#!/usr/bin/env python
"""Tests for V21.026 market regime source contract repair."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v21" / "v21_026_market_regime_source_contract_repair.py"
WRAPPER = ROOT / "scripts" / "v21" / "run_v21_026_market_regime_source_contract_repair.ps1"
OUT_DIR = ROOT / "outputs" / "v21" / "factor_backtest"
REPORT = ROOT / "outputs" / "v21" / "read_center" / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_REPORT.md"

REQUIRED_OUTPUTS = [
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
    REPORT,
]

INPUTS = [
    OUT_DIR / "V21_024_V21_022_DECISION_INGEST_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_CONTEXT_SOURCE_CONTRACT_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_LABEL_ADEQUACY_CONFLICT_AUDIT.csv",
    OUT_DIR / "V21_024_TRUE_CONTEXT_ONLY_LOGIC_REPAIR_AUDIT.csv",
    OUT_DIR / "V21_024_REGIME_SPECIFIC_SCORING_CONTEXT_TEST.csv",
    OUT_DIR / "V21_024_REGIME_SPECIFIC_RISK_GATE_INTERACTION_TEST.csv",
    OUT_DIR / "V21_024_REGIME_CONTEXT_STATISTICAL_CONFIRMATION.csv",
    OUT_DIR / "V21_024_REGIME_TRANSITION_CONFLICT_EXCLUSION_TEST.csv",
    OUT_DIR / "V21_024_CONTEXT_LOGIC_REPAIR_DECISION.csv",
    OUT_DIR / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_SUMMARY.csv",
    ROOT / "outputs" / "v21" / "read_center" / "V21_024_MARKET_REGIME_CONTEXT_LOGIC_REPAIR_REPORT.md",
    OUT_DIR / "V21_005_OBSERVATION_SELECTION_AUDIT.csv",
]

ALLOWED_DECISIONS = {
    "MARKET_REGIME_SOURCE_CONTRACT_REPAIRED_RESEARCH_ONLY",
    "MARKET_REGIME_SOURCE_CONTRACT_PARTIAL_REPAIR_READY_FOR_CONTEXT_RETEST",
    "MARKET_REGIME_SOURCE_CONTRACT_REQUIRES_NEW_DATA_PRODUCERS",
    "MARKET_REGIME_SOURCE_CONTRACT_INCONCLUSIVE_REQUIRED_FILES_MISSING",
    "MARKET_REGIME_SOURCE_CONTRACT_NOT_REPAIRABLE_WITH_CURRENT_DATA",
}

ALLOWED_NEXT = {
    "V21.027_MARKET_REGIME_CONTEXT_RETEST_WITH_REPAIRED_LABELS",
    "V21.028_MARKET_REGIME_DATA_PRODUCER_IMPLEMENTATION",
    "V21.019_MORE_MATURED_OBSERVATION_ACCUMULATION_PLAN",
    "V21.015_NONLINEAR_FACTOR_INTERACTION_RESEARCH_PROTOTYPE",
    "V21.017_OVERHEAT_ENTRY_TIMING_AND_FALSE_BLOCK_REPAIR",
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


def test_v21_026_contract() -> None:
    result = run_stage()
    assert "STAGE_NAME=V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR" in result.stdout
    for path in REQUIRED_OUTPUTS:
        assert path.exists(), f"missing output {path}"
        assert path.stat().st_size > 0, f"empty output {path}"

    summary = read_csv(OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_SUMMARY.csv")[0]
    assert summary["research_only"] == "TRUE"
    assert summary["v21_024_context_logic_repair_decision"] == "MARKET_REGIME_CONTEXT_LOGIC_PARTIAL_LABELS_LIMITED"
    assert summary["v21_024_candidate_research_path_decision"] == "market regime label/source repair"
    assert summary["v21_024_recommended_next_stage"] == "V21.026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR"
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
    assert summary["source_contract_repair_decision"] in ALLOWED_DECISIONS
    assert summary["recommended_next_stage"] in ALLOWED_NEXT
    assert summary["prototype_output_scope"] == "V21_026_RESEARCH_ONLY"

    forbidden = ["PRODUCTION", "REAL_BOOK", "OFFICIAL_ACTIVATION", "OFFICIAL_RANKING_READINESS", "OFFICIAL_WEIGHT_UPDATE_READINESS"]
    for term in forbidden:
        assert term not in summary["final_status"]
        assert term not in summary["source_contract_repair_decision"]

    ingest = read_csv(OUT_DIR / "V21_026_V21_024_DECISION_INGEST_AUDIT.csv")
    assert any(row["audit_item"] == "v21_024_decision_ingested" and row["audit_passed"] == "TRUE" for row in ingest)
    assert any(row["audit_item"] == "recommended_next_stage_v21_026" and row["audit_passed"] == "TRUE" for row in ingest)

    contract = read_csv(OUT_DIR / "V21_026_PROPOSED_REGIME_LABEL_CONTRACT.csv")
    contract_labels = {row["label_name"] for row in contract}
    for label in ["risk_on", "risk_off", "neutral", "high_vix", "low_vix", "QQQ_uptrend", "SPY_uptrend", "sector_uptrend", "FOMC_window", "regime_transition_risk", "regime_conflict_flag"]:
        assert label in contract_labels
    assert all(row["research_only"] == "TRUE" for row in contract)

    derived = read_csv(OUT_DIR / "V21_026_DERIVED_RESEARCH_ONLY_REGIME_LABELS.csv")
    assert derived, "expected locally derivable research-only labels"
    assert all(row["label_status"] == "DERIVED_RESEARCH_ONLY" for row in derived)
    assert all(row["research_only"] == "TRUE" for row in derived)
    for row in derived:
        assert row["source_date"] <= row["as_of_date"], row
        assert row["point_in_time_eligible"] == "TRUE", row
    derived_labels = {row["label_name"] for row in derived}
    assert not {"high_vix", "low_vix", "normal_vix", "FOMC_window", "CPI_window", "NFP_window", "earnings_season_window"} & derived_labels

    pit = read_csv(OUT_DIR / "V21_026_PIT_VALIDATION_AUDIT.csv")
    assert pit
    assert all(row["source_date_lte_as_of_date"] == "TRUE" for row in pit)
    assert all(row["future_data_used"] == "FALSE" for row in pit)
    assert all(row["pit_validation_status"] == "PASS" for row in pit)

    gaps = read_csv(OUT_DIR / "V21_026_SOURCE_CONTRACT_GAP_TABLE.csv")
    assert any(row["affected_label"] == "high_vix|low_vix|normal_vix" and row["cannot_fabricate"] == "TRUE" for row in gaps)
    assert any("FOMC" in row["affected_label"] and row["cannot_fabricate"] == "TRUE" for row in gaps)

    decision = read_csv(OUT_DIR / "V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR_DECISION.csv")
    selected = [row for row in decision if row["selected_recommended_next_stage"] == "TRUE"]
    assert len(decision) == 1
    assert len(selected) == 1
    assert selected[0]["source_contract_repair_decision"] in ALLOWED_DECISIONS
    assert selected[0]["recommended_next_stage"] in ALLOWED_NEXT
    assert selected[0]["official_use_allowed"] == "FALSE"

    for output in REQUIRED_OUTPUTS:
        if output.suffix == ".csv":
            assert output.name.startswith("V21_026_")
    report_text = REPORT.read_text(encoding="utf-8").lower()
    for expected in [
        "research-only",
        "final source contract repair decision",
        "v21.024 decision ingestion",
        "proposed regime label contract",
        "derived research-only regime labels",
        "point-in-time validation",
        "data_trust zero-alpha confirmation",
        "explicit blocked actions",
        "no production readiness",
        "no real-book readiness",
        "recommended next stage",
    ]:
        assert expected in report_text
    forbidden_report_claims = ["production readiness confirmed", "real-book readiness confirmed", "official activation", "official ranking readiness confirmed", "official weight update readiness confirmed"]
    for claim in forbidden_report_claims:
        assert claim not in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)], cwd=ROOT, text=True, capture_output=True, check=True)
    for expected in [
        "STAGE_NAME=V21_026_MARKET_REGIME_SOURCE_CONTRACT_REPAIR",
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
    test_v21_026_contract()
    test_wrapper_parseable()
    print("V21.026 market regime source contract repair tests passed")
