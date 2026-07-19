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
