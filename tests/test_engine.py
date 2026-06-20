"""U4 tests — the shared engine operations (also exercises AE1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit_mcp.engine import Engine, PermissionDenied
from streamlit_mcp.runtime import AppTestRuntime

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


def _engine(guard=None):
    rt = AppTestRuntime(APP)
    rt.run()
    return Engine(rt, guard=guard, app_path=APP)


class FakeGuard:
    def __init__(self, can_write=True, allowed=None, hide=None):
        self._can_write = can_write
        self._allowed = allowed
        self._hide = hide or set()

    def can_write(self):
        return self._can_write

    def is_allowed(self, identifier):
        return self._allowed is None or identifier in self._allowed

    def filter_widgets(self, models):
        return [m for m in models if m["identifier"] not in self._hide]


def test_list_widgets_has_schemas_for_all():
    out = _engine().list_widgets()
    assert len(out["widgets"]) == 10
    assert all("schema" in w for w in out["widgets"])


def test_set_widget_then_output_reflects():
    """AE1."""
    eng = _engine()
    result = eng.set_widget("Name", "agent")
    assert any("Hello, agent!" == o["text"] for o in result["outputs"])


def test_click_changes_state():
    """AE1."""
    eng = _engine()
    eng.click("Save")
    assert eng.get_state()["saves"] == 1


def test_get_layout_shape_includes_unsupported():
    out = _engine().get_layout()
    assert {"widgets", "outputs", "session_state"} <= set(out)
    assert out["unsupported"] == []  # sample app has none


def test_read_output_shape():
    out = _engine().read_output()
    assert "outputs" in out and "session_state" in out


def test_guard_read_only_blocks_writes():
    eng = _engine(FakeGuard(can_write=False))
    with pytest.raises(PermissionDenied):
        eng.set_widget("Name", "x")
    with pytest.raises(PermissionDenied):
        eng.click("Save")
    # reads still work
    assert len(eng.list_widgets()["widgets"]) == 10


def test_guard_allow_list_blocks_disallowed():
    eng = _engine(FakeGuard(allowed={"Name"}))
    eng.set_widget("Name", "ok")  # allowed
    with pytest.raises(PermissionDenied):
        eng.set_widget("Level", 3)  # not in allow-list


def test_guard_filters_visible_widgets():
    eng = _engine(FakeGuard(hide={"bio"}))  # hide by identifier (the key)
    labels = {w["label"] for w in eng.list_widgets()["widgets"]}
    assert "Bio" not in labels and "Name" in labels
