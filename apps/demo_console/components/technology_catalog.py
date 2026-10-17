"""Source-based technology explanations, not a registry or operational authority.

The original six overview capabilities keep their definitions and public API.
Default rendering reads no research, model, account or operational status.
"""
from dataclasses import dataclass

import streamlit as st

from apps.demo_console.i18n import option_labeler, tr
from apps.demo_console.components.localized_tabs import localized_expander


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
        (("Research identity and duplicate checks", "scripts/maintenance/research_registry.py :: evaluate_proposal / resolve_alias / apply_patch"),
         ("Trial lifecycle and completion receipts", "scripts/maintenance/prospective_research_lifecycle.py :: evaluate_start_decision / validate_completion_receipt / apply_registry_completion"))),
    Capability("Storage separation", "How are source code, data and evidence kept apart?",
        "The storage configuration separates the code repository from data, results, caches, daily state, backtests and environments. The resolver rejects overlapping roots and repository-bound outputs.",
        "Code and control stay lightweight; input data, retained evidence and rebuildable outputs have separate configured destinations.",
        "Routing checks are not operating-system access controls. Read-only data policy and evidence retention remain separate protections.",
        (("Canonical storage configuration", "config/storage_paths.json"),
         ("Storage root validation", "scripts/common/storage_paths.py :: resolve / validate / assert_path_outside_repo"))),
)


TECHNOLOGIES = CAPABILITIES + (
    Capability('Feature engineering',
        'How are raw observations turned into defined model inputs?',
        'The Raw A2 source defines 32 rolling price and volume inputs: momentum, trend, volatility, price position and trading activity. Explicit formulas and complete windows make their meaning inspectable.',
        'Open the existing feature atlas to inspect source definitions. Other methods keep their own feature order and frozen transforms.',
        "This atlas describes the Raw A2 input schema, not every model and not a selected stock's feature values. It does not compute feature contributions.",
        (('Implementation source', 'apps/demo_console/components/ml_story.py :: FEATURES / render_feature_atlas'), ('Implementation source', 'scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py :: FEATURE_COLUMNS / build_stock_state_features'))),
    Capability('Machine learning methods',
        'Which learning methods can the research system compare?',
        'Research adapters define regularized linear models, boosted trees, ensembles, neural and sequence models, and quantile or distributional objectives. Named families and fixed capacities keep the comparison setup explicit.',
        'Ridge and ElasticNet, HGB, XGBoost, LightGBM, CatBoost, MLP, ResNet, FTTransformer, TCN, GRU and LSTM are examples in the source. Inspect the five application cases separately to see the accepted method and its native output.',
        'Implemented research methods are not a deployment list. This display does not train, rank or select models, and does not claim that all these families are used by the five applications.',
        (('Implementation source', 'scripts/research/a2/training/stateful_mechanism_models.py :: FAMILIES / parameters / fit'), ('Implementation source', 'scripts/research/a2/inference/consensus_paper.py :: r10_scaled_input'))),
    Capability('Time-aware validation',
        'How are training, validation and later observations kept apart?',
        'Temporal fold masks check signal time, label maturity and label availability against inner and outer cutoffs. Training and development content stay before 2026; frozen transforms are applied without refitting on later observations.',
        'The original fold builder and frozen-input path retain their date and ownership checks. The synthetic timing drill separately illustrates publication-time availability.',
        'Source boundaries are not proof of predictive skill. Exposed 2026 observations do not become a new independent holdout, and no fixed embargo length is implied here.',
        (('Implementation source', 'scripts/research/a2/training/stateful_account_models.py :: fold_masks'), ('Implementation source', 'scripts/research/a2/inference/consensus_paper.py :: r10_scaled_input'))),
    Capability('Risk-aware allocation',
        'How can a score become a portfolio under different risk assumptions?',
        'The selected HGB research paths bind diagonal and factor-shrinkage risk specifications. Portfolio construction reuses the original covariance, risk penalty, trading costs and solver, with policy-specific eligibility and position bounds.',
        'Compare the diagonal-risk application with the retained factor-shrinkage research path. Their source bindings explain the allocation mechanism without loading a model or solving a portfolio here.',
        'A retained research risk path is not evidence of deployment. This description neither changes the current account policy nor claims that one risk estimate guarantees smaller future losses.',
        (('Implementation source', 'scripts/research/a2/portfolio/selected_hgb.py :: _runtime / solve_targets'),)),
    Capability('On-demand reading and memory scope',
        'How can browsing and daily computation avoid unnecessary work?',
        'The stock-history reader projects approved columns and filters strategy, date and ticker in bounded Arrow batches. Current-input construction returns sealed references before publication, so its large temporary frames can leave scope first.',
        'Published views reuse verified source bindings; the daily owner retains its original history and resource checks. Browsing does not restart data acquisition, model fitting or order execution.',
        'These are specific source mechanisms, not a fixed peak-RAM promise or a claim that every source is streamed. Cache integrity, freshness and account permissions remain separate checks.',
        (('Implementation source', 'apps/demo_console/adapters/new_strategy_stock_history_reader.py :: _rows / _cached_rankings'), ('Implementation source', 'scripts/research/a2/inference/consensus_current_inputs.py :: _prepare_current_inputs / refresh_current_inputs'))),
)


QUICK_CAPABILITIES = ("Information timing", "Feature engineering", "Machine learning methods",
                      "Risk-aware allocation", "Execution mechanics", "Research discipline")


def _focus_capability(title):
    st.session_state["technology_capability"] = title


def render_technology_explorer():
    """Start with the question; open scope and source detail only when requested."""
    st.subheader(tr("Technology & research capabilities"))
    choices = tuple(item.title for item in TECHNOLOGIES)
    key = "technology_capability"
    selected = st.session_state.get(key)
    st.session_state[key] = selected if selected in choices else choices[0]
    with st.container(key="uq_capability_choices", horizontal=True, wrap=True, gap="small"):
        for title in QUICK_CAPABILITIES:
            st.button(tr(title), key="technology_quick_" + title.lower().replace(" ", "_"),
                type="primary" if title == st.session_state[key] else "secondary",
                on_click=_focus_capability, args=(title,))
    selected = st.selectbox(tr("Explore a technical capability"), choices, key=key,
        format_func=option_labeler(choices), persist_state="session")
    capability = next(item for item in TECHNOLOGIES if item.title == selected)
    with st.container(key="uq_capability_detail", border=True):
        st.caption(tr(capability.title))
        st.markdown("### " + tr(capability.question))
        st.write(tr(capability.mechanism))
        st.caption(tr("System application"))
        st.write(tr(capability.evidence))
    if selected == "Information timing":
        with localized_expander("Try the synthetic timing drill", key="technology_pit_drill") as detail:
            if detail.open:
                from apps.demo_console.components.pit_timing import render_pit_timing
                render_pit_timing()
    elif selected in ("Feature engineering", "Model lineage"):
        with localized_expander("Explore Raw A2 source-defined inputs", key="technology_feature_atlas") as detail:
            if detail.open:
                from apps.demo_console.components.ml_story import render_feature_atlas
                render_feature_atlas()
    with localized_expander("Implementation references & scope", key="technology_implementation_refs") as references:
        if references.open:
            st.write(tr(capability.scope))
            for label, reference in capability.references:
                st.caption(tr(label))
                st.code(reference, language="text")
            st.caption(tr("Engineering descriptions come from inspected source. This display does not load the current research registry or operational run status."))
