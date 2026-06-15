#!/usr/bin/env python
"""V20.148 promotion-readiness operator review.

Creates an operator-review layer for the V20.147 promotion-readiness packet.
This stage is review-only and audit-only. It does not auto-approve promotion
readiness or create official, real-book, trade, broker, overwrite, mutation, or
performance artifacts.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET_DECISION.csv"
IN_PACKET = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET.csv"
IN_MANIFEST = CONSOLIDATION / "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv"
IN_LIMITATION = CONSOLIDATION / "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv"
IN_SAFETY = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_147_NEXT_STAGE_GATE.csv"
IN_CRITERIA = CONSOLIDATION / "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv"
IN_DISPOSITION = CONSOLIDATION / "V20_146_BLOCKER_DISPOSITION_AUDIT.csv"
IN_V145_RECORD = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv"

OUT_DECISION = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET.csv"
OUT_OPTIONS = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT.csv"
OUT_REQUIRED = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS.csv"
OUT_SAFETY = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_148_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V147_REQUIRED_STATUS = "PASS_V20_147_PROMOTION_READINESS_PACKET_READY_FOR_V20_148"
PARTIAL_STATUS = "PARTIAL_PASS_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT"
BLOCKED_STATUS = "BLOCKED_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW"
PACKET_SCOPE = "PROMOTION_READINESS_PACKET_ONLY_NOT_OFFICIAL_PROMOTION"
NEXT_REVIEW_ACTION = "OPERATOR_REVIEW_OF_PROMOTION_READINESS_PACKET"
DEFAULT_ACTION = "AWAITING_EXPLICIT_OPERATOR_PROMOTION_READINESS_REVIEW"
OPERATOR_ACTIONS = [
    "APPROVE_PROMOTION_READINESS_FOR_STAGING",
    "REJECT_PROMOTION_READINESS_KEEP_RESEARCH_ONLY",
    "REQUEST_PROMOTION_READINESS_REMEDIATION",
]

REQUIRED_INPUTS = [IN_DECISION, IN_PACKET, IN_MANIFEST, IN_LIMITATION, IN_SAFETY, IN_GATE, IN_CRITERIA, IN_DISPOSITION, IN_V145_RECORD]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 148))
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
    "promotion_readiness_operator_review_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_147_gate_consumed", "v20_148_promotion_readiness_operator_review_allowed_by_v147", "v20_147_final_status", "v20_147_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_147", "promotion_readiness_packet_row_count", "operator_review_packet_row_count", "operator_review_options_audit_row_count", "operator_required_actions_row_count", "packet_requirements_met", "operator_actions_complete", "default_operator_action_valid", "operator_action_auto_selected_count", "no_operator_action_auto_selected", "operator_input_required_before_v20_149", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_149_promotion_readiness_operator_decision_capture_allowed", "promotion_readiness_operator_review_status", "blocking_reason", *COMMON.keys()]
PACKET_FIELDS = ["promotion_readiness_operator_review_packet_id", "selected_repair_scenario_id", "source_promotion_readiness_packet_id", "promotion_readiness_recheck_passed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "accepted_limitation_count", "evidence_manifest_row_count", "criteria_pass_count", "criteria_fail_count", "remaining_limitation_summary", "operator_review_question", "allowed_operator_actions", "default_operator_action", "selected_operator_action", "operator_action_auto_selected", "operator_input_required_before_v20_149", "ticker_rows_created", *COMMON.keys()]
OPTIONS_FIELDS = ["promotion_readiness_operator_review_options_audit_id", "selected_repair_scenario_id", "source_promotion_readiness_operator_review_packet_id", "operator_action_option", "option_available", "option_requires_explicit_operator_input", "option_auto_selected", "option_consequence", "promotion_ready", *COMMON.keys()]
REQUIRED_FIELDS = ["promotion_readiness_operator_required_action_id", "selected_repair_scenario_id", "source_promotion_readiness_operator_review_packet_id", "required_operator_decision", "allowed_operator_actions", "operator_action_selected", "selected_operator_action", "operator_input_required_before_v20_149", "promotion_readiness_decision_capture_allowed_before_input", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_147_gate_consumed", "v20_148_promotion_readiness_operator_review_allowed_by_v147", "selected_repair_scenario_id", "promotion_readiness_operator_review_created", "operator_input_required_before_v20_149", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_149_promotion_readiness_operator_decision_capture_allowed", "next_recommended_action", "blocking_reason", "promotion_readiness_operator_review_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.148 creates only an operator review layer and does not auto-select or create official/operational artifacts.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, packet, options, required, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_OPTIONS, OPTIONS_FIELDS, options)
    write_csv(OUT_REQUIRED, REQUIRED_FIELDS, required)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.148 Promotion Readiness Operator Review Report", "",
        f"- wrapper_status: {decision.get('promotion_readiness_operator_review_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- operator_review_packet_row_count: {decision.get('operator_review_packet_row_count')}",
        f"- operator_review_options_audit_row_count: {decision.get('operator_review_options_audit_row_count')}",
        f"- operator_input_required_before_v20_149: {decision.get('operator_input_required_before_v20_149')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_149_promotion_readiness_operator_decision_capture_allowed: {decision.get('v20_149_promotion_readiness_operator_decision_capture_allowed')}",
        "",
        "V20.149 must wait for explicit operator input before capturing a promotion-readiness decision.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_WEIGHT_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "TRADE_ACTION_CREATED", "BROKER_ACTION_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "WEIGHT_MUTATED", "PERFORMANCE_CLAIM_CREATED", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION_001", "v20_147_gate_consumed": "FALSE", "v20_148_promotion_readiness_operator_review_allowed_by_v147": "FALSE", "v20_147_final_status": "", "v20_147_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_147": "FALSE", "promotion_readiness_packet_row_count": "0", "operator_review_packet_row_count": "0", "operator_review_options_audit_row_count": "0", "operator_required_actions_row_count": "0", "packet_requirements_met": "FALSE", "operator_actions_complete": "FALSE", "default_operator_action_valid": "FALSE", "operator_action_auto_selected_count": "0", "no_operator_action_auto_selected": "TRUE", "operator_input_required_before_v20_149": "TRUE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_149_promotion_readiness_operator_decision_capture_allowed": "FALSE", "promotion_readiness_operator_review_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_148_NEXT_STAGE_GATE_001", "v20_147_gate_consumed": "FALSE", "v20_148_promotion_readiness_operator_review_allowed_by_v147": "FALSE", "selected_repair_scenario_id": "", "promotion_readiness_operator_review_created": "TRUE", "operator_input_required_before_v20_149": "TRUE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_149_promotion_readiness_operator_decision_capture_allowed": "FALSE", "next_recommended_action": "V20.148_PROMOTION_READINESS_OPERATOR_REVIEW_REPAIR", "blocking_reason": blocking, "promotion_readiness_operator_review_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_147_GATE_CONSUMED=FALSE")
    print("V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_ALLOWED=FALSE")
    print("OPERATOR_INPUT_REQUIRED_BEFORE_V20_149=TRUE")
    print_safety_stdout()
    return 0


def option_consequence(action: str) -> str:
    if action == "APPROVE_PROMOTION_READINESS_FOR_STAGING":
        return "Requires explicit V20.149 operator capture; does not itself mark promotion_ready or create official artifacts."
    if action == "REJECT_PROMOTION_READINESS_KEEP_RESEARCH_ONLY":
        return "Requires explicit V20.149 operator capture; scenario remains research-only."
    return "Requires explicit V20.149 operator capture; remediation may be requested without automatic action."


def build_review(selected_id: str, packet: dict[str, str], manifest_rows: list[dict[str, str]], criteria_rows: list[dict[str, str]], limitation_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    packet_id = "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET_001"
    allowed_actions = ";".join(OPERATOR_ACTIONS)
    review_packet = [{
        "promotion_readiness_operator_review_packet_id": packet_id,
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_packet_id": clean(packet.get("promotion_readiness_packet_id")),
        "promotion_readiness_recheck_passed": clean(packet.get("promotion_readiness_recheck_passed")),
        "evidence_acceptance": clean(packet.get("evidence_acceptance")),
        "operator_acceptance": clean(packet.get("operator_acceptance")),
        "promotion_ready": "FALSE",
        "accepted_limitation_count": str(len(limitation_rows)),
        "evidence_manifest_row_count": str(len(manifest_rows)),
        "criteria_pass_count": str(sum(1 for row in criteria_rows if truthy(row.get("criterion_passed")))),
        "criteria_fail_count": str(sum(1 for row in criteria_rows if not truthy(row.get("criterion_passed")))),
        "remaining_limitation_summary": clean(packet.get("remaining_limitation_summary")),
        "operator_review_question": "Select one explicit promotion-readiness review action before V20.149 can capture a decision.",
        "allowed_operator_actions": allowed_actions,
        "default_operator_action": DEFAULT_ACTION,
        "selected_operator_action": "",
        "operator_action_auto_selected": "FALSE",
        "operator_input_required_before_v20_149": "TRUE",
        "ticker_rows_created": "0",
        **COMMON,
    }]
    options = [{
        "promotion_readiness_operator_review_options_audit_id": f"V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT_{i:03d}",
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_operator_review_packet_id": packet_id,
        "operator_action_option": action,
        "option_available": "TRUE",
        "option_requires_explicit_operator_input": "TRUE",
        "option_auto_selected": "FALSE",
        "option_consequence": option_consequence(action),
        "promotion_ready": "FALSE",
        **COMMON,
    } for i, action in enumerate(OPERATOR_ACTIONS, start=1)]
    required = [{
        "promotion_readiness_operator_required_action_id": "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS_001",
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_operator_review_packet_id": packet_id,
        "required_operator_decision": "Choose one explicit promotion-readiness operator action before V20.149.",
        "allowed_operator_actions": allowed_actions,
        "operator_action_selected": "FALSE",
        "selected_operator_action": "",
        "operator_input_required_before_v20_149": "TRUE",
        "promotion_readiness_decision_capture_allowed_before_input": "FALSE",
        "promotion_ready": "FALSE",
        **COMMON,
    }]
    return review_packet, options, required


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)
    decision_rows = read_csv(IN_DECISION)
    packet_rows = read_csv(IN_PACKET)
    manifest_rows = read_csv(IN_MANIFEST)
    limitation_rows = read_csv(IN_LIMITATION)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    criteria_rows = read_csv(IN_CRITERIA)
    disposition_rows = read_csv(IN_DISPOSITION)
    v145_rows = read_csv(IN_V145_RECORD)
    if not all([decision_rows, packet_rows, manifest_rows, limitation_rows, safety_input_rows, gate_rows, criteria_rows, disposition_rows, v145_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    source_packet = first(packet_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v147_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_147_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_148_promotion_readiness_operator_review_allowed"))
    v147_status = clean(gate_in.get("promotion_readiness_packet_status")) or clean(decision_in.get("promotion_readiness_packet_status"))
    v147_status_allowed = v147_status == V147_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    packet_requirements_met = all([
        len(packet_rows) == 1,
        truthy(source_packet.get("promotion_readiness_recheck_passed")),
        truthy(source_packet.get("evidence_acceptance")),
        truthy(source_packet.get("operator_acceptance")),
        not truthy(source_packet.get("promotion_ready")),
        clean(source_packet.get("readiness_packet_scope")) == PACKET_SCOPE,
        clean(source_packet.get("allowed_next_review_action")) == NEXT_REVIEW_ACTION,
    ])

    review_packet_rows, option_rows, required_rows = build_review(selected_id, source_packet, manifest_rows, criteria_rows, limitation_rows)
    expected_actions = set(OPERATOR_ACTIONS)
    option_actions = {clean(row.get("operator_action_option")) for row in option_rows}
    operator_actions_complete = option_actions == expected_actions and len(option_rows) == 3
    default_valid = bool(review_packet_rows) and clean(review_packet_rows[0].get("default_operator_action")) == DEFAULT_ACTION
    auto_selected_count = (
        sum(1 for row in review_packet_rows if truthy(row.get("operator_action_auto_selected")) or clean(row.get("selected_operator_action")))
        + sum(1 for row in option_rows if truthy(row.get("option_auto_selected")))
        + sum(1 for row in required_rows if truthy(row.get("operator_action_selected")) or clean(row.get("selected_operator_action")))
    )
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in packet_rows + review_packet_rows)
    counts = prohibited_counts([decision_rows, packet_rows, manifest_rows, limitation_rows, safety_input_rows, gate_rows, criteria_rows, disposition_rows, v145_rows, review_packet_rows, option_rows, required_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v147_gate_consumed, allowed, v147_status_allowed, selected_matches, packet_requirements_met, len(review_packet_rows) == 1, operator_actions_complete, default_valid, auto_selected_count == 0, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PARTIAL_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PARTIAL_STATUS
    blocking = "" if next_allowed else "promotion_readiness_operator_review_requirements_not_met"

    decision = {"decision_check_id": "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION_001", "v20_147_gate_consumed": tf(v147_gate_consumed), "v20_148_promotion_readiness_operator_review_allowed_by_v147": tf(allowed), "v20_147_final_status": v147_status, "v20_147_status_allowed": tf(v147_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_147": tf(selected_matches), "promotion_readiness_packet_row_count": str(len(packet_rows)), "operator_review_packet_row_count": str(len(review_packet_rows)), "operator_review_options_audit_row_count": str(len(option_rows)), "operator_required_actions_row_count": str(len(required_rows)), "packet_requirements_met": tf(packet_requirements_met), "operator_actions_complete": tf(operator_actions_complete), "default_operator_action_valid": tf(default_valid), "operator_action_auto_selected_count": str(auto_selected_count), "no_operator_action_auto_selected": tf(auto_selected_count == 0), "operator_input_required_before_v20_149": "TRUE", "evidence_acceptance": clean(source_packet.get("evidence_acceptance")), "operator_acceptance": clean(source_packet.get("operator_acceptance")), "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_149_promotion_readiness_operator_decision_capture_allowed": tf(next_allowed), "promotion_readiness_operator_review_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_148_NEXT_STAGE_GATE_001", "v20_147_gate_consumed": tf(v147_gate_consumed), "v20_148_promotion_readiness_operator_review_allowed_by_v147": tf(allowed), "selected_repair_scenario_id": selected_id, "promotion_readiness_operator_review_created": "TRUE", "operator_input_required_before_v20_149": "TRUE", "evidence_acceptance": clean(source_packet.get("evidence_acceptance")), "operator_acceptance": clean(source_packet.get("operator_acceptance")), "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_149_promotion_readiness_operator_decision_capture_allowed": tf(next_allowed), "next_recommended_action": "V20.149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_AFTER_EXPLICIT_OPERATOR_INPUT" if next_allowed else "V20.148_PROMOTION_READINESS_OPERATOR_REVIEW_REPAIR", "blocking_reason": blocking, "promotion_readiness_operator_review_status": final_status, **COMMON}
    write_all([decision], review_packet_rows, option_rows, required_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_147_GATE_CONSUMED={tf(v147_gate_consumed)}")
    print(f"V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_ALLOWED_BY_V147={tf(allowed)}")
    print(f"V20_147_FINAL_STATUS={v147_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_147={tf(selected_matches)}")
    print(f"PROMOTION_READINESS_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"OPERATOR_REVIEW_PACKET_ROW_COUNT={len(review_packet_rows)}")
    print(f"OPERATOR_REVIEW_OPTIONS_AUDIT_ROW_COUNT={len(option_rows)}")
    print(f"OPERATOR_REQUIRED_ACTIONS_ROW_COUNT={len(required_rows)}")
    print(f"PACKET_REQUIREMENTS_MET={tf(packet_requirements_met)}")
    print(f"OPERATOR_ACTIONS_COMPLETE={tf(operator_actions_complete)}")
    print(f"DEFAULT_OPERATOR_ACTION_VALID={tf(default_valid)}")
    print(f"OPERATOR_ACTION_AUTO_SELECTED_COUNT={auto_selected_count}")
    print(f"NO_OPERATOR_ACTION_AUTO_SELECTED={tf(auto_selected_count == 0)}")
    print("OPERATOR_INPUT_REQUIRED_BEFORE_V20_149=TRUE")
    print(f"EVIDENCE_ACCEPTANCE={clean(source_packet.get('evidence_acceptance'))}")
    print(f"OPERATOR_ACCEPTANCE={clean(source_packet.get('operator_acceptance'))}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
