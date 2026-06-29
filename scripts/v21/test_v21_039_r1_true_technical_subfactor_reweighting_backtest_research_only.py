#!/usr/bin/env python
"""Tests for V21.039-R1 true technical reweighting backtest."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_039_r1_true_technical_subfactor_reweighting_backtest_research_only.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_039_R1_TRUE_TECHNICAL_SUBFACTOR_REWEIGHTING_BACKTEST_RESEARCH_ONLY_REPORT.md"

SUMMARY = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv"
DEFINITIONS = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_DEFINITIONS.csv"
BACKTEST = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv"
RANK_COMPARISON = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_RANK_COMPARISON.csv"
COLLINEARITY = OUT_DIR / "V21_039_R1_TECHNICAL_COLLINEARITY_AUDIT.csv"
RSI_AUDIT = OUT_DIR / "V21_039_R1_RSI_BEHAVIOR_AUDIT.csv"
RECOMMENDATION = OUT_DIR / "V21_039_R1_TECHNICAL_REWEIGHTING_RECOMMENDATION.csv"
VALIDATION = OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, DEFINITIONS, BACKTEST, RANK_COMPARISON, COLLINEARITY, RSI_AUDIT, RECOMMENDATION, VALIDATION, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_039_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.039-R1_TRUE_TECHNICAL_SUBFACTOR_REWEIGHTING_BACKTEST_RESEARCH_ONLY" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith((
        "PASS_V21_039_R1",
        "PARTIAL_PASS_V21_039_R1",
        "BLOCKED_V21_039_R1_INPUTS_MISSING",
    ))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["official_adoption_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    definitions = read_csv(DEFINITIONS)
    names = {row["variant_name"] for row in definitions}
    assert len(definitions) >= 7
    for required in {
        "BASELINE_TRUE_TECHNICAL",
        "RSI_DEEMPHASIZED_TRUE",
        "MOMENTUM_DEDUPED_TRUE",
        "REGIME_AWARE_RSI_TRUE",
        "TECHNICAL_CAPPED_TRUE",
    }:
        assert required in names

    if summary["matured_forward_return_source_found"] == "FALSE":
        assert summary["final_status"] == "PARTIAL_PASS_V21_039_R1_LIMITED_BY_FORWARD_RETURN_DATA"
        assert summary["best_research_variant_selected"] == "FALSE"

    recs = read_csv(RECOMMENDATION)
    if float(summary["best_variant_mean_excess_vs_baseline"] or 0.0) <= 0:
        assert all(row["shadow_gate_allowed"] == "FALSE" for row in recs)

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_039_r1_contract()
    print("V21.039-R1 true technical reweighting tests passed")
