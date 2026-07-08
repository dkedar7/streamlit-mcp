"""LLMAgent — an Anthropic tool-use loop that operates a Streamlit app via the six MCP tools.

The agent is handed the goal and the tools; it inspects (``list_widgets``/``read_output``/
``get_state``), acts (``set_widget``/``click``), and calls ``finish`` when done. This is the real
eval subject: point it at a model with ``--model`` and score how well that model can drive an app it
can only perceive as structured data.

The Anthropic client is injectable so the loop is unit-testable without an API key (see
``arena/tests/test_llm_agent.py``); in normal use it lazily constructs ``anthropic.Anthropic()``,
which reads ``ANTHROPIC_API_KEY`` from the environment.
"""

from __future__ import annotations

import json
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

_ANY = {"description": "the value to set, as the widget expects (string, number, boolean or array)"}

TOOLS = [
    {"name": "list_widgets", "description": "List the app's widgets and their current values.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_output", "description": "Read the app's rendered text output.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_state", "description": "Get the app's session_state.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "set_widget", "description": "Set a widget (by identifier) to a value; reruns the app.",
     "input_schema": {"type": "object",
                      "properties": {"identifier": {"type": "string"}, "value": _ANY},
                      "required": ["identifier", "value"]}},
    {"name": "click", "description": "Click a button (by identifier); reruns the app.",
     "input_schema": {"type": "object", "properties": {"identifier": {"type": "string"}},
                      "required": ["identifier"]}},
    {"name": "finish", "description": "Signal that the goal is complete.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
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


class LLMAgent(BaseAgent):
    def __init__(self, model: str = "claude-sonnet-4-6", *, client: Any = None,
                 max_iterations: Optional[int] = None, max_tokens: int = 1024):
        self.model = model
        self.name = f"llm:{model}"
        self._client = client
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens

    def _make_client(self):
        import anthropic  # lazy: scripted/random agents don't need the SDK installed
        return anthropic.Anthropic()

    def solve(self, env: ArenaEnv, goal: str) -> None:
        client = self._client or self._make_client()
        messages: list[dict] = [
            {"role": "user", "content": f"Goal: {goal}\n\nBegin by inspecting the app."}
        ]
        # bound total round-trips so a model that only reads (never acts) still terminates; reads
        # don't spend the action budget, so this is a separate ceiling.
        iterations = self.max_iterations or (env.max_steps * 2 + 5)
        for _ in range(iterations):
            resp = self._create(client, messages)
            messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                return  # model ended its turn without a tool call — it's done (or stuck)
            results, done = [], False
            for tu in tool_uses:
                if tu.name == "finish":
                    done = True
                    results.append(_result(tu.id, "ok"))
                    continue
                try:
                    out = _dispatch(env, tu.name, tu.input or {})
                except StepBudgetExceeded as e:
                    out, done = {"error": str(e)}, True
                results.append(_result(tu.id, json.dumps(out)[:4000]))
            messages.append({"role": "user", "content": results})
            if done:
                return

    def _create(self, client, messages):
        last = None
        for _ in range(3):  # brief retry, but only for TRANSIENT failures
            try:
                return client.messages.create(
                    model=self.model, system=SYSTEM, tools=TOOLS,
                    max_tokens=self.max_tokens, messages=messages,
                )
            except Exception as e:  # noqa: BLE001 - surfaced to the runner as a harness error
                last = e
                status = getattr(e, "status_code", None)
                # retry rate limits / 5xx / connection drops; never a 4xx (auth, billing, bad request)
                if not (status is None or status == 429 or status >= 500):
                    break
        raise last


def _result(tool_use_id: str, content: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
