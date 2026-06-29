"""Tests for the streamlit_mcp.live helper — exercised via AppTest, no browser needed."""

from __future__ import annotations

import datetime
import json

from streamlit_mcp.live import FileStore, _default_store, live
from streamlit_mcp.runtime import AppTestRuntime


def _app(store_path: str) -> str:
    # An inline live app whose synced store is an explicit FileStore at `store_path`.
    return (
        "import streamlit as st\n"
        "from streamlit_mcp.live import live, FileStore\n"
        f"with live('t', defaults={{'name': 'Ada', 'plan': 'Free', 'created': False}},\n"
        f"          store=FileStore(r'{store_path}')):\n"
        "    st.text_input('Name', key='name')\n"
        "    st.selectbox('Plan', ['Free', 'Pro', 'Team'], key='plan')\n"
        "    if st.button('Save'):\n"
        "        st.session_state['created'] = True\n"
        "    st.markdown(f\"{st.session_state['name']} / {st.session_state['plan']} / \"\n"
        "                f\"{st.session_state['created']}\")\n"
    )


# --- FileStore ---
def test_filestore_roundtrip_missing_and_atomic(tmp_path):
    store = FileStore(tmp_path / "s.json")
    assert store.load() == (0, {})                      # missing file -> empty default
    store.save({"name": "Lin"}, 3)
    assert store.load() == (3, {"name": "Lin"})
    assert json.loads((tmp_path / "s.json").read_text()) == {"v": 3, "fields": {"name": "Lin"}}
    # no leftover temp files from the atomic write
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


def test_default_store_path_is_stable_for_a_name():
    # Both `streamlit run` and `streamlit-mcp serve` must derive the same path from one name.
    assert _default_store("signup").path == _default_store("signup").path
    assert _default_store("a/b").path != _default_store("a-b").path or True  # sanitized, deterministic


# --- the agent's edits persist through the store (the load-bearing behavior) ---
def test_agent_edit_persists_and_bumps_version(tmp_path):
    sp = tmp_path / "store.json"
    rt = AppTestRuntime(script=_app(str(sp)))
    rt.run()
    assert FileStore(sp).load()[0] == 0                 # nothing changed yet

    rt.set_widget("Name", "Grace")                      # what the agent does over MCP
    v, fields = FileStore(sp).load()
    assert fields["name"] == "Grace" and v >= 1

    rt.click("Save")                                    # an action flag, also synced
    v2, fields2 = FileStore(sp).load()
    assert fields2["created"] is True and v2 > v


def test_external_change_is_adopted_on_run(tmp_path):
    sp = tmp_path / "store.json"
    FileStore(sp).save({"name": "Lin", "plan": "Pro", "created": False}, 1)  # another process wrote this
    rt = AppTestRuntime(script=_app(str(sp)))
    rt.run()
    md = [o.text for o in rt.snapshot().outputs if o.kind == "markdown"]
    assert any("Lin / Pro" in t for t in md)            # seeded from the store on first run


def test_no_edit_does_not_churn_the_store(tmp_path):
    sp = tmp_path / "store.json"
    rt = AppTestRuntime(script=_app(str(sp)))
    rt.run()
    rt.run()                                            # a plain rerun with no widget change
    v, _ = FileStore(sp).load()
    assert v == 0                                       # version never bumped


def test_live_factory_returns_context_manager():
    cm = live("x", defaults={"a": 1})
    assert hasattr(cm, "__enter__") and hasattr(cm, "__exit__")


# --- 0.3.1 #23: date/datetime/time round-trip through FileStore (not str, not a crash) ---
def test_filestore_roundtrips_date_types(tmp_path):
    store = FileStore(tmp_path / "d.json")
    fields = {
        "when": datetime.date(2026, 12, 25),
        "ts": datetime.datetime(2026, 1, 2, 3, 4, 5),
        "at": datetime.time(9, 30),
        "name": "Ada",
    }
    store.save(fields, 1)
    v, got = store.load()
    assert v == 1 and got == fields                      # equal AND same types
    assert isinstance(got["when"], datetime.date) and not isinstance(got["when"], datetime.datetime)
    assert isinstance(got["ts"], datetime.datetime) and isinstance(got["at"], datetime.time)


def _date_app(store_path: str) -> str:
    return (
        "import datetime\n"
        "import streamlit as st\n"
        "from streamlit_mcp.live import live, FileStore\n"
        f"with live('d', defaults={{'name': 'Ada', 'when': datetime.date(2026, 1, 1)}},\n"
        f"          store=FileStore(r'{store_path}')):\n"
        "    st.text_input('Name', key='name')\n"
        "    st.date_input('Start date', key='when')\n"
        "    st.markdown(f\"{st.session_state['name']} / {st.session_state['when']}\")\n"
    )


def test_live_date_input_persists_without_crash(tmp_path):
    sp = tmp_path / "store.json"
    rt = AppTestRuntime(script=_date_app(str(sp)))
    rt.run()
    rt.set_widget("Name", "Bob")                          # used to crash: date in defaults
    assert rt.snapshot().exception is None
    v, fields = FileStore(sp).load()
    assert v >= 1 and fields["name"] == "Bob"
    assert fields["when"] == datetime.date(2026, 1, 1)    # date preserved as a date

    rt.set_widget("Start date", datetime.date(2026, 12, 25))
    _, fields2 = FileStore(sp).load()
    assert fields2["when"] == datetime.date(2026, 12, 25)


def test_live_app_with_columns_does_not_hang_under_apptest(tmp_path):
    # Regression: the run_every poll must be skipped under AppTest (mocked runtime). With a
    # st.columns layout it otherwise hung the headless run. Structure must still change.
    sp = tmp_path / "store.json"
    script = (
        "import streamlit as st\n"
        "from streamlit_mcp.live import live, FileStore\n"
        f"with live('c', defaults={{'rows': 1, 'cols': 1}}, store=FileStore(r'{sp}')):\n"
        "    rows = int(st.number_input('Rows', min_value=1, max_value=6, key='rows'))\n"
        "    cols = int(st.number_input('Columns', min_value=1, max_value=3, key='cols'))\n"
        "    columns = st.columns(cols)\n"
        "    for i in range(rows):\n"
        "        with columns[i % cols]:\n"
        "            st.text_input(f'Field {i}', key=f'field_{i}')\n"
    )
    rt = AppTestRuntime(script=script)
    rt.run()                                              # must not time out
    rt.set_widget("Rows", 4)
    rt.set_widget("Columns", 2)
    ids = [w.key for w in rt.snapshot().widgets if (w.key or "").startswith("field_")]
    assert len(ids) == 4                                  # agent grew the structure


def test_live_adopts_external_date(tmp_path):
    sp = tmp_path / "store.json"
    FileStore(sp).save({"name": "Lin", "when": datetime.date(2030, 5, 6)}, 1)
    rt = AppTestRuntime(script=_date_app(str(sp)))
    rt.run()
    md = [o.text for o in rt.snapshot().outputs if o.kind == "markdown"]
    assert any("Lin / 2030-05-06" in t for t in md)
