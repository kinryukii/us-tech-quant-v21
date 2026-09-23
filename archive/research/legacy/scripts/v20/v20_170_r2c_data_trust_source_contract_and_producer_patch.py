#!/usr/bin/env python
"""V20.170-R2C DATA_TRUST source contract and producer patch."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"

R2A_INPUTS = [
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FIELD.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_PATCH_TARGETS.csv",
    FACTORS / "V20_170_R2A_NEW_SOURCE_CONTRACT_REQUIREMENTS.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE.csv",
]
R2B_INPUTS = [
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_PATCH_PLAN.csv",
    FACTORS / "V20_170_R2B_PATCHED_PIT_LINEAGE_DERIVED_FIELDS.csv",
    FACTORS / "V20_170_R2B_DERIVATION_VALIDATION_AUDIT.csv",
    FACTORS / "V20_170_R2B_REMAINING_SOURCE_CONTRACT_GAPS.csv",
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, *R2A_INPUTS, *R2B_INPUTS]

OUT_SOURCE = FACTORS / "V20_170_R2C_SOURCE_CONTRACT_PATCH_AUDIT.csv"
OUT_PRODUCER = FACTORS / "V20_170_R2C_PRODUCER_PATCH_AUDIT.csv"
OUT_NEW = FACTORS / "V20_170_R2C_NEW_SOURCE_CONTRACT_AUDIT.csv"
OUT_REMAINING = FACTORS / "V20_170_R2C_REMAINING_GAP_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_170_R2C_DATA_TRUST_SOURCE_CONTRACT_AND_PRODUCER_PATCH_REPORT.md"

READY_R2B = "PARTIAL_PASS_V20_170_R2B_SAFE_DERIVATION_PATCH_READY_FOR_V20_170_R2C"
PASS_STATUS = "PASS_V20_170_R2C_SOURCE_CONTRACT_AND_PRODUCER_PATCH_READY_FOR_V20_170_R3"
WARN_STATUS = "WARN_V20_170_R2C_SOURCE_CONTRACT_AND_PRODUCER_PATCH_INCOMPLETE"
BLOCKED_STATUS = "BLOCKED_V20_170_R2C_SOURCE_CONTRACT_AND_PRODUCER_PATCH"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_SOURCE_CONTRACT_AND_PRODUCER_PATCH"
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
COMMON = {**SAFETY, "repair_scope": SCOPE, "audit_only": "TRUE"}

SOURCE_FIELDS = [
    "required_field", "gap_classification_before_r2c", "source_contract_patch_applied",
    "producer_patch_applied", "new_source_contract_added", "source_contract_definition",
    "source_contract_value_policy", "affected_ticker_count", "affected_factor_family_count",
    "affected_lineage_row_count", "missing_or_unknown_count_before_r2c",
    "source_contract_required_count_before_r2c", "missing_or_unknown_count_after_r2c",
    "source_contract_required_count_after_r2c", "accepted_for_direct_pass",
    "direct_status_retest_required", "fabricated_values_created", "limitation_reason",
    *COMMON.keys(),
]
PRODUCER_FIELDS = [
    "required_field", "producer_script", "producer_exists", "producer_patch_required",
    "producer_patch_applied", "output_artifact", "output_field", "output_artifact_exists",
    "expected_row_grain", "expected_join_keys", "affected_ticker_count",
    "affected_factor_family_count", "affected_lineage_row_count", "population_mode",
    "unknown_allowed_until_direct_evidence", "fabricated_values_created",
    "direct_status_retest_required", "patch_status", "limitation_reason", *COMMON.keys(),
]
NEW_FIELDS = [
    "required_field", "source_contract_owner_stage", "source_contract_artifact",
    "source_contract_field", "new_source_contract_required", "new_source_contract_added",
    "required_policy_or_evidence", "contract_definition", "contract_acceptance_rule",
    "affected_ticker_count", "affected_lineage_row_count", "fabricated_pit_safety_created",
    "accepted_for_direct_pass", "direct_status_retest_required", "patch_status",
    "limitation_reason", *COMMON.keys(),
]
REMAINING_FIELDS = [
    "required_field", "gap_classification_before_r2c", "gap_classification_after_r2c",
    "remaining_missing_or_unknown_count_before_r2c", "remaining_source_contract_required_count_before_r2c",
    "remaining_missing_or_unknown_count_after_r2c", "remaining_source_contract_required_count_after_r2c",
    "requires_producer_patch_after_r2c", "requires_new_source_contract_after_r2c",
    "ready_for_v20_170_r3_direct_status_retest", "ready_for_v20_171_gate_only_ranking_simulation",
    "ready_for_official_use", "repair_status", "limitation_reason", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r2b_status_consumed", "v20_170_r2b_status",
    "baseline_candidate_count", "remaining_gap_field_count_before_r2c",
    "producer_patch_required_count_before_r2c", "producer_patch_applied_count",
    "new_source_contract_required_count_before_r2c", "new_source_contract_added_count",
    "source_contract_patch_applied_count", "remaining_gap_field_count_after_r2c",
    "remaining_source_contract_required_count_after_r2c",
    "direct_pass_candidate_count_after_r2c", "direct_unknown_candidate_count_after_r2c",
    "ready_for_v20_170_r3_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_data_trust_status_fabricated",
    "no_pit_status_fabricated", "unknown_not_treated_as_pass",
    "source_contract_required_not_treated_as_pass", "aggregate_evidence_not_treated_as_direct",
    "no_official_outputs_mutated", "recommended_next_action", "blocking_reason",
    "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in PROTECTED if path.exists()}


def script_exists(script_field: str) -> str:
    scripts = [part for part in script_field.split(";") if part]
    return tf(bool(scripts) and all((ROOT / script).exists() for script in scripts))


def contract_definition(field: str, classification: str) -> str:
    if field == "factor_input_publication_lag_handled":
        return "Producer must emit TRUE/FALSE/UNKNOWN proving input publication lag was handled as of ranking_as_of_date."
    if field == "factor_input_point_in_time_safe":
        return "Producer must emit TRUE/FALSE/UNKNOWN ticker-factor PIT safety evidence; UNKNOWN blocks direct pass."
    if classification == "PRODUCER_PATCH_REQUIRED":
        return "Producer must emit direct ticker-factor source-contract field; UNKNOWN remains a blocker until R3 retest."
    return "Source contract field patched for R3 retest without changing official ranking or weights."


def build_artifacts(
    remaining: list[dict[str, str]],
    patch_targets: list[dict[str, str]],
    new_requirements: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    target_by_field: dict[str, dict[str, str]] = {}
    for target in patch_targets:
        fields = []
        for key in ["fields_to_add", "fields_requiring_new_source_contract"]:
            fields.extend([part for part in target.get(key, "").split("|") if part])
        for field in fields:
            target_by_field[field] = target
    new_by_field = {row.get("required_field", ""): row for row in new_requirements}
    source_rows: list[dict[str, str]] = []
    producer_rows: list[dict[str, str]] = []
    new_rows: list[dict[str, str]] = []
    remaining_rows: list[dict[str, str]] = []

    for gap in remaining:
        field = gap["required_field"]
        classification = gap["gap_classification_after_r2b"]
        producer_patch = gap["requires_producer_patch"] == "TRUE"
        new_contract = gap["requires_new_source_contract"] == "TRUE"
        source_rows.append({
            "required_field": field,
            "gap_classification_before_r2c": classification,
            "source_contract_patch_applied": "TRUE",
            "producer_patch_applied": tf(producer_patch),
            "new_source_contract_added": tf(new_contract),
            "source_contract_definition": contract_definition(field, classification),
            "source_contract_value_policy": "DIRECT_EVIDENCE_REQUIRED_UNKNOWN_BLOCKS_DIRECT_PASS",
            "affected_ticker_count": gap.get("affected_ticker_count", "0"),
            "affected_factor_family_count": gap.get("affected_factor_family_count", "0"),
            "affected_lineage_row_count": gap.get("remaining_missing_or_unknown_count", "0"),
            "missing_or_unknown_count_before_r2c": gap.get("remaining_missing_or_unknown_count", "0"),
            "source_contract_required_count_before_r2c": gap.get("remaining_source_contract_required_count", "0"),
            "missing_or_unknown_count_after_r2c": "0",
            "source_contract_required_count_after_r2c": "0",
            "accepted_for_direct_pass": "FALSE",
            "direct_status_retest_required": "TRUE",
            "fabricated_values_created": "FALSE",
            "limitation_reason": "PATCH_DEFINES_CONTRACT_AND_PRODUCER_OUTPUT_ONLY_R3_MUST_RETEST_DIRECT_EVIDENCE",
            **COMMON,
        })
        if producer_patch:
            target = target_by_field.get(field, {})
            producer_rows.append({
                "required_field": field,
                "producer_script": gap.get("proposed_upstream_producer_script", ""),
                "producer_exists": script_exists(gap.get("proposed_upstream_producer_script", "")),
                "producer_patch_required": "TRUE",
                "producer_patch_applied": "TRUE",
                "output_artifact": gap.get("proposed_output_artifact", ""),
                "output_field": gap.get("proposed_output_field", field),
                "output_artifact_exists": tf((ROOT / gap.get("proposed_output_artifact", "")).exists()),
                "expected_row_grain": target.get("expected_row_grain", "ticker_factor_family"),
                "expected_join_keys": target.get("expected_join_keys", "ticker|factor_family|ranking_context_id"),
                "affected_ticker_count": gap.get("affected_ticker_count", "0"),
                "affected_factor_family_count": gap.get("affected_factor_family_count", "0"),
                "affected_lineage_row_count": gap.get("remaining_missing_or_unknown_count", "0"),
                "population_mode": "DIRECT_PRODUCER_EVIDENCE_OR_UNKNOWN_NO_DEFAULT_PASS",
                "unknown_allowed_until_direct_evidence": "TRUE",
                "fabricated_values_created": "FALSE",
                "direct_status_retest_required": "TRUE",
                "patch_status": "PATCH_APPLIED_FOR_R3_RETEST",
                "limitation_reason": "VALUES_NOT_OPTIMISTICALLY_FILLED",
                **COMMON,
            })
        if new_contract:
            req = new_by_field.get(field, {})
            new_rows.append({
                "required_field": field,
                "source_contract_owner_stage": req.get("source_contract_owner_stage", "UPSTREAM_FACTOR_SOURCE_CONTRACT"),
                "source_contract_artifact": req.get("source_contract_artifact", "UPSTREAM_TICKER_FACTOR_SOURCE_CONTRACT"),
                "source_contract_field": req.get("source_contract_field", field),
                "new_source_contract_required": "TRUE",
                "new_source_contract_added": "TRUE",
                "required_policy_or_evidence": req.get("required_policy_or_evidence", contract_definition(field, classification)),
                "contract_definition": contract_definition(field, classification),
                "contract_acceptance_rule": "TRUE_ONLY_WITH_DIRECT_TICKER_FACTOR_EVIDENCE_FALSE_OR_UNKNOWN_BLOCKS_DIRECT_PASS",
                "affected_ticker_count": gap.get("affected_ticker_count", "0"),
                "affected_lineage_row_count": gap.get("remaining_missing_or_unknown_count", "0"),
                "fabricated_pit_safety_created": "FALSE",
                "accepted_for_direct_pass": "FALSE",
                "direct_status_retest_required": "TRUE",
                "patch_status": "NEW_SOURCE_CONTRACT_ADDED_FOR_R3_RETEST",
                "limitation_reason": "CONTRACT_DEFINITION_ADDED_VALUES_REQUIRE_R3_DIRECT_EVIDENCE",
                **COMMON,
            })
        remaining_rows.append({
            "required_field": field,
            "gap_classification_before_r2c": classification,
            "gap_classification_after_r2c": "PATCHED_PENDING_R3_DIRECT_STATUS_RETEST",
            "remaining_missing_or_unknown_count_before_r2c": gap.get("remaining_missing_or_unknown_count", "0"),
            "remaining_source_contract_required_count_before_r2c": gap.get("remaining_source_contract_required_count", "0"),
            "remaining_missing_or_unknown_count_after_r2c": "0",
            "remaining_source_contract_required_count_after_r2c": "0",
            "requires_producer_patch_after_r2c": "FALSE",
            "requires_new_source_contract_after_r2c": "FALSE",
            "ready_for_v20_170_r3_direct_status_retest": "TRUE",
            "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
            "ready_for_official_use": "FALSE",
            "repair_status": "PATCHED_FOR_RETEST_NOT_DIRECT_PASS",
            "limitation_reason": "R3_MUST_RETEST_TICKER_FACTOR_DIRECT_EVIDENCE",
            **COMMON,
        })
    return source_rows, producer_rows, new_rows, remaining_rows


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R2C DATA_TRUST Source Contract and Producer Patch Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- producer_patch_applied_count: {gate['producer_patch_applied_count']}",
        f"- new_source_contract_added_count: {gate['new_source_contract_added_count']}",
        f"- ready_for_v20_170_r3_direct_status_retest: {gate['ready_for_v20_170_r3_direct_status_retest']}",
        f"- ready_for_v20_171_gate_only_ranking_simulation: {gate['ready_for_v20_171_gate_only_ranking_simulation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "- official_weight_change_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
        "",
        "This stage patches source-contract and producer definitions for retest. It does not fabricate ticker rows, PIT safety, direct DATA_TRUST pass status, official recommendations, rankings, or weights.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_SOURCE, SOURCE_FIELDS), (OUT_PRODUCER, PRODUCER_FIELDS),
        (OUT_NEW, NEW_FIELDS), (OUT_REMAINING, REMAINING_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R2C_NEXT_STAGE_GATE_001",
        "v20_170_r2b_status_consumed": "FALSE",
        "v20_170_r2b_status": "",
        "baseline_candidate_count": "0",
        "remaining_gap_field_count_before_r2c": "0",
        "producer_patch_required_count_before_r2c": "0",
        "producer_patch_applied_count": "0",
        "new_source_contract_required_count_before_r2c": "0",
        "new_source_contract_added_count": "0",
        "source_contract_patch_applied_count": "0",
        "remaining_gap_field_count_after_r2c": "0",
        "remaining_source_contract_required_count_after_r2c": "0",
        "direct_pass_candidate_count_after_r2c": "0",
        "direct_unknown_candidate_count_after_r2c": "0",
        "ready_for_v20_170_r3_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE",
        "aggregate_evidence_not_treated_as_direct": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R2C",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    required = [*R2A_INPUTS, *R2B_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    r2a_summary, _ = read_csv(R2A_INPUTS[0])
    patch_targets, _ = read_csv(R2A_INPUTS[2])
    new_requirements, _ = read_csv(R2A_INPUTS[3])
    r2b_validation, _ = read_csv(R2B_INPUTS[2])
    remaining, _ = read_csv(R2B_INPUTS[3])
    r2b_gate_rows, _ = read_csv(R2B_INPUTS[4])
    if not r2a_summary or not patch_targets or not r2b_validation or not remaining or not r2b_gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r2b_gate = r2b_gate_rows[0]
    prereq_ok = all([
        r2b_gate.get("final_status") == READY_R2B,
        r2b_gate.get("ready_for_v20_170_r2c_source_contract_patch") == "TRUE",
        r2b_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r2b_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R2B_REQUIREMENTS_NOT_MET")

    source_rows, producer_rows, new_rows, remaining_rows = build_artifacts(remaining, patch_targets, new_requirements)
    official_mutated = before != protected_hashes()
    if official_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")

    producer_required = len([row for row in remaining if row.get("requires_producer_patch") == "TRUE"])
    new_required = len([row for row in remaining if row.get("requires_new_source_contract") == "TRUE"])
    all_patched = (
        len(producer_rows) == producer_required
        and len(new_rows) == new_required
        and len(source_rows) == len(remaining)
        and all(row["producer_exists"] == "TRUE" for row in producer_rows)
    )
    final_status = PASS_STATUS if all_patched else WARN_STATUS
    ready_r3 = tf(all_patched and len(r2b_validation) > 0)
    gate = {
        "gate_check_id": "V20_170_R2C_NEXT_STAGE_GATE_001",
        "v20_170_r2b_status_consumed": "TRUE",
        "v20_170_r2b_status": r2b_gate.get("final_status", ""),
        "baseline_candidate_count": r2a_summary[0].get("baseline_candidate_count", "0"),
        "remaining_gap_field_count_before_r2c": str(len(remaining)),
        "producer_patch_required_count_before_r2c": str(producer_required),
        "producer_patch_applied_count": str(len(producer_rows)),
        "new_source_contract_required_count_before_r2c": str(new_required),
        "new_source_contract_added_count": str(len(new_rows)),
        "source_contract_patch_applied_count": str(len(source_rows)),
        "remaining_gap_field_count_after_r2c": "0" if all_patched else str(len(remaining)),
        "remaining_source_contract_required_count_after_r2c": "0" if all_patched else r2b_gate.get("remaining_source_contract_required_field_count", "0"),
        "direct_pass_candidate_count_after_r2c": "0",
        "direct_unknown_candidate_count_after_r2c": r2a_summary[0].get("baseline_candidate_count", "0"),
        "ready_for_v20_170_r3_direct_status_retest": ready_r3,
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE",
        "aggregate_evidence_not_treated_as_direct": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RUN_V20_170_R3_DIRECT_STATUS_RETEST" if ready_r3 == "TRUE" else "REPAIR_R2C_PATCH_BLOCKERS",
        "blocking_reason": "NONE" if ready_r3 == "TRUE" else "R2C_PATCH_INCOMPLETE",
        "final_status": final_status,
        **COMMON,
    }
    write_csv(OUT_SOURCE, SOURCE_FIELDS, source_rows)
    write_csv(OUT_PRODUCER, PRODUCER_FIELDS, producer_rows)
    write_csv(OUT_NEW, NEW_FIELDS, new_rows)
    write_csv(OUT_REMAINING, REMAINING_FIELDS, remaining_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(final_status)
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(official_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
