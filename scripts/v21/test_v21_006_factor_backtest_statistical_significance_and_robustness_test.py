#!/usr/bin/env python
"""Tests for V21.006 factor backtest statistical significance and robustness test."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_006_factor_backtest_statistical_significance_and_robustness_test.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_006_factor_backtest_statistical_significance_and_robustness_test.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_006_PRIMARY_DATASET_VALIDATION.csv",
    OUT_DIR / "V21_006_RANK_BUCKET_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANK_MONOTONICITY_TEST.csv",
    OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_006_SUBSAMPLE_ROBUSTNESS_STATS.csv",
    OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv",
    OUT_DIR / "V21_006_BENCHMARK_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_DECISION_GRADE_ROBUSTNESS_SCORECARD.csv",
    OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
    OUT_DIR / "V21_005_FORWARD_RETURN_WINDOW_COVERAGE.csv",
    OUT_DIR / "V21_005_RANK_BUCKET_FORWARD_RETURN_STATS.csv",
    OUT_DIR / "V21_005_FACTOR_FAMILY_IC_STATS.csv",
    OUT_DIR / "V21_005_FACTOR_ABLATION_FORWARD_RETURN_STATS.csv",
    OUT_DIR / "V21_005_RISK_OVERHEAT_EFFECTIVENESS_STATS.csv",
    OUT_DIR / "V21_005_REGIME_CONDITIONED_PERFORMANCE_STATS.csv",
    OUT_DIR / "V21_005_BENCHMARK_COMPARISON_STATS.csv",
    OUT_DIR / "V21_005_DECISION_GRADE_READINESS_SCORECARD.csv",
    OUT_DIR / "V21_005_REJECTED_OR_LEAKAGE_RISK_OBSERVATIONS.csv",
    OUT_DIR / "V21_005_BACKTEST_ENGINE_SUMMARY.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    before = snapshot(INPUTS)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = snapshot(INPUTS)
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    assert not changed, f"input files modified: {changed}"
    return result


def test_v21_006_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert "PRODUCTION" not in summary["final_verdict"]
    assert "REAL_BOOK" not in summary["final_verdict"]

    validation = read_csv(OUT_DIR / "V21_006_PRIMARY_DATASET_VALIDATION.csv")
    validation_by_item = {row["validation_item"]: row for row in validation}
    assert int(validation_by_item["primary_usable_matured_observation_count"]["validation_value"]) > 0
    assert validation_by_item["primary_stats_selection_status"]["validation_status"] == "PASS"
    assert validation_by_item["rejected_diagnostic_excluded_from_primary_statistics"]["validation_status"] == "PASS"

    rank_rows = read_csv(OUT_DIR / "V21_006_RANK_BUCKET_SIGNIFICANCE_STATS.csv")
    assert rank_rows, "rank bucket significance missing"
    assert any(row["forward_return_window"] for row in rank_rows), "no evaluated forward-return window tested"
    assert all(row["primary_stats_maturity_filter"] == "MATURED_ONLY" for row in rank_rows)
    assert all(row["diagnostic_observations_excluded"] == "TRUE" for row in rank_rows)

    random_rows = read_csv(OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv")
    assert random_rows, "random baseline comparison missing"
    assert all(row["deterministic_seed"] for row in random_rows)
    assert all(row["random_trial_count"] == "500" for row in random_rows if row["sample_status"] == "SUFFICIENT")
    assert summary["random_seed_base"] == "21006"

    ic_rows = read_csv(OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv")
    data_trust = [row for row in ic_rows if row["factor_family"] == "DATA_TRUST"]
    assert data_trust, "DATA_TRUST IC control rows missing"
    assert all(row["data_trust_alpha_contribution"] == "0" for row in data_trust)
    assert all(row["alpha_contribution_allowed"] == "FALSE_AUDIT_ONLY_ZERO_ALPHA_CONTROL" for row in data_trust)

    scorecard = read_csv(OUT_DIR / "V21_006_DECISION_GRADE_ROBUSTNESS_SCORECARD.csv")
    for gate in [
        "data_trust_zero_contribution",
        "no_official_ranking_mutation",
        "no_recommendation",
        "no_trade_action",
        "no_shadow_activation",
    ]:
        rows = [row for row in scorecard if row["hard_gate"] == gate]
        assert rows and rows[0]["gate_passed"] == "TRUE"

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final verdict",
        "primary dataset validation",
        "data_trust zero-contribution confirmation",
        "explicit blocked actions",
        "no production or real-book readiness verdict",
        "v21.007_factor_architecture_repair_plan_or_weight_update_blocker",
    ]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    for blocked_term in ["yfinance", "requests.", "urllib.request", "http.client", "socket.", "download("]:
        assert blocked_term not in script_text, f"network access term found: {blocked_term}"


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST",
        "final_verdict=",
        "final_status=",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_factor_weight_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_006_contract()
    test_wrapper_parseable()
    print("V21.006 factor backtest statistical significance and robustness tests passed")
