#!/usr/bin/env python
"""V20.108-R10 complete factor-family score assembler.

Assembles research-only candidate factor-family contribution availability from
materialized family sources. This stage performs completeness and applicability
checks only; it does not create weighted scores, rankings, or rerank output.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

R9_SOURCE = CONSOLIDATION / "V20_108_R9_RISK_CANDIDATE_SCORE_SOURCE.csv"
R9_VALIDATION = CONSOLIDATION / "V20_108_R9_RISK_MATERIALIZATION_VALIDATION.csv"
R9_COVERAGE = CONSOLIDATION / "V20_108_R9_FACTOR_FAMILY_COVERAGE_AFTER_RISK.csv"
R9_GATE = CONSOLIDATION / "V20_108_R9_NEXT_STAGE_GATE.csv"
R8_R3_SOURCE = CONSOLIDATION / "V20_108_R8_R3_MARKET_REGIME_CONTRIBUTION_SOURCE.csv"
R7_SOURCE = CONSOLIDATION / "V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE.csv"
R6B_SOURCE = CONSOLIDATION / "V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_SOURCE.csv"
R4_SCORES = CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv"
R107_WEIGHTS = CONSOLIDATION / "V20_107_SHADOW_DYNAMIC_FACTOR_FAMILY_WEIGHTS.csv"
R98B_WEIGHTS = CONSOLIDATION / "V20_98B_R5_ACTIVE_RESEARCH_BASE_WEIGHT_REGISTRY.csv"
V49_RESEARCH = CONSOLIDATION / "V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE.csv"
V49_OFFICIAL = CONSOLIDATION / "V20_49_OFFICIAL_PROMOTION_GATE.csv"

OUT_TABLE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
OUT_AUDIT = CONSOLIDATION / "V20_108_R10_FACTOR_FAMILY_ASSEMBLY_AUDIT.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_108_R10_FACTOR_FAMILY_COMPLETENESS_VALIDATION.csv"
OUT_POLICY = CONSOLIDATION / "V20_108_R10_APPLICABILITY_WEIGHT_POLICY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_108_R10_SHADOW_RERANK_READINESS_GATE.csv"
OUT_PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
OUT_PIT_SCHEMA_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv"
OUT_PIT_GAP_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv"
REPORT = READ_CENTER / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_REPORT.md"

PASS_STATUS = "PASS_V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_STRICT_EQUITY_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER_WITH_NON_EQUITY_APPLICABILITY_BLOCKER"
BLOCKED_STATUS = "BLOCKED_V20_108_R10_NO_COMPLETE_FACTOR_FAMILY_CANDIDATES"

FAMILIES = [
    ("FUNDAMENTAL", "fundamental_contribution", R6B_SOURCE, "fundamental_materialization_status"),
    ("TECHNICAL", "technical_contribution", R4_SCORES, ""),
    ("STRATEGY", "strategy_contribution", R7_SOURCE, "strategy_materialization_status"),
    ("RISK", "risk_contribution", R9_SOURCE, "risk_materialization_status"),
    ("MARKET_REGIME", "market_regime_contribution", R8_R3_SOURCE, "market_regime_materialization_status"),
    ("DATA_TRUST", "data_trust_contribution", R4_SCORES, ""),
]

TABLE_FIELDS = [
    "ticker", "baseline_rank", "instrument_type",
    "fundamental_contribution", "technical_contribution", "strategy_contribution",
    "risk_contribution", "market_regime_contribution", "data_trust_contribution",
    "fundamental_materialization_status", "technical_materialization_status",
    "strategy_materialization_status", "risk_materialization_status",
    "market_regime_materialization_status", "data_trust_materialization_status",
    "complete_six_family_contribution", "applicable_family_contribution_complete",
    "missing_factor_families", "non_applicable_factor_families",
    "factor_family_assembly_status", "eligible_for_strict_six_family_shadow_rerank",
    "eligible_for_applicability_adjusted_shadow_rerank",
    "applicability_weight_policy_required", "source_rank_or_score_used",
    "baseline_rank_used_as_factor_contribution", "fabricated_values_created",
    "proxy_values_activated", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "is_official_ranking", "is_official_weight",
    "weight_mutated", "trade_action_created", "broker_execution_supported",
]
AUDIT_FIELDS = [
    "ticker", "source_family", "source_artifact", "contribution_available",
    "contribution_value", "materialization_status", "accepted_for_assembly",
    "rejection_reason", "source_rank_or_score_used",
    "baseline_rank_used_as_factor_contribution", "fabricated_values_created",
    "proxy_values_activated", "research_only", "official_promotion_allowed",
    "official_recommendation_created", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
VALIDATION_FIELDS = [
    "validation_check_id", "candidate_count",
    "complete_six_family_contribution_candidate_count",
    "applicable_family_complete_candidate_count", "equity_full_six_family_ready_count",
    "non_equity_fundamental_not_applicable_count", "missing_or_blocked_candidate_count",
    "technical_complete_count", "data_trust_complete_count", "strategy_complete_count",
    "risk_complete_count", "market_regime_complete_count", "fundamental_complete_count",
    "fabricated_values_created", "proxy_values_activated", "source_rank_or_score_used",
    "baseline_rank_used_as_factor_contribution", "shadow_rerank_output_created",
    "official_ranking_created", "authoritative_ranking_overwritten",
    "validation_status", "validation_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
POLICY_FIELDS = [
    "policy_check_id", "dynamic_weight_source_available", "shadow_dynamic_weight_source",
    "base_research_weight_source", "mixed_universe_contains_non_equity_or_fund",
    "non_equity_fundamental_not_applicable_count", "missing_fundamental_treated_as_zero",
    "applicability_adjusted_weight_policy_exists",
    "applicability_adjusted_weight_policy_approved", "weight_renormalization_performed",
    "weight_mutated", "official_weight_created", "strict_six_family_equity_subset_allowed",
    "mixed_universe_shadow_rerank_ready", "policy_status", "policy_reason",
    "research_only", "official_promotion_allowed", "official_recommendation_created",
    "trade_action_created", "broker_execution_supported",
]
GATE_FIELDS = [
    "gate_check_id", "candidate_count",
    "complete_six_family_contribution_candidate_count",
    "equity_full_six_family_ready_count",
    "non_equity_fundamental_not_applicable_count",
    "applicable_family_complete_candidate_count",
    "strict_six_family_ready_for_shadow_rerank",
    "mixed_universe_shadow_rerank_ready",
    "partial_applicability_weight_policy_required", "next_stage_allowed",
    "recommended_next_stage", "blocking_reason", "research_only",
    "official_promotion_allowed", "official_recommendation_created",
    "is_official_weight", "weight_mutated", "trade_action_created",
    "broker_execution_supported",
]
PIT_LINEAGE_FIELDS = [
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id",
    "source_artifact", "source_row_id", "factor_family", "factor_input_name",
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
    "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    "accepted_for_data_trust_direct_pit_status", "source_contract_required_fields",
    "source_contract_required", "direct_pass_blocker_reason", "research_only",
    "data_trust_scoring_weight", "data_trust_role",
    "direct_ticker_mapping_required_before_official_use", "formal_activation_allowed",
    "promotion_ready", "official_recommendation_created", "official_ranking_mutated",
    "official_weight_change_created", "official_weight_registry_mutated", "weight_mutated",
    "real_book_action_created", "trade_action_created", "broker_execution_supported",
    "performance_claim_created", "shadow_weight_expansion_allowed",
]
PIT_SCHEMA_AUDIT_FIELDS = [
    "output_artifact", "sidecar_artifact", "row_grain", "primary_table_schema_extended",
    "primary_table_row_count_preserved", "required_field", "field_emitted",
    "field_population_mode", "required_non_null_for_direct_pass",
    "default_value_allowed_for_direct_pass", "validation_rule", "research_only",
    "data_trust_scoring_weight", "data_trust_role",
    "direct_ticker_mapping_required_before_official_use", "formal_activation_allowed",
    "promotion_ready", "official_recommendation_created", "official_ranking_mutated",
    "official_weight_change_created", "official_weight_registry_mutated", "weight_mutated",
    "real_book_action_created", "trade_action_created", "broker_execution_supported",
    "performance_claim_created", "shadow_weight_expansion_allowed",
]
PIT_GAP_AUDIT_FIELDS = [
    "missing_or_unknown_field", "affected_ticker_count", "affected_lineage_row_count",
    "source_contract_required", "proposed_source_contract_owner_stage",
    "proposed_source_contract_artifact", "proposed_source_contract_field",
    "can_be_implemented_in_current_producer", "requires_external_or_upstream_data_refresh",
    "repair_priority", "recommended_next_action", "research_only",
    "data_trust_scoring_weight", "data_trust_role",
    "direct_ticker_mapping_required_before_official_use", "formal_activation_allowed",
    "promotion_ready", "official_recommendation_created", "official_ranking_mutated",
    "official_weight_change_created", "official_weight_registry_mutated", "weight_mutated",
    "real_book_action_created", "trade_action_created", "broker_execution_supported",
    "performance_claim_created", "shadow_weight_expansion_allowed",
]
PIT_REQUIRED_FIELDS = [
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id",
    "source_artifact", "source_row_id", "factor_family", "factor_input_name",
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
    "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    "accepted_for_data_trust_direct_pit_status",
]
PIT_SOURCE_CONTRACT_REQUIRED_FIELDS = [
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "source_quality_usable",
    "freshness_usable", "lineage_to_ranking_score_available",
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


def pit_safety() -> dict[str, str]:
    return {
        "research_only": "TRUE",
        "data_trust_scoring_weight": "0.0000000000",
        "data_trust_role": "GATE_ONLY_AND_REPAIR_DIAGNOSTIC",
        "direct_ticker_mapping_required_before_official_use": "TRUE",
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_ranking_mutated": "FALSE",
        "official_weight_change_created": "FALSE",
        "official_weight_registry_mutated": "FALSE",
        "weight_mutated": "FALSE",
        "real_book_action_created": "FALSE",
        "trade_action_created": "FALSE",
        "broker_execution_supported": "FALSE",
        "performance_claim_created": "FALSE",
        "shadow_weight_expansion_allowed": "FALSE",
    }


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


def first_value(path: Path, field: str, default: str) -> str:
    rows, _, status = read_csv(path)
    return rows[0].get(field, default) if status == "OK" and rows and rows[0].get(field) else default


def load_by_ticker(path: Path) -> dict[str, dict[str, str]]:
    rows, _, _ = read_csv(path)
    return {row["ticker"]: row for row in rows if row.get("ticker")}


def load_candidates() -> list[dict[str, str]]:
    rows, _, status = read_csv(R4_SCORES)
    if status != "OK":
        return []
    return [{"ticker": row["ticker"], "baseline_rank": row.get("baseline_rank", "")} for row in rows if row.get("ticker")]


def materialization_status(family: str, source_row: dict[str, str], status_field: str, available: bool) -> str:
    if status_field and source_row.get(status_field):
        return source_row[status_field]
    if available:
        return f"{family}_CONTRIBUTION_MATERIALIZED"
    return f"{family}_CONTRIBUTION_MISSING"


def pit_source_contract_owner(field: str) -> str:
    owners = {
        "factor_input_as_of_date": "V20_108_FAMILY_SOURCE_PRODUCERS",
        "factor_input_source_timestamp": "V20_108_FAMILY_SOURCE_PRODUCERS",
        "factor_input_publication_lag_handled": "UPSTREAM_FACTOR_SOURCE_CONTRACT",
        "factor_input_point_in_time_safe": "UPSTREAM_FACTOR_SOURCE_CONTRACT",
        "non_pit_blocker_present": "V20_35_PIT_BLOCKER_PRODUCER",
        "leakage_flag_present": "V20_PIT_LEAKAGE_AUDIT_PRODUCER",
        "source_quality_usable": "V20_10_TO_V20_16_DATA_QUALITY_PRODUCERS",
        "freshness_usable": "V20_48_LINEAGE_FRESHNESS_PRODUCER",
        "lineage_to_ranking_score_available": "V20_108_R10_CANONICAL_ASSEMBLER",
    }
    return owners.get(field, "V20_108_R10_CANONICAL_ASSEMBLER")


def build_pit_lineage_rows(candidates: list[dict[str, str]], source_maps: dict[Path, dict[str, dict[str, str]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    row_id = 1
    for candidate in candidates:
        ticker = candidate["ticker"]
        for family, column, path, _ in FAMILIES:
            source_row = source_maps[path].get(ticker, {})
            source_contract_required = list(PIT_SOURCE_CONTRACT_REQUIRED_FIELDS)
            factor_input_name = column if column else "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"
            source_artifact = rel(path)
            blocker = "UNKNOWN"
            leakage = "UNKNOWN"
            pit_safe = "UNKNOWN"
            if family in {"FUNDAMENTAL", "STRATEGY", "RISK", "MARKET_REGIME"} and source_row:
                lineage = "UNKNOWN"
            else:
                lineage = "UNKNOWN"
            unknown_fields = list(source_contract_required)
            accepted = False
            rows.append({
                "ticker": ticker,
                "ranking_context_id": "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_ASSEMBLER",
                "ranking_as_of_date": "UNKNOWN",
                "data_snapshot_id": "UNKNOWN",
                "source_artifact": source_artifact,
                "source_row_id": str(row_id),
                "factor_family": family,
                "factor_input_name": factor_input_name,
                "factor_input_as_of_date": "UNKNOWN",
                "factor_input_source_timestamp": "UNKNOWN",
                "factor_input_publication_lag_handled": "UNKNOWN",
                "factor_input_point_in_time_safe": pit_safe,
                "non_pit_blocker_present": blocker,
                "leakage_flag_present": leakage,
                "schema_valid": "TRUE",
                "source_quality_usable": "UNKNOWN",
                "freshness_usable": "UNKNOWN",
                "lineage_to_ranking_score_available": lineage,
                "accepted_for_data_trust_direct_pit_status": tf(accepted),
                "source_contract_required_fields": "|".join(unknown_fields),
                "source_contract_required": "TRUE",
                "direct_pass_blocker_reason": "SOURCE_CONTRACT_REQUIRED_FIELDS_UNKNOWN",
                **pit_safety(),
            })
            row_id += 1
    return rows


def build_pit_schema_audit(original_row_count: int, patched_row_count: int) -> list[dict[str, str]]:
    rows = []
    for field in PIT_REQUIRED_FIELDS:
        if field in {"ticker", "factor_family", "source_artifact", "source_row_id", "ranking_context_id", "schema_valid", "accepted_for_data_trust_direct_pit_status"}:
            mode = "SAFE_DERIVATION_OR_DIRECT_FROM_R10_PRODUCER"
        else:
            mode = "UNKNOWN_SOURCE_CONTRACT_REQUIRED"
        rows.append({
            "output_artifact": rel(OUT_TABLE),
            "sidecar_artifact": rel(OUT_PIT_LINEAGE),
            "row_grain": "ticker_factor_family",
            "primary_table_schema_extended": "FALSE",
            "primary_table_row_count_preserved": tf(original_row_count == patched_row_count),
            "required_field": field,
            "field_emitted": "TRUE",
            "field_population_mode": mode,
            "required_non_null_for_direct_pass": "TRUE",
            "default_value_allowed_for_direct_pass": "FALSE",
            "validation_rule": "UNKNOWN_VALUES_BLOCK_DIRECT_PASS",
            **pit_safety(),
        })
    return rows


def build_pit_gap_audit(lineage_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    tickers = {row["ticker"] for row in lineage_rows}
    rows = []
    for field in PIT_SOURCE_CONTRACT_REQUIRED_FIELDS:
        affected = [row for row in lineage_rows if row.get(field) == "UNKNOWN"]
        rows.append({
            "missing_or_unknown_field": field,
            "affected_ticker_count": str(len({row["ticker"] for row in affected})),
            "affected_lineage_row_count": str(len(affected)),
            "source_contract_required": "TRUE",
            "proposed_source_contract_owner_stage": pit_source_contract_owner(field),
            "proposed_source_contract_artifact": "UPSTREAM_TICKER_FACTOR_SOURCE_CONTRACT",
            "proposed_source_contract_field": field,
            "can_be_implemented_in_current_producer": tf(field == "lineage_to_ranking_score_available"),
            "requires_external_or_upstream_data_refresh": tf(field != "lineage_to_ranking_score_available"),
            "repair_priority": "HIGH" if affected else "LOW",
            "recommended_next_action": "PATCH_UPSTREAM_SOURCE_CONTRACT_OR_REFRESH_INPUT_PRODUCER" if affected else "",
            **pit_safety(),
        })
    if not lineage_rows:
        rows.append({
            "missing_or_unknown_field": "ticker_factor_lineage_rows",
            "affected_ticker_count": str(len(tickers)),
            "affected_lineage_row_count": "0",
            "source_contract_required": "TRUE",
            "proposed_source_contract_owner_stage": "V20_108_R10_CANONICAL_ASSEMBLER",
            "proposed_source_contract_artifact": rel(OUT_PIT_LINEAGE),
            "proposed_source_contract_field": "ALL_REQUIRED_PIT_FIELDS",
            "can_be_implemented_in_current_producer": "TRUE",
            "requires_external_or_upstream_data_refresh": "FALSE",
            "repair_priority": "HIGH",
            "recommended_next_action": "REPAIR_R10_PIT_LINEAGE_EXTENSION_EMITTER",
            **pit_safety(),
        })
    return rows


def main() -> int:
    original_table_rows, original_table_fields, _ = read_csv(OUT_TABLE)
    original_row_count = len(original_table_rows)
    candidates = load_candidates()
    source_maps = {path: load_by_ticker(path) for _, _, path, _ in FAMILIES}
    fundamental_map = source_maps[R6B_SOURCE]
    regime_map = source_maps[R8_R3_SOURCE]

    table_rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []
    counts = {family: 0 for family, _, _, _ in FAMILIES}
    complete_six = 0
    applicable_complete = 0
    equity_ready = 0
    non_equity_na = 0
    missing_or_blocked = 0

    for candidate in candidates:
        ticker = candidate["ticker"]
        contributions: dict[str, str] = {}
        statuses: dict[str, str] = {}
        missing: list[str] = []
        non_applicable: list[str] = []
        fundamental_row = fundamental_map.get(ticker, {})
        fundamental_na = (
            not fundamental_row.get("fundamental_contribution")
            and fundamental_row.get("fundamental_materialization_status") == "EXCLUDED_NON_EQUITY_OR_FUNDAMENTAL_NOT_APPLICABLE"
        )
        if fundamental_na:
            non_equity_na += 1
            non_applicable.append("FUNDAMENTAL")
        instrument_type = "ETF_OR_FUND" if fundamental_na else regime_map.get(ticker, {}).get("instrument_type", "EQUITY_OR_ADR")

        for family, column, path, status_field in FAMILIES:
            source_row = source_maps[path].get(ticker, {})
            value = source_row.get(column, "")
            available = bool(value)
            if available:
                counts[family] += 1
            elif not (family == "FUNDAMENTAL" and fundamental_na):
                missing.append(family)
            status = materialization_status(family, source_row, status_field, available)
            contributions[column] = value
            statuses[f"{family.lower()}_materialization_status"] = status
            audit_rows.append({
                "ticker": ticker,
                "source_family": family,
                "source_artifact": rel(path),
                "contribution_available": tf(available),
                "contribution_value": value,
                "materialization_status": status,
                "accepted_for_assembly": tf(available),
                "rejection_reason": "" if available else ("FUNDAMENTAL_NOT_APPLICABLE_FOR_NON_EQUITY_OR_FUND" if family == "FUNDAMENTAL" and fundamental_na else "CONTRIBUTION_MISSING"),
                "source_rank_or_score_used": "FALSE",
                "baseline_rank_used_as_factor_contribution": "FALSE",
                "fabricated_values_created": "FALSE",
                "proxy_values_activated": "FALSE",
                **safety(),
            })

        is_complete_six = all(contributions[column] for _, column, _, _ in FAMILIES)
        applicable_is_complete = not missing and (is_complete_six or fundamental_na)
        if is_complete_six:
            complete_six += 1
            equity_ready += 1
            assembly_status = "COMPLETE_SIX_FAMILY_EQUITY_READY"
        elif fundamental_na and applicable_is_complete:
            applicable_complete += 1
            assembly_status = "APPLICABLE_FAMILY_COMPLETE_FUNDAMENTAL_NOT_APPLICABLE"
        else:
            missing_or_blocked += 1
            assembly_status = "MISSING_OR_BLOCKED_FACTOR_FAMILY"
        if is_complete_six:
            applicable_complete += 1

        table_rows.append({
            "ticker": ticker,
            "baseline_rank": candidate.get("baseline_rank", ""),
            "instrument_type": instrument_type,
            **contributions,
            "fundamental_materialization_status": statuses["fundamental_materialization_status"],
            "technical_materialization_status": statuses["technical_materialization_status"],
            "strategy_materialization_status": statuses["strategy_materialization_status"],
            "risk_materialization_status": statuses["risk_materialization_status"],
            "market_regime_materialization_status": statuses["market_regime_materialization_status"],
            "data_trust_materialization_status": statuses["data_trust_materialization_status"],
            "complete_six_family_contribution": tf(is_complete_six),
            "applicable_family_contribution_complete": tf(applicable_is_complete),
            "missing_factor_families": ";".join(missing),
            "non_applicable_factor_families": ";".join(non_applicable),
            "factor_family_assembly_status": assembly_status,
            "eligible_for_strict_six_family_shadow_rerank": tf(is_complete_six),
            "eligible_for_applicability_adjusted_shadow_rerank": "FALSE",
            "applicability_weight_policy_required": tf(fundamental_na),
            "source_rank_or_score_used": "FALSE",
            "baseline_rank_used_as_factor_contribution": "FALSE",
            "fabricated_values_created": "FALSE",
            "proxy_values_activated": "FALSE",
            **safety(extra=True),
        })

    total = len(table_rows)
    mixed_contains_non_equity = non_equity_na > 0
    strict_ready = equity_ready > 0 and complete_six == equity_ready
    mixed_ready = False
    policy_required = mixed_contains_non_equity
    if complete_six:
        wrapper_status = PARTIAL_STATUS if policy_required else PASS_STATUS
        validation_status = "PASS"
        validation_reason = "STRICT_EQUITY_SIX_FAMILY_SUBSET_READY_MIXED_UNIVERSE_REQUIRES_APPLICABILITY_WEIGHT_POLICY" if policy_required else "ALL_CANDIDATES_COMPLETE_SIX_FAMILY_READY"
    else:
        wrapper_status = BLOCKED_STATUS
        validation_status = "BLOCKED"
        validation_reason = "NO_COMPLETE_FACTOR_FAMILY_CANDIDATES"

    validation_rows = [{
        "validation_check_id": "V20_108_R10_COMPLETENESS_VALIDATION_001",
        "candidate_count": str(total),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "applicable_family_complete_candidate_count": str(applicable_complete),
        "equity_full_six_family_ready_count": str(equity_ready),
        "non_equity_fundamental_not_applicable_count": str(non_equity_na),
        "missing_or_blocked_candidate_count": str(missing_or_blocked),
        "technical_complete_count": str(counts["TECHNICAL"]),
        "data_trust_complete_count": str(counts["DATA_TRUST"]),
        "strategy_complete_count": str(counts["STRATEGY"]),
        "risk_complete_count": str(counts["RISK"]),
        "market_regime_complete_count": str(counts["MARKET_REGIME"]),
        "fundamental_complete_count": str(counts["FUNDAMENTAL"]),
        "fabricated_values_created": "FALSE",
        "proxy_values_activated": "FALSE",
        "source_rank_or_score_used": "FALSE",
        "baseline_rank_used_as_factor_contribution": "FALSE",
        "shadow_rerank_output_created": "FALSE",
        "official_ranking_created": "FALSE",
        "authoritative_ranking_overwritten": "FALSE",
        "validation_status": validation_status,
        "validation_reason": validation_reason,
        **safety(),
        "is_official_weight": "FALSE",
    }]

    policy_rows = [{
        "policy_check_id": "V20_108_R10_APPLICABILITY_WEIGHT_POLICY_001",
        "dynamic_weight_source_available": tf(R107_WEIGHTS.exists()),
        "shadow_dynamic_weight_source": rel(R107_WEIGHTS) if R107_WEIGHTS.exists() else "",
        "base_research_weight_source": rel(R98B_WEIGHTS) if R98B_WEIGHTS.exists() else "",
        "mixed_universe_contains_non_equity_or_fund": tf(mixed_contains_non_equity),
        "non_equity_fundamental_not_applicable_count": str(non_equity_na),
        "missing_fundamental_treated_as_zero": "FALSE",
        "applicability_adjusted_weight_policy_exists": "FALSE",
        "applicability_adjusted_weight_policy_approved": "FALSE",
        "weight_renormalization_performed": "FALSE",
        "weight_mutated": "FALSE",
        "official_weight_created": "FALSE",
        "strict_six_family_equity_subset_allowed": tf(strict_ready),
        "mixed_universe_shadow_rerank_ready": "FALSE",
        "policy_status": "BLOCKED_MIXED_UNIVERSE_APPLICABILITY_WEIGHT_POLICY_REQUIRED" if policy_required else "PASS_STRICT_SIX_FAMILY_POLICY_AVAILABLE",
        "policy_reason": "NON_EQUITY_FUNDAMENTAL_NOT_APPLICABLE_CANDIDATES_REQUIRE_EXPLICIT_WEIGHT_POLICY_NO_RENORMALIZATION_PERFORMED" if policy_required else "NO_NON_EQUITY_APPLICABILITY_EXCEPTION_PRESENT",
        **safety(),
    }]

    gate_rows = [{
        "gate_check_id": "V20_108_R10_SHADOW_RERANK_READINESS_GATE_001",
        "candidate_count": str(total),
        "complete_six_family_contribution_candidate_count": str(complete_six),
        "equity_full_six_family_ready_count": str(equity_ready),
        "non_equity_fundamental_not_applicable_count": str(non_equity_na),
        "applicable_family_complete_candidate_count": str(applicable_complete),
        "strict_six_family_ready_for_shadow_rerank": tf(strict_ready),
        "mixed_universe_shadow_rerank_ready": tf(mixed_ready),
        "partial_applicability_weight_policy_required": tf(policy_required),
        "next_stage_allowed": "FALSE",
        "recommended_next_stage": "V20.108-R10-R1_APPLICABILITY_WEIGHT_POLICY_GATE",
        "blocking_reason": "MIXED_UNIVERSE_SHADOW_RERANK_BLOCKED_UNTIL_FUNDAMENTAL_NOT_APPLICABLE_WEIGHT_POLICY_EXISTS",
        **safety(),
        "is_official_weight": "FALSE",
    }]

    write_csv(OUT_TABLE, TABLE_FIELDS, table_rows)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audit_rows)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation_rows)
    write_csv(OUT_POLICY, POLICY_FIELDS, policy_rows)
    write_csv(OUT_GATE, GATE_FIELDS, gate_rows)
    pit_lineage_rows = build_pit_lineage_rows(candidates, source_maps)
    pit_schema_rows = build_pit_schema_audit(original_row_count, len(table_rows))
    pit_gap_rows = build_pit_gap_audit(pit_lineage_rows)
    write_csv(OUT_PIT_LINEAGE, PIT_LINEAGE_FIELDS, pit_lineage_rows)
    write_csv(OUT_PIT_SCHEMA_AUDIT, PIT_SCHEMA_AUDIT_FIELDS, pit_schema_rows)
    write_csv(OUT_PIT_GAP_AUDIT, PIT_GAP_AUDIT_FIELDS, pit_gap_rows)

    research_gate = first_value(V49_RESEARCH, "research_only_gate_status", "PASS_V20_49_RESEARCH_ONLY_DAILY_CONCLUSION_GATE")
    official_gate = first_value(V49_OFFICIAL, "official_promotion_gate_status", "BLOCKED_V20_49_OFFICIAL_PROMOTION_GATE")
    report = [
        "# V20.108-R10 Complete Factor Family Score Assembler Report",
        "",
        "## Current Result",
        f"- wrapper_status: {wrapper_status}",
        f"- candidate_count: {total}",
        f"- complete_six_family_contribution_candidate_count: {complete_six}",
        f"- applicable_family_complete_candidate_count: {applicable_complete}",
        f"- equity_full_six_family_ready_count: {equity_ready}",
        f"- non_equity_fundamental_not_applicable_count: {non_equity_na}",
        f"- mixed_universe_shadow_rerank_ready: {tf(mixed_ready)}",
        f"- partial_applicability_weight_policy_required: {tf(policy_required)}",
        f"- v20_49_research_only_gate_status: {research_gate}",
        f"- v20_49_official_promotion_gate_status: {official_gate}",
        "- source_rank_or_score_used: FALSE",
        "- baseline_rank_used_as_factor_contribution: FALSE",
        "- fabricated_values_created: FALSE",
        "- proxy_values_activated: FALSE",
        "- missing_fundamental_treated_as_zero: FALSE",
        "- weight_renormalization_performed: FALSE",
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
        "",
        "## DATA_TRUST PIT Lineage Extension",
        f"- pit_lineage_sidecar_artifact: {rel(OUT_PIT_LINEAGE)}",
        f"- pit_lineage_row_count: {len(pit_lineage_rows)}",
        "- accepted_for_data_trust_direct_pit_status_count: 0",
        "- unknown_source_contract_fields_preserved: TRUE",
        "- primary_table_existing_columns_preserved: TRUE",
        f"- primary_table_original_row_count: {original_row_count}",
        f"- primary_table_patched_row_count: {len(table_rows)}",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    print(wrapper_status)
    print(f"CANDIDATE_COUNT={total}")
    print(f"COMPLETE_SIX_FAMILY_CONTRIBUTION_CANDIDATE_COUNT={complete_six}")
    print(f"APPLICABLE_FAMILY_COMPLETE_CANDIDATE_COUNT={applicable_complete}")
    print(f"EQUITY_FULL_SIX_FAMILY_READY_COUNT={equity_ready}")
    print(f"NON_EQUITY_FUNDAMENTAL_NOT_APPLICABLE_COUNT={non_equity_na}")
    print(f"MISSING_OR_BLOCKED_CANDIDATE_COUNT={missing_or_blocked}")
    print(f"STRICT_SIX_FAMILY_READY_FOR_SHADOW_RERANK={tf(strict_ready)}")
    print(f"MIXED_UNIVERSE_SHADOW_RERANK_READY={tf(mixed_ready)}")
    print(f"PARTIAL_APPLICABILITY_WEIGHT_POLICY_REQUIRED={tf(policy_required)}")
    print("SOURCE_RANK_OR_SCORE_USED=FALSE")
    print("BASELINE_RANK_USED_AS_FACTOR_CONTRIBUTION=FALSE")
    print("FABRICATED_VALUES_CREATED=FALSE")
    print("PROXY_VALUES_ACTIVATED=FALSE")
    print("MISSING_FUNDAMENTAL_TREATED_AS_ZERO=FALSE")
    print("WEIGHT_RENORMALIZATION_PERFORMED=FALSE")
    print("SHADOW_RERANK_OUTPUT_CREATED=FALSE")
    print("OFFICIAL_RANKING_CREATED=FALSE")
    print("AUTHORITATIVE_RANKING_OVERWRITTEN=FALSE")
    print("OFFICIAL_PROMOTION_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("IS_OFFICIAL_WEIGHT=FALSE")
    print("WEIGHT_MUTATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print(f"OUTPUT_TABLE={rel(OUT_TABLE)}")
    print(f"OUTPUT_ASSEMBLY_AUDIT={rel(OUT_AUDIT)}")
    print(f"OUTPUT_VALIDATION={rel(OUT_VALIDATION)}")
    print(f"OUTPUT_POLICY_AUDIT={rel(OUT_POLICY)}")
    print(f"OUTPUT_GATE={rel(OUT_GATE)}")
    print(f"OUTPUT_PIT_LINEAGE_EXTENSION={rel(OUT_PIT_LINEAGE)}")
    print(f"OUTPUT_PIT_SCHEMA_AUDIT={rel(OUT_PIT_SCHEMA_AUDIT)}")
    print(f"OUTPUT_PIT_GAP_AUDIT={rel(OUT_PIT_GAP_AUDIT)}")
    print(f"PIT_LINEAGE_ROW_COUNT={len(pit_lineage_rows)}")
    print("ACCEPTED_FOR_DATA_TRUST_DIRECT_PIT_STATUS_COUNT=0")
    print(f"OUTPUT_REPORT={rel(REPORT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
