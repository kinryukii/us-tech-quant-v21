"""Synthetic recovery tests; no real research numeric payload or model decode."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import ElasticNet

from scripts.research.a2.training import consensus_forecast_recovery as r


_spec=importlib.util.spec_from_file_location('_consensus_fusion_synthetic_fixture',Path(__file__).with_name('test_consensus_fusion.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
write=_fixture.write


@pytest.fixture
def setup(tmp_path,monkeypatch):
    parent,reader,spec,pf,_=_fixture.setup.__wrapped__(tmp_path,monkeypatch)
    monkeypatch.setattr(r,'assert_safe_output_path',lambda *a,**k:None)
    run=tmp_path/'recovery';run.mkdir()
    old=parent/'models/consensus_predictors/elastic/5d/2021/receipt.json'
    write(old,dict(status='FAILED',model_id='elastic',year=2021,horizon=5,
                   failure=dict(message='FIT_WORKER_FAILED:RuntimeError:UNRESOLVED_CONVERGENCE_NO_AUTOMATIC_RETRY'),reuse_tuple={}))
    summary=tmp_path/'ebm_summary.json';write(summary,dict(schema='CONSENSUS_EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1',
              original_failures_preserved=True,slots=[dict(status='TRAINED')]))
    scope_file=tmp_path/'root_scope.json';write(scope_file,dict(synthetic=True))
    qualification=tmp_path/'qualification.json';write(qualification,dict(synthetic=True))
    sidecar=tmp_path/'sidecar.parquet';sidecar.write_bytes(b'SYNTHETIC_METADATA_ONLY_PATCH_NOT_DECODED')
    scope=dict(schema=r.SCHEMA,status=r.GATE,task_id=r.predictors.TASK,research_id=r.RESEARCH_ID,run=str(run),
        source_pins=r.source_pins(),parent_predictor_freeze_ref=r.ref(parent/'CONSENSUS_PREDICTOR_FREEZE.json'),
        root_scope_ref=r.ref(scope_file),elastic_original_failure_ref=r.ref(old),ebm_summary_ref=r.ref(summary),
        source_qualification_ref=r.ref(qualification),correction_sidecar_ref=r.ref(sidecar),
        recovered_ebm_broad_publication_authorized=True,
        elastic_solver=dict(model_id='elastic',year=2021,horizon=5,max_iter=25000,alpha=.0001,l1_ratio=.35,tol=1e-5,selection='cyclic'),
        ordered_fusion_slots=r.ordered_slots(spec),prior_fit_units=2063,max_fit_units=10000,max_new_fit_units=75,
        no_fit_budget_reset=True,train_and_development_before='2026-01-01',test_2026_read_authorized=False,
        confirmation_read_authorized=False,old_artifacts_overwrite=False)
    write(run/r.FREEZE,scope)
    return run,parent,reader,spec,pf,scope


def test_exact_40_slots_and_75_fit_upper_bound(setup):
    run,_,_,_,_,scope=setup
    assert len(scope['ordered_fusion_slots'])==40
    assert sum(s['method']==r.fusion.owner.NNLS_ZERO_ABSTAIN for s in scope['ordered_fusion_slots'])==8
    units={'equal':1,'median':1,'nnls':2,'convex':2,'stack_ridge':3,r.fusion.owner.NNLS_ZERO_ABSTAIN:2}
    assert 3+sum(units[s['method']] for s in scope['ordered_fusion_slots'])==75
    assert r.metadata_preflight(run)['numeric_inputs_read'] is False


@pytest.mark.parametrize('field,value', [('prior_fit_units',0),('max_new_fit_units',76),
    ('test_2026_read_authorized',True),('recovered_ebm_broad_publication_authorized',False)])
def test_scope_rejects_drift_before_numeric_access(setup,field,value):
    run,_,_,_,_,scope=setup;scope[field]=value;write(run/r.FREEZE,scope)
    with pytest.raises(ValueError):r.metadata_preflight(run)


def test_proposed_scope_has_no_fit_authority(setup):
    run,_,_,_,_,scope=setup;scope['status']='PROPOSED';write(run/r.FREEZE,scope)
    assert r.metadata_preflight(run)['status']=='PASS_METADATA_ONLY'
    with pytest.raises(ValueError,match='ROOT_FORECAST_FIT_GATE_REQUIRED'):r.contract(run)


def test_future_publication_rejected_before_scope_or_model(monkeypatch):
    monkeypatch.setattr(r,'contract',lambda *a,**k:pytest.fail('must reject before scope or numeric access'))
    with pytest.raises(ValueError,match='2026'):r.publish_recovered_ebm('unused',2026)
    with pytest.raises(ValueError,match='2026'):r.published_fusion_forecasts('unused','equal',2026)


def _publication(reader,member,year):
    keys=reader.prediction_keys(year)[['signal_date','ticker']].copy()
    keys['expert_'+r.fusion.member_key(member)]=.03+np.arange(len(keys))*.001
    keys.loc[keys.ticker.eq('MISSING'),'expert_'+r.fusion.member_key(member)]=np.nan
    return keys,dict(member=r.fusion.member_key(member),year=year,synthetic_pin=True)


def test_same_original_fusion_code_shared_cashless_fit_and_publication(setup,monkeypatch):
    run,parent,reader,_,_,_=setup
    module=r.bind_fusion(run)
    monkeypatch.setattr(module,'write_json_atomic',write)
    assert module.fit_one.__code__.co_code==r.fusion.fit_one.__code__.co_code
    assert module.ConsensusFusion.predict_frame.__code__.co_code==r.fusion.ConsensusFusion.predict_frame.__code__.co_code
    assert module.contract(run,'broad29','equal',2023)[0]==run
    assert module.reader_run(run)==parent
    monkeypatch.setattr(module,'publication',lambda actual,member,year,reader:_publication(reader,member,year))
    fitted=module.fit_one(run,'broad29','equal',2023,reader)
    assert fitted.receipt['status']=='TRAINED' and fitted.receipt['fit_units']==1
    events=list(r.values._events(run/'FIT_LOG.jsonl'))
    assert sum(e.get('fit_units',0) for e in events if e['event']=='FIT_STARTED')==1
    again=module.fit_one(run,'broad29','equal',2023,reader)
    assert again.receipt['model_sha256']==fitted.receipt['model_sha256']
    pub=module.predict_one(run,'broad29','equal',2023,reader)
    assert pub['status']=='PUBLISHED' and pub['test_2026_rows_read']==0
    out,pins=module.published_fusion_forecasts(run,'equal',2023,reader,packet_id='broad29')
    assert out.prediction_qualified.sum()==24 and isinstance(pins,dict)
    assert not out.loc[out.ticker.eq('MISSING'),'prediction_qualified'].any()


def test_new_named_zero_fusion_keeps_original_nnls_identity(setup):
    run,_,_,_,_,_=setup;module=r.bind_fusion(run)
    original=module.contract(run,'broad29','nnls',2024)[4]
    named=module.contract(run,'broad29',r.fusion.owner.NNLS_ZERO_ABSTAIN,2024)[4]
    assert original['owner_id']==35 and named['owner_id']=='NAMED_NNLS_ZERO_ABSTAIN_R1'
    assert original['method']!=named['method'] and original['members']==named['members']


class Pipe:
    def __init__(self):self.messages=[];self.closed=False
    def send(self,value):self.messages.append(value)
    def recv(self):return True
    def close(self):self.closed=True


def test_elastic_solver_extends_only_iterations_with_ack(monkeypatch):
    monkeypatch.setattr(r.values,'_native',lambda deps:SimpleNamespace(estimator=lambda _:ElasticNet(
        alpha=.0001,l1_ratio=.35,tol=1e-5,max_iter=2500,selection='cyclic',random_state=r.values.SEED)))
    random=np.random.default_rng(17);x=random.normal(size=(120,4));y=x@np.array([.2,.1,0.,-.1])+random.normal(0,.01,120)
    pipe=Pipe();r._elastic_worker(pipe,'predictor','elastic',x,y,None,None,[],['a','b','c','d'],None)
    assert pipe.messages[0]==('FIT_START','PREDICTOR_SAME_OBJECTIVE_EXTENDED_SOLVER')
    assert pipe.messages[1][0]=='RESULT' and pipe.closed
    model=pipe.messages[1][1]
    assert model.max_iter==25000 and model.tol==1e-5 and model.alpha==.0001 and model.l1_ratio==.35
    assert pipe.messages[1][2]['solver_only_change'] is True


def test_elastic_private_namespace_configuration_is_honest(setup):
    run,_,_,spec,pf,scope=setup;fr=r.ref(run/r.FREEZE)
    module=r._elastic_namespace(run,scope,spec,pf,fr)
    assert r.ELASTIC_CONFIGURATION in module.fit_one.__code__.co_consts
    assert 'UNCHANGED_STATEFUL_WORKER_FACTORY_WITH_RIDGE_ALPHA1_OVERRIDE' not in module.fit_one.__code__.co_consts
    assert module.source_pins()==r.predictors.source_pins()
    with pytest.raises(ValueError,match='EXACT_ELASTIC'):module.contract(run,'ridge',2021,5)


def test_missing_recovered_member_does_not_shrink_packet(setup):
    run,parent,reader,_,pf,scope=setup
    with pytest.raises(r.fusion.PacketUnavailable,match='MISSING_RECOVERED_MEMBER'):
        r._recovery_publication(run,scope,pf,parent,r.ref(run/r.FREEZE),dict(model_id='ebm',horizon=5),2023,reader)


def test_recovered_ebm_publication_reuse_and_fusion_reader(setup,monkeypatch):
    run,parent,reader,_,pf,scope=setup;year=2023
    old=parent/'models/consensus_predictors/ebm/5d/2023/receipt.json'
    write(old,dict(status='FAILED',reuse_tuple=dict(year=year,calibration_maturity_exclusive=str(pd.Timestamp('2023-01-01')))))
    model=run/'synthetic_ebm.model';model.write_bytes(b'SYNTHETIC_MODEL_NOT_DECODED')
    calibration=run/'synthetic_ebm.calibration';calibration.write_bytes(b'SYNTHETIC_CALIBRATION_NOT_DECODED')
    reuse=dict(original_failed_receipt_ref=r.ref(old),dependency_paths=[])
    fit=dict(status='TRAINED',model_id='ebm',year=year,horizon=5,source_pins=r.predictors.source_pins(),
        test_2026_rows_read=0,model_ref=r.ref(model),calibration_ref=r.ref(calibration),
        reuse_tuple=reuse,reuse_tuple_sha256=r.values.digest(reuse))
    receipt=run/'synthetic_ebm_receipt.json';write(receipt,fit);fit_ref=r.ref(receipt)
    summary=Path(scope['ebm_summary_ref']['path'])
    write(summary,dict(schema='CONSENSUS_EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1',original_failures_preserved=True,
        slots=[dict(slot=dict(model_id='ebm',year=year,horizon=5),status='TRAINED',receipt_ref=fit_ref)]))
    scope['ebm_summary_ref']=r.ref(summary);write(run/r.FREEZE,scope)
    def predict(frame,actual_reader):
        assert actual_reader is reader
        out=frame[['signal_date','ticker']].copy();out['prediction']=.04;return out
    fitted=SimpleNamespace(predict_frame=predict)
    loads=[]
    monkeypatch.setattr(r.values,'_native',lambda deps:None)
    monkeypatch.setattr(r.joblib,'load',lambda path:loads.append(path) or fitted)
    monkeypatch.setattr(r,'write_json_atomic',write)
    publication=r.publish_recovered_ebm(run,year,reader)
    assert publication['status']=='PUBLISHED' and publication['fit_units']==0
    assert publication['test_2026_rows_read']==0 and len(loads)==1
    assert r.publish_recovered_ebm(run,year,reader)==publication and len(loads)==1
    forecasts,pins=r._recovery_publication(run,scope,pf,parent,r.ref(run/r.FREEZE),dict(model_id='ebm',horizon=5),year,reader)
    assert forecasts['expert_ebm_5d'].notna().sum()==24
    assert forecasts.loc[forecasts.ticker.eq('MISSING'),'expert_ebm_5d'].isna().all()
    assert pins['fit_receipt_sha256']==fit_ref['sha256']

