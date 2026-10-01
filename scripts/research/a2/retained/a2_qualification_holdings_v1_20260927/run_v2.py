"""Run the versioned account policies with frozen or freshly pre-2026 fits."""
from pathlib import Path
import sys,json,hashlib,argparse,time
import pandas as pd
import numpy as np
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'a2_latest_effective_joint_20260927'
sys.path.insert(0,str(OLD))
from run_suite import forbid_fitting
from models.predict import predict_panel
from engine_v2 import run_replay,OperationalExit
from adapters_v2 import PolicyV2
from joint_neural_v2 import FEATURES

NAMES=['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb','joint_q10','joint_q50','joint_q90',
       'joint_quantile_risk','joint_mlp','joint_rl_ensemble','joint_rl_zero_control','hgb_return_baseline']
TEST_NAMES=NAMES+['joint_hgb_lw','joint_hgb_pca']


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding='utf-8')


def clocks(calendar):
    # NYSE published 2025/2026 calendars; do not admit after-close evidence on
    # early-close sessions. July 2, 2026 is a regular close in the NYSE calendar.
    early={'2025-07-03','2025-11-28','2025-12-24','2026-11-27','2026-12-24'}
    if any(d.year not in [2025,2026] for d in calendar):raise ValueError('UNREVIEWED_SESSION_YEAR')
    return {d:(d+pd.Timedelta(hours=13 if str(d.date()) in early else 16)).tz_localize(
        'America/New_York').tz_convert('UTC') for d in calendar}


def operational_schedule(calendar,asofs):
    path=ROOT/'data/operational_exit_evidence.csv'
    if not path.exists():return {}
    df=pd.read_csv(path)
    if df.empty:return {}
    df['known_at']=pd.to_datetime(df.known_at,utc=True)
    df['effective_date']=pd.to_datetime(df.effective_date)
    out={}
    for d in calendar:
        known=df[(df.known_at<=asofs[d])&(df.effective_date<=d)]
        if len(known):out[d]={str(r.ticker):OperationalExit(str(r.reason),r.known_at,str(r.source_id)) for r in known.itertuples()}
    return out


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--year',required=True,type=int,choices=[2025,2026])
    parser.add_argument('--cost',type=float,default=10);parser.add_argument('--policies',nargs='+')
    args=parser.parse_args();year=args.year
    out=ROOT/f'evaluation_{year}'/f'cost_{args.cost:g}';out.mkdir(parents=True,exist_ok=True)
    if (out/'COMPLETE.json').exists():raise RuntimeError('FROZEN_VERSION_RESULT_EXISTS')
    names=args.policies or (TEST_NAMES if year==2026 else NAMES)
    assert set(names).issubset(TEST_NAMES if year==2026 else NAMES)
    source_paths=[ROOT/'VERSION_CONTRACT.md',ROOT/'engine_v2.py',ROOT/'adapters_v2.py',Path(__file__),
                  ROOT/'joint_neural_v2.py',ROOT/'neural_artifacts/TRAIN_RECEIPT.json',ROOT/'SESSION_CLOCK_SOURCES.json']
    source_paths+=list((ROOT/'neural_artifacts').glob('*.pt'))+list((ROOT/'neural_artifacts').glob('*.npz'))
    source_paths+=list((OLD/'joint_linear_tree_artifacts').glob('*.joblib'))+[OLD/'risk/frozen_covariance.npz']
    guard=forbid_fitting()
    if year==2026:
        source_paths +=[ROOT/'data/test_features_context.parquet',ROOT/'data/test_prices.parquet',ROOT/'data/DATA_RECEIPT.json']
        panel=pd.read_parquet(ROOT/'data/test_features_context.parquet')
        prices=pd.read_parquet(ROOT/'data/test_prices.parquet')
        calendar=pd.DatetimeIndex(pd.read_parquet(OLD/'data/calendar.parquet').query('is_test').trade_date)
        score=predict_panel(panel)[['signal_date','ticker','hgb']].rename(columns={'hgb':'baseline_hgb'})
        last='2026-09-22';stage='final'
    else:
        src=OLD/'data/pre2026_joint_context.parquet';source_paths.append(src)
        panel=pd.read_parquet(src).query('signal_date >= "2025-01-01"').copy()
        price_src=ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet'
        source_paths.append(price_src);prices=pd.read_parquet(price_src)
        calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
        score_src=ROOT.parent/'a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet'
        source_paths.append(score_src);score=pd.read_parquet(score_src)
        score=score.loc[score.signal_date.dt.year.eq(2025),['signal_date','ticker','prediction']].rename(columns={'prediction':'baseline_hgb'})
        last='2025-12-29';stage='validation'
    panel=panel.loc[panel.signal_date.le(last)].copy()
    panel=panel.merge(score,on=['signal_date','ticker'],how='left',validate='one_to_one')
    assert panel.baseline_hgb.notna().all()
    panel=panel[['signal_date','ticker','new_buy_eligible','baseline_hgb']+list(FEATURES)]
    source_hashes={str(p):sha(p) for p in source_paths}
    write(out/'FROZEN_BEFORE_REPLAY.json',dict(version='qualification_holdings_v1',year=year,
        cost_bps=args.cost,roster=names,source_sha256=source_hashes,fit_2026_rows=0,
        full_pool_complete=False,blind_test=False))
    asofs=clocks(calendar);ops=operational_schedule(calendar,asofs) if year==2026 else {}
    metrics=[]
    for name in names:
        folder=out/name
        if folder.exists():raise RuntimeError(f'RESULT_ALREADY_EXISTS: {folder}')
        folder.mkdir();start=time.monotonic()
        actor=PolicyV2(name,stage)
        with threadpool_limits(limits=2):
            result=run_replay(prices,calendar,panel,actor,candidate=name,cost_bps=args.cost,
                capacity_fraction=.01,signal_start=f'{year}-01-01',signal_end=last,
                signal_asof=asofs,operational_exits_by_signal=ops)
        for key in ['daily','trades','positions','target_decisions','diagnostics','valuation_intervals',
                    'raw_model_outputs','signal_contexts','operational_actions','execution_results']:
            getattr(result,key).to_parquet(folder/f'{key}.parquet',index=False)
        write(folder/'metadata.json',result.metadata)
        daily=result.daily;target=result.target_decisions;execution=result.execution_results
        row=dict(policy=name,year=year,cost_bps=args.cost,days=len(daily),trades=len(result.trades),
            indicative_return=float(daily.nav.iloc[-1]/1e6-1),uncertified_days=int(daily.certified_nav.isna().sum()),
            max_actual_names=int(daily.actual_name_count.max()),model_active_exits=int(target.decision_semantic.eq('MODEL_ACTIVE_EXIT').sum()),
            model_no_decisions=int(target.decision_semantic.eq('MODEL_NO_DECISION').sum()),
            operational_exits=int(target.decision_semantic.eq('OPERATIONAL_EXIT_REQUIRED').sum()),
            execution_rejections=int(execution.status.eq('REJECTED').sum()),
            seconds=round(time.monotonic()-start,2))
        metrics.append(row);pd.DataFrame(metrics).to_csv(out/'comparison.csv',index=False)
        print(json.dumps(row),flush=True)
    assert guard['attempts']==0
    assert all(sha(p)==h for p,h in source_hashes.items()),'Frozen source changed during replay'
    write(out/'COMPLETE.json',dict(status='VERSIONED_DIAGNOSTIC_REPLAY_COMPLETE',year=year,
        cost_bps=args.cost,policies=len(names),fit_attempts=guard['attempts'],sources_unchanged=True,
        full_pool_complete=False,version='qualification_holdings_v1'))


if __name__=='__main__':main()
