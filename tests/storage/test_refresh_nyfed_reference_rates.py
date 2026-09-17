import json
from pathlib import Path
import sqlite3
import tempfile
import uuid

import pandas as pd
import pytest

from scripts.storage import refresh_nyfed_reference_rates as m
from scripts.storage.storage_r2a import CATALOG_SCHEMA_SQL, DataStore


def record(kind='SOFR', day='2026-09-10'):
    row={'effectiveDate':day,'type':kind,'revisionIndicator':'r'}
    if kind=='SOFRAI':row.update(average30day=3.1,average90day=3.2,average180day=3.3,index=1.25)
    else:row.update(percentRate=3.6,percentPercentile1=3.4,percentPercentile25=3.5,
                    percentPercentile75=3.7,percentPercentile99=3.8,volumeInBillions=100)
    return row


def blob(*rows):return json.dumps({'refRates':rows}).encode()


def test_source_na_footnote_and_revision_are_retained():
    row=record();row.update(percentPercentile1='NA',footnoteId=2)
    f=m.parse(blob(row),'sofr',m.STARTS['sofr'],'2026-09-14')
    x=f[f.metric.eq('percentPercentile1')].iloc[0]
    assert pd.isna(x.value) and x.value_status=='SOURCE_NOT_AVAILABLE'
    assert x.provider_value_json=='"NA"' and x.source_footnote_json=='2' and x.revision_indicator=='r'


def test_old_effr_fields_and_regime_not_filled():
    row={'effectiveDate':'2010-01-04','type':'EFFR','percentRate':.12,'intraDayLow':.05,
         'intraDayHigh':.38,'stdDeviation':.03,'targetRateFrom':0.,'targetRateTo':.25}
    f=m.parse(blob(row),'effr',m.STARTS['effr'],'2026-09-14')
    assert set(f.metric)==set(row)-{'effectiveDate','type'}
    assert f.methodology_regime.eq('EFFR_BEFORE_2016_03_01').all()
    assert 'volumeInBillions' not in set(f.metric)


def test_sofrai_index_and_rates_have_different_units():
    f=m.parse(blob(record('SOFRAI','2026-09-11')),'sofrai',m.STARTS['sofrai'],'2026-09-14')
    assert f[f.metric.eq('index')].unit.iloc[0]=='index'
    assert set(f[f.metric.ne('index')].unit)=={'percent'}


@pytest.mark.parametrize('change',[
    {'type':'EFFR'}, {'effectiveDate':'2026-09-15'}, {'percentRate':None},
    {'percentRate':True}, {'percentPercentile1':4.}, {'percentRate':'bad'},
    {'unknownField':2}, {'volumeInBillions':-1},
])
def test_bad_sources_fail(change):
    row=record();row.update(change)
    with pytest.raises(ValueError):m.parse(blob(row),'sofr',m.STARTS['sofr'],'2026-09-14')


def test_duplicate_dates_fail():
    row=record()
    with pytest.raises(ValueError,match='DUPLICATE'):
        m.parse(blob(row,row),'sofr',m.STARTS['sofr'],'2026-09-14')


@pytest.mark.parametrize('change',[{'percentRate':3.61},{'footnoteId':2},{'revisionIndicator':''},{'stdDeviation':.1}])
def test_latest_same_date_changed_value_or_metadata_fails(change):
    rows=[record(k.upper(),'2026-09-11' if k=='sofrai' else '2026-09-10') for k in m.STARTS]
    frames={r['type']:m.parse(blob(r),r['type'].lower(),m.STARTS[r['type'].lower()],'2026-09-14') for r in rows}
    rows[0].update(change)
    with pytest.raises(ValueError,match='VALUE_DIFFERS'):m.validate_latest(frames,blob(*rows),'2026-09-14')


def test_real_catalog_integration_and_source_tamper():
    root=Path(tempfile.gettempdir())/('nyfed-test-'+uuid.uuid4().hex)
    p=m.common.resolve(data_root=root/'data',cache_root=root/'cache',results_root=root/'results',
                       daily_root=root/'daily',backtest_root=root/'backtests')
    p.cache_root.mkdir(parents=True);p.results_root.mkdir(parents=True)
    def raw(payload,url,name):
        path=p.cache_root/name;path.write_bytes(payload)
        return {'status':'DOWNLOADED','source':'NYFED_OFFICIAL','source_reference':url,'local_path':str(path),
                'sha256':m.common.sha256(path),'retrieval_timestamp_utc':'2026-09-14T01:00:00Z'}
    rows=[record(k.upper(),'2026-09-11' if k=='sofrai' else '2026-09-10') for k in m.STARTS]
    items=[{'kind':k,'start':m.STARTS[k],'raw':raw(blob(r),m.url_for(k,'2026-09-14'),k)} for k,r in zip(m.STARTS,rows)]
    a={'as_of':'2026-09-14','items':items,'latest_raw':raw(blob(*rows),m.LATEST_URL,'latest')}
    catalog=p.cache_root/'derived/data_catalog/catalog.sqlite3';catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as c:
        c.executescript(CATALOG_SCHEMA_SQL)
        c.executemany('INSERT INTO catalog_metadata VALUES (?,?)',[('schema_version',m.CATALOG_SCHEMA_VERSION),('catalog_role',m.CATALOG_ROLE)])
    result=m.normalize(a,p);mp=p.results_root/'manifest.json';m.common.save_json(mp,result)
    m.publish(mp,p)
    f=DataStore(p).read(m.DATASET,start_date='2026-09-11',end_date='2026-09-11')
    assert len(f)==4 and f.rate_type.eq('SOFRAI').all() and f.available_at_utc.isna().all()
    with sqlite3.connect(catalog) as c:
        line=json.loads(c.execute('SELECT lineage_json FROM data_files WHERE dataset=?',(m.DATASET,)).fetchone()[0])
        next(x for x in line['freshness'] if x['rate_type']=='SOFR')['observation_dates']=2
        c.execute('UPDATE data_files SET lineage_json=? WHERE dataset=?',(json.dumps(line),m.DATASET))
    with pytest.raises(ValueError,match='SERIES_COVERAGE'):m.publish(mp,p)
    Path(items[0]['raw']['local_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='IDENTITY'):m.publish(mp,p)
