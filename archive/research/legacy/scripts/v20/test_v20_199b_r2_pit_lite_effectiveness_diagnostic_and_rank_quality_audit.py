#!/usr/bin/env python
"""Tests for V20.199B-R2 PIT-lite diagnostic and rank quality audit."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_199b_r2_pit_lite_effectiveness_diagnostic_and_rank_quality_audit.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_199b_r2_pit_lite_effectiveness_diagnostic_and_rank_quality_audit.ps1"
OUT_DIR = ROOT / "outputs" / "v20" / "backtest"
OUTPUTS = [
    OUT_DIR / "V20_199B_R2_INPUT_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_SCENARIO_ROBUSTNESS_SUMMARY.csv",
    OUT_DIR / "V20_199B_R2_TOPN_MONOTONICITY_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_BENCHMARK_ROBUSTNESS_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_FORWARD_WINDOW_EFFECTIVENESS_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_TOP5_TOP10_RANK_PRECISION_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_OUTLIER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_ASOF_PERIOD_STABILITY_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_DYNAMIC_WEIGHT_ELIGIBILITY_AUDIT.csv",
    OUT_DIR / "V20_199B_R2_RESEARCH_CONCLUSION_SUMMARY.csv",
    OUT_DIR / "V20_199B_R2_NO_LOOKAHEAD_AND_NO_MUTATION_GUARD.csv",
    OUT_DIR / "V20_199B_R2_NEXT_STAGE_GATE.csv",
    OUT_DIR / "V20_199B_R2_READ_CENTER_REPORT.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_common(row: dict[str, str]) -> None:
    assert row["research_only"] == "TRUE"
    assert row["official_ranking_mutated"] == "FALSE"
    assert row["official_recommendation_created"] == "FALSE"
    assert row["trade_action_created"] == "FALSE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["real_book_action_created"] == "FALSE"
    assert row["no_lookahead_guard_pass"] == "TRUE"
    assert row["no_fabricated_scores"] == "TRUE"
    assert row["no_fabricated_returns"] == "TRUE"
    assert row["no_fabricated_benchmark_rows"] == "TRUE"
    assert row["current_snapshot_join_count"] == "0"
    assert row["current_fundamental_field_used_count"] == "0"
    assert row["future_price_used_for_factor_count"] == "0"


def test_r2_diagnostic_audit() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    stdout = result.stdout
    for expected in [
        "R1_INPUT_GATE_PASSED=TRUE",
        "NO_LOOKAHEAD_GUARD_PASS=TRUE",
        "DIAGNOSTIC_OUTPUTS_CREATED=TRUE",
        "DYNAMIC_WEIGHT_STATUS=SHADOW_ONLY",
        "ELIGIBLE_FOR_OFFICIAL_WEIGHT_ACTIVATION=FALSE",
        "RESEARCH_ONLY=TRUE",
        "OFFICIAL_RANKING_MUTATED=FALSE",
        "TRADE_ACTION_CREATED=FALSE",
    ]:
        assert expected in stdout, expected
    assert any(status in stdout for status in ["PASS_DIAGNOSTIC_READY", "PARTIAL_PASS_MIXED_SIGNAL"])
    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    input_audit = read_csv(OUTPUTS[0])
    scenario = read_csv(OUTPUTS[1])
    topn = read_csv(OUTPUTS[2])
    benchmark = read_csv(OUTPUTS[3])
    window = read_csv(OUTPUTS[4])
    precision = read_csv(OUTPUTS[5])
    outlier = read_csv(OUTPUTS[6])
    period = read_csv(OUTPUTS[7])
    dynamic = read_csv(OUTPUTS[8])
    conclusion = read_csv(OUTPUTS[9])
    guard = read_csv(OUTPUTS[10])
    gate = read_csv(OUTPUTS[11])[0]

    assert len(input_audit) == 9
    assert all(row["input_status"] == "PASS" for row in input_audit)
    assert len(scenario) >= 1
    assert len(topn) >= 4
    assert len(benchmark) >= 16
    assert len(window) >= 4
    assert len(precision) >= 2
    assert len(outlier) >= 16
    assert len(period) >= 16
    assert len(dynamic) == 1
    assert len(conclusion) == 1
    assert all(row["guard_passed"] == "TRUE" for row in guard)
    assert gate["r1_input_gate_passed"] == "TRUE"
    assert gate["no_lookahead_guard_pass"] == "TRUE"
    assert gate["diagnostic_outputs_created"] == "TRUE"
    assert gate["no_official_trade_mutation"] == "TRUE"
    assert gate["final_status"] in {"PASS_DIAGNOSTIC_READY", "PARTIAL_PASS_MIXED_SIGNAL"}
    assert dynamic[0]["dynamic_weight_status"] == "SHADOW_ONLY"
    assert dynamic[0]["eligible_for_official_weight_activation"] == "FALSE"
    assert any(row["topn_monotonicity_status"] in {"TOPN_PRECISION_STRONG", "BROAD_BUCKET_STRONGER", "MIXED_TOPN_SIGNAL"} for row in topn)
    assert any(row["benchmark_robustness_status"] in {"BENCHMARK_ROBUST", "TECH_BETA_NOT_ALPHA", "SEMI_BETA_UNDERPERFORMANCE", "MIXED_BENCHMARK_SIGNAL", "BENCHMARK_WEAK"} for row in benchmark)
    assert any(row["concentrated_selection_status"] in {"NOT_READY", "WATCHLIST_ONLY", "SHADOW_ONLY", "ELIGIBLE_FOR_FURTHER_VALIDATION"} for row in precision)
    assert_common(gate)

    report = OUTPUTS[-1].read_text(encoding="utf-8")
    assert "PIT-lite only" in report
    assert "Dynamic weights remain SHADOW_ONLY" in report
    assert "No official ranking mutation" in report


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert any(status in result.stdout for status in ["PASS_DIAGNOSTIC_READY", "PARTIAL_PASS_MIXED_SIGNAL"])
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout


if __name__ == "__main__":
    test_r2_diagnostic_audit()
    test_wrapper_parseable()
    print("PASS test_v20_199b_r2_pit_lite_effectiveness_diagnostic_and_rank_quality_audit")
