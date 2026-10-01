"""Read-only frozen-stack provenance and full 2025 inference reconstruction.

No fitting, no replay, no portfolio counterfactual, and no 2026 outcomes.
The final-stage output is only a post-hoc technical negative control.
"""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import time

HERE = Path(__file__).resolve().parent
WS = HERE.parent.parent
ROOT = WS / 'a2_multimodel_joint_20260928'
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import joblib
import torch
from threadpoolctl import threadpool_limits
import ensemble as e
import values as v
import evaluate
from train_values import counterfactual
from train_ensemble import expand_observable_state


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def clean(value):
    if isinstance(value, dict): return {str(k): clean(x) for k, x in value.items()}
    if isinstance(value, (list, tuple)): return [clean(x) for x in value]
    if isinstance(value, np.ndarray): return clean(value.tolist())
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating, float)): return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)): return bool(value)
    if isinstance(value, (Path, pd.Timestamp)): return str(value)
    return value


def write(name, value):
    (HERE/name).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def array_sha(array):
    """Hash dtype, shape and canonical little-endian float64 C-order bytes."""
    a = np.asarray(array, dtype='<f8', order='C')
    metadata = json.dumps({'dtype':'<f8', 'shape':list(a.shape)}, sort_keys=True).encode()
    return hashlib.sha256(metadata+b'\n'+a.tobytes(order='C')).hexdigest()


def delta(a,b):
    a,b=np.asarray(a),np.asarray(b)
    return dict(shape=list(a.shape), exact_equal=bool(np.array_equal(a,b)),
                max_abs_error=float(np.max(np.abs(a-b))) if a.size else 0.,
                allclose_atol_1e_12_rtol_1e_10=bool(np.allclose(a,b,atol=1e-12,rtol=1e-10)))


def main():
    started=time.monotonic()
    guard=evaluate.forbid_fitting()
    def deny_backward(*args, **kwargs):
        guard['attempts']+=1
        raise RuntimeError('BACKWARD_FORBIDDEN_DURING_READ_ONLY_AUDIT')
    torch.Tensor.backward=deny_backward
    torch.set_num_threads(2)
    folder=ROOT/'evaluation_2025/cost_10/ensemble_stacked'
    frozen_path=folder.parent/'FROZEN_BEFORE_REPLAY.json'
    frozen=read(frozen_path)
    receipt_path=e.OUT/'FIT_RECEIPT.json'
    receipt=read(receipt_path)
    ledger_names=['raw_model_outputs','signal_contexts','target_decisions']
    source_paths=set(Path(p) for p in frozen['source_sha256'])
    source_paths.update([frozen_path,receipt_path,folder/'metadata.json',folder/'DONE.json',folder.parent/'COMPLETE.json'])
    source_paths.update(folder/f'{name}.parquet' for name in ledger_names)
    before={str(p):sha(p) for p in sorted(source_paths)}
    write('INPUT_SHA256.json',before)
    # A Python audit hook blocks any accidental source mutation, even beyond fit().
    root_text=str(ROOT.resolve()).lower()
    def no_source_writes(event,args):
        if event=='open' and isinstance(args[0],(str,bytes,Path)):
            path=str(Path(args[0]).resolve()).lower()
            mode=args[1] or ''
            flags=args[2] if len(args)>2 else 0
            mutating=any(c in mode for c in 'wax+') or (isinstance(flags,int) and flags & (1|2|64|512|1024))
            if mutating and (path==root_text or path.startswith(root_text+'\\')):
                raise RuntimeError('FROZEN_SOURCE_WRITE_FORBIDDEN:'+path)
    sys.addaudithook(no_source_writes)
    frozen_rows=[]
    for path,expected in frozen['source_sha256'].items():
        frozen_rows.append(dict(path=path,recorded_sha256=expected,current_sha256=before[path],matches=expected==before[path]))
    pd.DataFrame(frozen_rows).to_csv(HERE/'frozen_manifest_check.csv',index=False,encoding='utf-8-sig')
    assert all(r['matches'] for r in frozen_rows)
    input_receipt_checks=[dict(path=p,receipt_sha256=h,current_sha256=sha(p),matches=sha(p)==h)
                          for p,h in receipt['input_sha256'].items()]
    assert all(r['matches'] for r in input_receipt_checks)
    write('receipt_input_hash_check.json',input_receipt_checks)
    assert sha(e.OUT/'PRE_FIT_CONTRACT.json')==receipt['pre_fit_contract_sha256']
    print('FROZEN_INPUTS_VERIFIED',len(frozen_rows),flush=True)
    data=pd.read_parquet(v.DATA)
    assert data.signal_date.lt('2026-01-01').all()
    index=data.set_index(['signal_date','ticker'],verify_integrity=True)
    arrays={}
    oof_results=[]
    clock_rows=[]
    for year in (2024,2025):
        audit=receipt['oof_sampling'][str(year)]
        assert sha(audit['sample_keys_path'])==audit['sample_keys_sha256']
        assert sha(audit['matrix_path'])==audit['matrix_sha256']
        keys=pd.read_parquet(audit['sample_keys_path'])
        selected=index.loc[pd.MultiIndex.from_frame(keys[['signal_date','ticker']])].reset_index()
        assert len(selected)==6000 and not keys.duplicated(['signal_date','ticker']).any()
        assert np.array_equal(selected.label_end_date.to_numpy(),keys.label_end_date.to_numpy())
        assert keys.signal_date.dt.year.eq(year).all() and keys.label_end_date.lt(f'{year+1}-01-01').all()
        assert selected.label_available.all() and selected.new_buy_eligible.all()
        with np.load(audit['matrix_path'],allow_pickle=False) as z:
            arrays[year]={k:z[k].copy() for k in z.files}
        assert arrays[year]['feature_order'].tolist()==e.META_FEATURES
        base=e.BaseBundle('early' if year==2024 else 'validation')
        full_features=arrays[year]['features'].reshape(15,len(keys),-1)
        full_target=arrays[year]['target'].reshape(15,len(keys))
        feature_error=target_error=0.
        feature_exact=target_exact=True
        for start in range(0,len(keys),500):
            block=selected.iloc[start:start+500]
            with threadpool_limits(limits=2),torch.no_grad():
                rebuilt=base.matrix(*expand_observable_state(block)).reshape(15,len(block),-1)
                _,target,_=counterfactual(block,robust_training=True)
            target=target.reshape(15,len(block))
            old=full_features[:,start:start+len(block)]
            old_target=full_target[:,start:start+len(block)]
            feature_error=max(feature_error,float(np.abs(old-rebuilt).max()))
            target_error=max(target_error,float(np.abs(old_target-target).max()))
            feature_exact &= np.array_equal(old,rebuilt)
            target_exact &= np.array_equal(old_target,target)
            assert np.allclose(old,rebuilt,atol=1e-12,rtol=1e-10)
            assert np.allclose(old_target,target,atol=1e-12,rtol=1e-10)
        oof_results.append(dict(year=year,base_stage=base.stage,stock_date_rows=len(keys),
            action_state_rows=len(keys)*15,days=keys.signal_date.nunique(),
            train_signal_min=str(keys.signal_date.min().date()),train_signal_max=str(keys.signal_date.max().date()),
            train_label_end_max=str(keys.label_end_date.max().date()),
            sample_keys_sha256=audit['sample_keys_sha256'],matrix_sha256=audit['matrix_sha256'],
            feature_content_sha256=array_sha(arrays[year]['features']),target_content_sha256=array_sha(arrays[year]['target']),
            full_oof_reconstruction_posthoc=True,feature_exact_equal=feature_exact,target_exact_equal=target_exact,
            feature_max_abs_error=feature_error,target_max_abs_error=target_error))
        for clock in base.predictor_clocks:
            clock_rows.append(dict(role=f'{year}_oof_predictor',**clock))
        print('FULL_OOF_RECONSTRUCTED',year,feature_error,target_error,flush=True)
    write('oof_full_reconstruction.json',oof_results)
    model_rows=[]
    for record in receipt['fits']:
        stage=record['stage']; artifact=Path(record['artifact'])
        model=joblib.load(artifact);scaler,regressor=model[0],model[-1]
        matrix=np.concatenate([arrays[y]['features'] for y in record['oof_years']])
        mean=matrix.mean(axis=0);var=matrix.var(axis=0)
        # Pure arithmetic moment check; no scaler.fit or regression fitting.
        assert int(scaler.n_samples_seen_)==len(matrix)
        comparisons={
            'mean_vs_receipt':delta(scaler.mean_,record['scaler_mean']),
            'scale_vs_receipt':delta(scaler.scale_,record['scaler_scale']),
            'coefficients_vs_receipt':delta(regressor.coef_,record['coefficients']),
            'intercept_vs_receipt':delta(regressor.intercept_,record['intercept']),
            'mean_vs_oof_population_moment':delta(scaler.mean_,mean),
            'variance_vs_oof_population_moment':delta(scaler.var_,var),
            'scale_vs_sqrt_oof_variance':delta(scaler.scale_,np.where(var>0,np.sqrt(var),1.))}
        assert all(x['allclose_atol_1e_12_rtol_1e_10'] for x in comparisons.values())
        row=dict(stage=stage,artifact=str(artifact),artifact_sha256=sha(artifact),
            receipt_sha256=record['artifact_sha256'],frozen_sha256=frozen['source_sha256'][str(artifact)],
            model_class=type(regressor).__name__,scaler_class=type(scaler).__name__,
            train_rows=record['train_rows'],actual_scaler_samples=int(scaler.n_samples_seen_),
            oof_years=record['oof_years'],train_signal_max=record['train_signal_max'],
            train_label_end_max=record['train_label_end_max'],cutoff_exclusive=record['cutoff_exclusive'],
            scaler_mean_sha256=array_sha(scaler.mean_),scaler_scale_sha256=array_sha(scaler.scale_),
            scaler_variance_sha256=array_sha(scaler.var_),coefficients_sha256=array_sha(regressor.coef_),
            intercept_sha256=array_sha(regressor.intercept_),comparisons=comparisons)
        assert row['artifact_sha256']==row['receipt_sha256']==row['frozen_sha256']
        model_rows.append(row)
    write('meta_internal_evidence.json',model_rows)
    pd.DataFrame([{k:v for k,v in row.items() if k!='comparisons'} for row in model_rows]).to_csv(
        HERE/'meta_stage_hash_mapping.csv',index=False,encoding='utf-8-sig')
    # Capture actual loads NOW. This is expressly not a backfilled historical runtime log.
    load_events=[]
    original_joblib=joblib.load;original_torch=torch.load;original_np=np.load
    load_stage={'value':None}
    def capture(fn,kind):
        def wrapped(path,*args,**kwargs):
            if isinstance(path,(str,Path)):
                load_events.append(dict(evidence_class='POSTHOC_ACTUAL_LOAD',stage=load_stage['value'],
                    loader=kind,path=str(Path(path)),sha256=sha(path)))
            return fn(path,*args,**kwargs)
        return wrapped
    joblib.load=capture(original_joblib,'joblib.load')
    torch.load=capture(original_torch,'torch.load')
    np.load=capture(original_np,'numpy.load')
    policies={}
    for stage in ('validation','final'):
        load_stage['value']=stage
        policies[stage]=e.StackedPolicy(stage)
        for clock in policies[stage].base.predictor_clocks:
            clock_rows.append(dict(role=f'{stage}_inference_predictor',**clock))
    joblib.load=original_joblib;torch.load=original_torch;np.load=original_np
    for event in load_events:
        event['frozen_sha256']=frozen['source_sha256'].get(event['path'])
        event['matches_frozen']=event['frozen_sha256']==event['sha256']
    assert all(x['matches_frozen'] for x in load_events)
    pd.DataFrame(load_events).to_csv(HERE/'posthoc_loaded_hashes.csv',index=False,encoding='utf-8-sig')
    write('predictor_clocks.json',clock_rows)
    raw=pd.read_parquet(folder/'raw_model_outputs.parquet').sort_values('signal_date')
    contexts=pd.read_parquet(folder/'signal_contexts.parquet').set_index('decision_id',verify_integrity=True)
    targets=pd.read_parquet(folder/'target_decisions.parquet')
    prices=pd.read_parquet(evaluate.PRICE).set_index(['trade_date','ticker'],verify_integrity=True)
    age={};daily=[];stock_rows=[]
    for number,row in enumerate(raw.itertuples(),1):
        ctx=contexts.loc[row.decision_id]
        if not row.policy_called: raise RuntimeError('UNEXPECTED_NONCALL_REQUIRES_REVIEW')
        current=json.loads(ctx.current_weights_json)
        age={t:age.get(t,0)+1 for t,w in current.items() if w>0}
        input_names=json.loads(row.decision_input_tickers_json)
        day=index.loc[pd.MultiIndex.from_arrays([[row.signal_date]*len(input_names),input_names])].reset_index()
        day=day.loc[day.new_buy_eligible.astype(bool)|day.ticker.map(current).fillna(0).gt(0)]
        day=day.sort_values('ticker',kind='stable').reset_index(drop=True)
        names=day.ticker.tolist()
        historical=json.loads(row.raw_model_outputs_json)
        saved_decisions=json.loads(row.model_decisions_json)
        assert set(names)==set(historical)==set(saved_decisions)
        current_array=np.array([current.get(t,0.) for t in names])
        age_array=np.array([age.get(t,0.) for t in names])
        old_scores=np.array([historical[t]['stacked_action_values'] for t in names])
        expected_weights=np.array([saved_decisions[t] for t in names])
        assert np.array_equal(expected_weights,np.array([historical[t]['chosen_weight'] for t in names]))
        scores={}
        for stage,policy in policies.items():
            with threadpool_limits(limits=2),torch.no_grad():
                scores[stage]=policy.score_actions(day,current_array,ctx.cash_weight,age_array)
        # Recover the original buy restriction from known signal-close availability.
        signal_closes=prices.close.reindex(pd.MultiIndex.from_arrays([[row.signal_date]*len(names),names])).to_numpy(float)
        eligible=day.new_buy_eligible.to_numpy(bool)&np.isfinite(signal_closes)&(signal_closes>0)
        allowed=eligible[:,None]|(v.ACTIONS[None,:]<=current_array[:,None]+1e-10)
        _,chosen=v.allocate_joint_scores(scores['validation'],names,max_names=int(ctx.available_slots),
            max_units=min(38,int(np.floor((ctx.available_weight+1e-12)/.025))),allowed=allowed)
        weights=v.ACTIONS[chosen]
        validation_delta=np.abs(scores['validation']-old_scores)
        final_delta=np.abs(scores['final']-old_scores)
        tt=targets.loc[targets.decision_id.eq(row.decision_id)&targets.explicit_model_decision].set_index('ticker')
        target_ledger_weights=tt.loc[names,'raw_model_weight'].to_numpy(float)
        daily.append(dict(signal_date=row.signal_date,decision_id=row.decision_id,stock_rows=len(names),action_values=len(names)*5,
            validation_score_max_abs_error=float(validation_delta.max()),
            validation_score_exact_cells=int((validation_delta==0).sum()),
            validation_score_matching_cells=int((validation_delta<=1e-12).sum()),
            validation_target_mismatches=int((np.abs(weights-expected_weights)>1e-12).sum()),
            raw_vs_target_ledger_mismatches=int((np.abs(expected_weights-target_ledger_weights)>1e-12).sum()),
            final_negative_control_max_abs_error=float(final_delta.max()),
            final_negative_control_matching_cells=int((final_delta<=1e-12).sum()),
            final_negative_control_distinct_cells=int((final_delta>1e-12).sum()),
            saved_exposure=float(expected_weights.sum()),reconstructed_validation_exposure=float(weights.sum()),
            context_cash_weight=float(ctx.cash_weight),max_reconstructed_age=int(age_array.max(initial=0))))
        for i,ticker in enumerate(names):
            item=dict(signal_date=row.signal_date,ticker=ticker,decision_id=row.decision_id,
                current_weight=current_array[i],cash_weight=float(ctx.cash_weight),reconstructed_age=int(age_array[i]),
                historical_target=expected_weights[i],validation_reconstructed_target=weights[i],
                target_ledger_raw_weight=target_ledger_weights[i])
            for j,action in enumerate(v.ACTIONS):
                item[f'historical_value_{j}']=old_scores[i,j]
                item[f'validation_value_{j}']=scores['validation'][i,j]
                item[f'final_technical_negative_control_value_{j}']=scores['final'][i,j]
            stock_rows.append(item)
        if number%31==0 or number==len(raw):
            print('FROZEN_CONTEXT_INFERENCE',number,len(raw),'validation_error',daily[-1]['validation_score_max_abs_error'],flush=True)
    daily=pd.DataFrame(daily)
    daily.to_csv(HERE/'daily_output_fingerprint_comparison.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(stock_rows).to_parquet(HERE/'all_stock_action_output_comparison.parquet',index=False)
    after={p:sha(p) for p in before}
    unchanged=before==after
    assert unchanged and guard['attempts']==0
    result=dict(status='PASS_POSTHOC_FULL_2025_RECONSTRUCTION',
        classification='2025 frozen validation stack; original outputs independently reproduced; runtime load not contemporaneously attested',
        original_records=dict(frozen_created_utc=frozen['created_utc'],frozen_manifest_items=len(frozen_rows),
            complete_receipt=read(folder.parent/'COMPLETE.json'),metadata_has_per_policy_load_hash=False,
            original_fit_receipt_calls=receipt['meta_fit_calls'],original_scaler_fit_calls=receipt['scaler_fit_calls']),
        posthoc_verification=dict(days=len(daily),stock_date_rows=int(daily.stock_rows.sum()),action_values=int(daily.action_values.sum()),
            validation_max_abs_error=float(daily.validation_score_max_abs_error.max()),
            validation_exact_cells=int(daily.validation_score_exact_cells.sum()),
            validation_matching_cells_atol_1e_12=int(daily.validation_score_matching_cells.sum()),
            validation_target_mismatches=int(daily.validation_target_mismatches.sum()),
            raw_vs_target_ledger_mismatches=int(daily.raw_vs_target_ledger_mismatches.sum()),
            final_negative_control_matching_cells_atol_1e_12=int(daily.final_negative_control_matching_cells.sum()),
            final_negative_control_distinct_cells=int(daily.final_negative_control_distinct_cells.sum()),
            final_negative_control_max_abs_error=float(daily.final_negative_control_max_abs_error.max()),
            final_negative_control_distinct_days=int(daily.final_negative_control_distinct_cells.gt(0).sum())),
        limits=['No original per-policy runtime stage/model/normalizer load receipt exists.',
            'Freeze manifest includes both stages and is not itself proof of which stage ran.',
            'Post-hoc deterministic equality is strong artifact-consistency evidence, not a timestamped execution attestation.',
            'Retrospective price-index NAV is not blind out-of-sample selection evidence or certified shareholder total return.',
            'Final-stage inference on 2025 consumes a model trained through 2025; only a technical negative control, no performance calculated.'],
        no_fit_attempts=guard['attempts'],original_input_hashes_unchanged=unchanged,
        no_2026_outcomes_loaded=True,no_portfolio_replay=True,no_original_files_modified=True,
        elapsed_seconds=time.monotonic()-started)
    assert result['posthoc_verification']['validation_matching_cells_atol_1e_12']==result['posthoc_verification']['action_values']
    assert result['posthoc_verification']['validation_target_mismatches']==0
    assert result['posthoc_verification']['raw_vs_target_ledger_mismatches']==0
    write('RESULT.json',result)
    print(json.dumps(clean(result),ensure_ascii=True),flush=True)


if __name__=='__main__':
    main()
