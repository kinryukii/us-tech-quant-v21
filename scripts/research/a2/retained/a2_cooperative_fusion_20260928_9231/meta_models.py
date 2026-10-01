"""Fixed-budget cooperative meta models on preserved pre-2026 OOF inputs.

Only this added meta layer is fitted. The old basis and old linear stacking
remain frozen. Predictions are raw action values: callers subtract action zero.
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
from scipy.optimize import nnls
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits

import data_context as dc

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'meta_artifacts'
STAGES={'validation':'2025-01-01','final':'2026-01-01'}
NAMES=('fusion_learned_weights','fusion_nonlinear_stacking','fusion_hgb_then_linear','fusion_linear_then_hgb')
TREE=dict(max_iter=60,max_depth=2,max_leaf_nodes=7,min_samples_leaf=500,
    learning_rate=.05,l2_regularization=10.,early_stopping=False,random_state=20260928)
RIDGE=dict(alpha=100.,fit_intercept=False,solver='lsqr',tol=1e-6)
NNLS_MAXITER=1000


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')


def check_name_stage(name,stage):
    if name not in NAMES or stage not in STAGES:raise ValueError('UNKNOWN_META_METHOD_OR_STAGE')


def stem(name):return name.removeprefix('fusion_')


def normalize_nonnegative(weights):
    weights=np.asarray(weights,float)
    if weights.shape!=(6,) or not np.isfinite(weights).all() or (weights<0).any():
        raise ValueError('INVALID_NONNEGATIVE_WEIGHTS')
    total=float(weights.sum())
    return weights/total if total>0 else np.zeros_like(weights)


def hgb_anchor_coefficient(x,y):
    x=np.asarray(x,float);y=np.asarray(y,float)
    return max(0.,float(x@y/(x@x+100.)))


def finite_vector(value,n):
    value=np.asarray(value,float).reshape(-1)
    if value.shape!=(n,) or not np.isfinite(value).all():raise ValueError('NONFINITE_OR_MISSHAPED_PREDICTION')
    return value


def rank_matrix(frame):
    x=frame[list(dc.RANK_COLUMNS)].to_numpy(float)
    if x.ndim!=2 or x.shape[1]!=6 or not np.isfinite(x).all():raise ValueError('INVALID_SIX_RANK_INPUT')
    return x


def nonadditive_sensitivity(model,x,prediction,anchor_coefs=None):
    """Describe replacing one rank input by zero; not additive attribution."""
    result={}
    for j,column in enumerate(dc.RANK_COLUMNS):
        changed=x.copy();changed[:,j]=0.
        effect=prediction-np.asarray(model.predict(changed),float)
        if anchor_coefs is not None:effect=effect+anchor_coefs[j]*x[:,j]
        result[f'nonadditive_zero_{column}_sensitivity']=effect
    return result


class MetaModels:
    def __init__(self,name,stage='final'):
        check_name_stage(name,stage)
        self.name=name;self.stage=stage
        receipt=json.loads((OUT/f'{stage}_{stem(name)}_TRAIN_RECEIPT.json').read_text(encoding='utf-8'))
        path=OUT/f'{stage}_{stem(name)}.joblib'
        if (receipt['status']!='PASS' or receipt['stage']!=stage or receipt['name']!=name
                or receipt['label_end_max']>=STAGES[stage] or receipt['artifact_sha256']!=sha(path)):
            raise ValueError('META_ARTIFACT_CLOCK_OR_HASH_MISMATCH')
        self.payload=joblib.load(path)
        if self.payload['meta_columns']!=list(dc.META_COLUMNS) or self.payload['rank_columns']!=list(dc.RANK_COLUMNS):
            raise ValueError('META_FEATURE_ORDER_MISMATCH')

    def predict(self,frame):
        """Return (raw scores[N], diagnostics[name][N]); no action-zero adjustment."""
        x=np.asarray(dc.meta_features(frame),float);r=rank_matrix(frame);n=len(frame)
        if x.shape!=(n,11) or not np.isfinite(x).all():raise ValueError('INVALID_ELEVEN_META_INPUTS')
        diagnostics={}
        with threadpool_limits(limits=2):
            if self.name=='fusion_learned_weights':
                coef=np.asarray(self.payload['coefficients'],float)
                normalized=np.asarray(self.payload['normalized_weights'],float)
                prediction=r@coef
                diagnostics['anchor_prediction']=prediction.copy()
                diagnostics['residual_prediction']=np.zeros(n)
                for j,column in enumerate(dc.RANK_COLUMNS):
                    diagnostics[f'contribution_{column}']=r[:,j]*coef[j]
                    diagnostics[f'normalized_weight_{column}']=np.full(n,normalized[j])
            elif self.name=='fusion_hgb_then_linear':
                j=list(dc.RANK_COLUMNS).index('rank_hgb')
                coefficient=float(self.payload['anchor_coefficient'])
                anchor=coefficient*r[:,j]
                model=self.payload['model'];residual=finite_vector(model.predict(x),n)
                prediction=anchor+residual
                diagnostics.update(anchor_prediction=anchor,residual_prediction=residual,
                    anchor_hgb_coefficient=np.full(n,coefficient))
                for k,column in enumerate(dc.META_COLUMNS):
                    diagnostics[f'linear_residual_contribution_{column}']=x[:,k]*model.coef_[k]
            elif self.name=='fusion_linear_then_hgb':
                coefficient=np.asarray(self.payload['anchor_coefficients'],float)
                anchor=r@coefficient+float(self.payload['anchor_intercept'])
                model=self.payload['model'];residual=finite_vector(model.predict(x),n)
                prediction=anchor+residual
                diagnostics.update(anchor_prediction=anchor,residual_prediction=residual)
                for j,column in enumerate(dc.RANK_COLUMNS):diagnostics[f'anchor_contribution_{column}']=r[:,j]*coefficient[j]
                diagnostics.update(nonadditive_sensitivity(model,x,residual,coefficient))
            else:
                model=self.payload['model'];prediction=finite_vector(model.predict(x),n)
                diagnostics.update(anchor_prediction=np.zeros(n),residual_prediction=prediction.copy())
                diagnostics.update(nonadditive_sensitivity(model,x,prediction))
            if self.name in ('fusion_nonlinear_stacking','fusion_linear_then_hgb'):
                for j,column in enumerate(dc.META_COLUMNS):diagnostics[f'input_{column}']=x[:,j].copy()
                diagnostics['base_rank_disagreement']=r.std(axis=1)
        prediction=finite_vector(prediction,n)
        diagnostics={k:finite_vector(v,n) for k,v in diagnostics.items()}
        return prediction,diagnostics


def frame_evidence(frame,stage):
    expected={2024} if stage=='validation' else {2024,2025}
    if set(pd.to_datetime(frame.signal_date).dt.year)!=expected:raise ValueError('META_OOF_YEAR_MISMATCH')
    signal=pd.to_datetime(frame.signal_date);labels=pd.to_datetime(frame.label_end_date)
    base=pd.to_datetime(frame.base_fit_cutoff)
    if not (signal.ge(base).all() and signal.lt(STAGES[stage]).all()
            and labels.gt(signal).all() and labels.lt(STAGES[stage]).all()):
        raise ValueError('META_TIME_LEAKAGE')
    expected_rows=90000 if stage=='validation' else 180000
    if len(frame)!=expected_rows:raise ValueError('FIXED_META_BUDGET_MISMATCH')
    columns=['signal_date','ticker','state_id','action','label_end_date',*dc.RANK_COLUMNS,
        'q10_downside_rank','current_weight','cash_weight','age','target_advantage']
    digest=hashlib.sha256(pd.util.hash_pandas_object(frame[columns],index=False).to_numpy().tobytes()).hexdigest()
    return dict(rows=len(frame),signal_first=str(signal.min().date()),signal_last=str(signal.max().date()),
        label_end_max=str(labels.max().date()),oof_years=sorted(expected),dataframe_fingerprint_sha256=digest)


def numerical_evidence(name,payload,r,x,target):
    if name=='fusion_learned_weights':
        w=payload['coefficients'];res=r@w-target;gradient=r.T@res
        violation=np.where(w>1e-14,np.abs(gradient),np.maximum(-gradient,0))
        return dict(solver='scipy.optimize.nnls',maxiter=NNLS_MAXITER,converged=True,
            maximum_kkt_violation=float(violation.max()),normalized_kkt_violation=float(violation.max()/max(1.,np.abs(r.T@target).max())),
            residual_norm=float(np.linalg.norm(res)),coefficients=w.tolist(),normalized_weights=payload['normalized_weights'].tolist(),
            all_zero_coefficients=bool(not w.any()))
    model=payload['model']
    if name=='fusion_hgb_then_linear':
        coef=model.coef_;gradient=x.T@(x@coef-target)+100.*coef
        return dict(solver='lsqr',iterations=np.asarray(model.n_iter_).tolist(),
            normalized_normal_equation_residual=float(np.max(np.abs(gradient))/max(1.,np.max(np.abs(x.T@target)))),
            convergence_note='Fixed solver/tolerance completed; report residual rather than asserting exact optimum',
            anchor_coefficient=float(payload['anchor_coefficient']))
    return dict(iterations=int(model.n_iter_),early_stopping=bool(model.early_stopping),
        fixed_iteration_budget_completed=bool(model.n_iter_==60),
        convergence_note='Fixed 60 boosting rounds; not a convex-optimization convergence claim')


def train():
    OUT.mkdir(exist_ok=True)
    if (OUT/'PRE_FIT_CONTRACT.json').exists() or list(OUT.glob('*.joblib')):
        raise RuntimeError('PRESERVE_EXISTING_META_TRAINING')
    if not (ROOT/'EXPERIMENT_CONTRACT.md').is_file():raise RuntimeError('MISSING_EXPERIMENT_CONTRACT')
    code_sha=sha(__file__);contract_sha=sha(ROOT/'EXPERIMENT_CONTRACT.md')
    spec=dict(status='PRE_FIT_LOCKED',created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        code_sha256=code_sha,contract_sha256=contract_sha,names=NAMES,stages=STAGES,
        meta_columns=list(dc.META_COLUMNS),rank_columns=list(dc.RANK_COLUMNS),
        nnls=dict(fit_intercept=False,maxiter=NNLS_MAXITER,normalization='report only; predictions use raw coefficients; all-zero remains zero'),
        nonlinear_hgb=TREE,linear_residual=RIDGE,
        hgb_anchor='max(0, rank_hgb.T@target / (rank_hgb.T@rank_hgb + 100))',
        main_fit_budget=8,nnls_calls=2,estimator_fit_calls=6,closed_form_anchor_estimates=2,
        test2026_rows_read=0,hyperparameter_search_trials=0,python=platform.python_version(),
        sequential_anchor_note='The old linear anchor was fitted on these meta OOF inputs; this residual fit is not an additional nested cross-fit of that anchor.',
        action_zero_rule='Caller subtracts the zero-action prediction within each security; predict() returns raw outputs.',
        nonlinear_diagnostic_rule='Single-rank-zero sensitivities describe perturbations and do not add up to the prediction.')
    write(OUT/'PRE_FIT_CONTRACT.json',spec)
    results=[]
    for stage in STAGES:
        frame=dc.load_training(stage)
        evidence=frame_evidence(frame,stage)
        r=rank_matrix(frame);x=np.asarray(dc.meta_features(frame),float);y=frame.target_advantage.to_numpy(float)
        if x.shape!=(len(frame),11) or not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('INVALID_META_TRAINING_MATRIX')
        sources=dc.training_sources(stage)
        anchor=dc.load_linear_baseline(stage)
        anchor_coef=np.asarray(anchor.coef_,float).reshape(-1)
        if anchor_coef.shape!=(6,) or float(anchor.intercept_)!=0.:raise ValueError('OLD_LINEAR_ANCHOR_INCOMPATIBLE')
        if not np.allclose(anchor.predict(r),r@anchor_coef,atol=1e-15,rtol=1e-12):raise ValueError('OLD_ANCHOR_FORMULA_MISMATCH')
        for name in NAMES:
            path=OUT/f'{stage}_{stem(name)}.joblib'
            pre={**spec,**evidence,'name':name,'stage':stage,'cutoff_exclusive':STAGES[stage],
                'source_sha256':sources,'created_utc':pd.Timestamp.now(tz='UTC').isoformat()}
            write(OUT/f'{stage}_{stem(name)}_PRE_FIT.json',pre)
            payload={'name':name,'stage':stage,'meta_columns':list(dc.META_COLUMNS),'rank_columns':list(dc.RANK_COLUMNS)}
            start=time.monotonic();target=y;closed_form_count=0
            with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
                warnings.simplefilter('always')
                if name=='fusion_learned_weights':
                    coef,rnorm=nnls(r,y,maxiter=NNLS_MAXITER)
                    payload.update(coefficients=coef,normalized_weights=normalize_nonnegative(coef))
                elif name=='fusion_hgb_then_linear':
                    j=list(dc.RANK_COLUMNS).index('rank_hgb')
                    coefficient=hgb_anchor_coefficient(r[:,j],y);target=y-coefficient*r[:,j]
                    payload.update(anchor_coefficient=coefficient,model=Ridge(**RIDGE).fit(x,target))
                    closed_form_count=1
                elif name=='fusion_linear_then_hgb':
                    target=y-r@anchor_coef
                    payload.update(anchor_coefficients=anchor_coef.copy(),anchor_intercept=0.,
                        anchor_origin='Frozen old stage linear stacking; trained on same meta OOF row years, no extra nested OOF',
                        model=HistGradientBoostingRegressor(**TREE).fit(x,target))
                else:payload['model']=HistGradientBoostingRegressor(**TREE).fit(x,y)
            warning_records=[dict(category=w.category.__name__,message=str(w.message)) for w in caught]
            if any(issubclass(w.category,ConvergenceWarning) for w in caught):
                write(OUT/f'{stage}_{stem(name)}_FAILED.json',dict(status='CONVERGENCE_WARNING',warnings=warning_records))
                raise RuntimeError('META_FIXED_RECIPE_CONVERGENCE_WARNING; no extra search or refit allowed')
            numeric=numerical_evidence(name,payload,r,x,target)
            joblib.dump(payload,path,compress=3)
            receipt={**pre,'status':'PASS','fit_seconds':time.monotonic()-start,
                'main_fit_calls':1,'nnls_calls':int(name=='fusion_learned_weights'),
                'estimator_fit_calls':int(name!='fusion_learned_weights'),'closed_form_anchor_estimates':closed_form_count,
                'old_model_fit_calls':0,'fit_warnings':warning_records,'numerical_evidence':numeric,
                'artifact_path':str(path),'artifact_sha256':sha(path),'test2026_rows_read':0}
            write(OUT/f'{stage}_{stem(name)}_TRAIN_RECEIPT.json',receipt)
            results.append(receipt)
            write(OUT/'TRAIN_RECEIPT.partial.json',dict(status='RUNNING',fits=results))
            print(json.dumps(dict(stage=stage,name=name,status='PASS',seconds=receipt['fit_seconds'],numerical_evidence=numeric)),flush=True)
        if dc.training_sources(stage)!=sources:raise RuntimeError('META_TRAINING_INPUTS_CHANGED')
    if sha(__file__)!=code_sha or sha(ROOT/'EXPERIMENT_CONTRACT.md')!=contract_sha:
        raise RuntimeError('META_TRAINING_CODE_OR_CONTRACT_CHANGED')
    receipt=dict(status='PASS',fits=results,main_fit_calls=8,nnls_calls=2,estimator_fit_calls=6,
        closed_form_anchor_estimates=2,old_model_fit_calls=0,test2026_rows_read=0,
        hyperparameter_search_trials=0,all_inputs_and_codes_unchanged=True)
    write(OUT/'TRAIN_RECEIPT.json',receipt)
    print(json.dumps(dict(status='COMPLETE',main_fit_calls=8,nnls_calls=2,estimator_fit_calls=6)),flush=True)


if __name__=='__main__':train()
