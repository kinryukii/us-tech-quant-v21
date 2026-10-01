"""Execute every predeclared feasible path; immutable inputs, independent cash."""
import argparse,time,traceback
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits
from shared import *
from fast_account import run_many
from market_runtime import prepare_market
from portfolio_policy import PortfolioPolicy

class LedgerWriter:
    def __init__(self,folder):
        self.folder=Path(folder);self.folder.mkdir(exist_ok=True,parents=True)
        self.writers={};self.schemas={};self.counts={};self.daily=[];self.solver=[]
        self.days=0;self.started=time.monotonic()
    def __call__(self,name,frame):
        if len(frame)==0:return
        if name=='daily':
            required=['path_id','date','nav','gross_exposure','cash_weight','transaction_cost_amount','turnover',
                'actual_name_count','certified_nav','stale_count','unknown_count','blocked_order_count']
            self.daily.append(frame[required].copy());self.days+=1
            if self.days%10==0:print(self.folder.name,'account_days',self.days,'date',frame.date.iloc[0],
                'elapsed',round(time.monotonic()-self.started,1),flush=True)
        if name=='optimization':
            stats=frame.groupby(['path_id','status']).agg(decisions=('iterations','size'),
                maximum_residual=('proximal_gradient_residual','max'),iterations=('iterations','sum')).reset_index()
            self.solver.append(stats)
        table=pa.Table.from_pandas(frame,preserve_index=False)
        if name not in self.writers:
            self.schemas[name]=table.schema;self.writers[name]=pq.ParquetWriter(self.folder/f'{name}.parquet',table.schema,compression='zstd')
        elif table.schema!=self.schemas[name]:table=table.cast(self.schemas[name])
        self.writers[name].write_table(table);self.counts[name]=self.counts.get(name,0)+len(frame)
    def close(self):
        for writer in self.writers.values():writer.close()
    def solver_summary(self):
        if not self.solver:return pd.DataFrame(columns=['path_id','status','decisions','maximum_residual','iterations'])
        return pd.concat(self.solver).groupby(['path_id','status']).agg(decisions=('decisions','sum'),
            maximum_residual=('maximum_residual','max'),iterations=('iterations','sum')).reset_index()

def summarize(daily,roster,year,solver):
    rows=[]
    for path,frame in daily.groupby('path_id',sort=False):
        frame=frame.sort_values('date');nav=frame.nav.to_numpy(float)
        growth=np.r_[1e6,nav];r=growth[1:]/growth[:-1]-1
        drawdown=growth/np.maximum.accumulate(growth)-1
        std=float(np.std(r,ddof=1));meanexpo=float(frame.gross_exposure.mean())
        selected=solver.loc[solver.path_id.eq(path)]
        limited=int(selected.loc[selected.status.eq('ITERATION_LIMIT'),'decisions'].sum()) if len(selected) else 0
        # Previous-day invested fraction is the observable capital at risk.
        expo=np.r_[0.,frame.gross_exposure.to_numpy(float)[:-1]];active=expo>.01
        normalized=float(np.mean(r[active]/expo[active])) if active.any() else None
        row={'path_id':path,'year':year,'research_status':'REPLAY_COMPLETE_WITH_APPROXIMATE_SOLVES' if limited else 'REPLAY_COMPLETE',
            'indicative_return':float(nav[-1]/1e6-1),'indicative_max_drawdown':float(drawdown.min()),
            'annualized_volatility':std*np.sqrt(252),'sharpe_zero_rf':float(np.mean(r)/std*np.sqrt(252)) if std>0 else None,
            'mean_gross_exposure':meanexpo,'mean_cash_weight':float(frame.cash_weight.mean()),
            'total_fees':float(frame.transaction_cost_amount.sum()),'turnover':float(frame.turnover.sum()),
            'max_actual_names':int(frame.actual_name_count.max()),'uncertified_nav_days':int(frame.certified_nav.isna().sum()),
            'stale_valuation_days':int(frame.stale_count.gt(0).sum()),'unknown_valuation_days':int(frame.unknown_count.gt(0).sum()),
            'blocked_orders':int(frame.blocked_order_count.sum()),'optimization_iteration_limit_decisions':limited,
            'solver_max_proximal_residual':float(selected.maximum_residual.max()) if len(selected) else None,
            'mean_daily_return_per_previous_invested_fraction':normalized,'active_exposure_days':int(active.sum()),
            'formal_full_pool_status':'BLOCKED_DATA' if year==2026 else 'HISTORICAL_INPUT_LIMITATIONS',
            'shareholder_total_return_certified':False,'blind_test':False,'cost_bps':10,'days':len(frame)}
        rows.append(row)
    result=pd.DataFrame(rows).merge(roster,on='path_id',how='left',validate='one_to_one')
    return result

def forbidden_fit_guard():
    # Runtime guard is additional to physical source isolation and hash binding.
    import sklearn.base
    original=sklearn.base.BaseEstimator.__getattribute__
    def guarded(self,name):
        value=original(self,name)
        if name in ['fit','partial_fit','fit_transform','fit_predict'] and callable(value):
            def forbidden(*args,**kwargs):raise RuntimeError('FITTING_FORBIDDEN_DURING_FROZEN_REPLAY')
            return forbidden
        return value
    sklearn.base.BaseEstimator.__getattribute__=guarded
    return lambda:setattr(sklearn.base.BaseEstimator,'__getattribute__',original)

def run_year(year):
    if year==2026:
        from freeze_batch import verify_freeze
        verify_freeze()
    destination=ROOT/'results'/f'evaluation_{year}'
    destination.mkdir(parents=True,exist_ok=True)
    if (destination/'COMPLETE.json').exists():return read_json(destination/'COMPLETE.json')
    predictions=ROOT/'predictions'/f'evaluation_{year}'
    if not (predictions/'COMPLETE.json').exists():raise RuntimeError('FULL_FROZEN_PREDICTIONS_REQUIRED')
    prediction_receipt=read_json(predictions/'COMPLETE.json')
    for name,expected in prediction_receipt['artifacts'].items():
        if sha(predictions/name)!=expected:raise RuntimeError('FROZEN_PREDICTION_CHANGED:'+name)
    roster=paths();coverage=pd.read_csv(predictions/'STREAM_COVERAGE.csv')
    available=set(coverage.loc[coverage.status.eq('AVAILABLE'),'stream_id'])
    stream_keys=roster.group+'__'+roster.fusion
    runnable=roster.loc[roster.layer.ne('rl_control')&stream_keys.isin(available)].copy()
    failed=roster.loc[roster.layer.ne('rl_control')&~stream_keys.isin(available)].copy()
    failed['year']=year;failed['research_status']='FAILED_PREDICTION_OR_FUSION';failed['failure_reason']='required declared member/calibration/fusion unavailable; no substitute member'
    prepared=prepare_market(year);market=prepared.market
    forecast=np.load(predictions/'forecast_cube.npz');risk_cache=np.load(predictions/'risk_cache.npz')
    if not np.array_equal(forecast['tickers'],market.tickers) or not np.array_equal(forecast['dates'],market.dates.to_numpy()):raise RuntimeError('MARKET_FORECAST_MISMATCH')
    summaries=[];receipts=[]
    # Run all forecast/risk rows together: covariance algebra stays vectorized,
    # while units, cash, pending orders and fills remain independent per row.
    for category in ['pto','target_fusion','rl_control']:
        selection=runnable.loc[runnable.layer.eq(category)].copy() if category!='rl_control' else roster.loc[roster.layer.eq(category)].copy()
        if selection.empty:continue
        folder=destination/category
        if (folder/'DONE.json').exists():
            summaries.append(pd.read_csv(folder/'SUMMARY.csv'));receipts.append(read_json(folder/'DONE.json'));continue
        if folder.exists():raise RuntimeError('PRESERVE_INTERRUPTED_REPLAY_FOLDER:'+str(folder))
        writer=LedgerWriter(folder);started=time.monotonic()
        print(year,category,len(selection),'START',flush=True)
        if category=='rl_control':
            from rl_control import RLRuntime
            actor=RLRuntime('validation' if year==2025 else 'final',feature_cube=prepared.features)
        else:
            actor=PortfolioPolicy(selection,forecast,risk_cache,diagnostic_callback=lambda frame:writer('optimization',frame))
        restore_guard=forbidden_fit_guard()
        try:
            with threadpool_limits(limits=2):
                result=run_many(market,selection.path_id.tolist(),actor,collect_ledgers=False,ledger_callback=writer)
        except Exception:
            write_json(folder/'FAILED_ATTEMPT.json',{'status':'IMPLEMENTATION_OR_RUNTIME_FAILURE','traceback':traceback.format_exc(),
                'elapsed':time.monotonic()-started,'roster_path_ids':selection.path_id.tolist(),'records':writer.counts})
            raise
        finally:restore_guard();writer.close()
        daily=pd.concat(writer.daily,ignore_index=True);solver=writer.solver_summary()
        solver.to_csv(folder/'SOLVER_SUMMARY.csv',index=False)
        summary=summarize(daily,selection,year,solver);summary.to_csv(folder/'SUMMARY.csv',index=False)
        receipt={'status':'ACCOUNT_REPLAY_COMPLETE','year':year,'category':category,'paths':len(selection),'fit_calls':0,
            'seconds':time.monotonic()-started,'records':writer.counts,'engine_audit':result.audit,'metadata':result.metadata,
            'source_binding':{name:sha(ROOT/name) for name in ['run_suite.py','fast_account.py','portfolio_policy.py','market_runtime.py','optimization.py','rl_control.py']},
            'artifacts':{p.name:sha(p) for p in folder.iterdir() if p.is_file()}}
        write_json(folder/'DONE.json',receipt);summaries.append(summary);receipts.append(receipt)
        print(year,category,len(selection),'COMPLETE',round(time.monotonic()-started,2),flush=True)
    combined=pd.concat([*summaries,failed],ignore_index=True)
    if len(combined)!=len(roster) or combined.path_id.duplicated().any():raise RuntimeError('DECLARED_PATH_COVERAGE_INCOMPLETE')
    combined.to_csv(destination/'ALL_PATHS.csv',index=False)
    if year==2026:
        from freeze_batch import verify_freeze
        verify_freeze()
    receipt={'status':'ALL_DECLARED_PATHS_RESOLVED','year':year,'declared':len(roster),'replayed':sum(r['paths'] for r in receipts),
        'failed_prediction_paths':len(failed),'all_results_included':True,'full_pool_formal_status':'BLOCKED_DATA' if year==2026 else 'HISTORICAL_INPUT_LIMITATIONS',
        'receipts':receipts,'coverage_sha256':sha(destination/'ALL_PATHS.csv')}
    write_json(destination/'COMPLETE.json',receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True,choices=[2025,2026]);a=p.parse_args();print(run_year(a.year)['status'],flush=True)
