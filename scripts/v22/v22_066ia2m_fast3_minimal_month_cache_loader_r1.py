import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');OUT=ROOT/'V22.066IA2M_FAST3_MINIMAL_MONTH_CACHE_LOADER_R1';MAP=ROOT/'V22.066IA0_FAST3_FROZEN_LEDGER_MAPPING_AUDIT_R1'/'underlying_trade_mapping.csv';CAN=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical');cache={};reads=0;hits=0
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(symbol,s,e):
 global reads,hits
 s=pd.Timestamp(s).tz_convert('UTC');e=pd.Timestamp(e).tz_convert('UTC');k=(symbol,f'{s.year:04d}-{s.month:02d}');hit=k in cache
 if hit:hits+=1
 else:
  p=CAN/f'symbol={symbol}'/f'year={s.year:04d}'/f'month={s.month:02d}'/'data.parquet';cache[k]=pd.read_parquet(p,columns=['timestamp_utc','open','high','low','close','volume']) if p.exists() else pd.DataFrame();reads+=1
 x=cache[k].copy();x['timestamp_utc']=pd.to_datetime(x.timestamp_utc,utc=True);return x[(x.timestamp_utc>=s)&(x.timestamp_utc<=e)],hit
def run():
 global cache,reads,hits
 cache={};reads=hits=0;b=h(MAP);t=pd.read_csv(MAP);t['entry_timestamp_utc']=pd.to_datetime(t.entry_timestamp_utc,utc=True);t['exit_timestamp_utc']=pd.to_datetime(t.exit_timestamp_utc,utc=True);x=pd.concat([t[t.execution_symbol_normalized.eq(z)].sort_values('entry_timestamp_utc').head(2) for z in ['TQQQ','SQQQ','SOXL','SOXS']]);rows=[];st=time.time()
 for _,r in x.iterrows():
  e=min(r.exit_timestamp_utc,r.entry_timestamp_utc+pd.Timedelta(minutes=30));u,uh=load(r.underlying_symbol,r.entry_timestamp_utc,e);l,lh=load(r.execution_symbol_normalized,r.entry_timestamp_utc,e);c=len(set(u.timestamp_utc)&set(l.timestamp_utc));rows.append({'trade_id':r.trade_id,'underlying_rows_returned':len(u),'leveraged_rows_returned':len(l),'common_timestamp_count':c,'synchronization_rate':c/len(set(u.timestamp_utc)|set(l.timestamp_utc)) if len(u) or len(l) else 0,'pair_path_ready':bool(c),'underlying_cache_hit':uh,'leveraged_cache_hit':lh,'issue_codes':'' if c else 'NO_COMMON_TIMESTAMP'})
 a=pd.DataFrame(rows);OUT.mkdir(parents=True,exist_ok=True);a.to_csv(OUT/'eight_trade_cache_audit.csv',index=False);s={'final_status':'PASS' if a.pair_path_ready.sum()>=7 and hits else 'FAIL','final_diagnostic_decision':'MINIMAL_MONTH_CACHE_READY' if a.pair_path_ready.sum()>=7 and hits else 'CACHE_NOT_REUSED','selected_trade_count':len(a),'pair_path_ready_count':int(a.pair_path_ready.sum()),'unique_symbol_month_count':len(cache),'physical_month_read_count':reads,'cache_hit_count':hits,'total_rows_read':sum(len(v) for v in cache.values()),'total_rows_returned':int(a.underlying_rows_returned.sum()+a.leveraged_rows_returned.sum()),'total_elapsed_seconds':time.time()-st,'frozen_input_modification_count':int(b!=h(MAP)),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False};(OUT/'v22_066ia2m_summary.json').write_text(json.dumps(s,indent=2));(OUT/'test_report.json').write_text('{}');return s
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();s=run() if a.execute else {};[print(f'{k.upper()}={v}') for k,v in s.items()]
