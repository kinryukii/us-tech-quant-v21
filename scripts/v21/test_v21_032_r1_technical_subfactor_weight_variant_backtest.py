#!/usr/bin/env python
"""Tests for V21.032-R1 technical subfactor weight variant backtest."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_032_r1_technical_subfactor_weight_variant_backtest.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_032_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST_REPORT.md"

SUMMARY = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv"
INFLUENCE = OUT_DIR / "V21_032_R1_TECHNICAL_SUBFACTOR_INFLUENCE_AUDIT.csv"
DEFINITIONS = OUT_DIR / "V21_032_R1_TECHNICAL_WEIGHT_VARIANT_DEFINITIONS.csv"
BY_WINDOW = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv"
RANK_COMPARISON = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_RANK_COMPARISON.csv"
RECOMMENDATION = OUT_DIR / "V21_032_R1_TECHNICAL_REWEIGHTING_RECOMMENDATION.csv"

REQUIRED = [
    SUMMARY,
    INFLUENCE,
    DEFINITIONS,
    BY_WINDOW,
    RANK_COMPARISON,
    RECOMMENDATION,
    REPORT,
]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_032_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.032-R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANT_BACKTEST" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_032_R1", "PARTIAL_PASS_V21_032_R1"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"
    assert int(summary["variants_tested_count"]) >= 5
    assert int(summary["immature_rows_excluded"]) >= 1

    definitions = read_csv(DEFINITIONS)
    names = {row["variant_name"] for row in definitions}
    assert len(definitions) >= 5
    assert "BASELINE_CURRENT_TECHNICAL" in names
    assert "RSI_DEEMPHASIZED" in names
    assert "MOMENTUM_DEDUPED" in names
    assert "TECHNICAL_SUBFACTOR_CAPPED" in names
    assert "REGIME_AWARE_RSI_PROXY" in names

    by_window = read_csv(BY_WINDOW)
    assert by_window
    assert any(row["forward_window"] == "60D" and row["result_quality"] == "FORWARD_WINDOW_UNAVAILABLE_OR_IMMATURE" for row in by_window)
    assert any(row["result_quality"] == "BENCHMARK_DATA_MISSING" for row in by_window)

    influence = read_csv(INFLUENCE)
    rsi = next(row for row in influence if row["subfactor_name"] == "RSI")
    if int(rsi["non_null_count"]) == 0:
        assert rsi["interpretation_issue"] == "MISSING_SUBFACTOR_DATA"

    methods = {row["scoring_method"] for row in definitions}
    if int(rsi["non_null_count"]) == 0:
        assert "PROXY_LIMITED" in methods or "PROXY_RESCORING" in methods

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert "TECHNICAL_SUBFACTOR_REWEIGHTING_RESEARCH_READY_SHADOW_ONLY_OFFICIAL_UPDATE_BLOCKED" in report
    assert "Why official weight mutation remains blocked" in report
    assert "Official weight mutation remains blocked" in report


if __name__ == "__main__":
    test_v21_032_r1_contract()
    print("V21.032-R1 technical subfactor variant backtest tests passed")
