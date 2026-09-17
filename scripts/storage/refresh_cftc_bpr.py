"""Official monthly BPR HTML tables; reuse CFTC/FAST6 storage and raw archive.

BPR has a 25-month linked HTML archive, unlike the existing TFF SoQL dataset.
No contract-code inference, hidden-bank-count reconstruction or PIT promotion.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit
import urllib.error
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve
from scripts.storage.refresh_cftc_cot import disk_floor, identity, NoRedirect, strict_json
from scripts.storage.refresh_official_research_data import archive_module, save_json, json_bytes, VINTAGE

INDEX='https://www.cftc.gov/MarketReports/BankParticipationReports/index.htm'
NOTES='https://www.cftc.gov/MarketReports/BankParticipationReports/ExplanatoryNotes/index.htm'
SCHEDULE='https://www.cftc.gov/MarketReports/BankParticipationReports/ReleaseSchedule/index.htm'
DATASET='cftc_bank_participation_financial_futures_current'
MONTHS={name:i for i,name in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],1)}
MARKETS=('CBT UST BOND','CBT ULTRA UST BOND','CBT UST 2Y NOTE','CBT UST 10Y NOTE','CBT ULTRA UST 10Y','CBT UST 5Y NOTE','CBT FED FUNDS',
 'CME SOFR-3M','CME SOFR-1M','CME EURO SHORT TERM RATE','CME CANADIAN DOLLAR','CME SWISS FRANC','CME MEXICAN PESO','CME BRITISH POUND',
 'CME JAPANESE YEN','CME EURO FX','CME NZ DOLLAR','CME AUSTRALIAN DOLLAR','E VIX FUTURES','CBT DJIA x $5','CME E-MINI S&P 500','CME NASDAQ MINI','CME RUSSELL E-MINI')
HEADERS=['COMMODITY','BANK TYPE','BANK COUNT','LONG FUTURES','%','SHORT FUTURES','%','OPEN INTEREST']
RAW_LIMIT=100*1024**2
TOTAL_LIMIT=300*1024**2
PAGE_LIMIT=4*1024**2


def roots(paths,run_id):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,100}',run_id):raise ValueError('INVALID_RUN_ID')
    tail=Path('official_research_intake')/run_id/'cftc_bpr'
    return paths.results_root/tail,paths.cache_root/tail/'raw'


def clean(text):return ' '.join(text.split())


class Tables(HTMLParser):
    """Retain decoded cell text and physical coordinates; no inferred blank fill."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[];self.links=[];self.table=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])
        if tag=='table':
            if self.table is not None:raise ValueError('NESTED_TABLE_UNSUPPORTED')
            self.table=[]
        elif self.table is not None and tag=='tr':
            if self.row is not None:raise ValueError('UNCLOSED_ROW')
            self.row=[]
        elif self.row is not None and tag in {'th','td'}:
            if self.cell is not None:raise ValueError('UNCLOSED_CELL')
            self.cell={'text':'','rowspan':int(attrs.get('rowspan','1')),'colspan':int(attrs.get('colspan','1')),
                       'source_row':len(self.table)+1,'source_cell':len(self.row)+1}
            if not 1<=self.cell['rowspan']<=8 or not 1<=self.cell['colspan']<=8:raise ValueError('EXCESSIVE_CELL_SPAN')
        elif tag=='br' and self.cell is not None:self.cell['text']+='\n'
    def handle_data(self,text):
        if self.cell is not None:self.cell['text']+=text
    def handle_endtag(self,tag):
        if tag in {'td','th'} and self.cell is not None:self.row.append(self.cell);self.cell=None
        elif tag=='tr' and self.row is not None:
            if self.cell is not None:raise ValueError('CELL_NOT_CLOSED')
            self.table.append(self.row);self.row=None
        elif tag=='table' and self.table is not None:
            if self.row is not None:raise ValueError('ROW_NOT_CLOSED')
            self.tables.append(self.table);self.table=None


def document(raw):
    parser=Tables();parser.feed(raw.decode('utf-8-sig'));parser.close()
    if parser.table is not None or parser.row is not None or parser.cell is not None:raise ValueError('UNCLOSED_TABLE')
    return parser


def linked_reports(raw,as_of):
    upper=date.fromisoformat(as_of);tasks={}
    for href in document(raw).links:
        url=urljoin(INDEX,href);parts=urlsplit(url)
        match=re.fullmatch(r'/MarketReports/BankParticipation/dea([a-z]{3})(\d{2})f',parts.path)
        if not match:continue
        if parts.scheme!='https' or parts.netloc!='www.cftc.gov' or parts.query or parts.fragment:raise ValueError('UNEXPECTED_REPORT_LINK')
        month=f'{2000+int(match[2]):04d}-{MONTHS[match[1]]:02d}'
        if month>as_of[:7]:raise ValueError('UNPUBLISHED_FUTURE_MONTH_IN_INDEX')
        if month in tasks and tasks[month]!=url:raise ValueError('AMBIGUOUS_MONTH_LINK')
        tasks[month]=url
    if len(tasks)!=25:raise ValueError('EXPECTED_OFFICIAL_25_MONTH_ARCHIVE')
    ordered=sorted(tasks)
    indices=[int(x[:4])*12+int(x[5:]) for x in ordered]
    if indices!=list(range(indices[0],indices[0]+25)):raise ValueError('INDEX_MONTH_GAP')
    return [{'month':month,'url':tasks[month]} for month in ordered]


def grid(table):
    pending={};result=[]
    for number,row in enumerate(table,1):
        current={c:cell for c,(remaining,cell) in pending.items()};following={c:(n-1,cell) for c,(n,cell) in pending.items() if n>1}
        column=0
        for cell in row:
            while column in current:column+=1
            for offset in range(cell['colspan']):
                c=column+offset
                if c in current:raise ValueError('OVERLAPPING_SPANS')
                current[c]=cell
                if cell['rowspan']>1:following[c]=(cell['rowspan']-1,cell)
            column+=cell['colspan']
        if set(current)!=set(range(8)):raise ValueError('REPORT_TABLE_WIDTH_NOT_EIGHT')
        result.append([current[c] for c in range(8)]);pending=following
    if pending:raise ValueError('ROWSPAN_PAST_TABLE_END')
    return result


def number(token,integer=True):
    text=clean(token)
    if text=='':return None
    pattern=r'(?:\d{1,3}(?:,\d{3})+|\d+)' + ('' if integer else r'(?:\.\d+)?')
    if not re.fullmatch(pattern,text):return None  # Source suppression token retained separately.
    return Decimal(text.replace(',',''))


def parse_report(raw,expected_month,as_of):
    candidates=[table for table in document(raw).tables if any([clean(c['text']) for c in row]==HEADERS for row in table)]
    if len(candidates)!=1:raise ValueError('REPORT_TABLE_NOT_UNIQUE')
    table=candidates[0];expanded=grid(table)
    if [clean(c['text']) for c in expanded[1]]!=HEADERS:raise ValueError('REPORT_HEADER_POSITION_CHANGED')
    matches=re.findall(r'REPORT DATE:\s*(\d{1,2}/\d{1,2}/\d{4})',' '.join(c['text'] for c in table[0]))
    if len(matches)!=1:raise ValueError('REPORT_DATE_AMBIGUOUS')
    month,day,year=map(int,matches[0].split('/'));report_date=date(year,month,day).isoformat()
    if report_date[:7]!=expected_month or report_date>as_of:raise ValueError('REPORT_DATE_SCOPE_MISMATCH')
    rows=[];groups=defaultdict(list);all_groups=set();last_commodity=None;completed=set()
    for ordinal,cells in enumerate(expanded[2:],3):
        texts=[c['text'] for c in cells];commodity=clean(texts[0]);label=clean(texts[1])
        if not commodity:raise ValueError('MISSING_COMMODITY_IDENTITY')
        if commodity!=last_commodity:
            if commodity in completed:raise ValueError('REPEATED_COMMODITY_GROUP')
            if last_commodity:completed.add(last_commodity)
            last_commodity=commodity
        all_groups.add(commodity)
        if label not in {'U.S.','NON U.S.',''}:raise ValueError('UNKNOWN_BANK_CATEGORY')
        role={'U.S.':'US','NON U.S.':'NON_US','':'TOTAL'}[label]
        if commodity not in MARKETS:continue
        values=[number(texts[i],i not in {4,6}) for i in range(2,8)]
        row={'date':report_date,'report_month':expected_month,'provider_commodity':commodity,'provider_commodity_text':texts[0],
             'bank_category':role,'bank_type_text':texts[1],'bank_count_text':texts[2],'long_futures_text':texts[3],
             'long_percent_text':texts[4],'short_futures_text':texts[5],'short_percent_text':texts[6],'open_interest_text':texts[7],
             **dict(zip(['bank_count','long_futures','long_percent','short_futures','short_percent','open_interest'],values)),
             'bank_count_status':'SOURCE_BLANK_SUPPRESSED' if clean(texts[2])=='' else 'OBSERVED' if values[0] is not None else 'SOURCE_TOKEN',
             'source_table_row':ordinal,'source_cells_json':json.dumps(cells,ensure_ascii=False,sort_keys=True,separators=(',',':')),
             'available_at_utc':None,'historical_pit_certified':False}
        groups[commodity].append(row);rows.append(row)
    for commodity,items in groups.items():
        roles=[r['bank_category'] for r in items]
        if len(roles)!=len(set(roles)) or not 2<=len(roles)<=3 or roles[-1]!='TOTAL':raise ValueError('BANK_GROUP_STRUCTURE_INVALID')
        total=items[-1]
        if total['bank_count'] is None or total['bank_count']<5:raise ValueError('TOTAL_BANK_COUNT_BELOW_REPORT_THRESHOLD')
        oi=[r['open_interest'] for r in items if r['open_interest'] is not None]
        if not oi or len(set(oi))!=1 or oi[0]<=0:raise ValueError('MARKET_OPEN_INTEREST_AMBIGUOUS')
        for field in ['long_futures','short_futures']:
            if all(r[field] is not None for r in items) and sum(r[field] for r in items[:-1])!=total[field]:raise ValueError('BANK_POSITION_TOTAL_MISMATCH')
        if all(r['bank_count'] is not None for r in items) and sum(r['bank_count'] for r in items[:-1])!=total['bank_count']:raise ValueError('BANK_COUNT_TOTAL_MISMATCH')
        for row in items:row['market_open_interest']=oi[0]
    if not rows:raise ValueError('EMPTY_FINANCIAL_SCOPE')
    return rows,{'report_date':report_date,'physical_rows':len(table),'all_reported_commodities':sorted(all_groups),'selected_commodities':sorted(groups),
                 'selected_missing_from_source':sorted(set(MARKETS)-set(groups))}


def verify(receipt,paths,run_id,url):
    _,rawroot=roots(paths,run_id);raw=receipt['raw'];path=Path(raw['local_path']).resolve()
    if receipt['url']!=url or receipt['http']['status']!=200 or receipt['http']['final_url']!=url or raw['source_reference']!=url or raw['source']!='CFTC_OFFICIAL' or raw['status'] not in {'DOWNLOADED','CACHED'}:raise ValueError('RAW_RECEIPT_IDENTITY')
    if not path.is_relative_to(rawroot.resolve()) or path.name!=hashlib.sha256(url.encode()).hexdigest()+'.source':raise ValueError('RAW_PATH_IDENTITY')
    body=path.read_bytes();meta=strict_json(path.with_suffix('.json').read_bytes())
    if hashlib.sha256(body).hexdigest()!=raw['sha256'] or meta['byte_count']!=len(body) or any(meta[k]!=raw[k] for k in ['source_reference','sha256','retrieval_timestamp_utc','event_family','document_kind','source']):raise ValueError('RAW_SIDECAR_HASH_IDENTITY')
    if datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00')).utcoffset() is None:raise ValueError('RAW_RETRIEVED_TIMEZONE')
    return body


def fetch(paths,run_id,name,url,allowed,*,fresh=False):
    root,rawroot=roots(paths,run_id)
    if url not in allowed or not re.fullmatch(r'[a-z0-9_]+',name):raise ValueError('UNPLANNED_SOURCE_REQUEST')
    dest=root/'requests'/(name+'.json');marker=dest.with_suffix('.started.json')
    if dest.exists():
        receipt=strict_json(dest.read_bytes());verify(receipt,paths,run_id,url);return receipt
    if (root/'acquisition_stopped.json').exists() or marker.exists():raise ValueError('PRIOR_FAILURE_OR_INCOMPLETE_ATTEMPT_NO_RETRY')
    used=sum(p.stat().st_size for p in rawroot.rglob('*') if p.is_file())
    if used+PAGE_LIMIT>RAW_LIMIT:raise ValueError('RAW_BUDGET')
    disk_floor(root,rawroot);save_json(marker,{'url':url,'started_at_utc':datetime.now(timezone.utc).isoformat()})
    archive=archive_module(paths.repo_root);opener=urllib.request.build_opener(NoRedirect);http={}
    def bounded(target,timeout):
        if target!=url:raise ValueError('REQUEST_URL_CHANGED')
        time.sleep(1.05)
        try:
            with opener.open(urllib.request.Request(target,headers={'User-Agent':'USTQ-CFTC-official-research/1.0','Accept':'text/html'}),timeout=timeout) as response:
                http.update(status=response.status,final_url=response.url,headers={k:v for k,v in response.headers.items() if k.lower()!='set-cookie'})
                if response.status!=200 or response.url!=url:raise ValueError('NON200_OR_REDIRECT')
                body=response.read(PAGE_LIMIT+1)
                if len(body)>PAGE_LIMIT:raise ValueError('RESPONSE_SIZE_BUDGET')
                return body
        except urllib.error.HTTPError as exc:
            http.update(status=exc.code,final_url=exc.url,headers={k:v for k,v in exc.headers.items() if k.lower()!='set-cookie'});exc.close();raise
    archive._download_once=bounded
    raw=archive.acquire_url(url,'cftc_bpr_latest_after' if fresh else 'cftc_bpr','CFTC_OFFICIAL','BPR_REPORT',rawroot,60,0,0)
    receipt={'url':url,'http':http,'raw':asdict(raw),'acquisition_code':identity(__file__)};save_json(dest,receipt)
    if raw.status=='FAILED':
        save_json(root/'acquisition_stopped.json',{'status':'SOURCE_STOPPED_ONE_ATTEMPT','failed_receipt':identity(dest),'http_status':http.get('status')})
        raise ValueError('OFFICIAL_SOURCE_FAILED_NO_RETRY')
    verify(receipt,paths,run_id,url);return receipt


def normalized_signature(rows):
    return [{k:v for k,v in r.items() if k not in {'source_cells_json','source_table_row'}} for r in rows]


def run(paths,run_id,as_of,*,execute=False):
    root,rawroot=roots(paths,run_id)
    if not date(2026,1,1)<=date.fromisoformat(as_of)<=date.today():raise ValueError('AS_OF_OUTSIDE_CURRENT_SCOPE')
    if (root/'source_stopped.json').exists():
        guard=strict_json((root/'probe_budget_review.json').read_bytes())
        old=strict_json(Path(guard['parent']['path']).read_bytes())
        if identity(guard['parent']['path'])!=guard['parent'] or old['http']['status']!=200 or old['raw']['error']!='AssertionError: ':raise ValueError('UNREVIEWED_LEGACY_SOURCE_STOP')
    initial_refs={}
    def initial(name,url,legacy):
        path=root/legacy
        if path.exists():
            item=strict_json(path.read_bytes());verify(item,paths,run_id,url)
        else:
            path=root/'requests'/(name+'.json')
            if not execute and not path.exists():raise ValueError('INPUT_NOT_ACQUIRED_USE_EXECUTE')
            item=fetch(paths,run_id,name,url,{url})
        initial_refs[name]=identity(path)
        return item
    index=initial('index',INDEX,'probe_receipt.json');tasks=linked_reports(verify(index,paths,run_id,INDEX),as_of)
    samples={'notes':NOTES,'schedule':SCHEDULE,'latest':tasks[-1]['url'],'oldest_budget_recovery':tasks[0]['url']}
    budget_review=None
    if (root/'source_stopped.json').exists():
        review=strict_json((root/'probe_budget_review.json').read_bytes())
        if identity(review['parent']['path'])!=review['parent'] or identity(review['source_stop']['path'])!=review['source_stop']:raise ValueError('PROBE_BUDGET_PARENT_CHANGED')
        failed=strict_json(Path(review['parent']['path']).read_bytes())
        if failed['http']['status']!=200 or failed['url']!=tasks[0]['url'] or failed['raw']['error']!='AssertionError: ' or review['new_cap_bytes']!=PAGE_LIMIT:raise ValueError('ONLY_LOCAL_PROBE_CAP_RECOVERY_ACCEPTED')
        budget_review=identity(root/'probe_budget_review.json')
    receipts={name:initial(name,url,Path('samples')/(name+'.json')) for name,url in samples.items()}
    notes_text=clean(verify(receipts['notes'],paths,run_id,NOTES).decode('utf-8'))
    if 'most recent 25 months' not in notes_text:raise ValueError('HISTORY_RETENTION_RULE_CHANGED')
    contract={'as_of':as_of,'run_id':run_id,'tasks':tasks,'markets':list(MARKETS),'normalizer':identity(__file__),
              'cftc_helpers':identity(Path(__import__('scripts.storage.refresh_cftc_cot',fromlist=['x']).__file__)),
              'archive':identity(paths.repo_root/'fast6/src/fast6/acquisition.py'),'initial_receipts':initial_refs,'local_probe_budget_review':budget_review,
              'raw_limit_bytes':RAW_LIMIT,'total_limit_bytes':TOTAL_LIMIT}
    plan_path=root/'request_plan.json';save_json(plan_path,contract)
    manifest_path=root/'manifest.json'
    if manifest_path.exists():
        prior=strict_json(manifest_path.read_bytes())
        if prior['contract']!=contract:raise ValueError('COMPLETED_MANIFEST_CONTRACT_CHANGED')
        for name,item in prior['inputs'].items():verify(item,paths,run_id,item['url'])
        for out in prior['outputs']:
            if identity(out['path'])!={k:out[k] for k in ['path','bytes','sha256']}:raise ValueError('OUTPUT_HASH_CHANGED')
        return manifest_path
    if not execute:return plan_path
    inputs={**receipts,'index':index};allrows=[];coverage=[];allowed={t['url'] for t in tasks}
    for task in tasks:
        name=task['month'].replace('-','_')
        source=receipts['latest'] if task==tasks[-1] else receipts['oldest_budget_recovery'] if task==tasks[0] else fetch(paths,run_id,name,task['url'],allowed)
        inputs[name]=source;rows,counts=parse_report(verify(source,paths,run_id,task['url']),task['month'],as_of)
        coverage.append({'month':task['month'],**counts,'rows':len(rows)})
        for row in rows:row.update(source_url=task['url'],source_sha256=source['raw']['sha256'],retrieved_at_utc=source['raw']['retrieval_timestamp_utc'],vintage_semantics=VINTAGE)
        allrows.extend(rows);print(json.dumps({'month':task['month'],'selected_rows':len(rows)}),flush=True)
    after=fetch(paths,run_id,'latest_after',tasks[-1]['url'],allowed,fresh=True);inputs['latest_after']=after
    latest,_=parse_report(verify(after,paths,run_id,tasks[-1]['url']),tasks[-1]['month'],as_of)
    before,_=parse_report(verify(receipts['latest'],paths,run_id,tasks[-1]['url']),tasks[-1]['month'],as_of)
    if normalized_signature(latest)!=normalized_signature(before):raise ValueError('LATEST_REPORT_CHANGED_DURING_CAPTURE')
    if set(r['provider_commodity'] for r in latest)!=set(MARKETS):raise ValueError('LATEST_SELECTED_MARKET_SET_INCOMPLETE')
    numeric={'bank_count','long_futures','long_percent','short_futures','short_percent','open_interest','market_open_interest'}
    schema=pa.schema([(k,pa.decimal128(28,6) if k in numeric else pa.timestamp('us',tz='UTC') if k=='available_at_utc' else pa.bool_() if k=='historical_pit_certified' else pa.int64() if k=='source_table_row' else pa.string()) for k in allrows[0]])
    table=pa.Table.from_pylist(allrows,schema=schema)
    version=hashlib.sha256(json_bytes({'contract':contract,'inputs':{k:v['raw']['sha256'] for k,v in inputs.items()}})).hexdigest()[:24]
    output=paths.data_root/'reference/official_research/cftc_bpr'/version/(DATASET+'.parquet');tmp=output.with_suffix('.tmp.parquet')
    rawbytes=sum(p.stat().st_size for p in rawroot.rglob('*') if p.is_file())
    if rawbytes+table.nbytes*2>TOTAL_LIMIT:raise ValueError('TOTAL_STORAGE_BUDGET')
    disk_floor(output.parent,root);output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() or tmp.exists():raise ValueError('PRIOR_OUTPUT_PRESERVED')
    pq.write_table(table,tmp,compression='zstd')
    if not pq.read_table(tmp).equals(table):raise ValueError('PARQUET_ROUNDTRIP_MISMATCH')
    tmp.rename(output)
    out={**identity(output),'dataset':DATASET,'rows':len(allrows),'min_date':min(r['date'] for r in allrows),'max_date':max(r['date'] for r in allrows),'date_column':'date','source':'CFTC_OFFICIAL_BPR'}
    result={'status':'VALIDATED_DATA_ONLY','as_of':as_of,'contract':contract,'inputs':inputs,'outputs':[out],'coverage':coverage,
      'latest_complete':coverage[-1]['report_date'],'coverage_limit':'Official rolling 25-month archive only; not 2008+ history. Fixed 23 financial commodity labels; absent report markets are not filled.',
      'historical_pit_certified':False,'available_at_semantics':'UNKNOWN_NULL; report date is holdings date, scheduled release is separate unverified calendar evidence.',
      'release_schedule_evidence':{'url':SCHEDULE,'raw_sha256':receipts['schedule']['raw']['sha256'],'latest_report_period':coverage[-1]['report_date'],'not_actual_availability_certification':True},
      'data_terms':'CFTC government data public domain; acknowledge CFTC. https://www.cftc.gov/WebPolicy/index.htm',
      'limitations':['2026_PLUS_ACQUISITION_AND_DATA_QUALITY_ONLY_NO_MODEL_BACKTEST_OR_SELECTION','BPR measures reportable bank gross positions, not all banks, bank identities, net flows or concentration among named banks.',
       'Only markets with at least five reportable banks appear; category bank counts may be withheld when either US/non-US group has fewer than four. Do not infer suppressed values.',
       'Original market labels retained; no CFTC contract code or historical mapping fabricated. E VIX FUTURES is the literal provider label.',
       'market_open_interest explicitly carries the source market group OI; source row blank OI remains blank/null. Gross options are excluded.',
       'Current retrieved reports and methodology are not historical PIT vintages. Older 2008-2024-08 history is not supplied by the current official index.'],
      'qc':{'rows':len(allrows),'monthly_reports':len(tasks),'latest_bookend_semantics_equal':True,'raw_bytes_with_sidecars':rawbytes,'source_blank_bank_counts':sum(r['bank_count_status']=='SOURCE_BLANK_SUPPRESSED' for r in allrows),'parquet_roundtrip':'EXACT'},'catalog_written':False}
    save_json(manifest_path,result);return manifest_path


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);parser.add_argument('--as-of',required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();print(run(resolve(),args.run_id,args.as_of,execute=args.execute))


if __name__=='__main__':main()
