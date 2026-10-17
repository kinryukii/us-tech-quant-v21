"""Strict catalog JSON projection: synthetic sources only, no numeric history."""
import hashlib
import json
from io import BytesIO
from copy import deepcopy
import pandas as pd
import pytest
from apps.demo_console.adapters import stock_history_reader as reader
from scripts.common.json_projection import metadata_fields


def payload():
    return {'data_date':'2026-01-05','status':'READY','model_id':'A2_HGB','model_sha256':reader.base.MODEL_2026_SHA,
        'universe':{'report_path':'SYNTHETIC/universe.json','universe_members_sha256':'a'*64,'universe_id':'pool','quarter':'2025Q4'},
        'coverage':{'mapped_count':1,'unused_count':999}, 'currency':'SYNTHETIC_UNUSED',
        'ranked_rows':[{'ticker':'UNREAD','rank':i,'score':i/1000} for i in range(2000)]}


def projected(tmp_path, raw):
    path=tmp_path/'report.json';path.write_bytes(raw)
    return reader._catalog_report_metadata(path,hashlib.sha256(raw).hexdigest())


def consume(row, monkeypatch):
    reader._day(row['data_date'])
    if row.get('status')!='READY' or row.get('model_id')!='A2_HGB' or row.get('model_sha256')!=reader.base.MODEL_2026_SHA:
        return 'SKIPPED'
    monkeypatch.setattr(reader,'_frame',lambda *args:pd.DataFrame([{'ticker':'SYN','security_id':'ID'}]))
    return reader._daily_pool_members(row)[0].ticker.tolist()


def test_projection_matches_original_metadata_with_large_opaque_arrays_and_unicode(tmp_path):
    value=payload();value['opaque']='公司 α 日本語';raw=json.dumps(value,ensure_ascii=False).encode()
    old=metadata_fields(BytesIO(raw),{'data_date','status','model_id','model_sha256','universe','coverage'})
    old['coverage']={'mapped_count':old['coverage']['mapped_count']}
    assert projected(tmp_path,raw)==old
    assert set(projected(tmp_path,raw))=={'data_date','status','model_id','model_sha256','universe','coverage'}


@pytest.mark.parametrize('fragment',[
    '"data_date":"2026-01-05","data_date":"2026-01-06"',
    '"universe":{"universe_id":"a","universe_id":"b"}',
    '"coverage":{"mapped_count":1,"mapped_count":2}',
])
def test_selected_metadata_duplicates_reject(tmp_path,fragment):
    with pytest.raises(ValueError):projected(tmp_path,('{'+fragment+'}').encode())


@pytest.mark.parametrize('raw',[b'{}'+bytes([10])+b'{}',b'[]',b'null',b'{"data_date":true}',b'{"coverage":{"mapped_count":"one"}}',
    b'{"universe":"not-an-object"}',b'{"data_date":"x"'])
def test_invalid_type_structure_or_multiple_records_never_qualify(tmp_path,monkeypatch,raw):
    with pytest.raises((ValueError,TypeError,KeyError)):consume(projected(tmp_path,raw),monkeypatch)


@pytest.mark.parametrize('field,value',[('data_date',None),('data_date','2026-1-05'),('data_date','2026-01-05T00:00:00Z'),
    ('universe',None),('coverage',None),('coverage',{'mapped_count':None}),('coverage',{}),('coverage',{'mapped_count':2})])
def test_missing_null_and_noncanonical_date_keep_original_consumer_guard(tmp_path,monkeypatch,field,value):
    item=payload();item[field]=value
    with pytest.raises((ValueError,TypeError,KeyError)):consume(projected(tmp_path,json.dumps(item).encode()),monkeypatch)


def test_missing_required_date_and_unknown_duplicate_or_units_do_not_authorize_data(tmp_path,monkeypatch):
    item=payload();del item['data_date']
    with pytest.raises((ValueError,TypeError,KeyError)):consume(projected(tmp_path,json.dumps(item).encode()),monkeypatch)
    raw=json.dumps(payload()).encode();raw=raw[:-1]+b',"unknown":1,"unknown":2,"units":"not-price-data"}'
    # Unknown-field duplicates may be rejected more strictly by Arrow; they can
    # never replace any selected metadata or become a price/score object.
    try: row=projected(tmp_path,raw)
    except ValueError:return
    assert 'unknown' not in row and 'units' not in row and consume(row,monkeypatch)==['SYN']


def test_sha_and_changed_during_read_reject(tmp_path,monkeypatch):
    import pyarrow.json as arrow_json
    raw=json.dumps(payload()).encode();path=tmp_path/'report.json';path.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='HASH'):reader._catalog_report_metadata(path,'f'*64)
    original=arrow_json.read_json
    def changed(*args,**kwargs):
        result=original(*args,**kwargs);path.write_bytes(raw+b' ');return result
    monkeypatch.setattr(arrow_json,'read_json',changed)
    with pytest.raises(ValueError,match='CHANGED'):reader._catalog_report_metadata(path,digest)


def input_payload():
    value=payload();value.update(generated_at='2026-01-05T20:45:00+00:00',
        selected_hgb_features={'path':'SYNTHETIC/features.parquet','sha256':'f'*64})
    value['coverage']['eligible_count']=40
    return value


def test_input_binding_projection_matches_four_original_metadata_reads(tmp_path):
    raw=json.dumps(input_payload(),ensure_ascii=False).encode();path=tmp_path/'binding.json';path.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    old=reader._input_metadata(path,digest,{'status','data_date','model_id','model_sha256','generated_at'})
    for name,fields in [('universe',{'universe_id','quarter','universe_members_sha256'}),
            ('coverage',{'eligible_count'}),('selected_hgb_features',{'path','sha256'})]:
        old[name]=reader._input_metadata(path,digest,fields,branch=(name,))
    assert reader._catalog_report_metadata(path,digest,input_binding=True)==old


@pytest.mark.parametrize('fragment',[
    '"generated_at":"2026-01-05T20:45:00Z","generated_at":"2026-01-06T20:45:00Z"',
    '"coverage":{"eligible_count":40,"eligible_count":41}',
    '"selected_hgb_features":{"path":"a","path":"b","sha256":"hash"}',
])
def test_input_binding_duplicate_selected_fields_reject(tmp_path,fragment):
    raw=('{'+fragment+'}').encode();path=tmp_path/'duplicate.json';path.write_bytes(raw)
    with pytest.raises(ValueError):reader._catalog_report_metadata(path,hashlib.sha256(raw).hexdigest(),input_binding=True)


@pytest.mark.parametrize('field,value',[
    ('universe',None),('coverage',None),('selected_hgb_features',None),
    ('coverage',{'eligible_count':'forty'}),('selected_hgb_features',{'path':True,'sha256':'a'*64}),
])
def test_input_binding_null_or_wrong_type_rejects_before_acceptance(tmp_path,field,value):
    report=input_payload();report[field]=value;raw=json.dumps(report).encode();path=tmp_path/'bad.json';path.write_bytes(raw)
    with pytest.raises((ValueError,TypeError)):
        reader._catalog_report_metadata(path,hashlib.sha256(raw).hexdigest(),input_binding=True)
