"""U3 tests — element model, tool schemas, and unsupported detection."""

from __future__ import annotations

from pathlib import Path

from streamlit_mcp.elements import (
    detect_unsupported_source,
    outputs_to_list,
    serialize_value,
    tool_schema_for,
    widgets_to_models,
)
from streamlit_mcp.runtime import AppTestRuntime

APP = str(Path(__file__).parent / "apps" / "sample_app.py")


def _models():
    rt = AppTestRuntime(APP)
    rt.run()
    return {m["kind"]: m for m in widgets_to_models(rt.snapshot())}


def test_all_ten_widgets_modeled():
    models = _models()
    assert set(models) == {
        "text_input", "number_input", "text_area", "slider", "selectbox",
        "multiselect", "checkbox", "radio", "button", "date_input",
    }


def test_identifier_prefers_key():
    models = _models()
    assert models["text_input"]["identifier"] == "name"


def test_date_value_serialized_to_string():
    models = _models()
    assert models["date_input"]["value"] == "2026-01-01"


def test_selectbox_constraints_have_options():
    models = _models()
    assert models["selectbox"]["constraints"]["options"] == ["red", "green", "blue"]


def test_button_is_action():
    models = _models()
    assert models["button"]["action"] is True


def test_tool_schema_selectbox_is_enum():
    models = _models()
    schema = tool_schema_for(models["selectbox"])
    assert schema["properties"]["value"]["enum"] == ["red", "green", "blue"]


def test_tool_schema_checkbox_is_boolean():
    models = _models()
    assert tool_schema_for(models["checkbox"])["properties"]["value"]["type"] == "boolean"


def test_tool_schema_slider_has_bounds():
    models = _models()
    v = tool_schema_for(models["slider"])["properties"]["value"]
    assert v["type"] == "number" and v["minimum"] == 1 and v["maximum"] == 10


def test_tool_schema_multiselect_is_array():
    models = _models()
    v = tool_schema_for(models["multiselect"])["properties"]["value"]
    assert v["type"] == "array" and v["items"]["enum"] == ["a", "b", "c"]


def test_tool_schema_date_is_string_date():
    models = _models()
    v = tool_schema_for(models["date_input"])["properties"]["value"]
    assert v["type"] == "string" and v["format"] == "date"


def test_outputs_list():
    rt = AppTestRuntime(APP)
    rt.run()
    outs = outputs_to_list(rt.snapshot())
    assert any("Hello, world!" == o["text"] for o in outs)


def test_detect_unsupported_flags_file_uploader():
    """AE3: an unsupported element is reported, not silently dropped."""
    src = "import streamlit as st\nf = st.file_uploader('Upload')\n"
    found = detect_unsupported_source(src)
    assert len(found) == 1
    assert found[0]["element"] == "file_uploader" and found[0]["supported"] is False


def test_detect_unsupported_empty_for_supported_app():
    src = "import streamlit as st\nst.text_input('x')\nst.button('y')\n"
    assert detect_unsupported_source(src) == []


def test_serialize_value_handles_lists_and_dates():
    import datetime
    assert serialize_value([datetime.date(2026, 1, 2), "x"]) == ["2026-01-02", "x"]
