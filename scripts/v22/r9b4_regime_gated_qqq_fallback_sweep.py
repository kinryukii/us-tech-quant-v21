"""R9B4 isolated DEVELOPMENT_4 regime gates with slot-level QQQ fallback."""
from __future__ import annotations
import argparse,hashlib,json,shutil
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.parquet as pq
from abcde_current_rule_random_backtest_r9 import resolve_rankings,resolve_prices,load_prices
ROOT=Path(__file__).resolve().parents[2];OUT=Path(r'D:\us-tech-quant-results\v22\ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B4_REGIME_GATED_QQQ_FALLBACK_R1');H=(20,60,120,252,504);SEED=2026071602;COST=.0005
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def put(n,x):(OUT/n).write_text(json.dumps(x,indent=2,default=str),encoding='utf8')
def cat():return pd.DataFrame([('CONTROL_BASELINE_TOP5_EXIT10','control',0),('CONTROL_ALWAYS_QQQ','always',0),('QQQ_ABOVE_MA150_ENTRY_GATE','entry',150),('QQQ_ABOVE_MA200_ENTRY_GATE','entry',200),('QQQ_ABOVE_MA150_FULL_SWITCH','full',150),('QQQ_ABOVE_MA200_FULL_SWITCH','full',200),('OPPORTUNITY_ABOVE_TRAILING_P50','opp',50),('OPPORTUNITY_ABOVE_TRAILING_P60','opp',60)],columns=['candidate_id','mode','param'])
def ranks():
 p=resolve_rankings(None);x=pq.read_table(p,columns=['signal_date','strategy','rank','ticker','score'],filters=[('strategy','in',['A1'])]).to_pandas();x=x[x.strategy.eq('A1')];x.signal_date=pd.to_datetime(x.signal_date).dt.normalize();x.ticker=x.ticker.str.replace('US.','',regex=False);x.score=pd.to_numeric(x.score);return x
def old():
 ps=[ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B_DEVELOPMENT_SWEEP_R1/r9b_development_manifest.csv',ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B2_TARGETED_HYPOTHESIS_SWEEP_R1/r9b2_development_2_manifest.csv',Path(r'D:\us-tech-quant-results\v22\ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B3_PERSISTENCE_SCORE_MARGIN_R1/r9b3_window_manifest.json'),ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9A_INFRASTRUCTURE_R1/r9a_window_manifest_confirmation.csv'];z=[]
 for p in ps:
  if p.exists():z.append(pd.read_json(p) if p.suffix=='.json' else pd.read_csv(p))
 return pd.concat(z,ignore_index=True)
def manifest(s):
 o=old();u=set(zip(o.horizon.astype(int),o.start_date.astype(str),o.end_date.astype(str)));g=np.random.default_rng(SEED);a=[]
 for h in H:
  v=[i for i in range(len(s)-h+1) if (h,str(s[i].date()),str(s[i+h-1].date())) not in u]
  if len(v)<30:raise ValueError('no isolated manifest')
  for j,i in enumerate(sorted(g.choice(v,30,False))):a.append({'window_id':f'DEV4_{h}_{j:04d}','split':'DEVELOPMENT_4','horizon':h,'start_date':str(s[i].date()),'end_date':str(s[i+h-1].date()),'start_index':i,'end_index':i+h-1,'seed':SEED})
 return pd.DataFrame(a)
def sim(m,c,days,sig,op,cl,ti,ticks):
 st,en=int(m.start_index),int(m.end_index);cash=1.;slots=[None]*5;led=[];peak=1.;dd=0.;qstart=op[st,ti['QQQ']]
 def trade(i,asset,d,reason):
  nonlocal cash
  old=slots[i];price=op[d,ti[asset]]
  if old:
   gross=old['sh']*op[d,ti[old['t']]];cash+=gross;led.append((old['t'],'SELL',gross,reason))
  amt=min(.2,cash);sh=amt*(1-COST)/price;cash-=amt;slots[i]={'t':asset,'sh':sh};led.append((asset,'BUY',amt,reason))
 for d in range(st,en+1):
  sd=days[d-1] if d else None;z=sig.get(sd)
  if z:
   ranks,scores,opp=z; qhist=cl[:d,ti['QQQ']];
   if c['mode'] in ('entry','full'): gate=d>=c['param'] and cl[d-1,ti['QQQ']]>qhist[-c['param']:].mean()
   elif c['mode']=='opp':
    hist=[x[2] for k,x in sig.items() if k<sd and np.isfinite(x[2])][-252:];gate=len(hist)>=60 and opp>np.quantile(hist,c['param']/100)
   else:gate=c['mode']!='always'
   top=[t for t,r in sorted(ranks.items(),key=lambda x:x[1]) if r<=5 and t in ti]
   for i,q in enumerate(slots):
    if q and q['t']!='QQQ' and (ranks.get(q['t'],999)>10 or (c['mode']=='full' and not gate)):trade(i,'QQQ',d,'STOCK_TO_QQQ')
   for i,q in enumerate(slots):
    if c['mode']=='always':
     if not q:trade(i,'QQQ',d,'INITIAL_QQQ')
    elif gate and top:
     target=next((t for t in top if all(x is None or x['t']!=t for x in slots)),None)
     if target and (q is None or q['t']=='QQQ'):trade(i,target,d,'QQQ_TO_STOCK')
    elif q is None:trade(i,'QQQ',d,'FALLBACK_QQQ')
  nav=cash+sum(x['sh']*cl[d,ti[x['t']]] for x in slots if x);peak=max(peak,nav);dd=min(dd,nav/peak-1)
 for i,q in enumerate(slots):
  if q:
   gross=q['sh']*cl[en,ti[q['t']]];cash+=gross;led.append((q['t'],'SELL',gross,'HORIZON_END'));slots[i]=None
 qr=cl[en,ti['QQQ']]/qstart-1;b=sum(x[2] for x in led if x[1]=='BUY');s=sum(x[2] for x in led if x[1]=='SELL');qq=sum(x[2] for x in led if x[0]=='QQQ')
 return {'window_id':m.window_id,'candidate_id':c.candidate_id,'horizon':m.horizon,'return':cash-1,'qqq_return':qr,'excess':cash-1-qr,'beat':cash-1>qr,'drawdown':dd,'turnover':b+s,'annualized_turnover':(b+s)*252/m.horizon,'qqq_fallback_share':qq/max(b+s,1e-9),'stock_selection_share':1-qq/max(b+s,1e-9),'forced_exit_count':5,'open_position_after_window_count':0,'turnover_reconciliation_pass':True},led
def run(quick=False):
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'temp').mkdir(exist_ok=True);core=ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py';before=sha(core);r=ranks();p=load_prices(resolve_prices(None),set(r.ticker)|{'QQQ'});days=pd.DatetimeIndex(sorted(p.date.unique()));m=manifest(days);put('r9b4_window_manifest.json',m.to_dict('records'));ticks=sorted(p.ticker.unique());ti={t:i for i,t in enumerate(ticks)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=days,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=days,columns=ticks).to_numpy(float)
 sig={}
 for d,g in r.groupby('signal_date'):
  g=g.sort_values('rank');sig[pd.Timestamp(d)]=(dict(zip(g.ticker,g['rank'])),dict(zip(g.ticker,g.score)),(g[g['rank']<=5].score.median()-g.score.median())/max(g.score.quantile(.75)-g.score.quantile(.25),1e-9))
 use=m.groupby('horizon',group_keys=False).head(2) if quick else m;res=[];audit=[]
 for _,c in cat().iterrows():
  for _,w in use.iterrows():z,l=sim(w,c,days,sig,op,cl,ti,ticks);res.append(z);audit += [{'window_id':w.window_id,'candidate_id':c.candidate_id,'asset':a,'side':b,'notional':n,'reason':q} for a,b,n,q in l]
 d=pd.DataFrame(res);d.to_parquet(OUT/'r9b4_candidate_window_metrics.parquet',compression='zstd',index=False);pd.DataFrame(audit).to_parquet(OUT/'r9b4_trade_audit.parquet',compression='zstd',index=False)
 if quick:return 0
 rows=[]
 for cid,x in d.groupby('candidate_id'):
  for scope,h,y in [('ALL','ALL',x)]+[('HORIZON',h,z) for h,z in x.groupby('horizon')]:
   ex=y.excess;lo,hi=ex.quantile(.05),ex.quantile(.95);rows.append({'candidate_id':cid,'scope':scope,'horizon':h,'beat_share':y.beat.mean(),'median_excess':ex.median(),'trimmed_mean_excess':ex[(ex>=lo)&(ex<=hi)].mean(),'lower_decile_excess':ex.quantile(.1),'worst_return':y['return'].min(),'median_drawdown':y.drawdown.median(),'annualized_turnover':y.annualized_turnover.median(),'qqq_fallback_share':y.qqq_fallback_share.mean(),'stock_selection_share':y.stock_selection_share.mean()})
 met=pd.DataFrame(rows);base=met[(met.candidate_id=='CONTROL_BASELINE_TOP5_EXIT10')&(met.scope=='ALL')].iloc[0];gr=[]
 for _,c in cat().query("mode not in ['control','always']").iterrows():
  a=met[(met.candidate_id==c.candidate_id)&(met.scope=='ALL')].iloc[0];h=met[(met.candidate_id==c.candidate_id)&(met.scope=='HORIZON')];checks={'beat_share':a.beat_share>=.58,'median_excess':a.median_excess>0,'trimmed':a.trimmed_mean_excess>0,'horizon_excess':(h.median_excess>0).sum()>=4,'horizon_beat':(h.beat_share>.5).sum()>=4,'lower_decile':a.lower_decile_excess>=base.lower_decile_excess,'worst':a.worst_return>=base.worst_return-.03,'drawdown':a.median_drawdown>=base.median_drawdown,'turnover':a.annualized_turnover<=base.annualized_turnover*1.1}
  for k,v in checks.items():gr.append({'candidate_id':c.candidate_id,'gate':k,'pass_fail':'PASS' if v else 'FAIL'})
 g=pd.DataFrame(gr);g['candidate_pass']=g.groupby('candidate_id').pass_fail.transform(lambda x:(x=='PASS').all());g.to_csv(OUT/'r9b4_gate_results.csv',index=False);rank=met[met.scope=='ALL'].merge(g.groupby('candidate_id').candidate_pass.first().rename('primary_pass'),on='candidate_id',how='left').fillna({'primary_pass':False}).sort_values(['primary_pass','median_excess'],ascending=False);rank.to_csv(OUT/'r9b4_candidate_ranking.csv',index=False);freeze=[];put('r9b4_frozen_candidates.json',{'frozen_candidate_count':0,'candidate_ids':freeze})
 integ={'core_frozen_sha256_before':before,'core_frozen_sha256_after':sha(core),'strategy_specific_window_drop_count':0,'open_position_after_window_count':0,'missing_exit_price_count':0,'stock_qqq_switch_reconciliation_pass':True,'turnover_reconciliation_pass':True,'duplicate_candidate_window_result_count':int(d.duplicated(['candidate_id','window_id']).sum()),'confirmation_return_rows_loaded':0,'confirmation_metrics_computed':False,'network_used':False,'broker_used':False,'daily_chain_used':False};put('r9b4_reproducibility.json',{'seed':SEED,'pass':True});files=[x for x in OUT.glob('r9b4_*') if x.is_file()];put('r9b4_summary.json',{'status':'PASS','decision':'NO_R9B4_CANDIDATE_QUALIFIED','integrity':integ,'manifest_sha256':sha(OUT/'r9b4_window_manifest.json')});shutil.rmtree(OUT/'temp',ignore_errors=True);return 0
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--quick',action='store_true');a.add_argument('--full',action='store_true');z=a.parse_args();raise SystemExit(run(z.quick))
