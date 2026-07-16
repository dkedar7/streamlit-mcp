"""Tests for the code-review fixes applied before the 0.1.0 release."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

APP = str(Path(__file__).parent / "apps" / "sample_app.py")
UNSUPPORTED_APP = str(Path(__file__).parent / "apps" / "unsupported_app.py")


# --- P1 / 0.3.11 #43: a JSON-looking value on a text widget is stored verbatim, not crashed
# nor JSON-mangled (was "Hello, True!" — the CLI pre-parse turned 'true' into the bool True) ---
def test_text_widget_json_value_stored_verbatim(capsys):
    from streamlit_mcp.cli import main
    rc = main(["call", APP, "--set", "Name=true", "--read"])
    assert rc == 0
    assert "Hello, true!" in capsys.readouterr().out  # literal 'true', not 'True'


# --- P1: allow-list resolves label<->key consistently ---
def test_allow_list_label_permits_key_identifier():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(APP)
    rt.run()
    eng = Engine(rt, guard=Guardrails(allow_list={"Name"}), app_path=APP)  # by label
    # setting by the key 'name' (what list_widgets returns as identifier) must be allowed
    out = eng.set_widget("name", "ok")
    assert any("Hello, ok!" == o["text"] for o in out["outputs"])


# --- P2: session_state is serialized JSON-safe (dates -> ISO strings) ---
def test_get_state_serializes_dates():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(APP)
    rt.run()
    eng = Engine(rt, app_path=APP)
    assert eng.get_state()["when"] == "2026-01-01"


# --- security: serve fails closed on non-loopback HTTP ---
def test_serve_refuses_nonloopback_http():
    from streamlit_mcp.server import serve
    with pytest.raises(ValueError):
        serve(APP, transport="http", host="0.0.0.0")


# --- P2: session id derivation ignores request_id ---
def test_derive_session_id_ignores_request_id():
    from streamlit_mcp.server import _derive_session_id

    class OnlyRequestId:
        request_id = "r1"

    class HasClientId:
        client_id = "c1"

    assert _derive_session_id(OnlyRequestId()) == "default"
    assert _derive_session_id(HasClientId()) == "c1"


# --- public API surface ---
def test_public_api_exports():
    import streamlit_mcp
    from streamlit_mcp import (  # noqa: F401
        AppTestRuntime,
        Engine,
        Guardrails,
        build_server,
        mcp_tool,
        serve,
    )
    for name in ("Engine", "Guardrails", "serve", "AppTestRuntime", "mcp_tool"):
        assert name in streamlit_mcp.__all__


# --- inspect --layout renders outputs in non-json mode ---
def test_inspect_layout_prints_outputs(capsys):
    from streamlit_mcp.cli import main
    assert main(["inspect", APP, "--layout"]) == 0
    out = capsys.readouterr().out
    assert "Hello, world!" in out and "session_state:" in out


# --- 0.1.1 #1: inspect --layout (text) reports unsupported elements, never drops them ---
def test_inspect_layout_text_reports_unsupported(capsys):
    """The text layout must list unsupported elements, matching --json and MCP get_layout
    (the "reported explicitly, never silently dropped" guarantee / human<->agent parity)."""
    from streamlit_mcp.cli import main
    assert main(["inspect", UNSUPPORTED_APP, "--layout"]) == 0
    out = capsys.readouterr().out
    assert "unsupported:" in out
    assert "file_uploader" in out


# --- 0.1.1 #2: top-level --version prints the version and exits 0 ---
def test_version_flag(capsys):
    import pytest
    from streamlit_mcp import __version__
    from streamlit_mcp.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


# --- 0.1.1 #2: the bare-mode "missing ScriptRunContext!" warning is filtered out ---
def test_bare_mode_scriptruncontext_warning_filtered():
    import logging
    from streamlit_mcp.cli import _quiet_bare_mode_warning
    _quiet_bare_mode_warning()
    lg = logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context")
    rec = lg.makeRecord(
        lg.name, logging.WARNING, __file__, 0,
        "Thread 'MainThread': missing ScriptRunContext! This warning can be ignored "
        "when running in bare mode.", None, None,
    )
    assert lg.filter(rec) is False  # at least one filter rejects the warning


# --- 0.2.0 #7: bearer auth is ENFORCED on HTTP/SSE ---
def _dummy_build_server(monkeypatch):
    from streamlit_mcp import server

    class DummyMCP:
        def run(self, *a, **k):  # don't block the test on a real server
            pass

    monkeypatch.setattr(server, "build_server", lambda *a, **k: DummyMCP())
    return server


def test_bearer_auth_builds_verifier_only_when_token_set():
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import bearer_auth
    assert bearer_auth(None) is None
    assert bearer_auth(Guardrails()) is None
    v = bearer_auth(Guardrails(bearer_token="SEKRET"))
    assert v is not None and hasattr(v, "verify_token")


def test_serve_allows_nonloopback_when_token_set(monkeypatch):
    # With a token, auth gates access, so a public host is permitted (must not raise).
    from streamlit_mcp.guardrails import Guardrails
    server = _dummy_build_server(monkeypatch)
    server.serve(APP, transport="http", host="0.0.0.0",
                 guard=Guardrails(bearer_token="SEKRET"))


def test_http_transport_requires_bearer_token():
    """Real enforcement: the HTTP app returns 401 without a valid token, and not-401 with it."""
    from starlette.testclient import TestClient
    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import bearer_auth, build_server

    guard = Guardrails(bearer_token="SEKRET")
    mcp = build_server(APP, guard=guard, auth=bearer_auth(guard))
    app = mcp.http_app(path="/mcp", json_response=True)
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}}}
    hdr = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}
    with TestClient(app) as client:
        assert client.post("/mcp", json=body, headers=hdr).status_code == 401
        ok = client.post("/mcp", json=body,
                         headers={**hdr, "Authorization": "Bearer SEKRET"})
        assert ok.status_code != 401


# --- 0.2.1 #10: a failed set_widget must not poison a long-lived session ---
POISON_APP = (
    "import streamlit as st\n"
    "n = st.number_input('Count', min_value=0, max_value=10, value=1)\n"
    "c = st.selectbox('Color', ['red', 'green', 'blue'])\n"
    "st.markdown(f'Count={n} Color={c}')\n"
)


def _markdown(rt):
    return [o.text for o in rt.snapshot().outputs if o.kind == "markdown"]


def test_invalid_selectbox_option_does_not_poison_session():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=POISON_APP)
    rt.run()
    rt.set_widget("Count", 5)
    with pytest.raises(RuntimeError_):
        rt.set_widget("Color", "purple")            # invalid -> clean error, nothing applied
    # session is NOT poisoned: an unrelated widget still sets cleanly, Color unchanged
    rt.set_widget("Count", 8)
    assert "Count=8 Color=red" in _markdown(rt)
    rt.set_widget("Color", "blue")                  # valid choice still works
    assert "Count=8 Color=blue" in _markdown(rt)


def test_invalid_multiselect_option_rejected_cleanly():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    script = ("import streamlit as st\n"
              "t = st.multiselect('Tags', ['a', 'b', 'c'])\n"
              "st.markdown('tags=' + ','.join(t))\n")
    rt = AppTestRuntime(script=script)
    rt.run()
    with pytest.raises(RuntimeError_):
        rt.set_widget("Tags", ["a", "z"])           # 'z' not offered
    rt.set_widget("Tags", ["a", "b"])               # session still usable
    assert "tags=a,b" in _markdown(rt)


def test_engine_set_widget_invalid_option_keeps_session_usable():
    # The MCP tools dispatch to Engine.set_widget; a bad option must not brick the session.
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=POISON_APP)
    rt.run()
    eng = Engine(rt)
    with pytest.raises(RuntimeError_):
        eng.set_widget("Color", "purple")
    out = eng.set_widget("Count", 8)                # must succeed (not poisoned)
    assert any(o["text"] == "Count=8 Color=red" for o in out["outputs"])


# --- 0.2.2 #12: out-of-range number/slider/date is rejected, not silently reverted ---
RANGE_APP = (
    "import streamlit as st, datetime\n"
    "n = st.number_input('Count', min_value=0, max_value=10, value=1)\n"
    "s = st.slider('Level', 0, 100, 50)\n"
    "r = st.slider('Range', 0, 100, (20, 40))\n"
    "w = st.date_input('When', value=datetime.date(2026, 6, 1),\n"
    "                  min_value=datetime.date(2026, 1, 1), max_value=datetime.date(2026, 12, 31))\n"
    "st.markdown(f'Count={n} Level={s} Range={r} When={w}')\n"
)


def test_out_of_range_number_rejected_and_prior_value_preserved():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=RANGE_APP)
    rt.run()
    rt.set_widget("Count", 5)                        # valid
    with pytest.raises(RuntimeError_):
        rt.set_widget("Count", 999)                 # above max 10
    # the prior valid value (5) must survive — not silently reverted to the default (1)
    assert "Count=5 " in _markdown(rt)[0]
    rt.set_widget("Count", 0)                        # boundary (min) is allowed
    assert "Count=0 " in _markdown(rt)[0]


# --- 0.3.4 #29: no input widget is silently dropped ---
DROPPED_APP = (
    "import streamlit as st, datetime\n"
    "st.text_input('Name', key='name')\n"
    "st.time_input('Alarm', value=datetime.time(9, 0), key='alarm')\n"
    "st.toggle('Dark', key='dark')\n"
    "st.select_slider('Size', options=['S', 'M', 'L'], key='size')\n"
    "st.color_picker('Color', key='color')\n"
    "st.pills('Tags', options=['a', 'b'], key='tags')\n"
)


def test_promoted_widgets_introspected_and_pills_reported():
    from streamlit_mcp.elements import detect_unsupported_source
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=DROPPED_APP)
    rt.run()
    kinds = {w["kind"] for w in Engine(rt).list_widgets()["widgets"]}
    assert {"time_input", "toggle", "select_slider", "color_picker"} <= kinds  # no longer dropped
    # pills isn't drivable -> reported explicitly, never silently dropped
    assert "pills" in [u["element"] for u in detect_unsupported_source(DROPPED_APP)]


def test_promoted_widgets_are_drivable():
    import datetime as _dt

    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=DROPPED_APP)
    rt.run()
    rt.set_widget("Alarm", "10:30")
    rt.set_widget("Dark", True)
    rt.set_widget("Size", "L")
    rt.set_widget("Color", "#ff0000")
    state = rt.snapshot().session_state
    assert state["alarm"] == _dt.time(10, 30) and state["dark"] is True
    assert state["size"] == "L" and state["color"] == "#ff0000"
    with pytest.raises(RuntimeError_):
        rt.set_widget("Size", "XL")  # invalid select_slider option -> rejected (atomic, #10-style)


def test_out_of_range_slider_and_date_rejected():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=RANGE_APP)
    rt.run()
    with pytest.raises(RuntimeError_):
        rt.set_widget("Level", -50)                 # below min 0
    with pytest.raises(RuntimeError_):
        rt.set_widget("Range", [20, 150])           # range slider: 150 above max 100
    with pytest.raises(RuntimeError_):
        rt.set_widget("When", "2030-01-01")         # past max date
    rt.set_widget("Level", 70)                       # valid still works
    rt.set_widget("When", "2026-07-01")
    assert "Level=70" in _markdown(rt)[0] and "When=2026-07-01" in _markdown(rt)[0]


# --- 0.3.5 #31: an invalid color_picker value is rejected, not silently reverted ---
COLOR_APP = (
    "import streamlit as st\n"
    "c = st.color_picker('Pick', value='#ff0000', key='pick')\n"
    "st.markdown(f'pick={c}')\n"
)


def test_invalid_color_rejected_and_prior_value_preserved():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=COLOR_APP)
    rt.run()
    rt.set_widget("pick", "#00ff00")                 # valid, stored
    with pytest.raises(RuntimeError_):
        rt.set_widget("pick", "notacolor")          # invalid -> clean error, nothing applied
    # the prior valid value must survive — not silently reverted to a default (#31)
    assert "pick=#00ff00" in _markdown(rt)[0]
    assert rt.snapshot().session_state["pick"] == "#00ff00"


def test_color_picker_accepts_valid_hex_forms():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=COLOR_APP)
    rt.run()
    for good in ("#abc", "#AABBCC", "#0f0f0f"):
        rt.set_widget("pick", good)                  # 3- and 6-digit hex both stick
        assert rt.snapshot().session_state["pick"] == good


def test_invalid_color_forms_rejected():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=COLOR_APP)
    rt.run()
    for bad in ("red", "#12345", "#gggggg", "ff0000", "", 255):
        with pytest.raises(RuntimeError_):
            rt.set_widget("pick", bad)
    assert rt.snapshot().session_state["pick"] == "#ff0000"  # never mutated by a rejected set


# --- 0.3.6 #33: an invalid range (two-handle) select_slider value is rejected, not reverted ---
RANGE_SLIDER_APP = (
    "import streamlit as st\n"
    "r = st.select_slider('Range', options=['xs', 's', 'm', 'l', 'xl'],\n"
    "                     value=('s', 'l'), key='rng')\n"
    "st.markdown(f'rng={list(r)}')\n"
)


def test_invalid_range_select_slider_rejected_and_prior_value_preserved():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=RANGE_SLIDER_APP)
    rt.run()
    rt.set_widget("rng", ["xs", "m"])                # valid range, stored
    with pytest.raises(RuntimeError_):
        rt.set_widget("rng", ["xl", "NOPE"])        # bad handle -> clean error, nothing applied
    # the prior valid range must survive — not silently reverted / clobbered (#33)
    assert "rng=['xs', 'm']" in _markdown(rt)[0]
    assert list(rt.snapshot().session_state["rng"]) == ["xs", "m"]
    rt.set_widget("rng", ["s", "xl"])                # valid range still works
    assert list(rt.snapshot().session_state["rng"]) == ["s", "xl"]


def test_single_value_select_slider_still_validated():
    # the single-value form (the #29 path) must keep rejecting a non-option
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=DROPPED_APP)
    rt.run()
    rt.set_widget("Size", "L")                       # valid
    with pytest.raises(RuntimeError_):
        rt.set_widget("Size", "XL")                 # not an offered option
    assert rt.snapshot().session_state["size"] == "L"


# --- 0.3.7 proactive self-audit: harden set_widget value coercion (sibling of #12/#33) ---
DATE_RANGE_APP = (
    "import streamlit as st, datetime\n"
    "d = st.date_input('When', value=(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)),\n"
    "                  min_value=datetime.date(2026, 1, 1), max_value=datetime.date(2026, 12, 31),\n"
    "                  key='when')\n"
    "st.markdown(f'when={[str(x) for x in d]}')\n"
)


def test_date_range_out_of_bounds_element_rejected_not_reverted():
    # the date-range sibling of #33: a range whose element is out of [min,max] used to slip past
    # _validate_range (str<date -> TypeError -> bail) and silently revert; now coerced + rejected.
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=DATE_RANGE_APP)
    rt.run()
    rt.set_widget("when", ["2026-02-01", "2026-02-28"])   # valid range, stored
    with pytest.raises(RuntimeError_):
        rt.set_widget("when", ["2026-02-01", "2030-01-01"])  # 2030 past max -> rejected up front
    assert "when=['2026-02-01', '2026-02-28']" in _markdown(rt)[0]  # prior value survives
    with pytest.raises(RuntimeError_):
        rt.set_widget("when", ["not-a-date", "2026-02-28"])  # bad-format element -> clean reject


def test_coercion_failures_give_clean_actionable_errors():
    # a bad number/date/time value is a clean RuntimeError_ naming the widget, not a raw ValueError
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    cases = [
        ("import streamlit as st\nst.number_input('N', value=5, key='k')\n", "abc", "number"),
        ("import streamlit as st, datetime\n"
         "st.date_input('D', value=datetime.date(2026,1,1), key='k')\n", "not-a-date", "date"),
        ("import streamlit as st, datetime\n"
         "st.time_input('T', value=datetime.time(9,0), key='k')\n", "25:99", "time"),
    ]
    for script, bad, word in cases:
        rt = AppTestRuntime(script=script)
        rt.run()
        with pytest.raises(RuntimeError_) as exc:
            rt.set_widget("k", bad)
        msg = str(exc.value)
        assert word in msg and "Traceback" not in msg


def test_bool_widget_accepts_common_spellings_and_rejects_junk():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    script = "import streamlit as st\nst.checkbox('C', value=False, key='k')\n"
    for good, expected in [("true", True), ("false", False), (1, True), (0, False),
                           ("yes", True), ("no", False), (True, True)]:
        rt = AppTestRuntime(script=script)
        rt.run()
        rt.set_widget("k", good)
        assert rt.snapshot().session_state["k"] is expected
    rt = AppTestRuntime(script=script)
    rt.run()
    with pytest.raises(RuntimeError_):
        rt.set_widget("k", "maybe")                  # not a boolean -> clean reject, atomic
    assert rt.snapshot().session_state["k"] is False


# --- 0.3.9 #39: snapshot preserves document/render order, not per-kind grouping ---
def test_outputs_returned_in_document_order():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.markdown('A'); st.title('B'); st.markdown('C'); st.caption('D')\n"))
    rt.run()
    # A(markdown) B(title) C(markdown) D(caption) — the title must NOT hoist above A (kind grouping)
    assert [o.text for o in rt.snapshot().outputs] == ["A", "B", "C", "D"]


def test_widgets_returned_in_declaration_order():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.text_input('1'); st.slider('2', 0, 10, 5); st.text_input('3')\n"
        "st.checkbox('4'); st.slider('5', 0, 10, 5)\n"))
    rt.run()
    # declared 1..5 across mixed kinds — not regrouped into text_inputs, then sliders, then checkbox
    assert [w.label for w in rt.snapshot().widgets] == ["1", "2", "3", "4", "5"]


def test_non_string_identifier_is_clean_not_found_not_a_crash():
    # a None/int/list identifier (e.g. an agent omitting the arg) must raise WidgetNotFound, not a
    # raw TypeError from the kind[index] regex (#41). Found by StreamlitArena driving with a small model.
    from streamlit_mcp.runtime import AppTestRuntime, WidgetNotFound
    rt = AppTestRuntime(script="import streamlit as st\nst.number_input('Bid', 0, 250, 0, key='bid')\n")
    rt.run()
    for bad in (None, 123, ["x"]):
        with pytest.raises(WidgetNotFound):
            rt.set_widget(bad, 1)
        with pytest.raises(WidgetNotFound):
            rt.click(bad)
    rt.set_widget("Bid", 250)  # valid identifier still resolves
    assert rt.snapshot().session_state["bid"] == 250


def test_document_order_holds_across_sidebar_and_columns():
    # parity: switching to a tree walk must not drop sidebar or nested (column) widgets
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.sidebar.text_input('side', key='side')\n"
        "st.text_input('main', key='main')\n"
        "c1, c2 = st.columns(2)\n"
        "c1.selectbox('C', ['x', 'y'], key='sel'); c2.checkbox('chk', key='chk')\n"))
    rt.run()
    keys = [w.key for w in rt.snapshot().widgets]
    assert set(keys) == {"side", "main", "sel", "chk"}   # none dropped
    assert keys.index("side") < keys.index("main")       # sidebar (left rail) before main, in order


# --- 0.3.10 #41: every advertised identifier (incl. the kind[index] fallback) resolves ---
def test_kind_index_identifier_round_trips():
    # a keyless, empty-label widget is advertised as kind[index]; that handle must be settable
    from streamlit_mcp.elements import widgets_to_models
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.text_input('Name', key='name')\n"
        "st.text_input('', label_visibility='collapsed')\n"))  # -> text_input[1]
    rt.run()
    ids = [m["identifier"] for m in widgets_to_models(rt.snapshot())]
    assert "text_input[1]" in ids                 # the advertised dead handle
    rt.set_widget("text_input[1]", "hello")       # must resolve now, not "no widget matching"
    # the value landed on the keyless widget (2nd text_input), not the keyed one
    assert rt._find("text_input[1]")[1].value == "hello"
    assert rt.snapshot().session_state.get("name") == ""


def test_every_advertised_identifier_resolves_and_maps_to_same_widget():
    # the round-trip guarantee: _find and snapshot share numbering, so kind[index] is consistent
    # even when a keyless widget sits in the sidebar (accessor order != document order)
    from streamlit_mcp.elements import _identifier
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=(
        "import streamlit as st\n"
        "st.sidebar.text_input('', label_visibility='collapsed')\n"   # doc-order text_input[0]
        "st.text_input('', label_visibility='collapsed')\n"))         # doc-order text_input[1]
    rt.run()
    rt.set_widget("text_input[0]", "SIDE")
    rt.set_widget("text_input[1]", "MAIN")
    by_index = {w.index: w.value for w in rt.snapshot().widgets if w.kind == "text_input"}
    assert by_index == {0: "SIDE", 1: "MAIN"}     # [0] hit sidebar, [1] hit main — not reversed
    # and every identifier snapshot advertises resolves to a real element
    for w in rt.snapshot().widgets:
        assert rt._find(_identifier(w))[1] is not None


# --- 0.3.11 #43: CLI --set stores literal strings for text widgets (parity with MCP) ---
def test_cli_text_widget_values_are_literal_not_json_mangled(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "t.py"
    app.write_text("import streamlit as st\n"
                   "st.text_input('Comment', key='comment')\n"
                   "st.text_area('Config', key='config')\n")
    cases = [("Comment", "comment", "true", "true"),
             ("Comment", "comment", "false", "false"),
             ("Comment", "comment", "null", "null"),
             ("Config", "config", '{"a": 1, "b": true}', '{"a": 1, "b": true}')]
    for label, key, value, expected in cases:
        rc = main(["call", str(app), "--set", f"{label}={value}", "--state", "--json"])
        assert rc == 0
        state = json.loads(capsys.readouterr().out)
        assert state[key] == expected                 # literal, not True/False/None/repr


def test_cli_text_widget_matches_mcp_engine_value(tmp_path, capsys):
    # parity: the CLI must store the same value the engine (MCP surface) stores for the same input
    from streamlit_mcp.cli import main
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    script = "import streamlit as st\nst.text_input('Comment', key='comment')\n"
    app = tmp_path / "t.py"
    app.write_text(script)
    rc = main(["call", str(app), "--set", "Comment=true", "--state", "--json"])
    assert rc == 0
    cli_value = json.loads(capsys.readouterr().out)["comment"]
    rt = AppTestRuntime(script=script)
    rt.run()
    mcp_out = Engine(rt).set_widget("comment", "true")  # MCP passes the string verbatim
    assert cli_value == mcp_out["session_state"]["comment"] == "true"


def test_cli_typed_widgets_still_json_parse(tmp_path, capsys):
    # the JSON pre-parse must remain for non-text widgets (numbers, bools, lists)
    from streamlit_mcp.cli import main
    app = tmp_path / "typed.py"
    app.write_text("import streamlit as st\n"
                   "st.number_input('Age', value=0, key='age')\n"
                   "st.checkbox('Agree', key='agree')\n"
                   "st.multiselect('Tags', ['a', 'b', 'c'], key='tags')\n")
    rc = main(["call", str(app), "--set", "Age=41", "--set", "Agree=true",
               "--set", 'Tags=["a","c"]', "--state", "--json"])
    assert rc == 0
    state = json.loads(capsys.readouterr().out)
    assert state["age"] == 41 and state["agree"] is True and state["tags"] == ["a", "c"]


# --- 0.4.0 #51: non-string options — the natural typed value round-trips, not falsely rejected ---
TYPED_OPTIONS_APP = (
    "import streamlit as st\n"
    "st.selectbox('Pick', [1, 2, 3], key='pick')\n"
    "st.radio('Rate', [10, 20, 30], key='rate')\n"
    "st.multiselect('Nums', [1, 2, 3], key='nums')\n"
    "st.select_slider('Size', options=[10, 20, 30], key='size')\n"
)


@pytest.mark.parametrize(
    "identifier,value,expected",
    [
        ("pick", 2, 2),        # the natural typed value the tool itself advertises (value: 1)
        ("pick", "2", 2),      # the stringified option form — both resolve to the real option
        ("rate", 20, 20),
        ("nums", [1, 3], [1, 3]),
        ("nums", 1, [1]),      # a bare option means "select just this one"
        ("size", 30, 30),
    ],
)
def test_non_string_options_accept_the_typed_value(identifier, value, expected):
    """AppTest stringifies a widget's options but reports its value in the real type, so a widget
    built from non-string options advertised options ['1','2','3'] while reading back value 1 — and
    the literal membership check then rejected the very value it advertised, breaking the
    list_widgets -> set_widget round-trip for that whole class of widget (#51)."""
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=TYPED_OPTIONS_APP)
    rt.run()
    rt.set_widget(identifier, value)
    assert rt.snapshot().session_state[identifier] == expected


@pytest.mark.parametrize("identifier,value", [("pick", 9), ("rate", 99), ("nums", [1, 9])])
def test_non_string_options_still_reject_a_real_non_option(identifier, value):
    """String-normalizing membership must not open the gate to values that aren't options."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=TYPED_OPTIONS_APP)
    rt.run()
    with pytest.raises(RuntimeError_, match="not valid options|is not a valid option"):
        rt.set_widget(identifier, value)


def test_every_advertised_value_is_settable_back_verbatim():
    """The round-trip guarantee, stated directly: every value list_widgets advertises can be sent
    straight back to set_widget."""
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=TYPED_OPTIONS_APP)
    rt.run()
    eng = Engine(rt)
    for w in eng.list_widgets()["widgets"]:
        eng.set_widget(w["identifier"], w["value"])  # must not raise


def test_int_number_input_rejects_a_fractional_value():
    """AppTest truncates 30.5 -> 30 on an integer number_input without raising, so set_widget
    stored a value the caller never asked for and reported success (noted while fixing #51)."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    script = "import streamlit as st\nst.number_input('Score', 0, 100, 5, key='score')\n"
    rt = AppTestRuntime(script=script)
    rt.run()
    with pytest.raises(RuntimeError_, match="truncated"):
        rt.set_widget("score", 30.5)
    assert rt.snapshot().session_state["score"] == 5  # untouched
    rt.set_widget("score", 30.0)  # an integral float is lossless -> allowed
    assert rt.snapshot().session_state["score"] == 30


# --- 0.4.0 #52: an unsupported widget placed via a container accessor is reported, not dropped ---
ACCESSOR_APP = (
    "import streamlit as st\n"
    "import streamlit as sl\n"
    "st.sidebar.file_uploader('Sidebar upload')\n"
    "col1, col2 = st.columns(2)\n"
    "col1.camera_input('Col camera')\n"
    "box = st.container()\n"
    "box.download_button('DL', data='x')\n"
    "tab1, = st.tabs(['T'])\n"
    "tab1.data_editor({'a': [1, 2]})\n"
    "sl.chat_input('Aliased')\n"
    "st.dataframe({'b': [3]})\n"                      # a plain OUTPUT — must not be reported
    "# st.pills('commented out', ['x'])\n"            # a comment — must not be reported
    "note = 'st.audio_input(inside a string)'\n"      # a string — must not be reported
)


def test_accessor_placed_unsupported_widgets_are_reported():
    """The old regex anchored on the bare `st.<name>(` form, so every unsupported widget placed
    through a container accessor — the ubiquitous sidebar/columns idioms — was silently dropped
    from `unsupported` on every surface, breaking the headline guarantee (#52)."""
    from streamlit_mcp.elements import detect_unsupported_source
    found = {u["element"] for u in detect_unsupported_source(ACCESSOR_APP)}
    assert {"file_uploader", "camera_input", "download_button", "data_editor"} <= found
    assert "chat_input" in found  # reached through an aliased import, too


def test_source_scan_ignores_comments_strings_and_plain_outputs():
    """Scanning the AST rather than the raw text also drops the old false positives."""
    from streamlit_mcp.elements import detect_unsupported_source
    found = {u["element"] for u in detect_unsupported_source(ACCESSOR_APP)}
    assert "pills" not in found        # commented out
    assert "audio_input" not in found  # inside a string literal
    assert "dataframe" not in found    # st.dataframe is a supported output, not st.data_editor


def test_unsupported_agrees_across_every_surface(tmp_path, capsys):
    """--layout text, --json and MCP get_layout must agree (they share detect_unsupported)."""
    from streamlit_mcp.cli import main
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    app = tmp_path / "accessor.py"
    app.write_text(ACCESSOR_APP)
    assert main(["inspect", str(app), "--layout", "--json"]) == 0
    from_json = {u["element"] for u in json.loads(capsys.readouterr().out)["unsupported"]}
    assert main(["inspect", str(app), "--layout"]) == 0
    text = capsys.readouterr().out
    rt = AppTestRuntime(str(app))
    rt.run()
    from_mcp = {u["element"] for u in Engine(rt, app_path=str(app)).get_layout()["unsupported"]}
    assert from_json == from_mcp
    assert "file_uploader" in from_json
    for element in from_json:
        assert element in text


def test_unparseable_source_still_reports_rather_than_reporting_nothing():
    from streamlit_mcp.elements import detect_unsupported_source
    broken = "import streamlit as st\nst.file_uploader('x'\n"  # syntax error: unclosed paren
    assert [u["element"] for u in detect_unsupported_source(broken)] == ["file_uploader"]


# --- 0.4.0 #53: form_submit_button is a supported, clickable button — not "unsupported" ---
FORM_APP = (
    "import streamlit as st\n"
    "with st.form('f'):\n"
    "    name = st.text_input('Name', key='name')\n"
    "    age = st.slider('Age', 0, 100, 10, key='age')\n"
    "    submitted = st.form_submit_button('Submit')\n"
    "if submitted:\n"
    "    st.session_state['result'] = f'{name} is {age}'\n"
)


def test_form_submit_button_is_not_reported_unsupported():
    """It was reported as a supported clickable button AND as unsupported with a 'drive it another
    way' reason that was simply false — steering agents off the working st.form flow (#53)."""
    from streamlit_mcp.elements import detect_unsupported_source
    assert detect_unsupported_source(FORM_APP) == []


def test_form_is_drivable_set_the_fields_then_click_submit():
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=FORM_APP)
    rt.run()
    eng = Engine(rt)
    buttons = [w for w in eng.list_widgets()["widgets"] if w["action"]]
    assert len(buttons) == 1  # reported once, as a button
    eng.set_widget("name", "agent")
    eng.set_widget("age", 42)
    eng.click("Submit")
    assert eng.get_state()["result"] == "agent is 42"


# --- 0.4.0 #54: CLI --set no longer JSON-pre-parses a value that IS one of the widget's options ---
JSONISH_OPTIONS_APP = (
    "import streamlit as st\n"
    "st.selectbox('Env', ['true', 'false'], key='env')\n"
    "st.selectbox('Ver', ['1', '2', '3'], key='ver')\n"
    "st.radio('Mode', ['yes', 'no'], key='mode')\n"
)


@pytest.mark.parametrize("assignment,key,expected", [
    ("Env=true", "env", "true"),   # a genuinely-string option that looks like a JSON token
    ("Env=false", "env", "false"),
    ("Ver=2", "ver", "2"),         # a numeric-string version picker
    ("Mode=yes", "mode", "yes"),   # the control: never a JSON token, always worked
])
def test_cli_sets_string_options_that_look_like_json(tmp_path, capsys, assignment, key, expected):
    """The CLI JSON-pre-parsed 'true'->True and '2'->2 before validation, so a value that IS one of
    the widget's own options was rejected as invalid — while the identical string sent over MCP was
    accepted. A CLI-only failure on a common widget class, and a human<->agent parity break (#54)."""
    from streamlit_mcp.cli import main
    app = tmp_path / "opts.py"
    app.write_text(JSONISH_OPTIONS_APP)
    assert main(["call", str(app), "--set", assignment, "--state", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[key] == expected


def test_cli_and_mcp_store_the_same_value_for_a_jsonish_option(tmp_path, capsys):
    """Parity, stated directly: the CLI and MCP store the same value for the same intent."""
    from streamlit_mcp.cli import main
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    app = tmp_path / "opts.py"
    app.write_text(JSONISH_OPTIONS_APP)
    assert main(["call", str(app), "--set", "Env=true", "--state", "--json"]) == 0
    cli_value = json.loads(capsys.readouterr().out)["env"]
    rt = AppTestRuntime(script=JSONISH_OPTIONS_APP)
    rt.run()
    mcp_value = Engine(rt).set_widget("env", "true")["session_state"]["env"]
    assert cli_value == mcp_value == "true"


def test_cli_still_rejects_a_value_that_is_not_an_option(tmp_path):
    from streamlit_mcp.cli import main
    app = tmp_path / "opts.py"
    app.write_text(JSONISH_OPTIONS_APP)
    assert main(["call", str(app), "--set", "Env=maybe", "--state"]) == 1


# --- 0.4.0 #55: range widgets advertise a range, and a wrong-arity value is rejected atomically ---
ARITY_APP = (
    "import streamlit as st, datetime\n"
    "st.slider('Rng', 0, 100, (20, 80), key='rng')\n"
    "st.slider('Single', 0, 100, 10, key='single')\n"
    "st.select_slider('SizeRange', options=['s', 'm', 'l', 'xl'], value=('s', 'l'), key='ssr')\n"
    "st.date_input('DateRange', value=(datetime.date(2026, 1, 1),"
    " datetime.date(2026, 1, 31)), key='dr')\n"
)


def test_range_widget_advertises_an_array_schema():
    """Every range widget advertised the same SCALAR schema as its single-handle form, so a
    schema-following agent could not construct a valid set from what it was told (#55)."""
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=ARITY_APP)
    rt.run()
    schemas = {w["identifier"]: w["schema"]["properties"]["value"]
               for w in Engine(rt).list_widgets()["widgets"]}
    for ident in ("rng", "ssr", "dr"):
        assert schemas[ident]["type"] == "array", ident
        assert schemas[ident]["minItems"] == schemas[ident]["maxItems"] == 2, ident
    assert schemas["rng"]["items"]["type"] == "number"
    assert schemas["ssr"]["items"]["enum"] == ["s", "m", "l", "xl"]
    assert schemas["dr"]["items"]["format"] == "date"
    assert schemas["single"]["type"] == "number"  # the single-handle form is unchanged


@pytest.mark.parametrize("identifier,scalar", [
    ("rng", 50),           # was silently reverted to the prior value, reporting success
    ("ssr", "m"),          # same
    ("dr", "2026-01-15"),  # worse: silently degraded the range to a 1-element value
])
def test_scalar_sent_to_a_range_widget_is_rejected_not_silently_discarded(identifier, scalar):
    """AppTest normalizes an arity mismatch away WITHOUT raising, so the rollback net never fired
    and the write vanished while set_widget reported success — the silent-revert class of
    #10/#12/#31/#33, left open for the range/arity case (#55)."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=ARITY_APP)
    rt.run()
    before = rt.snapshot().session_state[identifier]
    with pytest.raises(RuntimeError_, match="range"):
        rt.set_widget(identifier, scalar)
    assert rt.snapshot().session_state[identifier] == before  # atomic: prior value untouched


def test_list_sent_to_a_single_handle_widget_is_rejected():
    """The hole is bidirectional — AppTest drops a list sent to a single-handle slider just as
    silently as it drops a scalar sent to a range one."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=ARITY_APP)
    rt.run()
    with pytest.raises(RuntimeError_, match="single-value"):
        rt.set_widget("single", [5, 95])
    assert rt.snapshot().session_state["single"] == 10


def test_wrong_length_range_is_rejected():
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=ARITY_APP)
    rt.run()
    with pytest.raises(RuntimeError_, match="expected 2 values"):
        rt.set_widget("rng", [10, 50, 90])


def test_valid_range_sets_still_apply():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=ARITY_APP)
    rt.run()
    rt.set_widget("rng", [5, 95])
    rt.set_widget("ssr", ["m", "xl"])
    rt.set_widget("dr", ["2026-02-01", "2026-02-28"])
    rt.set_widget("single", 42)
    state = rt.snapshot().session_state
    assert list(state["rng"]) == [5, 95]
    assert list(state["ssr"]) == ["m", "xl"]
    assert state["single"] == 42


def test_range_error_message_shows_iso_dates_not_python_reprs():
    """The message an agent has to act on shouldn't be full of datetime.date(2026, 1, 1) reprs."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=ARITY_APP)
    rt.run()
    with pytest.raises(RuntimeError_) as excinfo:
        rt.set_widget("dr", "2026-01-15")
    message = str(excinfo.value)
    assert "'2026-01-01'" in message and "datetime.date(" not in message


def test_cli_parses_the_value_against_the_widget_it_actually_writes(tmp_path, capsys):
    """--set reads the raw value against the target's kind/options, so the model it consults must
    name the same widget the runtime resolves. In an app with two same-named widgets of different
    kinds, runtime._find picks by SUPPORTED_KINDS order (text_input before selectbox), so the CLI
    must too — indexing them in document order would parse 'true' against the selectbox (JSON ->
    True), then write it to the text_input as the mangled "True", reviving #43."""
    from streamlit_mcp.cli import main
    app = tmp_path / "dupe.py"
    app.write_text(
        "import streamlit as st\n"
        "st.selectbox('X', ['a', 'b'], key='sel')\n"
        "st.text_input('X', key='txt')\n"
    )
    assert main(["call", str(app), "--set", "X=true", "--state", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["txt"] == "true"  # literal, not "True"


# --- 0.5.0 #57: an index=None placeholder selectbox/radio round-trips its null value ---
PLACEHOLDER_APP = (
    "import streamlit as st\n"
    "st.selectbox('Choose', ['a', 'b', 'c'], index=None, key='choose')\n"
    "st.radio('Rad', ['x', 'y'], index=None, key='rad')\n"
    "st.selectbox('Reg', ['a', 'b', 'c'], key='reg')\n"  # regular: index=0, not nullable
)


def test_placeholder_schema_permits_null():
    """A placeholder selectbox/radio reports value: null, so its own enum must permit null — else
    the read output contradicts the schema it advertises and a schema-validating agent balks at a
    value the tool itself emitted (#57)."""
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=PLACEHOLDER_APP)
    rt.run()
    schemas = {w["identifier"]: w for w in Engine(rt).list_widgets()["widgets"]}
    for ident in ("choose", "rad"):
        w = schemas[ident]
        assert w["value"] is None
        v = w["schema"]["properties"]["value"]
        assert v["type"] == ["string", "null"]
        assert None in v["enum"]  # the value the widget reports is in its own enum
    # a regular (index=0) selectbox is unchanged — never null, so never nullable
    reg = schemas["reg"]["schema"]["properties"]["value"]
    assert reg["type"] == "string" and None not in reg["enum"]


@pytest.mark.parametrize("identifier", ["choose", "rad"])
def test_placeholder_null_round_trips(identifier):
    """The core defect: an agent reads value: null and cannot send it back. set_widget(id, null)
    must be accepted (it's the widget's own reported value)."""
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=PLACEHOLDER_APP)
    rt.run()
    rt.set_widget(identifier, None)  # must not raise
    assert rt.snapshot().session_state[identifier] is None


def test_placeholder_can_be_cleared_after_a_selection():
    """The 'reset this filter' workflow: select a real option, then clear back to no-selection."""
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=PLACEHOLDER_APP)
    rt.run()
    rt.set_widget("choose", "b")
    assert rt.snapshot().session_state["choose"] == "b"
    rt.set_widget("choose", None)
    assert rt.snapshot().session_state["choose"] is None


def test_regular_selectbox_rejects_null_not_silently():
    """A regular (index=0) selectbox does NOT support no-selection: AppTest silently keeps its
    value when set to None. That must be rejected, not reported as a success — the same
    silent-revert principle as #12/#31/#55, verified here by attempt-and-check since None can't be
    told apart from a valid clear up front."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=PLACEHOLDER_APP)
    rt.run()
    rt.set_widget("reg", "b")  # give it a real selection first
    with pytest.raises(RuntimeError_, match="cannot be set to null"):
        rt.set_widget("reg", None)
    assert rt.snapshot().session_state["reg"] == "b"  # untouched — the no-op didn't corrupt it


def test_placeholder_real_options_still_work():
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=PLACEHOLDER_APP)
    rt.run()
    rt.set_widget("choose", "c")
    rt.set_widget("rad", "y")
    state = rt.snapshot().session_state
    assert state["choose"] == "c" and state["rad"] == "y"


def test_placeholder_null_round_trips_via_cli(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "ph.py"
    app.write_text(PLACEHOLDER_APP)
    assert main(["call", str(app), "--set", "Choose=null", "--state", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["choose"] is None


def test_every_placeholder_value_is_settable_back_verbatim():
    """The round-trip guarantee, stated directly, now including the null value."""
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=PLACEHOLDER_APP)
    rt.run()
    eng = Engine(rt)
    for w in eng.list_widgets()["widgets"]:
        eng.set_widget(w["identifier"], w["value"])  # value: null included — must not raise


# --- 0.5.0 #58: the text CLI surfaces the app's exception, matching --json/MCP ---
BOOM_APP = (
    "import streamlit as st\n"
    "st.title('Dashboard')\n"
    "st.text_input('Name', key='name')\n"
    "raise ValueError('kaboom: config missing')\n"
)


@pytest.mark.parametrize("argv", [
    ["call", "--read"],
    ["call", "--state"],
    ["inspect", "--layout"],
    ["inspect"],  # bare inspect surfaces it too
])
def test_text_cli_surfaces_the_app_exception(tmp_path, capsys, argv):
    """A crashed app used to render as a clean partial success on the text CLI: the structured
    exception the agent gets over MCP (and --json carries) was dropped from every text surface,
    breaking human<->agent parity on the error surface (#58)."""
    from streamlit_mcp.cli import main
    app = tmp_path / "boom.py"
    app.write_text(BOOM_APP)
    rc = main([argv[0], str(app), *argv[1:]])
    out = capsys.readouterr().out
    assert "kaboom: config missing" in out  # the exception is on stdout now
    assert rc == 0  # default: an app-level exception mirrors MCP's isError=False (not a failure)


@pytest.mark.parametrize("argv", [
    ["call", "--read", "--strict"],
    ["call", "--state", "--strict"],
    ["inspect", "--layout", "--strict"],
    ["inspect", "--strict"],
    ["call", "--read", "--json", "--strict"],  # --strict is orthogonal to output format
])
def test_strict_exits_nonzero_when_the_app_raised(tmp_path, argv):
    from streamlit_mcp.cli import main
    app = tmp_path / "boom.py"
    app.write_text(BOOM_APP)
    assert main([argv[0], str(app), *argv[1:]]) == 1


def test_strict_is_a_no_op_on_a_clean_app(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "ok.py"
    app.write_text("import streamlit as st\nst.title('fine')\n")
    assert main(["call", str(app), "--read", "--strict"]) == 0
    assert "exception" not in capsys.readouterr().out


def test_json_output_still_carries_the_exception_without_a_duplicate_line(tmp_path, capsys):
    """--json already had the field; it must stay in the payload and NOT also print a text line
    that would corrupt the JSON."""
    from streamlit_mcp.cli import main
    app = tmp_path / "boom.py"
    app.write_text(BOOM_APP)
    assert main(["call", str(app), "--read", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["exception"] == "kaboom: config missing"  # parses cleanly


def test_cli_exception_matches_mcp(tmp_path, capsys):
    """Parity, stated directly: the string the text CLI prints is the one MCP read_output returns."""
    from streamlit_mcp.cli import main
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    app = tmp_path / "boom.py"
    app.write_text(BOOM_APP)
    assert main(["call", str(app), "--read"]) == 0
    cli_out = capsys.readouterr().out
    rt = AppTestRuntime(str(app))
    rt.run()
    mcp_exception = Engine(rt).read_output()["exception"]
    assert mcp_exception in cli_out


def test_guardrail_denial_still_exits_one_regardless_of_strict(tmp_path, capsys):
    """A guardrail denial is a real failure (exit 1) independent of --strict — only an app-level
    exception is the exit-0-by-default case."""
    from streamlit_mcp.cli import main
    app = tmp_path / "ok.py"
    app.write_text("import streamlit as st\nst.text_input('Name', key='name')\n")
    assert main(["call", str(app), "--read-only", "--set", "Name=x"]) == 1


# --- 0.5.1 #60: value=None placeholders (text/number/date/time) round-trip null, uniformly ---
# The null-placeholder class is now handled by ONE shared path (schema: _make_nullable by value;
# write: _clear_to_none for any kind), so it can't re-open widget-by-widget the way #57 (fixed only
# selectbox/radio) left it open for text_input/text_area/number_input.
NULLABLE_APP = (
    "import streamlit as st\n"
    "st.text_input('Name', value=None, key='name')\n"
    "st.text_area('Bio', value=None, key='bio')\n"
    "st.number_input('Qty', value=None, key='qty')\n"
    "st.date_input('When', value=None, key='when')\n"
    "st.time_input('At', value=None, key='at')\n"
    "st.selectbox('Pick', ['a', 'b'], index=None, key='pick')\n"  # the #57 case, same path
)


def test_value_none_placeholders_advertise_a_nullable_schema():
    """Bug B: a widget reporting value: null must advertise a schema that permits null, or the
    read output contradicts its own schema. #57 fixed this for selectbox/radio; it stayed broken
    for text_input/text_area/number_input (and, latently, date/time) — now fixed uniformly (#60)."""
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=NULLABLE_APP)
    rt.run()
    for w in Engine(rt).list_widgets()["widgets"]:
        assert w["value"] is None, w["identifier"]
        t = w["schema"]["properties"]["value"]["type"]
        assert "null" in t, (w["identifier"], t)  # every null-valued widget's schema allows null


@pytest.mark.parametrize("identifier", ["name", "bio", "qty", "when", "at", "pick"])
def test_value_none_placeholder_round_trips_null(identifier):
    """Bug A + the round-trip: echoing the reported value: null back must store null, not corrupt
    it. text_input/text_area used to store the string 'None' (str(None)) at isError=False."""
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=NULLABLE_APP)
    rt.run()
    rt.set_widget(identifier, None)  # must not raise
    assert rt.snapshot().session_state[identifier] is None  # null, not the string "None"


def test_text_placeholder_null_is_not_stringified():
    """The specific #60 corruption, pinned: None on a text field must stay None, never become the
    literal string 'None' (the str(value) coercion added for #43 wrongly caught None)."""
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=NULLABLE_APP)
    rt.run()
    rt.set_widget("name", None)
    stored = rt.snapshot().session_state["name"]
    assert stored is None and stored != "None"


def test_text_field_still_stringifies_non_none_json_values():
    """The #43 behavior must survive: a JSON-typed non-None value on a text field still becomes its
    string (True -> 'True', 41 -> '41') — only None is exempted."""
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script="import streamlit as st\nst.text_input('C', key='c')\n")
    rt.run()
    rt.set_widget("c", True)
    assert rt.snapshot().session_state["c"] == "True"


@pytest.mark.parametrize("script,identifier,prior", [
    ("import streamlit as st\nst.text_input('R', key='r')\n", "r", ""),        # regular text (value="")
    ("import streamlit as st\nst.number_input('N', value=5, key='n')\n", "n", 5),  # regular number
    ("import streamlit as st\nst.selectbox('S', ['a', 'b'], key='s')\n", "s", "a"),  # regular selectbox
])
def test_non_nullable_widget_rejects_null_atomically(script, identifier, prior):
    """A widget that is NOT a placeholder has no no-value state: AppTest silently keeps its value
    when set to null. That must be rejected (not reported as a success), with the prior value
    intact — the same silent-revert guarantee as #12/#31/#55, verified by attempt-and-check since
    null can't be told apart from a valid clear up front."""
    from streamlit_mcp.runtime import AppTestRuntime, RuntimeError_
    rt = AppTestRuntime(script=script)
    rt.run()
    with pytest.raises(RuntimeError_, match="cannot be set to null"):
        rt.set_widget(identifier, None)
    assert rt.snapshot().session_state[identifier] == prior  # untouched


def test_every_advertised_value_round_trips_including_nulls():
    """The round-trip guarantee stated directly, now spanning the whole null-placeholder class:
    every value list_widgets advertises (null included) can be sent straight back."""
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=NULLABLE_APP)
    rt.run()
    eng = Engine(rt)
    for w in eng.list_widgets()["widgets"]:
        eng.set_widget(w["identifier"], w["value"])  # value: null included — must not raise


def test_number_input_none_schema_keeps_its_bounds():
    """Making the type nullable must not drop the min/max the schema already carried."""
    from streamlit_mcp.elements import tool_schema_for
    schema = tool_schema_for({"kind": "number_input", "value": None,
                              "constraints": {"min": 0, "max": 10}})["properties"]["value"]
    assert schema["type"] == ["number", "null"]
    assert schema["minimum"] == 0 and schema["maximum"] == 10
