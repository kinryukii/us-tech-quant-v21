"""Frozen inference only, using the existing holding-aware independent ledger."""
from pathlib import Path
import argparse
import hashlib
import json
import time
import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits
from adapters import PolicyV2
from engine_v2 import run_replay, OperationalExit
from values import FEATURES

ROOT = Path(__file__).resolve().parent
WS = ROOT.parent
DATA = WS/'a2_latest_effective_joint_20260927/data'
QUALIFIED = WS/'a2_qualification_holdings_v1_20260927/data'
TEST_DATA = ROOT/'data'
PRICE = WS/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
NAMES = ['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb',
         'joint_q10','joint_q50','joint_q90','joint_quantile_risk','joint_mlp',
         'joint_rl_ensemble','joint_rl_zero_control','cash_control','joint_hgb_lw','joint_hgb_pca',
         'ensemble_equal_weight','ensemble_stacked']
LEDGERS = ['daily','trades','positions','target_decisions','diagnostics',
           'valuation_intervals','raw_model_outputs','signal_contexts',
           'operational_actions','execution_results']

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    if isinstance(v,(np.floating,float)): return float(v) if np.isfinite(v) else None
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(pd.Timestamp,Path)): return str(v)
    return v

def write(path,v):
    Path(path).write_text(json.dumps(clean(v),indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def forbid_fitting():
    from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
    from sklearn.linear_model import Ridge, ElasticNet, LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.covariance import LedoitWolf
    from sklearn.pipeline import Pipeline
    count={'attempts':0}
    def denied(*args,**kwargs):
        count['attempts']+=1
        raise RuntimeError('FIT_FORBIDDEN_DURING_EVALUATION')
    for cls in [HistGradientBoostingRegressor,IsolationForest,Ridge,ElasticNet,LogisticRegression,
                StandardScaler,KMeans,LedoitWolf,Pipeline]:
        for name in ['fit','partial_fit','fit_transform']:
            if hasattr(cls,name): setattr(cls,name,denied)
    torch.optim.Adam.step=denied
    torch.optim.SGD.step=denied
    return count

def clocks(calendar):
    early={'2025-07-03','2025-11-28','2025-12-24','2026-11-27','2026-12-24'}
    assert all(d.year in (2025,2026) for d in calendar)
    return {d:(d+pd.Timedelta(hours=13 if str(d.date()) in early else 16))
            .tz_localize('America/New_York').tz_convert('UTC') for d in calendar}

def operations(calendar,asofs):
    df=pd.read_csv(QUALIFIED/'operational_exit_evidence.csv')
    if df.empty: return {}
    df['known_at']=pd.to_datetime(df.known_at,utc=True)
    df['effective_date']=pd.to_datetime(df.effective_date)
    return {d:{str(r.ticker):OperationalExit(str(r.reason),r.known_at,str(r.source_id))
               for r in df[(df.known_at<=asofs[d])&(df.effective_date<=d)].itertuples()}
            for d in calendar}

def model_files():
    files=[ROOT/'EXPERIMENT_CONTRACT.md',ROOT/'ENSEMBLE_CONTRACT.md',ROOT/'DATA_ADMISSIBILITY_ADDENDUM.md']+list(ROOT.glob('*.py'))
    for folder in ['value_artifacts','neural_artifacts','risk_artifacts','aux_artifacts','ensemble_artifacts']:
        files += [p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.joblib','.pt','.npz','.json','.parquet')]
    return sorted(set(files))

def summarize(result,name,year,cost):
    d=result.daily; t=result.trades; target=result.target_decisions
    nav=d.nav.astype(float)
    steps=pd.concat([pd.Series([1e6]),nav],ignore_index=True).pct_change(fill_method=None).iloc[1:]
    std=steps.std(ddof=1)
    growth=pd.concat([pd.Series([1e6]),nav],ignore_index=True)
    dd=growth/growth.cummax()-1
    certified=bool(year==2025 and d.certified_nav.notna().all())
    return dict(policy=name,year=year,cost_bps=cost,days=len(d),
        indicative_return=float(nav.iloc[-1]/1e6-1),
        indicative_max_drawdown=float(dd.min()),
        indicative_annualized_volatility=float(std*np.sqrt(252)),
        indicative_sharpe_zero_rf=float(steps.mean()/std*np.sqrt(252)) if std>0 else None,
        certified_retrospective_return=float(nav.iloc[-1]/1e6-1) if certified else None,
        formal_2026_performance=False,
        mean_cash_weight=float(d.cash_weight.mean()),mean_gross_exposure=float(d.gross_exposure.mean()),
        total_cost_dollars=float(d.transaction_cost_amount.sum()),turnover=float(d.turnover.sum()),
        trades=len(t),max_actual_names=int(d.actual_name_count.max()),
        uncertified_valuation_days=int(d.certified_nav.isna().sum()),
        model_active_exits=int(target.decision_semantic.eq('MODEL_ACTIVE_EXIT').sum()) if len(target) else 0,
        model_no_decisions=int(target.decision_semantic.eq('MODEL_NO_DECISION').sum()) if len(target) else 0,
        execution_rejections=int(result.execution_results.status.eq('REJECTED').sum()) if len(result.execution_results) else 0,
        metric_status='RETROSPECTIVE_PRICE_INDEX_2025' if certified else 'INDICATIVE_ONLY_RESTRICTED_POOL_AND_INPUT_QUALIFICATION')

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True,choices=[2025,2026])
    p.add_argument('--cost',type=float,default=10);p.add_argument('--resume',action='store_true')
    a=p.parse_args();year=a.year
    assert a.cost in (5,10,25) and (year==2026 or a.cost==10)
    out=ROOT/f'evaluation_{year}'/f'cost_{a.cost:g}';out.mkdir(parents=True,exist_ok=True)
    if (out/'COMPLETE.json').exists():raise RuntimeError('COMPLETED_EVALUATION_ALREADY_EXISTS')
    for required in ['value_artifacts/FIT_RECEIPT.json','neural_artifacts/TRAIN_RECEIPT.json']:
        assert (ROOT/required).is_file(),required
    guard=forbid_fitting()
    if year==2026:
        sources=[TEST_DATA/'test_features_context.parquet',TEST_DATA/'test_prices.parquet',
                 DATA/'calendar.parquet',QUALIFIED/'operational_exit_evidence.csv',TEST_DATA/'ADMISSIBILITY_RECEIPT.json',
                 QUALIFIED/'test_features_context.parquet',QUALIFIED/'test_prices.parquet',TEST_DATA/'GLW_EVIDENCE_BINDING.json']
        panel=pd.read_parquet(sources[0]);prices=pd.read_parquet(sources[1])
        calendar=pd.DatetimeIndex(pd.read_parquet(sources[2]).query('is_test').trade_date)
        last='2026-09-22';stage='final'
    else:
        sources=[DATA/'pre2026_joint_context.parquet',PRICE]
        panel=pd.read_parquet(sources[0]);panel=panel.loc[panel.signal_date.ge('2025-01-01')].copy()
        prices=pd.read_parquet(PRICE)
        calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
        last='2025-12-29';stage='validation'
    panel=panel.loc[panel.signal_date.le(last),['signal_date','ticker','new_buy_eligible',*FEATURES]].copy()
    assert panel.signal_date.dt.year.eq(year).all()
    assert not panel.duplicated(['signal_date','ticker']).any()
    assert np.isfinite(panel[FEATURES].to_numpy(float)).all()
    hashes={str(x):sha(x) for x in model_files()+sources}
    frozen=out/'FROZEN_BEFORE_REPLAY.json'
    binding=dict(created_utc=pd.Timestamp.now(tz='UTC').isoformat(),year=year,cost_bps=a.cost,
        roster=NAMES,source_sha256=hashes,fit_2026_rows=0,full_pool_complete=False,blind_test=False)
    if frozen.exists():
        assert a.resume,'Use explicit --resume only for interrupted evaluation'
        old=json.loads(frozen.read_text(encoding='utf-8'))
        assert old['source_sha256']==hashes and old['roster']==NAMES,'Frozen replay sources changed'
    else:write(frozen,binding)
    asofs=clocks(calendar);ops=operations(calendar,asofs) if year==2026 else {}
    metrics=[]
    for name in NAMES:
        folder=out/name
        if (folder/'DONE.json').exists() and a.resume:
            metrics.append(json.loads((folder/'DONE.json').read_text(encoding='utf-8')));continue
        if folder.exists():raise RuntimeError(f'Incomplete output must be preserved and reviewed: {folder}')
        folder.mkdir();start=time.monotonic();actor=PolicyV2(name,stage)
        with threadpool_limits(limits=2),torch.no_grad():
            result=run_replay(prices,calendar,panel,actor,candidate=name,cost_bps=a.cost,
                capacity_fraction=.01,signal_start=f'{year}-01-01',signal_end=last,
                signal_asof=asofs,operational_exits_by_signal=ops)
        for key in LEDGERS:getattr(result,key).to_parquet(folder/f'{key}.parquet',index=False)
        write(folder/'metadata.json',result.metadata)
        row=summarize(result,name,year,a.cost);row['seconds']=round(time.monotonic()-start,2)
        write(folder/'DONE.json',row);metrics.append(row)
        pd.DataFrame(metrics).to_csv(out/'comparison.csv',index=False)
        print(json.dumps(clean(row)),flush=True)
    assert guard['attempts']==0
    assert all(sha(p)==h for p,h in hashes.items()),'Frozen sources changed during replay'
    write(out/'COMPLETE.json',dict(status='FROZEN_REPLAY_COMPLETE',year=year,cost_bps=a.cost,
        policies=len(NAMES),fit_attempts=guard['attempts'],sources_unchanged=True,
        full_pool_complete=False,blind_test=False))

if __name__=='__main__':main()
