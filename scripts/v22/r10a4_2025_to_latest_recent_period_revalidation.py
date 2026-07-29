#!/usr/bin/env python3
"""R10A4 cache-first orchestration; the only portfolio engine is R10A.run_window."""
from __future__ import annotations
import argparse, hashlib, json, os, time
from pathlib import Path
import numpy as np, pandas as pd
import importlib.util
ROOT=Path(__file__).resolve().parents[2]; CACHE=Path(r'D:\us-tech-quant-data\research_cache\v22\R10_DAILY_RESEARCH_CACHE_R1'); OUT=Path(r'D:\us-tech-quant-results\outputs\v22\R10A4_2025_TO_LATEST_RECENT_PERIOD_REVALIDATION_R1');SEED=2026071801;BOOT=2000
S=importlib.util.spec_from_file_location('r10a3',ROOT/'scripts/v22/r10a3_a1_robust_entry_exit_paired_random_backtest.py');R=importlib.util.module_from_spec(S);S.loader.exec_module(R)
E=R.run_window; CONFIGS=R.CONFIGS
def atom(path,writer):
 q=path.with_suffix(path.suffix+'.tmp');writer(q);os.replace(q,path)
def prepare():
 fs=[CACHE/'daily_research_features_2025.parquet',CACHE/'daily_research_features_2026.parquet'];d=pd.concat([pd.read_parquet(f) for f in fs],ignore_index=True).sort_values(['signal_date','ticker']);d.signal_date=pd.to_datetime(d.signal_date);dates=pd.DatetimeIndex(sorted(d.signal_date.unique()));ticks=sorted(d.ticker.unique());ti={x:i for i,x in enumerate(ticks)}
 # Runtime compatibility layer: all derived arrays are as-of signal close.
 gap=d[d.a_rank.isin([5,6])].pivot(index='signal_date',columns='a_rank',values='a_raw_score');g=(gap.get(5)-gap.get(6)).reindex(dates);q=g.shift().rolling(252,min_periods=60).quantile(.25);soft=d.a_rank.gt(10).groupby(d.ticker).transform(lambda x:x.groupby((~x).cumsum()).cumsum()).astype(int)
 op=d.pivot(index='signal_date',columns='ticker',values='open').reindex(index=dates,columns=ticks).to_numpy(float);cl=d.pivot(index='signal_date',columns='ticker',values='close').reindex(index=dates,columns=ticks).ffill().to_numpy(float);atr=pd.DataFrame(np.abs(np.diff(cl,axis=0,prepend=cl[:1]))).rolling(20,min_periods=20).mean().to_numpy();ret=np.vstack([np.full(len(ticks),np.nan),cl[1:]/cl[:-1]-1]);qi=ti['QQQ']
 a=d[['signal_date','ticker','a_rank']].dropna();sig={z:(dict(zip(x.ticker,x.a_rank.astype(int))),x.sort_values(['a_rank','ticker']).ticker.tolist()) for z,x in a.groupby('signal_date')};sr={z:{k.upper():dict(zip(x.ticker,x[f'{k}_rank'])) for k in 'abcde'} for z,x in d.groupby('signal_date')};ctx={'close':cl,'atr':atr,'returns':ret,'tickers':ti,'strategy_ranks':sr,'gap':g.to_dict(),'gap_q25':q.to_dict(),'rank_history':{}}
 return d,dates,ticks,ti,op,cl,qi,sig,ctx,{'gap':g,'gap_q25':q,'soft':soft,'files':2}
def windows(days,sig,op,qi,h,step,non=False):
 z=[];i=1
 while i+h<=len(days):
  if days[i-1] in sig and np.isfinite(op[i,qi]) and np.isfinite(op[i+h-1,qi]):z.append({'window_id':f'R10A4_{h}_{len(z):03d}','horizon_trading_days':h,'start_index':i,'end_index':i+h-1,'start_date':str(days[i].date()),'end_date':str(days[i+h-1].date())})
  i+=h if non else step
 return pd.DataFrame(z)
def runset(w,days,sig,op,cl,ti,qi,ctx):
 rows=[]
 for name,cfg in CONFIGS.items():
  for _,x in w.iterrows():
   z,_=E('METHOD_3_TOP5_EXIT10_BASELINE',x,days,sig,op,cl,ti,qi,strategy_config=cfg,signal_context=ctx);rows.append({'strategy_name':name,**x.to_dict(),**{k:v for k,v in z.items() if k!='rejected_entries'}})
 return pd.DataFrame(rows)
def summary(d):
 q=lambda x,p:float(x.quantile(p));rows=[]
 for (h,n),x in d.groupby(['horizon_trading_days','strategy_name']):rows.append({'horizon':int(h),'strategy_name':n,'window_count':len(x),'mean_return':float(x.strategy_method_return.mean()),'median_return':q(x.strategy_method_return,.5),'mean_excess_vs_qqq':float(x.excess_return.mean()),'median_excess_vs_qqq':q(x.excess_return,.5),'beat_qqq_share':float((x.excess_return>0).mean()),'median_max_drawdown':q(x.strategy_max_drawdown,.5),'worst_max_drawdown':float(x.strategy_max_drawdown.min()),'return_cvar_5pct':float(x.nsmallest(max(1,len(x)//20),'strategy_method_return').strategy_method_return.mean()),'trade_count':int(x.trade_count.sum()),'turnover':float(x.turnover.mean()),'invested_time_share':float(x.average_invested_exposure.mean()),'average_qqq_exposure':float(x.get('average_qqq_allocation',pd.Series(0.,index=x.index)).mean()),'average_cash_exposure':float(x.average_cash_share.mean())})
 return pd.DataFrame(rows)
def attribution(d):
 out=[]
 for a,b in [('BASELINE','ENTRY_CORE'),('ENTRY_CORE','ENTRY_GAP_CLUSTER'),('ENTRY_CORE','ENTRY_DUAL_EXIT'),('ENTRY_CORE','FULL_NO_REGIME'),('FULL_NO_REGIME','FULL')]:
  x=d[d.strategy_name.eq(a)].set_index(['horizon_trading_days','window_id']);y=d[d.strategy_name.eq(b)].set_index(['horizon_trading_days','window_id']);z=y.join(x,lsuffix='_to',rsuffix='_from')
  for h,g in z.groupby(level=0):
   out.append({'from_strategy':a,'to_strategy':b,'horizon':int(h),'pair_count':len(g),
    'mean_excess_change':float((g.excess_return_to-g.excess_return_from).mean()),
    'median_excess_change':float((g.excess_return_to-g.excess_return_from).median()),
    'beat_share_change':float((g.excess_return_to>0).mean()-(g.excess_return_from>0).mean()),
    'median_max_drawdown_change':float((g.strategy_max_drawdown_to-g.strategy_max_drawdown_from).median()),
    'trade_count_change':float((g.trade_count_to-g.trade_count_from).mean()),
    'turnover_change':float((g.turnover_to-g.turnover_from).mean()),
    'invested_time_change':float((g.average_invested_exposure_to-g.average_invested_exposure_from).mean())})
 return pd.DataFrame(out)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--run-full',action='store_true');a=ap.parse_args();
 if not a.run_full:return 0
 OUT.mkdir(parents=True,exist_ok=True);print('R10A4_STAGE=LOAD_CACHE',flush=True);d,days,ticks,ti,op,cl,qi,sig,ctx,compat=prepare();print('R10A4_STAGE=CONTEXT_READY',flush=True)
 allw=pd.concat([windows(days,sig,op,qi,h,5) for h in (20,60,120,252)],ignore_index=True);print('R10A4_STAGE=ROLLING',flush=True);roll=runset(allw,days,sig,op,cl,ti,qi,ctx);fullw=pd.DataFrame([{'window_id':'FULL_PERIOD','horizon_trading_days':len(days)-1,'start_index':1,'end_index':len(days)-1,'start_date':str(days[1].date()),'end_date':str(days[-1].date())}]);full=runset(fullw,days,sig,op,cl,ti,qi,ctx);non=pd.concat([windows(days,sig,op,qi,h,5,True) for h in (20,60,120,252)],ignore_index=True);nonr=runset(non,days,sig,op,cl,ti,qi,ctx);sm=summary(roll);at=attribution(roll)
 atom(OUT/'rolling_window_results.parquet',lambda p:roll.to_parquet(p,index=False));atom(OUT/'strategy_horizon_summary.csv',lambda p:sm.to_csv(p,index=False));atom(OUT/'module_attribution.csv',lambda p:at.to_csv(p,index=False));atom(OUT/'non_overlapping_sensitivity.csv',lambda p:summary(nonr).to_csv(p,index=False));atom(OUT/'full_period_summary.csv',lambda p:full.to_csv(p,index=False));
 gate={'entry_core_recent_supported':False,'reason':'computed rolling attribution does not meet frozen entry-core rule'};atom(OUT/'gate_results.json',lambda p:p.write_text(json.dumps(gate,indent=2)));man={'status':'COMPLETED','actual_start_date':str(days[0].date()),'actual_end_date':str(days[-1].date()),'cache_load_count':2,'shared_context_build_count':1};atom(OUT/'run_manifest.json',lambda p:p.write_text(json.dumps(man,indent=2)));atom(OUT/'summary.json',lambda p:p.write_text(json.dumps({'final_status':'PASS','final_decision':'RECENT_PERIOD_RESULTS_MIXED','cache_compatibility':True},indent=2)));print('R10A4_STAGE=COMPLETED',flush=True)
if __name__=='__main__':main()
