#!/usr/bin/env python
"""V20.162 bound shadow elevated rank impact review.

Reviews the elevated rank impact observed in V20.161 using only the existing
V20.161 stability outputs and V20.158-R2 bound shadow rank outputs. This stage
is research-only and does not create proposals, mutate official rankings or
weights, create recommendations, claim performance, or create any real-book,
trade, or broker action.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V161_RUNS = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_RUNS.csv"
V161_SUMMARY = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SUMMARY.csv"
V161_GATE = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_GATE.csv"
V161_SOURCE = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SOURCE_AUDIT.csv"
V161_SAFETY = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_SAFETY_AUDIT.csv"
V161_LIMITATION = FACTORS / "V20_161_BOUND_SHADOW_STABILITY_LIMITATION_AUDIT.csv"

V158_R2_SIM = FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv"
V158_R2_DELTA = FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
V158_R2_GATE = FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv"

OUT_REVIEW = FACTORS / "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW.csv"
OUT_DISTRIBUTION = FACTORS / "V20_162_BOUND_SHADOW_RANK_DELTA_DISTRIBUTION.csv"
OUT_OUTLIERS = FACTORS / "V20_162_BOUND_SHADOW_OUTLIER_TICKER_AUDIT.csv"
OUT_ATTRIBUTION = FACTORS / "V20_162_BOUND_SHADOW_FACTOR_IMPACT_ATTRIBUTION.csv"
OUT_CAP = FACTORS / "V20_162_BOUND_SHADOW_CAP_RECOMMENDATION.csv"
OUT_GATE = FACTORS / "V20_162_BOUND_SHADOW_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW_REPORT.md"

PASS_V161 = "PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_READY_FOR_V20_162"
PARTIAL_V161 = "PARTIAL_PASS_V20_161_BOUND_SHADOW_STABILITY_OBSERVATION_WITH_ELEVATED_RANK_IMPACT_READY_FOR_V20_162"
PASS_STATUS = "PASS_V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW_READY_FOR_V20_163"
PARTIAL_STATUS = "PARTIAL_PASS_V20_162_BOUND_SHADOW_REVIEW_REQUIRES_SCORE_ADJUSTMENT_CAP"
WARN_STATUS = "WARN_V20_162_BOUND_SHADOW_RANK_IMPACT_TOO_CONCENTRATED"
BLOCKED_STATUS = "BLOCKED_V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE"

OUTLIER_DELTA_THRESHOLD = 5
CONCENTRATION_WARN_THRESHOLD = 0.75

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "bound_shadow_elevated_rank_impact_review_created": "TRUE",
    "shadow_review_scope": SCOPE,
    "shadow_weight_expansion_allowed": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
}
COMMON = {
    **SAFETY,
    "research_only": "TRUE",
    "staging_review_only": "TRUE",
    "elevated_rank_impact_review_only": "TRUE",
    "audit_only": "TRUE",
}

REVIEW_FIELDS = [
    "review_id",
    "observation_run_count",
    "average_top20_turnover_rate",
    "max_top20_turnover_rate",
    "average_rank_delta_across_runs",
    "max_rank_delta_across_runs",
    "median_rank_delta_across_runs",
    "elevated_rank_impact_confirmed",
    "top20_membership_stable",
    "internal_rank_churn_detected",
    "outlier_ticker_count",
    "top20_internal_churn_count",
    "non_top20_churn_count",
    "factor_impact_concentration",
    "score_adjustment_cap_required",
    "rank_movement_cap_required",
    "continued_shadow_research_allowed",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "recommended_next_action",
    *COMMON.keys(),
]
DIST_FIELDS = [
    "rank_delta_bucket",
    "ticker_count",
    "baseline_top20_count",
    "bound_shadow_top20_count",
    "max_absolute_rank_delta_in_bucket",
    "outlier_bucket_flag",
    *COMMON.keys(),
]
OUTLIER_FIELDS = [
    "ticker",
    "baseline_rank",
    "bound_shadow_rank",
    "absolute_rank_delta",
    "baseline_top20_flag",
    "bound_shadow_top20_flag",
    "outlier_rank_impact_flag",
    "likely_factor_driver",
    "cap_needed",
    *COMMON.keys(),
]
ATTRIBUTION_FIELDS = [
    "factor_driver",
    "impacted_ticker_count",
    "outlier_ticker_count",
    "max_absolute_rank_delta",
    "average_absolute_rank_delta",
    "factor_impact_concentration",
    "concentration_warning_flag",
    "score_adjustment_cap_required",
    *COMMON.keys(),
]
CAP_FIELDS = [
    "cap_recommendation_id",
    "score_adjustment_cap_required",
    "rank_movement_cap_required",
    "recommended_score_cap_scope",
    "recommended_rank_movement_cap",
    "cap_reason",
    "creates_official_recommendation",
    "official_weight_change_allowed",
    "shadow_weight_expansion_allowed",
    "continued_shadow_research_allowed",
    "recommended_next_action",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_161_gate_consumed",
    "v20_161_status",
    "v20_158_r2_gate_consumed",
    "v20_158_r2_status",
    "stable_enough_for_shadow_continuation",
    "stable_enough_for_shadow_expansion",
    "stable_enough_for_official_weight_change",
    "official_weight_change_allowed",
    "shadow_weight_expansion_allowed",
    "elevated_rank_impact_confirmed",
    "top20_membership_stable",
    "internal_rank_churn_detected",
    "outlier_ticker_count",
    "factor_impact_concentration",
    "score_adjustment_cap_required",
    "rank_movement_cap_required",
    "continued_shadow_research_allowed",
    "no_new_shadow_proposal_rows_created",
    "no_factor_scope_expansion",
    "no_official_ranking_mutated",
    "no_official_weights_mutated",
    "no_official_recommendation_created",
    "no_real_book_action_created",
    "no_trade_action_created",
    "no_broker_action_created",
    "no_outcomes_fabricated",
    "no_benchmarks_fabricated",
    "no_performance_claim_created",
    "no_upstream_outputs_mutated",
    "v20_163_allowed",
    "blocking_reason",
    "final_status",
    *COMMON.keys(),
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: object) -> bool:
    return clean(value).upper() == "TRUE"


def num(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(clean(value))
    except ValueError:
        return default
    return default if math.isnan(parsed) or math.isinf(parsed) else parsed


def intish(value: object, default: int = 0) -> int:
    return int(round(num(value, float(default))))


def fmt(value: float) -> str:
    return f"{value:.10f}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: clean(value) for key, value in row.items()} for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inputs() -> list[Path]:
    return [
        V161_RUNS, V161_SUMMARY, V161_GATE, V161_SOURCE, V161_SAFETY, V161_LIMITATION,
        V158_R2_SIM, V158_R2_DELTA, V158_R2_GATE,
    ]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def factor_driver(row: dict[str, str]) -> str:
    driver = clean(row.get("affected_factor_family"))
    if driver:
        return driver
    source = clean(row.get("reduced_shadow_adjustment_source"))
    return source if source else "UNKNOWN_FACTOR_DRIVER"


def ticker_metrics(sim_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    for row in sim_rows:
        baseline_rank = intish(row.get("authoritative_baseline_rank"))
        shadow_rank = intish(row.get("bound_reduced_shadow_rank"))
        delta = abs(intish(row.get("bound_reduced_rank_delta"), shadow_rank - baseline_rank))
        baseline_top20 = 0 < baseline_rank <= 20
        shadow_top20 = 0 < shadow_rank <= 20
        metrics.append({
            "ticker": clean(row.get("ticker")),
            "baseline_rank": baseline_rank,
            "shadow_rank": shadow_rank,
            "absolute_rank_delta": delta,
            "baseline_top20": baseline_top20,
            "shadow_top20": shadow_top20,
            "driver": factor_driver(row),
        })
    return metrics


def outlier_rows(metrics: list[dict[str, object]]) -> list[dict[str, str]]:
    rows = []
    for item in metrics:
        delta = int(item["absolute_rank_delta"])
        if delta < OUTLIER_DELTA_THRESHOLD:
            continue
        rows.append({
            "ticker": str(item["ticker"]),
            "baseline_rank": str(item["baseline_rank"]),
            "bound_shadow_rank": str(item["shadow_rank"]),
            "absolute_rank_delta": str(delta),
            "baseline_top20_flag": tf(bool(item["baseline_top20"])),
            "bound_shadow_top20_flag": tf(bool(item["shadow_top20"])),
            "outlier_rank_impact_flag": "TRUE",
            "likely_factor_driver": str(item["driver"]),
            "cap_needed": "TRUE",
            **COMMON,
        })
    return rows


def bucket_for(delta: int) -> str:
    if delta == 0:
        return "0"
    if delta <= 2:
        return "1_TO_2"
    if delta <= 4:
        return "3_TO_4"
    if delta <= 9:
        return "5_TO_9"
    return "10_PLUS"


def distribution_rows(metrics: list[dict[str, object]]) -> list[dict[str, str]]:
    order = ["0", "1_TO_2", "3_TO_4", "5_TO_9", "10_PLUS"]
    grouped: dict[str, list[dict[str, object]]] = {bucket: [] for bucket in order}
    for item in metrics:
        grouped[bucket_for(int(item["absolute_rank_delta"]))].append(item)
    rows = []
    for bucket in order:
        items = grouped[bucket]
        rows.append({
            "rank_delta_bucket": bucket,
            "ticker_count": str(len(items)),
            "baseline_top20_count": str(sum(1 for item in items if item["baseline_top20"])),
            "bound_shadow_top20_count": str(sum(1 for item in items if item["shadow_top20"])),
            "max_absolute_rank_delta_in_bucket": str(max([int(item["absolute_rank_delta"]) for item in items], default=0)),
            "outlier_bucket_flag": tf(bucket in {"5_TO_9", "10_PLUS"}),
            **COMMON,
        })
    return rows


def attribution_rows(metrics: list[dict[str, object]], outliers: list[dict[str, str]]) -> tuple[list[dict[str, str]], float]:
    outlier_drivers = Counter(row["likely_factor_driver"] for row in outliers)
    total_outliers = len(outliers)
    concentration = max(outlier_drivers.values(), default=0) / total_outliers if total_outliers else 0.0
    drivers = sorted({str(item["driver"]) for item in metrics} | set(outlier_drivers))
    rows = []
    for driver in drivers:
        impacted = [item for item in metrics if item["driver"] == driver and int(item["absolute_rank_delta"]) > 0]
        driver_outliers = [row for row in outliers if row["likely_factor_driver"] == driver]
        deltas = [int(item["absolute_rank_delta"]) for item in impacted]
        rows.append({
            "factor_driver": driver,
            "impacted_ticker_count": str(len(impacted)),
            "outlier_ticker_count": str(len(driver_outliers)),
            "max_absolute_rank_delta": str(max(deltas, default=0)),
            "average_absolute_rank_delta": fmt(mean(deltas) if deltas else 0.0),
            "factor_impact_concentration": fmt((len(driver_outliers) / total_outliers) if total_outliers else 0.0),
            "concentration_warning_flag": tf(total_outliers > 0 and len(driver_outliers) / total_outliers >= CONCENTRATION_WARN_THRESHOLD),
            "score_adjustment_cap_required": tf(bool(driver_outliers)),
            **COMMON,
        })
    return rows, concentration


def build_review(
    runs: list[dict[str, str]],
    summary: dict[str, str],
    metrics: list[dict[str, object]],
    outliers: list[dict[str, str]],
    concentration: float,
) -> dict[str, str]:
    run_medians = [num(row.get("median_absolute_rank_delta")) for row in runs]
    top20_internal_churn = sum(
        1 for item in metrics
        if bool(item["baseline_top20"]) and bool(item["shadow_top20"]) and int(item["absolute_rank_delta"]) > 0
    )
    non_top20_churn = sum(
        1 for item in metrics
        if not (bool(item["baseline_top20"]) and bool(item["shadow_top20"])) and int(item["absolute_rank_delta"]) > 0
    )
    elevated = bool(outliers) or num(summary.get("max_rank_delta_across_runs")) >= OUTLIER_DELTA_THRESHOLD
    top20_stable = num(summary.get("max_top20_turnover_rate")) == 0.0
    cap_required = elevated
    concentrated = concentration >= CONCENTRATION_WARN_THRESHOLD and bool(outliers)
    action = "REVIEW_FACTOR_CONCENTRATION_AND_APPLY_SCORE_ADJUSTMENT_CAP_BEFORE_ANY_SHADOW_EXPANSION"
    if cap_required and not concentrated:
        action = "CONTINUE_BOUND_SHADOW_RESEARCH_ONLY_WITH_SCORE_ADJUSTMENT_CAP_REVIEW"
    if not cap_required:
        action = "CONTINUE_BOUND_SHADOW_RESEARCH_ONLY_TO_V20_163"
    return {
        "review_id": "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW_001",
        "observation_run_count": clean(summary.get("observation_run_count")),
        "average_top20_turnover_rate": clean(summary.get("average_top20_turnover_rate")),
        "max_top20_turnover_rate": clean(summary.get("max_top20_turnover_rate")),
        "average_rank_delta_across_runs": clean(summary.get("average_rank_delta_across_runs")),
        "max_rank_delta_across_runs": clean(summary.get("max_rank_delta_across_runs")),
        "median_rank_delta_across_runs": fmt(median(run_medians) if run_medians else 0.0),
        "elevated_rank_impact_confirmed": tf(elevated),
        "top20_membership_stable": tf(top20_stable),
        "internal_rank_churn_detected": tf(top20_internal_churn > 0),
        "outlier_ticker_count": str(len(outliers)),
        "top20_internal_churn_count": str(top20_internal_churn),
        "non_top20_churn_count": str(non_top20_churn),
        "factor_impact_concentration": fmt(concentration),
        "score_adjustment_cap_required": tf(cap_required),
        "rank_movement_cap_required": tf(cap_required),
        "continued_shadow_research_allowed": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def cap_rows(review: dict[str, str]) -> list[dict[str, str]]:
    cap_required = truthy(review["score_adjustment_cap_required"])
    return [{
        "cap_recommendation_id": "V20_162_BOUND_SHADOW_CAP_RECOMMENDATION_001",
        "score_adjustment_cap_required": tf(cap_required),
        "rank_movement_cap_required": tf(cap_required),
        "recommended_score_cap_scope": "BOUND_SHADOW_RESEARCH_ONLY_OUTLIER_TICKERS_AND_CONCENTRATED_FACTOR_DRIVERS" if cap_required else "NONE",
        "recommended_rank_movement_cap": str(OUTLIER_DELTA_THRESHOLD - 1) if cap_required else "NONE",
        "cap_reason": "ELEVATED_RANK_IMPACT_REMAINS_WITH_STABLE_TOP20_MEMBERSHIP" if cap_required else "NO_ELEVATED_RANK_IMPACT_CONFIRMED",
        "creates_official_recommendation": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
        "continued_shadow_research_allowed": "TRUE",
        "recommended_next_action": review["recommended_next_action"],
        **COMMON,
    }]


def write_report(status: str, review: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.162 Bound Shadow Elevated Rank Impact Review Report",
        "",
        f"- wrapper_status: {status}",
        f"- shadow_review_scope: {SCOPE}",
        "- formal_activation_allowed: FALSE",
        "- shadow_weight_expansion_allowed: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if review:
        lines.extend([
            f"- observation_run_count: {review['observation_run_count']}",
            f"- average_top20_turnover_rate: {review['average_top20_turnover_rate']}",
            f"- max_rank_delta_across_runs: {review['max_rank_delta_across_runs']}",
            f"- outlier_ticker_count: {review['outlier_ticker_count']}",
            f"- factor_impact_concentration: {review['factor_impact_concentration']}",
            f"- score_adjustment_cap_required: {review['score_adjustment_cap_required']}",
            f"- recommended_next_action: {review['recommended_next_action']}",
        ])
    lines.extend([
        "",
        "This review consumes existing V20.161 and V20.158-R2 research-only artifacts only.",
        "It does not create official recommendations, mutate official rankings or weights, or claim performance.",
    ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_162_BOUND_SHADOW_NEXT_GATE_001",
        "v20_161_gate_consumed": "FALSE",
        "v20_161_status": "",
        "v20_158_r2_gate_consumed": "FALSE",
        "v20_158_r2_status": "",
        "stable_enough_for_shadow_continuation": "FALSE",
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
        "elevated_rank_impact_confirmed": "FALSE",
        "top20_membership_stable": "FALSE",
        "internal_rank_churn_detected": "FALSE",
        "outlier_ticker_count": "0",
        "factor_impact_concentration": fmt(0.0),
        "score_adjustment_cap_required": "FALSE",
        "rank_movement_cap_required": "FALSE",
        "continued_shadow_research_allowed": "FALSE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "v20_163_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_REVIEW, REVIEW_FIELDS, [])
    write_csv(OUT_DISTRIBUTION, DIST_FIELDS, [])
    write_csv(OUT_OUTLIERS, OUTLIER_FIELDS, [])
    write_csv(OUT_ATTRIBUTION, ATTRIBUTION_FIELDS, [])
    write_csv(OUT_CAP, CAP_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    before = input_hashes()
    missing = [path for path in inputs() if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    runs, _ = read_csv(V161_RUNS)
    summary_rows, _ = read_csv(V161_SUMMARY)
    gate_rows, _ = read_csv(V161_GATE)
    sim_rows, _ = read_csv(V158_R2_SIM)
    delta_rows, _ = read_csv(V158_R2_DELTA)
    r2_gate_rows, _ = read_csv(V158_R2_GATE)
    if not all([runs, summary_rows, gate_rows, sim_rows, delta_rows, r2_gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    summary = summary_rows[0]
    gate = gate_rows[0]
    r2_gate = r2_gate_rows[0]
    prereq_ok = all([
        gate.get("final_status") in {PASS_V161, PARTIAL_V161},
        summary.get("stable_enough_for_shadow_continuation") == "TRUE",
        summary.get("stable_enough_for_shadow_expansion") == "FALSE",
        summary.get("stable_enough_for_official_weight_change") == "FALSE",
        gate.get("official_weight_change_allowed") == "FALSE",
        gate.get("shadow_weight_expansion_allowed") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_161_REQUIREMENTS_NOT_MET")

    metrics = ticker_metrics(sim_rows)
    outliers = outlier_rows(metrics)
    distribution = distribution_rows(metrics)
    attribution, concentration = attribution_rows(metrics, outliers)
    review = build_review(runs, summary, metrics, outliers, concentration)
    caps = cap_rows(review)

    upstream_mutated = before != input_hashes()
    if upstream_mutated:
        status = BLOCKED_STATUS
        blocking = "UPSTREAM_OUTPUT_MUTATION_DETECTED"
    elif truthy(review["score_adjustment_cap_required"]) and concentration >= CONCENTRATION_WARN_THRESHOLD and outliers:
        status = WARN_STATUS
        blocking = ""
    elif truthy(review["score_adjustment_cap_required"]):
        status = PARTIAL_STATUS
        blocking = ""
    else:
        status = PASS_STATUS
        blocking = ""

    gate_out = {
        "gate_check_id": "V20_162_BOUND_SHADOW_NEXT_GATE_001",
        "v20_161_gate_consumed": "TRUE",
        "v20_161_status": gate.get("final_status", ""),
        "v20_158_r2_gate_consumed": "TRUE",
        "v20_158_r2_status": r2_gate.get("final_status", ""),
        "stable_enough_for_shadow_continuation": "TRUE",
        "stable_enough_for_shadow_expansion": "FALSE",
        "stable_enough_for_official_weight_change": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
        "elevated_rank_impact_confirmed": review["elevated_rank_impact_confirmed"],
        "top20_membership_stable": review["top20_membership_stable"],
        "internal_rank_churn_detected": review["internal_rank_churn_detected"],
        "outlier_ticker_count": review["outlier_ticker_count"],
        "factor_impact_concentration": review["factor_impact_concentration"],
        "score_adjustment_cap_required": review["score_adjustment_cap_required"],
        "rank_movement_cap_required": review["rank_movement_cap_required"],
        "continued_shadow_research_allowed": "TRUE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_official_ranking_mutated": "TRUE",
        "no_official_weights_mutated": "TRUE",
        "no_official_recommendation_created": "TRUE",
        "no_real_book_action_created": "TRUE",
        "no_trade_action_created": "TRUE",
        "no_broker_action_created": "TRUE",
        "no_outcomes_fabricated": "TRUE",
        "no_benchmarks_fabricated": "TRUE",
        "no_performance_claim_created": "TRUE",
        "no_upstream_outputs_mutated": tf(not upstream_mutated),
        "v20_163_allowed": tf(status in {PASS_STATUS, PARTIAL_STATUS, WARN_STATUS}),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_REVIEW, REVIEW_FIELDS, [review])
    write_csv(OUT_DISTRIBUTION, DIST_FIELDS, distribution)
    write_csv(OUT_OUTLIERS, OUTLIER_FIELDS, outliers)
    write_csv(OUT_ATTRIBUTION, ATTRIBUTION_FIELDS, attribution)
    write_csv(OUT_CAP, CAP_FIELDS, caps)
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_report(status, review)

    print(status)
    print("V20_161_GATE_CONSUMED=TRUE")
    print(f"V20_161_STATUS={gate.get('final_status', '')}")
    print("V20_158_R2_GATE_CONSUMED=TRUE")
    print(f"V20_158_R2_STATUS={r2_gate.get('final_status', '')}")
    print("STABLE_ENOUGH_FOR_SHADOW_CONTINUATION=TRUE")
    print("STABLE_ENOUGH_FOR_SHADOW_EXPANSION=FALSE")
    print("STABLE_ENOUGH_FOR_OFFICIAL_WEIGHT_CHANGE=FALSE")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print(f"OBSERVATION_RUN_COUNT={review['observation_run_count']}")
    print(f"AVERAGE_TOP20_TURNOVER_RATE={review['average_top20_turnover_rate']}")
    print(f"MAX_TOP20_TURNOVER_RATE={review['max_top20_turnover_rate']}")
    print(f"AVERAGE_RANK_DELTA_ACROSS_RUNS={review['average_rank_delta_across_runs']}")
    print(f"MAX_RANK_DELTA_ACROSS_RUNS={review['max_rank_delta_across_runs']}")
    print(f"MEDIAN_RANK_DELTA_ACROSS_RUNS={review['median_rank_delta_across_runs']}")
    print(f"ELEVATED_RANK_IMPACT_CONFIRMED={review['elevated_rank_impact_confirmed']}")
    print(f"TOP20_MEMBERSHIP_STABLE={review['top20_membership_stable']}")
    print(f"INTERNAL_RANK_CHURN_DETECTED={review['internal_rank_churn_detected']}")
    print(f"OUTLIER_TICKER_COUNT={review['outlier_ticker_count']}")
    print(f"FACTOR_IMPACT_CONCENTRATION={review['factor_impact_concentration']}")
    print(f"SCORE_ADJUSTMENT_CAP_REQUIRED={review['score_adjustment_cap_required']}")
    print(f"RANK_MOVEMENT_CAP_REQUIRED={review['rank_movement_cap_required']}")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print("OFFICIAL_RANKING_MUTATED=FALSE")
    print("OFFICIAL_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_ACTION_CREATED=FALSE")
    print("OUTCOMES_FABRICATED=0")
    print("BENCHMARKS_FABRICATED=0")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    print(f"V20_163_ALLOWED={gate_out['v20_163_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
