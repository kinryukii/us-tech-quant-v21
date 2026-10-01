"""Run the complete preregistered grid; no learning and no result-based selection."""
from common import *
import argparse, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from threadpoolctl import threadpool_limits
from batch_engine import BatchMarket,run_batch,OperationalExit
from policy import PTOBatchPolicy,StreamBank
import torch
torch.set_num_threads(1)
_MARKET=None
_STREAMS=None

def inputs(year):
    stage='validation' if year==2025 else 'final'
    prefix='pre' if year==2025 else 'test'
    panel=pd.read_parquet(ROOT/f'data/{prefix}.parquet')
    panel=panel.loc[pd.to_datetime(panel.signal_date).dt.year.eq(year)].copy()
    end=pd.Timestamp('2025-12-29' if year==2025 else '2026-09-22')
    panel=panel.loc[panel.signal_date.le(end),['signal_date','ticker','new_buy_eligible']+FEATURES+
        (['context_only_if_held'] if 'context_only_if_held' in panel else [])]
    panel['signal_date']=pd.to_datetime(panel.signal_date)
    if not np.isfinite(panel[FEATURES].to_numpy(float)).all():raise RuntimeError('NONFINITE_LEGAL_REPLAY_INPUT')
    prices=pd.read_parquet(ROOT/f'data/{prefix}_prices.parquet')
    cf=pd.read_parquet(ROOT/f'data/{prefix}_calendar.parquet')
    calendar=pd.DatetimeIndex(pd.to_datetime(cf['trade_date'] if 'trade_date' in cf else cf.iloc[:,0]))
    calendar=calendar[calendar.year==year]
    early={'2025-07-03','2025-11-28','2025-12-24','2026-11-27','2026-12-24'}
    asofs={d:(d+pd.Timedelta(hours=13 if str(d.date()) in early else 16)).tz_localize('America/New_York').tz_convert('UTC') for d in calendar}
    ops={}
    if year==2026:
        ev=pd.read_csv(ROOT/'data/test_operational_exit_evidence.csv')
        if len(ev):
            ev['known_at']=pd.to_datetime(ev.known_at,utc=True);ev['effective_date']=pd.to_datetime(ev.effective_date)
            for d in calendar:
                known=ev[(ev.known_at<=asofs[d])&(ev.effective_date<=d)]
                if len(known):ops[d]={str(r.ticker):OperationalExit(str(r.reason),r.known_at,str(r.source_id)) for r in known.itertuples()}
    names=set(panel.ticker)|{t for op in ops.values() for t in op}
    prices=prices.loc[prices.ticker.isin(names)].copy()
    return panel,prices,calendar,end,asofs,ops

def initializer(year):
    global _MARKET,_STREAMS
    started=time.time();print('INITIALIZE_INPUTS',year,flush=True)
    panel,prices,calendar,end,asofs,ops=inputs(year)
    print('INPUTS_READY',year,round(time.time()-started,2),flush=True)
    _MARKET=BatchMarket(prices,calendar,panel,signal_start=panel.signal_date.min(),signal_end=end,signal_asof=asofs,operational_exits_by_signal=ops)
    _STREAMS=StreamBank('validation' if year==2025 else 'final',_MARKET.tickers)
    print('INITIALIZED',year,len(_MARKET.tickers),round(time.time()-started,2),flush=True)

def forbid_learning():
    def deny(*a,**k):raise RuntimeError('LEARNING_FORBIDDEN_IN_ACCOUNT_REPLAY')
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge,ElasticNet,HuberRegressor,LogisticRegression
    from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier,RandomForestRegressor,ExtraTreesRegressor
    from sklearn.covariance import LedoitWolf,OAS
    from sklearn.decomposition import FactorAnalysis
    from sklearn.pipeline import Pipeline
    for cls in [StandardScaler,Ridge,ElasticNet,HuberRegressor,LogisticRegression,HistGradientBoostingRegressor,
        HistGradientBoostingClassifier,RandomForestRegressor,ExtraTreesRegressor,LedoitWolf,OAS,FactorAnalysis,Pipeline]:
        for method in ['fit','partial_fit','fit_transform']:
            if hasattr(cls,method):setattr(cls,method,deny)
    torch.Tensor.backward=deny
    torch.optim.Adam.step=deny

def metrics(daily):
    results=[]
    for name,d in daily.groupby('strategy_id',sort=False):
        d=d.sort_values('date');nav=d.nav.to_numpy(float);history=np.r_[1e6,nav]
        finite=np.isfinite(history).all();ret=np.r_[0.,np.diff(history)/history[:-1]]
        exposure=d.gross_exposure.to_numpy(float)
        fees=d.transaction_cost_amount.to_numpy(float)
        prior=history[:-1]
        positions=(d.actual_name_count.to_numpy(int)>0)
        excess=(np.diff(history)+fees)/prior
        previous_exposure=np.r_[0.,exposure[:-1]]
        normalized=np.divide(excess,previous_exposure,out=np.full_like(excess,np.nan),where=previous_exposure>.01)
        results.append({'strategy':name,'indicative_return':nav[-1]/1e6-1 if finite else None,
            'indicative_max_drawdown':float(np.min(history/np.maximum.accumulate(history)-1)) if finite else None,
            'certified_days':int(d.valuation_status.eq('certified').sum()),'uncertified_days':int(d.valuation_status.ne('certified').sum()),
            'mean_gross_exposure':float(np.nanmean(exposure)),'mean_cash':float(d.cash_weight.mean()),
            'fees':float(fees.sum()),'half_turnover':float(d.turnover.sum()),'traded_notional':float(d.traded_notional.sum()),
            'max_names':int(d.actual_name_count.max()),'holding_days':int(positions.sum()),'days':len(d),
            'exposure_normalized_daily_mean':float(np.nanmean(normalized)) if np.isfinite(normalized).any() else None,
            'normalized_days':int(np.isfinite(normalized).sum()),
            'max_cash_identity_error':float(d.cash_flow_identity_error.abs().max()),
            'max_nav_identity_error':float(d.nav_identity_error.abs().max()),
            'max_cost_identity_error':float(d.cost_identity_error.abs().max())})
    return results

def group_task(task):
    year,number,paths=task;stage='validation' if year==2025 else 'final'
    out=ROOT/f'results/{year}/batch_{number:03d}'
    complete=out/'COMPLETE.json'
    if complete.exists():return json.loads(complete.read_text(encoding='utf-8'))
    if out.exists() and any(out.iterdir()):raise RuntimeError('PARTIAL_REPLAY_REQUIRES_AUDITED_RESUME:'+str(out))
    started=time.time();out.mkdir(parents=True,exist_ok=True)
    policy=PTOBatchPolicy(paths,stage,_MARKET.tickers,stream_bank=_STREAMS)
    forbid_learning()
    try:
        with threadpool_limits(limits=1):
            result=run_batch(_MARKET,policy,[p['strategy'] for p in paths],output_dir=out,max_batch_size=384)
        summary=metrics(result.daily);pd.DataFrame(summary).to_csv(out/'SUMMARY.csv',index=False)
        write_json(out/'POLICY_RECEIPT.json',{'solver_counts':policy.solver_counts,'failures':policy.failures,
            'risk_fallback_counts':policy.risk.fallback_counts,'scenario_approximations':policy.risk.scenario_approximations,
            'fit_calls':0,'stage':stage,'year':year})
        record={'status':'REPLAYED','year':year,'batch':number,'strategies':[p['strategy'] for p in paths],
            'accounts':len(paths),'days':len(_MARKET.calendar),'seconds':time.time()-started,
            'scope':'AVAILABLE_PRE2026_RESEARCH_CONTEXT' if year==2025 else 'QUALIFIED_SUBPOOL_DIAGNOSTIC',
            'formal_full_pool':False,'metadata_sha256':sha(out/'metadata.json'),'summary_sha256':sha(out/'SUMMARY.csv'),
            'policy_sha256':sha(ROOT/'policy.py'),'engine_sha256':sha(ROOT/'batch_engine.py'),'new_fit_calls':0}
        write_json(complete,record);return record
    except Exception as e:
        record={'status':'FAILED','year':year,'batch':number,'strategies':[p['strategy'] for p in paths],
            'reason':str(e),'traceback':traceback.format_exc(),'seconds':time.time()-started}
        write_json(out/'FAILED.json',record);return record

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=[2025,2026],required=True)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--batch',type=int);a=p.parse_args()
    if a.year==2026:
        freeze=json.loads((ROOT/'FREEZE.json').read_text(encoding='utf-8'))
        if freeze['status']!='FROZEN_ALL_LEARNING_PRE2026':raise RuntimeError('FULL_BATCH_FREEZE_REQUIRED')
        for path,h in freeze['artifact_sha256'].items():
            if sha(ROOT/path)!=h:raise RuntimeError('FROZEN_ARTIFACT_CHANGED:'+path)
    paths=json.loads((ROOT/'REGISTRY.json').read_text(encoding='utf-8'))['strategies']
    tasks=[];index=0
    for risk in RISKS:
        for opt in OPTIMIZERS:
            group=[x for x in paths if x['risk']==risk and x['optimizer']==opt]
            tasks.append((a.year,index,group));index+=1
    if a.batch is not None:tasks=[t for t in tasks if t[1]==a.batch]
    output=ROOT/f'results/{a.year}';output.mkdir(parents=True,exist_ok=True)
    records=[]
    with ProcessPoolExecutor(max_workers=a.workers,initializer=initializer,initargs=(a.year,)) as pool:
        futures=[pool.submit(group_task,t) for t in tasks]
        for future in as_completed(futures):
            record=future.result();records.append(record)
            print(record['year'],record['batch'],record['status'],round(record['seconds'],1),flush=True)
            write_json(output/'PROGRESS.json',{'completed_batches':records,'registered_accounts':len(paths)})
    if a.batch is None:write_json(output/'ALL_BATCHES.json',{'records':records,'registered_accounts':len(paths)})

if __name__=='__main__':main()
