"""Numeric equivalence tests; no real model fitting or 2026 outcome reads."""
import numpy as np
import pytest

import optimizers as reference
import accelerated_solver as accelerated


def _problem(batch=7, n=20, scenarios=64):
    rng = np.random.default_rng(418)
    factors = rng.normal(size=(batch, n + 1, n + 3)) * .005
    joint = factors @ factors.transpose(0, 2, 1)
    fixed_weight = .08
    covariance = joint[:, :n, :n]
    cross = joint[:, :n, n] * fixed_weight
    fixed_variance = joint[:, n, n] * fixed_weight**2
    current = rng.uniform(0, .06, (batch, n))
    budget = rng.uniform(.23, .87, batch)
    upper = rng.uniform(.03, .1, (batch, n))
    upper[::2, ::3] = 0.
    returns = rng.normal(0, .025, (batch, scenarios, n))
    # Joint market factor and fixed holdings make scenario offsets material.
    market = rng.normal(0, .018, (batch, scenarios, 1))
    returns += market
    fixed_returns = market[:, :, 0] * fixed_weight + rng.normal(0, .001, (batch, scenarios))
    return dict(mu=rng.normal(.004, .002, (batch, n)), covariances=covariance,
                upper=upper, budget=budget, current=current, locked_cross=cross,
                locked_variance=fixed_variance, scenarios=returns,
                locked_scenario_returns=fixed_returns)


def _assert_equal(problem, method):
    before = {key: value.copy() for key, value in problem.items() if isinstance(value, np.ndarray)}
    wanted, wanted_meta = accelerated.ORIGINAL_SOLVE_BATCH(**problem, method=method)
    actual, actual_meta = accelerated.solve_batch(**problem, method=method)
    np.testing.assert_allclose(actual, wanted, rtol=0, atol=1e-8)
    for old, new in zip(wanted_meta, actual_meta):
        assert old.keys() == new.keys()
        for key in old:
            if isinstance(old[key], float):
                assert abs(old[key] - new[key]) <= 1e-8, (method, key, old[key], new[key])
            else:
                assert old[key] == new[key], (method, key)
    for key, old in before.items():
        np.testing.assert_array_equal(problem[key], old)
    return actual, actual_meta


@pytest.mark.parametrize("method", ["mv", "robust", "cvar"])
@pytest.mark.parametrize("n", [1, 5, 20])
def test_full_solver_batch_reserved_risk_and_scenarios(method, n):
    weights, metadata = _assert_equal(_problem(n=n), method)
    assert np.isfinite(weights).all()
    assert all(m["iterations"] == 80 and m["feasible"] for m in metadata)


@pytest.mark.parametrize("method", ["mv", "robust", "cvar"])
def test_readonly_noncontiguous_inputs(method):
    problem = _problem(batch=3)
    for key, value in problem.items():
        if value.ndim > 1:
            buffer = np.empty(value.shape[:-1] + (value.shape[-1] * 2,))
            buffer[..., ::2] = value
            problem[key] = buffer[..., ::2]
        problem[key].setflags(write=False)
    _assert_equal(problem, method)


@pytest.mark.parametrize("method", ["mv", "robust", "cvar"])
def test_scalar_constraints_zero_budget_and_degenerate_psd(method):
    problem = dict(mu=np.array([.003, .004, -.005]), covariances=np.zeros((3, 3)),
                   budget=0., upper=.1, current=np.array([.2, .05, 0.]),
                   scenarios=np.full((64, 3), .002), locked_scenario_returns=np.full((1, 64), .003))
    weights, metadata = _assert_equal(problem, method)
    assert weights.sum() < 1e-9 and metadata[0]["iterations"] == 80


def test_hard_cvar_preserves_unconverged_status_and_large_gap():
    _, metadata = _assert_equal(_problem(), "cvar")
    assert any(m["status"] == "approx_unconverged" for m in metadata)
    assert max(m["optimality_gap_bound"] for m in metadata) > 1e-6
    assert all(m["fixed_iterations_no_extension"] and not m["global_optimum_claimed"] for m in metadata)


@pytest.mark.parametrize("method", ["mv", "robust", "cvar", "equal_top20"])
def test_empty_support_metadata(method):
    _assert_equal(dict(mu=np.empty((2, 0))), method)


def test_equal_control_and_robust_alias_keep_public_contract():
    _assert_equal(_problem(), "equal_top20")
    _assert_equal(_problem(batch=1), "robust_mv")


@pytest.mark.parametrize("change,error", [
    ({"mu": np.array([[np.nan]])}, "INVALID_OPTIMIZER_MEANS"),
    ({"upper": -.1}, "INVALID_PORTFOLIO_CONSTRAINTS"),
    ({"budget": .96}, "INVALID_PORTFOLIO_CONSTRAINTS"),
    ({"locked_variance": -.01}, "NON_PSD_PORTFOLIO_RISK"),
])
def test_rejects_same_invalid_inputs(change, error):
    problem = _problem(batch=1)
    problem.update(change)
    for solver in [accelerated.ORIGINAL_SOLVE_BATCH, accelerated.solve_batch]:
        with pytest.raises(ValueError, match=error):
            solver(**problem)


def test_enable_disable_only_replaces_solver():
    original_projection = reference.project_box_budget
    try:
        accelerated.enable()
        assert reference.solve_batch is accelerated.solve_batch
        assert reference.project_box_budget is original_projection
        _assert_equal(_problem(batch=1), "mv")
    finally:
        accelerated.disable()
    assert reference.solve_batch is accelerated.ORIGINAL_SOLVE_BATCH
