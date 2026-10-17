"""U6 tests — the human-first CLI and parity with the engine/MCP path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamlit_mcp.cli import _parse_value, _split_assignment, build_parser, main
from streamlit_mcp.decorator import clear_registry

APP = str(Path(__file__).parent / "apps" / "sample_app.py")
SEMANTIC_APP = str(Path(__file__).parent / "apps" / "semantic_app.py")
RAISES_APP = str(Path(__file__).parent / "apps" / "raises_app.py")
CHAT_APP = str(Path(__file__).parent / "apps" / "chat_app.py")


@pytest.fixture(autouse=True)
def _clean_registry():
    # The @mcp_tool registry is process-global; keep CLI tests from leaking into each other.
    clear_registry()
    yield
    clear_registry()


def _run(argv):
    return main(argv)


def test_inspect_json_lists_widgets(capsys):
    assert _run(["inspect", APP, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["widgets"]) == 10


def test_call_set_and_read_parity(capsys):
    """AE4: the CLI runs the same set->read sequence an agent does, same result."""
    assert _run(["call", APP, "--set", "Name=agent", "--read"]) == 0
    assert "Hello, agent!" in capsys.readouterr().out


def test_call_click_and_state(capsys):
    assert _run(["call", APP, "--set", "Name=agent", "--click", "Save", "--state"]) == 0
    out = capsys.readouterr().out
    assert "saves = 1" in out
    assert "'agent'" in out  # name applied


def test_call_typed_values(capsys):
    # JSON-typed values: bool for checkbox, int for number, list for multiselect
    assert _run(["call", APP, "--set", "Agree=true", "--set", "Age=41",
                 "--set", 'Tags=["a","b"]', "--state"]) == 0
    out = capsys.readouterr().out
    assert "'agree': True" in out or "True" in out


def test_read_only_blocks_via_cli(capsys):
    rc = _run(["call", APP, "--read-only", "--set", "Name=x"])
    assert rc == 1
    assert "read-only" in capsys.readouterr().err


def test_allow_list_blocks_via_cli(capsys):
    rc = _run(["call", APP, "--allow", "Name", "--set", "Level=3"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "allow-list" in err


def test_allow_list_permits_listed(capsys):
    assert _run(["call", APP, "--allow", "Name", "--set", "Name=ok", "--read"]) == 0
    assert "Hello, ok!" in capsys.readouterr().out


def test_bad_set_format_errors(capsys):
    assert _run(["call", APP, "--set", "noequals"]) == 1


def test_parse_value_types():
    assert _parse_value("true") is True
    assert _parse_value("41") == 41
    assert _parse_value("green") == "green"
    assert _parse_value('["a","b"]') == ["a", "b"]


def test_split_assignment():
    assert _split_assignment("Name=agent") == ("Name", "agent")
    assert _split_assignment("Age=41") == ("Age", 41)


def test_serve_transport_choices():
    # argparse rejects an invalid transport with SystemExit(2)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["serve", APP, "--transport", "pigeon"])


# --- 0.3.1 #21: @mcp_tool semantic tools are reachable from the CLI (human<->agent parity) ---
def test_inspect_lists_semantic_tool(capsys):
    assert _run(["inspect", SEMANTIC_APP]) == 0
    out = capsys.readouterr().out
    assert "tools:" in out and "reset_all" in out


def test_inspect_json_includes_tools(capsys):
    assert _run(["inspect", SEMANTIC_APP, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [t["name"] for t in data.get("tools", [])] == ["reset_all"]


def test_call_invokes_semantic_tool(capsys):
    assert _run(["call", SEMANTIC_APP, "--tool", "reset_all"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_call_unknown_tool_errors(capsys):
    assert _run(["call", SEMANTIC_APP, "--tool", "nope"]) == 1
    assert "no semantic tool" in capsys.readouterr().err


def test_inspect_without_tools_has_no_tools_section(capsys):
    # an app with no @mcp_tool must not show a tools section (registry stays clean)
    assert _run(["inspect", APP]) == 0
    assert "tools:" not in capsys.readouterr().out


# --- 0.3.3 #26: read-only / allow-list gate `call --tool` ---
def test_call_tool_blocked_read_only(capsys):
    assert _run(["call", SEMANTIC_APP, "--read-only", "--tool", "reset_all"]) == 1
    assert "read-only" in capsys.readouterr().err


def test_call_tool_blocked_by_allow_list(capsys):
    assert _run(["call", SEMANTIC_APP, "--allow", "Name", "--tool", "reset_all"]) == 1
    assert "allow-list" in capsys.readouterr().err


def test_call_tool_permitted_when_allow_listed(capsys):
    assert _run(["call", SEMANTIC_APP, "--allow", "reset_all", "--tool", "reset_all"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


# --- 0.3.3 #27: an app exception must not corrupt stdout / --json ---
def test_json_stays_clean_when_app_raises(capsys):
    assert _run(["inspect", RAISES_APP, "--json"]) == 0
    json.loads(capsys.readouterr().out)                     # valid JSON, no traceback on stdout


def test_call_read_json_clean_and_surfaces_exception(capsys):
    assert _run(["call", RAISES_APP, "--read", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)              # stdout is valid JSON
    assert data.get("exception") and "kaboom" in data["exception"]


# --- 0.2.3 #15: inspect on a missing/unloadable app prints a clean error, not a traceback ---
def test_inspect_missing_file_clean_error(capsys):
    rc = _run(["inspect", "does_not_exist_xyz.py"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.strip()   # a clean one-liner, no traceback


def test_inspect_missing_file_json_clean_error(capsys):
    rc = _run(["inspect", "does_not_exist_xyz.py", "--json"])
    assert rc == 1
    assert "Traceback" not in capsys.readouterr().err


# --- #150: default `inspect` on an app with no supported widgets must not print nothing ---
def test_inspect_empty_state_printed_for_chat_app(capsys):
    """The README quickstart's first command printed 0 bytes at exit 0 for a chat app —
    indistinguishable from a hang or a crash — while --json and --layout both reported
    the state. The text view must say the empty state in words."""
    assert _run(["inspect", CHAT_APP]) == 0
    out = capsys.readouterr().out
    assert out.strip(), "bare inspect printed nothing (0 bytes) for a widget-less app (#150)"
    assert "No supported widgets" in out
    assert "--layout" in out  # the empty state points at the surface that explains why


def test_inspect_empty_state_printed_for_widgetless_app(tmp_path, capsys):
    # the other class from the report: an app with no input widgets at all
    app = tmp_path / "empty.py"
    app.write_text("import streamlit as st\nst.title('Empty')\nst.write('nothing to drive')\n")
    assert _run(["inspect", str(app)]) == 0
    out = capsys.readouterr().out
    assert out.strip(), "bare inspect printed nothing for an app with no widgets (#150)"
    assert "No supported widgets" in out


def test_inspect_json_empty_widgets_stays_structural(capsys):
    # --json already signalled the empty state structurally; the text fix must not leak into it
    assert _run(["inspect", CHAT_APP, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)     # still clean, parseable JSON
    assert payload["widgets"] == []


def test_inspect_layout_still_reports_state_for_chat_app(capsys):
    # --layout already reported the state (outputs + unsupported); it must keep doing so
    assert _run(["inspect", CHAT_APP, "--layout"]) == 0
    out = capsys.readouterr().out
    assert "[title] Chat Assistant" in out
    assert "unsupported:" in out and "chat_input" in out


def test_inspect_empty_state_absent_when_widgets_exist(capsys):
    # the empty-state line must not leak into the normal path
    assert _run(["inspect", APP]) == 0
    out = capsys.readouterr().out
    assert "No supported widgets" not in out
    assert "text_input" in out
