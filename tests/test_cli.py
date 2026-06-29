"""U6 tests — the human-first CLI and parity with the engine/MCP path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamlit_mcp.cli import _parse_value, _split_assignment, build_parser, main
from streamlit_mcp.decorator import clear_registry

APP = str(Path(__file__).parent / "apps" / "sample_app.py")
SEMANTIC_APP = str(Path(__file__).parent / "apps" / "semantic_app.py")


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
