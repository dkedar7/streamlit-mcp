"""Headless runtime that drives a Streamlit app via AppTest, behind an interface.

Streamlit has no callback graph — it reruns the whole script per interaction — so we
drive the app through ``streamlit.testing.v1.AppTest``: introspect widgets, set values,
click buttons (each triggers a rerun), and read the rendered element tree + session_state.

``Runtime`` is the interface so a lower-level ScriptRunner implementation can replace
``AppTestRuntime`` later without touching the element model, server, or CLI.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

# The ten widget kinds supported in v1 (origin R10). Order is display order.
SUPPORTED_KINDS = (
    "text_input",
    "number_input",
    "text_area",
    "slider",
    "selectbox",
    "multiselect",
    "checkbox",
    "radio",
    "button",
    "date_input",
)

# Output element kinds we render to agent-readable text.
OUTPUT_KINDS = ("title", "header", "subheader", "markdown", "caption", "text")


class RuntimeError_(Exception):
    """Base error for runtime operations."""


class WidgetNotFound(RuntimeError_):
    """Raised when an identifier matches no widget."""


@dataclass
class WidgetSnapshot:
    kind: str
    index: int
    key: Optional[str]
    label: Optional[str]
    value: Any
    options: Optional[list] = None
    min: Any = None
    max: Any = None
    step: Any = None


@dataclass
class OutputSnapshot:
    kind: str
    text: str


@dataclass
class RuntimeSnapshot:
    widgets: list[WidgetSnapshot] = field(default_factory=list)
    outputs: list[OutputSnapshot] = field(default_factory=list)
    session_state: dict = field(default_factory=dict)
    exception: Optional[str] = None


@runtime_checkable
class Runtime(Protocol):
    """The interface the element model, server, and CLI depend on."""

    def run(self) -> None: ...
    def snapshot(self) -> RuntimeSnapshot: ...
    def set_widget(self, identifier: str, value: Any) -> None: ...
    def click(self, identifier: str) -> None: ...


class AppTestRuntime:
    """Drives one Streamlit app instance via AppTest. One instance == one session."""

    def __init__(self, app_path: Optional[str] = None, *, script: Optional[str] = None):
        from streamlit.testing.v1 import AppTest

        if script is not None:
            self.at = AppTest.from_string(script)
        elif app_path is not None:
            self.at = AppTest.from_file(app_path)
        else:
            raise ValueError("provide app_path or script")
        self._started = False

    def run(self) -> None:
        self.at.run()
        self._started = True

    def _ensure(self) -> None:
        if not self._started:
            self.run()

    # ------------------------------------------------------------- introspect
    def snapshot(self) -> RuntimeSnapshot:
        self._ensure()
        widgets: list[WidgetSnapshot] = []
        for kind in SUPPORTED_KINDS:
            for index, el in enumerate(getattr(self.at, kind, [])):
                widgets.append(
                    WidgetSnapshot(
                        kind=kind,
                        index=index,
                        key=getattr(el, "key", None),
                        label=getattr(el, "label", None),
                        value=getattr(el, "value", None),
                        options=list(getattr(el, "options", []) or []) or None,
                        min=getattr(el, "min", None),
                        max=getattr(el, "max", None),
                        step=getattr(el, "step", None),
                    )
                )
        outputs: list[OutputSnapshot] = []
        for kind in OUTPUT_KINDS:
            for el in getattr(self.at, kind, []):
                val = getattr(el, "value", None)
                if val is not None:
                    outputs.append(OutputSnapshot(kind=kind, text=str(val)))
        return RuntimeSnapshot(
            widgets=widgets,
            outputs=outputs,
            session_state=self._session_state(),
            exception=self._exception(),
        )

    def _session_state(self) -> dict:
        ss = self.at.session_state
        try:
            return dict(ss.filtered_state)
        except AttributeError:
            pass
        try:  # fallback via explicit keys (iterating ss yields positions, not keys)
            return {k: ss[k] for k in ss.keys()}
        except Exception:
            return {}

    def _exception(self) -> Optional[str]:
        exc = getattr(self.at, "exception", None)
        if not exc:
            return None
        try:
            return "; ".join(str(getattr(e, "value", e)) for e in exc)
        except TypeError:
            return str(exc)

    # ----------------------------------------------------------------- act
    def set_widget(self, identifier: str, value: Any) -> None:
        kind, el = self._find(identifier)
        if kind == "button":
            raise RuntimeError_(f"{identifier!r} is a button; use click()")
        self._set(kind, el, self._coerce(kind, value))
        self.at.run()

    def click(self, identifier: str) -> None:
        kind, el = self._find(identifier)
        if kind != "button":
            raise RuntimeError_(f"{identifier!r} is not a button")
        el.click()
        self.at.run()

    # ----------------------------------------------------------------- helpers
    def _find(self, identifier: str):
        self._ensure()
        # match on key first, then label
        for by in ("key", "label"):
            for kind in SUPPORTED_KINDS:
                for el in getattr(self.at, kind, []):
                    if getattr(el, by, None) == identifier:
                        return kind, el
        raise WidgetNotFound(f"no widget matching {identifier!r}")

    @staticmethod
    def _coerce(kind: str, value: Any) -> Any:
        if kind == "date_input" and isinstance(value, str):
            return datetime.date.fromisoformat(value)
        if kind == "number_input" and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return float(value)
        if kind == "multiselect" and isinstance(value, str):
            return [value]
        if kind in ("text_input", "text_area") and not isinstance(value, str):
            # a JSON-typed value (True/41/None) bound for a text field becomes its string
            return str(value)
        return value

    @staticmethod
    def _set(kind: str, el, value: Any) -> None:
        try:
            el.set_value(value)
        except AttributeError:
            if kind in ("selectbox", "radio"):
                el.select(value)
            elif kind == "multiselect":
                for v in value:
                    el.select(v)
            elif kind == "checkbox":
                el.check() if value else el.uncheck()
            else:
                raise
