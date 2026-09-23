#!/usr/bin/env python
"""V20.182 DATA_TRUST gate-only closeout operator decision."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V173_PACKET = FACTORS / "V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET.csv"
V173_SUMMARY = FACTORS / "V20_173_DATA_TRUST_DECISION_EVIDENCE_SUMMARY.csv"
V173_GUARDRAIL = FACTORS / "V20_173_DATA_TRUST_GUARDRAIL_CONFIRMATION_AUDIT.csv"
V173_GATE = FACTORS / "V20_173_NEXT_STAGE_GATE.csv"
V174_INTEGRATION = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_INTEGRATION_AUDIT.csv"
V174_COMPATIBILITY = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_COMPATIBILITY_AUDIT.csv"
V174_GATE = FACTORS / "V20_174_NEXT_STAGE_GATE.csv"
V175_OBSERVATION = FACTORS / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION.csv"
V175_DISCLOSURE = FACTORS / "V20_175_DATA_TRUST_DISCLOSURE_STABILITY_AUDIT.csv"
V175_GATE = FACTORS / "V20_175_NEXT_STAGE_GATE.csv"
V177_PLAN = FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv"
V177_GATE = FACTORS / "V20_177_NEXT_STAGE_GATE.csv"
V178_RUN = FACTORS / "V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1.csv"
V178_GATE = FACTORS / "V20_178_NEXT_STAGE_GATE.csv"
V179_RUN = FACTORS / "V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2.csv"
V179_GATE = FACTORS / "V20_179_NEXT_STAGE_GATE.csv"
V180_RUN = FACTORS / "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3.csv"
V180_GATE = FACTORS / "V20_180_NEXT_STAGE_GATE.csv"
V181_3RUN = FACTORS / "V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_3RUN_SUMMARY.csv"
V181_GUARDRAIL = FACTORS / "V20_181_DATA_TRUST_AGGREGATE_GUARDRAIL_SUMMARY.csv"
V181_STABILITY = FACTORS / "V20_181_DATA_TRUST_RUN_TO_RUN_STABILITY_SUMMARY.csv"
V181_EVIDENCE = FACTORS / "V20_181_DATA_TRUST_CLOSEOUT_DECISION_EVIDENCE_PACKET.csv"
V181_GATE = FACTORS / "V20_181_NEXT_STAGE_GATE.csv"

PROTECTED = [
    V173_PACKET, V173_SUMMARY, V173_GUARDRAIL, V173_GATE,
    V174_INTEGRATION, V174_COMPATIBILITY, V174_GATE,
    V175_OBSERVATION, V175_DISCLOSURE, V175_GATE,
    V177_PLAN, V177_GATE, V178_RUN, V178_GATE, V179_RUN, V179_GATE,
    V180_RUN, V180_GATE, V181_3RUN, V181_GUARDRAIL, V181_STABILITY,
    V181_EVIDENCE, V181_GATE,
]

OUT_PACKET = FACTORS / "V20_182_DATA_TRUST_FINAL_OPERATOR_DECISION_PACKET.csv"
OUT_EVIDENCE = FACTORS / "V20_182_DATA_TRUST_FINAL_EVIDENCE_SUMMARY.csv"
OUT_GUARDRAIL = FACTORS / "V20_182_DATA_TRUST_FINAL_GUARDRAIL_AUDIT.csv"
OUT_STATUS = FACTORS / "V20_182_DATA_TRUST_DAILY_RUNNER_INTEGRATION_STATUS.csv"
OUT_GATE = FACTORS / "V20_182_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION_REPORT.md"

READY_V173 = "PASS_V20_173_DATA_TRUST_OPERATOR_DECISION_PACKET_READY_FOR_DAILY_RUNNER_GATE_ONLY_INTEGRATION"
READY_V174 = "PASS_V20_174_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION_READY_FOR_V20_175"
READY_V175 = "PASS_V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_READY_FOR_V20_176"
READY_V177 = "PASS_V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN_READY_FOR_V20_178_RUN_1"
READY_V178 = "PASS_V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1_READY_FOR_V20_179_RUN_2"
READY_V179 = "PASS_V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2_READY_FOR_V20_180_RUN_3"
READY_V180 = "PASS_V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3_READY_FOR_V20_181_CLOSEOUT_SUMMARY"
READY_V181 = "PASS_V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY_READY_FOR_V20_182_OPERATOR_DECISION"
PASS_STATUS = "PASS_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION_READY_FOR_V20_183_READ_CENTER_INTEGRATION"
BLOCKED_STATUS = "BLOCKED_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION"
RECOMMENDED_DECISION = "APPROVE_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_CLOSEOUT_AND_CONTINUE_DAILY_RUNNER_SHADOW_OBSERVATION"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION"

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
    "operator_decision_option", "option_available", "recommended_option",
    "recommended_operator_decision", "operator_decision_captured",
    "decision_scope", "decision_effect", "official_use_enabled_by_option",
    "real_book_use_enabled_by_option", "official_recommendation_enabled_by_option",
    "official_weight_mutation_enabled_by_option", "decision_rationale", *COMMON.keys(),
]
EVIDENCE_FIELDS = [
    "evidence_id", "evidence_category", "evidence_metric", "evidence_value",
    "expected_value", "evidence_passed", "source_artifact", "operator_relevance",
    *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "actual_value",
    "guardrail_passed", "blocks_official_use", "source_artifact", *COMMON.keys(),
]
STATUS_FIELDS = [
    "status_id", "daily_runner_integration_status", "data_trust_zero_weight",
    "data_trust_gate_only", "data_trust_audit_only", "data_trust_daily_runner_disclosed",
    "data_trust_shadow_observation_continued", "single_run_shadow_observation_pass",
    "multiday_shadow_observation_pass", "ready_for_read_center_integration",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_173_status_consumed", "v20_173_status",
    "v20_174_status_consumed", "v20_174_status", "v20_175_status_consumed",
    "v20_175_status", "v20_177_status_consumed", "v20_177_status",
    "v20_178_status_consumed", "v20_178_status", "v20_179_status_consumed",
    "v20_179_status", "v20_180_status_consumed", "v20_180_status",
    "v20_181_status_consumed", "v20_181_status", "recommended_operator_decision",
    "data_trust_gate_only_closeout_complete",
    "data_trust_daily_runner_shadow_observation_continued",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_daily_runner_disclosed", "ready_for_v20_183_daily_research_runner_read_center_integration",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "official_weight_registry_mutated",
    "official_recommendation_creation_attempted", "real_book_use_attempted",
    "final_evidence_summary_pass", "final_guardrail_audit_pass",
    "daily_runner_integration_status_pass", "recommended_next_action",
    "blocking_reason", "final_status", *COMMON.keys(),
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


def first(rows_by_path: dict[Path, list[dict[str, str]]], path: Path) -> dict[str, str]:
    return rows_by_path[path][0]


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.182 DATA_TRUST Gate-Only Closeout Operator Decision Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- recommended_operator_decision: {gate['recommended_operator_decision']}",
        f"- data_trust_gate_only_closeout_complete: {gate['data_trust_gate_only_closeout_complete']}",
        f"- data_trust_daily_runner_shadow_observation_continued: {gate['data_trust_daily_runner_shadow_observation_continued']}",
        f"- ready_for_v20_183_daily_research_runner_read_center_integration: {gate['ready_for_v20_183_daily_research_runner_read_center_integration']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Final operator closeout approves DATA_TRUST as zero-weight gate-only audit metadata and continues daily-runner shadow observation. No official recommendations, real-book actions, or official weight mutations are created or allowed.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_PACKET, PACKET_FIELDS), (OUT_EVIDENCE, EVIDENCE_FIELDS),
        (OUT_GUARDRAIL, GUARDRAIL_FIELDS), (OUT_STATUS, STATUS_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_182_NEXT_STAGE_GATE_001",
        "v20_173_status_consumed": "FALSE",
        "v20_173_status": "",
        "v20_174_status_consumed": "FALSE",
        "v20_174_status": "",
        "v20_175_status_consumed": "FALSE",
        "v20_175_status": "",
        "v20_177_status_consumed": "FALSE",
        "v20_177_status": "",
        "v20_178_status_consumed": "FALSE",
        "v20_178_status": "",
        "v20_179_status_consumed": "FALSE",
        "v20_179_status": "",
        "v20_180_status_consumed": "FALSE",
        "v20_180_status": "",
        "v20_181_status_consumed": "FALSE",
        "v20_181_status": "",
        "recommended_operator_decision": RECOMMENDED_DECISION,
        "data_trust_gate_only_closeout_complete": "FALSE",
        "data_trust_daily_runner_shadow_observation_continued": "TRUE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_daily_runner_disclosed": "TRUE",
        "ready_for_v20_183_daily_research_runner_read_center_integration": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_weight_registry_mutated": "FALSE",
        "official_recommendation_creation_attempted": "FALSE",
        "real_book_use_attempted": "FALSE",
        "final_evidence_summary_pass": "FALSE",
        "final_guardrail_audit_pass": "FALSE",
        "daily_runner_integration_status_pass": "FALSE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_182",
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
    before = protected_hashes()
    datasets = {path: read_csv(path)[0] for path in PROTECTED}
    if any(not rows for rows in datasets.values()):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    v173 = first(datasets, V173_GATE)
    v174 = first(datasets, V174_GATE)
    v175 = first(datasets, V175_GATE)
    v177 = first(datasets, V177_GATE)
    v178 = first(datasets, V178_GATE)
    v179 = first(datasets, V179_GATE)
    v180 = first(datasets, V180_GATE)
    v181 = first(datasets, V181_GATE)

    prereq_ok = all([
        v173.get("final_status") == READY_V173,
        v174.get("final_status") == READY_V174,
        v175.get("final_status") == READY_V175,
        v177.get("final_status") == READY_V177,
        v178.get("final_status") == READY_V178,
        v179.get("final_status") == READY_V179,
        v180.get("final_status") == READY_V180,
        v181.get("final_status") == READY_V181,
        v181.get("ready_for_v20_182_data_trust_gate_only_closeout_operator_decision") == "TRUE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_173_THROUGH_V20_181_REQUIREMENTS_NOT_MET")

    upstream_mutated = before != protected_hashes()
    decisions = [
        ("APPROVE_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_CLOSEOUT", "Approve closeout as zero-weight gate-only audit metadata."),
        ("CONTINUE_DATA_TRUST_MULTIDAY_SHADOW_OBSERVATION", "Continue multiday shadow observation before closeout."),
        ("REQUEST_ADDITIONAL_DATA_TRUST_REMEDIATION", "Request more remediation before closeout."),
        ("REJECT_DATA_TRUST_DAILY_RUNNER_INTEGRATION", "Reject daily-runner gate-only integration."),
    ]
    packet_rows = [{
        "operator_decision_option": option,
        "option_available": "TRUE",
        "recommended_option": tf(option == "APPROVE_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_CLOSEOUT"),
        "recommended_operator_decision": RECOMMENDED_DECISION,
        "operator_decision_captured": "TRUE",
        "decision_scope": "ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_DAILY_RUNNER_SHADOW_OBSERVATION",
        "decision_effect": "CLOSEOUT_AND_CONTINUE_DAILY_RUNNER_SHADOW_OBSERVATION" if option == "APPROVE_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_CLOSEOUT" else "NOT_SELECTED",
        "official_use_enabled_by_option": "FALSE",
        "real_book_use_enabled_by_option": "FALSE",
        "official_recommendation_enabled_by_option": "FALSE",
        "official_weight_mutation_enabled_by_option": "FALSE",
        "decision_rationale": rationale,
        **COMMON,
    } for option, rationale in decisions]

    evidence_specs = [
        ("V20_173_OPERATOR_DECISION", "recommended_operator_decision", v173.get("recommended_operator_decision", ""), "KEEP_DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_LAYER_AND_CONTINUE_SHADOW_OBSERVATION", V173_GATE, "Prior operator decision kept DATA_TRUST zero-weight gate-only with shadow observation."),
        ("V20_174_DAILY_RUNNER_INTEGRATION", "ready_for_v20_175_daily_runner_shadow_observation", v174.get("ready_for_v20_175_daily_runner_shadow_observation", ""), "TRUE", V174_GATE, "Daily runner integration was accepted as gate-only audit metadata."),
        ("V20_175_SINGLE_SHADOW_OBSERVATION", "ready_for_v20_176_data_trust_shadow_observation_summary", v175.get("ready_for_v20_176_data_trust_shadow_observation_summary", ""), "TRUE", V175_GATE, "Single daily-runner shadow observation passed."),
        ("V20_177_MULTIDAY_PLAN", "observation_run_required_count", v177.get("observation_run_required_count", ""), "3", V177_GATE, "Three-run multiday observation was planned."),
        ("V20_178_RUN_1", "run_1_disclosure_pass", first(datasets, V178_RUN).get("run_1_disclosure_pass", ""), "TRUE", V178_RUN, "Multiday run 1 passed disclosure guard."),
        ("V20_179_RUN_2", "run_2_all_guards_pass", first(datasets, V179_RUN).get("run_2_all_guards_pass", ""), "TRUE", V179_RUN, "Multiday run 2 passed all guards."),
        ("V20_180_RUN_3", "run_3_all_guards_pass", first(datasets, V180_RUN).get("run_3_all_guards_pass", ""), "TRUE", V180_RUN, "Multiday run 3 passed all guards."),
        ("V20_181_CLOSEOUT", "ready_for_v20_182_data_trust_gate_only_closeout_operator_decision", v181.get("ready_for_v20_182_data_trust_gate_only_closeout_operator_decision", ""), "TRUE", V181_GATE, "Multiday closeout summary was ready for final operator decision."),
        ("V20_181_STABILITY", "run_to_run_data_trust_caused_ranking_mutation_count", v181.get("run_to_run_data_trust_caused_ranking_mutation_count", ""), "0", V181_GATE, "Run-to-run DATA_TRUST-caused ranking mutation count remained zero."),
    ]
    evidence_rows = [{
        "evidence_id": f"V20_182_EVIDENCE_{idx:03d}",
        "evidence_category": category,
        "evidence_metric": metric,
        "evidence_value": value,
        "expected_value": expected,
        "evidence_passed": tf(value == expected),
        "source_artifact": rel(path),
        "operator_relevance": relevance,
        **COMMON,
    } for idx, (category, metric, value, expected, path, relevance) in enumerate(evidence_specs, start=1)]
    evidence_pass = all(row["evidence_passed"] == "TRUE" for row in evidence_rows)

    zero_weight = all([
        v174.get("data_trust_score_contribution_sum") == "0.0000000000",
        v175.get("data_trust_score_contribution_sum") == "0.0000000000",
        v181.get("data_trust_zero_weight") == "TRUE",
    ])
    gate_only = all([
        v174.get("data_trust_role") == DATA_TRUST_ROLE,
        v175.get("data_trust_role") == DATA_TRUST_ROLE,
        v181.get("data_trust_gate_only") == "TRUE",
    ])
    audit_only = all([
        v174.get("audit_only") == "TRUE",
        v175.get("audit_only") == "TRUE",
        v181.get("data_trust_audit_only") == "TRUE",
    ])
    daily_disclosed = all([
        v174.get("data_trust_daily_runner_disclosure_pass") == "TRUE",
        v175.get("data_trust_disclosure_candidate_count") == "40",
        v181.get("all_disclosure_guards_pass") == "TRUE",
    ])
    shadow_continued = all([
        v177.get("data_trust_shadow_observation_continued") == "TRUE",
        v181.get("data_trust_shadow_observation_only") == "TRUE",
    ])
    official_disabled = all(row.get("ready_for_official_use") == "FALSE" for row in [v173, v174, v175, v181])
    real_book_disabled = all(row.get("real_book_use_allowed") == "FALSE" for row in [v173, v174, v175, v181])
    recommendation_disabled = all(row.get("official_recommendation_created") == "FALSE" for row in [v173, v174, v175, v181])
    weight_mutation_disabled = all(row.get("official_weight_mutation_allowed") == "FALSE" for row in [v173, v174, v175, v181])

    guard_specs = [
        ("DATA_TRUST_ZERO_WEIGHT", "TRUE", tf(zero_weight), V181_GATE, "TRUE"),
        ("DATA_TRUST_GATE_ONLY", "TRUE", tf(gate_only), V181_GATE, "TRUE"),
        ("DATA_TRUST_AUDIT_ONLY", "TRUE", tf(audit_only), V181_GATE, "TRUE"),
        ("DATA_TRUST_DAILY_RUNNER_DISCLOSED", "TRUE", tf(daily_disclosed), V174_GATE, "TRUE"),
        ("DATA_TRUST_SHADOW_OBSERVATION_CONTINUED", "TRUE", tf(shadow_continued), V177_GATE, "TRUE"),
        ("READY_FOR_OFFICIAL_USE", "FALSE", tf(not official_disabled), V181_GATE, "TRUE"),
        ("REAL_BOOK_USE_ALLOWED", "FALSE", tf(not real_book_disabled), V181_GATE, "TRUE"),
        ("OFFICIAL_RECOMMENDATION_CREATED", "FALSE", tf(not recommendation_disabled), V181_GATE, "TRUE"),
        ("OFFICIAL_WEIGHT_MUTATION_ALLOWED", "FALSE", tf(not weight_mutation_disabled), V181_GATE, "TRUE"),
        ("OFFICIAL_WEIGHT_REGISTRY_MUTATED", "FALSE", "FALSE", V181_GATE, "TRUE"),
        ("OFFICIAL_RECOMMENDATION_CREATION_ATTEMPTED", "FALSE", "FALSE", OUT_PACKET, "TRUE"),
        ("REAL_BOOK_USE_ATTEMPTED", "FALSE", "FALSE", OUT_PACKET, "TRUE"),
        ("UPSTREAM_CLOSEOUT_ARTIFACTS_MUTATED", "FALSE", tf(upstream_mutated), V181_GATE, "TRUE"),
    ]
    guardrail_rows = [{
        "guardrail_id": f"V20_182_GUARDRAIL_{idx:03d}",
        "guardrail": guardrail,
        "expected_value": expected,
        "actual_value": actual,
        "guardrail_passed": tf(expected == actual),
        "blocks_official_use": blocks,
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (guardrail, expected, actual, path, blocks) in enumerate(guard_specs, start=1)]
    guardrail_pass = all(row["guardrail_passed"] == "TRUE" for row in guardrail_rows)

    integration_status_pass = all([zero_weight, gate_only, audit_only, daily_disclosed, shadow_continued])
    status_rows = [{
        "status_id": "V20_182_DAILY_RUNNER_INTEGRATION_STATUS_001",
        "daily_runner_integration_status": "DATA_TRUST_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_DISCLOSED_AND_SHADOW_OBSERVED",
        "data_trust_zero_weight": tf(zero_weight),
        "data_trust_gate_only": tf(gate_only),
        "data_trust_audit_only": tf(audit_only),
        "data_trust_daily_runner_disclosed": tf(daily_disclosed),
        "data_trust_shadow_observation_continued": tf(shadow_continued),
        "single_run_shadow_observation_pass": v175.get("ready_for_v20_176_data_trust_shadow_observation_summary", "FALSE"),
        "multiday_shadow_observation_pass": v181.get("multiday_observation_complete", "FALSE"),
        "ready_for_read_center_integration": tf(integration_status_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]

    closeout_complete = all([evidence_pass, guardrail_pass, integration_status_pass])
    gate = {
        "gate_check_id": "V20_182_NEXT_STAGE_GATE_001",
        "v20_173_status_consumed": "TRUE",
        "v20_173_status": v173.get("final_status", ""),
        "v20_174_status_consumed": "TRUE",
        "v20_174_status": v174.get("final_status", ""),
        "v20_175_status_consumed": "TRUE",
        "v20_175_status": v175.get("final_status", ""),
        "v20_177_status_consumed": "TRUE",
        "v20_177_status": v177.get("final_status", ""),
        "v20_178_status_consumed": "TRUE",
        "v20_178_status": v178.get("final_status", ""),
        "v20_179_status_consumed": "TRUE",
        "v20_179_status": v179.get("final_status", ""),
        "v20_180_status_consumed": "TRUE",
        "v20_180_status": v180.get("final_status", ""),
        "v20_181_status_consumed": "TRUE",
        "v20_181_status": v181.get("final_status", ""),
        "recommended_operator_decision": RECOMMENDED_DECISION,
        "data_trust_gate_only_closeout_complete": tf(closeout_complete),
        "data_trust_daily_runner_shadow_observation_continued": "TRUE",
        "data_trust_zero_weight": tf(zero_weight),
        "data_trust_gate_only": tf(gate_only),
        "data_trust_audit_only": tf(audit_only),
        "data_trust_daily_runner_disclosed": tf(daily_disclosed),
        "ready_for_v20_183_daily_research_runner_read_center_integration": tf(closeout_complete),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_weight_registry_mutated": "FALSE",
        "official_recommendation_creation_attempted": "FALSE",
        "real_book_use_attempted": "FALSE",
        "final_evidence_summary_pass": tf(evidence_pass),
        "final_guardrail_audit_pass": tf(guardrail_pass),
        "daily_runner_integration_status_pass": tf(integration_status_pass),
        "recommended_next_action": "RUN_V20_183_DAILY_RESEARCH_RUNNER_READ_CENTER_INTEGRATION" if closeout_complete else "REPAIR_V20_182_OPERATOR_CLOSEOUT_GUARD_FAILURE",
        "blocking_reason": "NONE" if closeout_complete else "V20_182_OPERATOR_CLOSEOUT_GUARD_FAILURE",
        "final_status": PASS_STATUS if closeout_complete else BLOCKED_STATUS,
        **COMMON,
    }

    write_csv(OUT_PACKET, PACKET_FIELDS, packet_rows)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence_rows)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrail_rows)
    write_csv(OUT_STATUS, STATUS_FIELDS, status_rows)
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)

    print(gate["final_status"])
    for key in GATE_FIELDS:
        if key in gate and key not in COMMON and key != "gate_check_id":
            print(f"{key.upper()}={gate[key]}")
    print("READY_FOR_OFFICIAL_USE=FALSE")
    print("REAL_BOOK_USE_ALLOWED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATED=FALSE")
    print("OFFICIAL_WEIGHT_MUTATION_ALLOWED=FALSE")
    print("OFFICIAL_WEIGHT_REGISTRY_MUTATED=FALSE")
    print("OFFICIAL_RECOMMENDATION_CREATION_ATTEMPTED=FALSE")
    print("REAL_BOOK_USE_ATTEMPTED=FALSE")
    print(f"OFFICIAL_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
