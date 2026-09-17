"""Explain recorded performance, its distribution, and the limits of the evidence."""
from pathlib import PureWindowsPath

import streamlit as st

from apps.demo_console.adapters.performance_reader import read_performance
from apps.demo_console.adapters.benchmarks_reader import read_benchmarks
from apps.demo_console.components.performance_charts import (
    drawdown_chart, return_distribution, rolling_chart, wealth_chart, yearly_chart,
)
from apps.demo_console.components.performance_stats import (
    matched_risk_comparison, rolling_returns, summarize_performance,
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


_RANGES = {"All days through selected execution": None, "252 execution days": 252,
           "126 execution days": 126, "63 execution days": 63}


def _percent(value, *, signed=False):
    return tr("N/A") if value is None else format(value, "+.2%" if signed else ".2%")


def _number(value, precision=3):
    return tr("N/A") if value is None else f"{value:,.{precision}f}"


def _metric(label, value, note):
    return (f'<div class="uq-metric"><div class="uq-metric-label">{text(tr(label))}</div>'
            f'<div class="uq-metric-value">{text(value)}</div>'
            f'<div class="uq-metric-note">{text(note)}</div></div>')


def _readout(summary):
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
                 markets, presentation):
    benchmarks = available_benchmarks(markets)
    with st.container(key="uq_performance_path"):
        st.html(section_header(tr("The recorded path, including the setbacks"), tr("RECORDED REPLAY"),
                               tr("Strategy net paths include recorded fees")))
        visible_series = render_curve_focus("research_curve_focus",
            available=(("A",) if show_reference and summary.reference_available else ())
                      + tuple(row.symbol for row in benchmarks))
        render_chart(wealth_chart(summary, show_reference=show_reference, show_gross=show_gross,
                                  benchmarks=benchmarks, visible_series=visible_series),
                        width="stretch", theme=None, key="research_wealth_chart")
        if summary.max_drawdown.depth < 0:
            st.caption(tr("The outlined point marks A2's deepest drawdown in this window."))
        st.caption(tr("Each path starts from 1 immediately before the first included return. The first day's gain or cost is included. Drawdown uses the selected window's running peak."))
        with st.expander(tr("Compare return and downside"), expanded=True):
            rows = matched_risk_comparison(summary)
            st.caption(tr("The same execution dates and net-return basis are used for both portfolios. A higher return can come with a deeper drawdown; this is not a risk-adjusted ranking."
                          if len(rows) > 1 else
                          "Frozen A is unavailable for this window. Any complete market references remain visible."))
            comparison = [{
                "series": tr(row.series), "net_total_return": row.net_total_return,
                "max_drawdown": row.max_drawdown,
                "worst_daily_net_return": row.worst_daily_net_return,
                "observations": row.observations,
            } for row in rows]
            comparison.extend({
                "series": benchmark_label(row.symbol), "net_total_return": row.total_return,
                "max_drawdown": row.max_drawdown,
                "worst_daily_net_return": min(point.daily_return for point in (row.points if markets.baseline_date else row.points[1:]))
                                          if markets.baseline_date or len(row.points) > 1 else None,
                "observations": len(row.points),
            } for row in benchmarks)
            st.dataframe(comparison, hide_index=True, width="stretch", key="research_risk_comparison",
                column_config={
                    "series": st.column_config.TextColumn(tr("Portfolio / control")),
                    "net_total_return": st.column_config.NumberColumn(tr("Period return"), format="percent"),
                    "max_drawdown": st.column_config.NumberColumn(tr("Maximum window drawdown"), format="percent"),
                    "worst_daily_net_return": st.column_config.NumberColumn(tr("Worst daily net return"), format="percent"),
                    "observations": st.column_config.NumberColumn(tr("Recorded execution days"), format="%d"),
                })
        with st.expander(tr("Inspect the A2 drawdown path"), expanded=False):
            render_chart(drawdown_chart(summary), width="stretch", theme=None,
                         key="research_drawdown_chart")
            _drawdown_story(summary)
        render_benchmark_notes(markets, presentation=presentation)
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
            tr("Frozen A control"): _percent(row.reference_net_return, signed=True),
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


def _method(history, *, presentation):
    st.html(section_header(tr("A convincing record needs several kinds of evidence"), tr("INTERPRETING THE RESULT")))
    evidence = (
        ("Historical performance", "Recorded", "Net and gross return paths, recorded execution costs, drawdowns and every observed period can be inspected."),
        ("Comparison", "Frozen A control" if history.reference_available else "Not evaluated",
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
            "No Sharpe ratio, alpha, confidence interval, DSR, PBO or probability of skill is inferred from these observations.",
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


def render_research(model, *, presentation):
    if is_recorded_2026("Research"):
        render_recorded_2026(presentation=presentation)
        return
    execution_date = model.provenance.execution_date
    if model.error or execution_date is None:
        st.info(tr("Research inspection requires a verified decision and its execution date."))
        return
    controls = st.columns([1.6, 1.25, 1.2, 1], gap="medium", vertical_alignment="bottom")
    with controls[0]:
        selected_range = st.selectbox(tr("Research window"), list(_RANGES), key="research_range",
                                      format_func=option_labeler(_RANGES), label_visibility="collapsed",
                                      on_change=reset_date_range, args=("research_dates",),
                                      help=tr("Selecting a preset replaces any applied custom date range."))
    with controls[2]:
        show_reference = st.toggle(tr("Show control on charts"),
                                   value="research_reference" not in st.session_state, key="research_reference")
    with controls[3]:
        show_gross = st.toggle(tr("Show gross path"), value=False, key="research_gross",
                              help=tr("Gross compounds the pre-fee returns along the recorded holdings path. It is not a separate fee-free strategy replay."))
    with st.spinner(tr("Verifying the recorded performance series…")):
        history = read_performance(execution_date)
    if history.error:
        st.error(tr(history.error))
        if not presentation and history.debug_error:
            st.code(history.debug_error, language="text")
        return
    if not history.points:
        st.info(tr("No performance observations are available through this execution date."))
        return
    count = _RANGES[selected_range]
    points = history.points[-count:] if count is not None else history.points
    with controls[1]:
        custom_range = render_date_range("research_dates", history.points[0].execution_date,
                                         execution_date, points[0].execution_date,
                                         points[-1].execution_date)
    if custom_range is not None:
        start, end = custom_range
        points = tuple(point for point in history.points if start <= point.execution_date <= end)
        if not points:
            st.info(tr("No recorded execution observations fall within {start} → {end}. Choose another range.",
                       start=start, end=end))
            return
    summary = summarize_performance(points, initial_wealth=history.initial_nav,
                                    full_history_dates=history.available_dates)
    offset = next(index for index, point in enumerate(history.points)
                  if point.execution_date == points[0].execution_date)
    baseline = history.points[offset - 1].execution_date if offset else None
    markets = read_benchmarks(tuple(point.execution_date for point in points), baseline_date=baseline)
    window_label = "CUSTOM DATE RANGE" if custom_range is not None else "PERFORMANCE WINDOW"
    st.html(f'<div class="uq-history-range"><span>{text(tr(window_label))}</span>'
            f'<strong>{text(summary.start_date)} → {text(summary.end_date)}</strong>'
            f'<span>{text(tr("{count} recorded execution days", count=summary.observations))}</span></div>')
    if history.reference_error:
        st.caption(tr(history.reference_error))
    _readout(summary)
    performance, recovery, consistency, method, execution = localized_tabs(
        ["Performance path", "Drawdown & recovery", "Consistency & concentration", "Evidence & method",
         "Execution frictions"], key="research_tabs")
    with performance:
        _performance(summary, show_reference, show_gross, points=points,
                     full_history_dates=history.available_dates, initial_nav=history.initial_nav,
                     markets=markets, presentation=presentation)
    with consistency:
        _consistency(summary, points, show_reference)
    with recovery:
        with st.container(key="uq_drawdown_episodes"):
            render_drawdown_episodes(points, presentation=presentation)
        with st.container(key="uq_recovery_execution"):
            st.caption(tr("Recovery describes the recorded net-return path. Inspect the execution ledger in Execution frictions for costs, cash and recorded simulation flags."))
    with method:
        _method(history, presentation=presentation)
    with execution:
        with st.container(key="uq_execution_quality"):
            render_execution_quality(points, initial_nav=history.initial_nav)
