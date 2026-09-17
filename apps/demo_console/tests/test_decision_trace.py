"""Synthetic decision joins and native selections; no external data reads."""
from dataclasses import replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from apps.demo_console.components import decision_trace
from apps.demo_console.components.decision_trace import trace_facts, trace_html
from apps.demo_console.models import DecisionOverview, HoldingRow, Provenance


def _model():
    return DecisionOverview(
        decision_date="2025-06-03", eligible_universe_count=91,
        ranking=(HoldingRow(2, "B", score=0.0, held_before=False),
                 HoldingRow(1, "A", score=-0.0025, held_before=True)),
        holdings=(HoldingRow(None, "B"), HoldingRow(None, "OUTSIDE")),
        previous_holdings=("A",), previous_decision_date="2025-06-02",
        provenance=Provenance(information_as_of="2025-06-03", execution_date="2025-06-04"))


def test_exact_dates_score_and_memberships_preserve_distinct_layers():
    model = _model()
    a, b = trace_facts(model, "A"), trace_facts(model, "B")
    assert a["rank"] == 1 and a["score"] == -0.0025
    assert a["held_before"] is True and a["held_after"] is False
    assert b["score"] == 0.0 and b["held_before"] is False and b["held_after"] is True
    assert (a["overlap_count"], a["ranked_count"], a["holdings_count"]) == (1, 2, 2)
    assert a["information_date"] == a["decision_date"] == "2025-06-03"
    assert a["execution_date"] == "2025-06-04"
    assert trace_facts(model, "OUTSIDE") is None
    assert trace_facts(replace(model, error="unverified"), "A") is None


def test_unavailable_portfolio_and_nonfinite_outputs_are_not_zero_filled():
    model = DecisionOverview(ranking=(HoldingRow(None, "A", score=float("nan")),))
    facts = trace_facts(model, "A")
    for field in ("rank", "score", "universe_count", "held_before", "held_after", "overlap_count",
                  "holdings_count", "information_date", "decision_date", "execution_date", "previous_decision_date"):
        assert facts[field] is None
    assert "Not recorded" in trace_html(facts)
    assert "nan" not in trace_html(facts)


def test_before_membership_handles_empty_previous_snapshot_and_conflicts():
    unknown = DecisionOverview(ranking=(HoldingRow(1, "A"),))
    assert trace_facts(unknown, "A")["held_before"] is None
    assert trace_facts(replace(unknown, previous_holdings=()), "A")["held_before"] is False
    conflict = replace(_model(), previous_holdings=("B",))
    assert trace_facts(conflict, "A")["held_before"] is None
    assert trace_facts(conflict, "B")["held_before"] is None
    first = replace(_model(), previous_holdings=None, previous_decision_date=None)
    assert trace_facts(first, "A")["held_before"] is True


def test_duplicate_tickers_are_ambiguous_and_all_html_values_are_escaped():
    assert trace_facts(DecisionOverview(ranking=(HoldingRow(1, "A"), HoldingRow(2, "A"))), "A") is None
    ticker = '<img src=x onerror="bad">'
    model = DecisionOverview(ranking=(HoldingRow(1, ticker, score=0.1),),
                             provenance=Provenance(information_as_of="<script>bad</script>"))
    html = trace_html(trace_facts(model, ticker))
    assert "<img" not in html and "<script>" not in html
    assert "&lt;img" in html and "&lt;script&gt;" in html


def test_case_resolution_is_read_only_and_uses_current_ranks_not_outcomes(monkeypatch):
    state = {"_research_case_ticker": "B", "ml_engine_ticker": "A", "decision_date": "2025-06-03"}
    monkeypatch.setattr(decision_trace.st, "session_state", state)
    original = dict(state)
    assert decision_trace.resolve_case_ticker(_model()) == "B"
    assert state == original
    state["_research_case_ticker"] = "OUTSIDE"
    assert decision_trace.resolve_case_ticker(_model()) == "A"
    state["ml_engine_ticker"] = "STALE"
    # A's original rank is first even though B appears first in the input and
    # has a numerically higher score. Neither score nor holdings picks the case.
    assert decision_trace.resolve_case_ticker(_model()) == "A"
    assert decision_trace.resolve_case_ticker(replace(_model(), error="unverified")) is None
    assert decision_trace.resolve_case_ticker(DecisionOverview()) is None
    duplicate = replace(_model(), ranking=(HoldingRow(1, "B"), HoldingRow(2, "B")))
    assert decision_trace.resolve_case_ticker(duplicate) is None


def test_remember_and_navigation_carry_have_distinct_writes_and_keep_the_cutoff(monkeypatch):
    state = {"selection": "B", "ml_engine_ticker": "A", "decision_date": "2025-06-03", "language": "ja"}
    monkeypatch.setattr(decision_trace.st, "session_state", state)
    decision_trace.remember_case("selection")
    assert state == {"selection": "B", "ml_engine_ticker": "A", "decision_date": "2025-06-03",
                     "language": "ja", "_research_case_ticker": "B"}
    decision_trace.carry_case(decision_trace.resolve_case_ticker(_model()))
    assert all(state[key] == "B" for key in (
        "_research_case_ticker", "ml_engine_ticker", "ml_trace_ticker", "ml_primary", "inspect_ticker",
        "history_ticker", "_history_focus", "system_focus_ticker"))
    assert state["decision_date"] == "2025-06-03" and state["language"] == "ja"
    original = dict(state)
    for invalid in (None, "", " ", False, 1):
        decision_trace.carry_case(invalid)
    decision_trace.remember_case("missing")
    assert state == original


def _app():
    import streamlit as st
    from dataclasses import replace
    from apps.demo_console.components.decision_trace import render_decision_trace
    from apps.demo_console.i18n import language_scope
    from apps.demo_console.tests.test_decision_trace import _model

    language = st.selectbox("Language", ("en", "zh", "ja"), key="language")
    show = st.checkbox("Show trace", value=True, key="show")
    remove = st.checkbox("Remove B", key="remove")
    failed = st.checkbox("Reader failed", key="failed")
    model = _model()
    if remove:
        model = replace(model, ranking=tuple(row for row in model.ranking if row.ticker != "B"))
    if failed:
        model = replace(model, error="synthetic error")
    if show:
        with language_scope(language):
            render_decision_trace(model)


def test_selection_survives_three_languages_and_section_cleanup():
    app = AppTest.from_file(str(Path(__file__)), default_timeout=10).run()
    assert not app.exception
    assert app.selectbox(key="ml_trace_ticker").value == "A"
    app.selectbox(key="ml_trace_ticker").select("B").run()
    assert app.session_state["_research_case_ticker"] == "B"
    for language in ("zh", "ja", "en"):
        app.selectbox(key="language").select(language).run()
        assert not app.exception
        assert app.selectbox(key="ml_trace_ticker").value == "B"
    app.checkbox(key="show").uncheck().run()
    app.checkbox(key="show").check().run()
    assert app.selectbox(key="ml_trace_ticker").value == "B"
    app.checkbox(key="remove").check().run()
    assert not app.exception
    assert app.selectbox(key="ml_trace_ticker").value == "A"
    app.checkbox(key="failed").check().run()
    assert not app.exception
    assert len(app.selectbox) == 1
    assert len(app.info) == 1
    assert not any("uq-trace-chain" in element.proto.body for element in app.get("html"))


if __name__ == "__main__":
    _app()
