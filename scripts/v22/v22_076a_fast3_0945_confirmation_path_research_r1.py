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
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

REPO=Path(__file__).resolve().parents[2]; OUT_NAME='V22.076A_FAST3_0945_CONFIRMATION_PATH_RESEARCH_R1'; LEGACY_RESULTS_ROOT=Path(r'D:\us-tech-quant-results\fast3\archive\legacy_v22')
DATA_ROOT=Path(r'D:/us-tech-quant-data/fast3/moomoo_24h_1m'); CONTRACT=LEGACY_RESULTS_ROOT/'V22.073A_FAST3_PIT_FEATURE_EXPANSION_RESEARCH_R1/feature_contract.json'
SYMS=['QQQ','SOXX','TQQQ','SQQQ','SOXL','SOXS']; COST=.001; TP=.030; SL=-.006
PREMARKET_FEATURES=['PREMARKET_CUM_RETURN','MAX_DRAWDOWN','REALIZED_VOL','PREMARKET_LAST_15M_RETURN','PREMARKET_LAST_30M_RETURN','PREMARKET_LAST_60M_RETURN','PREMARKET_HIGH_LOW_RANGE','PREMARKET_CLOSE_LOCATION_VALUE','PREMARKET_RETURN_FROM_LOW','PREMARKET_RETURN_FROM_HIGH','PREMARKET_TREND_SLOPE','PREMARKET_TREND_R2','PREMARKET_POSITIVE_MINUTE_RATIO','PREMARKET_MAX_15M_UP_MOVE','PREMARKET_MAX_15M_DOWN_MOVE','QQQ_PREMARKET_RETURN','SOXX_PREMARKET_RETURN','QQQ_MINUS_SOXX_PREMARKET_RETURN','SYMBOL_MINUS_QQQ_PREMARKET_RETURN','SYMBOL_MINUS_SOXX_PREMARKET_RETURN','PREMARKET_VOLUME_SHARE_LAST_30M','PREMARKET_VOLUME_CONCENTRATION']
CONFIRMATION_FEATURES=['OPEN_TO_0945_RETURN','OPEN_TO_0945_MAX_RETURN','OPEN_TO_0945_MIN_RETURN','OPEN_TO_0945_HIGH_LOW_RANGE','OPEN_TO_0945_REALIZED_VOL','OPEN_TO_0945_MAX_DRAWDOWN','OPEN_TO_0945_CLOSE_LOCATION_VALUE','OPEN_TO_0945_POSITIVE_MINUTE_RATIO','OPEN_TO_0945_LAST_5M_RETURN','OPEN_TO_0945_VOLUME','OPEN_TO_0945_LAST_5M_VOLUME_SHARE','SYMBOL_0945_RETURN_MINUS_QQQ','SYMBOL_0945_RETURN_MINUS_SOXX','QQQ_OPEN_TO_0945_RETURN','SOXX_OPEN_TO_0945_RETURN']
VOLUME_CONFIRMATION_FEATURES=CONFIRMATION_FEATURES[9:11]
MODEL_SPECS={'LOGISTIC_REGRESSION':{'solver':'lbfgs','C':1.0,'max_iter':2000,'class_weight':'balanced','random_state':20260731},'CONSTRAINED_RANDOM_FOREST':{'n_estimators':300,'max_depth':4,'min_samples_leaf':80,'max_features':.75,'class_weight':'balanced','random_state':20260731,'n_jobs':-1}}
def num(x): return float(x) if x is not None and np.isfinite(x) else None
def dump(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n'
def months(): return [str(x)[:7] for x in pd.period_range('2018-07','2023-03',freq='M')]+[str(x)[:7] for x in pd.period_range('2023-05','2024-11',freq='M')]
def pfeat(c):
 r=np.diff(np.log(c)); x=np.arange(len(c)); slope=np.polyfit(x,np.log(c),1)[0] if len(c)>1 else np.nan; fit=np.polyval(np.polyfit(x,np.log(c),1),x) if len(c)>1 else np.array([np.nan]); ss=np.sum((np.log(c)-np.log(c).mean())**2); r2=1-np.sum((np.log(c)-fit)**2)/ss if ss else 0.; roll=np.array([c[i+15]/c[i]-1 for i in range(len(c)-15)]); hi,lo=c.max(),c.min(); rng=hi-lo
 return {'PREMARKET_CUM_RETURN':c[-1]/c[0]-1,'MAX_DRAWDOWN':np.min(c/np.maximum.accumulate(c)-1),'REALIZED_VOL':np.std(r,ddof=0),'PREMARKET_LAST_15M_RETURN':c[-1]/c[-16]-1 if len(c)>=16 else np.nan,'PREMARKET_LAST_30M_RETURN':c[-1]/c[-31]-1 if len(c)>=31 else np.nan,'PREMARKET_LAST_60M_RETURN':c[-1]/c[-61]-1 if len(c)>=61 else np.nan,'PREMARKET_HIGH_LOW_RANGE':rng/c[0],'PREMARKET_CLOSE_LOCATION_VALUE':(c[-1]-lo)/rng if rng else .5,'PREMARKET_RETURN_FROM_LOW':c[-1]/lo-1,'PREMARKET_RETURN_FROM_HIGH':c[-1]/hi-1,'PREMARKET_TREND_SLOPE':slope,'PREMARKET_TREND_R2':r2,'PREMARKET_POSITIVE_MINUTE_RATIO':np.mean(r>0) if len(r) else np.nan,'PREMARKET_MAX_15M_UP_MOVE':roll.max() if len(roll) else np.nan,'PREMARKET_MAX_15M_DOWN_MOVE':roll.min() if len(roll) else np.nan}
def vfeat(v):
 total=v.sum(); return {'PREMARKET_VOLUME_SHARE_LAST_30M':v[-30:].sum()/total if total>0 else np.nan,'PREMARKET_VOLUME_CONCENTRATION':np.sum((v/total)**2) if total>0 else np.nan}
def cfeat(x, volume):
 o=float(x.iloc[0].open); c=x.close.astype(float).to_numpy(); hi=x.high.astype(float).to_numpy(); lo=x.low.astype(float).to_numpy(); r=np.diff(np.log(c)); rng=hi.max()-lo.min(); ans={'OPEN_TO_0945_RETURN':c[-1]/o-1,'OPEN_TO_0945_MAX_RETURN':hi.max()/o-1,'OPEN_TO_0945_MIN_RETURN':lo.min()/o-1,'OPEN_TO_0945_HIGH_LOW_RANGE':rng/o,'OPEN_TO_0945_REALIZED_VOL':np.std(r,ddof=0),'OPEN_TO_0945_MAX_DRAWDOWN':np.min(c/np.maximum.accumulate(c)-1),'OPEN_TO_0945_CLOSE_LOCATION_VALUE':(c[-1]-lo.min())/rng if rng else .5,'OPEN_TO_0945_POSITIVE_MINUTE_RATIO':np.mean(r>0) if len(r) else np.nan,'OPEN_TO_0945_LAST_5M_RETURN':c[-1]/c[-6]-1 if len(c)>=6 else np.nan}
 if volume:
  v=x.volume.astype(float).to_numpy(); ans.update({'OPEN_TO_0945_VOLUME':float(v.sum()),'OPEN_TO_0945_LAST_5M_VOLUME_SHARE':float(v[-5:].sum()/v.sum()) if v.sum()>0 else np.nan})
 return ans
def path_outcome(post):
 entry=float(post.iloc[0].open); tp=np.flatnonzero(post.high.astype(float).to_numpy()>=entry*(1+TP)); sl=np.flatnonzero(post.low.astype(float).to_numpy()<=entry*(1+SL)); a,b=(int(tp[0]) if len(tp) else None),(int(sl[0]) if len(sl) else None)
 if a is None and b is None:return 'NEITHER',float(post.iloc[-1].close)/entry-1
 if a is None:return 'SL_FIRST',SL
 if b is None:return 'TP_FIRST',TP
 if a==b:return 'SAME_MINUTE_BOTH',SL
 return ('TP_FIRST',TP) if a<b else ('SL_FIRST',SL)
def build_events():
 rows=[]; use_volume=True; volume_reason=None
 for month in months():
  for sym in SYMS:
   path=DATA_ROOT/'canonical'/f'symbol={sym}'/f'year={month[:4]}'/f'month={month[5:]}'/'data.parquet'
   if not path.is_file(): raise RuntimeError(f'RESEARCH_PARTITION_MISSING:{path}')
   schema=pq.ParquetFile(path).schema_arrow.names; required=['timestamp_et','open','high','low','close']
   if any(c not in schema for c in required): raise RuntimeError(f'FEATURE_CONTRACT_INPUT_SCHEMA_FAILURE:{path}')
   has_volume='volume' in schema
   if not has_volume: use_volume=False; volume_reason='CANONICAL_VOLUME_FIELD_MISSING'
   f=pq.read_table(path,columns=required+(['volume'] if has_volume else [])).to_pandas(); t=pd.to_datetime(f.timestamp_et,utc=True).dt.tz_convert('America/New_York'); f=f.assign(timestamp=t).dropna(subset=required); f['date']=f.timestamp.dt.date.astype(str)
   for date,day in f.groupby('date',sort=True):
    day=day.sort_values('timestamp'); tm=day.timestamp.dt.time; pre=day[(tm>=pd.Timestamp('04:00').time())&(tm<=pd.Timestamp('09:25').time())]; confirm=day[(tm>=pd.Timestamp('09:30').time())&(tm<=pd.Timestamp('09:45').time())]; post=day[(tm>=pd.Timestamp('09:45').time())&(tm<=pd.Timestamp('16:00').time())]
    if pre.timestamp.dt.floor('min').nunique()/326<.80 or confirm.timestamp.dt.floor('min').nunique()<16 or post.empty: continue
    valid_pre_volume=has_volume and np.isfinite(pre.volume.astype(float)).all() and not (pre.volume.astype(float)<0).any()
    if not valid_pre_volume: continue # Frozen premarket contract requires both premarket volume features.
    valid_confirmation_volume=has_volume and np.isfinite(confirm.volume.astype(float)).all() and not (confirm.volume.astype(float)<0).any()
    if not valid_confirmation_volume: use_volume=False; volume_reason='CANONICAL_CONFIRMATION_VOLUME_NOT_COMPLETE_FINITE_NONNEGATIVE'
    outcome,gross=path_outcome(post); row={'date':date,'symbol':sym,'path_outcome':outcome,'TP_BEFORE_SL_FROM_0945':int(outcome=='TP_FIRST'),'strategy_gross_return':gross,**pfeat(pre.close.astype(float).to_numpy()),**vfeat(pre.volume.astype(float).to_numpy()),**cfeat(confirm,valid_confirmation_volume)}; rows.append(row)
 e=pd.DataFrame(rows).sort_values(['date','symbol']).reset_index(drop=True)
 if not use_volume: e=e.drop(columns=VOLUME_CONFIRMATION_FEATURES,errors='ignore')
 pm=e.pivot(index='date',columns='symbol',values='PREMARKET_CUM_RETURN'); cm=e.pivot(index='date',columns='symbol',values='OPEN_TO_0945_RETURN')
 for key,sym in [('QQQ_PREMARKET_RETURN','QQQ'),('SOXX_PREMARKET_RETURN','SOXX')]: e[key]=e.date.map(pm.get(sym,pd.Series(dtype=float)))
 e['QQQ_MINUS_SOXX_PREMARKET_RETURN']=e.QQQ_PREMARKET_RETURN-e.SOXX_PREMARKET_RETURN; e['SYMBOL_MINUS_QQQ_PREMARKET_RETURN']=e.PREMARKET_CUM_RETURN-e.QQQ_PREMARKET_RETURN; e['SYMBOL_MINUS_SOXX_PREMARKET_RETURN']=e.PREMARKET_CUM_RETURN-e.SOXX_PREMARKET_RETURN
 e['QQQ_OPEN_TO_0945_RETURN']=e.date.map(cm.get('QQQ',pd.Series(dtype=float))); e['SOXX_OPEN_TO_0945_RETURN']=e.date.map(cm.get('SOXX',pd.Series(dtype=float))); e['SYMBOL_0945_RETURN_MINUS_QQQ']=e.OPEN_TO_0945_RETURN-e.QQQ_OPEN_TO_0945_RETURN; e['SYMBOL_0945_RETURN_MINUS_SOXX']=e.OPEN_TO_0945_RETURN-e.SOXX_OPEN_TO_0945_RETURN
 return e,use_volume,volume_reason
def folds(dates):
 b=np.array_split(np.asarray(sorted(set(dates))),6); return [{'fold_id':i+1,'train_dates':list(np.concatenate(b[:i+1])),'test_dates':list(b[i+1])} for i in range(5)]
def make_model(name,features):
 pre=ColumnTransformer([('numeric',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),features),('symbol',OneHotEncoder(handle_unknown='ignore'),['symbol'])]); est=LogisticRegression(**MODEL_SPECS[name]) if name=='LOGISTIC_REGRESSION' else RandomForestClassifier(**MODEL_SPECS[name]); return Pipeline([('preprocess',pre),('model',est)])
def lift(y,p):
 prev=float(np.mean(y)) if len(y) else None; return num(average_precision_score(y,p)/prev) if prev else None
def classify(x,fr,total):
 y=x.TP_BEFORE_SL_FROM_0945.to_numpy();p=x.prediction.to_numpy();prev=num(y.mean());k=max(1,math.ceil(len(x)*.1));top=x.sort_values(['prediction','symbol','date'],ascending=[False,True,True]).head(k); fl=[z['pr_auc_lift'] for z in fr if z['pr_auc_lift'] is not None]
 return {'event_count':len(x),'research_coverage_ratio':num(len(x)/total),'target_prevalence':prev,'roc_auc':num(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,'pr_auc':num(average_precision_score(y,p)) if prev else None,'pr_auc_lift':lift(y,p),'brier_score':num(brier_score_loss(y,p)),'log_loss':num(log_loss(y,p,labels=[0,1])),'top_decile_tp_before_sl_rate':num(top.TP_BEFORE_SL_FROM_0945.mean()),'top_decile_tp_before_sl_lift':num(top.TP_BEFORE_SL_FROM_0945.mean()/prev) if prev else None,'positive_fold_lift_ratio':num(np.mean([z>1 for z in fl])) if fl else None,'median_fold_pr_auc_lift':num(np.median(fl)) if fl else None,'worst_fold_pr_auc_lift':num(min(fl)) if fl else None}
def top1(x,research_dates):
 z=x.sort_values(['date','prediction','symbol'],ascending=[True,False,True]).groupby('date',as_index=False).head(1).copy(); z['net_return']=z.strategy_gross_return-COST; z['month']=z.date.str[:7]; z['equity']=(1+z.net_return).cumprod(); z['drawdown']=z.equity/z.equity.cummax()-1; g=z.net_return.clip(lower=0); tot=g.sum(); byf=[v.net_return.mean() for _,v in z.groupby('fold_id')]; bym=[v.net_return.mean() for _,v in z.groupby('month')]
 d={'daily_top1_trade_count':len(z),'daily_top1_date_coverage_ratio':num(len(z)/research_dates),'daily_top1_mean_gross_return':num(z.strategy_gross_return.mean()),'daily_top1_mean_net_return':num(z.net_return.mean()),'daily_top1_median_net_return':num(z.net_return.median()),'daily_top1_cumulative_net_return':num(z.equity.iloc[-1]-1),'daily_top1_positive_trade_ratio':num((z.net_return>0).mean()),'daily_top1_positive_month_ratio':num(np.mean([v>0 for v in bym])),'daily_top1_positive_fold_ratio':num(np.mean([v>0 for v in byf])),'daily_top1_max_drawdown':num(z.drawdown.min()),'daily_top1_top5_date_profit_concentration':num(g.nlargest(5).sum()/tot) if tot>0 else None,'daily_top1_top10_trade_profit_concentration':num(g.nlargest(10).sum()/tot) if tot>0 else None,'daily_top1_single_symbol_max_selection_ratio':num(z.symbol.value_counts().max()/len(z))}
 for o in ['TP_FIRST','SL_FIRST','SAME_MINUTE_BOTH','NEITHER']: d[f'daily_top1_{o.lower()}_count']=int((z.path_outcome==o).sum()); d[f'daily_top1_{o.lower()}_rate']=num((z.path_outcome==o).mean())
 return z,d
def evaluate(events,features,name,structure,fs):
 parts=[]; fr=[]; fits=0
 for f in fs:
  tr=events[events.date.isin(f['train_dates'])];te=events[events.date.isin(f['test_dates'])];valid=len(tr)>0 and len(te)>0 and tr.date.max()<te.date.min(); p=None
  if valid:
   p=make_model(name,features).fit(tr[features+['symbol']],tr.TP_BEFORE_SL_FROM_0945).predict_proba(te[features+['symbol']])[:,1];fits+=1;q=te.copy();q['prediction']=p;q['fold_id']=f['fold_id'];parts.append(q)
  fr.append({'feature_structure':structure,'model':name,'fold_id':f['fold_id'],'train_start_date':min(f['train_dates']),'train_end_date':max(f['train_dates']),'test_start_date':min(f['test_dates']),'test_end_date':max(f['test_dates']),'train_event_count':len(tr),'test_event_count':len(te),'pr_auc_lift':lift(te.TP_BEFORE_SL_FROM_0945,p) if valid else None,'valid':valid,'time_order_valid':max(f['train_dates'])<min(f['test_dates'])})
 x=pd.concat(parts,ignore_index=True); c=classify(x,fr,len(events));c.update({'feature_structure':structure,'model':name,'valid_fold_count':sum(z['valid'] for z in fr),'invalid_fold_count':sum(not z['valid'] for z in fr)});t,tm=top1(x,events.date.nunique());c.update(tm);return c,fr,t,fits
def improvement(base,conf): return {'confirmation_pr_auc_lift_improvement':num(conf['pr_auc_lift']-base['pr_auc_lift']) if conf['pr_auc_lift'] is not None and base['pr_auc_lift'] is not None else None,'confirmation_daily_mean_net_return_improvement':num(conf['daily_top1_mean_net_return']-base['daily_top1_mean_net_return']),'confirmation_sl_first_rate_improvement':num(base['daily_top1_sl_first_rate']-conf['daily_top1_sl_first_rate']),'confirmation_max_drawdown_improvement':num(conf['daily_top1_max_drawdown']-base['daily_top1_max_drawdown'])}
def passes(c,inc):
 return all([c['research_coverage_ratio']>=.80,c['valid_fold_count']==5,c['pr_auc_lift'] is not None and c['pr_auc_lift']>=1.2,c['top_decile_tp_before_sl_lift'] is not None and c['top_decile_tp_before_sl_lift']>=1.5,c['positive_fold_lift_ratio'] is not None and c['positive_fold_lift_ratio']>=.6,c['median_fold_pr_auc_lift'] is not None and c['median_fold_pr_auc_lift']>1,c['daily_top1_trade_count']>=1000,c['daily_top1_date_coverage_ratio']>=.8,c['daily_top1_mean_net_return']>0,c['daily_top1_median_net_return']>=0,c['daily_top1_positive_month_ratio']>=.55,c['daily_top1_positive_fold_ratio']>=.6,c['daily_top1_tp_first_rate']>c['daily_top1_sl_first_rate'],c['daily_top1_top5_date_profit_concentration'] is not None and c['daily_top1_top5_date_profit_concentration']<.6,c['daily_top1_single_symbol_max_selection_ratio']<.6,*[v is not None and v>0 for v in inc.values()]])
def run(results_root=LEGACY_RESULTS_ROOT):
 contract=json.loads(CONTRACT.read_text(encoding='utf-8'))
 if contract.get('usable_features')!=PREMARKET_FEATURES or len(PREMARKET_FEATURES)!=22: raise RuntimeError('FEATURE_CONTRACT_MISMATCH')
 e,has_volume,volume_reason=build_events(); usable_confirmation=[x for x in CONFIRMATION_FEATURES if x not in VOLUME_CONFIRMATION_FEATURES or has_volume]; confirmation_features=PREMARKET_FEATURES+usable_confirmation
 if e.empty: raise RuntimeError('NO_RESEARCH_EVENTS')
 fs=folds(e.date); rows=[]; foldrows=[]; trades=[];fits=0
 for structure,features in [('PREMARKET_ONLY',PREMARKET_FEATURES),('PREMARKET_PLUS_0945_CONFIRMATION',confirmation_features)]:
  for name in MODEL_SPECS:
   c,f,t,n=evaluate(e,features,name,structure,fs);rows.append(c);foldrows+=f;trades.append(t.assign(feature_structure=structure,model=name));fits+=n
 lookup={(r['feature_structure'],r['model']):r for r in rows}; symbolrows=[]
 for structure in ['PREMARKET_ONLY','PREMARKET_PLUS_0945_CONFIRMATION']:
  for name in MODEL_SPECS:
   t=[z for z in trades if z.feature_structure.iloc[0]==structure and z.model.iloc[0]==name][0]
   for sym in SYMS:
    z=t[t.symbol==sym];symbolrows.append({'feature_structure':structure,'model':name,'symbol':sym,'selection_count':len(z),'selection_net_return':num(z.net_return.sum()),'selection_mean_net_return':num(z.net_return.mean()) if len(z) else None})
 for name in MODEL_SPECS:
  base=lookup[('PREMARKET_ONLY',name)];conf=lookup[('PREMARKET_PLUS_0945_CONFIRMATION',name)];inc=improvement(base,conf);conf.update(inc);conf['confirmation_feature_incremental_value']=sum(v is not None and v>0 for v in inc.values())>=3;conf['candidate_pass']=passes(conf,inc);base['candidate_pass']=False
 outcomes=[]
 for sym in ['ALL',*SYMS]:
  a=e if sym=='ALL' else e[e.symbol==sym]
  for o in ['TP_FIRST','SL_FIRST','NEITHER','SAME_MINUTE_BOTH']:outcomes.append({'symbol':sym,'path_outcome':o,'count':int((a.path_outcome==o).sum()),'rate':num((a.path_outcome==o).mean())})
 confs=[r for r in rows if r['feature_structure']=='PREMARKET_PLUS_0945_CONFIRMATION'];bases=[r for r in rows if r['feature_structure']=='PREMARKET_ONLY'];bestconf=sorted(confs,key=lambda x:(x['pr_auc_lift'] is not None,x['pr_auc_lift'] or -1),reverse=True)[0];bestbase=sorted(bases,key=lambda x:(x['pr_auc_lift'] is not None,x['pr_auc_lift'] or -1),reverse=True)[0]; winners=[x for x in confs if x['candidate_pass']];rank={'LOGISTIC_REGRESSION':0,'CONSTRAINED_RANDOM_FOREST':1};selected=sorted(winners,key=lambda x:(-x['daily_top1_mean_net_return'],-x['pr_auc_lift'],rank[x['model']]))[0] if winners else None
 s={'research_id':OUT_NAME,'final_status':'PASS','final_decision':'0945_CONFIRMATION_PATH_RESEARCH_CANDIDATE_FOUND' if selected else 'FAST3_0945_RESEARCH_STOPPED_NO_EXECUTABLE_EDGE','next_freeze_stage_allowed':bool(selected),'fast3_0945_research_stopped':not bool(selected),'selected_model':selected['model'] if selected else None,'research_event_count':len(e),'research_date_count':e.date.nunique(),'former_development_role':'RESEARCH_DATA','former_validation_role':'RESEARCH_DATA','former_validation_still_independent':False,'confirmation_remains_sealed':True,'confirmation_row_read_count':0,'premarket_feature_count':22,'confirmation_feature_count':15,'usable_confirmation_feature_count':len(usable_confirmation),'confirmation_volume_feature_exclusion_reason':volume_reason,'feature_cutoff_time_et':'09:45:00','post_entry_feature_row_read_count':0,'data_leakage_detected':False,'entry_price_contract':'09:45_MINUTE_BAR_OPEN','take_profit_threshold':TP,'stop_loss_threshold':SL,'candidate_model_count':2,'hyperparameter_search_count':0,'valid_fold_count':bestconf['valid_fold_count'],'invalid_fold_count':bestconf['invalid_fold_count'],'time_order_violation_count':sum(not z['time_order_valid'] for z in foldrows),'research_fit_call_count':fits,'final_frozen_model_output_count':0,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,'live_trading_allowed':False,'order_output_count':0,'position_output_count':0,'broker_connection_count':0,'TP_FIRST_count':int((e.path_outcome=='TP_FIRST').sum()),'TP_FIRST_rate':num((e.path_outcome=='TP_FIRST').mean()),'SL_FIRST_count':int((e.path_outcome=='SL_FIRST').sum()),'SL_FIRST_rate':num((e.path_outcome=='SL_FIRST').mean()),'NEITHER_count':int((e.path_outcome=='NEITHER').sum()),'NEITHER_rate':num((e.path_outcome=='NEITHER').mean()),'SAME_MINUTE_BOTH_count':int((e.path_outcome=='SAME_MINUTE_BOTH').sum()),'SAME_MINUTE_BOTH_rate':num((e.path_outcome=='SAME_MINUTE_BOTH').mean()),'target_prevalence':num(e.TP_BEFORE_SL_FROM_0945.mean()),'premarket_only_best_model':bestbase['model'],'premarket_only_pr_auc_lift':bestbase['pr_auc_lift'],'premarket_only_daily_mean_net_return':bestbase['daily_top1_mean_net_return'],'premarket_only_daily_sl_first_rate':bestbase['daily_top1_sl_first_rate'],'confirmation_best_model':bestconf['model'],'confirmation_pr_auc_lift':bestconf['pr_auc_lift'],'confirmation_top_decile_lift':bestconf['top_decile_tp_before_sl_lift'],'confirmation_daily_top1_mean_net_return':bestconf['daily_top1_mean_net_return'],'confirmation_daily_top1_median_net_return':bestconf['daily_top1_median_net_return'],'confirmation_daily_top1_tp_first_rate':bestconf['daily_top1_tp_first_rate'],'confirmation_daily_top1_sl_first_rate':bestconf['daily_top1_sl_first_rate'],'confirmation_daily_top1_positive_month_ratio':bestconf['daily_top1_positive_month_ratio'],'confirmation_daily_top1_positive_fold_ratio':bestconf['daily_top1_positive_fold_ratio'],'confirmation_daily_top1_max_drawdown':bestconf['daily_top1_max_drawdown'],**improvement(lookup[('PREMARKET_ONLY',bestconf['model'])],bestconf),'confirmation_feature_incremental_value':bestconf['confirmation_feature_incremental_value']}
 out=Path(results_root)/OUT_NAME;out.parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.076a_',dir=out.parent))
 try:
  (stage/'v22_076a_summary.json').write_text(dump(s),encoding='utf-8');(stage/'feature_contract.json').write_text(dump({'premarket_contract_path':str(CONTRACT),'premarket_contract_sha256':hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),'premarket_features':PREMARKET_FEATURES,'confirmation_features':CONFIRMATION_FEATURES,'usable_confirmation_features':usable_confirmation,'confirmation_volume_feature_exclusion_reason':volume_reason,'feature_cutoff_time_et':'09:45:00','post_entry_feature_row_read_count':0,'entry_price_contract':'09:45_MINUTE_BAR_OPEN','target':'TP_BEFORE_SL_FROM_0945','classes':['TP_FIRST','SL_FIRST','NEITHER','SAME_MINUTE_BOTH'],'same_minute_both_treatment':'SL_FIRST','take_profit_threshold':TP,'stop_loss_threshold':SL,'confirmation_remains_sealed':True,'confirmation_row_read_count':0}),encoding='utf-8');pd.DataFrame(rows).to_csv(stage/'classification_scorecard.csv',index=False);pd.DataFrame(foldrows).to_csv(stage/'fold_scorecard.csv',index=False);pd.concat(trades,ignore_index=True).to_csv(stage/'daily_top1_trades.csv',index=False);pd.DataFrame(symbolrows).to_csv(stage/'symbol_scorecard.csv',index=False);pd.DataFrame(outcomes).to_csv(stage/'outcome_distribution.csv',index=False)
  if out.exists():shutil.rmtree(out)
  os.replace(stage,out);return s,out
 except Exception:shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');a.add_argument('--results-root',default=str(LEGACY_RESULTS_ROOT));z=a.parse_args()
 if z.execute:
  s,o=run(Path(z.results_root));print(json.dumps({**s,'summary_path':str(o/'v22_076a_summary.json')},ensure_ascii=False,sort_keys=True))
