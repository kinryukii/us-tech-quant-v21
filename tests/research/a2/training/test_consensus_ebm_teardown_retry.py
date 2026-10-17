"""Generated vectors, clocks, authority refs and worker cleanup; no real fit/data."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import consensus_ebm_teardown_retry as owner
from test_consensus_predictors import SyntheticReader

ORIGINAL_JOB=owner.values._fit_job


def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,sort_keys=True,allow_nan=False),encoding='utf-8')


class GeneratedReader(SyntheticReader):
    def __init__(self,run):
        super().__init__(run)
        self.calendar=self.calendar[~self.calendar.isin(pd.to_datetime(['2025-11-27','2025-12-25']))]
    def read_training_fold(self,year,horizon=5):
        train,cal=super().read_training_fold(year,horizon)
        if year==2026:cal.loc[cal.index[:2],'ticker']='BN'
        return train,cal


class GeneratedEstimator:
    def predict(self,x):return .02*np.asarray(x)[:,0]


class GeneratedBundle:
    def __init__(self,model_id,features):
        self.model_id=model_id;self.features=features;self.scaler=None;self.estimator_object=None
    def raw_predict(self,x):return self.estimator_object.predict(x)


@pytest.fixture
def setup(tmp_path,monkeypatch):
    run=tmp_path/'child';parent=tmp_path/'parent';(parent/'derived').mkdir(parents=True);run.mkdir()
    (parent/'derived/consensus100_daily.parquet').write_bytes(b'GENERATED MEMBERSHIP IDENTITY ONLY')
    (parent/'derived/PHYSICAL_SOURCE_BINDING.json').write_text('{}',encoding='utf-8')
    reader=GeneratedReader(parent);f=owner.predictors
    pf=dict(source_pins=f.source_pins(),authorized_spec=None,input_binding_sha256=owner.values.sha(parent/'derived/PHYSICAL_SOURCE_BINDING.json'),
        membership_sha256=reader.membership_sha256)
    plan=dict(seed=20260928,physical_fit_timeout_seconds=1800,calibration_sessions=60,sample_cap=None,weights='UNIFORM_LEGAL_ROWS')
    sp=tmp_path/'original_spec.json';write(sp,dict(training_plan=plan,dependency_paths=[]));pf['authorized_spec']=owner.ref(sp)
    pp=parent/'CONSENSUS_PREDICTOR_FREEZE.json';write(pp,pf)
    parentlog=parent/'FIT_LOG.jsonl';parentlog.write_text('{"event":"GENERATED_PARENT_SENTINEL"}\n',encoding='utf-8')
    scope=run/'CONTINUATION_SCOPE.json';write(scope,dict(parent_custody=dict(prior_fit_units=1098,parent_fit_log_ref=owner.ref(parentlog))))
    evidence=tmp_path/'generated_engineering_evidence.json';write(evidence,dict(status='GENERATED_ONLY'))
    entries=[]
    for year in range(2021,2027):
        fold,train,cal=f.guarded_frames(reader,year,5)
        t=dict(model_id='ebm',year=year,horizon=5,source_pins=pf['source_pins'],authorized_spec=pf['authorized_spec'],freeze_ref=owner.ref(pp),
            seed=20260928,bridge='NONE',feature_binding=owner.values.feature_binding(),train_frame_sha256=f.frame_hash(train),
            calibration_frame_sha256=f.frame_hash(cal),train_maturity_exclusive=str(fold['calibration_start']),
            calibration_maturity_exclusive=str(fold['cutoff_exclusive']),calibration_sessions=[str(x) for x in fold['calibration_sessions']])
        rp=parent/'models'/str(year)/'receipt.json';write(rp,dict(status='FAILED',model_id='ebm',year=year,horizon=5,fit_units=1,
            failure=dict(message='FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'),reuse_tuple=t,reuse_tuple_sha256=owner.values.digest(t)))
        entries.append(dict(model_id='ebm',year=year,horizon=5,original_failed_receipt_ref=owner.ref(rp),
            original_reuse_tuple_sha256=owner.values.digest(t),original_train_frame_sha256=f.frame_hash(train),original_calibration_frame_sha256=f.frame_hash(cal)))
    proposal=tmp_path/'_maintenance'/owner.TASK/owner.BASE_RELATIVE
    write(proposal,dict(schema='CONSENSUS_EBM_POST_RESULT_ENGINEERING_RETRY_AUTHORITY_R1',status='PROPOSED_NO_FIT_OR_PREDICTION_AUTHORITY',
        run=str(run),research_id=owner.fusion.CONTINUATION_RESEARCH_ID,attempt_id='GENERATED_EBM_RETRY',ordered_retry_slots=entries,
        continuation_scope_ref=owner.ref(scope),source_owner_refs=dict(values=owner.ref(Path(owner.values.__file__))),engineering_evidence_ref=owner.ref(evidence),
        authorized_original_spec_ref=owner.ref(sp),parent_predictor_freeze_ref=owner.ref(pp),fit_budget=dict(inherited_parent_fit_units=1098)))
    _,cal=reader.read_training_fold(2026,5);rows=[]
    for row in cal.iloc[:2].itertuples():
        old=float(row.y_open5);day=pd.Timestamp(row.signal_date)
        rows.append(dict(signal_date=day,ticker='BN',cusip='000000001',execution_date=day+pd.Timedelta(days=1),
            label_end_date=day+pd.Timedelta(days=5),label_mature_date=day+pd.Timedelta(days=6),label_coordinate=owner.values.LABEL,
            old_y_open5=old,new_y_open5=(1+old)*1.5/1.4999925000374998-1,old_quantity_multiplier=1.4999925000374998,new_quantity_multiplier=1.5))
    patch=run/'generated_patch.parquet';pd.DataFrame(rows,columns=owner.finalcal.PATCH_COLUMNS).to_parquet(patch,index=False)
    patchreceipt=run/'generated_patch_metadata.json';write(patchreceipt,dict(status='GENERATED_SOURCE_QUALIFICATION'))
    monkeypatch.setattr(owner,'RUN',run);monkeypatch.setattr(owner,'BASE_SHA',owner.values.sha(proposal))
    monkeypatch.setattr(owner,'resolve',lambda *_:SimpleNamespace(results_root=tmp_path))
    monkeypatch.setattr(owner,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(owner,'dependency_binding',lambda _:dict(generated_code_inventory=True))
    monkeypatch.setattr(owner.finalcal,'_patch_metadata',lambda _: (owner.ref(patchreceipt),dict(patch_ref=owner.ref(patch))))
    monkeypatch.setattr(owner,'write_json_atomic',write);monkeypatch.setattr(owner.values,'write_json_atomic',write)
    monkeypatch.setattr(owner.values,'assert_write_path',lambda *a,**k:None)
    monkeypatch.setattr(owner.values,'_native',lambda _:SimpleNamespace(NativeBundle=GeneratedBundle))
    childlog=run/'FIT_LOG.jsonl';childlog.write_text('{"event":"GENERATED_CHILD_SENTINEL"}\n',encoding='utf-8')
    def fake_job(*args,**kwargs):
        r=kwargs['receipt'];owner.values._component_start(kwargs['log'],kwargs['auth'],kwargs['prior'],'ebm',kwargs['year'],'PREDICTOR',kwargs['tuple_sha'])
        r['fit_units']+=1;write(r['receipt_path'],r);return GeneratedEstimator()
    monkeypatch.setattr(owner.values,'_fit_job',fake_job)
    s=owner.freeze_template(run);write(run/owner.FREEZE,s)
    return SimpleNamespace(run=run,parent=parent,reader=reader,spec=s,proposal=proposal,childlog=childlog,fake_job=fake_job)


def authorize(ctx):
    s=copy.deepcopy(ctx.spec);s['status']=owner.GATE
    s['child_fit_log_prefix']=dict(owner.ref(ctx.childlog),bytes=ctx.childlog.stat().st_size)
    binding=owner.authority_binding(s)
    roles=(('independent_review_ref','CONSENSUS_EBM_TEARDOWN_RETRY_INDEPENDENT_REVIEW_R1','PASS'),
        ('scientific_retry_authority_ref','CONSENSUS_EBM_TEARDOWN_RETRY_SCIENTIFIC_AUTHORITY_R1',owner.GATE),
        ('registry_attempt_binding_ref','CONSENSUS_EBM_TEARDOWN_RETRY_REGISTRY_BINDING_R1','APPLIED'))
    for field,schema,status in roles:
        p=ctx.run/(field+'.json');a=dict(schema=schema,status=status,binding=binding,reviewer_id='generated_independent_reviewer')
        if field=='scientific_retry_authority_ref':a.update(final_BN_two_key_calibration_authorized=True,
            source_qualification_ref=s['source_qualification_ref'],correction_sidecar_ref=s['correction_sidecar_ref'])
        write(p,a);s[field]=owner.ref(p)
    write(ctx.run/owner.FREEZE,s);return s


def fit_events(ctx):
    return [json.loads(line) for line in ctx.childlog.read_text(encoding='utf-8').splitlines() if json.loads(line)['event']=='FIT_STARTED']


def test_proposed_metadata_does_not_read_payload_or_authorize_fit(setup):
    count=setup.reader.reads;r=owner.metadata_preflight(setup.run)
    assert len(r['slots'])==6 and r['real_fits_started']==0 and not r['numeric_inputs_read']
    with pytest.raises(ValueError,match='FIT_AUTHORITY'):owner.fit_one(setup.run,2021,setup.reader)
    assert setup.reader.reads==count and not fit_events(setup)


def test_independent_science_registry_bind_exact_recipe_and_prefix(setup):
    s=authorize(setup);owner.contract(setup.run)
    changed=copy.deepcopy(s);changed['child_fit_log_prefix']['sha256']='0'*64
    assert owner.authority_binding(changed)!=owner.authority_binding(s)
    a=owner.metadata(s['independent_review_ref']['path']);a['reviewer_id']='consensus_pool'
    write(s['independent_review_ref']['path'],a);s['independent_review_ref']=owner.ref(s['independent_review_ref']['path']);write(setup.run/owner.FREEZE,s)
    with pytest.raises(ValueError,match='INDEPENDENT_REVIEWER'):owner.contract(setup.run)


@pytest.mark.parametrize('field,value',[('wide_32_fusion_authorized',True),('max_fit_units',9999),('ordered_slots',owner.SLOTS[:-1]),('test_2026_read_authorized',True)])
def test_frozen_scope_cannot_expand_or_shrink(setup,field,value):
    s=authorize(setup);s[field]=value;write(setup.run/owner.FREEZE,s)
    with pytest.raises(ValueError,match='FROZEN_PLAN'):owner.contract(setup.run)


def test_wrong_original_source_or_tuple_rejected(setup):
    b=owner.metadata(setup.proposal);entry=b['ordered_retry_slots'][0];r=owner.metadata(entry['original_failed_receipt_ref']['path'])
    r['reuse_tuple']['seed']=7;write(entry['original_failed_receipt_ref']['path'],r)
    entry['original_failed_receipt_ref']=owner.ref(entry['original_failed_receipt_ref']['path']);write(setup.proposal,b)
    old_sha=owner.BASE_SHA;owner.BASE_SHA=owner.values.sha(setup.proposal)
    try:
        with pytest.raises(ValueError,match='REUSE_TUPLE'):owner.freeze_template(setup.run)
    finally:owner.BASE_SHA=old_sha


def test_complete_checkpoint_and_pickle_native_consumer_without_new_fits(setup):
    authorize(setup);r=owner.fit_one(setup.run,2021,setup.reader);assert r.receipt['status']=='TRAINED'
    assert [e['component'] for e in fit_events(setup)]==['PREDICTOR','HELDOUT_RESIDUAL_SIGMA']
    again=owner.fit_one(setup.run,2021,setup.reader);frame=setup.reader.read_prediction_year(2021)
    out=again.predict_frame(frame,setup.reader);assert np.isfinite(out.prediction).all() and out.value_sigma.gt(0).all()
    assert len(fit_events(setup))==2 and not (setup.run/'CONSENSUS_FIT.lock').exists()
    old=owner.metadata(setup.proposal)['ordered_retry_slots'][0]['original_failed_receipt_ref'];owner.pin(old)


def test_engineering_failure_retained_and_same_recipe_bounded_resume(setup,monkeypatch):
    authorize(setup);calls=[]
    def fail_once(*a,**k):
        model=setup.fake_job(*a,**k);calls.append((a[0:3],k['year']))
        if len(calls)==1:raise RuntimeError('FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT')
        return model
    monkeypatch.setattr(owner.values,'_fit_job',fail_once);monkeypatch.setattr(owner.time,'sleep',lambda _:None)
    fitted=owner.fit_one(setup.run,2021,setup.reader);p=setup.run/owner.ROOT/'2021/attempt2/receipt.json'
    failed=owner.metadata(p);assert failed['status']=='FAILED_ENGINEERING' and failed['fit_units']==1
    assert fitted.receipt['previous_attempt_refs']==[owner.ref(p)] and len(fit_events(setup))==3
    assert calls[0][1]==calls[1][1] and owner.values.digest(failed['reuse_tuple'])==fitted.receipt['reuse_tuple_sha256']


def test_partial_native_checkpoint_resumes_calibration_without_new_native_fit(setup,monkeypatch):
    authorize(setup);original=owner.values.heldout_calibration;calls=[]
    def fail_once(*a,**k):
        calls.append(1)
        if len(calls)==1:raise OSError('generated transient storage/IPC failure')
        return original(*a,**k)
    monkeypatch.setattr(owner.values,'heldout_calibration',fail_once);monkeypatch.setattr(owner.time,'sleep',lambda _:None)
    fitted=owner.fit_one(setup.run,2021,setup.reader)
    assert Path(fitted.receipt['native_model_reused_ref']['path']).parts[-2:]==('attempt2','native_checkpoint.joblib')
    assert [e['component'] for e in fit_events(setup)]==['PREDICTOR','HELDOUT_RESIDUAL_SIGMA','HELDOUT_RESIDUAL_SIGMA']


def test_scientific_sigma_failure_does_not_retry(setup,monkeypatch):
    authorize(setup)
    monkeypatch.setattr(owner.values,'heldout_calibration',lambda *a,**k:(_ for _ in ()).throw(ValueError('NONPOSITIVE_HELDOUT_RESIDUAL_SIGMA')))
    r=owner.fit_one(setup.run,2021,setup.reader)
    assert r['status']=='FAILED_SCIENTIFIC_NO_RETRY' and len(fit_events(setup))==2
    assert not (setup.run/owner.ROOT/'2021/attempt3').exists()


def test_save_only_retry_consumes_no_additional_fit_unit(setup,monkeypatch):
    authorize(setup);original=owner.joblib.dump;calls=[]
    def once(value,path,*a,**k):
        calls.append(str(path))
        if len(calls)==1:raise OSError('generated transient save')
        return original(value,path,*a,**k)
    monkeypatch.setattr(owner.joblib,'dump',once);monkeypatch.setattr(owner.time,'sleep',lambda _:None)
    fitted=owner.fit_one(setup.run,2021,setup.reader);assert fitted.receipt['status']=='TRAINED' and len(fit_events(setup))==2
    assert len(calls)==3


def test_final_cutoff_patches_only_calibration_and_refuses_real_year2026_inference(setup):
    authorize(setup);fitted=owner.fit_one(setup.run,2026,setup.reader);t=fitted.receipt['reuse_tuple']
    assert t['original_calibration_frame_sha256']!=t['effective_calibration_frame_sha256']
    original=owner.metadata(t['original_failed_receipt_ref']['path'])
    assert t['train_frame_sha256']==original['reuse_tuple']['train_frame_sha256']
    _,cal=setup.reader.read_training_fold(2026,5)
    with pytest.raises(ValueError,match='PRE2026_ANNUAL_SCOPE'):fitted.predict_frame(cal,setup.reader)
    with pytest.raises(ValueError,match='SIX_PRE2026'):owner.fit_one(setup.run,2027,setup.reader)


def test_actual_global_budget_and_foreign_shared_lock_not_reset_or_removed(setup):
    authorize(setup);lock=setup.run/'CONSENSUS_FIT.lock';lock.write_text('GENERATED FOREIGN MAIN ACCOUNT LOCK',encoding='utf-8')
    with pytest.raises(FileExistsError):owner.fit_one(setup.run,2021,setup.reader)
    assert lock.read_text(encoding='utf-8')=='GENERATED FOREIGN MAIN ACCOUNT LOCK';lock.unlink()
    with setup.childlog.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(event='FIT_STARTED',fit_units=8902))+'\n')
    r=owner.fit_one(setup.run,2021,setup.reader)
    assert r['failure']['message']=='CUMULATIVE_FIT_BUDGET_EXHAUSTED' and r['fit_units']==0
    assert not (setup.run/owner.ROOT/'2021/attempt3').exists()


def test_prefix_can_append_but_not_rewrite_or_truncate(setup):
    s=authorize(setup)
    with setup.childlog.open('a',encoding='utf-8') as stream:stream.write('{"event":"GENERATED_APPEND"}\n')
    owner.contract(setup.run)
    setup.childlog.write_bytes(b'X'+setup.childlog.read_bytes()[1:])
    with pytest.raises(ValueError,match='PREFIX_CHANGED'):owner.contract(setup.run)


def generated_late_worker(pipe,*args):
    pipe.send(('FIT_START','PREDICTOR'));assert pipe.recv() is True
    pipe.send(('RESULT',dict(generated_result=True),dict(generated_worker=True)));time.sleep(6.1);pipe.close()


def generated_nonzero_worker(pipe,*args):
    pipe.send(('FIT_START','PREDICTOR'));assert pipe.recv() is True
    pipe.send(('RESULT',dict(generated_result=True),dict(generated_worker=True)));pipe.close();os._exit(9)


@pytest.mark.parametrize('target,clean',[(generated_late_worker,True),(generated_nonzero_worker,False)])
def test_original_job_post_result_wait_clean_exit_or_nonzero_rejection(tmp_path,monkeypatch,target,clean):
    monkeypatch.setattr(owner.values,'_fit_job',ORIGINAL_JOB);monkeypatch.setattr(owner.values,'FIT_TIMEOUT',20)
    monkeypatch.setattr(owner.values,'write_json_atomic',write);monkeypatch.setattr(owner.values,'assert_write_path',lambda *a,**k:None)
    r=dict(receipt_path=str(tmp_path/'receipt.json'),fit_units=0);events=[];write(r['receipt_path'],r)
    original_context=owner.values.mp.get_context
    with owner.post_result_context(events.append):
        args=dict(log=tmp_path/'FIT_LOG.jsonl',auth=dict(max_fit_units=10000),prior=1098,year=2021,tuple_sha='generated',receipt=r,worker_target=target)
        if clean:result=ORIGINAL_JOB('predictor','ebm',None,None,None,None,[],[],None,**args)
        else:
            with pytest.raises(RuntimeError,match='DID_NOT_EXIT_CLEANLY'):ORIGINAL_JOB('predictor','ebm',None,None,None,None,[],[],None,**args)
    assert owner.values.mp.get_context is original_context and r['fit_units']==1
    assert len(events)==1 and events[0]['clean_exit']==clean and not events[0]['deadline_reset_after_result']
    assert events[0]['fit_start_ack_count']==1 and events[0]['final_exitcode']==(0 if clean else 9)
    if clean:assert result['generated_result'] and events[0]['initial_join_alive']


def test_remaining_deadline_not_extended_and_nonresult_join_unchanged(monkeypatch):
    clock=[0.];monkeypatch.setattr(owner.time,'monotonic',lambda:clock[0])
    class Process:
        exitcode=None
        def __init__(self):self.waits=[]
        def is_alive(self):return True
        def join(self,timeout):self.waits.append(timeout);clock[0]+=timeout
    process=Process();events=[];state=dict(result_received=True,deadline=2.,result_monotonic=0.,ack_count=1)
    wrapped=owner._Process(process,state,events.append)
    with pytest.raises(TimeoutError,match='DURING_RESULT_TEARDOWN'):wrapped.join(5)
    assert sum(process.waits)==2 and events[0]['final_alive'] and not events[0]['clean_exit']
    wrapped.join(5);assert process.waits[-1]==5 # original finally cleanup; never another grace window
    process=Process();state['result_received']=False;wrapped=owner._Process(process,state,events.append);wrapped.join(5)
    assert process.waits==[5] and len(events)==1


@pytest.mark.parametrize('exc,retry',[(RuntimeError('FIT_WORKER_FAILED:RuntimeError:UNRESOLVED_CONVERGENCE_NO_AUTOMATIC_RETRY'),False),
    (TimeoutError('PHYSICAL_FIT_1800_SECONDS_EXCEEDED'),False),
    (RuntimeError('FIT_WORKER_FAILED:ModuleNotFoundError:generated missing import'),True)])
def test_engineering_classifier_preserves_scientific_and_timeout_failures(exc,retry):
    assert owner.engineering_failure(exc)==retry


def test_cold_original_native_bundle_and_unfitted_ebm_type_have_no_common_alias(tmp_path):
    # Original source/config only. The real EBM type is constructed, never fitted;
    # the consumer's estimator and all vectors are generated and explicitly named.
    import subprocess
    import sys
    deps=owner.metadata(owner.predictors.spec_path())['dependency_paths']
    native=owner.values._native(deps);bundle=native.NativeBundle('ebm',list(owner.predictors.FEATURES))
    bundle.estimator_object=GeneratedEstimator()
    x=np.arange(128,dtype=float).reshape(4,32)/128
    raw=bundle.raw_predict(x);cal=owner.values.heldout_calibration('ebm',raw,raw+np.array([-.01,.01,-.02,.02]))
    fitted=owner.predictors.ConsensusPredictor(bundle,cal,None,dict(native_model_id='ebm'))
    model=tmp_path/'generated_original_native_bundle.joblib';owner.joblib.dump(fitted,model)
    prototype=tmp_path/'unfitted_original_ebm_type.joblib';owner.joblib.dump(native.estimator('ebm'),prototype)
    code="""
import json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from scripts.research.a2.training import consensus_ebm_teardown_retry as m
native=m.values._native(json.loads(sys.argv[5]))
assert 'common' not in sys.modules
fitted=m.joblib.load(sys.argv[3]);proto=m.joblib.load(sys.argv[4])
x=np.arange(128,dtype=float).reshape(4,32)/128
raw=fitted.native.raw_predict(x);mu,sigma=fitted.mapped(raw)
assert np.isfinite(mu).all() and np.isfinite(sigma).all() and (sigma>0).all()
assert proto.get_params()==native.estimator('ebm').get_params()
assert proto.__class__.__name__=='ExplainableBoostingRegressor'
assert proto.get_params()['random_state']==20260928
assert not hasattr(proto,'term_scores_')
print(json.dumps(dict(status='GENERATED_COLD_NATIVE_CONSUMER_PASS',real_ebm_fits=0,common_alias=False)))
"""
    result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code,str(owner.predictors.REPO),str(Path(__file__).parent),
        str(model),str(prototype),json.dumps(deps)],capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout.strip())['real_ebm_fits']==0
