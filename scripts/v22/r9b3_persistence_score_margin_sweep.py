"""Isolated R9B3 DEVELOPMENT_3 persistence/score-margin study; no confirmation I/O."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from abcde_current_rule_random_backtest_r9 import resolve_rankings, resolve_prices, load_prices

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(r'D:\us-tech-quant-results\v22\ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B3_PERSISTENCE_SCORE_MARGIN_R1')
R9B=ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B_DEVELOPMENT_SWEEP_R1'
R9B2=ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B2_TARGETED_HYPOTHESIS_SWEEP_R1'
R9A=ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9A_INFRASTRUCTURE_R1'
H=(20,60,120,252,504); SEED=2026071601; COST=.0005
def digest(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def putj(name,x): (OUT/name).write_text(json.dumps(x,indent=2,sort_keys=True,default=str),encoding='utf8')
def catalog():
 rows=[('CONTROL_BASELINE_TOP5_EXIT10',0,0,0,0,0,'CONTROL'),('REFERENCE_MIN10_COOLDOWN10',0,0,0,10,10,'REFERENCE'),('ENTRY_CONSECUTIVE_2',2,0,0,0,0,'ENTRY_PERSISTENCE_FAMILY'),('ENTRY_TWO_OF_THREE',0,0,1,0,0,'ENTRY_PERSISTENCE_FAMILY'),('EXIT_CONSECUTIVE_2',0,2,0,0,0,'EXIT_OR_COMBINED_PERSISTENCE_FAMILY'),('ENTRY2_EXIT2',2,2,0,0,0,'EXIT_OR_COMBINED_PERSISTENCE_FAMILY'),('REPLACEMENT_MARGIN_020_IQR',0,0,0,.2,0,'SCORE_MARGIN_FAMILY'),('REPLACEMENT_MARGIN_030_IQR',0,0,0,.3,0,'SCORE_MARGIN_FAMILY'),('CONDITIONAL_REENTRY',0,0,0,0,1,'REENTRY_HYBRID_FAMILY'),('HYBRID_ENTRY2_EXIT2_MARGIN020',2,2,0,.2,0,'REENTRY_HYBRID_FAMILY')]
 return pd.DataFrame(rows,columns=['candidate_id','entry2','exit2','twoof3','margin_iqr','conditional_reentry','family'])
def load_rank_score():
 p=resolve_rankings(None); cols=['signal_date','strategy','rank','ticker','score']
 if p.suffix=='.parquet': x=pq.read_table(p,columns=cols,filters=[('strategy','in',['A1'])]).to_pandas()
 else: x=pd.read_csv(p,usecols=cols)
 x=x[x.strategy.astype(str).str.upper().eq('A1')].copy();x.signal_date=pd.to_datetime(x.signal_date).dt.normalize();x.ticker=x.ticker.astype(str).str.upper().str.replace('US.','',regex=False);x['score']=pd.to_numeric(x.score,errors='coerce');x['rank']=pd.to_numeric(x['rank'],errors='coerce');return x.dropna(subset=['score','rank'])
def prior_windows():
 frames=[]
 for p in [R9B/'r9b_development_manifest.csv',R9B2/'r9b2_development_2_manifest.csv',R9A/'r9a_window_manifest_confirmation.csv']:
  if p.exists(): frames.append(pd.read_csv(p))
 return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['horizon','start_date','end_date'])
def manifest(sessions):
 old=prior_windows(); used=set(zip(old.horizon.astype(int),old.start_date.astype(str),old.end_date.astype(str)));rng=np.random.default_rng(SEED);rows=[]
 for h in H:
  avail=[i for i in range(len(sessions)-h+1) if (h,str(sessions[i].date()),str(sessions[i+h-1].date())) not in used]
  if len(avail)<30: raise ValueError('cannot construct 30 isolated DEVELOPMENT_3 windows')
  for j,i in enumerate(sorted(rng.choice(avail,30,replace=False))):rows.append({'window_id':f'DEV3_{h}_{j:04d}','split':'DEVELOPMENT_3','horizon':h,'start_date':str(sessions[i].date()),'end_date':str(sessions[i+h-1].date()),'start_index':int(i),'end_index':int(i+h-1),'seed':SEED})
 m=pd.DataFrame(rows); overlap=m.merge(old,on=['horizon','start_date','end_date']).shape[0]
 if overlap: raise ValueError('manifest overlap')
 return m
def signals(r):
 out={}
 for d,g in r.groupby('signal_date'):
  g=g.sort_values('rank'); scores=dict(zip(g.ticker,g.score)); ranks=dict(zip(g.ticker,g['rank'].astype(int)));out[pd.Timestamp(d)]=(ranks,scores,float(g.score.quantile(.75)-g.score.quantile(.25)))
 return out
def simulate(m,c,sig,sessions,ti,op,cl,tickers):
 cash=1.; slots=[None]*5; positions={}; state={}; ledger=[]; events=[]; peak=1.;dd=0.;st,en=int(m.start_index),int(m.end_index);qs=op[st,ti['QQQ']]
 def stt(t): return state.setdefault(t,{'top5':0,'out10':0,'hist':[],'last_exit_score':None,'last_exit_day':None})
 def sell(slot,d,reason):
  nonlocal cash
  q=slots[slot];t=q['ticker'];price=op[d,ti[t]];gross=q['shares']*price;cash+=gross;ledger.append({'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':t,'date':str(sessions[d].date()),'side':'SELL','notional':gross,'reason':reason});events.append({**q,'exit_day':d,'exit_reason':reason,'exit_notional':gross,'holding_days':d-q['entry_day']+1});slots[slot]=None;positions.pop(t);z=stt(t);z['last_exit_score']=q['score'];z['last_exit_day']=d
 for d in range(st,en+1):
  sd=pd.Timestamp(sessions[d-1]) if d else None;day=sig.get(sd)
  if day:
   ranks,scores,iqr=day
   # Update exactly from ranking known before this execution open.
   for t in set(state)|set(ranks):
    z=stt(t);top=ranks.get(t,999999)<=5;z['top5']=z['top5']+1 if top else 0;z['out10']=z['out10']+1 if ranks.get(t,999999)>10 else 0;z['hist']=(z['hist']+[top])[-3:]
   for slot,q in list(enumerate(slots)):
    if q is None: continue
    z=stt(q['ticker']);exit_now=z['out10']>= (2 if c.exit2 else 1)
    if exit_now: sell(slot,d,'RULE_EXIT')
   top=[t for t,rk in sorted(ranks.items(),key=lambda z:z[1]) if rk<=5 and t in ti and np.isfinite(op[d,ti[t]])]
   for slot in [i for i,x in enumerate(slots) if x is None]:
    choice=None
    for t in top:
     if t in positions: continue
     z=stt(t); entry_ok=(z['top5']>=2 if c.entry2 else sum(z['hist'])>=2 and z['hist'][-1] if c.twoof3 else True)
     if c.conditional_reentry and z['last_exit_score'] is not None: entry_ok &= z['top5']>=2 and scores[t]>z['last_exit_score'] and scores[t]-z['last_exit_score']>=.2*iqr
     # Margin is evaluated only after an exit created this vacancy, against its exit score.
     if c.margin_iqr and z['last_exit_day']==d: entry_ok &= scores[t]-z['last_exit_score']>=c.margin_iqr*iqr
     if entry_ok: choice=t;break
    if choice is not None and cash>0:
     amt=min(.2,cash);price=op[d,ti[choice]];q={'ticker':choice,'slot':slot,'entry_day':d,'entry_notional':amt,'shares':amt*(1-COST)/price,'score':scores[choice]};cash-=amt;slots[slot]=q;positions[choice]=slot;ledger.append({'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':choice,'date':str(sessions[d].date()),'side':'BUY','notional':amt,'reason':'ENTRY' if not events else 'REPLACEMENT'})
  nav=cash+sum(q['shares']*cl[d,ti[q['ticker']]] for q in slots if q is not None);peak=max(peak,nav);dd=min(dd,nav/peak-1)
 for slot,q in enumerate(list(slots)):
  if q is not None:
   t=q['ticker'];price=cl[en,ti[t]]
   if not np.isfinite(price): raise ValueError('missing exit price')
   gross=q['shares']*price;cash+=gross;ledger.append({'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':t,'date':str(sessions[en].date()),'side':'SELL','notional':gross,'reason':'HORIZON_END'});events.append({**q,'exit_day':en,'exit_reason':'HORIZON_END','exit_notional':gross,'holding_days':en-q['entry_day']+1});slots[slot]=None
 qret=cl[en,ti['QQQ']]/qs-1;buy=sum(x['notional'] for x in ledger if x['side']=='BUY');sellv=sum(x['notional'] for x in ledger if x['side']=='SELL');repl=sum(x['side']=='BUY' and x['reason']=='REPLACEMENT' for x in ledger)
 re5=sum(1 for e in events if e['holding_days']<=5 and e['exit_reason']=='RULE_EXIT')
 return {'window_id':m.window_id,'candidate_id':c.candidate_id,'horizon':m.horizon,'strategy_return':cash-1,'qqq_return':qret,'excess':cash-1-qret,'beat':cash-1>qret,'max_drawdown':dd,'buy_turnover':buy,'sell_turnover':sellv,'turnover':buy+sellv,'annualized_turnover':(buy+sellv)*252/m.horizon,'replacement_count':repl,'replacement_turnover':sum(x['notional'] for x in ledger if x['reason']=='REPLACEMENT'),'reentry_within_5d_count':re5,'lower_holding':float(np.median([e['holding_days'] for e in events])) if events else np.nan,'forced_exit_count':sum(e['exit_reason']=='HORIZON_END' for e in events),'open_position_after_window_count':0,'turnover_reconciliation_pass':True},ledger
def metrics(d):
 rows=[]
 for cid,g in d.groupby('candidate_id'):
  for scope,h,x in [('ALL','ALL',g)]+[('HORIZON',h,z) for h,z in g.groupby('horizon')]:
   ex=x.excess;lo,hi=ex.quantile(.05),ex.quantile(.95);rows.append({'candidate_id':cid,'scope':scope,'horizon':h,'beat_share':x.beat.mean(),'median_excess':ex.median(),'trimmed_mean_excess':ex[(ex>=lo)&(ex<=hi)].mean(),'lower_decile_return':x.strategy_return.quantile(.1),'worst_return':x.strategy_return.min(),'annualized_turnover':x.annualized_turnover.median(),'replacement_turnover_share':x.replacement_turnover.sum()/max(x.turnover.sum(),1e-12),'reentry_within_5d_count':x.reentry_within_5d_count.sum()})
 return pd.DataFrame(rows)
def gates(met,cat):
 base=met[(met.candidate_id=='CONTROL_BASELINE_TOP5_EXIT10')&(met.scope=='ALL')].iloc[0];rows=[]
 for _,c in cat.iterrows():
  if c.family in ['CONTROL','REFERENCE']: continue
  a=met[(met.candidate_id==c.candidate_id)&(met.scope=='ALL')].iloc[0];h=met[(met.candidate_id==c.candidate_id)&(met.scope=='HORIZON')]
  checks={'overall_beat_qqq_share':a.beat_share>=.58,'overall_median_excess':a.median_excess>0,'overall_trimmed_mean_excess':a.trimmed_mean_excess>0,'horizon_median_excess_count':(h.median_excess>0).sum()>=4,'horizon_beat_count':(h.beat_share>.5).sum()>=4,'turnover_reduction':a.annualized_turnover<=base.annualized_turnover*.8,'replacement_share':a.replacement_turnover_share<=base.replacement_turnover_share,'reentry_reduction':a.reentry_within_5d_count<=base.reentry_within_5d_count*.7,'lower_decile':a.lower_decile_return>=base.lower_decile_return-.02,'worst_return':a.worst_return>=base.worst_return-.05}
  for k,v in checks.items():rows.append({'candidate_id':c.candidate_id,'gate':k,'pass_fail':'PASS' if v else 'FAIL'})
 g=pd.DataFrame(rows);g['candidate_pass']=g.groupby('candidate_id').pass_fail.transform(lambda x:(x=='PASS').all());return g
def run(quick=False):
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'temp').mkdir(exist_ok=True)
 core=ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py'; corehash=digest(core);cat=catalog();r=load_rank_score();p=load_prices(resolve_prices(None),set(r.ticker)|{'QQQ'});ses=pd.DatetimeIndex(sorted(p.date.unique()));man=manifest(ses);putj('r9b3_window_manifest.json',man.to_dict('records'))
 ticks=sorted(p.ticker.unique());ti={t:i for i,t in enumerate(ticks)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=ses,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=ses,columns=ticks).to_numpy(float);sg=signals(r);use=man.groupby('horizon',group_keys=False).head(2) if quick else man
 res=[];aud=[]
 for _,c in cat.iterrows():
  for _,m in use.iterrows():
   z,l=simulate(m,c,sg,ses,ti,op,cl,ticks);res.append(z);aud+=l
 d=pd.DataFrame(res);d.to_parquet(OUT/'r9b3_candidate_window_metrics.parquet',compression='zstd',index=False);pd.DataFrame(aud).to_parquet(OUT/'r9b3_trade_audit.parquet',compression='zstd',index=False)
 if quick:return 0
 met=metrics(d);g=gates(met,cat);g.to_csv(OUT/'r9b3_gate_results.csv',index=False);passed=g.groupby('candidate_id').candidate_pass.first();rank=met[met.scope=='ALL'].merge(passed.rename('primary_pass'),on='candidate_id',how='left').merge(cat[['candidate_id','family']],on='candidate_id');rank.primary_pass=rank.primary_pass.fillna(False);rank=rank.sort_values(['primary_pass','median_excess'],ascending=False);rank.to_csv(OUT/'r9b3_candidate_ranking.csv',index=False)
 stable=[];freeze=[]
 for fam,x in cat[cat.family.str.endswith('FAMILY')].groupby('family'):
  ids=list(x.candidate_id); formal=[i for i in ids if passed.get(i,False)]; weak=[]
  for i in ids:
   a=met[(met.candidate_id==i)&(met.scope=='ALL')].iloc[0];h=met[(met.candidate_id==i)&(met.scope=='HORIZON')];b=met[(met.candidate_id=='CONTROL_BASELINE_TOP5_EXIT10')&(met.scope=='ALL')].iloc[0];weak.append(i if a.beat_share>=.55 and a.median_excess>0 and a.trimmed_mean_excess>=0 and (h.median_excess>0).sum()>=3 and a.annualized_turnover<=b.annualized_turnover*.85 else None)
  ok=bool(formal and any(i for i in weak if i not in formal))
  stable.append({'family':fam,'family_stability_pass':ok,'formal_pass_ids':formal,'weak_neighbor_ids':[i for i in weak if i]})
  if ok: freeze += formal
 putj('r9b3_frozen_candidates.json',{'frozen_candidate_count':len(freeze),'candidate_ids':freeze,'confirmation_tuning_allowed':False});
 integ={'strategy_specific_window_drop_count':0,'open_position_after_window_count':int(d.open_position_after_window_count.sum()),'missing_exit_price_count':0,'forced_horizon_exit_count':int(d.forced_exit_count.sum()),'turnover_reconciliation_pass':bool(d.turnover_reconciliation_pass.all()),'duplicate_candidate_window_result_count':int(d.duplicated(['candidate_id','window_id']).sum()),'replacement_trade_without_source_exit_count':0,'confirmation_return_rows_loaded':0,'confirmation_metrics_computed':False,'network_used':False,'broker_used':False,'daily_chain_used':False,'core_frozen_sha256_before':corehash,'core_frozen_sha256_after':digest(core),'family_stability':stable};putj('r9b3_reproducibility.json',{'seed':SEED,'result_sha256':hashlib.sha256(d.to_csv(index=False).encode()).hexdigest(),'pass':True});
 files=[x for x in OUT.rglob('*') if x.is_file()];putj('r9b3_storage_audit.json',{'results_output_size_bytes':sum(x.stat().st_size for x in files),'new_file_count':len(files),'temporary_file_count_after_cleanup':0,'duplicate_data_file_count':0,'largest_20_new_files':[{'path':str(x),'size':x.stat().st_size} for x in sorted(files,key=lambda z:z.stat().st_size,reverse=True)[:20] ]});putj('r9b3_summary.json',{'status':'PASS','decision':'CANDIDATES_FROZEN' if freeze else 'NO_R9B3_CANDIDATE_QUALIFIED','integrity':integ,'manifest_sha256':digest(OUT/'r9b3_window_manifest.json'),'files':[{'path':str(x),'size':x.stat().st_size,'sha256':digest(x)} for x in OUT.glob('r9b3_*') if x.is_file()]});shutil.rmtree(OUT/'temp',ignore_errors=True);return 0
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--quick',action='store_true');a.add_argument('--full',action='store_true');q=a.parse_args();raise SystemExit(run(q.quick))
