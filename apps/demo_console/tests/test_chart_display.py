"""Presentation typography over the real render boundaries and synthetic data."""
from copy import deepcopy
import json
from unittest.mock import patch

import altair as alt
import pyarrow as pa
from streamlit.testing.v1 import AppTest

from apps.demo_console.components.chart_display import chart_for_display, render_chart
from apps.demo_console.components.performance_charts import wealth_chart
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.tests.test_performance_charts import _points


def test_display_typography_preserves_chart_configuration_data_and_native_return_value():
    chart = wealth_chart(summarize_performance(_points()), show_reference=True, show_gross=True)
    original = chart.to_dict(validate=True)
    for presentation, size in ((True, 15), (False, 13)):
        display = chart_for_display(chart, presentation=presentation).to_dict(validate=True)
        expected = deepcopy(original)
        expected["background"] = "#ffffff"
        for section in ("axis", "legend"):
            expected["config"][section].update(labelFontSize=size, titleFontSize=size,
                                                labelColor="#536278", titleColor="#314158")
        expected["config"]["axis"]["gridColor"] = "#e7ecf2"
        assert display == expected
        assert chart.to_dict(validate=True) == original
    # A callback and the native selection result must pass through unchanged.
    callback, selected = lambda: None, {"selection": {"synthetic": [{"ticker": "ABC"}]}}
    with patch("apps.demo_console.components.chart_display.st.session_state", {"presentation_mode": False}), \
            patch("apps.demo_console.components.chart_display.st.altair_chart", return_value=selected) as render:
        assert render_chart(chart, key="synthetic", on_select=callback, selection_mode=["synthetic"],
                            width="stretch", theme=None) is selected
    assert render.call_args.kwargs == {"key": "synthetic", "on_select": callback,
                                      "selection_mode": ["synthetic"], "width": "stretch", "theme": None}
    assert render.call_args.args[0].to_dict()["config"]["axis"]["labelFontSize"] == 13
    # The helper also accepts a chart that has no previous display config.
    basic = alt.Chart(alt.Data(values=[{"x": 1}])).mark_point().encode(x="x:Q")
    assert chart_for_display(basic, presentation=True).to_dict()["data"]["values"] == [{"x": 1}]


def _display_app():
    from dataclasses import replace
    from unittest.mock import patch
    import streamlit as st
    from apps.demo_console.components.execution_quality import render_execution_quality
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkHistory
    from apps.demo_console.components.performance_stats import summarize_performance
    from apps.demo_console.components.score_profile import render_score_profile
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.pages.history import render_history
    from apps.demo_console.pages.research import _performance, _consistency
    from apps.demo_console.tests.test_history_charts import snapshot
    from apps.demo_console.tests.test_performance_charts import _rolling_points

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    presentation = st.toggle("Presentation", value=True, key="presentation_mode")
    dates = ("2025-01-02", "2025-01-03", "2025-01-06")
    history = tuple(replace(snapshot(day, rank=index + 1, score=None if index == 1 else .001 * index,
                                     available=index != 1, entered=("ABC",), exited=()),
                            available_dates=dates) for index, day in enumerate(dates))
    st.session_state.setdefault("decision_date", dates[-1])
    st.session_state.setdefault("workspace", "History")
    st.session_state.setdefault("history_window", "All available")
    points = _rolling_points(64)
    calendar = tuple(point.execution_date for point in points)
    summary = summarize_performance(points, full_history_dates=calendar)
    with language_scope(language):
        render_score_profile(history[-1].ranking)
        # Use the actual History render path while forbidding any source read.
        with patch("apps.demo_console.adapters.decision_reader.load_history", return_value=history):
            render_history(history[-1], presentation=presentation)
        _performance(summary, True, True, points=points, full_history_dates=calendar, initial_nav=1,
                     markets=BenchmarkHistory(), presentation=presentation)
        _consistency(summary, points, True)
        render_execution_quality(points)


def _chart_payloads(app):
    results = []
    for chart in app.get("vega_lite_chart"):
        spec = json.loads(chart.proto.spec)
        payloads = [chart.proto.data.data, *(dataset.data.data for dataset in chart.proto.datasets)]
        records = [row for payload in payloads if payload
                   for row in pa.ipc.open_stream(payload).read_all().to_pylist()]
        results.append((spec, records))
    return results


def test_actual_chart_renderers_follow_mode_in_three_languages_without_changing_economic_records(benchmark_stub):
    app = AppTest.from_function(_display_app, default_timeout=30).run()
    economic_fields = ("rank", "ticker", "score", "rank_change", "decision_date", "execution_date",
                       "signed_count", "turnover", "held", "net_wealth", "gross_wealth", "drawdown",
                       "reference_net_wealth", "reference_gross_wealth", "net_return", "gross_return",
                       "reference_net_return", "reference_gross_return", "period", "observations",
                       "start_date", "end_date", "series", "return", "transaction_cost", "cash", "nav")
    original_economic = None
    for language in ("en", "zh", "ja"):
        app.selectbox(key="language").select(language).run()
        reference_payloads = None
        for presentation in (True, False, True):
            app.toggle(key="presentation_mode").set_value(presentation).run()
            assert not app.exception and not app.error
            payloads = _chart_payloads(app)
            # Score; four history views + matrix; wealth/drawdown/month/year/
            # month detail; distribution/rolling; execution turnover.
            assert len(payloads) == 14
            expected = 15 if presentation else 13
            for spec, _ in payloads:
                for section in ("axis", "legend"):
                    assert spec["config"][section]["labelFontSize"] == expected
                    assert spec["config"][section]["titleFontSize"] == expected
            records = [rows for _, rows in payloads]
            if reference_payloads is None:
                reference_payloads = records
            assert records == reference_payloads, "Mode changes must not alter any serialized record"
            economic = [[tuple(row.get(field) for field in economic_fields) for row in rows] for rows in records]
            if original_economic is None:
                original_economic = economic
            assert economic == original_economic, "Language must not alter economic coordinates or coverage gaps"
            assert app.session_state["decision_date"] == "2025-01-06"
            assert app.session_state["history_ticker"] == "ABC"
