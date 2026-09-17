import importlib.util
from decimal import Decimal
import json
import math
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs,urlparse
import sys

import pyarrow.parquet as pq
import pytest

sys.path.insert(0,'D:/us-tech-quant')
if Path(__file__).with_name('refresh_fiscaldata.py').exists():
    spec=importlib.util.spec_from_file_location('fiscaldata_synthetic',Path(__file__).with_name('refresh_fiscaldata.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
else:
    from scripts.storage import refresh_fiscaldata as m


def payload(rows=None,number=1,size=2,total=3):
    rows=rows or [{'record_date':'2026-08-31','src_line_nbr':str(i),'security_desc':'Bills',
        'security_type_desc':'Marketable','avg_interest_rate_amt':'3.788'} for i in range((number-1)*size+1,min(number*size,total)+1)]
    pages=math.ceil(total/size)
    fields=list(rows[0]); types={key:'PERCENTAGE' if key=='avg_interest_rate_amt' else 'DATE' if key=='record_date' else 'INTEGER' if key=='src_line_nbr' else 'STRING' for key in fields}
    def link(page):return None if page is None else '&page%5Bnumber%5D='+str(page)+'&page%5Bsize%5D='+str(size)
    return {'data':rows,'meta':{'count':len(rows),'total-count':total,'total-pages':pages,'labels':{key:key for key in fields},
        'dataTypes':types,'dataFormats':{key:'10.2%' if key=='avg_interest_rate_amt' else 'String' for key in fields}},
        'links':{'self':link(number),'first':link(1),'last':link(pages),'prev':link(number-1 if number>1 else None),'next':link(number+1 if number<pages else None)}}


def test_original_tokens_decimal_precision_and_missing_kinds():
    rows=[{'record_date':'2026-08-31','src_line_nbr':str(i),'avg_interest_rate_amt':value} for i,value in enumerate(['12345678901234567890.123456789012','null',None,''],1)]
    receipt={'raw':{'sha256':'abc','source_reference':m.BASE+m.TABLES['avg_interest_rates'],'retrieval_timestamp_utc':'2026-09-15T00:00:00Z'}}
    out=m.normalize_rows(rows,receipt,'avg_interest_rates',1).to_pylist()
    assert [row['avg_interest_rate_amt'] for row in out]==[row['avg_interest_rate_amt'] for row in rows]
    assert out[0]['avg_interest_rate_amt_value']==Decimal(rows[0]['avg_interest_rate_amt'])
    assert [row['avg_interest_rate_amt_missing_kind'] for row in out]==[None,'SOURCE_NULL_TOKEN','JSON_NULL','EMPTY_STRING']
    assert all(row['available_at_utc'] is None and row['source_unit']=='PERCENT_NOT_FRACTION' for row in out)


@pytest.mark.parametrize('change',['total','next','count','numeric','field','unit','date','duplicate'])
def test_page_fail_closed(change):
    data=payload()
    if change=='total':data['meta']['total-pages']=9
    if change=='next':data['links']['next']='https://evil.invalid/data'
    if change=='count':data['meta']['count']=1
    if change=='numeric':data['data'][0]['avg_interest_rate_amt']='NaN'
    if change=='field':del data['data'][0]['src_line_nbr']
    if change=='unit':data['meta']['dataTypes']['avg_interest_rate_amt']='CURRENCY'
    if change=='date':data['data'][0]['record_date']='2026-09-16'
    if change=='duplicate':data['data'][1]['src_line_nbr']='1'
    with pytest.raises(ValueError):m.parse_page(json.dumps(data).encode(),'avg_interest_rates','2026-09-15',1,2)


def test_metadata_total_or_dictionary_change_rejected():
    body=payload();_,signature,_=m.parse_page(json.dumps(body).encode(),'avg_interest_rates','2026-09-15',1,2)
    body['meta']['labels']['src_line_nbr']='changed'
    with pytest.raises(ValueError,match='METADATA_OR_TOTAL'):m.parse_page(json.dumps(body).encode(),'avg_interest_rates','2026-09-15',1,2,expected_meta=signature)
    with pytest.raises(ValueError,match='DUPLICATE_JSON'):m.load_json(b'{"data":1,"data":2}')


class Response:
    def __init__(self,body,status=200):self.body=body;self.status_code=status;self.read=False;self.closed=False
    def iter_content(self,size):self.read=True;yield self.body
    def close(self):self.closed=True


def paths(tmp_path):
    out=SimpleNamespace(repo_root=Path('D:/us-tech-quant'),results_root=tmp_path/'results',cache_root=tmp_path/'cache',data_root=tmp_path/'data')
    for path in (out.results_root,out.cache_root,out.data_root):path.mkdir()
    return out


@pytest.mark.parametrize('status',[403,429])
def test_denied_unit_never_retried_and_error_body_not_read(tmp_path,monkeypatch,status):
    monkeypatch.setattr(m.time,'sleep',lambda _:None);p=paths(tmp_path);calls=[];response=Response(b'not read',status)
    def request(*a,**kw):calls.append(a);assert kw['allow_redirects'] is False;return response
    url=m.page_url('avg_interest_rates','2026-09-15')
    with pytest.raises(ValueError,match='HTTP_'):m.fetch(p,'test','avg_interest_rates',url,request=request)
    with pytest.raises(ValueError,match='NO_RETRY'):m.fetch(p,'test','avg_interest_rates',url,request=request)
    with pytest.raises(ValueError,match='UNIT_STOPPED'):m.fetch(p,'test','avg_interest_rates',m.page_url('avg_interest_rates','2026-09-15',2),request=request)
    assert len(calls)==1 and not response.read and response.closed


def test_endpoint_and_raw_budget_are_bounded(tmp_path,monkeypatch):
    p=paths(tmp_path);monkeypatch.setattr(m.time,'sleep',lambda _:None);monkeypatch.setattr(m,'PAGE_BUDGET',1)
    with pytest.raises(ValueError,match='ENDPOINT'):m.fetch(p,'test','avg_interest_rates','https://example.invalid/')
    with pytest.raises(ValueError,match='RAW_BUDGET'):m.fetch(p,'test','avg_interest_rates',m.page_url('avg_interest_rates','2026-09-15'),request=lambda *a,**k:Response(b'{}'))


def test_raw_budget_includes_another_table_and_refuses_before_network(tmp_path,monkeypatch):
    p=paths(tmp_path);monkeypatch.setattr(m,'RAW_BUDGET',3)
    other=p.cache_root/'official_research_intake/test/fiscaldata/operating_cash_balance/raw'
    other.mkdir(parents=True);(other/'existing.source').write_bytes(b'abc')
    def forbidden(*a,**k):raise AssertionError('network exceeds shared raw budget')
    with pytest.raises(ValueError,match='RAW_BUDGET'):
        m.fetch(p,'test','avg_interest_rates',m.page_url('avg_interest_rates','2026-09-15'),request=forbidden)


def test_full_pagination_latest_period_across_pages_and_offline_resume(tmp_path,monkeypatch):
    p=paths(tmp_path);monkeypatch.setattr(m,'PAGE_SIZE',2);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=25*1024**3));called=[]
    def request(url,**kwargs):
        called.append(url);query=parse_qs(urlparse(url).query);size=int(query['page[size]'][0]);number=int(query['page[number]'][0])
        return Response(json.dumps(payload(number=number,size=size)).encode())
    result=m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=request)
    frame=pq.read_table(result['outputs'][0]['path']).to_pylist()
    assert len(called)==3 and len(frame)==3 and result['latest_check_matches_all_fields']
    assert all(row['available_at_utc'] is None for row in frame)
    assert not result['catalog_written'] and result['outputs'][0]['max_date']=='2026-08-31'
    def forbidden(*a,**k):raise AssertionError('network on completed replay')
    assert m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=forbidden)==result
    raw=Path(result['inputs'][0]['raw']['local_path']);sidecar=raw.with_suffix('.json')
    value=json.loads(sidecar.read_bytes());value['source_reference']='wrong';sidecar.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='SIDECAR'):m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=forbidden)


def interrupted_table(tmp_path,monkeypatch):
    p=paths(tmp_path);monkeypatch.setattr(m,'PAGE_SIZE',2);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=25*1024**3))
    def request(url,**kwargs):
        number=int(parse_qs(urlparse(url).query)['page[number]'][0])
        if number==2:raise m.requests.exceptions.ReadTimeout('unprinted transport details')
        return Response(json.dumps(payload()).encode())
    with pytest.raises(ValueError,match='NETWORK_OR_RESPONSE'):
        m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=request)
    root=p.results_root/'official_research_intake/test/fiscaldata/avg_interest_rates'
    parents={path:path.read_bytes() for path in [root/'request_plan.json',root/'failure.json',*list((root/'requests').glob('*.json'))]}
    return p,root,parents


def test_one_timeout_recovery_preserves_parents_and_default_replays(tmp_path,monkeypatch):
    p,root,parents=interrupted_table(tmp_path,monkeypatch);calls=[]
    plan=m.load_json((root/'request_plan.json').read_bytes());plan['source_code_sha256']='0'*64
    failure=m.load_json((root/'failure.json').read_bytes());failure['contract']=plan
    (root/'request_plan.json').write_text(json.dumps(plan),encoding='utf-8')
    (root/'failure.json').write_text(json.dumps(failure),encoding='utf-8')
    parents={path:path.read_bytes() for path in parents}
    def request(url,**kwargs):
        calls.append(url);assert kwargs['timeout']==(10,90) and kwargs['allow_redirects'] is False
        query=parse_qs(urlparse(url).query)
        return Response(json.dumps(payload(number=int(query['page[number]'][0]),size=int(query['page[size]'][0]))).encode())
    out=m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=request,recover_read_timeout=True)
    assert len(calls)==2 and out['outputs'][0]['row_count']==3
    assert out['contract']['recovery']['plan']['sha256']==m.sha256(root/'request_plan.json')
    assert out['contract']['recovery']['original_source_code_sha256']=='0'*64
    assert out['contract']['source_code_sha256']==m.sha256(m.__file__)
    assert all(path.read_bytes()==body for path,body in parents.items())
    def forbidden(*a,**kw):raise AssertionError('second network attempt')
    assert m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=forbidden)==out
    parent=root/'failure.json';parent.write_bytes(parent.read_bytes()+b' ')
    with pytest.raises(ValueError,match='STARTED_IDENTITY'):
        m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=forbidden)


def test_failed_timeout_recovery_cannot_repeat(tmp_path,monkeypatch):
    p,root,parents=interrupted_table(tmp_path,monkeypatch);calls=[]
    def request(*a,**kw):calls.append(a);raise m.requests.exceptions.ReadTimeout('unprinted details')
    with pytest.raises(ValueError,match='NETWORK_OR_RESPONSE'):
        m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=request,recover_read_timeout=True)
    for flag in (False,True):
        with pytest.raises(ValueError,match='ALREADY_ATTEMPTED'):
            m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=request,recover_read_timeout=flag)
    assert len(calls)==1 and all(path.read_bytes()==body for path,body in parents.items())


@pytest.mark.parametrize('http,kind',[(401,'ReadTimeout'),(403,'ReadTimeout'),(429,'ReadTimeout'),(None,'ConnectTimeout'),(None,None)])
def test_recovery_rejects_http_denial_or_unproved_timeout(tmp_path,monkeypatch,http,kind):
    p,root,_=interrupted_table(tmp_path,monkeypatch)
    failed=next(path for path in (root/'requests').glob('*.json') if m.load_json(path.read_bytes())['status']=='FAILED')
    value=m.load_json(failed.read_bytes());value['http_status']=http;value['exception_type']=kind
    failed.write_text(json.dumps(value),encoding='utf-8')
    def forbidden(*a,**kw):raise AssertionError('ineligible request')
    with pytest.raises(ValueError,match='NOT_READTIMEOUT'):
        m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True,request=forbidden,recover_read_timeout=True)
    assert not (root/'readtimeout_recovery_started.json').exists()


def test_recovery_requires_original_scope_and_default_failure_stays_closed(tmp_path,monkeypatch):
    p,root,_=interrupted_table(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='PREVIOUS_UNIT_FAILURE'):
        m.run_table(p,'test','avg_interest_rates','2026-09-15',execute=True)
    with pytest.raises(ValueError,match='PARENT_SCOPE'):
        m.run_table(p,'test','avg_interest_rates','2026-09-14',execute=True,recover_read_timeout=True)


def auction_row(day='2026-09-14',cusip='912797UD7',completed=True):
    row={key:'null' for key in m.VALUE_FIELDS['auctions_query']}
    row.update(record_date='2026-09-17',auction_date=day,issue_date='2026-09-17',cusip=cusip,
        announcemt_date='2026-09-10',reopening='Yes',security_type='Bill',security_term='26-Week',
        pdf_filenm_comp_results='R_20260914_1.pdf' if completed else 'null',
        offering_amt='79000000000',price_per100='99-1/4',soma_holdings='1200000000')
    if completed: row.update(total_accepted='86053185400',total_tendered='223857560400',bid_to_cover_ratio='2.740000')
    return row


def auction_payload(rows,number=1,size=2,total=None):
    body=payload(rows=rows,number=number,size=size,total=total or len(rows))
    for key in body['meta']['labels']:
        kind='CURRENCY0' if key=='offering_amt' else 'NUMBER' if key in m.VALUE_FIELDS['auctions_query'] else 'DATE' if key in {'record_date','auction_date','issue_date','announcemt_date'} else 'STRING'
        body['meta']['dataTypes'][key]=kind;body['meta']['dataFormats'][key]=kind
    return body


def test_auction_dates_reopening_announcements_and_source_units():
    rows=[auction_row(),auction_row(day='2026-09-15',completed=False)]
    body=auction_payload(rows)
    parsed,_,keys=m.parse_page(json.dumps(body).encode(),'auctions_query','2026-09-15',1,2)
    assert keys==[('2026-09-14','912797UD7','2026-09-17'),('2026-09-15','912797UD7','2026-09-17')]
    receipt={'raw':{'sha256':'abc','source_reference':m.BASE+m.TABLES['auctions_query'],'retrieval_timestamp_utc':'2026-09-14T17:00:00Z'}}
    out=m.normalize_rows(parsed['data'],receipt,'auctions_query',1).to_pylist()
    assert out[0]['date']=='2026-09-14' and out[0]['record_date']=='2026-09-17'
    assert out[0]['bid_to_cover_ratio_value']==Decimal('2.740000') and out[0]['offering_amt_value']==Decimal('79000000000')
    assert out[0]['price_per100']=='99-1/4' and out[0]['reopening']=='Yes'
    assert [row['auction_record_state'] for row in out]==['RESULTS_PRESENT','ANNOUNCED_NO_RESULTS_IN_SOURCE']
    assert out[1]['auction_after_observed_new_york_date']=='Yes'
    assert all(row['available_at_utc'] is None and row['results_available_at_utc'] is None for row in out)


@pytest.mark.parametrize('change',['duplicate','announced_after','missing_cusip','number_type'])
def test_auction_identity_and_metadata_fail_closed(change):
    body=auction_payload([auction_row(),auction_row(day='2026-09-15',completed=False)])
    if change=='duplicate':body['data'][1]=dict(body['data'][0])
    if change=='announced_after':body['data'][0]['announcemt_date']='2026-09-15'
    if change=='missing_cusip':body['data'][0]['cusip']='null'
    if change=='number_type':body['meta']['dataTypes']['total_accepted']='STRING'
    with pytest.raises(ValueError):m.parse_page(json.dumps(body).encode(),'auctions_query','2026-09-15',1,2)


def test_future_auction_cannot_claim_results_and_zero_is_not_completed():
    row=auction_row(day='2026-09-15');receipt={'raw':{'sha256':'abc','source_reference':'official','retrieval_timestamp_utc':'2026-09-15T00:01:00Z'}}
    with pytest.raises(ValueError,match='RESULTS_BEFORE_AUCTION'):
        m.normalize_rows([row],receipt,'auctions_query',1)
    row['total_accepted']='0'
    assert m.auction_state(row)=='PARTIAL_OR_NONPOSITIVE_RESULTS'


def test_auction_pagination_has_separate_latest_completed_and_offline_replay(tmp_path,monkeypatch):
    p=paths(tmp_path);monkeypatch.setattr(m,'table_page_size',lambda _:2);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=25*1024**3))
    rows=[auction_row(day='2026-09-11',cusip='912797AA1'),auction_row(),auction_row(day='2026-09-15',completed=False)]
    calls=[]
    def request(url,**kw):
        calls.append(url);q=parse_qs(urlparse(url).query);size=int(q['page[size]'][0]);number=int(q['page[number]'][0])
        selected=rows[:2] if 'total_accepted:gt:0' in q['filter'][0] else rows
        if q['sort'][0].startswith('-'):selected=sorted(selected,key=lambda x:x['auction_date'],reverse=True)
        return Response(json.dumps(auction_payload(selected[(number-1)*size:number*size],number,size,len(selected))).encode())
    out=m.run_table(p,'auction_test','auctions_query','2026-09-15',execute=True,request=request)
    assert len(calls)==4 and out['auction_state_ranges']['RESULTS_PRESENT']['rows']==2
    assert out['outputs'][0]['max_date']=='2026-09-15' and out['auction_state_ranges']['RESULTS_PRESENT']['max_date']=='2026-09-14'
    assert out['latest_completed_check_matches_all_fields'] and out['numeric_field_units']['bid_to_cover_ratio']=='DIMENSIONLESS_RATIO'
    assert out['source_field_mapping']['price_per100']['numeric_conversion']=='RAW_SOURCE_TEXT_UNCHANGED'
    def forbidden(*a,**kw):raise AssertionError('network on completed auction replay')
    assert m.run_table(p,'auction_test','auctions_query','2026-09-15',execute=True,request=forbidden)==out


def debt_metadata_extras(body):
    for name in m.AUCTION_UNUSED_METADATA:
        for key in ('labels','dataTypes','dataFormats'):body['meta'][key][name]='UNUSED_DEBT_METADATA'
    return body


@pytest.mark.parametrize('mutation',['none','extra_unknown','actual_row_column','changed_existing','changed_total'])
def test_only_proven_unused_auction_dictionary_entries_can_be_excluded(mutation):
    body=auction_payload([auction_row()]);_,signature,_=m.parse_page(json.dumps(body).encode(),'auctions_query','2026-09-15',1,2)
    debt_metadata_extras(body)
    if mutation=='extra_unknown':
        for key in ('labels','dataTypes','dataFormats'):body['meta'][key]['unknown_field']='unknown'
    if mutation=='actual_row_column':body['data'][0]['debt_held_public_amt']='1'
    if mutation=='changed_existing':body['meta']['labels']['cusip']='changed'
    if mutation=='changed_total':body['meta']['total-count']=2
    if mutation=='none':
        parsed,effective,_=m.parse_page(json.dumps(body).encode(),'auctions_query','2026-09-15',1,2,expected_meta=signature)
        assert effective==signature and parsed['meta']==body['meta']
        assert set(parsed['unused_metadata_fields']['labels'])==m.AUCTION_UNUSED_METADATA
    else:
        with pytest.raises(ValueError):m.parse_page(json.dumps(body).encode(),'auctions_query','2026-09-15',1,2,expected_meta=signature)


def test_metadata_revalidation_reuses_http200_pages_and_preserves_parent(tmp_path,monkeypatch):
    p=paths(tmp_path);monkeypatch.setattr(m,'table_page_size',lambda _:2);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    monkeypatch.setattr(m.shutil,'disk_usage',lambda _:SimpleNamespace(free=25*1024**3))
    rows=[auction_row(day='2026-09-11',cusip='912797AA1'),auction_row(),auction_row(day='2026-09-15',completed=False)]
    calls=[]
    def request(url,**kw):
        calls.append(url);q=parse_qs(urlparse(url).query);size=int(q['page[size]'][0]);number=int(q['page[number]'][0])
        selected=rows[:2] if 'total_accepted:gt:0' in q['filter'][0] else rows
        if q['sort'][0].startswith('-'):selected=list(reversed(selected))
        body=auction_payload(selected[(number-1)*size:number*size],number,size,len(selected))
        if number==2:debt_metadata_extras(body)
        return Response(json.dumps(body).encode())
    original=m.parse_page
    def previous_parser(content,table,asof,number,size,**kw):
        if number==2:raise ValueError('FISCALDATA_METADATA_OR_TOTAL_CHANGED')
        return original(content,table,asof,number,size,**kw)
    monkeypatch.setattr(m,'parse_page',previous_parser)
    with pytest.raises(ValueError,match='METADATA_OR_TOTAL'):
        m.run_table(p,'meta_test','auctions_query','2026-09-15',execute=True,request=request)
    monkeypatch.setattr(m,'parse_page',original)
    root=p.results_root/'official_research_intake/meta_test/fiscaldata/auctions_query'
    preserved={path:path.read_bytes() for path in [root/'request_plan.json',root/'failure.json',*list((root/'requests').glob('*.json'))]}
    out=m.run_table(p,'meta_test','auctions_query','2026-09-15',execute=True,request=request,revalidate_auction_metadata=True)
    assert len(calls)==4 and all(path.read_bytes()==body for path,body in preserved.items())
    assert len(out['source_page_metadata'])==2
    assert set(out['source_page_metadata'][1]['unused_metadata_fields']['labels'])==m.AUCTION_UNUSED_METADATA
    assert out['contract']['recovery']['mode']=='AUCTION_UNUSED_DICTIONARY_ONLY_REVALIDATION'
    def forbidden(*a,**kw):raise AssertionError('network during completed replay')
    assert m.run_table(p,'meta_test','auctions_query','2026-09-15',execute=True,request=forbidden)==out
