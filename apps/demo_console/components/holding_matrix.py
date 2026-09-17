"""A bounded view of recorded holdings for the current, unmodified Top20 order."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
import json

import altair as alt
import streamlit as st

from apps.demo_console.components.history_charts import security_records
from apps.demo_console.components.visuals import section_header
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.i18n import tr
from apps.demo_console.models import DecisionOverview

_SELECTION = "holding_matrix_row"
_STATES = ("Held", "Not held", "Unavailable")


def _tickers(tickers: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ticker for ticker in tickers
                               if isinstance(ticker, str) and ticker))[:20]


def matrix_records(history: tuple[DecisionOverview, ...], tickers: Sequence[str]) -> list[dict]:
    """Retain raw identifiers and tri-state membership, without adding dates.

    The caller supplies the already bounded history window. This component only
    takes its last 60 snapshots, and never follows ``available_dates`` elsewhere.
    Availability is shared with the existing security history, including its
    distinction between a missing portfolio and a verified absent security.
    """
    window = tuple(sorted((snapshot for snapshot in history if snapshot.decision_date),
                          key=lambda snapshot: snapshot.decision_date)[-60:])
    records = []
    for ticker in _tickers(tickers):
        for row in security_records(window, ticker):
            held = row["held"]
            records.append({"decision_date": row["decision_date"],
                            "execution_date": row["execution_date"],
                            "ticker": ticker, "held": held,
                            "state": "Held" if held is True else
                                     "Not held" if held is False else "Unavailable"})
    return records


def matrix_chart(history: tuple[DecisionOverview, ...], tickers: Sequence[str],
                 focused_ticker: str | None = None):
    """Draw every supplied membership cell; selection never filters the data."""
    symbols = _tickers(tickers)
    records = [{**row, "state_label": tr(row["state"]),
                "execution_label": row["execution_date"] or tr("Not recorded")}
               for row in matrix_records(history, symbols)]
    dates = list(dict.fromkeys(row["decision_date"] for row in records))
    count = min(len(dates), 6)
    ticks = ([dates[round(i * (len(dates) - 1) / (count - 1))] for i in range(count)]
             if count > 1 else dates)
    label_expr = ("substring(datum.label, 0, 7)" if len({day[:4] for day in dates}) > 1
                  else "substring(datum.label, 5)")
    # Streamlit 1.63 otherwise appends all encoding channels even with fields
    # supplied, making fieldless opacity/tooltip channels invalid projections.
    selection = alt.selection_point(name=_SELECTION, fields=["ticker"], encodings=[],
                                    on="click", clear="dblclick", toggle=False)
    opacity = (alt.condition(alt.datum.ticker == focused_ticker,
                             alt.value(1.0), alt.value(.65))
               if focused_ticker in symbols else alt.value(1.0))
    chart = (alt.Chart(alt.Data(values=records))
             .mark_rect(cornerRadius=2, stroke="#11151e", strokeWidth=1, cursor="pointer")
             .encode(
                 x=alt.X("decision_date:O", title=tr("Decision date"), sort=dates,
                         scale=alt.Scale(domain=dates, paddingInner=.06),
                         axis=alt.Axis(values=ticks, labelExpr=label_expr, labelAngle=0)),
                 y=alt.Y("ticker:N", title=None, sort=list(symbols),
                         scale=alt.Scale(domain=list(symbols), paddingInner=.08)),
                 color=alt.Color("state:N", title=None,
                                 scale=alt.Scale(domain=list(_STATES),
                                                 range=["#739bff", "#1b2535", "#8f9db3"]),
                                 legend=alt.Legend(orient="top", direction="horizontal",
                                                  symbolType="square", labelExpr=json.dumps(
                                                      {state: tr(state) for state in _STATES},
                                                      ensure_ascii=True) + "[datum.label]")),
                 opacity=opacity,
                 tooltip=[alt.Tooltip("ticker:N", title=tr("Security")),
                          alt.Tooltip("decision_date:N", title=tr("Decision date")),
                          alt.Tooltip("execution_label:N", title=tr("Subsequent execution date")),
                          alt.Tooltip("state_label:N", title=tr("Holdings state"))],
             ).add_params(selection)
             # Keep row room plus the date title and membership legend even
             # for one row. fit includes both within the fullscreen frame.
             .properties(height=max(20, len(symbols) * 20) + 125, background="#11151e",
                         autosize=alt.AutoSizeParams(type="fit", contains="padding"))
             .configure_view(stroke=None)
             .configure_axis(labelColor="#9aa6ba", titleColor="#c5cfdf",
                             labelFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif",
                             titleFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif",
                             labelFontSize=13, titleFontSize=13, titleFontWeight="normal",
                             titlePadding=12, labelPadding=7, grid=False, domain=False, ticks=False)
             .configure_legend(labelColor="#9aa6ba", labelFontSize=13,
                               labelFont="Segoe UI, Microsoft YaHei, Yu Gothic UI, sans-serif"))
    return chart


def _selected_ticker(event, tickers: Sequence[str]) -> str | None:
    """Validate the native point-selection payload, including clear events."""
    if not isinstance(event, Mapping) or not isinstance(event.get("selection"), Mapping):
        return None
    rows = event["selection"].get(_SELECTION)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    ticker = rows[0].get("ticker")
    return ticker if isinstance(ticker, str) and ticker in _tickers(tickers) else None


def _select_row(tickers: tuple[str, ...], key: str) -> None:
    # Streamlit calls this before widgets are recreated. Render never reapplies
    # the persistent event state, so a later manual ticker choice takes priority.
    if st.session_state.get("_holding_matrix_key") != key:
        return
    ticker = _selected_ticker(st.session_state.get(key), tickers)
    if ticker is not None:
        st.session_state["_history_focus"] = ticker
        st.session_state["history_ticker"] = ticker


def render_holding_matrix(history: tuple[DecisionOverview, ...], tickers: Sequence[str]) -> None:
    symbols = _tickers(tickers)
    records = matrix_records(history, symbols)
    st.html(section_header(tr("Current Top20 · Historical holdings"), tr("RECORDED MEMBERSHIP")))
    if not records:
        st.session_state["_holding_matrix_key"] = None
        st.info(tr("No current Top20 securities or recorded snapshots are available for this matrix."))
        return
    focused = st.session_state.get("history_ticker")
    if focused not in symbols:
        focused = None
    # A manual focus/window change gets a fresh native selection store. This
    # also lets the user click a previously selected row again immediately.
    context = (symbols, tuple(dict.fromkeys(row["decision_date"] for row in records)), focused)
    if st.session_state.get("_holding_matrix_context") != context:
        st.session_state["_holding_matrix_revision"] = st.session_state.get("_holding_matrix_revision", 0) + 1
        st.session_state["_holding_matrix_context"] = context
    key = f'history_holding_matrix_{st.session_state["_holding_matrix_revision"]}'
    st.session_state["_holding_matrix_key"] = key
    render_chart(matrix_chart(history, symbols, focused), width="stretch", theme=None,
                    key=key, on_select=partial(_select_row, symbols, key),
                    selection_mode=[_SELECTION])
    st.caption(tr("Rows follow the current Top20's recorded order. At most the latest 60 snapshots in this window are shown. Cells describe holdings at the subsequent execution. Click a row to inspect that security."))
    st.caption(tr("Unavailable means the portfolio could not be verified; it does not mean the security was not held."))
