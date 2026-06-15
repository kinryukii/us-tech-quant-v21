#!/usr/bin/env python
"""V20.108-R3 candidate factor-family score materialization plan.

Creates a research-only plan for future candidate-level factor-family score
materialization. This stage audits sources and blockers only; it does not
create final contribution scores, shadow reranks, official rankings, or trades.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
EVIDENCE = ROOT / "outputs" / "v20" / "evidence"

R2_EXPANDED = CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv"
R2_SOURCE = CONSOLIDATION / "V20_108_R2_MISSING_FACTOR_FAMILY_SOURCE_AUDIT.csv"
R2_MATERIAL = CONSOLIDATION / "V20_108_R2_FACTOR_FAMILY_MATERIALIZATION_AUDIT.csv"
R2_READINESS = CONSOLIDATION / "V20_108_R2_SHADOW_RERANK_READINESS_AFTER_EXPANSION.csv"
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

OUT_PLAN = CONSOLIDATION / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN.csv"
OUT_MAPPING = CONSOLIDATION / "V20_108_R3_FACTOR_FAMILY_SOURCE_COLUMN_MAPPING_PLAN.csv"
OUT_PROXY = CONSOLIDATION / "V20_108_R3_SAFE_PROXY_ELIGIBILITY_AUDIT.csv"
OUT_BLOCKER = CONSOLIDATION / "V20_108_R3_MATERIALIZATION_BLOCKER_AUDIT.csv"
OUT_NEXT = CONSOLIDATION / "V20_108_R3_NEXT_STAGE_RECOMMENDATION.csv"
REPORT = READ_CENTER / "V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_REPORT.md"

PASS_STATUS = "PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_CREATED"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R3_CANDIDATE_FACTOR_FAMILY_SCORE_MATERIALIZATION_PLAN_WITH_BLOCKERS"
BLOCKED_STATUS = "BLOCKED_V20_108_R3_NO_SAFE_MATERIALIZATION_PATHS_FOUND"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
FAMILY_COLUMNS = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}

PLAN_FIELDS = [
    "factor_family", "current_coverage_status", "current_candidate_coverage_count",
    "required_candidate_count", "materialization_readiness_status",
    "proposed_source_artifact", "proposed_source_stage", "proposed_source_columns",
    "proposed_materialization_method", "normalization_required",
    "operator_approval_required", "safe_proxy_allowed", "materialization_allowed_now",
    "materialization_blocker_reason", "recommended_next_stage", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

MAPPING_FIELDS = [
    "factor_family", "source_artifact", "source_exists", "source_non_empty",
    "ticker_column_available", "candidate_level_numeric_columns",
    "candidate_level_semantic_match_columns", "family_level_only_columns",
    "rejected_columns", "rejection_reason", "source_rank_or_score_present",
    "source_rank_or_score_used_as_contribution", "mapping_confidence",
    "materialization_allowed", "materialization_blocker_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

PROXY_FIELDS = [
    "factor_family", "proxy_candidate_name", "proxy_source_artifact",
    "proxy_source_columns", "proxy_semantic_basis", "proxy_numeric_available",
    "proxy_candidate_level_available", "proxy_risk_level", "operator_approval_required",
    "proxy_activation_allowed", "proxy_status", "proxy_blocker_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

BLOCKER_FIELDS = [
    "blocker_id", "factor_family", "blocker_type", "current_status",
    "blocking_downstream_stage", "why_blocking", "safe_repair_action",
    "unsafe_action_forbidden", "recommended_next_stage", "research_only",
    "official_promotion_allowed", "official_recommendation_created", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]

NEXT_FIELDS = [
    "recommendation_id", "recommended_next_stage", "recommendation_scope",
    "target_factor_families", "precondition", "expected_output",
    "shadow_rerank_output_created", "official_ranking_created",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
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


def read_csv(path: Path) -> tuple[list[dict[str, str]], str, list[str]]:
    if not path.exists():
        return [], "MISSING", []
    if path.stat().st_size == 0:
        return [], "EMPTY", []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, "OK" if fields else "MALFORMED", fields


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


def discover_sources() -> list[Path]:
    seeds = [
        R2_EXPANDED, R2_SOURCE, R2_MATERIAL, R2_READINESS, V107_WEIGHTS,
        R5_REGISTRY, V48_CANDIDATES, V48_FACTORS, V50_CANDIDATES, V50_FACTORS,
        V50_ENTRY, V50_BENCH, V98C_AUDIT, V106_FACTOR, V49_RESEARCH, V49_OFFICIAL,
    ]
    found: list[Path] = []
    for pattern in (
        "*FUNDAMENTAL*.csv", "*TECHNICAL*.csv", "*STRATEGY*.csv", "*RISK*.csv",
        "*REGIME*.csv", "*DATA_TRUST*.csv", "*FACTOR*.csv",
    ):
        found.extend(CONSOLIDATION.glob(pattern))
        if EVIDENCE.exists():
            found.extend(EVIDENCE.glob(pattern))
    for root in (ROOT / "outputs" / "v18", ROOT / "outputs" / "v19", ROOT / "outputs" / "backtest"):
        if root.exists():
            found.extend(root.rglob("*.csv"))
    excluded = {OUT_PLAN.resolve(), OUT_MAPPING.resolve(), OUT_PROXY.resolve(), OUT_BLOCKER.resolve(), OUT_NEXT.resolve()}
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in seeds + sorted(found):
        resolved = path.resolve()
        if resolved in excluded:
            continue
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(path)
    return ordered


def semantic_family(column: str, fields_context: str = "") -> str | None:
    name = column.lower()
    context = fields_context.lower()
    if name in {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "factor_pack_rank"}:
        return None
    if "technical" in name or "timing" in name:
        return "TECHNICAL"
    if "fundamental" in name or "valuation" in name:
        return "FUNDAMENTAL"
    if "strategy" in name or "entry" in name or "setup" in name:
        return "STRATEGY"
    if "risk" in name or "drawdown" in name or "volatility" in name:
        return "RISK"
    if "market_regime" in name or "regime" in name:
        return "MARKET_REGIME"
    if "data_trust" in name or "trustworthiness" in name or "source_quality" in name:
        return "DATA_TRUST"
    if column == "factor_score_value" and "data_trustworthiness" in context:
        return "DATA_TRUST"
    return None


def mapping_rows_from_sources() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in discover_sources():
        data, status, fields = read_csv(path)
        exists = path.exists()
        non_empty = exists and path.stat().st_size > 0
        ticker_available = any(field in fields for field in ("ticker", "normalized_ticker", "ticker_or_candidate_id", "display_name_or_ticker"))
        source_rank_present = "source_rank_or_score" in fields
        context = " ".join(clean(row.get("factor_category")) + " " + clean(row.get("factor_family")) for row in data[:20])
        family_level_columns = [field for field in fields if field in {"factor_family", "regime_classification", "etf_pair"} and not ticker_available]
        numeric_fields = {
            field
            for field in fields
            if any(clean(row.get(field)) and clean(row.get(field)).replace(".", "", 1).replace("-", "", 1).isdigit() for row in data[:500])
        }
        numeric_candidates: list[str] = []
        semantic_by_family: dict[str, list[str]] = {family: [] for family in FAMILIES}
        rejected: list[str] = []
        for field in fields:
            if field in {"source_rank_or_score", "baseline_rank", "rank", "report_rank", "factor_pack_rank"}:
                rejected.append(field)
                continue
            fam = semantic_family(field, context)
            if fam:
                semantic_by_family[fam].append(field)
                if field in numeric_fields and any(token in field.lower() for token in ("score", "contribution", "metric", "signal", "value")):
                    numeric_candidates.append(field)
        for family in FAMILIES:
            semantic_cols = sorted(set(semantic_by_family[family]))
            candidate_numeric = sorted(set(col for col in numeric_candidates if col in semantic_cols))
            family_level = family_level_columns if family in clean(context).upper() or family == "MARKET_REGIME" and family_level_columns else []
            allowed = bool(ticker_available and candidate_numeric)
            if allowed:
                confidence = "HIGH" if family in {"TECHNICAL", "DATA_TRUST"} else "PARTIAL"
                blocker = ""
                rejection_reason = ""
            elif family_level:
                confidence = "LOW"
                blocker = "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_MATERIALIZABLE"
                rejection_reason = "FAMILY_LEVEL_ONLY_NOT_TICKER_LEVEL"
            else:
                confidence = "NONE"
                blocker = "NO_TICKER_LEVEL_NUMERIC_SEMANTIC_SOURCE"
                rejection_reason = "NO_SAFE_CANDIDATE_LEVEL_SEMANTIC_MATCH"
            rows.append({
                "factor_family": family,
                "source_artifact": rel(path),
                "source_exists": tf(exists),
                "source_non_empty": tf(non_empty),
                "ticker_column_available": tf(ticker_available),
                "candidate_level_numeric_columns": ";".join(candidate_numeric) if ticker_available else "",
                "candidate_level_semantic_match_columns": ";".join(semantic_cols),
                "family_level_only_columns": ";".join(family_level),
                "rejected_columns": ";".join(sorted(set(rejected))),
                "rejection_reason": rejection_reason,
                "source_rank_or_score_present": tf(source_rank_present),
                "source_rank_or_score_used_as_contribution": "FALSE",
                "mapping_confidence": confidence,
                "materialization_allowed": "FALSE",
                "materialization_blocker_reason": "PLANNING_ONLY_NO_SCORE_MATERIALIZATION_IN_R3" if allowed else blocker,
                **safety(),
            })
    return rows


def main() -> int:
    expanded, _, _ = read_csv(R2_EXPANDED)
    material, _, _ = read_csv(R2_MATERIAL)
    candidate_count = len(expanded)
    material_by_family = {row["factor_family"]: row for row in material}
    mapping_rows = mapping_rows_from_sources()

    plan_rows: list[dict[str, str]] = []
    proxy_rows: list[dict[str, str]] = []
    blocker_rows: list[dict[str, str]] = []
    blocked_count = 0
    ready_paths = 0

    for family in FAMILIES:
        mat = material_by_family.get(family, {})
        coverage_count = int(mat.get("total_candidates_with_contribution") or 0)
        coverage_ratio = float(mat.get("coverage_ratio") or 0.0)
        source_artifacts = mat.get("source_artifacts", "")
        semantic_sources = [
            row for row in mapping_rows
            if row["factor_family"] == family and row["candidate_level_numeric_columns"]
            and row["ticker_column_available"] == "TRUE"
        ]
        family_level_sources = [
            row for row in mapping_rows
            if row["factor_family"] == family and row["family_level_only_columns"]
        ]
        proposed_columns = sorted({
            col for row in semantic_sources
            for col in row["candidate_level_numeric_columns"].split(";")
            if col
        })
        proposed_sources = sorted({
            row["source_artifact"] for row in semantic_sources
            if row["source_artifact"]
        })
        if coverage_count == candidate_count and candidate_count:
            coverage_status = "PARTIAL_EXISTING_CONTRIBUTION_FAMILY_COMPLETE_CANDIDATE_COVERAGE"
            readiness = "READY_FROM_REAL_CANDIDATE_LEVEL_COLUMNS"
            method = "PLAN_ONLY_CARRY_FORWARD_EXISTING_REAL_CANDIDATE_LEVEL_COLUMNS"
            blocker = "NONE_R3_PLAN_ONLY_NO_MATERIALIZATION_CREATED"
            next_stage = "V20.108-R4_SHADOW_RERANK_WITH_COMPLETE_OR_APPROVED_CONTRIBUTIONS"
            allowed_now = "FALSE"
            operator_required = "FALSE"
            safe_proxy_allowed = "FALSE"
            ready_paths += 1
        elif coverage_count > 0:
            coverage_status = "PARTIAL_EXISTING_CONTRIBUTION_FAMILY_PARTIAL_CANDIDATE_COVERAGE"
            readiness = "PARTIAL_READY_FROM_REAL_CANDIDATE_LEVEL_COLUMNS"
            method = "PLAN_ONLY_EXTEND_REAL_CANDIDATE_LEVEL_COLUMNS_TO_FULL_UNIVERSE"
            blocker = "INCOMPLETE_CANDIDATE_COVERAGE"
            next_stage = f"V20.108-R4_{family}_CANDIDATE_LEVEL_SCORE_COMPLETION"
            allowed_now = "FALSE"
            operator_required = "FALSE"
            safe_proxy_allowed = "FALSE"
            ready_paths += 1
        elif family_level_sources:
            coverage_status = "MISSING_CANDIDATE_LEVEL_COVERAGE_FAMILY_LEVEL_EVIDENCE_EXISTS"
            readiness = "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_MATERIALIZABLE"
            method = "DO_NOT_MATERIALIZE_FROM_FAMILY_LEVEL_ONLY_EVIDENCE"
            blocker = "FAMILY_LEVEL_ONLY_NOT_CANDIDATE_MATERIALIZABLE"
            next_stage = f"V20.108-R4_{family}_CANDIDATE_LEVEL_SOURCE_ATTACHMENT"
            allowed_now = "FALSE"
            operator_required = "TRUE"
            safe_proxy_allowed = "FALSE"
            blocked_count += 1
        else:
            coverage_status = "MISSING_CANDIDATE_LEVEL_COVERAGE"
            readiness = "REQUIRES_UPSTREAM_FACTOR_SCORE_STAGE"
            method = "CREATE_UPSTREAM_TICKER_LEVEL_NUMERIC_FACTOR_FAMILY_SCORE_SOURCE"
            blocker = "BLOCKED_NO_SAFE_SOURCE"
            next_stage = f"V20.108-R4_{family}_UPSTREAM_FACTOR_FAMILY_SCORE_SOURCE_BUILDER"
            allowed_now = "FALSE"
            operator_required = "TRUE"
            safe_proxy_allowed = "FALSE"
            blocked_count += 1
        plan_rows.append({
            "factor_family": family,
            "current_coverage_status": coverage_status,
            "current_candidate_coverage_count": str(coverage_count),
            "required_candidate_count": str(candidate_count),
            "materialization_readiness_status": readiness,
            "proposed_source_artifact": ";".join(proposed_sources) or source_artifacts,
            "proposed_source_stage": ";".join(sorted({source_stage(src) for src in (proposed_sources or source_artifacts.split(";")) if src})),
            "proposed_source_columns": ";".join(proposed_columns),
            "proposed_materialization_method": method,
            "normalization_required": tf(coverage_count > 0 or bool(proposed_columns)),
            "operator_approval_required": operator_required,
            "safe_proxy_allowed": safe_proxy_allowed,
            "materialization_allowed_now": allowed_now,
            "materialization_blocker_reason": blocker,
            "recommended_next_stage": next_stage,
            **safety(extra=True),
        })
        proxy_rows.append({
            "factor_family": family,
            "proxy_candidate_name": f"{family}_OPERATOR_APPROVED_CANDIDATE_LEVEL_PROXY",
            "proxy_source_artifact": V106_FACTOR.as_posix() if family == "MARKET_REGIME" else "",
            "proxy_source_columns": "factor_mean_alpha;factor_hit_rate;factor_adverse_outcome_rate" if family == "MARKET_REGIME" else "",
            "proxy_semantic_basis": "FAMILY_LEVEL_CONTEXT_ONLY_REQUIRES_OPERATOR_APPROVAL_AND_TICKER_LEVEL_MAPPING",
            "proxy_numeric_available": tf(family == "MARKET_REGIME"),
            "proxy_candidate_level_available": "FALSE",
            "proxy_risk_level": "HIGH" if family in {"FUNDAMENTAL", "STRATEGY", "MARKET_REGIME"} else "MEDIUM",
            "operator_approval_required": "TRUE",
            "proxy_activation_allowed": "FALSE",
            "proxy_status": "PROXY_NOT_ACTIVATED_OPERATOR_APPROVAL_REQUIRED",
            "proxy_blocker_reason": "NO_OPERATOR_APPROVAL_AND_NO_CANDIDATE_LEVEL_PROXY_MAPPING",
            **safety(),
        })
        if readiness not in {"READY_FROM_REAL_CANDIDATE_LEVEL_COLUMNS"}:
            blocker_rows.append({
                "blocker_id": f"V20_108_R3_BLOCKER_{len(blocker_rows)+1:03d}",
                "factor_family": family,
                "blocker_type": readiness,
                "current_status": coverage_status,
                "blocking_downstream_stage": "V20.108_SHADOW_DYNAMIC_WEIGHTED_RANKING_SIMULATOR_RERUN",
                "why_blocking": "Complete six-family ticker-level numeric contribution coverage is required before shadow rerank.",
                "safe_repair_action": "Build or attach real ticker-level numeric candidate factor-family source columns.",
                "unsafe_action_forbidden": "Do not use source_rank_or_score, baseline_rank, family-level evidence, or fabricated proxy scores.",
                "recommended_next_stage": next_stage,
                **safety(),
            })

    next_rows = [{
        "recommendation_id": "V20_108_R3_NEXT_001",
        "recommended_next_stage": "V20.108-R4_CANDIDATE_LEVEL_FACTOR_FAMILY_SCORE_SOURCE_BUILDER",
        "recommendation_scope": "RESEARCH_ONLY_PLAN_NEXT_STAGE_NO_RERANK",
        "target_factor_families": "FUNDAMENTAL;STRATEGY;RISK;MARKET_REGIME",
        "precondition": "Operator-approved or upstream-produced ticker-level numeric candidate factor-family columns.",
        "expected_output": "Complete candidate-level six-family contribution source artifact for later V20.108 rerun.",
        "shadow_rerank_output_created": "FALSE",
        "official_ranking_created": "FALSE",
        **safety(extra=True),
    }]

    status = PARTIAL_STATUS if blocked_count else (PASS_STATUS if ready_paths else BLOCKED_STATUS)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan_rows)
    write_csv(OUT_MAPPING, MAPPING_FIELDS, mapping_rows)
    write_csv(OUT_PROXY, PROXY_FIELDS, proxy_rows)
    write_csv(OUT_BLOCKER, BLOCKER_FIELDS, blocker_rows)
    write_csv(OUT_NEXT, NEXT_FIELDS, next_rows)

    lines = [
        "# V20.108-R3 Candidate Factor-Family Score Materialization Plan",
        "",
        "## Current Result",
        f"- wrapper_status: {status}",
        f"- candidate_count: {candidate_count}",
        f"- factor_family_count: {len(plan_rows)}",
        f"- blocker_count: {len(blocker_rows)}",
        "- final_contribution_scores_created: FALSE",
        "- contribution_scores_fabricated: FALSE",
        "- source_rank_or_score_used_as_contribution: FALSE",
        "- baseline_rank_used_as_contribution: FALSE",
        "- shadow_rerank_output_created: FALSE",
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
    print(f"FACTOR_FAMILY_COUNT={len(plan_rows)}")
    print(f"BLOCKER_COUNT={len(blocker_rows)}")
    print("FINAL_CONTRIBUTION_SCORES_CREATED=FALSE")
    print("CONTRIBUTION_SCORES_FABRICATED=FALSE")
    print("SOURCE_RANK_OR_SCORE_USED_AS_CONTRIBUTION=FALSE")
    print("BASELINE_RANK_USED_AS_CONTRIBUTION=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_PLAN={rel(OUT_PLAN)}")
    print(f"OUTPUT_MAPPING={rel(OUT_MAPPING)}")
    print(f"OUTPUT_PROXY={rel(OUT_PROXY)}")
    print(f"OUTPUT_BLOCKER={rel(OUT_BLOCKER)}")
    print(f"OUTPUT_NEXT_STAGE={rel(OUT_NEXT)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
