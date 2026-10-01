"""Charts of verified replay observations; no inference or strategy generation."""
from dataclasses import asdict
from datetime import date, timedelta
import json

import altair as alt

from apps.demo_console.i18n import tr
from apps.demo_console.components.market_benchmarks import BENCHMARK_COLORS, benchmark_label
from apps.demo_console.components.performance_lines import line_end_labels, line_label_x_range

STRATEGY_COLORS = {"RAW_A2": "#2357d9", "HGB_DIAG_5": "#d97706", "HGB_FACTOR_5": "#087f71"}


def _style(chart):
    # Heights below describe the complete frame, including axes and legends.
    # Streamlit replaces this height in fullscreen; fit-x would add those
    # decorations beyond the supplied screen height and hide the date axis.
    return (chart.properties(background="#11151e", autosize=alt.AutoSizeParams(type="fit", contains="padding"))
            .configure_view(stroke=None)
            .configure_axis(labelColor="#9aa6ba", titleColor="#c5cfdf", gridColor="#252e3d", gridWidth=.7,
                            domain=False, ticks=False, labelFontSize=13, titleFontSize=13,
                            labelFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif",
                            titleFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif",
                            titleFontWeight="normal", titlePadding=12)
            .configure_legend(title=None, labelFontSize=13, labelColor="#9aa6ba", labelFont="Segoe UI",
                              orient="top", symbolStrokeWidth=2.5))


def _legend(mapping):
    return json.dumps({key: tr(value) for key, value in mapping.items()}, ensure_ascii=False) + "[datum.label]"


def _date_axis(records, *, title=None):
    dates = [row["execution_date"] for row in records]
    count = min(len(dates), 6)
    ticks = ([dates[round(index * (len(dates) - 1) / (count - 1))] for index in range(count)]
             if count > 1 else dates)
    date_format = "%Y-%m" if len({day[:4] for day in dates}) > 1 else "%m-%d"
    domain = [dates[0], dates[-1]] if dates else None
    if len(dates) == 1:
        # A zero-length temporal domain makes Vega's point coordinate NaN.
        # Pad the display scale only; ticks and observations stay on the one
        # recorded date, without adding a dated return or an inferred record.
        day = date.fromisoformat(dates[0])
        domain = [(day - timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat()]
    return alt.X("execution_date:T", title=title,
                 scale=alt.Scale(domain=domain) if domain else alt.Undefined,
                 axis=alt.Axis(format=date_format, values=ticks, labelAngle=0,
                               labelOverlap=True, labelFlush=True))


def nav_comparison_chart(series, *, baseline=1.0, title="NAV", percent=False, colors=None, dashed=()):
    """Show already rebased observed paths on an exactly shared recorded calendar."""
    calendars = [tuple(row["execution_date"] for row in points) for points in series.values()]
    if not calendars or not calendars[0] or any(dates != calendars[0] for dates in calendars[1:]):
        raise ValueError("Compared paths require the same nonempty recorded dates")
    records = [{"execution_date": row["execution_date"], "value": row["value"], "series": label}
               for label, points in series.items() for row in points]
    values = [baseline, *(row["value"] for row in records)]
    low, high = min(values), max(values)
    padding = (high - low) * .06 or .04
    axis = _date_axis([{"execution_date": day} for day in calendars[0]], title=tr("Execution date"))
    axis.scale = alt.Scale(domain=axis.to_dict()["scale"]["domain"], nice=False)
    known_colors = {tr("Raw A2"): STRATEGY_COLORS["RAW_A2"],
                    tr("HGB + diagonal risk"): STRATEGY_COLORS["HGB_DIAG_5"],
                    tr("HGB + factor / shrinkage risk"): STRATEGY_COLORS["HGB_FACTOR_5"],
                    "HGB＋对角风险": STRATEGY_COLORS["HGB_DIAG_5"],
                    "HGB＋因子／收缩风险": STRATEGY_COLORS["HGB_FACTOR_5"]}
    known_colors.update(colors or {})
    palette = [known_colors.get(label, ["#2357d9", "#d97706", "#087f71", "#87929d"][i % 4])
               for i, label in enumerate(series)]
    legend_labels={label:label for label in series}
    for label in (tr("HGB + diagonal risk"),"HGB＋对角风险"):
        if label in legend_labels:legend_labels[label]=tr("HGB · Diagonal")
    for label in (tr("HGB + factor / shrinkage risk"),"HGB＋因子／收缩风险"):
        if label in legend_labels:legend_labels[label]=tr("HGB · Factor")
    # Keep legend rows fixed during Streamlit SVG resizing. A columns width
    # expression can leave Vega fit's top padding stale after a resize.
    lines = (alt.Chart(alt.Data(values=records)).mark_line(clip=True, strokeWidth=3,
                        point=alt.OverlayMarkDef(filled=True, size=65) if len(calendars[0]) == 1 else False)
            .encode(x=axis,
                    y=alt.Y("value:Q", title=tr(title),
                            scale=alt.Scale(domain=[low - padding, high + padding], zero=False, nice=False),
                            axis=alt.Axis(format=".1%" if percent else ".2f")),
                    color=alt.Color("series:N", title=None,
                                    scale=alt.Scale(domain=list(series), range=palette),
                                    legend=alt.Legend(orient="top", labelExpr=_legend(legend_labels),
                                                      labelLimit=150, columns=1, rowPadding=2, padding=4)),
                    strokeDash=alt.StrokeDash("series:N",
                        scale=alt.Scale(domain=list(series),range=[[7,4] if label in dashed else [1,0] for label in series])),
                    tooltip=[alt.Tooltip("execution_date:T", title=tr("Execution date"), format="%Y-%m-%d"),
                             alt.Tooltip("series:N", title=tr("Portfolio / control")),
                             alt.Tooltip("value:Q", title=tr(title), format=".2%" if percent else ".4f")]))
    wide = [{"execution_date": day, **{f"s{i}": points[index]["value"]
             for i, points in enumerate(series.values())}} for index, day in enumerate(calendars[0])]
    hover = alt.selection_point(name="comparison_observation", fields=["execution_date"],
                                nearest=True, on="pointerover", clear="pointerout", empty=False)
    observed = alt.Chart(alt.Data(values=wide))
    targets = observed.mark_point(opacity=0).encode(x=axis).add_params(hover)
    rule = observed.mark_rule(color="#89959b", strokeWidth=1).encode(
        x=axis, opacity=alt.condition(hover, alt.value(.7), alt.value(0)),
        tooltip=[alt.Tooltip("execution_date:T", title=tr("Execution date"), format="%Y-%m-%d"),
                 *[alt.Tooltip(f"s{i}:Q", title=label, format=".2%" if percent else ".4f")
                   for i, label in enumerate(series)]])
    return _style(alt.layer(lines, targets, rule).properties(height=340))


def wealth_chart(summary, *, show_reference=True, show_gross=False,
                 inspect_selection: str | None = None, inspected_date: str | None = None,
                 benchmarks=(), visible_series=None, rx_summary=None):
    """Keep recorded-date hover; optionally expose a raw ISO-date click selection.

    The optional inspection field exists only on chart copies, so native
    selection callbacks can validate it without timezone/epoch coercion. A
    validated inspected date keeps its rule when the native chart is remounted.
    """
    records = [asdict(point) for point in summary.wealth]
    dates = tuple(row["execution_date"] for row in records)
    if rx_summary is not None:
        if tuple(point.execution_date for point in rx_summary.wealth) != dates:
            raise ValueError("RX and A2 dates must match exactly")
        if rx_summary.initial_wealth != summary.initial_wealth:
            raise ValueError("RX and A2 initial wealth must match exactly")
        for record, point in zip(records, rx_summary.wealth):
            record["rx_net_wealth"] = point.net_wealth
    if inspect_selection is not None:
        for record in records:
            record["inspection_date"] = record["execution_date"]
    if not records:
        return _style(alt.Chart(alt.Data(values=[])).mark_line())
    labels = {"net_wealth": "Raw A2 · Net", "reference_net_wealth": "Frozen A control · Net",
              "gross_wealth": "Raw A2 · Gross"}
    fields, colors = ["net_wealth"], ["#2357d9"]
    if rx_summary is not None:
        fields.append("rx_net_wealth")
        colors.append("#dd8ca5")
        labels["rx_net_wealth"] = "A2 + RX · Net"
    if show_reference and summary.reference_available:
        fields.append("reference_net_wealth")
        colors.append("#d97706")
    if show_gross:
        fields.append("gross_wealth")
        colors.append("#7e9ee8")
    for benchmark in benchmarks:
        if benchmark.error or tuple(point.date for point in benchmark.points) != dates:
            raise ValueError("Market and strategy dates must match exactly")
        field = f"benchmark_{benchmark.symbol.lower()}"
        fields.append(field)
        colors.append(BENCHMARK_COLORS[benchmark.symbol])
        labels[field] = benchmark_label(benchmark.symbol)
        for record, point in zip(records, benchmark.points):
            record[field] = point.equity * summary.initial_wealth
    if visible_series is not None:
        known = {"A2": "net_wealth", "A": "reference_net_wealth", "RX": "rx_net_wealth",
                 "QQQ": "benchmark_qqq", "SPY": "benchmark_spy"}
        if (isinstance(visible_series, str) or "A2" not in visible_series
                or len(set(visible_series)) != len(visible_series)
                or any(symbol not in known for symbol in visible_series)):
            raise ValueError("A curve comparison must include A2 and known reference symbols")
        if "RX" in visible_series and rx_summary is None:
            raise ValueError("RX curve comparison requires matching RX observations")
        wanted = {known[symbol] for symbol in visible_series}
        chosen = [(field, color) for field, color in zip(fields, colors) if field in wanted]
        fields, colors = map(list, zip(*chosen))
    values = [1.0, *(row[field] for row in records for field in fields if row[field] is not None)]
    low, high = min(values), max(values)
    padding = (high - low) * .06 or .04
    legend = alt.Legend(labelExpr=_legend(labels))
    base = alt.Chart(alt.Data(values=records))
    date_axis = _date_axis(records)
    date_axis.scale = alt.Scale(domain=date_axis.to_dict()["scale"]["domain"], range=line_label_x_range())
    wealth_axis = alt.Y("wealth:Q", title=tr("Growth of 1 · Window start"),
                        scale=alt.Scale(domain=[max(0, low - padding), high + padding], zero=False))
    lines = (base.transform_fold(fields, as_=["series", "wealth"])
             .mark_line(clip=True,
                        point=alt.OverlayMarkDef(filled=True, size=65) if len(records) == 1 else False)
             .encode(x=date_axis,
                     y=wealth_axis,
                     strokeWidth=alt.condition(alt.datum.series == "net_wealth", alt.value(3.5), alt.value(3)),
                     color=alt.Color("series:N", scale=alt.Scale(domain=fields, range=colors),
                                     legend=legend),
                     strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=fields,
                                               range=[{"net_wealth": [1, 0], "reference_net_wealth": [9, 4],
                                                       "rx_net_wealth": [1, 0],
                                                       "benchmark_qqq": [4, 3], "benchmark_spy": [10, 3, 2, 3],
                                                       "gross_wealth": [2, 3]}[field]
                                                      for field in fields]), legend=legend)))
    hover = alt.selection_point(name="performance_hover", fields=["execution_date"],
                                encodings=[], nearest=True, on="pointerover", clear="pointerout", empty=False)
    tooltip = [alt.Tooltip("execution_date:T", title=tr("Execution date"), format="%Y-%m-%d")]
    tooltip += [alt.Tooltip(f"{field}:Q", title=tr(labels[field]), format=".4f") for field in fields]
    tooltip.append(alt.Tooltip("drawdown:Q", title=tr("Window drawdown"), format=".2%"))
    targets = base.mark_point(opacity=0).encode(x=date_axis).add_params(hover)
    active = hover
    if inspect_selection is not None:
        inspection = alt.selection_point(name=inspect_selection, fields=["inspection_date"],
                                         encodings=[], on="click", clear=False, empty=False)
        targets = targets.add_params(inspection)
        active = hover | inspection
        if inspected_date is not None and any(row["inspection_date"] == inspected_date for row in records):
            active = active | alt.FieldEqualPredicate(field="inspection_date", equal=inspected_date)
    rule = (base.mark_rule(color="#7f8b9f", strokeWidth=1)
            .encode(x=date_axis, opacity=alt.condition(active, alt.value(.8), alt.value(0)), tooltip=tooltip))
    baseline = (base.transform_aggregate(observations="count()")
                .mark_rule(color="#49566b", strokeDash=[3, 4], strokeWidth=1).encode(y=alt.datum(1)))
    backdrop, annotations = [], []
    drawdown = summary.max_drawdown
    recorded_dates = {row["execution_date"] for row in records}
    if drawdown.depth < 0 and drawdown.trough_date in recorded_dates:
        # Temporal fields may already be parsed by Vega. Compare timestamps so
        # filtering works for both raw ISO dates and parsed Date objects.
        date_value = "toNumber(toDate(datum.execution_date))"
        trough_value = f"toNumber(toDate({json.dumps(drawdown.trough_date)}))"
        trough_axis = wealth_axis.copy()
        trough_axis.shorthand = "net_wealth:Q"
        annotations.append(base.transform_filter(f"{date_value} === {trough_value}")
                           .mark_point(filled=False, color="#3f4857", size=95, strokeWidth=2, clip=True,
                                       ariaRoleDescription=tr("Deepest recorded drawdown"))
                           .encode(x=date_axis, y=trough_axis, tooltip=tooltip)
                           .properties(name="performance_drawdown_trough"))
        if (not drawdown.peak_is_initial and drawdown.peak_date in recorded_dates
                and drawdown.peak_date < drawdown.trough_date):
            peak_value = f"toNumber(toDate({json.dumps(drawdown.peak_date)}))"
            span_axis = date_axis.copy()
            span_axis.aggregate = "min"
            # The line's explicit temporal domain remains authoritative. Vega
            # otherwise normalizes an aggregate layer's duplicate domain
            # differently, producing a conflicting union on empty datasets.
            span_axis.scale = alt.Undefined
            # Both boundaries are aggregated from existing observations. The
            # initial, undated wealth baseline can never create a shaded span.
            backdrop.append(base.transform_filter(
                f"{date_value} === {peak_value} || {date_value} === {trough_value}")
                .mark_rect(color="#64748b", opacity=.07, clip=True)
                .encode(x=span_axis, x2=alt.X2("max(execution_date):T"))
                .properties(name="performance_drawdown_span"))
    end_names = {"net_wealth": "A2", "reference_net_wealth": "A", "rx_net_wealth": "A2 + RX",
                 "gross_wealth": tr("A2 gross"), "benchmark_qqq": "QQQ", "benchmark_spy": "SPY"}
    endpoints = {field: records[-1][field] for field in fields if records[-1][field] is not None}
    end_leaders, end_labels = line_end_labels(lines, date_field="execution_date", value_field="wealth",
        end_date=dates[-1], endpoints=endpoints, label_names=end_names)
    return _style(alt.layer(*backdrop, baseline, lines.properties(name="performance_paths"),
                           *annotations, targets, rule, end_leaders, end_labels)
                  .properties(height=336, background="#11151e"))


def rolling_chart(windows, *, show_reference=True):
    """Display only complete, fixed-length net-return windows supplied by stats."""
    records = [{**asdict(row), "execution_date": row.end_date} for row in windows]
    fields, colors = ["net_return"], ["#739bff"]
    labels = {"net_return": "Raw A2 · Net", "reference_net_return": "Frozen A control · Net"}
    if show_reference and records and all(row["reference_net_return"] is not None for row in records):
        fields.append("reference_net_return")
        colors.append("#7f8b9f")
    values = [0.0, *(row[field] for row in records for field in fields)]
    low, high = min(values), max(values)
    padding = (high - low) * .06 or .01
    base = alt.Chart(alt.Data(values=records))
    x = _date_axis(records, title=tr("Window end date"))
    legend = alt.Legend(labelExpr=_legend(labels))
    lines = (base.transform_fold(fields, as_=["series", "return"])
             .mark_line(strokeWidth=2.4, clip=True,
                        point=alt.OverlayMarkDef(filled=True, size=65) if len(records) == 1 else False)
             .encode(x=x, y=alt.Y("return:Q", title=tr("63-day net return"),
                                  scale=alt.Scale(domain=[low - padding, high + padding]),
                                  axis=alt.Axis(format=".3~p")),
                     color=alt.Color("series:N", scale=alt.Scale(domain=fields, range=colors), legend=legend),
                     strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=fields,
                                               range=[[1, 0], [5, 3]][:len(fields)]), legend=legend)))
    hover = alt.selection_point(name="rolling_hover", fields=["execution_date"], encodings=[],
                                nearest=True, on="pointerover", clear="pointerout", empty=False)
    targets = base.mark_point(opacity=0).encode(x=x).add_params(hover)
    rule = base.mark_rule(color="#7f8b9f").encode(
        x=x, opacity=alt.condition(hover, alt.value(.8), alt.value(0)),
        tooltip=[alt.Tooltip("start_date:N", title=tr("Window start date")),
                 alt.Tooltip("end_date:N", title=tr("Window end date")),
                 alt.Tooltip("observations:Q", title=tr("Recorded execution days")),
                 *(alt.Tooltip(f"{field}:Q", title=tr(labels[field]), format=".2%") for field in fields)])
    zero = base.transform_aggregate(observations="count()").mark_rule(
        color="#49566b", strokeDash=[3, 4]).encode(y=alt.datum(0))
    return _style(alt.layer(zero, lines, targets, rule).properties(
        height=336, background="#11151e", name="research_rolling_chart"))


def drawdown_chart(summary, *, compact=False):
    """A separate responsive view avoids compound-chart axis overflow."""
    records = [{"execution_date": point.execution_date, "drawdown": point.drawdown}
               for point in summary.wealth]
    minimum = min((row["drawdown"] for row in records), default=0)
    base = alt.Chart(alt.Data(values=records))
    drawdown_mark = (base.mark_point(color="#e3af70", filled=True, size=65) if len(records) == 1 else
                    base.mark_area(color="#e3af70", opacity=.18, line={"color": "#e3af70", "strokeWidth": 1.5}))
    lower = (drawdown_mark
             .encode(x=_date_axis(records, title=None if compact else tr("Execution date")),
                     y=alt.Y("drawdown:Q", title=None if compact else tr("Window drawdown"),
                             axis=alt.Axis(format=".3~p", **({"tickCount": 3} if compact else {})),
                             scale=alt.Scale(domain=[minimum * 1.05 if minimum < 0 else -.01, 0])),
                     tooltip=[alt.Tooltip("execution_date:T", title=tr("Execution date"), format="%Y-%m-%d"),
                              alt.Tooltip("drawdown:Q", title=tr("Window drawdown"), format=".2%")])
             .properties(height=110 if compact else 220, background="#11151e"))
    return _style(lower)


def period_records(periods):
    records = []
    for period in periods:
        row = asdict(period)
        row["coverage_label"] = tr("Window partial" if period.window_partial else
                                   "Archive boundary" if period.coverage_boundary else "Recorded period")
        records.append(row)
    return records


def monthly_chart(summary, *, selected_period=None):
    records = period_records(summary.months)
    for row in records:
        row["year"], row["month"] = row["period"].split("-")
        marker = " *" if row["window_partial"] or row["coverage_boundary"] else ""
        row["label"] = f'{row["net_return"]:+.1%}{marker}'
    extent = max((abs(row["net_return"]) for row in records), default=.01) or .01
    base = alt.Chart(alt.Data(values=records)).encode(
        x=alt.X("month:O", sort=[f"{month:02}" for month in range(1, 13)], title=None,
                scale=alt.Scale(domain=[f"{month:02}" for month in range(1, 13)]),
                axis=alt.Axis(labelAngle=0)),
        y=alt.Y("year:O", sort="descending", title=None),
        tooltip=[alt.Tooltip("period:N", title=tr("Period")),
                 alt.Tooltip("net_return:Q", title=tr("Net return"), format=".2%"),
                 alt.Tooltip("observations:Q", title=tr("Recorded execution days")),
                 alt.Tooltip("start_date:N", title=tr("First observation")),
                 alt.Tooltip("end_date:N", title=tr("Last observation")),
                 alt.Tooltip("coverage_label:N", title=tr("Coverage"))])
    selection = alt.selection_point(name="research_month", fields=["period"], encodings=[],
                                    on="click", clear="dblclick", toggle=False)
    cells = base.mark_rect(cornerRadius=5, strokeWidth=4, cursor="pointer").encode(
        stroke=alt.condition(alt.datum.period == selected_period,
                             alt.value("#b6c8ff"), alt.value("#11151e")),
        color=alt.Color("net_return:Q", title=tr("Net return"),
                        scale=alt.Scale(domain=[-extent, 0, extent], range=["#e3af70", "#1a2230", "#739bff"],
                                        interpolate="rgb"),
                        legend=None))
    # Choose against the actual interpolated fill, including asymmetric warm
    # and cool ramps. Black/white meet at sqrt(21): at least 4.58:1 everywhere.
    labels = base.mark_text(fontSize=13, fontWeight=500, font="Segoe UI", cursor="pointer").encode(
        text="label:N", color=alt.condition(
            "luminance(scale('color', datum.net_return)) > 0.179128784747792",
            alt.value("#000000"), alt.value("#ffffff")))
    return _style((cells + labels).add_params(selection).properties(
        height=max(56, len({row["year"] for row in records}) * 58) + 40))


def yearly_chart(summary, *, show_reference=True):
    records = []
    for row in period_records(summary.years):
        row["period_label"] = row["period"] + (" *" if row["window_partial"] or row["coverage_boundary"] else "")
        records.append({**row, "series": "Raw A2", "series_label": tr("Raw A2"), "return": row["net_return"]})
        if show_reference and summary.reference_available:
            records.append({**row, "series": "Frozen A control", "series_label": tr("Frozen A control"),
                            "return": row["reference_net_return"]})
    values = [0.0, *(row["return"] for row in records if row["return"] is not None)]
    low, high = min(values), max(values)
    chart = (alt.Chart(alt.Data(values=records)).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
             .encode(x=alt.X("period_label:N", title=None, axis=alt.Axis(labelAngle=0)),
                     xOffset=alt.XOffset("series:N"),
                     y=alt.Y("return:Q", title=tr("Recorded period return"), stack=None,
                             scale=alt.Scale(domain=[low * 1.05, high * 1.05 if high != low else 1]),
                             axis=alt.Axis(format=".3~p")),
                     color=alt.Color("series:N", scale=alt.Scale(domain=["Raw A2", "Frozen A control"],
                                                                  range=["#739bff", "#7f8b9f"]),
                                     legend=alt.Legend(labelExpr=_legend({"Raw A2": "Raw A2", "Frozen A control": "Frozen A control"}))),
                     tooltip=[alt.Tooltip("period:N", title=tr("Period")),
                              alt.Tooltip("series_label:N", title=tr("Series")),
                              alt.Tooltip("return:Q", title=tr("Net return"), format=".2%"),
                              alt.Tooltip("observations:Q", title=tr("Recorded execution days")),
                              alt.Tooltip("start_date:N", title=tr("First observation")),
                              alt.Tooltip("end_date:N", title=tr("Last observation")),
                              alt.Tooltip("coverage_label:N", title=tr("Coverage"))])
             .properties(height=310))
    return _style(chart)


def return_distribution(points):
    """Count raw observations in disjoint, zero-aligned bins with known axes."""
    from collections import Counter
    from math import floor, log10

    records = [{"net_return": point.net_return} for point in points]
    values = [row["net_return"] for row in records]
    low, high = (min(values), max(values)) if values else (0, 0)
    # Keep the previous approximately 28-bin resolution using a readable
    # 1/2/5 step. A constant sample gets a finite display interval, not fake
    # observations. The precision floor keeps indices within safe integers.
    span = high - low or abs(low)
    raw_step = max(span, max(abs(low), abs(high)) * 1e-12) / 28 or .0001
    magnitude = 10 ** floor(log10(raw_step))
    step = next(magnitude * multiple for multiple in (1, 2, 5, 10)
                if magnitude * multiple >= raw_step)
    # Python and Vega use the same floor rule. The sign guard also keeps tiny
    # negative values below zero when division would underflow to negative 0.
    indices = [min(-1, floor(value / step)) if value < 0 else max(0, floor(value / step))
               for value in values]
    counts = Counter(indices)
    highest_bin = max(counts.values(), default=0)
    x_domain = [min(indices, default=0) * step, (max(indices, default=0) + 1) * step]
    width = json.dumps(step)
    index_expression = (f"datum.net_return < 0 ? min(-1, floor(datum.net_return / {width}))"
                        f" : max(0, floor(datum.net_return / {width}))")
    chart = (alt.Chart(alt.Data(values=records))
             .transform_calculate(bin_index=index_expression,
                                  direction="datum.net_return < 0 ? 'Negative' : 'Positive'")
             .transform_calculate(bin_start=f"datum.bin_index * {width}",
                                  bin_end=f"(datum.bin_index + 1) * {width}")
             .transform_aggregate(observations="count()", groupby=["bin_index", "bin_start", "bin_end", "direction"])
             .transform_calculate(return_interval="format(datum.bin_start, '.2%') + ' – ' + format(datum.bin_end, '.2%')")
             .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
             .encode(x=alt.X("bin_start:Q", bin="binned", title=tr("Daily net return"),
                            scale=alt.Scale(domain=x_domain, zero=False, nice=False),
                            axis=alt.Axis(format=".3~p", labelAngle=0) if values else None),
                     x2=alt.X2("bin_end:Q"),
                     y=alt.Y("observations:Q", title=tr("Recorded execution days"), stack=None,
                             scale=alt.Scale(domain=[0, highest_bin], nice=False),
                             axis=alt.Axis(tickMinStep=1, format="d") if values else None),
                     color=alt.Color("direction:N", scale=alt.Scale(domain=["Negative", "Positive"],
                                                                      range=["#e3af70", "#739bff"]), legend=None),
                     tooltip=[alt.Tooltip("return_interval:N", title=tr("Daily net return")),
                              alt.Tooltip("observations:Q", title=tr("Recorded execution days"), format="d")])
             .properties(height=324))
    return _style(chart)
