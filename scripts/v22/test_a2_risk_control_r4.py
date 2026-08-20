"""Focused integrity tests for frozen R4 structural-stress validation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
OUT = Path(r"D:\us-tech-quant-results\A2_RISK_CONTROL_R4_STRUCTURAL_STRESS_VALIDATION")


def _module():
    path = REPO / "scripts/v22/a2_risk_control_r4.py"
    spec = importlib.util.spec_from_file_location("focused_r4", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R4 = _module()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_identities_and_r3_rule_are_exact():
    identity = R4.identities()
    assert identity["r1_contract_sha256"] == R4.R1_HASH
    assert identity["r2_contract_sha256"] == R4.R2_HASH
    assert identity["r6_oof_sha256"] == R4.R6_HASH
    assert identity["r3_contract_sha256"] == R4.R3_CONTRACT_HASH
    assert R4.inherited_rule()["method"] == "COMBINED_SPX4_SOXX8_VIX50_CORR70_STRESS_BUDGET"


def test_r4_contract_hash_is_stable_and_reconstructable():
    saved = json.loads((OUT / "r4_contract.json").read_text())
    expected = R4.contract(R4.identities(), R4.inherited_rule())
    assert saved == expected
    assert _sha(OUT / "r4_contract.json") == (OUT / "r4_contract_sha256.txt").read_text().strip()


def test_no_2026_read_or_training_and_no_search():
    audit = json.loads((OUT / "r4_audit.json").read_text())
    assert audit["2026_R4_OUTCOME_READ_COUNT"] == 0
    assert audit["2026_training_rows"] == 0
    assert audit["parameter_search_count"] == 0
    assert audit["scenario_search_count"] == 0
    daily = pd.read_parquet(OUT / "r4_daily_exposure.parquet")
    assert pd.to_datetime(daily.date).max() < pd.Timestamp("2026-01-01")


def test_geometry_and_stress_inputs_are_pit_causal():
    _, _, _, _, geometry = R4.load_data()
    assert geometry.information_date.lt(geometry.signal_date).all()
    assert geometry.complete_sessions.eq(60).all()
    budgets = R4.R3.causal_budgets(geometry)
    assert budgets.signal_date.max() < pd.Timestamp("2026-01-01")
    # The causal reference must exclude the current observation.
    ordered = geometry.sort_values("signal_date").reset_index(drop=True)
    expected = ordered.combined_stress_loss.expanding(60).median().shift(1)
    legal = expected.notna()
    assert np.allclose(budgets.stress_reference, expected.loc[legal], atol=1e-14, rtol=0)


def test_stress_path_reproduces_r3_and_never_leverages():
    weights, _, _, _, geometry = R4.load_data()
    selected, budgets = R4.reproduce_path(weights, geometry)
    assert budgets.stress_budget.between(.5, 1.0).all()
    assert (selected.dynamic_weight <= selected.base_r6_weight + 1e-15).all()
    assert (selected.dynamic_weight >= -1e-15).all()
    assert budgets.stress_budget.diff().abs().dropna().le(.05 + 1e-14).all()


def test_whole_and_year_matched_exposure_are_exact():
    matched = pd.read_csv(OUT / "r4_matched_exposure.csv")
    assert matched.error.abs().max() <= 1e-14
    assert {"year_matched_weight", "whole_matched_weight"}.issubset(set(matched.match_type))
    assert len(matched.loc[matched.match_type.eq("year_matched_weight")]) == 4


def test_output_exposure_path_is_deterministically_reproduced():
    weights, positions, _, _, geometry = R4.load_data()
    selected, _ = R4.reproduce_path(weights, geometry)
    _, sims, _, _ = R4.simulate_set(selected, positions)
    saved = pd.read_parquet(OUT / "r4_daily_exposure.parquet")
    actual = sims["R4_STRESS_DYNAMIC"]
    assert np.allclose(saved.daily_return_dynamic, actual.daily_return, atol=1e-14, rtol=0)
    assert np.allclose(saved.target_exposure_dynamic, actual.target_exposure, atol=1e-14, rtol=0)


def test_cost_accounting_is_fixed_and_monotonic():
    metrics = pd.read_csv(OUT / "r4_cost_sensitivity.csv")
    dynamic = metrics.loc[metrics.strategy.eq("R4_STRESS_DYNAMIC")].set_index("cost_case")
    assert dynamic.loc["BASELINE", "cost_rate"] == .001
    assert dynamic.loc["TWO_X", "cost_rate"] == .002
    assert dynamic.loc["ADVERSE", "cost_rate"] == .003
    assert dynamic.loc["BASELINE", "total_return"] >= dynamic.loc["TWO_X", "total_return"] >= dynamic.loc["ADVERSE", "total_return"]


def test_placebo_contract_preserves_count_and_valid_shifts():
    placebo = pd.read_parquet(OUT / "r4_placebo_distribution.parquet")
    assert len(placebo) == 500
    assert placebo.placebo.nunique() == 500
    assert placebo["shift"].between(20, 903).all()


def test_episode_attribution_reconciles_audit():
    audit = json.loads((OUT / "r4_audit.json").read_text())
    episodes = pd.read_csv(OUT / "r4_episode_attribution.csv")
    unique = episodes.drop_duplicates("episode_id")
    assert np.isclose(unique.loc[unique.additive_delta.gt(0), "additive_delta"].sum(), audit["episode_summary"]["total_helpful"])
    assert np.isclose(unique.loc[unique.additive_delta.lt(0), "additive_delta"].sum(), audit["episode_summary"]["total_harmful"])


def test_classification_gate_and_firewall_are_consistent():
    summary = json.loads((OUT / "r4_final_summary.json").read_text())
    assert summary["A2_RISK_CONTROL_R4_PRE2026_CLASSIFICATION"] == "D_NO_MATERIAL_STRUCTURAL_VALUE"
    assert summary["R4_2026_AUTHORIZED"] is False
    assert summary["2026_R4_OUTCOME_READ_COUNT"] == 0
    assert summary["NEXT_AUTHORIZED_STEP"] == "PRESERVE_R4_VALIDATION_AND_STOP;DO_NOT_OPEN_2026"
