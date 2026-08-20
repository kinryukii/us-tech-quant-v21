"""Focused contracts for A2 STOCK-RISK ML R3."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("a2_stock_risk_ml_r3.py")
SPEC = importlib.util.spec_from_file_location("a2_stock_risk_ml_r3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_caps_and_stock_feature_majority() -> None:
    assert len(MODULE.FEATURES) == 22 <= 25
    assert len(MODULE.STOCK_FEATURES) == 18
    assert len(MODULE.MARKET_FEATURES) == 4 <= 5
    assert len({c.family for c in MODULE.CANDIDATES}) == 3
    assert len(MODULE.CANDIDATES) == 6 <= 9


def test_panel_timing_membership_and_firewall() -> None:
    panel, score_panel, _, _, _ = MODULE.build_panels()
    assert panel.groupby("signal_date").size().eq(20).all()
    assert score_panel.groupby("signal_date").size().eq(20).all()
    assert panel["information_date"].lt(panel["signal_date"]).all()
    assert panel["target_end_date"].lt(MODULE.TRAINING_CUTOFF).all()
    assert not panel[MODULE.FEATURES].isna().any().any()


def test_date_fold_and_purge_contract() -> None:
    panel, _, daily, _, _ = MODULE.build_panels()
    sessions = MODULE.pd.DatetimeIndex(daily["execution_date"])
    train, valid, cutoff = MODULE.fold_split(panel, sessions, *MODULE.FOLDS[0][1:])
    assert train["target_end_date"].max() < cutoff
    assert set(train["signal_date"]).isdisjoint(set(valid["signal_date"]))
    assert valid.groupby("signal_date").size().eq(20).all()


def test_position_mappings_do_not_exclude_or_redistribute() -> None:
    percentile = np.array([0.10, 0.71, 0.86, 0.96])
    assert np.array_equal(MODULE.R1.direct_multiplier(percentile), [1.0, 0.75, 0.50, 0.25])
    vol = np.array([0.20, 0.40, 0.80, 2.00])
    multiplier = np.clip(MODULE.STOCK_VOL_TARGET / vol, MODULE.STOCK_VOL_MIN_MULTIPLIER, 1.0)
    assert np.allclose(multiplier, [1.0, 1.0, 0.5, 0.25])
    assert np.all(multiplier > 0)


def test_overlay_turnover_is_nonnegative_and_zero_for_raw() -> None:
    date_1, date_2 = MODULE.pd.Timestamp("2025-01-02"), MODULE.pd.Timestamp("2025-01-03")
    raw = {date_1: {"A": 0.05, "B": 0.05}, date_2: {"A": 0.05, "C": 0.05}}
    controlled = {date_1: {"A": 0.05, "B": 0.025}, date_2: {"A": 0.025, "C": 0.05}}
    assert MODULE.overlay_turnover(raw, raw) == 0.0
    assert MODULE.overlay_turnover(controlled, raw) == 0.025
