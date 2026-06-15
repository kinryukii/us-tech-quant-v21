#!/usr/bin/env python
"""V20.143 third-round operator decision capture.

Captures conservative third-round operator decisions for V20.142 review
packets. Because no explicit human acceptance exists, every packet defaults
to REQUEST_FINAL_OPERATOR_ESCALATION. This stage is audit-only and non-mutating.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv"
IN_PACKET = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET.csv"
IN_SUMMARY = CONSOLIDATION / "V20_142_THIRD_ROUND_REVIEW_SUMMARY_AUDIT.csv"
IN_OPTIONS = CONSOLIDATION / "V20_142_THIRD_ROUND_REVIEW_OPTIONS_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_142_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv"
OUT_RECORD = CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_143_THIRD_ROUND_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_143_THIRD_ROUND_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_143_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V142_REQUIRED_STATUS = "PASS_V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_READY_FOR_V20_143"
PARTIAL_STATUS = "PARTIAL_PASS_V20_143_THIRD_ROUND_DECISIONS_PENDING_FINAL_HUMAN_CONFIRMATION_READY_FOR_V20_144"
PASS_STATUS = "PASS_V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_144"
BLOCKED_STATUS = "BLOCKED_V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE"
VALID_DECISIONS = ["ACCEPT_THIRD_ROUND_EVIDENCE_WITH_LIMITATION", "REJECT_THIRD_ROUND_EVIDENCE_KEEP_BLOCKED", "REQUEST_FINAL_OPERATOR_ESCALATION"]
DEFAULT_DECISION = "REQUEST_FINAL_OPERATOR_ESCALATION"
DEFAULT_SOURCE = "CONSERVATIVE_DEFAULT_NO_EXPLICIT_HUMAN_THIRD_ROUND_ACCEPTANCE"

REQUIRED_INPUTS = [IN_DECISION, IN_PACKET, IN_SUMMARY, IN_OPTIONS, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 143))
)
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE",
    "third_round_operator_decision_capture_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_142_gate_consumed", "v20_143_third_round_operator_decision_capture_allowed_by_v142", "v20_142_final_status", "v20_142_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_142", "third_round_review_packet_row_count", "third_round_operator_decision_record_count", "every_third_round_review_packet_has_decision_record", "default_request_final_operator_escalation_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_144_final_human_confirmation_packet_allowed", "third_round_operator_decision_capture_status", "blocking_reason", *COMMON.keys()]
RECORD_FIELDS = ["third_round_operator_decision_record_id", "selected_repair_scenario_id", "source_third_round_operator_review_packet_id", "source_third_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "source_operator_decision_record_id", "blocker_category", "third_round_operator_decision", "decision_source", "evidence_acceptance", "operator_acceptance", "decision_status", "blocker_status", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
VALIDATION_FIELDS = ["third_round_decision_validation_audit_id", "selected_repair_scenario_id", "source_third_round_operator_review_packet_id", "blocker_category", "third_round_operator_decision", "decision_available_in_v142_options", "third_round_decision_valid", "conservative_default_used", "explicit_valid_human_third_round_acceptance", "third_round_acceptance_valid", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
CONSEQUENCE_FIELDS = ["third_round_decision_consequence_audit_id", "selected_repair_scenario_id", "source_third_round_operator_review_packet_id", "blocker_category", "third_round_operator_decision", "third_round_decision_consequence", "decision_status", "blocker_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_142_gate_consumed", "v20_143_third_round_operator_decision_capture_allowed_by_v142", "selected_repair_scenario_id", "third_round_operator_decision_capture_created", "every_third_round_review_packet_has_decision_record", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_144_final_human_confirmation_packet_allowed", "next_recommended_action", "blocking_reason", "third_round_operator_decision_capture_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_143_THIRD_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.143 captures only conservative third-round decisions and keeps promotion readiness false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, record, validation, consequence, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_RECORD, RECORD_FIELDS, record)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation)
    write_csv(OUT_CONSEQUENCE, CONSEQUENCE_FIELDS, consequence)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.143 Third-Round Operator Decision Capture Report", "",
        f"- wrapper_status: {decision.get('third_round_operator_decision_capture_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- third_round_review_packet_row_count: {decision.get('third_round_review_packet_row_count')}",
        f"- third_round_operator_decision_record_count: {decision.get('third_round_operator_decision_record_count')}",
        f"- default_request_final_operator_escalation_count: {decision.get('default_request_final_operator_escalation_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_144_final_human_confirmation_packet_allowed: {decision.get('v20_144_final_human_confirmation_packet_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_DECISION_001", "v20_142_gate_consumed": "FALSE", "v20_143_third_round_operator_decision_capture_allowed_by_v142": "FALSE", "v20_142_final_status": "", "v20_142_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_142": "FALSE", "third_round_review_packet_row_count": "0", "third_round_operator_decision_record_count": "0", "every_third_round_review_packet_has_decision_record": "FALSE", "default_request_final_operator_escalation_count": "0", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_144_final_human_confirmation_packet_allowed": "FALSE", "third_round_operator_decision_capture_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_143_NEXT_STAGE_GATE_001", "v20_142_gate_consumed": "FALSE", "v20_143_third_round_operator_decision_capture_allowed_by_v142": "FALSE", "selected_repair_scenario_id": "", "third_round_operator_decision_capture_created": "TRUE", "every_third_round_review_packet_has_decision_record": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_144_final_human_confirmation_packet_allowed": "FALSE", "next_recommended_action": "V20.143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_REPAIR", "blocking_reason": blocking, "third_round_operator_decision_capture_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_142_GATE_CONSUMED=FALSE")
    print("V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def consequence_for(decision: str) -> tuple[str, str, str]:
    if decision == "REJECT_THIRD_ROUND_EVIDENCE_KEEP_BLOCKED":
        return "THIRD_ROUND_EVIDENCE_REJECTED_KEEP_BLOCKED", "BLOCKED", "Third-round evidence rejected; blocker remains blocked and promotion readiness remains false."
    if decision == "ACCEPT_THIRD_ROUND_EVIDENCE_WITH_LIMITATION":
        return "PENDING_FINAL_HUMAN_CONFIRMATION", "UNRESOLVED_OR_PENDING_FINAL_OPERATOR_CONFIRMATION", "Explicit valid human third-round acceptance is required; absent evidence prevents acceptance."
    return "PENDING_FINAL_HUMAN_CONFIRMATION", "UNRESOLVED_OR_PENDING_FINAL_OPERATOR_CONFIRMATION", "Final operator escalation requested; blocker remains unresolved pending final human confirmation."


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)
    decision_rows = read_csv(IN_DECISION)
    packet_rows = read_csv(IN_PACKET)
    summary_rows = read_csv(IN_SUMMARY)
    option_rows = read_csv(IN_OPTIONS)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, packet_rows, summary_rows, option_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v142_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_142_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_143_third_round_operator_decision_capture_allowed"))
    v142_status = clean(gate_in.get("third_round_operator_review_packet_status")) or clean(decision_in.get("third_round_operator_review_packet_status"))
    v142_status_allowed = v142_status == V142_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    available_by_packet: dict[str, set[str]] = {}
    for row in option_rows:
        if truthy(row.get("option_available")):
            available_by_packet.setdefault(clean(row.get("source_third_round_operator_review_packet_id")), set()).add(clean(row.get("review_option")))

    record_rows = []
    validation_rows = []
    consequence_rows = []
    for i, packet in enumerate(packet_rows, start=1):
        packet_id = clean(packet.get("third_round_operator_review_packet_id"))
        selected_decision = DEFAULT_DECISION
        decision_available = selected_decision in available_by_packet.get(packet_id, set())
        decision_valid = selected_decision in VALID_DECISIONS and decision_available
        explicit_acceptance = False
        acceptance_valid = False
        status, blocker_status, consequence = consequence_for(selected_decision)
        record_rows.append({
            "third_round_operator_decision_record_id": f"V20_143_THIRD_ROUND_OPERATOR_DECISION_RECORD_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_operator_review_packet_id": packet_id,
            "source_third_round_blocker_coverage_audit_id": clean(packet.get("source_third_round_blocker_coverage_audit_id")),
            "source_remaining_evidence_blocker_status_id": clean(packet.get("source_remaining_evidence_blocker_status_id")),
            "source_operator_decision_record_id": clean(packet.get("source_operator_decision_record_id")),
            "blocker_category": clean(packet.get("blocker_category")),
            "third_round_operator_decision": selected_decision,
            "decision_source": DEFAULT_SOURCE,
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "decision_status": status,
            "blocker_status": blocker_status,
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        validation_rows.append({
            "third_round_decision_validation_audit_id": f"V20_143_THIRD_ROUND_DECISION_VALIDATION_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_operator_review_packet_id": packet_id,
            "blocker_category": clean(packet.get("blocker_category")),
            "third_round_operator_decision": selected_decision,
            "decision_available_in_v142_options": tf(decision_available),
            "third_round_decision_valid": tf(decision_valid),
            "conservative_default_used": "TRUE",
            "explicit_valid_human_third_round_acceptance": tf(explicit_acceptance),
            "third_round_acceptance_valid": tf(acceptance_valid),
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
        consequence_rows.append({
            "third_round_decision_consequence_audit_id": f"V20_143_THIRD_ROUND_DECISION_CONSEQUENCE_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_operator_review_packet_id": packet_id,
            "blocker_category": clean(packet.get("blocker_category")),
            "third_round_operator_decision": selected_decision,
            "third_round_decision_consequence": consequence,
            "decision_status": status,
            "blocker_status": blocker_status,
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })

    packet_ids = {clean(row.get("third_round_operator_review_packet_id")) for row in packet_rows}
    record_packet_ids = {clean(row.get("source_third_round_operator_review_packet_id")) for row in record_rows}
    every_packet_has_record = bool(packet_rows) and len(record_rows) == len(packet_rows) and packet_ids == record_packet_ids
    default_count = sum(1 for row in record_rows if row["third_round_operator_decision"] == DEFAULT_DECISION)
    all_valid = bool(validation_rows) and all(truthy(row.get("third_round_decision_valid")) for row in validation_rows)
    no_invalid_acceptance = not any(row["third_round_operator_decision"] == "ACCEPT_THIRD_ROUND_EVIDENCE_WITH_LIMITATION" and row["explicit_valid_human_third_round_acceptance"] != "TRUE" for row in validation_rows)
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in packet_rows + record_rows)
    counts = prohibited_counts([decision_rows, packet_rows, summary_rows, option_rows, safety_input_rows, gate_rows, record_rows, validation_rows, consequence_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v142_gate_consumed, allowed, v142_status_allowed, selected_matches, every_packet_has_record, all_valid, no_invalid_acceptance, default_count == len(packet_rows), bool(consequence_rows), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PARTIAL_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status in {PARTIAL_STATUS, PASS_STATUS}
    blocking = "" if next_allowed else "third_round_operator_decision_capture_requirements_not_met"

    decision = {"decision_check_id": "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_DECISION_001", "v20_142_gate_consumed": tf(v142_gate_consumed), "v20_143_third_round_operator_decision_capture_allowed_by_v142": tf(allowed), "v20_142_final_status": v142_status, "v20_142_status_allowed": tf(v142_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_142": tf(selected_matches), "third_round_review_packet_row_count": str(len(packet_rows)), "third_round_operator_decision_record_count": str(len(record_rows)), "every_third_round_review_packet_has_decision_record": tf(every_packet_has_record), "default_request_final_operator_escalation_count": str(default_count), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_144_final_human_confirmation_packet_allowed": tf(next_allowed), "third_round_operator_decision_capture_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_143_NEXT_STAGE_GATE_001", "v20_142_gate_consumed": tf(v142_gate_consumed), "v20_143_third_round_operator_decision_capture_allowed_by_v142": tf(allowed), "selected_repair_scenario_id": selected_id, "third_round_operator_decision_capture_created": "TRUE", "every_third_round_review_packet_has_decision_record": tf(every_packet_has_record), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_144_final_human_confirmation_packet_allowed": tf(next_allowed), "next_recommended_action": "V20.144_FINAL_HUMAN_CONFIRMATION_PACKET" if next_allowed else "V20.143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_REPAIR", "blocking_reason": blocking, "third_round_operator_decision_capture_status": final_status, **COMMON}
    write_all([decision], record_rows, validation_rows, consequence_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_142_GATE_CONSUMED={tf(v142_gate_consumed)}")
    print(f"V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_ALLOWED_BY_V142={tf(allowed)}")
    print(f"V20_142_FINAL_STATUS={v142_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_142={tf(selected_matches)}")
    print(f"THIRD_ROUND_REVIEW_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"THIRD_ROUND_OPERATOR_DECISION_RECORD_COUNT={len(record_rows)}")
    print(f"EVERY_THIRD_ROUND_REVIEW_PACKET_HAS_DECISION_RECORD={tf(every_packet_has_record)}")
    print(f"DEFAULT_REQUEST_FINAL_OPERATOR_ESCALATION_COUNT={default_count}")
    print("EVIDENCE_ACCEPTANCE=FALSE")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

