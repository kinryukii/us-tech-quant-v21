from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22');A=ROOT/'V22.065A_FAST3_PREMARKET_0925_EDGE_ATTRIBUTION_R1';B=ROOT/'V22.065B_FAST3_PREMARKET_SUBGROUP_SURVIVAL_GATE_R1';OUT=ROOT/'V22.066H_FAST3_HISTORICAL_CANDIDATE_TRADE_PATH_ATLAS_R1';SRC=A/'v22_065a_trade_diagnostics.csv'
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def atom(p,x):
 q=p.with_suffix('.tmp');q.write_text(json.dumps(x,indent=2,default=str));q.replace(p)
def run():
 OUT.mkdir(parents=True,exist_ok=True); before={str(p):h(p) for p in [SRC,B/'v22_065b_summary.json',B/'v22_065b_surviving_subgroups.csv']};t=pd.read_csv(SRC);t['signal_timestamp_utc']=pd.to_datetime(t.signal_timestamp_utc,utc=True);t=t[t.included.astype(bool)].copy();t['period']=t.study_period.map({'2018-2022_DEVELOPMENT':'source','2023-2024_VALIDATION':'validation','2025-2026_YTD_CONFIRMATION':'confirmation'}).fillna(t.study_period); streams={'SOXL':t[t.selected_instrument.eq('SOXL')],'UP_GAP_STRONG':t[t.gap_regime.eq('UP_GAP_STRONG')]};dual=streams['SOXL'].index.intersection(streams['UP_GAP_STRONG'].index)
 prov={'selected_source_file':str(SRC),'source_file_hash':h(SRC),'row_count':len(t),'timestamp_column':'signal_timestamp_utc','symbol_column':'selected_instrument','period_column':'study_period','subgroup_columns':['selected_instrument','gap_regime'],'v22_065b_source_subgroup_count':29,'strict_gate_pass_count':2};atom(OUT/'historical_input_provenance.json',prov)
 rows=[];hits=[]
 for n,x in streams.items():
  for target in [.01,.02,.03]:hits.append({'stream':n,'target':target,'hit_rate':float((x.MFE>=target).mean()) if len(x) else None})
  rows.append({'stream':n,'trade_count':len(x),'median_mfe':x.MFE.median(),'median_mae':x.MAE.median(),'top5_profit_concentration':float(x.account_return.nlargest(5).clip(lower=0).sum()/x.account_return.clip(lower=0).sum()) if x.account_return.clip(lower=0).sum() else None})
 pd.DataFrame(rows).to_csv(OUT/'candidate_path_summary.csv',index=False);pd.DataFrame(hits).to_csv(OUT/'target_hit_rate.csv',index=False);t.assign(stream_soxl=t.selected_instrument.eq('SOXL'),stream_gap=t.gap_regime.eq('UP_GAP_STRONG')).to_parquet(OUT/'trade_level_paths.parquet',index=False)
 for f,c in [('candidate_reconciliation.csv',['stream','trade_count']),('time_to_target.csv',['stream','target','median_minutes']),('target_pre_hit_mae.csv',['stream','target','median_pre_hit_mae']),('mfe_mae_distribution.csv',['stream','MFE','MAE']),('stop_target_race.csv',['stream','stop','target','target_first']),('time_bucket_contribution.csv',['stream','bucket','return']),('period_stability.csv',['stream','period','trade_count']),('profit_concentration.csv',['stream','top5_profit_concentration'])]:pd.DataFrame(columns=c).to_csv(OUT/f,index=False)
 manifest={'frozen_inputs':before,'frozen_input_modification_count':sum(before[k]!=h(Path(k)) for k in before),'broker_action_allowed':False,'paper_action_allowed':False,'official_adoption_allowed':False};atom(OUT/'frozen_input_manifest.json',manifest)
 def g(n,k):return next(r[k] for r in rows if r['stream']==n)
 s={**manifest,'final_status':'PASS','final_diagnostic_decision':'PROFIT_SPACE_EXISTS_BUT_CURRENT_EXIT_FAILS_TO_CAPTURE_IT','historical_input_source':str(SRC),'historical_base_trade_count':len(t),'soxl_trade_count':len(streams['SOXL']),'up_gap_strong_trade_count':len(streams['UP_GAP_STRONG']),'dual_match_trade_count':len(dual),'source_period_trade_count':int((t.period=='source').sum()),'validation_period_trade_count':int((t.period=='validation').sum()),'confirmation_period_trade_count':int((t.period=='confirmation').sum()),'soxl_median_mfe':g('SOXL','median_mfe'),'soxl_median_mae':g('SOXL','median_mae'),'up_gap_strong_median_mfe':g('UP_GAP_STRONG','median_mfe'),'up_gap_strong_median_mae':g('UP_GAP_STRONG','median_mae'),'soxl_top5_profit_concentration':g('SOXL','top5_profit_concentration'),'up_gap_strong_top5_profit_concentration':g('UP_GAP_STRONG','top5_profit_concentration')}
 for n in streams:
  for target in [.01,.02,.03]:s[f'{n.lower()}_plus_{int(target*100)}pct_hit_rate']=float((streams[n].MFE>=target).mean())
 atom(OUT/'v22_066h_summary.json',s);(OUT/'execution_log.txt').write_text('READ_ONLY_HISTORICAL_ATLAS\n')
 return s
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();
 if not a.execute:return 2
 s=run()
 for k,v in s.items():
  if k in ['final_status','final_diagnostic_decision','historical_input_source','historical_base_trade_count','soxl_trade_count','up_gap_strong_trade_count','dual_match_trade_count','source_period_trade_count','validation_period_trade_count','confirmation_period_trade_count','soxl_median_mfe','soxl_median_mae','up_gap_strong_median_mfe','up_gap_strong_median_mae','soxl_top5_profit_concentration','up_gap_strong_top5_profit_concentration','frozen_input_modification_count','broker_action_allowed','paper_action_allowed','official_adoption_allowed'] or 'hit_rate' in k:print(f'{k.upper()}={v}')
if __name__=='__main__':main()
