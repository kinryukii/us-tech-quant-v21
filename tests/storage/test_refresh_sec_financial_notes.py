"""Bounded synthetic tests for SEC notes lineage, quoting, scope and resumption."""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pyarrow.parquet as pq
import pytest

from scripts.common.storage_paths import resolve
from scripts.storage import refresh_sec_financial_notes as m


def payload(table, columns, rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(columns); writer.writerows(rows)
    return output.getvalue()


def fixture(paths, periods=('2026_08',)):
    root = paths.results_root/'official_research_intake/test/sec_financial_notes'
    (root/'acquisition').mkdir(parents=True)
    raw_root = paths.cache_root/'official_research_intake/test/raw/sec_financial_notes'
    raw_root.mkdir(parents=True)
    tables = {
        'sub': (['adsh', 'cik', 'filed', 'accepted', 'form', 'aciks'], [
            ['A', '2488', '20260805', '2026-08-04 17:40:00.0', '10-Q', '9999'],
            ['B', '9999', '20260805', '', '10-Q/A', '2488']]),
        'num': (['adsh', 'tag', 'version', 'dimh', 'iprx', 'value', 'dcml', 'footnote'], [
            ['A', 'Revenue', '2026', '0x00000000', '2', '9999999999999999999.1234', '32767', ''],
            ['A', 'Revenue', '2026', '0x00000000', '3', '', '-6', ''],
            ['A', 'Revenue', '2026', '0x00000000', '4', '0.0000', '0', ''],
            ['B', 'Revenue', '2026', '0x00000000', '0', '999.0000', '-6', '']]),
        'txt': (['adsh', 'tag', 'version', 'dimh', 'iprx', 'value', 'srclen', 'escaped'], [
            ['A', 'Revenue', '2026', '0x00000000', '1', 'literal "quote"\tembedded tab\nnew line', '55', '1'],
            ['A', 'Revenue', '2026', '0x00000000', '2', 'NaN', '3', '0']]),
        'ren': (['adsh', 'report', 'longname'], [['A', '1', 'A "quoted" title']]),
        'pre': (['adsh', 'tag', 'version', 'negating'], [['A', 'Revenue', '2026', '1']]),
        'cal': (['adsh', 'ptag', 'pversion', 'ctag', 'cversion', 'negative'], [['A', 'Revenue', '2026', 'Unused', '2026', '-1']]),
        'tag': (['tag', 'version', 'doc'], [['Revenue', '2026', '"quoted" taxonomy'], ['Unused', '2026', 'preserve unused dictionary']]),
        'dim': (['dimhash', 'segments', 'segt'], [['0x00000000', '', '0'], ['0x123', 'unused dimension', '1']]),
    }
    tasks = []
    for period in periods:
        raw_path = raw_root/(period+'.source')
        with ZipFile(raw_path, 'w') as archive:
            for table, (columns, rows) in tables.items():
                archive.writestr(table+'.tsv', payload(table, columns, rows))
        url = 'https://www.sec.gov/files/dera/data/financial-statement-notes-data-sets/'+period+'_notes.zip'
        raw = {'local_path': str(raw_path), 'sha256': m.sha256_file(raw_path), 'status': 'DOWNLOADED',
               'source_reference': url, 'retrieval_timestamp_utc': '2026-09-14T10:04:15.648571Z'}
        raw_path.with_suffix('.json').write_text(json.dumps(raw), encoding='utf-8')
        task = {'period': period, 'url': url}; tasks.append(task)
        (root/'acquisition'/f'{period}.json').write_text(json.dumps({**task, 'raw': raw}), encoding='utf-8')
    plan = {'as_of': '2026-09-14', 'ciks': [2488], 'tasks': tasks, 'scope': {'sha256': 'fixture'},
            'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST'}
    (root/'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    return root, plan


@pytest.fixture
def paths(tmp_path):
    return resolve(repo_root=tmp_path/'repo', **{key: tmp_path/key for key in ['data_root', 'cache_root', 'results_root', 'daily_root', 'backtest_root', 'envs_root']})


def test_quoted_tsv_strings_scope_complete_dictionaries_and_lineage(paths):
    root, plan = fixture(paths)
    manifest = m.normalize(paths, 'test', '2026-09-14')
    num = pq.read_table(manifest['outputs']['num']['path']).to_pylist()
    assert [x['value'] for x in num] == ['9999999999999999999.1234', '', '0.0000']
    assert [x['iprx'] for x in num] == ['2', '3', '4']
    assert [x['source_value_is_empty'] for x in num] == [False, True, False]
    assert all(x['available_at_utc'] is None for x in num)
    assert num[0]['accepted_at_utc'] == datetime(2026, 8, 4, 21, 40, tzinfo=timezone.utc)
    assert num[0]['filing_date'].isoformat() == '2026-08-05'
    assert num[0]['observed_at_utc'] > num[0]['accepted_at_utc']
    assert len(num[0]['source_sha256']) == 64 and num[0]['source_row'] == 1
    txt = pq.read_table(manifest['outputs']['txt']['path']).to_pylist()
    assert txt[0]['value'] == 'literal "quote"\tembedded tab\nnew line' and txt[1]['value'] == 'NaN'
    dim = pq.read_table(manifest['outputs']['dim']['path']).to_pylist()
    assert len(dim) == 2 and dim[1]['dimhash'] == dim[1]['dimh'] == '0x123'
    assert dim[1]['filing_date'] is None and dim[1]['archive_period_end'].isoformat() == '2026-08-31'
    assert manifest['outputs']['tag']['rows'] == 2 and manifest['outputs']['sub']['rows'] == 1
    assert manifest['dictionary_links'] == {'unresolved_tag_keys': 0, 'unresolved_dimension_keys': 0}
    assert not manifest['historical_pit_certified']
    assert m.normalize(paths, 'test', '2026-09-14') == manifest


def test_historical_unclosed_literal_quote_cannot_swallow_following_rows(tmp_path):
    target = tmp_path/'historical.zip'
    content = 'tag\tversion\tdoc\nA\t2020\t"unclosed source text\nB\t2020\t"balanced literal text"\nC\t2020\tend\n'
    with ZipFile(target, 'w') as z:
        z.writestr('tag.tsv', content)
    with ZipFile(target) as z:
        dialect = m.member_dialect(z, 'tag.tsv')
        assert dialect['mode'] == 'LITERAL_TSV' and dialect['physical_rows'] == 3
        assert dialect['physical_rows_wrong_width'] == 0
        rows = [row for frame in m.batches(z, 'tag.tsv', 'tag', dialect=dialect) for row in frame.to_pylist()]
    assert [r['tag'] for r in rows] == ['A', 'B', 'C']
    assert [r['doc'] for r in rows] == ['"unclosed source text', '"balanced literal text"', 'end']


def test_ambiguous_literal_quote_and_embedded_tab_fail_closed(tmp_path):
    target = tmp_path/'ambiguous.zip'
    with ZipFile(target, 'w') as z:
        z.writestr('tag.tsv', 'tag\tversion\tdoc\nA\t2020\t"unclosed\nB\t2020\t"embedded\ttab"\n')
    with ZipFile(target) as z:
        with pytest.raises(ValueError, match='AMBIGUOUS_MIXED'):
            m.member_dialect(z, 'tag.tsv')


@pytest.mark.parametrize('expected', ['literal "quote"\tembedded tab\nnext line', 'newline alone\nnext line'])
def test_valid_quoted_member_preserves_embedded_tab_newline_and_doublequote(tmp_path, expected):
    target = tmp_path/'quoted.zip'
    with ZipFile(target, 'w') as z:
        z.writestr('tag.tsv', payload('tag', ['tag', 'version', 'doc'], [['A', '2026', expected]]))
    with ZipFile(target) as z:
        dialect = m.member_dialect(z, 'tag.tsv')
        assert dialect['mode'] == 'QUOTED_TSV'
        rows = [row for frame in m.batches(z, 'tag.tsv', 'tag', dialect=dialect) for row in frame.to_pylist()]
    assert rows == [{'tag':'A', 'version':'2026', 'doc':expected}]


def test_equal_width_physical_lines_cannot_silently_split_valid_quoted_records(tmp_path):
    target = tmp_path/'ambiguous_equal_width.zip'
    with ZipFile(target, 'w') as z:
        z.writestr('tag.tsv', payload('tag', ['tag', 'version', 'doc'], [['A','2020','first\nB\tinside\tlast'],['C','2020','end']]))
    with ZipFile(target) as z:
        with pytest.raises(ValueError, match='AMBIGUOUS_QUOTED_AND_LITERAL_RECORD_BOUNDARIES') as caught:
            list(m.batches(z, 'tag.tsv', 'tag'))
    details = json.loads(str(caught.value).split(':', 1)[1])
    assert details['physical_rows'] == 3 and details['quoted_rows'] == 2
    assert details['member'] == 'tag.tsv'
    assert details['samples'][0]['member_byte_offset'] == len('tag\tversion\tdoc\n')
    assert details['samples'][0]['physical_row'] == 1


@pytest.mark.parametrize('source,expected,status', [
    ('2026-08-04 17:40:00.0', '2026-08-04T21:40:00+00:00', 'PARSED_SOURCE_LOCAL_TIME'),
    ('2026-01-04 17:40:00.0', '2026-01-04T22:40:00+00:00', 'PARSED_SOURCE_LOCAL_TIME'),
    ('', None, 'SOURCE_EMPTY'), ('invalid', None, 'INVALID_SOURCE_LOCAL_TIME'),
    ('2026-11-01 01:30:00', None, 'AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME'),
    ('2026-03-08 02:30:00', None, 'AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME'),
])
def test_accepted_utc_does_not_guess(source, expected, status):
    parsed, actual = m.accepted_utc(source)
    assert (parsed.isoformat() if parsed else None) == expected and actual == status


def test_period_resume_and_complete_merge(paths):
    root, plan = fixture(paths, ('2026_08', '2026_07'))
    first = m.normalize(paths, 'test', '2026-09-14', '2026_08')
    assert first['status'] == 'NORMALIZED_AVAILABLE_PERIODS' and not (root/'manifest.json').exists()
    manifest = m.normalize(paths, 'test', '2026-09-14')
    assert manifest['outputs']['num']['rows'] == 6 and manifest['outputs']['dim']['rows'] == 4
    assert pq.read_table(manifest['outputs']['num']['path'])['source_period'].unique().to_pylist() == ['2026_08', '2026_07']


def test_raw_hash_and_sidecar_and_plan_mismatch_rejected(paths):
    root, plan = fixture(paths)
    with pytest.raises(ValueError, match='PLAN_MISMATCH'): m.normalize(paths, 'test', '2026-09-13')
    with pytest.raises(ValueError, match='PERIOD_NOT'): m.normalize(paths, 'test', '2026-09-14', '2026_09')
    item = m.verified_item(root, plan['tasks'][0]); path = Path(item['raw']['local_path'])
    meta = json.loads(path.with_suffix('.json').read_text()); meta['retrieval_timestamp_utc'] = '2026-09-13T00:00:00Z'
    path.with_suffix('.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='SIDECAR'): m.verified_item(root, plan['tasks'][0])
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='RAW_IDENTITY'): m.verified_item(root, plan['tasks'][0])


def test_cached_output_tamper_is_not_reused(paths):
    root, plan = fixture(paths, ('2026_08', '2026_07'))
    first = m.normalize(paths, 'test', '2026-09-14', '2026_08')
    receipt = json.loads((root/'normalization'/first['contract']['id']/'2026_08.json').read_text(encoding='utf-8'))
    Path(receipt['outputs']['num']['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='CACHE_HASH'): m.normalize(paths, 'test', '2026-09-14')


def test_malformed_header_and_row_rejected(tmp_path):
    for text in ['adsh\tvalue\nA\t1\n', 'adsh\treport\nA\t1\textra\n']:
        path = tmp_path/'test.zip'
        with ZipFile(path, 'w') as archive: archive.writestr('ren.tsv', text)
        with ZipFile(path) as archive:
            with pytest.raises(Exception): list(m.batches(archive, 'ren.tsv', 'ren'))


def test_data_store_roundtrip(paths):
    from scripts.storage.storage_r2a import DataStore, CATALOG_SCHEMA_SQL, CATALOG_ROLE, CATALOG_SCHEMA_VERSION
    from scripts.storage.build_data_catalog import register_file
    import sqlite3
    root, plan = fixture(paths)
    manifest = m.normalize(paths, 'test', '2026-09-14')
    catalog = paths.cache_root/'derived/data_catalog/catalog.sqlite3'; catalog.parent.mkdir(parents=True)
    output = manifest['outputs']['num']
    with sqlite3.connect(catalog) as connection:
        connection.executescript(CATALOG_SCHEMA_SQL)
        connection.executemany('INSERT INTO catalog_metadata VALUES (?,?)', [('schema_version', CATALOG_SCHEMA_VERSION), ('catalog_role', CATALOG_ROLE)])
        register_file(connection, 'notes_test', '', '', output['path'], output['rows'], '2026-08-05', '2026-08-05', 'SEC', {'date_column':'filing_date'})
    frame = DataStore(paths).read('notes_test', start_date='2026-08-05', end_date='2026-08-05', columns=['adsh', 'value'], date_column='filing_date')
    assert len(frame) == 3
