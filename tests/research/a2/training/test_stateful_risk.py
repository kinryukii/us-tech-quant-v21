"""Synthetic static-risk bindings and actual spawned worker ACKs only."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_risk as r
from scripts.research.a2.training import stateful_values as v


def fake_reader():
    calendar=pd.bdate_range('2022-09-01','2023-01-06')
    flags=pd.DataFrame({'signal_date':pd.to_datetime(['2022-09-02','2022-09-02','2023-01-03']),
        'ticker':['pastA','pastB','futureC'],'feature_available':[True]*3,
        'feature_source':[r.ALLOWED_SOURCES[0]]*3,'label_available':[False]*3,
        'y_open5':[np.inf]*3})
    calls=[]
    def history(names,decision,lookback):
        calls.append((tuple(names),pd.Timestamp(decision),lookback))
        dates=calendar[calendar<=decision][-lookback:]
        index=pd.MultiIndex.from_product([dates,names],names=['signal_date','ticker'])
        out=index.to_frame(index=False);out['ret_1d']=np.arange(len(out),dtype=float)/10000.;out['return_available']=True
        return out
    return SimpleNamespace(calendar=calendar,train_flags=flags,read_return_history=history),calls


def test_history_members_past_only_labels_unused_exact63():
    reader,calls=fake_reader();table,line=r.annual_inputs(reader,2023)
    assert tuple(table.columns)==('pastA','pastB') and len(table)==63
    assert table.index.max()<pd.Timestamp('2023-01-01')
    assert calls==[(('pastA','pastB'),table.index.max(),63)]
    assert line['labels_used'] is False and line['future_membership_used'] is False
    assert line['return_horizon_sessions']==1 and line['window_sessions']==63


def test_missing_calendar_sessions_fail_before_any_return_read():
    reader,calls=fake_reader();reader.calendar=reader.calendar[-10:]
    with pytest.raises(ValueError,match='EXACT63'):
        r.annual_inputs(reader,2023)
    assert calls==[]


def synthetic_table():
    rng=np.random.default_rng(20260928);dates=pd.bdate_range('2022-10-03',periods=63)
    common=rng.normal(0,.005,(63,1));independent=rng.normal(0,.008,(63,6))
    return pd.DataFrame(common+independent,index=dates,columns=[f's{i}' for i in range(6)])


@pytest.mark.parametrize('method,count',[('DIAG',0),('LW',1),('PCA',1),('COV_ENSEMBLE',2),('GARCH',2)])
def test_actual_array_worker_callbacks_and_daily_units(method,count,tmp_path,monkeypatch):
    events=[]
    def started(log,auth,prior,model_id,year,component,tuple_sha):events.append((model_id,component))
    monkeypatch.setattr(v,'_component_start',started)
    def writer(path,data):
        assert isinstance(path,Path) and path.is_relative_to(tmp_path)
        path.write_text(json.dumps(data),encoding='utf-8')
    monkeypatch.setattr(v,'write_json_atomic',writer)
    table=synthetic_table();payload={'worker_source_sha256':v.sha(r.__file__),
        'params':{'fit_cutoff':'2023-01-01','return_unit':r.UNIT,'return_horizon_sessions':1,
            'source_id':'SYNTHETIC_ONLY','information_set_id':'SYNTHETIC_ONLY'}}
    receipt={'receipt_path':str(tmp_path/'synthetic_receipt.json'),'fit_units':0}
    bundle=v._fit_job('risk','RISK::'+method,table,payload,table.index.to_numpy(),None,[],list(table.columns),None,
        log=tmp_path/'unused_log',auth={'max_fit_units':882},prior=18,year=2023,tuple_sha='synthetic',receipt=receipt,worker_target=r.risk_worker)
    meta=receipt['physical_fit_metadata'][-1]['metadata']
    assert receipt['fit_units']==count==len(events)==meta['actual_fit_count']
    assert all(c.startswith('RISK::') for _,c in events)
    assert bundle.status=='FITTED' and len(bundle.fitted_dates)==63
    assert bundle.fitted_state['return_unit']==r.UNIT and bundle.fitted_state['return_horizon_sessions']==1
    daily,details=r.joint.risk_matrix(bundle,['s0','s2'],return_metadata=True)
    assert np.isfinite(daily).all() and np.linalg.eigvalsh(daily).min()>=-1e-12
    if method=='DIAG':
        expected=table[['s0','s2']].var(ddof=1).to_numpy()
        assert np.allclose(np.diag(daily),expected) and daily[0,1]==0
    assert details['strategy_eligibility_upgraded'] is False and sum(e['estimate_units'] for e in meta['risk_estimates'])<=6
    assert not (tmp_path/'unused_log').exists()


def test_parent_budget_denial_prevents_actual_LW_fit(tmp_path,monkeypatch):
    def denied(*args):raise RuntimeError('RISK_BUCKET_EXHAUSTED_BEFORE_ACK')
    monkeypatch.setattr(v,'_component_start',denied)
    table=synthetic_table();payload={'worker_source_sha256':v.sha(r.__file__),
        'params':{'fit_cutoff':'2023-01-01','return_unit':r.UNIT,'return_horizon_sessions':1}}
    receipt={'receipt_path':str(tmp_path/'no_receipt.json'),'fit_units':0}
    with pytest.raises(RuntimeError,match='RISK_BUCKET_EXHAUSTED_BEFORE_ACK'):
        v._fit_job('risk','RISK::LW',table,payload,table.index.to_numpy(),None,[],list(table.columns),None,
            log=tmp_path/'unused_log',auth={'max_fit_units':882},prior=18,year=2023,tuple_sha='synthetic',receipt=receipt,worker_target=r.risk_worker)
    assert receipt['fit_units']==0 and not (tmp_path/'no_receipt.json').exists()


def test_actual_component_start_bucket72_before_ack(monkeypatch):
    events=[dict(event='FIT_STARTED',fit_units=1,budget_bucket='risk_primary') for _ in range(71)]
    events += [dict(event='FIT_STARTED',fit_units=1,budget_bucket='value_meta_primary') for _ in range(8)]
    monkeypatch.setattr(v,'_events',lambda path:list(events))
    monkeypatch.setattr(v,'_append',lambda path,event:events.append(event))
    auth={'max_fit_units':882,'budget_bucket':'risk_primary','max_new_bucket_fit_units':72}
    v._component_start(None,auth,18,'RISK::LW',2023,'RISK::LedoitWolf','SYNTHETIC_ONLY')
    assert events[-1]['budget_bucket']=='risk_primary' and events[-1]['fit_units']==1
    before=list(events)
    with pytest.raises(RuntimeError,match='FROZEN_FIT_BUCKET_EXHAUSTED'):
        v._component_start(None,auth,18,'RISK::OAS',2023,'RISK::OAS','SYNTHETIC_ONLY')
    assert events==before


def synthetic_frozen_run(tmp_path,monkeypatch):
    from scripts.research.a2.training import stateful_fusion as f
    run=tmp_path.resolve();(run/'logs').mkdir()
    (run/'input_manifest.json').write_text('{"synthetic_only":true}',encoding='utf-8')
    value_schedule=[{'model_id':f'SYNTHETIC_VALUE_{i}','year':year} for i in range(31) for year in r.YEARS]
    fusion_schedule=[{'model_id':method,'year':year} for method in f.METHODS.values() for year in r.YEARS]
    cfg={'strategy_version':'V24','training_cutoff_exclusive':'2026-01-01','prior_cumulative_fit_units':18,
         'research_design':{'risk_design_correction_before_first_fit':True},
         'value_training':{'ordered_schedule':value_schedule},'fusion_training':{'ordered_schedule':fusion_schedule}}
    pins=dict(module_sha256=v.sha(r.__file__),joint_source_sha256=v.sha(r.JOINT_PATH),
        values_module_sha256=v.sha(v.__file__),input_reader_sha256=v.sha(v.READER_SOURCE),
        input_manifest_sha256=v.sha(run/'input_manifest.json'),garch_definition_source_sha256=v.sha(r.GARCH_PATH))
    cfg['risk_training']=dict(pins,status='FROZEN',methods=list(r.METHODS),years=list(r.YEARS),
        lookback_sessions=63,horizon_multiplier=5,horizon_rule='IID_5_X_STATIC_DAILY_COV',fit_timeout_seconds=1800,
        budget_bucket='risk_primary',max_new_bucket_fit_units=72,max_fit_units=882,max_model_year_attempts=201)
    (run/'run_config.json').write_text(json.dumps(cfg),encoding='utf-8')
    (run/'logs/value_batch_status.json').write_text(json.dumps(dict(status='ATTEMPTS_FINISHED',expected_slots=93,
        slots=[dict(item,status='TRAINED') for item in value_schedule])),encoding='utf-8')
    progress=dict(status='ATTEMPTS_FINISHED',expected_slots=39,slots=[dict(item,status='TRAINED') for item in fusion_schedule])
    (run/'logs/fusion_batch_status.json').write_text(json.dumps(progress),encoding='utf-8')
    def no_external_write(path,purpose):assert Path(path).resolve().is_relative_to(run)
    monkeypatch.setattr(r,'assert_write_path',no_external_write)
    return run,cfg,progress


def test_serial_gate_exact_identity_and_no_outstanding(tmp_path,monkeypatch):
    run,cfg,progress=synthetic_frozen_run(tmp_path,monkeypatch)
    monkeypatch.setattr(v,'_events',lambda path:[])
    assert r.frozen_contract(run,'DIAG',2023)[-1]=='DIAG'
    events=[dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id='SYNTHETIC_UNFINISHED',year=2023)]
    monkeypatch.setattr(v,'_events',lambda path:events)
    with pytest.raises(RuntimeError,match='STILL_RUNNING'):
        r.frozen_contract(run,'DIAG',2023)
    events.append(dict(event='MODEL_YEAR_FAILED',model_id='SYNTHETIC_UNFINISHED',year=2023))
    progress['slots'][1]=dict(progress['slots'][0])
    (run/'logs/fusion_batch_status.json').write_text(json.dumps(progress),encoding='utf-8')
    with pytest.raises(ValueError,match='EXACT_SERIAL_FUSION39'):
        r.frozen_contract(run,'DIAG',2023)


def test_serial_gate_completed_fusion_error_is_not_qualified(tmp_path,monkeypatch):
    run,cfg,progress=synthetic_frozen_run(tmp_path,monkeypatch)
    monkeypatch.setattr(v,'_events',lambda path:[])
    progress['slots'][0]['status']='ERROR'
    progress['slots'][0]['failure']={'message':'SYNTHETIC_MISSING_EXPERT'}
    (run/'logs/fusion_batch_status.json').write_text(json.dumps(progress),encoding='utf-8')
    assert r.frozen_contract(run,'DIAG',2023)[-1]=='DIAG'
    assert progress['slots'][0]['status']=='ERROR' and 'scientific_feature_pit_qualified' not in progress['slots'][0]


def synthetic_diag_alias(tmp_path,monkeypatch):
    run=tmp_path.resolve();pins={'SYNTHETIC_ONLY':'same_source_identity'}
    class FakeReader:
        def __init__(self):self.run=run
    monkeypatch.setattr(r,'InputReader',FakeReader)
    monkeypatch.setattr(r,'frozen_contract',lambda run_dir,method,year:(run,{}, {},pins,method))
    events=[]
    monkeypatch.setattr(v,'_append',lambda path,event:events.append(event))
    def writer(path,data):
        assert Path(path).resolve().is_relative_to(run)
        Path(path).write_text(json.dumps(data),encoding='utf-8')
    monkeypatch.setattr(r,'write_json_atomic',writer)
    slot=run/'models/risk/DIAG/2023';slot.mkdir(parents=True)
    model=slot/'risk.joblib';r.joblib.dump(SimpleNamespace(method_id='DIAG',status='FITTED'),model)
    tup=dict(method='DIAG',year=2023,role=r.ROLE,source_pins=pins,specification=r.joint.specs('DIAG'),
        cutoff_exclusive='2023-01-01',return_unit=r.UNIT,return_horizon_sessions=1,
        horizon_rule='IID_5_X_STATIC_DAILY_COV',window_sessions=63,annual_static=True,seed=20260928,
        input_lineage={'synthetic_only':True})
    prior=dict(status='FITTED',method_id='DIAG',year=2023,role=r.ROLE,model_path=str(model),model_sha256=v.sha(model),
        scientific_feature_pit_qualified=True,scientific_return_proxy_qualified=True,reuse_tuple=tup,reuse_tuple_sha256=v.digest(tup))
    receipt=slot/'fit_receipt.json';writer(receipt,prior)
    return run,FakeReader(),events,receipt,prior


def test_histvol_exact_alias_is_idempotent_no_new_attempt(tmp_path,monkeypatch):
    run,reader,events,canonical,prior=synthetic_diag_alias(tmp_path,monkeypatch)
    bundle,receipt=r.fit_annual('HISTVOL',2023,run,reader)
    assert bundle.method_id=='DIAG' and receipt['status']=='EXACT_METHOD_REUSED' and receipt['fit_units']==0
    assert receipt['scientific_feature_pit_qualified'] is True
    assert receipt['source_receipt_sha256']==v.sha(canonical)
    r.fit_annual('HISTVOL',2023,run,reader)
    assert len(events)==1 and events[0]['event']=='RISK_METHOD_EXACT_REUSED'
    assert not any(e['event']=='MODEL_YEAR_ATTEMPT_STARTED' for e in events)


def test_histvol_alias_rejects_wrong_canonical_cutoff(tmp_path,monkeypatch):
    run,reader,events,canonical,prior=synthetic_diag_alias(tmp_path,monkeypatch)
    prior['reuse_tuple']['cutoff_exclusive']='2024-01-01'
    prior['reuse_tuple_sha256']=v.digest(prior['reuse_tuple'])
    canonical.write_text(json.dumps(prior),encoding='utf-8')
    with pytest.raises(RuntimeError,match='HISTVOL_'):
        r.fit_annual('HISTVOL',2023,run,reader)
    assert events==[]
