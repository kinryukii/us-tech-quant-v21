#!/usr/bin/env python
"""Tests for V21.041-R1 R4-context technical reweighting retest."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_041_r1_technical_reweighting_retest_with_r4_context_buckets_research_only.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R4_CONTEXT_BUCKETS_REPORT.md"

SUMMARY = OUT_DIR / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_SUMMARY.csv"
PERFORMANCE = OUT_DIR / "V21_041_R1_VARIANT_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv"
SCORECARD = OUT_DIR / "V21_041_R1_VARIANT_AGGREGATE_SCORECARD.csv"
RANK_DELTA = OUT_DIR / "V21_041_R1_VARIANT_RANK_DELTA_AUDIT.csv"
WEIGHTS = OUT_DIR / "V21_041_R1_TECHNICAL_SUBFACTOR_WEIGHT_VARIANTS.csv"
RECOMMENDATION = OUT_DIR / "V21_041_R1_SHADOW_GATE_RECOMMENDATION.csv"
VALIDATION = OUT_DIR / "V21_041_R1_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, PERFORMANCE, SCORECARD, RANK_DELTA, WEIGHTS, RECOMMENDATION, VALIDATION, REPORT]

OFFICIAL_GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv",
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_VARIANT_BACKTEST_BY_WINDOW.csv",
    OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv",
    OUT_DIR / "V21_040_R4_CANONICAL_CONTEXT_LEDGER.csv",
    OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_SELECTIVITY_AND_MATURITY_AUDIT.csv",
    OUT_DIR / "V21_040_R4_TECHNICAL_PERFORMANCE_BY_CONTEXT_BUCKET_WINDOW.csv",
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


def test_v21_041_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.041-R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R4_CONTEXT_BUCKETS_RESEARCH_ONLY" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_041_R1", "PARTIAL_PASS_V21_041_R1", "BLOCKED_V21_041_R1"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["official_adoption_allowed"] == "FALSE"
    assert summary["shadow_gate_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    if summary["final_status"] != "BLOCKED_V21_041_R1_R4_GATE_NOT_READY":
        assert summary["r4_retest_allowed"] == "TRUE"

    scorecard = read_csv(SCORECARD)
    assert any(row["variant_name"] == "BASELINE_TRUE_TECHNICAL" for row in scorecard)
    if summary["final_status"].startswith(("PASS", "PARTIAL")):
        assert int(float(summary["variants_tested_count"])) >= 8

    selected_rows = [row for row in scorecard if row["variant_selected"] == "TRUE"]
    for row in selected_rows:
        assert row["positive_excess_gate_pass"] == "TRUE"
        assert row["hit_rate_gate_pass"] == "TRUE"
        assert row["downside_gate_pass"] == "TRUE"
        assert row["context_breadth_gate_pass"] == "TRUE"
        assert row["rank_change_gate_pass"] == "TRUE"

    if summary["best_research_variant_selected"] == "FALSE":
        assert summary["best_research_variant_name"] == ""

    rec_rows = read_csv(RECOMMENDATION)
    assert rec_rows
    assert all(row["shadow_gate_allowed_now"] == "FALSE" for row in rec_rows)

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_041_r1_contract()
    print("V21.041-R1 R4-context technical reweighting retest tests passed")
