"""serve's startup status line (#201): the effective transport, URLs, auth and guardrails."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

APP = str(Path(__file__).parent / "apps" / "sample_app.py")
TOKEN = "SEKRET-T0KEN"


def _status(transport="stdio", host="127.0.0.1", port=8000, **guard):
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import startup_status
    return startup_status(APP, transport, host, port, Guardrails(**guard) if guard else None)


def test_stdio_without_flags_says_so():
    out = _status()
    assert str(Path(APP).resolve()) in out or str(Path(APP).absolute()) in out
    assert "stdio (local, unauthenticated)" in out
    assert "guardrails: none" in out


def test_a_token_on_stdio_is_called_out_as_having_no_effect():
    """#146: a token on stdio used to be silently ignored."""
    out = _status(bearer_token=TOKEN)
    assert "--bearer-token has no effect on stdio" in out
    assert TOKEN not in out


@pytest.mark.parametrize("transport,path", [("http", "mcp"), ("sse", "sse")])
def test_http_shows_connect_and_health_urls_and_auth(transport, path):
    out = _status(transport, port=8731, bearer_token=TOKEN)
    assert f"http://127.0.0.1:8731/{path}" in out
    assert "health: http://127.0.0.1:8731/health" in out
    assert "bearer token required" in out
    assert TOKEN not in out


def test_http_without_a_token_says_unauthenticated():
    assert "auth:       none (loopback only" in _status("http")


def test_guardrails_are_reported_from_the_guard_itself():
    out = _status(read_only=True, allow_list={"b", "a"}, redact_keys={"token"})
    assert "guardrails: read-only; allow-list: a, b; redacting: token" in out


def test_a_wildcard_bind_gets_a_connectable_url_like_config(tmp_path, capsys):
    from streamlit_mcp.cli import main
    out = _status("http", host="0.0.0.0", bearer_token=TOKEN)
    assert "http://127.0.0.1:8000/mcp" in out and "every interface" in out
    app = tmp_path / "app.py"
    app.write_text("")
    main(["config", str(app), "--transport", "http", "--host", "0.0.0.0", "--bearer-token", "T"])
    url = json.loads(capsys.readouterr().out)["mcpServers"]["streamlit-mcp"]["url"]
    assert url in out  # one URL helper, so config and serve can't disagree


def test_ipv6_hosts_are_bracketed():
    assert "http://[::1]:8000/sse" in _status("sse", host="::1")


def test_a_refused_bind_prints_no_status(capsys):
    """The line confirms what is about to run; a server that fails closed never gets one."""
    from streamlit_mcp.cli import main
    assert main(["serve", APP, "--transport", "http", "--host", "0.0.0.0"]) == 1
    err = capsys.readouterr().err
    assert "Refusing to serve" in err and "guardrails:" not in err


def test_real_stdio_serve_prints_status_on_stderr_and_keeps_stdout_clean(tmp_path):
    """Over a real stdio session: the status reaches stderr and the JSON-RPC channel still works."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    log = tmp_path / "stderr.log"

    async def session():
        with open(log, "w", encoding="utf-8") as errfile:
            transport = StdioTransport(
                sys.executable,
                ["-c", "import sys; from streamlit_mcp.cli import main; sys.exit(main())",
                 "serve", APP, "--read-only", "--redact", "token",
                 "--bearer-token", TOKEN],
                log_file=errfile)
            async with Client(transport) as c:
                return [t.name for t in await c.list_tools()]

    tools = asyncio.run(session())
    assert "get_state" in tools
    err = log.read_text(encoding="utf-8", errors="replace")
    assert "stdio (local, unauthenticated)" in err
    assert "--bearer-token has no effect on stdio" in err
    assert "guardrails: read-only; redacting: token" in err
    assert TOKEN not in err
