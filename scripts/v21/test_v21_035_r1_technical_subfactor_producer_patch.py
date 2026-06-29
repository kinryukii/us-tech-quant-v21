#!/usr/bin/env python
"""Tests for V21.035-R1 technical subfactor producer patch."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_035_r1_technical_subfactor_producer_patch.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_PATCH_REPORT.md"

SUMMARY = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_SUMMARY.csv"
SNAPSHOT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv"
COV_TICKER = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_TICKER.csv"
COV_DATE = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_COVERAGE_BY_DATE.csv"
INPUT_AUDIT = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_INPUT_AUDIT.csv"
VALIDATION = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, SNAPSHOT, COV_TICKER, COV_DATE, INPUT_AUDIT, VALIDATION, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_REPAIR_SUMMARY.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_035_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.035-R1_TECHNICAL_SUBFACTOR_PRODUCER_PATCH" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_035_R1", "PARTIAL_PASS_V21_035_R1", "BLOCKED_V21_035_R1_NO_USABLE_OHLCV_SOURCE"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    snapshot_rows = read_csv(SNAPSHOT)
    snapshot_fields = set(snapshot_rows[0].keys())
    if summary["local_price_source_found"] == "TRUE":
        for field in ["rsi_14", "kdj_k", "macd_line", "bb_position", "ma20_distance", "volume_ratio", "technical_score_normalized"]:
            assert field in snapshot_fields
    assert any(row["row_quality_status"] == "WARMUP_INSUFFICIENT_HISTORY" for row in snapshot_rows) or summary["local_price_source_found"] == "FALSE"

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_035_r1_contract()
    print("V21.035-R1 technical subfactor producer patch tests passed")
