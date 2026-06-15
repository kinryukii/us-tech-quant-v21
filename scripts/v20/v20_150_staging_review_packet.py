#!/usr/bin/env python
"""V20.150 staging review packet.

Creates a staging-review packet after V20.149 approved staging review only.
This stage writes only staging/read-center artifacts and keeps all formal
activation, promotion, official, real-book, trade, broker, overwrite, weight
mutation, and performance-claim boundaries closed.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
STAGING = ROOT / "outputs" / "v20" / "staging"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION.csv"
IN_INPUT = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT.csv"
IN_RECORD = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD.csv"
IN_VALIDATION = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT.csv"
IN_CONSEQUENCE = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_149_NEXT_STAGE_GATE.csv"

OUT_PACKET = STAGING / "V20_150_STAGING_REVIEW_PACKET.csv"
OUT_GATE = STAGING / "V20_150_STAGING_REVIEW_GATE.csv"
OUT_BOUNDARY = STAGING / "V20_150_PROMOTION_BOUNDARY_AUDIT.csv"
OUT_SAFETY = STAGING / "V20_150_SAFETY_CONSTRAINT_AUDIT.csv"
REPORT = READ_CENTER / "V20_150_STAGING_REVIEW_PACKET_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V149_REQUIRED_STATUS = "PASS_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_150"
PASS_STATUS = "PASS_V20_150_STAGING_REVIEW_PACKET_READY_FOR_V20_151"
BLOCKED_STATUS = "BLOCKED_V20_150_STAGING_REVIEW_PACKET"

REQUIRED_INPUTS = [IN_DECISION, IN_INPUT, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 150))
)
PROHIBITED_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "performance_claim_created",
    "performance_claims_created", "performance_effectiveness_claim_created", "official_promotion_allowed", "is_official_weight",
    "promotion_ready", "formal_activation_allowed",
]
COMMON = {
    "accepted_weight_created": "FALSE", "accepted_weights_created": "FALSE", "real_book_weight_created": "FALSE",
    "real_book_action_created": "FALSE", "official_weight_created": "FALSE", "official_weights_created": "FALSE",
    "official_ranking_created": "FALSE", "official_rankings_created": "FALSE", "official_recommendation_created": "FALSE",
    "official_recommendations_created": "FALSE", "trade_action_created": "FALSE", "trade_actions_created": "FALSE",
    "broker_action_created": "FALSE", "broker_actions_created": "FALSE", "authoritative_overwrite_created": "FALSE",
    "authoritative_overwrites_created": "FALSE", "authoritative_ranking_overwritten": "FALSE", "weight_mutated": "FALSE",
    "weight_mutations_created": "FALSE", "performance_claim_created": "FALSE", "performance_claims_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE", "official_promotion_allowed": "FALSE", "is_official_weight": "FALSE",
    "formal_activation_allowed": "FALSE", "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE",
    "staging_review_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

PACKET_FIELDS = ["staging_review_packet_id", "selected_repair_scenario_id", "source_operator_decision_record_id", "source_operator_decision_status", "selected_operator_action", "staging_review_allowed", "formal_activation_allowed", "promotion_ready", "evidence_acceptance", "operator_acceptance", "staging_review_scope", "staging_review_question", "allowed_staging_review_action", "ticker_rows_created", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "selected_repair_scenario_id", "v20_149_gate_consumed", "v20_150_staging_review_packet_allowed_by_v149", "source_operator_decision_status", "staging_review_packet_created", "staging_review_allowed", "formal_activation_allowed", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "promotion_boundary_audit_passed", "safety_constraint_audit_passed", "v20_151_staging_REVIEW_ALLOWED", "v20_151_staging_review_allowed", "next_recommended_action", "blocking_reason", "staging_review_packet_status", *COMMON.keys()]
BOUNDARY_FIELDS = ["promotion_boundary_audit_id", "selected_repair_scenario_id", "boundary_name", "boundary_required_value", "boundary_observed_value", "boundary_passed", "boundary_reason", *COMMON.keys()]
SAFETY_FIELDS = ["safety_constraint_audit_id", "selected_repair_scenario_id", "prohibited_field", "observed_true_count", "safety_constraint_passed", "safety_status", "safety_reason", *COMMON.keys()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def truthy(value: str | None) -> bool:
    return (value or "").strip().upper() == "TRUE"


def clean(value: str | None) -> str:
    return (value or "").strip()


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upstream_hashes() -> dict[str, str]:
    return {display_path(path): digest(path) for path in UPSTREAM_HASH_INPUTS if path.exists()}


def prohibited_counts(groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def build_boundary(selected_id: str, checks: list[tuple[str, str, str, bool, str]]) -> list[dict[str, str]]:
    return [{
        "promotion_boundary_audit_id": f"V20_150_PROMOTION_BOUNDARY_AUDIT_{i:03d}",
        "selected_repair_scenario_id": selected_id,
        "boundary_name": name,
        "boundary_required_value": required,
        "boundary_observed_value": observed,
        "boundary_passed": tf(passed),
        "boundary_reason": reason,
        **COMMON,
    } for i, (name, required, observed, passed, reason) in enumerate(checks, start=1)]


def build_safety(selected_id: str, counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_constraint_audit_id": f"V20_150_SAFETY_CONSTRAINT_AUDIT_{i:03d}",
        "selected_repair_scenario_id": selected_id,
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_constraint_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.150 is staging-review-only and does not create official, operational, mutation, performance, activation, or promotion-ready artifacts.",
        **COMMON,
    } for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_report(status: str, selected_id: str, packet_count: int, boundary_passed: bool, safety_passed: bool, next_allowed: bool) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.150 Staging Review Packet Report", "",
        f"- wrapper_status: {status}",
        f"- selected_repair_scenario_id: {selected_id}",
        f"- staging_review_packet_row_count: {packet_count}",
        f"- promotion_boundary_audit_passed: {tf(boundary_passed)}",
        f"- safety_constraint_audit_passed: {tf(safety_passed)}",
        "- staging_review_allowed: TRUE" if next_allowed else "- staging_review_allowed: FALSE",
        "- formal_activation_allowed: FALSE",
        "- promotion_ready: FALSE",
        "",
        "This packet is staging-review-only. It does not create official recommendations, rankings, weights, real-book actions, trades, broker execution, weight mutations, performance claims, or promotion readiness.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "TRADE_ACTION_CREATED", "BROKER_EXECUTION_CREATED", "WEIGHT_MUTATED", "PERFORMANCE_CLAIM_CREATED", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    selected_id = ""
    boundary = build_boundary(selected_id, [("required_inputs_available", "TRUE", "FALSE", False, blocking)])
    safety = build_safety(selected_id, {field: 0 for field in PROHIBITED_FIELDS}, False)
    gate = {"gate_check_id": "V20_150_STAGING_REVIEW_GATE_001", "selected_repair_scenario_id": selected_id, "v20_149_gate_consumed": "FALSE", "v20_150_staging_review_packet_allowed_by_v149": "FALSE", "source_operator_decision_status": "", "staging_review_packet_created": "FALSE", "staging_review_allowed": "FALSE", "formal_activation_allowed": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "promotion_boundary_audit_passed": "FALSE", "safety_constraint_audit_passed": "FALSE", "v20_151_staging_REVIEW_ALLOWED": "FALSE", "v20_151_staging_review_allowed": "FALSE", "next_recommended_action": "V20.150_STAGING_REVIEW_PACKET_REPAIR", "blocking_reason": blocking, "staging_review_packet_status": BLOCKED_STATUS, **COMMON}
    write_csv(OUT_PACKET, PACKET_FIELDS, [])
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_BOUNDARY, BOUNDARY_FIELDS, boundary)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(BLOCKED_STATUS, selected_id, 0, False, False, False)
    print(BLOCKED_STATUS)
    print("V20_150_STAGING_REVIEW_PACKET_ALLOWED_BY_V149=FALSE")
    print("V20_151_STAGING_REVIEW_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)
    decision_rows = read_csv(IN_DECISION)
    input_rows = read_csv(IN_INPUT)
    record_rows = read_csv(IN_RECORD)
    validation_rows = read_csv(IN_VALIDATION)
    consequence_rows = read_csv(IN_CONSEQUENCE)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, input_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision = first(decision_rows)
    record = first(record_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision.get("selected_repair_scenario_id"))
    v149_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_149_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_150_staging_review_packet_allowed"))
    status_ok = clean(record.get("operator_decision_status")) == "APPROVED_FOR_STAGING_REVIEW_ONLY" and clean(decision.get("promotion_readiness_operator_decision_capture_status")) == V149_REQUIRED_STATUS
    staging_allowed = truthy(record.get("staging_review_allowed")) and truthy(gate_in.get("staging_review_allowed"))
    formal_activation_allowed = truthy(record.get("formal_activation_allowed")) or truthy(gate_in.get("formal_activation_allowed"))
    promotion_ready = truthy(record.get("promotion_ready")) or truthy(gate_in.get("promotion_ready")) or truthy(decision.get("promotion_ready"))
    scenario_ok = selected_id == EXPECTED_SCENARIO_ID
    evidence_acceptance = truthy(record.get("evidence_acceptance"))
    operator_acceptance = truthy(record.get("operator_acceptance"))
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in record_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes

    packet = [{
        "staging_review_packet_id": "V20_150_STAGING_REVIEW_PACKET_001",
        "selected_repair_scenario_id": selected_id,
        "source_operator_decision_record_id": clean(record.get("promotion_readiness_operator_decision_record_id")),
        "source_operator_decision_status": clean(record.get("operator_decision_status")),
        "selected_operator_action": clean(record.get("selected_operator_action")),
        "staging_review_allowed": tf(staging_allowed),
        "formal_activation_allowed": "FALSE",
        "promotion_ready": "FALSE",
        "evidence_acceptance": tf(evidence_acceptance),
        "operator_acceptance": tf(operator_acceptance),
        "staging_review_scope": "STAGING_REVIEW_PACKET_ONLY_NOT_FORMAL_ACTIVATION_NOT_OFFICIAL_PROMOTION",
        "staging_review_question": "Review whether the staging packet should proceed to the next staging-review control.",
        "allowed_staging_review_action": "STAGING_REVIEW_ONLY_NO_FORMAL_ACTIVATION",
        "ticker_rows_created": "0",
        **COMMON,
    }]
    counts = prohibited_counts([decision_rows, input_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    safety_passed = upstream_safety and prohibited_count == 0
    boundary_checks = [
        ("operator_decision_status", "APPROVED_FOR_STAGING_REVIEW_ONLY", clean(record.get("operator_decision_status")), status_ok, "V20.149 must approve staging review only."),
        ("staging_review_allowed", "TRUE", tf(staging_allowed), staging_allowed, "Staging review must be explicitly allowed by V20.149."),
        ("formal_activation_allowed", "FALSE", tf(formal_activation_allowed), not formal_activation_allowed, "Formal activation remains disallowed."),
        ("promotion_ready", "FALSE", tf(promotion_ready), not promotion_ready, "Promotion readiness remains false."),
        ("v20_150_staging_review_packet_allowed", "TRUE", tf(allowed), allowed, "V20.149 gate must allow V20.150."),
        ("no_ticker_rows_fabricated", "0", str(ticker_count), ticker_count == 0, "No ticker rows are created in staging review."),
        ("no_upstream_v20_109_through_v20_149_outputs_mutated", "FALSE", tf(upstream_mutation), not upstream_mutation, "Prior outputs are read-only."),
        ("all_prohibited_action_flags_false", "0", str(prohibited_count), prohibited_count == 0, "No prohibited action flags are true."),
    ]
    boundary = build_boundary(selected_id, boundary_checks)
    boundary_passed = all(row["boundary_passed"] == "TRUE" for row in boundary)
    base_ok = all([v149_gate_consumed, allowed, status_ok, scenario_ok, staging_allowed, not formal_activation_allowed, not promotion_ready, evidence_acceptance, operator_acceptance, ticker_count == 0, not upstream_mutation, boundary_passed, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "staging_review_packet_requirements_not_met"
    safety = build_safety(selected_id, counts, safety_passed)
    gate = {"gate_check_id": "V20_150_STAGING_REVIEW_GATE_001", "selected_repair_scenario_id": selected_id, "v20_149_gate_consumed": tf(v149_gate_consumed), "v20_150_staging_review_packet_allowed_by_v149": tf(allowed), "source_operator_decision_status": clean(record.get("operator_decision_status")), "staging_review_packet_created": "TRUE", "staging_review_allowed": tf(staging_allowed), "formal_activation_allowed": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "promotion_boundary_audit_passed": tf(boundary_passed), "safety_constraint_audit_passed": tf(safety_passed), "v20_151_staging_REVIEW_ALLOWED": tf(next_allowed), "v20_151_staging_review_allowed": tf(next_allowed), "next_recommended_action": "V20.151_STAGING_REVIEW" if next_allowed else "V20.150_STAGING_REVIEW_PACKET_REPAIR", "blocking_reason": blocking, "staging_review_packet_status": final_status, **COMMON}
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_csv(OUT_BOUNDARY, BOUNDARY_FIELDS, boundary)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_report(final_status, selected_id, len(packet), boundary_passed, safety_passed, next_allowed)
    print(final_status)
    print(f"V20_149_GATE_CONSUMED={tf(v149_gate_consumed)}")
    print(f"V20_150_STAGING_REVIEW_PACKET_ALLOWED_BY_V149={tf(allowed)}")
    print(f"OPERATOR_DECISION_STATUS={clean(record.get('operator_decision_status'))}")
    print(f"STAGING_REVIEW_ALLOWED={tf(staging_allowed)}")
    print("FORMAL_ACTIVATION_ALLOWED=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"EVIDENCE_ACCEPTANCE={tf(evidence_acceptance)}")
    print(f"OPERATOR_ACCEPTANCE={tf(operator_acceptance)}")
    print(f"STAGING_REVIEW_PACKET_ROW_COUNT={len(packet)}")
    print(f"PROMOTION_BOUNDARY_AUDIT_PASSED={tf(boundary_passed)}")
    print(f"SAFETY_CONSTRAINT_AUDIT_PASSED={tf(safety_passed)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_151_STAGING_REVIEW_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
