# Security / trust model

- **`app_path` is executed as trusted code** in the server process (that's how `AppTest` runs
  it). Only serve apps you trust.
- **`get_state` / `read_output` expose the app's `session_state`** to the caller. If the app
  keeps something sensitive there, `--redact <key>` scrubs it from `session_state` on every read. It does not
  scrub a value the app renders into an output (see below).
- **HTTP/SSE bearer auth is enforced.** Pass `--bearer-token <T>` and every HTTP/SSE request must
  send `Authorization: Bearer <T>` — a missing or wrong token gets `401` before any tool runs. A
  non-loopback host is allowed **only** with a token set; without one, `serve` binds `127.0.0.1`
  only and refuses a non-loopback host (fail closed). stdio is local and unauthenticated.
- **`serve` prints its effective auth and guardrails to stderr at startup**, built from the same
  guard the engine enforces, so you can confirm the flags took effect. A `--bearer-token` given with
  stdio is reported as having no effect (#146). The token is never printed.
- **`GET /health` and `/healthz` need no token** on HTTP/SSE, so a container `HEALTHCHECK`, a
  Kubernetes probe, or a script waiting for the server to come up gets a plain `200`. They return
  only `{"status": "ok", "server": "streamlit-mcp"}`, with no app path, state or versions, so
  leaving them open exposes nothing the token guards.

```bash
# loopback, token required on every request
streamlit-mcp serve app.py --transport http --port 8000 --bearer-token "$TOKEN"

# public host is allowed only because a token gates access
streamlit-mcp serve app.py --transport http --host 0.0.0.0 --bearer-token "$TOKEN"
```

## Guardrails

`--read-only` blocks state-changing tools (`set_widget`/`click`), and `--allow <id>` restricts
which widgets can be seen or set. Both are enforced **identically** on the CLI and over MCP.

`--allow` hides a non-listed widget everywhere: it's dropped from `list_widgets`/`get_layout`, it
can't be set or clicked, **and its value is filtered out of every `session_state` read**
(`get_state`, `read_output`, `get_layout`, and the state a write returns) — so the allow-list can't
be sidestepped by reading state directly. App state that isn't a widget (counters, flags an app
stashes in `session_state`) is preserved.

`--redact <key>` (repeatable) scrubs a `session_state` key's value from the state on every read:
`get_state`, `read_output`, `get_layout` and the state a write returns, on the CLI and over MCP.
It filters state, not rendered output: if the app displays the value itself, that text is still
returned in `outputs` (see the limitation below). Use it for
what an app stores itself, such as a token from a login flow; `--allow` can't hide that, because
it deliberately keeps app state that isn't a widget. Redacting a widget's key also withholds the
widget's value in `list_widgets`/`get_layout` (it's marked `"redacted": true`), but the widget
can still be set.

```bash
streamlit-mcp serve app.py --redact access_token --redact user_email
```

They also cover **`@mcp_tool` semantic tools**, and fail closed: because streamlit-mcp can't know
whether a given tool mutates, `--read-only` blocks *any* semantic tool, and `--allow` gates tool
**names** too — `--allow reset_all` opts one specific tool back in. So `--read-only` really is a
look-but-don't-touch surface, including the higher-level action layer.

## Known limitations

- **Sessions.** Calls on one client session are serialized, so a second call waits for the first
  rather than interleaving its rerun; different sessions run in parallel. A long-running HTTP/SSE
  server keeps every client's session until restarted unless you bound it:
  `serve --session-ttl 600` discards a session idle for 10 minutes, and `--max-sessions 50`
  discards the least recently used beyond 50. A discarded client's next call starts a fresh app
  session (its widget values and `session_state` are gone). stdio is a single session either way.
- **Output capture** covers prose (`st.title`/`header`/`markdown`/`write`/`text`/…), status
  (`st.success`/`error`/`warning`/`info`/`toast`) and data (`st.metric` — with its delta's
  good/bad colour — `code`, `json`, `dataframe`, `table`) and charts that carry their own data
  (`st.line_chart`/`bar_chart`/`area_chart`/`scatter_chart`, `altair_chart`, `vega_lite_chart`)
  as kind `chart`, with a one-line summary and the plotted records in `data` (up to 200 points).
  Plotly, pyplot, maps, images and media are not captured.
- **`--allow` and `--redact` filter *state*, not rendered output.** If the app itself renders a
  hidden value into an output (e.g. `st.write(st.session_state["secret"])`), that text is still
  returned. The guardrails govern state and widget access, not what the app chooses to display.
  `@mcp_tool` return values aren't filtered either.
