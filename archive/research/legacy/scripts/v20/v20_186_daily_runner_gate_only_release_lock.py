#!/usr/bin/env python
"""V20.186 DATA_TRUST daily runner gate-only release lock."""

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
V185_SUMMARY = FACTORS / "V20_185_OPERATOR_FACING_RELEASE_SUMMARY.csv"
V185_GATE = FACTORS / "V20_185_NEXT_STAGE_GATE.csv"

PROTECTED = [V185_PACKET, V185_GUARDRAIL, V185_SUMMARY, V185_GATE]

OUT_LOCK = FACTORS / "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK.csv"
OUT_FORBIDDEN = FACTORS / "V20_186_DATA_TRUST_FORBIDDEN_USE_AUDIT.csv"
OUT_MUTATION = FACTORS / "V20_186_DATA_TRUST_MUTATION_GUARD_LOCK_AUDIT.csv"
OUT_GATE = FACTORS / "V20_186_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK_REPORT.md"

READY_V185 = "PASS_V20_185_DAILY_RUNNER_FINAL_GATE_ONLY_RELEASE_PACKET_READY_FOR_V20_186_RELEASE_LOCK"
PASS_STATUS = "PASS_V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK_READY_FOR_V20_187_REGRESSION_TEST"
BLOCKED_STATUS = "BLOCKED_V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK"

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

LOCK_FIELDS = [
    "release_lock_id", "lock_scope", "release_lock_created",
    "locked_zero_weight", "locked_gate_only", "locked_audit_only",
    "locked_read_center_disclosed", "locked_shadow_observation_continued",
    "official_scoring_factor_forbidden", "official_ranking_weight_forbidden",
    "official_recommendation_trigger_forbidden", "real_book_permission_gate_forbidden",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    *COMMON.keys(),
]
FORBIDDEN_FIELDS = [
    "forbidden_use_id", "forbidden_use", "expected_value", "actual_value",
    "forbidden_use_guard_passed", "source_artifact", *COMMON.keys(),
]
MUTATION_FIELDS = [
    "mutation_guard_id", "mutation_guard", "expected_value", "actual_value",
    "mutation_guard_locked", "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_185_status_consumed", "v20_185_status",
    "data_trust_release_lock_created", "forbidden_use_guard_pass",
    "mutation_guard_lock_pass", "locked_zero_weight", "locked_gate_only",
    "locked_audit_only", "locked_read_center_disclosed",
    "locked_shadow_observation_continued", "official_scoring_factor_forbidden",
    "official_ranking_weight_forbidden", "official_recommendation_trigger_forbidden",
    "real_book_permission_gate_forbidden", "ready_for_v20_187_daily_runner_release_lock_regression_test",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
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
        "# V20.186 Daily Runner Gate-Only Release Lock Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_release_lock_created: {gate['data_trust_release_lock_created']}",
        f"- forbidden_use_guard_pass: {gate['forbidden_use_guard_pass']}",
        f"- mutation_guard_lock_pass: {gate['mutation_guard_lock_pass']}",
        f"- ready_for_v20_187_daily_runner_release_lock_regression_test: {gate['ready_for_v20_187_daily_runner_release_lock_regression_test']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "DATA_TRUST daily runner release is locked as zero-weight gate-only audit metadata. Official scoring, official ranking weight, official recommendation trigger, and real-book permission gate use are explicitly forbidden.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_LOCK, LOCK_FIELDS), (OUT_FORBIDDEN, FORBIDDEN_FIELDS), (OUT_MUTATION, MUTATION_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_186_NEXT_STAGE_GATE_001",
        "v20_185_status_consumed": "FALSE",
        "v20_185_status": "",
        "data_trust_release_lock_created": "FALSE",
        "forbidden_use_guard_pass": "FALSE",
        "mutation_guard_lock_pass": "FALSE",
        "locked_zero_weight": "TRUE",
        "locked_gate_only": "TRUE",
        "locked_audit_only": "TRUE",
        "locked_read_center_disclosed": "TRUE",
        "locked_shadow_observation_continued": "TRUE",
        "official_scoring_factor_forbidden": "TRUE",
        "official_ranking_weight_forbidden": "TRUE",
        "official_recommendation_trigger_forbidden": "TRUE",
        "real_book_permission_gate_forbidden": "TRUE",
        "ready_for_v20_187_daily_runner_release_lock_regression_test": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_186",
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

    packet = datasets[V185_PACKET][0]
    summary = datasets[V185_SUMMARY][0]
    gate185 = datasets[V185_GATE][0]
    guardrail_rows = datasets[V185_GUARDRAIL]
    if not all([
        gate185.get("final_status") == READY_V185,
        gate185.get("ready_for_v20_186_daily_research_runner_release_lock") == "TRUE",
        summary.get("ready_for_v20_186_daily_research_runner_release_lock") == "TRUE",
        all(row.get("guardrail_passed") == "TRUE" for row in guardrail_rows),
    ]):
        return emit_blocked("V20_185_REQUIREMENTS_NOT_MET")

    upstream_mutated = before != protected_hashes()
    lock_created = all([
        packet.get("released_as_zero_weight") == "TRUE",
        packet.get("released_as_gate_only") == "TRUE",
        packet.get("released_as_audit_only") == "TRUE",
        packet.get("released_as_read_center_disclosed") == "TRUE",
        packet.get("released_as_shadow_observation_continued") == "TRUE",
    ])
    lock_rows = [{
        "release_lock_id": "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK_001",
        "lock_scope": "DAILY_RUNNER_ZERO_WEIGHT_GATE_ONLY_AUDIT_METADATA_LOCK",
        "release_lock_created": tf(lock_created),
        "locked_zero_weight": "TRUE",
        "locked_gate_only": "TRUE",
        "locked_audit_only": "TRUE",
        "locked_read_center_disclosed": "TRUE",
        "locked_shadow_observation_continued": "TRUE",
        "official_scoring_factor_forbidden": "TRUE",
        "official_ranking_weight_forbidden": "TRUE",
        "official_recommendation_trigger_forbidden": "TRUE",
        "real_book_permission_gate_forbidden": "TRUE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        **COMMON,
    }]

    forbidden_specs = [
        ("official_scoring_factor", "FALSE", packet.get("released_as_official_scoring_factor", "")),
        ("official_ranking_weight", "FALSE", packet.get("released_as_official_ranking_weight", "")),
        ("official_recommendation_trigger", "FALSE", packet.get("released_as_official_recommendation_trigger", "")),
        ("real_book_permission_gate", "FALSE", packet.get("released_as_real_book_permission_gate", "")),
    ]
    forbidden_rows = [{
        "forbidden_use_id": f"V20_186_FORBIDDEN_USE_{idx:03d}",
        "forbidden_use": use,
        "expected_value": expected,
        "actual_value": actual,
        "forbidden_use_guard_passed": tf(expected == actual),
        "source_artifact": rel(V185_PACKET),
        **COMMON,
    } for idx, (use, expected, actual) in enumerate(forbidden_specs, start=1)]
    forbidden_pass = all(row["forbidden_use_guard_passed"] == "TRUE" for row in forbidden_rows)

    mutation_specs = [
        ("official_ranking_score_mutation", "0", packet.get("official_ranking_score_mutation_count", "")),
        ("official_rank_mutation", "0", packet.get("official_rank_mutation_count", "")),
        ("nonzero_data_trust_score_contribution", "0.0000000000", packet.get("data_trust_score_contribution_sum", "")),
        ("nonzero_data_trust_weight", "0", packet.get("data_trust_nonzero_weight_count", "")),
        ("official_recommendation_creation", "FALSE", packet.get("official_recommendation_created", "")),
        ("real_book_use_enablement", "FALSE", packet.get("real_book_use_allowed", "")),
        ("official_weight_mutation", "FALSE", packet.get("official_weight_mutation_allowed", "")),
        ("upstream_release_lock_inputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    mutation_rows = [{
        "mutation_guard_id": f"V20_186_MUTATION_GUARD_LOCK_{idx:03d}",
        "mutation_guard": guard,
        "expected_value": expected,
        "actual_value": actual,
        "mutation_guard_locked": tf(expected == actual),
        "source_artifact": rel(V185_PACKET if idx < 8 else V185_GATE),
        **COMMON,
    } for idx, (guard, expected, actual) in enumerate(mutation_specs, start=1)]
    mutation_pass = all(row["mutation_guard_locked"] == "TRUE" for row in mutation_rows)
    all_pass = all([lock_created, forbidden_pass, mutation_pass])

    gate = {
        "gate_check_id": "V20_186_NEXT_STAGE_GATE_001",
        "v20_185_status_consumed": "TRUE",
        "v20_185_status": gate185.get("final_status", ""),
        "data_trust_release_lock_created": tf(lock_created),
        "forbidden_use_guard_pass": tf(forbidden_pass),
        "mutation_guard_lock_pass": tf(mutation_pass),
        "locked_zero_weight": "TRUE",
        "locked_gate_only": "TRUE",
        "locked_audit_only": "TRUE",
        "locked_read_center_disclosed": "TRUE",
        "locked_shadow_observation_continued": "TRUE",
        "official_scoring_factor_forbidden": "TRUE",
        "official_ranking_weight_forbidden": "TRUE",
        "official_recommendation_trigger_forbidden": "TRUE",
        "real_book_permission_gate_forbidden": "TRUE",
        "ready_for_v20_187_daily_runner_release_lock_regression_test": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RUN_V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST" if all_pass else "REPAIR_V20_186_RELEASE_LOCK",
        "blocking_reason": "NONE" if all_pass else "V20_186_RELEASE_LOCK_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_LOCK, LOCK_FIELDS, lock_rows)
    write_csv(OUT_FORBIDDEN, FORBIDDEN_FIELDS, forbidden_rows)
    write_csv(OUT_MUTATION, MUTATION_FIELDS, mutation_rows)
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
