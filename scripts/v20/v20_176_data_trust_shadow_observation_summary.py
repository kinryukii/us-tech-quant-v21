#!/usr/bin/env python
"""V20.176 DATA_TRUST shadow observation summary."""

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

R3_R2_GATE = FACTORS / "V20_170_R3_R2_NEXT_STAGE_GATE.csv"
V171_GATE = FACTORS / "V20_171_NEXT_STAGE_GATE.csv"
V172_GATE = FACTORS / "V20_172_NEXT_STAGE_GATE.csv"
V173_GATE = FACTORS / "V20_173_NEXT_STAGE_GATE.csv"
V174_GATE = FACTORS / "V20_174_NEXT_STAGE_GATE.csv"
V175_OBS = FACTORS / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION.csv"
V175_DISCLOSURE = FACTORS / "V20_175_DATA_TRUST_DISCLOSURE_STABILITY_AUDIT.csv"
V175_GATE = FACTORS / "V20_175_NEXT_STAGE_GATE.csv"
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, R3_R2_GATE, V171_GATE, V172_GATE, V173_GATE, V174_GATE, V175_OBS, V175_DISCLOSURE, V175_GATE]

OUT_CHAIN = FACTORS / "V20_176_DATA_TRUST_CHAIN_SUMMARY.csv"
OUT_STAGE = FACTORS / "V20_176_DATA_TRUST_STAGE_BY_STAGE_SUMMARY.csv"
OUT_GUARD = FACTORS / "V20_176_DATA_TRUST_FINAL_GUARDRAIL_SUMMARY.csv"
OUT_DAILY = FACTORS / "V20_176_DATA_TRUST_DAILY_RUNNER_READINESS_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_176_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY_REPORT.md"

PASS_STATUS = "PASS_V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY_READY_FOR_V20_177"
BLOCKED_STATUS = "BLOCKED_V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY"
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

CHAIN_FIELDS = [
    "summary_id", "direct_pass_candidate_count", "gate_only_simulation_passed",
    "impact_stability_disclosure_passed", "operator_decision",
    "daily_runner_integration_passed", "daily_runner_shadow_observation_passed",
    "final_data_trust_status", "zero_weight", "gate_only", "audit_only",
    "shadow_observation_continued", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "chain_summary_pass", *COMMON.keys(),
]
STAGE_FIELDS = [
    "stage_id", "stage_name", "source_gate_artifact", "final_status",
    "stage_passed", "key_metric", "key_metric_value",
    "ready_next_stage_flag", "ready_next_stage_value", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guardrail", "expected_value", "actual_value", "guardrail_passed",
    "source_stage", *COMMON.keys(),
]
DAILY_FIELDS = [
    "readiness_id", "daily_runner_candidate_count",
    "data_trust_disclosure_candidate_count", "disclosure_stability_pass",
    "no_mutation_guard_pass", "zero_weight_guard_pass", "official_use_guard_pass",
    "ready_for_daily_runner_shadow_observation_summary",
    "ready_for_multiday_observation_or_closeout", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_175_status_consumed", "v20_175_status",
    "baseline_candidate_count", "direct_pass_candidate_count",
    "data_trust_chain_summary_pass", "data_trust_final_guardrail_pass",
    "data_trust_daily_runner_shadow_observation_pass",
    "ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_shadow_observation_continued", "recommended_next_action",
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


def stage_row(stage_id: str, name: str, artifact: Path, gate: dict[str, str], metric: str, ready_flag: str) -> dict[str, str]:
    return {
        "stage_id": stage_id,
        "stage_name": name,
        "source_gate_artifact": rel(artifact),
        "final_status": gate.get("final_status", ""),
        "stage_passed": tf(gate.get("final_status", "").startswith("PASS_")),
        "key_metric": metric,
        "key_metric_value": gate.get(metric, ""),
        "ready_next_stage_flag": ready_flag,
        "ready_next_stage_value": gate.get(ready_flag, ""),
        **COMMON,
    }


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.176 DATA_TRUST Shadow Observation Summary Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_chain_summary_pass: {gate['data_trust_chain_summary_pass']}",
        f"- data_trust_final_guardrail_pass: {gate['data_trust_final_guardrail_pass']}",
        f"- data_trust_daily_runner_shadow_observation_pass: {gate['data_trust_daily_runner_shadow_observation_pass']}",
        f"- ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation: {gate['ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "DATA_TRUST closeout status: zero-weight, gate-only, audit-only, shadow observation continued, not official use, not real-book, and not an official recommendation.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_CHAIN, CHAIN_FIELDS), (OUT_STAGE, STAGE_FIELDS), (OUT_GUARD, GUARD_FIELDS), (OUT_DAILY, DAILY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_176_NEXT_STAGE_GATE_001",
        "v20_175_status_consumed": "FALSE",
        "v20_175_status": "",
        "baseline_candidate_count": "0",
        "direct_pass_candidate_count": "0",
        "data_trust_chain_summary_pass": "FALSE",
        "data_trust_final_guardrail_pass": "FALSE",
        "data_trust_daily_runner_shadow_observation_pass": "FALSE",
        "ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_176",
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
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, R3_R2_GATE, V171_GATE, V172_GATE, V173_GATE, V174_GATE, V175_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    r3_rows, _ = read_csv(R3_R2_GATE)
    v171_rows, _ = read_csv(V171_GATE)
    v172_rows, _ = read_csv(V172_GATE)
    v173_rows, _ = read_csv(V173_GATE)
    v174_rows, _ = read_csv(V174_GATE)
    v175_rows, _ = read_csv(V175_GATE)
    if not all([baseline, r3_rows, v171_rows, v172_rows, v173_rows, v174_rows, v175_rows]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r3, v171, v172, v173, v174, v175 = r3_rows[0], v171_rows[0], v172_rows[0], v173_rows[0], v174_rows[0], v175_rows[0]
    prereq_ok = all([
        r3.get("final_status", "").startswith("PASS_"),
        v171.get("final_status", "").startswith("PASS_"),
        v172.get("final_status", "").startswith("PASS_"),
        v173.get("final_status", "").startswith("PASS_"),
        v174.get("final_status", "").startswith("PASS_"),
        v175.get("final_status") == "PASS_V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_READY_FOR_V20_176",
        v175.get("ready_for_v20_176_data_trust_shadow_observation_summary") == "TRUE",
        v175.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("PRIOR_STAGE_REQUIREMENTS_NOT_MET")
    upstream_mutated = before != protected_hashes()
    stage_rows = [
        stage_row("V20_170_R3_R2", "Direct status retest after materialization", R3_R2_GATE, r3, "direct_pass_candidate_count", "ready_for_v20_171_gate_only_ranking_simulation"),
        stage_row("V20_171", "Full gate-only ranking simulation", V171_GATE, v171, "official_ranking_score_mutation_count", "ready_for_v20_172_impact_stability_disclosure_validation"),
        stage_row("V20_172", "Impact stability disclosure validation", V172_GATE, v172, "complete_disclosure_candidate_count", "ready_for_v20_173_operator_decision_packet"),
        stage_row("V20_173", "Operator decision packet", V173_GATE, v173, "guardrail_fail_count", "ready_for_data_trust_gate_only_daily_runner_integration"),
        stage_row("V20_174", "Gate-only daily runner integration", V174_GATE, v174, "data_trust_disclosure_candidate_count", "ready_for_v20_175_daily_runner_shadow_observation"),
        stage_row("V20_175", "Daily runner shadow observation", V175_GATE, v175, "data_trust_disclosure_candidate_count", "ready_for_v20_176_data_trust_shadow_observation_summary"),
    ]
    all_stages_pass = all(row["stage_passed"] == "TRUE" for row in stage_rows)
    guards = [
        ("no_score_mutation", "0", v175["official_ranking_score_mutation_count"], "V20_175"),
        ("no_rank_mutation", "0", v175["official_rank_mutation_count"], "V20_175"),
        ("zero_score_contribution", "0.0000000000", v175["data_trust_score_contribution_sum"], "V20_175"),
        ("zero_nonzero_weight_count", "0", v175["data_trust_nonzero_weight_count"], "V20_175"),
        ("complete_disclosure_coverage", "40", v175["data_trust_disclosure_candidate_count"], "V20_175"),
        ("no_candidate_removal_or_reorder", "0", v175["candidate_removed_or_reordered_count"], "V20_175"),
        ("not_official_use", "FALSE", v175["ready_for_official_use"], "V20_175"),
        ("not_real_book", "FALSE", v175["real_book_use_allowed"], "V20_175"),
        ("not_official_recommendation", "FALSE", v175["official_recommendation_created"], "V20_175"),
        ("official_weight_mutation_disallowed", "FALSE", v175["official_weight_mutation_allowed"], "V20_175"),
        ("official_outputs_not_mutated", "FALSE", tf(upstream_mutated), "V20_176"),
    ]
    guard_rows = [{
        "guardrail": name,
        "expected_value": expected,
        "actual_value": actual,
        "guardrail_passed": tf(expected == actual),
        "source_stage": source,
        **COMMON,
    } for name, expected, actual, source in guards]
    all_guards_pass = all(row["guardrail_passed"] == "TRUE" for row in guard_rows)
    daily_pass = v175.get("final_status", "").startswith("PASS_") and v175.get("disclosure_stability_pass") == "TRUE"
    chain = [{
        "summary_id": "V20_176_DATA_TRUST_CHAIN_SUMMARY_001",
        "direct_pass_candidate_count": r3.get("direct_pass_candidate_count", "0"),
        "gate_only_simulation_passed": v171.get("final_status", "").startswith("PASS_") and "TRUE" or "FALSE",
        "impact_stability_disclosure_passed": v172.get("final_status", "").startswith("PASS_") and "TRUE" or "FALSE",
        "operator_decision": v173.get("recommended_operator_decision", ""),
        "daily_runner_integration_passed": v174.get("final_status", "").startswith("PASS_") and "TRUE" or "FALSE",
        "daily_runner_shadow_observation_passed": tf(daily_pass),
        "final_data_trust_status": "ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_SHADOW_OBSERVATION_CONTINUED",
        "zero_weight": "TRUE",
        "gate_only": "TRUE",
        "audit_only": "TRUE",
        "shadow_observation_continued": "TRUE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "chain_summary_pass": tf(all_stages_pass and all_guards_pass and daily_pass),
        **COMMON,
    }]
    daily = [{
        "readiness_id": "V20_176_DAILY_RUNNER_READINESS_001",
        "daily_runner_candidate_count": v175.get("shadow_observation_candidate_count", "0"),
        "data_trust_disclosure_candidate_count": v175.get("data_trust_disclosure_candidate_count", "0"),
        "disclosure_stability_pass": v175.get("disclosure_stability_pass", "FALSE"),
        "no_mutation_guard_pass": v175.get("no_mutation_guard_pass", "FALSE"),
        "zero_weight_guard_pass": v175.get("zero_weight_guard_pass", "FALSE"),
        "official_use_guard_pass": v175.get("official_use_guard_pass", "FALSE"),
        "ready_for_daily_runner_shadow_observation_summary": v175.get("ready_for_v20_176_data_trust_shadow_observation_summary", "FALSE"),
        "ready_for_multiday_observation_or_closeout": tf(daily_pass and all_guards_pass),
        **COMMON,
    }]
    ready_next = all_stages_pass and all_guards_pass and daily_pass and not upstream_mutated
    gate = {
        "gate_check_id": "V20_176_NEXT_STAGE_GATE_001",
        "v20_175_status_consumed": "TRUE",
        "v20_175_status": v175.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "direct_pass_candidate_count": r3.get("direct_pass_candidate_count", "0"),
        "data_trust_chain_summary_pass": tf(all_stages_pass),
        "data_trust_final_guardrail_pass": tf(all_guards_pass),
        "data_trust_daily_runner_shadow_observation_pass": tf(daily_pass),
        "ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation": tf(ready_next),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_177_DATA_TRUST_DAILY_RUNNER_CLOSEOUT_OR_MULTIDAY_OBSERVATION" if ready_next else "REPAIR_V20_176_SUMMARY_GUARD_FAILURE",
        "blocking_reason": "NONE" if ready_next else "V20_176_SUMMARY_GUARD_FAILURE",
        "final_status": PASS_STATUS if ready_next else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_CHAIN, CHAIN_FIELDS, chain)
    write_csv(OUT_STAGE, STAGE_FIELDS, stage_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)
    write_csv(OUT_DAILY, DAILY_FIELDS, daily)
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
