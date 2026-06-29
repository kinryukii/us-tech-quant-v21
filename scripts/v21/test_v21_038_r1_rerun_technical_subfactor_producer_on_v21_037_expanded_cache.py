#!/usr/bin/env python
"""Tests for V21.038-R1 technical subfactor rerun."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_038_r1_rerun_technical_subfactor_producer_on_v21_037_expanded_cache.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_038_R1_RERUN_TECHNICAL_SUBFACTOR_PRODUCER_ON_V21_037_EXPANDED_CACHE_REPORT.md"
CACHE = ROOT / "inputs" / "v21" / "historical_ohlcv_cache" / "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"

SUMMARY = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv"
SNAPSHOT = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
COVERAGE_TICKER = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_TICKER.csv"
COVERAGE_DATE = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_DATE.csv"
HYGIENE = OUT_DIR / "V21_038_R1_TICKER_HYGIENE_EXCLUSION_REPORT.csv"
VALIDATION = OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, SNAPSHOT, COVERAGE_TICKER, COVERAGE_DATE, HYGIENE, VALIDATION, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_SUMMARY.csv",
    ROOT / "inputs" / "v21" / "historical_ohlcv_cache" / "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_038_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.038-R1_RERUN_TECHNICAL_SUBFACTOR_PRODUCER_ON_V21_037_EXPANDED_CACHE" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith((
        "PASS_V21_038_R1",
        "PARTIAL_PASS_V21_038_R1",
        "BLOCKED_V21_038_R1_V21_037_CACHE_MISSING",
    ))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    hygiene = read_csv(HYGIENE)
    for pseudo in {"TRUE", "FALSE"}:
        rows = [row for row in hygiene if row["normalized_ticker_value"] == pseudo]
        assert all(row["action_taken"] == "EXCLUDED_FROM_TECHNICAL_SUBFACTOR_PRODUCTION" for row in rows)

    snapshot = read_csv(SNAPSHOT)
    required_snapshot_fields = {
        "rsi_14",
        "kdj_k",
        "macd_line",
        "bb_position",
        "ma20_distance",
        "volume_ratio",
        "volatility_20",
        "momentum_20",
        "technical_score_normalized",
    }
    assert required_snapshot_fields.issubset(snapshot[0].keys())

    if CACHE.exists() and int(summary["input_rows"] or 0) > 1000:
        for field in [
            "rsi_coverage_ratio",
            "kdj_coverage_ratio",
            "macd_coverage_ratio",
            "bb_coverage_ratio",
            "ma_ema_coverage_ratio",
            "volume_coverage_ratio",
            "technical_score_coverage_ratio",
        ]:
            assert float(summary[field]) > 0.0, field

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_038_r1_contract()
    print("V21.038-R1 technical subfactor rerun tests passed")
