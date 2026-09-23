#!/usr/bin/env python
"""V20.188 DATA_TRUST daily runner gate-only release seal."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

V185_PACKET = FACTORS / "V20_185_DATA_TRUST_FINAL_GATE_ONLY_RELEASE_PACKET.csv"
V185_GUARDRAIL = FACTORS / "V20_185_DATA_TRUST_FINAL_RELEASE_GUARDRAIL_AUDIT.csv"
V185_GATE = FACTORS / "V20_185_NEXT_STAGE_GATE.csv"
V186_LOCK = FACTORS / "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK.csv"
V186_FORBIDDEN = FACTORS / "V20_186_DATA_TRUST_FORBIDDEN_USE_AUDIT.csv"
V186_MUTATION = FACTORS / "V20_186_DATA_TRUST_MUTATION_GUARD_LOCK_AUDIT.csv"
V186_GATE = FACTORS / "V20_186_NEXT_STAGE_GATE.csv"
V187_REGRESSION = FACTORS / "V20_187_DATA_TRUST_RELEASE_LOCK_REGRESSION_AUDIT.csv"
V187_FORBIDDEN = FACTORS / "V20_187_DATA_TRUST_FORBIDDEN_USE_REGRESSION_AUDIT.csv"
V187_MUTATION = FACTORS / "V20_187_DATA_TRUST_MUTATION_GUARD_REGRESSION_AUDIT.csv"
V187_COMPATIBILITY = FACTORS / "V20_187_DATA_TRUST_DOWNSTREAM_COMPATIBILITY_AUDIT.csv"
V187_GATE = FACTORS / "V20_187_NEXT_STAGE_GATE.csv"

PROTECTED = [
    V185_PACKET, V185_GUARDRAIL, V185_GATE,
    V186_LOCK, V186_FORBIDDEN, V186_MUTATION, V186_GATE,
    V187_REGRESSION, V187_FORBIDDEN, V187_MUTATION, V187_COMPATIBILITY, V187_GATE,
]

OUT_SEAL = FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv"
OUT_GUARDRAIL = FACTORS / "V20_188_DATA_TRUST_FINAL_SEAL_GUARDRAIL_AUDIT.csv"
OUT_FORBIDDEN = FACTORS / "V20_188_DATA_TRUST_FINAL_FORBIDDEN_USE_SEAL_AUDIT.csv"
OUT_SUMMARY = FACTORS / "V20_188_OPERATOR_FACING_SEAL_SUMMARY.csv"
OUT_GATE = FACTORS / "V20_188_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_REPORT.md"

READY_V185 = "PASS_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET_READY_FOR_V20_186_RELEASE_LOCK"
READY_V186 = "PASS_V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK_READY_FOR_V20_187_REGRESSION_TEST"
READY_V187 = "PASS_V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST_READY_FOR_V20_188_RELEASE_SEAL"
PASS_STATUS = "PASS_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_READY_FOR_V20_189_CURRENT_CHAIN_HANDOFF"
BLOCKED_STATUS = "BLOCKED_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL"

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

SEAL_FIELDS = [
    "release_seal_id", "seal_scope", "release_seal_created",
    "sealed_zero_weight", "sealed_gate_only", "sealed_audit_only",
    "sealed_read_center_disclosed", "sealed_daily_runner_compatible",
    "sealed_shadow_observation_continued", "official_scoring_factor_forbidden",
    "official_ranking_weight_forbidden", "official_recommendation_trigger_forbidden",
    "real_book_permission_gate_forbidden", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", *COMMON.keys(),
]
GUARDRAIL_FIELDS = [
    "guardrail_id", "guardrail", "expected_value", "actual_value",
    "final_seal_guardrail_passed", "source_artifact", *COMMON.keys(),
]
FORBIDDEN_FIELDS = [
    "forbidden_seal_id", "forbidden_use", "expected_value", "actual_value",
    "final_forbidden_use_seal_passed", "source_artifact", *COMMON.keys(),
]
SUMMARY_FIELDS = [
    "summary_id", "operator_facing_seal_summary", "data_trust_gate_only_release_sealed",
    "final_seal_guardrail_pass", "final_forbidden_use_seal_pass",
    "ready_for_v20_189_daily_runner_seal_handoff_to_current_chain",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_185_status_consumed", "v20_185_status",
    "v20_186_status_consumed", "v20_186_status", "v20_187_status_consumed",
    "v20_187_status", "data_trust_gate_only_release_sealed",
    "final_seal_guardrail_pass", "final_forbidden_use_seal_pass",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "ready_for_v20_189_daily_runner_seal_handoff_to_current_chain",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_read_center_disclosed", "data_trust_daily_runner_compatible",
    "data_trust_shadow_observation_continued", "official_scoring_factor_forbidden",
    "official_ranking_weight_forbidden", "official_recommendation_trigger_forbidden",
    "real_book_permission_gate_forbidden", "recommended_next_action",
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


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.188 Daily Runner Gate-Only Release Seal Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_gate_only_release_sealed: {gate['data_trust_gate_only_release_sealed']}",
        f"- final_seal_guardrail_pass: {gate['final_seal_guardrail_pass']}",
        f"- final_forbidden_use_seal_pass: {gate['final_forbidden_use_seal_pass']}",
        f"- ready_for_v20_189_daily_runner_seal_handoff_to_current_chain: {gate['ready_for_v20_189_daily_runner_seal_handoff_to_current_chain']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Final seal confirms DATA_TRUST remains zero-weight, gate-only, audit-only, read-center-disclosed, daily-runner compatible metadata with continued shadow observation. Forbidden official scoring, ranking weight, recommendation trigger, and real-book permission uses remain sealed off.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_SEAL, SEAL_FIELDS), (OUT_GUARDRAIL, GUARDRAIL_FIELDS), (OUT_FORBIDDEN, FORBIDDEN_FIELDS), (OUT_SUMMARY, SUMMARY_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_188_NEXT_STAGE_GATE_001",
        "v20_185_status_consumed": "FALSE",
        "v20_185_status": "",
        "v20_186_status_consumed": "FALSE",
        "v20_186_status": "",
        "v20_187_status_consumed": "FALSE",
        "v20_187_status": "",
        "data_trust_gate_only_release_sealed": "FALSE",
        "final_seal_guardrail_pass": "FALSE",
        "final_forbidden_use_seal_pass": "FALSE",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "ready_for_v20_189_daily_runner_seal_handoff_to_current_chain": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_daily_runner_compatible": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "official_scoring_factor_forbidden": "TRUE",
        "official_ranking_weight_forbidden": "TRUE",
        "official_recommendation_trigger_forbidden": "TRUE",
        "real_book_permission_gate_forbidden": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_188",
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

    v185_packet = datasets[V185_PACKET][0]
    v185_gate = datasets[V185_GATE][0]
    v186_lock = datasets[V186_LOCK][0]
    v186_gate = datasets[V186_GATE][0]
    v187_gate = datasets[V187_GATE][0]
    if not all([
        v185_gate.get("final_status") == READY_V185,
        v186_gate.get("final_status") == READY_V186,
        v187_gate.get("final_status") == READY_V187,
        v187_gate.get("ready_for_v20_188_daily_runner_gate_only_release_seal") == "TRUE",
        v186_lock.get("release_lock_created") == "TRUE",
    ]):
        return emit_blocked("V20_185_V20_186_OR_V20_187_REQUIREMENTS_NOT_MET")

    upstream_mutated = before != protected_hashes()
    sealed_status = {
        "zero_weight": v187_gate.get("data_trust_zero_weight") == "TRUE",
        "gate_only": v187_gate.get("data_trust_gate_only") == "TRUE",
        "audit_only": v187_gate.get("data_trust_audit_only") == "TRUE",
        "read_center_disclosed": v187_gate.get("data_trust_read_center_disclosed") == "TRUE",
        "daily_runner_compatible": v187_gate.get("downstream_compatibility_pass") == "TRUE",
        "shadow_observation_continued": v187_gate.get("data_trust_shadow_observation_continued") == "TRUE",
    }
    forbidden_status = {
        "official_scoring_factor": v186_lock.get("official_scoring_factor_forbidden") == "TRUE",
        "official_ranking_weight": v186_lock.get("official_ranking_weight_forbidden") == "TRUE",
        "official_recommendation_trigger": v186_lock.get("official_recommendation_trigger_forbidden") == "TRUE",
        "real_book_permission_gate": v186_lock.get("real_book_permission_gate_forbidden") == "TRUE",
    }
    mutation_guards_locked = all(row.get("mutation_guard_regression_passed") == "TRUE" for row in datasets[V187_MUTATION])
    score_mutations = v187_gate.get("official_ranking_score_mutation_count", "")
    rank_mutations = v187_gate.get("official_rank_mutation_count", "")
    contribution_sum = v187_gate.get("data_trust_score_contribution_sum", "")
    nonzero_weight_count = v187_gate.get("data_trust_nonzero_weight_count", "")
    official_disabled = all([
        v185_gate.get("ready_for_official_use") == "FALSE",
        v186_gate.get("ready_for_official_use") == "FALSE",
        v187_gate.get("ready_for_official_use") == "FALSE",
        v185_gate.get("real_book_use_allowed") == "FALSE",
        v186_gate.get("real_book_use_allowed") == "FALSE",
        v187_gate.get("real_book_use_allowed") == "FALSE",
        v185_gate.get("official_recommendation_created") == "FALSE",
        v186_gate.get("official_recommendation_created") == "FALSE",
        v187_gate.get("official_recommendation_created") == "FALSE",
        v185_gate.get("official_weight_mutation_allowed") == "FALSE",
        v186_gate.get("official_weight_mutation_allowed") == "FALSE",
        v187_gate.get("official_weight_mutation_allowed") == "FALSE",
    ])
    seal_created = all(sealed_status.values()) and all(forbidden_status.values()) and mutation_guards_locked

    seal_rows = [{
        "release_seal_id": "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL_001",
        "seal_scope": "DAILY_RUNNER_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_FINAL_SEAL",
        "release_seal_created": tf(seal_created),
        "sealed_zero_weight": tf(sealed_status["zero_weight"]),
        "sealed_gate_only": tf(sealed_status["gate_only"]),
        "sealed_audit_only": tf(sealed_status["audit_only"]),
        "sealed_read_center_disclosed": tf(sealed_status["read_center_disclosed"]),
        "sealed_daily_runner_compatible": tf(sealed_status["daily_runner_compatible"]),
        "sealed_shadow_observation_continued": tf(sealed_status["shadow_observation_continued"]),
        "official_scoring_factor_forbidden": tf(forbidden_status["official_scoring_factor"]),
        "official_ranking_weight_forbidden": tf(forbidden_status["official_ranking_weight"]),
        "official_recommendation_trigger_forbidden": tf(forbidden_status["official_recommendation_trigger"]),
        "real_book_permission_gate_forbidden": tf(forbidden_status["real_book_permission_gate"]),
        "official_ranking_score_mutation_count": score_mutations,
        "official_rank_mutation_count": rank_mutations,
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": nonzero_weight_count,
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]
    guard_specs = [
        ("sealed_zero_weight", "TRUE", seal_rows[0]["sealed_zero_weight"], V187_GATE),
        ("sealed_gate_only", "TRUE", seal_rows[0]["sealed_gate_only"], V187_GATE),
        ("sealed_audit_only", "TRUE", seal_rows[0]["sealed_audit_only"], V187_GATE),
        ("sealed_read_center_disclosed", "TRUE", seal_rows[0]["sealed_read_center_disclosed"], V187_GATE),
        ("sealed_daily_runner_compatible", "TRUE", seal_rows[0]["sealed_daily_runner_compatible"], V187_GATE),
        ("sealed_shadow_observation_continued", "TRUE", seal_rows[0]["sealed_shadow_observation_continued"], V187_GATE),
        ("mutation_guards_locked", "TRUE", tf(mutation_guards_locked), V187_MUTATION),
        ("official_ranking_score_mutation_count", "0", score_mutations, V187_GATE),
        ("official_rank_mutation_count", "0", rank_mutations, V187_GATE),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum, V187_GATE),
        ("data_trust_nonzero_weight_count", "0", nonzero_weight_count, V187_GATE),
        ("official_recommendation_created", "FALSE", "FALSE", V187_GATE),
        ("real_book_use_allowed", "FALSE", "FALSE", V187_GATE),
        ("official_weight_mutation_allowed", "FALSE", "FALSE", V187_GATE),
        ("upstream_seal_inputs_mutated", "FALSE", tf(upstream_mutated), V187_GATE),
    ]
    guardrail_rows = [{
        "guardrail_id": f"V20_188_FINAL_SEAL_GUARDRAIL_{idx:03d}",
        "guardrail": guardrail,
        "expected_value": expected,
        "actual_value": actual,
        "final_seal_guardrail_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (guardrail, expected, actual, path) in enumerate(guard_specs, start=1)]
    final_guardrail_pass = all(row["final_seal_guardrail_passed"] == "TRUE" for row in guardrail_rows)

    forbidden_rows = [{
        "forbidden_seal_id": f"V20_188_FORBIDDEN_USE_SEAL_{idx:03d}",
        "forbidden_use": use,
        "expected_value": "TRUE",
        "actual_value": tf(actual),
        "final_forbidden_use_seal_passed": tf(actual),
        "source_artifact": rel(V186_LOCK),
        **COMMON,
    } for idx, (use, actual) in enumerate(forbidden_status.items(), start=1)]
    final_forbidden_pass = all(row["final_forbidden_use_seal_passed"] == "TRUE" for row in forbidden_rows)
    all_pass = all([seal_created, final_guardrail_pass, final_forbidden_pass, official_disabled, not upstream_mutated])

    summary_rows = [{
        "summary_id": "V20_188_OPERATOR_FACING_SEAL_SUMMARY_001",
        "operator_facing_seal_summary": "DATA_TRUST_FINAL_SEALED_AS_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_READ_CENTER_DISCLOSED_DAILY_RUNNER_COMPATIBLE_SHADOW_OBSERVED",
        "data_trust_gate_only_release_sealed": tf(seal_created),
        "final_seal_guardrail_pass": tf(final_guardrail_pass),
        "final_forbidden_use_seal_pass": tf(final_forbidden_pass),
        "ready_for_v20_189_daily_runner_seal_handoff_to_current_chain": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]
    gate = {
        "gate_check_id": "V20_188_NEXT_STAGE_GATE_001",
        "v20_185_status_consumed": "TRUE",
        "v20_185_status": v185_gate.get("final_status", ""),
        "v20_186_status_consumed": "TRUE",
        "v20_186_status": v186_gate.get("final_status", ""),
        "v20_187_status_consumed": "TRUE",
        "v20_187_status": v187_gate.get("final_status", ""),
        "data_trust_gate_only_release_sealed": tf(seal_created),
        "final_seal_guardrail_pass": tf(final_guardrail_pass),
        "final_forbidden_use_seal_pass": tf(final_forbidden_pass),
        "official_ranking_score_mutation_count": score_mutations,
        "official_rank_mutation_count": rank_mutations,
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": nonzero_weight_count,
        "ready_for_v20_189_daily_runner_seal_handoff_to_current_chain": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_daily_runner_compatible": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "official_scoring_factor_forbidden": "TRUE",
        "official_ranking_weight_forbidden": "TRUE",
        "official_recommendation_trigger_forbidden": "TRUE",
        "real_book_permission_gate_forbidden": "TRUE",
        "recommended_next_action": "RUN_V20_189_DAILY_RUNNER_SEAL_HANDOFF_TO_CURRENT_CHAIN" if all_pass else "REPAIR_V20_188_RELEASE_SEAL",
        "blocking_reason": "NONE" if all_pass else "V20_188_RELEASE_SEAL_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_SEAL, SEAL_FIELDS, seal_rows)
    write_csv(OUT_GUARDRAIL, GUARDRAIL_FIELDS, guardrail_rows)
    write_csv(OUT_FORBIDDEN, FORBIDDEN_FIELDS, forbidden_rows)
    write_csv(OUT_SUMMARY, SUMMARY_FIELDS, summary_rows)
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
