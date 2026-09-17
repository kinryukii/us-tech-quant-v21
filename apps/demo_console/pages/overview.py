"""Decision-first historical overview. All economics arrive through the model."""

from dataclasses import asdict
from pathlib import PureWindowsPath
import re

import streamlit as st

from apps.demo_console.components.pipeline_status import render_pipeline
from apps.demo_console.components.top20_table import render_holding_table, score_label
from apps.demo_console.models import DecisionOverview
from apps.demo_console.components.visuals import apply_style, header_html, section_header, text
from apps.demo_console.components.portfolio_summary import chips
from apps.demo_console.pages.history import open_security_history, render_history, sync_history_case
from apps.demo_console.pages.research import render_research
from apps.demo_console.pages.machine_learning import render_machine_learning
from apps.demo_console.components.motion import render_motion
from apps.demo_console.components.demo_tour import render_demo_tour
from apps.demo_console.components.decision_trace import remember_case, resolve_case_ticker, trace_facts
from apps.demo_console.components.ml_comparison import comparison_rows
from apps.demo_console.components.replay import pause_replay
from apps.demo_console.components.system_overview import render_system_overview
from apps.demo_console.i18n import option_labeler, tr


def _short(value: str | None) -> str:
    if not value:
        return tr("N/A")
    if re.match(r"^(?:[A-Za-z]:[\\/]|/)", value):
        value = PureWindowsPath(value).name
    text = re.sub(r"\b[0-9a-fA-F]{40,64}\b", lambda match: match.group(0)[:8] + "…", value)
    return text if len(text) <= 90 else text[:87] + "…"


def _render_provenance(model: DecisionOverview, *, presentation: bool, expanded: bool = False) -> None:
    provenance = model.provenance
    with st.expander(tr("Decision provenance"), expanded=expanded):
        facts = {
            "Decision date": provenance.decision_date,
            "Previous decision date": model.previous_decision_date,
            "Information as of": provenance.information_as_of,
            "Execution date / epoch": provenance.execution_date,
            "Universe identity": provenance.universe_identity,
            "Strategy / configuration": provenance.strategy_identity,
            "Configuration identity": provenance.config_identity,
            "Artifact producer": provenance.producer_identity,
            "Alpha implementation": provenance.alpha_implementation,
            "Replay / reconciliation": provenance.replay_identity,
        }
        st.dataframe(
            [{tr("Field"): tr(label), tr("Value"): _short(value) if presentation else value or tr("N/A")}
             for label, value in facts.items()],
            hide_index=True,
            width="stretch",
        )
        st.markdown(f'**{tr("Artifact sources")}**')
        if provenance.artifact_sources:
            for source in provenance.artifact_sources:
                st.text(PureWindowsPath(source).name if presentation else source)
        else:
            st.caption(tr("Not exposed by current artifact"))
        if provenance.artifact_hashes:
            st.markdown(f'**{tr("Artifact identities")}**')
            for source, digest in provenance.artifact_hashes:
                st.text(f"{PureWindowsPath(source).name}: {_short(digest)}" if presentation
                        else f"{source}: {digest}")
        if not presentation:
            st.markdown(f'**{tr("Full provenance / raw metadata")}**')
            st.json(asdict(provenance))
            if model.debug_error:
                st.code(model.debug_error, language="text")


def _switch_portfolio_workspace() -> None:
    view = st.session_state.get("portfolio_workspace")
    if view in ("Portfolio", "History"):
        pause_replay()
        st.session_state["workspace"] = view


def _portfolio_rows(model: DecisionOverview, source: str, group: str, query: str):
    rows = model.ranking if source == "Raw A2 Top20" else model.holdings
    members = model.retained if group == "Retained" else model.entered if group == "Entered" else None
    filtered = tuple(row for row in rows if query in row.ticker.casefold()
                     and (group == "All names" or members is not None and row.ticker in members))
    return rows, members, filtered


def _current_portfolio_rows(model: DecisionOverview):
    return _portfolio_rows(model, st.session_state.get("record_set", "Raw A2 Top20"),
                           st.session_state.get("membership_filter", "All names"),
                           st.session_state.get("ticker_search", "").strip().casefold())[2]


def _remember_portfolio_security(current_tickers: tuple[str, ...]) -> None:
    if st.session_state.get("inspect_ticker") in current_tickers:
        remember_case("inspect_ticker")


def _prepare_portfolio_case(model: DecisionOverview) -> None:
    """Resolve the visible inspector before the shared case header is rendered."""
    tickers = tuple(row.ticker for row in _current_portfolio_rows(model))
    canonical = resolve_case_ticker(model)
    selected = st.session_state.get("inspect_ticker")
    entering = st.session_state.get("_rendered_workspace") != "Portfolio"
    changed = st.session_state.get("_research_case_ticker") != st.session_state.get("_portfolio_seen_case")
    if canonical in tickers and (entering or changed):
        selected = canonical
    elif selected not in tickers:
        selected = next(iter(tickers), None)
    if st.session_state.get("inspect_ticker") != selected:
        st.session_state["inspect_ticker"] = selected
    _remember_portfolio_security(tuple(row.ticker for row in comparison_rows(model)))
    st.session_state["_portfolio_seen_case"] = st.session_state.get("_research_case_ticker")


def _render_inspector(model: DecisionOverview, ticker: str) -> None:
    ranked = next((row for row in model.ranking if row.ticker == ticker), None)
    held = next((row for row in model.holdings if row.ticker == ticker), None)
    previous = ranked.held_before if ranked is not None else held.held_before if held else None
    status = ("Entered" if model.entered is not None and ticker in model.entered else
              "Retained" if model.retained is not None and ticker in model.retained else "Not exposed")
    rank = ranked.rank if ranked else None
    score = score_label(ranked.score) if ranked else None
    delta = f"{ranked.rank_change:+d}" if ranked and ranked.rank_change is not None else None
    trace = trace_facts(model, ticker)
    subsequent = trace["held_after"] if trace is not None else True if held is not None else None
    facts = (("Subsequent holding", tr("Yes") if subsequent is True else tr("No") if subsequent is False else None),
             ("Recorded rank", rank), ("Model score", score), ("Rank change", delta),
             ("Previous holding", tr("Yes") if previous else tr("No") if previous is False else None),
             ("Snapshot change", tr(status)))
    st.html(f'<div class="uq-inspector-symbol">{text(ticker)}</div>'
            '<dl class="uq-facts">' + ''.join(f'<div><dt>{text(tr(label))}</dt><dd>{text(tr("N/A") if value is None else value)}</dd></div>'
                                            for label, value in facts) + '</dl>'
            f'<p class="uq-panel-note">{text(tr("Score is the recorded model output. Snapshot changes describe holdings differences, not trading instructions."))}</p>')


def _render_portfolio(model: DecisionOverview) -> None:
    st.html(section_header(tr("Explore portfolio records"), tr("SECURITY WORKSPACE"),
                           tr("{ranked} ranked / {held} held", ranked=len(model.ranking), held=len(model.holdings))))
    controls = st.columns([1.25, 1, 1.2], gap="medium")
    with controls[0]:
        query = st.text_input(tr("Search ticker"), placeholder=tr("Find a symbol…"), key="ticker_search",
                              persist_state="session").strip().casefold()
    with controls[1]:
        source = st.selectbox(tr("Record set"), ["Raw A2 Top20", "Historical holdings"], key="record_set",
                              format_func=option_labeler(["Raw A2 Top20", "Historical holdings"]), persist_state="session")
    with controls[2]:
        group = st.selectbox(tr("Snapshot membership"), ["All names", "Retained", "Entered"], key="membership_filter",
                             format_func=option_labeler(["All names", "Retained", "Entered"]), persist_state="session")
    rows, members, filtered = _portfolio_rows(model, source, group, query)
    inspector, table = st.columns([1, 2.25], gap="medium")
    with table:
        st.caption(tr("{count} of {total} records · {record_set} · {date}", count=len(filtered), total=len(rows),
                      record_set=tr(source), date=model.decision_date or tr("N/A")))
        if group != "All names" and members is None:
            st.info(tr("Snapshot membership is not exposed for this date."))
        elif not filtered:
            st.info(tr("No records match these filters. Clear the ticker search or choose All names."))
        render_holding_table(filtered, key="portfolio_records")
    with inspector:
        with st.container(key="uq_inspector"):
            st.html(section_header(tr("Security detail"), tr("RECORD INSPECTOR")))
            if filtered:
                ticker = st.selectbox(tr("Inspect ticker"), [row.ticker for row in filtered], index=None,
                                      key="inspect_ticker", persist_state="session",
                                      on_change=_remember_portfolio_security,
                                      args=(tuple(row.ticker for row in comparison_rows(model)),))
                _render_inspector(model, ticker)
                st.button(tr("View security history ↗"), on_click=open_security_history, args=(ticker,),
                          key="open_security_history", width="stretch")
            else:
                st.caption(tr("Select a matching record to inspect its recorded fields."))
    with st.expander(tr("Compare all holdings across snapshots"), expanded=False):
        st.caption(f'{model.previous_decision_date or tr("N/A")} → {model.decision_date or tr("N/A")}')
        for label, values in (("Previous holdings", model.previous_holdings), ("Retained", model.retained),
                              ("Entered", model.entered), ("Exited", model.exited)):
            st.markdown(f"**{tr(label)}**")
            st.html(chips(values))


def _render_coverage(model: DecisionOverview) -> None:
    with st.expander(tr("Coverage & limitations"), expanded=True):
        for label, value in (("Raw A2 proposed changes", model.raw_proposed_changes),
                             ("RX accepted changes", model.rx_accepted_changes),
                             ("RX prevented changes", model.rx_prevented_changes)):
            st.write(f'{tr(label)}: {tr("N/A") if value is None else value}')
        st.caption(tr("N/A = not exposed by the current artifact. Ranking alone is not a trade decision."))
        for limitation in model.limitations:
            st.write(tr(limitation))


def _render_evidence(model: DecisionOverview, *, presentation: bool) -> None:
    st.html('<section class="uq-panel">' + section_header(tr("Snapshot timeline"), tr("EVIDENCE CHAIN"))
            + '<div class="uq-date-flow">' + ''.join(
                f'<div><span>{text(tr(label))}</span><strong>{text(tr("N/A") if value is None else value)}</strong></div>'
                for label, value in (("Information as of", model.provenance.information_as_of),
                                     ("Decision date", model.decision_date),
                                     ("Subsequent execution", model.provenance.execution_date)))
            + '</div><p class="uq-panel-note">'
            + text(tr("Holdings and turnover describe subsequent historical replay execution. AVAILABLE indicates readable evidence; PASS applies only to the stated validation scope."))
            + '</p></section>')
    coverage, details = st.columns([1, 1.7], gap="medium")
    with coverage:
        render_pipeline(model.pipeline, presentation=presentation)
    with details:
        _render_provenance(model, presentation=presentation, expanded=True)
        _render_coverage(model)


def case_context_html(model: DecisionOverview, view: str) -> str:
    """A compact cross-page identity from the current recorded case, without reads."""
    ticker = st.session_state.get("inspect_ticker") if view == "Portfolio" else resolve_case_ticker(model)
    if view == "Portfolio" and (model.error or ticker not in {row.ticker for row in _current_portfolio_rows(model)}):
        return ""
    facts = trace_facts(model, ticker) if ticker is not None else None
    if facts is None:
        if view == "Portfolio" and ticker is not None:
            return ('<div class="uq-case-context"><span class="uq-case-identity"><small>'
                    + text(tr("Security detail")) + '</small><strong>' + text(ticker) + '</strong></span>'
                    + '<span class="uq-case-date"><small>' + text(tr("Decision date")) + '</small><b>'
                    + text(model.decision_date or tr("Not recorded")) + '</b></span>'
                    + '<span class="uq-case-scope">' + text(tr("No unambiguous current Top20 record")) + '</span></div>')
        return ""
    dates = (("Decision date", facts["decision_date"]), ("Execution date", facts["execution_date"]))
    return ('<div class="uq-case-context"><span class="uq-case-identity"><small>'
            + text(tr("Recorded case")) + '</small><strong>' + text(facts["ticker"]) + '</strong></span>'
            + ''.join('<span class="uq-case-date"><small>' + text(tr(label)) + '</small><b>'
                      + text(value if value is not None else tr("Not recorded")) + '</b></span>' for label, value in dates)
            + ('<span class="uq-case-scope">' + text(tr("Portfolio context")) + '</span>' if view == "Research" else '')
            + '</div>')


def render_overview(model: DecisionOverview, *, presentation: bool = True, view: str = "Overview") -> None:
    from apps.demo_console.components.recorded_2026 import is_recorded_2026, render_research_period

    apply_style(presentation=presentation)
    st.html(header_html(model, view))
    if view == "Research":
        render_research_period()
    recorded_2026 = is_recorded_2026(view)
    if view == "History":
        sync_history_case(model)
    elif view == "Portfolio":
        _prepare_portfolio_case(model)
    if not recorded_2026:
        render_demo_tour(model, view)
    if view not in ("Overview", "History") and not recorded_2026:
        context = case_context_html(model, view)
        if context:
            st.html(context)
    if view in ("Portfolio", "History"):
        if st.session_state.get("portfolio_workspace") != view:
            st.session_state["portfolio_workspace"] = view
        labels = {"Portfolio": tr("Holdings"), "History": tr("Historical replay")}
        with st.container(key="uq_portfolio_navigation"):
            st.segmented_control(tr("Decisions & portfolio"), ("Portfolio", "History"),
                key="portfolio_workspace", format_func=labels.__getitem__, required=True,
                on_change=_switch_portfolio_workspace, persist_state="session",
                label_visibility="collapsed", width="content")
    if model.error and not recorded_2026:
        st.error(tr(model.error))
    if view == "Machine learning":
        render_machine_learning(model, presentation=presentation)
    elif view == "Portfolio":
        _render_portfolio(model)
    elif view == "Evidence":
        _render_evidence(model, presentation=presentation)
    elif view == "History":
        render_history(model, presentation=presentation)
    elif view == "Research":
        render_research(model, presentation=presentation)
    else:
        render_system_overview(model, presentation=presentation)
    if not recorded_2026:
        st.html(f'<div class="uq-scope-strip"><b>{text(tr("RAW A2 BASELINE"))}</b><span class="uq-scope-copy">'
                f'{text(tr("Recorded historical portfolio · Stateful RX trace and combined final portfolio"))} '
                f'<strong>{text(tr("NOT EXPOSED"))}</strong></span></div>')
    if view != "Evidence" and not recorded_2026:
        _render_provenance(model, presentation=presentation)
    st.html('<footer class="uq-footer"><span>US TECH QUANT <span class="uq-separator">/</span> '
            f'{text(tr("RESEARCH TERMINAL"))}</span><span>{text(tr("FROZEN HISTORICAL ARTIFACTS · READ ONLY"))}</span></footer>')
    if st.session_state.get("_rendered_workspace") != view:
        st.session_state["_rendered_workspace"] = view
        # Only a workspace change resets the presentation. Date, filter and
        # chart interactions retain their scroll position. No source text enters JS.
        st.html('<script>requestAnimationFrame(() => {'
                'document.querySelector(\'[data-testid="stMain"]\')?.scrollTo({top:0,behavior:"instant"});'
                '});</script>', unsafe_allow_javascript=True)
    render_motion(view, model.decision_date, enabled=st.session_state.get("motion_enabled", True))
