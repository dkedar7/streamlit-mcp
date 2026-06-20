"""U5 tests — per-client session isolation."""

from __future__ import annotations

from pathlib import Path

from streamlit_mcp.runtime import AppTestRuntime
from streamlit_mcp.session import SessionManager

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


def _mgr():
    return SessionManager(lambda: AppTestRuntime(APP))


def test_each_session_isolated():
    """AE2: a state change in one session is invisible to another."""
    mgr = _mgr()
    a = mgr.get_or_create("a")
    b = mgr.get_or_create("b")
    a.set_widget("Name", "alpha")
    a.click("Save")
    assert a.snapshot().session_state["saves"] == 1
    # b is untouched
    bsnap = b.snapshot()
    assert bsnap.session_state["saves"] == 0
    assert {w.label: w.value for w in bsnap.widgets}["Name"] == "world"


def test_get_or_create_is_stable():
    mgr = _mgr()
    first = mgr.get_or_create("x")
    again = mgr.get_or_create("x")
    assert first is again
    assert mgr.count == 1


def test_new_session_starts_from_initial_state():
    mgr = _mgr()
    a = mgr.get_or_create("a")
    a.click("Save")
    assert a.snapshot().session_state["saves"] == 1
    b = mgr.get_or_create("b")
    assert b.snapshot().session_state["saves"] == 0


def test_dispose_frees_session():
    mgr = _mgr()
    mgr.get_or_create("a")
    assert "a" in mgr and mgr.count == 1
    assert mgr.dispose("a") is True
    assert "a" not in mgr and mgr.count == 0
    assert mgr.dispose("a") is False
