#!/usr/bin/env python
"""Tests for V21.005 point-in-time walk-forward factor backtest engine."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_005_point_in_time_walk_forward_factor_backtest_engine.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_005_point_in_time_walk_forward_factor_backtest_engine.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE_REPORT.md"
REQUIRED_OUTPUTS = [
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
    REPORT,
]
INPUTS = [
    OUT_DIR / "V21_004_OBSERVATION_MATURITY_AUDIT.csv",
    OUT_DIR / "V21_004_LEAKAGE_RISK_AUDIT.csv",
    OUT_DIR / "V21_004_FACTOR_EVIDENCE_CAPABILITY_MATRIX.csv",
    OUT_DIR / "V21_004_DECISION_GRADE_GAP_TABLE.csv",
    OUT_DIR / "V21_004_REDESIGN_CONTRACT.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "recalibration" / "V21_003_RISK_REGIME_JOINED_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "recalibration_r1" / "V21_003_R1_NEXT_STAGE_GATE.csv",
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


def test_v21_005_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary_rows = read_csv(OUT_DIR / "V21_005_BACKTEST_ENGINE_SUMMARY.csv")
    assert summary_rows, "summary missing rows"
    summary = summary_rows[0]
    assert summary["research_only"] == "TRUE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"

    selection_rows = read_csv(OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv")
    assert any(row["selection_status"] == "USABLE_PRIMARY" for row in selection_rows)
    assert all(row["maturity_status"] == "MATURED" for row in selection_rows if row["selection_status"] == "USABLE_PRIMARY")
    assert not any(row["selection_status"] == "USABLE_PRIMARY" and row["maturity_status"] == "PENDING" for row in selection_rows)

    diagnostic_rows = read_csv(OUT_DIR / "V21_005_REJECTED_OR_LEAKAGE_RISK_OBSERVATIONS.csv")
    assert diagnostic_rows, "rejected/leakage diagnostics missing"
    assert any("maturity_pending" in row["diagnostic_reason"] or "non_primary_or_schedule_source" in row["diagnostic_reason"] for row in diagnostic_rows)

    rank_rows = read_csv(OUT_DIR / "V21_005_RANK_BUCKET_FORWARD_RETURN_STATS.csv")
    assert rank_rows, "rank bucket stats missing"
    assert all(row["primary_stats_maturity_filter"] == "MATURED_ONLY" for row in rank_rows)

    coverage_rows = read_csv(OUT_DIR / "V21_005_FORWARD_RETURN_WINDOW_COVERAGE.csv")
    available = [row for row in coverage_rows if row["availability_status"].startswith("AVAILABLE") and int(row["usable_observation_count"]) > 0]
    if int(summary["usable_primary_observation_count"]) > 0:
        assert available, "no forward-return window evaluated despite usable data"

    ablation_rows = read_csv(OUT_DIR / "V21_005_FACTOR_ABLATION_FORWARD_RETURN_STATS.csv")
    data_trust_rows = [row for row in ablation_rows if row["ablation_family"] == "DATA_TRUST"]
    assert data_trust_rows, "DATA_TRUST ablation rows missing"
    assert all(row["data_trust_alpha_contribution"] == "0" for row in data_trust_rows)

    ic_rows = read_csv(OUT_DIR / "V21_005_FACTOR_FAMILY_IC_STATS.csv")
    assert any(row["factor_family"] == "DATA_TRUST" and row["alpha_contribution_allowed"] == "FALSE" for row in ic_rows)

    readiness_rows = read_csv(OUT_DIR / "V21_005_DECISION_GRADE_READINESS_SCORECARD.csv")
    verdict = summary["final_verdict"]
    if verdict == "DECISION_GRADE_CANDIDATE":
        assert all(row["gate_passed"] == "TRUE" for row in readiness_rows)
    else:
        assert any(row["gate_passed"] == "FALSE" for row in readiness_rows)

    leakage_gate = [row for row in readiness_rows if row["hard_gate"] == "no_critical_leakage_risk"]
    assert leakage_gate, "leakage hard gate missing"
    if leakage_gate[0]["gate_passed"] == "FALSE":
        assert verdict != "DECISION_GRADE_CANDIDATE"

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research_only: true",
        "final verdict",
        "observation selection summary",
        "data_trust zero-contribution confirmation",
        "explicit blocked actions",
        "v21.006_factor_backtest_statistical_significance_and_robustness_test",
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
        "STAGE_NAME=V21_005_POINT_IN_TIME_WALK_FORWARD_FACTOR_BACKTEST_ENGINE",
        "final_verdict=",
        "final_status=",
        "usable_primary_observation_count=",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_005_contract()
    test_wrapper_parseable()
    print("V21.005 point-in-time walk-forward factor backtest engine tests passed")
