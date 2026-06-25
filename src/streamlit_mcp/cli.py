"""streamlit-mcp CLI — the human-first surface.

`serve` launches the MCP server; `inspect`/`call` let a human drive the app from the
terminal. All three go through the same engine an agent uses over MCP, so parity (R2)
holds by construction. Guardrail flags apply identically to the CLI and the server.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Optional

from . import __version__
from .engine import Engine
from .guardrails import Guardrails
from .runtime import AppTestRuntime


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_BARE_WARNING_FILTERED = False


def _drop_scriptruncontext_warning(record: logging.LogRecord) -> bool:
    # AppTest runs the app in bare mode (no ScriptRunContext), so Streamlit logs a noisy,
    # explicitly-ignorable "missing ScriptRunContext!" warning on every inspect/call/serve.
    # A filter (not setLevel) is used because Streamlit re-applies its own level to its
    # loggers when the runtime initializes, which would undo a level change.
    return "ScriptRunContext" not in record.getMessage()


def _quiet_bare_mode_warning() -> None:
    """Suppress Streamlit's bare-mode 'missing ScriptRunContext!' warning (idempotent)."""
    global _BARE_WARNING_FILTERED
    if _BARE_WARNING_FILTERED:
        return
    logging.getLogger(
        "streamlit.runtime.scriptrunner_utils.script_run_context"
    ).addFilter(_drop_scriptruncontext_warning)
    _BARE_WARNING_FILTERED = True


def build_guardrails(args: argparse.Namespace) -> Optional[Guardrails]:
    read_only = getattr(args, "read_only", False)
    allow = getattr(args, "allow", None)
    bearer = getattr(args, "bearer_token", None)
    if not read_only and not allow and not bearer:
        return None
    return Guardrails(
        read_only=read_only,
        allow_list=set(allow) if allow else None,
        bearer_token=bearer,
    )


def _engine(args: argparse.Namespace) -> Engine:
    rt = AppTestRuntime(args.app)
    rt.run()
    return Engine(rt, guard=build_guardrails(args), app_path=args.app)


def _parse_value(raw: str) -> Any:
    """Parse a --set value: JSON when possible (true/41/["a"]), else a plain string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _split_assignment(item: str) -> tuple[str, Any]:
    if "=" not in item:
        raise ValueError(f"--set expects 'identifier=value', got {item!r}")
    identifier, raw = item.split("=", 1)
    return identifier.strip(), _parse_value(raw)


# --------------------------------------------------------------------- commands
def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve
    try:
        serve(
            args.app,
            transport=args.transport,
            host=args.host,
            port=args.port,
            guard=build_guardrails(args),
        )
    except ValueError as e:  # fail-closed / bad transport -> clean message, not a traceback
        print(str(e), file=sys.stderr)
        return 1
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    eng = _engine(args)
    out = eng.get_layout() if args.layout else eng.list_widgets()
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    for w in out["widgets"]:
        flag = " [action]" if w.get("action") else ""
        print(f"  {w['kind']:<13} {w['identifier']:<14} = {w['value']!r}{flag}")
    if args.layout:
        for o in out.get("outputs", []):
            print(f"  [{o['kind']}] {o['text']}")
        state = out.get("session_state") or {}
        if state:
            print("  session_state:")
            for k, v in state.items():
                print(f"    {k} = {v!r}")
        unsupported = out.get("unsupported") or []
        if unsupported:
            print("  unsupported:")
            for u in unsupported:
                print(f"    {u['element']}: {u['reason']}")
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    try:
        eng = _engine(args)
        for item in args.set or []:
            ident, value = _split_assignment(item)
            eng.set_widget(ident, value)
        for ident in args.click or []:
            eng.click(ident)
        result = eng.get_state() if args.state else eng.read_output()
    except Exception as e:  # CLI: surface any failure as a clean message + exit 1
        print(str(e), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.state:
        for k, v in result.items():
            print(f"  {k} = {v!r}")
    else:
        for o in result.get("outputs", []):
            print(f"  [{o['kind']}] {o['text']}")
    return 0


# --------------------------------------------------------------------- parser
def _add_guard_flags(p: argparse.ArgumentParser, *, bearer: bool) -> None:
    p.add_argument("--read-only", dest="read_only", action="store_true",
                   help="block state-changing actions")
    p.add_argument("--allow", action="append",
                   help="allow-list a widget identifier (repeatable)")
    if bearer:
        p.add_argument("--bearer-token", dest="bearer_token",
                       help="require this bearer token on HTTP/SSE (enforced — 401 if the "
                            "Authorization header is missing or wrong; lets you bind a "
                            "non-loopback host)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="streamlit-mcp",
                                     description="Serve a Streamlit app as an MCP server.")
    parser.add_argument("--version", action="version",
                        version=f"streamlit-mcp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="serve an app over MCP")
    p_serve.add_argument("app")
    p_serve.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    _add_guard_flags(p_serve, bearer=True)
    p_serve.set_defaults(func=cmd_serve)

    p_inspect = sub.add_parser("inspect", help="print the app's widgets")
    p_inspect.add_argument("app")
    p_inspect.add_argument("--layout", action="store_true", help="full layout (outputs, state, unsupported)")
    p_inspect.add_argument("--json", action="store_true")
    _add_guard_flags(p_inspect, bearer=False)
    p_inspect.set_defaults(func=cmd_inspect)

    p_call = sub.add_parser("call", help="drive the app (same engine agents use)")
    p_call.add_argument("app")
    p_call.add_argument("--set", action="append", help="identifier=value (repeatable)")
    p_call.add_argument("--click", action="append", help="button identifier (repeatable)")
    p_call.add_argument("--read", action="store_true", help="print rendered output (default)")
    p_call.add_argument("--state", action="store_true", help="print session_state instead")
    p_call.add_argument("--json", action="store_true")
    _add_guard_flags(p_call, bearer=False)
    p_call.set_defaults(func=cmd_call)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    _force_utf8_output()
    _quiet_bare_mode_warning()
    args = build_parser().parse_args(argv)
    return args.func(args)


def _cli() -> None:
    """Console-script entry point. Propagates the exit code — entry-point shims call the
    target and ignore its return value, so returning from main() would always exit 0."""
    raise SystemExit(main())


if __name__ == "__main__":
    _cli()
