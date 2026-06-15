#!/usr/bin/env python
"""V20.108-R12 strict equity shadow dynamic weighted rerank simulator.

Computes research-only shadow weighted scores and deterministic shadow ranks
for the strict six-family equity input prepared by R11. This stage does not
create official rankings, recommendations, trade actions, broker payloads, or
official weights.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R11_MATRIX = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
R11_WEIGHT_AUDIT = CONSOLIDATION / "V20_108_R11_DYNAMIC_WEIGHT_BINDING_AUDIT.csv"
R11_SCOPE = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
R11_VALIDATION = CONSOLIDATION / "V20_108_R11_SHADOW_RERANK_READINESS_VALIDATION.csv"
R11_GATE = CONSOLIDATION / "V20_108_R11_NEXT_STAGE_GATE.csv"
R10_TABLE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V50_PACKET = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_VIEW = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_RERANK = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK.csv"
OUT_DELTA = CONSOLIDATION / "V20_108_R12_STRICT_EQUITY_SHADOW_RANK_DELTA_AUDIT.csv"
OUT_COMPONENT = CONSOLIDATION / "V20_108_R12_SHADOW_SCORE_COMPONENT_CONTRIBUTION_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R12_SHADOW_RERANK_VALIDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R12_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_REPORT.md"

PASS_STATUS = "PASS_V20_108_R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_SIMULATOR"
BLOCKED_STATUS = "BLOCKED_V20_108_R12_STRICT_EQUITY_SHADOW_RERANK_INPUT_INVALID"

FAMILIES = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
CONTRIBUTION_COLUMN = {
    "FUNDAMENTAL": "fundamental_contribution",
    "TECHNICAL": "technical_contribution",
    "STRATEGY": "strategy_contribution",
    "RISK": "risk_contribution",
    "MARKET_REGIME": "market_regime_contribution",
    "DATA_TRUST": "data_trust_contribution",
}
WEIGHT_COLUMN = {
    "FUNDAMENTAL": "fundamental_weight",
    "TECHNICAL": "technical_weight",
    "STRATEGY": "strategy_weight",
    "RISK": "risk_weight",
    "MARKET_REGIME": "market_regime_weight",
    "DATA_TRUST": "data_trust_weight",
}

RERANK_FIELDS = [
    "ticker", "baseline_rank", "strict_equity_shadow_rank", "shadow_rank_delta",
    "shadow_rank_delta_direction", "shadow_dynamic_weighted_score",
    "fundamental_contribution", "technical_contribution", "strategy_contribution",
    "risk_contribution", "market_regime_contribution", "data_trust_contribution",
    "fundamental_weight", "technical_weight", "strategy_weight", "risk_weight",
    "market_regime_weight", "data_trust_weight",
    "all_six_family_contributions_present", "all_six_family_weights_present",
    "strict_equity_rerank_scope", "excluded_from_mixed_universe_policy",
    "tie_breaker_used", "shadow_rerank_scope", "shadow_rerank_source_stage",
    "dynamic_weight_source", "research_only", "shadow_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_ranking", "is_official_weight", "weight_mutated",
    "trade_action_created", "broker_execution_supported",
]
DELTA_FIELDS = [
    "ticker", "baseline_rank", "strict_equity_shadow_rank", "shadow_rank_delta",
    "shadow_rank_delta_direction", "baseline_rank_source", "shadow_rank_source",
    "rank_delta_reason_available", "top_positive_component_family",
    "top_negative_component_family", "audit_status", "audit_reason",
    "research_only", "shadow_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
COMPONENT_FIELDS = [
    "ticker", "factor_family", "contribution_value", "shadow_dynamic_weight",
    "weighted_component_contribution", "contribution_available", "weight_available",
    "component_used_in_score", "component_source_stage", "component_source_artifact",
    "fabricated_values_created", "proxy_values_activated",
    "source_rank_or_score_used", "baseline_rank_used_as_factor_contribution",
    "research_only", "shadow_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "input_candidate_count", "output_candidate_count",
    "excluded_non_equity_or_fund_candidate_count", "dynamic_weight_sum",
    "dynamic_weight_sum_valid", "all_required_factor_families_present",
    "all_required_weights_present", "all_candidates_scored",
    "duplicate_shadow_rank_count", "missing_shadow_rank_count",
    "source_rank_or_score_used", "baseline_rank_used_as_factor_contribution",
    "fabricated_values_created", "proxy_values_activated",
    "shadow_dynamic_weighted_score_created",
    "strict_equity_shadow_rerank_output_created",
    "mixed_universe_shadow_rerank_output_created", "official_ranking_created",
    "official_recommendation_created", "authoritative_ranking_overwritten",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
    "validation_status", "validation_reason", "research_only", "shadow_only",
    "official_promotion_allowed", "is_official_weight",
]
GATE_FIELDS = [
    "gate_check_id", "strict_equity_shadow_rerank_created",
    "strict_equity_shadow_rerank_candidate_count",
    "mixed_universe_shadow_rerank_created",
    "excluded_non_equity_or_fund_candidate_count",
    "shadow_rerank_validation_passed", "next_stage_allowed",
    "recommended_next_stage", "blocking_reason", "research_only", "shadow_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def safety(extra: bool = False) -> dict[str, str]:
    row = {
        "research_only": "TRUE",
        "shadow_only": "TRUE",
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


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists() or path.stat().st_size == 0:
        return [], [], "MISSING_OR_EMPTY"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: clean(value) for key, value in row.items()} for row in reader]
    return rows, fields, "OK" if fields else "MALFORMED"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def dec(value: str) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP))


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    return rows[0].get(field, default) if status == "OK" and rows and rows[0].get(field) else default


def component_sources() -> dict[str, tuple[str, str]]:
    return {
        "FUNDAMENTAL": ("V20.108-R6B", "outputs/v20/consolidation/V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"),
        "TECHNICAL": ("V20.108-R4", "outputs/v20/consolidation/V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"),
        "STRATEGY": ("V20.108-R7", "outputs/v20/consolidation/V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"),
        "RISK": ("V20.108-R9", "outputs/v20/consolidation/V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv"),
        "MARKET_REGIME": ("V20.108-R8-R3", "outputs/v20/consolidation/V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv"),
        "DATA_TRUST": ("V20.108-R4", "outputs/v20/consolidation/V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"),
    }


def main() -> int:
    input_rows, input_fields, input_status = read_csv(R11_MATRIX)
    scope_rows, _, _ = read_csv(R11_SCOPE)
    excluded_count = sum(1 for row in scope_rows if row.get("exclusion_reason") == "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY")
    required_contribution_present = all(CONTRIBUTION_COLUMN[family] in input_fields for family in FAMILIES)
    required_weight_present = all(WEIGHT_COLUMN[family] in input_fields for family in FAMILIES)
    weight_sum = Decimal("0")
    if input_rows:
        for family in FAMILIES:
            value = dec(input_rows[0].get(WEIGHT_COLUMN[family], ""))
            if value is not None:
                weight_sum += value
    weight_sum_valid = weight_sum == Decimal("1.0000000000")
    valid_input = input_status == "OK" and len(input_rows) == 297 and required_contribution_present and required_weight_present and weight_sum_valid

    scored: list[dict[str, object]] = []
    component_rows: list[dict[str, str]] = []
    sources = component_sources()
    for row in input_rows:
        components: dict[str, Decimal] = {}
        all_values = True
        for family in FAMILIES:
            contribution = dec(row.get(CONTRIBUTION_COLUMN[family], ""))
            weight = dec(row.get(WEIGHT_COLUMN[family], ""))
            used = contribution is not None and weight is not None
            if not used:
                all_values = False
            weighted = (contribution or Decimal("0")) * (weight or Decimal("0"))
            components[family] = weighted
            stage, artifact = sources[family]
            component_rows.append({
                "ticker": row.get("ticker", ""),
                "factor_family": family,
                "contribution_value": row.get(CONTRIBUTION_COLUMN[family], ""),
                "shadow_dynamic_weight": row.get(WEIGHT_COLUMN[family], ""),
                "weighted_component_contribution": fmt(weighted),
                "contribution_available": tf(contribution is not None),
                "weight_available": tf(weight is not None),
                "component_used_in_score": tf(used and valid_input),
                "component_source_stage": stage,
                "component_source_artifact": artifact,
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                "source_rank_or_score_used": "FALSE",
                "baseline_rank_used_as_factor_contribution": "FALSE",
                **safety(),
            })
        score = sum(components.values(), Decimal("0"))
        baseline = dec(row.get("baseline_rank", "")) or Decimal("999999")
        risk = dec(row.get("risk_contribution", "")) or Decimal("0")
        trust = dec(row.get("data_trust_contribution", "")) or Decimal("0")
        scored.append({
            "row": row,
            "score": score,
            "risk": risk,
            "trust": trust,
            "baseline": baseline,
            "components": components,
            "all_values": all_values,
        })

    scored.sort(key=lambda item: (-item["score"], -item["risk"], -item["trust"], item["baseline"], clean(item["row"].get("ticker", ""))))
    rerank_rows: list[dict[str, str]] = []
    delta_rows: list[dict[str, str]] = []
    seen_ranks: set[int] = set()
    missing_rank_count = 0
    for index, item in enumerate(scored, start=1):
        row = item["row"]
        seen_ranks.add(index)
        baseline_rank = int(item["baseline"])
        delta = baseline_rank - index
        direction = "IMPROVED" if delta > 0 else "WORSENED" if delta < 0 else "UNCHANGED"
        components: dict[str, Decimal] = item["components"]
        top_positive = max(components.items(), key=lambda pair: (pair[1], pair[0]))[0]
        top_negative = min(components.items(), key=lambda pair: (pair[1], pair[0]))[0]
        common = {
            "ticker": row.get("ticker", ""),
            "baseline_rank": row.get("baseline_rank", ""),
            "strict_equity_shadow_rank": str(index),
            "shadow_rank_delta": str(delta),
            "shadow_rank_delta_direction": direction,
        }
        rerank_rows.append({
            **common,
            "shadow_dynamic_weighted_score": fmt(item["score"]),
            **{CONTRIBUTION_COLUMN[family]: row.get(CONTRIBUTION_COLUMN[family], "") for family in FAMILIES},
            **{WEIGHT_COLUMN[family]: row.get(WEIGHT_COLUMN[family], "") for family in FAMILIES},
            "all_six_family_contributions_present": row.get("all_six_family_contributions_present", "FALSE"),
            "all_six_family_weights_present": row.get("all_six_family_weights_present", "FALSE"),
            "strict_equity_rerank_scope": "STRICT_EQUITY_SIX_FAMILY_ONLY",
            "excluded_from_mixed_universe_policy": "TRUE",
            "tie_breaker_used": "score_desc;risk_desc;data_trust_desc;baseline_rank_asc;ticker_asc",
            "shadow_rerank_scope": "RESEARCH_ONLY_STRICT_EQUITY_SHADOW",
            "shadow_rerank_source_stage": "V20.108-R12",
            "dynamic_weight_source": rel(R107_WEIGHTS),
            **safety(extra=True),
        })
        delta_rows.append({
            **common,
            "baseline_rank_source": rel(R11_MATRIX),
            "shadow_rank_source": rel(OUT_RERANK),
            "rank_delta_reason_available": "TRUE",
            "top_positive_component_family": top_positive,
            "top_negative_component_family": top_negative,
            "audit_status": "PASS",
            "audit_reason": "STRICT_EQUITY_SHADOW_RANK_DELTA_COMPUTED_FOR_RESEARCH_ONLY",
            **safety(),
        })
    duplicate_rank_count = len(rerank_rows) - len(seen_ranks)
    all_scored = valid_input and len(rerank_rows) == len(input_rows) and all(item["all_values"] for item in scored)
    validation_passed = all_scored and duplicate_rank_count == 0 and missing_rank_count == 0
    wrapper_status = PASS_STATUS if validation_passed else BLOCKED_STATUS

    validation_rows = [{
        "validation_check_id": "V20_108_R12_SHADOW_RERANK_VALIDATION_001",
        "input_candidate_count": str(len(input_rows)),
        "output_candidate_count": str(len(rerank_rows)),
        "excluded_non_equity_or_fund_candidate_count": str(excluded_count),
        "dynamic_weight_sum": fmt(weight_sum),
        "dynamic_weight_sum_valid": tf(weight_sum_valid),
        "all_required_factor_families_present": tf(required_contribution_present),
        "all_required_weights_present": tf(required_weight_present),
        "all_candidates_scored": tf(all_scored),
        "duplicate_shadow_rank_count": str(duplicate_rank_count),
        "missing_shadow_rank_count": str(missing_rank_count),
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used_as_factor_contribution": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "shadow_dynamic_weighted_score_created": tf(validation_passed),
        "strict_equity_shadow_rerank_output_created": tf(validation_passed),
        "mixed_universe_shadow_rerank_output_created": "FALSE",
        "official_ranking_created": "FALSE",
        "official_recommendation_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "weight_mutated": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "validation_status": "PASS" if validation_passed else "BLOCKED",
        "validation_reason": "STRICT_EQUITY_RESEARCH_ONLY_SHADOW_RERANK_CREATED" if validation_passed else "STRICT_EQUITY_INPUT_INVALID",
        **safety(),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_108_R12_NEXT_STAGE_GATE_001",
        "strict_equity_shadow_rerank_created": tf(validation_passed),
        "strict_equity_shadow_rerank_candidate_count": str(len(rerank_rows)),
        "mixed_universe_shadow_rerank_created": "FALSE",
        "excluded_non_equity_or_fund_candidate_count": str(excluded_count),
        "shadow_rerank_validation_passed": tf(validation_passed),
        "next_stage_allowed": tf(validation_passed),
        "recommended_next_stage": "V20.108-R13_SHADOW_RERANK_RESEARCH_REVIEW_GATE" if validation_passed else "V20.108-R12_INPUT_REPAIR",
        "blocking_reason": "MIXED_UNIVERSE_RERANK_STILL_BLOCKED_BY_APPLICABILITY_WEIGHT_POLICY" if validation_passed else "STRICT_EQUITY_SHADOW_RERANK_VALIDATION_FAILED",
        **safety(extra=True),
    }]

    write_csv(OUT_RERANK, RERANK_FIELDS, rerank_rows)
    write_csv(OUT_DELTA, DELTA_FIELDS, delta_rows)
    write_csv(OUT_COMPONENT, COMPONENT_FIELDS, component_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R12 Strict Equity Shadow Dynamic Weighted Rerank Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- input_candidate_count: {len(input_rows)}",
        f"- output_candidate_count: {len(rerank_rows)}",
        f"- excluded_non_equity_or_fund_candidate_count: {excluded_count}",
        f"- dynamic_weight_sum: {fmt(weight_sum)}",
        f"- dynamic_weight_sum_valid: {tf(weight_sum_valid)}",
        f"- strict_equity_shadow_rerank_output_created: {tf(validation_passed)}",
        "- mixed_universe_shadow_rerank_output_created: FALSE",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- official_ranking_created: FALSE",
        "- official_recommendation_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "- weight_mutated: FALSE",
        "- trade_action_created: FALSE",
        "- broker_execution_supported: FALSE",
        "",
        "## Ranking Scope",
        "- scope: research-only strict equity six-family candidates",
        "- excluded: ETF/fund/non-equity candidates pending applicability weight policy",
        "- tie_breakers: score desc, risk desc, data trust desc, baseline rank asc, ticker asc",
        "",
        "## Safety Boundary",
        "- research_only: TRUE",
        "- shadow_only: TRUE",
        "- official_promotion_allowed: FALSE",
        "- is_official_ranking: FALSE",
        "- is_official_weight: FALSE",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"INPUT_CANDIDATE_COUNT={len(input_rows)}")
    print(f"OUTPUT_CANDIDATE_COUNT={len(rerank_rows)}")
    print(f"EXCLUDED_NON_EQUITY_OR_FUND_CANDIDATE_COUNT={excluded_count}")
    print(f"DYNAMIC_WEIGHT_SUM={fmt(weight_sum)}")
    print(f"DYNAMIC_WEIGHT_SUM_VALID={tf(weight_sum_valid)}")
    print(f"ALL_CANDIDATES_SCORED={tf(all_scored)}")
    print(f"DUPLICATE_SHADOW_RANK_COUNT={duplicate_rank_count}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print(f"SHADOW_DYNAMIC_WEIGHTED_SCORE_CREATED={tf(validation_passed)}")
    print(f"STRICT_EQUITY_SHADOW_RERANK_OUTPUT_CREATED={tf(validation_passed)}")
    print("MIXED_UNIVERSE_SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print(f"OUTPUT_RERANK={rel(OUT_RERANK)}")
    print(f"OUTPUT_DELTA_AUDIT={rel(OUT_DELTA)}")
    print(f"OUTPUT_COMPONENT_AUDIT={rel(OUT_COMPONENT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
