"""JOINT R1 adapter over the retained common account and budget projection.

The retained PTO policy freezes score Top20 before optimization and its gross/
cost semantics differ. This adapter keeps every legal, forecast-available name
in each gradient update, reusing only its numerical budget projection and the
unchanged account TargetDecision. The cardinality solve is deterministic and
approximate; it is not a global optimum certificate. No prices are read here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.optimization import project_budget

TASK_ID = "JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1"
EPS = 1e-10
DEFAULT_ROLES = {
    "CONTROL_RAW_A2_POLICY": {"kind": "raw"},
    "JOINT_SIMPLE_EQUAL": {"kind": "simple"},
    "PTO_RIDGE_DIAG": {"risk": "DIAG"},
    "PTO_HGB_DIAG": {"risk": "DIAG"},
    "PTO_EQUAL_ENSEMBLE_LW": {"risk": "LW"},
    "PTO_EQUAL_ENSEMBLE_LW_VOL": {"risk": "LW", "gross": "vol"},
    "ABL_SELECTION": {"risk": "LW"},
    "ABL_ACTION": {"risk": "LW", "rho": 1.0},
    "ABL_WEIGHT": {"risk": "LW", "equal": True},
    "ABL_GROSS": {"risk": "LW", "reuse": "PTO_EQUAL_ENSEMBLE_LW"},
}


class InfeasiblePolicy(ValueError):
    """An affected account needs a preserved-units fallback, not invented cash."""


def _capped_mass(values, upper, mass):
    """Equality mass using the existing capped-budget primitive."""
    if mass <= EPS:
        return np.zeros_like(values)
    if upper.sum() < mass - EPS:
        raise InfeasiblePolicy("INSUFFICIENT_CAPPED_COMPOSITION_MASS")
    # A common shift forces the existing <=budget projection onto sum=mass.
    shift = max(0.0, -float(values.min())) + float(upper.max()) + 1.0
    result = project_budget((values + shift)[None, :], np.array([mass]), upper[None, :])[0]
    gap = mass - float(result.sum())
    if gap > 0:
        headroom = upper - result
        for index in np.argsort(-headroom, kind="stable"):
            add = min(gap, float(headroom[index]))
            result[index] += add
            gap -= add
            if gap <= np.finfo(float).eps:
                break
    if abs(result.sum() - mass) > 1e-8:
        raise InfeasiblePolicy("CAPPED_COMPOSITION_PROJECTION_FAILED")
    return result


def _support_projection(values, upper, mass, slots, ticker_rank):
    result = np.zeros_like(upper)
    if mass <= EPS:
        return result
    candidates = np.flatnonzero(upper > EPS)
    count = min(int(slots), len(candidates))
    if count <= 0 or np.sort(upper[candidates])[-count:].sum() < mass - EPS:
        raise InfeasiblePolicy("INSUFFICIENT_SLOT_OR_CAPACITY_MASS")
    ordered = candidates[np.lexsort((ticker_rank[candidates], -values[candidates]))]
    chosen = ordered[:count].copy()
    # Capacity is a constraint, not an opportunity prefilter. Repair a gradient
    # support whose many tiny out-of-pool caps cannot carry the required mass.
    while upper[chosen].sum() < mass - EPS:
        remaining = np.setdiff1d(candidates, chosen, assume_unique=False)
        enter = remaining[np.lexsort((ticker_rank[remaining], -values[remaining], -upper[remaining]))][0]
        leave_order = np.lexsort((ticker_rank[chosen], values[chosen], upper[chosen]))
        leave = int(leave_order[0])
        if upper[enter] <= upper[chosen[leave]] + EPS:
            raise InfeasiblePolicy("GRADIENT_SUPPORT_CAPACITY_INFEASIBLE")
        chosen[leave] = enter
    result[chosen] = _capped_mass(values[chosen], upper[chosen], mass)
    return result


def _covariance_action(covariance, weights):
    if covariance.ndim == 1:
        return covariance * weights
    support = np.flatnonzero(weights != 0)
    return covariance[:, support] @ weights[support] if len(support) else np.zeros(len(weights))


class JointResearchPolicy:
    """Batched callable for the existing fast_account.run_many protocol.

    mu/uncertainty are [day,path,ticker], ordered exactly like role_ids and the
    account tickers. Annual frozen covariance keys are (year,"DIAG"/"LW").
    roles may specify kind(raw/simple/joint), risk, gross(fixed/vol), rho, equal.
    on_diagnostics receives one DataFrame per signal. parameters defaults to the
    already frozen task EXECUTION_PARAMETERS.json; tests may pass that mapping.
    """

    def __init__(self, role_ids, mu, uncertainty, covariance_by_year_and_kind,
                 roles=None, on_diagnostics=None, parameters=None):
        self.role_ids = tuple(map(str, role_ids))
        if not self.role_ids or len(set(self.role_ids)) != len(self.role_ids):
            raise ValueError("unique nonempty role_ids required")
        self.mu = np.asarray(mu)
        self.uncertainty = np.asarray(uncertainty)
        if self.mu.dtype.kind not in "fiu" or self.uncertainty.dtype.kind not in "fiu":
            raise ValueError("forecast arrays must be numeric")
        if self.mu.ndim != 3 or self.mu.shape != self.uncertainty.shape or self.mu.shape[1] != len(self.role_ids):
            raise ValueError("forecasts must be matching [day,path,ticker] arrays")
        if parameters is None:
            path = resolve().results_root / TASK_ID / "EXECUTION_PARAMETERS.json"
            parameters = json.loads(path.read_text(encoding="utf-8-sig"))
        self.parameters = parameters
        spec = parameters["optimizer"]
        self.penalty = float(spec["risk_penalty"])
        self.uncertainty_penalty = float(spec["uncertainty_penalty"])
        self.max_q = float(spec["max_q"])
        self.max_positions = int(spec["max_positions"])
        self.iterations = int(spec["iterations"])
        self.tolerance = float(spec["tolerance"])
        self.rho = float(parameters["action"]["partial_rebalance"])
        self.vol_target = float(parameters["gross"]["volatility_target_annual"])
        if float(spec["turnover_cost"]) != 0 or parameters["gross"]["fixed"] != 1:
            raise ValueError("JOINT R1 requires its frozen zero-cost, fixed-one composition environment")
        if not (self.penalty > 0 and 0 < self.max_q <= 1 and self.max_positions > 0 and
                self.iterations > 0 and self.tolerance > 0 and 0 < self.rho <= 1 and self.vol_target > 0):
            raise ValueError("invalid frozen JOINT optimizer parameters")
        supplied = roles or {}
        self.roles = {}
        for role in self.role_ids:
            if role not in DEFAULT_ROLES and role not in supplied:
                raise ValueError(f"unregistered policy role: {role}")
            config = {"kind": "joint", "risk": "DIAG", "gross": "fixed", "rho": self.rho, "equal": False}
            config.update(DEFAULT_ROLES.get(role, {}))
            config.update(supplied.get(role, {}))
            if config["kind"] not in {"joint", "raw", "simple"} or config["gross"] not in {"fixed", "vol"}:
                raise ValueError("unsupported frozen policy role")
            if float(config["rho"]) not in {self.rho, float(parameters["action"]["full_action_ablation"])}:
                raise ValueError("unregistered action rho")
            self.roles[role] = config
        self.covariances = covariance_by_year_and_kind
        self.callback = on_diagnostics
        self._checked_covariances = {}

    def _covariance(self, year, kind, count):
        aliases = {"DIAG": "DIAG", "DIAGONAL": "DIAG", "LW": "LW", "LEDOIT-WOLF": "LW", "LEDOIT_WOLF": "LW"}
        kind = aliases.get(str(kind).upper(), str(kind))
        key = (int(year), kind)
        if key not in self._checked_covariances:
            if key not in self.covariances:
                raise InfeasiblePolicy("FROZEN_RISK_YEAR_OR_KIND_MISSING")
            matrix = np.asarray(self.covariances[key], dtype=float)
            if (matrix.shape != (count, count) or not np.isfinite(matrix).all()
                    or not np.allclose(matrix, matrix.T, rtol=1e-10, atol=1e-12)
                    or np.any(np.diag(matrix) <= 0)):
                raise InfeasiblePolicy("FROZEN_RISK_INVALID_OR_UNKNOWN")
            lipschitz = self.penalty * np.abs(matrix).sum(axis=1).max()
            if not np.isfinite(lipschitz) or lipschitz <= 0:
                raise InfeasiblePolicy("FROZEN_RISK_LIPSCHITZ_INVALID")
            if kind == "DIAG":
                diagonal = np.diag(matrix).copy()
                if not np.allclose(matrix, np.diag(diagonal), rtol=0, atol=1e-12):
                    raise InfeasiblePolicy("DIAG_RISK_CONTAINS_UNDECLARED_CORRELATION")
                matrix = diagonal
            self._checked_covariances[key] = (matrix, 1.0 / lipschitz)
        return self._checked_covariances[key]

    def _optimize(self, mean, uncertainty, covariance, step, current, locked,
                  allowed, buy_allowed, slots, ticker_rank):
        reserved = np.where(locked, current, 0.0)
        mass = 1.0 - float(reserved.sum())
        if mass < -EPS:
            raise InfeasiblePolicy("RESERVED_WEIGHT_EXCEEDS_LONG_ONLY_BUDGET")
        upper = np.where(allowed & buy_allowed, self.max_q,
                         np.where(allowed, np.minimum(current, self.max_q), 0.0))
        valid = np.flatnonzero(upper > EPS)
        if mass <= EPS:
            return reserved, 0, 0.0, float("nan"), "RESERVED_FULL_ACCOUNT"
        if not len(valid):
            raise InfeasiblePolicy("NO_FORECAST_AVAILABLE_COMPOSITION")
        effective = mean[valid] - self.uncertainty_penalty * uncertainty[valid]
        fixed_risk = _covariance_action(covariance, reserved)
        values = np.full(len(mean), -np.inf)
        values[valid] = step * (effective - self.penalty * fixed_risk[valid])
        free = _support_projection(values, upper, mass, slots, ticker_rank)
        residual = np.inf
        best, best_objective = free.copy(), -np.inf
        status = "APPROXIMATE_FIXED_ITERATION_LIMIT"
        for iteration in range(1, self.iterations + 1):
            risk = _covariance_action(covariance, free + reserved)
            values[valid] = free[valid] + step * (effective - self.penalty * risk[valid])
            following = _support_projection(values, upper, mass, slots, ticker_rank)
            residual = float(np.max(np.abs(following - free)) / step)
            joint = following + reserved
            objective = float(effective @ following[valid] - .5 * self.penalty * joint @ _covariance_action(covariance, joint))
            if objective > best_objective:
                best, best_objective = following.copy(), objective
            free = following
            if residual <= self.tolerance:
                best, best_objective = free.copy(), objective
                status = "APPROXIMATE_PROJECTED_FIXED_POINT"
                break
        return best + reserved, iteration, residual, best_objective, status

    def _exposure(self, q, covariance, reserved, kind):
        if kind == "fixed":
            return q, 1.0
        r = float(reserved.sum())
        if r >= 1.0 - EPS:
            raise InfeasiblePolicy("VOL_TARGET_HAS_NO_FREE_EXPOSURE")
        free = q - reserved
        v = free / (1.0 - r)
        a = float(v @ _covariance_action(covariance, v))
        b = float(v @ _covariance_action(covariance, reserved))
        c = float(reserved @ _covariance_action(covariance, reserved))
        daily_target = self.vol_target ** 2 / 252.0
        if not np.isfinite([a, b, c]).all() or a <= 0 or c < -EPS:
            raise InfeasiblePolicy("VOL_TARGET_RISK_UNKNOWN")
        full_variance = a * (1-r) ** 2 + 2*b*(1-r) + c
        if full_variance <= daily_target:
            gross = 1.0
        else:
            discriminant = b*b + a*(daily_target-c)
            if discriminant < 0:
                raise InfeasiblePolicy("VOL_TARGET_INCOMPATIBLE_WITH_RESERVED_RISK")
            free_gross = (-b + np.sqrt(max(0.0, discriminant))) / a
            if not 0 <= free_gross <= 1-r+EPS:
                raise InfeasiblePolicy("VOL_TARGET_INCOMPATIBLE_WITH_RESERVED_RISK")
            gross = float(np.clip(r + free_gross, r, 1.0))
        if gross <= EPS:
            raise InfeasiblePolicy("VOL_TARGET_NO_FEASIBLE_POSITIVE_EXPOSURE")
        weights = reserved + (gross-r)*v
        composition = weights / gross
        variance = float(composition @ _covariance_action(covariance, composition))
        if variance <= 0 or not np.isfinite(variance):
            raise InfeasiblePolicy("VOL_TARGET_NONPOSITIVE_RISK")
        expected = float(np.clip(self.vol_target / np.sqrt(252.0*variance), 0.0, 1.0))
        if abs(expected-gross) > self.tolerance:
            raise InfeasiblePolicy("VOL_TARGET_RESERVED_FIXED_POINT_FAILED")
        return composition, gross

    def __call__(self, day, ctx):
        shape = ctx.current_weights.shape
        if tuple(ctx.path_ids) != self.role_ids or self.mu.shape[1:] != shape:
            raise ValueError("JOINT forecast path/ticker coordinates differ from account context")
        if not 0 <= int(day) < len(self.mu):
            raise ValueError("JOINT signal day outside frozen forecast arrays")
        n = shape[1]
        ticker_rank = np.argsort(np.argsort(np.asarray(ctx.tickers, dtype=str), kind="stable"), kind="stable")
        targets = np.zeros(shape)
        explicit = np.zeros(shape, dtype=bool)
        diagnostics = []
        for row, role in enumerate(self.role_ids):
            config = self.roles[role]
            current = np.asarray(ctx.current_weights[row], dtype=float)
            held = np.asarray(ctx.current_units[row]) > EPS
            mean = np.asarray(self.mu[day, row], dtype=float)
            uncertainty = np.asarray(self.uncertainty[day, row], dtype=float)
            known = np.isfinite(mean) & np.isfinite(uncertainty) & (uncertainty >= 0)
            modeled = np.asarray(ctx.decision_mask[row], dtype=bool) & known
            locked = np.asarray(ctx.reserved_mask[row], dtype=bool).copy()
            locked |= held & ~modeled & ~np.asarray(ctx.operational_mask[row], dtype=bool)
            reserved = np.where(locked, current, 0.0)
            slots = min(self.max_positions, int(ctx.max_positions)) - int(locked.sum())
            allowed = modeled & ~locked & (np.asarray(ctx.buy_allowed[row]) | held)
            record = {"path_id": role, "signal_date": ctx.signal_date, "role": config["kind"],
                      "status": "", "iterations": 0, "projected_gradient_residual": np.nan,
                      "full_candidate_count": int(allowed.sum()), "reserved_slots": int(locked.sum()),
                      "reserved_weight": float(np.nansum(reserved)), "missing_forecast_count": int((ctx.decision_mask[row] & ~known).sum()),
                      "selected_tickers": [], "composition_tickers": [], "relative_weights": [],
                      "selected_uncertainty": [], "selected_marginal_variance": [],
                      "reserved_tickers": np.asarray(ctx.tickers)[locked].tolist(),
                      "reserved_weights": reserved[locked].tolist(), "gross_target": np.nan,
                      "action_target_gross": np.nan, "objective": np.nan,
                      "failure_reason": "", "action_projection_repair": 0.0, "global_optimum_claim": False}
            try:
                if (not np.isfinite(ctx.nav[row]) or ctx.nav[row] <= 0 or not np.isfinite(current).all()
                        or np.any(current < 0) or slots < 0):
                    raise InfeasiblePolicy("ACCOUNT_STATE_UNKNOWN_OR_INVALID")
                if not np.isclose(ctx.max_invested, 1.0):
                    raise InfeasiblePolicy("COMMON_ENGINE_GROSS_BOUND_NOT_ONE")
                if config["kind"] in {"raw", "simple"}:
                    candidate = np.flatnonzero(allowed)
                    ordered = candidate[np.lexsort((ticker_rank[candidate], -mean[candidate]))]
                    selected = ordered[:max(0, slots)]
                    if not len(selected):
                        raise InfeasiblePolicy("RAW_SELECTOR_HAS_NO_LEGAL_AVAILABLE_FORECAST")
                    desired = np.zeros(n)
                    if config["kind"] == "raw":
                        desired[selected] = .0475
                        room = max(0.0, .95-float(reserved.sum()))
                        desired *= min(1.0, room/max(float(desired.sum()), EPS))
                    else:
                        room = 1.0-float(reserved.sum())
                        desired[selected] = room/len(selected)
                        if np.max(desired) > min(self.max_q, ctx.max_weight) + EPS:
                            raise InfeasiblePolicy("SIMPLE_EQUAL_INSUFFICIENT_SLOT_MASS")
                    desired[~ctx.buy_allowed[row]] = np.minimum(desired[~ctx.buy_allowed[row]], current[~ctx.buy_allowed[row]])
                    desired += reserved
                    if config["kind"] == "simple" and abs(desired.sum()-1.0) > 1e-8:
                        raise InfeasiblePolicy("SIMPLE_EQUAL_GROSS_ONE_INFEASIBLE")
                    gross = float(desired.sum())
                    if gross <= EPS:
                        raise InfeasiblePolicy("CONTROL_ZERO_COMPOSITION")
                    q = desired/gross
                    status = "FROZEN_CONTROL_RULE_COMPLETE"
                    iteration, residual, objective = 0, 0.0, np.nan
                else:
                    covariance, step = self._covariance(ctx.signal_date.year, config["risk"], n)
                    q, iteration, residual, objective, status = self._optimize(
                        mean, uncertainty, covariance, step, current, locked, allowed,
                        np.asarray(ctx.buy_allowed[row], bool), slots, ticker_rank)
                    if config["equal"]:
                        support = (q-reserved) > EPS
                        mass = 1.0-float(reserved.sum())
                        equal = mass/int(support.sum()) if support.any() else 0.0
                        upper = np.where(ctx.buy_allowed[row], self.max_q, np.minimum(current, self.max_q))
                        if equal <= 0 or np.any(equal > upper[support]+EPS):
                            raise InfeasiblePolicy("EQUAL_ABLATION_SUPPORT_NOT_FEASIBLE")
                        q = reserved + support*equal
                    q, gross = self._exposure(q, covariance, reserved, config["gross"])
                    desired = gross*q
                    selected = np.flatnonzero((desired-reserved) > EPS)
                if (abs(q.sum()-1.0) > 1e-8 or not 0 < gross <= 1+EPS
                        or len(selected)+int(locked.sum()) > min(self.max_positions, ctx.max_positions)
                        or np.any(desired[~locked] > ctx.max_weight+EPS)
                        or np.any(desired[~ctx.buy_allowed[row]] > current[~ctx.buy_allowed[row]]+EPS)):
                    raise InfeasiblePolicy("TARGET_CONSTRAINT_CHECK_FAILED")
                active_target = desired-reserved
                if config["kind"] == "joint":
                    rho = float(config["rho"])
                    # Selected incumbents partially move toward the joint target;
                    # unselected incumbents exit explicitly, so names cannot grow
                    # to the union of two twenty-name supports.
                    active_target[selected] = (1-rho)*current[selected] + rho*active_target[selected]
                action_upper = np.zeros(n)
                action_upper[selected] = min(self.max_q, float(ctx.max_weight))
                action_upper[~ctx.buy_allowed[row]] = np.minimum(action_upper[~ctx.buy_allowed[row]], current[~ctx.buy_allowed[row]])
                repaired = project_budget(active_target[None, :], np.array([1.0-float(reserved.sum())]), action_upper[None, :])[0]
                record["action_projection_repair"] = float(np.max(np.abs(repaired-active_target)))
                active_target = repaired
                targets[row] = active_target
                explicit[row] = modeled & ~locked
                record.update(status=status, iterations=iteration, projected_gradient_residual=residual,
                              selected_tickers=np.asarray(ctx.tickers)[selected].tolist(),
                              composition_tickers=np.asarray(ctx.tickers)[q>EPS].tolist(),
                              relative_weights=q[q>EPS].tolist(), gross_target=gross,
                              selected_uncertainty=uncertainty[selected].tolist(),
                              selected_marginal_variance=(np.diag(covariance)[selected] if covariance.ndim==2 else covariance[selected]).tolist() if config["kind"]=="joint" else [],
                              action_target_gross=float(active_target.sum()+reserved.sum()), objective=objective)
            except InfeasiblePolicy as error:
                # No explicit model decisions => exact held units are reserved by
                # the unchanged engine. Authoritative operational exits remain
                # the engine's responsibility, including during fallback.
                record.update(status="FALLBACK_PRESERVE_UNITS", failure_reason=str(error))
            diagnostics.append(record)
        if self.callback is not None:
            self.callback(pd.DataFrame(diagnostics))
        module = sys.modules.get(type(ctx).__module__)
        decision_type = getattr(module, "TargetDecision", TargetDecision)
        evidence = np.array([f"JOINT_R1:{role}|{ctx.signal_date.date()}" for role in self.role_ids], dtype=object)
        return decision_type(targets, explicit, evidence)
