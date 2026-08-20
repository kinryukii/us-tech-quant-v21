from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE = Path(__file__).with_name("pre2026_nonlinear_conditional_information_r1.py")
spec = importlib.util.spec_from_file_location("pre2026_nonlinear_r1", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
UTC = "UTC"


def test_2026_signal_and_crossing_target_are_rejected():
    frame = pd.DataFrame({"signal_date": pd.to_datetime(["2025-12-31T10:00:00Z", "2026-01-01T00:00:00Z"]), "target_end_timestamp": pd.to_datetime(["2026-01-01T00:01:00Z", "2025-12-31T10:00:00Z"])})
    eligible, signal_excluded, target_excluded = mod.eligibility(frame)
    assert eligible.empty
    assert signal_excluded == target_excluded == 1


def test_purge_makes_train_target_end_strictly_before_validation_start():
    start = pd.Timestamp("2024-06-01T00:00:00Z")
    train = pd.DataFrame({"target_end_timestamp": pd.to_datetime(["2024-05-31T23:59:00Z", "2024-06-01T00:00:00Z"]), "signal_date": pd.to_datetime(["2024-05-01T00:00:00Z", "2024-05-02T00:00:00Z"])})
    purged = mod.purge_train(train, start)
    assert len(purged) == 1
    assert (purged.target_end_timestamp < start).all()
    assert (purged.signal_date < start).all()


def test_singleton_signal_dates_fail_closed_for_cross_sectional_deciles():
    frame = pd.DataFrame({"signal_date": pd.to_datetime(["2024-01-02T00:00:00Z", "2024-01-03T00:00:00Z"])})
    with pytest.raises(mod.Stop, match="LACKS_CROSS_SECTIONAL"):
        mod.require_cross_section(frame)


def test_fold_local_preprocessing_does_not_use_validation_statistics():
    train = pd.DataFrame({"x": [0.0, 2.0], "y": [0.0, 1.0]})
    valid = pd.DataFrame({"x": [1000.0]})
    model = mod.Pipeline([("imputer", mod.SimpleImputer(strategy="median")), ("scaler", mod.StandardScaler()), ("model", mod.Ridge(**mod.RIDGE_CONFIG))])
    model.fit(train[["x"]], train.y)
    assert model.named_steps["imputer"].statistics_[0] == pytest.approx(1.0)
    assert model.named_steps["scaler"].mean_[0] == pytest.approx(1.0)
    assert model.predict(valid)[0] != pytest.approx(0.0)


def test_deciles_and_fixed_hgb_are_deterministic():
    dates = pd.to_datetime(["2024-01-02T00:00:00Z"] * 10)
    frame = pd.DataFrame({"signal_date": dates, "sample_id": [f"s{i}" for i in range(10)], "target": range(10), "ridge_prediction": range(10), "hgb_prediction": range(10)})
    assert mod.deciles(frame, "ridge_prediction").tolist() == list(range(1, 11))
    assert mod.model_metrics(frame, "hgb")[0] == mod.model_metrics(frame, "hgb")[0]
    x = pd.DataFrame({"x": np.arange(600, dtype=float)}); y = np.arange(600, dtype=float)
    a = mod.Pipeline([("imputer", mod.SimpleImputer(strategy="median")), ("model", mod.HistGradientBoostingRegressor(**mod.HGB_CONFIG))]).fit(x, y)
    b = mod.Pipeline([("imputer", mod.SimpleImputer(strategy="median")), ("model", mod.HistGradientBoostingRegressor(**mod.HGB_CONFIG))]).fit(x, y)
    assert np.array_equal(a.predict(x), b.predict(x))


def test_preregistered_classification_a_b_c():
    base = {"spearman": 0.01, "d10_d1_mean": 0.01, "d10_mean": 0.02, "d10_median": 0.02, "d10_cvar05": -0.01}
    hgb_a = {"spearman": 0.03, "d10_d1_mean": 0.03, "d10_mean": 0.03, "d10_median": 0.02, "d10_cvar05": -0.005}
    folds_a = pd.DataFrame({"hgb_spearman": [2,2,2,2,0], "ridge_spearman": [1,1,1,1,1], "hgb_d10_d1_mean": [.1,.1,.1,.1,-.1], "hgb_d10_mean": [.1]*5, "ridge_d10_mean": [0]*5})
    assert mod.classify(base, hgb_a, folds_a).startswith("A_")
    hgb_b = dict(hgb_a); hgb_b["d10_median"] = 0.0
    folds_b = pd.DataFrame({"hgb_spearman": [2,2,0,0,0], "ridge_spearman": [1,1,1,1,1], "hgb_d10_d1_mean": [.1,.1,.1,-.1,-.1], "hgb_d10_mean": [.1]*5, "ridge_d10_mean": [0]*5})
    assert mod.classify(base, hgb_b, folds_b).startswith("B_")
    assert mod.classify(base, dict(base), folds_b).startswith("C_")
