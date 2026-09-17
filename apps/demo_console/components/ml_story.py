"""Source-defined ML explanations; no model loading, fitting or feature inference.

Display definitions mirror FEATURE_COLUMNS/build_stock_state_features in
scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py (lines 68–79,
297–331). They describe the schema, not feature values from a replay record.
"""
from dataclasses import dataclass

import streamlit as st

from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.i18n import tr


@dataclass(frozen=True)
class Feature:
    name: str
    group: str
    label: str
    definition: str
    window: int
    formula: str
    short: int = 0

    def title(self) -> str:
        return tr(self.label, n=self.window, short=self.short)


FEATURES = (
    *(Feature(f"ret_{n}d", "Momentum", "{n}-session return",
              "Closing-price change over the selected horizon; {n} returns require {observations} closing-price observations.",
              n, "close[t] / close[t-n] − 1") for n in (1, 3, 5, 10, 20, 40, 60, 120)),
    *(Feature(f"price_vs_ma{n}", "Trend structure", "Price versus {n}-session average",
              "Closing price relative to its {n}-session arithmetic average.",
              n, "close[t] / mean(close, n) − 1") for n in (10, 20, 50, 120)),
    *(Feature(f"ma{s}_vs_ma{n}", "Trend structure", "{short}/{n}-session average spread",
              "The {short}-session price average relative to the {n}-session price average.",
              n, "mean(close, short) / mean(close, n) − 1", s) for s, n in ((10, 20), (20, 50), (50, 120))),
    *(Feature(f"realized_vol_{n}d", "Volatility", "{n}-session realized volatility",
              "Population standard deviation of daily close-to-close returns over {n} sessions; not annualized.",
              n, "std(daily_return, n, ddof=0)") for n in (5, 10, 20, 60)),
    Feature("downside_vol_20d", "Volatility", "20-session downside variation",
            "Root mean square of negative daily returns, with positive returns replaced by zero, over 20 sessions.",
            20, "sqrt(mean(min(daily_return, 0)², 20))"),
    Feature("upside_vol_20d", "Volatility", "20-session upside variation",
            "Root mean square of positive daily returns, with negative returns replaced by zero, over 20 sessions.",
            20, "sqrt(mean(max(daily_return, 0)², 20))"),
    *(Feature(f"distance_from_high_{n}d", "Price position", "Distance from {n}-session high",
              "Closing price relative to the highest closing price within {n} sessions.",
              n, "close[t] / max(close, n) − 1") for n in (20, 60)),
    *(Feature(f"distance_from_low_{n}d", "Price position", "Distance from {n}-session low",
              "Closing price relative to the lowest closing price within {n} sessions.",
              n, "close[t] / min(close, n) − 1") for n in (20, 60)),
    *(Feature(f"max_drawdown_{n}d", "Price position", "{n}-session maximum drawdown",
              "Worst peak-to-trough closing-price decline inside the {n}-session window; expressed as a nonpositive ratio.",
              n, "min(close / running_peak − 1, window=n)") for n in (20, 60)),
    *(Feature(f"avg_volume_{n}d", "Trading activity", "{n}-session average volume",
              "Arithmetic average of the source volume field over {n} sessions.",
              n, "mean(volume, n)") for n in (20, 60)),
    *(Feature(f"volume_ratio_{s}d_{n}d", "Trading activity", "{short}/{n}-session volume ratio",
              "The {short}-session average volume divided by the {n}-session average volume; no subtraction of one.",
              n, "mean(volume, short) / mean(volume, n)", s) for s, n in ((5, 20), (20, 60))),
    Feature("avg_dollar_volume_20d", "Trading activity", "20-session price × volume average",
            "Average of source closing price multiplied by volume over 20 sessions; a source-defined activity proxy.",
            20, "mean(close × volume, 20)"),
)
GROUPS = tuple(dict.fromkeys(feature.group for feature in FEATURES))


def render_feature_atlas(feature_columns: tuple[str, ...] | None = None) -> None:
    """Inspect all source-defined inputs, without presenting invented values."""
    matched = tuple(feature_columns or ()) == tuple(feature.name for feature in FEATURES)
    status = "Matches the recorded feature schema" if matched else "Source-defined schema"
    st.html(section_header(tr("Feature atlas"), tr("32 INPUT DEFINITIONS"), tr(status)))
    if feature_columns and not matched:
        st.warning(tr("The recorded schema differs from this source catalog. Definitions below are not bound to this record."))
    labels = {group: f"{tr(group)} · {sum(f.group == group for f in FEATURES)}" for group in GROUPS}
    if st.session_state.get("ml_feature_family") not in GROUPS:
        st.session_state["ml_feature_family"] = GROUPS[0]
    selected = st.pills(tr("Explore a feature family"), GROUPS, required=True,
                        format_func=labels.__getitem__, key="ml_feature_family", selection_mode="single")
    group = selected or GROUPS[0]
    features = tuple(feature for feature in FEATURES if feature.group == group)
    by_name = {feature.name: feature for feature in features}
    if st.session_state.get("ml_feature_name") not in by_name:
        st.session_state["ml_feature_name"] = features[0].name
    names = {feature.name: feature.title() for feature in features}
    name = st.selectbox(tr("Inspect an input"), tuple(by_name), index=None,
                        format_func=names.__getitem__, key="ml_feature_name")
    feature = by_name[name]
    definition = tr(feature.definition, n=feature.window, short=feature.short, observations=feature.window + 1)
    st.html('<article class="uq-ml-feature-detail">'
            f'<div class="uq-ml-feature-heading"><div><span class="uq-eyebrow">{text(tr(group))}</span>'
            f'<h3>{text(feature.title())}</h3></div><span class="uq-ml-window"><b>{feature.window}</b>'
            f'{text(tr("sessions"))}</span></div><p>{text(definition)}</p>'
            f'<code>{text(feature.formula)}</code><div class="uq-ml-schema-note">'
            f'{text(tr("Definition only · The selected stock’s feature value is not loaded."))}</div></article>')
    with st.expander(tr("Explore every input in this family")):
        st.html('<div class="uq-ml-feature-list">' + ''.join(
            f'<div><strong>{text(item.title())}</strong><code>{text(item.name)}</code></div>'
            for item in features) + '</div>')
        st.caption(tr("Definitions follow the R1 source implementation. Rolling statistics require a complete window; return-based statistics also need the preceding close."))
    st.caption(tr("13F information determines eligibility in this workflow. It is not one of these 32 model inputs. Per-stock feature values and feature contributions are not exposed in this replay."))


def render_learning_story(model, presentation: bool = True) -> None:
    """Show the objective and manifest-recorded vintages without fitting a model."""
    st.html(section_header(tr("What the model learns"), tr("LEARNING OBJECTIVE"), tr("Histogram gradient boosting")))
    st.html('<div class="uq-ml-objective"><div><span class="uq-eyebrow">'
            f'{text(tr("PREDICTION TARGET"))}</span><h3>{text(tr("Relative opportunity across stocks"))}</h3>'
            f'<p>{text(tr("The source-defined target averages stock return minus QQQ return across four future horizons."))}</p>'
            '</div><div class="uq-ml-horizons">' + ''.join(
                f'<div><b>{n}</b><span>{text(tr("sessions"))}</span></div>' for n in (3, 5, 10, 20))
            + '</div></div>')
    st.caption(tr("A score is a model output used for ranking. It is not a probability of rising, a promised return or a portfolio weight."))
    vintages = model.learning.vintages if not model.error else ()
    st.html('<div class="uq-ml-method-head">'
            f'<h3>{text(tr("Recorded model vintages"))}</h3><span>{text(tr("Frozen manifest metadata"))}</span></div>')
    if vintages:
        current_year = str(model.decision_date or "")[:4]
        cards = []
        for vintage in vintages:
            active = str(vintage.year) == current_year
            facts = (("Latest training observation", vintage.train_max_date),
                     ("Latest training-label maturity", vintage.train_target_end_max),
                     ("Recorded prediction period", f"{vintage.prediction_min_date} → {vintage.prediction_max_date}"),
                     ("Training rows", f"{vintage.training_row_count:,}"))
            cards.append(f'<li class="{"uq-ml-vintage-active" if active else ""}">'
                         f'<span class="uq-ml-step">{vintage.year}</span><h4>{text(tr(vintage.name))}</h4>'
                         + ''.join(f'<div class="uq-ml-vintage-fact"><span>{text(tr(label))}</span>'
                                   f'<strong>{text(value)}</strong></div>' for label, value in facts)
                         + '</li>')
        st.html('<ol class="uq-ml-learning-flow">' + ''.join(cards) + '</ol>')
        st.caption(tr("These are recorded training endpoints and prediction spans, not complete training intervals. Stage names come from the original manifest; they do not establish an untouched evaluation today."))
    else:
        st.caption(tr("Recorded training-vintage metadata is unavailable for this record."))
    if vintages and all("NOT_PERSISTED" in vintage.serialized_status for vintage in vintages):
        st.caption(tr("Historical stage models were not persisted. This workspace consumes their frozen predictions; it does not retrain them or reconstruct per-stock tree paths."))
    with st.expander(tr("Model identity and interpretation")):
        st.write(tr("Gradient boosting combines a sequence of decision trees, with later trees correcting remaining prediction errors. This is a method explanation; tree internals and contribution values are not loaded."))
        identity = model.provenance.config_identity if not model.error else None
        st.caption(tr("Recorded configuration fingerprint"))
        if identity:
            st.code(identity[:12] + "…" if presentation else identity, language=None)
        else:
            st.write(tr("Not exposed"))
        st.caption(tr("A matching fingerprint identifies a configuration. It does not establish predictive skill or independent validation."))
        if not presentation and model.provenance.alpha_implementation and not model.error:
            st.caption(tr("Recorded model implementation"))
            st.code(model.provenance.alpha_implementation, language=None)
        if model.learning.parameters and not model.error:
            st.caption(tr("Recorded HGB parameters"))
            parameter_labels = {"max_iter": "Maximum boosting iterations", "learning_rate": "Learning rate",
                                "max_leaf_nodes": "Maximum leaves per tree", "max_depth": "Maximum tree depth",
                                "min_samples_leaf": "Minimum samples per leaf", "l2_regularization": "L2 regularization",
                                "max_bins": "Maximum histogram bins", "early_stopping": "Early stopping",
                                "random_state": "Random seed", "loss": "Loss function"}
            st.html('<dl class="uq-ml-parameters">' + ''.join(
                f'<div><dt>{text(tr(parameter_labels.get(name, name)))}</dt><dd>{text(value)}</dd></div>'
                for name, value in model.learning.parameters) + '</dl>')
            st.caption(tr("Iteration and leaf settings are configured limits, not observed tree counts or a measure of predictive skill."))
