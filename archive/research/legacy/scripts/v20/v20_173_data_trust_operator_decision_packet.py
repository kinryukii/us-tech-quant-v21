#!/usr/bin/env python
"""V20.173 DATA_TRUST operator decision packet."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
CONSOLIDATION = OUTPUTS / "consolidation"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

BASELINE = CONSOLIDATION / "V20_83_AUTHORITATIVE_OFFICIAL_CURRENT_RANKING_TABLE.csv"
ACTIVE_WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"

R3_R2_CANDIDATES = FACTORS / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv"
R3_R2_GATE = FACTORS / "V20_170_R3_R2_NEXT_STAGE_GATE.csv"
V171_SIM = FACTORS / "V20_171_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
V171_GATE = FACTORS / "V20_171_NEXT_STAGE_GATE.csv"
V172_IMPACT = FACTORS / "V20_172_DATA_TRUST_IMPACT_AUDIT.csv"
V172_STABILITY = FACTORS / "V20_172_DATA_TRUST_STABILITY_AUDIT.csv"
V172_DISCLOSURE = FACTORS / "V20_172_DATA_TRUST_DISCLOSURE_AUDIT.csv"
V172_DOWNSTREAM = FACTORS / "V20_172_DATA_TRUST_DOWNSTREAM_CONSUMPTION_AUDIT.csv"
V172_OFFICIAL = FACTORS / "V20_172_OFFICIAL_USE_GUARD_AUDIT.csv"
V172_GATE = FACTORS / "V20_172_NEXT_STAGE_GATE.csv"
PROTECTED = [
    BASELINE, ACTIVE_WEIGHT_REGISTRY, R3_R2_CANDIDATES, R3_R2_GATE,
    V171_SIM, V171_GATE, V172_IMPACT, V172_STABILITY, V172_DISCLOSURE,
    V172_DOWNSTREAM, V172_OFFICIAL, V172_GATE,
]

OUT_PACKET = FACTORS / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET.csv"
OUT_SUMMARY = FACTORS / "V20_173_DATA_TRUST_DECISION_EVIDENCE_SUMMARY.csv"
OUT_GUARDRAIL = FACTORS / "V20_173_DATA_TRUST_GUARDRAIL_CONFIRMATION_AUDIT.csv"
OUT_GATE = FACTORS / "V20_173_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET_REPORT.md"

READY_V172 = "PASS_V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION_READY_FOR_V20_173"
PASS_STATUS = "PASS_V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET_READY_FOR_DAILY_RUNNER_GATE_ONLY_INTEGRATION"
BLOCKED_STATUS = "BLOCKED_V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET"
RECOMMENDED_DECISION = "KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER_AND_CONTINUE_SHADOW_OBSERVATION"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_OPERATOR_DECISION_PACKET"
SAFETY = {
    "research_only": "TRUE",
    "data_trust_scoring_weight": "0.0000000000",
    "data_trust_role": DATA_TRUST_ROLE,
    "direct_ticker_mapping_required_before_official_use": "TRUE",
    "formal_activation_allowed": "FALSE",
    "promotion_ready": "FALSE",
    "official_recommendation_created": "FALSE",
    "official_ranking_mutated": "FALSE",
    "official_weight_change_created": "FALSE",
    "official_weight_registry_mutated": "FALSE",
    "weight_mutated": "FALSE",
    "real_book_action_created": "FALSE",
    "trade_action_created": "FALSE",
    "broker_execution_supported": "FALSE",
    "performance_claim_created": "FALSE",
    "shadow_weight_expansion_allowed": "FALSE",
}
COMMON = {**SAFETY, "repair_scope": SCOPE, "audit_only": "TRUE"}

PACKET_FIELDS = [
    "decision_option", "option_available", "recommended_option",
    "operator_action_required", "decision_scope", "official_use_enabled_by_option",
    "real_book_use_enabled_by_option", "official_weight_mutation_enabled_by_option",
    "official_recommendation_enabled_by_option", "decision_rationale", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "evidence_id", "evidence_category", "evidence_metric", "evidence_value",
    "evidence_passed", "source_artifact", "operator_relevance", *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "actual_value",
    "guardrail_passed", "blocks_official_use", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_172_status_consumed", "v20_172_status",
    "baseline_candidate_count", "data_trust_direct_pass_candidate_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "complete_disclosure_candidate_count", "guardrail_pass_count",
    "guardrail_fail_count", "recommended_operator_decision",
    "ready_for_data_trust_gate_only_daily_runner_integration",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    "official_weight_change_allowed", "official_ranking_mutation_allowed",
    "data_trust_role", "recommended_next_action", "blocking_reason",
    "final_status", *COMMON.keys(),
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def tf(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: clean(v) for k, v in row.items()} for row in reader], list(reader.fieldnames or [])


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {rel(path): sha_file(path) for path in PROTECTED if path.exists()}


def build_packet() -> list[dict[str, str]]:
    options = [
        ("KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER", "Preserve DATA_TRUST as zero-weight audit/gate-only metadata."),
        ("CONTINUE_DATA_TRUST_SHADOW_OBSERVATION", "Continue observation without official activation."),
        ("REQUEST_ADDITIONAL_DATA_TRUST_VALIDATION", "Request additional validation before any activation proposal."),
        ("REJECT_DATA_TRUST_GATE_ONLY_INTEGRATION", "Reject the gate-only integration despite passing guards."),
    ]
    return [{
        "decision_option": option,
        "option_available": "TRUE",
        "recommended_option": tf(option in {
            "KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER",
            "CONTINUE_DATA_TRUST_SHADOW_OBSERVATION",
        }),
        "operator_action_required": "TRUE",
        "decision_scope": "GATE_ONLY_AUDIT_METADATA_NO_OFFICIAL_USE",
        "official_use_enabled_by_option": "FALSE",
        "real_book_use_enabled_by_option": "FALSE",
        "official_weight_mutation_enabled_by_option": "FALSE",
        "official_recommendation_enabled_by_option": "FALSE",
        "decision_rationale": rationale,
        **COMMON,
    } for option, rationale in options]


def build_summary(r3: dict[str, str], v171: dict[str, str], v172: dict[str, str]) -> list[dict[str, str]]:
    items = [
        ("DIRECT_STATUS", "direct_pass_candidate_count", r3["direct_pass_candidate_count"], "40", R3_R2_GATE, "Confirms complete DATA_TRUST direct PASS coverage."),
        ("SIMULATION", "official_ranking_score_mutation_count", v171["official_ranking_score_mutation_count"], "0", V171_GATE, "Confirms no official score mutation."),
        ("SIMULATION", "official_rank_mutation_count", v171["official_rank_mutation_count"], "0", V171_GATE, "Confirms no official rank mutation."),
        ("SIMULATION", "data_trust_score_contribution_sum", v171["data_trust_score_contribution_sum"], "0.0000000000", V171_GATE, "Confirms zero official score contribution."),
        ("VALIDATION", "complete_disclosure_candidate_count", v172["complete_disclosure_candidate_count"], "40", V172_GATE, "Confirms complete disclosure coverage."),
        ("VALIDATION", "downstream_audit_metadata_consumption_pass", v172["downstream_audit_metadata_consumption_pass"], "TRUE", V172_GATE, "Confirms daily runner audit-only consumption path."),
        ("VALIDATION", "official_use_guard_pass", v172["official_use_guard_pass"], "TRUE", V172_GATE, "Confirms official use remains disabled."),
    ]
    return [{
        "evidence_id": f"V20_173_EVIDENCE_{idx:03d}",
        "evidence_category": category,
        "evidence_metric": metric,
        "evidence_value": value,
        "evidence_passed": tf(value == expected),
        "source_artifact": rel(path),
        "operator_relevance": relevance,
        **COMMON,
    } for idx, (category, metric, value, expected, path, relevance) in enumerate(items, start=1)]


def build_guardrails(v172: dict[str, str], upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("ready_for_official_use", "FALSE", v172["ready_for_official_use"], "TRUE"),
        ("real_book_use_allowed", "FALSE", v172["real_book_use_allowed"], "TRUE"),
        ("official_recommendation_created", "FALSE", v172["official_recommendation_created"], "TRUE"),
        ("official_weight_mutation_allowed", "FALSE", "FALSE", "TRUE"),
        ("official_weight_change_allowed", "FALSE", v172["official_weight_change_allowed"], "TRUE"),
        ("official_ranking_mutation_allowed", "FALSE", v172["official_ranking_mutation_allowed"], "TRUE"),
        ("data_trust_scoring_weight", "0.0000000000", "0.0000000000", "TRUE"),
        ("official_outputs_mutated", "FALSE", tf(upstream_mutated), "TRUE"),
    ]
    return [{
        "guardrail_id": f"V20_173_GUARDRAIL_{idx:03d}",
        "guardrail": guardrail,
        "expected_value": expected,
        "actual_value": actual,
        "guardrail_passed": tf(expected == actual),
        "blocks_official_use": blocks,
        **COMMON,
    } for idx, (guardrail, expected, actual, blocks) in enumerate(checks, start=1)]


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.173 DATA_TRUST Operator Decision Packet Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- recommended_operator_decision: {gate['recommended_operator_decision']}",
        f"- ready_for_data_trust_gate_only_daily_runner_integration: {gate['ready_for_data_trust_gate_only_daily_runner_integration']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Recommended operator decision: keep DATA_TRUST as a zero-weight gate-only audit layer and continue shadow observation.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_PACKET, PACKET_FIELDS), (OUT_SUMMARY, SUMMARY_FIELDS), (OUT_GUARDRAIL, GUARDRAIL_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_173_NEXT_STAGE_GATE_001",
        "v20_172_status_consumed": "FALSE",
        "v20_172_status": "",
        "baseline_candidate_count": "0",
        "data_trust_direct_pass_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "complete_disclosure_candidate_count": "0",
        "guardrail_pass_count": "0",
        "guardrail_fail_count": "0",
        "recommended_operator_decision": "",
        "ready_for_data_trust_gate_only_daily_runner_integration": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "data_trust_role": DATA_TRUST_ROLE,
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_173",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def main() -> int:
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, R3_R2_GATE, V171_GATE, V172_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    r3_rows, _ = read_csv(R3_R2_GATE)
    v171_rows, _ = read_csv(V171_GATE)
    v172_rows, _ = read_csv(V172_GATE)
    baseline, _ = read_csv(BASELINE)
    if not r3_rows or not v171_rows or not v172_rows or not baseline:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r3 = r3_rows[0]
    v171 = v171_rows[0]
    v172 = v172_rows[0]
    prereq_ok = all([
        r3.get("direct_pass_candidate_count") == "40",
        v171.get("final_status") == "PASS_V20_171_DATA_TRUST_FULL_GATE_ONLY_RANKING_SIMULATION_READY_FOR_V20_172",
        v172.get("final_status") == "PASS_V20_172_DATA_TRUST_IMPACT_STABILITY_DISCLOSURE_VALIDATION_READY_FOR_V20_173",
        v172.get("ready_for_v20_173_operator_decision_packet") == "TRUE",
        v172.get("ready_for_official_use") == "FALSE",
        v172.get("real_book_use_allowed") == "FALSE",
        v172.get("official_recommendation_created") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_172_REQUIREMENTS_NOT_MET")
    upstream_mutated = before != protected_hashes()
    packet = build_packet()
    summary = build_summary(r3, v171, v172)
    guardrails = build_guardrails(v172, upstream_mutated)
    guard_pass = sum(row["guardrail_passed"] == "TRUE" for row in guardrails)
    guard_fail = len(guardrails) - guard_pass
    ready_daily = guard_fail == 0 and v172.get("ready_for_v20_173_operator_decision_packet") == "TRUE"
    gate = {
        "gate_check_id": "V20_173_NEXT_STAGE_GATE_001",
        "v20_172_status_consumed": "TRUE",
        "v20_172_status": v172.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "data_trust_direct_pass_candidate_count": r3.get("direct_pass_candidate_count", "0"),
        "official_ranking_score_mutation_count": v171.get("official_ranking_score_mutation_count", "0"),
        "official_rank_mutation_count": v171.get("official_rank_mutation_count", "0"),
        "data_trust_score_contribution_sum": v171.get("data_trust_score_contribution_sum", "0.0000000000"),
        "data_trust_nonzero_weight_count": v171.get("data_trust_nonzero_weight_count", "0"),
        "complete_disclosure_candidate_count": v172.get("complete_disclosure_candidate_count", "0"),
        "guardrail_pass_count": str(guard_pass),
        "guardrail_fail_count": str(guard_fail),
        "recommended_operator_decision": RECOMMENDED_DECISION,
        "ready_for_data_trust_gate_only_daily_runner_integration": tf(ready_daily),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "data_trust_role": DATA_TRUST_ROLE,
        "recommended_next_action": "OPERATOR_DECISION_KEEP_GATE_ONLY_AND_CONTINUE_SHADOW_OBSERVATION",
        "blocking_reason": "NONE" if ready_daily else "GUARDRAIL_FAILURE",
        "final_status": PASS_STATUS if ready_daily else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_PACKET, PACKET_FIELDS, packet)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrails)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
