#!/usr/bin/env python
"""V20.108-R11 strict equity shadow rerank readiness bridge.

Creates a research-only input bridge for strict six-family equity candidates.
No weighted score, ranking, recommendation, trade action, or shadow rerank
output is created in this stage.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R10_TABLE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
R10_AUDIT = CONSOLIDATION / "V20_108_R10_FACTOR_FAMILY_ASSEMBLY_AUDIT.csv"
R10_VALIDATION = CONSOLIDATION / "V20_108_R10_FACTOR_FAMILY_COMPLETENESS_VALIDATION.csv"
R10_POLICY = CONSOLIDATION / "V20_108_R10_APPLICABILITY_WEIGHT_POLICY_AUDIT.csv"
R10_GATE = CONSOLIDATION / "V20_108_R10_SHADOW_RERANK_READINESS_GATE.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R107_VALIDATION = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_WEIGHT_VALIDATION.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"
V50_PACKET = CONSOLIDATION / "V20_50_CANDIDATE_RESEARCH_DECISION_PACKET.csv"
V48_VIEW = CONSOLIDATION / "V20_48_REFRESHED_CANDIDATE_RESEARCH_VIEW.csv"

OUT_MATRIX = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_MATRIX.csv"
OUT_WEIGHT_AUDIT = CONSOLIDATION / "V20_108_R11_DYNAMIC_WEIGHT_BINDING_AUDIT.csv"
OUT_SCOPE_AUDIT = CONSOLIDATION / "V20_108_R11_STRICT_EQUITY_SCOPE_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R11_SHADOW_RERANK_READINESS_VALIDATION.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R11_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_108_R11_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_READINESS_BRIDGE_REPORT.md"

PASS_STATUS = "PASS_V20_108_R11_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK_READINESS_BRIDGE"
BLOCKED_STATUS = "BLOCKED_V20_108_R11_STRICT_EQUITY_SHADOW_RERANK_INPUT_NOT_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R11_STRICT_EQUITY_READY_MIXED_UNIVERSE_BLOCKED"

FAMILY_ORDER = ["FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"]
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

MATRIX_FIELDS = [
    "ticker", "baseline_rank", "instrument_type",
    "fundamental_contribution", "technical_contribution", "strategy_contribution",
    "risk_contribution", "market_regime_contribution", "data_trust_contribution",
    "fundamental_weight", "technical_weight", "strategy_weight", "risk_weight",
    "market_regime_weight", "data_trust_weight",
    "all_six_family_contributions_present", "all_six_family_weights_present",
    "included_in_strict_equity_shadow_rerank_input",
    "excluded_from_mixed_universe_policy", "preview_only", "source_table",
    "dynamic_weight_source", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
WEIGHT_AUDIT_FIELDS = [
    "factor_family", "contribution_column", "contribution_column_present",
    "shadow_dynamic_weight", "base_research_weight", "weight_source",
    "weight_present", "weight_numeric", "weight_sum_validation_status",
    "active_weight_mutated", "official_weight_created", "binding_status",
    "binding_reason", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "trade_action_created",
    "broker_execution_supported",
]
SCOPE_FIELDS = [
    "ticker", "baseline_rank", "instrument_type", "complete_six_family_contribution",
    "applicable_family_contribution_complete", "fundamental_materialization_status",
    "included_in_strict_equity_scope", "excluded_from_strict_equity_scope",
    "exclusion_reason", "eligible_for_applicability_adjusted_shadow_rerank",
    "applicability_weight_policy_required", "missing_factor_families",
    "non_applicable_factor_families", "source_rank_or_score_used",
    "baseline_rank_used_as_factor_contribution", "fabricated_values_created",
    "proxy_values_activated", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count", "strict_equity_input_candidate_count",
    "excluded_non_equity_or_fund_candidate_count",
    "six_family_contribution_complete_count", "six_family_weight_binding_complete",
    "dynamic_weight_sum", "dynamic_weight_sum_valid",
    "strict_equity_shadow_rerank_input_ready", "mixed_universe_shadow_rerank_ready",
    "applicability_weight_policy_required", "source_rank_or_score_used",
    "baseline_rank_used_as_factor_contribution", "fabricated_values_created",
    "proxy_values_activated", "final_weighted_score_created",
    "shadow_rerank_output_created", "official_ranking_created",
    "authoritative_ranking_overwritten", "validation_status", "validation_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
GATE_FIELDS = [
    "gate_check_id", "strict_equity_shadow_rerank_input_ready",
    "strict_equity_input_candidate_count", "mixed_universe_shadow_rerank_ready",
    "excluded_non_equity_or_fund_candidate_count", "next_stage_allowed",
    "recommended_next_stage", "blocking_reason", "research_only",
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


def decimal_or_none(value: str) -> Decimal | None:
    try:
        return Decimal(clean(value))
    except (InvalidOperation, ValueError):
        return None


def fmt_decimal(value: Decimal) -> str:
    return f"{value:.10f}"


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    return rows[0].get(field, default) if status == "OK" and rows and rows[0].get(field) else default


def load_weights() -> tuple[dict[str, str], dict[str, str]]:
    shadow_rows, _, _ = read_csv(R107_WEIGHTS)
    base_rows, _, _ = read_csv(R98B_WEIGHTS)
    shadow = {row["factor_family"].upper(): row.get("normalized_shadow_dynamic_weight") or row.get("shadow_dynamic_weight", "") for row in shadow_rows if row.get("factor_family")}
    base = {row["factor_family"].upper(): row.get("active_research_base_weight", "") for row in base_rows if row.get("factor_family")}
    return shadow, base


def main() -> int:
    table_rows, table_fields, _ = read_csv(R10_TABLE)
    shadow_weights, base_weights = load_weights()
    contribution_columns_present = all(column in table_fields for column in CONTRIBUTION_COLUMN.values())
    weight_values = [decimal_or_none(shadow_weights.get(family, "")) for family in FAMILY_ORDER]
    weight_sum = sum((value for value in weight_values if value is not None), Decimal("0"))
    weight_sum_valid = len([value for value in weight_values if value is not None]) == 6 and weight_sum == Decimal("1.0000000000")
    weights_complete = contribution_columns_present and weight_sum_valid

    matrix_rows: list[dict[str, str]] = []
    scope_rows: list[dict[str, str]] = []
    strict_count = 0
    excluded_count = 0
    six_complete_count = 0
    input_ready = False

    for row in table_rows:
        all_contrib = all(decimal_or_none(row.get(column, "")) is not None for column in CONTRIBUTION_COLUMN.values())
        if all_contrib:
            six_complete_count += 1
        fundamental_na = row.get("non_applicable_factor_families") == "FUNDAMENTAL" or row.get("applicability_weight_policy_required") == "TRUE"
        included = row.get("eligible_for_strict_six_family_shadow_rerank") == "TRUE" and all_contrib and not fundamental_na
        if included:
            strict_count += 1
        elif fundamental_na:
            excluded_count += 1
        exclusion_reason = ""
        if fundamental_na:
            exclusion_reason = "FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY"
        elif not included:
            exclusion_reason = "NOT_STRICT_SIX_FAMILY_EQUITY_READY"
        scope_rows.append({
            "ticker": row.get("ticker", ""),
            "baseline_rank": row.get("baseline_rank", ""),
            "instrument_type": row.get("instrument_type", ""),
            "complete_six_family_contribution": row.get("complete_six_family_contribution", ""),
            "applicable_family_contribution_complete": row.get("applicable_family_contribution_complete", ""),
            "fundamental_materialization_status": row.get("fundamental_materialization_status", ""),
            "included_in_strict_equity_scope": tf(included),
            "excluded_from_strict_equity_scope": tf(not included),
            "exclusion_reason": "" if included else exclusion_reason,
            "eligible_for_applicability_adjusted_shadow_rerank": row.get("eligible_for_applicability_adjusted_shadow_rerank", "FALSE"),
            "applicability_weight_policy_required": row.get("applicability_weight_policy_required", "FALSE"),
            "missing_factor_families": row.get("missing_factor_families", ""),
            "non_applicable_factor_families": row.get("non_applicable_factor_families", ""),
            "source_rank_or_score_used": row.get("source_rank_or_score_used", "FALSE"),
            "baseline_rank_used_as_factor_contribution": row.get("baseline_rank_used_as_factor_contribution", "FALSE"),
            "fabricated_values_created": row.get("fabricated_values_created", "FALSE"),
            "proxy_values_activated": row.get("proxy_values_activated", "FALSE"),
            **safety(),
        })
        if included:
            matrix = {
                "ticker": row.get("ticker", ""),
                "baseline_rank": row.get("baseline_rank", ""),
                "instrument_type": row.get("instrument_type", ""),
                "all_six_family_contributions_present": tf(all_contrib),
                "all_six_family_weights_present": tf(weights_complete),
                "included_in_strict_equity_shadow_rerank_input": "TRUE",
                "excluded_from_mixed_universe_policy": "TRUE",
                "preview_only": "FALSE",
                "source_table": rel(R10_TABLE),
                "dynamic_weight_source": rel(R107_WEIGHTS),
                **safety(extra=True),
            }
            for family, column in CONTRIBUTION_COLUMN.items():
                matrix[column] = row.get(column, "")
                matrix[WEIGHT_COLUMN[family]] = shadow_weights.get(family, "")
            matrix_rows.append(matrix)

    input_ready = strict_count > 0 and strict_count == six_complete_count and weights_complete
    mixed_ready = False
    policy_required = excluded_count > 0

    weight_audit_rows = []
    validation_rows, _, _ = read_csv(R107_VALIDATION)
    validation_sum_status = validation_rows[0].get("weight_sum_valid", tf(weight_sum_valid)) if validation_rows else tf(weight_sum_valid)
    for family in FAMILY_ORDER:
        weight = shadow_weights.get(family, "")
        parsed = decimal_or_none(weight)
        present = clean(weight) != ""
        numeric = parsed is not None
        binding_ok = contribution_columns_present and present and numeric and weight_sum_valid
        weight_audit_rows.append({
            "factor_family": family,
            "contribution_column": CONTRIBUTION_COLUMN[family],
            "contribution_column_present": tf(CONTRIBUTION_COLUMN[family] in table_fields),
            "shadow_dynamic_weight": weight,
            "base_research_weight": base_weights.get(family, ""),
            "weight_source": rel(R107_WEIGHTS),
            "weight_present": tf(present),
            "weight_numeric": tf(numeric),
            "weight_sum_validation_status": "PASS" if validation_sum_status == "TRUE" and weight_sum_valid else "BLOCKED",
            "active_weight_mutated": "FALSE",
            "official_weight_created": "FALSE",
            "binding_status": "BOUND" if binding_ok else "BLOCKED",
            "binding_reason": "DYNAMIC_WEIGHT_BOUND_TO_CONTRIBUTION_COLUMN" if binding_ok else "MISSING_OR_INVALID_WEIGHT_OR_COLUMN",
            **safety(),
        })

    if input_ready and policy_required:
        wrapper_status = PARTIAL_STATUS
        validation_status = "PASS"
        validation_reason = "STRICT_EQUITY_INPUT_READY_MIXED_UNIVERSE_BLOCKED_BY_APPLICABILITY_POLICY"
        next_allowed = "TRUE"
        next_stage = "V20.108-R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK"
        blocking_reason = "MIXED_UNIVERSE_RERANK_BLOCKED_ETF_FUND_APPLICABILITY_WEIGHT_POLICY_REQUIRED"
    elif input_ready:
        wrapper_status = PASS_STATUS
        validation_status = "PASS"
        validation_reason = "STRICT_EQUITY_INPUT_READY"
        next_allowed = "TRUE"
        next_stage = "V20.108-R12_STRICT_EQUITY_SHADOW_DYNAMIC_WEIGHTED_RERANK"
        blocking_reason = ""
    else:
        wrapper_status = BLOCKED_STATUS
        validation_status = "BLOCKED"
        validation_reason = "STRICT_EQUITY_INPUT_NOT_READY"
        next_allowed = "FALSE"
        next_stage = "V20.108-R11_REPAIR_STRICT_EQUITY_INPUT"
        blocking_reason = "STRICT_EQUITY_INPUT_VALIDATION_FAILED"

    validation_output = [{
        "validation_check_id": "V20_108_R11_READINESS_VALIDATION_001",
        "candidate_count": str(len(table_rows)),
        "strict_equity_input_candidate_count": str(strict_count),
        "excluded_non_equity_or_fund_candidate_count": str(excluded_count),
        "six_family_contribution_complete_count": str(six_complete_count),
        "six_family_weight_binding_complete": tf(weights_complete),
        "dynamic_weight_sum": fmt_decimal(weight_sum),
        "dynamic_weight_sum_valid": tf(weight_sum_valid),
        "strict_equity_shadow_rerank_input_ready": tf(input_ready),
        "mixed_universe_shadow_rerank_ready": tf(mixed_ready),
        "applicability_weight_policy_required": tf(policy_required),
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used_as_factor_contribution": "FALSE",
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "final_weighted_score_created": "FALSE",
        "shadow_rerank_output_created": "FALSE",
        "official_ranking_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
        "is_official_weight": "FALSE",
    }]
    gate_rows = [{
        "gate_check_id": "V20_108_R11_NEXT_STAGE_GATE_001",
        "strict_equity_shadow_rerank_input_ready": tf(input_ready),
        "strict_equity_input_candidate_count": str(strict_count),
        "mixed_universe_shadow_rerank_ready": tf(mixed_ready),
        "excluded_non_equity_or_fund_candidate_count": str(excluded_count),
        "next_stage_allowed": next_allowed,
        "recommended_next_stage": next_stage,
        "blocking_reason": blocking_reason,
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_MATRIX, MATRIX_FIELDS, matrix_rows)
    write_csv(OUT_WEIGHT_AUDIT, WEIGHT_AUDIT_FIELDS, weight_audit_rows)
    write_csv(OUT_SCOPE_AUDIT, SCOPE_FIELDS, scope_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_output)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R11 Strict Equity Shadow Dynamic Weighted Rerank Readiness Bridge Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {len(table_rows)}",
        f"- strict_equity_input_candidate_count: {strict_count}",
        f"- excluded_non_equity_or_fund_candidate_count: {excluded_count}",
        f"- dynamic_weight_sum: {fmt_decimal(weight_sum)}",
        f"- dynamic_weight_sum_valid: {tf(weight_sum_valid)}",
        f"- strict_equity_shadow_rerank_input_ready: {tf(input_ready)}",
        f"- mixed_universe_shadow_rerank_ready: {tf(mixed_ready)}",
        f"- next_stage_allowed: {next_allowed}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- final_weighted_score_created: FALSE",
        "- shadow_rerank_output_created: FALSE",
        "- official_ranking_created: FALSE",
        "- authoritative_ranking_overwritten: FALSE",
        "- source_rank_or_score_used: FALSE",
        "- baseline_rank_used_as_factor_contribution: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "",
        "## Scope Policy",
        "- strict_equity_input: complete six-family equity candidates only",
        "- excluded_non_equity_reason: FUNDAMENTAL_NOT_APPLICABLE_REQUIRES_APPLICABILITY_WEIGHT_POLICY",
        "- mixed_universe_shadow_rerank_ready: FALSE",
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
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"CANDIDATE_COUNT={len(table_rows)}")
    print(f"STRICT_EQUITY_INPUT_CANDIDATE_COUNT={strict_count}")
    print(f"EXCLUDED_NON_EQUITY_OR_FUND_CANDIDATE_COUNT={excluded_count}")
    print(f"DYNAMIC_WEIGHT_SUM={fmt_decimal(weight_sum)}")
    print(f"DYNAMIC_WEIGHT_SUM_VALID={tf(weight_sum_valid)}")
    print(f"STRICT_EQUITY_SHADOW_RERANK_INPUT_READY={tf(input_ready)}")
    print(f"MIXED_UNIVERSE_SHADOW_RERANK_READY={tf(mixed_ready)}")
    print("ACTIVE_RESEARCH_BASE_WEIGHTS_MUTATED=FALSE")
    print("V20_107_SHADOW_DYNAMIC_WEIGHTS_MUTATED=FALSE")
    print("FINAL_WEIGHTED_SCORE_CREATED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_MATRIX={rel(OUT_MATRIX)}")
    print(f"OUTPUT_WEIGHT_AUDIT={rel(OUT_WEIGHT_AUDIT)}")
    print(f"OUTPUT_SCOPE_AUDIT={rel(OUT_SCOPE_AUDIT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
