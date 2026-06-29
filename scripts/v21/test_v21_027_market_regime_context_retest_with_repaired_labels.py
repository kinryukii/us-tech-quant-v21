#!/usr/bin/env python
"""Tests for V21.027 market regime context retest with repaired labels."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_027_market_regime_context_retest_with_repaired_labels.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_027_market_regime_context_retest_with_repaired_labels.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_REPORT.md"

REQUIRED_OUTPUTS = [
    OUT_DIR / "V21_027_V21_026_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv",
    OUT_DIR / "V21_027_CONTEXT_RETEST_UNIVERSE.csv",
    OUT_DIR / "V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv",
    OUT_DIR / "V21_027_STABLE_VS_UNSTABLE_REGIME_TEST.csv",
    OUT_DIR / "V21_027_TREND_COMBINATION_CONTEXT_TEST.csv",
    OUT_DIR / "V21_027_RISK_GATE_BY_REPAIRED_CONTEXT.csv",
    OUT_DIR / "V21_027_STATISTICAL_RANDOM_BASELINE_RETEST.csv",
    OUT_DIR / "V21_027_REMAINING_SOURCE_GAP_IMPACT_AUDIT.csv",
    OUT_DIR / "V21_027_CONTEXT_RETEST_DECISION.csv",
    OUT_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_SUMMARY.csv",
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_026_V21_024_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_026_EXISTING_REGIME_LABEL_FAILURE_AUDIT.csv",
    OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_INVENTORY.csv",
    OUT_DIR / "V21_026_PROPOSED_REGIME_LABEL_CONTRACT.csv",
    OUT_DIR / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv",
    OUT_DIR / "V21_026_PIT_VALIDATION_AUDIT.csv",
    OUT_DIR / "V21_026_LABEL_COVERAGE_IMPROVEMENT_AUDIT.csv",
    OUT_DIR / "V21_026_SOURCE_CONTRACT_GAP_TABLE.csv",
    OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_DECISION.csv",
    OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_REPORT.md",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]

ALLOWED_DECISIONS = {
    "REPAIRED_LABEL_CONTEXT_SIGNAL_CONFIRMED_RESEARCH_ONLY",
    "REPAIRED_LABEL_CONTEXT_SIGNAL_WEAK_BUT_PROMISING",
    "REPAIRED_LABEL_CONTEXT_SIGNAL_MIXED_OR_REGIME_DEPENDENT",
    "REPAIRED_LABEL_CONTEXT_RETEST_BLOCKED_BY_SOURCE_GAPS",
    "REPAIRED_LABEL_CONTEXT_RETEST_INCONCLUSIVE_REQUIRED_FIELDS_MISSING",
}

ALLOWED_NEXT = {
    "V21.025_WITHIN_REGIME_ALPHA_ONLY_AND_RISK_GATE_SHADOW_RESEARCH_PLAN",
    "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
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


def test_v21_027_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_026_source_contract_repair_decision"] == "MARKET_REGIME_SOURCE_CONTRACT_PARTIAL_REPAIR_READY_FOR_CONTEXT_RETEST"
    assert summary["v21_026_recommended_next_stage"] == "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS"
    assert summary["vix_and_event_labels_fabricated"] == "FALSE"
    assert summary["single_global_market_regime_adjusted_score_used"] == "FALSE"
    assert summary["official_use_allowed"] == "FALSE"
    assert summary["official_ranking_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_readiness_allowed"] == "FALSE"
    assert summary["official_weight_update_blocked"] == "TRUE"
    assert summary["data_trust_ranking_weight"] == "0"
    assert summary["data_trust_alpha_contribution"] == "0"
    assert summary["risk_additive_alpha_contribution"] == "0"
    assert summary["market_regime_additive_alpha_contribution"] == "0"
    assert summary["official_ranking_mutation_count"] == "0"
    assert summary["official_factor_weight_mutation_count"] == "0"
    assert summary["official_recommendation_count"] == "0"
    assert summary["trade_action_count"] == "0"
    assert summary["shadow_activation"] == "FALSE"
    assert summary["context_retest_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_027_RESEARCH_ONLY"

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["context_retest_decision"]

    ingest = read_csv(OUT_DIR / "V21_027_V21_026_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_026_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "recommended_next_stage_v21_027" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "derived_research_only_labels_generated" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "vix_and_event_labels_not_fabricated" and row["audit_passed"] == "TRUE" for row in ingest)

    coverage = read_csv(OUT_DIR / "V21_027_REPAIRED_LABEL_COVERAGE_AUDIT.csv")
    by_label = {row["label_name"]: row for row in coverage}
    for missing_label in ["high_vix", "low_vix", "FOMC_window", "CPI_window", "NFP_window", "earnings_season_window"]:
        assert missing_label not in by_label or by_label[missing_label]["label_source_status"] != "DERIVED_RESEARCH_ONLY"
    for label in ["QQQ_uptrend", "SPY_uptrend", "sector_uptrend", "stable_regime_window"]:
        assert label in by_label

    universe = read_csv(OUT_DIR / "V21_027_CONTEXT_RETEST_UNIVERSE.csv")
    assert universe
    for col in ["GLOBAL_ALPHA_ONLY_RANK", "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK", "WITHIN_REPAIRED_LABEL_RISK_GATED_RANK"]:
        assert col in universe[0]
    assert all(row["label_status"] == "DERIVED_RESEARCH_ONLY" for row in universe)
    assert all(row["global_market_regime_adjusted_score_used"] == "FALSE" for row in universe)

    perf = read_csv(OUT_DIR / "V21_027_REPAIRED_CONTEXT_RANK_BUCKET_PERFORMANCE.csv")
    rank_types = {row["rank_type"] for row in perf}
    assert "GLOBAL_ALPHA_ONLY_RANK" in rank_types
    assert "WITHIN_REPAIRED_LABEL_ALPHA_ONLY_RANK" in rank_types
    assert "WITHIN_REPAIRED_LABEL_RISK_GATED_RANK" in rank_types
    assert all(row["global_market_regime_adjusted_score_used"] == "FALSE" for row in perf)

    decision = read_csv(OUT_DIR / "V21_027_CONTEXT_RETEST_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["context_retest_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["official_use_allowed"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.name.startswith("V21_027_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final context retest decision",
        "v21.026 decision ingestion",
        "repaired label coverage audit",
        "context retest universe construction",
        "no official ranking mutation",
        "no production readiness",
        "no real-book readiness",
        "recommended next stage",
    ]:
        assert expected in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS",
        "official_use_allowed=FALSE",
        "official_ranking_readiness_allowed=FALSE",
        "official_weight_update_readiness_allowed=FALSE",
        "official_weight_update_blocked=TRUE",
        "data_trust_ranking_weight=0",
        "data_trust_alpha_contribution=0",
        "risk_additive_alpha_contribution=0",
        "market_regime_additive_alpha_contribution=0",
        "official_ranking_mutation_count=0",
        "official_factor_weight_mutation_count=0",
        "official_recommendation_count=0",
        "trade_action_count=0",
        "shadow_activation=FALSE",
        "research_only=TRUE",
    ]:
        assert expected in result.stdout


if __name__ == "__main__":
    test_v21_027_contract()
    test_wrapper_parseable()
    print("V21.027 market regime context retest with repaired labels tests passed")
