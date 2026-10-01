"""Equivalent Numba implementation of the frozen 80-round numeric solver.

NumPy performs exactly the reference validation, spectral decomposition and
step construction.  Only the fixed iteration and residual kernels move into
Numba; there is no fastmath, extra iteration, alternative objective or search.
``enable`` replaces optimizers.solve_batch for the existing OptimizeTop20 API.
"""
from __future__ import annotations

import common  # Adds the experiment's isolated third_party runtime directory.
import numpy as np
from numba import njit
import optimizers as reference


ORIGINAL_SOLVE_BATCH = reference.solve_batch


@njit(cache=True)
def _prox_one(values, upper, budget, current, penalty):
    n = len(values)
    result = np.empty(n)
    total = 0.
    for i in range(n):
        delta = values[i] - current[i]
        sign = 1. if delta > 0. else -1. if delta < 0. else 0.
        result[i] = min(upper[i], max(0., current[i] + sign * max(abs(delta) - penalty, 0.)))
        total += result[i]
    if total > budget + 1e-12:
        lo = 0.
        hi = max(np.max(values) + np.max(np.abs(current)) + penalty + 1., 1.)
        for _ in range(36):
            mid = (lo + hi) / 2.
            total = 0.
            for i in range(n):
                delta = values[i] - mid - current[i]
                sign = 1. if delta > 0. else -1. if delta < 0. else 0.
                total += min(upper[i], max(0., current[i] + sign * max(abs(delta) - penalty, 0.)))
            if total > budget:
                lo = mid
            else:
                hi = mid
        for i in range(n):
            delta = values[i] - hi - current[i]
            sign = 1. if delta > 0. else -1. if delta < 0. else 0.
            result[i] = min(upper[i], max(0., current[i] + sign * max(abs(delta) - penalty, 0.)))
    return result


@njit(cache=True)
def _dual_one(values, cap):
    n = len(values)
    lo, hi = np.min(values) - cap, np.max(values)
    for _ in range(36):
        mid = (lo + hi) / 2.
        total = 0.
        for i in range(n):
            total += min(cap, max(0., values[i] - mid))
        if total > 1.:
            lo = mid
        else:
            hi = mid
    mid = (lo + hi) / 2.
    result = np.empty(n)
    total = 0.
    for i in range(n):
        result[i] = min(cap, max(0., values[i] - mid))
        total += result[i]
    for i in range(n):
        result[i] /= total
    return result


@njit(cache=True)
def _variance_one(w, covariance, cross, fixed_variance):
    total = fixed_variance
    quadratic = 0.
    cross_term = 0.
    for i in range(len(w)):
        cross_term += w[i] * cross[i]
        for j in range(len(w)):
            quadratic += w[i] * covariance[i, j] * w[j]
    return max(0., quadratic + 2. * cross_term + total)


@njit(cache=True)
def _objective_one(w, mu, current, covariance, cross, fixed_variance,
                   scenarios, fixed_scenarios, method):
    value = 0.
    for i in range(len(w)):
        value -= mu[i] * w[i]
        value += .001 * abs(w[i] - current[i])
    if method == 2:
        s = len(fixed_scenarios)
        losses = np.empty(s)
        for k in range(s):
            returns = fixed_scenarios[k]
            for i in range(len(w)):
                returns += scenarios[k, i] * w[i]
            losses[k] = -returns
        ordered = np.sort(losses)
        tail_mass = (1. - .9) * s
        whole = int(np.floor(tail_mass + 1e-12))
        fraction = tail_mass - whole
        tail_value = 0.
        for k in range(whole):
            tail_value += ordered[s - 1 - k]
        if fraction > 1e-12:
            tail_value += fraction * ordered[s - 1 - whole]
        return value + 2. * tail_value / tail_mass
    variance = _variance_one(w, covariance, cross, fixed_variance)
    value += 2. * variance
    if method == 1:
        value += .5 * np.sqrt(variance)
    return value


@njit(cache=True)
def _linear_minimum_one(linear, upper, budget, current):
    """Reference stable segment allocation, expressed as insertion sorting."""
    n = len(linear)
    capacity = np.empty(2 * n)
    slopes = np.empty(2 * n)
    order = np.arange(2 * n)
    minimum = 0.
    for i in range(n):
        middle = min(upper[i], max(0., current[i]))
        capacity[i], capacity[n + i] = middle, upper[i] - middle
        slopes[i], slopes[n + i] = linear[i] - .001, linear[i] + .001
        minimum += .001 * abs(current[i])
    for j in range(1, 2 * n):
        index = order[j]
        k = j - 1
        while k >= 0 and slopes[order[k]] > slopes[index]:
            order[k + 1] = order[k]
            k -= 1
        order[k + 1] = index
    prior = 0.
    for j in range(2 * n):
        index = order[j]
        available = capacity[index] if slopes[index] < 0. else 0.
        allocated = min(available, max(0., budget - prior))
        minimum += slopes[index] * allocated
        prior += available
    return minimum


@njit(cache=True)
def _kernel(mu, covariance, upper, budget, current, cross, fixed_variance,
            scenarios, fixed_scenarios, operator, offset, step, dual_step,
            method, cap):
    b, n = mu.shape
    weights = np.empty((b, n))
    # Columns: objective, variance, gap, mapping, violation, turnover penalty.
    metrics = np.empty((b, 6))
    for row in range(b):
        w = _prox_one(current[row], upper[row], budget[row], np.zeros(n), 0.)
        best = w.copy()
        best_value = _objective_one(w, mu[row], current[row], covariance[row], cross[row],
                                    fixed_variance[row], scenarios[row], fixed_scenarios[row], method)
        zero = np.zeros(n)
        zero_value = _objective_one(zero, mu[row], current[row], covariance[row], cross[row],
                                    fixed_variance[row], scenarios[row], fixed_scenarios[row], method)
        if zero_value < best_value:
            best, best_value = zero, zero_value
        k = operator.shape[1]
        dual = np.zeros(k)
        if method == 2:
            dual[:] = 1. / k
        extrapolated = w.copy()
        gradient = np.empty(n)
        values = np.empty(n)
        for iteration in range(80):
            if method != 0:
                dual_values = np.empty(k)
                for j in range(k):
                    factor = offset[row, j]
                    for i in range(n):
                        factor += operator[row, j, i] * extrapolated[i]
                    dual_values[j] = dual[j] + dual_step[row] * factor
                if method == 1:
                    length = np.sqrt(np.sum(dual_values * dual_values))
                    dual = dual_values / max(1., length / .5)
                else:
                    dual = _dual_one(dual_values, cap)
            for i in range(n):
                value = -mu[row, i]
                if method != 2:
                    risk_gradient = cross[row, i]
                    for j in range(n):
                        risk_gradient += covariance[row, i, j] * w[j]
                    value += 4. * risk_gradient
                if method != 0:
                    for j in range(k):
                        value += operator[row, j, i] * dual[j]
                gradient[i] = value
                values[i] = w[i] - step[row] * value
            new = _prox_one(values, upper[row], budget[row], current[row], step[row] * .001)
            if method != 0:
                extrapolated = 2. * new - w
            w = new
            value = _objective_one(w, mu[row], current[row], covariance[row], cross[row],
                                   fixed_variance[row], scenarios[row], fixed_scenarios[row], method)
            if value < best_value:
                best, best_value = w.copy(), value
        w = best
        variance = _variance_one(w, covariance[row], cross[row], fixed_variance[row])
        if method == 2:
            for i in range(n):
                value = -mu[row, i]
                for j in range(k):
                    value += operator[row, j, i] * dual[j]
                gradient[i] = value
            lower = _linear_minimum_one(gradient, upper[row], budget[row], current[row])
            for j in range(k):
                lower += dual[j] * offset[row, j]
            gap = max(0., best_value - lower)
        else:
            for i in range(n):
                risk_gradient = cross[row, i]
                for j in range(n):
                    risk_gradient += covariance[row, i, j] * w[j]
                gradient[i] = 4. * risk_gradient - mu[row, i]
            if method == 1:
                factor_values = np.empty(k)
                for j in range(k):
                    factor_values[j] = offset[row, j]
                    for i in range(n):
                        factor_values[j] += operator[row, j, i] * w[i]
                length = np.sqrt(np.sum(factor_values * factor_values))
                subgradient = .5 * factor_values / max(length, 1e-12)
                if length < 1e-10:
                    subgradient = dual
                for i in range(n):
                    for j in range(k):
                        gradient[i] += operator[row, j, i] * subgradient[j]
            minimum = _linear_minimum_one(gradient, upper[row], budget[row], current[row])
            gap_value = 0.
            for i in range(n):
                gap_value += gradient[i] * w[i] + .001 * abs(w[i] - current[row, i])
            gap = max(0., gap_value - minimum)
        for i in range(n):
            values[i] = w[i] - gradient[i]
        mapped = _prox_one(values, upper[row], budget[row], current[row], .001)
        residual, violation, total, turnover = 0., 0., 0., 0.
        for i in range(n):
            residual = max(residual, abs(w[i] - mapped[i]))
            violation = max(violation, -w[i], w[i] - upper[row, i])
            total += w[i]
            turnover += .001 * abs(w[i] - current[row, i])
        violation = max(violation, total - budget[row])
        weights[row] = w
        metrics[row, 0], metrics[row, 1], metrics[row, 2] = best_value, variance, gap
        metrics[row, 3], metrics[row, 4], metrics[row, 5] = residual, violation, turnover
    return weights, metrics


def solve_batch(mu, covariances=None, *, method="mv", upper=None, budget=.95,
                current=None, scenarios=None, locked_cross=None, locked_variance=None,
                locked_scenario_returns=None):
    """The reference public contract, including metadata and failure semantics."""
    if method == "robust_mv":
        method = "robust"
    if method not in {*reference.OPTIMIZERS, "equal_top20"}:
        raise ValueError("UNKNOWN_OPTIMIZER")
    mu = np.asarray(mu, float)
    one = mu.ndim == 1
    if one:
        mu = mu[None, :]
    if mu.ndim != 2 or not np.isfinite(mu).all():
        raise ValueError("INVALID_OPTIMIZER_MEANS")
    b, n = mu.shape
    upper = reference._matrix(upper, (b, n), .1)
    budget = reference._matrix(budget, (b,), .95)
    current = reference._matrix(current, (b, n), 0.)
    cross = reference._matrix(locked_cross, (b, n), 0.)
    fixed_var = reference._matrix(locked_variance, (b,), 0.)
    if ((upper < 0).any() or (upper > .1000001).any() or (budget < 0).any()
            or (budget > .9500001).any() or (current < 0).any()):
        raise ValueError("INVALID_PORTFOLIO_CONSTRAINTS")
    if n == 0 or method == "equal_top20":
        return ORIGINAL_SOLVE_BATCH(mu, covariances, method=method, upper=upper,
                                    budget=budget, current=current, scenarios=scenarios,
                                    locked_cross=cross, locked_variance=fixed_var,
                                    locked_scenario_returns=locked_scenario_returns)
    covariance = reference._matrix(covariances, (b, n, n), 0.)
    covariance = (covariance + covariance.transpose(0, 2, 1)) / 2
    eigenvalues = np.linalg.eigvalsh(covariance)
    if eigenvalues.min() < -1e-9 or (fixed_var < -1e-10).any():
        raise ValueError("NON_PSD_PORTFOLIO_RISK")
    spectral = np.maximum(eigenvalues[:, -1], 1e-10)
    scenario_values = np.empty((b, 0, n))
    fixed_scenarios = np.empty((b, 0))
    operator, offset = np.zeros((b, 0, n)), np.zeros((b, 0))
    dual_step, cap = np.zeros(b), 0.
    if method == "mv":
        step = .9 / (4 * spectral)
        code = 0
    elif method == "robust":
        augmented = np.zeros((b, n + 1, n + 1))
        augmented[:, :n, :n] = covariance
        augmented[:, :n, n], augmented[:, n, :n] = cross, cross
        augmented[:, n, n] = fixed_var
        eig, vec = np.linalg.eigh(augmented)
        if eig.min() < -1e-9:
            raise ValueError("FIXED_HOLDING_CROSS_RISK_NOT_PSD")
        root = (vec * np.sqrt(np.maximum(eig, 0.))[:, None, :]) @ vec.transpose(0, 2, 1)
        operator, offset = root[:, :, :n], root[:, :, n]
        norm = np.sqrt(np.maximum(eig[:, -1], 1e-10))
        step, dual_step = .9 / (4 * spectral + norm), .9 / norm
        code = 1
    else:
        scenario_values = np.asarray(scenarios, float)
        if scenario_values.ndim == 2 and one:
            scenario_values = scenario_values[None]
        if (scenario_values.ndim != 3 or scenario_values.shape[0] != b
                or scenario_values.shape[2] != n or not np.isfinite(scenario_values).all()):
            raise ValueError("INVALID_JOINT_SCENARIOS")
        s = scenario_values.shape[1]
        if s < 2:
            raise ValueError("CVAR_NEEDS_JOINT_SCENARIO_PANEL")
        fixed_scenarios = reference._matrix(locked_scenario_returns, (b, s), 0.)
        operator, offset = -reference.CVAR_PENALTY * scenario_values, -reference.CVAR_PENALTY * fixed_scenarios
        gram = np.einsum("bsi,bsj->bij", operator, operator)
        norm = np.sqrt(np.maximum(np.linalg.eigvalsh(gram)[:, -1], 1e-10))
        step, dual_step = .9 / norm, .9 / norm
        cap = 1 / ((1 - reference.CVAR_ALPHA) * s)
        code = 2
    inputs = [mu, covariance, upper, budget, current, cross, fixed_var,
              scenario_values, fixed_scenarios, operator, offset, step, dual_step]
    # Own writable C-order inputs keep readonly forecast-cache arrays untouched
    # and avoid signature proliferation between single and target-blend calls.
    weights, metrics = _kernel(*[np.array(x, dtype=float, order="C", copy=True) for x in inputs], code, cap)
    metadata = []
    for i in range(b):
        objective, var, gap, residual, violation, turnover = metrics[i]
        converged = gap <= reference.GAP_TOLERANCE and residual <= reference.MAPPING_TOLERANCE
        metadata.append({"method": method, "status": "approx_converged" if converged else "approx_unconverged",
                         "iterations": reference.ITERATIONS, "feasible": bool(violation <= 1e-8),
                         "constraint_violation": float(violation), "gradient_mapping_inf": float(residual),
                         "optimality_gap_bound": float(gap), "global_optimum_claimed": False,
                         "objective_utility": float(-objective), "target_exposure": float(weights[i].sum()),
                         "predicted_total_daily_variance": float(var), "turnover_penalty_amount": float(turnover),
                         "fixed_holding_variance": float(fixed_var[i]), "fixed_iterations_no_extension": True,
                         "solver": "proximal_projected_gradient" if method == "mv" else "projected_primal_dual"})
    return weights, metadata


def enable():
    reference.solve_batch = solve_batch


def disable():
    reference.solve_batch = ORIGINAL_SOLVE_BATCH
