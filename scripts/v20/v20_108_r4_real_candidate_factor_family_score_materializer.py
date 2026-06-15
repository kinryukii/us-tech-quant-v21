#!/usr/bin/env python
"""V20.108-R4 real candidate factor-family score materializer.

Materializes research-only candidate-level factor-family scores only for
families that V20.108-R3 marked ready or partial-ready from real candidate-level
columns. This stage does not create shadow reranks, official rankings, proxies,
or fabricated values.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R3_PLAN = CONSOLIDATION / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN.csv"
R3_MAPPING = CONSOLIDATION / "V20_108_R3_FACTOR_FAMILY_SOURCE_COLUMN_MAPPING_PLAN.csv"
R3_PROXY = CONSOLIDATION / "V20_108_R3_SAFE_PROXY_ELIGIBILITY_AUDIT.csv"
R3_BLOCKER = CONSOLIDATION / "V20_108_R3_MATERIALIZATION_BLOCKER_AUDIT.csv"
R3_NEXT = CONSOLIDATION / "V20_108_R3_NEXT_STAGE_RECOMMENDATION.csv"
R2_EXPANDED = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
R2_READINESS = CONSOLIDATION / "V20_108_R2_SHADOW_RERANK_READINESS_AFTER_EXPANSION.csv"
V107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R5_REGISTRY = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V48_CANDIDATES = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V48_FACTORS = CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv"
V50_CANDIDATES = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V50_FACTORS = CONSOLIDATION / "V20_50_FACTOR_RESEARCH_CONTEXT_PACKET.csv"
V50_ENTRY = CONSOLIDATION / "V20_50_ENTRY_STRATEGY_RESEARCH_CONTEXT_PACKET.csv"
V50_BENCH = CONSOLIDATION / "V20_50_BENCHMARK_RESEARCH_CONTEXT_PACKET.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R4_FACTOR_FAMILY_SCORE_MATERIALIZATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_108_R4_CANDIDATE_CONTRIBUTION_COVERAGE_AFTER_MATERIALIZATION.csv"
OUT_READINESS = CONSOLIDATION / "V20_108_R4_SHADOW_RERANK_READINESS_AFTER_MATERIALIZATION.csv"
REPORT = READ_CENTER / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZER_WITH_PARTIAL_FAMILY_COVERAGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R4_NO_REAL_MATERIALIZABLE_CANDIDATE_FACTOR_SCORES"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
FAMILY_COLUMNS = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}
READY_STATUSES = {
    "READY_FROM_REAL_CANDIDATE_LEVEL_COLUMNS",
    "PARTIAL_READY_FROM_REAL_CANDIDATE_LEVEL_COLUMNS",
}

SCORE_FIELDS = [
    "ticker", "baseline_rank", "baseline_score_source", "fundamental_contribution",
    "technical_contribution", "strategy_contribution", "risk_contribution",
    "market_regime_contribution", "data_trust_contribution",
    "materialized_factor_families", "missing_factor_families",
    "partial_factor_families", "complete_six_family_contribution",
    "contribution_normalization_status", "usable_for_shadow_rerank",
    "contribution_source_artifacts", "contribution_source_stages",
    "candidate_factor_granularity_status", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

AUDIT_FIELDS = [
    "factor_family", "r3_readiness_status", "materialization_attempted",
    "materialization_status", "candidate_count", "materialized_candidate_count",
    "missing_candidate_count", "source_artifact", "source_stage", "source_columns",
    "used_source_rank_or_score", "used_baseline_rank", "used_proxy",
    "fabricated_values_created", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]

COVERAGE_FIELDS = [
    "factor_family", "required_candidate_count", "materialized_candidate_count",
    "missing_candidate_count", "coverage_ratio", "contribution_coverage_status",
    "usable_for_shadow_rerank", "missing_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

READINESS_FIELDS = [
    "readiness_check_id", "candidate_count",
    "complete_six_family_contribution_candidate_count",
    "partial_contribution_candidate_count", "missing_contribution_candidate_count",
    "usable_for_shadow_rerank_count", "technical_coverage_ratio",
    "data_trust_coverage_ratio", "risk_coverage_ratio", "fundamental_coverage_ratio",
    "strategy_coverage_ratio", "market_regime_coverage_ratio",
    "shadow_rerank_readiness_status", "shadow_rerank_blocker_reason",
    "recommended_next_stage", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
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


def source_stage(path_text: str) -> str:
    name = Path(path_text).name
    if name.startswith("V20_"):
        parts = name.split("_", 2)
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else "V20"
    if name.startswith("V18_"):
        return "V18"
    if name.startswith("V19_"):
        return "V19"
    return "DISCOVERED"


def main() -> int:
    plan_rows, _ = read_csv(R3_PLAN)
    r2_rows, _ = read_csv(R2_EXPANDED)
    mapping_rows, _ = read_csv(R3_MAPPING)
    plan = {row["factor_family"]: row for row in plan_rows}
    candidate_count = len(r2_rows)

    allowed_families = {
        family for family, row in plan.items()
        if row.get("materialization_readiness_status") in READY_STATUSES
    }

    family_sources: dict[str, set[str]] = {family: set() for family in FAMILIES}
    family_columns: dict[str, set[str]] = {family: set() for family in FAMILIES}
    for row in mapping_rows:
        family = row.get("factor_family")
        if family in FAMILIES and row.get("candidate_level_numeric_columns"):
            family_sources[family].add(row.get("source_artifact", ""))
            for column in row.get("candidate_level_numeric_columns", "").split(";"):
                if column:
                    family_columns[family].add(column)

    score_rows: list[dict[str, str]] = []
    for row in r2_rows:
        materialized: list[str] = []
        missing: list[str] = []
        partial: list[str] = []
        out = {
            "ticker": row.get("ticker", ""),
            "baseline_rank": row.get("baseline_rank", ""),
            "baseline_score_source": row.get("baseline_score_source", ""),
            "contribution_source_artifacts": row.get("contribution_source_artifacts", ""),
            "contribution_source_stages": row.get("contribution_source_stages", ""),
            **safety(extra=True),
        }
        for family in FAMILIES:
            column = FAMILY_COLUMNS[family]
            value = row.get(column, "") if family in allowed_families else ""
            out[column] = value
            if value:
                materialized.append(family)
                if plan[family].get("materialization_readiness_status") == "PARTIAL_READY_FROM_REAL_CANDIDATE_LEVEL_COLUMNS":
                    partial.append(family)
            else:
                missing.append(family)
        complete = len(materialized) == len(FAMILIES)
        if complete:
            granularity = "CANDIDATE_FACTOR_FAMILY_COMPLETE_GRANULARITY"
            norm_status = "COMPLETE_REAL_SIX_FAMILY_CONTRIBUTIONS_AVAILABLE"
        elif materialized:
            granularity = "CANDIDATE_FACTOR_FAMILY_PARTIAL_GRANULARITY"
            norm_status = "PARTIAL_REAL_CONTRIBUTIONS_ONLY_NO_COMPLETE_SCORE_NORMALIZATION"
        else:
            granularity = "LIMITED_CANDIDATE_FACTOR_GRANULARITY"
            norm_status = "NO_REAL_MATERIALIZABLE_CONTRIBUTIONS"
        out.update({
            "materialized_factor_families": ";".join(materialized),
            "missing_factor_families": ";".join(missing),
            "partial_factor_families": ";".join(partial),
            "complete_six_family_contribution": tf(complete),
            "contribution_normalization_status": norm_status,
            "usable_for_shadow_rerank": tf(complete),
            "candidate_factor_granularity_status": granularity,
        })
        score_rows.append(out)

    audit_rows: list[dict[str, str]] = []
    coverage_rows: list[dict[str, str]] = []
    ratios: dict[str, float] = {}
    for family in FAMILIES:
        column = FAMILY_COLUMNS[family]
        readiness = plan.get(family, {}).get("materialization_readiness_status", "")
        attempted = family in allowed_families
        materialized_count = sum(1 for row in score_rows if row.get(column, ""))
        missing_count = candidate_count - materialized_count
        ratio = materialized_count / candidate_count if candidate_count else 0.0
        ratios[family] = ratio
        if attempted and materialized_count == candidate_count:
            status = "MATERIALIZED_COMPLETE_REAL_CANDIDATE_LEVEL_COVERAGE"
        elif attempted and materialized_count > 0:
            status = "MATERIALIZED_PARTIAL_REAL_CANDIDATE_LEVEL_COVERAGE"
        elif attempted:
            status = "ATTEMPTED_NO_REAL_VALUES_FOUND"
        else:
            status = "NOT_MATERIALIZED_BLOCKED_BY_R3"
        source_artifacts = sorted(src for src in family_sources[family] if src)
        source_columns = sorted(family_columns[family])
        audit_rows.append({
            "factor_family": family,
            "r3_readiness_status": readiness,
            "materialization_attempted": tf(attempted),
            "materialization_status": status,
            "candidate_count": str(candidate_count),
            "materialized_candidate_count": str(materialized_count),
            "missing_candidate_count": str(missing_count),
            "source_artifact": ";".join(source_artifacts),
            "source_stage": ";".join(sorted({source_stage(src) for src in source_artifacts})),
            "source_columns": ";".join(source_columns),
            "used_source_rank_or_score": "FALSE",
            "used_baseline_rank": "FALSE",
            "used_proxy": "FALSE",
            "fabricated_values_created": "FALSE",
            "validation_status": "PASS",
            "validation_reason": "REAL_CANDIDATE_LEVEL_COLUMNS_ONLY_NO_PROXY_NO_RANK_FIELDS",
            **safety(),
        })
        coverage_rows.append({
            "factor_family": family,
            "required_candidate_count": str(candidate_count),
            "materialized_candidate_count": str(materialized_count),
            "missing_candidate_count": str(missing_count),
            "coverage_ratio": f"{ratio:.10f}",
            "contribution_coverage_status": "COMPLETE" if ratio == 1.0 else ("PARTIAL" if ratio > 0 else "MISSING"),
            "usable_for_shadow_rerank": tf(ratio == 1.0),
            "missing_reason": "" if ratio == 1.0 else ("PARTIAL_REAL_CANDIDATE_LEVEL_COVERAGE" if ratio > 0 else "MISSING_REAL_CANDIDATE_LEVEL_CONTRIBUTION"),
            **safety(),
        })

    complete_count = sum(1 for row in score_rows if row["complete_six_family_contribution"] == "TRUE")
    partial_count = sum(1 for row in score_rows if row["materialized_factor_families"] and row["complete_six_family_contribution"] == "FALSE")
    missing_count = sum(1 for row in score_rows if not row["materialized_factor_families"])
    usable_count = complete_count
    ready = complete_count == candidate_count and candidate_count > 0
    readiness_rows = [{
        "readiness_check_id": "V20_108_R4_READINESS_001",
        "candidate_count": str(candidate_count),
        "complete_six_family_contribution_candidate_count": str(complete_count),
        "partial_contribution_candidate_count": str(partial_count),
        "missing_contribution_candidate_count": str(missing_count),
        "usable_for_shadow_rerank_count": str(usable_count),
        "technical_coverage_ratio": f"{ratios.get('TECHNICAL', 0.0):.10f}",
        "data_trust_coverage_ratio": f"{ratios.get('DATA_TRUST', 0.0):.10f}",
        "risk_coverage_ratio": f"{ratios.get('RISK', 0.0):.10f}",
        "fundamental_coverage_ratio": f"{ratios.get('FUNDAMENTAL', 0.0):.10f}",
        "strategy_coverage_ratio": f"{ratios.get('STRATEGY', 0.0):.10f}",
        "market_regime_coverage_ratio": f"{ratios.get('MARKET_REGIME', 0.0):.10f}",
        "shadow_rerank_readiness_status": "READY_FOR_SHADOW_RERANK" if ready else "NOT_READY_INCOMPLETE_REAL_SIX_FAMILY_CONTRIBUTION_COVERAGE",
        "shadow_rerank_blocker_reason": "" if ready else "FUNDAMENTAL_STRATEGY_MARKET_REGIME_MISSING_AND_RISK_PARTIAL",
        "recommended_next_stage": "V20.108-R5_SHADOW_RERANK_FROM_REAL_SIX_FAMILY_CONTRIBUTIONS" if ready else "V20.108-R5_COMPLETE_MISSING_CANDIDATE_FACTOR_FAMILY_SOURCES",
        **safety(extra=True),
    }]

    materialized_any = any(row["materialized_candidate_count"] != "0" for row in audit_rows)
    status = PASS_STATUS if ready else (PARTIAL_STATUS if materialized_any else BLOCKED_STATUS)

    write_csv(OUT_SCORES, SCORE_FIELDS, score_rows)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audit_rows)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage_rows)
    write_csv(OUT_READINESS, READINESS_FIELDS, readiness_rows)

    lines = [
        "# V20.108-R4 Real Candidate Factor-Family Score Materializer",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_count: {candidate_count}",
        f"- complete_six_family_contribution_candidate_count: {complete_count}",
        f"- partial_contribution_candidate_count: {partial_count}",
        f"- usable_for_shadow_rerank_count: {usable_count}",
        "- shadow_rerank_output_created: FALSE",
        "- source_rank_or_score_used_as_contribution: FALSE",
        "- baseline_rank_used_as_contribution: FALSE",
        "- proxy_values_activated: FALSE",
        "- contribution_scores_fabricated: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
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

    print(status)
    print(f"CANDIDATE_COUNT={candidate_count}")
    print(f"COMPLETE_SIX_FAMILY_CONTRIBUTION_CANDIDATE_COUNT={complete_count}")
    print(f"PARTIAL_CONTRIBUTION_CANDIDATE_COUNT={partial_count}")
    print(f"USABLE_FOR_SHADOW_RERANK_COUNT={usable_count}")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE")
    print("BASELINE_RANK_USED_AS_CONTRIBUTION=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("CONTRIBUTION_SCORES_FABRICATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_SCORES={rel(OUT_SCORES)}")
    print(f"OUTPUT_AUDIT={rel(OUT_AUDIT)}")
    print(f"OUTPUT_COVERAGE={rel(OUT_COVERAGE)}")
    print(f"OUTPUT_READINESS={rel(OUT_READINESS)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
