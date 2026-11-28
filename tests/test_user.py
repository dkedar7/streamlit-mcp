"""`--user key=value` sets what the served app reads as st.user, so an auth-gated app's logged-in
surface is reachable (#235). AppTest has a `user` dict from Streamlit ~1.67; on the locked 1.58
its runner hard-codes the test user, which runtime._seeded_user works around. Run these with
``uv run --with streamlit==<latest> pytest tests/test_user.py`` as well as on the locked version.
"""

from __future__ import annotations

import asyncio
import json

import pytest

GATED_APP = (
    "import streamlit as st\n"
    "if st.user.is_logged_in:\n"
    "    st.write('logged in as', st.user.email)\n"
    "    st.text_input('Query', key='q')\n"
    "    if st.session_state.q:\n"
    "        st.success(f'searched {st.session_state.q} for {st.user.email}')\n"
    "else:\n"
    "    st.info('Please log in')\n"
)
DEFENSIVE_APP = (
    "import streamlit as st\n"
    "if st.user.get('is_logged_in', False):\n"
    "    st.button('Export')\n"
    "else:\n"
    "    st.info('Please log in')\n"
    "st.write('keys: ' + ','.join(sorted(st.user.to_dict())))\n"
)
ALICE = {"is_logged_in": True, "email": "alice@example.com"}


def _engine(script, user=None):
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=script, user=user)
    rt.run()
    return Engine(rt)


def _texts(out):
    return [o["text"] for o in out["outputs"]]


def test_a_logged_in_user_reaches_the_gated_widgets_and_keeps_it_across_reruns():
    eng = _engine(GATED_APP, ALICE)
    layout = eng.get_layout()
    assert layout.get("exception") is None
    assert [w["identifier"] for w in layout["widgets"]] == ["q"]
    out = eng.set_widget("q", "cats")  # a rerun must still see the same user
    assert "searched cats for alice@example.com" in _texts(out)


def test_a_logged_out_user_renders_the_logged_out_branch():
    eng = _engine(GATED_APP, {"is_logged_in": False})
    layout = eng.get_layout()
    assert layout.get("exception") is None and layout["widgets"] == []
    assert _texts(layout) == ["Please log in"]


def test_without_user_the_app_sees_appTests_default_unchanged():
    """No --user, no change: st.user has no is_logged_in, as in a browser with no [auth]."""
    eng = _engine(GATED_APP)
    assert "is_logged_in" in eng.get_layout().get("exception", "")
    assert "keys: email" in " ".join(_texts(_engine(DEFENSIVE_APP).read_output()))


def test_the_user_replaces_the_default_test_user_rather_than_merging():
    eng = _engine(DEFENSIVE_APP, {"is_logged_in": True})
    out = eng.read_output()
    assert any("keys: is_logged_in" in t for t in _texts(out))
    assert [w["identifier"] for w in eng.list_widgets()["widgets"]] == ["Export"]


def test_the_seeded_user_does_not_leak_into_another_runtime():
    _engine(GATED_APP, ALICE)
    assert "is_logged_in" in _engine(GATED_APP).get_layout().get("exception", "")


@pytest.mark.parametrize("items,expected", [
    (["is_logged_in=true", "email=alice@example.com"], ALICE),
    (["sub=10769150350006150715113082367"], {"sub": "10769150350006150715113082367"}),
    (["name=Alice = Admin"], {"name": "Alice = Admin"}),
    (["picture=null"], {"picture": None}),
    (['tokens={"access": "abc"}'], {"tokens": {"access": "abc"}}),
    (["email_verified=false"], {"email_verified": False}),
])
def test_parse_user(items, expected):
    from streamlit_mcp.cli import parse_user
    assert parse_user(items) == expected


@pytest.mark.parametrize("items,match", [
    (["is_logged_in"], "key=value"),
    (["=x"], "key=value"),
    (["is_logged_in=yes"], "true or false"),
    (["is_logged_in=1"], "true or false"),
    (["tokens={bad"], "not valid JSON"),
])
def test_parse_user_rejects(items, match):
    from streamlit_mcp.cli import parse_user
    with pytest.raises(ValueError, match=match):
        parse_user(items)


def test_parse_user_none_without_flags():
    from streamlit_mcp.cli import parse_user
    assert parse_user(None) is None and parse_user([]) is None


def test_cli_inspect_and_call_take_user(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "gated.py"
    app.write_text(GATED_APP)
    assert main(["inspect", str(app), "--json", "--user", "is_logged_in=true",
                 "--user", "email=alice@example.com"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [w["identifier"] for w in payload["widgets"]] == ["q"]
    assert main(["call", str(app), "--user", "is_logged_in=true", "--user",
                 "email=alice@example.com", "--set", "q=cats", "--read"]) == 0
    assert "[success] searched cats for alice@example.com" in capsys.readouterr().out


def test_cli_rejects_a_bad_user_cleanly(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "gated.py"
    app.write_text(GATED_APP)
    assert main(["inspect", str(app), "--user", "is_logged_in=yes"]) == 1
    assert "true or false" in capsys.readouterr().err


def test_config_carries_user_and_refuses_a_bad_one(tmp_path, capsys):
    from streamlit_mcp.cli import main
    app = tmp_path / "gated.py"
    app.write_text(GATED_APP)
    assert main(["config", str(app), "--user", "is_logged_in=true",
                 "--user", "email=alice@example.com"]) == 0
    args = json.loads(capsys.readouterr().out)["mcpServers"]["streamlit-mcp"]["args"]
    assert args[-4:] == ["--user", "is_logged_in=true", "--user", "email=alice@example.com"]
    assert main(["config", str(app), "--user", "is_logged_in=maybe"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "true or false" in captured.err


def test_startup_status_names_the_user_keys_not_their_values():
    from streamlit_mcp.server import startup_status
    status = startup_status("app.py", "stdio", "127.0.0.1", 8000, None,
                            {"is_logged_in": True, "tokens": {"access": "SECRET"}})
    assert "st.user:    set by --user (is_logged_in, tokens)" in status
    assert "SECRET" not in status
    assert "st.user" not in startup_status("app.py", "stdio", "127.0.0.1", 8000, None)


def test_mcp_sessions_see_the_user(tmp_path):
    from fastmcp import Client

    from streamlit_mcp.server import build_server
    app = tmp_path / "gated.py"
    app.write_text(GATED_APP)

    async def drive():
        async with Client(build_server(str(app), user=ALICE)) as c:
            widgets = json.loads((await c.call_tool("list_widgets", {})).content[0].text)
            out = json.loads((await c.call_tool(
                "set_widget", {"identifier": "q", "value": "cats"})).content[0].text)
            return widgets, out

    widgets, out = asyncio.run(drive())
    assert [w["identifier"] for w in widgets["widgets"]] == ["q"]
    assert "searched cats for alice@example.com" in _texts(out)
