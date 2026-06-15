#!/usr/bin/env python
"""V20.139 third-round evidence plan.

Creates a planning-only third-round evidence plan for blockers whose V20.138
second-round operator decisions requested third-round evidence. This stage is
audit-only, non-mutating, and never marks evidence acceptance, operator
acceptance, or promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_DECISION.csv"
IN_RECORD = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv"
IN_VALIDATION = CONSOLIDATION / "V20_138_SECOND_ROUND_DECISION_VALIDATION_AUDIT.csv"
IN_CONSEQUENCE = CONSOLIDATION / "V20_138_SECOND_ROUND_DECISION_CONSEQUENCE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_138_NEXT_STAGE_GATE.csv"
IN_PACKET = CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv"
IN_COVERAGE = CONSOLIDATION / "V20_136_SECOND_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
IN_SECOND_RESULT = CONSOLIDATION / "V20_135_SECOND_ROUND_EVIDENCE_RESULT_AUDIT.csv"
IN_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"

OUT_DECISION = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PLAN_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv"
OUT_REQUIREMENT = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv"
OUT_PRIORITY = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PRIORITY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_139_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_139_THIRD_ROUND_EVIDENCE_PLAN_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V138_REQUIRED_STATUS = "PARTIAL_PASS_V20_138_SECOND_ROUND_DECISIONS_DEFAULT_THIRD_ROUND_READY_FOR_V20_139"
PASS_STATUS = "PASS_V20_139_THIRD_ROUND_EVIDENCE_PLAN_READY_FOR_V20_140"
BLOCKED_STATUS = "BLOCKED_V20_139_THIRD_ROUND_EVIDENCE_PLAN"

REQUIRED_INPUTS = [IN_DECISION, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_GATE, IN_PACKET, IN_COVERAGE, IN_SECOND_RESULT, IN_REMAINING]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131", "132", "133", "134", "135", "136", "137", "138"]],
    IN_DECISION, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_PACKET, IN_COVERAGE, IN_SECOND_RESULT, IN_REMAINING,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "third_round_evidence_plan_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_138_gate_consumed", "v20_139_third_round_evidence_plan_allowed_by_v138", "v20_138_final_status", "v20_138_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_138", "pending_third_round_evidence_count", "third_round_evidence_plan_row_count", "every_pending_third_round_evidence_has_plan_row", "third_round_evidence_requirement_audit_row_count", "third_round_evidence_priority_audit_row_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_140_third_round_evidence_dry_run_allowed", "third_round_evidence_plan_status", "blocking_reason", *COMMON.keys()]
PLAN_FIELDS = ["third_round_evidence_plan_id", "selected_repair_scenario_id", "source_second_round_operator_decision_record_id", "source_second_round_operator_review_packet_id", "source_second_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "source_second_round_evidence_result_audit_id", "source_operator_decision_record_id", "blocker_category", "prior_first_round_evidence_status", "prior_second_round_evidence_coverage_status", "second_round_operator_decision", "current_decision_status", "blocker_status", "third_round_evidence_requirement", "proposed_third_round_collection_action", "expected_closure_criterion", "priority", "explicit_human_review_remains_required", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
REQUIREMENT_FIELDS = ["third_round_evidence_requirement_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "source_second_round_operator_decision_record_id", "source_second_round_evidence_result_audit_id", "blocker_category", "second_round_operator_decision", "third_round_evidence_requirement", "requirement_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
PRIORITY_FIELDS = ["third_round_evidence_priority_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "blocker_category", "priority", "priority_rank", "priority_reason", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_138_gate_consumed", "v20_139_third_round_evidence_plan_allowed_by_v138", "selected_repair_scenario_id", "third_round_evidence_plan_created", "every_pending_third_round_evidence_has_plan_row", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_140_third_round_evidence_dry_run_allowed", "next_recommended_action", "blocking_reason", "third_round_evidence_plan_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_139_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.139 creates only third-round evidence plan artifacts and keeps all acceptance and promotion flags false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, plan, requirement, priority, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_REQUIREMENT, REQUIREMENT_FIELDS, requirement)
    write_csv(OUT_PRIORITY, PRIORITY_FIELDS, priority)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.139 Third-Round Evidence Plan Report", "",
        f"- wrapper_status: {decision.get('third_round_evidence_plan_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- pending_third_round_evidence_count: {decision.get('pending_third_round_evidence_count')}",
        f"- third_round_evidence_plan_row_count: {decision.get('third_round_evidence_plan_row_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_140_third_round_evidence_dry_run_allowed: {decision.get('v20_140_third_round_evidence_dry_run_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_139_THIRD_ROUND_EVIDENCE_PLAN_DECISION_001", "v20_138_gate_consumed": "FALSE", "v20_139_third_round_evidence_plan_allowed_by_v138": "FALSE", "v20_138_final_status": "", "v20_138_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_138": "FALSE", "pending_third_round_evidence_count": "0", "third_round_evidence_plan_row_count": "0", "every_pending_third_round_evidence_has_plan_row": "FALSE", "third_round_evidence_requirement_audit_row_count": "0", "third_round_evidence_priority_audit_row_count": "0", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_140_third_round_evidence_dry_run_allowed": "FALSE", "third_round_evidence_plan_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_139_NEXT_STAGE_GATE_001", "v20_138_gate_consumed": "FALSE", "v20_139_third_round_evidence_plan_allowed_by_v138": "FALSE", "selected_repair_scenario_id": "", "third_round_evidence_plan_created": "TRUE", "every_pending_third_round_evidence_has_plan_row": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_140_third_round_evidence_dry_run_allowed": "FALSE", "next_recommended_action": "V20.139_THIRD_ROUND_EVIDENCE_PLAN_REPAIR", "blocking_reason": blocking, "third_round_evidence_plan_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_138_GATE_CONSUMED=FALSE")
    print("V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def third_requirement(category: str) -> str:
    if category == "official_promotion_policy_evidence":
        return "THIRD_ROUND_OFFICIAL_PROMOTION_POLICY_EVIDENCE_WITH_EXPLICIT_HUMAN_REVIEW"
    if category == "operator_approval_evidence":
        return "THIRD_ROUND_OPERATOR_APPROVAL_EVIDENCE_WITH_EXPLICIT_HUMAN_REVIEW"
    return "THIRD_ROUND_BLOCKER_SPECIFIC_EVIDENCE_WITH_EXPLICIT_HUMAN_REVIEW"


def third_action(category: str) -> str:
    if category == "official_promotion_policy_evidence":
        return "Plan third-round collection of explicit policy-review evidence with acceptance traceability and no promotion artifact creation."
    if category == "operator_approval_evidence":
        return "Plan third-round collection of explicit operator approval evidence with human-review traceability and no trade artifact creation."
    return "Plan third-round blocker-specific evidence collection with explicit human review and no downstream mutation."


def build_plan_artifacts(selected_id: str, pending_rows: list[dict[str, str]], packet_rows: list[dict[str, str]], coverage_rows: list[dict[str, str]], result_rows: list[dict[str, str]], remaining_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    packet_by_id = {clean(row.get("second_round_operator_review_packet_id")): row for row in packet_rows}
    coverage_by_id = {clean(row.get("second_round_blocker_coverage_audit_id")): row for row in coverage_rows}
    result_by_id = {clean(row.get("second_round_evidence_result_audit_id")): row for row in result_rows}
    remaining_by_id = {clean(row.get("remaining_evidence_blocker_status_id")): row for row in remaining_rows}
    plans, reqs, priorities = [], [], []
    for i, record in enumerate(pending_rows, start=1):
        category = clean(record.get("blocker_category"))
        packet = packet_by_id.get(clean(record.get("source_second_round_operator_review_packet_id")), {})
        coverage = coverage_by_id.get(clean(record.get("source_second_round_blocker_coverage_audit_id")), {})
        result = result_by_id.get(clean(packet.get("source_second_round_evidence_result_audit_id")), {})
        remaining = remaining_by_id.get(clean(record.get("source_remaining_evidence_blocker_status_id")), {})
        plan_id = f"V20_139_THIRD_ROUND_EVIDENCE_PLAN_{i:03d}"
        requirement = third_requirement(category)
        plans.append({
            "third_round_evidence_plan_id": plan_id,
            "selected_repair_scenario_id": selected_id,
            "source_second_round_operator_decision_record_id": clean(record.get("second_round_operator_decision_record_id")),
            "source_second_round_operator_review_packet_id": clean(record.get("source_second_round_operator_review_packet_id")),
            "source_second_round_blocker_coverage_audit_id": clean(record.get("source_second_round_blocker_coverage_audit_id")),
            "source_remaining_evidence_blocker_status_id": clean(record.get("source_remaining_evidence_blocker_status_id")),
            "source_second_round_evidence_result_audit_id": clean(packet.get("source_second_round_evidence_result_audit_id")) or clean(coverage.get("source_second_round_evidence_result_audit_id")),
            "source_operator_decision_record_id": clean(record.get("source_operator_decision_record_id")),
            "blocker_category": category,
            "prior_first_round_evidence_status": clean(remaining.get("resolution_status")),
            "prior_second_round_evidence_coverage_status": clean(coverage.get("coverage_status")),
            "second_round_operator_decision": clean(record.get("second_round_operator_decision")),
            "current_decision_status": clean(record.get("decision_status")),
            "blocker_status": clean(record.get("blocker_status")),
            "third_round_evidence_requirement": requirement,
            "proposed_third_round_collection_action": third_action(category),
            "expected_closure_criterion": "A later stage records explicit valid human acceptance evidence while preserving audit-only boundaries and without creating promotion readiness.",
            "priority": "P1",
            "explicit_human_review_remains_required": "TRUE",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        reqs.append({
            "third_round_evidence_requirement_audit_id": f"V20_139_THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "source_second_round_operator_decision_record_id": clean(record.get("second_round_operator_decision_record_id")),
            "source_second_round_evidence_result_audit_id": clean(result.get("second_round_evidence_result_audit_id")),
            "blocker_category": category,
            "second_round_operator_decision": clean(record.get("second_round_operator_decision")),
            "third_round_evidence_requirement": requirement,
            "requirement_status": "PLANNED_FOR_THIRD_ROUND_DRY_RUN",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
        priorities.append({
            "third_round_evidence_priority_audit_id": f"V20_139_THIRD_ROUND_EVIDENCE_PRIORITY_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "blocker_category": category,
            "priority": "P1",
            "priority_rank": str(i),
            "priority_reason": "Required because V20.138 requested third-round evidence while blocker remains unresolved/pending.",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
    return plans, reqs, priorities


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
    coverage_rows = read_csv(IN_COVERAGE)
    result_rows = read_csv(IN_SECOND_RESULT)
    remaining_rows = read_csv(IN_REMAINING)
    if not all([decision_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_rows, coverage_rows, result_rows, remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v138_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_138_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_139_third_round_evidence_plan_allowed"))
    v138_status = clean(gate_in.get("second_round_operator_decision_capture_status")) or clean(decision_in.get("second_round_operator_decision_capture_status"))
    v138_status_allowed = v138_status == V138_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    pending_rows = [row for row in record_rows if clean(row.get("second_round_operator_decision")) == "REQUEST_THIRD_ROUND_EVIDENCE" and clean(row.get("decision_status")) == "PENDING_THIRD_ROUND_EVIDENCE"]
    plan_rows, requirement_rows, priority_rows = build_plan_artifacts(selected_id, pending_rows, packet_rows, coverage_rows, result_rows, remaining_rows)
    pending_ids = {clean(row.get("second_round_operator_decision_record_id")) for row in pending_rows}
    plan_ids = {clean(row.get("source_second_round_operator_decision_record_id")) for row in plan_rows}
    every_pending_has_plan = bool(pending_rows) and len(plan_rows) == len(pending_rows) and pending_ids == plan_ids
    plan_row_ids = {clean(row.get("third_round_evidence_plan_id")) for row in plan_rows}
    requirement_complete = bool(requirement_rows) and {clean(row.get("source_third_round_evidence_plan_id")) for row in requirement_rows} == plan_row_ids
    priority_complete = bool(priority_rows) and {clean(row.get("source_third_round_evidence_plan_id")) for row in priority_rows} == plan_row_ids
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in record_rows + packet_rows + plan_rows)
    counts = prohibited_counts([decision_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_rows, coverage_rows, result_rows, remaining_rows, plan_rows, requirement_rows, priority_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v138_gate_consumed, allowed, v138_status_allowed, selected_matches, every_pending_has_plan, requirement_complete, priority_complete, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "third_round_evidence_plan_requirements_not_met"

    decision = {"decision_check_id": "V20_139_THIRD_ROUND_EVIDENCE_PLAN_DECISION_001", "v20_138_gate_consumed": tf(v138_gate_consumed), "v20_139_third_round_evidence_plan_allowed_by_v138": tf(allowed), "v20_138_final_status": v138_status, "v20_138_status_allowed": tf(v138_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_138": tf(selected_matches), "pending_third_round_evidence_count": str(len(pending_rows)), "third_round_evidence_plan_row_count": str(len(plan_rows)), "every_pending_third_round_evidence_has_plan_row": tf(every_pending_has_plan), "third_round_evidence_requirement_audit_row_count": str(len(requirement_rows)), "third_round_evidence_priority_audit_row_count": str(len(priority_rows)), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_140_third_round_evidence_dry_run_allowed": tf(next_allowed), "third_round_evidence_plan_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_139_NEXT_STAGE_GATE_001", "v20_138_gate_consumed": tf(v138_gate_consumed), "v20_139_third_round_evidence_plan_allowed_by_v138": tf(allowed), "selected_repair_scenario_id": selected_id, "third_round_evidence_plan_created": "TRUE", "every_pending_third_round_evidence_has_plan_row": tf(every_pending_has_plan), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_140_third_round_evidence_dry_run_allowed": tf(next_allowed), "next_recommended_action": "V20.140_THIRD_ROUND_EVIDENCE_DRY_RUN" if next_allowed else "V20.139_THIRD_ROUND_EVIDENCE_PLAN_REPAIR", "blocking_reason": blocking, "third_round_evidence_plan_status": final_status, **COMMON}
    write_all([decision], plan_rows, requirement_rows, priority_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_138_GATE_CONSUMED={tf(v138_gate_consumed)}")
    print(f"V20_139_THIRD_ROUND_EVIDENCE_PLAN_ALLOWED_BY_V138={tf(allowed)}")
    print(f"V20_138_FINAL_STATUS={v138_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_138={tf(selected_matches)}")
    print(f"PENDING_THIRD_ROUND_EVIDENCE_COUNT={len(pending_rows)}")
    print(f"THIRD_ROUND_EVIDENCE_PLAN_ROW_COUNT={len(plan_rows)}")
    print(f"EVERY_PENDING_THIRD_ROUND_EVIDENCE_HAS_PLAN_ROW={tf(every_pending_has_plan)}")
    print(f"THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT_ROW_COUNT={len(requirement_rows)}")
    print(f"THIRD_ROUND_EVIDENCE_PRIORITY_AUDIT_ROW_COUNT={len(priority_rows)}")
    print("EVIDENCE_ACCEPTANCE=FALSE")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
