"""Focused contracts for aggregated stock-risk R5."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).with_name("a2_risk_r5.py")
SPEC = importlib.util.spec_from_file_location("a2_risk_r5", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_authoritative_hash_and_zero_model_contract() -> None:
    assert MODULE.R3.R1.sha256_file(MODULE.R3R_OOF_PATH) == MODULE.EXPECTED_R3R_HASH
    assert MODULE.REFERENCE_CANDIDATE == "LGBM_STOCK_Q90_1"


def test_tail_load_is_only_equal_weight_top20_mean() -> None:
    selected = MODULE.load_authoritative_oof()
    tail = MODULE.aggregate_tail_load(selected)
    expected = selected.groupby("signal_date").predicted_q90.mean().sort_index()
    actual = tail.set_index("signal_date").portfolio_tail_load.sort_index()
    pd.testing.assert_series_equal(actual, expected, check_names=False)
    assert selected.groupby("signal_date").size().eq(20).all()


def test_fold_training_threshold_input_is_incomplete() -> None:
    selected = MODULE.load_authoritative_oof()
    tail = MODULE.aggregate_tail_load(selected)
    _, score_panel, daily, _, _ = MODULE.R3.build_panels()
    all_outcomes = MODULE.portfolio_outcomes(score_panel.signal_date.drop_duplicates(), daily)
    availability = MODULE.training_threshold_availability(all_outcomes, tail, pd.DatetimeIndex(daily.execution_date))
    assert len(availability) == 5
    assert (~availability.threshold_available).all()
    assert availability.missing_training_tail_load_dates.gt(0).all()


def test_all_oof_inputs_are_pre2026_and_purged() -> None:
    selected = MODULE.load_authoritative_oof()
    assert selected.signal_date.lt(pd.Timestamp("2026-01-01")).all()
    assert (selected.information_date < selected.signal_date).all()
    assert (selected.train_max_target_end < selected.embargo_cutoff).all()
