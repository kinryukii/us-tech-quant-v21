#!/usr/bin/env python
"""V20.141 third-round evidence reconciliation.

Reconciles V20.140 third-round dry-run evidence outputs against the V20.139
third-round plan and V20.133 unresolved evidence blockers. This stage is
reconciliation-only, audit-only, non-mutating, and never marks promotion ready.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_DECISION.csv"
IN_EXECUTION = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_EXECUTION_AUDIT.csv"
IN_RESULT = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_RESULT_AUDIT.csv"
IN_GAP = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_140_THIRD_ROUND_EVIDENCE_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_140_NEXT_STAGE_GATE.csv"
IN_PLAN = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_PLAN.csv"
IN_REQUIREMENT = CONSOLIDATION / "V20_139_THIRD_ROUND_EVIDENCE_REQUIREMENT_AUDIT.csv"
IN_V138_RECORD = CONSOLIDATION / "V20_138_SECOND_ROUND_OPERATOR_DECISION_RECORD.csv"
IN_V133_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"

OUT_DECISION = CONSOLIDATION / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_141_THIRD_ROUND_PLAN_RECONCILIATION_AUDIT.csv"
OUT_RESULT = CONSOLIDATION / "V20_141_THIRD_ROUND_RESULT_RECONCILIATION_AUDIT.csv"
OUT_COVERAGE = CONSOLIDATION / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_141_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V140_REQUIRED_STATUS = "PASS_V20_140_THIRD_ROUND_EVIDENCE_DRY_RUN_READY_FOR_V20_141"
PASS_STATUS = "PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_READY_FOR_V20_142"
PARTIAL_STATUS = "PARTIAL_PASS_V20_141_THIRD_ROUND_EVIDENCE_RECONCILED_NEEDS_OPERATOR_REVIEW_READY_FOR_V20_142"
BLOCKED_STATUS = "BLOCKED_V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION"

REQUIRED_INPUTS = [IN_DECISION, IN_EXECUTION, IN_RESULT, IN_GAP, IN_SAFETY, IN_GATE, IN_PLAN, IN_REQUIREMENT, IN_V138_RECORD, IN_V133_REMAINING]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 141))
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
    "third_round_evidence_reconciliation_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_140_gate_consumed", "v20_141_third_round_evidence_reconciliation_allowed_by_v140", "v20_140_final_status", "v20_140_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_140", "third_round_evidence_plan_row_count", "third_round_plan_reconciliation_row_count", "every_third_round_evidence_plan_has_reconciliation_row", "third_round_result_reconciliation_row_count", "unresolved_evidence_blocker_count", "third_round_blocker_coverage_row_count", "every_unresolved_evidence_blocker_has_coverage_status", "third_round_covered_by_evidence_for_review_count", "third_round_partially_covered_needs_operator_review_count", "third_round_not_covered_evidence_still_missing_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_142_third_round_operator_review_packet_allowed", "third_round_evidence_reconciliation_status", "blocking_reason", *COMMON.keys()]
PLAN_FIELDS = ["third_round_plan_reconciliation_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_execution_audit_id", "source_remaining_evidence_blocker_status_id", "blocker_category", "plan_reconciliation_status", "third_round_evidence_requirement", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
RESULT_FIELDS = ["third_round_result_reconciliation_audit_id", "selected_repair_scenario_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_result_audit_id", "source_third_round_gap_status_audit_id", "blocker_category", "dry_run_result_status", "gap_status", "result_reconciliation_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
COVERAGE_FIELDS = ["third_round_blocker_coverage_audit_id", "selected_repair_scenario_id", "source_remaining_evidence_blocker_status_id", "source_second_round_operator_decision_record_id", "source_operator_decision_record_id", "source_third_round_evidence_plan_id", "source_third_round_evidence_result_audit_id", "blocker_category", "coverage_status", "coverage_reason", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_140_gate_consumed", "v20_141_third_round_evidence_reconciliation_allowed_by_v140", "selected_repair_scenario_id", "third_round_evidence_reconciliation_created", "every_third_round_evidence_plan_has_reconciliation_row", "every_unresolved_evidence_blocker_has_coverage_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_142_third_round_operator_review_packet_allowed", "next_recommended_action", "blocking_reason", "third_round_evidence_reconciliation_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.141 reconciles third-round dry-run evidence only and keeps all acceptance and promotion flags false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, plan, result, coverage, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_RESULT, RESULT_FIELDS, result)
    write_csv(OUT_COVERAGE, COVERAGE_FIELDS, coverage)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.141 Third-Round Evidence Reconciliation Report", "",
        f"- wrapper_status: {decision.get('third_round_evidence_reconciliation_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- third_round_evidence_plan_row_count: {decision.get('third_round_evidence_plan_row_count')}",
        f"- third_round_plan_reconciliation_row_count: {decision.get('third_round_plan_reconciliation_row_count')}",
        f"- third_round_blocker_coverage_row_count: {decision.get('third_round_blocker_coverage_row_count')}",
        f"- third_round_covered_by_evidence_for_review_count: {decision.get('third_round_covered_by_evidence_for_review_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_142_third_round_operator_review_packet_allowed: {decision.get('v20_142_third_round_operator_review_packet_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION_001", "v20_140_gate_consumed": "FALSE", "v20_141_third_round_evidence_reconciliation_allowed_by_v140": "FALSE", "v20_140_final_status": "", "v20_140_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_140": "FALSE", "third_round_evidence_plan_row_count": "0", "third_round_plan_reconciliation_row_count": "0", "every_third_round_evidence_plan_has_reconciliation_row": "FALSE", "third_round_result_reconciliation_row_count": "0", "unresolved_evidence_blocker_count": "0", "third_round_blocker_coverage_row_count": "0", "every_unresolved_evidence_blocker_has_coverage_status": "FALSE", "third_round_covered_by_evidence_for_review_count": "0", "third_round_partially_covered_needs_operator_review_count": "0", "third_round_not_covered_evidence_still_missing_count": "0", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_142_third_round_operator_review_packet_allowed": "FALSE", "third_round_evidence_reconciliation_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_141_NEXT_STAGE_GATE_001", "v20_140_gate_consumed": "FALSE", "v20_141_third_round_evidence_reconciliation_allowed_by_v140": "FALSE", "selected_repair_scenario_id": "", "third_round_evidence_reconciliation_created": "TRUE", "every_third_round_evidence_plan_has_reconciliation_row": "FALSE", "every_unresolved_evidence_blocker_has_coverage_status": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_142_third_round_operator_review_packet_allowed": "FALSE", "next_recommended_action": "V20.141_THIRD_ROUND_EVIDENCE_RECONCILIATION_REPAIR", "blocking_reason": blocking, "third_round_evidence_reconciliation_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_140_GATE_CONSUMED=FALSE")
    print("V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def is_unresolved(row: dict[str, str]) -> bool:
    return truthy(row.get("remaining_evidence_review_required")) or clean(row.get("blocker_status")) in {"UNRESOLVED_OR_PENDING_REVIEW", "BLOCKED"} or clean(row.get("resolution_status")).startswith("NOT_RESOLVED")


def build_reconciliation_artifacts(selected_id: str, plan_rows: list[dict[str, str]], execution_rows: list[dict[str, str]], result_rows: list[dict[str, str]], gap_rows: list[dict[str, str]], unresolved_rows: list[dict[str, str]], record_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    execution_by_plan = {clean(row.get("source_third_round_evidence_plan_id")): row for row in execution_rows}
    result_by_plan = {clean(row.get("source_third_round_evidence_plan_id")): row for row in result_rows}
    gap_by_plan = {clean(row.get("source_third_round_evidence_plan_id")): row for row in gap_rows}
    plan_by_remaining = {clean(row.get("source_remaining_evidence_blocker_status_id")): row for row in plan_rows}
    record_by_remaining = {clean(row.get("source_remaining_evidence_blocker_status_id")): row for row in record_rows}
    plan_recon = []
    result_recon = []
    coverage = []
    for i, plan in enumerate(plan_rows, start=1):
        plan_id = clean(plan.get("third_round_evidence_plan_id"))
        execution = execution_by_plan.get(plan_id, {})
        result = result_by_plan.get(plan_id, {})
        gap = gap_by_plan.get(plan_id, {})
        plan_recon.append({
            "third_round_plan_reconciliation_audit_id": f"V20_141_THIRD_ROUND_PLAN_RECONCILIATION_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "source_third_round_evidence_execution_audit_id": clean(execution.get("third_round_evidence_execution_audit_id")),
            "source_remaining_evidence_blocker_status_id": clean(plan.get("source_remaining_evidence_blocker_status_id")),
            "blocker_category": clean(plan.get("blocker_category")),
            "plan_reconciliation_status": "RECONCILED_TO_THIRD_ROUND_DRY_RUN_EXECUTION" if execution else "MISSING_THIRD_ROUND_DRY_RUN_EXECUTION",
            "third_round_evidence_requirement": clean(plan.get("third_round_evidence_requirement")),
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        gap_status = clean(gap.get("gap_status"))
        result_recon.append({
            "third_round_result_reconciliation_audit_id": f"V20_141_THIRD_ROUND_RESULT_RECONCILIATION_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_third_round_evidence_plan_id": plan_id,
            "source_third_round_evidence_result_audit_id": clean(result.get("third_round_evidence_result_audit_id")),
            "source_third_round_gap_status_audit_id": clean(gap.get("third_round_evidence_gap_status_audit_id")),
            "blocker_category": clean(plan.get("blocker_category")),
            "dry_run_result_status": clean(result.get("dry_run_result_status")),
            "gap_status": gap_status,
            "result_reconciliation_status": "RECONCILED_THIRD_ROUND_AVAILABLE_FOR_REVIEW" if gap_status == "THIRD_ROUND_EVIDENCE_AVAILABLE_FOR_REVIEW" else "RECONCILED_THIRD_ROUND_GAP_REMAINS",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
    for i, blocker in enumerate(unresolved_rows, start=1):
        remaining_id = clean(blocker.get("remaining_evidence_blocker_status_id"))
        plan = plan_by_remaining.get(remaining_id, {})
        plan_id = clean(plan.get("third_round_evidence_plan_id"))
        result = result_by_plan.get(plan_id, {})
        gap = gap_by_plan.get(plan_id, {})
        gap_status = clean(gap.get("gap_status"))
        if gap_status == "THIRD_ROUND_EVIDENCE_AVAILABLE_FOR_REVIEW":
            coverage_status = "THIRD_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW"
            reason = "Third-round dry-run evidence is available for review; explicit human acceptance remains absent."
        elif gap_status == "THIRD_ROUND_PARTIAL_EVIDENCE_AVAILABLE":
            coverage_status = "THIRD_ROUND_PARTIALLY_COVERED_NEEDS_OPERATOR_REVIEW"
            reason = "Third-round evidence is partially available and needs operator review."
        else:
            coverage_status = "THIRD_ROUND_NOT_COVERED_EVIDENCE_STILL_MISSING"
            reason = "Third-round evidence is still missing."
        record = record_by_remaining.get(remaining_id, {})
        coverage.append({
            "third_round_blocker_coverage_audit_id": f"V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_remaining_evidence_blocker_status_id": remaining_id,
            "source_second_round_operator_decision_record_id": clean(record.get("second_round_operator_decision_record_id")),
            "source_operator_decision_record_id": clean(blocker.get("source_operator_decision_record_id")) or clean(record.get("source_operator_decision_record_id")),
            "source_third_round_evidence_plan_id": plan_id,
            "source_third_round_evidence_result_audit_id": clean(result.get("third_round_evidence_result_audit_id")),
            "blocker_category": clean(blocker.get("blocker_category")),
            "coverage_status": coverage_status,
            "coverage_reason": reason,
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
    return plan_recon, result_recon, coverage


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    execution_rows = read_csv(IN_EXECUTION)
    result_rows = read_csv(IN_RESULT)
    gap_rows = read_csv(IN_GAP)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    plan_rows = read_csv(IN_PLAN)
    requirement_rows = read_csv(IN_REQUIREMENT)
    record_rows = read_csv(IN_V138_RECORD)
    remaining_rows = read_csv(IN_V133_REMAINING)
    if not all([decision_rows, execution_rows, result_rows, gap_rows, safety_input_rows, gate_rows, plan_rows, requirement_rows, record_rows, remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v140_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_140_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_141_third_round_evidence_reconciliation_allowed"))
    v140_status = clean(gate_in.get("third_round_evidence_dry_run_status")) or clean(decision_in.get("third_round_evidence_dry_run_status"))
    v140_status_allowed = v140_status == V140_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    unresolved_rows = [row for row in remaining_rows if is_unresolved(row)]

    plan_recon_rows, result_recon_rows, coverage_rows = build_reconciliation_artifacts(selected_id, plan_rows, execution_rows, result_rows, gap_rows, unresolved_rows, record_rows)
    plan_ids = {clean(row.get("third_round_evidence_plan_id")) for row in plan_rows}
    recon_plan_ids = {clean(row.get("source_third_round_evidence_plan_id")) for row in plan_recon_rows}
    every_plan_reconciled = bool(plan_rows) and len(plan_recon_rows) == len(plan_rows) and recon_plan_ids == plan_ids and all(clean(row.get("plan_reconciliation_status")) == "RECONCILED_TO_THIRD_ROUND_DRY_RUN_EXECUTION" for row in plan_recon_rows)
    unresolved_ids = {clean(row.get("remaining_evidence_blocker_status_id")) for row in unresolved_rows}
    coverage_ids = {clean(row.get("source_remaining_evidence_blocker_status_id")) for row in coverage_rows}
    every_unresolved_has_coverage = bool(unresolved_rows) and len(coverage_rows) == len(unresolved_rows) and coverage_ids == unresolved_ids
    covered_count = sum(1 for row in coverage_rows if row["coverage_status"] == "THIRD_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW")
    partial_count = sum(1 for row in coverage_rows if row["coverage_status"] == "THIRD_ROUND_PARTIALLY_COVERED_NEEDS_OPERATOR_REVIEW")
    missing_count = sum(1 for row in coverage_rows if row["coverage_status"] == "THIRD_ROUND_NOT_COVERED_EVIDENCE_STILL_MISSING")
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in execution_rows + plan_rows + plan_recon_rows)
    counts = prohibited_counts([decision_rows, execution_rows, result_rows, gap_rows, safety_input_rows, gate_rows, plan_rows, requirement_rows, record_rows, remaining_rows, plan_recon_rows, result_recon_rows, coverage_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v140_gate_consumed, allowed, v140_status_allowed, selected_matches, every_plan_reconciled, every_unresolved_has_coverage, bool(result_recon_rows), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    if base_ok and missing_count == 0 and partial_count == 0:
        final_status = PASS_STATUS
    elif base_ok:
        final_status = PARTIAL_STATUS
    else:
        final_status = BLOCKED_STATUS
    next_allowed = final_status in {PASS_STATUS, PARTIAL_STATUS}
    blocking = "" if next_allowed else "third_round_evidence_reconciliation_requirements_not_met"

    decision = {"decision_check_id": "V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_DECISION_001", "v20_140_gate_consumed": tf(v140_gate_consumed), "v20_141_third_round_evidence_reconciliation_allowed_by_v140": tf(allowed), "v20_140_final_status": v140_status, "v20_140_status_allowed": tf(v140_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_140": tf(selected_matches), "third_round_evidence_plan_row_count": str(len(plan_rows)), "third_round_plan_reconciliation_row_count": str(len(plan_recon_rows)), "every_third_round_evidence_plan_has_reconciliation_row": tf(every_plan_reconciled), "third_round_result_reconciliation_row_count": str(len(result_recon_rows)), "unresolved_evidence_blocker_count": str(len(unresolved_rows)), "third_round_blocker_coverage_row_count": str(len(coverage_rows)), "every_unresolved_evidence_blocker_has_coverage_status": tf(every_unresolved_has_coverage), "third_round_covered_by_evidence_for_review_count": str(covered_count), "third_round_partially_covered_needs_operator_review_count": str(partial_count), "third_round_not_covered_evidence_still_missing_count": str(missing_count), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_142_third_round_operator_review_packet_allowed": tf(next_allowed), "third_round_evidence_reconciliation_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_141_NEXT_STAGE_GATE_001", "v20_140_gate_consumed": tf(v140_gate_consumed), "v20_141_third_round_evidence_reconciliation_allowed_by_v140": tf(allowed), "selected_repair_scenario_id": selected_id, "third_round_evidence_reconciliation_created": "TRUE", "every_third_round_evidence_plan_has_reconciliation_row": tf(every_plan_reconciled), "every_unresolved_evidence_blocker_has_coverage_status": tf(every_unresolved_has_coverage), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_142_third_round_operator_review_packet_allowed": tf(next_allowed), "next_recommended_action": "V20.142_THIRD_ROUND_OPERATOR_REVIEW_PACKET" if next_allowed else "V20.141_THIRD_ROUND_EVIDENCE_RECONCILIATION_REPAIR", "blocking_reason": blocking, "third_round_evidence_reconciliation_status": final_status, **COMMON}
    write_all([decision], plan_recon_rows, result_recon_rows, coverage_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_140_GATE_CONSUMED={tf(v140_gate_consumed)}")
    print(f"V20_141_THIRD_ROUND_EVIDENCE_RECONCILIATION_ALLOWED_BY_V140={tf(allowed)}")
    print(f"V20_140_FINAL_STATUS={v140_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_140={tf(selected_matches)}")
    print(f"THIRD_ROUND_EVIDENCE_PLAN_ROW_COUNT={len(plan_rows)}")
    print(f"THIRD_ROUND_PLAN_RECONCILIATION_ROW_COUNT={len(plan_recon_rows)}")
    print(f"EVERY_THIRD_ROUND_EVIDENCE_PLAN_HAS_RECONCILIATION_ROW={tf(every_plan_reconciled)}")
    print(f"THIRD_ROUND_RESULT_RECONCILIATION_ROW_COUNT={len(result_recon_rows)}")
    print(f"UNRESOLVED_EVIDENCE_BLOCKER_COUNT={len(unresolved_rows)}")
    print(f"THIRD_ROUND_BLOCKER_COVERAGE_ROW_COUNT={len(coverage_rows)}")
    print(f"EVERY_UNRESOLVED_EVIDENCE_BLOCKER_HAS_COVERAGE_STATUS={tf(every_unresolved_has_coverage)}")
    print(f"THIRD_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW_COUNT={covered_count}")
    print(f"THIRD_ROUND_PARTIALLY_COVERED_NEEDS_OPERATOR_REVIEW_COUNT={partial_count}")
    print(f"THIRD_ROUND_NOT_COVERED_EVIDENCE_STILL_MISSING_COUNT={missing_count}")
    print("EVIDENCE_ACCEPTANCE=FALSE")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_142_THIRD_ROUND_OPERATOR_REVIEW_PACKET_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

