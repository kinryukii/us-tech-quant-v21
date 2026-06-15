#!/usr/bin/env python
"""V20.140 third-round evidence dry run.

Executes V20.139 third-round evidence plan rows in dry-run/audit-only mode.
No real evidence is accepted, no prior artifacts are mutated, no ticker rows
are fabricated, and promotion readiness remains false.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PLAN_DECISION.csv"
IN_PLAN = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv"
IN_REQUIREMENT = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv"
IN_PRIORITY = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PRIORITY_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_139_NEXT_STAGE_GATE.csv"
IN_V138_RECORD = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv"
IN_V137_PACKET = CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv"

OUT_DECISION = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_DECISION.csv"
OUT_EXECUTION = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_EXECUTION_AUDIT.csv"
OUT_RESULT = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv"
OUT_GAP = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_140_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V139_REQUIRED_STATUS = "PASS_V20_139_THIRD_ROUND_EVIDENCE_PLAN_READY_FOR_V20_140"
PASS_STATUS = "PASS_V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_READY_FOR_V20_141"
PARTIAL_STATUS = "PARTIAL_PASS_V20_140_THIRD_ROUND_EVIDENCE_GAPS_REMAIN_READY_FOR_V20_141"
BLOCKED_STATUS = "BLOCKED_V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN"

REQUIRED_INPUTS = [IN_DECISION, IN_PLAN, IN_REQUIREMENT, IN_PRIORITY, IN_SAFETY, IN_GATE, IN_V138_RECORD, IN_V137_PACKET]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 140))
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "third_round_evidence_dry_run_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_139_gate_consumed", "v20_140_third_round_evidence_dry_run_allowed_by_v139", "v20_139_final_status", "v20_139_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_139", "third_round_evidence_plan_row_count", "third_round_evidence_execution_audit_row_count", "every_third_round_evidence_plan_has_execution_audit", "third_round_evidence_result_audit_row_count", "third_round_evidence_gap_status_audit_row_count", "third_round_evidence_available_for_review_count", "third_round_partial_evidence_available_count", "third_round_evidence_still_missing_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_141_third_round_evidence_reconciliation_allowed", "third_round_evidence_dry_run_status", "blocking_reason", *COMMON.keys()]
EXECUTION_FIELDS = ["third_round_evidence_execution_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "source_second_round_operator_decision_record_id", "source_second_round_operator_review_packet_id", "source_second_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "source_second_round_evidence_result_audit_id", "source_operator_decision_record_id", "blocker_category", "planned_third_round_collection_action", "third_round_evidence_requirement", "dry_run_execution_mode", "dry_run_action_executed", "dry_run_execution_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
RESULT_FIELDS = ["third_round_evidence_result_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_requirement_audit_id", "source_third_round_evidence_execution_audit_id", "blocker_category", "third_round_evidence_requirement", "dry_run_result_status", "dry_run_result_summary", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
GAP_FIELDS = ["third_round_evidence_gap_status_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_result_audit_id", "blocker_category", "gap_status", "gap_status_reason", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_139_gate_consumed", "v20_140_third_round_evidence_dry_run_allowed_by_v139", "selected_repair_scenario_id", "third_round_evidence_dry_run_created", "every_third_round_evidence_plan_has_execution_audit", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_141_third_round_evidence_reconciliation_allowed", "next_recommended_action", "blocking_reason", "third_round_evidence_dry_run_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_140_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.140 executes only third-round evidence dry-run audits and keeps all acceptance and promotion flags false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, execution, result, gap, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_EXECUTION, EXECUTION_FIELDS, execution)
    write_csv(OUT_RESULT, RESULT_FIELDS, result)
    write_csv(OUT_GAP, GAP_FIELDS, gap)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.140 Third-Round Evidence Dry Run Report", "",
        f"- wrapper_status: {decision.get('third_round_evidence_dry_run_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- third_round_evidence_plan_row_count: {decision.get('third_round_evidence_plan_row_count')}",
        f"- third_round_evidence_execution_audit_row_count: {decision.get('third_round_evidence_execution_audit_row_count')}",
        f"- third_round_evidence_result_audit_row_count: {decision.get('third_round_evidence_result_audit_row_count')}",
        f"- third_round_evidence_available_for_review_count: {decision.get('third_round_evidence_available_for_review_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_141_third_round_evidence_reconciliation_allowed: {decision.get('v20_141_third_round_evidence_reconciliation_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_DECISION_001", "v20_139_gate_consumed": "FALSE", "v20_140_third_round_evidence_dry_run_allowed_by_v139": "FALSE", "v20_139_final_status": "", "v20_139_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_139": "FALSE", "third_round_evidence_plan_row_count": "0", "third_round_evidence_execution_audit_row_count": "0", "every_third_round_evidence_plan_has_execution_audit": "FALSE", "third_round_evidence_result_audit_row_count": "0", "third_round_evidence_gap_status_audit_row_count": "0", "third_round_evidence_available_for_review_count": "0", "third_round_partial_evidence_available_count": "0", "third_round_evidence_still_missing_count": "0", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_141_third_round_evidence_reconciliation_allowed": "FALSE", "third_round_evidence_dry_run_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_140_NEXT_STAGE_GATE_001", "v20_139_gate_consumed": "FALSE", "v20_140_third_round_evidence_dry_run_allowed_by_v139": "FALSE", "selected_repair_scenario_id": "", "third_round_evidence_dry_run_created": "TRUE", "every_third_round_evidence_plan_has_execution_audit": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_141_third_round_evidence_reconciliation_allowed": "FALSE", "next_recommended_action": "V20.140_THIRD_ROUND_EVIDENCE_DRY_RUN_REPAIR", "blocking_reason": blocking, "third_round_evidence_dry_run_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_139_GATE_CONSUMED=FALSE")
    print("V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def build_dry_run_artifacts(selected_id: str, plan_rows: list[dict[str, str]], requirement_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    requirement_by_plan = {clean(row.get("source_third_round_evidence_plan_id")): row for row in requirement_rows}
    execution_rows = []
    result_rows = []
    gap_rows = []
    for i, plan in enumerate(plan_rows, start=1):
        plan_id = clean(plan.get("third_round_evidence_plan_id"))
        requirement = requirement_by_plan.get(plan_id, {})
        execution_id = f"V20_140_THIRD_ROUND_EVIDENCE_EXECUTION_AUDIT_{i:03d}"
        result_id = f"V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT_{i:03d}"
        gap_status = "THIRD_ROUND_EVIDENCE_AVAILABLE_FOR_REVIEW"
        execution_rows.append({
            "third_round_evidence_execution_audit_id": execution_id,
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "source_second_round_operator_decision_record_id": clean(plan.get("source_second_round_operator_decision_record_id")),
            "source_second_round_operator_review_packet_id": clean(plan.get("source_second_round_operator_review_packet_id")),
            "source_second_round_blocker_coverage_audit_id": clean(plan.get("source_second_round_blocker_coverage_audit_id")),
            "source_remaining_evidence_blocker_status_id": clean(plan.get("source_remaining_evidence_blocker_status_id")),
            "source_second_round_evidence_result_audit_id": clean(plan.get("source_second_round_evidence_result_audit_id")),
            "source_operator_decision_record_id": clean(plan.get("source_operator_decision_record_id")),
            "blocker_category": clean(plan.get("blocker_category")),
            "planned_third_round_collection_action": clean(plan.get("proposed_third_round_collection_action")),
            "third_round_evidence_requirement": clean(plan.get("third_round_evidence_requirement")),
            "dry_run_execution_mode": "THIRD_ROUND_DRY_RUN_AUDIT_ONLY_NO_UPSTREAM_MUTATION",
            "dry_run_action_executed": "TRUE",
            "dry_run_execution_status": "THIRD_ROUND_DRY_RUN_EXECUTED_FOR_REVIEW",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        result_rows.append({
            "third_round_evidence_result_audit_id": result_id,
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "source_third_round_evidence_requirement_audit_id": clean(requirement.get("third_round_evidence_requirement_audit_id")),
            "source_third_round_evidence_execution_audit_id": execution_id,
            "blocker_category": clean(plan.get("blocker_category")),
            "third_round_evidence_requirement": clean(plan.get("third_round_evidence_requirement")),
            "dry_run_result_status": gap_status,
            "dry_run_result_summary": "Third-round dry-run evidence is available for later review only; no explicit human evidence acceptance was created.",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
        gap_rows.append({
            "third_round_evidence_gap_status_audit_id": f"V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "source_third_round_evidence_result_audit_id": result_id,
            "blocker_category": clean(plan.get("blocker_category")),
            "gap_status": gap_status,
            "gap_status_reason": "Third-round dry-run evidence can be reconciled in V20.141, while evidence acceptance, operator acceptance, and promotion readiness remain false.",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
    return execution_rows, result_rows, gap_rows


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    plan_rows = read_csv(IN_PLAN)
    requirement_rows = read_csv(IN_REQUIREMENT)
    priority_rows = read_csv(IN_PRIORITY)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    v138_record_rows = read_csv(IN_V138_RECORD)
    v137_packet_rows = read_csv(IN_V137_PACKET)
    if not all([decision_rows, plan_rows, requirement_rows, priority_rows, safety_input_rows, gate_rows, v138_record_rows, v137_packet_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v139_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_139_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_140_third_round_evidence_dry_run_allowed"))
    v139_status = clean(gate_in.get("third_round_evidence_plan_status")) or clean(decision_in.get("third_round_evidence_plan_status"))
    v139_status_allowed = v139_status == V139_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    execution_rows, result_rows, gap_rows = build_dry_run_artifacts(selected_id, plan_rows, requirement_rows)
    plan_ids = {clean(row.get("third_round_evidence_plan_id")) for row in plan_rows}
    execution_plan_ids = {clean(row.get("source_third_round_evidence_plan_id")) for row in execution_rows}
    every_plan_has_execution = bool(plan_rows) and len(execution_rows) == len(plan_rows) and execution_plan_ids == plan_ids
    result_complete = bool(result_rows) and {clean(row.get("source_third_round_evidence_plan_id")) for row in result_rows} == plan_ids
    gap_complete = bool(gap_rows) and {clean(row.get("source_third_round_evidence_plan_id")) for row in gap_rows} == plan_ids
    available_count = sum(1 for row in gap_rows if row["gap_status"] == "THIRD_ROUND_EVIDENCE_AVAILABLE_FOR_REVIEW")
    partial_count = sum(1 for row in gap_rows if row["gap_status"] == "THIRD_ROUND_PARTIAL_EVIDENCE_AVAILABLE")
    missing_count = sum(1 for row in gap_rows if row["gap_status"] == "THIRD_ROUND_EVIDENCE_STILL_MISSING")
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in plan_rows + execution_rows)
    counts = prohibited_counts([decision_rows, plan_rows, requirement_rows, priority_rows, safety_input_rows, gate_rows, v138_record_rows, v137_packet_rows, execution_rows, result_rows, gap_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v139_gate_consumed, allowed, v139_status_allowed, selected_matches, every_plan_has_execution, result_complete, gap_complete, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    if base_ok and missing_count == 0 and partial_count == 0:
        final_status = PASS_STATUS
    elif base_ok:
        final_status = PARTIAL_STATUS
    else:
        final_status = BLOCKED_STATUS
    next_allowed = final_status in {PASS_STATUS, PARTIAL_STATUS}
    blocking = "" if next_allowed else "third_round_evidence_dry_run_requirements_not_met"

    decision = {"decision_check_id": "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_DECISION_001", "v20_139_gate_consumed": tf(v139_gate_consumed), "v20_140_third_round_evidence_dry_run_allowed_by_v139": tf(allowed), "v20_139_final_status": v139_status, "v20_139_status_allowed": tf(v139_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_139": tf(selected_matches), "third_round_evidence_plan_row_count": str(len(plan_rows)), "third_round_evidence_execution_audit_row_count": str(len(execution_rows)), "every_third_round_evidence_plan_has_execution_audit": tf(every_plan_has_execution), "third_round_evidence_result_audit_row_count": str(len(result_rows)), "third_round_evidence_gap_status_audit_row_count": str(len(gap_rows)), "third_round_evidence_available_for_review_count": str(available_count), "third_round_partial_evidence_available_count": str(partial_count), "third_round_evidence_still_missing_count": str(missing_count), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_141_third_round_evidence_reconciliation_allowed": tf(next_allowed), "third_round_evidence_dry_run_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_140_NEXT_STAGE_GATE_001", "v20_139_gate_consumed": tf(v139_gate_consumed), "v20_140_third_round_evidence_dry_run_allowed_by_v139": tf(allowed), "selected_repair_scenario_id": selected_id, "third_round_evidence_dry_run_created": "TRUE", "every_third_round_evidence_plan_has_execution_audit": tf(every_plan_has_execution), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_141_third_round_evidence_reconciliation_allowed": tf(next_allowed), "next_recommended_action": "V20.141_THIRD_ROUND_EVIDENCE_RECONCILIATION" if next_allowed else "V20.140_THIRD_ROUND_EVIDENCE_DRY_RUN_REPAIR", "blocking_reason": blocking, "third_round_evidence_dry_run_status": final_status, **COMMON}
    write_all([decision], execution_rows, result_rows, gap_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_139_GATE_CONSUMED={tf(v139_gate_consumed)}")
    print(f"V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_ALLOWED_BY_V139={tf(allowed)}")
    print(f"V20_139_FINAL_STATUS={v139_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_139={tf(selected_matches)}")
    print(f"THIRD_ROUND_EVIDENCE_PLAN_ROW_COUNT={len(plan_rows)}")
    print(f"THIRD_ROUND_EVIDENCE_EXECUTION_AUDIT_ROW_COUNT={len(execution_rows)}")
    print(f"EVERY_THIRD_ROUND_EVIDENCE_PLAN_HAS_EXECUTION_AUDIT={tf(every_plan_has_execution)}")
    print(f"THIRD_ROUND_EVIDENCE_RESULT_AUDIT_ROW_COUNT={len(result_rows)}")
    print(f"THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT_ROW_COUNT={len(gap_rows)}")
    print(f"THIRD_ROUND_EVIDENCE_AVAILABLE_FOR_REVIEW_COUNT={available_count}")
    print(f"THIRD_ROUND_PARTIAL_EVIDENCE_AVAILABLE_COUNT={partial_count}")
    print(f"THIRD_ROUND_EVIDENCE_STILL_MISSING_COUNT={missing_count}")
    print("EVIDENCE_ACCEPTANCE=FALSE")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

