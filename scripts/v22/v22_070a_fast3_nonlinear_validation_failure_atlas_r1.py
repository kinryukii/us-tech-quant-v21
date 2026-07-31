from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, sys, tempfile
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import ks_2samp, spearmanr

REPO=Path(__file__).resolve().parents[2]; LOCAL=REPO/'.local_results'; DATA=Path(r'D:/us-tech-quant-data/fast3/moomoo_24h_1m')
B1='V22.069B1_FAST3_NONLINEAR_COMPACT_MODEL_MATERIALIZATION_R1'; C='V22.069C_FAST3_NONLINEAR_COMPACT_VALIDATION_R1'; OUT='V22.070A_FAST3_NONLINEAR_VALIDATION_FAILURE_ATLAS_R1'
MODEL_SHA='d92fbddcac00dd3e6e37e76daa3510eda40444cc914d4dc3160c2db0ffd93ce0'; STATE_SHA='e005ee7bb350b768375cf3e11efe968121b60ec370e6222e0693c9374cfe008e'
FEATURES=['PREMARKET_CUM_RETURN','PREMARKET_MAX_DRAWDOWN','PREMARKET_REALIZED_VOLATILITY']; SYMS=['QQQ','SOXX','TQQQ','SQQQ','SOXL','SOXS']; COST=.001

def stable(x): return (json.dumps(x,sort_keys=True,indent=2,default=str)+'\n').encode()
def sha(p):
 d=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): d.update(b)
 return d.hexdigest()
def null(x): return float(x) if x is not None and np.isfinite(x) else None
def roots(upstream, results): return Path(upstream)/'v22'/B1,Path(upstream)/'v22'/C,Path(results)/'v22'/OUT

def check_inputs(upstream):
 b,c,_=roots(upstream,upstream); req=[b/'frozen_model.joblib',b/'frozen_model_state.json',b/'training_contract_manifest.json',b/'development_model_predictions.csv',c/'validation_event_scores.csv',c/'v22_069c_summary.json']
 if any(not p.is_file() for p in req): raise RuntimeError('UPSTREAM_INPUT_MISSING')
 if sha(b/'frozen_model.joblib')!=MODEL_SHA: raise RuntimeError('MODEL_ARTIFACT_SHA256_MISMATCH')
 if sha(b/'frozen_model_state.json')!=STATE_SHA: raise RuntimeError('MODEL_STATE_SHA256_MISMATCH')
 s=json.loads((b/'v22_069b1_summary.json').read_text()); cs=json.loads((c/'v22_069c_summary.json').read_text()); man=json.loads((b/'training_contract_manifest.json').read_text())
 if s.get('final_status')!='PASS' or s.get('model_file_sha256')!=MODEL_SHA or man.get('feature_names')!=FEATURES: raise RuntimeError('B1_CONTRACT_MISMATCH')
 if cs.get('final_status')!='PASS' or cs.get('final_decision')!='NONLINEAR_COMPACT_MODEL_REJECTED_ON_VALIDATION' or cs.get('validation_event_count')!=2400: raise RuntimeError('C_VALIDATION_CONTRACT_MISMATCH')
 return joblib.load(b/'frozen_model.joblib'),pd.read_csv(b/'development_model_predictions.csv'),pd.read_csv(c/'validation_event_scores.csv'),man

def dev_features(man, predictions):
 """Legal diagnostic reconstruction only; no fitting/prediction or model choice."""
 wanted={(r.date,r.symbol) for r in predictions[['date','symbol']].itertuples(index=False)}; rows=[]
 for item in man['input_partitions']:
  path=DATA/item['relative_path']; sym=path.parents[2].name.split('=',1)[1]
  frame=pq.read_table(path,columns=['timestamp_et','open','close']).to_pandas(); t=pd.to_datetime(frame.timestamp_et,utc=True).dt.tz_convert('America/New_York'); frame=frame.assign(timestamp=t).dropna(subset=['timestamp','open','close']); frame['date']=frame.timestamp.dt.date.astype(str)
  for date,day in frame.groupby('date',sort=True):
   if (date,sym) not in wanted: continue
   day=day.sort_values('timestamp'); pre=day[(day.timestamp.dt.time>=pd.Timestamp('04:00').time())&(day.timestamp.dt.time<=pd.Timestamp('09:25').time())]; close=pre.close.astype(float).to_numpy()
   if len(close): rows.append({'date':date,'symbol':sym,'PREMARKET_CUM_RETURN':float(close[-1]/close[0]-1),'PREMARKET_MAX_DRAWDOWN':float(np.min(close/np.maximum.accumulate(close)-1)),'PREMARKET_REALIZED_VOLATILITY':float(np.std(np.diff(np.log(close)),ddof=0))})
 result=pd.DataFrame(rows); out=predictions.merge(result,on=['date','symbol'],validate='one_to_one')
 if len(out)!=7097: raise RuntimeError('DEVELOPMENT_DIAGNOSTIC_RECONSTRUCTION_MISMATCH')
 return out

def spread(g):
 if len(g)<5:return None
 n=max(1,math.ceil(len(g)*.2)); order=np.lexsort((np.arange(len(g)),g.prediction.to_numpy())); return float(g.target_return.to_numpy()[order[-n:]].mean()-g.target_return.to_numpy()[order[:n]].mean()-COST)
def ic(g): return null(spearmanr(g.target_return,g.prediction).statistic) if len(g)>1 else None
def stats(g):
 return {'count':len(g),'ic':ic(g),'net':spread(g),'gross':None if spread(g) is None else spread(g)+COST,'score_mean':null(g.prediction.mean()),'score_std':null(g.prediction.std(ddof=0)),'score_q05':null(g.prediction.quantile(.05)),'score_q50':null(g.prediction.quantile(.5)),'score_q95':null(g.prediction.quantile(.95)),'target_mean':null(g.target_return.mean()),'target_std':null(g.target_return.std(ddof=0)),'target_q05':null(g.target_return.quantile(.05)),'target_q50':null(g.target_return.quantile(.5)),'target_q95':null(g.target_return.quantile(.95))}
def psi(a,b):
 try:
  edges=np.unique(np.quantile(a,np.linspace(0,1,11))); 
  if len(edges)<2:return None,'CONSTANT_DEVELOPMENT_FEATURE'
  edges[0],edges[-1]=-np.inf,np.inf; pa=np.histogram(a,edges)[0]/len(a); pb=np.histogram(b,edges)[0]/len(b); e=1e-8; return float(np.sum((pb-pa)*np.log((pb+e)/(pa+e)))),None
 except Exception as e:return None,str(e)
def feature_drift(d,v):
 rows=[]
 for f in FEATURES:
  a,b=d[f].dropna().to_numpy(),v[f].dropna().to_numpy(); p,reason=psi(a,b); rows.append({'feature':f,'development_mean':null(np.mean(a)),'validation_mean':null(np.mean(b)),'development_std':null(np.std(a)),'validation_std':null(np.std(b)),'development_median':null(np.median(a)),'validation_median':null(np.median(b)),'development_q05':null(np.quantile(a,.05)),'validation_q05':null(np.quantile(b,.05)),'development_q95':null(np.quantile(a,.95)),'validation_q95':null(np.quantile(b,.95)),'development_missing_ratio':float(d[f].isna().mean()),'validation_missing_ratio':float(v[f].isna().mean()),'psi':p,'psi_reason':reason,'ks_statistic':null(ks_2samp(a,b).statistic),'standardized_mean_difference':null((np.mean(b)-np.mean(a))/np.sqrt((np.var(a)+np.var(b))/2))})
 return pd.DataFrame(rows)
def compose(g,col): return json.dumps(g[col].value_counts(normalize=True).sort_index().round(8).to_dict(),sort_keys=True)
def leaf_table(d,v,model):
 for x in (d,v): x['leaf_id']=model.apply(x[FEATURES]); x['month']=x.date.str[:7]
 rows=[]
 for leaf in sorted(set(d.leaf_id)|set(v.leaf_id)):
  a,b=d[d.leaf_id==leaf],v[v.leaf_id==leaf]
  rows.append({'leaf_id':int(leaf),'development_event_count':len(a),'validation_event_count':len(b),'development_population_share':len(a)/len(d),'validation_population_share':len(b)/len(v),'population_share_change':len(b)/len(v)-len(a)/len(d),'development_mean_target_return':null(a.target_return.mean()),'validation_mean_target_return':null(b.target_return.mean()),'development_median_target_return':null(a.target_return.median()),'validation_median_target_return':null(b.target_return.median()),'development_positive_return_ratio':float((a.target_return>0).mean()),'validation_positive_return_ratio':float((b.target_return>0).mean()),'score':null(a.prediction.iloc[0] if len(a) else b.prediction.iloc[0]),'development_symbol_composition':compose(a,'symbol'),'validation_symbol_composition':compose(b,'symbol'),'development_monthly_composition':compose(a,'month'),'validation_monthly_composition':compose(b,'month')})
 return pd.DataFrame(rows)
def concentration(g,n,bydate=False):
 x=g.groupby('date').target_return.sum() if bydate else g.target_return; pos=x[x>0]; return null(pos.nlargest(n).sum()/pos.sum()) if len(pos) and pos.sum()>0 else None

def run(upstream=LOCAL,results=LOCAL):
 b,c,out=roots(upstream,results); out.parent.mkdir(parents=True,exist_ok=True); stage=Path(tempfile.mkdtemp(prefix='.070a_',dir=out.parent))
 try:
  model,dp,v,man=check_inputs(upstream); d=dev_features(man,dp); _=b,c
  if list(v[FEATURES].columns)!=FEATURES: raise RuntimeError('VALIDATION_FEATURE_SCHEMA_MISMATCH')
  d['leaf_id']=model.apply(d[FEATURES]); v['leaf_id']=model.apply(v[FEATURES]); sd,sv=stats(d),stats(v)
  symbols=pd.DataFrame([{'symbol':s,**{f'development_{k}':x for k,x in stats(d[d.symbol==s]).items()},**{f'validation_{k}':x for k,x in stats(v[v.symbol==s]).items()}} for s in SYMS]); symbols['ic_reversal']=((symbols.development_ic>0)&(symbols.validation_ic<0)); symbols['spread_reversal']=((symbols.development_net>0)&(symbols.validation_net<0))
  monthly=pd.concat([pd.DataFrame([{'period':'development','month':m,**stats(g)} for m,g in d.groupby(d.date.str[:7])]),pd.DataFrame([{'period':'validation','month':m,**stats(g)} for m,g in v.groupby(v.date.str[:7])])],ignore_index=True)
  drift=feature_drift(d,v); leaves=leaf_table(d.copy(),v.copy(),model); vm=monthly[monthly.period=='validation']; posic=float((vm.ic>0).mean()); posnet=float((vm.net>0).mean())
  pop=bool((leaves.population_share_change.abs()>=.10).any()); sign=bool(((leaves.development_mean_target_return*leaves.validation_mean_target_return)<0).any()); ties=int(v.prediction.nunique()); causes=[]
  if drift.psi.max()>=.2 or drift.ks_statistic.max()>=.2: causes.append('FEATURE_DISTRIBUTION_DRIFT')
  if pop: causes.append('LEAF_POPULATION_SHIFT')
  if sign: causes.append('LEAF_RETURN_SIGN_REVERSAL')
  if int(symbols.ic_reversal.sum())>=4: causes.append('BROAD_CROSS_SYMBOL_FAILURE')
  elif int(symbols.ic_reversal.sum())>0: causes.append('SYMBOL_SPECIFIC_FAILURE')
  if posic<.5 or posnet<.5: causes.append('MONTHLY_REGIME_INSTABILITY')
  if ties<=len(leaves): causes.append('COARSE_TREE_SCORE_RESOLUTION')
  target_ks=ks_2samp(d.target_return,v.target_return).statistic
  if target_ks>=.2 or v.target_return.std(ddof=0)>d.target_return.std(ddof=0)*1.25: causes.append('TARGET_DISTRIBUTION_SHIFT')
  if not causes or len(causes)>1: primary='INSUFFICIENT_EVIDENCE_FOR_SINGLE_CAUSE'
  else: primary=causes[0]
  secondary=[x for x in causes if x!=primary] or ([] if primary!='INSUFFICIENT_EVIDENCE_FOR_SINGLE_CAUSE' else ['INSUFFICIENT_EVIDENCE_FOR_SINGLE_CAUSE'])
  summary={'final_status':'PASS','final_decision':'VALIDATION_FAILURE_EXPLAINED_FOR_NEW_RESEARCH_CYCLE','model_artifact_sha256_match':True,'model_state_sha256_match':True,'development_event_count':len(d),'validation_event_count':len(v),'development_spearman_ic':sd['ic'],'validation_spearman_ic':sv['ic'],'development_top_bottom_spread_net_10bps':sd['net'],'validation_top_bottom_spread_net_10bps':sv['net'],'feature_max_psi':null(drift.psi.max()),'feature_max_ks':null(drift.ks_statistic.max()),'symbol_ic_reversal_count':int(symbols.ic_reversal.sum()),'symbol_spread_reversal_count':int(symbols.spread_reversal.sum()),'validation_positive_ic_month_ratio':posic,'validation_positive_net_spread_month_ratio':posnet,'leaf_population_shift_detected':pop,'leaf_return_sign_reversal_detected':sign,'primary_failure_explanation':primary,'secondary_failure_explanations':secondary,'score_unique_count':ties,'target_distribution_ks':float(target_ks),'development_top10_event_concentration':concentration(d,10),'validation_top10_event_concentration':concentration(v,10),'development_top5_date_concentration':concentration(d,5,True),'validation_top5_date_concentration':concentration(v,5,True),'fit_call_count':0,'hyperparameter_search_count':0,'confirmation_row_read_count':0,'v22_069d_allowed':False,'new_model_training_allowed':False,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,'live_trading_allowed':False,'order_output_count':0,'position_output_count':0,'broker_connection_count':0}
  drift.to_csv(stage/'feature_drift.csv',index=False); symbols.to_csv(stage/'symbol_comparison.csv',index=False); monthly.to_csv(stage/'monthly_comparison.csv',index=False); leaves.to_csv(stage/'leaf_comparison.csv',index=False); (stage/'failure_atlas.json').write_bytes(stable({'overall_development':sd,'overall_validation':sv,'validation_worst_five_months':vm.nsmallest(5,'net').to_dict('records'),'validation_best_five_months':vm.nlargest(5,'net').to_dict('records'),'score_ties':int(len(v)-ties),'top_bucket_feature_means':v.nlargest(max(1,math.ceil(len(v)*.2)),'prediction')[FEATURES].mean().to_dict(),'bottom_bucket_feature_means':v.nsmallest(max(1,math.ceil(len(v)*.2)),'prediction')[FEATURES].mean().to_dict(),'causes':causes})); (stage/'v22_070a_summary.json').write_bytes(stable(summary))
  if out.exists(): shutil.rmtree(out)
  os.replace(stage,out); return summary,out
 except Exception as e:
  shutil.rmtree(stage,ignore_errors=True); raise

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--upstream-results-root');p.add_argument('--results-root');a=p.parse_args()
 if a.execute:
  s,o=run(a.upstream_results_root or LOCAL,a.results_root or LOCAL); print(json.dumps({**s,'summary_path':str(o/'v22_070a_summary.json')},sort_keys=True))
