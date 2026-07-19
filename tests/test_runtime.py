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
# --- read surface: an agent must see what the app says back, not just its prose ---
STATUS_APP = (
    "import streamlit as st\n"
    "import pandas as pd\n"
    "st.title('Report')\n"
    "name = st.text_input('Name', key='name')\n"
    "if st.button('Submit', key='go'):\n"
    "    if not name:\n"
    "        st.error('Name is required')\n"
    "    else:\n"
    "        st.success(f'Saved {name}')\n"
    "st.warning('unsaved changes')\n"
    "st.info('tip: use tab')\n"
    "st.metric('Total', '$4,210', delta='+8%')\n"
    "st.code('SELECT 1')\n"
    "st.json({'status': 'ok'})\n"
    "st.dataframe(pd.DataFrame({'item': ['taxi'], 'usd': [42]}))\n"
    "st.table(pd.DataFrame({'b': [2]}))\n"
)


def _outputs(rt):
    return {o.kind: o.text for o in rt.snapshot().outputs}


def test_status_outputs_are_visible():
    """The load-bearing gap: an agent that clicks submit could not see whether the app answered
    st.success or st.error — the outcome of its own action was invisible, leaving it to re-read
    widget values and guess. Only the prose kinds were reported."""
    rt = AppTestRuntime(script=STATUS_APP)
    rt.run()
    assert _outputs(rt).get("warning") == "unsaved changes"
    assert _outputs(rt).get("info") == "tip: use tab"

    rt.click("go")  # submit with an empty name -> the app reports an error
    assert _outputs(rt).get("error") == "Name is required"
    assert "success" not in _outputs(rt)

    rt.set_widget("name", "Kedar")
    rt.click("go")
    assert _outputs(rt).get("success") == "Saved Kedar"
    assert "error" not in _outputs(rt)


def test_data_outputs_are_visible():
    """Results an app reports as something other than prose."""
    rt = AppTestRuntime(script=STATUS_APP)
    rt.run()
    outs = _outputs(rt)
    assert outs.get("code") == "SELECT 1"
    assert outs.get("json") == '{"status": "ok"}'
    assert "taxi" in outs.get("dataframe", "") and "42" in outs.get("dataframe", "")
    assert "2" in outs.get("table", "")


def test_metric_keeps_its_label_and_delta():
    """A metric's `value` is the bare number, so stringifying it like the prose kinds would render
    a dashboard of metrics as a column of anonymous numbers."""
    rt = AppTestRuntime(script=STATUS_APP)
    rt.run()
    assert _outputs(rt)["metric"] == "Total: $4,210 (+8%)"


def test_metric_without_a_delta_omits_the_parenthetical():
    rt = AppTestRuntime(script="import streamlit as st\nst.metric('Users', 500)\n")
    rt.run()
    assert _outputs(rt)["metric"] == "Users: 500"


def test_large_output_is_truncated_with_a_marker():
    """st.json serializes a whole structure, so one output could otherwise crowd out the rest of
    the app in an agent's context."""
    from streamlit_mcp.runtime import MAX_OUTPUT_CHARS
    rt = AppTestRuntime(
        script="import streamlit as st\nst.json({'n': list(range(2000))})\n"
    )
    rt.run()
    text = _outputs(rt)["json"]
    assert len(text) > MAX_OUTPUT_CHARS          # the marker is appended past the cap
    assert len(text) < MAX_OUTPUT_CHARS + 100    # but the payload itself is capped
    assert "truncated" in text


def test_an_uncaught_crash_is_not_duplicated_into_outputs():
    """A crash renders as an `exception` element indistinguishable from a deliberate
    st.exception(e), and it already has its own dedicated surface — the snapshot's `exception`
    field (#27/#58/#64). One surface per fact."""
    rt = AppTestRuntime(
        script="import streamlit as st\nst.success('ok')\nraise ValueError('boom')\n"
    )
    rt.run()
    snap = rt.snapshot()
    assert snap.exception is not None and "boom" in snap.exception
    assert all(o.kind != "exception" for o in snap.outputs)
    assert any(o.kind == "success" for o in snap.outputs)  # prior outputs still reported
# --- #69: a deliberate st.exception(e) is not an app crash ---
def _exc(script):
    rt = AppTestRuntime(script=script)
    rt.run()
    return rt.snapshot().exception


def test_deliberate_st_exception_is_not_reported_as_a_crash():
    """st.exception(e) is the documented way to SHOW a handled error. Reporting it as a crash made
    an app that handles errors correctly look broken, and --strict failed CI for it (#69)."""
    assert _exc(
        "import streamlit as st\n"
        "try:\n"
        "    1 / 0\n"
        "except ZeroDivisionError as e:\n"
        "    st.exception(e)\n"
        "st.info('pick another file')\n"
    ) is None


def test_an_uncaught_crash_is_still_reported():
    """The guarantee #27/#58/#64 exist to give must not regress."""
    assert "boom" in _exc("import streamlit as st\nst.success('x')\nraise ValueError('boom')\n")


@pytest.mark.parametrize("script,where", [
    ("import streamlit as st\nraise ValueError('boom')\n", "first line, nothing rendered"),
    ("import streamlit as st\nwith st.sidebar:\n    raise ValueError('boom')\n", "inside sidebar"),
    ("import streamlit as st\nwith st.expander('e'):\n    raise ValueError('boom')\n", "in expander"),
])
def test_a_crash_is_reported_wherever_it_happens(script, where):
    """Streamlit renders an uncaught exception last even when it is raised inside a sidebar or an
    expander, which is what makes the position signal sound."""
    assert "boom" in (_exc(script) or ""), where


def test_a_deliberate_exception_as_the_final_statement_still_reports():
    """The residual ambiguity, asserted so it stays a deliberate choice rather than drifting: with
    nothing rendered after it, a deliberate st.exception(e) is indistinguishable from a crash, and
    the tie is broken toward reporting — missing a real crash is far worse than over-reporting."""
    assert _exc("import streamlit as st\nst.exception(ValueError('shown'))\n") == "shown"
