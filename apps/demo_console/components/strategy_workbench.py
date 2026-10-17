"""Data-free mechanism presentation, not a strategy or source registry.

The five identities remain owned by moomoo_component.strategy. These editorial
explanations use no model, result, market-data or account reader. The old label
API is re-exported by selected_strategies for existing research callers.
"""
from copy import deepcopy

import streamlit as st

from apps.demo_console.components.visuals import text
from apps.demo_console.i18n import tr

from apps.moomoo_trading_component.moomoo_component.strategy import (
    ACTIVE_PAPER_STRATEGY_IDS, APPLIED_STRATEGY_NAMES, QUERYABLE_STRATEGY_IDS,
)

WORKSPACE_STRATEGIES = {sid: "HGB + diagonal risk" if sid == "HGB_DIAG_5" else "Same-pool RAW · Consensus Top100" if sid == "RAW_s10" else APPLIED_STRATEGY_NAMES[sid]
                        for sid in QUERYABLE_STRATEGY_IDS}
LEGACY_STRATEGIES = {"HGB_FACTOR_5": "HGB + factor / shrinkage risk"}


def strategy_label(strategy_id):
    return WORKSPACE_STRATEGIES.get(strategy_id, LEGACY_STRATEGIES.get(strategy_id, strategy_id))


def short_strategy_label(strategy_id):
    return {"HGB_DIAG_5": "HGB \u00b7 Diagonal", "HGB_FACTOR_5": "HGB \u00b7 Factor"}.get(
        strategy_id, strategy_label(strategy_id))

FLOW_STEPS = (('Published inputs',
  'Dated universe membership, security identities and verified market features; each method keeps '
  'its own input contract.'),
 ('Frozen inference',
  'Apply the registered frozen models and transforms; this workbench does not fit or select '
  'models.'),
 ('Portfolio handling',
  'Apply method-specific decisions to existing holdings and cash under the original limits.'),
 ('Simulated execution',
  'Published targets, orders, fills and valuations are recorded separately; a target is not a '
  'fill.'))

TRAINING_BOUNDARY = 'Training and development stay before 2026-01-01, with earlier component cutoffs retained. The 2026 replay is descriptive and is not used for tuning.'

METHOD_STORIES = {'RAW_A2': {'question': 'Which stocks should we look at first?',
            'summary': 'Compare eligible stocks within the original candidate pool.',
            'input': "The model's defined price and trading-volume features.",
            'mechanism': 'Small decision trees make successive adjustments. Their contributions combine into '
                         'one score per stock.',
            'output': 'Relative stock scores and ranks.',
            'portfolio': 'The original candidate and holding rules turn scores into targets. Orders and '
                         'fills remain separate records.',
            'kind': 'Frozen HGB cross-sectional scoring baseline.',
            'native_output': 'Stock scores and ranks, not portfolio weights.',
            'portfolio_contract': 'Original Raw candidate and holding rules form targets.',
            'input_contract': 'Raw A2 keeps the frozen A2_HGB model identity. Scores feed the original '
                              'candidate and holding rules; execution remains a separate step.',
            'technical': 'HGB bins feature values to find tree splits. Training adds trees using loss '
                         'gradients; frozen inference sums their contributions into a stock score.',
            'glossary': (('Histogram binning',
                          'Group input values into ranges so trees can search their split points.'),
                         ('Loss gradient',
                          'A direction for the next tree to reduce the current prediction error during '
                          'training.')),
            'assumptions': ('The original candidate pool defines which stocks are being compared.',),
            'blind_spots': ("A stock score alone does not explain each feature's contribution.",),
            'research_prompts': ('Did this change come from the inputs, pool membership or a model version?',
                                 'Are ranks being compared within the same eligible pool and observation '
                                 'date?')},
 'HGB_DIAG_5': {'question': 'How much should each selected stock receive?',
                'summary': 'Turn stock scores into a portfolio that accounts for risk and trading costs.',
                'input': "HGB stock scores, each position's estimated risk, current holdings and cash.",
                'mechanism': 'An optimizer balances opportunity, position-level risk and the cost of '
                             'changing holdings.',
                'output': 'Target stock weights and a cash allocation.',
                'portfolio': 'Eligible targets pass through the original execution checks. Confirmed fills '
                             'show what was actually held.',
                'kind': 'Frozen HGB scores plus diagonal risk allocation.',
                'native_output': 'Stock scores, target weights and cash.',
                'portfolio_contract': 'Use the bound candidate policy and turnover costs.',
                'input_contract': 'Score the recorded Raw Top40 feature set, then use diagonal covariance in '
                                  'the original allocation optimizer. Candidate membership follows the bound '
                                  'policy.',
                'technical': 'HGB scores enter the allocation objective. A diagonal risk term penalizes '
                             'position-level variance, while turnover costs and portfolio limits constrain '
                             'changes from existing holdings. The optimizer chooses weights and cash.',
                'glossary': (('Diagonal risk',
                              "A risk estimate using each position's variance without cross-position "
                              'covariance terms.'),
                             ('Turnover cost', 'The modeled cost of changing the existing portfolio.')),
                'assumptions': ('The diagonal risk term uses position-level variances.',),
                'blind_spots': ('Cross-position covariance is not represented by the diagonal risk term.',),
                'research_prompts': ('How much of this weight change comes from the score, estimated risk or '
                                     'turnover cost?',
                                     'Could shared stock exposures matter beyond the position-level risk '
                                     'term?')},
 'R10_DIRECT_MEAN4_ELASTICNET_MID': {'question': 'Which action is preferable for this stock?',
                                     'summary': 'Compare entry choices and choices for existing holdings.',
                                     'input': "The entry and holding models' own features, in their frozen "
                                              'order and scale.',
                                     'mechanism': 'Linear models compare the actions. L1 and L2 penalties '
                                                  'limit coefficients during training; L1 can set some to '
                                                  'zero.',
                                     'output': 'Buy/skip proposals for candidates; sell/hold/replace '
                                               'proposals for existing holdings.',
                                     'portfolio': 'Original conflict, cash and position-preservation rules '
                                                  'turn proposals into targets.',
                                     'kind': 'Frozen ElasticNet action-value heads.',
                                     'native_output': 'BUY/SKIP and SELL/HOLD/REPLACE proposals; not stock '
                                                      'ranks.',
                                     'portfolio_contract': 'Resolve conflicts; preserve HOLD units and '
                                                           'original cash limits.',
                                     'input_contract': 'Entry and incumbent heads use their original feature '
                                                       'order and frozen scalers. Native proposals pass the '
                                                       'existing security and resource checks.',
                                     'technical': 'ElasticNet fits linear action-value heads with L1 and L2 '
                                                  'penalties. L1 can set coefficients to zero, while L2 '
                                                  'shrinks them; predicted action advantages feed the '
                                                  'original decision decoder.',
                                     'glossary': (('Action-value head',
                                                   'A model output that evaluates a particular action before '
                                                   'the decision rules resolve it.'),
                                                  ('L1 penalty',
                                                   'A training penalty that can make some fitted '
                                                   'coefficients exactly zero.'),
                                                  ('L2 penalty',
                                                   'A training penalty on squared coefficients that '
                                                   'discourages excessively large weights.'),
                                                  ('Exact HOLD units',
                                                   'Shares that the original decision rules require to '
                                                   'remain unchanged.')),
                                     'assumptions': ('Entry and incumbent heads keep their own action '
                                                     'meanings.',),
                                     'blind_spots': ('Sparse coefficients do not establish that selected '
                                                     'inputs are causal.',),
                                     'research_prompts': ('Which action head produced this proposal?',
                                                          'Which coefficients were zero after fitting, and '
                                                          'is that evidence exposed here?')},
 'R10_DIRECT_H5_RIDGE_MID': {'question': 'Which action is preferable for this stock?',
                             'summary': 'Compare entry choices and choices for existing holdings.',
                             'input': "The entry and holding models' own features, in their frozen order and "
                                      'scale.',
                             'mechanism': 'Linear models compare the actions. An L2 penalty limits large '
                                          'coefficients during training; the fitted model then stays fixed.',
                             'output': 'Buy/skip proposals for candidates; sell/hold/replace proposals for '
                                       'existing holdings.',
                             'portfolio': 'Original conflict, cash and position-preservation rules turn '
                                          'proposals into targets.',
                             'kind': 'Frozen Ridge action-value heads.',
                             'native_output': 'BUY/SKIP and SELL/HOLD/REPLACE proposals; not stock ranks.',
                             'portfolio_contract': 'Resolve conflicts; preserve HOLD units and original cash '
                                                   'limits.',
                             'input_contract': 'Entry and incumbent heads use their original feature order '
                                               'and frozen scalers. Native proposals pass the existing '
                                               'security and resource checks.',
                             'technical': 'Ridge fits linear action-value heads with an L2 penalty that '
                                          'shrinks coefficients, without the L1 sparsity term. Predicted '
                                          'action advantages feed the original entry and incumbent decision '
                                          'decoder.',
                             'glossary': (('Action-value head',
                                           'A model output that evaluates a particular action before the '
                                           'decision rules resolve it.'),
                                          ('L2 penalty',
                                           'A training penalty on squared coefficients that discourages '
                                           'excessively large weights.'),
                                          ('Exact HOLD units',
                                           'Shares that the original decision rules require to remain '
                                           'unchanged.')),
                             'assumptions': ('The frozen feature order and scales are part of the model '
                                             'contract.',),
                             'blind_spots': ('L2 shrinkage alone does not perform L1-style feature '
                                             'selection.',),
                             'research_prompts': ('Which action alternatives are compared under the original '
                                                  'decision rules?',
                                                  'Are we reading an action value or mistakenly treating it '
                                                  'as a stock-return score?')},
 'R7_GROSS_LINEAR': {'question': 'How much should be invested in stocks now?',
                     'summary': "Control the portfolio's investment level after stock choices have been "
                                'formed.',
                     'input': 'Verified model features and the previous requested investment level.',
                     'mechanism': 'A fixed linear classifier compares five exposure classes and selects the '
                                  'most likely class.',
                     'output': 'One requested investment level for the portfolio.',
                     'portfolio': 'Original portfolio rules handle targets, cash and positions whose share '
                                  'counts must be kept before execution is recorded.',
                     'kind': 'Frozen linear classifier for gross exposure.',
                     'native_output': 'A requested gross-exposure level, not stock ranks.',
                     'portfolio_contract': 'Scale explicit targets; keep exact HOLD units.',
                     'input_contract': 'A logistic linear classifier chooses one of five gross levels. The '
                                       'prior requested level is an input; target scaling preserves exact '
                                       'HOLD units.',
                     'technical': 'A logistic linear classifier turns features and prior requested exposure '
                                  'into probabilities for five exposure classes. The highest-probability '
                                  'class selects a requested gross level; it does not predict stock returns.',
                     'glossary': (('Linear classifier',
                                   'Combine weighted inputs to compare the available classes.'),
                                  ('Requested gross exposure',
                                   'The stock-investment level proposed by the model, before portfolio '
                                   'handling.'),
                                  ('Exact HOLD units',
                                   'Shares that the original decision rules require to remain unchanged.')),
                     'assumptions': ('The previous requested investment level is itself a model input.',),
                     'blind_spots': ('Requested exposure and final holdings can differ after exact HOLD '
                                     'rules.',),
                     'research_prompts': ('Did the new inputs or the previous request drive the class '
                                          'change?',
                                          'How did the original portfolio rules translate this request into '
                                          'eligible targets?')},
 'R6_BUY_NEURAL': {'question': 'Should we buy or skip this candidate?',
                   'summary': 'After candidates have been formed, decide whether to open a new position or '
                              'skip it.',
                   'input': 'Forty original features plus forty flags showing which inputs were missing.',
                   'mechanism': 'The fixed neural model estimates whether buying is preferable. The original '
                                'decoder chooses buy, skip or the reference rule.',
                   'output': 'The original buy-branch output.',
                   'portfolio': 'The original decision and portfolio rules process the buy output; the '
                                'duration branch keeps its own role.',
                   'kind': 'Frozen neural buy-branch model.',
                   'native_output': 'BUY or SKIP; exact ties and unknown values use REFERENCE.',
                   'portfolio_contract': 'Only the buy branch is supplied by this model; original portfolio '
                                         'handling remains authoritative.',
                   'input_contract': 'The frozen input has 80 dimensions: 40 original features and their 40 '
                                     'missingness flags.',
                   'technical': 'The frozen 80-dimensional neural buy branch supplies p_superior. The '
                                'original fixed decoder uses BUY above 0.5 and SKIP below 0.5; an exact tie '
                                'or unknown value uses REFERENCE. This illustration does not change that '
                                'threshold or the fitted model.',
                   'glossary': (('Missingness flag',
                                 'An extra input records whether the corresponding original feature was '
                                 'missing.'),
                                ('Learned weights',
                                 'Parameters determined during training and kept fixed for the published '
                                 'model.'),
                                ('Reference rule',
                                 'Return this branch to the unchanged original reference decision.')),
                   'assumptions': ('This model supplies the buy branch, not every holding decision.',),
                   'blind_spots': ('A missingness flag shows missing input state, not the missing value '
                                   'itself.',),
                   'research_prompts': ('Which missingness patterns are present in the buy-branch inputs?',
                                        'What happens to a buy proposal under the unchanged portfolio '
                                        'rules?')},
 'R6_DURATION_TREE': {'question': 'At the observation point, should we exit this holding?',
                      'summary': 'Split the question of continuing to hold into exit decisions at the '
                                 'original fixed observation points.',
                      'input': 'The 80-dimensional feature encoding and the original fixed proxy-age '
                               'observation points.',
                      'mechanism': 'The tree estimates the originally defined failure probability. At fixed '
                                   'proxy-age points, the original decoder decides whether to request an '
                                   'exit.',
                      'output': 'An exit proposal, or a return to the original reference rule.',
                      'portfolio': 'The original holding and execution rules apply. The supplied age is a '
                                   "proxy, not the account position's actual days held.",
                      'kind': 'Frozen tree duration-branch model.',
                      'native_output': 'SELL at qualified probes when p_failure exceeds 0.5; otherwise '
                                       'REFERENCE.',
                      'portfolio_contract': 'The tree supplies the duration role; original account and '
                                            'portfolio rules retain control.',
                      'input_contract': 'The frozen input has 80 dimensions: 40 original features and their '
                                        '40 missingness flags.',
                      'technical': 'The frozen tree duration branch uses the 80-dimensional encoding and '
                                   'p_failure. The original decoder participates only at proxy ages 0, 7 and '
                                   '14: p_failure above 0.5 requests SELL; other values, unknown values and '
                                   'non-probe ages use REFERENCE. This controls the original exit role, not '
                                   'a prediction of the number of days to hold.',
                      'glossary': (('Missingness flag',
                                    'An extra input records whether the corresponding original feature was '
                                    'missing.'),
                                   ('Proxy age',
                                    'The age supplied by the original model owner, rather than observed '
                                    'account holding days.'),
                                   ('Reference rule',
                                    'Return this branch to the unchanged original reference decision.')),
                      'assumptions': ("The supplied age is the original owner's proxy age.",),
                      'blind_spots': ('Proxy age must not be interpreted as actual account holding days.',),
                      'research_prompts': ('Which tree condition changed the duration branch?',
                                           'How would a mismatch between proxy age and actual holding age '
                                           'affect this interpretation?')},
 'RAW_s10': {'question': 'Which stocks stand out within Consensus Top100?',
             'summary': 'Apply the same frozen Raw scorer inside a different, explicitly defined candidate '
                        'pool.',
             'input': 'The original Raw features for the Consensus Top100 candidate pool.',
             'mechanism': 'Small decision trees make successive adjustments. Their contributions combine '
                          'into one score per stock.',
             'output': 'The available MAIN records expose actions and targets; stock ranks and scores were '
                       'not recorded.',
             'portfolio': 'The original candidate and holding rules turn scores into targets. Orders and '
                          'fills remain separate records.',
             'kind': 'Frozen HGB cross-sectional scoring baseline.',
             'native_output': 'The original Raw scorer is unchanged. This MAIN reader exposes recorded '
                              'actions and targets, without reconstructing missing ranks or scores.',
             'portfolio_contract': 'Original Raw candidate and holding rules form targets.',
             'input_contract': 'Consensus Top100 orders securities by institution count, then summed '
                               'institution portfolio weights, then CUSIP. Its pool differs from Raw A2; the '
                               'frozen scorer is unchanged.',
             'technical': 'HGB bins feature values to find tree splits. Training adds trees using loss '
                          'gradients; frozen inference sums their contributions into a stock score.',
             'glossary': (('Histogram binning',
                           'Group input values into ranges so trees can search their split points.'),
                          ('Loss gradient',
                           'A direction for the next tree to reduce the current prediction error during '
                           'training.')),
             'assumptions': ('Candidate selection happens before the unchanged Raw scorer is applied.',),
             'blind_spots': ('Different candidate pools can change ranks without changing the scorer.',),
             'research_prompts': ('Is the difference driven by pool membership or by the stock features?',
                                  'Are institution counts, weights and CUSIP identities bound to the '
                                  'intended snapshot?')}}

# Compatibility APIs are projections of the same narrative, not a second owner.
METHOD_EXPLANATIONS = {sid: (s["kind"], s["native_output"], s["portfolio_contract"],
    s["input_contract"], s["technical"]) for sid, s in METHOD_STORIES.items()}


def method_story(strategy_id):
    """Return one editorial story; identity and selection stay with their owners."""
    if strategy_id not in METHOD_STORIES:
        raise ValueError("METHOD_STORY_NOT_SOURCE_CONFIRMED")
    story = deepcopy(METHOD_STORIES[strategy_id])
    story.update(strategy_id=strategy_id, label=strategy_label(strategy_id), boundary=TRAINING_BOUNDARY,
        steps=[{"id": name, "body": story[field]} for name, field in (
            ("question", "summary"), ("input", "input"), ("mechanism", "mechanism"),
            ("output", "output"), ("portfolio", "portfolio"))])
    return story


def render_method_explanation(strategy_id, *, presentation=True, key=None):
    """Use the same source-free interaction in cases, ML explanations and empty states."""
    from apps.demo_console.components.method_explainer import render_method_explainer
    return render_method_explainer(method_story(strategy_id),presentation=presentation,key=key)


def _focus_method(strategy_id):
    """Use the existing global detail-focus and replay context transition."""
    if strategy_id not in WORKSPACE_STRATEGIES:
        return
    if st.session_state.get("workspace_strategy") != strategy_id:
        from apps.demo_console.app import _change_strategy
        st.session_state["workspace_strategy"] = strategy_id
        _change_strategy()


def _focus_catalog_method():
    """Query a known method without changing the accepted five-method roster."""
    _focus_method(st.session_state.get("workbench_catalog_method"))


def _open_view(view, strategy_id=None):
    """Route an exhibit action through the sole workspace navigation owner."""
    from apps.demo_console.app import navigate_workspace
    navigate_workspace(view, strategy_id=strategy_id)


OUTPUT_LABELS = {
    "RAW_A2": "Stock scores", "HGB_DIAG_5": "Weights and cash",
    "R10_DIRECT_MEAN4_ELASTICNET_MID": "Action proposals",
    "R10_DIRECT_H5_RIDGE_MID": "Action proposals", "R7_GROSS_LINEAR": "Gross exposure",
    "R6_BUY_NEURAL": "Buy decisions", "R6_DURATION_TREE": "Holding-duration decisions", "RAW_s10": "Stock scores",
}


def mechanism_html(focused, *, presentation):
    """A compact, data-free introduction; each method retains its own inputs."""
    steps = "".join('<li class="uq-technical-step"><span class="uq-stage-index">'
        + f"{index:02}" + '</span><strong>' + text(tr(title)) + '</strong></li>'
        for index, (title, _) in enumerate(FLOW_STEPS, 1))
    return ('<section class="uq-strategy-workbench" data-mode="'
        + ('presentation' if presentation else 'research') + '">'
        + '<div class="uq-workbench-purpose"><h2>'
        + text(tr("Five methods. One daily simulation.")) + '</h2><p>'
        + text(tr("Compare how verified market records become stock decisions, portfolio targets and confirmed simulated fills."))
        + '</p></div><ol class="uq-technical-flow">' + steps + '</ol></section>')


METHOD_QUESTIONS = {sid: story["question"] for sid, story in METHOD_STORIES.items()}


def method_detail_html(focused):
    """Static summary from the same story; keep the established public signature."""
    story = method_story(focused)
    return ('<section class="uq-method-detail" data-strategy-id="' + text(focused)
        + '"><h3>' + text(tr(story["question"])) + '</h3><p class="uq-method-definition">'
        + text(tr(story["summary"])) + '</p><div class="uq-method-decision"><article><strong>'
        + text(tr("What this method produces")) + '</strong><p>' + text(tr(story["output"]))
        + '</p></article><article><strong>' + text(tr("How it becomes a portfolio"))
        + '</strong><p>' + text(tr(story["portfolio"])) + '</p></article></div></section>')


def method_principle_html(focused):
    """Static technical projection for existing callers; one explanation once."""
    story = method_story(focused)
    return ('<section class="uq-method-principle" data-strategy-id="' + text(focused)
        + '"><strong>' + text(tr("Model principle")) + '</strong><p>'
        + text(tr(story["technical"])) + '</p></section>')


def inputs_html():
    return ('<section class="uq-workbench-inputs"><p>' + text(tr(FLOW_STEPS[0][1]))
        + '</p><p>' + text(tr(TRAINING_BOUNDARY)) + '</p><p>'
        + text(tr("Research data is updated manually each afternoon. Browsing uses published records and caches."))
        + '</p><p>' + text(tr("Simulation keeps the original account, quote and authorization checks."))
        + '</p><p>' + text(tr("Architecture only: no model execution, account refresh or new order is triggered here."))
        + '</p></section>')


def render_strategy_workbench(pages, presentation=True):
    """System engineering is the homepage; strategies are supporting cases."""
    from apps.demo_console.components.architecture_exhibit import render_architecture
    render_architecture(presentation)
    from apps.demo_console.components.technology_catalog import render_technology_explorer
    with st.container(key="technical_capability_explorer"):
        render_technology_explorer()
    with st.container(key="uq_exhibit_next", border=True):
        st.subheader(tr("Continue from principle to evidence"))
        st.caption(tr("Keep the same method and observation date as you explore its recorded decisions, charts and simulated execution."))
        with st.container(horizontal=True, gap="small", wrap=True):
            st.button(tr("Explore the five ML workbenches"), key="exhibit_open_ml",
                type="primary", icon=":material/model_training:",
                on_click=_open_view, args=("Machine learning",))
            st.button(tr("Explore data and charts"), key="exhibit_open_charts",
                icon=":material/monitoring:", on_click=_open_view, args=("Research",))
            st.button(tr("Open daily simulation"), key="exhibit_open_simulation",
                icon=":material/account_balance:", on_click=_open_view, args=("Execution",))


def render_method_picker(*, strategy_ids=None):
    """Shared method focus; the accepted roster is supplied by its existing owner."""
    ids = tuple(ACTIVE_PAPER_STRATEGY_IDS) if strategy_ids is None else tuple(strategy_ids)
    if not ids or len(set(ids)) != len(ids) or any(sid not in METHOD_STORIES for sid in ids):
        raise ValueError("INVALID_METHOD_DISPLAY_IDS")
    focused = st.session_state.get("workspace_strategy")
    if focused not in WORKSPACE_STRATEGIES:
        focused = ids[0]
    st.caption(tr("Choose a method"))
    with st.container(key="strategy_workbench_focus", horizontal=True, wrap=True, gap="small"):
        for sid in ids:
            with st.container(key="workbench_method_card_" + sid, border=False, width="stretch"):
                st.button(tr(short_strategy_label(sid)), key="workbench_method_" + sid,
                    type="primary" if sid == focused else "secondary", width="stretch",
                    on_click=_focus_method, args=(sid,))
                st.caption(tr(OUTPUT_LABELS[sid]))
    other_ids = tuple(sid for sid in WORKSPACE_STRATEGIES if sid not in ids)
    if other_ids:
        with st.expander(tr("Query other methods"), expanded=focused not in ids,
                on_change="rerun", key="workbench_other_methods") as other:
            if other.open:
                if focused in other_ids:
                    st.session_state["workbench_catalog_method"] = focused
                elif st.session_state.get("workbench_catalog_method") not in other_ids:
                    st.session_state["workbench_catalog_method"] = None
                st.selectbox(tr("Choose another method to inspect"),other_ids,index=None,
                    key="workbench_catalog_method",format_func=lambda sid:tr(strategy_label(sid)),
                    on_change=_focus_catalog_method,persist_state="session")
    if focused not in ids:
        st.caption(tr("Viewing another method. The five-method showcase stays unchanged."))
    return focused


def render_strategy_cases(pages, presentation=True, *, strategy_ids=None, show_picker=True):
    """Reuse the shared focus and the same explanation in every application tool."""
    focused = (render_method_picker(strategy_ids=strategy_ids) if show_picker
               else st.session_state["workspace_strategy"])
    render_method_explanation(focused,presentation=presentation,key="strategy_method_explanation")
    with st.container(key="workbench_method_actions", horizontal=True, gap="small", wrap=True):
        st.button(tr("Open this ML workbench"), key="workbench_open_ml", type="primary",
            icon=":material/model_training:", on_click=_open_view, args=("Machine learning", focused))
        st.button(tr("View recorded decisions"), key="workbench_open_decisions",
            icon=":material/table_chart:", on_click=_open_view, args=("Portfolio", focused))
    with st.expander(tr("Inputs and safeguards"), expanded=False,
            on_change="rerun", key="workbench_inputs") as inputs:
        if inputs.open:
            st.html(inputs_html())
