"""ArenaEnv — the environment an agent drives: one Streamlit app, via streamlit-mcp.

It exposes exactly the six core MCP tools (``list_widgets`` / ``get_layout`` / ``read_output`` /
``get_state`` / ``set_widget`` / ``click``) so every episode dogfoods the same surface an agent
uses over MCP. It records a trace of every tool call and enforces a step budget on *actions*
(reads are free).

Crucially, it distinguishes an **expected tool error** (a bad value rejected, a widget not found, a
guardrail block — normal signals an agent reacts to) from an **unexpected exception**, which is
almost certainly a streamlit-mcp bug. The latter is flagged as a ``crash`` in the trace, and the
report surfaces it — so running the benchmark is itself a structured stress test of streamlit-mcp.

v1 dispatches to the in-process ``Engine`` (the exact code the MCP server calls — the parity
guarantee makes this representative). A real ``fastmcp`` stdio client can slot in behind the same
interface later for full-stack fidelity (Milestone 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from streamlit_mcp.engine import Engine, PermissionDenied
from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_

# Errors that are a normal part of driving an app — the agent should see them and adapt, and they
# are NOT streamlit-mcp defects. WidgetNotFound subclasses RuntimeError_, so it is covered.
EXPECTED_TOOL_ERRORS = (RuntimeError_, PermissionDenied, ValueError)


@dataclass
class Step:
    tool: str
    args: dict
    ok: bool
    error: Optional[str] = None
    crash: bool = False  # an UNEXPECTED exception from streamlit-mcp — a candidate bug


class StepBudgetExceeded(Exception):
    """Raised when an agent spends more actions than the task's budget allows."""


class ArenaEnv:
    """One episode's worth of interaction with a single app."""

    ACTION_TOOLS = ("set_widget", "click")

    def __init__(self, app_path: str, *, guard: Any = None, max_steps: int = 30):
        self._rt = AppTestRuntime(app_path)
        self._rt.run()
        self._eng = Engine(self._rt, guard=guard, app_path=app_path)
        self.max_steps = max_steps
        self.trace: list[Step] = []

    @property
    def steps(self) -> int:
        """Actions spent (reads don't count against the budget)."""
        return sum(1 for s in self.trace if s.tool in self.ACTION_TOOLS)

    @property
    def crashed(self) -> bool:
        return any(s.crash for s in self.trace)

    # ------------------------------------------------------------- read tools (free)
    def list_widgets(self) -> dict:
        return self._record("list_widgets", {}, self._eng.list_widgets)

    def get_layout(self) -> dict:
        return self._record("get_layout", {}, self._eng.get_layout)

    def read_output(self) -> dict:
        return self._record("read_output", {}, self._eng.read_output)

    def get_state(self) -> dict:
        return self._record("get_state", {}, self._eng.get_state)

    # ------------------------------------------------------------- act tools (cost a step)
    def set_widget(self, identifier: str, value: Any) -> dict:
        self._charge()
        return self._record(
            "set_widget", {"identifier": identifier, "value": value},
            lambda: self._eng.set_widget(identifier, value),
        )

    def click(self, identifier: str) -> dict:
        self._charge()
        return self._record("click", {"identifier": identifier},
                            lambda: self._eng.click(identifier))

    # ------------------------------------------------------------- internals
    def _charge(self) -> None:
        if self.steps >= self.max_steps:
            raise StepBudgetExceeded(f"exceeded action budget of {self.max_steps}")

    def _record(self, tool: str, args: dict, fn: Callable[[], Any]) -> dict:
        try:
            result = fn()
            self.trace.append(Step(tool, args, ok=True))
            return result
        except EXPECTED_TOOL_ERRORS as e:
            # normal: surface to the agent as data, not a raise
            self.trace.append(Step(tool, args, ok=False, error=f"{type(e).__name__}: {e}"))
            return {"error": str(e)}
        except Exception as e:  # unexpected -> a streamlit-mcp bug candidate; flag it loudly
            self.trace.append(
                Step(tool, args, ok=False, error=f"{type(e).__name__}: {e}", crash=True)
            )
            return {"error": f"internal error: {e}"}
