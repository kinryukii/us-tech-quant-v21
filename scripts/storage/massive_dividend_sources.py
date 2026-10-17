"""Massive v1 historical dividend SOURCE capture; no market/account math."""
from __future__ import annotations
import io,json,hashlib,re,time
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import quote,urlsplit,parse_qsl,urlencode,urlunsplit
import requests
from scripts.common.storage_paths import assert_safe_output_path
from scripts.storage.refresh_massive_market import wait_request
from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
ENDPOINT='https://api.massive.com/stocks/v1/dividends'
FIELDS=frozenset(('ticker','ex_dividend_date','cash_amount','currency','declaration_date','pay_date','record_date','distribution_type','frequency','id'))
EXCLUDED=('split_adjusted_cash_amount','historical_adjustment_factor')
def require(ok,reason):
 if not ok:raise ValueError(reason)
def file_ref(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def write_json(p,d,paths):
 assert_safe_output_path(p,kind='cache',paths=paths);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return file_ref(p)
def _metadata_rows(body):
 rows=[]
 with io.BytesIO(body) as f:
  q=_JsonProjection(f);q.descend(('results',));q.expect(b'[');q.white()
  while q.peek()!=b']':
   a=q.tell();meta=q.metadata_fields({'ticker','ex_dividend_date'});z=q.tell();require(z-a<=65536,'VENDOR_ENTRY_OVER_ORIGINAL65KI');rows.append((a,z,meta));q.white();sep=q.take()
   if sep==b']':break
   require(sep==b',','VENDOR_ARRAY_STRUCTURE_CHANGED')
 return rows
def project_dividends(body,*,ticker,start_date,end_date,target_dates):
 require('2023-01-01'<=start_date<=end_date<'2026-01-01','VENDOR_PRE2026_WINDOW_REQUIRED');wanted=frozenset(target_dates)
 require(wanted and all(start_date<=x<=end_date for x in wanted),'VENDOR_EXACT_TARGETS_WITHIN_WINDOW_REQUIRED')
 rows=_metadata_rows(body)
 require(all(m.get('ticker')==ticker and isinstance(m.get('ex_dividend_date'),str) and start_date<=m['ex_dividend_date']<=end_date for _,_,m in rows),'VENDOR_RESPONSE_TICKER_DATE_FILTER_CHANGED_NO_NUMERIC_DECODE')
 selected=[];rejected=[]
 for a,z,m in rows:
  if m['ex_dividend_date'] not in wanted:continue
  raw=body[a:z]
  with io.BytesIO(raw) as f:q=_JsonProjection(f);timing=q.metadata_fields({'declaration_date'})
  declared=timing.get('declaration_date')
  if declared and declared>='2026-01-01':rejected.append(dict(ticker=ticker,ex_dividend_date=m['ex_dividend_date'],reason='DECLARATION_NOT_PRE2026_NO_CASH_DECODE'));continue
  with io.BytesIO(raw) as f:q=_JsonProjection(f);record=q.metadata_fields(FIELDS)
  selected.append(record)
 return dict(records=selected,total_metadata_rows=len(rows),target_rows_decoded=len(selected),outside_exact_target_numeric_rows_decoded=0,rejected_target_metadata=rejected,excluded_numeric_fields=list(EXCLUDED),frequency_role='PROVIDER_METADATA_MAY_BE_INFERRED_NOT_ISSUER_EXPLICIT_QUARTER',native_qualified=False,historical_vintage='UNKNOWN',first_publication_at=None,strict_PIT=False)
def safe_next_url(value):
 if not value:return None
 u=urlsplit(value);require(u.scheme=='https' and u.hostname=='api.massive.com' and u.path=='/stocks/v1/dividends','VENDOR_NEXT_URL_NOT_ORIGINAL_RESOURCE')
 pairs=[(k,v) for k,v in parse_qsl(u.query,keep_blank_values=True) if k.lower() not in {'apikey','api_key','access_token','authorization','token'}]
 return urlunsplit((u.scheme,u.netloc,u.path,urlencode(pairs),''))
def acquire_window(*,ticker,start_date,end_date,target_dates,key,root,paths,limit=5000,request_get=requests.get,gate=wait_request):
 require(0<limit<=5000,'VENDOR_LIMIT_REQUIRED');require('2023-01-01'<=start_date<=end_date<'2026-01-01','VENDOR_PRE2026_WINDOW_REQUIRED')
 require(target_dates and all(start_date<=x<=end_date for x in target_dates),'VENDOR_EXACT_TARGETS_WITHIN_WINDOW_REQUIRED')
 query={'ticker':ticker,'ex_dividend_date.gte':start_date,'ex_dividend_date.lte':end_date,'limit':limit,'sort':'ex_dividend_date.asc'}
 contract=dict(endpoint=ENDPOINT,query=query,exact_target_dates=sorted(set(target_dates)),fields=sorted(FIELDS),excluded=list(EXCLUDED),producer_ref=file_ref(Path(__file__)))
 folder=root/'windows'/ticker;checkpoint=folder/'checkpoint.json';assert_safe_output_path(checkpoint,kind='cache',paths=paths)
 if checkpoint.exists():
  saved=json.loads(checkpoint.read_text(encoding='utf-8'));require(saved['contract']==contract,'VENDOR_CHECKPOINT_CONTRACT_CHANGED')
  for a in saved['attempts']:
   if a.get('raw_ref'):require(file_ref(Path(a['raw_ref']['path']))==a['raw_ref'],'VENDOR_RAW_CHECKPOINT_HASH_CHANGED')
  if saved['status']!='PENDING':return saved,0
 else:saved=dict(contract=contract,status='PENDING',attempts=[])
 requests_made=0
 for retry in range(3):
  gate(root,minimum_interval=13);attempt={'started_at':datetime.now(timezone.utc).isoformat()};requests_made+=1
  try:
   response=request_get(ENDPOINT,params=query,headers={'Authorization':'Bearer '+key,'Accept':'application/json'},timeout=(15,45),allow_redirects=False)
   body=response.content;status=response.status_code;attempt.update(observed_at=datetime.now(timezone.utc).isoformat(),http_status=status,response_bytes=len(body),response_sha256=hashlib.sha256(body).hexdigest(),http_date=response.headers.get('Date'),redirect_location_present=bool(response.headers.get('Location')))
   require(key.encode() not in body and quote(key,safe='').encode() not in body,'RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED')
   rawp=folder/('response_'+attempt['response_sha256']+'.json');assert_safe_output_path(rawp,kind='cache',paths=paths);rawp.parent.mkdir(parents=True,exist_ok=True)
   if rawp.exists():require(file_ref(rawp)['sha256']==attempt['response_sha256'],'VENDOR_RAW_HASH_COLLISION')
   else:rawp.write_bytes(body)
   attempt['raw_ref']=file_ref(rawp)
   with io.BytesIO(body) as f:q=_JsonProjection(f);top=q.metadata_fields({'request_id','status','next_url'})
   attempt.update(provider_status=top.get('status'),request_id=top.get('request_id'),next_url_present=bool(top.get('next_url')))
   if top.get('next_url'):attempt['sanitized_next_url']=safe_next_url(top['next_url'])
   if status==200:
    result=project_dividends(body,ticker=ticker,start_date=start_date,end_date=end_date,target_dates=target_dates);saved.update(result);saved['status']='CAPTURED_EXACT_VENDOR_SOURCE_NOT_NATIVE_QUALIFIED';saved['pagination_complete']=not top.get('next_url');saved['next_page_not_followed']=bool(top.get('next_url'));saved['unmatched_target_dates']=sorted(set(target_dates)-{x['ex_dividend_date'] for x in result['records']})
   elif status in (401,403):saved['status']='HISTORY_ENTITLEMENT_DENIED' if any(x in body.lower() for x in (b'timeframe',b'history',b'historical')) else 'RESOURCE_AUTHORIZATION_DENIED'
   elif status==429:
    value=response.headers.get('Retry-After','');cool=float(value) if re.fullmatch(r'\d+(\.\d+)?',value) else 60.;saved.update(status='RATE_LIMIT_STOP_WITH_PERSISTED_COOLDOWN',retry_after_seconds=cool);write_json(root/'request_gate.json',{'not_before_epoch':time.time()+max(13,cool)},paths)
   elif status in (500,502,503,504):saved['status']='PENDING' if retry<2 else 'MAX3_TRANSPORT_RETRIES_EXHAUSTED'
   else:saved['status']='HTTP_REJECTED_NO_UNFILTERED_FALLBACK'
  except (requests.RequestException,ValueError,AssertionError,KeyError) as error:
   attempt.update(error_type=type(error).__name__,reason='TRANSPORT_ERROR_NO_SECRET_TEXT' if isinstance(error,requests.RequestException) else str(error)[:110]);saved['status']='PENDING' if isinstance(error,requests.RequestException) and retry<2 else 'BOUNDARY_OR_TRANSPORT_REJECTED'
  saved['attempts'].append(attempt);write_json(checkpoint,saved,paths)
  if saved['status']!='PENDING':break
 return saved,requests_made
