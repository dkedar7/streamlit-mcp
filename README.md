# streamlit-mcp

**Serve any Streamlit app as an MCP server.** Agents introspect your app's widgets,
set values, click buttons, and read the rendered output and `session_state` — natively,
over MCP, with **no browser automation**.

```bash
uv tool install .        # or: pip install .

# serve an app over MCP (stdio for local clients, or HTTP/SSE for networked agents)
streamlit-mcp serve app.py
streamlit-mcp serve app.py --transport http --host 127.0.0.1 --port 8000

# drive it yourself from the terminal (same engine the agent uses)
streamlit-mcp inspect app.py
streamlit-mcp call app.py --set "Name=agent" --click "Save" --read
```

Streamlit has no callback graph — it reruns the whole script per interaction — so
streamlit-mcp drives the app headlessly through Streamlit's own test runtime
(`streamlit.testing.v1.AppTest`) and returns the **semantic element tree**, not pixels.
Gradio and Dash already shipped native app-as-MCP; this fills the Streamlit gap.

## Tools exposed to agents

| Tool | What it does |
|---|---|
| `list_widgets` / `get_layout` | introspect widgets (kind, label, value, constraints) |
| `set_widget(identifier, value)` | set a widget and rerun |
| `click(identifier)` | click a button and rerun |
| `read_output()` | the rendered element tree, agent-readable |
| `get_state()` | the app's `session_state` |

Supported widgets (v1): text_input, number_input, text_area, slider, selectbox,
multiselect, checkbox, radio, button, date_input. Unsupported elements (file_uploader,
custom components, `st.chat`, fragments) are reported explicitly, never silently dropped.

## Human ↔ agent parity

Everything an agent can do over MCP, a human can do via the CLI — both call the same
engine. The read-only mode and widget allow-list guardrails apply identically to both
surfaces.

## Security / trust model

- **`app_path` is executed as trusted code** in the server process (that's how AppTest
  runs it). Only serve apps you trust.
- **`get_state` / `read_output` expose the app's `session_state`** to the caller — do not
  put secrets there.
- **HTTP/SSE is loopback-only in v1.** A bearer-token primitive exists, but it is **not yet
  enforced** on the transport, so `serve` refuses to bind HTTP/SSE to a non-loopback host.
  Use stdio for local clients, or HTTP/SSE on `127.0.0.1`. Enforced networked auth is the
  top follow-up (see `CHANGELOG.md`).

## License

MIT
