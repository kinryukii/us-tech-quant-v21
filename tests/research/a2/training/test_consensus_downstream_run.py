"""Synthetic orchestration only; no real source or training job is opened."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import consensus_downstream_run as d


def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,allow_nan=False),encoding='utf-8')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    run=tmp_path/'run';run.mkdir();write(run/'logs/PREDICTOR_PROGRESS.json',dict(status='COMPLETED_ALL_FIXED_SLOTS',slots_complete=228,total_slots=228))
    monkeypatch.setattr(d,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(d,'write_json_atomic',write);monkeypatch.setattr(d.values,'write_json_atomic',write)
    monkeypatch.setattr(d.values,'assert_write_path',lambda *a,**k:None)
    monkeypatch.setattr(d.predictors,'assert_safe_output_path',lambda *a,**k:None)
    actual=json.loads(d.predictors.spec_path().read_text(encoding='utf-8'))
    slots=d.fusion.planned_slots(actual)
    write(run/'CONSENSUS_FUSION_FREEZE.json',dict(ordered_slots=slots))
    pf=dict(input_binding_sha256='a'*64,membership_sha256='b'*64)
    write(run/'CONSENSUS_PREDICTOR_FREEZE.json',pf)
    def predictor_contract(*args):return actual,pf,dict(path=str(run/'CONSENSUS_PREDICTOR_FREEZE.json'),sha256=d.values.sha(run/'CONSENSUS_PREDICTOR_FREEZE.json'))
    monkeypatch.setattr(d.predictors,'contract',predictor_contract)
    monkeypatch.setattr(d.predictors,'reader_integrity',lambda *a:None)
    monkeypatch.setattr(d.fusion,'contract',lambda run,packet,method,year:(run,method,actual,{},next(s for s in slots if (s['packet_id'],s['method'],s['year'])==(packet,method,year)),{}))
    af=d.auxiliary_freeze_template(run);af.update(status='AUTHORIZED_PRE2026_TRAINING_ONLY',final_cutoff_training_only_authorized=True);write(run/'CONSENSUS_AUXILIARY_FREEZE.json',af)
    rng=np.random.default_rng(100);train=pd.DataFrame(rng.normal(size=(80,32)),columns=d.predictors.FEATURES)
    train['signal_date']=pd.bdate_range('2022-01-03',periods=80);train['ticker']='SYN';train['feature_available']=True;train['feature_source']=d.auxiliary.ALLOWED_SOURCES[0]
    train['target']=123456.;train['y_open5']=654321.
    cal=train.iloc[:8].copy();cal['ticker']='CALIBRATION_NEVER_FIT'
    fold=dict(calibration_start=pd.Timestamp('2025-10-01'),cutoff_exclusive=pd.Timestamp('2026-01-01'),calibration_sessions=pd.bdate_range('2025-10-01',periods=60))
    monkeypatch.setattr(d.predictors,'guarded_frames',lambda *a:(fold,train,cal))
    return run,slots,train,cal,fold


def test_fixed84_plan_only63_pre2026_publications_and21_final_fit_only(setup,monkeypatch):
    run,slots,*_=setup;calls=[];reader=object()
    def predict(run,p,m,y,reader):
        calls.append(('publish',p,m,y,id(reader)))
        return dict(status='FAILED' if len(calls)==1 else ('NOT_TESTABLE' if len(calls)==2 else 'PUBLISHED'))
    def fit(run,p,m,y,reader):calls.append(('fit',p,m,y,id(reader)));return SimpleNamespace(receipt=dict(status='TRAINED'))
    monkeypatch.setattr(d.fusion,'predict_one',predict);monkeypatch.setattr(d.fusion,'fit_one',fit)
    result=d.run_fusion(run,reader)
    assert len(calls)==84 and sum(c[0]=='publish' for c in calls)==63 and sum(c[0]=='fit' for c in calls)==21
    assert all(c[3]<2026 for c in calls if c[0]=='publish') and all(c[3]==2026 for c in calls if c[0]=='fit')
    assert {c[4] for c in calls}=={id(reader)}
    assert result['status']=='COMPLETED_ALL_FIXED_SLOTS' and result['slots_complete']==84
    assert [x['status'] for x in result['rows'][:2]]==['FAILED','NOT_TESTABLE']


def test_upstream_progress_and_active_fit_block_before_any_reader(setup,monkeypatch):
    run,*_=setup;monkeypatch.setattr(d,'ConsensusInputs',lambda *a:pytest.fail('reader opened before upstream complete'))
    write(run/'logs/PREDICTOR_PROGRESS.json',dict(status='RUNNING',slots_complete=227,total_slots=228))
    with pytest.raises(ValueError,match='228'):d.run_plan(run)
    write(run/'logs/PREDICTOR_PROGRESS.json',dict(status='COMPLETED_ALL_FIXED_SLOTS',slots_complete=228,total_slots=228))
    (run/'CONSENSUS_FIT.lock').write_text('SYNTHETIC_ACTIVE_JOB')
    with pytest.raises(ValueError,match='NO_LOCK_COMPETITION'):d.run_plan(run)


def test_all_stage_orders_full_fusion_before_auxiliary_and_preserves_foreign_lock(setup,monkeypatch):
    run,*_=setup;events=[];reader=object()
    monkeypatch.setattr(d,'run_fusion',lambda run,reader:events.append(('fusion',id(reader))) or dict(status='COMPLETED_ALL_FIXED_SLOTS'))
    monkeypatch.setattr(d,'run_auxiliary',lambda run,reader:events.append(('aux',id(reader))) or dict(status='TRAINED_DIAGNOSTICS'))
    result=d.run_plan(run,reader=reader);assert [e[0] for e in events]==['fusion','aux'] and len({e[1] for e in events})==1
    assert not (run/'CONSENSUS_DOWNSTREAM.lock').exists() and result['auxiliary']['status']=='TRAINED_DIAGNOSTICS'
    (run/'CONSENSUS_DOWNSTREAM.lock').write_text('FOREIGN_EXISTING')
    with pytest.raises(FileExistsError):d.run_plan(run,reader=reader)
    assert (run/'CONSENSUS_DOWNSTREAM.lock').read_text()=='FOREIGN_EXISTING'


def fake_job(calls):
    def fit(operation,model_id,frame,y,dates,quantile,dependencies,features,observed,**kw):
        assert (Path(kw['log']).parent/'CONSENSUS_FIT.lock').exists()
        calls.append(frame.copy());assert operation=='auxiliary' and y is None and 'target' not in frame and 'y_open5' not in frame
        assert not frame.ticker.eq('CALIBRATION_NEVER_FIT').any() and kw['worker_target'] is d._auxiliary_worker
        for component in ['SCALER',*d.COMPONENTS]:
            d.values._component_start(kw['log'],kw['auth'],0,model_id,2026,component,kw['tuple_sha']);kw['receipt']['fit_units']+=1
            write(kw['receipt']['receipt_path'],kw['receipt'])
        return d.auxiliary.AuxiliaryFit(None,{},dict(methods={name:dict(status='FITTED') for name in d.COMPONENTS},fit_units=6))
    return fit


def test_aux_train_x_only_shared_fitlog6_and_hash_checkpoint_no_refit(setup,monkeypatch):
    run,*_=setup;calls=[];monkeypatch.setattr(d.values,'_fit_job',fake_job(calls))
    result=d.run_auxiliary(run,object())
    assert result['status']=='TRAINED_DIAGNOSTICS' and result['fit_units']==6 and result['calibration_rows_fitted']==0
    assert len(calls)==1 and result['reuse_tuple']['year_key']==2026 and result['reuse_tuple']['cutoff'].startswith('2025-10-01')
    assert all(v['status']=='NOT_TESTABLE' for v in result['rl'].values())
    events=d.values._events(run/'FIT_LOG.jsonl');assert sum(e['fit_units'] for e in events if e['event']=='FIT_STARTED')==6
    assert d.run_auxiliary(run,object())==result and len(calls)==1
    Path(result['model_path']).write_bytes(b'SYNTHETIC_CORRUPTED')
    with pytest.raises(ValueError,match='CHECKPOINT_CHANGED'):d.run_auxiliary(run,object())


def test_aux_budget_denial_failure_preserved_without_retry(setup,monkeypatch):
    run,*_=setup;calls=[];monkeypatch.setattr(d.values,'_fit_job',fake_job(calls))
    (run/'FIT_LOG.jsonl').write_text(json.dumps(dict(event='FIT_STARTED',fit_units=10000))+'\n')
    result=d.run_auxiliary(run,object());assert result['status']=='FAILED_NO_RETRY' and result['fit_units']==0
    monkeypatch.setattr(d.predictors,'guarded_frames',lambda *a:pytest.fail('failed slot retried'))
    assert d.run_auxiliary(run,object())==result and len(calls)==1


def test_aux_freeze_requires_exact_final_gate_and_source_before_frame_scan(setup,monkeypatch):
    run,*_=setup;path=run/'CONSENSUS_AUXILIARY_FREEZE.json';frozen=json.loads(path.read_text());frozen['final_cutoff_training_only_authorized']=False;write(path,frozen)
    monkeypatch.setattr(d.predictors,'guarded_frames',lambda *a:pytest.fail('unfrozen frame scanned'))
    with pytest.raises(ValueError,match='EXACT_AUTHORIZED'):d.run_auxiliary(run,object())


def test_aux_real_native_worker_ack_uses_only_synthetic_past_features(setup):
    _,_,train,_,fold=setup;frame=train.drop(columns=['target','y_open5'])
    class Pipe:
        def __init__(self):self.messages=[];self.closed=False
        def send(self,message):self.messages.append(message)
        def recv(self):return True
        def close(self):self.closed=True
    pipe=Pipe();d._auxiliary_worker(pipe,'auxiliary','native_auxiliary5',frame,None,None,None,(),list(d.predictors.FEATURES),
        dict(cutoff=str(fold['calibration_start']),source_contract=dict(feature_source_qualified=True,feature_order=list(d.predictors.FEATURES))))
    assert pipe.closed and sum(m[0]=='FIT_START' for m in pipe.messages)==6
    result=pipe.messages[-1];assert result[0]=='RESULT' and isinstance(result[1],d.auxiliary.AuxiliaryFit)
    assert len(result[1].models)==5 and not result[2]['primary_pto_changed']


def test_main_stage_final_freeze_gate_precedes_reader_open(setup,monkeypatch):
    run,*_=setup;path=run/'CONSENSUS_AUXILIARY_FREEZE.json';frozen=json.loads(path.read_text());frozen['final_cutoff_training_only_authorized']=False;write(path,frozen)
    monkeypatch.setattr(d,'ConsensusInputs',lambda *a:pytest.fail('reader opened before auxiliary authorization'))
    with pytest.raises(ValueError,match='EXACT_AUTHORIZED'):d.run_plan(run,stage='auxiliary')
    assert not (run/'CONSENSUS_DOWNSTREAM.lock').exists()


def test_aux_actual_spawn_ack_artifact_lifecycle_on_generated_features(setup):
    run,*_=setup;receipt=d.run_auxiliary(run,object())
    assert receipt['status']=='TRAINED_DIAGNOSTICS',receipt.get('failure')
    assert receipt['fit_units']==6 and Path(receipt['model_path']).is_file()
    fitted=d.joblib.load(receipt['model_path']);assert isinstance(fitted,d.auxiliary.AuxiliaryFit) and len(fitted.models)==5
    assert receipt['calibration_rows_fitted']==0 and all(v['status']=='NOT_TESTABLE' for v in receipt['rl'].values())
    assert len(receipt['physical_fit_metadata'])==1
    starts=[e for e in d.values._events(run/'FIT_LOG.jsonl') if e['event']=='FIT_STARTED']
    assert len(starts)==6 and sum(e['fit_units'] for e in starts)==6
    assert d.run_auxiliary(run,object())==receipt


def test_continuation_named_entry_runs_only_four_slots_using_existing_parent_reader(setup,tmp_path,monkeypatch):
    parent,*_=setup;child=tmp_path/'child';child.mkdir()
    monkeypatch.setattr(d.fusion,'CONTINUATION_RUN',child)
    monkeypatch.setattr(d.fusion,'reader_run',lambda r:parent if r==child else r)
    slots=[dict(packet_id='core5',method='nnls_zero_abstain',year=y) for y in (2023,2024,2025,2026)]
    write(child/'CONSENSUS_FUSION_FREEZE.json',dict(ordered_slots=slots))
    monkeypatch.setattr(d.fusion,'contract',lambda r,p,m,y:(r,m,{}, {},next(s for s in slots if s['year']==y),{}))
    calls=[];reader=object()
    monkeypatch.setattr(d.fusion,'predict_one',lambda r,p,m,y,reader:(calls.append(('publish',y,id(reader))),dict(status='PUBLISHED'))[1])
    monkeypatch.setattr(d.fusion,'fit_one',lambda r,p,m,y,reader:(calls.append(('fit',y,id(reader))),SimpleNamespace(receipt=dict(status='TRAINED')))[1])
    monkeypatch.setattr(d,'run_auxiliary',lambda *a:pytest.fail('no new auxiliary search authorized'))
    monkeypatch.setattr(d,'ConsensusInputs',lambda *a:pytest.fail('reuse supplied guarded parent reader'))
    with pytest.raises(ValueError,match='ONLY_FOUR'):d.run_plan(child,stage='all',reader=reader)
    assert not (child/'CONSENSUS_DOWNSTREAM.lock').exists()
    result=d.run_plan(child,stage='fusion',reader=reader)['fusion']
    assert result['status']=='COMPLETED_ALL_FIXED_SLOTS' and result['total_slots']==4
    assert calls==[('publish',2023,id(reader)),('publish',2024,id(reader)),('publish',2025,id(reader)),('fit',2026,id(reader))]
    assert not (child/'CONSENSUS_DOWNSTREAM.lock').exists()
