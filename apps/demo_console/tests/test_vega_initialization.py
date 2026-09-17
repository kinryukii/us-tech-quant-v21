"""Run the installed frontend's Vega engines against synthetic chart lifecycles.

Streamlit embeds a named, initially empty dataset, then inserts Arrow records.
Compiling only the populated Altair specification does not cover that lifecycle.
No browser, network, result artifacts, or additional JS dependency is used here.
"""
from copy import deepcopy
import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import streamlit

from apps.demo_console.components.execution_quality import turnover_chart as execution_chart
from apps.demo_console.components.history_charts import portfolio_chart, security_chart
from apps.demo_console.components.holding_matrix import matrix_chart
from apps.demo_console.components.performance_charts import (
    drawdown_chart, monthly_chart, return_distribution, rolling_chart, wealth_chart, yearly_chart,
)
from apps.demo_console.components.performance_stats import rolling_returns, summarize_performance
from apps.demo_console.components.score_profile import score_chart
from apps.demo_console.i18n import language_scope
from apps.demo_console.models import HoldingRow
from apps.demo_console.tests.test_history_charts import snapshot
from apps.demo_console.tests.test_performance_charts import _points as performance_points, _rolling_points, _drawdown_cases
from apps.demo_console.tests.test_execution_quality import point as execution_point


_ENGINE = r"""
import fs from "node:fs";
import {pathToFileURL} from "node:url";
globalThis.window = {location: {pathname: "/", protocol: "https:", host: "localhost", search: "", hash: ""}};
globalThis.location = window.location;
globalThis.fetch = () => {throw Error("This synthetic chart test cannot access the network");};
try {
  const origin = pathToFileURL(input.bundle);
  let source = fs.readFileSync(input.bundle, "utf8");
  // Expose the engine bindings already used by this installed vega-embed bundle
  // in an in-memory module. Never modify the installed JavaScript file.
  const bindings = source.match(/var (\w+)=\w+,(\w+)=\w+,\w+=typeof window<`u`\?window:void 0/);
  if (!bindings) throw Error("Installed Vega bundle engine bindings changed; review the test adapter");
  source = source.replace(/from"(\.\/[^\"]+)"/g,
                          (_, ref) => "from" + JSON.stringify(new URL(ref, origin).href));
  source += `\nexport {${bindings[1]} as vega, ${bindings[2]} as vegaLite};`;
  const {vega, vegaLite} = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
  const results = [];
  for (const original of input.specs) {
    const spec = structuredClone(original);
    const rows = spec.data.values;
    spec.data = {name: "observations"};
    // width="stretch" supplies measured pixel widths before frontend compile;
    // leaving Altair's implicit band-step width would not model the real app.
    spec.width = input.width;
    for (const child of spec.vconcat ?? []) child.width = input.width;
    // Streamlit 1.63 ArrowVegaLiteChart fills absent point encodings even when
    // select.fields is provided. Explicit [] must survive this augmentation.
    for (const param of spec.params ?? []) {
      if (param.select?.type === "point" && !("encodings" in param.select)) {
        param.select.encodings = Object.keys(spec.encoding);
      }
    }
    const warnings = [];
    const logger = {level(){return this;}, warn(...args){warnings.push(args.join(" "));return this;},
      error(...args){warnings.push(args.join(" "));return this;}, info(){return this;}, debug(){return this;}};
    const compiled = vegaLite.compile(spec, {logger}).spec;
    const view = new vega.View(vega.parse(compiled), {renderer: "none", logger});
    const visibleAnnotationCount = () => {
      let count = 0;
      const visit = item => {
        if (["performance_drawdown_span_marks", "performance_drawdown_trough_marks"].includes(item.mark?.name)
            && (item.opacity ?? 1) > 0 && item.bounds
            && [item.bounds.x1, item.bounds.x2, item.bounds.y1, item.bounds.y2].every(Number.isFinite)
            && item.bounds.x2 > item.bounds.x1 && item.bounds.y2 > item.bounds.y1) count++;
        for (const child of item.items ?? []) visit(child);
      };
      visit(view.scenegraph().root);
      return count;
    };
    await view.runAsync();
    const initialWarnings = [...warnings];
    const initialAnnotations = visibleAnnotationCount();
    await view.insert("observations", rows).runAsync();
    // Streamlit runs an explicit layout pass after Arrow insertion, once the
    // real ordinal labels and legends are known (ArrowVegaLiteChart createView).
    await view.resize().runAsync();
    const loaded = view.data("observations").length;
    const loadedRows = view.data("observations").map(row => ({...row}));
    const measure = async () => {
    const histogramBars = [];
    const executionBars = [];
    const rollingMarks = [];
    const performanceMarks = [];
    const axisLabels = [];
    const legendLabels = [];
    const monthlyCells = [];
    const typography = [];
    const dataMarkBounds = [];
    const drawdownSpans = [], drawdownTroughs = [];
    const inspectMarks = (item, offsetX = 0, offsetY = 0) => {
      if (["rect", "text"].includes(item.mark?.marktype)
          && typeof item.datum?.month === "string" && typeof item.datum?.net_return === "number") {
        monthlyCells.push({type: item.mark.marktype, period: item.datum.period,
          net_return: item.datum.net_return, fill: item.fill, text: item.text});
      }
      if (item.mark?.name === "performance_drawdown_span_marks") {
        drawdownSpans.push({start: new Date(item.datum.min_execution_date).toISOString().slice(0, 10),
          end: new Date(item.datum.max_execution_date).toISOString().slice(0, 10),
          x: item.x, x2: item.x2, width: item.bounds.x2 - item.bounds.x1,
          height: item.bounds.y2 - item.bounds.y1, opacity: item.opacity});
      }
      if (item.mark?.name === "performance_drawdown_trough_marks") {
        drawdownTroughs.push({execution_date: new Date(item.datum.execution_date).toISOString().slice(0, 10),
          net_wealth: item.datum.net_wealth, drawdown: item.datum.drawdown,
          x: item.x, y: item.y, fill: item.fill ?? null, stroke: item.stroke,
          size: item.size, roleDescription: item.ariaRoleDescription});
      }
      // Inspect the rendered text items, not just the requested format string.
      // Labels suppressed by axis overlap do not count as visible tick labels.
      if (item.mark?.role === "axis-label" && item.mark?.marktype === "text"
          && (item.opacity ?? 1) > 0 && typeof item.text === "string") {
        axisLabels.push({text: item.text, value: item.datum?.value, x: item.x, y: item.y});
      }
      if (["axis-label", "axis-title", "legend-label", "legend-title"].includes(item.mark?.role)
          && item.mark?.marktype === "text" && (item.opacity ?? 1) > 0
          && typeof item.text === "string") {
        const record = {role: item.mark.role, text: item.text, fontSize: item.fontSize,
          x1: item.bounds.x1 + offsetX, x2: item.bounds.x2 + offsetX,
          y1: item.bounds.y1 + offsetY, y2: item.bounds.y2 + offsetY};
        typography.push(record);
        if (item.mark.role === "legend-label") legendLabels.push(record);
      }
      if (item.mark?.marktype === "rect" && item.datum?.bin_index !== undefined) {
        const {bin_index, bin_start, bin_end, observations, direction} = item.datum;
        histogramBars.push({bin_index, bin_start, bin_end, observations, direction,
          width: item.bounds.x2 - item.bounds.x1, height: item.bounds.y2 - item.bounds.y1});
      }
      if (item.mark?.marktype === "rect" && typeof item.datum?.turnover === "number") {
        executionBars.push({execution_date: item.datum.execution_date, turnover: item.datum.turnover,
          y: item.y, y2: item.y2, height: item.bounds.y2 - item.bounds.y1});
      }
      if (["rect", "symbol", "line", "area"].includes(item.mark?.marktype)
          && (item.opacity ?? 1) > 0 && item.bounds && item.datum
          && ["execution_date", "decision_date", "period", "bin_index", "ticker"].some(key => key in item.datum)) {
        dataMarkBounds.push({type: item.mark.marktype,
          x1: item.bounds.x1 + offsetX, x2: item.bounds.x2 + offsetX,
          y1: item.bounds.y1 + offsetY, y2: item.bounds.y2 + offsetY});
      }
      if (["line", "symbol"].includes(item.mark?.marktype) && item.datum?.end_date !== undefined
          && item.datum?.series !== undefined && typeof item.datum?.return === "number"
          && (item.opacity ?? 1) > 0) {
        const {start_date, end_date, observations, series, net_return, reference_net_return} = item.datum;
        rollingMarks.push({type: item.mark.marktype, start_date, end_date, observations, series,
          net_return, reference_net_return, value: item.datum.return,
          x: item.x, y: item.y, size: item.size});
      }
      if (["line", "symbol", "area"].includes(item.mark?.marktype)
          && item.mark?.name !== "performance_drawdown_trough_marks"
          && item.datum?.execution_date !== undefined && (item.opacity ?? 1) > 0
          && (typeof item.datum?.wealth === "number" || typeof item.datum?.drawdown === "number")) {
        const measure = typeof item.datum.wealth === "number" ? "wealth" : "drawdown";
        performanceMarks.push({type: item.mark.marktype, measure, series: item.datum.series,
          execution_date: new Date(item.datum.execution_date).toISOString().slice(0, 10),
          value: item.datum[measure], x: item.x, y: item.y, size: item.size});
      }
      const group = item.mark?.marktype === "group";
      for (const child of item.items ?? []) inspectMarks(child,
        offsetX + (group ? item.x ?? 0 : 0), offsetY + (group ? item.y ?? 0 : 0));
    };
    inspectMarks(view.scenegraph().root);
    const scaleDomains = Object.fromEntries((compiled.scales ?? []).map(scale =>
      [scale.name, view.scale(scale.name).domain()]));
    const svg = await view.toSVG();
    const origin = svg.match(/<g[^>]*\btransform="translate\(([^,]+),([^\)]+)\)"/);
    const viewport = {
      width: Number(svg.match(/<svg[^>]*\bwidth="([^"]+)"/)?.[1]),
      height: Number(svg.match(/<svg[^>]*\bheight="([^"]+)"/)?.[1]),
      originX: Number(origin?.[1]), originY: Number(origin?.[2]),
      plotWidth: view.signal("width"), plotHeight: view.signal("height"),
    };
    return {histogramBars, executionBars, rollingMarks, performanceMarks, axisLabels,
      legendLabels, typography, scaleDomains, viewport, dataMarkBounds, drawdownSpans, drawdownTroughs, monthlyCells};
    };
    const rendered = await measure(), resized = [];
    if (input.fullscreen) {
      for (const frame of [input.fullscreen, {width: input.width, height: original.height}]) {
        await view.width(frame.width).height(frame.height).resize().runAsync();
        resized.push({...await measure(), loadedRows: view.data("observations").map(row => ({...row}))});
      }
    }
    await view.remove("observations", () => true).runAsync();
    await view.resize().runAsync();
    const cleared = view.data("observations").length;
    const clearedAnnotations = visibleAnnotationCount();
    view.finalize();
    results.push({initialWarnings, warnings, loaded, loadedRows, cleared, initialAnnotations,
      clearedAnnotations, ...rendered, resized,
      stacks: compiled.data?.flatMap(item => item.transform ?? []).filter(item => item.type === "stack"),
      projections: (compiled.signals ?? []).filter(item => item.name.endsWith("_tuple_fields")).map(item => item.value)});
  }
  process.stdout.write(JSON.stringify({versions: [vegaLite.version, vega.version], results}));
} catch(error) { process.stderr.write(error.name + ": " + error.message); process.exitCode = 1; }
"""


def _run_specs(specs, *, width=640, fullscreen=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the installed Vega runtime check")
    directory = Path(streamlit.__file__).parent / "static" / "static" / "js"
    bundle = next((path for path in directory.glob("styled-components.*.js")
                   if "Cannot project a selection on encoding channel" in path.read_text(encoding="utf-8")), None)
    assert bundle is not None, "Installed frontend bundle changed; review the version-matched test adapter"
    payload = json.dumps({"bundle": str(bundle), "specs": specs, "width": width,
                          "fullscreen": fullscreen}, allow_nan=False).encode("utf-8")
    # A base64 data envelope also survives Windows Node launcher quoting. No
    # ticker, date or other field can become a JavaScript expression.
    encoded = base64.b64encode(payload).decode("ascii")
    program = f'const input = JSON.parse(Buffer.from("{encoded}", "base64").toString("utf8"));\n' + _ENGINE
    process = subprocess.run([node, "--input-type=module"], input=program,
                             text=True, encoding="utf-8", capture_output=True, timeout=30, check=False)
    assert process.returncode == 0, process.stderr[-1500:]
    return json.loads(process.stdout)


def _cases():
    mixed = (snapshot("2025-01-02", score=-.003, entered=("A", "B"), exited=("C",)),
             snapshot("2025-01-03", score=None, available=False),
             snapshot("2025-01-06", score=.02, entered=(), exited=(), turnover=0))
    unknown = (snapshot("2025-01-02", score=None, available=False),)
    return [
        score_chart((HoldingRow(1, "A", -.003), HoldingRow(2, "B", .02), HoldingRow(3, "ZERO", 0))),
        score_chart((HoldingRow(1, "ZERO", 0),)), score_chart(()),
        portfolio_chart(mixed), portfolio_chart(unknown), portfolio_chart(()),
        portfolio_chart(mixed, "turnover"), portfolio_chart(unknown, "turnover"),
        security_chart(mixed, "ABC", "score"), security_chart(mixed, "ABSENT", "score"),
        security_chart((), "ABC", "score"), security_chart(mixed, "ABSENT"),
        matrix_chart(mixed, ("ABC", "ABSENT"), "ABC"), matrix_chart((), ()),
    ]


def test_installed_vega_has_no_warnings_on_empty_insert_clear_or_missing_observations():
    specs = [chart.to_dict() for chart in _cases()]
    before = deepcopy(specs)
    results = _run_specs(specs)["results"]
    for spec, result in zip(specs, results, strict=True):
        assert result["warnings"] == [], (spec.get("params"), result)
        assert result["stacks"] == [], "Recorded bars must not acquire cumulative stack coordinates"
        assert result["loaded"] == len(spec["data"]["values"]) and result["cleared"] == 0
        for projection in result["projections"] or []:
            assert [field["field"] for field in projection] == ["ticker"]
    assert specs == before


def test_reproduction_detects_auto_stack_and_streamlit_fieldless_selection_projection():
    legacy = score_chart((HoldingRow(1, "SYNTH", .03),)).to_dict()
    del legacy["encoding"]["y"]["stack"]
    del legacy["encoding"]["y"]["scale"]["domain"]
    del legacy["params"][0]["select"]["encodings"]
    result = _run_specs([legacy])["results"][0]
    assert any("score_start" in warning for warning in result["warnings"])
    assert any("score_end" in warning for warning in result["warnings"])
    assert any('encoding channel "opacity"' in warning for warning in result["warnings"])
    assert any('encoding channel "tooltip"' in warning for warning in result["warnings"])
    assert result["stacks"]


def test_research_and_execution_specs_survive_empty_insert_clear_lifecycle():
    cases = []
    points = performance_points()
    for label, selected in (("single", points[:1]), ("many", points)):
        summary = summarize_performance(selected, full_history_dates=tuple(point.execution_date for point in points))
        cases.extend((f"{label}:{name}", chart.to_dict()) for name, chart in (
            ("wealth-all", wealth_chart(summary, show_reference=True, show_gross=True)),
            ("wealth-net", wealth_chart(summary, show_reference=False, show_gross=False)),
            ("drawdown", drawdown_chart(summary)), ("monthly", monthly_chart(summary)),
            ("annual", yearly_chart(summary)), ("distribution", return_distribution(selected)),
            ("execution", execution_chart(selected)),
        ))
    cases.extend((f"execution:{name}", execution_chart(selected).to_dict()) for name, selected in (
        ("zero", (execution_point("2025-01-02", turnover=0),)),
        ("missing", (execution_point("2025-01-02", turnover=None),)),
        ("empty", ()),
    ))
    results = _run_specs([spec for _, spec in cases])["results"]
    errors = [(name, result["warnings"]) for (name, _), result in zip(cases, results, strict=True)
              if result["warnings"]]
    assert errors == []
    for (name, spec), result in zip(cases, results, strict=True):
        assert result["loaded"] == len(spec["data"]["values"]) and result["cleared"] == 0, name


def test_rolling_windows_render_real_points_without_warnings_through_dataset_lifecycle():
    from math import isfinite

    cases = []
    for count in (63, 64, 126):
        for reference_mode in ("shown", "hidden", "missing"):
            rows = _rolling_points(count, reference=reference_mode != "missing")
            windows = rolling_returns(summarize_performance(rows))
            for language in ("en", "zh", "ja"):
                with language_scope(language):
                    spec = rolling_chart(windows, show_reference=reference_mode != "hidden").to_dict()
                cases.append(((count, reference_mode, language), spec))
    before = deepcopy(cases)
    results = _run_specs([spec for _, spec in cases])["results"]
    for (label, spec), result in zip(cases, results, strict=True):
        count, reference_mode, _ = label
        records = spec["data"]["values"]
        assert result["initialWarnings"] == [] and result["warnings"] == [], (label, result)
        assert result["loaded"] == count - 62 and result["cleared"] == 0, label
        assert result["loadedRows"] == records, "Vega must preserve the supplied observation fields"
        assert result["stacks"] == [], label
        for projection in result["projections"] or []:
            assert [field["field"] for field in projection] == ["execution_date"], label
        series = {"net_return", "reference_net_return"} if reference_mode == "shown" else {"net_return"}
        marks = result["rollingMarks"]
        assert {mark["series"] for mark in marks} == series, (label, marks)
        for field in series:
            line_points = [mark for mark in marks if mark["type"] == "line" and mark["series"] == field]
            assert len(line_points) == len(records), (label, line_points)
            for row, mark in zip(records, line_points, strict=True):
                for original_field in ("start_date", "end_date", "observations",
                                       "net_return", "reference_net_return"):
                    assert mark[original_field] == row[original_field], (label, mark)
                assert mark["value"] == row[field], (label, mark)
                assert all(isinstance(mark[axis], (int, float)) and isfinite(mark[axis])
                           for axis in ("x", "y")), (label, mark)
            if count == 63:
                points = [mark for mark in marks if mark["type"] == "symbol" and mark["series"] == field]
                assert len(points) == 1 and points[0]["size"] > 0, (label, points)
                assert points[0]["value"] == records[0][field], (label, points)
                assert all(isinstance(points[0][axis], (int, float)) and isfinite(points[0][axis])
                           for axis in ("x", "y")), (label, points)
    assert cases == before


def test_singleton_wealth_and_drawdown_have_finite_visible_recorded_points():
    from math import isfinite

    summary = summarize_performance(performance_points()[:1])
    cases = (
        ("wealth-all", wealth_chart(summary, show_reference=True, show_gross=True),
         {"net_wealth", "gross_wealth", "reference_net_wealth"}),
        ("wealth-net", wealth_chart(summary, show_reference=False), {"net_wealth"}),
        ("drawdown", drawdown_chart(summary), {"drawdown"}),
    )
    specs = [chart.to_dict() for _, chart, _ in cases]
    results = _run_specs(specs)["results"]
    for (name, _, fields), spec, result in zip(cases, specs, results, strict=True):
        assert result["warnings"] == [], (name, result)
        assert result["loadedRows"] == spec["data"]["values"], name
        assert result["loaded"] == 1 and result["cleared"] == 0, name
        points = [mark for mark in result["performanceMarks"] if mark["type"] == "symbol"]
        assert len(points) == len(fields), (name, points)
        for mark in points:
            field = mark["series"] if mark["measure"] == "wealth" else "drawdown"
            assert field in fields and mark["value"] == getattr(summary.wealth[0], field), (name, mark)
            assert mark["execution_date"] == summary.wealth[0].execution_date, (name, mark)
            assert mark["size"] > 0, (name, mark)
            assert all(isinstance(mark[axis], (int, float)) and isfinite(mark[axis])
                       for axis in ("x", "y")), (name, mark)


def test_wealth_drawdown_span_and_hollow_marker_use_only_real_dates_and_net_wealth():
    from dataclasses import asdict
    from math import isfinite
    from apps.demo_console.i18n import tr

    cases = []
    for name, rows in _drawdown_cases().items():
        summary = summarize_performance(rows)
        for language in ("en", "zh", "ja"):
            for all_series in (False, True):
                with language_scope(language):
                    spec = wealth_chart(summary, show_reference=all_series, show_gross=all_series).to_dict()
                    role = tr("Deepest recorded drawdown")
                cases.append(((name, language, all_series), summary, role, spec))
    plain_specs = [deepcopy(spec) for _, _, _, spec in cases[:2]]
    for spec in plain_specs:
        spec["layer"] = [layer for layer in spec["layer"] if layer.get("name") not in
                         {"performance_drawdown_span", "performance_drawdown_trough"}]
    results = _run_specs([*[spec for _, _, _, spec in cases], *plain_specs])["results"]
    for (label, summary, role, spec), result in zip(cases, results[:len(cases)], strict=True):
        assert result["warnings"] == [], (label, result["warnings"])
        assert result["loadedRows"] == [asdict(row) for row in summary.wealth], label
        assert result["loaded"] == len(summary.wealth) and result["cleared"] == 0, label
        assert result["initialAnnotations"] == 0 and result["clearedAnnotations"] == 0, label
        deepest = summary.max_drawdown
        troughs, spans = result["drawdownTroughs"], result["drawdownSpans"]
        assert len(troughs) == int(deepest.depth < 0), (label, troughs)
        assert len(spans) == int(deepest.depth < 0 and not deepest.peak_is_initial), (label, spans)
        if troughs:
            mark = troughs[0]
            actual = next(row for row in summary.wealth if row.execution_date == deepest.trough_date)
            assert (mark["execution_date"], mark["net_wealth"], mark["drawdown"]) == (
                actual.execution_date, actual.net_wealth, actual.drawdown), (label, mark)
            assert mark["fill"] in (None, "transparent") and mark["stroke"], (label, mark)
            assert mark["size"] > 0 and mark["roleDescription"] == role, (label, mark)
            assert isfinite(mark["x"]) and isfinite(mark["y"]), (label, mark)
        if spans:
            span = spans[0]
            assert (span["start"], span["end"]) == (deepest.peak_date, deepest.trough_date), (label, span)
            assert span["start"] < span["end"], (label, span)
            assert 0 < span["opacity"] <= .12, (label, span)
            assert isfinite(span["width"]) and span["width"] > 0, (label, span)
            assert isfinite(span["height"]) and span["height"] > 0, (label, span)
        # The annotation never replaces, restacks or shifts any plotted series.
        fields = {"net_wealth", "gross_wealth", "reference_net_wealth"} if label[2] else {"net_wealth"}
        for field in fields:
            marks = [mark for mark in result["performanceMarks"]
                     if mark["type"] == "line" and mark.get("series") == field]
            assert [(mark["execution_date"], mark["value"]) for mark in marks] == [
                (row.execution_date, getattr(row, field)) for row in summary.wealth], (label, field, marks)
    for decorated, plain in zip(results[:2], results[-2:], strict=True):
        assert plain["warnings"] == []
        assert decorated["performanceMarks"] == plain["performanceMarks"], "Original curve coordinates must not move"
        assert decorated["axisLabels"] == plain["axisLabels"], "Annotations must not change the chart axes"


def test_small_percentage_axes_render_distinct_nonzero_labels_without_changing_data_in_any_language():
    from dataclasses import asdict
    from apps.demo_console.tests.test_performance_stats import point, series

    # Values are deliberately much smaller than the old 1-percentage-point
    # formatting step. Every input here is synthetic and independent of files.
    loss = (point("2025-01-02", -.0005, gross=0, cost=.0005),)
    periods = (point("2024-01-02", -.0002, reference=.0003),
               point("2025-01-02", .0001, reference=-.0001))
    rolling = series([-.000001] * 63)
    distribution = series([-.00015, -.00005, 0, .00005, .00015])
    before = tuple(tuple(asdict(row) for row in rows) for rows in (loss, periods, rolling, distribution))
    cases = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            charts = (
                ("small-drawdown", drawdown_chart(summarize_performance(loss))),
                ("small-period-returns", yearly_chart(summarize_performance(periods))),
                ("small-rolling-returns", rolling_chart(rolling_returns(summarize_performance(rolling)))),
                ("small-daily-distribution", return_distribution(distribution)),
            )
            cases.extend(((name, language), chart.to_dict()) for name, chart in charts)
    specs = [spec for _, spec in cases]
    legacy = deepcopy(specs[0])
    legacy["encoding"]["y"]["axis"]["format"] = ".0%"
    results = _run_specs([*specs, legacy])["results"]
    economic_fields = ("execution_date", "start_date", "end_date", "period", "observations", "drawdown",
                       "net_return", "gross_return", "reference_net_return", "return", "series")
    economic_by_chart = {}

    def numeric_percentage(label):
        return float(label.replace("\N{MINUS SIGN}", "-").removesuffix("%")) / 100

    for ((name, language), spec), result in zip(cases, results[:-1], strict=True):
        label = (name, language)
        assert result["warnings"] == [], (label, result["warnings"])
        assert result["loadedRows"] == spec["data"]["values"], label
        assert result["loaded"] == len(spec["data"]["values"]) and result["cleared"] == 0, label
        ticks = [tick for tick in result["axisLabels"] if tick["text"].endswith("%")]
        assert len(ticks) >= 2, (label, result["axisLabels"])
        text_labels = [tick["text"] for tick in ticks]
        assert len(set(text_labels)) == len(text_labels), (label, text_labels)
        assert any(numeric_percentage(tick["text"]) != 0 for tick in ticks), (label, ticks)
        for tick in ticks:
            # Formatting must preserve a small tick's magnitude and sign; a
            # nonzero coordinate must not be labelled as either 0% or -0%.
            if tick["value"] != 0:
                displayed = numeric_percentage(tick["text"])
                assert displayed != 0 and displayed * tick["value"] > 0, (label, tick)
                assert displayed == pytest.approx(tick["value"], rel=.005, abs=1e-15), (label, tick)
        economic = [tuple(row.get(field) for field in economic_fields) for row in result["loadedRows"]]
        assert economic == economic_by_chart.setdefault(name, economic), label
    # Prove this scenegraph check detects the previous real failure, even when
    # Vega logs no warning and the underlying negative drawdown remains intact.
    legacy_ticks = [tick for tick in results[-1]["axisLabels"] if tick["text"].endswith("%")]
    assert any(tick["value"] != 0 for tick in legacy_ticks), legacy_ticks
    assert all(numeric_percentage(tick["text"]) == 0 for tick in legacy_ticks), legacy_ticks
    assert tuple(tuple(asdict(row) for row in rows) for rows in (loss, periods, rolling, distribution)) == before


def test_display_fonts_reach_real_axes_and_legends_without_changing_records_or_domains():
    from math import isfinite
    from streamlit.elements.vega_charts import _prepare_vega_lite_spec
    from apps.demo_console.components.chart_display import chart_for_display

    history = (snapshot("2024-12-31", entered=("ABC",), score=-.001),
               snapshot("2025-01-02", retained=("ABC",), score=.02),
               snapshot("2025-01-06", available=False, score=None))
    cases = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            charts = (
                ("score", score_chart((HoldingRow(1, "ABC", .012), HoldingRow(2, "DEF", -.001)))),
                ("history", portfolio_chart(history)),
                ("performance", wealth_chart(summarize_performance(performance_points()),
                                             show_reference=True, show_gross=True)),
                ("matrix", matrix_chart(history, ("ABC", "DEF"), "ABC")),
                ("execution", execution_chart((execution_point("2025-01-02", turnover=.001),))),
            )
            for name, chart in charts:
                original = chart.to_dict()
                for presentation in (False, True):
                    spec = chart_for_display(chart, presentation=presentation).to_dict()
                    without_surface = deepcopy(spec)
                    without_surface["config"] = deepcopy(original["config"])
                    without_surface["background"] = original["background"]
                    assert spec["background"] == "#ffffff"
                    assert without_surface == original, "The rendering boundary may only change the surface and typography"
                    assert chart.to_dict() == original, "The original Altair chart must stay immutable"
                    # Include the installed Python rendering boundary: it adds
                    # fit sizing to raw charts that leave autosize unspecified.
                    prepared = _prepare_vega_lite_spec(deepcopy(spec), use_container_width=True)
                    cases.append(((name, language, presentation), prepared))
    for width in (640, 1250):
        results = _run_specs([spec for _, spec in cases], width=width)["results"]
        normal = {}
        for ((name, language, presentation), spec), result in zip(cases, results, strict=True):
            label = (name, language, presentation, width)
            assert result["initialWarnings"] == [] and result["warnings"] == [], (label, result)
            assert result["loadedRows"] == spec["data"]["values"], label
            assert result["loaded"] == len(spec["data"]["values"]) and result["cleared"] == 0, label
            if not presentation:
                normal[name, language] = result
            else:
                previous = normal[name, language]
                assert result["loadedRows"] == previous["loadedRows"], label
                assert result["scaleDomains"] == previous["scaleDomains"], label
            text_marks = result["typography"]
            assert any(mark["role"] == "axis-label" for mark in text_marks), label
            assert all(mark["fontSize"] == (15 if presentation else 13) for mark in text_marks), (
                label, text_marks)
            if name in ("history", "performance", "matrix"):
                assert result["legendLabels"], label
            viewport = result["viewport"]
            assert viewport["width"] == width and viewport["height"] > 0, (label, viewport)
            for mark in text_marks:
                assert all(isfinite(mark[key]) for key in ("x1", "x2", "y1", "y2")), (label, mark)
                # Use the actual SVG viewport and translated scenegraph bounds,
                # permitting only the small font-metric rounding at the edges.
                assert -2 <= mark["x1"] + viewport["originX"], (label, mark, viewport)
                assert mark["x2"] + viewport["originX"] <= viewport["width"] + 2, (label, mark, viewport)
                assert -2 <= mark["y1"] + viewport["originY"], (label, mark, viewport)
                assert mark["y2"] + viewport["originY"] <= viewport["height"] + 2, (label, mark, viewport)


def test_recorded_market_comparison_has_finite_axes_during_empty_arrow_handoff():
    from dataclasses import asdict
    from apps.demo_console.components.chart_display import chart_for_display
    from apps.demo_console.components.recorded_2026 import recorded_2026_chart
    from apps.demo_console.tests.test_recorded_2026_view import _synthetic_recorded_window
    from apps.demo_console.tests.test_benchmark_view import _markets

    history = _synthetic_recorded_window()
    original = asdict(history)
    spy = _markets(tuple(point.date for point in history.points)).series[1]
    cases = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            for drawdown in (False, True):
                chart = recorded_2026_chart(history, drawdown=drawdown, benchmarks=(spy,))
                cases.append(chart_for_display(chart, presentation=True).to_dict())
    for spec, result in zip(cases, _run_specs(cases, width=600)["results"], strict=True):
        assert result["initialWarnings"] == [] and result["warnings"] == []
        assert result["loadedRows"] == spec["data"]["values"]
        assert result["loaded"] == 4 * len(history.points) and result["cleared"] == 0
        assert {row["series"] for row in result["loadedRows"]} == {"A2", "A", "QQQ", "SPY · S&P 500"}
    assert asdict(history) == original


def test_fullscreen_resize_fits_frame_preserves_short_plots_and_restores_original_frame():
    from math import isfinite
    from streamlit.elements.vega_charts import _prepare_vega_lite_spec
    from apps.demo_console.components.chart_display import chart_for_display

    points = performance_points()
    summary = summarize_performance(points)
    history = (snapshot("2024-12-31", entered=("ABC",)),
               snapshot("2025-01-02", available=False))
    cases = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            charts = (
                ("wealth-single", wealth_chart(summarize_performance(points[:1]), show_gross=True), 200),
                ("wealth", wealth_chart(summary, show_gross=True), 200),
                ("rolling-single", rolling_chart(rolling_returns(summarize_performance(_rolling_points(63)))), 200),
                ("drawdown", drawdown_chart(summary), 80),
                ("monthly-single", monthly_chart(summarize_performance(points[:1])), 50),
                ("monthly", monthly_chart(summary), 160),
                ("matrix-single", matrix_chart(history, ("ABC",)), 18),
                ("matrix-20", matrix_chart(history, tuple(f"S{index:02d}" for index in range(20))), 360),
                ("yearly", yearly_chart(summary), 200),
                ("distribution", return_distribution(points), 200),
                ("execution", execution_chart((execution_point("2025-01-02", turnover=.001),)), 150),
            )
            for name, chart, minimum_plot_height in charts:
                for presentation in (False, True):
                    spec = _prepare_vega_lite_spec(
                        chart_for_display(chart, presentation=presentation).to_dict(), True)
                    # ArrowVegaLiteChart also supplies this bottom padding when
                    # the application has not set it. Fullscreen then replaces
                    # width and height through the existing Vega View.resize.
                    spec.setdefault("padding", {})["bottom"] = 20
                    cases.append(((name, language, presentation), spec, minimum_plot_height))
    before = deepcopy(cases)
    fullscreen = {"width": 1250, "height": 662}
    full_width = {label[0] for label, _, _ in cases} - {"yearly", "distribution", "execution"}
    # The first four groups model the actual 1024px page's chart containers;
    # the final group also exercises restoring a larger presentation window.
    for width, names in ((414, {"distribution"}), (420, {"yearly"}), (431, {"execution"}),
                         (720, full_width), (1250, None)):
        selected = [case for case in cases if names is None or case[0][0] in names]
        results = _run_specs([spec for _, spec, _ in selected], width=width, fullscreen=fullscreen)["results"]
        for (label, spec, minimum_plot_height), result in zip(selected, results, strict=True):
            assert result["initialWarnings"] == [] and result["warnings"] == [], (label, width, result["warnings"])
            assert result["cleared"] == 0
            expanded, returned = result["resized"]
            for frame, expected_width, expected_height in (
                (result, width, spec["height"]), (expanded, fullscreen["width"], fullscreen["height"]),
                (returned, width, spec["height"]),
            ):
                viewport = frame["viewport"]
                assert viewport["width"] == expected_width and viewport["height"] == expected_height, (
                    label, width, viewport)
                assert frame["loadedRows"] == spec["data"]["values"], (label, width)
                assert frame["scaleDomains"] == result["scaleDomains"], (label, width)
                assert viewport["plotHeight"] >= minimum_plot_height, (label, width, viewport)
                marks = frame["dataMarkBounds"]
                assert marks and all(all(isfinite(mark[key]) for key in ("x1", "x2", "y1", "y2"))
                                     for mark in marks), (label, width, marks)
                assert any(mark["x2"] > mark["x1"] and mark["y2"] > mark["y1"] for mark in marks), (label, width)
                if label[0] in ("wealth-single", "rolling-single"):
                    assert any(mark["type"] == "symbol" and mark["x2"] > mark["x1"]
                               and mark["y2"] > mark["y1"] for mark in marks), (label, width)
            # Auto-layout can redistribute axis margins after resize. Restore
            # the requested outer frame and content, not incidental pixel offsets.
            assert [mark["type"] for mark in returned["dataMarkBounds"]] == [
                mark["type"] for mark in result["dataMarkBounds"]], (label, width)
            # Automatic numeric tick spacing can legitimately change with the
            # available plot area; units, legend identities and type size cannot.
            assert [(mark["role"], mark["text"], mark["fontSize"]) for mark in returned["typography"]
                    if mark["role"] != "axis-label"] == [
                (mark["role"], mark["text"], mark["fontSize"]) for mark in result["typography"]
                if mark["role"] != "axis-label"], (label, width)
            assert all(mark["fontSize"] == (15 if label[2] else 13)
                       for mark in returned["typography"]), (label, width)
    # Reproduce the original fullscreen failure with the former width-only fit.
    legacy = deepcopy(cases[0][1])
    legacy["autosize"] = {"type": "fit-x", "contains": "padding"}
    old = _run_specs([legacy], width=640, fullscreen=fullscreen)["results"][0]
    assert old["resized"][0]["viewport"]["height"] > fullscreen["height"]
    assert old["resized"][0]["loadedRows"] == legacy["data"]["values"]
    assert cases == before


def test_execution_axis_preserves_small_turnover_and_bar_height_in_all_languages():
    from dataclasses import asdict
    from math import isfinite

    samples = {
        "small": (execution_point("2025-01-02", turnover=.001),
                  execution_point("2025-01-03", turnover=.0004)),
        "tiny": (execution_point("2025-01-02", turnover=.00000001),),
        "zero": (execution_point("2025-01-02", turnover=0),),
        "empty": (),
    }
    before = {name: [asdict(row) for row in rows] for name, rows in samples.items()}
    cases = []
    for language in ("en", "zh", "ja"):
        with language_scope(language):
            cases.extend(((name, language), execution_chart(rows).to_dict())
                         for name, rows in samples.items())
    specs = [spec for _, spec in cases]
    legacy = deepcopy(specs[:2])
    for spec in legacy:
        spec["encoding"]["y"]["axis"]["format"] = ".0%"
    results = _run_specs([*specs, *legacy])["results"]

    for ((name, language), spec), result in zip(cases, results[:len(cases)], strict=True):
        label = (name, language)
        assert result["initialWarnings"] == [] and result["warnings"] == [], (label, result)
        assert result["loadedRows"] == spec["data"]["values"], label
        assert result["loaded"] == len(samples[name]) and result["cleared"] == 0, label
        assert [(bar["execution_date"], bar["turnover"]) for bar in result["executionBars"]] == [
            (row.execution_date, row.turnover) for row in samples[name]], label
        for bar in result["executionBars"]:
            assert all(isfinite(bar[field]) for field in ("y", "y2", "height")), (label, bar)
            assert (bar["height"] > 0) == (bar["turnover"] > 0), (label, bar)
        if name in ("small", "tiny"):
            ticks = [tick for tick in result["axisLabels"] if tick["text"].endswith("%")]
            nonzero = [tick for tick in ticks if tick["value"] > 0]
            assert nonzero, (label, ticks)
            for tick in nonzero:
                displayed = float(tick["text"].removesuffix("%")) / 100
                assert displayed > 0, (label, tick)
                assert displayed == pytest.approx(tick["value"], rel=.005), (label, tick)

    for current, previous in zip(results[:2], results[-2:], strict=True):
        # Changing axis text must neither round records nor change bar height.
        assert current["loadedRows"] == previous["loadedRows"]
        assert current["executionBars"] == previous["executionBars"]
        ticks = [tick for tick in previous["axisLabels"] if tick["text"].endswith("%")]
        assert any(tick["value"] > 0 for tick in ticks), ticks
        assert all(float(tick["text"].removesuffix("%")) == 0 for tick in ticks), ticks
    assert {name: [asdict(row) for row in rows] for name, rows in samples.items()} == before


def test_distribution_rendered_bins_count_every_raw_point_and_fit_the_true_peak():
    from math import isfinite, nextafter
    from types import SimpleNamespace

    samples = {
        "empty": [], "single": [.0378], "constant": [.0378] * 23,
        "negative": [-.20, -.03, -.03, -.001, -.00000001],
        "positive": [.00000001, .001, .03, .03, .20],
        "zero": [0.0] * 19,
        "cross-zero": [-.2, -.00001, -1e-12, -5e-324, -0.0, 0, 5e-324, 1e-12, .00001, .2],
        "decimal-boundaries": [nextafter(value, -float("inf")) for value in (-.01, -.002, .002, .01)]
                              + [-.01, -.002, .002, .01]
                              + [nextafter(value, float("inf")) for value in (-.01, -.002, .002, .01)],
        "spread": [index * .001 for index in range(-25, 26)] * 3,
    }
    specs = [return_distribution(tuple(SimpleNamespace(net_return=value) for value in values)).to_dict()
             for values in samples.values()]
    results = _run_specs(specs)["results"]
    for (name, values), spec, result in zip(samples.items(), specs, results, strict=True):
        assert spec["data"]["values"] == [{"net_return": value} for value in values], name
        assert result["loaded"] == len(values) and result["warnings"] == [], (name, result)
        assert result["stacks"] == [], name
        bars = result["histogramBars"]
        assert sum(bar["observations"] for bar in bars) == len(values), (name, bars)
        assert len({bar["bin_index"] for bar in bars}) == len(bars), "Each interval must have exactly one visible bar"
        for direction, expected in (("Negative", sum(value < 0 for value in values)),
                                    ("Positive", sum(value >= 0 for value in values))):
            selected = [bar for bar in bars if bar["direction"] == direction]
            assert sum(bar["observations"] for bar in selected) == expected, (name, direction, selected)
            assert all(bar["bin_end"] <= 0 if direction == "Negative" else bar["bin_start"] >= 0
                       for bar in selected), "A bin must never straddle zero"
        assert all(bar["width"] > 0 and bar["height"] > 0
                   and isfinite(bar["width"]) and isfinite(bar["height"]) for bar in bars), name
        highest_bin = max((bar["observations"] for bar in bars), default=0)
        assert spec["encoding"]["y"]["scale"]["domain"] == [0, highest_bin], name
        if name == "spread":
            assert highest_bin < len(values) / 5, "The y axis must not use total sample size as its ceiling"
