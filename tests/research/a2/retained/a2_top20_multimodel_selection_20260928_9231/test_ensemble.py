"""Temporal leakage, true combination, and holdings-budget tests for ensembles."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ensemble_under_test', HERE / 'ensemble.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_rank_preserves_cash_sign_scale_and_ties():
    advantages = np.array([[0, -.1, .2], [0, -.2, .2], [0, -.4, .8]])
    ranked = module.signed_rank(advantages)
    np.testing.assert_allclose(ranked, module.signed_rank(advantages * 400))
    assert np.all(ranked[:, 0] == 0)
    assert np.all(ranked[:, 1] < 0)
    assert ranked[0, 2] == ranked[1, 2] < ranked[2, 2]
    inputs = np.repeat(ranked[:, :, None], 6, axis=2)
    fused = module.fuse(inputs, np.zeros(ranked.shape), 'ensemble_equal')
    assert np.all(fused[:, 1] < 0)


def test_disagreement_and_downside_formula_is_fixed():
    ranks = np.arange(3 * 5 * 6).reshape(3, 5, 6) / 100.
    ranks[:, 0, :] = 0.
    downside = np.full((3, 5), .3)
    downside[:, 0] = 0.
    expected = ranks.mean(axis=-1) - .25 * ranks.std(axis=-1) - .25 * downside
    np.testing.assert_allclose(module.fuse(ranks, downside, 'ensemble_disagreement'), expected)
    assert np.all(expected <= module.fuse(ranks, downside, 'ensemble_equal') + 1e-14)


def test_oof_rejects_in_sample_base_and_unmatured_labels():
    frame = pd.DataFrame({'signal_date': pd.to_datetime(['2024-03-01']),
                          'label_end_date': pd.to_datetime(['2024-03-05']),
                          'base_fit_cutoff': ['2024-01-01']})
    module.verify_oof_clock(frame, '2025-01-01')
    with pytest.raises(ValueError, match='OOF clock'):
        module.verify_oof_clock(frame.assign(base_fit_cutoff='2025-01-01'), '2025-01-01')
    with pytest.raises(ValueError, match='OOF clock'):
        module.verify_oof_clock(frame.assign(label_end_date=pd.Timestamp('2025-01-01')), '2025-01-01')


def test_actual_ensemble_preserves_reserved_slots_capital_and_buy_restrictions():
    class FakeBases:
        def predict(self, day, current, cash, age, **kwargs):
            assert kwargs['max_names'] == 2
            assert kwargs['max_exposure'] == .15
            n = len(day)
            rank = np.tile(np.arange(5, dtype=float)[None, :, None], (n, 1, 6))
            raw = {name: rank[:, :, i] for i, name in enumerate(module.BASE_NAMES)}
            return rank, np.zeros((n, 5)), raw, np.zeros(n)

    policy = module.EnsemblePolicy.__new__(module.EnsemblePolicy)
    policy.name = 'ensemble_equal'
    policy.stage = 'validation'
    policy.age = {}
    policy.base = FakeBases()
    policy.meta = None
    policy.operational_events = None
    day = pd.DataFrame({'ticker': ['C', 'B', 'A', 'D'],
                        'new_buy_eligible': [True, False, True, True]})
    ctx = SimpleNamespace(current_weights={'B': .025, 'LOCKED': .1}, cash_weight=.5,
                           available_slots=2, available_weight=.15,
                           buy_restricted_tickers={'A'})
    result = policy(day, ctx)
    weights = result.model_decisions
    assert weights['A'] == 0
    assert weights['B'] <= .025
    assert 'LOCKED' not in weights
    assert sum(weight > 0 for weight in weights.values()) <= 2
    assert sum(weights.values()) <= .15 + 1e-12
    assert max(weights.values()) <= .1
    assert set(result.raw_model_outputs['C']['base_action_values']) == set(module.BASE_NAMES)


@pytest.mark.parametrize('year', [2024, 2025])
def test_actual_saved_oof_is_time_separated_and_hashed(year):
    path = module.OUT / f'oof_{year}.parquet'
    frame = pd.read_parquet(path)
    receipt = json.loads((module.OUT / f'OOF_{year}_RECEIPT.json').read_text(encoding='utf-8'))
    module.verify_oof_clock(frame, f'{year + 1}-01-01')
    assert receipt['oof_sha256'] == module.sha(path)
    assert receipt['cross_section'] == 'full available day before label-side sampling'
    assert receipt['fit_calls'] == 0 and receipt['reads_2026_rows'] == 0
    assert len(frame) <= 90000
    assert set(frame.signal_date.dt.year) == {year}
    assert frame.loc[frame.action.eq(0), module.RANK_COLUMNS + ['target_advantage']].eq(0).all().all()
    assert not frame.duplicated(['signal_date', 'ticker', 'state_id', 'action']).any()
    assert frame.groupby(['signal_date', 'ticker']).size().eq(15).all()
    for dependency, expected in receipt['base_artifact_sha256'].items():
        assert module.sha(dependency) == expected


@pytest.mark.parametrize('stage', ['validation', 'final'])
def test_actual_stacking_has_nonnegative_weights_without_inference_fit(stage, monkeypatch):
    policy = module.EnsemblePolicy('ensemble_stacking', stage)
    monkeypatch.setattr(policy.meta, 'fit', lambda *a, **k: pytest.fail('fit during inference'))
    assert policy.meta.positive and not policy.meta.fit_intercept
    assert np.all(policy.meta.coef_ >= 0)
    rank = np.zeros((2, 5, 6))
    rank[:, 1:, :] = .2
    scores = module.fuse(rank, np.zeros((2, 5)), 'ensemble_stacking', policy.meta)
    assert np.all(scores[:, 0] == 0)
    assert np.all(scores[:, 1:] >= 0)
    receipt = json.loads((module.OUT / f'{stage}_TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
    assert receipt['label_end_max'] < module.vm.STAGES[stage]
    assert receipt['no_in_sample_base_predictions']
    assert receipt['test2026_rows_read'] == 0
