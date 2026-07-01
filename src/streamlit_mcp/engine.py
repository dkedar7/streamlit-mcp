"""The shared engine: the operations both the MCP server and the CLI call.

Putting the operations here is what makes human↔agent parity (origin R2) structural —
the CLI and the MCP tools dispatch to the same code, not two parallel implementations.
An optional ``guard`` (origin R11, built in U8) is consulted for read-only mode and the
allow-list; when absent, the engine is permissive.
"""

from __future__ import annotations

from typing import Any, Optional

from .elements import (
    detect_unsupported,
    outputs_to_list,
    serialize_value,
    tool_schema_for,
    widgets_to_models,
)
from .runtime import Runtime


class PermissionDenied(Exception):
    """Raised when a guard blocks a write or a disallowed widget."""


def guard_semantic_tool(guard: Optional[Any], name: str) -> None:
    """Read-only / allow-list gate for ``@mcp_tool`` semantic tools, so guardrails cover the
    higher-level action surface too (origin: dogfood #26). Fail closed: since we can't know
    whether a tool mutates, read-only blocks any tool, and an allow-list blocks a tool whose
    name isn't listed (``--allow <tool-name>`` opts one back in)."""
    if guard is None:
        return
    if hasattr(guard, "can_write") and not guard.can_write():
        raise PermissionDenied("server is in read-only mode")
    if hasattr(guard, "is_allowed") and not guard.is_allowed(name):
        raise PermissionDenied(f"tool {name!r} is not in the allow-list")


class Engine:
    def __init__(self, runtime: Runtime, guard: Optional[Any] = None,
                 app_path: Optional[str] = None):
        self.rt = runtime
        self.guard = guard
        self.app_path = app_path

    # --------------------------------------------------------------- reads
    def list_widgets(self) -> dict:
        models = self._visible_widgets()
        for m in models:
            m["schema"] = tool_schema_for(m)
        return {"widgets": models}

    def get_layout(self) -> dict:
        snap = self.rt.snapshot()
        out: dict = {
            "widgets": self._visible_widgets(snap),
            "outputs": outputs_to_list(snap),
            "session_state": serialize_value(snap.session_state),
        }
        if self.app_path:
            out["unsupported"] = detect_unsupported(self.app_path)
        if snap.exception:
            out["exception"] = snap.exception
        return out

    def read_output(self) -> dict:
        snap = self.rt.snapshot()
        return {
            "outputs": outputs_to_list(snap),
            "session_state": serialize_value(snap.session_state),
            "exception": snap.exception,
        }

    def get_state(self) -> dict:
        return serialize_value(self.rt.snapshot().session_state)

    # --------------------------------------------------------------- writes
    def set_widget(self, identifier: str, value: Any) -> dict:
        self._guard_write()
        self._guard_allowed(identifier)
        self.rt.set_widget(identifier, value)
        return self.read_output()

    def click(self, identifier: str) -> dict:
        self._guard_write()
        self._guard_allowed(identifier)
        self.rt.click(identifier)
        return self.read_output()

    # --------------------------------------------------------------- guards
    def _visible_widgets(self, snapshot=None) -> list[dict]:
        snap = snapshot if snapshot is not None else self.rt.snapshot()
        models = widgets_to_models(snap)
        if self.guard is not None and hasattr(self.guard, "filter_widgets"):
            models = self.guard.filter_widgets(models)
        return models

    def _guard_write(self) -> None:
        if self.guard is not None and not self.guard.can_write():
            raise PermissionDenied("server is in read-only mode")

    def _guard_allowed(self, identifier: str) -> None:
        if self.guard is None or self.guard.is_allowed(identifier):
            return
        # The caller may pass a key or a label; allow if the resolved widget's identifier
        # OR label is allow-listed (consistent with filter_widgets, which matches both).
        for m in widgets_to_models(self.rt.snapshot()):
            if identifier in (m["identifier"], m["label"]):
                if self.guard.is_allowed(m["identifier"]) or (
                    m["label"] and self.guard.is_allowed(m["label"])
                ):
                    return
                break
        raise PermissionDenied(f"widget {identifier!r} is not in the allow-list")
