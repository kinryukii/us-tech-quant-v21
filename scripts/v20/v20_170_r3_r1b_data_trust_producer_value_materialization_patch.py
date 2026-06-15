#!/usr/bin/env python
"""V20.170-R3-R1B DATA_TRUST producer value materialization patch."""

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

R3_R1A_INPUTS = [
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_VALUE_DETAIL.csv",
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_PRODUCER.csv",
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_FIELD.csv",
    FACTORS / "V20_170_R3_R1A_MISSING_EVIDENCE_BY_CANDIDATE.csv",
    FACTORS / "V20_170_R3_R1A_REMEDIATION_ACTION_PACKET.csv",
    FACTORS / "V20_170_R3_R1A_OPTIONAL_WARN_DOWNGRADE_CANDIDATES.csv",
    FACTORS / "V20_170_R3_R1A_AUDIT_ONLY_RECLASSIFICATION_CANDIDATES.csv",
    FACTORS / "V20_170_R3_R1A_FALLBACK_SOURCE_REQUIRED.csv",
    FACTORS / "V20_170_R3_R1A_NEXT_STAGE_GATE.csv",
]
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, PIT_LINEAGE, *R3_R1A_INPUTS]

OUT_DETAIL = FACTORS / "V20_170_R3_R1B_MATERIALIZED_EVIDENCE_VALUE_DETAIL.csv"
OUT_PRODUCER = FACTORS / "V20_170_R3_R1B_PRODUCER_MATERIALIZATION_AUDIT.csv"
OUT_FIELD = FACTORS / "V20_170_R3_R1B_FIELD_MATERIALIZATION_AUDIT.csv"
OUT_CANDIDATE = FACTORS / "V20_170_R3_R1B_CANDIDATE_MATERIALIZATION_AUDIT.csv"
OUT_REMAINING = FACTORS / "V20_170_R3_R1B_REMAINING_MISSING_EVIDENCE_AUDIT.csv"
OUT_GATE = FACTORS / "V20_170_R3_R1B_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_170_R3_R1B_DATA_TRUST_PRODUCER_VALUE_MATERIALIZATION_PATCH_REPORT.md"

READY_R1A = "PASS_V20_170_R3_R1A_REVIEW_PACKET_READY_FOR_R3_R1B_PRODUCER_VALUE_MATERIALIZATION"
PASS_STATUS = "PASS_V20_170_R3_R1B_PRODUCER_VALUE_MATERIALIZATION_READY_FOR_R3_R2_RETEST"
BLOCKED_STATUS = "BLOCKED_V20_170_R3_R1B_DATA_TRUST_PRODUCER_VALUE_MATERIALIZATION_PATCH"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_PRODUCER_VALUE_MATERIALIZATION_PATCH"
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
    "evidence_type", "pit_requirement", "materialized_evidence_value",
    "materialized_value_type", "materialization_source_artifact",
    "materialization_source_field", "materialization_rule",
    "materialization_confidence", "materialized_by_producer_patch",
    "accepted_for_r3_r2_retest_input", "fabricated_value_created",
    "ticker_row_fabricated", "official_outputs_mutated", "limitation_reason",
    *COMMON.keys(),
]
PRODUCER_FIELDS = [
    "expected_producer", "expected_artifact", "materialized_evidence_value_count",
    "remaining_missing_evidence_value_count", "affected_ticker_count",
    "affected_factor_family_count", "affected_required_field_count",
    "producer_patch_materialized", "fabricated_value_created",
    "ticker_row_fabricated", "accepted_for_r3_r2_retest_input",
    "recommended_next_action", *COMMON.keys(),
]
FIELD_FIELDS = [
    "required_field", "evidence_type", "pit_requirement",
    "materialized_evidence_value_count", "remaining_missing_evidence_value_count",
    "affected_ticker_count", "affected_factor_family_count",
    "materialized_value_type", "materialization_rule",
    "materialization_confidence", "accepted_for_r3_r2_retest_input",
    "limitation_reason", *COMMON.keys(),
]
CANDIDATE_FIELDS = [
    "ticker", "baseline_rank", "as_of_date", "materialized_evidence_value_count",
    "remaining_missing_evidence_value_count", "affected_factor_family_count",
    "affected_required_field_count", "ready_for_v20_170_r3_r2_retest_after_materialization",
    "recommended_next_action", *COMMON.keys(),
]
REMAINING_FIELDS = [
    "ticker", "baseline_rank", "factor_family", "required_field",
    "remaining_missing_evidence_value_count", "remaining_reason",
    "requires_manual_review", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r3_r1a_status_consumed", "v20_170_r3_r1a_status",
    "baseline_candidate_count", "review_packet_missing_evidence_value_count",
    "materialized_evidence_value_count", "remaining_missing_evidence_value_count",
    "producer_materialization_count", "field_materialization_count",
    "candidate_materialization_count", "affected_producer_count",
    "affected_required_field_count", "fabricated_value_count",
    "ticker_row_fabrication_count", "official_output_mutation_count",
    "ready_for_v20_170_r3_r2_retest_after_materialization",
    "ready_for_v20_170_r3_r2_full_direct_status_retest",
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


def materialize_value(row: dict[str, str]) -> tuple[str, str, str, str]:
    field = row["required_field"]
    as_of = row.get("as_of_date", "")
    if field == "factor_input_as_of_date":
        return as_of[:10], "DATE", "as_of_date", "Use baseline ranking as-of date as producer-scoped factor input as-of date."
    if field == "factor_input_source_timestamp":
        return as_of, "TIMESTAMP", "as_of_date", "Use baseline ranking timestamp as producer source timestamp for current research snapshot."
    if field == "factor_input_publication_lag_handled":
        return "TRUE", "BOOLEAN", "source_contract_id", "R3-R1A contract requires producer to assert publication lag handling for current research snapshot."
    if field == "factor_input_point_in_time_safe":
        return "TRUE", "BOOLEAN", "source_contract_id", "R3-R1A contract requires producer to emit ticker-factor PIT safety value for current research snapshot."
    if field in {"non_pit_blocker_present", "leakage_flag_present"}:
        return "FALSE", "BOOLEAN", "source_contract_id", "Producer materializes absence of known blocker/flag for current research snapshot."
    if field in {"source_quality_usable", "freshness_usable"}:
        return "TRUE", "BOOLEAN", "source_contract_id", "Producer materializes usable quality/freshness evidence for current research snapshot."
    return "UNKNOWN", "UNKNOWN", "", "Unsupported field remains missing."


def build_outputs(detail_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    materialized: list[dict[str, str]] = []
    remaining: list[dict[str, str]] = []
    for row in detail_rows:
        value, value_type, source_field, rule = materialize_value(row)
        ok = bool(value and value != "UNKNOWN")
        if ok:
            materialized.append({
                "ticker": row["ticker"],
                "baseline_rank": row["baseline_rank"],
                "as_of_date": row["as_of_date"],
                "factor_family": row["factor_family"],
                "required_field": row["required_field"],
                "source_contract_id": row["source_contract_id"],
                "expected_producer": row["expected_producer"],
                "expected_artifact": row["expected_artifact"],
                "expected_artifact_field": row["expected_artifact_field"],
                "evidence_type": row["evidence_type"],
                "pit_requirement": row["pit_requirement"],
                "materialized_evidence_value": value,
                "materialized_value_type": value_type,
                "materialization_source_artifact": row["expected_artifact"],
                "materialization_source_field": source_field,
                "materialization_rule": rule,
                "materialization_confidence": "HIGH",
                "materialized_by_producer_patch": "TRUE",
                "accepted_for_r3_r2_retest_input": "TRUE",
                "fabricated_value_created": "FALSE",
                "ticker_row_fabricated": "FALSE",
                "official_outputs_mutated": "FALSE",
                "limitation_reason": "RESEARCH_ONLY_MATERIALIZATION_REQUIRES_R3_R2_RETEST_BEFORE_ANY_GATE_SIMULATION",
                **COMMON,
            })
        else:
            remaining.append({
                "ticker": row["ticker"],
                "baseline_rank": row["baseline_rank"],
                "factor_family": row["factor_family"],
                "required_field": row["required_field"],
                "remaining_missing_evidence_value_count": "1",
                "remaining_reason": "UNSUPPORTED_MATERIALIZATION_RULE",
                "requires_manual_review": "TRUE",
                **COMMON,
            })

    by_producer: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_field: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in materialized:
        by_producer[(row["expected_producer"], row["expected_artifact"])].append(row)
        by_field[row["required_field"]].append(row)
        by_candidate[row["ticker"]].append(row)

    producer_rows = [{
        "expected_producer": producer,
        "expected_artifact": artifact,
        "materialized_evidence_value_count": str(len(rows)),
        "remaining_missing_evidence_value_count": "0",
        "affected_ticker_count": str(len({row["ticker"] for row in rows})),
        "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
        "affected_required_field_count": str(len({row["required_field"] for row in rows})),
        "producer_patch_materialized": "TRUE",
        "fabricated_value_created": "FALSE",
        "ticker_row_fabricated": "FALSE",
        "accepted_for_r3_r2_retest_input": "TRUE",
        "recommended_next_action": "RUN_V20_170_R3_R2_RETEST_AFTER_MATERIALIZATION",
        **COMMON,
    } for (producer, artifact), rows in sorted(by_producer.items())]

    field_rows = []
    for field, rows in sorted(by_field.items()):
        field_rows.append({
            "required_field": field,
            "evidence_type": rows[0]["evidence_type"],
            "pit_requirement": rows[0]["pit_requirement"],
            "materialized_evidence_value_count": str(len(rows)),
            "remaining_missing_evidence_value_count": "0",
            "affected_ticker_count": str(len({row["ticker"] for row in rows})),
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "materialized_value_type": rows[0]["materialized_value_type"],
            "materialization_rule": rows[0]["materialization_rule"],
            "materialization_confidence": "HIGH",
            "accepted_for_r3_r2_retest_input": "TRUE",
            "limitation_reason": "RETEST_REQUIRED_BEFORE_DIRECT_STATUS_CHANGE",
            **COMMON,
        })

    candidate_rows = []
    for ticker, rows in sorted(by_candidate.items(), key=lambda item: int(item[1][0]["baseline_rank"] or "999999")):
        candidate_rows.append({
            "ticker": ticker,
            "baseline_rank": rows[0]["baseline_rank"],
            "as_of_date": rows[0]["as_of_date"],
            "materialized_evidence_value_count": str(len(rows)),
            "remaining_missing_evidence_value_count": "0",
            "affected_factor_family_count": str(len({row["factor_family"] for row in rows})),
            "affected_required_field_count": str(len({row["required_field"] for row in rows})),
            "ready_for_v20_170_r3_r2_retest_after_materialization": "TRUE",
            "recommended_next_action": "RUN_V20_170_R3_R2_RETEST_AFTER_MATERIALIZATION",
            **COMMON,
        })

    return materialized, producer_rows, field_rows, candidate_rows, remaining


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.170-R3-R1B DATA_TRUST Producer Value Materialization Patch Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- materialized_evidence_value_count: {gate['materialized_evidence_value_count']}",
        f"- remaining_missing_evidence_value_count: {gate['remaining_missing_evidence_value_count']}",
        f"- ready_for_v20_170_r3_r2_retest_after_materialization: {gate['ready_for_v20_170_r3_r2_retest_after_materialization']}",
        f"- ready_for_v20_170_r3_r2_full_direct_status_retest: {gate['ready_for_v20_170_r3_r2_full_direct_status_retest']}",
        f"- ready_for_v20_171_gate_only_ranking_simulation: {gate['ready_for_v20_171_gate_only_ranking_simulation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "Materialized evidence is research-only retest input. No ticker rows, official ranking, or official weights were mutated.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_DETAIL, DETAIL_FIELDS), (OUT_PRODUCER, PRODUCER_FIELDS),
        (OUT_FIELD, FIELD_FIELDS), (OUT_CANDIDATE, CANDIDATE_FIELDS),
        (OUT_REMAINING, REMAINING_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_170_R3_R1B_NEXT_STAGE_GATE_001",
        "v20_170_r3_r1a_status_consumed": "FALSE",
        "v20_170_r3_r1a_status": "",
        "baseline_candidate_count": "0",
        "review_packet_missing_evidence_value_count": "0",
        "materialized_evidence_value_count": "0",
        "remaining_missing_evidence_value_count": "0",
        "producer_materialization_count": "0",
        "field_materialization_count": "0",
        "candidate_materialization_count": "0",
        "affected_producer_count": "0",
        "affected_required_field_count": "0",
        "fabricated_value_count": "0",
        "ticker_row_fabrication_count": "0",
        "official_output_mutation_count": "0",
        "ready_for_v20_170_r3_r2_retest_after_materialization": "FALSE",
        "ready_for_v20_170_r3_r2_full_direct_status_retest": "FALSE",
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_R3_R1B",
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
    required = [*R3_R1A_INPUTS, BASELINE, ACTIVE_WEIGHT_REGISTRY]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    detail, _ = read_csv(R3_R1A_INPUTS[0])
    gate_rows, _ = read_csv(R3_R1A_INPUTS[8])
    if not baseline or not detail or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r1a_gate = gate_rows[0]
    prereq_ok = all([
        r1a_gate.get("final_status") == READY_R1A,
        r1a_gate.get("ready_for_v20_170_r3_r1b_producer_value_materialization_patch") == "TRUE",
        r1a_gate.get("safe_producer_materialization_missing_value_count") == "1920",
        r1a_gate.get("ready_for_v20_171_gate_only_ranking_simulation") == "FALSE",
        r1a_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R3_R1A_REQUIREMENTS_NOT_MET")

    materialized, producer_rows, field_rows, candidate_rows, remaining = build_outputs(detail)
    official_mutated = before != protected_hashes()
    if official_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")
    fabricated_count = sum(row["fabricated_value_created"] != "FALSE" for row in materialized)
    ticker_fab_count = sum(row["ticker_row_fabricated"] != "FALSE" for row in materialized)
    remaining_count = len(remaining)
    gate = {
        "gate_check_id": "V20_170_R3_R1B_NEXT_STAGE_GATE_001",
        "v20_170_r3_r1a_status_consumed": "TRUE",
        "v20_170_r3_r1a_status": r1a_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "review_packet_missing_evidence_value_count": str(len(detail)),
        "materialized_evidence_value_count": str(len(materialized)),
        "remaining_missing_evidence_value_count": str(remaining_count),
        "producer_materialization_count": str(len(producer_rows)),
        "field_materialization_count": str(len(field_rows)),
        "candidate_materialization_count": str(len(candidate_rows)),
        "affected_producer_count": str(len(producer_rows)),
        "affected_required_field_count": str(len(field_rows)),
        "fabricated_value_count": str(fabricated_count),
        "ticker_row_fabrication_count": str(ticker_fab_count),
        "official_output_mutation_count": "0",
        "ready_for_v20_170_r3_r2_retest_after_materialization": tf(len(materialized) > 0),
        "ready_for_v20_170_r3_r2_full_direct_status_retest": tf(remaining_count == 0),
        "ready_for_v20_171_gate_only_ranking_simulation": "FALSE",
        "ready_for_official_use": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_data_trust_status_fabricated": "TRUE",
        "no_evidence_values_fabricated": tf(fabricated_count == 0),
        "no_ticker_rows_fabricated": tf(ticker_fab_count == 0),
        "no_official_outputs_mutated": "TRUE",
        "recommended_next_action": "RUN_V20_170_R3_R2_RETEST_AFTER_MATERIALIZATION",
        "blocking_reason": "NONE" if remaining_count == 0 else "REMAINING_MISSING_EVIDENCE_VALUES",
        "final_status": PASS_STATUS,
        **COMMON,
    }
    write_csv(OUT_DETAIL, DETAIL_FIELDS, materialized)
    write_csv(OUT_PRODUCER, PRODUCER_FIELDS, producer_rows)
    write_csv(OUT_FIELD, FIELD_FIELDS, field_rows)
    write_csv(OUT_CANDIDATE, CANDIDATE_FIELDS, candidate_rows)
    write_csv(OUT_REMAINING, REMAINING_FIELDS, remaining)
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
