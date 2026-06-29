#!/usr/bin/env python
"""Tests for V21.034-R1 true technical subfactor repair stage."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_034_r1_true_technical_subfactor_capture_and_selection_logic_repair.py"
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_CAPTURE_AND_SELECTION_LOGIC_REPAIR_REPORT.md"

SUMMARY = OUT_DIR / "V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_REPAIR_SUMMARY.csv"
SOURCE_MAP = OUT_DIR / "V21_034_R1_TECHNICAL_SUBFACTOR_SOURCE_MAP.csv"
READINESS = OUT_DIR / "V21_034_R1_TRUE_REWEIGHTING_READINESS_MATRIX.csv"
RULES = OUT_DIR / "V21_034_R1_VARIANT_SELECTION_RULE_REPAIR_SPEC.csv"
QUEUE = OUT_DIR / "V21_034_R1_TECHNICAL_REPAIR_QUEUE.csv"

REQUIRED = [SUMMARY, SOURCE_MAP, READINESS, RULES, QUEUE, REPORT]

OFFICIAL_GUARD_PATHS = [
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_014_RESCALING_VARIANT_SCORE_OUTPUT.csv",
    ROOT / "outputs" / "v21" / "factor_backtest" / "V21_020_RESCALING_CANDIDATE_CONFIRMATION_DECISION.csv",
    ROOT / "outputs" / "v21" / "shadow_observation" / "V21_030_R1_CURRENT_DAILY_MATURITY_STATUS_LEDGER.csv",
    ROOT / "outputs" / "v21" / "ablation" / "V21_002_BASELINE_JOINED_FACTOR_OUTCOME_ROWS.csv",
    ROOT / "outputs" / "v21" / "factors" / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_SUMMARY.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mtimes() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in OFFICIAL_GUARD_PATHS if path.exists()}


def test_v21_034_r1_contract() -> None:
    before = mtimes()
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "STAGE_NAME=V21.034-R1_TRUE_TECHNICAL_SUBFACTOR_CAPTURE_AND_SELECTION_LOGIC_REPAIR" in result.stdout

    for path in REQUIRED:
        assert path.exists(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"

    summary = read_csv(SUMMARY)[0]
    assert summary["final_status"].startswith(("PASS_V21_034_R1", "PARTIAL_PASS_V21_034_R1"))
    assert summary["research_only"] == "TRUE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_weight_mutation_allowed"] == "FALSE"
    assert summary["official_ranking_mutation_allowed"] == "FALSE"
    assert summary["trade_action_allowed"] == "FALSE"
    assert summary["broker_execution_allowed"] == "FALSE"
    assert summary["real_book_mutation_allowed"] == "FALSE"
    assert summary["data_trust_alpha_weight_allowed"] == "FALSE"
    assert summary["upstream_issue_confirmed"] == "TRUE"
    assert summary["proxy_reweighting_allowed"] == "FALSE"
    assert summary["no_op_variant_selection_blocked"] == "TRUE"
    assert summary["zero_excess_best_selection_blocked"] == "TRUE"
    assert summary["rank_unchanged_best_selection_blocked"] == "TRUE"
    assert summary["top_bucket_unchanged_best_selection_blocked"] == "TRUE"

    rules = read_csv(RULES)
    rule_names = {row["rule_name"] for row in rules}
    assert "BEST_VARIANT_MUST_HAVE_POSITIVE_EXCESS_VS_BASELINE" in rule_names
    assert "PROXY_NOOP_CANNOT_BE_BEST_VARIANT" in rule_names

    source_map = read_csv(SOURCE_MAP)
    assert any(row["subfactor_name"] == "RSI" for row in source_map)
    assert any(row["subfactor_name"] == "FORWARD_RETURN_20D" for row in source_map)

    after = mtimes()
    assert before == after

    report = REPORT.read_text(encoding="utf-8")
    assert summary["decision"] in report
    assert "official mutation remains blocked" in report.lower()


if __name__ == "__main__":
    test_v21_034_r1_contract()
    print("V21.034-R1 true technical subfactor repair tests passed")
