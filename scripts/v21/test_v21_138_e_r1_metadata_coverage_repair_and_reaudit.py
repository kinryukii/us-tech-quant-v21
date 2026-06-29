#!/usr/bin/env python
"""Validate V21.138 metadata repair and concentration re-audit."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT"
A1_SOURCE = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv"
E_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
SUMMARY = OUT / "e_r1_metadata_reaudit_summary.json"
REQUIRED = [
    "metadata_source_inventory.csv",
    "consolidated_sector_industry_metadata_bridge.csv",
    "metadata_conflict_audit.csv",
    "metadata_missing_ticker_audit.csv",
    "metadata_coverage_reaudit.csv",
    "e_r1_vs_a1_concentration_reaudit.csv",
    "e_r1_sector_industry_reaudit_top20.csv",
    "e_r1_sector_industry_reaudit_top50.csv",
    "e_r1_metadata_reaudit_summary.json",
    "V21.138_E_R1_METADATA_COVERAGE_REPAIR_AND_REAUDIT_report.txt",
]
ALLOWED_STATUS = {"CLEARED", "NON_MATERIAL_REMAINING_GAPS", "MATERIAL_METADATA_GAPS_REMAIN", "BLOCKED_INSUFFICIENT_METADATA"}
ALLOWED_DECISIONS = {
    "E_R1_METADATA_REPAIRED_RISK_PROFILE_ACCEPTABLE_WAIT_MATURITY",
    "E_R1_METADATA_GAPS_NON_MATERIAL_WAIT_MATURITY",
    "E_R1_METADATA_GAPS_MATERIAL_REVIEW_REQUIRED",
    "E_R1_METADATA_INSUFFICIENT_BLOCKED",
}


def summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_and_sources():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    assert A1_SOURCE.is_file()
    assert E_SOURCE.is_file()


def test_inventory_and_bridge():
    inv = pd.read_csv(OUT / "metadata_source_inventory.csv")
    s = summary()
    if not str(s["FINAL_STATUS"]).startswith("BLOCKED_"):
        assert len(inv) >= 1
    bridge = pd.read_csv(OUT / "consolidated_sector_industry_metadata_bridge.csv")
    if not bridge.empty:
        assert bridge["ticker_norm"].map(lambda x: x == str(x).upper().strip()).all()
        assert not bridge["ticker_norm"].duplicated().any()


def test_coverage_and_concentration_exist():
    coverage = pd.read_csv(OUT / "metadata_coverage_reaudit.csv")
    conc = pd.read_csv(OUT / "e_r1_vs_a1_concentration_reaudit.csv")
    assert not coverage.empty
    assert not conc.empty
    assert {"coverage_group", "sector_coverage_ratio", "industry_coverage_ratio"}.issubset(coverage.columns)


def test_conflicts_and_missing_recorded_if_present():
    conflicts = pd.read_csv(OUT / "metadata_conflict_audit.csv")
    missing = pd.read_csv(OUT / "metadata_missing_ticker_audit.csv")
    if not conflicts.empty:
        assert "ticker_norm" in conflicts.columns
    if not missing.empty:
        assert "ticker_norm" in missing.columns


def test_allowed_status_decision_and_controls():
    s = summary()
    assert s["metadata_warning_status"] in ALLOWED_STATUS
    assert s["DECISION"] in ALLOWED_DECISIONS
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["research_only"] is True
    assert s["E_adoption_allowed"] is False
    assert s["protected_outputs_modified"] is False


def test_no_forward_or_web_artifacts():
    for name in REQUIRED:
        if name.endswith(".csv"):
            df = pd.read_csv(OUT / name)
            forbidden = [c for c in df.columns if any(tok in c.lower() for tok in ["forward_return", "future_label", "outcome", "web_fetch"])]
            assert forbidden == []
