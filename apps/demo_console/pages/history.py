"""Historical replay and security trajectories over verified recorded snapshots."""
import streamlit as st

from apps.demo_console.adapters import decision_reader
from apps.demo_console.components.history_charts import portfolio_chart, security_chart, security_records
from apps.demo_console.components.holding_matrix import render_holding_matrix
from apps.demo_console.components.localized_tabs import localized_tabs
from apps.demo_console.components import replay
from apps.demo_console.components.top20_table import score_label
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.decision_trace import remember_case, resolve_case_ticker, trace_facts
from apps.demo_console.components.ml_comparison import comparison_rows
from apps.demo_console.models import DecisionOverview
from apps.demo_console.i18n import option_labeler, tr


_WINDOWS = {"20 snapshots": 20, "60 snapshots": 60, "120 snapshots": 120, "All available": None}


def open_security_history(ticker: str) -> None:
    """A button callback runs before the next rendering of the global navigation."""
    st.session_state["_history_focus"] = ticker
    st.session_state["_history_explicit_focus"] = ticker
    st.session_state["workspace"] = "History"


def _select_replay_date() -> None:
    replay.reset_replay()
    st.session_state["decision_date"] = st.session_state["replay_date"]


def _remember_security(current_tickers: tuple[str, ...]) -> None:
    st.session_state["_history_focus"] = st.session_state["history_ticker"]
    st.session_state["_history_explicit_focus"] = st.session_state["history_ticker"]
    if st.session_state["history_ticker"] in current_tickers:
        remember_case("history_ticker")


def sync_history_case(model: DecisionOverview) -> None:
    """Reconcile navigation before tour controls; preserve local historical exploration."""
    current_tickers = tuple(row.ticker for row in comparison_rows(model))
    canonical = resolve_case_ticker(model)
    focus = st.session_state.get("_history_focus")
    explicit = st.session_state.pop("_history_explicit_focus", None)
    previous_focus = st.session_state.get("_history_seen_focus")
    local_change = previous_focus is not None and focus != previous_focus
    case_changed = st.session_state.get("_research_case_ticker") != st.session_state.get("_history_seen_case")
    if isinstance(explicit, str) and explicit:
        focus = explicit
    elif not local_change and (case_changed or not focus):
        # Returning from a read-only visit is not a security selection. In
        # particular, the current Top20 fallback must not replace an older
        # security deliberately being explored during historical replay.
        focus = canonical or focus
    if isinstance(focus, str) and focus:
        st.session_state["_history_focus"] = focus
        if focus in current_tickers:
            st.session_state["history_ticker"] = focus
            remember_case("history_ticker")
    st.session_state["_history_seen_focus"] = focus
    st.session_state["_history_seen_case"] = st.session_state.get("_research_case_ticker")


def history_case_context_html(model: DecisionOverview, ticker: str, start: str, end: str) -> str:
    """Describe the actual history focus; an outside name gets no current trace facts."""
    facts = trace_facts(model, ticker)
    dates = (("Decision date", facts["decision_date"]), ("Execution date", facts["execution_date"])) if facts else (
        ("Replay date", model.decision_date),)
    if facts is None:
        dates = (*dates, ("Observation window", f"{start} → {end}"))
    return ('<div class="uq-case-context"><span class="uq-case-identity"><small>'
            + text(tr("Recorded case" if facts else "Historical exploration")) + '</small><strong>'
            + text(ticker) + '</strong></span>' + ''.join(
                '<span class="uq-case-date"><small>' + text(tr(label)) + '</small><b>'
                + text(value if value is not None else tr("Not recorded")) + '</b></span>' for label, value in dates)
            + ('<span class="uq-case-scope">' + text(tr("No unambiguous current Top20 record")) + '</span>' if not facts else '')
            + '</div>')


def _render_security_summary(records: list[dict], ticker: str) -> None:
    last = records[-1]
    observed = sum(row["rank"] is not None for row in records)
    held = sum(row["held"] is True for row in records)
    known_holdings = sum(row["held"] is not None for row in records)
    rank = str(last["rank"]) if last["rank"] is not None else tr(last["ranking_status"])
    facts = ((tr("Latest recorded rank"), rank),
             (tr("Latest model score"), score_label(last["score"]) or tr("Not exposed")),
             (tr("Top20 observations"), tr("{observed} / {total} snapshots", observed=observed, total=len(records))),
             (tr("Held observations"), tr("{held} / {known} verified snapshots", held=held, known=known_holdings)))
    st.html('<div class="uq-history-security-summary">'
            f'<div><strong>{text(ticker)}</strong><span>{text(tr(last["status"]))} · {text(last["decision_date"])}</span></div>'
            '<dl>' + ''.join(f'<div><dt>{text(label)}</dt><dd>{text(value)}</dd></div>'
                            for label, value in facts) + '</dl></div>')


def render_history(model: DecisionOverview, *, presentation: bool) -> None:
    case_context = st.empty()
    if not model.available_dates or model.error:
        replay.pause_replay()
        st.info(tr("Historical replay requires a verified decision snapshot."))
        return
    replay.sync_replay_context("History", model.decision_date)
    replay.restore_replay_window()
    # Only the callback changes the global date. A sidebar change updates this
    # separate slider key before its widget is instantiated on the next run.
    if st.session_state.get("replay_date") != model.decision_date:
        st.session_state["replay_date"] = model.decision_date
    window_col, date_col, ticker_col = st.columns([1, 2, 1.3], gap="medium")
    with window_col:
        if "history_window" in st.session_state and st.session_state["history_window"] not in _WINDOWS:
            st.session_state["history_window"] = "60 snapshots"
        window_label = st.selectbox(tr("History window"), list(_WINDOWS),
                                    index=None if "history_window" in st.session_state else 1,
                                    key="history_window", format_func=option_labeler(_WINDOWS),
                                    on_change=replay.reset_replay)
    with date_col:
        st.select_slider(tr("Replay date"), options=model.available_dates, value=None,
                         key="replay_date", on_change=_select_replay_date,
                         help=tr("All history charts end at this recorded decision date."))
    replay.render_replay_controls(model.available_dates, model.decision_date,
                                  window_label, _WINDOWS[window_label])
    locked_dates = replay.visible_replay_dates(model.decision_date, window_label)
    with st.spinner(tr("Loading verified historical snapshots…")):
        # A replay reveals its locked start through the current frame. Asking
        # for the original window size at frame one would expose older dates.
        history = decision_reader.load_history(
            model.decision_date, window=len(locked_dates) if locked_dates else _WINDOWS[window_label])
    if locked_dates:
        history = tuple(snapshot for snapshot in history if snapshot.decision_date in locked_dates)
    if not history:
        replay.pause_replay()
        st.info(tr("No recorded historical snapshots are available for this selection."))
        return
    errors = [snapshot for snapshot in history if snapshot.error]
    if len(errors) == len(history):
        replay.pause_replay()
        st.error(tr("Historical records could not be verified. The current snapshot remains available in Overview."))
        if not presentation:
            for snapshot in errors:
                st.code(snapshot.debug_error or tr(snapshot.error), language="text")
        return
    symbols = sorted({row.ticker for snapshot in history for row in (*snapshot.ranking, *snapshot.holdings)})
    requested = st.session_state.get("_history_focus")
    if not requested:
        requested = model.ranking[0].ticker if model.ranking else symbols[0] if symbols else None
        if requested:
            st.session_state["_history_focus"] = requested
    if requested and requested not in symbols:
        symbols.append(requested)
        symbols.sort()
    if not symbols:
        replay.pause_replay()
        st.info(tr("No securities are exposed in this historical window."))
        return
    if st.session_state.get("history_ticker") not in symbols or st.session_state.get("history_ticker") != requested:
        st.session_state["history_ticker"] = requested or symbols[0]
    with ticker_col:
        ticker = st.selectbox(tr("Security history"), symbols, index=None, key="history_ticker",
                              on_change=_remember_security,
                              args=(tuple(row.ticker for row in comparison_rows(model)),))
    st.session_state["_history_seen_focus"] = ticker
    case_context.html(history_case_context_html(model, ticker, history[0].decision_date, history[-1].decision_date))
    st.html(f'<div class="uq-history-range"><span>{text(tr("OBSERVATION WINDOW"))}</span>'
            f'<strong>{text(history[0].decision_date)} → {text(history[-1].decision_date)}</strong>'
            f'<span>{text(tr("{count} recorded snapshots · Ends at selected decision date", count=len(history)))}</span></div>')
    unavailable = sum(not snapshot.holdings for snapshot in history)
    if errors or unavailable:
        st.warning(tr("Coverage gaps: {ranking} ranking snapshot(s), {portfolio} portfolio snapshot(s) unavailable. Charts preserve missing observations.",
                      ranking=len(errors), portfolio=unavailable))
    records = security_records(history, ticker)
    _render_security_summary(records, ticker)
    security, portfolio = st.columns([1, 1], gap="medium")
    with portfolio:
        with st.container(key="uq_history_portfolio"):
            st.html(section_header(tr("Portfolio evolution"), tr("ACROSS RECORDED SNAPSHOTS")))
            changes_tab, turnover_tab = localized_tabs(["Entries & exits", "Executed turnover"], key="history_portfolio_tabs")
            with changes_tab:
                render_chart(portfolio_chart(history, "changes"), width="stretch", height=290,
                                theme=None, key="history_changes_chart")
            with turnover_tab:
                render_chart(portfolio_chart(history, "turnover"), width="stretch", height=290,
                                theme=None, key="history_turnover_chart")
            st.caption(tr("Holdings changes and turnover describe subsequent replay execution. They are not RX actions or decision-time inputs."))
    with security:
        with st.container(key="uq_history_security"):
            st.html(section_header(tr("{ticker} · Security trajectory", ticker=ticker), tr("ORIGINAL RECORDS"), tr("Rank 1 is highest")))
            rank_tab, score_tab = localized_tabs(["Rank & holdings", "Model score"], key="history_security_tabs")
            with rank_tab:
                render_chart(security_chart(history, ticker, "rank"), width="stretch", height=290,
                                theme=None, key="history_rank_chart")
            with score_tab:
                render_chart(security_chart(history, ticker, "score"), width="stretch", height=290,
                                theme=None, key="history_score_chart")
            st.caption(tr("A missing Top20 rank is left blank. Model scores are not returns, probabilities or portfolio weights."))
    with st.container(key="uq_holding_matrix"):
        render_holding_matrix(history, tuple(row.ticker for row in model.ranking))
    snapshots_tab, security_tab = localized_tabs(
        ["Snapshot log", "{ticker} · Recorded observations"], key="history_log_tabs",
        format_func=lambda source: tr(source, ticker=ticker))
    with snapshots_tab:
        st.caption(tr("Most recent first · Select a replay date above to inspect the corresponding portfolio in Overview."))
        st.dataframe([{
            tr("Decision date"): snapshot.decision_date,
            tr("Execution date"): snapshot.provenance.execution_date,
            tr("Entered"): len(snapshot.entered) if snapshot.entered is not None else None,
            tr("Exited"): len(snapshot.exited) if snapshot.exited is not None else None,
            tr("Retained"): len(snapshot.retained) if snapshot.retained is not None else None,
            tr("Executed turnover"): f"{snapshot.turnover:.2%}" if snapshot.turnover is not None else None,
            tr("Coverage"): tr("Ranking unavailable" if snapshot.error else "Portfolio unavailable" if not snapshot.holdings else "Recorded"),
        } for snapshot in reversed(history)], width="stretch", hide_index=True, height=330, key="snapshot_history_table")
    with security_tab:
        st.caption(tr("Outside Top20 means no rank was recorded in that selection. Symbols are displayed as recorded; historical issuer identities are not reconstructed."))
        st.dataframe([{
            tr("Decision date"): row["decision_date"], tr("Execution date"): row["execution_date"],
            tr("Recorded rank"): row["rank"], tr("Model score"): score_label(row["score"]),
            tr("Ranking coverage"): tr(row["ranking_status"]), tr("Holdings status"): tr(row["status"]),
        } for row in reversed(records)], width="stretch", hide_index=True, height=330, key="security_history_table")
    replay.render_replay_timer()
