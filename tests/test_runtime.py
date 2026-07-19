"""U2 tests — AppTestRuntime drives the sample app headlessly."""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit_mcp.runtime import (
    SUPPORTED_KINDS,
    AppTestRuntime,
    RuntimeSnapshot,
    WidgetNotFound,
)

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


@pytest.fixture()
def rt():
    r = AppTestRuntime(APP)
    r.run()
    return r


def test_introspect_lists_sample_widgets(rt):
    snap = rt.snapshot()
    kinds = {w.kind for w in snap.widgets}
    assert kinds <= set(SUPPORTED_KINDS) and len(kinds) == 10  # sample_app's ten, all supported
    # constraints captured where applicable
    sb = next(w for w in snap.widgets if w.kind == "selectbox")
    assert sb.options == ["red", "green", "blue"]


def test_set_text_and_read_output(rt):
    """AE1: set a widget, read output reflects it."""
    rt.set_widget("Name", "agent")
    snap = rt.snapshot()
    assert any("Hello, agent!" == o.text for o in snap.outputs)


def test_click_button_accumulates_state(rt):
    """AE1: click a button, session_state changes; reruns accumulate."""
    rt.click("Save")
    rt.click("Save")
    assert rt.snapshot().session_state["saves"] == 2


def test_set_various_widget_kinds(rt):
    rt.set_widget("Level", 8)            # slider
    rt.set_widget("Color", "green")       # selectbox
    rt.set_widget("Agree", True)          # checkbox
    rt.set_widget("Plan", "pro")          # radio
    rt.set_widget("Tags", ["a", "b"])     # multiselect
    rt.set_widget("Age", 41)              # number_input
    snap = rt.snapshot()
    vals = {w.label: w.value for w in snap.widgets}
    assert vals["Level"] == 8
    assert vals["Color"] == "green"
    assert vals["Agree"] is True
    assert vals["Plan"] == "pro"
    assert vals["Age"] == 41


def test_set_date_from_iso_string(rt):
    rt.set_widget("When", "2026-03-04")
    val = {w.label: w.value for w in rt.snapshot().widgets}["When"]
    assert str(val) == "2026-03-04"


def test_resolve_by_key(rt):
    rt.set_widget("name", "viakey")  # key, not label
    assert any("Hello, viakey!" == o.text for o in rt.snapshot().outputs)


def test_unknown_identifier_raises(rt):
    with pytest.raises(WidgetNotFound):
        rt.set_widget("Nonexistent", "x")


def test_clicking_non_button_raises(rt):
    with pytest.raises(Exception):
        rt.click("Name")


def test_setting_button_raises(rt):
    with pytest.raises(Exception):
        rt.set_widget("Save", "x")


def test_runtime_satisfies_protocol(rt):
    from streamlit_mcp.runtime import Runtime
    assert isinstance(rt, Runtime)


def test_app_exception_surfaced():
    rt = AppTestRuntime(script="import streamlit as st\nraise ValueError('boom')\n")
    rt.run()
    snap = rt.snapshot()
    assert snap.exception is not None and "boom" in snap.exception


def test_snapshot_shape(rt):
    snap = rt.snapshot()
    assert isinstance(snap, RuntimeSnapshot)
    assert snap.session_state.get("saves") == 0  # initial


# --- pills / segmented_control / feedback: promoted from `unsupported` to driven ---
BUTTON_GROUP_APP = (
    "import streamlit as st\n"
    "st.pills('P1', ['a', 'b', 'c'], key='p1')\n"
    "st.pills('P2', ['x', 'y', 'z'], selection_mode='multi', default=['x'], key='p2')\n"
    "st.segmented_control('S1', ['one', 'two'], default='one', key='s1')\n"
    "st.feedback('stars', key='fb')\n"
    "st.feedback('thumbs', key='fb2')\n"
)


@pytest.fixture
def bg():
    rt = AppTestRuntime(script=BUTTON_GROUP_APP)
    rt.run()
    return rt


def test_pills_and_segmented_control_are_distinguished(bg):
    """Both arrive in the element tree under the shared protobuf name `button_group`, which is why
    they were once written off as undetectable. AppTest's typed accessors tell them apart, so an
    agent sees the kind it would write in the app — never `button_group`."""
    kinds = [w.kind for w in bg.snapshot().widgets]
    assert kinds.count("pills") == 2
    assert kinds.count("segmented_control") == 1
    assert kinds.count("feedback") == 2
    assert "button_group" not in kinds


def test_button_group_widgets_are_drivable(bg):
    bg.set_widget("p1", "b")
    bg.set_widget("p2", ["y", "z"])
    bg.set_widget("s1", "two")
    bg.set_widget("fb", 4)
    state = bg.snapshot().session_state
    assert state["p1"] == "b" and state["p2"] == ["y", "z"]
    assert state["s1"] == "two" and state["fb"] == 4


def test_a_bare_option_selects_just_that_one_on_a_multi_select(bg):
    """The multiselect convention, applied to a multi-mode pills."""
    bg.set_widget("p2", "y")
    assert bg.snapshot().session_state["p2"] == ["y"]


@pytest.mark.parametrize("identifier,value", [
    ("p1", "zzz"),            # invalid option on a single-select -> AppTest reverts silently
    ("p1", ["a", "b"]),       # a list sent to a single-select -> reverts silently
    ("p2", ["y", "NOPE"]),    # invalid member -> silently DROPPED, landing a partial write
    ("s1", "three"),
])
def test_bad_button_group_writes_are_rejected_atomically(bg, identifier, value):
    """AppTest neither raises nor keeps a bad option on these: a single-select reverts and a
    multi-select silently drops the offending member, so set_widget would report success on a write
    that never landed (or half-landed). The #10/#12/#33 silent-revert family, caught up front."""
    from streamlit_mcp.runtime import RuntimeError_
    before = bg.snapshot().session_state[identifier]
    with pytest.raises(RuntimeError_):
        bg.set_widget(identifier, value)
    assert bg.snapshot().session_state[identifier] == before  # atomic: prior value intact


@pytest.mark.parametrize("identifier,value", [
    ("fb", 5),        # a 5-star widget has indices 0-4
    ("fb", 99),
    ("fb", -1),
    ("fb2", 3),       # thumbs is a 2-point scale
    ("fb", "three"),  # non-integer raises inside the rerun and poisons the session
    ("fb", 2.5),
])
def test_bad_feedback_ratings_are_rejected_atomically(bg, identifier, value):
    """Feedback is the worst-behaved of these: AppTest neither raises nor reverts an out-of-range
    rating — it STORES it, so a bad value becomes the app's state with no signal at all."""
    from streamlit_mcp.runtime import RuntimeError_
    before = bg.snapshot().session_state[identifier]
    with pytest.raises(RuntimeError_):
        bg.set_widget(identifier, value)
    assert bg.snapshot().session_state[identifier] == before


def test_feedback_scale_comes_from_the_widget_style(bg):
    """thumbs is a 2-point scale and stars a 5-point one; the count is not exposed on the element,
    so it is read off the widget proto's enum by name."""
    widgets = {w.key: w for w in bg.snapshot().widgets}
    assert (widgets["fb"].min, widgets["fb"].max) == (0, 4)     # stars
    assert (widgets["fb2"].min, widgets["fb2"].max) == (0, 1)   # thumbs


def test_multi_select_is_cleared_with_an_empty_list(bg):
    """`[]` is a multi-select's no-selection state, and it round-trips — unlike null, which AppTest
    silently ignores on these widgets."""
    bg.set_widget("p2", [])
    assert bg.snapshot().session_state["p2"] == []


def test_clearing_a_selection_to_null_is_rejected_not_silently_ignored(bg):
    """AppTest's set_value(None) is a silent no-op on a pills/segmented_control, so accepting null
    would report success on a write that never happened. Rejected atomically, with a message that
    says what is actually true rather than the placeholder story."""
    from streamlit_mcp.runtime import RuntimeError_
    bg.set_widget("p1", "b")
    with pytest.raises(RuntimeError_, match="no way to deselect"):
        bg.set_widget("p1", None)
    assert bg.snapshot().session_state["p1"] == "b"  # untouched


def test_every_advertised_button_group_value_round_trips(bg):
    """The round-trip guarantee for the new kinds: whatever list_widgets advertises can be sent
    straight back to set_widget."""
    from streamlit_mcp.engine import Engine
    eng = Engine(bg)
    bg.set_widget("p1", "b")
    bg.set_widget("fb", 3)
    for w in eng.list_widgets()["widgets"]:
        eng.set_widget(w["identifier"], w["value"])  # must not raise
