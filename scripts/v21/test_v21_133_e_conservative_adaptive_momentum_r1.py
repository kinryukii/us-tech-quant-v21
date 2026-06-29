#!/usr/bin/env python
"""Validate V21.133 E conservative adaptive momentum R1 outputs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
SUMMARY = OUT / "e_validation_summary.json"
REQUIRED = [
    "e_full_ranking.csv",
    "e_top20.csv",
    "e_top50.csv",
    "e_score_components.csv",
    "e_abcd_overlap_matrix.csv",
    "e_vs_abcd_rank_diff.csv",
    "e_concentration_audit.csv",
    "e_data_quality_audit.csv",
    "e_maturity_gate_audit.csv",
    "e_validation_summary.json",
    "V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1_report.txt",
]
FINAL_COMPONENTS = ["A1_baseline_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]
NORMALIZED_COMPONENTS = [
    "A1_baseline_norm",
    "rs_vs_benchmark_norm",
    "price_momentum_20d_60d_norm",
    "volume_confirmed_momentum_norm",
    "pullback_after_strength_norm",
    "breakout_follow_through_norm",
    "context_momentum_norm",
    "rsi_position_repair_norm",
    "kdj_stochastic_confirmation_norm",
    "macd_direction_norm",
    "bollinger_position_norm",
    "ma_ema_volume_confirmation_norm",
    "technical_entry_quality_norm",
    "repeated_loser_avoidance_norm",
    "concentration_avoidance_norm",
    "left_tail_avoidance_norm",
    "data_quality_maturity_avoidance_norm",
    "risk_guardrail_norm",
]


def load_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_exist():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name


def test_weight_sums_exact():
    summary = load_summary()
    assert abs(sum(summary["final_weights"].values()) - 1.0) < 1e-12
    assert abs(sum(summary["expanded_effective_weights"].values()) - 1.0) < 1e-12


def test_full_ranking_integrity_and_scores():
    summary = load_summary()
    full = pd.read_csv(OUT / "e_full_ranking.csv")
    eligible = full[full["eligible_flag"].astype(str).str.lower().eq("true")]
    assert not eligible["E_final_score"].isna().any()
    assert not full["ticker"].duplicated().any()
    assert len(pd.read_csv(OUT / "e_top20.csv")) == min(20, len(eligible))
    assert len(pd.read_csv(OUT / "e_top50.csv")) == min(50, len(eligible))

    expected = sum(full[col] * weight for col, weight in summary["final_weights"].items())
    assert np.allclose(full["E_final_score"], expected, atol=1e-9, equal_nan=False)
    for col in NORMALIZED_COMPONENTS:
        assert col in full.columns
        assert full[col].between(0, 100).all(), col


def test_price_date_no_future_leakage():
    summary = load_summary()
    panel_max = pd.read_csv(PRICE_PANEL, usecols=["date"])["date"].astype(str).max()
    assert summary["latest_price_date_used"] <= panel_max
    full = pd.read_csv(OUT / "e_full_ranking.csv")
    forbidden = [
        col for col in full.columns
        if any(token in col.lower() for token in ["forward_return", "future_label", "matured_return", "outcome"])
    ]
    assert forbidden == []
    assert full["latest_price_date"].dropna().astype(str).max() <= summary["latest_price_date_used"]


def test_controls_locked_down():
    summary = load_summary()
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["research_only"] is True
    assert summary["protected_outputs_modified"] is False
    assert summary["E_adoption_allowed"] is False
    assert summary["D_or_ABCD_replaced"] is False


def test_overlap_matrix_consistent():
    full = pd.read_csv(OUT / "e_full_ranking.csv")
    e_top20 = set(pd.read_csv(OUT / "e_top20.csv")["ticker"].astype(str))
    matrix = pd.read_csv(OUT / "e_abcd_overlap_matrix.csv")
    assert set(matrix["strategy"]) == {"A1", "B", "C", "D", "E"}
    assert int(matrix.loc[matrix["strategy"].eq("E"), "E"].iloc[0]) == len(e_top20)
    assert int(matrix.loc[matrix["strategy"].eq("E"), "A1"].iloc[0]) == int(matrix.loc[matrix["strategy"].eq("A1"), "E"].iloc[0])
    assert len(e_top20) == min(20, int(full["eligible_flag"].astype(str).str.lower().eq("true").sum()))


def test_concentration_and_warning_behavior():
    concentration = pd.read_csv(OUT / "e_concentration_audit.csv")
    assert not concentration.empty
    assert {"view", "exposure_type", "bucket", "weight", "metadata_coverage"}.issubset(concentration.columns)
    warnings = pd.read_csv(OUT / "e_data_quality_audit.csv")
    assert not warnings.empty
    if (concentration["metadata_coverage"] < 0.95).any():
        assert warnings["warning_type"].eq("partial_metadata_coverage").any()
    if warnings["warning_type"].eq("insufficient_technical_history").any():
        full = pd.read_csv(OUT / "e_full_ranking.csv")
        warned = set(warnings[warnings["warning_type"].eq("insufficient_technical_history")]["ticker"].astype(str))
        if warned:
            subset = full[full["ticker"].isin(warned)]
            assert (subset["technical_entry_quality_norm"] == 50).all()


def test_price_panel_stale_status_if_applicable():
    summary = load_summary()
    if summary["price_panel_max_date"] < summary["latest_price_date_used"]:
        assert "WITH_DATA_WARN" in summary["FINAL_STATUS"]
