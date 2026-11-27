"""st.plotly_chart is a chart output like a native chart (#229), read from Plotly's figure JSON.

plotly isn't a dependency, so most tests feed the figure JSON Plotly itself writes (taken from
plotly 7.2) straight to the extractor. The end-to-end tests run only where plotly is installed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

GROUPED = {  # go.Bar(name="revenue") + add_scatter(name="cost"), title "Monthly"
    "data": [{"name": "revenue", "x": ["Jan", "Feb", "Mar"], "y": [100, 140, 90], "type": "bar"},
             {"name": "cost", "x": ["Jan", "Feb", "Mar"], "y": [10, 12, 9], "type": "scatter"}],
    "layout": {"title": {"text": "Monthly"}},
}
PX_LINE = {  # px.line(df, x="month", y="rev"): unnamed trace, y as a typed array
    "data": [{"mode": "lines", "name": "", "orientation": "v", "x": ["Jan", "Feb"],
              "y": {"dtype": "f8", "bdata": "AAAAAAAA+D8AAAAAAAAEQA=="}, "type": "scatter"}],
    "layout": {"xaxis": {"title": {"text": "month"}}, "yaxis": {"title": {"text": "rev"}}},
}


def _out(fig):
    from streamlit.proto.PlotlyChart_pb2 import PlotlyChart

    from streamlit_mcp.runtime import AppTestRuntime
    el = SimpleNamespace(proto=PlotlyChart(spec=json.dumps(fig)))
    return AppTestRuntime._plotly_output(el)


def test_traces_read_as_series_of_x_value_records():
    o = _out(GROUPED)
    assert o.kind == "chart"
    assert o.text == 'plotly chart "Monthly": revenue, cost over Jan, Feb, Mar (6 points)'
    assert o.data[:2] == [{"x": "Jan", "series": "revenue", "value": 100},
                          {"x": "Feb", "series": "revenue", "value": 140}]
    assert o.data[3] == {"x": "Jan", "series": "cost", "value": 10}


def test_a_plotly_express_typed_array_is_decoded_and_named_after_its_column():
    """Plotly writes numpy/pandas data as base64 typed arrays; px leaves the trace unnamed and
    puts the column name in the axis title."""
    o = _out(PX_LINE)
    assert o.text == "plotly line chart: rev over Jan, Feb (2 points)"
    assert o.data == [{"x": "Jan", "series": "rev", "value": 1.5},
                      {"x": "Feb", "series": "rev", "value": 2.5}]


@pytest.mark.parametrize("dtype, raw, want", [
    ("i4", (7).to_bytes(4, "little") + (-2).to_bytes(4, "little", signed=True), [7, -2]),
    ("u1", bytes([1, 255]), [1, 255]),
])
def test_integer_typed_arrays_decode(dtype, raw, want):
    import base64
    o = _out({"data": [{"type": "bar", "name": "n",
                        "y": {"dtype": dtype, "bdata": base64.b64encode(raw).decode()}}]})
    assert [r["value"] for r in o.data] == want
    assert [r["x"] for r in o.data] == [0, 1]  # no x: the point's position, as Plotly draws it


def test_a_horizontal_bar_reads_its_categories_from_y():
    o = _out({"data": [{"type": "bar", "orientation": "h", "name": "h", "y": ["a", "b"],
                        "x": [3, 4]}]})
    assert o.text == "plotly bar chart: h over a, b (2 points)"
    assert o.data == [{"x": "a", "series": "h", "value": 3}, {"x": "b", "series": "h", "value": 4}]


def test_markers_only_is_a_scatter_and_unnamed_traces_are_numbered():
    o = _out({"data": [{"type": "scatter", "mode": "markers", "y": [1]},
                       {"type": "scatter", "mode": "markers", "y": [2]}]})
    assert o.text == "plotly scatter chart: trace 0, trace 1 over 0 (2 points)"


def test_nan_reads_as_null():
    o = _out({"data": [{"type": "scatter", "name": "s", "y": [1.0, float("nan")]}]})
    assert o.data[1]["value"] is None
    json.dumps(o.data, allow_nan=False)


def test_traces_that_arent_x_y_are_named_not_dropped():
    """A histogram's bars are computed from raw samples, and a pie or a map has no x/y; they're
    reported as present but not captured, never silently missing."""
    mixed = _out({"data": [{"type": "histogram", "x": [1, 2, 2]},
                           {"type": "scatter", "mode": "markers", "name": "pts", "x": [1, 2],
                            "y": [5, 6]}]})
    assert mixed.text == "plotly chart: pts over 1, 2 (2 points) (histogram data not captured)"
    pie = _out({"data": [{"type": "pie", "labels": ["a"], "values": [1]}]})
    assert pie.text == "plotly pie chart (pie data not captured)" and not pie.data


def test_an_unreadable_figure_is_still_reported():
    from streamlit.proto.PlotlyChart_pb2 import PlotlyChart

    from streamlit_mcp.runtime import AppTestRuntime
    o = AppTestRuntime._plotly_output(SimpleNamespace(proto=PlotlyChart(spec="not json")))
    assert o.kind == "chart" and o.text == "plotly chart (no data)"
    bad = _out({"data": [{"type": "bar", "name": "b", "y": {"dtype": "f8", "bdata": "!!"}}]})
    assert bad.text == "plotly bar chart (data not readable)"


def test_many_points_are_cut_along_x_keeping_every_trace():
    from streamlit_mcp.runtime import MAX_CHART_POINTS
    n = 150
    o = _out({"data": [{"type": "scatter", "name": s, "x": list(range(n)), "y": list(range(n))}
                       for s in ("a", "b")]})
    assert len(o.data) == MAX_CHART_POINTS and {r["series"] for r in o.data} == {"a", "b"}
    assert "(300 points; data has the first 100 of 150 x-values, for all 2 series)" in o.text


# --- end to end, where plotly is installed ---

PLOT_APP = (
    "import streamlit as st, pandas as pd\n"
    "import plotly.graph_objects as go, plotly.express as px\n"
    "st.title('Sales')\n"
    "st.line_chart(pd.DataFrame({'rev': [10, 20, 15]}))\n"
    "fig = go.Figure(go.Bar(x=['Jan', 'Feb', 'Mar'], y=[100, 140, 90], name='revenue'))\n"
    "fig.add_scatter(x=['Jan', 'Feb', 'Mar'], y=[10, 12, 9], name='cost')\n"
    "st.plotly_chart(fig)\n"
    "st.plotly_chart(px.line(pd.DataFrame({'month': ['Jan', 'Feb'], 'rev': [1.5, 2.5]}),\n"
    "                        x='month', y='rev'))\n"
    "st.success('rendered')\n"
)


@pytest.fixture
def plot_eng():
    pytest.importorskip("plotly")
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=PLOT_APP)
    rt.run()
    return Engine(rt)


def test_a_plotly_chart_is_an_output_in_document_order(plot_eng):
    """It was dropped from every read surface, though the script ran past it (#229)."""
    outputs = plot_eng.read_output()["outputs"]
    assert [o["kind"] for o in outputs] == ["title", "chart", "chart", "chart", "success"]
    assert outputs[2]["text"] == "plotly chart: revenue, cost over Jan, Feb, Mar (6 points)"
    assert outputs[3]["text"] == "plotly line chart: rev over Jan, Feb (2 points)"
    assert outputs[3]["data"][1] == {"x": "Feb", "series": "rev", "value": 2.5}


def test_cli_read_shows_the_plotly_chart(tmp_path, capsys):
    pytest.importorskip("plotly")
    from streamlit_mcp.cli import main
    app = tmp_path / "plot.py"
    app.write_text(PLOT_APP)
    assert main(["call", str(app), "--read"]) == 0
    assert "[chart] plotly chart: revenue, cost over Jan, Feb, Mar (6 points)" in (
        capsys.readouterr().out)


# --- #231: a filled scatter trace is an area chart, as st.area_chart reads ---

@pytest.mark.parametrize("trace, mark", [
    ({"mode": "lines", "stackgroup": "1"}, "area"),        # px.area: a stackgroup, no fill
    ({"fill": "tozeroy"}, "area"),                         # go.Scatter(fill="tozeroy")
    ({"mode": "lines", "fill": "tonexty"}, "area"),
    ({"mode": "lines", "stackgroup": "1", "fill": "none"}, "line"),  # stacked, drawn unfilled
    ({"mode": "lines", "fill": "toself"}, "line"),         # a closed shape, not an area chart
    ({"mode": "markers", "fill": "none"}, "scatter"),
])
def test_a_filled_scatter_trace_is_an_area_chart(trace, mark):
    """px.area and go.Scatter(fill=...) read "line chart", though st.area_chart reads
    "area chart" (#231). px.area sets no fill at all: its stackgroup is what fills it."""
    o = _out({"data": [{"type": "scatter", "name": "v", "x": [1, 2, 3], "y": [4, 5, 6], **trace}]})
    assert o.text == f"plotly {mark} chart: v over 1, 2, 3 (3 points)"


AREA_APP = (
    "import streamlit as st, pandas as pd, plotly.express as px, plotly.graph_objects as go\n"
    "df = pd.DataFrame({'t': [1, 2, 3], 'v': [4, 5, 6]})\n"
    "st.area_chart(df, x='t', y='v')\n"
    "st.plotly_chart(px.area(df, x='t', y='v'))\n"
    "f = go.Figure()\n"
    "f.add_scatter(x=[1, 2, 3], y=[4, 5, 6], fill='tozeroy', name='v')\n"
    "st.plotly_chart(f)\n"
)


def test_plotly_area_charts_read_like_the_native_one(tmp_path, capsys):
    pytest.importorskip("plotly")
    from streamlit_mcp.cli import main
    app = tmp_path / "area.py"
    app.write_text(AREA_APP)
    assert main(["call", str(app), "--read"]) == 0
    charts = [ln.strip() for ln in capsys.readouterr().out.splitlines() if "[chart]" in ln]
    assert charts == ["[chart] area chart: v over 1, 2, 3 (3 points)",
                      "[chart] plotly area chart: v over 1, 2, 3 (3 points)",
                      "[chart] plotly area chart: v over 1, 2, 3 (3 points)"]


def test_a_plotly_chart_names_its_canonical_fields():
    assert _out(GROUPED).fields == {"x": "x", "series": "series", "value": "value"}
