# Changelog

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
- **HTTP bearer auth is not yet enforced on the transport.** The token primitive
  (`Guardrails.require_bearer`) is implemented and tested, but is not yet bound to the
  FastMCP HTTP/SSE request path. As a safeguard, `serve` refuses to start an HTTP/SSE
  server on a non-loopback host. Wiring `FastMCP(auth=...)` with a token verifier is the
  top follow-up before networked HTTP is supported.
- **Sessions are not yet disposed.** Per-client isolation works, but there is no
  session-close hook, so long-running HTTP servers accumulate runtimes. Single-client and
  stdio use are unaffected.
- **No concurrency locking.** Concurrent requests sharing one session are not serialized;
  AppTest is not known to be re-entrant. Use one in-flight request per session for now.
- Output capture covers headings/markdown/caption/text; `st.write`/`st.error`/etc. are a
  planned coverage expansion.
