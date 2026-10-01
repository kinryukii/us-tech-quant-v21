"""Decision-boundary tests only; never fit models or run a research account."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from portfolio_policy import CollaborationPolicy, rank_targets


COEFFICIENTS = np.array([.2, .5, .3])


def frame(names, ridge=None, hgb=None, mlp=None):
    default = np.arange(len(names), 0, -1, dtype=float)
    p = pd.DataFrame({
        'ticker': names,
        'p_ridge': default if ridge is None else ridge,
        'p_hgb': default if hgb is None else hgb,
        'p_mlp': default if mlp is None else mlp,
    })
    p['f_fixed_pred'] = p[['p_ridge', 'p_hgb', 'p_mlp']].to_numpy() @ COEFFICIENTS
    return p


def context(names, *, slots=20, budget=.95, held=None, reserved=()):
    held = {} if held is None else held.copy()
    return SimpleNamespace(
        decision_tickers=tuple(names), available_slots=slots, available_weight=budget,
        current_weights=held.copy(), current_units={k: 100. for k in held},
        reserved_tickers=tuple(reserved), reserved_units={k: 100. for k in reserved},
        reserved_weight=sum(held.get(k, 0.) for k in reserved), max_positions=20,
        max_weight=.1, max_invested=.95,
    )


def test_missing_input_reserved_holding_is_not_an_explicit_exit():
    day = frame(['A', 'B'])
    ctx = context(['A', 'B'], slots=19, budget=.75, held={'LOCKED': .2}, reserved=('LOCKED',))
    before = deepcopy(ctx.__dict__)
    result = CollaborationPolicy('fixed_pred', COEFFICIENTS)(day, ctx)
    assert set(result.model_decisions) == {'A', 'B'}
    assert 'LOCKED' not in result.model_decisions
    assert 'LOCKED' not in result.raw_model_outputs
    assert ctx.__dict__ == before


def test_decidable_unselected_old_holding_gets_explicit_zero():
    day = frame(['NEW', 'OLD'], ridge=[2., 1.], hgb=[2., 1.], mlp=[2., 1.])
    result = CollaborationPolicy('fixed_pred', COEFFICIENTS)(
        day, context(['NEW', 'OLD'], slots=1, held={'OLD': .04}))
    assert result.model_decisions['OLD'] == 0.
    assert result.model_decisions['NEW'] == pytest.approx(.0475)
    assert result.raw_model_outputs['OLD']['mapped_weight'] == 0.


def test_forecast_ties_use_ticker_not_frame_order_and_invalid_score_fails():
    first = rank_targets([1., 1., 1.], ['C', 'A', 'B'], 1, .95)
    second = rank_targets([1., 1., 1.], ['B', 'C', 'A'], 1, .95)
    assert dict(zip(['C', 'A', 'B'], first)) == dict(zip(['B', 'C', 'A'], second))
    assert first.tolist() == [0., .0475, 0.]
    for invalid in [float('nan'), float('inf')]:
        with pytest.raises(ValueError):
            rank_targets([1., invalid], ['A', 'B'], 2, .95)
    with pytest.raises(ValueError):
        rank_targets([1., 2.], ['A', 'A'], 2, .95)


def test_fewer_than_twenty_candidates_leave_unused_budget_as_cash():
    day = frame(['A', 'B', 'C'])
    for policy in ['fixed_pred', 'decision_blend']:
        result = CollaborationPolicy(policy, COEFFICIENTS)(day, context(day.ticker))
        assert list(result.model_decisions.values()) == pytest.approx([.0475] * 3)
        assert sum(result.model_decisions.values()) == pytest.approx(.1425)
        assert sum(result.model_decisions.values()) < .95


def test_available_slots_and_budget_apply_to_both_mapping_levels():
    names = [f'T{i:02d}' for i in range(25)]
    day = frame(names)
    for policy in ['fixed_pred', 'decision_blend']:
        result = CollaborationPolicy(policy, COEFFICIENTS)(day, context(names, slots=2, budget=.04))
        w = np.array(list(result.model_decisions.values()))
        assert np.count_nonzero(w) == 2
        assert w.sum() == pytest.approx(.04)
        assert w.min() >= 0 and w.max() <= .0475
        no_slots = CollaborationPolicy(policy, COEFFICIENTS)(day, context(names, slots=0, budget=.04))
        assert all(v == 0 for v in no_slots.model_decisions.values())
        no_budget = CollaborationPolicy(policy, COEFFICIENTS)(day, context(names, slots=20, budget=0))
        assert all(v == 0 for v in no_budget.model_decisions.values())
    assert np.count_nonzero(rank_targets(np.arange(25), names, 25, .95)) == 20


def test_target_blend_and_forecast_blend_are_distinct_decisions():
    # Large ridge magnitude wins the forecast mean; two other members win the
    # same-account target vote. Dropped target weight must remain as cash.
    day = frame(['A', 'B'], ridge=[100., 0.], hgb=[0., 3.], mlp=[0., 2.])
    ctx = context(['A', 'B'], slots=1)
    pred = CollaborationPolicy('fixed_pred', COEFFICIENTS)(day, ctx)
    target = CollaborationPolicy('decision_blend', COEFFICIENTS)(day, ctx)
    assert pred.model_decisions == {'A': .0475, 'B': 0.}
    assert target.model_decisions['A'] == 0.
    assert target.model_decisions['B'] == pytest.approx(.0475 * .8)
    assert sum(target.model_decisions.values()) < sum(pred.model_decisions.values())
    assert target.raw_model_outputs['B']['base_targets'] == [0., .0475, .0475]


def test_future_prices_states_and_labels_are_rejected_at_policy_boundary():
    names = ['A', 'B']
    forbidden = ['next_open', 'following_open', 'target', 'target_end_date',
                 'y_next_open', 'label_end_date', 'future_price', 'future_state']
    for policy in ['fixed_pred', 'decision_blend']:
        actor = CollaborationPolicy(policy, COEFFICIENTS)
        for column in forbidden:
            day = frame(names)
            day[column] = 123456.
            with pytest.raises(ValueError, match='FUTURE|LABEL|FORBIDDEN'):
                actor(day, context(names))


def test_invalid_frozen_coefficients_fail_before_any_policy_call():
    invalid = [[.2, .5], [.2, .5, .4], [-.1, .5, .6],
               [float('nan'), .5, .5], [float('inf'), 0., 0.]]
    for policy in ['fixed_pred', 'decision_blend', 'base_ridge']:
        for coefficients in invalid:
            with pytest.raises(ValueError, match='COEFFICIENT'):
                CollaborationPolicy(policy, coefficients)
