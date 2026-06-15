#!/usr/bin/env python
"""V20.177 DATA_TRUST multiday daily runner observation plan."""

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
V176_CHAIN = FACTORS / "V20_176_DATA_TRUST_CHAIN_SUMMARY.csv"
V176_STAGE = FACTORS / "V20_176_DATA_TRUST_STAGE_BY_STAGE_SUMMARY.csv"
V176_GUARD = FACTORS / "V20_176_DATA_TRUST_FINAL_GUARDRAIL_SUMMARY.csv"
V176_DAILY = FACTORS / "V20_176_DATA_TRUST_DAILY_RUNNER_READINESS_SUMMARY.csv"
V176_GATE = FACTORS / "V20_176_NEXT_STAGE_GATE.csv"
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, V176_CHAIN, V176_STAGE, V176_GUARD, V176_DAILY, V176_GATE]

OUT_PLAN = FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv"
OUT_CLOSEOUT = FACTORS / "V20_177_DATA_TRUST_CLOSEOUT_ELIGIBILITY_AUDIT.csv"
OUT_TEMPLATE = FACTORS / "V20_177_DATA_TRUST_PER_RUN_GUARDRAIL_TEMPLATE.csv"
OUT_GATE = FACTORS / "V20_177_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_177_DATA_TRUST_MULTIDAY_DAILY_RUNNER_OBSERVATION_PLAN_REPORT.md"

READY_V176 = "PASS_V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY_READY_FOR_V20_177"
PASS_STATUS = "PASS_V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN_READY_FOR_V20_178_RUN_1"
BLOCKED_STATUS = "BLOCKED_V20_177_DATA_TRUST_MULTIDAY_DAILY_RUNNER_OBSERVATION_PLAN"
RECOMMENDED_PATH = "CONTINUE_MULTIDAY_SHADOW_OBSERVATION"
OBSERVATION_RUN_REQUIRED_COUNT = "3"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_MULTIDAY_DAILY_RUNNER_OBSERVATION_PLAN"
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

PLAN_FIELDS = [
    "plan_id", "recommended_path", "alternative_path", "observation_run_required_count",
    "observation_window_type", "run_sequence", "run_stage_id",
    "required_input_stage", "required_guardrail_template", "closeout_allowed_before_window_complete",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "ready_for_next_observation_run", *COMMON.keys(),
]
CLOSEOUT_FIELDS = [
    "closeout_check_id", "closeout_option", "eligible_now", "recommended_now",
    "required_prior_pass", "actual_prior_pass", "reason", *COMMON.keys(),
]
TEMPLATE_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "required_each_run",
    "blocks_closeout_if_failed", "repair_action_if_failed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_176_status_consumed", "v20_176_status",
    "baseline_candidate_count", "recommended_path", "observation_run_required_count",
    "ready_for_v20_178_multiday_observation_run_1", "ready_for_immediate_closeout",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "data_trust_zero_weight",
    "data_trust_gate_only", "data_trust_audit_only", "data_trust_shadow_observation_continued",
    "recommended_next_action", "blocking_reason", "final_status", *COMMON.keys(),
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


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.177 DATA_TRUST Multiday Daily Runner Observation Plan Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- recommended_path: {gate['recommended_path']}",
        f"- observation_run_required_count: {gate['observation_run_required_count']}",
        f"- ready_for_v20_178_multiday_observation_run_1: {gate['ready_for_v20_178_multiday_observation_run_1']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        "",
        "Default path is conservative multiday shadow observation. DATA_TRUST remains zero-weight gate-only audit metadata.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_PLAN, PLAN_FIELDS), (OUT_CLOSEOUT, CLOSEOUT_FIELDS), (OUT_TEMPLATE, TEMPLATE_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_177_NEXT_STAGE_GATE_001",
        "v20_176_status_consumed": "FALSE",
        "v20_176_status": "",
        "baseline_candidate_count": "0",
        "recommended_path": "",
        "observation_run_required_count": "0",
        "ready_for_v20_178_multiday_observation_run_1": "FALSE",
        "ready_for_immediate_closeout": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_177",
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
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, V176_CHAIN, V176_STAGE, V176_GUARD, V176_DAILY, V176_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    gate_rows, _ = read_csv(V176_GATE)
    if not baseline or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v176 = gate_rows[0]
    prereq_ok = all([
        v176.get("final_status") == READY_V176,
        v176.get("ready_for_v20_177_data_trust_daily_runner_closeout_or_multiday_observation") == "TRUE",
        v176.get("ready_for_official_use") == "FALSE",
        v176.get("real_book_use_allowed") == "FALSE",
        v176.get("official_recommendation_created") == "FALSE",
        v176.get("official_weight_mutation_allowed") == "FALSE",
        v176.get("data_trust_zero_weight") == "TRUE",
        v176.get("data_trust_gate_only") == "TRUE",
        v176.get("data_trust_audit_only") == "TRUE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_176_REQUIREMENTS_NOT_MET")
    upstream_mutated = before != protected_hashes()
    if upstream_mutated:
        return emit_blocked("OFFICIAL_OR_UPSTREAM_MUTATION_DETECTED")

    plan_rows = []
    for run in range(1, int(OBSERVATION_RUN_REQUIRED_COUNT) + 1):
        plan_rows.append({
            "plan_id": f"V20_177_MULTIDAY_PLAN_RUN_{run}",
            "recommended_path": RECOMMENDED_PATH,
            "alternative_path": "IMMEDIATE_CLOSEOUT_AFTER_OPERATOR_APPROVAL",
            "observation_run_required_count": OBSERVATION_RUN_REQUIRED_COUNT,
            "observation_window_type": "DAILY_RUNNER_RUN_COUNT",
            "run_sequence": str(run),
            "run_stage_id": f"V20_178_RUN_{run}",
            "required_input_stage": "V20_174_DAILY_RUNNER_GATE_ONLY_INTEGRATION",
            "required_guardrail_template": "V20_177_DATA_TRUST_PER_RUN_GUARDRAIL_TEMPLATE",
            "closeout_allowed_before_window_complete": "FALSE",
            "data_trust_zero_weight": "TRUE",
            "data_trust_gate_only": "TRUE",
            "data_trust_audit_only": "TRUE",
            "ready_for_next_observation_run": tf(run == 1),
            **COMMON,
        })
    closeout_rows = [
        {
            "closeout_check_id": "V20_177_CLOSEOUT_001",
            "closeout_option": "IMMEDIATE_CLOSEOUT",
            "eligible_now": "TRUE",
            "recommended_now": "FALSE",
            "required_prior_pass": "V20_176_PASS",
            "actual_prior_pass": "TRUE",
            "reason": "Eligible but not recommended; conservative path requires multiday observation.",
            **COMMON,
        },
        {
            "closeout_check_id": "V20_177_CLOSEOUT_002",
            "closeout_option": "CONTINUE_MULTIDAY_SHADOW_OBSERVATION",
            "eligible_now": "TRUE",
            "recommended_now": "TRUE",
            "required_prior_pass": "V20_176_PASS",
            "actual_prior_pass": "TRUE",
            "reason": "Default conservative option before closeout.",
            **COMMON,
        },
    ]
    guardrails = [
        ("DATA_TRUST disclosure columns present", "TRUE"),
        ("official ranking score mutation count", "0"),
        ("official rank mutation count", "0"),
        ("DATA_TRUST score contribution sum", "0.0000000000"),
        ("DATA_TRUST nonzero weight count", "0"),
        ("candidate_removed_or_reordered_count", "0"),
        ("official_recommendation_created", "FALSE"),
        ("real_book_use_allowed", "FALSE"),
        ("official_weight_mutation_allowed", "FALSE"),
    ]
    template_rows = [{
        "guardrail_id": f"V20_177_PER_RUN_GUARD_{idx:03d}",
        "guardrail": guardrail,
        "expected_value": expected,
        "required_each_run": "TRUE",
        "blocks_closeout_if_failed": "TRUE",
        "repair_action_if_failed": "REPAIR_DAILY_RUNNER_GATE_ONLY_METADATA_OR_KEEP_OBSERVING",
        **COMMON,
    } for idx, (guardrail, expected) in enumerate(guardrails, start=1)]
    gate = {
        "gate_check_id": "V20_177_NEXT_STAGE_GATE_001",
        "v20_176_status_consumed": "TRUE",
        "v20_176_status": v176.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "recommended_path": RECOMMENDED_PATH,
        "observation_run_required_count": OBSERVATION_RUN_REQUIRED_COUNT,
        "ready_for_v20_178_multiday_observation_run_1": "TRUE",
        "ready_for_immediate_closeout": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_178_MULTIDAY_OBSERVATION_RUN_1",
        "blocking_reason": "NONE",
        "final_status": PASS_STATUS,
        **COMMON,
    }
    write_csv(OUT_PLAN, PLAN_FIELDS, plan_rows)
    write_csv(OUT_CLOSEOUT, CLOSEOUT_FIELDS, closeout_rows)
    write_csv(OUT_TEMPLATE, TEMPLATE_FIELDS, template_rows)
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
