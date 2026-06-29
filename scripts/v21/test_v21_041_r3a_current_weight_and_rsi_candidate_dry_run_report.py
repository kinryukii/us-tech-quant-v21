#!/usr/bin/env python
"""Tests for V21.041-R3A current weight RSI candidate dry-run report."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_041_r3a_current_weight_and_rsi_candidate_dry_run_report.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_041_R3A_CURRENT_WEIGHT_AND_RSI_CANDIDATE_DRY_RUN_REPORT.md"

SUMMARY = OUT_DIR / "V21_041_R3A_CURRENT_WEIGHT_DRY_RUN_SUMMARY.csv"
RANKING = OUT_DIR / "V21_041_R3A_CURRENT_RANKING_COMPARISON.csv"
TOP20 = OUT_DIR / "V21_041_R3A_TOP20_COMPARISON.csv"
TOP40 = OUT_DIR / "V21_041_R3A_TOP40_COMPARISON.csv"
CHANGE = OUT_DIR / "V21_041_R3A_DRY_RUN_CHANGE_AUDIT.csv"
VALIDATION = OUT_DIR / "V21_041_R3A_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, RANKING, TOP20, TOP40, CHANGE, VALIDATION, REPORT]

GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_041_R2_CONTEXT_CONDITIONED_RETEST_SUMMARY.csv",
    OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_VARIANT_DEFINITION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_REALIZED_FORWARD_RETURNS.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in GUARD_PATHS if path.exists()}


def test_v21_041_r3a_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.041-R3A_CURRENT_WEIGHT_AND_RSI_CANDIDATE_DRY_RUN_REPORT" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["shadow_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["official_adoption_allowed"] == "FALSE"
    assert summary["shadow_gate_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    if int(float(summary["current_input_rows"] or 0)) > 0:
        assert read_csv(TOP20)
        assert read_csv(TOP40)

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_041_r3a_contract()
    print("V21.041-R3A current dry-run tests passed")
