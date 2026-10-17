"""Synthetic-only R2 controller bindings; no research/financial file readers."""
from datetime import date,timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from scripts.research.a2.training import stateful_execution as execution
from scripts.research.a2.training import stateful_completion as completion


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')
    return dict(path=str(path),sha256=execution.values.sha(path))


def journal(path,events):
    path.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')


def friction(bps):
    return dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE',scenario_id='S'+str(bps),one_way_bps=bps,
        fee_bps=0,benchmark='NEXT_RAW_OPEN',authority='HYPOTHETICAL_RESEARCH_SCENARIO')


@pytest.fixture
def bound(tmp_path,monkeypatch):
    run=tmp_path/'new';parent=tmp_path/'old';run.mkdir();parent.mkdir()
    monkeypatch.setattr(execution,'assert_write_path',lambda *args,**kw:None)
    monkeypatch.setattr(execution,'write_json_atomic',lambda path,value:write(path,value))
    monkeypatch.setattr(execution.values,'resolve',lambda *args:SimpleNamespace(backtest_root=tmp_path))
    keys=('module_sha256','replay_module_sha256','joint_risk_source_sha256','input_reader_sha256',
          'values_module_sha256','metadata_reader_sha256','corporate_transition_source_sha256')
    sources={k:tmp_path/(k+'.py') for k in keys}
    for k,p in sources.items():p.write_text(k,encoding='utf-8')
    monkeypatch.setattr(execution,'CONTINUATION_SOURCE_PATHS',sources)
    pins={k:execution.values.sha(p) for k,p in sources.items()}
    features=['f'+str(i) for i in range(32)]
    monkeypatch.setattr(execution.values,'feature_binding',lambda:dict(features=features))
    folds={}
    for year in execution.YEARS:
        start=date(year-1,9,1);sessions=[(start+timedelta(days=i)).isoformat()+'T00:00:00' for i in range(60)]
        folds[str(year)]=dict(calendar_sha256='c'*64,calibration_start=sessions[0],
            calibration_sessions=sessions,cutoff_exclusive=f'{year}-01-01T00:00:00')
    parent_manifest=write(parent/'input_manifest.json',dict(annual_folds=folds))
    value_packets={};risk_packets={}
    for method in ('ridge','hgb'):
        packet=dict(source_kind='V24_VALUE_OUTPUTS',annual={})
        for year in execution.YEARS:
            folder=parent/'models'/method/str(year);f=folds[str(year)]
            reuse=dict(fold=f'ANNUAL_{year}',label_definition=execution.values.LABEL,
                cutoff_exclusive=f['cutoff_exclusive'],calendar_sha256=f['calendar_sha256'],
                calibration_sessions=f['calibration_sessions'],feature_binding=dict(features=features),
                training_signal_and_label_maturity_exclusive=f['calibration_start'],
                calibration_label_maturity_exclusive=f['cutoff_exclusive'],
                source_pins=dict(module_sha256=pins['values_module_sha256'],input_manifest_sha256=parent_manifest['sha256']))
            receipt=dict(status='TRAINED',year=year,scientific_feature_pit_qualified=True,
                scientific_target_qualified=True,reuse_tuple=reuse,train_label_maturity_max=f'{year-1}-08-31',
                calibration_label_maturity_max=f'{year-1}-12-29',sigma=999999)
            rp=write(folder/'fit_receipt.json',receipt)
            # Opaque placeholders: controller may stat but must not read/hash them.
            pp=write(folder/'prediction.parquet',{'this_is_not_a_real_prediction':True})
            packet['annual'][str(year)]=dict(receipt=rp,prediction=pp)
        value_packets[method]=packet
    for number in range(12):
        method='RISK'+str(number);packet=dict(annual={})
        for year in execution.YEARS:
            folder=parent/'risk'/method/str(year)
            bundle=write(folder/'risk.joblib',dict(opaque=True))
            dates=[(date(year-1,9,1)+timedelta(days=i)).isoformat() for i in range(63)]
            r=dict(status='FITTED',year=year,scientific_feature_pit_qualified=True,
                scientific_return_proxy_qualified=True,model_sha256=bundle['sha256'],fitted_dates=dates,
                reuse_tuple=dict(window_sessions=63,annual_static=True,cutoff_exclusive=f'{year}-01-01',
                    return_unit='ACCEPTED_FROZEN_PIT32_RET_1D_PROXY_FRACTIONAL',
                    source_pins=dict(joint_source_sha256=pins['joint_risk_source_sha256'])))
            packet['annual'][str(year)]=dict(receipt=write(folder/'fit_receipt.json',r),bundle=bundle)
        risk_packets[method]=packet
    pcfg=dict(phase='FROZEN',strategy_version='V24',evaluation_years=[2023,2024,2025],
        training_cutoff_exclusive='2026-01-01',prior_cumulative_fit_units=18,prior_account_paths=4,
        stateful_replay=dict(value_packets=value_packets,risk_packets=risk_packets))
    write(parent/'run_config.json',pcfg)
    journal(parent/'FIT_LOG.jsonl',[dict(event='FIT_STARTED',fit_units=437)])
    old=[]
    for i in range(70):
        old += [dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='old'+str(i)),
                dict(event='ACCOUNT_PATH_FAILED' if i==0 else 'ACCOUNT_PATH_COMPLETE',candidate_id='old'+str(i))]
    journal(parent/'ACCOUNT_PATH_LOG.jsonl',old)
    candidates=[dict(candidate_id='c'+str(i),source_method_ids=['M001'],action='raw' if i==0 else 'stateful',
        value_model='ridge' if i%2==0 else 'hgb',control='none',gross='fixed',risk='diag',
        target_role='shareholder5d',scientific_tuple_sha256=f'{i:064x}',action_cost_mode='blind' if i%2==0 else 'aware',
        execution_friction=friction(10 if i==0 else (5,10,20)[i%3])) for i in range(51)]
    auth=dict(status='FROZEN',reuse_only=True,module_sha256=pins['module_sha256'],source_pins=pins,
        max_new_fit_units=72,max_new_account_paths=80,poll_seconds=5,replay_chunk_size=8,
        worker_timeout_seconds=30,expected_candidates=51,baseline_candidate_id='c0',
        diagnostic_candidate_ids=['c'+str(i) for i in range(14)],
        value_packets=value_packets,risk_packets=risk_packets,risk_module_sha256=pins['joint_risk_source_sha256'],
        risk_static_window_sessions=63,risk_return_unit='ACCEPTED_FROZEN_PIT32_RET_1D_PROXY_FRACTIONAL',
        risk_horizon_conversion='IID_1D_COVARIANCE_TIMES_5')
    for name,key in (('run_config.json','parent_run_config_sha256'),('input_manifest.json','parent_input_manifest_sha256'),
        ('FIT_LOG.jsonl','parent_fit_log_sha256'),('ACCOUNT_PATH_LOG.jsonl','parent_account_log_sha256')):
        auth[key]=execution.values.sha(parent/name)
    custody=write(run/'contracts/source_custody/stateful_execution.py',dict(old_source=True))
    auth['controller_custody_sha256']=custody['sha256']
    cp=write(run/'candidates.json',candidates);auth.update(candidates_path=cp['path'],candidates_sha256=cp['sha256'])
    gate=write(run/'preflight.json',dict(status='PASS',test_2026_rows_read=0))
    auth.update(preflight_path=gate['path'],preflight_sha256=gate['sha256'])
    manifest=write(run/'input_manifest.json',dict(inputs_verified=True,reuse_only=True,
        training_cutoff_exclusive='2026-01-01',source_reader_sha256=pins['input_reader_sha256'],
        parent_input_manifest_sha256=parent_manifest['sha256']))
    auth['input_manifest_sha256']=manifest['sha256']
    cfg=dict(phase='FROZEN',strategy_version='V24',evaluation_years=[2023,2024,2025],capital_usd=3000,
        training_cutoff_exclusive='2026-01-01',prior_cumulative_fit_units=455,prior_account_paths=74,
        parent_run_dir=str(parent),execution_continuation=auth,
        budget=dict(new_fit_units_hard_limit=72,new_account_attempts_hard_limit=80))
    write(run/'run_config.json',cfg)
    return run,parent,cfg,auth,candidates


def test_exact_contract_and_opaque_packets_never_opened(bound,monkeypatch):
    run,parent,cfg,auth,candidates=bound
    original=execution.values.sha
    def safe_sha(path):
        assert Path(path).suffix not in ('.parquet','.joblib')
        return original(path)
    monkeypatch.setattr(execution.values,'sha',safe_sha)
    actual=execution.continuation_contract(run)
    assert len(actual[3])==51 and len(actual[2]['diagnostic_candidate_ids'])==14
    assert execution.continuation_budget(run,*actual[1:])['new_fit_units']==0


@pytest.mark.parametrize('field,value', [('phase','PREPARING'),('capital_usd',4000),
    ('prior_account_paths',73),('prior_cumulative_fit_units',454)])
def test_root_freeze_boundary_rejected(bound,field,value):
    run,_,cfg,_,_=bound;cfg[field]=value;write(run/'run_config.json',cfg)
    with pytest.raises(execution.ExecutionBlocked):execution.continuation_contract(run)


def test_zero_bps_duplicate_reference_rejected(bound):
    run,_,cfg,auth,candidates=bound;candidates[1]['execution_friction']=friction(0)
    auth['candidates_sha256']=write(run/'candidates.json',candidates)['sha256'];write(run/'run_config.json',cfg)
    with pytest.raises(execution.ExecutionBlocked,match='ZERO_IS_PRIOR_REFERENCE'):execution.continuation_contract(run)


def test_existing_fixed_forecast_overlay_allowed(bound):
    run,_,cfg,auth,candidates=bound;candidates[1]['forecast']='black_litterman';candidates[2]['forecast']='return_shrink'
    auth['candidates_sha256']=write(run/'candidates.json',candidates)['sha256'];write(run/'run_config.json',cfg)
    assert len(execution.continuation_contract(run)[3])==51


def events_for(auth,candidate,failed=False):
    common=dict(candidate_id=candidate['candidate_id'],scientific_tuple_sha256=candidate['scientific_tuple_sha256'],
        continuation=True,namespace='R2',module_sha256=auth['source_pins']['replay_module_sha256'],
        controller_module_sha256=auth['module_sha256'])
    return [dict(common,event='ACCOUNT_PATH_ATTEMPT_STARTED',path_units=1),
            dict(common,event='ACCOUNT_PATH_FAILED' if failed else 'ACCOUNT_PATH_COMPLETE')]


def test_failed_counts_and_alias_retry_rejected(bound):
    run,_,cfg,auth,candidates=bound;rows=events_for(auth,candidates[0],True)
    journal(run/'ACCOUNT_PATH_LOG.jsonl',rows)
    budget=execution.continuation_budget(run,cfg,auth,candidates)
    assert budget['failed']==1 and budget['new_account_path_attempts']==1 and budget['account_path_attempts_cumulative']==75
    journal(run/'ACCOUNT_PATH_LOG.jsonl',rows+rows)
    with pytest.raises(execution.ExecutionBlocked,match='DUPLICATE'):execution.continuation_budget(run,cfg,auth,candidates)


def test_any_new_fit_is_not_reserved_budget_authorization(bound):
    run,_,cfg,auth,candidates=bound;journal(run/'FIT_LOG.jsonl',[dict(event='FIT_STARTED',fit_units=1)])
    with pytest.raises(execution.ExecutionBlocked,match='UNAUTHORIZED_FIT'):execution.continuation_budget(run,cfg,auth,candidates)


def test_wrong_event_producer_and_missing_newline_rejected(bound):
    run,_,cfg,auth,candidates=bound;rows=events_for(auth,candidates[0]);rows[0]['module_sha256']=auth['module_sha256']
    journal(run/'ACCOUNT_PATH_LOG.jsonl',rows)
    with pytest.raises(execution.ExecutionBlocked,match='PRODUCER'):execution.continuation_budget(run,cfg,auth,candidates)
    (run/'ACCOUNT_PATH_LOG.jsonl').write_text('{}',encoding='utf-8')
    with pytest.raises(execution.ExecutionBlocked,match='TAIL'):execution.continuation_budget(run,cfg,auth,candidates)


def test_owned_lock_no_takeover_worker_token_and_config_pin(bound,monkeypatch):
    run,_,cfg,auth,_=bound
    with execution.continuation_lock(run,auth['module_sha256']) as token:
        with pytest.raises(execution.ExecutionBlocked,match='ALREADY_EXISTS'):
            with execution.continuation_lock(run,auth['module_sha256']):pass
        with pytest.raises(execution.ExecutionBlocked,match='REQUIRES'):execution.continuation_worker_guard(run)
        monkeypatch.setenv(execution.CONTINUATION_LOCK_ENV,token)
        assert execution.continuation_worker_guard(run)[0]==run
        cfg['harmless_annotation']='newbytes';write(run/'run_config.json',cfg)
        with pytest.raises(execution.ExecutionBlocked,match='LOCK_IDENTITY'):execution.continuation_worker_guard(run)
    assert not (run/'CONTINUATION_LOCK.json').exists()


def test_projected_receipt_skips_sigma_and_future_dates_reject(bound):
    run,parent,cfg,auth,_=bound
    record=auth['value_packets']['hgb']['annual']['2023']['receipt'];p=Path(record['path'])
    raw=p.read_text().replace('999999','1e999')
    p.write_text(raw,encoding='utf-8');record['sha256']=execution.values.sha(p)
    parent_cfg=json.loads((parent/'run_config.json').read_text());parent_cfg['stateful_replay']['value_packets']=auth['value_packets']
    write(parent/'run_config.json',parent_cfg);auth['parent_run_config_sha256']=execution.values.sha(parent/'run_config.json');write(run/'run_config.json',cfg)
    assert execution.continuation_contract(run)[0]==run
    raw=raw.replace('2022-08-31','2026-01-02');p.write_text(raw,encoding='utf-8');record['sha256']=execution.values.sha(p)
    parent_cfg['stateful_replay']['value_packets']=auth['value_packets'];write(parent/'run_config.json',parent_cfg)
    auth['parent_run_config_sha256']=execution.values.sha(parent/'run_config.json');write(run/'run_config.json',cfg)
    with pytest.raises(ValueError,match='POST2025'):execution.continuation_contract(run)


@pytest.mark.parametrize('qualified,total,skipped',[(False,14,37),(True,51,0)])
def test_one_controller_probe_gates_declared_groups_and_report(bound,monkeypatch,qualified,total,skipped):
    run,_,_,auth,candidates=bound;control=execution.Controller(run)
    monkeypatch.setattr(execution,'configure_environment',lambda cfg:dict(scope='synthetic'))
    monkeypatch.setattr(execution,'_baseline_qualified',lambda *args:qualified)
    calls=[]
    def fake_batch(control,ids,token):
        assert all(next(c for c in candidates if c['candidate_id']==i)['execution_friction']==
            next(c for c in candidates if c['candidate_id']==ids[0])['execution_friction'] for i in ids)
        rows=execution._continuation_events(run,'ACCOUNT_PATH_LOG.jsonl')
        for identity in ids:rows+=events_for(auth,next(c for c in candidates if c['candidate_id']==identity),identity=='c1')
        journal(run/'ACCOUNT_PATH_LOG.jsonl',rows);calls.append(ids)
    monkeypatch.setattr(execution,'_run_continuation_batch',fake_batch)
    monkeypatch.setattr(completion,'build_continuation_report',lambda run:dict(status='NOT_TESTABLE' if not qualified else 'PENDING',finite_execution_complete=True,outputs={'report':str(run/'report.md')}))
    result=control.run_continuation()
    assert result['status']=='COMPLETED' and result['stage']=='REPORT_BUILT' and calls[0]==['c0']
    assert result['budget']['new_account_path_attempts']==total and result['budget']['failed']==1
    assert list(result['candidate_states'].values()).count('NOT_EXECUTED_REQUIRED_BASELINE_UNQUALIFIED')==skipped
    assert result['selection_performed'] is False and result['report']['outputs']
    if not qualified:assert result['scientific_status']=='NOT_TESTABLE'
    assert not (run/'FIT_LOG.jsonl').exists()
    assert not (run/'CONTINUATION_LOCK.json').exists()
    # Completed rerun consumes no additional path and creates no second writer.
    before=len(calls);assert execution.Controller(run).run_continuation()['status']=='COMPLETED';assert len(calls)==before


def test_r1_contract_behavior_not_dispatch_changed(tmp_path,monkeypatch):
    write(tmp_path/'run_config.json',dict(execution_training=dict(status='FROZEN')))
    assert execution._continuation_requested(tmp_path) is False
    with patch.object(execution,'frozen_contract',side_effect=execution.ExecutionBlocked('R1 ORIGINAL GATE')) as old:
        with pytest.raises(execution.ExecutionBlocked,match='R1 ORIGINAL GATE'):execution.Controller(tmp_path)
        old.assert_called_once_with(tmp_path,allow_partial_logs=True)


def test_baseline_boolean_qualification_full_grid_without_economic_values(bound):
    run,_,_,auth,candidates=bound
    audit=dict(status='ACTUAL_CONTINUOUS_PRE2026_REPLAY_COMPLETE',continuation=True,
        annual_reset=False,calendar_sessions=752,candidates_sha256=auth['candidates_sha256'],
        source_closure=dict(module_sha256=auth['source_pins']['replay_module_sha256']),
        policy_and_execution_cost_schedule_identical=True,fit_units=0,**{'2026_rows_read':0},
        selection_eligibility={'c0':{str(y):dict(sessions=n,accounting_qualified_all=True,
        certified_nav_positive_and_finite_all=True,net_return_finite_except_initial=True)
        for y,n in zip(execution.YEARS,(250,252,250))}},
        artifacts={'protected_nav_or_return':1e300})
    record=write(run/'audit.json',audit);rows=events_for(auth,candidates[0])
    rows[1].update(audit_path=record['path'],audit_sha256=record['sha256']);journal(run/'ACCOUNT_PATH_LOG.jsonl',rows)
    assert execution._baseline_qualified(run,auth,'c0') is True
    audit['selection_eligibility']['c0']['2024']['accounting_qualified_all']=False
    rows[1]['audit_sha256']=write(run/'audit.json',audit)['sha256'];journal(run/'ACCOUNT_PATH_LOG.jsonl',rows)
    assert execution._baseline_qualified(run,auth,'c0') is False
    audit['calendar_sessions']=751
    rows[1]['audit_sha256']=write(run/'audit.json',audit)['sha256'];journal(run/'ACCOUNT_PATH_LOG.jsonl',rows)
    with pytest.raises(execution.ExecutionBlocked,match='FULL_CALENDAR'):execution._baseline_qualified(run,auth,'c0')


@pytest.fixture
def qualification_bound(bound,monkeypatch):
    run,parent,cfg,auth,candidates=bound
    candidates=candidates[:1];candidates[0]['risk']='diag20_reference'
    auth.update(qualification_only=True,namespace='A_SOURCE_ACCOUNT_R3',expected_candidates=1,
        max_new_fit_units=0,max_new_account_paths=1,replay_chunk_size=1,diagnostic_candidate_ids=['c0'],
        source_account_binding={'synthetic_fixture':True})
    cfg.update(prior_account_paths=88,budget=dict(new_fit_units_hard_limit=0,new_account_attempts_hard_limit=1))
    auth['candidates_sha256']=write(run/'candidates.json',candidates)['sha256']
    write(run/'run_config.json',cfg)
    # Source verification is separately tested; this fixture tests orchestration.
    monkeypatch.setattr(execution,'_qualification_identity',lambda *args:None)
    return run,parent,cfg,auth,candidates


def test_qualification_contract_one_path_zero_fit(qualification_bound):
    run,_,cfg,auth,candidates=qualification_bound
    execution.continuation_contract(run)
    budget=execution.continuation_budget(run,cfg,auth,candidates)
    assert budget['new_fit_units_hard_limit']==0 and budget['new_account_path_hard_limit']==1
    assert budget['account_path_attempts_cumulative']==88


@pytest.mark.parametrize('which', ['fits','accounts','extra_candidate'])
def test_qualification_scope_cannot_expand(qualification_bound,which):
    run,_,cfg,auth,candidates=qualification_bound
    if which=='fits':
        auth['max_new_fit_units']=1;cfg['budget']['new_fit_units_hard_limit']=1
    elif which=='accounts':
        auth['max_new_account_paths']=2;cfg['budget']['new_account_attempts_hard_limit']=2
    else:
        candidates.append(dict(candidates[0],candidate_id='candidate37',scientific_tuple_sha256='f'*64))
        auth['candidates_sha256']=write(run/'candidates.json',candidates)['sha256']
    write(run/'run_config.json',cfg)
    with pytest.raises(execution.ExecutionBlocked):execution.continuation_contract(run)


@pytest.mark.parametrize('qualified',[False,True])
def test_qualification_controller_never_activates_candidates(qualification_bound,monkeypatch,qualified):
    run,_,cfg,auth,candidates=qualification_bound
    monkeypatch.setattr(execution,'configure_environment',lambda config:{})
    monkeypatch.setattr(execution,'_baseline_qualified',lambda *args:qualified)
    calls=[]
    def batch(control,ids,token):
        calls.append(ids)
        rows=events_for(auth,candidates[0])
        for row in rows:row['namespace']='A_SOURCE_ACCOUNT_R3'
        journal(run/'ACCOUNT_PATH_LOG.jsonl',rows)
        return {}
    monkeypatch.setattr(execution,'_run_continuation_batch',batch)
    monkeypatch.setattr(completion,'build_continuation_report',lambda run:dict(status='QUALIFIED' if qualified else 'NOT_TESTABLE',finite_execution_complete=True))
    state=execution.Controller(run).run_continuation()
    assert state['status']=='COMPLETED' and calls==[['c0']]
    assert state['budget']['new_account_path_attempts']==1 and state['budget']['new_fit_units']==0
    assert not (run/'FIT_LOG.jsonl').exists() and not (run/'CONTINUATION_LOCK.json').exists()


def test_missing_source_binding_is_rejected(bound):
    run,_,cfg,auth,candidates=bound
    auth.update(qualification_only=True,namespace='A_SOURCE_ACCOUNT_R3',expected_candidates=1,replay_chunk_size=1,diagnostic_candidate_ids=['c0'])
    with pytest.raises(execution.ExecutionBlocked,match='ONE_BASELINE_EXACT_SCOPE'):
        execution._qualification_identity(run,cfg,auth,candidates[:1])


# Research-only namespace regression. All paths and receipts below are synthetic.
def research_loop_fixture(tmp_path,monkeypatch,groups,aggregate=True):
    from contextlib import contextmanager
    from scripts.research.a2.training import stateful_research_account as child
    run=tmp_path/'research_loop';run.mkdir()
    candidates=[dict(candidate_id='RAW_s10' if i==0 else f'RESEARCH_SYNTHETIC_{i:02d}',
        scientific_tuple_sha256=f'{i:064x}',execution_friction=friction((5,10,20)[i%3])) for i in range(57)]
    calls=[];state={}
    @contextmanager
    def lock(*args):yield 'SYNTHETIC_OWNED_LOCK'
    monkeypatch.setattr(execution,'continuation_lock',lock)
    monkeypatch.setattr(execution,'configure_environment',lambda config:{'synthetic':True})
    monkeypatch.setattr(child,'baseline_gate',lambda *args:dict(groups=groups,all_passed=aggregate,decision='UNTRUSTED_COMBINED_FLAG'))
    monkeypatch.setattr(child,'build_report',lambda *args:dict(status='SYNTHETIC_REPORT',economic_evaluation_performed=False))
    def batch(control,ids,token):
        assert token=='SYNTHETIC_OWNED_LOCK'
        assert not set(ids)&{x for group in calls for x in group}
        calls.append(list(ids))
        previous=execution.events(run,'ACCOUNT_PATH_LOG.jsonl')
        for cid in ids:
            row=next(c for c in candidates if c['candidate_id']==cid)
            for event in ('ACCOUNT_PATH_ATTEMPT_STARTED','ACCOUNT_PATH_COMPLETE'):
                previous.append(dict(event=event,candidate_id=cid,scientific_tuple_sha256=row['scientific_tuple_sha256']))
        journal(run/'ACCOUNT_PATH_LOG.jsonl',previous)
    monkeypatch.setattr(execution,'_run_research_batch',batch)
    def save(status,stage,**meta):state.update(status=status,stage=stage,**meta)
    control=SimpleNamespace(run=run,config={},auth={'replay_chunk_size':4},candidates=candidates,
        state=state,guard=lambda:None,save=save)
    return control,calls,candidates,child


def test_research_unique_controller_exact57_order_and_original_friction(tmp_path,monkeypatch):
    from scripts.research.a2.training import stateful_research_account as child
    control,calls,candidates,_=research_loop_fixture(tmp_path,monkeypatch,dict.fromkeys(child.GATES,True))
    result=execution._run_research_controller(control)
    assert result['status']=='COMPLETED' and result['baseline_qualified'] is True
    assert [cid for group in calls for cid in group]==[c['candidate_id'] for c in candidates]
    assert calls[0]==['RAW_s10']
    for group in calls:
        assert len({next(c['execution_friction']['one_way_bps'] for c in candidates if c['candidate_id']==cid) for cid in group})==1
    assert len(execution.events(control.run,'ACCOUNT_PATH_LOG.jsonl'))==114


@pytest.mark.parametrize('gate',range(10))
@pytest.mark.parametrize('bad',[False,None,'MISSING'])
def test_research_controller_each_literal_gate_blocks_even_combined_true(tmp_path,monkeypatch,gate,bad):
    from scripts.research.a2.training import stateful_research_account as child
    groups=dict.fromkeys(child.GATES,True)
    if bad=='MISSING':groups.pop(child.GATES[gate])
    else:groups[child.GATES[gate]]=bad
    control,calls,_,_=research_loop_fixture(tmp_path,monkeypatch,groups,aggregate=True)
    result=execution._run_research_controller(control)
    assert calls==[['RAW_s10']]
    assert result['baseline_qualified'] is False
    assert result['activation_decision']=='RESEARCH_ACCOUNT_BASELINE_BLOCKED'


def test_research_controller_aggregate_false_and_outstanding_never_dispatch(tmp_path,monkeypatch):
    from scripts.research.a2.training import stateful_research_account as child
    control,calls,_,_=research_loop_fixture(tmp_path,monkeypatch,dict.fromkeys(child.GATES,True),aggregate=False)
    assert execution._run_research_controller(control)['baseline_qualified'] is False
    assert calls==[['RAW_s10']]
    # An unresolved attempt is preserved; the controller never creates another writer.
    calls.clear();control.state.clear()
    journal(control.run/'ACCOUNT_PATH_LOG.jsonl',[dict(event='ACCOUNT_PATH_ATTEMPT_STARTED',candidate_id='RAW_s10')])
    result=execution._run_research_controller(control)
    assert result['status']=='BLOCKED' and calls==[]
    assert len(execution.events(control.run,'ACCOUNT_PATH_LOG.jsonl'))==1
