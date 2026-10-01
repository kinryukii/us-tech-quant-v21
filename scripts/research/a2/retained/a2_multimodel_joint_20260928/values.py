"""Frozen-spec capacity-aware state/action value models, trained before 2026.

The three account states are counterfactual one-security approximations. They
are not causal experiments or a replacement for the portfolio replay ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
FEATURE_SOURCE = ROOT.parent / 'a2_latest_effective_joint_20260927/models/model_registry.json'
DATA = ROOT.parent / 'a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet'
OUT = ROOT / 'value_artifacts'
FEATURES = ['ret_1d', 'ret_3d', 'ret_5d', 'ret_10d', 'ret_20d', 'ret_40d', 'ret_60d', 'ret_120d',
    'price_vs_ma10', 'price_vs_ma20', 'price_vs_ma50', 'price_vs_ma120', 'ma10_vs_ma20',
    'ma20_vs_ma50', 'ma50_vs_ma120', 'realized_vol_5d', 'realized_vol_10d', 'realized_vol_20d',
    'realized_vol_60d', 'downside_vol_20d', 'upside_vol_20d', 'distance_from_high_20d',
    'distance_from_high_60d', 'distance_from_low_20d', 'distance_from_low_60d',
    'max_drawdown_20d', 'max_drawdown_60d', 'avg_volume_20d', 'avg_volume_60d',
    'volume_ratio_5d_20d', 'volume_ratio_20d_60d', 'avg_dollar_volume_20d']
ACTIONS = np.array([0., .025, .05, .075, .1])
STATE_GRID = ((0., .95, 0.), (.05, .5, 10.), (.1, .05, 40.))
SEED = 20260928
MAX_ROWS = 200000
COST = .001
RISK_AVERSION = 4.
NOMINAL_CASH = 1000000.
CAPACITY_FRACTION = .01
NAMES = ('ridge', 'elastic_net', 'logistic', 'hgb', 'q10', 'q50', 'q90')
STAGES = {'validation': '2025-01-01', 'final': '2026-01-01'}
TREE = dict(max_iter=100, max_leaf_nodes=15, max_depth=3, min_samples_leaf=150,
    learning_rate=.05, l2_regularization=10., early_stopping=False, random_state=SEED)
SPECS = {'ridge': dict(alpha=100., solver='lsqr', tol=1e-6),
    'elastic_net': dict(alpha=.000001, l1_ratio=.35, max_iter=2500, tol=1e-5,
        selection='cyclic', random_state=SEED, precompute=True),
    'logistic': dict(C=.3, max_iter=400, solver='lbfgs', random_state=SEED),
    'hgb': TREE, 'q10': {**TREE, 'loss': 'quantile', 'quantile': .1},
    'q50': {**TREE, 'loss': 'quantile', 'quantile': .5},
    'q90': {**TREE, 'loss': 'quantile', 'quantile': .9}}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
        default=str, allow_nan=False), encoding='utf-8')


def mapped_features(x, current, cash, age, action):
    x = np.asarray(x, dtype=float)
    current, cash, age, action = [np.asarray(a, dtype=float).reshape(-1)
        for a in (current, cash, age, action)]
    volatility = x[:, FEATURES.index('realized_vol_20d')]
    return np.column_stack([x, current, cash, np.minimum(age, 252.) / 252., action,
        action * action, np.abs(action-current), action-current,
        x * action[:, None], x * (action-current)[:, None],
        action * cash, action * current, action * volatility * volatility])


def estimator(name):
    if name == 'ridge':
        return make_pipeline(StandardScaler(), Ridge(**SPECS[name]))
    if name == 'elastic_net':
        return make_pipeline(StandardScaler(), ElasticNet(**SPECS[name]))
    if name == 'logistic':
        return make_pipeline(StandardScaler(), LogisticRegression(**SPECS[name]))
    return HistGradientBoostingRegressor(**SPECS[name])


def predict_values(model, name, values):
    with threadpool_limits(limits=2):
        result = model.predict_proba(values)[:,1] if name == 'logistic' else model.predict(values)
    if not np.isfinite(result).all():
        raise RuntimeError('NONFINITE_ACTION_VALUE')
    return result


def allocate_joint_scores(scores, tickers, max_names=20, max_units=38, allowed=None):
    """Exact multiple-choice knapsack; 2.5% weight units, at most 20 stocks."""
    scores = np.asarray(scores,dtype=float)
    assert scores.shape == (len(tickers),len(ACTIONS)) and np.isfinite(scores).all()
    if max_names < 0 or max_units < 0:
        raise ValueError('NEGATIVE_PORTFOLIO_BUDGET')
    gains = scores-scores[:,:1]
    if allowed is not None:
        assert np.asarray(allowed).shape == scores.shape
        gains = np.where(allowed,gains,-np.inf)
    dp = np.full((max_names+1,max_units+1),-np.inf)
    dp[0,0] = 0.
    choices = np.zeros((len(tickers),max_names+1,max_units+1),dtype=np.uint8)
    for i in range(len(tickers)):
        prior = dp.copy()
        for action_idx in range(1,min(len(ACTIONS),max_units+1)):
            candidate = prior[:-1,:-action_idx]+gains[i,action_idx]
            destination = dp[1:,action_idx:]
            improves = candidate>destination+1e-12
            destination[improves] = candidate[improves]
            choices[i,1:,action_idx:][improves] = action_idx
    names,units = np.unravel_index(int(np.argmax(dp)),dp.shape)
    selected = np.zeros(len(tickers),dtype=np.int8)
    for i in range(len(tickers)-1,-1,-1):
        action_idx = int(choices[i,names,units]); selected[i] = action_idx
        if action_idx:
            names -= 1; units -= action_idx
    assert names == units == 0
    weights = {str(t):float(ACTIONS[a]) for t,a in zip(tickers,selected) if a>0}
    assert len(weights)<=max_names and sum(weights.values())<=max_units*.025+1e-12
    return weights,selected


class JointActionValuePolicy:
    def __init__(self,name,stage='final'):
        if stage not in STAGES or name not in (*NAMES,'quantile_risk'):
            raise ValueError('UNKNOWN_POLICY_OR_STAGE')
        self.name=name; self.stage=stage; self.models={}
        receipt=json.loads((OUT/'FIT_RECEIPT.json').read_text(encoding='utf-8'))
        assert receipt['status']=='PASS' and receipt['fit_2026_rows']==0
        names=('q10','q50','q90') if name=='quantile_risk' else (name,)
        for key in names:
            record=next(r for r in receipt['fits'] if r['stage']==stage and r['name']==key)
            repairs=[r for r in receipt.get('numerical_repairs', []) if r['stage']==stage and r['name']==key]
            if repairs:record=repairs[-1]
            if not record['converged']: raise RuntimeError(f'MODEL_NOT_CONVERGED:{stage}:{key}')
            path=Path(record['artifact'])
            assert sha(path)==record['artifact_sha256']
            self.models[key]=joblib.load(path)


def load_policy(name,stage='final'):
    return JointActionValuePolicy(name,stage)

