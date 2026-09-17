"""Inspect a recorded month inside an already selected execution window."""
from collections.abc import Mapping
from functools import partial
from math import isfinite

import streamlit as st

from apps.demo_console.components.performance_charts import monthly_chart, wealth_chart
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.i18n import tr
from apps.demo_console.models import PerformancePoint

_MONTH_KEY = "research_month_detail_month"
_EXPANDER_KEY = "research_month_detail"
_EXPANDER_OPEN = "_research_month_detail_open"
_SELECTION = "research_month"


def _remember_expander() -> None:
    st.session_state[_EXPANDER_OPEN] = bool(st.session_state.get(_EXPANDER_KEY, False))


def _select_month(months: tuple[str, ...], key: str) -> None:
    """Consume a current native click before rendering the month widgets."""
    if st.session_state.get("_research_month_chart_key") != key:
        return
    event = st.session_state.get(key)
    selection = event.get("selection") if isinstance(event, Mapping) else None
    rows = selection.get(_SELECTION) if isinstance(selection, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return
    period = rows[0].get("period")
    if isinstance(period, str) and period in months:
        st.session_state[_MONTH_KEY] = period
        # Stateful expanders support programmatic updates in Streamlit 1.63.
        st.session_state[_EXPANDER_KEY] = True
        st.session_state[_EXPANDER_OPEN] = True


def render_monthly_selector(summary) -> None:
    """Link displayed month cells to the existing bounded detail inspector."""
    months = tuple(period.period for period in summary.months)
    if not months:
        st.session_state["_research_month_chart_key"] = None
        return
    selected = st.session_state.get(_MONTH_KEY)
    if selected not in months:
        selected = months[-1]
    # Reset the native selection after a manual month choice, a different
    # displayed window, or closing the details. Old chart callbacks then cannot
    # override those choices, and the same cell can be clicked to reopen it.
    context = (tuple((period.period, period.start_date, period.end_date, period.observations)
                     for period in summary.months), selected,
               bool(st.session_state.get(_EXPANDER_OPEN, False)))
    if st.session_state.get("_research_month_chart_context") != context:
        st.session_state["_research_month_chart_revision"] = st.session_state.get("_research_month_chart_revision", 0) + 1
        st.session_state["_research_month_chart_context"] = context
    key = f'research_monthly_chart_{st.session_state["_research_month_chart_revision"]}'
    st.session_state["_research_month_chart_key"] = key
    render_chart(monthly_chart(summary, selected_period=selected), width="stretch", theme=None,
                    key=key, on_select=partial(_select_month, months, key), selection_mode=[_SELECTION])
    st.caption(tr("Click a recorded month to open its details below, or use the Month to inspect selector."))


def month_details(points: tuple[PerformancePoint, ...], month: str, *, full_history_dates):
    """Select only supplied observations; rebase before the month's first return."""
    rows = tuple(point for point in points if point.execution_date[:7] == month)
    if not rows:
        raise ValueError("The inspected month must occur in the selected execution window.")
    summary = summarize_performance(rows, initial_wealth=1.0, full_history_dates=full_history_dates)
    return rows, summary


def daily_records(points: tuple[PerformancePoint, ...]) -> list[dict]:
    """Original daily fractions and cost amounts, including missing reference values."""
    return [{"execution_date": point.execution_date, "net_return": point.net_return,
             "gross_return": point.gross_return, "reference_net_return": point.reference_net_return,
             "transaction_cost": point.transaction_cost} for point in points]


def render_period_inspector(points: tuple[PerformancePoint, ...], *, full_history_dates,
                            initial_nav: float = 1.0, show_reference: bool = True) -> None:
    if (isinstance(initial_nav, bool) or not isinstance(initial_nav, (int, float))
            or not isfinite(initial_nav) or initial_nav <= 0):
        raise ValueError("Source initial NAV must be finite and positive.")
    window = summarize_performance(points, initial_wealth=1.0, full_history_dates=full_history_dates)
    label = tr("Inspect a month in detail")
    # Expander identity includes its translated label in 1.63. Restore a saved
    # open/closed choice only when the label changes or the widget was absent;
    # normal reruns leave native state untouched.
    if (st.session_state.get("_research_month_detail_label") != label or _EXPANDER_KEY not in st.session_state):
        if _EXPANDER_OPEN in st.session_state:
            st.session_state[_EXPANDER_KEY] = st.session_state[_EXPANDER_OPEN]
        st.session_state["_research_month_detail_label"] = label
    with st.expander(label, expanded=False, key=_EXPANDER_KEY, on_change=_remember_expander):
        if not window.months:
            st.info(tr("No recorded months are available in this window."))
            return
        # Latest by calendar order, independent of returns. A valid existing
        # YYYY-MM choice survives both language and window changes.
        months = tuple(period.period for period in reversed(window.months))
        # Let the native default initialize a new control. Pre-writing its
        # state sends a one-shot set_value instruction back to the browser;
        # that instruction is needed only when an existing month leaves the
        # window, never for the ordinary initial render or a user selection.
        if _MONTH_KEY in st.session_state and st.session_state[_MONTH_KEY] not in months:
            st.session_state[_MONTH_KEY] = months[0]
        month = st.selectbox(tr("Month to inspect"), months, index=0, key=_MONTH_KEY,
                             persist_state="session")
        if month not in months:
            st.info(tr("No recorded months are available in this window."))
            return
        rows, summary = month_details(points, month, full_history_dates=full_history_dates)
        period = summary.months[0]
        st.caption(tr("Observed month: {month} · {start} → {end}",
                      month=month, start=summary.start_date, end=summary.end_date))
        count, net, drawdown = st.columns(3, gap="medium")
        with count:
            st.metric(tr("Recorded execution days"), summary.observations)
        with net:
            st.metric(tr("Month net return"), f"{summary.net_total_return:+.2%}")
        with drawdown:
            st.metric(tr("Within-month maximum drawdown"), f"{summary.max_drawdown.depth:.2%}")
        if period.window_partial:
            st.info(tr("The selected window cuts this month; only its included execution days are shown."))
        if period.coverage_boundary:
            st.caption(tr("This month touches a frozen archive boundary; calendar-month completeness is not asserted."))
        st.caption(tr("Rebased to 1 before this month's first included return, including that day's cost. Drawdown is measured within this month's displayed records, not the full archive."))
        if show_reference and not summary.reference_available:
            st.caption(tr("Frozen A comparison unavailable"))
        chart = wealth_chart(summary, show_reference=show_reference, show_gross=False)
        render_chart(chart.properties(name="research_month_detail_chart"),
                        width="stretch", theme=None, key="research_month_detail_chart")
        if summary.max_drawdown.depth < 0:
            st.caption(tr("Amber highlights the maximum drawdown within the displayed window."))
        st.caption(tr("Daily costs retain the original source unit (initial NAV = {initial_nav}).",
                      initial_nav=f"{initial_nav:g}"))
        st.dataframe(daily_records(rows), hide_index=True, width="stretch",
                     key="research_month_detail_table", column_config={
                         "execution_date": st.column_config.TextColumn(tr("Execution date")),
                         "net_return": st.column_config.NumberColumn(tr("Net return"), format="percent"),
                         "gross_return": st.column_config.NumberColumn(tr("Gross return"), format="percent"),
                         "reference_net_return": st.column_config.NumberColumn(tr("Frozen A control · Net"), format="percent"),
                         "transaction_cost": st.column_config.NumberColumn(tr("Transaction cost · Source units"), format="%.6g"),
                     })
