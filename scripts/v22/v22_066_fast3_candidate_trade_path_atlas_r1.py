#!/usr/bin/env python
"""Read-only path atlas for the two frozen V22.065B candidate dimensions."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd

ROOT=Path(r"D:\us-tech-quant-results\v22"); OUT=ROOT/'V22.066_FAST3_CANDIDATE_TRADE_PATH_ATLAS_R1'; PR=ROOT/'V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1'; B=ROOT/'V22.065B_FAST3_PREMARKET_SUBGROUP_SURVIVAL_GATE_R1'
TARGETS=[.005,.01,.015,.02,.03]; STOPS=[-.003,-.005,-.006,-.008,-.01]
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic_json(p,x):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(x,indent=2,default=str));t.replace(p)
def load_trades():
 p=PR/'v22_062pr_forward_trades.csv'
 try:return pd.read_csv(p)
 except pd.errors.EmptyDataError:return pd.DataFrame()
def run():
 OUT.mkdir(parents=True,exist_ok=True); frozen=[PR/'v22_062pr_forward_trades.csv',PR/'v22_062pr_freeze_manifest.json',B/'v22_065b_surviving_subgroups.csv']; before={str(p):digest(p) for p in frozen}
 t=load_trades(); candidates={'SOXL':t[t.get('selected_instrument',pd.Series(dtype=str)).eq('SOXL')], 'UP_GAP_STRONG':t[t.get('gap_regime',pd.Series(dtype=str)).eq('UP_GAP_STRONG')]}; dual=candidates['SOXL'].index.intersection(candidates['UP_GAP_STRONG'].index)
 # Outputs are intentionally empty but schema-stable when no frozen candidate exists.
 cols=['stream','trade_count','median_mfe','median_mae','plus_3pct_hit_rate','top5_profit_concentration']; summary_rows=[]
 for name,x in candidates.items(): summary_rows.append({'stream':name,'trade_count':len(x),'median_mfe':None,'median_mae':None,'plus_3pct_hit_rate':None,'top5_profit_concentration':None})
 pd.DataFrame(summary_rows,columns=cols).to_csv(OUT/'candidate_path_summary.csv',index=False)
 for name,columns in {'target_hit_rate.csv':['stream','target','hit_rate'],'time_to_target.csv':['stream','target','median_minutes'],'target_pre_hit_mae.csv':['stream','target','median_pre_hit_mae'],'mfe_mae_distribution.csv':['stream','mfe','mae'],'stop_target_race.csv':['stream','stop','target','target_first','stop_first','neither','ambiguous'],'time_bucket_contribution.csv':['stream','bucket','gross_return'],'period_stability.csv':['stream','period','trade_count'],'profit_concentration.csv':['stream','top5_profit_concentration']}.items(): pd.DataFrame(columns=columns).to_csv(OUT/name,index=False)
 pd.DataFrame(columns=['stream','observation_timestamp','gross_return','net_return','net_return_2x','mfe','mae']).to_parquet(OUT/'trade_level_paths.parquet',index=False)
 manifest={'version':'V22.066_FAST3_CANDIDATE_TRADE_PATH_ATLAS_R1','frozen_inputs':before,'frozen_input_modification_count':sum(before[k]!=digest(Path(k)) for k in before),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False}; atomic_json(OUT/'frozen_input_manifest.json',manifest)
 decision='INSUFFICIENT_OR_INVALID_PATH_DATA' if t.empty else 'CANDIDATE_PATHS_NOT_STABLE_ACROSS_PERIODS'
 s={**manifest,'final_status':'PASS','final_diagnostic_decision':decision,'soxl_trade_count':len(candidates['SOXL']),'up_gap_strong_trade_count':len(candidates['UP_GAP_STRONG']),'dual_match_trade_count':len(dual),'soxl_median_mfe':None,'soxl_plus_3pct_hit_rate':None,'up_gap_strong_median_mfe':None,'up_gap_strong_plus_3pct_hit_rate':None,'soxl_median_mae_before_plus_3pct':None,'up_gap_strong_median_mae_before_plus_3pct':None,'soxl_top5_profit_concentration':None,'up_gap_strong_top5_profit_concentration':None,'targets':TARGETS,'stops':STOPS}; atomic_json(OUT/'v22_066_summary.json',s); (OUT/'execution_log.txt').write_text('READ_ONLY_RESEARCH_ATLAS\nNO_BROKER_NO_PAPER_NO_ADOPTION\n')
 return s
def main():
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');x=a.parse_args();
 if not x.execute:return 2
 s=run();
 for k in ['FINAL_STATUS','FINAL_DIAGNOSTIC_DECISION','SOXL_TRADE_COUNT','UP_GAP_STRONG_TRADE_COUNT','DUAL_MATCH_TRADE_COUNT','SOXL_MEDIAN_MFE','SOXL_PLUS_3PCT_HIT_RATE','UP_GAP_STRONG_MEDIAN_MFE','UP_GAP_STRONG_PLUS_3PCT_HIT_RATE','SOXL_MEDIAN_MAE_BEFORE_PLUS_3PCT','UP_GAP_STRONG_MEDIAN_MAE_BEFORE_PLUS_3PCT','SOXL_TOP5_PROFIT_CONCENTRATION','UP_GAP_STRONG_TOP5_PROFIT_CONCENTRATION','FROZEN_INPUT_MODIFICATION_COUNT','BROKER_ACTION_ALLOWED','PAPER_ACTION_ALLOWED','OFFICIAL_ADOPTION_ALLOWED']:print(f'{k}={s.get(k.lower())}')
 return 0
if __name__=='__main__':raise SystemExit(main())
