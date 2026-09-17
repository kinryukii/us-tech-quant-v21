"""Synthetic checks of BLS source identity, missingness, dates and DataStore reads."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import uuid

import pandas as pd
import pytest

from scripts.storage import refresh_bls_observations as m
from scripts.storage.build_data_catalog import register_file
from scripts.storage.storage_r2a import CATALOG_SCHEMA_SQL, DataStore, CATALOG_ROLE, CATALOG_SCHEMA_VERSION


@pytest.fixture
def bundle():
    root = Path(tempfile.gettempdir())/('bls-test-' + uuid.uuid4().hex)
    paths = m.resolve(data_root=root/'data', cache_root=root/'cache', results_root=root/'results',
                      daily_root=root/'daily', backtest_root=root/'backtests')
    specs = {sid: m.series_specs()[sid] for sid in ['CUSR0000SA0', 'LNS14000000']}
    config = {'bls_api': {'endpoint': m.ENDPOINT, 'series': specs, 'start_year': 2026, 'end_year': 2026}}
    plan = {'as_of': '2026-03-14', 'start_year': 2026, 'tasks': [config], 'series_specs': specs}
    data = {'status': 'REQUEST_SUCCEEDED', 'message': ['The catalog has been disabled for this request.'],
            'Results': {'series': [{'seriesID': sid, 'data': [
                {'year': '2026', 'period': 'M02', 'value': '2.123', 'latest': 'true', 'footnotes': [{'code':'P','text':'Preliminary.'}]},
                {'year': '2026', 'period': 'M01', 'value': '-', 'footnotes': [{'code':'X','text':'Source unavailable'}]}]}
                for sid in specs]}}
    rawpath = paths.cache_root/'raw/fixture.json'; rawpath.parent.mkdir(parents=True)
    item = {'config': config, 'raw': {'status': 'DOWNLOADED', 'local_path': str(rawpath),
             'source_reference': m.ENDPOINT, 'source': 'BLS_OFFICIAL', 'event_family': 'BLS_API',
             'document_kind': 'bls_api_values', 'retrieval_timestamp_utc': '2026-03-14T01:00:00Z'}}
    persist(item, data)
    return paths, plan, item, data


def persist(item, data):
    path = Path(item['raw']['local_path']); path.write_bytes(m.json_bytes(data))
    item['raw']['sha256'] = m.sha256(path)
    api = item['config']['bls_api']
    request = {'seriesid': list(api['series']), 'startyear': api['start_year'], 'endyear': api['end_year'], 'catalog': True}
    path.with_suffix('.meta.json').write_text(json.dumps({'source_reference': m.ENDPOINT,
        'series_ids': list(api['series']),
        'sha256': item['raw']['sha256'], 'retrieval_timestamp_utc': item['raw']['retrieval_timestamp_utc'],
        'request_sha256': hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}))


def test_missing_values_notes_and_reference_month_not_publication(bundle):
    paths, _, item, _ = bundle
    frame, _ = m.normalize_document(item, paths, '2026-03-14')
    assert len(frame) == 4 and frame.value.isna().sum() == 2
    assert frame.loc[frame.value.isna(), 'value_text'].tolist() == ['-', '-']
    assert frame.available_at_utc.isna().all()
    assert frame.date_semantics.eq('REFERENCE_PERIOD_START_NOT_PUBLICATION').all()
    assert set(frame.reference_period_end) == {'2026-01-31', '2026-02-28'}
    assert frame.loc[frame.value.isna(), 'footnotes_json'].str.contains('Source unavailable').all()


@pytest.mark.parametrize('alter,reason', [
    (lambda d: d.update(status='REQUEST_FAILED'), 'UNSUCCESSFUL'),
    (lambda d: d.update(message=['Annual request limit exceeded']), 'WARNING'),
    (lambda d: d['Results']['series'].pop(), 'PARTIAL'),
    (lambda d: d['Results']['series'][0].update(seriesID='UNKNOWN'), 'PARTIAL'),
    (lambda d: d['Results']['series'][0]['data'][0].update(period='M13'), 'PERIOD'),
    (lambda d: d['Results']['series'][0]['data'][0].update(year='2027'), 'YEAR'),
    (lambda d: d['Results']['series'][0]['data'][0].update(value='inf'), 'NUMERIC'),
    (lambda d: d['Results']['series'][0]['data'][0].update(value='2.1oops'), 'NUMERIC'),
])
def test_invalid_payloads_fail_closed(bundle, alter, reason):
    paths, _, item, data = bundle
    alter(data); persist(item, data)
    with pytest.raises(ValueError, match=reason):
        m.normalize_document(item, paths, '2026-03-14')


def test_raw_and_request_identity_checked(bundle):
    paths, _, item, data = bundle
    Path(item['raw']['local_path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='RAW_IDENTITY'):
        m.verified_payload(item, paths)
    persist(item, data)
    item['config']['bls_api']['end_year'] = 2027
    with pytest.raises(ValueError, match='REQUEST_OR_VINTAGE'):
        m.verified_payload(item, paths)


def test_latest_source_marker_required_and_incomplete_month_excluded(bundle):
    paths, plan, item, data = bundle
    frame, _ = m.normalize_document(item, paths, '2026-02-14')
    assert frame.reference_period.unique().tolist() == ['2026-01']
    data['Results']['series'][0]['data'][0].pop('latest'); persist(item, data)
    with pytest.raises(ValueError, match='LATEST_MARKER'):
        m.normalize_all([item], plan, paths)


def test_missing_month_cannot_be_silently_published(bundle):
    paths, plan, item, data = bundle
    data['Results']['series'][0]['data'].pop(); persist(item, data)
    with pytest.raises(ValueError, match='MISSING_MONTHS'):
        m.normalize_all([item], plan, paths)


def test_source_duplicate_rejected(bundle):
    paths, _, item, data = bundle
    data['Results']['series'][0]['data'].append(copy.deepcopy(data['Results']['series'][0]['data'][0])); persist(item, data)
    with pytest.raises(RuntimeError, match='DUPLICATE'):
        m.normalize_document(item, paths, '2026-03-14')


def test_data_store_roundtrip_and_same_inputs_are_idempotent(bundle):
    paths, plan, item, _ = bundle
    result = m.normalize_all([item], plan, paths)
    assert m.normalize_all([item], plan, paths) == result
    record = result['catalog_records'][0]
    catalog = paths.cache_root/'derived/data_catalog/catalog.sqlite3'; catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as conn:
        conn.executescript(CATALOG_SCHEMA_SQL)
        conn.executemany('INSERT INTO catalog_metadata VALUES (?,?)', [('catalog_role', CATALOG_ROLE), ('schema_version', CATALOG_SCHEMA_VERSION)])
        register_file(conn, m.DATASET, '', '', record['path'], record['row_count'], record['min_date'], record['max_date'], record['source'], record['lineage'])
    store = DataStore(paths)
    frame = store.read(m.DATASET, start_date='2026-02-01', end_date='2026-02-28')
    assert len(frame) == 2 and frame.value.tolist() == [2.123, 2.123]
    assert store.metadata(m.DATASET)['lineage']['historical_pit_certified'] is False


def test_40_series_plan_with_unregistered_bls_limits(bundle):
    paths, _, _, _ = bundle
    plan = m.request_plan(paths, 'new-run', 2010, '2026-09-14')
    assert len(plan['series_specs']) == 40 and len(plan['tasks']) == 4
    assert all(len(t['bls_api']['series']) <= 25 and t['bls_api']['end_year'] - t['bls_api']['start_year'] < 10 for t in plan['tasks'])
    assert plan['series_specs']['CUSR0000SEHC']['units'] == 'INDEX_198212_100'
    assert plan['series_specs']['JTS000000000000000JOL']['units'] == 'THOUSANDS_OF_POSITIONS'


def test_saved_json_key_sorting_does_not_change_actual_post_identity(bundle):
    paths, _, item, data = bundle
    api = item['config']['bls_api']
    api['series'] = dict(reversed(list(api['series'].items())))
    persist(item, data)
    saved = paths.results_root/'request.json'
    m.save_json(saved, item)
    loaded = json.loads(saved.read_text())
    assert list(loaded['config']['bls_api']['series']) != list(api['series'])
    frame, _ = m.normalize_document(loaded, paths, '2026-03-14')
    assert len(frame) == 4
    meta_path = Path(item['raw']['local_path']).with_suffix('.meta.json')
    meta = json.loads(meta_path.read_text()); meta['series_ids'] = ['UNKNOWN', 'UNKNOWN']
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='SERIES_IDENTITY'):
        m.verified_payload(loaded, paths)
