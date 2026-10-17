"""Exact six-slot EBM engineering retry; no fit occurs on import/template/preflight.

The frozen stateful worker/job remains the sole estimator owner. In an isolated
named-main launcher its context is wrapped only to await clean post-RESULT exit
inside the original deadline. Original failures and completed calibrations stay
immutable. New artifacts are excluded from the primary core5 account selection.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.machinery
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
import uuid
from contextlib import contextmanager

import joblib
import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import consensus_predictors as predictors
from scripts.research.a2.training import consensus_fusion as fusion
from scripts.research.a2.training import consensus_final_calibration_completion as finalcal
from scripts.research.a2.training import stateful_values as values

TASK=predictors.TASK
RUN=fusion.CONTINUATION_RUN
SCHEMA='CONSENSUS_EBM_TEARDOWN_RETRY_FREEZE_R1'
FREEZE='CONSENSUS_EBM_TEARDOWN_RETRY_FREEZE.json'
GATE='AUTHORIZED_PRE2026_EBM_TEARDOWN_RETRY_ONLY'
ROOT='models/consensus_ebm_engineering_retry/ebm/5d'
BASE_SHA='06bf47667c4c04f1cff6fa09cd490b14812aab33672a74e58b55f2dcd01ab7de'
BASE_RELATIVE='ebm_teardown/EBM_RESULT_TEARDOWN_RETRY_AUTHORITY_PROPOSED_R1.json'
SLOTS=[dict(model_id='ebm',year=y,horizon=5) for y in range(2021,2027)]
AUTHORITY_FIELDS=('independent_review_ref','scientific_retry_authority_ref','registry_attempt_binding_ref','child_fit_log_prefix')
PACKAGES={'interpret':'interpret_core','numpy':'numpy','pandas':'pandas','sklearn':'scikit_learn',
          'scipy':'scipy','joblib':'joblib','threadpoolctl':'threadpoolctl','pyarrow':'pyarrow'}
_DEPENDENCY_CACHE={}
require=predictors.require


def ref(path):
    path=Path(path).resolve()
    return dict(path=str(path),sha256=values.sha(path))


def metadata(path):
    path=Path(path);require(path.stat().st_size<=65536,'BOUNDED_RETRY_METADATA_REQUIRED')
    value=json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(value,dict),'METADATA_OBJECT_REQUIRED');return value


def pin(r,expected=None):
    require(isinstance(r,dict) and isinstance(r.get('path'),str) and isinstance(r.get('sha256'),str),'EXACT_REF_REQUIRED')
    p=Path(r['path']);require(p.is_absolute() and str(p.resolve())==str(p),'CANONICAL_ABSOLUTE_REF_REQUIRED')
    if expected is not None:require(p==Path(expected).resolve(),'EXACT_REF_ROLE_PATH_REQUIRED')
    require(values.sha(p)==r['sha256'],'SOURCE_OR_ARTIFACT_SHA_CHANGED');return p


def _run(run):
    run=Path(run).resolve();require(run==RUN,'EXACT_EBM_CHILD_RUN_REQUIRED')
    assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO));return run


def _base(run):
    p=resolve(predictors.REPO).results_root/'_maintenance'/TASK/BASE_RELATIVE
    br=dict(path=str(p),sha256=BASE_SHA);b=metadata(pin(br))
    require(b['schema']=='CONSENSUS_EBM_POST_RESULT_ENGINEERING_RETRY_AUTHORITY_R1'
        and b['status']=='PROPOSED_NO_FIT_OR_PREDICTION_AUTHORITY' and Path(b['run'])==run
        and b['research_id']==fusion.CONTINUATION_RESEARCH_ID,'FIXED_PROPOSED_BASE_REQUIRED')
    require([{k:e[k] for k in ('model_id','year','horizon')} for e in b['ordered_retry_slots']]==SLOTS,'EXACT_SIX_EBM_SLOTS_REQUIRED')
    scope=metadata(pin(b['continuation_scope_ref'],run/'CONTINUATION_SCOPE.json'))
    require(scope['parent_custody']['prior_fit_units']==1098 if 'prior_fit_units' in scope['parent_custody']
        else b['fit_budget']['inherited_parent_fit_units']==1098,'INHERITED_BUDGET_CHANGED')
    for r in b['source_owner_refs'].values():pin(r)
    pin(b['engineering_evidence_ref']);sp=metadata(pin(b['authorized_original_spec_ref']))
    pf=metadata(pin(b['parent_predictor_freeze_ref']))
    require(pf['source_pins']==predictors.source_pins(),'ORIGINAL_PREDICTOR_OWNERS_CHANGED')
    require(pf['authorized_spec']=={k:b['authorized_original_spec_ref'][k] for k in ('path','sha256')},'ORIGINAL_SPEC_CHANGED')
    plan=sp['training_plan']
    require(plan['seed']==values.SEED==20260928 and plan['physical_fit_timeout_seconds']==values.FIT_TIMEOUT==1800
        and plan['calibration_sessions']==60 and plan['sample_cap'] is None and plan['weights']=='UNIFORM_LEGAL_ROWS','ORIGINAL_RECIPE_CHANGED')
    for entry in b['ordered_retry_slots']:
        r=metadata(pin(entry['original_failed_receipt_ref']));t=r['reuse_tuple']
        require(r['status']=='FAILED' and r['fit_units']==1 and r['failure']['message']=='FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT',
            'ORIGINAL_FAILED_DISPOSITION_CHANGED')
        require(r['model_id']==t['model_id']=='ebm' and r['year']==t['year']==entry['year'] and r['horizon']==t['horizon']==5,
            'ORIGINAL_SLOT_CHANGED')
        require(values.digest(t)==r['reuse_tuple_sha256']==entry['original_reuse_tuple_sha256'],'ORIGINAL_REUSE_TUPLE_CHANGED')
        require(t['source_pins']==pf['source_pins'] and t['freeze_ref']=={k:b['parent_predictor_freeze_ref'][k] for k in ('path','sha256')}
            and t['authorized_spec']==pf['authorized_spec'],'ORIGINAL_SOURCE_OR_FREEZE_TUPLE_CHANGED')
        require(t['train_frame_sha256']==entry['original_train_frame_sha256']
            and t['calibration_frame_sha256']==entry['original_calibration_frame_sha256']
            and t['seed']==values.SEED and t['bridge']=='NONE','ORIGINAL_FRAME_OR_RECIPE_CHANGED')
    return br,b,scope,sp,pf


def source_pins():
    return dict(adapter=ref(Path(__file__)),predictor_owners=predictors.source_pins(),
        final_calibration_patch_owner=ref(Path(finalcal.__file__)),native_common=ref(values.NATIVE.with_name('common.py')),
        metadata_closure_owner=ref(finalcal.closure.__file__),continuation_constants_owner=ref(fusion.__file__),
        physical_clock_guard_owner=ref(sys.modules[finalcal.guard_parquet.__module__].__file__))


def dependency_binding(dependencies):
    """Opaque code/native hashes only; wheel RECORD supplies a bounded file list."""
    env=resolve(predictors.REPO).envs_root.resolve();search=list(sys.path)+[str(p) for p in dependencies]
    for folder in dependencies:require(Path(folder).resolve().is_relative_to(env) and Path(folder).is_dir(),'QUALIFIED_DEPENDENCY_PATH_REQUIRED')
    result={}
    for name,distribution in PACKAGES.items():
        loaded=sys.modules.get(name);origin=getattr(loaded,'__file__',None)
        if origin is None:
            found=importlib.machinery.PathFinder.find_spec(name,search)
            require(found is not None and found.origin is not None,'MISSING_FIXED_DEPENDENCY:'+name);origin=found.origin
        origin=Path(origin).resolve();site=origin.parent if name=='threadpoolctl' else origin.parent.parent
        require(origin.is_relative_to(env),'DEPENDENCY_OUTSIDE_ENVS_ROOT:'+name)
        records=list(site.glob(distribution+'-*.dist-info/RECORD'))
        require(len(records)==1,'UNIQUE_WHEEL_RECORD_REQUIRED:'+name);record=records[0].resolve()
        require(record.stat().st_size<=4_000_000,'BOUNDED_WHEEL_RECORD_REQUIRED')
        names=list(csv.reader(record.read_text(encoding='utf-8').splitlines()))
        require(len(names)<=20000,'BOUNDED_PACKAGE_INVENTORY_REQUIRED')
        files=[]
        for row in names:
            p=(site/row[0]).resolve()
            if p.suffix.lower() in ('.py','.pyi','.pyd','.dll','.so','.exe') or p.name in ('RECORD','METADATA','WHEEL'):
                require(p.is_relative_to(env) and p.is_file(),'DEPENDENCY_CODE_MISSING_OR_OUTSIDE_ENV')
                st=p.stat();files.append((str(p),st.st_size,st.st_mtime_ns))
        require(files and any(p==str(origin) for p,_,_ in files),'DEPENDENCY_ORIGIN_NOT_IN_CODE_INVENTORY')
        files.sort();signature=values.digest(files)
        key=(name,signature)
        if key not in _DEPENDENCY_CACHE:
            _DEPENDENCY_CACHE[key]=values.digest([(p,size,values.sha(p)) for p,size,_ in files])
        result[name]=dict(origin=str(origin),wheel_record=ref(record),code_files=len(files),
            code_bytes=sum(size for _,size,_ in files),code_sha256=_DEPENDENCY_CACHE[key],
            hash_scope='WHEEL_LISTED_PYTHON_NATIVE_CODE_AND_WHEEL_METADATA_NO_DATA_DECODE')
    result['interpreter']=dict(executable=ref(sys.executable),version=sys.version)
    return result


def freeze_template(run=RUN):
    run=_run(run);br,b,scope,sp,pf=_base(run);rr,patch=finalcal._patch_metadata(run)
    parent_log=scope['parent_custody']['parent_fit_log_ref'];pin(parent_log)
    return dict(schema=SCHEMA,status='PROPOSED',task_id=TASK,research_id=fusion.CONTINUATION_RESEARCH_ID,run=str(run),
        attempt_id=b['attempt_id'],base_authority_ref=br,ordered_slots=SLOTS,source_pins=source_pins(),
        dependency_paths=sp['dependency_paths'],dependency_code_binding=dependency_binding(sp['dependency_paths']),
        original_failed_receipt_refs=[e['original_failed_receipt_ref'] for e in b['ordered_retry_slots']],
        continuation_scope_ref=b['continuation_scope_ref'],parent_predictor_freeze_ref=b['parent_predictor_freeze_ref'],
        parent_fit_log_ref=parent_log,prior_fit_units=1098,max_fit_units=10000,
        max_new_physical_attempts_per_slot=2,max_new_bucket_fit_units=24,artifact_save_attempts=3,
        physical_fit_timeout_seconds=1800,post_result_wait='REMAINING_ORIGINAL_DEADLINE_ONLY',seed=values.SEED,
        calibration_sessions=60,features=list(predictors.FEATURES),horizon=5,
        source_qualification_ref=rr,correction_sidecar_ref=patch['patch_ref'],final_calibration_only_patch=True,
        old_37_plus_14_unchanged=True,canonical_inputs_overwrite=False,support_expansion=False,
        primary_core5_selection_includes_retry_ebm=False,wide_32_fusion_authorized=False,
        test_2026_read_authorized=False,real_2026_prediction_publication_allowed=False,
        independent_review_ref=None,scientific_retry_authority_ref=None,registry_attempt_binding_ref=None,child_fit_log_prefix=None)


def authority_binding(spec):
    return dict(attempt_id=spec['attempt_id'],task_id=TASK,research_id=spec['research_id'],
        recipe_sha256=values.digest({k:v for k,v in spec.items() if k not in (*AUTHORITY_FIELDS[:-1],'status')}),
        source_pins=spec['source_pins'],test_2026_read_authorized=False)


def check_prefix(run,r):
    require(isinstance(r,dict) and Path(r['path'])==run/'FIT_LOG.jsonl' and isinstance(r.get('bytes'),int)
        and 0<r['bytes']<=64_000_000,'EXACT_BOUNDED_CHILD_FIT_LOG_PREFIX_REQUIRED')
    p=Path(r['path']);require(p.stat().st_size>=r['bytes'],'FIT_LOG_PREFIX_TRUNCATED')
    h=hashlib.sha256();last=b'';remaining=r['bytes']
    with p.open('rb') as stream:
        while remaining:
            chunk=stream.read(min(1<<20,remaining));require(bool(chunk),'FIT_LOG_PREFIX_TRUNCATED');h.update(chunk);last=chunk[-1:];remaining-=len(chunk)
    require(last==b'\n' and h.hexdigest()==r['sha256'],'ORIGINAL_CHILD_FIT_LOG_PREFIX_CHANGED')


def contract(run=RUN,*,authorized=True):
    run=_run(run);p=run/FREEZE;s=metadata(p);expected=freeze_template(run)
    require(s['status'] in ('PROPOSED',GATE),'RETRY_FREEZE_STATUS_REQUIRED')
    expected['status']=s['status']
    for field in AUTHORITY_FIELDS:expected[field]=s[field]
    require(s==expected,'RETRY_FROZEN_PLAN_SOURCE_OR_RECIPE_CHANGED')
    if authorized:
        require(s['status']==GATE,'SEPARATE_EBM_RETRY_FIT_AUTHORITY_REQUIRED');binding=authority_binding(s)
        checks=(('independent_review_ref','CONSENSUS_EBM_TEARDOWN_RETRY_INDEPENDENT_REVIEW_R1',('PASS_WITH_SCOPE_LIMITS','PASS')),
            ('scientific_retry_authority_ref','CONSENSUS_EBM_TEARDOWN_RETRY_SCIENTIFIC_AUTHORITY_R1',(GATE,)),
            ('registry_attempt_binding_ref','CONSENSUS_EBM_TEARDOWN_RETRY_REGISTRY_BINDING_R1',('APPLIED','ACCEPTED')))
        for field,schema,statuses in checks:
            a=metadata(pin(s[field]));require(a.get('schema')==schema and a.get('status') in statuses
                and a.get('binding')==binding,'EXACT_INDEPENDENT_REVIEW_SCIENTIFIC_AND_REGISTRY_BINDING_REQUIRED:'+field)
            if field=='independent_review_ref':require(a.get('reviewer_id') not in (None,'','consensus_pool','/root/consensus_pool'),'INDEPENDENT_REVIEWER_REQUIRED')
            if field=='scientific_retry_authority_ref':require(a.get('final_BN_two_key_calibration_authorized') is True
                and a.get('source_qualification_ref')==s['source_qualification_ref']
                and a.get('correction_sidecar_ref')==s['correction_sidecar_ref'],'EXACT_FINAL_EBM_PATCH_AUTHORITY_REQUIRED')
        check_prefix(run,s['child_fit_log_prefix'])
        require(not (Path(s['parent_fit_log_ref']['path']).parent/'CONSENSUS_FIT.lock').exists(),'IMMUTABLE_PARENT_STILL_FITTING')
    return run,s,ref(p)


def metadata_preflight(run=RUN):
    run,s,fr=contract(run,authorized=False)
    return dict(status='PASS_METADATA_ONLY_NO_FIT_AUTHORITY',freeze_ref=fr,binding=authority_binding(s),
        slots=s['ordered_slots'],prior_fit_units=1098,max_fit_units=10000,real_fits_started=0,
        native_models_loaded=False,numeric_inputs_read=False,test_2026_read=False)


class _ParentConnection:
    def __init__(self,connection,state):self.connection=connection;self.state=state
    def __getattr__(self,name):return getattr(self.connection,name)
    def recv(self):
        message=self.connection.recv();self.state['last_message']=message[0]
        if message[0]=='RESULT':self.state['result_received']=True;self.state['result_monotonic']=time.monotonic()
        return message
    def send(self,value):
        if value is True and self.state.get('last_message')=='FIT_START':
            caller=inspect.currentframe().f_back
            require(caller.f_code is values._fit_job.__code__ and isinstance(caller.f_locals.get('deadline'),float),
                'FROZEN_OWNER_ACK_DEADLINE_REQUIRED')
            self.state['deadline']=caller.f_locals['deadline'];self.state['ack_count']+=1
        return self.connection.send(value)


class _Process:
    def __init__(self,process,state,telemetry):self.process=process;self.state=state;self.telemetry=telemetry;self.joined_result=False
    def __getattr__(self,name):return getattr(self.process,name)
    def start(self):
        result=self.process.start();self.state['deadline']=time.monotonic()+self.state['timeout'];return result
    def join(self,timeout=None):
        if not self.state['result_received'] or self.joined_result:return self.process.join(timeout)
        self.joined_result=True;start=time.monotonic();remaining=max(0.,self.state['deadline']-start)
        self.process.join(min(float(timeout or 0),remaining))
        initial_alive=self.process.is_alive();initial_exit=self.process.exitcode
        if initial_alive:
            self.process.join(max(0.,self.state['deadline']-time.monotonic()))
        end=time.monotonic();expired=end>=self.state['deadline']
        self.telemetry(dict(result_received=True,fit_start_ack_count=self.state['ack_count'],
            result_to_join_seconds=start-self.state['result_monotonic'],initial_join_alive=initial_alive,
            initial_join_exitcode=initial_exit,post_result_join_seconds=end-start,
            deadline_remaining_seconds=max(0.,self.state['deadline']-end),
            final_alive=self.process.is_alive(),final_exitcode=self.process.exitcode,
            clean_exit=self.process.exitcode==0 and not self.process.is_alive(),deadline_reset_after_result=False,deadline_exceeded=expired))
        if expired:
            raise TimeoutError('PHYSICAL_FIT_1800_SECONDS_EXCEEDED_DURING_RESULT_TEARDOWN')


class _Context:
    def __init__(self,base,timeout,telemetry):
        self.base=base;self.telemetry=telemetry;self.state=dict(timeout=timeout,deadline=None,result_received=False,ack_count=0)
    def Pipe(self,*args,**kwargs):
        parent,child=self.base.Pipe(*args,**kwargs);return _ParentConnection(parent,self.state),child
    def Process(self,*args,**kwargs):return _Process(self.base.Process(*args,**kwargs),self.state,self.telemetry)


@contextmanager
def post_result_context(telemetry):
    """Process-local wrapper; production CLI is isolated and holds the shared lock."""
    original=values.mp.get_context
    def get_context(method=None):
        require(method=='spawn','ORIGINAL_SPAWN_CONTEXT_REQUIRED')
        return _Context(original(method),values.FIT_TIMEOUT,telemetry)
    values.mp.get_context=get_context
    try:yield
    finally:values.mp.get_context=original


def engineering_failure(exc):
    # Never retry worker ERROR/numerical/convergence/budget/source/time-limit failures.
    if isinstance(exc,TimeoutError):return False
    if isinstance(exc,(EOFError,BrokenPipeError,ConnectionResetError,ModuleNotFoundError,ImportError,OSError)):return True
    if isinstance(exc,RuntimeError) and any(str(exc).startswith('FIT_WORKER_FAILED:'+kind+':') for kind in
        ('OSError','PermissionError','ModuleNotFoundError','ImportError','BrokenPipeError','ConnectionResetError')):return True
    return isinstance(exc,RuntimeError) and (str(exc)=='FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'
        or str(exc).startswith('FIT_WORKER_EXITED_WITHOUT_RESULT:'))


def _save(operation,attempts):
    for i in range(attempts):
        try:return operation()
        except OSError:
            if i+1==attempts:raise
            time.sleep(min(2**i,4))


def _dump(fitted,path,attempts):
    require(not path.exists(),'IMMUTABLE_ARTIFACT_ALREADY_EXISTS')
    def write():
        temporary=path.with_name(path.name+'.partial_'+uuid.uuid4().hex)
        joblib.dump(fitted,temporary);os.replace(temporary,path)
    _save(write,attempts);return ref(path)


def _frames(reader,s,b,year):
    pf=metadata(pin(s['parent_predictor_freeze_ref']));predictors.reader_integrity(reader,pf)
    fold,train,cal=predictors.guarded_frames(reader,year,5)
    original=metadata(pin(b['ordered_retry_slots'][year-2021]['original_failed_receipt_ref']));t=original['reuse_tuple']
    require(predictors.frame_hash(train)==t['train_frame_sha256'] and predictors.frame_hash(cal)==t['calibration_frame_sha256'],
        'ORIGINAL_FULL_TRAIN_OR_CAL_FRAME_CHANGED')
    require(str(fold['calibration_start'])==t['train_maturity_exclusive'] and str(fold['cutoff_exclusive'])==t['calibration_maturity_exclusive']
        and [str(x) for x in fold['calibration_sessions']]==t['calibration_sessions'],'ORIGINAL_FOLD_CLOCKS_CHANGED')
    require(values.feature_binding()==t['feature_binding'] and tuple(s['features'])==predictors.FEATURES,'ORIGINAL_FEATURE_BINDING_CHANGED')
    corrected=finalcal.apply_patch_to_calibration(cal,5,finalcal.read_patch(s)) if year==2026 else cal
    return fold,train,corrected,original,predictors.frame_hash(cal)


def _completed(r,root,reuse,reader):
    require(r['reuse_tuple']==reuse and r['reuse_tuple_sha256']==values.digest(reuse),'CHECKPOINT_FULL_IDENTITY_CHANGED')
    for name,path in (('model_ref',root/'model.joblib'),('calibration_ref',root/'calibration.parquet')):pin(r[name],path)
    values._native(reuse['dependency_paths']);fitted=joblib.load(root/'model.joblib');fitted.receipt=r;return fitted


def fit_one(run,year,reader=None):
    run,s,fr=contract(run);require(year in range(2021,2027),'EXACT_SIX_PRE2026_FIT_CUTOFFS_REQUIRED')
    with predictors.fit_lock(run):
        # No payload or model decode before authority, lock and original source proof.
        _,b,scope,sp,pf=_base(run);parent=Path(s['parent_predictor_freeze_ref']['path']).parent
        require(values.sha(parent/'derived/PHYSICAL_SOURCE_BINDING.json')==pf['input_binding_sha256']
            and values.sha(parent/'derived/consensus100_daily.parquet')==pf['membership_sha256'],'ORIGINAL_PARENT_DERIVED_BYTES_CHANGED')
        reader=reader or predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
        fold,train,cal,old,original_cal_sha=_frames(reader,s,b,year)
        reuse=dict(freeze_ref=fr,source_pins=s['source_pins'],dependency_code_binding=s['dependency_code_binding'],
            dependency_paths=s['dependency_paths'],original_failed_receipt_ref=b['ordered_retry_slots'][year-2021]['original_failed_receipt_ref'],
            original_reuse_tuple_sha256=old['reuse_tuple_sha256'],year=year,horizon=5,seed=values.SEED,
            train_frame_sha256=predictors.frame_hash(train),original_calibration_frame_sha256=original_cal_sha,
            effective_calibration_frame_sha256=predictors.frame_hash(cal),source_qualification_ref=s['source_qualification_ref'] if year==2026 else None)
        tuple_sha=values.digest(reuse);history=[];native_reuse=None
        for number in range(2,2+s['max_new_physical_attempts_per_slot']):
            root=run/ROOT/str(year)/f'attempt{number}';rp=root/'receipt.json'
            if root.exists():
                require(rp.exists(),'UNRECEIPTED_ATTEMPT_PRESERVED_REQUIRES_RECOVERY_EVIDENCE');r=metadata(rp)
                require(r['reuse_tuple']==reuse and r['reuse_tuple_sha256']==tuple_sha,'EXISTING_ATTEMPT_IDENTITY_CHANGED')
                history.append(ref(rp))
                if r['status']=='TRAINED':return _completed(r,root,reuse,reader)
                if r['status']=='FAILED_SCIENTIFIC_NO_RETRY':return r
                require(r['status'] in ('FAILED_ENGINEERING','IN_PROGRESS'),'ATTEMPT_DISPOSITION_REQUIRED')
                if r.get('native_checkpoint_ref') is not None:pin(r['native_checkpoint_ref'],root/'native_checkpoint.joblib');native_reuse=r['native_checkpoint_ref']
                continue
            root.mkdir(parents=True);r=dict(status='IN_PROGRESS',phase='NATIVE',model_id='ebm',native_model_id='ebm',year=year,horizon=5,
                receipt_path=str(rp),fit_units=0,reuse_tuple=reuse,reuse_tuple_sha256=tuple_sha,source_pins=predictors.source_pins(),
                retry_source_pins=s['source_pins'],previous_attempt_refs=history.copy(),parent_failure_preserved=True,
                test_2026_rows_read=0,primary_core5_selection_includes_retry_ebm=False,post_result_telemetry=[])
            _save(lambda:write_json_atomic(rp,r),s['artifact_save_attempts']);log=run/'FIT_LOG.jsonl';auth=dict(max_fit_units=10000,budget_bucket='consensus_ebm_teardown_retry',
                max_new_bucket_fit_units=s['max_new_bucket_fit_units'])
            def save_receipt():return _save(lambda:write_json_atomic(rp,r),s['artifact_save_attempts'])
            def telemetry(event):r['post_result_telemetry'].append(event);save_receipt()
            try:
                native=values._native(s['dependency_paths'])
                if native_reuse is None:
                    bundle=native.NativeBundle('ebm',list(predictors.FEATURES))
                    require(bundle.scaler is None and 'ebm' not in values.SCALED,'ORIGINAL_EBM_NO_SCALER_REQUIRED')
                    with post_result_context(telemetry):
                        bundle.estimator_object=values._fit_job('predictor','ebm',train[list(predictors.FEATURES)].to_numpy(float),
                            train.target.to_numpy(float),train.signal_date,None,s['dependency_paths'],list(predictors.FEATURES),None,
                            log=log,auth=auth,prior=1098,year=year,tuple_sha=tuple_sha,receipt=r)
                    r['native_checkpoint_ref']=_dump(bundle,root/'native_checkpoint.joblib',s['artifact_save_attempts']);save_receipt()
                else:
                    pin(native_reuse);bundle=joblib.load(native_reuse['path']);r['native_model_reused_ref']=native_reuse
                r['phase']='CALIBRATION';save_receipt();raw=predictors.raw_predict(bundle,'ebm',cal,reader)
                values._component_start(log,auth,1098,'ebm',year,'HELDOUT_RESIDUAL_SIGMA',tuple_sha);r['fit_units']+=1;save_receipt()
                calibration=values.heldout_calibration('ebm',raw,cal.target.to_numpy(float))
                fitted=predictors.ConsensusPredictor(bundle,calibration,None,r);mean,sigma=fitted.mapped(raw)
                require(np.isfinite(mean).all() and np.isfinite(sigma).all() and (sigma>0).all(),'INVALID_NATIVE_CALIBRATED_FORECAST')
                diagnostic=cal[['signal_date','ticker','target','y_open5']].copy()
                for name,array in values.raw_fields('ebm',raw).items():diagnostic[name]=array
                diagnostic['prediction_primary5d']=mean;diagnostic['value_sigma']=sigma
                diagnostic['scope']='PAST_HELDOUT_CALIBRATION_USED_FOR_FIT_NOT_OOF_EVALUATION'
                r['phase']='ARTIFACT_SAVE';save_receipt()
                _save(lambda:diagnostic.to_parquet(root/'calibration.parquet',index=False),s['artifact_save_attempts'])
                r['calibration_ref']=ref(root/'calibration.parquet')
                r['model_ref']=_dump(fitted,root/'model.joblib',s['artifact_save_attempts'])
                r.update(status='TRAINED',phase='COMPLETED',calibration=calibration);save_receipt()
                values._append(log,dict(event='EBM_ENGINEERING_RETRY_COMPLETE',year=year,attempt=number,fit_units=r['fit_units'],reuse_tuple_sha256=tuple_sha))
                return fitted
            except Exception as exc:
                retry=engineering_failure(exc);r.update(status='FAILED_ENGINEERING' if retry else 'FAILED_SCIENTIFIC_NO_RETRY',
                    failure=dict(type=type(exc).__name__,message=str(exc)));save_receipt()
                values._append(log,dict(event='EBM_ENGINEERING_RETRY_FAILED',year=year,attempt=number,fit_units=r['fit_units'],
                    failure=r['failure'],reuse_tuple_sha256=tuple_sha));history.append(ref(rp))
                if not retry:return r
                if r.get('native_checkpoint_ref') is not None:native_reuse=r['native_checkpoint_ref']
                if number+1<2+s['max_new_physical_attempts_per_slot']:time.sleep(1)
        return dict(status='ENGINEERING_RETRY_LIMIT_REACHED',year=year,attempt_refs=history,preserved=True,test_2026_rows_read=0)


def run_all(run=RUN,reader=None):
    run,s,fr=contract(run);out=[]
    if reader is None:
        with predictors.fit_lock(run):
            parent=Path(s['parent_predictor_freeze_ref']['path']).parent
            reader=predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    for slot in SLOTS:
        print(f"START EBM teardown retry {slot['year']} 5d",flush=True)
        fitted=fit_one(run,slot['year'],reader);r=fitted.receipt if isinstance(fitted,predictors.ConsensusPredictor) else fitted
        out.append(dict(slot=slot,status=r['status'],receipt_ref=ref(r['receipt_path']) if 'receipt_path' in r else None))
        print(f"COMPLETE EBM teardown retry {slot['year']} {r['status']}",flush=True)
    return dict(status='FIXED_SIX_ATTEMPTS_FINISHED',freeze_ref=fr,slots=out,test_2026_read=False)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--run',default=str(RUN))
    parser.add_argument('--template',action='store_true');parser.add_argument('--metadata-preflight',action='store_true')
    parser.add_argument('--year',type=int);parser.add_argument('--all',action='store_true');args=parser.parse_args(argv)
    if args.template:result=freeze_template(args.run)
    elif args.metadata_preflight:result=metadata_preflight(args.run)
    elif args.all:result=run_all(args.run)
    elif args.year is not None:
        fitted=fit_one(args.run,args.year);result=fitted.receipt if isinstance(fitted,predictors.ConsensusPredictor) else fitted
    else:parser.error('choose --template, --metadata-preflight, --year or --all')
    print(json.dumps(result,sort_keys=True,default=str,allow_nan=False),flush=True)


if __name__=='__main__':main()
