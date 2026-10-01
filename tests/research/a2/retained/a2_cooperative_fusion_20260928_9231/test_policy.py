import numpy as np
import pandas as pd

from policy import CooperativePolicy, FIXED, BASE_NAMES, allocate, inference_frame


class FakeBase:
    def predict(self, day, current, cash, age, **kwargs):
        n = len(day)
        ranks = np.tile(np.arange(5)[None, :, None] / 5, (n, 1, 6))
        ranks *= np.linspace(.2, 1., n)[:, None, None]
        raw = {key: ranks[:, :, i].copy() for i, key in enumerate(BASE_NAMES)}
        raw['q10'] = raw['hgb'].copy()
        projected = np.zeros(n); projected[:min(20, n)] = min(.0475, kwargs['max_exposure'] / max(1, min(20, n)))
        return ranks, np.zeros((n, 5)), raw, projected


def actor(name):
    obj = CooperativePolicy.__new__(CooperativePolicy)
    obj.name = name; obj.stage = 'final'; obj.base = FakeBase(); obj.age = {}; obj.meta = None
    return obj


def day(n=30):
    return pd.DataFrame({'ticker': [f'T{i:03}' for i in range(n)],
                         'new_buy_eligible': True, 'realized_vol_20d': .02, 'ret_20d': .1})


def test_fixed_ratios_are_non_equal_and_reconcile():
    assert np.isclose(FIXED.sum(), 1) and not np.allclose(FIXED, 1 / 6)
    scores, ranks, _, _, _, detail = actor('fusion_fixed_non_equal').score(day())
    np.testing.assert_allclose(scores, np.einsum('naj,j->na', ranks, FIXED))
    np.testing.assert_allclose(scores, detail['contributions'].sum(axis=-1))
    assert np.all(scores[:, 0] == 0)


def test_target_fusion_conserves_contributions_then_joint_budget():
    f = day(40)
    scores, _, _, _, _, detail = actor('fusion_target_decisions').score(f, slots=12, exposure=.6)
    np.testing.assert_allclose(detail['mixed_target'], detail['target_contributions'].sum(axis=-1))
    weights, _ = allocate(scores, f.ticker.tolist(), np.zeros(len(f)), np.ones(len(f), bool), 12, .6)
    assert np.sum(weights > 0) <= 12 and weights.sum() <= .6 + 1e-10
    assert np.all(weights <= .1)


def test_restricted_new_names_cannot_be_admitted():
    scores = np.tile([0, 1, 2, 3, 4], (2, 1))
    weights, allowed = allocate(scores, ['A', 'B'], np.array([0., .05]), np.array([False, False]))
    assert weights[0] == 0 and weights[1] <= .05
    assert not allowed[0, 1:].any()


def test_inference_frame_has_only_known_state_no_labels():
    f = day(2); ranks = np.zeros((2, 5, 6)); downside = np.zeros((2, 5))
    frame = inference_frame(f, ranks, downside, [.02, .03], .8, [3, 4])
    assert len(frame) == 10 and not any('label' in c or 'target_advantage' == c for c in frame)
    np.testing.assert_allclose(frame.current_weight, np.repeat([.02, .03], 5))
    np.testing.assert_allclose(frame.age, np.repeat([3, 4], 5))
