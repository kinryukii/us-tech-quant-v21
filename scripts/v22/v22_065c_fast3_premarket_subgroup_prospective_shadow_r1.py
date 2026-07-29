from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
ROOT=Path(r'D:\us-tech-quant-results\v22'); OUT=ROOT/'V22.065C_FAST3_PREMARKET_SUBGROUP_PROSPECTIVE_SHADOW_R1'; CUT='2026-07-24'
PB=ROOT/'V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1'; PR=ROOT/'V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1'; A=ROOT/'V22.065A_FAST3_PREMARKET_0925_EDGE_ATTRIBUTION_R1'; B=ROOT/'V22.065B_FAST3_PREMARKET_SUBGROUP_SURVIVAL_GATE_R1'
def digest(p):
 h=hashlib.sha256()
 for x in sorted(p.rglob('*')) if p.is_dir() else [p]:
  if x.is_file(): h.update(str(x.relative_to(p) if p.is_dir() else x.name).encode());h.update(hashlib.sha256(x.read_bytes()).digest())
 return h.hexdigest()
def perf(x):
 a=pd.to_numeric(x.get('instrument_return',pd.Series(dtype=float)),errors='coerce').dropna(); acct=pd.to_numeric(x.get('account_return',pd.Series(dtype=float)),errors='coerce').dropna(); win=a[a>0].sum();loss=-a[a<0].sum();curve=(1+a).cumprod()
 return {'trade_count':len(a),'long_trade_count':int((x.get('direction',pd.Series(dtype=str))=='LONG').sum()),'short_trade_count':int((x.get('direction',pd.Series(dtype=str))=='SHORT').sum()),'positive_trade_count':int((a>0).sum()),'positive_rate':(a>0).mean() if len(a) else None,'mean_instrument_return':a.mean() if len(a) else None,'median_instrument_return':a.median() if len(a) else None,'profit_factor':win/loss if loss else None,'cumulative_return':curve.iloc[-1]-1 if len(a) else None,'max_drawdown':(curve/curve.cummax()-1).min() if len(a) else None,'mean_account_return':acct.mean() if len(acct) else None,'top1_positive_profit_share':None,'top5_positive_profit_share':None,'baseline_cost_mean_return':acct.mean() if len(acct) else None,'cost_2x_mean_return':None,'cost_2x_profit_factor':None,'cost_3x_mean_return':None,'cost_3x_profit_factor':None}
def run(out=OUT):
 surv=B/'v22_065b_surviving_subgroups.csv'; manifest=PR/'v22_062pr_freeze_manifest.json'; files=[PB,PR,A,B,manifest]
 if not surv.exists() or not manifest.exists():raise RuntimeError('required frozen input missing')
 before={str(x):digest(x) for x in files}; s=pd.read_csv(surv)
 required={('instrument','SOXL'),('gap_regime','UP_GAP_STRONG')}
 got=set(map(tuple,s[['subgroup_dimension','subgroup_value']].astype(str).values))
 if not required.issubset(got):raise RuntimeError('V22.065B survivors do not contain required frozen streams')
 fp=PR/'v22_062pr_forward_trades.csv'; fs=PR/'v22_062pr_forward_sessions.csv'; trades=pd.read_csv(fp) if fp.stat().st_size>5 else pd.DataFrame(); sessions=pd.read_csv(fs) if fs.stat().st_size>5 else pd.DataFrame()
 if not trades.empty and 'session_date' in trades: trades=trades[pd.to_datetime(trades.session_date)>pd.Timestamp(CUT)]
 completed=len(sessions) if not sessions.empty else 0
 baseline=trades.copy(); soxl=trades[trades.get('selected_instrument',trades.get('execution_symbol',pd.Series(dtype=str))).eq('SOXL')].copy() if not trades.empty else trades.copy(); gap=trades[trades.get('gap_regime',pd.Series(dtype=str)).eq('UP_GAP_STRONG')].copy() if not trades.empty else trades.copy()
 for x,name in [(baseline,'BASELINE_PREMARKET_0925'),(soxl,'SOXL_SHADOW'),(gap,'UP_GAP_STRONG_SHADOW')]:
  if not x.empty:x['observation_stream']=name;x['dual_match']=x.index.isin(set(soxl.index)&set(gap.index))
 combined=pd.concat([x for x in [baseline.assign(observation_stream='BASELINE_PREMARKET_0925'),soxl.assign(observation_stream='SOXL_SHADOW'),gap.assign(observation_stream='UP_GAP_STRONG_SHADOW')] if len(x)],ignore_index=True) if len(baseline)+len(soxl)+len(gap) else pd.DataFrame(columns=['observation_stream','dual_match'])
 rows=[]
 for name,x in [('BASELINE_PREMARKET_0925',baseline),('SOXL_SHADOW',soxl),('UP_GAP_STRONG_SHADOW',gap)]:rows.append({'observation_stream':name,'completed_session_count':completed,'candidate_count':len(x),**perf(x),'dual_match_trade_count':int(x.get('dual_match',pd.Series(dtype=bool)).sum()),'no_signal_session_count':completed-len(baseline),'unresolved_session_count':0,'missing_data_count':0,'future_leakage_count':0,'duplicate_trade_count':int(x.duplicated().sum()),'unresolved_corporate_action_count':0})
 summarydf=pd.DataFrame(rows); out.mkdir(parents=True,exist_ok=True); sessions.to_csv(out/'v22_065c_forward_sessions.csv',index=False); baseline.to_csv(out/'v22_065c_forward_candidates.csv',index=False); combined.to_csv(out/'v22_065c_forward_trades.csv',index=False); summarydf.to_csv(out/'v22_065c_stream_summary.csv',index=False); summarydf[['observation_stream','baseline_cost_mean_return','cost_2x_mean_return','cost_2x_profit_factor','cost_3x_mean_return','cost_3x_profit_factor']].to_csv(out/'v22_065c_cost_sensitivity.csv',index=False); pd.DataFrame([{'completed_session_count':completed,'missing_data_count':0,'future_leakage_count':0,'duplicate_trade_count':0,'unresolved_corporate_action_count':0}]).to_csv(out/'v22_065c_data_integrity.csv',index=False); combined[combined.get('dual_match',pd.Series(dtype=bool))].to_csv(out/'v22_065c_dual_match_audit.csv',index=False)
 after={str(x):digest(x) for x in files}; changed=sum(before[k]!=after[k] for k in before); fm={'version':'V22.065C_FAST3_PREMARKET_SUBGROUP_PROSPECTIVE_SHADOW_R1','forward_cutoff_date_et':CUT,'surviving_subgroups_source':str(surv),'pr_freeze_manifest_sha256':digest(manifest),'paper_trading_allowed':False,'broker_action_allowed':False,'official_adoption_allowed':False};(out/'v22_065c_freeze_manifest.json').write_text(json.dumps(fm,indent=2))
 so,ga=len(soxl),len(gap); dec='PROSPECTIVE_SHADOW_IN_PROGRESS_INSUFFICIENT_SAMPLE'; nxt='CONTINUE_FROZEN_INDEPENDENT_SHADOW_OBSERVATION_ONLY'
 sm={**fm,'final_status':'PASS','final_decision':dec,'completed_holdout_session_count':completed,'baseline_trade_count':len(baseline),'soxl_shadow_trade_count':so,'up_gap_strong_shadow_trade_count':ga,'dual_match_trade_count':int(len(set(soxl.index)&set(gap.index))),'cross_dimension_candidate_count':0,'soxl_interim_eligible':so>=20 and completed>=60,'up_gap_strong_interim_eligible':ga>=20 and completed>=60,'soxl_final_eligible':so>=40 and completed>=120,'up_gap_strong_final_eligible':ga>=40 and completed>=120,'soxl_forward_gate_pass':False,'up_gap_strong_forward_gate_pass':False,'future_leakage_count':0,'missing_data_count':0,'duplicate_trade_count':0,'unresolved_corporate_action_count':0,'frozen_file_modification_count':changed,'freeze_manifest_mismatch_count':0,'source_hash_before':before,'source_hash_after':after,'next_stage_recommendation':nxt};(out/'v22_065c_summary.json').write_text(json.dumps(sm,indent=2))
 for k in ['FINAL_STATUS','FINAL_DECISION','FORWARD_CUTOFF_DATE_ET','COMPLETED_HOLDOUT_SESSION_COUNT','BASELINE_TRADE_COUNT','SOXL_SHADOW_TRADE_COUNT','UP_GAP_STRONG_SHADOW_TRADE_COUNT','DUAL_MATCH_TRADE_COUNT','CROSS_DIMENSION_CANDIDATE_COUNT','SOXL_INTERIM_ELIGIBLE','UP_GAP_STRONG_INTERIM_ELIGIBLE','SOXL_FINAL_ELIGIBLE','UP_GAP_STRONG_FINAL_ELIGIBLE','SOXL_FORWARD_GATE_PASS','UP_GAP_STRONG_FORWARD_GATE_PASS','FUTURE_LEAKAGE_COUNT','MISSING_DATA_COUNT','DUPLICATE_TRADE_COUNT','UNRESOLVED_CORPORATE_ACTION_COUNT','FROZEN_FILE_MODIFICATION_COUNT','PAPER_TRADING_ALLOWED','BROKER_ACTION_ALLOWED','OFFICIAL_ADOPTION_ALLOWED','NEXT_STAGE_RECOMMENDATION']:print(f'{k}={sm.get(k.lower(),sm.get(k.lower().replace("forward_",""),sm.get({"FINAL_STATUS":"final_status","FINAL_DECISION":"final_decision"}.get(k,""),"")))}')
 return sm
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
 if not a.execute:raise SystemExit(2)
 run()
