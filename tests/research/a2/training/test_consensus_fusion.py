"""Synthetic exact packets, causal publications and shared ACK fit lifecycle."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import consensus_fusion as f
from scripts.research.a2.data.consensus_training_inputs import annual_fold


class Reader:
    def __init__(self,run):
        self.calendar=pd.bdate_range('2020-01-01','2025-12-31');self.records={}
        self.membership_sha256=f.values.sha(run/'derived/consensus100_daily.parquet')
    def annual_fold(self,y):return annual_fold(self.calendar,y)
    def dates(self,y):
        a=self.calendar[(self.calendar>=pd.Timestamp(f'{y}-01-01')) & (self.calendar<pd.Timestamp(f'{y+1}-01-01'))][:12]
        b=annual_fold(self.calendar,y+1)['calibration_sessions'][:12]
        return a.append(b)
    def frame(self,dates):
        dates=pd.DatetimeIndex(dates);n=len(dates);z=np.arange(n,dtype=float)-n/2
        x=pd.DataFrame(dict(signal_date=dates,ticker='SYN',cusip='000000001',
            feature_available=True,feature_source=f.owner.ALLOWED_SOURCES[0],label_available=True,
            account_event_unhandled=False,label_coordinate=f.values.LABEL,label_mature_date=dates+pd.Timedelta(days=1)))
        for k,col in enumerate(f.predictors.FEATURES):x[col]=z*.001+(k+1)*.01
        x['y_open5']=.1+.02*z+np.where(np.arange(n)%2,.01,-.01);x['target']=x.y_open5
        return x
    def read_training_fold(self,y,horizon=5):
        fold=self.annual_fold(y)
        return self.frame(self.dates(y-1)[:12]),self.frame(fold['calibration_sessions'][:12])
    def read_prediction_year(self,y):return self.frame(self.dates(y)).drop(columns=['target','y_open5'])
    def prediction_keys(self,y):
        a=self.read_prediction_year(y)[['signal_date','ticker']]
        return pd.concat([a,pd.DataFrame({'signal_date':[a.signal_date.iloc[0]],'ticker':['MISSING']})],ignore_index=True)


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,allow_nan=False),encoding='utf-8')


def publish(run,r,pf,model,year,horizon=5):
    slot,fr,mp,cp=f.predictors.slot_paths(run,model,year,horizon);slot.mkdir(parents=True,exist_ok=True)
    mp.write_bytes(b'SYNTHETIC_MODEL_SOURCE_PROOF');cp.write_bytes(b'HELDOUT_FIT_CALIBRATION_NOT_OOF')
    reuse=dict(year=year,horizon=horizon,primary_horizon=5,source_pins=pf['source_pins'],
        train_maturity_exclusive=str(r.annual_fold(year)['calibration_start']),calibration_maturity_exclusive=f'{year}-01-01',
        calibration_sessions=[str(d) for d in r.annual_fold(year)['calibration_sessions']],freeze_ref=dict(path=str(run/'CONSENSUS_PREDICTOR_FREEZE.json'),sha256=f.values.sha(run/'CONSENSUS_PREDICTOR_FREEZE.json')),
        authorized_spec=pf['authorized_spec'],input_binding_sha256=pf['input_binding_sha256'],membership_sha256=pf['membership_sha256'])
    fit=dict(status='TRAINED',model_id=model,year=year,horizon=horizon,reuse_tuple=reuse,reuse_tuple_sha256=f.values.digest(reuse),
        source_pins=pf['source_pins'],model_sha256=f.values.sha(mp),calibration_predictions_sha256=f.values.sha(cp))
    write(fr,fit)
    out=r.prediction_keys(year);n=len(out);out['prediction']=.03+np.arange(n)*.001
    out.loc[out.ticker.eq('MISSING'),'prediction']=np.nan;out['prediction_qualified']=out.prediction.notna()
    out['year']=year;out['reuse_tuple_sha256']=fit['reuse_tuple_sha256']
    path=run/'predictions/consensus_predictors'/model/f'{horizon}d/{year}.parquet';path.parent.mkdir(parents=True,exist_ok=True)
    out.to_parquet(path,index=False)
    pub=dict(status='PUBLISHED',path=str(path),sha256=f.values.sha(path),model_id=model,year=year,horizon=horizon,joint_horizon=5,
        rows=len(out),model_sha256=fit['model_sha256'],fit_receipt_path=str(fr),fit_receipt_sha256=f.values.sha(fr),
        reuse_tuple_sha256=fit['reuse_tuple_sha256'],source_pins=pf['source_pins'],test_2026_rows_read=0)
    write(path.with_suffix('.receipt.json'),pub);return path,pub


@pytest.fixture
def setup(tmp_path,monkeypatch):
    spec=json.loads(f.predictors.spec_path().read_text(encoding='utf-8'))
    sp=tmp_path/'synthetic_spec.json';write(sp,spec)
    monkeypatch.setattr(f.predictors,'spec_path',lambda:sp)
    monkeypatch.setattr(f.predictors,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(f,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(f.values,'assert_write_path',lambda *a,**k:None)
    monkeypatch.setattr(f,'write_json_atomic',write);monkeypatch.setattr(f.predictors,'write_json_atomic',write);monkeypatch.setattr(f.values,'write_json_atomic',write)
    run=tmp_path/'run';(run/'derived').mkdir(parents=True)
    (run/'derived/PHYSICAL_SOURCE_BINDING.json').write_text('{}',encoding='utf-8')
    (run/'derived/consensus100_daily.parquet').write_bytes(b'SYNTHETIC_POOL_IDENTITY')
    pf=f.predictors.freeze_template(run);pf['status']='AUTHORIZED_PRE2026_TRAINING_ONLY';write(run/'CONSENSUS_PREDICTOR_FREEZE.json',pf)
    frozen=f.freeze_template(run);frozen['status']='AUTHORIZED_PRE2026_TRAINING_ONLY';write(run/'CONSENSUS_FUSION_FREEZE.json',frozen)
    r=Reader(run)
    for y in (2021,2022,2023):
        for model in f.CORE:publish(run,r,pf,model,y)
    return run,r,spec,pf,frozen


def starts(run):return [e for e in f.values._events(run/'FIT_LOG.jsonl') if e['event']=='FIT_STARTED']


def test_fixed_packets_owner_ids_and_no_cartesian_growth(setup):
    _,_,spec,_,_=setup;slots=f.planned_slots(spec)
    assert len(slots)==84 and {s['owner_id'] for s in slots if s['packet_id']=='core5'}==set(range(32,45))
    ps=f.packets(spec);assert [len(p) for p in ps.values()]==[5,29,38]
    assert ps['core5'][-1]['model_id']=='cat' and f.FIXED_WEIGHTS==(.5,.125,.125,.125,.125)
    assert len([s for s in slots if s['packet_id']=='multih38'])==12
    with pytest.raises(ValueError,match='UNPLANNED_FUSION_SLOT'):f.contract(setup[0],'multih38','stack_hgb',2023)


def test_only_prior_annual_oof_and_disjoint_calibration_rows(setup):
    run,r,_,_,_=setup;slot=f.contract(run,'core5','equal',2023)[4]
    fold,train,cal,_,_,_,_,pins=f.training_packet(run,slot,2023,r)
    assert {p['year'] for p in pins}=={2021,2022}
    assert train.signal_date.max()<fold['calibration_start'] and train.label_mature_date.max()<fold['calibration_start']
    assert cal.signal_date.isin(fold['calibration_sessions']).all() and cal.label_mature_date.max()<fold['cutoff_exclusive']
    assert set(map(tuple,train[['signal_date','ticker']].values)).isdisjoint(set(map(tuple,cal[['signal_date','ticker']].values)))


def test_equal_lifecycle_cal_sigma_not_oof_and_checkpoint_reuse(setup):
    run,r,_,_,_=setup;fitted=f.fit_one(run,'core5','equal',2023,r)
    assert isinstance(fitted,f.ConsensusFusion) and fitted.receipt['calibration_is_oof'] is False
    slot=f.contract(run,'core5','equal',2023)[4];_,_,cal,_,cx,_,cstate,_=f.training_packet(run,slot,2023,r)
    raw=fitted.native.predict(cx,cstate)
    assert fitted.sigma==pytest.approx(np.std(cal.y_open5.to_numpy()-raw,ddof=1))
    assert len(starts(run))==1 and starts(run)[0]['component']=='HELDOUT_RESIDUAL_SIGMA'
    again=f.fit_one(run,'core5','equal',2023,r);assert again.receipt['model_sha256']==fitted.receipt['model_sha256'] and len(starts(run))==1
    pub=f.predict_one(run,'core5','equal',2023,r);out=pd.read_parquet(pub['path'])
    assert pub['prediction_role']=='MODEL_OOF' and len(out)==25 and not out.loc[out.ticker.eq('MISSING'),'prediction_qualified'].any()
    assert f.predict_one(run,'core5','equal',2023,r)==pub


def test_native_nnls_uses_shared_worker_ack_and_same_log(setup):
    run,r,_,_,_=setup;fitted=f.fit_one(run,'core5',35,2023,r)
    assert isinstance(fitted,f.ConsensusFusion)
    assert [s['component'] for s in starts(run)]==['FUSION_NNLS','HELDOUT_RESIDUAL_SIGMA']
    assert fitted.receipt['fit_units']==2 and fitted.receipt['physical_fit_metadata'][0]['metadata']['native_method']=='nnls'
    assert (fitted.native.weights>=0).all() and np.isclose(fitted.native.weights.sum(),1)


def test_missing_broad_member_never_shrinks_or_blocks_core(setup):
    run,r,_,_,_=setup;bad=f.fit_one(run,'broad29','equal',2023,r)
    assert bad['status']=='NOT_TESTABLE' and len(bad['members'])==29 and bad['fit_units']==0
    assert f.fit_one(run,'broad29','equal',2023,r)==bad
    assert isinstance(f.fit_one(run,'core5','equal',2023,r),f.ConsensusFusion)


def test_missing_member_row_is_not_silently_dropped(setup):
    run,r,_,_,_=setup;path=run/'predictions/consensus_predictors/ridge/5d/2022.parquet'
    a=pd.read_parquet(path);a=a.iloc[1:];a.to_parquet(path,index=False)
    rp=path.with_suffix('.receipt.json');pub=json.loads(rp.read_text());pub.update(sha256=f.values.sha(path),rows=len(a));write(rp,pub)
    result=f.fit_one(run,'core5','equal',2023,r)
    assert result['status']=='NOT_TESTABLE' and 'INCOMPLETE_REQUIRED' in result['reason'] and not starts(run)


@pytest.mark.parametrize('field,value',[('calibration_maturity_exclusive','2023-01-01'),('train_maturity_exclusive','2022-01-01')])
def test_future_member_fit_clock_rejected_before_numeric_scan(setup,monkeypatch,field,value):
    run,r,_,_,_=setup;member=dict(model_id='ridge',horizon=5);_,fr,_,_=f.predictors.slot_paths(run,'ridge',2022,5)
    fit=json.loads(fr.read_text());fit['reuse_tuple'][field]=value;fit['reuse_tuple_sha256']=f.values.digest(fit['reuse_tuple']);write(fr,fit)
    rp=run/'predictions/consensus_predictors/ridge/5d/2022.receipt.json';pub=json.loads(rp.read_text());pub.update(fit_receipt_sha256=f.values.sha(fr),reuse_tuple_sha256=fit['reuse_tuple_sha256']);write(rp,pub)
    monkeypatch.setattr(f.pq,'read_table',lambda *a,**k:pytest.fail('numeric forecast body opened'))
    with pytest.raises(ValueError,match='CLOCK_NOT_OOF'):f.publication(run,member,2022,r)


def test_calibration_artifact_cannot_be_declared_oof(setup,monkeypatch):
    run,r,_,_,_=setup;rp=run/'predictions/consensus_predictors/ridge/5d/2022.receipt.json'
    pub=json.loads(rp.read_text());pub['prediction_role']='CALIBRATION_FITTED';write(rp,pub)
    monkeypatch.setattr(f.pq,'read_table',lambda *a,**k:pytest.fail('calibration numeric body opened'))
    with pytest.raises(ValueError,match='CALIBRATION_IS_NOT'):f.publication(run,dict(model_id='ridge',horizon=5),2022,r)


def test_mixed_2026_physical_publication_rejected_before_values(setup,monkeypatch):
    run,r,_,_,_=setup;path=run/'predictions/consensus_predictors/ridge/5d/2022.parquet'
    a=pd.read_parquet(path);a.loc[len(a)-1,'signal_date']=pd.Timestamp('2026-01-01');a.to_parquet(path,index=False)
    rp=path.with_suffix('.receipt.json');pub=json.loads(rp.read_text());pub['sha256']=f.values.sha(path);write(rp,pub)
    monkeypatch.setattr(f.pq,'read_table',lambda *a,**k:pytest.fail('mixed-year numeric body opened'))
    with pytest.raises(ValueError,match='Forbidden mixed/test'):f.publication(run,dict(model_id='ridge',horizon=5),2022,r)


def test_final_cutoff_has_separate_gate_and_no_2026_prediction(setup):
    run,r,_,_,_=setup
    with pytest.raises(ValueError,match='FINAL_CUTOFF'):f.fit_one(run,'core5','equal',2026,r)
    with pytest.raises(ValueError,match='2026_PREDICTION'):f.predict_one(run,'core5','equal',2026,r)


def test_global_budget_failure_is_retained_without_retry(setup,monkeypatch):
    run,r,_,_,_=setup;write_log=run/'FIT_LOG.jsonl';write_log.write_text(json.dumps(dict(event='FIT_STARTED',fit_units=10000))+'\n')
    bad=f.fit_one(run,'core5','equal',2023,r);assert bad['status']=='FAILED' and bad['fit_units']==0
    monkeypatch.setattr(f,'training_packet',lambda *a:pytest.fail('failed slot re-read or retried'))
    assert f.fit_one(run,'core5','equal',2023,r)==bad


def test_failure_is_retained_and_completed_model_hash_checked(setup,monkeypatch):
    run,r,_,_,_=setup;monkeypatch.setattr(f.values,'_fit_job',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('SYNTH_FAIL')))
    bad=f.fit_one(run,'core5','nnls',2023,r);assert bad['status']=='FAILED' and bad['fit_units']==0
    assert f.fit_one(run,'core5','nnls',2023,r)==bad
    good=f.fit_one(run,'core5','equal',2023,r);Path(good.receipt['model_path']).write_bytes(b'CORRUPTED')
    with pytest.raises(ValueError,match='CHECKPOINT_CHANGED'):f.fit_one(run,'core5','equal',2023,r)


def test_source_pin_and_shared_lock_are_fail_closed(setup,monkeypatch):
    run,r,_,_,_=setup
    with f.predictors.fit_lock(run):
        with pytest.raises(FileExistsError):f.fit_one(run,'core5','equal',2023,r)
    assert not starts(run)
    monkeypatch.setattr(f,'source_pins',lambda:{})
    with pytest.raises(ValueError,match='FROZEN_SOURCE_CHANGED'):f.fit_one(run,'core5','equal',2023,r)


@pytest.mark.parametrize('width',[5,29,38])
def test_explicit_width_owner_reuse_and_legacy_defaults(width):
    x=np.arange(8*width,dtype=float).reshape(8,width)+1;y=x.mean(axis=1)
    starts=[];model=f.owner._fit_arrays('equal',x,y,None,None,starts.append,packet_width=width)
    assert not starts and np.allclose(model.predict(x,None),y)
    with pytest.raises(ValueError,match='INVALID_PAST'):f.owner._fit_arrays('equal',x,y,None,None,lambda _:None)
    with pytest.raises(ValueError,match='WIDTH'):f.owner._fit_arrays('equal',x,y,None,None,lambda _:None,packet_width=6)
    if width==5:
        weighted=f.owner._fit_arrays('fixed_weight',x,y,None,None,starts.append,packet_width=5,fixed_weights=f.FIXED_WEIGHTS)
        assert np.allclose(weighted.predict(x,None),x@f.FIXED_WEIGHTS)


@pytest.mark.parametrize('method',list(f.owner.METHODS.values()))
def test_all_thirteen_native_compact_methods_accept_fixed_core5(method):
    rng=np.random.default_rng(701);x=rng.normal(size=(256,5));state=rng.normal(size=(256,4))
    y=x@np.array([.5,.2,.15,.1,.05])+rng.normal(scale=.04,size=len(x));seen=[]
    model=f.owner._fit_arrays(method,x,y,state,np.ones(len(y)),seen.append,
        packet_width=5,fixed_weights=f.FIXED_WEIGHTS if method=='fixed_weight' else None)
    prediction=model.predict(x[:5],state[:5])
    assert prediction.shape==(5,) and np.isfinite(prediction).all()
    assert not seen if method in ('equal','median','fixed_weight') else seen
    if method=='stack_mlp':assert model.model.steps[-1][1].n_iter_==40
    if method=='residual_last_ridge':assert model.anchor==-1 and f.CORE[-1]=='cat'


def test_member_origin_pool_binding_rejected_before_numeric_scan(setup,monkeypatch):
    run,r,_,_,_=setup;_,fr,_,_=f.predictors.slot_paths(run,'ridge',2022,5)
    fit=json.loads(fr.read_text());fit['reuse_tuple']['membership_sha256']='0'*64
    fit['reuse_tuple_sha256']=f.values.digest(fit['reuse_tuple']);write(fr,fit)
    rp=run/'predictions/consensus_predictors/ridge/5d/2022.receipt.json';pub=json.loads(rp.read_text())
    pub.update(fit_receipt_sha256=f.values.sha(fr),reuse_tuple_sha256=fit['reuse_tuple_sha256']);write(rp,pub)
    monkeypatch.setattr(f.pq,'read_table',lambda *a,**k:pytest.fail('foreign pool numeric body opened'))
    with pytest.raises(ValueError,match='INPUT_ORIGIN_CHANGED'):f.publication(run,dict(model_id='ridge',horizon=5),2022,r)


@pytest.fixture
def continuation(setup,monkeypatch,tmp_path):
    parent,reader,spec,pf,ff=setup
    # Generate an ordinary complete parent publication before recording old-source custody.
    f.predict_one(parent,'core5','equal',2023,reader)
    for model in f.CORE:publish(parent,reader,pf,model,2024)
    child=tmp_path/'continuation';child.mkdir();archives=tmp_path/'old_source_archives';archives.mkdir()
    monkeypatch.setattr(f,'PARENT_RUN',parent);monkeypatch.setattr(f,'CONTINUATION_RUN',child)
    monkeypatch.setattr(f,'LEGACY_SOURCE_ARCHIVES',archives)
    sources={}
    for role,name in [('adapter','consensus_fusion_before_source_repair_continuation.py'),('fusion_owner','stateful_fusion_before_zero_abstention.py')]:
        path=archives/name;path.write_bytes(('GENERATED_OLD_'+role).encode());sources[role]=f.values.sha(path)
    monkeypatch.setattr(f,'LEGACY_SOURCE_SHA256',sources)
    ff=dict(ff);ff['source_pins']=dict(ff['source_pins'])
    ff['source_pins']['adapter']=dict(path=str(Path(f.__file__)),sha256=sources['adapter'])
    ff['source_pins']['fusion_owner']=dict(path=str(Path(f.owner.__file__)),sha256=sources['fusion_owner'])
    write(parent/'CONSENSUS_FUSION_FREEZE.json',ff);ff_ref=dict(path=str(parent/'CONSENSUS_FUSION_FREEZE.json'),sha256=f.values.sha(parent/'CONSENSUS_FUSION_FREEZE.json'))
    _,fr,mp=f.slot_paths(parent,'core5','equal',2023);fit=f.metadata(fr)
    fit['source_pins']=ff['source_pins'];fit['reuse_tuple']['source_pins']=ff['source_pins'];fit['reuse_tuple']['freeze_ref']=ff_ref
    fit['reuse_tuple_sha256']=f.values.digest(fit['reuse_tuple']);write(fr,fit)
    output=parent/'predictions/consensus_fusion/core5/equal/2023.parquet';frame=pd.read_parquet(output)
    frame['reuse_tuple_sha256']=fit['reuse_tuple_sha256'];frame.to_parquet(output,index=False)
    pub=f.metadata(output.with_suffix('.receipt.json'));pub.update(source_pins=ff['source_pins'],reuse_tuple_sha256=fit['reuse_tuple_sha256'],
        fit_receipt_sha256=f.values.sha(fr),sha256=f.values.sha(output));write(output.with_suffix('.receipt.json'),pub)
    ref=lambda path:dict(path=str(path),sha256=f.values.sha(path))
    dispositions=[]
    for slot in f.planned_slots(spec):
        entry=dict(slot=slot,status='NOT_TESTABLE')
        if (slot['packet_id'],slot['method'],slot['year'])==('core5','equal',2023):
            entry.update(status='TRAINED',receipt=ref(fr),artifacts=dict(model=ref(mp)),publication=ref(output.with_suffix('.receipt.json')),prediction=ref(output))
        dispositions.append(entry)
    audit=dict(task_id=f.TASK,run=str(parent),test_2026_numeric_read_authorized=False,candidate_fusions=dispositions)
    audit_path=parent/'CONSENSUS_RESEARCH_TERMINAL_AUDIT.json';write(audit_path,audit)
    log=parent/'FIT_LOG.jsonl';current=f.values._events(log);units=sum(e.get('fit_units',0) for e in current if e.get('event')=='FIT_STARTED')
    with log.open('a',encoding='utf-8') as stream:
        for _ in range(1098-units):stream.write(json.dumps(dict(event='FIT_STARTED',fit_units=1,synthetic_parent=True))+'\n')
    custody=dict(run=str(parent),predictor_freeze_ref=ref(parent/'CONSENSUS_PREDICTOR_FREEZE.json'),fusion_freeze_ref=ff_ref,
        physical_binding_ref=ref(parent/'derived/PHYSICAL_SOURCE_BINDING.json'),membership_ref=ref(parent/'derived/consensus100_daily.parquet'),
        authorized_spec_ref=pf['authorized_spec'],parent_fit_log_ref=ref(log),terminal_audit_ref=ref(audit_path),
        historical_fusion_adapter_archive_ref=ref(archives/'consensus_fusion_before_source_repair_continuation.py'),
        historical_owner_archive_ref=ref(archives/'stateful_fusion_before_zero_abstention.py'),parent_fit_units=1098,parent_fit_log_events=len(f.values._events(log)))
    scope=dict(schema='CONSENSUS_PRE2026_SOURCE_COMPLETION_CONTINUATION_SCOPE_R1',task_id=f.TASK,research_id=f.CONTINUATION_RESEARCH_ID,
        parent_research_id=f.TASK,run=str(child),original_artifacts_overwritten=False,parent_custody=custody,
        scientific_change=dict(new_named_fusion_candidate=f.owner.NNLS_ZERO_ABSTAIN,original_m035_zero_failure_preserved=True),
        boundaries=dict(fit_preprocess_calibration_selection_before='2026-01-01',no_new_2026_sample_or_outcome_read_authorized=True,FAST3_Confirmation_access=False),
        budget=dict(prior_fit_units=1098,global_original_fit_unit_limit=10000,no_fit_budget_reset=True,new_fusion_slots=4))
    scope_path=child/'CONTINUATION_SCOPE.json';write(scope_path,scope);monkeypatch.setattr(f,'CONTINUATION_SCOPE_SHA256',f.values.sha(scope_path))
    frozen=f.continuation_freeze_template(child);write(child/'CONSENSUS_FUSION_FREEZE.json',frozen)
    return dict(parent=parent,child=child,reader=reader,spec=spec,scope=scope,frozen=frozen,archives=archives,output=output,model=mp,fit_receipt=fr,scope_path=scope_path)


def authorize_continuation(c,*,final=False):
    c['frozen'].update(status='AUTHORIZED_PRE2026_TRAINING_ONLY',model_only_fit_authorized=True,final_cutoff_training_only_authorized=final)
    write(c['child']/'CONSENSUS_FUSION_FREEZE.json',c['frozen'])


def test_continuation_only_four_slots_parent_reader_and_no_fit_in_proposed(continuation):
    c=continuation;frozen=c['frozen'];child=c['child']
    assert len(f.planned_slots(c['spec']))==84 and len(frozen['ordered_slots'])==4
    assert {s['method'] for s in frozen['ordered_slots']}=={f.owner.NNLS_ZERO_ABSTAIN}
    assert [s['year'] for s in frozen['ordered_slots']]==[2023,2024,2025,2026]
    assert f.reader_run(child)==c['parent'] and frozen['prior_fit_units']==1098
    with pytest.raises(ValueError,match='CONTINUATION_FIT_NOT_AUTHORIZED'):f.fit_one(child,'core5',f.owner.NNLS_ZERO_ABSTAIN,2024,c['reader'])
    assert not (child/'FIT_LOG.jsonl').exists()
    authorize_continuation(c)
    with pytest.raises(ValueError,match='UNPLANNED_CONTINUATION_SLOT'):f.contract(child,'core5','nnls',2024)
    with pytest.raises(ValueError,match='FINAL_CUTOFF_ROOT_GATE'):f.contract(child,'core5',f.owner.NNLS_ZERO_ABSTAIN,2026)
    authorize_continuation(c,final=True);assert f.contract(child,'core5',f.owner.NNLS_ZERO_ABSTAIN,2026)[4]['year']==2026


def test_continuation_historical_parent_forecast_full_checks_without_live_relabelling(continuation):
    c=continuation;authorize_continuation(c);before=f.values.sha(c['parent']/'FIT_LOG.jsonl')
    out,pin=f.published_fusion_forecasts(c['child'],'equal',2023,c['reader'])
    assert len(out)==len(c['reader'].prediction_keys(2023)) and not out.prediction_qualified.iloc[-1]
    assert pin['origin_run']==str(c['parent']) and pin['source_role']=='PARENT_IMMUTABLE_PUBLISHED_FACT'
    assert c['scope']['parent_custody']['historical_fusion_adapter_archive_ref']['sha256']!=f.values.sha(f.__file__)
    assert before==f.values.sha(c['parent']/'FIT_LOG.jsonl') and not (c['child']/'models').exists()
    with pytest.raises(f.PacketUnavailable,match='PARENT_FUSION_PUBLICATION_UNAVAILABLE'):f.published_fusion_forecasts(c['child'],'nnls',2024,c['reader'])


def test_continuation_zero_model_child_only_budget_sigma_and_publication(continuation,monkeypatch):
    c=continuation;authorize_continuation(c);reader=c['reader'];original=reader.read_training_fold
    def negative_fold(year,horizon=5):
        frames=original(year,horizon)
        for frame in frames:frame['target']=frame['y_open5']=-np.abs(frame.y_open5.to_numpy())-.01
        return frames
    monkeypatch.setattr(reader,'read_training_fold',negative_fold)
    parent_log_before=f.values.sha(c['parent']/'FIT_LOG.jsonl');calls=[];start=f.values._component_start
    def counted(log,auth,prior,model,year,component,identity):
        calls.append((Path(log),prior,component));return start(log,auth,prior,model,year,component,identity)
    monkeypatch.setattr(f.values,'_component_start',counted)
    pub=f.predict_one(c['child'],'core5',f.owner.NNLS_ZERO_ABSTAIN,2024,reader)
    assert pub['status']=='PUBLISHED' and all(p==c['child']/'FIT_LOG.jsonl' and n==1098 for p,n,_ in calls)
    assert [v[2] for v in calls]==['FUSION_NNLS','HELDOUT_RESIDUAL_SIGMA']
    out,pin=f.published_fusion_forecasts(c['child'],f.owner.NNLS_ZERO_ABSTAIN,2024,reader)
    valid=out.prediction_qualified
    assert out.loc[valid,'prediction'].eq(0.).all() and out.loc[valid,'value_sigma'].gt(0.).all()
    assert out.loc[~valid,'prediction'].isna().all() and pin['origin_run']==str(c['child'])
    assert f.values.sha(c['parent']/'FIT_LOG.jsonl')==parent_log_before
    _,rp,mp=f.slot_paths(c['child'],'core5',f.owner.NNLS_ZERO_ABSTAIN,2024);receipt=f.metadata(rp)
    assert receipt['fit_units']==2 and receipt['reuse_tuple']['prior_fit_units']==1098
    assert receipt['zero_abstention_certificate']['unique_zero_optimum'] is True
    assert not (c['child']/'derived').exists()


@pytest.mark.parametrize('which',['archive','model','publication','parent_log','predictor_calibration'])
def test_continuation_wrong_parent_custody_or_leaf_bytes_reject(continuation,which):
    c=continuation;authorize_continuation(c)
    paths=dict(archive=c['archives']/'stateful_fusion_before_zero_abstention.py',model=c['model'],
        publication=c['output'].with_suffix('.receipt.json'),parent_log=c['parent']/'FIT_LOG.jsonl',
        predictor_calibration=f.predictors.slot_paths(c['parent'],'ridge',2021,5)[3])
    paths[which].write_bytes(b'TAMPERED_SYNTHETIC_BYTES')
    with pytest.raises(ValueError):f.published_fusion_forecasts(c['child'],'equal',2023,c['reader'])


def test_continuation_wrong_identity_source_or_budget_reject(continuation):
    c=continuation;authorize_continuation(c);path=c['child']/'CONSENSUS_FUSION_FREEZE.json';original=path.read_bytes()
    for field,value in [('prior_fit_units',0),('source_pins',{}),('research_id','OTHER'),('parent_custody',{})]:
        changed=dict(c['frozen']);changed[field]=value;write(path,changed)
        with pytest.raises(ValueError):f.contract(c['child'],'core5',f.owner.NNLS_ZERO_ABSTAIN,2024)
        path.write_bytes(original)
    other=c['child'].parent/'unmanaged';other.mkdir();write(other/'CONSENSUS_FUSION_FREEZE.json',c['frozen'])
    with pytest.raises(ValueError,match='EXACT_CONTINUATION_RUN'):f.contract(other,'core5',f.owner.NNLS_ZERO_ABSTAIN,2024)


def test_continuation_future_prediction_block_before_payload(continuation,monkeypatch):
    c=continuation;authorize_continuation(c,final=True)
    monkeypatch.setattr(f.pq,'read_table',lambda *a,**k:pytest.fail('future numeric payload opened'))
    with pytest.raises(ValueError,match='2026_PREDICTION'):f.predict_one(c['child'],'core5',f.owner.NNLS_ZERO_ABSTAIN,2026,c['reader'])
    with pytest.raises(ValueError,match='2026_PREDICTION'):f.published_fusion_forecasts(c['child'],'equal',2026,c['reader'])


def test_continuation_future_physical_date_blocks_forecast_payload(continuation,monkeypatch):
    from scripts.research.a2.data import joint_input_binding as binding
    c=continuation;authorize_continuation(c);original=binding.guard_parquet;read=f.pq.read_table
    def footer(path,*args,**kwargs):
        pf,proof=original(path,*args,**kwargs)
        if Path(path)==c['output']:
            proof=dict(proof,date_bounds=dict(signal_date=[dict(min='2026-01-02',max='2026-01-03')]))
        return pf,proof
    def no_future_payload(path,*args,**kwargs):
        if Path(path)==c['output']:pytest.fail('future forecast body opened')
        return read(path,*args,**kwargs)
    monkeypatch.setattr(binding,'guard_parquet',footer);monkeypatch.setattr(f.pq,'read_table',no_future_payload)
    with pytest.raises(ValueError,match='FUSION_PUBLISHED_PHYSICAL_YEAR_CHANGED'):
        f.published_fusion_forecasts(c['child'],'equal',2023,c['reader'])
