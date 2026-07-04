#!/usr/bin/env python
"""V20.203 10D local edge and downside attribution.

Research-only diagnostic layer on V20.201/V20.202 outputs. It investigates
whether the V20.202 10D local edge is robust, whether downside tails explain
overall underperformance, and whether any finding supports observation only.
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_TRIALS = OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv"
IN_FORWARD = OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv"
IN_ETF = OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv"
IN_202_WINDOW = OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv"
IN_202_FAMILY = OUT_DIR / "V20_202_WEIGHT_FAMILY_CORRELATION_DIAGNOSTICS.csv"
IN_202_BUCKET = OUT_DIR / "V20_202_WEIGHT_BUCKET_EFFECTIVENESS.csv"
IN_202_TOP_BOTTOM = OUT_DIR / "V20_202_TOP_BOTTOM_TRIAL_DIAGNOSTICS.csv"
IN_202_DISTRIBUTION = OUT_DIR / "V20_202_ETF_EXCESS_RETURN_DISTRIBUTION.csv"
IN_202_GATE = OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv"
REQUIRED_INPUTS = [
    IN_TRIALS, IN_FORWARD, IN_ETF, IN_202_WINDOW, IN_202_FAMILY, IN_202_BUCKET,
    IN_202_TOP_BOTTOM, IN_202_DISTRIBUTION, IN_202_GATE,
]

OUT_10D = OUT_DIR / "V20_203_10D_LOCAL_EDGE_SUMMARY.csv"
OUT_TAIL = OUT_DIR / "V20_203_DOWNSIDE_TAIL_ATTRIBUTION.csv"
OUT_CLUSTER = OUT_DIR / "V20_203_ASOF_DATE_CLUSTER_ATTRIBUTION.csv"
OUT_BIAS = OUT_DIR / "V20_203_10D_WEIGHT_BIAS_DIAGNOSTICS.csv"
OUT_SENSITIVITY = OUT_DIR / "V20_203_OUTLIER_SENSITIVITY_CHECK.csv"
OUT_GATE = OUT_DIR / "V20_203_LOCAL_EDGE_OBSERVATION_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_203_10D_LOCAL_EDGE_AND_DOWNSIDE_ATTRIBUTION_REPORT.md"

COMMON = {
    "research_only": "TRUE",
    "official_weight_mutated": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_recommendation_created": "FALSE",
    "trade_action_created": "FALSE",
    "real_book_signal_created": "FALSE",
    "broker_execution_supported": "FALSE",
}

RANKING_FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime"]
ALL_FAMILIES = [*RANKING_FAMILIES, "data_trust"]

SUMMARY_FIELDS = [
    "forward_window", "trial_count", "avg_stock_topN_return", "median_stock_topN_return",
    "avg_etf_rotation_return", "median_etf_rotation_return", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation", "positive_excess_count",
    "negative_excess_count", "local_edge_status", "robustness_comment",
]
TAIL_FIELDS = [
    "tail_group", "trial_count", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "min_excess_vs_etf_rotation",
    "max_excess_vs_etf_rotation", "avg_stock_topN_return", "avg_etf_rotation_return",
    "avg_fundamental_weight", "avg_technical_weight", "avg_strategy_weight",
    "avg_risk_weight", "avg_market_regime_weight", "dominant_weight_pattern",
    "attribution_comment",
]
CLUSTER_FIELDS = [
    "as_of_date", "trial_count", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "positive_excess_rate", "avg_stock_topN_return",
    "avg_etf_rotation_return", "cluster_status", "warning_reason",
    "selected_etf_mode", "etf_rotation_signal_mode",
]
BIAS_FIELDS = [
    "family_name", "avg_weight_all_10d", "avg_weight_top_10pct_10d",
    "avg_weight_bottom_10pct_10d", "top_minus_bottom_weight_delta",
    "correlation_with_10d_excess", "directional_signal", "robustness_status",
]
SENSITIVITY_FIELDS = [
    "scenario_name", "excluded_trial_count", "remaining_trial_count",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "win_rate_vs_etf_rotation", "conclusion",
]
GATE_FIELDS = [
    "final_status", "valid_trial_count", "ten_d_trial_count",
    "ten_d_avg_excess_vs_etf_rotation", "ten_d_median_excess_vs_etf_rotation",
    "ten_d_win_rate_vs_etf_rotation", "downside_tail_concentration_detected",
    "coherent_10d_weight_bias_detected", "outlier_sensitive",
    "local_edge_observation_recommended", "shadow_weight_change_recommended",
    "reason", "next_recommended_action", *COMMON.keys(),
]

STATUS_OBSERVE = "PASS_V20_203_10D_LOCAL_EDGE_OBSERVATION_CANDIDATE"
STATUS_WEAK = "PARTIAL_PASS_V20_203_10D_EDGE_WEAK_OR_OUTLIER_SENSITIVE"
STATUS_NONE = "PASS_V20_203_NO_ROBUST_LOCAL_EDGE_FOUND"
STATUS_BLOCKED = "BLOCKED_V20_203_REQUIRED_INPUT_MISSING"


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


def avg(values: list[float]) -> str:
    return fmt(mean(values)) if values else ""


def med(values: list[float]) -> str:
    return fmt(median(values)) if values else ""


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
    cov = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    return cov / math.sqrt(x_var * y_var)


def mode(values: list[str]) -> str:
    values = [value for value in values if value]
    if not values:
        return ""
    return Counter(values).most_common(1)[0][0]


def input_ready() -> bool:
    return all(path.exists() and path.stat().st_size > 0 and read_csv(path) for path in REQUIRED_INPUTS)


def build_metrics(
    trials: list[dict[str, str]],
    forward: list[dict[str, str]],
    etf: list[dict[str, str]],
) -> list[dict[str, object]]:
    forward_returns: dict[str, list[float]] = defaultdict(list)
    for row in forward:
        value = num(row.get("forward_return"))
        if row.get("outcome_status") == "PASS" and value is not None:
            forward_returns[row["trial_id"]].append(value)

    etf_by_trial: dict[str, dict[str, object]] = {}
    for row in etf:
        value = num(row.get("etf_forward_return"))
        if row.get("benchmark_status") == "PASS" and value is not None:
            etf_by_trial[row["trial_id"]] = {
                "etf_rotation_return": value,
                "selected_etf": row.get("selected_etf", ""),
                "etf_rotation_signal": row.get("etf_rotation_signal", ""),
            }

    metrics: list[dict[str, object]] = []
    for row in trials:
        trial_id = row.get("trial_id", "")
        if row.get("trial_status") != "VALID" or trial_id not in forward_returns or trial_id not in etf_by_trial:
            continue
        stock_return = mean(forward_returns[trial_id])
        etf_return = float(etf_by_trial[trial_id]["etf_rotation_return"])
        metric = {
            "trial_id": trial_id,
            "as_of_date": row.get("as_of_date", ""),
            "forward_window": row.get("forward_window", ""),
            "stock_topN_return": stock_return,
            "etf_rotation_return": etf_return,
            "excess_vs_etf_rotation": stock_return - etf_return,
            "selected_etf": etf_by_trial[trial_id]["selected_etf"],
            "etf_rotation_signal": etf_by_trial[trial_id]["etf_rotation_signal"],
        }
        for family in ALL_FAMILIES:
            metric[f"{family}_weight"] = num(row.get(f"{family}_weight")) or 0.0
        metrics.append(metric)
    return metrics


def status(values: list[float], win_rate: float | None) -> tuple[str, str]:
    if not values:
        return "NO_VALID_TRIALS", "No valid trials are available for this forward window."
    avg_excess = mean(values)
    med_excess = median(values)
    win = win_rate or 0.0
    if avg_excess > 0 and med_excess > 0 and win >= 0.55:
        return "LOCAL_EDGE_CANDIDATE", "Mean, median, and win rate are positive; still observation-only pending outlier checks."
    if avg_excess > 0 or med_excess > 0:
        return "MIXED_LOCAL_EDGE", "Only part of the 10D-style evidence is positive; not robust enough for weight change."
    return "NO_LOCAL_EDGE", "ETF rotation remains stronger for this window."


def local_edge_summary(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    windows = sorted({clean(row["forward_window"]) for row in metrics}, key=lambda x: int(x.rstrip("D")) if x.rstrip("D").isdigit() else x)
    for window in windows:
        subset = [row for row in metrics if row["forward_window"] == window]
        stock = [float(row["stock_topN_return"]) for row in subset]
        etf = [float(row["etf_rotation_return"]) for row in subset]
        excess = [float(row["excess_vs_etf_rotation"]) for row in subset]
        win_rate = sum(1 for value in excess if value > 0) / len(excess) if excess else None
        local_status, comment = status(excess, win_rate)
        rows.append({
            "forward_window": window,
            "trial_count": str(len(subset)),
            "avg_stock_topN_return": avg(stock),
            "median_stock_topN_return": med(stock),
            "avg_etf_rotation_return": avg(etf),
            "median_etf_rotation_return": med(etf),
            "avg_excess_vs_etf_rotation": avg(excess),
            "median_excess_vs_etf_rotation": med(excess),
            "win_rate_vs_etf_rotation": fmt(win_rate),
            "positive_excess_count": str(sum(1 for value in excess if value > 0)),
            "negative_excess_count": str(sum(1 for value in excess if value < 0)),
            "local_edge_status": local_status,
            "robustness_comment": comment,
        })
    return rows


def dominant_pattern(group: list[dict[str, object]], base: list[dict[str, object]]) -> str:
    if not group or not base:
        return "UNAVAILABLE"
    parts = []
    for family in RANKING_FAMILIES:
        group_avg = mean([float(row[f"{family}_weight"]) for row in group])
        base_avg = mean([float(row[f"{family}_weight"]) for row in base])
        delta = group_avg - base_avg
        if abs(delta) >= 0.01:
            parts.append(f"{family.upper()}_{'HIGH' if delta > 0 else 'LOW'}")
    return "NO_COHERENT_PATTERN" if not parts else ";".join(parts)


def group_row(name: str, group: list[dict[str, object]], base: list[dict[str, object]]) -> dict[str, object]:
    excess = [float(row["excess_vs_etf_rotation"]) for row in group]
    stock = [float(row["stock_topN_return"]) for row in group]
    etf = [float(row["etf_rotation_return"]) for row in group]
    if name.startswith("bottom"):
        comment = "Downside tail group; inspect whether its mean excess is materially worse than all trials."
    elif name.startswith("top"):
        comment = "Positive tail group; useful for contrast but not promotion evidence."
    elif name == "middle_50pct_by_excess":
        comment = "Central distribution after excluding both tails."
    else:
        comment = "All valid V20.201 trial/window rows."
    return {
        "tail_group": name,
        "trial_count": str(len(group)),
        "avg_excess_vs_etf_rotation": avg(excess),
        "median_excess_vs_etf_rotation": med(excess),
        "min_excess_vs_etf_rotation": fmt(min(excess) if excess else None),
        "max_excess_vs_etf_rotation": fmt(max(excess) if excess else None),
        "avg_stock_topN_return": avg(stock),
        "avg_etf_rotation_return": avg(etf),
        "avg_fundamental_weight": fmt(mean([float(row["fundamental_weight"]) for row in group])) if group else "",
        "avg_technical_weight": fmt(mean([float(row["technical_weight"]) for row in group])) if group else "",
        "avg_strategy_weight": fmt(mean([float(row["strategy_weight"]) for row in group])) if group else "",
        "avg_risk_weight": fmt(mean([float(row["risk_weight"]) for row in group])) if group else "",
        "avg_market_regime_weight": fmt(mean([float(row["market_regime_weight"]) for row in group])) if group else "",
        "dominant_weight_pattern": dominant_pattern(group, base),
        "attribution_comment": comment,
    }


def downside_tail_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(metrics, key=lambda row: float(row["excess_vs_etf_rotation"]))
    n = len(ordered)
    def count(pct: float) -> int:
        return max(1, math.ceil(n * pct)) if n else 0
    b5 = count(0.05)
    b10 = count(0.10)
    b25 = count(0.25)
    t25 = count(0.25)
    t10 = count(0.10)
    t5 = count(0.05)
    groups = [
        ("all_trials", ordered),
        ("bottom_5pct_by_excess", ordered[:b5]),
        ("bottom_10pct_by_excess", ordered[:b10]),
        ("bottom_25pct_by_excess", ordered[:b25]),
        ("middle_50pct_by_excess", ordered[b25:n - t25] if n > b25 + t25 else []),
        ("top_25pct_by_excess", ordered[n - t25:] if t25 else []),
        ("top_10pct_by_excess", ordered[n - t10:] if t10 else []),
        ("top_5pct_by_excess", ordered[n - t5:] if t5 else []),
    ]
    return [group_row(name, group, ordered) for name, group in groups]


def cluster_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in metrics:
        by_date[clean(row["as_of_date"])].append(row)
    rows: list[dict[str, object]] = []
    for as_of in sorted(by_date):
        group = by_date[as_of]
        excess = [float(row["excess_vs_etf_rotation"]) for row in group]
        stock = [float(row["stock_topN_return"]) for row in group]
        etf = [float(row["etf_rotation_return"]) for row in group]
        positive_rate = sum(1 for value in excess if value > 0) / len(excess) if excess else 0.0
        avg_excess = mean(excess) if excess else 0.0
        if avg_excess < 0 and positive_rate < 0.5:
            cluster_status = "NEGATIVE_CLUSTER"
            warning = "Date cluster contributed to underperformance versus ETF rotation."
        elif avg_excess < 0:
            cluster_status = "MIXED_NEGATIVE_CLUSTER"
            warning = "Average negative despite some positive trials."
        else:
            cluster_status = "NON_NEGATIVE_CLUSTER"
            warning = ""
        rows.append({
            "as_of_date": as_of,
            "trial_count": str(len(group)),
            "avg_excess_vs_etf_rotation": avg(excess),
            "median_excess_vs_etf_rotation": med(excess),
            "positive_excess_rate": fmt(positive_rate),
            "avg_stock_topN_return": avg(stock),
            "avg_etf_rotation_return": avg(etf),
            "cluster_status": cluster_status,
            "warning_reason": warning,
            "selected_etf_mode": mode([clean(row["selected_etf"]) for row in group]),
            "etf_rotation_signal_mode": mode([clean(row["etf_rotation_signal"]) for row in group]),
        })
    return rows


def ten_d_bias_rows(ten_d: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(ten_d, key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
    n = len(ordered)
    size = max(1, math.ceil(n * 0.10)) if n else 0
    top = ordered[:size]
    bottom = ordered[-size:] if size else []
    excess = [float(row["excess_vs_etf_rotation"]) for row in ten_d]
    rows: list[dict[str, object]] = []
    for family in ALL_FAMILIES:
        weights = [float(row[f"{family}_weight"]) for row in ten_d]
        top_avg = mean([float(row[f"{family}_weight"]) for row in top]) if top else None
        bottom_avg = mean([float(row[f"{family}_weight"]) for row in bottom]) if bottom else None
        delta = (top_avg - bottom_avg) if top_avg is not None and bottom_avg is not None else 0.0
        family_corr = corr(weights, excess)
        if family == "data_trust" and not any(weights):
            signal = "AUDIT_ONLY_ZERO_WEIGHT"
            robust = "AUDIT_ONLY_NOT_RANKING_WEIGHT"
        elif family_corr is not None and family_corr > 0.05 and delta > 0:
            signal = "POSITIVE"
            robust = "WEAK_10D_DIRECTIONAL_ASSOCIATION" if abs(family_corr) < 0.15 or abs(delta) < 0.01 else "COHERENT_10D_BIAS_REQUIRES_OBSERVATION"
        elif family_corr is not None and family_corr < -0.05 and delta < 0:
            signal = "NEGATIVE"
            robust = "WEAK_10D_DIRECTIONAL_ASSOCIATION" if abs(family_corr) < 0.15 or abs(delta) < 0.01 else "COHERENT_10D_BIAS_REQUIRES_OBSERVATION"
        else:
            signal = "NEUTRAL"
            robust = "NO_COHERENT_10D_BIAS"
        rows.append({
            "family_name": family,
            "avg_weight_all_10d": fmt(mean(weights) if weights else None),
            "avg_weight_top_10pct_10d": fmt(top_avg),
            "avg_weight_bottom_10pct_10d": fmt(bottom_avg),
            "top_minus_bottom_weight_delta": fmt(delta),
            "correlation_with_10d_excess": fmt(family_corr),
            "directional_signal": signal,
            "robustness_status": robust,
        })
    return rows


def sensitivity_values(values: list[float], scenario: str) -> tuple[list[float], int]:
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
    if scenario == "winsorize_1pct":
        low = ordered[c1 - 1]
        high = ordered[n - c1]
        return [min(max(value, low), high) for value in values], 0
    if scenario == "winsorize_5pct":
        low = ordered[c5 - 1]
        high = ordered[n - c5]
        return [min(max(value, low), high) for value in values], 0
    return values[:], 0


def sensitivity_rows(ten_d: list[dict[str, object]]) -> list[dict[str, object]]:
    scenarios = [
        "no_exclusion", "exclude_bottom_1pct", "exclude_bottom_5pct",
        "exclude_top_1pct", "exclude_top_5pct", "winsorize_1pct", "winsorize_5pct",
    ]
    values = [float(row["excess_vs_etf_rotation"]) for row in ten_d]
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        adjusted, excluded = sensitivity_values(values, scenario)
        avg_value = mean(adjusted) if adjusted else None
        med_value = median(adjusted) if adjusted else None
        win_rate = sum(1 for value in adjusted if value > 0) / len(adjusted) if adjusted else None
        conclusion = (
            "POSITIVE_MEAN_MEDIAN_AND_WIN_RATE"
            if avg_value is not None and avg_value > 0 and med_value is not None and med_value > 0 and (win_rate or 0.0) >= 0.55
            else "WEAK_OR_NOT_POSITIVE_AFTER_ADJUSTMENT"
        )
        rows.append({
            "scenario_name": scenario,
            "excluded_trial_count": str(excluded),
            "remaining_trial_count": str(len(adjusted)),
            "avg_excess_vs_etf_rotation": fmt(avg_value),
            "median_excess_vs_etf_rotation": fmt(med_value),
            "win_rate_vs_etf_rotation": fmt(win_rate),
            "conclusion": conclusion,
        })
    return rows


def gate_row(
    metrics: list[dict[str, object]],
    ten_d: list[dict[str, object]],
    tail: list[dict[str, object]],
    bias: list[dict[str, object]],
    sensitivity: list[dict[str, object]],
) -> dict[str, object]:
    ten_excess = [float(row["excess_vs_etf_rotation"]) for row in ten_d]
    ten_avg = mean(ten_excess) if ten_excess else None
    ten_med = median(ten_excess) if ten_excess else None
    ten_win = sum(1 for value in ten_excess if value > 0) / len(ten_excess) if ten_excess else None
    by_scenario = {row["scenario_name"]: row for row in sensitivity}
    bottom5_ok = by_scenario.get("exclude_bottom_5pct", {}).get("conclusion") == "POSITIVE_MEAN_MEDIAN_AND_WIN_RATE"
    top5_ok = by_scenario.get("exclude_top_5pct", {}).get("conclusion") == "POSITIVE_MEAN_MEDIAN_AND_WIN_RATE"
    outlier_sensitive = not (bottom5_ok and top5_ok)

    all_row = next((row for row in tail if row["tail_group"] == "all_trials"), {})
    bottom5_row = next((row for row in tail if row["tail_group"] == "bottom_5pct_by_excess"), {})
    all_avg = num(all_row.get("avg_excess_vs_etf_rotation"))
    bottom5_avg = num(bottom5_row.get("avg_excess_vs_etf_rotation"))
    downside_tail = bool(all_avg is not None and bottom5_avg is not None and all_avg < 0 and abs(bottom5_avg) > abs(all_avg) * 10)
    coherent_bias = any(row["robustness_status"] == "COHERENT_10D_BIAS_REQUIRES_OBSERVATION" for row in bias)

    if not ten_d or ten_avg is None or ten_med is None or ten_win is None:
        final_status = STATUS_NONE
        local_observe = "FALSE"
        reason = "10D trial rows are unavailable; no 10D local edge can be claimed."
        next_action = "Keep ETF rotation as the primary benchmark and keep random-weight stock ranking research-only."
    elif ten_avg > 0 and ten_med > 0 and ten_win >= 0.55 and not outlier_sensitive:
        final_status = STATUS_OBSERVE
        local_observe = "TRUE"
        reason = "10D mean, median, win rate, and 5pct outlier checks remain positive; observation-only candidate."
        next_action = "Continue local 10D observation only; do not activate shadow weights."
    elif ten_avg > 0 and ten_med > 0:
        final_status = STATUS_WEAK
        local_observe = "TRUE"
        reason = "10D has positive central evidence but is weak or outlier-sensitive."
        next_action = "Observe the 10D local edge in future runs while keeping ETF rotation primary and official weights unchanged."
    else:
        final_status = STATUS_NONE
        local_observe = "FALSE"
        reason = "10D average or median excess is not positive enough to support a local-edge observation candidate."
        next_action = "Keep ETF rotation as the primary benchmark and keep random-weight stock ranking research-only."

    return {
        "final_status": final_status,
        "valid_trial_count": str(len(metrics)),
        "ten_d_trial_count": str(len(ten_d)),
        "ten_d_avg_excess_vs_etf_rotation": fmt(ten_avg),
        "ten_d_median_excess_vs_etf_rotation": fmt(ten_med),
        "ten_d_win_rate_vs_etf_rotation": fmt(ten_win),
        "downside_tail_concentration_detected": "TRUE" if downside_tail else "FALSE",
        "coherent_10d_weight_bias_detected": "TRUE" if coherent_bias else "FALSE",
        "outlier_sensitive": "TRUE" if outlier_sensitive else "FALSE",
        "local_edge_observation_recommended": local_observe,
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": next_action,
        **COMMON,
    }


def write_report(
    gate: dict[str, object],
    summary_rows: list[dict[str, object]],
    tail_rows_out: list[dict[str, object]],
    cluster_rows_out: list[dict[str, object]],
    bias_rows_out: list[dict[str, object]],
    sensitivity_rows_out: list[dict[str, object]],
) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    ten_d = next((row for row in summary_rows if row["forward_window"] == "10D"), {})
    worst_clusters = sorted(cluster_rows_out, key=lambda row: num(row["avg_excess_vs_etf_rotation"]) or 0.0)[:5]
    top_bias = [row for row in bias_rows_out if row["directional_signal"] == "POSITIVE"]
    bottom_bias = [row for row in bias_rows_out if row["directional_signal"] == "NEGATIVE"]
    sens5 = [row for row in sensitivity_rows_out if row["scenario_name"] in {"exclude_bottom_5pct", "exclude_top_5pct", "winsorize_5pct"}]
    bottom5_tail = next((row for row in tail_rows_out if row["tail_group"] == "bottom_5pct_by_excess"), {})
    lines = [
        "# V20.203 10D Local Edge And Downside Attribution Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.201 context: PIT-forward random-weight backtest passed with 500 valid trials.",
        "- V20.202 context: no shadow change was recommended; overall average excess versus ETF rotation was negative while 10D was locally positive.",
        "",
        "10D local edge summary:",
        f"- trial_count={ten_d.get('trial_count', '')}, avg_excess={ten_d.get('avg_excess_vs_etf_rotation', '')}, "
        f"median_excess={ten_d.get('median_excess_vs_etf_rotation', '')}, win_rate={ten_d.get('win_rate_vs_etf_rotation', '')}, "
        f"status={ten_d.get('local_edge_status', '')}",
        "",
        "Outlier sensitivity:",
        *(f"- {row['scenario_name']}: avg={row['avg_excess_vs_etf_rotation']}, median={row['median_excess_vs_etf_rotation']}, win_rate={row['win_rate_vs_etf_rotation']}, conclusion={row['conclusion']}" for row in sens5),
        f"- 10D edge outlier_sensitive={gate.get('outlier_sensitive', '')}",
        "",
        "Downside tail concentration:",
        f"- bottom_5pct avg_excess={bottom5_tail.get('avg_excess_vs_etf_rotation', '')}, pattern={bottom5_tail.get('dominant_weight_pattern', '')}",
        f"- downside_tail_concentration_detected={gate.get('downside_tail_concentration_detected', '')}",
        "",
        "Worst as_of_date clusters:",
        *(f"- {row['as_of_date']}: avg_excess={row['avg_excess_vs_etf_rotation']}, positive_rate={row['positive_excess_rate']}, selected_etf={row['selected_etf_mode']}" for row in worst_clusters),
        "",
        "10D top-trial weight bias:",
        *(f"- {row['family_name']}: delta={row['top_minus_bottom_weight_delta']}, corr={row['correlation_with_10d_excess']}, robustness={row['robustness_status']}" for row in top_bias),
        *(["- No coherent positive 10D top-trial weight bias was strong enough for more than observation."] if not top_bias else []),
        "",
        "10D bottom-trial weight bias:",
        *(f"- {row['family_name']}: delta={row['top_minus_bottom_weight_delta']}, corr={row['correlation_with_10d_excess']}, robustness={row['robustness_status']}" for row in bottom_bias),
        *(["- No coherent negative 10D bottom-trial weight bias was isolated."] if not bottom_bias else []),
        "",
        f"- Further local-edge observation recommended: {gate.get('local_edge_observation_recommended', '')}",
        f"- Reason: {gate.get('reason', '')}",
        f"- Next recommended action: {gate.get('next_recommended_action', '')}",
        "- V20.203 is not authorized to recommend immediate shadow weight activation.",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- no trade action was created",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(reason: str) -> int:
    gate = {
        "final_status": STATUS_BLOCKED,
        "valid_trial_count": "0",
        "ten_d_trial_count": "0",
        "ten_d_avg_excess_vs_etf_rotation": "",
        "ten_d_median_excess_vs_etf_rotation": "",
        "ten_d_win_rate_vs_etf_rotation": "",
        "downside_tail_concentration_detected": "FALSE",
        "coherent_10d_weight_bias_detected": "FALSE",
        "outlier_sensitive": "TRUE",
        "local_edge_observation_recommended": "FALSE",
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": "Restore required V20.201 and V20.202 inputs before attribution.",
        **COMMON,
    }
    write_csv(OUT_10D, SUMMARY_FIELDS, [])
    write_csv(OUT_TAIL, TAIL_FIELDS, [])
    write_csv(OUT_CLUSTER, CLUSTER_FIELDS, [])
    write_csv(OUT_BIAS, BIAS_FIELDS, [])
    write_csv(OUT_SENSITIVITY, SENSITIVITY_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, [], [], [], [], [])
    print(f"FINAL_STATUS={STATUS_BLOCKED}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("SHADOW_WEIGHT_CHANGE_RECOMMENDED=FALSE")
    return 0


def main() -> int:
    if not input_ready():
        missing = [path.name for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0 or not read_csv(path)]
        return blocked_outputs("Missing or empty required inputs: " + ", ".join(missing))

    trials = read_csv(IN_TRIALS)
    forward = read_csv(IN_FORWARD)
    etf = read_csv(IN_ETF)
    metrics = build_metrics(trials, forward, etf)
    ten_d = [row for row in metrics if row["forward_window"] == "10D"]

    summaries = local_edge_summary(metrics)
    tails = downside_tail_rows(metrics)
    clusters = cluster_rows(metrics)
    bias = ten_d_bias_rows(ten_d)
    sensitivity = sensitivity_rows(ten_d)
    gate = gate_row(metrics, ten_d, tails, bias, sensitivity)

    write_csv(OUT_10D, SUMMARY_FIELDS, summaries)
    write_csv(OUT_TAIL, TAIL_FIELDS, tails)
    write_csv(OUT_CLUSTER, CLUSTER_FIELDS, clusters)
    write_csv(OUT_BIAS, BIAS_FIELDS, bias)
    write_csv(OUT_SENSITIVITY, SENSITIVITY_FIELDS, sensitivity)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, summaries, tails, clusters, bias, sensitivity)

    print(f"FINAL_STATUS={gate['final_status']}")
    print(f"VALID_TRIAL_COUNT={gate['valid_trial_count']}")
    print(f"TEN_D_TRIAL_COUNT={gate['ten_d_trial_count']}")
    print(f"TEN_D_AVG_EXCESS_VS_ETF_ROTATION={gate['ten_d_avg_excess_vs_etf_rotation']}")
    print(f"LOCAL_EDGE_OBSERVATION_RECOMMENDED={gate['local_edge_observation_recommended']}")
    print(f"SHADOW_WEIGHT_CHANGE_RECOMMENDED={gate['shadow_weight_change_recommended']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
