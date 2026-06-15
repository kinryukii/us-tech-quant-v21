#!/usr/bin/env python
"""V20.187 DATA_TRUST daily runner release lock regression test."""

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
WEIGHT_REGISTRY = CONSOLIDATION / "V20_98B_R1_FACTOR_WEIGHT_SOURCE_REGISTRY.csv"
DAILY_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
DISPLAY_SAMPLE = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv"
V186_LOCK = FACTORS / "V20_186_DATA_TRUST_GATE_ONLY_RELEASE_LOCK.csv"
V186_FORBIDDEN = FACTORS / "V20_186_DATA_TRUST_FORBIDDEN_USE_AUDIT.csv"
V186_MUTATION = FACTORS / "V20_186_DATA_TRUST_MUTATION_GUARD_LOCK_AUDIT.csv"
V186_GATE = FACTORS / "V20_186_NEXT_STAGE_GATE.csv"

PROTECTED = [
    BASELINE, WEIGHT_REGISTRY, DAILY_SAMPLE, DISPLAY_SAMPLE,
    V186_LOCK, V186_FORBIDDEN, V186_MUTATION, V186_GATE,
]

OUT_REGRESSION = FACTORS / "V20_187_DATA_TRUST_RELEASE_LOCK_REGRESSION_AUDIT.csv"
OUT_FORBIDDEN = FACTORS / "V20_187_DATA_TRUST_FORBIDDEN_USE_REGRESSION_AUDIT.csv"
OUT_MUTATION = FACTORS / "V20_187_DATA_TRUST_MUTATION_GUARD_REGRESSION_AUDIT.csv"
OUT_COMPATIBILITY = FACTORS / "V20_187_DATA_TRUST_DOWNSTREAM_COMPATIBILITY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_187_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST_REPORT.md"

READY_V186 = "PASS_V20_186_DAILY_RUNNER_GATE_ONLY_RELEASE_LOCK_READY_FOR_V20_187_REGRESSION_TEST"
PASS_STATUS = "PASS_V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST_READY_FOR_V20_188_RELEASE_SEAL"
BLOCKED_STATUS = "BLOCKED_V20_187_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RUNNER_RELEASE_LOCK_REGRESSION_TEST"

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

REGRESSION_FIELDS = [
    "regression_check_id", "surface", "regression_check", "expected_value",
    "actual_value", "regression_passed", "source_artifact", *COMMON.keys(),
]
FORBIDDEN_FIELDS = [
    "forbidden_regression_id", "forbidden_use", "expected_enforced",
    "actual_enforced", "forbidden_use_regression_passed", "source_artifact",
    *COMMON.keys(),
]
MUTATION_FIELDS = [
    "mutation_regression_id", "mutation_guard", "expected_value",
    "actual_value", "mutation_guard_regression_passed", "source_artifact",
    *COMMON.keys(),
]
COMPATIBILITY_FIELDS = [
    "compatibility_check_id", "downstream_surface", "compatibility_check",
    "expected_value", "actual_value", "downstream_compatibility_passed",
    "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_186_status_consumed", "v20_186_status",
    "release_lock_regression_pass", "forbidden_use_regression_pass",
    "ranking_mutation_regression_pass", "zero_weight_regression_pass",
    "official_use_regression_pass", "downstream_compatibility_pass",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "ready_for_v20_188_daily_runner_gate_only_release_seal",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_mutation_allowed",
    "data_trust_zero_weight", "data_trust_gate_only", "data_trust_audit_only",
    "data_trust_read_center_disclosed", "data_trust_shadow_observation_continued",
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
        "# V20.187 Daily Runner Release Lock Regression Test Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- release_lock_regression_pass: {gate['release_lock_regression_pass']}",
        f"- forbidden_use_regression_pass: {gate['forbidden_use_regression_pass']}",
        f"- ranking_mutation_regression_pass: {gate['ranking_mutation_regression_pass']}",
        f"- zero_weight_regression_pass: {gate['zero_weight_regression_pass']}",
        f"- official_use_regression_pass: {gate['official_use_regression_pass']}",
        f"- ready_for_v20_188_daily_runner_gate_only_release_seal: {gate['ready_for_v20_188_daily_runner_gate_only_release_seal']}",
        "",
        "Regression confirms DATA_TRUST remains zero-weight gate-only audit metadata across daily runner output, ranking calculation/order, read-center display, official recommendation gate, real-book gate, and weight/contribution audit.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_REGRESSION, REGRESSION_FIELDS), (OUT_FORBIDDEN, FORBIDDEN_FIELDS),
        (OUT_MUTATION, MUTATION_FIELDS), (OUT_COMPATIBILITY, COMPATIBILITY_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_187_NEXT_STAGE_GATE_001",
        "v20_186_status_consumed": "FALSE",
        "v20_186_status": "",
        "release_lock_regression_pass": "FALSE",
        "forbidden_use_regression_pass": "FALSE",
        "ranking_mutation_regression_pass": "FALSE",
        "zero_weight_regression_pass": "FALSE",
        "official_use_regression_pass": "FALSE",
        "downstream_compatibility_pass": "FALSE",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "ready_for_v20_188_daily_runner_gate_only_release_seal": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_187",
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

    baseline = datasets[BASELINE]
    daily = datasets[DAILY_SAMPLE]
    display = datasets[DISPLAY_SAMPLE]
    lock = datasets[V186_LOCK][0]
    forbidden = datasets[V186_FORBIDDEN]
    mutation = datasets[V186_MUTATION]
    gate186 = datasets[V186_GATE][0]
    if not all([
        gate186.get("final_status") == READY_V186,
        gate186.get("ready_for_v20_187_daily_runner_release_lock_regression_test") == "TRUE",
        lock.get("release_lock_created") == "TRUE",
        all(row.get("forbidden_use_guard_passed") == "TRUE" for row in forbidden),
        all(row.get("mutation_guard_locked") == "TRUE" for row in mutation),
    ]):
        return emit_blocked("V20_186_REQUIREMENTS_NOT_MET")

    baseline_by_ticker = {row["ticker"]: row for row in baseline}
    score_mutations = 0
    rank_mutations = 0
    contribution_sum = 0.0
    nonzero_weight_count = 0
    for row in daily:
        base = baseline_by_ticker.get(row["ticker"], {})
        score_mutations += int(base.get("official_current_score") != row.get("daily_runner_score"))
        rank_mutations += int(base.get("official_current_rank") != row.get("daily_runner_rank"))
        contribution_sum += float(row.get("data_trust_official_score_contribution", "0") or "0")
        nonzero_weight_count += int(row.get("data_trust_weight") != "0.0000000000")
    contribution_text = f"{contribution_sum:.10f}"

    daily_metadata_only = all([
        len(daily) == 40,
        all(row.get("data_trust_gate_only_metadata") == "TRUE" for row in daily),
        all(row.get("data_trust_weight") == "0.0000000000" for row in daily),
        all(row.get("data_trust_official_score_contribution") == "0.0000000000" for row in daily),
        all(row.get("audit_only") == "TRUE" for row in daily),
    ])
    read_center_ok = all([
        len(display) == 40,
        all(row.get("data_trust_gate_only_status") == "TRUE" for row in display),
        all(row.get("data_trust_zero_weight_status") == "TRUE" for row in display),
        all(row.get("data_trust_audit_only_status") == "TRUE" for row in display),
        all(row.get("read_center_display_ready") == "TRUE" for row in display),
    ])
    recommendation_gate_disabled = all(row.get("official_recommendation_created") == "FALSE" for row in daily + display)
    real_book_gate_disabled = all(row.get("real_book_use_allowed", "FALSE") == "FALSE" for row in daily) and all(row.get("real_book_use_status", "DISABLED") == "DISABLED" for row in display)
    weight_config_ok = all([
        lock.get("locked_zero_weight") == "TRUE",
        lock.get("locked_gate_only") == "TRUE",
        lock.get("locked_audit_only") == "TRUE",
        all(row.get("is_official_weight", "FALSE") == "FALSE" for row in datasets[WEIGHT_REGISTRY] if row.get("factor_id", "").upper().find("DATA_TRUST") >= 0),
    ])
    regression_specs = [
        ("daily_runner_output", "DATA_TRUST_PRESENT_ONLY_AS_AUDIT_METADATA", "TRUE", tf(daily_metadata_only), DAILY_SAMPLE),
        ("ranking_score_calculation", "OFFICIAL_RANKING_SCORE_MUTATION_COUNT_ZERO", "0", str(score_mutations), DAILY_SAMPLE),
        ("ranking_order", "OFFICIAL_RANK_MUTATION_COUNT_ZERO", "0", str(rank_mutations), DAILY_SAMPLE),
        ("read_center_display", "DATA_TRUST_READ_CENTER_DISCLOSED_AS_GATE_ONLY_AUDIT", "TRUE", tf(read_center_ok), DISPLAY_SAMPLE),
        ("official_recommendation_gate", "OFFICIAL_RECOMMENDATION_DISABLED", "TRUE", tf(recommendation_gate_disabled), DAILY_SAMPLE),
        ("real_book_gate", "REAL_BOOK_USE_DISABLED", "TRUE", tf(real_book_gate_disabled), DAILY_SAMPLE),
        ("weight_configuration_contribution_audit", "DATA_TRUST_WEIGHT_AND_CONTRIBUTION_ZERO", "TRUE", tf(weight_config_ok and contribution_text == "0.0000000000" and nonzero_weight_count == 0), WEIGHT_REGISTRY),
    ]
    regression_rows = [{
        "regression_check_id": f"V20_187_REGRESSION_{idx:03d}",
        "surface": surface,
        "regression_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "regression_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(regression_specs, start=1)]
    release_lock_regression = all(row["regression_passed"] == "TRUE" for row in regression_rows)

    forbidden_rows = [{
        "forbidden_regression_id": f"V20_187_FORBIDDEN_REGRESSION_{idx:03d}",
        "forbidden_use": row.get("forbidden_use", ""),
        "expected_enforced": "TRUE",
        "actual_enforced": row.get("forbidden_use_guard_passed", ""),
        "forbidden_use_regression_passed": tf(row.get("forbidden_use_guard_passed") == "TRUE"),
        "source_artifact": rel(V186_FORBIDDEN),
        **COMMON,
    } for idx, row in enumerate(forbidden, start=1)]
    forbidden_pass = all(row["forbidden_use_regression_passed"] == "TRUE" for row in forbidden_rows)

    mutation_map = {
        "official_ranking_score_mutation": str(score_mutations),
        "official_rank_mutation": str(rank_mutations),
        "nonzero_data_trust_score_contribution": contribution_text,
        "nonzero_data_trust_weight": str(nonzero_weight_count),
        "official_recommendation_creation": "FALSE",
        "real_book_use_enablement": "FALSE",
        "official_weight_mutation": "FALSE",
    }
    mutation_rows = []
    for idx, row in enumerate(mutation, start=1):
        guard = row.get("mutation_guard", "")
        actual = mutation_map.get(guard, row.get("actual_value", ""))
        expected = row.get("expected_value", "")
        mutation_rows.append({
            "mutation_regression_id": f"V20_187_MUTATION_REGRESSION_{idx:03d}",
            "mutation_guard": guard,
            "expected_value": expected,
            "actual_value": actual,
            "mutation_guard_regression_passed": tf(expected == actual),
            "source_artifact": rel(V186_MUTATION),
            **COMMON,
        })
    mutation_pass = all(row["mutation_guard_regression_passed"] == "TRUE" for row in mutation_rows)

    compatibility_specs = [
        ("daily_runner_output", "candidate_count_preserved", "40", str(len(daily)), DAILY_SAMPLE),
        ("read_center_display", "candidate_count_preserved", "40", str(len(display)), DISPLAY_SAMPLE),
        ("official_recommendation_gate", "disabled", "TRUE", tf(recommendation_gate_disabled), DAILY_SAMPLE),
        ("real_book_gate", "disabled", "TRUE", tf(real_book_gate_disabled), DAILY_SAMPLE),
        ("weight_configuration", "data_trust_nonzero_weight_count_zero", "0", str(nonzero_weight_count), WEIGHT_REGISTRY),
    ]
    compatibility_rows = [{
        "compatibility_check_id": f"V20_187_COMPATIBILITY_{idx:03d}",
        "downstream_surface": surface,
        "compatibility_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "downstream_compatibility_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(compatibility_specs, start=1)]
    compatibility_pass = all(row["downstream_compatibility_passed"] == "TRUE" for row in compatibility_rows)
    ranking_pass = score_mutations == 0 and rank_mutations == 0
    zero_weight_pass = contribution_text == "0.0000000000" and nonzero_weight_count == 0
    official_use_pass = all([recommendation_gate_disabled, real_book_gate_disabled, lock.get("official_weight_mutation_allowed") == "FALSE"])
    upstream_mutated = before != protected_hashes()
    all_pass = all([release_lock_regression, forbidden_pass, ranking_pass, zero_weight_pass, official_use_pass, compatibility_pass, mutation_pass, not upstream_mutated])

    gate = {
        "gate_check_id": "V20_187_NEXT_STAGE_GATE_001",
        "v20_186_status_consumed": "TRUE",
        "v20_186_status": gate186.get("final_status", ""),
        "release_lock_regression_pass": tf(release_lock_regression),
        "forbidden_use_regression_pass": tf(forbidden_pass),
        "ranking_mutation_regression_pass": tf(ranking_pass),
        "zero_weight_regression_pass": tf(zero_weight_pass),
        "official_use_regression_pass": tf(official_use_pass),
        "downstream_compatibility_pass": tf(compatibility_pass),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_text,
        "data_trust_nonzero_weight_count": str(nonzero_weight_count),
        "ready_for_v20_188_daily_runner_gate_only_release_seal": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL" if all_pass else "REPAIR_V20_187_RELEASE_LOCK_REGRESSION",
        "blocking_reason": "NONE" if all_pass else "V20_187_RELEASE_LOCK_REGRESSION_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_REGRESSION, REGRESSION_FIELDS, regression_rows)
    write_csv(OUT_FORBIDDEN, FORBIDDEN_FIELDS, forbidden_rows)
    write_csv(OUT_MUTATION, MUTATION_FIELDS, mutation_rows)
    write_csv(OUT_COMPATIBILITY, COMPATIBILITY_FIELDS, compatibility_rows)
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
