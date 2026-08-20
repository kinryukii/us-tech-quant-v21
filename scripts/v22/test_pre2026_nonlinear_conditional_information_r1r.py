from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PATH = Path(__file__).with_name("pre2026_nonlinear_conditional_information_r1r.py")
spec = importlib.util.spec_from_file_location("pre2026_r1r", PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_event_level_singleton_timestamps_pass_and_do_not_need_date_groups():
    events = pd.DataFrame({"sample_id": [f"s{i}" for i in range(1197)], "prediction": np.arange(1197, dtype=float)})
    ranked = mod.event_buckets(events, "prediction")
    assert len(ranked) == 1197
    assert ranked.quintile.min() == 1 and ranked.quintile.max() == 5


def test_2026_signal_and_crossing_target_are_rejected():
    frame = pd.DataFrame({"signal_date": pd.to_datetime(["2025-12-31T10:00:00Z", "2026-01-01T00:00:00Z"]), "target_end_timestamp": pd.to_datetime(["2026-01-01T00:01:00Z", "2025-12-31T10:00:00Z"])})
    eligible, signal_excluded, target_excluded = mod.r1.eligibility(frame)
    assert eligible.empty and signal_excluded == target_excluded == 1


def test_chronology_and_purge_are_strict():
    start = pd.Timestamp("2024-06-01T00:00:00Z")
    train = pd.DataFrame({"signal_date": pd.to_datetime(["2024-05-01T00:00:00Z", "2024-05-02T00:00:00Z"]), "target_end_timestamp": pd.to_datetime(["2024-05-31T23:59:00Z", "2024-06-01T00:00:00Z"])})
    kept = mod.r1.purge_train(train, start)
    assert len(kept) == 1 and (kept.signal_date < start).all() and (kept.target_end_timestamp < start).all()


def test_fold_local_quintiles_and_ties_are_deterministic():
    events = pd.DataFrame({"sample_id": ["z", "a", "y", "b", "x", "c", "w", "d", "v", "e"], "prediction": [1.0] * 10})
    first, second = mod.event_buckets(events, "prediction"), mod.event_buckets(events, "prediction")
    assert first.equals(second)
    assert first.loc[first.sample_id == "a", "quintile"].item() == 1
    assert first.loc[first.sample_id == "z", "quintile"].item() == 5


def test_preprocessing_is_fold_local():
    train, valid = pd.DataFrame({"x": [0.0, 2.0], "y": [0.0, 1.0]}), pd.DataFrame({"x": [1000.0]})
    model = mod.r1.Pipeline([("imputer", mod.r1.SimpleImputer(strategy="median")), ("scaler", mod.r1.StandardScaler()), ("model", mod.r1.Ridge(**mod.r1.RIDGE_CONFIG))]).fit(train[["x"]], train.y)
    assert model.named_steps["imputer"].statistics_[0] == pytest.approx(1.0)
    assert model.named_steps["scaler"].mean_[0] == pytest.approx(1.0)
    assert model.predict(valid)[0] != pytest.approx(0.0)


def test_preregistered_a_b_c_classification():
    ridge = {"oof_rank_spearman": .01, "q5_q1_mean": .01, "q5_mean": .02, "q5_median": .02, "q5_cvar10": -.01}
    hgb_a = {"oof_rank_spearman": .03, "q5_q1_mean": .03, "q5_mean": .03, "q5_median": .02, "q5_cvar10": -.005}
    fold_a = pd.DataFrame({"hgb_spearman": [2,2,2,2,0], "ridge_spearman": [1,1,1,1,1], "hgb_q5_q1_mean": [.1,.1,.1,.1,-.1], "ridge_q5_q1_mean": [0]*5})
    assert mod.classify(ridge, hgb_a, fold_a).startswith("A_")
    hgb_b = dict(hgb_a); hgb_b["q5_median"] = 0
    fold_b = pd.DataFrame({"hgb_spearman": [2,2,0,0,0], "ridge_spearman": [1,1,1,1,1], "hgb_q5_q1_mean": [.1,.1,.1,-.1,-.1], "ridge_q5_q1_mean": [0]*5})
    assert mod.classify(ridge, hgb_b, fold_b).startswith("B_")
    assert mod.classify(ridge, dict(ridge), fold_b).startswith("C_")
