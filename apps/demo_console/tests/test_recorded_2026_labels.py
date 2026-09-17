"""Recorded path focus and endpoint geometry over synthetic observations only."""
from dataclasses import asdict, replace
import math

import pytest

from apps.demo_console.components.chart_display import chart_for_display
from apps.demo_console.components.recorded_2026 import recorded_2026_chart
from apps.demo_console.i18n import language_scope
from apps.demo_console.tests.test_recorded_2026_view import _synthetic_calendar_window, _recorded_path_layer
from apps.demo_console.tests import test_vega_initialization as vega


def _case(kind):
    history = _synthetic_calendar_window()
    if kind in ("tied", "near"):
        close = 0 if kind == "tied" else .00001
        history = replace(history, points=tuple(replace(point,
            a_equity=100 + close, a2_equity=100, qqq_equity=100 + close * 2,
            a_drawdown=-close, a2_drawdown=0, qqq_drawdown=-close * 2)
            for point in history.points),
            spy_points=tuple(replace(point, equity=1 + close * 3 / 100, drawdown=-close * 3)
                             for point in history.spy_points))
    if kind == "single":
        history = replace(history, points=history.points[1:2], spy_points=history.spy_points[1:2])
    # Build chart references from existing synthetic point values, without
    # asking a file reader or recomputing the strategy history.
    from apps.demo_console.adapters.benchmarks_reader import BenchmarkSeries
    return history, (BenchmarkSeries("SPY", "SPY", points=history.spy_points),)


@pytest.mark.parametrize("focus", [None, ("A2", "A"), ("A2", "QQQ"), ("A2", "SPY")])
@pytest.mark.parametrize("drawdown", [False, True])
def test_focus_changes_only_visible_observations_not_the_history(focus, drawdown):
    history, markets = _case("normal")
    before = asdict(history)
    complete = recorded_2026_chart(history, benchmarks=markets, drawdown=drawdown).to_dict()
    spec = recorded_2026_chart(history, benchmarks=markets, drawdown=drawdown, visible_series=focus).to_dict()
    identifiers = {"SPY · S&P 500": "SPY"}
    expected = [row for row in complete["data"]["values"]
                if focus is None or identifiers.get(row["series"], row["series"]) in focus]
    assert spec["data"]["values"] == expected
    curve = _recorded_path_layer(spec)
    color = curve["encoding"]["color"]["scale"]
    palette = {"A2": "#2357d9", "A": "#d97706", "QQQ": "#087f71", "SPY · S&P 500": "#884ac7"}
    assert dict(zip(color["domain"], color["range"], strict=True)) == {
        key: value for key, value in palette.items() if focus is None or identifiers.get(key, key) in focus}
    assert asdict(history) == before


@pytest.mark.parametrize("focus", [(), ("A",), ("A2", "FAKE"), ("A2", "A2"), "A2"])
def test_invalid_focus_is_rejected(focus):
    history, markets = _case("normal")
    with pytest.raises(ValueError, match="Visible paths"):
        recorded_2026_chart(history, benchmarks=markets, visible_series=focus)


def _measure_labels(monkeypatch, specs, width):
    engine = vega._ENGINE.replace("const histogramBars = [];", "const endpointLabels = [], recordedPoints = []; const histogramBars = [];")
    engine = engine.replace("const group = item.mark?.marktype === \"group\";", r'''
      if (item.mark?.name === "recorded_end_labels_marks" && (item.opacity ?? 1) > 0) {
        endpointLabels.push({text: item.text, series: item.datum.series, value: item.datum.value,
          fontSize: item.fontSize, x1:item.bounds.x1 + offsetX, x2:item.bounds.x2 + offsetX,
          y1:item.bounds.y1 + offsetY, y2:item.bounds.y2 + offsetY});
      }
      if (["line", "symbol"].includes(item.mark?.marktype) && item.datum?.date !== undefined
          && item.datum?.value !== undefined) {
        recordedPoints.push({series:item.datum.series, value:item.datum.value, x:item.x, y:item.y});
      }
      const group = item.mark?.marktype === "group";
    ''')
    engine = engine.replace("return {histogramBars, executionBars", "return {endpointLabels, recordedPoints, histogramBars, executionBars")
    engine = engine.replace("return {endpointLabels, recordedPoints, histogramBars", r'''const renderedTexts = [...svg.matchAll(/<text\b[^>]*>([\s\S]*?)<\/text>/g)].map(match => match[1].replace(/<[^>]+>/g, ""));
    return {renderedTexts, endpointLabels, recordedPoints, histogramBars''')
    engine = engine.replace('"performance_drawdown_span_marks", "performance_drawdown_trough_marks"',
                            '"recorded_end_labels_marks"')
    monkeypatch.setattr(vega, "_ENGINE", engine)
    return vega._run_specs(specs, width=width, fullscreen={"width": 1250, "height": 662})["results"]


@pytest.mark.parametrize("width", [320, 420, 720])
def test_end_labels_do_not_overlap_or_leave_the_frame_on_insert_resize_clear(monkeypatch, width):
    specs = []
    for language in ("en", "zh", "ja"):
        for kind in ("normal", "tied", "near", "single"):
            history, markets = _case(kind)
            for drawdown in (False, True):
                with language_scope(language):
                    chart = recorded_2026_chart(history, benchmarks=markets, drawdown=drawdown)
                    specs.append(chart_for_display(chart, presentation=True).to_dict())
    for spec, result in zip(specs, _measure_labels(monkeypatch, specs, width), strict=True):
        assert not result["initialWarnings"] and not result["warnings"]
        assert result["initialAnnotations"] == result["clearedAnnotations"] == 0
        assert result["loadedRows"] == spec["data"]["values"] and result["cleared"] == 0
        last = max(row["date"] for row in spec["data"]["values"])
        endpoints = {row["series"]: row["value"] for row in spec["data"]["values"] if row["date"] == last}
        for frame in (result, *result["resized"]):
            labels, viewport = frame["endpointLabels"], frame["viewport"]
            assert len(labels) == 4
            assert {label["series"]: label["value"] for label in labels} == endpoints
            for label in labels:
                assert label["fontSize"] == 15
                assert all(math.isfinite(label[key]) for key in ("x1", "x2", "y1", "y2"))
                assert label["x1"] + viewport["originX"] >= 0
                assert label["x2"] + viewport["originX"] <= viewport["width"] + 1
                assert label["y1"] + viewport["originY"] >= 0
                assert label["y2"] + viewport["originY"] <= viewport["height"] + 1
                assert label["text"] in frame["renderedTexts"], "Do not truncate the endpoint's recorded number"
            ordered = sorted(labels, key=lambda label: label["y1"])
            assert all(left["y2"] + 3 <= right["y1"] for left, right in zip(ordered, ordered[1:]))
            assert frame["recordedPoints"]
            assert all(math.isfinite(point[key]) for point in frame["recordedPoints"] for key in ("x", "y"))
