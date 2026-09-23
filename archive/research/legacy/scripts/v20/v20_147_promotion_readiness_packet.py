#!/usr/bin/env python
"""V20.147 promotion-readiness packet.

Creates a promotion-readiness packet for later operator review. This stage is
packet-only and audit-only; it does not create promotion, official artifacts,
real-book actions, trades, broker actions, overwrites, weight mutations, or
performance claims.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_146_PROMOTION_READINESS_RECHECK_DECISION.csv"
IN_DISPOSITION = CONSOLIDATION / "V20_146_BLOCKER_DISPOSITION_AUDIT.csv"
IN_LIMITATION = CONSOLIDATION / "V20_146_LIMITATION_ACCEPTANCE_AUDIT.csv"
IN_CRITERIA = CONSOLIDATION / "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv"
IN_SAFETY = CONSOLIDATION / "V20_146_PROMOTION_READINESS_RECHECK_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_146_NEXT_STAGE_GATE.csv"
IN_V145_RECORD = CONSOLIDATION / "V20_145_FINAL_HUMAN_DECISION_RECORD.csv"
IN_V144_PACKET = CONSOLIDATION / "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv"
IN_V141_COVERAGE = CONSOLIDATION / "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv"
IN_V133_REMAINING = CONSOLIDATION / "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv"

OUT_DECISION = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET_DECISION.csv"
OUT_PACKET = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET.csv"
OUT_MANIFEST = CONSOLIDATION / "V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST.csv"
OUT_LIMITATION_SUMMARY = CONSOLIDATION / "V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY.csv"
OUT_SAFETY = CONSOLIDATION / "V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_147_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_147_PROMOTION_READINESS_PACKET_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V146_REQUIRED_STATUS = "PASS_V20_146_PROMOTION_READINESS_RECHECK_READY_FOR_V20_147"
PASS_STATUS = "PASS_V20_147_PROMOTION_READINESS_PACKET_READY_FOR_V20_148"
BLOCKED_STATUS = "BLOCKED_V20_147_PROMOTION_READINESS_PACKET"
REQUIRED_PACKET_SCOPE = "PROMOTION_READINESS_PACKET_ONLY_NOT_OFFICIAL_PROMOTION"
REQUIRED_NEXT_REVIEW_ACTION = "OPERATOR_REVIEW_OF_PROMOTION_READINESS_PACKET"
PACKET_SCOPE = REQUIRED_PACKET_SCOPE
NEXT_REVIEW_ACTION = REQUIRED_NEXT_REVIEW_ACTION

REQUIRED_INPUTS = [IN_DECISION, IN_DISPOSITION, IN_LIMITATION, IN_CRITERIA, IN_SAFETY, IN_GATE, IN_V145_RECORD, IN_V144_PACKET, IN_V141_COVERAGE, IN_V133_REMAINING]
UPSTREAM_HASH_INPUTS = sorted(
    path
    for path in CONSOLIDATION.glob("V20_*")
    if path.is_file() and any(path.name.startswith(f"V20_{stage}_") for stage in range(109, 147))
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
    "promotion_readiness_packet_only": "TRUE", "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id", "v20_146_gate_consumed", "v20_147_promotion_readiness_packet_allowed_by_v146", "v20_146_final_status", "v20_146_status_allowed", "selected_repair_scenario_id", "expected_selected_repair_scenario_id", "selected_scenario_matches_v20_146", "promotion_readiness_recheck_passed", "promotion_readiness_packet_row_count", "evidence_manifest_row_count", "limitation_summary_row_count", "packet_scope_valid", "allowed_next_review_action_valid", "evidence_acceptance", "operator_acceptance", "promotion_ready", "fabricated_ticker_row_count", "no_ticker_rows_fabricated", "upstream_mutation_detected", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "prohibited_action_true_count", "v20_148_promotion_readiness_operator_review_allowed", "promotion_readiness_packet_status", "blocking_reason", *COMMON.keys()]
PACKET_FIELDS = ["promotion_readiness_packet_id", "selected_repair_scenario_id", "source_recheck_status", "promotion_readiness_recheck_passed", "evidence_acceptance", "operator_acceptance", "accepted_blocker_count", "rejected_blocker_count", "more_evidence_required_blocker_count", "limitation_count", "criteria_pass_count", "criteria_fail_count", "remaining_limitation_summary", "readiness_packet_scope", "allowed_next_review_action", "promotion_ready", "ticker_rows_created", *COMMON.keys()]
MANIFEST_FIELDS = ["promotion_readiness_evidence_manifest_id", "selected_repair_scenario_id", "source_stage", "source_artifact", "source_record_id", "blocker_id", "blocker_category", "manifest_role", "promotion_ready", *COMMON.keys()]
LIMITATION_FIELDS = ["promotion_readiness_limitation_summary_id", "selected_repair_scenario_id", "source_limitation_acceptance_audit_id", "blocker_id", "blocker_category", "selected_human_action", "limitation_accepted_for_recheck_only", "acceptance_scope", "human_rationale_present", "limitation_summary", "evidence_acceptance", "operator_acceptance", "promotion_ready", *COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id", "prohibited_field", "observed_true_count", "safety_boundary_passed", "safety_status", "safety_reason", *COMMON.keys()]
GATE_FIELDS = ["gate_check_id", "v20_146_gate_consumed", "v20_147_promotion_readiness_packet_allowed_by_v146", "selected_repair_scenario_id", "promotion_readiness_packet_created", "promotion_readiness_recheck_passed", "promotion_ready", "evidence_acceptance", "operator_acceptance", "no_ticker_rows_fabricated", "no_upstream_outputs_mutated", "safety_boundary_audit_passed", "v20_148_promotion_readiness_operator_review_allowed", "next_recommended_action", "blocking_reason", "promotion_readiness_packet_status", *COMMON.keys()]


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
    return [{"safety_check_id": f"V20_147_PROMOTION_READINESS_PACKET_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.147 creates only a promotion-readiness packet for later operator review and keeps promotion readiness and all official/real-book/trade actions false.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, packet, manifest, limitations, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_MANIFEST, MANIFEST_FIELDS, manifest)
    write_csv(OUT_LIMITATION_SUMMARY, LIMITATION_FIELDS, limitations)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.147 Promotion Readiness Packet Report", "",
        f"- wrapper_status: {decision.get('promotion_readiness_packet_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- promotion_readiness_recheck_passed: {decision.get('promotion_readiness_recheck_passed')}",
        f"- promotion_readiness_packet_row_count: {decision.get('promotion_readiness_packet_row_count')}",
        f"- evidence_manifest_row_count: {decision.get('evidence_manifest_row_count')}",
        f"- limitation_summary_row_count: {decision.get('limitation_summary_row_count')}",
        f"- evidence_acceptance: {decision.get('evidence_acceptance')}",
        f"- operator_acceptance: {decision.get('operator_acceptance')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_148_promotion_readiness_operator_review_allowed: {decision.get('v20_148_promotion_readiness_operator_review_allowed')}",
        "",
        "This packet is for operator review only and is not official promotion.",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["OFFICIAL_RECOMMENDATION_CREATED", "OFFICIAL_RANKING_CREATED", "OFFICIAL_WEIGHT_CREATED", "REAL_BOOK_WEIGHT_CREATED", "REAL_BOOK_ACTION_CREATED", "TRADE_ACTION_CREATED", "BROKER_ACTION_CREATED", "AUTHORITATIVE_OVERWRITE_CREATED", "WEIGHT_MUTATED", "PERFORMANCE_CLAIM_CREATED", "PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    safety = build_safety({field: 0 for field in PROHIBITED_FIELDS}, False)
    decision = {"decision_check_id": "V20_147_PROMOTION_READINESS_PACKET_DECISION_001", "v20_146_gate_consumed": "FALSE", "v20_147_promotion_readiness_packet_allowed_by_v146": "FALSE", "v20_146_final_status": "", "v20_146_status_allowed": "FALSE", "selected_repair_scenario_id": "", "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_146": "FALSE", "promotion_readiness_recheck_passed": "FALSE", "promotion_readiness_packet_row_count": "0", "evidence_manifest_row_count": "0", "limitation_summary_row_count": "0", "packet_scope_valid": "FALSE", "allowed_next_review_action_valid": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "promotion_ready": "FALSE", "fabricated_ticker_row_count": "0", "no_ticker_rows_fabricated": "TRUE", "upstream_mutation_detected": "FALSE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "prohibited_action_true_count": "0", "v20_148_promotion_readiness_operator_review_allowed": "FALSE", "promotion_readiness_packet_status": BLOCKED_STATUS, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_147_NEXT_STAGE_GATE_001", "v20_146_gate_consumed": "FALSE", "v20_147_promotion_readiness_packet_allowed_by_v146": "FALSE", "selected_repair_scenario_id": "", "promotion_readiness_packet_created": "TRUE", "promotion_readiness_recheck_passed": "FALSE", "promotion_ready": "FALSE", "evidence_acceptance": "FALSE", "operator_acceptance": "FALSE", "no_ticker_rows_fabricated": "TRUE", "no_upstream_outputs_mutated": "TRUE", "safety_boundary_audit_passed": "FALSE", "v20_148_promotion_readiness_operator_review_allowed": "FALSE", "next_recommended_action": "V20.147_PROMOTION_READINESS_PACKET_REPAIR", "blocking_reason": blocking, "promotion_readiness_packet_status": BLOCKED_STATUS, **COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_146_GATE_CONSUMED=FALSE")
    print("V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def build_packet(selected_id: str, v146_status: str, recheck_passed: bool, disposition_rows: list[dict[str, str]], limitation_rows: list[dict[str, str]], criteria_rows: list[dict[str, str]], evidence_acceptance: bool, operator_acceptance: bool) -> list[dict[str, str]]:
    accepted = [row for row in disposition_rows if clean(row.get("blocker_disposition")) == "LIMITATION_ACCEPTED_FOR_PROMOTION_READINESS_RECHECK_ONLY"]
    rejected = [row for row in disposition_rows if clean(row.get("blocker_disposition")) == "BLOCKED_BY_OPERATOR_REJECTION"]
    more = [row for row in disposition_rows if clean(row.get("blocker_disposition")) == "BLOCKED_PENDING_MORE_EVIDENCE"]
    pass_count = sum(1 for row in criteria_rows if truthy(row.get("criterion_passed")))
    fail_count = sum(1 for row in criteria_rows if not truthy(row.get("criterion_passed")))
    limitation_summary = "; ".join(f"{clean(row.get('blocker_id'))}:{clean(row.get('acceptance_scope'))}" for row in limitation_rows)
    return [{
        "promotion_readiness_packet_id": "V20_147_PROMOTION_READINESS_PACKET_001",
        "selected_repair_scenario_id": selected_id,
        "source_recheck_status": v146_status,
        "promotion_readiness_recheck_passed": tf(recheck_passed),
        "evidence_acceptance": tf(evidence_acceptance),
        "operator_acceptance": tf(operator_acceptance),
        "accepted_blocker_count": str(len(accepted)),
        "rejected_blocker_count": str(len(rejected)),
        "more_evidence_required_blocker_count": str(len(more)),
        "limitation_count": str(len(limitation_rows)),
        "criteria_pass_count": str(pass_count),
        "criteria_fail_count": str(fail_count),
        "remaining_limitation_summary": limitation_summary,
        "readiness_packet_scope": PACKET_SCOPE,
        "allowed_next_review_action": NEXT_REVIEW_ACTION,
        "promotion_ready": "FALSE",
        "ticker_rows_created": "0",
        **COMMON,
    }]


def build_manifest(selected_id: str, disposition_rows: list[dict[str, str]], v145_rows: list[dict[str, str]], v144_rows: list[dict[str, str]], coverage_rows: list[dict[str, str]], remaining_rows: list[dict[str, str]], criteria_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    sources = [
        ("V20.133", "V20_133_REMAINING_EVIDENCE_BLOCKER_STATUS.csv", remaining_rows, "remaining_evidence_blocker_status_id", "BLOCKER_SOURCE"),
        ("V20.141", "V20_141_THIRD_ROUND_BLOCKER_COVERAGE_AUDIT.csv", coverage_rows, "third_round_blocker_coverage_audit_id", "THIRD_ROUND_BLOCKER_COVERAGE"),
        ("V20.144", "V20_144_FINAL_HUMAN_CONFIRMATION_PACKET.csv", v144_rows, "final_human_confirmation_packet_id", "FINAL_HUMAN_CONFIRMATION_PACKET"),
        ("V20.145", "V20_145_FINAL_HUMAN_DECISION_RECORD.csv", v145_rows, "final_human_decision_record_id", "FINAL_HUMAN_DECISION_RECORD"),
        ("V20.146", "V20_146_BLOCKER_DISPOSITION_AUDIT.csv", disposition_rows, "blocker_disposition_audit_id", "BLOCKER_DISPOSITION"),
        ("V20.146", "V20_146_PROMOTION_READINESS_CRITERIA_AUDIT.csv", criteria_rows, "promotion_readiness_criteria_audit_id", "PROMOTION_READINESS_CRITERIA"),
    ]
    for stage, artifact, source_rows, id_field, role in sources:
        for row in source_rows:
            rows.append({
                "promotion_readiness_evidence_manifest_id": f"V20_147_PROMOTION_READINESS_EVIDENCE_MANIFEST_{len(rows)+1:03d}",
                "selected_repair_scenario_id": selected_id,
                "source_stage": stage,
                "source_artifact": artifact,
                "source_record_id": clean(row.get(id_field)),
                "blocker_id": clean(row.get("blocker_id")) or clean(row.get("source_remaining_evidence_blocker_status_id")) or clean(row.get("remaining_evidence_blocker_status_id")),
                "blocker_category": clean(row.get("blocker_category")),
                "manifest_role": role,
                "promotion_ready": "FALSE",
                **COMMON,
            })
    return rows


def build_limitation_summary(selected_id: str, limitation_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for i, row in enumerate(limitation_rows, start=1):
        rows.append({
            "promotion_readiness_limitation_summary_id": f"V20_147_PROMOTION_READINESS_LIMITATION_SUMMARY_{i:03d}",
            "selected_repair_scenario_id": selected_id,
            "source_limitation_acceptance_audit_id": clean(row.get("limitation_acceptance_audit_id")),
            "blocker_id": clean(row.get("blocker_id")),
            "blocker_category": clean(row.get("blocker_category")),
            "selected_human_action": clean(row.get("selected_human_action")),
            "limitation_accepted_for_recheck_only": clean(row.get("limitation_accepted_for_recheck_only")),
            "acceptance_scope": clean(row.get("acceptance_scope")),
            "human_rationale_present": clean(row.get("human_rationale_present")),
            "limitation_summary": "Limitation accepted for promotion-readiness packet review only; no official promotion or operational action is authorized.",
            "evidence_acceptance": clean(row.get("evidence_acceptance")),
            "operator_acceptance": clean(row.get("operator_acceptance")),
            "promotion_ready": "FALSE",
            **COMMON,
        })
    return rows


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)
    decision_rows = read_csv(IN_DECISION)
    disposition_rows = read_csv(IN_DISPOSITION)
    limitation_rows = read_csv(IN_LIMITATION)
    criteria_rows = read_csv(IN_CRITERIA)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    v145_rows = read_csv(IN_V145_RECORD)
    v144_rows = read_csv(IN_V144_PACKET)
    coverage_rows = read_csv(IN_V141_COVERAGE)
    remaining_rows = read_csv(IN_V133_REMAINING)
    if not all([decision_rows, disposition_rows, limitation_rows, criteria_rows, safety_input_rows, gate_rows, v145_rows, v144_rows, coverage_rows, remaining_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v146_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_146_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_147_promotion_readiness_packet_allowed"))
    v146_status = clean(gate_in.get("promotion_readiness_recheck_status")) or clean(decision_in.get("promotion_readiness_recheck_status"))
    v146_status_allowed = v146_status == V146_REQUIRED_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    recheck_passed = truthy(gate_in.get("promotion_readiness_recheck_passed")) and truthy(decision_in.get("promotion_readiness_recheck_passed"))
    evidence_acceptance = truthy(gate_in.get("evidence_acceptance")) and truthy(decision_in.get("evidence_acceptance"))
    operator_acceptance = truthy(gate_in.get("operator_acceptance")) and truthy(decision_in.get("operator_acceptance"))

    packet_rows = build_packet(selected_id, v146_status, recheck_passed, disposition_rows, limitation_rows, criteria_rows, evidence_acceptance, operator_acceptance)
    manifest_rows = build_manifest(selected_id, disposition_rows, v145_rows, v144_rows, coverage_rows, remaining_rows, criteria_rows)
    limitation_summary_rows = build_limitation_summary(selected_id, limitation_rows)
    packet_scope_valid = len(packet_rows) == 1 and clean(packet_rows[0].get("readiness_packet_scope")) == REQUIRED_PACKET_SCOPE
    next_action_valid = len(packet_rows) == 1 and clean(packet_rows[0].get("allowed_next_review_action")) == REQUIRED_NEXT_REVIEW_ACTION
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in disposition_rows + packet_rows)
    counts = prohibited_counts([decision_rows, disposition_rows, limitation_rows, criteria_rows, safety_input_rows, gate_rows, v145_rows, v144_rows, coverage_rows, remaining_rows, packet_rows, manifest_rows, limitation_summary_rows])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety_rows = build_safety(counts, safety_passed)
    base_ok = all([v146_gate_consumed, allowed, v146_status_allowed, selected_matches, recheck_passed, len(packet_rows) == 1, bool(manifest_rows), bool(limitation_summary_rows), packet_scope_valid, next_action_valid, evidence_acceptance, operator_acceptance, ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    final_status = PASS_STATUS if base_ok else BLOCKED_STATUS
    next_allowed = final_status == PASS_STATUS
    blocking = "" if next_allowed else "promotion_readiness_packet_requirements_not_met"

    decision = {"decision_check_id": "V20_147_PROMOTION_READINESS_PACKET_DECISION_001", "v20_146_gate_consumed": tf(v146_gate_consumed), "v20_147_promotion_readiness_packet_allowed_by_v146": tf(allowed), "v20_146_final_status": v146_status, "v20_146_status_allowed": tf(v146_status_allowed), "selected_repair_scenario_id": selected_id, "expected_selected_repair_scenario_id": EXPECTED_SCENARIO_ID, "selected_scenario_matches_v20_146": tf(selected_matches), "promotion_readiness_recheck_passed": tf(recheck_passed), "promotion_readiness_packet_row_count": str(len(packet_rows)), "evidence_manifest_row_count": str(len(manifest_rows)), "limitation_summary_row_count": str(len(limitation_summary_rows)), "packet_scope_valid": tf(packet_scope_valid), "allowed_next_review_action_valid": tf(next_action_valid), "evidence_acceptance": tf(evidence_acceptance), "operator_acceptance": tf(operator_acceptance), "promotion_ready": "FALSE", "fabricated_ticker_row_count": str(ticker_count), "no_ticker_rows_fabricated": tf(ticker_count == 0), "upstream_mutation_detected": tf(upstream_mutation), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "prohibited_action_true_count": str(prohibited_count), "v20_148_promotion_readiness_operator_review_allowed": tf(next_allowed), "promotion_readiness_packet_status": final_status, "blocking_reason": blocking, **COMMON}
    gate = {"gate_check_id": "V20_147_NEXT_STAGE_GATE_001", "v20_146_gate_consumed": tf(v146_gate_consumed), "v20_147_promotion_readiness_packet_allowed_by_v146": tf(allowed), "selected_repair_scenario_id": selected_id, "promotion_readiness_packet_created": "TRUE", "promotion_readiness_recheck_passed": tf(recheck_passed), "promotion_ready": "FALSE", "evidence_acceptance": tf(evidence_acceptance), "operator_acceptance": tf(operator_acceptance), "no_ticker_rows_fabricated": tf(ticker_count == 0), "no_upstream_outputs_mutated": tf(not upstream_mutation), "safety_boundary_audit_passed": tf(safety_passed), "v20_148_promotion_readiness_operator_review_allowed": tf(next_allowed), "next_recommended_action": "V20.148_PROMOTION_READINESS_OPERATOR_REVIEW" if next_allowed else "V20.147_PROMOTION_READINESS_PACKET_REPAIR", "blocking_reason": blocking, "promotion_readiness_packet_status": final_status, **COMMON}
    write_all([decision], packet_rows, manifest_rows, limitation_summary_rows, safety_rows, [gate])
    write_report(decision)
    print(final_status)
    print(f"V20_146_GATE_CONSUMED={tf(v146_gate_consumed)}")
    print(f"V20_147_PROMOTION_READINESS_PACKET_ALLOWED_BY_V146={tf(allowed)}")
    print(f"V20_146_FINAL_STATUS={v146_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_146={tf(selected_matches)}")
    print(f"PROMOTION_READINESS_RECHECK_PASSED={tf(recheck_passed)}")
    print(f"PROMOTION_READINESS_PACKET_ROW_COUNT={len(packet_rows)}")
    print(f"EVIDENCE_MANIFEST_ROW_COUNT={len(manifest_rows)}")
    print(f"LIMITATION_SUMMARY_ROW_COUNT={len(limitation_summary_rows)}")
    print(f"PACKET_SCOPE_VALID={tf(packet_scope_valid)}")
    print(f"ALLOWED_NEXT_REVIEW_ACTION_VALID={tf(next_action_valid)}")
    print(f"EVIDENCE_ACCEPTANCE={tf(evidence_acceptance)}")
    print(f"OPERATOR_ACCEPTANCE={tf(operator_acceptance)}")
    print("PROMOTION_READY=FALSE")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_148_PROMOTION_READINESS_OPERATOR_REVIEW_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
