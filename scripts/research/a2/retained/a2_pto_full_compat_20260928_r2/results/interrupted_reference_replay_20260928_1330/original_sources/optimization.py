"""Frozen batch optimizers for the separately defined Top20 selection stage.

All methods keep cash endogenous. Inputs contain the already selected names;
selection is external and cannot be changed in response to optimizer results.
``scenarios`` are JOINT standardized historical residual scenarios. CVaR uses
mu + uncertainty * scenarios, preserving their cross-sectional dependence.
The smoothed CVaR objective is explicitly a fixed 5 bp softplus approximation.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

SPEC = dict(version="PTO_OPTIMIZATION_V1", risk_penalty=4.0,
            turnover_cost=0.001, max_weight=0.10, max_invested=0.95,
            robust_uncertainty_penalty=0.5, cvar_alpha=0.90,
            cvar_softplus_epsilon=0.0005, tolerance=2e-6,
            first_iterations=128, maximum_iterations=512,
            numeric_continuation="same objective and step, only unconverged rows",
            projection="exact shifted soft threshold and capped-budget bisection",
            projection_bisections=36, eta_bisections=24,
            step="1 / fixed analytic Lipschitz upper bound, no line search",
            residual="infinity norm of proximal gradient mapping; approximate stationarity, not a global KKT certificate",
            cvar_cash_baseline="softplus constant retained in reported objective; no objective substitution",
            exact_fixed_point_dedup="skip deterministic identical future iterates only on bitwise-equal following and current; count first 128 steps logically",
            selection="caller freezes descending mu Top20 with ticker tie break")


@dataclass
class OptimizationResult:
    weights: np.ndarray
    status: np.ndarray
    iterations: np.ndarray
    residual: np.ndarray
    objective: np.ndarray
    cvar_eta: np.ndarray
    residual_kind: str = SPEC["residual"]
    exact_fixed_point: np.ndarray | None = None
    gradient_evaluations: np.ndarray | None = None


def _soft(value, threshold):
    return np.sign(value) * np.maximum(np.abs(value) - threshold, 0.0)


def project_budget(values, budget, upper=0.10):
    """Euclidean capped-simplex projection; never scale small targets upward."""
    x = np.asarray(values, dtype=np.float64)
    b = np.maximum(np.asarray(budget, dtype=np.float64), 0.0)
    u = np.broadcast_to(np.asarray(upper, dtype=np.float64), x.shape)
    direct = np.clip(x, 0.0, u)
    constrained = direct.sum(axis=1) > b
    if not np.any(constrained):
        return direct
    sub, cap, limit = x[constrained], u[constrained], b[constrained]
    low = np.zeros(len(sub)); high = np.maximum(sub.max(axis=1), 0.0)
    for _ in range(SPEC["projection_bisections"]):
        mid = (low + high) * 0.5
        too_much = np.clip(sub - mid[:, None], 0.0, cap).sum(axis=1) > limit
        low = np.where(too_much, mid, low)
        high = np.where(too_much, high, mid)
    direct[constrained] = np.clip(sub - high[:, None], 0.0, cap)
    return direct


def _prox_budget(y, center, threshold, budget, upper):
    """Exact prox of turnover around current weights + capped budget set."""
    def shifted(lam):
        return np.clip(center + _soft(y - center - lam[:, None], threshold[:, None]), 0.0, upper)
    low = np.zeros(len(y)); direct = shifted(low)
    need = direct.sum(axis=1) > budget
    if not need.any():
        return direct
    high = np.maximum((y - center).max(axis=1) + center.max(axis=1) + threshold, 0.0)
    for _ in range(SPEC["projection_bisections"]):
        mid = (low + high) * 0.5
        too_much = shifted(mid).sum(axis=1) > budget
        low = np.where(need & too_much, mid, low)
        high = np.where(need & ~too_much, mid, high)
    constrained = shifted(high)
    return np.where(need[:, None], constrained, direct)


def _sigmoid(x):
    z = np.clip(x, -45.0, 45.0)
    return 1.0 / (1.0 + np.exp(-z))


def _smooth_cvar(weights, returns, reserved_joint_loss=None):
    epsilon, tail = SPEC["cvar_softplus_epsilon"], 1.0 - SPEC["cvar_alpha"]
    loss = -np.einsum("shn,sn->sh", returns, weights, optimize=True)
    if reserved_joint_loss is not None:
        loss = loss + reserved_joint_loss
    low = loss.min(axis=1) - 25.0 * epsilon
    high = loss.max(axis=1) + 25.0 * epsilon
    for _ in range(SPEC["eta_bisections"]):
        eta = (low + high) * 0.5
        mass = _sigmoid((loss - eta[:, None]) / epsilon).mean(axis=1)
        low = np.where(mass > tail, eta, low)
        high = np.where(mass > tail, high, eta)
    eta = (low + high) * 0.5
    normalized_loss = (loss - eta[:, None]) / epsilon
    cvar = eta + epsilon * np.logaddexp(0.0, normalized_loss).mean(axis=1) / tail
    gradient = -np.einsum("shn,sh->sn", returns, _sigmoid(normalized_loss), optimize=True) / (returns.shape[1] * tail)
    return cvar, gradient, eta


def optimize(kind, mu, cov, current, budget, slots, uncertainty=None, scenarios=None,
             *, upper=None, risk_linear=None, reserved_joint_loss=None,
             deduplicate_exact_fixed_points=True):
    """Batch fixed-objective solve with approximate stationarity diagnostics.

    mu/current: [S,N]; covariance: [S,N,N]; budget/slots: [S]. The caller
    selects N <= 20 and masks padded names via upper=0. ``risk_linear`` is
    C[selected, reserved] @ reserved_weights, so locked holdings' correlated
    risk enters MV objectives without making them tradable. CVaR instead uses
    reserved_joint_loss[S,H], the realized loss of fixed reserved units in the
    SAME scenario rows as selected assets. Omitting it asserts no reserved risk.
    """
    if kind not in {"positive_equal", "mean_variance", "robust_mv", "cvar"}:
        raise ValueError(f"unknown optimizer: {kind}")
    mu = np.asarray(mu, dtype=np.float64)
    current = np.asarray(current, dtype=np.float64)
    cov = np.asarray(cov, dtype=np.float64)
    if mu.ndim != 2 or current.shape != mu.shape or cov.shape != (len(mu), mu.shape[1], mu.shape[1]):
        raise ValueError("optimizer shape contract violated")
    if not np.isfinite(mu).all() or not np.isfinite(current).all() or not np.isfinite(cov).all():
        raise ValueError("unknown forecasts must be reserved/masked by caller")
    s, n = mu.shape
    budget = np.asarray(budget, dtype=np.float64).reshape(s)
    slots = np.asarray(slots, dtype=np.int64).reshape(s)
    if n < 1 or n > 20 or np.any(current < 0) or np.any(slots < 0) or not np.isfinite(budget).all() or np.any(budget < 0) or np.any(budget > SPEC["max_invested"] + 1e-9):
        raise ValueError("invalid Top20 budget/slots")
    cap = np.full_like(mu, SPEC["max_weight"]) if upper is None else np.minimum(np.broadcast_to(upper, mu.shape), SPEC["max_weight"]).copy()
    # External selection is ordered by mu. If reservations leave fewer slots,
    # mask the suffix instead of permitting an internal new cardinality search.
    cap[np.arange(n)[None, :] >= slots[:, None]] = 0.0
    if not np.isfinite(cap).all() or np.any(cap < 0):
        raise ValueError("negative upper bound")
    if kind == "positive_equal":
        active = (mu > SPEC["turnover_cost"]) & (cap > 0)
        count = active.sum(axis=1)
        equal = np.minimum(SPEC["max_weight"], np.divide(budget, count, out=np.zeros(s), where=count > 0))
        weights = np.minimum(active * equal[:, None], cap)
        obj = (mu * weights).sum(axis=1) - SPEC["turnover_cost"] * np.abs(weights-current).sum(axis=1)
        return OptimizationResult(weights, np.full(s,"RULE_COMPLETE",dtype="U24"), np.zeros(s,dtype=np.int32), np.zeros(s), obj, np.full(s,np.nan))
    scale = np.zeros_like(mu) if uncertainty is None else np.broadcast_to(np.asarray(uncertainty, dtype=np.float64), mu.shape)
    if np.any(scale < 0) or not np.isfinite(scale).all():
        raise ValueError("uncertainty must be finite nonnegative return scale")
    penalty, fee = SPEC["risk_penalty"], SPEC["turnover_cost"]
    effective_mu = mu - (SPEC["robust_uncertainty_penalty"] * scale if kind == "robust_mv" else 0.0)
    linear = np.zeros_like(mu) if risk_linear is None else np.broadcast_to(np.asarray(risk_linear,dtype=np.float64),mu.shape)
    if not np.isfinite(linear).all():
        raise ValueError("reserved covariance contribution must be finite")
    joint_returns = None
    locked_loss = None
    if kind == "cvar":
        if scenarios is None or uncertainty is None:
            raise ValueError("CVaR requires joint standardized scenarios and marginal scale")
        standardized = np.asarray(scenarios,dtype=np.float64)
        if standardized.ndim == 2:
            standardized = np.broadcast_to(standardized[None,:,:], (s,*standardized.shape))
        if standardized.ndim != 3 or standardized.shape[0] != s or standardized.shape[2] != n or standardized.shape[1] < 2 or not np.isfinite(standardized).all():
            raise ValueError("invalid joint scenario shape")
        joint_returns = mu[:,None,:] + scale[:,None,:] * standardized
        if reserved_joint_loss is not None:
            locked_loss = np.broadcast_to(np.asarray(reserved_joint_loss,dtype=np.float64),joint_returns.shape[:2])
            if not np.isfinite(locked_loss).all():
                raise ValueError("reserved joint scenario losses must be finite")
        elif np.any(linear != 0.0):
            raise ValueError("CVaR reserved risk requires reserved_joint_loss, not MV risk_linear")
        moment = np.einsum("shn,shm->snm",joint_returns,joint_returns,optimize=True) / joint_returns.shape[1]
        lipschitz = penalty * np.abs(moment).sum(axis=2).max(axis=1) / (4*SPEC["cvar_softplus_epsilon"]*(1-SPEC["cvar_alpha"]))
    else:
        if not np.allclose(cov,cov.swapaxes(1,2),atol=1e-10):
            raise ValueError("covariance must be symmetric")
        if np.any(np.linalg.eigvalsh(cov) < -1e-10):
            raise ValueError("covariance must be positive semidefinite")
        lipschitz = penalty * np.abs(cov).sum(axis=2).max(axis=1)
    step = 1.0 / np.maximum(lipschitz, 1e-5)
    weights = project_budget(current,budget,cap)
    iterations = np.zeros(s,dtype=np.int32)
    gradient_evaluations = np.zeros(s,dtype=np.int32)
    exact_fixed_point = np.zeros(s,dtype=bool)
    residual = np.full(s,np.inf)
    active = np.ones(s,dtype=bool)
    eta = np.full(s,np.nan)
    for iteration in range(1,SPEC["maximum_iterations"]+1):
        if not active.any():
            break
        idx = np.flatnonzero(active)
        gradient_evaluations[idx] += 1
        w = weights[idx]
        if kind == "cvar":
            _, grad_risk, local_eta = _smooth_cvar(w,joint_returns[idx],None if locked_loss is None else locked_loss[idx])
            gradient = penalty * grad_risk - effective_mu[idx]
            eta[idx] = local_eta
        else:
            gradient = penalty * (np.einsum("snm,sm->sn",cov[idx],w,optimize=True)+linear[idx]) - effective_mu[idx]
        following = _prox_budget(w-step[idx,None]*gradient,current[idx],fee*step[idx],budget[idx],cap[idx])
        residual[idx] = np.max(np.abs(following-w),axis=1) / step[idx]
        weights[idx] = following
        iterations[idx] = iteration
        if deduplicate_exact_fixed_points:
            exact=np.all(following==w,axis=1)
            # The map has no iteration-dependent step or eta warm start. All
            # arrays in its objective are fixed for this call. Identical x thus
            # repeats the identical deterministic map, so skipping those
            # repetitions does not use a tolerance or shorten the 128-step
            # logical block. ``gradient_evaluations`` reports actual work.
            frozen=idx[exact]
            exact_fixed_point[frozen]=True
            iterations[frozen]=max(iteration,SPEC["first_iterations"])
            active[frozen]=False
        # Every row receives the same prespecified first block; only numeric
        # residuals decide continuation, never returns or evaluation metrics.
        if iteration >= SPEC["first_iterations"]:
            active[idx[residual[idx] <= SPEC["tolerance"]]] = False
    if kind == "cvar":
        cvar, gradient_risk, eta = _smooth_cvar(weights,joint_returns,locked_loss)
        objective = (mu*weights).sum(axis=1)-penalty*cvar-fee*np.abs(weights-current).sum(axis=1)
        gradient = penalty*gradient_risk-effective_mu
    else:
        objective = (effective_mu*weights).sum(axis=1)-0.5*penalty*np.einsum("sn,snm,sm->s",weights,cov,weights,optimize=True)-penalty*(linear*weights).sum(axis=1)-fee*np.abs(weights-current).sum(axis=1)
        gradient = penalty*(np.einsum("snm,sm->sn",cov,weights,optimize=True)+linear)-effective_mu
    check = _prox_budget(weights-step[:,None]*gradient,current,fee*step,budget,cap)
    residual = np.max(np.abs(check-weights),axis=1)/step
    status = np.where(residual<=SPEC["tolerance"],"CONVERGED","ITERATION_LIMIT")
    return OptimizationResult(weights,status,iterations,residual,objective,eta,
                              exact_fixed_point=exact_fixed_point,gradient_evaluations=gradient_evaluations)
