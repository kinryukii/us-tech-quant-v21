"""Synthetic-only add-on identity, causal-year, IPC and shared-budget acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import consensus_forecast_completion as c

_spec=importlib.util.spec_from_file_location('_forecast_completion_recovery_fixture',Path(__file__).with_name('test_consensus_forecast_recovery.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
write=_fixture.write


def original_receipts(scope):
    return {e['original_failure_ref']['path']:Path(e['original_failure_ref']['path']).read_bytes() for e in scope['original_failures']}


@pytest.fixture
def setup(tmp_path,monkeypatch):
    run,parent,reader,spec,pf,recovery_scope=_fixture.setup.__wrapped__(tmp_path,monkeypatch)
    monkeypatch.setattr(c,'assert_safe_output_path',lambda *a,**k:None)
    monkeypatch.setattr(c,'write_json_atomic',write)
    base=c.recovery.bind_fusion(run)
    monkeypatch.setattr(base,'write_json_atomic',write)
    base.publication=lambda actual,member,year,reader:_fixture._publication(reader,member,year)
    def ipc_failure(*args,**kwargs):
        lost=2 if args[1]=='stack_ridge' else 1
        for i in range(lost):
            c.values._component_start(kwargs['log'],kwargs['auth'],2063,args[1],kwargs['year'],
                'SYNTHETIC_ORIGINAL_IPC_ATTEMPT_'+str(i),kwargs['tuple_sha'])
            kwargs['receipt']['fit_units']+=1
        raise ModuleNotFoundError("No module named 'common'")
    with monkeypatch.context() as local:
        local.setattr(c.values,'_fit_job',ipc_failure)
        for packet,method,_,_ in c.RETRIES:
            receipt=base.fit_one(run,packet,method,2023,reader)
            assert receipt['status']=='FAILED'
    entries=[]
    for slot in recovery_scope['ordered_fusion_slots']:
        _,rp,_=c.fusion.slot_paths(run,slot['packet_id'],slot['method'],slot['year'])
        if not rp.exists():write(rp,dict(status='NOT_TESTABLE',packet_id=slot['packet_id'],model_id=slot['method'],
            year=slot['year'],fit_units=0,reason='SYNTHETIC_METADATA_TERMINAL'))
        receipt=c.metadata(rp)
        entries.append(dict(slot=slot,status=receipt['status'],receipt_ref=c.ref(rp),publication_ref=None))
    summary=run/'FORECAST_RECOVERY_ACTUAL_SUMMARY.json'
    write(summary,dict(schema='CONSENSUS_FORECAST_RECOVERY_ACTUAL_SUMMARY_R12',freeze_ref=c.ref(run/c.recovery.FREEZE),
        fusion_slots=entries,test_2026_rows_read=0,original_failures_preserved=True))
    status=run/'FORECAST_RECOVERY_PROCESS_STATUS.json'
    write(status,dict(status='PLAN_TERMINAL_CHECK_RECEIPTS',pid=12345,summary_ref=c.ref(summary),
        prior_fit_units=2063,max_new_fit_units=75,fit_failures_not_subtracted=True,test2026_rows_read=0))
    terminal=run/'FORECAST_RECOVERY_TERMINAL_CUSTODY.json'
    custody=c.stage_terminal_template(run,c.ref(summary),12345)
    custody.update(status='TERMINAL',original_stage_process_stopped=True);write(terminal,custody)
    scope=c.freeze_template(run,recovery_scope['root_scope_ref'],stage_terminal_ref=c.ref(terminal))
    scope['status']=c.GATE;write(run/c.FREEZE,scope)
    admission=c.admission_template(run);admission['status']=c.REVIEW;write(run/c.ADMISSION,admission)
    monkeypatch.setattr(c.recovery,'bind_fusion',lambda actual:base)
    module=c.bind_fusion(run);monkeypatch.setattr(module,'write_json_atomic',write)
    return SimpleNamespace(run=run,parent=parent,reader=reader,spec=spec,scope=scope,terminal=terminal,module=module,
        old=original_receipts(scope),recovery_freeze=c.ref(run/c.recovery.FREEZE))


def test_exact_three_retries_and_nine_causal_upstream_slots_without_original_cap_or_identity_change(setup):
    s=setup
    assert len(s.scope['ordered_slots'])==12
    retries=s.scope['ordered_slots'][:3];upstream=s.scope['ordered_slots'][3:]
    assert sum(x['max_new_fit_units'] for x in retries)==7
    assert sum(x['max_new_fit_units'] for x in upstream)==15
    assert {x['year'] for x in retries}=={2023} and {x['year'] for x in upstream}=={2022}
    assert s.scope['causal_upstream']['rl_reward_training_years']==[2022]
    assert s.scope['original_phase_max_new_fit_units']==75 and s.scope['prior_fit_units']==2063
    assert sum(x['original_spent_fit_units'] for x in s.scope['original_failures'])==4
    assert c.metadata_preflight(s.run)['numeric_inputs_read'] is False
    assert c.ref(s.run/c.recovery.FREEZE)==s.recovery_freeze
    for path,content in s.old.items():assert Path(path).read_bytes()==content


@pytest.mark.parametrize('field,value',[('max_new_fit_units',23),('prior_fit_units',0),('upstream_fit_units_upper',16),
    ('test_2026_read_authorized',True),('confirmation_read_authorized',True)])
def test_scope_drift_rejects_before_numeric_inputs(setup,monkeypatch,field,value):
    s=setup;scope=copy.deepcopy(s.scope);scope[field]=value;write(s.run/c.FREEZE,scope)
    monkeypatch.setattr(s.module,'training_packet',lambda *a:pytest.fail('numeric input read'))
    with pytest.raises(ValueError,match='FROZEN_SCOPE_CHANGED'):c.contract(s.run)


def test_proposed_template_and_independent_admission_do_not_authorize_fit(setup):
    s=setup;scope=copy.deepcopy(s.scope);scope['status']='PROPOSED';write(s.run/c.FREEZE,scope)
    assert c.metadata_preflight(s.run)['status']=='PASS_METADATA_ONLY'
    with pytest.raises(ValueError,match='ROOT_COMPLETION'):c.bind_fusion(s.run)
    write(s.run/c.FREEZE,s.scope)
    admission=c.metadata(s.run/c.ADMISSION);admission['freeze_ref']['sha256']='0'*64;write(s.run/c.ADMISSION,admission)
    with pytest.raises(ValueError,match='INDEPENDENT_METADATA_ADMISSION'):c.bind_fusion(s.run)


@pytest.mark.parametrize('defect',['running','missing_slot','receipt_status','prefix','missing_lost_count','process_alive'])
def test_original_stage_terminal_requires_exact_status_40_receipts_and_immutable_counted_prefix(setup,defect):
    s=setup;custody=c.metadata(s.terminal)
    if defect=='running':
        path=s.run/'FORECAST_RECOVERY_PROCESS_STATUS.json';value=c.metadata(path);value['status']='RUNNING';write(path,value)
        custody['original_process_status_ref']=c.ref(path)
    elif defect=='missing_slot':
        path=s.run/'FORECAST_RECOVERY_ACTUAL_SUMMARY.json';value=c.metadata(path);value['fusion_slots'].pop();write(path,value)
        custody['original_summary_ref']=c.ref(path)
        status=s.run/'FORECAST_RECOVERY_PROCESS_STATUS.json';value=c.metadata(status);value['summary_ref']=c.ref(path);write(status,value)
        custody['original_process_status_ref']=c.ref(status)
    elif defect=='receipt_status':
        summary=c.metadata(s.run/'FORECAST_RECOVERY_ACTUAL_SUMMARY.json')
        entry=next(x for x in summary['fusion_slots'] if x['status']=='NOT_TESTABLE')
        path=Path(entry['receipt_ref']['path']);value=c.metadata(path);value['status']='IN_PROGRESS';write(path,value)
        entry['receipt_ref']=c.ref(path);summary_path=s.run/'FORECAST_RECOVERY_ACTUAL_SUMMARY.json';write(summary_path,summary)
        custody['original_summary_ref']=c.ref(summary_path)
        status=s.run/'FORECAST_RECOVERY_PROCESS_STATUS.json';value=c.metadata(status);value['summary_ref']=c.ref(summary_path);write(status,value)
        custody['original_process_status_ref']=c.ref(status)
    elif defect=='prefix':
        log=s.run/'FIT_LOG.jsonl';content=log.read_bytes();log.write_bytes(content.replace(b'SYNTHETIC_ORIGINAL_IPC_ATTEMPT_0',b'SYNTHETIC_ORIGINAL_IPC_ATTEMPT_9',1))
    elif defect=='missing_lost_count':
        log=s.run/'FIT_LOG.jsonl';events=list(c.values._events(log));next(e for e in events if e['event']=='FIT_STARTED')['reuse_tuple_sha256']='FAKE_TOKEN'
        log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
        custody['fit_log_prefix']=c._prefix_facts(log,log.stat().st_size)[0]
    else:custody['original_stage_process_stopped']=False
    write(s.terminal,custody)
    scope=copy.deepcopy(s.scope);scope['stage_terminal_ref']=c.ref(s.terminal);write(s.run/c.FREEZE,scope)
    with pytest.raises(ValueError):c.contract(s.run,authorized=False)


def test_shared_fit_lock_blocks_even_with_terminal_original_phase(setup):
    s=setup;write(s.run/'CONSENSUS_FIT.lock',dict(pid=999))
    with pytest.raises(ValueError,match='SHARED_FIT_OWNER_ACTIVE'):c.bind_fusion(s.run)


def test_retry_changed_original_train_or_calibration_hash_fails_before_fit(setup,monkeypatch):
    s=setup;original=s.module._original_training_packet
    def changed(*args):
        result=list(original(*args));result[1]=result[1].copy();result[1].loc[0,'y_open5']+=.001
        return tuple(result)
    monkeypatch.setattr(s.module,'_original_training_packet',changed)
    monkeypatch.setattr(c.values,'_fit_job',lambda *a,**k:pytest.fail('must reject changed training rows before worker'))
    with pytest.raises(ValueError,match='ORIGINAL_RETRY_TRAIN_CAL_RECIPE'):
        s.module.fit_one(s.run,'broad29','convex',2023,s.reader)
    assert c.ref(s.run/c.recovery.FREEZE)==s.recovery_freeze
    for path,content in s.old.items():assert Path(path).read_bytes()==content


def test_2022_original_packet_proves_2021_only_and_never_reads_2023_weights(setup,monkeypatch):
    s=setup;read_years=[];original=s.module.publication
    def publication(actual,member,year,reader):
        assert year==2021;read_years.append(year);return original(actual,member,year,reader)
    monkeypatch.setattr(s.module,'publication',publication)
    slot=next(x for x in s.scope['ordered_slots'] if x['packet_id']=='core5' and x['method']=='equal' and x['year']==2022)
    packet=s.module.training_packet(s.run,slot,2022,s.reader)
    assert read_years and {p['year'] for p in packet[-1]}=={2021}
    proof=c.metadata(s.run/'derived/consensus_forecast_completion_input_proofs/core5/equal/2022.json')
    assert proof['all_fitting_labels_before']=='2022-01-01' and proof['input_oof_years']==[2021]
    assert pd.Timestamp(proof['actual_max_calibration_label_mature'])<pd.Timestamp('2022-01-01')
    assert len(proof['calibration_sessions'])==60


def test_new_failed_addon_tuple_is_retained_and_never_automatically_retried(setup,monkeypatch):
    s=setup;calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        c.values._component_start(kwargs['log'],kwargs['auth'],kwargs['prior'],args[1],kwargs['year'],
            'SYNTHETIC_NEW_FAILED_ATTEMPT',kwargs['tuple_sha'])
        kwargs['receipt']['fit_units']+=1
        raise RuntimeError('SYNTHETIC_NEW_FAILURE_NO_AUTOMATIC_RETRY')
    monkeypatch.setattr(c.values,'_fit_job',fail)
    first=s.module.fit_one(s.run,'broad29','convex',2023,s.reader)
    assert first['status']=='FAILED' and first['fit_units']==1
    second=s.module.fit_one(s.run,'broad29','convex',2023,s.reader)
    assert second==first and len(calls)==1
    assert sum(e.get('fit_units',0) for e in c.values._events(s.run/'FIT_LOG.jsonl') if e['event']=='FIT_STARTED')==5
    for path,content in s.old.items():assert Path(path).read_bytes()==content


def test_component_budget_includes_original_four_losses_and_per_slot_upper_bound(setup):
    s=setup;_,rp,_=s.module.slot_paths(s.run,'broad29','convex',2023)
    write(rp,dict(reuse_tuple_sha256='SYNTHETIC_NEW_TOKEN'))
    auth=dict(max_fit_units=10000,budget_bucket='old_bucket')
    for _ in range(2):s.module.values._component_start(s.run/'FIT_LOG.jsonl',auth,0,'convex',2023,'SYNTHETIC', 'SYNTHETIC_NEW_TOKEN')
    with pytest.raises(RuntimeError,match='FROZEN_FIT_BUCKET_EXHAUSTED'):
        s.module.values._component_start(s.run/'FIT_LOG.jsonl',auth,0,'convex',2023,'SYNTHETIC','SYNTHETIC_NEW_TOKEN')
    for i in range(20):c.values._append(s.run/'FIT_LOG.jsonl',dict(event='FIT_STARTED',fit_units=1,reuse_tuple_sha256='OTHER_'+str(i)))
    with pytest.raises(RuntimeError,match='CUMULATIVE_FIT_BUDGET_EXHAUSTED'):
        s.module.values._component_start(s.run/'FIT_LOG.jsonl',auth,0,'convex',2023,'SYNTHETIC','SYNTHETIC_NEW_TOKEN')


def test_original_existing_publication_cannot_be_overwritten_by_addon(setup):
    s=setup;output=s.run/'predictions/consensus_fusion/broad29/convex/2023.parquet'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b'IMMUTABLE_ORIGINAL')
    write(output.with_suffix('.receipt.json'),dict(fit_receipt_path='ORIGINAL',source_pins={}))
    with pytest.raises(ValueError,match='EXISTING_ORIGINAL_PUBLICATION'):
        s.module.predict_one(s.run,'broad29','convex',2023,s.reader)
    assert output.read_bytes()==b'IMMUTABLE_ORIGINAL'


def test_fresh_namespace_retains_original_fit_predict_and_packet_business_code(setup):
    s=setup
    assert s.module.ConsensusFusion is not c.fusion.ConsensusFusion
    assert s.module.fit_one.__code__.co_code==c.fusion.fit_one.__code__.co_code
    assert s.module.predict_one.__code__.co_code==c.fusion.predict_one.__code__.co_code
    assert s.module._original_training_packet.__code__.co_code==c.fusion.training_packet.__code__.co_code
    assert s.module.ConsensusFusion.predict_frame.__code__.co_code==c.fusion.ConsensusFusion.predict_frame.__code__.co_code
    assert c.bind_fusion(s.run) is s.module
    with pytest.raises(ValueError,match='UNPLANNED_COMPLETION_SLOT'):s.module.contract(s.run,'core5','stack_ridge',2022)


def test_native_parent_is_primed_before_real_synthetic_ipc_and_publication_routes_addon(setup,monkeypatch):
    s=setup;events=[];original_native=c.fusion.owner._native;original_job=c.values._fit_job
    def native(dependencies=()):events.append('parent_native');return original_native(dependencies)
    def job(*args,**kwargs):
        assert events[-1]=='parent_native';events.append('canonical_ipc');return original_job(*args,**kwargs)
    monkeypatch.setattr(c.fusion.owner,'_native',native);monkeypatch.setattr(c.values,'_fit_job',job)
    result=s.module.predict_one(s.run,'broad29','convex',2023,s.reader)
    assert result['status']=='PUBLISHED',result
    assert result['fit_receipt_path']==str(s.module.slot_paths(s.run,'broad29','convex',2023)[1])
    assert 'canonical_ipc' in events
    frame,pin=c.published_fusion_forecasts(s.run,'convex',2023,s.reader,packet_id='broad29')
    assert pin['completion_route']==c.SCHEMA and frame.prediction_qualified.sum()==24
    assert result['source_pins']==c.source_pins()
    assert sum(e.get('fit_units',0) for e in c.values._events(s.run/'FIT_LOG.jsonl') if e['event']=='FIT_STARTED')==6
    for path,content in s.old.items():assert Path(path).read_bytes()==content
    assert c.ref(s.run/c.recovery.FREEZE)==s.recovery_freeze


def test_2022_equal_original_model_and_publication_keep_original_sigma_and_pre2022_proof(setup):
    s=setup
    result=s.module.predict_one(s.run,'core5','equal',2022,s.reader)
    assert result['status']=='PUBLISHED',result
    frame,pin=c.published_fusion_forecasts(s.run,'equal',2022,s.reader,packet_id='core5')
    assert frame.year.eq(2022).all() and frame.prediction_qualified.sum()==24
    assert pin['completion_route']==c.SCHEMA
    proof=c.metadata(s.run/'derived/consensus_forecast_completion_input_proofs/core5/equal/2022.json')
    assert proof['all_fitting_labels_before']=='2022-01-01'
    fitted=s.module.fit_one(s.run,'core5','equal',2022,s.reader)
    slot=next(x for x in s.scope['ordered_slots'] if (x['packet_id'],x['method'],x['year'])==('core5','equal',2022))
    _,_,cal,_,cx,_,state,_=s.module.training_packet(s.run,slot,2022,s.reader)
    assert fitted.sigma==pytest.approx(np.std(cal.y_open5.to_numpy()-fitted.native.predict(cx,state),ddof=1))


def test_nonaddon_publication_routes_original_and_future_or_unplanned_2022_fails_early(monkeypatch):
    calls=[]
    monkeypatch.setattr(c.recovery,'published_fusion_forecasts',lambda *a,**k:calls.append((a,k)) or ('ORIGINAL','PIN'))
    assert c.published_fusion_forecasts('unused','equal',2024)==('ORIGINAL','PIN') and len(calls)==1
    monkeypatch.setattr(c,'contract',lambda *a,**k:pytest.fail('future must reject before any source/model'))
    with pytest.raises(ValueError,match='2026'):c.published_fusion_forecasts('unused','equal',2026)
    with pytest.raises(ValueError,match='UNPLANNED_2022'):c.published_fusion_forecasts('unused','median',2022)



def test_2022_boundary_label_is_rejected_before_any_new_worker_or_proof_write(setup,monkeypatch):
    s=setup;original=s.module._original_training_packet
    def future_label(*args):
        result=list(original(*args));result[2]=result[2].copy()
        result[2].loc[0,'label_mature_date']=pd.Timestamp('2022-01-01')
        return tuple(result)
    monkeypatch.setattr(s.module,'_original_training_packet',future_label)
    monkeypatch.setattr(c.values,'_fit_job',lambda *a,**k:pytest.fail('future label reached worker'))
    with pytest.raises(ValueError,match='CAUSAL_PRIOR_OOF_SIGNALS_AND_ALL_FITTING_LABELS'):
        s.module.fit_one(s.run,'core5','equal',2022,s.reader)
    assert not (s.run/'derived/consensus_forecast_completion_input_proofs/core5/equal/2022.json').exists()
    assert sum(e.get('fit_units',0) for e in c.values._events(s.run/'FIT_LOG.jsonl') if e['event']=='FIT_STARTED')==4
