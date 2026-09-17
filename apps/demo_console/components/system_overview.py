"""A case-led presentation of inspected records and the existing frozen replay.

This is editorial navigation, not a component registry or a health monitor.
Engineering descriptions refer to reviewed source; adoption and current run
status are not inferred. Economic observations arrive through DecisionOverview.
"""
from dataclasses import dataclass
from collections.abc import Mapping
from functools import partial

import streamlit as st

from apps.demo_console.components.demo_tour import start_guided_tour
from apps.demo_console.components.pit_timing import render_pit_timing
from apps.demo_console.components.replay import pause_replay
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.adapters.performance_reader import read_performance
from apps.demo_console.components.performance_stats import summarize_performance
from apps.demo_console.components.performance_charts import wealth_chart, drawdown_chart
from apps.demo_console.components.chart_display import render_chart
from apps.demo_console.components.top20_table import score_label
from apps.demo_console.components.decision_trace import trace_facts, resolve_case_ticker, remember_case, carry_case
from apps.demo_console.components.ml_comparison import comparison_rows
from apps.demo_console.i18n import option_labeler, tr


@dataclass(frozen=True)
class Capability:
    title: str
    question: str
    mechanism: str
    evidence: str
    scope: str
    references: tuple[tuple[str, str], ...]
    replay: bool = False


CAPABILITIES = (
    Capability("Information timing", "Was this information available at the decision time?",
        "Disclosure timestamps carry a timezone and are checked against the signal cutoff. A later filing waits for a permitted session; missing timestamps are rejected.",
        "Inspect the existing timing functions in the synthetic reliability drill.",
        "This demonstrates one implemented timing rule. It does not validate the complete historical information chain.",
        (("13F disclosure timing primitives", "scripts/v22/pit_13f_reconstruction_r1.py :: accepted_utc / filing_is_public_for_signal / first_legal_signal_session"),)),
    Capability("Model lineage", "Which model and training boundary produced the recorded output?",
        "The verified freeze binds the feature schema, HGB configuration and yearly training and label-maturity boundaries to the recorded model identity.",
        "Inspect the feature definitions, annual vintages and original same-date ranks and scores in the learning studio.",
        "Historical stage models were not persisted. Inspect recorded model identity where available; local attribution and full-universe predictive quality are not established here.",
        (("Verified learning metadata", "apps/demo_console/adapters/system_status_reader.py :: learning_profile"),
         ("Frozen-model producer reference", "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py :: stage_rows / build_stock_state_features")), True),
    Capability("Execution mechanics", "What happens when a trade cannot execute as planned?",
        "The inspected simulator handles missing opening prices, stale valuation marks and sell-before-buy cash flow. Recorded fees constrain buy capacity; negative cash and implicit leverage are rejected.",
        "The historical execution ledger separately exposes the frozen replay's costs, cash, turnover and recorded simulation flags.",
        "The source mechanism and the historical ledger have distinct identities. This page does not claim the current source version produced the selected replay, or that RX decisions are available.",
        (("Portfolio execution and accounting", "scripts/v22/abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py :: execution_eligibility_policy / calculate_weight_rebalance / simulate_portfolio"),
         ("Frozen execution reader", "apps/demo_console/adapters/performance_reader.py"))),
    Capability("Risk inspection", "How did the recorded portfolio behave during setbacks?",
        "Inspect net and gross paths alongside every drawdown episode, recovery status, transaction costs and return concentration, through the selected execution only.",
        "A chronological episode explorer keeps unrecovered periods visible. When available, the fixed A control provides a same-study comparison with its own downside.",
        "Historical outcomes describe the portfolio path. They do not prove a deployed risk controller, independent alpha or future recovery times.",
        (("Validated performance and cutoff", "apps/demo_console/adapters/performance_reader.py"),
         ("Drawdown episodes on original coordinates", "apps/demo_console/components/drawdown_episodes.py :: analyze_drawdown_episodes / episode_chart")), True),
    Capability("Research discipline", "Can a renamed trial hide an old failure?",
        "Registry entry points resolve aliases and specification fingerprints, flag duplicate or closed branches, and bind trial completion receipts to identities. Failure counts cannot be silently reduced.",
        "The inspected registry and lifecycle have paired synthetic checks for duplicate proposals, closed-branch repackaging, failure counts and terminal receipts.",
        "These are entry-point mechanisms. The current accepted registry head, complete trial history and repository-wide enforcement are not audited in this display.",
        (("Research identity and duplicate checks", "research_registry.py :: evaluate_proposal / resolve_alias / apply_patch"),
         ("Trial lifecycle and completion receipts", "prospective_research_lifecycle.py :: evaluate_start_decision / validate_completion_receipt / apply_registry_completion"))),
    Capability("Storage separation", "How are source code, data and evidence kept apart?",
        "The storage configuration separates the code repository from data, results, caches, daily state, backtests and environments. The resolver rejects overlapping roots and repository-bound outputs.",
        "Code and control stay lightweight; input data, retained evidence and rebuildable outputs have separate configured destinations.",
        "Routing checks are not operating-system access controls. Read-only data policy and evidence retention remain separate protections.",
        (("Canonical storage configuration", "config/storage_paths.json"),
         ("Storage root validation", "scripts/common/storage_paths.py :: resolve / validate / assert_path_outside_repo"))),
)


def open_capability(workspace, *, section=None, research_tab=None):
    pause_replay()
    st.session_state["workspace"] = workspace
    if workspace == "Research":
        st.session_state["research_period"] = "Historical research"
    if section:
        st.session_state["ml_section"] = section
    if research_tab:
        st.session_state["_localized_tabs:research_tabs"] = research_tab


def overview_facts(model):
    """Evidence counts, not maturity scores or model-performance claims."""
    if model.error:
        return (None, None, None)
    return (len(model.available_dates) or None,
            len(model.learning.feature_columns) or None,
            len(model.learning.vintages) or None)


def system_hero_html(model):
    """Explain the workspace using only evidence exposed by the current snapshot."""
    usable = not model.error
    profile = model.learning
    if (usable and profile.feature_columns and profile.parameters
            and profile.source_fingerprint and model.provenance.config_identity):
        learning = tr("Frozen configuration · {count} feature definitions", count=len(profile.feature_columns))
    elif comparison_rows(model):
        learning = tr("Recorded model outputs · metadata incomplete")
    else:
        learning = tr("Model evidence unavailable")
    portfolio = tr("Recorded holdings linked to execution" if usable and model.holdings
                   and model.provenance.execution_date else "Portfolio linkage unavailable")
    sources = set(model.provenance.artifact_sources)
    identities = {source for source, digest in model.provenance.artifact_hashes if source and digest}
    provenance = tr("Source files with recorded hashes" if usable and sources and sources <= identities
                    else "Source identity coverage is incomplete")
    capabilities = (("Learning model", learning), ("Portfolio evidence", portfolio),
                    ("Inspectable sources", provenance))
    return ('<section class="uq-system-purpose" aria-label="' + text(tr("Research workspace")) + '">'
            '<div class="uq-system-intro"><h2 class="uq-system-headline">'
            + text(tr("From models. To evidence.")) + '</h2><p class="uq-system-purpose-line">'
            + text(tr("A research workspace linking recorded model outputs, portfolio records and source evidence."))
            + '</p></div><div class="uq-system-capability-area"><ul class="uq-system-capabilities">' + ''.join(
                '<li class="uq-system-capability"><strong>' + text(tr(label)) + '</strong><span>'
                + text(detail) + '</span></li>' for label, detail in capabilities) + '</ul></div></section>')


def _percent(value, *, signed=False):
    return '—' if value is None else format(value, '+.2%' if signed else '.2%')


def _select_execution(dates, key):
    """A click inspects a supplied execution locally; it never changes the cutoff."""
    if st.session_state.get('_system_chart_key') != key:
        return
    event = st.session_state.get(key)
    selection = event.get('selection') if isinstance(event, Mapping) else None
    rows = selection.get('system_execution_pick') if isinstance(selection, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return
    selected = rows[0].get('inspection_date')
    if isinstance(selected, str) and selected in dates:
        st.session_state['system_inspect_execution'] = selected


def _result_context_html(summary, execution_cutoff):
    """Keep the recorded window and comparison basis beside the return values."""
    fee_basis = ('Both net paths include recorded execution fees.' if summary.reference_available
                 else 'Raw A2 includes recorded execution fees.')
    comparison = ('Same-study A control; not an independent alpha test.' if summary.reference_available
                  else 'Frozen A comparison unavailable.')
    return ('<div class="uq-result-context" role="note" title="'
            + text(tr('Selected execution cutoff: {date}', date=execution_cutoff))
            + '"><div class="uq-result-window"><span>'
            + text(tr('Recorded execution window')) + '</span><strong>'
            + text(f'{summary.start_date} → {summary.end_date}') + '</strong></div>'
            + '<div class="uq-result-basis"><span>' + text(tr('Fee basis')) + '</span><p>'
            + text(tr(fee_basis)) + '</p></div><div class="uq-result-comparison"><span>'
            + text(tr('Comparison scope')) + '</span><p>' + text(tr(comparison)) + '</p></div></div>')


def _research_metrics(summary):
    facts = (
        ('Net cumulative return', _percent(summary.net_total_return, signed=True), 'Raw A2 · Net', 'primary'),
        ('Frozen A control · Net', _percent(summary.reference_net_total_return, signed=True),
         'Same execution window' if summary.reference_available else 'Not recorded', ''),
        ('Maximum window drawdown', _percent(summary.max_drawdown.depth), 'From the running peak', 'adverse'),
        ('Gross–net return gap', '—' if summary.gross_net_difference_pp is None else f'{summary.gross_net_difference_pp:.2f} pp', 'Compounded gross minus net', ''),
    )
    return '<div class="uq-research-metrics">' + ''.join(
        '<div class="uq-research-metric ' + kind + '" title="' + text(tr(note)) + '"><span>' + text(tr(label))
        + '</span><strong>' + text(value) + '</strong><small>' + text(tr(note)) + '</small></div>'
        for label, value, note, kind in facts) + '</div>'


def _execution_html(point, wealth):
    facts = (
        ('Window drawdown', _percent(wealth.drawdown)),
        ('Cash / NAV', _percent(point.cash / point.nav)),
        ('Recorded turnover', _percent(point.turnover)),
        ('Historical holdings', str(point.holding_count)),
    )
    return ('<div class="uq-execution-return"><span>' + text(tr('Daily net return'))
            + '</span><strong class="' + ('uq-negative' if point.net_return < 0 else 'uq-positive') + '">'
            + text(_percent(point.net_return, signed=True)) + '</strong><small>'
            + text(tr('Frozen A control')) + ' ' + text(_percent(point.reference_net_return, signed=True))
            + '</small></div><dl class="uq-facts uq-execution-facts">' + ''.join(
                '<div><dt>' + text(tr(label)) + '</dt><dd>' + text(value) + '</dd></div>'
                for label, value in facts) + '</dl>')


def _render_research_canvas(model, *, presentation):
    if model.error or not model.provenance.execution_date:
        st.session_state['_system_chart_key'] = None
        st.info(tr('A verified execution record is needed to display the research canvas.'))
        return
    history = read_performance(model.provenance.execution_date)
    if history.error or not history.points:
        st.session_state['_system_chart_key'] = None
        st.info(tr('The performance path is unavailable. The recorded case remains available.'
                   if comparison_rows(model) else
                   'Frozen performance is unavailable. Check the source evidence in Debug mode.'))
        if not presentation and history.debug_error:
            st.code(history.debug_error, language='text')
        return
    # The canonical reader supplies verified, cutoff-limited observations.
    # The archive calendar is used only to retain coverage semantics.
    points = history.points
    if any(point.execution_date > model.provenance.execution_date for point in points):
        st.session_state['_system_chart_key'] = None
        st.error(tr('Performance observations exceed the selected execution cutoff.'))
        return
    summary = summarize_performance(points, initial_wealth=history.initial_nav,
                                    full_history_dates=history.available_dates)
    st.html(_result_context_html(summary, model.provenance.execution_date) + _research_metrics(summary))
    dates = tuple(point.execution_date for point in points)
    selected = st.session_state.get('system_inspect_execution')
    if selected not in dates:
        selected = dates[-1]
        st.session_state['system_inspect_execution'] = selected
    context = (model.decision_date, dates, selected)
    if st.session_state.get('_system_chart_context') != context:
        st.session_state['_system_chart_revision'] = st.session_state.get('_system_chart_revision', 0) + 1
        st.session_state['_system_chart_context'] = context
    key = f'system_performance_chart_{st.session_state["_system_chart_revision"]}'
    st.session_state['_system_chart_key'] = key
    canvas, inspector = st.columns([2.6, 1], gap='medium')
    with canvas, st.container(key='uq_research_canvas'):
        st.html(section_header(tr('Portfolio trajectory'), tr('RETURN & RISK'),
                               f'{summary.start_date} → {summary.end_date}'))
        chart = wealth_chart(summary, show_reference=True, show_gross=False,
                             inspect_selection='system_execution_pick', inspected_date=selected).properties(height=195)
        render_chart(chart, width='stretch', theme=None, key=key,
                     on_select=partial(_select_execution, dates, key), selection_mode=['system_execution_pick'])
    with inspector, st.container(key='uq_execution_inspector'):
        st.html(section_header(tr('Portfolio execution record'), tr('INSPECT RECORD')))
        selected = st.selectbox(tr('Execution to inspect'), dates, index=None, key='system_inspect_execution',
                                persist_state='session', label_visibility='collapsed')
        index = dates.index(selected)
        point = points[index]
        st.html(_execution_html(point, summary.wealth[index]))
        with st.popover(tr('Execution record details'), width='stretch'):
            st.caption(tr('Stale marks {stale} · Skipped buys {skipped} · Blocked rebalances {blocked}',
                          stale=point.stale_mark_count, skipped=point.skipped_buy_count,
                          blocked=point.blocked_rebalance_count))
            st.button(tr('Open the execution ledger'), key='system_ledger', width='stretch',
                      on_click=open_capability, args=('Research',), kwargs={'research_tab':'Execution frictions'})
    st.html('<div class="uq-canvas-caption"><span>' + text(tr('FROZEN REPLAY'))
            + '</span><p>' + text(tr('Click the curve to inspect a recorded day. The research cutoff stays fixed.'))
            + '</p><b>' + text(tr('{count} execution records', count=summary.observations)) + '</b></div>')
    if history.reference_error:
        st.caption(tr(history.reference_error))
    with st.expander(tr('Inspect the drawdown path'), expanded=False):
        render_chart(drawdown_chart(summary, compact=True), width='stretch', theme=None,
                     key='system_drawdown_chart')


def _open_selected_trace():
    ticker = st.session_state.get('system_focus_ticker')
    carry_case(ticker)
    open_capability('Machine learning', section='Decision trace')


def _open_selected_comparison(tickers):
    ticker = st.session_state.get('system_focus_ticker')
    if not isinstance(ticker, str) or ticker not in tickers:
        return
    carry_case(ticker)
    open_capability('Machine learning', section='Compare outputs')


def _start_case_walkthrough(tickers):
    ticker = st.session_state.get('system_focus_ticker')
    if ticker in tickers:
        carry_case(ticker)
    start_guided_tour()


def _case_chain_html(facts):
    """A chronological record join; no feature values or trade reasons inferred."""
    missing = tr('Not recorded')
    membership = lambda value: tr('Held' if value is True else 'Not held' if value is False else 'Not recorded')
    rank = f'#{facts["rank"]}' if facts['rank'] is not None else missing
    steps = (
        ('Information boundary', facts['information_date'] or missing, ''),
        ('Model output', score_label(facts['score']) or missing, tr('Recorded rank') + ' · ' + rank),
        ('Portfolio membership', membership(facts['held_before']) + ' → ' + membership(facts['held_after']), 'Before execution → After execution'),
        ('Linked execution', facts['execution_date'] or missing, ''),
    )
    return '<ol class="uq-case-chain" data-ticker="' + text(facts['ticker']) + '">' + ''.join(
        '<li><span class="uq-case-step">' + f'{index:02}' + '</span><div><span>' + text(tr(label))
        + '</span><strong>' + text(value) + '</strong>'
        + ('<small>' + text(tr(note)) + '</small>' if note else '') + '</div></li>'
        for index, (label, value, note) in enumerate(steps, 1)) + '</ol>'


def _render_decision_focus(model):
    tickers = tuple(row.ticker for row in comparison_rows(model))
    if not tickers:
        st.info(tr('A verified Top20 record is required to inspect a decision trace.'))
        return False
    with st.container(key='uq_decision_focus'):
        title, select = st.columns([2.5, 1], gap='medium', vertical_alignment='center')
        with title:
            st.html(section_header(tr('Follow one recorded decision'), aside=model.decision_date or tr('Not recorded')))
        with select:
            resolved = resolve_case_ticker(model)
            if st.session_state.get('system_focus_ticker') != resolved:
                st.session_state['system_focus_ticker'] = resolved
            ticker = st.selectbox(tr('Decision to inspect'), tickers, index=None, key='system_focus_ticker',
                                  label_visibility='collapsed', persist_state='session',
                                  on_change=remember_case, args=('system_focus_ticker',))
        facts = trace_facts(model, ticker)
        if facts is None:
            st.info(tr('A verified Top20 record is required to inspect a decision trace.'))
            return False
        before, after = facts['held_before'], facts['held_after']
        state = {(True, True): 'Holding continued', (False, True): 'Entered the recorded holdings',
                 (True, False): 'Not retained in recorded holdings',
                 (False, False): 'Not held after the recorded execution'}.get((before, after), 'Membership is not fully recorded')
        st.html('<div class="uq-case-lead"><strong>' + text(ticker) + '</strong><div><b>'
                + text(tr(state)) + '</b></div></div>' + _case_chain_html(facts))
        _render_overview_actions(model)
        st.caption(tr('Linked records, not a causal explanation.'))
    return True


def _render_capability(capability, model, *, presentation):
    state = "Historical inspection" if capability.replay else "Engineering mechanism"
    if capability.replay and model.error:
        state = "Replay unavailable"
    st.html('<article class="uq-capability"><div class="uq-capability-heading"><span>'
            + text(tr(state)) + '</span><h3>' + text(tr(capability.question)) + '</h3></div>'
            '<div class="uq-capability-columns"><div><h4>' + text(tr("How it works")) + '</h4><p>'
            + text(tr(capability.mechanism)) + '</p></div><div><h4>' + text(tr("What you can inspect"))
            + '</h4><p>' + text(tr(capability.evidence)) + '</p></div></div>'
            '<p class="uq-capability-scope">' + text(tr(capability.scope)) + '</p></article>')
    if capability.title == "Model lineage":
        st.button(tr("Inspect the model lineage"), key="system_open_lineage", type="primary",
                  on_click=open_capability, args=("Machine learning",), kwargs={"section": "Training lineage"},
                  disabled=bool(model.error))
    elif capability.title in ("Execution mechanics", "Risk inspection"):
        risk = capability.title == "Risk inspection"
        st.button(tr("Inspect portfolio setbacks & recovery" if risk else "Inspect the execution ledger"),
                  key="system_open_records", type="primary", on_click=open_capability, args=("Research",),
                  kwargs={"research_tab": "Drawdown & recovery" if risk else "Execution frictions"},
                  disabled=bool(model.error or not model.provenance.execution_date))
    elif capability.title == "Research discipline":
        stages = ("Resolve identity", "Check prior trials", "Bind completion evidence")
        st.html('<div class="uq-system-rule-flow">' + ''.join('<div><span>' + f'{index:02}'
            + '</span><strong>' + text(tr(stage)) + '</strong></div>' for index, stage in enumerate(stages, 1)) + '</div>')
    elif capability.title == "Storage separation":
        layers = (("Code & control", "Source, compact configuration and tests"),
                  ("Input data", "Separate canonical input location"),
                  ("Evidence & runtime", "Results, backtests, state and environments"))
        st.html('<div class="uq-system-rule-flow">' + ''.join('<div><strong>' + text(tr(title))
            + '</strong><p>' + text(tr(detail)) + '</p></div>' for title, detail in layers) + '</div>')
    with st.expander(tr("Implementation references & scope"), expanded=False):
        for label, reference in capability.references:
            st.write(tr(label))
            if not presentation:
                st.code(reference, language="text")
        st.caption(tr("Engineering descriptions come from inspected source. This display does not load the current research registry or operational run status."))


def _render_overview_actions(model):
    tickers = tuple(row.ticker for row in comparison_rows(model))
    with st.container(horizontal=True, gap="small", key="system_actions"):
        st.button(tr("Follow this case"), key="system_start_tour", type="primary",
                  icon=":material/arrow_forward:", on_click=_start_case_walkthrough,
                  args=(tickers,),
                  disabled=bool(not tickers or st.session_state.get("_demo_tour_active")))
        st.button(tr('Inspect this decision'), key='system_focus_trace',
                  on_click=_open_selected_trace, icon=':material/route:',
                  disabled=not bool(tickers))


def _render_secondary_tools(model):
    tickers = tuple(row.ticker for row in comparison_rows(model))
    with st.container(horizontal=True, gap="small"):
        st.button(tr("Trace one decision"), key="system_trace", icon=":material/route:",
                  on_click=_open_selected_trace,
                  disabled=not bool(tickers))
        st.button(tr('Compare model outputs'), key='system_focus_compare',
                  on_click=_open_selected_comparison,
                  args=(tickers,), disabled=not bool(tickers))
        st.button(tr("Inspect portfolio setbacks & recovery"), key="system_risk", icon=":material/monitoring:",
                  on_click=open_capability, args=("Research",), kwargs={"research_tab": "Drawdown & recovery"},
                  disabled=bool(model.error or not model.provenance.execution_date))
        with st.popover(tr('Reliability drill'), icon=':material/verified_user:', width='content'):
            render_pit_timing()


def render_system_overview(model, *, presentation=True):
    st.html(system_hero_html(model))
    if not _render_decision_focus(model):
        _render_overview_actions(model)
    st.html('<div class="uq-portfolio-context">' + section_header(tr('Portfolio context'), tr('THE WIDER PICTURE'))
            + '<p>' + text(tr('This is the whole Raw A2 portfolio, not the selected stock’s contribution. Changing the case leaves this path unchanged.'))
            + '</p></div>')
    with st.container(key='uq_research_workspace'):
        _render_research_canvas(model, presentation=presentation)
    from apps.demo_console.components.recorded_2026 import open_recorded_2026
    st.button(tr("View the 2026 recorded window →"), key="system_2026",
              on_click=open_recorded_2026, type="tertiary")
    with st.expander(tr('System mechanisms & research coverage'), expanded=False):
        _render_secondary_tools(model)
        labels = ("Recorded snapshots", "Recorded features", "Annual model vintages")
        st.html('<div class="uq-system-evidence-strip"><span>' + text(tr("CURRENT FROZEN REPLAY")) + '</span>'
                + ''.join('<div><strong>' + text(f'{value:,}' if value is not None else '—') + '</strong><span>'
                          + text(tr(label)) + '</span></div>' for value, label in zip(overview_facts(model), labels)) + '</div>')
        options = tuple(capability.title for capability in CAPABILITIES)
        if st.session_state.get("system_capability") not in options:
            st.session_state["system_capability"] = options[0]
        selected = st.segmented_control(tr("System capability"), options, required=True,
            key="system_capability", format_func=option_labeler(options), persist_state="session",
            label_visibility="collapsed", width="stretch", wrap=True)
        _render_capability(next(capability for capability in CAPABILITIES if capability.title == selected),
                           model, presentation=presentation)
