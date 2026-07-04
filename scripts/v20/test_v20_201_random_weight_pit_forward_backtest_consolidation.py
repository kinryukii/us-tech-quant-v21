#!/usr/bin/env python
"""Tests for V20.201 random-weight PIT-forward backtest consolidation."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_201_random_weight_pit_forward_backtest_consolidation.py"
OUT_DIR = ROOT / "outputs" / "v20" / "random_weight_backtest"
REPORT = ROOT / "outputs" / "v20" / "read_center" / "V20_201_RANDOM_WEIGHT_PIT_FORWARD_BACKTEST_REPORT.md"
OUTPUTS = [
    OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv",
    OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv",
    OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv",
    OUT_DIR / "V20_201_WEIGHT_EFFECTIVENESS_SUMMARY.csv",
    OUT_DIR / "V20_201_PIT_LEAKAGE_AUDIT.csv",
    OUT_DIR / "V20_201_SOURCE_COVERAGE_DIAGNOSTICS.csv",
    REPORT,
]
BLOCKED = {
    "BLOCKED_V20_201_PIT_VALIDATION_FAILED",
    "BLOCKED_V20_201_ETF_ROTATION_BENCHMARK_UNAVAILABLE",
    "BLOCKED_V20_201_NO_VALID_TRIALS",
}
FORBIDDEN = [
    "forward", "outcome", "future", "return_after", "realized", "exit_price",
    "max_runup", "max_drawdown", "benchmark_return",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v20_201_random_weight_pit_forward_backtest() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=" in result.stdout
    assert "RESEARCH_ONLY=TRUE" in result.stdout
    assert "OFFICIAL_WEIGHT_MUTATED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "REAL_BOOK_SIGNAL_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout

    for path in OUTPUTS:
        assert path.exists(), f"missing output {path}"

    summary = read_csv(OUT_DIR / "V20_201_WEIGHT_EFFECTIVENESS_SUMMARY.csv")[0]
    final_status = summary["final_status"]
    trials = read_csv(OUT_DIR / "V20_201_RANDOM_WEIGHT_TRIALS.csv")
    rankings = read_csv(OUT_DIR / "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv")
    forward = read_csv(OUT_DIR / "V20_201_RANDOM_WEIGHT_FORWARD_OUTCOMES.csv")
    etf = read_csv(OUT_DIR / "V20_201_ETF_ROTATION_BENCHMARK_OUTCOMES.csv")
    pit = read_csv(OUT_DIR / "V20_201_PIT_LEAKAGE_AUDIT.csv")

    assert trials
    assert read_csv(OUT_DIR / "V20_201_PIT_LEAKAGE_AUDIT.csv")
    assert read_csv(OUT_DIR / "V20_201_SOURCE_COVERAGE_DIAGNOSTICS.csv")
    if final_status not in BLOCKED:
        assert rankings
        assert forward
        assert etf

    trial_ids = [row["trial_id"] for row in trials]
    assert len(trial_ids) == len(set(trial_ids))
    assert all(row["seed"] for row in trials)
    for row in trials:
        if row["trial_status"] == "BLOCKED":
            continue
        weight_sum = sum(float(row[f"{name}_weight"]) for name in ["fundamental", "technical", "strategy", "risk", "market_regime"])
        assert abs(weight_sum - 1.0) < 1e-8
        assert row["data_trust_weight"] == "0.0000000000"
        assert row["data_trust_used_in_ranking"] == "FALSE"
        assert row["data_trust_used_as_audit_gate"] == "TRUE"
        assert row["official_weight_mutated"] == "FALSE"
        assert row["official_recommendation_created"] == "FALSE"
        assert row["real_book_signal_created"] == "FALSE"
        assert row["broker_execution_supported"] == "FALSE"

    assert all(not (row["leakage_keyword_hit"] == "TRUE" and row["allowed_in_ranking"] == "TRUE") for row in pit)
    audited_ranking_inputs = [row for row in pit if row["checked_artifact"] == "V20_201_RANDOM_WEIGHT_ASOF_RANKINGS.csv"]
    forbidden_ranking_inputs = [
        row["checked_field"] for row in audited_ranking_inputs
        if row["allowed_in_ranking"] == "TRUE" and any(key in row["checked_field"].lower() for key in FORBIDDEN)
    ]
    assert not forbidden_ranking_inputs

    assert all(row["as_of_date"] < row["exit_date"] for row in forward if row["outcome_status"] == "PASS")
    valid_trials = {row["trial_id"] for row in trials if row["trial_status"] == "VALID"}
    etf_trials = {row["trial_id"] for row in etf if row["benchmark_status"] == "PASS"}
    coverage_warning = float(summary["etf_benchmark_coverage_rate"] or 0.0) < 1.0
    assert valid_trials <= etf_trials or coverage_warning

    created_artifacts = [path.name.lower() for path in OUT_DIR.glob("*")]
    forbidden_artifact_terms = ["official_recommendation", "broker_execution", "trade_action", "real_book_signal"]
    assert not any(any(term in name for term in forbidden_artifact_terms) for name in created_artifacts)
    assert "official weights were not changed" in REPORT.read_text(encoding="utf-8")
    assert final_status in REPORT.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_v20_201_random_weight_pit_forward_backtest()
    print("PASS test_v20_201_random_weight_pit_forward_backtest_consolidation")
