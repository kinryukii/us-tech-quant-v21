#!/usr/bin/env python
"""Tests for V21.040-R4 context bucket consolidation and retest gate."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_040_r4_context_bucket_consolidation_and_retest_eligibility_gate.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_AND_RETEST_ELIGIBILITY_GATE_REPORT.md"

SUMMARY = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv"
LEDGER = OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv"
MAPPING = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_MAPPING.csv"
AUDIT = OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_SELECTIVITY_AND_MATURITY_AUDIT.csv"
PERFORMANCE = OUT_DIR / "V21_040_R4_TECHNICAL_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
GATE = OUT_DIR / "V21_040_R4_RETEST_ELIGIBILITY_GATE.csv"
QUEUE = OUT_DIR / "V21_040_R4_CONTEXT_REPAIR_QUEUE.csv"

REQUIRED = [SUMMARY, LEDGER, MAPPING, AUDIT, PERFORMANCE, GATE, QUEUE, REPORT]

OFFICIAL_GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv",
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv",
    OUT_DIR / "V21_040_R3_CONTEXT_SELECTIVITY_REPAIR_SUMMARY.csv",
    OUT_DIR / "V21_040_R3_CANONICAL_FORWARD_RETURN_LEDGER_REPAIRED.csv",
    OUT_DIR / "V21_040_R3_CONTEXT_SELECTIVITY_AND_MATURITY_AUDIT.csv",
    OUT_DIR / "V21_040_R3_TECHNICAL_PERFORMANCE_BY_R3_CONTEXT_WINDOW.csv",
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


def test_v21_040_r4_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.040-R4_CONTEXT_BUCKET_CONSOLIDATION_AND_RETEST_ELIGIBILITY_GATE" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith((
        "PASS_V21_040_R4",
        "PARTIAL_PASS_V21_040_R4",
        "BLOCKED_V21_040_R4_INPUTS_MISSING",
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
    assert summary["shadow_gate_allowed"] == "FALSE"

    ledger_rows = read_csv(LEDGER)
    assert ledger_rows
    for field in {
        "observation_id",
        "ticker",
        "as_of_date",
        "forward_window",
        "maturity_status",
        "realized_forward_return",
        "r3_context_label",
        "canonical_context_bucket",
    }:
        assert field in ledger_rows[0]

    audit_rows = read_csv(AUDIT)
    assert audit_rows
    interpretable = 0
    for row in audit_rows:
        if row["canonical_context_bucket"] in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"}:
            assert row["alpha_interpretation_allowed"] == "FALSE"
        if row["ticker_coverage_ratio"]:
            ratio = float(row["ticker_coverage_ratio"])
            if ratio > 0.80:
                assert row["selectivity_status"] == "BROADCAST_OVERWIDE"
                assert row["alpha_interpretation_allowed"] == "FALSE"
        if row["selectivity_status"] == "BROADCAST_OVERWIDE":
            assert row["alpha_interpretation_allowed"] == "FALSE"
        if row["alpha_interpretation_allowed"] == "TRUE":
            interpretable += 1
            assert row["selectivity_status"] == "SELECTIVE"
            assert row["maturity_status"] == "SUFFICIENT"
            assert row["top20_sample_status"] == "SUFFICIENT"

    perf_rows = read_csv(PERFORMANCE)
    assert perf_rows
    for row in perf_rows:
        if row["canonical_context_bucket"] in {"MISSING_CONTEXT_LABEL", "UNRESOLVED_CONTEXT"}:
            assert row["interpretation_allowed"] == "FALSE"
        if "BROADCAST_OVERWIDE" in row["interpretation_block_reason"]:
            assert row["interpretation_allowed"] == "FALSE"
        if row["rows_used"] and int(float(row["rows_used"])) < 30:
            assert row["interpretation_allowed"] == "FALSE"

    if summary["technical_reweighting_retest_allowed"] == "TRUE":
        assert interpretable >= 1

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_040_r4_contract()
    print("V21.040-R4 context bucket consolidation tests passed")
