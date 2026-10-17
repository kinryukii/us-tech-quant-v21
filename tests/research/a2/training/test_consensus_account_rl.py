"""Synthetic canonical-engine episodes only; no research/source/model reads."""
from dataclasses import replace
from types import SimpleNamespace
import threading
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import consensus_account_rl as bridge
from scripts.research.a2.training import consensus_auxiliary as auxiliary
from scripts.research.a2.evaluation import consensus_cash_account as cash
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as owner

REF = dict(path='SYNTHETIC_ONLY', sha256='a'*64)


def contract():
    return dict(causal_observations=True, source_qualified=True,
        stateful_cash_holdings_fee_account=True, actual_fees_in_reward=True,
        episode_segments_frozen=True, training_reward_years=[2021, 2022],
        activity_caps=list(auxiliary.CAPS), observation_scaling=auxiliary.RECIPE['observation_scaling'],
        reward_definition=auxiliary.RECIPE['reward_definition'],
        dependency_paths=[str(auxiliary.TORCH_SNAPSHOT)],
        reset_segments=[dict(segment_id='2021', start='2021-01-04', end_exclusive='2021-01-08'),
            dict(segment_id='2022', start='2022-01-03', end_exclusive='2022-01-07')],
        chronological_oof_only=True, primary_horizon_sessions=5,
        outer_development_rewards_used=False, activity_gate_ref=REF.copy(), training_inputs_ref=REF.copy())


def factory(seen=None, failure=False, stale=False, future=False):
    def build(segment_id, seed):
        dates = pd.bdate_range('2021-01-04' if segment_id == '2021' else '2022-01-03', periods=4)
        if future:
            dates = pd.bdate_range('2026-01-05', periods=4)
        shape = (len(dates), 2)
        prices = np.full(shape, 100.)
        if stale:
            prices[2, 0] = np.nan
        market = owner.MarketArrays(dates, ['A','B'], np.full(shape, 100.), prices,
            adv=np.full(shape, 1e8), signal_mask=np.array([True,True,True,False]))
        def policy(di, context):
            if failure:
                raise ValueError('SYNTHETIC_CANONICAL_FAILURE')
            return owner.TargetDecision(np.array([[.1, .1]]), context.decision_mask.copy(), 'SYNTHETIC')
        def run(policy, callback):
            result = cash.run_cash_account(market, ['SYNTHETIC'], policy,
                collect_ledgers=False, ledger_callback=callback)
            if seen is not None:
                seen.append(result)
            return result
        return bridge.AccountEpisode(market, policy, run, dict(source_qualified=True,
            chronological_oof_only=True, cash_shareholder_owner_bound=True,
            unsupported_events_fail_closed=True, fresh_lifecycle=True,
            training_inputs_ref=REF.copy(), runner_ref=REF.copy()))
    return build


def synthetic_gate(decision, context, cap):
    # Fixture mapping is intentionally not a production activity-cap definition.
    return owner.TargetDecision(decision.weights * cap/.95, decision.explicit_mask.copy(), 'SYNTHETIC_CAP')


def environment(**kwargs):
    return bridge.AccountEnvironment(contract(), factory(**kwargs), synthetic_gate)


def test_steps_pause_single_canonical_account_and_fee_reward_reconciles():
    results = []
    env = environment(seen=results)
    initial = env.reset('2021', seed=1)
    assert initial['account_state']['nav'] == 3000.
    previous = initial
    for i in range(3):
        state = env.step(.95)
        a, b = previous['account_state'], state['account_state']
        assert state['reward'] == b['nav']/a['nav']-1.
        assert state['transaction_fee_usd'] == b['cumulative_fees']-a['cumulative_fees']
        assert state['as_of'] > previous['as_of']
        assert state['terminated'] == (i == 2)
        np.testing.assert_allclose(b['nav'], b['settled_cash']+b['unsettled_receivable']
            +b['corporate_receivable']+sum(b['position_market_values']), atol=1e-8)
        previous = state
    env.close()
    assert len(results) == 1 and results[0].daily.empty and results[0].fills.empty
    assert env._thread is None
    assert previous['account_state']['cumulative_fees'] > 0.


def test_zero_fixture_gate_action_cannot_receive_artificial_reward():
    env = environment()
    env.reset('2021', seed=1)
    state = env.step(0.)
    assert state['reward'] == state['transaction_fee_usd'] == 0.
    assert not state['account_state']['position_units'].any()
    env.close()


def test_close_while_waiting_and_reset_fresh_lifecycle_leave_no_threads():
    env = environment()
    env.reset('2021', seed=1)
    env.close()
    assert not any(t.name == 'consensus-account-rl' and t.is_alive() for t in threading.enumerate())
    env.reset('2022', seed=2)
    assert env._last_state['account_state']['nav'] == 3000.
    env.close()


@pytest.mark.parametrize('failure,stale,message', [
    (True,False,'SYNTHETIC_CANONICAL_FAILURE'),
    (False,True,'CERTIFIED_QUALIFIED_ACCOUNT_REWARD')])
def test_canonical_error_and_uncertified_reward_reach_caller_without_deadlock(failure, stale, message):
    env = environment(failure=failure, stale=stale)
    env.reset('2021', seed=1)
    with pytest.raises(RuntimeError, match=message):
        env.step(.95)
        env.step(.95)
    env.close()


def test_missing_qualification_future_coordinates_or_non_oof_reject_before_runner():
    c = contract(); c['outer_development_rewards_used'] = True
    with pytest.raises(ValueError, match='PAST_2021_2022_OOF'):
        bridge.AccountEnvironment(c, lambda *args: pytest.fail('unsafe factory invoked'), synthetic_gate)
    env = environment(future=True)
    with pytest.raises(ValueError, match='DATE_COORDINATES'):
        env.reset('2021', seed=1)
    base = factory()
    def unqualified(*args):
        e = base(*args); e.qualification['unsupported_events_fail_closed'] = False
        return e
    env = bridge.AccountEnvironment(contract(), unqualified, synthetic_gate)
    with pytest.raises(ValueError, match='SOURCE_QUALIFIED_OOF_SHAREHOLDER'):
        env.reset('2021', seed=1)
    assert env._thread is None


@pytest.mark.parametrize('method', ['ppo', 'reinforce'])
def test_actual_gradient_owner_trains_from_canonical_stateful_episode(method):
    env = environment(); calls = []
    try:
        fit = auxiliary.fit_account_rl(method, env, on_fit_started=calls.append)
    finally:
        env.close()
    assert isinstance(fit, auxiliary.RLFit), fit
    assert fit.receipt['training_steps'] == 72
    assert len(calls) == fit.receipt['fit_units'] == (1 if method == 'ppo' else 13)
    assert fit.receipt['stateful_rewards'] and fit.receipt['training_reward_years'] == [2021,2022]


def test_frozen_inference_uses_identical_caller_gate_without_fit():
    calls = []
    fit = auxiliary.RLFit('ppo', dict(observation_fields=list(auxiliary.ACCOUNT_FIELDS)), {}, {})
    fit.activity_cap = lambda observation, legal: .5
    def base(di, context):
        calls.append(('base', di)); return 'BASE_TARGET'
    def gate(decision, context, cap):
        calls.append(('gate',decision,context,cap)); return 'GATED_TARGET'
    policy = bridge.FrozenActivityPolicy(base, fit, lambda di,ctx: (np.zeros(4),np.ones(5,bool)), gate)
    assert policy(3, 'CAUSAL_CONTEXT') == 'GATED_TARGET'
    assert calls == [('base',3),('gate','BASE_TARGET','CAUSAL_CONTEXT',.5)]


def test_fit_adapter_reuses_original_owner_and_always_closes_account(monkeypatch):
    env = environment()
    env.reset('2021', seed=1)
    def owner_failure(*args, **kwargs):
        raise RuntimeError('SYNTHETIC_BUDGET_DENIED')
    monkeypatch.setattr(auxiliary, 'fit_account_rl', owner_failure)
    with pytest.raises(RuntimeError, match='SYNTHETIC_BUDGET_DENIED'):
        bridge.fit_activity_policy('ppo', env, on_fit_started=lambda event: None)
    assert env._thread is None


def gate_context(current, *, units=None, operational=None, locked=None, restricted=None):
    current = np.atleast_2d(np.asarray(current, float))
    mask = lambda x: np.zeros_like(current, bool) if x is None else np.broadcast_to(x, current.shape).copy()
    op, lock, sell = mask(operational), mask(locked), mask(restricted)
    return SimpleNamespace(current_weights=current,
        current_units=(current > 0).astype(float) if units is None else np.atleast_2d(units),
        decision_mask=~(op | lock | sell), operational_mask=op,
        reserved_mask=lock, sell_restricted=sell, max_positions=20, max_weight=.10)


def test_activity_delta_scales_current_to_target_instead_of_target_allocation():
    ctx = gate_context([[.08, .03, 0.]])
    base = owner.TargetDecision(np.array([[.02, .09, .08]]), None, 'BASE')
    result = bridge.activity_delta_gate(base, ctx, .5)
    np.testing.assert_allclose(result.weights, ctx.current_weights + .5/.95*(base.weights-ctx.current_weights))
    assert result.raw_evidence_id == 'BASE' and result.explicit_mask.all()
    np.testing.assert_array_equal(base.weights, [[.02,.09,.08]])


@pytest.mark.parametrize('drifted_weight', [.22,.1222223])
def test_activity_drift_above_name_limit_holds_that_name_and_keeps_other_delta(drifted_weight):
    ctx = gate_context([[drifted_weight, .01]])
    base = owner.TargetDecision(np.array([[.08, .09]]))
    result = bridge.activity_delta_gate(base, ctx, .5)
    assert result.weights[0,0] > .10 and not result.explicit_mask[0,0]
    assert result.explicit_mask[0,1] and .01 < result.weights[0,1] < .09
    np.testing.assert_array_equal(ctx.current_units, [[1.,1.]])


def test_activity_partial_exit_residual_overflow_cancels_all_ordinary_changes():
    ctx = gate_context([[.025]*20 + [0.]])
    target = np.array([[0.] + [.025]*19 + [.025]])
    result = bridge.activity_delta_gate(owner.TargetDecision(target), ctx, .5)
    assert result.weights[0,0] > 0 and result.weights[0,-1] > 0
    assert not result.explicit_mask.any()  # 20 residual names plus one new name.


@pytest.mark.parametrize('cap', [0., .5])
def test_activity_forced_and_stock_distribution_exit_masks_and_locks_are_retained(cap):
    # Both original operational and stock-distribution exits enter this same
    # canonical mask before the policy. Selling restrictions remain owner-owned.
    ctx = gate_context([[.04,.03,.02,.01,0.]], operational=[[True,True,False,False,False]],
        locked=[[False,False,True,False,False]], restricted=[[False,True,False,False,False]])
    originals = {k: v.copy() for k,v in vars(ctx).items() if isinstance(v,np.ndarray)}
    base = owner.TargetDecision(np.array([[0.,0.,0.,0.,.08]]), ctx.decision_mask.copy())
    result = bridge.activity_delta_gate(base, ctx, cap)
    np.testing.assert_array_equal(result.explicit_mask[0,:3], [False,False,False])
    np.testing.assert_array_equal(result.weights[0,:3], base.weights[0,:3])
    for key,value in originals.items():
        np.testing.assert_array_equal(getattr(ctx,key), value)
    assert result.explicit_mask[0,3:].all() == bool(cap)


def test_activity_zero_is_no_ordinary_decision_and_max_cap_is_exact_identity():
    ctx = gate_context([[.06,0.]])
    base = owner.TargetDecision(np.array([[0.,.08]]))
    assert bridge.activity_delta_gate(base, ctx, .95) is base
    zero = bridge.activity_delta_gate(base, ctx, 0.)
    assert not zero.explicit_mask.any()
    invalid = owner.TargetDecision(np.full((1,21), .025))
    many = gate_context(np.zeros((1,21)))
    for cap in (0.,.5,.95):
        assert bridge.activity_delta_gate(invalid, many, cap) is invalid


def test_activity_zero_keeps_canonical_operational_exit_and_never_undoes_sell_lock():
    dates = pd.bdate_range('2021-01-04', periods=4)
    shape = (4,3)
    restricted = np.zeros(shape,bool); restricted[1:,1] = True
    evidence = owner.OperationalEvidence('SYNTHETIC_EXIT', dates[1], 'SYNTHETIC_SOURCE')
    market = owner.MarketArrays(dates, ['EXIT','LOCKED','OTHER'], np.full(shape,100.), np.full(shape,100.),
        adv=np.full(shape,1e8), sell_restricted=restricted,
        known_restrictions_evidence=[dict(signal_date=d, ticker='LOCKED', known_at=d,
            source_id='SYNTHETIC_SOURCE', reason='SYNTHETIC_SELL_LOCK', sell_restricted=True) for d in dates[1:]],
        operational_exits={dates[1]: {'EXIT':evidence,'LOCKED':evidence}},
        signal_mask=np.array([True,True,True,False]))
    def policy(di, ctx):
        target = owner.TargetDecision(np.full((1,3), .08), ctx.decision_mask.copy())
        return bridge.activity_delta_gate(target, ctx, .95 if di==0 else 0.)
    result = cash.run_cash_account(market, ['SYNTHETIC'], policy)
    orders = result.orders[result.orders.signal_date.eq(dates[1])].set_index('ticker')
    assert orders.loc['EXIT','decision_semantic'] == 'OPERATIONAL_EXIT_REQUIRED'
    assert orders.loc['LOCKED','decision_semantic'] == 'OPERATIONAL_EXIT_REQUIRED'
    assert orders.loc['OTHER','decision_semantic'] == 'MODEL_NO_DECISION'
    positions = result.positions[result.positions.date.eq(dates[2])].set_index('ticker')
    assert 'EXIT' not in positions.index
    assert positions.loc['LOCKED','index_units'] > 0 and positions.loc['OTHER','index_units'] > 0
