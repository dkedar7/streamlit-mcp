"""Opt-in semantic tools: expose a developer-chosen function as a clean MCP tool.

The auto path (widget tools) needs no app changes. When a developer wants higher-level,
named actions, they decorate a function with ``@mcp_tool`` and it is registered alongside
the auto-generated widget tools (origin R8). Names must not collide with the core tools or
with each other (AE5 reporting).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# Mirror of server.TOOL_NAMES, kept here to avoid a server<->decorator import cycle.
RESERVED_NAMES = (
    "list_widgets",
    "get_layout",
    "set_widget",
    "click",
    "read_output",
    "get_state",
)


@dataclass
class SemanticToolSpec:
    name: str
    description: str
    func: Callable


_REGISTRY: dict[str, SemanticToolSpec] = {}


def _origin(fn: Callable) -> tuple:
    """Identify a function by where it's defined, so the SAME decorated function re-running
    (the app module is executed once per session) is recognized as a re-registration rather
    than a name collision with a different tool."""
    code = getattr(fn, "__code__", None)
    return (getattr(fn, "__qualname__", getattr(fn, "__name__", "")),
            getattr(code, "co_filename", None),
            getattr(code, "co_firstlineno", None))


def mcp_tool(func: Optional[Callable] = None, *, name: Optional[str] = None,
             description: Optional[str] = None):
    """Register ``func`` as a semantic MCP tool. Usable bare or with arguments::

        @mcp_tool
        def reset(): ...

        @mcp_tool(name="reset_all", description="Reset everything")
        def reset(): ...
    """

    def register(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        if tool_name in RESERVED_NAMES:
            raise ValueError(f"semantic tool name {tool_name!r} collides with a core tool")
        existing = _REGISTRY.get(tool_name)
        if existing is not None:
            if _origin(existing.func) == _origin(fn):
                return fn  # same tool re-registered (app module ran again) — idempotent
            raise ValueError(f"semantic tool name {tool_name!r} is already registered")
        _REGISTRY[tool_name] = SemanticToolSpec(
            name=tool_name,
            description=description or (fn.__doc__ or "").strip(),
            func=fn,
        )
        return fn

    if func is not None:  # used as @mcp_tool
        return register(func)
    return register  # used as @mcp_tool(...)


def registered_semantic_tools() -> list[SemanticToolSpec]:
    return list(_REGISTRY.values())


def clear_registry() -> None:
    """Reset the registry (test isolation)."""
    _REGISTRY.clear()
