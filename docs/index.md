# streamlit-mcp

**Serve any Streamlit app as an MCP server.** Agents introspect your app's widgets, set
values, click buttons, and read the rendered output and `session_state` — natively, over MCP,
with **no browser automation**.

```bash
pip install streamlit-mcp          # or run with no install via: uvx streamlit-mcp ...
```

```bash
# serve an app over MCP (stdio for local clients)
streamlit-mcp serve app.py
# ...or HTTP/SSE on loopback for local networked agents
streamlit-mcp serve app.py --transport http --port 8000

# drive it yourself from the terminal (same engine the agent uses)
streamlit-mcp inspect app.py
streamlit-mcp call app.py --set "Name=agent" --click "Save" --read
```

Streamlit has no callback graph — it reruns the whole script per interaction — so streamlit-mcp
drives the app headlessly through Streamlit's own test runtime (`streamlit.testing.v1.AppTest`)
and returns the **semantic element tree**, not pixels. Gradio and Dash already shipped native
app-as-MCP; this fills the Streamlit gap.

## See it

A normal Streamlit app — the kind a human opens in a browser:

![A Streamlit signup form running in a browser](assets/demo-app.png)

The same app, driven by an agent over MCP — `inspect` to see the widgets, `call` to set values,
click a button, and read the rendered result. No browser, no pixels:

![The streamlit-mcp CLI introspecting and driving the app](assets/agent-view.png)

…and a human can watch the agent work **live** in their browser — no refresh, no browser automation
([how](live.md)):

![A browser updating live as an agent edits the app over MCP](assets/live-demo.gif)

## Why it's nice

- **No browser, no pixels.** Agents get a structured element tree and `session_state`, not
  screenshots.
- **Human ↔ agent parity.** Everything an agent can do over MCP, a human can do via the CLI —
  both call the same engine, and the guardrails apply identically.
- **Atomic, honest writes.** An invalid option or out-of-range value is rejected up front with a
  clear error; a failed `set_widget` never poisons a long-lived session or silently mutates state.
- **Enforced auth.** A `--bearer-token` is actually required on HTTP/SSE (401 otherwise).

## Next

- [Usage](usage.md) — MCP-client config, the tools, custom semantic tools, and the CLI.
- [Security](security.md) — the trust model, bearer auth, and current limitations.
- [Changelog](changelog.md).
