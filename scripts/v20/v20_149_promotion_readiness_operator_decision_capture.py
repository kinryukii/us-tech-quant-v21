#!/usr/bin/env python
"""V20.149 promotion-readiness operator decision capture.

Captures the explicit operator decision from V20.148. This stage is
decision-capture-only, audit-only, and non-mutating. Approval allows staging
review only; it does not authorize formal activation, official promotion, or
any operational artifact creation.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_DECISION.csv"
IN_PACKET = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_PACKET.csv"
IN_OPTIONS = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_OPTIONS_AUDIT.csv"
IN_REQUIRED = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REQUIRED_ACTIONS.csv"
IN_SAFETY = CONSOLIDATION / "V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_148_NEXT_STAGE_GATE.csv"
IN_V147_PACKET = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET.csv"
IN_V147_MANIFEST = CONSOLIDATION / "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv"
IN_V147_LIMITATION = CONSOLIDATION / "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv"

OUT_DECISION = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION.csv"
OUT_INPUT = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT.csv"
OUT_RECORD = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_149_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V148_REQUIRED_STATUS = "PARTIAL_PASS_V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_AWAITING_OPERATOR_INPUT"
PASS_STATUS = "PASS_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_READY_FOR_V20_150"
BLOCKED_STATUS = "BLOCKED_V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE"
SELECTED_OPERATOR_ACTION = "APPROVE_PROMOTION_READINESS_FOR_STAGING"
OPERATOR_SCOPE = "The operator approves entering staging review only. This does not authorize formal activation, official promotion, official ranking creation, official recommendation creation, official weight creation, real-book weight creation, trade action, broker action, authoritative overwrite, weight mutation, or performance claim. promotion_ready must remain FALSE until a later explicit staging/promotion gate passes."
VALID_ACTIONS = [
    "APPROVE_PROMOTION_READINESS_FOR_STAGING",
    "REJECT_PROMOTION_READINESS_KEEP_RESEARCH_ONLY",
    "REQUEST_PROMOTION_READINESS_REMEDIATION",
]

REQUIRED_INPUTS = [IN_DECISION, IN_PACKET, IN_OPTIONS, IN_REQUIRED, IN_SAFETY, IN_GATE, IN_V147_PACKET, IN_V147_MANIFEST, IN_V147_LIMITATION]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 149))
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
    "promotion_readiness_operator_decision_capture_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_148_gate_consumed", "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148", "operator_input_required_before_v20_149", "v20_148_final_status", "v20_148_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_148", "operator_decision_input_audit_row_count", "operator_decision_record_count", "selected_operator_action", "operator_action_valid", "operator_action_explicit", "operator_action_auto_selected", "operator_decision_status", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_150_staging_review_packet_allowed", "promotion_readiness_operator_decision_capture_status", "blocking_reason", *COMMON.keys()]
INPUT_FIELDS = ["promotion_readiness_operator_decision_input_audit_id", "selected_repair_scenario_id", "source_promotion_readiness_operator_review_packet_id", "selected_operator_action", "operator_scope", "operator_input_source", "operator_action_auto_selected", "promotion_ready", *COMMON.keys()]
RECORD_FIELDS = ["promotion_readiness_operator_decision_record_id", "selected_repair_scenario_id", "source_promotion_readiness_operator_review_packet_id", "source_promotion_readiness_packet_id", "selected_operator_action", "operator_scope", "operator_decision_status", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
VALIDATION_FIELDS = ["promotion_readiness_operator_decision_validation_audit_id", "selected_repair_scenario_id", "source_promotion_readiness_operator_review_packet_id", "selected_operator_action", "operator_action_valid", "operator_action_available_in_v148_options", "operator_action_explicit", "operator_action_auto_selected", "formal_activation_allowed", "operator_decision_valid", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
CONSEQUENCE_FIELDS = ["promotion_readiness_operator_decision_consequence_audit_id", "selected_repair_scenario_id", "source_promotion_readiness_operator_review_packet_id", "selected_operator_action", "operator_decision_status", "decision_consequence", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_148_gate_consumed", "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148", "selected_repair_scenario_id", "operator_decision_capture_created", "staging_review_allowed", "formal_activation_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_150_staging_review_packet_allowed", "next_recommended_action", "blocking_reason", "promotion_readiness_operator_decision_capture_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_149_PROMOTION_READINESS_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.149 captures only an explicit operator decision for staging review and keeps all formal activation/promotion/official action fields false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, input_rows, record, validation, consequence, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_INPUT, INPUT_FIELDS, input_rows)
    write_csv(OUT_RECORD, RECORD_FIELDS, record)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation)
    write_csv(OUT_CONSEQUENCE, CONSEQUENCE_FIELDS, consequence)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.149 Promotion Readiness Operator Decision Capture Report", "",
        f"- wrapper_status: {decision.get('promotion_readiness_operator_decision_capture_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- selected_operator_action: {decision.get('selected_operator_action')}",
        f"- operator_decision_status: {decision.get('operator_decision_status')}",
        f"- staging_review_allowed: {decision.get('staging_review_allowed')}",
        f"- formal_activation_allowed: {decision.get('formal_activation_allowed')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_150_staging_review_packet_allowed: {decision.get('v20_150_staging_review_packet_allowed')}",
        "",
        "Approval is limited to staging review only. Formal activation, official promotion, official artifacts, real-book actions, trades, broker actions, overwrites, weight mutations, and performance claims remain disallowed.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_WEIGHT_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "TRADE_ACTION_CREATED", "BROKER_ACTION_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "WEIGHT_MUTATED", "PERFORMANCE_CLAIM_CREATED", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION_001", "v20_148_gate_consumed": "FALSE", "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148": "FALSE", "operator_input_required_before_v20_149": "TRUE", "v20_148_final_status": "", "v20_148_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_148": "FALSE", "operator_decision_input_audit_row_count": "0", "operator_decision_record_count": "0", "selected_operator_action": "", "operator_action_valid": "FALSE", "operator_action_explicit": "FALSE", "operator_action_auto_selected": "FALSE", "operator_decision_status": "", "staging_review_allowed": "FALSE", "formal_activation_allowed": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_150_staging_review_packet_allowed": "FALSE", "promotion_readiness_operator_decision_capture_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_149_NEXT_STAGE_GATE_001", "v20_148_gate_consumed": "FALSE", "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148": "FALSE", "selected_repair_scenario_id": "", "operator_decision_capture_created": "TRUE", "staging_review_allowed": "FALSE", "formal_activation_allowed": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_150_staging_review_packet_allowed": "FALSE", "next_recommended_action": "V20.149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_REPAIR", "blocking_reason": blocking, "promotion_readiness_operator_decision_capture_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_148_GATE_CONSUMED=FALSE")
    print("V20_150_STAGING_REVIEW_PACKET_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def decision_consequence(action: str) -> tuple[str, bool, bool, str]:
    if action == "APPROVE_PROMOTION_READINESS_FOR_STAGING":
        return "APPROVED_FOR_STAGING_REVIEW_ONLY", True, False, "Operator approved staging review only; formal activation and promotion readiness remain false pending later gate."
    if action == "REJECT_PROMOTION_READINESS_KEEP_RESEARCH_ONLY":
        return "REJECTED_KEEP_RESEARCH_ONLY", False, False, "Operator rejected promotion readiness; scenario remains research-only."
    if action == "REQUEST_PROMOTION_READINESS_REMEDIATION":
        return "REMEDIATION_REQUIRED", False, False, "Operator requested remediation; no staging review is allowed."
    return "INVALID_OPERATOR_DECISION", False, False, "Operator decision is invalid."


def build_capture(selected_id: str, review_packet: dict[str, str], action: str | None = None, auto_selected: bool = False, formal_activation_override: bool | None = None) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    if action is None:
        action = SELECTED_OPERATOR_ACTION
    status, staging_allowed, formal_activation_allowed, consequence = decision_consequence(action)
    if formal_activation_override is not None:
        formal_activation_allowed = formal_activation_override
    input_rows = [{
        "promotion_readiness_operator_decision_input_audit_id": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_INPUT_AUDIT_001",
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_operator_review_packet_id": clean(review_packet.get("promotion_readiness_operator_review_packet_id")),
        "selected_operator_action": action,
        "operator_scope": OPERATOR_SCOPE,
        "operator_input_source": "USER_PROVIDED_PROMOTION_READINESS_OPERATOR_DECISION_FOR_V20_149",
        "operator_action_auto_selected": tf(auto_selected),
        "promotion_ready": "FALSE",
        **COMMON,
    }]
    record = [{
        "promotion_readiness_operator_decision_record_id": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_RECORD_001",
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_operator_review_packet_id": clean(review_packet.get("promotion_readiness_operator_review_packet_id")),
        "source_promotion_readiness_packet_id": clean(review_packet.get("source_promotion_readiness_packet_id")),
        "selected_operator_action": action,
        "operator_scope": OPERATOR_SCOPE,
        "operator_decision_status": status,
        "staging_review_allowed": tf(staging_allowed),
        "formal_activation_allowed": tf(formal_activation_allowed),
        "evidence_acceptance": clean(review_packet.get("evidence_acceptance")),
        "operator_acceptance": clean(review_packet.get("operator_acceptance")),
        "promotion_ready": "FALSE",
        "ticker_rows_created": "0",
        **COMMON,
    }]
    validation = [{
        "promotion_readiness_operator_decision_validation_audit_id": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_VALIDATION_AUDIT_001",
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_operator_review_packet_id": clean(review_packet.get("promotion_readiness_operator_review_packet_id")),
        "selected_operator_action": action,
        "operator_action_valid": tf(action in VALID_ACTIONS),
        "operator_action_available_in_v148_options": "",
        "operator_action_explicit": tf(bool(action) and not auto_selected),
        "operator_action_auto_selected": tf(auto_selected),
        "formal_activation_allowed": tf(formal_activation_allowed),
        "operator_decision_valid": "FALSE",
        "evidence_acceptance": clean(review_packet.get("evidence_acceptance")),
        "operator_acceptance": clean(review_packet.get("operator_acceptance")),
        "promotion_ready": "FALSE",
        **COMMON,
    }]
    consequence_rows = [{
        "promotion_readiness_operator_decision_consequence_audit_id": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CONSEQUENCE_AUDIT_001",
        "selected_repair_scenario_id": selected_id,
        "source_promotion_readiness_operator_review_packet_id": clean(review_packet.get("promotion_readiness_operator_review_packet_id")),
        "selected_operator_action": action,
        "operator_decision_status": status,
        "decision_consequence": consequence,
        "staging_review_allowed": tf(staging_allowed),
        "formal_activation_allowed": tf(formal_activation_allowed),
        "evidence_acceptance": clean(review_packet.get("evidence_acceptance")),
        "operator_acceptance": clean(review_packet.get("operator_acceptance")),
        "promotion_ready": "FALSE",
        **COMMON,
    }]
    return input_rows, record, validation, consequence_rows


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)
    decision_rows = read_csv(IN_DECISION)
    packet_rows = read_csv(IN_PACKET)
    option_rows = read_csv(IN_OPTIONS)
    required_rows = read_csv(IN_REQUIRED)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    v147_packet_rows = read_csv(IN_V147_PACKET)
    v147_manifest_rows = read_csv(IN_V147_MANIFEST)
    v147_limitation_rows = read_csv(IN_V147_LIMITATION)
    if not all([decision_rows, packet_rows, option_rows, required_rows, safety_input_rows, gate_rows, v147_packet_rows, v147_manifest_rows, v147_limitation_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    review_packet = first(packet_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v148_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_148_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_149_promotion_readiness_operator_decision_capture_allowed"))
    input_required = truthy(gate_in.get("operator_input_required_before_v20_149")) and all(truthy(row.get("operator_input_required_before_v20_149")) for row in required_rows)
    v148_status = clean(gate_in.get("promotion_readiness_operator_review_status")) or clean(decision_in.get("promotion_readiness_operator_review_status"))
    v148_status_allowed = v148_status == V148_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    input_rows, record_rows, validation_rows, consequence_rows = build_capture(selected_id, review_packet)
    selected_action = clean(input_rows[0].get("selected_operator_action")) if input_rows else ""
    available_actions = {clean(row.get("operator_action_option")) for row in option_rows if truthy(row.get("option_available"))}
    action_valid = selected_action in VALID_ACTIONS
    action_available = selected_action in available_actions
    action_auto_selected = any(truthy(row.get("operator_action_auto_selected")) for row in input_rows + record_rows + validation_rows)
    action_explicit = bool(input_rows) and bool(selected_action) and not action_auto_selected
    formal_activation_allowed = any(truthy(row.get("formal_activation_allowed")) for row in record_rows + consequence_rows + validation_rows)
    evidence_acceptance = truthy(review_packet.get("evidence_acceptance")) and all(truthy(row.get("evidence_acceptance")) for row in record_rows)
    operator_acceptance = truthy(review_packet.get("operator_acceptance")) and all(truthy(row.get("operator_acceptance")) for row in record_rows)
    for row in validation_rows:
        row["operator_action_available_in_v148_options"] = tf(action_available)
        row["operator_decision_valid"] = tf(action_valid and action_available and action_explicit and not formal_activation_allowed and evidence_acceptance and operator_acceptance)

    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in packet_rows + record_rows)
    counts = prohibited_counts([decision_rows, packet_rows, option_rows, required_rows, safety_input_rows, gate_rows, v147_packet_rows, v147_manifest_rows, v147_limitation_rows, input_rows, record_rows, validation_rows, consequence_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    staging_allowed = any(truthy(row.get("staging_review_allowed")) for row in record_rows)
    status = clean(record_rows[0].get("operator_decision_status")) if record_rows else ""
    base_ok = all([v148_gate_consumed, allowed, input_required, v148_status_allowed, selected_matches, len(input_rows) == 1, len(record_rows) == 1, selected_action == SELECTED_OPERATOR_ACTION, action_valid, action_available, action_explicit, not action_auto_selected, status == "APPROVED_FOR_STAGING_REVIEW_ONLY", staging_allowed, not formal_activation_allowed, evidence_acceptance, operator_acceptance, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "promotion_readiness_operator_decision_capture_requirements_not_met"

    decision = {"decision_check_id": "V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_DECISION_001", "v20_148_gate_consumed": tf(v148_gate_consumed), "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148": tf(allowed), "operator_input_required_before_v20_149": tf(input_required), "v20_148_final_status": v148_status, "v20_148_status_allowed": tf(v148_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_148": tf(selected_matches), "operator_decision_input_audit_row_count": str(len(input_rows)), "operator_decision_record_count": str(len(record_rows)), "selected_operator_action": selected_action, "operator_action_valid": tf(action_valid and action_available), "operator_action_explicit": tf(action_explicit), "operator_action_auto_selected": tf(action_auto_selected), "operator_decision_status": status, "staging_review_allowed": tf(staging_allowed), "formal_activation_allowed": tf(formal_activation_allowed), "evidence_acceptance": tf(evidence_acceptance), "operator_acceptance": tf(operator_acceptance), "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_150_staging_review_packet_allowed": tf(next_allowed), "promotion_readiness_operator_decision_capture_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_149_NEXT_STAGE_GATE_001", "v20_148_gate_consumed": tf(v148_gate_consumed), "v20_149_promotion_readiness_operator_decision_capture_allowed_by_v148": tf(allowed), "selected_repair_scenario_id": selected_id, "operator_decision_capture_created": "TRUE", "staging_review_allowed": tf(staging_allowed), "formal_activation_allowed": tf(formal_activation_allowed), "evidence_acceptance": tf(evidence_acceptance), "operator_acceptance": tf(operator_acceptance), "promotion_ready": "FALSE", "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_150_staging_review_packet_allowed": tf(next_allowed), "next_recommended_action": "V20.150_STAGING_REVIEW_PACKET" if next_allowed else "V20.149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_REPAIR", "blocking_reason": blocking, "promotion_readiness_operator_decision_capture_status": final_status, **COMMON}
    write_all([decision], input_rows, record_rows, validation_rows, consequence_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_148_GATE_CONSUMED={tf(v148_gate_consumed)}")
    print(f"V20_149_PROMOTION_READINESS_OPERATOR_DECISION_CAPTURE_ALLOWED_BY_V148={tf(allowed)}")
    print(f"OPERATOR_INPUT_REQUIRED_BEFORE_V20_149={tf(input_required)}")
    print(f"V20_148_FINAL_STATUS={v148_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_148={tf(selected_matches)}")
    print(f"OPERATOR_DECISION_INPUT_AUDIT_ROW_COUNT={len(input_rows)}")
    print(f"OPERATOR_DECISION_RECORD_COUNT={len(record_rows)}")
    print(f"SELECTED_OPERATOR_ACTION={selected_action}")
    print(f"OPERATOR_ACTION_VALID={tf(action_valid and action_available)}")
    print(f"OPERATOR_ACTION_EXPLICIT={tf(action_explicit)}")
    print(f"OPERATOR_ACTION_AUTO_SELECTED={tf(action_auto_selected)}")
    print(f"OPERATOR_DECISION_STATUS={status}")
    print(f"STAGING_REVIEW_ALLOWED={tf(staging_allowed)}")
    print(f"FORMAL_ACTIVATION_ALLOWED={tf(formal_activation_allowed)}")
    print(f"EVIDENCE_ACCEPTANCE={tf(evidence_acceptance)}")
    print(f"OPERATOR_ACCEPTANCE={tf(operator_acceptance)}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_150_STAGING_REVIEW_PACKET_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
