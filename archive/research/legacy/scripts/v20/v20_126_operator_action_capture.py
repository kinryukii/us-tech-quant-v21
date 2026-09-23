#!/usr/bin/env python
"""V20.126 operator action capture.

Captures operator action selections for pending decisions. Because no explicit
human action has been supplied, the conservative default is captured as
NEED_MORE_EVIDENCE for every pending decision. This stage is audit-only,
non-mutating, and never marks promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_DECISION.csv"
IN_PACKET = CONSOLIDATION / "V20_125_OPERATOR_ACTION_PACKET.csv"
IN_OPTIONS = CONSOLIDATION / "V20_125_OPERATOR_ACTION_OPTIONS_AUDIT.csv"
IN_EVIDENCE = CONSOLIDATION / "V20_125_OPERATOR_ACTION_EVIDENCE_SUMMARY.csv"
IN_SAFETY = CONSOLIDATION / "V20_125_OPERATOR_ACTION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_125_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_DECISION.csv"
OUT_RECORD = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_126_OPERATOR_ACTION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_126_OPERATOR_ACTION_CAPTURE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_126_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_126_OPERATOR_ACTION_CAPTURE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V125_REQUIRED_STATUS = "PASS_V20_125_OPERATOR_REVIEW_ACTION_PACKET_READY_FOR_V20_126"
PARTIAL_STATUS = "PARTIAL_PASS_V20_126_OPERATOR_ACTIONS_DEFAULT_MORE_EVIDENCE_READY_FOR_V20_127"
PASS_STATUS = "PASS_V20_126_OPERATOR_ACTION_CAPTURE_READY_FOR_V20_127"
BLOCKED_STATUS = "BLOCKED_V20_126_OPERATOR_ACTION_CAPTURE"
DEFAULT_ACTION = "NEED_MORE_EVIDENCE"
REQUIRED_INPUTS = [IN_DECISION, IN_PACKET, IN_OPTIONS, IN_EVIDENCE, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125"]],
    IN_DECISION, IN_PACKET, IN_OPTIONS, IN_EVIDENCE, IN_SAFETY,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "operator_action_capture_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_125_gate_consumed", "v20_126_operator_action_capture_allowed_by_v125", "v20_125_final_status", "v20_125_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_125", "action_packet_row_count", "action_capture_record_count", "every_action_packet_has_capture_record", "default_need_more_evidence_count", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_127_operator_action_resolution_gate_allowed", "operator_action_capture_status", "blocking_reason", *COMMON.keys()]
RECORD_FIELDS = ["action_capture_record_id", "selected_repair_scenario_id", "source_action_packet_id", "source_operator_decision_record_id", "blocker_category", "operator_selected_action", "action_source", "captured_operator_action", "capture_source", "decision_status", "blocker_status", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
VALIDATION_FIELDS = ["validation_audit_id", "selected_repair_scenario_id", "source_action_packet_id", "blocker_category", "operator_selected_action", "captured_operator_action", "action_available_in_v125_options", "selected_action_valid", "conservative_default_used", "explicit_valid_human_acceptance_evidence", "operator_acceptance_valid", "promotion_ready", *COMMON.keys()]
CONSEQUENCE_FIELDS = ["consequence_audit_id", "selected_repair_scenario_id", "source_action_packet_id", "blocker_category", "operator_selected_action", "captured_operator_action", "action_consequence", "decision_status", "blocker_status", "decision_remains_pending", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_125_gate_consumed", "v20_126_operator_action_capture_allowed_by_v125", "selected_repair_scenario_id", "operator_action_capture_created", "every_action_packet_has_capture_record", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_127_operator_action_resolution_gate_allowed", "next_recommended_action", "blocking_reason", "operator_action_capture_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_126_OPERATOR_ACTION_CAPTURE_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.126 captures only conservative operator action defaults and keeps promotion readiness false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


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
        "# V20.126 Operator Action Capture Report", "",
        f"- wrapper_status: {decision.get('operator_action_capture_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- action_capture_record_count: {decision.get('action_capture_record_count')}",
        f"- default_need_more_evidence_count: {decision.get('default_need_more_evidence_count')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_127_operator_action_resolution_gate_allowed: {decision.get('v20_127_operator_action_resolution_gate_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_126_OPERATOR_ACTION_CAPTURE_DECISION_001", "v20_125_gate_consumed": "FALSE", "v20_126_operator_action_capture_allowed_by_v125": "FALSE", "v20_125_final_status": "", "v20_125_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_125": "FALSE", "action_packet_row_count": "0", "action_capture_record_count": "0", "every_action_packet_has_capture_record": "FALSE", "default_need_more_evidence_count": "0", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_127_operator_action_resolution_gate_allowed": "FALSE", "operator_action_capture_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_126_NEXT_STAGE_GATE_001", "v20_125_gate_consumed": "FALSE", "v20_126_operator_action_capture_allowed_by_v125": "FALSE", "selected_repair_scenario_id": "", "operator_action_capture_created": "TRUE", "every_action_packet_has_capture_record": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_127_operator_action_resolution_gate_allowed": "FALSE", "next_recommended_action": "V20.126_OPERATOR_ACTION_CAPTURE_REPAIR", "blocking_reason": blocking, "operator_action_capture_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_125_GATE_CONSUMED=FALSE")
    print("V20_127_OPERATOR_ACTION_RESOLUTION_GATE_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    packet_rows = read_csv(IN_PACKET)
    option_rows = read_csv(IN_OPTIONS)
    evidence_rows = read_csv(IN_EVIDENCE)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, packet_rows, option_rows, evidence_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v125_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_125_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_126_operator_action_capture_allowed"))
    v125_status = clean(gate_in.get("operator_review_action_packet_status")) or clean(decision_in.get("operator_review_action_packet_status"))
    v125_status_allowed = v125_status == V125_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    available_by_packet = {}
    consequence_by_packet_action = {}
    for row in option_rows:
        packet_id = clean(row.get("source_action_packet_id"))
        action = clean(row.get("operator_action"))
        if truthy(row.get("action_available")):
            available_by_packet.setdefault(packet_id, set()).add(action)
        consequence_by_packet_action[(packet_id, action)] = clean(row.get("action_consequence"))

    record_rows = []
    validation_rows = []
    consequence_rows = []
    for i, packet in enumerate(packet_rows, start=1):
        packet_id = clean(packet.get("action_packet_id"))
        category = clean(packet.get("blocker_category"))
        selected_action = DEFAULT_ACTION
        available = selected_action in available_by_packet.get(packet_id, set())
        decision_status = "PENDING_OPERATOR_DECISION"
        blocker_status = "UNRESOLVED_OR_PENDING_REVIEW"
        action_source = "CONSERVATIVE_DEFAULT_NO_EXPLICIT_HUMAN_ACCEPTANCE"
        record_rows.append({"action_capture_record_id": f"V20_126_OPERATOR_ACTION_CAPTURE_RECORD_{i:03d}", "selected_repair_scenario_id": selected_id, "source_action_packet_id": packet_id, "source_operator_decision_record_id": clean(packet.get("source_operator_decision_record_id")), "blocker_category": category, "operator_selected_action": selected_action, "action_source": action_source, "captured_operator_action": selected_action, "capture_source": action_source, "decision_status": decision_status, "blocker_status": blocker_status, "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "ticker_rows_created": "0", **COMMON})
        validation_rows.append({"validation_audit_id": f"V20_126_OPERATOR_ACTION_VALIDATION_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "source_action_packet_id": packet_id, "blocker_category": category, "operator_selected_action": selected_action, "captured_operator_action": selected_action, "action_available_in_v125_options": tf(available), "selected_action_valid": tf(available), "conservative_default_used": "TRUE", "explicit_valid_human_acceptance_evidence": "FALSE", "operator_acceptance_valid": "FALSE", "promotion_ready": "FALSE", **COMMON})
        consequence_rows.append({"consequence_audit_id": f"V20_126_OPERATOR_ACTION_CONSEQUENCE_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "source_action_packet_id": packet_id, "blocker_category": category, "operator_selected_action": selected_action, "captured_operator_action": selected_action, "action_consequence": consequence_by_packet_action.get((packet_id, selected_action), "Keeps decision pending and requests additional evidence before acceptance."), "decision_status": decision_status, "blocker_status": blocker_status, "decision_remains_pending": "TRUE", "promotion_ready": "FALSE", **COMMON})

    every_packet_has_capture = bool(packet_rows) and len(record_rows) == len(packet_rows) and {row["source_action_packet_id"] for row in record_rows} == {clean(row.get("action_packet_id")) for row in packet_rows}
    default_count = sum(1 for row in record_rows if row["captured_operator_action"] == DEFAULT_ACTION)
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in packet_rows + record_rows)
    counts = prohibited_counts([decision_rows, packet_rows, option_rows, evidence_rows, safety_input_rows, gate_rows, record_rows, validation_rows, consequence_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    all_valid = all(truthy(row.get("action_available_in_v125_options")) and truthy(row.get("conservative_default_used")) for row in validation_rows)
    base_ok = all([v125_gate_consumed, allowed, v125_status_allowed, selected_matches, every_packet_has_capture, all_valid, bool(consequence_rows), default_count == len(packet_rows), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PARTIAL_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PARTIAL_STATUS or final_status == PASS_STATUS
    blocking = "" if next_allowed else "operator_action_capture_requirements_not_met"

    decision = {"decision_check_id": "V20_126_OPERATOR_ACTION_CAPTURE_DECISION_001", "v20_125_gate_consumed": tf(v125_gate_consumed), "v20_126_operator_action_capture_allowed_by_v125": tf(allowed), "v20_125_final_status": v125_status, "v20_125_status_allowed": tf(v125_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_125": tf(selected_matches), "action_packet_row_count": str(len(packet_rows)), "action_capture_record_count": str(len(record_rows)), "every_action_packet_has_capture_record": tf(every_packet_has_capture), "default_need_more_evidence_count": str(default_count), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_127_operator_action_resolution_gate_allowed": tf(next_allowed), "operator_action_capture_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_126_NEXT_STAGE_GATE_001", "v20_125_gate_consumed": tf(v125_gate_consumed), "v20_126_operator_action_capture_allowed_by_v125": tf(allowed), "selected_repair_scenario_id": selected_id, "operator_action_capture_created": "TRUE", "every_action_packet_has_capture_record": tf(every_packet_has_capture), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_127_operator_action_resolution_gate_allowed": tf(next_allowed), "next_recommended_action": "V20.127_OPERATOR_ACTION_RESOLUTION_GATE" if next_allowed else "V20.126_OPERATOR_ACTION_CAPTURE_REPAIR", "blocking_reason": blocking, "operator_action_capture_status": final_status, **COMMON}
    write_all([decision], record_rows, validation_rows, consequence_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_125_GATE_CONSUMED={tf(v125_gate_consumed)}")
    print(f"V20_126_OPERATOR_ACTION_CAPTURE_ALLOWED_BY_V125={tf(allowed)}")
    print(f"V20_125_FINAL_STATUS={v125_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_125={tf(selected_matches)}")
    print(f"ACTION_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"ACTION_CAPTURE_RECORD_COUNT={len(record_rows)}")
    print(f"EVERY_ACTION_PACKET_HAS_CAPTURE_RECORD={tf(every_packet_has_capture)}")
    print(f"DEFAULT_NEED_MORE_EVIDENCE_COUNT={default_count}")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_127_OPERATOR_ACTION_RESOLUTION_GATE_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
