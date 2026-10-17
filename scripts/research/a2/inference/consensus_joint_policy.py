"""Task-scoped joint account adapter; reused numerical owners, no market reader.

The statistical predictors/fusion are supplied already in one five-session unit.
One account objective decides the entire target, including cash. Fixed transaction
fees and cardinality make this an approximate constrained solve, not a global
optimality certificate. Unknown source provenance never becomes PIT certified.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import ast
import copy
import hashlib
from types import SimpleNamespace
import numpy as np
import pandas as pd

from scripts.research.a2.portfolio import joint_allocation_methods as allocation
from scripts.research.a2.inference.joint_portfolio_policy import _support_projection, EPS
from scripts.research.a2.risk import joint_risk_estimators as risk
from scripts.research.a2.training.stateful_account import apply_controls, CONTROL_SPEC
from scripts.research.a2.evaluation.consensus_cash_account import (
    FeeConfig, fee_for_notional, quote_transition_cost, _CashRules,
)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

UNIT = "FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN"
RISK_METHODS = tuple(risk.CONFIGS)
ALLOCATION_METHODS = tuple(m for m in allocation.ALLOCATION_METHODS if m != "robust_cost_aware")
PRIMARY_RISKS = ("DIAG", "LW", "EWMA", "PCA", "OAS", "SCOV", "FA")
CANDIDATE_ALLOCATIONS = ("cost_aware", "equal_weight", "inverse_volatility", "gmv", "erc", "hrp",
                         "mean_variance", "robust_mean_variance", "mean_cvar", "mean_semivariance", "log_growth")
OWNER_SHA = "4b050af465a4432012a972b12b86302f88b089f322fd7b696dbef81ac7ea26a5"
OWNER_AST_SHA = "bda3400f9cdc64fd84bb0a5c1b19ece33cf20f40b3b82cf692de323e46400ecf"
SUPPORT_AST_SHA = "83e8faacf80e9eff13e809f0fdcc7e04ad53ab5c848b3203048b97389e509766"
CUTOFF = pd.Timestamp("2026-01-01")


@dataclass(frozen=True)
class PolicyConfig:
    risk_method: str = "LW"
    allocation_method: str = "cost_aware"
    lookback_sessions: int = 120
    controls: tuple[str, ...] = ("partial_rebalancing", "no_trade_band", "minimum_trade_usd")
    def __post_init__(self):
        if self.risk_method not in PRIMARY_RISKS or self.allocation_method not in CANDIDATE_ALLOCATIONS:
            raise ValueError("METHOD_NOT_IN_OUTCOME_FREE_TASK_CATALOGUE")
        if self.lookback_sessions not in (60, 120):
            raise ValueError("FIXED_LOOKBACK_60_OR_120_REQUIRED")
        if self.controls != ("partial_rebalancing", "no_trade_band", "minimum_trade_usd"):
            raise ValueError("ONE_FIXED_CONTROL_RECIPE_REQUIRED")


def catalogue():
    return dict(risk_methods=RISK_METHODS, allocation_methods=ALLOCATION_METHODS,
        primary_risks=PRIMARY_RISKS, candidate_allocations=CANDIDATE_ALLOCATIONS,
        primary_paths=[dict(risk_method=m, allocation_method="cost_aware") for m in PRIMARY_RISKS],
        allocation_paths=[dict(risk_method="LW", allocation_method=m) for m in CANDIDATE_ALLOCATIONS if m != "cost_aware"],
        unique_primary_paths=17, main_lookback=120, sensitivity_lookback=60,
        risk_refit_cadence="FIRST_DECISION_EACH_MONTH_THEN_FROZEN; final pre2026 state before test",
        covariance_unit="daily_return_covariance * 5; frozen horizon scaling assumption",
        forecast_unit=UNIT, shared_controls=dict(CONTROL_SPEC), fitted_policy=False,
        task_cost="sum(fee_for_notional(abs(target-current)*NAV))/NAV; explicit full exits bypass ordinary minimum only",
        joint_objective="4*0.5*w.T@C5@w - effective_mu@w + exact quoted one-way all-in and fixed fees/NAV",
        cash_constraint="sum(buy_notional + actual_fee_quote) <= settled cash; no same-session unsettled sale funding",
        solver="existing allocate_q fixed 128 iterations and support/capped projection; budget inequality adaptation",
        optimality_claim=False, source_provenance="UNKNOWN remains UNKNOWN",
        erc_scope="owner nonzero risk-parity composition normalization; actual holdings remain settled-cash constrained",
        gmv_scope="risk-only budget-inequality GMV can prefer all cash; no forced gross or renormalization")


class _TransitionRules:
    def __init__(self, current, locked, nav, cash, fee_config, method="cost_aware"):
        self.current = np.asarray(current, float)
        self.locked = np.asarray(locked, bool)
        self.nav, self.cash = float(nav), float(cash)
        self.fee_config = fee_config
        # Reuse the exact account's fee-aware buy sizing, with no replay started.
        helper = SimpleNamespace(config=fee_config)
        self.fund_buys = lambda requested, cash: _CashRules.fund_buys(helper, requested, cash)
        self.method = method

    def cost_gradient(self, weights):
        quote = quote_transition_cost(self.current, weights, self.nav, self.fee_config)
        delta = weights - self.current
        gradient = np.where(quote["notional"] > EPS,
                            self.fee_config.one_way_all_in_bps / 10000. * np.sign(delta), 0.)
        gradient[self.locked] = 0.
        return float(quote["total_fee"] / self.nav), gradient

    def project(self, values, upper, mass, slots, ranks):
        # Existing owner selects the support and calls the shared capped-budget
        # primitive. Passing only the requested positive mass removes its old
        # equality/full-investment requirement without adding another optimizer.
        ids = np.flatnonzero(upper > EPS)
        chosen = ids[np.lexsort((np.asarray(ranks)[ids], -np.asarray(values)[ids]))][:max(0, int(slots))]
        requested_mass = min(float(mass), float(np.clip(np.asarray(values)[chosen], 0., upper[chosen]).sum()))
        if self.method == "erc":
            # Risk parity is scale invariant and undefined at all-cash. Retain
            # the owner's nonzero composition normalization for this diagnostic
            # candidate; fee-aware affordability still limits the actual target.
            requested_mass = min(float(mass), float(np.sort(upper[ids])[-max(0,int(slots)):].sum())) if slots else 0.
        free = _support_projection(values, upper, max(0., requested_mass), slots, ranks)
        target = free + np.where(self.locked, self.current, 0.)
        requested_buy = np.maximum(target-self.current, 0.) * self.nav
        funded, _ = self.fund_buys(requested_buy[None, :], np.array([self.cash]))
        # Removed purchases stay as existing units (or cash for new names).
        target = np.where(requested_buy > EPS, self.current + funded[0]/self.nav, target)
        return np.where(self.locked, 0., target)


from types import FunctionType
_allocator_template_cache = None

def _project_allocator(rules):
    global _allocator_template_cache
    p = Path(allocation.__file__)
    if hashlib.sha256(p.read_bytes()).hexdigest() != OWNER_SHA:
        raise ValueError('ALLOCATION_OWNER_SOURCE_CHANGED')
    support_path = Path(__import__(_support_projection.__module__, fromlist=['x']).__file__)
    support_bytes = support_path.read_bytes()
    key = (OWNER_SHA, hashlib.sha256(support_bytes).hexdigest())
    cached = _allocator_template_cache
    if cached is None or cached[0] != key:
        tree = ast.parse(p.read_text(encoding='utf-8'))
        function = copy.deepcopy(next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'allocate_q')))
        if hashlib.sha256(ast.dump(function).encode()).hexdigest() != OWNER_AST_SHA:
            raise ValueError('ALLOCATION_OWNER_AST_CHANGED')
        support_tree = ast.parse(support_bytes.decode('utf-8'))
        support = next((n for n in support_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_support_projection'))
        if hashlib.sha256(ast.dump(support).encode()).hexdigest() != SUPPORT_AST_SHA:
            raise ValueError('CARDINALITY_OWNER_AST_CHANGED')
        old = ast.parse('if requested in {"cost_aware", "robust_cost_aware"} and friction:\n    delta = w-current\n    objective += (friction/10000.)*float(np.abs(delta).sum())\n    gradient += (friction/10000.)*np.sign(delta)').body[0]
        new = ast.parse('task_fee, task_fee_gradient = _transition.cost_gradient(w)\nobjective += task_fee\ngradient += task_fee_gradient').body
        matched = 0
        for node in ast.walk(function):
            for field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, ast.AST) and ast.dump(item) == ast.dump(old):
                            value[index:index + 1] = new
                            matched += 1
        if matched != 1:
            raise ValueError('EXACT_COST_ANCHOR_CHANGED')
        # The account projection permits zero free mass. The owner's
        # normalizations are only defined when their selected support exists.
        normalization_guard_count = 0
        anchors = tuple(ast.dump(ast.parse(text).body[0]) for text in
            ('raw[support]=mass/int(support.sum())', 'raw*=mass/raw.sum()'))
        for node in ast.walk(function):
            for field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, ast.AST) and ast.dump(item) in anchors:
                            value[index] = ast.If(test=ast.parse('support.any()', mode='eval').body,
                                body=[item], orelse=[])
                            normalization_guard_count += 1
        if normalization_guard_count != 2:
            raise ValueError('EXACT_EMPTY_SUPPORT_NORMALIZATION_ANCHORS_CHANGED')
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        namespace = {**allocation.__dict__, '_support_projection': rules.project, '_transition': rules}
        exec(compile(module, str(p), 'exec'), namespace)
        lineage = dict(owner_source_sha256=OWNER_SHA, owner_function_ast_sha256=OWNER_AST_SHA, support_function_ast_sha256=SUPPORT_AST_SHA, projected_function_ast_sha256=hashlib.sha256(ast.dump(function).encode()).hexdigest(), cost_ast_anchor_count=matched, empty_support_normalization_guard_count=normalization_guard_count, empty_support_semantics='KEEP_ZERO_FREE_MASS_CASH_OR_RESERVED_THEN_ORIGINAL_CONTROLS', old_owner_unchanged=True, equality_mass_replaced_by_budget_inequality=True)
        generated = namespace['allocate_q']
        cached = (key, generated.__code__, generated.__defaults__, generated.__kwdefaults__, lineage)
        _allocator_template_cache = cached
    namespace = {**allocation.__dict__, '_support_projection': rules.project, '_transition': rules}
    solver = FunctionType(cached[1], namespace, name='allocate_q', argdefs=cached[2])
    namespace["allocate_q"] = solver
    solver.__kwdefaults__ = None if cached[3] is None else dict(cached[3])
    return (solver, dict(cached[4]))


def allocate_transition(method, mu, uncertainty, covariance5, current, locked, allowed,
                        buy_allowed, slots, ticker_rank, *, nav, settled_cash, fee_config,
                        investment_budget=.95, scenarios=None, forced_exit=None):
    """One account-wide target; no separate q times gross or per-model orders."""
    if method not in CANDIDATE_ALLOCATIONS:
        raise ValueError("TASK_ALLOCATION_NOT_REGISTERED")
    current, locked = np.asarray(current, float), np.asarray(locked, bool)
    forced_exit = np.zeros_like(locked) if forced_exit is None else np.asarray(forced_exit, bool)
    if forced_exit.shape != locked.shape or (forced_exit & locked).any():
        raise ValueError("FORCED_EXIT_MASK_CONFLICT")
    if not np.isfinite(nav) or nav <= 0 or not np.isfinite(settled_cash) or settled_cash < 0:
        raise ValueError("CERTIFIED_NAV_AND_SETTLED_CASH_REQUIRED")
    if method in ("mean_cvar", "mean_semivariance", "log_growth") and scenarios is None:
        raise allocation.AllocationUnavailable("NOT_TESTABLE_WITHOUT_MATURE_CAUSAL_JOINT_SCENARIOS")
    rules = _TransitionRules(current, locked, nav, settled_cash, fee_config, method)
    solver, lineage = _project_allocator(rules)
    result = solver(method, mu, uncertainty, covariance5, current, locked, allowed, buy_allowed,
        slots, ticker_rank, scenarios=scenarios, investment_budget=investment_budget, execution_friction_bps=0.)
    target, explicit = result.q.copy(), np.asarray(allowed, bool).copy()
    target[forced_exit] = 0.
    for control in ("partial_rebalancing", "no_trade_band", "minimum_trade_usd"):
        target, explicit = apply_controls(target, explicit, current, nav, control=control)
    target[locked] = current[locked]
    # All controls preserve full exits. Cash affordability is checked again on
    # the controlled intention using the same account sizing and fee formula.
    requested_buy = np.maximum(target-current, 0.)*nav
    funded, _ = rules.fund_buys(requested_buy[None, :], np.array([settled_cash]))
    target = np.where(requested_buy > EPS, current+funded[0]/nav, target)
    # Partial rebalancing can blend a drifted holding back above the solver's
    # existing target cap. Reapply that cap only to actual model decisions;
    # locked and no-decision holdings retain the account's exact-unit semantics.
    controlled = explicit & ~locked
    target[controlled] = np.minimum(target[controlled], allocation.SPEC["max_q"])
    if np.count_nonzero(target > EPS) > int(slots) + int(locked.sum()):
        raise allocation.AllocationUnavailable("CONTROLLED_CARDINALITY_INFEASIBLE")
    quote = quote_transition_cost(current, target, nav, fee_config)
    # Fixed ticket fees create a no-trade region. Compare final controlled
    # utility against the complete hold account, never against each model.
    def utility(w):
        risk_term = .5*allocation.SPEC["risk_penalty"]*float(w @ np.asarray(covariance5) @ w)
        mean = np.asarray(mu, float).copy()
        if method == "robust_mean_variance":
            mean -= allocation.SPEC["uncertainty_penalty"]*np.asarray(uncertainty)
        fee = rules.cost_gradient(w)[0]
        if method == "mean_cvar":
            loss, _, _ = allocation._smooth_cvar(w[None, :], np.asarray(scenarios)[None, :, :])
            return float(mean @ w) - allocation.SPEC["risk_penalty"]*float(loss[0]) - fee
        if method == "mean_semivariance":
            downside = np.minimum(np.asarray(scenarios) @ w, 0.)
            return float(mean @ w) - allocation.SPEC["risk_penalty"]*float(np.mean(downside**2)) - fee
        if method == "log_growth":
            wealth = 1. + np.asarray(scenarios) @ w
            return -np.inf if (wealth <= 0).any() else float(np.mean(np.log(wealth))) - fee
        if method == "gmv":
            return -.5*float(w @ np.asarray(covariance5) @ w) - fee
        if method == "erc":
            variance = float(w @ np.asarray(covariance5) @ w)
            if variance <= EPS:
                return -np.inf
            active = np.asarray(allowed, bool) | locked
            budgets = active / max(int(active.sum()), 1)
            contribution = w * (np.asarray(covariance5) @ w) / variance
            return -float(np.sum((contribution-budgets)**2)) - fee
        return float(mean @ w) - risk_term - fee
    candidate_utility, hold_utility = utility(target), utility(current)
    valid_hold = (current.sum() <= investment_budget + EPS and np.all(current[~locked] <= allocation.SPEC["max_q"]+EPS)
                  and np.count_nonzero(current > EPS) <= int(slots)+int(locked.sum()))
    no_trade = valid_hold and not forced_exit.any() and candidate_utility <= hold_utility + EPS
    if no_trade:
        target, explicit = current.copy(), np.zeros_like(locked)
        quote = quote_transition_cost(current, target, nav, fee_config)
    buy = np.maximum(target-current, 0.)*nav
    buys_and_fees = float(np.sum(buy+fee_for_notional(buy, fee_config)))
    if buys_and_fees > settled_cash + 1e-7 or target.sum() > investment_budget + 1e-7:
        raise allocation.AllocationUnavailable("FEE_RESERVED_CASH_OR_GROSS_BUDGET_BREACH")
    if (not np.isfinite(target[explicit]).all() or (target[explicit] < 0.).any()
            or (target[explicit] > allocation.SPEC["max_q"] + EPS).any()):
        raise ValueError("INVALID_EXPLICIT_CONTROLLED_TARGET")
    return target, explicit, dict(status=result.status, owner_iterations=result.iterations,
        owner_residual=result.residual, owner_objective=result.objective,
        objective_semantics="TASK_COST_ADAPTED; owner objective before fixed execution controls",
        candidate_utility=candidate_utility, hold_utility=hold_utility, no_trade=no_trade,
        estimated_transition_fee=float(quote["total_fee"]), signal_buy_cash_required=buys_and_fees,
        available_settled_cash=float(settled_cash), method=method, lineage=lineage,
        global_optimum_claim=False, fixed_controls=dict(CONTROL_SPEC))


class ConsensusJointPolicy:
    """Caller-isolated forecasts and causal historical returns -> TargetDecision."""
    def __init__(self, forecasts, past_daily_returns, *, config=None, fee_config=None,
                 scenarios_by_date=None, on_diagnostics=None, shared_risk_cache=None, on_risk_fit_started=None):
        self.config = config or PolicyConfig()
        self.fee_config = fee_config or FeeConfig()
        required = {"signal_date", "ticker", "mu", "sigma", "p_up", "q10", "q50", "q90"}
        if not required.issubset(forecasts.columns) or forecasts.attrs.get("unit") != UNIT:
            raise ValueError("UNIFIED_FIVE_SESSION_FORECAST_FRAME_REQUIRED")
        self.forecasts = forecasts.copy()
        self.forecasts["signal_date"] = pd.to_datetime(self.forecasts.signal_date)
        if self.forecasts.duplicated(["signal_date", "ticker"]).any():
            raise ValueError("FORECAST_KEYS_MUST_BE_UNIQUE")
        self.forecasts = self.forecasts.set_index(["signal_date", "ticker"])
        if not isinstance(past_daily_returns.index, pd.DatetimeIndex) or past_daily_returns.index.has_duplicates or not past_daily_returns.index.is_monotonic_increasing:
            raise ValueError("CAUSAL_DAILY_RETURN_INDEX_REQUIRED")
        self.returns = past_daily_returns.copy()
        self.scenarios = scenarios_by_date or {}
        self.callback = on_diagnostics
        self.risk_cache = {} if shared_risk_cache is None else shared_risk_cache
        self.diagnostics = []
        self.on_risk_fit_started = on_risk_fit_started
        self.monthly_state_keys = {}
        self.last_forced_exit_assets = ()

    def freeze_final_risk(self, known_pre2026_assets):
        """Fit final pre2026 state before opening a separate test-data gate."""
        return self._risk(CUTOFF, tuple(known_pre2026_assets), fit_assets=known_pre2026_assets, allow_final_fit=True)

    def _risk(self, date, tickers, *, fit_assets=None, allow_final_fit=False):
        date = pd.Timestamp(date)
        cutoff = min(date, CUTOFF)
        month = cutoff.to_period("M").start_time
        if month not in self.monthly_state_keys:
            if date >= CUTOFF and not allow_final_fit:
                raise risk.RiskEstimatorBlocked("FINAL_PRE2026_RISK_MUST_ALREADY_BE_FROZEN")
            assets = tuple(sorted(set(tickers if fit_assets is None else fit_assets)))
            columns = [name for name in assets if name in self.returns.columns]
            past = self.returns.loc[self.returns.index < cutoff, columns].tail(self.config.lookback_sessions)
            fingerprint = hashlib.sha256(pd.util.hash_pandas_object(past, index=True).to_numpy().tobytes())
            fingerprint.update(repr(tuple(map(str,past.columns))).encode())
            fingerprint.update(str(self.returns.attrs.get("source_id", "UNKNOWN")).encode())
            key = (month, self.config.risk_method, self.config.lookback_sessions, fingerprint.hexdigest())
            if key not in self.risk_cache:
                if self.on_risk_fit_started is not None:
                    self.on_risk_fit_started(dict(method=self.config.risk_method, cutoff=cutoff.isoformat(),
                        month=month.isoformat(), assets=columns, input_sha256=fingerprint.hexdigest()))
                bundle = risk.fit_risk_estimator(self.config.risk_method, past,
                    params=dict(fit_cutoff=cutoff, return_unit="DAILY_DECIMAL_RETURN",
                        return_horizon_sessions=1, source_id=self.returns.attrs.get("source_id", "UNKNOWN"),
                        information_set_id="CAUSAL_MATURE_DAILY_RETURNS_PRE2026"))
                self.risk_cache[key] = bundle
            self.monthly_state_keys[month] = key
        key = self.monthly_state_keys[month]
        if cutoff < pd.Timestamp(self.risk_cache[key].specification["fit_cutoff"]):
            raise risk.RiskEstimatorBlocked("BACKWARD_DECISION_BEFORE_FROZEN_RISK_CUTOFF")
        covariance, meta = risk.risk_matrix(self.risk_cache[key], tickers, return_metadata=True)
        meta.update(covariance_horizon_sessions=5, scaling="daily covariance * 5; fixed approximation",
                    fit_cutoff=str(self.risk_cache[key].specification["fit_cutoff"]), refit_cadence="FIRST_DECISION_EACH_MONTH_THEN_FROZEN",
                    provenance=self.returns.attrs.get("source_id", "UNKNOWN"))
        return covariance*5., meta

    def __call__(self, di, ctx):
        date = pd.Timestamp(ctx.signal_date)
        if ctx.fee_config != self.fee_config:
            raise ValueError("TRAIN_DECISION_REPLAY_FEE_CONFIG_MISMATCH")
        distribution_exit = getattr(ctx, "stock_distribution_forced_exit_mask", None)
        mechanical = np.zeros_like(ctx.decision_mask, dtype=bool) if distribution_exit is None else np.asarray(distribution_exit, bool)
        if mechanical.shape != np.asarray(ctx.decision_mask).shape or np.any(mechanical & (np.asarray(ctx.current_units) <= EPS)):
            raise ValueError("INVALID_STOCK_DISTRIBUTION_FORCED_EXIT_MASK")
        if np.any(mechanical & ~np.asarray(ctx.operational_mask, bool)):
            raise ValueError("STOCK_DISTRIBUTION_MUST_USE_OPERATIONAL_EXIT_API")
        self.last_forced_exit_assets = tuple(np.asarray(ctx.tickers)[mechanical.any(axis=0)])
        try:
            rows = self.forecasts.loc[date].reindex(ctx.tickers)
        except KeyError:
            return TargetDecision(np.zeros_like(ctx.current_weights), np.zeros_like(ctx.decision_mask), "CONSENSUS_NO_FORECAST")
        values = rows[["mu", "sigma", "p_up", "q10", "q50", "q90"]].to_numpy(float)
        known = np.isfinite(values).all(axis=1) & (values[:, 1] >= 0) & (values[:, 2] >= 0) & (values[:, 2] <= 1)
        known &= (values[:, 3] <= values[:, 4]) & (values[:, 4] <= values[:, 5])
        try:
            fit_mask = np.asarray(ctx.decision_mask, bool).any(axis=0) | (np.asarray(ctx.current_units) > EPS).any(axis=0)
            fit_mask &= ~mechanical.any(axis=0)
            fit_assets = tuple(np.asarray(ctx.tickers)[fit_mask])
            covariance, risk_meta = self._risk(date, tuple(ctx.tickers), fit_assets=fit_assets)
        except (risk.RiskEstimatorBlocked, ValueError) as error:
            audit = dict(signal_date=date.isoformat(), status="NOT_TESTABLE_RISK_PRESERVE_UNITS", reason=str(error))
            self.diagnostics.append(audit)
            if self.callback is not None:
                self.callback(audit)
            return TargetDecision(np.zeros_like(ctx.current_weights), np.zeros_like(ctx.decision_mask), "CONSENSUS_RISK_BLOCKED")
        weights, explicit = np.zeros_like(ctx.current_weights), np.zeros_like(ctx.decision_mask)
        ranks = np.argsort(np.argsort(np.asarray(ctx.tickers), kind="stable"), kind="stable")
        for r, path in enumerate(ctx.path_ids):
            if not np.isfinite(ctx.nav[r]) or ctx.nav[r] <= 0:
                continue
            current = np.asarray(ctx.current_weights[r], float)
            if not np.isfinite(current).all():
                continue
            held = ctx.current_units[r] > EPS
            operational = (ctx.operational_mask[r] | mechanical[r]) & ~ctx.sell_restricted[r]
            locked = (ctx.reserved_mask[r] | (held & ~known)) & ~operational
            allowed = ctx.decision_mask[r] & known & ~locked & ~ctx.operational_mask[r] & ~mechanical[r] & (ctx.buy_allowed[r] | held)
            current_for_solve = current.copy()
            # Operational full-sale fees are part of this same intention;
            # proceeds remain unavailable until the account settles them.
            mu = np.where(known, values[:, 0], 0.)
            sigma = np.where(known, values[:, 1], 0.)
            try:
                target, mask, audit = allocate_transition(self.config.allocation_method, mu, sigma,
                    covariance, current_for_solve, locked, allowed, ctx.buy_allowed[r],
                    max(0, ctx.max_positions-int(locked.sum())), ranks, nav=ctx.nav[r],
                    settled_cash=ctx.settled_cash[r], fee_config=self.fee_config,
                    investment_budget=ctx.max_invested, scenarios=self.scenarios.get(date), forced_exit=operational)
            except allocation.AllocationUnavailable as error:
                target, mask = current.copy(), np.zeros_like(locked)
                audit = dict(status="NOT_TESTABLE_OR_INFEASIBLE_PRESERVE_UNITS", reason=str(error))
            weights[r], explicit[r] = target, mask
            audit.update(path_id=path, signal_date=date.isoformat(), risk=risk_meta,
                configuration=asdict(self.config), forecast_unit=UNIT, fixed_rule_policy=True,
                trained_predictors_supplied_by_caller=True, source_provenance="UNKNOWN_RETAINED_NO_STRICT_PIT_CLAIM")
            self.diagnostics.append(audit)
            if self.callback is not None:
                self.callback(audit)
        return TargetDecision(weights, explicit, "CONSENSUS_JOINT_PTO_ACCOUNT_TARGET")