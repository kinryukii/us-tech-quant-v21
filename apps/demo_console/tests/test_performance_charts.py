"""Synthetic display contracts for recorded performance; no artifact access."""
from dataclasses import asdict, replace
from datetime import date, timedelta
import unittest

from apps.demo_console.components.performance_charts import (
    drawdown_chart, monthly_chart, return_distribution, rolling_chart, wealth_chart, yearly_chart,
)
from apps.demo_console.components.performance_stats import rolling_returns, summarize_performance
from apps.demo_console.i18n import language_scope, tr
from apps.demo_console.tests.test_performance_stats import point


_CALENDAR = (
    "2023-12-27", "2023-12-29", "2024-01-02", "2024-01-31",
    "2024-02-01", "2024-02-29", "2024-12-31", "2025-01-02",
    "2025-01-31", "2025-02-03", "2025-02-28", "2025-12-31",
)


def _points():
    # The first loss is entirely a recorded cost; later observations are irregular.
    returns = (-.01, .02, -.03, .01, .04, -.02, .03, -.01, .02, -.04, .01, .02)
    return tuple(point(day, value, gross=0.0 if i == 0 else value + .001,
                       cost=.01 if i == 0 else .001, reference=.005)
                 for i, (day, value) in enumerate(zip(_CALENDAR, returns)))


def _rolling_points(count=126, *, reference=True):
    # Irregular recorded days make a mistaken calendar-day window detectable.
    start = date(2024, 1, 2)
    return tuple(point((start + timedelta(days=2 * index)).isoformat(),
                       -.01 if index == 0 else (index % 9 - 4) * .002,
                       gross=0 if index == 0 else (index % 9 - 4) * .002 + .001,
                       cost=.01 if index == 0 else .001,
                       reference=(index % 5 - 2) * .001 if reference else None)
                 for index in range(count))


def _drawdown_cases():
    samples = {
        "recorded-peak": (.10, -.10, -.05, .25),
        "unrecovered": (.10, -.10, -.05, .01),
        "initial-peak": (-.10, -.10, .01),
        "positive": (.01, .02), "flat": (0.0, 0.0),
        "single-positive": (.01,), "single-negative": (-.0005,),
    }
    start = date(2024, 1, 2)
    return {name: tuple(point((start + timedelta(days=index * 3)).isoformat(), value,
                              gross=value + .001, cost=.001, reference=.0002)
                        for index, value in enumerate(values)) for name, values in samples.items()}


def _views(spec):
    yield spec
    for kind in ("layer", "concat", "hconcat", "vconcat"):
        for child in spec.get(kind, []):
            yield from _views(child)


def _records(spec):
    data = spec["data"]
    return data["values"] if "values" in data else spec["datasets"][data["name"]]


def _mark(view):
    mark = view.get("mark", {})
    return {"type": mark} if isinstance(mark, str) else mark


def _has_visible_point(spec, value_field):
    for view in _views(spec):
        mark = _mark(view)
        if view.get("encoding", {}).get("y", {}).get("field") != value_field:
            continue
        if mark.get("opacity", 1) <= 0:
            continue
        point_mark = mark if mark.get("type") == "point" else mark.get("point")
        if point_mark is True:
            return True
        if isinstance(point_mark, dict):
            if point_mark.get("opacity", 1) > 0 and point_mark.get("size", 30) > 0:
                return True
    return False


def _folded_fields(spec):
    return {field for view in _views(spec) for transform in view.get("transform", [])
            for field in transform.get("fold", [])}


class PerformanceChartsTests(unittest.TestCase):
    def test_monthly_labels_contrast_with_actual_vega_interpolated_fills(self):
        import re
        from apps.demo_console.tests.test_vega_initialization import _run_specs

        # Synthetic monthly returns sample both complete color ramps, including
        # the formerly unreadable mid-tones. Inspect rendered Vega mark colors.
        rows = tuple(point(f"{1980 + index // 12}-{index % 12 + 1:02d}-01", (index - 200) / 500)
                     for index in range(401))
        summary = summarize_performance(rows)
        spec = monthly_chart(summary).to_dict()
        result = _run_specs([spec])["results"][0]
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["loadedRows"], spec["data"]["values"])
        cells = {item["period"]: item for item in result["monthlyCells"] if item["type"] == "rect"}
        labels = [item for item in result["monthlyCells"] if item["type"] == "text"]
        self.assertEqual(len(cells), len(rows))
        self.assertEqual(len(labels), len(rows))

        def luminance(color):
            channels = ([int(color[index:index + 2], 16) for index in (1, 3, 5)] if color.startswith("#")
                        else [int(value) for value in re.findall(r"\d+", color)])
            linear = [value / 255 / 12.92 if value / 255 <= .04045
                      else ((value / 255 + .055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722), strict=True))

        for label in labels:
            foreground, background = luminance(label["fill"]), luminance(cells[label["period"]]["fill"])
            ratio = (max(foreground, background) + .05) / (min(foreground, background) + .05)
            self.assertGreaterEqual(ratio, 4.5, (label, cells[label["period"]], ratio))

    def test_compact_drawdown_keeps_coordinates_units_and_dates_without_axis_titles(self):
        summary = summarize_performance(_points())
        normal = drawdown_chart(summary).to_dict()
        compact = drawdown_chart(summary, compact=True).to_dict()
        self.assertEqual(_records(compact), _records(normal))
        self.assertEqual(compact["height"], 110)
        self.assertEqual(normal["height"], 220)
        for axis in ("x", "y"):
            self.assertEqual(compact["encoding"][axis]["scale"], normal["encoding"][axis]["scale"])
            self.assertIsNone(compact["encoding"][axis]["title"])
        self.assertEqual(compact["encoding"]["y"]["axis"], {"format": ".3~p", "tickCount": 3})
        self.assertEqual(compact["encoding"]["tooltip"], normal["encoding"]["tooltip"])
        self.assertEqual(compact["autosize"], {"type": "fit", "contains": "padding"})

    def test_compact_drawdown_compiles_at_projection_size_and_restores_after_fullscreen(self):
        from streamlit.elements.vega_charts import _prepare_vega_lite_spec
        from apps.demo_console.components.chart_display import chart_for_display
        from apps.demo_console.tests.test_vega_initialization import _run_specs

        specs = []
        for language in ("en", "zh", "ja"):
            with language_scope(language):
                for rows in (_points()[:1], _points()):
                    chart = drawdown_chart(summarize_performance(rows), compact=True)
                    spec = _prepare_vega_lite_spec(chart_for_display(chart, presentation=True).to_dict(), True)
                    spec.setdefault("padding", {})["bottom"] = 20
                    specs.append(spec)
        results = _run_specs(specs, width=720, fullscreen={"width": 1250, "height": 662})["results"]
        for spec, result in zip(specs, results, strict=True):
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["loadedRows"], spec["data"]["values"])
            expanded, restored = result["resized"]
            self.assertEqual(restored["viewport"], result["viewport"])
            for frame, width, height in ((result, 720, 110), (expanded, 1250, 662), (restored, 720, 110)):
                viewport = frame["viewport"]
                self.assertEqual((viewport["width"], viewport["height"]), (width, height))
                self.assertGreater(viewport["plotHeight"], 45)
                self.assertEqual(frame["legendLabels"], [])
                for label in frame["typography"]:
                    self.assertEqual(label["role"], "axis-label")
                    self.assertEqual(label["fontSize"], 15)
                    self.assertGreaterEqual(label["x1"] + viewport["originX"], -2)
                    self.assertLessEqual(label["x2"] + viewport["originX"], width + 2)
                    self.assertGreaterEqual(label["y1"] + viewport["originY"], -2)
                    self.assertLessEqual(label["y2"] + viewport["originY"], height + 2)

    def test_optional_wealth_inspection_preserves_records_and_targets_one_unit(self):
        summary = summarize_performance(_points())
        before = asdict(summary)
        default = wealth_chart(summary).to_dict()
        inspected = wealth_chart(summary, inspect_selection="system_execution_pick").to_dict()
        self.assertEqual([parameter["name"] for parameter in default["params"]], ["performance_hover"])
        original = _records(default)
        records = _records(inspected)
        self.assertEqual([{key: value for key, value in row.items() if key != "inspection_date"}
                          for row in records], original)
        self.assertEqual([row["inspection_date"] for row in records],
                         [row["execution_date"] for row in original])
        parameters = {parameter["name"]: parameter for parameter in inspected["params"]}
        picker = parameters["system_execution_pick"]
        self.assertEqual(picker["select"], {"type": "point", "on": "click", "clear": False,
                                           "fields": ["inspection_date"], "encodings": []})
        self.assertEqual(picker["views"], parameters["performance_hover"]["views"])
        self.assertEqual(len(picker["views"]), 1)
        target = next(view for view in _views(inspected) if view.get("name") == picker["views"][0])
        self.assertEqual(_mark(target), {"type": "point", "opacity": 0})
        self.assertEqual(target["encoding"]["x"]["field"], "execution_date")
        self.assertEqual(target["encoding"]["x"]["type"], "temporal")
        rule = next(view for view in _views(inspected)
                    if _mark(view).get("type") == "rule" and "opacity" in view.get("encoding", {}))
        self.assertEqual(rule["encoding"]["opacity"]["condition"]["test"]["or"],
                         [{"param": "performance_hover", "empty": False},
                          {"param": "system_execution_pick", "empty": False}])
        self.assertEqual(asdict(summary), before)

    def test_optional_wealth_inspection_compiles_without_warnings_and_preserves_raw_dates(self):
        from apps.demo_console.tests.test_vega_initialization import _run_specs

        cases = (summarize_performance(_points()), summarize_performance(_points()[:1]))
        specs = [wealth_chart(summary, inspect_selection="system_execution_pick").to_dict()
                 for summary in cases]
        results = _run_specs(specs)["results"]
        for spec, result in zip(specs, results, strict=True):
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["loadedRows"], spec["data"]["values"])
            self.assertEqual(result["loaded"], len(spec["data"]["values"]))
            self.assertEqual(result["cleared"], 0)
            self.assertEqual([[field["field"] for field in projection]
                              for projection in result["projections"]],
                             [["execution_date"], ["inspection_date"]])

    def test_static_inspection_rule_accepts_only_current_recorded_dates_when_enabled(self):
        summary = summarize_performance(_points())
        date = summary.wealth[3].execution_date

        def predicate(spec):
            rule = next(view for view in _views(spec)
                        if _mark(view).get("type") == "rule" and "opacity" in view.get("encoding", {}))
            return rule["encoding"]["opacity"]["condition"]

        enabled = wealth_chart(summary, inspect_selection="system_execution_pick").to_dict()
        selected = wealth_chart(summary, inspect_selection="system_execution_pick", inspected_date=date).to_dict()
        self.assertEqual(_records(selected), _records(enabled))
        self.assertEqual(predicate(selected)["test"]["or"],
                         [predicate(enabled)["test"], {"field": "inspection_date", "equal": date}])
        for invalid in (None, "2026-01-01", date + "T00:00:00Z", "not-a-date"):
            with self.subTest(invalid=invalid):
                spec = wealth_chart(summary, inspect_selection="system_execution_pick", inspected_date=invalid).to_dict()
                self.assertEqual(predicate(spec), predicate(enabled))
                self.assertEqual(_records(spec), _records(enabled))
        default = wealth_chart(summary).to_dict()
        disabled = wealth_chart(summary, inspected_date=date).to_dict()
        self.assertEqual(predicate(disabled), predicate(default))
        self.assertEqual(_records(disabled), _records(default))

    def test_wealth_drawdown_annotations_reuse_records_and_never_date_the_initial_baseline(self):
        for name, rows in _drawdown_cases().items():
            summary = summarize_performance(rows)
            before = (asdict(summary), tuple(asdict(row) for row in rows))
            for language in ("en", "zh", "ja"):
                for show_reference, show_gross in ((True, True), (False, False)):
                    with self.subTest(name=name, language=language, show_reference=show_reference), language_scope(language):
                        spec = wealth_chart(summary, show_reference=show_reference, show_gross=show_gross).to_dict(validate=True)
                        self.assertEqual(_records(spec), [asdict(row) for row in summary.wealth])
                        self.assertTrue(all("data" not in view for view in _views(spec) if view is not spec))
                        named = {view.get("name"): view for view in _views(spec)}
                        trough = named.get("performance_drawdown_trough")
                        span = named.get("performance_drawdown_span")
                        self.assertEqual(trough is not None, summary.max_drawdown.depth < 0)
                        self.assertEqual(span is not None, summary.max_drawdown.depth < 0
                                         and not summary.max_drawdown.peak_is_initial)
                        if span:
                            self.assertIs(spec["layer"][0], span)
                            self.assertNotIn("y", span["encoding"])
                            self.assertNotIn("y2", span["encoding"])
                        if trough:
                            self.assertFalse(trough["mark"]["filled"])
                            self.assertEqual(trough["mark"]["ariaRoleDescription"], tr("Deepest recorded drawdown"))
                            self.assertEqual(trough["encoding"]["y"]["field"], "net_wealth")
                            line = next(view for view in _views(spec) if _mark(view).get("type") == "line")
                            self.assertEqual(trough["encoding"]["y"]["scale"], line["encoding"]["y"]["scale"])
                            self.assertLessEqual({"execution_date", "net_wealth", "drawdown"},
                                                 {field["field"] for field in trough["encoding"]["tooltip"]})
            self.assertEqual((asdict(summary), tuple(asdict(row) for row in rows)), before)

    def test_month_cells_select_only_original_periods_without_filtering_records(self):
        summary = summarize_performance(_points()[:10], full_history_dates=_CALENDAR)
        original = asdict(summary)
        baseline = _records(monthly_chart(summary).to_dict(validate=True))
        for language in ("en", "zh", "ja"):
            with language_scope(language):
                for selected in (summary.months[0].period, summary.months[-1].period):
                    spec = monthly_chart(summary, selected_period=selected).to_dict(validate=True)
                    self.assertEqual(spec["params"][0]["select"],
                                     {"type": "point", "fields": ["period"], "encodings": [],
                                      "on": "click", "clear": "dblclick", "toggle": False})
                    records = _records(spec)
                    self.assertEqual([{key: value for key, value in row.items() if key != "coverage_label"}
                                      for row in records],
                                     [{key: value for key, value in row.items() if key != "coverage_label"}
                                      for row in baseline])
                    self.assertFalse(any("filter" in transform for view in _views(spec)
                                         for transform in view.get("transform", [])))
                    self.assertTrue(all(_mark(view).get("cursor") == "pointer" for view in _views(spec)
                                        if _mark(view).get("type") in {"rect", "text"}))
        self.assertEqual(asdict(summary), original)

    def test_rolling_chart_uses_only_complete_recorded_windows_and_visible_singletons(self):
        all_rows = _rolling_points()
        calendar = tuple(row.execution_date for row in all_rows)
        for count in (63, 64, 126):
            selected = all_rows[:count]
            summary = summarize_performance(selected, full_history_dates=calendar)
            windows = rolling_returns(summary)
            with self.subTest(count=count):
                spec = rolling_chart(windows).to_dict(validate=True)
                records = _records(spec)
                self.assertEqual(spec["name"], "research_rolling_chart")
                self.assertEqual(len(records), count - 62)
                self.assertEqual(records, [{**asdict(row), "execution_date": row.end_date}
                                           for row in windows])
                self.assertEqual([row["execution_date"] for row in records],
                                 [row.execution_date for row in selected[62:]])
                self.assertEqual([row["start_date"] for row in records],
                                 [row.execution_date for row in selected[:count - 62]])
                self.assertTrue(all(row["observations"] == 63 for row in records))
                self.assertLessEqual(records[-1]["end_date"], selected[-1].execution_date)
                if count == 63:
                    self.assertTrue(_has_visible_point(spec, "return"),
                                    "One complete rolling window must not be an invisible one-point line.")
                for view in _views(spec):
                    x = view.get("encoding", {}).get("x", {})
                    if x.get("field") == "execution_date":
                        if len(windows) == 1:
                            # A surrounding display domain must not become a
                            # synthetic dated return or an extra tick.
                            self.assertLess(x["scale"]["domain"][0], windows[0].end_date)
                            self.assertGreater(x["scale"]["domain"][1], windows[0].end_date)
                        else:
                            self.assertEqual(x["scale"]["domain"],
                                             [windows[0].end_date, windows[-1].end_date])
                        self.assertLessEqual(set(x["axis"]["values"]),
                                             {row.end_date for row in windows})

    def test_rolling_languages_and_reference_controls_preserve_all_input_values(self):
        for reference_available in (True, False):
            rows = _rolling_points(64, reference=reference_available)
            summary = summarize_performance(rows)
            windows = rolling_returns(summary)
            before = (tuple(asdict(row) for row in rows), asdict(summary),
                      tuple(asdict(row) for row in windows))
            for language in ("en", "zh", "ja"):
                for show_reference in (False, True):
                    with self.subTest(language=language, reference_available=reference_available,
                                      show_reference=show_reference), language_scope(language):
                        spec = rolling_chart(windows, show_reference=show_reference).to_dict(validate=True)
                        expected_fields = {"net_return"}
                        if show_reference and reference_available:
                            expected_fields.add("reference_net_return")
                        self.assertEqual(_folded_fields(spec), expected_fields)
                        self.assertEqual(_records(spec),
                                         [{**asdict(row), "execution_date": row.end_date} for row in windows])
                        tooltips = {field["field"]: field for view in _views(spec)
                                    for field in view.get("encoding", {}).get("tooltip", [])}
                        self.assertEqual(set(tooltips),
                                         {"start_date", "end_date", "observations"} | expected_fields)
                        for field, label in (("start_date", "Window start date"),
                                             ("end_date", "Window end date"),
                                             ("observations", "Recorded execution days"),
                                             ("net_return", "Raw A2 · Net")):
                            self.assertEqual(tooltips[field]["title"], tr(label))
                        y_titles = {view["encoding"]["y"]["title"] for view in _views(spec)
                                    if view.get("encoding", {}).get("y", {}).get("field") == "return"}
                        self.assertEqual(y_titles, {tr("63-day net return")})
                        if language != "en":
                            self.assertNotEqual(tr("63-day net return"), "63-day net return")
            self.assertEqual((tuple(asdict(row) for row in rows), asdict(summary),
                              tuple(asdict(row) for row in windows)), before)

    def test_all_five_schemas_accept_one_two_and_many_observations_in_each_language(self):
        rows = _points()
        for count in (1, 2, 10):
            selected = rows[:count]
            summary = summarize_performance(selected, full_history_dates=_CALENDAR)
            for language in ("en", "zh", "ja"):
                with self.subTest(count=count, language=language), language_scope(language):
                    charts = (
                        wealth_chart(summary, show_reference=True, show_gross=True),
                        drawdown_chart(summary), monthly_chart(summary),
                        yearly_chart(summary), return_distribution(selected),
                    )
                    for chart in charts:
                        self.assertIn("$schema", chart.to_dict(validate=True))

    def test_single_observation_has_visible_marks_and_untimed_baseline_without_fake_returns(self):
        summary = summarize_performance(_points()[:1])
        wealth = wealth_chart(summary, show_gross=True).to_dict(validate=True)
        drawdown = drawdown_chart(summary).to_dict(validate=True)
        self.assertTrue(_has_visible_point(wealth, "wealth"))
        self.assertTrue(_has_visible_point(drawdown, "drawdown"))
        records = _records(wealth)
        self.assertEqual(records, [asdict(summary.wealth[0])])
        self.assertEqual(records[0]["execution_date"], _CALENDAR[0])
        self.assertAlmostEqual(records[0]["net_wealth"], .99)
        self.assertAlmostEqual(_records(drawdown)[0]["drawdown"], -.01)
        baselines = [view for view in _views(wealth)
                     if _mark(view).get("type") == "rule"
                     and view.get("encoding", {}).get("y", {}).get("datum") == 1]
        self.assertTrue(baselines, "The pre-return wealth of 1 needs a visible reference.")
        for baseline in baselines:
            self.assertNotIn("x", baseline["encoding"], "Baseline must not invent a dated observation.")
            self.assertNotIn("x2", baseline["encoding"])

    def test_drawdown_fits_both_dimensions_and_ticks_are_recorded_dates(self):
        for count in (1, 2, 10):
            summary = summarize_performance(_points()[:count])
            recorded_dates = [row.execution_date for row in summary.wealth]
            drawdown = drawdown_chart(summary).to_dict(validate=True)
            self.assertEqual(drawdown["autosize"], {"type": "fit", "contains": "padding"})
            self.assertIsInstance(drawdown["height"], (int, float))
            self.assertGreaterEqual(drawdown["height"], 64)
            self.assertFalse(any(kind in drawdown for kind in ("concat", "hconcat", "vconcat")))
            for chart in (wealth_chart(summary).to_dict(validate=True), drawdown):
                axes = [view["encoding"]["x"]["axis"] for view in _views(chart)
                        if view.get("encoding", {}).get("x", {}).get("field") == "execution_date"]
                self.assertTrue(axes)
                for axis in axes:
                    ticks = axis["values"]
                    self.assertTrue(ticks)
                    self.assertEqual(ticks, sorted(set(ticks)))
                    self.assertLessEqual(set(ticks), set(recorded_dates))
                    self.assertIn(recorded_dates[0], ticks)
                    self.assertIn(recorded_dates[-1], ticks)

    def test_partial_and_boundary_periods_are_visibly_marked_and_explain_actual_coverage(self):
        summary = summarize_performance(_points()[:10], full_history_dates=_CALENDAR)
        # This fixture has source boundaries, a window-cut month, and complete interiors.
        self.assertTrue(summary.months[0].coverage_boundary)
        self.assertTrue(summary.months[-1].window_partial)
        self.assertFalse(summary.months[-1].coverage_boundary)
        self.assertTrue(any(not p.window_partial and not p.coverage_boundary for p in summary.years))
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), language_scope(language):
                monthly = monthly_chart(summary).to_dict(validate=True)
                yearly = yearly_chart(summary).to_dict(validate=True)
                monthly_text = next(view["encoding"]["text"]["field"] for view in _views(monthly)
                                    if _mark(view).get("type") == "text")
                yearly_label = yearly["encoding"]["x"]["field"]
                for spec, periods, label_field in (
                    (monthly, summary.months, monthly_text),
                    (yearly, summary.years, yearly_label),
                ):
                    expected = {period.period: period for period in periods}
                    for row in _records(spec):
                        period = expected[row["period"]]
                        self.assertEqual("*" in row[label_field],
                                         period.window_partial or period.coverage_boundary)
                        self.assertEqual(row["start_date"], period.start_date)
                        self.assertEqual(row["end_date"], period.end_date)
                        self.assertEqual(row["observations"], period.observations)
                        self.assertEqual(row["net_return"], period.net_return)
                        coverage = ("Window partial" if period.window_partial else
                                    "Archive boundary" if period.coverage_boundary else "Recorded period")
                        self.assertEqual(row["coverage_label"], tr(coverage))
                    tooltips = [view["encoding"]["tooltip"] for view in _views(spec)
                                if "tooltip" in view.get("encoding", {})]
                    self.assertTrue(tooltips)
                    for tooltip in tooltips:
                        self.assertLessEqual({"start_date", "end_date", "observations", "coverage_label"},
                                             {field["field"] for field in tooltip})

    def test_language_and_display_toggles_preserve_summary_points_and_economic_values(self):
        original_rows = _points()[:10]
        for reference_available in (True, False):
            rows = original_rows if reference_available else tuple(
                replace(row, reference_nav=None, reference_net_return=None,
                        reference_gross_return=None, reference_transaction_cost=None)
                for row in original_rows)
            summary = summarize_performance(rows, full_history_dates=_CALENDAR)
            original_summary = asdict(summary)
            original_points = tuple(asdict(row) for row in rows)
            for language in ("en", "zh", "ja"):
                with language_scope(language):
                    distribution = return_distribution(rows).to_dict(validate=True)
                    self.assertEqual(_records(distribution),
                                     [{"net_return": row.net_return} for row in rows])
                    for show_reference in (False, True):
                        annual = yearly_chart(summary, show_reference=show_reference).to_dict(validate=True)
                        expected_series = {"Raw A2"}
                        if show_reference and reference_available:
                            expected_series.add("Frozen A control")
                        self.assertEqual({row["series"] for row in _records(annual)}, expected_series)
                        for row in _records(annual):
                            period = next(p for p in summary.years if p.period == row["period"])
                            value = (period.net_return if row["series"] == "Raw A2"
                                     else period.reference_net_return)
                            self.assertEqual(row["return"], value)
                            self.assertEqual(row["series_label"], tr(row["series"]))
                        for show_gross in (False, True):
                            with self.subTest(language=language, reference_available=reference_available,
                                              show_reference=show_reference, show_gross=show_gross):
                                spec = wealth_chart(summary, show_reference=show_reference,
                                                    show_gross=show_gross).to_dict(validate=True)
                                expected_fields = {"net_wealth"}
                                if show_reference and reference_available:
                                    expected_fields.add("reference_net_wealth")
                                if show_gross:
                                    expected_fields.add("gross_wealth")
                                self.assertEqual(_folded_fields(spec), expected_fields)
                                self.assertEqual(_records(spec), [asdict(p) for p in summary.wealth])
                                tooltip_fields = {field["field"] for view in _views(spec)
                                                  for field in view.get("encoding", {}).get("tooltip", [])}
                                self.assertEqual(tooltip_fields & {"net_wealth", "gross_wealth",
                                                                  "reference_net_wealth"}, expected_fields)
            self.assertEqual(asdict(summary), original_summary)
            self.assertEqual(tuple(asdict(row) for row in rows), original_points)


if __name__ == "__main__":
    unittest.main()
