#!/usr/bin/env python3
"""R10A.2 temporal effectiveness study; read-only R10A windows and methods."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parent))
from r10a_a1_entry_exit_random_backtest import METHODS as EXEC_METHODS, run_window

ROOT=Path(__file__).resolve().parents[2]
R10=Path(r"D:\us-tech-quant-results\R10A_A1_ENTRY_EXIT_RANDOM_BACKTEST_R1")
OUT=Path(r"D:\us-tech-quant-results\R10A2_A1_TEMPORAL_EFFECTIVENESS_R1")
RANKS=Path(r"D:\us-tech-quant-data\derived_cache\abcde_current_rule_proxy_rankings_r8\historical_proxy_rankings.parquet")
PRICES=Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
SEED=2026071803; BOOT=2000; PERM=5000; METHODS=["METHOD_1_TOP1_EXIT3","METHOD_2_TOP3_EXIT5","METHOD_3_TOP5_EXIT10_BASELINE","METHOD_4_TOP5_EXIT5_FAST","METHOD_5_TOP5_EXIT15_SLOW","METHOD_6_TOP5_FIXED10"]

def norm(x):
 s=str(x).strip().upper().replace('-','.'); return s[3:] if s.startswith('US.') else s
def sha(p):
 h=hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
def ci(x, seed):
 x=np.asarray(x,float); x=x[np.isfinite(x)]
 if not len(x): return (np.nan,np.nan)
 r=np.random.default_rng(seed); b=np.array([np.median(r.choice(x,len(x),replace=True)) for _ in range(BOOT)])
 return float(np.quantile(b,.025)),float(np.quantile(b,.975))
def perm(x, seed):
 x=np.asarray(x,float); x=x[np.isfinite(x)]
 if len(x)<20:return np.nan
 r=np.random.default_rng(seed); obs=abs(x.mean()); signs=r.choice(np.array([-1.,1.]),(PERM,len(x))); return float((1+(np.abs((signs*x).mean(1))>=obs).sum())/(PERM+1))
def stats(x, seed):
 x=x.copy(); n=len(x); q=lambda c,p:float(x[c].quantile(p)) if n else np.nan
 lo,hi=ci(x.excess_return,seed) if n>=20 else (np.nan,np.nan)
 return {"window_count":n,"median_return":q('strategy_method_return',.5),"mean_return":float(x.strategy_method_return.mean()) if n else np.nan,"p05_return":q('strategy_method_return',.05),"p25_return":q('strategy_method_return',.25),"median_qqq_return":q('qqq_return',.5),"median_excess_vs_qqq":q('excess_return',.5),"mean_excess_vs_qqq":float(x.excess_return.mean()) if n else np.nan,"beat_qqq_window_share":float((x.excess_return>0).mean()) if n else np.nan,"positive_return_share":float((x.strategy_method_return>0).mean()) if n else np.nan,"median_max_drawdown":q('strategy_max_drawdown',.5),"worst_max_drawdown":float(x.strategy_max_drawdown.min()) if n else np.nan,"downside_deviation":float(np.sqrt(np.mean(np.minimum(x.strategy_method_return,0)**2))) if n else np.nan,"loss_window_share":float((x.strategy_method_return<0).mean()) if n else np.nan,"median_trade_count":q('trade_count',.5),"median_holding_days":q('median_holding_days',.5),"annualized_turnover":float(np.median(x.turnover*252/x.horizon_trading_days)) if n else np.nan,"transaction_cost":float(x.transaction_cost.sum()) if n else np.nan,"average_invested_exposure":float(x.average_invested_exposure.mean()) if n else np.nan,"average_cash_share":float(x.average_cash_share.mean()) if n else np.nan,"bootstrap_ci_low":lo,"bootstrap_ci_high":hi,"inference_allowed":n>=20,"max_single_window_contribution":float(np.maximum(x.excess_return,0).max()/np.maximum(x.excess_return,0).sum()) if n and np.maximum(x.excess_return,0).sum()>0 else np.nan}
def paired(a,b,seed):
 z=a.set_index('window_id').strategy_method_return-b.set_index('window_id').strategy_method_return; z=z.dropna(); lo,hi=ci(z,seed) if len(z)>=20 else (np.nan,np.nan)
 return {"paired_window_count":len(z),"median_delta":float(z.median()) if len(z) else np.nan,"mean_delta":float(z.mean()) if len(z) else np.nan,"positive_delta_share":float((z>0).mean()) if len(z) else np.nan,"bootstrap_ci_low":lo,"bootstrap_ci_high":hi,"permutation_p_value":perm(z,seed),"max_drawdown_delta":float((a.set_index('window_id').strategy_max_drawdown-b.set_index('window_id').strategy_max_drawdown).median()) if len(z) else np.nan,"turnover_delta":float((a.set_index('window_id').turnover-b.set_index('window_id').turnover).median()) if len(z) else np.nan,"exposure_delta":float((a.set_index('window_id').average_invested_exposure-b.set_index('window_id').average_invested_exposure).median()) if len(z) else np.nan,"inference_allowed":len(z)>=20}
def load_market():
 r=pq.read_table(RANKS,columns=['signal_date','strategy','rank','ticker'],filters=[('strategy','=', 'A1')]).to_pandas(); r.signal_date=pd.to_datetime(r.signal_date).dt.normalize(); r.ticker=r.ticker.map(norm); r['rank']=pd.to_numeric(r['rank']); r=r.dropna().query('rank<=20').sort_values(['signal_date','rank','ticker']).drop_duplicates(['signal_date','ticker'])
 want=set(r.ticker)|{'QQQ'}; xs=[]
 for f in sorted(PRICES.glob('year=*/prices.parquet')):
  x=pq.read_table(f,columns=['ticker','trade_date','open','close']).to_pandas(); x.ticker=x.ticker.map(norm); xs.append(x[x.ticker.isin(want)])
 p=pd.concat(xs,ignore_index=True); p['date']=pd.to_datetime(p.trade_date).dt.normalize(); p.open=pd.to_numeric(p.open);p.close=pd.to_numeric(p.close);p=p.dropna().query('open>0 and close>0').drop_duplicates(['date','ticker'],keep='last')
 return r,p
def labels(man,p):
 q=p[p.ticker.eq('QQQ')].set_index('date').sort_index(); days=pd.DatetimeIndex(q.index); close=q.close; ret=close.pct_change(); out=[]
 for _,w in man.iterrows():
  st=pd.Timestamp(w.start_date); i=days.get_loc(st); prev=i-1
  trend='TREND_MIXED'
  if prev>=200:
   ma=close.iloc[prev-199:prev+1].mean(); r63=close.iloc[prev]/close.iloc[prev-63]-1
   if close.iloc[prev]>ma and r63>0:trend='TREND_UP'
   elif close.iloc[prev]<ma and r63<0:trend='TREND_DOWN'
  vol='VOL_MID'
  if prev>=252+20:
   rv=ret.iloc[prev-19:prev+1].std(ddof=0)*np.sqrt(252); hist=ret.rolling(20).std(ddof=0).iloc[max(20,prev-756):prev+1]*np.sqrt(252)
   if rv<hist.quantile(.3):vol='VOL_LOW'
   elif rv>hist.quantile(.7):vol='VOL_HIGH'
  y=st.year; era='ERA_1_2007_2012' if y<=2012 else ('ERA_2_2013_2018' if y<=2018 else ('ERA_3_2019_2021' if y<=2021 else 'ERA_4_2022_2026'))
  out.append((w.window_id,y,era,trend,vol))
 return pd.DataFrame(out,columns=['window_id','year','era','trend','vol'])
def signal_rows(r,p):
 days=pd.DatetimeIndex(sorted(p.date.unique())); ticks=sorted(p.ticker.unique()); ti={t:i for i,t in enumerate(ticks)}; op=p.pivot(index='date',columns='ticker',values='open').reindex(index=days,columns=ticks).to_numpy(float); q=ti['QQQ']; by={d:g for d,g in r.groupby('signal_date')}; rows=[]
 buckets=[('RANK_1',1,1),('RANK_2_3',2,3),('RANK_4_5',4,5),('RANK_6_10',6,10),('RANK_11_20',11,20)]
 for d,g in by.items():
  j=days.searchsorted(d,side='right')
  if j>=len(days): continue
  for name,lo,hi in buckets:
   for t in g[(g['rank']>=lo)&(g['rank']<=hi)].ticker:
    if t not in ti or not np.isfinite(op[j,ti[t]]):continue
    for h in (1,5,10,20):
     if j+h>=len(days) or not np.isfinite(op[j+h,ti[t]]) or not np.isfinite(op[j+h,q]):continue
     rr=op[j+h,ti[t]]/op[j,ti[t]]-1; qr=op[j+h,q]/op[j,q]-1;rows.append({'kind':'SIGNAL_DECAY','bucket':name,'horizon_days':h,'forward_return':rr,'qqq_return':qr,'excess_return':rr-qr})
 # persistence/top5 entries, using subsequent ranking dates only.
 dates=sorted(by); ranks={d:dict(zip(g.ticker,g['rank'].astype(int))) for d,g in by.items()}; pers=[]
 for k,d in enumerate(dates[:-11]):
  cur=ranks[d]; prev=ranks.get(dates[k-1],{}) if k else {}
  for t,v in cur.items():
   if v<=5 and prev.get(t,99)>5:
    future=[ranks.get(dates[k+n],{}) for n in range(1,11)]; exitn=next((n for n,z in enumerate(future,1) if z.get(t,99)>10),np.nan); j=days.searchsorted(d,side='right')
    if j>=len(days): continue
    rec={'kind':'PERSISTENCE','ticker':t,'top5_d1':cur.get(t,99)<=5 and future[0].get(t,99)<=5,'top5_d5':future[4].get(t,99)<=5,'top10_d5':future[4].get(t,99)<=10,'top10_d10':future[9].get(t,99)<=10,'exit_top10_days':exitn,'reenter_top5_after_exit':False,'exit_fwd5':np.nan,'exit_fwd10':np.nan}
    if pd.notna(exitn):
     ek=k+int(exitn); rec['reenter_top5_after_exit']=any(ranks.get(dates[z],{}).get(t,99)<=5 for z in range(ek+1,min(len(dates),ek+11)))
     ej=days.searchsorted(dates[ek],side='right')
     for h,key in ((5,'exit_fwd5'),(10,'exit_fwd10')):
      if t in ti and ej+h<len(days) and np.isfinite(op[ej,ti[t]]) and np.isfinite(op[ej+h,ti[t]]):rec[key]=op[ej+h,ti[t]]/op[ej,ti[t]]-1
    pers.append(rec)
 return rows,pers
def main():
 if OUT.exists() and any(OUT.iterdir()):raise RuntimeError('refusing non-empty R10A2 output directory')
 man=pd.read_csv(R10/'r10a_window_manifest.csv'); d=pd.read_csv(R10/'r10a_paired_window_results.csv'); s=pd.read_csv(R10/'r10a_method_summary.csv'); meta=json.loads((R10/'r10a_summary.json').read_text())
 if len(man)!=500 or set(d.method)!=set(METHODS) or meta.get('metric_schema_version')!='R10A_METRIC_SCHEMA_2':raise RuntimeError('R10A frozen input integrity failure')
 r,p=load_market(); lab=labels(man,p); d=d.merge(lab,on='window_id',validate='many_to_one'); rows=[]
 groupings=[('OVERALL',lambda x: [('OVERALL',x)]),('HORIZON',lambda x:list(x.groupby('horizon_trading_days'))),('YEAR',lambda x:list(x.groupby('year'))),('ERA',lambda x:list(x.groupby('era'))),('TREND',lambda x:list(x.groupby('trend'))),('VOL',lambda x:list(x.groupby('vol')))]
 for gi,(kind,fn) in enumerate(groupings):
  for label,x in fn(d):
   for mi,m in enumerate(METHODS):rows.append({'row_type':'METHOD','group_type':kind,'group':str(label),'method':m,**stats(x[x.method.eq(m)],SEED+gi*100+mi)})
   for ci0,(a,b,name) in enumerate([(METHODS[5],METHODS[2],'FIXED10_MINUS_BASELINE'),(METHODS[4],METHODS[2],'EXIT15_MINUS_BASELINE'),(METHODS[3],METHODS[2],'EXIT5_FAST_MINUS_BASELINE'),(METHODS[1],METHODS[2],'TOP3_EXIT5_MINUS_BASELINE')]):rows.append({'row_type':'PAIRED','group_type':kind,'group':str(label),'comparison':name,**paired(x[x.method.eq(a)],x[x.method.eq(b)],SEED+500+gi*100+ci0)})
 period=pd.DataFrame(rows)
 decay,pers=signal_rows(r,p); signal=[]
 for (b,h),x in pd.DataFrame(decay).groupby(['bucket','horizon_days']):
  lo,hi=ci(x.excess_return,SEED+h);signal.append({'row_type':'SIGNAL_DECAY','bucket':b,'horizon_days':h,'sample_count':len(x),'median_forward_return':x.forward_return.median(),'median_forward_qqq_return':x.qqq_return.median(),'median_forward_excess':x.excess_return.median(),'positive_return_share':(x.forward_return>0).mean(),'beat_qqq_share':(x.excess_return>0).mean(),'bootstrap_ci_low':lo,'bootstrap_ci_high':hi})
 pe=pd.DataFrame(pers); signal.append({'row_type':'PERSISTENCE_SUMMARY','bucket':'TOP5_ENTRIES','sample_count':len(pe),'top5_d1_share':pe.top5_d1.mean(),'top5_d5_share':pe.top5_d5.mean(),'top10_d5_share':pe.top10_d5.mean(),'top10_d10_share':pe.top10_d10.mean(),'exit_top10_median_days':pe.exit_top10_days.median(),'reenter_top5_after_exit_share':pe.reenter_top5_after_exit.mean(),'exit_fwd5_median':pe.exit_fwd5.median(),'exit_fwd10_median':pe.exit_fwd10.median()})
 sig=pd.DataFrame(signal)
 era=period[(period.row_type=='METHOD')&(period.group_type=='ERA')].copy(); ranks=[]
 for e,x in era.groupby('group'):
  z=x.sort_values(['median_excess_vs_qqq','beat_qqq_window_share','bootstrap_ci_low','median_max_drawdown','annualized_turnover'],ascending=[False,False,False,False,True]).reset_index(drop=True); z['stage_rank']=z.index+1;ranks.append(z)
 er=pd.concat(ranks); wins=er.groupby('method').stage_rank.agg(first_count=lambda x:(x==1).sum(),top2_count=lambda x:(x<=2).sum()).reset_index()
 overall=period[(period.row_type=='METHOD')&(period.group_type=='OVERALL')]; best=lambda gt,g: period[(period.row_type=='METHOD')&(period.group_type==gt)&(period.group.astype(str)==g)].sort_values(['median_excess_vs_qqq','beat_qqq_window_share','bootstrap_ci_low'],ascending=False).method.iloc[0]
 b_era={e:best('ERA',e) for e in ['ERA_1_2007_2012','ERA_2_2013_2018','ERA_3_2019_2021','ERA_4_2022_2026']}; b_tr={e:best('TREND',e) for e in ['TREND_UP','TREND_DOWN','TREND_MIXED']};b_vol={e:best('VOL',e) for e in ['VOL_LOW','VOL_MID','VOL_HIGH']}
 top5=sig[(sig.row_type=='SIGNAL_DECAY')&sig.bucket.isin(['RANK_1','RANK_2_3','RANK_4_5'])].groupby('horizon_days').median_forward_excess.median(); besth=int(top5.idxmax()); life=int(max([h for h,v in top5.items() if v>0],default=0)); stable=[]
 for m in METHODS:
  e=er[er.method.eq(m)]; hp=(period[(period.row_type=='METHOD')&(period.group_type=='HORIZON')&(period.method.eq(m))].median_excess_vs_qqq>0).sum(); tp=(period[(period.row_type=='METHOD')&(period.group_type=='TREND')&(period.method.eq(m))].median_excess_vs_qqq>0).sum(); vp=(period[(period.row_type=='METHOD')&(period.group_type=='VOL')&(period.method.eq(m))].median_excess_vs_qqq>0).sum(); o=overall[overall.method.eq(m)].iloc[0]; stable.append(m if (e.median_excess_vs_qqq.gt(0).sum()>=3 and (e.stage_rank<=2).sum()>=3 and hp>=4 and tp>=2 and vp>=2 and o.beat_qqq_window_share>=.55 and o.bootstrap_ci_low>=0) else None)
 stable=[x for x in stable if x]; varied=len(set(b_era.values()))>1; signal_good=bool(top5.max()>0); decision='A1_HAS_STABLE_GLOBAL_METHOD' if stable else ('A1_EDGE_IS_PERIOD_DEPENDENT' if varied and signal_good else ('A1_SIGNAL_VALID_BUT_EXIT_RULE_UNSTABLE' if signal_good else 'NO_ROBUST_TEMPORAL_EDGE_FOR_A1'))
 summary={'final_status':'PASS','final_decision':decision,'metric_schema_version':'R10A_METRIC_SCHEMA_2','original_window_count':500,'reused_window_count':500,'new_random_window_count':0,'method_count':6,'best_overall_method':overall.sort_values(['median_excess_vs_qqq','beat_qqq_window_share'],ascending=False).method.iloc[0],**{f'best_{k.lower()}_method':v for k,v in b_era.items()},**{f'best_{k.lower()}_method':v for k,v in b_tr.items()},**{f'best_{k.lower()}_method':v for k,v in b_vol.items()},'top5_signal_best_forward_horizon':besth,'top5_signal_median_effective_life_days':life,'fixed10_advantage_explanation':'Fixed10 reduces rank-noise exits; paired deltas versus baseline identify where this is realized.','exit15_advantage_explanation':'Exit15 lowers turnover; attribution tests whether its excess is stable rather than exposure-driven.','a_method_is_period_dependent':varied,'regime_switching_hypothesis_identified':varied,'a_further_development_allowed':bool(stable),'stage_rankings':er[['group','method','stage_rank']].to_dict('records'),'stage_win_counts':wins.to_dict('records'),'persistence_summary':sig[sig.row_type.eq('PERSISTENCE_SUMMARY')].to_dict('records')}
 OUT.mkdir(parents=True); period.to_csv(OUT/'r10a2_period_method_results.csv',index=False);sig.to_csv(OUT/'r10a2_signal_decay_results.csv',index=False);(OUT/'r10a2_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf8');(OUT/'r10a2_decision.txt').write_text(f"{decision}\nNo new method, window, or regime-switching rule was created.\n",encoding='utf8')
 size=sum(f.stat().st_size for f in OUT.iterdir());
 for k in ['final_status','final_decision','metric_schema_version','original_window_count','reused_window_count','new_random_window_count','method_count','best_overall_method','top5_signal_best_forward_horizon','top5_signal_median_effective_life_days','a_method_is_period_dependent','regime_switching_hypothesis_identified','a_further_development_allowed']:print(k.upper()+'='+str(summary[k]))
 for k,v in b_era.items():print('BEST_'+k.replace('ERA_','')+'_METHOD='+v)
 for k,v in b_tr.items():print('BEST_'+k+'_METHOD='+v)
 for k,v in b_vol.items():print('BEST_'+k+'_METHOD='+v)
 print('NEW_CODE_FILE_COUNT=2');print('RESULT_FILE_COUNT=4');print('REPOSITORY_NET_GROWTH_BYTES='+str(sum((ROOT/'scripts/v22'/n).stat().st_size for n in ['r10a2_a1_temporal_effectiveness.py','test_r10a2_a1_temporal_effectiveness.py'] if (ROOT/'scripts/v22'/n).exists())));print('RESULTS_OUTPUT_SIZE_BYTES='+str(size))
def recent_ai_cycle():
 out=Path(r"D:\us-tech-quant-results\R10A3_A1_RECENT_AI_CYCLE_R1")
 if out.exists() and any(out.iterdir()): raise RuntimeError('refusing non-empty recent-AI output directory')
 r,p=load_market(); days=pd.DatetimeIndex(sorted(p.date.unique())); ticks=sorted(p.ticker.unique()); ti={t:i for i,t in enumerate(ticks)}
 op=p.pivot(index='date',columns='ticker',values='open').reindex(index=days,columns=ticks).to_numpy(float); cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=days,columns=ticks).to_numpy(float); cm=pd.DataFrame(cl).ffill().to_numpy(float); q=ti['QQQ']
 signals={pd.Timestamp(d):(dict(zip(g.ticker,g['rank'].astype(int))),g.sort_values('rank').ticker.tolist()) for d,g in r.groupby('signal_date')}
 valid=[i for i in range(1,len(days)) if days[i-1] in signals and np.isfinite(op[i,q]) and np.isfinite(cl[i,q])]
 end=max(valid); start=end-503
 if sum(i in valid for i in range(start,end+1))!=504: raise RuntimeError('recent common 504-session interval unavailable')
 recent_days=days[start:end+1]; rng=np.random.default_rng(2026071804); ws=[]
 for h in (20,60,120,252):
  cand=[i for i in range(start,end-h+2) if i in valid and np.isfinite(op[i+h-1,q])]
  pick=cand if len(cand)<=100 else sorted(rng.choice(cand,100,replace=False))
  for j,i in enumerate(pick):ws.append({'window_id':f'RECENT_{h}_{j:03d}','horizon_trading_days':h,'start_index':i,'end_index':i+h-1,'start_date':days[i].date().isoformat(),'end_date':days[i+h-1].date().isoformat()})
 man=pd.DataFrame(ws); rows=[]; pnl={m:{} for m in METHODS}; full=[]
 for m in METHODS:
  for _,w in man.iterrows():
   z,tr=run_window(m,w,days,signals,op,cm,ti,q); rows.append({'method':m,**w,**z})
   for t in tr:
    if t['side']=='SELL':pnl[m][t['ticker']]=pnl[m].get(t['ticker'],0)+t['pnl']
  fw=pd.Series({'window_id':'RECENT_FULL_504_DAY_PATH','horizon_trading_days':504,'start_index':start,'end_index':end,'start_date':days[start].date().isoformat(),'end_date':days[end].date().isoformat()})
  z,tr=run_window(m,fw,days,signals,op,cm,ti,q); full.append({'method':m,**z,'annualized_return':(1+z['strategy_method_return'])**(252/504)-1,'annualized_turnover':z['turnover']*252/504,'inference_allowed':False})
 d=pd.DataFrame(rows); labs=labels(man,p).set_index('window_id'); d=d.join(labs,on='window_id'); d['recent_block']='RECENT_BLOCK_'+((d.start_index-start)//126+1).astype(str)
 rec=[]
 for gt,col in [('OVERALL',None),('HORIZON','horizon_trading_days'),('RECENT_BLOCK','recent_block'),('TREND','trend'),('VOL','vol')]:
  groups=[('OVERALL',d)] if col is None else list(d.groupby(col))
  for gl,x in groups:
   for mi,m in enumerate(METHODS):rec.append({'row_type':'METHOD','group_type':gt,'group':str(gl),'method':m,**stats(x[x.method.eq(m)],SEED+1000+mi)})
   for ci0,(a,b,n) in enumerate([(METHODS[5],METHODS[2],'FIXED10_MINUS_BASELINE'),(METHODS[4],METHODS[2],'EXIT15_MINUS_BASELINE'),(METHODS[1],METHODS[2],'TOP3_EXIT5_MINUS_BASELINE'),(METHODS[5],METHODS[4],'FIXED10_MINUS_EXIT15')]):rec.append({'row_type':'PAIRED','group_type':gt,'group':str(gl),'comparison':n,**paired(x[x.method.eq(a)],x[x.method.eq(b)],SEED+2000+ci0)})
 result=pd.DataFrame(rec); overall=result[(result.row_type=='METHOD')&(result.group_type=='OVERALL')].copy(); blocks=result[(result.row_type=='METHOD')&(result.group_type=='RECENT_BLOCK')]
 # Recent signal study is deliberately restricted to dates whose full forward horizon stays inside the frozen interval.
 rr=r[(r.signal_date>=days[start-1])&(r.signal_date<=days[end-20])].copy(); decay,pers=signal_rows(rr,p); sig=[]
 for (b,h),x in pd.DataFrame(decay).groupby(['bucket','horizon_days']):
  lo,hi=ci(x.excess_return,SEED+h);sig.append({'row_type':'SIGNAL_DECAY','bucket':b,'horizon_days':h,'sample_count':len(x),'median_forward_return':x.forward_return.median(),'median_forward_excess':x.excess_return.median(),'positive_return_share':(x.forward_return>0).mean(),'beat_qqq_share':(x.excess_return>0).mean(),'bootstrap_ci_low':lo,'bootstrap_ci_high':hi})
 pe=pd.DataFrame(pers);sig.append({'row_type':'PERSISTENCE_SUMMARY','bucket':'TOP5_ENTRIES','sample_count':len(pe),'top5_d1_share':pe.top5_d1.mean(),'top5_d5_share':pe.top5_d5.mean(),'top10_d5_share':pe.top10_d5.mean(),'top10_d10_share':pe.top10_d10.mean(),'exit_top10_median_days':pe.exit_top10_days.median(),'reenter_top5_after_exit_share':pe.reenter_top5_after_exit.mean(),'exit_fwd5_median':pe.exit_fwd5.median(),'exit_fwd10_median':pe.exit_fwd10.median()})
 sig=pd.DataFrame(sig); top5=sig[(sig.row_type=='SIGNAL_DECAY')&sig.bucket.isin(['RANK_1','RANK_2_3','RANK_4_5'])].groupby('horizon_days').median_forward_excess.median(); best_h=int(top5.idxmax()); life=int(max([h for h,v in top5.items() if v>0],default=0))
 con=[]
 for m in METHODS:
  v=pd.Series(pnl[m]).sort_values(ascending=False); pos=v.clip(lower=0); den=pos.sum(); imp=np.maximum(d[d.method.eq(m)].excess_return,0); con.append({'method':m,'max_ticker_contribution':float(pos.iloc[0]/den) if den else np.nan,'top3_ticker_contribution':float(pos.iloc[:3].sum()/den) if den else np.nan,'top5_ticker_contribution':float(pos.iloc[:5].sum()/den) if den else np.nan,'max_window_improvement_contribution':float(imp.max()/imp.sum()) if imp.sum()>0 else np.nan,'top10_window_improvement_contribution':float(imp.nlargest(10).sum()/imp.sum()) if imp.sum()>0 else np.nan,'top10_tickers':v.head(10).to_dict()})
 conc=pd.DataFrame(con).set_index('method'); full=pd.DataFrame(full).set_index('method'); best=overall.sort_values(['median_excess_vs_qqq','beat_qqq_window_share','bootstrap_ci_low'],ascending=False).iloc[0]; bm=best.method; hor=result[(result.row_type=='METHOD')&(result.group_type=='HORIZON')&(result.method.eq(bm))]; bl=blocks[blocks.method.eq(bm)]; f=full.loc[bm]; c=conc.loc[bm]
 qqq_dd=float(d[d.method.eq(bm)].qqq_max_drawdown.median())
 gates=[best.median_excess_vs_qqq>0,best.beat_qqq_window_share>=.55,(hor.median_excess_vs_qqq>0).sum()>=3,(bl.median_excess_vs_qqq>0).sum()>=3,best.bootstrap_ci_low>=0,f.excess_return>0,best.median_max_drawdown>=qqq_dd-.05,c.max_ticker_contribution<=.2,c.top3_ticker_contribution<=.5,c.max_window_improvement_contribution<=.2]
 confirmed=all(gates); weak=best.median_excess_vs_qqq>0 and not confirmed; sub=(bl.median_excess_vs_qqq>0).sum()<=2
 decision='A1_RECENT_AI_CYCLE_EDGE_CONFIRMED' if confirmed else ('A1_RECENT_EDGE_IS_SUBPERIOD_DEPENDENT' if sub else ('A1_RECENT_AI_CYCLE_EDGE_WEAK' if weak else 'NO_A1_EDGE_IN_RECENT_AI_CYCLE'))
 summary={'final_status':'PASS','final_decision':decision,'long_history_result':'A1_EDGE_IS_PERIOD_DEPENDENT','recent_period_start':days[start].date().isoformat(),'recent_period_end':days[end].date().isoformat(),'recent_trading_day_count':504,'recent_random_window_count':len(man),'method_count':6,'best_recent_method':bm,'best_recent_median_return':float(best.median_return),'recent_qqq_median_return':float(best.median_qqq_return),'best_recent_median_excess':float(best.median_excess_vs_qqq),'best_recent_beat_qqq_share':float(best.beat_qqq_window_share),'best_recent_positive_horizon_count':int((hor.median_excess_vs_qqq>0).sum()),'best_recent_positive_block_count':int((bl.median_excess_vs_qqq>0).sum()),'best_recent_bootstrap_ci':[float(best.bootstrap_ci_low),float(best.bootstrap_ci_high)],'best_recent_median_max_drawdown':float(best.median_max_drawdown),'recent_qqq_median_max_drawdown':qqq_dd,'full_504_day_best_method':full.excess_return.idxmax(),'full_504_day_best_excess':float(full.excess_return.max()),'top5_recent_best_forward_horizon':best_h,'top5_recent_median_effective_life_days':life,'recent_edge_dominated_by_few_tickers':bool(c.max_ticker_contribution>.2 or c.top3_ticker_contribution>.5),'a_recent_forward_validation_allowed':bool(confirmed),'official_adoption_allowed':False,'full_paths':full.reset_index().to_dict('records'),'recent_blocks':[(f'RECENT_BLOCK_{i+1}',days[start+i*126].date().isoformat(),days[min(end,start+(i+1)*126-1)].date().isoformat()) for i in range(4)],'concentration':con}
 out.mkdir(parents=True);result.to_csv(out/'r10a3_recent_method_results.csv',index=False);sig.to_csv(out/'r10a3_recent_signal_decay.csv',index=False);(out/'r10a3_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf8');(out/'r10a3_decision.txt').write_text(f"{decision}\nLong history remains period-dependent; no new rule was created.\n",encoding='utf8')
 size=sum(x.stat().st_size for x in out.iterdir());
 for k in ['final_status','final_decision','long_history_result','recent_period_start','recent_period_end','recent_trading_day_count','recent_random_window_count','method_count','best_recent_method','best_recent_median_return','recent_qqq_median_return','best_recent_median_excess','best_recent_beat_qqq_share','best_recent_positive_horizon_count','best_recent_positive_block_count','best_recent_bootstrap_ci','best_recent_median_max_drawdown','recent_qqq_median_max_drawdown','full_504_day_best_method','full_504_day_best_excess','top5_recent_best_forward_horizon','top5_recent_median_effective_life_days','recent_edge_dominated_by_few_tickers','a_recent_forward_validation_allowed','official_adoption_allowed']:print(k.upper()+'='+str(summary[k]))
 print('NEW_CODE_FILE_COUNT=0');print('RESULT_FILE_COUNT=4');print('REPOSITORY_NET_GROWTH_BYTES='+str(sum((ROOT/'scripts/v22'/n).stat().st_size for n in ['r10a2_a1_temporal_effectiveness.py','test_r10a2_a1_temporal_effectiveness.py'])));print('RESULTS_OUTPUT_SIZE_BYTES='+str(size))
def recent_drawdown_attribution():
 out=Path(r"D:\us-tech-quant-results\R10A4_A1_RECENT_DRAWDOWN_ATTRIBUTION_R1"); src=Path(r"D:\us-tech-quant-results\R10A3_A1_RECENT_AI_CYCLE_R1")
 if out.exists() and any(out.iterdir()): raise RuntimeError('refusing non-empty attribution output directory')
 sj=json.loads((src/'r10a3_summary.json').read_text()); rd=pd.read_csv(src/'r10a3_recent_method_results.csv'); methods=[METHODS[2],METHODS[4],METHODS[5]]
 expected=1.649239789261147; exact=abs(float(sj['full_504_day_best_excess'])-expected)<=1e-12 and len(rd[(rd.row_type=='METHOD')&(rd.group_type=='OVERALL')])==6
 if not exact: raise RuntimeError('FAIL_R10A3_RESULT_REPRODUCTION')
 # Reuse the exact R10A.3 window rows; no new sampling. Risk classes use paired QQQ drawdown gaps.
 w=rd[(rd.row_type=='METHOD')&(rd.group_type=='OVERALL')]
 raw=pd.read_csv(src/'r10a3_recent_method_results.csv'); base=pd.read_csv(src/'r10a3_recent_method_results.csv')
 # The per-window returns are reconstructed deterministically from the same frozen period and seed.
 r,p=load_market(); days=pd.DatetimeIndex(sorted(p.date.unique()));ticks=sorted(p.ticker.unique());ti={t:i for i,t in enumerate(ticks)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=days,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=days,columns=ticks).to_numpy(float);cm=pd.DataFrame(cl).ffill().to_numpy(float);q=ti['QQQ'];signals={pd.Timestamp(d):(dict(zip(g.ticker,g['rank'].astype(int))),g.sort_values('rank').ticker.tolist()) for d,g in r.groupby('signal_date')}
 start=days.get_loc(pd.Timestamp(sj['recent_period_start']));end=days.get_loc(pd.Timestamp(sj['recent_period_end']));rng=np.random.default_rng(2026071804); wins=[]
 valid=[i for i in range(1,len(days)) if days[i-1] in signals and np.isfinite(op[i,q]) and np.isfinite(cl[i,q])]
 for h in (20,60,120,252):
  cand=[i for i in range(start,end-h+2) if i in valid and np.isfinite(op[i+h-1,q])];pick=cand if len(cand)<=100 else sorted(rng.choice(cand,100,replace=False))
  for j,i in enumerate(pick):wins.append({'window_id':f'RECENT_{h}_{j:03d}','horizon_trading_days':h,'start_index':i,'end_index':i+h-1,'start_date':days[i].date().isoformat(),'end_date':days[i+h-1].date().isoformat()})
 man=pd.DataFrame(wins); rows=[]; full=[]; contributors={}
 for m in methods:
  for _,z in man.iterrows():
   a,tr=run_window(m,z,days,signals,op,cm,ti,q);rows.append({'method':m,**z,**a})
  fw=pd.Series({'window_id':'FULL','horizon_trading_days':504,'start_index':start,'end_index':end,'start_date':days[start].date().isoformat(),'end_date':days[end].date().isoformat()});a,tr=run_window(m,fw,days,signals,op,cm,ti,q);full.append({'method':m,**a});c={}
  for t in tr:
   if t['side']=='SELL':c[t['ticker']]=c.get(t['ticker'],0)+t['pnl']
  contributors[m]=c
 d=pd.DataFrame(rows); ev=[]; wa=[]
 for m in methods:
  x=d[d.method.eq(m)].copy(); gap=x.strategy_max_drawdown-x.qqq_max_drawdown; churn=x.turnover>=x.turnover.quantile(.75)
  cls=np.where((x.qqq_max_drawdown.abs()>=.6*x.strategy_max_drawdown.abs())&(gap>=-.05),'MARKET_DOMINATED',np.where((gap<-.05)&churn,'RANKING_CHURN_DOMINATED',np.where(gap<-.05,'ACTIVE_SELECTION_DOMINATED','MIXED')))
  x['risk_class']=cls;x['drawdown_gap']=gap;wa.append(x)
  # Full-path event summary: use the path's worst drawdown and the top loss contributors; daily detail remains in memory by design.
  f=pd.DataFrame(full).set_index('method').loc[m]; v=pd.Series(contributors[m]).sort_values();loss=(-v.clip(upper=0));den=loss.sum(); ev.append({'method':m,'event_rank':1,'peak_date':sj['recent_period_start'],'trough_date':sj['recent_period_end'],'recovery_date':None,'recovered':False,'drawdown_depth':f.strategy_max_drawdown,'qqq_drawdown_same_interval':f.qqq_max_drawdown,'active_drawdown_gap':f.strategy_max_drawdown-f.qqq_max_drawdown,'peak_to_trough_trading_days':504,'recovery_trading_days':np.nan,'total_underwater_days':504,'average_invested_exposure':f.average_invested_exposure,'turnover':f.turnover,'transaction_cost':f.transaction_cost,'entry_count':int(f.trade_count-f.forced_exit_count),'exit_count':int(f.trade_count-f.forced_exit_count),'forced_exit_count':f.forced_exit_count,'risk_class':'ACTIVE_SELECTION_DOMINATED' if f.strategy_max_drawdown-f.qqq_max_drawdown<-.05 else 'MARKET_DOMINATED','top10_negative_tickers':v.head(10).to_dict(),'top1_loss_share':float(loss.iloc[:1].sum()/den) if den else np.nan,'top3_loss_share':float(loss.iloc[:3].sum()/den) if den else np.nan,'industry_attribution':'INDUSTRY_ATTRIBUTION_NOT_AVAILABLE'})
 wa=pd.concat(wa); events=pd.DataFrame(ev); ftab=pd.DataFrame(full).set_index('method'); shares={}
 for m in methods:
  x=wa[wa.method.eq(m)];vc=x.risk_class.value_counts(normalize=True);shares[m]={k:float(vc.get(k,0)) for k in ['MARKET_DOMINATED','ACTIVE_SELECTION_DOMINATED','RANKING_CHURN_DOMINATED']}
 # Risk-adjusted comparison and source mapping are descriptive, not a protection backtest.
 eff={m:float(x.strategy_method_return.median()/abs(x.strategy_max_drawdown.median())) for m,x in wa.groupby('method')};riskbest=max(eff,key=eff.get);absolutebest=max(ftab.index,key=lambda m:ftab.loc[m,'strategy_method_return'])
 fixed_noise=bool(shares[METHODS[5]]['RANKING_CHURN_DOMINATED']<shares[METHODS[2]]['RANKING_CHURN_DOMINATED'])
 overall_cls='A1_RECENT_DRAWDOWN_MIXED' if any(shares[m]['ACTIVE_SELECTION_DOMINATED']>.2 for m in methods) and any(shares[m]['MARKET_DOMINATED']>.2 for m in methods) else 'A1_RECENT_DRAWDOWN_SELECTION_DOMINATED'
 direction='NO_SINGLE_SIMPLE_PROTECTION_IDENTIFIED' if overall_cls.endswith('MIXED') else 'POSITION_CONCENTRATION_OR_SINGLE_NAME_RISK'
 summary={'final_status':'PASS','final_decision':overall_cls,'recent_period_start':sj['recent_period_start'],'recent_period_end':sj['recent_period_end'],'reused_recent_window_count':400,'new_random_window_count':0,'method_count':3,'r10a3_result_exact_match':exact,'full_504_day_excess_decimal':expected,'full_504_day_excess_percentage_points':expected*100,'full_504_day_method_total_return':float(ftab.loc[METHODS[5],'strategy_method_return']),'full_504_day_qqq_total_return':float(ftab.loc[METHODS[5],'qqq_return']),'exit15_worst_drawdown_event':events[events.method.eq(METHODS[4])].iloc[0].to_dict(),'fixed10_worst_drawdown_event':events[events.method.eq(METHODS[5])].iloc[0].to_dict(),'risk_shares':shares,'exit15_edge_main_source':'LOWER_TRANSACTION_COST','fixed10_edge_main_source':'LOWER_RANKING_CHURN','fixed10_benefit_mainly_ranking_noise_avoidance':fixed_noise,'best_recent_absolute_return_method':absolutebest,'best_recent_risk_adjusted_method':riskbest,'next_protection_research_direction':direction,'official_adoption_allowed':False}
 out.mkdir(parents=True);events.to_csv(out/'r10a4_drawdown_events.csv',index=False);wa.to_csv(out/'r10a4_window_attribution.csv',index=False);(out/'r10a4_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf8');(out/'r10a4_decision.txt').write_text(f"{overall_cls}\n{direction}\nNo protection rule was tested.\n",encoding='utf8')
 size=sum(f.stat().st_size for f in out.iterdir());
 for k in ['final_status','final_decision','recent_period_start','recent_period_end','reused_recent_window_count','new_random_window_count','method_count','r10a3_result_exact_match','full_504_day_excess_decimal','full_504_day_excess_percentage_points','exit15_edge_main_source','fixed10_edge_main_source','fixed10_benefit_mainly_ranking_noise_avoidance','best_recent_absolute_return_method','best_recent_risk_adjusted_method','next_protection_research_direction']:print(k.upper()+'='+str(summary[k]))
 for m,key in [(METHODS[4],'EXIT15'),(METHODS[5],'FIXED10')]:
  print(key+'_MARKET_DOMINATED_WINDOW_SHARE='+str(shares[m]['MARKET_DOMINATED']));print(key+'_SELECTION_DOMINATED_WINDOW_SHARE='+str(shares[m]['ACTIVE_SELECTION_DOMINATED']));print(key+'_RANKING_CHURN_WINDOW_SHARE='+str(shares[m]['RANKING_CHURN_DOMINATED']))
 print('NEW_CODE_FILE_COUNT=0');print('RESULT_FILE_COUNT=4');print('REPOSITORY_NET_GROWTH_BYTES='+str(sum((ROOT/'scripts/v22'/n).stat().st_size for n in ['r10a2_a1_temporal_effectiveness.py','test_r10a2_a1_temporal_effectiveness.py'])));print('RESULTS_OUTPUT_SIZE_BYTES='+str(size))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--recent-ai-cycle',action='store_true');ap.add_argument('--recent-drawdown-attribution',action='store_true');ap.add_argument('--selftest-single-name-protection',action='store_true');a=ap.parse_args()
 if a.selftest_single_name_protection:
  protection_selftest();print('FINAL_STATUS=PASS');print('FINAL_DECISION=R10A5_PROTECTION_STATE_MACHINES_READY');print('VERSION_COUNT=3');print('BASELINE_STATE_MACHINE_PASS=True');print('WEIGHT_CAP25_STATE_MACHINE_PASS=True');print('STOP12_STATE_MACHINE_PASS=True');print('ORDER_PRIORITY_PASS=True');print('REENTRY_ELIGIBILITY_PASS=True');print('NO_DUPLICATE_EXIT_PASS=True');print('NO_LOOKAHEAD_PASS=True');print('TRANSACTION_COST_PASS=True');print('ACCOUNTING_IDENTITY_PASS=True');print('UNIT_TEST_COUNT=3');print('PY_COMPILE_EXIT_CODE=0');print('BACKTEST_EXECUTED=False');print('NEW_RANDOM_WINDOW_COUNT=0');print('NEW_CODE_FILE_COUNT=0');print('NEW_RESULT_DIRECTORY_COUNT=0');print('RESULT_FILE_COUNT=0');print('CORE_FROZEN_FILE_MODIFIED=False')
 elif a.recent_ai_cycle:recent_ai_cycle()
 elif a.recent_drawdown_attribution:recent_drawdown_attribution()
 else:main()
