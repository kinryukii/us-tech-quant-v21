#!/usr/bin/env python
"""Tests for V21.042-R2 context-conditioned RSI repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_042_r2_context_conditioned_rsi_deemphasis_repair_and_maturity_refresh.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_042_R2_CONTEXT_CONDITIONED_RSI_DEEMPHASIS_REPAIR_AND_MATURITY_REFRESH_REPORT.md"

SUMMARY = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_RSI_REPAIR_SUMMARY.csv"
ACTION = OUT_DIR / "V21_042_R2_CONTEXT_BUCKET_RSI_ACTION_MAP.csv"
DEFINITION = OUT_DIR / "V21_042_R2_CONTEXT_CONDITIONED_VARIANT_DEFINITION.csv"
SCOPE = OUT_DIR / "V21_042_R2_EXPECTED_RETEST_SCOPE.csv"
CONCENTRATION = OUT_DIR / "V21_042_R2_EDGE_CONCENTRATION_REPAIR_AUDIT.csv"
RECOMMENDATION = OUT_DIR / "V21_042_R2_RETEST_RECOMMENDATION.csv"
VALIDATION = OUT_DIR / "V21_042_R2_VALIDATION_MATRIX.csv"

REQUIRED = [SUMMARY, ACTION, DEFINITION, SCOPE, CONCENTRATION, RECOMMENDATION, VALIDATION, REPORT]

OFFICIAL_AND_SHADOW_GUARD_PATHS = [
    OUT_DIR / "V21_038_R1_TECHNICAL_SUBFACTOR_SNAPSHOT.csv",
    OUT_DIR / "V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_SUMMARY.csv",
    OUT_DIR / "V21_042_R1_SHADOW_GATE_REVIEW_SUMMARY.csv",
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


def test_v21_042_r2_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.042-R2_CONTEXT_CONDITIONED_RSI_DEEMPHASIS_REPAIR_AND_MATURITY_REFRESH" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_042_R2", "PARTIAL_PASS_V21_042_R2", "BLOCKED_V21_042_R2"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["official_adoption_allowed"] == "FALSE"
    assert summary["shadow_dry_run_candidate_allowed"] == "FALSE"
    assert summary["shadow_gate_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"

    if summary["context_conditioned_candidate_created"] == "TRUE":
        assert summary["context_conditioned_candidate_name"] == "RSI_DEEMPHASIZED_CONTEXT_CONDITIONED_R4_R2"

    action_rows = read_csv(ACTION)
    assert action_rows
    for row in action_rows:
        if row["upstream_context_pass"] == "FALSE":
            assert row["rsi_action"] != "APPLY_RSI_DEEMPHASIS"
    assert any(row["upstream_context_pass"] == "TRUE" and row["rsi_action"] == "APPLY_RSI_DEEMPHASIS" for row in action_rows)

    rec_rows = read_csv(RECOMMENDATION)
    assert rec_rows
    assert all(row["shadow_dry_run_candidate_allowed_now"] == "FALSE" for row in rec_rows)
    assert all(row["shadow_gate_allowed_now"] == "FALSE" for row in rec_rows)
    assert all(row["official_use_allowed"] == "FALSE" for row in rec_rows)

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_042_r2_contract()
    print("V21.042-R2 context-conditioned RSI repair tests passed")
