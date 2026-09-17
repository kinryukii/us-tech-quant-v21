import copy
import pandas as pd
import pytest

from scripts.storage.refresh_free_market import normalize_chart, write_versioned_parquet, sha256


def payload():
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': 'ABC', 'currency': 'USD', 'exchangeTimezoneName': 'America/New_York', 'instrumentType': 'EQUITY'},
        'timestamp': [1788960600, 1789047000],
        'indicators': {'quote': [{'open': [10, 11], 'high': [12, 13], 'low': [9, 10], 'close': [11, 12], 'volume': [100, 200]}],
                       'adjclose': [{'adjclose': [5.5, 6]}]},
        'events': {'splits': {'1788960600': {'date': 1788960600, 'numerator': 2, 'denominator': 1, 'splitRatio': '2:1'}}}
    }]}}


def norm(data):
    return normalize_chart(data, 'ABC', 'ABC', '2026-09-01', '2026-09-11', '/raw.json', '2026-09-12T18:00:00Z')


def test_basis_close_and_actions_are_not_blended():
    bars, actions, meta, rejected = norm(payload())
    assert list(bars.close) == [11, 12]
    assert list(bars.adjusted_close) == [5.5, 6]
    assert set(bars.adjustment) == {'split_adjusted'}
    assert len(actions) == 1 and actions[0]['event_type'] == 'splits'
    assert not rejected
    assert bars.source_timestamp_utc.dt.tz is not None
    assert set(bars.observed_at) == {'2026-09-12T18:00:00Z'}


@pytest.mark.parametrize('field,value,error', [('symbol', 'XYZ', 'SYMBOL'), ('currency', 'CAD', 'CURRENCY'),
    ('exchangeTimezoneName', 'Europe/London', 'TIMEZONE'), ('instrumentType', 'CRYPTOCURRENCY', 'INSTRUMENT')])
def test_identity_and_market_mismatch_rejected(field, value, error):
    data = payload(); data['chart']['result'][0]['meta'][field] = value
    with pytest.raises(ValueError, match=error): norm(data)


def test_null_bar_explicitly_rejected_without_fill():
    data=payload(); data['chart']['result'][0]['indicators']['quote'][0]['close'][0]=None
    bars, _, _, rejected=norm(data)
    assert len(bars)==1 and bars.close.iloc[0]==12
    assert len(rejected)==1 and rejected[0]['reason']=='NULL_OR_INVALID_OHLCV'


def test_duplicate_day_and_array_mismatch():
    data=payload(); data['chart']['result'][0]['timestamp'][1]=data['chart']['result'][0]['timestamp'][0]
    with pytest.raises(ValueError, match='DUPLICATE'): norm(data)
    data=payload(); data['chart']['result'][0]['indicators']['quote'][0]['volume']=[1]
    with pytest.raises(ValueError, match='ARRAY_LENGTH'): norm(data)


def test_new_york_day_is_not_utc_day():
    data=payload(); data['chart']['result'][0]['timestamp']=[int(pd.Timestamp('2026-09-10T00:30:00Z').timestamp()),int(pd.Timestamp('2026-09-11T00:30:00Z').timestamp())]
    bars, *_=norm(data)
    assert list(bars.date)==['2026-09-09','2026-09-10']


def test_no_result_and_invalid_adjusted_close_rejected():
    with pytest.raises(ValueError, match='PROVIDER_ERROR'): norm({'chart': {'error': {'code':'Not Found'}}})
    data=payload(); data['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'][0]=-1
    with pytest.raises(ValueError, match='ADJUSTED_CLOSE'): norm(data)


def test_new_retrieval_never_overwrites_prior_version(tmp_path):
    frame, *_ = norm(payload())
    first = write_versioned_parquet(frame, tmp_path, 'daily')
    before = sha256(first)
    assert write_versioned_parquet(frame, tmp_path, 'daily') == first
    frame['observed_at'] = '2026-09-13T18:00:00Z'
    second = write_versioned_parquet(frame, tmp_path, 'daily')
    assert first != second and sha256(first) == before


def test_numeric_strings_materialize_as_numeric():
    data = payload()
    for field, vals in data['chart']['result'][0]['indicators']['quote'][0].items():
        data['chart']['result'][0]['indicators']['quote'][0][field] = list(map(str, vals))
    data['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'] = ['5.5', '6']
    bars, *_ = norm(data)
    assert all(pd.api.types.is_numeric_dtype(bars[name]) for name in ['open','high','low','close','volume','adjusted_close'])
