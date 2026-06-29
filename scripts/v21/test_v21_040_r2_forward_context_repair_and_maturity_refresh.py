#!/usr/bin/env python
"""Tests for V21.040-R2 forward context repair and maturity refresh."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_040_r2_forward_context_repair_and_maturity_refresh.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_040_R2_FORWARD_CONTEXT_REPAIR_AND_MATURITY_REFRESH_REPORT.md"

SUMMARY = OUT_DIR / "V21_040_R2_FORWARD_CONTEXT_REPAIR_SUMMARY.csv"
LEDGER = OUT_DIR / "V21_040_R2_CANONICAL_FORWARD_RETURN_LEDGER.csv"
MAPPING = OUT_DIR / "V21_040_R2_CONTEXT_REPAIR_MAPPING.csv"
CONTEXT = OUT_DIR / "V21_040_R2_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERFORMANCE = OUT_DIR / "V21_040_R2_TECHNICAL_PERFORMANCE_BY_REPAIRED_CONTEXT_WINDOW.csv"
PENDING = OUT_DIR / "V21_040_R2_PENDING_MATURITY_REFRESH.csv"
REPAIR = OUT_DIR / "V21_040_R2_FORWARD_CONTEXT_REPAIR_QUEUE.csv"
VALIDATION = OUT_DIR / "V21_040_R2_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, LEDGER, MAPPING, CONTEXT, PERFORMANCE, PENDING, REPAIR, VALIDATION, REPORT]

OFFICIAL_GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv",
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv",
    OUT_DIR / "V21_040_R1_MATURED_FORWARD_CONTEXT_ALIGNMENT_SUMMARY.csv",
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


def test_v21_040_r2_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.040-R2_FORWARD_CONTEXT_REPAIR_AND_MATURITY_REFRESH" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith((
        "PASS_V21_040_R2",
        "PARTIAL_PASS_V21_040_R2",
        "BLOCKED_V21_040_R2_INPUTS_MISSING",
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

    ledger_rows = read_csv(LEDGER)
    assert ledger_rows
    for field in {
        "observation_id",
        "ticker",
        "as_of_date",
        "forward_window",
        "maturity_status",
        "realized_forward_return",
        "original_context_label",
        "repaired_context_label",
    }:
        assert field in ledger_rows[0]

    context_rows = read_csv(CONTEXT)
    assert context_rows
    for row in context_rows:
        if row["repaired_context_label"] == "MISSING_CONTEXT_LABEL":
            assert row["alpha_interpretation_allowed"] == "FALSE"
        if row["ticker_coverage_ratio"]:
            ratio = float(row["ticker_coverage_ratio"])
            if ratio > 0.80:
                assert row["selectivity_status"] == "BROADCAST_OVERWIDE"
                assert row["alpha_interpretation_allowed"] == "FALSE"
        if row["maturity_status"] == "LOW_CONTEXT_MATURITY":
            assert row["alpha_interpretation_allowed"] == "FALSE"

    perf_rows = read_csv(PERFORMANCE)
    assert perf_rows
    for row in perf_rows:
        if row["repaired_context_label"] == "MISSING_CONTEXT_LABEL":
            assert row["interpretation_allowed"] == "FALSE"
        if "BROADCAST_OVERWIDE" in row["interpretation_block_reason"]:
            assert row["interpretation_allowed"] == "FALSE"
        if "LOW_CONTEXT_MATURITY" in row["interpretation_block_reason"]:
            assert row["interpretation_allowed"] == "FALSE"

    if summary["context_overbroadcast_after"] == "TRUE":
        assert summary["shadow_gate_allowed"] == "FALSE"

    if int(float(summary["total_pending_observations"] or 0)) > 0:
        pending_rows = read_csv(PENDING)
        assert pending_rows
        assert pending_rows[0]["observation_id"]

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_040_r2_contract()
    print("V21.040-R2 forward context repair tests passed")
