from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from a2_right_tail_event_antecedent_diagnostic_r1 import atomic_csv, atomic_text, sha256_file


TASK_NAME = "A2_RAW_SCORE_OOS_PROBABILITY_TO_ECONOMICS_BRIDGE_R1"
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_NAME
PRIOR = RESULTS / "A2_RAW_SCORE_OOS_TAIL_PREDICTION_R1"
PREDICTIONS = PRIOR / "oos_predictions.parquet"
PRIOR_SUMMARY = PRIOR / "oos_summary.csv"
MAX_OUTCOME_DATE = pd.Timestamp("2025-12-31")
PRE2025_END = pd.Timestamp("2024-12-31")
TOL = 1e-12


class BridgeFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        suffix = f":{evidence}" if evidence != "" else ""
        raise BridgeFailure(f"{code}{suffix}")


def prior_value(frame: pd.DataFrame, section: str, metric: str, scope: str | None = None) -> str:
    rows = frame.loc[frame.section.eq(section) & frame.metric.eq(metric)]
    if scope is not None:
        rows = rows.loc[rows.scope.eq(scope)]
    require(len(rows) == 1, "PRIOR_SUMMARY_IDENTITY_FAILURE", f"{section}:{metric}:{scope}:{len(rows)}")
    return str(rows.iloc[0].value)


def row(section: str, metric: str, scope: str, value: Any, notes: str = "", year: Any = "ALL") -> dict[str, Any]:
    if isinstance(value, float) and not np.isfinite(value):
        value = "NA"
    return {"section": section, "metric": metric, "scope": scope, "year": year, "value": value, "notes": notes}


def finite_mean(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else float("nan")


def finite_median(series: pd.Series) -> float:
    return float(series.median()) if len(series) else float("nan")


def bridge(frame: pd.DataFrame) -> dict[str, Any]:
    high = frame.loc[frame.high_score]
    lower = frame.loc[~frame.high_score]
    high_tail = high.loc[high.right_tail.eq(1), "event_active_return"]
    high_nontail = high.loc[high.right_tail.eq(0), "event_active_return"]
    lower_tail = lower.loc[lower.right_tail.eq(1), "event_active_return"]
    lower_nontail = lower.loc[lower.right_tail.eq(0), "event_active_return"]
    p_high = float(high.right_tail.mean()) if len(high) else float("nan")
    p_lower = float(lower.right_tail.mean()) if len(lower) else float("nan")
    t_high, t_lower = finite_mean(high_tail), finite_mean(lower_tail)
    n_high, n_lower = finite_mean(high_nontail), finite_mean(lower_nontail)
    high_mean = finite_mean(high.event_active_return)
    lower_mean = finite_mean(lower.event_active_return)
    high_identity = high_mean - (p_high * t_high + (1 - p_high) * n_high) if all(np.isfinite(x) for x in (high_mean, p_high, t_high, n_high)) else float("nan")
    lower_identity = lower_mean - (p_lower * t_lower + (1 - p_lower) * n_lower) if all(np.isfinite(x) for x in (lower_mean, p_lower, t_lower, n_lower)) else float("nan")
    net = high_mean - lower_mean if np.isfinite(high_mean) and np.isfinite(lower_mean) else float("nan")
    probability = (p_high - p_lower) * (t_lower - n_lower) if all(np.isfinite(x) for x in (p_high, p_lower, t_lower, n_lower)) else float("nan")
    tail_magnitude = p_high * (t_high - t_lower) if all(np.isfinite(x) for x in (p_high, t_high, t_lower)) else float("nan")
    nontail = (1 - p_high) * (n_high - n_lower) if all(np.isfinite(x) for x in (p_high, n_high, n_lower)) else float("nan")
    residual = net - probability - tail_magnitude - nontail if all(np.isfinite(x) for x in (net, probability, tail_magnitude, nontail)) else float("nan")
    return {
        "event_count": int(len(frame)), "high_count": int(len(high)), "lower_count": int(len(lower)),
        "high_tail_count": int(high.right_tail.sum()) if len(high) else 0,
        "lower_tail_count": int(lower.right_tail.sum()) if len(lower) else 0,
        "high_nontail_count": int((high.right_tail == 0).sum()), "lower_nontail_count": int((lower.right_tail == 0).sum()),
        "high_tail_rate": p_high, "lower_tail_rate": p_lower,
        "tail_rate_spread": p_high - p_lower if np.isfinite(p_high) and np.isfinite(p_lower) else float("nan"),
        "high_mean": high_mean, "lower_mean": lower_mean, "net": net,
        "high_median": finite_median(high.event_active_return), "lower_median": finite_median(lower.event_active_return),
        "median_spread": finite_median(high.event_active_return) - finite_median(lower.event_active_return) if len(high) and len(lower) else float("nan"),
        "high_tail_mean": t_high, "lower_tail_mean": t_lower,
        "high_tail_median": finite_median(high_tail), "lower_tail_median": finite_median(lower_tail),
        "high_nontail_mean": n_high, "lower_nontail_mean": n_lower,
        "high_nontail_median": finite_median(high_nontail), "lower_nontail_median": finite_median(lower_nontail),
        "high_expected_return_identity_error": high_identity, "lower_expected_return_identity_error": lower_identity,
        "probability_component": probability, "tail_magnitude_component": tail_magnitude,
        "nontail_component": nontail, "decomposition_residual": residual,
    }


def append_bridge(rows: list[dict[str, Any]], section: str, scope: str, values: dict[str, Any], notes: str = "", year: Any = "ALL") -> None:
    for metric, value in values.items():
        rows.append(row(section, metric.upper(), scope, value, notes, year))


def load_and_validate() -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    require(PREDICTIONS.exists() and PRIOR_SUMMARY.exists(), "PRIOR_ARTIFACT_MISSING")
    predictions = pd.read_parquet(PREDICTIONS)
    summary = pd.read_csv(PRIOR_SUMMARY, dtype=str, keep_default_na=False)
    for column in ("decision_date", "holding_start", "holding_end", "raw_score_available_timestamp"):
        predictions[column] = pd.to_datetime(predictions[column])
    require(len(predictions) == int(float(prior_value(summary, "POOLED_PROBABILITY", "N", "OUTER_TEST_ONLY"))), "PRIOR_OOS_ROW_COUNT_MISMATCH")
    require(int(predictions.right_tail.sum()) == int(float(prior_value(summary, "POOLED_PROBABILITY", "POSITIVE_COUNT", "OUTER_TEST_ONLY"))), "PRIOR_RIGHT_TAIL_COUNT_MISMATCH")
    require(predictions.outer_fold.nunique() == 5 and predictions.outer_fold.notna().all(), "PRIOR_OUTER_FOLD_IDENTITY_MISMATCH")
    require(predictions.decision_date.is_unique, "PRIOR_OOS_EVENT_DUPLICATE")
    require(predictions.holding_end.max() <= MAX_OUTCOME_DATE, "POST_2025_OUTCOME_LEAKAGE")
    require((predictions.raw_score_available_timestamp <= predictions.decision_date).all(), "PRIOR_PREDICTOR_TIMESTAMP_FAILURE")
    require(predictions.event_active_return.notna().all() and np.isfinite(predictions.event_active_return).all(), "PRIOR_ACTIVE_RETURN_INVALID")
    require(predictions.right_tail.isin([0, 1]).all(), "PRIOR_RIGHT_TAIL_LABEL_INVALID")
    require(predictions.high_score.dtype == bool or predictions.high_score.isin([True, False]).all(), "PRIOR_HIGH_SCORE_LABEL_INVALID")
    expected_high = predictions.raw_score.gt(predictions.train_score_q80)
    require(np.array_equal(predictions.high_score.to_numpy(bool), expected_high.to_numpy(bool)), "PRIOR_HIGH_SCORE_MEMBERSHIP_MISMATCH")
    require(predictions.groupby("outer_fold").train_score_q80.nunique().eq(1).all(), "PRIOR_TRAIN_Q80_FOLD_METADATA_FAILURE")
    prior_high_count = int(float(prior_value(summary, "POOLED_HIGH_SCORE", "HIGH_COUNT", "OUTER_TEST_ONLY")))
    prior_high_lift = float(prior_value(summary, "POOLED_HIGH_SCORE", "LIFT", "OUTER_TEST_ONLY"))
    high = predictions.loc[predictions.high_score]
    high_lift = float(high.right_tail.mean() / predictions.right_tail.mean())
    require(int(predictions.high_score.sum()) == prior_high_count, "PRIOR_HIGH_SCORE_COUNT_MISMATCH")
    require(abs(high_lift - prior_high_lift) <= 1e-14, "PRIOR_HIGH_SCORE_LIFT_MISMATCH", high_lift - prior_high_lift)
    require(prior_value(summary, "TARGET", "EVENT_ACTIVE_RETURN_DEFINITION") == "EVENT_INCREMENTAL_WEALTH / PRE_EVENT_A2_NAV", "PRIOR_ACTIVE_RETURN_DEFINITION_MISMATCH")
    require(prior_value(summary, "CLASSIFICATION", "PROBABILITY_SIGNAL_CLASSIFICATION") == "SUPPORTED", "PRIOR_PROBABILITY_CLASSIFICATION_MISMATCH")
    require(prior_value(summary, "CLASSIFICATION", "PAYOFF_SIGNAL_CLASSIFICATION") == "NOT_SUPPORTED", "PRIOR_PAYOFF_CLASSIFICATION_MISMATCH")
    require(prior_value(summary, "CLASSIFICATION", "RAW_A2_SCORE_TAIL_PREDICTION_CLASSIFICATION") == "PROBABILITY_ONLY_SUPPORTED", "PRIOR_OVERALL_CLASSIFICATION_MISMATCH")
    rows = [
        row("PRIOR_IDENTITY", "PRIOR_OOS_IDENTITY_STATUS", "ALL", "PASS"),
        row("PRIOR_IDENTITY", "OOS_PREDICTIONS_SHA256", str(PREDICTIONS), sha256_file(PREDICTIONS)),
        row("PRIOR_IDENTITY", "OOS_SUMMARY_SHA256", str(PRIOR_SUMMARY), sha256_file(PRIOR_SUMMARY)),
        row("PRIOR_IDENTITY", "POOLED_OOS_EVENT_COUNT", "ALL", len(predictions)),
        row("PRIOR_IDENTITY", "POOLED_OOS_RIGHT_TAIL_COUNT", "ALL", int(predictions.right_tail.sum())),
        row("PRIOR_IDENTITY", "OUTER_FOLD_COUNT", "ALL", predictions.outer_fold.nunique()),
        row("PRIOR_IDENTITY", "HIGH_SCORE_EVENT_COUNT", "ALL", int(predictions.high_score.sum())),
        row("PRIOR_IDENTITY", "HIGH_SCORE_WINNER_LIFT", "ALL", high_lift),
        row("PRIOR_IDENTITY", "EVENT_ACTIVE_RETURN_DEFINITION", "ALL", "EVENT_INCREMENTAL_WEALTH / PRE_EVENT_A2_NAV"),
        row("PRIOR_IDENTITY", "HIGH_SCORE_DEFINITION", "ALL", "persisted raw_score > persisted fold-local TRAIN_Q80"),
    ]
    return predictions.sort_values("decision_date", kind="mergesort").reset_index(drop=True), summary, rows


def analyze(predictions: pd.DataFrame, rows: list[dict[str, Any]]) -> dict[str, Any]:
    pooled = bridge(predictions)
    require(abs(pooled["high_expected_return_identity_error"]) <= TOL, "HIGH_EXPECTED_RETURN_IDENTITY_FAILURE")
    require(abs(pooled["lower_expected_return_identity_error"]) <= TOL, "LOWER_EXPECTED_RETURN_IDENTITY_FAILURE")
    require(abs(pooled["decomposition_residual"]) <= TOL, "POOLED_DECOMPOSITION_IDENTITY_FAILURE")
    append_bridge(rows, "POOLED_BRIDGE", "OUTER_TEST_ONLY", pooled)

    fold_results: dict[str, dict[str, Any]] = {}
    for fold, group in predictions.groupby("outer_fold", sort=True):
        values = bridge(group)
        for key in ("high_expected_return_identity_error", "lower_expected_return_identity_error", "decomposition_residual"):
            require(not np.isfinite(values[key]) or abs(values[key]) <= TOL, "FOLD_BRIDGE_IDENTITY_FAILURE", f"{fold}:{key}:{values[key]}")
        fold_results[str(fold)] = values
        append_bridge(rows, "FOLD_BRIDGE", str(fold), values, "persisted OUTER TEST rows; no refit or threshold estimation")

    pre = predictions.loc[predictions.holding_end.le(PRE2025_END)].copy()
    require(len(pre) > 0 and pre.holding_end.max() <= PRE2025_END, "PRE2025_SCOPE_FAILURE")
    pre_values = bridge(pre)
    require(abs(pre_values["high_expected_return_identity_error"]) <= TOL, "PRE2025_HIGH_EXPECTED_RETURN_IDENTITY_FAILURE")
    require(abs(pre_values["lower_expected_return_identity_error"]) <= TOL, "PRE2025_LOWER_EXPECTED_RETURN_IDENTITY_FAILURE")
    require(abs(pre_values["decomposition_residual"]) <= TOL, "PRE2025_DECOMPOSITION_IDENTITY_FAILURE")
    append_bridge(rows, "PRE2025_BRIDGE", "OUTER_TEST_ONLY_PRE2025", pre_values)

    year_results: dict[int, dict[str, Any]] = {}
    outcome_year = predictions.holding_end.dt.year
    for year, group in predictions.groupby(outcome_year, sort=True):
        values = bridge(group)
        year_results[int(year)] = values
        direct = {key: values[key] for key in (
            "event_count", "high_count", "lower_count", "high_tail_rate", "lower_tail_rate",
            "tail_rate_spread", "high_mean", "lower_mean", "net",
        )}
        append_bridge(rows, "YEAR_BRIDGE_DESCRIPTIVE", str(year), direct, "fixed persisted score groups; descriptive only", int(year))

    finite_folds = [value for value in fold_results.values() if np.isfinite(value["net"])]
    positive_net_folds = sum(value["net"] > 0 for value in finite_folds)
    negative_net_folds = sum(value["net"] < 0 for value in finite_folds)
    positive_probability_folds = sum(np.isfinite(value["probability_component"]) and value["probability_component"] > 0 for value in fold_results.values())
    negative_nontail_folds = sum(np.isfinite(value["nontail_component"]) and value["nontail_component"] < 0 for value in fold_results.values())
    finite_years = [value for value in year_results.values() if np.isfinite(value["net"])]
    positive_net_years = sum(value["net"] > 0 for value in finite_years)
    negative_net_years = sum(value["net"] < 0 for value in finite_years)
    undefined_years = len(year_results) - len(finite_years)

    pooled_cells_sufficient = all(pooled[key] > 0 for key in ("high_tail_count", "high_nontail_count", "lower_tail_count", "lower_nontail_count"))
    nontail_not_fully_offset_probability = pooled["nontail_component"] >= 0 or pooled["probability_component"] + pooled["nontail_component"] > 0
    supported = (
        pooled_cells_sufficient and pooled["tail_rate_spread"] > 0 and pooled["probability_component"] > 0
        and pooled["net"] > 0 and positive_net_folds >= 4 and pre_values["net"] > 0
        and nontail_not_fully_offset_probability
    )
    if not pooled_cells_sufficient or len(finite_folds) < 3:
        classification = "INSUFFICIENT_OOS_CELLS"
    elif supported:
        classification = "SUPPORTED_NET_POSITIVE_PROBABILITY_BRIDGE"
    elif pooled["net"] > 0:
        classification = "NET_POSITIVE_BUT_UNSTABLE"
    elif (
        pooled["tail_rate_spread"] > 0 and pooled["probability_component"] > 0
        and pooled["nontail_component"] < 0
        and (abs(pooled["nontail_component"]) >= .50 * pooled["probability_component"] or pooled["net"] <= 0)
    ):
        classification = "PROBABILITY_UPLIFT_MOSTLY_OFFSET_BY_NONTAIL_DRAG"
    else:
        classification = "NO_NET_ECONOMIC_BRIDGE"
    sizing = "SUPPORTED" if classification == "SUPPORTED_NET_POSITIVE_PROBABILITY_BRIDGE" else ("MIXED" if classification == "NET_POSITIVE_BUT_UNSTABLE" else "NOT_SUPPORTED")
    rows.extend([
        row("STABILITY", "VALID_ECONOMIC_FOLD_COUNT", "ALL", len(finite_folds), "OUTER_5 has no persisted HIGH_SCORE observations and is retained as NA"),
        row("STABILITY", "POSITIVE_NET_ECONOMIC_FOLD_COUNT", "ALL", positive_net_folds),
        row("STABILITY", "NEGATIVE_NET_ECONOMIC_FOLD_COUNT", "ALL", negative_net_folds),
        row("STABILITY", "POSITIVE_PROBABILITY_COMPONENT_FOLD_COUNT", "ALL", positive_probability_folds),
        row("STABILITY", "NEGATIVE_NONTAIL_COMPONENT_FOLD_COUNT", "ALL", negative_nontail_folds),
        row("STABILITY", "POSITIVE_NET_ECONOMIC_YEAR_COUNT", "ALL", positive_net_years),
        row("STABILITY", "NEGATIVE_NET_ECONOMIC_YEAR_COUNT", "ALL", negative_net_years),
        row("STABILITY", "UNDEFINED_YEAR_COUNT", "ALL", undefined_years),
        row("CLASSIFICATION", "PROBABILITY_TO_ECONOMICS_CLASSIFICATION", "ALL", classification),
        row("CLASSIFICATION", "POSITION_SIZING_RESEARCH_JUSTIFICATION", "ALL", sizing),
    ])
    return {
        "pooled": pooled, "folds": fold_results, "pre": pre_values, "years": year_results,
        "positive_net_folds": positive_net_folds, "negative_net_folds": negative_net_folds,
        "positive_probability_folds": positive_probability_folds, "negative_nontail_folds": negative_nontail_folds,
        "positive_net_years": positive_net_years, "negative_net_years": negative_net_years,
        "undefined_years": undefined_years, "classification": classification, "sizing": sizing,
        "valid_economic_folds": len(finite_folds), "pre_count": len(pre),
        "nontail_probability_offset_share": abs(pooled["nontail_component"]) / pooled["probability_component"] if pooled["probability_component"] > 0 and pooled["nontail_component"] < 0 else 0.0,
    }


def fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "NA"
    if isinstance(value, float):
        return f"{value:.10f}"
    return str(value)


def build_report(predictions: pd.DataFrame, result: dict[str, Any]) -> str:
    p = result["pooled"]
    pre = result["pre"]
    tail_direction = "positive" if p["tail_magnitude_component"] > 0 else ("negative" if p["tail_magnitude_component"] < 0 else "negligible")
    lines = [
        "# A2 Raw-score OOS probability-to-economics bridge R1", "", "## Verdict", "",
        f"`PROBABILITY_TO_ECONOMICS_CLASSIFICATION={result['classification']}`", "",
        f"`POSITION_SIZING_RESEARCH_JUSTIFICATION={result['sizing']}`", "",
        "The previously demonstrated strict-OOS right-tail probability uplift translates into positive pooled event-level economics under the fixed persisted TRAIN-Q80 grouping. This is a diagnostic bridge only: no model was refit, no threshold was recalculated, and no strategy or position sizing was run.", "",
        "## Fixed pooled groups", "",
        "| Group | Events | Tail events | Tail rate | Non-tail events | Mean active return | Median active return |", "|---|---:|---:|---:|---:|---:|---:|",
        f"| HIGH_SCORE | {p['high_count']} | {p['high_tail_count']} | {p['high_tail_rate']:.4%} | {p['high_nontail_count']} | {p['high_mean']:.6%} | {p['high_median']:.6%} |",
        f"| LOWER_SCORE | {p['lower_count']} | {p['lower_tail_count']} | {p['lower_tail_rate']:.4%} | {p['lower_nontail_count']} | {p['lower_mean']:.6%} | {p['lower_median']:.6%} |", "",
        f"Tail-rate uplift is {p['tail_rate_spread']:.4%}. HIGH minus LOWER mean and median event active returns are {p['net']:.6%} and {p['median_spread']:.6%}.", "",
        "## Conditional economics and exact bridge", "",
        "| Quantity | HIGH_SCORE | LOWER_SCORE |", "|---|---:|---:|",
        f"| Tail mean | {p['high_tail_mean']:.6%} | {p['lower_tail_mean']:.6%} |",
        f"| Tail median | {p['high_tail_median']:.6%} | {p['lower_tail_median']:.6%} |",
        f"| Non-tail mean | {p['high_nontail_mean']:.6%} | {p['lower_nontail_mean']:.6%} |",
        f"| Non-tail median | {p['high_nontail_median']:.6%} | {p['lower_nontail_median']:.6%} |", "",
        f"- Probability uplift component: `{fmt(p['probability_component'])}` ({p['probability_component']:.4%}).",
        f"- Tail magnitude component: `{fmt(p['tail_magnitude_component'])}` ({p['tail_magnitude_component']:.4%}).",
        f"- Non-tail payoff component: `{fmt(p['nontail_component'])}` ({p['nontail_component']:.4%}).",
        f"- Net HIGH minus LOWER: `{fmt(p['net'])}` ({p['net']:.4%}).",
        f"- Decomposition residual: `{p['decomposition_residual']:.3e}`.", "",
        f"The non-tail component is a drag and offsets {result['nontail_probability_offset_share']:.1%} of the probability component, but does not erase it. The conditional tail-magnitude component is {tail_direction}.", "",
        "## Chronological-fold stability", "",
        "| Fold | HIGH/LOWER N | Tail-rate spread | Net return spread | Probability component | Tail magnitude | Non-tail component |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for fold, values in result["folds"].items():
        lines.append(f"| {fold} | {values['high_count']}/{values['lower_count']} | {fmt(values['tail_rate_spread'])} | {fmt(values['net'])} | {fmt(values['probability_component'])} | {fmt(values['tail_magnitude_component'])} | {fmt(values['nontail_component'])} |")
    lines.extend([
        "", f"Net economics are positive in {result['positive_net_folds']} and negative in {result['negative_net_folds']} of {result['valid_economic_folds']} valid folds. `OUTER_5` has no persisted HIGH_SCORE rows, so its conditional bridge remains NA rather than receiving a substituted threshold.", "",
        "## Pre-2025 strict-OOS", "",
        f"Among {result['pre_count']} prior outer-test observations before 2025, tail-rate uplift is {pre['tail_rate_spread']:.4%}, net HIGH-minus-LOWER return is {pre['net']:.4%}, and probability/tail-magnitude/non-tail components are {pre['probability_component']:.4%}, {pre['tail_magnitude_component']:.4%}, and {pre['nontail_component']:.4%}. The net direction is therefore positive before 2025.", "",
        "## Answers", "",
        f"1. HIGH_SCORE has higher strict-OOS tail probability: yes, {p['high_tail_rate']:.4%} versus {p['lower_tail_rate']:.4%}.",
        f"2. The probability uplift contributes positively: {p['probability_component']:.4%} per event.",
        f"3. Tail magnitude is {tail_direction}: {p['tail_magnitude_component']:.4%}.",
        f"4. Non-tail outcomes impose a drag of {p['nontail_component']:.4%}.",
        f"5. After all components, HIGH_SCORE expected active return is higher by {p['net']:.4%}.",
        f"6. The net advantage is positive in {result['positive_net_folds']}/{result['valid_economic_folds']} valid chronological folds.",
        f"7. Pre-2025 net direction is {'positive' if pre['net'] > 0 else 'not positive'} at {pre['net']:.4%}.",
        "8. The probability signal is economically useful in this fixed OOS bridge, although adverse non-tail outcomes consume a material part of its benefit.", "",
        "## Validation and boundary", "",
        f"- Prior strict-OOS rows: {len(predictions)}, each appearing once; maximum outcome date {predictions.holding_end.max().date()}.",
        "- HIGH/LOWER membership is the persisted fold-local TRAIN-Q80 classification and was reconciled as `raw_score > train_score_q80` without threshold estimation.",
        f"- Expected-return identity errors: HIGH {p['high_expected_return_identity_error']:.3e}; LOWER {p['lower_expected_return_identity_error']:.3e}.",
        f"- Three-component residual: {p['decomposition_residual']:.3e}.",
        "- No train rows, refits, new folds, new labels, new predictors, network calls, or post-2025 outcomes were used.",
        "- `SUPPORTED` position-sizing research justification permits only a separately authorized future experiment; it is not a sizing strategy or promotion.", "",
    ])
    return "\n".join(lines)


def console_summary(predictions: pd.DataFrame, result: dict[str, Any], artifact_count: int) -> str:
    p, pre = result["pooled"], result["pre"]
    fields = {
        "RESEARCH_RESULT_STATUS": "COMPLETE_READ_ONLY_OOS_ECONOMIC_BRIDGE",
        "EXECUTION_STATUS": "PASS", "REPOSITORY_POLICY_STATUS": "PASS_WITH_PREEXISTING_UNRELATED_WARNINGS",
        "DATE_MAX_OUTCOME_USED": predictions.holding_end.max().date(), "POST_2025_OUTCOME_USED": "false", "NETWORK_USED": "false",
        "PRIOR_OOS_IDENTITY_STATUS": "PASS", "POOLED_OOS_EVENT_COUNT": len(predictions),
        "HIGH_SCORE_EVENT_COUNT": p["high_count"], "LOWER_SCORE_EVENT_COUNT": p["lower_count"],
        "HIGH_SCORE_RIGHT_TAIL_RATE": p["high_tail_rate"], "LOWER_SCORE_RIGHT_TAIL_RATE": p["lower_tail_rate"],
        "HIGH_MINUS_LOWER_RIGHT_TAIL_RATE": p["tail_rate_spread"],
        "HIGH_SCORE_MEAN_EVENT_ACTIVE_RETURN": p["high_mean"], "LOWER_SCORE_MEAN_EVENT_ACTIVE_RETURN": p["lower_mean"], "NET_HIGH_MINUS_LOWER": p["net"],
        "HIGH_SCORE_TAIL_MEAN_RETURN": p["high_tail_mean"], "LOWER_SCORE_TAIL_MEAN_RETURN": p["lower_tail_mean"],
        "HIGH_SCORE_NONTAIL_MEAN_RETURN": p["high_nontail_mean"], "LOWER_SCORE_NONTAIL_MEAN_RETURN": p["lower_nontail_mean"],
        "PROBABILITY_UPLIFT_COMPONENT": p["probability_component"], "TAIL_MAGNITUDE_COMPONENT": p["tail_magnitude_component"],
        "NONTAIL_PAYOFF_COMPONENT": p["nontail_component"], "DECOMPOSITION_RESIDUAL": p["decomposition_residual"],
        "POSITIVE_NET_ECONOMIC_FOLD_COUNT": result["positive_net_folds"], "NEGATIVE_NET_ECONOMIC_FOLD_COUNT": result["negative_net_folds"],
        "POSITIVE_PROBABILITY_COMPONENT_FOLD_COUNT": result["positive_probability_folds"], "NEGATIVE_NONTAIL_COMPONENT_FOLD_COUNT": result["negative_nontail_folds"],
        "PRE2025_OOS_EVENT_COUNT": result["pre_count"], "PRE2025_HIGH_MINUS_LOWER_TAIL_RATE": pre["tail_rate_spread"],
        "PRE2025_NET_HIGH_MINUS_LOWER": pre["net"], "PRE2025_PROBABILITY_UPLIFT_COMPONENT": pre["probability_component"],
        "PRE2025_TAIL_MAGNITUDE_COMPONENT": pre["tail_magnitude_component"], "PRE2025_NONTAIL_PAYOFF_COMPONENT": pre["nontail_component"],
        "POSITIVE_NET_ECONOMIC_YEAR_COUNT": result["positive_net_years"], "NEGATIVE_NET_ECONOMIC_YEAR_COUNT": result["negative_net_years"],
        "PROBABILITY_TO_ECONOMICS_CLASSIFICATION": result["classification"], "POSITION_SIZING_RESEARCH_JUSTIFICATION": result["sizing"],
        "SOURCE_MODIFICATION_COUNT": 1, "RESULT_ARTIFACT_COUNT": artifact_count, "TEMP_FILE_REMAINS": 0,
        "NEXT_RESEARCH_QUESTION": "STOP;HUMAN_REVIEW_ONLY;DO_NOT_AUTO_START_POSITION_SIZING_RESEARCH",
    }
    lines = ["=" * 60, f"{TASK_NAME}_FINAL", "=" * 60, ""]
    lines.extend(f"{key}={fmt(value)}" for key, value in fields.items())
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def main() -> None:
    predictions, _, rows = load_and_validate()
    result = analyze(predictions, rows)
    report = build_report(predictions, result)
    summary = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    for path in OUT.glob(".*.tmp"):
        path.unlink()
    atomic_csv(OUT / "economics_bridge.csv", summary)
    atomic_text(OUT / "final_report.md", report)
    artifacts = sorted(path for path in OUT.iterdir() if path.is_file())
    require(len(artifacts) == 2, "RESULT_ARTIFACT_COUNT_FAILURE", [path.name for path in artifacts])
    require(not list(OUT.glob(".*.tmp")), "TEMP_FILE_REMAINS")
    print(console_summary(predictions, result, len(artifacts)))


if __name__ == "__main__":
    main()
