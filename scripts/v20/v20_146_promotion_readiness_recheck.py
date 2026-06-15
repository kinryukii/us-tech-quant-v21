#!/usr/bin/env python
"""V20.146 promotion-readiness recheck.

Performs only a readiness recheck after explicit V20.145 human decisions. This
stage may allow a later promotion-readiness packet, but it never creates
official artifacts, real-book actions, trades, broker actions, overwrites,
weight mutations, performance claims, or promotion readiness.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_CAPTURE_DECISION.csv"
IN_INPUT_AUDIT = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_INPUT_AUDIT.csv"
IN_INPUT_FALLBACK = CONSOLIDATION / "V20_145_EXPLICIT_HUMAN_DECISION_INPUT.csv"
IN_RECORD = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv"
IN_VALIDATION = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_VALIDATION_AUDIT.csv"
IN_CONSEQUENCE = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_CONSEQUENCE_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_145_NEXT_STAGE_GATE.csv"
IN_PACKET = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv"
IN_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"
IN_COVERAGE = CONSOLIDATION / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv"

OUT_DECISION = CONSOLIDATION / "V20_146_PROMOTION_READINESS_RECHECK_DECISION.csv"
OUT_DISPOSITION = CONSOLIDATION / "V20_146_BLOCKER_DISPOSITION_AUDIT.csv"
OUT_LIMITATION = CONSOLIDATION / "V20_146_LIMITATION_ACCEPTANCE_AUDIT.csv"
OUT_CRITERIA = CONSOLIDATION / "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_146_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_146_PROMOTION_READINESS_RECHECK_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V145_REQUIRED_STATUS = "PASS_V20_145_FINAL_HUMAN_DECISION_CAPTURE_READY_FOR_PROMOTION_READINESS_RECHECK"
PASS_STATUS = "PASS_V20_146_PROMOTION_READINESS_RECHECK_READY_FOR_V20_147"
PARTIAL_STATUS = "PARTIAL_PASS_V20_146_PROMOTION_READINESS_RECHECK_FAILED_BLOCKERS_REMAIN"
BLOCKED_STATUS = "BLOCKED_V20_146_PROMOTION_READINESS_RECHECK"
VALID_ACTIONS = ["ACCEPT_WITH_LIMITATION", "REJECT_KEEP_BLOCKED", "MORE_EVIDENCE_REQUIRED"]

REQUIRED_INPUTS = [IN_DECISION, IN_RECORD, IN_VALIDATION, IN_CONSEQUENCE, IN_SAFETY, IN_GATE, IN_PACKET, IN_REMAINING, IN_COVERAGE]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 146))
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
    "promotion_readiness_recheck_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_145_gate_consumed", "v20_146_promotion_readiness_recheck_allowed_by_v145", "v20_145_final_status", "v20_145_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_145", "final_human_decision_record_count", "blocker_disposition_row_count", "limitation_acceptance_row_count", "promotion_readiness_criteria_row_count", "all_remaining_blockers_have_explicit_human_decisions", "all_human_decisions_valid", "no_reject_keep_blocked", "no_more_evidence_required", "all_accept_with_limitation_rows_have_human_rationale", "evidence_acceptance", "operator_acceptance", "promotion_readiness_recheck_passed", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_147_promotion_readiness_packet_allowed", "promotion_readiness_recheck_status", "blocking_reason", *COMMON.keys()]
DISPOSITION_FIELDS = ["blocker_disposition_audit_id", "selected_repair_scenario_id", "source_final_human_decision_record_id", "blocker_id", "blocker_category", "selected_human_action", "human_rationale", "blocker_disposition", "promotion_readiness_recheck_passed", "evidence_acceptance", "operator_acceptance", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
LIMITATION_FIELDS = ["limitation_acceptance_audit_id", "selected_repair_scenario_id", "source_final_human_decision_record_id", "blocker_id", "blocker_category", "selected_human_action", "human_rationale_present", "limitation_accepted_for_recheck_only", "acceptance_scope", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
CRITERIA_FIELDS = ["promotion_readiness_criteria_audit_id", "selected_repair_scenario_id", "criterion_name", "criterion_passed", "criterion_observed_value", "criterion_required_value", "criterion_failure_blocks_pass", "promotion_readiness_recheck_passed", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_145_gate_consumed", "v20_146_promotion_readiness_recheck_allowed_by_v145", "selected_repair_scenario_id", "promotion_readiness_recheck_created", "promotion_readiness_recheck_passed", "promotion_ready", "evidence_acceptance", "operator_acceptance", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_147_promotion_readiness_packet_allowed", "next_recommended_action", "blocking_reason", "promotion_readiness_recheck_status", *COMMON.keys()]


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


def input_audit_path() -> Path:
    return IN_INPUT_AUDIT if IN_INPUT_AUDIT.exists() else IN_INPUT_FALLBACK


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
    return [{"safety_check_id": f"V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.146 performs only promotion-readiness recheck auditing and does not create official, real-book, trade, broker, overwrite, mutation, performance, or promotion-ready artifacts.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, disposition, limitation, criteria, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_DISPOSITION, DISPOSITION_FIELDS, disposition)
    write_csv(OUT_LIMITATION, LIMITATION_FIELDS, limitation)
    write_csv(OUT_CRITERIA, CRITERIA_FIELDS, criteria)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.146 Promotion Readiness Recheck Report", "",
        f"- wrapper_status: {decision.get('promotion_readiness_recheck_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- final_human_decision_record_count: {decision.get('final_human_decision_record_count')}",
        f"- blocker_disposition_row_count: {decision.get('blocker_disposition_row_count')}",
        f"- promotion_readiness_recheck_passed: {decision.get('promotion_readiness_recheck_passed')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_147_promotion_readiness_packet_allowed: {decision.get('v20_147_promotion_readiness_packet_allowed')}",
        "",
        "This is a readiness recheck only. It does not create official recommendations, rankings, weights, real-book actions, trades, broker actions, overwrites, weight mutations, performance claims, or promotion readiness.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_WEIGHT_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "TRADE_ACTION_CREATED", "BROKER_ACTION_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "WEIGHT_MUTATED", "PERFORMANCE_CLAIM_CREATED", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_146_PROMOTION_READINESS_RECHECK_DECISION_001", "v20_145_gate_consumed": "FALSE", "v20_146_promotion_readiness_recheck_allowed_by_v145": "FALSE", "v20_145_final_status": "", "v20_145_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_145": "FALSE", "final_human_decision_record_count": "0", "blocker_disposition_row_count": "0", "limitation_acceptance_row_count": "0", "promotion_readiness_criteria_row_count": "0", "all_remaining_blockers_have_explicit_human_decisions": "FALSE", "all_human_decisions_valid": "FALSE", "no_reject_keep_blocked": "FALSE", "no_more_evidence_required": "FALSE", "all_accept_with_limitation_rows_have_human_rationale": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_readiness_recheck_passed": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_147_promotion_readiness_packet_allowed": "FALSE", "promotion_readiness_recheck_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_146_NEXT_STAGE_GATE_001", "v20_145_gate_consumed": "FALSE", "v20_146_promotion_readiness_recheck_allowed_by_v145": "FALSE", "selected_repair_scenario_id": "", "promotion_readiness_recheck_created": "TRUE", "promotion_readiness_recheck_passed": "FALSE", "promotion_ready": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_147_promotion_readiness_packet_allowed": "FALSE", "next_recommended_action": "V20.146_PROMOTION_READINESS_RECHECK_REPAIR", "blocking_reason": blocking, "promotion_readiness_recheck_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_145_GATE_CONSUMED=FALSE")
    print("V20_147_PROMOTION_READINESS_PACKET_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def disposition_for(action: str) -> tuple[str, bool]:
    if action == "ACCEPT_WITH_LIMITATION":
        return "LIMITATION_ACCEPTED_FOR_PROMOTION_READINESS_RECHECK_ONLY", True
    if action == "REJECT_KEEP_BLOCKED":
        return "BLOCKED_BY_OPERATOR_REJECTION", False
    if action == "MORE_EVIDENCE_REQUIRED":
        return "BLOCKED_PENDING_MORE_EVIDENCE", False
    return "BLOCKED_INVALID_FINAL_HUMAN_DECISION", False


def build_disposition_and_limitation(selected_id: str, record_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    disposition_rows, limitation_rows = [], []
    for i, row in enumerate(record_rows, start=1):
        action = clean(row.get("selected_human_action"))
        disposition, passed = disposition_for(action)
        rationale = clean(row.get("human_rationale"))
        evidence_acceptance = "TRUE" if action == "ACCEPT_WITH_LIMITATION" and truthy(row.get("evidence_acceptance")) else "FALSE"
        operator_acceptance = "TRUE" if action == "ACCEPT_WITH_LIMITATION" and truthy(row.get("operator_acceptance")) else "FALSE"
        disposition_rows.append({
            "blocker_disposition_audit_id": f"V20_146_BLOCKER_DISPOSITION_AUDIT_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_final_human_decision_record_id": clean(row.get("final_human_decision_record_id")),
            "blocker_id": clean(row.get("blocker_id")),
            "blocker_category": clean(row.get("blocker_category")),
            "selected_human_action": action,
            "human_rationale": rationale,
            "blocker_disposition": disposition,
            "promotion_readiness_recheck_passed": tf(passed),
            "evidence_acceptance": evidence_acceptance,
            "operator_acceptance": operator_acceptance,
            "promotion_ready": "FALSE",
            "ticker_rows_created": "0",
            **COMMON,
        })
        if action == "ACCEPT_WITH_LIMITATION":
            limitation_rows.append({
                "limitation_acceptance_audit_id": f"V20_146_LIMITATION_ACCEPTANCE_AUDIT_{len(limitation_rows)+1:03d}",
                "selected_repair_scenario_id": selected_id,
                "source_final_human_decision_record_id": clean(row.get("final_human_decision_record_id")),
                "blocker_id": clean(row.get("blocker_id")),
                "blocker_category": clean(row.get("blocker_category")),
                "selected_human_action": action,
                "human_rationale_present": tf(bool(rationale)),
                "limitation_accepted_for_recheck_only": "TRUE",
                "acceptance_scope": "PROMOTION_READINESS_RECHECK_ONLY_NO_OFFICIAL_OR_REAL_BOOK_OR_TRADE_ACTIONS",
                "evidence_acceptance": evidence_acceptance,
                "operator_acceptance": operator_acceptance,
                "promotion_ready": "FALSE",
                **COMMON,
            })
    return disposition_rows, limitation_rows


def build_criteria(selected_id: str, criteria: list[tuple[str, bool, str, str]], passed: bool) -> list[dict[str, str]]:
    return [{
        "promotion_readiness_criteria_audit_id": f"V20_146_PROMOTION_READINESS_CRITERIA_AUDIT_{i:03d}",
        "selected_repair_scenario_id": selected_id,
        "criterion_name": name,
        "criterion_passed": tf(ok),
        "criterion_observed_value": observed,
        "criterion_required_value": required,
        "criterion_failure_blocks_pass": "TRUE",
        "promotion_readiness_recheck_passed": tf(passed),
        "promotion_ready": "FALSE",
        **COMMON,
    } for i, (name, ok, observed, required) in enumerate(criteria, start=1)]


def main() -> int:
    before_hashes = upstream_hashes()
    input_path = input_audit_path()
    required = REQUIRED_INPUTS + [input_path]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)

    decision_rows = read_csv(IN_DECISION)
    input_rows = read_csv(input_path)
    record_rows = read_csv(IN_RECORD)
    validation_rows = read_csv(IN_VALIDATION)
    consequence_rows = read_csv(IN_CONSEQUENCE)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    packet_rows = read_csv(IN_PACKET)
    remaining_rows = read_csv(IN_REMAINING)
    coverage_rows = read_csv(IN_COVERAGE)
    if not all([decision_rows, input_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_rows, remaining_rows, coverage_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v145_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_145_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_146_promotion_readiness_recheck_allowed"))
    v145_status = clean(gate_in.get("final_human_decision_capture_status")) or clean(decision_in.get("final_human_decision_capture_status"))
    v145_status_allowed = v145_status == V145_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))

    disposition_rows, limitation_rows = build_disposition_and_limitation(selected_id, record_rows)
    record_blockers = {clean(row.get("blocker_id")) for row in record_rows}
    input_blockers = {clean(row.get("blocker_id")) for row in input_rows}
    packet_blockers = {clean(row.get("blocker_id")) for row in packet_rows}
    all_explicit = bool(record_rows) and record_blockers == input_blockers == packet_blockers and all(clean(row.get("human_decision_source")) == "USER_PROVIDED_FINAL_HUMAN_CONFIRMATION_FOR_V20_145" for row in record_rows)
    all_valid_actions = all(clean(row.get("selected_human_action")) in VALID_ACTIONS for row in record_rows)
    no_reject = not any(clean(row.get("selected_human_action")) == "REJECT_KEEP_BLOCKED" for row in record_rows)
    no_more = not any(clean(row.get("selected_human_action")) == "MORE_EVIDENCE_REQUIRED" for row in record_rows)
    rationale_ok = all(clean(row.get("selected_human_action")) != "ACCEPT_WITH_LIMITATION" or bool(clean(row.get("human_rationale"))) for row in record_rows)
    evidence_acceptance_ok = bool(record_rows) and all(truthy(row.get("evidence_acceptance")) for row in record_rows)
    operator_acceptance_ok = bool(record_rows) and all(truthy(row.get("operator_acceptance")) for row in record_rows)
    validation_ok = bool(validation_rows) and all(truthy(row.get("human_decision_valid")) and truthy(row.get("explicit_human_decision_present")) for row in validation_rows)
    every_blocker_disposed = bool(disposition_rows) and len(disposition_rows) == len(record_rows) and {clean(row.get("blocker_id")) for row in disposition_rows} == record_blockers
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in record_rows + disposition_rows)
    counts = prohibited_counts([decision_rows, input_rows, record_rows, validation_rows, consequence_rows, safety_input_rows, gate_rows, packet_rows, remaining_rows, coverage_rows, disposition_rows, limitation_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0

    criteria_seed = [
        ("all_remaining_blockers_have_explicit_human_decisions", all_explicit, str(len(input_blockers)), str(len(packet_blockers))),
        ("all_final_human_decisions_are_valid_allowed_actions", all_valid_actions and validation_ok, ";".join(sorted({clean(row.get("selected_human_action")) for row in record_rows})), ";".join(VALID_ACTIONS)),
        ("no_blocker_is_reject_keep_blocked", no_reject, str(sum(1 for row in record_rows if clean(row.get("selected_human_action")) == "REJECT_KEEP_BLOCKED")), "0"),
        ("no_blocker_is_more_evidence_required", no_more, str(sum(1 for row in record_rows if clean(row.get("selected_human_action")) == "MORE_EVIDENCE_REQUIRED")), "0"),
        ("all_accept_with_limitation_rows_include_human_rationale", rationale_ok, str(sum(1 for row in record_rows if clean(row.get("selected_human_action")) == "ACCEPT_WITH_LIMITATION" and bool(clean(row.get("human_rationale"))))), str(sum(1 for row in record_rows if clean(row.get("selected_human_action")) == "ACCEPT_WITH_LIMITATION"))),
        ("evidence_acceptance_true_for_all_remaining_blockers", evidence_acceptance_ok, str(sum(1 for row in record_rows if truthy(row.get("evidence_acceptance")))), str(len(record_rows))),
        ("operator_acceptance_true_for_all_remaining_blockers", operator_acceptance_ok, str(sum(1 for row in record_rows if truthy(row.get("operator_acceptance")))), str(len(record_rows))),
        ("all_prohibited_action_flags_false", prohibited_count == 0, str(prohibited_count), "0"),
        ("no_ticker_rows_fabricated", ticker_count == 0, str(ticker_count), "0"),
        ("no_upstream_v20_109_through_v20_145_outputs_mutated", not upstream_mutation, tf(upstream_mutation), "FALSE"),
    ]
    criteria_without_pass = [ok for _, ok, _, _ in criteria_seed]
    recheck_passed = all([v145_gate_consumed, allowed, v145_status_allowed, selected_matches, every_blocker_disposed, safety_passed, *criteria_without_pass])
    criteria_rows = build_criteria(selected_id, criteria_seed, recheck_passed)
    safety_rows = build_safety(counts, safety_passed)
    blocked = not all([v145_gate_consumed, allowed, v145_status_allowed, selected_matches, safety_passed, not upstream_mutation])
    final_status = PASS_STATUS if recheck_passed else (BLOCKED_STATUS if blocked else PARTIAL_STATUS)
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else ("promotion_readiness_recheck_gate_or_safety_blocked" if blocked else "promotion_readiness_recheck_failed_blockers_remain")

    decision = {"decision_check_id": "V20_146_PROMOTION_READINESS_RECHECK_DECISION_001", "v20_145_gate_consumed": tf(v145_gate_consumed), "v20_146_promotion_readiness_recheck_allowed_by_v145": tf(allowed), "v20_145_final_status": v145_status, "v20_145_status_allowed": tf(v145_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_145": tf(selected_matches), "final_human_decision_record_count": str(len(record_rows)), "blocker_disposition_row_count": str(len(disposition_rows)), "limitation_acceptance_row_count": str(len(limitation_rows)), "promotion_readiness_criteria_row_count": str(len(criteria_rows)), "all_remaining_blockers_have_explicit_human_decisions": tf(all_explicit), "all_human_decisions_valid": tf(all_valid_actions and validation_ok), "no_reject_keep_blocked": tf(no_reject), "no_more_evidence_required": tf(no_more), "all_accept_with_limitation_rows_have_human_rationale": tf(rationale_ok), "evidence_acceptance": tf(evidence_acceptance_ok), "operator_acceptance": tf(operator_acceptance_ok), "promotion_readiness_recheck_passed": tf(recheck_passed), "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_147_promotion_readiness_packet_allowed": tf(next_allowed), "promotion_readiness_recheck_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_146_NEXT_STAGE_GATE_001", "v20_145_gate_consumed": tf(v145_gate_consumed), "v20_146_promotion_readiness_recheck_allowed_by_v145": tf(allowed), "selected_repair_scenario_id": selected_id, "promotion_readiness_recheck_created": "TRUE", "promotion_readiness_recheck_passed": tf(recheck_passed), "promotion_ready": "FALSE", "evidence_acceptance": tf(evidence_acceptance_ok), "operator_acceptance": tf(operator_acceptance_ok), "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_147_promotion_readiness_packet_allowed": tf(next_allowed), "next_recommended_action": "V20.147_PROMOTION_READINESS_PACKET" if next_allowed else "V20.146_BLOCKER_REMEDIATION_OR_FINAL_BLOCKED_REPORT", "blocking_reason": blocking, "promotion_readiness_recheck_status": final_status, **COMMON}
    write_all([decision], disposition_rows, limitation_rows, criteria_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_145_GATE_CONSUMED={tf(v145_gate_consumed)}")
    print(f"V20_146_PROMOTION_READINESS_RECHECK_ALLOWED_BY_V145={tf(allowed)}")
    print(f"V20_145_FINAL_STATUS={v145_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_145={tf(selected_matches)}")
    print(f"FINAL_HUMAN_DECISION_RECORD_COUNT={len(record_rows)}")
    print(f"BLOCKER_DISPOSITION_ROW_COUNT={len(disposition_rows)}")
    print(f"LIMITATION_ACCEPTANCE_ROW_COUNT={len(limitation_rows)}")
    print(f"PROMOTION_READINESS_CRITERIA_ROW_COUNT={len(criteria_rows)}")
    print(f"ALL_REMAINING_BLOCKERS_HAVE_EXPLICIT_HUMAN_DECISIONS={tf(all_explicit)}")
    print(f"ALL_HUMAN_DECISIONS_VALID={tf(all_valid_actions and validation_ok)}")
    print(f"NO_REJECT_KEEP_BLOCKED={tf(no_reject)}")
    print(f"NO_MORE_EVIDENCE_REQUIRED={tf(no_more)}")
    print(f"ALL_ACCEPT_WITH_LIMITATION_ROWS_HAVE_HUMAN_RATIONALE={tf(rationale_ok)}")
    print(f"EVIDENCE_ACCEPTANCE={tf(evidence_acceptance_ok)}")
    print(f"OPERATOR_ACCEPTANCE={tf(operator_acceptance_ok)}")
    print(f"PROMOTION_READINESS_RECHECK_PASSED={tf(recheck_passed)}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_147_PROMOTION_READINESS_PACKET_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
