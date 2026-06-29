#!/usr/bin/env python
"""Tests for V21.037-R1 historical OHLCV ingestion and cache expansion."""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_037_r1_historical_ohlcv_ingestion_and_cache_expansion.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
CACHE_DIR = ROOT / "inputs" / "v21" / "historical_ohlcv_cache"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_AND_CACHE_EXPANSION_REPORT.md"

SUMMARY = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_SUMMARY.csv"
CACHE = CACHE_DIR / "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"
SOURCE_AUDIT = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_SOURCE_AUDIT.csv"
DEPTH = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_TICKER_DEPTH_AFTER_INGESTION.csv"
FETCH_PLAN = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_FETCH_PLAN.csv"
READINESS = OUT_DIR / "V21_037_R1_TECHNICAL_RERUN_READINESS_MATRIX.csv"

REQUIRED = [SUMMARY, CACHE, SOURCE_AUDIT, DEPTH, FETCH_PLAN, READINESS, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_036_R1_HISTORICAL_OHLCV_BACKFILL_SUMMARY.csv",
    ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_037_r1_contract() -> None:
    before = mtimes()
    env = os.environ.copy()
    env.pop("V21_ALLOW_NETWORK_BACKFILL", None)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True, env=env)
    assert "STAGE_NAME=V21.037-R1_HISTORICAL_OHLCV_INGESTION_AND_CACHE_EXPANSION" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith((
        "PASS_V21_037_R1",
        "PARTIAL_PASS_V21_037_R1",
        "BLOCKED_V21_037_R1_NO_USABLE_OHLCV_SOURCE",
    ))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"
    assert summary["network_backfill_enabled"] == "FALSE"
    assert summary["network_backfill_used"] == "FALSE"

    if (
        summary["network_backfill_enabled"] == "FALSE"
        and float(summary["median_history_depth_by_ticker_after_ingestion"] or 0.0) < 60
        and summary["final_status"].startswith("PARTIAL_PASS")
    ):
        assert summary["decision"] in {
            "HISTORICAL_OHLCV_NETWORK_BACKFILL_DISABLED_LOCAL_HISTORY_INSUFFICIENT",
            "HISTORICAL_OHLCV_CACHE_STILL_LIMITED_MANUAL_DATA_IMPORT_REQUIRED",
        }

    cache = read_csv(CACHE)
    if summary["local_source_found"] == "TRUE":
        keys = [(row["ticker"], row["as_of_date"]) for row in cache if row.get("ticker") and row.get("as_of_date")]
        assert len(keys) == len(set(keys))

    depth = read_csv(DEPTH)
    required_depth_fields = {
        "rsi14_ready",
        "kdj9_ready",
        "macd_26_9_ready",
        "bb20_ready",
        "ma20_ready",
        "ma50_ready",
        "volume_ma20_ready",
        "technical_score_ready",
    }
    assert depth
    assert required_depth_fields.issubset(depth[0].keys())
    if float(summary["median_history_depth_by_ticker_after_ingestion"] or 0.0) < 60:
        assert summary["true_reweighting_ready"] == "FALSE"

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_037_r1_contract()
    print("V21.037-R1 historical OHLCV ingestion tests passed")
