#!/usr/bin/env python
"""V20.189 DATA_TRUST current chain handoff."""

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
V188_GUARDRAIL = FACTORS / "V20_188_DATA_TRUST_FINAL_SEAL_GUARDRAIL_AUDIT.csv"
V188_FORBIDDEN = FACTORS / "V20_188_DATA_TRUST_FINAL_FORBIDDEN_USE_SEAL_AUDIT.csv"
V188_SUMMARY = FACTORS / "V20_188_OPERATOR_FACING_SEAL_SUMMARY.csv"
V188_GATE = FACTORS / "V20_188_NEXT_STAGE_GATE.csv"
V188_REPORT = READ_CENTER / "V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_REPORT.md"

PROTECTED = [
    DAILY_SAMPLE, DISPLAY_SAMPLE, V188_SEAL, V188_GUARDRAIL,
    V188_FORBIDDEN, V188_SUMMARY, V188_GATE, V188_REPORT,
]

OUT_HANDOFF = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_AUDIT.csv"
OUT_COMPATIBILITY = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv"
OUT_GUARD = FACTORS / "V20_189_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_GATE = FACTORS / "V20_189_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_REPORT.md"

READY_V188 = "PASS_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_READY_FOR_V20_189_CURRENT_CHAIN_HANDOFF"
PASS_STATUS = "PASS_V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_READY_FOR_V20_190_CURRENT_CHAIN_SMOKE_TEST"
BLOCKED_STATUS = "BLOCKED_V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_CURRENT_CHAIN_HANDOFF"

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
    "handoff_check_id", "handoff_surface", "handoff_check",
    "expected_value", "actual_value", "handoff_check_passed",
    "source_artifact", *COMMON.keys(),
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
GATE_FIELDS = [
    "gate_check_id", "v20_188_status_consumed", "v20_188_status",
    "current_chain_candidate_count", "read_center_display_candidate_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "data_trust_current_chain_handoff_pass", "data_trust_sealed_status_preserved",
    "ranking_mutation_guard_pass", "official_use_guard_pass",
    "ready_for_v20_190_current_chain_smoke_test", "ready_for_official_use",
    "real_book_use_allowed", "official_recommendation_created",
    "official_weight_mutation_allowed", "data_trust_zero_weight",
    "data_trust_gate_only", "data_trust_audit_only",
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
        "# V20.189 DATA_TRUST Current Chain Handoff Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- data_trust_current_chain_handoff_pass: {gate['data_trust_current_chain_handoff_pass']}",
        f"- data_trust_sealed_status_preserved: {gate['data_trust_sealed_status_preserved']}",
        f"- ranking_mutation_guard_pass: {gate['ranking_mutation_guard_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- ready_for_v20_190_current_chain_smoke_test: {gate['ready_for_v20_190_current_chain_smoke_test']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        f"- official_recommendation_created: {gate['official_recommendation_created']}",
        f"- official_weight_mutation_allowed: {gate['official_weight_mutation_allowed']}",
        "",
        "Current chain handoff confirms DATA_TRUST remains read-center-disclosed zero-weight gate-only audit metadata. It does not alter official score or rank, create official recommendations, allow real-book use, or mutate official weights.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [(OUT_HANDOFF, AUDIT_FIELDS), (OUT_COMPATIBILITY, COMPATIBILITY_FIELDS), (OUT_GUARD, GUARD_FIELDS)]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_189_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "FALSE",
        "v20_188_status": "",
        "current_chain_candidate_count": "0",
        "read_center_display_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "data_trust_current_chain_handoff_pass": "FALSE",
        "data_trust_sealed_status_preserved": "FALSE",
        "ranking_mutation_guard_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "ready_for_v20_190_current_chain_smoke_test": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_189",
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
    datasets = {path: read_csv(path)[0] for path in PROTECTED if path != V188_REPORT}
    if any(not rows for rows in datasets.values()) or not V188_REPORT.exists():
        return emit_blocked("EMPTY_REQUIRED_INPUTS")

    daily = datasets[DAILY_SAMPLE]
    display = datasets[DISPLAY_SAMPLE]
    seal = datasets[V188_SEAL][0]
    gate188 = datasets[V188_GATE][0]
    if not all([
        gate188.get("final_status") == READY_V188,
        gate188.get("ready_for_v20_189_daily_runner_seal_handoff_to_current_chain") == "TRUE",
        seal.get("release_seal_created") == "TRUE",
        all(row.get("final_seal_guardrail_passed") == "TRUE" for row in datasets[V188_GUARDRAIL]),
        all(row.get("final_forbidden_use_seal_passed") == "TRUE" for row in datasets[V188_FORBIDDEN]),
    ]):
        return emit_blocked("V20_188_REQUIREMENTS_NOT_MET")

    score_mutations = sum(row.get("official_current_score") != row.get("daily_runner_score") for row in daily)
    rank_mutations = sum(row.get("official_current_rank") != row.get("daily_runner_rank") for row in daily)
    contribution_sum = f"{sum(float(row.get('data_trust_official_score_contribution', '0') or '0') for row in daily):.10f}"
    nonzero_weight = sum(row.get("data_trust_weight") != "0.0000000000" for row in daily)
    current_chain_reads_metadata = all([
        len(daily) == 40,
        all(row.get("data_trust_direct_status") == "PASS" for row in daily),
        all(row.get("data_trust_gate_only_metadata") == "TRUE" for row in daily),
        all(row.get("audit_only") == "TRUE" for row in daily),
    ])
    read_center_clear = all([
        len(display) == 40,
        all(row.get("data_trust_gate_only_status") == "TRUE" for row in display),
        all(row.get("data_trust_zero_weight_status") == "TRUE" for row in display),
        all(row.get("data_trust_audit_only_status") == "TRUE" for row in display),
        all(row.get("read_center_display_ready") == "TRUE" for row in display),
    ])
    sealed_status_preserved = all([
        seal.get("sealed_zero_weight") == "TRUE",
        seal.get("sealed_gate_only") == "TRUE",
        seal.get("sealed_audit_only") == "TRUE",
        seal.get("sealed_read_center_disclosed") == "TRUE",
        seal.get("sealed_daily_runner_compatible") == "TRUE",
        seal.get("sealed_shadow_observation_continued") == "TRUE",
        contribution_sum == "0.0000000000",
        nonzero_weight == 0,
    ])
    official_guard = all([
        gate188.get("ready_for_official_use") == "FALSE",
        gate188.get("real_book_use_allowed") == "FALSE",
        gate188.get("official_recommendation_created") == "FALSE",
        gate188.get("official_weight_mutation_allowed") == "FALSE",
        all(row.get("official_recommendation_created") == "FALSE" for row in daily),
        all(row.get("real_book_use_allowed") == "FALSE" for row in daily),
        all(row.get("official_weight_mutation_allowed") == "FALSE" for row in daily),
    ])
    upstream_mutated = before != protected_hashes()

    handoff_specs = [
        ("current_daily_research_chain", "DATA_TRUST_GATE_ONLY_METADATA_READABLE", "TRUE", tf(current_chain_reads_metadata), DAILY_SAMPLE),
        ("current_daily_research_chain", "DATA_TRUST_ZERO_WEIGHT_PRESERVED", "TRUE", tf(contribution_sum == "0.0000000000" and nonzero_weight == 0), DAILY_SAMPLE),
        ("current_daily_research_chain", "DATA_TRUST_DOES_NOT_ALTER_OFFICIAL_SCORE", "0", str(score_mutations), DAILY_SAMPLE),
        ("current_daily_research_chain", "DATA_TRUST_DOES_NOT_ALTER_OFFICIAL_RANK", "0", str(rank_mutations), DAILY_SAMPLE),
        ("read_center", "DATA_TRUST_STATUS_CLEARLY_DISPLAYED", "TRUE", tf(read_center_clear), DISPLAY_SAMPLE),
    ]
    handoff_rows = [{
        "handoff_check_id": f"V20_189_HANDOFF_{idx:03d}",
        "handoff_surface": surface,
        "handoff_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "handoff_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(handoff_specs, start=1)]
    handoff_pass = all(row["handoff_check_passed"] == "TRUE" for row in handoff_rows)

    compatibility_specs = [
        ("daily_runner_output", "candidate_count_preserved", "40", str(len(daily)), DAILY_SAMPLE),
        ("read_center_display", "candidate_count_preserved", "40", str(len(display)), DISPLAY_SAMPLE),
        ("release_seal", "sealed_daily_runner_compatible", "TRUE", seal.get("sealed_daily_runner_compatible", ""), V188_SEAL),
        ("shadow_observation", "sealed_shadow_observation_continued", "TRUE", seal.get("sealed_shadow_observation_continued", ""), V188_SEAL),
    ]
    compatibility_rows = [{
        "compatibility_check_id": f"V20_189_COMPATIBILITY_{idx:03d}",
        "current_chain_surface": surface,
        "compatibility_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "compatibility_check_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (surface, check, expected, actual, path) in enumerate(compatibility_specs, start=1)]
    compatibility_pass = all(row["compatibility_check_passed"] == "TRUE" for row in compatibility_rows)

    guard_specs = [
        ("ready_for_official_use", "FALSE", gate188.get("ready_for_official_use", ""), V188_GATE),
        ("real_book_use_allowed", "FALSE", gate188.get("real_book_use_allowed", ""), V188_GATE),
        ("official_recommendation_created", "FALSE", gate188.get("official_recommendation_created", ""), V188_GATE),
        ("official_weight_mutation_allowed", "FALSE", gate188.get("official_weight_mutation_allowed", ""), V188_GATE),
        ("official_ranking_score_mutation_count", "0", str(score_mutations), DAILY_SAMPLE),
        ("official_rank_mutation_count", "0", str(rank_mutations), DAILY_SAMPLE),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum, DAILY_SAMPLE),
        ("data_trust_nonzero_weight_count", "0", str(nonzero_weight), DAILY_SAMPLE),
        ("upstream_handoff_inputs_mutated", "FALSE", tf(upstream_mutated), V188_GATE),
    ]
    guard_rows = [{
        "guard_check_id": f"V20_189_OFFICIAL_USE_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    } for idx, (check, expected, actual, path) in enumerate(guard_specs, start=1)]
    official_use_guard = all(row["guard_passed"] == "TRUE" for row in guard_rows[:4]) and not upstream_mutated
    ranking_guard = score_mutations == 0 and rank_mutations == 0
    all_pass = all([handoff_pass, compatibility_pass, sealed_status_preserved, ranking_guard, official_use_guard, not upstream_mutated])

    gate = {
        "gate_check_id": "V20_189_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "TRUE",
        "v20_188_status": gate188.get("final_status", ""),
        "current_chain_candidate_count": str(len(daily)),
        "read_center_display_candidate_count": str(len(display)),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "data_trust_current_chain_handoff_pass": tf(handoff_pass and compatibility_pass),
        "data_trust_sealed_status_preserved": tf(sealed_status_preserved),
        "ranking_mutation_guard_pass": tf(ranking_guard),
        "official_use_guard_pass": tf(official_use_guard),
        "ready_for_v20_190_current_chain_smoke_test": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "data_trust_read_center_disclosed": "TRUE",
        "data_trust_shadow_observation_continued": "TRUE",
        "recommended_next_action": "RUN_V20_190_CURRENT_CHAIN_SMOKE_TEST" if all_pass else "REPAIR_V20_189_CURRENT_CHAIN_HANDOFF",
        "blocking_reason": "NONE" if all_pass else "V20_189_CURRENT_CHAIN_HANDOFF_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_HANDOFF, AUDIT_FIELDS, handoff_rows)
    write_csv(OUT_COMPATIBILITY, COMPATIBILITY_FIELDS, compatibility_rows)
    write_csv(OUT_GUARD, GUARD_FIELDS, guard_rows)
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
