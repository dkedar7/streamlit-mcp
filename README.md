# streamlit-mcp

**Serve any Streamlit app as an MCP server.** Agents introspect your app's widgets,
set values, click buttons, and read the rendered output and `session_state` — natively,
over MCP, with **no browser automation**.

```bash
pip install streamlit-mcp          # or run with no install via: uvx streamlit-mcp ...

# serve an app over MCP (stdio for local clients)
streamlit-mcp serve app.py
# ...or HTTP/SSE on loopback for local networked agents
streamlit-mcp serve app.py --transport http --port 8000

# drive it yourself from the terminal (same engine the agent uses)
streamlit-mcp inspect app.py
streamlit-mcp call app.py --set "Name=agent" --click "Save" --read
```

Streamlit has no callback graph — it reruns the whole script per interaction — so
streamlit-mcp drives the app headlessly through Streamlit's own test runtime
(`streamlit.testing.v1.AppTest`) and returns the **semantic element tree**, not pixels.
Gradio and Dash already shipped native app-as-MCP; this fills the Streamlit gap.

## Use it with an MCP client

**Claude Desktop / Cursor** — add to your MCP config (`claude_desktop_config.json` or
`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "streamlit-mcp": {
      "command": "uvx",
      "args": ["streamlit-mcp", "serve", "/absolute/path/to/your/app.py"]
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add streamlit-mcp -- uvx streamlit-mcp serve /absolute/path/to/your/app.py
```

`uvx` runs the published package with no prior install. stdio (the default) is the right
transport for local clients.

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
- **HTTP/SSE bearer auth is enforced.** Pass `--bearer-token <T>` and every HTTP/SSE request
  must send `Authorization: Bearer <T>` — a missing or wrong token gets `401` before any tool
  runs. A non-loopback host is allowed **only** with a token set; without one, `serve` binds
  `127.0.0.1` only and refuses a non-loopback host (fail closed). stdio is local and
  unauthenticated.

## License

MIT
