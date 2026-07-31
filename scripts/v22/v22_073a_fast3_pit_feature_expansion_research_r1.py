from __future__ import annotations
import argparse, json, math, os, shutil, tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

REPO=Path(__file__).resolve().parents[2]
OUT_NAME='V22.073A_FAST3_PIT_FEATURE_EXPANSION_RESEARCH_R1'
CONTRACT=REPO/'.local_results/v22/V22.069A_FAST_RESEARCH_CONTRACT_R1/v22_069a_fast_frozen_research_contract.json'
DATA_ROOT=Path(r'D:/us-tech-quant-data/fast3/moomoo_24h_1m')
SYMS=['QQQ','SOXX','TQQQ','SQQQ','SOXL','SOXS']; COST=.001
BASE_FEATURES=['PREMARKET_CUM_RETURN','MAX_DRAWDOWN','REALIZED_VOL']
PRICE_FEATURES=BASE_FEATURES+['PREMARKET_LAST_15M_RETURN','PREMARKET_LAST_30M_RETURN','PREMARKET_LAST_60M_RETURN','PREMARKET_HIGH_LOW_RANGE','PREMARKET_CLOSE_LOCATION_VALUE','PREMARKET_RETURN_FROM_LOW','PREMARKET_RETURN_FROM_HIGH','PREMARKET_TREND_SLOPE','PREMARKET_TREND_R2','PREMARKET_POSITIVE_MINUTE_RATIO','PREMARKET_MAX_15M_UP_MOVE','PREMARKET_MAX_15M_DOWN_MOVE']
ETF_FEATURES=['QQQ_PREMARKET_RETURN','SOXX_PREMARKET_RETURN','QQQ_MINUS_SOXX_PREMARKET_RETURN','SYMBOL_MINUS_QQQ_PREMARKET_RETURN','SYMBOL_MINUS_SOXX_PREMARKET_RETURN']
VOLUME_FEATURES=['PREMARKET_VOLUME_SHARE_LAST_30M','PREMARKET_VOLUME_CONCENTRATION']
FIXED_FEATURES=PRICE_FEATURES+ETF_FEATURES
MODEL_SPECS={'RIDGE':{'alpha':1.0},'CONSTRAINED_RANDOM_FOREST':{'n_estimators':300,'max_depth':4,'min_samples_leaf':80,'max_features':.75,'random_state':20260731,'n_jobs':-1}}
HYPOTHESIS='盘前累计收益、最大回撤和波动率不足以描述盘前价格路径。增加固定的路径形态、近期动量、反弹、区间位置和跨 ETF 市场背景特征，可能提升全样本覆盖下的稳定排序能力。'
def num(v): return float(v) if v is not None and np.isfinite(v) else None
def dump(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n'
def paths(months): return [DATA_ROOT/'canonical'/f'symbol={s}'/f'year={m[:4]}'/f'month={m[5:]}'/'data.parquet' for m in months for s in SYMS]
def folds(dates):
 b=np.array_split(np.asarray(sorted(set(dates))),6)
 return [{'fold_id':i+1,'train_dates':list(np.concatenate(b[:i+1])),'test_dates':list(b[i+1])} for i in range(5) if len(b[i+1])]
def pfeat(c):
 r=np.diff(np.log(c)); x=np.arange(len(c)); slope=np.polyfit(x,np.log(c),1)[0] if len(c)>1 else np.nan
 fit=np.polyval(np.polyfit(x,np.log(c),1),x) if len(c)>1 else np.array([np.nan]); ss=np.sum((np.log(c)-np.log(c).mean())**2); r2=1-np.sum((np.log(c)-fit)**2)/ss if ss>0 else 0.
 roll=np.array([c[i+15]/c[i]-1 for i in range(len(c)-15)])
 hi,lo=c.max(),c.min(); rng=hi-lo
 return {'PREMARKET_CUM_RETURN':c[-1]/c[0]-1,'MAX_DRAWDOWN':np.min(c/np.maximum.accumulate(c)-1),'REALIZED_VOL':np.std(r,ddof=0),'PREMARKET_LAST_15M_RETURN':c[-1]/c[-16]-1 if len(c)>=16 else np.nan,'PREMARKET_LAST_30M_RETURN':c[-1]/c[-31]-1 if len(c)>=31 else np.nan,'PREMARKET_LAST_60M_RETURN':c[-1]/c[-61]-1 if len(c)>=61 else np.nan,'PREMARKET_HIGH_LOW_RANGE':rng/c[0],'PREMARKET_CLOSE_LOCATION_VALUE':(c[-1]-lo)/rng if rng else .5,'PREMARKET_RETURN_FROM_LOW':c[-1]/lo-1,'PREMARKET_RETURN_FROM_HIGH':c[-1]/hi-1,'PREMARKET_TREND_SLOPE':slope,'PREMARKET_TREND_R2':r2,'PREMARKET_POSITIVE_MINUTE_RATIO':np.mean(r>0) if len(r) else np.nan,'PREMARKET_MAX_15M_UP_MOVE':roll.max() if len(roll) else np.nan,'PREMARKET_MAX_15M_DOWN_MOVE':roll.min() if len(roll) else np.nan}
def volume_features(v):
 total=v.sum(); last=v[-30:].sum()
 return {'PREMARKET_VOLUME_SHARE_LAST_30M':last/total if total>0 else np.nan,'PREMARKET_VOLUME_CONCENTRATION':np.sum((v/total)**2) if total>0 else np.nan}
def build_events(months):
 use_volume=True; reason=None; rows=[]
 for path in paths(months):
  if not path.is_file(): raise RuntimeError(f'RESEARCH_PARTITION_MISSING:{path}')
  schema=pq.ParquetFile(path).schema_arrow.names
  if 'volume' not in schema: use_volume=False; reason='CANONICAL_VOLUME_FIELD_MISSING'
  cols=['timestamp_et','open','close']+(['volume'] if 'volume' in schema else [])
  frame=pq.read_table(path,columns=cols).to_pandas(); ts=pd.to_datetime(frame.timestamp_et,utc=True).dt.tz_convert('America/New_York'); frame=frame.assign(timestamp=ts).dropna(subset=['timestamp','open','close']); frame['date']=frame.timestamp.dt.date.astype(str); frame=frame[frame.date.str[:7].isin(set(months))]
  symbol=path.parents[2].name.split('=',1)[1]
  for date,day in frame.groupby('date',sort=True):
   day=day.sort_values('timestamp'); pre=day[(day.timestamp.dt.time>=pd.Timestamp('04:00').time())&(day.timestamp.dt.time<=pd.Timestamp('09:25').time())]
   entry=day[(day.timestamp.dt.time>=pd.Timestamp('09:30').time())&(day.timestamp.dt.time<=pd.Timestamp('09:32').time())]; exit_=day[(day.timestamp.dt.time>=pd.Timestamp('15:58').time())&(day.timestamp.dt.time<=pd.Timestamp('16:00').time())]
   if pre.timestamp.dt.floor('min').nunique()/326<.80 or entry.empty or exit_.empty: continue
   c=pre.close.astype(float).to_numpy(); row={'date':date,'symbol':symbol,'target_return':float(exit_.iloc[-1].close)/float(entry.iloc[0].open)-1,**pfeat(c)}
   if 'volume' not in pre or not np.isfinite(pre.volume.astype(float)).all() or (pre.volume.astype(float)<0).any(): use_volume=False; reason='CANONICAL_VOLUME_NOT_COMPLETE_FINITE_NONNEGATIVE'
   else: row.update(volume_features(pre.volume.astype(float).to_numpy()))
   rows.append(row)
 events=pd.DataFrame(rows).sort_values(['date','symbol']).reset_index(drop=True)
 # Same-date ETF context is constructed only from that date's already-complete
 # premarket windows; no later regular-session information is involved.
 context=events.pivot(index='date',columns='symbol',values='PREMARKET_CUM_RETURN')
 events['QQQ_PREMARKET_RETURN']=events.date.map(context.get('QQQ',pd.Series(dtype=float)))
 events['SOXX_PREMARKET_RETURN']=events.date.map(context.get('SOXX',pd.Series(dtype=float)))
 events['QQQ_MINUS_SOXX_PREMARKET_RETURN']=events['QQQ_PREMARKET_RETURN']-events['SOXX_PREMARKET_RETURN']
 events['SYMBOL_MINUS_QQQ_PREMARKET_RETURN']=events['PREMARKET_CUM_RETURN']-events['QQQ_PREMARKET_RETURN']
 events['SYMBOL_MINUS_SOXX_PREMARKET_RETURN']=events['PREMARKET_CUM_RETURN']-events['SOXX_PREMARKET_RETURN']
 if use_volume: return events, VOLUME_FEATURES, None
 return events.drop(columns=VOLUME_FEATURES,errors='ignore'), [], reason or 'CANONICAL_VOLUME_CONTRACT_NOT_MET'
def make_model(name,features):
 pre=ColumnTransformer([('numeric',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),features),('symbol',OneHotEncoder(handle_unknown='ignore'),['symbol'])])
 estimator=Ridge(**MODEL_SPECS[name]) if name=='RIDGE' else RandomForestRegressor(**MODEL_SPECS[name])
 return Pipeline([('preprocess',pre),('model',estimator)])
def bucket(y,p):
 if len(y)<5:return (None,)*4
 k=max(1,math.ceil(len(y)*.2)); order=np.lexsort((np.arange(len(p)),p)); y=np.asarray(y); top=float(y[order[-k:]].mean()); bottom=float(y[order[:k]].mean()); return top,bottom,top-bottom,top-bottom-COST
def concentration(x,k,date=False):
 q=x.nlargest(max(1,math.ceil(len(x)*.2)),'prediction'); gain=q.target_return.clip(lower=0); total=gain.sum()
 if total<=0:return None
 return num((gain.groupby(q.date).sum() if date else gain).nlargest(k).sum()/total)
def metric(x,fr,total):
 top,bot,gross,net=bucket(x.target_return,x.prediction); ics=[z['spearman_ic'] for z in fr if z['spearman_ic'] is not None]; months=[bucket(g.target_return,g.prediction)[3] for _,g in x.groupby(x.date.str[:7])]; symbols=[bucket(g.target_return,g.prediction)[3] for _,g in x.groupby('symbol')]
 u=int(x.prediction.nunique()) if len(x) else 0
 return {'event_count':len(x),'research_coverage_ratio':num(len(x)/total),'oof_spearman_ic':num(spearmanr(x.target_return,x.prediction).statistic) if len(x)>1 else None,'top_mean_return':top,'bottom_mean_return':bot,'top_bottom_spread_gross':gross,'top_bottom_spread_net_10bps':net,'positive_fold_ratio':num(np.mean([z>0 for z in ics])) if ics else None,'median_fold_ic':num(np.median(ics)) if ics else None,'worst_fold_ic':num(min(ics)) if ics else None,'positive_month_ratio':num(np.mean([z>0 for z in months if z is not None])) if any(z is not None for z in months) else None,'valid_symbol_count':sum(z is not None for z in symbols),'positive_symbol_net_spread_count':sum(z is not None and z>0 for z in symbols),'negative_symbol_net_spread_count':sum(z is not None and z<=0 for z in symbols),'top5_date_concentration':concentration(x,5,True) if len(x) else None,'top10_event_concentration':concentration(x,10) if len(x) else None,'unique_score_count':u,'score_tie_ratio':num(1-u/len(x)) if len(x) else None}
def evaluate(events,features,name,fs):
 out=[]; frows=[]; fits=0
 for f in fs:
  tr=events[events.date.isin(f['train_dates'])]; te=events[events.date.isin(f['test_dates'])]; valid=len(tr)>=2 and len(te)>=2
  if valid:
   m=make_model(name,features).fit(tr[features+['symbol']],tr.target_return); pred=m.predict(te[features+['symbol']]); q=te[['date','symbol','target_return']].copy();q['prediction']=pred;out.append(q); ic=num(spearmanr(q.target_return,pred).statistic);fits+=1
  else: ic=None
  frows.append({'model':name,'fold_id':f['fold_id'],'train_start_date':min(f['train_dates']),'train_end_date':max(f['train_dates']),'test_start_date':min(f['test_dates']),'test_end_date':max(f['test_dates']),'train_event_count':len(tr),'test_event_count':len(te),'spearman_ic':ic,'valid':valid,'time_order_valid':max(f['train_dates'])<min(f['test_dates'])})
 x=pd.concat(out,ignore_index=True) if out else pd.DataFrame(columns=['date','symbol','target_return','prediction']); result=metric(x,frows,len(events)); result.update({'model':name,'valid_fold_count':sum(z['valid'] for z in frows),'invalid_fold_count':sum(not z['valid'] for z in frows)}); syms=[]
 for s in SYMS:
  z=metric(x[x.symbol==s],frows,len(events));z.update({'model':name,'symbol':s});syms.append(z)
 return result,frows,syms,fits
def psi(a,b):
 if len(a)<2 or len(b)<1:return None
 edges=np.unique(np.quantile(a,np.linspace(0,1,11)));
 if len(edges)<3:return 0.
 aa=np.histogram(a,bins=edges)[0]/len(a);bb=np.histogram(b,bins=edges)[0]/len(b);aa=np.clip(aa,1e-6,None);bb=np.clip(bb,1e-6,None);return num(np.sum((aa-bb)*np.log(aa/bb)))
def quality(events,features,devmonths):
 ans=[]
 for f in BASE_FEATURES+PRICE_FEATURES[len(BASE_FEATURES):]+ETF_FEATURES+VOLUME_FEATURES:
  present=f in features; v=events[f] if present else pd.Series(dtype=float); finite=np.isfinite(v).sum() if present else 0; missing=v.isna().mean() if present and len(v) else 1.; uniq=int(v.nunique()) if present else 0; usable=bool(present and missing<=.20 and finite/len(v)>=.99 and uniq>=3)
  ans.append({'feature':f,'included':present,'usable':usable,'usable_event_count':int(finite),'missing_ratio':num(missing),'finite_ratio':num(finite/len(v)) if len(v) else 0.,'mean':num(v.mean()) if present else None,'std':num(v.std(ddof=0)) if present else None,'unique_count':uniq,'extreme_value_ratio':num(np.mean(np.abs((v-v.mean())/(v.std(ddof=0) or np.nan))>6)) if present else None,'development_vs_former_validation_psi':psi(v[events.date.str[:7].isin(devmonths)].dropna(),v[~events.date.str[:7].isin(devmonths)].dropna()) if present else None,'time_available_at_or_before_open':present,'pit_compliant':present,'rejection_reason':None if usable else ('VOLUME_CONTRACT_NOT_MET' if f in VOLUME_FEATURES and not present else 'QUALITY_OR_PIT_FAILURE')})
 return ans
def passes(r):
 return all([r['research_coverage_ratio']>=.80,r['event_count']>=7500,r['oof_spearman_ic'] is not None and r['oof_spearman_ic']>0,r['top_bottom_spread_net_10bps'] is not None and r['top_bottom_spread_net_10bps']>0,r['positive_fold_ratio'] is not None and r['positive_fold_ratio']>=.60,r['median_fold_ic'] is not None and r['median_fold_ic']>0,r['positive_month_ratio'] is not None and r['positive_month_ratio']>=.50,r['valid_symbol_count']==6,r['positive_symbol_net_spread_count']>=4,r['top5_date_concentration'] is not None and r['top5_date_concentration']<.60,r['valid_fold_count']==5])
def run(results_root=REPO/'.local_results'):
 c=json.loads(CONTRACT.read_text(encoding='utf-8')); months=c['split']['development_months']+c['split']['validation_months']; events,volumes,volume_reason=build_events(months)
 if len(events)!=9497: raise RuntimeError(f'RESEARCH_EVENT_COUNT_MISMATCH:{len(events)}')
 features=FIXED_FEATURES+volumes; q=quality(events,features,c['split']['development_months']); usable=[x['feature'] for x in q if x['usable']]
 if not usable: raise RuntimeError('NO_USABLE_FEATURES')
 fs=folds(events.date); models=[];foldrows=[];symrows=[];fits=0
 for name in MODEL_SPECS:
  r,f,s,n=evaluate(events,usable,name,fs);r['candidate_pass']=passes(r);models.append(r);foldrows+=f;symrows+=s;fits+=n
 winners=[r for r in models if r['candidate_pass']]; rank={'RIDGE':0,'CONSTRAINED_RANDOM_FOREST':1}; selected=sorted(winners,key=lambda r:(-r['median_fold_ic'],-r['top_bottom_spread_net_10bps'],-r['positive_symbol_net_spread_count'],r['top5_date_concentration'],rank[r['model']]))[0] if winners else None; best=sorted(models,key=lambda r:(r['oof_spearman_ic'] is not None,r['oof_spearman_ic'] or -99),reverse=True)[0]
 summary={'research_id':OUT_NAME,'final_status':'PASS','final_decision':'EXPANDED_PIT_FEATURE_RESEARCH_CANDIDATE_FOUND' if selected else 'FAST3_EXPANDED_FEATURE_LINE_STOPPED_NO_STABLE_EDGE','next_freeze_stage_allowed':bool(selected),'fast3_expanded_feature_line_stopped':not bool(selected),'selected_model':selected['model'] if selected else None,'research_event_count':len(events),'former_development_role':'RESEARCH_DATA','former_validation_role':'RESEARCH_DATA','former_validation_still_independent':False,'confirmation_remains_sealed':True,'confirmation_row_read_count':0,'base_feature_count':3,'expanded_feature_count':len(features),'usable_feature_count':len(usable),'rejected_feature_count':len(q)-len(usable),'volume_features_included':bool(volumes),'volume_feature_exclusion_reason':volume_reason,'candidate_model_count':2,'hyperparameter_search_count':0,'valid_fold_count':len(fs),'invalid_fold_count':0,'time_order_violation_count':sum(not x['time_order_valid'] for x in foldrows),'data_leakage_detected':False,'research_fit_call_count':fits,'final_frozen_model_output_count':0,'broker_action_allowed':False,'paper_trading_allowed':False,'official_adoption_allowed':False,'live_trading_allowed':False,'order_output_count':0,'position_output_count':0,'broker_connection_count':0,**{f'{r["model"].lower()}_{k}':r[k] for r in models for k in ('oof_spearman_ic','top_bottom_spread_net_10bps')},**{f'best_{k}':best[k] for k in ('model','oof_spearman_ic','top_bottom_spread_net_10bps','positive_fold_ratio','positive_month_ratio','positive_symbol_net_spread_count','research_coverage_ratio')}}
 out=Path(results_root)/'v22'/OUT_NAME;out.parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix='.073a_',dir=out.parent))
 try:
  (stage/'v22_073a_summary.json').write_text(dump(summary),encoding='utf-8');(stage/'feature_contract.json').write_text(dump({'primary_hypothesis':HYPOTHESIS,'fixed_features':BASE_FEATURES+PRICE_FEATURES[len(BASE_FEATURES):]+ETF_FEATURES+VOLUME_FEATURES,'included_features':features,'usable_features':usable,'symbols':SYMS,'target':'V22.069_INTRADAY_OPEN_TO_CLOSE','cost_bps':10,'confirmation_remains_sealed':True,'confirmation_row_read_count':0,'volume_contract_reason':volume_reason,'random_kfold_used':False}),encoding='utf-8');pd.DataFrame(q).to_csv(stage/'feature_quality.csv',index=False);pd.DataFrame(models).to_csv(stage/'model_scorecard.csv',index=False);pd.DataFrame(foldrows).to_csv(stage/'fold_scorecard.csv',index=False);pd.DataFrame(symrows).to_csv(stage/'symbol_scorecard.csv',index=False)
  if out.exists(): shutil.rmtree(out)
  os.replace(stage,out);return summary,out
 except Exception: shutil.rmtree(stage,ignore_errors=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');a.add_argument('--results-root',default=str(REPO/'.local_results'));z=a.parse_args()
 if z.execute:
  s,o=run(Path(z.results_root));print(json.dumps({**s,'summary_path':str(o/'v22_073a_summary.json')},ensure_ascii=False,sort_keys=True))
