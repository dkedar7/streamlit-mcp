"""Charts that carry their own data are a readable output (#207), not silently dropped."""

from __future__ import annotations

import asyncio
import json

DASHBOARD_APP = (
    "import streamlit as st, pandas as pd\n"
    "df = pd.DataFrame({'revenue': [10, 20, 15], 'cost': [5, 8, 7]}, index=['Jan', 'Feb', 'Mar'])\n"
    "st.title('Dashboard')\n"
    "st.metric('Total revenue', 45)\n"
    "st.line_chart(df)\n"
    "st.bar_chart(df)\n"
    "st.area_chart(df)\n"
    "st.scatter_chart(df)\n"
    "st.dataframe(df)\n"
)
NATIVE = {
    "x": "Jan", "series": "revenue", "value": 10,
}


def _engine(script):
    from streamlit_mcp.engine import Engine
    from streamlit_mcp.runtime import AppTestRuntime
    rt = AppTestRuntime(script=script)
    rt.run()
    return Engine(rt)


def _charts(eng):
    return [o for o in eng.read_output()["outputs"] if o["kind"] == "chart"]


def test_native_charts_are_outputs_in_document_order_with_their_records():
    outputs = _engine(DASHBOARD_APP).read_output()["outputs"]
    assert [o["kind"] for o in outputs] == [
        "title", "metric", "chart", "chart", "chart", "chart", "dataframe"]
    texts = [o["text"] for o in outputs if o["kind"] == "chart"]
    assert texts == [f"{m} chart: revenue, cost over Jan, Feb, Mar (6 points)"
                     for m in ("line", "bar", "area", "scatter")]
    line = outputs[2]
    assert line["data"] == [
        {"x": "Jan", "series": "revenue", "value": 10},
        {"x": "Feb", "series": "revenue", "value": 20},
        {"x": "Mar", "series": "revenue", "value": 15},
        {"x": "Jan", "series": "cost", "value": 5},
        {"x": "Feb", "series": "cost", "value": 8},
        {"x": "Mar", "series": "cost", "value": 7},
    ]
    json.dumps(outputs)  # every record is JSON-safe as returned


def test_other_outputs_keep_their_kind_text_shape():
    for o in _engine(DASHBOARD_APP).read_output()["outputs"]:
        if o["kind"] != "chart":
            assert set(o) == {"kind", "text"}


def test_explicit_columns_altair_and_vega_lite_keep_their_own_field_names():
    app = (
        "import streamlit as st, pandas as pd, altair as alt\n"
        "st.scatter_chart(pd.DataFrame({'a': [1, 2], 'b': [3, 4]}), x='a', y='b')\n"
        "st.altair_chart(alt.Chart(pd.DataFrame({'h': [1], 'w': [2]}), title='Size')"
        ".mark_bar().encode(x='h', y='w'))\n"
        "st.vega_lite_chart({'mark': 'line', 'data': {'values': [{'t': 1, 'v': 9}]},\n"
        "                    'encoding': {'x': {'field': 't'}, 'y': {'field': 'v'}}})\n"
    )
    charts = _charts(_engine(app))
    assert [(c["text"], c["data"]) for c in charts] == [
        ("scatter chart: a, b (2 points)", [{"a": 1, "b": 3}, {"a": 2, "b": 4}]),
        ('bar chart "Size": h, w (1 point)', [{"h": 1, "w": 2}]),
        ("line chart: t, v (1 point)", [{"t": 1, "v": 9}]),
    ]


def test_dates_are_iso_and_missing_values_null():
    app = (
        "import streamlit as st, pandas as pd\n"
        "st.line_chart(pd.DataFrame({'temp': [1.5, None]},\n"
        "              index=pd.to_datetime(['2026-01-01', '2026-01-02'])))\n"
    )
    (chart,) = _charts(_engine(app))
    # One series stays wide: the column keeps the app's name.
    assert [r["x"][:10] for r in chart["data"]] == ["2026-01-01", "2026-01-02"]
    assert [r["temp"] for r in chart["data"]] == [1.5, None]
    assert chart["text"].startswith("line chart: temp over 2026-01-01")


def test_a_long_series_is_capped_and_the_text_says_so():
    from streamlit_mcp.runtime import MAX_CHART_POINTS
    n = MAX_CHART_POINTS + 50
    app = (
        "import streamlit as st, pandas as pd\n"
        f"st.line_chart(pd.DataFrame({{'y': list(range({n}))}}))\n"
    )
    (chart,) = _charts(_engine(app))
    assert len(chart["data"]) == MAX_CHART_POINTS
    assert chart["data"][0] == {"x": 0, "y": 0}
    assert f"({n} points; the first {MAX_CHART_POINTS} are in data)" in chart["text"]
    assert "… (" in chart["text"]  # the x summary is abbreviated, not 250 values long


def test_a_chart_without_inline_data_is_still_reported():
    app = (
        "import streamlit as st\n"
        "with st.sidebar:\n"
        "    st.vega_lite_chart({'mark': 'bar', 'data': {'url': 'https://example.com/d.csv'},\n"
        "                        'encoding': {'x': {'field': 'a'}}})\n"
    )
    (chart,) = _charts(_engine(app))
    assert chart["text"] == "bar chart (no data)"
    assert chart["data"] == []


def test_cli_read_prints_the_charts(capsys, tmp_path):
    from streamlit_mcp.cli import main
    app = tmp_path / "dash.py"
    app.write_text(DASHBOARD_APP, encoding="utf-8")
    assert main(["call", str(app), "--read"]) == 0
    out = capsys.readouterr().out
    assert "[chart] line chart: revenue, cost over Jan, Feb, Mar (6 points)" in out
    assert main(["call", str(app), "--read", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [o["data"][0] for o in data["outputs"] if o["kind"] == "chart"] == [
        {"x": "Jan", "series": "revenue", "value": 10}] * 4


def test_mcp_read_output_and_get_layout_carry_the_chart_data(tmp_path):
    from fastmcp import Client

    from streamlit_mcp.server import build_server
    app = tmp_path / "dash.py"
    app.write_text(DASHBOARD_APP, encoding="utf-8")

    async def run():
        async with Client(build_server(str(app))) as c:
            for tool in ("read_output", "get_layout"):
                res = await c.call_tool(tool, {})
                charts = [o for o in res.data["outputs"] if o["kind"] == "chart"]
                assert len(charts) == 4, tool
                assert charts[0]["data"][0] == NATIVE

    asyncio.run(run())
