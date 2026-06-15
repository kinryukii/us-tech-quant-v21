#!/usr/bin/env python
"""V20.145 final human decision capture.

Captures explicit final human decisions supplied after V20.144. This stage is
decision-capture-only and audit-only: it records the human choices and their
limited consequences, but does not create official artifacts, mutate weights,
or mark promotion readiness true.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_DECISION.csv"
IN_PACKET = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv"
IN_OPTIONS = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_OPTIONS_AUDIT.csv"
IN_REQUIRED = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_REQUIRED_ACTIONS.csv"
IN_SAFETY = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_144_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION.csv"
OUT_INPUT = CONSOLIDATION / "V20_145_EXPLICIT_HUMAN_DECISION_INPUT.csv"
OUT_RECORD = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv"
OUT_VALIDATION = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT.csv"
OUT_CONSEQUENCE = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_145_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V144_REQUIRED_STATUS = "PARTIAL_PASS_V20_144_FINAL_HUMAN_CONFIRMATION_PACKET_AWAITING_OPERATOR_INPUT"
PASS_STATUS = "PASS_V20_145_FINAL_HUMAN_DECISION_CAPTURE_READY_FOR_PROMOTION_READINESS_RECHECK"
BLOCKED_STATUS = "BLOCKED_V20_145_FINAL_HUMAN_DECISION_CAPTURE"
ALLOWED_ACTIONS = ["ACCEPT_WITH_LIMITATION", "REJECT_KEEP_BLOCKED", "MORE_EVIDENCE_REQUIRED"]

EXPLICIT_HUMAN_DECISIONS = [
    {
        "blocker_id": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS_001",
        "blocker_category": "official_promotion_policy_evidence",
        "selected_human_action": "ACCEPT_WITH_LIMITATION",
        "human_rationale": "Accept with limitation for promotion-readiness recheck only. This acceptance does not authorize official ranking creation, official recommendation creation, real-book weight creation, broker action, trade action, authoritative overwrite, or performance claim.",
    },
    {
        "blocker_id": "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS_002",
        "blocker_category": "operator_approval_evidence",
        "selected_human_action": "ACCEPT_WITH_LIMITATION",
        "human_rationale": "Operator accepts the remaining limitation for controlled promotion-readiness recheck only. This does not authorize official promotion, official weights, official recommendations, real-book actions, broker actions, or trades.",
    },
]

REQUIRED_INPUTS = [IN_DECISION, IN_PACKET, IN_OPTIONS, IN_REQUIRED, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 145))
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
    "final_human_decision_capture_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_144_gate_consumed", "v20_145_final_human_decision_capture_allowed_by_v144", "v20_144_final_status", "v20_144_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_144", "final_human_confirmation_packet_row_count", "explicit_human_decision_input_count", "final_human_decision_record_count", "every_packet_has_explicit_human_decision", "all_human_actions_allowed", "accept_with_limitation_count", "reject_keep_blocked_count", "more_evidence_required_count", "evidence_acceptance", "operator_acceptance", "promotion_ready", "promotion_readiness_recheck_allowed", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_146_promotion_readiness_recheck_allowed", "final_human_decision_capture_status", "blocking_reason", *COMMON.keys()]
INPUT_FIELDS = ["explicit_human_decision_input_id", "selected_repair_scenario_id", "blocker_id", "blocker_category", "selected_human_action", "human_rationale", "input_source", *COMMON.keys()]
RECORD_FIELDS = ["final_human_decision_record_id", "selected_repair_scenario_id", "source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "selected_human_action", "human_rationale", "human_decision_source", "decision_status", "blocker_status", "evidence_acceptance", "operator_acceptance", "promotion_ready", "promotion_readiness_recheck_allowed", "ticker_rows_created", *COMMON.keys()]
VALIDATION_FIELDS = ["final_human_decision_validation_audit_id", "selected_repair_scenario_id", "source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "selected_human_action", "human_action_allowed_in_v144_packet", "explicit_human_decision_present", "human_rationale_present", "human_decision_valid", "prohibited_authorization_detected", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
CONSEQUENCE_FIELDS = ["final_human_decision_consequence_audit_id", "selected_repair_scenario_id", "source_final_human_confirmation_packet_id", "blocker_id", "blocker_category", "selected_human_action", "decision_consequence", "decision_status", "blocker_status", "promotion_readiness_recheck_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_144_gate_consumed", "v20_145_final_human_decision_capture_allowed_by_v144", "selected_repair_scenario_id", "final_human_decision_capture_created", "every_packet_has_explicit_human_decision", "all_human_actions_allowed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "promotion_readiness_recheck_allowed", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_146_promotion_readiness_recheck_allowed", "next_recommended_action", "blocking_reason", "final_human_decision_capture_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.145 captures explicit final human decisions only and keeps all operational/prohibited actions false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, explicit_input, record, validation, consequence, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_INPUT, INPUT_FIELDS, explicit_input)
    write_csv(OUT_RECORD, RECORD_FIELDS, record)
    write_csv(OUT_VALIDATION, VALIDATION_FIELDS, validation)
    write_csv(OUT_CONSEQUENCE, CONSEQUENCE_FIELDS, consequence)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.145 Final Human Decision Capture Report", "",
        f"- wrapper_status: {decision.get('final_human_decision_capture_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- explicit_human_decision_input_count: {decision.get('explicit_human_decision_input_count')}",
        f"- final_human_decision_record_count: {decision.get('final_human_decision_record_count')}",
        f"- accept_with_limitation_count: {decision.get('accept_with_limitation_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- promotion_readiness_recheck_allowed: {decision.get('promotion_readiness_recheck_allowed')}",
        "",
        "Captured acceptance is limited to a later promotion-readiness recheck. It does not authorize official ranking, official recommendation, real-book weight, broker action, trade action, authoritative overwrite, or performance claim creation.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED", "ACCEPTED_WEIGHTS_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "OFFICIAL_WEIGHT_CREATED", "OFFICIAL_WEIGHTS_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_RANKINGS_CREATED", "OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RECOMMENDATIONS_CREATED", "TRADE_ACTION_CREATED", "TRADE_ACTIONS_CREATED", "BROKER_ACTION_CREATED", "BROKER_ACTIONS_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "AUTHORITATIVE_OVERWRITES_CREATED", "AUTHORITATIVE_RANKING_OVERWRITTEN", "WEIGHT_MUTATED", "WEIGHT_MUTATIONS_CREATED", "PERFORMANCE_CLAIM_CREATED", "PERFORMANCE_CLAIMS_CREATED", "PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED", "OFFICIAL_PROMOTION_ALLOWED", "IS_OFFICIAL_WEIGHT", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION_001", "v20_144_gate_consumed": "FALSE", "v20_145_final_human_decision_capture_allowed_by_v144": "FALSE", "v20_144_final_status": "", "v20_144_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_144": "FALSE", "final_human_confirmation_packet_row_count": "0", "explicit_human_decision_input_count": "0", "final_human_decision_record_count": "0", "every_packet_has_explicit_human_decision": "FALSE", "all_human_actions_allowed": "FALSE", "accept_with_limitation_count": "0", "reject_keep_blocked_count": "0", "more_evidence_required_count": "0", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "promotion_readiness_recheck_allowed": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_146_promotion_readiness_recheck_allowed": "FALSE", "final_human_decision_capture_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_145_NEXT_STAGE_GATE_001", "v20_144_gate_consumed": "FALSE", "v20_145_final_human_decision_capture_allowed_by_v144": "FALSE", "selected_repair_scenario_id": "", "final_human_decision_capture_created": "TRUE", "every_packet_has_explicit_human_decision": "FALSE", "all_human_actions_allowed": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "promotion_readiness_recheck_allowed": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_146_promotion_readiness_recheck_allowed": "FALSE", "next_recommended_action": "V20.145_FINAL_HUMAN_DECISION_CAPTURE_REPAIR", "blocking_reason": blocking, "final_human_decision_capture_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_144_GATE_CONSUMED=FALSE")
    print("V20_146_PROMOTION_READINESS_RECHECK_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def build_input_rows(selected_id: str) -> list[dict[str, str]]:
    rows = []
    for i, item in enumerate(EXPLICIT_HUMAN_DECISIONS, start=1):
        rows.append({
            "explicit_human_decision_input_id": f"V20_145_EXPLICIT_HUMAN_DECISION_INPUT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "blocker_id": item["blocker_id"],
            "blocker_category": item["blocker_category"],
            "selected_human_action": item["selected_human_action"],
            "human_rationale": item["human_rationale"],
            "input_source": "USER_PROVIDED_FINAL_HUMAN_CONFIRMATION_FOR_V20_145",
            **COMMON,
        })
    return rows


def consequence(action: str) -> tuple[str, str, str, str, str, bool]:
    if action == "ACCEPT_WITH_LIMITATION":
        return (
            "FINAL_HUMAN_ACCEPTED_WITH_LIMITATION_FOR_PROMOTION_READINESS_RECHECK_ONLY",
            "RESOLVED_WITH_LIMITATION_PENDING_PROMOTION_READINESS_RECHECK",
            "Explicit human acceptance with limitation captured; a later promotion-readiness recheck may run, while promotion readiness and all official/real-book/trade actions remain false.",
            "TRUE",
            "TRUE",
            True,
        )
    if action == "REJECT_KEEP_BLOCKED":
        return ("FINAL_HUMAN_REJECTED_KEEP_BLOCKED", "BLOCKED", "Explicit human rejection captured; blocker remains blocked.", "FALSE", "TRUE", False)
    return ("FINAL_HUMAN_REQUESTED_MORE_EVIDENCE", "MORE_EVIDENCE_REQUIRED_BY_FINAL_HUMAN_DECISION", "Explicit human request for more evidence captured; no automatic evidence loop is started by V20.145.", "FALSE", "TRUE", False)


def build_records(selected_id: str, packets: list[dict[str, str]], option_rows: list[dict[str, str]], explicit_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    explicit_by_blocker = {clean(row.get("blocker_id")): row for row in explicit_rows}
    allowed_by_packet: dict[str, set[str]] = {}
    for row in option_rows:
        if truthy(row.get("option_available")):
            allowed_by_packet.setdefault(clean(row.get("source_final_human_confirmation_packet_id")), set()).add(clean(row.get("human_action_option")))
    records, validations, consequences = [], [], []
    for i, packet in enumerate(packets, start=1):
        packet_id = clean(packet.get("final_human_confirmation_packet_id"))
        blocker_id = clean(packet.get("blocker_id"))
        explicit = explicit_by_blocker.get(blocker_id, {})
        action = clean(explicit.get("selected_human_action"))
        rationale = clean(explicit.get("human_rationale"))
        allowed = action in allowed_by_packet.get(packet_id, set())
        present = bool(explicit)
        rationale_present = bool(rationale)
        lowered_rationale = rationale.lower()
        prohibited_authorization = (
            any(token in lowered_rationale for token in ["authorizes official", "authorizes trade", "authorizes broker", "authorizes real-book"])
            and "does not authorize" not in lowered_rationale
        )
        valid = present and allowed and rationale_present and not prohibited_authorization
        decision_status, blocker_status, consequence_text, evidence_acceptance, operator_acceptance, recheck_allowed = consequence(action)
        if not valid:
            decision_status, blocker_status, consequence_text, evidence_acceptance, operator_acceptance, recheck_allowed = ("INVALID_OR_MISSING_FINAL_HUMAN_DECISION", "UNRESOLVED_PENDING_VALID_FINAL_HUMAN_DECISION", "Final human decision is missing or invalid; no acceptance or recheck is allowed.", "FALSE", "FALSE", False)
        records.append({
            "final_human_decision_record_id": f"V20_145_FINAL_HUMAN_DECISION_RECORD_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_final_human_confirmation_packet_id": packet_id,
            "blocker_id": blocker_id,
            "blocker_category": clean(packet.get("blocker_category")),
            "selected_human_action": action,
            "human_rationale": rationale,
            "human_decision_source": clean(explicit.get("input_source")),
            "decision_status": decision_status,
            "blocker_status": blocker_status,
            "evidence_acceptance": evidence_acceptance,
            "operator_acceptance": operator_acceptance,
            "promotion_ready": "FALSE",
            "promotion_readiness_recheck_allowed": tf(recheck_allowed),
            "ticker_rows_created": "0",
            **COMMON,
        })
        validations.append({
            "final_human_decision_validation_audit_id": f"V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_final_human_confirmation_packet_id": packet_id,
            "blocker_id": blocker_id,
            "blocker_category": clean(packet.get("blocker_category")),
            "selected_human_action": action,
            "human_action_allowed_in_v144_packet": tf(allowed),
            "explicit_human_decision_present": tf(present),
            "human_rationale_present": tf(rationale_present),
            "human_decision_valid": tf(valid),
            "prohibited_authorization_detected": tf(prohibited_authorization),
            "evidence_acceptance": evidence_acceptance,
            "operator_acceptance": operator_acceptance,
            "promotion_ready": "FALSE",
            **COMMON,
        })
        consequences.append({
            "final_human_decision_consequence_audit_id": f"V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_final_human_confirmation_packet_id": packet_id,
            "blocker_id": blocker_id,
            "blocker_category": clean(packet.get("blocker_category")),
            "selected_human_action": action,
            "decision_consequence": consequence_text,
            "decision_status": decision_status,
            "blocker_status": blocker_status,
            "promotion_readiness_recheck_allowed": tf(recheck_allowed),
            "evidence_acceptance": evidence_acceptance,
            "operator_acceptance": operator_acceptance,
            "promotion_ready": "FALSE",
            **COMMON,
        })
    return records, validations, consequences


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
    if not all([decision_rows, packet_rows, option_rows, required_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v144_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_144_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_145_final_human_decision_capture_allowed"))
    v144_status = clean(gate_in.get("final_human_confirmation_packet_status")) or clean(decision_in.get("final_human_confirmation_packet_status"))
    v144_status_allowed = v144_status == V144_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    explicit_rows = build_input_rows(selected_id)
    record_rows, validation_rows, consequence_rows = build_records(selected_id, packet_rows, option_rows, explicit_rows)

    packet_ids = {clean(row.get("final_human_confirmation_packet_id")) for row in packet_rows}
    record_packet_ids = {clean(row.get("source_final_human_confirmation_packet_id")) for row in record_rows}
    every_packet_has_decision = bool(packet_rows) and packet_ids == record_packet_ids and len(record_rows) == len(packet_rows)
    valid_rows = bool(validation_rows) and all(truthy(row.get("human_decision_valid")) for row in validation_rows)
    all_allowed = bool(validation_rows) and all(truthy(row.get("human_action_allowed_in_v144_packet")) for row in validation_rows)
    accept_count = sum(1 for row in record_rows if row.get("selected_human_action") == "ACCEPT_WITH_LIMITATION")
    reject_count = sum(1 for row in record_rows if row.get("selected_human_action") == "REJECT_KEEP_BLOCKED")
    more_count = sum(1 for row in record_rows if row.get("selected_human_action") == "MORE_EVIDENCE_REQUIRED")
    evidence_acceptance = tf(bool(record_rows) and all(row.get("evidence_acceptance") == "TRUE" for row in record_rows))
    operator_acceptance = tf(bool(record_rows) and all(row.get("operator_acceptance") == "TRUE" for row in record_rows))
    recheck_allowed = tf(bool(record_rows) and all(truthy(row.get("promotion_readiness_recheck_allowed")) for row in record_rows))
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in packet_rows + record_rows)
    counts = prohibited_counts([decision_rows, packet_rows, option_rows, required_rows, safety_input_rows, gate_rows, explicit_rows, record_rows, validation_rows, consequence_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v144_gate_consumed, allowed, v144_status_allowed, selected_matches, every_packet_has_decision, valid_rows, all_allowed, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS and recheck_allowed == "TRUE"
    blocking = "" if base_ok else "final_human_decision_capture_requirements_not_met"

    decision = {"decision_check_id": "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION_001", "v20_144_gate_consumed": tf(v144_gate_consumed), "v20_145_final_human_decision_capture_allowed_by_v144": tf(allowed), "v20_144_final_status": v144_status, "v20_144_status_allowed": tf(v144_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_144": tf(selected_matches), "final_human_confirmation_packet_row_count": str(len(packet_rows)), "explicit_human_decision_input_count": str(len(explicit_rows)), "final_human_decision_record_count": str(len(record_rows)), "every_packet_has_explicit_human_decision": tf(every_packet_has_decision), "all_human_actions_allowed": tf(all_allowed), "accept_with_limitation_count": str(accept_count), "reject_keep_blocked_count": str(reject_count), "more_evidence_required_count": str(more_count), "evidence_acceptance": evidence_acceptance, "operator_acceptance": operator_acceptance, "promotion_ready": "FALSE", "promotion_readiness_recheck_allowed": tf(next_allowed), "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_146_promotion_readiness_recheck_allowed": tf(next_allowed), "final_human_decision_capture_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_145_NEXT_STAGE_GATE_001", "v20_144_gate_consumed": tf(v144_gate_consumed), "v20_145_final_human_decision_capture_allowed_by_v144": tf(allowed), "selected_repair_scenario_id": selected_id, "final_human_decision_capture_created": "TRUE", "every_packet_has_explicit_human_decision": tf(every_packet_has_decision), "all_human_actions_allowed": tf(all_allowed), "evidence_acceptance": evidence_acceptance, "operator_acceptance": operator_acceptance, "promotion_ready": "FALSE", "promotion_readiness_recheck_allowed": tf(next_allowed), "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_146_promotion_readiness_recheck_allowed": tf(next_allowed), "next_recommended_action": "V20.146_PROMOTION_READINESS_RECHECK" if next_allowed else "V20.145_FINAL_HUMAN_DECISION_CAPTURE_REPAIR", "blocking_reason": blocking, "final_human_decision_capture_status": final_status, **COMMON}
    write_all([decision], explicit_rows, record_rows, validation_rows, consequence_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_144_GATE_CONSUMED={tf(v144_gate_consumed)}")
    print(f"V20_145_FINAL_HUMAN_DECISION_CAPTURE_ALLOWED_BY_V144={tf(allowed)}")
    print(f"V20_144_FINAL_STATUS={v144_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_144={tf(selected_matches)}")
    print(f"FINAL_HUMAN_CONFIRMATION_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"EXPLICIT_HUMAN_DECISION_INPUT_COUNT={len(explicit_rows)}")
    print(f"FINAL_HUMAN_DECISION_RECORD_COUNT={len(record_rows)}")
    print(f"EVERY_PACKET_HAS_EXPLICIT_HUMAN_DECISION={tf(every_packet_has_decision)}")
    print(f"ALL_HUMAN_ACTIONS_ALLOWED={tf(all_allowed)}")
    print(f"ACCEPT_WITH_LIMITATION_COUNT={accept_count}")
    print(f"REJECT_KEEP_BLOCKED_COUNT={reject_count}")
    print(f"MORE_EVIDENCE_REQUIRED_COUNT={more_count}")
    print(f"EVIDENCE_ACCEPTANCE={evidence_acceptance}")
    print(f"OPERATOR_ACCEPTANCE={operator_acceptance}")
    print("PROMOTION_READY=FALSE")
    print(f"PROMOTION_READINESS_RECHECK_ALLOWED={tf(next_allowed)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_146_PROMOTION_READINESS_RECHECK_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
