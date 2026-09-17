import csv
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from scripts.storage import refresh_sec_nport as m


def package(tmp_path, *, form='NPORT-P/A', filing_date='30-JUN-2026', report_date='31-MAY-2026',
            second_id='h2', child_id='h1', number='-123.456', series='', note='NA "source" note', empty=False):
    paths = SimpleNamespace(cache_root=tmp_path / 'cache', data_root=tmp_path / 'data',
                            results_root=tmp_path / 'results', repo_root=tmp_path / 'repo')
    for folder in (paths.cache_root, paths.data_root, paths.results_root): folder.mkdir(exist_ok=True)
    tables = {
        'SUBMISSION': (['ACCESSION_NUMBER','FILING_DATE','FILE_NUM','SUB_TYPE','REPORT_ENDING_PERIOD','REPORT_DATE','IS_LAST_FILING'],
                       [['a1','01-APR-2026','','NPORT-P','31-DEC-2026','31-JAN-2026','N'],
                        ['a2',filing_date,'',form,'31-DEC-2026',report_date,'Y']]),
        'REGISTRANT': (['ACCESSION_NUMBER','CIK','REGISTRANT_NAME','FILE_NUM'],
                       [['a1','0000000042','fund','001'],['a2','0000000042','fund','001']]),
        'FUND_REPORTED_INFO': (['ACCESSION_NUMBER','SERIES_NAME','SERIES_ID','SERIES_LEI','NET_ASSETS'],
                              [['a1','fund','S000000042','lei','1'],['a2','fund',series,'lei','2']]),
        'FUND_REPORTED_HOLDING': (['ACCESSION_NUMBER','HOLDING_ID','BALANCE','UNIT','CURRENCY_CODE','CURRENCY_VALUE','EXCHANGE_RATE','PERCENTAGE'],
                                  [['a1','h1','-10','NS','EUR',number,'1.2','-12.3456'],['a2',second_id,'2','NS','USD','','','0']]),
        'IDENTIFIERS': (['HOLDING_ID','IDENTIFIERS_ID','IDENTIFIER_TICKER'],[[child_id,'i1','NA'],['h2','i2','ABC']]),
        'SECURITIES_LENDING': (['HOLDING_ID','IS_LOAN_BY_FUND','LOAN_VALUE'],[['h1','Y','12']]),
        'EXPLANATORY_NOTE': (['ACCESSION_NUMBER','EXPLANATORY_NOTE_ID','ITEM_NO','EXPLANATORY_NOTE'],[['a2','n1','C.2',note]]),
    }
    if empty:
        tables['EXPLANATORY_NOTE'] = (tables['EXPLANATORY_NOTE'][0], [])
    path = paths.cache_root / '2026q2_nport.zip'
    metadata = {'tables': [{'url': name + '.tsv','tableSchema': {'columns': [{'name': col} for col in cols]}}
                           for name,(cols,rows) in tables.items()]}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('nport_metadata.json', json.dumps(metadata))
        for name,(cols,rows) in tables.items():
            stream=io.StringIO(newline='')
            writer=csv.writer(stream,delimiter='\t',lineterminator='\n')
            writer.writerows([cols] + rows)
            z.writestr(name + '.tsv',stream.getvalue())
        z.writestr('UNNORMALIZED_DETAILS.tsv','KEY\tVALUE\nx\tfull source retained\n')
    raw = {'status': 'DOWNLOADED','path':str(path),'url':m.source_url('2026q2'),'sha256':m.sha256_file(path),
           'observed_at_utc':'2026-09-14T09:57:53+00:00'}
    return paths, raw


def run_fixture(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setattr(m, 'MIN_FREE_DISK', 0)
    monkeypatch.setattr(m, 'CHUNK_ROWS', 1)
    paths, raw = package(tmp_path, **kwargs)
    manifest = m.normalize(paths, 'test', '2026q2', raw, '2026-09-14')
    frames = {o['source_table']:pd.read_parquet(o['path']) for o in manifest['outputs']}
    return paths,raw,manifest,frames


def test_complete_rows_versions_units_and_null_pit(tmp_path, monkeypatch):
    paths,raw,manifest,frames = run_fixture(tmp_path,monkeypatch)
    f,h = frames['FILINGS'],frames['FUND_REPORTED_HOLDING']
    assert f.accession.tolist() == ['a1','a2']
    assert f.is_amendment.tolist() == [False,True]
    assert manifest['amendment_filings'] == 1 and manifest['missing_series_identity'] == 1
    assert f.REPORT_ENDING_PERIOD.eq('31-DEC-2026').all()
    assert h.value_usd.tolist() == [Decimal('-123.456'),None]
    assert h.CURRENCY_CODE.tolist() == ['EUR','USD']
    assert h.balance_numeric.iloc[0] == Decimal('-10')
    assert h.percent_net_assets.iloc[0] == Decimal('-12.3456')
    assert h.source_row_number.tolist() == [1,2]
    assert frames['IDENTIFIERS'].accession.tolist() == ['a1','a2']
    assert frames['IDENTIFIERS'].IDENTIFIER_TICKER.tolist() == ['NA','ABC']
    assert frames['EXPLANATORY_NOTE'].EXPLANATORY_NOTE.iloc[0] == 'NA "source" note'
    assert all(d.available_at_utc.isna().all() for d in frames.values())
    assert all(d.observed_at_utc.eq(raw['observed_at_utc']).all() for d in frames.values())
    assert manifest['archive_crc_verified']
    assert any(x['member']=='UNNORMALIZED_DETAILS.tsv' for x in manifest['members'])
    notes = next(x for x in manifest['outputs'] if x['source_table']=='EXPLANATORY_NOTE')
    assert notes['min_date'] == '2026-06-30'
    assert m.normalize(paths, 'test','2026q2',raw,'2026-09-14') == manifest


@pytest.mark.parametrize('kwargs,error', [
    ({'second_id':'h1'},'DUPLICATE_HOLDING_ID'),
    ({'child_id':'missing'},'ORPHAN_HOLDING_OR_ACCESSION'),
    ({'form':'NPORT-NP'},'NONPUBLIC_OR_UNSUPPORTED'),
    ({'filing_date':'01-JUL-2026'},'FILING_DATE_MISSING_OR_AFTER'),
    ({'filing_date':''},'FILING_DATE_MISSING_OR_AFTER'),
    ({'number':'bad'},'NONNUMERIC_SOURCE_VALUE'),
    ({'number':'NaN'},'NONFINITE_SOURCE_VALUE'),
])
def test_source_faults_stop_without_silent_coercion(tmp_path,monkeypatch,kwargs,error):
    with pytest.raises(ValueError,match=error):run_fixture(tmp_path,monkeypatch,**kwargs)


def test_missing_report_date_preserved_review_flag(tmp_path,monkeypatch):
    _,_,manifest,frames=run_fixture(tmp_path,monkeypatch,report_date='')
    assert manifest['report_date_min']=='2026-01-31'
    assert manifest['report_date_review_rows']==1
    assert frames['FILINGS'].report_date.tolist()==['2026-01-31','']


def test_empty_auxiliary_table_still_has_schema(tmp_path,monkeypatch):
    _,_,manifest,frames=run_fixture(tmp_path,monkeypatch,empty=True)
    assert frames['EXPLANATORY_NOTE'].empty
    assert next(o for o in manifest['outputs'] if o['source_table']=='EXPLANATORY_NOTE')['min_date'] is None


def test_csvw_quoted_tab_newline_doublequote_preserved(tmp_path,monkeypatch):
    note='Issuer "quoted"\tcontains a tab\nand a new line'
    _,_,_,frames=run_fixture(tmp_path,monkeypatch,note=note)
    assert frames['EXPLANATORY_NOTE'].EXPLANATORY_NOTE.tolist()==[note]


def test_merge_retains_source_versions_exact_decimals_and_nullable_strings(tmp_path,monkeypatch):
    paths,raw,manifest,frames=run_fixture(tmp_path,monkeypatch)
    second=json.loads(json.dumps(manifest));second['contract']['quarter']='2026q1'
    second['outputs']=[]
    for output in manifest['outputs']:
        frame=pd.read_parquet(output['path']);frame['source_quarter']='2026q1';frame['EXTRA_SOURCE_FIELD']=''
        new_path=Path(output['path']).with_name('q1_'+Path(output['path']).name)
        frame.to_parquet(new_path,index=False)
        second['outputs'].append({**output,**m.file_identity(new_path)})
    # pandas infers decimal scale from values: preserve the exact normalizer schema.
    import pyarrow.parquet as pq
    import pyarrow as pa
    for output,original in zip(second['outputs'],manifest['outputs']):
        table=pq.read_table(output['path']);schema=pq.read_table(original['path']).schema
        for field in schema:
            if pa.types.is_decimal(field.type):
                i=table.column_names.index(field.name);table=table.set_column(i,field,table[field.name].cast(field.type))
        pq.write_table(table,output['path']);output.update(m.file_identity(Path(output['path'])))
    result=m.merge_quarters(paths,'test',[manifest,second],'2026-09-14')
    assert result['filings']==4 and result['unique_accessions']==2
    assert result['cross_package_duplicate_accessions']==2 and result['cross_package_duplicate_filing_rows']==2
    holding=pd.read_parquet(next(o['path'] for o in result['outputs'] if o['source_table']=='FUND_REPORTED_HOLDING'))
    assert holding.value_usd.tolist()==[Decimal('-123.456'),None,Decimal('-123.456'),None]
    assert holding.source_quarter.tolist()==['2026q1','2026q1','2026q2','2026q2']
    assert holding.EXTRA_SOURCE_FIELD.iloc[:2].eq('').all() and holding.EXTRA_SOURCE_FIELD.iloc[2:].isna().all()
    assert m.merge_quarters(paths,'test',[manifest,second],'2026-09-14')==result


def test_raw_hash_change_and_output_change_are_rejected(tmp_path,monkeypatch):
    paths,raw,manifest,_=run_fixture(tmp_path,monkeypatch)
    output=Path(manifest['outputs'][0]['path'])
    with output.open('ab') as f:f.write(b'x')
    with pytest.raises(ValueError,match='EXISTING_OUTPUT_IDENTITY_DIFFERS'):m.normalize(paths,'test','2026q2',raw,'2026-09-14')
    raw['sha256']='bad'
    with pytest.raises(ValueError,match='RAW_SOURCE_IDENTITY_INVALID'):m.normalize(paths,'test','2026q2',raw,'2026-09-14')


def test_provider_metadata_schema_must_match(tmp_path):
    paths,raw=package(tmp_path)
    with zipfile.ZipFile(raw['path']) as z:
        schemas=m.inspect_archive(z);schemas['SUBMISSION.tsv']['columns'][0]['name']='WRONG'
        with pytest.raises(ValueError,match='TABLE_COLUMNS_DIFFER'):m.read_table(z,'SUBMISSION',schemas)


def test_decimal_precision_not_rounded():
    assert m.decimal_values(['123.000000000001','']).to_pylist()==[Decimal('123.000000000001'),None]
    with pytest.raises(Exception):m.decimal_values(['.1234567890123'])


def test_denial_stops_no_retry_and_no_follow_redirect(tmp_path,monkeypatch):
    paths,_=package(tmp_path)
    monkeypatch.setattr(m,'MIN_FREE_DISK',0)
    monkeypatch.setattr(m,'configured_user_agent',lambda _: 'Research test@example.org')
    monkeypatch.setattr(m.time,'sleep',lambda _:None)
    calls=[]
    class Response:
        status_code=403
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
    class Session:
        def get(self,url,**kwargs):calls.append((url,kwargs));return Response()
    with pytest.raises(ValueError,match='HTTP_403'):m.download(paths,'denied','2026q2',session=Session())
    assert len(calls)==1 and calls[0][1]['allow_redirects'] is False
    with pytest.raises(ValueError,match='INCOMPLETE_OR_DENIED'):m.download(paths,'denied','2026q2',session=Session())
    assert len(calls)==1
    meta=json.loads((paths.cache_root/'official_research_intake/denied/sec_nport/raw/2026q2_nport.json').read_text())
    assert meta['status']=='STOPPED_SOURCE_FAILURE' and '@' not in json.dumps(meta)


@pytest.mark.parametrize('quarter',['2019q3','2026q5','../../../x'])
def test_invalid_package_scopes(quarter):
    with pytest.raises(ValueError):m.source_url(quarter)
