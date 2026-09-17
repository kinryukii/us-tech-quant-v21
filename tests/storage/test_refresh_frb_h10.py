"""Synthetic H.10 source identity, unit direction and missing-value checks."""
import io
import zipfile
from dataclasses import make_dataclass
from pathlib import Path
import tempfile
import sqlite3
import gc
import pandas as pd
import pytest

from scripts.storage import refresh_frb_h10 as m


def release_html():
    rows = '<tr><th>COUNTRY</th><th>CURRENCY</th>' + ''.join('<th>Sep. '+str(d)+'</th>' for d in range(1, 6)) + '</tr>'
    for name, country in m.SERIES_COUNTRIES.items():
        unit = 'JAN06=100' if name.startswith('JRX') else 'DOLLAR'
        rows += f'<tr><th>{country}</th><td>{unit}</td>' + '<td>1.2500</td>'*5 + '</tr>'
    return ('Release Date: September 8, 2026 H.10 Weekly<table>'+rows+'</table>').encode()


def zipped_xml(status='A', value='1.2500', duplicate=False):
    body = ''
    for name in m.SERIES_COUNTRIES:
        unit = 'Index:_1997_Jan_100' if name.startswith('JRX') else 'Currency'
        body += f'<s:Series FREQ="9" SERIES_NAME="{name}" FX="XYZ" CURRENCY="XYZ" UNIT="{unit}" UNIT_MULT="1">'
        body += f'<f:Obs TIME_PERIOD="2020-01-01" OBS_STATUS="{status}" OBS_VALUE="{value}"/>'
        if duplicate: body += '<f:Obs TIME_PERIOD="2020-01-01" OBS_STATUS="A" OBS_VALUE="1.25"/>'
        body += '<f:Obs TIME_PERIOD="2026-09-05" OBS_STATUS="A" OBS_VALUE="1.2500"/></s:Series>'
    xml = (f'<m:MessageGroup xmlns:m="{m.NS["m"]}" xmlns:f="{m.NS["f"]}" xmlns:s="{m.NS["s"]}">'
           '<m:Header><m:ID>H10</m:ID><m:Prepared>2026-09-08T12:00:00</m:Prepared></m:Header>'
           f'<f:DataSet>{body}</f:DataSet></m:MessageGroup>').encode()
    return zip_payload(xml)


def zip_payload(payload, name='H10_data.xml'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive: archive.writestr(name, payload)
    return stream.getvalue()


def test_release_latest_and_country_identity():
    result = m.parse_release(release_html())
    assert result['release_date'] == '2026-09-08'
    assert result['latest_date'] == '2026-09-05'
    assert len(result['series']) == 26


def test_quote_direction_metadata_conflict_and_all_series_retained():
    frame, summary = m.parse_sdmx(zipped_xml(), m.parse_release(release_html()), '2020-01-01', '2026-09-14')
    assert len(frame) == 52 and len(summary) == 26
    assert frame.loc[frame.provider_series.eq('RXI$US_N.B.EU'), 'quote_convention'].eq('USD_PER_FOREIGN_UNIT').all()
    assert frame.loc[frame.provider_series.eq('RXI_N.B.JA'), 'quote_convention'].eq('FOREIGN_UNITS_PER_USD').all()
    index = frame.loc[frame.provider_series.eq('JRXWTFB_N.B')]
    assert index.provider_unit.eq('Index:_1997_Jan_100').all()
    assert index.quote_convention.eq('INDEX_JAN2006_100').all()
    assert index.unit_metadata_status.eq('XML_BASE_LABEL_DIFFERS_FROM_OFFICIAL_RELEASE').all()


def test_missing_values_are_not_negative_exchange_rates():
    frame, _ = m.parse_sdmx(zipped_xml('ND', '-9999'), m.parse_release(release_html()), '2020-01-01', '2026-09-14')
    assert frame.value.isna().sum() == 26
    assert frame.loc[frame.value.isna(), 'provider_value_text'].eq('-9999').all()


@pytest.mark.parametrize('status,value', [('A', '-9999'), ('A', 'nan'), ('A', 'inf'), ('X', '1'), ('ND', '0')])
def test_unrecognized_or_invalid_values_fail_closed(status, value):
    with pytest.raises(ValueError):
        m.parse_sdmx(zipped_xml(status, value), m.parse_release(release_html()), '2020-01-01', '2026-09-14')


def test_duplicate_observation_and_unpublished_release_rejected():
    release = m.parse_release(release_html())
    with pytest.raises(ValueError, match='COVERAGE'):
        m.parse_sdmx(zipped_xml(duplicate=True), release, '2020-01-01', '2026-09-14')
    with pytest.raises(ValueError, match='BOUNDARY'):
        m.parse_sdmx(zipped_xml(), release, '2020-01-01', '2026-09-04')


def test_official_release_latest_value_must_agree_with_xml():
    release = m.parse_release(release_html())
    release['series']['JAPAN']['latest_value'] = '100'
    with pytest.raises(ValueError, match='VALUE_MISMATCH'):
        m.parse_sdmx(zipped_xml(), release, '2020-01-01', '2026-09-14')


def test_archive_member_name_and_external_entities_rejected():
    release = m.parse_release(release_html())
    with pytest.raises(ValueError, match='MEMBER'):
        m.parse_sdmx(zip_payload(b'xml', '../H10_data.xml'), release, '2020-01-01', '2026-09-14')
    with pytest.raises(ValueError, match='DECLARATION'):
        m.parse_sdmx(zip_payload(b'<!DOCTYPE root>'), release, '2020-01-01', '2026-09-14')


def test_missing_series_in_latest_page_fails_closed():
    with pytest.raises(ValueError, match='COUNTRY_SET'):
        m.parse_release(release_html().replace(b'*AUSTRALIA', b'UNKNOWN'))


def test_release_orphan_footer_cells_do_not_mutate_completed_rows():
    raw = release_html().replace(b'</table>', b'<td>Memo:</td></tr><td>UNRELATED</td></tr></table>')
    assert len(m.parse_release(raw)['series']) == 26


def test_run_roundtrip_idempotency_boundaries_and_catalog_read(monkeypatch):
    from scripts.storage.storage_r2a import DataStore, CATALOG_SCHEMA_SQL, CATALOG_ROLE, CATALOG_SCHEMA_VERSION
    from scripts.storage.build_data_catalog import register_file
    with tempfile.TemporaryDirectory(prefix='h10-test-') as directory:
        base = Path(directory)
        paths = m.resolve(data_root=base/'data', cache_root=base/'cache', results_root=base/'results',
                          daily_root=base/'daily', backtest_root=base/'backtests')
        calls = []
        class Capture:
            def acquire_url(self, url, family, source, kind, raw_root, *args):
                calls.append(url); raw_root.mkdir(parents=True, exist_ok=True)
                path = raw_root/(kind+'.source'); path.write_bytes(release_html() if kind=='CURRENT_RELEASE' else zipped_xml('ND','-9999'))
                data = {'status':'DOWNLOADED','source_reference':url,'local_path':str(path),'sha256':m.sha256(path),
                        'source':source,'retrieval_timestamp_utc':'2026-09-14T08:00:00Z'}
                return make_dataclass('Raw', [(k,object) for k in data])(**data)
        monkeypatch.setattr(m, 'archive_module', lambda _: Capture())
        monkeypatch.setattr(m.time, 'sleep', lambda _: None)
        first = m.run(paths,'test',as_of='2026-09-14')
        assert m.run(paths,'test',as_of='2026-09-14') == first and len(calls)==2
        output = first['outputs'][0]; frame = pd.read_parquet(output['path'])
        assert frame.available_at_utc.isna().all() and frame.value.isna().sum()==26
        catalog=paths.cache_root/'derived/data_catalog/catalog.sqlite3'; catalog.parent.mkdir(parents=True)
        with sqlite3.connect(catalog) as conn:
            conn.executescript(CATALOG_SCHEMA_SQL)
            conn.executemany('INSERT INTO catalog_metadata VALUES (?,?)',[('schema_version',CATALOG_SCHEMA_VERSION),('catalog_role',CATALOG_ROLE)])
            register_file(conn,m.DATASET,'','',output['path'],output['row_count'],output['min_date'],output['max_date'],'FRB_OFFICIAL',{'date_column':'date'})
        conn.close()
        assert len(DataStore(paths).read(m.DATASET,start_date='2026-09-01',end_date='2026-09-14'))==26
        with pytest.raises(ValueError,match='CONTRACT'):
            m.run(paths,'test',as_of='2026-09-13')
        Path(first['inputs'][0]['local_path']).write_bytes(b'changed')
        with pytest.raises(ValueError,match='IDENTITY'):
            m.run(paths,'test',as_of='2026-09-14')
        gc.collect()  # Release short-lived SQLite reader handles before Windows temp cleanup.
