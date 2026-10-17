"""Exact child pre2026 calibration supplement; never train a native predictor.

Metadata proposal/preflight has no numerical decoder. Root must separately freeze
and independently review source-qualified two-key repair before any fit entry.
All native/scaler bytes and original failures stay retained at the parent/child.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import inspect
import io
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import consensus_predictors as predictors, consensus_fusion as fusion
from scripts.research.a2.evaluation import consensus_final_freeze as closure
from scripts.research.a2.data.joint_input_binding import guard_parquet

values=predictors.values
require=predictors.require
TASK=predictors.TASK
SCHEMA='CONSENSUS_SOURCE_CORRECTION_FINAL_CALIBRATION_SUPPLEMENT_R1'
FREEZE='CONSENSUS_FINAL_CALIBRATION_COMPLETION_FREEZE.json'
GATE='AUTHORIZED_PRE2026_CALIBRATION_ONLY'
PATCH_STATUS='SOURCE_QUALIFIED_TWO_ORIGINAL_MATURE_KEYS_ONLY_PENDING_CALIBRATION_FIT_AUTHORITY'
PATCH_RECEIPT_SHA='05ced496895f5ced9eb24eff4bbf992134dc6669b19a2aa33a5610535495e6e9'
PATCH_RELATIVE='derived/source_completion/BN_FINAL_CALIBRATION_LABEL_PATCH_R1.json'
ROOT='models/consensus_final_calibration_completion'
KEYS=('2025-10-07|BN','2025-10-08|BN')
PATCH_COLUMNS=('signal_date','ticker','cusip','execution_date','label_end_date','label_mature_date','label_coordinate',
    'old_y_open5','new_y_open5','old_quantity_multiplier','new_quantity_multiplier')
PATCH_CLOCKS=('signal_date','execution_date','label_end_date','label_mature_date')


class NotTestable(ValueError):pass


def ref(path):return closure._ref(path)


def source_pins():
    return dict(adapter=ref(__file__),predictor=ref(predictors.__file__),fusion=ref(fusion.__file__),
        value_owner=ref(values.__file__),metadata_closure_owner=ref(closure.__file__),
        native=ref(values.NATIVE),extension_owner=ref(values.EXTENSION_SOURCE))


def _secondary_owner_branch():
    """Compile the unchanged canonical inline bridge branch, not a copy of OLS."""
    tree=ast.parse(inspect.getsource(predictors.fit_one))
    matches=[n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.test,ast.Compare)
        and isinstance(n.test.left,ast.Name) and n.test.left.id=='horizon'
        and len(n.test.ops)==1 and isinstance(n.test.ops[0],ast.NotEq)
        and isinstance(n.test.comparators[0],ast.Constant) and n.test.comparators[0].value==5]
    require(len(matches)==1,'CANONICAL_SECONDARY_BRIDGE_BRANCH_REQUIRED')
    body=copy.deepcopy(matches[0].body)
    # The original owner assigns bridge and calibration and calls statistical.
    names={n.id for stmt in body for n in ast.walk(stmt) if isinstance(n,ast.Name)}
    require({'bridge','calibration','statistical','cal','fields'}<=names,'CANONICAL_SECONDARY_BRIDGE_SHAPE_CHANGED')
    fragment=ast.Module(body=body,type_ignores=[]);ast.fix_missing_locations(fragment)
    return compile(fragment,predictors.__file__,'exec'),values.digest(ast.dump(fragment,include_attributes=False))


def secondary_owner_calibration(owner,horizon,cal,fields,statistical):
    code,_=_secondary_owner_branch();scope=dict(owner=owner,horizon=horizon,cal=cal,fields=fields,statistical=statistical,np=np,require=require)
    exec(code,scope)
    return scope['calibration'],scope['bridge']


def _originals(run):
    facts=fusion._continuation_facts(run);parent=facts['parent'];refs=facts['scope']['parent_custody']
    models,oldf,_,_=closure._candidate_dispositions(parent,facts['spec'],facts['pf'],refs['predictor_freeze_ref'],facts['ff'],refs['fusion_freeze_ref'])
    require(models==facts['audit']['candidate_predictors'] and oldf==facts['audit']['candidate_fusions'],'ORIGINAL_DISPOSITION_CUSTODY_CHANGED')
    _,_,_,ff,_,ffref=fusion.contract(run,'core5',fusion.owner.NNLS_ZERO_ABSTAIN,2026)
    newf,_=closure._child_fusion_dispositions(run,ff,ffref,parent,facts['spec'])
    ps=[e for e in models if e['slot']['year']==2026 and e['status']=='TRAINED']
    fs=[e for e in oldf+newf if e['slot']['year']==2026 and e['slot']['packet_id']=='core5' and e['status']=='TRAINED']
    require(len(ps)==37 and len(fs)==14,'EXACT_SUCCESSFUL_FINAL_37_AND14_REQUIRED')
    excluded=[e for e in models if e['slot']['year']==2026 and e['status']!='TRAINED']
    require(len(excluded)==1 and excluded[0]['slot']['model_id']=='ebm','ORIGINAL_FINAL_EBM_FAILURE_MUST_REMAIN')
    return facts,ps,fs,excluded


def _patch_metadata(run):
    rr=dict(path=str(run/PATCH_RELATIVE),sha256=PATCH_RECEIPT_SHA);path=closure._pin(rr,run/PATCH_RELATIVE)
    value=closure._metadata(path)
    require(value['status']==PATCH_STATUS,'SOURCE_QUALIFIED_PATCH_RECEIPT_REQUIRED')
    closure._qualified_metadata_ref(rr,name='final_calibration_source',expected_patch=value['patch_ref'])
    require(Path(value['patch_ref']['path'])==run/'derived/source_completion/BN_FINAL_CALIBRATION_LABEL_PATCH_R1.parquet',
        'EXACT_DERIVED_LABEL_PATCH_PATH_REQUIRED')
    return rr,value


def _run(run):
    run=Path(run).resolve();require(run==fusion.CONTINUATION_RUN,'EXACT_CHILD_FINAL_CALIBRATION_RUN_REQUIRED')
    assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    require(not (run/'CONSENSUS_DOWNSTREAM.lock').exists(),'DOWNSTREAM_ACTIVE_NO_CALIBRATION')
    return run


def freeze_template(run=fusion.CONTINUATION_RUN):
    run=_run(run);facts,ps,fs,excluded=_originals(run);rr,patch=_patch_metadata(run);_,branch_sha=_secondary_owner_branch()
    return dict(schema=SCHEMA,status='PROPOSED',task_id=TASK,research_id=fusion.CONTINUATION_RESEARCH_ID,run=str(run),
        scientific_supplement_id='SOURCE_CORRECTION_FINAL_CALIBRATION_SUPPLEMENT',continuation_scope_ref=facts['scope_ref'],
        prior_fit_units=1098,parent_fit_log_ref=facts['scope']['parent_custody']['parent_fit_log_ref'],max_fit_units=10000,
        parent_predictor_freeze_ref=facts['scope']['parent_custody']['predictor_freeze_ref'],dependency_paths=facts['spec']['dependency_paths'],
        predictor_slots=[e['slot'] for e in ps],fusion_slots=[e['slot'] for e in fs],original_final_predictors=ps,original_final_fusions=fs,
        original_excluded_final_predictor_failures=excluded,source_pins=source_pins(),
        correction_sidecar_ref=patch['patch_ref'],source_qualification_ref=rr,independent_review_refs=[],
        native_training_refit_authorized=False,test_2026_read_authorized=False,fit_timeout_seconds=1800,seed=values.SEED,
        cutoff='2026-01-01 exclusive',calibration_sessions=60,secondary_bridge_owner_branch_sha256=branch_sha,
        canonical_inputs_overwrite=False,support_expansion=False,mu_shift_for_fusion=False,strict_PIT_certified=False,vintage='UNKNOWN_RETAINED')


def contract(run,*,authorized=True):
    run=_run(run);sp=run/FREEZE;s=closure._metadata(sp);fr=ref(sp)
    expected=freeze_template(run)
    require(s['status'] in ('PROPOSED',GATE) and s['schema']==SCHEMA,'FINAL_CALIBRATION_FREEZE_REQUIRED')
    expected['status']=s['status'];expected['independent_review_refs']=s['independent_review_refs']
    require(s==expected,'FINAL_CALIBRATION_FROZEN_PLAN_SOURCE_OR_RECIPE_CHANGED')
    if authorized:
        require(s['status']==GATE and bool(s['independent_review_refs']),'FINAL_CALIBRATION_INDEPENDENT_FIT_AUTHORITY_REQUIRED')
        for r in s['independent_review_refs']:closure._qualified_metadata_ref(r,name='calibration_supplement_independent_review')
    require(not (Path(s['parent_fit_log_ref']['path']).parent/'CONSENSUS_FIT.lock').exists(),'IMMUTABLE_PARENT_STILL_FITTING')
    return run,s,fr


def metadata_preflight(run=fusion.CONTINUATION_RUN):
    run,s,fr=contract(run,authorized=False)
    return dict(status='PASS_METADATA_ONLY_NO_FIT_AUTHORITY',freeze_ref=fr,predictor_slots=s['predictor_slots'],fusion_slots=s['fusion_slots'],
        source_qualification_ref=s['source_qualification_ref'],prior_fit_units=s['prior_fit_units'],max_fit_units=s['max_fit_units'],
        native_models_loaded=False,numeric_inputs_read=False,test_2026_read=False)


def read_patch(spec):
    r=spec['correction_sidecar_ref'];path=closure._pin(r)
    _,proof=guard_parquet(path,r['sha256'],list(PATCH_CLOCKS))
    require(proof['rows']==2 and proof['schema']==list(PATCH_COLUMNS),'EXACT_TWO_KEY_PATCH_PHYSICAL_SCHEMA_REQUIRED')
    predicates=[[('signal_date','==',pd.Timestamp(d)),('ticker','==','BN'),
        *[(c,'<',pd.Timestamp('2026-01-01')) for c in PATCH_CLOCKS]] for d in ('2025-10-07','2025-10-08')]
    patch=pq.read_table(path,columns=list(PATCH_COLUMNS),filters=predicates).to_pandas()
    require(len(patch)==2 and (pd.to_datetime(patch.signal_date).dt.strftime('%Y-%m-%d')+'|'+patch.ticker).tolist()==list(KEYS),
        'EXACT_TWO_ORIGINAL_CALIBRATION_KEYS_REQUIRED')
    require(patch.label_coordinate.eq(values.LABEL).all() and np.isfinite(patch[['old_y_open5','new_y_open5','old_quantity_multiplier','new_quantity_multiplier']].to_numpy(float)).all(),
        'QUALIFIED_PATCH_LABEL_COORDINATE_AND_FINITE_VALUES_REQUIRED')
    require(patch.old_quantity_multiplier.eq(1.4999925000374998).all() and patch.new_quantity_multiplier.eq(1.5).all(),
        'ONLY_OFFICIAL_BN_QUANTITY_CORRECTION_REQUIRED')
    corrected=(1+patch.old_y_open5.to_numpy(float))*1.5/patch.old_quantity_multiplier.to_numpy(float)-1
    require(np.allclose(corrected,patch.new_y_open5.to_numpy(float),rtol=0,atol=2e-15),'CANONICAL_SOURCE_BACKED_LABEL_REPAIR_FORMULA_CHANGED')
    for c in PATCH_CLOCKS:require(pd.to_datetime(patch[c]).lt('2026-01-01').all(),'PATCH_PHYSICAL_CLOCK_MUST_BE_PRE2026')
    require(pd.to_datetime(patch.label_mature_date).ge(pd.to_datetime(patch.label_end_date)).all()
        and pd.to_datetime(patch.execution_date).gt(pd.to_datetime(patch.signal_date)).all(), 'PATCH_LABEL_MATURITY_AND_EXECUTION_ORDER_REQUIRED')
    return patch


def apply_patch_to_calibration(cal,horizon,patch):
    require(horizon in (3,5,10,20) and not cal.duplicated(['signal_date','ticker']).any(),'EXACT_ORIGINAL_CALIBRATION_KEYS_REQUIRED')
    result=cal.copy(deep=True);index={(pd.Timestamp(row.signal_date),row.ticker):i for i,row in enumerate(cal.itertuples())}
    for row in patch.itertuples():
        key=(pd.Timestamp(row.signal_date),row.ticker);require(key in index,'PATCH_CANNOT_EXPAND_ORIGINAL_CALIBRATION_SUPPORT');i=index[key]
        require(np.isclose(float(cal.iloc[i].y_open5),row.old_y_open5,rtol=0,atol=2e-15),'PATCH_ORIGINAL_Y5_COORDINATE_CHANGED')
        result.iloc[i,result.columns.get_loc('y_open5')]=row.new_y_open5
        if horizon==5:
            require(np.isclose(float(cal.iloc[i].target),row.old_y_open5,rtol=0,atol=2e-15),'PATCH_ORIGINAL_PRIMARY_TARGET_CHANGED')
            result.iloc[i,result.columns.get_loc('target')]=row.new_y_open5
    expected=cal.copy(deep=True)
    columns=['y_open5']+(['target'] if horizon==5 else [])
    expected[columns]=result[columns]
    require(expected.equals(result) and len(result)==len(cal),'CALIBRATION_ONLY_PATCH_CANNOT_CHANGE_FEATURES_MASK_OR_OTHER_HORIZON_TARGET')
    return result


def _payload_hash(native):
    stream=io.BytesIO();joblib.dump(native,stream,compress=0,protocol=5);return hashlib.sha256(stream.getvalue()).hexdigest()


def _clear_runtime_cache(native):
    for name in ('_torch_model','_model'):
        if hasattr(native,name):setattr(native,name,None)


def slot_paths(run,kind,slot):
    name=slot['model_id']+'_'+str(slot['horizon'])+'d' if kind=='predictor' else slot['method']
    root=run/ROOT/kind/name
    return root,root/'receipt.json',root/'model.joblib',root/'calibration.parquet'


def _frames(reader,spec,original,horizon):
    pf=closure._metadata(closure._pin(spec['parent_predictor_freeze_ref']));predictors.reader_integrity(reader,pf)
    cache=getattr(reader,'_final_calibration_frames',{})
    if horizon not in cache:cache[horizon]=predictors.guarded_frames(reader,2026,horizon)
    reader._final_calibration_frames=cache;fold,train,cal=cache[horizon]
    reuse=original['reuse_tuple']
    require(predictors.frame_hash(train)==reuse['train_frame_sha256'] and predictors.frame_hash(cal)==reuse['calibration_frame_sha256'],
        'ORIGINAL_NATIVE_TRAIN_OR_CALIBRATION_FRAME_CHANGED')
    require([str(d) for d in fold['calibration_sessions']]==reuse['calibration_sessions'],'ORIGINAL60_SESSION_CALIBRATION_CHANGED')
    return fold,train,cal


def _packet(reader,original,slot):
    parent=fusion.reader_run(fusion.CONTINUATION_RUN);key=(tuple(fusion.member_key(m) for m in slot['members']),fusion.owner.state_required(slot['method']))
    cache=getattr(reader,'_final_calibration_packets',{})
    if key not in cache:cache[key]=fusion.training_packet(parent,slot,2026,reader)
    reader._final_calibration_packets=cache;packet=cache[key];fold,train,cal,_,_,_,_,pins=packet
    require(predictors.frame_hash(train)==original['reuse_tuple']['train_frame_sha256']
        and predictors.frame_hash(cal)==original['reuse_tuple']['calibration_frame_sha256']
        and pins==original['reuse_tuple']['past_publication_pins'],'ORIGINAL_COMPLETE_FUSION_PACKET_CHANGED')
    return packet


def _complete(run,kind,entry,spec,fr,reader,patch):
    slot=entry['slot'];root,rp,mp,cp=slot_paths(run,kind,slot)
    original=closure._metadata(closure._pin(entry['receipt']));closure._pin(entry['artifacts']['model'])
    require(original['status']=='TRAINED' and original['reuse_tuple_sha256']==values.digest(original['reuse_tuple']), 'ORIGINAL_SUCCESSFUL_MODEL_ONLY')
    if kind=='predictor':
        owner=predictors.ALIAS.get(slot['model_id'],slot['model_id']);fold,train,cal=_frames(reader,spec,original,slot['horizon'])
        cal=apply_patch_to_calibration(cal,slot['horizon'],patch)
    else:
        owner=slot['method'];fold,train,cal,x,cx,state,cstate,pins=_packet(reader,original,slot);cal=apply_patch_to_calibration(cal,5,patch)
    reuse=dict(copy.deepcopy(original['reuse_tuple']),freeze_ref=fr,source_pins=spec['source_pins'],
        original_freeze_ref=original['reuse_tuple']['freeze_ref'],completion_spec_ref=fr,correction_sidecar_ref=spec['correction_sidecar_ref'],
        calibration_frame_sha256=predictors.frame_hash(cal),research_id=fusion.CONTINUATION_RESEARCH_ID,prior_fit_units=1098)
    tuple_sha=values.digest(reuse)
    if rp.exists():
        old=closure._metadata(rp)
        require(old['reuse_tuple_sha256']==tuple_sha,'CALIBRATION_CHECKPOINT_IDENTITY_CHANGED')
        if old['status']!='CALIBRATION_COMPLETED':return old
        require(values.sha(mp)==old['model_sha256'] and values.sha(cp)==old['calibration_sha256'],'CALIBRATION_CHECKPOINT_BYTES_CHANGED')
        return old
    root.mkdir(parents=True,exist_ok=True)
    r=dict(status='IN_PROGRESS',kind=kind,slot=slot,task_id=TASK,research_id=fusion.CONTINUATION_RESEARCH_ID,
        source_pins=spec['source_pins'],completion_spec_ref=fr,correction_sidecar_ref=spec['correction_sidecar_ref'],
        original_fit_receipt_ref=entry['receipt'],original_model_ref=entry['artifacts']['model'],
        original_reuse_tuple_sha256=original['reuse_tuple_sha256'],reuse_tuple=reuse,reuse_tuple_sha256=tuple_sha,
        native_training_refitted=False,test_2026_content_read=False,fit_units=0,receipt_path=str(rp),
        model_id=original['model_id'],native_model_id=original.get('native_model_id'),year=2026,horizon=slot.get('horizon',5),packet_id=slot.get('packet_id'))
    write_json_atomic(rp,r);log=run/'FIT_LOG.jsonl';auth=dict(max_fit_units=10000,budget_bucket='consensus_final_calibration_completion')
    def statistical(component):
        values._component_start(log,auth,1098,owner,2026,component,tuple_sha);r['fit_units']+=1;write_json_atomic(rp,r)
    try:
        values._native(spec['dependency_paths'])
        fitted=joblib.load(entry['artifacts']['model']['path']);native=fitted.native;_clear_runtime_cache(native);before=_payload_hash(native)
        if kind=='predictor':
            require(isinstance(fitted,predictors.ConsensusPredictor),'ORIGINAL_NATIVE_PREDICTOR_BUNDLE_REQUIRED')
            if owner in ('logistic','svc'):
                require((cal.target>0).sum()>=2 and (cal.target<=0).sum()>=2,'CLASSIFICATION_CALIBRATION_TWO_PER_CLASS_REQUIRED')
            raw=predictors.raw_predict(native,owner,cal,reader);fields=values.raw_fields(owner,raw)
            if slot['horizon']!=5:calibration,bridge=secondary_owner_calibration(owner,slot['horizon'],cal,fields,statistical)
            else:
                bridge=None;isotonic=None
                if owner in values.RANK or owner=='svc':
                    scores=fields['rank_score'] if owner in values.RANK else fields['svc_margin']
                    isotonic=values._fit_job('isotonic',owner,scores,cal.target.to_numpy(float),None,None,
                        spec['dependency_paths'],list(predictors.FEATURES),None,
                        log=log,auth=auth,prior=1098,year=2026,tuple_sha=tuple_sha,receipt=r)
                elif owner=='logistic' or owner=='huber' or owner in values.QUANTILE:
                    statistical('HELDOUT_CLASS_AMPLITUDES' if owner=='logistic' else 'HELDOUT_MEAN_OFFSET')
                statistical('HELDOUT_RESIDUAL_SIGMA');calibration=values.heldout_calibration(owner,raw,cal.target.to_numpy(float),isotonic=isotonic)
            result=predictors.ConsensusPredictor(native,calibration,bridge,r);mean,sigma=result.mapped(raw)
            diagnostic=cal[['signal_date','ticker','target','y_open5']].copy()
            for name,array in fields.items():diagnostic[name]=array
            diagnostic['prediction_primary5d']=mean;diagnostic['value_sigma']=sigma
            r.update(calibration={k:v for k,v in calibration.items() if k!='isotonic'},bridge=bridge)
        else:
            require(isinstance(fitted,fusion.ConsensusFusion),'ORIGINAL_NATIVE_FUSION_BUNDLE_REQUIRED')
            raw=np.asarray(native.predict(cx,cstate),float)
            statistical('HELDOUT_RESIDUAL_SIGMA');sigma=values.heldout_calibration('ridge',raw,cal.y_open5.to_numpy(float))['sigma']
            result=fusion.ConsensusFusion(native,sigma,r,run);diagnostic=cal[['signal_date','ticker','target','y_open5']].copy()
            diagnostic['prediction_primary5d']=raw;diagnostic['value_sigma']=sigma;r['sigma']=sigma
            r['zero_abstention_certificate']=getattr(native,'zero_abstention_certificate',None)
        _clear_runtime_cache(native);after=_payload_hash(native)
        require(before==after,'NATIVE_ESTIMATOR_OR_SCALER_BYTES_CHANGED_DURING_CALIBRATION')
        r.update(status='CALIBRATION_COMPLETED',raw_native_payload_sha256_before=before,raw_native_payload_sha256_after=after,
            raw_estimator_and_scaler_reused_same_bytes=True)
        diagnostic['scope']='PAST_HELDOUT_FINAL_CALIBRATION_SOURCE_CORRECTION_NOT_OOF_OR_TEST'
        diagnostic.to_parquet(cp,index=False);joblib.dump(result,mp)
        r.update(model_sha256=values.sha(mp),calibration_sha256=values.sha(cp));write_json_atomic(rp,r)
        values._append(log,dict(event='FINAL_CALIBRATION_COMPLETE',kind=kind,model_id=owner,year=2026,fit_units=r['fit_units'],reuse_tuple_sha256=tuple_sha))
    except Exception as exc:
        r.update(status='FAILED_NO_RETRY',failure=dict(type=type(exc).__name__,message=str(exc)));write_json_atomic(rp,r)
        values._append(log,dict(event='FINAL_CALIBRATION_FAILED',kind=kind,model_id=owner,year=2026,fit_units=r['fit_units'],reuse_tuple_sha256=tuple_sha))
    return r


def fit_one(run,kind,model_id,horizon=5,reader=None):
    run,s,fr=contract(run)
    entries=s['original_final_predictors'] if kind=='predictor' else s['original_final_fusions'] if kind=='fusion' else []
    selected=([e for e in entries if e['slot']['model_id']==model_id and e['slot']['horizon']==horizon] if kind=='predictor'
        else [e for e in entries if e['slot']['method']==model_id])
    require(len(selected)==1,'UNPLANNED_FINAL_CALIBRATION_SLOT')
    parent=fusion.reader_run(run);reader=reader or predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    with predictors.fit_lock(run):return _complete(run,kind,selected[0],s,fr,reader,read_patch(s))


def run_all(run=fusion.CONTINUATION_RUN,reader=None):
    run,s,fr=contract(run);parent=fusion.reader_run(run);reader=reader or predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    with predictors.fit_lock(run):
        manifest=run/closure.FINAL_CALIBRATION_RELATIVE
        if manifest.exists():
            old=closure._metadata(manifest,summary=True,continuation=True)
            require(old['completion_spec_ref']==fr,'FINAL_CALIBRATION_EXISTING_MANIFEST_IDENTITY_CHANGED')
            if old['status']==closure.FINAL_CALIBRATION_STATUS:
                closure._final_calibration_completion(run,dict(final_calibration_completion_ref=ref(manifest)),
                    s['original_final_predictors'],s['original_final_fusions'],s['continuation_scope_ref'])
            else:
                # Failure is a retained terminal artifact, never an automatic retry.
                for key in ('predictor_completions','fusion_completions'):
                    for e in old[key]:
                        for ar in e['artifacts'].values():closure._pin(ar)
            return old
        patch=read_patch(s);rows=dict(predictor_completions=[],fusion_completions=[]);failures=[]
        for kind,entries,key in (('predictor',s['original_final_predictors'],'predictor_completions'),('fusion',s['original_final_fusions'],'fusion_completions')):
            for entry in entries:
                r=_complete(run,kind,entry,s,fr,reader,patch);root,rp,mp,cp=slot_paths(run,kind,entry['slot'])
                item=dict(slot=entry['slot'],status=r['status'],original_fit_receipt_ref=entry['receipt'],original_model_ref=entry['artifacts']['model'],
                    raw_estimator_and_scaler_reused_same_bytes=r.get('raw_estimator_and_scaler_reused_same_bytes',False),artifacts=dict(receipt=ref(rp)))
                if kind=='predictor':item['original_calibration_ref']=entry['artifacts']['calibration']
                if r['status']=='CALIBRATION_COMPLETED':item['artifacts'].update(model=ref(mp),calibration=ref(cp))
                else:failures.append(item)
                rows[key].append(item)
                print(json.dumps(dict(kind=kind,slot=entry['slot'],status=r['status']),sort_keys=True),flush=True)
        complete=dict(schema=closure.FINAL_CALIBRATION_SCHEMA,status=closure.FINAL_CALIBRATION_STATUS if not failures else 'NOT_COMPLETE_NO_TEST_USE',
            task_id=TASK,research_id=fusion.CONTINUATION_RESEARCH_ID,run=str(run),continuation_scope_ref=s['continuation_scope_ref'],
            native_training_refitted=False,original_support_preserved=True,test_2026_content_read=False,cutoff=s['cutoff'],
            completion_spec_ref=fr,correction_sidecar_ref=s['correction_sidecar_ref'],source_qualification_ref=s['source_qualification_ref'],
            independent_review_refs=s['independent_review_refs'],fit_log_snapshot_ref=ref(run/'FIT_LOG.jsonl'),
            original_excluded_final_predictor_failures=s['original_excluded_final_predictor_failures'],**rows)
        path=run/closure.FINAL_CALIBRATION_RELATIVE
        if path.exists():require(closure._metadata(path,summary=True,continuation=True)==complete,'FINAL_CALIBRATION_MANIFEST_CANNOT_OVERWRITE')
        else:write_json_atomic(path,complete)
        return complete



def frozen_predictor_values(fitted,frame,reader):
    """Pure frozen transform on caller-qualified input; grants no data authority.

    The inherited predict_frame entry is intentionally unavailable for these
    finalcutoff bundles. Caller authenticates system/model/input custody first.
    """
    r=fitted.receipt
    require(isinstance(fitted,predictors.ConsensusPredictor) and r['status']=='CALIBRATION_COMPLETED'
        and r['kind']=='predictor' and r['native_training_refitted'] is False,'COMPLETED_FROZEN_PREDICTOR_REQUIRED')
    raw=predictors.raw_predict(fitted.native,r['native_model_id'],frame,reader);mean,sigma=fitted.mapped(raw)
    require(len(mean)==len(sigma)==len(frame) and np.isfinite(mean).all() and np.isfinite(sigma).all()
        and np.all(sigma>0),'FINITE_FROZEN_PREDICTOR_VALUES_REQUIRED')
    return mean,sigma


def frozen_fusion_values(fitted,x,state):
    """Pure native frozen fusion and stored sigma; no fit or packet construction."""
    r=fitted.receipt;x=np.asarray(x,float);state=np.asarray(state,float)
    require(isinstance(fitted,fusion.ConsensusFusion) and r['status']=='CALIBRATION_COMPLETED'
        and r['kind']=='fusion' and r['native_training_refitted'] is False,'COMPLETED_FROZEN_FUSION_REQUIRED')
    require(x.ndim==state.ndim==2 and len(x)==len(state) and x.shape[1]==len(r['slot']['members'])
        and np.isfinite(x).all() and np.isfinite(state).all(),'COMPLETE_FROZEN_FUSION_INPUT_REQUIRED')
    mean=np.asarray(fitted.native.predict(x,state),float);sigma=np.full(len(mean),fitted.sigma)
    require(mean.ndim==1 and len(mean)==len(x) and np.isfinite(mean).all() and np.isfinite(sigma).all()
        and np.all(sigma>0),'FINITE_FROZEN_FUSION_VALUES_REQUIRED')
    return mean,sigma


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--run',default=str(fusion.CONTINUATION_RUN));mode=p.add_mutually_exclusive_group()
    mode.add_argument('--template',action='store_true');mode.add_argument('--metadata-preflight',action='store_true');args=p.parse_args(argv)
    result=freeze_template(args.run) if args.template else metadata_preflight(args.run) if args.metadata_preflight else run_all(args.run)
    print(json.dumps(result if args.template else dict(status=result['status'],test_gate='CLOSED'),ensure_ascii=False))


if __name__=='__main__':main()
