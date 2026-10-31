"""Regression tests for the 0.8.0 batch from the nightly dogfood run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


# --- one numeric write guard for number_input AND slider (#158/#161/#164/#169/#79/#98) ---
# Each hole was found on one kind and then again on the other, so every case runs on both.
NUMERIC_APP = (
    "import streamlit as st\n"
    "st.number_input('Age', min_value=0, max_value=120, value=30, key='age')\n"
    "st.number_input('Price', min_value=0.0, max_value=100.0, value=10.0, key='price')\n"
    "st.number_input('Qty', value=None, step=1, key='qty')\n"
    "st.slider('Vol', 0, 100, 50, key='vol')\n"
    "st.slider('Mix', 0.0, 1.0, 0.5, key='mix')\n"
    "st.slider('Band', 0, 100, (20, 80), key='band')\n"
)


def _numeric_rt():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=NUMERIC_APP)
    rt.run()
    return rt


@pytest.mark.parametrize("ident,bad", [
    ("age", True), ("age", False), ("price", True), ("vol", True), ("mix", False),  # #164/#169
    ("band", [True, 80]),
])
def test_a_boolean_is_not_a_number(ident, bad):
    """bool is an int subclass, so True slipped every guard and was stored as 1 — while "maybe",
    which violates the same {"type":"number"} schema, was rejected."""
    from streamlit_mcp.runtime import RuntimeError_
    rt = _numeric_rt()
    prior = rt.snapshot().session_state[ident]
    with pytest.raises(RuntimeError_, match="not a valid number"):
        rt.set_widget(ident, bad)
    assert rt.snapshot().session_state[ident] == prior


@pytest.mark.parametrize("ident,bad", [
    ("price", "nan"), ("price", float("nan")), ("mix", "nan"), ("age", float("inf")),
    ("band", [float("nan"), 80]),
])
def test_a_non_finite_value_is_rejected_not_silently_reset(ident, bad):
    """NaN fails every comparison, so it passed the range check and AppTest reset the widget to
    its DEFAULT — clobbering the prior valid value while reporting success (#158)."""
    from streamlit_mcp.runtime import RuntimeError_
    rt = _numeric_rt()
    rt.set_widget(ident, {"band": [30, 70], "mix": 0.7}.get(ident, 50))
    prior = rt.snapshot().session_state[ident]
    with pytest.raises(RuntimeError_, match="finite"):
        rt.set_widget(ident, bad)
    assert rt.snapshot().session_state[ident] == prior  # the prior set survives, not the default


@pytest.mark.parametrize("ident,bad", [("qty", 30.5), ("vol", 55.5), ("band", [20, 80.5])])
def test_a_fractional_value_on_an_integer_widget_is_rejected(ident, bad):
    """Integer-ness is the proto's declared type, so an EMPTY value=None integer input — which
    has no current value to infer it from — is guarded too (#161), and so is a slider (#79)."""
    from streamlit_mcp.runtime import RuntimeError_
    rt = _numeric_rt()
    prior = rt.snapshot().session_state[ident]
    with pytest.raises(RuntimeError_, match="truncated"):
        rt.set_widget(ident, bad)
    assert rt.snapshot().session_state[ident] == prior


def test_valid_numeric_sets_still_land():
    rt = _numeric_rt()
    for ident, value, stored in [("qty", 30, 30), ("qty", 30.0, 30), ("vol", "55", 55),
                                 ("mix", "0.25", 0.25), ("band", [10, 90], (10, 90)),
                                 ("price", 99.5, 99.5)]:
        rt.set_widget(ident, value)
        assert rt.snapshot().session_state[ident] == stored, ident


def test_a_slider_string_that_is_not_a_number_gets_a_clean_message():
    """A slider skipped the string coercion number_input had, so AppTest raised a raw Python
    "could not convert string to float" from inside the rerun."""
    from streamlit_mcp.runtime import RuntimeError_
    rt = _numeric_rt()
    with pytest.raises(RuntimeError_, match="'maybe' is not a valid number for slider"):
        rt.set_widget("vol", "maybe")


def test_integer_widgets_advertise_integer_and_integer_bounds():
    """AppTest reports min/max as floats even on an integer widget, so an int number_input
    advertised {"type": "number", "minimum": 0.0} for a value it then truncates (#98)."""
    from streamlit_mcp.engine import Engine
    widgets = {w["identifier"]: w for w in Engine(_numeric_rt()).list_widgets()["widgets"]}

    def value(ident):
        return widgets[ident]["schema"]["properties"]["value"]

    assert value("age") == {"type": "integer", "minimum": 0, "maximum": 120}
    assert isinstance(value("age")["minimum"], int)
    assert value("qty")["type"] == ["integer", "null"]  # the empty int input, too (#161)
    assert value("vol")["type"] == "integer"
    assert value("band")["items"]["type"] == "integer"
    assert value("price")["type"] == "number" and value("mix")["type"] == "number"
    assert widgets["age"]["constraints"]["integer"] is True
    assert "integer" not in widgets["price"]["constraints"]


def test_every_advertised_numeric_value_still_round_trips():
    from streamlit_mcp.engine import Engine
    eng = Engine(_numeric_rt())
    for w in eng.list_widgets()["widgets"]:
        eng.set_widget(w["identifier"], w["value"])


def test_cli_rejects_a_boolean_number(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "num.py"
    app.write_text(NUMERIC_APP)
    assert main(["call", str(app), "--set", "vol=55", "--set", "vol=true", "--state"]) == 1
    assert "not a valid number" in capsys.readouterr().err


# --- #160: a disabled widget says so on the read surface, before a write fails ---
def test_disabled_widgets_are_advertised():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.text_input('Locked', value='x', disabled=True)\n"
        "st.button('Go', disabled=True)\n"
        "st.text_input('Open')\n"
    ))
    rt.run()
    eng = Engine(rt)
    for surface in (eng.list_widgets(), eng.get_layout()):
        flags = {w["identifier"]: w["disabled"] for w in surface["widgets"]}
        assert flags == {"Locked": True, "Go": True, "Open": False}


# --- #174: a metric's delta colour is its verdict, and an agent must be able to read it ---
def test_metric_delta_reports_good_bad_or_nothing_for_neutral():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.metric('Revenue', '$4,210', '+8%')\n"
        "st.metric('Error rate', '5%', '+2%', delta_color='inverse')\n"
        "st.metric('Latency', '120ms', '-3ms', delta_color='off')\n"
        "st.metric('Churn', '3%', '-1%', delta_color='inverse')\n"
    ))
    rt.run()
    assert [o.text for o in rt.snapshot().outputs] == [
        "Revenue: $4,210 (+8%, good)",
        "Error rate: 5% (+2%, bad)",      # read identically to a good delta before
        "Latency: 120ms (-3ms)",
        "Churn: 3% (-1%, good)",          # inverse + down = good
    ]


# --- #170: st.toast — the app's answer to an action — is captured as an output ---
def test_toast_is_reported_as_an_output():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "if st.button('Save', key='save'):\n"
        "    st.toast('Saved!')\n"
        "st.write('page')\n"
    ))
    rt.run()
    eng = Engine(rt)
    assert all(o["kind"] != "toast" for o in eng.read_output()["outputs"])
    outputs = eng.click("save")["outputs"]
    assert {"kind": "toast", "text": "Saved!"} in outputs
    assert outputs[-1]["kind"] == "toast"  # floats over the page: after the document-order outputs


# --- #172: a widget revealed by an earlier --set is parsed against ITS kind/options ---
COND_APP = (
    "import streamlit as st\n"
    "if st.checkbox('Show', key='show'):\n"
    "    st.text_input('Comment', key='comment')\n"
    "    st.selectbox('Env', ['true', 'false'], key='env')\n"
)


def test_cli_set_on_a_widget_revealed_by_an_earlier_set(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "cond.py"
    app.write_text(COND_APP)
    rc = main(["call", str(app), "--set", "show=true", "--set", "comment=true",
               "--set", "env=false", "--state", "--json"])
    assert rc == 0
    state = json.loads(capsys.readouterr().out)
    assert state["comment"] == "true"  # was 'True' — JSON-parsed, then str()-ified
    assert state["env"] == "false"     # was rejected: pre-parsed to the bool False


# --- #84/#167: our version in the MCP handshake; Streamlit's on --version ---
def test_server_advertises_streamlit_mcps_version_not_fastmcps():
    import asyncio

    from fastmcp import Client

    from streamlit_mcp import __version__
    from streamlit_mcp.server import build_server

    async def handshake():
        async with Client(build_server(APP)) as client:
            return client.initialize_result.serverInfo.version

    assert asyncio.run(handshake()) == __version__


def test_version_flag_names_the_installed_streamlit(capsys):
    import streamlit

    from streamlit_mcp.cli import main
    with pytest.raises(SystemExit):
        main(["--version"])
    assert f"streamlit {streamlit.__version__}" in capsys.readouterr().out
