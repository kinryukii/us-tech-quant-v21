import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
import pytest

from scripts.storage.refresh_free_market import normalize_chart, write_versioned_parquet, sha256
from scripts.storage import refresh_free_market as market


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


def test_extended_events_keep_raw_splits_but_no_price_after_end(tmp_path, monkeypatch):
    data = payload()
    result = data['chart']['result'][0]
    after_end = int(pd.Timestamp('2026-09-11T13:30:00Z').timestamp())
    result['timestamp'].append(after_end)
    for values in result['indicators']['quote'][0].values():
        values.append(None)
    result['indicators']['adjclose'][0]['adjclose'].append(None)
    result['events']['splits'][str(after_end)] = {'date': after_end, 'numerator': 3, 'denominator': 1}
    request = Mock(return_value=SimpleNamespace(status_code=200, content=json.dumps(data).encode(),
        url='https://query1.finance.yahoo.com/v8/finance/chart/ABC', json=lambda: data))
    monkeypatch.setattr(market.requests, 'get', request)
    for part in ('raw', 'checkpoints'):
        (tmp_path / part).mkdir()
    receipt = market.acquire_one('ABC', 'ABC', '2026-09-01', '2026-09-10', tmp_path,
        tmp_path / 'data', Mock(), events_through='2026-09-11')
    assert receipt['status'] == 'SUCCESS' and receipt['rejected_row_count'] == 0
    assert receipt['max_date'] == '2026-09-10'
    assert receipt['contract']['end'] == '2026-09-10'
    assert receipt['contract']['events_through'] == '2026-09-11'
    params = request.call_args.kwargs['params']
    assert 'splits' in params['events'].split(',')
    assert params['period2'] == int(pd.Timestamp('2026-09-12T00:00:00', tz='America/New_York').timestamp())
    raw = next(item for item in receipt['files'] if item['role'] == 'RAW_HTTP_RESPONSE')
    assert str(after_end) in json.loads(Path(raw['path']).read_text())['chart']['result'][0]['events']['splits']
    output = next(item for item in receipt['files'] if item['role'] == 'NORMALIZED_DAILY')
    assert set(pd.read_parquet(output['path']).date) == {'2026-09-09', '2026-09-10'}


def test_default_events_contract_and_checkpoint_remain_compatible(tmp_path, monkeypatch):
    data = payload()
    request = Mock(return_value=SimpleNamespace(status_code=200, content=json.dumps(data).encode(),
        url='https://query1.finance.yahoo.com/v8/finance/chart/ABC', json=lambda: data))
    monkeypatch.setattr(market.requests, 'get', request)
    for part in ('raw', 'checkpoints'):
        (tmp_path / part).mkdir()
    args = ('ABC', 'ABC', '2026-09-01', '2026-09-11', tmp_path, tmp_path/'data', Mock())
    receipt = market.acquire_one(*args)
    assert 'events_through' not in receipt['contract']
    assert request.call_args.kwargs['params']['period2'] == int(pd.Timestamp('2026-09-12T00:00:00Z').timestamp())
    assert market.acquire_one(*args) == receipt
    request.assert_called_once()


def test_event_extension_rejects_invalid_bounds_and_keeps_price_end_guard(tmp_path):
    with pytest.raises(ValueError, match='events_through'):
        market.event_request_end('2026-09-10', '2026-09-09')
    future = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
    with pytest.raises(ValueError, match='events_through'):
        market.event_request_end('2026-09-10', future)
    with pytest.raises(ValueError, match='completed New York'):
        market.main(['--start', future, '--end', future, '--events-through', future,
                     '--tickers', 'ABC', '--work-root', str(tmp_path)])


@pytest.mark.parametrize('utc_stamp,accepted', [('2026-09-22T21:00:00+00:00', True),
                                              ('2026-09-22T19:59:59+00:00', False)])
def test_cli_uses_new_york_close_instead_of_utc_date(tmp_path, monkeypatch, utc_stamp, accepted):
    fixed = datetime.fromisoformat(utc_stamp)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(market, 'datetime', Clock)
    monkeypatch.setattr(market, 'resolve', lambda: SimpleNamespace(cache_root=tmp_path))
    args = ['--start', '2026-09-21', '--end', '2026-09-22', '--events-through', '2026-09-22',
            '--tickers', 'ABC', '--work-root', str(tmp_path)]
    if accepted:
        assert market.main(args) == 0
    else:
        with pytest.raises(ValueError, match='completed New York'):
            market.main(args)
