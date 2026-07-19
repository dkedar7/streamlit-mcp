"""Every surface must report the same facts about an app.

streamlit-mcp exposes an app three ways — the human text CLI, the same command's ``--json``, and
the MCP tools — and the promise underneath all of them is that a human and an agent see the same
app. That promise has broken three times, always the same shape and always fixed one surface at a
time: **#1** (text ``--layout`` dropped the ``unsupported`` section that ``--json`` carried),
**#58** (the text CLI dropped the ``exception`` that ``--json`` and MCP carried), **#64** (bare
``inspect --json`` dropped the ``exception`` its own text form printed, and so did
``call --state --json``).

Patching the reported surface each time is what let the family re-open. These tests assert the
invariant across the whole matrix instead, so the next dropped field fails here rather than in
tomorrow morning's dogfood issue.

MCP is covered transitively: every MCP tool returns its Engine dict verbatim (``server.py``), so
``test_json_payload_is_exactly_what_mcp_serves`` pins the CLI's ``--json`` to that same dict.

Exception parity is deliberately not duplicated here — it is asserted over all four command forms
by ``test_json_form_reports_the_exception_its_text_form_prints`` (#64) in test_release_fixes.py.
"""

from __future__ import annotations

import json

import pytest

# Keys are word-only and outputs single-line on purpose: the text surface is positional, and this
# fixture exists to compare WHAT is reported, not to test the text renderer's edge cases.
PARITY_APP = (
    "import streamlit as st\n"
    "st.title('Report')\n"
    "st.text_input('Name', value='ada', key='name')\n"
    "st.number_input('Qty', value=3, key='qty')\n"
    "st.selectbox('Env', ['dev', 'prod'], key='env')\n"
    "st.pills('Mode', ['fast', 'slow'], key='mode')\n"
    "st.checkbox('Agree', key='agree')\n"
    "st.success('saved')\n"
    "st.error('nope')\n"
    "st.metric('Rev', 12, delta=3)\n"
    "st.file_uploader('Doc', key='doc')\n"   # unsupported -> must appear on every surface
)


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "parity.py"
    path.write_text(PARITY_APP)
    return str(path)


def _run(capsys, argv):
    """(text, json) for the same command — the pair that has to agree."""
    from streamlit_mcp.cli import main
    assert main(argv) == 0
    text = capsys.readouterr().out
    assert main([*argv, "--json"]) == 0
    return text, json.loads(capsys.readouterr().out)


def _widget_lines(text):
    # `  {kind:<13} {identifier:<14} = {value!r}` — two-space indent; session_state uses four.
    return [ln for ln in text.splitlines()
            if ln.startswith("  ") and not ln.startswith("   ") and " = " in ln]


def _indented_under(text, header):
    """The four-space entries printed under a `  header:` line."""
    lines = text.splitlines()
    if header not in lines:
        return []
    out = []
    for ln in lines[lines.index(header) + 1:]:
        if not ln.startswith("    "):
            break
        out.append(ln.strip())
    return out


@pytest.mark.parametrize("argv", [["inspect"], ["inspect", "--layout"]], ids=["bare", "layout"])
def test_every_widget_is_reported_on_both_surfaces_with_the_same_value(capsys, app, argv):
    """A widget dropped from — or renamed on — one surface means a human and an agent disagree
    about what the app contains."""
    text, payload = _run(capsys, [argv[0], app, *argv[1:]])
    lines = _widget_lines(text)
    assert len(lines) == len(payload["widgets"]), (
        f"text shows {len(lines)} widgets, --json shows {len(payload['widgets'])}"
    )
    for w in payload["widgets"]:
        assert any(
            w["identifier"] in ln and f"= {w['value']!r}" in ln for ln in lines
        ), f"{w['identifier']!r} (= {w['value']!r}) is in --json but not in the text output"


def test_every_output_is_reported_on_both_surfaces(capsys, app):
    """The read surface an agent acts on: if the text form shows `st.error` and `--json` doesn't
    (or the reverse), the two callers reach different conclusions about what the app just said."""
    for argv in (["call", app, "--read"], ["inspect", app, "--layout"]):
        text, payload = _run(capsys, argv)
        rendered = [ln for ln in text.splitlines() if ln.startswith("  [")]
        assert len(rendered) == len(payload["outputs"]), (
            f"{argv[0]}: text shows {len(rendered)} outputs, --json shows {len(payload['outputs'])}"
        )
        for o in payload["outputs"]:
            head = o["text"].splitlines()[0] if o["text"] else ""
            assert any(f"[{o['kind']}]" in ln and head in ln for ln in rendered), (
                f"{argv[0]}: output {o['kind']}={head!r} is in --json but not in the text output"
            )


def test_session_state_is_reported_on_both_surfaces(capsys, app):
    for argv, header in (
        (["call", app, "--state"], None),
        (["inspect", app, "--layout"], "  session_state:"),
    ):
        text, payload = _run(capsys, argv)
        state = payload if header is None else payload["session_state"]
        shown = text.splitlines() if header is None else _indented_under(text, header)
        for key in state:
            assert any(key in ln for ln in shown), (
                f"{argv[0]}: session_state key {key!r} is in --json but not in the text output"
            )


def test_unsupported_elements_are_reported_on_both_surfaces(capsys, app):
    """This is #1 exactly: the text form dropped the `unsupported` section while `--json` carried
    it, so a human reading the app never learned a widget existed that the agent was told about."""
    text, payload = _run(capsys, ["inspect", app, "--layout"])
    names = [u["element"] for u in payload["unsupported"]]
    assert names, "fixture no longer contains an unsupported widget — update PARITY_APP"
    shown = _indented_under(text, "  unsupported:")
    assert len(shown) == len(names)
    for name in names:
        assert any(ln.startswith(f"{name}:") for ln in shown), (
            f"unsupported element {name!r} is in --json but not in the text output"
        )


@pytest.mark.parametrize("argv,method", [
    (["inspect"], "list_widgets"),
    (["inspect", "--layout"], "get_layout"),
    (["call", "--read"], "read_output"),
    (["call", "--state"], "get_state"),
])
def test_json_payload_is_exactly_what_mcp_serves(capsys, app, argv, method):
    """Ties the third surface in without a stdio round-trip: each MCP tool returns its Engine dict
    verbatim, so if the CLI's --json payload equals that dict, all three surfaces agree by
    construction. A field added to one CLI surface but not the engine shows up here."""
    from streamlit_mcp.cli import main
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime

    assert main([argv[0], app, *argv[1:], "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    rt = AppTestRuntime(app)
    rt.run()
    served = json.loads(json.dumps(getattr(Engine(rt, app_path=app), method)(), default=str))

    # The CLI adds `tools` (its counterpart of the MCP tool list) and injects `exception` where the
    # engine call doesn't carry one (#64); neither is a disagreement about the app itself.
    payload.pop("tools", None)
    for key in set(payload) - set(served):
        assert key == "exception", f"--json has {key!r}, which MCP's {method} does not serve"
        payload.pop(key)
    assert payload == served, f"{argv} --json diverges from what MCP {method} serves"
