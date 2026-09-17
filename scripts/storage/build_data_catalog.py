"""Rebuildable data index and conservative local market-data recovery.

No model execution, deletion, identity inference, or frozen-pointer mutation.
Prices stay in per-symbol Parquet under the configured data root. SQLite is
only an index over those files and existing SEC / 13F sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS data_files(
 dataset TEXT NOT NULL,ticker TEXT NOT NULL DEFAULT '',adjustment TEXT NOT NULL DEFAULT '',
 path TEXT NOT NULL,format TEXT NOT NULL DEFAULT 'parquet',source TEXT,source_sha256 TEXT,
 vintage_id TEXT,row_count INTEGER,min_date TEXT,max_date TEXT,updated_utc TEXT,
 lineage_json TEXT NOT NULL DEFAULT '{}',is_current INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(dataset,ticker,adjustment,path));
CREATE UNIQUE INDEX IF NOT EXISTS one_current_file ON data_files(dataset,ticker,adjustment)
 WHERE is_current=1;
CREATE TABLE IF NOT EXISTS source_files(path TEXT PRIMARY KEY,sha256 TEXT,size_bytes INTEGER,
 status TEXT,detail TEXT);
CREATE TABLE IF NOT EXISTS data_subscriptions(
 provider_code TEXT PRIMARY KEY,ticker TEXT NOT NULL,requested_start TEXT NOT NULL,
 target_date TEXT NOT NULL,identity_source TEXT NOT NULL,status TEXT NOT NULL);
"""
PRICE_COLUMNS = ['ticker','date','open','high','low','close','volume','turnover',
                 'adjustment','source','provider_code','source_id','observed_at']


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def utc_now(): return datetime.now(timezone.utc).isoformat()


def normalize(frame, adjustment, source_id, cutoff, quarantine=None):
    f = frame.copy()
    if f.empty: return pd.DataFrame(columns=PRICE_COLUMNS)
    dc = next((x for x in ['date','trade_date','time_key'] if x in f), None)
    if dc is None: raise ValueError('missing date column')
    if 'ticker' not in f:
        sc = next((x for x in ['moomoo_symbol','moomoo_code','code'] if x in f),None)
        if sc is None: raise ValueError('missing provider symbol')
        f['ticker'] = f[sc].astype(str).str.replace(r'^US\.', '', regex=True)
    f['ticker'] = f.ticker.astype(str).str.upper().str.strip()
    if not f.ticker.str.fullmatch(r'[A-Z0-9][A-Z0-9._/\-]{0,31}').all():
        raise ValueError('invalid ticker or path component')
    if f.ticker.str.contains('..',regex=False).any():raise ValueError('invalid ticker path component')
    dates = pd.to_datetime(f[dc], errors='coerce')
    if dates.isna().any(): raise ValueError('invalid dates')
    f['date'] = dates.dt.strftime('%Y-%m-%d')
    f = f[f.date <= cutoff].copy()
    for col in ['open','high','low','close','volume','turnover']:
        f[col] = pd.to_numeric(f[col], errors='coerce') if col in f else np.nan
    nums = f[['open','high','low','close','volume']]
    ok = np.isfinite(nums).all(axis=1) & (f[['open','high','low','close']] > 0).all(axis=1)
    ok &= (f.volume >= 0) & (f.high >= f[['open','close','low']].max(axis=1))
    ok &= f.low <= f[['open','close','high']].min(axis=1)
    if not ok.all():
        if quarantine is None:raise ValueError(f'invalid OHLCV: {int((~ok).sum())} rows')
        for row in f.loc[~ok,['ticker','date','open','high','low','close','volume']].to_dict('records'):
            quarantine.append({**row,'source_id':source_id,'adjustment':adjustment,'issue':'INVALID_OHLCV'})
        f=f.loc[ok].copy()
    if f.duplicated(['ticker','date']).any(): raise ValueError('duplicate symbol/date')
    if 'adjustment' in f:
        if f.adjustment.isna().any():raise ValueError('missing explicit row adjustment')
        vals=set(f.adjustment.dropna().astype(str).str.lower())
        aliases={'raw':{'raw','none','au_type.none','0'},'qfq':{'qfq','forward','au_type.qfq','1'}}
        if vals and not vals <= aliases[adjustment]:
            raise ValueError(f'adjustment mismatch: {vals} != {adjustment}')
    f['adjustment'] = adjustment
    if 'source' not in f and 'provider' in f and 'price_type' in f:
        if f.provider.astype(str).str.upper().eq('MOOMOO').all() and f.price_type.eq(adjustment.upper()+'_DAILY').all():
            f['source']='MOOMOO'
    if 'source' not in f or not f.source.fillna('').astype(str).str.upper().isin(['MOOMOO_OPEND','MOOMOO']).all():
        raise ValueError('unverified or non-Moomoo source provenance')
    if 'provider' in f and not f.provider.astype(str).str.upper().eq('MOOMOO').all():
        raise ValueError('contradictory provider provenance')
    if 'price_type' in f and not f.price_type.astype(str).str.upper().eq(adjustment.upper()+'_DAILY').all():
        raise ValueError('contradictory price_type adjustment')
    f['source']=f.source.astype(str).str.upper()
    pc = next((x for x in ['provider_code','moomoo_symbol','moomoo_code','code'] if x in f),None)
    if pc is None and not f.ticker.str.fullmatch(r'[A-Z0-9]+').all():
        raise ValueError('explicit provider mapping required for nonstandard ticker')
    f['provider_code'] = f[pc].astype(str).str.upper().str.strip() if pc else 'US.' + f.ticker
    if not f.provider_code.str.fullmatch(r'US\.[A-Z0-9][A-Z0-9._/\-]{0,63}').all() or f.provider_code.str.contains('..',regex=False).any():
        raise ValueError('invalid provider mapping')
    if f.groupby('ticker').provider_code.nunique().gt(1).any():raise ValueError('ambiguous provider mapping')
    f['source_id'] = source_id
    oc = next((x for x in ['fetched_at_utc','fetch_timestamp','observed_at'] if x in f),None)
    f['observed_at'] = f[oc].astype('string') if oc else pd.NA
    return f[PRICE_COLUMNS].sort_values(['ticker','date']).reset_index(drop=True)


def combine_candidates(candidates, adjustment):
    """Choose complete history; fill only compatible gaps, recording conflicts.

    QFQ histories with overlapping price revisions are not spliced. A disjoint
    QFQ interval is held back until an overlap or provider vintage proves it.
    """
    # The first argument is the already selected history. Never silently lose
    # its dates just because another vintage has more rows overall.
    ranked = list(candidates)
    priority, result, first_path = ranked[0]
    result=result.copy(); used=[first_path]; issues=[]
    for pri, candidate, path in sorted(ranked[1:],key=lambda c:(c[1].date.max(),c[0]),reverse=True):
        if set(candidate.provider_code)!=set(result.provider_code):
            issues.append({'path':path,'reason':'PROVIDER_MAPPING_CONFLICT_REQUIRES_ALIAS_EVIDENCE'})
            continue
        left=result.set_index('date'); right=candidate.set_index('date')
        overlap=left.index.intersection(right.index)
        conflicts=0
        if len(overlap):
            a=left.loc[overlap,['open','high','low','close']].to_numpy(float)
            b=right.loc[overlap,['open','high','low','close']].to_numpy(float)
            conflicts=int((~np.isclose(a,b,rtol=1e-6,atol=1e-8)).any(axis=1).sum())
        missing=right.index.difference(left.index)
        if conflicts:
            issues.append({'path':path,'reason':'PRICE_VINTAGE_CONFLICT','overlap_conflict_days':conflicts,
                           'held_back_days':len(missing)})
            # A newer complete source may replace the old vintage, never splice it.
            if candidate.date.max()>result.date.max() and set(result.date).issubset(set(candidate.date)):
                result=candidate.copy(); used=[path]
            continue
        if adjustment=='qfq' and not len(overlap) and len(missing):
            issues.append({'path':path,'reason':'QFQ_NO_OVERLAP_VINTAGE_UNPROVEN','held_back_days':len(missing)})
            continue
        if len(missing):
            result=pd.concat([result,right.loc[missing].reset_index()],ignore_index=True)
            used.append(path)
    return result.sort_values('date').reset_index(drop=True), used, issues


def discover_market(paths):
    items=[]
    for a in ['raw','qfq']:
        items.extend((p,a,10) for p in (paths.data_root/'stocks').glob(f'*/daily_{a}.parquet'))
        items.extend((p,a,20) for p in (paths.cache_root/'canonical/moomoo_ohlcv').glob(f'*/canonical_moomoo_ohlcv_daily_{a}.csv'))
        base=paths.cache_root/f'raw/moomoo/daily_{a}'
        dirs=[p for p in base.glob('*') if p.is_dir()]
        def stamp(p):
            dates=re.findall(r'20\d{6}',p.name)
            return max(dates) if dates else ''
        # Existing canonical snapshots retain older history. Read the last two
        # source snapshots from each family plus A2's broad validated source set.
        ordinary=sorted([p for p in dirs if 'moomoo_only' in p.name],key=stamp)[-2:]
        chosen=ordinary+[p for p in dirs if 'a2_' in p.name]
        for d in chosen: items.extend((p,a,30) for p in d.glob('*.csv'))
    items.extend((p,'qfq',40) for p in (paths.cache_root/'a2_pit_moomoo_current_week_completion_r1/merged_history').glob('*.parquet'))
    # This file pair is explicitly labelled by its producer, unlike directories
    # named "raw" which sometimes contain unlabelled QFQ API returns.
    root=paths.results_root/'A2_PIT_CANONICAL_COVERAGE_R3'
    for a in ['raw','qfq']:
        p=root/f'api_incremental_{a}_20260819_20260820.parquet'
        if p.is_file(): items.append((p,a,50))
    return items


def register_file(conn, dataset, ticker, adjustment, path, row_count, min_date, max_date,
                  source, lineage, current=True, format='parquet'):
    if format not in {'parquet','parquet_manifest'}:raise ValueError('unsupported catalog file format')
    path=Path(path).resolve(); digest=sha256(path)
    conn.execute('UPDATE data_files SET is_current=0 WHERE dataset=? AND ticker=? AND adjustment=?',
                 (dataset,ticker,adjustment)) if current else None
    values=(dataset,ticker,adjustment,str(path),format,source,digest,digest[:20],row_count,
            min_date,max_date,utc_now(),json.dumps(lineage,ensure_ascii=False),int(current))
    conn.execute('INSERT OR REPLACE INTO data_files VALUES ('+','.join(['?']*len(values))+')',values)


def materialize_market(paths, conn, cutoff, extra_root=None, source_paths=None, updates_only=False):
    candidates={}; deferred={}; errors=[]; quarantined=[]; inventory=[]; seen=set()
    for ticker,a,path,expected in conn.execute(
        "SELECT ticker,adjustment,path,source_sha256 FROM data_files WHERE dataset='prices_daily' AND is_current=1"
    ).fetchall():
        p=Path(path)
        if not p.is_file() or sha256(p)!=expected:
            raise ValueError(f'Prior selected data is missing or changed; preserve and repair before rebuild: {p}')
        frame=pq.ParquetFile(p).read().to_pandas()
        if frame.date.max()>cutoff:
            raise ValueError('Rebuild cutoff would truncate the existing selected history')
        # Retain original source_id values so a no-op rebuild stays byte-stable.
        candidates[(ticker,a)]=(0,frame,[str(p)],[])
    if updates_only and not candidates:raise ValueError('updates-only requires an existing populated price catalog')
    items=[] if updates_only else discover_market(source_paths or paths)
    if extra_root:
        for manifest in Path(extra_root).glob('intervals/*.json'):
            record=json.loads(manifest.read_text(encoding='utf-8'))
            a=record.get('item',{}).get('adjustment')
            p=Path(record.get('path',''))
            if a in {'raw','qfq'} and p.is_file() and sha256(p)==record.get('sha256'):
                items.append((p,a,100))
    for index,(p,a,pri) in enumerate(items):
        try:
            digest=sha256(p)
            if (digest,a) in seen:
                conn.execute('INSERT OR REPLACE INTO source_files VALUES (?,?,?,?,?)',
                             (str(p),digest,p.stat().st_size,'EXACT_DUPLICATE_PRESERVED',''))
                continue
            seen.add((digest,a))
            frame=pd.read_csv(p) if p.suffix=='.csv' else pq.ParquetFile(p).read().to_pandas()
            source_quarantine=[]
            norm=normalize(frame,a,digest,cutoff,source_quarantine)
            quarantined.extend({'path':str(p),**row} for row in source_quarantine)
            for ticker,group in norm.groupby('ticker',sort=False):
                key=(ticker,a)
                if key not in candidates:
                    candidates[key]=(pri,group.copy(),[str(p)],[])
                else:
                    oldpri,old,used,issues=candidates[key]
                    combined,new_used,new_issues=combine_candidates(
                        [(oldpri,old,used[0]),(pri,group,str(p))],a)
                    candidates[key]=(max(oldpri,pri),combined,list(dict.fromkeys(used+new_used)),issues+new_issues)
                    if any(x['reason']=='QFQ_NO_OVERLAP_VINTAGE_UNPROVEN' for x in new_issues):
                        deferred.setdefault(key,[]).append((pri,group.copy(),str(p)))
            conn.execute('INSERT OR REPLACE INTO source_files VALUES (?,?,?,?,?)',
                         (str(p),digest,p.stat().st_size,'VALID_ROWS_WITH_QUARANTINE' if source_quarantine else 'READ_VALIDATED',
                          json.dumps({'quarantined_rows':len(source_quarantine)}) if source_quarantine else ''))
        except (ValueError,KeyError,OSError,TypeError) as exc:
            errors.append({'path':str(p),'reason':str(exc)})
            conn.execute('INSERT OR REPLACE INTO source_files VALUES (?,?,?,?,?)',
                         (str(p),'',p.stat().st_size if p.exists() else 0,'REJECTED',str(exc)))
        if index%250==0: print(f'sources {index}/{len(items)}',flush=True)
    for index,((ticker,a),values) in enumerate(sorted(candidates.items())):
        _,frame,used,issues=values
        pending=deferred.get((ticker,a),[])
        # A later overlapping interval may bridge an earlier disjoint interval.
        # Each successful pass adds dates; failed vintages remain visible.
        for _ in range(len(pending)+1):
            before=len(frame); remaining=[]
            for pri,candidate,path in pending:
                if set(candidate.date).issubset(set(frame.date)):continue
                out,_,reasons=combine_candidates([(0,frame,used[0]),(pri,candidate,path)],a)
                if len(out)>len(frame):frame=out
                else:remaining.append((pri,candidate,path))
            pending=remaining
            if len(frame)==before:break
        directory=paths.data_root/'stocks'/quote(ticker,safe='.-_')/'versions'
        directory.mkdir(parents=True,exist_ok=True)
        temp=directory/f'daily_{a}.staging.parquet'
        frame.to_parquet(temp,index=False,compression='zstd')
        digest=sha256(temp); final=directory/f'daily_{a}_{digest[:20]}.parquet'
        if final.exists():
            if sha256(final)!=digest: raise ValueError('content address collision')
            temp.unlink()  # exact task-created temporary file only
        else: os.replace(temp,final)
        source_ids=sorted(set(frame.source_id))
        actual_inputs=[]
        for sid in source_ids:
            row=conn.execute('SELECT path,sha256 FROM source_files WHERE sha256=? ORDER BY path LIMIT 1',(sid,)).fetchone()
            if row is None: raise ValueError('missing source lineage')
            actual_inputs.append({'path':row[0],'sha256':row[1]})
        lineage={'schema_version':1,'role':'RECOVERED_MARKET_DATA','inputs':actual_inputs,
                 'source_labels':sorted(set(frame.source)),
                 'identity_authority':'PROVIDER_SYMBOL_ONLY_NOT_PIT_SECURITY_ID',
                 'issues':issues,'unbridged_interval_count':len(pending),
                 'available_time_policy':'SOURCE_OBSERVED_AT_OR_NULL',
                 'target_date':cutoff}
        labels=sorted(set(frame.source))
        register_file(conn,'prices_daily',ticker,a,final,len(frame),frame.date.min(),frame.date.max(),
                      labels[0] if len(labels)==1 else 'MOOMOO',lineage)
        inventory.append({'ticker':ticker,'adjustment':a,'rows':len(frame),'min_date':frame.date.min(),
                          'max_date':frame.date.max(),'path':str(final),'issues':len(issues)})
        if index%250==0: print(f'normalized {index}/{len(candidates)}',flush=True)
    return {'source_files':len(items),'rejected_sources':errors,'quarantined_rows':quarantined,'price_files':inventory}


def index_support(paths, conn, sec_root=None, quarter_root=None, incremental_sec_root=None, calendar_manifest=None, public_sources_report=None):
    records=[]
    conn.execute("UPDATE data_files SET is_current=0 WHERE dataset IN ('13f_universe','13f_holdings')")
    known=[('13f_universe_legacy',paths.results_root/'13f_pit_v1/data/universe/13f_dynamic_universe.parquet','effective_date'),
           ('13f_holdings_legacy',paths.results_root/'13f_pit_v1/data/holdings/selected_top100_master.parquet','filing_date'),
           ('13f_identity',paths.results_root/'13f_pit_v1/data/universe/security_identity_v17c_transport.parquet',None),
           ('trading_calendar_provider_legacy',paths.data_root/'moomoo/source/trading_calendar/us_trading_calendar.parquet','trade_date')]
    conn.execute("UPDATE data_files SET is_current=0 WHERE dataset='trading_calendar' AND path=?",
                 (str(paths.data_root/'moomoo/source/trading_calendar/us_trading_calendar.parquet'),))
    if sec_root:
        known += [(f'sec_{name}',Path(sec_root)/filename,dc) for name,filename,dc in [
            ('submissions_pre2026','historical/relevant_submissions.parquet','filed_date'),
            ('facts_pre2026','historical/relevant_companyfacts.parquet','filed_date_fact'),
            ('feature_states_pre2026','historical/fundamental_feature_states.parquet','feature_effective_date'),
            ('bulk_read_audit','historical/bulk_read_audit.parquet',None),
            ('companyfacts_2026_snapshot','current/companyfacts.parquet','filed_date'),
            ('submissions_2026_snapshot','current/submissions.parquet','filed_date'),
            ('snapshot_read_audit','current/read_audit.parquet',None)]]
    if quarter_root:
        known += [(name,Path(quarter_root)/filename,dc) for name,filename,dc in [
            ('13f_universe_external25','dynamic_universe.parquet','effective_date'),
            ('13f_quarter_external25','quarter_universe.parquet','effective_date'),
            ('13f_filings_external25','filing_metadata.parquet','filed_date'),
            ('13f_holdings_external25','selected_top100.parquet',None),
            ('13f_historical_holdings_usd_external25','historical_selected_top100_units.parquet',None)]]
    if incremental_sec_root:
        known += [(f'sec_{name}_incremental',Path(incremental_sec_root)/filename,None if name=='cik_status' else 'filed_date') for name,filename in [
            ('companyfacts','companyfacts.parquet'),('submissions','submissions.parquet'),
            ('cik_status','cik_status.parquet'),('filing_index','filing_index.parquet')]]
        known += [('sec_submissions_acceptance_exceptions',Path(incremental_sec_root)/'acceptance_exceptions.parquet','filed_date')]
    for name,p,dc in known:
        if not p.is_file(): records.append({'dataset':name,'path':str(p),'status':'MISSING'});continue
        f=pq.ParquetFile(p);lo=hi=None
        if dc and dc in f.schema_arrow.names:
            d=f.read(columns=[dc]).to_pandas()[dc].dropna().astype(str)
            if len(d):lo,hi=d.min(),d.max()
        register_file(conn,name,'','',p,f.metadata.num_rows,lo,hi,'EXISTING_LOCAL_SOURCE',
                      {'date_column':dc,'authority':'ORIGINAL_SOURCE_CONTRACT_UNCHANGED'})
        records.append({'dataset':name,'path':str(p),'status':'INDEXED','rows':f.metadata.num_rows,
                        'min_date':lo,'max_date':hi})
    if calendar_manifest:
        manifest_path=Path(calendar_manifest)
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        record=manifest['catalog_record'];path=Path(record['path'])
        if record['dataset']!='trading_calendar' or not path.resolve().is_relative_to(paths.data_root.resolve()):
            raise ValueError('invalid calendar catalog contract')
        if not path.is_file() or sha256(path)!=manifest['sha256']:
            raise ValueError('calendar hash mismatch')
        register_file(conn,**{**record,'path':path})
        records.append({'dataset':'trading_calendar','path':str(path),'status':'INDEXED',
                        'rows':record['row_count'],'min_date':record['min_date'],'max_date':record['max_date']})
    if public_sources_report:
        from scripts.storage.storage_r2a import DataStore
        store=DataStore(paths)
        report_path=store._check_data_path(Path(public_sources_report))
        report=json.loads(report_path.read_text(encoding='utf-8'))
        for item in report['results']:
            name=item.get('dataset',item.get('source','UNKNOWN'))
            if item.get('status')!='SUCCESS':
                records.append({'dataset':name,'status':'ACQUISITION_FAILED','evidence':str(report_path)});continue
            if name not in {'vix_cboe_daily','bls_release_calendar'}:raise ValueError('unexpected public source dataset')
            output=item['output'];path=store._check_data_path(Path(output['path']))
            raw=store._check_data_path(Path(item['raw_path']))
            if sha256(path)!=output['sha256'] or sha256(raw)!=item['raw_sha256']:
                raise ValueError('public source evidence hash mismatch')
            current=conn.execute("SELECT path,source_sha256,lineage_json FROM data_files WHERE dataset=? AND ticker='' AND adjustment='' AND is_current=1",(name,)).fetchone()
            if current and name=='vix_cboe_daily':
                prior=json.loads(current[2]);current_path=store._check_data_path(Path(current[0]))
                same_raw=any(x.get('sha256')==item['raw_sha256'] for x in prior.get('inputs',[]))
                if prior.get('calendar_alignment') and same_raw and 'is_xnys_session' not in output['columns']:
                    if sha256(current_path)!=current[1]:raise ValueError('annotated current VIX changed')
                    records.append({'dataset':name,'path':str(current_path),'status':'PRESERVED_CURRENT_ANNOTATED_VERSION'})
                    continue
            register_file(conn,name,'','',path,output['row_count'],output['min_date'],output['max_date'],item['source'],
                          {'date_column':output['date_column'],'source_url':item['source_url'],
                           'observed_at':item['observed_at'],'vintage_semantics':item['vintage_semantics'],
                           'inputs':[{'path':str(raw),'sha256':item['raw_sha256']},
                                     {'path':str(report_path),'sha256':sha256(report_path)}]})
            records.append({'dataset':name,'path':str(path),'status':'INDEXED','rows':output['row_count'],
                            'min_date':output['min_date'],'max_date':output['max_date']})
    legacy_bls=paths.data_root/'macro_event/raw_official/bls_calendar/BLS_RELEASE_CALENDAR_2020_2025.csv'
    if legacy_bls.is_file():
        frame=pd.read_csv(legacy_bls,dtype='string')
        pd.to_datetime(frame.release_date,errors='raise')
        if frame.duplicated(['event_family','reference_period','release_date','release_time_et']).any():
            raise ValueError('duplicate legacy BLS release key')
        source_sha=sha256(legacy_bls)
        directory=paths.data_root/'reference/bls_release_calendar/versions';directory.mkdir(parents=True,exist_ok=True)
        path=directory/f'legacy_{source_sha[:20]}.parquet'
        if not path.exists():frame.to_parquet(path,index=False,compression='zstd')
        register_file(conn,'bls_release_calendar_legacy','','',path,len(frame),frame.release_date.min(),frame.release_date.max(),
                      'EXISTING_BLS_RELEASE_CALENDAR',{'date_column':'release_date',
                      'content_semantics':'RELEASE_CALENDAR_ONLY_NOT_MACRO_VALUES',
                      'source_observed_at':None,'inputs':[{'path':str(legacy_bls),'sha256':source_sha}]})
        records.append({'dataset':'bls_release_calendar_legacy','path':str(path),'status':'INDEXED','rows':len(frame),
                        'min_date':frame.release_date.min(),'max_date':frame.release_date.max()})
    return records


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--target-date',default='2026-09-11')
    ap.add_argument('--data-root');ap.add_argument('--cache-root');ap.add_argument('--results-root')
    ap.add_argument('--source-data-root');ap.add_argument('--source-cache-root');ap.add_argument('--source-results-root')
    ap.add_argument('--extra-market-root');ap.add_argument('--sec-root')
    ap.add_argument('--quarter-root');ap.add_argument('--incremental-sec-root')
    ap.add_argument('--calendar-manifest')
    ap.add_argument('--public-sources-report')
    ap.add_argument('--report',required=True);ap.add_argument('--index-only',action='store_true')
    ap.add_argument('--updates-only',action='store_true',help='read validated current files plus explicit new market intervals; skip rediscovering old market sources')
    args=ap.parse_args();pd.Timestamp(args.target_date)
    paths=resolve(data_root=args.data_root,cache_root=args.cache_root,results_root=args.results_root)
    sources=resolve(data_root=args.source_data_root,cache_root=args.source_cache_root,results_root=args.source_results_root)
    catalog=paths.cache_root/'derived/data_catalog/catalog.sqlite3';catalog.parent.mkdir(parents=True,exist_ok=True)
    if catalog.exists():
        from scripts.storage.storage_r2a import DataStore
        DataStore(paths,catalog)._catalog_rows('prices_daily')
    conn=sqlite3.connect(catalog);conn.executescript(SCHEMA)
    conn.executemany('INSERT OR REPLACE INTO catalog_metadata VALUES (?,?)',
                     [('schema_version','1'),('catalog_role','REBUILDABLE_FILE_INDEX'),('built_at',utc_now())])
    try:
        if args.index_only: report={'price_files':[]}
        else:
            report=materialize_market(paths,conn,args.target_date,args.extra_market_root,sources,args.updates_only)
        report['support_datasets']=index_support(sources,conn,args.sec_root,args.quarter_root,args.incremental_sec_root,args.calendar_manifest,args.public_sources_report)
        report.update({'catalog':str(catalog),'target_date':args.target_date,'generated_at':utc_now(),
                       'original_snapshot_pointer_changed':False,'model_execution_count':0})
        conn.commit()
    except BaseException:
        conn.rollback();raise
    finally:conn.close()
    output=Path(args.report);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'catalog':str(catalog),'report':str(output),'price_files':len(report['price_files'])}))


if __name__=='__main__':main()
