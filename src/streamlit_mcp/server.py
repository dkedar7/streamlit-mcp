"""FastMCP server: exposes the engine's operations as MCP tools over stdio and HTTP/SSE.

The tool bodies are thin — they resolve the caller's session engine and dispatch to the
shared engine (so CLI parity holds). Per-client isolation routes through SessionManager,
keyed by a best-effort session id from the FastMCP context (the exact binding is the
plan's deferred open question; the isolation machinery itself is complete and tested).
"""

from __future__ import annotations

from typing import Any, Optional

from fastmcp import FastMCP

try:  # Context must be a module global so string annotations (PEP 563) resolve.
    from fastmcp import Context
except Exception:  # pragma: no cover - fastmcp without a Context export
    Context = None

from .engine import Engine
from .runtime import AppTestRuntime
from .session import SessionManager

TOOL_NAMES = (
    "list_widgets",
    "get_layout",
    "set_widget",
    "click",
    "read_output",
    "get_state",
)

VALID_TRANSPORTS = ("stdio", "http", "sse")


def core_tool_handlers(engine: Engine) -> dict:
    """The tool implementations bound to one engine — directly unit-testable."""
    return {
        "list_widgets": lambda: engine.list_widgets(),
        "get_layout": lambda: engine.get_layout(),
        "set_widget": lambda identifier, value: engine.set_widget(identifier, value),
        "click": lambda identifier: engine.click(identifier),
        "read_output": lambda: engine.read_output(),
        "get_state": lambda: engine.get_state(),
    }


def _derive_session_id(ctx: Any) -> str:
    if ctx is None:
        return "default"
    # NB: not request_id — it changes per request, which would spin up a fresh runtime
    # (and leak it) on every call instead of persisting one session per client.
    for attr in ("session_id", "client_id"):
        val = getattr(ctx, attr, None)
        if val:
            return str(val)
    return "default"


def _validate_transport(transport: str) -> str:
    if transport not in VALID_TRANSPORTS:
        raise ValueError(f"transport must be one of {VALID_TRANSPORTS}, got {transport!r}")
    return transport


def build_server(app_path: str, guard: Optional[Any] = None, app_name: str = "streamlit-mcp"):
    """Construct a FastMCP server exposing the core tools (+ any semantic tools)."""
    mcp = FastMCP(app_name)
    sessions = SessionManager(lambda: AppTestRuntime(app_path))

    def engine_for(ctx: Any) -> Engine:
        rt = sessions.get_or_create(_derive_session_id(ctx))
        return Engine(rt, guard=guard, app_path=app_path)

    if Context is not None:
        @mcp.tool
        def list_widgets(ctx: Context) -> dict:
            """List the app's widgets with their MCP tool schemas."""
            return engine_for(ctx).list_widgets()

        @mcp.tool
        def get_layout(ctx: Context) -> dict:
            """Full layout: widgets, rendered outputs, session_state, unsupported elements."""
            return engine_for(ctx).get_layout()

        @mcp.tool
        def set_widget(identifier: str, value: Any, ctx: Context) -> dict:
            """Set a widget (by key or label) to a value and rerun."""
            return engine_for(ctx).set_widget(identifier, value)

        @mcp.tool
        def click(identifier: str, ctx: Context) -> dict:
            """Click a button (by key or label) and rerun."""
            return engine_for(ctx).click(identifier)

        @mcp.tool
        def read_output(ctx: Context) -> dict:
            """Read the rendered element tree and session_state."""
            return engine_for(ctx).read_output()

        @mcp.tool
        def get_state(ctx: Context) -> dict:
            """Return the app's session_state."""
            return engine_for(ctx).get_state()
    else:  # pragma: no cover - fallback path
        @mcp.tool
        def list_widgets() -> dict:
            return engine_for(None).list_widgets()

        @mcp.tool
        def get_layout() -> dict:
            return engine_for(None).get_layout()

        @mcp.tool
        def set_widget(identifier: str, value: Any) -> dict:
            return engine_for(None).set_widget(identifier, value)

        @mcp.tool
        def click(identifier: str) -> dict:
            return engine_for(None).click(identifier)

        @mcp.tool
        def read_output() -> dict:
            return engine_for(None).read_output()

        @mcp.tool
        def get_state() -> dict:
            return engine_for(None).get_state()

    _register_semantic_tools(mcp)
    return mcp


def _register_semantic_tools(mcp) -> None:
    """Register any @mcp_tool-decorated semantic tools (U7). No-op if none/absent."""
    try:
        from .decorator import registered_semantic_tools
    except Exception:
        return
    for spec in registered_semantic_tools():
        mcp.tool(spec.func, name=spec.name, description=spec.description)


def serve(app_path: str, transport: str = "stdio", host: str = "127.0.0.1",
          port: int = 8000, guard: Optional[Any] = None) -> None:
    """Build and run the server on the chosen transport (blocking)."""
    _validate_transport(transport)
    if transport in ("http", "sse") and host not in ("127.0.0.1", "::1", "localhost"):
        # Bearer auth is not yet enforced on the transport (see CHANGELOG), so refuse to
        # expose an unauthenticated server beyond loopback. Fail closed.
        raise ValueError(
            f"Refusing to serve {transport} on non-loopback host {host!r}: HTTP bearer auth "
            "is not yet enforced. Bind to 127.0.0.1 for local agents, or use stdio."
        )
    mcp = build_server(app_path, guard=guard)
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=transport, host=host, port=port)
