import numpy as np
import pandas as pd
import pytest

import risk_aux as risk


def test_risk_boundary_excludes_future_price_poison():
    dates = pd.bdate_range('2023-01-02', '2025-12-31')
    frame = pd.DataFrame({'trade_date': dates, 'ticker': 'A',
                          'close': 100*np.exp(np.arange(len(dates))*.0005)})
    before = risk.prepare_risk_returns(frame, '2025-01-01')
    frame.loc[frame.trade_date.ge('2025-01-01'), 'close'] = 1e20
    after = risk.prepare_risk_returns(frame, '2025-01-01')
    pd.testing.assert_frame_equal(before, after)
    assert len(before) == 252 and before.index.max() < pd.Timestamp('2025-01-01')


def test_aux_sampling_is_key_only_deterministic_and_stage_limited():
    frame = pd.DataFrame(np.zeros((8, len(risk.FEATURES))), columns=risk.FEATURES)
    frame['signal_date'] = pd.to_datetime(['2024-12-23', '2024-12-24', '2024-12-26',
                                         '2024-12-27', '2024-12-30', '2024-12-31',
                                         '2025-01-02', '2025-01-03'])
    frame['ticker'] = 'A'
    a = risk.sample_aux_rows(frame, '2025-01-01', max_rows=4)
    frame.loc[frame.signal_date.ge('2025-01-01'), risk.FEATURES] = np.nan
    b = risk.sample_aux_rows(frame.sample(frac=1, random_state=4), '2025-01-01', max_rows=4)
    pd.testing.assert_frame_equal(a, b)
    assert a.signal_date.lt('2025-01-01').all() and len(a) == 4


def test_covariance_psd_and_unknown_names_conservative():
    generator = np.random.default_rng(4)
    returns = pd.DataFrame(generator.normal(0, .02, (252, 6)), columns=list('ABCDEF'))
    returns.loc[:100, 'F'] = np.nan
    with risk.threadpool_limits(limits=1):
        arrays, details = risk.estimate_covariance(returns)
    assert 'F' not in arrays['tickers'] and details['factors'] == 5
    obj = object.__new__(risk.FrozenRisk)
    obj.lookup = {name: index for index, name in enumerate(arrays['tickers'])}
    obj.cov, obj.factor = arrays['covariance'], arrays['factor_covariance']
    for factor in [False, True]:
        cov = obj.covariance_for(['B', 'UNKNOWN', 'A'], factor=factor)
        np.linalg.cholesky(cov)
        assert cov[1, 1] == .08**2 and cov[0, 1] == cov[1, 2] == 0
    with pytest.raises(ValueError, match='DUPLICATE'):
        obj.covariance_for(['A', 'A'])


def test_loaded_stage_artifacts_have_correct_cutoff():
    if not (risk.RISK_OUT/'final/TRAIN_RECEIPT.json').exists():
        pytest.skip('artifact integration runs after the scheduled fit')
    for stage, cutoff in risk.STAGES.items():
        obj = risk.FrozenRisk(stage)
        assert obj.stage == stage
        model = risk._load_aux(stage)
        assert model['cutoff_exclusive'] == cutoff
        source = pd.read_parquet(risk.SOURCE, columns=['signal_date', 'ticker', *risk.FEATURES])
        sample = source.loc[source.signal_date.lt(cutoff)].head(10)
        output = risk.aux_predict(sample, stage)
        assert len(output) == len(sample)
        assert set(output.state_cluster) <= set(range(5))
        assert np.isfinite(output.anomaly_score).all()
        assert not {'target_weight', 'buy', 'sell', 'signal'} & set(output)
