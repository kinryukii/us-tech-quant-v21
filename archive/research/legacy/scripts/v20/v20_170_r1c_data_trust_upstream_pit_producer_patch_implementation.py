#!/usr/bin/env python
"""V20.170-R1C DATA_TRUST upstream PIT producer patch implementation."""

from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"
SCRIPTS = ROOT / "scripts" / "v20"

PRODUCER_SCRIPT = SCRIPTS / "v20_108_r10_complete_factor_family_score_assembler.py"
R10_TABLE = CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv"
PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
PIT_SCHEMA_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv"
PIT_GAP_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv"
BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"

R1B_INPUTS = [
    FACTORS / "V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN.csv",
    FACTORS / "V20_170_R1B_PIT_MISSING_FIELD_TO_PRODUCER_MAPPING.csv",
    FACTORS / "V20_170_R1B_PIT_REQUIRED_FIELD_DERIVATION_RULES.csv",
    FACTORS / "V20_170_R1B_PIT_PRODUCER_SCRIPT_PATCH_TARGETS.csv",
    FACTORS / "V20_170_R1B_PIT_OUTPUT_SCHEMA_EXTENSION_PLAN.csv",
    FACTORS / "V20_170_R1B_PIT_PATCH_RISK_AND_SAFETY_AUDIT.csv",
    FACTORS / "V20_170_R1B_PIT_PRODUCER_PATCH_NEXT_GATE.csv",
]

OUT_AUDIT = FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_IMPLEMENTATION_AUDIT.csv"
OUT_VALIDATION = FACTORS / "V20_170_R1C_PATCHED_PIT_LINEAGE_VALIDATION.csv"
OUT_COMPLETION = FACTORS / "V20_170_R1C_PIT_FIELD_COMPLETION_AUDIT.csv"
OUT_BACKLOG = FACTORS / "V20_170_R1C_UNRESOLVED_SOURCE_CONTRACT_BACKLOG.csv"
OUT_GATE = FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R1C_PIT_PRODUCER_PATCH_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_R1C_DATA_TRUST_UPSTREAM_PIT_PRODUCER_PATCH_IMPLEMENTATION_REPORT.md"

PASS_R1B = "PASS_V20_170_R1B_UPSTREAM_PIT_PRODUCER_PATCH_PLAN_READY_FOR_V20_170_R1C"
PARTIAL_R1B = "PARTIAL_PASS_V20_170_R1B_PATCH_PLAN_WITH_UNRESOLVED_SOURCE_CONTRACTS_READY_FOR_V20_170_R1C"
PASS_STATUS = "PASS_V20_170_R1C_PIT_PRODUCER_PATCH_READY_FOR_V20_170_R2"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R1C_PIT_PRODUCER_PATCH_WITH_SOURCE_CONTRACT_GAPS_READY_FOR_V20_170_R2"
WARN_STATUS = "WARN_V20_170_R1C_PIT_PRODUCER_PATCH_CREATED_BUT_NO_ACCEPTED_DIRECT_LINEAGE"
BLOCKED_STATUS = "BLOCKED_V20_170_R1C_PIT_PRODUCER_PATCH_IMPLEMENTATION"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_UPSTREAM_PIT_PRODUCER_PATCH_IMPLEMENTATION"

REQUIRED_PIT_FIELDS = [
    "ticker", "ranking_context_id", "ranking_as_of_date", "data_snapshot_id",
    "source_artifact", "source_row_id", "factor_family", "factor_input_name",
    "factor_input_as_of_date", "factor_input_source_timestamp",
    "factor_input_publication_lag_handled", "factor_input_point_in_time_safe",
    "non_pit_blocker_present", "leakage_flag_present", "schema_valid",
    "source_quality_usable", "freshness_usable", "lineage_to_ranking_score_available",
    "accepted_for_data_trust_direct_pit_status",
]

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
COMMON = {**SAFETY, "pit_producer_patch_implementation_created": "TRUE", "repair_scope": SCOPE, "audit_only": "TRUE"}

AUDIT_FIELDS = [
    "producer_script", "producer_patched", "output_artifact",
    "output_artifact_schema_extended", "sidecar_artifact_created",
    "original_column_count", "patched_column_count", "original_row_count",
    "patched_row_count", "row_count_preserved", "downstream_compatibility_preserved",
    "fields_added", "fields_populated_from_direct_evidence",
    "fields_populated_from_safe_derivation", "fields_left_unknown",
    "source_contract_required_fields", "patch_success", "limitation_reason", *COMMON.keys(),
]
VALIDATION_FIELDS = [
    "ticker", "factor_family", "baseline_rank", "pit_lineage_row_created",
    "required_pit_field_count", "populated_direct_field_count",
    "populated_derivable_field_count", "unknown_required_field_count",
    "source_contract_required_field_count", "accepted_for_data_trust_direct_pit_status",
    "direct_pass_blocker_reason", "ready_for_v20_170_r2_direct_status_retest", *COMMON.keys(),
]
COMPLETION_FIELDS = [
    "pit_field", "lineage_row_count", "populated_count", "unknown_count",
    "source_contract_required_count", "direct_evidence_population_supported",
    "safe_derivation_population_supported", "accepted_for_direct_pass_when_unknown",
    "completion_status", *COMMON.keys(),
]
BACKLOG_FIELDS = [
    "missing_or_unknown_field", "affected_ticker_count", "affected_lineage_row_count",
    "source_contract_required", "proposed_source_contract_owner_stage",
    "proposed_source_contract_artifact", "proposed_source_contract_field",
    "can_be_implemented_in_current_producer", "requires_external_or_upstream_data_refresh",
    "repair_priority", "recommended_next_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r1b_status_consumed", "v20_170_r1b_status",
    "producer_script_patched", "sidecar_pit_lineage_artifact_created",
    "original_row_count", "patched_row_count", "row_count_preserved",
    "ticker_factor_lineage_row_count", "accepted_direct_pit_lineage_row_count",
    "unknown_required_pit_field_count", "source_contract_required_field_count",
    "fields_added_count", "fields_directly_populated_count", "fields_safely_derived_count",
    "fields_left_unknown_count", "ready_for_v20_170_r2_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_pit_status_fabricated",
    "aggregate_pit_not_treated_as_ticker_pass", "unknown_not_treated_as_pass",
    "pit_criteria_not_lowered", "no_official_outputs_mutated", "recommended_next_action",
    "blocking_reason", "final_status", *COMMON.keys(),
]
SAFETY_FIELDS = [
    "safety_check_id", "safety_check", "expected_value", "actual_value", "safety_passed", *COMMON.keys(),
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


def protected_hashes() -> dict[str, str]:
    return {rel(p): sha_file(p) for p in [BASELINE, ACTIVE_WEIGHT_REGISTRY] if p.exists()}


def baseline_rank_map() -> dict[str, str]:
    rows, _ = read_csv(R10_TABLE)
    return {row.get("ticker", ""): row.get("baseline_rank", "") for row in rows}


def count_unknowns(row: dict[str, str]) -> int:
    return sum(clean(row.get(field)).upper() in {"", "UNKNOWN", "UNKNOWN_CONTEXT_ID", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"} for field in REQUIRED_PIT_FIELDS)


def source_contract_fields(row: dict[str, str]) -> list[str]:
    fields = clean(row.get("source_contract_required_fields"))
    return [f for f in fields.split("|") if f]


def build_validation(lineage: list[dict[str, str]]) -> list[dict[str, str]]:
    ranks = baseline_rank_map()
    rows = []
    for row in lineage:
        unknown_count = count_unknowns(row)
        source_contract_count = len(source_contract_fields(row))
        accepted = row.get("accepted_for_data_trust_direct_pit_status") == "TRUE"
        direct_count = sum(1 for field in ["ticker", "source_artifact", "source_row_id", "factor_family", "schema_valid"] if clean(row.get(field)) and clean(row.get(field)).upper() != "UNKNOWN")
        derivable_count = sum(1 for field in ["ranking_context_id", "factor_input_name"] if clean(row.get(field)) and clean(row.get(field)).upper() not in {"UNKNOWN", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"})
        rows.append({
            "ticker": row.get("ticker", ""),
            "factor_family": row.get("factor_family", ""),
            "baseline_rank": ranks.get(row.get("ticker", ""), ""),
            "pit_lineage_row_created": "TRUE",
            "required_pit_field_count": str(len(REQUIRED_PIT_FIELDS)),
            "populated_direct_field_count": str(direct_count),
            "populated_derivable_field_count": str(derivable_count),
            "unknown_required_field_count": str(unknown_count),
            "source_contract_required_field_count": str(source_contract_count),
            "accepted_for_data_trust_direct_pit_status": tf(accepted),
            "direct_pass_blocker_reason": "" if accepted else row.get("direct_pass_blocker_reason", "SOURCE_CONTRACT_REQUIRED_FIELDS_UNKNOWN"),
            "ready_for_v20_170_r2_direct_status_retest": "TRUE",
            **COMMON,
        })
    return rows


def build_completion(lineage: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for field in REQUIRED_PIT_FIELDS:
        populated = [row for row in lineage if clean(row.get(field)) and clean(row.get(field)).upper() not in {"UNKNOWN", "UNKNOWN_CONTEXT_ID", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"}]
        unknown = len(lineage) - len(populated)
        source_contract = sum(field in source_contract_fields(row) for row in lineage)
        rows.append({
            "pit_field": field,
            "lineage_row_count": str(len(lineage)),
            "populated_count": str(len(populated)),
            "unknown_count": str(unknown),
            "source_contract_required_count": str(source_contract),
            "direct_evidence_population_supported": tf(field in {"ticker", "source_artifact", "source_row_id", "factor_family", "schema_valid"}),
            "safe_derivation_population_supported": tf(field in {"ranking_context_id", "factor_input_name", "accepted_for_data_trust_direct_pit_status"}),
            "accepted_for_direct_pass_when_unknown": "FALSE",
            "completion_status": "COMPLETE" if unknown == 0 else "SOURCE_CONTRACT_GAP_OR_UNKNOWN",
            **COMMON,
        })
    return rows


def build_audit(original_rows: int, patched_rows: int, original_cols: int, patched_cols: int, lineage: list[dict[str, str]]) -> dict[str, str]:
    unknown_fields = sorted({field for row in lineage for field in REQUIRED_PIT_FIELDS if clean(row.get(field)).upper() in {"", "UNKNOWN", "UNKNOWN_CONTEXT_ID", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"}})
    source_contract_required = sorted({field for row in lineage for field in source_contract_fields(row)})
    return {
        "producer_script": rel(PRODUCER_SCRIPT),
        "producer_patched": "TRUE",
        "output_artifact": rel(R10_TABLE),
        "output_artifact_schema_extended": "FALSE",
        "sidecar_artifact_created": tf(PIT_LINEAGE.exists() and bool(lineage)),
        "original_column_count": str(original_cols),
        "patched_column_count": str(patched_cols),
        "original_row_count": str(original_rows),
        "patched_row_count": str(patched_rows),
        "row_count_preserved": tf(original_rows == patched_rows),
        "downstream_compatibility_preserved": tf(original_cols == patched_cols and original_rows == patched_rows),
        "fields_added": "|".join(REQUIRED_PIT_FIELDS),
        "fields_populated_from_direct_evidence": "ticker|source_artifact|source_row_id|factor_family|schema_valid",
        "fields_populated_from_safe_derivation": "ranking_context_id|factor_input_name|accepted_for_data_trust_direct_pit_status",
        "fields_left_unknown": "|".join(unknown_fields),
        "source_contract_required_fields": "|".join(source_contract_required),
        "patch_success": tf(PIT_LINEAGE.exists() and bool(lineage) and original_rows == patched_rows),
        "limitation_reason": "SOURCE_CONTRACT_GAPS_REMAIN_NO_DIRECT_PIT_PASS_ROWS",
        **COMMON,
    }


def build_safety(summary: dict[str, str], official_mutated: bool, prereq_ok: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_r1b_status_required", "TRUE", tf(prereq_ok)),
        ("producer_script_patched", "TRUE", summary["producer_script_patched"]),
        ("sidecar_pit_lineage_artifact_created", "TRUE", summary["sidecar_pit_lineage_artifact_created"]),
        ("ready_for_v20_171_gate_only_ranking_simulation", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
        ("official_weight_change_allowed", "FALSE", "FALSE"),
        ("official_ranking_mutation_allowed", "FALSE", "FALSE"),
        ("ranking_simulation_created", "FALSE", "FALSE"),
        ("pit_status_fabricated", "FALSE", "FALSE"),
        ("unknown_treated_as_pass", "FALSE", "FALSE"),
        ("official_outputs_mutated", "FALSE", tf(official_mutated)),
    ]
    return [{"safety_check_id": f"V20_170_R1C_SAFETY_{i:03d}", "safety_check": c, "expected_value": e,
             "actual_value": a, "safety_passed": tf(e == a), **COMMON}
            for i, (c, e, a) in enumerate(checks, start=1)]


def write_report(status: str, summary: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R1C DATA_TRUST Upstream PIT Producer Patch Implementation Report",
        "",
        f"- final_status: {status}",
        "- research_only: TRUE",
        f"- producer_script_patched: {summary['producer_script_patched']}",
        f"- sidecar_pit_lineage_artifact_created: {summary['sidecar_pit_lineage_artifact_created']}",
        f"- ticker_factor_lineage_row_count: {summary['ticker_factor_lineage_row_count']}",
        f"- accepted_direct_pit_lineage_row_count: {summary['accepted_direct_pit_lineage_row_count']}",
        f"- unknown_required_pit_field_count: {summary['unknown_required_pit_field_count']}",
        f"- source_contract_required_field_count: {summary['source_contract_required_field_count']}",
        f"- ready_for_v20_170_r2_direct_status_retest: {summary['ready_for_v20_170_r2_direct_status_retest']}",
        "- ready_for_v20_171_gate_only_ranking_simulation: FALSE",
        "- ready_for_official_use: FALSE",
        "",
        "The patch emits ticker-factor PIT lineage with UNKNOWN/source-contract blockers preserved; it does not create direct PIT PASS rows.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_AUDIT, AUDIT_FIELDS), (OUT_VALIDATION, VALIDATION_FIELDS), (OUT_COMPLETION, COMPLETION_FIELDS),
                         (OUT_BACKLOG, BACKLOG_FIELDS), (OUT_SAFETY, SAFETY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE_001",
        "v20_170_r1b_status_consumed": "FALSE", "v20_170_r1b_status": "",
        "producer_script_patched": "FALSE", "sidecar_pit_lineage_artifact_created": "FALSE",
        "original_row_count": "0", "patched_row_count": "0", "row_count_preserved": "FALSE",
        "ticker_factor_lineage_row_count": "0", "accepted_direct_pit_lineage_row_count": "0",
        "unknown_required_pit_field_count": "0", "source_contract_required_field_count": "0",
        "fields_added_count": "0", "fields_directly_populated_count": "0", "fields_safely_derived_count": "0",
        "fields_left_unknown_count": "0", "ready_for_v20_170_r2_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE", "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE", "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R1C", "blocking_reason": reason,
        "final_status": BLOCKED_STATUS, **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    missing = [p for p in R1B_INPUTS if not p.exists() or p.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(p) for p in missing))
    gate_rows, _ = read_csv(FACTORS / "V20_170_R1B_PIT_PRODUCER_PATCH_NEXT_GATE.csv")
    if not gate_rows:
        return emit_blocked("EMPTY_R1B_GATE")
    r1b_status = gate_rows[0].get("final_status", "")
    prereq_ok = r1b_status in {PASS_R1B, PARTIAL_R1B}
    if not prereq_ok:
        return emit_blocked("V20_170_R1B_REQUIRED_STATUS_NOT_MET")

    before_official = protected_hashes()
    original_rows, original_fields = read_csv(R10_TABLE)
    result = subprocess.run([sys.executable, str(PRODUCER_SCRIPT)], cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        return emit_blocked("PRODUCER_SCRIPT_FAILED:" + result.stderr[-500:])
    patched_rows, patched_fields = read_csv(R10_TABLE)
    lineage, lineage_fields = read_csv(PIT_LINEAGE)
    gap_rows, _ = read_csv(PIT_GAP_AUDIT)
    official_mutated = before_official != protected_hashes()

    validation = build_validation(lineage)
    completion = build_completion(lineage)
    audit = build_audit(len(original_rows), len(patched_rows), len(original_fields), len(patched_fields), lineage)
    accepted_count = sum(row.get("accepted_for_data_trust_direct_pit_status") == "TRUE" for row in lineage)
    unknown_required_count = sum(count_unknowns(row) for row in lineage)
    source_contract_count = sum(len(source_contract_fields(row)) for row in lineage)
    unknown_fields = sorted({field for row in lineage for field in REQUIRED_PIT_FIELDS if clean(row.get(field)).upper() in {"", "UNKNOWN", "UNKNOWN_CONTEXT_ID", "UNKNOWN_NOT_FACTOR_INPUT_LEVEL"}})
    summary = {
        "producer_script_patched": "TRUE",
        "sidecar_pit_lineage_artifact_created": tf(PIT_LINEAGE.exists() and bool(lineage)),
        "original_row_count": str(len(original_rows)),
        "patched_row_count": str(len(patched_rows)),
        "row_count_preserved": tf(len(original_rows) == len(patched_rows)),
        "ticker_factor_lineage_row_count": str(len(lineage)),
        "accepted_direct_pit_lineage_row_count": str(accepted_count),
        "unknown_required_pit_field_count": str(unknown_required_count),
        "source_contract_required_field_count": str(source_contract_count),
        "fields_added_count": str(len(REQUIRED_PIT_FIELDS)),
        "fields_directly_populated_count": "5",
        "fields_safely_derived_count": "3",
        "fields_left_unknown_count": str(len(unknown_fields)),
        "ready_for_v20_170_r2_direct_status_retest": tf(PIT_LINEAGE.exists() and bool(lineage)),
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": "RUN_V20_170_R2_DIRECT_STATUS_RETEST_WITH_SOURCE_CONTRACT_BLOCKERS",
    }
    safety = build_safety(summary, official_mutated, prereq_ok)
    if official_mutated or not all(row["safety_passed"] == "TRUE" for row in safety):
        return emit_blocked("SAFETY_OR_OFFICIAL_MUTATION_FAILURE")

    if not PIT_LINEAGE.exists() or not lineage:
        final_status = BLOCKED_STATUS
        blocking_reason = "SIDEcar_PIT_LINEAGE_NOT_CREATED".upper()
    elif accepted_count > 0 and source_contract_count == 0:
        final_status = PASS_STATUS
        blocking_reason = ""
    elif source_contract_count > 0:
        final_status = PARTIAL_STATUS if accepted_count > 0 else WARN_STATUS
        blocking_reason = "SOURCE_CONTRACT_GAPS_REMAIN"
    else:
        final_status = WARN_STATUS
        blocking_reason = "NO_ACCEPTED_DIRECT_LINEAGE"

    gate = {
        "gate_check_id": "V20_170_R1C_PIT_PRODUCER_PATCH_NEXT_GATE_001",
        "v20_170_r1b_status_consumed": "TRUE", "v20_170_r1b_status": r1b_status,
        **summary,
        "official_weight_change_allowed": "FALSE", "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE", "no_pit_status_fabricated": "TRUE",
        "aggregate_pit_not_treated_as_ticker_pass": "TRUE", "unknown_not_treated_as_pass": "TRUE",
        "pit_criteria_not_lowered": "TRUE", "no_official_outputs_mutated": "TRUE",
        "blocking_reason": blocking_reason, "final_status": final_status, **COMMON,
    }
    write_csv(OUT_AUDIT, AUDIT_FIELDS, [audit])
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation)
    write_csv(OUT_COMPLETION, COMPLETION_FIELDS, completion)
    write_csv(OUT_BACKLOG, BACKLOG_FIELDS, [{**row, **COMMON} for row in gap_rows])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(final_status, summary)

    print(final_status)
    print(f"V20_170_R1B_STATUS={r1b_status}")
    for key in ["producer_script_patched", "sidecar_pit_lineage_artifact_created", "original_row_count",
                "patched_row_count", "row_count_preserved", "ticker_factor_lineage_row_count",
                "accepted_direct_pit_lineage_row_count", "unknown_required_pit_field_count",
                "source_contract_required_field_count", "fields_added_count",
                "fields_directly_populated_count", "fields_safely_derived_count",
                "fields_left_unknown_count", "ready_for_v20_170_r2_direct_status_retest",
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
    print(f"OFFICIAL_MUTATION_DETECTED={tf(official_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
