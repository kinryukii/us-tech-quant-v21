"""Frozen stage-specific replay; no model fitting is permitted here."""
from pathlib import Path
import argparse, hashlib, json, time
import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits
from engine_v2 import run_replay, OperationalExit
from adapters import PolicyV2
from linear_train import FEATURES
from risk_aux import FrozenDiagnostics

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent/'a2_latest_effective_joint_20260927'
QUAL = ROOT.parent/'a2_qualification_holdings_v1_20260927'
STRICT = ROOT.parent/'a2_strict_method_retrain_20260926'
NAMES = ['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb',
         'joint_q10','joint_q50','joint_q90','joint_quantile_risk','joint_mlp',
         'joint_rl_ensemble','joint_rl_zero_control','cash_control','joint_hgb_lw','joint_hgb_pca']
LEDGERS = ['daily','trades','positions','target_decisions','diagnostics','valuation_intervals',
           'raw_model_outputs','signal_contexts','operational_actions','execution_results']

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(np.floating,float)):return float(x) if np.isfinite(x) else None
    if isinstance(x,(Path,pd.Timestamp)):return str(x)
    return x

def write(path,x):Path(path).write_text(json.dumps(clean(x),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def forbid_fit():
    from sklearn.ensemble import HistGradientBoostingRegressor,IsolationForest
    from sklearn.linear_model import Ridge,ElasticNet,LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.covariance import LedoitWolf
    from sklearn.pipeline import Pipeline
    count={'attempts':0}
    def denied(*a,**k):count['attempts']+=1;raise RuntimeError('FITTING_FORBIDDEN_IN_REPLAY')
    for cls in [HistGradientBoostingRegressor,IsolationForest,Ridge,ElasticNet,LogisticRegression,
                StandardScaler,KMeans,LedoitWolf,Pipeline]:
        for method in ['fit','partial_fit','fit_transform']:
            if hasattr(cls,method):setattr(cls,method,denied)
    torch.optim.Adam.step=denied
    torch.Tensor.backward=denied
    return count

def inputs(year):
    if year==2026:
        pp=QUAL/'data/test_features_context.parquet';xp=QUAL/'data/test_prices.parquet'
        cp=OLD/'data/calendar.parquet'
        panel=pd.read_parquet(pp);prices=pd.read_parquet(xp)
        calendar=pd.DatetimeIndex(pd.read_parquet(cp).query('is_test').trade_date)
        last='2026-09-22';paths=[pp,xp,cp,QUAL/'data/operational_exit_evidence.csv']
    else:
        pp=OLD/'data/pre2026_joint_context.parquet'
        xp=STRICT/'results/pre2026_original_price_coordinate.parquet'
        panel=pd.read_parquet(pp).query('signal_date >= "2025-01-01"').copy()
        prices=pd.read_parquet(xp)
        calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
        last='2025-12-29';paths=[pp,xp]
    panel=panel.loc[panel.signal_date.le(last),['signal_date','ticker','new_buy_eligible']+list(FEATURES)].copy()
    assert np.isfinite(panel[FEATURES].to_numpy(float)).all()
    assert panel.signal_date.dt.year.eq(year).all() and not panel.duplicated(['signal_date','ticker']).any()
    early={'2025-07-03','2025-11-28','2025-12-24','2026-11-27','2026-12-24'}
    asofs={d:(d+pd.Timedelta(hours=13 if str(d.date()) in early else 16)).tz_localize('America/New_York').tz_convert('UTC') for d in calendar}
    ops={}
    if year==2026:
        ev=pd.read_csv(paths[-1]);ev['known_at']=pd.to_datetime(ev.known_at,utc=True)
        ev['effective_date']=pd.to_datetime(ev.effective_date)
        for d in calendar:
            known=ev[(ev.known_at<=asofs[d])&(ev.effective_date<=d)]
            if len(known):ops[d]={str(r.ticker):OperationalExit(str(r.reason),r.known_at,str(r.source_id)) for r in known.itertuples()}
    return panel,prices,calendar,last,asofs,ops,paths

def audit_result(r,cost,panel):
    d,t,p,a=r.daily,r.trades,r.positions,r.target_decisions
    assert d.cash.ge(-1e-6).all() and d.actual_name_count.le(20).all()
    cash=1e6;maximum_error=0.;units={}
    byday={k:g for k,g in t.groupby('execution_date')}
    pos={k:g for k,g in p.groupby('date')}
    for row in d.itertuples():
        trades=byday.get(row.date,t.iloc[:0])
        for z in trades.itertuples():
            sign=1 if z.side=='BUY' else -1
            cash-=sign*z.notional+z.transaction_cost
            units[z.ticker]=units.get(z.ticker,0)+sign*z.index_units
            assert z.execution_date>z.signal_date
            assert abs(z.transaction_cost-z.notional*cost/10000)<1e-7
            assert abs(z.index_units*z.price-z.notional)<1e-6
        maximum_error=max(maximum_error,abs(cash-row.cash))
        assert abs(cash-row.cash)<1e-5
        positions=pos.get(row.date,p.iloc[:0])
        actual=dict(zip(positions.ticker,positions.index_units))
        for ticker in set(units)|set(actual):
            assert abs(units.get(ticker,0)-actual.get(ticker,0))<1e-7
        if np.isfinite(row.nav):assert abs(row.nav-row.cash-positions.market_value.sum())<1e-5
    if len(t):
        buys=t[t.side.eq('BUY')].merge(a[['order_id','signal_day_adv']],on='order_id',validate='one_to_one')
        buys=buys.merge(panel[['signal_date','ticker','new_buy_eligible']],on=['signal_date','ticker'],how='left',validate='many_to_one')
        assert buys.new_buy_eligible.notna().all()
        assert buys.new_buy_eligible.all()
        assert (buys.notional<=.01*buys.signal_day_adv+1e-6).all()
    assert a.target_weight.dropna().ge(-1e-10).all()
    # Reserved existing positions can drift above caps. Model-requested weights cannot.
    assert a.raw_model_weight.dropna().le(.1+1e-7).all()
    return dict(status='PASS',independent_cash_error_max=maximum_error,
                max_actual_names=int(d.actual_name_count.max()),days=len(d),trades=len(t))

def metrics(r,name,year,cost):
    d=r.daily;nav=d.nav.to_numpy(float)
    certified=bool(d.certified_nav.notna().all())
    dd=float(np.min(np.r_[1e6,nav]/np.maximum.accumulate(np.r_[1e6,nav])-1)) if certified and year==2025 else None
    t=r.target_decisions;tr=r.trades
    return dict(policy=name,year=year,cost_bps=cost,days=len(d),trades=len(tr),
                indicative_return=nav[-1]/1e6-1 if np.isfinite(nav[-1]) else None,
                max_drawdown_2025_certified=dd,mean_cash=float(d.cash_weight.mean()),
                last_cash=float(d.cash_weight.iloc[-1]),fees=float(d.transaction_cost_amount.sum()),
                half_turnover=float(d.turnover.sum()),uncertified_days=int(d.certified_nav.isna().sum()),
                actual_names_max=int(d.actual_name_count.max()),
                active_exit_decisions=int(t.decision_semantic.eq('MODEL_ACTIVE_EXIT').sum()),
                no_decision_held=int((t.decision_semantic.eq('MODEL_NO_DECISION')&t.current_units.gt(0)).sum()),
                buys=int(tr.side.eq('BUY').sum()),sells=int(tr.side.eq('SELL').sum()),
                complete_original_pool=False if year==2026 else None,blind_test=False)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,choices=[2025,2026],required=True)
    ap.add_argument('--cost',type=float,choices=[5,10,25],default=10);args=ap.parse_args()
    year,cost=args.year,args.cost;stage='validation' if year==2025 else 'final'
    out=ROOT/f'evaluation_{year}'/f'cost_{cost:g}'
    if (out/'COMPLETE.json').exists():raise RuntimeError('COMPLETED_RESULT_PRESERVED')
    out.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/n for n in ['EXPERIMENT_CONTRACT.md','SCOPE.md','run_experiment.py','adapters.py','engine_v2.py','linear_train.py','neural_train.py','risk_aux.py']]
    for folder in ['linear_artifacts','neural_artifacts','risk_artifacts']:
        assert (ROOT/folder).exists(),folder
        paths += [p for p in (ROOT/folder).rglob('*') if p.suffix in ['.joblib','.pt','.npz','.json']]
    # Refuse starting evaluation before all prespecified training receipts exist.
    for folder,name in [('linear_artifacts','FIT_RECEIPT.json'),('neural_artifacts','TRAIN_RECEIPT.json'),('risk_artifacts','TRAIN_RECEIPT.json')]:
        assert (ROOT/folder/name).exists(),f'MISSING_COMPLETED_TRAINING:{folder}/{name}'
    guard=forbid_fit()
    panel,prices,calendar,last,asofs,ops,input_paths=inputs(year)
    paths+=input_paths
    binding=dict(stage=stage,year=year,cost_bps=cost,roster=NAMES,
                 source_sha256={str(p.resolve()):sha(p) for p in paths},
                 fit_attempts=0,blind_test=False,full_original_pool=False if year==2026 else None)
    frozen=out/'FROZEN_BEFORE_REPLAY.json'
    if frozen.exists():
        assert json.loads(frozen.read_text(encoding='utf-8'))==binding,'RESTART_BINDING_CHANGED'
    else:write(frozen,binding)
    diag=pd.concat([panel[['signal_date','ticker']],FrozenDiagnostics(stage=stage).predict(panel)],axis=1)
    diag.to_parquet(out/'state_diagnostics.parquet',index=False)
    rows=[]
    for name in NAMES:
        folder=out/name
        if (folder/'PATH_COMPLETE.json').exists():
            receipt=json.loads((folder/'PATH_COMPLETE.json').read_text(encoding='utf-8'))
            assert all(sha(folder/f'{k}.parquet')==v for k,v in receipt['ledger_sha256'].items())
            rows.append(receipt['metrics']);continue
        if folder.exists():raise RuntimeError(f'PARTIAL_PATH_REQUIRES_INSPECTION:{folder}')
        folder.mkdir();start=time.monotonic()
        actor=PolicyV2(name,stage=stage)
        with threadpool_limits(limits=2):
            r=run_replay(prices,calendar,panel,actor,candidate=name,cost_bps=cost,capacity_fraction=.01,
                         signal_start=f'{year}-01-01',signal_end=last,signal_asof=asofs,operational_exits_by_signal=ops)
        for key in LEDGERS:getattr(r,key).to_parquet(folder/f'{key}.parquet',index=False)
        write(folder/'metadata.json',r.metadata)
        audit=audit_result(r,cost,panel);row=metrics(r,name,year,cost);row['seconds']=time.monotonic()-start
        write(folder/'PATH_COMPLETE.json',dict(audit=audit,metrics=row,ledger_sha256={k:sha(folder/f'{k}.parquet') for k in LEDGERS}))
        rows.append(row);pd.DataFrame(rows).to_csv(out/'comparison.csv',index=False)
        print(json.dumps(clean(row)),flush=True)
    assert guard['attempts']==0
    assert all(sha(p)==h for p,h in binding['source_sha256'].items()),'FROZEN_INPUT_CHANGED'
    pd.DataFrame(rows).to_csv(out/'comparison.csv',index=False)
    write(out/'COMPLETE.json',dict(status='PASS',policies=len(rows),fit_attempts=guard['attempts'],sources_unchanged=True,year=year,cost_bps=cost))

if __name__=='__main__':main()
