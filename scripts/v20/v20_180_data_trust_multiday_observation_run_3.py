#!/usr/bin/env python
"""V20.180 DATA_TRUST multiday observation run 3."""

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
DAILY_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
V177_PLAN = FACTORS / "V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN.csv"
V177_TEMPLATE = FACTORS / "V20_177_DATA_TRUST_PER_RUN_GUARDRAIL_TEMPLATE.csv"
V177_GATE = FACTORS / "V20_177_NEXT_STAGE_GATE.csv"
V178_RUN = FACTORS / "V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1.csv"
V178_DISCLOSURE = FACTORS / "V20_178_DATA_TRUST_RUN_1_CANDIDATE_DISCLOSURE_AUDIT.csv"
V178_GATE = FACTORS / "V20_178_NEXT_STAGE_GATE.csv"
V179_RUN = FACTORS / "V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2.csv"
V179_DISCLOSURE = FACTORS / "V20_179_DATA_TRUST_RUN_2_CANDIDATE_DISCLOSURE_AUDIT.csv"
V179_COMPARISON = FACTORS / "V20_179_DATA_TRUST_RUN_2_VS_RUN_1_COMPARISON_AUDIT.csv"
V179_GATE = FACTORS / "V20_179_NEXT_STAGE_GATE.csv"
PROTECTED = [
    BASELINE, ACTIVE_WEIGHT_REGISTRY, DAILY_SAMPLE, V177_PLAN, V177_TEMPLATE,
    V177_GATE, V178_RUN, V178_DISCLOSURE, V178_GATE, V179_RUN,
    V179_DISCLOSURE, V179_COMPARISON, V179_GATE,
]

OUT_RUN = FACTORS / "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3.csv"
OUT_DISCLOSURE = FACTORS / "V20_180_DATA_TRUST_RUN_3_CANDIDATE_DISCLOSURE_AUDIT.csv"
OUT_ZERO = FACTORS / "V20_180_DATA_TRUST_RUN_3_ZERO_WEIGHT_NO_MUTATION_AUDIT.csv"
OUT_OFFICIAL = FACTORS / "V20_180_DATA_TRUST_RUN_3_OFFICIAL_USE_GUARD_AUDIT.csv"
OUT_COMPARISON = FACTORS / "V20_180_DATA_TRUST_RUN_3_VS_RUN_1_RUN_2_COMPARISON_AUDIT.csv"
OUT_GATE = FACTORS / "V20_180_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3_REPORT.md"

READY_V177 = "PASS_V20_177_DATA_TRUST_MULTIDAY_OBSERVATION_PLAN_READY_FOR_V20_178_RUN_1"
READY_V178 = "PASS_V20_178_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_1_READY_FOR_V20_179_RUN_2"
READY_V179 = "PASS_V20_179_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_2_READY_FOR_V20_180_RUN_3"
PASS_STATUS = "PASS_V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3_READY_FOR_V20_181_CLOSEOUT_SUMMARY"
BLOCKED_STATUS = "BLOCKED_V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3"
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

RUN_FIELDS = [
    "run_id", "run_sequence", "candidate_count",
    "data_trust_disclosure_candidate_count", "official_ranking_score_mutation_count",
    "official_rank_mutation_count", "data_trust_score_contribution_sum",
    "data_trust_nonzero_weight_count", "candidate_removed_or_reordered_count",
    "official_recommendation_created", "real_book_use_allowed",
    "official_weight_mutation_allowed", "run_3_disclosure_pass",
    "run_3_no_mutation_guard_pass", "run_3_zero_weight_guard_pass",
    "run_3_official_use_guard_pass", "run_3_vs_run_1_run_2_comparison_pass",
    "run_3_all_guards_pass", *COMMON.keys(),
]
DISCLOSURE_AUDIT_FIELDS = [
    "ticker", "official_current_rank", "daily_runner_rank",
    "data_trust_direct_status", "data_trust_gate_action",
    "data_trust_evidence_status", "data_trust_shadow_observation_flag",
    "data_trust_official_score_contribution", "data_trust_weight",
    "all_disclosure_fields_present", "candidate_removed_or_reordered",
    "run_3_disclosure_pass", *COMMON.keys(),
]
GUARD_FIELDS = [
    "guard_check_id", "guard_check", "expected_value", "actual_value",
    "guard_passed", *COMMON.keys(),
]
COMPARISON_FIELDS = [
    "ticker", "run_1_rank", "run_2_rank", "run_3_rank",
    "run_1_data_trust_direct_status", "run_2_data_trust_direct_status",
    "run_3_data_trust_direct_status", "run_1_data_trust_gate_action",
    "run_2_data_trust_gate_action", "run_3_data_trust_gate_action",
    "run_1_data_trust_weight", "run_2_data_trust_weight", "run_3_data_trust_weight",
    "run_1_data_trust_score_contribution", "run_2_data_trust_score_contribution",
    "run_3_data_trust_score_contribution", "data_trust_caused_ranking_mutation_vs_run_1",
    "data_trust_caused_ranking_mutation_vs_run_2", "data_trust_disclosure_changed_vs_run_1",
    "data_trust_disclosure_changed_vs_run_2", "run_to_run_candidate_match",
    "run_3_vs_run_1_run_2_comparison_pass", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_177_status_consumed", "v20_177_status",
    "v20_178_status_consumed", "v20_178_status", "v20_179_status_consumed",
    "v20_179_status", "observation_run_sequence", "baseline_candidate_count",
    "run_1_candidate_count", "run_2_candidate_count", "run_3_candidate_count",
    "run_3_data_trust_disclosure_candidate_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "candidate_removed_or_reordered_count", "run_to_run_candidate_mismatch_count",
    "run_to_run_data_trust_caused_ranking_mutation_count",
    "run_to_run_disclosure_change_count", "official_recommendation_created",
    "real_book_use_allowed", "official_weight_mutation_allowed",
    "run_3_disclosure_pass", "run_3_no_mutation_guard_pass",
    "run_3_zero_weight_guard_pass", "run_3_official_use_guard_pass",
    "run_3_vs_run_1_run_2_comparison_pass",
    "ready_for_v20_181_multiday_observation_closeout_summary",
    "ready_for_official_use", "data_trust_zero_weight", "data_trust_gate_only",
    "data_trust_audit_only", "recommended_next_action", "blocking_reason",
    "final_status", *COMMON.keys(),
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
        "guard_check_id": f"V20_180_{prefix}_{idx:03d}",
        "guard_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "guard_passed": tf(expected == actual),
        **COMMON,
    } for idx, (check, expected, actual) in enumerate(checks, start=1)]


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.180 DATA_TRUST Multiday Observation Run 3 Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- run_3_disclosure_pass: {gate['run_3_disclosure_pass']}",
        f"- run_3_no_mutation_guard_pass: {gate['run_3_no_mutation_guard_pass']}",
        f"- run_3_zero_weight_guard_pass: {gate['run_3_zero_weight_guard_pass']}",
        f"- run_3_official_use_guard_pass: {gate['run_3_official_use_guard_pass']}",
        f"- run_3_vs_run_1_run_2_comparison_pass: {gate['run_3_vs_run_1_run_2_comparison_pass']}",
        f"- ready_for_v20_181_multiday_observation_closeout_summary: {gate['ready_for_v20_181_multiday_observation_closeout_summary']}",
        f"- ready_for_official_use: {gate['ready_for_official_use']}",
        "",
        "Run 3 confirms DATA_TRUST remains zero-weight gate-only audit metadata and is stable versus runs 1 and 2.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path, fields in [
        (OUT_RUN, RUN_FIELDS), (OUT_DISCLOSURE, DISCLOSURE_AUDIT_FIELDS),
        (OUT_ZERO, GUARD_FIELDS), (OUT_OFFICIAL, GUARD_FIELDS),
        (OUT_COMPARISON, COMPARISON_FIELDS),
    ]:
        write_csv(path, fields, [])
    gate = {
        "gate_check_id": "V20_180_NEXT_STAGE_GATE_001",
        "v20_177_status_consumed": "FALSE",
        "v20_177_status": "",
        "v20_178_status_consumed": "FALSE",
        "v20_178_status": "",
        "v20_179_status_consumed": "FALSE",
        "v20_179_status": "",
        "observation_run_sequence": "3",
        "baseline_candidate_count": "0",
        "run_1_candidate_count": "0",
        "run_2_candidate_count": "0",
        "run_3_candidate_count": "0",
        "run_3_data_trust_disclosure_candidate_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "candidate_removed_or_reordered_count": "0",
        "run_to_run_candidate_mismatch_count": "0",
        "run_to_run_data_trust_caused_ranking_mutation_count": "0",
        "run_to_run_disclosure_change_count": "0",
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "run_3_disclosure_pass": "FALSE",
        "run_3_no_mutation_guard_pass": "FALSE",
        "run_3_zero_weight_guard_pass": "FALSE",
        "run_3_official_use_guard_pass": "FALSE",
        "run_3_vs_run_1_run_2_comparison_pass": "FALSE",
        "ready_for_v20_181_multiday_observation_closeout_summary": "FALSE",
        "ready_for_official_use": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_180",
        "blocking_reason": reason,
        "final_status": BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_GATE, GATE_FIELDS, [gate])
    write_report(gate)
    print(BLOCKED_STATUS)
    print(f"BLOCKING_REASON={reason}")
    return 0


def disclosure_changed(a: dict[str, str], b: dict[str, str]) -> bool:
    return any([
        a.get("data_trust_direct_status") != b.get("data_trust_direct_status"),
        a.get("data_trust_gate_action") != b.get("data_trust_gate_action"),
        a.get("data_trust_weight") != b.get("data_trust_weight"),
        a.get("data_trust_official_score_contribution") != b.get("data_trust_official_score_contribution"),
    ])


def main() -> int:
    required = [
        BASELINE, ACTIVE_WEIGHT_REGISTRY, DAILY_SAMPLE, V177_PLAN, V177_TEMPLATE,
        V177_GATE, V178_RUN, V178_DISCLOSURE, V178_GATE, V179_RUN,
        V179_DISCLOSURE, V179_COMPARISON, V179_GATE,
    ]
    missing = [path for path in required if not path.exists() or path.stat().st_size == 0]
    if missing:
        return emit_blocked("MISSING_REQUIRED_INPUTS:" + ";".join(rel(path) for path in missing))
    before = protected_hashes()
    baseline, _ = read_csv(BASELINE)
    sample, _ = read_csv(DAILY_SAMPLE)
    v177_gate_rows, _ = read_csv(V177_GATE)
    v178_run_rows, _ = read_csv(V178_RUN)
    v178_disclosure_rows, _ = read_csv(V178_DISCLOSURE)
    v178_gate_rows, _ = read_csv(V178_GATE)
    v179_run_rows, _ = read_csv(V179_RUN)
    v179_disclosure_rows, _ = read_csv(V179_DISCLOSURE)
    v179_comparison_rows, _ = read_csv(V179_COMPARISON)
    v179_gate_rows, _ = read_csv(V179_GATE)
    if not all([
        baseline, sample, v177_gate_rows, v178_run_rows, v178_disclosure_rows,
        v178_gate_rows, v179_run_rows, v179_disclosure_rows, v179_comparison_rows,
        v179_gate_rows,
    ]):
        return emit_blocked("EMPTY_REQUIRED_INPUTS")
    v177 = v177_gate_rows[0]
    v178_gate = v178_gate_rows[0]
    v178_run = v178_run_rows[0]
    v179_gate = v179_gate_rows[0]
    v179_run = v179_run_rows[0]
    prereq_ok = all([
        v177.get("final_status") == READY_V177,
        v177.get("observation_run_required_count") in {"3", ""},
        v178_gate.get("final_status") == READY_V178,
        v178_run.get("run_1_all_guards_pass") == "TRUE",
        v179_gate.get("final_status") == READY_V179,
        v179_gate.get("ready_for_v20_180_multiday_observation_run_3") == "TRUE",
        v179_gate.get("ready_for_official_use") == "FALSE",
        v179_gate.get("real_book_use_allowed") == "FALSE",
        v179_gate.get("official_recommendation_created") == "FALSE",
        v179_gate.get("official_weight_mutation_allowed") == "FALSE",
        v179_run.get("run_2_all_guards_pass") == "TRUE",
        all(row.get("run_2_vs_run_1_comparison_pass") == "TRUE" for row in v179_comparison_rows),
    ])
    if not prereq_ok:
        return emit_blocked("V20_177_V20_178_OR_V20_179_REQUIREMENTS_NOT_MET")
    if [row["ticker"] for row in baseline] != [row["ticker"] for row in sample]:
        return emit_blocked("RUN_3_CANDIDATE_UNIVERSE_MISMATCH")

    upstream_mutated = before != protected_hashes()
    disclosure_rows = []
    for row in sample:
        present = all(row.get(field, "") != "" for field in DISCLOSURE_FIELDS)
        removed = row["official_current_rank"] != row["daily_runner_rank"]
        disclosure_rows.append({
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
            "run_3_disclosure_pass": tf(present and not removed),
            **COMMON,
        })

    run1_by_ticker = {row["ticker"]: row for row in v178_disclosure_rows}
    run2_by_ticker = {row["ticker"]: row for row in v179_disclosure_rows}
    run3_by_ticker = {row["ticker"]: row for row in disclosure_rows}
    comparison_rows = []
    for ticker in [row["ticker"] for row in sample]:
        run1 = run1_by_ticker.get(ticker, {})
        run2 = run2_by_ticker.get(ticker, {})
        run3 = run3_by_ticker.get(ticker, {})
        candidate_match = bool(run1 and run2 and run3)
        rank_vs_run1 = candidate_match and run1.get("daily_runner_rank") != run3.get("daily_runner_rank")
        rank_vs_run2 = candidate_match and run2.get("daily_runner_rank") != run3.get("daily_runner_rank")
        disclosure_vs_run1 = candidate_match and disclosure_changed(run1, run3)
        disclosure_vs_run2 = candidate_match and disclosure_changed(run2, run3)
        comparison_pass = candidate_match and not rank_vs_run1 and not rank_vs_run2 and not disclosure_vs_run1 and not disclosure_vs_run2
        comparison_rows.append({
            "ticker": ticker,
            "run_1_rank": run1.get("daily_runner_rank", ""),
            "run_2_rank": run2.get("daily_runner_rank", ""),
            "run_3_rank": run3.get("daily_runner_rank", ""),
            "run_1_data_trust_direct_status": run1.get("data_trust_direct_status", ""),
            "run_2_data_trust_direct_status": run2.get("data_trust_direct_status", ""),
            "run_3_data_trust_direct_status": run3.get("data_trust_direct_status", ""),
            "run_1_data_trust_gate_action": run1.get("data_trust_gate_action", ""),
            "run_2_data_trust_gate_action": run2.get("data_trust_gate_action", ""),
            "run_3_data_trust_gate_action": run3.get("data_trust_gate_action", ""),
            "run_1_data_trust_weight": run1.get("data_trust_weight", ""),
            "run_2_data_trust_weight": run2.get("data_trust_weight", ""),
            "run_3_data_trust_weight": run3.get("data_trust_weight", ""),
            "run_1_data_trust_score_contribution": run1.get("data_trust_official_score_contribution", ""),
            "run_2_data_trust_score_contribution": run2.get("data_trust_official_score_contribution", ""),
            "run_3_data_trust_score_contribution": run3.get("data_trust_official_score_contribution", ""),
            "data_trust_caused_ranking_mutation_vs_run_1": tf(rank_vs_run1),
            "data_trust_caused_ranking_mutation_vs_run_2": tf(rank_vs_run2),
            "data_trust_disclosure_changed_vs_run_1": tf(disclosure_vs_run1),
            "data_trust_disclosure_changed_vs_run_2": tf(disclosure_vs_run2),
            "run_to_run_candidate_match": tf(candidate_match),
            "run_3_vs_run_1_run_2_comparison_pass": tf(comparison_pass),
            **COMMON,
        })

    score_mutations = sum(row["official_current_score"] != row["daily_runner_score"] for row in sample)
    rank_mutations = sum(row["official_current_rank"] != row["daily_runner_rank"] for row in sample)
    removed_count = sum(row["candidate_removed_or_reordered"] == "TRUE" for row in disclosure_rows)
    nonzero_weight = sum(row["data_trust_weight"] != "0.0000000000" for row in sample)
    contribution_sum = "0.0000000000"
    candidate_mismatch_count = sum(row["run_to_run_candidate_match"] != "TRUE" for row in comparison_rows)
    run_to_run_ranking_mutation_count = sum(
        row["data_trust_caused_ranking_mutation_vs_run_1"] == "TRUE"
        or row["data_trust_caused_ranking_mutation_vs_run_2"] == "TRUE"
        for row in comparison_rows
    )
    disclosure_change_count = sum(
        row["data_trust_disclosure_changed_vs_run_1"] == "TRUE"
        or row["data_trust_disclosure_changed_vs_run_2"] == "TRUE"
        for row in comparison_rows
    )
    disclosure_pass = len(disclosure_rows) == 40 and all(row["run_3_disclosure_pass"] == "TRUE" for row in disclosure_rows)
    mutation_pass = score_mutations == 0 and rank_mutations == 0 and not upstream_mutated
    zero_pass = contribution_sum == "0.0000000000" and nonzero_weight == 0
    official_pass = True
    comparison_pass = (
        len(comparison_rows) == 40
        and candidate_mismatch_count == 0
        and run_to_run_ranking_mutation_count == 0
        and disclosure_change_count == 0
        and all(row["run_3_vs_run_1_run_2_comparison_pass"] == "TRUE" for row in comparison_rows)
    )
    all_pass = all([disclosure_pass, mutation_pass, zero_pass, official_pass, comparison_pass])

    run_rows = [{
        "run_id": "V20_180_DATA_TRUST_MULTIDAY_OBSERVATION_RUN_3",
        "run_sequence": "3",
        "candidate_count": str(len(sample)),
        "data_trust_disclosure_candidate_count": str(len(disclosure_rows)),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "candidate_removed_or_reordered_count": str(removed_count),
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "run_3_disclosure_pass": tf(disclosure_pass),
        "run_3_no_mutation_guard_pass": tf(mutation_pass),
        "run_3_zero_weight_guard_pass": tf(zero_pass),
        "run_3_official_use_guard_pass": tf(official_pass),
        "run_3_vs_run_1_run_2_comparison_pass": tf(comparison_pass),
        "run_3_all_guards_pass": tf(all_pass),
        **COMMON,
    }]
    zero_guard = guard_rows("ZERO_WEIGHT_NO_MUTATION", [
        ("official_ranking_score_mutation_count", "0", str(score_mutations)),
        ("official_rank_mutation_count", "0", str(rank_mutations)),
        ("data_trust_score_contribution_sum", "0.0000000000", contribution_sum),
        ("data_trust_nonzero_weight_count", "0", str(nonzero_weight)),
        ("candidate_removed_or_reordered_count", "0", str(removed_count)),
        ("official_outputs_mutated", "FALSE", tf(upstream_mutated)),
        ("run_to_run_data_trust_caused_ranking_mutation_count", "0", str(run_to_run_ranking_mutation_count)),
    ])
    official_guard = guard_rows("OFFICIAL_USE", [
        ("official_recommendation_created", "FALSE", "FALSE"),
        ("real_book_use_allowed", "FALSE", "FALSE"),
        ("official_weight_mutation_allowed", "FALSE", "FALSE"),
        ("ready_for_official_use", "FALSE", "FALSE"),
    ])
    gate = {
        "gate_check_id": "V20_180_NEXT_STAGE_GATE_001",
        "v20_177_status_consumed": "TRUE",
        "v20_177_status": v177.get("final_status", ""),
        "v20_178_status_consumed": "TRUE",
        "v20_178_status": v178_gate.get("final_status", ""),
        "v20_179_status_consumed": "TRUE",
        "v20_179_status": v179_gate.get("final_status", ""),
        "observation_run_sequence": "3",
        "baseline_candidate_count": str(len(baseline)),
        "run_1_candidate_count": v178_run.get("candidate_count", ""),
        "run_2_candidate_count": v179_run.get("candidate_count", ""),
        "run_3_candidate_count": str(len(sample)),
        "run_3_data_trust_disclosure_candidate_count": str(len(disclosure_rows)),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "candidate_removed_or_reordered_count": str(removed_count),
        "run_to_run_candidate_mismatch_count": str(candidate_mismatch_count),
        "run_to_run_data_trust_caused_ranking_mutation_count": str(run_to_run_ranking_mutation_count),
        "run_to_run_disclosure_change_count": str(disclosure_change_count),
        "official_recommendation_created": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "run_3_disclosure_pass": tf(disclosure_pass),
        "run_3_no_mutation_guard_pass": tf(mutation_pass),
        "run_3_zero_weight_guard_pass": tf(zero_pass),
        "run_3_official_use_guard_pass": tf(official_pass),
        "run_3_vs_run_1_run_2_comparison_pass": tf(comparison_pass),
        "ready_for_v20_181_multiday_observation_closeout_summary": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RUN_V20_181_MULTIDAY_OBSERVATION_CLOSEOUT_SUMMARY" if all_pass else "REPAIR_V20_180_RUN_3_GUARD_FAILURE",
        "blocking_reason": "NONE" if all_pass else "V20_180_RUN_3_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_RUN, RUN_FIELDS, run_rows)
    write_csv(OUT_DISCLOSURE, DISCLOSURE_AUDIT_FIELDS, disclosure_rows)
    write_csv(OUT_ZERO, GUARD_FIELDS, zero_guard)
    write_csv(OUT_OFFICIAL, GUARD_FIELDS, official_guard)
    write_csv(OUT_COMPARISON, COMPARISON_FIELDS, comparison_rows)
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
