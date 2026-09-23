#!/usr/bin/env python
"""V20.137 second-round operator review packet.

Builds operator-readable second-round review packets for blockers whose
second-round evidence is covered for review. This stage is review-packet-only,
audit-only, non-mutating, and never marks promotion ready.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_136_SECOND_ROUND_EVIDENCE_RECONCILIATION_DECISION.csv"
IN_PLAN_RECON = CONSOLIDATION / "V20_136_SECOND_ROUND_PLAN_RECONCILIATION_AUDIT.csv"
IN_RESULT_RECON = CONSOLIDATION / "V20_136_SECOND_ROUND_RESULT_RECONCILIATION_AUDIT.csv"
IN_COVERAGE = CONSOLIDATION / "V20_136_SECOND_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_136_SECOND_ROUND_EVIDENCE_RECONCILIATION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_136_NEXT_STAGE_GATE.csv"
IN_DRY_RESULT = CONSOLIDATION / "V20_135_SECOND_ROUND_EVIDENCE_RESULT_AUDIT.csv"
IN_DRY_GAP = CONSOLIDATION / "V20_135_SECOND_ROUND_EVIDENCE_GAP_STATUS_AUDIT.csv"
IN_PLAN = CONSOLIDATION / "V20_134_SECOND_ROUND_EVIDENCE_PLAN.csv"
IN_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"

OUT_DECISION = CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET.csv"
OUT_SUMMARY = CONSOLIDATION / "V20_137_SECOND_ROUND_REVIEW_SUMMARY_AUDIT.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_137_SECOND_ROUND_REVIEW_OPTIONS_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_137_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V136_REQUIRED_STATUS = "PASS_V20_136_SECOND_ROUND_EVIDENCE_RECONCILIATION_READY_FOR_V20_137"
PASS_STATUS = "PASS_V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_READY_FOR_V20_138"
BLOCKED_STATUS = "BLOCKED_V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET"
ACTION_OPTIONS = ["ACCEPT_SECOND_ROUND_EVIDENCE_WITH_LIMITATION", "REJECT_SECOND_ROUND_EVIDENCE_KEEP_BLOCKED", "REQUEST_THIRD_ROUND_EVIDENCE"]
DEFAULT_ACTION = "REQUEST_THIRD_ROUND_EVIDENCE"
COVERED_STATUS = "SECOND_ROUND_COVERED_BY_EVIDENCE_FOR_REVIEW"

REQUIRED_INPUTS = [IN_DECISION, IN_PLAN_RECON, IN_RESULT_RECON, IN_COVERAGE, IN_SAFETY, IN_GATE, IN_DRY_RESULT, IN_DRY_GAP, IN_PLAN, IN_REMAINING]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120", "121", "122", "123", "124", "125", "126", "127", "128", "129", "130", "131", "132", "133", "134", "135", "136"]],
    IN_DECISION, IN_PLAN_RECON, IN_RESULT_RECON, IN_COVERAGE, IN_SAFETY, IN_DRY_RESULT, IN_DRY_GAP, IN_PLAN, IN_REMAINING,
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE",
    "second_round_operator_review_packet_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_136_gate_consumed", "v20_137_second_round_operator_review_packet_allowed_by_v136", "v20_136_final_status", "v20_136_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_136", "covered_second_round_blocker_count", "second_round_operator_review_packet_row_count", "every_covered_second_round_blocker_has_review_packet", "second_round_review_summary_audit_row_count", "second_round_review_options_audit_row_count", "all_packet_rows_include_required_options", "all_packet_rows_default_request_third_round_evidence", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_138_second_round_operator_decision_capture_allowed", "second_round_operator_review_packet_status", "blocking_reason", *COMMON.keys()]
PACKET_FIELDS = ["second_round_operator_review_packet_id", "selected_repair_scenario_id", "source_second_round_blocker_coverage_audit_id", "source_remaining_evidence_blocker_status_id", "source_second_round_evidence_plan_id", "source_second_round_evidence_result_audit_id", "source_operator_decision_record_id", "blocker_category", "current_blocker_status", "second_round_evidence_coverage_status", "second_round_evidence_source_artifacts", "second_round_dry_run_result_summary", "remaining_limitation_summary", "operator_review_question", "available_review_options", "conservative_default", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
SUMMARY_FIELDS = ["second_round_review_summary_audit_id", "selected_repair_scenario_id", "source_second_round_operator_review_packet_id", "source_second_round_blocker_coverage_audit_id", "blocker_category", "second_round_evidence_coverage_status", "second_round_dry_run_result_status", "second_round_review_summary", "operator_review_required", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
OPTIONS_FIELDS = ["second_round_review_options_audit_id", "selected_repair_scenario_id", "source_second_round_operator_review_packet_id", "blocker_category", "review_option", "option_available", "option_consequence", "recommended_default", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_136_gate_consumed", "v20_137_second_round_operator_review_packet_allowed_by_v136", "selected_repair_scenario_id", "second_round_operator_review_packet_created", "every_covered_second_round_blocker_has_review_packet", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_138_second_round_operator_decision_capture_allowed", "next_recommended_action", "blocking_reason", "second_round_operator_review_packet_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_137_SECOND_ROUND_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.137 creates only second-round operator review packet artifacts and keeps all acceptance and promotion flags false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, packet, summary, options, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
    write_csv(OUT_OPTIONS, OPTIONS_FIELDS, options)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.137 Second-Round Operator Review Packet Report", "",
        f"- wrapper_status: {decision.get('second_round_operator_review_packet_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- covered_second_round_blocker_count: {decision.get('covered_second_round_blocker_count')}",
        f"- second_round_operator_review_packet_row_count: {decision.get('second_round_operator_review_packet_row_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_138_second_round_operator_decision_capture_allowed: {decision.get('v20_138_second_round_operator_decision_capture_allowed')}",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_DECISION_001", "v20_136_gate_consumed": "FALSE", "v20_137_second_round_operator_review_packet_allowed_by_v136": "FALSE", "v20_136_final_status": "", "v20_136_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_136": "FALSE", "covered_second_round_blocker_count": "0", "second_round_operator_review_packet_row_count": "0", "every_covered_second_round_blocker_has_review_packet": "FALSE", "second_round_review_summary_audit_row_count": "0", "second_round_review_options_audit_row_count": "0", "all_packet_rows_include_required_options": "FALSE", "all_packet_rows_default_request_third_round_evidence": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_138_second_round_operator_decision_capture_allowed": "FALSE", "second_round_operator_review_packet_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_137_NEXT_STAGE_GATE_001", "v20_136_gate_consumed": "FALSE", "v20_137_second_round_operator_review_packet_allowed_by_v136": "FALSE", "selected_repair_scenario_id": "", "second_round_operator_review_packet_created": "TRUE", "every_covered_second_round_blocker_has_review_packet": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_138_second_round_operator_decision_capture_allowed": "FALSE", "next_recommended_action": "V20.137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_REPAIR", "blocking_reason": blocking, "second_round_operator_review_packet_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_136_GATE_CONSUMED=FALSE")
    print("V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def option_consequence(option: str) -> str:
    if option == "ACCEPT_SECOND_ROUND_EVIDENCE_WITH_LIMITATION":
        return "Would require explicit valid human evidence acceptance in a later stage; V20.137 does not accept it."
    if option == "REJECT_SECOND_ROUND_EVIDENCE_KEEP_BLOCKED":
        return "Keeps the blocker blocked and prevents promotion readiness."
    return "Requests third-round evidence and keeps the blocker pending."


def build_packet_artifacts(selected_id: str, covered_rows: list[dict[str, str]], dry_result_rows: list[dict[str, str]], dry_gap_rows: list[dict[str, str]], plan_rows: list[dict[str, str]], remaining_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    result_by_id = {clean(row.get("second_round_evidence_result_audit_id")): row for row in dry_result_rows}
    gap_by_plan = {clean(row.get("source_second_round_evidence_plan_id")): row for row in dry_gap_rows}
    plan_by_id = {clean(row.get("second_round_evidence_plan_id")): row for row in plan_rows}
    remaining_by_id = {clean(row.get("remaining_evidence_blocker_status_id")): row for row in remaining_rows}
    packet_rows = []
    summary_rows = []
    option_rows = []
    for i, coverage in enumerate(covered_rows, start=1):
        plan_id = clean(coverage.get("source_second_round_evidence_plan_id"))
        result_id = clean(coverage.get("source_second_round_evidence_result_audit_id"))
        remaining_id = clean(coverage.get("source_remaining_evidence_blocker_status_id"))
        result = result_by_id.get(result_id, {})
        plan = plan_by_id.get(plan_id, {})
        gap = gap_by_plan.get(plan_id, {})
        remaining = remaining_by_id.get(remaining_id, {})
        packet_id = f"V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_{i:03d}"
        artifacts = ";".join(filter(None, [
            "outputs/v20/consolidation/V20_136_SECOND_ROUND_BLOCKER_COVERAGE_AUDIT.csv",
            "outputs/v20/consolidation/V20_135_SECOND_ROUND_EVIDENCE_RESULT_AUDIT.csv",
            plan_id,
        ]))
        dry_summary = clean(result.get("dry_run_result_summary")) or "Second-round dry-run evidence is available for review only; no explicit human evidence acceptance was created."
        limitation = "Second-round evidence remains dry-run-only and cannot create evidence acceptance, operator acceptance, or promotion readiness without explicit valid human acceptance."
        packet_rows.append({
            "second_round_operator_review_packet_id": packet_id,
            "selected_repair_scenario_id": selected_id,
            "source_second_round_blocker_coverage_audit_id": clean(coverage.get("second_round_blocker_coverage_audit_id")),
            "source_remaining_evidence_blocker_status_id": remaining_id,
            "source_second_round_evidence_plan_id": plan_id,
            "source_second_round_evidence_result_audit_id": result_id,
            "source_operator_decision_record_id": clean(remaining.get("source_operator_decision_record_id")),
            "blocker_category": clean(coverage.get("blocker_category")),
            "current_blocker_status": clean(remaining.get("blocker_status")) or "UNRESOLVED_OR_PENDING_REVIEW",
            "second_round_evidence_coverage_status": clean(coverage.get("coverage_status")),
            "second_round_evidence_source_artifacts": artifacts,
            "second_round_dry_run_result_summary": dry_summary,
            "remaining_limitation_summary": limitation,
            "operator_review_question": "Should the second-round dry-run evidence be accepted with limitation, rejected while keeping the blocker blocked, or should third-round evidence be requested?",
            "available_review_options": ";".join(ACTION_OPTIONS),
            "conservative_default": DEFAULT_ACTION,
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        summary_rows.append({
            "second_round_review_summary_audit_id": f"V20_137_SECOND_ROUND_REVIEW_SUMMARY_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_second_round_operator_review_packet_id": packet_id,
            "source_second_round_blocker_coverage_audit_id": clean(coverage.get("second_round_blocker_coverage_audit_id")),
            "blocker_category": clean(coverage.get("blocker_category")),
            "second_round_evidence_coverage_status": clean(coverage.get("coverage_status")),
            "second_round_dry_run_result_status": clean(result.get("dry_run_result_status")),
            "second_round_review_summary": f"{dry_summary} {clean(gap.get('gap_status_reason'))}",
            "operator_review_required": "TRUE",
            "evidence_acceptance": "FALSE",
            "operator_acceptance": "FALSE",
            "promotion_ready": "FALSE",
            **COMMON,
        })
        for option in ACTION_OPTIONS:
            option_rows.append({
                "second_round_review_options_audit_id": f"V20_137_SECOND_ROUND_REVIEW_OPTIONS_AUDIT_{len(option_rows)+1:03d}",
                "selected_repair_scenario_id": selected_id,
                "source_second_round_operator_review_packet_id": packet_id,
                "blocker_category": clean(coverage.get("blocker_category")),
                "review_option": option,
                "option_available": "TRUE",
                "option_consequence": option_consequence(option),
                "recommended_default": tf(option == DEFAULT_ACTION),
                "evidence_acceptance": "FALSE",
                "operator_acceptance": "FALSE",
                "promotion_ready": "FALSE",
                **COMMON,
            })
    return packet_rows, summary_rows, option_rows


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    plan_recon_rows = read_csv(IN_PLAN_RECON)
    result_recon_rows = read_csv(IN_RESULT_RECON)
    coverage_rows = read_csv(IN_COVERAGE)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    dry_result_rows = read_csv(IN_DRY_RESULT)
    dry_gap_rows = read_csv(IN_DRY_GAP)
    plan_rows = read_csv(IN_PLAN)
    remaining_rows = read_csv(IN_REMAINING)
    if not all([decision_rows, plan_recon_rows, result_recon_rows, coverage_rows, safety_input_rows, gate_rows, dry_result_rows, dry_gap_rows, plan_rows, remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v136_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_136_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_137_second_round_operator_review_packet_allowed"))
    v136_status = clean(gate_in.get("second_round_evidence_reconciliation_status")) or clean(decision_in.get("second_round_evidence_reconciliation_status"))
    v136_status_allowed = v136_status == V136_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    covered_rows = [row for row in coverage_rows if clean(row.get("coverage_status")) == COVERED_STATUS]
    packet_rows, summary_rows, option_rows = build_packet_artifacts(selected_id, covered_rows, dry_result_rows, dry_gap_rows, plan_rows, remaining_rows)

    covered_ids = {clean(row.get("second_round_blocker_coverage_audit_id")) for row in covered_rows}
    packet_ids = {clean(row.get("source_second_round_blocker_coverage_audit_id")) for row in packet_rows}
    every_covered_has_packet = bool(covered_rows) and len(packet_rows) == len(covered_rows) and packet_ids == covered_ids
    required_options = set(ACTION_OPTIONS)
    all_include_options = all(set(clean(row.get("available_review_options")).split(";")) == required_options for row in packet_rows)
    all_default = all(clean(row.get("conservative_default")) == DEFAULT_ACTION for row in packet_rows)
    summary_complete = bool(summary_rows) and {clean(row.get("source_second_round_operator_review_packet_id")) for row in summary_rows} == {clean(row.get("second_round_operator_review_packet_id")) for row in packet_rows}
    options_by_packet = {}
    for row in option_rows:
        options_by_packet.setdefault(clean(row.get("source_second_round_operator_review_packet_id")), set()).add(clean(row.get("review_option")))
    options_complete = bool(option_rows) and all(options_by_packet.get(clean(row.get("second_round_operator_review_packet_id"))) == required_options for row in packet_rows)
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in plan_recon_rows + packet_rows)
    counts = prohibited_counts([decision_rows, plan_recon_rows, result_recon_rows, coverage_rows, safety_input_rows, gate_rows, dry_result_rows, dry_gap_rows, plan_rows, remaining_rows, packet_rows, summary_rows, option_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v136_gate_consumed, allowed, v136_status_allowed, selected_matches, every_covered_has_packet, summary_complete, options_complete, all_include_options, all_default, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "second_round_operator_review_packet_requirements_not_met"

    decision = {"decision_check_id": "V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_DECISION_001", "v20_136_gate_consumed": tf(v136_gate_consumed), "v20_137_second_round_operator_review_packet_allowed_by_v136": tf(allowed), "v20_136_final_status": v136_status, "v20_136_status_allowed": tf(v136_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_136": tf(selected_matches), "covered_second_round_blocker_count": str(len(covered_rows)), "second_round_operator_review_packet_row_count": str(len(packet_rows)), "every_covered_second_round_blocker_has_review_packet": tf(every_covered_has_packet), "second_round_review_summary_audit_row_count": str(len(summary_rows)), "second_round_review_options_audit_row_count": str(len(option_rows)), "all_packet_rows_include_required_options": tf(all_include_options), "all_packet_rows_default_request_third_round_evidence": tf(all_default), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_138_second_round_operator_decision_capture_allowed": tf(next_allowed), "second_round_operator_review_packet_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_137_NEXT_STAGE_GATE_001", "v20_136_gate_consumed": tf(v136_gate_consumed), "v20_137_second_round_operator_review_packet_allowed_by_v136": tf(allowed), "selected_repair_scenario_id": selected_id, "second_round_operator_review_packet_created": "TRUE", "every_covered_second_round_blocker_has_review_packet": tf(every_covered_has_packet), "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_138_second_round_operator_decision_capture_allowed": tf(next_allowed), "next_recommended_action": "V20.138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE" if next_allowed else "V20.137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_REPAIR", "blocking_reason": blocking, "second_round_operator_review_packet_status": final_status, **COMMON}
    write_all([decision], packet_rows, summary_rows, option_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_136_GATE_CONSUMED={tf(v136_gate_consumed)}")
    print(f"V20_137_SECOND_ROUND_OPERATOR_REVIEW_PACKET_ALLOWED_BY_V136={tf(allowed)}")
    print(f"V20_136_FINAL_STATUS={v136_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_136={tf(selected_matches)}")
    print(f"COVERED_SECOND_ROUND_BLOCKER_COUNT={len(covered_rows)}")
    print(f"SECOND_ROUND_OPERATOR_REVIEW_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"EVERY_COVERED_SECOND_ROUND_BLOCKER_HAS_REVIEW_PACKET={tf(every_covered_has_packet)}")
    print(f"SECOND_ROUND_REVIEW_SUMMARY_AUDIT_ROW_COUNT={len(summary_rows)}")
    print(f"SECOND_ROUND_REVIEW_OPTIONS_AUDIT_ROW_COUNT={len(option_rows)}")
    print(f"ALL_PACKET_ROWS_INCLUDE_REQUIRED_OPTIONS={tf(all_include_options)}")
    print(f"ALL_PACKET_ROWS_DEFAULT_REQUEST_THIRD_ROUND_EVIDENCE={tf(all_default)}")
    print("EVIDENCE_ACCEPTANCE=FALSE")
    print("OPERATOR_ACCEPTANCE=FALSE")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_138_SECOND_ROUND_OPERATOR_DECISION_CAPTURE_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
