"""Tests for the code-review fixes applied before the 0.1.0 release."""

from __future__ import annotations

from pathlib import Path

import pytest

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


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
