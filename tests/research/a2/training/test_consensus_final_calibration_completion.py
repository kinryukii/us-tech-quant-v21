"""Generated pre2026 frames/models only. No actual source receipt or run is read."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sklearn.isotonic import IsotonicRegression
from scripts.research.a2.training import consensus_final_calibration_completion as m
ORIGINAL_FIT_JOB=m.values._fit_job


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')


def blob(path):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'SYNTHETIC_CONTROL_ONLY');return m.ref(path)


class FakeScaler:
    def transform(self,x):return x
    def fit(self,*a,**kw):raise AssertionError('native train-only scaler must never refit')


class FakeNative:
    def __init__(self,model_id):
        self.model_id=model_id;self.scaler=FakeScaler();self.estimator_object={'fixed_train_weights':np.array([.1,.2])};self._torch_model=None
    def raw_predict(self,x):
        scalar=.003*np.sin(np.arange(len(x)))
        if self.model_id in m.values.QUANTILE:return np.column_stack([scalar-.01,scalar,scalar+.01])
        if self.model_id in m.values.DISTRIBUTION:return np.column_stack([scalar,np.full(len(x),.03)])
        if self.model_id=='logistic':return .5+.2*np.sin(np.arange(len(x)))
        return scalar
    def fit(self,*a,**kw):raise AssertionError('native estimator must never refit')


class FakeFusion:
    def __init__(self,method):
        self.method=method;self.packet_width=5;self.coef=np.array([.2]*5)
        self.zero_abstention_certificate={'status':'SYNTHETIC_CERTIFIED_ZERO'} if method==m.fusion.owner.NNLS_ZERO_ABSTAIN else None
    def predict(self,x,state):return np.zeros(len(x)) if self.method==m.fusion.owner.NNLS_ZERO_ABSTAIN else np.asarray(x).mean(axis=1)*.2
    def fit(self,*a,**kw):raise AssertionError('fusion native weights must never refit')


@pytest.fixture
def b(tmp_path,monkeypatch):
    run=tmp_path/'child';parent=tmp_path/'parent';run.mkdir();parent.mkdir();code=blob(run/'source.py')
    monkeypatch.setattr(m.fusion,'CONTINUATION_RUN',run);monkeypatch.setattr(m,'assert_safe_output_path',lambda *a,**kw:None)
    monkeypatch.setattr(m,'source_pins',lambda:dict(adapter=code))
    monkeypatch.setattr(m,'write_json_atomic',write);monkeypatch.setattr(m.values,'write_json_atomic',write)
    monkeypatch.setattr(m.values,'assert_write_path',lambda *a,**kw:None);monkeypatch.setattr(m.values,'_native',lambda *a:None)
    monkeypatch.setattr(m.predictors,'reader_integrity',lambda *a:None)
    original_raw=m.predictors.raw_predict
    def generated_native_raw(bundle,owner,frame,reader):
        if owner in m.values.EXTENSIONS:return bundle.raw_predict(frame[list(m.predictors.FEATURES)].to_numpy(float))
        return original_raw(bundle,owner,frame,reader)
    monkeypatch.setattr(m.predictors,'raw_predict',generated_native_raw)
    sessions=pd.bdate_range('2025-10-07',periods=60);cal=pd.DataFrame(dict(signal_date=sessions,ticker='BN',
        target=.01*np.cos(np.arange(60))+.003*np.sin(np.arange(60)),label_coordinate=m.values.LABEL))
    cal['y_open5']=cal.target
    for i,f in enumerate(m.predictors.FEATURES):cal[f]=np.arange(60)*.01+i
    train=cal.iloc[:8].copy();train.signal_date=pd.bdate_range('2025-08-01',periods=8)
    frames={}
    for h in (5,3,10,20):
        t=train.copy();c=cal.copy()
        if h!=5:t.target=t.target*h;c.target=c.target*h
        frames[h]=(dict(calibration_sessions=sessions,calibration_start=sessions[0],cutoff_exclusive=pd.Timestamp('2026-01-01')),t,c)
    monkeypatch.setattr(m.predictors,'guarded_frames',lambda r,y,h:frames[h])
    reader=SimpleNamespace();pf_path=parent/'CONSENSUS_PREDICTOR_FREEZE.json';write(pf_path,dict(fake=True));pfr=m.ref(pf_path)
    scope=blob(run/'CONTINUATION_SCOPE.json');facts=dict(parent=parent,scope_ref=scope,scope=dict(parent_custody=dict(parent_fit_log_ref=blob(parent/'FIT_LOG.jsonl'),predictor_freeze_ref=pfr)),
        spec=dict(dependency_paths=[]),pf=dict(fake=True))
    monkeypatch.setattr(m.fusion,'_continuation_facts',lambda r:facts);monkeypatch.setattr(m.fusion,'reader_run',lambda r:parent)
    ps=[];fs=[]
    def original(kind,slot):
        owner=m.predictors.ALIAS.get(slot.get('model_id'),slot.get('model_id')) if kind=='predictor' else slot['method']
        h=slot.get('horizon',5);_,t,c=frames[h];root=parent/'original'/kind/(owner+'_'+str(h));root.mkdir(parents=True)
        reuse=dict(task_id=m.TASK,model_id=owner,year=2026,train_maturity_exclusive=str(sessions[0]),calibration_maturity_exclusive='2026-01-01',
            calibration_sessions=[str(d) for d in sessions],train_frame_sha256=m.predictors.frame_hash(t),calibration_frame_sha256=m.predictors.frame_hash(c),freeze_ref=code,
            past_publication_pins=[],horizon=h)
        r=dict(status='TRAINED',model_id=owner,native_model_id=owner,year=2026,horizon=h,reuse_tuple=reuse,reuse_tuple_sha256=m.values.digest(reuse))
        fitted=m.predictors.ConsensusPredictor(FakeNative(owner),dict(model_id=owner,kind='point',offset=0.,sigma=.1),None,r) if kind=='predictor' else m.fusion.ConsensusFusion(FakeFusion(owner),.1,r,parent)
        mp=root/'model.joblib';joblib.dump(fitted,mp);cp=blob(root/'old_calibration.parquet');write(root/'receipt.json',r)
        return dict(slot=slot,status='TRAINED',receipt=m.ref(root/'receipt.json'),artifacts=dict(model=m.ref(mp),calibration=cp))
    for model in m.values.FIRST_MODELS:
        if model!='ebm':ps.append(original('predictor',dict(model_id=model,year=2026,horizon=5)))
    for h in (3,10,20):
        for model in m.predictors.SECONDARY:ps.append(original('predictor',dict(model_id=model,year=2026,horizon=h)))
    members=[dict(model_id=x,horizon=5) for x in m.fusion.CORE]
    for method in list(m.fusion.PACKET_METHODS['core5'])+[m.fusion.owner.NNLS_ZERO_ABSTAIN]:fs.append(original('fusion',dict(packet_id='core5',method=method,year=2026,members=members)))
    excluded=[dict(slot=dict(model_id='ebm',year=2026,horizon=5),status='FAILED',receipt=code)]
    monkeypatch.setattr(m,'_originals',lambda r:(facts,ps,fs,excluded))
    x=np.tile(np.arange(60,dtype=float)[:,None]*.001,(1,5));tx=x[:8].copy()
    monkeypatch.setattr(m.fusion,'training_packet',lambda *a:(frames[5][0],frames[5][1],frames[5][2],tx,x,np.zeros((8,4)),np.zeros((60,4)),[]))
    patch=cal.iloc[:2][['signal_date','ticker']].copy();patch['cusip']='123456789'
    patch['execution_date']=pd.to_datetime(['2025-10-08','2025-10-09']);patch['label_end_date']=pd.to_datetime(['2025-10-15','2025-10-16'])
    patch['label_mature_date']=pd.to_datetime(['2025-10-16','2025-10-17']);patch['label_coordinate']=m.values.LABEL
    patch['old_y_open5']=cal.iloc[:2].y_open5.to_numpy();patch['new_y_open5']=(1+patch.old_y_open5)*1.5/1.4999925000374998-1
    patch['old_quantity_multiplier']=1.4999925000374998;patch['new_quantity_multiplier']=1.5;patch=patch[list(m.PATCH_COLUMNS)]
    patchp=run/'derived/source_completion/BN_FINAL_CALIBRATION_LABEL_PATCH_R1.parquet';patchp.parent.mkdir(parents=True);patch.to_parquet(patchp,index=False)
    receipt=dict(schema='CONSENSUS_SOURCE_QUALIFIED_FINAL_CALIBRATION_LABEL_PATCH_R1',status=m.PATCH_STATUS,task_id=m.TASK,
        research_id=m.fusion.CONTINUATION_RESEARCH_ID,patch_ref=m.ref(patchp),rows=2,exact_signal_keys=list(m.KEYS),fold_year_key=2026,
        fold_cutoff_exclusive='2026-01-01',calibration_start=str(sessions[0]),all_changed_keys_calibration_only=True,native_training_rows_changed=0,
        original_masks_and_support_unchanged=True,canonical_inputs_overwritten=False,features_or_prices_or_2026_payload_read=False)
    for role in ('support_ref','official_share_right_ref','source_panel_ref','label_formula_owner_ref','generator_ref'):receipt[role]=code
    rr=run/m.PATCH_RELATIVE;write(rr,receipt);monkeypatch.setattr(m,'PATCH_RECEIPT_SHA',m.ref(rr)['sha256'])
    spec=m.freeze_template(run);write(run/m.FREEZE,spec)
    jobs=[]
    def iso_job(operation,owner,x,y,dates,quantile,dependencies,features,observed,*,log,auth,prior,year,tuple_sha,receipt,**kw):
        assert operation=='isotonic' and prior==1098 and year==2026
        # Synthetic worker ACK sequence: reserve before any real isotonic fitting.
        m.values._component_start(log,auth,prior,owner,year,'ISOTONIC',tuple_sha);receipt['fit_units']+=1;write(Path(receipt['receipt_path']),receipt)
        jobs.append(dict(operation=operation,owner=owner,rows=len(x),ack_before_fit=True))
        return IsotonicRegression(out_of_bounds='clip').fit(x,y)
    monkeypatch.setattr(m.values,'_fit_job',iso_job)
    return dict(run=run,parent=parent,reader=reader,ps=ps,fs=fs,frames=frames,cal=cal,patch=patch,patchp=patchp,receipt=receipt,spec=spec,jobs=jobs)


def authorize(b):
    p=b['run']/'review.json';write(p,dict(status='PASS_ENGINEERING_SYNTHETIC_ONLY',test_2026_content_read=False))
    spec=copy.deepcopy(b['spec']);spec.update(status=m.GATE,independent_review_refs=[m.ref(p)]);write(b['run']/m.FREEZE,spec);return spec


def test_metadata_only_proposal_and_unreviewed_fit_are_closed(b,monkeypatch):
    monkeypatch.setattr(m.pq,'read_table',lambda *a,**kw:pytest.fail('metadata preflight cannot decode numerical patch'))
    monkeypatch.setattr(m.joblib,'load',lambda *a,**kw:pytest.fail('metadata preflight cannot load native model'))
    result=m.metadata_preflight(b['run']);assert len(result['predictor_slots'])==37 and len(result['fusion_slots'])==14
    assert result['status']=='PASS_METADATA_ONLY_NO_FIT_AUTHORITY' and result['numeric_inputs_read'] is False
    with pytest.raises(ValueError,match='INDEPENDENT_FIT_AUTHORITY'):m.fit_one(b['run'],'predictor','ridge',reader=b['reader'])
    spec=authorize(b);spec['predictor_slots'].pop();write(b['run']/m.FREEZE,spec)
    with pytest.raises(ValueError,match='FROZEN_PLAN_SOURCE_OR_RECIPE'):m.contract(b['run'])


def test_patch_changes_only_two_y5_and_primary_target_without_expansion(b):
    patch=m.read_patch(b['spec']);primary=m.apply_patch_to_calibration(b['frames'][5][2],5,patch)
    secondary=m.apply_patch_to_calibration(b['frames'][10][2],10,patch)
    assert primary.iloc[:2].target.equals(primary.iloc[:2].y_open5)
    pd.testing.assert_series_equal(secondary.target,b['frames'][10][2].target)
    pd.testing.assert_frame_equal(primary.iloc[2:],b['cal'].iloc[2:])
    missing=b['cal'].iloc[1:].reset_index(drop=True)
    with pytest.raises(ValueError,match='CANNOT_EXPAND'):m.apply_patch_to_calibration(missing,5,patch)
    bad=b['cal'].copy();bad.loc[0,'y_open5']+=.01
    with pytest.raises(ValueError,match='ORIGINAL_Y5'):m.apply_patch_to_calibration(bad,5,patch)


def test_patch_physical_future_clock_and_formula_drift_fail_before_fit(b):
    spec=copy.deepcopy(b['spec']);patch=b['patch'].copy();patch.loc[0,'label_mature_date']=pd.Timestamp('2026-01-02');patch.to_parquet(b['patchp'],index=False)
    spec['correction_sidecar_ref']=m.ref(b['patchp'])
    with pytest.raises(ValueError):m.read_patch(spec)
    patch=b['patch'].copy();patch.loc[0,'new_y_open5']+=.01;patch.to_parquet(b['patchp'],index=False);spec['correction_sidecar_ref']=m.ref(b['patchp'])
    with pytest.raises(ValueError,match='LABEL_REPAIR_FORMULA'):m.read_patch(spec)


def test_secondary_executes_original_owner_branch_and_counts_both_statistics(b):
    cal=m.apply_patch_to_calibration(b['frames'][10][2],10,b['patch']);fields={'native_mu':np.sin(np.arange(len(cal)))*.003};started=[]
    c,bridge=m.secondary_owner_calibration('ridge',10,cal,fields,started.append)
    assert started==['HELDOUT_OLS_BRIDGE_TO_PRIMARY5D','HELDOUT_BRIDGE_RESIDUAL_SIGMA']
    design=np.column_stack([np.ones(len(cal)),fields['native_mu']]);coef=np.linalg.lstsq(design,cal.y_open5.to_numpy(float),rcond=None)[0]
    assert bridge['intercept']==coef[0] and bridge['slope']==coef[1] and c['sigma']>0


@pytest.mark.parametrize('model',['ridge','huber','xgb_rank','svc','mlp_dist'])
def test_calibration_reuses_native_bytes_and_rank_svc_genuine_isotonic_ack(b,model):
    authorize(b);old=next(e for e in b['ps'] if e['slot']['model_id']==model and e['slot']['horizon']==5);sha=old['artifacts']['model']['sha256']
    r=m.fit_one(b['run'],'predictor',model,reader=b['reader'])
    assert r['status']=='CALIBRATION_COMPLETED' and r['native_training_refitted'] is False
    assert r['raw_native_payload_sha256_before']==r['raw_native_payload_sha256_after']
    assert m.values.sha(old['artifacts']['model']['path'])==sha
    assert r['fit_units']==(2 if model in ('xgb_rank','svc','huber') else 1)
    if model in ('xgb_rank','svc'):assert b['jobs'][0]['operation']=='isotonic' and b['jobs'][0]['ack_before_fit'] is True
    else:assert not b['jobs']
    if model=='mlp_dist':
        _,_,mp,cp=m.slot_paths(b['run'],'predictor',old['slot']);loaded=joblib.load(mp);diagnostic=pq.read_table(cp).to_pandas()
        raw=m.predictors.raw_predict(loaded.native,model,b['cal'],b['reader'])
        np.testing.assert_array_equal(diagnostic.native_mu.to_numpy(),m.values.raw_fields(model,raw)['native_mu'])


def test_secondary_calibration_two_units_and_native_target_stays_original(b):
    authorize(b);r=m.fit_one(b['run'],'predictor','ridge',horizon=10,reader=b['reader'])
    assert r['status']=='CALIBRATION_COMPLETED' and r['fit_units']==2
    assert r['bridge']['output_horizon']==5
    _,_,_,cp=m.slot_paths(b['run'],'predictor',dict(model_id='ridge',horizon=10));c=pq.read_table(cp).to_pandas()
    np.testing.assert_array_equal(c.target,b['frames'][10][2].target)


def test_fusion_zero_mu_is_unchanged_sigma_only_and_checkpoint_no_duplicate_fit(b):
    authorize(b);method=m.fusion.owner.NNLS_ZERO_ABSTAIN;r=m.fit_one(b['run'],'fusion',method,reader=b['reader'])
    assert r['status']=='CALIBRATION_COMPLETED' and r['fit_units']==1 and r['sigma']>0
    e=next(e for e in b['fs'] if e['slot']['method']==method);_,_,_,cp=m.slot_paths(b['run'],'fusion',e['slot'])
    c=pq.read_table(cp).to_pandas();assert c.prediction_primary5d.eq(0).all()
    log=b['run']/'FIT_LOG.jsonl';before=log.read_bytes();assert m.fit_one(b['run'],'fusion',method,reader=b['reader'])==r and log.read_bytes()==before


def test_full_51_manifest_can_join_final_builder_and_reuse_after_account_log_append(b,monkeypatch):
    authorize(b);original={e['artifacts']['model']['path']:e['artifacts']['model']['sha256'] for e in b['ps']+b['fs']}
    complete=m.run_all(b['run'],reader=b['reader'])
    assert complete['status']==m.closure.FINAL_CALIBRATION_STATUS and len(complete['predictor_completions'])==37 and len(complete['fusion_completions'])==14
    assert complete['original_excluded_final_predictor_failures'][0]['slot']['model_id']=='ebm'
    assert all(m.values.sha(p)==h for p,h in original.items())
    path=b['run']/m.closure.FINAL_CALIBRATION_RELATIVE
    checked,_=m.closure._final_calibration_completion(b['run'],dict(final_calibration_completion_ref=m.ref(path)),b['ps'],b['fs'],b['spec']['continuation_scope_ref'])
    assert checked['manifest']==complete
    before_log=(b['run']/'FIT_LOG.jsonl').read_bytes()
    monkeypatch.setattr(m.values,'_component_start',lambda *a,**kw:pytest.fail('frozen consumers must never fit'))
    monkeypatch.setattr(m.values,'_fit_job',lambda *a,**kw:pytest.fail('frozen consumers must never refit calibration'))
    for kind,key in (('predictor','predictor_completions'),('fusion','fusion_completions')):
        for item in complete[key]:
            fitted=joblib.load(item['artifacts']['model']['path'])
            if kind=='predictor':mean,sigma=m.frozen_predictor_values(fitted,b['frames'][item['slot']['horizon']][2],b['reader'])
            else:mean,sigma=m.frozen_fusion_values(fitted,np.ones((60,5)),np.zeros((60,4)))
            assert len(mean)==len(sigma)==60 and np.isfinite(mean).all() and np.all(sigma>0)
            if kind=='fusion' and item['slot']['method']==m.fusion.owner.NNLS_ZERO_ABSTAIN:assert np.all(mean==0)
    assert (b['run']/'FIT_LOG.jsonl').read_bytes()==before_log
    m.values._append(b['run']/'FIT_LOG.jsonl',dict(event='FIT_STARTED',fit_units=1,component='SYNTHETIC_ACCOUNT_RISK'))
    assert m.run_all(b['run'],reader=b['reader'])==complete


def test_native_hash_maturity_budget_failure_is_terminal_no_automatic_retry(b,monkeypatch):
    authorize(b);entry=next(e for e in b['ps'] if e['slot']==dict(model_id='ridge',year=2026,horizon=5))
    calls=[]
    def depleted(*a,**kw):calls.append(1);raise RuntimeError('CUMULATIVE_FIT_BUDGET_EXHAUSTED')
    monkeypatch.setattr(m.values,'_component_start',depleted)
    r=m.fit_one(b['run'],'predictor','ridge',reader=b['reader']);assert r['status']=='FAILED_NO_RETRY'
    assert m.fit_one(b['run'],'predictor','ridge',reader=b['reader'])==r and len(calls)==1
    _,rp,_,_=m.slot_paths(b['run'],'predictor',entry['slot']);write(rp,dict(r,reuse_tuple_sha256='0'*64))
    with pytest.raises(ValueError,match='CHECKPOINT_IDENTITY'):m.fit_one(b['run'],'predictor','ridge',reader=b['reader'])


def test_unplanned_ebm_other_year_future_run_and_native_frame_drift_are_rejected(b):
    authorize(b)
    with pytest.raises(ValueError,match='UNPLANNED'):m.fit_one(b['run'],'predictor','ebm',reader=b['reader'])
    with pytest.raises(ValueError,match='EXACT_CHILD'):m.contract(b['parent'])
    original=next(e for e in b['ps'] if e['slot']==dict(model_id='ridge',year=2026,horizon=5));rp=Path(original['receipt']['path']);r=json.loads(rp.read_text(encoding='utf-8'))
    r['reuse_tuple']['train_frame_sha256']='0'*64;r['reuse_tuple_sha256']=m.values.digest(r['reuse_tuple']);write(rp,r);original['receipt']=m.ref(rp)
    # Frozen originals must first bind this changed receipt; the frame guard still rejects it.
    spec=json.loads((b['run']/m.FREEZE).read_text(encoding='utf-8'));spec['original_final_predictors']=b['ps'];write(b['run']/m.FREEZE,spec)
    with pytest.raises(ValueError,match='ORIGINAL_NATIVE_TRAIN'):m.fit_one(b['run'],'predictor','ridge',reader=b['reader'])


def test_original_parent_job_ack_controls_genuine_generated_isotonic_fit(b):
    root=b['run']/'ack_only';root.mkdir();rp=root/'receipt.json';r=dict(receipt_path=str(rp),fit_units=0)
    y=.01*np.cos(np.arange(60));scores=.003*np.sin(np.arange(60));log=b['run']/'FIT_LOG.jsonl'
    fitted=ORIGINAL_FIT_JOB('isotonic','svc',scores,y,None,None,[],[],None,log=log,
        auth=dict(max_fit_units=10000),prior=1098,year=2026,tuple_sha='a'*64,receipt=r)
    assert isinstance(fitted,IsotonicRegression) and r['fit_units']==1
    assert r['physical_fit_metadata'][0]['operation']=='isotonic'
    events=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert len(events)==1 and events[0]['event']=='FIT_STARTED' and events[0]['component']=='HELDOUT_ISOTONIC'
    before=log.read_bytes();blocked=dict(receipt_path=str(root/'blocked.json'),fit_units=0)
    with pytest.raises(RuntimeError,match='CUMULATIVE_FIT_BUDGET_EXHAUSTED'):
        ORIGINAL_FIT_JOB('isotonic','svc',scores,y,None,None,[],[],None,log=log,auth=dict(max_fit_units=1098),
            prior=1098,year=2026,tuple_sha='b'*64,receipt=blocked)
    assert blocked['fit_units']==0 and 'physical_fit_metadata' not in blocked and log.read_bytes()==before


def test_svc_retains_original_two_per_class_calibration_gate(b,monkeypatch):
    cal=b['frames'][5][2];cal.target=np.abs(cal.target)+.001;cal.y_open5=cal.target
    b['patch']['old_y_open5']=cal.iloc[:2].y_open5.to_numpy();b['patch']['new_y_open5']=(1+b['patch'].old_y_open5)*1.5/1.4999925000374998-1
    b['patch'].to_parquet(b['patchp'],index=False)
    receipt=b['receipt'];receipt['patch_ref']=m.ref(b['patchp']);write(b['run']/m.PATCH_RELATIVE,receipt)
    # Rebind only this generated receipt to the generated original-frame proof.
    monkeypatch.setattr(m,'PATCH_RECEIPT_SHA',m.ref(b['run']/m.PATCH_RELATIVE)['sha256'])
    entry=next(e for e in b['ps'] if e['slot']['model_id']=='svc' and e['slot']['horizon']==5);rp=Path(entry['receipt']['path'])
    r=json.loads(rp.read_text(encoding='utf-8'));r['reuse_tuple']['calibration_frame_sha256']=m.predictors.frame_hash(cal)
    r['reuse_tuple_sha256']=m.values.digest(r['reuse_tuple']);write(rp,r);entry['receipt']=m.ref(rp)
    b['spec']=m.freeze_template(b['run']);authorize(b)
    r=m.fit_one(b['run'],'predictor','svc',reader=b['reader'])
    assert r['status']=='FAILED_NO_RETRY' and r['fit_units']==0 and r['failure']['message']=='CLASSIFICATION_CALIBRATION_TWO_PER_CLASS_REQUIRED'
    assert not b['jobs']
