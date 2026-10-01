"""Frozen-spec capacity-aware state/action value models, trained before 2026.

The three account states are counterfactual one-security approximations. They
are not causal experiments or a replacement for the portfolio replay ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import time
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.metrics import log_loss, mean_pinball_loss, mean_squared_error, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
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


def mature_rows(frame, cutoff):
    cutoff = pd.Timestamp(cutoff)
    if cutoff > pd.Timestamp('2026-01-01'):
        raise ValueError('CUTOFF_AFTER_TRAINING_BOUNDARY')
    selected = frame.loc[frame.signal_date.ge('2023-01-01') & frame.signal_date.lt(cutoff)
        & frame.label_end_date.lt(cutoff) & frame.label_end_date.gt(frame.signal_date)
        & frame.label_available.astype(bool) & frame.new_buy_eligible.astype(bool)].copy()
    if selected.empty:
        raise ValueError('NO_MATURE_ROWS')
    if selected.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('DUPLICATE_TRAINING_KEY')
    if not np.isfinite(selected[[*FEATURES, 'y_next_open']].to_numpy(float)).all():
        raise ValueError('NONFINITE_TRAINING_VALUE')
    if not selected.avg_dollar_volume_20d.gt(0).all():
        raise ValueError('NONPOSITIVE_ADV')
    return selected.sort_values(['signal_date', 'ticker'], kind='stable').reset_index(drop=True)


def select_dates(frame, maximum_base_rows=MAX_ROWS // 15):
    """Round-robin date allocation with stable SHA256 ticker/date ordering.

    Every mature date is represented; keys, never outcomes, determine inclusion.
    The function retains its historical name for compatible callers.
    """
    if frame.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('DUPLICATE_SAMPLE_KEY')
    dates = pd.DatetimeIndex(sorted(frame.signal_date.unique()))
    if maximum_base_rows < len(dates):
        raise ValueError('BUDGET_CANNOT_COVER_ALL_MATURE_DATES')
    sample = frame.copy()
    if len(sample) > maximum_base_rows:
        date_keys = {d: hashlib.sha256(f'{SEED}|{d.date()}'.encode()).hexdigest() for d in dates}
        sample['_date_hash'] = sample.signal_date.map(date_keys)
        sample['_key_hash'] = [hashlib.sha256(f'{SEED}|{d.date()}|{t}'.encode()).hexdigest()
            for d, t in zip(sample.signal_date, sample.ticker)]
        sample = sample.sort_values(['signal_date', '_key_hash', 'ticker'], kind='stable')
        sample['_rank'] = sample.groupby('signal_date', sort=False).cumcount()
        sample = sample.sort_values(['_rank', '_date_hash', '_key_hash', 'ticker'], kind='stable')
        sample = sample.head(maximum_base_rows).drop(columns=['_date_hash', '_key_hash', '_rank'])
    sample = sample.sort_values(['signal_date', 'ticker'], kind='stable').reset_index(drop=True)
    assert sample.signal_date.nunique() == len(dates)
    return sample, dates


def realized_weight(current, action, adv_dollars):
    adv = np.asarray(adv_dollars, dtype=float)
    if not np.isfinite(adv).all() or not (adv > 0).all():
        raise ValueError('ADV_MUST_BE_FINITE_POSITIVE')
    if action > current:
        return current + np.minimum(action-current, CAPACITY_FRACTION*adv/NOMINAL_CASH)
    return np.full_like(adv, action)


def counterfactual(frame, robust_training=True):
    x = frame[FEATURES].to_numpy(float)
    forward = frame.y_next_open.to_numpy(float)
    if robust_training:
        forward = np.clip(forward, -.20, .20)
    vol = frame.realized_vol_20d.to_numpy(float)
    adv = frame.avg_dollar_volume_20d.to_numpy(float)
    blocks, rewards, constrained = [], [], 0
    n = len(frame)
    for current, cash, age in STATE_GRID:
        for action in ACTIONS:
            actual = realized_weight(current, float(action), adv)
            constrained += int(np.count_nonzero(actual < action-1e-12)) if action > current else 0
            blocks.append(mapped_features(x, np.full(n,current), np.full(n,cash),
                np.full(n,age), np.full(n,action)))
            rewards.append(actual*forward - COST*np.abs(actual-current)
                - .5*RISK_AVERSION*vol**2*actual**2)
    xx, yy = np.concatenate(blocks), np.concatenate(rewards)
    if xx.shape != (n*15,106) or not np.isfinite(xx).all() or not np.isfinite(yy).all():
        raise ValueError('BAD_COUNTERFACTUAL_MATRIX')
    return xx, yy, {'capacity_limited_buy_labels': constrained,
        'return_clip_applied': bool(robust_training), 'base_returns_over_clip': int((abs(frame.y_next_open)>.2).sum())}


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
        assert receipt['status']=='PASS'
        names=('q10','q50','q90') if name=='quantile_risk' else (name,)
        for key in names:
            record=next(r for r in receipt['fits'] if r['stage']==stage and r['name']==key)
            repairs=[r for r in receipt['numerical_repairs'] if r['stage']==stage and r['name']==key]
            if repairs:record=repairs[-1]
            path=Path(record['artifact'])
            assert sha(path)==record['artifact_sha256']
            self.models[key]=joblib.load(path)


def load_policy(name,stage='final'):
    return JointActionValuePolicy(name,stage)


def train():
    OUT.mkdir(exist_ok=True)
    if (OUT/'PRE_FIT_CONTRACT.json').exists() or list(OUT.glob('*.joblib')):
        raise RuntimeError('EXISTING_TRAINING_PRESERVED')
    if not (ROOT/'EXPERIMENT_CONTRACT.md').is_file():
        raise RuntimeError('MISSING_PRE_FIT_EXPERIMENT_CONTRACT')
    columns=['signal_date','ticker','label_end_date','label_available','new_buy_eligible','y_next_open',*FEATURES]
    frame=pd.read_parquet(DATA,columns=columns)
    if not frame.signal_date.lt('2026-01-01').all():
        raise RuntimeError('2026_ROWS_IN_TRAINING_FILE')
    if not frame.label_end_date.dropna().lt('2026-01-01').all():
        raise RuntimeError('2026_LABELS_IN_TRAINING_FILE')
    audit={}; selected={}
    for stage,cutoff in STAGES.items():
        mature=mature_rows(frame,cutoff)
        selected[stage],dates=select_dates(mature)
        sample=selected[stage]
        key_path=OUT/f'sample_keys_{stage}.parquet'
        sample[['signal_date','ticker','label_end_date']].to_parquet(key_path,index=False)
        audit[stage]={'cutoff_exclusive':cutoff,'mature_base_rows':len(mature),
            'base_rows':len(sample),'counterfactual_rows':len(sample)*15,
            'mature_dates':len(dates),'sampled_dates':sample.signal_date.nunique(),
            'signal_min':str(sample.signal_date.min().date()),'signal_max':str(sample.signal_date.max().date()),
            'label_end_max':str(sample.label_end_date.max().date()),
            'sample_keys_sha256':sha(key_path), 'sample_rows_per_day_min':int(sample.groupby('signal_date').size().min()),
            'sample_rows_per_day_max':int(sample.groupby('signal_date').size().max())}
    spec={'status':'PRE_FIT_LOCKED','created_utc':pd.Timestamp.now(tz='UTC').isoformat(),
        'source':str(DATA),'source_sha256':sha(DATA),'training_code_sha256':sha(__file__),
        'experiment_contract_sha256':sha(ROOT/'EXPERIMENT_CONTRACT.md'),
        'features':FEATURES,'parameters':SPECS,'stages':audit,'random_seed':SEED,
        'state_grid':STATE_GRID,'action_grid':ACTIONS.tolist(),'maximum_counterfactual_rows':MAX_ROWS,
        'nominal_cash':NOMINAL_CASH,'capacity_fraction':CAPACITY_FRACTION,'cost_per_side':COST,
        'risk_aversion':RISK_AVERSION,'return_clip_training_only':[-.2,.2],
        'capacity_formula':'buy=current+min(request-current,0.01*signal_ADV/1000000); sell=request',
        'reward':'actual_weight*next_open_return - 0.001*abs(actual-current) - 0.5*4*vol20^2*actual_weight^2',
        'sampling':'All mature dates; round-robin by within-date SHA256(seed,date,ticker) rank and SHA256(seed,date)',
        'hyperparameter_search_count':0,'2026_rows_read':0,'main_fit_budget':14,
        'elastic_numerical_repair':{'maximum_attempts_per_stage':1,'warm_start':True,
            'precompute_gram':True,'max_iter':25000,'same_data_same_objective':True},
        'validation_usage':'Fixed recipe diagnosis only, no tuning, screening or early stopping',
        'logistic_readout':'positive net reward probability, unitless action utility, not predicted return',
        'quantile_readout':'conditional one-session net reward quantiles, not gross stock returns',
        'limitations':['Counterfactual account states, not complete trajectory optimization.',
            'Fixed nominal capacity reward is a partial-equilibrium one-security approximation.',
            'Input price coordinate is an adjusted research index, not certified shareholder total return.',
            'Previously observed validation/test periods cannot be restored to original blind holdouts.']}
    write(OUT/'PRE_FIT_CONTRACT.json',spec)
    receipt={'status':'RUNNING','pre_fit_contract_sha256':sha(OUT/'PRE_FIT_CONTRACT.json'),
        'fits':[],'numerical_repairs':[],'sampling':audit,'fit_calls_attempted':0,
        'fit_calls_completed':0,'validation_metrics':{},'test2026_rows_read':0,
        'hyperparameter_search_count':0,'python':platform.python_version(),'sklearn':sklearn.__version__}
    val=frame.loc[frame.signal_date.ge('2025-01-01')].copy()
    val,_=select_dates(mature_rows(val,'2026-01-01'))
    vx,vy,_=counterfactual(val,robust_training=False)
    for stage in STAGES:
        tx,ty,label_audit=counterfactual(selected[stage])
        assert len(tx)<=MAX_ROWS
        for name in NAMES:
            target=(ty>0).astype(int) if name=='logistic' else ty
            model=estimator(name)
            receipt['current_fit']=f'{stage}/{name}'
            receipt['fit_calls_attempted']+=1
            write(OUT/'FIT_RECEIPT.partial.json',receipt)
            start=time.monotonic()
            with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
                warnings.simplefilter('always'); model.fit(tx,target)
            path=OUT/f'{stage}_{name}.joblib'; joblib.dump(model,path,compress=3)
            final=model[-1] if hasattr(model,'steps') else model
            converged=not any(issubclass(w.category,ConvergenceWarning) for w in caught)
            row={'stage':stage,'name':name,'train_rows':len(tx),'model_input_features':tx.shape[1],
                'fit_seconds':time.monotonic()-start,'train_signal_max':audit[stage]['signal_max'],
                'train_label_end_max':audit[stage]['label_end_max'],'artifact':str(path),
                'artifact_sha256':sha(path),'iterations':np.asarray(getattr(final,'n_iter_',None)).tolist(),
                'converged':converged,'fit_warnings':[{'category':w.category.__name__,'message':str(w.message)} for w in caught],
                **label_audit}
            receipt['fits'].append(row); receipt['fit_calls_completed']+=1
            print(json.dumps(row),flush=True)
            if not converged:
                if name!='elastic_net':
                    write(OUT/'FIT_RECEIPT.partial.json',receipt)
                    raise RuntimeError(f'NON_ELASTIC_MODEL_NOT_CONVERGED:{stage}:{name}')
                final.set_params(precompute=True,max_iter=25000,warm_start=True)
                start=time.monotonic()
                with warnings.catch_warnings(record=True) as repaired,threadpool_limits(limits=2):
                    warnings.simplefilter('always'); final.fit(model[0].transform(tx),target)
                success=not any(issubclass(w.category,ConvergenceWarning) for w in repaired)
                fixed=OUT/f'{stage}_elastic_net_numerical_repair.joblib'; joblib.dump(model,fixed,compress=3)
                repair={'stage':stage,'name':name,'original_artifact':str(path),'original_sha256':row['artifact_sha256'],
                    'artifact':str(fixed),'artifact_sha256':sha(fixed),'fit_seconds':time.monotonic()-start,
                    'iterations':int(final.n_iter_),'dual_gap':float(final.dual_gap_),'converged':success,
                    'same_samples_objective_scaler':True,'additional_fit_calls':1,'used_for_policy':success,
                    'fit_warnings':[{'category':w.category.__name__,'message':str(w.message)} for w in repaired]}
                receipt['numerical_repairs'].append(repair)
                print(json.dumps({'numerical_repair':repair}),flush=True)
                if not success:
                    write(OUT/'FIT_RECEIPT.partial.json',receipt)
                    raise RuntimeError('ELASTIC_NUMERICAL_REPAIR_NOT_CONVERGED')
            if stage=='validation':
                prediction=predict_values(model,name,vx)
                if name=='logistic':
                    metric={'roc_auc':float(roc_auc_score(vy>0,prediction)),'log_loss':float(log_loss(vy>0,prediction))}
                elif name.startswith('q'):
                    metric={'pinball_loss':float(mean_pinball_loss(vy,prediction,alpha=float(name[1:])/100))}
                else:metric={'mse':float(mean_squared_error(vy,prediction))}
                receipt['validation_metrics'][name]=metric
            receipt.pop('current_fit',None)
            write(OUT/'FIT_RECEIPT.partial.json',receipt)
        del tx,ty
    assert sha(DATA)==spec['source_sha256'] and sha(__file__)==spec['training_code_sha256']
    assert sha(ROOT/'EXPERIMENT_CONTRACT.md')==spec['experiment_contract_sha256']
    receipt.update(status='PASS',source_and_code_unchanged=True,main_fit_calls=14,
        total_fit_calls_including_numerical_repairs=14+len(receipt['numerical_repairs']),
        scaler_fit_calls=6,validation_counterfactual_rows=len(vx),fit_guard_2026_rows=0)
    write(OUT/'FIT_RECEIPT.json',receipt)
    print(json.dumps({'status':'PASS','main_fits':14,'numerical_repairs':len(receipt['numerical_repairs'])}),flush=True)


if __name__=='__main__':
    train()
