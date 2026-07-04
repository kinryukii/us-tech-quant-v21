#!/usr/bin/env python
"""V20.202 random-weight effectiveness aggregation.

Consumes V20.201 random-weight PIT-forward backtest outputs and emits
higher-level diagnostics. This stage is research-only and does not rerun,
mutate, or replace the V20.201 trial framework.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_TRIALS = OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv"
IN_RANKINGS = OUT_DIR / "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv"
IN_FORWARD = OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv"
IN_ETF = OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv"
IN_SUMMARY = OUT_DIR / "V20_201_WEIGHT_EFFECTIVENESS_SUMMARY.csv"
IN_PIT = OUT_DIR / "V20_201_PIT_LEAKAGE_AUDIT.csv"
IN_COVERAGE = OUT_DIR / "V20_201_SOURCE_COVERAGE_DIAGNOSTICS.csv"
REQUIRED_INPUTS = [IN_TRIALS, IN_RANKINGS, IN_FORWARD, IN_ETF, IN_SUMMARY, IN_PIT, IN_COVERAGE]

OUT_WINDOW = OUT_DIR / "V20_202_FORWARD_WINDOW_EFFECTIVENESS.csv"
OUT_FAMILY = OUT_DIR / "V20_202_WEIGHT_FAMILY_CORRELATION_DIAGNOSTICS.csv"
OUT_BUCKET = OUT_DIR / "V20_202_WEIGHT_BUCKET_EFFECTIVENESS.csv"
OUT_TOP_BOTTOM = OUT_DIR / "V20_202_TOP_BOTTOM_TRIAL_DIAGNOSTICS.csv"
OUT_DISTRIBUTION = OUT_DIR / "V20_202_ETF_EXCESS_RETURN_DISTRIBUTION.csv"
OUT_GATE = OUT_DIR / "V20_202_SHADOW_WEIGHT_READINESS_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_202_RANDOM_WEIGHT_EFFECTIVENESS_AGGREGATOR_REPORT.md"

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

WINDOW_FIELDS = [
    "forward_window", "trial_count", "avg_stock_topN_return", "median_stock_topN_return",
    "avg_etf_rotation_return", "median_etf_rotation_return", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation", "win_rate_vs_qqq",
    "win_rate_vs_spy", "positive_excess_trial_count", "negative_excess_trial_count",
    "effectiveness_status",
]
FAMILY_FIELDS = [
    "family_name", "min_weight", "max_weight", "avg_weight",
    "correlation_with_stock_topN_return", "correlation_with_excess_vs_etf_rotation",
    "top_decile_avg_weight", "bottom_decile_avg_weight", "directional_signal",
    "robustness_status",
]
BUCKET_FIELDS = [
    "family_name", "weight_bucket", "trial_count", "avg_stock_topN_return",
    "median_stock_topN_return", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation",
    "bucket_effectiveness_status",
]
TOP_BOTTOM_FIELDS = [
    "group_name", "trial_count", "avg_fundamental_weight", "avg_technical_weight",
    "avg_strategy_weight", "avg_risk_weight", "avg_market_regime_weight",
    "avg_data_trust_weight", "avg_stock_topN_return", "avg_etf_rotation_return",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "dominant_weight_pattern",
]
DISTRIBUTION_FIELDS = ["metric_name", "metric_value"]
GATE_FIELDS = [
    "final_status", "valid_trial_count", "avg_excess_vs_etf_rotation",
    "median_excess_vs_etf_rotation", "win_rate_vs_etf_rotation", "best_forward_window",
    "strongest_positive_family_bias", "strongest_negative_family_bias", "evidence_strength",
    "shadow_weight_change_recommended", "reason", "next_recommended_action", *COMMON.keys(),
]

BLOCKED_STATUS = "BLOCKED_V20_202_REQUIRED_V20_201_OUTPUT_MISSING"
NO_CHANGE_STATUS = "PASS_V20_202_EFFECTIVENESS_AGGREGATED_NO_SHADOW_CHANGE"
MEAN_ONLY_STATUS = "PARTIAL_PASS_V20_202_MEAN_ONLY_EDGE_NOT_ROBUST"
CANDIDATE_STATUS = "PASS_V20_202_SHADOW_WEIGHT_CANDIDATE_BIAS_FOUND"


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
    x_vals = [x for x, _ in pairs]
    y_vals = [y for _, y in pairs]
    x_mean = mean(x_vals)
    y_mean = mean(y_vals)
    x_var = sum((x - x_mean) ** 2 for x in x_vals)
    y_var = sum((y - y_mean) ** 2 for y in y_vals)
    if x_var <= 0 or y_var <= 0:
        return None
    cov = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    return cov / math.sqrt(x_var * y_var)


def required_inputs_ready() -> bool:
    return all(path.exists() and path.stat().st_size > 0 and read_csv(path) for path in REQUIRED_INPUTS)


def write_report(
    gate: dict[str, object],
    summary: dict[str, str],
    windows: list[dict[str, object]],
    families: list[dict[str, object]],
    top_bottom: list[dict[str, object]],
) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    positive = [row for row in families if row["directional_signal"] == "POSITIVE"]
    negative = [row for row in families if row["directional_signal"] == "NEGATIVE"]
    window_lines = [
        f"- {row['forward_window']}: avg_excess={row['avg_excess_vs_etf_rotation']}, "
        f"median_excess={row['median_excess_vs_etf_rotation']}, win_rate={row['win_rate_vs_etf_rotation']}, "
        f"status={row['effectiveness_status']}"
        for row in windows
    ]
    top_row = next((row for row in top_bottom if row["group_name"] == "TOP_DECILE_EXCESS"), {})
    bottom_row = next((row for row in top_bottom if row["group_name"] == "BOTTOM_DECILE_EXCESS"), {})
    lines = [
        "# V20.202 Random-Weight Effectiveness Aggregator Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        f"- V20.201 passed: {'TRUE' if clean(summary.get('final_status')).startswith('PASS_') else 'FALSE'}",
        f"- Trials analyzed: {gate.get('valid_trial_count', '')}",
        f"- Overall average excess versus ETF rotation: {gate.get('avg_excess_vs_etf_rotation', '')}",
        f"- Overall median excess versus ETF rotation: {gate.get('median_excess_vs_etf_rotation', '')}",
        "",
        "Forward-window breakdown:",
        *(window_lines or ["- No valid forward-window rows were available."]),
        "",
        "Positive family association:",
        *(f"- {row['family_name']}: corr_excess={row['correlation_with_excess_vs_etf_rotation']}, robustness={row['robustness_status']}" for row in positive),
        *(["- None robust enough to justify a shadow-weight change."] if not positive else []),
        "",
        "Negative family association:",
        *(f"- {row['family_name']}: corr_excess={row['correlation_with_excess_vs_etf_rotation']}, robustness={row['robustness_status']}" for row in negative),
        *(["- None material."] if not negative else []),
        "",
        f"- Top-decile coherent weight pattern: {top_row.get('dominant_weight_pattern', 'UNAVAILABLE')}",
        f"- Bottom-decile coherent weight pattern: {bottom_row.get('dominant_weight_pattern', 'UNAVAILABLE')}",
        f"- Shadow weight readiness conclusion: {gate.get('reason', '')}",
        f"- Next recommended action: {gate.get('next_recommended_action', '')}",
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
        "final_status": BLOCKED_STATUS,
        "valid_trial_count": "0",
        "avg_excess_vs_etf_rotation": "",
        "median_excess_vs_etf_rotation": "",
        "win_rate_vs_etf_rotation": "",
        "best_forward_window": "",
        "strongest_positive_family_bias": "NONE",
        "strongest_negative_family_bias": "NONE",
        "evidence_strength": "BLOCKED",
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": "Restore all required V20.201 outputs before aggregating effectiveness.",
        **COMMON,
    }
    write_csv(OUT_WINDOW, WINDOW_FIELDS, [])
    write_csv(OUT_FAMILY, FAMILY_FIELDS, [])
    write_csv(OUT_BUCKET, BUCKET_FIELDS, [])
    write_csv(OUT_TOP_BOTTOM, TOP_BOTTOM_FIELDS, [])
    write_csv(OUT_DISTRIBUTION, DISTRIBUTION_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, {}, [], [], [])
    print(f"FINAL_STATUS={BLOCKED_STATUS}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


def build_trial_metrics(
    trials: list[dict[str, str]],
    forward: list[dict[str, str]],
    etf: list[dict[str, str]],
) -> list[dict[str, object]]:
    stock_returns: dict[str, list[float]] = defaultdict(list)
    for row in forward:
        value = num(row.get("forward_return"))
        if row.get("outcome_status") == "PASS" and value is not None:
            stock_returns[row["trial_id"]].append(value)

    etf_by_trial: dict[str, dict[str, float]] = {}
    for row in etf:
        if row.get("benchmark_status") != "PASS":
            continue
        etf_return = num(row.get("etf_forward_return"))
        if etf_return is None:
            continue
        etf_by_trial[row["trial_id"]] = {
            "etf_rotation_return": etf_return,
            "qqq_return": num(row.get("qqq_forward_return")) if num(row.get("qqq_forward_return")) is not None else math.nan,
            "spy_return": num(row.get("spy_forward_return")) if num(row.get("spy_forward_return")) is not None else math.nan,
        }

    metrics: list[dict[str, object]] = []
    for row in trials:
        tid = row.get("trial_id", "")
        if row.get("trial_status") != "VALID" or tid not in stock_returns or tid not in etf_by_trial:
            continue
        stock = mean(stock_returns[tid])
        etf_return = etf_by_trial[tid]["etf_rotation_return"]
        metric = {
            "trial_id": tid,
            "as_of_date": row.get("as_of_date", ""),
            "forward_window": row.get("forward_window", ""),
            "stock_topN_return": stock,
            "etf_rotation_return": etf_return,
            "excess_vs_etf_rotation": stock - etf_return,
            "qqq_return": etf_by_trial[tid]["qqq_return"],
            "spy_return": etf_by_trial[tid]["spy_return"],
        }
        for family in ALL_FAMILIES:
            metric[f"{family}_weight"] = num(row.get(f"{family}_weight")) or 0.0
        metrics.append(metric)
    return metrics


def status_for(values: list[float], win_rate: float | None) -> str:
    if not values:
        return "NO_VALID_TRIALS"
    avg_excess = mean(values)
    med_excess = median(values)
    if avg_excess > 0 and med_excess > 0 and (win_rate or 0.0) >= 0.55:
        return "POSITIVE_ROBUST_EDGE_CANDIDATE"
    if avg_excess > 0 and med_excess <= 0:
        return "MEAN_ONLY_EDGE_NOT_ROBUST"
    if avg_excess > 0 or med_excess > 0:
        return "MIXED_NOT_ROBUST"
    return "UNDERPERFORMS_ETF_ROTATION"


def forward_window_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    windows = sorted({clean(row["forward_window"]) for row in metrics}, key=lambda x: int(x.rstrip("D")) if x.rstrip("D").isdigit() else x)
    for window in windows:
        subset = [row for row in metrics if row["forward_window"] == window]
        stocks = [float(row["stock_topN_return"]) for row in subset]
        etfs = [float(row["etf_rotation_return"]) for row in subset]
        excess = [float(row["excess_vs_etf_rotation"]) for row in subset]
        qqq_pairs = [(float(row["stock_topN_return"]), float(row["qqq_return"])) for row in subset if math.isfinite(float(row["qqq_return"]))]
        spy_pairs = [(float(row["stock_topN_return"]), float(row["spy_return"])) for row in subset if math.isfinite(float(row["spy_return"]))]
        win_etf = sum(1 for row in subset if float(row["stock_topN_return"]) > float(row["etf_rotation_return"])) / len(subset) if subset else None
        win_qqq = sum(1 for stock, bench in qqq_pairs if stock > bench) / len(qqq_pairs) if qqq_pairs else None
        win_spy = sum(1 for stock, bench in spy_pairs if stock > bench) / len(spy_pairs) if spy_pairs else None
        rows.append({
            "forward_window": window,
            "trial_count": str(len(subset)),
            "avg_stock_topN_return": avg(stocks),
            "median_stock_topN_return": med(stocks),
            "avg_etf_rotation_return": avg(etfs),
            "median_etf_rotation_return": med(etfs),
            "avg_excess_vs_etf_rotation": avg(excess),
            "median_excess_vs_etf_rotation": med(excess),
            "win_rate_vs_etf_rotation": fmt(win_etf),
            "win_rate_vs_qqq": fmt(win_qqq),
            "win_rate_vs_spy": fmt(win_spy),
            "positive_excess_trial_count": str(sum(1 for value in excess if value > 0)),
            "negative_excess_trial_count": str(sum(1 for value in excess if value < 0)),
            "effectiveness_status": status_for(excess, win_etf),
        })
    return rows


def top_bottom_groups(metrics: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    ordered = sorted(metrics, key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
    size = max(1, math.ceil(len(ordered) * 0.10)) if ordered else 0
    top = ordered[:size]
    bottom = ordered[-size:] if size else []
    overall = {family: mean([float(row[f"{family}_weight"]) for row in metrics]) for family in ALL_FAMILIES} if metrics else {}

    def pattern(group: list[dict[str, object]]) -> str:
        if not group:
            return "UNAVAILABLE"
        parts = []
        for family in RANKING_FAMILIES:
            group_avg = mean([float(row[f"{family}_weight"]) for row in group])
            delta = group_avg - overall.get(family, group_avg)
            if abs(delta) >= 0.01:
                parts.append(f"{family.upper()}_{'HIGH' if delta > 0 else 'LOW'}")
        return "NO_COHERENT_PATTERN" if not parts else ";".join(parts)

    rows = []
    for name, group in [("TOP_DECILE_EXCESS", top), ("BOTTOM_DECILE_EXCESS", bottom)]:
        stocks = [float(row["stock_topN_return"]) for row in group]
        etfs = [float(row["etf_rotation_return"]) for row in group]
        excess = [float(row["excess_vs_etf_rotation"]) for row in group]
        rows.append({
            "group_name": name,
            "trial_count": str(len(group)),
            "avg_fundamental_weight": fmt(mean([float(row["fundamental_weight"]) for row in group])) if group else "",
            "avg_technical_weight": fmt(mean([float(row["technical_weight"]) for row in group])) if group else "",
            "avg_strategy_weight": fmt(mean([float(row["strategy_weight"]) for row in group])) if group else "",
            "avg_risk_weight": fmt(mean([float(row["risk_weight"]) for row in group])) if group else "",
            "avg_market_regime_weight": fmt(mean([float(row["market_regime_weight"]) for row in group])) if group else "",
            "avg_data_trust_weight": fmt(mean([float(row["data_trust_weight"]) for row in group])) if group else "",
            "avg_stock_topN_return": avg(stocks),
            "avg_etf_rotation_return": avg(etfs),
            "avg_excess_vs_etf_rotation": avg(excess),
            "median_excess_vs_etf_rotation": med(excess),
            "dominant_weight_pattern": pattern(group),
        })
    return rows, top, bottom


def family_rows(metrics: list[dict[str, object]], top: list[dict[str, object]], bottom: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    stocks = [float(row["stock_topN_return"]) for row in metrics]
    excess = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    for family in ALL_FAMILIES:
        weights = [float(row[f"{family}_weight"]) for row in metrics]
        stock_corr = corr(weights, stocks)
        excess_corr = corr(weights, excess)
        top_avg = mean([float(row[f"{family}_weight"]) for row in top]) if top else None
        bottom_avg = mean([float(row[f"{family}_weight"]) for row in bottom]) if bottom else None
        diff = (top_avg - bottom_avg) if top_avg is not None and bottom_avg is not None else 0.0
        if excess_corr is None:
            signal = "AUDIT_ONLY_ZERO_WEIGHT" if family == "data_trust" and not any(weights) else "NEUTRAL"
        elif excess_corr > 0.05 and diff > 0:
            signal = "POSITIVE"
        elif excess_corr < -0.05 and diff < 0:
            signal = "NEGATIVE"
        else:
            signal = "NEUTRAL"
        if signal == "POSITIVE" and abs(excess_corr or 0.0) >= 0.15 and abs(diff) >= 0.01:
            robust = "DIRECTIONAL_BIAS_REQUIRES_FUTURE_CONFIRMATION"
        elif signal in {"POSITIVE", "NEGATIVE"}:
            robust = "WEAK_DIRECTIONAL_ASSOCIATION"
        elif family == "data_trust" and not any(weights):
            robust = "AUDIT_ONLY_NOT_RANKING_WEIGHT"
        else:
            robust = "NO_ROBUST_BIAS"
        rows.append({
            "family_name": family,
            "min_weight": fmt(min(weights) if weights else None),
            "max_weight": fmt(max(weights) if weights else None),
            "avg_weight": fmt(mean(weights) if weights else None),
            "correlation_with_stock_topN_return": fmt(stock_corr),
            "correlation_with_excess_vs_etf_rotation": fmt(excess_corr),
            "top_decile_avg_weight": fmt(top_avg),
            "bottom_decile_avg_weight": fmt(bottom_avg),
            "directional_signal": signal,
            "robustness_status": robust,
        })
    return rows


def bucket_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for family in RANKING_FAMILIES:
        weights = [float(row[f"{family}_weight"]) for row in metrics]
        q33 = percentile(weights, 1 / 3)
        q66 = percentile(weights, 2 / 3)
        buckets: dict[str, list[dict[str, object]]] = {"LOW": [], "MID": [], "HIGH": []}
        for row in metrics:
            weight = float(row[f"{family}_weight"])
            bucket = "LOW" if q33 is not None and weight <= q33 else "HIGH" if q66 is not None and weight >= q66 else "MID"
            buckets[bucket].append(row)
        for bucket in ["LOW", "MID", "HIGH"]:
            subset = buckets[bucket]
            stocks = [float(row["stock_topN_return"]) for row in subset]
            excess = [float(row["excess_vs_etf_rotation"]) for row in subset]
            win_rate = sum(1 for row in subset if float(row["excess_vs_etf_rotation"]) > 0) / len(subset) if subset else None
            rows.append({
                "family_name": family,
                "weight_bucket": bucket,
                "trial_count": str(len(subset)),
                "avg_stock_topN_return": avg(stocks),
                "median_stock_topN_return": med(stocks),
                "avg_excess_vs_etf_rotation": avg(excess),
                "median_excess_vs_etf_rotation": med(excess),
                "win_rate_vs_etf_rotation": fmt(win_rate),
                "bucket_effectiveness_status": status_for(excess, win_rate),
            })
    return rows


def distribution_rows(excess: list[float]) -> list[dict[str, object]]:
    metrics = {
        "mean_excess": mean(excess) if excess else None,
        "median_excess": median(excess) if excess else None,
        "std_excess": math.sqrt(sum((value - mean(excess)) ** 2 for value in excess) / (len(excess) - 1)) if len(excess) > 1 else 0.0 if excess else None,
        "min_excess": min(excess) if excess else None,
        "max_excess": max(excess) if excess else None,
        "p10_excess": percentile(excess, 0.10),
        "p25_excess": percentile(excess, 0.25),
        "p75_excess": percentile(excess, 0.75),
        "p90_excess": percentile(excess, 0.90),
        "positive_excess_rate": sum(1 for value in excess if value > 0) / len(excess) if excess else None,
        "negative_excess_rate": sum(1 for value in excess if value < 0) / len(excess) if excess else None,
    }
    return [{"metric_name": name, "metric_value": fmt(value)} for name, value in metrics.items()]


def gate_row(metrics: list[dict[str, object]], windows: list[dict[str, object]], families: list[dict[str, object]]) -> dict[str, object]:
    excess = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    avg_excess = mean(excess) if excess else 0.0
    med_excess = median(excess) if excess else 0.0
    win_rate = sum(1 for value in excess if value > 0) / len(excess) if excess else 0.0
    best_window = max(windows, key=lambda row: num(row["avg_excess_vs_etf_rotation"]) if num(row["avg_excess_vs_etf_rotation"]) is not None else -999.0)["forward_window"] if windows else ""
    positive = [row for row in families if row["directional_signal"] == "POSITIVE"]
    negative = [row for row in families if row["directional_signal"] == "NEGATIVE"]
    strongest_pos = max(positive, key=lambda row: num(row["correlation_with_excess_vs_etf_rotation"]) or -999.0)["family_name"] if positive else "NONE"
    strongest_neg = min(negative, key=lambda row: num(row["correlation_with_excess_vs_etf_rotation"]) or 999.0)["family_name"] if negative else "NONE"
    robust_window = any(
        (num(row["avg_excess_vs_etf_rotation"]) or 0.0) > 0
        and (num(row["median_excess_vs_etf_rotation"]) or 0.0) > 0
        and (num(row["win_rate_vs_etf_rotation"]) or 0.0) >= 0.55
        for row in windows
    )
    if avg_excess > 0 and med_excess > 0 and win_rate >= 0.55:
        final_status = CANDIDATE_STATUS
        recommended = "TRUE"
        evidence = "ROBUST_OVERALL_POSITIVE"
        reason = "Overall mean, median, and ETF win rate are positive enough for shadow-weight observation."
        next_action = "Open a future shadow-weight observation candidate; keep official weights unchanged."
    elif avg_excess > 0 and med_excess <= 0:
        final_status = MEAN_ONLY_STATUS
        recommended = "FALSE"
        evidence = "MEAN_ONLY_EDGE_NOT_ROBUST"
        reason = "Average excess is positive but median excess is not positive; edge is not robust."
        next_action = "Continue ETF rotation as the primary benchmark and keep random-weight stock ranking research-only."
    else:
        final_status = NO_CHANGE_STATUS
        recommended = "FALSE"
        evidence = "MIXED_SUBWINDOW_ONLY" if robust_window else "NO_ROBUST_POSITIVE_EDGE"
        reason = "Random weights do not show robust overall excess versus ETF rotation."
        next_action = "Continue ETF rotation as the primary benchmark and keep random-weight stock ranking research-only."
    return {
        "final_status": final_status,
        "valid_trial_count": str(len(metrics)),
        "avg_excess_vs_etf_rotation": fmt(avg_excess),
        "median_excess_vs_etf_rotation": fmt(med_excess),
        "win_rate_vs_etf_rotation": fmt(win_rate),
        "best_forward_window": best_window,
        "strongest_positive_family_bias": strongest_pos,
        "strongest_negative_family_bias": strongest_neg,
        "evidence_strength": evidence,
        "shadow_weight_change_recommended": recommended,
        "reason": reason,
        "next_recommended_action": next_action,
        **COMMON,
    }


def main() -> int:
    if not required_inputs_ready():
        missing = [path.name for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0 or not read_csv(path)]
        return blocked_outputs("Missing or empty required V20.201 outputs: " + ", ".join(missing))

    trials = read_csv(IN_TRIALS)
    forward = read_csv(IN_FORWARD)
    etf = read_csv(IN_ETF)
    summary_rows = read_csv(IN_SUMMARY)
    summary = summary_rows[0] if summary_rows else {}

    metrics = build_trial_metrics(trials, forward, etf)
    windows = forward_window_rows(metrics)
    top_bottom, top, bottom = top_bottom_groups(metrics)
    families = family_rows(metrics, top, bottom)
    buckets = bucket_rows(metrics)
    excess = [float(row["excess_vs_etf_rotation"]) for row in metrics]
    distribution = distribution_rows(excess)
    gate = gate_row(metrics, windows, families)

    write_csv(OUT_WINDOW, WINDOW_FIELDS, windows)
    write_csv(OUT_FAMILY, FAMILY_FIELDS, families)
    write_csv(OUT_BUCKET, BUCKET_FIELDS, buckets)
    write_csv(OUT_TOP_BOTTOM, TOP_BOTTOM_FIELDS, top_bottom)
    write_csv(OUT_DISTRIBUTION, DISTRIBUTION_FIELDS, distribution)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, summary, windows, families, top_bottom)

    print(f"FINAL_STATUS={gate['final_status']}")
    print(f"VALID_TRIAL_COUNT={gate['valid_trial_count']}")
    print(f"AVG_EXCESS_VS_ETF_ROTATION={gate['avg_excess_vs_etf_rotation']}")
    print(f"MEDIAN_EXCESS_VS_ETF_ROTATION={gate['median_excess_vs_etf_rotation']}")
    print(f"SHADOW_WEIGHT_CHANGE_RECOMMENDED={gate['shadow_weight_change_recommended']}")
    print("RESEARCH_ONLY=TRUE")
    print("OFFICIAL_WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_SIGNAL_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
