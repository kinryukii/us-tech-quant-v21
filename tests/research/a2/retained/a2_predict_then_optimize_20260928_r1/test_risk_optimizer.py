"""Synthetic causal, marginal, constraint and numerical optimizer checks."""
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import rankdata

from risk_models import (RiskBank, RISK_NAMES, prepare_returns, estimate_matrices,
                         MIN_DAILY_VOL, UNKNOWN_DAILY_VOL)
from optimizers import (solve_batch, project_box_budget, empirical_cvar,
                        select_top20, OptimizeTop20)


def synthetic_bank():
    bank = RiskBank("validation", load=False)
    rng = np.random.default_rng(23)
    returns = rng.normal(size=(252, 8)) + rng.normal(size=(252, 1)) * .7
    vol = np.linspace(.015, .03, 8)
    cov = np.cov(returns, rowvar=False)
    corr = cov / np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
    bank.arrays = {"tickers": np.array(list("ABCDEFGH")), "daily_vol": vol,
                   "rank_uniforms": np.column_stack([rankdata(returns[:, i]) / 253 for i in range(8)]),
                   "market_rank_uniforms": rankdata(returns.mean(axis=1)) / 253}
    for name in RISK_NAMES:
        if name not in {"lw_hgb_vol", "lw_mlp_vol"}:
            bank.arrays[f"cov_{name}"] = (np.eye(8) if name == "diag" else corr) * np.outer(vol, vol)
    bank.lookup = {name: i for i, name in enumerate(bank.arrays["tickers"])}
    bank.coverage_lookup = {name: 252 for name in bank.lookup}
    bank.features = [f"x{i}" for i in range(32)]
    return bank


def test_risk_time_boundary_is_filtered_before_tail_selection():
    dates = pd.bdate_range(end="2024-12-31", periods=253)
    prices = pd.DataFrame({"trade_date": np.r_[dates.to_numpy(), np.datetime64("2026-01-02")],
                           "ticker": "A", "close": np.r_[np.arange(253) + 100., 1e12]})
    returns = prepare_returns(prices, "2025-01-01")
    assert len(returns) == 252 and returns.index.max() == pd.Timestamp("2024-12-31")
    assert returns.max().max() < .011


def test_statistical_members_are_psd_and_keep_insufficient_history_coverage():
    rng = np.random.default_rng(31)
    returns = pd.DataFrame(rng.normal(0, .003, (252, 8)), columns=list("ABCDEFGH"))
    returns.loc[:140, "H"] = np.nan
    arrays, coverage, details = estimate_matrices(returns)
    assert "H" not in arrays["tickers"]
    assert not coverage.set_index("ticker").loc["H", "history_qualified"]
    assert details["securities_insufficient"] == 1
    for key, matrix in arrays.items():
        if key.startswith("cov_"):
            assert np.linalg.eigvalsh(matrix).min() > 0
            assert np.diag(matrix).min() >= MIN_DAILY_VOL ** 2 - 1e-12


def test_unknown_stock_stays_in_covariance_and_scenario_rank_is_disclosed():
    bank = synthetic_bank()
    covariance, metadata = bank.covariance(["A", "UNKNOWN1", "UNKNOWN2"], return_metadata=True)
    assert covariance.shape == (3, 3)
    assert covariance[1, 1] == covariance[2, 2] == UNKNOWN_DAILY_VOL ** 2
    assert covariance[1, 2] == 0
    samples, detail = bank.scenarios(["A", "UNKNOWN1", "UNKNOWN2"], np.zeros(3), return_metadata=True)
    assert detail["rank_deficient"] and not detail["exact_dependence_match_claimed"]
    assert samples.shape == (64, 3)
    assert np.std(samples[:, 1:], axis=0, ddof=1).min() >= UNKNOWN_DAILY_VOL - 1e-12
    assert set(metadata["unknown_tickers"]) == {"UNKNOWN1", "UNKNOWN2"}


def test_native_sigma_and_learned_risk_scale_both_affect_scenarios():
    bank = synthetic_bank()
    names, mu = ["A", "B"], np.array([.001, -.002])
    original = bank.scenarios(names, mu, {"sigma": [.02, .03]})
    doubled_native = bank.scenarios(names, mu, {"sigma": [.04, .06]})
    np.testing.assert_allclose(doubled_native - mu, 2 * (original - mu), atol=1e-12)
    original_vol = np.sqrt(np.diag(bank.covariance(names)))
    doubled_risk = bank.scenarios(names, mu, {"sigma": [.02, .03]},
                                   risk_name="lw_hgb_vol", signalvol=2 * original_vol)
    np.testing.assert_allclose(doubled_risk - mu, 2 * (original - mu), atol=1e-12)
    np.testing.assert_allclose(original.mean(axis=0), mu, atol=1e-12)


def test_mixed_native_quantile_and_point_nan_fields_are_compatible():
    bank = synthetic_bank()
    samples, metadata = bank.scenarios(["A", "B"], np.array([.001, .002]),
        {"sigma": [.02, .03], "q": np.array([[-.02, .001, .04], [np.nan, np.nan, np.nan]])},
        return_metadata=True)
    assert np.isfinite(samples).all()
    assert metadata["native_quantile_support_count"] == 1
    assert metadata["sigma_fallback_support_count"] == 1


def test_projection_respects_budget_upper_and_l1_current_kink():
    result = project_box_budget(np.array([[.3, .1, -.1], [.1, .2, .3]]),
        upper=np.array([[.1, .02, 0.], [.04, .04, .04]]), budget=[.08, .1],
        current=np.array([[.05, .01, 0.], [0., 0., 0.]]), penalty=.01)
    assert (result >= 0).all()
    assert (result.sum(axis=1) <= np.array([.08, .1]) + 1e-9).all()
    assert result[0, 1] <= .02 and result[0, 2] == 0


def test_batch_mv_matches_analytic_solution_and_reserved_cross_changes_it():
    mu = np.array([[.00102, .00104, -.01], [.00102, .00104, -.01]])
    covariance = np.broadcast_to(np.eye(3) * .0001, (2, 3, 3))
    w, metadata = solve_batch(mu, covariance, method="mv")
    np.testing.assert_allclose(w, [[.05, .1, 0.], [.05, .1, 0.]], atol=2e-8)
    assert all(row["iterations"] == 80 and row["feasible"] for row in metadata)
    changed, _ = solve_batch(mu[:1], covariance[:1], method="mv",
                             locked_cross=np.array([[.00008, .00008, 0.]]), locked_variance=[.001])
    assert changed[0, :2].sum() < w[0, :2].sum()


def test_random_mv_objective_agrees_with_independent_slsqp():
    rng = np.random.default_rng(40)
    x = rng.normal(size=(20, 20))
    covariance = x.T @ x * .00002 + np.eye(20) * .0001
    mu = rng.uniform(.0005, .004, 20)
    current = rng.uniform(0, .08, 20)
    w, metadata = solve_batch(mu, covariance, method="mv", current=current)
    def objective(weights):
        return float(-mu @ weights + 2 * weights @ covariance @ weights + .001 * np.abs(weights - current).sum())
    reference = minimize(objective, w[0], method="SLSQP", bounds=[(0, .1)] * 20,
                         constraints={"type": "ineq", "fun": lambda weights: .95 - weights.sum()},
                         options={"maxiter": 300, "ftol": 1e-12})
    assert reference.success
    assert objective(w[0]) - reference.fun < 2e-6
    assert metadata[0]["global_optimum_claimed"] is False


def test_robust_and_joint_cvar_keep_zero_when_objective_favors_cash():
    mu = np.full((2, 4), .001)
    covariance = np.broadcast_to(np.eye(4) * .0004, (2, 4, 4))
    robust, report = solve_batch(mu, covariance, method="robust")
    assert robust.sum() == 0
    scenario = np.full((2, 64, 4), .002)
    scenario[:, :8, :] = -.04
    cvar, detail = solve_batch(mu, covariance, method="cvar", scenarios=scenario)
    assert cvar.sum() == 0
    assert all(z["iterations"] == 80 and z["status"] in {"approx_converged", "approx_unconverged"}
               for z in report + detail)


def test_joint_cvar_positive_constant_scenario_uses_feasible_budget():
    mu = np.full((3, 20), .003)
    scenario = np.full((3, 64, 20), .003)
    weights, report = solve_batch(mu, np.broadcast_to(np.eye(20) * .0001, (3, 20, 20)),
                                  method="cvar", scenarios=scenario)
    np.testing.assert_allclose(weights.sum(axis=1), .95, atol=1e-8)
    assert max(z["optimality_gap_bound"] for z in report) < 1e-6


def test_empirical_cvar_uses_fractional_tail_mass():
    loss = np.arange(64.)
    expected = (sum(range(58, 64)) + .4 * 57) / 6.4
    assert abs(float(empirical_cvar(loss)) - expected) < 1e-12


def test_top20_ranking_and_context_reserved_capacity_are_obeyed():
    names = [f"S{i:02}" for i in range(30)]
    mu = np.full(30, .001)
    ix = select_top20(names[::-1], mu)
    assert np.asarray(names[::-1])[ix].tolist() == names[:20]
    day = pd.DataFrame({"ticker": names, "new_buy_eligible": True})
    ctx = SimpleNamespace(current_weights={"S00": .02}, buy_restricted_tickers=("S00",),
                          available_slots=17, available_weight=.81)
    targets, metadata = OptimizeTop20("equal_top20", "none")(day, ctx, mu)
    assert len(targets) <= 17 and sum(targets.values()) <= .81 + 1e-8
    assert targets.get("S00", 0) <= .02
    assert metadata["full_pool_rows"] == 30 and metadata["risk_member"] == "none"
