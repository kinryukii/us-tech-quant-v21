#!/usr/bin/env python
"""Validate V21.136 E_R1 overlay influence diagnostic."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC"
E_R1_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
A1_SOURCE = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv"
SUMMARY = OUT / "e_r1_overlay_diagnostic_summary.json"
REQUIRED = [
    "e_r1_vs_a1_rank_movement_audit.csv",
    "e_r1_top20_entries_exits.csv",
    "e_r1_top50_entries_exits.csv",
    "e_r1_component_contribution_decomposition.csv",
    "e_r1_overlay_driver_attribution.csv",
    "e_r1_overlay_influence_strength_audit.csv",
    "e_r1_calibration_simulation_summary.csv",
    "e_r1_calibration_simulated_top20.csv",
    "e_r1_calibration_simulated_top50.csv",
    "e_r1_calibration_overlap_matrix.csv",
    "e_r1_structural_recommendation.json",
    "e_r1_overlay_diagnostic_summary.json",
    "V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC_report.txt",
]
ALLOWED_CLASSES = {"TOO_WEAK", "CONSERVATIVE_BUT_MEANINGFUL", "TOO_STRONG_OR_UNSTABLE"}
ALLOWED_RECS = {"KEEP_E_R1_WAIT_FORWARD_MATURITY", "CONSIDER_E_R2_AFTER_FORWARD_MATURITY", "E_R1_TOO_WEAK_NEEDS_CALIBRATION_REVIEW", "E_R1_TOO_STRONG_REVERT_CLOSER_TO_A1", "E_REJECT_STRUCTURAL_RISK"}


def summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_required_outputs_and_sources():
    assert OUT.is_dir()
    for name in REQUIRED:
        assert (OUT / name).is_file(), name
    assert E_R1_SOURCE.is_file()
    assert A1_SOURCE.is_file()


def test_ticker_norm_and_duplicates():
    e = pd.read_csv(E_R1_SOURCE)
    assert e["ticker_norm"].map(lambda x: x == str(x).upper().strip()).all()
    assert not e["ticker_norm"].duplicated().any()


def test_weighted_score_reconstruction():
    comp = pd.read_csv(OUT / "e_r1_component_contribution_decomposition.csv")
    expected = comp["A1_contribution"] + comp["context_momentum_contribution"] + comp["technical_contribution"] + comp["risk_contribution"]
    assert np.allclose(comp["E_final_score"], expected, atol=1e-9)


def test_entries_exits_consistent():
    movement = pd.read_csv(OUT / "e_r1_vs_a1_rank_movement_audit.csv")
    top20 = pd.read_csv(OUT / "e_r1_top20_entries_exits.csv")
    top50 = pd.read_csv(OUT / "e_r1_top50_entries_exits.csv")
    assert set(top20[top20["change_type"].eq("ENTRY")]["ticker_norm"]) == set(movement[movement["entered_E_top20_from_outside_A1_top20"].astype(bool)]["ticker_norm"])
    assert set(top20[top20["change_type"].eq("EXIT")]["ticker_norm"]) == set(movement[movement["exited_A1_top20_under_E_R1"].astype(bool)]["ticker_norm"])
    assert set(top50[top50["change_type"].eq("ENTRY")]["ticker_norm"]) == set(movement[movement["entered_E_top50_from_outside_A1_top50"].astype(bool)]["ticker_norm"])
    assert set(top50[top50["change_type"].eq("EXIT")]["ticker_norm"]) == set(movement[movement["exited_A1_top50_under_E_R1"].astype(bool)]["ticker_norm"])


def test_influence_class_and_recommendation_allowed():
    s = summary()
    strength = pd.read_csv(OUT / "e_r1_overlay_influence_strength_audit.csv").iloc[0]
    assert strength["overlay_influence_class"] in ALLOWED_CLASSES
    assert s["overlay_influence_class"] in ALLOWED_CLASSES
    rec = json.loads((OUT / "e_r1_structural_recommendation.json").read_text(encoding="utf-8"))
    assert rec["structural_recommendation"] in ALLOWED_RECS
    assert s["structural_recommendation"] in ALLOWED_RECS


def test_calibration_simulations_diagnostic_only():
    sims = pd.read_csv(OUT / "e_r1_calibration_simulation_summary.csv")
    assert not sims.empty
    assert sims["diagnostic_only"].astype(bool).all()
    assert not sims["adopted"].astype(bool).any()
    assert np.allclose(sims["weight_sum"], 1.0, atol=1e-12)
    top20 = pd.read_csv(OUT / "e_r1_calibration_simulated_top20.csv")
    assert top20["diagnostic_only"].astype(bool).all()
    assert not top20["adopted"].astype(bool).any()


def test_no_forward_columns_for_calibration():
    for name in ["e_r1_calibration_simulation_summary.csv", "e_r1_overlay_influence_strength_audit.csv"]:
        df = pd.read_csv(OUT / name)
        forbidden = [c for c in df.columns if any(tok in c.lower() for tok in ["forward_return", "future_label", "outcome"])]
        assert forbidden == []


def test_controls_locked_down():
    s = summary()
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["research_only"] is True
    assert s["E_adoption_allowed"] is False
    assert s["protected_outputs_modified"] is False
