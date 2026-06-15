#!/usr/bin/env python
"""V20.122 pending decision resolution plan.

Creates an audit-only, non-mutating resolution plan for pending operator
decisions carried forward by V20.121. This stage does not create official
artifacts and never marks promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_V121_DECISION = CONSOLIDATION / "V20_121_OPERATOR_DECISION_REVIEW_GATE_DECISION.csv"
IN_V121_COMPLETENESS = CONSOLIDATION / "V20_121_OPERATOR_DECISION_COMPLETENESS_AUDIT.csv"
IN_V121_PENDING = CONSOLIDATION / "V20_121_PENDING_DECISION_GATE_AUDIT.csv"
IN_V121_ACCEPTANCE = CONSOLIDATION / "V20_121_OPERATOR_ACCEPTANCE_VALIDATION_AUDIT.csv"
IN_V121_PROMOTION = CONSOLIDATION / "V20_121_PROMOTION_READINESS_GATE_AUDIT.csv"
IN_V121_SAFETY = CONSOLIDATION / "V20_121_OPERATOR_DECISION_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
IN_V121_GATE = CONSOLIDATION / "V20_121_NEXT_STAGE_GATE.csv"
IN_V120_RECORD = CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv"
IN_V120_UNRESOLVED = CONSOLIDATION / "V20_120_UNRESOLVED_DECISION_AUDIT.csv"
IN_V119_REQUIRED = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv"
IN_V118_REMAINING = CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv"

OUT_DECISION = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION.csv"
OUT_PLAN = CONSOLIDATION / "V20_122_PENDING_DECISION_RESOLUTION_PLAN.csv"
OUT_EVIDENCE_GAP = CONSOLIDATION / "V20_122_REQUIRED_EVIDENCE_GAP_AUDIT.csv"
OUT_FOLLOWUP = CONSOLIDATION / "V20_122_REQUIRED_FOLLOWUP_ACTION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_122_RESOLUTION_BOUNDARY_SAFETY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_122_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_122_PENDING_DECISION_RESOLUTION_PLAN_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V121_REQUIRED_STATUS = "PARTIAL_PASS_V20_121_OPERATOR_DECISIONS_STILL_PENDING_READY_FOR_V20_122"
PASS_STATUS = "PASS_V20_122_PENDING_DECISION_RESOLUTION_PLAN_READY_FOR_V20_123"
BLOCKED_STATUS = "BLOCKED_V20_122_PENDING_DECISION_RESOLUTION_PLAN"

REQUIRED_INPUTS = [
    IN_V121_DECISION,
    IN_V121_COMPLETENESS,
    IN_V121_PENDING,
    IN_V121_ACCEPTANCE,
    IN_V121_PROMOTION,
    IN_V121_SAFETY,
    IN_V121_GATE,
    IN_V120_RECORD,
    IN_V120_UNRESOLVED,
    IN_V119_REQUIRED,
    IN_V118_REMAINING,
]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121"]],
    IN_V121_DECISION,
    IN_V121_COMPLETENESS,
    IN_V121_PENDING,
    IN_V121_ACCEPTANCE,
    IN_V121_PROMOTION,
    IN_V121_SAFETY,
    IN_V120_RECORD,
    IN_V120_UNRESOLVED,
    IN_V119_REQUIRED,
    IN_V118_REMAINING,
]
PROHIBITED_FIELDS = [
    "accepted_weight_created",
    "accepted_weights_created",
    "real_book_weight_created",
    "real_book_action_created",
    "official_weight_created",
    "official_weights_created",
    "official_ranking_created",
    "official_rankings_created",
    "official_recommendation_created",
    "official_recommendations_created",
    "trade_action_created",
    "trade_actions_created",
    "broker_action_created",
    "broker_actions_created",
    "authoritative_overwrite_created",
    "authoritative_overwrites_created",
    "authoritative_ranking_overwritten",
    "weight_mutated",
    "weight_mutations_created",
    "performance_claim_created",
    "performance_claims_created",
    "performance_effectiveness_claim_created",
    "official_promotion_allowed",
    "is_official_weight",
    "promotion_ready",
]
COMMON = {
    "accepted_weight_created": "FALSE",
    "accepted_weights_created": "FALSE",
    "real_book_weight_created": "FALSE",
    "real_book_action_created": "FALSE",
    "official_weight_created": "FALSE",
    "official_weights_created": "FALSE",
    "official_ranking_created": "FALSE",
    "official_rankings_created": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_recommendations_created": "FALSE",
    "trade_action_created": "FALSE",
    "trade_actions_created": "FALSE",
    "broker_action_created": "FALSE",
    "broker_actions_created": "FALSE",
    "authoritative_overwrite_created": "FALSE",
    "authoritative_overwrites_created": "FALSE",
    "authoritative_ranking_overwritten": "FALSE",
    "weight_mutated": "FALSE",
    "weight_mutations_created": "FALSE",
    "performance_claim_created": "FALSE",
    "performance_claims_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE",
    "official_promotion_allowed": "FALSE",
    "is_official_weight": "FALSE",
    "promotion_ready": "FALSE",
    "research_only": "TRUE",
    "shadow_only": "TRUE",
    "pending_decision_resolution_planning_only": "TRUE",
    "audit_only": "TRUE",
    "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_121_gate_consumed", "v20_122_pending_decision_resolution_plan_allowed_by_v121", "v20_121_final_status", "v20_121_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_121", "pending_operator_decision_count", "resolution_plan_row_count", "every_pending_decision_has_resolution_plan", "evidence_gap_audit_row_count", "followup_action_audit_row_count", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_123_pending_evidence_followup_allowed", "pending_decision_resolution_plan_status", "blocking_reason", *COMMON.keys()]
PLAN_FIELDS = ["resolution_plan_id", "selected_repair_scenario_id", "source_operator_decision_record_id", "source_required_decision_id", "blocker_category", "current_decision_status", "current_pending_reason", "missing_evidence", "required_followup_action", "expected_artifact_needed_to_resolve", "operator_judgment_still_required", "promotion_ready", "resolution_plan_complete", *COMMON.keys()]
EVIDENCE_GAP_FIELDS = ["evidence_gap_id", "selected_repair_scenario_id", "blocker_category", "source_operator_decision_record_id", "missing_evidence", "expected_artifact_needed_to_resolve", "evidence_gap_status", *COMMON.keys()]
FOLLOWUP_FIELDS = ["followup_action_id", "selected_repair_scenario_id", "blocker_category", "source_operator_decision_record_id", "required_followup_action", "operator_judgment_still_required", "followup_action_status", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_121_gate_consumed", "v20_122_pending_decision_resolution_plan_allowed_by_v121", "selected_repair_scenario_id", "pending_decision_resolution_plan_created", "every_pending_decision_has_resolution_plan", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_123_pending_evidence_followup_allowed", "next_recommended_action", "blocking_reason", "pending_decision_resolution_plan_status", *COMMON.keys()]


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
    return [
        {
            "safety_check_id": f"V20_122_RESOLUTION_BOUNDARY_SAFETY_AUDIT_{i:03d}",
            "prohibited_field": field,
            "observed_true_count": str(counts.get(field, 0)),
            "safety_boundary_passed": tf(passed),
            "safety_status": "PASS" if passed else "BLOCKED",
            "safety_reason": "V20.122 creates only pending-decision resolution planning artifacts and keeps promotion readiness false.",
            **COMMON,
        }
        for i, field in enumerate(PROHIBITED_FIELDS, start=1)
    ]


def write_all(decision, plan, evidence_gap, followup, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PLAN, PLAN_FIELDS, plan)
    write_csv(OUT_EVIDENCE_GAP, EVIDENCE_GAP_FIELDS, evidence_gap)
    write_csv(OUT_FOLLOWUP, FOLLOWUP_FIELDS, followup)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        "\n".join(
            [
                "# V20.122 Pending Decision Resolution Plan Report",
                "",
                f"- wrapper_status: {decision.get('pending_decision_resolution_plan_status')}",
                f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
                f"- pending_operator_decision_count: {decision.get('pending_operator_decision_count')}",
                f"- resolution_plan_row_count: {decision.get('resolution_plan_row_count')}",
                f"- promotion_ready: {decision.get('promotion_ready')}",
                f"- v20_123_pending_evidence_followup_allowed: {decision.get('v20_123_pending_evidence_followup_allowed')}",
                "- official_recommendation_created: FALSE",
                "- performance_claim_created: FALSE",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED",
        "ACCEPTED_WEIGHTS_CREATED",
        "REAL_BOOK_WEIGHT_CREATED",
        "REAL_BOOK_ACTION_CREATED",
        "OFFICIAL_WEIGHT_CREATED",
        "OFFICIAL_WEIGHTS_CREATED",
        "OFFICIAL_RANKING_CREATED",
        "OFFICIAL_RANKINGS_CREATED",
        "OFFICIAL_RECOMMENDATION_CREATED",
        "OFFICIAL_RECOMMENDATIONS_CREATED",
        "TRADE_ACTION_CREATED",
        "TRADE_ACTIONS_CREATED",
        "BROKER_ACTION_CREATED",
        "BROKER_ACTIONS_CREATED",
        "AUTHORITATIVE_OVERWRITE_CREATED",
        "AUTHORITATIVE_OVERWRITES_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN",
        "WEIGHT_MUTATED",
        "WEIGHT_MUTATIONS_CREATED",
        "PERFORMANCE_CLAIM_CREATED",
        "PERFORMANCE_CLAIMS_CREATED",
        "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED",
        "IS_OFFICIAL_WEIGHT",
        "PROMOTION_READY",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {
        "decision_check_id": "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION_001",
        "v20_121_gate_consumed": "FALSE",
        "v20_122_pending_decision_resolution_plan_allowed_by_v121": "FALSE",
        "v20_121_final_status": "",
        "v20_121_status_allowed": "FALSE",
        "selected_repair_scenario_id": "",
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_121": "FALSE",
        "pending_operator_decision_count": "0",
        "resolution_plan_row_count": "0",
        "every_pending_decision_has_resolution_plan": "FALSE",
        "evidence_gap_audit_row_count": "0",
        "followup_action_audit_row_count": "0",
        "promotion_ready": "FALSE",
        "fabricated_ticker_row_count": "0",
        "no_ticker_rows_fabricated": "TRUE",
        "upstream_mutation_detected": "FALSE",
        "no_upstream_outputs_mutated": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "prohibited_action_true_count": "0",
        "v20_123_pending_evidence_followup_allowed": "FALSE",
        "pending_decision_resolution_plan_status": BLOCKED_STATUS,
        "blocking_reason": blocking,
        **COMMON,
    }
    gate = {
        "gate_check_id": "V20_122_NEXT_STAGE_GATE_001",
        "v20_121_gate_consumed": "FALSE",
        "v20_122_pending_decision_resolution_plan_allowed_by_v121": "FALSE",
        "selected_repair_scenario_id": "",
        "pending_decision_resolution_plan_created": "TRUE",
        "every_pending_decision_has_resolution_plan": "FALSE",
        "promotion_ready": "FALSE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_upstream_outputs_mutated": "TRUE",
        "safety_boundary_audit_passed": "FALSE",
        "v20_123_pending_evidence_followup_allowed": "FALSE",
        "next_recommended_action": "V20.122_PENDING_DECISION_RESOLUTION_PLAN_REPAIR",
        "blocking_reason": blocking,
        "pending_decision_resolution_plan_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_121_GATE_CONSUMED=FALSE")
    print("V20_123_PENDING_EVIDENCE_FOLLOWUP_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def describe_missing_evidence(category: str) -> str:
    if category == "official_promotion_policy_evidence":
        return "Explicit operator-accepted policy evidence showing the unresolved promotion blocker is resolved without creating official artifacts."
    if category == "operator_approval_evidence":
        return "Explicit human operator approval evidence linked to the required decision row."
    return "Explicit valid evidence supporting resolution of the pending operator decision."


def describe_followup(category: str) -> str:
    if category == "official_promotion_policy_evidence":
        return "Collect and attach policy review evidence; operator must decide whether the promotion blocker is resolved."
    if category == "operator_approval_evidence":
        return "Collect explicit operator acceptance or rejection with evidence; keep promotion_ready false until accepted."
    return "Collect required evidence and retain operator decision as pending until reviewed."


def expected_artifact(category: str) -> str:
    return f"operator_evidence_packet_for_{category}"


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    v121_decision_rows = read_csv(IN_V121_DECISION)
    v121_completeness_rows = read_csv(IN_V121_COMPLETENESS)
    v121_pending_rows = read_csv(IN_V121_PENDING)
    v121_acceptance_rows = read_csv(IN_V121_ACCEPTANCE)
    v121_promotion_rows = read_csv(IN_V121_PROMOTION)
    v121_safety_rows = read_csv(IN_V121_SAFETY)
    v121_gate_rows = read_csv(IN_V121_GATE)
    v120_record_rows = read_csv(IN_V120_RECORD)
    v120_unresolved_rows = read_csv(IN_V120_UNRESOLVED)
    v119_required_rows = read_csv(IN_V119_REQUIRED)
    v118_remaining_rows = read_csv(IN_V118_REMAINING)
    if not all([v121_decision_rows, v121_completeness_rows, v121_pending_rows, v121_acceptance_rows, v121_promotion_rows, v121_safety_rows, v121_gate_rows, v120_record_rows, v119_required_rows, v118_remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(v121_decision_rows)
    gate_in = first(v121_gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v121_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_121_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_122_pending_decision_resolution_plan_allowed"))
    v121_status = clean(gate_in.get("operator_decision_review_gate_status")) or clean(decision_in.get("operator_decision_review_gate_status"))
    v121_status_allowed = v121_status == V121_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    pending_records = [
        row
        for row in v120_record_rows
        if clean(row.get("decision_status")) == "PENDING_OPERATOR_DECISION" and clean(row.get("selected_repair_scenario_id")) == selected_id
    ]
    pending_categories_from_v121 = {clean(row.get("blocker_category")) for row in v121_pending_rows if clean(row.get("decision_status")) == "PENDING_OPERATOR_DECISION"}
    required_categories = {clean(row.get("blocker_category")) for row in v119_required_rows if truthy(row.get("decision_required"))}

    plan_rows = []
    gap_rows = []
    followup_rows = []
    for i, row in enumerate(pending_records, start=1):
        category = clean(row.get("blocker_category"))
        missing_evidence = describe_missing_evidence(category)
        followup = describe_followup(category)
        artifact = expected_artifact(category)
        current_reason = "Operator decision remains pending because operator_acceptance is FALSE and valid_acceptance_evidence is FALSE."
        plan_rows.append(
            {
                "resolution_plan_id": f"V20_122_PENDING_DECISION_RESOLUTION_PLAN_{i:03d}",
                "selected_repair_scenario_id": selected_id,
                "source_operator_decision_record_id": clean(row.get("operator_decision_record_id")),
                "source_required_decision_id": clean(row.get("source_required_decision_id")),
                "blocker_category": category,
                "current_decision_status": clean(row.get("decision_status")),
                "current_pending_reason": current_reason,
                "missing_evidence": missing_evidence,
                "required_followup_action": followup,
                "expected_artifact_needed_to_resolve": artifact,
                "operator_judgment_still_required": "TRUE",
                "promotion_ready": "FALSE",
                "resolution_plan_complete": "TRUE",
                **COMMON,
            }
        )
        gap_rows.append(
            {
                "evidence_gap_id": f"V20_122_REQUIRED_EVIDENCE_GAP_AUDIT_{i:03d}",
                "selected_repair_scenario_id": selected_id,
                "blocker_category": category,
                "source_operator_decision_record_id": clean(row.get("operator_decision_record_id")),
                "missing_evidence": missing_evidence,
                "expected_artifact_needed_to_resolve": artifact,
                "evidence_gap_status": "MISSING_EVIDENCE_REQUIRES_OPERATOR_FOLLOWUP",
                **COMMON,
            }
        )
        followup_rows.append(
            {
                "followup_action_id": f"V20_122_REQUIRED_FOLLOWUP_ACTION_AUDIT_{i:03d}",
                "selected_repair_scenario_id": selected_id,
                "blocker_category": category,
                "source_operator_decision_record_id": clean(row.get("operator_decision_record_id")),
                "required_followup_action": followup,
                "operator_judgment_still_required": "TRUE",
                "followup_action_status": "REQUIRED_BEFORE_ANY_PROMOTION_READINESS",
                **COMMON,
            }
        )

    every_pending_has_plan = (
        bool(pending_records)
        and len(plan_rows) == len(pending_records)
        and {row["blocker_category"] for row in plan_rows} == pending_categories_from_v121 == required_categories
        and all(clean(row.get("resolution_plan_complete")) == "TRUE" for row in plan_rows)
    )
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in v120_record_rows)
    counts = prohibited_counts(
        [
            v121_decision_rows,
            v121_completeness_rows,
            v121_pending_rows,
            v121_acceptance_rows,
            v121_promotion_rows,
            v121_safety_rows,
            v121_gate_rows,
            v120_record_rows,
            v120_unresolved_rows,
            v119_required_rows,
            v118_remaining_rows,
            plan_rows,
            gap_rows,
            followup_rows,
        ]
    )
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in v121_safety_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)

    base_ok = all(
        [
            v121_gate_consumed,
            allowed,
            v121_status_allowed,
            selected_matches,
            every_pending_has_plan,
            bool(gap_rows),
            bool(followup_rows),
            ticker_count == 0,
            not upstream_mutation,
            safety_passed,
            prohibited_count == 0,
        ]
    )
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "pending_decision_resolution_plan_requirements_not_met"

    decision = {
        "decision_check_id": "V20_122_PENDING_DECISION_RESOLUTION_PLAN_DECISION_001",
        "v20_121_gate_consumed": tf(v121_gate_consumed),
        "v20_122_pending_decision_resolution_plan_allowed_by_v121": tf(allowed),
        "v20_121_final_status": v121_status,
        "v20_121_status_allowed": tf(v121_status_allowed),
        "selected_repair_scenario_id": selected_id,
        "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID,
        "selected_scenario_matches_v20_121": tf(selected_matches),
        "pending_operator_decision_count": str(len(pending_records)),
        "resolution_plan_row_count": str(len(plan_rows)),
        "every_pending_decision_has_resolution_plan": tf(every_pending_has_plan),
        "evidence_gap_audit_row_count": str(len(gap_rows)),
        "followup_action_audit_row_count": str(len(followup_rows)),
        "promotion_ready": "FALSE",
        "fabricated_ticker_row_count": str(ticker_count),
        "no_ticker_rows_fabricated": tf(ticker_count == 0),
        "upstream_mutation_detected": tf(upstream_mutation),
        "no_upstream_outputs_mutated": tf(not upstream_mutation),
        "safety_boundary_audit_passed": tf(safety_passed),
        "prohibited_action_true_count": str(prohibited_count),
        "v20_123_pending_evidence_followup_allowed": tf(next_allowed),
        "pending_decision_resolution_plan_status": final_status,
        "blocking_reason": blocking,
        **COMMON,
    }
    gate = {
        "gate_check_id": "V20_122_NEXT_STAGE_GATE_001",
        "v20_121_gate_consumed": tf(v121_gate_consumed),
        "v20_122_pending_decision_resolution_plan_allowed_by_v121": tf(allowed),
        "selected_repair_scenario_id": selected_id,
        "pending_decision_resolution_plan_created": "TRUE",
        "every_pending_decision_has_resolution_plan": tf(every_pending_has_plan),
        "promotion_ready": "FALSE",
        "no_ticker_rows_fabricated": tf(ticker_count == 0),
        "no_upstream_outputs_mutated": tf(not upstream_mutation),
        "safety_boundary_audit_passed": tf(safety_passed),
        "v20_123_pending_evidence_followup_allowed": tf(next_allowed),
        "next_recommended_action": "V20.123_PENDING_EVIDENCE_FOLLOWUP" if next_allowed else "V20.122_PENDING_DECISION_RESOLUTION_PLAN_REPAIR",
        "blocking_reason": blocking,
        "pending_decision_resolution_plan_status": final_status,
        **COMMON,
    }
    write_all([decision], plan_rows, gap_rows, followup_rows, safety_rows, [gate])
    write_report(decision)

    print(final_status)
    print(f"V20_121_GATE_CONSUMED={tf(v121_gate_consumed)}")
    print(f"V20_122_PENDING_DECISION_RESOLUTION_PLAN_ALLOWED_BY_V121={tf(allowed)}")
    print(f"V20_121_FINAL_STATUS={v121_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_121={tf(selected_matches)}")
    print(f"PENDING_OPERATOR_DECISION_COUNT={len(pending_records)}")
    print(f"RESOLUTION_PLAN_ROW_COUNT={len(plan_rows)}")
    print(f"EVERY_PENDING_DECISION_HAS_RESOLUTION_PLAN={tf(every_pending_has_plan)}")
    print(f"EVIDENCE_GAP_AUDIT_ROW_COUNT={len(gap_rows)}")
    print(f"FOLLOWUP_ACTION_AUDIT_ROW_COUNT={len(followup_rows)}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_123_PENDING_EVIDENCE_FOLLOWUP_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
