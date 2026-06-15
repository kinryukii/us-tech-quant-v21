#!/usr/bin/env python
"""V20.144 final human confirmation packet.

Creates final human-confirmation packets for blockers pending final human
confirmation after V20.143. This stage is human-confirmation-packet-only,
audit-only, non-mutating, and does not create another evidence round.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv"
IN_RECORD = CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_RECORD.csv"
IN_VALIDATION = CONSOLIDATION / "V20_143_THIRD_ROUND_DECISION_VALIDATION_AUDIT.csv"
IN_CONSEQUENCE = CONSOLIDATION / "V20_143_THIRD_ROUND_DECISION_CONSEQUENCE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_143_THIRD_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_143_NEXT_STAGE_GATE.csv"
IN_PACKET = CONSOLIDATION / "V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET.csv"
IN_SUMMARY = CONSOLIDATION / "V20_142_THIRD_ROUND_REVIEW_SUMMARY_AUDIT.csv"
IN_COVERAGE = CONSOLIDATION / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
IN_RESULT = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv"
IN_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"

OUT_DECISION = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT.csv"
OUT_REQUIRED = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS.csv"
OUT_SAFETY = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_144_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V143_REQUIRED_STATUS = "PARTIAL_PASS_V20_143_THIRD_ROUND_DECISIONS_PENDING_FINAL_HUMAN_CONFIRMATION_READY_FOR_V20_144"
PARTIAL_STATUS = "PARTIAL_PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_AWAITING_OPERATOR_INPUT"
BLOCKED_STATUS = "BLOCKED_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET"
PENDING_DECISION = "REQUEST_FINAL_OPERATOR_ESCALATION"
PENDING_STATUS = "PENDING_FINAL_HUMAN_CONFIRMATION"
DEFAULT_ACTION = "AWAITING_EXPLICIT_HUMAN_CONFIRMATION"
HUMAN_ACTIONS = ["ACCEPT_WITH_LIMITATION", "REJECT_KEEP_BLOCKED", "MORE_EVIDENCE_REQUIRED"]

REQUIRED_INPUTS = [IN_DECISION, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_GATE, IN_PACKET, IN_SUMMARY, IN_COVERAGE, IN_RESULT, IN_REMAINING]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 144))
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
    "final_human_confirmation_packet_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_143_gate_consumed", "v20_144_final_human_confirmation_packet_allowed_by_v143", "v20_143_final_status", "v20_143_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_143", "pending_final_human_confirmation_blocker_count", "final_human_confirmation_packet_row_count", "every_pending_blocker_has_final_human_confirmation_packet", "final_human_confirmation_options_audit_row_count", "final_human_confirmation_required_action_row_count", "all_packets_have_exactly_three_allowed_actions", "all_packets_default_awaiting_explicit_human_confirmation", "human_action_auto_selected_count", "no_human_action_auto_selected", "fourth_round_evidence_plan_created", "no_fourth_round_evidence_plan_created", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_145_final_human_decision_capture_allowed", "final_human_confirmation_packet_status", "blocking_reason", *COMMON.keys()]
PACKET_FIELDS = ["final_human_confirmation_packet_id", "selected_repair_scenario_id", "blocker_id", "source_third_round_operator_decision_record_id", "source_third_round_operator_review_packet_id", "source_third_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "source_third_round_evidence_result_audit_id", "blocker_category", "blocker_status", "first_round_evidence_summary", "second_round_evidence_summary", "third_round_evidence_summary", "current_decision_status", "remaining_limitation_summary", "human_confirmation_question", "allowed_human_actions", "default_action", "selected_human_action", "human_action_auto_selected", "operator_input_required", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
OPTIONS_FIELDS = ["final_human_confirmation_options_audit_id", "selected_repair_scenario_id", "source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "human_action_option", "option_available", "option_requires_explicit_human_input", "option_auto_selected", "option_consequence", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
REQUIRED_FIELDS = ["final_human_confirmation_required_action_id", "selected_repair_scenario_id", "source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "required_human_decision", "allowed_human_actions", "human_action_selected", "selected_human_action", "operator_input_required_before_v20_145", "acceptance_blocker_closure_or_promotion_recheck_allowed_before_input", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_143_gate_consumed", "v20_144_final_human_confirmation_packet_allowed_by_v143", "selected_repair_scenario_id", "final_human_confirmation_packet_created", "every_pending_blocker_has_final_human_confirmation_packet", "human_operator_input_required_before_v20_145", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "no_fourth_round_evidence_plan_created", "safety_boundary_audit_passed", "v20_145_final_human_decision_capture_allowed", "next_recommended_action", "blocking_reason", "final_human_confirmation_packet_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.144 creates only final human confirmation packet artifacts and does not auto-select human actions or create promotion readiness.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, packet, options, required, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_OPTIONS, OPTIONS_FIELDS, options)
    write_csv(OUT_REQUIRED, REQUIRED_FIELDS, required)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.144 Final Human Confirmation Packet Report", "",
        f"- wrapper_status: {decision.get('final_human_confirmation_packet_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- pending_final_human_confirmation_blocker_count: {decision.get('pending_final_human_confirmation_blocker_count')}",
        f"- final_human_confirmation_packet_row_count: {decision.get('final_human_confirmation_packet_row_count')}",
        f"- human_action_auto_selected_count: {decision.get('human_action_auto_selected_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_145_final_human_decision_capture_allowed: {decision.get('v20_145_final_human_decision_capture_allowed')}",
        "",
        "V20.145 must wait for explicit human decisions before acceptance, blocker closure, or promotion-readiness recheck.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION_001", "v20_143_gate_consumed": "FALSE", "v20_144_final_human_confirmation_packet_allowed_by_v143": "FALSE", "v20_143_final_status": "", "v20_143_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_143": "FALSE", "pending_final_human_confirmation_blocker_count": "0", "final_human_confirmation_packet_row_count": "0", "every_pending_blocker_has_final_human_confirmation_packet": "FALSE", "final_human_confirmation_options_audit_row_count": "0", "final_human_confirmation_required_action_row_count": "0", "all_packets_have_exactly_three_allowed_actions": "FALSE", "all_packets_default_awaiting_explicit_human_confirmation": "FALSE", "human_action_auto_selected_count": "0", "no_human_action_auto_selected": "TRUE", "fourth_round_evidence_plan_created": "FALSE", "no_fourth_round_evidence_plan_created": "TRUE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_145_final_human_decision_capture_allowed": "FALSE", "final_human_confirmation_packet_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_144_NEXT_STAGE_GATE_001", "v20_143_gate_consumed": "FALSE", "v20_144_final_human_confirmation_packet_allowed_by_v143": "FALSE", "selected_repair_scenario_id": "", "final_human_confirmation_packet_created": "TRUE", "every_pending_blocker_has_final_human_confirmation_packet": "FALSE", "human_operator_input_required_before_v20_145": "TRUE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "no_fourth_round_evidence_plan_created": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_145_final_human_decision_capture_allowed": "FALSE", "next_recommended_action": "V20.144_FINAL_HUMAN_CONFIRMATION_PACKET_REPAIR", "blocking_reason": blocking, "final_human_confirmation_packet_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_143_GATE_CONSUMED=FALSE")
    print("V20_145_FINAL_HUMAN_DECISION_CAPTURE_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def option_consequence(action: str) -> str:
    if action == "ACCEPT_WITH_LIMITATION":
        return "Requires explicit human confirmation; only then can later capture consider acceptance with limitations."
    if action == "REJECT_KEEP_BLOCKED":
        return "Requires explicit human confirmation; blocker remains blocked after later capture."
    return "Requires explicit human confirmation; later capture may request more evidence without automatic selection."


def build_packets(selected_id: str, pending_rows: list[dict[str, str]], packet_rows: list[dict[str, str]], summary_rows: list[dict[str, str]], coverage_rows: list[dict[str, str]], result_rows: list[dict[str, str]], remaining_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    packet_by_id = {clean(row.get("third_round_operator_review_packet_id")): row for row in packet_rows}
    summary_by_packet = {clean(row.get("source_third_round_operator_review_packet_id")): row for row in summary_rows}
    coverage_by_id = {clean(row.get("third_round_blocker_coverage_audit_id")): row for row in coverage_rows}
    result_by_id = {clean(row.get("third_round_evidence_result_audit_id")): row for row in result_rows}
    remaining_by_id = {clean(row.get("remaining_evidence_blocker_status_id")): row for row in remaining_rows}
    packets, options, required = [], [], []
    for i, record in enumerate(pending_rows, start=1):
        packet = packet_by_id.get(clean(record.get("source_third_round_operator_review_packet_id")), {})
        summary = summary_by_packet.get(clean(packet.get("third_round_operator_review_packet_id")), {})
        coverage = coverage_by_id.get(clean(record.get("source_third_round_blocker_coverage_audit_id")), {})
        result = result_by_id.get(clean(packet.get("source_third_round_evidence_result_audit_id")) or clean(coverage.get("source_third_round_evidence_result_audit_id")), {})
        remaining = remaining_by_id.get(clean(record.get("source_remaining_evidence_blocker_status_id")), {})
        blocker_id = clean(record.get("source_remaining_evidence_blocker_status_id")) or clean(record.get("third_round_operator_decision_record_id"))
        packet_id = f"V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_{i:03d}"
        first_summary = f"First-round/open blocker state: {clean(remaining.get('resolution_status')) or 'NOT_RESOLVED'}; evidence decision status: {clean(remaining.get('evidence_decision_status')) or 'PENDING_MORE_EVIDENCE'}."
        second_summary = f"Second-round operator path escalated to third-round review via {clean(coverage.get('source_second_round_operator_decision_record_id')) or 'second-round decision record'}."
        third_summary = clean(summary.get("third_round_review_summary")) or clean(result.get("dry_run_result_summary")) or "Third-round evidence is available for review only; explicit human confirmation remains absent."
        allowed_actions = ";".join(HUMAN_ACTIONS)
        packets.append({
            "final_human_confirmation_packet_id": packet_id,
            "selected_repair_scenario_id": selected_id,
            "blocker_id": blocker_id,
            "source_third_round_operator_decision_record_id": clean(record.get("third_round_operator_decision_record_id")),
            "source_third_round_operator_review_packet_id": clean(record.get("source_third_round_operator_review_packet_id")),
            "source_third_round_blocker_coverage_audit_id": clean(record.get("source_third_round_blocker_coverage_audit_id")),
            "source_remaining_evidence_blocker_status_id": clean(record.get("source_remaining_evidence_blocker_status_id")),
            "source_third_round_evidence_result_audit_id": clean(packet.get("source_third_round_evidence_result_audit_id")) or clean(coverage.get("source_third_round_evidence_result_audit_id")),
            "blocker_category": clean(record.get("blocker_category")),
            "blocker_status": clean(record.get("blocker_status")),
            "first_round_evidence_summary": first_summary,
            "second_round_evidence_summary": second_summary,
            "third_round_evidence_summary": third_summary,
            "current_decision_status": clean(record.get("decision_status")),
            "remaining_limitation_summary": clean(packet.get("remaining_limitation_summary")) or "No explicit human confirmation has been captured; no acceptance, blocker closure, or promotion-readiness recheck is allowed.",
            "human_confirmation_question": "Select exactly one final human action for this blocker before V20.145 can capture a decision.",
            "allowed_human_actions": allowed_actions,
            "default_action": DEFAULT_ACTION,
            "selected_human_action": "",
            "human_action_auto_selected": "FALSE",
            "operator_input_required": "TRUE",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        required.append({
            "final_human_confirmation_required_action_id": f"V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_final_human_confirmation_packet_id": packet_id,
            "blocker_id": blocker_id,
            "blocker_category": clean(record.get("blocker_category")),
            "required_human_decision": "Choose one explicit final human action before V20.145.",
            "allowed_human_actions": allowed_actions,
            "human_action_selected": "FALSE",
            "selected_human_action": "",
            "operator_input_required_before_v20_145": "TRUE",
            "acceptance_blocker_closure_or_promotion_recheck_allowed_before_input": "FALSE",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
        for action in HUMAN_ACTIONS:
            options.append({
                "final_human_confirmation_options_audit_id": f"V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT_{len(options)+1:03d}",
                "selected_repair_scenario_id": selected_id,
                "source_final_human_confirmation_packet_id": packet_id,
                "blocker_id": blocker_id,
                "blocker_category": clean(record.get("blocker_category")),
                "human_action_option": action,
                "option_available": "TRUE",
                "option_requires_explicit_human_input": "TRUE",
                "option_auto_selected": "FALSE",
                "option_consequence": option_consequence(action),
                "evidence_acceptance": "FALSE",
                "operator_acceptance": "FALSE",
                "promotion_ready": "FALSE",
                **COMMON,
            })
    return packets, options, required


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
    packet_input_rows = read_csv(IN_PACKET)
    summary_rows = read_csv(IN_SUMMARY)
    coverage_rows = read_csv(IN_COVERAGE)
    result_rows = read_csv(IN_RESULT)
    remaining_rows = read_csv(IN_REMAINING)
    if not all([decision_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_input_rows, summary_rows, coverage_rows, result_rows, remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v143_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_143_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_144_final_human_confirmation_packet_allowed"))
    v143_status = clean(gate_in.get("third_round_operator_decision_capture_status")) or clean(decision_in.get("third_round_operator_decision_capture_status"))
    v143_status_allowed = v143_status == V143_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    pending_rows = [row for row in record_rows if clean(row.get("third_round_operator_decision")) == PENDING_DECISION and clean(row.get("decision_status")) == PENDING_STATUS]
    packet_rows, option_rows, required_rows = build_packets(selected_id, pending_rows, packet_input_rows, summary_rows, coverage_rows, result_rows, remaining_rows)

    pending_ids = {clean(row.get("third_round_operator_decision_record_id")) for row in pending_rows}
    packet_record_ids = {clean(row.get("source_third_round_operator_decision_record_id")) for row in packet_rows}
    every_pending_has_packet = bool(pending_rows) and len(packet_rows) == len(pending_rows) and packet_record_ids == pending_ids
    packet_ids = {clean(row.get("final_human_confirmation_packet_id")) for row in packet_rows}
    expected_actions = set(HUMAN_ACTIONS)
    options_by_packet: dict[str, set[str]] = {}
    for row in option_rows:
        options_by_packet.setdefault(clean(row.get("source_final_human_confirmation_packet_id")), set()).add(clean(row.get("human_action_option")))
    options_complete = bool(option_rows) and all(options_by_packet.get(packet_id) == expected_actions for packet_id in packet_ids) and len(option_rows) == len(packet_rows) * len(HUMAN_ACTIONS)
    defaults_ok = all(clean(row.get("default_action")) == DEFAULT_ACTION for row in packet_rows)
    auto_selected_count = sum(1 for row in packet_rows if truthy(row.get("human_action_auto_selected"))) + sum(1 for row in option_rows if truthy(row.get("option_auto_selected"))) + sum(1 for row in required_rows if truthy(row.get("human_action_selected")) or clean(row.get("selected_human_action")))
    no_auto_selected = auto_selected_count == 0
    required_complete = bool(required_rows) and {clean(row.get("source_final_human_confirmation_packet_id")) for row in required_rows} == packet_ids
    fourth_round_created = any(path.exists() for path in [
        CONSOLIDATION / "V20_144_FOURTH_ROUND_EVIDENCE_PLAN.csv",
        CONSOLIDATION / "V20_144_FOURTH_ROUND_EVIDENCE_PLAN_DECISION.csv",
        CONSOLIDATION / "V20_144_NEXT_EVIDENCE_PLAN.csv",
    ])
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in record_rows + packet_rows)
    counts = prohibited_counts([decision_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_input_rows, summary_rows, coverage_rows, result_rows, remaining_rows, packet_rows, option_rows, required_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v143_gate_consumed, allowed, v143_status_allowed, selected_matches, every_pending_has_packet, options_complete, defaults_ok, no_auto_selected, required_complete, not fourth_round_created, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PARTIAL_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PARTIAL_STATUS
    blocking = "" if next_allowed else "final_human_confirmation_packet_requirements_not_met"

    decision = {"decision_check_id": "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION_001", "v20_143_gate_consumed": tf(v143_gate_consumed), "v20_144_final_human_confirmation_packet_allowed_by_v143": tf(allowed), "v20_143_final_status": v143_status, "v20_143_status_allowed": tf(v143_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_143": tf(selected_matches), "pending_final_human_confirmation_blocker_count": str(len(pending_rows)), "final_human_confirmation_packet_row_count": str(len(packet_rows)), "every_pending_blocker_has_final_human_confirmation_packet": tf(every_pending_has_packet), "final_human_confirmation_options_audit_row_count": str(len(option_rows)), "final_human_confirmation_required_action_row_count": str(len(required_rows)), "all_packets_have_exactly_three_allowed_actions": tf(options_complete), "all_packets_default_awaiting_explicit_human_confirmation": tf(defaults_ok), "human_action_auto_selected_count": str(auto_selected_count), "no_human_action_auto_selected": tf(no_auto_selected), "fourth_round_evidence_plan_created": tf(fourth_round_created), "no_fourth_round_evidence_plan_created": tf(not fourth_round_created), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_145_final_human_decision_capture_allowed": tf(next_allowed), "final_human_confirmation_packet_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_144_NEXT_STAGE_GATE_001", "v20_143_gate_consumed": tf(v143_gate_consumed), "v20_144_final_human_confirmation_packet_allowed_by_v143": tf(allowed), "selected_repair_scenario_id": selected_id, "final_human_confirmation_packet_created": "TRUE", "every_pending_blocker_has_final_human_confirmation_packet": tf(every_pending_has_packet), "human_operator_input_required_before_v20_145": "TRUE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "no_fourth_round_evidence_plan_created": tf(not fourth_round_created), "safety_boundary_audit_passed": tf(safety_passed), "v20_145_final_human_decision_capture_allowed": tf(next_allowed), "next_recommended_action": "V20.145_FINAL_HUMAN_DECISION_CAPTURE_AFTER_EXPLICIT_OPERATOR_INPUT" if next_allowed else "V20.144_FINAL_HUMAN_CONFIRMATION_PACKET_REPAIR", "blocking_reason": blocking, "final_human_confirmation_packet_status": final_status, **COMMON}
    write_all([decision], packet_rows, option_rows, required_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_143_GATE_CONSUMED={tf(v143_gate_consumed)}")
    print(f"V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_ALLOWED_BY_V143={tf(allowed)}")
    print(f"V20_143_FINAL_STATUS={v143_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_143={tf(selected_matches)}")
    print(f"PENDING_FINAL_HUMAN_CONFIRMATION_BLOCKER_COUNT={len(pending_rows)}")
    print(f"FINAL_HUMAN_CONFIRMATION_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"EVERY_PENDING_BLOCKER_HAS_FINAL_HUMAN_CONFIRMATION_PACKET={tf(every_pending_has_packet)}")
    print(f"FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT_ROW_COUNT={len(option_rows)}")
    print(f"FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTION_ROW_COUNT={len(required_rows)}")
    print(f"ALL_PACKETS_HAVE_EXACTLY_THREE_ALLOWED_ACTIONS={tf(options_complete)}")
    print(f"ALL_PACKETS_DEFAULT_AWAITING_EXPLICIT_HUMAN_CONFIRMATION={tf(defaults_ok)}")
    print(f"HUMAN_ACTION_AUTO_SELECTED_COUNT={auto_selected_count}")
    print(f"NO_HUMAN_ACTION_AUTO_SELECTED={tf(no_auto_selected)}")
    print(f"FOURTH_ROUND_EVIDENCE_PLAN_CREATED={tf(fourth_round_created)}")
    print("EVIDENCE_ACCEPTANCE=FALSE")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_145_FINAL_HUMAN_DECISION_CAPTURE_ALLOWED={tf(next_allowed)}")
    print("OPERATOR_INPUT_REQUIRED_BEFORE_V20_145=TRUE")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
