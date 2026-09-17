"""Describe recorded simulation frictions without estimating live execution skill."""
from __future__ import annotations

from datetime import date
from math import fsum, isfinite
from statistics import median

import altair as alt
import streamlit as st

from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import tr
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.models import PerformancePoint

_FLAGS = (("stale_mark_count", "Days with stale marks"),
          ("skipped_buy_count", "Days with skipped buys"),
          ("blocked_rebalance_count", "Days with blocked sells or rebalances"),
          ("buy_cash_scale", "Days with buy scale below 1"))


def _number(value, *, integer=False, positive=False, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value < 0 or (positive and value == 0)
            or (integer and int(value) != value) or (maximum is not None and value > maximum)):
        return None
    return value


def execution_records(points: tuple[PerformancePoint, ...]) -> list[dict]:
    """Keep every supplied execution; unavailable fields remain None, never zero."""
    dates = tuple(point.execution_date for point in points)
    try:
        valid = all(date.fromisoformat(day).isoformat() == day for day in dates)
    except (TypeError, ValueError):
        valid = False
    if not valid or dates != tuple(sorted(set(dates))):
        raise ValueError("Execution dates must be unique, ascending ISO dates.")
    records = []
    for point in points:
        nav, cash = _number(point.nav, positive=True), _number(point.cash)
        share = cash / nav if cash is not None and nav is not None else None
        records.append({
            "execution_date": point.execution_date, "nav": nav, "cash": cash,
            "cash_share": share if share is not None and isfinite(share) and share <= 1 else None,
            "turnover": _number(point.turnover), "transaction_cost": _number(point.transaction_cost),
            "stale_mark_count": _number(point.stale_mark_count, integer=True),
            "skipped_buy_count": _number(point.skipped_buy_count, integer=True),
            "blocked_rebalance_count": _number(point.blocked_rebalance_count, integer=True),
            "buy_cash_scale": _number(point.buy_cash_scale, maximum=1),
        })
    return records


def _range(records, field):
    values = [row[field] for row in records if row[field] is not None]
    return {"minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "median": median(values) if values else None,
            "last": records[-1][field] if records else None,
            "observations": len(values)}


def summarize_execution(points: tuple[PerformancePoint, ...]) -> dict:
    records = execution_records(points)
    events = []
    for field, label in _FLAGS:
        values = [row[field] for row in records if row[field] is not None]
        events.append({"field": field, "label": label, "observations": len(values),
                       "days": (sum(value < 1 if field == "buy_cash_scale" else value > 0
                                    for value in values) if values else None)})
    costs = [row["transaction_cost"] for row in records if row["transaction_cost"] is not None]
    return {"observations": len(records), "events": events,
            "cash_share": _range(records, "cash_share"), "turnover": _range(records, "turnover"),
            "cost_observations": len(costs),
            "total_cost": fsum(costs) if records and len(costs) == len(records) else None}


def _percent(value):
    return tr("N/A") if value is None else f"{value:.2%}"


def turnover_chart(points: tuple[PerformancePoint, ...]):
    records = [{**row, "cash_share_label": _percent(row["cash_share"])}
               for row in execution_records(points)]
    dates = [row["execution_date"] for row in records]
    count = min(6, len(dates))
    ticks = ([dates[round(i * (len(dates) - 1) / (count - 1))] for i in range(count)]
             if count > 1 else dates)
    expression = ("substring(datum.label, 0, 7)" if len({day[:4] for day in dates}) > 1
                  else "substring(datum.label, 5)")
    maximum = max((row["turnover"] for row in records if row["turnover"] is not None), default=0)
    return (alt.Chart(alt.Data(values=records)).mark_bar(color="#739bff", opacity=.85)
            .encode(x=alt.X("execution_date:O", title=tr("Execution date"), sort=dates,
                            scale=alt.Scale(domain=dates),
                            axis=alt.Axis(values=ticks, labelExpr=expression, labelAngle=0)),
                    y=alt.Y("turnover:Q", title=tr("Executed turnover"), stack=None,
                            scale=alt.Scale(domain=[0, maximum * 1.05 or .01]),
                            axis=alt.Axis(format=".3~p", tickCount=3)),
                    tooltip=[alt.Tooltip("execution_date:N", title=tr("Execution date")),
                             alt.Tooltip("turnover:Q", title=tr("Executed turnover"), format=".2%"),
                             alt.Tooltip("cash_share_label:N", title=tr("Cash / NAV"))])
            # This is the full frame height, including both translated axes.
            .properties(height=260, background="#11151e",
                        autosize=alt.AutoSizeParams(type="fit", contains="padding"))
            .configure_view(stroke=None)
            .configure_axis(labelColor="#9aa6ba", titleColor="#c5cfdf", gridColor="#252e3d", gridWidth=.7,
                            domain=False, ticks=False, labelFontSize=13, titleFontSize=13,
                            labelFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif",
                            titleFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif",
                            titleFontWeight="normal", titlePadding=10))


def render_execution_quality(points: tuple[PerformancePoint, ...], *, initial_nav: float = 1.0) -> None:
    if _number(initial_nav, positive=True) is None:
        raise ValueError("Source initial NAV must be finite and positive.")
    summary = summarize_execution(points)
    st.html(section_header(tr("Execution frictions"), tr("SIMULATED EXECUTION")))
    if not points:
        st.info(tr("No recorded executions are available in this window."))
        return
    cards = []
    for item in summary["events"]:
        value = tr("N/A") if item["days"] is None else str(item["days"])
        note = tr("{known} / {total} days with this field recorded",
                  known=item["observations"], total=summary["observations"])
        cards.append(f'<div class="uq-metric"><div class="uq-metric-label">{text(tr(item["label"]))}</div>'
                     f'<div class="uq-metric-value">{text(value)}</div>'
                     f'<div class="uq-metric-note">{text(note)}</div></div>')
    st.html('<div class="uq-metrics">' + ''.join(cards) + '</div>')
    st.caption(tr("Counts are days with a nonzero recorded flag, or a buy cash scale below 1. Zero means no such event was recorded; it does not establish live execution quality."))
    cash, turnover = st.columns([1, 1.8], gap="large")
    with cash:
        values = summary["cash_share"]
        cash_range = (tr("N/A") if values["minimum"] is None else
                      f'{_percent(values["minimum"])} – {_percent(values["maximum"])}')
        facts = (("Cash / NAV range", cash_range),
                 ("Cash / NAV at window end", _percent(values["last"])),
                 ("Median executed turnover", _percent(summary["turnover"]["median"])),
                 ("Recorded transaction costs", tr("N/A") if summary["total_cost"] is None else
                  f'{summary["total_cost"]:.6g}'))
        st.html('<dl class="uq-facts">' + ''.join(
            f'<div><dt>{text(tr(label))}</dt><dd>{text(value)}</dd></div>' for label, value in facts) + '</dl>')
        st.caption(tr("Cash / NAV: {cash} / {total} recorded days. Turnover: {turnover} / {total}. Costs: {costs} / {total}.",
                      cash=values["observations"], total=summary["observations"],
                      turnover=summary["turnover"]["observations"], costs=summary["cost_observations"]))
    with turnover:
        render_chart(turnover_chart(points), width="stretch", theme=None, key="research_execution_turnover")
    st.caption(tr("Amounts retain the source capital unit (initial NAV = {initial_nav}), even in a shorter window. Costs are recorded simulation amounts, not percentages or live account currency.",
                  initial_nav=f"{initial_nav:g}"))
    with st.expander(tr("Inspect daily execution records"), expanded=False):
        st.caption(tr("Buy cash scale is the recorded fraction of requested buy notional financed after cash and fees. A value below 1 can reflect ordinary fee funding; it is not by itself an execution failure."))
        st.dataframe([{
            tr("Execution date"): row["execution_date"], tr("Stale mark count"): row["stale_mark_count"],
            tr("Skipped buy count"): row["skipped_buy_count"],
            tr("Blocked sell or rebalance count"): row["blocked_rebalance_count"],
            tr("Buy cash scale"): row["buy_cash_scale"], tr("Cash / NAV"): _percent(row["cash_share"]),
            tr("Executed turnover"): _percent(row["turnover"]),
            tr("Cash · Source units"): row["cash"], tr("NAV · Source units"): row["nav"],
            tr("Transaction cost · Source units"): row["transaction_cost"],
        } for row in reversed(execution_records(points))], hide_index=True, width="stretch",
            key="research_execution_records")
