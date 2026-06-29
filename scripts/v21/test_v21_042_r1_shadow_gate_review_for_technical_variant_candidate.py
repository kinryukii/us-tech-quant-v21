#!/usr/bin/env python
"""Tests for V21.042-R1 shadow gate review."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_042_r1_shadow_gate_review_for_technical_variant_candidate.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_042_R1_SHADOW_GATE_REVIEW_FOR_TECHNICAL_VARIANT_CANDIDATE_REPORT.md"

SUMMARY = OUT_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_SUMMARY.csv"
CONTEXT = OUT_DIR / "V21_042_R1_CANDIDATE_STABILITY_BY_CONTEXT_BUCKET.csv"
WINDOW = OUT_DIR / "V21_042_R1_CANDIDATE_STABILITY_BY_FORWARD_WINDOW.csv"
RANK = OUT_DIR / "V21_042_R1_CANDIDATE_RANK_DELTA_STABILITY_AUDIT.csv"
CONCENTRATION = OUT_DIR / "V21_042_R1_CONTEXT_BUCKET_EDGE_CONCENTRATION_AUDIT.csv"
READINESS = OUT_DIR / "V21_042_R1_SHADOW_DRY_RUN_READINESS_MATRIX.csv"
RECOMMENDATION = OUT_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_RECOMMENDATION.csv"
VALIDATION = OUT_DIR / "V21_042_R1_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, CONTEXT, WINDOW, RANK, CONCENTRATION, READINESS, RECOMMENDATION, VALIDATION, REPORT]

OFFICIAL_AND_SHADOW_GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv",
    OUT_DIR / "V21_040_R4_CONTEXT_BUCKET_CONSOLIDATION_SUMMARY.csv",
    OUT_DIR / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_REALIZED_FORWARD_RETURNS.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_AND_SHADOW_GUARD_PATHS if path.exists()}


def test_v21_042_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.042-R1_SHADOW_GATE_REVIEW_FOR_TECHNICAL_VARIANT_CANDIDATE" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_042_R1", "PARTIAL_PASS_V21_042_R1", "BLOCKED_V21_042_R1"))
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

    if summary["candidate_from_v21_041"] == "TRUE":
        assert summary["candidate_variant_name"] == "RSI_DEEMPHASIZED_R4"

    required_gates = [
        "context_stability_pass",
        "window_stability_pass",
        "rank_delta_stability_pass",
        "downside_stability_pass",
        "turnover_guardrail_pass",
        "benchmark_robustness_pass",
    ]
    if summary["stability_review_pass"] == "TRUE":
        assert all(summary[field] == "TRUE" for field in required_gates)
        assert summary["overfit_warning_detected"] == "FALSE"
        assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    assert summary["shadow_dry_run_candidate_allowed"] == summary["stability_review_pass"]

    rec_rows = read_csv(RECOMMENDATION)
    assert rec_rows
    assert all(row["shadow_gate_allowed_now"] == "FALSE" for row in rec_rows)
    assert all(row["official_use_allowed"] == "FALSE" for row in rec_rows)

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_042_r1_contract()
    print("V21.042-R1 shadow gate review tests passed")
