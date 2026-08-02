from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score,brier_score_loss,log_loss,roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder,StandardScaler

REPO=Path(__file__).resolve().parents[2]; OUT_NAME='V22.075A_FAST3_PATH_ORDER_TARGET_RESEARCH_R1'; DATA_ROOT=Path(r'D:/us-tech-quant-data/fast3/moomoo_24h_1m'); LEGACY_RESULTS_ROOT=Path(r'D:\us-tech-quant-results\fast3\archive\legacy_v22')
CONTRACT=LEGACY_RESULTS_ROOT/'V22.073A_FAST3_PIT_FEATURE_EXPANSION_RESEARCH_R1/feature_contract.json'; SYMS=['QQQ','SOXX','TQQQ','SQQQ','SOXL','SOXS']; COST=.001; TP=.030; SL=-.006
FEATURES=['PREMARKET_CUM_RETURN','MAX_DRAWDOWN','REALIZED_VOL','PREMARKET_LAST_15M_RETURN','PREMARKET_LAST_30M_RETURN','PREMARKET_LAST_60M_RETURN','PREMARKET_HIGH_LOW_RANGE','PREMARKET_CLOSE_LOCATION_VALUE','PREMARKET_RETURN_FROM_LOW','PREMARKET_RETURN_FROM_HIGH','PREMARKET_TREND_SLOPE','PREMARKET_TREND_R2','PREMARKET_POSITIVE_MINUTE_RATIO','PREMARKET_MAX_15M_UP_MOVE','PREMARKET_MAX_15M_DOWN_MOVE','QQQ_PREMARKET_RETURN','SOXX_PREMARKET_RETURN','QQQ_MINUS_SOXX_PREMARKET_RETURN','SYMBOL_MINUS_QQQ_PREMARKET_RETURN','SYMBOL_MINUS_SOXX_PREMARKET_RETURN','PREMARKET_VOLUME_SHARE_LAST_30M','PREMARKET_VOLUME_CONCENTRATION']
MODEL_SPECS={'LOGISTIC_REGRESSION':{'solver':'lbfgs','C':1.0,'max_iter':2000,'class_weight':'balanced','random_state':20260731},'CONSTRAINED_RANDOM_FOREST':{'n_estimators':300,'max_depth':4,'min_samples_leaf':80,'max_features':.75,'class_weight':'balanced','random_state':20260731,'n_jobs':-1}}
def num(x): return float(x) if x is not None and np.isfinite(x) else None
def dump(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n'
def months(): return [str(x)[:7] for x in pd.period_range('2018-07','2023-03',freq='M')]+[str(x)[:7] for x in pd.period_range('2023-05','2024-11',freq='M')]
def pfeat(c):
 r=np.diff(np.log(c)); x=np.arange(len(c)); slope=np.polyfit(x,np.log(c),1)[0] if len(c)>1 else np.nan; fit=np.polyval(np.polyfit(x,np.log(c),1),x) if len(c)>1 else np.array([np.nan]); ss=np.sum((np.log(c)-np.log(c).mean())**2); r2=1-np.sum((np.log(c)-fit)**2)/ss if ss else 0.; roll=np.array([c[i+15]/c[i]-1 for i in range(len(c)-15)]); hi,lo=c.max(),c.min(); rng=hi-lo
 return {'PREMARKET_CUM_RETURN':c[-1]/c[0]-1,'MAX_DRAWDOWN':np.min(c/np.maximum.accumulate(c)-1),'REALIZED_VOL':np.std(r,ddof=0),'PREMARKET_LAST_15M_RETURN':c[-1]/c[-16]-1 if len(c)>=16 else np.nan,'PREMARKET_LAST_30M_RETURN':c[-1]/c[-31]-1 if len(c)>=31 else np.nan,'PREMARKET_LAST_60M_RETURN':c[-1]/c[-61]-1 if len(c)>=61 else np.nan,'PREMARKET_HIGH_LOW_RANGE':rng/c[0],'PREMARKET_CLOSE_LOCATION_VALUE':(c[-1]-lo)/rng if rng else .5,'PREMARKET_RETURN_FROM_LOW':c[-1]/lo-1,'PREMARKET_RETURN_FROM_HIGH':c[-1]/hi-1,'PREMARKET_TREND_SLOPE':slope,'PREMARKET_TREND_R2':r2,'PREMARKET_POSITIVE_MINUTE_RATIO':np.mean(r>0) if len(r) else np.nan,'PREMARKET_MAX_15M_UP_MOVE':roll.max() if len(roll) else np.nan,'PREMARKET_MAX_15M_DOWN_MOVE':roll.min() if len(roll) else np.nan}
def vfeat(v):
 total=v.sum(); return {'PREMARKET_VOLUME_SHARE_LAST_30M':v[-30:].sum()/total if total>0 else np.nan,'PREMARKET_VOLUME_CONCENTRATION':np.sum((v/total)**2) if total>0 else np.nan}
def path_outcome(rth):
 entry=float(rth.iloc[0].open); tp=np.flatnonzero(rth.high.astype(float).to_numpy()>=entry*(1+TP)); sl=np.flatnonzero(rth.low.astype(float).to_numpy()<=entry*(1+SL)); a,b=(int(tp[0]) if len(tp) else None),(int(sl[0]) if len(sl) else None)
 if a is None and b is None: return 'NEITHER',float(rth.iloc[-1].close)/entry-1
 if a is None: return 'SL_FIRST',SL
 if b is None: return 'TP_FIRST',TP
 if a==b: return 'SAME_MINUTE_BOTH',SL
 return ('TP_FIRST',TP) if a<b else ('SL_FIRST',SL)
def build_events():
 rows=[]
 for month in months():
  for sym in SYMS:
   path=DATA_ROOT/'canonical'/f'symbol={sym}'/f'year={month[:4]}'/f'month={month[5:]}'/'data.parquet'
   if not path.is_file(): raise RuntimeError(f'RESEARCH_PARTITION_MISSING:{path}')
   need=['timestamp_et','open','high','low','close','volume']; schema=pq.ParquetFile(path).schema_arrow.names
   if any(c not in schema for c in need): raise RuntimeError(f'FEATURE_CONTRACT_INPUT_SCHEMA_FAILURE:{path}')
   f=pq.read_table(path,columns=need).to_pandas(); t=pd.to_datetime(f.timestamp_et,utc=True).dt.tz_convert('America/New_York'); f=f.assign(timestamp=t).dropna(subset=need); f['date']=f.timestamp.dt.date.astype(str)
   for date,day in f.groupby('date',sort=True):
    day=day.sort_values('timestamp'); tm=day.timestamp.dt.time; pre=day[(tm>=pd.Timestamp('04:00').time())&(tm<=pd.Timestamp('09:25').time())]; rth=day[(tm>=pd.Timestamp('09:30').time())&(tm<=pd.Timestamp('16:00').time())]
    if pre.timestamp.dt.floor('min').nunique()/326<.80 or rth.empty or not np.isfinite(pre.volume.astype(float)).all() or (pre.volume.astype(float)<0).any(): continue
    outcome,gross=path_outcome(rth); entry=float(rth.iloc[0].open); rows.append({'date':date,'symbol':sym,'path_outcome':outcome,'TP_BEFORE_SL':int(outcome=='TP_FIRST'),'PLUS_3PCT_HIT_BY_CLOSE':int((rth.high.astype(float)>=entry*(1+TP)).any()),'strategy_gross_return':gross,**pfeat(pre.close.astype(float).to_numpy()),**vfeat(pre.volume.astype(float).to_numpy())})
 e=pd.DataFrame(rows).sort_values(['date','symbol']).reset_index(drop=True); ctx=e.pivot(index='date',columns='symbol',values='PREMARKET_CUM_RETURN'); e['QQQ_PREMARKET_RETURN']=e.date.map(ctx['QQQ']); e['SOXX_PREMARKET_RETURN']=e.date.map(ctx['SOXX']); e['QQQ_MINUS_SOXX_PREMARKET_RETURN']=e.QQQ_PREMARKET_RETURN-e.SOXX_PREMARKET_RETURN; e['SYMBOL_MINUS_QQQ_PREMARKET_RETURN']=e.PREMARKET_CUM_RETURN-e.QQQ_PREMARKET_RETURN; e['SYMBOL_MINUS_SOXX_PREMARKET_RETURN']=e.PREMARKET_CUM_RETURN-e.SOXX_PREMARKET_RETURN
 return e
def folds(dates):
 b=np.array_split(np.asarray(sorted(set(dates))),6); return [{'fold_id':i+1,'train_dates':list(np.concatenate(b[:i+1])),'test_dates':list(b[i+1])} for i in range(5)]
def make_model(name):
 pre=ColumnTransformer([('numeric',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),FEATURES),('symbol',OneHotEncoder(handle_unknown='ignore'),['symbol'])]); est=LogisticRegression(**MODEL_SPECS[name]) if name=='LOGISTIC_REGRESSION' else RandomForestClassifier(**MODEL_SPECS[name]); return Pipeline([('preprocess',pre),('model',est)])
def lift(y,p):
 prev=float(np.mean(y)) if len(y) else None; return num(average_precision_score(y,p)/prev) if prev else None
def calibration(y,p):
 q=pd.DataFrame({'target':y,'prediction':p});q['decile']=pd.qcut(q.prediction.rank(method='first'),10,labels=False,duplicates='drop')+1;return [{'decile':int(k),'event_count':len(g),'mean_prediction':num(g.prediction.mean()),'observed_tp_before_sl_rate':num(g.target.mean())} for k,g in q.groupby('decile')]
def classify(x,fr,total):
 y=x.TP_BEFORE_SL.to_numpy();p=x.prediction.to_numpy();prev=num(y.mean());k=max(1,math.ceil(len(x)*.1));top=x.sort_values(['prediction','symbol','date'],ascending=[False,True,True]).head(k);fl=[z['pr_auc_lift'] for z in fr if z['pr_auc_lift'] is not None]
 return {'event_count':len(x),'research_coverage_ratio':num(len(x)/total),'target_prevalence':prev,'roc_auc':num(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,'pr_auc':num(average_precision_score(y,p)) if prev else None,'pr_auc_lift':lift(y,p),'brier_score':num(brier_score_loss(y,p)),'log_loss':num(log_loss(y,p,labels=[0,1])),'top_decile_tp_before_sl_rate':num(top.TP_BEFORE_SL.mean()),'top_decile_tp_before_sl_lift':num(top.TP_BEFORE_SL.mean()/prev) if prev else None,'positive_fold_lift_ratio':num(np.mean([z>1 for z in fl])) if fl else None,'median_fold_pr_auc_lift':num(np.median(fl)) if fl else None,'worst_fold_pr_auc_lift':num(min(fl)) if fl else None,'calibration_deciles':calibration(y,p)}
def top1(x,research_dates):
 z=x.sort_values(['date','prediction','symbol'],ascending=[True,False,True]).groupby('date',as_index=False).head(1).copy();z['net_return']=z.strategy_gross_return-COST;z['month']=z.date.str[:7];z['equity']=(1+z.net_return).cumprod();z['drawdown']=z.equity/z.equity.cummax()-1;g=z.net_return.clip(lower=0);tot=g.sum(); byf=[v.net_return.mean() for _,v in z.groupby('fold_id')];bym=[v.net_return.mean() for _,v in z.groupby('month')]
 d={'daily_top1_trade_count':len(z),'daily_top1_date_coverage_ratio':num(len(z)/research_dates),'daily_top1_mean_gross_return':num(z.strategy_gross_return.mean()),'daily_top1_mean_net_return':num(z.net_return.mean()),'daily_top1_median_net_return':num(z.net_return.median()),'daily_top1_cumulative_net_return':num(z.equity.iloc[-1]-1),'daily_top1_positive_trade_ratio':num((z.net_return>0).mean()),'daily_top1_positive_month_ratio':num(np.mean([v>0 for v in bym])),'daily_top1_positive_fold_ratio':num(np.mean([v>0 for v in byf])),'daily_top1_max_drawdown':num(z.drawdown.min()),'daily_top1_top5_date_profit_concentration':num(g.nlargest(5).sum()/tot) if tot>0 else None,'daily_top1_top10_trade_profit_concentration':num(g.nlargest(10).sum()/tot) if tot>0 else None,'daily_top1_single_symbol_max_selection_ratio':num(z.symbol.value_counts().max()/len(z))}
 for o in ['TP_FIRST','SL_FIRST','SAME_MINUTE_BOTH','NEITHER']: d[f'daily_top1_{o.lower()}_count']=int((z.path_outcome==o).sum());d[f'daily_top1_{o.lower()}_rate']=num((z.path_outcome==o).mean())
 return z,d
def passes(c,t): return all([c['research_coverage_ratio']>=.80,c.get('valid_fold_count')==5,c['pr_auc_lift'] is not None and c['pr_auc_lift']>=1.2,c['top_decile_tp_before_sl_lift'] is not None and c['top_decile_tp_before_sl_lift']>=1.5,c['positive_fold_lift_ratio'] is not None and c['positive_fold_lift_ratio']>=.6,c['median_fold_pr_auc_lift'] is not None and c['median_fold_pr_auc_lift']>1,t['daily_top1_trade_count']>=1000,t['daily_top1_date_coverage_ratio']>=.8,t['daily_top1_mean_net_return']>0,t['daily_top1_median_net_return']>=0,t['daily_top1_positive_month_ratio']>=.55,t['daily_top1_positive_fold_ratio']>=.6,t['daily_top1_tp_first_rate']>t['daily_top1_sl_first_rate'],t['daily_top1_top5_date_profit_concentration'] is not None and t['daily_top1_top5_date_profit_concentration']<.6,t['daily_top1_single_symbol_max_selection_ratio']<.6])
def run(results_root=LEGACY_RESULTS_ROOT):
 contract=json.loads(CONTRACT.read_text(encoding='utf-8'))
 if contract.get('usable_features')!=FEATURES or len(FEATURES)!=22: raise RuntimeError('FEATURE_CONTRACT_MISMATCH')
 e=build_events()
 if len(e)!=9497: raise RuntimeError(f'RESEARCH_EVENT_COUNT_MISMATCH:{len(e)}')
 fs=folds(e.date);allfold=[];models=[];tradesall=[];symbols=[];fits=0;dates=e.date.nunique()
 for name in MODEL_SPECS:
  parts=[];mf=[]
  for f in fs:
   tr=e[e.date.isin(f['train_dates'])];te=e[e.date.isin(f['test_dates'])]; valid=len(tr)>0 and len(te)>0 and tr.date.max()<te.date.min(); p=None
   if valid:
    p=make_model(name).fit(tr[FEATURES+['symbol']],tr.TP_BEFORE_SL).predict_proba(te[FEATURES+['symbol']])[:,1];fits+=1;q=te.copy();q['prediction']=p;q['fold_id']=f['fold_id'];parts.append(q)
   r={'model':name,'fold_id':f['fold_id'],'train_start_date':min(f['train_dates']),'train_end_date':max(f['train_dates']),'test_start_date':min(f['test_dates']),'test_end_date':max(f['test_dates']),'train_event_count':len(tr),'test_event_count':len(te),'pr_auc_lift':lift(te.TP_BEFORE_SL,p) if valid else None,'valid':valid,'time_order_valid':max(f['train_dates'])<min(f['test_dates'])};allfold.append(r);mf.append(r)
  x=pd.concat(parts,ignore_index=True);c=classify(x,mf,len(e));c.update({'model':name,'valid_fold_count':sum(r['valid'] for r in mf),'invalid_fold_count':sum(not r['valid'] for r in mf)});t,tm=top1(x,dates);c.update(tm);c['candidate_pass']=passes(c,tm);models.append(c);tradesall.append(t.assign(model=name))
  for sym in SYMS:
   a=x[x.symbol==sym];b=t[t.symbol==sym]; symbols.append({'model':name,'symbol':sym,'event_count':len(a),'TP_FIRST_count':int((a.path_outcome=='TP_FIRST').sum()),'TP_FIRST_rate':num((a.path_outcome=='TP_FIRST').mean()),'SL_FIRST_count':int((a.path_outcome=='SL_FIRST').sum()),'SL_FIRST_rate':num((a.path_outcome=='SL_FIRST').mean()),'NEITHER_count':int((a.path_outcome=='NEITHER').sum()),'NEITHER_rate':num((a.path_outcome=='NEITHER').mean()),'SAME_MINUTE_BOTH_count':int((a.path_outcome=='SAME_MINUTE_BOTH').sum()),'SAME_MINUTE_BOTH_rate':num((a.path_outcome=='SAME_MINUTE_BOTH').mean()),'selection_count':len(b),'selection_net_return':num(b.net_return.sum())})
 outcomes=[]
 for sym in ['ALL',*SYMS]:
  a=e if sym=='ALL' else e[e.symbol==sym]
  for o in ['TP_FIRST','SL_FIRST','NEITHER','SAME_MINUTE_BOTH']: outcomes.append({'symbol':sym,'path_outcome':o,'count':int((a.path_outcome==o).sum()),'rate':num((a.path_outcome==o).mean())})
 plus=e[e.PLUS_3PCT_HIT_BY_CLOSE==1]; slplus=int((plus.path_outcome=='SL_FIRST').sum()); ratio=num(slplus/len(plus)) if len(plus) else None; mismatch_ratio=num(plus.path_outcome.isin(['SL_FIRST','SAME_MINUTE_BOTH']).mean()) if len(plus) else None; mismatch=bool(mismatch_ratio is not None and mismatch_ratio>0)
 winners=[x for x in models if x['candidate_pass']];rank={'LOGISTIC_REGRESSION':0,'CONSTRAINED_RANDOM_FOREST':1};best=sorted(models,key=lambda x:(x['pr_auc_lift'] is not None,x['pr_auc_lift'] or -1),reverse=True)[0]; selected=sorted(winners,key=lambda x:(-x['daily_top1_mean_net_return'],-x['pr_auc_lift'],-x['daily_top1_tp_first_rate'],x['daily_top1_max_drawdown'],rank[x['model']]))[0] if winners else None
 s={'final_status':'PASS','final_decision':'PATH_ORDER_RESEARCH_CANDIDATE_FOUND' if selected else 'FAST3_PREMARKET_RESEARCH_STOPPED_NO_PATH_ORDER_EDGE','next_freeze_stage_allowed':bool(selected),'fast3_premarket_research_stopped':not bool(selected),'selected_model':selected['model'] if selected else None,'research_event_count':len(e),'research_date_count':dates,'former_development_role':'RESEARCH_DATA','former_validation_role':'RESEARCH_DATA','former_validation_still_independent':False,'confirmation_remains_sealed':True,'confirmation_row_read_count':0,'feature_contract_match':True,'input_feature_count':22,'candidate_model_count':2,'hyperparameter_search_count':0,'valid_fold_count':sum(x['valid'] for x in allfold if x['model']=='LOGISTIC_REGRESSION'),'invalid_fold_count':sum(not x['valid'] for x in allfold if x['model']=='LOGISTIC_REGRESSION'),'time_order_violation_count':sum(not x['time_order_valid'] for x in allfold),'data_leakage_detected':False,'research_fit_call_count':fits,'final_frozen_model_output_count':0,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,'live_trading_allowed':False,'order_output_count':0,'position_output_count':0,'broker_connection_count':0,'TP_FIRST_count':int((e.path_outcome=='TP_FIRST').sum()),'TP_FIRST_rate':num((e.path_outcome=='TP_FIRST').mean()),'SL_FIRST_count':int((e.path_outcome=='SL_FIRST').sum()),'SL_FIRST_rate':num((e.path_outcome=='SL_FIRST').mean()),'NEITHER_count':int((e.path_outcome=='NEITHER').sum()),'NEITHER_rate':num((e.path_outcome=='NEITHER').mean()),'SAME_MINUTE_BOTH_count':int((e.path_outcome=='SAME_MINUTE_BOTH').sum()),'SAME_MINUTE_BOTH_rate':num((e.path_outcome=='SAME_MINUTE_BOTH').mean()),'plus3_hit_tp_first_ratio':num((plus.path_outcome=='TP_FIRST').mean()) if len(plus) else None,'plus3_hit_sl_first_ratio':ratio,'plus3_hit_same_minute_both_ratio':num((plus.path_outcome=='SAME_MINUTE_BOTH').mean()) if len(plus) else None,'plus3_hit_but_sl_first_count':slplus,'plus3_hit_but_sl_first_ratio':ratio,'target_execution_mismatch_ratio':mismatch_ratio,'target_execution_mismatch_confirmed':mismatch,'best_model':best['model'],'best_pr_auc_lift':best['pr_auc_lift'],'best_top_decile_tp_before_sl_lift':best['top_decile_tp_before_sl_lift'],**{f'{x["model"].lower()}_{k}':x[k] for x in models for k in ('target_prevalence','roc_auc','pr_auc','pr_auc_lift','top_decile_tp_before_sl_lift','daily_top1_mean_net_return')},**{k:best[k] for k in best if k.startswith('daily_top1_')}}
 out=Path(results_root)/OUT_NAME;out.parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.075a_',dir=out.parent))
 try:
  (stage/'v22_075a_summary.json').write_text(dump(s),encoding='utf-8');(stage/'path_target_contract.json').write_text(dump({'target':'TP_BEFORE_SL','entry':'FIRST_RTH_MINUTE_OPEN','observation_window':'09:30-16:00 America/New_York','take_profit_threshold':TP,'stop_loss_threshold':SL,'uses_minute_high_and_low':True,'classes':['TP_FIRST','SL_FIRST','NEITHER','SAME_MINUTE_BOTH'],'same_minute_both_treatment':'SL_FIRST','cost_bps':10,'feature_contract_path':str(CONTRACT),'feature_contract_sha256':hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),'features':FEATURES,'confirmation_remains_sealed':True,'confirmation_row_read_count':0}),encoding='utf-8');pd.DataFrame([{k:v for k,v in x.items() if k!='calibration_deciles'} for x in models]).to_csv(stage/'classification_scorecard.csv',index=False);pd.DataFrame(allfold).to_csv(stage/'fold_scorecard.csv',index=False);pd.concat(tradesall,ignore_index=True).to_csv(stage/'daily_top1_trades.csv',index=False);pd.DataFrame(symbols).to_csv(stage/'symbol_scorecard.csv',index=False);pd.DataFrame(outcomes).to_csv(stage/'outcome_distribution.csv',index=False)
  if out.exists():shutil.rmtree(out)
  os.replace(stage,out);return s,out
 except Exception: shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');a.add_argument('--results-root',default=str(LEGACY_RESULTS_ROOT));z=a.parse_args()
 if z.execute:
  s,o=run(Path(z.results_root));print(json.dumps({**s,'summary_path':str(o/'v22_075a_summary.json')},ensure_ascii=False,sort_keys=True))
