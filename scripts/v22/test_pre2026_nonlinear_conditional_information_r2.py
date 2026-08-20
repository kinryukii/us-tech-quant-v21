from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PATH = Path(__file__).with_name("pre2026_nonlinear_conditional_information_r2.py")
spec = importlib.util.spec_from_file_location("pre2026_r2", PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_config_diff_allows_only_architecture_leaf_repair():
    old = dict(mod.r1.HGB_CONFIG); new = dict(old); new["min_samples_leaf"] = 50
    assert mod.config_diff(old, new) == {"min_samples_leaf": [500, 50]}
    new["max_depth"] = 3
    assert set(mod.config_diff(old, new)) == {"max_depth", "min_samples_leaf"}


def test_199_row_leaf_50_hgb_can_make_nonconstant_predictions():
    x = pd.DataFrame({"x": np.arange(199, dtype=float)})
    y = (x.x >= 100).astype(float)
    model = mod.r1.Pipeline([("imputer", mod.r1.SimpleImputer(strategy="median")), ("model", mod.r1.HistGradientBoostingRegressor(**({**mod.r1.HGB_CONFIG, "min_samples_leaf": 50})))]).fit(x, y)
    assert mod.nonconstant(model.predict(x))["hgb_nonconstant"] is True


def test_constant_detector_and_architecture_gate():
    assert mod.nonconstant(np.ones(10))["hgb_nonconstant"] is False
    assert mod.nonconstant(np.array([0.0, 1.0]))["hgb_nonconstant"] is True
    assert mod.architecture_gate(pd.DataFrame({"hgb_nonconstant": [True] * 5})) is True
    assert mod.architecture_gate(pd.DataFrame({"hgb_nonconstant": [True] * 4 + [False]})) is False


def test_2026_and_target_window_eligibility_rejections():
    frame = pd.DataFrame({"signal_date": pd.to_datetime(["2026-01-01T00:00:00Z", "2025-12-31T10:00:00Z"]), "target_end_timestamp": pd.to_datetime(["2025-12-31T10:00:00Z", "2026-01-01T00:00:00Z"])})
    valid, excluded_signal, excluded_target = mod.r1.eligibility(frame)
    assert valid.empty and excluded_signal == excluded_target == 1


def test_purge_and_quintile_ties_are_deterministic():
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    train = pd.DataFrame({"target_end_timestamp": pd.to_datetime(["2023-12-31T23:59:00Z", "2024-01-01T00:00:00Z"])})
    assert len(mod.r1.purge_train(train, start)) == 1
    events = pd.DataFrame({"sample_id": ["z", "a", "y", "b", "x"], "prediction": [1.0] * 5})
    first, second = mod.r1r.event_buckets(events, "prediction"), mod.r1r.event_buckets(events, "prediction")
    assert first.equals(second) and first.loc[first.sample_id == "a", "quintile"].item() == 1


def test_r1r_classification_rules_remain_unchanged():
    ridge = {"oof_rank_spearman": .01, "q5_q1_mean": .01, "q5_mean": .02, "q5_median": .02, "q5_cvar10": -.01}
    hgb = {"oof_rank_spearman": .03, "q5_q1_mean": .03, "q5_mean": .03, "q5_median": .02, "q5_cvar10": -.005}
    fold = pd.DataFrame({"hgb_spearman": [2,2,2,2,0], "ridge_spearman": [1,1,1,1,1], "hgb_q5_q1_mean": [.1,.1,.1,.1,-.1], "ridge_q5_q1_mean": [0]*5})
    assert mod.r1r.classify(ridge, hgb, fold).startswith("A_")
