#!/usr/bin/env python
"""V20.125 operator review action packet.

Builds an operator-readable, audit-only action packet for remaining pending
operator decisions. This stage creates no official artifacts, accepts no
decisions, fabricates no ticker rows, and never marks promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_DECISION.csv"
IN_UPDATED = CONSOLIDATION / "V20_124_UPDATED_OPERATOR_DECISION_RECORD.csv"
IN_RATIONALE = CONSOLIDATION / "V20_124_DECISION_UPDATE_RATIONALE_AUDIT.csv"
IN_REMAINING = CONSOLIDATION / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_124_NEXT_STAGE_GATE.csv"
IN_V123_CLOSURE = CONSOLIDATION / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv"
IN_V122_PLAN = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv"
IN_V119_REQUIRED = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv"
IN_V118_REMAINING = CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv"

OUT_DECISION = CONSOLIDATION / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_125_OPERATOR_ACTION_PACKET.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_125_OPERATOR_ACTION_OPTIONS_AUDIT.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_125_OPERATOR_ACTION_EVIDENCE_SUMMARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_125_OPERATOR_ACTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_125_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_125_OPERATOR_REVIEW_ACTION_PACKET_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V124_REQUIRED_STATUS = "PARTIAL_PASS_V20_124_OPERATOR_DECISIONS_STILL_REQUIRE_REVIEW_READY_FOR_V20_125"
PASS_STATUS = "PASS_V20_125_OPERATOR_REVIEW_ACTION_PACKET_READY_FOR_V20_126"
BLOCKED_STATUS = "BLOCKED_V20_125_OPERATOR_REVIEW_ACTION_PACKET"
ACTION_OPTIONS = ["ACCEPT_WITH_LIMITATION", "REJECT_AND_KEEP_BLOCKED", "NEED_MORE_EVIDENCE"]
DEFAULT_ACTION = "NEED_MORE_EVIDENCE"

REQUIRED_INPUTS = [IN_DECISION, IN_UPDATED, IN_RATIONALE, IN_REMAINING, IN_SAFETY, IN_GATE, IN_V123_CLOSURE, IN_V122_PLAN, IN_V119_REQUIRED, IN_V118_REMAINING]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124"]],
    IN_DECISION, IN_UPDATED, IN_RATIONALE, IN_REMAINING, IN_SAFETY, IN_V123_CLOSURE, IN_V122_PLAN, IN_V119_REQUIRED, IN_V118_REMAINING,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "operator_review_action_packet_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_124_gate_consumed", "v20_125_operator_review_action_packet_allowed_by_v124", "v20_124_final_status", "v20_124_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_124", "remaining_pending_decision_count", "action_packet_row_count", "every_remaining_pending_decision_has_action_packet", "action_options_audit_row_count", "evidence_summary_row_count", "all_packet_rows_include_required_options", "all_packet_rows_default_need_more_evidence", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_126_operator_action_capture_allowed", "operator_review_action_packet_status", "blocking_reason", *COMMON.keys()]
PACKET_FIELDS = ["action_packet_id", "selected_repair_scenario_id", "source_remaining_review_id", "source_operator_decision_record_id", "blocker_category", "pending_reason", "evidence_status", "related_evidence_files", "available_operator_actions", "recommended_conservative_default", "accept_with_limitation_consequence", "reject_and_keep_blocked_consequence", "need_more_evidence_consequence", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
OPTIONS_FIELDS = ["action_option_audit_id", "selected_repair_scenario_id", "source_action_packet_id", "blocker_category", "operator_action", "action_available", "action_consequence", "recommended_default", "promotion_ready", *COMMON.keys()]
EVIDENCE_FIELDS = ["evidence_summary_id", "selected_repair_scenario_id", "source_action_packet_id", "blocker_category", "evidence_status", "related_evidence_files", "evidence_summary", "operator_review_required", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_124_gate_consumed", "v20_125_operator_review_action_packet_allowed_by_v124", "selected_repair_scenario_id", "operator_review_action_packet_created", "every_remaining_pending_decision_has_action_packet", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_126_operator_action_capture_allowed", "next_recommended_action", "blocking_reason", "operator_review_action_packet_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_125_OPERATOR_ACTION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.125 creates only operator action packet artifacts and keeps promotion readiness false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, packet, options, evidence, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_OPTIONS, OPTIONS_FIELDS, options)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.125 Operator Review Action Packet Report", "",
        f"- wrapper_status: {decision.get('operator_review_action_packet_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- remaining_pending_decision_count: {decision.get('remaining_pending_decision_count')}",
        f"- action_packet_row_count: {decision.get('action_packet_row_count')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_126_operator_action_capture_allowed: {decision.get('v20_126_operator_action_capture_allowed')}",
        "- official_recommendation_created: FALSE", "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_125_OPERATOR_REVIEW_ACTION_PACKET_DECISION_001", "v20_124_gate_consumed": "FALSE", "v20_125_operator_review_action_packet_allowed_by_v124": "FALSE", "v20_124_final_status": "", "v20_124_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_124": "FALSE", "remaining_pending_decision_count": "0", "action_packet_row_count": "0", "every_remaining_pending_decision_has_action_packet": "FALSE", "action_options_audit_row_count": "0", "evidence_summary_row_count": "0", "all_packet_rows_include_required_options": "FALSE", "all_packet_rows_default_need_more_evidence": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_126_operator_action_capture_allowed": "FALSE", "operator_review_action_packet_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_125_NEXT_STAGE_GATE_001", "v20_124_gate_consumed": "FALSE", "v20_125_operator_review_action_packet_allowed_by_v124": "FALSE", "selected_repair_scenario_id": "", "operator_review_action_packet_created": "TRUE", "every_remaining_pending_decision_has_action_packet": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_126_operator_action_capture_allowed": "FALSE", "next_recommended_action": "V20.125_OPERATOR_REVIEW_ACTION_PACKET_REPAIR", "blocking_reason": blocking, "operator_review_action_packet_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_124_GATE_CONSUMED=FALSE")
    print("V20_126_OPERATOR_ACTION_CAPTURE_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def action_consequence(action: str) -> str:
    if action == "ACCEPT_WITH_LIMITATION":
        return "Would require explicit valid operator acceptance before any later promotion-readiness path; V20.125 does not accept it."
    if action == "REJECT_AND_KEEP_BLOCKED":
        return "Keeps the blocker unresolved and prevents promotion readiness."
    return "Keeps decision pending and requests additional evidence before acceptance."


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    updated_rows = read_csv(IN_UPDATED)
    rationale_rows = read_csv(IN_RATIONALE)
    remaining_rows = read_csv(IN_REMAINING)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    closure_rows = read_csv(IN_V123_CLOSURE)
    plan_rows = read_csv(IN_V122_PLAN)
    required_rows = read_csv(IN_V119_REQUIRED)
    v118_remaining_rows = read_csv(IN_V118_REMAINING)
    if not all([decision_rows, updated_rows, rationale_rows, remaining_rows, safety_input_rows, gate_rows, closure_rows, plan_rows, required_rows, v118_remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v124_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_124_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_125_operator_review_action_packet_allowed"))
    v124_status = clean(gate_in.get("operator_decision_update_status")) or clean(decision_in.get("operator_decision_update_status"))
    v124_status_allowed = v124_status == V124_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    updated_by_record = {clean(row.get("source_operator_decision_record_id")): row for row in updated_rows}
    closure_by_category = {clean(row.get("blocker_category")): row for row in closure_rows}
    plan_by_record = {clean(row.get("source_operator_decision_record_id")): row for row in plan_rows}
    required_by_category = {clean(row.get("blocker_category")): row for row in required_rows}
    packet_rows = []
    options_rows = []
    evidence_rows = []
    for i, remaining in enumerate(remaining_rows, start=1):
        record_id = clean(remaining.get("source_operator_decision_record_id"))
        category = clean(remaining.get("blocker_category"))
        updated = updated_by_record.get(record_id, {})
        closure = closure_by_category.get(category, {})
        plan = plan_by_record.get(record_id, {})
        required = required_by_category.get(category, {})
        related_files = ";".join([
            "outputs/v20/consolidation/V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv",
            "outputs/v20/consolidation/V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv",
            "outputs/v20/consolidation/V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv",
            "outputs/v20/consolidation/V20_118_REMAINING_BLOCKER_AUDIT.csv",
        ])
        evidence_status = clean(closure.get("gap_closure_status")) or clean(updated.get("gap_closure_status")) or "PARTIALLY_CLOSED_NEEDS_OPERATOR_REVIEW"
        pending_reason = clean(remaining.get("remaining_review_reason")) or "Decision remains pending until explicit valid human acceptance is supplied."
        packet_id = f"V20_125_OPERATOR_ACTION_PACKET_{i:03d}"
        packet_rows.append({
            "action_packet_id": packet_id,
            "selected_repair_scenario_id": selected_id,
            "source_remaining_review_id": clean(remaining.get("remaining_review_id")),
            "source_operator_decision_record_id": record_id,
            "blocker_category": category,
            "pending_reason": pending_reason,
            "evidence_status": evidence_status,
            "related_evidence_files": related_files,
            "available_operator_actions": ";".join(ACTION_OPTIONS),
            "recommended_conservative_default": DEFAULT_ACTION,
            "accept_with_limitation_consequence": action_consequence("ACCEPT_WITH_LIMITATION"),
            "reject_and_keep_blocked_consequence": action_consequence("REJECT_AND_KEEP_BLOCKED"),
            "need_more_evidence_consequence": action_consequence("NEED_MORE_EVIDENCE"),
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        for action in ACTION_OPTIONS:
            options_rows.append({
                "action_option_audit_id": f"V20_125_OPERATOR_ACTION_OPTIONS_AUDIT_{len(options_rows)+1:03d}",
                "selected_repair_scenario_id": selected_id,
                "source_action_packet_id": packet_id,
                "blocker_category": category,
                "operator_action": action,
                "action_available": "TRUE",
                "action_consequence": action_consequence(action),
                "recommended_default": tf(action == DEFAULT_ACTION),
                "promotion_ready": "FALSE",
                **COMMON,
            })
        evidence_rows.append({
            "evidence_summary_id": f"V20_125_OPERATOR_ACTION_EVIDENCE_SUMMARY_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_action_packet_id": packet_id,
            "blocker_category": category,
            "evidence_status": evidence_status,
            "related_evidence_files": related_files,
            "evidence_summary": f"{clean(required.get('required_operator_decision')) or 'Operator decision required.'} Missing evidence: {clean(plan.get('missing_evidence')) or 'explicit valid human acceptance evidence'}.",
            "operator_review_required": "TRUE",
            "promotion_ready": "FALSE",
            **COMMON,
        })

    remaining_pending_count = sum(1 for row in updated_rows if clean(row.get("updated_decision_status")) == "PENDING_OPERATOR_DECISION")
    packet_record_ids = {row["source_operator_decision_record_id"] for row in packet_rows}
    remaining_record_ids = {clean(row.get("source_operator_decision_record_id")) for row in remaining_rows}
    every_remaining_has_packet = bool(remaining_rows) and len(packet_rows) == len(remaining_rows) and packet_record_ids == remaining_record_ids
    required_options = set(ACTION_OPTIONS)
    all_include_options = all(set(clean(row.get("available_operator_actions")).split(";")) == required_options for row in packet_rows)
    all_default_more_evidence = all(clean(row.get("recommended_conservative_default")) == DEFAULT_ACTION for row in packet_rows)
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in updated_rows + packet_rows)

    counts = prohibited_counts([decision_rows, updated_rows, rationale_rows, remaining_rows, safety_input_rows, gate_rows, closure_rows, plan_rows, required_rows, v118_remaining_rows, packet_rows, options_rows, evidence_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)

    base_ok = all([v124_gate_consumed, allowed, v124_status_allowed, selected_matches, every_remaining_has_packet, bool(options_rows), bool(evidence_rows), all_include_options, all_default_more_evidence, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "operator_review_action_packet_requirements_not_met"

    decision = {"decision_check_id": "V20_125_OPERATOR_REVIEW_ACTION_PACKET_DECISION_001", "v20_124_gate_consumed": tf(v124_gate_consumed), "v20_125_operator_review_action_packet_allowed_by_v124": tf(allowed), "v20_124_final_status": v124_status, "v20_124_status_allowed": tf(v124_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_124": tf(selected_matches), "remaining_pending_decision_count": str(remaining_pending_count), "action_packet_row_count": str(len(packet_rows)), "every_remaining_pending_decision_has_action_packet": tf(every_remaining_has_packet), "action_options_audit_row_count": str(len(options_rows)), "evidence_summary_row_count": str(len(evidence_rows)), "all_packet_rows_include_required_options": tf(all_include_options), "all_packet_rows_default_need_more_evidence": tf(all_default_more_evidence), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_126_operator_action_capture_allowed": tf(next_allowed), "operator_review_action_packet_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_125_NEXT_STAGE_GATE_001", "v20_124_gate_consumed": tf(v124_gate_consumed), "v20_125_operator_review_action_packet_allowed_by_v124": tf(allowed), "selected_repair_scenario_id": selected_id, "operator_review_action_packet_created": "TRUE", "every_remaining_pending_decision_has_action_packet": tf(every_remaining_has_packet), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_126_operator_action_capture_allowed": tf(next_allowed), "next_recommended_action": "V20.126_OPERATOR_ACTION_CAPTURE" if next_allowed else "V20.125_OPERATOR_REVIEW_ACTION_PACKET_REPAIR", "blocking_reason": blocking, "operator_review_action_packet_status": final_status, **COMMON}

    write_all([decision], packet_rows, options_rows, evidence_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_124_GATE_CONSUMED={tf(v124_gate_consumed)}")
    print(f"V20_125_OPERATOR_REVIEW_ACTION_PACKET_ALLOWED_BY_V124={tf(allowed)}")
    print(f"V20_124_FINAL_STATUS={v124_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_124={tf(selected_matches)}")
    print(f"REMAINING_PENDING_DECISION_COUNT={remaining_pending_count}")
    print(f"ACTION_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"EVERY_REMAINING_PENDING_DECISION_HAS_ACTION_PACKET={tf(every_remaining_has_packet)}")
    print(f"ACTION_OPTIONS_AUDIT_ROW_COUNT={len(options_rows)}")
    print(f"EVIDENCE_SUMMARY_ROW_COUNT={len(evidence_rows)}")
    print(f"ALL_PACKET_ROWS_INCLUDE_REQUIRED_OPTIONS={tf(all_include_options)}")
    print(f"ALL_PACKET_ROWS_DEFAULT_NEED_MORE_EVIDENCE={tf(all_default_more_evidence)}")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_126_OPERATOR_ACTION_CAPTURE_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
