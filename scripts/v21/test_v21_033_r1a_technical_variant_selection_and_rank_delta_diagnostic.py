#!/usr/bin/env python
"""Tests for V21.033-R1A technical variant selection diagnostic."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_033_r1a_technical_variant_selection_and_rank_delta_diagnostic.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_AND_RANK_DELTA_DIAGNOSTIC_REPORT.md"

SUMMARY = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_SUMMARY.csv"
DELTA = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SCORE_RANK_DELTA_AUDIT.csv"
BUCKET = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_BUCKET_COMPOSITION_AUDIT.csv"
TIEBREAK = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_TIEBREAK_AUDIT.csv"
RECOMMEND = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_DIAGNOSTIC_RECOMMENDATION.csv"

REQUIRED = [SUMMARY, DELTA, BUCKET, TIEBREAK, RECOMMEND, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_SUMMARY.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_033_r1a_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.033-R1A_TECHNICAL_VARIANT_SELECTION_AND_RANK_DELTA_DIAGNOSTIC" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_033_R1A", "PARTIAL_PASS_V21_033_R1A"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"
    assert summary["diagnostic_variant_name"] == "RSI_DEEMPHASIZED"
    assert summary["zero_excess_detected"] == "TRUE"
    assert summary["probable_issue_type"]

    delta = read_csv(DELTA)[0]
    if float(delta["score_changed_ratio"] or 0.0) == 0.0:
        assert delta["no_op_warning"] == "TRUE"
    if float(delta["top20_overlap_ratio"] or 0.0) == 1.0:
        assert summary["top20_composition_changed"] == "FALSE"

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "shadow adoption remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_033_r1a_contract()
    print("V21.033-R1A technical variant selection diagnostic tests passed")
