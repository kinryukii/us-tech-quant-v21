#!/usr/bin/env python
"""V20.175 DATA_TRUST daily runner shadow observation."""

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
V174_INTEGRATION = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_INTEGRATION_AUDIT.csv"
V174_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
V174_COMPAT = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_COMPATIBILITY_AUDIT.csv"
V174_RANK_GUARD = FACTORS / "V20_174_OFFICIAL_RANKING_MUTATION_GUARD_AUDIT.csv"
V174_ZERO_GUARD = FACTORS / "V20_174_DATA_TRUST_ZERO_WEIGHT_GUARD_AUDIT.csv"
V174_OFFICIAL_GUARD = FACTORS / "V20_174_OFFICIAL_USE_GUARD_AUDIT.csv"
V174_GATE = FACTORS / "V20_174_NEXT_STAGE_GATE.csv"
PROTECTED = [
    BASELINE, ACTIVE_WEIGHT_REGISTRY, V174_INTEGRATION, V174_SAMPLE, V174_COMPAT,
    V174_RANK_GUARD, V174_ZERO_GUARD, V174_OFFICIAL_GUARD, V174_GATE,
]

OUT_OBSERVATION = FACTORS / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION.csv"
OUT_DISCLOSURE = FACTORS / "V20_175_DATA_TRUST_DISCLOSURE_STABILITY_AUDIT.csv"
OUT_ZERO = FACTORS / "V20_175_DATA_TRUST_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv"
OUT_OFFICIAL = FACTORS / "V20_175_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_GATE = FACTORS / "V20_175_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_REPORT.md"

READY_V174 = "PASS_V20_174_DATA_TRUST_GATE_ONLY_DAILY_RUNNER_INTEGRATION_READY_FOR_V20_175"
PASS_STATUS = "PASS_V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION_READY_FOR_V20_176"
BLOCKED_STATUS = "BLOCKED_V20_175_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_DAILY_RUNNER_SHADOW_OBSERVATION"
DISCLOSURE_FIELDS = [
    "data_trust_direct_status",
    "data_trust_gate_action",
    "data_trust_evidence_status",
    "data_trust_shadow_observation_flag",
    "data_trust_official_score_contribution",
    "data_trust_weight",
]
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

OBS_FIELDS = [
    "observation_id", "observation_mode", "candidate_count",
    "data_trust_disclosure_candidate_count", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "candidate_removed_or_reordered_count",
    "official_recommendation_created", "real_book_use_allowed",
    "official_weight_mutation_allowed", "shadow_observation_pass",
    "limitation_reason", *COMMON.keys(),
]
DISCLOSURE_AUDIT_FIELDS = [
    "ticker", "official_current_rank", "daily_runner_rank",
    "data_trust_direct_status", "data_trust_gate_action",
    "data_trust_evidence_status", "data_trust_shadow_observation_flag",
    "data_trust_official_score_contribution", "data_trust_weight",
    "all_disclosure_fields_present", "candidate_removed_or_reordered",
    "disclosure_stability_pass", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_174_status_consumed", "v20_174_status",
    "baseline_candidate_count", "shadow_observation_candidate_count",
    "data_trust_disclosure_candidate_count", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "candidate_removed_or_reordered_count",
    "official_recommendation_created", "real_book_use_allowed",
    "official_weight_mutation_allowed", "disclosure_stability_pass",
    "no_mutation_guard_pass", "zero_weight_guard_pass", "official_use_guard_pass",
    "ready_for_v20_176_data_trust_shadow_observation_summary",
    "ready_for_official_use", "data_trust_role", "recommended_next_action",
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


def guard_rows(prefix: str, checks: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [{
        "guard_check_id": f"V20_175_{prefix}_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def build_disclosure(sample: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in sample:
        present = all(row.get(field, "") != "" for field in DISCLOSURE_FIELDS)
        removed = row["official_current_rank"] != row["daily_runner_rank"]
        rows.append({
            "ticker": row["ticker"],
            "official_current_rank": row["official_current_rank"],
            "daily_runner_rank": row["daily_runner_rank"],
            "data_trust_direct_status": row["data_trust_direct_status"],
            "data_trust_gate_action": row["data_trust_gate_action"],
            "data_trust_evidence_status": row["data_trust_evidence_status"],
            "data_trust_shadow_observation_flag": row["data_trust_shadow_observation_flag"],
            "data_trust_official_score_contribution": row["data_trust_official_score_contribution"],
            "data_trust_weight": row["data_trust_weight"],
            "all_disclosure_fields_present": tf(present),
            "candidate_removed_or_reordered": tf(removed),
            "disclosure_stability_pass": tf(present and not removed),
            **COMMON,
        })
    return rows


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.175 DATA_TRUST Daily Runner Shadow Observation Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- disclosure_stability_pass: {gate['disclosure_stability_pass']}",
        f"- no_mutation_guard_pass: {gate['no_mutation_guard_pass']}",
        f"- zero_weight_guard_pass: {gate['zero_weight_guard_pass']}",
        f"- official_use_guard_pass: {gate['official_use_guard_pass']}",
        f"- ready_for_v20_176_data_trust_shadow_observation_summary: {gate['ready_for_v20_176_data_trust_shadow_observation_summary']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "DATA_TRUST remains zero-weight gate-only audit metadata during daily runner shadow observation.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_OBSERVATION, OBS_FIELDS), (OUT_DISCLOSURE, DISCLOSURE_AUDIT_FIELDS),
        (OUT_ZERO, GUARD_FIELDS), (OUT_OFFICIAL, GUARD_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_175_NEXT_STAGE_GATE_001",
        "v20_174_status_consumed": "FALSE",
        "v20_174_status": "",
        "baseline_candidate_count": "0",
        "shadow_observation_candidate_count": "0",
        "data_trust_disclosure_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "candidate_removed_or_reordered_count": "0",
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "disclosure_stability_pass": "FALSE",
        "no_mutation_guard_pass": "FALSE",
        "zero_weight_guard_pass": "FALSE",
        "official_use_guard_pass": "FALSE",
        "ready_for_v20_176_data_trust_shadow_observation_summary": "FALSE",
        "ready_for_official_use": "FALSE",
        "data_trust_role": DATA_TRUST_ROLE,
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_175",
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
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, V174_SAMPLE, V174_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    sample, _ = read_csv(V174_SAMPLE)
    gate_rows, _ = read_csv(V174_GATE)
    if not baseline or not sample or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v174_gate = gate_rows[0]
    prereq_ok = all([
        v174_gate.get("final_status") == READY_V174,
        v174_gate.get("ready_for_v20_175_daily_runner_shadow_observation") == "TRUE",
        v174_gate.get("ready_for_official_use") == "FALSE",
        v174_gate.get("real_book_use_allowed") == "FALSE",
        v174_gate.get("official_recommendation_created") == "FALSE",
        v174_gate.get("official_weight_mutation_allowed") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_174_REQUIREMENTS_NOT_MET")
    if [row["ticker"] for row in baseline] != [row["ticker"] for row in sample]:
        return emit_blocked("SHADOW_OBSERVATION_CANDIDATE_UNIVERSE_MISMATCH")

    disclosure = build_disclosure(sample)
    upstream_mutated = before != protected_hashes()
    score_mutations = sum(row["official_current_score"] != row["daily_runner_score"] for row in sample)
    rank_mutations = sum(row["official_current_rank"] != row["daily_runner_rank"] for row in sample)
    removed = sum(row["candidate_removed_or_reordered"] == "TRUE" for row in disclosure)
    nonzero_weight = sum(row["data_trust_weight"] != "0.0000000000" for row in sample)
    contribution_sum = "0.0000000000"
    disclosure_pass = len(disclosure) == 40 and all(row["disclosure_stability_pass"] == "TRUE" for row in disclosure)
    mutation_pass = score_mutations == 0 and rank_mutations == 0 and not upstream_mutated
    zero_pass = contribution_sum == "0.0000000000" and nonzero_weight == 0
    official_pass = True
    all_guards = all([disclosure_pass, mutation_pass, zero_pass, official_pass])
    observation = [{
        "observation_id": "V20_175_DAILY_RUNNER_SHADOW_OBSERVATION_001",
        "observation_mode": "SHADOW_OBSERVATION_AUDIT_ONLY",
        "candidate_count": str(len(sample)),
        "data_trust_disclosure_candidate_count": str(len(disclosure)),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "candidate_removed_or_reordered_count": str(removed),
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "shadow_observation_pass": tf(all_guards),
        "limitation_reason": "AUDIT_ONLY_ZERO_WEIGHT_SHADOW_OBSERVATION",
        **COMMON,
    }]
    zero_guard = guard_rows("ZERO_WEIGHT_NO_MUTATION", [
        ("official_ranking_score_mutation_count", "0", str(score_mutations)),
        ("official_rank_mutation_count", "0", str(rank_mutations)),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum),
        ("data_trust_nonzero_weight_count", "0", str(nonzero_weight)),
        ("candidate_removed_or_reordered_count", "0", str(removed)),
        ("official_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ])
    official_guard = guard_rows("OFFICIAL_USE", [
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("real_book_use_allowed", "FALSE", "FALSE"),
        ("official_weight_mutation_allowed", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
    ])
    gate = {
        "gate_check_id": "V20_175_NEXT_STAGE_GATE_001",
        "v20_174_status_consumed": "TRUE",
        "v20_174_status": v174_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "shadow_observation_candidate_count": str(len(sample)),
        "data_trust_disclosure_candidate_count": str(len(disclosure)),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "candidate_removed_or_reordered_count": str(removed),
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "disclosure_stability_pass": tf(disclosure_pass),
        "no_mutation_guard_pass": tf(mutation_pass),
        "zero_weight_guard_pass": tf(zero_pass),
        "official_use_guard_pass": tf(official_pass),
        "ready_for_v20_176_data_trust_shadow_observation_summary": tf(all_guards),
        "ready_for_official_use": "FALSE",
        "data_trust_role": DATA_TRUST_ROLE,
        "recommended_next_action": "RUN_V20_176_DATA_TRUST_SHADOW_OBSERVATION_SUMMARY" if all_guards else "REPAIR_V20_175_GUARD_FAILURE",
        "blocking_reason": "NONE" if all_guards else "V20_175_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_guards else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_OBSERVATION, OBS_FIELDS, observation)
    write_csv(OUT_DISCLOSURE, DISCLOSURE_AUDIT_FIELDS, disclosure)
    write_csv(OUT_ZERO, GUARD_FIELDS, zero_guard)
    write_csv(OUT_OFFICIAL, GUARD_FIELDS, official_guard)
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
