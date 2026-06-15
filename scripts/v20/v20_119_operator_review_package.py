#!/usr/bin/env python
"""V20.119 operator review package.

Builds an audit-only operator review package for the selected repair scenario
and remaining V20.118 promotion blockers. This stage is review-package-only,
non-mutating, and never marks promotion ready.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_118_PROMOTION_BLOCKER_RECHECK_DECISION.csv"
IN_STATUS = CONSOLIDATION / "V20_118_BLOCKER_STATUS_RECHECK_AUDIT.csv"
IN_EVIDENCE = CONSOLIDATION / "V20_118_BLOCKER_RESOLUTION_EVIDENCE_AUDIT.csv"
IN_REMAINING = CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_118_PROMOTION_BOUNDARY_SAFETY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_118_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_PACKAGE_DECISION.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_BLOCKER_SUMMARY.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_EVIDENCE_MANIFEST.csv"
OUT_REQUIRED = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv"
OUT_SAFETY = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_119_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_119_OPERATOR_REVIEW_PACKAGE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V118_ALLOWED_STATUSES = {
    "PARTIAL_PASS_V20_118_PROMOTION_BLOCKERS_REMAIN_READY_FOR_OPERATOR_REVIEW_PACKAGE",
    "PASS_V20_118_PROMOTION_BLOCKER_RECHECK_READY_FOR_V20_119",
}
PASS_STATUS = "PASS_V20_119_OPERATOR_REVIEW_PACKAGE_READY_FOR_V20_120"
BLOCKED_STATUS = "BLOCKED_V20_119_OPERATOR_REVIEW_PACKAGE"

REQUIRED_INPUTS = [IN_DECISION, IN_STATUS, IN_EVIDENCE, IN_REMAINING, IN_SAFETY, IN_GATE]
SUPPORTING_ARTIFACTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_116_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_117_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_118_NEXT_STAGE_GATE.csv",
    IN_DECISION,
    IN_STATUS,
    IN_EVIDENCE,
    IN_REMAINING,
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
COMMON_SAFETY = {
    "accepted_weight_created": "FALSE", "accepted_weights_created": "FALSE", "real_book_weight_created": "FALSE",
    "real_book_action_created": "FALSE", "official_weight_created": "FALSE", "official_weights_created": "FALSE",
    "official_ranking_created": "FALSE", "official_rankings_created": "FALSE", "official_recommendation_created": "FALSE",
    "official_recommendations_created": "FALSE", "trade_action_created": "FALSE", "trade_actions_created": "FALSE",
    "broker_action_created": "FALSE", "broker_actions_created": "FALSE", "authoritative_overwrite_created": "FALSE",
    "authoritative_overwrites_created": "FALSE", "authoritative_ranking_overwritten": "FALSE", "weight_mutated": "FALSE",
    "weight_mutations_created": "FALSE", "performance_claim_created": "FALSE", "performance_claims_created": "FALSE",
    "performance_effectiveness_claim_created": "FALSE", "official_promotion_allowed": "FALSE",
    "is_official_weight": "FALSE", "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE",
    "operator_review_package_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id", "v20_118_gate_consumed", "v20_119_operator_review_package_allowed_by_v118",
    "v20_118_final_status", "v20_118_status_allowed", "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_118",
    "blocker_summary_created", "blocker_summary_row_count", "evidence_manifest_created",
    "evidence_manifest_row_count", "required_decisions_created", "required_decision_row_count",
    "unresolved_blocker_count", "unresolved_blockers_carried_forward", "promotion_ready",
    "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected",
    "no_upstream_outputs_mutated", "shadow_only_confirmed", "operator_review_package_only_confirmed",
    "audit_only_confirmed", "safety_boundary_audit_passed", "prohibited_action_true_count",
    "operator_review_package_complete", "v20_120_operator_decision_record_allowed",
    "operator_review_package_status", "blocking_reason", *COMMON_SAFETY.keys(),
]
SUMMARY_FIELDS = ["summary_id", "selected_repair_scenario_id", "blocker_category", "blocker_resolved", "blocker_status", "evidence_source", "operator_review_required", "promotion_ready", *[k for k in COMMON_SAFETY.keys() if k != "promotion_ready"]]
MANIFEST_FIELDS = ["manifest_entry_id", "selected_repair_scenario_id", "artifact_path", "artifact_role", "artifact_exists", "evidence_traceable", "official_artifact", "real_book_artifact", "promotion_ready", *[k for k in COMMON_SAFETY.keys() if k != "promotion_ready"]]
REQUIRED_FIELDS = ["required_decision_id", "selected_repair_scenario_id", "blocker_category", "required_operator_decision", "decision_required", "promotion_ready", "decision_status", *[k for k in COMMON_SAFETY.keys() if k != "promotion_ready"]]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON_SAFETY.keys()]
GATE_FIELDS = ["gate_check_id", "v20_118_gate_consumed", "v20_119_operator_review_package_allowed_by_v118", "selected_repair_scenario_id", "operator_review_package_decision_created", "operator_review_package_complete", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_120_operator_decision_record_allowed", "next_recommended_action", "blocking_reason", "operator_review_package_status", *COMMON_SAFETY.keys()]


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
    return {display_path(path): digest(path) for path in SUPPORTING_ARTIFACTS if path.exists()}


def prohibited_counts(groups: list[list[dict[str, str]]]) -> dict[str, int]:
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    for rows in groups:
        for row in rows:
            for field in PROHIBITED_FIELDS:
                if field in row and truthy(row.get(field)):
                    counts[field] += 1
    return counts


def build_summary(selected_id: str, status_rows: list[dict[str, str]], evidence_rows: list[dict[str, str]], remaining_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    evidence_by_category = {clean(row.get("blocker_category")): clean(row.get("evidence_source")) for row in evidence_rows}
    remaining = {clean(row.get("blocker_category")) for row in remaining_rows}
    rows = []
    for index, row in enumerate(status_rows, start=1):
        category = clean(row.get("blocker_category"))
        rows.append({
            "summary_id": f"V20_119_OPERATOR_REVIEW_BLOCKER_SUMMARY_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "blocker_category": category,
            "blocker_resolved": clean(row.get("blocker_resolved")),
            "blocker_status": clean(row.get("blocker_status")),
            "evidence_source": evidence_by_category.get(category, ""),
            "operator_review_required": tf(category in remaining),
            **COMMON_SAFETY,
        })
    return rows


def build_manifest(selected_id: str) -> list[dict[str, str]]:
    rows = []
    for index, path in enumerate(SUPPORTING_ARTIFACTS, start=1):
        rows.append({
            "manifest_entry_id": f"V20_119_OPERATOR_REVIEW_EVIDENCE_MANIFEST_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "artifact_path": display_path(path),
            "artifact_role": "supporting_shadow_lineage_or_blocker_evidence",
            "artifact_exists": tf(path.exists()),
            "evidence_traceable": tf(path.exists()),
            "official_artifact": "FALSE",
            "real_book_artifact": "FALSE",
            **COMMON_SAFETY,
        })
    return rows


def build_required(selected_id: str, remaining_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{
        "required_decision_id": f"V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS_{index:03d}",
        "selected_repair_scenario_id": selected_id,
        "blocker_category": clean(row.get("blocker_category")),
        "required_operator_decision": "Operator must decide whether additional evidence or remediation is required before any promotion path can continue.",
        "decision_required": "TRUE",
        "decision_status": "AWAITING_OPERATOR_REVIEW",
        **COMMON_SAFETY,
    } for index, row in enumerate(remaining_rows, start=1)]


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_119_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.119 creates an operator review package only and keeps promotion_ready FALSE.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, summary, manifest, required, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
    write_csv(OUT_MANIFEST, MANIFEST_FIELDS, manifest)
    write_csv(OUT_REQUIRED, REQUIRED_FIELDS, required)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.119 Operator Review Package Report",
        "",
        f"- wrapper_status: {decision.get('operator_review_package_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- unresolved_blocker_count: {decision.get('unresolved_blocker_count')}",
        f"- required_decision_row_count: {decision.get('required_decision_row_count')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_120_operator_decision_record_allowed: {decision.get('v20_120_operator_decision_record_allowed')}",
        "- official_recommendation_created: FALSE",
        "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in [
        "ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED",
        "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED",
        "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED",
        "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED",
        "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED",
        "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED",
        "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {"decision_check_id": "V20_119_OPERATOR_REVIEW_PACKAGE_DECISION_001", "v20_118_gate_consumed": "FALSE", "v20_119_operator_review_package_allowed_by_v118": "FALSE", "v20_118_final_status": "", "v20_118_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_118": "FALSE", "blocker_summary_created": "FALSE", "blocker_summary_row_count": "0", "evidence_manifest_created": "FALSE", "evidence_manifest_row_count": "0", "required_decisions_created": "FALSE", "required_decision_row_count": "0", "unresolved_blocker_count": "0", "unresolved_blockers_carried_forward": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "shadow_only_confirmed": "FALSE", "operator_review_package_only_confirmed": "TRUE", "audit_only_confirmed": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "operator_review_package_complete": "FALSE", "v20_120_operator_decision_record_allowed": "FALSE", "operator_review_package_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_119_NEXT_STAGE_GATE_001", "v20_118_gate_consumed": "FALSE", "v20_119_operator_review_package_allowed_by_v118": "FALSE", "selected_repair_scenario_id": "", "operator_review_package_decision_created": "TRUE", "operator_review_package_complete": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_120_operator_decision_record_allowed": "FALSE", "next_recommended_action": "V20.119_OPERATOR_REVIEW_PACKAGE_REPAIR", "blocking_reason": blocking, "operator_review_package_status": BLOCKED_STATUS, **COMMON_SAFETY}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_118_GATE_CONSUMED=FALSE")
    print("V20_120_OPERATOR_DECISION_RECORD_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    status_rows = read_csv(IN_STATUS)
    evidence_rows = read_csv(IN_EVIDENCE)
    remaining_rows = read_csv(IN_REMAINING)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, status_rows, evidence_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v118_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_118_NEXT_STAGE_GATE_001"
    v119_allowed = truthy(gate_in.get("v20_119_operator_review_package_allowed"))
    v118_status = clean(gate_in.get("promotion_blocker_recheck_status")) or clean(decision_in.get("promotion_blocker_recheck_status"))
    v118_status_allowed = v118_status in V118_ALLOWED_STATUSES
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    summary = build_summary(selected_id, status_rows, evidence_rows, remaining_rows)
    manifest = build_manifest(selected_id)
    required = build_required(selected_id, remaining_rows)
    counts = prohibited_counts([decision_rows, status_rows, evidence_rows, remaining_rows, safety_input_rows, gate_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety = build_safety(counts, safety_passed)
    unresolved_count = len(remaining_rows)
    ticker_count = 0
    complete = all([v118_gate_consumed, v119_allowed, v118_status_allowed, selected_matches, bool(summary), bool(manifest), bool(required) == (unresolved_count > 0), unresolved_count == len(required), not upstream_mutation, safety_passed, prohibited_count == 0])
    status = PASS_STATUS if complete else BLOCKED_STATUS
    blocking = "" if complete else "operator_review_package_requirements_not_met"
    decision = {"decision_check_id": "V20_119_OPERATOR_REVIEW_PACKAGE_DECISION_001", "v20_118_gate_consumed": tf(v118_gate_consumed), "v20_119_operator_review_package_allowed_by_v118": tf(v119_allowed), "v20_118_final_status": v118_status, "v20_118_status_allowed": tf(v118_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_118": tf(selected_matches), "blocker_summary_created": tf(bool(summary)), "blocker_summary_row_count": str(len(summary)), "evidence_manifest_created": tf(bool(manifest)), "evidence_manifest_row_count": str(len(manifest)), "required_decisions_created": tf(bool(required)), "required_decision_row_count": str(len(required)), "unresolved_blocker_count": str(unresolved_count), "unresolved_blockers_carried_forward": tf(unresolved_count == len(required)), "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "shadow_only_confirmed": tf(truthy(decision_in.get("shadow_only_confirmed"))), "operator_review_package_only_confirmed": "TRUE", "audit_only_confirmed": tf(truthy(decision_in.get("audit_only_confirmed"))), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "operator_review_package_complete": tf(complete), "v20_120_operator_decision_record_allowed": tf(complete), "operator_review_package_status": status, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_119_NEXT_STAGE_GATE_001", "v20_118_gate_consumed": tf(v118_gate_consumed), "v20_119_operator_review_package_allowed_by_v118": tf(v119_allowed), "selected_repair_scenario_id": selected_id, "operator_review_package_decision_created": "TRUE", "operator_review_package_complete": tf(complete), "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_120_operator_decision_record_allowed": tf(complete), "next_recommended_action": "V20.120_OPERATOR_DECISION_RECORD" if complete else "V20.119_OPERATOR_REVIEW_PACKAGE_REPAIR", "blocking_reason": blocking, "operator_review_package_status": status, **COMMON_SAFETY}
    write_all([decision], summary, manifest, required, safety, [gate])
    write_report(decision)
    print(status)
    print(f"V20_118_GATE_CONSUMED={tf(v118_gate_consumed)}")
    print(f"V20_119_OPERATOR_REVIEW_PACKAGE_ALLOWED_BY_V118={tf(v119_allowed)}")
    print(f"V20_118_FINAL_STATUS={v118_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_118={tf(selected_matches)}")
    print(f"BLOCKER_SUMMARY_CREATED={tf(bool(summary))}")
    print(f"EVIDENCE_MANIFEST_CREATED={tf(bool(manifest))}")
    print(f"REQUIRED_DECISIONS_CREATED={tf(bool(required))}")
    print(f"UNRESOLVED_BLOCKER_COUNT={unresolved_count}")
    print("PROMOTION_READY=FALSE")
    print("FABRICATED_TICKER_ROW_COUNT=0")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_120_OPERATOR_DECISION_RECORD_ALLOWED={tf(complete)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
