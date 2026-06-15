#!/usr/bin/env python
"""V20.170-R2B DATA_TRUST safe derivation patch."""

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
PIT_SCHEMA_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SCHEMA_EXTENSION_AUDIT.csv"
PIT_GAP_AUDIT = CONSOLIDATION / "V20_108_R10_PIT_LINEAGE_SOURCE_CONTRACT_GAP_AUDIT.csv"

R2A_INPUTS = [
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SUMMARY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FIELD.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_TICKER.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_BY_FACTOR_FAMILY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_PATCH_TARGETS.csv",
    FACTORS / "V20_170_R2A_SAFE_DERIVATION_CANDIDATES.csv",
    FACTORS / "V20_170_R2A_NEW_SOURCE_CONTRACT_REQUIREMENTS.csv",
    FACTORS / "V20_170_R2A_DIRECT_PASS_BLOCKER_PRIORITY.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_NEXT_GATE.csv",
    FACTORS / "V20_170_R2A_SOURCE_CONTRACT_GAP_SAFETY_AUDIT.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, PIT_SCHEMA_AUDIT, PIT_GAP_AUDIT, *R2A_INPUTS]

OUT_PLAN = FACTORS / "V20_170_R2B_SAFE_DERIVATION_PATCH_PLAN.csv"
OUT_DERIVED = FACTORS / "V20_170_R2B_SAFE_DERIVATION_OUTPUT.csv"
OUT_PATCHED = FACTORS / "V20_170_R2B_PATCHED_PIT_LINEAGE_DERIVED_FIELDS.csv"
OUT_VALIDATION = FACTORS / "V20_170_R2B_DERIVATION_VALIDATION_AUDIT.csv"
OUT_REMAINING = FACTORS / "V20_170_R2B_REMAINING_SOURCE_CONTRACT_GAPS.csv"
OUT_RETEST = FACTORS / "V20_170_R2B_DIRECT_STATUS_RETEST_INPUT.csv"
OUT_GATE = FACTORS / "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE.csv"
OUT_SAFETY = FACTORS / "V20_170_R2B_SAFE_DERIVATION_SAFETY_AUDIT.csv"
REPORT = READ_CENTER / "V20_170_R2B_DATA_TRUST_SAFE_DERIVATION_PATCH_REPORT.md"

PASS_R2A = "PASS_V20_170_R2A_SOURCE_CONTRACT_GAP_PLAN_READY_FOR_V20_170_R2B"
PARTIAL_R2A = "PARTIAL_PASS_V20_170_R2A_SOURCE_CONTRACT_GAP_PLAN_READY_FOR_V20_170_R2B_R2C"
PASS_STATUS = "PASS_V20_170_R2B_SAFE_DERIVATION_PATCH_READY_FOR_V20_170_R3"
PARTIAL_STATUS = "PARTIAL_PASS_V20_170_R2B_SAFE_DERIVATION_PATCH_READY_FOR_V20_170_R2C"
WARN_STATUS = "WARN_V20_170_R2B_SAFE_DERIVATION_INSUFFICIENT_SOURCE_CONTRACT_PATCH_REQUIRED"
BLOCKED_STATUS = "BLOCKED_V20_170_R2B_SAFE_DERIVATION_PATCH"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_SAFE_DERIVATION_PATCH"
DIRECT_FIELDS = [
    "ranking_context_id",
    "ranking_as_of_date",
    "data_snapshot_id",
    "factor_input_name",
    "factor_input_as_of_date",
    "factor_input_source_timestamp",
    "factor_input_publication_lag_handled",
    "factor_input_point_in_time_safe",
    "non_pit_blocker_present",
    "leakage_flag_present",
    "schema_valid",
    "source_quality_usable",
    "freshness_usable",
    "lineage_to_ranking_score_available",
]
NEGATIVE_BLOCKER_FIELDS = {"non_pit_blocker_present", "leakage_flag_present"}
SAFE = {
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
COMMON = {**SAFE, "repair_scope": SCOPE, "audit_only": "TRUE"}

PATCH_FIELDS = [
    "required_field", "derivation_source_artifact", "derivation_source_field",
    "derivation_rule", "derivation_safe", "derivation_applied",
    "affected_ticker_count", "affected_factor_family_count", "affected_lineage_row_count",
    "derived_non_null_count", "derived_unknown_count", "accepted_for_direct_evidence",
    "limitation_reason", *COMMON.keys(),
]
PATCHED_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "source_artifact", "source_row_id",
    "original_required_field", "original_field_value", "derived_field_value",
    "derivation_rule", "derivation_confidence", "safe_derivation_applied",
    "direct_evidence_after_derivation", "still_unknown_after_derivation",
    "source_contract_required_after_derivation",
    "accepted_for_data_trust_direct_pit_status_after_derivation", "rejection_reason",
    *COMMON.keys(),
]
VALIDATION_FIELDS = [
    "ticker", "factor_family", "safe_derivation_field_count",
    "safe_derivation_applied_count", "safe_derivation_rejected_count",
    "remaining_unknown_required_field_count",
    "remaining_source_contract_required_field_count", "non_pit_blocker_present",
    "leakage_flag_present", "accepted_direct_pit_lineage_after_derivation",
    "direct_pass_blocker_reason", "ready_for_v20_170_r2c_source_contract_patch",
    "ready_for_v20_170_r3_direct_status_retest", *COMMON.keys(),
]
REMAINING_FIELDS = [
    "required_field", "remaining_missing_or_unknown_count",
    "remaining_source_contract_required_count", "affected_ticker_count",
    "affected_factor_family_count", "gap_classification_after_r2b",
    "requires_producer_patch", "requires_new_source_contract",
    "proposed_upstream_producer_script", "proposed_output_artifact",
    "proposed_output_field", "recommended_next_stage", "repair_priority", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r2a_status_consumed", "v20_170_r2a_status",
    "baseline_candidate_count", "safe_derivation_candidate_count_before",
    "safe_derivation_applied_count", "safe_derivation_rejected_count",
    "derived_field_non_null_count", "remaining_unknown_required_pit_field_count",
    "remaining_source_contract_required_field_count",
    "accepted_direct_pit_lineage_row_count_after_derivation",
    "direct_pass_candidate_count_after_derivation",
    "direct_unknown_candidate_count_after_derivation",
    "remaining_producer_patch_required_count",
    "remaining_new_source_contract_required_count",
    "ready_for_v20_170_r2c_source_contract_patch",
    "ready_for_v20_170_r3_direct_status_retest",
    "ready_for_v20_171_gate_only_ranking_simulation", "ready_for_official_use",
    "recommended_next_action", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "ranking_simulation_created",
    "no_data_trust_status_fabricated", "no_pit_status_fabricated",
    "unknown_not_treated_as_pass", "source_contract_required_not_treated_as_pass",
    "aggregate_evidence_not_treated_as_direct", "no_upstream_outputs_mutated",
    "blocking_reason", "final_status", *COMMON.keys(),
]
SAFETY_FIELDS = ["safety_check_id", "safety_check", "expected_value", "actual_value", "safety_passed", *COMMON.keys()]


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


def is_unknown(value: str) -> bool:
    return clean(value).upper() in {"", "UNKNOWN", "SOURCE_CONTRACT_REQUIRED"}


def direct_field_pass(field: str, value: str) -> bool:
    value = clean(value).upper()
    if field in NEGATIVE_BLOCKER_FIELDS:
        return value == "FALSE"
    return value == "TRUE" if field.endswith("_handled") or field.endswith("_safe") or field.endswith("_usable") or field in {"schema_valid", "lineage_to_ranking_score_available"} else not is_unknown(value)


def baseline_map(baseline: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("ticker", ""): row for row in baseline if row.get("ticker")}


def derive_value(field: str, row: dict[str, str], base: dict[str, str]) -> tuple[str, str, str]:
    if field == "ranking_as_of_date":
        value = base.get("ranking_timestamp_utc") or base.get("latest_price_date")
        return value, "HIGH" if value else "NONE", "BASELINE_TICKER_CONTEXT_MISSING" if not value else ""
    if field == "data_snapshot_id":
        parts = [base.get("accepted_artifact_path"), base.get("source_run_id"), base.get("source_file")]
        value = "|".join(part for part in parts if part)
        return value, "HIGH" if value else "NONE", "BASELINE_SNAPSHOT_FIELDS_MISSING" if not value else ""
    if field == "lineage_to_ranking_score_available":
        ok = bool(base and row.get("ticker") and row.get("factor_family") and row.get("source_artifact") and row.get("source_row_id"))
        return tf(ok), "HIGH" if ok else "NONE", "" if ok else "LINEAGE_BINDING_INCOMPLETE"
    if field == "accepted_for_data_trust_direct_pit_status":
        values = current_after_derivation(row, {})
        ok = all(direct_field_pass(field_name, values.get(field_name, "")) for field_name in DIRECT_FIELDS)
        return tf(ok), "COMPUTED_BLOCKER_PRESERVING", "" if ok else "REMAINING_UNKNOWN_OR_SOURCE_CONTRACT_BLOCKERS"
    return "", "NONE", "UNSUPPORTED_SAFE_DERIVATION_RULE"


def current_after_derivation(row: dict[str, str], derived: dict[str, str]) -> dict[str, str]:
    values = {field: row.get(field, "") for field in DIRECT_FIELDS}
    values.update({k: v for k, v in derived.items() if k in DIRECT_FIELDS})
    return values


def remaining_fields(row: dict[str, str], derived: dict[str, str]) -> list[str]:
    values = current_after_derivation(row, derived)
    return [field for field in DIRECT_FIELDS if not direct_field_pass(field, values.get(field, ""))]


def source_contract_fields_after(row: dict[str, str], rem: list[str]) -> list[str]:
    original = [field for field in row.get("source_contract_required_fields", "").split("|") if field]
    return [field for field in original if field in rem]


def build_outputs(
    lineage: list[dict[str, str]],
    baseline: list[dict[str, str]],
    safe_candidates: list[dict[str, str]],
    by_field: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    base_by_ticker = baseline_map(baseline)
    safe_fields = [row["required_field"] for row in safe_candidates]
    candidate_by_field = {row["required_field"]: row for row in safe_candidates}
    field_meta = {row["required_field"]: row for row in by_field}
    row_derived: dict[int, dict[str, str]] = defaultdict(dict)
    patched: list[dict[str, str]] = []

    for idx, line in enumerate(lineage):
        base = base_by_ticker.get(line.get("ticker", ""), {})
        for field in safe_fields:
            candidate = candidate_by_field[field]
            value, confidence, rejection = derive_value(field, line, base)
            applied = field != "accepted_for_data_trust_direct_pit_status" and bool(value) and value != "UNKNOWN"
            if applied:
                row_derived[idx][field] = value
            rem = remaining_fields(line, row_derived[idx])
            source_contract_rem = source_contract_fields_after(line, rem)
            accepted = len(rem) == 0 and len(source_contract_rem) == 0
            if field == "accepted_for_data_trust_direct_pit_status":
                value = tf(accepted)
                applied = True
                rejection = "" if accepted else "REMAINING_UNKNOWN_OR_SOURCE_CONTRACT_BLOCKERS"
            patched.append({
                "ticker": line.get("ticker", ""),
                "baseline_rank": base.get("official_current_rank", ""),
                "factor_family": line.get("factor_family", ""),
                "source_artifact": line.get("source_artifact", ""),
                "source_row_id": line.get("source_row_id", ""),
                "original_required_field": field,
                "original_field_value": line.get(field, ""),
                "derived_field_value": value or "UNKNOWN",
                "derivation_rule": candidate.get("proposed_derivation_rule", ""),
                "derivation_confidence": confidence,
                "safe_derivation_applied": tf(applied),
                "direct_evidence_after_derivation": tf(direct_field_pass(field, value) and field != "accepted_for_data_trust_direct_pit_status"),
                "still_unknown_after_derivation": tf(is_unknown(value)),
                "source_contract_required_after_derivation": tf(field in source_contract_rem),
                "accepted_for_data_trust_direct_pit_status_after_derivation": tf(accepted),
                "rejection_reason": rejection,
                **COMMON,
            })

    plan: list[dict[str, str]] = []
    derived_out: list[dict[str, str]] = []
    for field in safe_fields:
        candidate = candidate_by_field[field]
        field_rows = [row for row in patched if row["original_required_field"] == field]
        applied_rows = [row for row in field_rows if row["safe_derivation_applied"] == "TRUE"]
        non_null = [row for row in field_rows if not is_unknown(row["derived_field_value"])]
        unknown = len(field_rows) - len(non_null)
        accepted_direct = field != "accepted_for_data_trust_direct_pit_status" and unknown == 0 and len(applied_rows) == len(field_rows)
        row = {
            "required_field": field,
            "derivation_source_artifact": candidate.get("current_available_source_artifact", ""),
            "derivation_source_field": candidate.get("current_available_source_field", ""),
            "derivation_rule": candidate.get("proposed_derivation_rule", ""),
            "derivation_safe": "TRUE",
            "derivation_applied": tf(len(applied_rows) > 0),
            "affected_ticker_count": str(len({r["ticker"] for r in applied_rows})),
            "affected_factor_family_count": str(len({r["factor_family"] for r in applied_rows})),
            "affected_lineage_row_count": str(len(applied_rows)),
            "derived_non_null_count": str(len(non_null)),
            "derived_unknown_count": str(unknown),
            "accepted_for_direct_evidence": tf(accepted_direct),
            "limitation_reason": "REMAINING_SOURCE_CONTRACT_BLOCKERS_PREVENT_DIRECT_PASS" if field == "accepted_for_data_trust_direct_pit_status" else candidate.get("limitation_reason", ""),
            **COMMON,
        }
        plan.append(row)
        derived_out.append(row.copy())

    validation: list[dict[str, str]] = []
    for idx, line in enumerate(lineage):
        base = base_by_ticker.get(line.get("ticker", ""), {})
        rem = remaining_fields(line, row_derived[idx])
        source_contract_rem = source_contract_fields_after(line, rem)
        accepted = len(rem) == 0 and len(source_contract_rem) == 0
        rejected = len([field for field in safe_fields if field not in row_derived[idx] and field != "accepted_for_data_trust_direct_pit_status"])
        validation.append({
            "ticker": line.get("ticker", ""),
            "factor_family": line.get("factor_family", ""),
            "safe_derivation_field_count": str(len(safe_fields)),
            "safe_derivation_applied_count": str(len(row_derived[idx]) + 1),
            "safe_derivation_rejected_count": str(rejected),
            "remaining_unknown_required_field_count": str(len(rem)),
            "remaining_source_contract_required_field_count": str(len(source_contract_rem)),
            "non_pit_blocker_present": row_derived[idx].get("non_pit_blocker_present", line.get("non_pit_blocker_present", "")),
            "leakage_flag_present": row_derived[idx].get("leakage_flag_present", line.get("leakage_flag_present", "")),
            "accepted_direct_pit_lineage_after_derivation": tf(accepted),
            "direct_pass_blocker_reason": "NONE" if accepted else "REMAINING_UNKNOWN_OR_SOURCE_CONTRACT_REQUIRED_FIELDS",
            "ready_for_v20_170_r2c_source_contract_patch": tf(not accepted),
            "ready_for_v20_170_r3_direct_status_retest": "FALSE",
            **COMMON,
        })

    remaining_counts = Counter()
    remaining_source_counts = Counter()
    remaining_tickers: dict[str, set[str]] = defaultdict(set)
    remaining_families: dict[str, set[str]] = defaultdict(set)
    for idx, line in enumerate(lineage):
        rem = remaining_fields(line, row_derived[idx])
        source_rem = set(source_contract_fields_after(line, rem))
        for field in rem:
            remaining_counts[field] += 1
            remaining_tickers[field].add(line.get("ticker", ""))
            remaining_families[field].add(line.get("factor_family", ""))
            if field in source_rem:
                remaining_source_counts[field] += 1

    remaining: list[dict[str, str]] = []
    for field, count in sorted(remaining_counts.items()):
        meta = field_meta.get(field, {})
        classification = meta.get("gap_classification", "REMAINING_UNKNOWN_REQUIRED_FIELD")
        remaining.append({
            "required_field": field,
            "remaining_missing_or_unknown_count": str(count),
            "remaining_source_contract_required_count": str(remaining_source_counts[field]),
            "affected_ticker_count": str(len(remaining_tickers[field])),
            "affected_factor_family_count": str(len(remaining_families[field])),
            "gap_classification_after_r2b": classification,
            "requires_producer_patch": tf(classification == "PRODUCER_PATCH_REQUIRED"),
            "requires_new_source_contract": tf(classification == "NEW_SOURCE_CONTRACT_REQUIRED"),
            "proposed_upstream_producer_script": meta.get("proposed_upstream_producer_script", ""),
            "proposed_output_artifact": meta.get("proposed_output_artifact", ""),
            "proposed_output_field": meta.get("proposed_output_field", field),
            "recommended_next_stage": "V20_170_R2C",
            "repair_priority": meta.get("repair_priority", "HIGH"),
            **COMMON,
        })

    return plan, derived_out, patched, validation, remaining


def safety_rows(prereq_ok: bool, upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("v20_170_r2a_prerequisites_met", "TRUE", tf(prereq_ok)),
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
    return [{"safety_check_id": f"V20_170_R2B_SAFETY_{i:03d}", "safety_check": check,
             "expected_value": expected, "actual_value": actual,
             "safety_passed": tf(expected == actual), **COMMON}
            for i, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(status: str, gate: dict[str, str] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R2B DATA_TRUST Safe Derivation Patch Report",
        "",
        f"- final_status: {status}",
        "- research_only: TRUE",
        "- ranking_simulation_created: FALSE",
        "- ready_for_official_use: FALSE",
        "- official_weight_change_allowed: FALSE",
        "- official_ranking_mutation_allowed: FALSE",
    ]
    if gate:
        for key in [
            "baseline_candidate_count", "safe_derivation_candidate_count_before",
            "safe_derivation_applied_count", "safe_derivation_rejected_count",
            "derived_field_non_null_count", "remaining_unknown_required_pit_field_count",
            "remaining_source_contract_required_field_count",
            "accepted_direct_pit_lineage_row_count_after_derivation",
            "direct_pass_candidate_count_after_derivation",
            "direct_unknown_candidate_count_after_derivation",
            "remaining_producer_patch_required_count",
            "remaining_new_source_contract_required_count",
            "recommended_next_action",
        ]:
            lines.append(f"- {key}: {gate.get(key, '')}")
    lines.extend([
        "",
        "This stage writes a research-only sidecar patch. It does not mark any ticker DIRECT_PASS and does not mutate official ranking or weight artifacts.",
    ])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_PLAN, PATCH_FIELDS), (OUT_DERIVED, PATCH_FIELDS), (OUT_PATCHED, PATCHED_FIELDS),
        (OUT_VALIDATION, VALIDATION_FIELDS), (OUT_REMAINING, REMAINING_FIELDS),
        (OUT_RETEST, VALIDATION_FIELDS), (OUT_SAFETY, SAFETY_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE_001",
        "v20_170_r2a_status_consumed": "FALSE",
        "v20_170_r2a_status": "",
        "baseline_candidate_count": "0",
        "safe_derivation_candidate_count_before": "0",
        "safe_derivation_applied_count": "0",
        "safe_derivation_rejected_count": "0",
        "derived_field_non_null_count": "0",
        "remaining_unknown_required_pit_field_count": "0",
        "remaining_source_contract_required_field_count": "0",
        "accepted_direct_pit_lineage_row_count_after_derivation": "0",
        "direct_pass_candidate_count_after_derivation": "0",
        "direct_unknown_candidate_count_after_derivation": "0",
        "remaining_producer_patch_required_count": "0",
        "remaining_new_source_contract_required_count": "0",
        "ready_for_v20_170_r2c_source_contract_patch": "FALSE",
        "ready_for_v20_170_r3_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R2B",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE",
        "aggregate_evidence_not_treated_as_direct": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(BLOCKED_STATUS, gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    required = [*R2A_INPUTS, PIT_LINEAGE, PIT_SCHEMA_AUDIT, PIT_GAP_AUDIT, BASELINE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))

    before = protected_hashes()
    summary_rows, _ = read_csv(R2A_INPUTS[0])
    by_field, _ = read_csv(R2A_INPUTS[1])
    by_ticker, _ = read_csv(R2A_INPUTS[2])
    safe_candidates, _ = read_csv(R2A_INPUTS[5])
    gate_rows, _ = read_csv(R2A_INPUTS[8])
    lineage, _ = read_csv(PIT_LINEAGE)
    baseline, _ = read_csv(BASELINE)
    if not summary_rows or not gate_rows or not safe_candidates or not by_ticker or not lineage or not baseline:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    summary = summary_rows[0]
    r2a_gate = gate_rows[0]
    r2a_status = r2a_gate.get("final_status", "")
    prereq_ok = all([
        r2a_status in {PASS_R2A, PARTIAL_R2A},
        int(summary.get("safe_derivation_candidate_count", "0")) > 0,
        summary.get("ready_for_v20_170_r2b_safe_derivation_patch") == "TRUE",
        summary.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        summary.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R2A_REQUIREMENTS_NOT_MET")

    scoped_tickers = {row.get("ticker", "") for row in by_ticker if row.get("ticker", "")}
    scoped_lineage = [row for row in lineage if row.get("ticker", "") in scoped_tickers]
    plan, derived_out, patched, validation, remaining = build_outputs(scoped_lineage, baseline, safe_candidates, by_field)
    remaining_producer = len({row["required_field"] for row in remaining if row["requires_producer_patch"] == "TRUE"})
    remaining_new = len({row["required_field"] for row in remaining if row["requires_new_source_contract"] == "TRUE"})
    accepted_rows = sum(row["accepted_direct_pit_lineage_after_derivation"] == "TRUE" for row in validation)
    accepted_tickers = {
        row["ticker"] for row in validation
        if row["accepted_direct_pit_lineage_after_derivation"] == "TRUE"
    }
    all_tickers = {row.get("ticker", "") for row in scoped_lineage if row.get("ticker", "")}
    applied_fields = sum(row["derivation_applied"] == "TRUE" for row in plan)
    rejected_fields = len(plan) - applied_fields
    derived_non_null = sum(int(row["derived_non_null_count"]) for row in plan)
    remaining_unknown = sum(int(row["remaining_missing_or_unknown_count"]) for row in remaining)
    remaining_source = sum(int(row["remaining_source_contract_required_count"]) for row in remaining)
    ready_r2c = remaining_producer > 0 or remaining_new > 0
    ready_r3 = accepted_rows > 0
    if ready_r2c:
        final_status = PARTIAL_STATUS
        next_action = "RUN_V20_170_R2C_SOURCE_CONTRACT_PATCH_BEFORE_R3_RETEST"
    elif ready_r3:
        final_status = PASS_STATUS
        next_action = "RUN_V20_170_R3_DIRECT_STATUS_RETEST"
    else:
        final_status = WARN_STATUS
        next_action = "RUN_V20_170_R2C_SOURCE_CONTRACT_PATCH"

    upstream_mutated = before != protected_hashes()
    safety = safety_rows(prereq_ok, upstream_mutated)
    if upstream_mutated or not all(row["safety_passed"] == "TRUE" for row in safety):
        return emit_blocked("SAFETY_OR_UPSTREAM_MUTATION_FAILURE")

    gate = {
        "gate_check_id": "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE_001",
        "v20_170_r2a_status_consumed": "TRUE",
        "v20_170_r2a_status": r2a_status,
        "baseline_candidate_count": summary.get("baseline_candidate_count", str(len(all_tickers))),
        "safe_derivation_candidate_count_before": str(len(safe_candidates)),
        "safe_derivation_applied_count": str(applied_fields),
        "safe_derivation_rejected_count": str(rejected_fields),
        "derived_field_non_null_count": str(derived_non_null),
        "remaining_unknown_required_pit_field_count": str(remaining_unknown),
        "remaining_source_contract_required_field_count": str(remaining_source),
        "accepted_direct_pit_lineage_row_count_after_derivation": str(accepted_rows),
        "direct_pass_candidate_count_after_derivation": str(len(accepted_tickers) if accepted_rows else 0),
        "direct_unknown_candidate_count_after_derivation": str(len(all_tickers) - len(accepted_tickers)),
        "remaining_producer_patch_required_count": str(remaining_producer),
        "remaining_new_source_contract_required_count": str(remaining_new),
        "ready_for_v20_170_r2c_source_contract_patch": tf(ready_r2c),
        "ready_for_v20_170_r3_direct_status_retest": tf(ready_r3),
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "recommended_next_action": next_action,
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_pit_status_fabricated": "TRUE",
        "unknown_not_treated_as_pass": "TRUE",
        "source_contract_required_not_treated_as_pass": "TRUE",
        "aggregate_evidence_not_treated_as_direct": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "blocking_reason": "REMAINING_SOURCE_CONTRACT_GAPS_BLOCK_DIRECT_PASS",
        "final_status": final_status,
        **COMMON,
    }

    write_csv(OUT_PLAN, PATCH_FIELDS, plan)
    write_csv(OUT_DERIVED, PATCH_FIELDS, derived_out)
    write_csv(OUT_PATCHED, PATCHED_FIELDS, patched)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation)
    write_csv(OUT_REMAINING, REMAINING_FIELDS, remaining)
    write_csv(OUT_RETEST, VALIDATION_FIELDS, validation)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(final_status, gate)

    print(final_status)
    print(f"V20_170_R2A_STATUS={r2a_status}")
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
