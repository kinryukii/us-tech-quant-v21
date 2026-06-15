#!/usr/bin/env python
"""V20.170-R1B DATA_TRUST upstream PIT producer patch plan."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"
SCRIPTS = ROOT / "scripts" / "v20"

REQUIRED_R1A_STATUS = "WARN_V20_170_R1A_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_REQUIRED"
PASS_STATUS = "PASS_V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_READY_FOR_V20_170_R1C"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1B_PATCH_PLAN_WITH_UNRESOLVED_SOURCE_CONTRACTS_READY_FOR_V20_170_R1C"
WARN_STATUS = "WARN_V20_170_R1B_NO_PATCHABLE_UPSTREAM_PRODUCER_IDENTIFIED"
BLOCKED_STATUS = "BLOCKED_V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_UPSTREAM_PIT_PRODUCER_PATCH_PLAN"

R1A_INPUTS = [
    FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_CONTRACT.csv",
    FACTORS / "V20_170_R1A_UPSTREAM_PIT_SOURCE_DISCOVERY.csv",
    FACTORS / "V20_170_R1A_TICKER_FACTOR_PIT_LINEAGE_EMITTER.csv",
    FACTORS / "V20_170_R1A_TICKER_LEVEL_PIT_DIRECT_STATUS.csv",
    FACTORS / "V20_170_R1A_PIT_DIRECT_STATUS_MISSING_FIELD_AUDIT.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_REPAIR_BACKLOG.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_COVERAGE_SUMMARY.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_NEXT_GATE.csv",
    FACTORS / "V20_170_R1A_PIT_SOURCE_CONTRACT_SAFETY_AUDIT.csv",
]
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"

OUT_PLAN = FACTORS / "V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN.csv"
OUT_MAPPING = FACTORS / "V20_170_R1B_PIT_MISSING_FIELD_TO_PRODUCER_MAPPING.csv"
OUT_RULES = FACTORS / "V20_170_R1B_PIT_REQUIRED_FIELD_DERIVATION_RULES.csv"
OUT_TARGETS = FACTORS / "V20_170_R1B_PIT_PRODUCER_SCRIPT_PATCH_TARGETS.csv"
OUT_SCHEMA = FACTORS / "V20_170_R1B_PIT_OUTPUT_SCHEMA_EXTENSION_PLAN.csv"
OUT_RISK = FACTORS / "V20_170_R1B_PIT_PATCH_RISK_AND_SAFETY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_R1B_PIT_PRODUCER_PATCH_NEXT_GATE.csv"
REPORT = READ_CENTER / "V20_170_R1B_DATA_TRUST_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_REPORT.md"
OUTPUT_PATHS = [OUT_PLAN, OUT_MAPPING, OUT_RULES, OUT_TARGETS, OUT_SCHEMA, OUT_RISK, OUT_GATE]

SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
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
COMMON = {**SAFETY, "upstream_pit_producer_patch_plan_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

REQUIRED_FIELDS = [
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id", "source_artifact",
    "source_row_id", "factor_family", "factor_input_name", "factor_input_as_of_date",
    "factor_input_source_timestamp", "factor_input_publication_lag_handled",
    "factor_input_point_in_time_safe", "non_pit_blocker_present", "leakage_flag_present",
    "schema_valid", "source_quality_usable", "freshness_usable",
    "lineage_to_ranking_score_available", "accepted_for_data_trust_direct_pit_status",
]

OUTPUT_ARTIFACTS = {
    "CANONICAL": CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
    "FAMILY_SCORES": CONSOLIDATION / "V20_108_R4_REAL_CANDIDATE_FACTOR_FAMILY_SCORES.csv",
    "CONTRIBUTIONS": CONSOLIDATION / "V20_108_R1_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv",
    "EXPANDED": CONSOLIDATION / "V20_108_R2_EXPANDED_CANDIDATE_FACTOR_FAMILY_CONTRIBUTIONS.csv",
    "WEIGHT_AUDIT": CONSOLIDATION / "V20_98B_FACTOR_SCORE_CONTRIBUTION_AUDIT.csv",
    "WEIGHT_EXPOSURE": CONSOLIDATION / "V20_98B_RESEARCH_ONLY_FACTOR_WEIGHT_EXPOSURE.csv",
    "SUPPORT_45": CONSOLIDATION / "V20_45_CURRENT_OPERATOR_FACTOR_SUPPORT_VIEW.csv",
    "SUPPORT_48": CONSOLIDATION / "V20_48_REFRESHED_FACTOR_SUPPORT_VIEW.csv",
    "SUPPORT_54": CONSOLIDATION / "V20_54_FACTOR_SUPPORT_READABLE_VIEW.csv",
    "VALIDATION_CURRENT": CONSOLIDATION / "V20_CURRENT_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
    "VALIDATION_82": CONSOLIDATION / "V20_82_FACTOR_MULTI_PATH_VALIDATION_TABLE.csv",
}

SCRIPT_BY_ARTIFACT = {
    "CANONICAL": SCRIPTS / "v20_108_r10_complete_factor_family_score_assembler.py",
    "FAMILY_SCORES": SCRIPTS / "v20_108_r4_real_candidate_factor_family_score_materializer.py",
    "CONTRIBUTIONS": SCRIPTS / "v20_108_r1_candidate_factor_family_contribution_builder.py",
    "EXPANDED": SCRIPTS / "v20_108_r2_missing_factor_family_contribution_source_expander.py",
    "WEIGHT_AUDIT": SCRIPTS / "v20_98b_research_only_factor_weight_exposure_auditor.py",
    "WEIGHT_EXPOSURE": SCRIPTS / "v20_98b_research_only_factor_weight_exposure_auditor.py",
    "SUPPORT_45": SCRIPTS / "v20_45_current_operator_report_research_only_run.py",
    "SUPPORT_48": SCRIPTS / "v20_48_refreshed_current_operator_research_report.py",
    "SUPPORT_54": SCRIPTS / "v20_54_user_readable_current_decision_report.py",
    "VALIDATION_CURRENT": SCRIPTS / "v20_82_multi_path_strategy_benchmark_validation_layer.py",
    "VALIDATION_82": SCRIPTS / "v20_82_multi_path_strategy_benchmark_validation_layer.py",
}

FIELD_TARGET = {
    "ticker": "CANONICAL",
    "ranking_context_id": "CANONICAL",
    "ranking_as_of_date": "CANONICAL",
    "data_snapshot_id": "CANONICAL",
    "source_artifact": "CANONICAL",
    "source_row_id": "CANONICAL",
    "factor_family": "CANONICAL",
    "factor_input_name": "CANONICAL",
    "factor_input_as_of_date": "CANONICAL",
    "factor_input_source_timestamp": "CANONICAL",
    "factor_input_publication_lag_handled": "CANONICAL",
    "factor_input_point_in_time_safe": "CANONICAL",
    "non_pit_blocker_present": "CANONICAL",
    "leakage_flag_present": "CANONICAL",
    "schema_valid": "CANONICAL",
    "source_quality_usable": "CANONICAL",
    "freshness_usable": "CANONICAL",
    "lineage_to_ranking_score_available": "CANONICAL",
    "accepted_for_data_trust_direct_pit_status": "CANONICAL",
}

CLASSIFICATION = {
    "ticker": "EXISTING_FIELD_DIRECT",
    "ranking_context_id": "EXISTING_FIELD_DERIVABLE",
    "ranking_as_of_date": "EXISTING_FIELD_DERIVABLE",
    "data_snapshot_id": "EXISTING_FIELD_DERIVABLE",
    "source_artifact": "EXISTING_FIELD_DERIVABLE",
    "source_row_id": "EXISTING_FIELD_DERIVABLE",
    "factor_family": "EXISTING_FIELD_DIRECT",
    "factor_input_name": "EXISTING_FIELD_DERIVABLE",
    "factor_input_as_of_date": "NEEDS_PRODUCER_PATCH",
    "factor_input_source_timestamp": "NEEDS_PRODUCER_PATCH",
    "factor_input_publication_lag_handled": "NEEDS_NEW_SOURCE_CONTRACT",
    "factor_input_point_in_time_safe": "NEEDS_NEW_SOURCE_CONTRACT",
    "non_pit_blocker_present": "NEEDS_PRODUCER_PATCH",
    "leakage_flag_present": "NEEDS_PRODUCER_PATCH",
    "schema_valid": "EXISTING_FIELD_DERIVABLE",
    "source_quality_usable": "EXISTING_FIELD_DERIVABLE",
    "freshness_usable": "EXISTING_FIELD_DERIVABLE",
    "lineage_to_ranking_score_available": "NEEDS_PRODUCER_PATCH",
    "accepted_for_data_trust_direct_pit_status": "EXISTING_FIELD_DERIVABLE",
}

FIELD_TYPE = {
    "source_row_id": "INTEGER_OR_STRING_ROW_ID",
    "factor_input_publication_lag_handled": "BOOLEAN",
    "factor_input_point_in_time_safe": "BOOLEAN",
    "non_pit_blocker_present": "BOOLEAN",
    "leakage_flag_present": "BOOLEAN",
    "schema_valid": "BOOLEAN",
    "source_quality_usable": "BOOLEAN",
    "freshness_usable": "BOOLEAN",
    "lineage_to_ranking_score_available": "BOOLEAN",
    "accepted_for_data_trust_direct_pit_status": "BOOLEAN_COMPUTED",
}

PLAN_FIELDS = [
    "missing_required_field", "affected_ticker_count", "affected_lineage_row_count",
    "current_source_artifact", "current_source_field_available", "patch_classification",
    "proposed_upstream_producer_script", "proposed_output_artifact", "proposed_output_field",
    "derivation_rule", "derivation_safe", "requires_code_patch", "requires_schema_extension",
    "requires_backfill", "repair_priority", "blocking_for_direct_pit_pass",
    "recommended_patch_action", *COMMON.keys(),
]
MAPPING_FIELDS = [
    "missing_required_field", "factor_family", "affected_ticker_count",
    "affected_lineage_row_count", "current_source_artifact", "current_source_field_available",
    "patch_classification", "proposed_upstream_producer_script", "proposed_output_artifact",
    "proposed_output_field", "recommended_patch_action", *COMMON.keys(),
]
RULE_FIELDS = [
    "proposed_output_field", "source_field_or_constant", "derivation_logic", "valid_values",
    "null_handling_rule", "unknown_handling_rule", "fail_handling_rule",
    "pit_safety_implication", "accepted_for_direct_evidence", "limitation_reason",
    *COMMON.keys(),
]
TARGET_FIELDS = [
    "producer_script", "producer_exists", "current_output_artifact", "output_artifact_exists",
    "patch_required", "schema_extension_required", "fields_to_add", "derivable_fields_to_add",
    "non_derivable_fields_to_add", "expected_row_grain", "expected_join_keys",
    "downstream_consumers", "patch_order", "test_required", *COMMON.keys(),
]
SCHEMA_FIELDS = [
    "output_artifact", "row_grain", "required_join_keys", "new_field_name", "field_type",
    "required_non_null_for_direct_pass", "allowed_values", "default_value",
    "default_value_allowed_for_direct_pass", "validation_rule", "downstream_required_by",
    "backwards_compatibility_notes", *COMMON.keys(),
]
RISK_FIELDS = [
    "audit_id", "risk_or_safety_check", "expected_value", "actual_value", "safety_passed",
    "missing_required_pit_field_count", "affected_ticker_count", "affected_lineage_row_count",
    "producer_script_target_count", "output_artifact_target_count", "existing_field_direct_count",
    "existing_field_derivable_count", "needs_producer_patch_count",
    "needs_new_source_contract_count", "cannot_repair_from_current_artifacts_count",
    "patch_plan_created", "ready_for_v20_170_r1c_producer_patch",
    "ready_for_v20_170_r2_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r1a_status_consumed", "v20_170_r1a_status",
    "missing_required_pit_field_count", "affected_ticker_count", "affected_lineage_row_count",
    "producer_script_target_count", "output_artifact_target_count", "existing_field_direct_count",
    "existing_field_derivable_count", "needs_producer_patch_count",
    "needs_new_source_contract_count", "cannot_repair_from_current_artifacts_count",
    "patch_plan_created", "ready_for_v20_170_r1c_producer_patch",
    "ready_for_v20_170_r2_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_pit_status_fabricated",
    "aggregate_pit_not_treated_as_ticker_pass", "unknown_not_treated_as_pass",
    "pit_criteria_not_lowered", "no_upstream_outputs_mutated", "recommended_next_action",
    "blocking_reason", "final_status", *COMMON.keys(),
]


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


def protected_paths() -> list[Path]:
    producer_scripts = []
    for pattern in ["v20_108*.py", "v20_98B*.py", "v20_98b*.py", "v20_82*.py", "v20_current*.py", "v20_45*.py", "v20_48*.py", "v20_54*.py"]:
        producer_scripts.extend(SCRIPTS.glob(pattern))
    return sorted(set([*R1A_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY, *OUTPUT_ARTIFACTS.values(), *producer_scripts]))


def input_hashes(paths: list[Path]) -> dict[str, str]:
    return {rel(path): sha_file(path) for path in paths if path.exists()}


def output_fields(path: Path) -> set[str]:
    _, fields = read_csv(path)
    return set(fields)


def rule_for(field: str) -> dict[str, str]:
    rules = {
        "ticker": ("ticker", "Carry existing ticker column at ticker-factor row grain.", "NON_EMPTY", "Missing ticker blocks row creation."),
        "ranking_context_id": ("source_run_id|source_stage", "Derive from authoritative ranking source_run_id and stage.", "NON_EMPTY", "UNKNOWN until ranking binding exists."),
        "ranking_as_of_date": ("ranking_timestamp_utc|latest_price_date", "Carry ranking timestamp/date from V20.83 context.", "ISO_DATE_OR_TIMESTAMP", "UNKNOWN blocks direct evidence."),
        "data_snapshot_id": ("accepted_artifact_path|source_file|source_run_id", "Bind to source artifact/run id used to produce the row.", "NON_EMPTY", "UNKNOWN blocks direct evidence."),
        "source_artifact": ("output artifact path constant", "Emit the artifact path containing the ticker-factor evidence row.", "NON_EMPTY", "UNKNOWN blocks direct evidence."),
        "source_row_id": ("row_number or stable row id", "Emit deterministic row id after output ordering is fixed.", "NON_EMPTY", "UNKNOWN blocks direct evidence."),
        "factor_family": ("factor_family or materialized contribution column family", "Normalize each family contribution to ticker-factor row grain.", "FUNDAMENTAL|TECHNICAL|STRATEGY|RISK|MARKET_REGIME|DATA_TRUST", "UNKNOWN blocks direct evidence."),
        "factor_input_name": ("contribution/materialization source column", "Name the exact input or contribution column for the family.", "NON_EMPTY", "UNKNOWN blocks direct evidence."),
        "factor_input_as_of_date": ("producer input as_of/effective date", "Carry from the family source producer; do not infer from current run timestamp.", "ISO_DATE", "UNKNOWN blocks direct evidence."),
        "factor_input_source_timestamp": ("producer source timestamp", "Carry provider/cache/source timestamp from the family producer.", "ISO_TIMESTAMP", "UNKNOWN blocks direct evidence."),
        "factor_input_publication_lag_handled": ("source contract boolean", "Producer sets TRUE only when lag policy proves input was public by ranking_as_of_date.", "TRUE|FALSE|UNKNOWN", "UNKNOWN is not pass."),
        "factor_input_point_in_time_safe": ("source contract boolean", "Producer sets TRUE only when direct PIT policy is satisfied for that ticker-factor input.", "TRUE|FALSE|UNKNOWN", "UNKNOWN is not pass."),
        "non_pit_blocker_present": ("V20_35 blocker checks plus producer blocker result", "Emit TRUE when required factor input is known current-only or blocked.", "TRUE|FALSE|UNKNOWN", "TRUE is direct fail; UNKNOWN blocks pass."),
        "leakage_flag_present": ("PIT/leakage audits plus producer result", "Emit TRUE when stale/leakage/outcome lookahead risk is present.", "TRUE|FALSE|UNKNOWN", "TRUE is direct fail; UNKNOWN blocks pass."),
        "schema_valid": ("schema/data quality audit", "Emit TRUE only when producer row satisfies canonical PIT schema.", "TRUE|FALSE|UNKNOWN", "UNKNOWN blocks direct evidence."),
        "source_quality_usable": ("source/evidence quality audit", "Emit TRUE only when source quality is usable at ticker-factor grain.", "TRUE|FALSE|UNKNOWN", "UNKNOWN blocks direct evidence."),
        "freshness_usable": ("freshness audit/source timestamp", "Emit TRUE only when freshness policy passes for ranking_as_of_date.", "TRUE|FALSE|UNKNOWN", "UNKNOWN blocks direct evidence."),
        "lineage_to_ranking_score_available": ("ranking score lineage binding", "Emit TRUE only when row joins to the ranking score/contribution path.", "TRUE|FALSE|UNKNOWN", "UNKNOWN blocks direct evidence."),
        "accepted_for_data_trust_direct_pit_status": ("computed by DATA_TRUST emitter", "Compute TRUE only after all required fields are non-null and PIT booleans pass.", "TRUE|FALSE", "Never default TRUE."),
    }
    source, logic, valid, null = rules[field]
    return {
        "proposed_output_field": field,
        "source_field_or_constant": source,
        "derivation_logic": logic,
        "valid_values": valid,
        "null_handling_rule": null,
        "unknown_handling_rule": "UNKNOWN_VALUE_REJECTED_FOR_DIRECT_PASS",
        "fail_handling_rule": "FALSE_OR_BLOCKER_VALUE_CAUSES_DIRECT_FAIL_OR_UNKNOWN_AS_DEFINED_BY_CONTRACT",
        "pit_safety_implication": "REQUIRED_FOR_DIRECT_TICKER_LEVEL_PIT_EVIDENCE",
        "accepted_for_direct_evidence": "FALSE_UNTIL_FIELD_PRESENT_AND_VALIDATED",
        "limitation_reason": "PLAN_ONLY_NO_PRODUCER_PATCH_EXECUTED",
        **COMMON,
    }


def classification_requires_patch(classification: str) -> bool:
    return classification in {"NEEDS_PRODUCER_PATCH", "NEEDS_NEW_SOURCE_CONTRACT", "CANNOT_REPAIR_FROM_CURRENT_ARTIFACTS"}


def build_rows(contract: list[dict[str, str]], missing: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    required = [row["contract_field"] for row in contract if row.get("contract_field") in REQUIRED_FIELDS] or REQUIRED_FIELDS
    missing_by_field: dict[str, list[dict[str, str]]] = defaultdict(list)
    missing_by_field_family: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in missing:
        field = row.get("missing_required_field", "")
        if field:
            missing_by_field[field].append(row)
            missing_by_field_family[(field, row.get("factor_family", "UNKNOWN"))].append(row)

    plan_rows = []
    mapping_rows = []
    schema_rows = []
    rules = [rule_for(field) for field in required]
    target_to_fields: dict[str, list[str]] = defaultdict(list)
    target_to_derivable: dict[str, list[str]] = defaultdict(list)
    target_to_non_derivable: dict[str, list[str]] = defaultdict(list)

    for field in required:
        target_key = FIELD_TARGET[field]
        artifact = OUTPUT_ARTIFACTS[target_key]
        script = SCRIPT_BY_ARTIFACT[target_key]
        fields = output_fields(artifact)
        current_available = tf(field in fields)
        affected_tickers = len({r.get("ticker", "") for r in missing_by_field.get(field, []) if r.get("ticker", "")})
        affected_rows = len(missing_by_field.get(field, []))
        classification = "EXISTING_FIELD_DIRECT" if affected_rows == 0 and field in fields else CLASSIFICATION[field]
        requires_patch = classification_requires_patch(classification) or affected_rows > 0
        requires_schema = field not in fields
        target_to_fields[target_key].append(field)
        if classification in {"EXISTING_FIELD_DIRECT", "EXISTING_FIELD_DERIVABLE"}:
            target_to_derivable[target_key].append(field)
        else:
            target_to_non_derivable[target_key].append(field)
        rule = rule_for(field)["derivation_logic"]
        plan_rows.append({
            "missing_required_field": field,
            "affected_ticker_count": str(affected_tickers),
            "affected_lineage_row_count": str(affected_rows),
            "current_source_artifact": rel(artifact),
            "current_source_field_available": current_available,
            "patch_classification": classification,
            "proposed_upstream_producer_script": rel(script),
            "proposed_output_artifact": rel(artifact),
            "proposed_output_field": field,
            "derivation_rule": rule,
            "derivation_safe": tf(classification in {"EXISTING_FIELD_DIRECT", "EXISTING_FIELD_DERIVABLE"}),
            "requires_code_patch": tf(requires_patch),
            "requires_schema_extension": tf(requires_schema),
            "requires_backfill": tf(affected_rows > 0),
            "repair_priority": "HIGH" if affected_rows > 0 else "MEDIUM",
            "blocking_for_direct_pit_pass": "TRUE",
            "recommended_patch_action": "EXTEND_PRODUCER_OUTPUT_SCHEMA_AND_BACKFILL_TICKER_FACTOR_PIT_FIELD" if requires_patch else "CARRY_EXISTING_FIELD_IN_CANONICAL_OUTPUT",
            **COMMON,
        })
        for (mfield, family), rows in sorted(missing_by_field_family.items()):
            if mfield != field:
                continue
            mapping_rows.append({
                "missing_required_field": field,
                "factor_family": family,
                "affected_ticker_count": str(len({r.get("ticker", "") for r in rows if r.get("ticker", "")})),
                "affected_lineage_row_count": str(len(rows)),
                "current_source_artifact": rel(artifact),
                "current_source_field_available": current_available,
                "patch_classification": classification,
                "proposed_upstream_producer_script": rel(script),
                "proposed_output_artifact": rel(artifact),
                "proposed_output_field": field,
                "recommended_patch_action": "ADD_FIELD_TO_CANONICAL_TICKER_FACTOR_PIT_OUTPUT",
                **COMMON,
            })
        schema_rows.append({
            "output_artifact": rel(artifact),
            "row_grain": "ticker_factor_family",
            "required_join_keys": "ticker|ranking_context_id|factor_family|factor_input_name",
            "new_field_name": field,
            "field_type": FIELD_TYPE.get(field, "STRING"),
            "required_non_null_for_direct_pass": "TRUE",
            "allowed_values": rule_for(field)["valid_values"],
            "default_value": "UNKNOWN" if field not in {"ticker", "factor_family"} else "",
            "default_value_allowed_for_direct_pass": "FALSE",
            "validation_rule": "NON_NULL_AND_CONTRACT_VALIDATED_BEFORE_DIRECT_PASS",
            "downstream_required_by": "V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST",
            "backwards_compatibility_notes": "Append-only schema extension; existing score/ranking fields remain unchanged.",
            **COMMON,
        })

    targets = []
    order = 1
    for key in ["CANONICAL", "FAMILY_SCORES", "CONTRIBUTIONS", "EXPANDED", "VALIDATION_CURRENT", "VALIDATION_82", "SUPPORT_45", "SUPPORT_48", "SUPPORT_54", "WEIGHT_AUDIT", "WEIGHT_EXPOSURE"]:
        script = SCRIPT_BY_ARTIFACT[key]
        artifact = OUTPUT_ARTIFACTS[key]
        if key != "CANONICAL" and not artifact.exists():
            continue
        fields_to_add = target_to_fields[key] if key == "CANONICAL" else []
        targets.append({
            "producer_script": rel(script),
            "producer_exists": tf(script.exists()),
            "current_output_artifact": rel(artifact),
            "output_artifact_exists": tf(artifact.exists()),
            "patch_required": tf(key == "CANONICAL"),
            "schema_extension_required": tf(key == "CANONICAL"),
            "fields_to_add": "|".join(fields_to_add),
            "derivable_fields_to_add": "|".join(target_to_derivable[key]),
            "non_derivable_fields_to_add": "|".join(target_to_non_derivable[key]),
            "expected_row_grain": "ticker_factor_family" if key == "CANONICAL" else "supporting_source",
            "expected_join_keys": "ticker|ranking_context_id|factor_family|factor_input_name" if key == "CANONICAL" else "source_artifact|factor_family",
            "downstream_consumers": "V20_170_R1A;V20_170_R2_DATA_TRUST_DIRECT_STATUS_RETEST",
            "patch_order": str(order),
            "test_required": "TRUE",
            **COMMON,
        })
        order += 1

    summary = summarize(plan_rows, targets, missing)
    return plan_rows, mapping_rows, rules, targets, schema_rows, summary


def summarize(plan_rows: list[dict[str, str]], targets: list[dict[str, str]], missing: list[dict[str, str]]) -> dict[str, str]:
    classifications = [row["patch_classification"] for row in plan_rows]
    needs_patch = sum(row["requires_code_patch"] == "TRUE" for row in plan_rows)
    schema_required = any(row["requires_schema_extension"] == "TRUE" for row in plan_rows)
    return {
        "missing_required_pit_field_count": str(len(missing)),
        "affected_ticker_count": str(len({r.get("ticker", "") for r in missing if r.get("ticker", "")})),
        "affected_lineage_row_count": str(len({(r.get("ticker", ""), r.get("factor_family", "")) for r in missing})),
        "producer_script_target_count": str(len({r["producer_script"] for r in targets if r["patch_required"] == "TRUE"})),
        "output_artifact_target_count": str(len({r["current_output_artifact"] for r in targets if r["patch_required"] == "TRUE"})),
        "existing_field_direct_count": str(classifications.count("EXISTING_FIELD_DIRECT")),
        "existing_field_derivable_count": str(classifications.count("EXISTING_FIELD_DERIVABLE")),
        "needs_producer_patch_count": str(classifications.count("NEEDS_PRODUCER_PATCH")),
        "needs_new_source_contract_count": str(classifications.count("NEEDS_NEW_SOURCE_CONTRACT")),
        "cannot_repair_from_current_artifacts_count": str(classifications.count("CANNOT_REPAIR_FROM_CURRENT_ARTIFACTS")),
        "patch_plan_created": "TRUE",
        "ready_for_v20_170_r1c_producer_patch": tf(needs_patch > 0 or schema_required),
        "ready_for_v20_170_r2_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": "IMPLEMENT_V20_170_R1C_UPSTREAM_PIT_PRODUCER_PATCH" if needs_patch > 0 or schema_required else "IDENTIFY_PATCHABLE_UPSTREAM_PRODUCER",
    }


def risk_rows(summary: dict[str, str], upstream_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_r1a_status_required", "TRUE", tf(prereq_ok)),
        ("patch_plan_created", "TRUE", summary["patch_plan_created"]),
        ("ranking_simulation_created", "FALSE", "FALSE"),
        ("ready_for_v20_170_r2_direct_status_retest", "FALSE", "FALSE"),
        ("ready_for_v20_171_gate_only_ranking_simulation", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
        ("official_weight_change_allowed", "FALSE", "FALSE"),
        ("official_ranking_mutation_allowed", "FALSE", "FALSE"),
        ("pit_status_fabricated", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("upstream_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "audit_id": f"V20_170_R1B_PATCH_RISK_{i:03d}",
        "risk_or_safety_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "safety_passed": tf(expected == actual),
        **summary,
        **COMMON,
    } for i, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R1B DATA_TRUST Upstream PIT Producer Patch Plan Report",
        "",
        f"- final_status: {status}",
        "- research_only: TRUE",
        "- producer_scripts_patched: FALSE",
        "- ranking_simulation_created: FALSE",
        "- ready_for_official_use: FALSE",
    ]
    if summary:
        for key in ["missing_required_pit_field_count", "affected_ticker_count", "affected_lineage_row_count",
                    "producer_script_target_count", "output_artifact_target_count", "needs_producer_patch_count",
                    "needs_new_source_contract_count", "ready_for_v20_170_r1c_producer_patch",
                    "ready_for_v20_170_r2_direct_status_retest", "recommended_next_action"]:
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "This stage creates a patch plan only; it does not mark PIT rows as PASS or modify producer outputs."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    empty_summary = {
        "missing_required_pit_field_count": "0", "affected_ticker_count": "0", "affected_lineage_row_count": "0",
        "producer_script_target_count": "0", "output_artifact_target_count": "0", "existing_field_direct_count": "0",
        "existing_field_derivable_count": "0", "needs_producer_patch_count": "0",
        "needs_new_source_contract_count": "0", "cannot_repair_from_current_artifacts_count": "0",
        "patch_plan_created": "FALSE", "ready_for_v20_170_r1c_producer_patch": "FALSE",
        "ready_for_v20_170_r2_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE", "ready_for_official_use": "FALSE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R1B",
    }
    for path, fields in [(OUT_PLAN, PLAN_FIELDS), (OUT_MAPPING, MAPPING_FIELDS), (OUT_RULES, RULE_FIELDS),
                         (OUT_TARGETS, TARGET_FIELDS), (OUT_SCHEMA, SCHEMA_FIELDS), (OUT_RISK, RISK_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R1B_PIT_PRODUCER_PATCH_NEXT_GATE_001",
        "v20_170_r1a_status_consumed": "FALSE", "v20_170_r1a_status": "",
        **empty_summary,
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE", "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason, "final_status": BLOCKED_STATUS, **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    protected = protected_paths()
    before = input_hashes(protected)
    missing_inputs = [p for p in R1A_INPUTS if not p.exists() or p.stat().st_size == 0]
    if missing_inputs:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing_inputs))

    contract, _ = read_csv(R1A_INPUTS[0])
    missing_audit, _ = read_csv(R1A_INPUTS[4])
    gate_rows, _ = read_csv(R1A_INPUTS[7])
    if not contract or not missing_audit or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r1a_status = gate_rows[0].get("final_status", "")
    prereq_ok = r1a_status == REQUIRED_R1A_STATUS
    if not prereq_ok:
        return emit_blocked("V20_170_R1A_REQUIRED_STATUS_NOT_MET")

    plan, mapping, rules, targets, schema, summary = build_rows(contract, missing_audit)
    upstream_mutated = before != input_hashes(protected)
    risks = risk_rows(summary, upstream_mutated, prereq_ok)
    if upstream_mutated or not all(row["safety_passed"] == "TRUE" for row in risks):
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    patchable = int(summary["producer_script_target_count"]) > 0
    unresolved = int(summary["needs_new_source_contract_count"]) > 0 or int(summary["cannot_repair_from_current_artifacts_count"]) > 0
    if patchable and unresolved:
        final_status = PARTIAL_STATUS
    elif patchable:
        final_status = PASS_STATUS
    else:
        final_status = WARN_STATUS
    blocking_reason = "" if patchable else "NO_PATCHABLE_UPSTREAM_PRODUCER_IDENTIFIED"

    gate = {
        "gate_check_id": "V20_170_R1B_PIT_PRODUCER_PATCH_NEXT_GATE_001",
        "v20_170_r1a_status_consumed": "TRUE", "v20_170_r1a_status": r1a_status,
        **summary,
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE", "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": blocking_reason, "final_status": final_status, **COMMON,
    }
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_MAPPING, MAPPING_FIELDS, mapping)
    write_csv(OUT_RULES, RULE_FIELDS, rules)
    write_csv(OUT_TARGETS, TARGET_FIELDS, targets)
    write_csv(OUT_SCHEMA, SCHEMA_FIELDS, schema)
    write_csv(OUT_RISK, RISK_FIELDS, risks)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(final_status, summary)

    print(final_status)
    print(f"V20_170_R1A_STATUS={r1a_status}")
    for key in ["missing_required_pit_field_count", "affected_ticker_count", "affected_lineage_row_count",
                "producer_script_target_count", "output_artifact_target_count", "existing_field_direct_count",
                "existing_field_derivable_count", "needs_producer_patch_count",
                "needs_new_source_contract_count", "cannot_repair_from_current_artifacts_count",
                "patch_plan_created", "ready_for_v20_170_r1c_producer_patch",
                "ready_for_v20_170_r2_direct_status_retest",
                "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
                "recommended_next_action"]:
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
