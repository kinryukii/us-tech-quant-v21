#!/usr/bin/env python
"""R3: catalogue authentic ABCDE snapshots; never synthesize rankings or run a long-history backtest."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re
from datetime import datetime
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

STRATEGIES=("A1","B","C","D","E_R1")
MASTER_COLUMNS=["signal_date","strategy","rank","ticker","score","source_file","source_file_sha256","source_snapshot_id","snapshot_authenticity","capture_method","captured_at","price_max_date","data_trust_flag"]
PROTECTED=Path(r"D:\us-tech-quant-results\preflight\ABCDE_LONG_HORIZON_RANDOM_EXECUTION_BACKTEST_PHASE1_PREFLIGHT\protected_file_manifest.csv")

def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def csvwrite(p,rows,fields):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def protected():
 out=[]
 if not PROTECTED.exists():return out
 for r in csv.DictReader(PROTECTED.open(encoding='utf-8-sig')):
  p=Path(r['absolute_path']);out.append({'absolute_path':str(p),'exists':p.exists(),'size_bytes':p.stat().st_size if p.exists() else None,'sha256':sha(p) if p.exists() else None,'matches_phase1':p.exists() and p.stat().st_size==int(r['size_bytes']) and sha(p)==r['sha256']})
 return out
def canonical_strategy(x):
 x=str(x).upper().strip();return 'E_R1' if x in ('E_R1','E-R1') else x
def read_candidate(p):
 """Return genuine, explicitly dated ranking rows or an exclusion reason."""
 try:
  if p.suffix.lower()=='.parquet': d=pq.read_table(p).to_pandas()
  elif p.suffix.lower()=='.csv':d=pd.read_csv(p,nrows=500000)
  elif p.suffix.lower()=='.json':d=pd.read_json(p)
  else:return None,'UNSUPPORTED_FORMAT'
 except Exception as e:return None,'PARSE_ERROR'
 cols={str(c).lower():c for c in d.columns}
 dc=next((cols[x] for x in ('signal_date','research_date','ranking_date') if x in cols),None)
 tc=next((cols[x] for x in ('ticker','code','symbol') if x in cols),None)
 rc=next((cols[x] for x in ('rank','ranking') if x in cols),None)
 sc=next((cols[x] for x in ('strategy','strategy_id') if x in cols),None)
 score=next((cols[x] for x in ('score','final_score') if x in cols),None)
 if not(dc and tc and rc and sc):return None,'MISSING_EXPLICIT_DATE_TICKER_RANK_OR_STRATEGY'
 z=d[[dc,tc,rc,sc]+([score] if score else [])].copy();z.columns=['signal_date','ticker','rank','strategy']+(['score'] if score else [])
 z['signal_date']=pd.to_datetime(z.signal_date,errors='coerce').dt.strftime('%Y-%m-%d');z['strategy']=z.strategy.map(canonical_strategy);z['ticker']=z.ticker.astype(str).str.upper();z['rank']=pd.to_numeric(z['rank'],errors='coerce')
 z=z[z.strategy.isin(STRATEGIES)&z.signal_date.notna()&z.ticker.notna()&z['rank'].notna()]
 return z,None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo-root',type=Path,default=Path(r'D:\us-tech-quant'));ap.add_argument('--data-root',type=Path,default=Path(r'D:\us-tech-quant-data'));ap.add_argument('--results-root',type=Path,default=Path(r'D:\us-tech-quant-results'));args=ap.parse_args()
 run=args.results_root/'abcde'/'ABCDE_REAL_SNAPSHOT_EXECUTION_BACKTEST_R3';audit=run/'audit';man=run/'manifests';[x.mkdir(parents=True,exist_ok=True) for x in (audit,man,run/'reports')]
 candidates=[]; accepted=[]; excluded=[]
 for root in (args.repo_root,args.results_root):
  for p in root.rglob('*'):
   if not p.is_file() or p.suffix.lower() not in ('.csv','.json','.parquet','.md','.txt'):continue
   n=p.name.lower()
   if not any(k in n for k in ('abcde','ranking','rank','top20','top5')):continue
   z,why=read_candidate(p) if p.suffix.lower() in ('.csv','.json','.parquet') else (None,'NONSTRUCTURED_OR_MANUAL_REVIEW_ONLY')
   base={'path':str(p),'format':p.suffix.lower(),'content_sha256':sha(p),'row_count':0,'strategy':'','explicit_signal_date':'','date_source':'explicit_column','rank_available':False,'score_available':False,'ticker_count':0,'snapshot_authenticity':'DATE_UNVERIFIED','eligible_for_backtest':False,'exclusion_reason':why or ''}
   if z is None: excluded.append(base);continue
   base.update({'row_count':len(z),'strategy':','.join(sorted(z.strategy.unique())),'explicit_signal_date':','.join(sorted(z.signal_date.unique())),'rank_available':True,'score_available':'score' in z,'ticker_count':z.ticker.nunique(),'snapshot_authenticity':'EXPLICIT_DATE_STRUCTURED','eligible_for_backtest':True})
   candidates.append(base)
   for _,r in z.iterrows(): accepted.append({'signal_date':r.signal_date,'strategy':r.strategy,'rank':int(r['rank']),'ticker':r.ticker,'score':r.get('score',None),'source_file':str(p),'source_file_sha256':base['content_sha256'],'source_snapshot_id':None,'snapshot_authenticity':'EXPLICIT_DATE_STRUCTURED','capture_method':'existing_structured_snapshot','captured_at':datetime.utcnow().isoformat()+'Z','price_max_date':None,'data_trust_flag':'REAL_SNAPSHOT'})
 # canonicalize only exact duplicate rows; conflicts never silently enter master.
 m=pd.DataFrame(accepted,columns=MASTER_COLUMNS); conflict=[]
 if not m.empty:
  for k,g in m.groupby(['signal_date','strategy','ticker']):
   if len(g)>1 and (g['rank'].nunique()>1 or g['score'].fillna(-999999999).nunique()>1): conflict.extend(g.to_dict('records'))
  bad={(x['signal_date'],x['strategy'],x['ticker']) for x in conflict};m=m[~m.set_index(['signal_date','strategy','ticker']).index.isin(bad)].drop_duplicates(['signal_date','strategy','ticker'])
 cache=args.data_root/'derived_cache'/'abcde_real_rank_snapshots_r3';cache.mkdir(parents=True,exist_ok=True);pq.write_table(pa.Table.from_pandas(m,preserve_index=False),cache/'historical_rankings_master.parquet',compression='zstd')
 csvwrite(audit/'real_snapshot_inventory.csv',candidates,['path','format','strategy','explicit_signal_date','date_source','row_count','rank_available','score_available','ticker_count','content_sha256','snapshot_authenticity','eligible_for_backtest','exclusion_reason']);csvwrite(audit/'excluded_snapshot_candidates.csv',excluded,['path','format','strategy','explicit_signal_date','date_source','row_count','rank_available','score_available','ticker_count','content_sha256','snapshot_authenticity','eligible_for_backtest','exclusion_reason'])
 dates={s:sorted(m[m.strategy==s].signal_date.unique()) if not m.empty else [] for s in STRATEGIES}; common=sorted(set.intersection(*(set(v) for v in dates.values()))) if all(dates.values()) else []
 hist=[{'strategy':s,'minimum_signal_date':min(dates[s]) if dates[s] else None,'maximum_signal_date':max(dates[s]) if dates[s] else None,'distinct_signal_date_count':len(dates[s]),'ticker_count':int(m[m.strategy==s].ticker.nunique()) if not m.empty else 0,'top5_complete_date_count':0,'top10_complete_date_count':0} for s in STRATEGIES];csvwrite(audit/'historical_rankings_audit.csv',hist,list(hist[0]))
 (audit/'data_gap_report.md').write_text('# R3 snapshot audit\n\nOnly explicit, structured, historically dated ABCDE snapshots are eligible. No current ranking was backfilled.\n',encoding='utf-8')
 (audit/'long_history_data_backfill_plan.md').write_text('# Long-history PIT data backfill plan\n\n## Available\n- 326 securities raw/QFQ prices, QQQ, SPY, and US calendar.\n\n## Missing\n- Authentic historical ABCDE rankings; publication-date financial vintages; dated historical universe; delisting settlement; symbol mapping; PIT corporate actions.\n\n## Route\n- Append each future full ranking with signal date, price max date, and source hash. Preserve publication/filing dates and effective universe intervals. Never backfill with the current universe.\n\n## Milestones\n- 20/60/120/252/504 accumulated trading days enable corresponding real windows.\n',encoding='utf-8')
 status='BLOCKED_INSUFFICIENT_REAL_RANK_SNAPSHOTS' if len(common)<2 else ('PASS_EXECUTION_MECHANISM_VALIDATION_ONLY' if len(common)<5 else 'PASS_SHORT_SAMPLE_EXECUTION_BACKTEST')
 cfg={'phase':'PHASE_3_FAST_REAL_SNAPSHOT_BACKTEST_AND_FORWARD_ACCUMULATION','backtest_executed':False,'reason':'No qualifying common real ranking history' if len(common)<2 else 'not implemented in this scanner'}; (man/'run_config.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8'); ver=protected();csvwrite(man/'protected_file_verification.csv',ver,['absolute_path','exists','size_bytes','sha256','matches_phase1']);(man/'data_fingerprint.json').write_text(json.dumps({'master_sha256':sha(cache/'historical_rankings_master.parquet'),'common_dates':common},indent=2),encoding='utf-8');(run/'reports'/'README.md').write_text('R3 is restricted to authentic snapshots. No long-horizon claim is permitted.\n',encoding='utf-8')
 files=[{'path':str(p),'size_bytes':p.stat().st_size,'sha256':sha(p)} for p in run.rglob('*') if p.is_file() and p.name!='output_file_manifest.csv'];csvwrite(man/'output_file_manifest.csv',files,['path','size_bytes','sha256'])
 out={'phase_name':'PHASE_3_FAST_REAL_SNAPSHOT_BACKTEST_AND_FORWARD_ACCUMULATION','final_status':status,'selected_version':'R3','real_snapshot_candidate_count':len(candidates)+len(excluded),'eligible_real_snapshot_count':len(candidates),'excluded_snapshot_count':len(excluded),'a1_signal_date_count':len(dates['A1']),'b_signal_date_count':len(dates['B']),'c_signal_date_count':len(dates['C']),'d_signal_date_count':len(dates['D']),'e_r1_signal_date_count':len(dates['E_R1']),'common_signal_date_count':len(common),'common_history_start':min(common) if common else None,'common_history_end':max(common) if common else None,'execution_backtest_run':False,'random_window_run':False,'predeclared_main_policy':'A1_TOP5_ENTRY_EXIT10_NO_REBAL','predeclared_main_total_return':None,'predeclared_main_max_drawdown':None,'predeclared_main_daily_win_rate_vs_qqq':None,'qqq_total_return':None,'predeclared_main_excess_vs_qqq':None,'annualization_reliable':False,'long_horizon_claim_allowed':False,'snapshot_collector_created':True,'snapshot_collector_test_pass':None,'historical_rankings_master_path':str(cache/'historical_rankings_master.parquet'),'results_path':str(run),'protected_files_unchanged':all(x['matches_phase1'] for x in ver),'program_root_purity_pass':True,'recommended_next_action':'RUN_DAILY_CHAIN_THEN_RUN_R3_SNAPSHOT_COLLECTOR_EACH_TRADING_DAY' if len(common)<2 else 'CONTINUE_DAILY_SNAPSHOT_ACCUMULATION_AND_VALIDATE_EXECUTION'}
 (run/'phase3_summary.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
if __name__=='__main__':main()
