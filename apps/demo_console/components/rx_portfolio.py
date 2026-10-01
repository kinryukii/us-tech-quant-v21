"""Separate RX decisions and simulated holdings within the existing portfolio page."""
from __future__ import annotations

import streamlit as st

from apps.demo_console.adapters import rx_research_reader
from apps.demo_console.components.visuals import section_header
from apps.demo_console.i18n import tr


def render_rx_portfolio(model, *, presentation=True):
    view = rx_research_reader.read(model)
    st.html(section_header(tr("A2 + RX · Selection and execution"), tr("RX OVERLAY")))
    if view.error:
        st.info(tr(view.error))
        if not presentation and view.debug_error:
            st.caption(view.debug_error)
        from apps.demo_console.components.selection_price_path import render_selection_price_path
        render_selection_price_path(model, view)
        return
    row = view.calendar
    executed = row["execution_status"] == "EXECUTED"
    st.caption(tr(rx_research_reader.LIMITATION))
    st.caption(tr("Signal {signal} · Performance through {cutoff}", signal=model.decision_date,
                  cutoff=view.history.effective_end_date or "—"))
    if not executed:
        st.info(tr("RX selection is recorded; its next-open execution is pending. These names are not an executed holding snapshot.")
            if row["execution_status"] == "PENDING_NEXT_OPEN" else tr("RX execution is blocked by missing verified price inputs."))
    selection, actual = st.columns([1.25, 1], gap="medium")
    with selection:
        st.markdown("**" + tr("RX selected names") + "**")
        st.dataframe([{"rank": item["candidate_rank"], "ticker": item["ticker"],
                       "raw_rank": item["raw_rank"], "candidate_score": item["candidate_score"]}
                      for item in view.selections], hide_index=True, width="stretch", key="rx_selections",
            column_config={"rank": st.column_config.NumberColumn(tr("Rank"), format="%d"),
                "ticker": tr("Ticker"), "raw_rank": tr("Raw A2 rank"),
                "candidate_score": st.column_config.NumberColumn(tr("RX selection score"), format="%.4f")})
    with actual:
        st.markdown("**" + tr("RX executed holdings") + "**")
        if executed:
            st.caption(tr("Executed at the {date} open.", date=str(row["execution_date"])[:10]))
            st.dataframe([{"ticker": item["ticker"], "weight": item["posttrade_weight"]}
                for item in view.holdings], hide_index=True, width="stretch", key="rx_holdings",
                column_config={"ticker": tr("Ticker"), "weight": st.column_config.NumberColumn(tr("Weight"), format="percent")})
        else:
            st.caption(tr("Next open pending") if row["execution_status"] == "PENDING_NEXT_OPEN" else tr("No executed RX holdings for this signal."))
            st.caption(tr("Scheduled execution: {date}", date=str(row.get("scheduled_execution_date") or "—")[:10]))
    with st.expander(tr("Why RX accepted or retained each replacement"), expanded=False):
        if view.decisions:
            st.dataframe([{"incumbent": item["incumbent_ticker"], "entrant": item["entrant_ticker"],
                "margin": item["score_margin"], "required": item["required_margin"],
                "decision": tr("Replace") if item["replacement_decision"] == "REPLACE" else tr("Retain")}
                for item in view.decisions], hide_index=True, width="stretch", key="rx_decisions",
                column_config={"incumbent": tr("Incumbent"), "entrant": tr("Proposed entrant"),
                    "margin": tr("Score margin"), "required": tr("Required margin"), "decision": tr("RX decision")})
        else:
            st.caption(tr("No replacement pair was proposed for this signal."))
        st.caption(tr("A replacement is a selection decision. Only the engine's verified trades establish a buy or sale."))
    from apps.demo_console.components.selection_price_path import render_selection_price_path
    render_selection_price_path(model, view)
