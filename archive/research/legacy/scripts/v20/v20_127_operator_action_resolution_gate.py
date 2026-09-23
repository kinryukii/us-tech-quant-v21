#!/usr/bin/env python
"""V20.127 operator action resolution gate.

Evaluates whether V20.126 captured operator actions resolve remaining
blockers. This stage is resolution-gate-only, audit-only, non-mutating, and
never marks promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_DECISION.csv"
IN_RECORD = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_RECORD.csv"
IN_VALIDATION = CONSOLIDATION / "V20_126_OPERATOR_ACTION_VALIDATION_AUDIT.csv"
IN_CONSEQUENCE = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CONSEQUENCE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_126_NEXT_STAGE_GATE.csv"
IN_PACKET = CONSOLIDATION / "V20_125_OPERATOR_ACTION_PACKET.csv"
IN_REMAINING = CONSOLIDATION / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv"

OUT_DECISION = CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv"
OUT_AUDIT = CONSOLIDATION / "V20_127_ACTION_RESOLUTION_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_127_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V126_ALLOWED_STATUSES = {
    "PARTIAL_PASS_V20_126_OPERATOR_ACTIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_127",
    "PASS_V20_126_OPERATOR_ACTION_CAPTURE_READY_FOR_V20_127",
}
PARTIAL_STATUS = "PARTIAL_PASS_V20_127_MORE_EVIDENCE_REQUIRED_READY_FOR_V20_128"
PASS_STATUS = "PASS_V20_127_OPERATOR_ACTION_RESOLUTION_GATE_READY_FOR_V20_128"
BLOCKED_STATUS = "BLOCKED_V20_127_OPERATOR_ACTION_RESOLUTION_GATE"

REQUIRED_INPUTS = [IN_DECISION, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_GATE, IN_PACKET, IN_REMAINING]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126"]],
    IN_DECISION, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_PACKET, IN_REMAINING,
]
PROHIBITED_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "performance_claim_created",
    "performance_claims_created", "performance_effectiveness_claim_created", "official_promotion_allowed", "is_official_weight",
    "promotion_ready",
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "operator_action_resolution_gate_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_126_gate_consumed", "v20_127_operator_action_resolution_gate_allowed_by_v126", "v20_126_final_status", "v20_126_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_126", "action_capture_record_count", "action_resolution_audit_row_count", "every_action_capture_record_has_resolution_audit", "need_more_evidence_action_count", "not_resolved_more_evidence_required_count", "invalid_acceptance_missing_evidence_count", "remaining_blocker_resolution_status_count", "required_next_evidence_audit_count", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_128_additional_evidence_collection_plan_allowed", "operator_action_resolution_gate_status", "blocking_reason", *COMMON.keys()]
AUDIT_FIELDS = ["action_resolution_audit_id", "selected_repair_scenario_id", "source_action_capture_record_id", "source_action_packet_id", "source_operator_decision_record_id", "blocker_category", "operator_selected_action", "action_source", "explicit_valid_human_acceptance_evidence", "operator_acceptance_valid", "resolution_status", "decision_status", "blocker_status", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
REMAINING_FIELDS = ["remaining_blocker_resolution_status_id", "selected_repair_scenario_id", "source_action_capture_record_id", "source_operator_decision_record_id", "blocker_category", "resolution_status", "decision_status", "blocker_status", "remaining_blocker_requires_review", "promotion_ready", *COMMON.keys()]
EVIDENCE_FIELDS = ["required_next_evidence_audit_id", "selected_repair_scenario_id", "source_action_capture_record_id", "source_action_packet_id", "source_operator_decision_record_id", "blocker_category", "operator_selected_action", "required_next_evidence", "evidence_required_for_v20_128", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_126_gate_consumed", "v20_127_operator_action_resolution_gate_allowed_by_v126", "selected_repair_scenario_id", "operator_action_resolution_gate_created", "every_action_capture_record_has_resolution_audit", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_128_additional_evidence_collection_plan_allowed", "next_recommended_action", "blocking_reason", "operator_action_resolution_gate_status", *COMMON.keys()]


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


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{"safety_check_id": f"V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.127 evaluates operator action resolution only and keeps promotion readiness false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, audit, remaining, evidence, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_AUDIT, AUDIT_FIELDS, audit)
    write_csv(OUT_REMAINING, REMAINING_FIELDS, remaining)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.127 Operator Action Resolution Gate Report", "",
        f"- wrapper_status: {decision.get('operator_action_resolution_gate_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- action_resolution_audit_row_count: {decision.get('action_resolution_audit_row_count')}",
        f"- need_more_evidence_action_count: {decision.get('need_more_evidence_action_count')}",
        f"- not_resolved_more_evidence_required_count: {decision.get('not_resolved_more_evidence_required_count')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_128_additional_evidence_collection_plan_allowed: {decision.get('v20_128_additional_evidence_collection_plan_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION_001", "v20_126_gate_consumed": "FALSE", "v20_127_operator_action_resolution_gate_allowed_by_v126": "FALSE", "v20_126_final_status": "", "v20_126_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_126": "FALSE", "action_capture_record_count": "0", "action_resolution_audit_row_count": "0", "every_action_capture_record_has_resolution_audit": "FALSE", "need_more_evidence_action_count": "0", "not_resolved_more_evidence_required_count": "0", "invalid_acceptance_missing_evidence_count": "0", "remaining_blocker_resolution_status_count": "0", "required_next_evidence_audit_count": "0", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_128_additional_evidence_collection_plan_allowed": "FALSE", "operator_action_resolution_gate_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_127_NEXT_STAGE_GATE_001", "v20_126_gate_consumed": "FALSE", "v20_127_operator_action_resolution_gate_allowed_by_v126": "FALSE", "selected_repair_scenario_id": "", "operator_action_resolution_gate_created": "TRUE", "every_action_capture_record_has_resolution_audit": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_128_additional_evidence_collection_plan_allowed": "FALSE", "next_recommended_action": "V20.127_OPERATOR_ACTION_RESOLUTION_GATE_REPAIR", "blocking_reason": blocking, "operator_action_resolution_gate_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_126_GATE_CONSUMED=FALSE")
    print("V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    record_rows = read_csv(IN_RECORD)
    validation_rows = read_csv(IN_VALIDATION)
    consequence_rows = read_csv(IN_CONSEQUENCE)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    packet_rows = read_csv(IN_PACKET)
    remaining_input_rows = read_csv(IN_REMAINING)
    if not all([decision_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_rows, remaining_input_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v126_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_126_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_127_operator_action_resolution_gate_allowed"))
    v126_status = clean(gate_in.get("operator_action_capture_status")) or clean(decision_in.get("operator_action_capture_status"))
    v126_status_allowed = v126_status in V126_ALLOWED_STATUSES
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    validation_by_packet = {clean(row.get("source_action_packet_id")): row for row in validation_rows}

    audit_rows = []
    remaining_rows = []
    evidence_rows = []
    operator_acceptance_true_count = 0
    for i, record in enumerate(record_rows, start=1):
        action = clean(record.get("operator_selected_action")) or clean(record.get("captured_operator_action"))
        packet_id = clean(record.get("source_action_packet_id"))
        validation = validation_by_packet.get(packet_id, {})
        explicit_acceptance = truthy(validation.get("explicit_valid_human_acceptance_evidence"))
        acceptance_valid = truthy(validation.get("operator_acceptance_valid"))
        if action == "NEED_MORE_EVIDENCE":
            resolution_status = "NOT_RESOLVED_MORE_EVIDENCE_REQUIRED"
            decision_status = "PENDING_OPERATOR_DECISION"
            blocker_status = "UNRESOLVED_OR_PENDING_REVIEW"
            operator_acceptance = "FALSE"
        elif action == "REJECT_AND_KEEP_BLOCKED":
            resolution_status = "REJECTED_KEEP_BLOCKED"
            decision_status = "OPERATOR_REJECTED"
            blocker_status = "BLOCKED"
            operator_acceptance = "FALSE"
        elif action == "ACCEPT_WITH_LIMITATION" and explicit_acceptance and acceptance_valid:
            resolution_status = "RESOLVED_ACCEPTED_WITH_LIMITATION"
            decision_status = "OPERATOR_ACCEPTED_WITH_LIMITATION"
            blocker_status = "RESOLVED_WITH_LIMITATION"
            operator_acceptance = "TRUE"
            operator_acceptance_true_count += 1
        elif action == "ACCEPT_WITH_LIMITATION":
            resolution_status = "INVALID_ACCEPTANCE_MISSING_EVIDENCE"
            decision_status = "PENDING_OPERATOR_DECISION"
            blocker_status = "UNRESOLVED_OR_PENDING_REVIEW"
            operator_acceptance = "FALSE"
        else:
            resolution_status = "INVALID_OR_UNSUPPORTED_OPERATOR_ACTION"
            decision_status = "PENDING_OPERATOR_DECISION"
            blocker_status = "UNRESOLVED_OR_PENDING_REVIEW"
            operator_acceptance = "FALSE"

        audit_id = f"V20_127_ACTION_RESOLUTION_AUDIT_{i:03d}"
        audit_rows.append({"action_resolution_audit_id": audit_id, "selected_repair_scenario_id": selected_id, "source_action_capture_record_id": clean(record.get("action_capture_record_id")), "source_action_packet_id": packet_id, "source_operator_decision_record_id": clean(record.get("source_operator_decision_record_id")), "blocker_category": clean(record.get("blocker_category")), "operator_selected_action": action, "action_source": clean(record.get("action_source")), "explicit_valid_human_acceptance_evidence": tf(explicit_acceptance), "operator_acceptance_valid": tf(acceptance_valid), "resolution_status": resolution_status, "decision_status": decision_status, "blocker_status": blocker_status, "operator_acceptance": operator_acceptance, "promotion_ready": "FALSE", "ticker_rows_created": clean(record.get("ticker_rows_created")) or "0", **COMMON})
        remaining_rows.append({"remaining_blocker_resolution_status_id": f"V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS_{i:03d}", "selected_repair_scenario_id": selected_id, "source_action_capture_record_id": clean(record.get("action_capture_record_id")), "source_operator_decision_record_id": clean(record.get("source_operator_decision_record_id")), "blocker_category": clean(record.get("blocker_category")), "resolution_status": resolution_status, "decision_status": decision_status, "blocker_status": blocker_status, "remaining_blocker_requires_review": tf(blocker_status != "RESOLVED_WITH_LIMITATION"), "promotion_ready": "FALSE", **COMMON})
        if action == "NEED_MORE_EVIDENCE":
            evidence_rows.append({"required_next_evidence_audit_id": f"V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT_{len(evidence_rows)+1:03d}", "selected_repair_scenario_id": selected_id, "source_action_capture_record_id": clean(record.get("action_capture_record_id")), "source_action_packet_id": packet_id, "source_operator_decision_record_id": clean(record.get("source_operator_decision_record_id")), "blocker_category": clean(record.get("blocker_category")), "operator_selected_action": action, "required_next_evidence": "explicit valid human acceptance evidence and supporting blocker-specific review evidence", "evidence_required_for_v20_128": "TRUE", "promotion_ready": "FALSE", **COMMON})

    capture_ids = {clean(row.get("action_capture_record_id")) for row in record_rows}
    audit_ids = {clean(row.get("source_action_capture_record_id")) for row in audit_rows}
    every_record_has_audit = bool(record_rows) and len(audit_rows) == len(record_rows) and capture_ids == audit_ids
    need_more_count = sum(1 for row in audit_rows if row["operator_selected_action"] == "NEED_MORE_EVIDENCE")
    not_resolved_count = sum(1 for row in audit_rows if row["resolution_status"] == "NOT_RESOLVED_MORE_EVIDENCE_REQUIRED")
    invalid_acceptance_count = sum(1 for row in audit_rows if row["resolution_status"] == "INVALID_ACCEPTANCE_MISSING_EVIDENCE")
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in record_rows + packet_rows + audit_rows)
    counts = prohibited_counts([decision_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_rows, remaining_input_rows, audit_rows, remaining_rows, evidence_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v126_gate_consumed, allowed, v126_status_allowed, selected_matches, every_record_has_audit, bool(remaining_rows), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    all_resolved_accept = all(row["resolution_status"] == "RESOLVED_ACCEPTED_WITH_LIMITATION" for row in audit_rows)
    if base_ok and all_resolved_accept:
        final_status = PASS_STATUS
    elif base_ok:
        final_status = PARTIAL_STATUS
    else:
        final_status = BLOCKED_STATUS
    next_allowed = final_status in {PARTIAL_STATUS, PASS_STATUS}
    blocking = "" if next_allowed else "operator_action_resolution_gate_requirements_not_met"
    operator_acceptance = tf(operator_acceptance_true_count > 0)

    decision = {"decision_check_id": "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION_001", "v20_126_gate_consumed": tf(v126_gate_consumed), "v20_127_operator_action_resolution_gate_allowed_by_v126": tf(allowed), "v20_126_final_status": v126_status, "v20_126_status_allowed": tf(v126_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_126": tf(selected_matches), "action_capture_record_count": str(len(record_rows)), "action_resolution_audit_row_count": str(len(audit_rows)), "every_action_capture_record_has_resolution_audit": tf(every_record_has_audit), "need_more_evidence_action_count": str(need_more_count), "not_resolved_more_evidence_required_count": str(not_resolved_count), "invalid_acceptance_missing_evidence_count": str(invalid_acceptance_count), "remaining_blocker_resolution_status_count": str(len(remaining_rows)), "required_next_evidence_audit_count": str(len(evidence_rows)), "operator_acceptance": operator_acceptance, "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_128_additional_evidence_collection_plan_allowed": tf(next_allowed), "operator_action_resolution_gate_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_127_NEXT_STAGE_GATE_001", "v20_126_gate_consumed": tf(v126_gate_consumed), "v20_127_operator_action_resolution_gate_allowed_by_v126": tf(allowed), "selected_repair_scenario_id": selected_id, "operator_action_resolution_gate_created": "TRUE", "every_action_capture_record_has_resolution_audit": tf(every_record_has_audit), "operator_acceptance": operator_acceptance, "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_128_additional_evidence_collection_plan_allowed": tf(next_allowed), "next_recommended_action": "V20.128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN" if next_allowed else "V20.127_OPERATOR_ACTION_RESOLUTION_GATE_REPAIR", "blocking_reason": blocking, "operator_action_resolution_gate_status": final_status, **COMMON}
    write_all([decision], audit_rows, remaining_rows, evidence_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_126_GATE_CONSUMED={tf(v126_gate_consumed)}")
    print(f"V20_127_OPERATOR_ACTION_RESOLUTION_GATE_ALLOWED_BY_V126={tf(allowed)}")
    print(f"V20_126_FINAL_STATUS={v126_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_126={tf(selected_matches)}")
    print(f"ACTION_CAPTURE_RECORD_COUNT={len(record_rows)}")
    print(f"ACTION_RESOLUTION_AUDIT_ROW_COUNT={len(audit_rows)}")
    print(f"EVERY_ACTION_CAPTURE_RECORD_HAS_RESOLUTION_AUDIT={tf(every_record_has_audit)}")
    print(f"NEED_MORE_EVIDENCE_ACTION_COUNT={need_more_count}")
    print(f"NOT_RESOLVED_MORE_EVIDENCE_REQUIRED_COUNT={not_resolved_count}")
    print(f"INVALID_ACCEPTANCE_MISSING_EVIDENCE_COUNT={invalid_acceptance_count}")
    print(f"REMAINING_BLOCKER_RESOLUTION_STATUS_COUNT={len(remaining_rows)}")
    print(f"REQUIRED_NEXT_EVIDENCE_AUDIT_COUNT={len(evidence_rows)}")
    print(f"OPERATOR_ACCEPTANCE={operator_acceptance}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
