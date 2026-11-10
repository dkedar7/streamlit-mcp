"""FastMCP server: exposes the engine's operations as MCP tools over stdio and HTTP/SSE.

The tool bodies are thin — they resolve the caller's session engine and dispatch to the
shared engine (so CLI parity holds). Per-client isolation routes through SessionManager,
keyed by a best-effort session id from the FastMCP context (the exact binding is the
plan's deferred open question; the isolation machinery itself is complete and tested).
"""

from __future__ import annotations

import sys
from typing import Any, Optional

from fastmcp import FastMCP

try:  # Context must be a module global so string annotations (PEP 563) resolve.
    from fastmcp import Context
except Exception:  # pragma: no cover - fastmcp without a Context export
    Context = None

from . import __version__
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
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
# Addresses a server binds to that a client can't connect to (#195).
WILDCARD_HOSTS = ("0.0.0.0", "::", "")


def version_string() -> str:
    """Ours plus the installed Streamlit's: Streamlit's version governs AppTest's behaviour (the
    st.form change in #151 arrived with a Streamlit upgrade), so a bug report needs both (#167)."""
    try:
        from importlib.metadata import version
        return f"streamlit-mcp {__version__} (streamlit {version('streamlit')})"
    except Exception:
        return f"streamlit-mcp {__version__}"


def client_url(host: str, port: int, path: str) -> str:
    """The URL a client dials for a server bound to ``host``. A wildcard bind listens on every
    interface but isn't itself an address, so it maps to loopback. ``config`` and the ``serve``
    status line both use this, so they can't disagree about where the server is (#195, #201)."""
    if host in WILDCARD_HOSTS:
        host = "127.0.0.1"
    if ":" in host:  # an IPv6 literal must be bracketed in a URL
        host = f"[{host}]"
    return f"http://{host}:{port}/{path}"


def startup_status(app_path: str, transport: str, host: str, port: int,
                   guard: Optional[Any]) -> str:
    """What ``serve`` is about to run, with the guardrails and auth it actually applies (#201).

    Built from the same guard object the engine enforces, so it reports the effective posture
    rather than echoing the flags. Never includes the token itself."""
    import os
    token = getattr(guard, "bearer_token", None)
    lines = [f"{version_string()}  serving {os.path.abspath(app_path)}"]
    if transport == "stdio":
        lines.append("  transport:  stdio (local, unauthenticated)")
        if token:  # #146: the token is accepted but there's no HTTP request to check it on
            lines.append("  auth:       none: --bearer-token has no effect on stdio; "
                         "use --transport http or sse to require it")
        else:
            lines.append("  auth:       none (stdio is local)")
    else:
        url = client_url(host, port, "mcp" if transport == "http" else "sse")
        lines.append(f"  transport:  {transport}  {url}   health: {client_url(host, port, 'health')}")
        if host in WILDCARD_HOSTS:
            lines.append(f"              (bound to every interface ({host or 'all'}); remote "
                         "clients use this machine's address)")
        lines.append("  auth:       bearer token required" if token else
                     "  auth:       none (loopback only; pass --bearer-token to require one)")
    rails = []
    if guard is not None and getattr(guard, "read_only", False):
        rails.append("read-only")
    allow = getattr(guard, "allow_list", None)
    if allow is not None:
        rails.append(f"allow-list: {', '.join(sorted(allow)) or '(empty)'}")
    redact = getattr(guard, "redact_keys", None)
    if redact:
        rails.append(f"redacting: {', '.join(sorted(redact))}")
    lines.append(f"  guardrails: {'; '.join(rails) or 'none'}")
    return "\n".join(lines)


def bearer_auth(guard: Optional[Any]):
    """Build a FastMCP token verifier from a guard's bearer token, or None if unset.

    When a token is configured it is REQUIRED on every HTTP/SSE request: FastMCP's auth
    middleware returns 401 for a missing or wrong ``Authorization: Bearer <token>``. stdio
    is local and unauthenticated, so this is only wired up for the HTTP/SSE transports.
    """
    token = getattr(guard, "bearer_token", None)
    if not token:
        return None
    from fastmcp.server.auth import StaticTokenVerifier

    return StaticTokenVerifier({token: {"client_id": "streamlit-mcp", "scopes": []}})


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


def build_server(app_path: str, guard: Optional[Any] = None, app_name: str = "streamlit-mcp",
                 auth: Optional[Any] = None, session_ttl: Optional[float] = None,
                 max_sessions: Optional[int] = None):
    """Construct a FastMCP server exposing the core tools (+ any semantic tools).

    ``auth`` is a FastMCP auth provider (see ``bearer_auth``); when set, the HTTP/SSE
    transport requires a valid bearer token. It has no effect on stdio. ``session_ttl`` (idle
    seconds) and ``max_sessions`` bound how many per-client runtimes a long-running server keeps
    (see SessionManager); both default to no eviction.
    """
    # Without an explicit version FastMCP advertises its OWN in the initialize handshake, so a
    # client saw "3.4.5" where the CLI's --version said ours (#84).
    mcp = FastMCP(app_name, auth=auth, version=__version__)

    @mcp.custom_route("/health", methods=["GET"])
    @mcp.custom_route("/healthz", methods=["GET"])
    async def health(request):
        """Liveness for HTTP/SSE: answers 200 once the server accepts connections (#197). It sits
        outside the bearer check, which guards only the MCP endpoint, so a probe needs no token;
        it therefore says nothing a token would protect, not even the versions."""
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "ok", "server": "streamlit-mcp"})
    sessions = SessionManager(lambda: AppTestRuntime(app_path), ttl=session_ttl,
                              max_sessions=max_sessions)

    def dispatch(ctx: Any, op: str, *args: Any) -> dict:
        # The whole operation runs while holding the session, not just the lookup. A set_widget is
        # a write, a rerun and a read, and a second call on the same session must not run in
        # between (#178).
        with sessions.use(_derive_session_id(ctx)) as rt:
            return getattr(Engine(rt, guard=guard, app_path=app_path), op)(*args)

    if Context is not None:
        @mcp.tool
        def list_widgets(ctx: Context) -> dict:
            """List the app's widgets with their MCP tool schemas."""
            return dispatch(ctx, "list_widgets")

        @mcp.tool
        def get_layout(ctx: Context) -> dict:
            """Full layout: widgets, rendered outputs, session_state, unsupported elements."""
            return dispatch(ctx, "get_layout")

        @mcp.tool
        def set_widget(identifier: str, value: Any, ctx: Context) -> dict:
            """Set a widget (by key or label) to a value and rerun."""
            return dispatch(ctx, "set_widget", identifier, value)

        @mcp.tool
        def click(identifier: str, ctx: Context) -> dict:
            """Click a button (by key or label) and rerun."""
            return dispatch(ctx, "click", identifier)

        @mcp.tool
        def read_output(ctx: Context) -> dict:
            """Read the rendered element tree and session_state."""
            return dispatch(ctx, "read_output")

        @mcp.tool
        def get_state(ctx: Context) -> dict:
            """Return the app's session_state."""
            return dispatch(ctx, "get_state")
    else:  # pragma: no cover - fallback path
        @mcp.tool
        def list_widgets() -> dict:
            return dispatch(None, "list_widgets")

        @mcp.tool
        def get_layout() -> dict:
            return dispatch(None, "get_layout")

        @mcp.tool
        def set_widget(identifier: str, value: Any) -> dict:
            return dispatch(None, "set_widget", identifier, value)

        @mcp.tool
        def click(identifier: str) -> dict:
            return dispatch(None, "click", identifier)

        @mcp.tool
        def read_output() -> dict:
            return dispatch(None, "read_output")

        @mcp.tool
        def get_state() -> dict:
            return dispatch(None, "get_state")

    _register_semantic_tools(mcp, guard)
    return mcp


def _register_semantic_tools(mcp, guard: Optional[Any] = None) -> None:
    """Register any @mcp_tool-decorated semantic tools (U7). No-op if none/absent. Each is wrapped
    so the read-only / allow-list guard covers it too (#26) — otherwise a state-changing action
    would run despite --read-only."""
    try:
        from .decorator import registered_semantic_tools
    except Exception:
        return
    for spec in registered_semantic_tools():
        mcp.tool(_guarded_tool(spec, guard), name=spec.name, description=spec.description)


def _guarded_tool(spec, guard):
    import functools

    from .engine import guard_semantic_tool

    @functools.wraps(spec.func)  # preserves the signature so FastMCP builds the right schema
    def wrapped(*args, **kwargs):
        guard_semantic_tool(guard, spec.name)
        return spec.func(*args, **kwargs)

    return wrapped


def _load_app_semantic_tools(app_path: str) -> None:
    """Run the served app once so any ``@mcp_tool`` it defines registers BEFORE we build the
    server's tool list. The decorator only fires when the app module executes, and per-client
    sessions run it lazily — too late for ``build_server``/``_register_semantic_tools``. This
    makes the intuitive placement (decorate in your app file) actually expose the tool over the
    documented ``serve`` entrypoint. Best-effort: a broken app surfaces its error per session,
    so don't block serve startup here. (Re-registration on later session runs is idempotent.)"""
    try:
        AppTestRuntime(app_path).run()
    except Exception:
        pass


def check_bind(transport: str, host: str, has_token: bool) -> None:
    """Refuse an unauthenticated HTTP/SSE server beyond loopback. ``serve`` enforces it, and
    ``config`` applies the same check so it never prints a command ``serve`` would reject (#195)."""
    if transport in ("http", "sse") and not has_token and host not in LOOPBACK_HOSTS:
        # No token => requests are unauthenticated. Refuse to expose that beyond
        # loopback; bind 127.0.0.1, or pass a bearer token to gate a public host.
        raise ValueError(
            f"Refusing to serve {transport} on non-loopback host {host!r} without a "
            "bearer token: requests would be unauthenticated. Pass --bearer-token to bind "
            "a non-loopback host, or use 127.0.0.1 / stdio."
        )


def serve(app_path: str, transport: str = "stdio", host: str = "127.0.0.1",
          port: int = 8000, guard: Optional[Any] = None, session_ttl: Optional[float] = None,
          max_sessions: Optional[int] = None) -> None:
    """Build and run the server on the chosen transport (blocking)."""
    _validate_transport(transport)
    if session_ttl is not None and session_ttl <= 0:
        raise ValueError(f"--session-ttl must be a positive number of seconds, got {session_ttl}")
    if max_sessions is not None and max_sessions < 1:
        raise ValueError(f"--max-sessions must be at least 1, got {max_sessions}")
    auth = None
    if transport in ("http", "sse"):
        auth = bearer_auth(guard)
        check_bind(transport, host, auth is not None)
    _load_app_semantic_tools(app_path)
    mcp = build_server(app_path, guard=guard, auth=auth, session_ttl=session_ttl,
                       max_sessions=max_sessions)
    # stderr only: under stdio, stdout is the JSON-RPC channel.
    print(startup_status(app_path, transport, host, port, guard), file=sys.stderr, flush=True)
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=transport, host=host, port=port)
