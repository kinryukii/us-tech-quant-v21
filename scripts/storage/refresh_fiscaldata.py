"""Bounded official FiscalData intake; source tokens and revised vintage retained."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import time
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from scripts.common.storage_paths import resolve
from scripts.storage.refresh_official_research_data import archive_module, save_json, json_bytes, VINTAGE
from scripts.storage.build_data_catalog import sha256

BASE = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/'
TABLES = {
    'operating_cash_balance': 'v1/accounting/dts/operating_cash_balance',
    'debt_to_penny': 'v2/accounting/od/debt_to_penny',
    'avg_interest_rates': 'v2/accounting/od/avg_interest_rates',
    'auctions_query': 'v1/accounting/od/auctions_query',
}
RAW_BUDGET = 100 * 1024**2
PAGE_BUDGET = 5 * 1024**2
PAGE_SIZE = 2000
MAX_PAGES = 50
AUCTION_UNUSED_METADATA = {'debt_held_public_amt','intragov_hold_amt','tot_pub_debt_out_amt','src_line_nbr',
    'record_fiscal_year','record_fiscal_quarter','record_calendar_year','record_calendar_quarter',
    'record_calendar_month','record_calendar_day'}
VALUE_FIELDS = {
    'operating_cash_balance':['close_today_bal','open_today_bal','open_month_bal','open_fiscal_year_bal'],
    'debt_to_penny':['debt_held_public_amt','intragov_hold_amt','tot_pub_debt_out_amt'],
    'avg_interest_rates':['avg_interest_rate_amt'],
    'auctions_query':['bid_to_cover_ratio','offering_amt','comp_accepted','comp_tendered','noncomp_accepted',
        'fima_noncomp_accepted','fima_noncomp_tendered','primary_dealer_accepted','primary_dealer_tendered',
        'direct_bidder_accepted','direct_bidder_tendered','indirect_bidder_accepted','indirect_bidder_tendered',
        'soma_accepted','soma_tendered','soma_holdings','total_accepted','total_tendered','treas_retail_accepted',
        'currently_outstanding'],
}
UNITS = {'operating_cash_balance':'MILLION_USD_SOURCE_ROUNDED',
         'debt_to_penny':'USD', 'avg_interest_rates':'PERCENT_NOT_FRACTION',
         'auctions_query':'FIELD_SPECIFIC_USD_AMOUNTS_AND_DIMENSIONLESS_BID_TO_COVER; OTHER_SOURCE_COLUMNS_UNSCALED'}
DOCS = {
    'api':'https://fiscaldata.treasury.gov/api-documentation/',
    'operating_cash_balance':'https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/',
    'debt_to_penny':'https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/',
    'avg_interest_rates':'https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/',
    'github':'https://github.com/fedspendingtransparency/fiscal-data',
    'github_license':'https://raw.githubusercontent.com/fedspendingtransparency/fiscal-data/master/LICENSE',
    'auction_query':'https://www.treasurydirect.gov/auctions/auction-query/',
    'auction_faqs':'https://www.treasurydirect.gov/help-center/faqs/auction-faqs/',
}


def load_json(raw):
    def unique(pairs):
        out = {}
        for key,value in pairs:
            if key in out: raise ValueError('FISCALDATA_DUPLICATE_JSON_KEY')
            out[key] = value
        return out
    def nonfinite(_): raise ValueError('FISCALDATA_NONFINITE_JSON')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=nonfinite)


def table_page_size(table):
    return 500 if table == 'auctions_query' else PAGE_SIZE


def source_date_field(table):
    return 'auction_date' if table == 'auctions_query' else 'record_date'


def source_sort(table):
    return ['auction_date','cusip','issue_date'] if table == 'auctions_query' else ['record_date','src_line_nbr']


def auction_state(row):
    total = row['total_accepted']
    if total not in (None,'','null') and Decimal(total)>0: return 'RESULTS_PRESENT'
    result_fields = [key for key in VALUE_FIELDS['auctions_query'] if key not in {'offering_amt','currently_outstanding','soma_holdings'}]
    if all(row[key] in (None,'','null') for key in result_fields): return 'ANNOUNCED_NO_RESULTS_IN_SOURCE'
    return 'PARTIAL_OR_NONPOSITIVE_RESULTS'


def page_url(table, as_of, number=1, size=None, *, descending=False, completed=False):
    size = table_page_size(table) if size is None else size
    day = source_date_field(table)
    if completed and table != 'auctions_query': raise ValueError('FISCALDATA_COMPLETED_FILTER_SCOPE')
    return query_url(table,sort=('-' if descending else '')+','.join(source_sort(table)),
        filter=day+':gte:2000-01-01,'+day+':lte:'+as_of+(',total_accepted:gt:0' if completed else ''),
        **({'format':'json'} if table=='auctions_query' else {}),
        **{'page[size]':size,'page[number]':number})


def budget_usage(paths, run_id):
    raw_root = paths.cache_root/'official_research_intake'/run_id/'fiscaldata'
    output_root = paths.data_root/'reference/official_research/fiscaldata'/run_id
    raw = sum(path.stat().st_size for path in raw_root.glob('*/raw/*.source'))
    output = sum(path.stat().st_size for path in output_root.glob('*/*.parquet*'))
    return raw,output


def verify_raw(receipt, paths, run_id, table, url):
    raw = receipt.get('raw') or {}
    root = paths.cache_root/'official_research_intake'/run_id/'fiscaldata'/table/'raw'
    path = Path(raw.get('local_path','')).resolve()
    if (receipt.get('status') != 'ACQUIRED' or receipt.get('http_status') != 200
            or receipt.get('url') != url or raw.get('source_reference') != url
            or raw.get('source') != 'US_TREASURY_FISCALDATA' or raw.get('event_family') != 'FISCALDATA_'+table
            or raw.get('document_kind') != 'OFFICIAL_API_JSON'
            or not path.is_relative_to(root.resolve()) or sha256(path) != raw['sha256']):
        raise ValueError('FISCALDATA_CACHED_RAW_IDENTITY')
    content = path.read_bytes()
    meta = load_json(path.with_suffix('.json').read_bytes())
    if any(meta.get(key) != value for key,value in raw.items()) or meta.get('byte_count') != len(content) or receipt.get('bytes') != len(content):
        raise ValueError('FISCALDATA_SIDECAR_IDENTITY')
    observed = datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00'))
    if observed.tzinfo is None: raise ValueError('FISCALDATA_OBSERVED_TIMEZONE')
    return content


def query_url(table, **parameters):
    return BASE + TABLES[table] + '?' + urlencode(parameters)


def fetch(paths, run_id, table, url, *, request=None, recovery=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id) or table not in TABLES or urlparse(url).scheme != 'https' or urlparse(url).netloc != 'api.fiscaldata.treasury.gov' or urlparse(url).path != urlparse(BASE + TABLES[table]).path:
        raise ValueError('FISCALDATA_ENDPOINT_NOT_ALLOWED')
    root = paths.results_root/'official_research_intake'/run_id/'fiscaldata'/table
    raw_root = paths.cache_root/'official_research_intake'/run_id/'fiscaldata'/table/'raw'
    receipt_path = root/'requests'/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt['status'] == 'ACQUIRED':
            verify_raw(receipt,paths,run_id,table,url)
            return receipt
        if (not recovery or recovery['url'] != url or recovery['request']['path'] != str(receipt_path)
                or recovery['request']['sha256'] != sha256(receipt_path)
                or receipt.get('url') != url or receipt.get('http_status') is not None
                or receipt.get('exception_type') != 'ReadTimeout' or receipt.get('raw') is not None
                or receipt.get('error_code') != 'FISCALDATA_NETWORK_OR_RESPONSE_FAILURE'):
            raise ValueError('FISCALDATA_RECORDED_FAILURE_NO_RETRY')
        receipt_path = receipt_path.with_suffix('.readtimeout_recovery.json')
        if receipt_path.exists():
            raise ValueError('FISCALDATA_READTIMEOUT_RECOVERY_ALREADY_ATTEMPTED')
    for previous in (root/'requests').glob('*.json'):
        previous_record = load_json(previous.read_bytes())
        if previous_record.get('http_status') in {401,403,429}:
            raise ValueError('FISCALDATA_ACCESS_DENIED_UNIT_STOPPED')
    capture = archive_module(paths.repo_root)
    path = raw_root/(capture.cache_key(url)+'.source')
    if path.exists() or path.with_suffix('.json').exists(): raise ValueError('FISCALDATA_INCOMPLETE_PRIOR_REQUEST')
    total,output_bytes = budget_usage(paths,run_id)
    if min(shutil.disk_usage(paths.data_root).free,shutil.disk_usage(paths.cache_root).free)<20*1024**3:
        raise ValueError('FISCALDATA_DISK_FLOOR')
    remaining = min(PAGE_BUDGET,RAW_BUDGET-total,300*1024**2-total-output_bytes)
    if remaining <= 0: raise ValueError('FISCALDATA_RAW_BUDGET')
    session = requests.Session(); session.trust_env = False
    response = None
    receipt = {'status':'FAILED','url':url,'observed_at_utc':datetime.now(timezone.utc).isoformat(),'raw':None,
               'acquisition_code_sha256':sha256(__file__)}
    if recovery and recovery['url'] == url: receipt['recovery_parent'] = recovery['request']
    try:
        time.sleep(0.5)
        response = (request or session.get)(url,headers={'User-Agent':'us-tech-quant-official-intake/1.0','Accept':'application/json'},timeout=(10,90 if recovery else 40),allow_redirects=False,stream=True)
        receipt['http_status'] = response.status_code
        if response.status_code != 200: raise ValueError('FISCALDATA_HTTP_'+str(response.status_code))
        data = bytearray()
        for chunk in response.iter_content(65536):
            if len(data)+len(chunk) > remaining: raise ValueError('FISCALDATA_RAW_BUDGET')
            data.extend(chunk)
        observed = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        raw_root.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as handle: handle.write(data)
        raw = asdict(capture.RawDocument('FISCALDATA_'+table,'US_TREASURY_FISCALDATA',url,'OFFICIAL_API_JSON',str(path),hashlib.sha256(data).hexdigest(),observed,'DOWNLOADED'))
        save_json(path.with_suffix('.json'),{**raw,'byte_count':len(data)})
        receipt.update(status='ACQUIRED',raw=raw,bytes=len(data))
    except Exception as error:
        code = str(error) if isinstance(error,ValueError) and str(error).startswith('FISCALDATA_') else 'FISCALDATA_NETWORK_OR_RESPONSE_FAILURE'
        receipt['error_code'] = code
        receipt['exception_type'] = type(error).__name__
    finally:
        if response is not None: response.close()
        session.close()
    save_json(receipt_path,receipt)
    if receipt['status'] != 'ACQUIRED': raise ValueError(receipt['error_code'])
    return receipt


def parse_page(content, table, as_of, number, size, *, expected_meta=None):
    payload = load_json(content)
    data = payload['data']; meta = payload['meta']; links = payload['links']
    total = meta['total-count']; pages = meta['total-pages']
    if (type(total) is not int or not 0 < total <= PAGE_SIZE*MAX_PAGES
            or pages != math.ceil(total/size) or type(meta['count']) is not int
            or meta['count'] != len(data) or len(data) != min(size,total-(number-1)*size)
            or not 1 <= number <= pages):
        raise ValueError('FISCALDATA_PAGINATION_COUNTS')
    for key,page in [('self',number),('first',1),('last',pages),('prev',number-1 if number>1 else None),('next',number+1 if number<pages else None)]:
        if page is None:
            if links.get(key) is not None: raise ValueError('FISCALDATA_PAGINATION_LINKS')
        elif not isinstance(links.get(key),str) or parse_qs(links[key].lstrip('&?')) != {'page[number]':[str(page)],'page[size]':[str(size)]}:
            raise ValueError('FISCALDATA_PAGINATION_LINKS')
    # The archived auction page 12 includes ten unrelated debt dictionary entries,
    # while every data row still has precisely the auction fields. Keep raw meta.
    if table=='auctions_query':
        row_fields=set(data[0]);extras=set(meta['labels'])-row_fields
        if extras:
            if (extras != AUCTION_UNUSED_METADATA or any(set(row)!=row_fields for row in data)
                    or any(set(meta[key]) != set(meta['labels']) for key in ('dataTypes','dataFormats'))):
                raise ValueError('FISCALDATA_UNPROVEN_UNUSED_METADATA')
            payload['unused_metadata_fields']={key:{field:meta[key][field] for field in sorted(extras)} for key in ('labels','dataTypes','dataFormats')}
            meta={**meta,**{key:{field:value for field,value in meta[key].items() if field not in extras} for key in ('labels','dataTypes','dataFormats')}}
    fields = list(meta['labels'])
    signature = {key:meta[key] for key in ('labels','dataTypes','dataFormats','total-count')}
    if expected_meta is not None and signature != expected_meta: raise ValueError('FISCALDATA_METADATA_OR_TOTAL_CHANGED')
    required = {'record_date',*source_sort(table),*VALUE_FIELDS[table]}
    if table == 'auctions_query': required.update({'announcemt_date','reopening','security_type','security_term','pdf_filenm_comp_results'})
    if set(fields) != set(meta['dataTypes']) or set(fields) != set(meta['dataFormats']) or not required <= set(fields):
        raise ValueError('FISCALDATA_METADATA_FIELDS')
    for key in VALUE_FIELDS[table]:
        kind = meta['dataTypes'][key]
        valid_kind = kind == ('CURRENCY0' if key=='offering_amt' else 'NUMBER') if table=='auctions_query' else (kind == 'PERCENTAGE' if table=='avg_interest_rates' else kind.startswith('CURRENCY'))
        if not valid_kind:
            raise ValueError('FISCALDATA_UNIT_TYPE_CHANGED')
    keys = []
    for row in data:
        if set(row) != set(fields) or any(value is not None and not isinstance(value,str) for value in row.values()):
            raise ValueError('FISCALDATA_RECORD_SCHEMA')
        day = date.fromisoformat(row[source_date_field(table)])
        if not '2000-01-01' <= day.isoformat() <= as_of:
            raise ValueError('FISCALDATA_ROW_DATE_OR_LINE')
        if table == 'auctions_query':
            if not re.fullmatch(r'[0-9A-Z]{9}',row['cusip']): raise ValueError('FISCALDATA_AUCTION_CUSIP')
            for key,kind in meta['dataTypes'].items():
                if kind=='DATE' and row[key] not in (None,'','null'): date.fromisoformat(row[key])
            if row['issue_date'] in (None,'','null'): raise ValueError('FISCALDATA_AUCTION_ISSUE_DATE')
            if row['announcemt_date'] not in (None,'','null') and row['announcemt_date']>day.isoformat():
                raise ValueError('FISCALDATA_ANNOUNCEMENT_AFTER_AUCTION')
            keys.append((day.isoformat(),row['cusip'],row['issue_date']))
        else:
            if not re.fullmatch(r'\d+',row['src_line_nbr']): raise ValueError('FISCALDATA_ROW_DATE_OR_LINE')
            keys.append((day.isoformat(),int(row['src_line_nbr'])))
        for key in VALUE_FIELDS[table]:
            value = row[key]
            if value not in (None,'','null') and not re.fullmatch(r'-?\d{1,24}(?:\.\d{1,12})?',value):
                raise ValueError('FISCALDATA_UNKNOWN_NUMBER_OR_NULL')
    if len(set(keys)) != len(keys): raise ValueError('FISCALDATA_DUPLICATE_RECORD_KEY')
    return payload, signature, keys


def normalize_rows(rows, receipt, table, number):
    out = []; raw = receipt['raw']
    for index,row in enumerate(rows,1):
        values = dict(row)
        for key in VALUE_FIELDS[table]:
            value = row[key]
            values[key+'_value'] = None if value in (None,'','null') else Decimal(value)
            values[key+'_missing_kind'] = 'JSON_NULL' if value is None else 'EMPTY_STRING' if value=='' else 'SOURCE_NULL_TOKEN' if value=='null' else None
        values.update(date=row[source_date_field(table)], source='US_TREASURY_FISCALDATA',source_table=table,
            source_unit=UNITS[table],source_id=raw['sha256'],source_url=raw['source_reference'],
            source_page=number,source_index_on_page=index,observed_at_utc=raw['retrieval_timestamp_utc'],
            available_at_utc=None,vintage_semantics=VINTAGE)
        if table == 'auctions_query':
            state=auction_state(row)
            observed_day=datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
            if state=='RESULTS_PRESENT' and row['auction_date']>observed_day:
                raise ValueError('FISCALDATA_RESULTS_BEFORE_AUCTION_DAY')
            values.update(auction_record_state=state,results_available_at_utc=None,
                auction_after_observed_new_york_date='Yes' if row['auction_date']>observed_day else 'No')
        out.append(values)
    schema = pa.schema([(key,pa.decimal128(38,12) if key in {f+'_value' for f in VALUE_FIELDS[table]}
        else pa.int64() if key in {'source_page','source_index_on_page'}
        else pa.timestamp('us',tz='UTC') if key in {'available_at_utc','results_available_at_utc'} else pa.string()) for key in out[0]])
    return pa.Table.from_pylist(out,schema=schema)


def recovery_binding(paths, run_id, table, as_of, contract, *, metadata_fix=False):
    """Bind one reviewed ReadTimeout to the unchanged original plan and failure."""
    root = paths.results_root/'official_research_intake'/run_id/'fiscaldata'/table
    plan_path = root/'request_plan.json'; failure_path = root/'failure.json'
    plan = load_json(plan_path.read_bytes()); failed = load_json(failure_path.read_bytes())
    if ({k:v for k,v in plan.items() if k != 'source_code_sha256'} !=
            {k:v for k,v in contract.items() if k != 'source_code_sha256'}
            or failed.get('contract') != plan
            or failed.get('error_code') != ('FISCALDATA_METADATA_OR_TOTAL_CHANGED' if metadata_fix else 'FISCALDATA_NETWORK_OR_RESPONSE_FAILURE')
            or (metadata_fix and table!='auctions_query')):
        raise ValueError('FISCALDATA_RECOVERY_PARENT_SCOPE')
    inputs = failed['inputs']
    if not inputs: raise ValueError('FISCALDATA_RECOVERY_REQUIRES_VALIDATED_FIRST_PAGE')
    last = None;signature=None
    for number,item in enumerate(inputs,1):
        url = page_url(table,as_of,number)
        last,signature,_ = parse_page(verify_raw(item,paths,run_id,table,url),table,as_of,number,table_page_size(table),expected_meta=signature)
    url = (page_url(table,as_of,len(inputs)+1) if len(inputs)<last['meta']['total-pages']
           else page_url(table,as_of,1,1,descending=True))
    if table=='auctions_query' and len(inputs)==last['meta']['total-pages'] and failed.get('latest_check'):
        verify_raw(failed['latest_check'],paths,run_id,table,url)
        url=page_url(table,as_of,1,1,descending=True,completed=True)
    request_path = root/'requests'/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    old = load_json(request_path.read_bytes())
    if metadata_fix:
        raw=verify_raw(old,paths,run_id,table,url)
        checked,_,_=parse_page(raw,table,as_of,len(inputs)+1,table_page_size(table),expected_meta=signature)
        if set(checked.get('unused_metadata_fields',{}).get('labels',{})) != AUCTION_UNUSED_METADATA:
            raise ValueError('FISCALDATA_METADATA_REPAIR_NOT_PROVEN')
    elif (old.get('status') != 'FAILED' or old.get('url') != url or old.get('http_status') is not None
            or old.get('exception_type') != 'ReadTimeout' or old.get('raw') is not None
            or old.get('error_code') != 'FISCALDATA_NETWORK_OR_RESPONSE_FAILURE'):
        raise ValueError('FISCALDATA_RECOVERY_NOT_READTIMEOUT')
    return {'mode':'AUCTION_UNUSED_DICTIONARY_ONLY_REVALIDATION' if metadata_fix else 'ONE_SAME_URL_READTIMEOUT_RECOVERY','url':url,
        'plan':{'path':str(plan_path),'sha256':sha256(plan_path)},
        'failure':{'path':str(failure_path),'sha256':sha256(failure_path)},
        'request':{'path':str(request_path),'sha256':sha256(request_path)},
        'original_source_code_sha256':plan['source_code_sha256'],
        'recovery_source_code_sha256':contract['source_code_sha256']}


def run_table(paths, run_id, table, as_of, *, execute=False, request=None, recover_read_timeout=False, revalidate_auction_metadata=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id) or table not in TABLES or not date(2000,1,1) <= date.fromisoformat(as_of) <= date.today():
        raise ValueError('FISCALDATA_SCOPE')
    root = paths.results_root/'official_research_intake'/run_id/'fiscaldata'/table
    contract = {'table':table,'endpoint':BASE+TABLES[table],'run_id':run_id,'start_date':'2000-01-01',
        'as_of':as_of,'page_size':table_page_size(table),'max_pages':MAX_PAGES,'raw_budget_bytes':RAW_BUDGET,
        'total_output_budget_bytes':300*1024**2,'budget_scope':'ENTIRE_FISCALDATA_FAMILY_IN_THIS_RUN','sort':source_sort(table),
        'source_code_sha256':sha256(__file__),'shared_code_sha256':sha256(Path(__import__('scripts.storage.refresh_official_research_data',fromlist=['x']).__file__))}
    metadata_fix = revalidate_auction_metadata or (root/'auction_metadata_revalidation_started.json').exists()
    if metadata_fix and (table!='auctions_query' or recover_read_timeout or (root/'readtimeout_recovery_started.json').exists()):
        raise ValueError('FISCALDATA_REVALIDATION_SCOPE_OR_MODE')
    prefix='auction_metadata_revalidation' if metadata_fix else 'readtimeout_recovery'
    started = root/(prefix+'_started.json'); finished = root/(prefix+'_result.json')
    recovery = None
    if started.exists() or ((recover_read_timeout or metadata_fix) and (root/'failure.json').exists()):
        recovery = recovery_binding(paths,run_id,table,as_of,contract,metadata_fix=metadata_fix)
        contract = {**contract,'recovery':recovery}
        if started.exists() and load_json(started.read_bytes())['contract'] != contract:
            raise ValueError('FISCALDATA_RECOVERY_STARTED_IDENTITY')
    else:
        save_json(root/'request_plan.json',contract)
    manifest_path = root/'manifest.json'
    if manifest_path.exists():
        previous = load_json(manifest_path.read_bytes())
        if previous['contract'] != contract: raise ValueError('FISCALDATA_EXISTING_CONTRACT_CHANGED')
        if recovery:
            result = load_json(finished.read_bytes())
            if (result.get('status') != 'COMPLETE' or result.get('contract') != contract
                    or result.get('manifest_sha256') != sha256(manifest_path)):
                raise ValueError('FISCALDATA_RECOVERY_RESULT_IDENTITY')
        for item in [*previous['inputs'],previous['latest_check']]:
            verify_raw(item,paths,run_id,table,item['url'])
        if previous.get('latest_completed_check'):
            item=previous['latest_completed_check'];verify_raw(item,paths,run_id,table,item['url'])
        for output in previous['outputs']:
            if not Path(output['path']).resolve().is_relative_to(paths.data_root.resolve()) or sha256(output['path']) != output['sha256']:
                raise ValueError('FISCALDATA_OUTPUT_IDENTITY')
        return previous
    if (root/'failure.json').exists() and not recovery: raise ValueError('FISCALDATA_PREVIOUS_UNIT_FAILURE_REQUIRES_REVIEW')
    if not execute: return {'status':'PLAN_ONLY','contract':contract}
    if recovery:
        if started.exists() or finished.exists(): raise ValueError('FISCALDATA_READTIMEOUT_RECOVERY_ALREADY_ATTEMPTED')
        save_json(started,{'status':'STARTED_ONE_ATTEMPT','contract':contract,
                          'started_at_utc':datetime.now(timezone.utc).isoformat()})
    pages=[]; metadata=None; prior_key=None; keys_seen=set(); last_row_by_key={}; latest=None
    latest_completed=None; completed_rows={}; states={}; completed_count=0; page_metadata=[]
    try:
        for number in range(1,MAX_PAGES+1):
            url=page_url(table,as_of,number)
            receipt=fetch(paths,run_id,table,url,request=request,recovery=recovery)
            payload,signature,keys=parse_page(verify_raw(receipt,paths,run_id,table,url),table,as_of,number,table_page_size(table),expected_meta=metadata)
            metadata=signature
            if table=='auctions_query':page_metadata.append({'page':number,'url':url,'raw_sha256':receipt['raw']['sha256'],
                'original_metadata':payload['meta'],'unused_metadata_fields':payload.get('unused_metadata_fields',{})})
            if keys != sorted(keys) or (prior_key is not None and keys[0] <= prior_key) or keys_seen.intersection(keys):
                raise ValueError('FISCALDATA_GLOBAL_SORT_OR_DUPLICATE')
            keys_seen.update(keys); prior_key=keys[-1]
            last_row_by_key={key:row for key,row in last_row_by_key.items() if key[0]==keys[-1][0]}
            last_row_by_key.update({key:row for key,row in zip(keys,payload['data']) if key[0]==keys[-1][0]})
            if table=='auctions_query':
                for key,row in zip(keys,payload['data']):
                    state=auction_state(row);summary=states.setdefault(state,{'rows':0,'min_date':key[0],'max_date':key[0]})
                    summary['rows']+=1;summary['max_date']=key[0]
                    if state=='RESULTS_PRESENT':
                        completed_count+=1
                        completed_rows={k:v for k,v in completed_rows.items() if k[0]==key[0]}
                        completed_rows[key]=row
            pages.append(receipt)
            print(json.dumps({'table':table,'page':number,'pages':payload['meta']['total-pages'],'rows':len(keys_seen)}),flush=True)
            if number == payload['meta']['total-pages']: break
        if len(keys_seen) != metadata['total-count']: raise ValueError('FISCALDATA_INCOMPLETE_PAGES')
        url=page_url(table,as_of,1,1,descending=True)
        latest=fetch(paths,run_id,table,url,request=request,recovery=recovery)
        check,signature,check_keys=parse_page(verify_raw(latest,paths,run_id,table,url),table,as_of,1,1,expected_meta=metadata)
        if check_keys[0][0] != prior_key[0] or last_row_by_key.get(check_keys[0]) != check['data'][0]:
            raise ValueError('FISCALDATA_LATEST_CHANGED_OR_VALUES_DIFFER')
        if table=='auctions_query':
            if not completed_rows: raise ValueError('FISCALDATA_NO_AUCTION_RESULTS')
            url=page_url(table,as_of,1,1,descending=True,completed=True)
            latest_completed=fetch(paths,run_id,table,url,request=request,recovery=recovery)
            result_check,_,result_keys=parse_page(verify_raw(latest_completed,paths,run_id,table,url),table,as_of,1,1,
                expected_meta={**metadata,'total-count':completed_count})
            if completed_rows.get(result_keys[0]) != result_check['data'][0]:
                raise ValueError('FISCALDATA_LATEST_COMPLETED_AUCTION_DIFFERS')
        if min(shutil.disk_usage(paths.data_root).free,shutil.disk_usage(paths.cache_root).free)<20*1024**3:
            raise ValueError('FISCALDATA_DISK_FLOOR')
        version=hashlib.sha256(json_bytes({'contract':contract,'inputs':[p['raw']['sha256'] for p in pages]})).hexdigest()[:24]
        dataset='treasury_fiscaldata_'+table+'_current'
        output=paths.data_root/'reference/official_research/fiscaldata'/run_id/version/(dataset+'.parquet')
        temporary=output.with_suffix('.parquet.tmp')
        if output.exists() or temporary.exists(): raise ValueError('FISCALDATA_PRIOR_OUTPUT_PRESERVED')
        output.parent.mkdir(parents=True,exist_ok=True)
        writer=None; missing={key:{} for key in VALUE_FIELDS[table]}; categories={}; row_count=0
        try:
            for number,item in enumerate(pages,1):
                payload,_,_=parse_page(verify_raw(item,paths,run_id,table,item['url']),table,as_of,number,table_page_size(table),expected_meta=metadata)
                arrow=normalize_rows(payload['data'],item,table,number)
                if writer is None: writer=pq.ParquetWriter(temporary,arrow.schema,compression='zstd')
                writer.write_table(arrow);row_count+=arrow.num_rows
                for row in payload['data']:
                    for key in VALUE_FIELDS[table]:
                        value=row[key]
                        if value in (None,'','null'):
                            kind='JSON_NULL' if value is None else 'EMPTY_STRING' if value=='' else 'SOURCE_NULL_TOKEN'
                            missing[key][kind]=missing[key].get(kind,0)+1
                    label=row.get('account_type') or row.get('security_desc') or row.get('security_type')
                    if label:
                        summary=categories.setdefault(label,{'rows':0,'min_date':row[source_date_field(table)],'max_date':row[source_date_field(table)]})
                        summary['rows']+=1;summary['max_date']=row[source_date_field(table)]
        finally:
            if writer is not None: writer.close()
        raw_bytes=sum(p.stat().st_size for p in (paths.cache_root/'official_research_intake'/run_id/'fiscaldata'/table/'raw').glob('*.source'))
        family_raw,family_output=budget_usage(paths,run_id)
        if family_raw>RAW_BUDGET or family_raw+family_output>300*1024**2:
            raise ValueError('FISCALDATA_FINAL_SIZE_BUDGET')
        if pq.ParquetFile(temporary).metadata.num_rows != row_count: raise ValueError('FISCALDATA_ROW_COUNT_WRITE')
        temporary.replace(output)
        result={'status':'VALIDATED_DATA_ONLY','role':'TREASURY_FISCALDATA_INTAKE','contract':contract,'inputs':pages,'latest_check':latest,
            'source_metadata':metadata,'outputs':[{'dataset':dataset,'path':str(output),'sha256':sha256(output),'row_count':row_count,
                'min_date':min(keys_seen)[0],'max_date':prior_key[0],'date_column':'date','source':'US_TREASURY_FISCALDATA','bytes':output.stat().st_size}],
            'source_missing':missing,'source_category_ranges':categories,'source_unit':UNITS[table],
            'raw_bytes':raw_bytes,'family_raw_bytes_at_completion':family_raw,'family_output_bytes_at_completion':family_output,
            'total_budget_bytes':300*1024**2,'latest_check_matches_all_fields':True,
            'available_at_semantics':'UNKNOWN_NULL','date_semantics':'SOURCE_RECORD_DATE_NOT_ASSERTED_PUBLICATION_TIMESTAMP',
            'vintage_semantics':VINTAGE,'historical_pit_certified':False,'catalog_written':False,'official_docs':DOCS,
            'github_reference_license':'MIT_SOFTWARE_LICENSE_NOT_A_SEPARATE_DATA_LICENSE; no wrapper code installed or copied',
            'limitations':['NON_ATOMIC_PAGINATION_WITH_STABLE_TOTAL_METADATA_AND_INDEPENDENT_LATEST_ROW_CHECK',
                'CURRENT_REVISED_HISTORY_NOT_ORIGINAL_PUBLICATION_VINTAGES','SOURCE_NULL_STRING_AND_JSON_NULL_DISTINGUISHED',
                'SOURCE_RECORD_DATE_DOES_NOT_CERTIFY_AVAILABLE_AT','2026_PLUS_INTAKE_ONLY_NO_MODEL_OR_PERFORMANCE_ACCESS',
                'CASH_ACCOUNT_TYPE_DISTINGUISHES_STOCK_BALANCES_FROM_DEPOSITS_WITHDRAWALS_AND_CUMULATIVE_COLUMNS',
                'CASH_SCHEMA_HISTORY_RETAINED; DO_NOT_ASSUME_CLOSE_TODAY_BAL_IS_ALWAYS_POPULATED',
                'MONTHLY_AVERAGE_INTEREST_RATE_IS_OUTSTANDING_DEBT_RATE_NOT_MARKET_YIELD_CURVE',
                'OFFICIAL_WEBSITE_DESCRIPTION_PAGES_HTTP403; OFFICIAL_API_IS_SEPARATE_PUBLIC_HOST']}
        if table=='auctions_query':
            result['limitations']=[item for item in result['limitations'] if not item.startswith(('CASH_','MONTHLY_AVERAGE_INTEREST_RATE_'))]
            result.update(latest_completed_check=latest_completed,auction_state_ranges=states,
                source_page_metadata=page_metadata,
                latest_checks_metadata={'latest':check['meta'],'latest_completed':result_check['meta']},
                latest_completed_check_matches_all_fields=True,
                date_semantics='AUCTION_DATE; RECORD_DATE_AND_ISSUE_DATE_PRESERVED_SEPARATELY_NOT_AVAILABILITY',
                numeric_field_units={key:'DIMENSIONLESS_RATIO' if key=='bid_to_cover_ratio' else 'USD' for key in VALUE_FIELDS[table]},
                all_source_fields_preserved=True,
                source_field_mapping={key:{'output_column':key,'original_type':metadata['dataTypes'][key],
                    'original_format':metadata['dataFormats'][key],'label':metadata['labels'][key],
                    'decimal_column':key+'_value' if key in VALUE_FIELDS[table] else None,
                    'missing_kind_column':key+'_missing_kind' if key in VALUE_FIELDS[table] else None,
                    'numeric_conversion':'EXACT_DECIMAL_UNSCALED' if key in VALUE_FIELDS[table] else 'RAW_SOURCE_TEXT_UNCHANGED'} for key in metadata['labels']})
            result['limitations'] += ['AUCTION_ANNOUNCEMENT_IS_NOT_RESULT_PUBLICATION; RESULTS_AVAILABLE_AT_UNKNOWN_NULL',
                'RESULTS_PRESENT_MEANS_POSITIVE_SOURCE_TOTAL_ACCEPTED_NOT_HISTORICAL_PIT_CERTIFICATION',
                'ANNOUNCED_NO_RESULTS_IN_SOURCE_DOES_NOT_PROVE_CANCELLED_OR_NEVER_OCCURRED',
                'DIRECT_AND_INDIRECT_BIDDER_CATEGORIES_DO_NOT_IDENTIFY_FOREIGN_OR_DOMESTIC_DOMICILE',
                'BID_TO_COVER_IS_SOURCE_REPORTED_RATIO; DO_NOT_RECOMPUTE_FROM_TOTAL_INCLUDING_SOMA',
                'CUSIP_REOPENINGS_RETAINED; IDENTITY_INCLUDES_AUCTION_DATE_AND_ISSUE_DATE',
                'SOURCE_FIELDS_EXPANDED_IN_APRIL_2008; EARLIER_MISSING_BIDDER_FIELDS_NOT_FILLED',
                'OTHER_NUMBER_RATE_PRICE_FIELDS_RETAIN_ORIGINAL_TEXT_AND_FORMAT_NO_UNIT_CONVERSION']
        save_json(manifest_path,result)
        if recovery:
            save_json(finished,{'status':'COMPLETE','contract':contract,'manifest_sha256':sha256(manifest_path)})
        return result
    except Exception as error:
        save_json(finished if recovery else root/'failure.json',{'status':'FAILED_UNIT_NO_AUTOMATIC_RETRY','contract':contract,'inputs':pages,'latest_check':latest,'latest_completed_check':latest_completed,
            'error_code':str(error) if isinstance(error,ValueError) and str(error).startswith('FISCALDATA_') else 'FISCALDATA_UNCLASSIFIED_FAILURE',
            'exception_type':type(error).__name__})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True);parser.add_argument('--as-of',required=True)
    parser.add_argument('--tables',nargs='+',choices=list(TABLES),default=list(TABLES))
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--recover-read-timeouts-once',action='store_true',help='One attempt only for the preserved unit failure proven to be a ReadTimeout; no HTTP rejection retries')
    parser.add_argument('--revalidate-auction-metadata',action='store_true',help='Revalidate the archived HTTP200 auction page with the ten proven unused debt dictionary fields; preserve its failed plan and resume only unrequested pages')
    args=parser.parse_args();paths=resolve();failed=False
    for table in dict.fromkeys(args.tables):
        try:
            result=run_table(paths,args.run_id,table,args.as_of,execute=args.execute,recover_read_timeout=args.recover_read_timeouts_once,revalidate_auction_metadata=args.revalidate_auction_metadata)
            print(json.dumps({'table':table,'status':result['status'],'outputs':result.get('outputs',[])}),flush=True)
        except Exception as error:
            failed=True
            print(json.dumps({'table':table,'status':'STOPPED','error_type':type(error).__name__}),flush=True)
    return int(failed)


if __name__=='__main__':raise SystemExit(main())
