#!/usr/bin/env python
"""Validate V21.133 R1 E baseline anchor and overlap repair outputs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
SUMMARY = OUT / "e_r1_validation_summary.json"
REQUIRED = [
    "input_artifact_audit.csv",
    "input_top20_snapshot.csv",
    "input_score_distribution_audit.csv",
    "ticker_normalization_audit.csv",
    "a1_baseline_anchor_audit.csv",
    "e_r1_full_ranking.csv",
    "e_r1_top20.csv",
    "e_r1_top50.csv",
    "e_r1_score_components.csv",
    "e_r1_anchor_correlation_audit.csv",
    "e_r1_overlap_matrix.csv",
    "e_r1_rank_diff_vs_a1.csv",
    "e_r1_abcd_overlap_matrix.csv",
    "e_r1_abcd_overlap_tickers.json",
    "e_r1_validation_summary.json",
    "V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR_report.txt",
]
COMPONENTS = ["A1_baseline_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]


def summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def explicit_fail() -> bool:
    return str(summary()["FINAL_STATUS"]).startswith(("FAIL_", "BLOCKED_"))


def test_required_outputs_exist():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name


def test_ticker_norm_uppercase_stripped_and_no_duplicates():
    full = pd.read_csv(OUT / "e_r1_full_ranking.csv")
    assert "ticker_norm" in full.columns
    assert full["ticker_norm"].map(lambda x: x == str(x).upper().strip()).all()
    eligible = full[full["eligible_flag"].astype(str).str.lower().eq("true")]
    assert not eligible["ticker_norm"].duplicated().any()


def test_weights_components_and_formula():
    s = summary()
    assert abs(sum(s["weights"].values()) - 1.0) < 1e-12
    full = pd.read_csv(OUT / "e_r1_full_ranking.csv")
    for col in COMPONENTS:
        assert col in full.columns
        assert full[col].between(0, 100).all(), col
    expected = sum(full[col] * s["weights"][col] for col in COMPONENTS)
    assert np.allclose(full["E_final_score"], expected, atol=1e-9)
    eligible = full[full["eligible_flag"].astype(str).str.lower().eq("true")]
    assert not eligible["A1_baseline_norm"].isna().any()


def test_a1_correlation_and_overlap_sanity():
    s = summary()
    if not explicit_fail():
        assert s["corr_E_final_score_A1_baseline_norm"] >= 0.75
        assert s["E_vs_A1_top20_overlap_count"] > 0
    if s["E_vs_A1_top20_overlap_count"] == 0:
        assert str(s["FINAL_STATUS"]).startswith("FAIL_")


def test_overlap_matrix_consistent_and_uses_ticker_norm():
    matrix = pd.read_csv(OUT / "e_r1_abcd_overlap_matrix.csv")
    assert set(matrix["strategy"]) == {"A1", "B", "C", "D", "E"}
    e_row = matrix[matrix["strategy"].eq("E")].iloc[0]
    a1_row = matrix[matrix["strategy"].eq("A1")].iloc[0]
    assert int(e_row["A1_top20_overlap_count"]) == int(a1_row["E_top20_overlap_count"])
    detail = json.loads((OUT / "e_r1_abcd_overlap_tickers.json").read_text(encoding="utf-8"))
    assert detail["E_vs_A1"]["top20_overlap_count"] == int(e_row["A1_top20_overlap_count"])
    for ticker in detail["E_vs_A1"]["top20_overlap_tickers"]:
        assert ticker == ticker.upper().strip()


def test_no_future_or_outcome_columns_used():
    s = summary()
    panel_max = pd.read_csv(PRICE_PANEL, usecols=["date"])["date"].astype(str).max()
    assert s["latest_price_date_used"] <= panel_max
    full = pd.read_csv(OUT / "e_r1_full_ranking.csv")
    forbidden = [
        col for col in full.columns
        if any(token in col.lower() for token in ["forward_return", "future_label", "matured_return", "outcome"])
    ]
    assert forbidden == []


def test_controls_locked_down():
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["research_only"] is True
    assert s["protected_outputs_modified"] is False
    assert s["E_adoption_allowed"] is False


def test_a1_reconstruction_failure_status_if_invalid():
    s = summary()
    anchor = pd.read_csv(OUT / "a1_baseline_anchor_audit.csv")
    if anchor["A1_baseline_norm"].isna().all():
        assert str(s["FINAL_STATUS"]).startswith(("FAIL_", "BLOCKED_"))
