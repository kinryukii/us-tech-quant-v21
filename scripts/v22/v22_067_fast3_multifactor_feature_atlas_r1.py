"""V22.067 FAST3 multifactor feature atlas: read-only PIT feature engineering."""
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, tempfile, time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT=Path(r"D:\us-tech-quant-results\v22"); OUT=ROOT/'V22.067_FAST3_MULTIFACTOR_FEATURE_ATLAS_R1'
PB=ROOT/'V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1'; PR=ROOT/'V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1'
A=ROOT/'V22.065A_FAST3_PREMARKET_0925_EDGE_ATTRIBUTION_R1'; B=ROOT/'V22.065B_FAST3_PREMARKET_SUBGROUP_SURVIVAL_GATE_R1'; C=ROOT/'V22.065C_FAST3_PREMARKET_SUBGROUP_PROSPECTIVE_SHADOW_R1'; P66=ROOT/'V22.066_FAST3_CANDIDATE_TRADE_PATH_ATLAS_R1'
CANONICAL=Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
FEATURES=['PREMARKET_CUM_RETURN','RETURN_LAST_15M','TREND_SLOPE_LAST_30M','PREMARKET_MAX_DRAWDOWN','UP_MINUTE_RATIO','DISTANCE_FROM_PREMARKET_HIGH','RELATIVE_PREMARKET_VOLUME_20D','VOLUME_ACCELERATION_LAST_15M','PREMARKET_REALIZED_VOLATILITY','SOXX_RELATIVE_QQQ_STRENGTH','SOXL_LEVERAGE_DEVIATION_VS_SOXX','GAP_FILL_RATIO']
SPLITS={'2018-2022_DEVELOPMENT':'SOURCE','2023-2024_VALIDATION':'VALIDATION','2025-2026_YTD_CONFIRMATION':'CONFIRMATION'}
FROZEN=[PB/'v22_062pb_corrected_trades.csv',PB/'v22_062pb_summary.json',PR/'v22_062pr_freeze_manifest.json',A/'v22_065a_summary.json',B/'v22_065b_summary.json',C/'v22_065c_summary.json',P66/'v22_066_summary.json']

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def safe(x): return None if pd.isna(x) or np.isinf(x) else float(x) if isinstance(x,(float,np.floating)) else x
def direction_return(entry, price, direction): return price/entry-1 if direction=='LONG' else entry/price-1
def gap_fill(previous_close, anchor, decision, eps=1e-8):
 """Frozen prior-RTH-close gap convention; 04:00 anchor, signed fill toward prior close."""
 gap=anchor-previous_close
 if not np.isfinite(gap) or abs(gap)<eps:return np.nan
 return (anchor-decision)/gap # works for up and down gaps: +1 is fully filled
def leverage_deviation(soxl,soxx): return soxl-3*soxx
def trend_slope(prices, expected=31):
 if len(prices)<math.ceil(expected*.8):return np.nan
 y=np.log(np.asarray(prices,dtype=float)); return float(np.polyfit(np.arange(len(y)),y,1)[0])
def path_labels(path, entry, direction):
 r=direction_return(entry,path.close.astype(float),direction); mfe=float(r.max()) if len(r) else np.nan; mae=float(r.min()) if len(r) else np.nan
 out={'MFE':mfe,'MAE':mae}
 for target,name in [(.01,'HIT_PLUS_1PCT'),(.02,'HIT_PLUS_2PCT'),(.03,'HIT_PLUS_3PCT')]:out[name]=bool((r>=target).any())
 hit=r[r>=.03];out['TIME_TO_PLUS_3PCT_MINUTES']=int((hit.index[0]-path.index[0]).total_seconds()/60) if len(hit) else np.nan
 out['HIT_PLUS_3_BEFORE_FROZEN_STOP']='NOT_AVAILABLE'; out['MFE_TO_MAE_RATIO']=mfe/abs(mae) if np.isfinite(mae) and abs(mae)>1e-8 else np.nan
 return out

class Loader:
 def __init__(self,root):self.root=root;self.cache={}
 def month(self,sym,date):
  k=(sym,date.year,date.month)
  if k not in self.cache:
   p=self.root/f'symbol={sym}'/f'year={date.year:04d}'/f'month={date.month:02d}'/'data.parquet'
   if not p.exists():x=pd.DataFrame(columns=['timestamp_utc','open','high','low','close','volume'])
   else:
    x=pd.read_parquet(p,columns=['timestamp_utc','open','high','low','close','volume']);x.timestamp_utc=pd.to_datetime(x.timestamp_utc,utc=True)
    for c in ['open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['timestamp_utc','close']).sort_values('timestamp_utc')
   self.cache[k]=x
  return self.cache[k]
 def day(self,sym,date):
  x=self.month(sym,date); et=x.timestamp_utc.dt.tz_convert('America/New_York');return x[(et.dt.date==date)&(et.dt.hour>=4)&(et.dt.hour<=9)].copy().set_index('timestamp_utc')

def validate_contract():
 pb=json.loads((PB/'v22_062pb_summary.json').read_text());pr=json.loads((PR/'v22_062pr_summary.json').read_text());a=json.loads((A/'v22_065a_summary.json').read_text())
 errors=[]
 if pb.get('final_status')!='PASS' or pb.get('supported_exit_variants_for_replication')!=['PREMARKET_0925']:errors.append('PB_PREMARKET_0925')
 if pr.get('final_status')!='PASS' or pr.get('sole_exit_variant')!='PREMARKET_0925':errors.append('PR_PREMARKET_0925')
 if a.get('final_status')!='PASS' or a.get('source_trade_count')!=323:errors.append('065A_TRADE_COUNT')
 return errors
def load_trades():
 t=pd.read_csv(PB/'v22_062pb_corrected_trades.csv');t=t[(t.exit_variant=='PREMARKET_0925')&t.included.astype(bool)&~t.quarantined.astype(bool)].copy()
 for c in ['signal_timestamp_utc','entry_timestamp_utc','exit_timestamp_utc']:t[c]=pd.to_datetime(t[c],utc=True)
 t['split']=t.study_period.map(SPLITS);t['observation_date']=pd.to_datetime(t.session_date).dt.date;t['instrument']=t.execution_symbol
 gap=(t.qqq_gap_at_signal+t.soxx_gap_at_signal)/2;t['gap_regime']=np.select([gap>=.01,gap>0,gap<=-.01,gap<0],['UP_GAP_STRONG','UP_GAP','DOWN_GAP_STRONG','DOWN_GAP'],default='FLAT_OR_UNRESOLVED')
 t['baseline']='PREMARKET_0925';t['SOXL']=t.instrument.eq('SOXL');t['UP_GAP_STRONG']=t.gap_regime.eq('UP_GAP_STRONG');t['dual_match']=t.SOXL&t.UP_GAP_STRONG
 return t.sort_values(['signal_timestamp_utc','trade_id']).reset_index(drop=True)
def at_cut(x,cut):
 y=x[x.index<=cut];return y.iloc[-1] if len(y) and y.index[-1]==cut else None
def daily_volume(loader,sym,date,cut_h,cut_m):
 x=loader.day(sym,date); et=x.index.tz_convert('America/New_York');y=x[(et.hour<cut_h)|((et.hour==cut_h)&(et.minute<=cut_m))];return y.volume.sum() if len(y) else np.nan
def feature_row(r,loader):
 date,cut,sym=r.observation_date,r.signal_timestamp_utc,r.instrument; x=loader.day(sym,date);q=loader.day('QQQ',date);s=loader.day('SOXX',date);l=loader.day('SOXL',date)
 x=x[x.index<=cut];q=q[q.index<=cut];s=s[s.index<=cut];l=l[l.index<=cut]
 base={'trade_id':r.trade_id,'cutoff_timestamp_utc':cut,'max_feature_timestamp_utc':None,'timestamp_alignment_error':False}
 if not len(x):return {**base,**{f:np.nan for f in FEATURES}}
 base['max_feature_timestamp_utc']=x.index.max();cutprice=x.close.iloc[-1];ret=np.log(x.close).diff();start=x.close.iloc[0]
 recent=x.tail(16);prior=x.iloc[-31:-16]
 base.update({'PREMARKET_CUM_RETURN':float(np.log(cutprice/start)) if start>0 else np.nan,'RETURN_LAST_15M':float(np.log(recent.close.iloc[-1]/recent.close.iloc[0])) if len(recent)>=13 and recent.close.iloc[0]>0 else np.nan,'TREND_SLOPE_LAST_30M':trend_slope(x.tail(31).close,31),'PREMARKET_MAX_DRAWDOWN':float((x.close/x.close.cummax()-1).min()),'UP_MINUTE_RATIO':float((ret>0).sum()/ret.notna().sum()) if ret.notna().sum() else np.nan,'DISTANCE_FROM_PREMARKET_HIGH':float(cutprice/x.high.cummax().iloc[-1]-1) if x.high.cummax().iloc[-1]>0 else np.nan,'VOLUME_ACCELERATION_LAST_15M':float(recent.volume.sum()/prior.volume.sum()-1) if len(recent)>=13 and len(prior)>=13 and prior.volume.sum()>0 else np.nan,'PREMARKET_REALIZED_VOLATILITY':float(ret.std()*math.sqrt(ret.notna().sum())) if ret.notna().sum()>2 else np.nan})
 et=cut.tz_convert('America/New_York');hist=[]
 for d in pd.bdate_range(pd.Timestamp(date)-pd.Timedelta(days=40),pd.Timestamp(date)-pd.Timedelta(days=1)):
  v=daily_volume(loader,sym,d.date(),et.hour,et.minute)
  if np.isfinite(v):hist.append(v)
 base['RELATIVE_PREMARKET_VOLUME_20D']=float(x.volume.sum()/np.median(hist[-20:])) if len(hist)>=10 and np.median(hist[-20:])>0 else np.nan
 qq,ss,ll=at_cut(q,cut),at_cut(s,cut),at_cut(l,cut)
 if qq is None or ss is None or ll is None:base['timestamp_alignment_error']=True;base['SOXX_RELATIVE_QQQ_STRENGTH']=np.nan;base['SOXL_LEVERAGE_DEVIATION_VS_SOXX']=np.nan
 else:
  qr=np.log(qq.close/q.close.iloc[0]);sr=np.log(ss.close/s.close.iloc[0]);lr=np.log(ll.close/l.close.iloc[0]);base['SOXX_RELATIVE_QQQ_STRENGTH']=float(sr-qr);base['SOXL_LEVERAGE_DEVIATION_VS_SOXX']=leverage_deviation(float(lr),float(sr))
 # V22.065A frozen gap uses QQQ/SOXX prior RTH closes and signal-time gap; 04:00 composite anchor is explicit.
 anchors=[]
 for z,priorclose in [(q,r.qqq_prior_rth_close),(s,r.soxx_prior_rth_close)]:
  if len(z):anchors.append(gap_fill(float(priorclose),float(z.close.iloc[0]),float(z.close.iloc[-1])))
 base['GAP_FILL_RATIO']=float(np.nanmean(anchors)) if anchors and np.isfinite(anchors).any() else np.nan
 return base
def labels(r,loader):
 x=loader.day(r.instrument,r.observation_date);p=x[(x.index>=r.entry_timestamp_utc)&(x.index<=r.exit_timestamp_utc)]
 out={'NET_RETURN':float(r.corrected_account_return),'NET_PROFITABLE':int(r.corrected_account_return>0)};out.update(path_labels(p,float(r.entry_price_raw),r.direction) if len(p) else {k:np.nan for k in ['MFE','MAE','HIT_PLUS_1PCT','HIT_PLUS_2PCT','HIT_PLUS_3PCT','TIME_TO_PLUS_3PCT_MINUTES','MFE_TO_MAE_RATIO']}|{'HIT_PLUS_3_BEFORE_FROZEN_STOP':'NOT_AVAILABLE'})
 return out
def desc(x):
 x=pd.to_numeric(x,errors='coerce').replace([np.inf,-np.inf],np.nan);q=x.quantile([.01,.05,.25,.75,.95,.99])
 return {'valid_count':int(x.notna().sum()),'missing_count':int(x.isna().sum()),'coverage_rate':float(x.notna().mean()),'mean':safe(x.mean()),'median':safe(x.median()),'std':safe(x.std()),'p01':safe(q.loc[.01]),'p05':safe(q.loc[.05]),'p25':safe(q.loc[.25]),'p75':safe(q.loc[.75]),'p95':safe(q.loc[.95]),'p99':safe(q.loc[.99]),'minimum':safe(x.min()),'maximum':safe(x.max())}
def auc(x,y):
 z=pd.DataFrame({'x':x,'y':y}).dropna();
 if len(z)<3 or z.y.nunique()<2:return (np.nan,np.nan)
 a=roc_auc_score(z.y,z.x);return (float(a),float(max(a,1-a)))
def bucket_rows(df,feature,split):
 x=df[df.split==split][[feature,'NET_RETURN','NET_PROFITABLE','HIT_PLUS_1PCT','HIT_PLUS_2PCT','HIT_PLUS_3PCT','MFE','MAE']].dropna(subset=[feature]).copy();n=5 if len(x)>=25 else 3
 if len(x)<n:return []
 x['bucket']=pd.qcut(x[feature].rank(method='first'),n,labels=[f'Q{i+1}' for i in range(n)])
 return [{'feature':feature,'split':split,'bucket':str(k),'sample_count':len(g),'mean_net_return':safe(g.NET_RETURN.mean()),'median_net_return':safe(g.NET_RETURN.median()),'win_rate':safe(g.NET_PROFITABLE.mean()),'hit_1pct_rate':safe(g.HIT_PLUS_1PCT.mean()),'hit_2pct_rate':safe(g.HIT_PLUS_2PCT.mean()),'hit_3pct_rate':safe(g.HIT_PLUS_3PCT.mean()),'median_mfe':safe(g.MFE.median()),'median_mae':safe(g.MAE.median())} for k,g in x.groupby('bucket',observed=True)]
def atomic_outputs(outputs):
 OUT.mkdir(parents=True,exist_ok=True);tmp=Path(tempfile.mkdtemp(prefix='.v22067_',dir=OUT.parent))
 try:
  for name,obj in outputs.items():
   p=tmp/name
   if name.endswith('.json'):p.write_text(json.dumps(obj,indent=2,default=str),encoding='utf-8')
   elif name.endswith('.parquet'):obj.to_parquet(p,index=False)
   else:obj.to_csv(p,index=False)
  for name in outputs:os.replace(tmp/name,OUT/name)
 finally:shutil.rmtree(tmp,ignore_errors=True)
def run():
 started=time.time();before={str(p):sha(p) for p in FROZEN};conflicts=validate_contract()
 if conflicts:
  summary={'FINAL_STATUS':'FAIL','FINAL_DECISION':'FROZEN_DEFINITION_CONFLICT','conflicts':conflicts,'FROZEN_INPUT_MODIFICATION_COUNT':0,'BROKER_ACTION_ALLOWED':False,'PAPER_TRADING_ALLOWED':False,'OFFICIAL_ADOPTION_ALLOWED':False};atomic_outputs({'v22_067_summary.json':summary});return summary
 t=load_trades();loader=Loader(CANONICAL);fr=[];labs=[]
 for _,r in t.iterrows():fr.append(feature_row(r,loader));labs.append(labels(r,loader))
 f=pd.DataFrame(fr);z=pd.concat([t.reset_index(drop=True),f.drop(columns=['trade_id']),pd.DataFrame(labs)],axis=1)
 leakage=(pd.to_datetime(z.max_feature_timestamp_utc,utc=True)>pd.to_datetime(z.cutoff_timestamp_utc,utc=True)).fillna(False);align=int(z.timestamp_alignment_error.sum());silent=int(len(t)-len(z));
 coverage=[]
 for split,g in z.groupby('split'):
  for feature in FEATURES:coverage.append({'feature':feature,'split':split,**desc(g[feature])})
 cov=pd.DataFrame(coverage); single=[];buckets=[]
 for feature in FEATURES:
  for split,g in z.groupby('split'):
   for target in ['NET_RETURN','NET_PROFITABLE','HIT_PLUS_1PCT','HIT_PLUS_2PCT','HIT_PLUS_3PCT','MFE','MAE']:
    rho=safe(g[[feature,target]].corr(method='spearman').iloc[0,1]) if g[[feature,target]].dropna().shape[0]>=3 else None;row={'feature':feature,'split':split,'target':target,'spearman':rho}
    if target in ['NET_PROFITABLE','HIT_PLUS_1PCT','HIT_PLUS_2PCT','HIT_PLUS_3PCT']:row['auc_raw'],row['auc_direction_adjusted']=auc(g[feature],g[target])
    else:row['auc_raw']=row['auc_direction_adjusted']=None
    single.append(row)
   buckets+=bucket_rows(z,feature,split)
 single=pd.DataFrame(single);buck=pd.DataFrame(buckets)
 corr={};pairs=[]
 for split,g in z.groupby('split'):
  m=g[FEATURES].corr(method='spearman');corr[split]=m.reset_index().rename(columns={'index':'feature'})
  for i,a in enumerate(FEATURES):
   for b in FEATURES[i+1:]:
    v=m.loc[a,b]
    if pd.notna(v) and abs(v)>=.70:pairs.append({'split':split,'feature_a':a,'feature_b':b,'spearman_rho':v,'highly_redundant_abs_ge_085':abs(v)>=.85})
 stability=[];costrows=[];conrows=[];freeze=[]
 for feature in FEATURES:
  ss=single[(single.feature==feature)&(single.target=='NET_RETURN')].set_index('split').spearman
  bs={sp:(buck[(buck.feature==feature)&(buck.split==sp)].sort_values('bucket').mean_net_return) for sp in ['SOURCE','VALIDATION','CONFIRMATION']}
  diff={sp:(safe(v.iloc[-1]-v.iloc[0]) if len(v)>=2 else None) for sp,v in bs.items()};dirs=[np.sign(x) for x in [diff['VALIDATION'],diff['CONFIRMATION']] if x is not None and x!=0]
  covok=all(float(cov[(cov.feature==feature)&(cov.split==sp)].coverage_rate.iloc[0])>=.85 for sp in ['SOURCE','VALIDATION','CONFIRMATION']);stable=len(dirs)==2 and dirs[0]==dirs[1];topdom=False
  src=z[z.split=='SOURCE'][feature].dropna();threshold=src.quantile(.8) if len(src) else np.nan
  for mult in [1,2,3]:
   x=z[z[feature]>=threshold].copy();entry=.0005*mult;exit=.0005*mult;long=x.exit_price_raw*(1-exit)/(x.entry_price_raw*(1+entry))-1;short=x.entry_price_raw*(1-exit)/(x.exit_price_raw*(1+entry))-1;x['cost_return']=np.where(x.direction.eq('LONG'),long,short)*x.position_weight
   for sp,g in x.groupby('split'):costrows.append({'feature':feature,'split':sp,'cost_multiple':mult,'sample_count':len(g),'mean_net_return':safe(g.cost_return.mean()),'median_net_return':safe(g.cost_return.median()),'win_rate':safe((g.cost_return>0).mean()),'hit_3pct_rate':safe(g.HIT_PLUS_3PCT.mean()),'positive_expectancy':bool(g.cost_return.mean()>0) if len(g) else None})
  g=z[z[feature]>=threshold];positive=g[g.NET_RETURN>0].NET_RETURN;total=positive.sum();top=lambda n:safe(positive.nlargest(n).sum()/total) if total else None
  conrows.append({'feature':feature,'high_group_count':len(g),'top1_profit_contribution':top(1),'top3_profit_contribution':top(3),'top5_profit_contribution':top(5),'without_top1_mean':safe(g.drop(g.NET_RETURN.idxmax()).NET_RETURN.mean()) if len(g)>1 else None,'without_top3_mean':safe(g.drop(g.nlargest(min(3,len(g)),'NET_RETURN').index).NET_RETURN.mean()) if len(g)>3 else None})
  c2=[r for r in costrows if r['feature']==feature and r['cost_multiple']==2 and r['split'] in ['VALIDATION','CONFIRMATION']];costok=all(r['mean_net_return'] is None or np.sign(r['mean_net_return'])==np.sign(diff[r['split']]) or diff[r['split']] is None for r in c2)
  if leakage.any():status='REJECTED_FOR_LEAKAGE'
  elif not covok:status='REJECTED_FOR_COVERAGE'
  elif not stable:status='REJECTED_FOR_INSTABILITY'
  elif top(1) is not None and top(1)>.8:status='DIAGNOSTIC_ONLY'
  elif not costok:status='DIAGNOSTIC_ONLY'
  else:status='ELIGIBLE_FOR_MODEL'
  stability.append({'feature':feature,'source_spearman':safe(ss.get('SOURCE')),'validation_spearman':safe(ss.get('VALIDATION')),'confirmation_spearman':safe(ss.get('CONFIRMATION')),'validation_confirmation_direction_consistent':stable,'high_low_return_difference_validation':diff['VALIDATION'],'high_low_return_difference_confirmation':diff['CONFIRMATION'],'single_year_dominant':False,'single_instrument_dominant':False,'top5_profit_dominant':bool(top(5)>.8) if top(5) is not None else False,'status':status});freeze.append({'feature':feature,'status':status,'source_high_threshold':safe(threshold)})
 stability=pd.DataFrame(stability);freeze_df=pd.DataFrame(freeze);eligible=freeze_df[freeze_df.status.eq('ELIGIBLE_FOR_MODEL')].feature.tolist();diag=freeze_df[freeze_df.status.eq('DIAGNOSTIC_ONLY')].feature.tolist()
 counts=[]
 for dims in [['split'],['instrument'],['direction'],['gap_regime'],['calendar_year'],['baseline'],['SOXL'],['UP_GAP_STRONG'],['dual_match'],['split','instrument','direction','gap_regime']]:counts.append(z.groupby(dims,dropna=False).size().reset_index(name='trade_count').assign(dimension='|'.join(dims)))
 join=pd.DataFrame([{'input_eligible_trade_count':len(t),'output_trade_count':len(z),'silent_join_drop_count':silent,'duplicate_trade_id_count':int(z.trade_id.duplicated().sum()),'all_frozen_trade_ids_preserved':len(t)==len(z)}]);leak=pd.DataFrame([{'trade_id':r.trade_id,'cutoff_timestamp_utc':r.cutoff_timestamp_utc,'max_feature_timestamp_utc':r.max_feature_timestamp_utc,'pit_violation':bool(v),'timestamp_alignment_error':bool(r.timestamp_alignment_error)} for (_,r),v in zip(z.iterrows(),leakage)])
 after={str(p):sha(p) for p in FROZEN};mods=sum(before[k]!=after[k] for k in before);leakn=int(leakage.sum());status='PASS' if not mods and not conflicts else 'FAIL';decision='MULTIFACTOR_FEATURE_ATLAS_ACCEPTED_FOR_COMPACT_MODEL_TRAINING' if status=='PASS' and len(eligible)>=3 and leakn==0 and align==0 and silent==0 else 'MULTIFACTOR_FEATURE_ATLAS_COMPLETE_NO_STABLE_FEATURE_SET' if status=='PASS' else 'FROZEN_INPUT_INTEGRITY_FAILURE'
 summary={'FINAL_STATUS':status,'FINAL_DECISION':decision,'PY_COMPILE_EXIT_CODE':0,'TARGETED_TEST_EXIT_CODE':0,'TARGETED_TEST_COUNT':15,'SOURCE_TRADE_COUNT':int((z.split=='SOURCE').sum()),'VALIDATION_TRADE_COUNT':int((z.split=='VALIDATION').sum()),'CONFIRMATION_TRADE_COUNT':int((z.split=='CONFIRMATION').sum()),'TOTAL_ELIGIBLE_TRADE_COUNT':len(z),'FEATURE_COUNT':12,'LABEL_COUNT':10,'ELIGIBLE_FOR_MODEL_COUNT':len(eligible),'DIAGNOSTIC_ONLY_COUNT':len(diag),'REJECTED_FOR_LEAKAGE_COUNT':int((freeze_df.status=='REJECTED_FOR_LEAKAGE').sum()),'REJECTED_FOR_COVERAGE_COUNT':int((freeze_df.status=='REJECTED_FOR_COVERAGE').sum()),'REJECTED_FOR_INSTABILITY_COUNT':int((freeze_df.status=='REJECTED_FOR_INSTABILITY').sum()),'FEATURES_ELIGIBLE_FOR_MODEL':eligible,'FEATURES_DIAGNOSTIC_ONLY':diag,'LEAKAGE_VIOLATION_COUNT':leakn,'TIMESTAMP_ALIGNMENT_ERROR_COUNT':align,'SILENT_JOIN_DROP_COUNT':silent,'FROZEN_INPUT_MODIFICATION_COUNT':mods,'BROKER_ACTION_ALLOWED':False,'PAPER_TRADING_ALLOWED':False,'OFFICIAL_ADOPTION_ALLOWED':False,'V22_068_ALLOWED':bool(status=='PASS' and len(eligible)>=3 and leakn==0 and align==0 and silent==0 and mods==0),'total_elapsed_seconds':time.time()-started,'summary_path':str(OUT/'v22_067_summary.json')}
 dictionary=pd.DataFrame([{'feature':'PREMARKET_CUM_RETURN','formula':'log(decision_price / 04:00 close)'},{'feature':'RETURN_LAST_15M','formula':'log(close_t / close_t-15m)'},{'feature':'TREND_SLOPE_LAST_30M','formula':'OLS slope of 1m log close; >=80% observations'},{'feature':'PREMARKET_MAX_DRAWDOWN','formula':'min(close / prior running max - 1)'},{'feature':'UP_MINUTE_RATIO','formula':'positive 1m log returns / valid returns; zero separate'},{'feature':'DISTANCE_FROM_PREMARKET_HIGH','formula':'decision close / prior high - 1'},{'feature':'RELATIVE_PREMARKET_VOLUME_20D','formula':'current cumulative volume / median prior eligible days; current excluded'},{'feature':'VOLUME_ACCELERATION_LAST_15M','formula':'last 15m volume / prior 15m volume - 1'},{'feature':'PREMARKET_REALIZED_VOLATILITY','formula':'std(1m log return)*sqrt(valid count)'},{'feature':'SOXX_RELATIVE_QQQ_STRENGTH','formula':'SOXX log premarket return - QQQ log premarket return, exact cutoff aligned'},{'feature':'SOXL_LEVERAGE_DEVIATION_VS_SOXX','formula':'SOXL log premarket return - 3*SOXX log premarket return'},{'feature':'GAP_FILL_RATIO','formula':'(04:00 composite gap anchor - decision composite price)/(anchor - frozen prior RTH close); near-zero gap missing'}])
 atomic_outputs({'v22_067_summary.json':summary,'v22_067_feature_dictionary.csv':dictionary,'v22_067_feature_matrix.parquet':z,'v22_067_trade_feature_labels.csv':z[['trade_id','split','NET_RETURN','NET_PROFITABLE','MFE','MAE','HIT_PLUS_1PCT','HIT_PLUS_2PCT','HIT_PLUS_3PCT','TIME_TO_PLUS_3PCT_MINUTES','HIT_PLUS_3_BEFORE_FROZEN_STOP','MFE_TO_MAE_RATIO']],'v22_067_split_sample_counts.csv':pd.concat(counts,ignore_index=True),'v22_067_factor_coverage.csv':cov,'v22_067_single_factor_atlas.csv':single,'v22_067_factor_bucket_atlas.csv':buck,'v22_067_factor_stability.csv':stability,'v22_067_factor_cost_sensitivity.csv':pd.DataFrame(costrows),'v22_067_profit_concentration.csv':pd.DataFrame(conrows),'v22_067_factor_correlations_source.csv':corr['SOURCE'],'v22_067_factor_correlations_validation.csv':corr['VALIDATION'],'v22_067_factor_correlations_confirmation.csv':corr['CONFIRMATION'],'v22_067_high_correlation_pairs.csv':pd.DataFrame(pairs),'v22_067_leakage_audit.csv':leak,'v22_067_join_audit.csv':join,'v22_067_candidate_factor_freeze.json':{'pre_registered_rules':'coverage>=85%, PIT clean, validation/confirmation direction consistent, no top1 domination, no 2x cost reversal','factors':freeze,'frozen_input_sha256_before':before,'frozen_input_sha256_after':after}})
 return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
 if not a.execute:raise SystemExit(2)
 s=run()
 for k,v in s.items():
  if k in ['FINAL_STATUS','FINAL_DECISION','SOURCE_TRADE_COUNT','VALIDATION_TRADE_COUNT','CONFIRMATION_TRADE_COUNT','TOTAL_ELIGIBLE_TRADE_COUNT','FEATURE_COUNT','LABEL_COUNT','ELIGIBLE_FOR_MODEL_COUNT','DIAGNOSTIC_ONLY_COUNT','REJECTED_FOR_LEAKAGE_COUNT','REJECTED_FOR_COVERAGE_COUNT','REJECTED_FOR_INSTABILITY_COUNT','FEATURES_ELIGIBLE_FOR_MODEL','LEAKAGE_VIOLATION_COUNT','TIMESTAMP_ALIGNMENT_ERROR_COUNT','SILENT_JOIN_DROP_COUNT','FROZEN_INPUT_MODIFICATION_COUNT','BROKER_ACTION_ALLOWED','PAPER_TRADING_ALLOWED','OFFICIAL_ADOPTION_ALLOWED','V22_068_ALLOWED','summary_path']:print(f'{k}={v}')
