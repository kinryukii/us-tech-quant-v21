"""Focused contract tests for A2 RISK-ML-R2."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("a2_risk_ml_r2.py")
SPEC = importlib.util.spec_from_file_location("a2_risk_ml_r2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_feature_and_candidate_caps() -> None:
    assert MODULE.MARKET_FEATURES == MODULE.R1.FEATURES
    assert len(MODULE.MARKET_FEATURES) == 14
    assert len(MODULE.PORTFOLIO_FEATURES) == 4
    assert len(MODULE.FEATURES) == 18 <= 22
    assert len({c.family for c in MODULE.CANDIDATES}) == 3
    assert len(MODULE.CANDIDATES) == 6 <= 9


def test_portfolio_state_is_prior_close_and_complete() -> None:
    matrix, _, _ = MODULE.build_r2_matrix()
    assert matrix["portfolio_information_date"].eq(matrix["market_date"]).all()
    assert matrix["portfolio_information_date"].lt(matrix["signal_date"]).all()
    assert matrix["top20_count"].eq(20).all()
    assert not matrix[MODULE.FEATURES].isna().any().any()
    assert matrix["path_end_date"].max() < MODULE.TRAINING_CUTOFF


def test_rolling_q90_uses_only_matured_history() -> None:
    matrix, daily, _ = MODULE.build_r2_matrix()
    sessions = MODULE.pd.DatetimeIndex(daily["date"])
    train, valid, cutoff = MODULE.R1B.fold_split(matrix, sessions, *MODULE.FOLDS[0][1:])
    baseline = MODULE.rolling_unconditional_q90(matrix, valid.head(3))
    assert len(baseline) == 3 and np.isfinite(baseline).all()
    assert train["path_end_date"].max() < cutoff


def test_vol_target_is_fixed_and_capped() -> None:
    vol = np.array([0.10, 0.15, 0.30])
    multiplier = np.minimum(1.0, MODULE.VOL_TARGET / vol)
    assert np.allclose(multiplier, [1.0, 1.0, 0.5])
    assert MODULE.PRIMARY_QUANTILE == 0.90
