"""U4 tests — server tool handlers, session-id derivation, transport validation, build."""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit_mcp.engine import Engine
from streamlit_mcp.runtime import AppTestRuntime
from streamlit_mcp.server import (
    TOOL_NAMES,
    _derive_session_id,
    _validate_transport,
    build_server,
    core_tool_handlers,
)

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


def _engine():
    rt = AppTestRuntime(APP)
    rt.run()
    return Engine(rt, app_path=APP)


def test_handlers_cover_all_tool_names():
    handlers = core_tool_handlers(_engine())
    assert set(handlers) == set(TOOL_NAMES)


def test_handlers_drive_app():
    """AE1 via the registered tool handlers."""
    handlers = core_tool_handlers(_engine())
    out = handlers["set_widget"]("Name", "agent")
    assert any("Hello, agent!" == o["text"] for o in out["outputs"])
    handlers["click"]("Save")
    assert handlers["get_state"]()["saves"] == 1
    assert len(handlers["list_widgets"]()["widgets"]) == 10


def test_derive_session_id():
    class Ctx:
        session_id = "abc"
    assert _derive_session_id(Ctx()) == "abc"
    assert _derive_session_id(None) == "default"
    assert _derive_session_id(object()) == "default"


def test_validate_transport():
    for t in ("stdio", "http", "sse"):
        assert _validate_transport(t) == t
    with pytest.raises(ValueError):
        _validate_transport("carrier-pigeon")


def test_build_server_smoke():
    from fastmcp import FastMCP
    mcp = build_server(APP)
    assert isinstance(mcp, FastMCP)
