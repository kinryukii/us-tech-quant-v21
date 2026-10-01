"""Fit two meta models on causal 2024/2025 out-of-fold base predictions only."""
from pathlib import Path
import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import ensemble as e
import values as v
from train_values import read_frame, sample, counterfactual

ROOT, OUT = e.ROOT, e.OUT
SPEC = dict(alpha=100., solver='lsqr', tol=1e-6)


def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False), encoding='utf-8')


def expand_observable_state(frame):
    """Same outer-state/outer-action/inner-stock order as reward construction."""
    n = len(frame)
    x = np.tile(frame[v.FEATURES].to_numpy(float),(15,1))
    current = np.repeat([s[0] for s in v.STATE_GRID for _ in v.ACTIONS],n)
    cash = np.repeat([s[1] for s in v.STATE_GRID for _ in v.ACTIONS],n)
    age = np.repeat([s[2] for s in v.STATE_GRID for _ in v.ACTIONS],n)
    action = np.repeat(np.tile(v.ACTIONS,len(v.STATE_GRID)),n)
    return x,current,cash,age,action


def select_oof(frame, year):
    year_start, end = pd.Timestamp(f'{year}-01-01'), f'{year+1}-01-01'
    if year not in [2024,2025]:
        raise ValueError('OOF_YEAR_MUST_BE_2024_OR_2025')
    selected, audit = sample(frame.loc[frame.signal_date.ge(year_start)&frame.signal_date.lt(end)],end,budget=6000)
    if not selected.signal_date.dt.year.eq(year).all() or not selected.label_end_date.lt(end).all():
        raise RuntimeError('OOF_LABEL_BOUNDARY')
    return selected,audit


def build_oof(selected, year, base):
    expected = 'early' if year == 2024 else 'validation'
    if base.stage != expected or pd.Timestamp(base.boundary) > selected.signal_date.min():
        raise RuntimeError('OOF_PREDICTOR_NOT_STRICTLY_PRIOR_YEAR')
    matrix = base.matrix(*expand_observable_state(selected))
    _, target, label_audit = counterfactual(selected,robust_training=True)
    if matrix.shape != (len(selected)*15,len(e.META_FEATURES)) or len(matrix) != len(target):
        raise RuntimeError('OOF_MATRIX_REWARD_ALIGNMENT')
    return matrix,target,label_audit


def main():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError('PRESERVE_EXISTING_META_TRAINING')
    # Load and verify every base before creating the pre-fit output directory.
    bases = {stage:e.BaseBundle(stage) for stage in ['early','validation','final']}
    frame = read_frame()
    picked, audits = {}, {}
    for year in [2024,2025]:
        picked[year],audits[year] = select_oof(frame,year)
    OUT.mkdir(parents=True)
    for year,selected in picked.items():
        path = OUT/f'oof_sample_keys_{year}.parquet'
        selected[['signal_date','ticker','label_end_date']].to_parquet(path,index=False)
        audits[year]['sample_keys_path'] = str(path)
        audits[year]['sample_keys_sha256'] = v.sha(path)
    hashes = {str(path):v.sha(path) for path in [v.DATA,ROOT/'ENSEMBLE_CONTRACT.md',
        ROOT/'EXPERIMENT_CONTRACT.md',ROOT/'ensemble.py',Path(__file__),ROOT/'values.py',
        ROOT/'train_values.py',ROOT/'neural.py']}
    for base in bases.values():
        hashes.update(base.hashes)
    contract = dict(status='PRE_FIT_LOCKED', model='StandardScaler + Ridge',parameters=SPEC,
        feature_order=e.META_FEATURES, base_model_names=[*v.NAMES,'direct_mlp'],
        oof_sampling={str(year):audit for year,audit in audits.items()},
        oof_predictor_clocks={str(year):bases['early' if year==2024 else 'validation'].predictor_clocks for year in picked},
        training_years={'validation':[2024],'final':[2024,2025]},
        inference_base_stages={'validation':'validation','final':'final'},
        counterfactual_order='state outer, action middle, selected stock-date inner',
        reward='same fixed one-step capacity/cost/risk reward as train_values; training return clipped to +/-0.20',
        input_sha256=hashes, fit_2026_rows=0,hyperparameter_search_count=0,planned_meta_fit_calls=2,
        caveat='chronological stacking with base-refit distribution shift; OOF rows share stocks/dates and are not independent experiments')
    write(OUT/'PRE_FIT_CONTRACT.json',contract)
    matrices,targets,label_audits = {},{},{}
    for year,selected in picked.items():
        print(json.dumps({'status':'BUILDING_OOF','year':year,'stock_date_rows':len(selected)}),flush=True)
        with threadpool_limits(limits=2):
            matrix,target,label_audit = build_oof(selected,year,bases['early' if year==2024 else 'validation'])
        path = OUT/f'oof_matrix_{year}.npz'
        np.savez_compressed(path,features=matrix,target=target,feature_order=np.asarray(e.META_FEATURES,str))
        matrices[year],targets[year],label_audits[year] = matrix,target,label_audit
        audits[year]['matrix_path'],audits[year]['matrix_sha256'] = str(path),v.sha(path)
    receipt = dict(status='RUNNING',fits=[],fit_2026_rows=0,meta_fit_calls=0,scaler_fit_calls=0,
        hyperparameter_search_count=0,feature_order=e.META_FEATURES,
        pre_fit_contract_sha256=v.sha(OUT/'PRE_FIT_CONTRACT.json'),input_sha256=hashes,
        oof_sampling={str(year):audit for year,audit in audits.items()},
        oof_predictor_clocks=contract['oof_predictor_clocks'],
        inference_dependencies={stage:bases[stage].hashes for stage in ['validation','final']},
        inference_predictor_clocks={stage:bases[stage].predictor_clocks for stage in ['validation','final']})
    for stage,years in [('validation',[2024]),('final',[2024,2025])]:
        started=time.monotonic()
        matrix=np.concatenate([matrices[y] for y in years]);target=np.concatenate([targets[y] for y in years])
        model=make_pipeline(StandardScaler(),Ridge(**SPEC))
        with threadpool_limits(limits=2):
            model.fit(matrix,target)
        if not np.isfinite(model[-1].coef_).all():
            raise RuntimeError('META_NONFINITE_COEFFICIENT')
        artifact=OUT/f'{stage}_meta.joblib'
        joblib.dump(model,artifact,compress=3)
        sample_rows=pd.concat([picked[y] for y in years],ignore_index=True)
        cutoff=e.STAGES[stage]
        assert sample_rows.signal_date.lt(cutoff).all() and sample_rows.label_end_date.lt(cutoff).all()
        row=dict(stage=stage,artifact=str(artifact),artifact_sha256=v.sha(artifact),
            cutoff_exclusive=cutoff,oof_years=years,train_rows=len(matrix),
            independent_stock_date_rows=len(sample_rows),train_days=int(sample_rows.signal_date.nunique()),
            train_signal_max=str(sample_rows.signal_date.max().date()),
            train_label_end_max=str(sample_rows.label_end_date.max().date()),
            feature_order=e.META_FEATURES,coefficients=model[-1].coef_.tolist(),
            intercept=float(model[-1].intercept_),scaler_mean=model[0].mean_.tolist(),
            scaler_scale=model[0].scale_.tolist(),parameters=SPEC,
            fit_seconds=time.monotonic()-started,fit_2026_rows=0,
            label_audit={str(y):label_audits[y] for y in years})
        receipt['fits'].append(row);receipt['meta_fit_calls']+=1;receipt['scaler_fit_calls']+=1
        write(OUT/'FIT_RECEIPT.partial.json',receipt)
        print(json.dumps({'status':'META_FIT_COMPLETE','stage':stage,'rows':len(matrix),
                          'signal_max':row['train_signal_max'],'label_end_max':row['train_label_end_max']}),flush=True)
    if any(v.sha(path)!=digest for path,digest in hashes.items()):
        raise RuntimeError('META_TRAINING_INPUT_CHANGED')
    receipt.update(status='PASS',source_hashes_unchanged=True,test_rows_read=0)
    write(OUT/'FIT_RECEIPT.json',receipt)
    print(json.dumps({'status':'PASS','meta_fit_calls':2,'fit_2026_rows':0}),flush=True)


if __name__=='__main__':
    main()
