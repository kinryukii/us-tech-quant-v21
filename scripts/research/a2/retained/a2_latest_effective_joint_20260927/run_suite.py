"""Frozen joint-policy evaluation with explicit subset and price-quality limits."""
from pathlib import Path
import argparse
import hashlib
import json
import time
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from engine import run_replay
from joint_linear_tree import load_policy
from joint_neural import NeuralAdapter
from joint_risk import JointRiskPolicy
from models.predict import predict_panel,predict_state
from risk import FrozenRisk

ROOT=Path(__file__).resolve().parent
NAMES=['joint_ridge','joint_elastic_net','joint_logistic','joint_hgb','joint_q10','joint_q50','joint_q90',
       'joint_quantile_risk','joint_mlp','joint_rl_ensemble','joint_rl_zero_control','hgb_return_baseline']
TEST_NAMES=NAMES+['joint_hgb_lw','joint_hgb_pca']

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str,allow_nan=False),encoding='utf-8')

def freeze():
    files=[]
    for folder,patterns in [('joint_linear_tree_artifacts',['*.joblib','*.json']),('joint_neural_artifacts',['*.pt','*.npz','*.json']),
                            ('models',['*.joblib','*.pt','*.json']),('risk',['*.npz','*.json']),('data',['test*.parquet','calendar.parquet','*AUDIT.json'])]:
        for pattern in patterns:files.extend((ROOT/folder).glob(pattern))
    files.extend(ROOT/p for p in ['run_suite.py','engine.py','joint_neural.py','joint_linear_tree.py','joint_risk.py','risk.py','models/predict.py'])
    files.extend(ROOT.glob('*CONTRACT.md'))
    return dict(roster=TEST_NAMES,cost_bps_per_side=[10,5,25],created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        inference_only=True,full_pool=False,qualification='retrospective_verified_subset_price_index_diagnostic',
        universe_rule='latest public and effective 13F pool; retain the prior effective pool until next effective date',
        risk_extension='learned joint HGB action values plus frozen one-day LW/PCA covariance; four coordinate ascent passes; no return TOP20 prescreen',
        price_gate='No outcome-based signal exclusion. At execution or valuation, flagged price rows become unavailable; never silently mark them trusted.',
        source_hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(files))})

def forbid_fitting():
    from sklearn.ensemble import HistGradientBoostingRegressor,IsolationForest
    from sklearn.linear_model import Ridge,ElasticNet,LogisticRegression
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.covariance import LedoitWolf
    from sklearn.pipeline import Pipeline
    count={'attempts':0}
    def denied(*args,**kwargs):count['attempts']+=1;raise RuntimeError('FIT_FORBIDDEN_DURING_EVALUATION')
    for cls in [HistGradientBoostingRegressor,IsolationForest,Ridge,ElasticNet,LogisticRegression,MLPRegressor,
                StandardScaler,KMeans,PCA,LedoitWolf,Pipeline]:
        for name in ['fit','partial_fit','fit_transform']:
            if hasattr(cls,name):setattr(cls,name,denied)
    return count

class Stateful:
    def __init__(self,name,stage):
        self.name=name;self.age={};self.lastdate=None;self.records=[]
        if name=='joint_mlp':self.policy=NeuralAdapter('direct',stage=stage)
        elif name=='joint_rl_ensemble':self.policy=NeuralAdapter('rl',stage=stage)
        elif name=='joint_rl_zero_control':self.policy=NeuralAdapter('rl',zero=True,stage=stage)
        elif name in ['joint_hgb_lw','joint_hgb_pca']:self.policy=JointRiskPolicy(factor=name.endswith('pca'))
        elif name=='hgb_return_baseline':self.policy=None
        else:self.policy=load_policy(name.removeprefix('joint_'),stage=stage)
    def __call__(self,day,weights,cash):
        if day.empty:return {}
        self.age={t:self.age.get(t,0)+1 for t,v in weights.items() if v>0}
        if self.policy is None:
            eligible=day[day.new_buy_eligible].sort_values(['baseline_hgb','ticker'],ascending=[False,True],kind='stable').head(20)
            return {str(t):.0475 for t in eligible.ticker}
        if hasattr(self.policy,'policy') or isinstance(self.policy,JointRiskPolicy):
            targets=self.policy(day,weights,cash,held_age=self.age)
        else:targets=self.policy(day,weights,cash)
        if hasattr(self.policy,'last_diagnostic'):
            self.records.append(dict(signal_date=str(day.signal_date.iloc[0].date()),**self.policy.last_diagnostic))
        return targets

def metrics(result,name,cost,year):
    d=result.daily;nav=np.r_[1e6,d.nav.to_numpy(float)]
    nav=nav[np.isfinite(nav)]
    unc=int((d.valuation_status!='certified').sum())
    return dict(policy=name,year=year,cost_bps_per_side=cost,days=len(d),
        indicative_return=float(nav[-1]/1e6-1),indicative_max_drawdown=float((nav/np.maximum.accumulate(nav)-1).min()),
        mean_cash=float(d.cash_weight.mean()),fee_amount=float(d.transaction_cost_amount.sum()),
        half_turnover=float(d.turnover.sum()),trades=len(result.trades),uncertified_days=unc,
        terminal_valuation=str(d.valuation_status.iloc[-1]),
        all_prices_current_path_return=float(nav[-1]/1e6-1) if unc==0 else None,
        formal_full_pool_return=None,
        blocked_orders=int(d.blocked_order_count.sum()),max_actual_names=int(d.actual_name_count.max()),
        target_decisions=len(result.target_decisions),max_abs_cash_error=float(d.cash_flow_identity_error.abs().max()),
        max_abs_cost_error=float(d.cost_identity_error.abs().max()),max_abs_nav_error=float(d.nav_identity_error.abs().max()))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,choices=[2025,2026],required=True)
    parser.add_argument('--costs',type=float,nargs='+',default=[10,5,25]);args=parser.parse_args()
    year=args.year;out=ROOT/f'evaluation_{year}'
    if year==2026 and len(args.costs)==1:out=out/f'cost_{args.costs[0]:g}'
    out.mkdir(parents=True,exist_ok=True)
    if (out/'COMPLETE.json').exists():raise RuntimeError('EVALUATION_EXISTS; do not overwrite')
    names=TEST_NAMES if year==2026 else NAMES
    counts=forbid_fitting()
    if year==2026:
        seal=freeze();write(out/'FROZEN_BEFORE_SCORING.json',seal)
        panel=pd.read_parquet(ROOT/'data/test_features_context.parquet')
        prices=pd.read_parquet(ROOT/'data/test_prices.parquet')
        # Price reliability gates execution/valuation at the consuming date,
        # never the preceding model candidate choice.
        flagged=prices.price_quality_warning.astype(bool)
        prices.loc[flagged,['open','close']]=np.nan
        calendar=pd.DatetimeIndex(pd.read_parquet(ROOT/'data/calendar.parquet').query('is_test').trade_date)
        last='2026-09-22';stage='final'
        score=predict_panel(panel)[['signal_date','ticker','hgb']].rename(columns={'hgb':'baseline_hgb'})
    else:
        panel=pd.read_parquet(ROOT/'data/pre2026_joint_context.parquet').query('signal_date >= "2025-01-01"').copy()
        prices=pd.read_parquet(ROOT.parent/'a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet')
        calendar=pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('QQQ')&prices.trade_date.ge('2025-01-01'),'trade_date'].unique()))
        last='2025-12-29';stage='validation'
        score=pd.read_parquet(ROOT.parent/'a2_strict_method_retrain_20260926/results/hgb/pre2026_oof.parquet')
        score=score[score.signal_date.dt.year.eq(2025)][['signal_date','ticker','prediction']].rename(columns={'prediction':'baseline_hgb'})
    panel=panel[panel.signal_date.le(last)].copy()
    panel=panel.merge(score,on=['signal_date','ticker'],how='left',validate='one_to_one')
    assert panel.baseline_hgb.notna().all()
    # Export only observation columns, never future label fields, into callbacks.
    keep=['signal_date','ticker','new_buy_eligible','baseline_hgb']+list(__import__('joint_neural').FEATURES)
    panel=panel[keep]
    rows=[]
    for cost in args.costs:
        for name in names:
            started=time.monotonic();directory=out/f'{name}_{cost:g}bps';directory.mkdir(exist_ok=True)
            actor=Stateful(name,stage)
            with threadpool_limits(limits=2):
                result=run_replay(prices,calendar,panel,actor,candidate=name,cost_bps=cost,max_invested=.95,
                    capacity_fraction=.01,missing_signal_policy='cash',signal_start=f'{year}-01-01',signal_end=last)
            for key in ['daily','trades','positions','target_decisions','diagnostics','valuation_intervals']:
                getattr(result,key).to_parquet(directory/f'{key}.parquet',index=False)
            write(directory/'metadata.json',result.metadata)
            if actor.records:write(directory/'risk_solver.json',actor.records)
            row=metrics(result,name,cost,year);rows.append(row)
            pd.DataFrame(rows).to_csv(out/'comparison.csv',index=False)
            print(json.dumps(dict(policy=name,cost=cost,seconds=round(time.monotonic()-started,2),**{k:row[k] for k in ['indicative_return','uncertified_days','trades']})),flush=True)
    diagnostics=[]
    if year==2026:
        for d,g in panel.groupby('signal_date'):
            if len(g)>=20:diagnostics.append(dict(signal_date=d,**predict_state(g)))
        pd.DataFrame(diagnostics).to_csv(out/'state_anomaly.csv',index=False)
        for rel,expected in seal['source_hashes'].items():assert sha(ROOT/rel)==expected,rel
    write(out/'COMPLETE.json',dict(status='DIAGNOSTIC_COMPLETE',year=year,policies=len(names),evaluations=len(rows),
        fit_guard_attempts=counts['attempts'],sources_unchanged=True if year==2026 else None,
        training_2026_rows=0,full_pool_formal_result=False,
        notes='All scheduled policies reported; no winner selected from 2026. Uncertified paths retain indicative values only.'))

if __name__=='__main__':main()
