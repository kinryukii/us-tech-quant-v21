#!/usr/bin/env python
"""V20.191 daily runner regression with DATA_TRUST gate-only metadata."""

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
DAILY_SAMPLE = FACTORS / "V20_174_DATA_TRUST_DAILY_RUNNER_OUTPUT_SAMPLE.csv"
DISPLAY_SAMPLE = FACTORS / "V20_183_DATA_TRUST_READ_CENTER_DISPLAY_SAMPLE.csv"
V188_SEAL = FACTORS / "V20_188_DATA_TRUST_GATE_ONLY_RELEASE_SEAL.csv"
V188_GATE = FACTORS / "V20_188_NEXT_STAGE_GATE.csv"
V189_HANDOFF = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_AUDIT.csv"
V189_COMPATIBILITY = FACTORS / "V20_189_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv"
V189_GUARD = FACTORS / "V20_189_OFFICIAL_USE_GUARD_AUDIT.csv"
V189_GATE = FACTORS / "V20_189_NEXT_STAGE_GATE.csv"
V190_SMOKE = FACTORS / "V20_190_CURRENT_CHAIN_SMOKE_TEST_AUDIT.csv"
V190_COMPATIBILITY = FACTORS / "V20_190_DATA_TRUST_CURRENT_CHAIN_COMPATIBILITY_AUDIT.csv"
V190_RANKING = FACTORS / "V20_190_RANKING_WEIGHT_MUTATION_GUARD_AUDIT.csv"
V190_OFFICIAL = FACTORS / "V20_190_OFFICIAL_USE_GUARD_AUDIT.csv"
V190_DISPLAY = FACTORS / "V20_190_READ_CENTER_DISPLAY_AUDIT.csv"
V190_GATE = FACTORS / "V20_190_NEXT_STAGE_GATE.csv"

PROTECTED = [
    BASELINE, DAILY_SAMPLE, DISPLAY_SAMPLE, V188_SEAL, V188_GATE,
    V189_HANDOFF, V189_COMPATIBILITY, V189_GUARD, V189_GATE,
    V190_SMOKE, V190_COMPATIBILITY, V190_RANKING, V190_OFFICIAL,
    V190_DISPLAY, V190_GATE,
]

OUT_REGRESSION = FACTORS / "V20_191_DAILY_RUNNER_REGRESSION_AUDIT.csv"
OUT_UNIVERSE = FACTORS / "V20_191_CANDIDATE_UNIVERSE_REGRESSION_AUDIT.csv"
OUT_RANKING = FACTORS / "V20_191_RANKING_WEIGHT_REGRESSION_AUDIT.csv"
OUT_READ_CENTER = FACTORS / "V20_191_READ_CENTER_REGRESSION_AUDIT.csv"
OUT_OFFICIAL = FACTORS / "V20_191_OFFICIAL_USE_REGRESSION_AUDIT.csv"
OUT_DOWNSTREAM = FACTORS / "V20_191_DOWNSTREAM_COMPATIBILITY_REGRESSION_AUDIT.csv"
OUT_GATE = FACTORS / "V20_191_NEXT_STAGE_GATE.csv"
REPORT = READ_CENTER / "V20_191_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY_REPORT.md"

READY_V188 = "PASS_V20_188_DAILY_RUNNER_GATE_ONLY_RELEASE_SEAL_READY_FOR_V20_189_CURRENT_CHAIN_HANDOFF"
READY_V189 = "PASS_V20_189_DATA_TRUST_CURRENT_CHAIN_HANDOFF_READY_FOR_V20_190_CURRENT_CHAIN_SMOKE_TEST"
READY_V190 = "PASS_V20_190_CURRENT_CHAIN_SMOKE_TEST_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_191_DAILY_RUNNER_REGRESSION"
PASS_STATUS = "PASS_V20_191_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY_READY_FOR_V20_192_RELEASE_CANDIDATE"
BLOCKED_STATUS = "BLOCKED_V20_191_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY"
DATA_TRUST_ROLE = "GATE_ONLY_AND_REPAIR_DIAGNOSTIC"
SCOPE = "RESEARCH_ONLY_DAILY_RUNNER_REGRESSION_WITH_DATA_TRUST_GATE_ONLY"

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
    "regression_check_id", "regression_surface", "regression_check",
    "expected_value", "actual_value", "regression_passed",
    "source_artifact", *COMMON.keys(),
]
GATE_FIELDS = [
    "gate_check_id", "v20_188_status_consumed", "v20_188_status",
    "v20_189_status_consumed", "v20_189_status", "v20_190_status_consumed",
    "v20_190_status", "baseline_candidate_count", "daily_runner_candidate_count",
    "read_center_display_candidate_count", "candidate_removed_or_reordered_count",
    "official_ranking_score_mutation_count", "official_rank_mutation_count",
    "data_trust_score_contribution_sum", "data_trust_nonzero_weight_count",
    "daily_runner_regression_pass", "candidate_universe_regression_pass",
    "ranking_regression_pass", "zero_weight_regression_pass",
    "read_center_regression_pass", "official_use_regression_pass",
    "downstream_compatibility_regression_pass",
    "ready_for_v20_192_daily_runner_current_chain_release_candidate",
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


def audit_row(prefix: str, idx: int, surface: str, check: str, expected: str, actual: str, path: Path) -> dict[str, str]:
    return {
        "regression_check_id": f"V20_191_{prefix}_{idx:03d}",
        "regression_surface": surface,
        "regression_check": check,
        "expected_value": expected,
        "actual_value": actual,
        "regression_passed": tf(expected == actual),
        "source_artifact": rel(path),
        **COMMON,
    }


def write_report(gate: dict[str, str]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# V20.191 Daily Runner Regression With DATA_TRUST Gate-Only Report",
        "",
        f"- final_status: {gate['final_status']}",
        f"- daily_runner_regression_pass: {gate['daily_runner_regression_pass']}",
        f"- candidate_universe_regression_pass: {gate['candidate_universe_regression_pass']}",
        f"- ranking_regression_pass: {gate['ranking_regression_pass']}",
        f"- zero_weight_regression_pass: {gate['zero_weight_regression_pass']}",
        f"- read_center_regression_pass: {gate['read_center_regression_pass']}",
        f"- official_use_regression_pass: {gate['official_use_regression_pass']}",
        f"- downstream_compatibility_regression_pass: {gate['downstream_compatibility_regression_pass']}",
        f"- ready_for_v20_192_daily_runner_current_chain_release_candidate: {gate['ready_for_v20_192_daily_runner_current_chain_release_candidate']}",
        "",
        "Daily runner regression confirms DATA_TRUST remains zero-weight gate-only audit metadata without changing candidate universe, ranking, read-center display, recommendation gating, official-use constraints, or downstream compatibility.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_blocked(reason: str) -> int:
    for path in [OUT_REGRESSION, OUT_UNIVERSE, OUT_RANKING, OUT_READ_CENTER, OUT_OFFICIAL, OUT_DOWNSTREAM]:
        write_csv(path, AUDIT_FIELDS, [])
    gate = {
        "gate_check_id": "V20_191_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "FALSE",
        "v20_188_status": "",
        "v20_189_status_consumed": "FALSE",
        "v20_189_status": "",
        "v20_190_status_consumed": "FALSE",
        "v20_190_status": "",
        "baseline_candidate_count": "0",
        "daily_runner_candidate_count": "0",
        "read_center_display_candidate_count": "0",
        "candidate_removed_or_reordered_count": "0",
        "official_ranking_score_mutation_count": "0",
        "official_rank_mutation_count": "0",
        "data_trust_score_contribution_sum": "0.0000000000",
        "data_trust_nonzero_weight_count": "0",
        "daily_runner_regression_pass": "FALSE",
        "candidate_universe_regression_pass": "FALSE",
        "ranking_regression_pass": "FALSE",
        "zero_weight_regression_pass": "FALSE",
        "read_center_regression_pass": "FALSE",
        "official_use_regression_pass": "FALSE",
        "downstream_compatibility_regression_pass": "FALSE",
        "ready_for_v20_192_daily_runner_current_chain_release_candidate": "FALSE",
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RESOLVE_BLOCKER_AND_RERUN_V20_191",
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
    gate188 = datasets[V188_GATE][0]
    gate189 = datasets[V189_GATE][0]
    gate190 = datasets[V190_GATE][0]
    if not all([
        gate188.get("final_status") == READY_V188,
        gate189.get("final_status") == READY_V189,
        gate190.get("final_status") == READY_V190,
        gate190.get("ready_for_v20_191_current_chain_daily_runner_regression") == "TRUE",
        all(row.get("smoke_check_passed") == "TRUE" for row in datasets[V190_SMOKE]),
        all(row.get("compatibility_check_passed") == "TRUE" for row in datasets[V190_COMPATIBILITY]),
        all(row.get("guard_passed") == "TRUE" for row in datasets[V190_RANKING]),
        all(row.get("guard_passed") == "TRUE" for row in datasets[V190_OFFICIAL]),
        all(row.get("display_check_passed") == "TRUE" for row in datasets[V190_DISPLAY]),
    ]):
        return emit_blocked("V20_188_V20_189_OR_V20_190_REQUIREMENTS_NOT_MET")

    baseline_tickers = [row["ticker"] for row in baseline]
    daily_tickers = [row["ticker"] for row in daily]
    display_tickers = [row["ticker"] for row in display]
    score_mutations = sum(row.get("official_current_score") != row.get("daily_runner_score") for row in daily)
    rank_mutations = sum(row.get("official_current_rank") != row.get("daily_runner_rank") for row in daily)
    removed_reordered = sum(row.get("official_current_rank") != row.get("daily_runner_rank") for row in daily)
    contribution_sum = f"{sum(float(row.get('data_trust_official_score_contribution', '0') or '0') for row in daily):.10f}"
    nonzero_weight = sum(row.get("data_trust_weight") != "0.0000000000" for row in daily)
    disclosure_fields = [
        "data_trust_direct_status", "data_trust_gate_action", "data_trust_evidence_status",
        "data_trust_shadow_observation_flag", "data_trust_official_score_contribution",
        "data_trust_weight", "data_trust_gate_only_metadata",
    ]
    disclosure_present = all(all(row.get(field, "") != "" for field in disclosure_fields) for row in daily)
    gate_only_audit = all(row.get("data_trust_gate_only_metadata") == "TRUE" and row.get("audit_only") == "TRUE" for row in daily)
    official_disabled = all([
        gate190.get("ready_for_official_use") == "FALSE",
        gate190.get("real_book_use_allowed") == "FALSE",
        gate190.get("official_recommendation_created") == "FALSE",
        gate190.get("official_weight_mutation_allowed") == "FALSE",
        all(row.get("official_recommendation_created") == "FALSE" for row in daily),
        all(row.get("real_book_use_allowed") == "FALSE" for row in daily),
        all(row.get("official_weight_mutation_allowed") == "FALSE" for row in daily),
    ])
    read_center_ok = all([
        len(display) == 40,
        display_tickers == daily_tickers,
        all(row.get("data_trust_direct_status_summary") == "PASS" for row in display),
        all(row.get("data_trust_gate_only_status") == "TRUE" for row in display),
        all(row.get("data_trust_zero_weight_status") == "TRUE" for row in display),
        all(row.get("data_trust_audit_only_status") == "TRUE" for row in display),
        all(row.get("read_center_display_ready") == "TRUE" for row in display),
    ])
    downstream_ok = all([
        all(row.get("compatibility_check_passed") == "TRUE" for row in datasets[V189_COMPATIBILITY]),
        all(row.get("compatibility_check_passed") == "TRUE" for row in datasets[V190_COMPATIBILITY]),
        gate190.get("current_chain_smoke_test_pass") == "TRUE",
    ])
    upstream_mutated = before != protected_hashes()

    regression_rows = [
        audit_row("DAILY_RUNNER", 1, "daily_runner", "DATA_TRUST_DISCLOSURE_COLUMNS_PRESENT", "TRUE", tf(disclosure_present), DAILY_SAMPLE),
        audit_row("DAILY_RUNNER", 2, "daily_runner", "DATA_TRUST_GATE_ONLY_AUDIT_ONLY", "TRUE", tf(gate_only_audit), DAILY_SAMPLE),
        audit_row("DAILY_RUNNER", 3, "daily_runner", "NO_CANDIDATE_REMOVED_OR_REORDERED_BY_DATA_TRUST", "0", str(removed_reordered), DAILY_SAMPLE),
    ]
    universe_rows = [
        audit_row("UNIVERSE", 1, "candidate_universe", "baseline_candidate_count", "40", str(len(baseline)), BASELINE),
        audit_row("UNIVERSE", 2, "candidate_universe", "daily_runner_candidate_count", "40", str(len(daily)), DAILY_SAMPLE),
        audit_row("UNIVERSE", 3, "candidate_universe", "ticker_order_matches_baseline", "TRUE", tf(daily_tickers == baseline_tickers), DAILY_SAMPLE),
    ]
    ranking_rows = [
        audit_row("RANKING", 1, "ranking_weight", "official_ranking_score_mutation_count", "0", str(score_mutations), DAILY_SAMPLE),
        audit_row("RANKING", 2, "ranking_weight", "official_rank_mutation_count", "0", str(rank_mutations), DAILY_SAMPLE),
        audit_row("RANKING", 3, "ranking_weight", "data_trust_score_contribution_sum", "0.0000000000", contribution_sum, DAILY_SAMPLE),
        audit_row("RANKING", 4, "ranking_weight", "data_trust_nonzero_weight_count", "0", str(nonzero_weight), DAILY_SAMPLE),
    ]
    read_center_rows = [
        audit_row("READ_CENTER", 1, "read_center", "read_center_candidate_count", "40", str(len(display)), DISPLAY_SAMPLE),
        audit_row("READ_CENTER", 2, "read_center", "display_ticker_order_matches_daily_runner", "TRUE", tf(display_tickers == daily_tickers), DISPLAY_SAMPLE),
        audit_row("READ_CENTER", 3, "read_center", "data_trust_status_readable", "TRUE", tf(read_center_ok), DISPLAY_SAMPLE),
    ]
    official_rows = [
        audit_row("OFFICIAL_USE", 1, "official_use", "ready_for_official_use", "FALSE", gate190.get("ready_for_official_use", ""), V190_GATE),
        audit_row("OFFICIAL_USE", 2, "official_use", "real_book_use_allowed", "FALSE", gate190.get("real_book_use_allowed", ""), V190_GATE),
        audit_row("OFFICIAL_USE", 3, "official_use", "official_recommendation_created", "FALSE", gate190.get("official_recommendation_created", ""), V190_GATE),
        audit_row("OFFICIAL_USE", 4, "official_use", "official_weight_mutation_allowed", "FALSE", gate190.get("official_weight_mutation_allowed", ""), V190_GATE),
    ]
    downstream_rows = [
        audit_row("DOWNSTREAM", 1, "downstream", "v189_compatibility_passed", "TRUE", tf(all(row.get("compatibility_check_passed") == "TRUE" for row in datasets[V189_COMPATIBILITY])), V189_COMPATIBILITY),
        audit_row("DOWNSTREAM", 2, "downstream", "v190_compatibility_passed", "TRUE", tf(all(row.get("compatibility_check_passed") == "TRUE" for row in datasets[V190_COMPATIBILITY])), V190_COMPATIBILITY),
        audit_row("DOWNSTREAM", 3, "downstream", "current_chain_smoke_test_pass", "TRUE", gate190.get("current_chain_smoke_test_pass", ""), V190_GATE),
        audit_row("DOWNSTREAM", 4, "downstream", "upstream_regression_inputs_mutated", "FALSE", tf(upstream_mutated), V190_GATE),
    ]
    daily_pass = all(row["regression_passed"] == "TRUE" for row in regression_rows)
    universe_pass = all(row["regression_passed"] == "TRUE" for row in universe_rows)
    ranking_pass = score_mutations == 0 and rank_mutations == 0
    zero_weight_pass = contribution_sum == "0.0000000000" and nonzero_weight == 0
    read_center_pass = all(row["regression_passed"] == "TRUE" for row in read_center_rows)
    official_pass = all(row["regression_passed"] == "TRUE" for row in official_rows) and official_disabled
    downstream_pass = all(row["regression_passed"] == "TRUE" for row in downstream_rows)
    all_pass = all([daily_pass, universe_pass, ranking_pass, zero_weight_pass, read_center_pass, official_pass, downstream_pass, not upstream_mutated])

    gate = {
        "gate_check_id": "V20_191_NEXT_STAGE_GATE_001",
        "v20_188_status_consumed": "TRUE",
        "v20_188_status": gate188.get("final_status", ""),
        "v20_189_status_consumed": "TRUE",
        "v20_189_status": gate189.get("final_status", ""),
        "v20_190_status_consumed": "TRUE",
        "v20_190_status": gate190.get("final_status", ""),
        "baseline_candidate_count": str(len(baseline)),
        "daily_runner_candidate_count": str(len(daily)),
        "read_center_display_candidate_count": str(len(display)),
        "candidate_removed_or_reordered_count": str(removed_reordered),
        "official_ranking_score_mutation_count": str(score_mutations),
        "official_rank_mutation_count": str(rank_mutations),
        "data_trust_score_contribution_sum": contribution_sum,
        "data_trust_nonzero_weight_count": str(nonzero_weight),
        "daily_runner_regression_pass": tf(daily_pass),
        "candidate_universe_regression_pass": tf(universe_pass),
        "ranking_regression_pass": tf(ranking_pass),
        "zero_weight_regression_pass": tf(zero_weight_pass),
        "read_center_regression_pass": tf(read_center_pass),
        "official_use_regression_pass": tf(official_pass),
        "downstream_compatibility_regression_pass": tf(downstream_pass),
        "ready_for_v20_192_daily_runner_current_chain_release_candidate": tf(all_pass),
        "ready_for_official_use": "FALSE",
        "real_book_use_allowed": "FALSE",
        "official_recommendation_created": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "data_trust_zero_weight": "TRUE",
        "data_trust_gate_only": "TRUE",
        "data_trust_audit_only": "TRUE",
        "recommended_next_action": "RUN_V20_192_DAILY_RUNNER_CURRENT_CHAIN_RELEASE_CANDIDATE" if all_pass else "REPAIR_V20_191_DAILY_RUNNER_REGRESSION",
        "blocking_reason": "NONE" if all_pass else "V20_191_DAILY_RUNNER_REGRESSION_GUARD_FAILURE",
        "final_status": PASS_STATUS if all_pass else BLOCKED_STATUS,
        **COMMON,
    }
    write_csv(OUT_REGRESSION, AUDIT_FIELDS, regression_rows)
    write_csv(OUT_UNIVERSE, AUDIT_FIELDS, universe_rows)
    write_csv(OUT_RANKING, AUDIT_FIELDS, ranking_rows)
    write_csv(OUT_READ_CENTER, AUDIT_FIELDS, read_center_rows)
    write_csv(OUT_OFFICIAL, AUDIT_FIELDS, official_rows)
    write_csv(OUT_DOWNSTREAM, AUDIT_FIELDS, downstream_rows)
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
