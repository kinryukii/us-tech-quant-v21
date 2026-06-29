#!/usr/bin/env python
"""Validate V21.134 E_R1 forward tracking ledger."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER"
E_R1_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
INVALID_E_SOURCE = ROOT / "outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1/e_full_ranking.csv"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
SUMMARY = OUT / "e_r1_forward_tracking_summary.json"
REQUIRED = [
    "e_r1_forward_ledger_top20.csv",
    "e_r1_forward_ledger_top50.csv",
    "e_r1_forward_summary_by_horizon.csv",
    "e_r1_vs_qqq_forward_summary.csv",
    "e_r1_vs_abcd_forward_comparison.csv",
    "e_r1_maturity_gate_audit.csv",
    "e_r1_no_leakage_audit.csv",
    "e_r1_data_quality_audit.csv",
    "e_r1_forward_tracking_summary.json",
    "V21.134_E_R1_FORWARD_TRACKING_LEDGER_report.txt",
]


def load_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_and_source():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    assert E_R1_SOURCE.is_file()
    summary = load_summary()
    assert summary["E_R1_source_path"].endswith("V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
    assert summary["invalid_original_v21_133_primary_source_used"] is False
    assert INVALID_E_SOURCE.is_file()


def test_ledger_row_counts_and_duplicates():
    source = pd.read_csv(E_R1_SOURCE)
    top20 = pd.read_csv(OUT / "e_r1_forward_ledger_top20.csv")
    top50 = pd.read_csv(OUT / "e_r1_forward_ledger_top50.csv")
    assert len(top20) == min(20, len(source[source["eligible_flag"].astype(str).str.lower().eq("true")]))
    assert len(top50) == min(50, len(source[source["eligible_flag"].astype(str).str.lower().eq("true")]))
    assert not top20["ticker_norm"].duplicated().any()
    assert not top50["ticker_norm"].duplicated().any()


def test_frozen_scores_match_source():
    source = pd.read_csv(E_R1_SOURCE).set_index("ticker_norm")
    ledger = pd.concat([
        pd.read_csv(OUT / "e_r1_forward_ledger_top20.csv"),
        pd.read_csv(OUT / "e_r1_forward_ledger_top50.csv"),
    ], ignore_index=True)
    for _, row in ledger.drop_duplicates("ticker_norm").iterrows():
        src = source.loc[row["ticker_norm"]]
        assert np.isclose(row["E_final_score"], src["E_final_score"], atol=1e-9)
        assert np.isclose(row["A1_baseline_norm"], src["A1_baseline_norm"], atol=1e-9)


def test_no_score_leakage_and_dates():
    summary = load_summary()
    panel_max = pd.read_csv(PRICE_PANEL, usecols=["date"])["date"].astype(str).max()
    assert summary["ranking_date"] <= panel_max
    audit = pd.read_csv(OUT / "e_r1_no_leakage_audit.csv")
    assert audit["status"].eq("PASS").all()
    assert not audit["forward_returns_used_to_compute_E_score"].astype(bool).any()
    ledger = pd.read_csv(OUT / "e_r1_forward_ledger_top20.csv")
    for horizon in [5, 10, 20]:
        date_col = f"h{horizon}_forward_date"
        mature_col = f"h{horizon}_matured"
        dated = ledger[date_col].dropna().astype(str)
        dated = dated[dated.ne("")]
        assert (dated > summary["ranking_date"]).all()
        assert ledger[mature_col].isin([True, False]).all()
        matured = ledger[mature_col].astype(bool)
        assert (ledger.loc[matured, date_col].astype(str) > summary["ranking_date"]).all()


def test_benchmark_and_warnings():
    ledger = pd.read_csv(OUT / "e_r1_forward_ledger_top20.csv")
    dq = pd.read_csv(OUT / "e_r1_data_quality_audit.csv")
    if ledger["h5_qqq_matured"].notna().any():
        assert "h5_qqq_forward_return" in ledger.columns
    if dq["warning_type"].eq("MISSING_PRIMARY_BENCHMARK_QQQ").any():
        assert not ledger["h5_qqq_matured"].astype(bool).any()
    maturity = pd.read_csv(OUT / "e_r1_maturity_gate_audit.csv")
    assert not maturity.empty
    assert maturity.iloc[0]["status"] == "BLOCK"


def test_controls_locked_down():
    summary = load_summary()
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
    assert summary["E_adoption_allowed"] is False
    assert summary["protected_outputs_modified"] is False
