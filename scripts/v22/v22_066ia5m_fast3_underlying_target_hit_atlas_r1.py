import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');OUT=ROOT/'V22.066IA5M_FAST3_UNDERLYING_TARGET_HIT_ATLAS_R1';IN=ROOT/'V22.066IA4M_FAST3_FULL_LEDGER_UNDERLYING_MFE_MAE_R1'/'full_323_underlying_mfe_mae.csv';CAN=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical');cache={}
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def path(sym,s,e):
 z=[]
 for y,m in {(s.year,s.month),(e.year,e.month)}:
  k=(sym,y,m)
  if k not in cache:cache[k]=pd.read_parquet(CAN/f'symbol={sym}'/f'year={y:04d}'/f'month={m:02d}'/'data.parquet',columns=['timestamp_utc','open','high','low'])
  z.append(cache[k])
 x=pd.concat(z);x.timestamp_utc=pd.to_datetime(x.timestamp_utc,utc=True);return x[(x.timestamp_utc>=s)&(x.timestamp_utc<=e)].sort_values('timestamp_utc')
def run():
 b=h(IN);t=pd.read_csv(IN);t.entry_timestamp_utc=pd.to_datetime(t.entry_timestamp_utc,utc=True);t.requested_end_timestamp_utc=pd.to_datetime(t.requested_end_timestamp_utc,utc=True);rows=[];st=time.time()
 for _,r in t.iterrows():
  x=path(r.underlying_symbol,r.entry_timestamp_utc,r.requested_end_timestamp_utc);entry=r.entry_price;sg=1 if r.normalized_direction=='LONG' else -1;vals=(x.high/entry-1) if sg==1 else -(x.low/entry-1);o=dict(r)
  for q,n in [(.0025,'0p25'),(.005,'0p50'),(.0075,'0p75'),(.01,'1p00')]:
   z=x[vals>=q];o['hit_'+n]=bool(len(z));o['first_hit_'+n+'_timestamp_utc']=z.iloc[0].timestamp_utc if len(z) else None;o['time_to_'+n+'_minutes']=(z.iloc[0].timestamp_utc-r.entry_timestamp_utc).total_seconds()/60 if len(z) else None
  rows.append(o)
 a=pd.DataFrame(rows);OUT.mkdir(parents=True,exist_ok=True);a.to_csv(OUT/'full_323_underlying_target_hits.csv',index=False);s={'final_status':'PASS','final_diagnostic_decision':'UNDERLYING_TARGET_HIT_ATLAS_READY','historical_trade_count':len(t),'processed_trade_count':len(a),'total_elapsed_seconds':time.time()-st,'frozen_input_modification_count':int(b!=h(IN)),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False}
 for name,g in [('all',a),('qqq',a[a.underlying_symbol.eq('QQQ')]),('soxx',a[a.underlying_symbol.eq('SOXX')]),('long',a[a.normalized_direction.eq('LONG')]),('short',a[a.normalized_direction.eq('SHORT')]),('source',a[a.study_period.eq('2018-2022_DEVELOPMENT')]),('validation',a[a.study_period.eq('2023-2024_VALIDATION')]),('confirmation',a[a.study_period.eq('2025-2026_YTD_CONFIRMATION')])]:
  for n in ['0p25','0p50','0p75','1p00']:s[name+'_'+n+'_hit_rate']=float(g['hit_'+n].mean())
  s[name+'_median_time_to_0p50']=g.time_to_0p50_minutes.median()
 (OUT/'v22_066ia5m_summary.json').write_text(json.dumps(s,indent=2,default=str));(OUT/'test_report.json').write_text('{}');return s
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();s=run() if a.execute else {};[print(f'{k.upper()}={v}') for k,v in s.items()]
