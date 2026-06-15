#!/usr/bin/env python
"""Tests for V20.192 DATA_TRUST zero-weight random as-of backtest."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_192_data_trust_zero_weight_random_asof_backtest.py"
BACKTEST = ROOT / "outputs" / "v20" / "backtest"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
FACTORS = ROOT / "outputs" / "v20" / "factors"

OUTPUTS = [
    BACKTEST / "V20_192_ZERO_WEIGHT_RANDOM_ASOF_SAMPLE_DATES.csv",
    BACKTEST / "V20_192_ZERO_WEIGHT_POLICY_USED.csv",
    BACKTEST / "V20_192_RANDOM_ASOF_TOPN_SELECTIONS.csv",
    BACKTEST / "V20_192_RANDOM_ASOF_FORWARD_RETURNS.csv",
    BACKTEST / "V20_192_RANDOM_ASOF_BENCHMARK_RETURNS.csv",
    BACKTEST / "V20_192_TOPN_BENCHMARK_COMPARISON.csv",
    BACKTEST / "V20_192_FORWARD_WINDOW_EFFECTIVENESS_SUMMARY.csv",
    BACKTEST / "V20_192_FACTOR_FAMILY_CONTRIBUTION_AUDIT.csv",
    BACKTEST / "V20_192_DATA_TRUST_ZERO_WEIGHT_BACKTEST_GUARD_AUDIT.csv",
    BACKTEST / "V20_192_EFFECTIVENESS_SUMMARY.csv",
    BACKTEST / "V20_192_NEXT_STAGE_GATE.csv",
]
PROTECTED = [
    CONSOLIDATION / "V20_104_RANDOM_ASOF_FORWARD_OUTCOME_MATRIX.csv",
    CONSOLIDATION / "V20_104_RANDOM_ASOF_BENCHMARK_COMPARISON.csv",
    CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv",
    CONSOLIDATION / "V20_108_R10_COMPLETE_FACTOR_FAMILY_SCORE_TABLE.csv",
    FACTORS / "V20_166_DATA_TRUST_GATE_ONLY_WEIGHT_SIMULATION.csv",
]
EXPECTED_STATUS = "BLOCKED_MISSING_RECOMPUTABLE_FACTOR_FIELDS"
SAFETY_FALSE_FIELDS = [
    "official_ranking_mutated", "official_recommendation_created",
    "trade_action_created", "broker_execution_supported", "real_book_action_created",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[Path, str]:
    return {path: digest(path) for path in PROTECTED if path.exists()}


def assert_safety(rows: list[dict[str, str]]) -> None:
    for row in rows:
        assert row.get("research_only") == "TRUE"
        assert row.get("data_trust_scoring_weight") == "0.0000000000"
        assert row.get("data_trust_score_contribution_sum") == "0.0000000000"
        for field in SAFETY_FALSE_FIELDS:
            if field in row:
                assert row[field] == "FALSE", f"{field} is not FALSE"
        if "official_ranking_score_mutation_count" in row:
            assert row["official_ranking_score_mutation_count"] == "0"
        if "official_rank_mutation_count" in row:
            assert row["official_rank_mutation_count"] == "0"


def test_data_trust_zero_weight_random_asof_backtest() -> None:
    before = protected_hashes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = protected_hashes()
    assert before == after, "protected source artifacts were mutated"
    stdout = result.stdout
    for expected in [
        EXPECTED_STATUS,
        "SCORING_FIELDS_RECOMPUTABLE=FALSE",
        "GUARD_AUDIT_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "READY_FOR_NEXT_STAGE=FALSE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "DATA_TRUST_SCORING_WEIGHT=0.0000000000",
        "DATA_TRUST_SCORE_CONTRIBUTION_SUM=0.0000000000",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    samples = read_csv(OUTPUTS[0])
    policy = read_csv(OUTPUTS[1])
    selections = read_csv(OUTPUTS[2])
    forward = read_csv(OUTPUTS[3])
    benchmark = read_csv(OUTPUTS[4])
    comparison = read_csv(OUTPUTS[5])
    windows = read_csv(OUTPUTS[6])
    contribution = read_csv(OUTPUTS[7])
    guards = read_csv(OUTPUTS[8])
    effectiveness = read_csv(OUTPUTS[9])[0]
    gate = read_csv(OUTPUTS[10])[0]

    assert len(policy) == 6
    weights = {row["factor_family"]: row["scoring_weight"] for row in policy}
    assert weights["FUNDAMENTAL"] == "0.2222222222"
    assert weights["TECHNICAL"] == "0.2777777778"
    assert weights["STRATEGY"] == "0.2222222222"
    assert weights["RISK"] == "0.1666666667"
    assert weights["MARKET_REGIME"] == "0.1111111111"
    assert weights["DATA_TRUST"] == "0.0000000000"
    assert all(row["used_in_zero_weight_score"] == "FALSE" for row in policy)
    assert len(samples) <= 100
    assert all(row["scoring_fields_recomputable"] == "FALSE" for row in samples)
    assert all(row["selection_status"] == EXPECTED_STATUS for row in selections)
    assert all(row["return_status"] == EXPECTED_STATUS for row in forward)
    assert all(row["benchmark_status"] in {"INSUFFICIENT_BENCHMARK_DATA", "AVAILABLE_NOT_USED_SELECTION_BLOCKED"} for row in benchmark)
    assert all(row["benchmark_comparison_status"] == "INSUFFICIENT_SELECTION_DATA" for row in comparison)
    assert all(row["insufficient_data_reason"] for row in windows)
    assert any(row["factor_family"] == "TECHNICAL" and row["field_available"] == "FALSE" for row in contribution)
    assert any(row["factor_family"] == "FUNDAMENTAL" and row["field_available"] == "FALSE" for row in contribution)
    assert all(row["guard_passed"] == "TRUE" for row in guards)
    assert effectiveness["effectiveness_status"] == "BLOCKED"
    assert effectiveness["guard_audit_pass"] == "TRUE"
    assert gate["final_status"] == EXPECTED_STATUS
    assert gate["scoring_fields_recomputable"] == "FALSE"
    assert gate["guard_audit_pass"] == "TRUE"
    assert gate["ready_for_next_stage"] == "FALSE"
    assert gate["blocking_reason"] == "MISSING_RECOMPUTABLE_HISTORICAL_FACTOR_FIELDS_FOR_ZERO_WEIGHT_FORMULA"
    assert_safety([gate, effectiveness, *policy, *guards, *contribution])


if __name__ == "__main__":
    test_data_trust_zero_weight_random_asof_backtest()
    print("PASS test_v20_192_data_trust_zero_weight_random_asof_backtest")
