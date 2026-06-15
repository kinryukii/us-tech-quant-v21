#!/usr/bin/env python
"""V20.120 operator decision record.

Creates audit-only operator decision records for unresolved V20.119 blocker
decisions. Conservative default is pending decisions and promotion_ready FALSE.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"

IN_DECISION = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_PACKAGE_DECISION.csv"
IN_SUMMARY = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_BLOCKER_SUMMARY.csv"
IN_MANIFEST = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_EVIDENCE_MANIFEST.csv"
IN_REQUIRED = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_REQUIRED_DECISIONS.csv"
IN_SAFETY = CONSOLIDATION / "V20_119_OPERATOR_REVIEW_SAFETY_BOUNDARY_AUDIT.csv"
IN_GATE = CONSOLIDATION / "V20_119_NEXT_STAGE_GATE.csv"

OUT_DECISION = CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD_DECISION.csv"
OUT_RECORD = CONSOLIDATION / "V20_120_OPERATOR_DECISION_RECORD.csv"
OUT_EVIDENCE = CONSOLIDATION / "V20_120_OPERATOR_DECISION_EVIDENCE_AUDIT.csv"
OUT_UNRESOLVED = CONSOLIDATION / "V20_120_UNRESOLVED_DECISION_AUDIT.csv"
OUT_SAFETY = CONSOLIDATION / "V20_120_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT.csv"
OUT_GATE = CONSOLIDATION / "V20_120_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_120_OPERATOR_DECISION_RECORD_REPORT.md"

EXPECTED_SCENARIO_ID = "R10_R2_REPAIR_001_MINIMUM_CHANGE_QUALITY_FLOOR"
V119_PASS_STATUS = "PASS_V20_119_OPERATOR_REVIEW_PACKAGE_READY_FOR_V20_120"
PASS_STATUS = "PASS_V20_120_OPERATOR_DECISION_RECORD_READY_FOR_V20_121"
PARTIAL_STATUS = "PARTIAL_PASS_V20_120_OPERATOR_DECISIONS_PENDING_READY_FOR_V20_121"
BLOCKED_STATUS = "BLOCKED_V20_120_OPERATOR_DECISION_RECORD"
REQUIRED_INPUTS = [IN_DECISION, IN_SUMMARY, IN_MANIFEST, IN_REQUIRED, IN_SAFETY, IN_GATE]
UPSTREAM_HASH_INPUTS = [
    CONSOLIDATION / "V20_109_R11_REPAIR_ROBUSTNESS_VALIDATION.csv",
    *[CONSOLIDATION / f"V20_{n}_NEXT_STAGE_GATE.csv" for n in ["110", "111", "112", "113", "114", "115", "116", "117", "118", "119"]],
    IN_DECISION, IN_SUMMARY, IN_MANIFEST, IN_REQUIRED,
]
PROHIBITED_FIELDS = [
    "accepted_weight_created", "accepted_weights_created", "real_book_weight_created", "real_book_action_created",
    "official_weight_created", "official_weights_created", "official_ranking_created", "official_rankings_created",
    "official_recommendation_created", "official_recommendations_created", "trade_action_created", "trade_actions_created",
    "broker_action_created", "broker_actions_created", "authoritative_overwrite_created", "authoritative_overwrites_created",
    "authoritative_ranking_overwritten", "weight_mutated", "weight_mutations_created", "performance_claim_created",
    "performance_claims_created", "performance_effectiveness_claim_created", "official_promotion_allowed", "is_official_weight",
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
    "promotion_ready": "FALSE", "research_only": "TRUE", "shadow_only": "TRUE", "operator_decision_record_only": "TRUE",
    "audit_only": "TRUE", "simulation_only": "TRUE",
}

DECISION_FIELDS = ["decision_check_id","v20_119_gate_consumed","v20_120_operator_decision_record_allowed_by_v119","v20_119_final_status","v20_119_status_passed","selected_repair_scenario_id","expected_selected_repair_scenario_id","selected_scenario_matches_v20_119","required_decision_count","operator_decision_record_created","operator_decision_record_count","evidence_audit_created","unresolved_decision_audit_created","pending_decision_count","accepted_decision_count","all_operator_decisions_accepted_with_valid_evidence","promotion_ready","fabricated_ticker_row_count","no_ticker_rows_fabricated","upstream_mutation_detected","no_upstream_outputs_mutated","safety_boundary_audit_passed","prohibited_action_true_count","v20_121_operator_decision_review_gate_allowed","operator_decision_record_status","blocking_reason",*COMMON.keys()]
RECORD_FIELDS = ["operator_decision_record_id","selected_repair_scenario_id","source_required_decision_id","blocker_category","decision_status","operator_acceptance","valid_acceptance_evidence","promotion_ready","evidence_manifest_linked","ticker_rows_created",*COMMON.keys()]
EVIDENCE_FIELDS = ["evidence_audit_id","selected_repair_scenario_id","blocker_category","evidence_manifest_row_count","evidence_linked","valid_acceptance_evidence","evidence_status",*COMMON.keys()]
UNRESOLVED_FIELDS = ["unresolved_decision_id","selected_repair_scenario_id","blocker_category","decision_status","unresolved_reason","promotion_ready","operator_review_required",*COMMON.keys()]
SAFETY_FIELDS = ["safety_check_id","prohibited_field","observed_true_count","safety_boundary_passed","safety_status","safety_reason",*COMMON.keys()]
GATE_FIELDS = ["gate_check_id","v20_119_gate_consumed","v20_120_operator_decision_record_allowed_by_v119","selected_repair_scenario_id","operator_decision_record_decision_created","all_operator_decisions_accepted_with_valid_evidence","promotion_ready","no_ticker_rows_fabricated","no_upstream_outputs_mutated","safety_boundary_audit_passed","v20_121_operator_decision_review_gate_allowed","next_recommended_action","blocking_reason","operator_decision_record_status",*COMMON.keys()]


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
    return [{"safety_check_id": f"V20_120_OPERATOR_DECISION_SAFETY_BOUNDARY_AUDIT_{i:03d}", "prohibited_field": field, "observed_true_count": str(counts.get(field, 0)), "safety_boundary_passed": tf(passed), "safety_status": "PASS" if passed else "BLOCKED", "safety_reason": "V20.120 records pending operator decisions only and creates no promotion or official artifacts.", **COMMON} for i, field in enumerate(PROHIBITED_FIELDS, start=1)]


def write_all(decision, records, evidence, unresolved, safety, gate) -> None:
    write_csv(OUT_DECISION, DECISION_FIELDS, decision)
    write_csv(OUT_RECORD, RECORD_FIELDS, records)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence)
    write_csv(OUT_UNRESOLVED, UNRESOLVED_FIELDS, unresolved)
    write_csv(OUT_SAFETY, SAFETY_FIELDS, safety)
    write_csv(OUT_GATE, GATE_FIELDS, gate)


def write_report(decision: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join([
        "# V20.120 Operator Decision Record Report", "",
        f"- wrapper_status: {decision.get('operator_decision_record_status')}",
        f"- selected_repair_scenario_id: {decision.get('selected_repair_scenario_id')}",
        f"- pending_decision_count: {decision.get('pending_decision_count')}",
        f"- promotion_ready: {decision.get('promotion_ready')}",
        f"- v20_121_operator_decision_review_gate_allowed: {decision.get('v20_121_operator_decision_review_gate_allowed')}",
        "- official_recommendation_created: FALSE", "- performance_claim_created: FALSE",
    ]) + "\n", encoding="utf-8")


def print_safety_stdout() -> None:
    for flag in ["ACCEPTED_WEIGHT_CREATED","ACCEPTED_WEIGHTS_CREATED","REAL_BOOK_WEIGHT_CREATED","REAL_BOOK_ACTION_CREATED","OFFICIAL_WEIGHT_CREATED","OFFICIAL_WEIGHTS_CREATED","OFFICIAL_RANKING_CREATED","OFFICIAL_RANKINGS_CREATED","OFFICIAL_RECOMMENDATION_CREATED","OFFICIAL_RECOMMENDATIONS_CREATED","TRADE_ACTION_CREATED","TRADE_ACTIONS_CREATED","BROKER_ACTION_CREATED","BROKER_ACTIONS_CREATED","AUTHORITATIVE_OVERWRITE_CREATED","AUTHORITATIVE_OVERWRITES_CREATED","AUTHORITATIVE_RANKING_OVERWRITTEN","WEIGHT_MUTATED","WEIGHT_MUTATIONS_CREATED","PERFORMANCE_CLAIM_CREATED","PERFORMANCE_CLAIMS_CREATED","PERFORMANCE_EFFECTIVENESS_CLAIM_CREATED","OFFICIAL_PROMOTION_ALLOWED","IS_OFFICIAL_WEIGHT","PROMOTION_READY"]:
        print(f"{flag}=FALSE")


def emit_blocked(reason: str, missing: list[Path] | None = None) -> int:
    missing_text = ";".join(display_path(path) for path in missing or [])
    blocking = reason if not missing_text else f"{reason}:{missing_text}"
    counts = {field: 0 for field in PROHIBITED_FIELDS}
    safety = build_safety(counts, False)
    decision = {"decision_check_id":"V20_120_OPERATOR_DECISION_RECORD_DECISION_001","v20_119_gate_consumed":"FALSE","v20_120_operator_decision_record_allowed_by_v119":"FALSE","v20_119_final_status":"","v20_119_status_passed":"FALSE","selected_repair_scenario_id":"","expected_selected_repair_scenario_id":EXPECTED_SCENARIO_ID,"selected_scenario_matches_v20_119":"FALSE","required_decision_count":"0","operator_decision_record_created":"FALSE","operator_decision_record_count":"0","evidence_audit_created":"FALSE","unresolved_decision_audit_created":"FALSE","pending_decision_count":"0","accepted_decision_count":"0","all_operator_decisions_accepted_with_valid_evidence":"FALSE","promotion_ready":"FALSE","fabricated_ticker_row_count":"0","no_ticker_rows_fabricated":"TRUE","upstream_mutation_detected":"FALSE","no_upstream_outputs_mutated":"TRUE","safety_boundary_audit_passed":"FALSE","prohibited_action_true_count":"0","v20_121_operator_decision_review_gate_allowed":"FALSE","operator_decision_record_status":BLOCKED_STATUS,"blocking_reason":blocking,**COMMON}
    gate = {"gate_check_id":"V20_120_NEXT_STAGE_GATE_001","v20_119_gate_consumed":"FALSE","v20_120_operator_decision_record_allowed_by_v119":"FALSE","selected_repair_scenario_id":"","operator_decision_record_decision_created":"TRUE","all_operator_decisions_accepted_with_valid_evidence":"FALSE","promotion_ready":"FALSE","no_ticker_rows_fabricated":"TRUE","no_upstream_outputs_mutated":"TRUE","safety_boundary_audit_passed":"FALSE","v20_121_operator_decision_review_gate_allowed":"FALSE","next_recommended_action":"V20.120_OPERATOR_DECISION_RECORD_REPAIR","blocking_reason":blocking,"operator_decision_record_status":BLOCKED_STATUS,**COMMON}
    write_all([decision], [], [], [], safety, [gate])
    write_report(decision)
    print(BLOCKED_STATUS)
    print("V20_119_GATE_CONSUMED=FALSE")
    print("V20_121_OPERATOR_DECISION_REVIEW_GATE_ALLOWED=FALSE")
    print_safety_stdout()
    return 0


def main() -> int:
    before_hashes = upstream_hashes()
    missing = [path for path in REQUIRED_INPUTS if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS", missing)
    decision_rows = read_csv(IN_DECISION)
    summary_rows = read_csv(IN_SUMMARY)
    manifest_rows = read_csv(IN_MANIFEST)
    required_rows = read_csv(IN_REQUIRED)
    safety_input_rows = read_csv(IN_SAFETY)
    gate_rows = read_csv(IN_GATE)
    if not all([decision_rows, summary_rows, manifest_rows, required_rows, safety_input_rows, gate_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    decision_in = first(decision_rows)
    gate_in = first(gate_rows)
    selected_id = clean(gate_in.get("selected_repair_scenario_id")) or clean(decision_in.get("selected_repair_scenario_id"))
    v119_gate_consumed = clean(gate_in.get("gate_check_id")) == "V20_119_NEXT_STAGE_GATE_001"
    allowed = truthy(gate_in.get("v20_120_operator_decision_record_allowed"))
    v119_status = clean(gate_in.get("operator_review_package_status")) or clean(decision_in.get("operator_review_package_status"))
    v119_passed = v119_status == V119_PASS_STATUS
    selected_matches = selected_id == EXPECTED_SCENARIO_ID and selected_id == clean(decision_in.get("selected_repair_scenario_id"))
    records = []
    evidence = []
    unresolved = []
    manifest_count = len(manifest_rows)
    for i, row in enumerate(required_rows, start=1):
        category = clean(row.get("blocker_category"))
        records.append({"operator_decision_record_id": f"V20_120_OPERATOR_DECISION_RECORD_{i:03d}", "selected_repair_scenario_id": selected_id, "source_required_decision_id": clean(row.get("required_decision_id")), "blocker_category": category, "decision_status": "PENDING_OPERATOR_DECISION", "operator_acceptance": "FALSE", "valid_acceptance_evidence": "FALSE", "evidence_manifest_linked": tf(manifest_count > 0), "ticker_rows_created": "0", **COMMON})
        evidence.append({"evidence_audit_id": f"V20_120_OPERATOR_DECISION_EVIDENCE_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "blocker_category": category, "evidence_manifest_row_count": str(manifest_count), "evidence_linked": tf(manifest_count > 0), "valid_acceptance_evidence": "FALSE", "evidence_status": "PENDING_OPERATOR_ACCEPTANCE_EVIDENCE", **COMMON})
        unresolved.append({"unresolved_decision_id": f"V20_120_UNRESOLVED_DECISION_AUDIT_{i:03d}", "selected_repair_scenario_id": selected_id, "blocker_category": category, "decision_status": "PENDING_OPERATOR_DECISION", "unresolved_reason": "No explicit human acceptance with valid evidence has been provided.", "operator_review_required": "TRUE", **COMMON})
    pending_count = len(unresolved)
    accepted_count = sum(1 for row in records if truthy(row.get("operator_acceptance")) and truthy(row.get("valid_acceptance_evidence")))
    all_accepted = bool(records) and accepted_count == len(records)
    promotion_ready = all_accepted
    ticker_count = sum(int(clean(row.get("ticker_rows_created")) or "0") for row in records)
    counts = prohibited_counts([decision_rows, summary_rows, manifest_rows, required_rows, safety_input_rows, gate_rows, records, evidence, unresolved])
    prohibited_count = sum(counts.values())
    upstream_safety = all(truthy(row.get("safety_boundary_passed")) for row in safety_input_rows)
    after_hashes = upstream_hashes()
    upstream_mutation = before_hashes != after_hashes
    safety_passed = upstream_safety and prohibited_count == 0
    safety = build_safety(counts, safety_passed)
    base_ok = all([v119_gate_consumed, allowed, v119_passed, selected_matches, bool(records), bool(evidence), bool(unresolved), ticker_count == 0, not upstream_mutation, safety_passed, prohibited_count == 0])
    status = PASS_STATUS if base_ok and promotion_ready else PARTIAL_STATUS if base_ok else BLOCKED_STATUS
    blocking = "" if status != BLOCKED_STATUS else "operator_decision_record_requirements_not_met"
    next_allowed = base_ok
    decision = {"decision_check_id":"V20_120_OPERATOR_DECISION_RECORD_DECISION_001","v20_119_gate_consumed":tf(v119_gate_consumed),"v20_120_operator_decision_record_allowed_by_v119":tf(allowed),"v20_119_final_status":v119_status,"v20_119_status_passed":tf(v119_passed),"selected_repair_scenario_id":selected_id,"expected_selected_repair_scenario_id":EXPECTED_SCENARIO_ID,"selected_scenario_matches_v20_119":tf(selected_matches),"required_decision_count":str(len(required_rows)),"operator_decision_record_created":tf(bool(records)),"operator_decision_record_count":str(len(records)),"evidence_audit_created":tf(bool(evidence)),"unresolved_decision_audit_created":tf(bool(unresolved)),"pending_decision_count":str(pending_count),"accepted_decision_count":str(accepted_count),"all_operator_decisions_accepted_with_valid_evidence":tf(all_accepted),"promotion_ready":tf(promotion_ready),"fabricated_ticker_row_count":str(ticker_count),"no_ticker_rows_fabricated":tf(ticker_count == 0),"upstream_mutation_detected":tf(upstream_mutation),"no_upstream_outputs_mutated":tf(not upstream_mutation),"safety_boundary_audit_passed":tf(safety_passed),"prohibited_action_true_count":str(prohibited_count),"v20_121_operator_decision_review_gate_allowed":tf(next_allowed),"operator_decision_record_status":status,"blocking_reason":blocking,**COMMON}
    gate = {"gate_check_id":"V20_120_NEXT_STAGE_GATE_001","v20_119_gate_consumed":tf(v119_gate_consumed),"v20_120_operator_decision_record_allowed_by_v119":tf(allowed),"selected_repair_scenario_id":selected_id,"operator_decision_record_decision_created":"TRUE","all_operator_decisions_accepted_with_valid_evidence":tf(all_accepted),"promotion_ready":tf(promotion_ready),"no_ticker_rows_fabricated":tf(ticker_count == 0),"no_upstream_outputs_mutated":tf(not upstream_mutation),"safety_boundary_audit_passed":tf(safety_passed),"v20_121_operator_decision_review_gate_allowed":tf(next_allowed),"next_recommended_action":"V20.121_OPERATOR_DECISION_REVIEW_GATE" if next_allowed else "V20.120_OPERATOR_DECISION_RECORD_REPAIR","blocking_reason":blocking,"operator_decision_record_status":status,**COMMON}
    write_all([decision], records, evidence, unresolved, safety, [gate])
    write_report(decision)
    print(status)
    print(f"V20_119_GATE_CONSUMED={tf(v119_gate_consumed)}")
    print(f"V20_120_OPERATOR_DECISION_RECORD_ALLOWED_BY_V119={tf(allowed)}")
    print(f"V20_119_FINAL_STATUS={v119_status}")
    print(f"SELECTED_REPAIR_SCENARIO_ID={selected_id}")
    print(f"SELECTED_SCENARIO_MATCHES_V20_119={tf(selected_matches)}")
    print(f"OPERATOR_DECISION_RECORD_CREATED={tf(bool(records))}")
    print(f"REQUIRED_DECISION_COUNT={len(required_rows)}")
    print(f"PENDING_DECISION_COUNT={pending_count}")
    print(f"ACCEPTED_DECISION_COUNT={accepted_count}")
    print(f"ALL_OPERATOR_DECISIONS_ACCEPTED_WITH_VALID_EVIDENCE={tf(all_accepted)}")
    print(f"PROMOTION_READY={tf(promotion_ready)}")
    print(f"FABRICATED_TICKER_ROW_COUNT={ticker_count}")
    print(f"UPSTREAM_MUTATION_DETECTED={tf(upstream_mutation)}")
    print(f"SAFETY_BOUNDARY_AUDIT_PASSED={tf(safety_passed)}")
    print(f"PROHIBITED_ACTION_TRUE_COUNT={prohibited_count}")
    print(f"V20_121_OPERATOR_DECISION_REVIEW_GATE_ALLOWED={tf(next_allowed)}")
    print_safety_stdout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
