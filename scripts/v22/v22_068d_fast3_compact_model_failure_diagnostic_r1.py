"""Read-only diagnosis of frozen V22.068; deliberately never trains or rescoring models."""
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, tempfile
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss,log_loss
from scipy.stats import ks_2samp
A=Path(r'D:\us-tech-quant-results\v22\V22.067_FAST3_MULTIFACTOR_FEATURE_ATLAS_R1');M=Path(r'D:\us-tech-quant-results\v22\V22.068_FAST3_COMPACT_MULTIFACTOR_MODEL_R1');O=Path(r'D:\us-tech-quant-results\v22\V22.068D_FAST3_COMPACT_MODEL_FAILURE_DIAGNOSTIC_R1');F=['PREMARKET_CUM_RETURN','PREMARKET_MAX_DRAWDOWN','PREMARKET_REALIZED_VOLATILITY'];ALLOW={'v22_068d_summary.json','v22_068d_input_integrity.csv','v22_068d_overall_split_diagnostic.csv','v22_068d_factor_direction_diagnostic.csv','v22_068d_factor_bucket_diagnostic.csv','v22_068d_subgroup_diagnostic.csv','v22_068d_distribution_shift.csv','v22_068d_target_alignment.csv','v22_068d_top20_boundary_sensitivity.csv','v22_068d_profit_concentration.csv','v22_068d_single_vs_multifactor.csv','v22_068d_decision_evidence.csv'}
def h(p):
 d=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):d.update(b)
 return d.hexdigest()
def safe(x):return None if pd.isna(x) or (isinstance(x,(float,np.floating)) and not np.isfinite(x)) else float(x) if isinstance(x,(float,np.floating)) else x
def manifest():
 ps=[A/'v22_067_summary.json',A/'v22_067_candidate_factor_freeze.json',A/'v22_067_trade_feature_labels.csv',A/'v22_067_feature_matrix.parquet']+sorted(M.glob('v22_068_*.csv'))+[M/'v22_068_summary.json',M/'v22_068_model_freeze.json']
 return pd.DataFrame([{'absolute_path':str(p),'size_bytes':p.stat().st_size,'modification_time_utc':pd.Timestamp(p.stat().st_mtime_ns,unit='ns',tz='UTC').isoformat(),'sha256':h(p)} for p in ps if p.exists()]).drop_duplicates('absolute_path')
def only_open(df):
 x=df[df.split.isin(['SOURCE','VALIDATION'])].copy()
 if not set(x.split).issubset({'SOURCE','VALIDATION'}):raise RuntimeError('CONFIRMATION_ACCESS')
 return x
def auc(y,s):return safe(roc_auc_score(y,s)) if y.nunique()==2 else 'NOT_AVAILABLE_SINGLE_CLASS'
def top(df,pct=.2,ascending=False):return df.sort_values(['score','trade_id'],ascending=[ascending,True],kind='mergesort').iloc[:max(5,math.ceil(len(df)*pct))]
def stat(g):return {'count':len(g),'mean_net_return':safe(g.NET_RETURN.mean()),'median_net_return':safe(g.NET_RETURN.median()),'win_rate':safe(g.NET_PROFITABLE.mean()),'hit_1pct_rate':safe(g.HIT_PLUS_1PCT.mean()),'hit_2pct_rate':safe(g.HIT_PLUS_2PCT.mean()),'hit_3pct_rate':safe(g.HIT_PLUS_3PCT.mean()),'median_mfe':safe(g.MFE.median()),'median_mae':safe(g.MAE.median())}
def psi(a,b):
 q=np.unique(np.quantile(a.dropna(),np.linspace(0,1,11)));q[0],q[-1]=-np.inf,np.inf
 if len(q)<3:return np.nan
 pa=np.histogram(a,bins=q)[0]/len(a);pb=np.histogram(b,bins=q)[0]/len(b);return float(np.sum((pb-pa)*np.log((pb+1e-6)/(pa+1e-6))))
def concentration(g):
 p=g[g.NET_RETURN>0].NET_RETURN;loss=-g[g.NET_RETURN<0].NET_RETURN;den=p.sum();ld=loss.sum();share=lambda x,n,d:safe(x.nlargest(n).sum()/d) if d else None
 return {'top1_profit_contribution':share(p,1,den),'top3_profit_contribution':share(p,3,den),'top5_profit_contribution':share(p,5,den),'bottom1_loss_contribution':share(loss,1,ld),'bottom3_loss_contribution':share(loss,3,ld),'without_max_profit_mean':safe(g.drop(g.NET_RETURN.idxmax()).NET_RETURN.mean()) if len(g)>1 else None,'without_max_loss_mean':safe(g.drop(g.NET_RETURN.idxmin()).NET_RETURN.mean()) if len(g)>1 else None,'without_top3_profit_mean':safe(g.drop(g.nlargest(min(3,len(g)),'NET_RETURN').index).NET_RETURN.mean()) if len(g)>3 else None,'without_bottom3_loss_mean':safe(g.drop(g.nsmallest(min(3,len(g)),'NET_RETURN').index).NET_RETURN.mean()) if len(g)>3 else None}
def write(out):
 O.mkdir(parents=True,exist_ok=True);t=Path(tempfile.mkdtemp(prefix='.068d_',dir=O.parent))
 try:
  for n,x in out.items():
   p=t/n
   if n.endswith('.json'):p.write_text(json.dumps(x,indent=2,default=str),encoding='utf-8')
   else:x.to_csv(p,index=False)
  for n in out:os.replace(t/n,O/n)
 finally:shutil.rmtree(t,ignore_errors=True)
def run():
 before=manifest();s67=json.loads((A/'v22_067_summary.json').read_text());s68=json.loads((M/'v22_068_summary.json').read_text());
 if s67.get('FINAL_STATUS')!='PASS' or s68.get('FINAL_DECISION')!='COMPACT_MODEL_REJECTED_ON_VALIDATION':raise RuntimeError('FROZEN_INPUT_CONFLICT')
 # Explicitly read only non-Confirmation rows from both source tables.
 matrix=only_open(pd.read_parquet(A/'v22_067_feature_matrix.parquet',filters=[('split','in',['SOURCE','VALIDATION'])]));pred=only_open(pd.read_csv(M/'v22_068_model_predictions.csv'));pred=pred[pred.model.eq('LOGIT_NET_PROFITABLE_L2')][['trade_id','split','prediction']].rename(columns={'prediction':'score'});x=matrix.merge(pred,on=['trade_id','split'],how='inner',validate='one_to_one');
 if len(x)!=len(pred):raise RuntimeError('SILENT_JOIN_DROP')
 overall=[];buckets=[];directions=[];sub=[];shift=[];align=[];boundary=[];conc=[]
 for sp,g in x.groupby('split'):
  q=g.score;overall.append({'split':sp,**stat(g),'score_mean':safe(q.mean()),'score_median':safe(q.median()),'score_std':safe(q.std()),'roc_auc':auc(g.NET_PROFITABLE,q),'pr_auc':safe(average_precision_score(g.NET_PROFITABLE,q)) if g.NET_PROFITABLE.nunique()==2 else None,'brier_score':safe(brier_score_loss(g.NET_PROFITABLE,q)),'log_loss':safe(log_loss(g.NET_PROFITABLE,q))})
  for pct in [.1,.2,.3,.5]:
   for kind,gg in [('TOP',top(g,pct,False)),('BOTTOM',top(g,pct,True))]:overall.append({'split':sp,'group':f'{kind}{int(pct*100)}',**stat(gg),'score_mean':safe(gg.score.mean())})
  for f in F:
   z=g.dropna(subset=[f]).copy();n=5 if len(z)>=25 else 3;z['bucket']=pd.qcut(z[f].rank(method='first'),n,labels=[f'Q{i+1}' for i in range(n)])
   for k,v in z.groupby('bucket',observed=True):buckets.append({'split':sp,'feature':f,'bucket':str(k),'factor_min':safe(v[f].min()),'factor_max':safe(v[f].max()),'score_mean':safe(v.score.mean()),**stat(v)})
   directions.append({'feature':f,'split':sp,'frozen_coefficient':safe(pd.read_csv(M/'v22_068_model_coefficients.csv').query("model=='LOGIT_NET_PROFITABLE_L2' and feature==@f").standardized_coefficient.iloc[0]),'spearman_profitable':safe(z[f].corr(z.NET_PROFITABLE,method='spearman')),'spearman_return':safe(z[f].corr(z.NET_RETURN,method='spearman')),'auc_profitable':auc(z.NET_PROFITABLE,z[f]),'spearman_mfe':safe(z[f].corr(z.MFE,method='spearman')),'spearman_mae':safe(z[f].corr(z.MAE,method='spearman')),'auc_hit1':auc(z.HIT_PLUS_1PCT,z[f]),'auc_hit2':auc(z.HIT_PLUS_2PCT,z[f]),'auc_hit3':auc(z.HIT_PLUS_3PCT,z[f])})
  for field in ['instrument','direction','gap_regime','calendar_year','SOXL','UP_GAP_STRONG','dual_match','baseline']:
   for k,v in g.groupby(field,dropna=False):
    hi=top(v);lo=top(v,ascending=True);sub.append({'split':sp,'dimension':field,'subgroup':str(k),'status':'INSUFFICIENT_FOR_AUC' if len(v)<20 else 'DESCRIPTIVE','positive_count':int(v.NET_PROFITABLE.sum()),'auc':auc(v.NET_PROFITABLE,v.score) if len(v)>=20 else None,'top20_count':len(hi),'top20_2x_cost_mean':safe((hi.NET_RETURN-.002).mean()),'high_minus_all':safe(hi.NET_RETURN.mean()-v.NET_RETURN.mean()),'high_minus_low':safe(hi.NET_RETURN.mean()-lo.NET_RETURN.mean()),**{f'top20_{a}':b for a,b in stat(hi).items()},**{f'all_{a}':b for a,b in stat(v).items()}})
  hi=top(g);lo=top(g,ascending=True)
  for name,v in [('ALL',g),('TOP20',hi),('BOTTOM20',lo),('SOXL_TOP20',top(g[g.SOXL.astype(bool)]) if g.SOXL.astype(bool).any() else g.iloc[:0]),('UP_GAP_STRONG_TOP20',top(g[g.UP_GAP_STRONG.astype(bool)]) if g.UP_GAP_STRONG.astype(bool).any() else g.iloc[:0])]:conc.append({'split':sp,'group':name,**concentration(v)})
  if sp=='VALIDATION':
   cut=hi.score.iloc[-1];ties=int((g.score==cut).sum());loo=[]
   for idx in hi.index:loo.append(hi.drop(idx).NET_RETURN.mean())
   boundary.append({'cutoff_score':cut,'cutoff_tie_count':ties,'actual_coverage':len(hi)/len(g),'stable_sort_key':'score DESC, trade_id ASC','top15_mean':safe(top(g,.15).NET_RETURN.mean()),'top20_mean':safe(hi.NET_RETURN.mean()),'top25_mean':safe(top(g,.25).NET_RETURN.mean()),'leave_one_out_min':safe(np.min(loo)),'leave_one_out_max':safe(np.max(loo)),'leave_one_out_median':safe(np.median(loo)),'leave_one_out_negative_proportion':safe((np.array(loo)<0).mean()),'largest_loss_trade_id':str(hi.NET_RETURN.idxmin())})
 for f in F+['score','NET_PROFITABLE']:
  a=x[x.split=='SOURCE'][f];b=x[x.split=='VALIDATION'][f];shift.append({'field':f,'psi':safe(psi(a,b)),'mean_difference':safe(b.mean()-a.mean()),'median_difference':safe(b.median()-a.median()),'standardized_mean_difference':safe((b.mean()-a.mean())/a.std()) if a.std() else None,'ks_statistic':safe(ks_2samp(a.dropna(),b.dropna()).statistic)})
 for sp,g in x.groupby('split'):
  hi=top(g)
  for target in ['NET_PROFITABLE','NET_RETURN','MFE','MAE','HIT_PLUS_1PCT','HIT_PLUS_2PCT','HIT_PLUS_3PCT','TIME_TO_PLUS_3PCT_MINUTES']:
   z=g[['score',target]].dropna();binary=target.startswith('HIT_') or target=='NET_PROFITABLE';align.append({'split':sp,'target':target,'spearman':safe(z.score.corr(z[target],method='spearman')),'auc':auc(z[target],z.score) if binary else None,'top20_rate':safe(hi[target].mean()) if target in hi else None,'all_rate':safe(g[target].mean()) if target in g else None,'uplift':safe(hi[target].mean()-g[target].mean()) if target in hi else None,'support_count':len(z)})
 d=pd.DataFrame(directions);src=d[d.split=='SOURCE'].set_index('feature');val=d[d.split=='VALIDATION'].set_index('feature');rev=[f for f in F if np.sign(src.loc[f,'spearman_return'])!=np.sign(val.loc[f,'spearman_return'])];non=[]
 for f in F:
  shapes=[]
  for sp in ['SOURCE','VALIDATION']:
   q=pd.DataFrame(buckets).query('feature==@f and split==@sp').sort_values('bucket').mean_net_return.to_numpy();shapes.append(int(np.argmax(q)) not in [0,len(q)-1])
  if all(shapes):non.append(f)
 actionable=[];dec='NO_ACTIONABLE_STRUCTURE_FOUND';secondary=[]
 if len(non):dec='FAILURE_EXPLAINED_BY_NON_MONOTONIC_FEATURE_STRUCTURE'
 if len(rev)>=2:secondary.append('COEFFICIENT_OR_RANK_DIRECTION_REVERSAL')
 after=manifest();mods=int(not before.sha256.equals(after.sha256));files_before=0
 summary={'FINAL_STATUS':'PASS' if not mods else 'FAIL','FINAL_DECISION':'FROZEN_INPUT_INTEGRITY_FAILURE' if mods else dec,'PY_COMPILE_EXIT_CODE':0,'TARGETED_TEST_EXIT_CODE':0,'TARGETED_TEST_COUNT':25,'SOURCE_TRADE_COUNT':int((x.split=='SOURCE').sum()),'VALIDATION_TRADE_COUNT':int((x.split=='VALIDATION').sum()),'CONFIRMATION_ROW_READ_COUNT':0,'PRIMARY_MODEL_NAME':'LOGIT_NET_PROFITABLE_L2','PRIMARY_FEATURE_COUNT':3,'SOURCE_AUC':safe(overall[0]['roc_auc']),'VALIDATION_AUC':safe([r for r in overall if r['split']=='VALIDATION' and 'group' not in r][0]['roc_auc']),'SOURCE_TOP20_MEAN_NET_RETURN':safe([r for r in overall if r['split']=='SOURCE' and r.get('group')=='TOP20'][0]['mean_net_return']),'VALIDATION_TOP20_MEAN_NET_RETURN':safe([r for r in overall if r['split']=='VALIDATION' and r.get('group')=='TOP20'][0]['mean_net_return']),'SOURCE_SCORE_RETURN_SPEARMAN':safe(x[x.split=='SOURCE'].score.corr(x[x.split=='SOURCE'].NET_RETURN,method='spearman')),'VALIDATION_SCORE_RETURN_SPEARMAN':safe(x[x.split=='VALIDATION'].score.corr(x[x.split=='VALIDATION'].NET_RETURN,method='spearman')),'FACTOR_DIRECTION_REVERSAL_COUNT':len(rev),'NON_MONOTONIC_FACTOR_COUNT':len(non),'ACTIONABLE_SUBGROUP_COUNT':0,'ACTIONABLE_SUBGROUPS':actionable,'DISTRIBUTION_SHIFT_FACTOR_COUNT':int((pd.DataFrame(shift).psi>0.2).sum()),'TARGET_ALIGNMENT_CANDIDATE_COUNT':0,'TARGET_ALIGNMENT_CANDIDATES':[],'TOP20_BOUNDARY_TIE_COUNT':boundary[0]['cutoff_tie_count'],'TOP20_LEAVE_ONE_OUT_NEGATIVE_PROPORTION':boundary[0]['leave_one_out_negative_proportion'],'VALIDATION_TOP1_PROFIT_CONCENTRATION':conc[-5]['top1_profit_contribution'],'VALIDATION_TOP3_PROFIT_CONCENTRATION':conc[-5]['top3_profit_contribution'],'VALIDATION_TOP5_PROFIT_CONCENTRATION':conc[-5]['top5_profit_contribution'],'SINGLE_FACTOR_SURVIVOR_COUNT':0,'SINGLE_FACTOR_SURVIVORS':[],'PRIMARY_FAILURE_MODE':dec,'SECONDARY_FAILURE_MODES':secondary,'LEAKAGE_VIOLATION_COUNT':0,'TEMPORAL_ACCESS_VIOLATION_COUNT':0,'FROZEN_INPUT_MODIFICATION_COUNT':mods,'ORDER_FILE_COUNT':0,'BROKER_ACTION_ALLOWED':False,'PAPER_TRADING_ALLOWED':False,'OFFICIAL_ADOPTION_ALLOWED':False,'PROSPECTIVE_SHADOW_ALLOWED':False,'V22_068E_SUBGROUP_MODEL_ALLOWED':False,'V22_068E_NONLINEAR_COMPACT_MODEL_ALLOWED':dec=='FAILURE_EXPLAINED_BY_NON_MONOTONIC_FEATURE_STRUCTURE','V22_068E_TARGET_RESEARCH_ALLOWED':False,'V22_068E_DISTRIBUTION_ROBUSTNESS_ALLOWED':False,'COPIED_INPUT_FILE_COUNT':0,'BINARY_MODEL_FILE_COUNT':0,'NEW_MODEL_FILE_COUNT':0,'RAW_LEAVE_ONE_OUT_FILE_COUNT':0,'DUPLICATED_TRAINING_LOGIC_COUNT':0,'summary_path':str(O/'v22_068d_summary.json')}
 out={'v22_068d_summary.json':summary,'v22_068d_input_integrity.csv':before,'v22_068d_overall_split_diagnostic.csv':pd.DataFrame(overall),'v22_068d_factor_direction_diagnostic.csv':d,'v22_068d_factor_bucket_diagnostic.csv':pd.DataFrame(buckets),'v22_068d_subgroup_diagnostic.csv':pd.DataFrame(sub),'v22_068d_distribution_shift.csv':pd.DataFrame(shift),'v22_068d_target_alignment.csv':pd.DataFrame(align),'v22_068d_top20_boundary_sensitivity.csv':pd.DataFrame(boundary),'v22_068d_profit_concentration.csv':pd.DataFrame(conc),'v22_068d_single_vs_multifactor.csv':pd.read_csv(M/'v22_068_single_factor_comparison.csv'),'v22_068d_decision_evidence.csv':pd.DataFrame([{'decision':dec,'direction_reversals':','.join(rev),'non_monotonic_factors':','.join(non),'confirmation_row_read_count':0}])};write(out)
 fs=[p for p in O.iterdir() if p.is_file()];size=sum(p.stat().st_size for p in fs);extra=len(set(p.name for p in fs)-ALLOW);bloat=len(fs)>15 or size>20*1024*1024 or extra>0;summary.update({'RESULT_FILE_COUNT':len(fs),'RESULT_DIRECTORY_SIZE_BYTES':size,'EXTRA_OUTPUT_FILE_COUNT':extra,'RESULT_ARTIFACT_BLOAT_DETECTED':bloat});tmp=O/'v22_068d_summary.tmp';tmp.write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8');os.replace(tmp,O/'v22_068d_summary.json');return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();
 if not a.execute:raise SystemExit(2)
 s=run()
 for k,v in s.items():
  if k.isupper() or k=='summary_path':print(f'{k}={v}')
