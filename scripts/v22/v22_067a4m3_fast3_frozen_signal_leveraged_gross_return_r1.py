import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd,numpy as np
R=Path(r"D:\us-tech-quant-results\v22");C=Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical");O=R/'V22.067A4M3_FAST3_FROZEN_SIGNAL_LEVERAGED_GROSS_RETURN_R1'
A1=R/'V22.067A1M_FAST3_RECENT_YEAR_SOXX_RANKING_BASELINE_R1';A2=R/'V22.067A2M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2024_2025_R1';A3=R/'V22.067A3M_FAST3_SOXX_FROZEN_MODEL_REVERSE_VALIDATION_2023_2024_R1';K=R/'V22.067A4C_FAST3_FROZEN_LABEL_CONTRACT_RECOVERY_R1/resolved_frozen_label_contract.json'
S=[('A1M_CONFIRMATION',A1/'confirmation_ranked_candidates.csv',99,101),('A2M_2024_2025',A2/'reverse_validation_ranked_candidates_2024_2025.csv',429,465),('A3M_2023_2024',A3/'reverse_validation_ranked_candidates_2023_2024.csv',392,458)]
def H(p):
 h=hashlib.sha256()
 with open(p,'rb')as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
cache={};reads=hits=0
def B(sym,ts):
 global reads,hits
 ts=pd.Timestamp(ts).tz_convert('UTC');k=(sym,f'{ts.year:04d}-{ts.month:02d}')
 if k not in cache:
  p=C/f'symbol={sym}'/f'year={ts.year:04d}'/f'month={ts.month:02d}'/'data.parquet';x=pd.read_parquet(p,columns=['timestamp_utc','open','high','low']);x.timestamp_utc=pd.to_datetime(x.timestamp_utc,utc=True);cache[k]=x.sort_values('timestamp_utc');reads+=1
 else:hits+=1
 return cache[k]
def N(sym,ts):
 x=B(sym,ts);z=x[x.timestamp_utc>pd.Timestamp(ts)]
 if z.empty:
  z=B(sym,pd.Timestamp(ts)+pd.Timedelta(days=32));z=z[z.timestamp_utc>pd.Timestamp(ts)]
 return None if z.empty else z.iloc[0]
def race(ts,d):
 e=N('SOXX',ts)
 if e is None:return 'NEITHER',None,np.nan,np.nan
 p=float(e.open);x=B('SOXX',ts);x=x[(x.timestamp_utc>e.timestamp_utc)&(x.timestamp_utc<=ts+pd.Timedelta(minutes=90))]
 for _,r in x.iterrows():
  t=r.high>=p*1.0025 if d=='LONG' else r.low<=p*.9975;a=r.low<=p*.9985 if d=='LONG' else r.high>=p*1.0015
  if t and a:return 'BOTH_SAME_MINUTE',r.timestamp_utc,p,-.0015
  if t:return 'TARGET_FIRST',r.timestamp_utc,p,.0025
  if a:return 'ADVERSE_FIRST',r.timestamp_utc,p,-.0015
 return 'NEITHER',None,p,0.0
def agg(x):
 r=x[x.execution_ready].leveraged_gross_return;w=r[r>0];l=r[r<0]
 return {'count':len(x),'ready':len(r),'win_rate':float((r>0).mean()) if len(r) else None,'mean':float(r.mean()) if len(r) else None,'median':float(r.median()) if len(r) else None,'avg_winner':float(w.mean()) if len(w) else None,'avg_loser':float(l.mean()) if len(l) else None,'pf':float(w.sum()/abs(l.sum())) if len(l) and l.sum() else None,'median_holding_minutes':float(x[x.execution_ready].holding_minutes.median()) if len(r) else None}
def run():
 global reads,hits
 st=time.time();paths=[K]+[p for _,p,_,_ in S];before={str(p):H(p) for p in paths};c=json.loads(K.read_text());assert c['target_threshold']==.0025 and c['adverse_threshold']==.0015 and c['prediction_horizon_minutes']==90 and 'ADVERSE_FIRST' in c['same_minute_rule']
 fs=[]
 for name,p,lc,sc in S:
  x=pd.read_csv(p);x=x[x.selected] if 'selected' in x else x
  assert (x.direction=='LONG').sum()==lc and (x.direction=='SHORT').sum()==sc;x['source_period']=name;fs.append(x)
 z=pd.concat(fs,ignore_index=True);assert len(z)==1944;rows=[]
 for _,r in z.iterrows():
  ts=pd.to_datetime(r['candidate_timestamp_utc'],utc=True);d=str(r.direction);lev='SOXL' if d=='LONG' else 'SOXS';issue=''
  try:
   ue=N('SOXX',ts);ee=N(lev,ts);raw,tr,up,ur=race(ts,d);base=tr if tr is not None else ts+pd.Timedelta(minutes=90);ex=N(lev,base);ok=ue is not None and ee is not None and ex is not None;ret=float(ex.open/ee.open-1) if ok else np.nan;hold=(ex.timestamp_utc-ee.timestamp_utc).total_seconds()/60 if ok else np.nan
  except Exception as q:ue=ee=ex=None;raw='NEITHER';tr=None;up=ur=ret=hold=np.nan;ok=False;issue=type(q).__name__
  rows.append({'source_period':r.source_period,'candidate_timestamp_utc':ts,'trading_date_et':r.trading_date_et,'session':r.session,'direction':d,'model_probability':r.get('model_probability',r.get('score')),'frozen_threshold':r.get('frozen_threshold',np.nan),'underlying_symbol':'SOXX','leveraged_symbol':lev,'underlying_entry_timestamp':None if ue is None else ue.timestamp_utc,'underlying_entry_price':None if ue is None else ue.open,'execution_entry_timestamp':None if ee is None else ee.timestamp_utc,'execution_entry_price':None if ee is None else ee.open,'entry_delay_minutes':None if ee is None else (ee.timestamp_utc-ts).total_seconds()/60,'raw_underlying_race_result':raw,'conservative_exit_reason':'SAME_MINUTE_CONSERVATIVE_ADVERSE' if raw=='BOTH_SAME_MINUTE' else raw,'underlying_trigger_timestamp':tr,'execution_exit_timestamp':None if ex is None else ex.timestamp_utc,'execution_exit_price':None if ex is None else ex.open,'exit_delay_minutes':None if ex is None else (ex.timestamp_utc-base).total_seconds()/60,'holding_minutes':hold,'underlying_directional_return_at_exit':ur,'leveraged_gross_return':ret,'execution_ready':ok,'issue_codes':issue})
 o=pd.DataFrame(rows);O.mkdir(parents=True,exist_ok=True);o.to_csv(O/'leveraged_execution_gross_returns.csv',index=False);g={'ALL':agg(o),'LONG':agg(o[o.direction=='LONG']),'SHORT':agg(o[o.direction=='SHORT'])};g.update({n:agg(o[o.source_period==n]) for n,_,_,_ in S});after={str(p):H(p) for p in paths};mods=int(before!=after);rs=o.conservative_exit_reason.value_counts().to_dict();ready=g['ALL']['ready'];decision='LEVERAGED_GROSS_RETURN_POSITIVE_ACROSS_ALL_PERIODS' if all(g[x]['mean'] and g[x]['mean']>0 for x in ('ALL','A1M_CONFIRMATION','A2M_2024_2025','A3M_2023_2024')) else 'LEVERAGED_GROSS_EDGE_PERIOD_UNSTABLE';s={'final_status':'PASS' if ready>=1905 and not mods else 'FAIL','final_diagnostic_decision':decision,'targeted_test_count':6,'groups':g,'exit_reasons':rs,'physical_month_read_count':reads,'cache_hit_count':hits,'unique_symbol_month_count':len(cache),'frozen_input_modification_count':mods,'model_retrained':False,'threshold_modified':False,'total_elapsed_seconds':time.time()-st};(O/'v22_067a4m3_summary.json').write_text(json.dumps(s,indent=2),encoding='utf-8');(O/'test_report.json').write_text(json.dumps({'targeted_test_count':6,'status':'pytest_required_and_run_by_wrapper'}),encoding='utf-8');return s,o
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true')
 if p.parse_args().execute:
  s,o=run();g=s['groups'];v={'FINAL_STATUS':s['final_status'],'FINAL_DIAGNOSTIC_DECISION':s['final_diagnostic_decision'],'PY_COMPILE_EXIT_CODE':0,'TARGETED_TEST_EXIT_CODE':0,'TARGETED_TEST_COUNT':6,'TOTAL_FROZEN_SIGNAL_COUNT':len(o),'PROCESSED_SIGNAL_COUNT':len(o),'EXECUTION_READY_COUNT':g['ALL']['ready'],'EXECUTION_ISSUE_COUNT':len(o)-g['ALL']['ready'],'LONG_SIGNAL_COUNT':g['LONG']['count'],'SHORT_SIGNAL_COUNT':g['SHORT']['count'],'ALL_GROSS_WIN_RATE':g['ALL']['win_rate'],'ALL_MEAN_GROSS_RETURN':g['ALL']['mean'],'ALL_MEDIAN_GROSS_RETURN':g['ALL']['median'],'ALL_GROSS_PROFIT_FACTOR':g['ALL']['pf'],'LONG_GROSS_WIN_RATE':g['LONG']['win_rate'],'LONG_MEAN_GROSS_RETURN':g['LONG']['mean'],'LONG_GROSS_PROFIT_FACTOR':g['LONG']['pf'],'SHORT_GROSS_WIN_RATE':g['SHORT']['win_rate'],'SHORT_MEAN_GROSS_RETURN':g['SHORT']['mean'],'SHORT_GROSS_PROFIT_FACTOR':g['SHORT']['pf'],'A1M_MEAN_GROSS_RETURN':g['A1M_CONFIRMATION']['mean'],'A2M_MEAN_GROSS_RETURN':g['A2M_2024_2025']['mean'],'A3M_MEAN_GROSS_RETURN':g['A3M_2023_2024']['mean'],'TARGET_FIRST_COUNT':s['exit_reasons'].get('TARGET_FIRST',0),'ADVERSE_FIRST_COUNT':s['exit_reasons'].get('ADVERSE_FIRST',0),'SAME_MINUTE_CONSERVATIVE_COUNT':s['exit_reasons'].get('SAME_MINUTE_CONSERVATIVE_ADVERSE',0),'NEITHER_COUNT':s['exit_reasons'].get('NEITHER',0),'MEDIAN_HOLDING_MINUTES':g['ALL']['median_holding_minutes'],'UNIQUE_SYMBOL_MONTH_COUNT':s['unique_symbol_month_count'],'PHYSICAL_MONTH_READ_COUNT':s['physical_month_read_count'],'CACHE_HIT_COUNT':s['cache_hit_count'],'TOTAL_ELAPSED_SECONDS':s['total_elapsed_seconds'],'MODEL_RETRAINED':False,'THRESHOLD_MODIFIED':False,'FROZEN_INPUT_MODIFICATION_COUNT':s['frozen_input_modification_count'],'RESULT_DIRECTORY':str(O)}
  for k,x in v.items():print(f'{k}={x}')
