"""Invented public observations and fake transport only; no source acquisition.

Import the installed task module so CLI wiring cannot pass by testing a fragment.
Temporary files belong to the test runner's approved external temporary root.
"""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.research.a2.options import public_history as public
from scripts.research.a2.options.contracts import Invalid


def test_keyset_rowlimit_needs_pinned_count_and_resume_skips_completed(tmp_path):
    session = bare_session(tmp_path)
    keys = [dict(request_key_id='one',ticker='TEST',date='2025-03-03'),
            dict(request_key_id='empty',ticker='TEST',date='2025-03-04')]
    answers = [dict(query_execution_status='Success', rows=[dict(date='2025-03-03',act_symbol='TEST',row_count=3)]),
        dict(query_execution_status='RowLimit', rows=[invented_row() | {'strike':'100'}, invented_row() | {'strike':'101'}]),
        dict(query_execution_status='Success', rows=[invented_row() | {'strike':'102'}])]
    queries = []
    def sql(query):
        queries.append(query)
        session.manifest['requests'].append(dict(source='DOLT',status='COMPLETE',params={'q':query},file='invented-'+str(len(queries)),
            sha256='invented',requested_at_utc='2026-09-15T00:00:00Z'))
        return answers.pop(0)
    session.sql = sql
    public.acquire_dolt(session, {'request_keys':keys})
    assert session.manifest['dolt_keys']['one']['status'] == 'COMPLETE'
    assert session.manifest['dolt_keys']['one']['downloaded_rows'] == 3
    assert session.manifest['dolt_keys']['empty']['status'] == 'COMPLETE_EMPTY'
    assert '(date, act_symbol, expiration, strike, call_put) >' in queries[-1]
    assert "'2025-04-17', 101, 'Call'" in queries[-1]
    public.acquire_dolt(session, {'request_keys':keys})
    assert len(queries) == 3


def test_download_budget_preserves_counted_unread_as_unknown(tmp_path):
    session = bare_session(tmp_path)
    session.manifest['requests'] = [dict(source='DOLT') for _ in range(360)]
    session.manifest['dolt_keys'] = {'one':dict(ticker='TEST',date='2025-03-03',status='COUNTED_NOT_DOWNLOADED',
        expected_rows=5,downloaded_rows=0,pages=[])}
    public.acquire_dolt(session, {'request_keys':[dict(request_key_id='one',ticker='TEST',date='2025-03-03')]})
    assert session.manifest['dolt_keys']['one']['status'] == 'BUDGET_NOT_DOWNLOADED'
    assert session.manifest['dolt_keys']['one']['downloaded_rows'] == 0
    assert session.manifest['source_status']['DOLT']['complete_empty'] == 0


def test_writer_deduplicates_exact_rows_retains_same_key_conflicts_and_reread(tmp_path, monkeypatch):
    session = bare_session(tmp_path)
    batches = [('DOLT','invented-1','2026-09-15T00:00:00Z',0, frame_of(invented_row(), invented_row())),
        ('DOLT','invented-2','2026-09-15T00:00:00Z',0, frame_of(invented_row(bid='0.80')))]
    monkeypatch.setattr(public, '_raw_batches', lambda _: iter(batches))
    public.normalize_cache(session)
    state = session.manifest['normalization']
    assert (state['raw_rows'],state['normalized_rows'],state['exact_duplicate_rows'],state['conflict_keys']) == (3,2,1,1)
    frames = [pd.read_parquet(session.cache / part['file']) for part in state['parts']]
    assert pd.concat(frames).observation_bid.tolist() == [1.0,0.8]
    assert pd.concat(frames).observation_key.nunique() == 1
    session.offline = True
    public.normalize_cache(session)
    assert len(state['parts']) == 2


def test_new_raw_inventory_extends_existing_normalization_without_rewriting_parts(tmp_path, monkeypatch):
    session = bare_session(tmp_path)
    batches = [('DOLT','invented-1','2026-09-15T00:00:00Z',0,frame_of(invented_row()))]
    session.manifest['dolt_keys'] = {'one':{'pages':[dict(file='invented-1',sha256='1')]}}
    monkeypatch.setattr(public, '_raw_batches', lambda _: iter(batches))
    public.normalize_cache(session)
    first = session.manifest['normalization']['parts'][0].copy()
    batches.append(('DOLT','invented-2','2026-09-15T00:00:00Z',0,frame_of(invented_row(strike='101'))))
    session.manifest['dolt_keys']['one']['pages'].append(dict(file='invented-2',sha256='2'))
    public.normalize_cache(session)
    assert session.manifest['normalization']['normalized_rows'] == 2
    assert session.manifest['normalization']['parts'][0] == first


def test_public_source_lock_rejects_changed_commit_or_mixed_count_version(tmp_path):
    session = bare_session(tmp_path)
    for index, repo in enumerate(public.REPOS):
        path = session.cache / ('tree-'+str(index))
        path.write_text('{"tree":[]}',encoding='utf-8')
        session.manifest['sources'][repo] = dict(commit=str(index)*40,tree_file=path.name)
    session.manifest['etf_file_binding'] = dict(path='spy/options_2024.parquet',git_blob_sha='1'*40)
    payload = public.public_source_payload(session)
    session.manifest['public_source_lock'] = dict(sha256=public.digest(json.dumps(payload,sort_keys=True).encode()))
    public.validate_public_sources(session)
    session.manifest['sources']['DOLT']['commit'] = 'b'*32
    with pytest.raises(Invalid,match='PUBLIC_SOURCE_VERSION_CHANGED'):
        public.validate_public_sources(session)
    session.manifest['sources']['DOLT']['commit'] = 'a'*32
    session.manifest['requests'].append(dict(params={'q':"SELECT date FROM option_chain AS OF '"+'b'*32+"' LIMIT 0;"}))
    with pytest.raises(Invalid,match='PUBLIC_COUNT_PAGE_VERSION_MIX'):
        public.validate_public_sources(session)


def test_only_named_readtimeout_gets_one_explicit_counted_recovery(tmp_path, monkeypatch):
    session = bare_session(tmp_path)
    params = {'q':'SHOW TABLES;'}
    identity = dict(source='DOLT',method='GET',url=public.DOLT,params=params,headers={})
    key = public.digest(json.dumps(identity,sort_keys=True).encode())
    session.manifest['requests'] = [dict(identity,request_id=key,status='FAILED',exception_type='ReadTimeout')]
    session.manifest['bounded_latency_repair'] = dict(one_retry_request_ids=[key],read_timeout_seconds=60)
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs['timeout'])
        raise public.requests.exceptions.ReadTimeout()
    session.http = SimpleNamespace(request=fail)
    monkeypatch.setattr(public.time,'sleep',lambda _:None)
    with pytest.raises(Invalid,match='PUBLIC_NETWORK_OR_IO_ERROR'):
        session.get('DOLT',public.DOLT,params=params)
    assert calls == [(10,60)] and len(session.manifest['requests']) == 2
    assert session.manifest['requests'][-1]['retry'] == 1
    with pytest.raises(Invalid,match='PUBLIC_UNCERTAIN_ATTEMPT_NO_RETRY'):
        session.get('DOLT',public.DOLT,params=params)
    assert len(calls) == 1


def test_one_page_timeout_is_preserved_while_other_fixed_scope_completes_and_no_retry(tmp_path):
    session = bare_session(tmp_path)
    keys = [dict(request_key_id='failed',ticker='TEST',date='2025-03-03'),
            dict(request_key_id='next',ticker='TEST',date='2025-03-04')]
    session.manifest['dolt_keys'] = {k['request_key_id']:dict(ticker=k['ticker'],date=k['date'],
        status='COUNTED_NOT_DOWNLOADED',pages=[],downloaded_rows=0,expected_rows=1) for k in keys}
    queries = []
    def sql(query):
        queries.append(query)
        record = dict(source='DOLT',params={'q':query},request_id=str(len(queries)),status='COMPLETE',
                      file='invented-next',sha256='invented',requested_at_utc='2026-09-15T00:00:00Z')
        session.manifest['requests'].append(record)
        if "date = '2025-03-03'" in query:
            record.update(status='FAILED',exception_type='ReadTimeout')
            raise Invalid('PUBLIC_NETWORK_OR_IO_ERROR')
        return dict(query_execution_status='Success',rows=[invented_row(date='2025-03-04')])
    session.sql = sql
    public.acquire_dolt(session, {'request_keys':keys})
    assert session.manifest['dolt_keys']['failed']['status'] == 'PAGE_ERROR'
    assert session.manifest['dolt_keys']['next']['status'] == 'COMPLETE'
    assert len(queries) == 2
    public.acquire_dolt(session, {'request_keys':keys})
    assert len(queries) == 2


def test_count_permission_denial_stops_known_page_dependency(tmp_path):
    session = bare_session(tmp_path)
    keys = [dict(request_key_id='unknown',ticker='TEST',date='2025-03-03'),
            dict(request_key_id='known',ticker='TEST',date='2025-03-04')]
    session.manifest['dolt_keys'] = {'known':dict(ticker='TEST',date='2025-03-04',
        status='COUNTED_NOT_DOWNLOADED',pages=[],downloaded_rows=0,expected_rows=1)}
    calls = []
    def sql(query):
        calls.append(query)
        session.manifest['requests'].append(dict(source='DOLT',status='COMPLETE',http_status=403,params={'q':query}))
        raise Invalid('DOLT_HTTP_403')
    session.sql = sql
    public.acquire_dolt(session,{'request_keys':keys})
    assert len(calls) == 1 and 'COUNT(*)' in calls[0]
    assert session.manifest['dolt_keys']['known']['downloaded_rows'] == 0
    assert session.manifest['source_status']['DOLT']['dependency_stop_reason'] == 'DOLT_HTTP_403'


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('These tests must not request a real public source')
    monkeypatch.setattr(public.requests.Session, 'request', forbidden)


def invented_row(**changes):
    return dict(date='2025-03-03', act_symbol='TEST', expiration='2025-04-17',
                strike='100', call_put='Call', bid='1.00', ask='1.20') | changes


def frame_of(*rows):
    # Explicit object dtype preserves the distinction between missing and NaN.
    return pd.DataFrame(list(rows), dtype=object)


def normalize(frame, source='INVENTED_SOURCE', file_id='invented-file'):
    return public.normalize_observations(frame, source, file_id, '2026-09-15T01:00:00Z')


def reasons(row):
    return set(json.loads(row.quality_reasons))


def bare_session(tmp_path, *, offline=False):
    """Bypass constructor: no original manifest or real source is opened."""
    session = object.__new__(public.PublicSession)
    session.output = tmp_path
    session.cache = tmp_path / 'invented-cache'
    session.cache.mkdir(exist_ok=True)
    session.path = tmp_path / 'invented-manifest.json'
    session.offline = offline
    session.manifest = dict(requests=[], source_status={}, acquisition_policy={'count_key_batch':24},
        sources={'DOLT': {'commit': 'a' * 32}}, inherited_massive_requests=12,
        acquisition_deadline_epoch=10**20, cache_limit_bytes=1024 * 1024)
    session.http = SimpleNamespace(request=lambda *a, **k: pytest.fail('Unexpected HTTP'))
    return session


@pytest.mark.parametrize('bad_date', [None, '', 'not-a-date', '2022-12-30', '2026-01-02'])
def test_invalid_observation_date_rejects_whole_batch_not_a_cutoff_filter(bad_date):
    frame = frame_of(invented_row(), invented_row() | {'date': bad_date})
    before = frame.copy(deep=True)
    with pytest.raises(Invalid, match='PUBLIC_OBSERVATION_DATE'):
        normalize(frame)
    pd.testing.assert_frame_equal(frame, before)


def test_future_expiry_and_late_download_are_not_future_economic_observations():
    result = normalize(frame_of(invented_row() | {'expiration': '2026-01-16'}))
    row = result.iloc[0]
    assert row.observation_date == '2025-03-03'
    assert row.normalized_expiration == '2026-01-16'
    assert row.downloaded_at == '2026-09-15T01:00:00Z'
    assert reasons(row) == set()


def test_null_zero_nan_and_unknown_vol_have_distinct_meanings():
    result = normalize(frame_of(
        invented_row() | {'bid': None, 'vol': None},
        invented_row() | {'bid': 0, 'vol': 0},
        invented_row() | {'bid': float('nan'), 'vol': '0.42'},
    ))
    missing, zero, nonfinite = [result.iloc[i] for i in range(3)]
    assert 'MISSING_BID' in reasons(missing) and 'ZERO_BID' not in reasons(missing)
    assert zero.observation_bid == 0 and 'ZERO_BID' in reasons(zero)
    assert 'NON_FINITE_BID' in reasons(nonfinite) and 'MISSING_BID' not in reasons(nonfinite)
    assert result.vol_raw.tolist() == [None, 0, '0.42']
    assert result.vol_semantics.eq('UNKNOWN').all()
    assert result.observation_volume.isna().all()
    assert result.observation_implied_volatility.isna().all()


def test_quality_failures_remain_rows_with_original_fields_and_index():
    frame = frame_of(
        invented_row() | {'date': '2025-03-02', 'expiration': '2025-03-01',
                         'bid': 2, 'ask': 1, 'bid_size': -1, 'volume': -2},
        invented_row() | {'expiration': 'bad-expiry', 'strike': None,
                         'call_put': 'UNKNOWN', 'bid': -1},
    )
    frame.index = [7, 7]
    result = normalize(frame)
    pd.testing.assert_frame_equal(result[frame.columns], frame)
    assert len(result) == 2 and result.index.tolist() == [7, 7]
    assert {'NON_TRADING_DAY', 'EXPIRATION_BEFORE_OBSERVATION_DATE',
            'BID_GREATER_THAN_ASK', 'NEGATIVE_BID_SIZE', 'NEGATIVE_VOLUME'} <= reasons(result.iloc[0])
    assert {'INVALID_EXPIRATION', 'MISSING_STRIKE', 'UNKNOWN_RIGHT',
            'NEGATIVE_BID', 'OBSERVATION_KEY_NOT_IDENTIFIABLE'} <= reasons(result.iloc[1])
    assert pd.isna(result.iloc[1].observation_key)
    assert result.quality_status.eq('OBSERVATION_HAS_QUALITY_FLAGS').all()


def test_observation_identity_is_exact_source_scoped_and_not_price_or_file_selected():
    frame = frame_of(invented_row() | {'strike': Decimal('100.00000000000000000001')},
                     invented_row() | {'strike': Decimal('100.00000000000000000002')})
    result = normalize(frame)
    assert result.normalized_strike.tolist() == ['100.00000000000000000001', '100.00000000000000000002']
    assert result.observation_key.nunique() == 2
    assert result.observation_key.tolist() == normalize(frame, file_id='second-file').observation_key.tolist()
    other_source = normalize(frame, source='OTHER_INVENTED_SOURCE')
    assert not set(result.observation_key) & set(other_source.observation_key)
    changed = frame.assign(bid='900', ask='1000')
    assert result.observation_key.tolist() == normalize(changed).observation_key.tolist()
    equivalent = normalize(frame_of(invented_row() | {'strike': '100.00'},
                                    invented_row() | {'strike': '1E2'}))
    assert equivalent.normalized_strike.eq('100').all()
    assert equivalent.observation_key.nunique() == 1


def test_daily_snapshot_greeks_do_not_become_executable_historical_quotes(monkeypatch):
    from scripts.research.a2.options import expression
    monkeypatch.setattr(expression, 'evaluate', lambda *a, **k: pytest.fail('Daily observations reached evaluate'))
    row = normalize(frame_of(invented_row() | {'delta': '.5', 'gamma': '.02', 'vol': '.4'})).iloc[0]
    assert row.snapshot_delta == .5 and row.snapshot_gamma == .02
    assert row.delta_qualification == 'NOT_QUALIFIED_HISTORICAL_DECISION_DELTA'
    assert row.greeks_semantics == 'SNAPSHOT_DERIVED_NOT_QUALIFIED'
    assert row.observation_semantics == 'PUBLIC_DAILY_OBSERVATION_NOT_EXECUTABLE_QUOTE'
    for field in ('quote_timestamp', 'available_at', 'historical_available_at',
                  'multiplier', 'deliverable', 'underlying_uid'):
        assert row[field] is None
    assert row.size_unit == row.historical_uid_status == 'UNKNOWN'


def test_reserved_columns_cannot_silently_replace_original_observations():
    with pytest.raises(Invalid, match='PUBLIC_RESERVED_NORMALIZED_COLUMN_COLLISION'):
        normalize(frame_of(invented_row() | {'observation_bid': 99}))
    frame = frame_of(invented_row())
    frame['BID'] = 99
    with pytest.raises(Invalid, match='PUBLIC_CASE_AMBIGUOUS_INPUT_COLUMNS'):
        normalize(frame)


@pytest.mark.parametrize('raw,reason', [
    (b'<html>an error page</html>', 'PUBLIC_NOT_PARQUET_MAGIC'),
    (b'version https://git-lfs.github.com/spec/v1\noid sha256:invented\n', 'PUBLIC_LFS_POINTER'),
    (b'PAR1unfinished-footer', 'PUBLIC_TRUNCATED_PARQUET'),
    (b'PAR1', 'PUBLIC_'),
])
def test_non_parquet_and_truncated_files_are_rejected(tmp_path, raw, reason):
    path = tmp_path / 'invented.parquet'
    path.write_bytes(raw)
    with pytest.raises(Invalid, match=reason):
        public.inspect_parquet(path)


def write_invented_parquet(tmp_path, dates, *, statistics=True):
    path = tmp_path / 'invented-dates.parquet'
    table = pa.table({'date': pa.array(dates, type=pa.date32()),
                      'expiration': pa.array([date(2026, 1, 16)] * len(dates), type=pa.date32()),
                      'bid': [1.] * len(dates)})
    pq.write_table(table, path, row_group_size=1, write_statistics=statistics)
    return path


def test_parquet_footer_proves_pre2026_dates_without_reading_record_batches(tmp_path, monkeypatch):
    path = write_invented_parquet(tmp_path, [date(2024, 1, 2), date(2024, 12, 31)])
    real_constructor = public.pq.ParquetFile
    class FooterOnly:
        def __init__(self, *args, **kwargs):
            self.delegate = real_constructor(*args, **kwargs)
        def __getattr__(self, name):
            if name in {'read', 'read_row_group', 'read_row_groups', 'iter_batches'}:
                pytest.fail('Footer inspection attempted to read economic rows')
            return getattr(self.delegate, name)
    monkeypatch.setattr(public.pq, 'ParquetFile', FooterOnly)
    _, footer = public.inspect_parquet(path, year=2024)
    assert footer['rows'] == 2 and len(footer['row_groups']) == 2
    assert footer['row_groups'][0]['date_min'] == '2024-01-02'
    assert footer['row_groups'][1]['date_max'] == '2024-12-31'
    with pytest.raises(Invalid, match='PUBLIC_ANNUAL_FILE_SCOPE'):
        public.inspect_parquet(path, year=2025)


@pytest.mark.parametrize('bad_date', [date(2022, 12, 30), date(2026, 1, 2)])
def test_parquet_mixed_date_scope_is_rejected_at_footer(tmp_path, bad_date):
    path = write_invented_parquet(tmp_path, [date(2025, 3, 3), bad_date])
    with pytest.raises(Invalid, match='PUBLIC_PARQUET_DATE_SCOPE'):
        public.inspect_parquet(path)


@pytest.mark.parametrize('dates,statistics', [([date(2025, 3, 3)], False), ([None], True)])
def test_parquet_unknown_or_null_date_statistics_do_not_certify_scope(tmp_path, dates, statistics):
    path = write_invented_parquet(tmp_path, dates, statistics=statistics)
    with pytest.raises(Invalid, match='PUBLIC_PARQUET_DATE_STATS_UNKNOWN'):
        public.inspect_parquet(path)


def test_count_and_page_queries_use_frozen_dates_source_commit_and_primary_key(tmp_path):
    session = bare_session(tmp_path)
    key = {'date': '2025-03-03', 'ticker': 'TEST'}
    count = public.count_query(session, [key])
    after = ['2025-03-03', 'TEST', '2026-01-16', '100.00000000000000000001', 'C']
    page = public.page_query(session, key, after)
    for query in (count, page):
        assert "AS OF '" + 'a' * 32 + "'" in query
        assert "date >= '2023-01-01'" in query and "date < '2026-01-01'" in query
        assert "date = '2025-03-03'" in query and "act_symbol = 'TEST'" in query
        where = query.split(' WHERE ', 1)[1].lower()
        assert not any(field in where for field in (' bid', ' ask', ' vol', ' delta', ' gamma'))
    assert 'COUNT(*) AS row_count' in count
    assert '100.00000000000000000001' in page
    assert 'ORDER BY date, act_symbol, expiration, strike, call_put LIMIT 500;' in page
    assert public.page_query(session, key | {'bid': 999, 'ask': 1000}, after) == page
    assert public.count_query(session, [key | {'future_return': -99}]) == count


@pytest.mark.parametrize('day', ['2022-12-30', '2026-01-02'])
def test_count_and_page_scopes_reject_dates_outside_authorized_interval(tmp_path, day):
    session = bare_session(tmp_path)
    key = {'date': day, 'ticker': 'TEST'}
    with pytest.raises(Invalid, match='PUBLIC_'):
        public.count_query(session, [key])
    with pytest.raises(Invalid, match='PUBLIC_'):
        public.page_query(session, key)


def test_count_query_is_bounded_and_keyset_strike_is_finite(tmp_path):
    session = bare_session(tmp_path)
    key = {'date': '2025-03-03', 'ticker': 'TEST'}
    for keys in ([], [key] * 25):
        with pytest.raises(Invalid, match='PUBLIC_COUNT_KEYS_BOUNDARY'):
            public.count_query(session, keys)
    with pytest.raises(Invalid, match='PUBLIC_KEYSET_STRIKE'):
        public.page_query(session, key, ['2025-03-03', 'TEST', '2026-01-16', 'NaN', 'C'])


@pytest.mark.parametrize('status', ['Error', 'RowLimit'])
def test_sql_retains_application_error_and_row_limit_body(tmp_path, status):
    session = bare_session(tmp_path)
    body = {'query_execution_status': status, 'rows': [], 'message': 'invented diagnostic'}
    path = tmp_path / 'invented-sql-response.json'
    path.write_text(json.dumps(body), encoding='utf-8')
    seen = []
    def fake_get(source, url, **kwargs):
        seen.append((source, url, kwargs['params']))
        return {'http_status': 200}, path
    session.get = fake_get
    query = public.count_query(session, [{'date': '2025-03-03', 'ticker': 'TEST'}])
    assert session.sql(query) == body
    assert seen == [('DOLT', public.DOLT, {'q': query})]


def test_sql_rejects_unsafe_read_scope_before_fake_transport(tmp_path):
    session = bare_session(tmp_path)
    session.get = lambda *a, **k: pytest.fail('Unbounded query reached transport')
    with pytest.raises(Invalid, match='PUBLIC_SQL_READ_ONLY'):
        session.sql('DELETE FROM option_chain;')
    with pytest.raises(Invalid, match='PUBLIC_SQL_OBSERVATION_CUTOFF'):
        session.sql('SELECT * FROM option_chain LIMIT 10;')


def test_completed_cache_resume_does_not_make_another_network_request(tmp_path, monkeypatch):
    session = bare_session(tmp_path)
    calls = []
    payload = b'{"invented": true}'
    class FakeResponse:
        status_code = 200
        headers = {'Content-Length': str(len(payload)), 'Content-Type': 'application/json'}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def iter_content(self, chunk_size):
            yield payload
    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse()
    session.http = SimpleNamespace(request=fake_request)
    monkeypatch.setattr(public.time, 'sleep', lambda _: None)
    first, path = session.get('DOLT', public.DOLT, params={'q': 'SHOW TABLES;'}, maximum=4096)
    assert first['status'] == 'COMPLETE' and path.read_bytes() == payload
    resumed = bare_session(tmp_path, offline=True)
    resumed.manifest = json.loads(session.path.read_bytes())
    second, again = resumed.get('DOLT', public.DOLT, params={'q': 'SHOW TABLES;'}, maximum=4096)
    assert second == first and again == path and len(calls) == 1
    assert len(resumed.manifest['requests']) == 1
    path.write_bytes(b'changed invented cache')
    with pytest.raises(Invalid, match='PUBLIC_CACHE_CHANGED'):
        resumed.get('DOLT', public.DOLT, params={'q': 'SHOW TABLES;'})
    assert len(calls) == 1


def test_offline_missing_cache_and_uncertain_attempt_do_not_retry(tmp_path):
    session = bare_session(tmp_path, offline=True)
    params = {'q': 'SHOW TABLES;'}
    with pytest.raises(Invalid, match='OFFLINE_CACHE_MISS'):
        session.get('DOLT', public.DOLT, params=params)
    identity = dict(source='DOLT', method='GET', url=public.DOLT, params=params, headers={})
    key = public.digest(json.dumps(identity, sort_keys=True).encode())
    session.manifest['requests'].append(dict(request_id=key, status='PENDING'))
    with pytest.raises(Invalid, match='PUBLIC_UNCERTAIN_ATTEMPT_NO_RETRY'):
        session.get('DOLT', public.DOLT, params=params)
    assert len(session.manifest['requests']) == 1


def test_cli_public_history_consumes_new_entrypoint_without_economic_evaluate(tmp_path, monkeypatch):
    from scripts.research.a2.options import cli, expression
    called = []
    def fake_run(output, offline=False):
        called.append((Path(output), offline))
        return dict(required_stage_success=True, planned_acquisition_opportunities=240,
                    raw_observation_rows=2, normalized_rows=2, public_http_requests=0)
    monkeypatch.setattr(public, 'run_public_history', fake_run)
    monkeypatch.setattr(cli, 'evaluate', lambda *a, **k: pytest.fail('Daily CLI called evaluate'))
    monkeypatch.setattr(expression, 'evaluate', lambda *a, **k: pytest.fail('Daily CLI called evaluate'))
    monkeypatch.setattr(cli, 'run', lambda *a, **k: pytest.fail('Daily CLI fell back to legacy run'))
    assert cli.main(['--mode', 'public-history', '--output', str(tmp_path), '--offline']) == 0
    assert called == [(tmp_path, True)]


@pytest.mark.parametrize('mode', ['synthetic', 'local', 'real-options', 'real-stock'])
def test_cli_offline_flag_is_not_silently_accepted_by_old_modes(mode, monkeypatch):
    from scripts.research.a2.options import cli
    monkeypatch.setattr(cli, 'run', lambda *a, **k: pytest.fail('Offline old mode was executed'))
    monkeypatch.setattr(cli, 'run_historical_quotes', lambda *a, **k: pytest.fail('Offline old mode made quote requests'))
    assert cli.main(['--mode', mode, '--offline']) == 2
