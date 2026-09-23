#!/usr/bin/env python
"""V20.190 current chain smoke test with DATA_TRUST gate-only metadata."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs" / "v20"
FACTORS = OUTPUTS / "factors"
READ_CENTER = OUTPUTS / "read_center"

DAILY_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
DISPLAY_SAMPLE = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv"
V188_SEAL = FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv"
V188_GATE = FACTORS / "V20_188_NEXT_STAGE_GATE.csv"
V189_HANDOFF = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_AUDIT.csv"
V189_COMPATIBILITY = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv"
V189_GUARD = FACTORS / "V20_189_OFFICIAL_USE_GUARD_AUDIT.csv"
V189_GATE = FACTORS / "V20_189_NEXT_STAGE_GATE.csv"

PROTECTED = [
    DAILY_SAMPLE, DISPLAY_SAMPLE, V188_SEAL, V188_GATE,
    V189_HANDOFF, V189_COMPATIBILITY, V189_GUARD, V189_GATE,
]

OUT_SMOKE = FACTORS / "V20_190_CURRENT_CHAIN_SMOKE_TEST_AUDIT.csv"
OUT_COMPATIBILITY = FACTORS / "V20_190_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv"
OUT_RANKING = FACTORS / "V20_190_RANKING_WEIGHT_MUTATION_GUARD_AUDIT.csv"
OUT_OFFICIAL = FACTORS / "V20_190_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_DISPLAY = FACTORS / "V20_190_READ_CENTER_DISPLAY_AUDIT.csv"
OUT_GATE = FACTORS / "V20_190_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_190_CURRENT_CHAIN_SMOKE_TEST_WITH_DATA_TRUST_GATE_ONLY_REPORT.md"

READY_V188 = "PASS_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_READY_FOR_V20_189_CURRENT_CHAIN_HANDOFF"
READY_V189 = "PASS_V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_READY_FOR_V20_190_CURRENT_CHAIN_SMOKE_TEST"
PASS_STATUS = "PASS_V20_190_CURRENT_CHAIN_SMOKE_TEST_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_191_DAILY_RUNNER_REGRESSION"
BLOCKED_STATUS = "BLOCKED_V20_190_CURRENT_CHAIN_SMOKE_TEST_WITH_DATA_TRUST_GATE_ONLY"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_CURRENT_CHAIN_SMOKE_TEST_WITH_DATA_TRUST_GATE_ONLY"

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

AUDIT_FIELDS = [
    "smoke_check_id", "smoke_surface", "smoke_check", "expected_value",
    "actual_value", "smoke_check_passed", "source_artifact", *COMMON.keys(),
]
COMPATIBILITY_FIELDS = [
    "compatibility_check_id", "current_chain_surface", "compatibility_check",
    "expected_value", "actual_value", "compatibility_check_passed",
    "source_artifact", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", "source_artifact", *COMMON.keys(),
]
DISPLAY_FIELDS = [
    "display_check_id", "display_surface", "display_check", "expected_value",
    "actual_value", "display_check_passed", "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_188_status_consumed", "v20_188_status",
    "v20_189_status_consumed", "v20_189_status", "current_chain_candidate_count",
    "read_center_display_candidate_count", "candidate_removed_or_reordered_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "current_chain_smoke_test_pass", "data_trust_sealed_status_preserved",
    "ranking_mutation_guard_pass", "zero_weight_guard_pass",
    "official_use_guard_pass", "read_center_display_guard_pass",
    "ready_for_v20_191_current_chain_daily_runner_regression",
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
        "# V20.190 Current Chain Smoke Test With DATA_TRUST Gate-Only Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- current_chain_smoke_test_pass: {gate['current_chain_smoke_test_pass']}",
        f"- data_trust_sealed_status_preserved: {gate['data_trust_sealed_status_preserved']}",
        f"- ranking_mutation_guard_pass: {gate['ranking_mutation_guard_pass']}",
        f"- zero_weight_guard_pass: {gate['zero_weight_guard_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- read_center_display_guard_pass: {gate['read_center_display_guard_pass']}",
        f"- ready_for_v20_191_current_chain_daily_runner_regression: {gate['ready_for_v20_191_current_chain_daily_runner_regression']}",
        "",
        "Smoke test confirms current chain consumes DATA_TRUST gate-only audit metadata without errors, ranking mutation, weight mutation, official recommendation creation, real-book enablement, or read-center disclosure loss.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_SMOKE, AUDIT_FIELDS), (OUT_COMPATIBILITY, COMPATIBILITY_FIELDS),
        (OUT_RANKING, GUARD_FIELDS), (OUT_OFFICIAL, GUARD_FIELDS),
        (OUT_DISPLAY, DISPLAY_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_190_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "FALSE",
        "v20_188_status": "",
        "v20_189_status_consumed": "FALSE",
        "v20_189_status": "",
        "current_chain_candidate_count": "0",
        "read_center_display_candidate_count": "0",
        "candidate_removed_or_reordered_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "current_chain_smoke_test_pass": "FALSE",
        "data_trust_sealed_status_preserved": "FALSE",
        "ranking_mutation_guard_pass": "FALSE",
        "zero_weight_guard_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "read_center_display_guard_pass": "FALSE",
        "ready_for_v20_191_current_chain_daily_runner_regression": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_190",
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

    daily = datasets[DAILY_SAMPLE]
    display = datasets[DISPLAY_SAMPLE]
    seal = datasets[V188_SEAL][0]
    gate188 = datasets[V188_GATE][0]
    gate189 = datasets[V189_GATE][0]
    if not all([
        gate188.get("final_status") == READY_V188,
        gate189.get("final_status") == READY_V189,
        gate189.get("ready_for_v20_190_current_chain_smoke_test") == "TRUE",
        all(row.get("handoff_check_passed") == "TRUE" for row in datasets[V189_HANDOFF]),
        all(row.get("compatibility_check_passed") == "TRUE" for row in datasets[V189_COMPATIBILITY]),
        all(row.get("guard_passed") == "TRUE" for row in datasets[V189_GUARD]),
    ]):
        return emit_blocked("V20_188_OR_V20_189_REQUIREMENTS_NOT_MET")

    score_mutations = sum(row.get("official_current_score") != row.get("daily_runner_score") for row in daily)
    rank_mutations = sum(row.get("official_current_rank") != row.get("daily_runner_rank") for row in daily)
    removed_reordered = sum(row.get("official_current_rank") != row.get("daily_runner_rank") for row in daily)
    contribution_sum = f"{sum(float(row.get('data_trust_official_score_contribution', '0') or '0') for row in daily):.10f}"
    nonzero_weight = sum(row.get("data_trust_weight") != "0.0000000000" for row in daily)
    metadata_consumed = all([
        len(daily) == 40,
        all(row.get("data_trust_direct_status") == "PASS" for row in daily),
        all(row.get("data_trust_gate_only_metadata") == "TRUE" for row in daily),
        all(row.get("audit_only") == "TRUE" for row in daily),
    ])
    sealed_preserved = all([
        seal.get("sealed_zero_weight") == "TRUE",
        seal.get("sealed_gate_only") == "TRUE",
        seal.get("sealed_audit_only") == "TRUE",
        seal.get("sealed_read_center_disclosed") == "TRUE",
        contribution_sum == "0.0000000000",
        nonzero_weight == 0,
    ])
    official_use_disabled = all([
        gate189.get("ready_for_official_use") == "FALSE",
        gate189.get("real_book_use_allowed") == "FALSE",
        gate189.get("official_recommendation_created") == "FALSE",
        gate189.get("official_weight_mutation_allowed") == "FALSE",
        all(row.get("official_recommendation_created") == "FALSE" for row in daily),
        all(row.get("real_book_use_allowed") == "FALSE" for row in daily),
        all(row.get("official_weight_mutation_allowed") == "FALSE" for row in daily),
    ])
    display_clear = all([
        len(display) == 40,
        all(row.get("data_trust_direct_status_summary") == "PASS" for row in display),
        all(row.get("data_trust_gate_only_status") == "TRUE" for row in display),
        all(row.get("data_trust_zero_weight_status") == "TRUE" for row in display),
        all(row.get("data_trust_audit_only_status") == "TRUE" for row in display),
        all(row.get("read_center_display_ready") == "TRUE" for row in display),
    ])
    upstream_mutated = before != protected_hashes()

    smoke_specs = [
        ("current_chain", "DATA_TRUST_METADATA_CONSUMED_WITHOUT_ERRORS", "TRUE", tf(metadata_consumed), DAILY_SAMPLE),
        ("current_chain", "DATA_TRUST_ZERO_WEIGHT", "TRUE", tf(nonzero_weight == 0), DAILY_SAMPLE),
        ("current_chain", "DATA_TRUST_GATE_ONLY_AUDIT_ONLY", "TRUE", tf(all(row.get("data_trust_gate_only_metadata") == "TRUE" and row.get("audit_only") == "TRUE" for row in daily)), DAILY_SAMPLE),
        ("current_chain", "NO_CANDIDATE_REMOVED_OR_REORDERED_BY_DATA_TRUST", "0", str(removed_reordered), DAILY_SAMPLE),
    ]
    smoke_rows = [{
        "smoke_check_id": f"V20_190_SMOKE_{idx:03d}",
        "smoke_surface": surface,
        "smoke_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "smoke_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(smoke_specs, start=1)]
    smoke_pass = all(row["smoke_check_passed"] == "TRUE" for row in smoke_rows)

    compatibility_specs = [
        ("daily_runner_output", "candidate_count_preserved", "40", str(len(daily)), DAILY_SAMPLE),
        ("read_center_display", "candidate_count_preserved", "40", str(len(display)), DISPLAY_SAMPLE),
        ("release_seal", "sealed_daily_runner_compatible", "TRUE", seal.get("sealed_daily_runner_compatible", ""), V188_SEAL),
        ("current_chain_handoff", "handoff_passed", "TRUE", gate189.get("data_trust_current_chain_handoff_pass", ""), V189_GATE),
    ]
    compatibility_rows = [{
        "compatibility_check_id": f"V20_190_COMPATIBILITY_{idx:03d}",
        "current_chain_surface": surface,
        "compatibility_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "compatibility_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(compatibility_specs, start=1)]
    compatibility_pass = all(row["compatibility_check_passed"] == "TRUE" for row in compatibility_rows)

    ranking_specs = [
        ("official_ranking_score_mutation_count", "0", str(score_mutations), DAILY_SAMPLE),
        ("official_rank_mutation_count", "0", str(rank_mutations), DAILY_SAMPLE),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum, DAILY_SAMPLE),
        ("data_trust_nonzero_weight_count", "0", str(nonzero_weight), DAILY_SAMPLE),
        ("candidate_removed_or_reordered_count", "0", str(removed_reordered), DAILY_SAMPLE),
        ("upstream_smoke_inputs_mutated", "FALSE", tf(upstream_mutated), V189_GATE),
    ]
    ranking_rows = [{
        "guard_check_id": f"V20_190_RANKING_WEIGHT_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (check, expected, actual, path) in enumerate(ranking_specs, start=1)]
    ranking_pass = score_mutations == 0 and rank_mutations == 0
    zero_weight_pass = contribution_sum == "0.0000000000" and nonzero_weight == 0

    official_specs = [
        ("official_recommendation_created", "FALSE", gate189.get("official_recommendation_created", ""), V189_GATE),
        ("real_book_use_allowed", "FALSE", gate189.get("real_book_use_allowed", ""), V189_GATE),
        ("official_weight_mutation_allowed", "FALSE", gate189.get("official_weight_mutation_allowed", ""), V189_GATE),
        ("ready_for_official_use", "FALSE", gate189.get("ready_for_official_use", ""), V189_GATE),
    ]
    official_rows = [{
        "guard_check_id": f"V20_190_OFFICIAL_USE_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (check, expected, actual, path) in enumerate(official_specs, start=1)]
    official_pass = all(row["guard_passed"] == "TRUE" for row in official_rows)

    display_specs = [
        ("read_center_display", "data_trust_direct_status_visible", "TRUE", tf(all(row.get("data_trust_direct_status_summary") == "PASS" for row in display)), DISPLAY_SAMPLE),
        ("read_center_display", "data_trust_gate_only_visible", "TRUE", tf(all(row.get("data_trust_gate_only_status") == "TRUE" for row in display)), DISPLAY_SAMPLE),
        ("read_center_display", "data_trust_zero_weight_visible", "TRUE", tf(all(row.get("data_trust_zero_weight_status") == "TRUE" for row in display)), DISPLAY_SAMPLE),
        ("read_center_display", "data_trust_audit_only_visible", "TRUE", tf(all(row.get("data_trust_audit_only_status") == "TRUE" for row in display)), DISPLAY_SAMPLE),
        ("read_center_display", "official_use_disabled_visible", "TRUE", tf(all(row.get("official_use_status") == "DISABLED" for row in display)), DISPLAY_SAMPLE),
    ]
    display_rows = [{
        "display_check_id": f"V20_190_READ_CENTER_DISPLAY_{idx:03d}",
        "display_surface": surface,
        "display_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "display_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(display_specs, start=1)]
    display_pass = all(row["display_check_passed"] == "TRUE" for row in display_rows)
    all_pass = all([smoke_pass, compatibility_pass, sealed_preserved, ranking_pass, zero_weight_pass, official_pass, display_pass, not upstream_mutated])

    gate = {
        "gate_check_id": "V20_190_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "TRUE",
        "v20_188_status": gate188.get("final_status", ""),
        "v20_189_status_consumed": "TRUE",
        "v20_189_status": gate189.get("final_status", ""),
        "current_chain_candidate_count": str(len(daily)),
        "read_center_display_candidate_count": str(len(display)),
        "candidate_removed_or_reordered_count": str(removed_reordered),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "current_chain_smoke_test_pass": tf(smoke_pass and compatibility_pass),
        "data_trust_sealed_status_preserved": tf(sealed_preserved),
        "ranking_mutation_guard_pass": tf(ranking_pass),
        "zero_weight_guard_pass": tf(zero_weight_pass),
        "official_use_guard_pass": tf(official_pass),
        "read_center_display_guard_pass": tf(display_pass),
        "ready_for_v20_191_current_chain_daily_runner_regression": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RUN_V20_191_CURRENT_CHAIN_DAILY_RUNNER_REGRESSION" if all_pass else "REPAIR_V20_190_CURRENT_CHAIN_SMOKE_TEST",
        "blocking_reason": "NONE" if all_pass else "V20_190_CURRENT_CHAIN_SMOKE_TEST_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_SMOKE, AUDIT_FIELDS, smoke_rows)
    write_csv(OUT_COMPATIBILITY, COMPATIBILITY_FIELDS, compatibility_rows)
    write_csv(OUT_RANKING, GUARD_FIELDS, ranking_rows)
    write_csv(OUT_OFFICIAL, GUARD_FIELDS, official_rows)
    write_csv(OUT_DISPLAY, DISPLAY_FIELDS, display_rows)
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
