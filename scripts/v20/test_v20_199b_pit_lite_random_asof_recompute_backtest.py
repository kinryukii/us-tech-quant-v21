#!/usr/bin/env python
"""Tests for V20.199B PIT-lite random as-of recompute backtest."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199b_pit_lite_random_asof_recompute_backtest.py"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
OUTPUTS = [
    OUT_DIR / "V20_199B_RANDOM_ASOF_DATE_SELECTION.csv",
    OUT_DIR / "V20_199B_PIT_LITE_INPUT_DISCOVERY.csv",
    OUT_DIR / "V20_199B_RECOMPUTABLE_FACTOR_POLICY.csv",
    OUT_DIR / "V20_199B_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
    OUT_DIR / "V20_199B_RANDOM_ASOF_TOPN_SELECTIONS.csv",
    OUT_DIR / "V20_199B_FORWARD_RETURNS.csv",
    OUT_DIR / "V20_199B_BENCHMARK_RETURNS.csv",
    OUT_DIR / "V20_199B_TOPN_BENCHMARK_COMPARISON.csv",
    OUT_DIR / "V20_199B_WEIGHT_SCENARIO_COMPARISON.csv",
    OUT_DIR / "V20_199B_DYNAMIC_WEIGHT_WALK_FORWARD_AUDIT.csv",
    OUT_DIR / "V20_199B_NO_LOOKAHEAD_GUARD_AUDIT.csv",
    OUT_DIR / "V20_199B_EFFECTIVENESS_SUMMARY.csv",
    OUT_DIR / "V20_199B_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_199B_READ_CENTER_REPORT.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_pit_lite_random_asof_recompute_backtest() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "NO_LOOKAHEAD_GUARD_PASS=",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "OFFICIAL_RECOMMENDATION_CREATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
        "BROKER_EXECUTION_SUPPORTED=FALSE",
        "NO_FABRICATED_SCORES=TRUE",
        "NO_FABRICATED_RETURNS=TRUE",
        "NO_FABRICATED_BENCHMARK_ROWS=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    discovery = read_csv(OUTPUTS[1])
    policy = read_csv(OUTPUTS[2])
    snapshots = read_csv(OUTPUTS[3])
    forward = read_csv(OUTPUTS[5])
    benchmarks = read_csv(OUTPUTS[6])
    comparison = read_csv(OUTPUTS[7])
    dynamic = read_csv(OUTPUTS[9])
    guard = read_csv(OUTPUTS[10])
    effect = read_csv(OUTPUTS[11])[0]
    gate = read_csv(OUTPUTS[12])[0]

    assert len(discovery) > 0
    assert {row["factor_family"] for row in policy} >= {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
    assert all(row["scoring_weight"] == "0.0000000000" for row in policy if row["factor_family"] in {"FUNDAMENTAL", "DATA_TRUST"})
    assert all(row["dynamic_weight_status"] == "EVALUATED_SHADOW_ONLY" for row in dynamic) if dynamic else True
    assert all(row["dynamic_weight_activated"] == "FALSE" for row in dynamic) if dynamic else True
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert gate["no_lookahead_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["research_only"] == "TRUE"
    assert gate["official_ranking_mutated"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS", "BLOCKED"))
    if snapshots:
        assert all(row["max_factor_input_date"] <= row["as_of_date"] for row in snapshots)
    if forward:
        assert all(row["forward_return"] == "" for row in forward if row["return_status"] != "PASS")
        assert all(row["min_forward_return_date"] > row["as_of_date"] for row in forward if row["return_status"] == "PASS")
    if benchmarks:
        assert all(row["benchmark_forward_return"] == "" for row in benchmarks if row["benchmark_status"] != "PASS")
    if comparison:
        required = {
            "candidate_count",
            "valid_return_count",
            "average_forward_return",
            "median_forward_return",
            "win_rate",
            "average_excess_return_vs_benchmark",
            "median_excess_return_vs_benchmark",
            "positive_excess_return_rate_vs_benchmark",
            "missing_return_count",
            "insufficient_factor_data_count",
            "universe_pit_status",
            "no_lookahead_guard_status",
        }
        assert required.issubset(comparison[0].keys())
    assert effect["no_lookahead_guard_pass"] == "TRUE"
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "Current factor snapshots" in report


if __name__ == "__main__":
    test_pit_lite_random_asof_recompute_backtest()
    print("PASS test_v20_199b_pit_lite_random_asof_recompute_backtest")
