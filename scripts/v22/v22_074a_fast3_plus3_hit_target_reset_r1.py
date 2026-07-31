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

REPO=Path(__file__).resolve().parents[2]
OUT_NAME='V22.074A_FAST3_PLUS3_HIT_TARGET_RESET_R1'
DATA_ROOT=Path(r'D:/us-tech-quant-data/fast3/moomoo_24h_1m')
V073_CONTRACT=REPO/'.local_results/v22/V22.073A_FAST3_PIT_FEATURE_EXPANSION_RESEARCH_R1/feature_contract.json'
SYMS=['QQQ','SOXX','TQQQ','SQQQ','SOXL','SOXS']; COST=.001
FEATURES=['PREMARKET_CUM_RETURN','MAX_DRAWDOWN','REALIZED_VOL','PREMARKET_LAST_15M_RETURN','PREMARKET_LAST_30M_RETURN','PREMARKET_LAST_60M_RETURN','PREMARKET_HIGH_LOW_RANGE','PREMARKET_CLOSE_LOCATION_VALUE','PREMARKET_RETURN_FROM_LOW','PREMARKET_RETURN_FROM_HIGH','PREMARKET_TREND_SLOPE','PREMARKET_TREND_R2','PREMARKET_POSITIVE_MINUTE_RATIO','PREMARKET_MAX_15M_UP_MOVE','PREMARKET_MAX_15M_DOWN_MOVE','QQQ_PREMARKET_RETURN','SOXX_PREMARKET_RETURN','QQQ_MINUS_SOXX_PREMARKET_RETURN','SYMBOL_MINUS_QQQ_PREMARKET_RETURN','SYMBOL_MINUS_SOXX_PREMARKET_RETURN','PREMARKET_VOLUME_SHARE_LAST_30M','PREMARKET_VOLUME_CONCENTRATION']
MODEL_SPECS={'LOGISTIC_REGRESSION':{'solver':'lbfgs','C':1.0,'max_iter':2000,'class_weight':'balanced','random_state':20260731},'CONSTRAINED_RANDOM_FOREST':{'n_estimators':300,'max_depth':4,'min_samples_leaf':80,'max_features':.75,'class_weight':'balanced','random_state':20260731,'n_jobs':-1}}

def num(x): return float(x) if x is not None and np.isfinite(x) else None
def dump(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n'
def research_months():
 return [str(x)[:7] for x in pd.period_range('2018-07','2023-03',freq='M')]+[str(x)[:7] for x in pd.period_range('2023-05','2024-11',freq='M')]
def pfeat(c):
 r=np.diff(np.log(c)); x=np.arange(len(c)); slope=np.polyfit(x,np.log(c),1)[0] if len(c)>1 else np.nan; fit=np.polyval(np.polyfit(x,np.log(c),1),x) if len(c)>1 else np.array([np.nan]); ss=np.sum((np.log(c)-np.log(c).mean())**2); r2=1-np.sum((np.log(c)-fit)**2)/ss if ss else 0.; roll=np.array([c[i+15]/c[i]-1 for i in range(len(c)-15)]); hi,lo=c.max(),c.min(); rng=hi-lo
 return {'PREMARKET_CUM_RETURN':c[-1]/c[0]-1,'MAX_DRAWDOWN':np.min(c/np.maximum.accumulate(c)-1),'REALIZED_VOL':np.std(r,ddof=0),'PREMARKET_LAST_15M_RETURN':c[-1]/c[-16]-1 if len(c)>=16 else np.nan,'PREMARKET_LAST_30M_RETURN':c[-1]/c[-31]-1 if len(c)>=31 else np.nan,'PREMARKET_LAST_60M_RETURN':c[-1]/c[-61]-1 if len(c)>=61 else np.nan,'PREMARKET_HIGH_LOW_RANGE':rng/c[0],'PREMARKET_CLOSE_LOCATION_VALUE':(c[-1]-lo)/rng if rng else .5,'PREMARKET_RETURN_FROM_LOW':c[-1]/lo-1,'PREMARKET_RETURN_FROM_HIGH':c[-1]/hi-1,'PREMARKET_TREND_SLOPE':slope,'PREMARKET_TREND_R2':r2,'PREMARKET_POSITIVE_MINUTE_RATIO':np.mean(r>0) if len(r) else np.nan,'PREMARKET_MAX_15M_UP_MOVE':roll.max() if len(roll) else np.nan,'PREMARKET_MAX_15M_DOWN_MOVE':roll.min() if len(roll) else np.nan}
def vfeat(v):
 total=v.sum(); return {'PREMARKET_VOLUME_SHARE_LAST_30M':v[-30:].sum()/total if total>0 else np.nan,'PREMARKET_VOLUME_CONCENTRATION':np.sum((v/total)**2) if total>0 else np.nan}
def simulate(rth):
 entry=float(rth.iloc[0].open); take=entry*1.03; stop=entry*.994
 for _,bar in rth.iterrows():
  high,low=float(bar.high),float(bar.low)
  if low<=stop: return (stop/entry-1,'STOP_LOSS') # includes same-minute dual trigger: stop first
  if high>=take: return (take/entry-1,'TAKE_PROFIT')
 return (float(rth.iloc[-1].close)/entry-1,'CLOSE_EXIT')
def build_events():
 rows=[]; months=research_months()
 for month in months:
  for sym in SYMS:
   path=DATA_ROOT/'canonical'/f'symbol={sym}'/f'year={month[:4]}'/f'month={month[5:]}'/'data.parquet'
   if not path.is_file(): raise RuntimeError(f'RESEARCH_PARTITION_MISSING:{path}')
   need=['timestamp_et','open','high','low','close','volume']; schema=pq.ParquetFile(path).schema_arrow.names
   if any(c not in schema for c in need): raise RuntimeError(f'FEATURE_CONTRACT_INPUT_SCHEMA_FAILURE:{path}')
   f=pq.read_table(path,columns=need).to_pandas(); t=pd.to_datetime(f.timestamp_et,utc=True).dt.tz_convert('America/New_York'); f=f.assign(timestamp=t).dropna(subset=need); f['date']=f.timestamp.dt.date.astype(str)
   for date,day in f.groupby('date',sort=True):
    day=day.sort_values('timestamp'); tm=day.timestamp.dt.time; pre=day[(tm>=pd.Timestamp('04:00').time())&(tm<=pd.Timestamp('09:25').time())]; rth=day[(tm>=pd.Timestamp('09:30').time())&(tm<=pd.Timestamp('16:00').time())]
    if pre.timestamp.dt.floor('min').nunique()/326<.80 or rth.empty or not np.isfinite(pre.volume.astype(float)).all() or (pre.volume.astype(float)<0).any(): continue
    gross,reason=simulate(rth); entry=float(rth.iloc[0].open); row={'date':date,'symbol':sym,'PLUS_3PCT_HIT_BY_CLOSE':int((rth.high.astype(float)>=entry*1.03).any()),'strategy_gross_return':gross,'strategy_exit_reason':reason,**pfeat(pre.close.astype(float).to_numpy()),**vfeat(pre.volume.astype(float).to_numpy())}; rows.append(row)
 e=pd.DataFrame(rows).sort_values(['date','symbol']).reset_index(drop=True); ctx=e.pivot(index='date',columns='symbol',values='PREMARKET_CUM_RETURN')
 e['QQQ_PREMARKET_RETURN']=e.date.map(ctx['QQQ']); e['SOXX_PREMARKET_RETURN']=e.date.map(ctx['SOXX']); e['QQQ_MINUS_SOXX_PREMARKET_RETURN']=e.QQQ_PREMARKET_RETURN-e.SOXX_PREMARKET_RETURN; e['SYMBOL_MINUS_QQQ_PREMARKET_RETURN']=e.PREMARKET_CUM_RETURN-e.QQQ_PREMARKET_RETURN; e['SYMBOL_MINUS_SOXX_PREMARKET_RETURN']=e.PREMARKET_CUM_RETURN-e.SOXX_PREMARKET_RETURN
 return e
def folds(dates):
 b=np.array_split(np.asarray(sorted(set(dates))),6); return [{'fold_id':i+1,'train_dates':list(np.concatenate(b[:i+1])),'test_dates':list(b[i+1])} for i in range(5)]
def make_model(name):
 pre=ColumnTransformer([('numeric',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),FEATURES),('symbol',OneHotEncoder(handle_unknown='ignore'),['symbol'])])
 est=LogisticRegression(**MODEL_SPECS[name]) if name=='LOGISTIC_REGRESSION' else RandomForestClassifier(**MODEL_SPECS[name])
 return Pipeline([('preprocess',pre),('model',est)])
def lift(y,p):
 prevalence=float(np.mean(y)) if len(y) else None
 if prevalence in (None,0): return None
 return num(average_precision_score(y,p)/prevalence)
def calibration(y,p):
 q=pd.DataFrame({'target':y,'prediction':p}); q['decile']=pd.qcut(q.prediction.rank(method='first'),10,labels=False,duplicates='drop')+1
 return [{'decile':int(k),'event_count':len(g),'mean_prediction':num(g.prediction.mean()),'observed_hit_rate':num(g.target.mean())} for k,g in q.groupby('decile')]
def classify(x,foldrows,total):
 y=x.PLUS_3PCT_HIT_BY_CLOSE.to_numpy(); p=x.prediction.to_numpy(); prev=num(y.mean()); k=max(1,math.ceil(len(x)*.1)); top=x.sort_values(['prediction','symbol','date'],ascending=[False,True,True]).head(k); fl=[z['pr_auc_lift'] for z in foldrows if z['pr_auc_lift'] is not None]
 return {'event_count':len(x),'research_coverage_ratio':num(len(x)/total),'target_prevalence':prev,'roc_auc':num(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,'roc_auc_reason':None if len(np.unique(y))==2 else 'SINGLE_CLASS','pr_auc':num(average_precision_score(y,p)) if prev else None,'pr_auc_lift':lift(y,p),'brier_score':num(brier_score_loss(y,p)),'log_loss':num(log_loss(y,p,labels=[0,1])),'top_decile_hit_rate':num(top.PLUS_3PCT_HIT_BY_CLOSE.mean()),'top_decile_hit_rate_lift':num(top.PLUS_3PCT_HIT_BY_CLOSE.mean()/prev) if prev else None,'positive_fold_lift_ratio':num(np.mean([z>1 for z in fl])) if fl else None,'median_fold_pr_auc_lift':num(np.median(fl)) if fl else None,'worst_fold_pr_auc_lift':num(min(fl)) if fl else None,'calibration_deciles':calibration(y,p)}
def top1(x):
 z=x.sort_values(['date','prediction','symbol'],ascending=[True,False,True]).groupby('date',as_index=False).head(1).copy(); z['net_return']=z.strategy_gross_return-COST; z['month']=z.date.str[:7]; z['equity']=(1+z.net_return).cumprod(); z['drawdown']=z.equity/z.equity.cummax()-1
 gains=z.net_return.clip(lower=0); total=gains.sum(); byfold=[g.net_return.mean() for _,g in z.groupby('fold_id')]; bymonth=[g.net_return.mean() for _,g in z.groupby('month')]
 return z,{'daily_top1_trade_count':len(z),'daily_top1_date_coverage_ratio':None,'daily_top1_take_profit_hit_count':int((z.strategy_exit_reason=='TAKE_PROFIT').sum()),'daily_top1_take_profit_hit_rate':num((z.strategy_exit_reason=='TAKE_PROFIT').mean()),'daily_top1_stop_loss_hit_count':int((z.strategy_exit_reason=='STOP_LOSS').sum()),'daily_top1_stop_loss_hit_rate':num((z.strategy_exit_reason=='STOP_LOSS').mean()),'daily_top1_close_exit_count':int((z.strategy_exit_reason=='CLOSE_EXIT').sum()),'daily_top1_close_exit_rate':num((z.strategy_exit_reason=='CLOSE_EXIT').mean()),'daily_top1_mean_gross_return':num(z.strategy_gross_return.mean()),'daily_top1_mean_net_return':num(z.net_return.mean()),'daily_top1_median_net_return':num(z.net_return.median()),'daily_top1_cumulative_net_return':num(z.equity.iloc[-1]-1) if len(z) else None,'daily_top1_positive_trade_ratio':num((z.net_return>0).mean()),'daily_top1_positive_month_ratio':num(np.mean([v>0 for v in bymonth])) if bymonth else None,'daily_top1_positive_fold_ratio':num(np.mean([v>0 for v in byfold])) if byfold else None,'daily_top1_max_drawdown':num(z.drawdown.min()) if len(z) else None,'daily_top1_top5_date_profit_concentration':num(gains.nlargest(5).sum()/total) if total>0 else None,'daily_top1_top10_trade_profit_concentration':num(gains.nlargest(10).sum()/total) if total>0 else None,'daily_top1_single_symbol_max_selection_ratio':num(z.symbol.value_counts().max()/len(z)) if len(z) else None}
def passes(c,t):
 return all([c['research_coverage_ratio']>=.80,c['valid_fold_count']==5,c['pr_auc_lift'] is not None and c['pr_auc_lift']>=1.20,c['top_decile_hit_rate_lift'] is not None and c['top_decile_hit_rate_lift']>=1.50,c['positive_fold_lift_ratio'] is not None and c['positive_fold_lift_ratio']>=.60,c['median_fold_pr_auc_lift'] is not None and c['median_fold_pr_auc_lift']>1,t['daily_top1_trade_count']>=1000,t['daily_top1_date_coverage_ratio']>=.80,t['daily_top1_mean_net_return']>0,t['daily_top1_median_net_return']>=0,t['daily_top1_positive_month_ratio']>=.55,t['daily_top1_positive_fold_ratio']>=.60,t['daily_top1_take_profit_hit_rate']>t['daily_top1_stop_loss_hit_rate'],t['daily_top1_top5_date_profit_concentration'] is not None and t['daily_top1_top5_date_profit_concentration']<.60,t['daily_top1_single_symbol_max_selection_ratio']<.60])
def run(results_root=REPO/'.local_results'):
 contract=json.loads(V073_CONTRACT.read_text(encoding='utf-8'))
 if contract.get('usable_features')!=FEATURES or len(FEATURES)!=22: raise RuntimeError('V22_073A_22_FEATURE_CONTRACT_MISMATCH')
 events=build_events()
 if len(events)!=9497: raise RuntimeError(f'RESEARCH_EVENT_COUNT_MISMATCH:{len(events)}')
 fs=folds(events.date); outputs=[]; foldrows=[]; symbols=[]; models=[]; fits=0; research_dates=events.date.nunique()
 for name in MODEL_SPECS:
  parts=[]; model_folds=[]
  for f in fs:
   tr=events[events.date.isin(f['train_dates'])]; te=events[events.date.isin(f['test_dates'])]; valid=len(tr)>0 and len(te)>0 and tr.date.max()<te.date.min()
   if valid:
    m=make_model(name).fit(tr[FEATURES+['symbol']],tr.PLUS_3PCT_HIT_BY_CLOSE); p=m.predict_proba(te[FEATURES+['symbol']])[:,1]; q=te.copy();q['prediction']=p;q['fold_id']=f['fold_id'];parts.append(q); fits+=1; fl=lift(te.PLUS_3PCT_HIT_BY_CLOSE,p)
   else: fl=None
   row={'model':name,'fold_id':f['fold_id'],'train_start_date':min(f['train_dates']),'train_end_date':max(f['train_dates']),'test_start_date':min(f['test_dates']),'test_end_date':max(f['test_dates']),'train_event_count':len(tr),'test_event_count':len(te),'pr_auc_lift':fl,'valid':valid,'time_order_valid':max(f['train_dates'])<min(f['test_dates'])};foldrows.append(row);model_folds.append(row)
  x=pd.concat(parts,ignore_index=True); c=classify(x,model_folds,len(events)); c.update({'model':name,'valid_fold_count':sum(r['valid'] for r in model_folds),'invalid_fold_count':sum(not r['valid'] for r in model_folds)}); trades,t=top1(x);t['daily_top1_date_coverage_ratio']=num(len(trades)/research_dates); c.update(t);c['candidate_pass']=passes(c,t);models.append(c);outputs.append(trades.assign(model=name));
  for sym in SYMS: symbols.append({'model':name,'symbol':sym,'event_count':int((x.symbol==sym).sum()),'target_prevalence':num(x.loc[x.symbol==sym,'PLUS_3PCT_HIT_BY_CLOSE'].mean()),'selection_count':int((trades.symbol==sym).sum()),'selection_ratio':num((trades.symbol==sym).mean())})
 winners=[x for x in models if x['candidate_pass']]; rank={'LOGISTIC_REGRESSION':0,'CONSTRAINED_RANDOM_FOREST':1}; best=sorted(models,key=lambda x:(x['pr_auc_lift'] is not None,x['pr_auc_lift'] or -1),reverse=True)[0]; selected=sorted(winners,key=lambda x:(-x['daily_top1_mean_net_return'],-x['pr_auc_lift'],-x['daily_top1_take_profit_hit_rate'],x['daily_top1_max_drawdown'],rank[x['model']]))[0] if winners else None
 s={'final_status':'PASS','final_decision':'PLUS3_HIT_RESEARCH_CANDIDATE_FOUND' if selected else 'FAST3_PREMARKET_RESEARCH_STOPPED_NO_PLUS3_PREDICTIVE_EDGE','next_freeze_stage_allowed':bool(selected),'fast3_premarket_research_stopped':not bool(selected),'selected_model':selected['model'] if selected else None,'research_event_count':len(events),'research_date_count':research_dates,'former_development_role':'RESEARCH_DATA','former_validation_role':'RESEARCH_DATA','former_validation_still_independent':False,'confirmation_remains_sealed':True,'confirmation_row_read_count':0,'feature_contract_verified':True,'feature_count':22,'candidate_model_count':2,'hyperparameter_search_count':0,'valid_fold_count':sum(x['valid'] for x in foldrows if x['model']=='LOGISTIC_REGRESSION'),'invalid_fold_count':sum(not x['valid'] for x in foldrows if x['model']=='LOGISTIC_REGRESSION'),'time_order_violation_count':sum(not x['time_order_valid'] for x in foldrows),'data_leakage_detected':False,'research_fit_call_count':fits,'final_frozen_model_output_count':0,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,'live_trading_allowed':False,'order_output_count':0,'position_output_count':0,'broker_connection_count':0,'best_model':best['model'],'best_pr_auc_lift':best['pr_auc_lift'],'best_top_decile_hit_rate_lift':best['top_decile_hit_rate_lift'],**{f'{x["model"].lower()}_{k}':x[k] for x in models for k in ('target_prevalence','roc_auc','pr_auc','pr_auc_lift','top_decile_hit_rate_lift','daily_top1_mean_net_return')},**{f'daily_top1_{k[11:]}':best[k] for k in best if k.startswith('daily_top1_')}}
 out=Path(results_root)/'v22'/OUT_NAME; out.parent.mkdir(parents=True,exist_ok=True); stage=Path(tempfile.mkdtemp(prefix='.074a_',dir=out.parent))
 try:
  (stage/'v22_074a_summary.json').write_text(dump(s),encoding='utf-8'); (stage/'target_contract.json').write_text(dump({'target':'PLUS_3PCT_HIT_BY_CLOSE','entry':'FIRST_RTH_MINUTE_OPEN','observation_window':'09:30-16:00 America/New_York','target_uses':'MINUTE_HIGH','take_profit':.03,'stop_loss':-.006,'same_minute_dual_trigger':'STOP_LOSS_FIRST','cost_bps':10,'feature_contract_path':str(V073_CONTRACT),'feature_contract_sha256':hashlib.sha256(V073_CONTRACT.read_bytes()).hexdigest(),'features':FEATURES,'confirmation_remains_sealed':True,'confirmation_row_read_count':0}),encoding='utf-8');pd.DataFrame([{k:v for k,v in x.items() if k!='calibration_deciles'} for x in models]).to_csv(stage/'classification_scorecard.csv',index=False);pd.DataFrame([{'model':x['model'],**d} for x in models for d in x['calibration_deciles']]).to_csv(stage/'calibration_deciles.csv',index=False);pd.DataFrame(foldrows).to_csv(stage/'fold_scorecard.csv',index=False);pd.concat(outputs,ignore_index=True).to_csv(stage/'daily_top1_trades.csv',index=False);pd.DataFrame(symbols).to_csv(stage/'symbol_scorecard.csv',index=False)
  if out.exists(): shutil.rmtree(out)
  os.replace(stage,out); return s,out
 except Exception: shutil.rmtree(stage,ignore_errors=True); raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');a.add_argument('--results-root',default=str(REPO/'.local_results'));z=a.parse_args()
 if z.execute:
  s,o=run(Path(z.results_root)); print(json.dumps({**s,'summary_path':str(o/'v22_074a_summary.json')},ensure_ascii=False,sort_keys=True))
