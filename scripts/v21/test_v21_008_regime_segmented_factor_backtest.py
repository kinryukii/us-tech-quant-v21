#!/usr/bin/env python
"""Tests for V21.008 regime-segmented factor backtest."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_008_regime_segmented_factor_backtest.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_008_regime_segmented_factor_backtest.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_008_V21_007_BLOCKER_INGEST_AUDIT.csv",
    OUT_DIR / "V21_008_REGIME_LABEL_INVENTORY.csv",
    OUT_DIR / "V21_008_REGIME_RANK_BUCKET_PERFORMANCE.csv",
    OUT_DIR / "V21_008_REGIME_FACTOR_FAMILY_IC_STATS.csv",
    OUT_DIR / "V21_008_REGIME_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_008_REGIME_BENCHMARK_COMPARISON.csv",
    OUT_DIR / "V21_008_REGIME_TRANSITION_CONFLICT_AUDIT.csv",
    OUT_DIR / "V21_008_REGIME_RISK_OVERHEAT_BEHAVIOR.csv",
    OUT_DIR / "V21_008_REGIME_SEGMENTATION_DECISION.csv",
    OUT_DIR / "V21_008_REGIME_SEGMENTED_BACKTEST_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_007_V21_006_VERDICT_INGEST_AUDIT.csv",
    OUT_DIR / "V21_007_OUTLIER_DEPENDENCY_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_REGIME_DEPENDENCY_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_FACTOR_FAMILY_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RANK_ARCHITECTURE_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_RISK_OVERHEAT_REPAIR_DIAGNOSIS.csv",
    OUT_DIR / "V21_007_WEIGHT_UPDATE_BLOCKER_DECISION.csv",
    OUT_DIR / "V21_007_REPAIR_ROADMAP.csv",
    OUT_DIR / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER_REPORT.md",
    OUT_DIR / "V21_006_RANK_BUCKET_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_FACTOR_FAMILY_IC_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_RANDOM_BASELINE_COMPARISON.csv",
    OUT_DIR / "V21_006_SUBSAMPLE_ROBUSTNESS_STATS.csv",
    OUT_DIR / "V21_006_OUTLIER_CONCENTRATION_AUDIT.csv",
    OUT_DIR / "V21_006_RISK_OVERHEAT_ROBUSTNESS_TEST.csv",
    OUT_DIR / "V21_006_BENCHMARK_SIGNIFICANCE_STATS.csv",
    OUT_DIR / "V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
    OUT_DIR / "V21_005_REGIME_CONDITIONED_PERFORMANCE_STATS.csv",
    OUT_DIR / "V21_005_FACTOR_FAMILY_IC_STATS.csv",
    OUT_DIR / "V21_005_RANK_BUCKET_FORWARD_RETURN_STATS.csv",
    OUT_DIR / "V21_005_BENCHMARK_COMPARISON_STATS.csv",
]

ALLOWED_NEXT_STAGES = {
    "V21.009_OUTLIER_NEUTRALIZED_FACTOR_BACKTEST",
    "V21.010_RISK_OVERHEAT_FALSE_BLOCK_REPAIR",
    "V21.011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST",
    "V21.012_SECTOR_NEUTRAL_AND_THEME_CONCENTRATION_AUDIT",
    "V21.013_REGIME_AWARE_SHADOW_SCORING_EXPERIMENT_PLAN",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def snapshot(paths: list[Path]) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in paths if path.exists()}


def run_stage() -> subprocess.CompletedProcess[str]:
    before = snapshot(INPUTS)
    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    after = snapshot(INPUTS)
    changed = [path for path, mtime in before.items() if after.get(path) != mtime]
    assert not changed, f"input files modified: {changed}"
    return result


def test_v21_008_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST" in result.stdout

    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_008_REGIME_SEGMENTED_BACKTEST_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_007_weight_update_blocker_decision"] == "WEIGHT_UPDATE_BLOCKED_REGIME_SEGMENTATION_REQUIRED"
    assert summary["official_weight_update_allowed"] == "FALSE"
    assert summary["research_only_limited_weight_experiment_allowed"] == "FALSE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert int(summary["inventoried_regime_label_count"]) >= 1
    assert summary["regime_segmentation_decision"]
    assert summary["recommended_next_stage"] in ALLOWED_NEXT_STAGES

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["regime_segmentation_decision"]

    audit = read_csv(OUT_DIR / "V21_008_V21_007_BLOCKER_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_007_blocker_decision_ingested" and row["audit_passed"] == "TRUE" for row in audit)
    assert any(row["audit_item"] == "official_weight_update_allowed_false" and row["audit_passed"] == "TRUE" for row in audit)

    inventory = read_csv(OUT_DIR / "V21_008_REGIME_LABEL_INVENTORY.csv")
    assert any(row["sample_adequacy"] != "MISSING_REGIME_LABEL_SOURCE" for row in inventory)

    decision = read_csv(OUT_DIR / "V21_008_REGIME_SEGMENTATION_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(selected) == 1
    assert selected[0]["recommended_next_stage"] == summary["recommended_next_stage"]
    assert selected[0]["official_use_allowed"] == "FALSE"

    ic_rows = read_csv(OUT_DIR / "V21_008_REGIME_FACTOR_FAMILY_IC_STATS.csv")
    data_trust = [row for row in ic_rows if row["factor_family"] == "DATA_TRUST"]
    assert data_trust
    assert all(row["data_trust_alpha_contribution"] == "0" for row in data_trust)

    random_rows = read_csv(OUT_DIR / "V21_008_REGIME_RANDOM_BASELINE_COMPARISON.csv")
    assert random_rows
    assert all(row["deterministic_seed"] for row in random_rows)
    assert summary["random_seed_base"] == "21008"

    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final regime segmentation decision",
        "v21.007 blocker ingestion",
        "data_trust zero-alpha confirmation",
        "explicit blocked actions",
        "no production readiness",
        "recommended next stage",
    ]:
        assert expected in report_text

    script_text = SCRIPT.read_text(encoding="utf-8").lower()
    for blocked_term in ["yfinance", "requests.", "urllib.request", "http.client", "socket.", "download("]:
        assert blocked_term not in script_text, f"network access term found: {blocked_term}"


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    for expected in [
        "STAGE_NAME=V21_008_REGIME_SEGMENTED_FACTOR_BACKTEST",
        "final_status=",
        "regime_segmentation_decision=",
        "official_weight_update_allowed=FALSE",
        "research_only_limited_weight_experiment_allowed=FALSE",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_factor_weight_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_008_contract()
    test_wrapper_parseable()
    print("V21.008 regime-segmented factor backtest tests passed")
