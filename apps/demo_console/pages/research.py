"""Explain recorded performance, its distribution, and the limits of the evidence."""
from pathlib import PureWindowsPath
from calendar import monthrange
from random import sample
from math import fsum
from types import SimpleNamespace

import streamlit as st

from apps.demo_console.adapters.performance_reader import read_performance
from apps.demo_console.adapters import workspace_reader
from apps.demo_console.adapters import rx_research_reader
from apps.demo_console.adapters import selected_strategies_reader
from apps.demo_console.adapters.benchmarks_reader import read_benchmarks, default_benchmarks_config, read_updated_benchmarks
from apps.demo_console.components.performance_charts import (
    drawdown_chart, nav_comparison_chart, return_distribution, rolling_chart, wealth_chart, yearly_chart,
)
from apps.demo_console.components.performance_stats import (
    annualized_sharpe, matched_risk_comparison, rolling_returns, summarize_performance, summarize_nav_window,
)
from apps.demo_console.components.execution_quality import render_execution_quality
from apps.demo_console.components.drawdown_episodes import render_drawdown_episodes
from apps.demo_console.components.period_inspector import render_monthly_selector, render_period_inspector
from apps.demo_console.components.localized_tabs import localized_tabs
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.performance_range import render_date_range, reset_date_range
from apps.demo_console.i18n import option_labeler, tr
from apps.demo_console.components.recorded_2026 import is_recorded_2026, render_recorded_2026
from apps.demo_console.components.market_benchmarks import (
    available_benchmarks, benchmark_label, render_benchmark_notes, render_curve_focus,
)
from apps.demo_console.pages.selected_strategies import WORKSPACE_STRATEGIES


_RANGES = {"All days through selected execution": None, "Single date": None, "Custom dates": None,
           "Random period": None, "Calendar month": None, "Calendar quarter": None,
           "252 execution days": 252, "126 execution days": 126, "63 execution days": 63}



def _calendar_window(label, *, quarter=False):
    """Return exact calendar boundaries; recorded dates are intersected separately."""
    year = int(label[:4])
    first_month = (int(label[-1]) - 1) * 3 + 1 if quarter else int(label[5:7])
    last_month = first_month + 2 if quarter else first_month
    return (f"{year:04d}-{first_month:02d}-01",
            f"{year:04d}-{last_month:02d}-{monthrange(year, last_month)[1]:02d}")


def _random_window(dates, previous=None):
    """Choose recorded endpoints, keeping at least two observations where possible."""
    if len(dates) == 1:
        return dates[0], dates[0]
    bounds = tuple(sorted(sample(dates, 2)))
    if bounds == previous and len(dates) > 2:
        start, end = dates.index(bounds[0]), dates.index(bounds[1])
        # A repeated draw advances one endpoint, so explicit reroll visibly changes.
        bounds = (dates[start], dates[end + 1]) if end + 1 < len(dates) else (dates[0], dates[1])
        if bounds == previous:
            bounds = dates[0], dates[-1]
    return bounds


def _select_research_points(history, execution_date, selected_range):
    available = tuple(point for point in history.points if point.execution_date <= execution_date)
    if not available:
        return (), (execution_date, execution_date), None
    count = _RANGES[selected_range]
    points = available[-count:] if count is not None else available
    dates = tuple(point.execution_date for point in available)
    if selected_range == "Single date":
        if st.session_state.get("research_single_date") not in dates:
            st.session_state["research_single_date"] = dates[-1]
        day = st.selectbox(tr("Single date"), tuple(reversed(dates)), key="research_single_date",
                           label_visibility="collapsed")
        return tuple(point for point in available if point.execution_date == day), (day, day), None
    if selected_range == "Random period":
        previous = st.session_state.get("research_random_bounds")
        changed = st.session_state.get("_research_random_dates") != dates
        reroll = st.button(tr("Choose another random period"), key="research_random_reroll")
        if changed or previous is None or reroll:
            bounds = _random_window(dates, previous if not changed else None)
            st.session_state["research_random_bounds"] = bounds
            st.session_state["_research_random_dates"] = dates
        else:
            bounds = previous
        st.caption(tr("Random period: {start} → {end}", start=bounds[0], end=bounds[1]))
        return tuple(point for point in available if bounds[0] <= point.execution_date <= bounds[1]), bounds, None
    if selected_range in ("Calendar month", "Calendar quarter"):
        quarter = selected_range == "Calendar quarter"
        labels = sorted({(f"{point.execution_date[:4]}-Q{(int(point.execution_date[5:7]) - 1) // 3 + 1}"
                          if quarter else point.execution_date[:7]) for point in available}, reverse=True)
        key = "research_calendar_quarter" if quarter else "research_calendar_month"
        if st.session_state.get(key) not in labels:
            st.session_state[key] = labels[0]
        selected = st.selectbox(tr("Calendar quarter" if quarter else "Calendar month"), labels,
                                key=key, label_visibility="collapsed")
        bounds = _calendar_window(selected, quarter=quarter)
        points = tuple(point for point in available if bounds[0] <= point.execution_date <= bounds[1])
        return points, None, bounds
    custom = render_date_range("research_dates", available[0].execution_date,
                               min(execution_date, available[-1].execution_date),
                               points[0].execution_date, points[-1].execution_date)
    if custom is not None:
        points = tuple(point for point in available if custom[0] <= point.execution_date <= custom[1])
    return points, custom, None


def _percent(value, *, signed=False):
    return tr("N/A") if value is None else format(value, "+.2%" if signed else ".2%")


def _number(value, precision=3):
    return tr("N/A") if value is None else f"{value:,.{precision}f}"


def _metric(label, value, note):
    return (f'<div class="uq-metric"><div class="uq-metric-label">{text(tr(label))}</div>'
            f'<div class="uq-metric-value">{text(value)}</div>'
            f'<div class="uq-metric-note">{text(note)}</div></div>')


def _readout(summary, *, updated=False):
    difference = (100 * (summary.net_total_return - summary.reference_net_total_return)
                  if summary.reference_available else None)
    cards = [
        _metric("Net cumulative return", _percent(summary.net_total_return, signed=True), tr("Raw A2 · Net")),
        _metric("A control period return", _percent(summary.reference_net_total_return, signed=True),
                tr("Original strategy control") if summary.reference_available else tr("Frozen A comparison unavailable")),
        _metric("A2 − A return difference", f"{difference:+.2f} pp" if difference is not None else tr("N/A"),
                tr("Observed difference · Not risk-adjusted alpha")),
        _metric("Maximum window drawdown", _percent(summary.max_drawdown.depth),
                tr("From the selected window's running peak")),
    ]
    if updated:
        cards = [
            _metric("Net cumulative return", _percent(summary.net_total_return, signed=True), tr("Raw A2 · Net")),
            _metric("Maximum window drawdown", _percent(summary.max_drawdown.depth),
                    tr("From the selected window's running peak")),
            _metric("Worst daily net return", _percent(summary.worst_day.net_return, signed=True),
                    summary.worst_day.execution_date),
            _metric("Gross–net return gap", f"{summary.gross_net_difference_pp:.2f} pp", tr("Compounded gross minus net")),
        ]
    st.html('<div class="uq-metrics uq-motion-enter">' + ''.join(cards) + '</div>')


def _drawdown_story(summary):
    drawdown = summary.max_drawdown
    if drawdown.depth == 0:
        st.caption(tr("No decline below the running peak was recorded in this window."))
        return
    peak = tr("Initial window baseline") if drawdown.peak_is_initial else drawdown.peak_date
    recovery = drawdown.recovery_date or tr("Not recovered within the window")
    st.html('<div class="uq-drawdown-story">' + ''.join(
        f'<div><span>{text(tr(label))}</span><strong>{text(value)}</strong></div>'
        for label, value in (("Peak before the deepest drawdown", peak),
                             ("Deepest drawdown date", drawdown.trough_date),
                             ("Recovery to that peak", recovery))) + '</div>')


def _performance(summary, show_reference, show_gross, *, points, full_history_dates, initial_nav,
                 markets, presentation, updated=False, rx_summary=None, hgb_comparison=None):
    benchmarks = available_benchmarks(markets)
    with st.container(key="uq_performance_path"):
        st.html(section_header(tr("Portfolio growth after costs" if updated else "The recorded path, including the setbacks"), tr("RECORDED REPLAY"),
                               tr("Strategy net paths include recorded fees")))
        comparison_series = (("A",) if show_reference and summary.reference_available else ()) + (("RX",) if rx_summary else ()) + tuple(row.symbol for row in benchmarks)
        visible_series = render_curve_focus("research_curve_focus", available=comparison_series) if comparison_series else None
        render_chart(wealth_chart(summary, show_reference=show_reference, show_gross=show_gross,
                                  benchmarks=benchmarks, visible_series=visible_series, rx_summary=rx_summary),
                        width="stretch", theme=None, key="research_wealth_chart")
        if summary.max_drawdown.depth < 0:
            st.caption(tr("The outlined point marks A2's deepest drawdown in this window."))
        st.caption(tr("Each path starts from 1 immediately before the first included return. The first day's gain or cost is included. Drawdown uses the selected window's running peak."))
        with st.expander(tr("Compare return and downside"), expanded=True):
            skip_baseline = bool(updated and markets.baseline_date is None and points[0].holding_count == 0
                                 and points[0].net_return == 0 and points[0].transaction_cost == 0)
            rows = matched_risk_comparison(summary, skip_initial_cash_baseline=skip_baseline)
            st.caption(tr("The selected period, after recorded trading costs." if updated else
                          "The same execution dates and net-return basis are used for both portfolios. A higher return can come with a deeper drawdown; this is not a risk-adjusted ranking."
                          if len(rows) > 1 else
                          "Frozen A is unavailable for this window. Any complete market references remain visible."))
            comparison = [{
                "series": tr(row.series), "net_total_return": row.net_total_return,
                "max_drawdown": row.max_drawdown,
                "worst_daily_net_return": row.worst_daily_net_return,
                "observations": row.observations, "annualized_sharpe": row.annualized_sharpe,
            } for row in rows]
            if rx_summary is not None:
                comparison.append({"series": "A2 + RX", "net_total_return": rx_summary.net_total_return,
                    "max_drawdown": rx_summary.max_drawdown.depth,
                    "worst_daily_net_return": rx_summary.worst_day.net_return,
                    "observations": rx_summary.observations,
                    "annualized_sharpe": matched_risk_comparison(rx_summary, skip_initial_cash_baseline=skip_baseline)[0].annualized_sharpe})
            comparison.extend({
                "series": benchmark_label(row.symbol), "net_total_return": row.total_return,
                "max_drawdown": row.max_drawdown,
                "worst_daily_net_return": min(point.daily_return for point in (row.points if markets.baseline_date else row.points[1:]))
                                          if markets.baseline_date or len(row.points) > 1 else None,
                "observations": len(row.points),
                "annualized_sharpe": annualized_sharpe(point.daily_return for point in
                    (row.points if markets.baseline_date else row.points[1:])),
            } for row in benchmarks)
            st.dataframe(comparison, hide_index=True, width="stretch", key="research_risk_comparison",
                column_config={
                    "series": st.column_config.TextColumn(tr("Portfolio / control")),
                    "annualized_sharpe": st.column_config.NumberColumn(tr("Annualized Sharpe"), format="%.2f"),
                    "net_total_return": st.column_config.NumberColumn(tr("Period return"), format="percent"),
                    "max_drawdown": st.column_config.NumberColumn(tr("Maximum window drawdown"), format="percent"),
                    "worst_daily_net_return": st.column_config.NumberColumn(tr("Worst daily net return"), format="percent"),
                    "observations": st.column_config.NumberColumn(tr("Recorded execution days"), format="%d"),
                })
            st.caption(tr("Sharpe: daily mean / sample standard deviation × √252; risk-free rate = 0. Initial cash baseline excluded. Fewer than two returns or zero variance: unavailable. Descriptive, not evidence of statistical significance."))
        with st.expander(tr("Inspect the A2 drawdown path"), expanded=False):
            render_chart(drawdown_chart(summary), width="stretch", theme=None,
                         key="research_drawdown_chart")
            _drawdown_story(summary)
        render_benchmark_notes(markets, presentation=presentation)
        if hgb_comparison:
            _render_hgb_comparison(hgb_comparison)
    if updated:
        _historical_comparisons(summary.start_date, summary.end_date, presentation=presentation)
    st.html(section_header(tr("Every observed month"), tr("PERIOD DISTRIBUTION"),
                           tr("Blue: positive · Amber: negative")))
    render_monthly_selector(summary)
    st.caption(tr("Monthly cells compound the displayed daily net returns. Empty calendar periods carry no result. Hover to inspect dates, observation count and partial-period status."))
    st.caption(tr("* Archive boundary or window-cut period. A marked month or year should not be read as a full calendar-period result.").replace("*", r"\*", 1))
    render_period_inspector(points, full_history_dates=full_history_dates,
                            initial_nav=initial_nav, show_reference=show_reference)
    years, costs = st.columns([1.5, 1], gap="large")
    with years:
        st.html(section_header(tr("Across recorded years")))
        render_chart(yearly_chart(summary, show_reference=show_reference), width="stretch",
                        theme=None, key="research_yearly_chart")
    with costs:
        st.html(section_header(tr("What the replay charged"), tr("COST CONTEXT")))
        facts = (("Gross cumulative return", _percent(summary.gross_total_return, signed=True)),
                 ("Net cumulative return", _percent(summary.net_total_return, signed=True)),
                 ("Recorded transaction costs", _number(summary.total_transaction_cost, 4)),
                 ("Cost unit", tr("Original capital = 1")))
        st.html('<dl class="uq-facts">' + ''.join(
            f'<div><dt>{text(tr(label))}</dt><dd>{text(value)}</dd></div>' for label, value in facts) + '</dl>')
        st.caption(tr("The frozen contract records 10 bps round-trip transaction cost. The amount sum and the gross–net compounded return gap are different measures; neither is a forecast of live trading costs."))
    with st.expander(tr("Inspect the period ledger"), expanded=False):
        st.dataframe([{
            tr("Period"): row.period, tr("Net return"): _percent(row.net_return, signed=True),
            **({} if updated else {tr("Frozen A control"): _percent(row.reference_net_return, signed=True)}),
            tr("Recorded execution days"): row.observations,
            tr("First observation"): row.start_date, tr("Last observation"): row.end_date,
            tr("Coverage"): tr("Window partial" if row.window_partial else
                               "Archive boundary" if row.coverage_boundary else "Recorded period"),
        } for row in reversed(summary.months)], hide_index=True, width="stretch", key="research_period_table")


def _consistency(summary, points, show_reference):
    st.html(section_header(tr("How much came from a few exceptional days?"), tr("GROWTH CONCENTRATION")))
    top5, top10, extremes = st.columns([1, 1, 1.5], gap="large")
    with top5:
        st.metric(tr("Top 5 positive days"), _percent(summary.top5_positive_log_share))
        st.caption(tr("Share of all positive log growth"))
    with top10:
        st.metric(tr("Top 10 positive days"), _percent(summary.top10_positive_log_share))
        st.caption(tr("Share of all positive log growth"))
    with extremes:
        rows = (("Best recorded day", summary.best_day), ("Worst recorded day", summary.worst_day))
        st.html('<dl class="uq-facts uq-extremes">' + ''.join(
            f'<div><dt>{text(tr(label))}<small>{text(day.execution_date if day else None)}</small></dt>'
            f'<dd>{text(_percent(day.net_return if day else None, signed=True))}</dd></div>'
            for label, day in rows) + '</dl>')
    st.caption(tr("Positive contributions use log(1 + daily net return), divided by all positive log growth. Negative days are kept separately. These shares describe concentration, not the probability of skill."))
    distribution, dependence = st.columns([1.45, 1], gap="large")
    with distribution:
        st.html(section_header(tr("The daily return distribution")))
        render_chart(return_distribution(points), width="stretch", theme=None,
                        key="research_distribution_chart")
    with dependence:
        st.html(section_header(tr("Observations are not independent trials"), tr("TIME DEPENDENCE")))
        st.html('<dl class="uq-facts">' + ''.join(
            f'<div><dt>{text(tr(label))}</dt><dd>{text(_number(value))}</dd></div>'
            for label, value in (("Return autocorrelation · Lag 1", summary.autocorrelation_lag1),
                                 ("Return autocorrelation · Lag 5", summary.autocorrelation_lag5),
                                 ("Positive log growth", summary.positive_log_growth),
                                 ("Negative log growth", summary.negative_log_growth))) + '</dl>')
        st.caption(tr("Autocorrelation uses fixed lags and at least 20 observed pairs. It is descriptive, without a significance threshold or an independence claim. Constant or short samples remain unavailable."))
    valid_months = [period for period in summary.months if not period.window_partial and not period.coverage_boundary]
    positive = sum(period.net_return > 0 for period in valid_months)
    st.html(f'<div class="uq-research-observation"><strong>{text(tr("{positive} / {total} interior months had a positive net return", positive=positive, total=len(valid_months)))}</strong>'
            f'<p>{text(tr("Boundary and window-partial months are excluded from this count. A positive-month frequency is a historical observation, not a forecast or a skill probability."))}</p></div>')
    with st.expander(tr("Inspect fixed 63-day windows"), expanded=False):
        st.caption(tr("Each point compounds 63 recorded execution days ending on that date. Overlapping windows share observations; this is not a count of independent trials."))
        windows = rolling_returns(summary)
        if windows:
            st.caption(tr("Rolling windows: {count} · End dates {start} → {end}",
                          count=len(windows), start=windows[0].end_date, end=windows[-1].end_date))
            render_chart(rolling_chart(windows, show_reference=show_reference),
                         width="stretch", theme=None, key="research_rolling_chart")
            reference_visible = show_reference and all(row.reference_net_return is not None for row in windows)
            st.dataframe([{
                "start_date": row.start_date, "end_date": row.end_date,
                "observations": row.observations, "net_return": row.net_return,
                "reference_net_return": row.reference_net_return,
            } for row in windows], hide_index=True, width="stretch", height=220,
                key="research_rolling_table", column_config={
                    "start_date": st.column_config.TextColumn(tr("Window start date")),
                    "end_date": st.column_config.TextColumn(tr("Window end date")),
                    "observations": st.column_config.NumberColumn(tr("Recorded execution days"), format="%d"),
                    "net_return": st.column_config.NumberColumn(tr("Raw A2 · Net"), format="percent"),
                    "reference_net_return": (st.column_config.NumberColumn(tr("Frozen A control · Net"), format="percent")
                                             if reference_visible else None),
                })
        else:
            st.info(tr("Fewer than 63 execution records are included. No full rolling window is available."))


def _historical_comparisons(start_date, end_date, *, presentation):
    """Inspect the frozen evidence inside the selected window, without joining NAVs."""
    with st.expander(tr("Historical research comparisons"), expanded=False):
        st.caption(tr("Original frozen A2 / A and ETF references retain their own recorded basis. These paths are not joined to the updated portfolio."))
        benchmark_config = default_benchmarks_config()
        bindings = {item.symbol: item for item in benchmark_config.artifacts
                    if item.window == "historical" and item.symbol in ("QQQ", "SPY")}
        if set(bindings) != {"QQQ", "SPY"}:
            st.info(tr("The historical QQQ / SPY reference window is unavailable."))
            return
        common_start = max(start_date, *(item.start_date for item in bindings.values()))
        common_end = min(end_date, *(item.end_date for item in bindings.values()))
        if common_start > common_end:
            st.info(tr("No frozen comparison observations overlap the selected period."))
            return
        history = read_performance(common_end)
        if history.error:
            st.info(tr(history.error))
            return
        points = tuple(point for point in history.points if common_start <= point.execution_date <= common_end)
        if not points:
            st.info(tr("No frozen comparison observations overlap the selected period."))
            return
        summary = summarize_performance(points, initial_wealth=history.initial_nav,
                                        full_history_dates=history.available_dates)
        offset = next(index for index, point in enumerate(history.points)
                      if point.execution_date == points[0].execution_date)
        baseline = history.points[offset - 1].execution_date if offset else None
        if baseline is not None and baseline < max(item.start_date for item in bindings.values()):
            baseline = None
        markets = read_benchmarks(tuple(point.execution_date for point in points), baseline_date=baseline,
                                  config=benchmark_config)
        benchmarks = available_benchmarks(markets)
        st.caption(tr("Shared reference coverage: {start} → {end} · {count} execution days",
                      start=summary.start_date, end=summary.end_date, count=summary.observations))
        st.caption(tr("The comparison uses the common recorded window of frozen A2 / A, QQQ and SPY. The updated strategy above keeps its full selected period."))
        available = (("A",) if summary.reference_available else ()) + tuple(row.symbol for row in benchmarks)
        visible = render_curve_focus("research_historical_curve_focus", available=available) if available else None
        render_chart(wealth_chart(summary, show_reference=summary.reference_available, show_gross=False,
                                  benchmarks=benchmarks, visible_series=visible),
                     width="stretch", theme=None, key="research_historical_wealth_chart")
        st.caption(tr("Each frozen path starts from 1 before this reference window. Only complete ETF observations for this window are displayed."))
        rows = [{tr("Portfolio / control"): tr(row.series), tr("Period return"): row.net_total_return,
                 tr("Maximum window drawdown"): row.max_drawdown,
                 tr("Recorded execution days"): row.observations}
                for row in matched_risk_comparison(summary)]
        rows.extend({tr("Portfolio / control"): benchmark_label(row.symbol), tr("Period return"): row.total_return,
                     tr("Maximum window drawdown"): row.max_drawdown,
                     tr("Recorded execution days"): len(row.points)} for row in benchmarks)
        st.dataframe(rows, hide_index=True, width="stretch", key="research_historical_comparison",
                     column_config={tr("Period return"): st.column_config.NumberColumn(format="percent"),
                                    tr("Maximum window drawdown"): st.column_config.NumberColumn(format="percent")})
        if history.reference_error:
            st.caption(tr(history.reference_error))
        render_benchmark_notes(markets, presentation=presentation)
        st.caption(tr("Source: original frozen execution archive"))
        for path, digest in history.source_refs:
            st.caption(PureWindowsPath(path).name if presentation else path)
            if not presentation:
                st.code(digest, language="text")


def _method(history, *, presentation, updated=False):
    st.html(section_header(tr("A convincing record needs several kinds of evidence"), tr("INTERPRETING THE RESULT")))
    evidence = (
        ("Historical performance", "Recorded", "Net and gross return paths, recorded execution costs, drawdowns and every observed period can be inspected."),
        ("Comparison", "QQQ / SPY price references" if updated else "Frozen A control" if history.reference_available else "Not evaluated",
         "QQQ and SPY use the same selected dates and raw open-to-open price returns, excluding dividends. These market references do not establish risk-adjusted alpha." if updated else
         "The A control is a fixed-rule portfolio from the same frozen study. It is not a market index or a risk-adjusted alpha estimate."),
        ("Independent statistical advantage", "Not evaluated",
         "A complete trial history, independent out-of-sample protocol and selection-bias-adjusted evaluation are not available in this display."),
    )
    st.html('<div class="uq-research-evidence">' + ''.join(
        f'<article><span>{text(tr(label))}</span><strong>{text(tr(status))}</strong><p>{text(tr(detail))}</p></article>'
        for label, status, detail in evidence) + '</div>')
    st.caption(tr("These are descriptive results from a retrospectively assembled frozen replay. Artifact integrity does not establish that this history was untouched during strategy selection."))
    with st.expander(tr("Calculation notes"), expanded=True):
        for source in (
            "Returns compound every included execution day, including the first observation. Fees are not removed from the net path.",
            "A selected window is rebased to 1 before its first return. The maximum drawdown is measured within that window; it is not necessarily the full-archive drawdown.",
            "Period returns retain all recorded days. Archive-edge periods and windows cut through recorded periods are labelled explicitly.",
            "The normalized cost amount uses the original initial capital, even when a shorter return window is selected.",
            "Sharpe is a descriptive annualized ratio. No alpha, confidence interval, DSR, PBO or probability of skill is inferred from these observations.",
            "This view never extends beyond the execution linked to the selected decision. A custom range can end earlier. Later archive rows are excluded.",
        ):
            st.write(tr(source))
    st.markdown(tr("Method references: [time dependence and Sharpe ratios](https://rpc.cfainstitute.org/research/financial-analysts-journal/2002/the-statistics-of-sharpe-ratios), [selection bias and the Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf), [statistical interpretation](https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf)."))
    with st.expander(tr("Performance artifact identities"), expanded=False):
        for path, digest in history.source_refs:
            source = PureWindowsPath(path)
            label = (f"{source.parent.name} / {source.name}" if source.parent.name in {"A", "A2"}
                     else source.name) if presentation else path
            st.text(f'{label} · {digest[:12] + "…" if presentation else digest}')
        for limitation in history.limitations:
            st.caption(tr(limitation))
        if not presentation and history.debug_error:
            st.code(history.debug_error, language="text")
        if not presentation and history.reference_debug_error:
            st.code(history.reference_debug_error, language="text")


_nav_window = summarize_nav_window


def _hgb_comparison(package, start, end, raw_daily=()):
    """Keep one exact common recorded window; unmatched RAW dates stay separate."""
    raw_daily = package.get("raw_reference", {}).get("daily", raw_daily)
    strategies = {sid: package["strategies"][sid] for sid in selected_strategies_reader.STRATEGY_IDS}
    common_start = max(start, *(strategy["daily"][0]["date"] for strategy in strategies.values()))
    common_end = min(end, *(strategy["daily"][-1]["date"] for strategy in strategies.values()))
    if common_start > common_end:
        return None
    windows = {strategy["label"]: _nav_window(strategy["daily"], common_start, common_end)
               for strategy in strategies.values()}
    if any(window is None for window in windows.values()):
        return None
    dates = tuple(row["execution_date"] for row in next(iter(windows.values()))["rows"])
    if any(tuple(row["execution_date"] for row in window["rows"]) != dates for window in windows.values()):
        raise ValueError("HGB comparison calendars differ")
    raw_matches = False
    if raw_daily:
        raw_window = _nav_window(raw_daily, common_start, common_end)
        raw_matches = bool(raw_window and tuple(row["execution_date"] for row in raw_window["rows"]) == dates)
        if raw_matches:
            windows = {"Raw A2": raw_window, **windows}
    return {"windows": windows, "start": dates[0], "end": dates[-1], "days": len(dates),
            "raw_requested": bool(raw_daily), "raw_matches": raw_matches,
            "same_batch": "raw_reference" in package,
            "strategy_ids": {"Raw A2": "RAW_A2", **{strategy["label"]: sid for sid, strategy in strategies.items()}}}


def _load_hgb_comparison(history, start, end, package=None):
    try:
        package = selected_strategies_reader.load_package() if package is None else package
        raw_daily = [{"date": point.execution_date, "nav": point.nav, "cash_weight": point.cash / point.nav}
                     for point in history.points]
        return _hgb_comparison(package, start, end, raw_daily)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _render_hgb_comparison(comparison):
    from apps.demo_console.pages.selected_strategies import render_comparison_paths, render_comparison_statistics
    render_comparison_paths(comparison, key_prefix="research_hgb")
    render_comparison_statistics(comparison, key_prefix="research_hgb")


def render_applied_performance(contexts, package, cutoff, *, key_prefix="applied", statistics=True):
    """One interval controls all three ledgers, with no detail-focus dependency."""
    from apps.demo_console.pages.selected_strategies import (
        render_comparison_cards, render_comparison_paths, render_comparison_statistics, _comparison_summaries,
    )
    from .selected_strategies import replay_basis_caption, replay_update_caption
    st.caption(tr(replay_basis_caption(package)))
    update_caption = replay_update_caption(package)
    if update_caption:
        st.caption(tr(update_caption))
    daily = contexts[selected_strategies_reader.STRATEGY_IDS[0]]["history"]["daily"]
    if not daily:
        render_comparison_cards(contexts, summaries={}, key=key_prefix + "_summary")
        st.info(tr("No recorded HGB performance is available through this observation date."))
        return None
    controls = st.columns([1.3, 1.0, .65, 1.6], gap="small", vertical_alignment="bottom")
    with controls[0]:
        selected_range = st.selectbox(tr("Research window"), list(_RANGES), key="research_range",
            format_func=option_labeler(_RANGES), label_visibility="collapsed", persist_state="session",
            on_change=reset_date_range, args=("research_dates",))
    selectable = SimpleNamespace(points=tuple(SimpleNamespace(execution_date=row["date"]) for row in daily))
    with controls[1]:
        points, _, calendar_bounds = _select_research_points(selectable, daily[-1]["date"], selected_range)
    if not points:
        st.info(tr("No recorded HGB performance is available in this selected window."))
        return None
    comparison = _hgb_comparison(package, points[0].execution_date, points[-1].execution_date,
                                 contexts.get("RAW_A2", {}).get("history", {}).get("daily", []))
    if not comparison:
        st.info(tr("No comparable replay is available in this window."))
        return None
    with controls[2]:
        reference_symbol=st.selectbox(tr("Price reference"),("QQQ","SPY","None"), key="applied_benchmark",
            format_func=lambda value:tr(value),persist_state="session",label_visibility="collapsed")
    if comparison["same_batch"] and reference_symbol != "None":
        archive=package["strategies"][selected_strategies_reader.STRATEGY_IDS[0]]["daily"]
        first=next(index for index,row in enumerate(archive) if row["date"]==comparison["start"])
        baseline_date=archive[first-1]["date"] if first else None
        references=read_updated_benchmarks(tuple(row["execution_date"] for row in next(iter(comparison["windows"].values()))["rows"]), baseline_date)
        matching=next((item for item in references.series if item.symbol==reference_symbol and not item.error),None)
        if matching:
            comparison["reference"]={"label":reference_symbol+" · "+tr("Price reference"),
                "rows":[{"execution_date":point.date,"value":point.equity} for point in matching.points],
                "return":matching.total_return}
        else:
            st.caption(tr("Price reference is unavailable for the complete interval."))
    with controls[3]:
        st.caption(tr("Shared recorded window: {start} → {end} · {count} observations",
            start=comparison["start"], end=comparison["end"], count=comparison["days"]))
    render_comparison_paths(comparison, key_prefix=key_prefix)
    render_comparison_cards(contexts, summaries=_comparison_summaries(comparison), key=key_prefix + "_summary")
    if cutoff and cutoff > daily[-1]["date"]:
        st.caption(tr("Replay through {end} · Signal snapshot {selected}. Later targets do not add returns.",
            end=daily[-1]["date"], selected=cutoff))
    if calendar_bounds:
        st.caption(tr("Calendar period: {start} → {end}. Only recorded execution dates within this period are included.",
            start=calendar_bounds[0], end=calendar_bounds[1]))
        if daily[0]["date"] > calendar_bounds[0] or daily[-1]["date"] < calendar_bounds[1]:
            st.caption(tr("Boundary calendar period: available records {start} → {end}; this may be an incomplete month or quarter.",
                start=points[0].execution_date, end=points[-1].execution_date))
    if comparison["raw_requested"] and not comparison["raw_matches"]:
        st.caption(tr("RAW dates do not fully match this HGB window; RAW is omitted from this comparison."))
    if statistics:
        render_comparison_statistics(comparison, key_prefix=key_prefix)
    return comparison


def _render_applied_research(model, strategy_id, *, presentation, package=None):
    cutoff = st.session_state.get("decision_date") or model.decision_date
    try:
        package = selected_strategies_reader.load_package() if package is None else package
        contexts = workspace_reader.load_applied_strategies(
            cutoff, package=package, sample=st.session_state.get("workspace_sample", "test_2026"))
        view = contexts[selected_strategies_reader.STRATEGY_IDS[0]]
        if view.get("error"):
            raise ValueError(view.get("debug_error") or view["error"])
        comparison = render_applied_performance(contexts, package, cutoff, key_prefix="research_hgb")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        st.error(tr("Selected HGB performance is unavailable; no RAW result is substituted."))
        if not presentation:
            st.code(f"{type(exc).__name__}: {exc}", language="text")
        return
    with st.expander(tr("Evidence & method"), expanded=False):
        st.caption(tr("Three frozen strategies use the same cash-start ledger, execution dates, price inputs and 5 bp one-way fee. No model is refitted and no missing return is extended."))
        from .selected_strategies import replay_basis_caption
        st.caption(tr(replay_basis_caption(package)))
        st.caption(tr("Window returns use the NAV immediately before the first included record. Cash values are historical replay weights, separate from the latest cash-start target."))
        for name, digest in package["source_hashes"].items():
            st.text(f'{name} · {digest[:12] + "…" if presentation else digest}')
    if strategy_id == "RAW_A2":
        details = st.expander(tr("Raw A2 details"), expanded=False, on_change="rerun", key="applied_raw_research_details")
        if details.open:
            with details:
                _render_raw_research(model, presentation=presentation, selected_package=package,
                    window_bounds=(comparison["start"], comparison["end"]) if comparison else None)


def render_research(model, *, presentation, selected_package=None):
    selected_strategy = st.session_state.get("workspace_strategy", "RAW_A2")
    if (selected_strategy in selected_strategies_reader.STRATEGY_IDS
            or st.session_state.get("workspace_sample") == "test_2026"):
        _render_applied_research(model, selected_strategy, presentation=presentation, package=selected_package)
        return
    _render_raw_research(model, presentation=presentation, selected_package=selected_package)


def _render_raw_research(model, *, presentation, selected_package=None, window_bounds=None):
    updated = workspace_reader.is_updated(model)
    if not updated and is_recorded_2026("Research"):
        render_recorded_2026(presentation=presentation)
        return
    execution_date = model.performance_cutoff_date if updated else model.provenance.execution_date
    if model.error or execution_date is None:
        st.info(tr("Research inspection requires a verified decision and its execution date."))
        return
    controls = None
    if window_bounds is None:
        controls = st.columns([1.6, 1.25, 1] if updated else [1.6, 1.25, 1.2, 1],
                              gap="medium", vertical_alignment="bottom")
        with controls[0]:
            selected_range = st.selectbox(tr("Research window"), list(_RANGES), key="research_range",
                                          format_func=option_labeler(_RANGES), label_visibility="collapsed",
                                          on_change=reset_date_range, args=("research_dates",),
                                          help=tr("Selecting a preset replaces any applied custom date range."))
    show_reference = False
    if not updated:
        with controls[2] if controls else st.container():
            show_reference = st.toggle(tr("Show control on charts"),
                                      value="research_reference" not in st.session_state, key="research_reference")
    with controls[-1] if controls else st.container():
        show_gross = st.toggle(tr("Show gross path"), value=False, key="research_gross",
                              help=tr("Gross compounds the pre-fee returns along the recorded holdings path. It is not a separate fee-free strategy replay."))
    with st.spinner(tr("Verifying the recorded performance series…")):
        history = workspace_reader.read_performance(model) if updated else read_performance(execution_date)
    if history.error:
        st.error(tr(history.error))
        if not presentation and history.debug_error:
            st.code(history.debug_error, language="text")
        return
    if not history.points:
        st.info(tr("No performance observations are available through this execution date."))
        return
    if window_bounds is None:
        with controls[1]:
            points, custom_range, calendar_bounds = _select_research_points(history, execution_date, selected_range)
    else:
        points = tuple(point for point in history.points
                       if window_bounds[0] <= point.execution_date <= min(execution_date, window_bounds[1]))
        custom_range, calendar_bounds = window_bounds, None
    if not points:
        start, end = custom_range or calendar_bounds
        st.info(tr("No recorded execution observations fall within {start} → {end}. Choose another range.",
                   start=start, end=end))
        return
    if calendar_bounds is not None:
        st.caption(tr("Calendar period: {start} → {end}. Only recorded execution dates within this period are included.",
                      start=calendar_bounds[0], end=calendar_bounds[1]))
        if history.points[0].execution_date > calendar_bounds[0] or history.points[-1].execution_date < calendar_bounds[1]:
            st.caption(tr("Boundary calendar period: available records {start} → {end}; this may be an incomplete month or quarter.",
                          start=points[0].execution_date, end=points[-1].execution_date))
    summary = summarize_performance(points, initial_wealth=history.initial_nav,
                                    full_history_dates=history.available_dates)
    rx_summary = None
    if updated:
        rx = rx_research_reader.read(model)
        if rx.error:
            st.caption(tr(rx.error))
        else:
            selected_dates = tuple(point.execution_date for point in points)
            rx_points = tuple(point for point in rx.history.points if point.execution_date in set(selected_dates))
            if tuple(point.execution_date for point in rx_points) == selected_dates:
                rx_summary = summarize_performance(rx_points, initial_wealth=rx.history.initial_nav,
                    full_history_dates=rx.history.available_dates)
                st.caption(tr(rx_research_reader.LIMITATION))
            else:
                st.info(tr("RX performance ends on {cutoff} and does not fully cover this window. The original A2 and market window is unchanged.",
                           cutoff=rx.history.effective_end_date or "—"))
    offset = next(index for index, point in enumerate(history.points)
                  if point.execution_date == points[0].execution_date)
    baseline = history.points[offset - 1].execution_date if offset else history.baseline_date
    benchmark_reader = read_updated_benchmarks if updated else read_benchmarks
    markets = benchmark_reader(tuple(point.execution_date for point in points), baseline_date=baseline)
    window_label = "CUSTOM DATE RANGE" if custom_range is not None else "PERFORMANCE WINDOW"
    st.html(f'<div class="uq-history-range"><span>{text(tr(window_label))}</span>'
            f'<strong>{text(summary.start_date)} → {text(summary.end_date)}</strong>'
            f'<span>{text(tr("{count} recorded execution days", count=summary.observations))}</span></div>')
    if history.reference_error:
        st.caption(tr(history.reference_error))
    if updated:
        st.caption(tr("After-cost returns · Valued at each execution open"))
    _readout(summary, updated=updated)
    performance, recovery, consistency, method, execution = localized_tabs(
        ["Performance path", "Drawdown & recovery", "Consistency & concentration", "Evidence & method",
         "Execution frictions"], key="research_tabs")
    with performance:
        hgb_comparison = (_load_hgb_comparison(history, points[0].execution_date, points[-1].execution_date, selected_package)
                          if updated and window_bounds is None and points[-1].execution_date >= "2026-01-01" else None)
        _performance(summary, show_reference, show_gross, points=points,
                     full_history_dates=history.available_dates, initial_nav=history.initial_nav,
                     markets=markets, presentation=presentation, updated=updated, rx_summary=rx_summary,
                     hgb_comparison=hgb_comparison)
    with consistency:
        _consistency(summary, points, show_reference)
    with recovery:
        with st.container(key="uq_drawdown_episodes"):
            render_drawdown_episodes(points, presentation=presentation)
        with st.container(key="uq_recovery_execution"):
            st.caption(tr("Recovery describes the recorded net-return path. Inspect the execution ledger in Execution frictions for costs, cash and recorded simulation flags."))
    with method:
        _method(history, presentation=presentation, updated=updated)
    with execution:
        with st.container(key="uq_execution_quality"):
            render_execution_quality(points, initial_nav=history.initial_nav)
