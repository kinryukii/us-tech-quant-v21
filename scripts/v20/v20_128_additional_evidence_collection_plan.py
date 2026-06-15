#!/usr/bin/env python
"""V20.128 additional evidence collection plan.

Creates an audit-only plan for collecting additional evidence for unresolved
or pending blockers carried forward by V20.127. This stage does not collect
data, create ticker rows, accept operator decisions, or mark promotion ready.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_GATE_DECISION.csv"
IN_ACTION_AUDIT = CONSOLIDATION / "V20_127_ACTION_RESOLUTION_AUDIT.csv"
IN_REMAINING = CONSOLIDATION / "V20_127_REMAINING_BLOCKER_RESOLUTION_STATUS.csv"
IN_REQUIRED_EVIDENCE = CONSOLIDATION / "V20_127_REQUIRED_NEXT_EVIDENCE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_127_OPERATOR_ACTION_RESOLUTION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_127_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_PLAN.csv"
OUT_DETAIL = CONSOLIDATION / "V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT.csv"
OUT_PRIORITY = CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_PRIORITY_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_128_EVIDENCE_COLLECTION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_128_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V127_REQUIRED_STATUS = "PARTIAL_PASS_V20_127_MORE_EVIDENCE_REQUIRED_READY_FOR_V20_128"
PASS_STATUS = "PASS_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_READY_FOR_V20_129"
BLOCKED_STATUS = "BLOCKED_V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN"

REQUIRED_INPUTS = [IN_DECISION, IN_ACTION_AUDIT, IN_REMAINING, IN_REQUIRED_EVIDENCE, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127"]],
    IN_DECISION, IN_ACTION_AUDIT, IN_REMAINING, IN_REQUIRED_EVIDENCE, IN_SAFETY,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "additional_evidence_collection_plan_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_127_gate_consumed", "v20_128_additional_evidence_collection_plan_allowed_by_v127", "v20_127_final_status", "v20_127_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_127", "unresolved_pending_blocker_count", "evidence_collection_plan_row_count", "every_unresolved_pending_blocker_has_plan_row", "evidence_requirement_detail_audit_row_count", "evidence_collection_priority_audit_row_count", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_129_additional_evidence_collection_dry_run_allowed", "additional_evidence_collection_plan_status", "blocking_reason", *COMMON.keys()]
PLAN_FIELDS = ["evidence_collection_plan_id", "selected_repair_scenario_id", "source_remaining_blocker_resolution_status_id", "source_action_capture_record_id", "source_operator_decision_record_id", "blocker_category", "current_resolution_status", "decision_status", "blocker_status", "missing_evidence_type", "required_evidence_artifact", "proposed_collection_action", "priority", "expected_closure_criterion", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
DETAIL_FIELDS = ["evidence_requirement_detail_audit_id", "selected_repair_scenario_id", "source_evidence_collection_plan_id", "source_required_next_evidence_audit_id", "source_action_capture_record_id", "blocker_category", "missing_evidence_type", "required_next_evidence", "required_evidence_artifact", "requirement_detail_status", "promotion_ready", *COMMON.keys()]
PRIORITY_FIELDS = ["evidence_collection_priority_audit_id", "selected_repair_scenario_id", "source_evidence_collection_plan_id", "blocker_category", "priority", "priority_rank", "priority_reason", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_127_gate_consumed", "v20_128_additional_evidence_collection_plan_allowed_by_v127", "selected_repair_scenario_id", "additional_evidence_collection_plan_created", "every_unresolved_pending_blocker_has_plan_row", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_129_additional_evidence_collection_dry_run_allowed", "next_recommended_action", "blocking_reason", "additional_evidence_collection_plan_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_128_EVIDENCE_COLLECTION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.128 creates only additional evidence collection plan artifacts and keeps promotion readiness false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, plan, detail, priority, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_DETAIL, DETAIL_FIELDS, detail)
    write_csv(OUT_PRIORITY, PRIORITY_FIELDS, priority)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.128 Additional Evidence Collection Plan Report", "",
        f"- wrapper_status: {decision.get('additional_evidence_collection_plan_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- unresolved_pending_blocker_count: {decision.get('unresolved_pending_blocker_count')}",
        f"- evidence_collection_plan_row_count: {decision.get('evidence_collection_plan_row_count')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_129_additional_evidence_collection_dry_run_allowed: {decision.get('v20_129_additional_evidence_collection_dry_run_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_DECISION_001", "v20_127_gate_consumed": "FALSE", "v20_128_additional_evidence_collection_plan_allowed_by_v127": "FALSE", "v20_127_final_status": "", "v20_127_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_127": "FALSE", "unresolved_pending_blocker_count": "0", "evidence_collection_plan_row_count": "0", "every_unresolved_pending_blocker_has_plan_row": "FALSE", "evidence_requirement_detail_audit_row_count": "0", "evidence_collection_priority_audit_row_count": "0", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_129_additional_evidence_collection_dry_run_allowed": "FALSE", "additional_evidence_collection_plan_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_128_NEXT_STAGE_GATE_001", "v20_127_gate_consumed": "FALSE", "v20_128_additional_evidence_collection_plan_allowed_by_v127": "FALSE", "selected_repair_scenario_id": "", "additional_evidence_collection_plan_created": "TRUE", "every_unresolved_pending_blocker_has_plan_row": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_129_additional_evidence_collection_dry_run_allowed": "FALSE", "next_recommended_action": "V20.128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_REPAIR", "blocking_reason": blocking, "additional_evidence_collection_plan_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_127_GATE_CONSUMED=FALSE")
    print("V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def is_unresolved_pending(row: dict[str, str]) -> bool:
    return truthy(row.get("remaining_blocker_requires_review")) or clean(row.get("blocker_status")) in {"UNRESOLVED_OR_PENDING_REVIEW", "BLOCKED"} or clean(row.get("resolution_status")).startswith("NOT_RESOLVED")


def missing_evidence_type(blocker_category: str) -> str:
    if blocker_category == "official_promotion_policy_evidence":
        return "OFFICIAL_PROMOTION_POLICY_ACCEPTANCE_EVIDENCE"
    if blocker_category == "operator_approval_evidence":
        return "EXPLICIT_OPERATOR_APPROVAL_EVIDENCE"
    return "EXPLICIT_VALID_HUMAN_ACCEPTANCE_AND_SUPPORTING_REVIEW_EVIDENCE"


def required_artifact(blocker_category: str) -> str:
    safe_category = blocker_category.upper() or "UNCLASSIFIED_BLOCKER"
    return f"outputs/v20/consolidation/V20_129_{safe_category}_EVIDENCE_DRY_RUN_AUDIT.csv"


def proposed_action(blocker_category: str) -> str:
    if blocker_category == "official_promotion_policy_evidence":
        return "Prepare a dry-run evidence request for explicit policy acceptance limits before any future promotion path."
    if blocker_category == "operator_approval_evidence":
        return "Prepare a dry-run evidence request for explicit operator approval evidence and acceptance traceability."
    return "Prepare a dry-run evidence request for explicit human acceptance and blocker-specific supporting review evidence."


def build_plan_artifacts(selected_id: str, unresolved_rows: list[dict[str, str]], evidence_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    evidence_by_capture = {clean(row.get("source_action_capture_record_id")): row for row in evidence_rows}
    plan_rows = []
    detail_rows = []
    priority_rows = []
    for i, blocker in enumerate(unresolved_rows, start=1):
        capture_id = clean(blocker.get("source_action_capture_record_id"))
        category = clean(blocker.get("blocker_category"))
        evidence = evidence_by_capture.get(capture_id, {})
        plan_id = f"V20_128_EVIDENCE_COLLECTION_PLAN_{i:03d}"
        priority = "P1"
        plan_rows.append({
            "evidence_collection_plan_id": plan_id,
            "selected_repair_scenario_id": selected_id,
            "source_remaining_blocker_resolution_status_id": clean(blocker.get("remaining_blocker_resolution_status_id")),
            "source_action_capture_record_id": capture_id,
            "source_operator_decision_record_id": clean(blocker.get("source_operator_decision_record_id")),
            "blocker_category": category,
            "current_resolution_status": clean(blocker.get("resolution_status")),
            "decision_status": clean(blocker.get("decision_status")),
            "blocker_status": clean(blocker.get("blocker_status")),
            "missing_evidence_type": missing_evidence_type(category),
            "required_evidence_artifact": required_artifact(category),
            "proposed_collection_action": proposed_action(category),
            "priority": priority,
            "expected_closure_criterion": "A later stage records explicit valid human acceptance evidence and blocker-specific support without creating official, real-book, trade, broker, overwrite, mutation, or performance-claim artifacts.",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        detail_rows.append({
            "evidence_requirement_detail_audit_id": f"V20_128_EVIDENCE_REQUIREMENT_DETAIL_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_evidence_collection_plan_id": plan_id,
            "source_required_next_evidence_audit_id": clean(evidence.get("required_next_evidence_audit_id")),
            "source_action_capture_record_id": capture_id,
            "blocker_category": category,
            "missing_evidence_type": missing_evidence_type(category),
            "required_next_evidence": clean(evidence.get("required_next_evidence")) or "explicit valid human acceptance evidence and supporting blocker-specific review evidence",
            "required_evidence_artifact": required_artifact(category),
            "requirement_detail_status": "PLANNED_FOR_DRY_RUN_COLLECTION",
            "promotion_ready": "FALSE",
            **COMMON,
        })
        priority_rows.append({
            "evidence_collection_priority_audit_id": f"V20_128_EVIDENCE_COLLECTION_PRIORITY_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_evidence_collection_plan_id": plan_id,
            "blocker_category": category,
            "priority": priority,
            "priority_rank": str(i),
            "priority_reason": "Required before any operator acceptance or promotion-readiness path because blocker remains unresolved/pending.",
            "promotion_ready": "FALSE",
            **COMMON,
        })
    return plan_rows, detail_rows, priority_rows


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    action_rows = read_csv(IN_ACTION_AUDIT)
    remaining_rows = read_csv(IN_REMAINING)
    required_evidence_rows = read_csv(IN_REQUIRED_EVIDENCE)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, action_rows, remaining_rows, required_evidence_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v127_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_127_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_128_additional_evidence_collection_plan_allowed"))
    v127_status = clean(gate_in.get("operator_action_resolution_gate_status")) or clean(decision_in.get("operator_action_resolution_gate_status"))
    v127_status_allowed = v127_status == V127_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    unresolved_rows = [row for row in remaining_rows if is_unresolved_pending(row)]
    plan_rows, detail_rows, priority_rows = build_plan_artifacts(selected_id, unresolved_rows, required_evidence_rows)
    unresolved_ids = {clean(row.get("remaining_blocker_resolution_status_id")) for row in unresolved_rows}
    plan_ids = {clean(row.get("source_remaining_blocker_resolution_status_id")) for row in plan_rows}
    every_unresolved_has_plan = bool(unresolved_rows) and len(plan_rows) == len(unresolved_rows) and unresolved_ids == plan_ids
    detail_plan_ids = {clean(row.get("source_evidence_collection_plan_id")) for row in detail_rows}
    priority_plan_ids = {clean(row.get("source_evidence_collection_plan_id")) for row in priority_rows}
    plan_row_ids = {clean(row.get("evidence_collection_plan_id")) for row in plan_rows}
    detail_complete = bool(detail_rows) and detail_plan_ids == plan_row_ids
    priority_complete = bool(priority_rows) and priority_plan_ids == plan_row_ids
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in action_rows + plan_rows)
    counts = prohibited_counts([decision_rows, action_rows, remaining_rows, required_evidence_rows, safety_input_rows, gate_rows, plan_rows, detail_rows, priority_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v127_gate_consumed, allowed, v127_status_allowed, selected_matches, every_unresolved_has_plan, detail_complete, priority_complete, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "additional_evidence_collection_plan_requirements_not_met"

    decision = {"decision_check_id": "V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_DECISION_001", "v20_127_gate_consumed": tf(v127_gate_consumed), "v20_128_additional_evidence_collection_plan_allowed_by_v127": tf(allowed), "v20_127_final_status": v127_status, "v20_127_status_allowed": tf(v127_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_127": tf(selected_matches), "unresolved_pending_blocker_count": str(len(unresolved_rows)), "evidence_collection_plan_row_count": str(len(plan_rows)), "every_unresolved_pending_blocker_has_plan_row": tf(every_unresolved_has_plan), "evidence_requirement_detail_audit_row_count": str(len(detail_rows)), "evidence_collection_priority_audit_row_count": str(len(priority_rows)), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_129_additional_evidence_collection_dry_run_allowed": tf(next_allowed), "additional_evidence_collection_plan_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_128_NEXT_STAGE_GATE_001", "v20_127_gate_consumed": tf(v127_gate_consumed), "v20_128_additional_evidence_collection_plan_allowed_by_v127": tf(allowed), "selected_repair_scenario_id": selected_id, "additional_evidence_collection_plan_created": "TRUE", "every_unresolved_pending_blocker_has_plan_row": tf(every_unresolved_has_plan), "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_129_additional_evidence_collection_dry_run_allowed": tf(next_allowed), "next_recommended_action": "V20.129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN" if next_allowed else "V20.128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_REPAIR", "blocking_reason": blocking, "additional_evidence_collection_plan_status": final_status, **COMMON}
    write_all([decision], plan_rows, detail_rows, priority_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_127_GATE_CONSUMED={tf(v127_gate_consumed)}")
    print(f"V20_128_ADDITIONAL_EVIDENCE_COLLECTION_PLAN_ALLOWED_BY_V127={tf(allowed)}")
    print(f"V20_127_FINAL_STATUS={v127_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_127={tf(selected_matches)}")
    print(f"UNRESOLVED_PENDING_BLOCKER_COUNT={len(unresolved_rows)}")
    print(f"EVIDENCE_COLLECTION_PLAN_ROW_COUNT={len(plan_rows)}")
    print(f"EVERY_UNRESOLVED_PENDING_BLOCKER_HAS_PLAN_ROW={tf(every_unresolved_has_plan)}")
    print(f"EVIDENCE_REQUIREMENT_DETAIL_AUDIT_ROW_COUNT={len(detail_rows)}")
    print(f"EVIDENCE_COLLECTION_PRIORITY_AUDIT_ROW_COUNT={len(priority_rows)}")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_129_ADDITIONAL_EVIDENCE_COLLECTION_DRY_RUN_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
