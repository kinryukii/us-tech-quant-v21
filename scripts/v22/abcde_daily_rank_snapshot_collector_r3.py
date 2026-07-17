#!/usr/bin/env python
"""Append-only external collector; it reads a completed daily directory but never changes it."""
from __future__ import annotations
import argparse, hashlib, json, csv
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from abcde_real_snapshot_execution_backtest_r3 import MASTER_COLUMNS, STRATEGIES, sha
NAME_MAP={'A1_CONTROL':'A1','B_STATIC_MOMENTUM':'B','C_DYNAMIC_MOMENTUM':'C','D_WEIGHT_OPTIMIZED_REFERENCE':'D','E_R1_DEFENSIVE_REFERENCE':'E_R1'}
def norm_strategy(v): return NAME_MAP.get(str(v).strip().upper(),str(v).strip().upper())
def resolve_paths(summary_path: Path, repo: Path):
    """Strict chain order: summary-declared paths, then V21.233 current-run directory."""
    js=json.loads(summary_path.read_text(encoding='utf-8'));paths=[]
    for k in ('abcde_summary_path','v21_233_summary_path','abcde_output_dir','v21_233_output_dir','canonical_snapshot_dir'):
        if js.get(k):
            p=Path(js[k]);paths.extend([p] if p.is_file() else list(p.glob('*ranking*.csv'))+list(p.glob('*ranking*.parquet')))
    v233=repo/'outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN';paths.extend(list(v233.glob('*ranking*.csv'))+list(v233.glob('*ranking*.parquet')) if v233.exists() else [])
    return js,list(dict.fromkeys(paths))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--daily-run-dir',type=Path);ap.add_argument('--repo-root',type=Path,default=Path(r'D:\us-tech-quant'));ap.add_argument('--data-root',type=Path,default=Path(r'D:\us-tech-quant-data'));ap.add_argument('--results-root',type=Path,default=Path(r'D:\us-tech-quant-results'));ap.add_argument('--v22-040-summary-path',type=Path);ap.add_argument('--expected-signal-date');ap.add_argument('--execute',action='store_true');a=ap.parse_args();root=a.data_root/'derived_cache'/'abcde_real_rank_snapshots_r3';root.mkdir(parents=True,exist_ok=True);master=root/'historical_rankings_master.parquet';ledger=root/'capture_ledger.parquet'
 summary=a.v22_040_summary_path or ((a.daily_run_dir and next(iter(a.daily_run_dir.glob('*summary*.json')),None)))
 if not summary or not summary.exists(): raise SystemExit('FAIL_DAILY_SUMMARY_MISSING')
 js,files=resolve_paths(summary,a.repo_root) if a.v22_040_summary_path else (json.loads(summary.read_text(encoding='utf-8')),list(a.daily_run_dir.glob('*ranking*.parquet'))+list(a.daily_run_dir.glob('*ranking*.csv')))
 status=str(js.get('final_status','')).upper()
 if not (status.startswith('PASS') or 'SUCCESS' in status or 'READY' in status): raise SystemExit('FAIL_DAILY_NOT_SUCCESSFUL')
 rows=[]
 for p in files:
  d=pq.read_table(p).to_pandas() if p.suffix=='.parquet' else pd.read_csv(p);cols={str(c).lower():c for c in d.columns};dc=cols.get('research_date') or cols.get('signal_date') or cols.get('latest_date');sc=cols.get('strategy') or cols.get('strategy_id') or cols.get('strategy_name');tc=cols.get('ticker');rc=cols.get('rank');
  if not all((dc,sc,tc,rc)):continue
  for _,r in d.iterrows():
   st=norm_strategy(r[sc]);dt=str(r[dc])[:10]
   if st in STRATEGIES and (not a.expected_signal_date or dt==a.expected_signal_date):rows.append({'signal_date':dt,'strategy':st,'rank':int(r[rc]),'ticker':str(r[tc]),'score':r.get(cols.get('score')),'source_file':str(p),'source_file_sha256':sha(p),'source_snapshot_id':js.get('source_snapshot_id'),'snapshot_authenticity':'DAILY_SUCCESS_OUTPUT','capture_method':'append_only_collector','captured_at':pd.Timestamp.utcnow().isoformat(),'price_max_date':js.get('canonical_latest_date'),'data_trust_flag':js.get('data_trust','UNKNOWN'),'ranking_scope':'FULL_UNIVERSE','full_universe_ranking':True,'daily_run_status':status,'daily_run_summary_path':str(summary),'capture_timestamp':pd.Timestamp.utcnow().isoformat(),'capture_version':'R3'})
 new=pd.DataFrame(rows);old=pq.read_table(master).to_pandas() if master.exists() else pd.DataFrame(columns=MASTER_COLUMNS);conf=0;skip=0
 if new.empty: raise SystemExit('FAIL_ABCDE_OUTPUT_NOT_FOUND')
 if new.duplicated(['signal_date','strategy','ticker']).any() or new.duplicated(['signal_date','strategy','rank']).any() or (new['rank']<=0).any(): raise SystemExit('FAIL_INCOMPLETE_STRATEGY_RANKINGS')
 if set(new.strategy.unique())!=set(STRATEGIES) or any(len(new[(new.strategy==s)&(new['rank']<=10)])<10 for s in STRATEGIES): raise SystemExit('FAIL_INCOMPLETE_STRATEGY_RANKINGS')
 for k,g in new.groupby(['signal_date','strategy','ticker']):
  ex=old[(old.signal_date==k[0])&(old.strategy==k[1])&(old.ticker==k[2])]
  if not ex.empty and ex.source_file_sha256.iloc[0]!=g.source_file_sha256.iloc[0]:conf+=len(g);new=new.drop(g.index)
  elif not ex.empty:skip+=len(g);new=new.drop(g.index)
 merged=pd.concat([old,new],ignore_index=True);pq.write_table(pa.Table.from_pandas(merged,preserve_index=False),master,compression='zstd')
 entry=pd.DataFrame([{'captured_at':pd.Timestamp.utcnow().isoformat(),'daily_run_dir':str(a.daily_run_dir),'captured_row_count':len(new),'duplicate_skipped_count':skip,'conflict_count':conf}]); oldledger=pq.read_table(ledger).to_pandas() if ledger.exists() else pd.DataFrame(columns=entry.columns);pq.write_table(pa.Table.from_pandas(pd.concat([oldledger,entry],ignore_index=True),preserve_index=False),ledger,compression='zstd')
 if conf:
  q=root/'quarantine';q.mkdir(exist_ok=True);new.to_csv(q/('conflict_'+pd.Timestamp.utcnow().strftime('%Y%m%dT%H%M%S')+'.csv'),index=False)
 out={'capture_status':'PASS' if conf==0 else 'CONFLICT_QUARANTINE_REQUIRED','signal_date':new.signal_date.iloc[0] if len(new) else None,'strategy_count':new.strategy.nunique(),'captured_row_count':len(new),'duplicate_skipped_count':skip,'conflict_count':conf,'historical_signal_date_count':merged.signal_date.nunique(),'historical_start_date':merged.signal_date.min() if len(merged) else None,'historical_end_date':merged.signal_date.max() if len(merged) else None,'output_path':str(master)};(root/'latest_capture_status.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
