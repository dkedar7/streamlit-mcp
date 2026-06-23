# Changelog

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
