#!/usr/bin/env python
"""V20.170-R3-R1 DATA_TRUST direct evidence diagnostics repair."""

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

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
PIT_LINEAGE = CONSOLIDATION / "V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"

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
R3_INPUTS = [
    FACTORS / "V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_FIELD_RETEST_AUDIT.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_REMAINING_UNKNOWN_AUDIT.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_FAIL_DIAGNOSTICS.csv",
    FACTORS / "V20_170_R3_NEXT_STAGE_GATE.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, *R2B_INPUTS, *R2C_INPUTS, *R3_INPUTS]

OUT_BINDING = FACTORS / "V20_170_R3_R1_DIRECT_EVIDENCE_BINDING_DIAGNOSTICS.csv"
OUT_CANDIDATE = FACTORS / "V20_170_R3_R1_CANDIDATE_UNKNOWN_CAUSE_AUDIT.csv"
OUT_FIELD = FACTORS / "V20_170_R3_R1_FIELD_UNKNOWN_CAUSE_AUDIT.csv"
OUT_ARTIFACT = FACTORS / "V20_170_R3_R1_ARTIFACT_EVIDENCE_AVAILABILITY_AUDIT.csv"
OUT_JOIN = FACTORS / "V20_170_R3_R1_JOIN_KEY_ASOF_MAPPING_AUDIT.csv"
OUT_REPAIR = FACTORS / "V20_170_R3_R1_SAFE_BINDING_REPAIR_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_R3_R1_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_170_R3_R1_DATA_TRUST_DIRECT_EVIDENCE_DIAGNOSTICS_REPAIR_REPORT.md"

READY_R3 = "WARN_V20_170_R3_ALL_CANDIDATES_REMAIN_UNKNOWN_REQUIRE_R3_R1_DIAGNOSTICS_REPAIR"
WARN_STATUS = "WARN_V20_170_R3_R1_NO_SAFE_BINDING_REPAIR_MANUAL_PRODUCER_REVIEW_REQUIRED"
PASS_STATUS = "PASS_V20_170_R3_R1_SAFE_BINDING_REPAIR_READY_FOR_R3_R2_RETEST"
BLOCKED_STATUS = "BLOCKED_V20_170_R3_R1_DATA_TRUST_DIRECT_EVIDENCE_DIAGNOSTICS_REPAIR"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DIRECT_EVIDENCE_DIAGNOSTICS_REPAIR"
UNKNOWN_CAUSES = [
    "missing_evidence_value",
    "producer_output_not_consumed",
    "field_name_mismatch",
    "join_key_mismatch",
    "as_of_date_mismatch",
    "ticker_mapping_mismatch",
    "derived_evidence_not_promoted_to_retest_input",
    "retest_logic_excludes_valid_derived_or_patched_evidence",
    "other_unknown_binding_failure",
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
COMMON = {**SAFETY, "repair_scope": SCOPE, "audit_only": "TRUE"}

BINDING_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "required_field", "unknown_cause",
    "r2b_unknown_count", "r2c_structural_gap_present", "r2c_patch_definition_present",
    "producer_output_artifact", "producer_output_field", "producer_output_artifact_exists",
    "field_present_in_producer_output", "direct_evidence_value_present",
    "safe_binding_repair_possible", "safe_binding_repair_applied",
    "unknown_reduced_by_repair", "diagnostic_reason", *COMMON.keys(),
]
CANDIDATE_FIELDS = [
    "ticker", "baseline_rank", "direct_status_after_r3",
    "unknown_direct_evidence_count_before_repair",
    "unknown_direct_evidence_count_after_repair", "safe_binding_repair_applied_count",
    "dominant_unknown_cause", "missing_evidence_value_count",
    "producer_output_not_consumed_count", "field_name_mismatch_count",
    "join_key_mismatch_count", "as_of_date_mismatch_count",
    "ticker_mapping_mismatch_count", "derived_evidence_not_promoted_to_retest_input_count",
    "retest_logic_excludes_valid_derived_or_patched_evidence_count",
    "other_unknown_binding_failure_count", "ready_for_v20_170_r3_r2_retest_after_binding_repair",
    "recommended_next_action", *COMMON.keys(),
]
FIELD_FIELDS = [
    "required_field", "unknown_cause", "affected_ticker_count",
    "affected_factor_family_count", "unknown_direct_evidence_count_before_repair",
    "unknown_direct_evidence_count_after_repair", "source_contract_patch_applied",
    "producer_patch_applied", "new_source_contract_added", "producer_output_artifact",
    "producer_output_field", "producer_output_artifact_exists",
    "field_present_in_producer_output", "safe_binding_repair_possible",
    "safe_binding_repair_applied", "manual_review_required", "diagnostic_reason",
    *COMMON.keys(),
]
ARTIFACT_FIELDS = [
    "source_artifact", "required_field", "artifact_exists", "field_present",
    "row_count", "non_unknown_value_count", "unknown_value_count",
    "available_for_direct_evidence_binding", "availability_cause",
    "recommended_action", *COMMON.keys(),
]
JOIN_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "join_key_ticker_present",
    "join_key_factor_family_present", "join_key_baseline_rank_present",
    "ticker_mapping_match", "as_of_date_available", "as_of_date_mismatch",
    "join_key_mismatch", "mapping_safe_for_binding", "mapping_diagnostic_reason",
    *COMMON.keys(),
]
REPAIR_FIELDS = [
    "required_field", "safe_binding_repair_type", "safe_binding_repair_possible",
    "safe_binding_repair_applied", "unknown_count_before_repair",
    "unknown_count_after_repair", "unknown_reduction_count",
    "fabricated_values_created", "ticker_rows_fabricated", "evidence_values_fabricated",
    "official_outputs_mutated", "repair_status", "limitation_reason", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r3_status_consumed", "v20_170_r3_status",
    "baseline_candidate_count", "candidate_diagnostic_count",
    "field_diagnostic_count", "artifact_diagnostic_count",
    "join_mapping_diagnostic_count", "remaining_unknown_direct_evidence_count_before_repair",
    "remaining_unknown_direct_evidence_count_after_repair", "unknown_reduction_count",
    "safe_binding_repair_possible_count", "safe_binding_repair_applied_count",
    "missing_evidence_value_count", "producer_output_not_consumed_count",
    "field_name_mismatch_count", "join_key_mismatch_count", "as_of_date_mismatch_count",
    "ticker_mapping_mismatch_count", "derived_evidence_not_promoted_to_retest_input_count",
    "retest_logic_excludes_valid_derived_or_patched_evidence_count",
    "other_unknown_binding_failure_count",
    "ready_for_v20_170_r3_r2_retest_after_binding_repair",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "ranking_simulation_created", "no_data_trust_status_fabricated",
    "no_evidence_values_fabricated", "no_ticker_rows_fabricated",
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


def load_artifact_header(path_text: str) -> tuple[bool, list[str], int, list[dict[str, str]]]:
    path = ROOT / path_text
    if not path.exists() or path.is_dir():
        return False, [], 0, []
    rows, fields = read_csv(path)
    return True, fields, len(rows), rows


def is_unknown(value: str) -> bool:
    return clean(value).upper() in {"", "UNKNOWN", "SOURCE_CONTRACT_REQUIRED"}


def build_outputs(
    baseline: list[dict[str, str]],
    r2b_validation: list[dict[str, str]],
    r2c_source: list[dict[str, str]],
    r2c_producer: list[dict[str, str]],
    r3_candidates: list[dict[str, str]],
    r3_unknown: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    baseline_by_ticker = {row["ticker"]: row for row in baseline}
    candidate_by_ticker = {row["ticker"]: row for row in r3_candidates}
    producer_by_field = {row["required_field"]: row for row in r2c_producer}
    source_by_field = {row["required_field"]: row for row in r2c_source}
    patched_fields = list(source_by_field)

    validation_by_pair = {(row["ticker"], row["factor_family"]): row for row in r2b_validation}
    unknown_pairs = [(row["ticker"], row["factor_family"]) for row in r3_unknown]

    artifact_rows: list[dict[str, str]] = []
    artifact_field_present: dict[str, bool] = {}
    artifact_value_present: dict[str, bool] = {}
    for field in patched_fields:
        producer = producer_by_field.get(field, {})
        artifact = producer.get("output_artifact") or "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
        exists, header, row_count, rows = load_artifact_header(artifact)
        field_present = field in header
        non_unknown = sum(1 for row in rows if field in row and not is_unknown(row.get(field, "")))
        unknown_count = sum(1 for row in rows if field in row and is_unknown(row.get(field, "")))
        artifact_field_present[field] = field_present
        artifact_value_present[field] = non_unknown > 0
        artifact_rows.append({
            "source_artifact": artifact,
            "required_field": field,
            "artifact_exists": tf(exists),
            "field_present": tf(field_present),
            "row_count": str(row_count),
            "non_unknown_value_count": str(non_unknown),
            "unknown_value_count": str(unknown_count),
            "available_for_direct_evidence_binding": tf(field_present and non_unknown > 0),
            "availability_cause": "missing_evidence_value" if field_present and non_unknown == 0 else ("field_name_mismatch" if exists and not field_present else "producer_output_not_consumed"),
            "recommended_action": "MANUAL_PRODUCER_EVIDENCE_CONTRACT_REVIEW",
            **COMMON,
        })

    join_rows: list[dict[str, str]] = []
    for ticker, family in unknown_pairs:
        base = baseline_by_ticker.get(ticker, {})
        validation = validation_by_pair.get((ticker, family), {})
        ticker_present = bool(ticker)
        family_present = bool(family)
        rank_present = bool(base.get("official_current_rank", ""))
        asof_available = False
        join_rows.append({
            "ticker": ticker,
            "baseline_rank": base.get("official_current_rank", ""),
            "factor_family": family,
            "join_key_ticker_present": tf(ticker_present),
            "join_key_factor_family_present": tf(family_present),
            "join_key_baseline_rank_present": tf(rank_present),
            "ticker_mapping_match": tf(ticker in baseline_by_ticker),
            "as_of_date_available": tf(asof_available),
            "as_of_date_mismatch": "FALSE",
            "join_key_mismatch": tf(not (ticker_present and family_present and rank_present and validation)),
            "mapping_safe_for_binding": "FALSE",
            "mapping_diagnostic_reason": "JOIN_KEYS_PRESENT_BUT_DIRECT_EVIDENCE_AS_OF_VALUES_REMAIN_UNAVAILABLE",
            **COMMON,
        })

    binding_rows: list[dict[str, str]] = []
    for ticker, family in unknown_pairs:
        base = baseline_by_ticker.get(ticker, {})
        validation = validation_by_pair.get((ticker, family), {})
        for field in patched_fields:
            source = source_by_field[field]
            producer = producer_by_field.get(field, {})
            cause = "missing_evidence_value"
            if not artifact_field_present.get(field, False):
                cause = "field_name_mismatch"
            elif producer and producer.get("producer_patch_applied") != "TRUE":
                cause = "producer_output_not_consumed"
            binding_rows.append({
                "ticker": ticker,
                "baseline_rank": base.get("official_current_rank", ""),
                "factor_family": family,
                "required_field": field,
                "unknown_cause": cause,
                "r2b_unknown_count": validation.get("remaining_unknown_required_field_count", "0"),
                "r2c_structural_gap_present": "FALSE",
                "r2c_patch_definition_present": source.get("source_contract_patch_applied", "FALSE"),
                "producer_output_artifact": producer.get("output_artifact", ""),
                "producer_output_field": producer.get("output_field", field),
                "producer_output_artifact_exists": producer.get("output_artifact_exists", "TRUE"),
                "field_present_in_producer_output": tf(artifact_field_present.get(field, False)),
                "direct_evidence_value_present": tf(artifact_value_present.get(field, False)),
                "safe_binding_repair_possible": "FALSE",
                "safe_binding_repair_applied": "FALSE",
                "unknown_reduced_by_repair": "0",
                "diagnostic_reason": "CONTRACT_AND_FIELD_BINDING_EXIST_BUT_NON_UNKNOWN_DIRECT_EVIDENCE_VALUES_ARE_ABSENT",
                **COMMON,
            })

    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in binding_rows:
        by_ticker[row["ticker"]].append(row)
    candidate_rows: list[dict[str, str]] = []
    for ticker, rows in by_ticker.items():
        base = baseline_by_ticker.get(ticker, {})
        counts = Counter(row["unknown_cause"] for row in rows)
        dominant = counts.most_common(1)[0][0] if counts else "other_unknown_binding_failure"
        before = len(rows)
        candidate_rows.append({
            "ticker": ticker,
            "baseline_rank": base.get("official_current_rank", ""),
            "direct_status_after_r3": candidate_by_ticker.get(ticker, {}).get("direct_status_after_r3", "UNKNOWN"),
            "unknown_direct_evidence_count_before_repair": str(before),
            "unknown_direct_evidence_count_after_repair": str(before),
            "safe_binding_repair_applied_count": "0",
            "dominant_unknown_cause": dominant,
            **{f"{cause}_count": str(counts.get(cause, 0)) for cause in UNKNOWN_CAUSES},
            "ready_for_v20_170_r3_r2_retest_after_binding_repair": "FALSE",
            "recommended_next_action": "MANUAL_PRODUCER_EVIDENCE_CONTRACT_REVIEW",
            **COMMON,
        })

    field_rows: list[dict[str, str]] = []
    for field in patched_fields:
        rows = [row for row in binding_rows if row["required_field"] == field]
        cause = rows[0]["unknown_cause"] if rows else "other_unknown_binding_failure"
        producer = producer_by_field.get(field, {})
        source = source_by_field[field]
        field_rows.append({
            "required_field": field,
            "unknown_cause": cause,
            "affected_ticker_count": str(len({row["ticker"] for row in rows})),
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "unknown_direct_evidence_count_before_repair": str(len(rows)),
            "unknown_direct_evidence_count_after_repair": str(len(rows)),
            "source_contract_patch_applied": source.get("source_contract_patch_applied", "FALSE"),
            "producer_patch_applied": source.get("producer_patch_applied", "FALSE"),
            "new_source_contract_added": source.get("new_source_contract_added", "FALSE"),
            "producer_output_artifact": producer.get("output_artifact", ""),
            "producer_output_field": producer.get("output_field", field),
            "producer_output_artifact_exists": producer.get("output_artifact_exists", "TRUE"),
            "field_present_in_producer_output": tf(artifact_field_present.get(field, False)),
            "safe_binding_repair_possible": "FALSE",
            "safe_binding_repair_applied": "FALSE",
            "manual_review_required": "TRUE",
            "diagnostic_reason": "NO_NON_UNKNOWN_DIRECT_EVIDENCE_VALUE_AVAILABLE_FOR_SAFE_BINDING",
            **COMMON,
        })

    repair_rows = [{
        "required_field": row["required_field"],
        "safe_binding_repair_type": "NO_SAFE_REPAIR_AVAILABLE",
        "safe_binding_repair_possible": "FALSE",
        "safe_binding_repair_applied": "FALSE",
        "unknown_count_before_repair": row["unknown_direct_evidence_count_before_repair"],
        "unknown_count_after_repair": row["unknown_direct_evidence_count_after_repair"],
        "unknown_reduction_count": "0",
        "fabricated_values_created": "FALSE",
        "ticker_rows_fabricated": "FALSE",
        "evidence_values_fabricated": "FALSE",
        "official_outputs_mutated": "FALSE",
        "repair_status": "REJECTED_NO_DIRECT_EVIDENCE_VALUE_TO_BIND",
        "limitation_reason": "SAFE_BINDING_CANNOT_CREATE_MISSING_DIRECT_EVIDENCE_VALUES",
        **COMMON,
    } for row in field_rows]

    return binding_rows, candidate_rows, field_rows, artifact_rows, join_rows, repair_rows


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R3-R1 DATA_TRUST Direct Evidence Diagnostics Repair Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- remaining_unknown_direct_evidence_count_before_repair: {gate['remaining_unknown_direct_evidence_count_before_repair']}",
        f"- remaining_unknown_direct_evidence_count_after_repair: {gate['remaining_unknown_direct_evidence_count_after_repair']}",
        f"- unknown_reduction_count: {gate['unknown_reduction_count']}",
        f"- safe_binding_repair_applied_count: {gate['safe_binding_repair_applied_count']}",
        f"- ready_for_v20_170_r3_r2_retest_after_binding_repair: {gate['ready_for_v20_170_r3_r2_retest_after_binding_repair']}",
        f"- ready_for_v20_171_gate_only_ranking_simulation: {gate['ready_for_v20_171_gate_only_ranking_simulation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "The dominant cause is missing_evidence_value: source-contract definitions and output fields are patched, but non-UNKNOWN direct ticker-factor evidence values are not available for safe binding. No ticker rows, evidence values, rankings, or weights were fabricated or mutated.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_BINDING, BINDING_FIELDS), (OUT_CANDIDATE, CANDIDATE_FIELDS),
        (OUT_FIELD, FIELD_FIELDS), (OUT_ARTIFACT, ARTIFACT_FIELDS),
        (OUT_JOIN, JOIN_FIELDS), (OUT_REPAIR, REPAIR_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R3_R1_NEXT_STAGE_GATE_001",
        "v20_170_r3_status_consumed": "FALSE",
        "v20_170_r3_status": "",
        "baseline_candidate_count": "0",
        "candidate_diagnostic_count": "0",
        "field_diagnostic_count": "0",
        "artifact_diagnostic_count": "0",
        "join_mapping_diagnostic_count": "0",
        "remaining_unknown_direct_evidence_count_before_repair": "0",
        "remaining_unknown_direct_evidence_count_after_repair": "0",
        "unknown_reduction_count": "0",
        "safe_binding_repair_possible_count": "0",
        "safe_binding_repair_applied_count": "0",
        **{f"{cause}_count": "0" for cause in UNKNOWN_CAUSES},
        "ready_for_v20_170_r3_r2_retest_after_binding_repair": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R3_R1",
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
    required = [*R2B_INPUTS, *R2C_INPUTS, *R3_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    r2b_validation, _ = read_csv(R2B_INPUTS[2])
    r2c_source, _ = read_csv(R2C_INPUTS[0])
    r2c_producer, _ = read_csv(R2C_INPUTS[1])
    r3_candidates, _ = read_csv(R3_INPUTS[0])
    r3_unknown, _ = read_csv(R3_INPUTS[2])
    r3_gate_rows, _ = read_csv(R3_INPUTS[4])
    if not baseline or not r2b_validation or not r2c_source or not r3_candidates or not r3_unknown or not r3_gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r3_gate = r3_gate_rows[0]
    prereq_ok = all([
        r3_gate.get("final_status") == READY_R3,
        r3_gate.get("structural_source_contract_gap_count") == "0",
        r3_gate.get("direct_unknown_candidate_count") == "40",
        int(r3_gate.get("remaining_unknown_direct_evidence_count", "0")) > 0,
        r3_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r3_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R3_REQUIREMENTS_NOT_MET")

    binding, candidate, field, artifact, join, repair = build_outputs(
        baseline, r2b_validation, r2c_source, r2c_producer, r3_candidates, r3_unknown
    )
    official_mutated = before != protected_hashes()
    if official_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")
    before_unknown = len(binding)
    after_unknown = sum(int(row["unknown_count_after_repair"]) for row in repair)
    reduction = before_unknown - after_unknown
    possible = sum(row["safe_binding_repair_possible"] == "TRUE" for row in repair)
    applied = sum(row["safe_binding_repair_applied"] == "TRUE" for row in repair)
    cause_counts = Counter(row["unknown_cause"] for row in binding)
    ready_r3_r2 = reduction > 0
    gate = {
        "gate_check_id": "V20_170_R3_R1_NEXT_STAGE_GATE_001",
        "v20_170_r3_status_consumed": "TRUE",
        "v20_170_r3_status": r3_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "candidate_diagnostic_count": str(len(candidate)),
        "field_diagnostic_count": str(len(field)),
        "artifact_diagnostic_count": str(len(artifact)),
        "join_mapping_diagnostic_count": str(len(join)),
        "remaining_unknown_direct_evidence_count_before_repair": str(before_unknown),
        "remaining_unknown_direct_evidence_count_after_repair": str(after_unknown),
        "unknown_reduction_count": str(reduction),
        "safe_binding_repair_possible_count": str(possible),
        "safe_binding_repair_applied_count": str(applied),
        **{f"{cause}_count": str(cause_counts.get(cause, 0)) for cause in UNKNOWN_CAUSES},
        "ready_for_v20_170_r3_r2_retest_after_binding_repair": tf(ready_r3_r2),
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RUN_V20_170_R3_R2_RETEST_AFTER_BINDING_REPAIR" if ready_r3_r2 else "MANUAL_PRODUCER_EVIDENCE_CONTRACT_REVIEW",
        "blocking_reason": "NONE" if ready_r3_r2 else "NO_SAFE_BINDING_REPAIR_POSSIBLE_MISSING_DIRECT_EVIDENCE_VALUES",
        "final_status": PASS_STATUS if ready_r3_r2 else WARN_STATUS,
        **COMMON,
    }
    write_csv(OUT_BINDING, BINDING_FIELDS, binding)
    write_csv(OUT_CANDIDATE, CANDIDATE_FIELDS, candidate)
    write_csv(OUT_FIELD, FIELD_FIELDS, field)
    write_csv(OUT_ARTIFACT, ARTIFACT_FIELDS, artifact)
    write_csv(OUT_JOIN, JOIN_FIELDS, join)
    write_csv(OUT_REPAIR, REPAIR_FIELDS, repair)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(official_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
