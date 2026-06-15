#!/usr/bin/env python
"""Tests for V20.199B-R1 canonical-price PIT-lite random as-of backtest."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199b_r1_pit_lite_random_asof_recompute_backtest_with_canonical_price_history.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_199b_r1_pit_lite_random_asof_recompute_backtest_with_canonical_price_history.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
OUTPUTS = [
    OUT_DIR / "V20_199B_R1_CANONICAL_PRICE_INPUT_AUDIT.csv",
    OUT_DIR / "V20_199B_R1_RANDOM_ASOF_DATE_SELECTION.csv",
    OUT_DIR / "V20_199B_R1_RECOMPUTABLE_FACTOR_POLICY.csv",
    OUT_DIR / "V20_199B_R1_RANDOM_ASOF_RECOMPUTED_FACTOR_SNAPSHOT.csv",
    OUT_DIR / "V20_199B_R1_RANDOM_ASOF_TOPN_SELECTIONS.csv",
    OUT_DIR / "V20_199B_R1_FORWARD_RETURNS.csv",
    OUT_DIR / "V20_199B_R1_BENCHMARK_RETURNS.csv",
    OUT_DIR / "V20_199B_R1_TOPN_BENCHMARK_COMPARISON.csv",
    OUT_DIR / "V20_199B_R1_WEIGHT_SCENARIO_COMPARISON.csv",
    OUT_DIR / "V20_199B_R1_DYNAMIC_WEIGHT_WALK_FORWARD_AUDIT.csv",
    OUT_DIR / "V20_199B_R1_NO_LOOKAHEAD_GUARD_AUDIT.csv",
    OUT_DIR / "V20_199B_R1_EFFECTIVENESS_SUMMARY.csv",
    OUT_DIR / "V20_199B_R1_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_199B_R1_READ_CENTER_REPORT.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_ranking_score_mutation_count"] == "0"
    assert row["official_rank_mutation_count"] == "0"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["no_fabricated_scores"] == "TRUE"
    assert row["no_fabricated_returns"] == "TRUE"
    assert row["no_fabricated_benchmark_rows"] == "TRUE"
    assert row["current_snapshot_join_count"] == "0"
    assert row["current_fundamental_field_used_count"] == "0"
    assert row["future_price_used_for_factor_count"] == "0"


def test_canonical_price_pit_lite_backtest() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "CANONICAL_PRICE_INPUTS_PASS=",
        "VALID_RANDOM_ASOF_COUNT=",
        "RECOMPUTED_TICKER_ASOF_ROWS=",
        "NO_LOOKAHEAD_GUARD_PASS=TRUE",
        "NO_OFFICIAL_TRADE_MUTATION=TRUE",
        "RESEARCH_ONLY=TRUE",
        "NO_FABRICATED_SCORES=TRUE",
        "NO_FABRICATED_RETURNS=TRUE",
        "NO_FABRICATED_BENCHMARK_ROWS=TRUE",
    ]:
        assert expected in stdout, expected
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    input_audit = read_csv(OUTPUTS[0])
    dates = read_csv(OUTPUTS[1])
    policy = read_csv(OUTPUTS[2])
    snapshots = read_csv(OUTPUTS[3])
    selections = read_csv(OUTPUTS[4])
    forward = read_csv(OUTPUTS[5])
    benchmark = read_csv(OUTPUTS[6])
    comparison = read_csv(OUTPUTS[7])
    weights = read_csv(OUTPUTS[8])
    dynamic = read_csv(OUTPUTS[9])
    guard = read_csv(OUTPUTS[10])
    effect = read_csv(OUTPUTS[11])[0]
    gate = read_csv(OUTPUTS[12])[0]

    assert len(input_audit) == 5
    assert all(row["input_status"] == "PASS" for row in input_audit)
    assert all(row["canonical_close_used"] == "TRUE" for row in input_audit)
    assert all(row["adjusted_close_future_adjustment_risk_flag"] == "FALSE" for row in input_audit)
    assert gate["canonical_price_inputs_pass"] == "TRUE"
    assert gate["final_status"].startswith(("PASS", "PARTIAL_PASS", "BLOCKED"))
    assert gate["no_lookahead_guard_pass"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert_common(gate)

    assert len(dates) >= 30
    assert len(snapshots) >= 500
    assert len(selections) > 0
    assert len(forward) > 0
    assert len(benchmark) > 0
    assert len(comparison) > 0
    assert len(weights) == len(comparison)
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert all(row["dynamic_weight_status"] == "EVALUATED_SHADOW_ONLY" for row in dynamic)
    assert all(row["dynamic_weight_activated"] == "FALSE" for row in dynamic)
    assert {row["factor_family"] for row in policy} >= {"FUNDAMENTAL", "TECHNICAL", "STRATEGY", "RISK", "MARKET_REGIME", "DATA_TRUST"}
    assert all(row["scoring_weight"] == "0.0000000000" for row in policy if row["factor_family"] in {"FUNDAMENTAL", "DATA_TRUST"})
    assert all(row["max_factor_input_date"] <= row["as_of_date"] for row in snapshots)
    assert all(row["min_forward_return_date"] > row["as_of_date"] for row in forward if row["return_status"] == "PASS")
    assert all(row["min_benchmark_return_date"] > row["as_of_date"] for row in benchmark if row["benchmark_status"] == "PASS")
    assert all(row["forward_return"] == "" for row in forward if row["return_status"] != "PASS")
    assert all(row["benchmark_forward_return"] == "" for row in benchmark if row["benchmark_status"] != "PASS")
    assert any(row["benchmark"] == "QQQ" and int(row["valid_return_count"]) > 0 for row in comparison)
    assert any(row["benchmark"] == "SPY" and int(row["valid_return_count"]) > 0 for row in comparison)
    assert effect["no_lookahead_guard_pass"] == "TRUE"
    assert int(effect["forward_windows_with_valid_results"]) >= 3
    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "canonical V20.199D close prices only" in report
    assert "CURRENT_UNIVERSE_SURVIVORSHIP_RISK" in report


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert any(status in result.stdout for status in [
        "PASS_V20_199B_R1_PIT_LITE_RANDOM_ASOF_RECOMPUTE_BACKTEST_WITH_CANONICAL_PRICE_HISTORY",
        "PARTIAL_PASS_V20_199B_R1_PIT_LITE_RANDOM_ASOF_RECOMPUTE_BACKTEST_WITH_CANONICAL_PRICE_HISTORY",
        "BLOCKED_V20_199B_R1_PIT_LITE_RANDOM_ASOF_RECOMPUTE_BACKTEST_WITH_CANONICAL_PRICE_HISTORY",
    ])
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "NO_FABRICATED_RETURNS=TRUE" in result.stdout


if __name__ == "__main__":
    test_canonical_price_pit_lite_backtest()
    test_wrapper_parseable()
    print("PASS test_v20_199b_r1_pit_lite_random_asof_recompute_backtest_with_canonical_price_history")
