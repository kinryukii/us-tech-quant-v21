#!/usr/bin/env python
"""Validate V21.137 E_R1 risk decomposition versus A1."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1"
A1_SOURCE = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv"
E_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
SUMMARY = OUT / "e_r1_risk_decomposition_summary.json"
REQUIRED = [
    "e_r1_vs_a1_concentration_comparison.csv",
    "e_r1_sector_industry_exposure_top20.csv",
    "e_r1_sector_industry_exposure_top50.csv",
    "e_r1_top20_entry_exit_risk_attribution.csv",
    "e_r1_top50_entry_exit_risk_attribution.csv",
    "e_r1_vs_a1_left_tail_proxy_comparison.csv",
    "e_r1_ticker_left_tail_proxy.csv",
    "e_r1_vs_a1_repeated_loser_comparison.csv",
    "e_r1_vs_a1_data_quality_comparison.csv",
    "e_r1_risk_decomposition_summary.json",
    "V21.137_E_R1_RISK_DECOMPOSITION_VS_A1_report.txt",
]
ALLOWED = {
    "E_R1_RISK_PROFILE_ACCEPTABLE_WAIT_MATURITY",
    "E_R1_RISK_PROFILE_ACCEPTABLE_WITH_WARN_WAIT_MATURITY",
    "E_R1_RISK_PROFILE_WORSE_THAN_A1_REVIEW_REQUIRED",
    "E_R1_REJECT_STRUCTURAL_RISK",
}


def summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_and_sources():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    assert A1_SOURCE.is_file()
    assert E_SOURCE.is_file()


def test_ticker_norm_and_no_duplicates():
    for path in [OUT / "e_r1_sector_industry_exposure_top20.csv", OUT / "e_r1_sector_industry_exposure_top50.csv"]:
        df = pd.read_csv(path)
        if "ticker_norm" in df.columns:
            assert df["ticker_norm"].map(lambda x: x == str(x).upper().strip()).all()
    for path in [A1_SOURCE, E_SOURCE]:
        df = pd.read_csv(path)
        col = "ticker_norm" if "ticker_norm" in df.columns else "ticker"
        tickers = df[col].astype(str).str.upper().str.strip()
        assert not tickers.duplicated().any()


def test_entries_exits_consistent():
    top20 = pd.read_csv(OUT / "e_r1_top20_entry_exit_risk_attribution.csv")
    top50 = pd.read_csv(OUT / "e_r1_top50_entry_exit_risk_attribution.csv")
    s = summary()
    assert set(top20[top20["action"].eq("ENTRY")]["ticker_norm"]) == set(filter(None, s["top20_entries"].split("|")))
    assert set(top20[top20["action"].eq("EXIT")]["ticker_norm"]) == set(filter(None, s["top20_exits"].split("|")))
    assert set(top50["action"]).issubset({"ENTRY", "EXIT"})


def test_concentration_and_metadata_warning_behavior():
    conc = pd.read_csv(OUT / "e_r1_vs_a1_concentration_comparison.csv")
    assert not conc.empty
    assert "E_R1_metadata_coverage_ratio" in conc.columns
    dq = pd.read_csv(OUT / "e_r1_vs_a1_data_quality_comparison.csv")
    assert not dq.empty
    s = summary()
    if (dq["metadata_missing_count"] > 0).any():
        assert s["metadata_warning"] is True or s["warnings"] != "none"


def test_left_tail_proxy_no_forward_columns():
    proxy = pd.read_csv(OUT / "e_r1_ticker_left_tail_proxy.csv")
    assert not proxy.empty
    s = summary()
    assert (proxy["latest_price_date_used"].dropna().astype(str) <= s["ranking_date"]).all()
    forbidden = [c for c in proxy.columns if any(tok in c.lower() for tok in ["forward_return", "future_label", "outcome"])]
    assert forbidden == []


def test_repeated_loser_flag_explicit_and_decision_allowed():
    rep = pd.read_csv(OUT / "e_r1_vs_a1_repeated_loser_comparison.csv")
    assert not rep.empty
    assert rep["repeated_loser_source_available"].astype(str).str.lower().isin(["true", "false"]).all()
    assert summary()["DECISION"] in ALLOWED


def test_controls_locked_down():
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["research_only"] is True
    assert s["E_adoption_allowed"] is False
    assert s["protected_outputs_modified"] is False
