"""Fixed-budget batched portfolio solvers on forecast-ranked TOP20 support.

All learned objects arrive through frozen inputs. The optimizer receives the
strategy's own current weights; accounting costs are charged by the common
replay engine in addition to the prespecified turnover objective penalty.
The solvers always perform exactly 80 iterations and report feasibility and
approximate convergence separately. No failure triggers extra iterations.
"""
from __future__ import annotations

from collections.abc import Mapping
import numpy as np
import pandas as pd

from common import OPTIMIZERS


ITERATIONS = 80
TURNOVER_PENALTY = .001
RISK_AVERSION = 4.
ROBUST_RADIUS = .5
CVAR_ALPHA = .9
CVAR_PENALTY = 2.
PROJECTION_STEPS = 36
GAP_TOLERANCE = 1e-6
MAPPING_TOLERANCE = 1e-5
OPTIMIZER_SPEC = {
    "members": list(OPTIMIZERS) + ["equal_top20"], "iterations": ITERATIONS,
    "support": "full legal decision pool sorted by mu descending then ticker ascending; at most min(20, available slots)",
    "constraints": "0<=w_i<=upper_i<=.10; sum active weights<=available_weight<=.95; frozen units reserve capital and slots",
    "mv_utility": "mu @ w - 2 * total_daily_variance - .001 * sum(abs(w-current))",
    "robust_utility": "mv_utility - .5 * sqrt(total_daily_variance); norm penalty is a mean-error robustness proxy, not a fitted confidence interval",
    "cvar_utility": "mu @ w - 2 * empirical_CVaR_0.9(-joint_scenario_portfolio_return) - .001*sum(abs(w-current))",
    "fixed_holdings": "cross covariance and fixed-holding variance enter MV and robust; fixed-holding scenario returns enter CVaR",
    "turnover_penalty": TURNOVER_PENALTY, "risk_aversion": RISK_AVERSION,
    "robust_radius": ROBUST_RADIUS, "cvar_alpha": CVAR_ALPHA, "cvar_penalty": CVAR_PENALTY,
    "mv_solver": "80 proximal projected-gradient iterations with spectral Lipschitz step",
    "robust_solver": "80 projected primal-dual iterations on covariance square-root norm plus smooth quadratic",
    "cvar_solver": "80 projected primal-dual iterations using capped-simplex scenario dual weights; no scenario independence assumption",
    "numerical_steps": "deterministic spectral steps, safety factor .9, no parameter or seed search",
    "projection_bisection_steps": PROJECTION_STEPS,
    "convergence": {"utility_gap_tolerance": GAP_TOLERANCE, "gradient_mapping_inf_tolerance": MAPPING_TOLERANCE,
                    "status_when_exceeded": "approx_unconverged", "global_optimum_claim": False},
    "iterate_selection": "lowest actual convex objective among initialization, zero, and the 80 iterates; no extra optimization",
    "equal_top20": "equal capped water fill to available .95 budget; risk canonicalized none; no optimizer training",
    "separate_actual_cost": "replay independently charges 10bp on realized buys and sells; objective turnover penalty is not an accounting fee",
}


def _matrix(value, shape, default):
    if value is None:
        return np.full(shape, default, float)
    result = np.broadcast_to(np.asarray(value, float), shape).copy()
    if not np.isfinite(result).all():
        raise ValueError("NONFINITE_OPTIMIZER_INPUT")
    return result


def project_box_budget(values, upper, budget, *, current=None, penalty=0.):
    """Exact box/budget proximal map up to fixed bisection precision.

``penalty`` is the proximal L1 coefficient, potentially different per batch.
The budget constraint is an inequality: weak opportunities can retain cash.
"""
    values = np.asarray(values, float)
    one = values.ndim == 1
    if one:
        values = values[None, :]
    shape = values.shape
    upper = _matrix(upper, shape, .1)
    budget = _matrix(np.asarray(budget).reshape(-1, 1) if np.ndim(budget) else budget, (shape[0], 1), .95)
    current = _matrix(current, shape, 0.)
    penalty = _matrix(np.asarray(penalty).reshape(-1, 1) if np.ndim(penalty) else penalty, (shape[0], 1), 0.)
    if (upper < 0).any() or (budget < 0).any() or (penalty < 0).any():
        raise ValueError("NEGATIVE_PROJECTION_CONSTRAINT")
    def candidate(threshold):
        delta = values - threshold - current
        shrunk = current + np.sign(delta) * np.maximum(np.abs(delta) - penalty, 0.)
        return np.clip(shrunk, 0., upper)
    result = candidate(0.)
    constrained = result.sum(axis=1, keepdims=True) > budget + 1e-12
    if constrained.any():
        lo = np.zeros((shape[0], 1))
        hi = np.maximum(values.max(axis=1, keepdims=True) + np.max(np.abs(current), axis=1, keepdims=True) + penalty + 1., 1.)
        for _ in range(PROJECTION_STEPS):
            mid = (lo + hi) / 2
            above = candidate(mid).sum(axis=1, keepdims=True) > budget
            lo = np.where(above, mid, lo)
            hi = np.where(above, hi, mid)
        result = np.where(constrained, candidate(hi), result)
    return result[0] if one else result


def _project_capped_probability(values, cap):
    """Project scenario dual weights onto sum(q)=1, 0<=q<=cap."""
    values = np.asarray(values, float)
    lo = values.min(axis=1, keepdims=True) - cap
    hi = values.max(axis=1, keepdims=True)
    for _ in range(PROJECTION_STEPS):
        mid = (lo + hi) / 2
        above = np.clip(values - mid, 0., cap).sum(axis=1, keepdims=True) > 1.
        lo = np.where(above, mid, lo)
        hi = np.where(above, hi, mid)
    q = np.clip(values - (lo + hi) / 2, 0., cap)
    # The bisection error is tiny; normalization maintains the equality.
    q /= q.sum(axis=1, keepdims=True)
    return q


def _linear_cost_minimum(linear, upper, budget, current, cost=TURNOVER_PENALTY):
    """Exact min of a linear term plus L1 turnover over a box/budget."""
    middle = np.clip(current, 0., upper)
    capacity = np.concatenate([middle, upper - middle], axis=1)
    slopes = np.concatenate([linear - cost, linear + cost], axis=1)
    order = np.argsort(slopes, axis=1, kind="stable")
    ordered_slopes = np.take_along_axis(slopes, order, axis=1)
    ordered_capacity = np.take_along_axis(capacity, order, axis=1)
    ordered_capacity = np.where(ordered_slopes < 0., ordered_capacity, 0.)
    prior = np.cumsum(ordered_capacity, axis=1) - ordered_capacity
    allocated = np.minimum(ordered_capacity, np.maximum(0., budget[:, None] - prior))
    minimum = cost * np.abs(current).sum(axis=1) + (ordered_slopes * allocated).sum(axis=1)
    return minimum


def empirical_cvar(losses, alpha=CVAR_ALPHA):
    """Equal-weight empirical tail mean with the fractional boundary weight."""
    losses = np.asarray(losses, float)
    ordered = np.sort(losses, axis=-1)[..., ::-1]
    tail_mass = (1 - alpha) * losses.shape[-1]
    whole = int(np.floor(tail_mass + 1e-12))
    fraction = tail_mass - whole
    result = ordered[..., :whole].sum(axis=-1)
    if fraction > 1e-12:
        result += fraction * ordered[..., whole]
    return result / tail_mass


def solve_batch(mu, covariances=None, *, method="mv", upper=None, budget=.95,
                current=None, scenarios=None, locked_cross=None, locked_variance=None,
                locked_scenario_returns=None):
    """Return weights[B,N] and per-row solver metadata without any fitting.

    Padded supports use upper=0. ``locked_cross`` is Sigma_active,fixed @ w_fixed;
    ``locked_variance`` is w_fixed.T @ Sigma_fixed,fixed @ w_fixed. Fixed scenario
    returns have shape [B,S] and include their actual frozen holding weights.
    """
    if method == "robust_mv":
        method = "robust"
    if method not in {*OPTIMIZERS, "equal_top20"}:
        raise ValueError("UNKNOWN_OPTIMIZER")
    mu = np.asarray(mu, float)
    one = mu.ndim == 1
    if one:
        mu = mu[None, :]
    if mu.ndim != 2 or not np.isfinite(mu).all():
        raise ValueError("INVALID_OPTIMIZER_MEANS")
    b, n = mu.shape
    upper = _matrix(upper, (b, n), .1)
    budget = _matrix(budget, (b,), .95)
    current = _matrix(current, (b, n), 0.)
    cross = _matrix(locked_cross, (b, n), 0.)
    fixed_var = _matrix(locked_variance, (b,), 0.)
    if (upper < 0).any() or (upper > .1000001).any() or (budget < 0).any() or (budget > .9500001).any() or (current < 0).any():
        raise ValueError("INVALID_PORTFOLIO_CONSTRAINTS")
    if n == 0:
        return np.empty((b, 0)), [{"method": method, "status": "approx_converged", "iterations": 0,
                                  "reason": "empty_support", "feasible": True} for _ in range(b)]
    if method == "equal_top20":
        weights = project_box_budget(np.full((b, n), 1.), upper, budget)
        metadata = [{"method": method, "status": "fixed_rule", "iterations": 0, "feasible": True,
                     "target_exposure": float(weights[i].sum()),
                     "unused_budget": float(budget[i] - weights[i].sum()), "risk_member": "none"} for i in range(b)]
        return weights, metadata
    covariance = _matrix(covariances, (b, n, n), 0.)
    covariance = (covariance + covariance.transpose(0, 2, 1)) / 2
    eigenvalues = np.linalg.eigvalsh(covariance)
    if eigenvalues.min() < -1e-9 or (fixed_var < -1e-10).any():
        raise ValueError("NON_PSD_PORTFOLIO_RISK")
    spectral = np.maximum(eigenvalues[:, -1], 1e-10)
    scenario_values = None
    fixed_scenarios = None
    if method == "cvar":
        scenario_values = np.asarray(scenarios, float)
        if scenario_values.ndim == 2 and one:
            scenario_values = scenario_values[None]
        if scenario_values.ndim != 3 or scenario_values.shape[0] != b or scenario_values.shape[2] != n or not np.isfinite(scenario_values).all():
            raise ValueError("INVALID_JOINT_SCENARIOS")
        s = scenario_values.shape[1]
        if s < 2:
            raise ValueError("CVAR_NEEDS_JOINT_SCENARIO_PANEL")
        fixed_scenarios = _matrix(locked_scenario_returns, (b, s), 0.)
    def variance(w):
        return np.maximum(0., np.einsum("bi,bij,bj->b", w, covariance, w) + 2 * (w * cross).sum(axis=1) + fixed_var)
    def objective(w):
        value = -(mu * w).sum(axis=1) + TURNOVER_PENALTY * np.abs(w - current).sum(axis=1)
        if method == "cvar":
            returns = np.einsum("bsi,bi->bs", scenario_values, w) + fixed_scenarios
            return value + CVAR_PENALTY * empirical_cvar(-returns)
        var = variance(w)
        return value + 2 * var + (ROBUST_RADIUS * np.sqrt(var) if method == "robust" else 0.)
    # Starting from actual feasible holdings avoids an implicit shared account.
    w = project_box_budget(current, upper, budget)
    zero = np.zeros_like(w)
    best = w.copy()
    best_value = objective(w)
    zero_value = objective(zero)
    replace = zero_value < best_value
    best[replace], best_value[replace] = zero[replace], zero_value[replace]
    dual = operator = offset = None
    if method == "mv":
        step = .9 / (4 * spectral)
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
        step = .9 / (4 * spectral + norm)
        dual_step = .9 / norm
        dual = np.zeros((b, n + 1))
        extrapolated = w.copy()
    else:
        operator = -CVAR_PENALTY * scenario_values
        offset = -CVAR_PENALTY * fixed_scenarios
        gram = np.einsum("bsi,bsj->bij", operator, operator)
        norm = np.sqrt(np.maximum(np.linalg.eigvalsh(gram)[:, -1], 1e-10))
        step = .9 / norm
        dual_step = .9 / norm
        dual = np.full((b, scenario_values.shape[1]), 1 / scenario_values.shape[1])
        cap = 1 / ((1 - CVAR_ALPHA) * scenario_values.shape[1])
        extrapolated = w.copy()
    for _ in range(ITERATIONS):
        if method == "mv":
            gradient = 4 * (np.einsum("bij,bj->bi", covariance, w) + cross) - mu
        elif method == "robust":
            dual += dual_step[:, None] * (np.einsum("bki,bi->bk", operator, extrapolated) + offset)
            dual /= np.maximum(1., np.linalg.norm(dual, axis=1) / ROBUST_RADIUS)[:, None]
            gradient = (4 * (np.einsum("bij,bj->bi", covariance, w) + cross) - mu
                        + np.einsum("bki,bk->bi", operator, dual))
        else:
            dual = _project_capped_probability(dual + dual_step[:, None] * (
                np.einsum("bsi,bi->bs", operator, extrapolated) + offset), cap)
            gradient = -mu + np.einsum("bsi,bs->bi", operator, dual)
        new = project_box_budget(w - step[:, None] * gradient, upper, budget,
                                 current=current, penalty=step * TURNOVER_PENALTY)
        if method != "mv":
            extrapolated = 2 * new - w
        w = new
        value = objective(w)
        replace = value < best_value
        best[replace], best_value[replace] = w[replace], value[replace]
    w = best
    var = variance(w)
    if method == "cvar":
        gradient = -mu + np.einsum("bsi,bs->bi", operator, dual)
        lower = _linear_cost_minimum(gradient, upper, budget, current) + (dual * offset).sum(axis=1)
        gap = np.maximum(0., objective(w) - lower)
    else:
        gradient = 4 * (np.einsum("bij,bj->bi", covariance, w) + cross) - mu
        if method == "robust":
            factor_value = np.einsum("bki,bi->bk", operator, w) + offset
            length = np.linalg.norm(factor_value, axis=1)
            subgradient = ROBUST_RADIUS * factor_value / np.maximum(length[:, None], 1e-12)
            # At zero norm any dual vector in the radius ball is a valid subgradient.
            subgradient[length < 1e-10] = dual[length < 1e-10]
            gradient += np.einsum("bki,bk->bi", operator, subgradient)
        minimum = _linear_cost_minimum(gradient, upper, budget, current)
        gap = np.maximum(0., (gradient * w).sum(axis=1) + TURNOVER_PENALTY * np.abs(w - current).sum(axis=1) - minimum)
    mapping = w - project_box_budget(w - gradient, upper, budget,
                                    current=current, penalty=TURNOVER_PENALTY)
    residual = np.max(np.abs(mapping), axis=1)
    violation = np.maximum.reduce([np.maximum(0., -w.min(axis=1)),
                                   np.maximum(0., (w - upper).max(axis=1)),
                                   np.maximum(0., w.sum(axis=1) - budget)])
    metadata = []
    for i in range(b):
        converged = gap[i] <= GAP_TOLERANCE and residual[i] <= MAPPING_TOLERANCE
        metadata.append({"method": method, "status": "approx_converged" if converged else "approx_unconverged",
                         "iterations": ITERATIONS, "feasible": bool(violation[i] <= 1e-8),
                         "constraint_violation": float(violation[i]), "gradient_mapping_inf": float(residual[i]),
                         "optimality_gap_bound": float(gap[i]), "global_optimum_claimed": False,
                         "objective_utility": float(-best_value[i]), "target_exposure": float(w[i].sum()),
                         "predicted_total_daily_variance": float(var[i]),
                         "turnover_penalty_amount": float(TURNOVER_PENALTY * np.abs(w[i] - current[i]).sum()),
                         "fixed_holding_variance": float(fixed_var[i]),
                         "fixed_iterations_no_extension": True,
                         "solver": "proximal_projected_gradient" if method == "mv" else "projected_primal_dual"})
    return w, metadata


def select_top20(tickers, mu, *, slots=20, legal=None):
    tickers = np.asarray(tickers, str)
    mu = np.asarray(mu, float)
    if tickers.shape != mu.shape or not np.isfinite(mu).all() or len(set(tickers)) != len(tickers):
        raise ValueError("INVALID_FULL_POOL_FORECAST")
    indices = np.arange(len(tickers))
    if legal is not None:
        indices = indices[np.asarray(legal, bool)]
    return indices[np.lexsort((tickers[indices], -mu[indices]))][:max(0, min(20, int(slots)))]


class OptimizeTop20:
    def __init__(self, method="mv", risk_name="lw", risk_bank=None):
        self.method, self.risk_name, self.risk_bank = method, risk_name, risk_bank

    def __call__(self, day, context=None, mu=None, marginals=None):
        names = day.ticker.astype(str).to_numpy()
        mu = np.asarray(day.mu.to_numpy(float) if mu is None else mu, float)
        current_map = {} if context is None else context.current_weights
        current = np.array([current_map.get(t, 0.) for t in names])
        eligible = day.new_buy_eligible.to_numpy(dtype=bool, copy=True) if "new_buy_eligible" in day else np.ones(len(day), bool)
        restricted = set() if context is None else set(context.buy_restricted_tickers)
        eligible &= ~np.isin(names, list(restricted))
        slots = 20 if context is None else context.available_slots
        budget = .95 if context is None else context.available_weight
        ix = select_top20(names, mu, slots=slots, legal=eligible | (current > 0))
        selected = names[ix].tolist()
        old = current[ix]
        upper = np.where(eligible[ix], .1, np.minimum(old, .1))
        if not len(ix):
            return {}, {"method": self.method, "status": "empty_support", "support_tickers": [], "iterations": 0}
        kwargs = {"upper": upper, "budget": budget, "current": old}
        risk_metadata = {}
        if self.method != "equal_top20":
            if self.risk_bank is None:
                raise ValueError("RISK_OPTIMIZER_REQUIRES_FROZEN_RISK_BANK")
            locked = [] if context is None else list(context.reserved_tickers)
            locked_weights = np.array([context.reserved_weights[t] for t in locked]) if locked else np.empty(0)
            all_names = selected + locked
            signalvol = None
            if self.risk_name in {"lw_hgb_vol", "lw_mlp_vol"}:
                active_vol = self.risk_bank.predict_signal_vol(day.iloc[ix], self.risk_name)
                frozen_vol = np.array([self.risk_bank.arrays["daily_vol"][self.risk_bank.lookup[t]]
                                       if t in self.risk_bank.lookup else .08 for t in locked])
                signalvol = np.r_[active_vol, frozen_vol]
            covariance, risk_metadata = self.risk_bank.covariance(all_names, risk_name=self.risk_name,
                                                                 signalvol=signalvol, return_metadata=True)
            k = len(selected)
            kwargs["covariances"] = covariance[:k, :k]
            kwargs["locked_cross"] = covariance[:k, k:] @ locked_weights
            kwargs["locked_variance"] = float(locked_weights @ covariance[k:, k:] @ locked_weights)
            if self.method == "cvar":
                marginal_subset = {}
                if marginals is not None:
                    for key in ["sigma", "q10", "q50", "q90"]:
                        if key in marginals:
                            value = np.asarray(marginals[key], float)[ix]
                            if locked:
                                sigma_fixed = np.sqrt(np.diag(covariance)[k:])
                                fixed = sigma_fixed if key == "sigma" else {"q10": -1.2815515655 * sigma_fixed,
                                        "q50": np.zeros(len(locked)), "q90": 1.2815515655 * sigma_fixed}[key]
                                value = np.r_[value, fixed]
                            marginal_subset[key] = value
                scenarios, scenario_metadata = self.risk_bank.scenarios(all_names, np.r_[mu[ix], np.zeros(len(locked))],
                    marginals=marginal_subset, risk_name=self.risk_name, signalvol=signalvol, return_metadata=True)
                kwargs["scenarios"] = scenarios[:, :k]
                kwargs["locked_scenario_returns"] = scenarios[:, k:] @ locked_weights
                risk_metadata["scenarios"] = scenario_metadata
        weights, metadata = solve_batch(mu[ix], method=self.method, **kwargs)
        result = {t: float(value) for t, value in zip(selected, weights[0]) if value > 1e-10}
        report = {**metadata[0], "risk_member": "none" if self.method == "equal_top20" else self.risk_name,
                  "support_tickers": selected, "full_pool_rows": len(day), "risk_coverage": risk_metadata,
                  "selection_scope": "forecast_top20_only_then_risk_weighting",
                  "global_mixed_integer_optimum_claimed": False,
                  "explicit_old_position_zero_required_by_caller": True}
        return result, report
