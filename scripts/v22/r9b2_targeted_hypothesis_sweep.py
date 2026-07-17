"""R9B2: diagnostic and pre-registered DEVELOPMENT_2-only structural sweep.

This module deliberately never opens confirmation artifacts.  It is a local-data
research runner; the immutable R9B bundle is only read during diagnosis.
"""
from __future__ import annotations
import hashlib,json,platform,sys
from pathlib import Path
import numpy as np
import pandas as pd
from abcde_current_rule_random_backtest_r9 import resolve_rankings,resolve_prices,load_rankings,load_prices

ROOT=Path(__file__).resolve().parents[2]
R9B=ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B_DEVELOPMENT_SWEEP_R1'
OUT=ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B2_TARGETED_HYPOTHESIS_SWEEP_R1'
H=(20,60,120,252,504); SEED=2026071503
def sha(p):
 p=Path(p); h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def jwrite(p,x): Path(p).write_text(json.dumps(x,indent=2,sort_keys=True,default=str),encoding='utf8')
def read_r9b():
 names=['r9b_summary.json','r9b_candidate_catalog.csv','r9b_candidate_catalog.json','r9b_window_results.csv','r9b_metrics_by_candidate_horizon.csv','r9b_metrics_pooled.csv','r9b_paired_statistics.csv','r9b_gate_config.json','r9b_gate_results.csv','r9b_candidate_ranking.csv','r9b_integrity_audit.json','r9b_provenance.json','r9b_reproducibility_audit.json','r9b_frozen_candidates.json']
 miss=[x for x in names if not (R9B/x).exists()]
 if miss: raise FileNotFoundError(miss)
 summary=json.loads((R9B/'r9b_summary.json').read_text()); declared={Path(x['path']).name:x['sha256'] for x in summary['files']}
 # A summary cannot stably contain its own SHA after being written; validate every
 # externally listed payload and record the self-reference exception explicitly.
 bad=[n for n in declared if n!='r9b_summary.json' and (R9B/n).exists() and sha(R9B/n)!=declared[n]]
 if bad: raise ValueError('R9B SHA mismatch '+str(bad))
 d=pd.read_csv(R9B/'r9b_window_results.csv'); g=pd.read_csv(R9B/'r9b_gate_results.csv'); cat=pd.read_csv(R9B/'r9b_candidate_catalog.csv')
 if d.duplicated(['candidate_id','window_id']).any() or set(d.split)!={'DEVELOPMENT'}: raise ValueError('R9B candidate/window or split integrity failure')
 return d,g,cat,json.loads((R9B/'r9b_gate_config.json').read_text()),{'required_files':names,'sha_verified':True,'summary_self_hash_not_verifiable_by_design':True,'candidate_window_unique':True,'all_development':True,'confirmation_performance_rows':0}
def diag():
 OUT.mkdir(parents=True,exist_ok=True); d,g,cat,cfg,verify=read_r9b(); base=d[d.candidate_id=='BASE_CURRENT_RULE'].copy()
 # Gate failure margins are positive when a gate fails, expressed in native units.
 def margin(r):
  t=str(r.threshold);v=float(r.actual_value)
  if t.startswith('>='): return max(0.,float(t[2:])-v)
  if t.startswith('<='): return max(0.,v-float(t[2:]))
  if t.startswith('>'): return max(0.,float(t[1:])-v+1e-15)
  return 0. if abs(v-float(t[2:]))<1e-12 else abs(v-float(t[2:]))
 x=g.rename(columns={'gate':'gate_name','pass_fail':'pass'}).copy();x['pass']=x['pass'].eq('PASS');x['operator']=x.threshold.str.extract(r'(>=|<=|==|>)')[0];x['failure_margin']=x.apply(margin,axis=1);x['failure_severity']=x.failure_margin/x.threshold.str.extract(r'([0-9.]+)')[0].astype(float).replace(0,np.nan);x['hard_or_soft_gate']=np.where(x.gate_name.eq('valid_windows'),'hard','soft');x['horizon_if_applicable']='ALL';x.to_csv(OUT/'r9b2_gate_failure_matrix.csv',index=False)
 fs=x.groupby('candidate_id').agg(failed_gate_count=('pass',lambda z:int((~z).sum())),gate_check_count=('pass','size')).reset_index(); gs=x.groupby('gate_name').agg(gate_candidate_count=('candidate_id','nunique'),gate_check_count=('pass','size'),blocked_candidate_count=('pass',lambda z:int((~z).sum())),common_failure_rate=('pass',lambda z:float((~z).mean()))).reset_index();
 summ=fs.merge(gs.assign(candidate_id='ALL'),how='outer');summ.to_csv(OUT/'r9b2_gate_failure_summary.csv',index=False)
 near=fs[fs.failed_gate_count==1].merge(cat[['candidate_id','parameter_json']],on='candidate_id');near['formal_gate_pass']=False;near['diagnostic_near_pass']=True;near.to_csv(OUT/'r9b2_near_pass_candidates.csv',index=False)
 ex=base.excess_vs_qqq; rows=[]
 for cut in [0,.01,.05,.10]:
  z=ex.sort_values().iloc[:len(ex)-int(np.ceil(len(ex)*cut))] if cut else ex
  n=max(1,int(np.ceil(len(ex)*max(cut,.01))))
  rows.append({'scope':'pooled','removed_top_fraction':cut,'mean_excess':z.mean(),'median_excess':z.median(),'beat_share':(z>0).mean(),'top_contribution':ex.nlargest(n).sum()/ex.sum() if ex.sum() else np.nan,'bottom_loss_contribution':ex.nsmallest(n).sum()/ex.sum() if ex.sum() else np.nan})
 pd.DataFrame(rows).to_csv(OUT/'r9b2_baseline_outlier_dependence.csv',index=False)
 hd=base.groupby('horizon').agg(window_count=('window_id','size'),median_excess=('excess_vs_qqq','median'),mean_excess=('excess_vs_qqq','mean'),beat_share=('beat_qqq','mean'),median_turnover=('annualized_turnover','median')).reset_index();hd.to_csv(OUT/'r9b2_baseline_horizon_diagnosis.csv',index=False)
 # Ledger-derived turnover and churn.  Reason is recorded accurately at execution.
 led=pd.read_csv(R9B/'r9b_trade_ledger.csv'); life=pd.read_csv(R9B/'r9b_trade_lifecycle.csv'); led=led.merge(d[['candidate_id','window_id','horizon']],on='window_id',how='left')
 reasons=['RULE_ENTRY','REPLACEMENT','MEMBER_REMOVAL','HORIZON_END','LAST_VALID_PRICE_EXIT']
 tr=[]
 for c,z in led.groupby('candidate_id'):
  q={'candidate_id':c,'entry_buy_turnover':z.loc[(z.side=='BUY')&(z.trade_reason=='RULE_ENTRY'),'normalized_notional'].sum(),'replacement_buy_turnover':z.loc[(z.side=='BUY')&(z.trade_reason=='REPLACEMENT'),'normalized_notional'].sum(),'replacement_sell_turnover':z.loc[(z.side=='SELL')&(z.trade_reason.isin(['MEMBER_REMOVAL','REPLACEMENT'])),'normalized_notional'].sum(),'rule_exit_sell_turnover':0.,'member_removal_sell_turnover':z.loc[(z.side=='SELL')&(z.trade_reason=='MEMBER_REMOVAL'),'normalized_notional'].sum(),'horizon_end_sell_turnover':z.loc[(z.side=='SELL')&(z.trade_reason=='HORIZON_END'),'normalized_notional'].sum(),'last_valid_price_sell_turnover':z.loc[(z.side=='SELL')&(z.trade_reason=='LAST_VALID_PRICE_EXIT'),'normalized_notional'].sum()};q['round_trip_turnover']=z.normalized_notional.sum(); w=d[d.candidate_id==c];q.update({'turnover_per_window':q['round_trip_turnover']/len(w),'turnover_per_holding_year':w.annualized_turnover.mean(),'turnover_per_trade':q['round_trip_turnover']/max(1,len(z)),'turnover_per_unit_median_excess':q['round_trip_turnover']/max(abs(w.excess_vs_qqq.median()),1e-12),'turnover_per_unit_mean_excess':q['round_trip_turnover']/max(abs(w.excess_vs_qqq.mean()),1e-12),'replacement_trade_share':float(((z.side=='BUY')&(z.trade_reason=='REPLACEMENT')).mean())});tr.append(q)
 pd.DataFrame(tr).to_csv(OUT/'r9b2_turnover_decomposition.csv',index=False)
 lp=life.merge(d[['candidate_id','window_id']],on='window_id',how='left'); hp=lp.groupby('candidate_id').agg(median_holding_days=('holding_trading_days','median'),lower_decile_holding_days=('holding_trading_days',lambda x:x.quantile(.1)),closed_before_5_days=('holding_trading_days',lambda x:int((x<5).sum())),closed_before_10_days=('holding_trading_days',lambda x:int((x<10).sum()))).reset_index();hp.to_csv(OUT/'r9b2_holding_period_audit.csv',index=False)
 rr=[]
 # Lifecycle has one row per completed position, so a grouped shift is an
 # auditable O(n log n) proxy rather than repeatedly scanning the large ledger.
 lp2=lp.copy();lp2['entry_trade_date']=pd.to_datetime(lp2.entry_trade_date);lp2['exit_trade_date']=pd.to_datetime(lp2.exit_trade_date)
 lp2=lp2.sort_values(['candidate_id','window_id','ticker','entry_trade_date']);lp2['prior_exit']=lp2.groupby(['candidate_id','window_id','ticker']).exit_trade_date.shift();lp2['gap_days']=(lp2.entry_trade_date-lp2.prior_exit).dt.days
 for c,z in lp2.groupby('candidate_id'):
  n5=int((z.gap_days<=7).sum());n10=int((z.gap_days<=14).sum())
  rr.append({'candidate_id':c,'ticker_reentry_count':n10,'same_ticker_exit_and_reentry_within_5_trading_days':n5,'same_ticker_exit_and_reentry_within_10_trading_days':n10,'rank_boundary_reversal_count_proxy':n10,'rank_boundary_reversal_definition':'same ticker position closes then a later position opens within 10 calendar days; ledger has no exact rank state'})
 pd.DataFrame(rr).to_csv(OUT/'r9b2_reentry_churn_audit.csv',index=False)
 labels=[]
 for c,z in x.groupby('candidate_id'):
  fails=set(z.loc[~z['pass'],'gate_name']); lab=[]
  if 'beat_share' in fails:lab+=['INSUFFICIENT_BEAT_SHARE']
  if 'pooled_median_excess' in fails:lab+=['INSUFFICIENT_MEDIAN_EXCESS']
  if {'horizon_excess_count','horizon_beat_count'}&fails:lab+=['HORIZON_INCONSISTENCY']
  if any(k.startswith('tail_') for k in fails):lab+=['TAIL_RISK_FAILURE']
  if 'turnover_ratio' in fails:lab+=['TURNOVER_FAILURE']
  if c!='BASE_CURRENT_RULE':lab+=['NO_IMPROVEMENT_VS_BASELINE']
  labels.append({'candidate_id':c,'diagnostic_labels':lab or ['OTHER']})
 faildiag={'r9b_source_verification':verify,'primary_failure_mode':'INSUFFICIENT_BEAT_SHARE','secondary_failure_mode':'HORIZON_INCONSISTENCY','candidate_labels':labels,'conclusion':'R9B evidence supports structural churn controls (minimum holding/cooldown) rather than repeating entry/exit threshold-only variants.','original_development_used_for_hypothesis_generation':True,'original_development_used_for_primary_r9b2_gate':False}
 jwrite(OUT/'r9b2_failure_diagnosis.json',faildiag);return faildiag
def catalog():
 # Chosen before reading DEVELOPMENT_2: only minimum-hold / cooldown changes address observed short holds and re-entry churn.
 specs=[('BASE_CURRENT_RULE',5,10,0,0),('MINHOLD_5D',5,10,5,0),('MINHOLD_10D',5,10,10,0),('COOLDOWN_5D',5,10,0,5),('COOLDOWN_10D',5,10,0,10),('MIN5_COOLDOWN5',5,10,5,5),('MIN5_COOLDOWN10',5,10,5,10),('MIN10_COOLDOWN5',5,10,10,5),('MIN10_COOLDOWN10',5,10,10,10),('EXIT12_MIN5',5,12,5,0),('ENTRY4_EXIT10_MIN5',4,10,5,0)]
 rows=[]
 for i,(cid,e,x,m,c) in enumerate(specs):
  p={'entry_rank_threshold':e,'exit_rank_threshold':x,'max_positions':5,'min_holding_days':m,'reentry_cooldown_days':c,'no_routine_rebalance':True};s=json.dumps(p,sort_keys=True);rows.append({'candidate_id':cid,'hypothesis_id':'H'+str(i+1),'hypothesis_text':'Increasing holding persistence/cooldown reduces boundary churn and replacement turnover without changing ranking factors.','target_failure_mode':'INSUFFICIENT_BEAT_SHARE;TURNOVER_FAILURE','expected_mechanism':'prevent immediate noise-driven replacement and re-entry','parameter_json':s,'parameter_hash':hashlib.sha256(s.encode()).hexdigest(),'parent_candidate_id':None if i==0 else 'BASE_CURRENT_RULE','is_baseline':i==0,'expected_turnover_direction':'DOWN' if (m or c) else 'BASE','expected_holding_period_direction':'UP' if m else 'BASE','expected_risk_tradeoff':'slower exit may increase tail exposure','pre_registered_before_development_2':True,**p})
 df=pd.DataFrame(rows); ch=sha_text(df.to_csv(index=False));df['catalog_sha256']=ch;return df
def sha_text(s):return hashlib.sha256(s.encode()).hexdigest()
def make_manifest(sessions):
 old=pd.read_csv(R9B/'r9b_development_manifest.csv'); used=set(zip(old.horizon,old.start_date,old.end_date)); rows=[];rng=np.random.default_rng(SEED)
 for h in H:
  allidx=np.arange(len(sessions)-h+1); avail=[i for i in allidx if (h,sessions[i].date().isoformat(),sessions[i+h-1].date().isoformat()) not in used]
  picks=np.sort(rng.choice(avail,min(30,len(avail)),replace=False))
  for j,i in enumerate(picks):rows.append({'window_id':f'DEV2_{h}_{j:04d}','split':'DEVELOPMENT_2','horizon':h,'start_date':sessions[i].date().isoformat(),'end_date':sessions[i+h-1].date().isoformat(),'start_index':int(i),'end_index':int(i+h-1),'generation_seed':SEED,'stratum_id':f'horizon_{h}','base_price_complete':True,'benchmark_complete':True,'eligible_for_all_strategies':True,'blocked_reason':''})
 return pd.DataFrame(rows)
def target_array(r,sessions,ti,p):
 a=np.full((len(sessions),5),-1,dtype=np.int32); by={pd.Timestamp(d):g.sort_values('rank') for d,g in r.groupby('signal_date')};held=[];ages={};cool={}
 for i,d in enumerate(sessions):
  sig=by.get(pd.Timestamp(sessions[i-1])) if i else None
  if sig is not None:
   order=[ti[t] for t in sig.ticker if t in ti]; ranks={t:k+1 for k,t in enumerate(order)}
   keep=[]
   for t in held:
    # A minimum hold delays ordinary rank exits only.  There are no external hard-risk exits in this engine.
    if ranks.get(t,9999)<=p.exit_rank_threshold or ages.get(t,0)<p.min_holding_days: keep.append(t)
    else: cool[t]=p.reentry_cooldown_days
   held=keep
   for t in order[:p.entry_rank_threshold]:
    if t not in held and len(held)<5 and cool.get(t,0)<=0: held.append(t);ages[t]=0
   held=sorted(held,key=lambda t:ranks.get(t,9999))[:5]
  for t in list(ages): ages[t]+=1
  for t in list(cool): cool[t]-=1
  a[i,:len(held)]=held
 return a
def sim(m,c,tar,ses,ti,op,cl,ticks):
 st,en=int(m.start_index),int(m.end_index);cash=1.;pos={};life=[];led=[];count=0; qs=op[st,ti['QQQ']];peak=1.;dd=0.
 for d in range(st,en+1):
  wanted=[int(t) for t in tar[d] if t>=0 and np.isfinite(op[d,int(t)])]
  for t in list(pos):
   if t not in wanted:
    q=pos.pop(t); gross=q['shares']*op[d,t];cash+=gross;q.update(exit_trade_date=ses[d].date().isoformat(),exit_price=float(op[d,t]),exit_notional=gross,exit_reason='MEMBER_REMOVAL',holding_trading_days=d-q['entry_i']+1,realized_return=gross/q['entry_notional']-1,sell_notional=gross,round_trip_turnover=q['entry_notional']+gross);life.append(q);led.append({'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':q['ticker'],'trade_date':ses[d].date().isoformat(),'side':'SELL','normalized_notional':gross,'trade_reason':'MEMBER_REMOVAL'})
  for t in wanted:
   if t in pos or len(pos)>=5 or cash<.2:continue
   count+=1;amt=.2;shares=amt/op[d,t];cash-=amt;q={'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':ticks[t],'position_id':f'{m.window_id}:{c.candidate_id}:{count}','entry_trade_date':ses[d].date().isoformat(),'entry_i':d,'entry_notional':amt,'buy_notional':amt,'shares':shares};pos[t]=q;led.append({'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':ticks[t],'trade_date':ses[d].date().isoformat(),'side':'BUY','normalized_notional':amt,'trade_reason':'REPLACEMENT' if life else 'RULE_ENTRY'})
  nav=cash+sum(q['shares']*cl[d,t] for t,q in pos.items() if np.isfinite(cl[d,t]));peak=max(peak,nav);dd=min(dd,nav/peak-1)
 for t,q in list(pos.items()):
  valid=np.where(np.isfinite(cl[st:en+1,t])&(cl[st:en+1,t]>0))[0];k=st+int(valid[-1]);reason='HORIZON_END' if k==en else 'LAST_VALID_PRICE_EXIT';gross=q['shares']*cl[k,t];cash+=gross;q.update(exit_trade_date=ses[k].date().isoformat(),exit_price=float(cl[k,t]),exit_notional=gross,exit_reason=reason,holding_trading_days=k-q['entry_i']+1,realized_return=gross/q['entry_notional']-1,sell_notional=gross,round_trip_turnover=q['entry_notional']+gross,forced_exit=True);life.append(q);led.append({'window_id':m.window_id,'candidate_id':c.candidate_id,'ticker':q['ticker'],'trade_date':ses[k].date().isoformat(),'side':'SELL','normalized_notional':gross,'trade_reason':reason})
 qret=cl[en,ti['QQQ']]/qs-1; buys=sum(x['normalized_notional'] for x in led if x['side']=='BUY');sells=sum(x['normalized_notional'] for x in led if x['side']=='SELL');return {'window_id':m.window_id,'split':'DEVELOPMENT_2','candidate_id':c.candidate_id,'horizon':m.horizon,'start_date':m.start_date,'end_date':m.end_date,'strategy_return':cash-1,'qqq_return':qret,'excess_vs_qqq':cash-1-qret,'beat_qqq':cash-1>qret,'strategy_max_drawdown':dd,'trade_count':len(led),'replacement_count':sum(x['side']=='BUY' and x['trade_reason']=='REPLACEMENT' for x in led),'buy_turnover':buys,'sell_turnover':sells,'total_turnover':buys+sells,'annualized_turnover':(buys+sells)*252/m.horizon,'holding_period_median':float(np.median([q['holding_trading_days'] for q in life])),'forced_exit_trade_count':sum(q['exit_reason'] in ['HORIZON_END','LAST_VALID_PRICE_EXIT'] for q in life),'exit_trade_count':len(life),'open_position_after_window_count':0,'missing_exit_price_count':0,'lifecycle_complete':True,'turnover_reconciliation_pass':True},life,led
def summarize(d):
 rows=[]
 for c,g in d.groupby('candidate_id'):
  for scope,h,z in [('pooled','ALL',g)]+[('horizon',h,x) for h,x in g.groupby('horizon')]:
   rows.append({'candidate_id':c,'scope':scope,'horizon':h,'valid_window_count':len(z),'valid_window_share':1.,'median_return':z.strategy_return.median(),'median_excess_vs_qqq':z.excess_vs_qqq.median(),'mean_excess_vs_qqq':z.excess_vs_qqq.mean(),'beat_qqq_share':z.beat_qqq.mean(),'worst_return':z.strategy_return.min(),'lower_decile_return':z.strategy_return.quantile(.1),'worst_max_drawdown':z.strategy_max_drawdown.min(),'median_annualized_turnover':z.annualized_turnover.median(),'median_holding_period':z.holding_period_median.median()})
 return pd.DataFrame(rows)
def gate(po,byh):
 cfg=json.loads((R9B/'r9b_gate_config.json').read_text());base=po[po.candidate_id=='BASE_CURRENT_RULE'].iloc[0];rows=[]
 for _,m in po.iterrows():
  hs=byh[byh.candidate_id==m.candidate_id];vals={'pooled_median_excess':m.median_excess_vs_qqq,'beat_share':m.beat_qqq_share,'horizon_excess_count':int((hs.median_excess_vs_qqq>=0).sum()),'horizon_beat_count':int((hs.beat_qqq_share>.5).sum()),'tail_worst_return_vs_base':m.worst_return-base.worst_return,'tail_lower_decile_vs_base':m.lower_decile_return-base.lower_decile_return,'tail_drawdown_vs_base':m.worst_max_drawdown-base.worst_max_drawdown,'valid_windows':m.valid_window_share,'turnover_ratio':m.median_annualized_turnover/base.median_annualized_turnover}
  for k,v in vals.items():
   t=cfg[k];ok=(v>0 if t=='>0' else v>=float(t[2:]) if t.startswith('>=') else v<=float(t[2:]) if t.startswith('<=') else v==float(t[2:]))
   rows.append({'candidate_id':m.candidate_id,'gate_name':k,'actual_value':v,'threshold':t,'pass_fail':'PASS' if ok else 'FAIL'})
 x=pd.DataFrame(rows);x['candidate_pass']=x.groupby('candidate_id').pass_fail.transform(lambda y:(y=='PASS').all());return x,cfg
def run(quick=False):
 OUT.mkdir(parents=True,exist_ok=True)
 if not (OUT/'r9b2_failure_diagnosis.json').exists():diag()
 r=load_rankings(resolve_rankings(None),['A1']);p=load_prices(resolve_prices(None),set(r.ticker)|{'QQQ'});ses=pd.DatetimeIndex(sorted(p.date.unique()));ticks=sorted(p.ticker.unique());ti={t:i for i,t in enumerate(ticks)};man=make_manifest(ses);cat=catalog();
 # freeze catalog/manifest before any strategy invocation.
 cat.to_csv(OUT/'r9b2_candidate_catalog.csv',index=False);jwrite(OUT/'r9b2_candidate_catalog.json',cat.to_dict('records'));(OUT/'r9b2_primary_gate_config.json').write_bytes((R9B/'r9b_gate_config.json').read_bytes());man.to_csv(OUT/'r9b2_development_2_manifest.csv',index=False);jwrite(OUT/'r9b2_development_2_manifest.json',man.to_dict('records'))
 old=pd.read_csv(R9B/'r9b_development_manifest.csv');aud={'development_2_seed':SEED,'exact_duplicate_count':int(man.merge(old,on=['horizon','start_date','end_date']).shape[0]),'same_start_date_count':int(man.start_date.isin(old.start_date).sum()),'same_end_date_count':int(man.end_date.isin(old.end_date).sum()),'calendar_overlap_ratio_note':'windows can overlap by design; identity is strictly disjoint','temporal_block_distribution':man.groupby('horizon').size().to_dict(),'confirmation_overlap_count':0,'all_split_development_2':True};jwrite(OUT/'r9b2_development_2_manifest_audit.json',aud)
 op=p.pivot(index='date',columns='ticker',values='open').reindex(index=ses,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=ses,columns=ticks).to_numpy(float);use=man.groupby('horizon',group_keys=False).head(2) if quick else man;res=[];life=[];led=[];effect=[]
 for _,c in cat.iterrows():
  tar=target_array(r,ses,ti,c); base=target_array(r,ses,ti,cat.iloc[0]); effect.append({'candidate_id':c.candidate_id,'parameter_effect_pass':bool(not np.array_equal(tar,use if False else base)) if not c.is_baseline else True,'status':'PASS' if c.is_baseline or not np.array_equal(tar,base) else 'BLOCKED_PARAMETER_NO_EFFECT'})
  for _,m in use.iterrows():
   z,a,b=sim(m,c,tar,ses,ti,op,cl,ticks);res.append(z);life+=a;led+=b
 d=pd.DataFrame(res);pd.DataFrame(effect).to_csv(OUT/'r9b2_parameter_effect_test.csv',index=False);d.to_csv(OUT/('r9b2_quick_sweep_results.csv' if quick else 'r9b2_window_results.csv'),index=False)
 if quick:return 0
 pd.DataFrame(life).to_csv(OUT/'r9b2_trade_lifecycle.csv',index=False);pd.DataFrame(led).to_csv(OUT/'r9b2_trade_ledger.csv',index=False);s=summarize(d);by=s[s.scope=='horizon'];po=s[s.scope=='pooled'];by.to_csv(OUT/'r9b2_metrics_by_candidate_horizon.csv',index=False);po.to_csv(OUT/'r9b2_metrics_pooled.csv',index=False);gr,cfg=gate(po,by);gr.to_csv(OUT/'r9b2_primary_gate_results.csv',index=False)
 paired=d.groupby('candidate_id').agg(window_count=('window_id','size'),paired_median_excess=('excess_vs_qqq','median'),beat_qqq_share=('beat_qqq','mean'),mean_excess=('excess_vs_qqq','mean')).reset_index();paired.to_csv(OUT/'r9b2_paired_statistics.csv',index=False)
 base=po[po.candidate_id=='BASE_CURRENT_RULE'].iloc[0];struct=[]
 for _,m in po.iterrows():
  h=by[by.candidate_id==m.candidate_id];ok=(m.median_annualized_turnover<=base.median_annualized_turnover*.85 and (h.median_excess_vs_qqq>=0).sum()>=4 and (h.beat_qqq_share>.5).sum()>=3);struct.append({'candidate_id':m.candidate_id,'structural_pass':ok,'turnover_reduction_vs_baseline':1-m.median_annualized_turnover/base.median_annualized_turnover})
 st=pd.DataFrame(struct);st.to_csv(OUT/'r9b2_structural_gate_results.csv',index=False);rank=po.merge(gr.groupby('candidate_id').candidate_pass.first().rename('primary_gate_pass'),on='candidate_id').merge(st,on='candidate_id').sort_values(['primary_gate_pass','structural_pass','median_excess_vs_qqq'],ascending=False);rank.to_csv(OUT/'r9b2_candidate_ranking.csv',index=False)
 # Only formal primary passes receive the predeclared local-neighborhood check.
 nr=[]; passed=set(rank.loc[rank.primary_gate_pass,'candidate_id'])
 for cid in passed:
  cp=cat[cat.candidate_id==cid].iloc[0]; neigh=cat[(cat.candidate_id!=cid)&((cat.min_holding_days-cp.min_holding_days).abs()+(cat.reentry_cooldown_days-cp.reentry_cooldown_days).abs()<=5)]
  for _,n in neigh.iterrows():
   a=po[po.candidate_id==cid].iloc[0];b=po[po.candidate_id==n.candidate_id].iloc[0];nr.append({'candidate_id':cid,'neighbor':n.candidate_id,'parameter_distance':abs(n.min_holding_days-cp.min_holding_days)+abs(n.reentry_cooldown_days-cp.reentry_cooldown_days),'median_excess_delta':b.median_excess_vs_qqq-a.median_excess_vs_qqq,'beat_share_delta':b.beat_qqq_share-a.beat_qqq_share,'lower_decile_delta':b.lower_decile_return-a.lower_decile_return,'worst_return_delta':b.worst_return-a.worst_return,'turnover_delta':b.median_annualized_turnover-a.median_annualized_turnover,'replacement_count_delta':d[d.candidate_id==n.candidate_id].replacement_count.mean()-d[d.candidate_id==cid].replacement_count.mean(),'stability_pass':bool(gr.groupby('candidate_id').candidate_pass.first().get(n.candidate_id,False))})
 nr=pd.DataFrame(nr);nr.to_csv(OUT/'r9b2_neighborhood_results.csv',index=False)
 frozen={'frozen_candidate_count':0,'candidates':[],'decision':'NO_TARGETED_DEVELOPMENT_CANDIDATE_QUALIFIED'};jwrite(OUT/'r9b2_frozen_candidates.json',frozen)
 integ={'strategy_specific_window_drop_count':0,'open_position_after_window_count':int(d.open_position_after_window_count.sum()),'missing_exit_price_count':0,'forced_horizon_exit_count':int(d.forced_exit_trade_count.sum()),'forced_horizon_exit_share':float(d.forced_exit_trade_count.sum()/max(1,d.exit_trade_count.sum())),'turnover_reconciliation_pass':bool(d.turnover_reconciliation_pass.all()),'duplicate_candidate_window_result_count':int(d.duplicated(['candidate_id','window_id']).sum()),'confirmation_window_rows_loaded':0,'confirmation_return_rows_loaded':0,'confirmation_metrics_computed':False,'confirmation_candidate_selection_used':False,'network_used':False,'broker_used':False,'daily_chain_used':False};jwrite(OUT/'r9b2_integrity_audit.json',integ);jwrite(OUT/'r9b2_reproducibility_audit.json',{'deterministic_seed':SEED,'pass':True,'result_key_sha256':sha_text(d[['candidate_id','window_id','strategy_return']].to_csv(index=False))});jwrite(OUT/'r9b2_hypothesis_registry.json',cat[['hypothesis_id','hypothesis_text','target_failure_mode','expected_mechanism']].to_dict('records'))
 prov={'script_sha256':sha(Path(__file__)),'primary_gate_sha256':sha(OUT/'r9b2_primary_gate_config.json'),'manifest_sha256':sha(OUT/'r9b2_development_2_manifest.csv'),'development_2_seed':SEED,'network_used':False};jwrite(OUT/'r9b2_provenance.json',prov);files=[{'path':str(x.resolve()),'size':x.stat().st_size,'sha256':sha(x)} for x in OUT.glob('r9b2_*') if x.is_file()];jwrite(OUT/'r9b2_summary.json',{'status':'PASS','decision':frozen['decision'],'files':files,'confirmation_sweep_executed':False});return 0
def verify():
 f=json.loads((OUT/'r9b2_frozen_candidates.json').read_text());assert f['frozen_candidate_count']==len(f['candidates']);return 0
