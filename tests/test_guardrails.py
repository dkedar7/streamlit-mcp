"""U8 tests — guardrails: read-only, allow-list, bearer auth, and engine integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit_mcp.engine import Engine, PermissionDenied
from streamlit_mcp.guardrails import Guardrails
from streamlit_mcp.runtime import AppTestRuntime

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


def _engine(guard):
    rt = AppTestRuntime(APP)
    rt.run()
    return Engine(rt, guard=guard, app_path=APP)


# ---------------------------------------------------------------- read-only
def test_read_only_blocks_writes_allows_reads():
    """R11: read-only rejects set/click but allows list/read."""
    eng = _engine(Guardrails(read_only=True))
    with pytest.raises(PermissionDenied):
        eng.set_widget("Name", "x")
    with pytest.raises(PermissionDenied):
        eng.click("Save")
    assert len(eng.list_widgets()["widgets"]) == 10  # reads fine


def test_default_allows_writes():
    eng = _engine(Guardrails())
    eng.set_widget("Name", "ok")
    assert any("Hello, ok!" == o["text"] for o in eng.read_output()["outputs"])


# ---------------------------------------------------------------- allow-list
def test_allow_list_hides_and_blocks():
    eng = _engine(Guardrails(allow_list={"name"}))
    labels = {w["label"] for w in eng.list_widgets()["widgets"]}
    assert labels == {"Name"}
    eng.set_widget("name", "ok")  # allowed
    with pytest.raises(PermissionDenied):
        eng.set_widget("Level", 3)  # not allowed


def test_allow_list_matches_label_too():
    g = Guardrails(allow_list={"Name"})
    models = [{"identifier": "name", "label": "Name"}, {"identifier": "lvl", "label": "Level"}]
    kept = g.filter_widgets(models)
    assert [m["identifier"] for m in kept] == ["name"]


def test_none_allow_list_allows_all():
    g = Guardrails()
    assert g.is_allowed("anything") is True
    assert g.filter_widgets([{"identifier": "x", "label": "X"}]) == [{"identifier": "x", "label": "X"}]


# ---------------------------------------------------------------- bearer auth
def test_check_bearer_no_token_configured_is_open():
    assert Guardrails().check_bearer(None) is True
    assert Guardrails().check_bearer("whatever") is True


def test_check_bearer_matches():
    g = Guardrails(bearer_token="s3cret")
    assert g.check_bearer("s3cret") is True
    assert g.check_bearer("wrong") is False
    assert g.check_bearer(None) is False


def test_require_bearer_header_parsing():
    g = Guardrails(bearer_token="s3cret")
    assert g.require_bearer("Bearer s3cret") is True
    assert g.require_bearer("bearer s3cret") is True   # case-insensitive scheme
    assert g.require_bearer("Bearer wrong") is False
    assert g.require_bearer("Basic s3cret") is False
    assert g.require_bearer(None) is False
    assert g.require_bearer("s3cret") is False          # missing scheme


def test_require_bearer_open_when_unconfigured():
    assert Guardrails().require_bearer(None) is True
