"""U7 tests — the @mcp_tool semantic-tool decorator and its registration path."""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit_mcp.decorator import (
    clear_registry,
    mcp_tool,
    registered_semantic_tools,
)

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


@pytest.fixture(autouse=True)
def _clean():
    clear_registry()
    yield
    clear_registry()


def test_bare_decorator_uses_name_and_doc():
    @mcp_tool
    def reset():
        """Reset the app."""
        return "done"

    tools = registered_semantic_tools()
    assert len(tools) == 1
    assert tools[0].name == "reset"
    assert tools[0].description == "Reset the app."
    assert reset() == "done"  # still callable


def test_decorator_with_overrides():
    @mcp_tool(name="reset_all", description="Reset everything")
    def reset():
        return 1

    spec = registered_semantic_tools()[0]
    assert spec.name == "reset_all" and spec.description == "Reset everything"


def test_collision_with_core_tool_reported():
    with pytest.raises(ValueError):
        @mcp_tool(name="set_widget")
        def x():
            pass


def test_collision_between_semantic_tools_reported():
    @mcp_tool(name="dup")
    def a():
        pass

    with pytest.raises(ValueError):
        @mcp_tool(name="dup")
        def b():
            pass


def test_register_semantic_tools_path():
    """AE5: a decorated tool is registered alongside the core tools."""
    @mcp_tool(name="reset_all", description="Reset everything")
    def reset():
        return 1

    calls = []

    class FakeMCP:
        def tool(self, func, name=None, description=None):
            calls.append((name, description, func))

    from streamlit_mcp.server import _register_semantic_tools
    _register_semantic_tools(FakeMCP())
    assert calls and calls[0][0] == "reset_all"
    assert calls[0][2]() == 1


def test_build_server_with_semantic_tool_smoke():
    @mcp_tool(name="reset_all")
    def reset():
        return 1

    from fastmcp import FastMCP
    from streamlit_mcp.server import build_server
    mcp = build_server(APP)  # exercises the real mcp.tool(func, name=...) registration
    assert isinstance(mcp, FastMCP)
