"""All prespecified routes, each with an independent holding-aware account."""
from __future__ import annotations
from common import *
import argparse,time,traceback,os
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime,timezone
import pandas as pd
import joblib
from threadpoolctl import threadpool_limits
from data_contract import load_eval_inputs,FEATURES
from engine_fast_inputs import run_replay,PreparedInputs
from engine_v2 import HoldingAwareDecision,OperationalExit

ENV={}
LEDGERS=['daily','trades','positions','target_decisions','diagnostics','valuation_intervals',
         'raw_model_outputs','signal_contexts','operational_actions','execution_results']

def clocks(calendar):
    half_days={'2025-07-03','2025-11-28','2025-12-24'}
    return {d:(d+pd.Timedelta(hours=13 if str(d.date()) in half_days else 16)).tz_localize('America/New_York').tz_convert('UTC') for d in calendar}

def forbid_fitting():
    import torch
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn import linear_model,ensemble,neural_network,covariance,decomposition,isotonic
    count={'attempts':0}
    def denied(*args,**kwargs):
        count['attempts']+=1;raise RuntimeError('FIT_FORBIDDEN_DURING_REPLAY')
    for module in [linear_model,ensemble,neural_network,covariance,decomposition,isotonic]:
        for name in dir(module):
            cls=getattr(module,name)
            if isinstance(cls,type) and hasattr(cls,'fit'):
                for method in ['fit','partial_fit','fit_transform']:
                    if hasattr(cls,method):setattr(cls,method,denied)
    for cls in [Pipeline,StandardScaler]:
        for method in ['fit','partial_fit','fit_transform']:
            if hasattr(cls,method):setattr(cls,method,denied)
    torch.optim.Adam.step=denied;torch.optim.SGD.step=denied;torch.set_num_threads(1)
    from models_native import NativeBundle,_import
    NativeBundle.fit=classmethod(denied)
    for module_name,class_names in [('xgboost',['XGBRegressor','XGBClassifier','XGBRanker']),
         ('lightgbm',['LGBMRegressor','LGBMClassifier','LGBMRanker']),('catboost',['CatBoostRegressor','CatBoostClassifier']),
         ('ngboost',['NGBRegressor']),('interpret.glassbox',['ExplainableBoostingRegressor'])]:
        module=_import(module_name)
        for name in class_names:setattr(getattr(module,name),'fit',denied)
    return count

def initialize(year):
    global ENV
    from risk_models import RiskBank
    from accelerated_optimizer import enable
    enable()
    from accelerated_solver import enable as enable_solver
    enable_solver()
    p,px,cal,ops,meta=load_eval_inputs(year)
    p=p[['signal_date','ticker','new_buy_eligible',*FEATURES]].sort_values(['signal_date','ticker']).reset_index(drop=True)
    asofs=clocks(cal)
    operations={d:{str(r.ticker):OperationalExit(str(r.reason),r.known_at,str(r.source_id))
       for r in ops.loc[(ops.known_at<=asofs[d])&(ops.effective_date<=d)].itertuples()} for d in cal}
    stage='validation' if year==2025 else 'final'
    ENV=dict(year=year,panel=p,prices=px,calendar=cal,metadata=meta,stage=stage,asofs=asofs,ops=operations,
       prepared=PreparedInputs(px,cal,p,signal_asof=asofs),risk=RiskBank(stage=stage),forecasts={},optimizers={},guard=forbid_fitting())
    from cached_risk_inference import enable as enable_risk_cache
    ENV['risk_cache']=enable_risk_cache(ENV['risk'])

def prediction_table(fid):
    if fid not in ENV['forecasts']:
        path=ROOT/f'predictions/forecasts/{ENV["year"]}'/(fid+'.parquet')
        frame=pd.read_parquet(path)
        by_date={}
        for d,g in frame.groupby('signal_date',sort=False):
            values=g[['mu','sigma','q10','q50','q90']].to_numpy(float,copy=True)
            values.setflags(write=False)
            semantics=g.marginal_semantics.unique() if 'marginal_semantics' in g else ['normal_moment_proxy']
            if len(semantics)!=1:raise RuntimeError('MIXED_MARGINAL_SEMANTICS:'+fid)
            by_date[d]=(pd.Index(g.ticker),values,str(semantics[0]))
        ENV['forecasts'][fid]=(by_date,str(path.relative_to(ROOT)))
        if len(ENV['forecasts'])>ENV.get('forecast_cache_limit',31):
            first=next(iter(ENV['forecasts']))
            if first!=fid:ENV['forecasts'].pop(first)
    return ENV['forecasts'][fid]

def optimizer(risk,method):
    from optimizers import OptimizeTop20
    key=(risk,method)
    if key not in ENV['optimizers']:
        ENV['optimizers'][key]=OptimizeTop20(method=method,risk_name=risk,risk_bank=ENV['risk'])
    return ENV['optimizers'][key]

def make_target(day,ctx,fid,risk,method):
    forecast,path=prediction_table(fid)
    names=day.ticker.to_numpy()
    lookup,values,semantics=forecast[ctx.signal_date]
    aligned=lookup.get_indexer(names)
    if (aligned<0).any():raise RuntimeError('FORECAST_KEY_OR_FINITE_ERROR:'+fid)
    values=values[aligned]
    if not np.isfinite(values).all():raise RuntimeError('FORECAST_KEY_OR_FINITE_ERROR:'+fid)
    mu=values[:,0]
    if method=='equal_top20':
        # The same legal support and held-only caps as the risk optimizers.
        from optimizers import select_top20,project_box_budget
        current=np.array([ctx.current_weights.get(str(t),0.) for t in names])
        eligible=day.new_buy_eligible.to_numpy(bool)&~day.ticker.isin(ctx.buy_restricted_tickers).to_numpy()
        indices=select_top20(names,mu,slots=ctx.available_slots,legal=eligible|(current>0))
        upper=np.where(eligible[indices],.1,np.minimum(current[indices],.1))
        weights=project_box_budget(np.ones(len(indices)),upper,ctx.available_weight) if len(indices) else np.empty(0)
        targets={str(names[i]):float(w) for i,w in zip(indices,weights) if w>0}
        metadata=dict(method=method,solver_status='closed_form_fixed_gross',support=[str(names[i]) for i in indices],
             objective=None,feasibility_error=0.,forecast_id=fid,prediction_file=path,selected_count=len(indices),
             target_exposure=sum(targets.values()),full_decision_pool_rows=len(day))
    else:
        columns=['sigma','q10','q50','q90'] if semantics=='native_quantile_piecewise' else ['sigma']
        targets,metadata=optimizer(risk,method)(day,ctx,mu=mu,marginals={k:values[:,['mu','sigma','q10','q50','q90'].index(k)] for k in columns})
        metadata={**metadata,'forecast_id':fid,'prediction_file':path,'marginal_semantics':semantics,'full_decision_pool_rows':len(day)}
    return targets,metadata

class Policy:
    def __init__(self,spec):
        self.spec=spec;self.diagnostics=[];self.member_targets=[]
        if spec['route']=='target_fusion':
            fusion=joblib.load(ROOT/'fusion_artifacts'/ENV['stage']/(spec['coalition']+'__convex.joblib'))
            self.blend_weights=fusion.fixed
    def __call__(self,day,ctx):
        # Only explicit zeros for old holdings; unused zero candidates create no orders.
        zeros={str(t):0. for t in day.ticker if t in ctx.current_units}
        if day.empty:return HoldingAwareDecision(model_decisions=zeros)
        s=self.spec
        if s['route']=='prediction_fusion':
            targets,metadata=make_target(day,ctx,s['forecast_id'],s['risk'],s['optimizer'])
        else:
            targets={};details=[]
            for member,blend_weight in zip(s['members'],self.blend_weights):
                t,m=make_target(day,ctx,'single__'+member,s['risk'],s['optimizer']);details.append(m)
                for ticker,w in t.items():
                    targets[ticker]=targets.get(ticker,0.)+float(blend_weight)*w
                    self.member_targets.append(dict(signal_date=ctx.signal_date,decision_id=s['strategy_id']+'|'+str(ctx.signal_date.date()),
                        member=member,ticker=ticker,member_target=w,blend_weight=float(blend_weight),weighted_target=float(blend_weight)*w,
                        prediction_id='single__'+member+'|'+str(ctx.signal_date.date())+'|'+ticker))
            keep=sorted(targets,key=lambda t:(-targets[t],t))[:ctx.available_slots]
            targets={t:targets[t] for t in keep if targets[t]>0}
            before=sum(targets.values())
            if before>ctx.available_weight and before>0:targets={t:w*ctx.available_weight/before for t,w in targets.items()}
            metadata=dict(method=s['optimizer'],route='target_fusion',members=s['members'],blend_weights=self.blend_weights.tolist(),
                 member_forecast_ids=['single__'+m for m in s['members']],selected_count=len(targets),
                 target_exposure=sum(targets.values()),target_support_truncation=True,
                 solver_status='member_targets_blended_and_projected',
                 member_solver_statuses=[m.get('solver_status',m.get('status')) for m in details],
                 member_max_residual=max([float(m.get('gradient_mapping_inf',0.) or 0.) for m in details],default=0.),
                 member_max_gap_bound=max([float(m.get('optimality_gap_bound',0.) or 0.) for m in details],default=0.),
                 member_unconverged=sum(m.get('status')=='approx_unconverged' for m in details))
        zeros.update(targets)
        record=dict(signal_date=ctx.signal_date,strategy_id=s['strategy_id'],**clean(metadata))
        if 'risk_coverage' in record:record['risk_coverage_json']=json.dumps(record.pop('risk_coverage'),ensure_ascii=False)
        self.diagnostics.append(record)
        return HoldingAwareDecision(model_decisions=zeros,raw_model_outputs=clean(metadata))

def summarize(result,spec,seconds):
    d=result.daily;t=result.trades;nav=d.nav.astype(float);ret=np.log(nav/nav.shift()).dropna()
    dd=nav/nav.cummax()-1
    identity_cols=['nav_identity_error','cash_flow_identity_error','cost_identity_error','open_self_finance_error']
    errors={k:float(d[k].abs().max()) for k in identity_cols}
    if max(errors.values())>1e-5:raise AssertionError('ACCOUNT_IDENTITY_FAILED')
    if d.actual_name_count.max()>20 or d.cash.min()<-1e-6:raise AssertionError('ACCOUNT_CONSTRAINT_FAILED')
    orders=result.target_decisions
    if len(t) and (not t.order_id.isin(orders.order_id).all() or not result.execution_results.order_id.isin(orders.order_id).all()):raise AssertionError('BROKEN_ORDER_LINK')
    row={k:spec.get(k) for k in ['strategy_id','forecast_id','coalition','fusion','risk','optimizer','route','target_fusion']}
    row.update(year=ENV['year'],status='REPLAY_COMPLETE',seconds=seconds,initial_cash=1e6,
      terminal_nav=float(nav.iloc[-1]),net_return=float(nav.iloc[-1]/1e6-1),max_drawdown=float(dd.min()),
      annualized_log_vol=float(ret.std(ddof=0)*np.sqrt(252)),mean_daily_log_return=float(ret.mean()),
      mean_gross_exposure=float(d.gross_exposure.mean()),mean_cash_weight=float(d.cash_weight.mean()),
      total_fees=float(d.transaction_cost_amount.sum()),turnover=float(d.turnover.sum()),trades=len(t),
      max_names=int(d.actual_name_count.max()),signal_days=len(result.signal_contexts),
      stale_valuation_days=int(d.stale_count.gt(0).sum()),unknown_valuation_days=int(d.unknown_count.gt(0).sum()),
      formal_full_pool_test=False,blind_test=False,shareholder_return_certified=False,
      evidence_scope='upstream_available_pool_price_index' if ENV['year']==2025 else 'qualified_subset_retrospective_diagnostic',
      guard_fit_attempts=ENV['guard']['attempts'],**errors)
    return clean(row)

def prediction_order_links(result,spec):
    columns=['candidate','decision_id','order_id','signal_date','execution_date','ticker','decision_semantic',
             'model_input_row_present','decision_input_row_present','raw_model_weight','adapted_target_weight']
    frame=result.target_decisions[columns].copy()
    if spec['route']=='prediction_fusion':
        ids=[spec['forecast_id']]
    else:ids=['single__'+m for m in spec['members']]
    frame['forecast_ids_json']=json.dumps(ids)
    frame['prediction_key_suffix']=[str(d.date())+'|'+t if present else None for d,t,present in
         zip(frame.signal_date,frame.ticker,frame.model_input_row_present)]
    frame['prediction_id']=([ids[0]+'|'+str(s) if pd.notna(s) else None for s in frame.prediction_key_suffix]
         if len(ids)==1 else None)
    frame['risk']=spec['risk'];frame['optimizer']=spec['optimizer'];frame['route']=spec['route']
    return frame

def run_one(spec,resume=False):
    folder=ROOT/f'evaluation_{ENV["year"]}'/spec['strategy_id'];done=folder/'DONE.json'
    if done.exists():
        if not resume:raise RuntimeError('COMPLETED_REPLAY_EXISTS')
        record=read(done)
        for relative,expected in record.get('ledger_sha256',{}).items():
            if not (folder/relative).is_file() or sha(folder/relative)!=expected:raise RuntimeError('COMPLETED_LEDGER_HASH_MISMATCH')
        return record
    if folder.exists() and any(folder.iterdir()):
        # Preserve interrupted attempt, permit a separate deterministic retry directory.
        archive=folder/'attempts'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        if not archive.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('ATTEMPT_ARCHIVE_OUTSIDE_WORKSPACE')
        archive.mkdir(parents=True,exist_ok=True)
        for old_file in list(folder.iterdir()):
            if old_file.is_file():old_file.rename(archive/old_file.name)
        write(archive/'INTERRUPTED_ATTEMPT.json',dict(status='PRESERVED_INCOMPLETE_ATTEMPT',time=datetime.now(timezone.utc).isoformat()))
    folder.mkdir(parents=True,exist_ok=True)
    policy=Policy(spec);start=time.monotonic()
    try:
        with threadpool_limits(limits=1):
            result=run_replay(ENV['prices'],ENV['calendar'],ENV['panel'],policy,candidate=spec['strategy_id'],
              cost_bps=10,capacity_fraction=.01,signal_start=ENV['metadata']['signal_start'],signal_end=ENV['metadata']['signal_end'],
              signal_asof=ENV['asofs'],operational_exits_by_signal=ENV['ops'],prepared_inputs=ENV['prepared'])
        for name in LEDGERS:getattr(result,name).to_parquet(folder/(name+'.parquet'),index=False,compression='zstd')
        prediction_order_links(result,spec).to_parquet(folder/'prediction_order_links.parquet',index=False,compression='zstd')
        pd.DataFrame(policy.diagnostics).to_parquet(folder/'optimization_diagnostics.parquet',index=False,compression='zstd')
        if policy.member_targets:pd.DataFrame(policy.member_targets).to_parquet(folder/'member_targets.parquet',index=False,compression='zstd')
        write(folder/'metadata.json',result.metadata)
        row=summarize(result,spec,time.monotonic()-start)
        diag=pd.DataFrame(policy.diagnostics)
        if len(diag):
            statuses=diag['status'].fillna('fixed_rule') if 'status' in diag else pd.Series(['fixed_rule']*len(diag))
            row['optimizer_approx_unconverged_days']=int(statuses.eq('approx_unconverged').sum())
            row['optimizer_infeasible_days']=int(diag['feasible'].eq(False).sum()) if 'feasible' in diag else 0
            row['max_optimality_gap_bound']=float(diag.optimality_gap_bound.max()) if 'optimality_gap_bound' in diag else 0.
            row['max_gradient_mapping_inf']=float(diag.gradient_mapping_inf.max()) if 'gradient_mapping_inf' in diag else 0.
            row['target_blend_unconverged_member_days']=int(diag.member_unconverged.sum()) if 'member_unconverged' in diag else 0
        row['ledger_sha256']={p.name:sha(p) for p in sorted(folder.glob('*.parquet'))}
        row['model_batch_freeze_sha256']=sha(ROOT/'GLOBAL_FREEZE.json') if (ROOT/'GLOBAL_FREEZE.json').exists() else None
        write(done,row);return row
    except Exception as e:
        row={k:spec.get(k) for k in ['strategy_id','forecast_id','coalition','fusion','risk','optimizer','route','target_fusion']}
        row.update(year=ENV['year'],status='FAILED',failure_type=type(e).__name__,reason=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-start)
        write(folder/'FAILURE.json',row);return row

def chunk_worker(task):
    specs,resume=task
    ENV['forecasts'].clear()
    ENV['forecast_cache_limit']=len(specs[0]['members']) if specs[0]['route']=='target_fusion' else 1
    return [run_one(s,resume=resume) for s in specs]

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=[2025,2026],required=True);p.add_argument('--workers',type=int,default=8)
    p.add_argument('--resume',action='store_true');p.add_argument('--limit',type=int);p.add_argument('--forecast');a=p.parse_args()
    if a.year==2026:
        from freeze_batch import validate_global_freeze
        validate_global_freeze()
    specs=strategies()
    if a.forecast:specs=[s for s in specs if s['forecast_id']==a.forecast]
    if a.limit:specs=specs[:a.limit]
    out=ROOT/f'evaluation_{a.year}';out.mkdir(exist_ok=True)
    groups={}
    for s in specs:groups.setdefault((s['route'],s['forecast_id']),[]).append(s)
    tasks=[(group,a.resume) for group in groups.values()];rows=[]
    with ProcessPoolExecutor(max_workers=a.workers,initializer=initialize,initargs=(a.year,)) as pool:
        futures={pool.submit(chunk_worker,t):t[0][0]['forecast_id'] for t in tasks}
        for future in as_completed(futures):
            result=future.result();rows.extend(result)
            pd.DataFrame(rows).to_csv(out/'comparison_progress.csv',index=False)
            print(json.dumps(dict(year=a.year,finished=len(rows),expected=len(specs),last_group=futures[future],
                 failed=sum(r['status']=='FAILED' for r in rows))),flush=True)
    pd.DataFrame(rows).sort_values('strategy_id').to_csv(out/'comparison.csv',index=False)
    write(out/'COMPLETE.json',dict(expected=len(specs),completed=sum(r['status']=='REPLAY_COMPLETE' for r in rows),failed=sum(r['status']=='FAILED' for r in rows),
      status='ALL_ROUTES_ATTEMPTED',partial_diagnostic_run=bool(a.limit or a.forecast),formal_2026_full_pool_test=False,fit_attempts=sum(r.get('guard_fit_attempts',0) for r in rows)))

if __name__=='__main__':main()
