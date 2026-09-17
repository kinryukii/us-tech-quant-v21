"""Present one bounded, already exposed record with its original acceptance status."""
from pathlib import PureWindowsPath
from datetime import date, timedelta

import altair as alt
import streamlit as st

from apps.demo_console.adapters.recorded_2026_reader import read_recorded_2026
from apps.demo_console.adapters.calendar_2026_reader import (
    Calendar2026History, read_calendar_2026, calendar_market_window,
)
from apps.demo_console.adapters.benchmarks_reader import read_benchmarks
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.history_charts import _style
from apps.demo_console.components.replay import pause_replay
from apps.demo_console.components.performance_range import render_date_range, reset_date_range
from apps.demo_console.components.recorded_2026_window import slice_recorded_2026
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import option_labeler, tr
from apps.demo_console.components.market_benchmarks import (
    available_benchmarks, benchmark_label, render_benchmark_notes, render_curve_focus,
)

HISTORICAL = "Historical research"
RECORDED = "2026 recorded performance"
CALENDAR_REPLAY = "Year-start calendar replay"
JUNE_ARCHIVE = "Original June archive"


def is_recorded_2026(view):
    return view == "Research" and st.session_state.get("research_period") == RECORDED


def open_recorded_2026():
    st.session_state["workspace"] = "Research"
    st.session_state["research_period"] = RECORDED
    _change_period()


def _change_period():
    pause_replay()
    if st.session_state.get("research_period") == RECORDED:
        st.session_state["_demo_tour_active"] = False
        st.session_state.pop("_demo_tour_step", None)


def render_research_period():
    if st.session_state.get("research_period") not in (HISTORICAL, RECORDED):
        st.session_state["research_period"] = HISTORICAL
    st.segmented_control(tr("Performance period"), (HISTORICAL, RECORDED),
        key="research_period", required=True, format_func=option_labeler((HISTORICAL, RECORDED)),
        on_change=_change_period, persist_state="session", label_visibility="collapsed")


def recorded_2026_chart(history, *, drawdown=False, benchmarks=(), visible_series=None):
    from apps.demo_console.components.performance_lines import line_end_labels, line_label_x_range

    if visible_series is not None:
        if (isinstance(visible_series, str) or "A2" not in visible_series
                or len(set(visible_series)) != len(visible_series)
                or not set(visible_series) <= {"A2", "A", "QQQ", "SPY"}):
            raise ValueError("Visible paths must be unique known series including A2")
    field = "drawdown" if drawdown else "equity"
    rows = [{"date": point.date, "series": arm,
             "value": getattr(point, f"{arm.lower()}_{field}")}
            for point in history.points for arm in ("A2", "A", "QQQ")]
    if not rows:
        raise ValueError("A recorded chart requires verified observations")
    domain, colors, dashes = ["A2", "A", "QQQ"], ["#2357d9", "#d97706", "#087f71"], [[1, 0], [10, 4], [6, 4]]
    symbols = {"A2": "A2", "A": "A", "QQQ": "QQQ"}
    for benchmark in benchmarks:
        if (benchmark.symbol != "SPY" or benchmark.error
                or tuple(point.date for point in benchmark.points) != tuple(point.date for point in history.points)):
            raise ValueError("Only an exactly aligned SPY reference may supplement the original record")
        label = benchmark_label(benchmark.symbol)
        domain.append(label)
        colors.append("#884ac7")
        dashes.append([12, 4, 4, 4])
        symbols[label] = "SPY"
        rows.extend({"date": point.date, "series": label,
                     "value": point.drawdown if drawdown else point.equity * 100}
                    for point in benchmark.points)
    if visible_series is not None:
        keep = [index for index, label in enumerate(domain) if symbols[label] in visible_series]
        domain, colors, dashes = ([items[index] for index in keep] for items in (domain, colors, dashes))
        rows = [row for row in rows if symbols[row["series"]] in visible_series]
    title = tr("Drawdown from the recorded peak" if drawdown else "Recorded equity · baseline = 100")
    # Streamlit mounts the Vega view before delivering its Arrow dataset.
    # Verified finite domains avoid an empty-data extent during that handoff.
    values = [row["value"] for row in rows]
    low, high = min(values), max(values)
    padding = (high - low) * .05 or (.01 if drawdown else 1.0)
    value_domain = [low - padding, 0.0 if drawdown else high + padding]
    single_point = len(history.points) == 1
    date_domain = [history.points[0].date, history.points[-1].date]
    if single_point:
        day = date.fromisoformat(history.points[0].date)
        date_domain = [(day - timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat()]
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X("date:T", title=None, scale=alt.Scale(domain=date_domain, range=line_label_x_range()),
                axis=alt.Axis(format="%m/%d", tickCount=6)),
        y=alt.Y("value:Q", title=tr("Window drawdown" if drawdown else "Equity path"),
                scale=alt.Scale(zero=drawdown, domain=value_domain),
                axis=alt.Axis(format=".3~p" if drawdown else ".0f")),
        color=alt.Color("series:N", title=None, sort=domain, legend=None,
                        scale=alt.Scale(domain=domain, range=colors)),
        strokeDash=alt.StrokeDash("series:N", legend=None,
            scale=alt.Scale(domain=domain, range=dashes)),
        tooltip=[alt.Tooltip("date:T", title=tr("Date"), format="%Y-%m-%d"),
                 alt.Tooltip("series:N", title=tr("Portfolio / control")),
                 alt.Tooltip("value:Q", title=title, format=".2%" if drawdown else ".2f")],
    )
    lines = base.mark_line(point=single_point).encode(
        strokeWidth=alt.condition(alt.datum.series == "A2", alt.value(3.5), alt.value(3)))
    endpoints = {row["series"]: row["value"] for row in rows if row["date"] == history.points[-1].date}
    leaders, labels = line_end_labels(base, date_field="date", value_field="value",
        end_date=history.points[-1].date, endpoints=endpoints, label_names=symbols,
        number_format=".2%" if drawdown else ".2f")
    return _style(alt.layer(lines.properties(name="recorded_paths"), leaders, labels)
                  .properties(autosize=alt.AutoSizeParams(type="fit", contains="padding")), height=285)


def _metrics(history):
    series = {row.key: row for row in history.series}
    cards = (
        ("A2 period return", f"{series['A2'].total_return:+.2%}", tr("Recorded strategy path")),
        ("A control period return", f"{series['A'].total_return:+.2%}", tr("Original strategy control")),
        ("A2 − A return difference", f"{100 * (series['A2'].total_return - series['A'].total_return):+.2f} pp",
         tr("Observed difference · Not risk-adjusted alpha")),
        ("A2 maximum drawdown", f"{series['A2'].maximum_drawdown:.2%}", tr("Within this recorded window")),
    )
    st.html('<div class="uq-metrics uq-motion-enter">' + ''.join(
        '<div class="uq-metric"><div class="uq-metric-label">' + text(tr(label))
        + '</div><div class="uq-metric-value">' + text(value)
        + '</div><div class="uq-metric-note">' + text(note) + '</div></div>'
        for label, value, note in cards) + '</div>')


def _choose_preset(label):
    reset_date_range("recorded_2026_range")
    st.session_state["recorded_2026_preset"] = label


def _change_source():
    source = st.session_state.get("recorded_2026_source")
    previous = st.session_state.get("_recorded_2026_active_source", CALENDAR_REPLAY)
    # A radio sends its displayed label. A delayed response in the previous
    # language is not a new source, and must not discard an applied interval.
    if source not in (CALENDAR_REPLAY, JUNE_ARCHIVE):
        st.session_state["recorded_2026_source"] = previous
    elif source != previous:
        _choose_preset("Since Jan 1")
        st.session_state["_recorded_2026_active_source"] = source


def _record_source():
    with st.expander(tr("Choose the 2026 record"), expanded=False):
        source = st.radio(tr("Record source"), (CALENDAR_REPLAY, JUNE_ARCHIVE),
            key="recorded_2026_source", format_func=option_labeler((CALENDAR_REPLAY, JUNE_ARCHIVE)),
            on_change=_change_source, persist_state="session", horizontal=True)
        st.caption(tr("The calendar replay starts from cash in January. The original June run starts from cash in June. They are separate paths; their overlapping dates do not have identical starting holdings."))
    return source


def _calendar_range(history):
    end = history.end_date
    presets = {"Since Jan 1": ("2026-01-01", end)}
    for label, first, last in (("Q1", "2026-01-01", "2026-03-31"),
                               ("Q2", "2026-04-01", "2026-06-30"),
                               ("Q3", "2026-07-01", "2026-09-30"),
                               ("Q4", "2026-10-01", "2026-12-31")):
        if first <= end:
            presets[label] = (first, min(last, end))
    selected = st.session_state.get("recorded_2026_preset", "Since Jan 1")
    if selected not in presets:
        selected = "Since Jan 1"
    controls = st.columns([2, *([1] * len(presets))], gap="small")
    with controls[0]:
        custom = render_date_range("recorded_2026_range", "2026-01-01", end, *presets[selected])
    for column, label in zip(controls[1:], presets):
        with column:
            st.button(tr(label), key=f"recorded_2026_preset_{label}",
                type="primary" if custom is None and selected == label else "secondary",
                on_click=_choose_preset, args=(label,), width="stretch")
    return custom or presets[selected], custom is not None


def _source_details(history, *, presentation):
    st.caption(tr("This record uses the same frozen quarterly A/A2 baseline. It is independent of the pre-2026 case date and is not joined to the historical research curve."))
    if isinstance(history, Calendar2026History):
        st.caption(tr("The calendar replay uses the existing frozen model without training or tuning. Its source check recovered exact preregistration bytes from Git; this does not upgrade the historical research identity or establish independent validation."))
        st.code(f"{history.source_status}\nEVIDENCE_ROLE: DESCRIPTIVE_ONLY\n"
                f"LEDGER_ARITHMETIC: VERIFIED_ACCOUNTING_IDENTITIES\nRESEARCH_ACCEPTANCE: NOT_REASSESSED\n"
                f"MODEL_SHA256: {history.model_sha256}\nORIGINAL_JUNE_STATUS: {history.original_source_status}", language="text")
    else:
        st.caption(tr("The source run's failure is retained. Reading and matching these files does not change its acceptance status or repeat the original research audit."))
        st.code(f"{history.source_status}\nFINAL_CLASSIFICATION: {history.classification}\n"
                f"ANTI_BLOAT_STATUS: {history.anti_bloat_status}\n"
                f"ACCOUNTING_COMPLETE: {history.accounting_complete}", language="text")
    for path, digest in history.source_refs:
        st.caption(PureWindowsPath(path).name if presentation else path)
        if not presentation:
            st.code(digest, language="text")


def render_recorded_2026(*, presentation):
    source = st.session_state.get("recorded_2026_source", CALENDAR_REPLAY)
    if source not in (CALENDAR_REPLAY, JUNE_ARCHIVE):
        source = st.session_state.get("_recorded_2026_active_source", CALENDAR_REPLAY)
    # Echo the current localized label even when an old English browser value
    # equals the internal source key and therefore does not fire a callback.
    st.session_state["recorded_2026_source"] = source
    st.session_state["_recorded_2026_active_source"] = source
    history = read_calendar_2026() if source == CALENDAR_REPLAY else read_recorded_2026()
    calendar_replay = isinstance(history, Calendar2026History)
    if history.error or not history.points:
        st.error(tr(history.error or "2026 recorded performance is unavailable."))
        if not presentation and history.debug_error:
            st.code(history.debug_error, language="text")
        _record_source()
        return
    requested, custom = _calendar_range(history)
    window = slice_recorded_2026(history, *requested)
    st.html('<div class="uq-history-range"><span>' + text(tr("CUSTOM DATE RANGE" if custom else "2026 · CALENDAR WINDOW"))
        + '</span><strong>' + text(requested[0]) + ' → ' + text(requested[1])
        + '</strong><span>' + text(tr(source)) + '</span></div>')
    if not calendar_replay:
        st.caption(tr("Archive coverage: {start} → {end}. Selected calendar dates do not extend the recorded data.",
                      start=history.start_date, end=history.end_date))
    if requested[0] < history.start_date and not calendar_replay:
        st.info(tr("This archive contains no observations before {start}. Returns below cover the available observations only; they are not a return since January 1.", start=history.start_date))
    if calendar_replay:
        st.caption(tr("Frozen-model replay · Limited price coverage · Not live performance or independent validation"))
    else:
        st.warning(tr("Recorded results · The original run did not pass full acceptance. Its repository governance gate failed; the figures below retain that status."), icon=":material/info:")
    if window.error:
        st.info(tr(window.error))
        with st.expander(tr("2026 source & scope"), expanded=False):
            _source_details(history, presentation=presentation)
        _record_source()
        return
    st.caption(tr("Displayed observations: {start} → {end} · Return baseline: {baseline}",
                  start=window.start_date, end=window.end_date, baseline=window.baseline_date))
    if not calendar_replay:
        st.caption(tr("A: original strategy · A2: the same baseline with the frozen machine-learning ranker · {count} return observations", count=window.return_observations))
    _metrics(window)
    markets = (calendar_market_window(history, window) if calendar_replay else
               read_benchmarks(tuple(point.date for point in window.points),
                   baseline_date=None if window.baseline_is_archive_start else window.baseline_date))
    benchmarks = available_benchmarks(markets, ("SPY",))
    st.html(section_header(tr("Strategy, control and market context")))
    if st.session_state.get("recorded_2026_chart_mode") not in ("Equity path", "Drawdown path"):
        st.session_state["recorded_2026_chart_mode"] = "Equity path"
    path_mode, curve_focus = st.columns([1, 2], gap="small")
    with path_mode:
        chart_mode = st.segmented_control(tr("Recorded path"), ("Equity path", "Drawdown path"),
            required=True, key="recorded_2026_chart_mode", persist_state="session",
            format_func=option_labeler(("Equity path", "Drawdown path")), label_visibility="collapsed")
    with curve_focus:
        visible_series = render_curve_focus("recorded_2026_curve_focus",
            available=("A", "QQQ", *(row.symbol for row in benchmarks)))
    render_chart(recorded_2026_chart(window, drawdown=chart_mode == "Drawdown path", benchmarks=benchmarks,
                                     visible_series=visible_series),
                 width="stretch", theme=None, key="recorded_2026_path")
    st.caption(tr("Equity is indexed to 100 at the return baseline. When the range starts inside the archive, the preceding recorded date is the baseline and the first selected return is included. Drawdowns use this window's running peak. A/A2 include the source's 10 bps round-trip fees; ETFs have no transaction fees."))
    st.html(section_header(tr("Return alongside the risk taken"), tr("SAME WINDOW")))
    by_key = {row.key: row for row in window.series}
    comparison = [{"series": key, "return": by_key[key].total_return,
                   "drawdown": by_key[key].maximum_drawdown, "worst": by_key[key].worst_day,
                   "best": by_key[key].best_day}
                  for key in ("A2", "A", "QQQ")]
    comparison.extend({"series": benchmark_label(row.symbol), "return": row.total_return,
                       "drawdown": row.max_drawdown,
                       "worst": min(point.daily_return for point in (row.points[1:] if window.baseline_is_archive_start else row.points)) if window.return_observations else None,
                       "best": max(point.daily_return for point in (row.points[1:] if window.baseline_is_archive_start else row.points)) if window.return_observations else None}
                      for row in benchmarks)
    st.dataframe(comparison, hide_index=True, width="stretch",
        key="recorded_2026_comparison", column_config={
            "series": st.column_config.TextColumn(tr("Portfolio / control")),
            "return": st.column_config.NumberColumn(tr("Period return"), format="percent"),
            "drawdown": st.column_config.NumberColumn(tr("Maximum window drawdown"), format="percent"),
            "worst": st.column_config.NumberColumn(tr("Worst recorded day"), format="percent"),
            "best": st.column_config.NumberColumn(tr("Best recorded day"), format="percent"),
        })
    st.caption(tr("A is the original strategy control; A2 adds the frozen machine-learning ranker. This short, already exposed window is descriptive evidence, not proof of persistent skill or live performance."))
    render_benchmark_notes(markets, presentation=presentation, symbols=("SPY",))
    if calendar_replay:
        with st.expander(tr("Inspect data coverage and quarterly universes"), expanded=False):
            st.caption(tr("Descriptive replay · Frozen model, existing data coverage. Only stocks meeting the original price-history and feature requirements are eligible. This is not live performance or independent validation."))
            st.caption(tr("A: original strategy · A2: the same baseline with the frozen machine-learning ranker · {count} return observations", count=window.return_observations))
            st.caption(tr("The full candidate pools are retained. Missing source histories are reported as missing, not treated as IPOs or proof that a stock could not trade. The replay uses the original eligibility rules; incomplete coverage limits its conclusions."))
            st.caption(tr("Coverage is measured on each signal date. Trades use the preceding session's signal, so signal-date counts are not the executed holding count."))
            st.dataframe([{"date": row.date, "quarter": row.quarter,
                           "candidates": row.candidates, "with_prices": row.with_prices,
                           "eligible": row.eligible} for row in history.coverage
                          if requested[0] <= row.date <= requested[1]],
                hide_index=True, width="stretch", key="calendar_2026_coverage", column_config={
                    "date": st.column_config.TextColumn(tr("Signal date")),
                    "quarter": st.column_config.TextColumn(tr("Active 13F quarter")),
                    "candidates": st.column_config.NumberColumn(tr("13F candidates")),
                    "with_prices": st.column_config.NumberColumn(tr("With recorded prices")),
                    "eligible": st.column_config.NumberColumn(tr("Eligible after original filters")),
                })
    with st.expander(tr("Inspect the recorded subperiods"), expanded=False):
        st.caption(tr("Original archive subperiods: {start} → {end}. This source table does not change with the selected range.", start=history.start_date, end=history.end_date))
        st.dataframe([{"period": f"{row.start_date} → {row.end_date}", "A2": row.a2_return,
                       "A": row.a_return, "QQQ": row.qqq_return} for row in history.subperiods],
            hide_index=True, width="stretch", key="recorded_2026_subperiods",
            column_config={"period": st.column_config.TextColumn(tr("Source period")),
                           **{arm: st.column_config.NumberColumn(arm, format="percent") for arm in ("A2", "A", "QQQ")}})
        st.caption(tr("Monthly rows compound the recorded returns. The final month ends at the last available date; this is not a full-year result." if calendar_replay else
                      "The first and last periods are partial months. No annualized or full-year result is inferred from this window."))
    with st.expander(tr("2026 source & scope"), expanded=False):
        _source_details(history, presentation=presentation)
        st.caption(tr("Daily equity in the selected range · Rebased to the displayed return baseline"))
        st.dataframe([{"date": row.date, "A2": row.a2_equity, "A": row.a_equity,
                       "QQQ": row.qqq_equity} for row in window.points], hide_index=True,
            width="stretch", key="recorded_2026_daily", column_config={
                "date": st.column_config.TextColumn(tr("Date")),
                **{arm: st.column_config.NumberColumn(arm, format="%.2f") for arm in ("A2", "A", "QQQ")}})
    _record_source()
