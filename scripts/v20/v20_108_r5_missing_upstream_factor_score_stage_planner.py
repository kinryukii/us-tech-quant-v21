#!/usr/bin/env python
"""V20.108-R5 missing upstream factor score stage planner.

Plans the research-only upstream stages needed to complete candidate-level
factor-family score coverage before any real V20.108 shadow rerank. This stage
does not create scores, proxies, rankings, recommendations, trades, or weights.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R4_AUDIT = CONSOLIDATION / "V20_108_R4_FACTOR_FAMILY_SCORE_MATERIALIZATION_AUDIT.csv"
R4_COVERAGE = CONSOLIDATION / "V20_108_R4_CANDIDATE_CONTRIBUTION_COVERAGE_AFTER_MATERIALIZATION.csv"
R4_READINESS = CONSOLIDATION / "V20_108_R4_SHADOW_RERANK_READINESS_AFTER_MATERIALIZATION.csv"
R3_PLAN = CONSOLIDATION / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN.csv"
R3_BLOCKER = CONSOLIDATION / "V20_108_R3_MATERIALIZATION_BLOCKER_AUDIT.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
V50_BENCH = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
V98C_AUDIT = CONSOLIDATION / "V20_98C_RESEARCH_ONLY_ETF_ROTATION_REGIME_AUDIT.csv"
V106_FACTOR = CONSOLIDATION / "V20_106_REGIME_CONDITIONED_FACTOR_ALIGNMENT.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_STAGE_PLAN = CONSOLIDATION / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN.csv"
OUT_GAP_MAP = CONSOLIDATION / "V20_108_R5_FACTOR_FAMILY_GAP_TO_STAGE_MAP.csv"
OUT_SOURCE_REQ = CONSOLIDATION / "V20_108_R5_UPSTREAM_SOURCE_REQUIREMENT_AUDIT.csv"
OUT_RESOLUTION = CONSOLIDATION / "V20_108_R5_SHADOW_RERANK_BLOCKER_RESOLUTION_PLAN.csv"
REPORT = READ_CENTER / "V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLAN_REPORT.md"

STATUS = "PASS_V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
STAGE_BY_FAMILY = {
    "FUNDAMENTAL": "V20.108-R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE_BUILDER",
    "STRATEGY": "V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER",
    "MARKET_REGIME": "V20.108-R8_MARKET_REGIME_CANDIDATE_EXPOSURE_BUILDER",
    "RISK": "V20.108-R9_RISK_CANDIDATE_SCORE_COVERAGE_EXPANDER",
}
ASSEMBLER_STAGE = "V20.108-R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER"

STAGE_FIELDS = [
    "planned_stage", "target_factor_family", "current_coverage_status",
    "current_candidate_coverage_count", "required_candidate_count", "stage_goal",
    "required_input_artifacts", "required_source_columns", "planned_output_artifacts",
    "materialization_method", "proxy_allowed", "operator_approval_required",
    "required_before_shadow_rerank", "downstream_unblocked_stage",
    "safety_constraints", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

GAP_FIELDS = [
    "factor_family", "gap_type", "current_coverage_count", "required_coverage_count",
    "missing_candidate_count", "planned_repair_stage", "repair_priority",
    "blocker_status", "blocker_reason", "unsafe_action_forbidden", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

SOURCE_FIELDS = [
    "requirement_id", "planned_stage", "target_factor_family",
    "required_input_artifact", "artifact_exists", "artifact_non_empty",
    "required_columns", "source_requirement_status", "source_requirement_reason",
    "proxy_activation_allowed", "contribution_scores_created", "shadow_rerank_created",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

RESOLUTION_FIELDS = [
    "readiness_check_id", "complete_six_family_contribution_candidate_count",
    "usable_for_shadow_rerank_count", "current_shadow_rerank_status",
    "blocking_factor_families", "required_repair_stages",
    "minimum_condition_to_rerun_v20_108", "recommended_next_stage", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "official_promotion_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
    }
    if extra:
        row["is_official_ranking"] = "FALSE"
        row["is_official_weight"] = "FALSE"
    return row


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.exists():
        return [], "MISSING"
    if path.stat().st_size == 0:
        return [], "EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, "OK" if reader.fieldnames else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def requirement_rows(stage: str, family: str, artifacts: list[Path], columns: str) -> list[dict[str, str]]:
    rows = []
    for idx, artifact in enumerate(artifacts, start=1):
        rows.append({
            "requirement_id": f"{stage.replace('.', '_').replace('-', '_')}_REQ_{idx:03d}",
            "planned_stage": stage,
            "target_factor_family": family,
            "required_input_artifact": rel(artifact),
            "artifact_exists": tf(artifact.exists()),
            "artifact_non_empty": tf(artifact.exists() and artifact.stat().st_size > 0),
            "required_columns": columns,
            "source_requirement_status": "INPUT_AVAILABLE_FOR_PLANNING" if artifact.exists() and artifact.stat().st_size > 0 else "INPUT_MISSING_OR_EMPTY",
            "source_requirement_reason": "PLANNING_ONLY_NO_SCORE_CREATION",
            "proxy_activation_allowed": "FALSE",
            "contribution_scores_created": "FALSE",
            "shadow_rerank_created": "FALSE",
            **safety(extra=True),
        })
    return rows


def main() -> int:
    coverage_rows, _ = read_csv(R4_COVERAGE)
    readiness_rows, _ = read_csv(R4_READINESS)
    coverage = {row["factor_family"]: row for row in coverage_rows}
    readiness = readiness_rows[0] if readiness_rows else {}
    required_count = int(coverage_rows[0]["required_candidate_count"]) if coverage_rows else 0

    stage_rows: list[dict[str, str]] = []
    gap_rows: list[dict[str, str]] = []
    source_rows: list[dict[str, str]] = []

    for family in FAMILIES:
        row = coverage.get(family, {})
        current = int(row.get("materialized_candidate_count") or 0)
        missing = int(row.get("missing_candidate_count") or 0)
        status = row.get("contribution_coverage_status", "MISSING")
        if status == "COMPLETE":
            gap_type = "NO_GAP_ALREADY_MATERIALIZED"
            stage = "NONE_ALREADY_MATERIALIZED"
            priority = "NONE"
            blocker = "NOT_BLOCKING"
            reason = "Candidate-level contribution coverage is complete for this family."
        elif status == "PARTIAL":
            gap_type = "PARTIAL_CANDIDATE_LEVEL_COVERAGE"
            stage = STAGE_BY_FAMILY[family]
            priority = "HIGH"
            blocker = "BLOCKING_TRUE_SHADOW_RERANK"
            reason = f"{family} has only {current}/{required_count} candidate-level contributions."
        else:
            gap_type = "MISSING_CANDIDATE_LEVEL_COVERAGE"
            stage = STAGE_BY_FAMILY.get(family, f"V20.108-RX_{family}_CANDIDATE_SCORE_SOURCE_BUILDER")
            priority = "HIGH"
            blocker = "BLOCKING_TRUE_SHADOW_RERANK"
            reason = f"{family} has no materialized candidate-level contribution coverage."
        gap_rows.append({
            "factor_family": family,
            "gap_type": gap_type,
            "current_coverage_count": str(current),
            "required_coverage_count": str(required_count),
            "missing_candidate_count": str(missing),
            "planned_repair_stage": stage,
            "repair_priority": priority,
            "blocker_status": blocker,
            "blocker_reason": reason,
            "unsafe_action_forbidden": "Do not use source_rank_or_score, baseline_rank, family-level evidence, proxies, or fabricated scores.",
            **safety(),
        })

    planned_specs = [
        {
            "stage": STAGE_BY_FAMILY["FUNDAMENTAL"],
            "family": "FUNDAMENTAL",
            "goal": "Build real ticker-level fundamental contribution columns for all current candidates.",
            "inputs": [V48_CANDIDATES, V50_CANDIDATES, V50_FACTORS, R3_PLAN],
            "columns": "ticker;fundamental_candidate_score;valuation_metric;quality_metric;growth_metric",
            "outputs": "outputs/v20/consolidation/V20_108_R6_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv",
            "method": "RESEARCH_ONLY_TICKER_LEVEL_FUNDAMENTAL_SCORE_SOURCE_ATTACHMENT",
            "proxy": "FALSE",
            "approval": "FALSE",
        },
        {
            "stage": STAGE_BY_FAMILY["STRATEGY"],
            "family": "STRATEGY",
            "goal": "Build real ticker-level strategy contribution columns for all current candidates.",
            "inputs": [V48_CANDIDATES, V50_ENTRY, V50_FACTORS, R3_PLAN],
            "columns": "ticker;strategy_candidate_score;entry_setup_metric;strategy_signal_metric",
            "outputs": "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv",
            "method": "RESEARCH_ONLY_TICKER_LEVEL_STRATEGY_SCORE_SOURCE_ATTACHMENT",
            "proxy": "FALSE",
            "approval": "FALSE",
        },
        {
            "stage": STAGE_BY_FAMILY["MARKET_REGIME"],
            "family": "MARKET_REGIME",
            "goal": "Build real ticker-level market regime exposure columns; family-level ETF regime evidence alone is insufficient.",
            "inputs": [V48_CANDIDATES, V98C_AUDIT, V106_FACTOR, R3_PLAN],
            "columns": "ticker;market_regime_exposure_score;sector_or_theme_mapping;regime_sensitivity_metric",
            "outputs": "outputs/v20/consolidation/V20_108_R8_MARKET_REGIME_CANDIDATE_EXPOSURE.csv",
            "method": "RESEARCH_ONLY_TICKER_LEVEL_MARKET_REGIME_EXPOSURE_ATTACHMENT",
            "proxy": "FALSE",
            "approval": "TRUE",
        },
        {
            "stage": STAGE_BY_FAMILY["RISK"],
            "family": "RISK",
            "goal": "Expand real ticker-level risk contribution coverage from 11 candidates to the full current universe.",
            "inputs": [R4_SCORES, V48_CANDIDATES, V50_BENCH, R3_PLAN],
            "columns": "ticker;risk_candidate_score;risk_adjusted_score;drawdown_metric;volatility_metric",
            "outputs": "outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_COVERAGE.csv",
            "method": "RESEARCH_ONLY_TICKER_LEVEL_RISK_SCORE_COVERAGE_EXPANSION",
            "proxy": "FALSE",
            "approval": "FALSE",
        },
        {
            "stage": ASSEMBLER_STAGE,
            "family": "ALL",
            "goal": "Assemble complete six-family candidate score source after R6-R9 succeed; do not rerank.",
            "inputs": [R4_SCORES, R4_COVERAGE],
            "columns": "ticker;fundamental_contribution;technical_contribution;strategy_contribution;risk_contribution;market_regime_contribution;data_trust_contribution",
            "outputs": "outputs/v20/consolidation/V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_SOURCE.csv",
            "method": "RESEARCH_ONLY_COMPLETE_SIX_FAMILY_SCORE_ASSEMBLY_NO_RERANK",
            "proxy": "FALSE",
            "approval": "FALSE",
        },
    ]

    coverage_status = {row["factor_family"]: row for row in gap_rows}
    for spec in planned_specs:
        family = spec["family"]
        if family == "ALL":
            current_status = "ASSEMBLER_PENDING_R6_R9_COMPLETION"
            current_count = "0"
        else:
            gap = coverage_status[family]
            current_status = gap["gap_type"]
            current_count = gap["current_coverage_count"]
        stage_rows.append({
            "planned_stage": spec["stage"],
            "target_factor_family": family,
            "current_coverage_status": current_status,
            "current_candidate_coverage_count": current_count,
            "required_candidate_count": str(required_count),
            "stage_goal": spec["goal"],
            "required_input_artifacts": ";".join(rel(path) for path in spec["inputs"]),
            "required_source_columns": spec["columns"],
            "planned_output_artifacts": spec["outputs"],
            "materialization_method": spec["method"],
            "proxy_allowed": spec["proxy"],
            "operator_approval_required": spec["approval"],
            "required_before_shadow_rerank": "TRUE",
            "downstream_unblocked_stage": "V20.108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR_RERUN",
            "safety_constraints": "RESEARCH_ONLY;NO_OFFICIAL_RANKING;NO_RECOMMENDATION;NO_TRADE;NO_PROXY_ACTIVATION;NO_FABRICATION;NO_SOURCE_RANK_OR_BASELINE_RANK",
            **safety(extra=True),
        })
        source_rows.extend(requirement_rows(spec["stage"], family, spec["inputs"], spec["columns"]))

    blocking_families = [
        row["factor_family"] for row in gap_rows
        if row["blocker_status"] == "BLOCKING_TRUE_SHADOW_RERANK"
    ]
    repair_stages = [STAGE_BY_FAMILY[family] for family in ["FUNDAMENTAL", "STRATEGY", "MARKET_REGIME", "RISK"]]
    repair_stages.append(ASSEMBLER_STAGE)
    resolution_rows = [{
        "readiness_check_id": "V20_108_R5_RESOLUTION_001",
        "complete_six_family_contribution_candidate_count": readiness.get("complete_six_family_contribution_candidate_count", "0"),
        "usable_for_shadow_rerank_count": readiness.get("usable_for_shadow_rerank_count", "0"),
        "current_shadow_rerank_status": readiness.get("shadow_rerank_readiness_status", "NOT_READY"),
        "blocking_factor_families": ";".join(blocking_families),
        "required_repair_stages": ";".join(repair_stages),
        "minimum_condition_to_rerun_v20_108": "All 315 candidates must have real non-proxy candidate-level contributions for all six factor families.",
        "recommended_next_stage": STAGE_BY_FAMILY["FUNDAMENTAL"],
        **safety(extra=True),
    }]

    write_csv(OUT_STAGE_PLAN, STAGE_FIELDS, stage_rows)
    write_csv(OUT_GAP_MAP, GAP_FIELDS, gap_rows)
    write_csv(OUT_SOURCE_REQ, SOURCE_FIELDS, source_rows)
    write_csv(OUT_RESOLUTION, RESOLUTION_FIELDS, resolution_rows)

    lines = [
        "# V20.108-R5 Missing Upstream Factor Score Stage Planner",
        "",
        "## Current Result",
        f"- wrapper_status: {STATUS}",
        f"- factor_family_count: {len(gap_rows)}",
        f"- planned_stage_count: {len(stage_rows)}",
        "- contribution_scores_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "",
        "## Required Planned Stages",
        *[f"- {spec['stage']}" for spec in planned_specs],
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- official_recommendation_created: FALSE",
        "- is_official_ranking: FALSE",
        "- is_official_weight: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(STATUS)
    print(f"FACTOR_FAMILY_COUNT={len(gap_rows)}")
    print(f"PLANNED_STAGE_COUNT={len(stage_rows)}")
    print("R6_PRESENT=TRUE")
    print("R7_PRESENT=TRUE")
    print("R8_PRESENT=TRUE")
    print("R9_PRESENT=TRUE")
    print("R10_PRESENT=TRUE")
    print("CONTRIBUTION_SCORES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_STAGE_PLAN={rel(OUT_STAGE_PLAN)}")
    print(f"OUTPUT_GAP_MAP={rel(OUT_GAP_MAP)}")
    print(f"OUTPUT_SOURCE_REQUIREMENT_AUDIT={rel(OUT_SOURCE_REQ)}")
    print(f"OUTPUT_RESOLUTION_PLAN={rel(OUT_RESOLUTION)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
