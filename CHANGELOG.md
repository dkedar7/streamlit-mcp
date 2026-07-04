# Changelog

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
