from __future__ import annotations
import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');OUT=ROOT/'V22.066IA1M_FAST3_MINIMAL_CANONICAL_PATH_LOADER_R1';MAP=ROOT/'V22.066IA0_FAST3_FROZEN_LEDGER_MAPPING_AUDIT_R1'/'underlying_trade_mapping.csv';CAN=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load_canonical_path(symbol,start,end):
 s=pd.Timestamp(start);e=pd.Timestamp(end)
 if s.tzinfo is None or e.tzinfo is None:raise ValueError('UTC-aware required')
 s=s.tz_convert('UTC');e=e.tz_convert('UTC'); files=[]
 for y,m in {(s.year,s.month),(e.year,e.month)}:
  p=CAN/f'symbol={symbol}'/f'year={y:04d}'/f'month={m:02d}'/'data.parquet'
  if p.exists():files.append(p)
 cols=['timestamp_utc','open','high','low','close','volume'];rows=[]
 for p in files:
  x=pd.read_parquet(p,columns=cols);x['source_file']=str(p);rows.append(x)
 x=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=cols+['source_file']);x['timestamp_utc']=pd.to_datetime(x.timestamp_utc,utc=True);x=x[(x.timestamp_utc>=s)&(x.timestamp_utc<=e)].sort_values('timestamp_utc');inv=int((x.high<x[['open','close','low']].max(axis=1)).sum()+(x.low>x[['open','close','high']].min(axis=1)).sum());a={'symbol':symbol,'candidate_files':len(files),'opened_files':len(files),'rows_read':sum(len(z) for z in rows),'rows_returned':len(x),'load_mode':'MONTH_PARTITION_COLUMN_FILTER','duplicate_count':int(x.timestamp_utc.duplicated().sum()),'invalid_ohlc_count':inv,'issue_codes':'' if len(x) else 'EMPTY_PATH'};return x,a
def run():
 OUT.mkdir(parents=True,exist_ok=True);before=h(MAP);t=pd.read_csv(MAP);t['entry_timestamp_utc']=pd.to_datetime(t.entry_timestamp_utc,utc=True);t['exit_timestamp_utc']=pd.to_datetime(t.exit_timestamp_utc,utc=True);samples=[]
 for ex in ['TQQQ','SQQQ','SOXL','SOXS']:
  r=t[t.execution_symbol_normalized.eq(ex)&t.mapping_resolved].sort_values('entry_timestamp_utc').iloc[0];samples.append(r)
 s=pd.DataFrame(samples);s['selection_rank']=1;s['selection_reason']='EARLIEST_RESOLVED_BY_EXECUTION_SYMBOL';s.to_csv(OUT/'selected_four_sample_trades.csv',index=False);aud=[]
 for _,r in s.iterrows():
  st=r.entry_timestamp_utc;en=min(r.exit_timestamp_utc,st+pd.Timedelta(minutes=30));u,ua=load_canonical_path(r.underlying_symbol,st,en);l,la=load_canonical_path(r.execution_symbol_normalized,st,en);common=len(set(u.timestamp_utc)&set(l.timestamp_utc));union=len(set(u.timestamp_utc)|set(l.timestamp_utc));aud.append({'trade_id':r.trade_id,'underlying_symbol':r.underlying_symbol,'execution_symbol':r.execution_symbol_normalized,'requested_start':st,'requested_end':en,'underlying_candidate_file_count':ua['candidate_files'],'leveraged_candidate_file_count':la['candidate_files'],'underlying_rows_read':ua['rows_read'],'leveraged_rows_read':la['rows_read'],'underlying_rows_returned':len(u),'leveraged_rows_returned':len(l),'common_timestamp_count':common,'synchronization_rate':common/union if union else 0,'underlying_load_mode':ua['load_mode'],'leveraged_load_mode':la['load_mode'],'pair_path_ready':bool(len(u) and len(l) and common),'issue_codes':'|'.join(x for x in [ua['issue_codes'],la['issue_codes']] if x)})
 a=pd.DataFrame(aud);a.to_csv(OUT/'four_sample_path_load_audit.csv',index=False);after=h(MAP);sm={'final_status':'PASS' if a.pair_path_ready.sum()>=3 else 'FAIL','final_diagnostic_decision':'MINIMAL_CANONICAL_PATH_LOADER_READY' if a.pair_path_ready.sum()>=3 else 'MINIMAL_PATH_LOADING_FAILED','ia0_mapping_trade_count':len(t),'selected_sample_count':4,'pair_path_ready_count':int(a.pair_path_ready.sum()),'total_opened_file_count':int(a.underlying_candidate_file_count.sum()+a.leveraged_candidate_file_count.sum()),'total_rows_read':int(a.underlying_rows_read.sum()+a.leveraged_rows_read.sum()),'total_rows_returned':int(a.underlying_rows_returned.sum()+a.leveraged_rows_returned.sum()),'frozen_input_modification_count':int(before!=after),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False};(OUT/'v22_066ia1m_summary.json').write_text(json.dumps(sm,indent=2));(OUT/'test_report.json').write_text('{}');return sm,a
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');z=p.parse_args();sm,a=run() if z.execute else ({},pd.DataFrame());[print(f'{k.upper()}={v}') for k,v in sm.items()]
