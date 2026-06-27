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
SEMANTIC_APP = str(Path(__file__).parent / "apps" / "semantic_app.py")


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


# --- 0.2.3 #14: an @mcp_tool in the served app file is exposed through serve ---
def test_app_file_tool_registered_by_warmup_and_exposed():
    import asyncio
    from streamlit_mcp.server import _load_app_semantic_tools, build_server
    _load_app_semantic_tools(SEMANTIC_APP)         # what serve() does before build_server
    assert "reset_all" in [t.name for t in registered_semantic_tools()]
    mcp = build_server(SEMANTIC_APP)
    names = sorted(t.name for t in asyncio.run(mcp.list_tools()))
    assert "reset_all" in names                    # exposed alongside the widget tools


def test_app_module_rerun_is_idempotent():
    # Per-session runs re-execute the app's @mcp_tool; that must not raise or set at.exception
    # (regression: previously every run after the first errored "already registered").
    from streamlit_mcp.runtime import AppTestRuntime
    AppTestRuntime(SEMANTIC_APP).run()             # first run registers
    rt = AppTestRuntime(SEMANTIC_APP)
    rt.run()                                       # second run must be clean
    assert rt.snapshot().exception is None
    assert len(registered_semantic_tools()) == 1   # still exactly one


def test_same_name_different_function_still_collides():
    # Idempotency is keyed on the function's origin, so a genuine duplicate name still raises.
    @mcp_tool(name="dup")
    def a():
        pass

    with pytest.raises(ValueError):
        @mcp_tool(name="dup")
        def b():
            pass
