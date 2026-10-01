"""Additional pre-2024 base fits solely for genuinely forward 2024 stacking data.

This additive experiment preserves the earlier values.py contract and fits.
No 2024, 2025 or 2026 outcomes are consumed by these development estimators.
"""
from __future__ import annotations

import json
from pathlib import Path
import platform
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

import values as base

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'development_value_artifacts'
DATA = base.DATA
FEATURES = base.FEATURES
ACTIONS = base.ACTIONS
mapped_features = base.mapped_features
predict_values = base.predict_values
allocate_joint_scores = base.allocate_joint_scores
NAMES = base.NAMES
CUTOFF = '2024-01-01'


class DevelopmentPolicy:
    def __init__(self, name, stage='development'):
        if stage != 'development' or name not in (*NAMES,'quantile_risk'):
            raise ValueError('ONLY_DEVELOPMENT_STAGE_AVAILABLE')
        self.name=name; self.stage=stage; self.models={}
        receipt=json.loads((OUT/'FIT_RECEIPT.json').read_text(encoding='utf-8'))
        assert receipt['status']=='PASS' and receipt['cutoff_exclusive']==CUTOFF
        names=('q10','q50','q90') if name=='quantile_risk' else (name,)
        for key in names:
            record=next(r for r in receipt['fits'] if r['name']==key)
            repairs=[r for r in receipt['numerical_repairs'] if r['name']==key]
            if repairs:record=repairs[-1]
            path=Path(record['artifact'])
            assert base.sha(path)==record['artifact_sha256']
            self.models[key]=joblib.load(path)


def load_policy(name,stage='development'):
    return DevelopmentPolicy(name,stage)


def train():
    OUT.mkdir(exist_ok=True)
    if (OUT/'PRE_FIT_CONTRACT.json').exists() or list(OUT.glob('*.joblib')):
        raise RuntimeError('EXISTING_DEVELOPMENT_FITS_PRESERVED')
    columns=['signal_date','ticker','label_end_date','label_available','new_buy_eligible','y_next_open',*FEATURES]
    frame=pd.read_parquet(DATA,columns=columns,filters=[('signal_date','<',pd.Timestamp(CUTOFF))])
    assert frame.signal_date.lt(CUTOFF).all()
    mature=base.mature_rows(frame,CUTOFF)
    selected,dates=base.select_dates(mature)
    keys=OUT/'sample_keys_development.parquet'
    selected[['signal_date','ticker','label_end_date']].to_parquet(keys,index=False)
    sample_audit={'mature_base_rows':len(mature),'base_rows':len(selected),
        'counterfactual_rows':len(selected)*15,'mature_dates':len(dates),
        'sampled_dates':selected.signal_date.nunique(),
        'signal_min':str(selected.signal_date.min().date()),
        'signal_max':str(selected.signal_date.max().date()),
        'label_end_max':str(selected.label_end_date.max().date()),
        'sample_keys_sha256':base.sha(keys)}
    spec={'status':'PRE_FIT_LOCKED','created_utc':pd.Timestamp.now(tz='UTC').isoformat(),
        'purpose':'New pre-2024 base fits only; generate forward OOF features in 2024 for stacking',
        'stage':'development','cutoff_exclusive':CUTOFF,'source':str(DATA),'source_sha256':base.sha(DATA),
        'training_code_sha256':base.sha(__file__),'base_code_sha256':base.sha(base.__file__),
        'original_contract_sha256':base.sha(ROOT/'EXPERIMENT_CONTRACT.md'),
        'parameters':base.SPECS,'features':FEATURES,'sample':sample_audit,
        'state_grid':base.STATE_GRID,'action_grid':ACTIONS.tolist(),
        'nominal_cash':base.NOMINAL_CASH,'capacity_fraction':base.CAPACITY_FRACTION,
        'cost_per_side':base.COST,'risk_aversion':base.RISK_AVERSION,
        'return_clip_training_only':[-.2,.2],
        'reward':'Same frozen capacity-limited one-step net utility as values.py',
        'main_fit_budget':7,'hyperparameter_search_count':0,
        '2024_or_later_training_rows':0,'2026_rows_read':0,
        'elastic_numerical_repair':{'maximum_attempts':1,'warm_start':True,'precompute':True,
            'max_iter':25000,'same_data_objective_scaler':True},
        'selection':'No validation or test performance consulted; no architecture or parameter selection',
        'limitations':['Shares the original adjusted research price-coordinate and data-quality limitations.',
            'Only chronological OOF predictions may train a stacker; no in-sample base predictions.',
            'The 2024 developer predictions and 2025 forward validation must remain distinct.']}
    base.write(OUT/'PRE_FIT_CONTRACT.json',spec)
    tx,ty,label_audit=base.counterfactual(selected)
    assert len(tx)<=200000
    receipt={'status':'RUNNING','stage':'development','cutoff_exclusive':CUTOFF,
        'pre_fit_contract_sha256':base.sha(OUT/'PRE_FIT_CONTRACT.json'),'sampling':sample_audit,
        'fits':[],'numerical_repairs':[],'fit_calls_attempted':0,'fit_calls_completed':0,
        'test2026_rows_read':0,'2024_or_later_training_rows':0,'hyperparameter_search_count':0,
        'python':platform.python_version()}
    for name in NAMES:
        target=(ty>0).astype(int) if name=='logistic' else ty
        model=base.estimator(name)
        receipt['current_fit']=name;receipt['fit_calls_attempted']+=1
        base.write(OUT/'FIT_RECEIPT.partial.json',receipt)
        start=time.monotonic()
        with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
            warnings.simplefilter('always');model.fit(tx,target)
        artifact=OUT/f'development_{name}.joblib';joblib.dump(model,artifact,compress=3)
        final=model[-1] if hasattr(model,'steps') else model
        success=not any(issubclass(w.category,ConvergenceWarning) for w in caught)
        row={'stage':'development','name':name,'train_rows':len(tx),'model_input_features':tx.shape[1],
            'fit_seconds':time.monotonic()-start,'train_signal_max':sample_audit['signal_max'],
            'train_label_end_max':sample_audit['label_end_max'],'artifact':str(artifact),
            'artifact_sha256':base.sha(artifact),'iterations':np.asarray(getattr(final,'n_iter_',None)).tolist(),
            'converged':success,'fit_warnings':[{'category':w.category.__name__,'message':str(w.message)} for w in caught],
            **label_audit}
        receipt['fits'].append(row);receipt['fit_calls_completed']+=1
        print(json.dumps(row),flush=True)
        if not success:
            if name!='elastic_net':
                base.write(OUT/'FIT_RECEIPT.partial.json',receipt)
                raise RuntimeError(f'DEVELOPMENT_FIT_NOT_CONVERGED:{name}')
            final.set_params(precompute=True,max_iter=25000,warm_start=True)
            start=time.monotonic()
            with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=2):
                warnings.simplefilter('always');final.fit(model[0].transform(tx),target)
            success=not any(issubclass(w.category,ConvergenceWarning) for w in caught)
            artifact=OUT/'development_elastic_net_numerical_repair.joblib';joblib.dump(model,artifact,compress=3)
            repair={'stage':'development','name':name,'original_artifact':row['artifact'],
                'original_sha256':row['artifact_sha256'],'artifact':str(artifact),'artifact_sha256':base.sha(artifact),
                'fit_seconds':time.monotonic()-start,'iterations':int(final.n_iter_),'dual_gap':float(final.dual_gap_),
                'converged':success,'same_samples_objective_scaler':True,'additional_fit_calls':1,
                'used_for_policy':success,'fit_warnings':[{'category':w.category.__name__,'message':str(w.message)} for w in caught]}
            receipt['numerical_repairs'].append(repair)
            print(json.dumps({'numerical_repair':repair}),flush=True)
            if not success:
                base.write(OUT/'FIT_RECEIPT.partial.json',receipt)
                raise RuntimeError('DEVELOPMENT_ELASTIC_REPAIR_NOT_CONVERGED')
        receipt.pop('current_fit',None)
        base.write(OUT/'FIT_RECEIPT.partial.json',receipt)
    assert base.sha(DATA)==spec['source_sha256'] and base.sha(__file__)==spec['training_code_sha256']
    assert base.sha(base.__file__)==spec['base_code_sha256']
    receipt.update(status='PASS',main_fit_calls=7,scaler_fit_calls=3,
        total_fit_calls_including_numerical_repairs=7+len(receipt['numerical_repairs']),
        source_and_codes_unchanged=True)
    base.write(OUT/'FIT_RECEIPT.json',receipt)
    checks=[]
    for name in NAMES:
        policy=load_policy(name)
        pred=base.predict_values(policy.models[name],name,tx[:512])
        assert np.isfinite(pred).all()
        checks.append({'name':name,'hash_verified':True,'finite_inference':True})
    base.write(OUT/'VERIFY.json',{'status':'PASS','artifact_checks':checks,
        'all_mature_dates_covered':selected.signal_date.nunique()==len(dates),
        'signal_and_label_end_strictly_before':CUTOFF,'2026_rows_read':0})
    print(json.dumps({'status':'PASS','main_fits':7,'numerical_repairs':len(receipt['numerical_repairs']),
        'sample':sample_audit}),flush=True)


if __name__=='__main__':
    train()
