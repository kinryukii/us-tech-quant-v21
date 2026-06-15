#!/usr/bin/env python
"""V20.118 promotion blocker recheck.

Rechecks promotion blockers using accumulated V20.117 shadow observations. This
stage is blocker-recheck-only, audit-only, shadow-only, and non-mutating. It is
conservative: promotion_ready remains FALSE unless every required blocker
category has explicit valid resolution evidence.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_117_MULTI_RUN_SHADOW_OBSERVATION_DECISION.csv"
IN_REGISTRY = CONSOLIDATION / "V20_117_SHADOW_OBSERVATION_RUN_REGISTRY.csv"
IN_SUMMARY = CONSOLIDATION / "V20_117_MULTI_RUN_OBSERVATION_SUMMARY.csv"
IN_CONSISTENCY = CONSOLIDATION / "V20_117_OBSERVATION_CONSISTENCY_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_117_OBSERVATION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_117_NEXT_STAGE_GATE.csv"
IN_V98_BLOCKERS = CONSOLIDATION / "V20_98_OFFICIAL_PROMOTION_BLOCKER_TRACE.csv"

OUT_DECISION = CONSOLIDATION / "V20_118_PROMOTION_BLOCKER_RECHECK_DECISION.csv"
OUT_STATUS = CONSOLIDATION / "V20_118_BLOCKER_STATUS_RECHECK_AUDIT.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_118_BLOCKER_RESOLUTION_EVIDENCE_AUDIT.csv"
OUT_REMAINING = CONSOLIDATION / "V20_118_REMAINING_BLOCKER_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_118_PROMOTION_BOUNDARY_SAFETY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_118_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_118_PROMOTION_BLOCKER_RECHECK_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V117_PASS_STATUS = "PASS_V20_117_MULTI_RUN_SHADOW_OBSERVATION_READY_FOR_V20_118"
PASS_STATUS = "PASS_V20_118_PROMOTION_BLOCKER_RECHECK_READY_FOR_V20_119"
PARTIAL_STATUS = "PARTIAL_PASS_V20_118_PROMOTION_BLOCKERS_REMAIN_READY_FOR_OPERATOR_REVIEW_PACKAGE"
BLOCKED_STATUS = "BLOCKED_V20_118_PROMOTION_BLOCKER_RECHECK"

REQUIRED_INPUTS = [IN_DECISION, IN_REGISTRY, IN_SUMMARY, IN_CONSISTENCY, IN_SAFETY, IN_GATE]
REQUIRED_BLOCKERS = [
    "multi_run_observation_sufficiency",
    "stability_regression_clearance",
    "official_promotion_policy_evidence",
    "operator_approval_evidence",
    "official_artifact_boundary_clearance",
]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    CONSOLIDATION / "V20_110_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_111_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_112_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_113_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_114_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_115_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_116_NEXT_STAGE_GATE.csv",
    CONSOLIDATION / "V20_117_NEXT_STAGE_GATE.csv",
    IN_DECISION,
    IN_REGISTRY,
]
PROHIBITED_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "performance_claim_created",
    "performance_claims_created", "performance_effectiveness_claim_created", "official_promotion_allowed", "is_official_weight",
]
COMMON_SAFETY = {
    "accepted_weight_created": "FALSE", "accepted_weights_created": "FALSE", "real_book_weight_created": "FALSE",
    "real_book_action_created": "FALSE", "official_weight_created": "FALSE", "official_weights_created": "FALSE",
    "official_ranking_created": "FALSE", "official_rankings_created": "FALSE", "official_recommendation_created": "FALSE",
    "official_recommendations_created": "FALSE", "trade_action_created": "FALSE", "trade_actions_created": "FALSE",
    "broker_action_created": "FALSE", "broker_actions_created": "FALSE", "authoritative_overwrite_created": "FALSE",
    "authoritative_overwrites_created": "FALSE", "authoritative_ranking_overwritten": "FALSE", "weight_mutated": "FALSE",
    "weight_mutations_created": "FALSE", "promotion_ready": "FALSE", "performance_claim_created": "FALSE",
    "performance_claims_created": "FALSE", "performance_effectiveness_claim_created": "FALSE",
    "official_promotion_allowed": "FALSE", "is_official_weight": "FALSE", "research_only": "TRUE",
    "shadow_only": "TRUE", "blocker_recheck_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = [
    "decision_check_id", "v20_117_gate_consumed", "v20_118_promotion_blocker_recheck_allowed_by_v117",
    "v20_117_final_status", "v20_117_status_passed", "selected_repair_scenario_id",
    "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_117",
    "observation_registry_consumed", "observation_registry_row_count", "blocker_status_recheck_created",
    "blocker_resolution_evidence_created", "remaining_blocker_audit_created", "required_blocker_count",
    "resolved_blocker_count", "remaining_blocker_count", "all_required_blockers_resolved",
    "promotion_ready", "operator_review_package_allowed", "fabricated_ticker_row_count",
    "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated",
    "shadow_only_confirmed", "blocker_recheck_only_confirmed", "audit_only_confirmed",
    "safety_boundary_audit_passed", "prohibited_action_true_count",
    "promotion_blocker_recheck_status", "blocking_reason", *COMMON_SAFETY.keys(),
]
STATUS_FIELDS = ["blocker_check_id", "selected_repair_scenario_id", "blocker_category", "prior_blocker_source", "observation_evidence_count", "explicit_resolution_evidence_present", "blocker_resolved", "blocker_status", "promotion_ready", *[k for k in COMMON_SAFETY.keys() if k != "promotion_ready"]]
EVIDENCE_FIELDS = ["evidence_check_id", "selected_repair_scenario_id", "blocker_category", "evidence_source", "evidence_summary", "valid_resolution_evidence", "evidence_status", "promotion_ready", *[k for k in COMMON_SAFETY.keys() if k != "promotion_ready"]]
REMAINING_FIELDS = ["remaining_blocker_id", "selected_repair_scenario_id", "blocker_category", "remaining_blocker", "operator_review_required", "promotion_ready", "remaining_status", *[k for k in COMMON_SAFETY.keys() if k != "promotion_ready"]]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON_SAFETY.keys()]
GATE_FIELDS = ["gate_check_id", "v20_117_gate_consumed", "v20_118_promotion_blocker_recheck_allowed_by_v117", "selected_repair_scenario_id", "promotion_blocker_recheck_decision_created", "all_required_blockers_resolved", "promotion_ready", "operator_review_package_allowed", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_119_operator_review_package_allowed", "next_recommended_action", "blocking_reason", "promotion_blocker_recheck_status", *COMMON_SAFETY.keys()]


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


def build_recheck(selected_id: str, registry: list[dict[str, str]], summary: dict[str, str], consistency: list[dict[str, str]], v98_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    obs_by_type = {clean(row.get("observation_type")): clean(row.get("observation_value")) for row in registry}
    evidence_map = {
        "multi_run_observation_sufficiency": bool(registry) and clean(summary.get("ticker_rows_created")) == "0",
        "stability_regression_clearance": obs_by_type.get("violating_exception_count") == "0" and obs_by_type.get("stable_delta_count") not in {"", "0"},
        "official_artifact_boundary_clearance": all(truthy(row.get("consistency_passed")) for row in consistency),
        "official_promotion_policy_evidence": False,
        "operator_approval_evidence": False,
    }
    prior_source = display_path(IN_V98_BLOCKERS) if v98_rows else "NO_PRIOR_PROMOTION_BLOCKER_FILE_AVAILABLE"
    status_rows = []
    evidence_rows = []
    remaining_rows = []
    for index, category in enumerate(REQUIRED_BLOCKERS, start=1):
        resolved = evidence_map[category]
        evidence_rows.append({
            "evidence_check_id": f"V20_118_BLOCKER_RESOLUTION_EVIDENCE_AUDIT_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "blocker_category": category,
            "evidence_source": "V20.117 observation registry" if resolved else prior_source,
            "evidence_summary": "Valid shadow observation evidence resolves this blocker." if resolved else "Explicit resolution evidence is not available in current shadow lineage.",
            "valid_resolution_evidence": tf(resolved),
            "evidence_status": "VALID_RESOLUTION_EVIDENCE" if resolved else "EVIDENCE_MISSING_OR_INSUFFICIENT",
            **COMMON_SAFETY,
        })
        status_rows.append({
            "blocker_check_id": f"V20_118_BLOCKER_STATUS_RECHECK_AUDIT_{index:03d}",
            "selected_repair_scenario_id": selected_id,
            "blocker_category": category,
            "prior_blocker_source": prior_source,
            "observation_evidence_count": str(len(registry)),
            "explicit_resolution_evidence_present": tf(resolved),
            "blocker_resolved": tf(resolved),
            "blocker_status": "RESOLVED" if resolved else "REMAINS_BLOCKED",
            **COMMON_SAFETY,
        })
        if not resolved:
            remaining_rows.append({
                "remaining_blocker_id": f"V20_118_REMAINING_BLOCKER_AUDIT_{len(remaining_rows) + 1:03d}",
                "selected_repair_scenario_id": selected_id,
                "blocker_category": category,
                "remaining_blocker": "Required explicit resolution evidence is absent.",
                "operator_review_required": "TRUE",
                "remaining_status": "REMAINS_FOR_OPERATOR_REVIEW",
                **COMMON_SAFETY,
            })
    return status_rows, evidence_rows, remaining_rows


def build_safety(counts: dict[str, int], passed: bool) -> list[dict[str, str]]:
    return [{
        "safety_check_id": f"V20_118_PROMOTION_BOUNDARY_SAFETY_AUDIT_{index:03d}",
        "prohibited_field": field,
        "observed_true_count": str(counts.get(field, 0)),
        "safety_boundary_passed": tf(passed),
        "safety_status": "PASS" if passed else "BLOCKED",
        "safety_reason": "V20.118 rechecks blockers only and creates no promotion, official, real-book, or execution artifacts.",
        **COMMON_SAFETY,
    } for index, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, status, evidence, remaining, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_STATUS, STATUS_FIELDS, status)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence)
    write_csv(OUT_REMAINING, REMAINING_FIELDS, remaining)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.118 Promotion Blocker Recheck Report",
        "",
        f"- wrapper_status: {decision.get('promotion_blocker_recheck_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- resolved_blocker_count: {decision.get('resolved_blocker_count')}",
        f"- remaining_blocker_count: {decision.get('remaining_blocker_count')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- operator_review_package_allowed: {decision.get('operator_review_package_allowed')}",
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
        "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT",
    ]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {"decision_check_id": "V20_118_PROMOTION_BLOCKER_RECHECK_DECISION_001", "v20_117_gate_consumed": "FALSE", "v20_118_promotion_blocker_recheck_allowed_by_v117": "FALSE", "v20_117_final_status": "", "v20_117_status_passed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_117": "FALSE", "observation_registry_consumed": "FALSE", "observation_registry_row_count": "0", "blocker_status_recheck_created": "FALSE", "blocker_resolution_evidence_created": "FALSE", "remaining_blocker_audit_created": "FALSE", "required_blocker_count": str(len(REQUIRED_BLOCKERS)), "resolved_blocker_count": "0", "remaining_blocker_count": str(len(REQUIRED_BLOCKERS)), "all_required_blockers_resolved": "FALSE", "promotion_ready": "FALSE", "operator_review_package_allowed": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "shadow_only_confirmed": "FALSE", "blocker_recheck_only_confirmed": "TRUE", "audit_only_confirmed": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "promotion_blocker_recheck_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_118_NEXT_STAGE_GATE_001", "v20_117_gate_consumed": "FALSE", "v20_118_promotion_blocker_recheck_allowed_by_v117": "FALSE", "selected_repair_scenario_id": "", "promotion_blocker_recheck_decision_created": "TRUE", "all_required_blockers_resolved": "FALSE", "promotion_ready": "FALSE", "operator_review_package_allowed": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_119_operator_review_package_allowed": "FALSE", "next_recommended_action": "V20.118_PROMOTION_BLOCKER_RECHECK_REPAIR", "blocking_reason": blocking, "promotion_blocker_recheck_status": BLOCKED_STATUS, **COMMON_SAFETY}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_117_GATE_CONSUMED=FALSE")
    print("V20_119_OPERATOR_REVIEW_PACKAGE_ALLOWED=FALSE")
    print_safety_stdout()
    print("PROMOTION_READY=FALSE")
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    registry_rows = read_csv(IN_REGISTRY)
    summary_rows = read_csv(IN_SUMMARY)
    consistency_rows = read_csv(IN_CONSISTENCY)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, registry_rows, summary_rows, consistency_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v98_rows = read_csv(IN_V98_BLOCKERS) if IN_V98_BLOCKERS.exists() and IN_V98_BLOCKERS.stat().st_size > 0 else []
    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    summary = first(summary_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v117_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_117_NEXT_STAGE_GATE_001"
    v118_allowed = truthy(gate_in.get("v20_118_promotion_blocker_recheck_allowed"))
    v117_status = clean(gate_in.get("multi_run_shadow_observation_status")) or clean(decision_in.get("multi_run_shadow_observation_status"))
    v117_status_passed = v117_status == V117_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    status_rows, evidence_rows, remaining_rows = build_recheck(selected_id, registry_rows, summary, consistency_rows, v98_rows)
    resolved_count = sum(1 for row in status_rows if truthy(row.get("blocker_resolved")))
    remaining_count = len(remaining_rows)
    all_resolved = resolved_count == len(REQUIRED_BLOCKERS)
    promotion_ready = all_resolved
    operator_review_allowed = bool(status_rows and evidence_rows) and not promotion_ready
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in registry_rows)
    counts = prohibited_counts([decision_rows, registry_rows, summary_rows, consistency_rows, safety_input_rows, gate_rows, status_rows, evidence_rows, remaining_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    recheck_success = all([v117_gate_consumed, v118_allowed, v117_status_passed, selected_matches, bool(status_rows), bool(evidence_rows), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if recheck_success and promotion_ready else PARTIAL_STATUS if recheck_success else BLOCKED_STATUS
    blocking = "" if final_status != BLOCKED_STATUS else "promotion_blocker_recheck_requirements_not_met"
    decision = {"decision_check_id": "V20_118_PROMOTION_BLOCKER_RECHECK_DECISION_001", "v20_117_gate_consumed": tf(v117_gate_consumed), "v20_118_promotion_blocker_recheck_allowed_by_v117": tf(v118_allowed), "v20_117_final_status": v117_status, "v20_117_status_passed": tf(v117_status_passed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_117": tf(selected_matches), "observation_registry_consumed": tf(bool(registry_rows)), "observation_registry_row_count": str(len(registry_rows)), "blocker_status_recheck_created": tf(bool(status_rows)), "blocker_resolution_evidence_created": tf(bool(evidence_rows)), "remaining_blocker_audit_created": "TRUE", "required_blocker_count": str(len(REQUIRED_BLOCKERS)), "resolved_blocker_count": str(resolved_count), "remaining_blocker_count": str(remaining_count), "all_required_blockers_resolved": tf(all_resolved), "promotion_ready": tf(promotion_ready), "operator_review_package_allowed": tf(operator_review_allowed or promotion_ready), "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "shadow_only_confirmed": tf(truthy(decision_in.get("shadow_only_confirmed"))), "blocker_recheck_only_confirmed": "TRUE", "audit_only_confirmed": tf(truthy(decision_in.get("audit_only_confirmed"))), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "promotion_blocker_recheck_status": final_status, "blocking_reason": blocking, **COMMON_SAFETY}
    gate = {"gate_check_id": "V20_118_NEXT_STAGE_GATE_001", "v20_117_gate_consumed": tf(v117_gate_consumed), "v20_118_promotion_blocker_recheck_allowed_by_v117": tf(v118_allowed), "selected_repair_scenario_id": selected_id, "promotion_blocker_recheck_decision_created": "TRUE", "all_required_blockers_resolved": tf(all_resolved), "promotion_ready": tf(promotion_ready), "operator_review_package_allowed": tf(operator_review_allowed or promotion_ready), "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_119_operator_review_package_allowed": tf(recheck_success), "next_recommended_action": "V20.119_OPERATOR_REVIEW_PACKAGE" if recheck_success else "V20.118_PROMOTION_BLOCKER_RECHECK_REPAIR", "blocking_reason": blocking, "promotion_blocker_recheck_status": final_status, **COMMON_SAFETY}
    write_all([decision], status_rows, evidence_rows, remaining_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_117_GATE_CONSUMED={tf(v117_gate_consumed)}")
    print(f"V20_118_PROMOTION_BLOCKER_RECHECK_ALLOWED_BY_V117={tf(v118_allowed)}")
    print(f"V20_117_FINAL_STATUS={v117_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_117={tf(selected_matches)}")
    print(f"BLOCKER_STATUS_RECHECK_CREATED={tf(bool(status_rows))}")
    print(f"BLOCKER_RESOLUTION_EVIDENCE_CREATED={tf(bool(evidence_rows))}")
    print("REMAINING_BLOCKER_AUDIT_CREATED=TRUE")
    print(f"REQUIRED_BLOCKER_COUNT={len(REQUIRED_BLOCKERS)}")
    print(f"RESOLVED_BLOCKER_COUNT={resolved_count}")
    print(f"REMAINING_BLOCKER_COUNT={remaining_count}")
    print(f"ALL_REQUIRED_BLOCKERS_RESOLVED={tf(all_resolved)}")
    print(f"PROMOTION_READY={tf(promotion_ready)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_119_OPERATOR_REVIEW_PACKAGE_ALLOWED={tf(recheck_success)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
