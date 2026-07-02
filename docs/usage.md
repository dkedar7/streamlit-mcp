# Usage

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

Supported widgets: `text_input`, `number_input`, `text_area`, `slider`, `select_slider`,
`selectbox`, `multiselect`, `checkbox`, `toggle`, `radio`, `button`, `date_input`,
`time_input`, `color_picker`. Input widgets streamlit-mcp can't drive (`file_uploader`,
`camera_input`, `chat_input`, `pills`, `segmented_control`, `feedback`, …) are reported
explicitly on every surface (text `--layout`, `--json`, and MCP `get_layout`), never silently
dropped.

!!! note "Atomic writes"
    Setting a `selectbox`/`radio`/`multiselect` to an option that isn't offered, or a
    `number_input`/`slider`/`date_input` outside its `min`/`max`, is rejected **before** any
    state changes — with a clear error listing the valid choices/range. A failed `set_widget`
    leaves the session usable and never silently mutates state.

## Custom semantic tools

Beyond the per-widget tools, expose a higher-level named action by decorating a function with
`@mcp_tool` in your app file:

```python
import streamlit as st
from streamlit_mcp import mcp_tool

@mcp_tool
def reset_all():
    """Reset everything to defaults."""
    return {"ok": True}

st.text_input("Name")
```

`streamlit-mcp serve app.py` loads the app and exposes `reset_all` over MCP alongside the widget
tools. The decorated function is called directly (it isn't a widget), so keep it self-contained.

The CLI reaches it too (human ↔ agent parity): `inspect` lists registered tools, and `call --tool`
invokes one:

```bash
streamlit-mcp inspect app.py                 # ...lists reset_all under "tools:"
streamlit-mcp call app.py --tool reset_all   # invoke it; --arg key=value passes arguments
```

## Drive it from the terminal

The CLI calls the same engine an agent uses over MCP, so behavior matches exactly:

```bash
streamlit-mcp inspect app.py                 # print the widgets
streamlit-mcp inspect app.py --layout --json # full layout (widgets, outputs, state, unsupported)
streamlit-mcp call app.py --set "Name=agent" --click "Save" --read
streamlit-mcp call app.py --read-only --set "Name=x"   # guardrail: blocked, exit 1
streamlit-mcp call app.py --allow "Name" --set "Age=5"  # allow-list: 'Age' blocked, exit 1
streamlit-mcp --version
```
