#!/usr/bin/env python
"""Tests for V21.033 shadow ledger matured result evaluator."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_033_shadow_ledger_matured_result_evaluator.py"
OUT_DIR = ROOT / "outputs" / "v21" / "shadow_observation"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR_REPORT.md"

REQUIRED = [
    OUT_DIR / "V21_033_MATURED_RESULT_EVALUATION_SUMMARY.csv",
    OUT_DIR / "V21_033_CONTEXT_PERFORMANCE_EVALUATION.csv",
    OUT_DIR / "V21_033_CONTEXT_OVERLAP_AUDIT.csv",
    OUT_DIR / "V21_033_CONTEXT_DISCRIMINATION_AUDIT.csv",
    OUT_DIR / "V21_033_FORWARD_WINDOW_EVALUATION.csv",
    OUT_DIR / "V21_033_SHADOW_EVALUATOR_DECISION.csv",
    REPORT,
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v21_033_contract() -> None:
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21_033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR" in result.stdout
    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(OUT_DIR / "V21_033_MATURED_RESULT_EVALUATION_SUMMARY.csv")[0]
    assert summary["matured_row_count"] == "360"
    assert summary["pending_row_count"] == "180"
    assert summary["price_missing_row_count"] == "0"
    assert summary["current_daily_observation_allowed"] == "FALSE"
    assert summary["research_only"] == "TRUE"

    v30 = read_csv(OUT_DIR / "V21_030_SHADOW_OBSERVATION_LEDGER_MATURITY_TRACKER_SUMMARY.csv")[0]
    assert v30["final_status"] == "PASS_V21_030_SHADOW_LEDGER_MATURITY_TRACKER_READY_WITH_MATURED_RESULTS"

    decision = read_csv(OUT_DIR / "V21_033_SHADOW_EVALUATOR_DECISION.csv")
    assert len(decision) == 1
    row = decision[0]
    assert row["official_use_allowed"] == "FALSE"
    assert row["official_ranking_readiness_allowed"] == "FALSE"
    assert row["official_weight_update_readiness_allowed"] == "FALSE"
    assert row["official_weight_update_blocked"] == "TRUE"
    assert row["broker_execution_supported"] == "FALSE"
    assert row["shadow_activation"] == "FALSE"
    assert row["research_only"] == "TRUE"
    assert row["selected_recommended_next_stage"] == "TRUE"

    overlap = read_csv(OUT_DIR / "V21_033_CONTEXT_OVERLAP_AUDIT.csv")
    discr = read_csv(OUT_DIR / "V21_033_CONTEXT_DISCRIMINATION_AUDIT.csv")[0]
    assert overlap
    assert discr
    if discr["all_context_metrics_identical"] == "TRUE":
        assert discr["alpha_interpretation_allowed"] == "FALSE"
        assert row["context_alpha_interpretation_allowed"] == "FALSE"

    report = REPORT.read_text(encoding="utf-8").lower()
    assert "fallback limitation" in report
    assert "context overlap warning" in report
    assert "recommended next stage" in report


if __name__ == "__main__":
    test_v21_033_contract()
    print("V21.033 shadow ledger matured result evaluator tests passed")
