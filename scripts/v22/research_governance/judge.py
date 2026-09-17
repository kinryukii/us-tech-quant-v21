"""Deterministic, fail-closed Research Trial Judge R1."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable

from .schemas import FoldRecord, MODEL_FAMILIES, TrialInput


TRUE = "TRUE"
FALSE = "FALSE"
UNKNOWN = "UNKNOWN"
NOT_EVALUATED = "NOT_EVALUATED"
CLASSIFICATIONS = {
    "A_STABLE_CHALLENGER",
    "B_PROMISING_BUT_UNPROVEN",
    "C_NO_MATERIAL_EDGE",
    "D_UNSTABLE",
    "E_INVALID",
}
FLAG_NAMES = (
    "SINGLE_PERIOD_DOMINATED",
    "HIGH_FOLD_VARIANCE",
    "NEGATIVE_MEDIAN_FOLD",
    "LOW_POSITIVE_FOLD_SUPPORT",
    "EXCESSIVE_TURNOVER",
    "WINNER_DESTRUCTION",
    "MAX_DRAWDOWN_DETERIORATION",
    "ECONOMIC_EDGE_WITHOUT_PREDICTIVE_SUPPORT",
    "PREDICTIVE_EDGE_WITHOUT_ECONOMIC_SUPPORT",
    "INSUFFICIENT_COMMON_SUPPORT",
    "MISSING_REQUIRED_METADATA",
    "TEMPORAL_SPLIT_INVALID",
    "2026_TRAINING_VIOLATION",
    "2026_MODEL_SELECTION_VIOLATION",
    "UNKNOWN_DATA_LINEAGE",
)
ECONOMIC_METRICS = ("cagr", "sharpe", "sortino", "calmar", "max_drawdown", "turnover", "cost")


@dataclass(frozen=True)
class JudgeThresholds:
    """Policy thresholds. Null scientific edge thresholds stay informational."""

    model_family: str = "ALPHA"
    predictive_metric: str = "rank_ic"
    economic_metric: str = "sharpe"
    stability_metric: str = "rank_ic"
    predictive_min_delta: float | None = None
    economic_min_delta: float | None = None
    minimum_common_folds: int = 3
    minimum_positive_fold_ratio: float = 0.5
    maximum_fold_metric_std: float | None = None
    maximum_turnover: float | None = None
    maximum_winner_damage: float | None = None
    dominance_metric: str = "sharpe"
    dominance_group_by: str = "fold"
    dominance_min_share: float = 0.5

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JudgeThresholds":
        known = {item.name for item in __import__("dataclasses").fields(cls)}
        unknown = set(payload) - known
        if unknown:
            raise ValueError(f"unknown threshold fields: {sorted(unknown)}")
        result = cls(**payload)
        if result.minimum_common_folds < 2:
            raise ValueError("minimum_common_folds must be at least 2")
        if result.model_family not in MODEL_FAMILIES:
            raise ValueError("threshold model_family must be ALPHA, RISK, or EXECUTION")
        if not 0.0 <= result.minimum_positive_fold_ratio <= 1.0:
            raise ValueError("minimum_positive_fold_ratio must be in [0, 1]")
        if result.dominance_group_by not in {"fold", "year"}:
            raise ValueError("dominance_group_by must be fold or year")
        if not 0.0 <= result.dominance_min_share <= 1.0:
            raise ValueError("dominance_min_share must be in [0, 1]")
        return result


def _state(value: bool | None) -> str:
    return NOT_EVALUATED if value is None else TRUE if value else FALSE


def _values(folds: Iterable[FoldRecord], metric: str) -> list[float]:
    return [value for fold in folds if (value := fold.metric(metric)) is not None]


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def predictive_quality(folds: tuple[FoldRecord, ...]) -> dict[str, Any]:
    rank_ic = _values(folds, "rank_ic")
    ndcg = _values(folds, "ndcg_at_20")
    return {
        "mean_rank_ic": _mean(rank_ic),
        "median_rank_ic": _median(rank_ic),
        "mean_ndcg20": _mean(ndcg),
        "median_ndcg20": _median(ndcg),
        "positive_ic_fold_count": sum(value > 0 for value in rank_ic),
        "negative_ic_fold_count": sum(value < 0 for value in rank_ic),
        "positive_fold_ratio": (sum(value > 0 for value in rank_ic) / len(rank_ic)) if rank_ic else None,
    }


def fold_stability(folds: tuple[FoldRecord, ...], metric: str) -> dict[str, Any]:
    observed = [(fold.fold_id, fold.metric(metric)) for fold in folds]
    observed = [(fold_id, value) for fold_id, value in observed if value is not None]
    if not observed:
        return {
            "metric": metric, "best_fold": None, "worst_fold": None, "fold_metric_std": None,
            "positive_fold_ratio": None, "negative_fold_ratio": None, "fold_count": 0,
        }
    values = [value for _, value in observed]
    return {
        "metric": metric,
        "best_fold": max(observed, key=lambda item: (item[1], item[0]))[0],
        "worst_fold": min(observed, key=lambda item: (item[1], item[0]))[0],
        "fold_metric_std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "positive_fold_ratio": sum(value > 0 for value in values) / len(values),
        "negative_fold_ratio": sum(value < 0 for value in values) / len(values),
        "fold_count": len(values),
    }


def _period_key(fold: FoldRecord, group_by: str) -> str | None:
    if group_by == "fold":
        return fold.period_id or fold.fold_id or None
    if fold.period_id:
        return fold.period_id
    return fold.validation_start[:4] if fold.validation_start and len(fold.validation_start) >= 4 else None


def _group_metric(folds: tuple[FoldRecord, ...], metric: str, group_by: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for fold in folds:
        key, value = _period_key(fold, group_by), fold.metric(metric)
        if key and value is not None:
            grouped.setdefault(key, []).append(value)
    return {key: statistics.fmean(values) for key, values in grouped.items()}


def single_period_dominance(
    candidate: tuple[FoldRecord, ...], benchmark: tuple[FoldRecord, ...], thresholds: JudgeThresholds,
    candidate_summary: dict[str, float | None] | Any, benchmark_summary: dict[str, float | None] | Any,
) -> dict[str, Any]:
    metric = thresholds.dominance_metric
    candidate_by = _group_metric(candidate, metric, thresholds.dominance_group_by)
    benchmark_by = _group_metric(benchmark, metric, thresholds.dominance_group_by)
    periods = sorted(set(candidate_by) & set(benchmark_by))
    if len(periods) < thresholds.minimum_common_folds:
        return {
            "status": NOT_EVALUATED, "single_period_dominated": NOT_EVALUATED,
            "dominant_period": None, "full_sample_delta": None, "leave_period_out_delta": None,
            "dominance_share": None, "leave_one_period_out": {}, "common_period_count": len(periods),
            "metric": metric, "group_by": thresholds.dominance_group_by,
        }
    candidate_full = candidate_summary.get(metric) if candidate_summary else None
    benchmark_full = benchmark_summary.get(metric) if benchmark_summary else None
    full_delta = (
        candidate_full - benchmark_full
        if candidate_full is not None and benchmark_full is not None
        else statistics.fmean(candidate_by[p] for p in periods) - statistics.fmean(benchmark_by[p] for p in periods)
    )
    contributions = {period: candidate_by[period] - benchmark_by[period] for period in periods}
    dominant = max(periods, key=lambda period: (contributions[period], period))
    positive_total = sum(max(0.0, value) for value in contributions.values())
    share = max(0.0, contributions[dominant]) / positive_total if positive_total > 0 else None
    leave_out = {
        removed: statistics.fmean(candidate_by[p] for p in periods if p != removed)
        - statistics.fmean(benchmark_by[p] for p in periods if p != removed)
        for removed in periods
    }
    dominant_leave_out = leave_out[dominant]
    dominated = bool(
        full_delta > 0
        and contributions[dominant] > 0
        and dominant_leave_out <= 0
        and share is not None
        and share >= thresholds.dominance_min_share
    )
    return {
        "status": "EVALUATED", "single_period_dominated": _state(dominated),
        "dominant_period": dominant, "full_sample_delta": full_delta,
        "leave_period_out_delta": dominant_leave_out, "dominance_share": share,
        "leave_one_period_out": leave_out, "common_period_count": len(periods),
        "metric": metric, "group_by": thresholds.dominance_group_by,
    }


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _is_unknown(value: Any) -> bool:
    return value is None or str(value).strip().upper() in {"", "UNKNOWN", "NOT_EVALUATED", "NA"}


def _bool_value(value: bool | str) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).upper()
    if text == "TRUE":
        return True
    if text == "FALSE":
        return False
    return None


def _delta(candidate: float | None, benchmark: float | None) -> float | None:
    return candidate - benchmark if candidate is not None and benchmark is not None else None


def _threshold_pass(delta: float | None, threshold: float | None) -> bool | None:
    return None if delta is None or threshold is None else delta > threshold


def evaluate_trial(
    trial: TrialInput,
    thresholds: JudgeThresholds | None = None,
    *,
    expected_benchmark_id: str | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or JudgeThresholds()
    flags = {name: NOT_EVALUATED for name in FLAG_NAMES}
    reasons: list[str] = []

    required = {
        "trial_id": trial.trial_id, "model_id": trial.model_id, "model_family": trial.model_family,
        "feature_set_id": trial.feature_set_id, "parameter_set_id": trial.parameter_set_id,
        "benchmark_id": trial.benchmark_id, "training_cutoff": trial.training_cutoff,
        "universe_id": trial.universe_id, "data_lineage": trial.data_lineage,
    }
    missing = sorted(name for name, value in required.items() if _is_unknown(value))
    boolean_metadata = {
        "uses_2026_training": _bool_value(trial.uses_2026_training),
        "uses_2026_parameter_search": _bool_value(trial.uses_2026_parameter_search),
        "uses_2026_model_selection": _bool_value(trial.uses_2026_model_selection),
    }
    missing.extend(name for name, value in boolean_metadata.items() if value is None)
    if not trial.folds:
        missing.append("folds")
    flags["MISSING_REQUIRED_METADATA"] = _state(bool(missing))
    if missing:
        reasons.append("missing_required_metadata:" + ",".join(sorted(set(missing))))

    lineage_unknown = _is_unknown(trial.data_lineage) or _is_unknown(trial.universe_id)
    flags["UNKNOWN_DATA_LINEAGE"] = _state(lineage_unknown)
    if lineage_unknown:
        reasons.append("unknown_data_lineage")

    temporal_invalid = False
    training_2026_count = 0
    cutoff_2026 = date(2026, 1, 1)
    for fold in trial.folds:
        train_end, validation_start = _parse_date(fold.train_end), _parse_date(fold.validation_start)
        if train_end is None or validation_start is None or train_end >= validation_start:
            temporal_invalid = True
        if train_end is not None and train_end >= cutoff_2026:
            training_2026_count += 1
    flags["TEMPORAL_SPLIT_INVALID"] = _state(temporal_invalid)
    if temporal_invalid:
        reasons.append("temporal_split_invalid")

    training_cutoff = _parse_date(trial.training_cutoff)
    training_violation = bool(
        training_2026_count
        or (training_cutoff is not None and training_cutoff >= cutoff_2026)
        or boolean_metadata["uses_2026_training"] is True
    )
    flags["2026_TRAINING_VIOLATION"] = _state(training_violation)
    if training_violation:
        reasons.append("2026_training_forbidden")
    selection_violation = bool(
        boolean_metadata["uses_2026_parameter_search"] is True
        or boolean_metadata["uses_2026_model_selection"] is True
    )
    flags["2026_MODEL_SELECTION_VIOLATION"] = _state(selection_violation)
    if selection_violation:
        reasons.append("2026_parameter_or_model_selection_forbidden")

    if trial.model_family not in MODEL_FAMILIES:
        reasons.append("invalid_model_family")
    if trial.model_family != thresholds.model_family:
        reasons.append("threshold_family_mismatch")
    if trial.pit_status != "PASS":
        reasons.append("pit_status_not_pass")
    if expected_benchmark_id and trial.benchmark_id != expected_benchmark_id:
        reasons.append("benchmark_mismatch")

    predictive = predictive_quality(trial.folds)
    stability = {
        "rank_ic": fold_stability(trial.folds, "rank_ic"),
        "sharpe": fold_stability(trial.folds, "sharpe"),
    }
    selected_stability = stability[thresholds.stability_metric]
    dominance = single_period_dominance(
        trial.folds, trial.benchmark_folds, thresholds,
        trial.economic_summary, trial.benchmark_summary,
    )
    flags["SINGLE_PERIOD_DOMINATED"] = dominance["single_period_dominated"]

    common_support = dominance["common_period_count"]
    flags["INSUFFICIENT_COMMON_SUPPORT"] = _state(common_support < thresholds.minimum_common_folds)
    median_value = _median(_values(trial.folds, thresholds.stability_metric))
    flags["NEGATIVE_MEDIAN_FOLD"] = _state(None if median_value is None else median_value < 0)
    positive_ratio = selected_stability["positive_fold_ratio"]
    flags["LOW_POSITIVE_FOLD_SUPPORT"] = _state(
        None if positive_ratio is None else positive_ratio < thresholds.minimum_positive_fold_ratio
    )
    flags["HIGH_FOLD_VARIANCE"] = _state(
        None if thresholds.maximum_fold_metric_std is None or selected_stability["fold_metric_std"] is None
        else selected_stability["fold_metric_std"] > thresholds.maximum_fold_metric_std
    )

    economic = {metric: trial.economic_summary.get(metric) for metric in ECONOMIC_METRICS}
    deltas = {
        metric: _delta(trial.economic_summary.get(metric), trial.benchmark_summary.get(metric))
        for metric in ECONOMIC_METRICS
    }
    turnover = economic["turnover"]
    flags["EXCESSIVE_TURNOVER"] = _state(
        None if turnover is None or thresholds.maximum_turnover is None else turnover > thresholds.maximum_turnover
    )
    winner_damage = trial.economic_summary.get("winner_damage")
    flags["WINNER_DESTRUCTION"] = _state(
        None if winner_damage is None or thresholds.maximum_winner_damage is None
        else winner_damage > thresholds.maximum_winner_damage
    )
    maxdd_delta = deltas["max_drawdown"]
    flags["MAX_DRAWDOWN_DETERIORATION"] = _state(None if maxdd_delta is None else maxdd_delta < 0)

    predictive_candidate = _mean(_values(trial.folds, thresholds.predictive_metric))
    predictive_benchmark = _mean(_values(trial.benchmark_folds, thresholds.predictive_metric))
    if predictive_benchmark is None:
        predictive_benchmark = trial.benchmark_summary.get(thresholds.predictive_metric)
    predictive_delta = _delta(predictive_candidate, predictive_benchmark)
    economic_delta = deltas.get(thresholds.economic_metric)
    predictive_pass = _threshold_pass(predictive_delta, thresholds.predictive_min_delta)
    economic_pass = _threshold_pass(economic_delta, thresholds.economic_min_delta)
    flags["ECONOMIC_EDGE_WITHOUT_PREDICTIVE_SUPPORT"] = _state(
        None if economic_pass is None else economic_pass and predictive_pass is not True
    )
    flags["PREDICTIVE_EDGE_WITHOUT_ECONOMIC_SUPPORT"] = _state(
        None if predictive_pass is None else predictive_pass and economic_pass is not True
    )

    invalid = bool(
        missing or lineage_unknown or temporal_invalid or training_violation or selection_violation
        or trial.model_family not in MODEL_FAMILIES or trial.model_family != thresholds.model_family
        or trial.pit_status != "PASS"
        or (expected_benchmark_id and trial.benchmark_id != expected_benchmark_id)
    )
    unstable_names = (
        "SINGLE_PERIOD_DOMINATED", "HIGH_FOLD_VARIANCE", "NEGATIVE_MEDIAN_FOLD",
        "LOW_POSITIVE_FOLD_SUPPORT", "EXCESSIVE_TURNOVER", "WINNER_DESTRUCTION",
        "MAX_DRAWDOWN_DETERIORATION",
    )
    unstable = any(flags[name] == TRUE for name in unstable_names)
    stable_gates_evaluated_and_clear = all(
        flags[name] == FALSE for name in (
            "SINGLE_PERIOD_DOMINATED", "HIGH_FOLD_VARIANCE", "NEGATIVE_MEDIAN_FOLD",
            "LOW_POSITIVE_FOLD_SUPPORT", "EXCESSIVE_TURNOVER", "WINNER_DESTRUCTION",
            "MAX_DRAWDOWN_DETERIORATION", "INSUFFICIENT_COMMON_SUPPORT",
        )
    )
    if invalid:
        classification = "E_INVALID"
    elif unstable:
        classification = "D_UNSTABLE"
    elif (
        predictive_pass is True and economic_pass is True and stable_gates_evaluated_and_clear
    ):
        classification = "A_STABLE_CHALLENGER"
    elif predictive_pass is False and economic_pass is False:
        classification = "C_NO_MATERIAL_EDGE"
    else:
        classification = "B_PROMISING_BUT_UNPROVEN"
    assert classification in CLASSIFICATIONS

    if thresholds.predictive_min_delta is None:
        reasons.append(f"{thresholds.predictive_metric}_threshold_informational_only")
    if thresholds.economic_min_delta is None:
        reasons.append(f"{thresholds.economic_metric}_threshold_informational_only")
    if classification == "D_UNSTABLE":
        reasons.extend(name.lower() for name in unstable_names if flags[name] == TRUE)

    return {
        "schema_version": "1.0.0",
        "judge": "A2_RESEARCH_TRIAL_JUDGE_R1",
        "trial_id": trial.trial_id,
        "model_id": trial.model_id,
        "model_family": trial.model_family,
        "benchmark_id": trial.benchmark_id,
        "data_validity": "INVALID" if invalid else "VALID",
        "temporal_validity": "INVALID" if temporal_invalid else "VALID",
        "pit_status": trial.pit_status,
        "2026_training_rows": training_2026_count,
        "2026_selection_status": flags["2026_MODEL_SELECTION_VIOLATION"],
        "predictive": predictive,
        "predictive_delta": predictive_delta,
        "economic": economic,
        "vs_champion": {f"delta_{metric}": value for metric, value in deltas.items()},
        "stability": stability,
        "single_period_dominance": dominance,
        "flags": flags,
        "classification": classification,
        "classification_reasons": sorted(set(reasons)),
        "thresholds": asdict(thresholds),
        "promotion_eligible": False,
        "user_authorization_required": True,
        "auto_promotion_forbidden": True,
    }


def _shown(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def render_scorecard(result: dict[str, Any]) -> str:
    predictive, economic = result["predictive"], result["economic"]
    deltas, dominance = result["vs_champion"], result["single_period_dominance"]
    stability = result["stability"][result["thresholds"]["stability_metric"]]
    active_flags = [name for name, state in result["flags"].items() if state in {TRUE, UNKNOWN, NOT_EVALUATED}]
    lines = [
        "=" * 50, "RESEARCH TRIAL JUDGE R1", "=" * 50, "",
        f"TRIAL_ID={result['trial_id']}", f"MODEL_ID={result['model_id']}",
        f"MODEL_FAMILY={result['model_family']}", f"BENCHMARK_ID={result['benchmark_id']}", "",
        f"DATA_VALIDITY={result['data_validity']}", f"TEMPORAL_VALIDITY={result['temporal_validity']}",
        f"PIT_STATUS={result['pit_status']}", f"2026_TRAINING_ROWS={result['2026_training_rows']}",
        f"2026_SELECTION_STATUS={result['2026_selection_status']}", "", "PREDICTIVE:",
        f"  MEAN_RANK_IC={_shown(predictive['mean_rank_ic'])}",
        f"  MEDIAN_RANK_IC={_shown(predictive['median_rank_ic'])}",
        f"  MEAN_NDCG20={_shown(predictive['mean_ndcg20'])}",
        f"  POSITIVE_FOLD_RATIO={_shown(predictive['positive_fold_ratio'])}", "", "ECONOMIC:",
        f"  CAGR={_shown(economic['cagr'])}", f"  SHARPE={_shown(economic['sharpe'])}",
        f"  CALMAR={_shown(economic['calmar'])}", f"  MAX_DRAWDOWN={_shown(economic['max_drawdown'])}",
        f"  TURNOVER={_shown(economic['turnover'])}", "", "VS_CHAMPION:",
        f"  DELTA_CAGR={_shown(deltas['delta_cagr'])}", f"  DELTA_SHARPE={_shown(deltas['delta_sharpe'])}",
        f"  DELTA_CALMAR={_shown(deltas['delta_calmar'])}",
        f"  DELTA_MAXDD={_shown(deltas['delta_max_drawdown'])}",
        f"  DELTA_TURNOVER={_shown(deltas['delta_turnover'])}", "", "STABILITY:",
        f"  BEST_FOLD={_shown(stability['best_fold'])}", f"  WORST_FOLD={_shown(stability['worst_fold'])}",
        f"  FOLD_METRIC_STD={_shown(stability['fold_metric_std'])}",
        f"  SINGLE_PERIOD_DOMINATED={dominance['single_period_dominated']}",
        f"  DOMINANT_PERIOD={_shown(dominance['dominant_period'])}", "",
        f"FLAGS={','.join(active_flags) if active_flags else 'NONE'}",
        f"CLASSIFICATION={result['classification']}", "",
        f"PROMOTION_ELIGIBLE={str(result['promotion_eligible']).upper()}",
        f"USER_AUTHORIZATION_REQUIRED={str(result['user_authorization_required']).upper()}", "=" * 50,
    ]
    return "\n".join(lines) + "\n"


def result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
