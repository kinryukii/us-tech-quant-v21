"""Historical line labels must sit outside real paths, including after resize."""
from dataclasses import asdict

import pytest

from apps.demo_console.components.chart_display import chart_for_display
from apps.demo_console.components.performance_charts import wealth_chart
from apps.demo_console.components.performance_lines import LINE_LABEL_GUTTER
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.i18n import language_scope
from apps.demo_console.tests.test_benchmark_view import _markets
from apps.demo_console.tests.test_performance_charts import _rolling_points, _views
from apps.demo_console.tests.test_recorded_2026_labels import _measure_labels


@pytest.mark.parametrize("width", [420, 720])
def test_historical_paths_reserve_space_for_complete_end_values(monkeypatch, width):
    summary = summarize_performance(_rolling_points(63))
    markets = _markets(tuple(point.execution_date for point in summary.wealth))
    original = asdict(summary)
    cases = []
    for language in ("en", "zh", "ja"):
        for focus, gross in ((None, False), (("A2", "SPY"), False), (None, True)):
            with language_scope(language):
                chart = wealth_chart(summary, benchmarks=markets.series, visible_series=focus, show_gross=gross)
                spec = chart_for_display(chart, presentation=True).to_dict()
            path = next(view for view in _views(spec) if view.get("name") == "performance_paths")
            # Nested Altair property assignment previously silently lost range.
            assert path["encoding"]["x"]["scale"]["range"] == [0, {"expr": f"max(48, width - {LINE_LABEL_GUTTER})"}]
            cases.append((spec, 2 if focus else 5 if gross else 4))
    results = _measure_labels(monkeypatch, [spec for spec, _ in cases], width)
    for (spec, count), result in zip(cases, results, strict=True):
        assert not result["warnings"] and not result["initialWarnings"]
        assert result["loadedRows"] == spec["data"]["values"] and result["cleared"] == 0
        assert result["initialAnnotations"] == result["clearedAnnotations"] == 0
        for frame in (result, *result["resized"]):
            labels = frame["endpointLabels"]
            paths = [point for point in frame["performanceMarks"] if point["measure"] == "wealth"]
            assert len(labels) == count and paths
            assert max(point["x"] for point in paths) + 4 <= min(label["x1"] for label in labels)
            ordered = sorted(labels, key=lambda label: label["y1"])
            assert all(left["y2"] + 3 <= right["y1"] for left, right in zip(ordered, ordered[1:]))
            viewport = frame["viewport"]
            for label in labels:
                assert label["text"] in frame["renderedTexts"]
                assert label["x2"] + viewport["originX"] <= viewport["width"] + 1
                assert label["y1"] + viewport["originY"] >= 0
                assert label["y2"] + viewport["originY"] <= viewport["height"] + 1
    assert asdict(summary) == original
