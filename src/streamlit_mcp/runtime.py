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

# The widget kinds we drive (origin R10). Order is display order.
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
    "pills",
    "segmented_control",
    "feedback",
)

# st.pills and st.segmented_control are the SAME element in the tree — both arrive typed
# `button_group`, which is why they were once written off as undetectable — but AppTest exposes
# them under separate typed accessors. Resolving the real kind from those accessors is what lets
# them be supported under the names an agent actually writes in the app, rather than a shared
# protobuf name that matches neither.
BUTTON_GROUP_KINDS = ("pills", "segmented_control")

# st.feedback's option count is fixed by its style and is not exposed on the AppTest element, so it
# comes off the widget proto's enum — keyed by NAME rather than number, so a renumbering upstream
# can't silently turn thumbs into a 5-point scale.
_FEEDBACK_OPTION_COUNTS = {"THUMBS": 2, "FACES": 5, "STARS": 5}

# Output element kinds we render to agent-readable text.
OUTPUT_KINDS = ("title", "header", "subheader", "markdown", "caption", "text")


def _display(value: Any) -> str:
    """A value as it should read in an error message an agent or human acts on: dates and times as
    the ISO strings they're set with, not ``datetime.date(2026, 1, 1)`` Python reprs."""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return repr(value.isoformat())
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_display(v) for v in value) + "]"
    return repr(value)


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
        overrides = self._button_group_kinds()
        kind_index: dict[str, int] = {}
        for el in self._walk():
            kind = getattr(el, "type", None)
            if kind == "button_group":
                # Shared protobuf name for pills and segmented_control — resolve which one it is.
                # An unrecognized button_group (a future widget on the same proto) maps to None and
                # falls through as unsupported, rather than being driven under the wrong kind.
                kind = overrides.get(self._widget_id(el))
            if kind in supported:
                idx = kind_index.get(kind, 0)
                kind_index[kind] = idx + 1
                yield kind, idx, el

    @staticmethod
    def _widget_id(el) -> Optional[str]:
        """The widget's own protobuf id — stable across accessor reads, unlike Python identity."""
        return getattr(getattr(el, "proto", None), "id", None)

    def _button_group_kinds(self) -> dict:
        """widget id -> real kind, for the elements whose ``.type`` is the shared `button_group`."""
        mapping: dict = {}
        for kind in BUTTON_GROUP_KINDS:
            for el in getattr(self.at, kind, []) or []:
                wid = self._widget_id(el)
                if wid is not None:
                    mapping[wid] = kind
        return mapping

    @classmethod
    def _feedback_max(cls, el) -> Optional[int]:
        """Highest valid index for an st.feedback widget (thumbs -> 1, faces/stars -> 4).

        An unrecognized style yields None, so no bound is advertised or enforced rather than a
        wrong one — better to let a value through than to reject a valid rating."""
        proto = getattr(el, "proto", None)
        if proto is None:
            return None
        try:
            field = proto.DESCRIPTOR.fields_by_name["type"]
            name = field.enum_type.values_by_number[getattr(proto, "type", 0)].name
        except Exception:
            return None
        count = _FEEDBACK_OPTION_COUNTS.get(name)
        return count - 1 if count else None

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
                # A feedback widget carries no min/max of its own; its bounds are the option count
                # implied by its style, so they're derived and advertised like any other range.
                min=0 if kind == "feedback" else getattr(el, "min", None),
                max=self._feedback_max(el) if kind == "feedback" else getattr(el, "max", None),
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
        coerced = self._coerce(kind, value, el)
        # Setting a widget to null means "return it to its no-value/no-selection state" — the state
        # a value=None / index=None placeholder is born in and reports as its value. It's not an
        # option/number/date to validate, so it takes one shared attempt-and-verify path across
        # every kind (#57 selectbox/radio, #60 text/number), see _clear_to_none.
        if coerced is None:
            self._clear_to_none(identifier, kind, el)
            return
        # Reject a bad value BEFORE writing it. An invalid *option* raises inside at.run()
        # and the pending bad value poisons every later call (#10); an out-of-range *number/
        # slider/date* does the opposite — AppTest silently resets it to the widget default
        # and run() does NOT raise, so it must be caught up front too (#12). A bad *color*
        # reverts the same silent way (#31), so it needs its own up-front check as well. So does
        # a wrong *arity* — a scalar sent to a two-handle range widget, or vice versa (#55) — and
        # a *fractional* value on an integer number_input, which AppTest truncates (#51).
        self._validate_arity(kind, identifier, el, coerced)
        self._validate_choice(kind, el, coerced)
        self._validate_range(kind, el, coerced)
        self._validate_color(kind, coerced)
        self._validate_number(kind, identifier, el, coerced)
        self._validate_feedback(kind, identifier, el, coerced)
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

    def _clear_to_none(self, identifier: str, kind: str, el) -> None:
        """Set any widget to null — its no-value/no-selection state. A widget built with
        ``value=None`` / ``index=None`` (a text/number/date/time placeholder, or a 'please select…'
        selectbox/radio) is born holding null and reports it as its value, so an agent must be able
        to send null straight back (#57/#60). This is the one write that can't be pre-validated:
        AppTest exposes no 'is nullable' flag, and a placeholder that currently holds a value looks
        identical to a regular widget. It doesn't need to be — null is never a value-corrupting
        write to attempt. A widget that supports null accepts it and reads back null; one that
        doesn't (a regular selectbox, a plain text field) silently keeps its value or resets to its
        default, never raising. So we set null and VERIFY it took: if the value didn't become null,
        roll the prior value back and reject, keeping the set atomic and never reporting a non-clear
        as success — the same guarantee the up-front checks (#12/#31/#55) give value-corrupting
        writes, reached here by detection since there's nothing harmful to prevent."""
        prior = getattr(el, "value", None)
        if prior is None:
            return  # already null — an agent echoing back the reported value; nothing to change
        self._set(kind, el, None)
        try:
            self._run_script()
        except Exception as e:
            self._rollback(identifier, prior)
            raise RuntimeError_(
                f"clearing {identifier!r} to null failed and was rolled back: {e}"
            ) from e
        _, after = self._find(identifier)
        if getattr(after, "value", None) is not None:
            # Not nullable: the widget didn't clear (it kept its value, or reset to the default).
            # Restore the prior value so the failed set leaves state untouched, then reject.
            self._rollback(identifier, prior)
            options = list(getattr(el, "options", []) or [])
            hint = f" Choose one of {options}." if options else ""
            if kind in BUTTON_GROUP_KINDS:
                # Not the placeholder story the generic message tells: a pills/segmented_control
                # legitimately starts with no selection, so it may well have been created without a
                # default — AppTest simply offers no way back, since set_value(None) is a silent
                # no-op on it. Say what's actually true, and point at the route that does work.
                clear = " A multi-select is cleared with []." if isinstance(prior, list) else ""
                raise RuntimeError_(
                    f"{kind} {identifier!r} cannot be set to null: AppTest offers no way to "
                    f"deselect it once a selection is made.{hint}{clear}"
                )
            raise RuntimeError_(
                f"{kind} {identifier!r} cannot be set to null: it has no no-value state (it was not "
                f"created with value=None / index=None).{hint}"
            )

    def click(self, identifier: str) -> None:
        kind, el = self._find(identifier)
        if kind != "button":
            raise RuntimeError_(f"{identifier!r} is not a button")
        el.click()
        self._run_script()

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _validate_arity(kind: str, identifier: str, el, value: Any) -> None:
        """Reject a value whose ARITY doesn't match the widget, before it is written to AppTest.

        A slider/select_slider/date_input built with a tuple ``value=`` is a two-handle *range*
        widget holding a list; the single-handle form of each holds a scalar. AppTest normalizes an
        arity mismatch away without raising — a scalar sent to a range slider/select_slider reverts
        to the prior value, a list sent to a single one is dropped, and a scalar sent to a date
        range degrades it to a one-element range — so the rollback net never fires and the write
        silently vanishes (or half-lands) while set_widget reports success (#55). That is the arity
        sibling of the value-mismatch silent reverts closed in #12/#31/#33, and it has to be caught
        the same way: up front. Checked in both directions, since both revert silently."""
        if kind in BUTTON_GROUP_KINDS:
            # A pills/segmented_control is single- or multi-select, and its VALUE SHAPE is the
            # signal (the same signal a range widget gives): multi holds a list — [] when nothing
            # is chosen — where single holds a bare option or None. AppTest normalizes a mismatch
            # away silently, exactly like the range case: a list sent to a single-select reverts
            # with no exception, so set_widget would report success on a write that never landed.
            # (The mirror direction, a bare option sent to a multi-select, is a legitimate "select
            # just this one" and is wrapped in _coerce instead — the multiselect convention.)
            if not isinstance(getattr(el, "value", None), list) and isinstance(value, (list, tuple)):
                raise RuntimeError_(
                    f"{identifier!r} is a single-select {kind} (currently "
                    f"{_display(getattr(el, 'value', None))}), but {_display(value)} is a list — "
                    f"send one option, or rebuild the widget with selection_mode='multi'"
                )
            return
        if kind not in ("slider", "select_slider", "date_input"):
            return
        current = getattr(el, "value", None)
        is_range = isinstance(current, (list, tuple))
        given_list = isinstance(value, (list, tuple))
        if is_range and not given_list:
            raise RuntimeError_(
                f"{identifier!r} is a two-handle range {kind}: its value is a list "
                f"(currently {_display(current)}), but {_display(value)} is a single value — send "
                f"both handles as a 2-element list, e.g. [low, high]"
            )
        if given_list and not is_range:
            raise RuntimeError_(
                f"{identifier!r} is a single-value {kind} (currently {_display(current)}), but "
                f"{_display(value)} is a list — send one value, not a range"
            )
        if not is_range:
            return
        # A slider/select_slider range has exactly two handles. A date range is Streamlit's own
        # partial-selection model (it legitimately holds 0, 1, or 2 dates), so only an over-long
        # list is wrong there — a caller passing one date explicitly asked for a half-open range.
        n = len(value)
        if kind in ("slider", "select_slider") and n != 2:
            raise RuntimeError_(
                f"{identifier!r} is a two-handle range {kind}; expected 2 values, got {n}: "
                f"{_display(value)}"
            )
        if kind == "date_input" and n > 2:
            raise RuntimeError_(
                f"{identifier!r} is a date range; expected at most 2 dates, got {n}"
            )

    @staticmethod
    def _validate_choice(kind: str, el, value: Any) -> None:
        """Reject a selectbox/radio/select_slider/multiselect value that isn't an offered
        option, before it is written to AppTest. Skipped when the widget exposes no options.

        Membership is compared on the *string form* of both sides. AppTest stringifies a widget's
        options (Streamlit formats them with ``str`` for the accessor) but reports its value in the
        real type, so a widget built from non-string options — ``st.selectbox("Pick", [1, 2, 3])``,
        a very common pattern — advertises ``options ['1','2','3']`` while reading back ``value 1``.
        A literal ``value not in options`` check then rejected the natural typed value the tool had
        just advertised, breaking the list_widgets -> set_widget round-trip for that whole class of
        widget (#51). AppTest resolves either form to the real option (``set_value(2)`` and
        ``set_value("2")`` both land on the int ``2``), so both are accepted here."""
        options = list(getattr(el, "options", []) or [])
        choice_kinds = ("selectbox", "radio", "select_slider", "multiselect", *BUTTON_GROUP_KINDS)
        if not options or kind not in choice_kinds:
            return
        offered = {str(o) for o in options}
        # multiselect carries a list of values; select_slider a single value OR a (lo, hi) range;
        # selectbox/radio a single value. Every element must be an offered option — the range form
        # used to be skipped, so a bad handle silently reverted while reporting success (#33). A
        # pills/segmented_control is whichever shape its selection_mode makes it, so it follows the
        # value: a bad option reverts silently on a single-select, and is silently DROPPED from a
        # multi-select (['y','NOPE'] lands as ['y']) — a partial write reported as a success.
        many = kind in ("select_slider", "multiselect") or (
            kind in BUTTON_GROUP_KINDS and isinstance(value, (list, tuple))
        )
        values = list(value) if many and isinstance(value, (list, tuple)) else [value]
        invalid = [v for v in values if str(v) not in offered]
        if not invalid:
            return
        if not many:
            raise RuntimeError_(
                f"{value!r} is not a valid option for {kind}; choose one of {options}"
            )
        raise RuntimeError_(
            f"{invalid!r} are not valid options for {kind}; choose from {options}"
        )

    @classmethod
    def _validate_feedback(cls, kind: str, identifier: str, el, value: Any) -> None:
        """Reject an out-of-range or non-integer st.feedback rating before it is written.

        Feedback is the worst-behaved of the kinds added here: AppTest neither raises nor reverts
        an out-of-range index — it simply STORES it. A 5 on a 5-star widget (valid indices 0-4), a
        99, or a -1 all stick, so an agent's bad rating becomes the app's state with no signal at
        all. That is the silent-corruption family of #12/#31/#55 in its purest form, and the only
        defence is the same one: check up front. A non-integer is worse still — it raises inside
        the rerun and poisons the session (#10), so it has to be caught here too."""
        if kind != "feedback":
            return
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError_(
                f"{value!r} is not a valid rating for the feedback widget {identifier!r}; send a "
                f"whole number (0 is the first option)"
            )
        hi = cls._feedback_max(el)
        if value < 0 or (hi is not None and value > hi):
            bound = f"0-{hi}" if hi is not None else "0 or greater"
            raise RuntimeError_(
                f"{value!r} is out of range for the feedback widget {identifier!r}; "
                f"valid ratings are {bound}"
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

    @staticmethod
    def _validate_number(kind: str, identifier: str, el, value: Any) -> None:
        """Reject a fractional value for an *integer* number_input before it is written. AppTest
        truncates it (30.5 -> 30) without raising, so set_widget stored a value the caller never
        asked for and reported success — the silent-corruption sibling of #12/#55, noted while
        fixing #51. An integral float (30.0) is lossless, so it passes."""
        if kind != "number_input":
            return
        current = getattr(el, "value", None)
        # bool is an int subclass; a float number_input takes fractional values fine.
        if isinstance(current, bool) or not isinstance(current, int):
            return
        if isinstance(value, float) and not value.is_integer():
            raise RuntimeError_(
                f"{value!r} is not a valid value for the integer number_input {identifier!r}; it "
                f"would be truncated to {int(value)!r} — send a whole number"
            )

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
        # A non-string identifier (None, an int, ...) can't name a widget — reject it cleanly up
        # front. Otherwise it would sail past the key/label comparisons (and even wrongly match a
        # keyless widget when it's None) and reach re.fullmatch(), which raises a raw TypeError
        # instead of a clean WidgetNotFound. An agent that omits/nulls the identifier should get a
        # normal "not found", not a crash.
        if not isinstance(identifier, str):
            raise WidgetNotFound(f"no widget matching {identifier!r}")
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
    def _coerce(cls, kind: str, value: Any, el: Any = None) -> Any:
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
        if kind in BUTTON_GROUP_KINDS:
            # A multi-select holds a list; a bare option means "select just this one" — the same
            # convention multiselect uses below. Single-select is left alone, so a list sent to one
            # still reaches _validate_arity and is rejected rather than quietly wrapped.
            if isinstance(getattr(el, "value", None), list) and not isinstance(value, (list, tuple)):
                return [value]
            return value
        if kind == "feedback" and isinstance(value, str):
            try:  # a rating arrives as a string over the CLI (--set stars=3)
                return int(value)
            except ValueError:
                return value  # left for _validate_feedback to reject with a useful message
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
        if kind == "multiselect" and not isinstance(value, (list, tuple)):
            # a multiselect holds a list; a bare option ("a", or the int 1 for an int-option
            # widget) means "select just this one" — wrap it rather than handing AppTest a scalar
            # it would choke on iterating
            return [value]
        if kind in ("text_input", "text_area") and value is not None and not isinstance(value, str):
            # a JSON-typed value (True/41) bound for a text field becomes its string (#43). But
            # None is the field's own no-value sentinel (a value=None placeholder reports it), not a
            # value to stringify: str(None) -> "None" silently stored a wrong value at isError=False
            # (#60). None passes through to the shared null path (set_widget -> _clear_to_none).
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
