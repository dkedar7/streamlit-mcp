"""An advertised identifier resolves to the widget it was advertised for (#186)."""

from __future__ import annotations

import pytest

SEARCH_APP = (
    "import streamlit as st\n"
    "st.text_input('Search', key='q')\n"
    "if st.button('Search'):\n"
    "    st.success(f\"Searched for: {st.session_state.get('q')!r}\")\n"
    "else:\n"
    "    st.info('no search yet')\n"
)


@pytest.fixture
def eng():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=SEARCH_APP)
    rt.run()
    return Engine(rt)


def test_every_advertised_identifier_resolves_to_its_own_widget(eng):
    widgets = eng.list_widgets()["widgets"]
    assert [(w["kind"], w["identifier"]) for w in widgets] == [("text_input", "q"), ("button", "Search")]
    for w in widgets:
        assert eng.rt._find(w["identifier"])[0] == w["kind"]


def test_clicking_the_advertised_button_clicks_it(eng):
    """It raised "'Search' is not a button": the keyed text_input's label shadowed it."""
    eng.set_widget("q", "hello")
    out = eng.click("Search")
    assert [o["text"] for o in out["outputs"] if o["kind"] == "success"] == ["Searched for: 'hello'"]


def test_setting_the_button_handle_does_not_silently_write_the_text_input(eng):
    from streamlit_mcp.runtime import RuntimeError_
    with pytest.raises(RuntimeError_):
        eng.set_widget("Search", "hello")
    assert eng.get_state()["q"] == ""


def test_a_keyed_widget_is_still_reachable_by_its_label_when_nothing_else_claims_it():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script="import streamlit as st\nst.text_input('Name', key='n')\n")
    rt.run()
    eng = Engine(rt)
    eng.set_widget("Name", "Kedar")
    assert eng.get_state()["n"] == "Kedar"


def test_cli_clicks_the_advertised_button(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "search.py"
    app.write_text(SEARCH_APP)
    assert main(["call", str(app), "--set", "q=hello", "--click", "Search", "--read"]) == 0
    assert "[success] Searched for: 'hello'" in capsys.readouterr().out
