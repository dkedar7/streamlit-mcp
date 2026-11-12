"""st.data_editor is a drivable widget (#204), via Streamlit's own edit-state protocol."""

from __future__ import annotations

import asyncio
import json

import pytest

CART_APP = (
    "import streamlit as st, pandas as pd\n"
    "edited = st.data_editor(pd.DataFrame({'qty': [1, 2], 'price': [10, 20]}), key='cart',\n"
    "                        num_rows='dynamic')\n"
    "st.metric('Total', int((edited['qty'] * edited['price']).sum()))\n"
    "st.dataframe(pd.DataFrame({'ro': [1]}))\n"
)
FIXED_APP = (
    "import streamlit as st, pandas as pd\n"
    "e = st.data_editor(pd.DataFrame({'qty': [1, 2]}))\n"
    "st.metric('Sum', int(e['qty'].sum()))\n"
)
FORM_APP = (
    "import streamlit as st, pandas as pd\n"
    "with st.form('f'):\n"
    "    e = st.data_editor(pd.DataFrame({'x': [1]}), key='fe')\n"
    "    st.form_submit_button('Go')\n"
    "st.metric('X', int(e['x'].sum()))\n"
)


def _engine(script, guard=None):
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=script)
    rt.run()
    return Engine(rt, guard=guard)


def _metric(eng):
    return [o["text"] for o in eng.read_output()["outputs"] if o["kind"] == "metric"]


def _editor(eng):
    return next(w for w in eng.list_widgets()["widgets"] if w["kind"] == "data_editor")


def test_the_editor_is_a_widget_and_a_plain_dataframe_stays_an_output():
    eng = _engine(CART_APP)
    w = _editor(eng)
    assert w["identifier"] == "cart"
    assert w["value"] == {"rows": [{"qty": 1, "price": 10}, {"qty": 2, "price": 20}],
                          "edits": {"edited_rows": {}, "added_rows": [], "deleted_rows": []}}
    assert w["constraints"] == {"columns": ["qty", "price"], "dynamic": True}
    assert set(w["schema"]["properties"]["value"]["properties"]) == {"edit", "add", "delete"}
    outputs = eng.read_output()["outputs"]
    assert [o["kind"] for o in outputs].count("dataframe") == 1  # only the read-only one (#128)
    assert "qty" not in json.dumps([o for o in outputs if o["kind"] == "dataframe"])


def test_edit_add_delete_and_edits_accumulate():
    eng = _engine(CART_APP)
    assert _metric(eng) == ["Total: 50"]
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}})
    assert _metric(eng) == ["Total: 90"]
    eng.set_widget("cart", {"add": [{"qty": 9, "price": 3}], "delete": [1]})
    assert _metric(eng) == ["Total: 77"]  # 5*10 + 9*3; the row-0 edit survived
    eng.set_widget("cart", {"edit": {"2": {"qty": 1}}})  # row n+0 is the first added row
    assert _metric(eng) == ["Total: 53"]
    assert _editor(eng)["value"]["edits"] == {
        "edited_rows": {"0": {"qty": 5}}, "added_rows": [{"qty": 1, "price": 3}],
        "deleted_rows": [1]}


def test_edits_survive_unrelated_reruns():
    """1.58's AppTest drops the edit state on the next rerun; the runtime re-applies it."""
    eng = _engine(CART_APP + "st.button('noop')\n")
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}})
    eng.click("noop")
    assert _metric(eng) == ["Total: 90"]


def test_null_resets_to_the_apps_data():
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}, "add": [{"qty": 1, "price": 1}]})
    eng.set_widget("cart", None)
    assert _metric(eng) == ["Total: 50"]


@pytest.mark.parametrize("bad,why", [
    ({"edit": {"7": {"qty": 1}}}, "out of range"),
    ({"edit": {"-1": {"qty": 1}}}, "out of range"),
    ({"edit": {"x": {"qty": 1}}}, "not a row number"),
    ({"edit": {"0": {"nope": 1}}}, "unknown column"),
    ({"delete": [5]}, "out of range"),
    ({"zap": 1}, "takes"),
    ({}, "takes"),
    (5, "takes"),
])
def test_a_bad_edit_is_rejected_and_changes_nothing(bad, why):
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}})
    with pytest.raises(RuntimeError_, match=why):
        eng.set_widget("cart", bad)
    assert _metric(eng) == ["Total: 90"]


def test_a_deleted_row_cant_be_edited():
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"delete": [1]})
    with pytest.raises(RuntimeError_, match="was deleted"):
        eng.set_widget("cart", {"edit": {"1": {"qty": 3}}})


def test_fixed_rows_take_edits_but_not_add_or_delete():
    """An unkeyed editor without num_rows='dynamic': driven by its kind[index] handle."""
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(FIXED_APP)
    w = _editor(eng)
    assert w["identifier"] == "data_editor[0]" and w["constraints"]["dynamic"] is False
    assert set(w["schema"]["properties"]["value"]["properties"]) == {"edit"}
    eng.set_widget("data_editor[0]", {"edit": {"1": {"qty": 10}}})
    assert _metric(eng) == ["Sum: 11"]
    for op in ({"add": [{"qty": 1}]}, {"delete": [0]}):
        with pytest.raises(RuntimeError_, match="fixed set of rows"):
            eng.set_widget("data_editor[0]", op)
    assert _metric(eng) == ["Sum: 11"]


def test_an_editor_in_a_form_is_held_until_submit():
    eng = _engine(FORM_APP)
    assert _editor(eng)["form"] == "f"
    eng.set_widget("fe", {"edit": {"0": {"x": 5}}})
    assert _metric(eng) == ["X: 1"]  # not submitted yet
    assert _editor(eng)["value"]["edits"]["edited_rows"] == {"0": {"x": 5}}  # shows what's held
    eng.click("FormSubmitter:f-Go")
    assert _metric(eng) == ["X: 5"]


def test_guardrails_cover_the_editor():
    from streamlit_mcp.engine import PermissionDenied
    from streamlit_mcp.guardrails import Guardrails
    with pytest.raises(PermissionDenied):
        _engine(CART_APP, Guardrails(read_only=True)).set_widget("cart", {"edit": {"0": {"qty": 5}}})
    with pytest.raises(PermissionDenied):
        _engine(CART_APP, Guardrails(allow_list={"other"})).set_widget("cart", {"delete": [0]})


def test_it_is_no_longer_reported_unsupported(tmp_path):
    from streamlit_mcp.elements import detect_unsupported_source
    assert detect_unsupported_source(CART_APP) == []


def test_cli_set_drives_the_editor(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "cart.py"
    app.write_text(CART_APP)
    edit = json.dumps({"edit": {"0": {"qty": 5}}, "add": [{"qty": 9, "price": 3}], "delete": [1]})
    assert main(["call", str(app), "--set", f"cart={edit}", "--read"]) == 0
    assert "Total: 77" in capsys.readouterr().out
    assert main(["call", str(app), "--set", 'cart={"edit": {"9": {"qty": 1}}}']) == 1
    assert "out of range" in capsys.readouterr().err


def test_mcp_set_widget_drives_the_editor(tmp_path):
    from fastmcp import Client

    from streamlit_mcp.server import build_server
    app = tmp_path / "cart.py"
    app.write_text(CART_APP)

    async def go():
        async with Client(build_server(str(app))) as c:
            r = await c.call_tool("set_widget", {"identifier": "cart",
                                                 "value": {"edit": {"0": {"qty": 5}}}})
            return json.loads(r.content[0].text)

    out = asyncio.run(go())
    assert {"kind": "metric", "text": "Total: 90"} in out["outputs"]
    assert out["session_state"]["cart"]["edited_rows"] == {"0": {"qty": 5}}
