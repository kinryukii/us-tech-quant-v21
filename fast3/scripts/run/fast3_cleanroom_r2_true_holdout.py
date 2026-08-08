#!/usr/bin/env python
"""One-shot Clean-Room R2 holdout scoring and label evaluation; no refitting."""
from __future__ import annotations
import argparse, hashlib, json, importlib.util, sys
from pathlib import Path
import joblib, numpy as np, pandas as pd

REPO=Path(__file__).parents[3]; sys.path.insert(0,str(REPO/'fast3/src')); R2P=REPO/'fast3/scripts/run/fast3_cleanroom_r2_freeze.py'
s=importlib.util.spec_from_file_location('r2',R2P); R2=importlib.util.module_from_spec(s); s.loader.exec_module(R2); R1=R2.R1
from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as PAYOFF
FROZEN=Path(r'D:\us-tech-quant-results\frozen\fast3\cleanroom_r2_20260808')
EXPECTED={'UP_HGB':'dc1c05be91a50cc2fc8fdd1a622ba5fd24592fb1a42e5e008da2274e7e1b88eb','DOWN_HGB':'70f216be92b90e295f0eaac0295ac057259ab0e5b4f90f1e9ef60a900b59372d','UP_LOGIT':'46ecf17957f6c7e7df95274dbd6c07025a011689ed38978799a8d2694e431dd5','DOWN_LOGIT':'93376b3e1231a40090d029b1790647f16610acb5d5deae5dca087566aeea7e11'}
LEDGER_HASH='5444c6ea38313fb5c7f355be9b5f70cc41ef2754b8a57dd27d4c038e3eb48ede'; ECON_HASH='70d0624bb61dd77cf2d8a8aea5c53b87488a094a222eca5d42167ba343cbee8f'

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,default=str)+'\n')
def identity():
 m=json.loads((FROZEN/'cleanroom_r2_freeze_manifest.json').read_text()); t=json.loads((FROZEN/'cleanroom_r2_thresholds.json').read_text())['thresholds']; models={x['model']:x for x in m['models']}; ok=all(sha(models[k]['path'])==v for k,v in EXPECTED.items()) and sha(m['holdout_ledger_path'])==LEDGER_HASH and sha(m['economic_contract_path'])==ECON_HASH
 return m,t,models,ok
def label_symbol(raw, base):
 ns=R1.utc_nanoseconds(raw.timestamp_utc); good=raw.valid.to_numpy(bool); hi=raw.high.to_numpy(float); lo=raw.low.to_numpy(float); op=raw.open.to_numpy(float); ma,sz=R1.build_tree(hi,True); mi,_=R1.build_tree(lo,False); out=[]
 for r in base.itertuples(index=False):
  i=int(np.searchsorted(ns,pd.Timestamp(r.decision_timestamp_utc).value)); entry=R1.next_valid(good,i+1)
  if entry<0: continue
  dead=ns[entry]+int(pd.Timedelta(hours=24).value); cover=int(np.searchsorted(ns,dead,'left')); end=int(np.searchsorted(ns,dead,'right')-1)
  if cover>=len(ns) or end<=entry: continue
  up=R1.first_cross(ma,sz,entry,end,op[entry]*1.01,True); down=R1.first_cross(mi,sz,entry,end,op[entry]*.99,False)
  lab='AMBIGUOUS_EVENT' if up>=0 and up==down else ('UP_FIRST' if up>=0 and (down<0 or up<down) else ('DOWN_FIRST' if down>=0 else 'NO_EVENT'))
  out.append({'base_id':r.base_id,'first_touch_label':lab,'label_information_end_utc':raw.timestamp_utc.iat[end]})
 return pd.DataFrame(out)
def metric(x,score,th):
 y=x.target_first.to_numpy(int); sel=score>=th; base=float(y.mean()); p=float(y[sel].mean()) if sel.any() else None
 return {'candidate_count':len(x),'positive_count':int(y.sum()),'base_rate':base,'selected_count':int(sel.sum()),'selected_rate':float(sel.mean()),'selected_precision':p,'lift':(p/base if p is not None and base else None)}
def stability(x,score,th,freq):
 z=x.copy();z['score']=score;z['selected']=z.score>=th;z['period']=pd.to_datetime(z.decision_timestamp_et).dt.to_period(freq).astype(str)
 return z.groupby('period').apply(lambda a:pd.Series(metric(a,a.score.to_numpy(),th))).reset_index()
def ci95(values, statistic, rng, draws=2000):
 a=np.asarray(values,float)
 if not len(a): return [None,None]
 sims=np.array([statistic(a[rng.integers(0,len(a),len(a))]) for _ in range(draws)],float)
 return [float(np.quantile(sims,.025)),float(np.quantile(sims,.975))]
def cluster_mean_ci(frame,rng,draws=2000):
 groups=[a.net20.to_numpy(float) for _,a in frame.groupby('month',sort=True)]
 if not groups:return [None,None]
 sims=[]
 for _ in range(draws):
  picked=[groups[i] for i in rng.integers(0,len(groups),len(groups))]
  sims.append(float(np.concatenate(picked).mean()))
 return [float(np.quantile(sims,.025)),float(np.quantile(sims,.975))]
def trade_metrics(trades):
 if trades.empty:return {'TRADE_COUNT':0}
 x=trades.net20.to_numpy(float); wins=x>0
 streak=best=0
 for w in wins:
  streak=0 if w else streak+1; best=max(best,streak)
 result={'TRADE_COUNT':int(len(x)),'WIN_COUNT':int(wins.sum()),'LOSS_COUNT':int((~wins).sum()),'WIN_RATE':float(wins.mean()),
         'MEAN_NET20':float(x.mean()),'GEOMETRIC_MEAN_NET20':float(np.prod(1+x)**(1/len(x))-1),'MEDIAN_NET20':float(np.median(x)),
         'P05_NET20':float(np.quantile(x,.05)),'P25_NET20':float(np.quantile(x,.25)),'P75_NET20':float(np.quantile(x,.75)),'P95_NET20':float(np.quantile(x,.95)),
         'BEST_TRADE':float(x.max()),'WORST_TRADE':float(x.min()),'MAX_CONSECUTIVE_LOSSES':int(best)}
 for key,sub in [('UP',trades[trades.direction.eq('UP')]),('DOWN',trades[trades.direction.eq('DOWN')]),('QQQ',trades[trades.underlying_symbol.eq('QQQ')]),('SOXX',trades[trades.underlying_symbol.eq('SOXX')])]:
  result[f'{key}_TRADE_COUNT']=int(len(sub));result[f'{key}_WIN_RATE']=float((sub.net20>0).mean()) if len(sub) else None;result[f'{key}_MEAN_NET20']=float(sub.net20.mean()) if len(sub) else None
 return result
def select_trades(signals,payoffs):
 """Apply the frozen one-position rule; caller has already rejected unresolved ties."""
 p=payoffs.set_index('candidate_id',verify_integrity=True); rows=[]; until=None
 for r in signals.sort_values(['decision_timestamp_utc','candidate_id'],kind='mergesort').itertuples(index=False):
  decision=pd.Timestamp(r.decision_timestamp_utc)
  if until is not None and decision < until: continue
  side=r.direction.lower(); pr=p.loc[r.candidate_id]
  if not bool(pr[f'{side}_payoff_valid']): continue
  entry=pd.Timestamp(pr[f'{side}_entry_timestamp_et']); exit_=pd.Timestamp(pr[f'{side}_actual_exit_timestamp_et'])
  rows.append({'trade_id':f'R2H-{len(rows)+1:06d}','source_candidate_id':r.candidate_id,'underlying_symbol':r.underlying_symbol,'direction':r.direction,
               'action_instrument':pr[f'{side}_action_instrument'],'decision_timestamp_utc':decision,'entry_timestamp_et':entry,'exit_timestamp_et':exit_,
               'entry_price':float(pr[f'{side}_entry_price']),'exit_price':float(pr[f'{side}_exit_price']),'net20':float(pr[f'{side}_action_net_return_20bps'])})
  until=exit_
 return pd.DataFrame(rows)
def prediction_decision(mets,economic_status,econ):
 up,down=(mets['UP_HGB']['lift'] or 0),(mets['DOWN_HGB']['lift'] or 0)
 if up<=1 and down<=1:return 'D_TRUE_HOLDOUT_FAILURE'
 if economic_status!='COMPLETE':return 'C_WEAK_OR_INCONCLUSIVE_HOLDOUT'
 supported=econ['MEAN_NET20']>0 and econ['MEDIAN_NET20']>0 and econ['MEAN_NET20_CI95'][0]>0 and econ['MONTH_CLUSTER_MEAN_NET20_CI95'][0]>0
 if up>1 and down>1 and supported:return 'A_STRONG_TRUE_HOLDOUT_PERSISTENCE'
 if up>1 and down>1 and econ['MEAN_NET20']>0:return 'B_REAL_EDGE_WITH_MATERIAL_DECAY'
 return 'C_WEAK_OR_INCONCLUSIVE_HOLDOUT'
def main(runtime,scratch,fout):
 m,t,models,ok=identity(); runtime.mkdir(parents=True,exist_ok=True);scratch.mkdir(parents=True,exist_ok=True);fout.mkdir(parents=True,exist_ok=True)
 dump(fout/'true_holdout_identity_audit.json',{'FREEZE_IDENTITY_VERIFIED':ok,'model_hashes':EXPECTED,'ledger_hash':LEDGER_HASH,'economic_contract_hash':ECON_HASH,
                                               'thresholds':t,'true_holdout_start_et':str(R2.TRUE_HOLDOUT_START_ET),'true_holdout_start_utc':str(R2.TRUE_HOLDOUT_START_UTC)})
 if not ok: raise RuntimeError('STOP_FREEZE_IDENTITY_MISMATCH')
 ledger=pd.read_parquet(m['holdout_ledger_path']); ledger['base_id']=ledger.underlying_symbol+'|'+ledger.decision_timestamp_utc.astype(str)
 labels=[]
 for sym in R1.SYMBOLS:
  raw=R2.read_symbol(sym,R2.symbol_paths(sym,first=(2025,1))); base=ledger[ledger.underlying_symbol.eq(sym)][['base_id','decision_timestamp_utc']].drop_duplicates(); labels.append(label_symbol(raw,base))
 lab=pd.concat(labels,ignore_index=True); ledger=ledger.merge(lab,on='base_id',how='inner',validate='many_to_one'); ledger['target_first']=(ledger.first_touch_label==ledger.direction+'_FIRST').astype(int)
 scores={}; mets={}; st=[]
 for head in R2.HEADS:
  x=ledger[(ledger.direction==head)&(~ledger.first_touch_label.eq('AMBIGUOUS_EVENT'))].copy()
  for fam in R2.FAMILIES:
   key=f'{head}_{fam}'; p=joblib.load(models[key]['path']).predict_proba(x[list(R1.FEATURES)])[:,1]; scores[key]=(x,p); mets[key]=metric(x,p,t[f'{key}_THRESHOLD'])
  x,p=scores[f'{head}_HGB']; st.append(stability(x,p,t[f'{head}_HGB_THRESHOLD'],'M').assign(head=head,granularity='MONTH'));st.append(stability(x,p,t[f'{head}_HGB_THRESHOLD'],'Q').assign(head=head,granularity='QUARTER'))
 pred_stability=pd.concat(st,ignore_index=True)
 counts=lab.first_touch_label.value_counts().to_dict(); pre=m['oof_metrics']; ret={}
 for h in R2.HEADS:
  ret[f'{h}_HGB_PREHOLDOUT_LIFT']=pre[f'{h}_HGB']['lift']; ret[f'{h}_HGB_HOLDOUT_LIFT']=mets[f'{h}_HGB']['lift'];ret[f'{h}_LIFT_RETENTION_RATIO']=mets[f'{h}_HGB']['lift']/pre[f'{h}_HGB']['lift'] if pre[f'{h}_HGB']['lift'] else None
 # The frozen contract declares only opposite-direction simultaneous signals as ABSTAIN.
 # Same-direction cross-underlying ties are intentionally not resolved by this run.
 signal=[]
 for h in R2.HEADS:
  x,p=scores[f'{h}_HGB']; z=x.loc[p>=t[f'{h}_HGB_THRESHOLD'],['candidate_id','underlying_symbol','direction','decision_timestamp_utc','decision_timestamp_et']].copy();signal.append(z)
 signal=pd.concat(signal,ignore_index=True).sort_values(['decision_timestamp_utc','candidate_id'],kind='mergesort').reset_index(drop=True)
 grouped=signal.groupby('decision_timestamp_utc',sort=True)['direction'].agg(lambda a:set(a)) if len(signal) else pd.Series(dtype=object)
 opposite=set(grouped[grouped.map(lambda x:len(x)>1)].index)
 signal=signal[~signal.decision_timestamp_utc.isin(opposite)].copy()
 same_ties=signal.groupby('decision_timestamp_utc',sort=True).size(); same_ties=same_ties[same_ties>1]
 tie_audit={'selected_hgb_signal_count_before_conflict_abstention':int(sum(len(v[0]) for k,v in scores.items() if k.endswith('_HGB'))),
            'opposite_direction_abstain_timestamp_count':int(len(opposite)),'same_direction_unresolved_timestamp_count':int(len(same_ties)),
            'same_direction_unresolved_candidate_count':int(same_ties.sum())}
 economic_status='COMPLETE'; trades=pd.DataFrame(); economic={'ECONOMIC_STATUS':'COMPLETE'}; bootstrap={'ECONOMIC_STATUS':'COMPLETE','seed':20260808,'draws':2000}
 if len(same_ties):
  economic_status='STOP_EXECUTION_CONTRACT_SAME_DIRECTION_TIE_UNSPECIFIED'
  economic={'ECONOMIC_STATUS':economic_status,'TRADE_COUNT':None,'reason':'Frozen R2 contract does not specify a same-direction cross-underlying priority while flat.'}
  bootstrap={'ECONOMIC_STATUS':economic_status,'seed':20260808}
 else:
  candidates=signal[['candidate_id','underlying_symbol','decision_timestamp_et']].rename(columns={'underlying_symbol':'candidate_instrument','decision_timestamp_et':'authoritative_anchor_timestamp_et'}).copy()
  candidates['decision_timestamp_et']=candidates['authoritative_anchor_timestamp_et']
  payoffs,_=PAYOFF.construct_payoffs(candidates,R2.CANONICAL)
  payoffs.to_parquet(scratch/'cleanroom_r2_true_holdout_selected_signal_payoffs.parquet',index=False)
  trades=select_trades(signal,payoffs)
  if len(trades):
   trades['month']=pd.to_datetime(trades.entry_timestamp_et).dt.to_period('M').astype(str);trades['quarter']=pd.to_datetime(trades.entry_timestamp_et).dt.to_period('Q').astype(str)
  economic=trade_metrics(trades)
  economic['ECONOMIC_STATUS']='COMPLETE'
  rng=np.random.default_rng(20260808); bootstrap={'ECONOMIC_STATUS':'COMPLETE','seed':20260808,'draws':2000,
     'WIN_RATE_CI95':ci95((trades.net20.to_numpy(float)>0).astype(float),np.mean,rng), 'MEAN_NET20_CI95':ci95(trades.net20.to_numpy(float),np.mean,rng),
     'MONTH_CLUSTER_MEAN_NET20_CI95':cluster_mean_ci(trades,rng)} if len(trades) else {'ECONOMIC_STATUS':'COMPLETE','seed':20260808,'draws':2000,'WIN_RATE_CI95':[None,None],'MEAN_NET20_CI95':[None,None],'MONTH_CLUSTER_MEAN_NET20_CI95':[None,None]}
  economic.update(bootstrap)
  for freq,label in [('month','MONTH'),('quarter','QUARTER')]:
   if len(trades):
    e=trades.groupby(freq).agg(trade_count=('trade_id','size'),win_rate=('net20',lambda x:float((x>0).mean())),mean_net20=('net20','mean'),median_net20=('net20','median'),cumulative_simple_net20=('net20','sum')).reset_index().rename(columns={freq:'period'});e['head']='HGB';e['granularity']=label;pred_stability=pd.concat([pred_stability,e],ignore_index=True,sort=False)
  economic['PROFITABLE_MONTH_RATIO']=float((trades.groupby('month').net20.mean()>0).mean()) if len(trades) else None
  economic['PROFITABLE_QUARTER_RATIO']=float((trades.groupby('quarter').net20.mean()>0).mean()) if len(trades) else None
  economic['WORST_MONTH_MEAN_NET20']=float(trades.groupby('month').net20.mean().min()) if len(trades) else None
  economic['WORST_QUARTER_MEAN_NET20']=float(trades.groupby('quarter').net20.mean().min()) if len(trades) else None
  economic['BEST_MONTH_CONTRIBUTION_RATIO']=float(trades.groupby('month').net20.sum().max()/trades.net20.sum()) if len(trades) and trades.net20.sum()!=0 else None
 trades.to_csv(fout/'true_holdout_trades.csv',index=False); pred_stability.to_csv(fout/'true_holdout_time_stability.csv',index=False)
 duplicate_id=int(trades.trade_id.duplicated().sum()) if len(trades) else 0; duplicate_source=int(trades.source_candidate_id.duplicated().sum()) if len(trades) else 0
 overlap=int((pd.to_datetime(trades.entry_timestamp_et).iloc[1:].to_numpy()<pd.to_datetime(trades.exit_timestamp_et).iloc[:-1].to_numpy()).sum()) if len(trades)>1 else 0
 economic.update({'DUPLICATE_TRADE_ID_COUNT':duplicate_id,'DUPLICATE_SOURCE_CANDIDATE_COUNT':duplicate_source,'DUPLICATE_EXECUTION_COUNT':duplicate_source,'OVERLAPPING_TRADE_COUNT':overlap,'signal_tie_audit':tie_audit})
 dump(fout/'true_holdout_economic_metrics.json',economic);dump(fout/'true_holdout_bootstrap.json',bootstrap)
 dump(fout/'true_holdout_predictive_metrics.json',{'requested_start_et':str(R2.TRUE_HOLDOUT_START_ET),'effective_start_et':str(ledger.decision_timestamp_et.min()),'effective_end_et':str(ledger.decision_timestamp_et.max()),'base_candidate_count':int(len(lab)),'label_counts':counts,'metrics':mets,'retention':ret,'signal_tie_audit':tie_audit,'economic_status':economic_status,'post_holdout_model_refit':False,'post_holdout_threshold_recomputed':False,'post_holdout_feature_change':False,'post_holdout_parameter_change':False})
 decision=prediction_decision(mets,economic_status,economic)
 dump(fout/'true_holdout_contract.json',{'models':EXPECTED,'thresholds':t,'economic_contract_sha256':ECON_HASH,'holdout_boundary_et':str(R2.TRUE_HOLDOUT_START_ET),'holdout_boundary_utc':str(R2.TRUE_HOLDOUT_START_UTC),'economic_status':economic_status})
 (fout/'TRUE_HOLDOUT_REPORT.md').write_text(f'# FAST3 Clean-Room R2 true holdout\n\nTRUE_HOLDOUT_DECISION={decision}\n\nECONOMIC_STATUS={economic_status}\n\nNo model, feature, threshold, or parameter was changed after holdout reveal.\n')
 dump(runtime/'true_holdout_runtime_summary.json',{'status':'COMPLETE','decision':decision,'economic_status':economic_status})
 return counts,mets,ret,decision,ledger,economic,bootstrap
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--runtime',required=True);a.add_argument('--scratch',required=True);a.add_argument('--frozen',required=True);q=a.parse_args(); c,me,r,d,l=main(Path(q.runtime),Path(q.scratch),Path(q.frozen));print('CLEANROOM_R2_TRUE_HOLDOUT_STATUS=COMPLETE');print('TRUE_HOLDOUT_DECISION='+d)
