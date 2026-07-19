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


def _recover_typed(sample: Any, text: str) -> Any:
    """Parse a stringified option back into ``sample``'s type, or None if it can't be recovered
    exactly. The ``str(recovered) == text`` round-trip check is what keeps this honest: we only ever
    advertise a typed form that stringifies back to the very option it came from, so the typed and
    string members of an enum always denote the same option. An option that doesn't survive the
    round-trip (``'two'`` among int options) is simply left in its string form."""
    kind = type(sample)
    try:
        if kind is bool:  # bool(str) is truthy for any non-empty string, so map the two forms
            return {"True": True, "False": False}.get(text)
        recovered = kind(text)
    except (TypeError, ValueError):
        return None
    return recovered if str(recovered) == text else None


def _choice_value_schema(model: dict, options: list) -> dict:
    """The value-schema for an options widget (selectbox/radio/select_slider/multiselect).

    AppTest reports a widget's options **stringified** but its value in the **real type**, so a
    widget built from non-string options — ``st.selectbox('Year', [2023, 2024, 2025])``, ubiquitous
    — advertised ``enum: ['2023','2024','2025']`` while reporting ``value: 2023``: a value that is
    neither a member of nor the type of the schema the same call advertises (#62). #51 fixed only
    the *write* path (set_widget matches on string form); the advertised model stayed
    self-inconsistent.

    The runtime cannot tell us the true option types — the widget protobuf carries options already
    stringified (``options: "2023"``), so the current value's type is the only evidence there is.
    We use it to recover the typed form of **every** option, not just the selected one: an agent
    must be able to construct *any* valid set from what's advertised, not merely echo back the
    selection it was handed. Both forms are advertised because set_widget accepts both (#51), and
    the strict ``type: "string"`` is dropped since a mixed enum has no single type.

    Known limitation: a widget with **no** current selection (``st.multiselect('Nums', [1,2,3])``,
    default empty) offers no type evidence, so its enum stays the string form. That is still
    correct and usable — the string form is always settable — just less informative, and the
    self-consistency invariant holds trivially (there is no value to contradict it)."""
    value = model.get("value")
    selected = value if isinstance(value, list) else [value]
    typed = [v for v in selected if v is not None and not isinstance(v, str)]
    if not typed:
        return {"type": "string", "enum": list(options)}
    sample = typed[0]
    recovered: list = []
    for opt in options:
        rec = _recover_typed(sample, opt)
        if rec is not None and rec not in recovered:
            recovered.append(rec)
    enum = recovered + [o for o in options if o not in recovered]
    for v in typed:  # the reported value is a member by construction, even if it didn't round-trip
        if v not in enum:
            enum.append(v)
    return {"enum": enum}


def _make_nullable(value_schema: dict) -> dict:
    """Widen a value-schema to also permit null. A widget built with ``value=None`` / ``index=None``
    (a text/number/date/time placeholder, or a 'please select…' selectbox/radio) reports
    ``value: null``, so its own schema must allow null — else the reported value contradicts the
    schema it advertises and a schema-validating agent balks at a value the tool itself emitted.
    Applied uniformly by value (not per-kind) so the fix can't re-open for the next placeholder-
    capable widget (#57 fixed only selectbox/radio; #60 hit text_input/text_area/number_input)."""
    s = dict(value_schema)
    t = s.get("type")
    if isinstance(t, str):
        s["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        s["type"] = [*t, "null"]
    if "enum" in s and None not in s["enum"]:
        s["enum"] = [*s["enum"], None]
    return s


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
        value = _choice_value_schema(model, list(c.get("options", [])))
    elif kind == "multiselect":
        value = {"type": "array", "items": _choice_value_schema(model, list(c.get("options", [])))}
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
    elif model.get("value") is None:
        value = _make_nullable(value)  # a value=None / index=None placeholder — see _make_nullable
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
