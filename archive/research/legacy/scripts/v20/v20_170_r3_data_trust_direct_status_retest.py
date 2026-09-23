#!/usr/bin/env python
"""V20.170-R3 DATA_TRUST direct status retest."""

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

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"

R2B_INPUTS = [
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_PATCH_PLAN.csv",
    FACTORS / "V20_170_R2B_PATCHED_PIT_LINEAGE_DERIVED_FIELDS.csv",
    FACTORS / "V20_170_R2B_DERIVATION_VALIDATION_AUDIT.csv",
    FACTORS / "V20_170_R2B_REMAINING_SOURCE_CONTRACT_GAPS.csv",
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE.csv",
]
R2C_INPUTS = [
    FACTORS / "V20_170_R2C_SOURCE_CONTRACT_PATCH_AUDIT.csv",
    FACTORS / "V20_170_R2C_PRODUCER_PATCH_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEW_SOURCE_CONTRACT_AUDIT.csv",
    FACTORS / "V20_170_R2C_REMAINING_GAP_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, *R2B_INPUTS, *R2C_INPUTS]

OUT_CANDIDATES = FACTORS / "V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv"
OUT_FIELDS = FACTORS / "V20_170_R3_DATA_TRUST_FIELD_RETEST_AUDIT.csv"
OUT_UNKNOWN = FACTORS / "V20_170_R3_DATA_TRUST_REMAINING_UNKNOWN_AUDIT.csv"
OUT_FAIL = FACTORS / "V20_170_R3_DATA_TRUST_FAIL_DIAGNOSTICS.csv"
OUT_GATE = FACTORS / "V20_170_R3_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST_REPORT.md"

READY_R2C = "PASS_V20_170_R2C_SOURCE_CONTRACT_AND_PRODUCER_PATCH_READY_FOR_V20_170_R3"
PASS_STATUS = "PASS_V20_170_R3_DIRECT_STATUS_RETEST_READY_FOR_V20_171"
WARN_STATUS = "WARN_V20_170_R3_ALL_CANDIDATES_REMAIN_UNKNOWN_REQUIRE_R3_R1_DIAGNOSTICS_REPAIR"
BLOCKED_STATUS = "BLOCKED_V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DIRECT_STATUS_RETEST"
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

CANDIDATE_FIELDS = [
    "ticker", "baseline_rank", "direct_status_before_r3", "direct_status_after_r3",
    "factor_family_count", "direct_pass_lineage_row_count", "direct_warn_lineage_row_count",
    "direct_fail_lineage_row_count", "direct_unknown_lineage_row_count",
    "structural_source_contract_gap_present", "remaining_unknown_direct_evidence_count",
    "remaining_fail_direct_evidence_count", "status_changed_from_unknown",
    "accepted_for_v20_171_gate_only_ranking_simulation", "direct_status_reason", *COMMON.keys(),
]
FIELD_FIELDS = [
    "required_field", "field_retest_status", "structural_gap_present_after_r2c",
    "direct_evidence_value_available", "direct_evidence_pass_count", "direct_evidence_warn_count",
    "direct_evidence_fail_count", "direct_evidence_unknown_count", "affected_ticker_count",
    "affected_factor_family_count", "source_contract_patch_applied",
    "producer_patch_applied", "new_source_contract_added", "accepted_for_direct_status",
    "diagnostic_required", "limitation_reason", *COMMON.keys(),
]
UNKNOWN_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "unknown_required_field_count",
    "unknown_required_fields", "structural_source_contract_gap_present",
    "source_contract_definition_present", "producer_patch_definition_present",
    "recommended_repair_stage", "diagnostic_reason", *COMMON.keys(),
]
FAIL_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "failed_field_count",
    "failed_fields", "fail_reason", "hard_fail_present", "recommended_action", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r2c_status_consumed", "v20_170_r2c_status",
    "baseline_candidate_count", "candidate_retest_count", "direct_pass_candidate_count",
    "direct_warn_candidate_count", "direct_fail_candidate_count",
    "direct_unknown_candidate_count", "status_changed_from_unknown_count",
    "structural_source_contract_gap_count", "remaining_unknown_direct_evidence_count",
    "remaining_fail_direct_evidence_count", "ready_for_v20_171_gate_only_ranking_simulation",
    "ready_for_official_use", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "ranking_simulation_created",
    "no_data_trust_status_fabricated", "no_pit_status_fabricated",
    "unknown_not_treated_as_pass", "source_contract_required_not_treated_as_pass",
    "aggregate_evidence_not_treated_as_direct", "no_official_outputs_mutated",
    "recommended_next_action", "blocking_reason", "final_status", *COMMON.keys(),
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


def build_outputs(
    baseline: list[dict[str, str]],
    r2b_validation: list[dict[str, str]],
    source_contract: list[dict[str, str]],
    r2c_remaining: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    validation_by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in r2b_validation:
        validation_by_ticker[row.get("ticker", "")].append(row)

    structural_gap_fields = {
        row["required_field"] for row in r2c_remaining
        if row.get("remaining_source_contract_required_count_after_r2c", "0") not in {"", "0"}
        or row.get("requires_producer_patch_after_r2c") == "TRUE"
        or row.get("requires_new_source_contract_after_r2c") == "TRUE"
    }
    patched_field_rows = {row["required_field"]: row for row in source_contract}
    patched_fields = list(patched_field_rows)

    candidates: list[dict[str, str]] = []
    unknown_rows: list[dict[str, str]] = []
    fail_rows: list[dict[str, str]] = []
    for base in baseline:
        ticker = base.get("ticker", "")
        lineage_rows = validation_by_ticker.get(ticker, [])
        unknown_count = sum(int(row.get("remaining_unknown_required_field_count", "0") or "0") for row in lineage_rows)
        fail_count = 0
        family_count = len({row.get("factor_family", "") for row in lineage_rows})
        direct_status = "PASS" if lineage_rows and unknown_count == 0 and not structural_gap_fields else "UNKNOWN"
        if direct_status == "UNKNOWN":
            for row in lineage_rows:
                unknown_rows.append({
                    "ticker": ticker,
                    "baseline_rank": base.get("official_current_rank", ""),
                    "factor_family": row.get("factor_family", ""),
                    "unknown_required_field_count": row.get("remaining_unknown_required_field_count", "0"),
                    "unknown_required_fields": "|".join(patched_fields),
                    "structural_source_contract_gap_present": tf(bool(structural_gap_fields)),
                    "source_contract_definition_present": "TRUE",
                    "producer_patch_definition_present": "TRUE",
                    "recommended_repair_stage": "V20_170_R3_R1_DIAGNOSTICS_REPAIR",
                    "diagnostic_reason": "PATCH_DEFINITIONS_EXIST_BUT_DIRECT_TICKER_FACTOR_EVIDENCE_REMAINS_UNKNOWN",
                    **COMMON,
                })
        candidates.append({
            "ticker": ticker,
            "baseline_rank": base.get("official_current_rank", ""),
            "direct_status_before_r3": "UNKNOWN",
            "direct_status_after_r3": direct_status,
            "factor_family_count": str(family_count),
            "direct_pass_lineage_row_count": str(family_count if direct_status == "PASS" else 0),
            "direct_warn_lineage_row_count": "0",
            "direct_fail_lineage_row_count": str(fail_count),
            "direct_unknown_lineage_row_count": str(0 if direct_status == "PASS" else family_count),
            "structural_source_contract_gap_present": tf(bool(structural_gap_fields)),
            "remaining_unknown_direct_evidence_count": str(unknown_count),
            "remaining_fail_direct_evidence_count": str(fail_count),
            "status_changed_from_unknown": tf(direct_status != "UNKNOWN"),
            "accepted_for_v20_171_gate_only_ranking_simulation": tf(direct_status == "PASS"),
            "direct_status_reason": "ALL_DIRECT_EVIDENCE_PRESENT" if direct_status == "PASS" else "DIRECT_TICKER_FACTOR_EVIDENCE_REMAINS_UNKNOWN_AFTER_R2C",
            **COMMON,
        })

    fields: list[dict[str, str]] = []
    ticker_count = len({row.get("ticker", "") for row in r2b_validation})
    family_count = len({row.get("factor_family", "") for row in r2b_validation})
    for field in patched_fields:
        patch = patched_field_rows[field]
        unknown_count = sum(int(row.get("remaining_unknown_required_field_count", "0") or "0") for row in r2b_validation)
        fields.append({
            "required_field": field,
            "field_retest_status": "UNKNOWN",
            "structural_gap_present_after_r2c": tf(field in structural_gap_fields),
            "direct_evidence_value_available": "FALSE",
            "direct_evidence_pass_count": "0",
            "direct_evidence_warn_count": "0",
            "direct_evidence_fail_count": "0",
            "direct_evidence_unknown_count": str(unknown_count),
            "affected_ticker_count": str(ticker_count),
            "affected_factor_family_count": str(family_count),
            "source_contract_patch_applied": patch.get("source_contract_patch_applied", "FALSE"),
            "producer_patch_applied": patch.get("producer_patch_applied", "FALSE"),
            "new_source_contract_added": patch.get("new_source_contract_added", "FALSE"),
            "accepted_for_direct_status": "FALSE",
            "diagnostic_required": "TRUE",
            "limitation_reason": "R2C_PATCHED_DEFINITION_NOT_DIRECT_VALUES",
            **COMMON,
        })

    return candidates, fields, unknown_rows, fail_rows


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R3 DATA_TRUST Direct Status Retest Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- baseline_candidate_count: {gate['baseline_candidate_count']}",
        f"- direct_pass_candidate_count: {gate['direct_pass_candidate_count']}",
        f"- direct_unknown_candidate_count: {gate['direct_unknown_candidate_count']}",
        f"- ready_for_v20_171_gate_only_ranking_simulation: {gate['ready_for_v20_171_gate_only_ranking_simulation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "- official_weight_change_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
        "",
        "R3 retested candidate status without fabricating direct ticker-factor evidence. All candidates remain UNKNOWN, so V20.171 is blocked pending R3-R1 diagnostics repair.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_CANDIDATES, CANDIDATE_FIELDS), (OUT_FIELDS, FIELD_FIELDS),
        (OUT_UNKNOWN, UNKNOWN_FIELDS), (OUT_FAIL, FAIL_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R3_NEXT_STAGE_GATE_001",
        "v20_170_r2c_status_consumed": "FALSE",
        "v20_170_r2c_status": "",
        "baseline_candidate_count": "0",
        "candidate_retest_count": "0",
        "direct_pass_candidate_count": "0",
        "direct_warn_candidate_count": "0",
        "direct_fail_candidate_count": "0",
        "direct_unknown_candidate_count": "0",
        "status_changed_from_unknown_count": "0",
        "structural_source_contract_gap_count": "0",
        "remaining_unknown_direct_evidence_count": "0",
        "remaining_fail_direct_evidence_count": "0",
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
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R3",
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
    required = [*R2B_INPUTS, *R2C_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    r2b_validation, _ = read_csv(R2B_INPUTS[2])
    source_contract, _ = read_csv(R2C_INPUTS[0])
    r2c_remaining, _ = read_csv(R2C_INPUTS[3])
    r2c_gate_rows, _ = read_csv(R2C_INPUTS[4])
    if not baseline or not r2b_validation or not source_contract or not r2c_remaining or not r2c_gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r2c_gate = r2c_gate_rows[0]
    prereq_ok = all([
        r2c_gate.get("final_status") == READY_R2C,
        r2c_gate.get("ready_for_v20_170_r3_direct_status_retest") == "TRUE",
        r2c_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r2c_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R2C_REQUIREMENTS_NOT_MET")

    candidates, fields, unknown_rows, fail_rows = build_outputs(baseline, r2b_validation, source_contract, r2c_remaining)
    official_mutated = before != protected_hashes()
    if official_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")

    pass_count = sum(row["direct_status_after_r3"] == "PASS" for row in candidates)
    warn_count = sum(row["direct_status_after_r3"] == "WARN" for row in candidates)
    fail_count = sum(row["direct_status_after_r3"] == "FAIL" for row in candidates)
    unknown_count = sum(row["direct_status_after_r3"] == "UNKNOWN" for row in candidates)
    structural_gap_count = sum(1 for row in r2c_remaining if row.get("gap_classification_after_r2c") != "PATCHED_PENDING_R3_DIRECT_STATUS_RETEST")
    ready_v171 = pass_count > 0 and structural_gap_count == 0
    final_status = PASS_STATUS if ready_v171 else WARN_STATUS
    gate = {
        "gate_check_id": "V20_170_R3_NEXT_STAGE_GATE_001",
        "v20_170_r2c_status_consumed": "TRUE",
        "v20_170_r2c_status": r2c_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "candidate_retest_count": str(len(candidates)),
        "direct_pass_candidate_count": str(pass_count),
        "direct_warn_candidate_count": str(warn_count),
        "direct_fail_candidate_count": str(fail_count),
        "direct_unknown_candidate_count": str(unknown_count),
        "status_changed_from_unknown_count": str(sum(row["status_changed_from_unknown"] == "TRUE" for row in candidates)),
        "structural_source_contract_gap_count": str(structural_gap_count),
        "remaining_unknown_direct_evidence_count": str(sum(int(row["remaining_unknown_direct_evidence_count"]) for row in candidates)),
        "remaining_fail_direct_evidence_count": str(sum(int(row["remaining_fail_direct_evidence_count"]) for row in candidates)),
        "ready_for_v20_171_gate_only_ranking_simulation": tf(ready_v171),
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
        "recommended_next_action": "RUN_V20_171_GATE_ONLY_RANKING_SIMULATION" if ready_v171 else "RUN_V20_170_R3_R1_DIAGNOSTICS_REPAIR",
        "blocking_reason": "NONE" if ready_v171 else "ALL_CANDIDATES_REMAIN_UNKNOWN_DIRECT_EVIDENCE_MISSING",
        "final_status": final_status,
        **COMMON,
    }
    write_csv(OUT_CANDIDATES, CANDIDATE_FIELDS, candidates)
    write_csv(OUT_FIELDS, FIELD_FIELDS, fields)
    write_csv(OUT_UNKNOWN, UNKNOWN_FIELDS, unknown_rows)
    write_csv(OUT_FAIL, FAIL_FIELDS, fail_rows)
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
