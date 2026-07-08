"""LLMAgent — an LLM tool-use loop that operates a Streamlit app via the six MCP tools.

The agent is handed the goal and the tools; it inspects (``list_widgets``/``read_output``/
``get_state``), acts (``set_widget``/``click``), and calls ``finish`` when done. This is the real
eval subject: point it at a model and score how well that model drives an app it can only perceive
as structured data.

The provider-specific bits (request shape, tool schema, how tool calls are parsed) live in a small
``Backend``; the loop is provider-agnostic. Two backends ship:

- ``AnthropicBackend`` — the Anthropic Messages API (``ANTHROPIC_API_KEY``).
- ``OpenAIBackend`` — any OpenAI-compatible endpoint; used for **OpenRouter**
  (``OPENROUTER_API_KEY``), which proxies Claude, GPT, Gemini, Llama, … behind one API.

The client is injectable, so the loop is unit-tested with a fake client (no network); see
``arena/tests/test_llm_agent.py``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .agents import BaseAgent
from .env import ArenaEnv, StepBudgetExceeded

SYSTEM = (
    "You operate a Streamlit app entirely through tools — you cannot see the screen. Accomplish "
    "the user's goal by inspecting and driving the app.\n\n"
    "Tools:\n"
    "- list_widgets: the widgets, each with \"identifier\" (use this exact string to target it), "
    "\"kind\", \"value\", and \"constraints\" (e.g. options for a selectbox, min/max for a slider).\n"
    "- read_output: the app's rendered text.\n"
    "- get_state: the app's session_state.\n"
    "- set_widget(identifier, value): set a widget's value; the app reruns.\n"
    "- click(identifier): press a button; the app reruns.\n"
    "- finish: call when the goal is fully accomplished.\n\n"
    "Each set_widget/click reruns the app and may REVEAL NEW WIDGETS, so re-inspect with "
    "list_widgets after acting when the layout might have changed. Use identifiers exactly as "
    "returned. Work efficiently and call finish when the goal is met."
)

# One neutral tool list; each backend renders it into its provider's schema. `value` accepts any
# scalar or a list (multiselect), with items:{} so strict validators accept the array branch.
_VALUE = {"type": ["string", "number", "integer", "boolean", "array"], "items": {},
          "description": "the value to set, as the widget expects"}
_EMPTY = {"type": "object", "properties": {}, "required": []}
_TOOLS = [
    ("list_widgets", "List the app's widgets and their current values.", _EMPTY),
    ("read_output", "Read the app's rendered text output.", _EMPTY),
    ("get_state", "Get the app's session_state.", _EMPTY),
    ("set_widget", "Set a widget (by identifier) to a value; reruns the app.",
     {"type": "object", "properties": {"identifier": {"type": "string"}, "value": _VALUE},
      "required": ["identifier", "value"]}),
    ("click", "Click a button (by identifier); reruns the app.",
     {"type": "object", "properties": {"identifier": {"type": "string"}}, "required": ["identifier"]}),
    ("finish", "Signal that the goal is complete.", _EMPTY),
]


def _dispatch(env: ArenaEnv, name: str, args: dict) -> Any:
    if name == "list_widgets":
        return env.list_widgets()
    if name == "read_output":
        return env.read_output()
    if name == "get_state":
        return env.get_state()
    if name == "set_widget":
        return env.set_widget(args.get("identifier"), args.get("value"))
    if name == "click":
        return env.click(args.get("identifier"))
    raise ValueError(f"unknown tool {name!r}")


def _goal_message(goal: str) -> dict:
    return {"role": "user", "content": f"Goal: {goal}\n\nBegin by inspecting the app."}


class AnthropicBackend:
    """Anthropic Messages API."""

    def __init__(self, model: str, *, client: Any = None, max_tokens: int = 1024):
        self.model, self._client, self.max_tokens = model, client, max_tokens
        self.tools = [{"name": n, "description": d, "input_schema": s} for n, d, s in _TOOLS]

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def initial_messages(self, goal: str) -> list:
        return [_goal_message(goal)]

    def create(self, messages: list):
        return self.client.messages.create(model=self.model, system=SYSTEM, tools=self.tools,
                                            max_tokens=self.max_tokens, messages=messages)

    def tool_calls(self, resp) -> list[tuple]:
        return [(b.id, b.name, b.input or {})
                for b in resp.content if getattr(b, "type", None) == "tool_use"]

    def extend(self, messages: list, resp, results: list[tuple]) -> None:
        messages.append({"role": "assistant", "content": resp.content})
        if results:
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": i, "content": c} for i, c in results]})


class OpenAIBackend:
    """Any OpenAI-compatible Chat Completions endpoint. ``provider='openrouter'`` targets OpenRouter."""

    OPENROUTER_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str, *, client: Any = None, max_tokens: int = 1024,
                 provider: str = "openrouter"):
        self.model, self._client, self.max_tokens = model, client, max_tokens
        self.provider = provider
        self.tools = [{"type": "function", "function": {"name": n, "description": d, "parameters": s}}
                      for n, d, s in _TOOLS]

    @property
    def client(self):
        if self._client is None:
            import openai
            if self.provider == "openrouter":
                self._client = openai.OpenAI(base_url=self.OPENROUTER_URL,
                                             api_key=os.environ["OPENROUTER_API_KEY"])
            else:
                self._client = openai.OpenAI()
        return self._client

    def initial_messages(self, goal: str) -> list:
        return [{"role": "system", "content": SYSTEM}, _goal_message(goal)]

    def create(self, messages: list):
        return self.client.chat.completions.create(model=self.model, messages=messages,
                                                    tools=self.tools, max_tokens=self.max_tokens)

    def tool_calls(self, resp) -> list[tuple]:
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append((tc.id, tc.function.name, args))
        return calls

    def extend(self, messages: list, resp, results: list[tuple]) -> None:
        msg = resp.choices[0].message
        assistant: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        messages.append(assistant)
        for i, c in results:
            messages.append({"role": "tool", "tool_call_id": i, "content": c})


class LLMAgent(BaseAgent):
    def __init__(self, model: str = "claude-sonnet-4-6", *, provider: str = "anthropic",
                 backend: Any = None, client: Any = None, max_iterations: Optional[int] = None,
                 max_tokens: int = 1024):
        self.model = model
        self.provider = provider
        self.name = f"llm:{model}" if provider == "anthropic" else f"llm:{provider}:{model}"
        self._backend = backend
        self._client = client
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens

    def _make_backend(self):
        if self._backend is not None:
            return self._backend
        if self.provider == "anthropic":
            return AnthropicBackend(self.model, client=self._client, max_tokens=self.max_tokens)
        if self.provider in ("openrouter", "openai"):
            return OpenAIBackend(self.model, client=self._client, max_tokens=self.max_tokens,
                                 provider=self.provider)
        raise ValueError(f"unknown provider {self.provider!r} (anthropic | openrouter | openai)")

    def solve(self, env: ArenaEnv, goal: str) -> None:
        backend = self._make_backend()
        messages = backend.initial_messages(goal)
        iterations = self.max_iterations or (env.max_steps * 2 + 5)
        for _ in range(iterations):
            resp = self._create(backend, messages)
            calls = backend.tool_calls(resp)
            if not calls:
                return  # the model ended its turn without a tool call — done (or stuck)
            results, done = [], False
            for call_id, name, args in calls:
                if name == "finish":
                    done = True
                    results.append((call_id, "ok"))
                    continue
                try:
                    out = _dispatch(env, name, args)
                except StepBudgetExceeded as e:
                    out, done = {"error": str(e)}, True
                results.append((call_id, json.dumps(out)[:4000]))
            backend.extend(messages, resp, results)
            if done:
                return

    def _create(self, backend, messages):
        last = None
        for _ in range(3):  # brief retry, but only for TRANSIENT failures
            try:
                return backend.create(messages)
            except Exception as e:  # noqa: BLE001 - surfaced to the runner as a harness error
                last = e
                status = getattr(e, "status_code", None)
                if not (status is None or status == 429 or status >= 500):
                    break  # 4xx (auth, billing, bad request) — don't hammer
        raise last
