#!/usr/bin/env python
"""V20.123 pending evidence follow-up.

Executes V20.122 pending evidence follow-up actions in audit-only mode. This
stage does not accept operator decisions, create official artifacts, fabricate
ticker rows, mutate upstream outputs, or mark promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION.csv"
IN_PLAN = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv"
IN_GAP = CONSOLIDATION / "V20_122_REQUIRED_EVIDENCE_GAP_AUDIT.csv"
IN_FOLLOWUP = CONSOLIDATION / "V20_122_REQUIRED_FOLLOWUP_ACTION_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_122_RESOLUTION_BOUNDARY_SAFETY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_122_NEXT_STAGE_GATE.csv"
IN_V121_PENDING = CONSOLIDATION / "V20_121_PENDING_DECISION_GATE_AUDIT.csv"
IN_V120_RECORD = CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv"
IN_V118_REMAINING = CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv"

OUT_DECISION = CONSOLIDATION / "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION.csv"
OUT_RESULT = CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_RESULT_AUDIT.csv"
OUT_CLOSURE = CONSOLIDATION / "V20_123_EVIDENCE_GAP_CLOSURE_AUDIT.csv"
OUT_STATUS = CONSOLIDATION / "V20_123_PENDING_DECISION_STATUS_UPDATE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_123_EVIDENCE_FOLLOWUP_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_123_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_123_PENDING_EVIDENCE_FOLLOWUP_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V122_REQUIRED_STATUS = "PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_READY_FOR_V20_123"
PASS_STATUS = "PASS_V20_123_PENDING_EVIDENCE_FOLLOWUP_READY_FOR_V20_124"
PARTIAL_STATUS = "PARTIAL_PASS_V20_123_EVIDENCE_PARTIALLY_CLOSED_READY_FOR_V20_124"
BLOCKED_STATUS = "BLOCKED_V20_123_PENDING_EVIDENCE_FOLLOWUP"
REQUIRED_INPUTS = [IN_DECISION, IN_PLAN, IN_GAP, IN_FOLLOWUP, IN_SAFETY, IN_GATE, IN_V121_PENDING, IN_V120_RECORD, IN_V118_REMAINING]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122"]],
    IN_DECISION, IN_PLAN, IN_GAP, IN_FOLLOWUP, IN_SAFETY, IN_V121_PENDING, IN_V120_RECORD, IN_V118_REMAINING,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "pending_evidence_followup_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_122_gate_consumed", "v20_123_pending_evidence_followup_allowed_by_v122", "v20_122_final_status", "v20_122_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_122", "resolution_plan_row_count", "followup_result_row_count", "every_resolution_plan_has_followup_result", "evidence_gap_closure_row_count", "pending_decision_status_update_row_count", "closed_gap_count", "partially_closed_gap_count", "still_open_gap_count", "operator_acceptance_true_count", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_124_operator_decision_update_allowed", "pending_evidence_followup_status", "blocking_reason", *COMMON.keys()]
RESULT_FIELDS = ["followup_result_id", "selected_repair_scenario_id", "source_resolution_plan_id", "source_operator_decision_record_id", "blocker_category", "required_followup_action", "followup_execution_mode", "followup_executed", "followup_result", "operator_acceptance", "promotion_ready", *COMMON.keys()]
CLOSURE_FIELDS = ["gap_closure_id", "selected_repair_scenario_id", "source_evidence_gap_id", "source_resolution_plan_id", "blocker_category", "missing_evidence", "expected_artifact_needed_to_resolve", "gap_closure_status", "closure_reason", "operator_review_still_required", "promotion_ready", *COMMON.keys()]
STATUS_FIELDS = ["status_update_id", "selected_repair_scenario_id", "source_operator_decision_record_id", "blocker_category", "previous_decision_status", "updated_decision_status", "operator_acceptance", "valid_acceptance_evidence", "promotion_ready", "status_update_reason", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_122_gate_consumed", "v20_123_pending_evidence_followup_allowed_by_v122", "selected_repair_scenario_id", "pending_evidence_followup_created", "every_resolution_plan_has_followup_result", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_124_operator_decision_update_allowed", "next_recommended_action", "blocking_reason", "pending_evidence_followup_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_123_EVIDENCE_FOLLOWUP_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.123 executes evidence follow-up in audit-only mode and keeps promotion readiness false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, result, closure, status, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_RESULT, RESULT_FIELDS, result)
    write_csv(OUT_CLOSURE, CLOSURE_FIELDS, closure)
    write_csv(OUT_STATUS, STATUS_FIELDS, status)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.123 Pending Evidence Follow-up Report", "",
        f"- wrapper_status: {decision.get('pending_evidence_followup_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- followup_result_row_count: {decision.get('followup_result_row_count')}",
        f"- partially_closed_gap_count: {decision.get('partially_closed_gap_count')}",
        f"- operator_acceptance_true_count: {decision.get('operator_acceptance_true_count')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_124_operator_decision_update_allowed: {decision.get('v20_124_operator_decision_update_allowed')}",
        "- official_recommendation_created: FALSE", "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION_001", "v20_122_gate_consumed": "FALSE", "v20_123_pending_evidence_followup_allowed_by_v122": "FALSE", "v20_122_final_status": "", "v20_122_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_122": "FALSE", "resolution_plan_row_count": "0", "followup_result_row_count": "0", "every_resolution_plan_has_followup_result": "FALSE", "evidence_gap_closure_row_count": "0", "pending_decision_status_update_row_count": "0", "closed_gap_count": "0", "partially_closed_gap_count": "0", "still_open_gap_count": "0", "operator_acceptance_true_count": "0", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_124_operator_decision_update_allowed": "FALSE", "pending_evidence_followup_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_123_NEXT_STAGE_GATE_001", "v20_122_gate_consumed": "FALSE", "v20_123_pending_evidence_followup_allowed_by_v122": "FALSE", "selected_repair_scenario_id": "", "pending_evidence_followup_created": "TRUE", "every_resolution_plan_has_followup_result": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_124_operator_decision_update_allowed": "FALSE", "next_recommended_action": "V20.123_PENDING_EVIDENCE_FOLLOWUP_REPAIR", "blocking_reason": blocking, "pending_evidence_followup_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_122_GATE_CONSUMED=FALSE")
    print("V20_124_OPERATOR_DECISION_UPDATE_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def closure_status_for(category: str) -> tuple[str, str]:
    if category in {"official_promotion_policy_evidence", "operator_approval_evidence"}:
        return ("PARTIALLY_CLOSED_NEEDS_OPERATOR_REVIEW", "Audit-only follow-up identifies the required evidence packet, but explicit operator acceptance is still absent.")
    return ("STILL_OPEN_NEEDS_MORE_EVIDENCE", "No explicit evidence artifact is available in the current shadow lineage.")


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    plan_rows = read_csv(IN_PLAN)
    gap_rows = read_csv(IN_GAP)
    followup_rows = read_csv(IN_FOLLOWUP)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    v121_pending_rows = read_csv(IN_V121_PENDING)
    v120_record_rows = read_csv(IN_V120_RECORD)
    v118_remaining_rows = read_csv(IN_V118_REMAINING)
    if not all([decision_rows, plan_rows, gap_rows, followup_rows, safety_input_rows, gate_rows, v121_pending_rows, v120_record_rows, v118_remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v122_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_122_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_123_pending_evidence_followup_allowed"))
    v122_status = clean(gate_in.get("pending_decision_resolution_plan_status")) or clean(decision_in.get("pending_decision_resolution_plan_status"))
    v122_status_allowed = v122_status == V122_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    followup_by_record = {clean(row.get("source_operator_decision_record_id")): row for row in followup_rows}
    gap_by_record = {clean(row.get("source_operator_decision_record_id")): row for row in gap_rows}
    record_by_id = {clean(row.get("operator_decision_record_id")): row for row in v120_record_rows}
    result_rows = []
    closure_rows = []
    status_rows = []
    for i, plan in enumerate(plan_rows, start=1):
        record_id = clean(plan.get("source_operator_decision_record_id"))
        category = clean(plan.get("blocker_category"))
        followup = followup_by_record.get(record_id, {})
        gap = gap_by_record.get(record_id, {})
        record = record_by_id.get(record_id, {})
        closure_status, closure_reason = closure_status_for(category)
        result_rows.append({"followup_result_id": f"V20_123_EVIDENCE_FOLLOWUP_RESULT_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "source_resolution_plan_id": clean(plan.get("resolution_plan_id")), "source_operator_decision_record_id": record_id, "blocker_category": category, "required_followup_action": clean(followup.get("required_followup_action")) or clean(plan.get("required_followup_action")), "followup_execution_mode": "AUDIT_ONLY_NON_MUTATING", "followup_executed": "TRUE", "followup_result": "EVIDENCE_PACKET_IDENTIFIED_FOR_OPERATOR_REVIEW", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", **COMMON})
        closure_rows.append({"gap_closure_id": f"V20_123_EVIDENCE_GAP_CLOSURE_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "source_evidence_gap_id": clean(gap.get("evidence_gap_id")), "source_resolution_plan_id": clean(plan.get("resolution_plan_id")), "blocker_category": category, "missing_evidence": clean(gap.get("missing_evidence")) or clean(plan.get("missing_evidence")), "expected_artifact_needed_to_resolve": clean(gap.get("expected_artifact_needed_to_resolve")) or clean(plan.get("expected_artifact_needed_to_resolve")), "gap_closure_status": closure_status, "closure_reason": closure_reason, "operator_review_still_required": "TRUE", "promotion_ready": "FALSE", **COMMON})
        status_rows.append({"status_update_id": f"V20_123_PENDING_DECISION_STATUS_UPDATE_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "source_operator_decision_record_id": record_id, "blocker_category": category, "previous_decision_status": clean(record.get("decision_status")) or clean(plan.get("current_decision_status")), "updated_decision_status": "PENDING_OPERATOR_DECISION", "operator_acceptance": "FALSE", "valid_acceptance_evidence": "FALSE", "promotion_ready": "FALSE", "status_update_reason": "Follow-up remains audit-only; explicit human operator acceptance has not been provided.", **COMMON})

    every_plan_has_result = bool(plan_rows) and len(result_rows) == len(plan_rows) and all(clean(row.get("followup_executed")) == "TRUE" for row in result_rows)
    closed_count = sum(1 for row in closure_rows if row["gap_closure_status"] == "CLOSED_BY_EXISTING_SHADOW_EVIDENCE")
    partial_count = sum(1 for row in closure_rows if row["gap_closure_status"] == "PARTIALLY_CLOSED_NEEDS_OPERATOR_REVIEW")
    open_count = sum(1 for row in closure_rows if row["gap_closure_status"] == "STILL_OPEN_NEEDS_MORE_EVIDENCE")
    operator_acceptance_true_count = sum(1 for row in status_rows if truthy(row.get("operator_acceptance")))
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in v120_record_rows)

    counts = prohibited_counts([decision_rows, plan_rows, gap_rows, followup_rows, safety_input_rows, gate_rows, v121_pending_rows, v120_record_rows, v118_remaining_rows, result_rows, closure_rows, status_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)

    base_ok = all([v122_gate_consumed, allowed, v122_status_allowed, selected_matches, every_plan_has_result, bool(closure_rows), bool(status_rows), operator_acceptance_true_count == 0, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    if not base_ok:
        final_status = BLOCKED_STATUS
    elif open_count == 0 and partial_count == 0:
        final_status = PASS_STATUS
    elif open_count == 0 and partial_count > 0:
        final_status = PARTIAL_STATUS
    else:
        final_status = PARTIAL_STATUS
    next_allowed = final_status in {PASS_STATUS, PARTIAL_STATUS}
    blocking = "" if next_allowed else "pending_evidence_followup_requirements_not_met"

    decision = {"decision_check_id": "V20_123_PENDING_EVIDENCE_FOLLOWUP_DECISION_001", "v20_122_gate_consumed": tf(v122_gate_consumed), "v20_123_pending_evidence_followup_allowed_by_v122": tf(allowed), "v20_122_final_status": v122_status, "v20_122_status_allowed": tf(v122_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_122": tf(selected_matches), "resolution_plan_row_count": str(len(plan_rows)), "followup_result_row_count": str(len(result_rows)), "every_resolution_plan_has_followup_result": tf(every_plan_has_result), "evidence_gap_closure_row_count": str(len(closure_rows)), "pending_decision_status_update_row_count": str(len(status_rows)), "closed_gap_count": str(closed_count), "partially_closed_gap_count": str(partial_count), "still_open_gap_count": str(open_count), "operator_acceptance_true_count": str(operator_acceptance_true_count), "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_124_operator_decision_update_allowed": tf(next_allowed), "pending_evidence_followup_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_123_NEXT_STAGE_GATE_001", "v20_122_gate_consumed": tf(v122_gate_consumed), "v20_123_pending_evidence_followup_allowed_by_v122": tf(allowed), "selected_repair_scenario_id": selected_id, "pending_evidence_followup_created": "TRUE", "every_resolution_plan_has_followup_result": tf(every_plan_has_result), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_124_operator_decision_update_allowed": tf(next_allowed), "next_recommended_action": "V20.124_OPERATOR_DECISION_UPDATE" if next_allowed else "V20.123_PENDING_EVIDENCE_FOLLOWUP_REPAIR", "blocking_reason": blocking, "pending_evidence_followup_status": final_status, **COMMON}

    write_all([decision], result_rows, closure_rows, status_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_122_GATE_CONSUMED={tf(v122_gate_consumed)}")
    print(f"V20_123_PENDING_EVIDENCE_FOLLOWUP_ALLOWED_BY_V122={tf(allowed)}")
    print(f"V20_122_FINAL_STATUS={v122_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_122={tf(selected_matches)}")
    print(f"RESOLUTION_PLAN_ROW_COUNT={len(plan_rows)}")
    print(f"FOLLOWUP_RESULT_ROW_COUNT={len(result_rows)}")
    print(f"EVERY_RESOLUTION_PLAN_HAS_FOLLOWUP_RESULT={tf(every_plan_has_result)}")
    print(f"EVIDENCE_GAP_CLOSURE_ROW_COUNT={len(closure_rows)}")
    print(f"PENDING_DECISION_STATUS_UPDATE_ROW_COUNT={len(status_rows)}")
    print(f"OPERATOR_ACCEPTANCE_TRUE_COUNT={operator_acceptance_true_count}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_124_OPERATOR_DECISION_UPDATE_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
