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

Widgets and outputs are returned in **document/render order** (the order the app renders them,
recursing through the sidebar and columns), so the layout an agent reads back matches the app.

Supported widgets: `text_input`, `number_input`, `text_area`, `slider`, `select_slider`,
`selectbox`, `multiselect`, `checkbox`, `toggle`, `radio`, `button`, `date_input`,
`time_input`, `color_picker`. Input widgets streamlit-mcp can't drive (`file_uploader`,
`camera_input`, `chat_input`, `pills`, `segmented_control`, `feedback`, …) are reported
explicitly on every surface (text `--layout`, `--json`, and MCP `get_layout`), never silently
dropped — wherever they're placed, including `st.sidebar.file_uploader(...)` and inside columns,
tabs and containers.

!!! note "Range widgets"
    A `slider`, `select_slider` or `date_input` built with a tuple `value=` is a **two-handle
    range** widget: its value is a 2-element list, and it advertises a matching array schema
    (`{"type": "array", "items": …, "minItems": 2, "maxItems": 2}`), so send both handles —
    `--set "Price=[20, 80]"`, `set_widget("Dates", ["2026-01-01", "2026-01-31"])`. Sending a single
    value to one (or a list to a single-handle widget) is rejected rather than silently dropped.

!!! note "Forms"
    An `st.form` is driven the way a human drives it: set the fields, then click the form's submit
    button (by its label, e.g. `--click "Submit"`). The submit button is reported as a regular
    clickable `button`; clicking it commits the form and runs its body.

!!! note "Atomic writes"
    Setting a `selectbox`/`radio`/`select_slider`/`multiselect` to an option that isn't offered
    (including every handle of a two-handle `select_slider` range), a
    `number_input`/`slider`/`date_input` outside its `min`/`max` (including either end of a
    two-date range), a value of the wrong **arity** (a single value for a two-handle range widget,
    or a list for a single-handle one), a **fractional** value for an integer `number_input`, or a
    `color_picker` to anything but a `#RGB`/`#RRGGBB` hex string, is rejected **before** any state
    changes — with a clear error listing the valid choices/range/format. An unparseable number,
    date, or time value is likewise rejected with a clear message. A failed `set_widget` leaves the
    session usable and never silently mutates state.

!!! note "Option types"
    A widget built from non-string options (`st.selectbox("Pick", [1, 2, 3])`) advertises its
    options in the string form Streamlit displays (`["1", "2", "3"]`) while reporting its value in
    the real type (`1`) — that's what Streamlit's own testing API exposes. Both forms are accepted:
    `set_widget("Pick", 2)` and `set_widget("Pick", "2")` both select the real option `2`.

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

A `--set` value is JSON-parsed for typed widgets (so `Age=5` is a number, `Tags=["a","b"]` a
list, `Agree=true` a boolean), but for a `text_input`/`text_area` it's stored **literally** — so
`Comment=true` is the string `"true"`, not the boolean — matching what the same value stores over
MCP.
