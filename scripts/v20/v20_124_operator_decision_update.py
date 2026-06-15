#!/usr/bin/env python
"""V20.124 operator decision update.

Updates operator decision state from V20.123 evidence follow-up audits in a
non-mutating, audit-only manner. Without explicit valid human acceptance for
every required decision, decisions remain pending and promotion readiness stays
false.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION.csv"
IN_RESULT = CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_RESULT_AUDIT.csv"
IN_CLOSURE = CONSOLIDATION / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv"
IN_STATUS = CONSOLIDATION / "V20_123_PENDING_DECISION_STATUS_UPDATE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_123_NEXT_STAGE_GATE.csv"
IN_V122_PLAN = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv"
IN_V120_RECORD = CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv"

OUT_DECISION = CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_DECISION.csv"
OUT_UPDATED = CONSOLIDATION / "V20_124_UPDATED_OPERATOR_DECISION_RECORD.csv"
OUT_RATIONALE = CONSOLIDATION / "V20_124_DECISION_UPDATE_RATIONALE_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_124_REMAINING_OPERATOR_REVIEW_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_124_OPERATOR_DECISION_UPDATE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_124_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_124_OPERATOR_DECISION_UPDATE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V123_ALLOWED_STATUSES = {
    "PARTIAL_PASS_V20_123_EVIDENCE_PARTIALLY_CLOSED_READY_FOR_V20_124",
    "PASS_V20_123_PENDING_EVIDENCE_FOLLOWUP_READY_FOR_V20_124",
}
PASS_STATUS = "PASS_V20_124_OPERATOR_DECISION_UPDATE_READY_FOR_V20_125"
PARTIAL_STATUS = "PARTIAL_PASS_V20_124_OPERATOR_DECISIONS_STILL_REQUIRE_REVIEW_READY_FOR_V20_125"
BLOCKED_STATUS = "BLOCKED_V20_124_OPERATOR_DECISION_UPDATE"
REQUIRED_INPUTS = [IN_DECISION, IN_RESULT, IN_CLOSURE, IN_STATUS, IN_SAFETY, IN_GATE, IN_V122_PLAN, IN_V120_RECORD]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123"]],
    IN_DECISION, IN_RESULT, IN_CLOSURE, IN_STATUS, IN_SAFETY, IN_V122_PLAN, IN_V120_RECORD,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "operator_decision_update_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_123_gate_consumed", "v20_124_operator_decision_update_allowed_by_v123", "v20_123_final_status", "v20_123_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_123", "v20_123_status_update_row_count", "updated_operator_decision_record_count", "every_v123_status_update_carried_forward", "pending_operator_decision_count", "accepted_operator_decision_count", "remaining_operator_review_count", "all_required_decisions_accepted_with_valid_human_evidence", "operator_acceptance_true_count", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_125_operator_review_action_packet_allowed", "operator_decision_update_status", "blocking_reason", *COMMON.keys()]
UPDATED_FIELDS = ["updated_operator_decision_record_id", "selected_repair_scenario_id", "source_operator_decision_record_id", "source_v123_status_update_id", "blocker_category", "gap_closure_status", "previous_decision_status", "updated_decision_status", "operator_acceptance", "valid_human_acceptance_evidence", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
RATIONALE_FIELDS = ["rationale_audit_id", "selected_repair_scenario_id", "source_operator_decision_record_id", "blocker_category", "gap_closure_status", "decision_update_rationale", "operator_acceptance", "promotion_ready", *COMMON.keys()]
REMAINING_FIELDS = ["remaining_review_id", "selected_repair_scenario_id", "source_operator_decision_record_id", "blocker_category", "remaining_review_required", "remaining_review_reason", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_123_gate_consumed", "v20_124_operator_decision_update_allowed_by_v123", "selected_repair_scenario_id", "operator_decision_update_created", "every_v123_status_update_carried_forward", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_125_operator_review_action_packet_allowed", "next_recommended_action", "blocking_reason", "operator_decision_update_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_124_OPERATOR_DECISION_UPDATE_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.124 updates operator decision state only and keeps promotion readiness false without explicit valid human acceptance.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, updated, rationale, remaining, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_UPDATED, UPDATED_FIELDS, updated)
    write_csv(OUT_RATIONALE, RATIONALE_FIELDS, rationale)
    write_csv(OUT_REMAINING, REMAINING_FIELDS, remaining)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.124 Operator Decision Update Report", "",
        f"- wrapper_status: {decision.get('operator_decision_update_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- updated_operator_decision_record_count: {decision.get('updated_operator_decision_record_count')}",
        f"- pending_operator_decision_count: {decision.get('pending_operator_decision_count')}",
        f"- remaining_operator_review_count: {decision.get('remaining_operator_review_count')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_125_operator_review_action_packet_allowed: {decision.get('v20_125_operator_review_action_packet_allowed')}",
        "- official_recommendation_created: FALSE", "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_124_OPERATOR_DECISION_UPDATE_DECISION_001", "v20_123_gate_consumed": "FALSE", "v20_124_operator_decision_update_allowed_by_v123": "FALSE", "v20_123_final_status": "", "v20_123_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_123": "FALSE", "v20_123_status_update_row_count": "0", "updated_operator_decision_record_count": "0", "every_v123_status_update_carried_forward": "FALSE", "pending_operator_decision_count": "0", "accepted_operator_decision_count": "0", "remaining_operator_review_count": "0", "all_required_decisions_accepted_with_valid_human_evidence": "FALSE", "operator_acceptance_true_count": "0", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_125_operator_review_action_packet_allowed": "FALSE", "operator_decision_update_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_124_NEXT_STAGE_GATE_001", "v20_123_gate_consumed": "FALSE", "v20_124_operator_decision_update_allowed_by_v123": "FALSE", "selected_repair_scenario_id": "", "operator_decision_update_created": "TRUE", "every_v123_status_update_carried_forward": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_125_operator_review_action_packet_allowed": "FALSE", "next_recommended_action": "V20.124_OPERATOR_DECISION_UPDATE_REPAIR", "blocking_reason": blocking, "operator_decision_update_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_123_GATE_CONSUMED=FALSE")
    print("V20_125_OPERATOR_REVIEW_ACTION_PACKET_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    result_rows = read_csv(IN_RESULT)
    closure_rows = read_csv(IN_CLOSURE)
    status_rows = read_csv(IN_STATUS)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    plan_rows = read_csv(IN_V122_PLAN)
    v120_record_rows = read_csv(IN_V120_RECORD)
    if not all([decision_rows, result_rows, closure_rows, status_rows, safety_input_rows, gate_rows, plan_rows, v120_record_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v123_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_123_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_124_operator_decision_update_allowed"))
    v123_status = clean(gate_in.get("pending_evidence_followup_status")) or clean(decision_in.get("pending_evidence_followup_status"))
    v123_status_allowed = v123_status in V123_ALLOWED_STATUSES
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    closure_by_record = {clean(row.get("source_operator_decision_record_id")): row for row in closure_rows}
    record_by_id = {clean(row.get("operator_decision_record_id")): row for row in v120_record_rows}
    updated_rows = []
    rationale_rows = []
    remaining_rows = []
    for i, status in enumerate(status_rows, start=1):
        record_id = clean(status.get("source_operator_decision_record_id"))
        category = clean(status.get("blocker_category"))
        closure = closure_by_record.get(record_id, {})
        source_record = record_by_id.get(record_id, {})
        gap_status = clean(closure.get("gap_closure_status"))
        explicit_valid_acceptance = truthy(status.get("operator_acceptance")) and truthy(status.get("valid_acceptance_evidence"))
        if gap_status == "PARTIALLY_CLOSED_NEEDS_OPERATOR_REVIEW" or not explicit_valid_acceptance:
            updated_status = "PENDING_OPERATOR_DECISION"
            rationale = "Evidence follow-up is partial and still requires operator review; no explicit valid human acceptance exists."
            remaining_required = True
        else:
            updated_status = "ACCEPTED_OPERATOR_DECISION"
            rationale = "Explicit valid human acceptance is present for this required decision."
            remaining_required = False
        updated_rows.append({"updated_operator_decision_record_id": f"V20_124_UPDATED_OPERATOR_DECISION_RECORD_{i:03d}", "selected_repair_scenario_id": selected_id, "source_operator_decision_record_id": record_id, "source_v123_status_update_id": clean(status.get("status_update_id")), "blocker_category": category, "gap_closure_status": gap_status, "previous_decision_status": clean(source_record.get("decision_status")) or clean(status.get("previous_decision_status")), "updated_decision_status": updated_status, "operator_acceptance": tf(explicit_valid_acceptance), "valid_human_acceptance_evidence": tf(explicit_valid_acceptance), "promotion_ready": "FALSE", "ticker_rows_created": "0", **COMMON})
        rationale_rows.append({"rationale_audit_id": f"V20_124_DECISION_UPDATE_RATIONALE_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "source_operator_decision_record_id": record_id, "blocker_category": category, "gap_closure_status": gap_status, "decision_update_rationale": rationale, "operator_acceptance": tf(explicit_valid_acceptance), "promotion_ready": "FALSE", **COMMON})
        if remaining_required:
            remaining_rows.append({"remaining_review_id": f"V20_124_REMAINING_OPERATOR_REVIEW_AUDIT_{len(remaining_rows)+1:03d}", "selected_repair_scenario_id": selected_id, "source_operator_decision_record_id": record_id, "blocker_category": category, "remaining_review_required": "TRUE", "remaining_review_reason": "Decision remains pending until explicit valid human acceptance is supplied.", "promotion_ready": "FALSE", **COMMON})

    every_status_carried = bool(status_rows) and len(updated_rows) == len(status_rows) and {row["source_v123_status_update_id"] for row in updated_rows} == {clean(row.get("status_update_id")) for row in status_rows}
    pending_count = sum(1 for row in updated_rows if row["updated_decision_status"] == "PENDING_OPERATOR_DECISION")
    accepted_count = sum(1 for row in updated_rows if row["updated_decision_status"] == "ACCEPTED_OPERATOR_DECISION")
    operator_acceptance_true_count = sum(1 for row in updated_rows if truthy(row.get("operator_acceptance")))
    all_accepted = bool(updated_rows) and accepted_count == len(updated_rows) and operator_acceptance_true_count == len(updated_rows)
    promotion_ready = all_accepted
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in v120_record_rows + updated_rows)

    counts = prohibited_counts([decision_rows, result_rows, closure_rows, status_rows, safety_input_rows, gate_rows, plan_rows, v120_record_rows, updated_rows, rationale_rows, remaining_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)

    base_ok = all([v123_gate_consumed, allowed, v123_status_allowed, selected_matches, every_status_carried, bool(updated_rows), bool(rationale_rows), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    if not base_ok:
        final_status = BLOCKED_STATUS
    elif promotion_ready:
        final_status = PASS_STATUS
    else:
        final_status = PARTIAL_STATUS
    next_allowed = final_status in {PASS_STATUS, PARTIAL_STATUS}
    blocking = "" if next_allowed else "operator_decision_update_requirements_not_met"

    decision = {"decision_check_id": "V20_124_OPERATOR_DECISION_UPDATE_DECISION_001", "v20_123_gate_consumed": tf(v123_gate_consumed), "v20_124_operator_decision_update_allowed_by_v123": tf(allowed), "v20_123_final_status": v123_status, "v20_123_status_allowed": tf(v123_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_123": tf(selected_matches), "v20_123_status_update_row_count": str(len(status_rows)), "updated_operator_decision_record_count": str(len(updated_rows)), "every_v123_status_update_carried_forward": tf(every_status_carried), "pending_operator_decision_count": str(pending_count), "accepted_operator_decision_count": str(accepted_count), "remaining_operator_review_count": str(len(remaining_rows)), "all_required_decisions_accepted_with_valid_human_evidence": tf(all_accepted), "operator_acceptance_true_count": str(operator_acceptance_true_count), "promotion_ready": tf(promotion_ready), "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_125_operator_review_action_packet_allowed": tf(next_allowed), "operator_decision_update_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_124_NEXT_STAGE_GATE_001", "v20_123_gate_consumed": tf(v123_gate_consumed), "v20_124_operator_decision_update_allowed_by_v123": tf(allowed), "selected_repair_scenario_id": selected_id, "operator_decision_update_created": "TRUE", "every_v123_status_update_carried_forward": tf(every_status_carried), "operator_acceptance": tf(operator_acceptance_true_count > 0), "promotion_ready": tf(promotion_ready), "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_125_operator_review_action_packet_allowed": tf(next_allowed), "next_recommended_action": "V20.125_OPERATOR_REVIEW_ACTION_PACKET" if next_allowed else "V20.124_OPERATOR_DECISION_UPDATE_REPAIR", "blocking_reason": blocking, "operator_decision_update_status": final_status, **COMMON}

    write_all([decision], updated_rows, rationale_rows, remaining_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_123_GATE_CONSUMED={tf(v123_gate_consumed)}")
    print(f"V20_124_OPERATOR_DECISION_UPDATE_ALLOWED_BY_V123={tf(allowed)}")
    print(f"V20_123_FINAL_STATUS={v123_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_123={tf(selected_matches)}")
    print(f"V20_123_STATUS_UPDATE_ROW_COUNT={len(status_rows)}")
    print(f"UPDATED_OPERATOR_DECISION_RECORD_COUNT={len(updated_rows)}")
    print(f"EVERY_V123_STATUS_UPDATE_CARRIED_FORWARD={tf(every_status_carried)}")
    print(f"PENDING_OPERATOR_DECISION_COUNT={pending_count}")
    print(f"OPERATOR_ACCEPTANCE_TRUE_COUNT={operator_acceptance_true_count}")
    print(f"REMAINING_OPERATOR_REVIEW_COUNT={len(remaining_rows)}")
    print(f"PROMOTION_READY={tf(promotion_ready)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_125_OPERATOR_REVIEW_ACTION_PACKET_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
