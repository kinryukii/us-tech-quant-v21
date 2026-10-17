"""Pure new-research consumers of qualified forecasts and existing risk states.

The caller owns all source, clock, UID and original-artifact qualification. This
module reads no files and estimates nothing. Both policies use the same account
capacity rule; old Joint retains Q0. The explicit PTO descendant adds
canonical robust/cost allocation without changing old policy identities.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scripts.research.a2.inference.joint_portfolio_policy import (
    EPS, _support_projection, _capped_mass,
)
from scripts.research.a2.portfolio.joint_allocation_methods import allocate_q
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision


class FeasiblePolicyBlocked(ValueError):
    pass


@dataclass(frozen=True)
class FeasiblePolicyResult:
    target: TargetDecision
    receipt: dict


def _need(condition, reason):
    if not condition:
        raise FeasiblePolicyBlocked(reason)


def required_mask(ctx):
    """External information must cover eligible union actual holdings."""
    return ((np.asarray(ctx.current_units)[0] > EPS)
            | (np.asarray(ctx.current_weights)[0] > EPS)
            | (np.asarray(ctx.decision_mask)[0] & np.asarray(ctx.buy_allowed)[0]))


def feasible_capacity(ctx):
    """One maximum deployable account budget, independent of policy scores."""
    assets = tuple(map(str, ctx.tickers))
    n = len(assets)
    _need(len(set(assets)) == n and len(ctx.path_ids) == 1,
          "UNIQUE_SINGLE_ACCOUNT_ASSET_DOMAIN_REQUIRED")
    _need(ctx.max_positions == 20 and ctx.max_weight == .1 and ctx.max_invested == 1.,
          "FIXED_COMMON_ACCOUNT_CONSTRAINTS_REQUIRED")
    asof = pd.Timestamp(ctx.signal_asof)
    _need(asof.tzinfo is not None and asof < pd.Timestamp('2026-01-01', tz='UTC')
          and pd.Timestamp('2023-01-01') <= pd.Timestamp(ctx.signal_date).tz_localize(None)
          < pd.Timestamp('2026-01-01'), "PRE2026_RESEARCH_CONTEXT_REQUIRED")
    for name in ('current_weights', 'current_units', 'reserved_mask', 'decision_mask',
                 'buy_allowed', 'operational_mask'):
        _need(np.asarray(getattr(ctx, name)).shape == (1, n),
              "ACCOUNT_CONTEXT_SHAPE_MISMATCH:" + name)
    for name in ('reserved_mask', 'decision_mask', 'buy_allowed', 'operational_mask'):
        _need(np.asarray(getattr(ctx, name)).dtype == bool,
              "BOOLEAN_ACCOUNT_MASK_REQUIRED:" + name)
    for name in ('nav', 'cash', 'cash_weight'):
        _need(np.asarray(getattr(ctx, name)).shape == (1,),
              'ACCOUNT_CONTEXT_SHAPE_MISMATCH:' + name)
    current = np.asarray(ctx.current_weights[0], float)
    units = np.asarray(ctx.current_units[0], float)
    _need(np.isfinite(current).all() and np.isfinite(units).all()
          and np.all(current >= 0) and np.all(units >= 0)
          and current.sum() <= 1 + EPS and np.isfinite(ctx.nav[0]) and ctx.nav[0] > 0,
          "ACTUAL_ACCOUNT_STATE_INVALID")
    cash, nav = float(ctx.cash[0]), float(ctx.nav[0])
    cash_weight = float(ctx.cash_weight[0])
    _need(np.isfinite(cash) and cash >= 0 and np.isfinite(cash_weight)
          and cash_weight >= 0 and abs(cash_weight - cash / nav) <= 1e-8,
          'ACTUAL_LIQUID_CASH_STATE_INVALID')
    spendable_budget = float(current.sum()) + cash / nav
    _need(spendable_budget <= 1 + EPS, 'STOCK_AND_CASH_EXCEED_ACCOUNT_NAV')
    # Receivables remain part of NAV, but cannot finance stock targets.
    spendable_budget = min(1., spendable_budget)
    held = (units > EPS) | (current > EPS)
    modeled = np.asarray(ctx.decision_mask[0])
    operational = np.asarray(ctx.operational_mask[0])
    locked = np.asarray(ctx.reserved_mask[0]).copy() | (held & ~modeled & ~operational)
    reserved = np.where(locked, current, 0.)
    slots = 20 - int(locked.sum())
    _need(slots >= 0, "LOCKED_HOLDINGS_EXCEED_POSITION_LIMIT")
    buy = np.asarray(ctx.buy_allowed[0])
    allowed = modeled & ~locked & (buy | held)
    upper = np.where(allowed & buy, .1, np.where(allowed, np.minimum(current, .1), 0.))
    candidates = np.flatnonzero(upper > EPS)
    capacity = float(np.sort(upper[candidates])[-slots:].sum()) if slots and len(candidates) else 0.
    mass = min(max(0., spendable_budget - float(reserved.sum())), capacity)
    return dict(assets=assets, current=current, locked=locked, reserved=reserved,
                slots=slots, allowed=allowed, buy=buy, upper=upper, mass=mass,
                investment_budget=float(reserved.sum()) + mass,
                spendable_budget=spendable_budget)

# Explicit development integration; never an old P0/P1/P2 frozen identity.
PTO_REUSE_KIND = "PTO_REUSE_ROBUST_COST"
RAW_SOURCE_REUSE_KIND = "RAW_A2_SOURCE_REUSE"
PTO_FORECAST_RECIPE = "RIDGE_HGB_EQUAL"
PTO_REUSE_PROFILE = dict(forecast_recipe=PTO_FORECAST_RECIPE,
    allocator="robust_cost_aware", execution_friction_bps=10,
    gross="MAXIMUM_FEASIBLE_LIQUID_BUDGET", action="FULL_TARGET",
    uncertainty="TWO_MEMBER_DISAGREEMENT_NOT_CALIBRATED_PREDICTIVE_SD",
    new_fit_units=0, frozen_historical_identity=False)

# Bounded new-policy descendants. Original Simple/Joint remain the default pair.
MECHANISM_PANEL_POLICIES = {
    "JOINT_REUSE_NO_ALPHA": dict(opportunity_use="FIXED_ZERO_Q0_OBJECTIVE", gross="G0", action="FULL_TARGET"),
    "JOINT_REUSE_G1": dict(opportunity_use="P0", gross="G1", action="FULL_TARGET"),
    "JOINT_REUSE_A2": dict(opportunity_use="P0", gross="G0", action="ORIGINAL_A2"),
    "JOINT_REUSE_G1_A2": dict(opportunity_use="P0", gross="G1", action="ORIGINAL_A2"),
}
MECHANISM_PANEL_PROFILE = dict(
    schema="B_FIXED_FOUR_MECHANISM_DESCENDANTS_V1",
    policies=MECHANISM_PANEL_POLICIES, primary_cost_bps=10, sessions=752,
    opportunity_scope="CONDITIONAL_ON_ORIGINAL_ADMITTED_POOL_AND_INFORMATION_COMPLETENESS",
    opportunity_source_values_preserved=True, no_fake_zero_forecasts=True,
    joint_baseline_action="FULL_TARGET_NEW_DESCENDANT_NOT_OLD_A0",
    g1=dict(annual_volatility_target=.10, annualization=252/5),
    a2=dict(uncertainty_multiplier=.5, band=0., minimum_trade_usd=0.),
    no_new_forecast_training=True, no_new_learned_Gross=True,
)


def _panel_capacity_gross(weights, matrix, reserved, capacity):
    """Reuse G1 in a unit-capacity coordinate, then restore actual NAV weights."""
    from scripts.research.a2.portfolio.joint_allocation_methods import exposure, SPEC
    capacity=float(capacity)
    if capacity <= EPS:
        return np.asarray(weights,float).copy()
    _need(0 < capacity <= 1 and np.isfinite(capacity), "PANEL_INVALID_SPENDABLE_CAPACITY")
    _need(SPEC["volatility_target_annual"]==.10 and SPEC["annualization"]==252/5,
          "ORIGINAL_FROZEN_G1_PARAMETERS_CHANGED")
    q=np.asarray(weights,float)/capacity
    _need(abs(float(q.sum())-1.)<=1e-8, "PANEL_COMPLETE_COMPOSITION_REQUIRED")
    # Arithmetic coordinate conversion only; original matrix/receipt is preserved.
    composition,gross=exposure(q,np.asarray(matrix,float)*capacity**2,
                               np.asarray(reserved,float)/capacity,"volatility_targeting")
    following=capacity*gross*composition
    _need(np.all(following >= reserved-EPS)
          and np.allclose(following[reserved>EPS],reserved[reserved>EPS],rtol=0,atol=1e-10),
          "PANEL_GROSS_CHANGED_RESERVED_HOLDINGS")
    return following


def _panel_original_a2(kind, mu, uncertainty, covariance, ctx, qualified):
    """Original .5 hysteresis, band0/min0, around the same feasible target owner."""
    from scripts.research.a2.inference.joint_stateful_policy import RuleStatefulPolicy
    inner="JOINT_REUSE_G1" if kind=="JOINT_REUSE_G1_A2" else "JOINT_REUSE"
    captured=[]
    def base(day,gated):
        result=feasible_target(inner,mu,uncertainty,covariance,gated,
                               covariance_psd_qualified=qualified)
        captured.append(result)
        return result.target
    decision=RuleStatefulPolicy(base,np.asarray(mu)[None,None,:],
        np.asarray(uncertainty)[None,None,:],no_trade_band=0.,minimum_trade_usd=0.,
        hysteresis=.5)(0,ctx)
    receipt=dict(captured[-1].receipt)
    receipt.update(kind=kind,mechanism_panel=True,action="ORIGINAL_A2",
                   uncertainty_multiplier=.5,no_trade_band=0.,minimum_trade_usd=0.,
                   original_A0_partial_rebalance_claim=False)
    return FeasiblePolicyResult(decision,receipt)


def feasible_target(kind, mu, uncertainty, covariance, ctx, *, covariance_psd_qualified=False):
    """Produce a target; residual cash is caused by actual caps/slots/locks.

    SIMPLE_FEASIBLE selects by descending unchanged P0 mean, then ticker, and
    equally allocates the largest feasible mass, with cap saturation. JOINT_REUSE
    solves canonical Q0 on the same capacity with its original fixed parameters.
    Execution cash scaling and transaction costs remain the common engine's job.
    """
    if kind == RAW_SOURCE_REUSE_KIND:
        feasible_capacity(ctx)  # Validate account/clock only; preserve Raw target rule.
        from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
        from scripts.research.a2.evaluation.joint_method_accounts import PARAMETERS
        mean, sigma = np.asarray(mu, float), np.asarray(uncertainty, float)
        required = required_mask(ctx)
        _need(mean.shape == sigma.shape == required.shape
              and np.isfinite(mean[required]).all() and np.isfinite(sigma[required]).all()
              and np.all(sigma[required] >= 0), "RAW_REQUIRED_SOURCE_FORECAST_UNAVAILABLE")
        records = []
        def record(frame):
            rows = frame.to_dict('records') if hasattr(frame, 'to_dict') else [frame]
            for row in rows:
                _need(not str(row.get('status', '')).startswith('FALLBACK'),
                      'ORIGINAL_RAW_POLICY_FALLBACK:' + str(row.get('failure_reason', row.get('reason', row.get('status')))))
                records.append(row)
        pid = ctx.path_ids[0]
        original = JointResearchPolicy((pid,), mean[None, None, :], sigma[None, None, :], {},
            roles={pid: dict(kind='raw')}, parameters=PARAMETERS, on_diagnostics=record)
        target = original(0, ctx)
        return FeasiblePolicyResult(target, dict(kind=kind, allocator='ORIGINAL_RAW_A2_POLICY',
            original_rule_owner='JointResearchPolicy:raw', raw_selected_weight=.0475,
            raw_target_gross_cap=.95, original_diagnostics=records, strict_PIT=False,
            production_qualified=False, quote_qualified=False, certified_NAV=False))
    _need(kind in ('SIMPLE_FEASIBLE', 'JOINT_REUSE', PTO_REUSE_KIND) or kind in MECHANISM_PANEL_POLICIES,
          "UNKNOWN_PAIR_POLICY_KIND")
    if kind in ('JOINT_REUSE_A2','JOINT_REUSE_G1_A2'):
        return _panel_original_a2(kind,mu,uncertainty,covariance,ctx,covariance_psd_qualified)
    c = feasible_capacity(ctx)
    n = len(c['assets'])
    mean = np.asarray(mu, float)
    sigma = np.asarray(uncertainty, float)
    _need(mean.shape == sigma.shape == (n,), "FORECAST_VECTOR_DOMAIN_MISMATCH")
    required = required_mask(ctx)
    _need(np.isfinite(mean[required]).all() and np.isfinite(sigma[required]).all()
          and np.all(sigma[required] >= 0), "REQUIRED_FORECAST_UNAVAILABLE")
    mean = np.where(required, mean, 0.)
    sigma = np.where(required, sigma, 0.)
    ranks = np.argsort(np.argsort(np.asarray(c['assets']), kind='stable'), kind='stable')
    if kind == 'SIMPLE_FEASIBLE':
        # Only ordering selects Simple names. Scale ordinal scores by free
        # mass so arbitrary forecast magnitudes cannot zero selected support.
        values = np.full(n, -np.inf)
        ids = np.flatnonzero(c['upper'] > EPS)
        ordered = ids[np.lexsort((ranks[ids], -mean[ids]))]
        if len(ordered):
            values[ordered] = (2. + np.arange(len(ordered), 0, -1) / (len(ordered) + 1)) * c['mass'] / max(1, c['slots'])
        support = _support_projection(values, c['upper'], c['mass'], c['slots'], ranks) > EPS
        free = np.zeros(n)
        if support.any():
            free[support] = _capped_mass(np.zeros(int(support.sum())), c['upper'][support], c['mass'])
        weights = c['reserved'] + free
        status, iterations, residual = 'DETERMINISTIC_MAX_FEASIBLE_EQUAL', 0, 0.
    else:
        matrix = np.asarray(covariance, float)
        _need(covariance_psd_qualified is True, "CALLER_QUALIFIED_EXISTING_COVARIANCE_REQUIRED")
        _need(matrix.shape == (n, n) and np.isfinite(matrix).all()
              and np.allclose(matrix, matrix.T, rtol=0, atol=1e-12)
              and np.all(np.diag(matrix) > 0), "EXISTING_COVARIANCE_DOMAIN_OR_VALUES_INVALID")
        # Explicit policy-use ablation. No source forecast value is changed.
        objective_mean = np.zeros_like(mean) if kind=='JOINT_REUSE_NO_ALPHA' else mean
        method = PTO_REUSE_PROFILE['allocator'] if kind == PTO_REUSE_KIND else 'mean_variance'
        friction = PTO_REUSE_PROFILE['execution_friction_bps'] if kind == PTO_REUSE_KIND else 0.
        solved = allocate_q(method, objective_mean, sigma, matrix, c['current'], c['locked'],
                            c['allowed'], c['buy'], c['slots'], ranks,
                            execution_friction_bps=friction, investment_budget=c['investment_budget'])
        weights = solved.q
        if kind=='JOINT_REUSE_G1':
            weights = _panel_capacity_gross(weights,matrix,c['reserved'],c['investment_budget'])
        status, iterations, residual = solved.status, solved.iterations, solved.residual
    explicit = np.asarray(ctx.decision_mask[0]) & ~c['locked']
    target = np.where(explicit, weights - c['reserved'], 0.)
    effective = np.where(explicit, target, c['current'])
    effective[np.asarray(ctx.operational_mask[0]) & ~c['locked']] = 0.
    _need(np.isfinite(target).all() and np.all(target >= -EPS)
          and np.all(target[explicit] <= .1 + EPS)
          and effective.sum() <= c['spendable_budget'] + EPS
          and np.count_nonzero(effective > EPS) <= 20
          and np.all(effective[~c['buy']] <= c['current'][~c['buy']] + EPS),
          "MAX_FEASIBLE_TARGET_CONSTRAINT_FAILURE")
    if kind=='JOINT_REUSE_G1':
        _need(float(c['reserved'].sum())-1e-8 <= float(weights.sum()) <= c['investment_budget']+1e-8,
              "PANEL_GROSS_OUTSIDE_SPENDABLE_CAPACITY")
    else:
        _need(abs(float(weights.sum()) - c['investment_budget']) <= 1e-8,
              "MAX_FEASIBLE_MASS_NOT_DEPLOYED")
    receipt = dict(kind=kind, allocator='rank_then_capped_equal' if kind == 'SIMPLE_FEASIBLE' else 'mean_variance',
                   maximum_feasible_gross=c['investment_budget'],
                   residual_cash_weight=max(0., c['spendable_budget'] - float(weights.sum())),
                   spendable_stock_and_cash_weight=c['spendable_budget'],
                   nonspendable_NAV_weight=max(0., 1. - c['spendable_budget']),
                   locked_slots=int(c['locked'].sum()), free_slots=c['slots'], required_asset_count=int(required.sum()),
                   status=status, iterations=iterations, residual=residual, global_optimum_claim=False,
                   strict_PIT=False, production_qualified=False, quote_qualified=False, certified_NAV=False)
    if kind == PTO_REUSE_KIND:
        gross = float(weights.sum())
        receipt.update(PTO_REUSE_PROFILE, kind=kind,
            uncertainty_consumed_in_objective=True, signal_known_cost_consumed_in_objective=True,
            actual_turnover_still_charged_by_common_account=True,
            q=(weights / gross if gross > EPS else np.zeros(n)).tolist(), gross=gross,
            allocation_equivalence=solved.equivalence,
            scientific_scope='PRE2026_DEVELOPMENT_DESCENDANT')
    if kind in MECHANISM_PANEL_POLICIES:
        receipt.update(mechanism_panel=True,opportunity_use=MECHANISM_PANEL_POLICIES[kind]['opportunity_use'],
            forecast_source_values_preserved=True,original_A0_partial_rebalance_claim=False,
            actual_target_invested_weight=float(weights.sum()))
    decision = TargetDecision(target[None, :], explicit[None, :], 'REUSED_ASSET_MAX_FEASIBLE_PAIR')
    return FeasiblePolicyResult(decision, receipt)


class ReusedFeasiblePolicy:
    """Thin callable; input_provider(day, ctx) supplies source-qualified inputs."""
    def __init__(self, kind, input_provider):
        self.kind, self.input_provider = kind, input_provider
        self.diagnostics = []

    def __call__(self, day, ctx):
        inputs = self.input_provider(day, ctx)
        result = feasible_target(self.kind, inputs['mu'], inputs['uncertainty'],
                                 inputs.get('covariance'), ctx,
                                 covariance_psd_qualified=inputs.get('covariance_psd_qualified', False))
        self.diagnostics.append(dict(signal_date=str(pd.Timestamp(ctx.signal_date).date()), **result.receipt))
        return result.target
