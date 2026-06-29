#!/usr/bin/env python
"""Tests for V21.040-R1 matured forward-return/context alignment."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_040_r1_matured_forward_return_extension_and_context_alignment.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_040_R1_MATURED_FORWARD_RETURN_EXTENSION_AND_CONTEXT_ALIGNMENT_REPORT.md"

SUMMARY = OUT_DIR / "V21_040_R1_MATURED_FORWARD_CONTEXT_ALIGNMENT_SUMMARY.csv"
WINDOW = OUT_DIR / "V21_040_R1_FORWARD_RETURN_MATURITY_BY_WINDOW.csv"
CONTEXT = OUT_DIR / "V21_040_R1_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERFORMANCE = OUT_DIR / "V21_040_R1_TECHNICAL_PERFORMANCE_BY_CONTEXT_WINDOW.csv"
PENDING = OUT_DIR / "V21_040_R1_PENDING_MATURITY_SCHEDULE.csv"
REPAIR = OUT_DIR / "V21_040_R1_FORWARD_CONTEXT_ALIGNMENT_REPAIR_QUEUE.csv"
VALIDATION = OUT_DIR / "V21_040_R1_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, WINDOW, CONTEXT, PERFORMANCE, PENDING, REPAIR, VALIDATION, REPORT]

OFFICIAL_GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv",
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_REALIZED_FORWARD_RETURNS.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_040_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.040-R1_MATURED_FORWARD_RETURN_EXTENSION_AND_CONTEXT_ALIGNMENT" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith((
        "PASS_V21_040_R1",
        "PARTIAL_PASS_V21_040_R1",
        "BLOCKED_V21_040_R1_INPUTS_MISSING",
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

    window_rows = read_csv(WINDOW)
    windows = {row["forward_window"] for row in window_rows}
    assert {"5D", "10D", "20D", "60D"}.issubset(windows)

    context_rows = read_csv(CONTEXT)
    assert context_rows
    for row in context_rows:
        if row["ticker_coverage_ratio"]:
            ratio = float(row["ticker_coverage_ratio"])
            if ratio > 0.80:
                assert row["selectivity_status"] == "BROADCAST_OVERWIDE"

    if summary["context_overbroadcast_detected"] == "TRUE":
        assert summary["shadow_gate_allowed"] == "FALSE"

    if int(float(summary["total_pending_observations"] or 0)) > 0:
        pending_rows = read_csv(PENDING)
        assert pending_rows
        assert pending_rows[0]["observation_id"]

    validation_rows = read_csv(VALIDATION)
    assert {row["validation_item"] for row in validation_rows} >= {
        "V21_039_SUMMARY_FOUND",
        "V21_038_TECHNICAL_SNAPSHOT_FOUND",
        "FORWARD_RETURN_SOURCES_FOUND",
        "NO_OFFICIAL_MUTATION",
        "RESEARCH_ONLY_TRUE",
        "DATA_TRUST_ALPHA_FALSE",
    }

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_040_r1_contract()
    print("V21.040-R1 matured forward/context alignment tests passed")
