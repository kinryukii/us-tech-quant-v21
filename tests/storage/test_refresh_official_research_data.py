"""Synthetic parser, lineage and real catalog/DataStore integration tests."""
import json
from decimal import Decimal
from dataclasses import make_dataclass
from pathlib import Path
import sqlite3
import tempfile
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.storage import refresh_official_research_data as m
from scripts.storage.storage_r2a import CATALOG_SCHEMA_SQL, DataStore

HEADER = 'Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n'


def finra(rows='20251231|ABC|60|10|100|B,Q,N', count=1):
    return (HEADER + rows + '\n' + str(count) + '\n').encode()


def treasury(dataset=m.NOMINAL, value='-0.25', year=2025):
    nominal = dataset in {m.NOMINAL, m.CURRENT_NAMES[m.NOMINAL]}
    prefix = 'BC_' if nominal else 'TC_'
    category = 'DailyTreasuryYieldCurveRateDatum' if nominal else 'DailyTreasuryRealYieldCurveRateDatum'
    fields = ''.join(f'<d:{prefix}{tenor} m:type="Edm.Double">{value}</d:{prefix}{tenor}>' for tenor in ['5YEAR', '10YEAR', '30YEAR'])
    return (f'<feed xmlns="{m.NS["a"]}" xmlns:m="{m.NS["m"]}" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
        '<entry><updated>2026-09-14T01:00:00Z</updated>'
        f'<category term="Model.{category}"/><content><m:properties><d:NEW_DATE>{year}-12-31T00:00:00</d:NEW_DATE>'
        f'{fields}</m:properties></content></entry></feed>').encode()


def test_finra_exempt_already_included_and_symbols_preserved():
    f = m.parse_finra(finra(), '2025-12-31')
    assert f.short_volume_share.iloc[0] == .6
    assert f.short_exempt_volume.iloc[0] == 10
    assert 'ticker' not in f
    assert f.provider_symbol.iloc[0] == 'ABC'


@pytest.mark.parametrize('payload,day,reason', [
    (finra(count=2), '2025-12-31', 'TRAILER'),
    (finra(), '2025-12-30', 'DATE'),
    (finra('20251231|ABC|60|61|100|Q'), '2025-12-31', 'ORDER'),
    (finra('20251231|ABC|101|0|100|Q'), '2025-12-31', 'ORDER'),
    (finra('20251231|ABC|1.5|0|100|Q'), '2025-12-31', 'INTEGER'),
    (finra('20251231|ABC|60|0|100|Q,Q'), '2025-12-31', 'FACILITY'),
    (finra('20251231|ABC|60|0|100|O'), '2025-12-31', 'FACILITY'),
    (finra('20251231|ABC|60|0|100|Q\n20251231|ABC|60|0|100|N', 2), '2025-12-31', 'DUPLICATED'),
    (finra(), '2026-01-01', 'PRE2026'),
])
def test_finra_rejects_malformed_or_wrong_scope(payload, day, reason):
    with pytest.raises(ValueError, match=reason):
        m.parse_finra(payload, day)


def test_finra_zero_volume_is_missing_ratio_not_zero_signal():
    f = m.parse_finra(finra('20251231|ABC|0|0|0|Q'), '2025-12-31')
    assert f.short_volume_share.isna().all()
    assert f.volume_status.iloc[0] == 'ZERO_TOTAL_VOLUME'


def test_treasury_preserves_negative_yield_and_feed_update():
    f = m.parse_treasury(treasury(m.REAL), m.REAL, 2025)
    assert f.yield_percent.eq(-.25).all()
    assert f.date.eq('2025-12-31').all()
    assert f.feed_updated_at_utc.eq('2026-09-14T01:00:00Z').all()


def test_treasury_source_null_is_retained():
    raw = treasury().replace(b'<d:BC_10YEAR m:type="Edm.Double">-0.25</d:BC_10YEAR>', b'<d:BC_10YEAR m:null="true"/>')
    f = m.parse_treasury(raw, m.NOMINAL, 2025)
    assert len(f) == 3 and f.yield_percent.isna().sum() == 1


@pytest.mark.parametrize('raw,dataset,year', [
    (treasury(), m.REAL, 2025), (treasury(), m.NOMINAL, 2024),
    (treasury(year=2026), m.NOMINAL, 2026),
    (treasury(value='inf'), m.NOMINAL, 2025),
    (treasury().replace(b'BC_5YEAR', b'BC_UNKNOWN'), m.NOMINAL, 2025),
    (b'<!DOCTYPE root>' + treasury(), m.NOMINAL, 2025),
])
def test_treasury_rejects_invalid_source(raw, dataset, year):
    with pytest.raises(ValueError):
        m.parse_treasury(raw, dataset, year)


@pytest.fixture
def bundle():
    root = Path(tempfile.gettempdir()) / ('official-data-test-' + uuid.uuid4().hex)
    paths = m.resolve(data_root=root/'data', cache_root=root/'cache', results_root=root/'results',
                      daily_root=root/'daily', backtest_root=root/'backtests')
    tasks, items = [], []
    for dataset in sorted(m.DATASETS):
        payload = finra() if dataset == m.FINRA else treasury(dataset)
        period = '2025-12-31' if dataset == m.FINRA else '2025'
        url = m.FINRA_URL.format(day='20251231') if dataset == m.FINRA else m.TREASURY_URL.format(kind=m.KINDS[dataset], year=2025)
        task = {'dataset': dataset, 'period': period, 'url': url}
        rawpath = paths.cache_root / (dataset + '.source')
        rawpath.parent.mkdir(parents=True, exist_ok=True)
        rawpath.write_bytes(payload)
        tasks.append(task)
        items.append({**task, 'raw': {'status': 'DOWNLOADED', 'source': 'FINRA_OFFICIAL' if dataset == m.FINRA else 'US_TREASURY_OFFICIAL',
            'local_path': str(rawpath), 'sha256': m.sha256(rawpath), 'source_reference': url,
            'retrieval_timestamp_utc': '2026-09-14T01:00:00Z'}})
    catalog = paths.cache_root/'derived/data_catalog/catalog.sqlite3'
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as conn:
        conn.executescript(CATALOG_SCHEMA_SQL)
        conn.executemany('INSERT INTO catalog_metadata VALUES (?,?)', [('schema_version', m.CATALOG_SCHEMA_VERSION), ('catalog_role', m.CATALOG_ROLE)])
    return paths, {'tasks': tasks}, items


def test_normalize_register_query_and_unknown_historical_availability(bundle):
    paths, plan, items = bundle
    result = m.normalize_items(items, plan, paths)
    path = paths.results_root/'manifest.json'
    m.save_json(path, result)
    m.publish_catalog(path, paths)
    store = DataStore(paths)
    frame = store.read(m.FINRA, start_date='2025-12-31', end_date='2025-12-31')
    assert frame.short_volume_share.tolist() == [.6]
    assert frame.available_at_utc.isna().all()
    assert frame.vintage_semantics.eq(m.VINTAGE).all()
    assert store.read(m.FINRA, end_date='2025-12-30').empty
    assert store.metadata(m.FINRA)['lineage']['historical_pit_certified'] is False


def test_missing_source_blocks_publication(bundle):
    paths, plan, items = bundle
    items[0]['raw']['status'] = 'FAILED'
    with pytest.raises(ValueError, match='INCOMPLETE'):
        m.normalize_items(items, plan, paths)


def test_normalization_is_idempotent_for_same_inputs(bundle):
    paths, plan, items = bundle
    first = m.normalize_items(items, plan, paths)
    second = m.normalize_items(items, plan, paths)
    assert first == second


def test_raw_tamper_detected_before_catalog_mutation(bundle):
    paths, plan, items = bundle
    result = m.normalize_items(items, plan, paths)
    path = paths.results_root/'manifest.json'
    m.save_json(path, result)
    Path(items[0]['raw']['local_path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='IDENTITY'):
        m.publish_catalog(path, paths)
    with sqlite3.connect(paths.cache_root/'derived/data_catalog/catalog.sqlite3') as conn:
        assert conn.execute('SELECT count(*) FROM data_files').fetchone()[0] == 0


def test_invalid_catalog_role_rejected(bundle):
    paths, plan, items = bundle
    path = paths.results_root/'manifest.json'
    m.save_json(path, m.normalize_items(items, plan, paths))
    with sqlite3.connect(paths.cache_root/'derived/data_catalog/catalog.sqlite3') as conn:
        conn.execute("UPDATE catalog_metadata SET value='INVALID' WHERE key='catalog_role'")
    with pytest.raises(ValueError, match='SCHEMA_OR_ROLE'):
        m.publish_catalog(path, paths)


def test_current_finra_preserves_six_decimals_and_large_counts_exactly():
    f = m.parse_finra(finra('20260911|ABC|9007199254.123456|.0|9007199255.123456|Q').replace(b'|.0|', b'|0.000001|'),
                      '2026-09-11', as_of='2026-09-14')
    assert f.short_volume.iloc[0] == Decimal('9007199254.123456')
    assert f.short_exempt_volume.iloc[0] == Decimal('0.000001')


@pytest.mark.parametrize('day,volume,as_of', [
    ('2026-02-20', '1.000001', '2026-09-14'),
    ('2026-02-23', '1.0000001', '2026-09-14'),
    ('2026-02-23', '-1', '2026-09-14'),
    ('2026-02-23', '1e2', '2026-09-14'),
    ('2026-09-15', '1', '2026-09-14'),
])
def test_current_finra_rejects_precision_transition_or_boundary_error(day, volume, as_of):
    with pytest.raises(ValueError):
        m.parse_finra(finra(f'{day.replace("-", "")}|ABC|{volume}|0|100|Q'), day, as_of=as_of)


def test_treasury_current_annual_feed_is_bounded_by_as_of():
    dataset = m.CURRENT_NAMES[m.NOMINAL]
    raw = treasury(dataset, year=2026).replace(b'2026-12-31T00:00:00', b'2026-09-11T00:00:00')
    extra = raw[raw.index(b'<entry>'):raw.index(b'</entry>') + len(b'</entry>')].replace(b'2026-09-11', b'2026-09-15')
    raw = raw.replace(b'</feed>', extra + b'</feed>')
    f = m.parse_treasury(raw, dataset, 2026, as_of='2026-09-14')
    assert len(f) == 3 and f.date.unique().tolist() == ['2026-09-11']
    with pytest.raises(ValueError, match='CONTRACT'):
        m.parse_treasury(raw, m.NOMINAL, 2026, as_of='2026-09-14')


def current_bundle(paths, items):
    current = []
    for item in items:
        current.append({**item, 'dataset': m.CURRENT_NAMES[item['dataset']], 'raw': dict(item['raw'])})
    dataset = m.CURRENT_NAMES[m.FINRA]
    rawpath = paths.cache_root / 'finra-current.source'
    rawpath.write_bytes(finra('20260911|ABC|60.123456|0.000001|100.123457|Q'))
    url = m.FINRA_URL.format(day='20260911')
    current.insert(1, {'dataset': dataset, 'period': '2026-09-11', 'url': url,
        'raw': {'status': 'DOWNLOADED', 'source': 'FINRA_OFFICIAL', 'local_path': str(rawpath),
                'sha256': m.sha256(rawpath), 'source_reference': url, 'retrieval_timestamp_utc': '2026-09-14T01:00:00Z'}})
    plan = {'as_of': '2026-09-14', 'tasks': [{k: item[k] for k in ['dataset', 'period', 'url']} for item in current]}
    return plan, current


def test_current_snapshot_mixed_integer_decimal_and_legacy_catalog_preserved(bundle):
    paths, plan, items = bundle
    legacy_path = paths.results_root/'legacy.json'
    m.save_json(legacy_path, m.normalize_items(items, plan, paths))
    m.publish_catalog(legacy_path, paths)
    before = {dataset: DataStore(paths).metadata(dataset) for dataset in m.DATASETS}
    current_plan, current_items = current_bundle(paths, items)
    result = m.normalize_items(current_items, current_plan, paths)
    manifest = paths.results_root/'current.json'
    m.save_json(manifest, result)
    m.publish_catalog(manifest, paths)
    store = DataStore(paths)
    dataset = m.CURRENT_NAMES[m.FINRA]
    frame = store.read(dataset, end_date='2026-09-14')
    assert frame.short_volume.tolist() == [Decimal('60.000000'), Decimal('60.123456')]
    assert frame.available_at_utc.isna().all()
    assert store.metadata(dataset)['lineage']['as_of'] == '2026-09-14'
    assert pq.read_schema(store.metadata(dataset)['path']).field('short_volume').type == pa.decimal128(24, 6)
    assert {dataset: store.metadata(dataset) for dataset in m.DATASETS} == before
    assert m.normalize_items(current_items, current_plan, paths) == result


def test_current_identity_without_explicit_as_of_fails_closed(bundle):
    paths, _, items = bundle
    plan, items = current_bundle(paths, items)
    plan.pop('as_of')
    with pytest.raises(ValueError, match='TEMPORAL_SCOPE'):
        m.normalize_items(items, plan, paths)


def test_reuse_keeps_original_raw_path_hash_and_observation_time(bundle, monkeypatch):
    paths, plan, items = bundle
    manifest = paths.results_root/'legacy.json'
    m.save_json(manifest, m.normalize_items(items, plan, paths))
    current = {'tasks': [{**task, 'dataset': m.CURRENT_NAMES[task['dataset']]} for task in plan['tasks']]}
    class NoNetwork:
        def acquire_url(self, *args, **kwargs):
            raise AssertionError('Archive reuse must not download again')
    monkeypatch.setattr(m, 'archive_module', lambda _: NoNetwork())
    reused = m.acquire(current, paths, 'reuse-test', reuse_manifest=manifest)
    for before, after in zip(items, reused):
        assert after['dataset'] == m.CURRENT_NAMES[before['dataset']]
        for key in ['local_path', 'sha256', 'retrieval_timestamp_utc']:
            assert before['raw'][key] == after['raw'][key]
        assert after['raw']['status'] == 'CACHED'
    Path(items[0]['raw']['local_path']).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='REUSE_RAW_IDENTITY'):
        m.reusable_inputs(manifest, paths)


def test_current_year_treasury_is_refetched_across_manifests(bundle, monkeypatch):
    paths, _, items = bundle
    _, current = current_bundle(paths, items)
    annual = next(item for item in current if item['dataset'] == m.CURRENT_NAMES[m.NOMINAL])
    annual['period'] = '2026'
    annual['url'] = m.TREASURY_URL.format(kind=m.KINDS[annual['dataset']], year=2026)
    previous = {item['url']: item['raw'] for item in current}
    monkeypatch.setattr(m, 'reusable_inputs', lambda *args: previous)
    monkeypatch.setattr(m.time, 'sleep', lambda _: None)
    calls = []
    class Capture:
        def acquire_url(self, url, *args, **kwargs):
            calls.append(url)
            record = make_dataclass('Record', [(key, object) for key in annual['raw']])
            return record(**{**annual['raw'], 'status': 'DOWNLOADED'})
    monkeypatch.setattr(m, 'archive_module', lambda _: Capture())
    plan = {'as_of': '2026-09-14', 'tasks': [{k: item[k] for k in ['dataset', 'period', 'url']} for item in current]}
    m.acquire(plan, paths, 'new-current-run', reuse_manifest='old-current.json')
    assert calls == [annual['url']]


def test_current_manifest_cannot_publish_under_legacy_identity_or_beyond_as_of(bundle):
    paths, _, items = bundle
    plan, current = current_bundle(paths, items)
    result = m.normalize_items(current, plan, paths)
    invalid_identity = {**result, 'outputs': [{**o, 'dataset': o['dataset'].replace('_current', '_pre2026')} for o in result['outputs']]}
    path = paths.results_root/'wrong-identity.json'
    m.save_json(path, invalid_identity)
    with pytest.raises(ValueError, match='DATASET_SET'):
        m.publish_catalog(path, paths)
    path = paths.results_root/'wrong-boundary.json'
    result['outputs'][0]['max_date'] = '2026-09-15'
    m.save_json(path, result)
    with pytest.raises(ValueError, match='TEMPORAL_SCOPE'):
        m.publish_catalog(path, paths)
