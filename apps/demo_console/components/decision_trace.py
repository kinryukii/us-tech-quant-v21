"""Follow one recorded decision; no inferred reasons, trades or new source reads."""
from __future__ import annotations

import streamlit as st

from apps.demo_console.components.ml_comparison import comparison_rows
from apps.demo_console.components.top20_table import score_label
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import tr
from apps.demo_console.models import DecisionOverview


_CASE_SELECTION_KEYS = ("ml_engine_ticker", "ml_trace_ticker", "ml_primary", "inspect_ticker",
                        "history_ticker", "_history_focus", "system_focus_ticker")


def resolve_case_ticker(model: DecisionOverview) -> str | None:
    """Read the current case only from unambiguous, currently recorded names."""
    tickers = tuple(row.ticker for row in comparison_rows(model))
    for key in ("_research_case_ticker", *_CASE_SELECTION_KEYS):
        selected = st.session_state.get(key)
        if isinstance(selected, str) and selected in tickers:
            return selected
    return next(iter(tickers), None)


def remember_case(widget_key: str) -> None:
    """Remember a native security selection without changing any other widget."""
    ticker = st.session_state.get(widget_key)
    if isinstance(ticker, str) and ticker.strip():
        st.session_state["_research_case_ticker"] = ticker


def carry_case(ticker: str | None) -> None:
    """Navigation only: carry a caller-validated case; never change the date."""
    if isinstance(ticker, str) and ticker.strip():
        for key in ("_research_case_ticker", *_CASE_SELECTION_KEYS):
            st.session_state[key] = ticker


def trace_facts(model: DecisionOverview, ticker: str) -> dict | None:
    """Join existing display records, keeping unknown membership distinct from false."""
    rows = comparison_rows(model)
    selected = next((row for row in rows if row.ticker == ticker), None)
    if selected is None:
        return None
    before = selected.held_before if isinstance(selected.held_before, bool) else None
    if model.previous_holdings is not None:
        previous = ticker in model.previous_holdings
        before = previous if before is None else before if before == previous else None
    held = {row.ticker for row in model.holdings}
    ranked = {row.ticker for row in rows}
    count = model.eligible_universe_count
    return {
        "ticker": ticker, "rank": selected.rank, "score": selected.score,
        "universe_count": count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None,
        "held_before": before, "held_after": ticker in held if held else None,
        "overlap_count": len(ranked & held) if held else None,
        "ranked_count": len(ranked), "holdings_count": len(held) if held else None,
        "information_date": model.provenance.information_as_of,
        "decision_date": model.decision_date,
        "execution_date": model.provenance.execution_date,
        "previous_decision_date": model.previous_decision_date,
    }


def _display(value) -> str:
    return text(tr("Not recorded") if value is None else value)


def _membership(value: bool | None) -> str:
    source = "Held" if value is True else "Not held" if value is False else "Not recorded"
    return text(tr(source))


def trace_html(facts: dict, *, presentation: bool = True) -> str:
    """Escaped, connected factual cards, with dates kept at their recorded precision."""
    dates = (("Information as of", facts["information_date"]),
             ("Decision date", facts["decision_date"]),
             ("Subsequent execution date", facts["execution_date"]))
    rank = f'#{facts["rank"]}' if facts["rank"] is not None else None
    score = score_label(facts["score"])
    count = f'{facts["universe_count"]:,}' if facts["universe_count"] is not None else None
    return ('<section class="uq-trace ' + ('uq-trace-presentation' if presentation else '') + '">'
            '<div class="uq-trace-identity"><span class="uq-eyebrow">' + text(tr("ONE RECORDED DECISION"))
            + '</span><strong>' + text(facts["ticker"]) + '</strong><span>'
            + text(tr("Original records · No inference rerun")) + '</span></div>'
            '<ol class="uq-trace-chain"><li><span class="uq-trace-step">01</span><h3>'
            + text(tr("Eligible universe")) + '</h3><strong class="uq-trace-value">' + _display(count)
            + '</strong><p>' + text(tr("Producer-reported eligible names for this decision."))
            + '</p><small>' + text(tr("The per-stock eligibility audit is not loaded here.")) + '</small></li>'
            '<li><span class="uq-trace-step">02</span><h3>' + text(tr("Model output"))
            + '</h3><div class="uq-trace-output"><div><span>' + text(tr("Recorded rank"))
            + '</span><strong>' + _display(rank) + '</strong></div><div><span>'
            + text(tr("Recorded score")) + '</span><strong>' + _display(score) + '</strong></div></div><p>'
            + text(tr("Original Top20 rank and model score, without recalculation.")) + '</p></li>'
            '<li><span class="uq-trace-step">03</span><h3>' + text(tr("Portfolio membership"))
            + '</h3><div class="uq-trace-membership"><div><span>' + text(tr("Before execution"))
            + '</span><strong>' + _membership(facts["held_before"]) + '</strong></div>'
            '<span class="uq-trace-arrow" aria-hidden="true">→</span><div><span>'
            + text(tr("After execution")) + '</span><strong>' + _membership(facts["held_after"])
            + '</strong></div></div><p>' + text(tr("Membership in the recorded Raw A2 portfolio.")) + '</p></li></ol>'
            '<div class="uq-trace-dates">' + ''.join(
                '<div><span>' + text(tr(label)) + '</span><strong>' + _display(value) + '</strong></div>'
                for label, value in dates) + '</div></section>')


def render_decision_trace(model: DecisionOverview, presentation: bool = True) -> None:
    """Inspect one Top20 name through the already assembled decision snapshot."""
    rows = comparison_rows(model)
    st.html(section_header(tr("Decision trace"), tr("FOLLOW ONE SECURITY")))
    if not rows:
        st.info(tr("A verified Top20 record is required to inspect a decision trace."))
        return
    tickers = tuple(row.ticker for row in rows)
    st.session_state["ml_trace_ticker"] = resolve_case_ticker(model)
    ticker = st.selectbox(tr("Security to trace"), tickers, index=None,
                          key="ml_trace_ticker", persist_state="session",
                          on_change=remember_case, args=("ml_trace_ticker",))
    facts = trace_facts(model, ticker)
    if facts is None:
        st.info(tr("A verified Top20 record is required to inspect a decision trace."))
        return
    st.html(trace_html(facts, presentation=presentation))
    if facts["overlap_count"] is not None:
        st.html('<div class="uq-trace-overlap"><span>'
                + text(tr("Ranked names in subsequent holdings")) + '</span><strong>'
                + text(f'{facts["overlap_count"]} / {facts["ranked_count"]}') + '</strong><small>'
                + text(tr("{held} distinct recorded holdings · Set overlap only", held=facts["holdings_count"]))
                + '</small></div>')
    else:
        st.caption(tr("Subsequent holdings are unavailable; membership and set overlap remain unknown."))
    st.caption(tr("This is a linked sequence of records, not a causal explanation. Ranking selection does not establish execution or risk approval; RX decisions and feature contributions are not exposed."))
    with st.expander(tr("How to read this trace")):
        st.write(tr("The universe count describes the producer’s eligible set. A Top20 score describes a model output. Holdings describe the portfolio record after the associated execution. Each is a different layer of evidence."))
        st.caption(tr("Before-execution membership uses the recorded flag or a consistent previous portfolio snapshot. Missing or conflicting records remain unknown."))
        st.caption(tr("Previous decision snapshot · {date}", date=facts["previous_decision_date"] or tr("Not recorded")))
        st.caption(tr("Dates retain the precision supplied by the current reader. No intraday information-availability timestamp is inferred."))
