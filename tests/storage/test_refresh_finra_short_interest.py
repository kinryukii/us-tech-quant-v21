"""Synthetic FINRA raw identity, source semantics and bounded acquisition tests."""
from decimal import Decimal
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow.parquet as pq
import pytest

from scripts.common.storage_paths import resolve
from scripts.storage import refresh_finra_short_interest as m


def raw_file(**changes):
    row = dict(zip(m.HEADER, ['20260814', 'SYN/A', 'Synthetic Issue', 'R', 'NNM', '100', '50', '',
                             '20', '5.00', '', '100.00', '50', '2026-08-14']))
    row.update(changes)
    return ('|'.join(m.HEADER) + '\n' + '|'.join(row[k] for k in m.HEADER) + '\n').encode()


def test_source_symbols_flags_and_large_precision_preserved():
    frame = m.parse_file(raw_file(currentShortPositionQuantity='999999999999999999.123456', stockSplitFlag='S', revisionFlag='R'), '2026-08-14', '2026-09-14')
    assert frame.iloc[0].current_short_interest_shares == Decimal('999999999999999999.123456')
    assert frame.iloc[0].provider_symbol == 'SYN/A'
    assert frame.iloc[0].stockSplitFlag == 'S' and frame.iloc[0].revisionFlag == 'R'


def test_literal_unescaped_quotes_are_retained_in_pipe_source():
    frame = m.parse_file(raw_file(issueName='"Synthetic Issue and its Class "A'), '2026-08-14', '2026-09-14')
    assert frame.iloc[0].issueName == '"Synthetic Issue and its Class "A'


@pytest.mark.parametrize('change', [
    {'currentShortPositionQuantity': '-1'}, {'currentShortPositionQuantity': '1.1234567'},
    {'averageDailyVolumeQuantity': 'NaN'}, {'changePercent': 'Infinity'}, {'stockSplitFlag': 'X'},
    {'revisionFlag': 'Y'}, {'settlementDate': '2026-08-31'}, {'accountingYearMonthNumber': '20260831'},
])
def test_invalid_source_rejected(change):
    with pytest.raises(ValueError): m.parse_file(raw_file(**change), '2026-08-14', '2026-09-14')


def test_wrong_header_truncated_row_and_duplicate_symbol_rejected():
    raw = raw_file()
    for bad in [raw.replace(b'accountingYearMonthNumber', b'legacyField'), raw.rsplit(b'|', 1)[0], raw + raw.split(b'\n')[1] + b'\n']:
        with pytest.raises(ValueError): m.parse_file(bad, '2026-08-14', '2026-09-14')


@pytest.mark.parametrize('days,average,status', [('999.99', '0', 'SOURCE_999_99_SENTINEL_OR_CAP_NOT_EXACT'),
    ('999.99', '1', 'SOURCE_999_99_SENTINEL_OR_CAP_NOT_EXACT'), ('0', '0', 'UNDEFINED_ZERO_AVERAGE_VOLUME')])
def test_days_sentinel_and_zero_denominator_are_not_exact_values(days, average, status):
    frame = m.parse_file(raw_file(daysToCoverQuantity=days, averageDailyVolumeQuantity=average), '2026-08-14', '2026-09-14')
    assert frame.iloc[0].days_to_cover_value is None
    assert frame.iloc[0].daysToCoverQuantity == days and frame.iloc[0].days_to_cover_status == status


def test_floor_and_otcbb_source_scope():
    frame = m.parse_file(raw_file(daysToCoverQuantity='1.00', marketClassCode='OTCBB', previousShortPositionQuantity='0'), '2026-08-14', '2026-09-14')
    assert frame.iloc[0].days_to_cover_status == 'SOURCE_FLOORED_AT_ONE'
    assert frame.iloc[0].market_scope == 'OTC'
    assert frame.iloc[0].change_percent_status == 'PRIOR_POSITION_ZERO_SOURCE_DEFAULT_NOT_ORDINARY_PERCENT_CHANGE'
    assert frame.iloc[0].changePercent == '100.00'


def index(days=('20260814',)):
    return ''.join('<a href="https://cdn.finra.org/equity/otcmarket/biweekly/shrt'+d+'.csv">file</a>' for d in days).encode()


def schedule():
    return b'<h2>2026 Short Interest Reporting Dates</h2><table><tr><td>August 14 (Friday)</td><td>August 18</td><td>August 25 (Tuesday)</td></tr><tr><td>August 31 (Monday)</td><td>September 2</td><td>September 10 (Thursday)</td></tr><tr><td>September 15</td><td>September 17</td><td>September 24</td></tr></table>'


def test_index_limits_scope_and_excludes_nonofficial_mock_urls():
    raw = index() + b'<a href="https://example.com/shrt20260831.csv">bad</a><a href="https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterestMock">mock</a>'
    assert list(m.parse_index(raw, '2020-01-01', '2026-09-14')) == ['2026-08-14']
    assert m.parse_schedule(schedule(), '2026-09-14') == {'2026-08-14': '2026-08-25', '2026-08-31': '2026-09-10'}


def fixture_paths(tmp_path):
    return resolve(repo_root=tmp_path/'repo', **{key: tmp_path/key for key in ['data_root', 'cache_root', 'results_root', 'daily_root', 'backtest_root', 'envs_root']})


def archive(paths, url, raw):
    base = paths.cache_root/'official_research_intake/test/finra_short_interest/raw/finra_short_interest'
    base.mkdir(parents=True, exist_ok=True)
    key = m.hashlib.sha256(url.encode()).hexdigest(); path = base/(key+'.source'); path.write_bytes(raw)
    meta = {'event_family': m.FAMILY, 'source': 'FINRA_OFFICIAL', 'source_reference': url,
            'document_kind': 'TEST', 'sha256': m.sha256(path), 'retrieval_timestamp_utc': '2026-09-14T01:00:00Z'}
    (base/(key+'.json')).write_text(json.dumps(meta), encoding='utf-8')
    return {**meta, 'local_path': str(path), 'status': 'CACHED', 'failure_class': None, 'error': None}


def test_offline_intake_preserves_gap_null_availability_and_immutable_vintage(tmp_path, monkeypatch):
    paths = fixture_paths(tmp_path)
    for url, raw in [(m.INDEX_URL,index()), (m.SCHEDULE_URL,schedule()),
                     ('https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260814.csv',raw_file())]: archive(paths,url,raw)
    monkeypatch.setattr(m, 'archive_module', lambda repo: None)
    result = m.run(paths, 'test', as_of='2026-09-14')
    assert result['status'] == 'PARTIAL_SOURCE_COVERAGE' and result['missing_settlement_dates'] == ['2026-08-31']
    assert not result['latest_complete'] and not result['historical_pit_certified'] and not result['catalog_written']
    frame = pd.read_parquet(result['outputs'][0]['path'])
    assert frame.available_at_utc.isna().all() and frame.scheduled_publication_date.tolist() == ['2026-08-25']
    assert pq.read_schema(result['outputs'][0]['path']).field('current_short_interest_shares').type == m.pa.decimal128(24,6)
    from scripts.storage.storage_r2a import DataStore, CATALOG_SCHEMA_SQL, CATALOG_ROLE, CATALOG_SCHEMA_VERSION
    from scripts.storage.build_data_catalog import register_file
    catalog=paths.cache_root/'derived/data_catalog/catalog.sqlite3';catalog.parent.mkdir(parents=True)
    conn=sqlite3.connect(catalog)
    try:
        conn.executescript(CATALOG_SCHEMA_SQL)
        conn.executemany('INSERT INTO catalog_metadata VALUES (?,?)',[('schema_version',CATALOG_SCHEMA_VERSION),('catalog_role',CATALOG_ROLE)])
        output=result['outputs'][0]
        register_file(conn,m.DATASET,'','',output['path'],output['row_count'],output['min_date'],output['max_date'],'FINRA_OFFICIAL',{'date_column':'date'})
        conn.commit()
    finally: conn.close()
    assert len(DataStore(paths).read(m.DATASET,start_date='2026-08-01',end_date='2026-08-31'))==1
    assert DataStore(paths).read(m.DATASET,end_date='2025-12-31').empty
    assert m.run(paths, 'test', as_of='2026-09-14') == result
    with pytest.raises(ValueError): m.run(paths, 'test', as_of='2026-09-13')
    Path(result['outputs'][0]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='OUTPUT_IDENTITY'): m.run(paths, 'test', as_of='2026-09-14')


def test_raw_hash_and_external_root_required(tmp_path):
    paths = fixture_paths(tmp_path); record = archive(paths, m.INDEX_URL, index())
    record['sha256'] = 'bad'
    with pytest.raises(ValueError,match='RAW_PATH_HASH'): m.verified_raw(record, paths)


def test_download_never_guesses_missing_latest_and_stops_rate_limit(tmp_path, monkeypatch):
    paths = fixture_paths(tmp_path)
    archive(paths,m.INDEX_URL,index(('20260814','20260731','20260715'))); archive(paths,m.SCHEDULE_URL,schedule())
    archive(paths,'https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260814.csv',raw_file())
    called=[]
    from dataclasses import make_dataclass
    Failure = make_dataclass('Failure',[('source_reference',str),('status',str),('error',str),('local_path',object),('sha256',object)])
    def acquire(url,*args):
        called.append(url); return Failure(url,'FAILED','HTTPError: HTTP Error 429: Too Many Requests',None,None)
    monkeypatch.setattr(m,'archive_module',lambda repo: SimpleNamespace(acquire_url=acquire))
    monkeypatch.setattr(m.time,'sleep',lambda delay: None)
    result=m.run(paths,'test',as_of='2026-09-14',download=True)
    assert called==['https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260731.csv']
    assert result['latest_acquired_settlement']=='2026-08-14'


def api_metadata_bytes(partitions=None, **changes):
    value = {'datasetGroup':'OTCMARKET','datasetName':'CONSOLIDATEDSHORTINTEREST',
        'partitionFields':['settlementDate'] if partitions is None else partitions,
        'fields':[{'name':name,'type':'Number' if name in set(m.NUMBERS)|{'accountingYearMonthNumber'} else 'Date' if name=='settlementDate' else 'String'} for name in m.HEADER]}
    value.update(changes)
    return json.dumps(value).encode()


def api_page(symbols=('AAA',), **changes):
    rows=[]
    for symbol in symbols:
        row=dict(zip(m.HEADER,raw_file().decode().splitlines()[1].split('|')))
        row.update(accountingYearMonthNumber='20260831',settlementDate='2026-08-31',symbolCode=symbol,
                   stockSplitFlag=None,revisionFlag=None)
        row.update(changes)
        rows.append('{'+','.join(json.dumps(key)+':'+('null' if value is None else str(value) if key in set(m.NUMBERS)|{'accountingYearMonthNumber'} else json.dumps(value)) for key,value in row.items())+'}')
    return ('['+','.join(rows)+']').encode()


def page_headers(offset, total, returned=1, limit=5000):
    return {'record-total':str(total),'record-offset':str(offset),'record-limit':str(limit),
            'total-records-on-page':str(returned),'record-max-limit':'5000'}


def api_parent(tmp_path, monkeypatch):
    paths=fixture_paths(tmp_path)
    for url,raw in [(m.INDEX_URL,index()),(m.SCHEDULE_URL,schedule()),
                    ('https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260814.csv',raw_file())]: archive(paths,url,raw)
    monkeypatch.setattr(m,'archive_module',lambda repo:None)
    m.run(paths,'test',as_of='2026-09-14')
    parent=paths.results_root/'official_research_intake/test/finra_short_interest/manifest.json'
    return paths,parent


class Response:
    def __init__(self,body,status=200,headers=None):
        self.body=body;self.status_code=status;self.headers=headers or {};self.read=False;self.closed=False
    def iter_content(self,chunk_size):
        self.read=True
        for i in range(0,len(self.body),chunk_size): yield self.body[i:i+chunk_size]
    def close(self): self.closed=True


ENV={'FINRA_API_CLIENT_ID':'synthetic-client-id-never-real','FINRA_API_CLIENT_SECRET':'synthetic-client-secret-never-real'}
TOKEN='synthetic-access-token-never-real'


def token_response():
    return Response(json.dumps({'access_token':TOKEN,'token_type':'Bearer','expires_in':'1800'}).encode())


def test_api_json_retains_null_flags_numeric_lexemes_and_literal_text():
    text='"Class A" | line\nSecond line'
    frame=m.parse_api_file(api_page(issueName=text,currentShortPositionQuantity='999999999999999999.123456',daysToCoverQuantity='999.99'), '2026-08-31','2026-09-14')
    row=frame.iloc[0]
    assert row.issueName==text and row.stockSplitFlag is None and row.revisionFlag is None
    assert row.currentShortPositionQuantity=='999999999999999999.123456'
    assert row.current_short_interest_shares==Decimal('999999999999999999.123456')
    assert row.days_to_cover_value is None


@pytest.mark.parametrize('body',[
    b'[]',b'[{"x":1,"x":2}]',api_page(settlementDate='2026-09-15'),
    api_page(symbolCode=None),api_page(averageDailyVolumeQuantity=None),
    api_page(currentShortPositionQuantity='NaN'),
])
def test_api_wrong_dates_missing_identity_null_numbers_nonfinite_and_duplicate_keys_fail(body):
    with pytest.raises(ValueError):m.parse_api_file(body,'2026-08-31','2026-09-14')


def test_api_metadata_refuses_mock_unknown_fields_and_unfilterable_partition():
    assert m.api_metadata(api_metadata_bytes())==['settlementDate']
    for body in [api_metadata_bytes(datasetName='consolidatedShortInterestMock'),api_metadata_bytes(partitions=['marketClassCode']),api_metadata_bytes(fields=[])]:
        with pytest.raises(ValueError):m.api_metadata(body)
    payload=m.api_request('2026-08-31',3,['settlementDate','accountingYearMonthNumber'])
    assert payload['offset']==3 and payload['sortFields']==['symbolCode'] and len(payload['compareFilters'])==2


@pytest.mark.parametrize('headers',[
    page_headers(2,5),page_headers(0,4),page_headers(0,5,returned=2),page_headers(0,500001),{},
])
def test_api_pagination_rejects_changed_counts_offsets_and_bounds(headers):
    with pytest.raises(ValueError):m.api_page_headers(headers,0,1,5)


def test_api_auth_headers_exact_hosts_memory_only_and_no_error_echo():
    called=[]
    def request(method,url,**kwargs):
        called.append((method,url,kwargs))
        return token_response() if url==m.API_TOKEN_URL else Response(api_metadata_bytes())
    client=m.FinraAPI(environment=ENV,request=request,pause=lambda:None)
    client.get(m.API_METADATA_URL)
    assert called[0][0:2]==('POST',m.API_TOKEN_URL)
    assert called[0][2]['headers']['Authorization'].startswith('Basic ')
    assert called[1][2]['headers']['Authorization']=='Bearer '+TOKEN
    assert all(item[2]['allow_redirects'] is False and item[2]['stream'] for item in called)
    with pytest.raises(m.FinraAPIError,match='ENDPOINT_NOT_ALLOWED'):client.get(m.API_URL+'Mock')
    assert len(called)==2
    client.close();assert client._token is None and client._private==()
    with pytest.raises(m.FinraAPIError,match='ENV_CREDENTIALS_REQUIRED'):m.FinraAPI(environment={})


@pytest.mark.parametrize('status',[301,401,403,429,503])
def test_api_http_refusal_is_once_and_error_body_is_never_read(status):
    response=Response(ENV['FINRA_API_CLIENT_SECRET'].encode(),status=status)
    called=[]
    def request(*args,**kwargs):called.append(args);return response
    client=m.FinraAPI(environment=ENV,request=request,pause=lambda:None)
    with pytest.raises(m.FinraAPIError,match='HTTP_'+str(status)):client.get(m.API_METADATA_URL)
    assert len(called)==1 and not response.read and response.closed
    with pytest.raises(m.FinraAPIError,match='CLIENT_STOPPED'):client.get(m.API_METADATA_URL)
    assert len(called)==1


@pytest.mark.parametrize('status',[401,403,429])
def test_api_bearer_refusal_never_refreshes_token_or_retries(status):
    responses=[token_response(),Response(api_metadata_bytes()),Response(b'private error body',status=status)]
    called=[]
    def request(method,url,**kwargs):called.append(url);return responses.pop(0)
    client=m.FinraAPI(environment=ENV,request=request,pause=lambda:None)
    client.get(m.API_METADATA_URL)
    with pytest.raises(m.FinraAPIError,match='HTTP_'+str(status)):client.get(m.API_URL,m.api_request('2026-08-31',0,['settlementDate']))
    with pytest.raises(m.FinraAPIError,match='CLIENT_STOPPED'):client.get(m.API_URL,m.api_request('2026-08-31',0,['settlementDate']))
    assert called==[m.API_TOKEN_URL,m.API_METADATA_URL,m.API_URL]


def test_api_empty_data_query_rejected_before_authentication():
    called=[]
    def request(*args,**kwargs):called.append(args);raise AssertionError('No request expected')
    client=m.FinraAPI(environment=ENV,request=request,pause=lambda:None)
    with pytest.raises(m.FinraAPIError,match='DATA_QUERY_REQUIRED'):
        client.get(m.API_URL,{})
    assert called==[] and client._token is None


def test_api_success_echo_and_network_exception_are_sanitized():
    client=m.FinraAPI(environment=ENV,request=lambda *a,**k:Response(ENV['FINRA_API_CLIENT_SECRET'].encode()),pause=lambda:None)
    with pytest.raises(m.FinraAPIError,match='CREDENTIAL_ECHO'):client.get(m.API_METADATA_URL)
    def broken(*a,**k):raise RuntimeError(ENV['FINRA_API_CLIENT_SECRET'])
    client=m.FinraAPI(environment=ENV,request=broken,pause=lambda:None)
    with pytest.raises(m.FinraAPIError) as caught:client.get(m.API_METADATA_URL)
    assert str(caught.value)=='FINRA_API_NETWORK_OR_RESPONSE_FAILURE'


def test_api_capture_pages_actual_lengths_preserves_parent_and_resumes_without_credentials(tmp_path,monkeypatch):
    paths,parent=api_parent(tmp_path,monkeypatch);parent_bytes=parent.read_bytes();called=[]
    responses=[token_response(),Response(api_metadata_bytes()),
        Response(api_page(('AAA','BBB')),headers=page_headers(0,3,2)),
        Response(api_page(('CCC',)),headers=page_headers(2,3))]
    def request(method,url,**kwargs):called.append((method,url,kwargs));return responses.pop(0)
    factory=lambda:m.FinraAPI(environment=ENV,request=request,pause=lambda:None)
    result=m.capture_api_settlement(paths,'api_test',parent,'2026-08-31','2026-09-14',download=True,client_factory=factory)
    assert result['row_count']==3 and result['market_counts']=={'NNM':3}
    assert called[-1][2]['json']['offset']==2 and not result['catalog_written']
    assert parent.read_bytes()==parent_bytes and result['pages'][0]['raw']['retrieval_timestamp_utc']
    def forbidden():raise AssertionError('Credentials/network must not be accessed')
    assert m.capture_api_settlement(paths,'api_test',parent,'2026-08-31','2026-09-14',download=True,client_factory=forbidden)==result
    for folder in (paths.cache_root,paths.results_root):
        for path in folder.rglob('*'):
            if path.is_file():
                raw=path.read_bytes()
                assert all(value.encode() not in raw for value in [*ENV.values(),TOKEN])
    result['market_counts']={'NNM':4}
    with pytest.raises(ValueError,match='MARKET_COUNTS'):m.verify_api_capture(result,paths,result['contract'])


def test_api_dry_run_scope_and_recorded_refusal_do_not_make_new_requests(tmp_path,monkeypatch):
    paths,parent=api_parent(tmp_path,monkeypatch)
    def forbidden():raise AssertionError('Not authorized to access credentials/network')
    dry=m.capture_api_settlement(paths,'api_test',parent,'2026-08-31','2026-09-14',client_factory=forbidden)
    assert dry['status']=='AWAITING_EXPLICIT_API_EXECUTION'
    with pytest.raises(ValueError,match='NOT_A_PARENT_LATEST_GAP'):
        m.capture_api_settlement(paths,'wrong',parent,'2026-08-14','2026-09-14',client_factory=forbidden)
    calls=[]
    def request(*a,**k):calls.append(a);return Response(b'not stored',status=403)
    factory=lambda:m.FinraAPI(environment=ENV,request=request,pause=lambda:None)
    with pytest.raises(ValueError,match='RECORDED_FAILURE'):
        m.capture_api_settlement(paths,'api_test',parent,'2026-08-31','2026-09-14',download=True,client_factory=factory)
    assert len(calls)==1
    with pytest.raises(ValueError,match='RECORDED_FAILURE'):
        m.capture_api_settlement(paths,'api_test',parent,'2026-08-31','2026-09-14',download=True,client_factory=forbidden)
    assert not list((paths.cache_root/'official_research_intake/api_test').rglob('*.source'))


def test_api_duplicate_symbol_across_pages_preserves_failure_without_merging(tmp_path,monkeypatch):
    paths,parent=api_parent(tmp_path,monkeypatch)
    class Client:
        def get(self,url,payload=None):
            return (api_metadata_bytes(),{},'2026-09-14T13:00:00Z') if url==m.API_METADATA_URL else (api_page(),page_headers(payload['offset'],2),'2026-09-14T13:00:01Z')
        def close(self):pass
    with pytest.raises(ValueError,match='RECORDED_FAILURE'):
        m.capture_api_settlement(paths,'api_test',parent,'2026-08-31','2026-09-14',download=True,client_factory=Client)
    result=json.loads((paths.results_root/'official_research_intake/api_test/finra_short_interest/api/2026-08-31/capture.json').read_text(encoding='utf-8'))
    assert result['error_code']=='FINRA_API_DUPLICATE_SYMBOL_ACROSS_PAGES' and len(result['pages'])==2
