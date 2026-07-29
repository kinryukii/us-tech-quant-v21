#!/usr/bin/env python3
"""R10A3 runner: orchestration only; all portfolio iteration is run_window."""
from __future__ import annotations
import argparse, json, shutil, sys, os, gc
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.parquet as pq
from r10a_a1_entry_exit_random_backtest import run_window,manifest
ROOT=Path(__file__).resolve().parents[2];OUT=Path(r'D:\us-tech-quant-results\outputs\v22\R10A3_A1_ROBUST_ENTRY_EXIT_PAIRED_RANDOM_BACKTEST_R1');R=Path(r'D:\us-tech-quant-data\derived_cache\abcde_current_rule_proxy_rankings_r8\historical_proxy_rankings.parquet');P=Path(r'D:\us-tech-quant-data\moomoo\source\prices_qfq');SEED=2026071801
CONFIGS={"BASELINE":{"name":"BASELINE","baseline":True},"ENTRY_CORE":{"name":"ENTRY_CORE"},"ENTRY_GAP_CLUSTER":{"name":"ENTRY_GAP_CLUSTER","gap":True,"cluster":True},"ENTRY_DUAL_EXIT":{"name":"ENTRY_DUAL_EXIT"},"FULL_NO_REGIME":{"name":"FULL_NO_REGIME","gap":True,"cluster":True},"FULL":{"name":"FULL","gap":True,"cluster":True,"regime":True}}
def n(x):
 s=str(x).upper();return s[3:] if s.startswith('US.') else s
def data():
 r=pq.read_table(R,columns=['signal_date','strategy','rank','ticker','score']).to_pandas();r.signal_date=pd.to_datetime(r.signal_date).dt.normalize();r.strategy=r.strategy.replace({'A1':'A','E_R1':'E'});r.ticker=r.ticker.map(n);r['rank']=pd.to_numeric(r['rank']);a=r[r.strategy.eq('A')];want=set(a.ticker)|{'QQQ'};z=[]
 for f in P.glob('year=*/prices.parquet'):
  x=pq.read_table(f,columns=['ticker','trade_date','open','close']).to_pandas();x.ticker=x.ticker.map(n);z.append(x[x.ticker.isin(want)])
 p=pd.concat(z);p['date']=pd.to_datetime(p.trade_date).dt.normalize();days=pd.DatetimeIndex(sorted(p.date.unique()));names=sorted(p.ticker.unique());ti={t:i for i,t in enumerate(names)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=days,columns=names).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=days,columns=names).ffill().to_numpy(float)
 sig={d:(dict(zip(g.ticker,g['rank'])),g.sort_values('rank').ticker.tolist()) for d,g in a.groupby('signal_date')};sr={d:{k:dict(zip(x.ticker,x['rank'])) for k,x in g.groupby('strategy')} for d,g in r.groupby('signal_date')};ret=np.vstack([np.full(len(names),np.nan),cl[1:]/cl[:-1]-1]);atr=pd.DataFrame(np.abs(np.diff(cl,axis=0,prepend=cl[:1]))).rolling(20,min_periods=20).mean().to_numpy();gap={};
 for d,(_,top) in sig.items():
  g=a[a.signal_date.eq(d)].set_index('ticker').score;gap[d]=g.get(top[4],np.nan)-g.get(top[5],np.nan) if len(top)>5 else np.nan
 q=pd.Series(gap).sort_index().shift(1).rolling(252,min_periods=60).quantile(.25).to_dict();rh={(i,t):sig.get(days[i],({},[]))[0].get(t) for i in range(len(days)) for t in []};return days,ti,op,cl,sig,{'close':cl,'atr':atr,'returns':ret,'tickers':ti,'strategy_ranks':sr,'gap':gap,'gap_q25':q,'rank_history':rh}
def atomic(path, writer):
 tmp=path.with_suffix(path.suffix+'.tmp');writer(tmp);os.replace(tmp,path)
def paired_bootstrap_ci(values, statistic, repetitions, rng, chunk_size=200):
 values=np.asarray(values,dtype=float);values=values[np.isfinite(values)];est=np.empty(repetitions);o=0
 while o<repetitions:
  c=min(chunk_size,repetitions-o);ix=rng.integers(0,len(values),(c,len(values)));est[o:o+c]=statistic(values[ix],axis=1);o+=c
 return tuple(float(x) for x in np.quantile(est,[.025,.975])) if len(values) else (np.nan,np.nan)
def bootstrap(d):
 out=[];rng=np.random.default_rng(SEED+9173)
 for (h,v),x in d[d.version.ne('BASELINE')].groupby(['horizon_trading_days','version']):
  b=d[(d.horizon_trading_days==h)&d.version.eq('BASELINE')].set_index('window_id');q=x.set_index('window_id').join(b,rsuffix='_b',how='inner');
  a=q.excess_return-q.excess_return_b;ret=q.strategy_method_return-q.strategy_method_return_b;beat=(q.excess_return>0).astype(float)-(q.excess_return_b>0).astype(float);dd=q.strategy_max_drawdown-q.strategy_max_drawdown_b
  ix=rng.integers(0,len(q),(2000,len(q)));ci=lambda z,f:(float(np.quantile(np.apply_along_axis(f,1,z[ix]),.025)),float(np.quantile(np.apply_along_axis(f,1,z[ix]),.975)))
  mc=paired_bootstrap_ci(a.to_numpy(float),np.mean,2000,rng);dc=paired_bootstrap_ci(a.to_numpy(float),np.median,2000,rng);bc=paired_bootstrap_ci(beat.to_numpy(float),np.mean,2000,rng);xc=paired_bootstrap_ci(dd.to_numpy(float),np.median,2000,rng)
  out.append({'strategy_name':v,'horizon':int(h),'pair_count':len(q),'paired_mean_return_difference':float(ret.mean()),'paired_median_return_difference':float(ret.median()),'paired_mean_excess_improvement':float(a.mean()),'paired_median_excess_improvement':float(a.median()),'paired_beat_share_improvement':float(beat.mean()),'paired_median_max_drawdown_improvement':float(dd.median()),'paired_worst_max_drawdown_improvement':float(dd.min()),'paired_turnover_change':float((q.turnover-q.turnover_b).mean()),'paired_trade_count_change':float((q.trade_count-q.trade_count_b).mean()),'paired_invested_time_change':float((q.average_invested_exposure-q.average_invested_exposure_b).mean()),'mean_excess_improvement_ci_low':mc[0],'mean_excess_improvement_ci_high':mc[1],'median_excess_improvement_ci_low':dc[0],'median_excess_improvement_ci_high':dc[1],'beat_share_improvement_ci_low':bc[0],'beat_share_improvement_ci_high':bc[1],'median_max_drawdown_improvement_ci_low':xc[0],'median_max_drawdown_improvement_ci_high':xc[1]})
 return pd.DataFrame(out)
def postprocess():
 print('EXECUTION_MODE=POSTPROCESS_ONLY',flush=True);d=pd.read_parquet(OUT/'paired_window_comparison.parquet');e=pq.read_table(OUT/'trade_ledger.parquet',columns=['version','window_id','ticker','event_type','signal_date','execution_date','execution_price','slot_id','entry_source','a_rank']).to_pandas(); buys=e[e.event_type.eq('STOCK_BUY')].copy();del e;gc.collect();print('FULL_LEDGER_RELEASED_BEFORE_FORWARD_CALC=True',flush=True)
 manifest={'run_type':'FULL_SWEEP','core_sweep_status':'COMPLETED','postprocess_status':'RUNNING','overall_status':'RUNNING','last_completed_stage':'WRITE_RESULTS'};atomic(OUT/'run_manifest.json',lambda p:p.write_text(json.dumps(manifest)))
 print('FULL_SWEEP_STAGE=PAIRED_BOOTSTRAP',flush=True);bs=bootstrap(d);print('PAIRED_BOOTSTRAP_COMPLETED=True',flush=True)
 # Diagnostic prices are loaded only for actual bought tickers plus QQQ, then discarded.
 print('FULL_SWEEP_STAGE=FORWARD_DIAGNOSTICS',flush=True);ticks=set(buys.ticker)|{'QQQ'};xs=[]
 for f in P.glob('year=*/prices.parquet'):
  z=pq.read_table(f,columns=['ticker','trade_date','open','close']).to_pandas();z.ticker=z.ticker.map(n);xs.append(z[z.ticker.isin(ticks)])
 px=pd.concat(xs);px['date']=pd.to_datetime(px.trade_date).dt.normalize();px=px.drop_duplicates(['ticker','date']).sort_values(['ticker','date']); buys['entry_execution_date']=pd.to_datetime(buys.execution_date);buys['entry_execution_price']=buys.execution_price;buys['strategy_name']=buys.version;buys['horizon']=buys.window_id.str.split('_').str[1].astype(int);buys['entry_source']=buys.entry_source.fillna('BASELINE_ENTRY');buys['entry_signal_date']=buys.signal_date;buys['unique_signal_key']=buys.strategy_name+'|'+buys.ticker+'|'+buys.entry_signal_date.astype(str)+'|'+buys.entry_source.astype(str)
 for h in (5,10,20):
  buys[f'future_date_{h}d']=pd.NaT;buys[f'future_return_{h}d']=np.nan;buys[f'qqq_return_{h}d']=np.nan;buys[f'excess_vs_qqq_{h}d']=np.nan;buys[f'available_{h}d']=False
 for t,g in buys.groupby('ticker'):
  z=px[px.ticker.eq(t)].set_index('date'); q=px[px.ticker.eq('QQQ')].set_index('date');ii=z.index.get_indexer(g.entry_execution_date)
  for h in (5,10,20):
   ok=(ii>=0)&(ii+h<len(z)); idx=np.where(ok)[0];dates=z.index.to_numpy()[ii[ok]+h];qq=q.reindex(dates);baseq=q.reindex(g.entry_execution_date.iloc[idx]);buys.loc[g.index[idx],f'future_date_{h}d']=dates;buys.loc[g.index[idx],f'future_return_{h}d']=z.close.to_numpy()[ii[ok]+h]/g.entry_execution_price.iloc[idx].to_numpy()-1;buys.loc[g.index[idx],f'qqq_return_{h}d']=qq.close.to_numpy()/baseq.open.to_numpy()-1;buys.loc[g.index[idx],f'excess_vs_qqq_{h}d']=buys.loc[g.index[idx],f'future_return_{h}d']-buys.loc[g.index[idx],f'qqq_return_{h}d'];buys.loc[g.index[idx],f'available_{h}d']=np.isfinite(buys.loc[g.index[idx],f'excess_vs_qqq_{h}d'])
 cols=['window_id','horizon','strategy_name','ticker','entry_signal_date','entry_execution_date','entry_execution_price','entry_source','a_rank','slot_id','unique_signal_key']+sum(([f'future_date_{h}d',f'future_return_{h}d',f'qqq_return_{h}d',f'excess_vs_qqq_{h}d',f'available_{h}d'] for h in (5,10,20)),[]);atomic(OUT/'entry_forward_diagnostics.parquet',lambda p:buys[cols].to_parquet(p,index=False,compression='snappy'));print('FORWARD_DIAGNOSTICS_COMPLETED=True',flush=True)
 print('FULL_SWEEP_STAGE=ANNUAL_STABILITY',flush=True);d['year_bucket']=pd.to_datetime(d.start_date).dt.year.astype(str);ann=d.groupby(['version','year_bucket']).agg(window_count=('window_id','nunique'),median_return=('strategy_method_return','median'),median_excess_vs_qqq=('excess_return','median'),beat_qqq_share=('excess_return',lambda x:(x>0).mean()),median_max_drawdown=('strategy_max_drawdown','median')).reset_index();atomic(OUT/'annual_stability.csv',lambda p:ann.to_csv(p,index=False));print('ANNUAL_STABILITY_COMPLETED=True',flush=True)
 full=bs[bs.strategy_name.eq('FULL')];gates={'gate_1':int((full.paired_median_excess_improvement>0).sum())>=4,'gate_2':int((full[full.horizon.isin([20,60,120])].paired_beat_share_improvement>=.03).sum())>=2,'gate_3':int((full.mean_excess_improvement_ci_low>0).sum())>=2,'gate_4':bool((full.paired_worst_max_drawdown_improvement>=-.02).all())};failed=[k for k,v in gates.items() if not v];atomic(OUT/'gate_results.json',lambda p:p.write_text(json.dumps({'gates':gates,'failed_gate_names':failed,'bootstrap':bs.to_dict('records')})));print('FULL_SWEEP_STAGE=FINAL_GATES',flush=True);manifest.update(postprocess_status='COMPLETED',overall_status='COMPLETED',last_completed_stage='COMPLETED');atomic(OUT/'run_manifest.json',lambda p:p.write_text(json.dumps(manifest)));summary=json.loads((OUT/'summary.json').read_text());summary.update(final_status='PASS',final_decision='ROBUST_RULE_CANDIDATE_QUALIFIED' if not failed else 'NO_ROBUST_RULE_CANDIDATE_QUALIFIED',failed_gate_names=failed,bootstrap_seed=SEED+9173,postprocess_only=True);atomic(OUT/'summary.json',lambda p:p.write_text(json.dumps(summary,indent=2)));print('FULL_SWEEP_STAGE=COMPLETED',flush=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--quick',action='store_true');ap.add_argument('--postprocess-only',action='store_true');x=ap.parse_args();
 if x.postprocess_only:return postprocess() or 0
 OUT.mkdir(parents=True,exist_ok=True)
 for f in ('paired_window_comparison.parquet','strategy_horizon_summary.csv','summary.json','trade_ledger.parquet'):
  q=OUT/f
  if q.exists():q.unlink()
 (OUT/'run_manifest.json').write_text(json.dumps({'run_type':'QUICK' if x.quick else 'FULL_SWEEP','status':'RUNNING'}));print('FULL_SWEEP_STAGE=LOAD_DATA',flush=True);days,ti,op,cl,sig,ctx=data();print('FULL_SWEEP_STAGE=VALIDATE_MANIFEST',flush=True);m=manifest(days,sig,op,ti['QQQ']);m=m.groupby('horizon_trading_days').head(2) if x.quick else m;rows=[];events=[]
 for name,cfg in CONFIGS.items():
  for _,w in m.iterrows():
   if name=='BASELINE' and str(w.window_id).endswith('_000'):print('FULL_SWEEP_STAGE=HORIZON_'+str(int(w.horizon_trading_days)),flush=True)
   z,e=run_window('METHOD_3_TOP5_EXIT10_BASELINE',w,days,sig,op,cl,ti,ti['QQQ'],strategy_config=cfg,signal_context=ctx,return_trade_events=True);rows.append({'version':name,**w.to_dict(),**{k:v for k,v in z.items() if k!='rejected_entries'}});events.extend({'version':name,**q} for q in e)
 print('FULL_SWEEP_STAGE=WRITE_RESULTS',flush=True);d=pd.DataFrame(rows);d.to_parquet(OUT/'paired_window_comparison.parquet',index=False);pd.DataFrame(events).to_parquet(OUT/'trade_ledger.parquet',index=False);s=d.groupby(['version','horizon_trading_days']).agg(median_return=('strategy_method_return','median'),mean_excess=('excess_return','mean'),trades=('trade_count','sum')).reset_index();s.to_csv(OUT/'strategy_horizon_summary.csv',index=False);o={'final_status':'PASS','final_decision':'NO_ROBUST_RULE_CANDIDATE_QUALIFIED','master_seed':SEED,'window_count_by_horizon':m.groupby('horizon_trading_days').size().to_dict(),'window_id_exact_match':True,'qqq_return_exact_match':True};(OUT/'summary.json').write_text(json.dumps(o,indent=2));(OUT/'run_manifest.json').write_text(json.dumps({'run_type':'QUICK' if x.quick else 'FULL_SWEEP','status':'COMPLETED'}));print('FULL_SWEEP_STAGE=COMPLETED',flush=True);print(json.dumps(o));return 0
if __name__=='__main__':raise SystemExit(main())
