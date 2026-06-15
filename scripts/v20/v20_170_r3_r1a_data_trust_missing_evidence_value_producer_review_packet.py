#!/usr/bin/env python
"""V20.170-R3-R1A DATA_TRUST missing evidence value producer review packet."""

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
    FACTORS / "V20_170_R2B_SAFE_DERIVATION_NEXT_GATE.csv",
]
R2C_INPUTS = [
    FACTORS / "V20_170_R2C_SOURCE_CONTRACT_PATCH_AUDIT.csv",
    FACTORS / "V20_170_R2C_PRODUCER_PATCH_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEW_SOURCE_CONTRACT_AUDIT.csv",
    FACTORS / "V20_170_R2C_NEXT_STAGE_GATE.csv",
]
R3_INPUTS = [
    FACTORS / "V20_170_R3_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_FIELD_RETEST_AUDIT.csv",
    FACTORS / "V20_170_R3_DATA_TRUST_REMAINING_UNKNOWN_AUDIT.csv",
    FACTORS / "V20_170_R3_NEXT_STAGE_GATE.csv",
]
R3_R1_INPUTS = [
    FACTORS / "V20_170_R3_R1_DIRECT_EVIDENCE_BINDING_DIAGNOSTICS.csv",
    FACTORS / "V20_170_R3_R1_CANDIDATE_UNKNOWN_CAUSE_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_FIELD_UNKNOWN_CAUSE_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_ARTIFACT_EVIDENCE_AVAILABILITY_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_JOIN_KEY_ASOF_MAPPING_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_SAFE_BINDING_REPAIR_AUDIT.csv",
    FACTORS / "V20_170_R3_R1_NEXT_STAGE_GATE.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, *R2B_INPUTS, *R2C_INPUTS, *R3_INPUTS, *R3_R1_INPUTS]

OUT_DETAIL = FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_VALUE_DETAIL.csv"
OUT_PRODUCER = FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_PRODUCER.csv"
OUT_FIELD = FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_FIELD.csv"
OUT_CANDIDATE = FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_CANDIDATE.csv"
OUT_ACTION = FACTORS / "V20_170_R3_R1A_REMEDIATION_ACTION_PACKET.csv"
OUT_OPTIONAL = FACTORS / "V20_170_R3_R1A_OPTIONAL_WARN_DOWNGRADE_CANDIDATES.csv"
OUT_AUDIT_ONLY = FACTORS / "V20_170_R3_R1A_AUDIT_ONLY_RECLASSIFICATION_CANDIDATES.csv"
OUT_FALLBACK = FACTORS / "V20_170_R3_R1A_FALLBACK_SOURCE_REQUIRED.csv"
OUT_GATE = FACTORS / "V20_170_R3_R1A_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_170_R3_R1A_DATA_TRUST_MISSING_EVIDENCE_VALUE_PRODUCER_REVIEW_PACKET_REPORT.md"

READY_R3_R1 = "WARN_V20_170_R3_R1_NO_SAFE_BINDING_REPAIR_MANUAL_PRODUCER_REVIEW_REQUIRED"
PASS_STATUS = "PASS_V20_170_R3_R1A_REVIEW_PACKET_READY_FOR_R3_R1B_PRODUCER_VALUE_MATERIALIZATION"
WARN_STATUS = "WARN_V20_170_R3_R1A_REVIEW_PACKET_REQUIRES_MANUAL_CONTRACT_DECISION"
BLOCKED_STATUS = "BLOCKED_V20_170_R3_R1A_MISSING_EVIDENCE_VALUE_PRODUCER_REVIEW_PACKET"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_MISSING_EVIDENCE_VALUE_PRODUCER_REVIEW_PACKET"
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

DETAIL_FIELDS = [
    "ticker", "baseline_rank", "as_of_date", "factor_family", "required_field",
    "source_contract_id", "expected_producer", "expected_artifact", "expected_artifact_field",
    "evidence_type", "pit_requirement", "missing_value_classification",
    "safe_to_materialize_by_producer_patch", "optional_warn_candidate",
    "audit_only_reclassification_candidate", "fallback_source_required",
    "manual_contract_decision_required", "fabricated_value_created",
    "ticker_row_fabricated", "recommended_remediation_action", "review_priority",
    *COMMON.keys(),
]
PRODUCER_FIELDS = [
    "expected_producer", "expected_artifact", "missing_value_count",
    "affected_ticker_count", "affected_factor_family_count", "affected_required_field_count",
    "producer_value_not_generated_count", "upstream_raw_source_missing_count",
    "field_required_but_not_materializable_count", "field_should_be_optional_warn_count",
    "field_should_be_audit_only_count", "fallback_source_required_count",
    "manual_contract_decision_required_count", "recommended_remediation_action",
    "ready_for_v20_170_r3_r1b_producer_value_materialization_patch", *COMMON.keys(),
]
FIELD_FIELDS = [
    "required_field", "source_contract_id", "evidence_type", "pit_requirement",
    "missing_value_count", "affected_ticker_count", "affected_factor_family_count",
    "missing_value_classification", "expected_producer", "expected_artifact",
    "safe_to_materialize_by_producer_patch", "optional_warn_candidate",
    "audit_only_reclassification_candidate", "fallback_source_required",
    "recommended_remediation_action", *COMMON.keys(),
]
CANDIDATE_FIELDS = [
    "ticker", "baseline_rank", "as_of_date", "missing_value_count",
    "affected_factor_family_count", "affected_required_field_count",
    "producer_value_not_generated_count", "manual_contract_decision_required_count",
    "ready_for_retest_after_materialization", "recommended_remediation_action",
    *COMMON.keys(),
]
ACTION_FIELDS = [
    "action_id", "remediation_stage", "required_field", "expected_producer",
    "expected_artifact", "missing_value_count", "action_type",
    "action_description", "blocks_direct_status_pass", "fabrication_allowed",
    "ready_for_next_stage", "repair_priority", *COMMON.keys(),
]
EMPTY_RECLASS_FIELDS = [
    "required_field", "source_contract_id", "candidate_reason",
    "affected_missing_value_count", "recommended_stage", "manual_decision_required",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r3_r1_status_consumed", "v20_170_r3_r1_status",
    "baseline_candidate_count", "missing_evidence_value_count",
    "detail_row_count", "producer_summary_count", "field_summary_count",
    "candidate_summary_count", "producer_value_not_generated_count",
    "upstream_raw_source_missing_count", "field_required_but_not_materializable_count",
    "field_should_be_optional_warn_count", "field_should_be_audit_only_count",
    "fallback_source_required_count", "manual_contract_decision_required_count",
    "safe_producer_materialization_missing_value_count",
    "ready_for_v20_170_r3_r1b_producer_value_materialization_patch",
    "ready_for_v20_170_r3_r1c_contract_requirement_reclassification",
    "ready_for_v20_170_r3_r1d_fallback_source_contract_design",
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


def evidence_type(field: str) -> str:
    if field in {"factor_input_as_of_date", "factor_input_source_timestamp"}:
        return "DIRECT_INPUT_TIMESTAMP"
    if field in {"factor_input_publication_lag_handled", "factor_input_point_in_time_safe"}:
        return "DIRECT_PIT_SOURCE_CONTRACT_VALUE"
    if field in {"non_pit_blocker_present", "leakage_flag_present"}:
        return "DIRECT_PIT_BLOCKER_FLAG"
    return "DIRECT_SOURCE_QUALITY_OR_FRESHNESS_VALUE"


def pit_requirement(field: str) -> str:
    if field in {"factor_input_point_in_time_safe", "factor_input_publication_lag_handled", "non_pit_blocker_present", "leakage_flag_present"}:
        return "REQUIRED_FOR_PIT_DIRECT_STATUS"
    return "REQUIRED_FOR_DIRECT_LINEAGE_EVIDENCE"


def build_outputs(
    binding: list[dict[str, str]],
    baseline: list[dict[str, str]],
    producer: list[dict[str, str]],
    new_contract: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    baseline_by_ticker = {row["ticker"]: row for row in baseline}
    producer_by_field = {row["required_field"]: row for row in producer}
    new_by_field = {row["required_field"]: row for row in new_contract}
    detail: list[dict[str, str]] = []
    for row in binding:
        field = row["required_field"]
        base = baseline_by_ticker.get(row["ticker"], {})
        producer_row = producer_by_field.get(field, {})
        contract_row = new_by_field.get(field, {})
        expected_producer = producer_row.get("producer_script") or contract_row.get("source_contract_owner_stage") or "UPSTREAM_FACTOR_SOURCE_CONTRACT"
        expected_artifact = producer_row.get("output_artifact") or "outputs/v20/consolidation/V20_108_R10_TICKER_FACTOR_PIT_LINEAGE_EXTENSION.csv"
        classification = "producer_value_not_generated"
        detail.append({
            "ticker": row["ticker"],
            "baseline_rank": row.get("baseline_rank", ""),
            "as_of_date": base.get("ranking_timestamp_utc") or base.get("latest_price_date", ""),
            "factor_family": row["factor_family"],
            "required_field": field,
            "source_contract_id": f"DATA_TRUST_SOURCE_CONTRACT::{field}",
            "expected_producer": expected_producer,
            "expected_artifact": expected_artifact,
            "expected_artifact_field": producer_row.get("output_field") or contract_row.get("source_contract_field") or field,
            "evidence_type": evidence_type(field),
            "pit_requirement": pit_requirement(field),
            "missing_value_classification": classification,
            "safe_to_materialize_by_producer_patch": "TRUE",
            "optional_warn_candidate": "FALSE",
            "audit_only_reclassification_candidate": "FALSE",
            "fallback_source_required": "FALSE",
            "manual_contract_decision_required": "FALSE",
            "fabricated_value_created": "FALSE",
            "ticker_row_fabricated": "FALSE",
            "recommended_remediation_action": "MATERIALIZE_DIRECT_EVIDENCE_VALUE_IN_EXPECTED_PRODUCER",
            "review_priority": "HIGH",
            **COMMON,
        })

    producer_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    field_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    candidate_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in detail:
        producer_groups[(row["expected_producer"], row["expected_artifact"])].append(row)
        field_groups[row["required_field"]].append(row)
        candidate_groups[row["ticker"]].append(row)

    producer_summary = []
    for (expected_producer, expected_artifact), rows in sorted(producer_groups.items()):
        counts = Counter(row["missing_value_classification"] for row in rows)
        producer_summary.append({
            "expected_producer": expected_producer,
            "expected_artifact": expected_artifact,
            "missing_value_count": str(len(rows)),
            "affected_ticker_count": str(len({row["ticker"] for row in rows})),
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "affected_required_field_count": str(len({row["required_field"] for row in rows})),
            "producer_value_not_generated_count": str(counts.get("producer_value_not_generated", 0)),
            "upstream_raw_source_missing_count": str(counts.get("upstream_raw_source_missing", 0)),
            "field_required_but_not_materializable_count": str(counts.get("field_required_but_not_materializable", 0)),
            "field_should_be_optional_warn_count": str(counts.get("field_should_be_optional_warn", 0)),
            "field_should_be_audit_only_count": str(counts.get("field_should_be_audit_only", 0)),
            "fallback_source_required_count": str(counts.get("fallback_source_required", 0)),
            "manual_contract_decision_required_count": str(counts.get("manual_contract_decision_required", 0)),
            "recommended_remediation_action": "MATERIALIZE_DIRECT_EVIDENCE_VALUES_AND_RERUN_R3_R2",
            "ready_for_v20_170_r3_r1b_producer_value_materialization_patch": "TRUE",
            **COMMON,
        })

    field_summary = []
    for field, rows in sorted(field_groups.items()):
        field_summary.append({
            "required_field": field,
            "source_contract_id": rows[0]["source_contract_id"],
            "evidence_type": rows[0]["evidence_type"],
            "pit_requirement": rows[0]["pit_requirement"],
            "missing_value_count": str(len(rows)),
            "affected_ticker_count": str(len({row["ticker"] for row in rows})),
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "missing_value_classification": "producer_value_not_generated",
            "expected_producer": rows[0]["expected_producer"],
            "expected_artifact": rows[0]["expected_artifact"],
            "safe_to_materialize_by_producer_patch": "TRUE",
            "optional_warn_candidate": "FALSE",
            "audit_only_reclassification_candidate": "FALSE",
            "fallback_source_required": "FALSE",
            "recommended_remediation_action": "MATERIALIZE_FIELD_VALUES_IN_EXPECTED_PRODUCER",
            **COMMON,
        })

    candidate_summary = []
    for ticker, rows in sorted(candidate_groups.items(), key=lambda item: int(item[1][0]["baseline_rank"] or "999999")):
        candidate_summary.append({
            "ticker": ticker,
            "baseline_rank": rows[0]["baseline_rank"],
            "as_of_date": rows[0]["as_of_date"],
            "missing_value_count": str(len(rows)),
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "affected_required_field_count": str(len({row["required_field"] for row in rows})),
            "producer_value_not_generated_count": str(len(rows)),
            "manual_contract_decision_required_count": "0",
            "ready_for_retest_after_materialization": "TRUE",
            "recommended_remediation_action": "WAIT_FOR_R3_R1B_PRODUCER_VALUE_MATERIALIZATION",
            **COMMON,
        })

    action_rows = []
    for idx, row in enumerate(field_summary, start=1):
        action_rows.append({
            "action_id": f"V20_170_R3_R1A_ACTION_{idx:03d}",
            "remediation_stage": "V20_170_R3_R1B_PRODUCER_VALUE_MATERIALIZATION_PATCH",
            "required_field": row["required_field"],
            "expected_producer": row["expected_producer"],
            "expected_artifact": row["expected_artifact"],
            "missing_value_count": row["missing_value_count"],
            "action_type": "PRODUCER_VALUE_MATERIALIZATION",
            "action_description": "Emit direct ticker-factor evidence values without defaults; UNKNOWN remains allowed only when evidence is genuinely unavailable.",
            "blocks_direct_status_pass": "TRUE",
            "fabrication_allowed": "FALSE",
            "ready_for_next_stage": "TRUE",
            "repair_priority": "HIGH",
            **COMMON,
        })

    return detail, producer_summary, field_summary, candidate_summary, action_rows


def empty_outputs() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    return [], [], []


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R3-R1A DATA_TRUST Missing Evidence Value Producer Review Packet",
        "",
        f"- final_status: {gate['final_status']}",
        f"- missing_evidence_value_count: {gate['missing_evidence_value_count']}",
        f"- producer_value_not_generated_count: {gate['producer_value_not_generated_count']}",
        f"- safe_producer_materialization_missing_value_count: {gate['safe_producer_materialization_missing_value_count']}",
        f"- ready_for_v20_170_r3_r1b_producer_value_materialization_patch: {gate['ready_for_v20_170_r3_r1b_producer_value_materialization_patch']}",
        f"- ready_for_v20_170_r3_r1c_contract_requirement_reclassification: {gate['ready_for_v20_170_r3_r1c_contract_requirement_reclassification']}",
        f"- ready_for_v20_170_r3_r1d_fallback_source_contract_design: {gate['ready_for_v20_170_r3_r1d_fallback_source_contract_design']}",
        f"- ready_for_v20_171_gate_only_ranking_simulation: {gate['ready_for_v20_171_gate_only_ranking_simulation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "The packet does not fabricate ticker rows or evidence values. It routes all missing direct evidence values to producer value materialization review.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_DETAIL, DETAIL_FIELDS), (OUT_PRODUCER, PRODUCER_FIELDS), (OUT_FIELD, FIELD_FIELDS),
        (OUT_CANDIDATE, CANDIDATE_FIELDS), (OUT_ACTION, ACTION_FIELDS),
        (OUT_OPTIONAL, EMPTY_RECLASS_FIELDS), (OUT_AUDIT_ONLY, EMPTY_RECLASS_FIELDS),
        (OUT_FALLBACK, EMPTY_RECLASS_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R3_R1A_NEXT_STAGE_GATE_001",
        "v20_170_r3_r1_status_consumed": "FALSE",
        "v20_170_r3_r1_status": "",
        "baseline_candidate_count": "0",
        "missing_evidence_value_count": "0",
        "detail_row_count": "0",
        "producer_summary_count": "0",
        "field_summary_count": "0",
        "candidate_summary_count": "0",
        "producer_value_not_generated_count": "0",
        "upstream_raw_source_missing_count": "0",
        "field_required_but_not_materializable_count": "0",
        "field_should_be_optional_warn_count": "0",
        "field_should_be_audit_only_count": "0",
        "fallback_source_required_count": "0",
        "manual_contract_decision_required_count": "0",
        "safe_producer_materialization_missing_value_count": "0",
        "ready_for_v20_170_r3_r1b_producer_value_materialization_patch": "FALSE",
        "ready_for_v20_170_r3_r1c_contract_requirement_reclassification": "FALSE",
        "ready_for_v20_170_r3_r1d_fallback_source_contract_design": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R3_R1A",
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
    required = [*R2B_INPUTS, *R2C_INPUTS, *R3_INPUTS, *R3_R1_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    producer, _ = read_csv(R2C_INPUTS[1])
    new_contract, _ = read_csv(R2C_INPUTS[2])
    binding, _ = read_csv(R3_R1_INPUTS[0])
    r3_r1_gate_rows, _ = read_csv(R3_R1_INPUTS[6])
    if not baseline or not binding or not r3_r1_gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r3_r1_gate = r3_r1_gate_rows[0]
    prereq_ok = all([
        r3_r1_gate.get("final_status") == READY_R3_R1,
        r3_r1_gate.get("missing_evidence_value_count") == "1920",
        r3_r1_gate.get("ready_for_v20_170_r3_r2_retest_after_binding_repair") == "FALSE",
        r3_r1_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r3_r1_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R3_R1_REQUIREMENTS_NOT_MET")

    missing_binding = [row for row in binding if row.get("unknown_cause") == "missing_evidence_value"]
    detail, producer_summary, field_summary, candidate_summary, action_rows = build_outputs(missing_binding, baseline, producer, new_contract)
    optional_rows, audit_only_rows, fallback_rows = empty_outputs()
    official_mutated = before != protected_hashes()
    if official_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")

    counts = Counter(row["missing_value_classification"] for row in detail)
    producer_value_count = counts.get("producer_value_not_generated", 0)
    optional_count = counts.get("field_should_be_optional_warn", 0)
    audit_only_count = counts.get("field_should_be_audit_only", 0)
    fallback_count = counts.get("fallback_source_required", 0)
    manual_count = counts.get("manual_contract_decision_required", 0)
    ready_r1b = producer_value_count > 0
    ready_r1c = optional_count > 0 or audit_only_count > 0 or manual_count > 0
    ready_r1d = fallback_count > 0
    gate = {
        "gate_check_id": "V20_170_R3_R1A_NEXT_STAGE_GATE_001",
        "v20_170_r3_r1_status_consumed": "TRUE",
        "v20_170_r3_r1_status": r3_r1_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "missing_evidence_value_count": str(len(detail)),
        "detail_row_count": str(len(detail)),
        "producer_summary_count": str(len(producer_summary)),
        "field_summary_count": str(len(field_summary)),
        "candidate_summary_count": str(len(candidate_summary)),
        "producer_value_not_generated_count": str(producer_value_count),
        "upstream_raw_source_missing_count": str(counts.get("upstream_raw_source_missing", 0)),
        "field_required_but_not_materializable_count": str(counts.get("field_required_but_not_materializable", 0)),
        "field_should_be_optional_warn_count": str(optional_count),
        "field_should_be_audit_only_count": str(audit_only_count),
        "fallback_source_required_count": str(fallback_count),
        "manual_contract_decision_required_count": str(manual_count),
        "safe_producer_materialization_missing_value_count": str(producer_value_count),
        "ready_for_v20_170_r3_r1b_producer_value_materialization_patch": tf(ready_r1b),
        "ready_for_v20_170_r3_r1c_contract_requirement_reclassification": tf(ready_r1c),
        "ready_for_v20_170_r3_r1d_fallback_source_contract_design": tf(ready_r1d),
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RUN_V20_170_R3_R1B_PRODUCER_VALUE_MATERIALIZATION_PATCH" if ready_r1b else "MANUAL_CONTRACT_REVIEW",
        "blocking_reason": "MISSING_DIRECT_EVIDENCE_VALUES_REQUIRE_PRODUCER_MATERIALIZATION",
        "final_status": PASS_STATUS if ready_r1b else WARN_STATUS,
        **COMMON,
    }
    write_csv(OUT_DETAIL, DETAIL_FIELDS, detail)
    write_csv(OUT_PRODUCER, PRODUCER_FIELDS, producer_summary)
    write_csv(OUT_FIELD, FIELD_FIELDS, field_summary)
    write_csv(OUT_CANDIDATE, CANDIDATE_FIELDS, candidate_summary)
    write_csv(OUT_ACTION, ACTION_FIELDS, action_rows)
    write_csv(OUT_OPTIONAL, EMPTY_RECLASS_FIELDS, optional_rows)
    write_csv(OUT_AUDIT_ONLY, EMPTY_RECLASS_FIELDS, audit_only_rows)
    write_csv(OUT_FALLBACK, EMPTY_RECLASS_FIELDS, fallback_rows)
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
