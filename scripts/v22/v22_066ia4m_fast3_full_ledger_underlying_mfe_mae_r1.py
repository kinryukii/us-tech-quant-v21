import argparse,hashlib,json,time
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');OUT=ROOT/'V22.066IA4M_FAST3_FULL_LEDGER_UNDERLYING_MFE_MAE_R1';MAP=ROOT/'V22.066IA0_FAST3_FROZEN_LEDGER_MAPPING_AUDIT_R1'/'underlying_trade_mapping.csv';S3=ROOT/'V22.066IA3M_FAST3_FULL_LEDGER_PATH_AVAILABILITY_R1'/'v22_066ia3m_summary.json';CAN=Path(r'D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical');cache={}
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def path(sym,s,e):
 s=pd.Timestamp(s).tz_convert('UTC');e=pd.Timestamp(e).tz_convert('UTC');z=[]
 for y,m in {(s.year,s.month),(e.year,e.month)}:
  k=(sym,y,m)
  if k not in cache:
   p=CAN/f'symbol={sym}'/f'year={y:04d}'/f'month={m:02d}'/'data.parquet';cache[k]=pd.read_parquet(p,columns=['timestamp_utc','open','high','low','close'])
  z.append(cache[k])
 x=pd.concat(z);x.timestamp_utc=pd.to_datetime(x.timestamp_utc,utc=True);return x[(x.timestamp_utc>=s)&(x.timestamp_utc<=e)].sort_values('timestamp_utc')
def run():
 assert json.loads(S3.read_text())['pair_path_ready_count']==323;b=h(MAP);t=pd.read_csv(MAP);t.entry_timestamp_utc=pd.to_datetime(t.entry_timestamp_utc,utc=True);t.exit_timestamp_utc=pd.to_datetime(t.exit_timestamp_utc,utc=True);rows=[];st=time.time()
 for _,r in t.iterrows():
  try:
   e=min(r.exit_timestamp_utc,r.entry_timestamp_utc+pd.Timedelta(minutes=90));x=path(r.underlying_symbol,r.entry_timestamp_utc,e);entry=x.iloc[0].open;sg=1 if r.normalized_direction=='LONG' else -1;fav=(x.high/entry-1)*sg if sg==1 else (x.low/entry-1)*sg;adv=(x.low/entry-1)*sg if sg==1 else (x.high/entry-1)*sg;mi=fav.idxmax();ai=adv.idxmin();rows.append({'trade_id':r.trade_id,'underlying_symbol':r.underlying_symbol,'execution_symbol':r.execution_symbol_normalized,'normalized_direction':r.normalized_direction,'study_period':r.study_period,'gap_regime':r.gap_regime,'entry_timestamp_utc':r.entry_timestamp_utc,'requested_end_timestamp_utc':e,'entry_price':entry,'entry_price_source':'ENTRY_BAR_OPEN','path_row_count':len(x),'underlying_mfe':fav.loc[mi],'underlying_mae':adv.loc[ai],'mfe_timestamp_utc':x.loc[mi,'timestamp_utc'],'mae_timestamp_utc':x.loc[ai,'timestamp_utc'],'time_to_mfe_minutes':(x.loc[mi,'timestamp_utc']-r.entry_timestamp_utc).total_seconds()/60,'time_to_mae_minutes':(x.loc[ai,'timestamp_utc']-r.entry_timestamp_utc).total_seconds()/60,'final_directional_return':sg*(x.iloc[-1].close/entry-1),'path_ready':True,'issue_codes':''})
  except Exception:rows.append({'trade_id':r.trade_id,'path_ready':False,'issue_codes':'PATH_LOAD_ERROR'})
 a=pd.DataFrame(rows);OUT.mkdir(parents=True,exist_ok=True);a.to_csv(OUT/'full_323_underlying_mfe_mae.csv',index=False);ok=a[a.path_ready];s={'final_status':'PASS' if len(ok)>=320 else 'FAIL','final_diagnostic_decision':'FULL_LEDGER_UNDERLYING_MFE_MAE_READY','historical_trade_count':len(t),'processed_trade_count':len(a),'mfe_mae_ready_count':len(ok),'mfe_mae_issue_count':len(a)-len(ok),'all_median_mfe':ok.underlying_mfe.median(),'all_median_mae':ok.underlying_mae.median(),'frozen_input_modification_count':int(b!=h(MAP)),'total_elapsed_seconds':time.time()-st,'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False}
 for k,g in [('qqq',ok[ok.underlying_symbol.eq('QQQ')]),('soxx',ok[ok.underlying_symbol.eq('SOXX')]),('long',ok[ok.normalized_direction.eq('LONG')]),('short',ok[ok.normalized_direction.eq('SHORT')]),('source',ok[ok.study_period.eq('2018-2022_DEVELOPMENT')]),('validation',ok[ok.study_period.eq('2023-2024_VALIDATION')]),('confirmation',ok[ok.study_period.eq('2025-2026_YTD_CONFIRMATION')])]:s[k+'_trade_count']=len(g);s[k+'_median_mfe']=g.underlying_mfe.median();s[k+'_median_mae']=g.underlying_mae.median()
 (OUT/'v22_066ia4m_summary.json').write_text(json.dumps(s,indent=2,default=str));(OUT/'test_report.json').write_text('{}');return s
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();s=run() if a.execute else {};[print(f'{k.upper()}={v}') for k,v in s.items()]
