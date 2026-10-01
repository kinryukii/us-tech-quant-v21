"""Tests of output semantics, group labels, and serialization contracts."""
import joblib
import numpy as np
import pandas as pd
import pytest

from predictors import (NAMES, POINT_NAMES, PROBABILITY_NAMES, QUANTILE_NAMES,
                        DISTRIBUTION_NAMES, RANK_NAMES, fit, predict_raw, rank_training_data)


def fixture():
    rng = np.random.default_rng(123)
    x = rng.normal(size=(400, 32))
    y = .015*x[:, 0] + .005*rng.normal(size=400)
    dates = np.repeat(pd.date_range("2023-01-02", periods=20), 20)
    return x, y, dates


def test_ridge_units_and_joblib_roundtrip(tmp_path):
    x, y, dates = fixture()
    model = fit("ridge", x, y, dates)
    raw = predict_raw(model, x)
    assert set(raw) == {"raw"}
    assert raw["raw"].shape == y.shape
    assert abs(raw["raw"].mean()-y.mean()) < 1e-8
    path = tmp_path / "ridge.joblib"
    joblib.dump(model, path)
    np.testing.assert_array_equal(raw["raw"], predict_raw(joblib.load(path), x)["raw"])


def test_probability_keeps_probability_object():
    x, y, dates = fixture()
    model = fit("logistic", x, y, dates)
    raw = predict_raw(model, x)
    assert set(raw) == {"p"}
    assert ((raw["p"] >= 0) & (raw["p"] <= 1)).all()
    assert np.corrcoef(raw["p"], (y > 0).astype(int))[0, 1] > .5


def test_rank_bins_use_within_date_order():
    x = np.zeros((6, 32))
    x[:, 0] = np.arange(6)
    dates = ["2023-01-03", "2023-01-02", "2023-01-03", "2023-01-02", "2023-01-03", "2023-01-02"]
    xx, relevance, sizes = rank_training_data(x, np.array([10, -.1, 20, -.2, 30, -.3]), dates)
    np.testing.assert_array_equal(sizes, [3, 3])
    assert relevance[0] > relevance[1] > relevance[2]
    assert relevance[3] < relevance[4] < relevance[5]
    np.testing.assert_array_equal(xx[:, 0], [1, 3, 5, 0, 2, 4])


def test_invalid_train_observation_is_rejected():
    x, y, dates = fixture()
    x[2, 1] = np.nan
    with pytest.raises(ValueError, match="NONFINITE"):
        fit("ridge", x, y, dates)


def test_predeclared_specification_counts():
    assert len(NAMES) == 31
    assert len(NAMES) + 2*len(QUANTILE_NAMES) == 43
    assert len(POINT_NAMES) == 13 and len(PROBABILITY_NAMES) == 7
    assert len(DISTRIBUTION_NAMES) == 3 and len(RANK_NAMES) == 2
