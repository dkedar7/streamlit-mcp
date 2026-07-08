"""McpEnv — the same benchmark environment, but over the REAL MCP transport.

Where ``ArenaEnv`` dispatches to the in-process ``Engine``, ``McpEnv`` spawns ``streamlit-mcp serve
<app>`` as a subprocess and drives it through a ``fastmcp`` stdio client — exercising the whole
product surface: JSON-RPC over pipes, FastMCP's server, the tool schemas as actually exposed, and
error propagation. Pick it with ``--transport mcp``.

Crash detection is subtler here than in-process: FastMCP wraps *every* server-side exception into a
``ToolError``, so a clean rejection (bad value, guardrail block) and a genuine library crash both
arrive as errors. We classify by message — anything that doesn't look like one of streamlit-mcp's
known clean errors is flagged as a ``crash`` (a bug candidate), the same signal the Engine env gets
for free.

The ``fastmcp`` client is async; the agents and runner are sync, so the env owns an event loop and
marshals each call through it (sequential request/response, so a loop-per-call is fine).
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .env import Step, StepBudgetExceeded

# A ToolError whose message matches one of these is a normal rejection an agent adapts to (not a
# defect). Anything else — a raw Python exception text, an "internal error" — is a crash candidate.
_CLEAN_ERROR = re.compile("|".join([
    r"no widget matching",
    r"is not a valid",              # option / number / date / time / color / boolean
    r"are not valid options",
    r"is out of range",
    r"is a button; use click",
    r"is not a button",
    r"read-only mode",
    r"not in the allow-list",
    r"failed and was rolled back",
]), re.IGNORECASE)


def _serve_command() -> str:
    exe = shutil.which("streamlit-mcp")
    if exe:
        return exe
    name = "streamlit-mcp.exe" if sys.platform == "win32" else "streamlit-mcp"
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("streamlit-mcp executable not found on PATH")


class McpEnv:
    ACTION_TOOLS = ("set_widget", "click")

    def __init__(self, app_path: str, *, server_args=(), max_steps: int = 30):
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        self.max_steps = max_steps
        self.trace: list[Step] = []
        self._loop = asyncio.new_event_loop()
        transport = StdioTransport(
            command=_serve_command(),
            args=["serve", str(app_path), *server_args],
            keep_alive=False,  # tear the subprocess down on exit (avoids a GC-time loop warning)
        )
        self._client = Client(transport)
        self._loop.run_until_complete(self._client.__aenter__())

    @property
    def steps(self) -> int:
        return sum(1 for s in self.trace if s.tool in self.ACTION_TOOLS)

    @property
    def crashed(self) -> bool:
        return any(s.crash for s in self.trace)

    # ------------------------------------------------------------- read tools (free)
    def list_widgets(self) -> dict:
        return self._call("list_widgets", {})

    def get_layout(self) -> dict:
        return self._call("get_layout", {})

    def read_output(self) -> dict:
        return self._call("read_output", {})

    def get_state(self) -> dict:
        return self._call("get_state", {})

    # ------------------------------------------------------------- act tools (cost a step)
    def set_widget(self, identifier: Any, value: Any) -> dict:
        self._charge()
        return self._call("set_widget", {"identifier": identifier, "value": value})

    def click(self, identifier: Any) -> dict:
        self._charge()
        return self._call("click", {"identifier": identifier})

    # ------------------------------------------------------------- generic (semantic tools / tests)
    def tool_names(self) -> list[str]:
        tools = self._loop.run_until_complete(self._client.list_tools())
        return sorted(t.name for t in tools)

    def invoke(self, name: str, args: dict) -> dict:
        """Call any server tool by name (e.g. an @mcp_tool). Recorded in the trace, no step charge."""
        return self._call(name, args)

    # ------------------------------------------------------------- internals
    def _charge(self) -> None:
        if self.steps >= self.max_steps:
            raise StepBudgetExceeded(f"exceeded action budget of {self.max_steps}")

    def _call(self, name: str, args: dict) -> dict:
        from fastmcp.exceptions import ToolError

        try:
            result = self._loop.run_until_complete(self._client.call_tool(name, args))
        except ToolError as e:
            msg = str(e)
            crash = _CLEAN_ERROR.search(msg) is None  # not a known clean error -> bug candidate
            self.trace.append(Step(name, args, ok=False, error=msg, crash=crash))
            return {"error": msg}
        data = getattr(result, "data", None)
        if data is None:
            data = getattr(result, "structured_content", None)
        self.trace.append(Step(name, args, ok=True))
        return data if data is not None else {}

    def close(self) -> None:
        try:
            self._loop.run_until_complete(self._client.__aexit__(None, None, None))
        except Exception:
            pass
        finally:
            self._client = None
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()
