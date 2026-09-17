import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pyarrow.parquet as pq
import pytest

from scripts.storage import refresh_cftc_cot as m


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(m.json_bytes(value))


def raw_receipt(root, name, url, value):
    body = m.json_bytes(value)
    path = root / 'raw' / name / (hashlib.sha256(url.encode()).hexdigest() + '.source')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    raw = {'local_path': str(path), 'sha256': hashlib.sha256(body).hexdigest(),
           'source_reference': url, 'status': 'DOWNLOADED', 'retrieval_timestamp_utc': '2026-09-14T16:00:00Z'}
    put(path.with_suffix('.json'), {**raw, 'byte_count': len(body)})
    receipt = root / (name + '.json')
    put(receipt, {'url': url, 'raw': raw, 'http_response': {'status': 200}})
    return m.identity(receipt)


@pytest.fixture
def fixture(tmp_path):
    fields = [('id', 'text'), ('cftc_contract_market_code', 'text'), ('report_date_as_yyyy_mm_dd', 'calendar_date'), ('futonly_or_combined', 'text'), ('open_interest_all', 'number')]
    meta = {'id': 'gpe5-46if', 'name': 'TFF - Futures Only', 'provenance': 'official', 'rowsUpdatedAt': 123,
            'columns': [{'fieldName': n, 'dataTypeName': t} for n, t in fields]}
    stamp = '2026-09-08T00:00:00.000'
    rows = [{'id': 'r' + c, 'cftc_contract_market_code': c, 'report_date_as_yyyy_mm_dd': stamp, 'futonly_or_combined': 'FutOnly', 'open_interest_all': '12345678901234567890.001'} for c in m.CODES]
    aggregate = [{'cftc_contract_market_code': c, 'row_count': '1', 'first_date': stamp, 'last_date': stamp} for c in m.CODES]
    where = m.where_clause('2026-09-15')
    plan = {'codes': list(m.CODES), 'start_date': m.START, 'as_of': '2026-09-15', 'where': where, 'page_size': m.PAGE_SIZE,
            'fields': m.schema_fields(meta), 'metadata_rows_updated_at': 123, 'expected': m.aggregate_stats(aggregate), 'expected_rows': len(rows), 'latest_date': stamp[:10]}
    plan_path = tmp_path / 'plan.json'; put(plan_path, plan)
    refs = {}
    for phase in ['before', 'after']:
        for kind, url, value in [('metadata', m.METADATA, meta), ('scope', m.aggregate_url(where), aggregate),
                                 ('latest', m.api_url(**{'$select': 'max(report_date_as_yyyy_mm_dd) as latest,count(*) as total', '$limit': 1}), [{'latest': stamp, 'total': '999'}])]:
            name = kind + '_' + phase
            refs[name] = raw_receipt(tmp_path, name, url, value)
    url = m.api_url(**{'$where': where, '$order': 'report_date_as_yyyy_mm_dd,cftc_contract_market_code,id', '$limit': m.PAGE_SIZE, '$offset': 0})
    page = {'offset': 0, 'url': url, 'receipt': raw_receipt(tmp_path, 'page', url, rows)}
    return {'plan': plan, 'plan_file': m.identity(plan_path), 'references': refs, 'pages': [page]}, tmp_path, rows


def replace_page(fixture, rows):
    result, root, _ = fixture
    result['pages'][0]['receipt'] = raw_receipt(root, 'page', result['pages'][0]['url'], rows)


def test_full_fields_decimal_token_null_preservation(fixture):
    result, root, rows = fixture
    rows[0]['open_interest_all'] = '.'
    rows[1].pop('open_interest_all')
    rows[2]['open_interest_all'] = None
    replace_page(fixture, rows)
    out = list(m.normalized_rows(result, root / 'raw'))
    assert out[0]['open_interest_all'] == '.'
    assert 'open_interest_all' not in json.loads(out[1]['source_row_json'])
    assert json.loads(out[2]['source_row_json'])['open_interest_all'] is None
    assert out[3]['open_interest_all'] == '12345678901234567890.001'
    assert all(r['available_at_utc'] is None and r['historical_pit_certified'] is False for r in out)


@pytest.mark.parametrize('change,error', [
    (lambda rows: rows.pop(), 'PAGE_LENGTH'),
    (lambda rows: rows.__setitem__(1, rows[0].copy()), 'DUPLICATE'),
    (lambda rows: rows.reverse(), 'UNSORTED'),
    (lambda rows: rows[0].update(cftc_contract_market_code='000000'), 'SCOPE'),
    (lambda rows: rows[0].update(futonly_or_combined='Combined'), 'SCOPE'),
    (lambda rows: rows[0].update(report_date_as_yyyy_mm_dd='2026-09-16T00:00:00.000'), 'SCOPE'),
    (lambda rows: rows[0].update(unknown='x'), 'UNKNOWN_FIELD'),
    (lambda rows: rows[0].update(open_interest_all=0), 'NONSTRING'),
    (lambda rows: rows[0].update(open_interest_all='NaN'), 'NONFINITE'),
])
def test_reject_bad_rows(fixture, change, error):
    result, root, rows = fixture
    change(rows); replace_page(fixture, rows)
    with pytest.raises(ValueError, match=error):
        list(m.normalized_rows(result, root / 'raw'))


def test_bookend_revision_mismatch(fixture):
    result, root, _ = fixture
    ref = result['references']['metadata_after']
    receipt = json.loads(Path(ref['path']).read_text(encoding="utf-8"))
    meta = json.loads(Path(receipt['raw']['local_path']).read_text(encoding="utf-8")); meta['rowsUpdatedAt'] += 1
    result['references']['metadata_after'] = raw_receipt(root, 'metadata_after', m.METADATA, meta)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        m.validate_acquisition(result, root / 'raw')


def test_pagination_gap(fixture):
    result, root, _ = fixture
    result['pages'][0]['offset'] = 1
    with pytest.raises(ValueError, match='PAGINATION_GAP'):
        m.validate_acquisition(result, root / 'raw')


def test_raw_hash_and_observed_identity(fixture):
    result, root, _ = fixture
    receipt = json.loads(Path(result['pages'][0]['receipt']['path']).read_text(encoding="utf-8"))
    path = Path(receipt['raw']['local_path'])
    meta = json.loads(path.with_suffix('.json').read_text(encoding="utf-8")); meta['retrieval_timestamp_utc'] = '2026-09-15T00:00:00Z'
    put(path.with_suffix('.json'), meta)
    with pytest.raises(ValueError, match='SIDECAR'):
        list(m.normalized_rows(result, root / 'raw'))


def test_duplicate_json_and_bad_calendar():
    with pytest.raises(ValueError, match='DUPLICATE_JSON'):
        m.strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError):
        m.period('2026-02-30T00:00:00.000')
    with pytest.raises(ValueError):
        m.period('2026-09-08T15:30:00.000')


def test_scope_complete_and_literal_codes(fixture):
    result, root, _ = fixture
    assert "'13874A'" in result['plan']['where']
    bad = [{'cftc_contract_market_code': m.CODES[0], 'row_count': '0', 'first_date': '2026-09-08T00:00:00.000', 'last_date': '2026-09-08T00:00:00.000'}]
    with pytest.raises(ValueError, match='AGGREGATE'):
        m.aggregate_stats(bad)


@pytest.mark.parametrize('status', [401, 403, 429, 503])
def test_failed_http_is_one_attempt_and_stops_source(tmp_path, monkeypatch, status):
    paths = SimpleNamespace(results_root=tmp_path / 'results', cache_root=tmp_path / 'cache', repo_root=Path('D:/us-tech-quant'))
    capture = m.Capture(paths, 'synthetic_test')
    calls = []
    def denied(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, status, 'failure', {}, None)
    monkeypatch.setattr(capture.opener, 'open', denied)
    with pytest.raises(RuntimeError, match='FAILED_SOURCE_STOPPED'):
        capture.get('metadata', m.METADATA)
    with pytest.raises((ValueError, RuntimeError)):
        capture.get('metadata', m.METADATA)
    with pytest.raises(RuntimeError, match='STOPPED'):
        capture.get('another', m.METADATA)
    assert calls == [m.METADATA]


def test_redirects_are_never_followed():
    assert m.NoRedirect().redirect_request(None, None, None, None, None, None) is None


def test_finished_manifest_replay_and_code_contract(tmp_path, fixture, monkeypatch):
    result, source_root, _ = fixture
    paths = SimpleNamespace(results_root=tmp_path / 'results', cache_root=tmp_path / 'cache', data_root=tmp_path / 'data')
    root = tmp_path
    monkeypatch.setattr(m, 'locations', lambda p, r: (root, source_root / 'raw'))
    acquisition = root / 'acquisition.json'; put(acquisition, result)
    manifest_path = m.normalize(paths, 'synthetic_test', acquisition)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert pq.read_table(manifest['outputs'][0]['path']).num_rows == 18
    original = manifest_path.read_bytes()
    monkeypatch.setattr(m, 'normalized_rows', lambda *a: (_ for _ in ()).throw(AssertionError('NO_REPARSE')))
    assert m.normalize(paths, 'synthetic_test', acquisition) == manifest_path
    assert manifest_path.read_bytes() == original
    manifest['contract']['normalizer']['sha256'] = '0' * 64
    put(manifest_path, manifest)
    with pytest.raises(ValueError, match='CONTRACT_CHANGED'):
        m.normalize(paths, 'synthetic_test', acquisition)
