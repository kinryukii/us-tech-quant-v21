#!/usr/bin/env python
"""V20.181 DATA_TRUST multiday observation closeout summary."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V177_PLAN = FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv"
V177_TEMPLATE = FACTORS / "V20_177_DATA_TRUST_PER_RUN_GUARDRAIL_TEMPLATE.csv"
V177_GATE = FACTORS / "V20_177_NEXT_STAGE_GATE.csv"
V178_RUN = FACTORS / "V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1.csv"
V178_DISCLOSURE = FACTORS / "V20_178_DATA_TRUST_RUN_1_CANDIDATE_DISCLOSURE_AUDIT.csv"
V178_ZERO = FACTORS / "V20_178_DATA_TRUST_RUN_1_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv"
V178_OFFICIAL = FACTORS / "V20_178_DATA_TRUST_RUN_1_OFFICIAL_USE_GUARD_AUDIT.csv"
V178_GATE = FACTORS / "V20_178_NEXT_STAGE_GATE.csv"
V179_RUN = FACTORS / "V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2.csv"
V179_DISCLOSURE = FACTORS / "V20_179_DATA_TRUST_RUN_2_CANDIDATE_DISCLOSURE_AUDIT.csv"
V179_ZERO = FACTORS / "V20_179_DATA_TRUST_RUN_2_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv"
V179_OFFICIAL = FACTORS / "V20_179_DATA_TRUST_RUN_2_OFFICIAL_USE_GUARD_AUDIT.csv"
V179_COMPARISON = FACTORS / "V20_179_DATA_TRUST_RUN_2_VS_RUN_1_COMPARISON_AUDIT.csv"
V179_GATE = FACTORS / "V20_179_NEXT_STAGE_GATE.csv"
V180_RUN = FACTORS / "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3.csv"
V180_DISCLOSURE = FACTORS / "V20_180_DATA_TRUST_RUN_3_CANDIDATE_DISCLOSURE_AUDIT.csv"
V180_ZERO = FACTORS / "V20_180_DATA_TRUST_RUN_3_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv"
V180_OFFICIAL = FACTORS / "V20_180_DATA_TRUST_RUN_3_OFFICIAL_USE_GUARD_AUDIT.csv"
V180_COMPARISON = FACTORS / "V20_180_DATA_TRUST_RUN_3_VS_RUN_1_RUN_2_COMPARISON_AUDIT.csv"
V180_GATE = FACTORS / "V20_180_NEXT_STAGE_GATE.csv"

PROTECTED = [
    V177_PLAN, V177_TEMPLATE, V177_GATE,
    V178_RUN, V178_DISCLOSURE, V178_ZERO, V178_OFFICIAL, V178_GATE,
    V179_RUN, V179_DISCLOSURE, V179_ZERO, V179_OFFICIAL, V179_COMPARISON, V179_GATE,
    V180_RUN, V180_DISCLOSURE, V180_ZERO, V180_OFFICIAL, V180_COMPARISON, V180_GATE,
]

OUT_3RUN = FACTORS / "V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_3RUN_SUMMARY.csv"
OUT_GUARDRAIL = FACTORS / "V20_181_DATA_TRUST_AGGREGATE_GUARDRAIL_SUMMARY.csv"
OUT_STABILITY = FACTORS / "V20_181_DATA_TRUST_RUN_TO_RUN_STABILITY_SUMMARY.csv"
OUT_EVIDENCE = FACTORS / "V20_181_DATA_TRUST_CLOSEOUT_DECISION_EVIDENCE_PACKET.csv"
OUT_GATE = FACTORS / "V20_181_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY_REPORT.md"

READY_V177 = "PASS_V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN_READY_FOR_V20_178_RUN_1"
READY_V178 = "PASS_V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1_READY_FOR_V20_179_RUN_2"
READY_V179 = "PASS_V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2_READY_FOR_V20_180_RUN_3"
READY_V180 = "PASS_V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3_READY_FOR_V20_181_CLOSEOUT_SUMMARY"
PASS_STATUS = "PASS_V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY_READY_FOR_V20_182_OPERATOR_DECISION"
BLOCKED_STATUS = "BLOCKED_V20_181_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY"

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

SUMMARY_FIELDS = [
    "run_id", "run_sequence", "candidate_count", "data_trust_disclosure_candidate_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "candidate_removed_or_reordered_count", "run_to_run_data_trust_caused_ranking_mutation_count",
    "disclosure_guard_pass", "no_mutation_guard_pass", "zero_weight_guard_pass",
    "official_use_guard_pass", "run_to_run_comparison_pass", "all_run_guards_pass",
    "ready_for_official_use", "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight", "data_trust_gate_only",
    "data_trust_audit_only", "data_trust_shadow_observation_only", *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "actual_value",
    "aggregate_guardrail_pass", "evidence_source", *COMMON.keys(),
]
STABILITY_FIELDS = [
    "stability_check_id", "stability_check", "run_1_value", "run_2_value",
    "run_3_value", "aggregate_value", "run_to_run_stability_pass",
    "evidence_source", *COMMON.keys(),
]
EVIDENCE_FIELDS = [
    "evidence_id", "closeout_condition", "evidence_value", "condition_pass",
    "evidence_source", "decision_effect", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_177_status_consumed", "v20_177_status",
    "v20_178_status_consumed", "v20_178_status", "v20_179_status_consumed",
    "v20_179_status", "v20_180_status_consumed", "v20_180_status",
    "planned_observation_run_count", "completed_observation_run_count",
    "multiday_observation_complete", "aggregate_guardrail_pass",
    "run_to_run_stability_pass", "run_to_run_data_trust_caused_ranking_mutation_count",
    "all_disclosure_guards_pass", "all_no_mutation_guards_pass",
    "all_zero_weight_guards_pass", "all_official_use_guards_pass",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_shadow_observation_only", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed",
    "ready_for_v20_182_data_trust_gate_only_closeout_operator_decision",
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


def as_int(row: dict[str, str], key: str) -> int:
    value = row.get(key, "0") or "0"
    return int(float(value))


def run_value(run: dict[str, str], run_no: int, suffix: str) -> str:
    return run.get(f"run_{run_no}_{suffix}", "")


def all_guard_rows_pass(rows: list[dict[str, str]]) -> bool:
    return bool(rows) and all(row.get("guard_passed") == "TRUE" for row in rows)


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.181 DATA_TRUST Multiday Observation Closeout Summary Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- completed_observation_run_count: {gate['completed_observation_run_count']}",
        f"- multiday_observation_complete: {gate['multiday_observation_complete']}",
        f"- aggregate_guardrail_pass: {gate['aggregate_guardrail_pass']}",
        f"- run_to_run_stability_pass: {gate['run_to_run_stability_pass']}",
        f"- run_to_run_data_trust_caused_ranking_mutation_count: {gate['run_to_run_data_trust_caused_ranking_mutation_count']}",
        f"- ready_for_v20_182_data_trust_gate_only_closeout_operator_decision: {gate['ready_for_v20_182_data_trust_gate_only_closeout_operator_decision']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "The 3-run DATA_TRUST shadow observation sequence is closed out as zero-weight, gate-only, audit-only metadata. Official use, real-book use, official recommendations, and official weight mutation remain disabled.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_3RUN, SUMMARY_FIELDS),
        (OUT_GUARDRAIL, GUARDRAIL_FIELDS),
        (OUT_STABILITY, STABILITY_FIELDS),
        (OUT_EVIDENCE, EVIDENCE_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_181_NEXT_STAGE_GATE_001",
        "v20_177_status_consumed": "FALSE",
        "v20_177_status": "",
        "v20_178_status_consumed": "FALSE",
        "v20_178_status": "",
        "v20_179_status_consumed": "FALSE",
        "v20_179_status": "",
        "v20_180_status_consumed": "FALSE",
        "v20_180_status": "",
        "planned_observation_run_count": "3",
        "completed_observation_run_count": "0",
        "multiday_observation_complete": "FALSE",
        "aggregate_guardrail_pass": "FALSE",
        "run_to_run_stability_pass": "FALSE",
        "run_to_run_data_trust_caused_ranking_mutation_count": "0",
        "all_disclosure_guards_pass": "FALSE",
        "all_no_mutation_guards_pass": "FALSE",
        "all_zero_weight_guards_pass": "FALSE",
        "all_official_use_guards_pass": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_shadow_observation_only": "TRUE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "ready_for_v20_182_data_trust_gate_only_closeout_operator_decision": "FALSE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_181",
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

    v177 = datasets[V177_GATE][0]
    v178_run = datasets[V178_RUN][0]
    v179_run = datasets[V179_RUN][0]
    v180_run = datasets[V180_RUN][0]
    v178_gate = datasets[V178_GATE][0]
    v179_gate = datasets[V179_GATE][0]
    v180_gate = datasets[V180_GATE][0]

    prereq_ok = all([
        v177.get("final_status") == READY_V177,
        v178_gate.get("final_status") == READY_V178,
        v179_gate.get("final_status") == READY_V179,
        v180_gate.get("final_status") == READY_V180,
        v180_gate.get("ready_for_v20_181_multiday_observation_closeout_summary") == "TRUE",
        v180_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_177_THROUGH_V20_180_REQUIREMENTS_NOT_MET")

    runs = [(1, v178_run), (2, v179_run), (3, v180_run)]
    completed_count = sum(run.get("run_sequence") == str(run_no) for run_no, run in runs)
    planned_count = v177.get("observation_run_required_count", "3") or "3"
    run2_mutations = as_int(v179_gate, "run_to_run_data_trust_caused_ranking_mutation_count")
    run3_mutations = as_int(v180_gate, "run_to_run_data_trust_caused_ranking_mutation_count")
    aggregate_run_to_run_mutations = run2_mutations + run3_mutations

    summary_rows = []
    for run_no, run in runs:
        comparison_pass = "TRUE" if run_no == 1 else (
            run.get("run_2_vs_run_1_comparison_pass") if run_no == 2 else run.get("run_3_vs_run_1_run_2_comparison_pass")
        )
        summary_rows.append({
            "run_id": run.get("run_id", ""),
            "run_sequence": str(run_no),
            "candidate_count": run.get("candidate_count", ""),
            "data_trust_disclosure_candidate_count": run.get("data_trust_disclosure_candidate_count", ""),
            "official_ranking_score_mutation_count": run.get("official_ranking_score_mutation_count", ""),
            "official_rank_mutation_count": run.get("official_rank_mutation_count", ""),
            "data_trust_score_contribution_sum": run.get("data_trust_score_contribution_sum", ""),
            "data_trust_nonzero_weight_count": run.get("data_trust_nonzero_weight_count", ""),
            "candidate_removed_or_reordered_count": run.get("candidate_removed_or_reordered_count", ""),
            "run_to_run_data_trust_caused_ranking_mutation_count": "0" if run_no == 1 else str(run2_mutations if run_no == 2 else run3_mutations),
            "disclosure_guard_pass": run_value(run, run_no, "disclosure_pass"),
            "no_mutation_guard_pass": run_value(run, run_no, "no_mutation_guard_pass"),
            "zero_weight_guard_pass": run_value(run, run_no, "zero_weight_guard_pass"),
            "official_use_guard_pass": run_value(run, run_no, "official_use_guard_pass"),
            "run_to_run_comparison_pass": comparison_pass,
            "all_run_guards_pass": run_value(run, run_no, "all_guards_pass"),
            "ready_for_official_use": "FALSE",
            "real_book_use_allowed": run.get("real_book_use_allowed", "FALSE"),
            "official_recommendation_created": run.get("official_recommendation_created", "FALSE"),
            "official_weight_mutation_allowed": run.get("official_weight_mutation_allowed", "FALSE"),
            "data_trust_zero_weight": "TRUE",
            "data_trust_gate_only": "TRUE",
            "data_trust_audit_only": "TRUE",
            "data_trust_shadow_observation_only": "TRUE",
            **COMMON,
        })

    all_disclosure = all(row["disclosure_guard_pass"] == "TRUE" for row in summary_rows)
    all_no_mutation = all(row["no_mutation_guard_pass"] == "TRUE" for row in summary_rows)
    all_zero = all(row["zero_weight_guard_pass"] == "TRUE" for row in summary_rows)
    all_official = all(row["official_use_guard_pass"] == "TRUE" for row in summary_rows)
    all_run_guards = all(row["all_run_guards_pass"] == "TRUE" for row in summary_rows)
    official_disabled = all([
        v178_gate.get("ready_for_official_use") == "FALSE",
        v179_gate.get("ready_for_official_use") == "FALSE",
        v180_gate.get("ready_for_official_use") == "FALSE",
    ])
    real_book_disabled = all(row["real_book_use_allowed"] == "FALSE" for row in summary_rows)
    recommendation_disabled = all(row["official_recommendation_created"] == "FALSE" for row in summary_rows)
    weight_mutation_disabled = all(row["official_weight_mutation_allowed"] == "FALSE" for row in summary_rows)
    zero_weight = all(row["data_trust_score_contribution_sum"] == "0.0000000000" and row["data_trust_nonzero_weight_count"] == "0" for row in summary_rows)
    gate_only = all(run.get("data_trust_role") == DATA_TRUST_ROLE for _, run in runs)
    audit_only = all(run.get("audit_only") == "TRUE" for _, run in runs)
    shadow_only = all(run.get("research_only") == "TRUE" for _, run in runs)
    upstream_mutated = before != protected_hashes()

    guardrail_specs = [
        ("ALL_DISCLOSURE_GUARDS_PASS", "TRUE", tf(all_disclosure), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("ALL_NO_MUTATION_GUARDS_PASS", "TRUE", tf(all_no_mutation), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("ALL_ZERO_WEIGHT_GUARDS_PASS", "TRUE", tf(all_zero), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("ALL_OFFICIAL_USE_GUARDS_PASS", "TRUE", tf(all_official), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("DATA_TRUST_ZERO_WEIGHT", "TRUE", tf(zero_weight), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("DATA_TRUST_GATE_ONLY", "TRUE", tf(gate_only), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("DATA_TRUST_AUDIT_ONLY", "TRUE", tf(audit_only), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("DATA_TRUST_SHADOW_OBSERVATION_ONLY", "TRUE", tf(shadow_only), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("READY_FOR_OFFICIAL_USE", "FALSE", tf(not official_disabled), "V20_178_GATE,V20_179_GATE,V20_180_GATE"),
        ("REAL_BOOK_USE_ALLOWED", "FALSE", tf(not real_book_disabled), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("OFFICIAL_RECOMMENDATION_CREATED", "FALSE", tf(not recommendation_disabled), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("OFFICIAL_WEIGHT_MUTATION_ALLOWED", "FALSE", tf(not weight_mutation_disabled), "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("UPSTREAM_OBSERVATION_ARTIFACTS_MUTATED", "FALSE", tf(upstream_mutated), "V20_177_THROUGH_V20_180_ARTIFACT_HASHES"),
    ]
    guardrail_rows = [{
        "guardrail_id": f"V20_181_GUARDRAIL_{idx:03d}",
        "guardrail": name,
        "expected_value": expected,
        "actual_value": actual,
        "aggregate_guardrail_pass": tf(expected == actual),
        "evidence_source": source,
        **COMMON,
    } for idx, (name, expected, actual, source) in enumerate(guardrail_specs, start=1)]
    aggregate_guardrail_pass = all(row["aggregate_guardrail_pass"] == "TRUE" for row in guardrail_rows)

    candidate_values = [row["candidate_count"] for row in summary_rows]
    disclosure_values = [row["data_trust_disclosure_candidate_count"] for row in summary_rows]
    contribution_values = [row["data_trust_score_contribution_sum"] for row in summary_rows]
    nonzero_weight_values = [row["data_trust_nonzero_weight_count"] for row in summary_rows]
    rank_mutation_values = [row["official_rank_mutation_count"] for row in summary_rows]
    score_mutation_values = [row["official_ranking_score_mutation_count"] for row in summary_rows]
    stability_specs = [
        ("CANDIDATE_COUNT_STABLE", candidate_values, candidate_values[0], len(set(candidate_values)) == 1),
        ("DISCLOSURE_COUNT_EQUALS_CANDIDATE_COUNT", disclosure_values, ",".join(disclosure_values), candidate_values == disclosure_values),
        ("OFFICIAL_SCORE_MUTATION_COUNT_ZERO", score_mutation_values, "0", all(value == "0" for value in score_mutation_values)),
        ("OFFICIAL_RANK_MUTATION_COUNT_ZERO", rank_mutation_values, "0", all(value == "0" for value in rank_mutation_values)),
        ("DATA_TRUST_SCORE_CONTRIBUTION_SUM_ZERO", contribution_values, "0.0000000000", all(value == "0.0000000000" for value in contribution_values)),
        ("DATA_TRUST_NONZERO_WEIGHT_COUNT_ZERO", nonzero_weight_values, "0", all(value == "0" for value in nonzero_weight_values)),
        ("RUN_TO_RUN_DATA_TRUST_CAUSED_RANKING_MUTATION_COUNT_ZERO", ["0", str(run2_mutations), str(run3_mutations)], str(aggregate_run_to_run_mutations), aggregate_run_to_run_mutations == 0),
    ]
    stability_rows = [{
        "stability_check_id": f"V20_181_STABILITY_{idx:03d}",
        "stability_check": name,
        "run_1_value": values[0],
        "run_2_value": values[1],
        "run_3_value": values[2],
        "aggregate_value": aggregate,
        "run_to_run_stability_pass": tf(passed),
        "evidence_source": "V20_178_RUN,V20_179_GATE,V20_180_GATE",
        **COMMON,
    } for idx, (name, values, aggregate, passed) in enumerate(stability_specs, start=1)]
    run_to_run_stability_pass = all(row["run_to_run_stability_pass"] == "TRUE" for row in stability_rows)

    multiday_complete = completed_count == 3 and planned_count == "3" and all_run_guards
    closeout_pass = all([
        multiday_complete, aggregate_guardrail_pass, run_to_run_stability_pass,
        aggregate_run_to_run_mutations == 0, all_disclosure, all_no_mutation,
        all_zero, all_official, official_disabled, real_book_disabled,
        recommendation_disabled, weight_mutation_disabled,
    ])
    evidence_specs = [
        ("3_RUN_OBSERVATION_COMPLETE", tf(multiday_complete), multiday_complete, "V20_177_GATE,V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("AGGREGATE_GUARDRAILS_PASS", tf(aggregate_guardrail_pass), aggregate_guardrail_pass, "V20_181_DATA_TRUST_AGGREGATE_GUARDRAIL_SUMMARY"),
        ("RUN_TO_RUN_STABILITY_PASS", tf(run_to_run_stability_pass), run_to_run_stability_pass, "V20_181_DATA_TRUST_RUN_TO_RUN_STABILITY_SUMMARY"),
        ("RUN_TO_RUN_DATA_TRUST_CAUSED_RANKING_MUTATION_COUNT", str(aggregate_run_to_run_mutations), aggregate_run_to_run_mutations == 0, "V20_179_GATE,V20_180_GATE"),
        ("OFFICIAL_USE_DISABLED", tf(official_disabled), official_disabled, "V20_178_GATE,V20_179_GATE,V20_180_GATE"),
        ("REAL_BOOK_USE_DISABLED", tf(real_book_disabled), real_book_disabled, "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("OFFICIAL_RECOMMENDATION_DISABLED", tf(recommendation_disabled), recommendation_disabled, "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
        ("OFFICIAL_WEIGHT_MUTATION_DISALLOWED", tf(weight_mutation_disabled), weight_mutation_disabled, "V20_178_RUN,V20_179_RUN,V20_180_RUN"),
    ]
    evidence_rows = [{
        "evidence_id": f"V20_181_EVIDENCE_{idx:03d}",
        "closeout_condition": condition,
        "evidence_value": value,
        "condition_pass": tf(passed),
        "evidence_source": source,
        "decision_effect": "ALLOW_V20_182_OPERATOR_DECISION" if passed else "BLOCK_V20_182_OPERATOR_DECISION",
        **COMMON,
    } for idx, (condition, value, passed, source) in enumerate(evidence_specs, start=1)]

    gate = {
        "gate_check_id": "V20_181_NEXT_STAGE_GATE_001",
        "v20_177_status_consumed": "TRUE",
        "v20_177_status": v177.get("final_status", ""),
        "v20_178_status_consumed": "TRUE",
        "v20_178_status": v178_gate.get("final_status", ""),
        "v20_179_status_consumed": "TRUE",
        "v20_179_status": v179_gate.get("final_status", ""),
        "v20_180_status_consumed": "TRUE",
        "v20_180_status": v180_gate.get("final_status", ""),
        "planned_observation_run_count": planned_count,
        "completed_observation_run_count": str(completed_count),
        "multiday_observation_complete": tf(multiday_complete),
        "aggregate_guardrail_pass": tf(aggregate_guardrail_pass),
        "run_to_run_stability_pass": tf(run_to_run_stability_pass),
        "run_to_run_data_trust_caused_ranking_mutation_count": str(aggregate_run_to_run_mutations),
        "all_disclosure_guards_pass": tf(all_disclosure),
        "all_no_mutation_guards_pass": tf(all_no_mutation),
        "all_zero_weight_guards_pass": tf(all_zero),
        "all_official_use_guards_pass": tf(all_official),
        "data_trust_zero_weight": tf(zero_weight),
        "data_trust_gate_only": tf(gate_only),
        "data_trust_audit_only": tf(audit_only),
        "data_trust_shadow_observation_only": tf(shadow_only),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "ready_for_v20_182_data_trust_gate_only_closeout_operator_decision": tf(closeout_pass),
        "recommended_next_action": "RUN_V20_182_DATA_TRUST_GATE_ONLY_CLOSEOUT_OPERATOR_DECISION" if closeout_pass else "REPAIR_V20_181_CLOSEOUT_GUARD_FAILURE",
        "blocking_reason": "NONE" if closeout_pass else "V20_181_CLOSEOUT_GUARD_FAILURE",
        "final_status": PASS_STATUS if closeout_pass else BLOCKED_STATUS,
        **COMMON,
    }

    write_csv(OUT_3RUN, SUMMARY_FIELDS, summary_rows)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrail_rows)
    write_csv(OUT_STABILITY, STABILITY_FIELDS, stability_rows)
    write_csv(OUT_EVIDENCE, EVIDENCE_FIELDS, evidence_rows)
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
    print(f"OFFICIAL_MUTATION_DETECTED={tf(upstream_mutated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
