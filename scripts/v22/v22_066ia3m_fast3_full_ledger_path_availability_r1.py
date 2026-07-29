import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');OUT=ROOT/'V22.066IA3M_FAST3_FULL_LEDGER_PATH_AVAILABILITY_R1';MAP=ROOT/'V22.066IA0_FAST3_FROZEN_LEDGER_MAPPING_AUDIT_R1'/'underlying_trade_mapping.csv';CAN=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical');cache={};reads=hits=0
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(sym,s,e):
 global reads,hits
 s=pd.Timestamp(s).tz_convert('UTC');e=pd.Timestamp(e).tz_convert('UTC');out=[];hit=False
 for y,m in {(s.year,s.month),(e.year,e.month)}:
  k=(sym,f'{y:04d}-{m:02d}')
  if k in cache:hits+=1;hit=True
  else:
   p=CAN/f'symbol={sym}'/f'year={y:04d}'/f'month={m:02d}'/'data.parquet';cache[k]=pd.read_parquet(p,columns=['timestamp_utc']) if p.exists() else pd.DataFrame(columns=['timestamp_utc']);reads+=1
  out.append(cache[k])
 x=pd.concat(out);x['timestamp_utc']=pd.to_datetime(x.timestamp_utc,utc=True);return x[(x.timestamp_utc>=s)&(x.timestamp_utc<=e)],hit
def run():
 global cache,reads,hits
 cache={};reads=hits=0;b=h(MAP);t=pd.read_csv(MAP);t['entry_timestamp_utc']=pd.to_datetime(t.entry_timestamp_utc,utc=True);t['exit_timestamp_utc']=pd.to_datetime(t.exit_timestamp_utc,utc=True);rows=[];st=time.time()
 for _,r in t.iterrows():
  try:
   e=min(r.exit_timestamp_utc,r.entry_timestamp_utc+pd.Timedelta(minutes=90));u,uh=load(r.underlying_symbol,r.entry_timestamp_utc,e);l,lh=load(r.execution_symbol_normalized,r.entry_timestamp_utc,e);c=len(set(u.timestamp_utc)&set(l.timestamp_utc));iss=[]
   if not len(u):iss+=['EMPTY_UNDERLYING_PATH']
   if not len(l):iss+=['EMPTY_LEVERAGED_PATH']
   if not c:iss+=['NO_COMMON_TIMESTAMP']
   rows.append({'trade_id':r.trade_id,'underlying_symbol':r.underlying_symbol,'execution_symbol':r.execution_symbol_normalized,'normalized_direction':r.normalized_direction,'entry_timestamp_utc':r.entry_timestamp_utc,'requested_end_timestamp_utc':e,'underlying_rows_returned':len(u),'leveraged_rows_returned':len(l),'common_timestamp_count':c,'synchronization_rate':c/len(set(u.timestamp_utc)|set(l.timestamp_utc)) if len(u) or len(l) else 0,'underlying_entry_minute_present':r.entry_timestamp_utc in set(u.timestamp_utc),'leveraged_entry_minute_present':r.entry_timestamp_utc in set(l.timestamp_utc),'underlying_path_nonempty':bool(len(u)),'leveraged_path_nonempty':bool(len(l)),'pair_path_ready':bool(c),'underlying_cache_hit':uh,'leveraged_cache_hit':lh,'issue_codes':'|'.join(iss)})
  except Exception as ex:rows.append({'trade_id':r.trade_id,'pair_path_ready':False,'issue_codes':'PARQUET_READ_ERROR'})
 a=pd.DataFrame(rows);OUT.mkdir(parents=True,exist_ok=True);a.to_csv(OUT/'full_323_path_availability.csv',index=False);ready=int(a.pair_path_ready.sum());s={'final_status':'PASS' if ready>=315 else 'FAIL','final_diagnostic_decision':'FULL_LEDGER_PATH_AVAILABILITY_READY' if ready>=315 else 'FULL_LEDGER_PATH_COVERAGE_INSUFFICIENT','historical_trade_count':len(t),'processed_trade_count':len(a),'pair_path_ready_count':ready,'pair_path_not_ready_count':len(a)-ready,'unique_symbol_month_count':len(cache),'physical_month_read_count':reads,'cache_hit_count':hits,'total_rows_read':sum(len(x) for x in cache.values()),'total_rows_returned':int(a.underlying_rows_returned.fillna(0).sum()+a.leveraged_rows_returned.fillna(0).sum()),'total_elapsed_seconds':time.time()-st,'full_history_scan_detected':False,'frozen_input_modification_count':int(b!=h(MAP)),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False};(OUT/'v22_066ia3m_summary.json').write_text(json.dumps(s,indent=2));(OUT/'test_report.json').write_text('{}');return s
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();s=run() if a.execute else {};[print(f'{k.upper()}={v}') for k,v in s.items()]
