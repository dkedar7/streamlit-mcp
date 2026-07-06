"""Headless runtime that drives a Streamlit app via AppTest, behind an interface.

Streamlit has no callback graph — it reruns the whole script per interaction — so we
drive the app through ``streamlit.testing.v1.AppTest``: introspect widgets, set values,
click buttons (each triggers a rerun), and read the rendered element tree + session_state.

``Runtime`` is the interface so a lower-level ScriptRunner implementation can replace
``AppTestRuntime`` later without touching the element model, server, or CLI.
"""

from __future__ import annotations

import contextlib
import datetime
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@contextlib.contextmanager
def _stdout_to_stderr():
    """Keep the app's own output off stdout during a run. Streamlit prints an uncaught-exception
    traceback (and any ``print()`` the app makes) to stdout; stdout must stay clean for the CLI's
    ``--json`` and the stdio MCP JSON-RPC channel, so redirect it to stderr for the duration. The
    error itself is still captured in the snapshot's ``exception`` field (origin: dogfood #27)."""
    saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = saved

# The ten widget kinds supported in v1 (origin R10). Order is display order.
SUPPORTED_KINDS = (
    "text_input",
    "number_input",
    "text_area",
    "slider",
    "select_slider",
    "selectbox",
    "multiselect",
    "checkbox",
    "toggle",
    "radio",
    "button",
    "date_input",
    "time_input",
    "color_picker",
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

    def _run_script(self) -> None:
        """Run the app, keeping its stdout output (tracebacks, print) off our stdout. Uses a
        generous timeout — AppTest's 3s default spuriously trips for a slow app or a loaded CI
        box; a real app run finishes in well under a second."""
        with _stdout_to_stderr():
            self.at.run(timeout=30)

    def run(self) -> None:
        self._run_script()
        self._started = True

    def _ensure(self) -> None:
        if not self._started:
            self.run()

    # ------------------------------------------------------------- introspect
    def _walk(self):
        """Yield every element under the sidebar then main blocks, in document/render order.
        AppTest's typed accessors (at.text_input, at.markdown, ...) each return one list per kind,
        so concatenating them kind-by-kind reorders the app — every heading hoisted above all body
        text, a form's fields regrouped by type — bearing no relation to how it renders (#39).
        Walking the blocks preserves render order and still yields the same rich element objects.
        Sidebar first (it's the left rail / first in the DOM), then main; nested blocks (columns,
        expanders) recurse, and their container nodes fall through since their .type isn't a
        widget/output kind. at.main alone excludes the sidebar, so both roots are walked."""
        for root in (getattr(self.at, "sidebar", None), self.at.main):
            if root is None:
                continue
            yield from root

    def _iter_widgets(self):
        """(kind, index, el) for every supported widget in document order. The single source of
        widget identity — snapshot() (what an agent reads) and _find() (what set_widget/click
        resolve) both consume it, so an advertised identifier is exactly the one _find accepts,
        including the ``kind[index]`` fallback (#41). ``index`` is a per-kind counter in this order."""
        supported = set(SUPPORTED_KINDS)
        kind_index: dict[str, int] = {}
        for el in self._walk():
            kind = getattr(el, "type", None)
            if kind in supported:
                idx = kind_index.get(kind, 0)
                kind_index[kind] = idx + 1
                yield kind, idx, el

    def snapshot(self) -> RuntimeSnapshot:
        self._ensure()
        output_kinds = set(OUTPUT_KINDS)
        widgets = [
            WidgetSnapshot(
                kind=kind,
                index=idx,
                key=getattr(el, "key", None),
                label=getattr(el, "label", None),
                value=getattr(el, "value", None),
                options=list(getattr(el, "options", []) or []) or None,
                min=getattr(el, "min", None),
                max=getattr(el, "max", None),
                step=getattr(el, "step", None),
            )
            for kind, idx, el in self._iter_widgets()
        ]
        outputs: list[OutputSnapshot] = []
        for el in self._walk():
            kind = getattr(el, "type", None)
            if kind in output_kinds:
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
        coerced = self._coerce(kind, value)
        # Reject a bad value BEFORE writing it. An invalid *option* raises inside at.run()
        # and the pending bad value poisons every later call (#10); an out-of-range *number/
        # slider/date* does the opposite — AppTest silently resets it to the widget default
        # and run() does NOT raise, so it must be caught up front too (#12). A bad *color*
        # reverts the same silent way (#31), so it needs its own up-front check as well.
        self._validate_choice(kind, el, coerced)
        self._validate_range(kind, el, coerced)
        self._validate_color(kind, coerced)
        prior = getattr(el, "value", None)
        self._set(kind, el, coerced)
        try:
            self._run_script()
        except Exception as e:
            # Any other failed run() also leaves bad pending state. Roll back to the prior
            # value and re-run so the session stays usable, and attribute the failure to
            # THIS call rather than letting it leak into the next one.
            self._rollback(identifier, prior)
            raise RuntimeError_(
                f"setting {identifier!r} to {value!r} failed and was rolled back: {e}"
            ) from e

    def click(self, identifier: str) -> None:
        kind, el = self._find(identifier)
        if kind != "button":
            raise RuntimeError_(f"{identifier!r} is not a button")
        el.click()
        self._run_script()

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _validate_choice(kind: str, el, value: Any) -> None:
        """Reject a selectbox/radio/select_slider/multiselect value that isn't an offered
        option, before it is written to AppTest. Skipped when the widget exposes no options."""
        options = list(getattr(el, "options", []) or [])
        if not options:
            return
        if kind in ("selectbox", "radio"):
            if value not in options:
                raise RuntimeError_(
                    f"{value!r} is not a valid option for {kind}; choose one of {options}"
                )
        elif kind in ("select_slider", "multiselect"):
            # Both carry multiple values against a fixed option list: multiselect a list,
            # select_slider a single value OR a (lo, hi) range. Every element must be an
            # offered option — the range form used to be skipped, so a bad handle silently
            # reverted while reporting success (#33).
            values = list(value) if isinstance(value, (list, tuple)) else [value]
            invalid = [v for v in values if v not in options]
            if invalid:
                raise RuntimeError_(
                    f"{invalid!r} are not valid options for {kind}; choose from {options}"
                )

    @staticmethod
    def _validate_range(kind: str, el, value: Any) -> None:
        """Reject a number_input/slider/date_input value outside the widget's [min, max]
        before it is written. AppTest silently resets an out-of-range value to the default
        (run() does not raise), so the rollback net never fires — it must be caught up front."""
        if kind not in ("number_input", "slider", "date_input"):
            return
        lo, hi = getattr(el, "min", None), getattr(el, "max", None)
        if lo is None and hi is None:
            return
        for v in (value if isinstance(value, (list, tuple)) else (value,)):
            try:
                below, above = (lo is not None and v < lo), (hi is not None and v > hi)
            except TypeError:
                return  # value not comparable to the bounds — leave it to _coerce/AppTest
            if below:
                raise RuntimeError_(f"{v!r} is out of range for {kind}: minimum is {lo!r}")
            if above:
                raise RuntimeError_(f"{v!r} is out of range for {kind}: maximum is {hi!r}")

    # A color_picker accepts only a #RGB / #RRGGBB hex string. AppTest normalizes anything
    # else (a bad hex, a CSS name, a wrong-length string) back to the widget default without
    # raising — the same silent-revert path as an out-of-range number (#12) — so the rollback
    # net never fires. Catch it up front (#31). Verified against AppTest: only 3- or 6-digit
    # hex sticks; "#12345", "#gggggg", "red", "notacolor" all revert.
    _COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")

    @classmethod
    def _validate_color(cls, kind: str, value: Any) -> None:
        if kind != "color_picker":
            return
        if not (isinstance(value, str) and cls._COLOR_RE.match(value)):
            raise RuntimeError_(
                f"{value!r} is not a valid color for color_picker; expected a hex string "
                "like '#ff0000' or '#f00'"
            )

    def _rollback(self, identifier: str, prior: Any) -> None:
        """Best-effort restore of a widget's prior value + re-run, so one failed set doesn't
        brick the session. Restore failures are swallowed — the original error still raises."""
        try:
            kind, el = self._find(identifier)
            self._set(kind, el, prior)
            self._run_script()
        except Exception:
            pass

    def _find(self, identifier: str):
        self._ensure()
        # match on key first, then label (a widget is reachable by either, even though
        # _identifier advertises key-if-present-else-label)
        for by in ("key", "label"):
            for kind in SUPPORTED_KINDS:
                for el in getattr(self.at, kind, []):
                    if getattr(el, by, None) == identifier:
                        return kind, el
        # then the ``kind[index]`` fallback _identifier hands out for a keyless, empty-label
        # widget — resolved through the SAME document-order numbering snapshot() advertises, so
        # the list_widgets -> set_widget round-trip holds. Without this the advertised identifier
        # is a dead handle: the one string the tool tells you to use, and the one _find rejects (#41).
        m = re.fullmatch(r"(\w+)\[(\d+)\]", identifier)
        if m:
            want_kind, want_idx = m.group(1), int(m.group(2))
            for kind, idx, el in self._iter_widgets():
                if kind == want_kind and idx == want_idx:
                    return kind, el
        raise WidgetNotFound(f"no widget matching {identifier!r}")

    @staticmethod
    def _to_date(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            raise RuntimeError_(
                f"{value!r} is not a valid date for date_input; use ISO format like '2026-01-31'"
            ) from None

    @staticmethod
    def _to_time(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return datetime.time.fromisoformat(value)
        except ValueError:
            raise RuntimeError_(
                f"{value!r} is not a valid time for time_input; use 24-hour 'HH:MM' like '09:30'"
            ) from None

    # accepted string spellings of a boolean, for checkbox/toggle set from the CLI
    _BOOL_STRINGS = {"true": True, "false": False, "1": True, "0": False,
                     "yes": True, "no": False, "on": True, "off": False}

    @classmethod
    def _to_bool(cls, kind: str, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):  # 0/1 from a JSON number
            return bool(value)
        if isinstance(value, str):
            v = cls._BOOL_STRINGS.get(value.strip().lower())
            if v is not None:
                return v
        raise RuntimeError_(f"{value!r} is not a valid boolean for {kind}; use true or false")

    @classmethod
    def _coerce(cls, kind: str, value: Any) -> Any:
        # A clean, actionable error on a bad value beats a raw Python ValueError leaking to the
        # CLI/MCP boundary; coercing every element of a *range* (list/tuple) keeps the value
        # typed so _validate_range can bounds-check it instead of bailing on a str<date compare
        # (the date-range sibling of the #33 select_slider gap).
        if kind == "date_input":
            if isinstance(value, (list, tuple)):
                return [cls._to_date(v) for v in value]
            return cls._to_date(value)
        if kind == "time_input":
            return cls._to_time(value)
        if kind == "number_input" and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    raise RuntimeError_(
                        f"{value!r} is not a valid number for number_input"
                    ) from None
        if kind in ("checkbox", "toggle"):
            return cls._to_bool(kind, value)
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
