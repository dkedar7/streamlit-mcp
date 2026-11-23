"""st.form fields are held until their form's submit click, as in a browser (#151, #130).

These tests matter most on the Streamlit versions CI doesn't pin. Run them with
``uv run --with streamlit==<latest> pytest tests/test_forms.py`` as well as on the locked version.
"""

from __future__ import annotations

import pytest

FORM_APP = (
    "import streamlit as st\n"
    "with st.form('signup'):\n"
    "    name = st.text_input('Name', key='name')\n"
    "    age = st.number_input('Age', 0, 120, 0, key='age')\n"
    "    submitted = st.form_submit_button('Submit')\n"
    "with st.form('other'):\n"
    "    city = st.text_input('City', key='city')\n"
    "    sent = st.form_submit_button('Send')\n"
    "st.text_input('Outside', key='out')\n"
    "if submitted:\n"
    "    st.success(f'Submitted name={name!r} age={age}')\n"
    "if sent:\n"
    "    st.info(f'Sent city={city!r}')\n"
)


@pytest.fixture
def eng():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=FORM_APP)
    rt.run()
    return Engine(rt)


def _texts(out, kind):
    return [o["text"] for o in out["outputs"] if o["kind"] == kind]


def test_set_fields_then_submit_runs_the_submit_with_the_set_values(eng):
    """The documented flow. On streamlit >= ~1.64 it submitted the DEFAULTS, because the rerun
    after each set discarded the pending form value (#151)."""
    eng.set_widget("name", "Kedar")
    eng.set_widget("age", 30)
    out = eng.click("Submit")
    assert _texts(out, "success") == ["Submitted name='Kedar' age=30"]
    assert eng.get_state()["name"] == "Kedar" and eng.get_state()["age"] == 30


def test_a_form_field_does_not_commit_before_submit(eng):
    """A browser user can't put a form value into session_state without submitting (#130)."""
    eng.set_widget("name", "Kedar")
    assert eng.get_state()["name"] == ""
    assert not _texts(eng.read_output(), "success")


def test_a_held_value_is_visible_on_the_widget(eng):
    """The field shows what was typed into it, as it would in a browser, though it isn't committed."""
    eng.set_widget("name", "Kedar")
    widgets = {w["identifier"]: w for w in eng.list_widgets()["widgets"]}
    assert widgets["name"]["value"] == "Kedar"


def test_a_held_value_survives_other_interactions_before_submit(eng):
    eng.set_widget("name", "Kedar")
    eng.set_widget("out", "elsewhere")   # a rerun that is not this form's submit
    eng.set_widget("city", "Paris")      # a field in a different form
    eng.click("Send")                    # submitting the OTHER form
    out = eng.click("Submit")
    assert _texts(out, "success") == ["Submitted name='Kedar' age=0"]


def test_submitting_one_form_does_not_send_another_forms_fields(eng):
    eng.set_widget("name", "Kedar")
    eng.set_widget("city", "Paris")
    out = eng.click("Send")
    assert _texts(out, "info") == ["Sent city='Paris'"]
    assert eng.get_state()["name"] == ""  # still held for its own form
    assert _texts(eng.click("Submit"), "success") == ["Submitted name='Kedar' age=0"]


def test_an_invalid_form_value_is_still_rejected_up_front(eng):
    from streamlit_mcp.runtime import RuntimeError_
    with pytest.raises(RuntimeError_, match="out of range"):
        eng.set_widget("age", 500)
    with pytest.raises(RuntimeError_, match="truncated"):
        eng.set_widget("age", 30.5)
    assert _texts(eng.click("Submit"), "success") == ["Submitted name='' age=0"]


def test_a_second_submit_does_not_resend_the_held_values(eng):
    eng.set_widget("name", "Kedar")
    eng.click("Submit")
    eng.set_widget("name", "Other")
    assert _texts(eng.click("Submit"), "success") == ["Submitted name='Other' age=0"]


def test_cli_documented_form_flow(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "form.py"
    app.write_text(FORM_APP)
    rc = main(["call", str(app), "--set", "name=Kedar", "--set", "age=30",
               "--click", "Submit", "--read"])
    assert rc == 0
    assert "[success] Submitted name='Kedar' age=30" in capsys.readouterr().out


CLEAR_APP = (
    "import streamlit as st\n"
    "import pandas as pd\n"
    "st.selectbox('Mode', ['a', 'b'], key='mode')\n"
    "with st.form('signup', clear_on_submit=True):\n"
    "    nm = st.text_input('FormName', key='fn')\n"
    "    qty = st.number_input('FormQty', 0, 10, 0, key='fq')\n"
    "    tags = st.multiselect('Tags', ['x', 'y'], default=['x'], key='tg')\n"
    "    opt = st.text_input('Opt', value=None, key='op')\n"
    "    grid = st.data_editor(pd.DataFrame({'n': [1]}), key='grid')\n"
    "    submitted = st.form_submit_button('Submit')\n"
    "with st.form('keep'):\n"
    "    kept = st.text_input('Keep', key='kp')\n"
    "    st.form_submit_button('Save')\n"
    "if submitted:\n"
    "    st.success(f'Got {nm!r} qty={qty} tags={tags} opt={opt!r} n={int(grid.n.sum())}')\n"
)
CLEARED = {"fn": "", "fq": 0, "tg": ["x"], "op": None}


@pytest.fixture
def clear_eng():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=CLEAR_APP)
    rt.run()
    return Engine(rt)


def _values(eng):
    return {w["identifier"]: w["value"] for w in eng.list_widgets()["widgets"]
            if w["kind"] != "button"}


def _fill_and_submit(eng):
    for k, v in (("fn", "zoe"), ("fq", 3), ("tg", ["y"]), ("op", "hi"), ("kp", "kept")):
        eng.set_widget(k, v)
    eng.set_widget("grid", {"edit": {"0": {"n": 5}}})
    eng.click("Save")
    return eng.click("Submit")


def test_clear_on_submit_fields_read_as_their_defaults_after_the_submit(clear_eng):
    """A browser resets a clear_on_submit form's fields after Submit; AppTest has no frontend,
    so they kept the submitted values on every later read (#225). The submit itself still sees
    the submitted values."""
    out = _fill_and_submit(clear_eng)
    assert _texts(out, "success") == ["Got 'zoe' qty=3 tags=['y'] opt='hi' n=5"]
    values = _values(clear_eng)
    assert {k: values[k] for k in CLEARED} == CLEARED
    assert values["grid"]["edits"] == {"edited_rows": {}, "added_rows": [], "deleted_rows": []}
    assert values["kp"] == "kept"  # a form without clear_on_submit keeps its values


def test_session_state_keeps_the_submitted_values_until_the_next_submit(clear_eng):
    """As in a browser: the cleared values are unsubmitted form values, so session_state still
    holds what was submitted, and a rerun outside the form doesn't change either."""
    out = _fill_and_submit(clear_eng)
    assert {k: out["session_state"][k] for k in CLEARED} == {
        "fn": "zoe", "fq": 3, "tg": ["y"], "op": "hi"}
    clear_eng.set_widget("mode", "b")
    values = _values(clear_eng)
    assert {k: values[k] for k in CLEARED} == CLEARED


def test_the_next_submit_sends_the_cleared_defaults_unless_fields_are_set_again(clear_eng):
    _fill_and_submit(clear_eng)
    assert _texts(clear_eng.click("Submit"), "success") == ["Got '' qty=0 tags=['x'] opt=None n=1"]
    clear_eng.set_widget("fn", "amy")
    assert _texts(clear_eng.click("Submit"), "success") == [
        "Got 'amy' qty=0 tags=['x'] opt=None n=1"]
