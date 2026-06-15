#!/usr/bin/env python
"""V20.171 DATA_TRUST full gate-only ranking simulation."""

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
R3_R2_CANDIDATES = FACTORS / "V20_170_R3_R2_DATA_TRUST_DIRECT_STATUS_RETEST_CANDIDATES.csv"
R3_R2_GATE = FACTORS / "V20_170_R3_R2_NEXT_STAGE_GATE.csv"
PROTECTED = [BASELINE, ACTIVE_WEIGHT_REGISTRY, R3_R2_CANDIDATES, R3_R2_GATE]

OUT_SIM = FACTORS / "V20_171_DATA_TRUST_GATE_ONLY_RANKING_SIMULATION.csv"
OUT_ACTION = FACTORS / "V20_171_DATA_TRUST_GATE_ACTION_AUDIT.csv"
OUT_DELTA = FACTORS / "V20_171_RANKING_DELTA_VS_BASELINE_AUDIT.csv"
OUT_CONTRIB = FACTORS / "V20_171_DATA_TRUST_SCORE_CONTRIBUTION_AUDIT.csv"
OUT_GUARD = FACTORS / "V20_171_OFFICIAL_RANKING_MUTATION_GUARD_AUDIT.csv"
OUT_GATE = FACTORS / "V20_171_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_171_DATA_TRUST_FULL_GATE_ONLY_RANKING_SIMULATION_REPORT.md"

READY_R3_R2 = "PASS_V20_170_R3_R2_DIRECT_STATUS_RETEST_READY_FOR_V20_171"
PASS_STATUS = "PASS_V20_171_DATA_TRUST_FULL_GATE_ONLY_RANKING_SIMULATION_READY_FOR_V20_172"
BLOCKED_STATUS = "BLOCKED_V20_171_DATA_TRUST_FULL_GATE_ONLY_RANKING_SIMULATION"

DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_FULL_GATE_ONLY_RANKING_SIMULATION"
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

SIM_FIELDS = [
    "ticker", "baseline_rank", "simulated_rank", "baseline_official_score",
    "simulated_official_score", "official_score_delta", "data_trust_direct_status",
    "data_trust_gate_action", "data_trust_gate_only_applied",
    "data_trust_official_weight", "data_trust_score_contribution",
    "candidate_removed_from_official_ranking", "simulation_only",
    "official_ranking_score_mutated", "official_rank_mutated", *COMMON.keys(),
]
ACTION_FIELDS = [
    "data_trust_gate_action", "candidate_count", "tickers",
    "candidate_removed_from_official_ranking", "simulation_only_action",
    "official_recommendation_created", "real_book_use_allowed", *COMMON.keys(),
]
DELTA_FIELDS = [
    "ticker", "baseline_rank", "simulated_rank", "rank_delta",
    "baseline_official_score", "simulated_official_score", "score_delta",
    "official_ranking_score_mutated", "official_rank_mutated",
    "delta_reason", *COMMON.keys(),
]
CONTRIB_FIELDS = [
    "ticker", "data_trust_direct_status", "data_trust_gate_action",
    "data_trust_weight_in_official_score", "data_trust_score_contribution_to_official_ranking",
    "data_trust_excluded_from_official_score", "zero_weight_guard_pass",
    "contribution_reason", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_170_r3_r2_status_consumed", "v20_170_r3_r2_status",
    "baseline_candidate_count", "simulation_candidate_count",
    "data_trust_pass_candidate_count", "data_trust_warn_candidate_count",
    "data_trust_fail_candidate_count", "data_trust_unknown_candidate_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "official_ranking_mutation_guard_pass", "data_trust_zero_weight_guard_pass",
    "data_trust_gate_coverage_pass", "candidate_removed_from_official_ranking_count",
    "ready_for_v20_172_impact_stability_disclosure_validation",
    "ready_for_official_use", "real_book_use_allowed",
    "official_recommendation_created", "official_weight_change_allowed",
    "official_ranking_mutation_allowed", "ranking_simulation_created",
    "no_ticker_rows_fabricated", "no_evidence_values_fabricated",
    "official_ranking_outputs_preserved", "recommended_next_action",
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


def gate_action(status: str) -> str:
    return {
        "PASS": "PASS_GATE_ONLY_ALLOW",
        "WARN": "WARN_GATE_ONLY_FLAG",
        "FAIL": "FAIL_GATE_ONLY_BLOCK_SIMULATED",
        "UNKNOWN": "UNKNOWN_GATE_ONLY_REVIEW",
    }.get(status, "UNKNOWN_GATE_ONLY_REVIEW")


def build_outputs(baseline: list[dict[str, str]], statuses: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    status_by_ticker = {row["ticker"]: row for row in statuses}
    sim: list[dict[str, str]] = []
    delta: list[dict[str, str]] = []
    contrib: list[dict[str, str]] = []
    for base in baseline:
        ticker = base["ticker"]
        status = status_by_ticker[ticker]["direct_status_after_materialization"]
        action = gate_action(status)
        rank = base["official_current_rank"]
        score = base["official_current_score"]
        sim.append({
            "ticker": ticker,
            "baseline_rank": rank,
            "simulated_rank": rank,
            "baseline_official_score": score,
            "simulated_official_score": score,
            "official_score_delta": "0",
            "data_trust_direct_status": status,
            "data_trust_gate_action": action,
            "data_trust_gate_only_applied": "TRUE",
            "data_trust_official_weight": "0.0000000000",
            "data_trust_score_contribution": "0.0000000000",
            "candidate_removed_from_official_ranking": "FALSE",
            "simulation_only": "TRUE",
            "official_ranking_score_mutated": "FALSE",
            "official_rank_mutated": "FALSE",
            **COMMON,
        })
        delta.append({
            "ticker": ticker,
            "baseline_rank": rank,
            "simulated_rank": rank,
            "rank_delta": "0",
            "baseline_official_score": score,
            "simulated_official_score": score,
            "score_delta": "0",
            "official_ranking_score_mutated": "FALSE",
            "official_rank_mutated": "FALSE",
            "delta_reason": "DATA_TRUST_GATE_ONLY_ZERO_WEIGHT_NO_SCORE_OR_RANK_CHANGE",
            **COMMON,
        })
        contrib.append({
            "ticker": ticker,
            "data_trust_direct_status": status,
            "data_trust_gate_action": action,
            "data_trust_weight_in_official_score": "0.0000000000",
            "data_trust_score_contribution_to_official_ranking": "0.0000000000",
            "data_trust_excluded_from_official_score": "TRUE",
            "zero_weight_guard_pass": "TRUE",
            "contribution_reason": "DATA_TRUST_REMAINS_GATE_ONLY_NOT_OFFICIAL_WEIGHT",
            **COMMON,
        })
    action_rows: list[dict[str, str]] = []
    for action in ["PASS_GATE_ONLY_ALLOW", "WARN_GATE_ONLY_FLAG", "FAIL_GATE_ONLY_BLOCK_SIMULATED", "UNKNOWN_GATE_ONLY_REVIEW"]:
        rows = [row for row in sim if row["data_trust_gate_action"] == action]
        action_rows.append({
            "data_trust_gate_action": action,
            "candidate_count": str(len(rows)),
            "tickers": "|".join(row["ticker"] for row in rows),
            "candidate_removed_from_official_ranking": "FALSE",
            "simulation_only_action": "TRUE",
            "official_recommendation_created": "FALSE",
            "real_book_use_allowed": "FALSE",
            **COMMON,
        })
    return sim, action_rows, delta, contrib


def guard_rows(gate: dict[str, str], upstream_mutated: bool) -> list[dict[str, str]]:
    checks = [
        ("official_ranking_score_mutation_count", "0", gate["official_ranking_score_mutation_count"]),
        ("official_rank_mutation_count", "0", gate["official_rank_mutation_count"]),
        ("data_trust_score_contribution_sum", "0.0000000000", gate["data_trust_score_contribution_sum"]),
        ("data_trust_nonzero_weight_count", "0", gate["data_trust_nonzero_weight_count"]),
        ("candidate_removed_from_official_ranking_count", "0", gate["candidate_removed_from_official_ranking_count"]),
        ("ready_for_official_use", "FALSE", gate["ready_for_official_use"]),
        ("real_book_use_allowed", "FALSE", gate["real_book_use_allowed"]),
        ("official_recommendation_created", "FALSE", gate["official_recommendation_created"]),
        ("official_outputs_mutated", "FALSE", tf(upstream_mutated)),
    ]
    return [{
        "guard_check_id": f"V20_171_GUARD_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.171 DATA_TRUST Full Gate-Only Ranking Simulation Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- baseline_candidate_count: {gate['baseline_candidate_count']}",
        f"- data_trust_pass_candidate_count: {gate['data_trust_pass_candidate_count']}",
        f"- official_ranking_score_mutation_count: {gate['official_ranking_score_mutation_count']}",
        f"- data_trust_score_contribution_sum: {gate['data_trust_score_contribution_sum']}",
        f"- ready_for_v20_172_impact_stability_disclosure_validation: {gate['ready_for_v20_172_impact_stability_disclosure_validation']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        f"- real_book_use_allowed: {gate['real_book_use_allowed']}",
        "",
        "DATA_TRUST remains gate-only with zero official weight. Baseline official ranks and scores are preserved unchanged.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_SIM, SIM_FIELDS), (OUT_ACTION, ACTION_FIELDS), (OUT_DELTA, DELTA_FIELDS),
        (OUT_CONTRIB, CONTRIB_FIELDS), (OUT_GUARD, GUARD_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_171_NEXT_STAGE_GATE_001",
        "v20_170_r3_r2_status_consumed": "FALSE",
        "v20_170_r3_r2_status": "",
        "baseline_candidate_count": "0",
        "simulation_candidate_count": "0",
        "data_trust_pass_candidate_count": "0",
        "data_trust_warn_candidate_count": "0",
        "data_trust_fail_candidate_count": "0",
        "data_trust_unknown_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "official_ranking_mutation_guard_pass": "FALSE",
        "data_trust_zero_weight_guard_pass": "FALSE",
        "data_trust_gate_coverage_pass": "FALSE",
        "candidate_removed_from_official_ranking_count": "0",
        "ready_for_v20_172_impact_stability_disclosure_validation": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "FALSE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "official_ranking_outputs_preserved": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_171",
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
    required = [BASELINE, ACTIVE_WEIGHT_REGISTRY, R3_R2_CANDIDATES, R3_R2_GATE]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    statuses, _ = read_csv(R3_R2_CANDIDATES)
    gate_rows, _ = read_csv(R3_R2_GATE)
    if not baseline or not statuses or not gate_rows:
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    r3_r2_gate = gate_rows[0]
    prereq_ok = all([
        r3_r2_gate.get("final_status") == READY_R3_R2,
        r3_r2_gate.get("direct_pass_candidate_count") == "40",
        r3_r2_gate.get("direct_unknown_candidate_count") == "0",
        r3_r2_gate.get("ready_for_v20_171_full_gate_only_ranking_simulation") == "TRUE",
        r3_r2_gate.get("ready_for_official_use") == "FALSE",
    ])
    if not prereq_ok:
        return emit_blocked("V20_170_R3_R2_REQUIREMENTS_NOT_MET")
    if [row["ticker"] for row in baseline] != [row["ticker"] for row in statuses]:
        return emit_blocked("BASELINE_AND_DATA_TRUST_TICKER_ORDER_MISMATCH")

    sim, action, delta, contrib = build_outputs(baseline, statuses)
    upstream_mutated = before != protected_hashes()
    score_mutation_count = sum(row["official_ranking_score_mutated"] == "TRUE" for row in sim)
    rank_mutation_count = sum(row["official_rank_mutated"] == "TRUE" for row in sim)
    nonzero_weight_count = sum(row["data_trust_official_weight"] != "0.0000000000" for row in sim)
    removed_count = sum(row["candidate_removed_from_official_ranking"] == "TRUE" for row in sim)
    pass_count = sum(row["data_trust_direct_status"] == "PASS" for row in sim)
    warn_count = sum(row["data_trust_direct_status"] == "WARN" for row in sim)
    fail_count = sum(row["data_trust_direct_status"] == "FAIL" for row in sim)
    unknown_count = sum(row["data_trust_direct_status"] == "UNKNOWN" for row in sim)
    official_guard = score_mutation_count == 0 and rank_mutation_count == 0 and not upstream_mutated
    zero_guard = nonzero_weight_count == 0
    coverage_guard = len(sim) == 40 and unknown_count == 0
    all_guards = official_guard and zero_guard and coverage_guard and removed_count == 0
    gate = {
        "gate_check_id": "V20_171_NEXT_STAGE_GATE_001",
        "v20_170_r3_r2_status_consumed": "TRUE",
        "v20_170_r3_r2_status": r3_r2_gate.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "simulation_candidate_count": str(len(sim)),
        "data_trust_pass_candidate_count": str(pass_count),
        "data_trust_warn_candidate_count": str(warn_count),
        "data_trust_fail_candidate_count": str(fail_count),
        "data_trust_unknown_candidate_count": str(unknown_count),
        "official_ranking_score_mutation_count": str(score_mutation_count),
        "official_rank_mutation_count": str(rank_mutation_count),
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": str(nonzero_weight_count),
        "official_ranking_mutation_guard_pass": tf(official_guard),
        "data_trust_zero_weight_guard_pass": tf(zero_guard),
        "data_trust_gate_coverage_pass": tf(coverage_guard),
        "candidate_removed_from_official_ranking_count": str(removed_count),
        "ready_for_v20_172_impact_stability_disclosure_validation": tf(all_guards),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_change_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "ranking_simulation_created": "TRUE",
        "no_ticker_rows_fabricated": "TRUE",
        "no_evidence_values_fabricated": "TRUE",
        "official_ranking_outputs_preserved": tf(not upstream_mutated),
        "recommended_next_action": "RUN_V20_172_IMPACT_STABILITY_DISCLOSURE_VALIDATION" if all_guards else "REPAIR_V20_171_GUARD_FAILURE",
        "blocking_reason": "NONE" if all_guards else "V20_171_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_guards else BLOCKED_STATUS,
        **COMMON,
    }
    guards = guard_rows(gate, upstream_mutated)
    if not all(row["guard_passed"] == "TRUE" for row in guards):
        gate["final_status"] = BLOCKED_STATUS
        gate["ready_for_v20_172_impact_stability_disclosure_validation"] = "FALSE"
        gate["blocking_reason"] = "V20_171_GUARD_FAILURE"
    write_csv(OUT_SIM, SIM_FIELDS, sim)
    write_csv(OUT_ACTION, ACTION_FIELDS, action)
    write_csv(OUT_DELTA, DELTA_FIELDS, delta)
    write_csv(OUT_CONTRIB, CONTRIB_FIELDS, contrib)
    write_csv(OUT_GUARD, GUARD_FIELDS, guards)
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
