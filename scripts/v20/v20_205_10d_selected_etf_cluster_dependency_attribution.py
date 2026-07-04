#!/usr/bin/env python
"""V20.205 selected ETF cluster dependency attribution.

Research-only attribution over V20.204 expanded 10D outputs. This stage does
not rerun trials and cannot recommend shadow weight activation.
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

IN_TRIALS = OUT_DIR / "V20_204_10D_EXPANDED_TRIALS.csv"
IN_FORWARD = OUT_DIR / "V20_204_10D_EXPANDED_FORWARD_OUTCOMES.csv"
IN_ETF = OUT_DIR / "V20_204_10D_EXPANDED_ETF_BENCHMARK_OUTCOMES.csv"
IN_SUMMARY = OUT_DIR / "V20_204_10D_ROBUSTNESS_SUMMARY.csv"
IN_BOOT = OUT_DIR / "V20_204_10D_BOOTSTRAP_CONFIDENCE.csv"
IN_TRIM = OUT_DIR / "V20_204_10D_TRIMMED_WINSORIZED_ANALYSIS.csv"
IN_LOO = OUT_DIR / "V20_204_10D_LEAVE_ONE_CLUSTER_OUT.csv"
IN_BIAS = OUT_DIR / "V20_204_10D_WEIGHT_BIAS_REPEATABILITY.csv"
IN_GATE = OUT_DIR / "V20_204_10D_ROBUSTNESS_GATE.csv"
REQUIRED_INPUTS = [IN_TRIALS, IN_FORWARD, IN_ETF, IN_SUMMARY, IN_BOOT, IN_TRIM, IN_LOO, IN_BIAS, IN_GATE]

OUT_EFFECT = OUT_DIR / "V20_205_SELECTED_ETF_CLUSTER_EFFECTIVENESS.csv"
OUT_LOO = OUT_DIR / "V20_205_SELECTED_ETF_LEAVE_ONE_OUT_DIAGNOSTICS.csv"
OUT_CONTRIB = OUT_DIR / "V20_205_SELECTED_ETF_CONTRIBUTION_DECOMPOSITION.csv"
OUT_BIAS = OUT_DIR / "V20_205_CLUSTER_WEIGHT_BIAS_DIAGNOSTICS.csv"
OUT_RISK = OUT_DIR / "V20_205_CLUSTER_DEPENDENCY_RISK_AUDIT.csv"
OUT_GATE = OUT_DIR / "V20_205_10D_OBSERVATION_CONTINUATION_GATE.csv"
OUT_REPORT = READ_CENTER / "V20_205_10D_SELECTED_ETF_CLUSTER_DEPENDENCY_ATTRIBUTION_REPORT.md"

FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime", "data_trust"]
RANKING_FAMILIES = ["fundamental", "technical", "strategy", "risk", "market_regime"]

EFFECT_FIELDS = [
    "selected_etf", "trial_count", "trial_share", "avg_stock_topN_return",
    "median_stock_topN_return", "avg_etf_rotation_return", "median_etf_rotation_return",
    "avg_excess_vs_etf_rotation", "median_excess_vs_etf_rotation",
    "win_rate_vs_etf_rotation", "positive_excess_count", "negative_excess_count",
    "cluster_effectiveness_status", "cluster_comment",
]
LOO_FIELDS = [
    "excluded_selected_etf", "excluded_trial_count", "remaining_trial_count",
    "remaining_avg_excess_vs_etf_rotation", "remaining_median_excess_vs_etf_rotation",
    "remaining_win_rate_vs_etf_rotation", "edge_survives_exclusion",
    "weak_exclusion_flag", "exclusion_comment",
]
CONTRIB_FIELDS = [
    "selected_etf", "trial_count", "trial_share", "avg_excess_vs_etf_rotation",
    "total_excess_contribution", "contribution_share_of_total_positive_excess",
    "contribution_share_of_total_absolute_excess", "concentration_flag",
    "contribution_comment",
]
BIAS_FIELDS = [
    "selected_etf", "family_name", "avg_weight_all_cluster",
    "avg_weight_top_10pct_cluster", "avg_weight_bottom_10pct_cluster",
    "top_minus_bottom_weight_delta", "correlation_with_cluster_excess",
    "directional_signal", "cluster_bias_status",
]
RISK_FIELDS = ["metric_name", "metric_value", "risk_status", "comment"]
GATE_FIELDS = [
    "final_status", "valid_trial_count", "selected_etf_cluster_count",
    "robust_positive_cluster_count", "negative_cluster_count", "weak_exclusion_count",
    "top_positive_contribution_share", "cluster_dependency_risk_level",
    "local_edge_observation_recommended", "shadow_weight_change_recommended",
    "reason", "next_recommended_action",
]

STATUS_OK = "PASS_V20_205_10D_EDGE_CLUSTER_DISTRIBUTION_ACCEPTABLE_FOR_OBSERVATION"
STATUS_MOD = "PARTIAL_PASS_V20_205_10D_EDGE_CLUSTER_DEPENDENCY_MODERATE"
STATUS_HIGH = "PARTIAL_PASS_V20_205_10D_EDGE_CLUSTER_DEPENDENCY_HIGH"
STATUS_INSUFF = "PARTIAL_PASS_V20_205_INSUFFICIENT_CLUSTER_EVIDENCE"
STATUS_MISSING = "BLOCKED_V20_205_REQUIRED_INPUT_MISSING"


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
            "selected_etf": etf_row.get("selected_etf", ""),
            "stock_topN_return": stock_return,
            "etf_rotation_return": etf_return,
            "excess_vs_etf_rotation": stock_return - etf_return,
        }
        for family in FAMILIES:
            metric[f"{family}_weight"] = num(trial.get(f"{family}_weight")) or 0.0
        metrics.append(metric)
    return metrics


def cluster_status(count: int, avg_excess: float, med_excess: float, win_rate: float) -> tuple[str, str]:
    if count < 30:
        return "INSUFFICIENT_CLUSTER_SAMPLE", "Cluster has fewer than 30 trials."
    if avg_excess > 0 and med_excess > 0 and win_rate >= 0.55:
        return "ROBUST_POSITIVE_CLUSTER", "Cluster independently supports the 10D edge versus ETF rotation."
    if (avg_excess > 0 or med_excess > 0) and win_rate < 0.55:
        return "MIXED_POSITIVE_CLUSTER", "Cluster has positive central evidence but weak win-rate support."
    if abs(avg_excess) <= 0.001 and abs(med_excess) <= 0.001:
        return "NEUTRAL_CLUSTER", "Cluster is close to flat versus ETF rotation."
    if avg_excess < 0 and med_excess < 0:
        return "NEGATIVE_CLUSTER", "Cluster underperforms ETF rotation on mean and median."
    return "MIXED_POSITIVE_CLUSTER", "Cluster evidence is mixed."


def effect_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    total = len(metrics)
    by_etf: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in metrics:
        by_etf[clean(row["selected_etf"]) or "UNKNOWN"].append(row)
    rows = []
    for selected_etf in sorted(by_etf):
        group = by_etf[selected_etf]
        stocks = [float(row["stock_topN_return"]) for row in group]
        etfs = [float(row["etf_rotation_return"]) for row in group]
        excess = [float(row["excess_vs_etf_rotation"]) for row in group]
        win_rate = sum(1 for value in excess if value > 0) / len(excess) if excess else 0.0
        avg_excess = mean(excess) if excess else 0.0
        med_excess = median(excess) if excess else 0.0
        status, comment = cluster_status(len(group), avg_excess, med_excess, win_rate)
        rows.append({
            "selected_etf": selected_etf,
            "trial_count": str(len(group)),
            "trial_share": fmt(len(group) / total if total else None),
            "avg_stock_topN_return": fmt(mean(stocks) if stocks else None),
            "median_stock_topN_return": fmt(median(stocks) if stocks else None),
            "avg_etf_rotation_return": fmt(mean(etfs) if etfs else None),
            "median_etf_rotation_return": fmt(median(etfs) if etfs else None),
            "avg_excess_vs_etf_rotation": fmt(avg_excess),
            "median_excess_vs_etf_rotation": fmt(med_excess),
            "win_rate_vs_etf_rotation": fmt(win_rate),
            "positive_excess_count": str(sum(1 for value in excess if value > 0)),
            "negative_excess_count": str(sum(1 for value in excess if value < 0)),
            "cluster_effectiveness_status": status,
            "cluster_comment": comment,
        })
    return rows


def loo_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    clusters = sorted({clean(row["selected_etf"]) for row in metrics if clean(row["selected_etf"])})
    for cluster in clusters:
        remaining = [row for row in metrics if clean(row["selected_etf"]) != cluster]
        values = [float(row["excess_vs_etf_rotation"]) for row in remaining]
        avg_value = mean(values) if values else 0.0
        med_value = median(values) if values else 0.0
        win_rate = sum(1 for value in values if value > 0) / len(values) if values else 0.0
        weak = avg_value <= 0 or med_value <= 0 or win_rate < 0.55
        rows.append({
            "excluded_selected_etf": cluster,
            "excluded_trial_count": str(len(metrics) - len(remaining)),
            "remaining_trial_count": str(len(remaining)),
            "remaining_avg_excess_vs_etf_rotation": fmt(avg_value),
            "remaining_median_excess_vs_etf_rotation": fmt(med_value),
            "remaining_win_rate_vs_etf_rotation": fmt(win_rate),
            "edge_survives_exclusion": tf(not weak),
            "weak_exclusion_flag": tf(weak),
            "exclusion_comment": "Excluding this ETF weakens the expanded 10D edge below robustness thresholds." if weak else "Expanded 10D edge survives this ETF exclusion.",
        })
    return rows


def contribution_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    total = len(metrics)
    by_etf: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in metrics:
        by_etf[clean(row["selected_etf"]) or "UNKNOWN"].append(row)
    total_positive = sum(max(0.0, float(row["excess_vs_etf_rotation"])) for row in metrics)
    total_abs = sum(abs(float(row["excess_vs_etf_rotation"])) for row in metrics)
    raw = []
    for selected_etf, group in by_etf.items():
        total_excess = sum(float(row["excess_vs_etf_rotation"]) for row in group)
        positive_contribution = sum(max(0.0, float(row["excess_vs_etf_rotation"])) for row in group)
        raw.append({
            "selected_etf": selected_etf,
            "trial_count": str(len(group)),
            "trial_share": fmt(len(group) / total if total else None),
            "avg_excess_vs_etf_rotation": fmt(mean([float(row["excess_vs_etf_rotation"]) for row in group]) if group else None),
            "total_excess_contribution": fmt(total_excess),
            "contribution_share_of_total_positive_excess": fmt(positive_contribution / total_positive if total_positive else None),
            "contribution_share_of_total_absolute_excess": fmt(sum(abs(float(row["excess_vs_etf_rotation"])) for row in group) / total_abs if total_abs else None),
        })
    top_share = max((num(row["contribution_share_of_total_positive_excess"]) or 0.0 for row in raw), default=0.0)
    if top_share > 0.50:
        flag = "HIGH_CONCENTRATION"
    elif top_share >= 0.30:
        flag = "MODERATE_CONCENTRATION"
    else:
        flag = "BROAD_DISTRIBUTION"
    for row in raw:
        row["concentration_flag"] = flag
        row["contribution_comment"] = "Positive excess is concentrated in the top selected ETF cluster." if flag != "BROAD_DISTRIBUTION" else "Positive excess is broadly distributed across selected ETF clusters."
    return sorted(raw, key=lambda row: row["selected_etf"])


def bias_rows(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    by_etf: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in metrics:
        by_etf[clean(row["selected_etf"]) or "UNKNOWN"].append(row)
    rows = []
    for selected_etf in sorted(by_etf):
        group = sorted(by_etf[selected_etf], key=lambda row: float(row["excess_vs_etf_rotation"]), reverse=True)
        size = max(1, math.ceil(len(group) * 0.10)) if group else 0
        top = group[:size]
        bottom = group[-size:] if size else []
        excess = [float(row["excess_vs_etf_rotation"]) for row in group]
        for family in FAMILIES:
            weights = [float(row[f"{family}_weight"]) for row in group]
            top_avg = mean([float(row[f"{family}_weight"]) for row in top]) if top else None
            bottom_avg = mean([float(row[f"{family}_weight"]) for row in bottom]) if bottom else None
            delta = (top_avg - bottom_avg) if top_avg is not None and bottom_avg is not None else 0.0
            family_corr = corr(weights, excess)
            if family == "data_trust" and not any(weights):
                signal = "AUDIT_ONLY_ZERO_WEIGHT"
                status = "AUDIT_ONLY_NOT_RANKING_WEIGHT"
            elif family_corr is not None and family_corr > 0.05 and delta > 0:
                signal = "POSITIVE"
                status = "COHERENT_CLUSTER_BIAS" if abs(family_corr) >= 0.10 and abs(delta) >= 0.01 else "WEAK_CLUSTER_BIAS"
            elif family_corr is not None and family_corr < -0.05 and delta < 0:
                signal = "NEGATIVE"
                status = "COHERENT_CLUSTER_BIAS" if abs(family_corr) >= 0.10 and abs(delta) >= 0.01 else "WEAK_CLUSTER_BIAS"
            else:
                signal = "NEUTRAL"
                status = "NO_COHERENT_CLUSTER_BIAS"
            rows.append({
                "selected_etf": selected_etf,
                "family_name": family,
                "avg_weight_all_cluster": fmt(mean(weights) if weights else None),
                "avg_weight_top_10pct_cluster": fmt(top_avg),
                "avg_weight_bottom_10pct_cluster": fmt(bottom_avg),
                "top_minus_bottom_weight_delta": fmt(delta),
                "correlation_with_cluster_excess": fmt(family_corr),
                "directional_signal": signal,
                "cluster_bias_status": status,
            })
    return rows


def risk_and_gate(metrics: list[dict[str, object]], effects: list[dict[str, object]], loo: list[dict[str, object]], contrib: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    cluster_count = len(effects)
    largest_share = max((num(row["trial_share"]) or 0.0 for row in effects), default=0.0)
    top_positive_share = max((num(row["contribution_share_of_total_positive_excess"]) or 0.0 for row in contrib), default=0.0)
    negative_count = sum(1 for row in effects if row["cluster_effectiveness_status"] == "NEGATIVE_CLUSTER")
    robust_count = sum(1 for row in effects if row["cluster_effectiveness_status"] == "ROBUST_POSITIVE_CLUSTER")
    weak_count = sum(1 for row in loo if row["weak_exclusion_flag"] == "TRUE")
    broad = top_positive_share <= 0.30
    insufficient = cluster_count < 2 or sum(1 for row in effects if int(row["trial_count"]) < 30) > cluster_count / 2
    if insufficient:
        risk = "INSUFFICIENT_CLUSTER_EVIDENCE"
    elif weak_count > 1 or top_positive_share > 0.50:
        risk = "HIGH_CLUSTER_DEPENDENCY_RISK"
    elif broad and weak_count == 0 and robust_count >= 2:
        risk = "LOW_CLUSTER_DEPENDENCY_RISK"
    elif weak_count <= 1 and robust_count >= 1:
        risk = "MODERATE_CLUSTER_DEPENDENCY_RISK"
    else:
        risk = "HIGH_CLUSTER_DEPENDENCY_RISK"

    rows = [
        {"metric_name": "selected_etf_cluster_count", "metric_value": str(cluster_count), "risk_status": risk, "comment": "Number of selected ETF clusters in expanded 10D trials."},
        {"metric_name": "largest_cluster_trial_share", "metric_value": fmt(largest_share), "risk_status": risk, "comment": "Largest single-cluster share of valid trials."},
        {"metric_name": "top_positive_contribution_share", "metric_value": fmt(top_positive_share), "risk_status": risk, "comment": "Largest selected ETF share of total positive excess."},
        {"metric_name": "negative_cluster_count", "metric_value": str(negative_count), "risk_status": risk, "comment": "Clusters with negative mean and median excess."},
        {"metric_name": "robust_positive_cluster_count", "metric_value": str(robust_count), "risk_status": risk, "comment": "Clusters with positive mean, median, and win rate >= 0.55."},
        {"metric_name": "weak_exclusion_count", "metric_value": str(weak_count), "risk_status": risk, "comment": "Selected ETF exclusions that break the 10D edge thresholds."},
        {"metric_name": "broad_distribution_detected", "metric_value": tf(broad), "risk_status": risk, "comment": "TRUE when no cluster contributes more than 30% of total positive excess."},
        {"metric_name": "cluster_dependency_risk_level", "metric_value": risk, "risk_status": risk, "comment": "Overall selected ETF cluster dependency classification."},
    ]
    if risk == "LOW_CLUSTER_DEPENDENCY_RISK":
        final_status = STATUS_OK
        reason = "10D edge appears broadly distributed enough for continued observation."
    elif risk == "MODERATE_CLUSTER_DEPENDENCY_RISK":
        final_status = STATUS_MOD
        reason = "10D edge has moderate selected ETF dependency; continued observation only."
    elif risk == "HIGH_CLUSTER_DEPENDENCY_RISK":
        final_status = STATUS_HIGH
        reason = "10D edge is selected ETF cluster-dependent; do not advance toward shadow activation."
    else:
        final_status = STATUS_INSUFF
        reason = "Selected ETF cluster evidence is insufficient for dependency assessment."
    gate = {
        "final_status": final_status,
        "valid_trial_count": str(len(metrics)),
        "selected_etf_cluster_count": str(cluster_count),
        "robust_positive_cluster_count": str(robust_count),
        "negative_cluster_count": str(negative_count),
        "weak_exclusion_count": str(weak_count),
        "top_positive_contribution_share": fmt(top_positive_share),
        "cluster_dependency_risk_level": risk,
        "local_edge_observation_recommended": "TRUE",
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": "Continue 10D local-edge observation only; ETF rotation remains the primary benchmark and shadow weight change is not recommended.",
    }
    return rows, gate


def write_report(gate: dict[str, object], effects: list[dict[str, object]], loo: list[dict[str, object]], contrib: list[dict[str, object]], bias: list[dict[str, object]]) -> None:
    READ_CENTER.mkdir(parents=True, exist_ok=True)
    weak = [row for row in loo if row["weak_exclusion_flag"] == "TRUE"]
    robust = [row for row in effects if row["cluster_effectiveness_status"] == "ROBUST_POSITIVE_CLUSTER"]
    weak_clusters = [row for row in effects if row["cluster_effectiveness_status"] != "ROBUST_POSITIVE_CLUSTER"]
    coherent_bias = [row for row in bias if row["cluster_bias_status"] == "COHERENT_CLUSTER_BIAS"]
    top_contrib = sorted(contrib, key=lambda row: num(row["contribution_share_of_total_positive_excess"]) or 0.0, reverse=True)[:3]
    lines = [
        "# V20.205 10D Selected ETF Cluster Dependency Attribution Report",
        "",
        f"- Final status: {gate.get('final_status', '')}",
        "- V20.201 context: random-weight PIT-forward consolidation passed.",
        "- V20.202 context: no shadow weight change was recommended.",
        "- V20.203 context: 10D edge was weak or outlier-sensitive.",
        "- V20.204 context: expanded 10D evidence improved, but leave-one-selected-ETF robustness failed.",
        "",
        "Selected ETF cluster effectiveness:",
        *(f"- {row['selected_etf']}: trials={row['trial_count']}, avg_excess={row['avg_excess_vs_etf_rotation']}, median_excess={row['median_excess_vs_etf_rotation']}, win_rate={row['win_rate_vs_etf_rotation']}, status={row['cluster_effectiveness_status']}" for row in effects),
        "",
        "Weak leave-one-out behavior:",
        *(f"- Excluding {row['excluded_selected_etf']}: remaining_avg={row['remaining_avg_excess_vs_etf_rotation']}, remaining_win_rate={row['remaining_win_rate_vs_etf_rotation']}" for row in weak),
        *(["- No selected ETF exclusion broke the edge thresholds."] if not weak else []),
        "",
        f"- Distribution assessment: {gate.get('cluster_dependency_risk_level', '')}",
        "Top positive contribution clusters:",
        *(f"- {row['selected_etf']}: positive_share={row['contribution_share_of_total_positive_excess']}, concentration={row['concentration_flag']}" for row in top_contrib),
        "",
        "Robust positive clusters:",
        *(f"- {row['selected_etf']}" for row in robust),
        *(["- None."] if not robust else []),
        "Negative or weak clusters:",
        *(f"- {row['selected_etf']}: {row['cluster_effectiveness_status']}" for row in weak_clusters),
        *(["- None."] if not weak_clusters else []),
        "",
        "Cluster-specific weight bias:",
        *(f"- {row['selected_etf']} {row['family_name']}: delta={row['top_minus_bottom_weight_delta']}, corr={row['correlation_with_cluster_excess']}, signal={row['directional_signal']}" for row in coherent_bias[:10]),
        *(["- No coherent cluster-specific family bias strong enough for activation work."] if not coherent_bias else []),
        "",
        f"- 10D local-edge observation should continue: {gate.get('local_edge_observation_recommended', '')}",
        f"- Reason: {gate.get('reason', '')}",
        f"- Next recommended action: {gate.get('next_recommended_action', '')}",
        "",
        "Safety statement:",
        "- official weights were not changed",
        "- no official recommendation was created",
        "- no real-book signal was created",
        "- no broker execution was created",
        "- shadow weight change is not recommended in V20.205",
        "- no trade action was created",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def blocked_outputs(reason: str) -> int:
    gate = {
        "final_status": STATUS_MISSING,
        "valid_trial_count": "0",
        "selected_etf_cluster_count": "0",
        "robust_positive_cluster_count": "0",
        "negative_cluster_count": "0",
        "weak_exclusion_count": "0",
        "top_positive_contribution_share": "",
        "cluster_dependency_risk_level": "INSUFFICIENT_CLUSTER_EVIDENCE",
        "local_edge_observation_recommended": "TRUE",
        "shadow_weight_change_recommended": "FALSE",
        "reason": reason,
        "next_recommended_action": "Restore required V20.204 inputs before cluster dependency attribution.",
    }
    write_csv(OUT_EFFECT, EFFECT_FIELDS, [])
    write_csv(OUT_LOO, LOO_FIELDS, [])
    write_csv(OUT_CONTRIB, CONTRIB_FIELDS, [])
    write_csv(OUT_BIAS, BIAS_FIELDS, [])
    write_csv(OUT_RISK, RISK_FIELDS, [{"metric_name": "cluster_dependency_risk_level", "metric_value": "INSUFFICIENT_CLUSTER_EVIDENCE", "risk_status": "INSUFFICIENT_CLUSTER_EVIDENCE", "comment": reason}])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, [], [], [], [])
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
        return blocked_outputs("Missing or empty required V20.204 inputs: " + ", ".join(missing))
    metrics = build_metrics()
    if not metrics:
        return blocked_outputs("No valid expanded 10D trial metrics could be reconstructed.")
    effects = effect_rows(metrics)
    loo = loo_rows(metrics)
    contrib = contribution_rows(metrics)
    bias = bias_rows(metrics)
    risk, gate = risk_and_gate(metrics, effects, loo, contrib)
    write_csv(OUT_EFFECT, EFFECT_FIELDS, effects)
    write_csv(OUT_LOO, LOO_FIELDS, loo)
    write_csv(OUT_CONTRIB, CONTRIB_FIELDS, contrib)
    write_csv(OUT_BIAS, BIAS_FIELDS, bias)
    write_csv(OUT_RISK, RISK_FIELDS, risk)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate, effects, loo, contrib, bias)
    print(f"FINAL_STATUS={gate['final_status']}")
    print(f"VALID_TRIAL_COUNT={gate['valid_trial_count']}")
    print(f"CLUSTER_DEPENDENCY_RISK_LEVEL={gate['cluster_dependency_risk_level']}")
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
