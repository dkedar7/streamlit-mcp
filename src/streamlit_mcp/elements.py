"""Element model: normalize runtime snapshots into agent-readable, JSON-safe shapes
and generate per-widget MCP tool schemas. Also detects unsupported elements explicitly.

This layer depends only on the Runtime's snapshot dataclasses, never on AppTest directly,
so a different Runtime implementation produces the same models.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from .runtime import RuntimeSnapshot, WidgetSnapshot

# Widgets that take a value via set_widget vs. the action-only button.
ACTION_KINDS = ("button",)

# Common Streamlit elements we do NOT support in v1 — reported explicitly, never
# silently dropped (origin R10 / AE3).
UNSUPPORTED_ELEMENTS = (
    "file_uploader",
    "camera_input",
    "audio_input",
    "chat_input",
    "chat_message",
    "data_editor",
    "color_picker",  # not in the v1 ten
    "download_button",
)

_UNSUPPORTED_RE = re.compile(
    r"\bst\.(" + "|".join(re.escape(n) for n in UNSUPPORTED_ELEMENTS) + r")\s*\("
)


def serialize_value(value: Any) -> Any:
    """Make a value JSON-safe (dates -> ISO strings, tuples -> lists, dicts recursed,
    unknown objects -> str). Used for both widget values and session_state."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): serialize_value(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _identifier(w: WidgetSnapshot) -> str:
    return w.key or w.label or f"{w.kind}[{w.index}]"


def _constraints(w: WidgetSnapshot) -> dict:
    c: dict = {}
    if w.options is not None:
        c["options"] = list(w.options)
    for name in ("min", "max", "step"):
        val = getattr(w, name)
        if val is not None:
            c[name] = serialize_value(val)
    return c


def widget_to_model(w: WidgetSnapshot) -> dict:
    return {
        "kind": w.kind,
        "identifier": _identifier(w),
        "key": w.key,
        "label": w.label,
        "value": serialize_value(w.value),
        "constraints": _constraints(w),
        "action": w.kind in ACTION_KINDS,
        "supported": True,
    }


def widgets_to_models(snapshot: RuntimeSnapshot) -> list[dict]:
    return [widget_to_model(w) for w in snapshot.widgets]


def outputs_to_list(snapshot: RuntimeSnapshot) -> list[dict]:
    return [{"kind": o.kind, "text": o.text} for o in snapshot.outputs]


def tool_schema_for(model: dict) -> dict:
    """A JSON-schema-ish input schema for setting/invoking this widget."""
    kind = model["kind"]
    c = model.get("constraints", {})
    if kind in ("text_input", "text_area"):
        value = {"type": "string"}
    elif kind in ("number_input", "slider"):
        value = {"type": "number"}
        if "min" in c:
            value["minimum"] = c["min"]
        if "max" in c:
            value["maximum"] = c["max"]
    elif kind in ("selectbox", "radio"):
        value = {"type": "string", "enum": c.get("options", [])}
    elif kind == "multiselect":
        value = {"type": "array", "items": {"type": "string", "enum": c.get("options", [])}}
    elif kind == "checkbox":
        value = {"type": "boolean"}
    elif kind == "date_input":
        value = {"type": "string", "format": "date"}
    elif kind == "button":
        return {"type": "object", "properties": {}, "description": "click action; no value"}
    else:
        value = {}
    return {
        "type": "object",
        "properties": {"value": value},
        "required": ["value"],
    }


def detect_unsupported_source(source: str) -> list[dict]:
    """Scan app source for known-unsupported st.* element calls (heuristic, deterministic)."""
    found = sorted(set(_UNSUPPORTED_RE.findall(source or "")))
    return [
        {"element": name, "supported": False,
         "reason": f"st.{name} is not supported in v1; drive it another way or extend coverage"}
        for name in found
    ]


def detect_unsupported(app_path: str) -> list[dict]:
    try:
        with open(app_path, "r", encoding="utf-8") as fh:
            return detect_unsupported_source(fh.read())
    except OSError:
        return []  # missing/unreadable app file -> no unsupported report, not a crash
