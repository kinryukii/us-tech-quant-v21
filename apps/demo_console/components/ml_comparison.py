"""Compare two recorded Top20 outputs; no model loading or inferred explanations."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from math import isfinite

import altair as alt
import streamlit as st

from apps.demo_console.adapters import decision_reader
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.history_charts import (
    _recorded_domain, _style, _x, security_records,
)
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import option_labeler, tr
from apps.demo_console.models import DecisionOverview, HoldingRow

_WINDOWS = {"20 snapshots": 20, "60 snapshots": 60}
_METRICS = {"Recorded rank": "rank", "Model score": "score"}
_COLORS = ["#235c48", "#997045"]


def _score(value):
    return value if (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and isfinite(value)) else None


def _rank(value):
    return value if (isinstance(value, int) and not isinstance(value, bool)
                     and 1 <= value <= 20) else None


def comparison_rows(model: DecisionOverview) -> tuple[HoldingRow, ...]:
    """Preserve missing coordinates and exclude ambiguous duplicate identities."""
    if model.error:
        return ()
    counts = Counter(row.ticker for row in model.ranking)
    rows = (replace(row, rank=_rank(row.rank), score=_score(row.score))
            for row in model.ranking if row.ticker and counts[row.ticker] == 1)
    return tuple(sorted(rows, key=lambda row: (row.rank is None, row.rank or 0, row.ticker)))


def selection_pair(rows, primary=None, secondary=None) -> tuple[str | None, str | None]:
    """Resolve stale selections within this snapshot, keeping the pair distinct."""
    tickers = tuple(row.ticker for row in rows)
    first = primary if primary in tickers else next(iter(tickers), None)
    others = tuple(ticker for ticker in tickers if ticker != first)
    second = secondary if secondary in others else next(iter(others), None)
    return first, second


def comparison_delta(primary: HoldingRow, secondary: HoldingRow) -> dict:
    """Signed primary-minus-comparison differences, retaining unknown values."""
    values = {}
    for field, clean in (("rank", _rank), ("score", _score)):
        first, second = clean(getattr(primary, field)), clean(getattr(secondary, field))
        difference = first - second if first is not None and second is not None else None
        values[field] = _score(difference)
    return values


def comparison_history(history, primary: str, secondary: str) -> list[dict]:
    """Reuse the existing recorded-history semantics, including missing-run boundaries."""
    if primary == secondary:
        raise ValueError("A comparison requires two different securities.")
    return [{**record, "ticker": ticker,
             "ranking_label": tr(record["ranking_status"]),
             "score_label": (format(record["score"], ".6g")
                             if record["score"] is not None else tr("Not recorded"))}
            for ticker in (primary, secondary)
            for record in security_records(history, ticker)]


def comparison_chart(history, primary: str, secondary: str, metric="rank"):
    """Overlay actual coordinates with explicit domains and disconnected missing runs."""
    if metric not in {"rank", "score"}:
        raise ValueError("Comparison metric must be rank or score.")
    records = comparison_history(history, primary, secondary)
    y = (alt.Y("rank:Q", title=tr("Top20 rank · 1 is highest"),
               scale=alt.Scale(domain=[20, 1], zero=False),
               axis=alt.Axis(values=[1, 5, 10, 15, 20], format="d"))
         if metric == "rank" else
         alt.Y("score:Q", title=tr("Recorded model score"),
               scale=alt.Scale(domain=_recorded_domain(records, "score", zero=False), zero=False),
               axis=alt.Axis(format=".3~g", tickCount=4)
               if any(row["score"] is not None for row in records) else None))
    chart = (alt.Chart(alt.Data(values=records))
             .transform_filter(alt.FieldValidPredicate(field=metric, valid=True))
             .mark_line(strokeWidth=2.5, point={"filled": True, "size": 44})
             .encode(
                 x=_x(records), y=y,
                 color=alt.Color("ticker:N", title=None,
                                 scale=alt.Scale(domain=[primary, secondary], range=_COLORS),
                                 legend=alt.Legend(orient="top", direction="horizontal", title=None)),
                 strokeDash=alt.StrokeDash("ticker:N",
                                          scale=alt.Scale(domain=[primary, secondary],
                                                          range=[[1, 0], [5, 3]])),
                 detail=f"{metric}_segment:N",
                 tooltip=[alt.Tooltip("ticker:N", title=tr("Ticker")),
                          alt.Tooltip("decision_date:N", title=tr("Decision date")),
                          alt.Tooltip("rank:Q", title=tr("Recorded rank"), format="d"),
                          alt.Tooltip("score_label:N", title=tr("Recorded score")),
                          alt.Tooltip("ranking_label:N", title=tr("Ranking evidence"))],
             ))
    # Both ticker channels share one visible legend. Hiding the dash legend
    # would also suppress the merged color legend in the installed runtime.
    return _style(chart, height=250)


def matchup_header(ticker: str, role: str, *, secondary=False) -> str:
    tone = "secondary" if secondary else "primary"
    return (f'<div class="uq-ml-matchup uq-ml-matchup-{tone}">'
            f'<span>{text(tr(role))}</span><strong>{text(ticker)}</strong></div>')


def _value(value, *, signed=False) -> str:
    return (format(value, "+.6g" if signed else ".6g")
            if value is not None else tr("Not recorded"))


def _remember_primary_case() -> None:
    # Decision trace imports comparison_rows; defer this shared callback import.
    from apps.demo_console.components.decision_trace import remember_case
    remember_case("ml_primary")


def render_model_comparison(model: DecisionOverview, presentation=True) -> None:
    """Render an inspectable pair and a cutoff-limited history from the existing reader."""
    rows = comparison_rows(model)
    if len(rows) < 2:
        st.info(tr("Two distinct recorded Top20 securities are required for comparison."))
        return
    # Native section changes bypass the engine's action callback. Resolve the
    # shared case here as well, before constructing the primary selector.
    from apps.demo_console.components.decision_trace import resolve_case_ticker
    by_ticker = {row.ticker: row for row in rows}
    primary, secondary = selection_pair(
        rows, resolve_case_ticker(model), st.session_state.get("ml_secondary"))
    st.session_state["ml_primary"] = primary
    st.html(section_header(tr("Compare model outputs"), tr("SAME MODEL · SAME DECISION DATE"),
                           model.decision_date or tr("Not recorded")))
    first_col, second_col = st.columns(2, gap="medium")
    with first_col:
        primary = st.selectbox(tr("Primary security"), list(by_ticker), index=None,
                               key="ml_primary", persist_state="session",
                               on_change=_remember_primary_case)
    # A new primary can invalidate the comparison. Repair before its widget exists.
    primary, secondary = selection_pair(rows, primary, secondary)
    st.session_state["ml_secondary"] = secondary
    with second_col:
        secondary = st.selectbox(tr("Comparison security"),
                                 [ticker for ticker in by_ticker if ticker != primary],
                                 index=None, key="ml_secondary", persist_state="session")
    if primary not in by_ticker or secondary not in by_ticker or primary == secondary:
        st.info(tr("Two distinct recorded Top20 securities are required for comparison."))
        return
    for column, ticker, role, is_second in (
            (first_col, primary, "Primary security", False),
            (second_col, secondary, "Comparison security", True)):
        row = by_ticker[ticker]
        with column:
            with st.container(border=True):
                st.html(matchup_header(ticker, role, secondary=is_second))
                with st.container(horizontal=True):
                    st.metric(tr("Recorded rank"), f"#{row.rank}" if row.rank is not None else tr("Not recorded"))
                    st.metric(tr("Recorded score"), _value(row.score))
    difference = comparison_delta(by_ticker[primary], by_ticker[secondary])
    with st.container(horizontal=True):
        st.metric(tr("Rank difference · primary − comparison"), _value(difference["rank"], signed=True), border=True)
        st.metric(tr("Score difference · primary − comparison"), _value(difference["score"], signed=True), border=True)
    st.caption(tr("Rank 1 is highest. Scores are recorded model outputs, not probabilities, expected returns or portfolio weights."))
    if not model.decision_date:
        return
    window_col, metric_col = st.columns(2, gap="medium")
    with window_col:
        if st.session_state.get("ml_history_window") not in _WINDOWS:
            st.session_state["ml_history_window"] = "20 snapshots"
        window = st.selectbox(tr("Comparison history"), list(_WINDOWS), index=None,
                              key="ml_history_window", format_func=option_labeler(_WINDOWS),
                              persist_state="session")
    with metric_col:
        if st.session_state.get("ml_history_metric") not in _METRICS:
            st.session_state["ml_history_metric"] = "Recorded rank"
        metric = st.segmented_control(tr("Trajectory metric"), list(_METRICS), required=True,
                                      key="ml_history_metric", format_func=option_labeler(_METRICS),
                                      persist_state="session")
    metric = metric if metric in _METRICS else "Recorded rank"
    window = window if window in _WINDOWS else "20 snapshots"
    with st.spinner(tr("Loading verified historical snapshots…")):
        history = decision_reader.load_history(model.decision_date, window=_WINDOWS[window])
    if not history or all(snapshot.error for snapshot in history):
        st.info(tr("Comparison history is unavailable. The current recorded pair remains visible."))
        return
    render_chart(comparison_chart(history, primary, secondary, _METRICS[metric]),
                 width="stretch", height=300 if presentation else 270,
                 theme=None, key="ml_comparison_chart")
    st.caption(tr("Recorded Top20 history through {date}. Gaps mean outside Top20 or unavailable evidence; no rank or score is filled in.",
                  date=model.decision_date))
    st.caption(tr("This pair is selected from the current decision date's Top20. Its historical paths describe these names; they do not measure full-universe predictive skill."))
