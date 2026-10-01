"""Temporal and immutable-inference checks for freshly trained risk diagnostics."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('new_risk_aux_under_test', HERE / 'risk_aux.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_future_prices_cannot_change_validation_risk_window():
    dates = pd.bdate_range('2023-10-01', '2025-02-01')
    frame = pd.DataFrame([(d, f'S{i}', 50 + k * .01 + i) for k, d in enumerate(dates)
                          for i in range(6)], columns=['trade_date', 'ticker', 'close'])
    before = module.risk_returns(frame, '2025-01-01')
    frame.loc[frame.trade_date.ge('2025-01-01'), 'close'] *= 1000
    after = module.risk_returns(frame, '2025-01-01')
    pd.testing.assert_frame_equal(before, after)
    assert len(before) == 252
    assert before.index.max() < pd.Timestamp('2025-01-01')


def test_aux_sampling_uses_keys_and_stage_only():
    dates = pd.bdate_range('2024-01-01', '2025-01-10')
    frame = pd.DataFrame([(d, f'S{i}') for d in dates for i in range(8)], columns=['signal_date', 'ticker'])
    for feature in module.FEATURES:
        frame[feature] = 0.
    before = module.sample_auxiliary(frame, '2025-01-01', max_rows=100)
    frame['future_target'] = np.arange(len(frame))
    after = module.sample_auxiliary(frame.sample(frac=1, random_state=9), '2025-01-01', max_rows=100)
    pd.testing.assert_frame_equal(before, after)
    assert before.signal_date.max() < pd.Timestamp('2025-01-01')


@pytest.mark.parametrize('stage', ['validation', 'final'])
def test_actual_frozen_models_and_inference(stage, monkeypatch):
    risk = module.FrozenRisk(stage)
    names = list(risk.lookup)[:7] + ['UNKNOWN_SECURITY']
    for factor in [False, True]:
        covariance = risk.covariance_for(names, factor)
        assert np.allclose(covariance, covariance.T)
        assert np.linalg.eigvalsh(covariance).min() > 0
        assert covariance[-1, -1] == module.UNKNOWN_VOL**2
        assert np.count_nonzero(covariance[-1, :-1]) == 0
    assert risk.receipt['return_days'] == 252
    assert risk.receipt['fit_2026_rows'] == 0
    with pytest.raises(ValueError, match='Duplicate'):
        risk.covariance_for(['X', 'X'])
    aux = module.FrozenAuxiliary(stage)
    for model in aux.models.values():
        if hasattr(model, 'fit'):
            monkeypatch.setattr(model, 'fit', lambda *a, **k: pytest.fail('inference attempted fit'))
    frame = pd.read_parquet(module.PRE, columns=module.FEATURES).iloc[:11]
    before_hash = module.sha(module.AUX_OUT / stage / 'frozen_auxiliary.joblib')
    result = aux.transform(frame)
    pd.testing.assert_frame_equal(result, aux.predict(frame.to_numpy()))
    assert result.cluster.between(0, 4).all()
    assert np.isfinite(result.anomaly_score).all()
    assert before_hash == module.sha(module.AUX_OUT / stage / 'frozen_auxiliary.joblib')
    assert aux.receipt['train_rows'] <= 20000
    assert aux.receipt['fit_2026_rows'] == 0
    assert aux.receipt['train_last'] < module.STAGES[stage]


def test_stage_parameters_reject_cross_stage_alias():
    with pytest.raises(ValueError, match='Unknown stage'):
        module.FrozenRisk('2026')
