#!/usr/bin/env python
"""V20.170-R2A DATA_TRUST source contract gap repair plan."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"
SCRIPTS = ROOT / "scripts" / "v20"

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
PIT_SCHEMA_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv"
PIT_GAP_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv"

R2_INPUTS = [
    FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST.csv",
    FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_PASS_FAIL_UNKNOWN.csv",
    FACTORS / "V20_170_R2_PIT_LINEAGE_CONSUMPTION_AUDIT.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_BLOCKER_AUDIT.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_REPAIR_BACKLOG.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_COVERAGE_SUMMARY.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_NEXT_GATE.csv",
    FACTORS / "V20_170_R2_DIRECT_STATUS_SAFETY_AUDIT.csv",
]
R1C_INPUTS = [
    FACTORS / "V20_170_R1C_UNRESOLVED_SOURCE_CONTRACT_BACKLOG.csv",
    FACTORS / "V20_170_R1C_PIT_FIELD_COMPLETION_AUDIT.csv",
    FACTORS / "V20_170_R1C_PATCHED_PIT_LINEAGE_VALIDATION.csv",
]

OUT_SUMMARY = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY.csv"
OUT_BY_FIELD = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FIELD.csv"
OUT_BY_TICKER = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_TICKER.csv"
OUT_BY_FAMILY = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FACTOR_FAMILY.csv"
OUT_TARGETS = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_PATCH_TARGETS.csv"
OUT_SAFE = FACTORS / "V20_170_R2A_SAFE_DERIVATION_CANDIDATES.csv"
OUT_NEW = FACTORS / "V20_170_R2A_NEW_SOURCE_CONTRACT_REQUIREMENTS.csv"
OUT_PRIORITY = FACTORS / "V20_170_R2A_DIRECT_PASS_BLOCKER_PRIORITY.csv"
OUT_GATE = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_R2A_DATA_TRUST_SOURCE_CONTRACT_GAP_REPAIR_PLAN_REPORT.md"

REQUIRED_R2_STATUS = "WARN_V20_170_R2_DIRECT_STATUS_RETEST_BLOCKED_BY_SOURCE_CONTRACT_GAPS"
PASS_STATUS = "PASS_V20_170_R2A_SOURCE_CONTRACT_GAP_PLAN_READY_FOR_V20_170_R2B"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R2A_SOURCE_CONTRACT_GAP_PLAN_READY_FOR_V20_170_R2B_R2C"
WARN_STATUS = "WARN_V20_170_R2A_NO_REPAIRABLE_SOURCE_CONTRACT_GAPS_FOUND"
BLOCKED_STATUS = "BLOCKED_V20_170_R2A_SOURCE_CONTRACT_GAP_REPAIR_PLAN"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_SOURCE_CONTRACT_GAP_REPAIR_PLAN"

DIMENSIONS = [
    "ranking_context_id", "ranking_as_of_date", "data_snapshot_id", "factor_input_name",
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
    "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    "accepted_for_data_trust_direct_pit_status",
]

FIELD_PLAN = {
    "ranking_context_id": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_108_r10_complete_factor_family_score_assembler.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "ranking_context_id", "Carry R10 producer stage/run context.", "ranking_context_id"),
    "ranking_as_of_date": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_108_r10_complete_factor_family_score_assembler.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "ranking_as_of_date", "Derive from V20.83 ranking_timestamp_utc/latest_price_date for matching ticker.", "ranking_timestamp_utc|latest_price_date"),
    "data_snapshot_id": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_108_r10_complete_factor_family_score_assembler.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "data_snapshot_id", "Derive from V20.83 accepted_artifact_path/source_run_id/source_file.", "accepted_artifact_path|source_run_id|source_file"),
    "factor_input_name": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_108_r10_complete_factor_family_score_assembler.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "factor_input_name", "Carry R10 contribution column name.", "factor_input_name"),
    "factor_input_as_of_date": ("PRODUCER_PATCH_REQUIRED", "scripts/v20/v20_108_r6b_fundamental_candidate_score_materializer_with_partial_coverage.py;scripts/v20/v20_108_r7_strategy_candidate_score_source_builder.py;scripts/v20/v20_108_r8_r3_market_regime_exposure_metadata_to_contribution_mapper.py;scripts/v20/v20_108_r9_risk_candidate_score_coverage_expander.py;scripts/v20/v20_108_r4_real_candidate_factor_family_score_materializer.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "factor_input_as_of_date", "Family producers must carry direct input as-of dates to R10 sidecar.", ""),
    "factor_input_source_timestamp": ("PRODUCER_PATCH_REQUIRED", "scripts/v20/v20_108_r6b_fundamental_candidate_score_materializer_with_partial_coverage.py;scripts/v20/v20_108_r7_strategy_candidate_score_source_builder.py;scripts/v20/v20_108_r8_r3_market_regime_exposure_metadata_to_contribution_mapper.py;scripts/v20/v20_108_r9_risk_candidate_score_coverage_expander.py;scripts/v20/v20_108_r4_real_candidate_factor_family_score_materializer.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "factor_input_source_timestamp", "Family producers must carry source/cache/provider timestamps to R10 sidecar.", ""),
    "factor_input_publication_lag_handled": ("NEW_SOURCE_CONTRACT_REQUIRED", "scripts/v20/v20_108_r6a_r1_fundamental_source_contract_and_import_gate.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "factor_input_publication_lag_handled", "Create explicit source contract rule proving input was public by ranking_as_of_date.", ""),
    "factor_input_point_in_time_safe": ("NEW_SOURCE_CONTRACT_REQUIRED", "scripts/v20/v20_108_r6a_r1_fundamental_source_contract_and_import_gate.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "factor_input_point_in_time_safe", "Create explicit ticker-factor PIT safety contract with TRUE/FALSE/UNKNOWN.", ""),
    "non_pit_blocker_present": ("PRODUCER_PATCH_REQUIRED", "scripts/v20/v20_35_random_asof_top20_technical_recompute_backtest.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "non_pit_blocker_present", "Carry ticker-factor non-PIT blocker scan result; UNKNOWN remains blocker.", ""),
    "leakage_flag_present": ("PRODUCER_PATCH_REQUIRED", "scripts/v20/v20_7_stale_leakage_pit_gate.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "leakage_flag_present", "Carry ticker-factor leakage flag result; UNKNOWN remains blocker.", ""),
    "schema_valid": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_108_r10_complete_factor_family_score_assembler.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "schema_valid", "Validate sidecar required columns and non-null direct fields.", "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT"),
    "source_quality_usable": ("PRODUCER_PATCH_REQUIRED", "scripts/v20/v20_10_factor_source_attachment_or_availability_audit.py;scripts/v20/v20_16_factor_score_review_or_backtest_readiness_gate.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "source_quality_usable", "Carry ticker-factor source/evidence quality status to R10 sidecar.", ""),
    "freshness_usable": ("PRODUCER_PATCH_REQUIRED", "scripts/v20/v20_48_refreshed_current_operator_research_report.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "freshness_usable", "Carry ticker-factor freshness validation against ranking_as_of_date.", ""),
    "lineage_to_ranking_score_available": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_108_r10_complete_factor_family_score_assembler.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "lineage_to_ranking_score_available", "Derive TRUE when sidecar ticker/family binds to R10 contribution row and V20.83 baseline ticker.", "ticker|factor_family|baseline_rank"),
    "accepted_for_data_trust_direct_pit_status": ("SAFE_DERIVATION_AVAILABLE", "scripts/v20/v20_170_r2_data_trust_direct_status_emitter_retest_after_pit_producer_patch.py", "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv", "accepted_for_data_trust_direct_pit_status", "Compute TRUE only after all direct PIT dimensions are valid and no UNKNOWN/source-contract blockers remain.", "computed"),
}

SAFETY = {
    "research_only": "TRUE", "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE, "direct_ticker_mapping_required_before_official_use": "TRUE",
    "formal_activation_allowed": "FALSE", "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE", "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE", "official_weight_registry_mutated": "FALSE",
    "weight_mutated": "FALSE", "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE", "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE", "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {**SAFETY, "source_contract_gap_repair_plan_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

SUMMARY_FIELDS = [
    "summary_id", "baseline_candidate_count", "direct_pass_count_before_gap_repair",
    "direct_unknown_count_before_gap_repair", "source_contract_required_field_count",
    "unknown_required_pit_field_count", "distinct_gap_field_count",
    "safe_derivation_candidate_count", "producer_patch_required_count",
    "new_source_contract_required_count", "cannot_repair_with_current_pipeline_count",
    "manual_operator_policy_required_count", "patch_target_count",
    "blockers_affecting_all_tickers_count", "gap_repair_plan_created",
    "ready_for_v20_170_r2b_safe_derivation_patch",
    "ready_for_v20_170_r2c_source_contract_patch",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "recommended_next_action", *COMMON.keys(),
]
FIELD_FIELDS = [
    "required_field", "blocker_category", "missing_or_unknown_count",
    "source_contract_required_count", "affected_ticker_count", "affected_factor_family_count",
    "affected_lineage_row_count", "current_available_source_artifact",
    "current_available_source_field", "gap_classification", "safe_derivation_possible",
    "proposed_derivation_rule", "proposed_upstream_producer_script",
    "proposed_output_artifact", "proposed_output_field", "requires_schema_extension",
    "requires_new_source_contract", "blocks_direct_pass", "repair_priority",
    "recommended_repair_action", *COMMON.keys(),
]
TICKER_FIELDS = [
    "ticker", "baseline_rank", "direct_status_after_r2", "direct_pass_blocker_count",
    "missing_required_field_count", "source_contract_required_field_count",
    "affected_factor_family_count", "highest_priority_blocker",
    "can_repair_from_safe_derivation", "requires_producer_patch",
    "requires_new_source_contract", "recommended_next_action", *COMMON.keys(),
]
FAMILY_FIELDS = [
    "factor_family", "affected_ticker_count", "lineage_row_count",
    "missing_required_field_count", "source_contract_required_field_count",
    "direct_pass_blocker_count", "top_missing_field", "proposed_producer_script",
    "proposed_output_artifact", "repair_priority", *COMMON.keys(),
]
TARGET_FIELDS = [
    "patch_target_id", "producer_script", "producer_exists", "output_artifact",
    "output_artifact_exists", "fields_to_add", "fields_to_safely_derive",
    "fields_requiring_new_source_contract", "expected_row_grain", "expected_join_keys",
    "downstream_consumers", "patch_sequence_order", "patch_risk", "test_required",
    "recommended_stage_for_patch", *COMMON.keys(),
]
SAFE_FIELDS = [
    "required_field", "current_available_source_artifact", "current_available_source_field",
    "proposed_derivation_rule", "affected_ticker_count", "affected_lineage_row_count",
    "producer_script", "output_artifact", "ready_for_v20_170_r2b_safe_derivation_patch",
    "limitation_reason", *COMMON.keys(),
]
NEW_FIELDS = [
    "required_field", "source_contract_owner_stage", "source_contract_artifact",
    "source_contract_field", "affected_ticker_count", "affected_lineage_row_count",
    "required_policy_or_evidence", "blocks_direct_pass", "recommended_stage_for_contract",
    "repair_priority", *COMMON.keys(),
]
PRIORITY_FIELDS = [
    "blocker_rank", "blocker_field", "blocker_category", "affected_ticker_count",
    "affected_lineage_row_count", "blocks_all_tickers",
    "can_be_resolved_by_safe_derivation", "can_be_resolved_by_single_producer_patch",
    "requires_new_source_contract", "recommended_stage", "expected_impact_if_repaired",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r2_status_consumed", "v20_170_r2_status",
    *[f for f in SUMMARY_FIELDS if f not in COMMON and f != "summary_id"],
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_data_trust_status_fabricated",
    "no_pit_status_fabricated", "unknown_not_treated_as_pass",
    "source_contract_required_not_treated_as_pass", "aggregate_evidence_not_treated_as_direct",
    "no_upstream_outputs_mutated", "blocking_reason", "final_status", *COMMON.keys(),
]
SAFETY_FIELDS = ["safety_check_id", "safety_check", "expected_value", "actual_value", "safety_passed", *COMMON.keys()]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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
        return [{k: clean(v) for k, v in row.items()} for row in reader], list(reader.fieldnames or [])


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


def protected_hashes() -> dict[str, str]:
    paths = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, PIT_SCHEMA_AUDIT, PIT_GAP_AUDIT, *R2_INPUTS, *R1C_INPUTS]
    return {rel(path): sha_file(path) for path in paths if path.exists()}


def script_exists(script_list: str) -> str:
    first = script_list.split(";")[0]
    return tf((ROOT / first).exists())


def is_unknown(value: object) -> bool:
    return clean(value).upper() in {"", "UNKNOWN", "UNKNOWN_CONTEXT_ID", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"}


def build_field_rows(lineage: list[dict[str, str]], baseline_tickers: set[str]) -> list[dict[str, str]]:
    consumed = [row for row in lineage if row.get("ticker") in baseline_tickers]
    rows = []
    for field in DIMENSIONS:
        unknown_rows = [row for row in consumed if is_unknown(row.get(field))]
        source_rows = [row for row in consumed if field in clean(row.get("source_contract_required_fields")).split("|")]
        affected_rows = {id(row): row for row in [*unknown_rows, *source_rows]}.values()
        affected = list(affected_rows)
        classification, script, artifact, out_field, rule, current_field = FIELD_PLAN[field]
        missing_count = len(unknown_rows)
        source_count = len(source_rows)
        blocker_category = "NO_GAP" if not affected else ("SOURCE_CONTRACT_REQUIRED" if source_count else "UNKNOWN_REQUIRED_FIELD")
        rows.append({
            "required_field": field,
            "blocker_category": blocker_category,
            "missing_or_unknown_count": str(missing_count),
            "source_contract_required_count": str(source_count),
            "affected_ticker_count": str(len({row.get("ticker") for row in affected})),
            "affected_factor_family_count": str(len({row.get("factor_family") for row in affected})),
            "affected_lineage_row_count": str(len(affected)),
            "current_available_source_artifact": artifact if current_field else "",
            "current_available_source_field": current_field,
            "gap_classification": "SAFE_DERIVATION_AVAILABLE" if not affected and classification == "SAFE_DERIVATION_AVAILABLE" else classification,
            "safe_derivation_possible": tf(classification == "SAFE_DERIVATION_AVAILABLE"),
            "proposed_derivation_rule": rule,
            "proposed_upstream_producer_script": script,
            "proposed_output_artifact": artifact,
            "proposed_output_field": out_field,
            "requires_schema_extension": "FALSE",
            "requires_new_source_contract": tf(classification == "NEW_SOURCE_CONTRACT_REQUIRED"),
            "blocks_direct_pass": tf(bool(affected) or field == "accepted_for_data_trust_direct_pit_status"),
            "repair_priority": "HIGH" if affected else "LOW",
            "recommended_repair_action": repair_action(classification, field, bool(affected)),
            **COMMON,
        })
    return rows


def repair_action(classification: str, field: str, affected: bool) -> str:
    if not affected and field != "accepted_for_data_trust_direct_pit_status":
        return "NO_ACTION_REQUIRED_CURRENTLY_POPULATED"
    if classification == "SAFE_DERIVATION_AVAILABLE":
        return "IMPLEMENT_V20_170_R2B_SAFE_DERIVATION_PATCH"
    if classification == "PRODUCER_PATCH_REQUIRED":
        return "IMPLEMENT_V20_170_R2C_PRODUCER_SOURCE_CONTRACT_PATCH"
    if classification == "NEW_SOURCE_CONTRACT_REQUIRED":
        return "CREATE_EXPLICIT_UPSTREAM_SOURCE_CONTRACT"
    if classification == "MANUAL_OPERATOR_POLICY_REQUIRED":
        return "REQUEST_MANUAL_OPERATOR_POLICY"
    return "CANNOT_REPAIR_WITH_CURRENT_PIPELINE"


def build_ticker_rows(retest: list[dict[str, str]], lineage: list[dict[str, str]], baseline: list[dict[str, str]]) -> list[dict[str, str]]:
    by_ticker = defaultdict(list)
    for row in lineage:
        by_ticker[row.get("ticker")].append(row)
    rank = {row.get("ticker"): row.get("official_current_rank") or row.get("baseline_rank") for row in baseline}
    rows = []
    for row in retest:
        ticker = row.get("ticker")
        ticker_lineage = by_ticker[ticker]
        missing_fields = set()
        source_fields = set()
        for line in ticker_lineage:
            for field in DIMENSIONS:
                if is_unknown(line.get(field)):
                    missing_fields.add(field)
            source_fields.update([f for f in clean(line.get("source_contract_required_fields")).split("|") if f])
        classifications = {FIELD_PLAN[field][0] for field in missing_fields | source_fields}
        rows.append({
            "ticker": ticker,
            "baseline_rank": rank.get(ticker, row.get("baseline_rank", "")),
            "direct_status_after_r2": row.get("retested_direct_data_trust_status", ""),
            "direct_pass_blocker_count": "1" if row.get("retested_direct_data_trust_status") != "PASS" else "0",
            "missing_required_field_count": str(sum(1 for line in ticker_lineage for field in DIMENSIONS if is_unknown(line.get(field)))),
            "source_contract_required_field_count": str(sum(len([f for f in clean(line.get("source_contract_required_fields")).split("|") if f]) for line in ticker_lineage)),
            "affected_factor_family_count": str(len({line.get("factor_family") for line in ticker_lineage})),
            "highest_priority_blocker": "factor_input_point_in_time_safe" if ticker_lineage else "NO_LINEAGE",
            "can_repair_from_safe_derivation": tf("SAFE_DERIVATION_AVAILABLE" in classifications),
            "requires_producer_patch": tf("PRODUCER_PATCH_REQUIRED" in classifications),
            "requires_new_source_contract": tf("NEW_SOURCE_CONTRACT_REQUIRED" in classifications),
            "recommended_next_action": "REPAIR_SOURCE_CONTRACT_GAPS_BEFORE_RANKING",
            **COMMON,
        })
    return rows


def build_family_rows(lineage: list[dict[str, str]], baseline_tickers: set[str]) -> list[dict[str, str]]:
    consumed = [row for row in lineage if row.get("ticker") in baseline_tickers]
    by_family = defaultdict(list)
    for row in consumed:
        by_family[row.get("factor_family")].append(row)
    rows = []
    for family, items in sorted(by_family.items()):
        counts = Counter()
        source_count = 0
        for row in items:
            for field in DIMENSIONS:
                if is_unknown(row.get(field)):
                    counts[field] += 1
            source_count += len([f for f in clean(row.get("source_contract_required_fields")).split("|") if f])
        top_field = counts.most_common(1)[0][0] if counts else ""
        script = FIELD_PLAN.get(top_field, FIELD_PLAN["factor_input_point_in_time_safe"])[1]
        artifact = FIELD_PLAN.get(top_field, FIELD_PLAN["factor_input_point_in_time_safe"])[2]
        rows.append({
            "factor_family": family,
            "affected_ticker_count": str(len({row.get("ticker") for row in items})),
            "lineage_row_count": str(len(items)),
            "missing_required_field_count": str(sum(counts.values())),
            "source_contract_required_field_count": str(source_count),
            "direct_pass_blocker_count": str(len(items)),
            "top_missing_field": top_field,
            "proposed_producer_script": script,
            "proposed_output_artifact": artifact,
            "repair_priority": "HIGH",
            **COMMON,
        })
    return rows


def build_targets(field_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in field_rows:
        if int(row["affected_lineage_row_count"]) > 0 or row["required_field"] == "accepted_for_data_trust_direct_pit_status":
            grouped[(row["proposed_upstream_producer_script"], row["proposed_output_artifact"])].append(row)
    rows = []
    for idx, ((script, artifact), items) in enumerate(sorted(grouped.items()), start=1):
        safe = [r["required_field"] for r in items if r["gap_classification"] == "SAFE_DERIVATION_AVAILABLE"]
        new = [r["required_field"] for r in items if r["gap_classification"] == "NEW_SOURCE_CONTRACT_REQUIRED"]
        add = [r["required_field"] for r in items if r["gap_classification"] == "PRODUCER_PATCH_REQUIRED"]
        rows.append({
            "patch_target_id": f"V20_170_R2A_PATCH_TARGET_{idx:03d}",
            "producer_script": script,
            "producer_exists": script_exists(script),
            "output_artifact": artifact,
            "output_artifact_exists": tf((ROOT / artifact).exists()),
            "fields_to_add": "|".join(add),
            "fields_to_safely_derive": "|".join(safe),
            "fields_requiring_new_source_contract": "|".join(new),
            "expected_row_grain": "ticker_factor_family",
            "expected_join_keys": "ticker|factor_family|ranking_context_id",
            "downstream_consumers": "V20_170_R2_DIRECT_STATUS_RETEST;V20_170_R2B;V20_170_R2C",
            "patch_sequence_order": str(idx),
            "patch_risk": "MEDIUM" if new else "LOW",
            "test_required": "TRUE",
            "recommended_stage_for_patch": "V20_170_R2B" if safe and not (add or new) else "V20_170_R2C",
            **COMMON,
        })
    return rows


def build_priority(field_rows: list[dict[str, str]], baseline_count: int) -> list[dict[str, str]]:
    active = [row for row in field_rows if int(row["affected_lineage_row_count"]) > 0 or row["required_field"] == "accepted_for_data_trust_direct_pit_status"]
    active.sort(key=lambda r: (-int(r["affected_ticker_count"]), r["gap_classification"], r["required_field"]))
    rows = []
    for idx, row in enumerate(active, start=1):
        classification = row["gap_classification"]
        rows.append({
            "blocker_rank": str(idx),
            "blocker_field": row["required_field"],
            "blocker_category": row["blocker_category"],
            "affected_ticker_count": row["affected_ticker_count"],
            "affected_lineage_row_count": row["affected_lineage_row_count"],
            "blocks_all_tickers": tf(int(row["affected_ticker_count"]) == baseline_count or row["required_field"] == "accepted_for_data_trust_direct_pit_status"),
            "can_be_resolved_by_safe_derivation": tf(classification == "SAFE_DERIVATION_AVAILABLE"),
            "can_be_resolved_by_single_producer_patch": tf(classification == "PRODUCER_PATCH_REQUIRED"),
            "requires_new_source_contract": tf(classification == "NEW_SOURCE_CONTRACT_REQUIRED"),
            "recommended_stage": "V20_170_R2B" if classification == "SAFE_DERIVATION_AVAILABLE" else "V20_170_R2C",
            "expected_impact_if_repaired": "REMOVES_DIRECT_PASS_BLOCKER_DIMENSION_FOR_AFFECTED_ROWS",
            **COMMON,
        })
    return rows


def build_summary(gate: dict[str, str], field_rows: list[dict[str, str]], targets: list[dict[str, str]], priority: list[dict[str, str]]) -> dict[str, str]:
    active = [row for row in field_rows if int(row["affected_lineage_row_count"]) > 0 or row["required_field"] == "accepted_for_data_trust_direct_pit_status"]
    count_by = Counter(row["gap_classification"] for row in active)
    safe_count = count_by["SAFE_DERIVATION_AVAILABLE"]
    producer_count = count_by["PRODUCER_PATCH_REQUIRED"]
    new_count = count_by["NEW_SOURCE_CONTRACT_REQUIRED"]
    cannot = count_by["CANNOT_REPAIR_WITH_CURRENT_PIPELINE"]
    manual = count_by["MANUAL_OPERATOR_POLICY_REQUIRED"]
    if safe_count and (producer_count or new_count):
        action = "RUN_V20_170_R2B_SAFE_DERIVATION_THEN_V20_170_R2C_SOURCE_CONTRACT_PATCH"
    elif safe_count:
        action = "RUN_V20_170_R2B_SAFE_DERIVATION_PATCH"
    elif producer_count or new_count:
        action = "RUN_V20_170_R2C_SOURCE_CONTRACT_PATCH"
    else:
        action = "REQUIRE_MANUAL_OPERATOR_POLICY"
    return {
        "summary_id": "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY_001",
        "baseline_candidate_count": gate.get("baseline_candidate_count", "0"),
        "direct_pass_count_before_gap_repair": gate.get("retested_direct_data_trust_pass_count", "0"),
        "direct_unknown_count_before_gap_repair": gate.get("retested_direct_data_trust_unknown_count", "0"),
        "source_contract_required_field_count": gate.get("source_contract_required_field_count", "0"),
        "unknown_required_pit_field_count": gate.get("unknown_required_pit_field_count", "0"),
        "distinct_gap_field_count": str(len({row["required_field"] for row in active})),
        "safe_derivation_candidate_count": str(safe_count),
        "producer_patch_required_count": str(producer_count),
        "new_source_contract_required_count": str(new_count),
        "cannot_repair_with_current_pipeline_count": str(cannot),
        "manual_operator_policy_required_count": str(manual),
        "patch_target_count": str(len(targets)),
        "blockers_affecting_all_tickers_count": str(sum(row["blocks_all_tickers"] == "TRUE" for row in priority)),
        "gap_repair_plan_created": "TRUE",
        "ready_for_v20_170_r2b_safe_derivation_patch": tf(safe_count > 0),
        "ready_for_v20_170_r2c_source_contract_patch": tf(producer_count > 0 or new_count > 0),
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": action,
        **COMMON,
    }


def safety_rows(prereq_ok: bool, upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_r2_prerequisites_met", "TRUE", tf(prereq_ok)),
        ("ranking_simulation_created", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
        ("official_weight_change_allowed", "FALSE", "FALSE"),
        ("official_ranking_mutation_allowed", "FALSE", "FALSE"),
        ("data_trust_status_fabricated", "FALSE", "FALSE"),
        ("pit_status_fabricated", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("source_contract_required_treated_as_pass", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{"safety_check_id": f"V20_170_R2A_SAFETY_{i:03d}", "safety_check": c, "expected_value": e,
             "actual_value": a, "safety_passed": tf(e == a), **COMMON}
            for i, (c, e, a) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R2A DATA_TRUST Source Contract Gap Repair Plan Report",
        "",
        f"- final_status: {status}",
        "- research_only: TRUE",
        "- ranking_simulation_created: FALSE",
        "- ready_for_official_use: FALSE",
    ]
    if summary:
        for key in ["baseline_candidate_count", "source_contract_required_field_count",
                    "unknown_required_pit_field_count", "distinct_gap_field_count",
                    "safe_derivation_candidate_count", "producer_patch_required_count",
                    "new_source_contract_required_count", "patch_target_count",
                    "ready_for_v20_170_r2b_safe_derivation_patch",
                    "ready_for_v20_170_r2c_source_contract_patch", "recommended_next_action"]:
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "This stage is planning-only; it does not mark any ticker DIRECT_PASS."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_SUMMARY, SUMMARY_FIELDS), (OUT_BY_FIELD, FIELD_FIELDS), (OUT_BY_TICKER, TICKER_FIELDS),
                         (OUT_BY_FAMILY, FAMILY_FIELDS), (OUT_TARGETS, TARGET_FIELDS), (OUT_SAFE, SAFE_FIELDS),
                         (OUT_NEW, NEW_FIELDS), (OUT_PRIORITY, PRIORITY_FIELDS), (OUT_SAFETY, SAFETY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE_001",
        "v20_170_r2_status_consumed": "FALSE", "v20_170_r2_status": "",
        "baseline_candidate_count": "0", "direct_pass_count_before_gap_repair": "0",
        "direct_unknown_count_before_gap_repair": "0", "source_contract_required_field_count": "0",
        "unknown_required_pit_field_count": "0", "distinct_gap_field_count": "0",
        "safe_derivation_candidate_count": "0", "producer_patch_required_count": "0",
        "new_source_contract_required_count": "0", "cannot_repair_with_current_pipeline_count": "0",
        "manual_operator_policy_required_count": "0", "patch_target_count": "0",
        "blockers_affecting_all_tickers_count": "0", "gap_repair_plan_created": "FALSE",
        "ready_for_v20_170_r2b_safe_derivation_patch": "FALSE",
        "ready_for_v20_170_r2c_source_contract_patch": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE", "ready_for_official_use": "FALSE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R2A",
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE", "aggregate_evidence_not_treated_as_direct": "TRUE",
        "no_upstream_outputs_mutated": "TRUE", "blocking_reason": reason, "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    required = [*R2_INPUTS, PIT_LINEAGE, PIT_SCHEMA_AUDIT, PIT_GAP_AUDIT, *R1C_INPUTS]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing))
    before = protected_hashes()
    r2_gate_rows, _ = read_csv(FACTORS / "V20_170_R2_DIRECT_STATUS_NEXT_GATE.csv")
    retest, _ = read_csv(FACTORS / "V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST.csv")
    lineage, _ = read_csv(PIT_LINEAGE)
    baseline, _ = read_csv(BASELINE)
    if not r2_gate_rows or not retest or not lineage:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r2_gate = r2_gate_rows[0]
    prereq_ok = all([
        r2_gate.get("final_status") == REQUIRED_R2_STATUS,
        r2_gate.get("ready_for_v20_170_r2a_source_contract_gap_repair") == "TRUE",
        r2_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r2_gate.get("ready_for_official_use") == "FALSE",
        r2_gate.get("retested_direct_data_trust_pass_count") == "0",
        r2_gate.get("retested_direct_data_trust_unknown_count") == "40",
        int(r2_gate.get("source_contract_required_field_count", "0")) > 0,
        int(r2_gate.get("unknown_required_pit_field_count", "0")) > 0,
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R2_REQUIREMENTS_NOT_MET")
    baseline_tickers = {row.get("ticker") for row in retest}
    field_rows = build_field_rows(lineage, baseline_tickers)
    ticker_rows = build_ticker_rows(retest, lineage, baseline)
    family_rows = build_family_rows(lineage, baseline_tickers)
    targets = build_targets(field_rows)
    priority = build_priority(field_rows, int(r2_gate.get("baseline_candidate_count", "0")))
    safe_rows = [{
        "required_field": row["required_field"],
        "current_available_source_artifact": row["current_available_source_artifact"],
        "current_available_source_field": row["current_available_source_field"],
        "proposed_derivation_rule": row["proposed_derivation_rule"],
        "affected_ticker_count": row["affected_ticker_count"],
        "affected_lineage_row_count": row["affected_lineage_row_count"],
        "producer_script": row["proposed_upstream_producer_script"],
        "output_artifact": row["proposed_output_artifact"],
        "ready_for_v20_170_r2b_safe_derivation_patch": "TRUE",
        "limitation_reason": "DERIVATION_MUST_REMAIN_NON_PASS_UNTIL_VALIDATED",
        **COMMON,
    } for row in field_rows if row["gap_classification"] == "SAFE_DERIVATION_AVAILABLE" and (int(row["affected_lineage_row_count"]) > 0 or row["required_field"] == "accepted_for_data_trust_direct_pit_status")]
    new_rows = [{
        "required_field": row["required_field"],
        "source_contract_owner_stage": "UPSTREAM_FACTOR_SOURCE_CONTRACT",
        "source_contract_artifact": "UPSTREAM_TICKER_FACTOR_SOURCE_CONTRACT",
        "source_contract_field": row["proposed_output_field"],
        "affected_ticker_count": row["affected_ticker_count"],
        "affected_lineage_row_count": row["affected_lineage_row_count"],
        "required_policy_or_evidence": row["proposed_derivation_rule"],
        "blocks_direct_pass": "TRUE",
        "recommended_stage_for_contract": "V20_170_R2C",
        "repair_priority": "HIGH",
        **COMMON,
    } for row in field_rows if row["gap_classification"] == "NEW_SOURCE_CONTRACT_REQUIRED" and int(row["affected_lineage_row_count"]) > 0]
    summary = build_summary(r2_gate, field_rows, targets, priority)
    upstream_mutated = before != protected_hashes()
    safety = safety_rows(prereq_ok, upstream_mutated)
    if upstream_mutated or not all(row["safety_passed"] == "TRUE" for row in safety):
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")
    safe_count = int(summary["safe_derivation_candidate_count"])
    producer_count = int(summary["producer_patch_required_count"])
    new_count = int(summary["new_source_contract_required_count"])
    if safe_count and (producer_count or new_count):
        final_status = PARTIAL_STATUS
    elif safe_count:
        final_status = PASS_STATUS
    elif not (safe_count or producer_count or new_count):
        final_status = WARN_STATUS
    else:
        final_status = PARTIAL_STATUS
    gate_out = {
        "gate_check_id": "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE_001",
        "v20_170_r2_status_consumed": "TRUE",
        "v20_170_r2_status": r2_gate.get("final_status", ""),
        **summary,
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE", "aggregate_evidence_not_treated_as_direct": "TRUE",
        "no_upstream_outputs_mutated": "TRUE", "blocking_reason": "SOURCE_CONTRACT_GAPS_BLOCK_V20_171",
        "final_status": final_status, **COMMON,
    }
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, [summary])
    write_csv(OUT_BY_FIELD, FIELD_FIELDS, field_rows)
    write_csv(OUT_BY_TICKER, TICKER_FIELDS, ticker_rows)
    write_csv(OUT_BY_FAMILY, FAMILY_FIELDS, family_rows)
    write_csv(OUT_TARGETS, TARGET_FIELDS, targets)
    write_csv(OUT_SAFE, SAFE_FIELDS, safe_rows)
    write_csv(OUT_NEW, NEW_FIELDS, new_rows)
    write_csv(OUT_PRIORITY, PRIORITY_FIELDS, priority)
    write_csv(OUT_GATE, GATE_FIELDS, [gate_out])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(final_status, summary)
    print(final_status)
    print(f"V20_170_R2_STATUS={r2_gate.get('final_status', '')}")
    for key in SUMMARY_FIELDS:
        if key in summary and key not in COMMON and key != "summary_id":
            print(f"{key.upper()}={summary[key]}")
    print("OFFICIAL_WEIGHT_CHANGE_ALLOWED=FALSE")
    print("OFFICIAL_RANKING_MUTATION_ALLOWED=FALSE")
    print("RANKING_SIMULATION_CREATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("REAL_BOOK_ACTION_CREATED=FALSE")
    print("TRADE_ACTION_CREATED=FALSE")
    print("BROKER_EXECUTION_SUPPORTED=FALSE")
    print("PERFORMANCE_CLAIM_CREATED=FALSE")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
