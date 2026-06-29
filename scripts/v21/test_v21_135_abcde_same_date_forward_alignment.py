#!/usr/bin/env python
"""Validate V21.135 ABCDE same-date forward alignment."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT"
E_R1_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
INVALID_E_SOURCE = ROOT / "outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1/e_full_ranking.csv"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
SUMMARY = OUT / "abcde_alignment_summary.json"
REQUIRED = [
    "abcde_aligned_top20_forward_ledger.csv",
    "abcde_aligned_top50_forward_ledger.csv",
    "abcde_same_date_source_audit.csv",
    "abcde_top20_overlap_matrix.csv",
    "abcde_top50_overlap_matrix.csv",
    "abcde_forward_summary_by_strategy_horizon.csv",
    "abcde_pairwise_forward_comparison.csv",
    "abcde_maturity_gate_audit.csv",
    "abcde_no_leakage_audit.csv",
    "abcde_data_quality_audit.csv",
    "abcde_alignment_summary.json",
    "V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT_report.txt",
]
STRATEGIES = {"A1", "B", "C", "D", "E_R1"}


def load_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_and_sources():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    assert E_R1_SOURCE.is_file()
    assert INVALID_E_SOURCE.is_file()
    s = load_summary()
    assert s["source_paths"]["E_R1"].endswith("V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
    assert s["invalid_original_v21_133_e_used"] is False
    if not Path(ROOT / s["source_paths"]["A1"]).is_file():
        assert str(s["FINAL_STATUS"]).startswith("BLOCKED_")


def test_ticker_norm_and_row_counts():
    for path, n in [(OUT / "abcde_aligned_top20_forward_ledger.csv", 20), (OUT / "abcde_aligned_top50_forward_ledger.csv", 50)]:
        df = pd.read_csv(path)
        assert df["ticker_norm"].map(lambda x: x == str(x).upper().strip()).all()
        for strategy, group in df.groupby("strategy_id"):
            assert not group["ticker_norm"].duplicated().any()
            assert len(group) == n


def test_dates_maturity_and_benchmarks():
    s = load_summary()
    panel_max = pd.read_csv(PRICE_PANEL, usecols=["date"])["date"].astype(str).max()
    assert s["ranking_date"] <= panel_max
    ledger = pd.concat([
        pd.read_csv(OUT / "abcde_aligned_top20_forward_ledger.csv"),
        pd.read_csv(OUT / "abcde_aligned_top50_forward_ledger.csv"),
    ])
    for h in [5, 10, 20]:
        mature = ledger[f"h{h}_matured"].astype(bool)
        dates = ledger.loc[mature, f"h{h}_forward_date"].astype(str)
        assert (dates > s["ranking_date"]).all()
        assert ledger[f"h{h}_matured"].isin([True, False]).all()
        if ledger[f"h{h}_qqq_matured"].astype(bool).any():
            assert f"h{h}_qqq_forward_return" in ledger.columns


def test_no_leakage_and_forward_columns_not_scoring():
    audit = pd.read_csv(OUT / "abcde_no_leakage_audit.csv")
    assert audit["status"].eq("PASS").all()
    assert not audit["forward_returns_used_for_scoring"].astype(bool).any()
    ledger = pd.read_csv(OUT / "abcde_aligned_top20_forward_ledger.csv")
    forbidden = [c for c in ledger.columns if any(tok in c.lower() for tok in ["future_label", "outcome"])]
    assert forbidden == []


def test_overlap_matrices_symmetric_and_e_overlap():
    s = load_summary()
    for name in ["abcde_top20_overlap_matrix.csv", "abcde_top50_overlap_matrix.csv"]:
        matrix = pd.read_csv(OUT / name).set_index("strategy_id")
        assert set(matrix.index) == STRATEGIES
        for a in STRATEGIES:
            for b in STRATEGIES:
                assert int(matrix.loc[a, b]) == int(matrix.loc[b, a])
    top20 = pd.read_csv(OUT / "abcde_top20_overlap_matrix.csv").set_index("strategy_id")
    assert int(top20.loc["E_R1", "A1"]) == int(s["E_R1_vs_A1_top20_overlap"])
    assert int(top20.loc["E_R1", "A1"]) == 16


def test_controls_and_wait_maturity_status():
    s = load_summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["research_only"] is True
    assert s["E_adoption_allowed"] is False
    assert s["protected_outputs_modified"] is False
    forward = pd.read_csv(OUT / "abcde_forward_summary_by_strategy_horizon.csv")
    if int(forward["matured_rows"].sum()) == 0:
        assert "WAIT_MATURITY" in s["FINAL_STATUS"]
