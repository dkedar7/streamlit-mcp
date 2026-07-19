# Changelog

## 0.7.1 (2026-07-19)

Documentation fix. `README.md` is the PyPI long description, so this correction is the point of
the release — the text was wrong on the project page.

- **Fix:** the README listed `st.pills`, `st.segmented_control` and `st.feedback` as supported
  and, six lines further down, among the input widgets streamlit-mcp **"can't drive"** (#72). The
  0.7.0 promotion updated the same sentence in `docs/usage.md` and missed the README's, so a
  reader going top-to-bottom hit a direct contradiction on a headline 0.7.0 capability — and the
  second claim was simply false. The undrivable list now reads `file_uploader`, `camera_input`,
  `audio_input`, `chat_input`, `data_editor`, which matches what the code reports.

- **Internal:** CI now guards the two classes the nightly dogfood routine keeps finding first.
  The routine installs the published package clean-room and follows the docs verbatim, so it is a
  doc-conformance tester by construction and every doc/behaviour gap is a guaranteed find. The
  docs' widget lists are now asserted against `SUPPORTED_KINDS`/`UNSUPPORTED_ELEMENTS` (in *both*
  docs — checking only one is how #72 escaped), and text↔`--json` surface parity is asserted
  across the whole command matrix rather than one surface at a time, which is what let #1 → #58 →
  #64 keep re-opening.

## 0.7.0 (2026-07-19)

Widens what an agent can **see** and **drive**, plus one crash-reporting false positive. The
supported list turned out to be stale rather than accurate — three widgets it called undrivable
are drivable, and the read surface had a larger gap than any of them.

- **New:** an agent can now see the **status and data outputs** an app renders, not just its prose.
  Previously only `title`/`header`/`subheader`/`markdown`/`caption`/`text` were reported, so an
  agent that filled a form and clicked submit **could not tell whether the app answered
  `st.success("Saved")` or `st.error("Name is required")`** — the outcome of its own action was
  invisible, leaving it to re-read widget values and guess. Adds the status kinds (`success`,
  `error`, `warning`, `info`) and the data kinds (`metric`, `code`, `json`, `dataframe`, `table`).

    A `metric` is assembled rather than stringified — its `value` is the bare number, so a
    dashboard of four metrics read as four anonymous numbers; it now reports as
    `Total: $4,210 (+8%)`. Output text is capped, because `st.json` serializes a whole structure
    (~11 KB for a 2000-element list) where a DataFrame self-truncates, and one output should not
    crowd out the rest of the app.

- **New:** `st.pills`, `st.segmented_control` and `st.feedback` are **supported widgets**, no
  longer reported as undrivable. `pills` and `segmented_control` share the `button_group` protobuf
  name in the element tree — which is why they were written off — but Streamlit's typed accessors
  tell them apart, so they are driven under the names you write in the app. A `feedback` widget's
  scale (`thumbs` 0-1, `faces`/`stars` 0-4) is read off the widget proto by enum name.

    All three corrupt silently when driven naively, so each is guarded up front, in the tradition
    of #12/#31/#55: a bad option on a single-select **reverts with no exception**; a bad member of
    a multi-select is **silently dropped** (`['y','NOPE']` lands as `['y']` — a partial write
    reported as success, #33); and an out-of-range `feedback` rating is neither rejected nor
    reverted but **stored** — `5` on a 5-star widget, `99`, `-1` all stuck. A `selection_mode` is
    not exposed by Streamlit, so the value's shape is the signal (a list means multi), the same
    signal a range widget gives.

- **Fix:** a deliberate **`st.exception(e)` is no longer reported as an app crash** (#69). It is
  the documented way to *show* a handled error, but every exception element was read as the app's
  uncaught exception — so an app that handles errors correctly looked broken on every surface, and
  `--strict` failed CI for it. Streamlit offers nothing that separates the two directly (there is
  no `SCRIPT_STOPPED_WITH_EXCEPTION` event, and a caught exception displayed on purpose carries a
  real stack trace just like a crash), but an uncaught exception **halts the script** — so anything
  rendered after an exception element proves it was deliberate. Deliberately partial: a lone
  `st.exception(e)` as an app's final statement is indistinguishable from a crash and keeps
  reporting, because missing a real crash would break the guarantee #27/#58/#64 exist to give.

**Behavior changes:** `read_output`/`get_layout` now report more output kinds, so an agent reading
`outputs` sees entries it did not before (additive; existing kinds are unchanged, and `exception`
is deliberately excluded so a crash is not duplicated into `outputs`). `pills`,
`segmented_control` and `feedback` move out of `unsupported` and into `widgets`, and are settable.
An app that only ever displayed a handled exception no longer reports an `exception` field and no
longer exits non-zero under `--strict`.

## 0.6.0 (2026-07-18)

Two self-consistency fixes from the nightly dogfood run, both instances of the same theme the
0.5.x line has been working through: **the tool must not contradict itself across its own
surfaces**. Also carries the 0.5.1 fix below, which was never published separately.

- **Fix:** a widget built from **non-string options** (`st.selectbox("Year", [2023, 2024, 2025])`)
  no longer reports a `value` that violates the `schema` the same call advertises (#62). It read
  back `value: 2023` (int) against `{"type": "string", "enum": ["2023","2024","2025"]}` — a value
  that is neither a member of nor the type of its own schema, so a schema-validating agent balked
  at output the tool itself emitted. #51 fixed only the *write* path (`set_widget` matches on
  string form); the advertised model stayed self-inconsistent. The `enum` now carries **both**
  forms — `[2023, 2024, 2025, "2023", "2024", "2025"]` — so the reported value is always a member,
  and **any** option can be set in either form, not just the one currently selected.

    Streamlit hands over options already stringified, so the current value's type is the only
    evidence of the real option type available at runtime. It's used to recover every option's
    typed form, guarded by a round-trip check so a typed member always denotes the option it came
    from: a mixed list (`[1, "two", 3.0]`) keeps the unrecoverable options in string form, and
    `bool` gets its own mapping (`bool("False")` is `True`). A widget with **nothing selected**
    (an untouched `st.multiselect("Nums", [1,2,3])`) offers no such evidence and keeps the string
    form — still correct and settable, just less informative.

- **Fix:** a command's `--json` form now carries the app-level `exception` its own **text** form
  prints (#64). 0.5.0 (#58) made all four text CLI forms report a crashed app, but bare
  `inspect --json` and `call --state --json` still dropped it — so within the *same command* the
  human saw `exception: boom` and a script doing `inspect --json | jq .exception` got `null`.
  Those two payloads come from `list_widgets`/`get_state`, which legitimately don't carry the
  field (they mirror MCP tools that don't), while `get_layout`/`read_output` do. The value is now
  injected once per command wherever it's missing, rather than being plumbed surface by surface —
  the pattern that let this family (#27 → #58 → #64) keep re-opening. The **MCP contract is
  unchanged**; this is a CLI text↔`--json` parity fix, and it closes a gap against the documented
  guarantee that the exception is surfaced on every read surface.

**Behavior changes:** a non-string-option `selectbox`/`radio`/`select_slider`/`multiselect` now
advertises a mixed-type `enum` (both the typed and string form of each option) and no longer
carries `"type": "string"`, since a mixed enum has no single JSON-Schema type; pure-string-option
widgets are untouched. `inspect --json` and `call --state --json` gain an `"exception"` field when
the served app raised — a healthy app's payload is byte-identical to before. No previously-correct
set stops working.

Thanks to [@Sanjays2402](https://github.com/Sanjays2402) for #63, which found and fixed the
non-string-option schema inconsistency.

## 0.5.1 (2026-07-16 — never published separately; shipped in 0.6.0)

Completes the null-placeholder fix from 0.5.0 (#57), which covered only `selectbox`/`radio` and
left the other widgets that legitimately hold `value: None` broken the same way (#60). The whole
class is now handled by **one shared path** — schema nullability keyed on the value, and a single
kind-agnostic write path — so it can't re-open widget-by-widget.

- **Fix:** a `text_input`/`text_area` built with `value=None` (the "empty field" placeholder) no
  longer **corrupts its value on write-back**. Echoing its reported `value: null` back over MCP —
  `set_widget("name", null)` — stored the literal string `"None"` and returned `isError=False`:
  the value an agent just read couldn't be sent back, state was silently mutated to a wrong value,
  and the failed round-trip was reported as success. The `str(value)` coercion added for #43 (so a
  JSON-typed value on a text field becomes its string — `True` → `"True"`) wrongly caught `None`,
  the field's own no-value sentinel. `None` now passes through and round-trips as `null`. (Non-None
  values still stringify, as #43 intends.)

- **Fix:** the `None`-placeholder **schema is now nullable for every widget that reports
  `value: null`**, not just `selectbox`/`radio`. A `text_input`/`text_area`/`number_input` (and
  `date_input`/`time_input`) built with `value=None` advertised `value: null` against a
  non-nullable schema (`{"type": "string"}` / `{"type": "number"}`), so a schema-validating agent
  balked at a value the tool itself emitted — the (b)-half of #57, left unfixed for non-option
  widgets. `tool_schema_for` now widens the schema to allow null whenever the reported value is
  null, uniformly (`{"type": ["string","null"]}`, `{"type": ["number","null"], …}`), so the
  reported value always satisfies its own schema.

- Under the hood, `set_widget(id, null)` is now one **kind-agnostic** operation ("return the widget
  to its no-value/no-selection state"): a `value=None`/`index=None` placeholder of any kind accepts
  null and round-trips it; a regular widget (a `selectbox` with a default, a plain `text_input`, a
  `number_input` with a value) has no no-value state and **rejects null atomically** — with its
  prior value intact — instead of silently keeping it (text previously stored `"None"`; a regular
  `number_input`/`selectbox` silently no-op'd or reset to default). One documented rule per the
  issue's suggestion, so the next placeholder-capable widget is covered for free.

**Behavior changes:** a `value=None` `text_input`/`text_area`/`number_input`/`date_input`/
`time_input` now advertises a nullable schema (`["…","null"]`) instead of the bare type, and
`set_widget(id, null)` on such a widget round-trips (text no longer stores `"None"`); a regular
widget of those kinds now rejects `null` where text used to store `"None"` and number silently
ignored it. No previously-correct set stops working.

## 0.5.0 (2026-07-15)

Two more fixes from the nightly dogfood routine — both restoring fidelity between what a surface
reports and what it accepts, the same through-line as 0.4.0.

- **Fix:** a **placeholder** `selectbox`/`radio` (built with `index=None` — the ubiquitous
  "please select…" pattern) now round-trips its no-selection value (#57). Its value is reported as
  `null`, but that `null` (a) violated the widget's own advertised `schema` — `list_widgets`/
  `inspect --json` emitted `enum: [...options]` with no `null`, while reporting `value: null` — and
  (b) was **rejected on write-back**: `set_widget("choose", null)` failed with "None is not a valid
  option", even though `null` is exactly the value the tool just reported. So the round-trip was
  broken for the whole placeholder class: an agent read `value: null` and couldn't send it back.
  Two coordinated changes: the schema is now **nullable when the value is null**
  (`{"type": ["string","null"], "enum": [...options, null]}`), so the reported value satisfies its
  own schema; and `set_widget(id, null)` **clears the selection** back to the placeholder (a real
  "reset this filter" operation AppTest supports). A *regular* (`index=0`) selectbox/radio, which
  genuinely has no no-selection state, still rejects `null` — with the prior value rolled back, so
  the set stays atomic. (That path can't be pre-validated: AppTest exposes no "is nullable" flag
  and silently keeps or default-resets a non-nullable widget set to `null`, so it's caught by
  setting `null` and verifying the selection actually cleared — sound because `null` is never a
  value-corrupting write to attempt.)

- **Fix:** the human text CLI now **surfaces a served app's uncaught exception**, matching `--json`
  and MCP (#58). When an app raises, the exception is captured in the structured `exception` field
  and reported on `--json` (`call`/`inspect`) and over MCP (`read_output`/`get_layout`) — but the
  default text CLI dropped it, printing only the partial render with **`exit 0`** and no error line,
  so a crashed app looked like a clean, successful run (and only Streamlit's raw stderr traceback
  hinted otherwise — the very dump #27 keeps off the protocol channel). This broke the headline
  human↔agent parity guarantee on the error surface. `call --read`, `call --state`, and
  `inspect --layout`/bare `inspect` now print an `exception:` line matching what `--json`/MCP carry.

- **New:** a **`--strict` flag** on `call` and `inspect` makes them **exit non-zero** when the
  served app raised an uncaught exception, so a crashed app is detectable in CI/scripts without
  parsing `--json` for a non-null `exception` (`streamlit-mcp call app.py --read --strict || …`).
  Default behavior is unchanged: an app-level exception is a *reported field*, not a failure — over
  MCP it returns with `isError=False`, and the CLI mirrors that with `exit 0` unless `--strict` is
  set. (A guardrail/load error is a real failure and still exits non-zero regardless.)

**Behavior changes** (why this is a minor bump): a placeholder `selectbox`/`radio` advertises a
nullable schema (`["string","null"]`) instead of the bare `string` enum, and `set_widget(id, null)`
on such a widget now succeeds where it used to error; the text CLI prints an `exception:` line for a
crashed app where it previously printed nothing. No previously-working set stops working, and the
default exit codes are unchanged.

## 0.4.0 (2026-07-13)

Five fixes from the nightly dogfood routine, all of the same family: the widget model lost
**type, arity, or placement** fidelity, so a value an agent read back could not be sent back.

- **Fix:** a widget built from **non-string options** (`st.selectbox("Pick", [1, 2, 3])` — a very
  common pattern) can now be set to its natural typed value (#51). AppTest stringifies a widget's
  options but reports its value in the real type, so such a widget advertised
  `options: ["1","2","3"]` while reading back `value: 1` — and `_validate_choice` compared the
  incoming value against the *stringified* options, rejecting `2` (a genuine option, and the same
  type as the value the tool had just advertised) as "not a valid option". The whole class of
  numeric/non-string-option widgets was undrivable on the CLI and misrepresented over MCP, breaking
  the `list_widgets` → `set_widget` round-trip. Membership is now compared on the string form of
  both sides, so **both** the typed value (`2`) and the option's string form (`"2"`) are accepted —
  AppTest resolves either to the real option. A value that genuinely isn't an option is still
  rejected. (Also: a **fractional value on an integer `number_input`** — `Score=30.5`, which
  AppTest silently truncated to `30` while reporting success — is now rejected up front.)

- **Fix:** unsupported widgets placed through a **container accessor** are no longer silently
  dropped (#52). `detect_unsupported` regex-scanned the source for the literal `st.<name>(` form,
  so `st.sidebar.file_uploader(...)`, `col.camera_input(...)`, `container.download_button(...)` and
  `tab.data_editor(...)` — the sidebar and columns idioms most real apps are built from — matched
  nothing and were reported nowhere, on any surface. That is exactly the failure the "never
  silently dropped" guarantee exists to prevent: an agent introspecting such an app got no
  indication the widget existed. The scan now parses the source as an **AST** and matches the call
  node's attribute, so any receiver is caught (including an aliased `import streamlit as sl`), and
  occurrences in comments and string literals — previously reported as real — no longer are.
  (The runtime element tree can't serve as the detector: AppTest names nodes after their protobuf
  type, so `st.data_editor` arrives as `dataframe`, indistinguishable from a plain `st.dataframe`
  output, and pills/segmented_control/feedback all collapse into `button_group`.)

- **Fix:** `st.form` is now a **supported flow**, and `form_submit_button` is no longer
  double-reported (#53). It was listed *both* as a supported, clickable `button` **and** as
  `unsupported` with the reason "drive it another way" — which was simply false: clicking it
  submits the form and runs its body, over the CLI and MCP alike. An agent reading `get_layout`
  reasonably concluded it could not submit the form, and gave up on an interaction it was fully
  capable of performing. `form_submit_button` is dropped from `UNSUPPORTED_ELEMENTS`; a form is
  driven the way a human drives it — set the fields, then click the submit button.

- **Fix:** the CLI no longer JSON-pre-parses a `--set` value that **is one of the widget's own
  options** (#54). An option widget whose options are genuinely strings that look like JSON tokens
  (`["true","false"]`, a `["1","2","3"]` version picker) could not be set from the CLI at all:
  `--set "Env=true"` was pre-parsed to the boolean `True`, matched no option, and was rejected —
  while the identical string sent over MCP was accepted. A CLI-only failure on a common widget
  class, and a human↔agent parity break; the only way through was to guess the `--set 'Env="true"'`
  quoting trick. This is the #43 class (CLI JSON pre-parse corrupting a value that should be a
  literal string), which #43 fixed only for `text_input`/`text_area`. `--set` now prefers an exact
  match against the target's advertised options over the JSON parse (`Rng=[5,95]`, `Tags=[]` and
  `Age=41` keep parsing as before).

- **Fix:** two-handle **range** widgets (`st.slider("P", 0, 100, (20, 80))`,
  `st.select_slider(..., value=("s","l"))`, `st.date_input(..., value=(d1, d2))`) now advertise a
  range, and a wrong-arity value is rejected instead of silently discarded (#55). They hold a
  2-element list but advertised the **scalar** schema of their single-handle form, so nothing in
  the model said the widget was a range — and a schema-following agent that sent the scalar it was
  told to send had its write **silently thrown away** (slider/select_slider reverted to the prior
  value; a date range degraded to a one-element range) while `set_widget` reported success. The
  schema is now range-aware (`{"type": "array", "items": …, "minItems": 2, "maxItems": 2}`), and
  `set_widget` validates **arity** up front, in both directions — a single value sent to a range
  widget, and a list sent to a single-handle one, are both rejected with a clear error, leaving the
  prior value untouched. This closes the silent-revert class (#10/#12/#31/#33) for the arity case:
  those validators guarded a value's *content*, leaving its *shape* unchecked.

**Behavior changes** (why this is a minor bump, not a patch): range widgets advertise an array
schema instead of a scalar one; `form_submit_button` moves from `unsupported` to a supported
`button`; `set_widget` now rejects two inputs it previously accepted and then discarded (a
wrong-arity value, and a fractional value on an integer `number_input`); and an unsupported element
that appears only in a comment or a string literal is no longer reported. Every new rejection
replaces a silent failure — nothing that used to apply cleanly stops applying.

## 0.3.12 (2026-07-08)

- **Fix:** `set_widget`/`click` with a **non-string identifier** (e.g. `None` or a number — an agent
  that omits or nulls the `identifier` argument) now raise a clean `WidgetNotFound` instead of
  crashing with `TypeError: expected string or bytes-like object`. The `kind[index]` resolver added
  in #41 ran `re.fullmatch()` on the identifier; a `None`/int slipped past the key/label comparisons
  and hit the regex, which raised a raw `TypeError`. `_find` now rejects a non-string identifier up
  front. (Surfaced by the StreamlitArena benchmark, driving apps with a small model that emitted a
  null identifier.)

## 0.3.11 (2026-07-07)

- **Fix:** the CLI no longer mangles `text_input`/`text_area` values that look like JSON (#43).
  `--set` JSON-parses values so typed widgets get real numbers/lists/booleans, but that parse was
  applied unconditionally — so `Comment=true` on a text field became the boolean `True`, then was
  `str()`-ified to `"True"`; `null`→`"None"`; a pasted `{"a": 1, "b": true}` came back as a Python
  `repr` (`"{'a': 1, 'b': True}"`, no longer valid JSON). The same value over MCP is stored
  verbatim, so this was silent data corruption on the most common widget kind **and** a human↔agent
  parity break. The CLI now resolves the target widget kind first and passes the **raw string**
  through for `text_input`/`text_area` (keeping JSON parsing for list/number/boolean widgets), so
  `Comment=true` stores `"true"` — matching MCP.

## 0.3.10 (2026-07-06)

- **Fix:** the `kind[index]` identifier that `list_widgets`/`get_layout`/`inspect` advertise for a
  keyless, empty-label widget (e.g. `text_input[1]`) is now resolvable by `set_widget`/`click`
  (#41). `_identifier` minted the `kind[index]` fallback but `_find` only matched key/label, so the
  one handle the tools ever exposed for such a widget was a dead handle — `set_widget`/`click`
  rejected it with `no widget matching`, breaking the `list_widgets` → `set_widget` round-trip on
  both CLI and MCP. `_find` now resolves the `kind[index]` form. To guarantee it names the same
  widget `snapshot()` advertised (accessor order ≠ document order once a sidebar is involved),
  `snapshot()` and `_find` now share one document-order widget iterator, so the numbering can't
  drift between what's shown and what's resolved.

## 0.3.9 (2026-07-05)

- **Fix:** `read_output`/`get_layout`/`list_widgets`/`inspect` now return elements in
  **document/render order** instead of grouping them by kind (#39). `snapshot()` built its lists
  by iterating each kind's typed accessor (`at.title`, `at.markdown`, `at.text_input`, …) in turn,
  so every heading was hoisted above all body text and a form's fields were regrouped by type —
  the transcript an agent read back bore no relation to how the app renders. It now walks the
  block tree (sidebar then main, recursing into columns/expanders) in render order, so the
  "rendered element tree" the README advertises is actually ordered. Same elements are captured —
  only their order changes — on every surface (text CLI, `--json`, MCP). Order *within* a kind was
  already correct; this fixes the cross-kind grouping.

## 0.3.8 (2026-07-04)

Proactive hardening of guardrail enforcement coverage, from a self-audit of every action/read
path against read-only, allow-list, and bearer auth (the class behind #4/#7/#26):

- **Security fix:** the `--allow` allow-list no longer leaks a hidden widget's **value**. A
  non-listed widget was correctly dropped from `list_widgets`/`get_layout` and blocked from
  `set_widget`/`click`, but its value still came back through every `session_state`-bearing read
  (`get_state`, `read_output`, `get_layout`, and the dict a write returns) — so the allow-list
  guarded the *widgets* surface but not the *state* surface (the same "guard misses a path" shape
  as #26). The allow-list now filters those hidden widgets' values out of `session_state` on all
  read paths, on both the CLI and MCP. App state that isn't a widget (counters, flags an app
  stashes in `session_state`) is preserved, so nothing is over-hidden; `--read-only` and the
  no-guard path are unchanged (they don't filter reads). See `docs/security.md` for the one
  remaining caveat (the allow-list governs widget *state*, not what an app chooses to *render*).

## 0.3.7 (2026-07-04)

Proactive hardening of `set_widget` value coercion, from a self-audit of the whole widget
surface for the silent-revert / atomicity class (siblings of #12, #31, #33):

- **Fix:** an out-of-range element in a **`date_input` range** (`(start, end)`) is now rejected
  instead of silently reverting. The range value stayed a list of raw strings (only bare-string
  dates were coerced), so `_validate_range` hit a `str < date` `TypeError`, bailed, and let the
  bad date slip through to a silent revert-and-report-success. `date_input` now coerces **each**
  end of a range to a real date, so the bounds check runs and rejects the bad end up front,
  leaving the prior value untouched (atomic, CLI + MCP).
- **Cleaner errors:** an unparseable `number_input`, `date_input`, or `time_input` value now
  raises a clear, actionable message (e.g. `'abc' is not a valid number for number_input`;
  `'25:99' is not a valid time for time_input; use 24-hour 'HH:MM' like '09:30'`) instead of a
  raw Python `ValueError` (`could not convert string to float`, `Invalid isoformat string`).
- **Boolean spellings:** `checkbox`/`toggle` accept the natural string/int spellings a human
  passes on the CLI (`true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off`, case-insensitive) and reject
  anything else with a clear `not a valid boolean` error rather than an opaque rollback message.

## 0.3.6 (2026-07-04)

- **Fix:** an invalid **range** (two-handle) `select_slider` value is now rejected instead of
  silently reverting (#33). The single-value form was already validated, but `_validate_choice`
  explicitly skipped list/tuple values, so a range set with a handle that isn't an offered option
  (e.g. `["xl", "NOPE"]`) fell through all three safety nets — AppTest reverts the bad handle to
  the default without raising, so `set_widget` reported success (`exit 0` / `isError=false`) while
  discarding the requested value and clobbering any prior valid range. `select_slider` now
  validates **every** handle against `options` (like `multiselect`), raising a clear error up front
  and leaving the prior value untouched (atomic, CLI + MCP). Closes the last known gap in the
  silent-revert class (#10/#12/#31).

## 0.3.5 (2026-07-03)

- **Fix:** an invalid `color_picker` value is now rejected instead of silently reverting (#31).
  `color_picker` became a supported widget in 0.3.4, but a bad value (`"notacolor"`, a CSS name,
  a wrong-length hex) fell through both validation nets: AppTest normalizes it back to the widget
  default **without raising**, so `set_widget` reported success (`exit 0` / `isError=false`) while
  discarding the requested value — and clobbering any prior valid one in a long-lived session. This
  is the same silent-revert class as the out-of-range fix in #12, now closed for `color_picker`:
  `set_widget` validates up front that the value is a `#RGB`/`#RRGGBB` hex string and raises a clear
  error otherwise, leaving the prior value untouched (atomic, on both the CLI and MCP).

## 0.3.4 (2026-07-02)

- **Widgets no longer silently dropped** (#29). Any input widget that was neither in the
  supported set nor the unsupported list vanished from `widgets` **and** `unsupported` on every
  surface, breaking the "reported explicitly, never silently dropped" guarantee. Now:
  - **`time_input`, `toggle`, `select_slider`, and `color_picker` are supported** — introspected
    and drivable via `set_widget` (AppTest drives them; `time_input` accepts `"HH:MM"`). This also
    resolves the inconsistency where `live()` synced `time_input` but `inspect` showed nothing.
  - the remaining input widgets streamlit-mcp can't drive (`pills`, `segmented_control`,
    `feedback`, `link_button`, `page_link`, `form_submit_button`, plus the existing
    file/camera/audio/chat/data_editor/download_button) are **reported in `unsupported`**.

## 0.3.3 (2026-07-01)

- **Fix:** an uncaught app exception no longer corrupts stdout (#27). Streamlit prints a rich
  traceback to **stdout** when a served app raises; that made `--json` unparseable and put
  non-protocol bytes on the stdio MCP JSON-RPC channel. The app's stdout is now redirected to
  stderr for the duration of each run, so stdout carries only the JSON payload / MCP messages —
  the error is still reported in the structured `exception` field.
- **Fix (security):** `--read-only` and `--allow` now cover `@mcp_tool` semantic tools on both the
  CLI and MCP (#26). Previously a semantic tool ran with full side effects despite `--read-only`,
  returning success. It now fails closed: `--read-only` blocks any tool; `--allow` gates tool
  names too (`--allow <tool>` opts one back in).
- **Robustness:** the AppTest run timeout is raised from its 3s default so a slow app or a loaded
  CI box doesn't spuriously fail a run.

## 0.3.2 (2026-06-29)

- **Fix:** `live()`'s polling fragment is now reliably skipped under headless AppTest (the agent
  driving over MCP, or tests). The previous `st.runtime.exists()` gate was `True` under AppTest
  too, so the `run_every` fragment could install and intermittently hang a headless run for apps
  using `st.columns`. AppTest mocks the runtime, so a genuine `Runtime` instance is now the gate;
  the live browser still polls as before.
- **Docs:** new "Dynamic / agent-driven layout" guide + `examples/dynamic_app.py` — the agent
  adds components and rearranges the layout by driving state (the app's structure is a function of
  state it controls), with the human watching live.

## 0.3.1 (2026-06-29)

- **Fix:** `live()` now syncs `date_input`/`time_input` values. `FileStore` used a plain
  `json.dumps`, so a synced `datetime.date` (a documented supported widget) raised
  `TypeError: Object of type date is not JSON serializable` — crashing the rerun, never
  persisting the store, yet reporting success. `FileStore` now uses a symmetric
  date/datetime/time codec so those values round-trip back as real objects (#23).
- **Fix (parity):** `@mcp_tool` semantic tools are now reachable from the CLI, restoring the
  "Human ↔ agent parity" guarantee. `inspect` lists them (text, `--json`, `--layout`) and
  `call --tool <name> [--arg k=v ...]` invokes one — both via the same registry the MCP server
  uses. Previously they were callable over MCP but invisible/uncallable from the CLI (#21).

## 0.3.0 (2026-06-28)

- **New: `streamlit_mcp.live`** — opt-in live human-in-the-loop sync. Wrap your widgets in
  `with live(name, defaults={...}):` and an agent's edits over MCP appear in a watching browser
  live (no manual refresh, no browser automation). It bridges Streamlit's isolated sessions
  through a shared, versioned store the app re-reads — re-seeding widget `session_state` before
  widgets are created, publishing local edits on exit, and polling via `st.fragment(run_every=...)`
  in a live browser (skipped under headless AppTest). Ships a `FileStore` (atomic writes) by
  default and a `Store` protocol so a custom backend (e.g. Redis) can be passed for multi-node.
  Purely app-side — no new MCP tools, no engine/server changes. See the docs "Live /
  human-in-the-loop" page and `examples/live_app.py`.

## 0.2.3 (2026-06-27)

- **Fix:** a `@mcp_tool` defined in the served app file is now actually exposed over `serve`
  (#14). The decorator only fires when the app module executes, but sessions run the app
  lazily — after the tool list was already built — so app-file semantic tools were silently
  never registered. `serve` now loads the app once at startup before building the tool list,
  and `@mcp_tool` registration is idempotent so per-session re-runs don't error. Documented
  in the README.
- **Fix:** `inspect` on a missing/unloadable app file now prints a clean one-line error and
  exits 1, matching `call`, instead of dumping a raw Python traceback (#15).

## 0.2.2 (2026-06-26)

- **Fix:** an out-of-range `number_input`/`slider`/`date_input` `set_widget` is now rejected up
  front with a clear error, instead of silently reverting the widget to its default and reporting
  success (#12). 0.2.1 made *option* widgets atomic; range-constrained widgets fell through both
  safety nets because AppTest doesn't raise on an out-of-range value — it resets to the default —
  so a bad value reported `isError=False` while discarding the prior valid value. `set_widget` now
  range-checks against the widget's `min`/`max` before writing, matching the option path.

## 0.2.1 (2026-06-25)

- **Fix:** a failed `set_widget` no longer poisons a long-lived MCP session (#10). Setting a
  selectbox/radio/multiselect to an option that isn't offered is now rejected up front with a
  clear error (it lists the valid options) **before** any state changes — previously the bad
  value was left pending in the AppTest runtime, so every later `set_widget`/`click` on any
  widget re-raised the stale error and the failing call could silently apply its own mutation.
  Any other failed run is now rolled back to the prior value so the session stays usable, and
  the error is attributed to the call that caused it.

## 0.2.0 (2026-06-25)

- **Bearer auth is now enforced on HTTP/SSE** (#7). `serve --transport http|sse --bearer-token
  <T>` wires a FastMCP token verifier, so every request must carry `Authorization: Bearer <T>`
  — a missing or wrong token gets **401** before any tool runs. stdio stays local/unauthenticated.
  - Non-loopback hosts are now allowed **when a token is set** (auth gates access); without a
    token, `serve` still refuses a non-loopback host (fail closed).
  - Removes the 0.1.2 "token is set but not enforced" startup warning — it's no longer true.
- **CI:** bump `actions/checkout` (v4→v7) and `astral-sh/setup-uv` (v5→v7) to clear the Node-20
  deprecation (#8).

## 0.1.2 (2026-06-24)

- **Fix (security UX):** `serve --transport http/sse` now prints a prominent stderr warning
  when `--bearer-token` is set, because bearer auth is **not yet enforced** on the transport —
  the server accepts unauthenticated loopback requests. Previously the flag was silently
  accepted with no effect while `--help` claimed it was "required", implying a protection that
  did not exist. The `--help` text now states the flag is reserved/not-yet-enforced (#4).
  (Real `FastMCP(auth=…)` enforcement remains the documented top follow-up.)

## 0.1.1 (2026-06-23)

Fixes from a clean-room dogfood of the published 0.1.0.

- **Fix (parity):** `inspect --layout` text output now lists unsupported elements. The
  `unsupported` section was present in `--json` and the MCP `get_layout` tool but silently
  dropped from the default human/text view, contradicting the "reported explicitly, never
  silently dropped" guarantee (#1).
- **Add:** a top-level `--version` flag (`streamlit-mcp --version`) (#2).
- **Fix:** silence Streamlit's explicitly-ignorable "missing ScriptRunContext!" bare-mode
  warning that leaked to stderr on every `inspect`/`call`/`serve` (#2).
- **Packaging/docs:** declare Python 3.13 support (trove classifier + CI matrix); 0.1.0 is
  marked released below (#2).

## 0.1.0 (2026-06-20)

First release. Serve an existing Streamlit app as an MCP server, driven headlessly via
`streamlit.testing.v1.AppTest` — no browser automation.

- Auto-introspect all ten v1 widget kinds (text_input, number_input, text_area, slider,
  selectbox, multiselect, checkbox, radio, button, date_input) into MCP tools.
- Core MCP tools: `list_widgets`, `get_layout`, `set_widget`, `click`, `read_output`,
  `get_state`. Unsupported elements are reported explicitly.
- Transports: stdio and HTTP/SSE (see Known issues for HTTP auth status).
- Human-first CLI (`serve`/`inspect`/`call`) with parity to the MCP tools.
- `@mcp_tool` decorator for opt-in semantic tools.
- Guardrails: read-only mode and widget allow-list (enforced on both CLI and MCP).

### Known issues / immediate follow-ups
_Snapshot as of 0.1.0. Later releases resolved some of these (see the entries above); the
README's "Known limitations" tracks what's still open today._
- **HTTP bearer auth is not yet enforced on the transport.** The token primitive
  (`Guardrails.require_bearer`) is implemented and tested, but is not yet bound to the
  FastMCP HTTP/SSE request path. As a safeguard, `serve` refuses to start an HTTP/SSE
  server on a non-loopback host. Wiring `FastMCP(auth=...)` with a token verifier is the
  top follow-up before networked HTTP is supported.
  **→ Resolved in 0.2.0** — bearer auth is enforced (401 without a valid token), and a
  non-loopback host is allowed when a token is set.
- **Sessions are not yet disposed.** Per-client isolation works, but there is no
  session-close hook, so long-running HTTP servers accumulate runtimes. Single-client and
  stdio use are unaffected.
- **No concurrency locking.** Concurrent requests sharing one session are not serialized;
  AppTest is not known to be re-entrant. Use one in-flight request per session for now.
- Output capture covers headings/markdown/caption/text; `st.write`/`st.error`/etc. are a
  planned coverage expansion.
