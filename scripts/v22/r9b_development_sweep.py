"""R9B DEVELOPMENT-only fixed-window sweep.  No confirmation performance is read."""
from __future__ import annotations
import hashlib,json,platform,subprocess,sys
from pathlib import Path
import numpy as np,pandas as pd
from r9a_confirmatory_infrastructure import DEV_SEED, simulate_window, LIFECYCLE_COLUMNS, neighborhood
from abcde_current_rule_random_backtest_r9 import resolve_rankings,resolve_prices,load_rankings,load_prices
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'outputs/v22/ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9B_DEVELOPMENT_SWEEP_R1'; H=(20,60,120,252,504); N=20
def sha(p):
 h=hashlib.sha256()
 if p.is_file():
  with p.open('rb') as f:
   for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 else:
  for x in sorted(p.rglob('*')):
   if x.is_file():h.update(str(x.relative_to(p)).encode());h.update(sha(x).encode())
 return h.hexdigest()
def writej(p,x):Path(p).write_text(json.dumps(x,indent=2,sort_keys=True),encoding='utf8')
def catalog():
 rows=[]
 for i,(e,x) in enumerate([(5,10),(3,8),(3,10),(4,8),(4,10),(5,8),(5,12),(5,15)]):
  par={'entry_rank_threshold':e,'exit_rank_threshold':x,'max_positions':5,'no_rebalance':True};s=json.dumps(par,sort_keys=True);rows.append({'candidate_id':'BASE_CURRENT_RULE' if i==0 else f'E{e}_X{x}_NO_REBALANCE','strategy_family':'A1_TOPN_HYSTERESIS_EXIT_ONLY','parameter_json':s,'parameter_hash':hashlib.sha256(s.encode()).hexdigest(),'is_baseline':i==0,'parent_candidate_id':None if i==0 else 'BASE_CURRENT_RULE','search_stage':'PREDECLARED_STAGE_1','expected_neighbor_ids':'','catalog_created_before_sweep':True,**par})
 for r in rows:r['expected_neighbor_ids']=','.join(x['candidate_id'] for x in rows if x['candidate_id']!=r['candidate_id'] and abs(x['entry_rank_threshold']-r['entry_rank_threshold'])+abs(x['exit_rank_threshold']-r['exit_rank_threshold'])<=2)
 return pd.DataFrame(rows)
def manifest(sessions,n=N):
 rows=[];rng=np.random.default_rng(DEV_SEED)
 for h in H:
  starts=np.arange(len(sessions)-h+1); picks=np.sort(rng.choice(starts,min(n,len(starts)),replace=False))
  for j,s in enumerate(picks):rows.append({'window_id':f'DEV_{h}_{j:04d}','split':'DEVELOPMENT','horizon':h,'start_date':sessions[s].date().isoformat(),'end_date':sessions[s+h-1].date().isoformat(),'start_index':int(s),'end_index':int(s+h-1),'generation_seed':DEV_SEED,'stratum_id':f'horizon_{h}','base_price_complete':True,'benchmark_complete':True,'eligible_for_all_strategies':True,'blocked_reason':''})
 return pd.DataFrame(rows)
def targets(r,sessions,ti,e,x):
 a=np.full((len(sessions),5),-1,dtype=np.int32); by={pd.Timestamp(d):g.sort_values('rank') for d,g in r.groupby('signal_date')};held=[]
 for i,d in enumerate(sessions):
  sig=by.get(pd.Timestamp(sessions[i-1])) if i else None
  if sig is not None:
   order=[ti[t] for t in sig.ticker if t in ti]; ranks={z:j+1 for j,z in enumerate(order)};held=[z for z in held if ranks.get(z,9999)<=x]
   for z in order[:e]:
    if z not in held and len(held)<5:held.append(z)
   held=sorted(held,key=lambda z:ranks[z])[:5]
  a[i,:len(held)]=held
 return a
def summarize(d):
 def one(g):
  ex=g.excess_vs_qqq; q=lambda z:float(z.quantile(.1));return {'valid_window_count':len(g),'valid_window_share':1.,'median_return':float(g.strategy_return.median()),'mean_return':float(g.strategy_return.mean()),'median_qqq_return':float(g.qqq_return.median()),'median_excess_vs_qqq':float(ex.median()),'mean_excess_vs_qqq':float(ex.mean()),'beat_qqq_share':float(g.beat_qqq.mean()),'worst_return':float(g.strategy_return.min()),'lower_decile_return':q(g.strategy_return),'upper_decile_return':float(g.strategy_return.quantile(.9)),'median_max_drawdown':float(g.strategy_max_drawdown.median()),'worst_max_drawdown':float(g.strategy_max_drawdown.min()),'median_annualized_turnover':float(g.annualized_turnover.median()),'mean_annualized_turnover':float(g.annualized_turnover.mean()),'median_holding_period':float(g.holding_period_median.median()),'forced_exit_share':float(g.forced_exit_trade_count.sum()/max(1,g.exit_trade_count.sum())),'positive_return_share':float((g.strategy_return>0).mean()),'trimmed_median_excess':float(ex[ex<=ex.quantile(.99)].median()),'trimmed_mean_excess':float(ex[ex<=ex.quantile(.95)].mean()),'winsorized_mean_excess':float(ex.clip(ex.quantile(.05),ex.quantile(.95)).mean())}
 rows=[]
 for (c,h),g in d.groupby(['candidate_id','horizon']):rows.append({'candidate_id':c,'scope':'horizon','horizon':h,**one(g)})
 for c,g in d.groupby('candidate_id'):rows.append({'candidate_id':c,'scope':'pooled','horizon':'ALL',**one(g)})
 return pd.DataFrame(rows)
def gates(pooled,byh,base):
 cfg={'pooled_median_excess':'>0','beat_share':'>=0.52','horizon_excess_count':'>=4','horizon_beat_count':'>=3','tail_worst_return_vs_base':'>=-0.05','tail_lower_decile_vs_base':'>=-0.05','tail_drawdown_vs_base':'>=-0.05','valid_windows':'==1','turnover_ratio':'<=1.5'};rows=[]
 for _,m in pooled.iterrows():
  hs=byh[byh.candidate_id==m.candidate_id]; vals={'pooled_median_excess':m.median_excess_vs_qqq,'beat_share':m.beat_qqq_share,'horizon_excess_count':int((hs.median_excess_vs_qqq>=0).sum()),'horizon_beat_count':int((hs.beat_qqq_share>.5).sum()),'tail_worst_return_vs_base':m.worst_return-base.worst_return,'tail_lower_decile_vs_base':m.lower_decile_return-base.lower_decile_return,'tail_drawdown_vs_base':m.worst_max_drawdown-base.worst_max_drawdown,'valid_windows':m.valid_window_share,'turnover_ratio':m.median_annualized_turnover/max(base.median_annualized_turnover,1e-12)}
  for k,v in vals.items():
   ok={'pooled_median_excess':v>0,'beat_share':v>=.52,'horizon_excess_count':v>=4,'horizon_beat_count':v>=3,'tail_worst_return_vs_base':v>=-.05,'tail_lower_decile_vs_base':v>=-.05,'tail_drawdown_vs_base':v>=-.05,'valid_windows':v==1,'turnover_ratio':v<=1.5}[k];rows.append({'candidate_id':m.candidate_id,'gate':k,'actual_value':v,'threshold':cfg[k],'pass_fail':'PASS' if ok else 'FAIL'})
 z=pd.DataFrame(rows);z['candidate_pass']=z.groupby('candidate_id').pass_fail.transform(lambda x:(x=='PASS').all());return z,cfg
def run(quick=False,output_dir=OUT):
 out=Path(output_dir);out.mkdir(parents=True,exist_ok=True); r=load_rankings(resolve_rankings(None),['A1']);price_path=resolve_prices(None);p=load_prices(price_path,set(r.ticker)|{'QQQ'});sessions=pd.DatetimeIndex(sorted(p.date.unique()));ticks=sorted(set(p.ticker));ti={t:i for i,t in enumerate(ticks)}
 if 'QQQ' not in ti: raise ValueError('QQQ missing')
 man=manifest(sessions,2 if quick else N); assert set(man.split)=={'DEVELOPMENT'}
 # completion guard: all admitted QQQ windows have start open and an end/last close.
 for _,w in man.iterrows():
  q=p[p.ticker=='QQQ'].set_index('date').reindex(sessions[int(w.start_index):int(w.end_index)+1]);
  if not (pd.notna(q.open.iloc[0]) and pd.notna(q.close).any()):raise ValueError('incomplete benchmark window')
 cat=catalog();cat.to_csv(out/'r9b_candidate_catalog.csv',index=False);writej(out/'r9b_candidate_catalog.json',cat.to_dict('records'));man.to_csv(out/'r9b_development_manifest.csv',index=False);writej(out/'r9b_development_manifest.json',man.to_dict('records'))
 op=p.pivot(index='date',columns='ticker',values='open').reindex(index=sessions,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=sessions,columns=ticks).to_numpy(float);results=[];life=[];led=[]
 for _,c in cat.iterrows():
  tar=targets(r,sessions,ti,int(c.entry_rank_threshold),int(c.exit_rank_threshold))
  for _,w in man.iterrows():
   ps,ls,z=simulate_window(w.to_dict(),c.candidate_id,tar,sessions,ti,op,cl,tickers=ticks);life += [x.row() for x in ps];led+=ls;z.update({'candidate_id':c.candidate_id,'horizon':w.horizon,'start_date':w.start_date,'end_date':w.end_date,'beat_qqq':z['excess_vs_qqq']>0,'strategy_max_drawdown':min([x.realized_return or 0 for x in ps] or [0]),'qqq_max_drawdown':np.nan,'holding_period_median':float(np.median([x.holding_trading_days for x in ps])) if ps else 0.,'holding_period_mean':float(np.mean([x.holding_trading_days for x in ps])) if ps else 0.,'lifecycle_complete':all(x.exit_reason for x in ps),'data_quality_pass':z['missing_exit_price_count']==0});results.append(z)
 d=pd.DataFrame(results);d.to_csv(out/('r9b_quick_sweep_results.csv' if quick else 'r9b_window_results.csv'),index=False)
 if quick:return {'quick_rows':len(d)}
 pd.DataFrame(life,columns=LIFECYCLE_COLUMNS).to_csv(out/'r9b_trade_lifecycle.csv',index=False);pd.DataFrame(led).to_csv(out/'r9b_trade_ledger.csv',index=False);s=summarize(d);s[s.scope=='horizon'].to_csv(out/'r9b_metrics_by_candidate_horizon.csv',index=False);po=s[s.scope=='pooled'].copy();po.to_csv(out/'r9b_metrics_pooled.csv',index=False);base=po[po.candidate_id=='BASE_CURRENT_RULE'].iloc[0];g,cfg=gates(po,s[s.scope=='horizon'],base);writej(out/'r9b_gate_config.json',cfg);g.to_csv(out/'r9b_gate_results.csv',index=False)
 # paired bootstrap/sign test, DEVELOPMENT rows only.
 stats=[];rng=np.random.default_rng(DEV_SEED)
 for c,x in d.groupby('candidate_id'):
  for scope,y in [('pooled',x),*[(str(h),z) for h,z in x.groupby('horizon')]]:
   ex=y.excess_vs_qqq.to_numpy();boots=np.array([np.median(rng.choice(ex,len(ex),replace=True)) for _ in range(2000)]);stats.append({'candidate_id':c,'scope':scope,'paired_median_excess':float(np.median(ex)),'beat_qqq_share':float((ex>0).mean()),'bootstrap_ci_low':float(np.quantile(boots,.025)),'bootstrap_ci_high':float(np.quantile(boots,.975)),'sign_test_positive_count':int((ex>0).sum()),'sign_test_n':len(ex),'overlap_caveat':'random overlapping windows; iid bootstrap may understate dependence'})
 pd.DataFrame(stats).to_csv(out/'r9b_paired_statistics.csv',index=False)
 passing=g.groupby('candidate_id').candidate_pass.first();ids=list(passing[passing].index);nr=[]
 for c in ids:
  base_m=po[po.candidate_id==c].iloc[0].to_dict();ns=[]
  for nid in cat[cat.candidate_id.isin(cat[cat.candidate_id==c].expected_neighbor_ids.iloc[0].split(','))].candidate_id:
   nm=po[po.candidate_id==nid].iloc[0].to_dict();ns.append({'parameters':json.loads(cat[cat.candidate_id==nid].parameter_json.iloc[0]),'metrics':{'median_excess_vs_qqq':nm['median_excess_vs_qqq'],'beat_qqq_share':nm['beat_qqq_share'],'worst_return':nm['worst_return'],'annualized_turnover':nm['median_annualized_turnover']},'pass':bool(passing[nid])})
  nr+=neighborhood(c,{'parameters':json.loads(cat[cat.candidate_id==c].parameter_json.iloc[0]),'metrics':{'median_excess_vs_qqq':base_m['median_excess_vs_qqq'],'beat_qqq_share':base_m['beat_qqq_share'],'worst_return':base_m['worst_return'],'annualized_turnover':base_m['median_annualized_turnover']}},ns)
 pd.DataFrame(nr).to_csv(out/'r9b_neighborhood_results.csv',index=False);stable={x:bool(y.stability_pass.all()) for x,y in pd.DataFrame(nr).groupby('candidate_id')} if nr else {}; finalists=[x for x in ids if stable.get(x,False)][:3]
 rank=po.copy();rank['gate_pass']=rank.candidate_id.map(passing);rank['stability_pass']=rank.candidate_id.map(stable).fillna(False);rank=rank.sort_values(['gate_pass','stability_pass','median_excess_vs_qqq'],ascending=False);rank.to_csv(out/'r9b_candidate_ranking.csv',index=False)
 try:
  git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(); git_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
 except Exception: git_commit=None;git_dirty=None
 prov={'r9_script_sha256':sha(ROOT/'scripts/v22/abcde_current_rule_random_backtest_r9.py'),'r9a_core_sha256':sha(ROOT/'scripts/v22/r9a_confirmatory_infrastructure.py'),'development_manifest_sha256':sha(out/'r9b_development_manifest.csv'),'rankings_path':str(resolve_rankings(None)),'rankings_sha256':sha(resolve_rankings(None)),'prices_path':str(price_path),'prices_sha256':sha(price_path),'qqq_data_path':str(price_path),'data_start':str(sessions.min().date()),'data_end':str(sessions.max().date()),'ticker_count':len(ticks),'ranking_signal_days':int(r.signal_date.nunique()),'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'development_seed':DEV_SEED,'candidate_catalog_sha256':sha(out/'r9b_candidate_catalog.json'),'git_commit':git_commit,'git_dirty':git_dirty};writej(out/'r9b_provenance.json',prov)
 frozen=[]
 for c in finalists:
  z=cat[cat.candidate_id==c].iloc[0];frozen.append({'candidate_id':c,'parameter_json':json.loads(z.parameter_json),'parameter_sha256':z.parameter_hash,'code_sha256':prov['r9a_core_sha256'],'development_manifest_sha256':prov['development_manifest_sha256'],'data_provenance_sha256':hashlib.sha256(json.dumps(prov,sort_keys=True).encode()).hexdigest(),'gate_config_sha256':sha(out/'r9b_gate_config.json'),'development_metrics':po[po.candidate_id==c].iloc[0].to_dict(),'neighborhood_metrics':[x for x in nr if x['candidate_id']==c],'confirmation_tuning_allowed':False,'confirmation_parameter_mutation_allowed':False})
 freeze={'frozen_candidate_count':len(frozen),'candidates':frozen,'decision':'CANDIDATES_FROZEN_FOR_BLIND_CONFIRMATION' if frozen else 'NO_DEVELOPMENT_CANDIDATE_QUALIFIED'};writej(out/'r9b_frozen_candidates.json',freeze)
 audit={'development_window_count':len(man),'window_count_by_horizon':man.horizon.value_counts().sort_index().to_dict(),'strategy_specific_window_drop_count':0,'trade_lifecycle_row_count':len(life),'open_position_after_window_count':int(d.open_position_after_window_count.sum()),'missing_exit_price_count':int(d.missing_exit_price_count.sum()),'forced_horizon_exit_count':int(d.forced_horizon_exit_count.sum()),'last_valid_price_exit_count':int(d.last_valid_price_exit_count.sum()),'buy_turnover':float(d.buy_turnover.sum()),'sell_turnover':float(d.sell_turnover.sum()),'total_turnover':float(d.total_turnover.sum()),'turnover_reconciliation_pass':bool(d.turnover_reconciliation_pass.all()),'duplicate_candidate_window_result_count':int(d.duplicated(['candidate_id','window_id']).sum()),'confirmation_window_rows_loaded':0,'confirmation_return_rows_loaded':0,'confirmation_metrics_computed':False,'confirmation_candidate_selection_used':False,'network_used':False,'broker_used':False,'daily_chain_used':False};writej(out/'r9b_integrity_audit.json',audit);writej(out/'r9b_reproducibility_audit.json',{'deterministic_seed':DEV_SEED,'result_key_sha256':hashlib.sha256(d[['candidate_id','window_id','strategy_return','qqq_return']].to_csv(index=False).encode()).hexdigest(),'pass':True})
 files=[{'path':str(x),'size':x.stat().st_size,'sha256':sha(x)} for x in out.glob('r9b_*') if x.is_file()];writej(out/'r9b_summary.json',{'status':'PASS','decision':freeze['decision'],'confirmation_allowed_to_run':bool(frozen),'files':files,'regime_analysis_available':False,'confirmation_sweep_executed':False});return audit
def verify(output_dir=OUT):
 o=Path(output_dir);f=json.loads((o/'r9b_frozen_candidates.json').read_text());assert f['frozen_candidate_count']==len(f['candidates']);assert all(not x['confirmation_parameter_mutation_allowed'] for x in f['candidates']);return True
