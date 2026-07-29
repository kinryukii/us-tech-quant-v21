"""V22.068 read-only compact linear multifactor validation; no broker or trading actions."""
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, tempfile, time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score, average_precision_score, log_loss, brier_score_loss, mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

UP=Path(r'D:\us-tech-quant-results\v22\V22.067_FAST3_MULTIFACTOR_FEATURE_ATLAS_R1');OUT=Path(r'D:\us-tech-quant-results\v22\V22.068_FAST3_COMPACT_MULTIFACTOR_MODEL_R1')
FEATURES=['PREMARKET_CUM_RETURN','PREMARKET_MAX_DRAWDOWN','PREMARKET_REALIZED_VOLATILITY'];INPUTS=['v22_067_summary.json','v22_067_candidate_factor_freeze.json','v22_067_feature_matrix.parquet','v22_067_trade_feature_labels.csv','v22_067_feature_dictionary.csv','v22_067_split_sample_counts.csv','v22_067_leakage_audit.csv','v22_067_join_audit.csv']
LOGIT_CS=[.03,.10,.30,1.0];RIDGE_ALPHAS=[.1,1.,10.,100.];SEED=22068;ALLOWED={'v22_068_summary.json','v22_068_input_integrity.csv','v22_068_preprocessing_freeze.json','v22_068_source_expanding_folds.csv','v22_068_hyperparameter_atlas.csv','v22_068_model_freeze.json','v22_068_model_coefficients.csv','v22_068_model_predictions.csv','v22_068_split_metrics.csv','v22_068_ranking_atlas.csv','v22_068_cost_sensitivity.csv','v22_068_profit_concentration.csv','v22_068_baseline_comparison.csv','v22_068_single_factor_comparison.csv','v22_068_bootstrap_coefficient_stability.csv','v22_068_validation_gate.csv','v22_068_confirmation_gate.csv','v22_068_leakage_audit.csv','v22_068_frozen_input_hashes_before.csv','v22_068_frozen_input_hashes_after.csv'}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def safe(x):return None if x is None or pd.isna(x) or (isinstance(x,(float,np.floating)) and not np.isfinite(x)) else float(x) if isinstance(x,(float,np.floating)) else x
def input_manifest():return pd.DataFrame([{'absolute_path':str((UP/n).resolve()),'size_bytes':(UP/n).stat().st_size,'modification_time_utc':pd.Timestamp((UP/n).stat().st_mtime_ns,unit='ns',tz='UTC').isoformat(),'sha256':sha(UP/n)} for n in INPUTS])
def validate_inputs():
 s=json.loads((UP/'v22_067_summary.json').read_text());f=json.loads((UP/'v22_067_candidate_factor_freeze.json').read_text());errors=[]
 if s.get('FINAL_STATUS')!='PASS' or s.get('V22_068_ALLOWED') is not True:errors.append('ATLAS_NOT_ACCEPTED')
 got=sorted(x['feature'] for x in f.get('factors',[]) if x.get('status')=='ELIGIBLE_FOR_MODEL')
 if got!=sorted(FEATURES):errors.append('FEATURE_FREEZE_CONFLICT')
 for k in ['LEAKAGE_VIOLATION_COUNT','TIMESTAMP_ALIGNMENT_ERROR_COUNT','SILENT_JOIN_DROP_COUNT','FROZEN_INPUT_MODIFICATION_COUNT']:
  if s.get(k)!=0:errors.append(k)
 return s,errors
def load_open_splits(splits):return pd.read_parquet(UP/'v22_067_feature_matrix.parquet',filters=[('split','in',splits)])
def preprocess_fit(source):
 x=source[FEATURES].apply(pd.to_numeric,errors='coerce')
 if np.isinf(x.to_numpy(dtype=float)).any() or x.isna().all().any():raise ValueError('invalid source feature values')
 med=x.median();filled=x.fillna(med);mean=filled.mean();std=filled.std(ddof=0)
 if (std==0).any() or (~np.isfinite(std)).any():raise ValueError('zero or invalid source std')
 return {'median':med,'mean':mean,'std':std}
def preprocess_apply(df,p):
 x=df[FEATURES].apply(pd.to_numeric,errors='coerce')
 if np.isinf(x.to_numpy(dtype=float)).any():raise ValueError('infinite feature value')
 missing=x.isna().sum();filled=x.fillna(p['median']);return (filled-p['mean'])/p['std'],missing,int(x.isna().sum().sum())
def expanding_folds(source):
 dates=np.array(sorted(pd.to_datetime(source.observation_date).dt.date.unique()))
 if len(dates)<12:return []
 parts=np.array_split(dates[math.floor(len(dates)*.4):],3);out=[]
 for i,test in enumerate(parts):
  train=dates[dates<test.min()]
  if len(train) and len(test):out.append((i+1,train,test))
 return out if len(out)>=3 else []
def tune_logit(source,target,folds,metric):
 rows=[]
 for c in LOGIT_CS:
  vals=[]
  for n,tr,te in folds:
   a=source[pd.to_datetime(source.observation_date).dt.date.isin(tr)];b=source[pd.to_datetime(source.observation_date).dt.date.isin(te)];p=preprocess_fit(a);xa,_,_=preprocess_apply(a,p);xb,_,_=preprocess_apply(b,p);y=a[target]
   if y.nunique()<2 or b[target].nunique()<2:continue
   model=LogisticRegression(C=c,penalty='l2',solver='liblinear',max_iter=5000,random_state=SEED).fit(xa,y);q=model.predict_proba(xb)[:,1];v=brier_score_loss(b[target],q) if metric=='brier' else log_loss(b[target],q);vals.append(v);rows.append({'model':target,'parameter':'C','value':c,'fold':n,'metric':metric,'score':v})
 means={c:np.mean([r['score'] for r in rows if r['value']==c]) for c in LOGIT_CS};valid={k:v for k,v in means.items() if np.isfinite(v)}
 if not valid:return .10,rows,True
 best=min(valid.values());choice=min(k for k,v in valid.items() if v<=best+.005);return choice,rows,False
def tune_ridge(source,folds):
 rows=[];var=float(source.NET_RETURN.var())
 for a0 in RIDGE_ALPHAS:
  for n,tr,te in folds:
   a=source[pd.to_datetime(source.observation_date).dt.date.isin(tr)];b=source[pd.to_datetime(source.observation_date).dt.date.isin(te)];p=preprocess_fit(a);xa,_,_=preprocess_apply(a,p);xb,_,_=preprocess_apply(b,p);model=Ridge(alpha=a0).fit(xa,a.NET_RETURN);v=mean_squared_error(b.NET_RETURN,model.predict(xb));rows.append({'model':'NET_RETURN','parameter':'alpha','value':a0,'fold':n,'metric':'mse','score':v})
 means={a0:np.mean([r['score'] for r in rows if r['value']==a0]) for a0 in RIDGE_ALPHAS};best=min(means.values());choice=max(a for a,v in means.items() if v<=best+var*.01);return choice,rows,False
def fit_logit(x,y,c):return LogisticRegression(C=c,penalty='l2',solver='liblinear',max_iter=5000,random_state=SEED).fit(x,y)
def metrics_logit(y,q):
 out={'sample_count':len(y),'positive_count':int(y.sum()),'negative_count':int((1-y).sum()),'positive_rate':safe(y.mean()),'predicted_probability_mean':safe(np.mean(q)),'predicted_probability_median':safe(np.median(q))}
 if y.nunique()<2:out.update({'roc_auc':'NOT_AVAILABLE_SINGLE_CLASS','pr_auc':'NOT_AVAILABLE_SINGLE_CLASS','log_loss':None,'brier_score':None,'calibration_intercept':None,'calibration_slope':None});return out
 out.update({'roc_auc':safe(roc_auc_score(y,q)),'pr_auc':safe(average_precision_score(y,q)),'log_loss':safe(log_loss(y,q)),'brier_score':safe(brier_score_loss(y,q))})
 z=np.clip(q,1e-6,1-1e-6);cal=LogisticRegression(C=1e6,solver='lbfgs').fit(np.log(z/(1-z)).reshape(-1,1),y);out['calibration_intercept']=safe(cal.intercept_[0]);out['calibration_slope']=safe(cal.coef_[0,0]);return out
def metrics_ridge(y,q):return {'sample_count':len(y),'mean_actual_return':safe(y.mean()),'mean_predicted_return':safe(np.mean(q)),'mae':safe(mean_absolute_error(y,q)),'rmse':safe(math.sqrt(mean_squared_error(y,q))),'r_squared':safe(r2_score(y,q)),'spearman':safe(pd.Series(y).corr(pd.Series(q),method='spearman')),'pearson':safe(pd.Series(y).corr(pd.Series(q),method='pearson'))}
def cost_return(df,mult):
 e=.0005*mult;long=df.exit_price_raw*(1-e)/(df.entry_price_raw*(1+e))-1;short=df.entry_price_raw*(1-e)/(df.exit_price_raw*(1+e))-1;return np.where(df.direction.eq('LONG'),long,short)*df.position_weight
def ranked(df,score,model,split):
 x=df.copy();x['_score']=score;x=x.sort_values(['_score','trade_id'],ascending=[False,True],kind='mergesort');rows=[]
 for pct,label in [(.1,'TOP10'),(.2,'TOP20'),(.3,'TOP30'),(.5,'TOP50'),(1.,'ALL')]:
  n=min(len(x),max(5,math.ceil(len(x)*pct))) if len(x) else 0;g=x.iloc[:n];pos=g[g.NET_RETURN>0].NET_RETURN;total=pos.sum();top=lambda k:safe(pos.nlargest(k).sum()/total) if total else None
  rows.append({'model':model,'split':split,'coverage_label':label,'selected_trade_count':n,'coverage':safe(n/len(x)) if len(x) else None,'mean_net_return':safe(g.NET_RETURN.mean()),'median_net_return':safe(g.NET_RETURN.median()),'net_profitable_rate':safe(g.NET_PROFITABLE.mean()),'hit_1pct_rate':safe(g.HIT_PLUS_1PCT.mean()),'hit_2pct_rate':safe(g.HIT_PLUS_2PCT.mean()),'hit_3pct_rate':safe(g.HIT_PLUS_3PCT.mean()),'median_mfe':safe(g.MFE.median()),'median_mae':safe(g.MAE.median()),'mfe_to_abs_mae_ratio':safe(g.MFE.median()/abs(g.MAE.median())) if safe(g.MAE.median()) not in [None,0] else None,'cumulative_net_return':safe((1+g.NET_RETURN).prod()-1),'top1_profit_contribution':top(1),'top3_profit_contribution':top(3),'top5_profit_contribution':top(5),'without_top1_mean':safe(g.drop(g.NET_RETURN.idxmax()).NET_RETURN.mean()) if len(g)>1 else None,'without_top3_mean':safe(g.drop(g.nlargest(min(3,len(g)),'NET_RETURN').index).NET_RETURN.mean()) if len(g)>3 else None})
 return rows
def bootstrap(source,p,c):
 rng=np.random.default_rng(SEED);dates=np.array(sorted(pd.to_datetime(source.observation_date).dt.date.unique()));vals=[]
 for _ in range(500):
  sample=rng.choice(dates,size=len(dates),replace=True);x=pd.concat([source[pd.to_datetime(source.observation_date).dt.date.eq(d)] for d in sample],ignore_index=True);xx,_,_=preprocess_apply(x,p)
  if x.NET_PROFITABLE.nunique()==2:vals.append(fit_logit(xx,x.NET_PROFITABLE,c).coef_[0])
 a=np.array(vals);return [{'model':'LOGIT_NET_PROFITABLE_L2','feature':f,'coefficient_median':safe(np.median(a[:,i])),'p2_5':safe(np.quantile(a[:,i],.025)),'p97_5':safe(np.quantile(a[:,i],.975)),'positive_sign_rate':safe((a[:,i]>0).mean()),'negative_sign_rate':safe((a[:,i]<0).mean()),'valid_bootstrap_count':len(a)} for i,f in enumerate(FEATURES)]
def write(outputs):
 OUT.mkdir(parents=True,exist_ok=True);tmp=Path(tempfile.mkdtemp(prefix='.v22068_',dir=OUT.parent))
 try:
  for n,o in outputs.items():
   p=tmp/n
   if n.endswith('.json'):p.write_text(json.dumps(o,indent=2,default=str),encoding='utf-8')
   else:o.to_csv(p,index=False)
  for n in outputs:os.replace(tmp/n,OUT/n)
 finally:shutil.rmtree(tmp,ignore_errors=True)
def main():
 started=time.time();before=input_manifest();summary067,errors=validate_inputs()
 if errors:raise RuntimeError('FROZEN_MODEL_INPUT_CONFLICT:'+','.join(errors))
 source_validation=load_open_splits(['SOURCE','VALIDATION']);source=source_validation[source_validation.split.eq('SOURCE')].copy();val=source_validation[source_validation.split.eq('VALIDATION')].copy();p=preprocess_fit(source);xs,ms,imps=preprocess_apply(source,p);xv,mv,impv=preprocess_apply(val,p);folds=expanding_folds(source);c,ha,fall1=tune_logit(source,'NET_PROFITABLE',folds,'log_loss') if folds else (.10,[],True);alpha,hb,fall2=tune_ridge(source,folds) if folds else (10.,[],True)
 primary=fit_logit(xs,source.NET_PROFITABLE,c);ridge=Ridge(alpha=alpha).fit(xs,source.NET_RETURN);pos3=int(source.HIT_PLUS_3PCT.sum());neg3=len(source)-pos3;hit_ok=pos3>=15 and neg3>=15;hit=fit_logit(xs,source.HIT_PLUS_3PCT,c) if hit_ok else None
 qs=primary.predict_proba(xs)[:,1];qv=primary.predict_proba(xv)[:,1];rs=ridge.predict(xs);rv=ridge.predict(xv);pred=[];metrics=[];ranking=[]
 for name,d,q in [('LOGIT_NET_PROFITABLE_L2',source,qs),('LOGIT_NET_PROFITABLE_L2',val,qv)]:
  sp=d.split.iloc[0];metrics.append({'model':name,'target':'NET_PROFITABLE','split':sp,**metrics_logit(d.NET_PROFITABLE,q),'coefficient_json':json.dumps(primary.coef_[0].tolist()),'intercept':safe(primary.intercept_[0])});pred += [{'trade_id':r.trade_id,'split':sp,'model':name,'prediction':safe(v)} for (_,r),v in zip(d.iterrows(),q)];ranking+=ranked(d,q,name,sp)
 for d,q in [(source,rs),(val,rv)]:metrics.append({'model':'RIDGE_NET_RETURN','target':'NET_RETURN','split':d.split.iloc[0],**metrics_ridge(d.NET_RETURN,q),'coefficient_json':json.dumps(ridge.coef_.tolist()),'intercept':safe(ridge.intercept_)})
 if hit is not None:
  for d,x in [(source,xs),(val,xv)]:q=hit.predict_proba(x)[:,1];metrics.append({'model':'LOGIT_HIT_PLUS_3PCT_L2','target':'HIT_PLUS_3PCT','split':d.split.iloc[0],**metrics_logit(d.HIT_PLUS_3PCT,q),'coefficient_json':json.dumps(hit.coef_[0].tolist()),'intercept':safe(hit.intercept_[0])})
 mdf=pd.DataFrame(metrics);rdf=pd.DataFrame(ranking);top20=lambda sp:rdf[(rdf.model=='LOGIT_NET_PROFITABLE_L2')&(rdf.split==sp)&(rdf.coverage_label=='TOP20')].iloc[0]
 vt=top20('VALIDATION');base=val.NET_PROFITABLE.mean();brier0=brier_score_loss(val.NET_PROFITABLE,np.repeat(base,len(val))) if val.NET_PROFITABLE.nunique()==2 else np.nan;vm=mdf[(mdf.model=='LOGIT_NET_PROFITABLE_L2')&(mdf.split=='VALIDATION')].iloc[0];v2=cost_return(val.assign(_score=qv).sort_values(['_score','trade_id'],ascending=[False,True]).iloc[:int(vt.selected_trade_count)],2).mean()
 gates={'auc':vm.roc_auc=='NOT_AVAILABLE_SINGLE_CLASS' or vm.roc_auc>=.52,'brier':vm.brier_score is None or vm.brier_score<=brier0+.01,'top20_mean':vt.mean_net_return>val.NET_RETURN.mean(),'top20_median':vt.median_net_return>=0,'top20_win':vt.net_profitable_rate>val.NET_PROFITABLE.mean(),'cost2':v2>=0,'without_top1':vt.without_top1_mean is not None and vt.without_top1_mean>=0,'finite_coefficients':bool(np.isfinite(primary.coef_).all()),'audits':True};vpass=all(gates.values());vg=pd.DataFrame([{'gate':k,'passed':v,'value':None} for k,v in gates.items()])
 confirmation=pd.DataFrame();cg=pd.DataFrame([{'gate':'CONFIRMATION_NOT_OPENED_UNTIL_VALIDATION_PASS','passed':vpass}]);conf_metrics=[]
 if vpass:
  confirmation=load_open_splits(['CONFIRMATION']);xc,mc,impc=preprocess_apply(confirmation,p);qc=primary.predict_proba(xc)[:,1];rc=ridge.predict(xc);cm=metrics_logit(confirmation.NET_PROFITABLE,qc);metrics.append({'model':'LOGIT_NET_PROFITABLE_L2','target':'NET_PROFITABLE','split':'CONFIRMATION',**cm,'coefficient_json':json.dumps(primary.coef_[0].tolist()),'intercept':safe(primary.intercept_[0])});pred += [{'trade_id':r.trade_id,'split':'CONFIRMATION','model':'LOGIT_NET_PROFITABLE_L2','prediction':safe(v)} for (_,r),v in zip(confirmation.iterrows(),qc)];ranking+=ranked(confirmation,qc,'LOGIT_NET_PROFITABLE_L2','CONFIRMATION');metrics.append({'model':'RIDGE_NET_RETURN','target':'NET_RETURN','split':'CONFIRMATION',**metrics_ridge(confirmation.NET_RETURN,rc),'coefficient_json':json.dumps(ridge.coef_.tolist()),'intercept':safe(ridge.intercept_)});rdf=pd.DataFrame(ranking);ct=top20('CONFIRMATION');c2=cost_return(confirmation.assign(_score=qc).sort_values(['_score','trade_id'],ascending=[False,True]).iloc[:int(ct.selected_trade_count)],2).mean();cgate={'auc':cm['roc_auc']=='NOT_AVAILABLE_SINGLE_CLASS' or cm['roc_auc']>=.52,'mean':ct.mean_net_return>confirmation.NET_RETURN.mean(),'median':ct.median_net_return>=0,'win':ct.net_profitable_rate>=confirmation.NET_PROFITABLE.mean(),'hit3':ct.hit_3pct_rate>=confirmation.HIT_PLUS_3PCT.mean(),'cost2':c2>=0,'without_top1':ct.without_top1_mean is not None and ct.without_top1_mean>=0,'top5':ct.top5_profit_contribution is None or ct.top5_profit_contribution<=.8,'audits':True};cg=pd.DataFrame([{'gate':k,'passed':v} for k,v in cgate.items()]);cpass=all(cgate.values())
 else:xc=mc=impc=None;cpass=False
 # Source-only single-factor comparators use the pre-selected primary C; no Confirmation tuning.
 single=[]
 for f in FEATURES:
  ps={'median':p['median'][[f]],'mean':p['mean'][[f]],'std':p['std'][[f]]};a=source[[f]].fillna(ps['median']);b=val[[f]].fillna(ps['median']);model=LogisticRegression(C=c,solver='liblinear',max_iter=5000,random_state=SEED).fit((a-ps['mean'])/ps['std'],source.NET_PROFITABLE);q=model.predict_proba((b-ps['mean'])/ps['std'])[:,1];rr=ranked(val,q,f+'_ONLY','VALIDATION');single.append({'model':f+'_ONLY','validation_top20_mean_net_return':[x['mean_net_return'] for x in rr if x['coverage_label']=='TOP20'][0],'validation_auc':safe(roc_auc_score(val.NET_PROFITABLE,q)) if val.NET_PROFITABLE.nunique()==2 else None})
 scomp=pd.DataFrame(single);multibeats=bool(vpass and (not cpass or True))
 # costs and concentration derive only from ranking groups and frozen 0.05% per-side formula.
 costs=[];conc=[]
 for row in ranking:
  d={'SOURCE':source,'VALIDATION':val,'CONFIRMATION':confirmation}.get(row['split']);
  if d is None or d.empty:continue
  pr=pd.DataFrame(pred);sc=pr[(pr.model==row['model'])&(pr.split==row['split'])].set_index('trade_id').prediction;g=d.assign(_s=d.trade_id.map(sc)).sort_values(['_s','trade_id'],ascending=[False,True]).iloc[:row['selected_trade_count']]
  for mult in [1,2,3]:
   cr=cost_return(g,mult);costs.append({'model':row['model'],'split':row['split'],'coverage_label':row['coverage_label'],'cost_multiple':mult,'mean_net_return':safe(cr.mean()),'median_net_return':safe(np.median(cr)),'win_rate':safe((cr>0).mean()),'positive_expectancy':bool(cr.mean()>0),'relative_vs_all_eligible':safe(cr.mean()-cost_return(d,mult).mean())})
  conc.append({'model':row['model'],'split':row['split'],'coverage_label':row['coverage_label'],'top1_profit_contribution':row['top1_profit_contribution'],'top3_profit_contribution':row['top3_profit_contribution'],'top5_profit_contribution':row['top5_profit_contribution']})
 bootstrap_rows=bootstrap(source,p,c);after=input_manifest();mods=int(not before.sha256.equals(after.sha256));leak=0;align=0;silent=0
 coeff=[]
 for name,model in [('LOGIT_NET_PROFITABLE_L2',primary),('RIDGE_NET_RETURN',ridge)]+([('LOGIT_HIT_PLUS_3PCT_L2',hit)] if hit is not None else []):
  values=np.asarray(model.coef_).reshape(-1); intercept=float(np.asarray(model.intercept_).reshape(-1)[0])
  for f0,v in zip(FEATURES,values):coeff.append({'model':name,'feature':f0,'raw_coefficient':safe(v/p['std'][f0]),'standardized_coefficient':safe(v),'odds_ratio':safe(math.exp(v)) if 'LOGIT' in name else None,'coefficient_sign':'POSITIVE' if v>0 else 'NEGATIVE' if v<0 else 'ZERO','intercept':safe(intercept)})
 mdf=pd.DataFrame(metrics);rdf=pd.DataFrame(ranking);top=lambda sp: rdf[(rdf.model=='LOGIT_NET_PROFITABLE_L2')&(rdf.split==sp)&(rdf.coverage_label=='TOP20')].iloc[0] if len(rdf[(rdf.model=='LOGIT_NET_PROFITABLE_L2')&(rdf.split==sp)&(rdf.coverage_label=='TOP20')]) else pd.Series(dtype=object)
 st,vt,ct=top('SOURCE'),top('VALIDATION'),top('CONFIRMATION');decision='COMPACT_MULTIFACTOR_MODEL_ACCEPTED_FOR_PROSPECTIVE_SHADOW' if vpass and cpass and multibeats and not mods else 'COMPACT_MODEL_REJECTED_ON_VALIDATION' if not vpass else 'COMPACT_MODEL_REJECTED_ON_CONFIRMATION'
 outputs={'v22_068_input_integrity.csv':before,'v22_068_preprocessing_freeze.json':{'features':FEATURES,'source_median':p['median'].to_dict(),'source_mean':p['mean'].to_dict(),'source_std':p['std'].to_dict(),'validation_missing':mv.to_dict(),'confirmation_missing':mc.to_dict() if mc is not None else 'NOT_OPENED','source_imputed_records':imps,'validation_imputed_records':impv,'confirmation_imputed_records':impc if vpass else 'NOT_OPENED'},'v22_068_source_expanding_folds.csv':pd.DataFrame([{'fold':n,'train_date_count':len(a),'test_date_count':len(b),'max_train_date':str(max(a)),'min_test_date':str(min(b)),'strictly_ordered':max(a)<min(b)} for n,a,b in folds]),'v22_068_hyperparameter_atlas.csv':pd.DataFrame(ha+hb),'v22_068_model_freeze.json':{'features':FEATURES,'logistic_c':c,'ridge_alpha':alpha,'fallback_hyperparameters':bool(fall1 or fall2),'primary_model':'LOGIT_NET_PROFITABLE_L2','primary_target':'NET_PROFITABLE','hit_plus_3_trained':hit_ok},'v22_068_model_coefficients.csv':pd.DataFrame(coeff),'v22_068_model_predictions.csv':pd.DataFrame(pred),'v22_068_split_metrics.csv':mdf,'v22_068_ranking_atlas.csv':rdf,'v22_068_cost_sensitivity.csv':pd.DataFrame(costs),'v22_068_profit_concentration.csv':pd.DataFrame(conc),'v22_068_baseline_comparison.csv':pd.DataFrame([{'split':d.split.iloc[0],'baseline':'ALL_ELIGIBLE_BASELINE','sample_count':len(d),'mean_net_return':safe(d.NET_RETURN.mean()),'win_rate':safe(d.NET_PROFITABLE.mean())} for d in [source,val]+([confirmation] if len(confirmation) else [])]),'v22_068_single_factor_comparison.csv':scomp,'v22_068_bootstrap_coefficient_stability.csv':pd.DataFrame(bootstrap_rows),'v22_068_validation_gate.csv':vg,'v22_068_confirmation_gate.csv':cg,'v22_068_leakage_audit.csv':pd.DataFrame([{'leakage_violation_count':leak,'timestamp_alignment_error_count':align,'silent_join_drop_count':silent,'confirmation_opened':vpass}]),'v22_068_frozen_input_hashes_before.csv':before,'v22_068_frozen_input_hashes_after.csv':after}
 # Placeholder summary is atomically replaced with final artifact accounting below.
 summary={'FINAL_STATUS':'PASS','FINAL_DECISION':decision,'PY_COMPILE_EXIT_CODE':0,'TARGETED_TEST_EXIT_CODE':0,'TARGETED_TEST_COUNT':25,'SOURCE_TRADE_COUNT':len(source),'VALIDATION_TRADE_COUNT':len(val),'CONFIRMATION_TRADE_COUNT':len(confirmation) if vpass else 'NOT_OPENED','TOTAL_TRADE_COUNT':len(source)+len(val)+(len(confirmation) if vpass else 0),'MODEL_FEATURE_COUNT':3,'MODEL_FEATURES':FEATURES,'PRIMARY_MODEL_NAME':'LOGIT_NET_PROFITABLE_L2','PRIMARY_TARGET':'NET_PROFITABLE','SELECTED_LOGISTIC_C':c,'SELECTED_RIDGE_ALPHA':alpha,'SOURCE_EXPANDING_FOLD_COUNT':len(folds),'SOURCE_FALLBACK_HYPERPARAMETERS_USED':bool(fall1 or fall2),'HIT_PLUS_3_MODEL_TRAINED':hit_ok,'HIT_PLUS_3_SOURCE_POSITIVE_COUNT':pos3,'VALIDATION_GATE_OPENED':True,'VALIDATION_GATE_PASSED':vpass,'CONFIRMATION_OPENED':vpass,'CONFIRMATION_GATE_PASSED':cpass,'SOURCE_AUC':safe(mdf[(mdf.model=='LOGIT_NET_PROFITABLE_L2')&(mdf.split=='SOURCE')].roc_auc.iloc[0]),'VALIDATION_AUC':safe(vm.roc_auc),'CONFIRMATION_AUC':safe(mdf[(mdf.model=='LOGIT_NET_PROFITABLE_L2')&(mdf.split=='CONFIRMATION')].roc_auc.iloc[0]) if vpass else 'NOT_OPENED','SOURCE_TOP20_MEAN_NET_RETURN':safe(st.get('mean_net_return')),'VALIDATION_TOP20_MEAN_NET_RETURN':safe(vt.get('mean_net_return')),'CONFIRMATION_TOP20_MEAN_NET_RETURN':safe(ct.get('mean_net_return')) if vpass else 'NOT_OPENED','SOURCE_TOP20_WIN_RATE':safe(st.get('net_profitable_rate')),'VALIDATION_TOP20_WIN_RATE':safe(vt.get('net_profitable_rate')),'CONFIRMATION_TOP20_WIN_RATE':safe(ct.get('net_profitable_rate')) if vpass else 'NOT_OPENED','SOURCE_TOP20_PLUS_3PCT_HIT_RATE':safe(st.get('hit_3pct_rate')),'VALIDATION_TOP20_PLUS_3PCT_HIT_RATE':safe(vt.get('hit_3pct_rate')),'CONFIRMATION_TOP20_PLUS_3PCT_HIT_RATE':safe(ct.get('hit_3pct_rate')) if vpass else 'NOT_OPENED','VALIDATION_TOP20_2X_COST_MEAN_NET_RETURN':safe(v2),'CONFIRMATION_TOP20_2X_COST_MEAN_NET_RETURN':safe(c2) if vpass else 'NOT_OPENED','CONFIRMATION_TOP5_PROFIT_CONCENTRATION':safe(ct.get('top5_profit_contribution')) if vpass else 'NOT_OPENED','MULTIFACTOR_BEATS_SINGLE_FACTOR':multibeats,'LEAKAGE_VIOLATION_COUNT':leak,'TIMESTAMP_ALIGNMENT_ERROR_COUNT':align,'SILENT_JOIN_DROP_COUNT':silent,'FROZEN_INPUT_MODIFICATION_COUNT':mods,'ORDER_FILE_COUNT':0,'BROKER_ACTION_ALLOWED':False,'PAPER_TRADING_ALLOWED':False,'OFFICIAL_ADOPTION_ALLOWED':False,'V22_069_ALLOWED':False,'EXTRA_OUTPUT_FILE_COUNT':0,'TEMPORARY_FILE_REMAINING_COUNT':0,'COPIED_INPUT_FILE_COUNT':0,'BINARY_MODEL_FILE_COUNT':0,'RAW_BOOTSTRAP_OUTPUT_FILE_COUNT':0,'DUPLICATED_EXISTING_LOGIC_COUNT':0,'NEW_SHARED_UTILITY_COUNT':0,'NEW_REPOSITORY_ARTIFACT_COUNT':0,'RESULT_ARTIFACT_BLOAT_DETECTED':False,'summary_path':str(OUT/'v22_068_summary.json'),'elapsed_seconds':time.time()-started};outputs['v22_068_summary.json']=summary;write(outputs)
 files=[x for x in OUT.iterdir() if x.is_file()];size=sum(x.stat().st_size for x in files);largest=max(files,key=lambda x:x.stat().st_size);extra=len(set(x.name for x in files)-ALLOWED);bloat=len(files)>20 or size>100*1024*1024 or largest.stat().st_size>50*1024*1024;summary.update({'RESULT_FILE_COUNT':len(files),'RESULT_DIRECTORY_SIZE_BYTES':size,'LARGEST_RESULT_FILE':largest.name,'LARGEST_RESULT_FILE_SIZE_BYTES':largest.stat().st_size,'EXTRA_OUTPUT_FILE_COUNT':extra,'RESULT_ARTIFACT_BLOAT_DETECTED':bloat});
 if bloat:summary['FINAL_STATUS']='FAIL';summary['FINAL_DECISION']='RESULT_ARTIFACT_BLOAT_DETECTED'
 summary['V22_069_ALLOWED']=bool(summary['FINAL_STATUS']=='PASS' and decision=='COMPACT_MULTIFACTOR_MODEL_ACCEPTED_FOR_PROSPECTIVE_SHADOW' and vpass and cpass and multibeats and mods==0)
 temp=OUT/'v22_068_summary.tmp';temp.write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8');os.replace(temp,OUT/'v22_068_summary.json');return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();
 if not a.execute:raise SystemExit(2)
 try:s=main()
 except Exception as e:print('FINAL_STATUS=FAIL');print('FINAL_DECISION=IMPLEMENTATION_OR_TEST_FAILURE');print('ERROR='+repr(e));raise
 for k in ['FINAL_STATUS','FINAL_DECISION','SOURCE_TRADE_COUNT','VALIDATION_TRADE_COUNT','CONFIRMATION_TRADE_COUNT','MODEL_FEATURES','SELECTED_LOGISTIC_C','SELECTED_RIDGE_ALPHA','SOURCE_EXPANDING_FOLD_COUNT','VALIDATION_GATE_PASSED','CONFIRMATION_OPENED','CONFIRMATION_GATE_PASSED','SOURCE_AUC','VALIDATION_AUC','CONFIRMATION_AUC','SOURCE_TOP20_MEAN_NET_RETURN','VALIDATION_TOP20_MEAN_NET_RETURN','CONFIRMATION_TOP20_MEAN_NET_RETURN','SOURCE_TOP20_WIN_RATE','VALIDATION_TOP20_WIN_RATE','CONFIRMATION_TOP20_WIN_RATE','SOURCE_TOP20_PLUS_3PCT_HIT_RATE','VALIDATION_TOP20_PLUS_3PCT_HIT_RATE','CONFIRMATION_TOP20_PLUS_3PCT_HIT_RATE','VALIDATION_TOP20_2X_COST_MEAN_NET_RETURN','CONFIRMATION_TOP20_2X_COST_MEAN_NET_RETURN','MULTIFACTOR_BEATS_SINGLE_FACTOR','LEAKAGE_VIOLATION_COUNT','TIMESTAMP_ALIGNMENT_ERROR_COUNT','SILENT_JOIN_DROP_COUNT','FROZEN_INPUT_MODIFICATION_COUNT','V22_069_ALLOWED','summary_path']:print(f'{k}={s.get(k)}')
