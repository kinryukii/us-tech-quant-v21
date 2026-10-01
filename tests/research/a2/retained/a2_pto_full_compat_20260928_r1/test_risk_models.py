"""Risk compatibility checks with synthetic histories; no economic evaluation."""
import numpy as np
import pandas as pd
import pytest

import risk_models as risk


def test_psd_stable_order_and_floor():
    covariance = risk.psd([[1., 1.1], [1.1, 1.]])
    assert np.linalg.eigvalsh(covariance).min() >= 1e-10 - 1e-12
    np.testing.assert_allclose(covariance, covariance.T)
    with pytest.raises(ValueError, match="NONFINITE_RISK_MATRIX"):
        risk.psd([[np.nan]])


def test_scale_sampling_matches_common_and_purges_equal_cutoff():
    dates = pd.to_datetime(["2024-12-27", "2024-12-28", "2024-12-29"])
    frame = pd.DataFrame({"signal_date": dates, "label_end_date": pd.to_datetime(
        ["2024-12-30", "2025-01-01", "2024-12-31"]), "ticker": ["A", "B", "C"],
        "label_available": True, "new_buy_eligible": [True, True, False], "y_next_open": .01})
    for name in risk.FEATURES:
        frame[name] = .1
    selected = risk.sample_scale_training(frame, "2025-01-01")
    assert selected.ticker.tolist() == ["A"]
    assert selected.label_end_date.lt("2025-01-01").all()
    changed = frame.copy()
    changed.y_next_open = -.02
    assert risk.sample_scale_training(changed, "2025-01-01").sample_hash.tolist() == selected.sample_hash.tolist()


def synthetic_bank():
    random = np.random.default_rng(7)
    joint_z = random.normal(size=(252, 3))
    joint_z[:, 1] = .6 * joint_z[:, 0] + .8 * joint_z[:, 1]
    cov = np.array([[.0004, .00018, .00006], [.00018, .0009, .00004], [.00006, .00004, .000225]])
    bank = risk.RiskBank.__new__(risk.RiskBank)
    bank.lookup = {"A": 0, "B": 1, "C": 2}
    bank.data = {"unknown_sigma": np.array(.05), "baseline_sigma": np.array([.02, .03, .015]),
                 "joint_z": joint_z, "garch_sigma": np.array([.022, .033, .017]),
                 "gjr_sigma": np.array([.024, .031, .016]),
                 **{f"cov_{name}": cov.copy() for name in (
                     "diagonal", "samplecov", "lw", "oas", "pca5", "fa5", "lw_oas")}}
    bank.data["cov_diagonal"] = np.diag(np.diag(cov))
    bank.fallback_counts = {"unknown_ticker_queries": 0, "missing_supervised_features": 0}
    bank.scenario_approximations = {"calls": 0, "rank_deficient_calls": 0}
    return bank


def test_covariance_alignment_unknown_and_garch_psd():
    bank = synthetic_bank()
    covariance = bank.covariance("lw", ["B", "UNKNOWN", "A"])
    np.testing.assert_allclose(np.diag(covariance), [.0009, .0025, .0004])
    assert covariance[0, 2] == .00018 and covariance[0, 1] == 0.
    assert np.linalg.eigvalsh(bank.covariance("lw_gjr11", ["B", "A"])).min() > 0
    with pytest.raises(ValueError, match="DUPLICATE"):
        bank.covariance("lw", ["A", "A"])


def test_joint_scenarios_have_selected_covariance_and_mean():
    bank = synthetic_bank()
    names = ["B", "A", "C"]
    for specification in ["diagonal", "lw", "lw_garch11", "lw_gjr11"]:
        mu = np.array([.01, -.002, .004])
        scenarios = bank.scenarios(specification, names, mu=mu)
        assert scenarios.shape == (252, 3)
        np.testing.assert_allclose(scenarios.mean(axis=0), mu, atol=1e-12)
        np.testing.assert_allclose(np.cov(scenarios, rowvar=False), bank.covariance(specification, names), atol=1e-12)
    assert bank.scenario_approximations["rank_deficient_calls"] == 0


def test_unknown_joint_scenario_rank_approximation_is_visible():
    bank = synthetic_bank()
    scenarios = bank.scenarios("lw", ["MISSING1", "MISSING2"], mu=[0., 0.])
    assert np.isfinite(scenarios).all()
    assert bank.scenario_approximations["rank_deficient_calls"] == 1
