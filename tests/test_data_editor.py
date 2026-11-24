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
    assert w["constraints"] == {"columns": ["qty", "price"], "dynamic": True,
                                "column_types": {"qty": "integer", "price": "integer"}}
    assert set(w["schema"]["properties"]["value"]["properties"]) == {"edit", "add", "delete", "rows", "edits"}
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
    assert set(w["schema"]["properties"]["value"]["properties"]) == {"edit", "rows", "edits"}
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


TYPED_APP = (
    "import streamlit as st, pandas as pd\n"
    "df = pd.DataFrame({'item': ['apple', 'pear'], 'qty': [1, 2], 'price': [1.5, 2.0],\n"
    "                   'ok': [True, False], 'when': pd.to_datetime(['2026-01-01', '2026-01-02'])})\n"
    "e = st.data_editor(df, key='grid', num_rows='dynamic')\n"
    "st.metric('Qty', int(e['qty'].sum()))\n"
)


def test_column_types_are_advertised_in_constraints_and_schema():
    """An agent learns each column's cell type up front, from one source (#218)."""
    w = _editor(_engine(TYPED_APP))
    types = {"item": "string", "qty": "integer", "price": "number", "ok": "boolean"}
    assert w["constraints"]["column_types"] == types  # the datetime column isn't checked
    cell = w["schema"]["properties"]["value"]["properties"]["edit"]["additionalProperties"]
    assert cell["properties"] == {k: {"type": [t, "null"]} for k, t in types.items()}


@pytest.mark.parametrize("bad, msg", [
    ({"edit": {"0": {"qty": "not_a_number"}}}, "qty in edit of row 0 must be an integer"),
    ({"edit": {"0": {"qty": 2.7}}}, "must be an integer"),
    ({"edit": {"0": {"qty": True}}}, "must be an integer"),
    ({"edit": {"1": {"price": "cheap"}}}, "price in edit of row 1 must be a number"),
    ({"edit": {"0": {"ok": 1}}}, "ok in edit of row 0 must be true or false"),
    ({"edit": {"0": {"item": 5}}}, "item in edit of row 0 must be a string"),
    ({"add": [{"qty": "x"}]}, "qty in added row 0 must be an integer"),
])
def test_a_cell_that_misfits_its_column_is_rejected_atomically(bad, msg):
    """Streamlit coerces a misfit cell to NaN and reports success; a browser user can't type it.
    The edit is rejected with the edits so far untouched (#218)."""
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(TYPED_APP)
    eng.set_widget("grid", {"edit": {"1": {"qty": 5}}})
    before = _editor(eng)["value"]["edits"]
    with pytest.raises(RuntimeError_, match=msg):
        eng.set_widget("grid", bad)
    assert _editor(eng)["value"]["edits"] == before
    assert _metric(eng) == ["Qty: 6"]


def test_cells_that_fit_their_column_are_accepted():
    eng = _engine(TYPED_APP)
    eng.set_widget("grid", {"edit": {"0": {"qty": 4.0, "price": 3, "ok": False, "item": "fig"}},
                            "add": [{"qty": 10, "when": "2026-02-01"}]})
    edits = _editor(eng)["value"]["edits"]
    assert edits["edited_rows"]["0"] == {"qty": 4, "price": 3, "ok": False, "item": "fig"}
    assert _metric(eng) == ["Qty: 16"]
    eng.set_widget("grid", {"edit": {"1": {"qty": None}}})  # null clears a cell, as in a browser
    assert _metric(eng) == ["Qty: 14"]


def test_cli_strict_rejects_a_misfit_cell(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "grid.py"
    app.write_text(TYPED_APP)
    assert main(["call", str(app), "--set", 'grid={"edit": {"0": {"qty": "nope"}}}',
                 "--strict"]) == 1
    assert "must be an integer" in capsys.readouterr().err


CONFIG_APP = (
    "import streamlit as st, pandas as pd\n"
    "df = pd.DataFrame({'item': ['a', 'b'], 'qty': [1, 2], 'status': ['open', 'open'],\n"
    "                   'price': [1.5, 2.5]})\n"
    "ed = st.data_editor(df, num_rows='dynamic', key='grid', column_config={\n"
    "    'qty': st.column_config.NumberColumn('Quantity', min_value=0, max_value=10),\n"
    "    'status': st.column_config.SelectboxColumn('Status', options=['open', 'closed']),\n"
    "    'price': st.column_config.NumberColumn(min_value=0.5),\n"
    "    'item': st.column_config.TextColumn('Item'),\n"
    "})\n"
    "st.metric('Qty', int(ed['qty'].sum()))\n"
    "st.metric('Closed', int((ed['status'] == 'closed').sum()))\n"
)


def test_column_config_rules_are_advertised_in_constraints_and_schema():
    """SelectboxColumn options and NumberColumn bounds are visible before a write (#220)."""
    w = _editor(_engine(CONFIG_APP))
    assert w["constraints"]["column_rules"] == {
        "qty": {"min": 0, "max": 10}, "status": {"options": ["open", "closed"]},
        "price": {"min": 0.5}}  # a TextColumn has no value rule
    props = w["schema"]["properties"]["value"]["properties"]["edit"]["additionalProperties"][
        "properties"]
    assert props["qty"] == {"type": ["integer", "null"], "minimum": 0, "maximum": 10}
    assert props["status"] == {"type": ["string", "null"], "enum": ["open", "closed", None]}
    assert props["price"] == {"type": ["number", "null"], "minimum": 0.5}


@pytest.mark.parametrize("bad, msg", [
    ({"edit": {"0": {"status": "BOGUS"}}}, "'BOGUS' is not a valid option for status"),
    ({"edit": {"0": {"qty": 999}}}, "999 is out of range for qty in edit of row 0: maximum is 10"),
    ({"edit": {"1": {"qty": -1}}}, "minimum is 0"),
    ({"edit": {"0": {"price": 0.25}}}, "minimum is 0.5"),
    ({"add": [{"status": "pending"}]}, "not a valid option for status in added row 0"),
])
def test_a_cell_that_breaks_its_column_config_is_rejected_atomically(bad, msg):
    """A browser's dropdown / bounded number cell can't produce these; standalone selectbox and
    number_input already reject them, so the editor must too, leaving its edits intact (#220)."""
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(CONFIG_APP)
    eng.set_widget("grid", {"edit": {"1": {"qty": 5, "status": "closed"}}})
    before = _editor(eng)["value"]["edits"]
    with pytest.raises(RuntimeError_, match=msg):
        eng.set_widget("grid", bad)
    assert _editor(eng)["value"]["edits"] == before
    assert _metric(eng) == ["Qty: 6", "Closed: 1"]


def test_cells_within_their_column_config_are_accepted():
    eng = _engine(CONFIG_APP)
    eng.set_widget("grid", {"edit": {"0": {"qty": 10, "status": "closed", "price": 0.5}},
                            "add": [{"item": "c", "qty": 0, "status": None}]})
    assert _metric(eng) == ["Qty: 12", "Closed: 1"]


DISABLED_APP = (
    "import streamlit as st, pandas as pd\n"
    "df = pd.DataFrame({'name': ['a', 'b'], 'locked': [10, 20], 'frozen': [1, 2], 'qty': [1, 2]})\n"
    "ed = st.data_editor(df, key='grid', num_rows='dynamic', disabled=['frozen'],\n"
    "                    column_config={'locked': st.column_config.NumberColumn(disabled=True)})\n"
    "whole = st.data_editor(pd.DataFrame({'x': [1]}), key='whole', disabled=True)\n"
    "st.metric('Sum', int(ed['locked'].sum() + ed['frozen'].sum() + ed['qty'].sum()))\n"
    "st.metric('X', int(whole['x'].sum()))\n"
)


def _editors(eng):
    return {w["identifier"]: w for w in eng.list_widgets()["widgets"]
            if w["kind"] == "data_editor"}


def test_disabled_columns_are_advertised_and_left_out_of_the_schema():
    """Both ways an app makes a column read-only are surfaced, and the write schema doesn't
    offer them, so a schema-following agent never tries the write (#223)."""
    w = _editors(_engine(DISABLED_APP))["grid"]
    assert w["constraints"]["disabled_columns"] == ["locked", "frozen"]
    cell = w["schema"]["properties"]["value"]["properties"]["edit"]["additionalProperties"]
    assert cell["propertyNames"]["enum"] == ["name", "qty"]
    assert set(cell["properties"]) == {"name", "qty"}


@pytest.mark.parametrize("ident, bad, msg", [
    ("grid", {"edit": {"0": {"locked": 777}}}, r"column\(s\) \['locked'\] of 'grid' are disabled"),
    ("grid", {"edit": {"1": {"frozen": 9, "qty": 3}}}, r"\['frozen'\] .* \(edit of row 1\)"),
    ("grid", {"edit": {"0": {"locked": None}}}, "are disabled"),  # clearing is an edit too
    ("grid", {"add": [{"name": "c", "locked": 5}]}, r"\(added row 0\)"),
    ("whole", {"edit": {"0": {"x": 9}}}, "Cannot update a disabled data_editor widget"),
])
def test_a_write_to_a_disabled_editor_or_column_is_rejected_atomically(ident, bad, msg):
    """A browser shows these read-only; the write used to land and report success (#223)."""
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(DISABLED_APP)
    eng.set_widget("grid", {"edit": {"0": {"qty": 5}}})
    before = {k: w["value"]["edits"] for k, w in _editors(eng).items()}
    with pytest.raises(RuntimeError_, match=msg):
        eng.set_widget(ident, bad)
    assert {k: w["value"]["edits"] for k, w in _editors(eng).items()} == before
    assert _metric(eng) == ["Sum: 40", "X: 1"]


def test_enabled_columns_of_an_editor_with_disabled_ones_stay_writable():
    eng = _engine(DISABLED_APP)
    eng.set_widget("grid", {"edit": {"0": {"qty": 5}}, "add": [{"name": "c", "qty": 1}]})
    assert _metric(eng) == ["Sum: 41", "X: 1"]  # the added row's disabled cells stay empty
    eng.set_widget("whole", None)  # resetting a disabled editor writes nothing; it's allowed
    assert _metric(eng) == ["Sum: 41", "X: 1"]


# --- #227: the value an editor reports is valid against its own schema, and round-trips ---

EMPTY = {"edited_rows": {}, "added_rows": [], "deleted_rows": []}
APPS = {"cart": CART_APP, "fixed": FIXED_APP, "form": FORM_APP, "typed": TYPED_APP,
        "config": CONFIG_APP, "disabled": DISABLED_APP}


def _as_received(w):
    """A widget's value as an agent receives it: through JSON (row numbers become strings)."""
    return json.loads(json.dumps(w["value"]))


def _validate(w):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_as_received(w), w["schema"]["properties"]["value"])


@pytest.mark.parametrize("app", list(APPS))
def test_the_reported_value_is_valid_against_its_own_schema(app):
    """It wasn't: the schema described only the edit/add/delete patch, with
    additionalProperties false, so {rows, edits} failed it (#227, the #57/#62/#78 class)."""
    editors = [w for w in _engine(APPS[app]).list_widgets()["widgets"]
               if w["kind"] == "data_editor"]
    assert editors
    for w in editors:
        _validate(w)


def test_the_reported_value_stays_valid_after_edits():
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}, "add": [{"qty": 3, "price": 1}],
                            "delete": [1]})
    _validate(_editor(eng))
    eng = _engine(DISABLED_APP)
    eng.set_widget("grid", {"add": [{"name": "c", "locked": None}]})
    w = _editors(eng)["grid"]
    _validate(w)  # the empty disabled cell isn't kept, so it can't break the schema
    assert w["value"]["edits"]["added_rows"] == [{"name": "c"}]


def test_the_value_as_read_round_trips_through_set_widget():
    """As for every other widget (#57): what an agent reads, it can send back."""
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}, "add": [{"qty": 3, "price": 1}],
                            "delete": [1]})
    read = _as_received(_editor(eng))
    assert _metric(eng) == ["Total: 53"]
    eng.set_widget("cart", read)  # sent back unchanged: the same table, not the edits twice
    assert _as_received(_editor(eng)) == read and _metric(eng) == ["Total: 53"]
    eng.set_widget("cart", None)
    assert _metric(eng) == ["Total: 50"]
    eng.set_widget("cart", read)  # restores the table as read
    assert _as_received(_editor(eng)) == read and _metric(eng) == ["Total: 53"]


def test_the_value_as_read_replaces_the_edits_rather_than_adding_to_them():
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}})
    rows = _editor(eng)["value"]["rows"]
    eng.set_widget("cart", {"rows": rows, "edits": {**EMPTY, "edited_rows": {"1": {"qty": 1}}}})
    assert _editor(eng)["value"]["edits"]["edited_rows"] == {"1": {"qty": 1}}
    assert _metric(eng) == ["Total: 30"]
    eng.set_widget("cart", {"edits": EMPTY})  # rows may be left out; no edits is a reset
    assert _metric(eng) == ["Total: 50"]


@pytest.mark.parametrize("bad, msg", [
    ({"rows": [{"qty": 9, "price": 10}, {"qty": 2, "price": 20}], "edits": EMPTY},
     "is the app's data and can't be changed"),
    ({"edits": {"edited_rows": {}, "added": []}}, "must be an object with"),
    ({"edits": {**EMPTY, "edited_rows": {"0": {"qty": 2}}, "deleted_rows": [0]}},
     "both edited and deleted"),
    ({"edits": {**EMPTY, "edited_rows": {"0": {"qty": "x"}}}}, "must be an integer"),
    ({"edits": {**EMPTY, "edited_rows": {"7": {"qty": 1}}}}, "out of range"),
    ({"edits": EMPTY, "edit": {"0": {"qty": 1}}}, "takes"),
])
def test_a_bad_value_as_read_is_rejected_and_changes_nothing(bad, msg):
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(CART_APP)
    eng.set_widget("cart", {"edit": {"0": {"qty": 5}}})
    before = _editor(eng)["value"]
    with pytest.raises(RuntimeError_, match=msg):
        eng.set_widget("cart", bad)
    assert _editor(eng)["value"] == before and _metric(eng) == ["Total: 90"]


def test_a_fixed_editor_takes_no_added_or_deleted_rows_as_read_either():
    from streamlit_mcp.runtime import RuntimeError_
    eng = _engine(FIXED_APP)
    state = _editor(eng)["schema"]["properties"]["value"]["properties"]["edits"]["properties"]
    assert state["added_rows"]["maxItems"] == 0 and state["deleted_rows"]["maxItems"] == 0
    with pytest.raises(RuntimeError_, match="fixed set of rows"):
        eng.set_widget("data_editor[0]", {"edits": {**EMPTY, "added_rows": [{"qty": 1}]}})


def test_the_value_as_read_is_held_in_a_form_until_submit():
    eng = _engine(FORM_APP)
    eng.set_widget("fe", {"edits": {**EMPTY, "edited_rows": {"0": {"x": 4}}}})
    assert _metric(eng) == ["X: 1"]
    eng.click("Go")
    assert _metric(eng) == ["X: 4"]


def test_cli_set_takes_the_value_as_read(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "cart.py"
    app.write_text(CART_APP)
    value = {"rows": [{"qty": 1, "price": 10}, {"qty": 2, "price": 20}],
             "edits": {**EMPTY, "edited_rows": {"1": {"qty": 3}}}}
    assert main(["call", str(app), "--set", f"cart={json.dumps(value)}", "--read"]) == 0
    assert "Total: 70" in capsys.readouterr().out
