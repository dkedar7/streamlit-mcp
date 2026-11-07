"""0.10.0: form membership on the widget model (#189), --redact (#191), `config` (#190)."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path

import pytest

TWO_FORMS_APP = (
    "import streamlit as st\n"
    "with st.form('login'):\n"
    "    st.text_input('Username', key='user')\n"
    "    st.text_input('Password', key='pw')\n"
    "    st.form_submit_button('Log in')\n"
    "with st.form('search'):\n"
    "    st.text_input('Query', key='q')\n"
    "    st.form_submit_button('Search')\n"
    "st.text_input('Outside', key='out')\n"
)

SECRET_APP = (
    "import streamlit as st\n"
    "if 'access_token' not in st.session_state:\n"
    "    st.session_state['access_token'] = 'sk-SUPER-SECRET-123'\n"
    "st.text_input('Name', key='name')\n"
    "st.write('hello')\n"
)
SECRET = "sk-SUPER-SECRET-123"


def _engine(script, guard=None):
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=script)
    rt.run()
    return Engine(rt, guard=guard)


# --- #189: every form field and submit button says which st.form it belongs to ---
def test_widgets_advertise_their_form_on_every_surface():
    eng = _engine(TWO_FORMS_APP)
    for surface in (eng.list_widgets(), eng.get_layout()):
        forms = {w["label"]: w["form"] for w in surface["widgets"]}
        assert forms == {"Username": "login", "Password": "login", "Log in": "login",
                         "Query": "search", "Search": "search", "Outside": None}


def test_an_agent_can_pick_the_submit_for_the_fields_it_set():
    """The pairing the issue asks for: the button whose ``form`` matches the fields' ``form``."""
    eng = _engine(TWO_FORMS_APP)
    widgets = eng.list_widgets()["widgets"]
    eng.set_widget("user", "alice")
    form = next(w["form"] for w in widgets if w["identifier"] == "user")
    submit = next(w for w in widgets if w["action"] and w["form"] == form)
    eng.click(submit["identifier"])
    assert eng.get_state()["user"] == "alice"


def test_cli_inspect_shows_form_membership(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "forms.py"
    app.write_text(TWO_FORMS_APP)
    assert main(["inspect", str(app)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(" user " in ln and "[form: login]" in ln for ln in lines)
    assert any(" out " in ln and "[form:" not in ln for ln in lines)


# --- #191: --redact keeps a named session_state key off every read surface ---
def _redacting(*keys):
    from streamlit_mcp.guardrails import Guardrails
    return _engine(SECRET_APP, guard=Guardrails(redact_keys=set(keys)))


def test_a_redacted_non_widget_key_never_appears_in_any_read():
    eng = _redacting("access_token")
    reads = [eng.get_state(), eng.read_output(), eng.get_layout(), eng.list_widgets(),
             eng.set_widget("name", "x")]
    for out in reads:
        assert SECRET not in json.dumps(out, default=str)
    assert eng.get_state() == {"name": "x"}


def test_without_redact_the_key_is_returned():
    assert _engine(SECRET_APP).get_state()["access_token"] == SECRET


def test_a_redacted_widget_key_hides_its_value_but_stays_drivable():
    eng = _redacting("name")
    eng.set_widget("name", "private")
    widget = next(w for w in eng.list_widgets()["widgets"] if w["identifier"] == "name")
    assert widget["redacted"] is True and "value" not in widget
    assert "name" not in eng.get_state()
    assert "private" not in json.dumps(eng.get_layout(), default=str)
    assert "value" in widget["schema"]["properties"]  # still settable


def test_redact_composes_with_the_allow_list():
    """--allow keeps non-widget app state by design, which is why it can't hide a token."""
    from streamlit_mcp.guardrails import Guardrails
    eng = _engine(SECRET_APP, guard=Guardrails(allow_list={"name"}, redact_keys={"access_token"}))
    assert eng.get_state() == {"name": ""}


def test_cli_redact(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "secret.py"
    app.write_text(SECRET_APP)
    assert main(["call", str(app), "--redact", "access_token", "--set", "name=x",
                 "--state", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"name": "x"}
    assert main(["inspect", str(app), "--redact", "name", "--layout"]) == 0
    out = capsys.readouterr().out
    assert "<redacted>" in out and SECRET in out  # only the named key is withheld


def test_mcp_redact_over_a_real_client(tmp_path):
    from fastmcp import Client

    from streamlit_mcp.guardrails import Guardrails
    from streamlit_mcp.server import build_server
    app = tmp_path / "secret.py"
    app.write_text(SECRET_APP)

    async def reads():
        server = build_server(str(app), guard=Guardrails(redact_keys={"access_token"}))
        async with Client(server) as c:
            return [(await c.call_tool(t, {})).content[0].text
                    for t in ("get_state", "read_output", "get_layout", "list_widgets")]

    for text in asyncio.run(reads()):
        assert SECRET not in text


# --- #190: `config` prints client wiring with the app path made absolute ---
def _config(capsys, *argv):
    from streamlit_mcp.cli import main
    rc = main(["config", *argv])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_config_resolves_a_relative_path(tmp_path, monkeypatch, capsys):
    (tmp_path / "app.py").write_text("import streamlit as st\n")
    monkeypatch.chdir(tmp_path)
    rc, out, err = _config(capsys, "app.py")
    assert rc == 0 and err == ""
    assert json.loads(out) == {"mcpServers": {"streamlit-mcp": {
        "command": "uvx", "args": ["streamlit-mcp", "serve", str((tmp_path / "app.py").resolve())]}}}


def test_config_carries_guardrails_and_name(tmp_path, capsys):
    app = tmp_path / "app.py"
    app.write_text("")
    rc, out, _ = _config(capsys, str(app), "--name", "myapp", "--client", "cursor", "--read-only",
                         "--allow", "q", "--redact", "access_token")
    entry = json.loads(out)["mcpServers"]["myapp"]
    assert entry["args"][3:] == ["--read-only", "--allow", "q", "--redact", "access_token"]


def test_config_for_claude_code_is_a_runnable_command(tmp_path, capsys):
    app = tmp_path / "my app.py"  # a space must survive the shell
    app.write_text("")
    rc, out, _ = _config(capsys, str(app), "--client", "claude-code")
    assert rc == 0
    assert shlex.split(out) == ["claude", "mcp", "add", "streamlit-mcp", "--", "uvx",
                                "streamlit-mcp", "serve", str(app.resolve())]


def test_config_for_http_points_at_the_url_with_the_token(tmp_path, capsys):
    app = tmp_path / "app.py"
    app.write_text("")
    rc, out, err = _config(capsys, str(app), "--transport", "http", "--port", "9000",
                           "--bearer-token", "T")
    assert json.loads(out) == {"mcpServers": {"streamlit-mcp": {
        "url": "http://127.0.0.1:9000/mcp", "headers": {"Authorization": "Bearer T"}}}}
    assert "streamlit-mcp serve" in err and "--bearer-token T" in err
    rc, out, _ = _config(capsys, str(app), "--transport", "http", "--client", "claude-code")
    assert shlex.split(out) == ["claude", "mcp", "add", "--transport", "http", "streamlit-mcp",
                                "http://127.0.0.1:8000/mcp"]


def test_config_refuses_http_for_claude_desktop(tmp_path, capsys):
    app = tmp_path / "app.py"
    app.write_text("")
    rc, out, err = _config(capsys, str(app), "--transport", "http", "--client", "claude-desktop")
    assert rc == 1 and out == "" and "stdio" in err


def test_config_warns_on_a_missing_app(tmp_path, capsys):
    rc, out, err = _config(capsys, str(tmp_path / "nope.py"))
    assert rc == 0 and "does not exist" in err
    assert json.loads(out)["mcpServers"]["streamlit-mcp"]["args"][-1].endswith("nope.py")


# --- 0.10.1 #193: redacting a value must not change the widget's advertised schema ---
REDACT_SHAPES_APP = (
    "import streamlit as st\n"
    "st.text_input('Token', value='secret123', key='token')\n"
    "st.selectbox('Role', ['admin', 'user'], key='role')\n"
    "st.slider('Band', 0, 100, (20, 80), key='band')\n"
    "st.pills('Tags', ['a', 'b'], selection_mode='multi', default=['a'], key='tags')\n"
    "st.selectbox('Maybe', ['x', 'y'], index=None, key='maybe')\n"
)


def test_redaction_leaves_every_schema_exactly_as_advertised_without_it():
    from streamlit_mcp.guardrails import Guardrails

    def schemas(eng):
        return {w["identifier"]: w["schema"] for w in eng.list_widgets()["widgets"]}

    keys = {"token", "role", "band", "tags", "maybe"}
    plain = schemas(_engine(REDACT_SHAPES_APP))
    redacted_eng = _engine(REDACT_SHAPES_APP, guard=Guardrails(redact_keys=keys))
    assert schemas(redacted_eng) == plain
    # and the nullability it advertises is the nullability set_widget honours
    assert "null" not in json.dumps(plain["token"]) and "null" not in json.dumps(plain["role"])
    assert "null" in json.dumps(plain["maybe"])
    redacted_eng.set_widget("maybe", None)
    redacted_eng.set_widget("band", [30, 70])
    widgets = {w["identifier"]: w for w in redacted_eng.list_widgets()["widgets"]}
    assert all(widgets[k]["redacted"] and "value" not in widgets[k] for k in keys)


# --- 0.10.2 #195: config never prints a server command that serve would refuse ---
def test_config_refuses_a_public_http_host_without_a_token_like_serve_does(tmp_path, capsys):
    from streamlit_mcp.server import serve
    app = tmp_path / "app.py"
    app.write_text("")
    rc, out, err = _config(capsys, str(app), "--transport", "http", "--host", "0.0.0.0")
    assert rc == 1 and out == "" and "Refusing to serve http" in err
    with pytest.raises(ValueError) as served:
        serve(str(app), transport="http", host="0.0.0.0")
    assert str(served.value) in err  # the same check, the same message


def test_config_points_a_wildcard_bind_at_a_connectable_url(tmp_path, capsys):
    app = tmp_path / "app.py"
    app.write_text("")
    rc, out, err = _config(capsys, str(app), "--transport", "http", "--host", "0.0.0.0",
                           "--bearer-token", "T")
    assert rc == 0
    assert json.loads(out)["mcpServers"]["streamlit-mcp"]["url"] == "http://127.0.0.1:8000/mcp"
    assert "--host 0.0.0.0" in err and "this machine's address" in err  # serve still binds all


def test_config_brackets_an_ipv6_host(tmp_path, capsys):
    app = tmp_path / "app.py"
    app.write_text("")
    rc, out, _ = _config(capsys, str(app), "--transport", "sse", "--host", "::1")
    assert json.loads(out)["mcpServers"]["streamlit-mcp"]["url"] == "http://[::1]:8000/sse"
