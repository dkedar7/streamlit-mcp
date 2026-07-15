"""Element model: normalize runtime snapshots into agent-readable, JSON-safe shapes
and generate per-widget MCP tool schemas. Also detects unsupported elements explicitly.

This layer depends only on the Runtime's snapshot dataclasses, never on AppTest directly,
so a different Runtime implementation produces the same models.
"""

from __future__ import annotations

import ast
import datetime
import re
from typing import Any

from .runtime import RuntimeSnapshot, WidgetSnapshot

# Widgets that take a value via set_widget vs. the action-only button.
ACTION_KINDS = ("button",)

# Streamlit input/interactive elements we do NOT drive — reported explicitly, never silently
# dropped (origin R10 / AE3; completed for the full input-widget set in #29). Kept in sync with
# Streamlit's "Input widgets" category minus the supported kinds; anything here is surfaced in
# `unsupported` so an agent/human at least learns it exists.
#
# form_submit_button is deliberately NOT here: AppTest renders it as a `button`-typed node, so the
# runtime already surfaces it as a supported, clickable widget and clicking it genuinely submits
# the form. Listing it here too reported the same element as supported AND unsupported, with a
# "drive it another way" reason that was simply false — steering agents away from the ubiquitous
# st.form flow they can in fact drive (#53). Forms are driven by setting the fields, then clicking
# the submit button.
UNSUPPORTED_ELEMENTS = (
    "file_uploader",
    "camera_input",
    "audio_input",
    "chat_input",
    "chat_message",
    "data_editor",
    "download_button",
    "link_button",
    "page_link",
    "pills",
    "segmented_control",
    "feedback",
)

# Fallback for source that doesn't parse (see _unsupported_names).
_UNSUPPORTED_RE = re.compile(
    r"\bst\.(" + "|".join(re.escape(n) for n in UNSUPPORTED_ELEMENTS) + r")\s*\("
)


def serialize_value(value: Any) -> Any:
    """Make a value JSON-safe (dates -> ISO strings, tuples -> lists, dicts recursed,
    unknown objects -> str). Used for both widget values and session_state."""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
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


# A slider/select_slider/date_input built with a tuple `value=` is a TWO-HANDLE RANGE widget whose
# value is a list, not a scalar; the single-handle form of each holds a scalar. The value's own
# shape is the signal, and it's a reliable one — Streamlit hands back a tuple for a range widget and
# a bare scalar for a single one (even an untouched `st.date_input(value=[])` range is `()`).
RANGE_KINDS = ("slider", "select_slider", "date_input")


def is_range_widget(model: dict) -> bool:
    return model["kind"] in RANGE_KINDS and isinstance(model.get("value"), list)


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
    elif kind in ("selectbox", "radio", "select_slider"):
        value = {"type": "string", "enum": list(c.get("options", []))}
        # A placeholder selectbox/radio (built with index=None) has no selection: its value is
        # null, so its own schema must permit null — otherwise the reported value contradicts the
        # enum it advertises and a schema-validating agent balks at a value the tool itself emitted
        # (#57). select_slider always has both handles, so it is never null.
        if model.get("value") is None and kind in ("selectbox", "radio"):
            value = {"type": ["string", "null"], "enum": value["enum"] + [None]}
    elif kind == "multiselect":
        value = {"type": "array", "items": {"type": "string", "enum": c.get("options", [])}}
    elif kind in ("checkbox", "toggle"):
        value = {"type": "boolean"}
    elif kind == "date_input":
        value = {"type": "string", "format": "date"}
    elif kind == "time_input":
        value = {"type": "string", "format": "time"}
    elif kind == "color_picker":
        value = {"type": "string"}
    elif kind == "button":
        return {"type": "object", "properties": {}, "description": "click action; no value"}
    else:
        value = {}
    if is_range_widget(model):
        # Advertising the scalar shape for a range widget told a schema-following agent to send a
        # number/string — which AppTest then silently discarded (or, for a date range, degraded to
        # a one-element range) while set_widget reported success (#55). Advertise what the widget
        # actually holds: both handles, so a valid set can be constructed from what's advertised.
        value = {"type": "array", "items": value, "minItems": 2, "maxItems": 2}
    return {
        "type": "object",
        "properties": {"value": value},
        "required": ["value"],
    }


def _unsupported_names(source: str) -> list[str]:
    """Names of unsupported elements the app *calls*, found by parsing the source.

    This is the only detector for unsupported widgets — the runtime element tree can't serve as
    one, because AppTest names nodes after their protobuf type, which is lossy in exactly the wrong
    way: st.data_editor arrives as `dataframe` (indistinguishable from a plain st.dataframe output,
    which is perfectly fine), and pills/segmented_control/feedback all collapse into `button_group`.
    Deriving `unsupported` from the tree would therefore flag every st.dataframe as undrivable.

    So we read the source — but as an AST, not as text. The old regex anchored on the literal
    `st.<name>(` form, which silently dropped every unsupported widget placed through a container
    accessor — st.sidebar.file_uploader(...), col.camera_input(...), tab.data_editor(...) — i.e.
    the ubiquitous sidebar/columns idioms, breaking the "never silently dropped" guarantee exactly
    where real apps live (#52). Matching the *call node's attribute* instead catches any receiver
    (st, st.sidebar, a column, a tab, an aliased `import streamlit as sl`), and, being an AST,
    ignores occurrences in comments and strings that the text scan used to report.

    Detection stays static, so an unsupported widget behind a branch that didn't run this time is
    still reported. That over-approximates (a call under `if False:` is reported too) — the safe
    direction for a guarantee whose whole point is that a widget is never silently missing.
    """
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        # An app that doesn't parse can't run either (AppTest surfaces that as an `exception`);
        # still, fall back to the text scan rather than reporting nothing at all.
        return sorted(set(_UNSUPPORTED_RE.findall(source or "")))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):  # st.file_uploader(), st.sidebar.file_uploader(), col.x()
            name = func.attr
        elif isinstance(func, ast.Name):  # from streamlit import file_uploader
            name = func.id
        else:
            continue
        if name in UNSUPPORTED_ELEMENTS:
            names.add(name)
    return sorted(names)


def detect_unsupported_source(source: str) -> list[dict]:
    """Report the known-unsupported elements an app calls (deterministic; see _unsupported_names)."""
    return [
        {"element": name, "supported": False,
         "reason": f"st.{name} is not supported in v1; drive it another way or extend coverage"}
        for name in _unsupported_names(source)
    ]


def detect_unsupported(app_path: str) -> list[dict]:
    try:
        with open(app_path, "r", encoding="utf-8") as fh:
            return detect_unsupported_source(fh.read())
    except OSError:
        return []  # missing/unreadable app file -> no unsupported report, not a crash
