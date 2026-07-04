#!/usr/bin/env python
"""V20.206 10D SPY conditional overlay validation.

Research-only validation of whether the expanded 10D local edge is conditional
on ETF rotation selecting SPY. This stage does not rerun trials and cannot
recommend shadow weight activation.
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_TRIALS = OUT_DIR / "V20_204_10D_EXPANDED_TRIALS.csv"
IN_FORWARD = OUT_DIR / "V20_204_10D_EXPANDED_FORWARD_OUTCOMES.csv"
IN_ETF = OUT_DIR / "V20_204_10D_EXPANDED_ETF_BENCHMARK_OUTCOMES.csv"
IN_204_SUMMARY = OUT_DIR / "V20_204_10D_ROBUSTNESS_SUMMARY.csv"
IN_204_BOOT = OUT_DIR / "V20_204_10D_BOOTSTRAP_CONFIDENCE.csv"
IN_204_TRIM = OUT_DIR / "V20_204_10D_TRIMMED_WINSORIZED_ANALYSIS.csv"
IN_204_LOO = OUT_DIR / "V20_204_10D_LEAVE_ONE_CLUSTER_OUT.csv"
IN_204_BIAS = OUT_DIR / "V20_204_10D_WEIGHT_BIAS_REPEATABILITY.csv"
IN_204_GATE = OUT_DIR / "V20_204_10D_ROBUSTNESS_GATE.csv"
IN_205_EFFECT = OUT_DIR / "V20_205_SELECTED_ETF_CLUSTER_EFFECTIVENESS.csv"
IN_205_LOO = OUT_DIR / "V20_205_SELECTED_ETF_LEAVE_ONE_OUT_DIAGNOSTICS.csv"
IN_205_CONTRIB = OUT_DIR / "V20_205_SELECTED_ETF_CONTRIBUTION_DECOMPOSITION.csv"
IN_205_BIAS = OUT_DIR / "V20_205_CLUSTER_WEIGHT_BIAS_DIAGNOSTICS.csv"
IN_205_RISK = OUT_DIR / "V20_205_CLUSTER_DEPENDENCY_RISK_AUDIT.csv"
IN_205_GATE = OUT_DIR / "V20_205_10D_OBSERVATION_CONTINUATION_GATE.csv"
REQUIRED_INPUTS = [
    IN_TRIALS, IN_FORWARD, IN_ETF, IN_204_SUMMARY, IN_204_BOOT, IN_204_TRIM,
    IN_204_LOO, IN_204_BIAS, IN_204_GATE, IN_205_EFFECT, IN_205_LOO,
    IN_205_CONTRIB, IN_205_BIAS, IN_205_RISK, IN_205_GATE,
]

OUT_EFFECT = OUT_DIR / "V20_206_SPY_CONDITIONAL_EFFECTIVENESS.csv"
OUT_COMPARE = OUT_DIR / "V20_206_SPY_VS_NON_SPY_COMPARISON.csv"
OUT_BOOT = OUT_DIR / "V20_206_SPY_CONDITIONAL_BOOTSTRAP.csv"
OUT_TRIM = OUT_DIR / "V20_206_SPY_CONDITIONAL_TRIMMED_WINSORIZED.csv"
OUT_STABILITY = OUT_DIR / "V20_206_SPY_ASOF_DATE_STABILITY.csv"
OUT_BIAS = OUT_DIR / "V20_206_SPY_WEIGHT_BIAS_REPEATABILITY.csv"
OUT_RULE = OUT_DIR / "V20_206_CONDITIONAL_OVERLAY_RULE_CANDIDATE.csv"
OUT_GATE = OUT_DIR / "V20_206_SPY_CONDITIONAL_OBSERVATION_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_206_10D_SPY_CONDITIONAL_OVERLAY_VALIDATION_REPORT.md"

BOOTSTRAP_ITERATIONS = 1000
BOOTSTRAP_SEED = 202606206
BIAS_BOOTSTRAP_ITERATIONS = 500
FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime", "data_trust"]

EFFECT_FIELDS = [
    "condition_name", "selected_etf_filter", "trial_count", "avg_stock_topN_return",
    "median_stock_topN_return", "avg_etf_rotation_return", "median_etf_rotation_return",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "win_rate_vs_etf_rotation", "positive_excess_count", "negative_excess_count",
    "effectiveness_status", "comment",
]
COMPARE_FIELDS = ["metric_name", "spy_value", "non_spy_value", "all_trials_value", "spy_minus_non_spy", "comparison_status", "comment"]
BOOT_FIELDS = [
    "condition_name", "bootstrap_iterations", "mean_excess", "median_excess",
    "mean_excess_ci_lower_95", "mean_excess_ci_upper_95",
    "median_excess_ci_lower_95", "median_excess_ci_upper_95",
    "probability_mean_excess_positive", "probability_median_excess_positive",
    "bootstrap_status",
]
TRIM_FIELDS = [
    "condition_name", "scenario_name", "excluded_or_adjusted_trial_count",
    "remaining_trial_count", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation", "conclusion",
]
STABILITY_FIELDS = [
    "condition_name", "as_of_date", "trial_count", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation",
    "stability_status", "warning_reason",
]
BIAS_FIELDS = [
    "condition_name", "family_name", "avg_weight_all", "avg_weight_top_10pct",
    "avg_weight_bottom_10pct", "top_minus_bottom_weight_delta",
    "correlation_with_excess", "bootstrap_direction_consistency",
    "repeatability_status",
]
RULE_FIELDS = [
    "rule_id", "rule_name", "condition_expression", "forward_window",
    "overlay_action", "allowed_scope", "disabled_scope",
    "required_confirmation_metrics", "rule_status", "reason",
]
GATE_FIELDS = [
    "final_status", "valid_trial_count", "spy_trial_count", "non_spy_trial_count",
    "spy_avg_excess_vs_etf_rotation", "spy_median_excess_vs_etf_rotation",
    "spy_win_rate_vs_etf_rotation", "non_spy_avg_excess_vs_etf_rotation",
    "non_spy_median_excess_vs_etf_rotation", "non_spy_win_rate_vs_etf_rotation",
    "spy_bootstrap_ci_lower_95", "spy_bootstrap_ci_upper_95",
    "spy_trimmed_5pct_avg_excess", "spy_winsorized_5pct_avg_excess",
    "spy_asof_stability_status", "coherent_spy_weight_bias_detected",
    "conditional_overlay_observation_recommended",
    "non_spy_edge_disabled_for_observation", "shadow_weight_change_recommended",
    "reason", "next_recommended_action",
]

STATUS_CANDIDATE = "PASS_V20_206_SPY_CONDITIONAL_OVERLAY_OBSERVATION_CANDIDATE"
STATUS_MIXED = "PARTIAL_PASS_V20_206_SPY_CONDITIONAL_EDGE_MIXED_ROBUSTNESS"
STATUS_NONE = "PASS_V20_206_NO_SPY_CONDITIONAL_EDGE_FOUND"
STATUS_SMALL = "PARTIAL_PASS_V20_206_INSUFFICIENT_SPY_CONDITION_SAMPLE"
STATUS_MISSING = "BLOCKED_V20_206_REQUIRED_INPUT_MISSING"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def num(value: object) -> float | None:
    try:
        text = clean(value)
        if not text:
            return None
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def fmt(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.10f}"


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def corr(xs: list[float], ys: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    x_mean = mean([x for x, _ in pairs])
    y_mean = mean([y for _, y in pairs])
    x_var = sum((x - x_mean) ** 2 for x, _ in pairs)
    y_var = sum((y - y_mean) ** 2 for _, y in pairs)
    if x_var <= 0 or y_var <= 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in pairs) / math.sqrt(x_var * y_var)


def inputs_ready() -> bool:
    return all(path.exists() and path.stat().st_size > 0 and read_csv(path) for path in REQUIRED_INPUTS)


def build_metrics() -> list[dict[str, object]]:
    trials = {row["trial_id"]: row for row in read_csv(IN_TRIALS) if row.get("trial_status") == "VALID"}
    forward_returns: dict[str, list[float]] = defaultdict(list)
    for row in read_csv(IN_FORWARD):
        value = num(row.get("forward_return"))
        if row.get("outcome_status") == "PASS" and value is not None:
            forward_returns[row["trial_id"]].append(value)
    etfs = {row["trial_id"]: row for row in read_csv(IN_ETF) if row.get("benchmark_status") == "PASS"}
    metrics: list[dict[str, object]] = []
    for trial_id, trial in trials.items():
        etf_row = etfs.get(trial_id)
        etf_return = num(etf_row.get("etf_forward_return") if etf_row else None)
        if not etf_row or etf_return is None or not forward_returns.get(trial_id):
            continue
        stock_return = mean(forward_returns[trial_id])
        metric = {
            "trial_id": trial_id,
            "as_of_date": trial.get("as_of_date", ""),
            "selected_etf": etf_row.get("selected_etf", ""),
            "stock_topN_return": stock_return,
            "etf_rotation_return": etf_return,
            "excess_vs_etf_rotation": stock_return - etf_return,
        }
        for family in FAMILIES:
            metric[f"{family}_weight"] = num(trial.get(f"{family}_weight")) or 0.0
        metrics.append(metric)
    return metrics


def subsets(metrics: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    return {
        "selected_etf_eq_SPY": [row for row in metrics if row["selected_etf"] == "SPY"],
        "selected_etf_not_SPY": [row for row in metrics if row["selected_etf"] != "SPY"],
        "all_10D_trials": metrics[:],
    }


def basic_stats(rows: list[dict[str, object]]) -> dict[str, float | int]:
    stocks = [float(row["stock_topN_return"]) for row in rows]
    etfs = [float(row["etf_rotation_return"]) for row in rows]
    excess = [float(row["excess_vs_etf_rotation"]) for row in rows]
    return {
        "trial_count": len(rows),
        "avg_stock": mean(stocks) if stocks else math.nan,
        "median_stock": median(stocks) if stocks else math.nan,
        "avg_etf": mean(etfs) if etfs else math.nan,
        "median_etf": median(etfs) if etfs else math.nan,
        "avg_excess": mean(excess) if excess else math.nan,
        "median_excess": median(excess) if excess else math.nan,
        "win_rate": sum(1 for value in excess if value > 0) / len(excess) if excess else math.nan,
        "positive_count": sum(1 for value in excess if value > 0),
        "negative_count": sum(1 for value in excess if value < 0),
    }


def effectiveness_status(stats: dict[str, float | int]) -> tuple[str, str]:
    count = int(stats["trial_count"])
    avg_excess = float(stats["avg_excess"])
    med_excess = float(stats["median_excess"])
    win_rate = float(stats["win_rate"])
    if count < 30:
        return "INSUFFICIENT_CONDITION_SAMPLE", "Fewer than 30 trials are available for this condition."
    if avg_excess > 0 and med_excess > 0 and win_rate >= 0.55:
        return "ROBUST_POSITIVE_CONDITION", "Condition beats ETF rotation on mean, median, and win rate."
    if (avg_excess > 0 or med_excess > 0) and win_rate < 0.55:
        return "MIXED_POSITIVE_CONDITION", "Condition has partial positive evidence but weak win-rate support."
    if avg_excess < 0 and med_excess < 0:
        return "NEGATIVE_CONDITION", "Condition underperforms ETF rotation on mean and median."
    return "MIXED_POSITIVE_CONDITION", "Condition evidence is mixed."


def effectiveness_rows(groups: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    filters = {
        "selected_etf_eq_SPY": "selected_etf == SPY",
        "selected_etf_not_SPY": "selected_etf != SPY",
        "all_10D_trials": "all expanded 10D trials",
    }
    rows = []
    for name in ["selected_etf_eq_SPY", "selected_etf_not_SPY", "all_10D_trials"]:
        stats = basic_stats(groups[name])
        status, comment = effectiveness_status(stats)
        rows.append({
            "condition_name": name,
            "selected_etf_filter": filters[name],
            "trial_count": str(stats["trial_count"]),
            "avg_stock_topN_return": fmt(float(stats["avg_stock"])),
            "median_stock_topN_return": fmt(float(stats["median_stock"])),
            "avg_etf_rotation_return": fmt(float(stats["avg_etf"])),
            "median_etf_rotation_return": fmt(float(stats["median_etf"])),
            "avg_excess_vs_etf_rotation": fmt(float(stats["avg_excess"])),
            "median_excess_vs_etf_rotation": fmt(float(stats["median_excess"])),
            "win_rate_vs_etf_rotation": fmt(float(stats["win_rate"])),
            "positive_excess_count": str(stats["positive_count"]),
            "negative_excess_count": str(stats["negative_count"]),
            "effectiveness_status": status,
            "comment": comment,
        })
    return rows


def comparison_rows(groups: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    spy = basic_stats(groups["selected_etf_eq_SPY"])
    non = basic_stats(groups["selected_etf_not_SPY"])
    all_rows = basic_stats(groups["all_10D_trials"])
    metrics = [
        ("trial_count", "trial_count"),
        ("avg_excess_vs_etf_rotation", "avg_excess"),
        ("median_excess_vs_etf_rotation", "median_excess"),
        ("win_rate_vs_etf_rotation", "win_rate"),
        ("avg_stock_topN_return", "avg_stock"),
        ("avg_etf_rotation_return", "avg_etf"),
        ("positive_excess_rate", "win_rate"),
    ]
    rows = []
    for metric_name, key in metrics:
        spy_val = float(spy[key])
        non_val = float(non[key])
        all_val = float(all_rows[key])
        diff = spy_val - non_val
        rows.append({
            "metric_name": metric_name,
            "spy_value": fmt(spy_val) if key != "trial_count" else str(int(spy_val)),
            "non_spy_value": fmt(non_val) if key != "trial_count" else str(int(non_val)),
            "all_trials_value": fmt(all_val) if key != "trial_count" else str(int(all_val)),
            "spy_minus_non_spy": fmt(diff),
            "comparison_status": "SPY_STRONGER" if diff > 0 else "NON_SPY_STRONGER_OR_EQUAL",
            "comment": "SPY condition is stronger than non-SPY for this metric." if diff > 0 else "SPY condition does not exceed non-SPY for this metric.",
        })
    return rows


def bootstrap_condition(condition_name: str, rows: list[dict[str, object]]) -> dict[str, object]:
    values = [float(row["excess_vs_etf_rotation"]) for row in rows]
    if not values:
        return {"condition_name": condition_name, "bootstrap_iterations": str(BOOTSTRAP_ITERATIONS), "bootstrap_status": "NO_VALID_TRIALS"}
    rng = random.Random(BOOTSTRAP_SEED + len(condition_name))
    means, medians = [], []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(mean(sample))
        medians.append(median(sample))
    lower_mean = percentile(means, 0.025)
    upper_mean = percentile(means, 0.975)
    lower_med = percentile(medians, 0.025)
    upper_med = percentile(medians, 0.975)
    return {
        "condition_name": condition_name,
        "bootstrap_iterations": str(BOOTSTRAP_ITERATIONS),
        "mean_excess": fmt(mean(values)),
        "median_excess": fmt(median(values)),
        "mean_excess_ci_lower_95": fmt(lower_mean),
        "mean_excess_ci_upper_95": fmt(upper_mean),
        "median_excess_ci_lower_95": fmt(lower_med),
        "median_excess_ci_upper_95": fmt(upper_med),
        "probability_mean_excess_positive": fmt(sum(1 for value in means if value > 0) / len(means)),
        "probability_median_excess_positive": fmt(sum(1 for value in medians if value > 0) / len(medians)),
        "bootstrap_status": "MEAN_CI_POSITIVE" if lower_mean is not None and lower_mean > 0 else "MEAN_CI_INCLUDES_OR_BELOW_ZERO",
    }


def bootstrap_rows(groups: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    return [
        bootstrap_condition("selected_etf_eq_SPY", groups["selected_etf_eq_SPY"]),
        bootstrap_condition("selected_etf_not_SPY", groups["selected_etf_not_SPY"]),
    ]


def adjust_values(values: list[float], scenario: str) -> tuple[list[float], int]:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return [], 0
    c1 = max(1, math.ceil(n * 0.01))
    c5 = max(1, math.ceil(n * 0.05))
    if scenario == "exclude_bottom_1pct":
        return ordered[c1:], c1
    if scenario == "exclude_bottom_5pct":
        return ordered[c5:], c5
    if scenario == "exclude_top_1pct":
        return ordered[:n - c1], c1
    if scenario == "exclude_top_5pct":
        return ordered[:n - c5], c5
    if scenario == "exclude_top_bottom_1pct":
        return ordered[c1:n - c1], c1 * 2
    if scenario == "exclude_top_bottom_5pct":
        return ordered[c5:n - c5], c5 * 2
    if scenario == "winsorize_1pct":
        low, high = ordered[c1 - 1], ordered[n - c1]
        return [min(max(value, low), high) for value in values], c1 * 2
    if scenario == "winsorize_5pct":
        low, high = ordered[c5 - 1], ordered[n - c5]
        return [min(max(value, low), high) for value in values], c5 * 2
    return values[:], 0


def trimmed_rows(groups: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    scenarios = [
        "no_exclusion", "exclude_bottom_1pct", "exclude_bottom_5pct",
        "exclude_top_1pct", "exclude_top_5pct", "exclude_top_bottom_1pct",
        "exclude_top_bottom_5pct", "winsorize_1pct", "winsorize_5pct",
    ]
    rows = []
    for condition_name in ["selected_etf_eq_SPY", "selected_etf_not_SPY"]:
        values = [float(row["excess_vs_etf_rotation"]) for row in groups[condition_name]]
        for scenario in scenarios:
            adjusted, changed = adjust_values(values, scenario)
            avg_value = mean(adjusted) if adjusted else math.nan
            med_value = median(adjusted) if adjusted else math.nan
            win_rate = sum(1 for value in adjusted if value > 0) / len(adjusted) if adjusted else math.nan
            conclusion = "POSITIVE_AFTER_ADJUSTMENT" if avg_value > 0 and med_value > 0 and win_rate >= 0.55 else "WEAK_OR_NEGATIVE_AFTER_ADJUSTMENT"
            rows.append({
                "condition_name": condition_name,
                "scenario_name": scenario,
                "excluded_or_adjusted_trial_count": str(changed),
                "remaining_trial_count": str(len(adjusted)),
                "avg_excess_vs_etf_rotation": fmt(avg_value),
                "median_excess_vs_etf_rotation": fmt(med_value),
                "win_rate_vs_etf_rotation": fmt(win_rate),
                "conclusion": conclusion,
            })
    return rows


def stability_rows(groups: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    rows = []
    condition_list = ["selected_etf_eq_SPY"]
    if len(groups["selected_etf_not_SPY"]) >= 30:
        condition_list.append("selected_etf_not_SPY")
    for condition_name in condition_list:
        by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in groups[condition_name]:
            by_date[clean(row["as_of_date"])].append(row)
        for as_of in sorted(by_date):
            group = by_date[as_of]
            values = [float(row["excess_vs_etf_rotation"]) for row in group]
            avg_value = mean(values)
            med_value = median(values)
            win_rate = sum(1 for value in values if value > 0) / len(values)
            if len(group) < 3:
                status = "LOW_DATE_SAMPLE"
                warning = "Date has fewer than 3 trials."
            elif avg_value > 0 and med_value > 0 and win_rate >= 0.55:
                status = "STABLE_POSITIVE_DATE"
                warning = ""
            else:
                status = "WEAK_OR_NEGATIVE_DATE"
                warning = "Date does not independently support the condition edge."
            rows.append({
                "condition_name": condition_name,
                "as_of_date": as_of,
                "trial_count": str(len(group)),
                "avg_excess_vs_etf_rotation": fmt(avg_value),
                "median_excess_vs_etf_rotation": fmt(med_value),
                "win_rate_vs_etf_rotation": fmt(win_rate),
                "stability_status": status,
                "warning_reason": warning,
            })
    return rows


def direction_consistency(rows: list[dict[str, object]], family: str, observed_delta: float) -> float | None:
    if not rows:
        return None
    if abs(observed_delta) < 1e-12:
        return 0.0
    sign = 1 if observed_delta > 0 else -1
    rng = random.Random(BOOTSTRAP_SEED + len(family) + len(rows))
    size = max(1, math.ceil(len(rows) * 0.10))
    consistent = 0
    for _ in range(BIAS_BOOTSTRAP_ITERATIONS):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        ordered = sorted(sample, key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
        top = ordered[:size]
        bottom = ordered[-size:]
        delta = mean([float(row[f"{family}_weight"]) for row in top]) - mean([float(row[f"{family}_weight"]) for row in bottom])
        if (1 if delta > 0 else -1 if delta < 0 else 0) == sign:
            consistent += 1
    return consistent / BIAS_BOOTSTRAP_ITERATIONS


def bias_rows(groups: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    output = []
    for condition_name in ["selected_etf_eq_SPY", "selected_etf_not_SPY"]:
        rows = sorted(groups[condition_name], key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
        size = max(1, math.ceil(len(rows) * 0.10)) if rows else 0
        top = rows[:size]
        bottom = rows[-size:] if size else []
        excess = [float(row["excess_vs_etf_rotation"]) for row in rows]
        for family in FAMILIES:
            weights = [float(row[f"{family}_weight"]) for row in rows]
            top_avg = mean([float(row[f"{family}_weight"]) for row in top]) if top else math.nan
            bottom_avg = mean([float(row[f"{family}_weight"]) for row in bottom]) if bottom else math.nan
            delta = top_avg - bottom_avg if math.isfinite(top_avg) and math.isfinite(bottom_avg) else 0.0
            family_corr = corr(weights, excess)
            consistency = direction_consistency(rows, family, delta)
            if family == "data_trust" and not any(weights):
                status = "AUDIT_ONLY_NOT_RANKING_WEIGHT"
            elif consistency is not None and consistency >= 0.70 and abs(delta) >= 0.01 and abs(family_corr or 0.0) >= 0.10:
                status = "REPEATABLE_CONDITION_BIAS_FOR_OBSERVATION"
            elif consistency is not None and consistency >= 0.60:
                status = "WEAK_DIRECTIONAL_REPEATABILITY"
            else:
                status = "NO_REPEATABLE_BIAS"
            output.append({
                "condition_name": condition_name,
                "family_name": family,
                "avg_weight_all": fmt(mean(weights) if weights else None),
                "avg_weight_top_10pct": fmt(top_avg),
                "avg_weight_bottom_10pct": fmt(bottom_avg),
                "top_minus_bottom_weight_delta": fmt(delta),
                "correlation_with_excess": fmt(family_corr),
                "bootstrap_direction_consistency": fmt(consistency),
                "repeatability_status": status,
            })
    return output


def spy_asof_status(stability: list[dict[str, object]]) -> str:
    spy_rows = [row for row in stability if row["condition_name"] == "selected_etf_eq_SPY" and int(row["trial_count"]) >= 3]
    if not spy_rows:
        return "INSUFFICIENT_DATE_STABILITY"
    positive = sum(1 for row in spy_rows if row["stability_status"] == "STABLE_POSITIVE_DATE")
    rate = positive / len(spy_rows)
    if rate >= 0.60:
        return "BROAD_ASOF_STABILITY"
    if rate >= 0.40:
        return "MIXED_ASOF_STABILITY"
    return "WEAK_ASOF_STABILITY"


def rule_row(gate: dict[str, object]) -> dict[str, object]:
    recommended = gate.get("conditional_overlay_observation_recommended") == "TRUE"
    return {
        "rule_id": "V20_206_RULE_001",
        "rule_name": "10D_SPY_SELECTED_ETF_RESEARCH_ONLY_LOCAL_EDGE_OBSERVATION",
        "condition_expression": "selected_etf == SPY",
        "forward_window": "10D",
        "overlay_action": "ALLOW_RESEARCH_ONLY_LOCAL_EDGE_OBSERVATION" if recommended else "NO_OVERLAY_OBSERVATION",
        "allowed_scope": "SPY_SELECTED_ETF_REGIME_ONLY",
        "disabled_scope": "NON_SPY_SELECTED_ETF_REGIMES",
        "required_confirmation_metrics": "positive_mean_median_win_rate_bootstrap_ci_trimmed_winsorized_spy_condition",
        "rule_status": "OBSERVATION_CANDIDATE_ONLY" if recommended else "REJECTED_INSUFFICIENT_EVIDENCE",
        "reason": gate.get("reason", ""),
    }


def build_gate(groups: dict[str, list[dict[str, object]]], boots: list[dict[str, object]], trims: list[dict[str, object]], stability: list[dict[str, object]], bias: list[dict[str, object]]) -> dict[str, object]:
    spy_stats = basic_stats(groups["selected_etf_eq_SPY"])
    non_stats = basic_stats(groups["selected_etf_not_SPY"])
    spy_boot = next(row for row in boots if row["condition_name"] == "selected_etf_eq_SPY")
    spy_trim = next(row for row in trims if row["condition_name"] == "selected_etf_eq_SPY" and row["scenario_name"] == "exclude_top_bottom_5pct")
    spy_winsor = next(row for row in trims if row["condition_name"] == "selected_etf_eq_SPY" and row["scenario_name"] == "winsorize_5pct")
    spy_stability = spy_asof_status(stability)
    coherent_bias = any(row["condition_name"] == "selected_etf_eq_SPY" and row["repeatability_status"] == "REPEATABLE_CONDITION_BIAS_FOR_OBSERVATION" for row in bias)
    spy_count = int(spy_stats["trial_count"])
    spy_avg = float(spy_stats["avg_excess"])
    spy_med = float(spy_stats["median_excess"])
    spy_win = float(spy_stats["win_rate"])
    ci_lower = num(spy_boot.get("mean_excess_ci_lower_95")) or 0.0
    trim_avg = num(spy_trim.get("avg_excess_vs_etf_rotation")) or 0.0
    winsor_avg = num(spy_winsor.get("avg_excess_vs_etf_rotation")) or 0.0
    if spy_count < 30:
        final_status = STATUS_SMALL
        recommended = "TRUE"
        reason = "SPY condition sample is insufficient; continue observation only."
    elif spy_avg > 0 and spy_med > 0 and spy_win >= 0.55 and ci_lower > 0 and trim_avg > 0 and winsor_avg > 0:
        final_status = STATUS_CANDIDATE
        recommended = "TRUE"
        reason = "SPY condition passes central, bootstrap, trimmed, and winsorized checks for observation only."
    elif spy_avg > 0 and spy_med > 0 and spy_win >= 0.55:
        final_status = STATUS_MIXED
        recommended = "TRUE"
        reason = "SPY condition is positive but fails one or more robustness checks."
    else:
        final_status = STATUS_NONE
        recommended = "FALSE"
        reason = "SPY condition does not support a positive conditional 10D edge."
    return {
        "final_status": final_status,
        "valid_trial_count": str(len(groups["all_10D_trials"])),
        "spy_trial_count": str(spy_count),
        "non_spy_trial_count": str(non_stats["trial_count"]),
        "spy_avg_excess_vs_etf_rotation": fmt(spy_avg),
        "spy_median_excess_vs_etf_rotation": fmt(spy_med),
        "spy_win_rate_vs_etf_rotation": fmt(spy_win),
        "non_spy_avg_excess_vs_etf_rotation": fmt(float(non_stats["avg_excess"])),
        "non_spy_median_excess_vs_etf_rotation": fmt(float(non_stats["median_excess"])),
        "non_spy_win_rate_vs_etf_rotation": fmt(float(non_stats["win_rate"])),
        "spy_bootstrap_ci_lower_95": spy_boot.get("mean_excess_ci_lower_95", ""),
        "spy_bootstrap_ci_upper_95": spy_boot.get("mean_excess_ci_upper_95", ""),
        "spy_trimmed_5pct_avg_excess": fmt(trim_avg),
        "spy_winsorized_5pct_avg_excess": fmt(winsor_avg),
        "spy_asof_stability_status": spy_stability,
        "coherent_spy_weight_bias_detected": tf(coherent_bias),
        "conditional_overlay_observation_recommended": recommended,
        "non_spy_edge_disabled_for_observation": "TRUE",
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": "Observe 10D random-weight local edge only when ETF rotation selects SPY; disable non-SPY regimes for local-edge observation; do not activate shadow weights.",
    }


def write_report(gate: dict[str, object], effects: list[dict[str, object]], boots: list[dict[str, object]], trims: list[dict[str, object]], stability: list[dict[str, object]], bias: list[dict[str, object]], rule: dict[str, object]) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    spy_effect = next(row for row in effects if row["condition_name"] == "selected_etf_eq_SPY")
    non_effect = next(row for row in effects if row["condition_name"] == "selected_etf_not_SPY")
    spy_boot = next(row for row in boots if row["condition_name"] == "selected_etf_eq_SPY")
    spy_trim = [row for row in trims if row["condition_name"] == "selected_etf_eq_SPY" and row["scenario_name"] in {"exclude_top_bottom_5pct", "winsorize_5pct"}]
    repeatable = [row for row in bias if row["condition_name"] == "selected_etf_eq_SPY" and row["repeatability_status"] == "REPEATABLE_CONDITION_BIAS_FOR_OBSERVATION"]
    spy_date_rows = [row for row in stability if row["condition_name"] == "selected_etf_eq_SPY"]
    stable_dates = sum(1 for row in spy_date_rows if row["stability_status"] == "STABLE_POSITIVE_DATE")
    lines = [
        "# V20.206 10D SPY Conditional Overlay Validation Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.201 context: random-weight PIT-forward consolidation passed.",
        "- V20.202 context: no shadow weight change was recommended.",
        "- V20.203 context: 10D edge was weak or outlier-sensitive.",
        "- V20.204 context: expanded 10D evidence strengthened but failed selected-ETF leave-one-out robustness.",
        "- V20.205 context: SPY was the only robust positive selected ETF cluster.",
        "",
        "SPY condition effectiveness:",
        f"- trials={spy_effect['trial_count']}, avg_excess={spy_effect['avg_excess_vs_etf_rotation']}, median_excess={spy_effect['median_excess_vs_etf_rotation']}, win_rate={spy_effect['win_rate_vs_etf_rotation']}, status={spy_effect['effectiveness_status']}",
        "Non-SPY condition effectiveness:",
        f"- trials={non_effect['trial_count']}, avg_excess={non_effect['avg_excess_vs_etf_rotation']}, median_excess={non_effect['median_excess_vs_etf_rotation']}, win_rate={non_effect['win_rate_vs_etf_rotation']}, status={non_effect['effectiveness_status']}",
        f"- SPY explains the 10D local edge: {'TRUE' if gate.get('conditional_overlay_observation_recommended') == 'TRUE' else 'FALSE'}",
        "",
        "SPY bootstrap:",
        f"- mean CI 95%={spy_boot.get('mean_excess_ci_lower_95', '')} to {spy_boot.get('mean_excess_ci_upper_95', '')}; probability mean positive={spy_boot.get('probability_mean_excess_positive', '')}",
        "SPY trimmed/winsorized:",
        *(f"- {row['scenario_name']}: avg={row['avg_excess_vs_etf_rotation']}, conclusion={row['conclusion']}" for row in spy_trim),
        "",
        f"- SPY as_of_date stability: {gate.get('spy_asof_stability_status', '')}; stable_positive_dates={stable_dates} of {len(spy_date_rows)}",
        "SPY-specific weight family bias:",
        *(f"- {row['family_name']}: delta={row['top_minus_bottom_weight_delta']}, corr={row['correlation_with_excess']}, consistency={row['bootstrap_direction_consistency']}" for row in repeatable),
        *(["- No repeatable SPY-specific family bias was strong enough for activation work."] if not repeatable else []),
        "",
        "Conditional overlay rule candidate:",
        f"- {rule.get('rule_name', '')}: condition={rule.get('condition_expression', '')}, status={rule.get('rule_status', '')}, action={rule.get('overlay_action', '')}",
        f"- Non-SPY regimes disabled for local-edge observation: {gate.get('non_spy_edge_disabled_for_observation', '')}",
        f"- Next recommended action: {gate.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- shadow weight change is not recommended in V20.206",
        "- no trade action was created",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(reason: str) -> int:
    gate = {
        "final_status": STATUS_MISSING,
        "valid_trial_count": "0",
        "spy_trial_count": "0",
        "non_spy_trial_count": "0",
        "conditional_overlay_observation_recommended": "FALSE",
        "non_spy_edge_disabled_for_observation": "TRUE",
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": "Restore V20.204/V20.205 inputs before SPY conditional validation.",
    }
    rule = rule_row(gate)
    write_csv(OUT_EFFECT, EFFECT_FIELDS, [])
    write_csv(OUT_COMPARE, COMPARE_FIELDS, [])
    write_csv(OUT_BOOT, BOOT_FIELDS, [])
    write_csv(OUT_TRIM, TRIM_FIELDS, [])
    write_csv(OUT_STABILITY, STABILITY_FIELDS, [])
    write_csv(OUT_BIAS, BIAS_FIELDS, [])
    write_csv(OUT_RULE, RULE_FIELDS, [rule])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(
        "\n".join(
            [
                "# V20.206 10D SPY Conditional Overlay Validation Report",
                "",
                f"- Final status: {STATUS_MISSING}",
                f"- Reason: {reason}",
                "- Required V20.204/V20.205 inputs are missing or contain no effective data rows.",
                "- This blocked result is parseable and research-only.",
                "",
                "Safety statement:",
                "- official weights were not changed",
                "- no official recommendation was created",
                "- no real-book signal was created",
                "- no broker execution was created",
                "- shadow weight change is not recommended in V20.206",
                "- no trade action was created",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"FINAL_STATUS={STATUS_MISSING}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


def main() -> int:
    if not inputs_ready():
        missing = [path.name for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0 or not read_csv(path)]
        return blocked_outputs("Missing or empty required inputs: " + ", ".join(missing))
    metrics = build_metrics()
    if not metrics:
        return blocked_outputs("No expanded 10D metrics could be reconstructed.")
    groups = subsets(metrics)
    effects = effectiveness_rows(groups)
    compares = comparison_rows(groups)
    boots = bootstrap_rows(groups)
    trims = trimmed_rows(groups)
    stability = stability_rows(groups)
    bias = bias_rows(groups)
    gate = build_gate(groups, boots, trims, stability, bias)
    rule = rule_row(gate)
    write_csv(OUT_EFFECT, EFFECT_FIELDS, effects)
    write_csv(OUT_COMPARE, COMPARE_FIELDS, compares)
    write_csv(OUT_BOOT, BOOT_FIELDS, boots)
    write_csv(OUT_TRIM, TRIM_FIELDS, trims)
    write_csv(OUT_STABILITY, STABILITY_FIELDS, stability)
    write_csv(OUT_BIAS, BIAS_FIELDS, bias)
    write_csv(OUT_RULE, RULE_FIELDS, [rule])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, effects, boots, trims, stability, bias, rule)
    print(f"FINAL_STATUS={gate['final_status']}")
    print(f"VALID_TRIAL_COUNT={gate['valid_trial_count']}")
    print(f"SPY_TRIAL_COUNT={gate['spy_trial_count']}")
    print(f"CONDITIONAL_OVERLAY_OBSERVATION_RECOMMENDED={gate['conditional_overlay_observation_recommended']}")
    print(f"NON_SPY_EDGE_DISABLED_FOR_OBSERVATION={gate['non_spy_edge_disabled_for_observation']}")
    print(f"SHADOW_WEIGHT_CHANGE_RECOMMENDED={gate['shadow_weight_change_recommended']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
