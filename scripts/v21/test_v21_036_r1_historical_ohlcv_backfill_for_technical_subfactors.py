#!/usr/bin/env python
"""Tests for V21.036-R1 historical OHLCV backfill."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_036_r1_historical_ohlcv_backfill_for_technical_subfactors.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_036_R1_HISTORICAL_OHLCV_BACKFILL_FOR_TECHNICAL_SUBFACTORS_REPORT.md"

SUMMARY = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_BACKFILL_SUMMARY.csv"
NORMALIZED = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_NORMALIZED.csv"
SOURCE_AUDIT = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_SOURCE_AUDIT.csv"
DEPTH = OUT_DIR / "V21_036_R1_HISTORICAL_DEPTH_BY_TICKER.csv"
READINESS = OUT_DIR / "V21_036_R1_TECHNICAL_RERUN_READINESS_MATRIX.csv"

REQUIRED = [SUMMARY, NORMALIZED, SOURCE_AUDIT, DEPTH, READINESS, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_SUMMARY.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_036_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.036-R1_HISTORICAL_OHLCV_BACKFILL_FOR_TECHNICAL_SUBFACTORS" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_036_R1", "PARTIAL_PASS_V21_036_R1", "BLOCKED_V21_036_R1_NO_LOCAL_OHLCV_SOURCE"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    normalized = read_csv(NORMALIZED)
    if summary["local_ohlcv_source_found"] == "TRUE":
        keys = [(row["ticker"], row["as_of_date"]) for row in normalized if row.get("ticker") and row.get("as_of_date")]
        assert len(keys) == len(set(keys))

    depth = read_csv(DEPTH)
    required_depth_fields = {
        "rsi14_ready", "kdj9_ready", "macd_26_9_ready", "bb20_ready",
        "ma20_ready", "ma50_ready", "volume_ma20_ready", "technical_score_ready",
    }
    assert required_depth_fields.issubset(depth[0].keys())
    if float(summary["median_history_depth_by_ticker"] or 0.0) < 60:
        assert summary["true_reweighting_ready"] == "FALSE"

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_036_r1_contract()
    print("V21.036-R1 historical OHLCV backfill tests passed")
