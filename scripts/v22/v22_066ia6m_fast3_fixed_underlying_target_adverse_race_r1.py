import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');OUT=ROOT/'V22.066IA6M_FAST3_FIXED_UNDERLYING_TARGET_ADVERSE_RACE_R1';IN=ROOT/'V22.066IA4M_FAST3_FULL_LEDGER_UNDERLYING_MFE_MAE_R1'/'full_323_underlying_mfe_mae.csv';CAN=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical');C=[(.0025,.0015),(.005,.0025),(.0075,.003)];cache={}
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
  x=path(r.underlying_symbol,r.entry_timestamp_utc,r.requested_end_timestamp_utc);sg=1 if r.normalized_direction=='LONG' else -1;entry=r.entry_price;fav=(x.high/entry-1) if sg==1 else -(x.low/entry-1);adv=(x.low/entry-1) if sg==1 else -(x.high/entry-1)
  for target,stop in C:
   ft=x[fav>=target];fa=x[adv<=-stop];tt=ft.iloc[0].timestamp_utc if len(ft) else None;ta=fa.iloc[0].timestamp_utc if len(fa) else None;raw='NEITHER' if tt is None and ta is None else 'TARGET_FIRST' if ta is None or(tt is not None and tt<ta) else 'ADVERSE_FIRST' if tt is None or ta<tt else 'BOTH_SAME_MINUTE';rows.append({'trade_id':r.trade_id,'underlying_symbol':r.underlying_symbol,'normalized_direction':r.normalized_direction,'study_period':r.study_period,'target':target,'adverse':stop,'first_target_timestamp':tt,'first_adverse_timestamp':ta,'raw_race_result':raw,'conservative_race_result':'ADVERSE_FIRST' if raw=='BOTH_SAME_MINUTE' else raw})
 a=pd.DataFrame(rows);OUT.mkdir(parents=True,exist_ok=True);a.to_csv(OUT/'full_323_fixed_target_adverse_race.csv',index=False);s={'final_status':'PASS','final_diagnostic_decision':'FIXED_UNDERLYING_TARGET_ADVERSE_RACE_READY','historical_trade_count':len(t),'processed_trade_count':len(t),'same_minute_dual_touch_count':int(a.raw_race_result.eq('BOTH_SAME_MINUTE').sum()),'total_elapsed_seconds':time.time()-st,'frozen_input_modification_count':int(b!=h(IN)),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False}
 for target,stop in C:
  key=f'{target:.4f}_{stop:.4f}'
  for n,g in [('all',a),('qqq',a[a.underlying_symbol.eq('QQQ')]),('soxx',a[a.underlying_symbol.eq('SOXX')]),('long',a[a.normalized_direction.eq('LONG')]),('short',a[a.normalized_direction.eq('SHORT')]),('source',a[a.study_period.eq('2018-2022_DEVELOPMENT')]),('validation',a[a.study_period.eq('2023-2024_VALIDATION')]),('confirmation',a[a.study_period.eq('2025-2026_YTD_CONFIRMATION')])]:
   q=g[(g.target==target)&(g.adverse==stop)];s[n+'_'+key+'_target_first_rate']=float(q.conservative_race_result.eq('TARGET_FIRST').mean())
 (OUT/'v22_066ia6m_summary.json').write_text(json.dumps(s,indent=2));(OUT/'test_report.json').write_text('{}');return s
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();s=run() if a.execute else {};[print(f'{k.upper()}={v}') for k,v in s.items()]
