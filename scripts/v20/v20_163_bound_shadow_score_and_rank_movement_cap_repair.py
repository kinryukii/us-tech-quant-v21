#!/usr/bin/env python
"""V20.163 bound shadow score and rank movement cap repair.

Builds a research-only capped bound shadow simulation from V20.162 review
outputs and V20.158-R2 bound shadow simulation outputs. The cap repair only
reduces score adjustment magnitude and rank movement. It does not create new
proposal rows, expand factor scope, mutate official rankings or weights, create
recommendations, create actions, fabricate outcomes, or claim performance.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V162_REVIEW = FACTORS / "V20_162_BOUND_SHADOW_ELEVATED_RANK_IMPACT_REVIEW.csv"
V162_DISTRIBUTION = FACTORS / "V20_162_BOUND_SHADOW_RANK_DELTA_DISTRIBUTION.csv"
V162_OUTLIERS = FACTORS / "V20_162_BOUND_SHADOW_OUTLIER_TICKER_AUDIT.csv"
V162_ATTRIBUTION = FACTORS / "V20_162_BOUND_SHADOW_FACTOR_IMPACT_ATTRIBUTION.csv"
V162_CAP = FACTORS / "V20_162_BOUND_SHADOW_CAP_RECOMMENDATION.csv"
V162_GATE = FACTORS / "V20_162_BOUND_SHADOW_NEXT_GATE.csv"

V158_R2_SIM = FACTORS / "V20_158_R2_BOUND_REDUCED_SHADOW_RANKING_SIMULATION.csv"
V158_R2_DELTA = FACTORS / "V20_158_R2_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
V158_R2_GATE = FACTORS / "V20_158_R2_RANK_IMPACT_RETEST_GATE.csv"

OUT_REPAIR = FACTORS / "V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR.csv"
OUT_SIM = FACTORS / "V20_163_CAPPED_BOUND_SHADOW_RANKING_SIMULATION.csv"
OUT_DELTA = FACTORS / "V20_163_CAPPED_BOUND_SHADOW_VS_BASELINE_RANK_DELTA.csv"
OUT_SCORE_AUDIT = FACTORS / "V20_163_SCORE_ADJUSTMENT_CAP_AUDIT.csv"
OUT_RANK_AUDIT = FACTORS / "V20_163_RANK_MOVEMENT_CAP_AUDIT.csv"
OUT_OUTLIER_AUDIT = FACTORS / "V20_163_OUTLIER_CAP_REPAIR_AUDIT.csv"
OUT_GATE = FACTORS / "V20_163_CAPPED_SHADOW_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_163_BOUND_SHADOW_SCORE_AND_RANK_MOVEMENT_CAP_REPAIR_REPORT.md"

REQUIRED_V162_STATUS = "WARN_V20_162_BOUND_SHADOW_RANK_IMPACT_TOO_CONCENTRATED"
PASS_STATUS = "PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_READY_FOR_V20_164"
PARTIAL_STATUS = "PARTIAL_PASS_V20_163_BOUND_SHADOW_CAP_REPAIR_WITH_REMAINING_ELEVATED_IMPACT_READY_FOR_V20_164"
WARN_STATUS = "WARN_V20_163_BOUND_SHADOW_CAP_REPAIR_INSUFFICIENT"
BLOCKED_STATUS = "BLOCKED_V20_163_BOUND_SHADOW_SCORE_RANK_CAP_REPAIR"
SCOPE = "RESEARCH_ONLY_LIMITED_CONSERVATIVE_BOUND_TO_AUTHORITATIVE_BASELINE_WITH_CAPS"

DEFAULT_RANK_CAP = 4
HIGH_RANK_DELTA_THRESHOLD = 5

SAFETY = {
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "capped_bound_shadow_simulation_created": "TRUE",
    "shadow_repair_scope": SCOPE,
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
    "staging_repair_only": "TRUE",
    "cap_repair_only": "TRUE",
    "audit_only": "TRUE",
}

REPAIR_FIELDS = [
    "ticker",
    "baseline_rank",
    "uncapped_bound_shadow_rank",
    "capped_bound_shadow_rank",
    "uncapped_absolute_rank_delta",
    "capped_absolute_rank_delta",
    "baseline_score",
    "uncapped_bound_shadow_score",
    "capped_bound_shadow_score",
    "uncapped_score_delta",
    "capped_score_delta",
    "score_adjustment_cap_applied",
    "rank_movement_cap_applied",
    "outlier_cap_applied",
    "likely_factor_driver",
    "factor_impact_concentration_before",
    "factor_impact_concentration_after",
    "baseline_top20_flag",
    "capped_shadow_top20_flag",
    "official_ranking_mutated",
    "official_weight_change_created",
    *COMMON.keys(),
]
SIM_FIELDS = [
    *REPAIR_FIELDS,
    "source_uncapped_artifact",
    "score_adjustment_not_increased",
    "rank_movement_not_increased",
    "top20_membership_preserved",
]
DELTA_FIELDS = [
    "summary_id",
    "baseline_candidate_count",
    "capped_shadow_candidate_count",
    "top20_overlap_count",
    "entered_top20_count",
    "exited_top20_count",
    "capped_top20_turnover_rate",
    "uncapped_max_absolute_rank_delta",
    "capped_max_absolute_rank_delta",
    "uncapped_average_absolute_rank_delta",
    "capped_average_absolute_rank_delta",
    "outlier_ticker_count_before",
    "outlier_ticker_count_after",
    "factor_impact_concentration_before",
    "factor_impact_concentration_after",
    "cap_repair_success",
    "remaining_rank_impact_severity",
    "recommended_next_action",
    *COMMON.keys(),
]
SCORE_AUDIT_FIELDS = [
    "ticker",
    "uncapped_score_delta",
    "capped_score_delta",
    "score_delta_magnitude_reduced_or_equal",
    "score_adjustment_cap_applied",
    "score_adjustment_increased",
    *COMMON.keys(),
]
RANK_AUDIT_FIELDS = [
    "ticker",
    "baseline_rank",
    "uncapped_bound_shadow_rank",
    "capped_bound_shadow_rank",
    "uncapped_absolute_rank_delta",
    "capped_absolute_rank_delta",
    "rank_movement_cap_limit",
    "rank_movement_cap_applied",
    "rank_movement_increased",
    "top20_membership_preserved",
    *COMMON.keys(),
]
OUTLIER_AUDIT_FIELDS = [
    "ticker",
    "outlier_before_flag",
    "outlier_after_flag",
    "outlier_cap_applied",
    "likely_factor_driver",
    "cap_repair_result",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id",
    "v20_162_gate_consumed",
    "v20_162_status",
    "v20_158_r2_gate_consumed",
    "v20_158_r2_status",
    "top20_membership_stable",
    "elevated_rank_impact_confirmed",
    "score_adjustment_cap_required",
    "rank_movement_cap_required",
    "shadow_weight_expansion_allowed",
    "official_weight_change_allowed",
    "baseline_candidate_count",
    "capped_shadow_candidate_count",
    "capped_top20_turnover_rate",
    "uncapped_max_absolute_rank_delta",
    "capped_max_absolute_rank_delta",
    "outlier_ticker_count_before",
    "outlier_ticker_count_after",
    "factor_impact_concentration_before",
    "factor_impact_concentration_after",
    "cap_repair_success",
    "remaining_rank_impact_severity",
    "continued_shadow_research_allowed",
    "no_new_shadow_proposal_rows_created",
    "no_factor_scope_expansion",
    "no_score_adjustment_increased",
    "no_rank_movement_increased",
    "top20_membership_preserved",
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
    "v20_164_allowed",
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
        V162_REVIEW, V162_DISTRIBUTION, V162_OUTLIERS, V162_ATTRIBUTION, V162_CAP, V162_GATE,
        V158_R2_SIM, V158_R2_DELTA, V158_R2_GATE,
    ]


def input_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in inputs() if path.exists()}


def rank_cap_from_cap_row(cap_row: dict[str, str]) -> int:
    value = clean(cap_row.get("recommended_rank_movement_cap"))
    if value.upper() == "NONE" or not value:
        return DEFAULT_RANK_CAP
    return max(0, intish(value, DEFAULT_RANK_CAP))


def factor_driver(row: dict[str, str], outlier_driver_by_ticker: dict[str, str]) -> str:
    ticker = clean(row.get("ticker"))
    if ticker in outlier_driver_by_ticker:
        return outlier_driver_by_ticker[ticker]
    driver = clean(row.get("affected_factor_family"))
    return driver if driver else "UNKNOWN_FACTOR_DRIVER"


def capped_rank(baseline_rank: int, uncapped_rank: int, cap: int) -> int:
    movement = uncapped_rank - baseline_rank
    if abs(movement) <= cap:
        return uncapped_rank
    direction = -1 if movement < 0 else 1
    return baseline_rank + direction * cap


def capped_score_delta(uncapped_score_delta: float, uncapped_abs_delta: int, cap: int) -> tuple[float, bool]:
    if uncapped_abs_delta <= cap or uncapped_abs_delta <= 0:
        return uncapped_score_delta, False
    scale = cap / uncapped_abs_delta
    return uncapped_score_delta * scale, True


def concentration(rows: list[dict[str, str]], flag_field: str, driver_field: str) -> float:
    flagged = [row for row in rows if truthy(row.get(flag_field))]
    if not flagged:
        return 0.0
    counts = Counter(clean(row.get(driver_field)) for row in flagged)
    return max(counts.values(), default=0) / len(flagged)


def build_rows(
    sim_rows: list[dict[str, str]],
    outlier_rows: list[dict[str, str]],
    cap_limit: int,
    concentration_before: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], float]:
    outlier_driver_by_ticker = {clean(row.get("ticker")): clean(row.get("likely_factor_driver")) for row in outlier_rows}
    repair_rows: list[dict[str, str]] = []
    score_audit: list[dict[str, str]] = []
    rank_audit: list[dict[str, str]] = []
    outlier_audit: list[dict[str, str]] = []

    for source in sim_rows:
        ticker = clean(source.get("ticker"))
        baseline_rank = intish(source.get("authoritative_baseline_rank"))
        uncapped_rank = intish(source.get("bound_reduced_shadow_rank"))
        uncapped_abs = abs(intish(source.get("bound_reduced_rank_delta"), uncapped_rank - baseline_rank))
        capped_shadow_rank = capped_rank(baseline_rank, uncapped_rank, cap_limit)
        capped_abs = abs(capped_shadow_rank - baseline_rank)
        baseline_score = num(source.get("authoritative_baseline_score"))
        uncapped_score = num(source.get("bound_reduced_shadow_score"))
        uncapped_delta = num(source.get("bound_reduced_score_delta"))
        capped_delta, score_cap_applied = capped_score_delta(uncapped_delta, uncapped_abs, cap_limit)
        capped_score = uncapped_score - uncapped_delta + capped_delta
        rank_cap_applied = capped_abs < uncapped_abs
        outlier_before = uncapped_abs >= HIGH_RANK_DELTA_THRESHOLD
        outlier_after = capped_abs >= HIGH_RANK_DELTA_THRESHOLD
        driver = factor_driver(source, outlier_driver_by_ticker)
        baseline_top20 = 0 < baseline_rank <= 20
        capped_top20 = 0 < capped_shadow_rank <= 20
        row = {
            "ticker": ticker,
            "baseline_rank": str(baseline_rank),
            "uncapped_bound_shadow_rank": str(uncapped_rank),
            "capped_bound_shadow_rank": str(capped_shadow_rank),
            "uncapped_absolute_rank_delta": str(uncapped_abs),
            "capped_absolute_rank_delta": str(capped_abs),
            "baseline_score": fmt(baseline_score),
            "uncapped_bound_shadow_score": fmt(uncapped_score),
            "capped_bound_shadow_score": fmt(capped_score),
            "uncapped_score_delta": fmt(uncapped_delta),
            "capped_score_delta": fmt(capped_delta),
            "score_adjustment_cap_applied": tf(score_cap_applied),
            "rank_movement_cap_applied": tf(rank_cap_applied),
            "outlier_cap_applied": tf(outlier_before and not outlier_after),
            "likely_factor_driver": driver,
            "factor_impact_concentration_before": fmt(concentration_before),
            "factor_impact_concentration_after": "",
            "baseline_top20_flag": tf(baseline_top20),
            "capped_shadow_top20_flag": tf(capped_top20),
            "official_ranking_mutated": "FALSE",
            "official_weight_change_created": "FALSE",
            **COMMON,
        }
        repair_rows.append(row)
        score_audit.append({
            "ticker": ticker,
            "uncapped_score_delta": row["uncapped_score_delta"],
            "capped_score_delta": row["capped_score_delta"],
            "score_delta_magnitude_reduced_or_equal": tf(abs(capped_delta) <= abs(uncapped_delta) + 1e-12),
            "score_adjustment_cap_applied": tf(score_cap_applied),
            "score_adjustment_increased": tf(abs(capped_delta) > abs(uncapped_delta) + 1e-12),
            **COMMON,
        })
        rank_audit.append({
            "ticker": ticker,
            "baseline_rank": str(baseline_rank),
            "uncapped_bound_shadow_rank": str(uncapped_rank),
            "capped_bound_shadow_rank": str(capped_shadow_rank),
            "uncapped_absolute_rank_delta": str(uncapped_abs),
            "capped_absolute_rank_delta": str(capped_abs),
            "rank_movement_cap_limit": str(cap_limit),
            "rank_movement_cap_applied": tf(rank_cap_applied),
            "rank_movement_increased": tf(capped_abs > uncapped_abs),
            "top20_membership_preserved": tf(baseline_top20 == capped_top20),
            **COMMON,
        })
        outlier_audit.append({
            "ticker": ticker,
            "outlier_before_flag": tf(outlier_before),
            "outlier_after_flag": tf(outlier_after),
            "outlier_cap_applied": tf(outlier_before and not outlier_after),
            "likely_factor_driver": driver,
            "cap_repair_result": "OUTLIER_REPAIRED" if outlier_before and not outlier_after else ("REMAINING_OUTLIER" if outlier_after else "NOT_OUTLIER"),
            **COMMON,
        })

    concentration_after = concentration(outlier_audit, "outlier_after_flag", "likely_factor_driver")
    for row in repair_rows:
        row["factor_impact_concentration_after"] = fmt(concentration_after)
    sim = [{**row, "source_uncapped_artifact": rel(V158_R2_SIM), "score_adjustment_not_increased": "TRUE", "rank_movement_not_increased": "TRUE", "top20_membership_preserved": tf(row["baseline_top20_flag"] == row["capped_shadow_top20_flag"])} for row in repair_rows]
    return repair_rows, sim, score_audit, rank_audit, outlier_audit, concentration_after


def build_summary(
    repair_rows: list[dict[str, str]],
    outlier_audit: list[dict[str, str]],
    concentration_before: float,
    concentration_after: float,
) -> dict[str, str]:
    baseline_top20 = {row["ticker"] for row in repair_rows if row["baseline_top20_flag"] == "TRUE"}
    capped_top20 = {row["ticker"] for row in repair_rows if row["capped_shadow_top20_flag"] == "TRUE"}
    overlap = len(baseline_top20 & capped_top20)
    entered = len(capped_top20 - baseline_top20)
    exited = len(baseline_top20 - capped_top20)
    turnover = (entered + exited) / max(len(baseline_top20), 1)
    uncapped_deltas = [intish(row["uncapped_absolute_rank_delta"]) for row in repair_rows]
    capped_deltas = [intish(row["capped_absolute_rank_delta"]) for row in repair_rows]
    outlier_before = sum(1 for row in outlier_audit if row["outlier_before_flag"] == "TRUE")
    outlier_after = sum(1 for row in outlier_audit if row["outlier_after_flag"] == "TRUE")
    capped_max = max(capped_deltas, default=0)
    cap_success = turnover == 0 and capped_max < HIGH_RANK_DELTA_THRESHOLD and outlier_after == 0
    if turnover > 0:
        severity = "UNSTABLE_TOP20_MEMBERSHIP_CHANGED"
        action = "BLOCK_OR_REPAIR_TOP20_MEMBERSHIP_BEFORE_CONTINUATION"
    elif capped_max >= HIGH_RANK_DELTA_THRESHOLD:
        severity = "ELEVATED_CAPPED_RANK_IMPACT_REMAINS"
        action = "REQUIRE_ANOTHER_CAP_REVIEW"
    elif concentration_after >= 1.0 and outlier_after > 0:
        severity = "CONCENTRATED_FACTOR_IMPACT_REMAINS"
        action = "REQUIRE_FACTOR_IMPACT_NORMALIZATION_REVIEW"
    else:
        severity = "CAPPED_RANK_IMPACT_REPAIRED_RESEARCH_ONLY"
        action = "CONTINUE_BOUND_SHADOW_RESEARCH_ONLY_TO_V20_164_WITH_CAPS"
    return {
        "summary_id": "V20_163_CAPPED_BOUND_SHADOW_VS_BASELINE_RANK_DELTA_001",
        "baseline_candidate_count": str(len(repair_rows)),
        "capped_shadow_candidate_count": str(len(repair_rows)),
        "top20_overlap_count": str(overlap),
        "entered_top20_count": str(entered),
        "exited_top20_count": str(exited),
        "capped_top20_turnover_rate": fmt(turnover),
        "uncapped_max_absolute_rank_delta": str(max(uncapped_deltas, default=0)),
        "capped_max_absolute_rank_delta": str(capped_max),
        "uncapped_average_absolute_rank_delta": fmt(mean(uncapped_deltas) if uncapped_deltas else 0.0),
        "capped_average_absolute_rank_delta": fmt(mean(capped_deltas) if capped_deltas else 0.0),
        "outlier_ticker_count_before": str(outlier_before),
        "outlier_ticker_count_after": str(outlier_after),
        "factor_impact_concentration_before": fmt(concentration_before),
        "factor_impact_concentration_after": fmt(concentration_after),
        "cap_repair_success": tf(cap_success),
        "remaining_rank_impact_severity": severity,
        "recommended_next_action": action,
        **COMMON,
    }


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.163 Bound Shadow Score And Rank Movement Cap Repair Report",
        "",
        f"- wrapper_status: {status}",
        f"- shadow_repair_scope: {SCOPE}",
        "- formal_activation_allowed: FALSE",
        "- shadow_weight_expansion_allowed: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- performance_claim_created: FALSE",
    ]
    if summary:
        lines.extend([
            f"- baseline_candidate_count: {summary['baseline_candidate_count']}",
            f"- capped_top20_turnover_rate: {summary['capped_top20_turnover_rate']}",
            f"- uncapped_max_absolute_rank_delta: {summary['uncapped_max_absolute_rank_delta']}",
            f"- capped_max_absolute_rank_delta: {summary['capped_max_absolute_rank_delta']}",
            f"- outlier_ticker_count_before: {summary['outlier_ticker_count_before']}",
            f"- outlier_ticker_count_after: {summary['outlier_ticker_count_after']}",
            f"- factor_impact_concentration_before: {summary['factor_impact_concentration_before']}",
            f"- factor_impact_concentration_after: {summary['factor_impact_concentration_after']}",
            f"- cap_repair_success: {summary['cap_repair_success']}",
            f"- recommended_next_action: {summary['recommended_next_action']}",
        ])
    lines.extend([
        "",
        "The capped simulation is research-only and reduces existing score adjustment and rank movement only.",
        "It does not mutate official rankings or weights and does not create recommendations or actions.",
    ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    gate = {
        "gate_check_id": "V20_163_CAPPED_SHADOW_NEXT_GATE_001",
        "v20_162_gate_consumed": "FALSE",
        "v20_162_status": "",
        "v20_158_r2_gate_consumed": "FALSE",
        "v20_158_r2_status": "",
        "top20_membership_stable": "FALSE",
        "elevated_rank_impact_confirmed": "FALSE",
        "score_adjustment_cap_required": "FALSE",
        "rank_movement_cap_required": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "baseline_candidate_count": "0",
        "capped_shadow_candidate_count": "0",
        "capped_top20_turnover_rate": fmt(0.0),
        "uncapped_max_absolute_rank_delta": "0",
        "capped_max_absolute_rank_delta": "0",
        "outlier_ticker_count_before": "0",
        "outlier_ticker_count_after": "0",
        "factor_impact_concentration_before": fmt(0.0),
        "factor_impact_concentration_after": fmt(0.0),
        "cap_repair_success": "FALSE",
        "remaining_rank_impact_severity": "BLOCKED",
        "continued_shadow_research_allowed": "FALSE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_score_adjustment_increased": "TRUE",
        "no_rank_movement_increased": "TRUE",
        "top20_membership_preserved": "TRUE",
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
        "v20_164_allowed": "FALSE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_REPAIR, REPAIR_FIELDS, [])
    write_csv(OUT_SIM, SIM_FIELDS, [])
    write_csv(OUT_DELTA, DELTA_FIELDS, [])
    write_csv(OUT_SCORE_AUDIT, SCORE_AUDIT_FIELDS, [])
    write_csv(OUT_RANK_AUDIT, RANK_AUDIT_FIELDS, [])
    write_csv(OUT_OUTLIER_AUDIT, OUTLIER_AUDIT_FIELDS, [])
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

    review_rows, _ = read_csv(V162_REVIEW)
    outlier_rows, _ = read_csv(V162_OUTLIERS)
    attr_rows, _ = read_csv(V162_ATTRIBUTION)
    cap_rows, _ = read_csv(V162_CAP)
    gate_rows, _ = read_csv(V162_GATE)
    sim_rows, _ = read_csv(V158_R2_SIM)
    r2_delta_rows, _ = read_csv(V158_R2_DELTA)
    r2_gate_rows, _ = read_csv(V158_R2_GATE)
    if not all([review_rows, outlier_rows, attr_rows, cap_rows, gate_rows, sim_rows, r2_delta_rows, r2_gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    review = review_rows[0]
    cap = cap_rows[0]
    gate = gate_rows[0]
    r2_gate = r2_gate_rows[0]
    prereq_ok = all([
        gate.get("final_status") == REQUIRED_V162_STATUS,
        review.get("top20_membership_stable") == "TRUE",
        review.get("elevated_rank_impact_confirmed") == "TRUE",
        review.get("score_adjustment_cap_required") == "TRUE",
        review.get("rank_movement_cap_required") == "TRUE",
        review.get("shadow_weight_expansion_allowed") == "FALSE",
        review.get("official_weight_change_allowed") == "FALSE",
        gate.get("shadow_weight_expansion_allowed") == "FALSE",
        gate.get("official_weight_change_allowed") == "FALSE",
        cap.get("score_adjustment_cap_required") == "TRUE",
        cap.get("rank_movement_cap_required") == "TRUE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_162_REQUIREMENTS_NOT_MET")

    rank_cap = rank_cap_from_cap_row(cap)
    concentration_before = num(review.get("factor_impact_concentration"), num(gate.get("factor_impact_concentration"), 0.0))
    repair, sim, score_audit, rank_audit, outlier_audit, concentration_after = build_rows(
        sim_rows, outlier_rows, rank_cap, concentration_before
    )
    summary = build_summary(repair, outlier_audit, concentration_before, concentration_after)
    upstream_mutated = before != input_hashes()
    score_increased = any(row["score_adjustment_increased"] == "TRUE" for row in score_audit)
    rank_increased = any(row["rank_movement_increased"] == "TRUE" for row in rank_audit)
    top20_preserved = all(row["top20_membership_preserved"] == "TRUE" for row in rank_audit)

    if upstream_mutated or score_increased or rank_increased or not top20_preserved:
        status = BLOCKED_STATUS
        blocking = "SAFETY_OR_CAP_RULE_FAILURE"
    elif num(summary["capped_top20_turnover_rate"]) > 0:
        status = WARN_STATUS
        blocking = ""
    elif intish(summary["capped_max_absolute_rank_delta"]) >= HIGH_RANK_DELTA_THRESHOLD:
        status = WARN_STATUS
        blocking = ""
    elif num(summary["factor_impact_concentration_after"]) >= 1.0 and intish(summary["outlier_ticker_count_after"]) > 0:
        status = PARTIAL_STATUS
        blocking = ""
    elif summary["cap_repair_success"] == "TRUE":
        status = PASS_STATUS
        blocking = ""
    else:
        status = PARTIAL_STATUS
        blocking = ""

    gate_out = {
        "gate_check_id": "V20_163_CAPPED_SHADOW_NEXT_GATE_001",
        "v20_162_gate_consumed": "TRUE",
        "v20_162_status": gate.get("final_status", ""),
        "v20_158_r2_gate_consumed": "TRUE",
        "v20_158_r2_status": r2_gate.get("final_status", ""),
        "top20_membership_stable": "TRUE",
        "elevated_rank_impact_confirmed": "TRUE",
        "score_adjustment_cap_required": "TRUE",
        "rank_movement_cap_required": "TRUE",
        "shadow_weight_expansion_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "baseline_candidate_count": summary["baseline_candidate_count"],
        "capped_shadow_candidate_count": summary["capped_shadow_candidate_count"],
        "capped_top20_turnover_rate": summary["capped_top20_turnover_rate"],
        "uncapped_max_absolute_rank_delta": summary["uncapped_max_absolute_rank_delta"],
        "capped_max_absolute_rank_delta": summary["capped_max_absolute_rank_delta"],
        "outlier_ticker_count_before": summary["outlier_ticker_count_before"],
        "outlier_ticker_count_after": summary["outlier_ticker_count_after"],
        "factor_impact_concentration_before": summary["factor_impact_concentration_before"],
        "factor_impact_concentration_after": summary["factor_impact_concentration_after"],
        "cap_repair_success": summary["cap_repair_success"],
        "remaining_rank_impact_severity": summary["remaining_rank_impact_severity"],
        "continued_shadow_research_allowed": "TRUE",
        "no_new_shadow_proposal_rows_created": "TRUE",
        "no_factor_scope_expansion": "TRUE",
        "no_score_adjustment_increased": tf(not score_increased),
        "no_rank_movement_increased": tf(not rank_increased),
        "top20_membership_preserved": tf(top20_preserved),
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
        "v20_164_allowed": tf(status in {PASS_STATUS, PARTIAL_STATUS}),
        "blocking_reason": blocking,
        "final_status": status,
        **COMMON,
    }

    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair)
    write_csv(OUT_SIM, SIM_FIELDS, sim)
    write_csv(OUT_DELTA, DELTA_FIELDS, [summary])
    write_csv(OUT_SCORE_AUDIT, SCORE_AUDIT_FIELDS, score_audit)
    write_csv(OUT_RANK_AUDIT, RANK_AUDIT_FIELDS, rank_audit)
    write_csv(OUT_OUTLIER_AUDIT, OUTLIER_AUDIT_FIELDS, outlier_audit)
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_report(status, summary)

    print(status)
    print("V20_162_GATE_CONSUMED=TRUE")
    print(f"V20_162_STATUS={gate.get('final_status', '')}")
    print("V20_158_R2_GATE_CONSUMED=TRUE")
    print(f"V20_158_R2_STATUS={r2_gate.get('final_status', '')}")
    print("TOP20_MEMBERSHIP_STABLE=TRUE")
    print("ELEVATED_RANK_IMPACT_CONFIRMED=TRUE")
    print("SCORE_ADJUSTMENT_CAP_REQUIRED=TRUE")
    print("RANK_MOVEMENT_CAP_REQUIRED=TRUE")
    print("SHADOW_WEIGHT_EXPANSION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    for field in [
        "baseline_candidate_count",
        "capped_shadow_candidate_count",
        "top20_overlap_count",
        "entered_top20_count",
        "exited_top20_count",
        "capped_top20_turnover_rate",
        "uncapped_max_absolute_rank_delta",
        "capped_max_absolute_rank_delta",
        "uncapped_average_absolute_rank_delta",
        "capped_average_absolute_rank_delta",
        "outlier_ticker_count_before",
        "outlier_ticker_count_after",
        "factor_impact_concentration_before",
        "factor_impact_concentration_after",
        "cap_repair_success",
        "remaining_rank_impact_severity",
        "recommended_next_action",
    ]:
        print(f"{field.upper()}={summary[field]}")
    print(f"NO_SCORE_ADJUSTMENT_INCREASED={tf(not score_increased)}")
    print(f"NO_RANK_MOVEMENT_INCREASED={tf(not rank_increased)}")
    print(f"TOP20_MEMBERSHIP_PRESERVED={tf(top20_preserved)}")
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
    print(f"V20_164_ALLOWED={gate_out['v20_164_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
