"""Exactly eight predeclared meta fits; all base experts remain frozen.

Selection uses only 2024 Q4 date/path-weighted raw-utility MSE. The selected
interaction shrinkage is then fixed for the 2025 validation and 2026 final
stages. This script never reads 2026 observations or replay performance.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

import meta as m

ROOT, OUT = m.ROOT, m.OUT
PANEL = ROOT/'panel_artifacts'


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
        allow_nan=False, default=str), encoding='utf-8')


def load_panel(year):
    if year not in (2024, 2025):
        raise ValueError('META_PANEL_YEAR_MUST_BE_PRE2026_OOF')
    path, keys_path = PANEL/f'panel_{year}.npz', PANEL/f'panel_keys_{year}.parquet'
    with np.load(path, allow_pickle=False) as loaded:
        arrays = {name:loaded[name].copy() for name in loaded.files}
    keys = pd.read_parquet(keys_path)
    for field, expected in [('expert_order',m.EXPERT_FEATURES), ('basis_order',m.BASIS_FEATURES),
                             ('state_order',m.STATE_FEATURES)]:
        if arrays[field].tolist() != expected:
            raise RuntimeError(f'CONTEXTUAL_PANEL_FEATURE_ORDER:{field}')
    m._validated_inputs(arrays['p'], arrays['z'], arrays['basis'])
    length = len(arrays['p'])
    if length != len(keys)*5 or not np.allclose(arrays['actions'], [0,.025,.05,.075,.1], atol=0, rtol=0):
        raise RuntimeError('CONTEXTUAL_PANEL_ACTION_ALIGNMENT')
    dates = pd.to_datetime(arrays['row_dates'])
    key_dates = pd.to_datetime(keys.signal_date)
    label_dates = pd.to_datetime(keys.label_end_date)
    if not np.array_equal(dates.to_numpy(), np.repeat(key_dates.to_numpy(),5)):
        raise RuntimeError('CONTEXTUAL_PANEL_KEY_DATE_ALIGNMENT')
    if not key_dates.dt.year.eq(year).all() or not label_dates.lt(f'{year+1}-01-01').all():
        raise RuntimeError('CONTEXTUAL_PANEL_LABEL_YEAR_LEAKAGE')
    allowed = np.asarray(arrays['allowed'],bool)
    weights = np.asarray(arrays['weights'],float)
    if allowed.shape != (length,) or weights.shape != (length,):
        raise RuntimeError('CONTEXTUAL_PANEL_WEIGHT_SHAPE')
    expected_weights = m.date_equal_weights(dates,allowed,weights)
    if not np.allclose(weights,expected_weights,rtol=1e-10,atol=1e-12) or not np.all(weights[~allowed] == 0):
        raise RuntimeError('CONTEXTUAL_PANEL_WEIGHTS_NOT_DATE_NORMALIZED')
    # Each fixed behavior path has the same mass on a shared date.
    check = pd.DataFrame(dict(date=dates, path=np.repeat(keys.behavior_path.astype(str).to_numpy(),5), weight=weights))
    path_weights = check.groupby(['date','path']).weight.sum()
    for _, daily in path_weights.groupby(level=0):
        positive = daily[daily>0]
        if len(positive) and not np.allclose(positive.to_numpy(), np.full(len(positive),1/len(positive)),rtol=1e-10,atol=1e-12):
            raise RuntimeError('CONTEXTUAL_PANEL_PATH_WEIGHT_NOT_EQUAL')
    arrays['row_dates'] = dates.to_numpy()
    arrays['label_end_dates'] = np.repeat(label_dates.to_numpy(),5)
    arrays['path'] = np.repeat(keys.behavior_path.astype(str).to_numpy(),5)
    for target in ('target_clip','target_unclipped'):
        if arrays[target].shape != (length,) or not np.isfinite(arrays[target]).all():
            raise RuntimeError('CONTEXTUAL_PANEL_TARGET_INVALID')
    arrays['panel_row_index'] = np.arange(length,dtype=np.int64)
    return arrays, keys


def subset(panel, mask):
    mask = np.asarray(mask,bool)
    length = len(panel['p'])
    result = {name:value[mask] for name,value in panel.items()
              if isinstance(value,np.ndarray) and value.ndim and len(value)==length}
    result['weights'] = m.date_equal_weights(result['row_dates'],result['allowed'],result['weights'])
    return result


def combine(panels):
    names = ['p','z','basis','target_clip','target_unclipped','allowed','row_dates',
             'label_end_dates','path','weights','panel_row_index']
    return {name:np.concatenate([panel[name] for panel in panels],axis=0) for name in names}


def fit_clock(panel, stage):
    cutoff = '2024-10-01' if stage=='internal' else m.STAGE_CUTOFFS[stage]
    if not (pd.to_datetime(panel['row_dates']) < pd.Timestamp(cutoff)).all() or not (
            pd.to_datetime(panel['label_end_dates']) < pd.Timestamp(cutoff)).all():
        raise RuntimeError('CONTEXTUAL_META_LABEL_MATURITY_LEAKAGE')
    return dict(train_signal_min=str(pd.Timestamp(panel['row_dates'].min()).date()),
        train_signal_max=str(pd.Timestamp(panel['row_dates'].max()).date()),
        train_label_end_max=str(pd.Timestamp(panel['label_end_dates'].max()).date()),
        cutoff_exclusive=cutoff, oof_years=sorted(set(pd.to_datetime(panel['row_dates']).year)))


def save_scalers(main, interaction, phase):
    artifacts = {}
    for name, scaler in [('main',main),('interaction',interaction)]:
        path = OUT/f'{phase}_{name}_scaler.joblib'
        joblib.dump(scaler,path,compress=3)
        write(OUT/f'{phase}_{name}_scaler.json',scaler.state())
        artifacts[f'{name}_scaler_artifact']=str(path)
        artifacts[f'{name}_scaler_sha256']=m.sha(path)
        artifacts[f'{name}_scaler_array_sha256']=hash_scaler_arrays(scaler)
    return artifacts


def hash_scaler_arrays(scaler):
    return m.scaler_array_sha256(scaler)


def save_fit(model,panel,phase,scaler_artifacts,receipt):
    multiplier = int(model.interaction_multiplier)
    suffix = f'_{multiplier}' if phase=='internal' and model.kind=='M1' else ''
    artifact=OUT/f'{phase}_{model.kind}{suffix}.joblib'
    joblib.dump(model,artifact,compress=3)
    penalties=[m.ALPHA_MAIN]*21+([m.ALPHA_MAIN*model.interaction_multiplier]*48 if model.kind=='M1' else [])
    coefpath=OUT/f'{phase}_{model.kind}{suffix}_coefficients.parquet'
    pd.DataFrame(dict(feature=model.feature_order,coefficient=model.coefficients,
        penalty=penalties,feature_group=['main']*21+(['interaction']*48 if model.kind=='M1' else []))).to_parquet(coefpath,index=False)
    clock=fit_clock(panel,phase)
    row=dict(kind=model.kind,stage=phase,artifact=str(artifact),artifact_sha256=m.sha(artifact),
        coefficient_artifact=str(coefpath),coefficient_sha256=m.sha(coefpath),
        feature_order=model.feature_order,expert_order=m.EXPERT_FEATURES,basis_order=m.BASIS_FEATURES,
        state_order=m.STATE_FEATURES,coefficients=model.coefficients.tolist(),intercept=model.intercept,
        alpha_main=m.ALPHA_MAIN,interaction_multiplier=model.interaction_multiplier,
        weight_definition='each date=1; fixed behavior paths equal within date; feasible rows equal within path',
        coefficients_are_funding_weights=False)
    row.update(clock)
    row.update(scaler_artifacts)
    row.update(model.metadata)
    row['train_signal_max']=clock['train_signal_max']
    row['train_label_end_max']=clock['train_label_end_max']
    receipt['fits'].append(row)
    receipt['meta_fit_calls']+=1
    write(OUT/'FIT_RECEIPT.partial.json',receipt)
    return row


def fit_phase(phase,panel,kinds,receipt):
    clock=fit_clock(panel,phase)
    main,interaction=m.fit_scalers(panel['p'],panel['z'],panel['basis'],panel['weights'])
    receipt['main_scaler_fit_calls']+=1
    receipt['interaction_scaler_fit_calls']+=1
    artifacts=save_scalers(main,interaction,phase)
    receipt['normalizers'].append(dict(stage=phase,**clock,**artifacts,
        main_weighted_moments=main.state(),interaction_weighted_moments=interaction.state()))
    models={}
    for kind,multiplier in kinds:
        started=time.monotonic()
        with threadpool_limits(limits=2):
            model=m.fit_meta(kind,phase,panel['p'],panel['z'],panel['basis'],panel['target_clip'],
                panel['row_dates'],panel['allowed'],main,interaction,
                interaction_multiplier=multiplier,metadata=clock,sample_weight=panel['weights'])
        model.metadata['fit_seconds']=time.monotonic()-started
        models[(kind,multiplier)]=model
        row=save_fit(model,panel,phase,artifacts,receipt)
        print(json.dumps(dict(status='META_FIT_COMPLETE',stage=phase,kind=kind,
            multiplier=multiplier,rows=len(panel['p']),days=model.metadata['train_days'],
            stationarity=model.metadata['stationarity_relative_residual'])),flush=True)
    # M1 has no difference from M0 when only its new interaction block is zeroed.
    if ('M0',0.) in models:
        static=models[('M0',0.)]
        for (kind,multiplier), conditional in models.items():
            if kind=='M1':
                nested=copy.deepcopy(conditional)
                nested.coefficients=np.r_[static.coefficients,np.zeros(48)]
                nested.intercept=static.intercept
                take=min(1000,len(panel['p']))
                a=static.predict(panel['p'][:take],panel['z'][:take],panel['basis'][:take])
                b=nested.predict(panel['p'][:take],panel['z'][:take],panel['basis'][:take])
                error=float(np.max(np.abs(a-b))) if take else 0.
                if error>1e-12:
                    raise RuntimeError('CONTEXTUAL_M0_M1_NESTED_CHECK_FAILED')
                receipt['nested_checks'].append(dict(stage=phase,multiplier=multiplier,
                    rows=take,maximum_absolute_error=error,status='PASS'))
    return models


def internal_selection(models,validation,receipt):
    predictions={}
    summary=[]
    prediction_frame=pd.DataFrame(dict(panel_row_index=validation['panel_row_index'],
        signal_date=pd.to_datetime(validation['row_dates']),path=validation['path'],
        label_end_date=pd.to_datetime(validation['label_end_dates']),allowed=validation['allowed'],
        sample_weight=validation['weights'],target_clip=validation['target_clip'],
        target_unclipped=validation['target_unclipped']))
    for (kind,multiplier),model in models.items():
        name='M0' if kind=='M0' else f'M1_{int(multiplier)}'
        predicted=model.predict(validation['p'],validation['z'],validation['basis'])
        predictions[name]=predicted
        prediction_frame[f'prediction_{name}']=predicted
        for target_name in ('target_unclipped','target_clip'):
            errors=m.date_error_frame(validation['row_dates'],validation[target_name],predicted,
                validation['allowed'],validation['weights'])
            errors.to_parquet(OUT/f'internal_{name}_{target_name}_date_errors.parquet',index=False)
            summary.append(dict(kind=kind,multiplier=multiplier,target=target_name,
                date_equal_mse=float(errors.mse.mean()),date_equal_mae=float(errors.mae.mean()),
                dates=len(errors),rows=int(validation['allowed'].sum())))
    path=OUT/'internal_selection_predictions.parquet'
    prediction_frame.to_parquet(path,index=False)
    candidates=[record for record in summary if record['kind']=='M1' and record['target']=='target_unclipped']
    best=min(record['date_equal_mse'] for record in candidates)
    # Relative tolerance only, as fixed in the pre-fit contract.
    tied=[record for record in candidates if abs(record['date_equal_mse']-best) <= 1e-12*abs(best)]
    selected=max(record['multiplier'] for record in tied)
    selection=dict(status='SELECTED_AND_FROZEN',selection_year=2024,
        train_signal_exclusive='2024-10-01',train_label_end_exclusive='2024-10-01',
        validation_signal_inclusive='2024-10-01',validation_label_end_exclusive='2025-01-01',
        criterion='date/path-weighted un-clipped feasible action utility MSE',
        candidates=list(m.INTERACTION_MULTIPLIERS),selected_multiplier=selected,
        relative_tie_tolerance=1e-12,tie_rule='stronger shrinkage',metrics=summary,
        predictions_path=str(path),predictions_sha256=m.sha(path),
        selection_2025_rows=0,selection_2026_rows=0)
    write(OUT/'INTERNAL_SELECTION.json',selection)
    receipt['internal_selection']=selection
    return selected


def validation_panel_predictions(models,panel,receipt):
    frame=pd.DataFrame(dict(panel_row_index=panel['panel_row_index'],
        signal_date=pd.to_datetime(panel['row_dates']),label_end_date=pd.to_datetime(panel['label_end_dates']),
        behavior_path=panel['path'],allowed=panel['allowed'],sample_weight=panel['weights'],
        target_clip=panel['target_clip'],target_unclipped=panel['target_unclipped']))
    summary=[]
    predictions={}
    for (kind,multiplier),model in models.items():
        if model.stage!='validation':
            raise RuntimeError('2025_PANEL_PREDICTION_REQUIRES_VALIDATION_META')
        prediction=model.predict(panel['p'],panel['z'],panel['basis'])
        predictions[kind]=prediction
        frame[f'prediction_{kind}']=prediction
        action_delta=(prediction.reshape(-1,5)-prediction.reshape(-1,5)[:,:1]).reshape(-1)
        frame[f'action_delta_prediction_{kind}']=action_delta
        for target_name in ('target_unclipped','target_clip'):
            for output in ('absolute_utility','action_minus_zero_utility'):
                target=panel[target_name]
                predicted=prediction
                if output=='action_minus_zero_utility':
                    target=(target.reshape(-1,5)-target.reshape(-1,5)[:,:1]).reshape(-1)
                    predicted=action_delta
                    frame[f'action_delta_{target_name}']=target
                errors=m.date_error_frame(panel['row_dates'],target,predicted,panel['allowed'],panel['weights'])
                errors.to_parquet(OUT/f'validation2025_{kind}_{target_name}_{output}_date_errors.parquet',index=False)
                summary.append(dict(kind=kind,stage='validation',target=target_name,output=output,
                    date_equal_mse=float(errors.mse.mean()),date_equal_mae=float(errors.mae.mean()),dates=len(errors),
                    evaluation_role='2025 held-out meta prediction diagnosis; not hyperparameter selection'))
    difference=predictions['M1']-predictions['M0']
    delta_difference=(difference.reshape(-1,5)-difference.reshape(-1,5)[:,:1]).reshape(-1)
    frame['M1_minus_M0_utility']=difference
    frame['M1_minus_M0_action_delta']=delta_difference
    keys=pd.read_parquet(PANEL/'panel_keys_2025.parquet')
    warning_path=PANEL/'warning_keys_2025.parquet'
    if warning_path.exists():
        warning_keys=pd.read_parquet(warning_path)
        if len(warning_keys)!=len(keys) or any(not np.array_equal(keys[name].astype(str).to_numpy(),
                warning_keys[name].astype(str).to_numpy()) for name in ('key_id','behavior_path','ticker')):
            raise RuntimeError('CONTEXTUAL_WARNING_SIDECAR_KEY_ALIGNMENT')
        for field in ('y_next_open','label_price_warning'):
            keys[field]=warning_keys[field].to_numpy()
    frame['ticker']=np.repeat(keys.ticker.astype(str).to_numpy(),5)
    warning_available='label_price_warning' in keys
    if warning_available:
        frame['label_price_warning']=np.repeat(keys.label_price_warning.fillna(False).astype(bool).to_numpy(),5)
    else:
        frame['label_price_warning']=False
    forward_column=next((name for name in ('y_next_open','forward_return','label_return') if name in keys),None)
    if forward_column:
        frame['forward_return']=np.repeat(keys[forward_column].to_numpy(float),5)
        frame['forward_return_abs_gt20pct']=frame.forward_return.abs()>.2
    frame['training_clip_changes_label']=~np.isclose(panel['target_clip'],panel['target_unclipped'],rtol=1e-12,atol=1e-14)
    concentration=[]
    for output,values in [('absolute_utility',difference),('action_minus_zero_utility',delta_difference)]:
        df=pd.DataFrame(dict(signal_date=frame.signal_date,ticker=frame.ticker,
            abs_difference=np.abs(values)*panel['weights'],squared_difference=values**2*panel['weights']))
        for group in ('signal_date','ticker'):
            aggregated=df.groupby(group,as_index=False).agg(weighted_absolute_difference=('abs_difference','sum'),
                weighted_squared_difference=('squared_difference','sum'))
            path=OUT/f'validation2025_prediction_difference_{output}_by_{group}.parquet'
            aggregated.to_parquet(path,index=False)
            total=float(aggregated.weighted_squared_difference.sum())
            ranked=aggregated.sort_values('weighted_squared_difference',ascending=False)
            concentration.append(dict(output=output,group=group,groups=len(aggregated),
                weighted_squared_difference_total=total,
                top1_share=float(ranked.weighted_squared_difference.iloc[:1].sum()/total) if total else 0.,
                top5_share=float(ranked.weighted_squared_difference.iloc[:5].sum()/total) if total else 0.,
                top10_share=float(ranked.weighted_squared_difference.iloc[:10].sum()/total) if total else 0.,
                path=str(path),sha256=m.sha(path)))
    error_attribution=[]
    for output in ('absolute_utility','action_minus_zero_utility'):
        target=panel['target_unclipped']
        static=predictions['M0']
        conditional=predictions['M1']
        if output=='action_minus_zero_utility':
            target=(target.reshape(-1,5)-target.reshape(-1,5)[:,:1]).reshape(-1)
            static=(static.reshape(-1,5)-static.reshape(-1,5)[:,:1]).reshape(-1)
            conditional=(conditional.reshape(-1,5)-conditional.reshape(-1,5)[:,:1]).reshape(-1)
        improvement=((static-target)**2-(conditional-target)**2)*panel['weights']
        frame[f'M1_squared_error_improvement_{output}']=improvement
        df=pd.DataFrame(dict(signal_date=frame.signal_date,ticker=frame.ticker,
            label_price_warning=frame.label_price_warning,
            training_clip_changes_label=frame.training_clip_changes_label,
            weighted_squared_error_improvement=improvement,
            weighted_squared_error_M0=(static-target)**2*panel['weights'],
            weighted_squared_error_M1=(conditional-target)**2*panel['weights'],
            date_weight=panel['weights']))
        if forward_column:
            df['forward_return_abs_gt20pct']=frame.forward_return_abs_gt20pct
        for group in ('signal_date','ticker','label_price_warning','training_clip_changes_label',
                      *(['forward_return_abs_gt20pct'] if forward_column else [])):
            aggregated=df.groupby(group,as_index=False).agg(
                weighted_squared_error_improvement=('weighted_squared_error_improvement','sum'),
                weighted_squared_error_M0=('weighted_squared_error_M0','sum'),
                weighted_squared_error_M1=('weighted_squared_error_M1','sum'),
                date_weight=('date_weight','sum'))
            path=OUT/f'validation2025_error_improvement_{output}_by_{group}.parquet'
            aggregated.to_parquet(path,index=False)
            gains=aggregated.weighted_squared_error_improvement.clip(lower=0)
            losses=-aggregated.weighted_squared_error_improvement.clip(upper=0)
            error_attribution.append(dict(output=output,group=group,groups=len(aggregated),
                net_weighted_squared_error_improvement=float(aggregated.weighted_squared_error_improvement.sum()),
                positive_improvement_total=float(gains.sum()),negative_improvement_total=float(losses.sum()),
                top1_positive_share=float(gains.nlargest(1).sum()/gains.sum()) if gains.sum() else 0.,
                top5_positive_share=float(gains.nlargest(5).sum()/gains.sum()) if gains.sum() else 0.,
                top5_negative_share=float(losses.nlargest(5).sum()/losses.sum()) if losses.sum() else 0.,
                path=str(path),sha256=m.sha(path)))
    path=OUT/'validation_2025_panel_predictions.parquet'
    frame.to_parquet(path,index=False)
    receipt['validation_panel_prediction']=dict(path=str(path),sha256=m.sha(path),metrics=summary,
        meta_stage='validation',base_stage='validation',used_for_selection=False,
        difference_concentration=concentration,error_improvement_attribution=error_attribution,
        inherited_label_price_warning_field_available=warning_available,
        forward_return_field=forward_column,
        price_warning_rows_excluded=0,
        label_warning_caveat='Inherited label_price_warning rows are retained; raw utility diagnostics may be concentrated in unreliable price labels.')


def main():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError('PRESERVE_EXISTING_CONTEXTUAL_META_ARTIFACTS')
    lock_path=ROOT/'PRE_FIT_LOCK.json'
    lock=m.read(lock_path)
    if lock['status']!='PRE_FIT_LOCKED' or lock['planned_meta_fit_calls']!=8:
        raise RuntimeError('CONTEXTUAL_PRE_FIT_LOCK_MISSING')
    if lock['alpha_main']!=100 or lock['interaction_multipliers']!=[4,16,64]:
        raise RuntimeError('CONTEXTUAL_PRE_FIT_PARAMETER_MISMATCH')
    contract_path=ROOT/'EXPERIMENT_CONTRACT.md'
    m.checked_path(contract_path,lock['contract_sha256'])
    panel_receipt_path=PANEL/'PANEL_RECEIPT.json'
    panel_receipt=m.read(panel_receipt_path)
    if panel_receipt['status']!='PASS':
        raise RuntimeError('CONTEXTUAL_PANEL_RECEIPT_NOT_COMPLETE')
    if panel_receipt['fit_2026_rows']!=0 or panel_receipt['read_2026_rows']!=0 or panel_receipt['expert_fit_attempts']!=0:
        raise RuntimeError('CONTEXTUAL_PANEL_RECEIPT_TIME_OR_EXPERT_FIT_VIOLATION')
    for year in (2024,2025):
        record=panel_receipt['artifacts'][str(year)]
        m.checked_path(PANEL/f'panel_{year}.npz',record['matrix_sha256'])
        m.checked_path(PANEL/f'panel_keys_{year}.parquet',record['keys_sha256'])
    m.checked_path(PANEL/'PRE_PANEL_CONTRACT.json',panel_receipt['pre_panel_contract_sha256'])
    for path,digest in panel_receipt['source_sha256'].items():
        m.checked_path(path,digest)
    panels={year:load_panel(year)[0] for year in (2024,2025)}
    warning_paths=[PANEL/f'warning_keys_{year}.parquet' for year in (2024,2025)]
    if not all(path.is_file() for path in warning_paths):
        raise RuntimeError('CONTEXTUAL_INHERITED_LABEL_WARNING_DIAGNOSTIC_INPUT_NOT_READY')
    input_paths=[lock_path,contract_path,panel_receipt_path,PANEL/'PRE_PANEL_CONTRACT.json',PANEL/'schema.json',*warning_paths,
        *[PANEL/f'panel_{year}{suffix}' for year in (2024,2025) for suffix in ('.npz',)],
        *[PANEL/f'panel_keys_{year}.parquet' for year in (2024,2025)]]
    source_paths=[Path(__file__).resolve(),ROOT/'meta.py']
    input_hashes={str(path):m.sha(path) for path in input_paths+source_paths}
    input_hashes.update(panel_receipt['source_sha256'])
    if str(m.OLD_ROOT) not in sys.path:
        sys.path.insert(0,str(m.OLD_ROOT))
    import ensemble as old_ensemble
    bases={stage:old_ensemble.BaseBundle(stage) for stage in ('validation','final')}
    for base in bases.values():
        input_hashes.update(base.hashes)
    OUT.mkdir(parents=True)
    receipt=dict(status='RUNNING',experiment='A2_CONTEXTUAL_STACKING_R1',fits=[],normalizers=[],nested_checks=[],
        meta_fit_calls=0,main_scaler_fit_calls=0,interaction_scaler_fit_calls=0,
        new_base_expert_fit_calls=0,fit_2026_rows=0,test_rows_read=0,
        pre_fit_contract_path=str(lock_path),pre_fit_contract_sha256=m.sha(lock_path),
        source_sha256={str(path):m.sha(path) for path in source_paths},input_sha256=input_hashes,
        inference_dependencies={stage:base.hashes for stage,base in bases.items()},
        inference_predictor_clocks={stage:base.predictor_clocks for stage,base in bases.items()},
        objective='sum_dates mean_path(mean_feasible(error²)) + 100*main_L2 + 100*multiplier*interaction_L2',
        alpha_scale_note='new date-weight sum D; not equivalent to the old 90000 unweighted rows with alpha100',
        effective_coefficient_function=dict(
            standardized_p='beta_j + sum_k [(z_k-main_mean_zk)/main_scale_zk] * gamma_jk/interaction_scale_jk',
            raw_p='standardized_p coefficient divided by main_scale_pj',
            conditional_intercept='intercept - sum_jk gamma_jk*interaction_mean_jk/interaction_scale_jk',
            funding_weights=False,expert_features=m.EXPERT_FEATURES,state_features=m.STATE_FEATURES))
    panel2024=panels[2024]
    train_mask=(panel2024['row_dates']<np.datetime64('2024-10-01')) & (
        panel2024['label_end_dates']<np.datetime64('2024-10-01'))
    validation_mask=(panel2024['row_dates']>=np.datetime64('2024-10-01')) & (
        panel2024['label_end_dates']<np.datetime64('2025-01-01'))
    train,validation=subset(panel2024,train_mask),subset(panel2024,validation_mask)
    receipt['internal_split']=dict(train_rows=len(train['p']),validation_rows=len(validation['p']),
        purged_rows=int((~(train_mask|validation_mask)).sum()),
        train_dates=int(pd.Series(train['row_dates']).nunique()),validation_dates=int(pd.Series(validation['row_dates']).nunique()),
        train_label_end_max=str(pd.Timestamp(train['label_end_dates'].max()).date()),
        validation_signal_min=str(pd.Timestamp(validation['row_dates'].min()).date()))
    internal_models=fit_phase('internal',train,[('M0',0.),*[('M1',value) for value in m.INTERACTION_MULTIPLIERS]],receipt)
    selected=internal_selection(internal_models,validation,receipt)
    validation_models=fit_phase('validation',panel2024,[('M0',0.),('M1',selected)],receipt)
    validation_panel_predictions(validation_models,panels[2025],receipt)
    final=combine([panels[2024],panels[2025]])
    fit_phase('final',final,[('M0',0.),('M1',selected)],receipt)
    if receipt['meta_fit_calls']!=8 or receipt['main_scaler_fit_calls']!=3 or receipt['interaction_scaler_fit_calls']!=3:
        raise RuntimeError('CONTEXTUAL_UNEXPECTED_FIT_COUNT')
    if any(m.sha(path)!=digest for path,digest in input_hashes.items()):
        raise RuntimeError('CONTEXTUAL_FIT_INPUT_CHANGED')
    receipt.update(status='PASS',selected_interaction_multiplier=selected,source_hashes_unchanged=True)
    write(OUT/'FIT_RECEIPT.json',receipt)
    # Actual stage-specific deserialization, including external/embedded scaler match.
    loaded=[]
    for stage in ('validation','final'):
        for kind in ('M0','M1'):
            model=m.ContextualMeta(kind,stage)
            loaded.append(model.loaded_receipt)
    write(OUT/'POST_FIT_ACTUAL_LOAD_RECEIPTS.json',dict(status='PASS',loads=loaded))
    print(json.dumps(dict(status='PASS',meta_fit_calls=8,new_base_expert_fit_calls=0,
        fit_2026_rows=0,selected_multiplier=selected,
        validation_2025=receipt['validation_panel_prediction']['metrics'])),flush=True)


if __name__=='__main__':
    main()
