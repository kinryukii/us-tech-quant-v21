#!/usr/bin/env python
"""Tests for V21.033-R1 technical variant robustness gate."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_033_r1_technical_variant_robustness_and_shadow_adoption_gate.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_AND_SHADOW_ADOPTION_GATE_REPORT.md"

SUMMARY = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_SUMMARY.csv"
BY_WINDOW = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_BY_WINDOW.csv"
BY_BUCKET = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_BY_BUCKET.csv"
BENCH = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_BENCHMARK_DECOMPOSITION.csv"
DECISION = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_SHADOW_ADOPTION_DECISION.csv"

REQUIRED = [SUMMARY, BY_WINDOW, BY_BUCKET, BENCH, DECISION, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_033_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.033-R1_TECHNICAL_VARIANT_ROBUSTNESS_AND_SHADOW_ADOPTION_GATE" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_033_R1", "PARTIAL_PASS_V21_033_R1"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"
    assert summary["candidate_variant_name"] == "RSI_DEEMPHASIZED"
    assert summary["official_adoption_allowed"] == "FALSE"
    assert summary["shadow_adoption_allowed"] in {"TRUE", "FALSE"}

    candidate_excess = float(summary["candidate_mean_excess_vs_baseline"] or 0.0)
    candidate_hit = float(summary["candidate_hit_rate"] or 0.0)
    baseline_hit = float(summary["baseline_hit_rate"] or 0.0)
    if candidate_excess <= 0:
        assert summary["shadow_adoption_allowed"] == "FALSE"
    if candidate_hit < baseline_hit:
        assert summary["shadow_adoption_allowed"] == "FALSE"

    decision = read_csv(DECISION)[0]
    assert decision["candidate_variant_name"] == "RSI_DEEMPHASIZED"
    assert decision["official_adoption_allowed"] == "FALSE"
    assert decision["shadow_adoption_allowed"] in {"TRUE", "FALSE"}

    bench = read_csv(BENCH)
    assert {row["benchmark_name"] for row in bench} == {"QQQ", "SPY", "SOXX"}
    missing_rows = [row for row in bench if row["benchmark_available"] == "FALSE"]
    for row in missing_rows:
        assert row["benchmark_interpretation_status"] == "BENCHMARK_DATA_MISSING"

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official adoption remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_033_r1_contract()
    print("V21.033-R1 technical variant robustness gate tests passed")
