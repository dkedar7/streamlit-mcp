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

A chart that carries its own data (`st.line_chart`, `bar_chart`, `area_chart`, `scatter_chart`,
`altair_chart`, `vega_lite_chart`) is an output of kind `chart`. Its `text` is a one-line summary
(`line chart: revenue, cost over Jan, Feb, Mar (6 points)`) and its `data` holds the plotted
records, up to 200 of them (a chart of several series is cut along the x-axis, so every
series stays in `data`). A native chart of several series reads
`{"x": "Jan", "series": "revenue", "value": 10}`; a single series, or a chart given explicit
columns, keeps the app's column names. `--read` prints the summary; `--json` and MCP include
`data`. Pyplot, maps and images are not captured.

An `st.plotly_chart` is a `chart` output too, read from the figure itself (plotly isn't needed by
streamlit-mcp). Each scatter, line, area or bar trace is a series, and its records read
`{"x": "Jan", "series": "revenue", "value": 100}`. The series is the trace's name, or for a single
unnamed trace (as Plotly Express draws one) the y-axis title, which is the app's column name. A
horizontal bar's categories are its `x`. Other trace types, such as a histogram (whose bars Plotly
computes from raw samples), a pie or a map, aren't read; the text names them as not captured, so
the chart is never silently missing: `plotly pie chart (pie data not captured)`.

Supported widgets: `text_input`, `number_input`, `text_area`, `slider`, `select_slider`,
`selectbox`, `multiselect`, `checkbox`, `toggle`, `radio`, `button`, `date_input`,
`time_input`, `color_picker`, `pills`, `segmented_control`, `feedback`, `data_editor`. Input widgets
streamlit-mcp can't drive (`file_uploader`, `camera_input`, `audio_input`, `chat_input`, …) are reported explicitly on every surface (text `--layout`, `--json`, and MCP `get_layout`), never silently
dropped — wherever they're placed, including `st.sidebar.file_uploader(...)` and inside columns,
tabs and containers.

An `st.data_editor` is driven with edits in Streamlit's own protocol:

```bash
streamlit-mcp call app.py --set 'cart={"edit": {"0": {"qty": 5}}, "add": [{"qty": 9, "price": 3}], "delete": [1]}' --read
```

Row numbers are positions in the app's original data, and row `n + i` is the i-th added row.
Edits accumulate, and `null` resets the table. Adding or deleting rows needs
`num_rows="dynamic"` (advertised as `constraints.dynamic`), and an unknown column or row is
rejected without changing anything. So is a cell value that doesn't fit its column, as in a
browser's cell editor: integer, number, boolean and all-string columns are listed in
`constraints.column_types` (and in the schema), and `null` clears a cell. Other columns, such as
dates, are passed through unchecked. The app's `column_config` value rules are enforced too: a
`SelectboxColumn` cell must be one of its `options`, and a `NumberColumn` cell must be within its
`min_value`/`max_value`. They're listed in `constraints.column_rules` (and in the schema as
`enum`/`minimum`/`maximum`). A disabled column, set with `disabled=[...]` or
`column_config` `disabled=True`, is read-only as in a browser. It's listed in
`constraints.disabled_columns` and left out of the write schema; in an added row it stays empty.
A whole editor built with `disabled=True` rejects every edit, like any disabled widget, though
`null` (a reset) is allowed. Other `column_config` settings, such as `step` and `required`,
aren't checked. Its `value` is `{"rows": <the app's data>, "edits": ...}`, and that value is a
valid write too, like any widget's: sending it back replaces the edits with the ones it holds, so
a table read earlier can be restored. `rows` may be left out; if it's sent it must be unchanged,
since only `edits` change the table.
AppTest never holds the edited table, so read the result from what the app renders. Inside an
`st.form`, edits are held until the submit, like any other field.

!!! note "Range widgets"
    A `slider`, `select_slider` or `date_input` built with a tuple `value=` is a **two-handle
    range** widget: its value is a 2-element list, and it advertises a matching array schema
    (`{"type": "array", "items": …, "minItems": 2, "maxItems": 2}`), so send both handles —
    `--set "Price=[20, 80]"`, `set_widget("Dates", ["2026-01-01", "2026-01-31"])`. Sending a single
    value to one (or a list to a single-handle widget) is rejected rather than silently dropped.

!!! note "Forms"
    An `st.form` is driven the way a human drives it: set the fields, then click the form's submit
    button (by its label, e.g. `--click "Submit"`). The submit button is reported as a regular
    clickable `button`; clicking it commits the form and runs its body. As in a browser, a form
    field you set is held until Submit: the widget shows the new value, but `session_state` and the
    app's output don't change until the submit click sends every field in one rerun. Each field
    and submit button reports the `form` it belongs to (`null` outside a form), so with several
    forms, click the submit whose `form` matches the fields you set.

    A form built with `clear_on_submit=True` clears the way a browser clears it. The submit runs
    with the values you set, and then its fields read as their defaults. Like any unsubmitted form
    value, the cleared fields don't reach `session_state` until the next submit, so `session_state`
    keeps the submitted values until then. To confirm a submit, read the app's output.

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
    A widget built from non-string options (`st.selectbox("Pick", [1, 2, 3])`) reports its value in
    the real type (`1`) while `constraints.options` lists the string form Streamlit displays
    (`["1", "2", "3"]`) — that's what Streamlit's own testing API exposes. Both forms are accepted:
    `set_widget("Pick", 2)` and `set_widget("Pick", "2")` both select the real option `2`, and the
    advertised `schema` says so — its `enum` carries **both** (`[1, 2, 3, "1", "2", "3"]`), so the
    reported value is always a member of its own schema and any option can be set in either form.

    The value's type is the only evidence of the real option type available at runtime (Streamlit
    hands over options already stringified), so a widget with **nothing selected** — an untouched
    `st.multiselect("Nums", [1, 2, 3])` — advertises the string form alone. That form is always
    settable, so the round-trip still works.

!!! note "Selection widgets (`pills`, `segmented_control`) and `feedback`"
    A `pills`/`segmented_control` is single- or multi-select depending on its `selection_mode`,
    and Streamlit exposes no flag for which — the **value's shape** is the signal, as it is for a
    range widget. A single-select holds a bare option (or `null` before anything is chosen) and
    advertises the option itself; a multi-select holds a list (`[]` when empty) and advertises an
    array. Sending a bare option to a multi-select means "select just this one", as with
    `multiselect`; a multi-select is cleared with `[]`.

    Once a selection is made it **cannot be cleared with `null`** — Streamlit's testing API
    silently ignores that, so `set_widget(id, null)` is rejected rather than reported as a success
    that never happened. Select a different option, or send `[]` on a multi-select.

    An `st.feedback` rating is an **index into its scale** — `thumbs` is `0-1`, `faces` and
    `stars` are `0-4` — and it advertises those bounds. Out-of-range ratings are rejected up front
    because the testing API neither raises nor reverts them; it stores them.

!!! note "Placeholder (null) widgets"
    A widget built with `value=None` / `index=None` — a `text_input`/`text_area`/`number_input`/
    `date_input`/`time_input` empty-field placeholder, or a "please select…" `selectbox`/`radio` —
    starts with no value: it reports `value: null` and advertises a nullable schema (e.g.
    `{"type": ["string","null"]}`). Setting it to `null` (`set_widget(id, null)`) **returns it to
    that no-value state**, so the value round-trips and a "reset this field/filter" flow works.
    A *regular* widget of the same kind (with a real default) has no no-value state and rejects
    `null` — atomically, leaving its value intact. (Over the CLI, JSON-typed values go through
    `--set`'s JSON parse, so `null` reaches an option/number widget; a text field takes `--set`
    verbatim per #43, so send its `null` over MCP or clear it another way.)

!!! note "App exceptions"
    If the served app raises an uncaught exception, it's captured in the `exception` field and
    surfaced on every read surface — `--json`, MCP `read_output`/`get_layout`, **and** the text CLI
    (`call`/`inspect` print an `exception:` line). By default this is a reported field, not a
    failure (exit `0`, mirroring MCP's `isError=False`); pass `--strict` to `call`/`inspect` to
    **exit non-zero** when the app raised, for CI and scripts. (A guardrail or load error is a real
    failure and exits non-zero regardless.)

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

An `--arg` value is JSON, like a `--set` value, falling back to a plain string when it isn't valid
JSON. So `--arg n=5` passes the number `5`, exactly what an agent sends as `{"n": 5}`, and
`--arg 'n="5"'` passes the string. For a parameter with no type annotation, that JSON value is what
the function receives on both surfaces; annotate the parameter if the type matters.

## Drive it from the terminal

The CLI calls the same engine an agent uses over MCP, so behavior matches exactly:

```bash
streamlit-mcp inspect app.py                 # print the widgets
streamlit-mcp inspect app.py --layout --json # full layout (widgets, outputs, state, unsupported)
streamlit-mcp call app.py --set "Name=agent" --click "Save" --read
streamlit-mcp call app.py --read-only --set "Name=x"   # guardrail: blocked, exit 1
streamlit-mcp call app.py --allow "Name" --set "Age=5"  # allow-list: 'Age' blocked, exit 1
streamlit-mcp call app.py --redact access_token --state # that key is dropped from state
streamlit-mcp config app.py                  # MCP client config, app path made absolute
streamlit-mcp --version
```

`config` prints an `mcpServers` JSON block for Claude Desktop, Cursor and similar clients, or with
`--client claude-code` a `claude mcp add` command, or with `--client vscode` a `.vscode/mcp.json`
`servers` block (VS Code ignores `mcpServers`). It carries `--read-only`/`--allow`/`--redact`
into the server command. With `--transport http` (or `sse`) it prints the URL wiring instead,
including the `Authorization` header when you pass `--bearer-token`, and prints the `serve` command
to start the server on stderr.

`serve` prints its effective posture to stderr when it starts:

```
streamlit-mcp 0.12.0 (streamlit 1.67.0)  serving /abs/path/app.py
  transport:  http  http://127.0.0.1:8000/mcp   health: http://127.0.0.1:8000/health
  auth:       bearer token required
  guardrails: read-only; redacting: access_token
```

A `--set` value is JSON-parsed for typed widgets (so `Age=5` is a number, `Tags=["a","b"]` a
list, `Agree=true` a boolean), but for a `text_input`/`text_area` it's stored **literally** — so
`Comment=true` is the string `"true"`, not the boolean — matching what the same value stores over
MCP.
