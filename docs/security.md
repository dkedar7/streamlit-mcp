# Security / trust model

- **`app_path` is executed as trusted code** in the server process (that's how `AppTest` runs
  it). Only serve apps you trust.
- **`get_state` / `read_output` expose the app's `session_state`** to the caller — do not put
  secrets there.
- **HTTP/SSE bearer auth is enforced.** Pass `--bearer-token <T>` and every HTTP/SSE request must
  send `Authorization: Bearer <T>` — a missing or wrong token gets `401` before any tool runs. A
  non-loopback host is allowed **only** with a token set; without one, `serve` binds `127.0.0.1`
  only and refuses a non-loopback host (fail closed). stdio is local and unauthenticated.

```bash
# loopback, token required on every request
streamlit-mcp serve app.py --transport http --port 8000 --bearer-token "$TOKEN"

# public host is allowed only because a token gates access
streamlit-mcp serve app.py --transport http --host 0.0.0.0 --bearer-token "$TOKEN"
```

## Guardrails

`--read-only` blocks state-changing tools (`set_widget`/`click`), and `--allow <id>` restricts
which widgets can be seen or set. Both are enforced **identically** on the CLI and over MCP.

They also cover **`@mcp_tool` semantic tools**, and fail closed: because streamlit-mcp can't know
whether a given tool mutates, `--read-only` blocks *any* semantic tool, and `--allow` gates tool
**names** too — `--allow reset_all` opts one specific tool back in. So `--read-only` really is a
look-but-don't-touch surface, including the higher-level action layer.

## Known limitations

- **Sessions are not disposed.** Per-client isolation works, but there is no session-close hook,
  so a long-running HTTP server accumulates one runtime per client. stdio and single-client use
  are unaffected.
- **No concurrency locking.** Concurrent requests sharing one session are not serialized, and
  `AppTest` is not known to be re-entrant — use one in-flight request per session for now.
- **Output capture** covers headings / markdown / caption / text; `st.write`, `st.error`, and
  similar are a planned coverage expansion.
