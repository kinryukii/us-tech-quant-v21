"""Focused contracts for R1 attribution and R1B path risk."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("a2_risk_ml_r1b.py")
SPEC = importlib.util.spec_from_file_location("a2_risk_ml_r1b", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_exact_r1_feature_schema_and_model_caps() -> None:
    assert MODULE.FEATURES == MODULE.R1.FEATURES
    assert len(MODULE.FEATURES) == 14
    assert len({c.family for c in MODULE.CANDIDATES}) == 3
    assert len(MODULE.CANDIDATES) == 6
    assert all(sum(x.family == c.family for x in MODULE.CANDIDATES) <= 3 for c in MODULE.CANDIDATES)


def test_forward_mae_uses_full_compounded_path() -> None:
    returns = np.array([0.02, -0.03, -0.04, 0.01, 0.02])
    path = np.cumprod(1 + returns) - 1
    assert np.isclose(MODULE.forward_5d_mae(returns), max(0.0, -path.min()))
    assert MODULE.forward_5d_mae(np.full(5, 0.01)) == 0.0


def test_constant_control_matches_mean_gross_exposure() -> None:
    raw = np.array([0.01, -0.02, 0.005])
    gross = np.ones(3)
    multiplier = np.array([1.0, 0.5, 0.75])
    _, _, constant, mean_gross = MODULE.constant_control(raw, gross, multiplier)
    assert np.isclose(constant, 0.75)
    assert np.isclose(mean_gross, 0.75)


def test_purge_embargo_contract() -> None:
    daily = MODULE.load_a2_daily()
    features = MODULE.R1.build_market_features(MODULE.R1.load_pre2026_prices(), MODULE.R1.load_vix(True))
    matrix = MODULE.build_path_matrix(daily, features)
    sessions = MODULE.pd.DatetimeIndex(daily["date"])
    train, valid, cutoff = MODULE.fold_split(matrix, sessions, *MODULE.FOLDS[0][1:])
    assert train["path_end_date"].max() < cutoff
    assert train["path_end_date"].max() < valid["signal_date"].min()
    assert matrix["path_end_date"].max() < MODULE.TRAINING_CUTOFF
