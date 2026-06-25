"""Tests for the code-review fixes applied before the 0.1.0 release."""

from __future__ import annotations

from pathlib import Path

import pytest

APP = str(Path(__file__).parent / "apps" / "sample_app.py")
UNSUPPORTED_APP = str(Path(__file__).parent / "apps" / "unsupported_app.py")


# --- P1: text widget + JSON-looking value no longer crashes the CLI ---
def test_text_widget_json_value_does_not_crash(capsys):
    from streamlit_mcp.cli import main
    rc = main(["call", APP, "--set", "Name=true", "--read"])
    assert rc == 0
    assert "Hello, True!" in capsys.readouterr().out


# --- P1: allow-list resolves label<->key consistently ---
def test_allow_list_label_permits_key_identifier():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(APP)
    rt.run()
    eng = Engine(rt, guard=Guardrails(allow_list={"Name"}), app_path=APP)  # by label
    # setting by the key 'name' (what list_widgets returns as identifier) must be allowed
    out = eng.set_widget("name", "ok")
    assert any("Hello, ok!" == o["text"] for o in out["outputs"])


# --- P2: session_state is serialized JSON-safe (dates -> ISO strings) ---
def test_get_state_serializes_dates():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(APP)
    rt.run()
    eng = Engine(rt, app_path=APP)
    assert eng.get_state()["when"] == "2026-01-01"


# --- security: serve fails closed on non-loopback HTTP ---
def test_serve_refuses_nonloopback_http():
    from streamlit_mcp.server import serve
    with pytest.raises(ValueError):
        serve(APP, transport="http", host="0.0.0.0")


# --- P2: session id derivation ignores request_id ---
def test_derive_session_id_ignores_request_id():
    from streamlit_mcp.server import _derive_session_id

    class OnlyRequestId:
        request_id = "r1"

    class HasClientId:
        client_id = "c1"

    assert _derive_session_id(OnlyRequestId()) == "default"
    assert _derive_session_id(HasClientId()) == "c1"


# --- public API surface ---
def test_public_api_exports():
    import streamlit_mcp
    from streamlit_mcp import (  # noqa: F401
        AppTestRuntime,
        Engine,
        Guardrails,
        build_server,
        mcp_tool,
        serve,
    )
    for name in ("Engine", "Guardrails", "serve", "AppTestRuntime", "mcp_tool"):
        assert name in streamlit_mcp.__all__


# --- inspect --layout renders outputs in non-json mode ---
def test_inspect_layout_prints_outputs(capsys):
    from streamlit_mcp.cli import main
    assert main(["inspect", APP, "--layout"]) == 0
    out = capsys.readouterr().out
    assert "Hello, world!" in out and "session_state:" in out


# --- 0.1.1 #1: inspect --layout (text) reports unsupported elements, never drops them ---
def test_inspect_layout_text_reports_unsupported(capsys):
    """The text layout must list unsupported elements, matching --json and MCP get_layout
    (the "reported explicitly, never silently dropped" guarantee / human<->agent parity)."""
    from streamlit_mcp.cli import main
    assert main(["inspect", UNSUPPORTED_APP, "--layout"]) == 0
    out = capsys.readouterr().out
    assert "unsupported:" in out
    assert "file_uploader" in out


# --- 0.1.1 #2: top-level --version prints the version and exits 0 ---
def test_version_flag(capsys):
    import pytest
    from streamlit_mcp import __version__
    from streamlit_mcp.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


# --- 0.1.1 #2: the bare-mode "missing ScriptRunContext!" warning is filtered out ---
def test_bare_mode_scriptruncontext_warning_filtered():
    import logging
    from streamlit_mcp.cli import _quiet_bare_mode_warning
    _quiet_bare_mode_warning()
    lg = logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context")
    rec = lg.makeRecord(
        lg.name, logging.WARNING, __file__, 0,
        "Thread 'MainThread': missing ScriptRunContext! This warning can be ignored "
        "when running in bare mode.", None, None,
    )
    assert lg.filter(rec) is False  # at least one filter rejects the warning


# --- 0.2.0 #7: bearer auth is ENFORCED on HTTP/SSE ---
def _dummy_build_server(monkeypatch):
    from streamlit_mcp import server

    class DummyMCP:
        def run(self, *a, **k):  # don't block the test on a real server
            pass

    monkeypatch.setattr(server, "build_server", lambda *a, **k: DummyMCP())
    return server


def test_bearer_auth_builds_verifier_only_when_token_set():
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import bearer_auth
    assert bearer_auth(None) is None
    assert bearer_auth(Guardrails()) is None
    v = bearer_auth(Guardrails(bearer_token="SEKRET"))
    assert v is not None and hasattr(v, "verify_token")


def test_serve_allows_nonloopback_when_token_set(monkeypatch):
    # With a token, auth gates access, so a public host is permitted (must not raise).
    from streamlit_mcp.guardrails import Guardrails
    server = _dummy_build_server(monkeypatch)
    server.serve(APP, transport="http", host="0.0.0.0",
                 guard=Guardrails(bearer_token="SEKRET"))


def test_http_transport_requires_bearer_token():
    """Real enforcement: the HTTP app returns 401 without a valid token, and not-401 with it."""
    from starlette.testclient import TestClient
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import bearer_auth, build_server

    guard = Guardrails(bearer_token="SEKRET")
    mcp = build_server(APP, guard=guard, auth=bearer_auth(guard))
    app = mcp.http_app(path="/mcp", json_response=True)
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}}
    hdr = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}
    with TestClient(app) as client:
        assert client.post("/mcp", json=body, headers=hdr).status_code == 401
        ok = client.post("/mcp", json=body,
                         headers={**hdr, "Authorization": "Bearer SEKRET"})
        assert ok.status_code != 401


# --- 0.2.1 #10: a failed set_widget must not poison a long-lived session ---
POISON_APP = (
    "import streamlit as st\n"
    "n = st.number_input('Count', min_value=0, max_value=10, value=1)\n"
    "c = st.selectbox('Color', ['red', 'green', 'blue'])\n"
    "st.markdown(f'Count={n} Color={c}')\n"
)


def _markdown(rt):
    return [o.text for o in rt.snapshot().outputs if o.kind == "markdown"]


def test_invalid_selectbox_option_does_not_poison_session():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=POISON_APP)
    rt.run()
    rt.set_widget("Count", 5)
    with pytest.raises(RuntimeError_):
        rt.set_widget("Color", "purple")            # invalid -> clean error, nothing applied
    # session is NOT poisoned: an unrelated widget still sets cleanly, Color unchanged
    rt.set_widget("Count", 8)
    assert "Count=8 Color=red" in _markdown(rt)
    rt.set_widget("Color", "blue")                  # valid choice still works
    assert "Count=8 Color=blue" in _markdown(rt)


def test_invalid_multiselect_option_rejected_cleanly():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    script = ("import streamlit as st\n"
              "t = st.multiselect('Tags', ['a', 'b', 'c'])\n"
              "st.markdown('tags=' + ','.join(t))\n")
    rt = AppTestRuntime(script=script)
    rt.run()
    with pytest.raises(RuntimeError_):
        rt.set_widget("Tags", ["a", "z"])           # 'z' not offered
    rt.set_widget("Tags", ["a", "b"])               # session still usable
    assert "tags=a,b" in _markdown(rt)


def test_engine_set_widget_invalid_option_keeps_session_usable():
    # The MCP tools dispatch to Engine.set_widget; a bad option must not brick the session.
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=POISON_APP)
    rt.run()
    eng = Engine(rt)
    with pytest.raises(RuntimeError_):
        eng.set_widget("Color", "purple")
    out = eng.set_widget("Count", 8)                # must succeed (not poisoned)
    assert any(o["text"] == "Count=8 Color=red" for o in out["outputs"])
