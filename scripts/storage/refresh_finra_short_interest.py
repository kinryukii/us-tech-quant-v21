"""FINRA public short-interest files, distinct from daily short-sale volume.

Reuse the existing raw archive and storage routing. Keep source fields, provider
symbols, split/revision flags and uncertain availability; never publish catalog.
"""
from __future__ import annotations

import argparse
import base64
import csv
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from scripts.common.storage_paths import resolve
from scripts.storage.build_data_catalog import sha256
from scripts.storage.refresh_official_research_data import archive_module, save_json, json_bytes, VINTAGE

DATASET = 'finra_consolidated_short_interest_current'
FAMILY = 'finra_short_interest'
BASE = 'https://www.finra.org/finra-data/browse-catalog/equity-short-interest'
INDEX_URL = BASE + '/files?custom_month%5Bmonth%5D=any&custom_year%5Byear%5D=any'
SCHEDULE_URL = 'https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest'
FILE_PATTERN = r'https://cdn\.finra\.org/equity/otcmarket/biweekly/shrt(\d{8})\.csv'
HEADER = ['accountingYearMonthNumber', 'symbolCode', 'issueName', 'issuerServicesGroupExchangeCode',
          'marketClassCode', 'currentShortPositionQuantity', 'previousShortPositionQuantity', 'stockSplitFlag',
          'averageDailyVolumeQuantity', 'daysToCoverQuantity', 'revisionFlag', 'changePercent',
          'changePreviousNumber', 'settlementDate']
NUMBERS = {'currentShortPositionQuantity': 'current_short_interest_shares',
           'previousShortPositionQuantity': 'previous_short_interest_shares',
           'averageDailyVolumeQuantity': 'average_daily_volume_shares',
           'changePreviousNumber': 'source_change_shares', 'changePercent': 'source_change_percent',
           'daysToCoverQuantity': 'source_days_to_cover'}
API_URL = 'https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest'
API_METADATA_URL = API_URL.replace('/data/', '/metadata/', 1)
API_TOKEN_URL = 'https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials'
API_LIMIT = 5000
API_MAX_PAGES = 20


class OfficialHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.year = None; self.heading = None
        self.row = []; self.cell = None; self.schedule = {}
    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.links.append(dict(attrs).get('href', ''))
        if tag in {'h2', 'h3'}: self.heading = []
        if tag == 'tr': self.row = []
        if tag in {'th', 'td'}: self.cell = []
    def handle_data(self, value):
        if self.heading is not None: self.heading.append(value)
        if self.cell is not None: self.cell.append(value)
    def handle_endtag(self, tag):
        if tag in {'h2', 'h3'} and self.heading is not None:
            match = re.search(r'(20\d\d)\s+Short Interest Reporting Dates', ''.join(self.heading))
            if match: self.year = int(match[1])
            self.heading = None
        if tag in {'th', 'td'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell = None
        if tag == 'tr' and len(self.row) == 3 and self.year:
            try:
                def day(value):
                    match = re.match(r'([A-Za-z]+ \d{1,2})\b', value)
                    return datetime.strptime(f'{match[1]} {self.year}', '%B %d %Y').date()
                settlement, published = day(self.row[0]), day(self.row[2])
            except (ValueError, TypeError): return
            if published < settlement: published = published.replace(year=published.year + 1)
            if settlement.isoformat() in self.schedule: raise ValueError('DUPLICATE_SCHEDULE_DATE')
            self.schedule[settlement.isoformat()] = published.isoformat()


def parse_index(raw, start_date, as_of):
    parser = OfficialHTML(); parser.feed(raw.decode('utf-8-sig'))
    found = {}
    for url in parser.links:
        match = re.fullmatch(FILE_PATTERN, url)
        if not match: continue
        day = datetime.strptime(match[1], '%Y%m%d').date().isoformat()
        if start_date <= day <= as_of: found[day] = url
    if not found or len(found) > 350: raise ValueError('EMPTY_OR_UNBOUNDED_OFFICIAL_INDEX')
    return dict(sorted(found.items()))


def parse_schedule(raw, as_of):
    parser = OfficialHTML(); parser.feed(raw.decode('utf-8-sig'))
    known = {day: published for day, published in parser.schedule.items() if published <= as_of}
    if not known: raise ValueError('NO_PUBLISHED_SCHEDULE_DATES')
    return known


def parse_file(raw, expected_date, as_of):
    if not date(2017, 12, 29) <= date.fromisoformat(expected_date) <= date.fromisoformat(as_of):
        raise ValueError('SETTLEMENT_OUTSIDE_BOUNDARY')
    text = raw.decode('utf-8-sig')
    if not text.splitlines() or text.splitlines()[0].split('|') != HEADER:
        raise ValueError('UNSUPPORTED_SHORT_INTEREST_HEADER')
    # FINRA pipe files contain literal, unescaped quotes in issue names.
    rows = list(csv.reader(io.StringIO(text), delimiter='|', quoting=csv.QUOTE_NONE))
    if any(len(row) != len(HEADER) for row in rows): raise ValueError('MALFORMED_SOURCE_ROW_WIDTH')
    frame = pd.DataFrame(rows[1:], columns=HEADER)
    return normalize_frame(frame, expected_date, as_of)


def normalize_frame(frame, expected_date, as_of, *, api=False):
    """One source-semantic implementation for pipe files and API JSON records."""
    if not date(2017, 12, 29) <= date.fromisoformat(expected_date) <= date.fromisoformat(as_of):
        raise ValueError('SETTLEMENT_OUTSIDE_BOUNDARY')
    if frame.empty or not frame.settlementDate.eq(expected_date).all() or not frame.accountingYearMonthNumber.eq(expected_date.replace('-', '')).all():
        raise ValueError('EMPTY_OR_WRONG_SETTLEMENT_DATE')
    if frame.symbolCode.isna().any() or frame.symbolCode.eq('').any() or frame.duplicated(['settlementDate', 'symbolCode']).any():
        raise ValueError('EMPTY_OR_DUPLICATE_PROVIDER_SYMBOL')
    if not frame.stockSplitFlag.isin(['', 'S'] + ([None] if api else [])).all() or not frame.revisionFlag.isin(['', 'R'] + ([None] if api else [])).all():
        raise ValueError('UNKNOWN_SPLIT_OR_REVISION_FLAG')
    if frame.marketClassCode.isna().any() or frame.issueName.isna().any() or frame.marketClassCode.eq('').any() or frame.issueName.eq('').any():
        raise ValueError('EMPTY_SOURCE_IDENTITY_FIELD')
    for source, target in NUMBERS.items():
        pattern = r'-?\d{1,18}(?:\.\d{1,6})?' if source in {'changePercent', 'changePreviousNumber'} else r'\d{1,18}(?:\.\d{1,6})?'
        if frame[source].isna().any() or not frame[source].str.fullmatch(pattern).all(): raise ValueError('INVALID_SOURCE_NUMBER:' + source)
        frame[target] = frame[source].map(lambda x: Decimal(x).quantize(Decimal('.000001')))
    frame['date'] = expected_date
    frame['provider_symbol'] = frame.symbolCode
    frame['provider_market'] = frame.marketClassCode
    frame['change_percent_status'] = frame.previous_short_interest_shares.map(
        lambda x: 'PRIOR_POSITION_ZERO_SOURCE_DEFAULT_NOT_ORDINARY_PERCENT_CHANGE' if x == 0 else 'SOURCE_REPORTED')
    frame['market_scope'] = frame.marketClassCode.map(lambda x: 'OTC' if x in {'OTC', 'OTCBB'} else
        ('EXCHANGE_LISTED' if x in {'NYSE', 'NNM', 'SC', 'ARCA', 'BZX', 'AMEX'} else 'UNKNOWN_PROVIDER_MARKET'))
    frame['days_to_cover_status'] = 'SOURCE_REPORTED'
    frame['days_to_cover_value'] = frame.source_days_to_cover
    capped = frame.source_days_to_cover.eq(Decimal('999.99'))
    zero = frame.average_daily_volume_shares.eq(0)
    frame.loc[frame.source_days_to_cover.eq(1), 'days_to_cover_status'] = 'SOURCE_FLOORED_AT_ONE'
    frame.loc[zero, 'days_to_cover_status'] = 'UNDEFINED_ZERO_AVERAGE_VOLUME'
    frame.loc[capped, 'days_to_cover_status'] = 'SOURCE_999_99_SENTINEL_OR_CAP_NOT_EXACT'
    frame.loc[capped | zero, 'days_to_cover_value'] = None
    return frame.sort_values('provider_symbol').reset_index(drop=True)


class FinraAPIError(ValueError):
    """Only constant, credential-free error codes cross the HTTP boundary."""


class FinraAPI:
    def __init__(self, *, environment=None, request=None, pause=None):
        environment = os.environ if environment is None else environment
        values = tuple(environment.get(key, '') for key in ('FINRA_API_CLIENT_ID', 'FINRA_API_CLIENT_SECRET'))
        if any(not isinstance(value, str) or not value for value in values) or ':' in values[0]:
            raise FinraAPIError('FINRA_API_ENV_CREDENTIALS_REQUIRED')
        self._private = values
        self._basic = base64.b64encode(':'.join(values).encode()).decode('ascii')
        self._token = None; self._expires = 0; self._stopped = False
        self._request = request or requests.request
        self._pause = pause or (lambda: time.sleep(1.0))

    def _http(self, method, url, authorization, payload=None):
        if self._stopped: raise FinraAPIError('FINRA_API_CLIENT_STOPPED_AFTER_FAILURE')
        if (method, url) not in {('POST', API_TOKEN_URL), ('GET', API_METADATA_URL), ('POST', API_URL)}:
            raise FinraAPIError('FINRA_API_ENDPOINT_NOT_ALLOWED')
        headers = {'Authorization': authorization, 'Accept': 'application/json',
                   'User-Agent': 'us-tech-quant-research-intake/1.0'}
        if url != API_TOKEN_URL: headers['Data-API-Version'] = '1'
        self._pause()
        response = None
        try:
            response = self._request(method, url, headers=headers, json=payload,
                timeout=(15, 45), allow_redirects=False, stream=True)
            if response.status_code != 200:
                raise FinraAPIError('FINRA_API_HTTP_' + str(int(response.status_code)))
            chunks = []; size = 0
            maximum = 64 * 1024 if url == API_TOKEN_URL else 4 * 1024**2
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > maximum: raise FinraAPIError('FINRA_API_RESPONSE_SIZE_LIMIT')
                chunks.append(chunk)
            content = b''.join(chunks)
            safe_headers = {key.lower(): str(value) for key, value in response.headers.items()
                if key.lower() in {'record-total','record-offset','record-limit','total-records-on-page',
                    'record-max-limit','response-payload-max-size','finra-api-request-id','date','content-type'}}
            secrets = [*self._private, self._basic] + ([self._token] if self._token else [])
            check = content + json_bytes(safe_headers)
            if any(value.encode() in check for value in secrets):
                raise FinraAPIError('FINRA_API_CREDENTIAL_ECHO_NOT_PERSISTED')
            return content, safe_headers, datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        except FinraAPIError:
            self._stopped = True
            raise
        except Exception:
            self._stopped = True
            raise FinraAPIError('FINRA_API_NETWORK_OR_RESPONSE_FAILURE') from None
        finally:
            if response is not None:
                try: response.close()
                except Exception: pass

    def get(self, url, payload=None):
        if self._stopped: raise FinraAPIError('FINRA_API_CLIENT_STOPPED_AFTER_FAILURE')
        if url not in {API_METADATA_URL, API_URL}: raise FinraAPIError('FINRA_API_ENDPOINT_NOT_ALLOWED')
        if (url == API_URL and (not isinstance(payload,dict) or not payload)) or (url == API_METADATA_URL and payload is not None):
            raise FinraAPIError('FINRA_API_DATA_QUERY_REQUIRED_METADATA_HAS_NO_BODY')
        if self._token is None:
            body, _, _ = self._http('POST', API_TOKEN_URL, 'Basic ' + self._basic)
            try:
                token = json.loads(body)
                value = token['access_token']; expiry = int(token['expires_in'])
                if token.get('token_type', '').lower() != 'bearer' or not isinstance(value,str) or not value or re.search(r'\s',value) or expiry < 60:
                    raise ValueError
                self._token = value; self._expires = time.monotonic() + min(expiry,1800) - 15
            except Exception:
                self._stopped = True
                raise FinraAPIError('FINRA_API_INVALID_TOKEN_RESPONSE') from None
        if time.monotonic() >= self._expires:
            self._stopped = True
            raise FinraAPIError('FINRA_API_TOKEN_EXPIRED_NO_AUTOMATIC_RETRY')
        return self._http('GET' if url == API_METADATA_URL else 'POST', url, 'Bearer ' + self._token, payload)

    def close(self):
        self._private = (); self._basic = ''; self._token = None; self._expires = 0; self._stopped = True


def api_json(content):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('FINRA_API_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def invalid(_): raise ValueError('FINRA_API_NONFINITE_JSON_NUMBER')
    return json.loads(content, parse_int=str, parse_float=str, parse_constant=invalid, object_pairs_hook=unique)


def api_metadata(content):
    value = api_json(content)
    if not isinstance(value,dict) or str(value.get('datasetGroup','')).lower() != 'otcmarket' or str(value.get('datasetName','')).lower() != 'consolidatedshortinterest':
        raise ValueError('FINRA_API_METADATA_DATASET_MISMATCH')
    fields = value.get('fields', [])
    if len(fields) != len(HEADER) or {item['name'] for item in fields} != set(HEADER):
        raise ValueError('FINRA_API_UNSUPPORTED_METADATA_FIELDS')
    expected = {name: 'Number' if name in set(NUMBERS) | {'accountingYearMonthNumber'} else 'Date' if name == 'settlementDate' else 'String' for name in HEADER}
    if any(item['type'] != expected[item['name']] for item in fields):
        raise ValueError('FINRA_API_METADATA_FIELD_TYPE_CHANGED')
    partitions = value.get('partitionFields')
    if not isinstance(partitions,list) or len(partitions) != len(set(partitions)) or not set(partitions) <= {'settlementDate','accountingYearMonthNumber'}:
        raise ValueError('FINRA_API_UNSUPPORTED_PARTITION_FIELDS')
    return partitions


def api_request(settlement, offset, partitions):
    filters = {'settlementDate': settlement}
    if 'accountingYearMonthNumber' in partitions: filters['accountingYearMonthNumber'] = settlement.replace('-','')
    return {'fields':HEADER, 'compareFilters':[{'fieldName':key,'fieldValue':value,'compareType':'EQUAL'} for key,value in filters.items()],
            'sortFields':['symbolCode'], 'limit':API_LIMIT, 'offset':offset, 'async':False}


def parse_api_file(content, settlement, as_of):
    rows = api_json(content)
    if not isinstance(rows,list) or not rows or len(rows) > API_LIMIT:
        raise ValueError('FINRA_API_EMPTY_OR_OVERSIZED_PAGE')
    if any(not isinstance(row,dict) or set(row) != set(HEADER) or any(value is not None and not isinstance(value,str) for value in row.values()) for row in rows):
        raise ValueError('FINRA_API_UNSUPPORTED_RECORD_SCHEMA')
    return normalize_frame(pd.DataFrame(rows,columns=HEADER), settlement, as_of, api=True)


def api_page_headers(headers, offset, rows, expected_total=None):
    try:
        total = int(headers['record-total']); limit = int(headers['record-limit'])
        valid = int(headers['record-offset']) == offset and 0 < rows <= limit <= API_LIMIT and offset + rows <= total <= API_LIMIT * API_MAX_PAGES
        valid = valid and (expected_total is None or total == expected_total)
        if 'total-records-on-page' in headers: valid = valid and int(headers['total-records-on-page']) == rows
    except (ValueError, KeyError, TypeError): valid = False
    if not valid: raise ValueError('FINRA_API_PAGINATION_HEADERS_CHANGED_OR_INVALID')
    return total


def save_api_raw(paths, run_id, settlement, url, request, content, headers, observed):
    root = paths.cache_root/'official_research_intake'/run_id/FAMILY/'api'/settlement/'raw'
    request_sha = hashlib.sha256(json_bytes({'url':url,'request':request})).hexdigest()
    path = root/(request_sha+'.source'); metadata = path.with_suffix('.json')
    if path.exists() or metadata.exists(): raise ValueError('FINRA_API_RAW_ALREADY_EXISTS_REQUIRES_REVIEW')
    root.mkdir(parents=True,exist_ok=True)
    record = {'event_family':FAMILY+'_api','source':'FINRA_OFFICIAL','source_reference':url,
        'document_kind':'API_METADATA' if request is None else 'API_SHORT_INTEREST_PAGE',
        'local_path':str(path),'sha256':hashlib.sha256(content).hexdigest(),
        'retrieval_timestamp_utc':observed,'status':'DOWNLOADED','failure_class':None,'error':None}
    with path.open('xb') as handle: handle.write(content)
    save_json(metadata,{**record,'byte_count':len(content),'request':request,'request_sha256':request_sha,'response_headers':headers})
    return {'raw':record,'request':request,'response_headers':headers}


def verify_api_capture(result, paths, contract):
    if result.get('status') != 'COMPLETE_SINGLE_SETTLEMENT_API_CAPTURE' or result.get('contract') != contract:
        raise ValueError('FINRA_API_RECORDED_FAILURE_OR_CONTRACT_MISMATCH')
    def raw_bytes(item,url):
        allowed = paths.cache_root/'official_research_intake'/contract['run_id']/FAMILY/'api'/contract['settlement_date']/'raw'
        if not Path(item['raw']['local_path']).resolve().is_relative_to(allowed):
            raise ValueError('FINRA_API_RAW_OUTSIDE_CAPTURE')
        content = verified_raw(item['raw'],paths,url)
        meta = json.loads(Path(item['raw']['local_path']).with_suffix('.json').read_text(encoding='utf-8'))
        expected = hashlib.sha256(json_bytes({'url':url,'request':item['request']})).hexdigest()
        if meta.get('request') != item['request'] or meta.get('response_headers') != item['response_headers'] or meta.get('request_sha256') != expected or meta.get('byte_count') != len(content):
            raise ValueError('FINRA_API_SIDECAR_REQUEST_MISMATCH')
        return content
    if result['metadata']['request'] is not None: raise ValueError('FINRA_API_METADATA_REQUEST_MISMATCH')
    partitions = api_metadata(raw_bytes(result['metadata'],API_METADATA_URL))
    offset = 0; total = None; symbols = set(); markets = {}
    if not 0 < len(result['pages']) <= API_MAX_PAGES: raise ValueError('FINRA_API_PAGE_COUNT_INVALID')
    for item in result['pages']:
        if item['request'] != api_request(contract['settlement_date'],offset,partitions): raise ValueError('FINRA_API_PAGE_REQUEST_MISMATCH')
        frame = parse_api_file(raw_bytes(item,API_URL),contract['settlement_date'],contract['as_of'])
        total = api_page_headers(item['response_headers'],offset,len(frame),total)
        if symbols.intersection(frame.provider_symbol): raise ValueError('FINRA_API_DUPLICATE_SYMBOL_ACROSS_PAGES')
        symbols.update(frame.provider_symbol); offset += len(frame)
        for market,count in frame.provider_market.value_counts().items(): markets[market] = markets.get(market,0) + int(count)
    if offset != total or offset != result['row_count']: raise ValueError('FINRA_API_INCOMPLETE_PAGINATION')
    if markets != result['market_counts']: raise ValueError('FINRA_API_MARKET_COUNTS_MISMATCH')
    return result


def capture_api_settlement(paths, run_id, parent_manifest, settlement, as_of, *, download=False, client_factory=FinraAPI):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id) or not date(2017,12,29) <= date.fromisoformat(settlement) <= date.fromisoformat(as_of) <= date.today():
        raise ValueError('FINRA_API_SCOPE_INVALID')
    parent_path = Path(parent_manifest).resolve()
    if not parent_path.is_relative_to(paths.results_root/'official_research_intake') or parent_path.parent.name != FAMILY or parent_path.name != 'manifest.json':
        raise ValueError('FINRA_API_PARENT_PATH_INVALID')
    parent = json.loads(parent_path.read_text(encoding='utf-8'))
    if parent.get('role') != 'FINRA_SHORT_INTEREST_INTAKE' or parent['contract']['dataset'] != DATASET or parent['contract']['as_of'] != as_of or settlement not in parent['missing_settlement_dates'] or settlement != parent['expected_latest_settlement'] or parent['expected_latest_publication'] > as_of:
        raise ValueError('FINRA_API_NOT_A_PARENT_LATEST_GAP')
    if hashlib.sha256(json_bytes(parent['contract'])).hexdigest() != parent['contract_sha256']:
        raise ValueError('FINRA_API_PARENT_CONTRACT_HASH_MISMATCH')
    contract = {'version':'finra-api-single-settlement-v1','parent_manifest':{'path':str(parent_path),'sha256':sha256(parent_path)},
        'run_id':run_id,'settlement_date':settlement,'as_of':as_of,'api_url':API_URL,'metadata_url':API_METADATA_URL,
        'scheduled_publication_date':parent['expected_latest_publication'],
        'data_api_version':1,'limit':API_LIMIT,'max_pages':API_MAX_PAGES,'market_filter':None}
    root = paths.results_root/'official_research_intake'/run_id/FAMILY/'api'/settlement
    save_json(root/'request_plan.json',contract)
    result_path = root/'capture.json'
    if result_path.exists(): return verify_api_capture(json.loads(result_path.read_text(encoding='utf-8')),paths,contract)
    if not download: return {'status':'AWAITING_EXPLICIT_API_EXECUTION','contract':contract,'capture_path':str(result_path)}
    if (root/'started.json').exists(): raise ValueError('FINRA_API_INCOMPLETE_ATTEMPT_REQUIRES_REVIEW')
    client = client_factory()
    save_json(root/'started.json',{'contract':contract,'capture_code_sha256':sha256(__file__)})
    result = {'status':'STARTED','contract':contract,'metadata':None,'pages':[],'capture_code_sha256':sha256(__file__),
        'row_count':0,'market_counts':{},'catalog_written':False,'historical_pit_certified':False,
        'available_at_semantics':'UNKNOWN_NULL','vintage_semantics':VINTAGE,
        'limitations':['NON_ATOMIC_PAGINATED_CURRENT_RETRIEVAL','API_MARKET_SCOPE_REQUIRES_ACTUAL_COUNTS_REVIEW','NOT_YET_APPENDED_TO_PARENT_DATASET']}
    try:
        body,headers,observed = client.get(API_METADATA_URL)
        result['metadata'] = save_api_raw(paths,run_id,settlement,API_METADATA_URL,None,body,headers,observed)
        partitions = api_metadata(body); total = None; symbols = set()
        for _ in range(API_MAX_PAGES):
            request = api_request(settlement,result['row_count'],partitions)
            body,headers,observed = client.get(API_URL,request)
            item = save_api_raw(paths,run_id,settlement,API_URL,request,body,headers,observed)
            result['pages'].append(item)
            frame = parse_api_file(body,settlement,as_of)
            total = api_page_headers(headers,result['row_count'],len(frame),total)
            if symbols.intersection(frame.provider_symbol): raise ValueError('FINRA_API_DUPLICATE_SYMBOL_ACROSS_PAGES')
            symbols.update(frame.provider_symbol); result['row_count'] += len(frame)
            for market,count in frame.provider_market.value_counts().items():
                result['market_counts'][market] = result['market_counts'].get(market,0) + int(count)
            if result['row_count'] == total: break
        if result['row_count'] != total: raise ValueError('FINRA_API_PAGE_BUDGET_EXCEEDED')
        result['status'] = 'COMPLETE_SINGLE_SETTLEMENT_API_CAPTURE'
    except Exception as error:
        code = str(error) if isinstance(error,(FinraAPIError,ValueError)) else ''
        result['status'] = 'FAILED_NO_AUTOMATIC_RETRY'
        result['error_code'] = code if re.fullmatch(r'[A-Z0-9_:]+',code) else 'FINRA_API_CAPTURE_VALIDATION_FAILURE'
    finally:
        client.close()
    save_json(result_path,result)
    return verify_api_capture(result,paths,contract)


def verified_raw(record, paths, url=None):
    if record['status'] not in {'DOWNLOADED', 'CACHED'}: raise ValueError('SOURCE_NOT_ACQUIRED')
    path = Path(record['local_path']).resolve()
    if not path.is_relative_to(paths.cache_root) or sha256(path) != record['sha256'] or (url and record['source_reference'] != url):
        raise ValueError('RAW_PATH_HASH_OR_URL_MISMATCH')
    metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if any(metadata.get(key) != record.get(key) for key in ['source_reference', 'sha256', 'retrieval_timestamp_utc']):
        raise ValueError('RAW_METADATA_IDENTITY_MISMATCH')
    observed = pd.Timestamp(record['retrieval_timestamp_utc'])
    if pd.isna(observed) or observed.tzinfo is None: raise ValueError('SOURCE_OBSERVATION_TIME_MISSING')
    return path.read_bytes()


def run(paths, run_id, start_date='2017-12-29', as_of=None, download=False):
    as_of = as_of or date.today().isoformat()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id): raise ValueError('INVALID_RUN_ID')
    if not date(2017, 12, 29) <= date.fromisoformat(start_date) <= date.fromisoformat(as_of) <= date.today():
        raise ValueError('INTAKE_DATE_BOUNDARY_INVALID')
    report = paths.results_root/'official_research_intake'/run_id/FAMILY
    raw_root = paths.cache_root/'official_research_intake'/run_id/FAMILY/'raw'
    request = {'dataset': DATASET, 'run_id': run_id, 'start_date': start_date, 'as_of': as_of,
               'normalizer_sha256': sha256(__file__), 'source_index_url': INDEX_URL}
    plan_path = report/'request_plan.json'
    if plan_path.exists():
        original = json.loads(plan_path.read_text(encoding='utf-8'))
        if any(original.get(k) != v for k, v in request.items() if k != 'normalizer_sha256'):
            raise ValueError('EXISTING_RUN_SCOPE_DIFFERS')
    else: save_json(plan_path, request)
    # A failed parser can be repaired without changing its initial acquisition
    # plan. Each derived version binds the effective parser and original plan.
    request['initial_request_plan_sha256'] = sha256(plan_path)
    if (report/'manifest.json').exists():
        prior = json.loads((report/'manifest.json').read_text(encoding='utf-8'))
        if any(prior['contract'].get(k) != v for k, v in request.items()): raise ValueError('EXISTING_RUN_CONTRACT_DIFFERS')
        if hashlib.sha256(json_bytes(prior['contract'])).hexdigest() != prior['contract_sha256']:
            raise ValueError('EXISTING_CONTRACT_HASH_MISMATCH')
        for item in prior['inputs'] + [period['raw'] for period in prior['periods']]: verified_raw(item, paths)
        for item in prior['outputs']:
            path = Path(item['path']).resolve()
            if not path.is_relative_to(paths.data_root) or sha256(path) != item['sha256']: raise ValueError('OUTPUT_IDENTITY_CHANGED')
        return prior
    capture = archive_module(paths.repo_root)
    records = {}; failures = []
    # Reuse exact current-run raw bytes only; a new date/run captures a new vintage.
    def cache_record(meta):
        item = json.loads(meta.read_text(encoding='utf-8'))
        item = {key: item[key] for key in ['event_family', 'source', 'source_reference', 'document_kind', 'sha256', 'retrieval_timestamp_utc']}
        item.update(local_path=str(meta.with_suffix('.source')), status='CACHED', failure_class=None, error=None)
        verified_raw(item, paths)
        return item
    for meta in sorted((raw_root/FAMILY).glob('*.json')):
        item = cache_record(meta); records[item['source_reference']] = item
    for evidence in ['coverage_probe.json', 'indexed_acquisition.json', 'acquisition_failure.json']:
        path = report/evidence
        if path.exists():
            value = json.loads(path.read_text(encoding='utf-8'))
            failures.extend(x for x in (value if isinstance(value, list) else value['inputs']) if x['status'] == 'FAILED')
    failures = list({(x['source_reference'], x.get('error')): x for x in failures}.values())
    failed_urls = {item['source_reference'] for item in failures}
    host_stopped = any('429' in item.get('error', '') or '401' in item.get('error', '') for item in failures)
    consecutive_denials = 0
    def acquire(url, kind):
        nonlocal host_stopped, consecutive_denials
        if url in records: return records[url]
        if not download: return None
        if url in failed_urls or host_stopped: return None
        time.sleep(.75)
        item = asdict(capture.acquire_url(url, FAMILY, 'FINRA_OFFICIAL', kind, raw_root, 30, 0, 1.))
        if item['status'] == 'FAILED':
            failures.append(item); failed_urls.add(url)
            error = item.get('error', '')
            consecutive_denials = consecutive_denials + 1 if '403' in error else 0
            host_stopped = '429' in error or '401' in error or consecutive_denials >= 2
            return None
        consecutive_denials = 0
        item = cache_record(Path(item['local_path']).with_suffix('.json')); records[url] = item
        return item
    index = acquire(INDEX_URL, 'ALL_FILES_INDEX'); schedule = acquire(SCHEDULE_URL, 'SCHEDULE')
    if not index or not schedule: raise ValueError('OFFICIAL_INDEX_OR_SCHEDULE_NOT_ACQUIRED')
    planned = parse_index(verified_raw(index, paths), start_date, as_of)
    published = parse_schedule(verified_raw(schedule, paths), as_of)
    expected_latest = max(published)
    # Index publication can lag; the schedule supplies the expected latest cycle.
    expected = dict(planned)
    if start_date <= expected_latest and expected_latest not in expected:
        expected[expected_latest] = 'https://cdn.finra.org/equity/otcmarket/biweekly/shrt' + expected_latest.replace('-', '') + '.csv'
    # Network requests are restricted to links actually present in this index.
    for day, url in sorted(planned.items(), reverse=True): acquire(url, 'BIWEEKLY_SHORT_INTEREST')
    if failures and not (report/'acquisition_failure.json').exists():
        save_json(report/'acquisition_failure.json', {'inputs': failures, 'host_stopped': host_stopped})
    inputs = [records[url] for url in [INDEX_URL, SCHEDULE_URL]]
    inputs += [records[url] for url in [BASE + '/files', BASE + '/glossary'] if url in records]
    selected = [(day, records[url]) for day, url in sorted(expected.items()) if url in records]
    if not selected: raise ValueError('NO_REAL_SHORT_INTEREST_FILES')
    identities = [{k: item[k] for k in ['source_reference', 'sha256', 'retrieval_timestamp_utc']} for item in inputs + [raw for _, raw in selected]]
    contract = {**request, 'source_identities': identities, 'expected_dates': sorted(expected)}
    digest = hashlib.sha256(json_bytes(contract)).hexdigest()
    directory = paths.data_root/'reference/official_research/versions'/digest[:24]
    directory.mkdir(parents=True, exist_ok=True)
    output = directory/(DATASET+'.parquet'); temporary = directory/(DATASET+'.parquet.tmp')
    writer = None; summaries = []; total = 0
    try:
        for day, record in selected:
            frame = parse_file(verified_raw(record, paths, expected[day]), day, as_of)
            frame['source'] = 'FINRA_OFFICIAL'; frame['source_id'] = record['sha256']
            frame['observed_at_utc'] = record['retrieval_timestamp_utc']
            frame['scheduled_publication_date'] = published.get(day)
            frame['available_at_utc'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
            frame['vintage_semantics'] = VINTAGE
            table = pa.Table.from_pandas(frame, preserve_index=False)
            fields = [pa.field(f.name, pa.decimal128(24, 6) if f.name in set(NUMBERS.values()) | {'days_to_cover_value'} else
                       pa.string() if f.name == 'scheduled_publication_date' else f.type) for f in table.schema]
            table = table.cast(pa.schema(fields))
            if writer is None: writer = pq.ParquetWriter(temporary, table.schema, compression='zstd')
            writer.write_table(table); total += len(frame)
            summaries.append({'date': day, 'scheduled_publication_date': published.get(day), 'row_count': len(frame),
                'market_counts': frame.provider_market.value_counts().to_dict(), 'revision_rows': int(frame.revisionFlag.eq('R').sum()),
                'split_rows': int(frame.stockSplitFlag.eq('S').sum()), 'sentinel_999_99_rows': int(frame.source_days_to_cover.eq(Decimal('999.99')).sum()),
                'undefined_days_to_cover_rows': int(frame.days_to_cover_value.isna().sum()), 'raw': record})
    finally:
        if writer is not None: writer.close()
    if pq.ParquetFile(temporary).metadata.num_rows != total: raise ValueError('PARQUET_ROW_COUNT_MISMATCH')
    if output.exists():
        if sha256(output) != sha256(temporary): raise ValueError('IMMUTABLE_OUTPUT_CHANGED')
        temporary.unlink()
    else: temporary.replace(output)
    missing = sorted(set(expected) - {day for day, _ in selected})
    indexed_missing = sorted(set(planned) - {day for day, _ in selected})
    manifest = {'schema_version': 1, 'role': 'FINRA_SHORT_INTEREST_INTAKE',
        'status': 'PARTIAL_SOURCE_COVERAGE' if missing else 'VALIDATED_DATA_ONLY', 'contract': contract,
        'contract_sha256': digest, 'inputs': inputs, 'periods': summaries, 'failures': failures,
        'expected_latest_settlement': expected_latest, 'expected_latest_publication': published[expected_latest],
        'latest_acquired_settlement': selected[-1][0], 'missing_settlement_dates': missing,
        'indexed_period_count': len(planned), 'indexed_missing_dates': indexed_missing, 'indexed_history_complete': not indexed_missing,
        'latest_complete': expected_latest == selected[-1][0], 'catalog_written': False,
        'outputs': [{'dataset': DATASET, 'path': str(output), 'sha256': sha256(output), 'row_count': total,
            'min_date': selected[0][0], 'max_date': selected[-1][0], 'date_column': 'date', 'source': 'FINRA_OFFICIAL',
            'source_numeric_missing_rows': 0, 'undefined_days_to_cover_rows': sum(x['undefined_days_to_cover_rows'] for x in summaries)}],
        'historical_pit_certified': False, 'available_at_semantics': 'UNKNOWN_NULL', 'vintage_semantics': VINTAGE,
        'limitations': ['SOURCE_IS_OUTSTANDING_SHORT_POSITIONS_NOT_DAILY_SHORT_SALE_VOLUME',
            'ONLY_CURRENT_REVISED_VINTAGE_AVAILABLE', 'SCHEDULE_DATE_DOES_NOT_CERTIFY_ORIGINAL_VERSION_AVAILABILITY',
            'SOURCE_SYMBOLS_PRESERVED_WITHOUT_HISTORICAL_IDENTITY_MAPPING',
            'CURRENT_RETRIEVED_HISTORY_CAN_CONTAIN_LISTED_STOCKS_BEFORE_DOCUMENTED_COVERAGE_START',
            'OFFICIAL_FILES_DESCRIPTION_JUNE2021_AND_API_NOTES_JUNE2022_DO_NOT_ESTABLISH_ORIGINAL_HISTORICAL_AVAILABILITY',
            'SOURCE_999_99_MAY_BE_SENTINEL_OR_CAP_NOT_EXACT_DAYS', 'SOURCE_DAYS_TO_COVER_FLOORED_AT_ONE',
            'SOURCE_AVERAGE_VOLUME_ZERO_CAN_INCLUDE_PROVIDER_TRANSLATED_NULL',
            'SOURCE_CHANGE_PERCENT_100_CAN_BE_DEFAULT_WHEN_PRIOR_POSITION_ZERO',
            'INCLUDES_SOURCE_EQUITY_INSTRUMENTS_ETFS_WARRANTS_AND_CLASSES_NO_COMMON_STOCK_UNIVERSE_INFERRED',
            '2026_PLUS_INTAKE_ONLY_NO_TRAINING_TUNING_OR_PERFORMANCE_VALIDATION']}
    save_json(report/'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True, help='Immutable capture ID; use a new run for fresh vintage')
    parser.add_argument('--start-date', default='2017-12-29'); parser.add_argument('--as-of', required=True)
    parser.add_argument('--execute', '--download', dest='download', action='store_true',
                        help='Request only indexed public files; denied objects are not retried; rate or general access limits stop the host')
    parser.add_argument('--api-settlement', help='Capture one parent-manifest latest gap using the authenticated production API')
    parser.add_argument('--api-parent-manifest', help='Existing immutable FINRA file manifest; required with --api-settlement')
    args = parser.parse_args()
    if bool(args.api_settlement) != bool(args.api_parent_manifest): parser.error('API settlement and parent manifest must be supplied together')
    if args.api_settlement:
        result = capture_api_settlement(resolve(),args.run_id,args.api_parent_manifest,args.api_settlement,args.as_of,download=args.download)
        print(json.dumps({key:result[key] for key in ('status','row_count','market_counts','capture_path') if key in result},ensure_ascii=False))
        return
    result = run(resolve(), args.run_id, args.start_date, args.as_of, args.download)
    print(json.dumps({key: result[key] for key in ['status', 'outputs', 'latest_complete', 'latest_acquired_settlement']}, ensure_ascii=False))


if __name__ == '__main__': main()
