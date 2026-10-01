"""Exact support, readonly/layout, unknown coverage and cache isolation."""
import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits, ThreadpoolController

import cached_risk_inference as cached
import risk_models
from common import ROOT, sha
from data_contract import FEATURES


def bitwise(a, b):
    assert a.dtype == b.dtype and a.shape == b.shape
    assert a.tobytes(order='C') == b.tobytes(order='C')


@pytest.fixture
def signal_inputs():
    return pd.read_parquet(ROOT/'input/pre2026.parquet', columns=list(FEATURES)).head(20)


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.setattr(risk_models, 'threadpool_limits', threadpool_limits)
    return risk_models.RiskBank('validation')


@pytest.mark.parametrize('name', ['lw_hgb_vol', 'lw_mlp_vol'])
def test_same_actual_support_shapes_and_readonly_bitwise(bank, signal_inputs, name):
    x = signal_inputs.to_numpy(float)
    readonly = x.copy()
    readonly.flags.writeable = False
    supports = [signal_inputs, signal_inputs.iloc[[8, 3, 1]],
                np.ascontiguousarray(x), np.asfortranarray(x), readonly,
                signal_inputs.iloc[[0]]]
    baseline = []
    for support in supports:
        try:
            baseline.append(bank.predict_signal_vol(support, name))
        except Exception as error:
            baseline.append(error)
    code_hash = sha(ROOT/'risk_models.py')
    inference = cached.enable(bank)
    for support, expected in zip(supports, baseline):
        if isinstance(expected, Exception):
            with pytest.raises(type(expected), match=str(expected)):
                bank.predict_signal_vol(support, name)
        else:
            first = bank.predict_signal_vol(support, name)
            bitwise(first, expected)
            first[:] = 999
            bitwise(bank.predict_signal_vol(support, name), expected)
    assert sha(ROOT/'risk_models.py') == code_hash
    assert inference.stats()['fit_attempts'] == 0
    assert inference.stats()['thread_limit'] == 2
    assert cached.enable(bank) is inference


def test_unknown_history_covariance_remains_conservative(bank, signal_inputs):
    known = list(bank.lookup)[:2]
    names = known + ['UNKNOWN_NOT_IN_FROZEN_HISTORY']
    frame = signal_inputs.iloc[:3]
    expected, detail = bank.covariance(names, features=frame,
        risk_name='lw_hgb_vol', return_metadata=True)
    cached.enable(bank)
    actual, actual_detail = bank.covariance(names, features=frame,
        risk_name='lw_hgb_vol', return_metadata=True)
    bitwise(actual, expected)
    assert actual_detail == detail
    assert actual[-1, -1] >= risk_models.UNKNOWN_DAILY_VOL ** 2


def test_invalid_inputs_and_non_supervised_passthrough(bank, signal_inputs):
    inference = cached.enable(bank)
    for name in ['diag', 'lw', 'unknown']:
        assert bank.predict_signal_vol(None, name) is None
    for bad in [np.ones((2, 31)), np.ones(32),
                np.full((2, 32), np.nan), np.full((2, 32), np.inf)]:
        with pytest.raises(ValueError, match='INVALID_SUPERVISED'):
            bank.predict_signal_vol(bad, 'lw_mlp_vol')
    with pytest.raises(KeyError):
        bank.predict_signal_vol(signal_inputs.drop(columns=FEATURES[0]), 'lw_hgb_vol')
    assert inference.stats()['original_prediction_calls'] == 0


def test_content_order_layout_and_model_identity_are_cache_keys(bank, signal_inputs):
    inference = cached.enable(bank)
    x = np.ascontiguousarray(signal_inputs.to_numpy(float))
    a = bank.predict_signal_vol(x, 'lw_mlp_vol')
    bitwise(bank.predict_signal_vol(x.copy(), 'lw_mlp_vol'), a)
    assert inference.hits == 1 and inference.misses == 1
    bank.predict_signal_vol(x[::-1], 'lw_mlp_vol')
    changed = x.copy()
    changed[0, 0] = np.nextafter(changed[0, 0], np.inf)
    bank.predict_signal_vol(changed, 'lw_mlp_vol')
    bank.predict_signal_vol(np.asfortranarray(x), 'lw_mlp_vol')
    assert inference.misses == 4


def test_lru_bound_and_no_output_alias(bank, signal_inputs, monkeypatch):
    inference = cached.enable(bank)
    monkeypatch.setattr(inference, 'MAX_ENTRIES', 2)
    frames = [signal_inputs.iloc[[i]] for i in range(3)]
    for f in frames:
        bank.predict_signal_vol(f, 'lw_hgb_vol')
    assert len(inference.cache) == 2
    old_misses = inference.misses
    bank.predict_signal_vol(frames[0], 'lw_hgb_vol')
    assert inference.misses == old_misses + 1


def test_controller_enumerated_once_and_two_thread_context_restored(monkeypatch):
    banks = [risk_models.RiskBank('validation'), risk_models.RiskBank('final')]
    calls = []
    def counted():
        calls.append(True)
        return ThreadpoolController()
    monkeypatch.setattr(cached, '_CONTROLLER', None)
    monkeypatch.setattr(cached, '_CONTROLLER_PID', None)
    monkeypatch.setattr(cached, 'ThreadpoolController', counted)
    inferences = [cached.enable(b) for b in banks]
    assert len(calls) == 1
    controller = inferences[0].controller
    before = controller.info()
    with risk_models.threadpool_limits(limits=2):
        assert all(info['num_threads'] == 2 for info in controller.info())
    assert controller.info() == before
