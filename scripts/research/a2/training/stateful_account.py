"""Stateful overlays around the frozen A2 action policy; one common account engine."""
from __future__ import annotations
import hashlib
import importlib.util
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

REFERENCE = Path("D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/STATEFUL_POLICY.py")
REFERENCE_SHA = "e15d9e14a9b8e8078072c048366808c38e899bcc7c422674bf16eb7688a1bcee"
CONTROL_SPEC = {"no_trade_band": .005, "partial_rebalancing": .5, "minimum_trade_usd": 5., "volatility_target_annual": .10}

def reference_policy_class():
    with REFERENCE.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != REFERENCE_SHA:
            raise ValueError("FROZEN_ACTION_SOURCE_CHANGED")
    name = "_stateful_frozen_action_reference"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REFERENCE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name].StatefulPolicy

class _OnePath:
    fields = {"current_units", "current_weights", "cash", "nav", "available_budget",
              "decision_mask", "buy_allowed", "holding_age", "entry_date", "entry_price", "entry_execution_open"}
    def __init__(self, context, index, alias):
        self.context, self.index, self.path_ids = context, index, (alias,)
    def __getattr__(self, name):
        value = getattr(self.context, name)
        return value[self.index:self.index+1] if name in self.fields else value

class _CurrentVector:
    def __init__(self, index, value):
        self.index, self.value = index, value
    def __getitem__(self, index):
        if index != self.index:
            raise ValueError("POLICY_REQUESTED_ANOTHER_DECISION")
        return self.value

def apply_controls(weights, explicit, current, nav, *, control):
    weights, explicit = weights.copy(), explicit.copy()
    if control == "none" or control == "hysteresis":
        return weights, explicit
    full_exit = explicit & (current > 1e-12) & (weights <= 1e-12)
    change = weights - current
    if control == "no_trade_band":
        hold = explicit & ~full_exit & (np.abs(change) <= CONTROL_SPEC[control])
        weights[hold] = current[hold]
        explicit[hold] = False
    elif control == "minimum_trade_usd":
        hold = explicit & ~full_exit & (np.abs(change) * nav < CONTROL_SPEC[control])
        weights[hold] = current[hold]
        explicit[hold] = False
    elif control == "partial_rebalancing":
        active = explicit & ~full_exit
        weights[active] = current[active] + CONTROL_SPEC[control] * change[active]
    else:
        raise ValueError("UNREGISTERED_CONTROL:" + str(control))
    return weights, explicit

def exposure_budget(mode, relative, value, sigma, covariance5):
    if mode == "fixed":
        return 1.
    relative = np.asarray(relative, float)
    support = relative > 1e-12
    if not support.any():
        return 0.
    covariance5 = np.asarray(covariance5, float)
    if covariance5.shape != (len(relative), len(relative)) or not np.isfinite(covariance5).all():
        return np.nan
    variance5 = float(relative @ covariance5 @ relative)
    if variance5 < -1e-10:
        raise ValueError("NON_PSD_RISK")
    variance5 = max(0., variance5)
    if mode in {"volatility_targeting", "risk_constrained_cash"}:
        annual_vol = np.sqrt(variance5 * 252. / 5.)
        return float(np.clip(CONTROL_SPEC["volatility_target_annual"] / max(annual_vol, 1e-12), 0., 1.))
    if mode == "dynamic":
        if not np.isfinite(value[support]).all() or not np.isfinite(sigma) or sigma < 0:
            return np.nan
        mu = float(relative[support] @ value[support])
        # Conservative common residual uncertainty; not a claim of independent forecast errors.
        uncertainty = float(np.abs(relative[support]).sum()) * sigma
        return float(np.clip(mu / max(variance5 + uncertainty**2, 1e-12), 0., 1.))
    raise ValueError("UNREGISTERED_GROSS:" + str(mode))

def forecast_overlay(mode, value, sigma, vol5, raw_top20):
    """Fixed forecast coordinates only; no selector, q optimizer or fitted state.

    Existing Joint BL couples posterior to its q solver. A's identity-view,
    diagonal reference Sigma5 has this exact closed form and keeps q untouched.
    """
    value=np.asarray(value,float).copy()
    if mode=='none':return value
    if mode=='return_shrink':return .5*value
    if mode!='black_litterman':raise ValueError('UNREGISTERED_FORECAST_OVERLAY:'+str(mode))
    top=np.asarray(raw_top20,bool);vol=np.asarray(vol5,float)
    valid=np.isfinite(value)&np.isfinite(vol)&(vol>=0)&np.isfinite(sigma)&(sigma>=0)
    if int(top.sum())!=20:return np.full_like(value,np.nan)
    reference=top.astype(float)/20.
    variance5=vol**2;prior=variance5*reference
    scaled=.05*variance5;omega=float(sigma)**2
    denominator=scaled+omega
    gain=np.divide(scaled,denominator,out=np.zeros_like(scaled),where=denominator>0)
    value[valid]=prior[valid]+gain[valid]*(value[valid]-prior[valid])
    value[~valid]=np.nan
    return value

def _friction_rates(friction):
    if friction is None:
        return 0., 0.
    if (friction.get("kind") != "FIXED_ADVERSE_OPEN_SLIPPAGE"
            or friction.get("benchmark") != "NEXT_RAW_OPEN"
            or friction.get("authority") != "HYPOTHETICAL_RESEARCH_SCENARIO"
            or not friction.get("scenario_id") or "one_way_bps" not in friction):
        raise ValueError("UNQUALIFIED_ACTION_FRICTION_SCENARIO")
    rates = []
    for field in ("one_way_bps", "fee_bps"):
        value = friction.get(field, 0.)
        if isinstance(value, bool) or not np.isscalar(value):
            raise ValueError("INVALID_FRICTION_RATE")
        value = float(value)
        if not np.isfinite(value) or not 0 <= value < 10000:
            raise ValueError("INVALID_FRICTION_RATE")
        rates.append(value / 10000.)
    return rates[0], rates[1]


def action_friction_overlay(value, held, entrants, friction, *, mode="blind"):
    """First-order per-unit action utility, never a changed return forecast.

    A held stock avoids a sell leg when kept; a new entrant requires a buy leg.
    Replacement carries both legs in the existing utility difference.
    This local rule is not a portfolio optimizer or an exact expected-profit
    test for unequal notionals. Planned dollar costs are quoted separately.
    Gross continues to receive the original forecast.
    """
    if mode not in ("blind", "aware"):
        raise ValueError("UNREGISTERED_ACTION_COST_MODE")
    value = np.asarray(value, float).copy()
    held, entrants = np.asarray(held, bool), np.asarray(entrants, bool)
    if value.ndim != 1 or held.shape != value.shape or entrants.shape != value.shape:
        raise ValueError("ACTION_FRICTION_SHAPE")
    if np.any(held & entrants):
        raise ValueError("HELD_IS_NOT_A_NEW_ENTRANT")
    slip, fee = _friction_rates(friction)
    if mode == "aware" and friction is None:
        raise ValueError("COST_AWARE_REQUIRES_EXPLICIT_EXECUTION_SCENARIO")
    if mode == "aware" and slip + fee:
        value[held] += slip + fee
        value[entrants] -= slip + fee
    return value


def quote_transition_cost(current, target, explicit, signal_nav, friction):
    """Signal-time full-intent cost quote; no next Open or actual-fill claim."""
    current, target = np.asarray(current, float), np.asarray(target, float)
    explicit = np.asarray(explicit, bool)
    if current.ndim != 1 or current.shape != target.shape or explicit.shape != current.shape:
        raise ValueError("TRANSITION_COST_SHAPE")
    if (not np.isfinite(current).all() or not np.isfinite(target).all()
            or (current < -1e-12).any() or (target < -1e-12).any()
            or not np.isfinite(signal_nav) or signal_nav <= 0):
        raise ValueError("TRANSITION_COST_SIGNAL_STATE")
    slip, fee = _friction_rates(friction)
    difference = np.where(explicit, target - current, 0.)
    buy = float(np.maximum(difference, 0.).sum()) * float(signal_nav)
    sell = float(np.maximum(-difference, 0.).sum()) * float(signal_nav)
    return {"planned_buy_notional_usd": buy, "planned_sell_notional_usd": sell,
            "planned_slippage_usd": (buy + sell) * slip,
            "planned_fee_usd": (buy + sell) * fee,
            "planned_friction_usd": (buy + sell) * (slip + fee),
            "cost_quote_role": "SIGNAL_TIME_FULL_INTENT_ESTIMATE_NOT_ACTUAL_FILL",
            "future_open_used": False,
            "input_time_qualification_verified": False,
            "signal_mark_authority": "CALLER_SIGNAL_STATE_NOT_VERIFIED_BY_THIS_QUOTER"}


class StatefulOverlay:
    """Own-state HOLD/SELL/REPLACE, with independent exposure and target controls.

    BUY/ADD/REDUCE remain common-engine execution semantics. No selector is fitted,
    and raw Top20 membership/ranking are never replaced by the value model.
    """
    def __init__(self, candidates, value_packets, top20, qualified, vol5, risk_provider=None, *, descriptive_evaluation_authority=None):
        self.candidates, self.values = candidates, value_packets
        self.top20, self.qualified, self.vol5 = top20, qualified, vol5
        self.risk_provider, self.audit = risk_provider, []
        self.descriptive_evaluation_authority = descriptive_evaluation_authority
        self.reference = reference_policy_class()

    def __call__(self, di, context):
        if self.descriptive_evaluation_authority is not None:
            from scripts.research.a2.evaluation.frozen_test_authority import require_descriptive_decision
            for candidate in self.candidates:
                require_descriptive_decision(self.descriptive_evaluation_authority, context.signal_date, path_id=candidate["candidate_id"])
        elif pd.Timestamp(context.signal_date) >= pd.Timestamp("2026-01-01"):
            raise ValueError("V24_DEVELOPMENT_POLICY_FORBIDS_LOCKED_TEST")
        shape = context.current_units.shape
        weights, explicit = np.zeros(shape), np.zeros(shape, bool)
        for row, candidate in enumerate(self.candidates):
            if str(context.path_ids[row]) != candidate["candidate_id"]:
                raise ValueError("POLICY_PATH_ORDER")
            packet = self.values[candidate["value_model"]]
            value = np.asarray(packet["mu"][di], float)
            sigma = float(packet["sigma"][di])
            vol = np.asarray(self.vol5[di], float)
            held = context.current_units[row] > 1e-10
            source_value = forecast_overlay(candidate.get('forecast','none'),value,sigma,vol,self.top20[di])
            if candidate.get("control") == "hysteresis":
                source_value[held] += sigma
            alias = "A" if candidate["action"] == "stateful" else "B"
            view = _OnePath(context, row, alias)
            friction = candidate.get("execution_friction")
            cost_mode = candidate.get("action_cost_mode", "blind")
            if cost_mode == "aware" and candidate["action"] != "stateful":
                raise ValueError("COST_AWARE_ACTION_REQUIRES_STATEFUL_POLICY")
            entrants = self.top20[di] & self.qualified[di] & view.buy_allowed[0] & view.decision_mask[0] & ~held
            action_value = action_friction_overlay(source_value, held, entrants, friction, mode=cost_mode)
            source = self.reference(_CurrentVector(di, action_value), packet["sigma"], None,
                                    np.full(len(packet["sigma"]), np.nan), self.vol5,
                                    self.top20, self.qualified, packet["lineage"])
            decision = source(di, view)
            w, mask = decision.weights[0].copy(), decision.explicit_mask[0].copy()
            gross_mode = candidate.get("gross", "fixed")
            gross = 1.
            risk_status = "PREDECISION_REALIZED_VOL20_DIAGONAL"
            if gross_mode != "fixed":
                intended = np.where(mask, w, view.current_weights[0])
                amount = float(intended.sum())
                relative = intended / amount if amount > 1e-12 else intended
                selected = np.flatnonzero(relative > 1e-12)
                if not len(selected):
                    covariance = np.zeros((0, 0))
                elif self.risk_provider is None:
                    covariance = np.diag(vol[selected]**2)
                else:
                    covariance = self.risk_provider(di, selected, context.tickers, candidate.get("risk", "diag"))
                    risk_status = candidate.get("risk", "diag")
                gross = exposure_budget(gross_mode, relative[selected], source_value[selected], sigma, covariance)
                if not np.isfinite(gross):
                    w[:] = 0.
                    mask[:] = False
                    risk_status = "MISSING_PAST_RISK_OR_VALUE_HOLD_ACTUAL_UNITS"
                else:
                    forecast_valid = np.isfinite(source_value) & np.isfinite(vol) & np.isfinite(sigma) & (sigma >= 0)
                    hard_frozen = held & (~view.decision_mask[0] | ((candidate["action"] == "stateful") & ~forecast_valid))
                    reserved = hard_frozen
                    reserved_weight = float(view.current_weights[0, reserved].sum())
                    budget = max(0., min(float(view.available_budget[0]), gross - reserved_weight))
                    controllable = selected[~reserved[selected]]
                    w[:] = 0.
                    denom = float(relative[controllable].sum())
                    if denom > 0:
                        w[controllable] = relative[controllable] * budget / denom
                    mask = ((held & view.decision_mask[0]) | (w > 0)) & ~hard_frozen
                    cannot_add = (~self.qualified[di] | ~view.buy_allowed[0]) & (w > view.current_weights[0])
                    w[cannot_add] = np.maximum(0., view.current_weights[0, cannot_add])
            w, mask = apply_controls(w, mask, view.current_weights[0], float(view.nav[0]),
                                     control=candidate.get("control", "none"))
            quote = quote_transition_cost(view.current_weights[0], w, mask, float(view.nav[0]), friction) if friction is not None else {}
            weights[row], explicit[row] = w, mask
            self.audit.append({"candidate_id": candidate["candidate_id"], "signal_date": str(context.signal_date.date()),
                               "value_model": candidate["value_model"], "gross_mode": gross_mode, "gross_target": gross,
                               "risk_status": risk_status, "own_cash": float(view.cash[0]), "own_nav": float(view.nav[0]),
                               "own_holding_count": int(held.sum()), "raw_entrant_count": int(self.top20[di].sum()),
                               "control": candidate.get("control", "none"), "forecast_overlay": candidate.get("forecast", "none"), "forecast_overlay_fits": 0,
                               "action_cost_mode": cost_mode, "execution_friction_scenario": friction.get("scenario_id") if friction else None,
                               "action_friction_is_return_forecast": False, "gross_uses_action_friction_bonus": False, **quote})
        return TargetDecision(weights, explicit_mask=explicit, raw_evidence_id="V24_FROZEN_RAW_STATEFUL_VALUE")

def synthetic_check():
    current = np.array([.10, 0., .05])
    weights = np.array([0., .05, .051])
    explicit = np.ones(3, bool)
    w, m = apply_controls(weights, explicit, current, 3000., control="partial_rebalancing")
    assert w[0] == 0 and w[1] == .025 and np.isclose(w[2], .0505)
    w, m = apply_controls(weights, explicit, current, 3000., control="minimum_trade_usd")
    assert m[0] and m[1] and not m[2]
    w, m = apply_controls(weights, explicit, current, 3000., control="no_trade_band")
    assert m[0] and m[1] and not m[2]
    q = np.array([.5, .5]); cov = np.array([[.001, .0002], [.0002, .001]])
    a = exposure_budget("volatility_targeting", q, np.ones(2), .01, cov)
    b = exposure_budget("risk_constrained_cash", q, np.ones(2), .01, cov)
    assert a == b and 0 <= a <= 1
    assert np.isnan(exposure_budget("dynamic", q, np.array([np.nan, .1]), .01, cov))
    reference_policy_class()
    return {"status": "PASS", "checks": 5, "real_data_read": False, "fitting": False}
