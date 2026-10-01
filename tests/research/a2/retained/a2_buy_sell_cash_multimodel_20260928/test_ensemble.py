import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("new_ensemble", Path(__file__).with_name("ensemble_train.py"))
meta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(meta)


def test_optimizer_prefers_better_risk_adjusted_returns_with_fixed_bounds():
    rng = np.random.default_rng(31)
    returns = rng.normal(0, .002, (160, 6))
    returns[:, 0] += .003
    returns[:, 1] -= .003
    weights, report = meta.solve_weights(returns)
    assert abs(weights.sum() - 1) < 1e-9
    assert weights.min() >= .05 - 1e-9 and weights.max() <= .35 + 1e-9
    assert weights[0] > weights[1]
    assert report["objective_utility"] >= report["equal_weight_utility"]
    assert report["maximum_kkt_error"] < 1e-5


def test_identical_returns_stay_equal_weight():
    returns = np.tile(np.linspace(-.01, .01, 100)[:, None], (1, 6))
    weights, _ = meta.solve_weights(returns)
    np.testing.assert_allclose(weights, np.full(6, 1 / 6), atol=1e-8)


def test_unknown_day_excludes_all_methods_without_zero_fill():
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"])
    frames = {}
    for name in meta.METHODS:
        frames[name] = pd.DataFrame({"date": dates, "certified_nav": [100, 101, 102, 103, 104],
                                     "valuation_status": ["certified"] * 5,
                                     "net_return": [np.nan, .01, 102 / 101 - 1, 103 / 102 - 1, 104 / 103 - 1]})
    frames[meta.METHODS[0]].loc[2, ["certified_nav", "net_return"]] = np.nan
    frames[meta.METHODS[0]].loc[2, "valuation_status"] = "unknown"
    frames[meta.METHODS[0]].loc[3, "net_return"] = np.nan
    selected, _, report = meta.complete_case_returns(frames, "2025-07-01")
    assert selected.index.tolist() == [dates[1], dates[4]]
    assert report["excluded_entire_dates"] == 3


def test_validation_meta_never_uses_second_half():
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-07-01"])
    frames = {name: pd.DataFrame({"date": dates, "certified_nav": [100, 101, 102, 103],
                                 "valuation_status": ["certified"] * 4,
                                 "net_return": [np.nan, .01, 102 / 101 - 1, 103 / 102 - 1]}) for name in meta.METHODS}
    first, _, _ = meta.complete_case_returns(frames, "2025-07-01")
    for frame in frames.values():
        frame.loc[3, "net_return"] = -999
        frame.loc[3, "certified_nav"] = -999
    second, _, _ = meta.complete_case_returns(frames, "2025-07-01")
    pd.testing.assert_frame_equal(first, second)


def test_no_silent_nan_optimizer_inputs():
    with pytest.raises(ValueError, match="INVALID_META_RETURN_MATRIX"):
        meta.solve_weights(np.full((30, 6), np.nan))


@pytest.mark.skipif(not (meta.OUT / "TRAIN_RECEIPT.json").exists(), reason="real meta fit awaits OOS ledger completion")
@pytest.mark.parametrize("stage", list(meta.STAGES))
def test_frozen_weights_have_certified_training_boundary(stage):
    weights = meta.load_weights(stage)
    assert list(weights) == meta.METHODS
    assert abs(sum(weights.values()) - 1) < 1e-8
    artifact = meta.read(meta.OUT / f"{stage}_weights.json")
    assert artifact["selection"]["last_return"] < meta.STAGES[stage]
    receipt = meta.read(meta.OUT / "TRAIN_RECEIPT.json")
    assert receipt["fit_2026_rows"] == 0 and receipt["2026_outcomes_read"] is False
