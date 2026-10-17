"""Generated control JSON and fake artifact bytes only; no real accounts/models."""
from dataclasses import replace
from pathlib import Path
import copy
import json
import pytest
from scripts.research.a2.evaluation import consensus_child_terminal_audit as owner

base = owner.base


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def blob(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'GENERATED_CONTROL_ARTIFACT_NOT_A_REAL_MODEL_OR_PARQUET')
    return base._ref(path)


@pytest.fixture
def controls(tmp_path, monkeypatch):
    run = tmp_path / 'child'
    run.mkdir()
    monkeypatch.setattr(base.fusion, 'CONTINUATION_RUN', run)
    paths = base.resolve(base.predictors.REPO)
    synthetic_paths = replace(paths, backtest_root=run, cache_root=tmp_path / 'cache',
        data_root=tmp_path / 'data', daily_root=tmp_path / 'daily',
        results_root=tmp_path / 'results', envs_root=tmp_path / 'envs')
    monkeypatch.setattr(base, 'resolve', lambda *_: synthetic_paths)
    from scripts.storage import storage_r2a
    monkeypatch.setattr(storage_r2a, 'assert_write_path',
        lambda path, kind: base.assert_safe_output_path(path, kind='backtest', paths=synthetic_paths))
    monkeypatch.setattr(base.predictors, 'fit_one', lambda *a, **k: pytest.fail('no predictor fit'))
    monkeypatch.setattr(base.fusion, 'fit_one', lambda *a, **k: pytest.fail('no fusion fit'))
    monkeypatch.setattr(base.evaluation.joblib, 'load', lambda *a, **k: pytest.fail('no model or state decoding'))
    monkeypatch.setattr(base.evaluation.pq, 'read_table', lambda *a, **k: pytest.fail('no numeric parquet decoding'))
    recipe = copy.deepcopy(base.evaluation.RECIPE)
    recipe['fusion_methods'].append(base.fusion.owner.NNLS_ZERO_ABSTAIN)
    freeze = dict(recipe=recipe)
    write(run / 'generated_freeze.json', freeze)
    fr = base._ref(run / 'generated_freeze.json')

    def account(method, risk='LW', allocation='cost_aware', tag=None, status='NOT_TESTABLE'):
        fid = base.evaluation.flow_id(method, risk, allocation, tag, run=base.fusion.CONTINUATION_RUN)
        path = run / 'evaluation/consensus_account' / fid / 'receipt.json'
        fee = copy.deepcopy(recipe['fee_config'])
        if tag is not None:
            diagnostic = next(d for d in recipe['diagnostic_sensitivities'] if d['tag'] == tag)
            fee.update(one_way_all_in_bps=diagnostic['one_way_all_in_bps'], fixed_per_fill_usd=diagnostic['fixed_per_fill_usd'])
        r = dict(task_id=base.TASK, status=status, flow_id=fid, fusion_method=method,
                 risk_method=risk, allocation_method=allocation, fee_config=fee,
                 receipt_path=str(path), freeze_ref=fr, artifacts={})
        if status == 'COMPLETE':
            r['artifacts']['state'] = blob(path.with_name('state.joblib'))
        write(path, r)
        return r

    stage1 = [account(m) for m in recipe['fusion_methods']]
    summary = dict(status='NOT_TESTABLE', task_id=base.TASK, freeze_ref=fr,
                   test_2026_rows_read=0, stage1=stage1, stage2=[])
    return dict(run=run, recipe=recipe, freeze=freeze, fr=fr, account=account, summary=summary)


def partial(controls):
    c = controls
    method = c['recipe']['fusion_methods'][0]
    c['summary']['stage1'][0] = c['account'](method, status='COMPLETE')
    stage2 = [c['account'](method, p['risk_method'], p['allocation_method'],
                         status='COMPLETE' if (p['risk_method'], p['allocation_method']) == ('LW', 'cost_aware') else 'NOT_TESTABLE')
              for p in c['recipe']['stage2']]
    chosen = next(r for r in stage2 if r['status'] == 'COMPLETE')
    diagnostics = [c['account'](method, 'LW', 'cost_aware', d['tag'], status='COMPLETE')
                   for d in c['recipe']['diagnostic_sensitivities']]

    def risk(account, status):
        fid = account['flow_id']
        path = c['run'] / 'models/consensus_final_policy' / fid / 'receipt.json'
        r = dict(task_id=base.TASK, status=status, selected_flow=fid, receipt_path=str(path),
                 freeze_ref=c['fr'], artifacts=dict(state=blob(path.with_name('state.joblib'))),
                 identity_sha256=base.values.digest(dict(selected_flow=fid,
                     selected_receipt_sha256=base.values.sha(account['receipt_path']), freeze_ref=c['fr'])))
        if status == 'COMPLETE':
            r.update(test_rows_read=0, final_risk_fit_cutoff='2026-01-01 exclusive')
        else:
            r['failure'] = dict(type='GeneratedRiskFailure', reason='NO_GENERATED_FIT')
        write(path, r)
        return r

    summary = dict(c['summary'], status='FINAL_RISK_NOT_FROZEN_NO_TEST_USE', selected_fusion=method,
                   selected_flow=chosen['flow_id'], stage2=stage2, sensitivities=diagnostics,
                   final_risk_receipt=risk(chosen, 'FAILED_NO_RETRY'),
                   sensitivity_final_risk=[risk(r, 'COMPLETE') for r in diagnostics])
    return summary, risk, chosen


def test_all14_noncomplete_are_honest_terminal_with_real_receipt_checks(controls):
    c = controls
    accounts, risks = owner._account_terminal(c['run'], c['summary'], c['freeze'], c['fr'])
    assert len(accounts) == 14 and risks == []
    assert all(r['status'] == 'NOT_TESTABLE' for r in accounts)


def test_no_winner_cannot_hide_complete_stage1(controls):
    c = controls
    c['summary']['stage1'][0]['status'] = 'COMPLETE'
    with pytest.raises(ValueError, match='CANNOT_HIDE_SUCCESSFUL_STAGE1'):
        owner._account_terminal(c['run'], c['summary'], c['freeze'], c['fr'])


def test_source_receipt_drift_rejected_without_artifact_decoding(controls):
    c = controls
    path = Path(c['summary']['stage1'][0]['receipt_path'])
    r = dict(c['summary']['stage1'][0], status='FAILED_NO_RETRY')
    write(path, r)
    with pytest.raises(ValueError, match='ACCOUNT_SUMMARY_CUSTODY_CHANGED'):
        owner._account_terminal(c['run'], c['summary'], c['freeze'], c['fr'])


def test_partial_finalrisk_failure_is_bound_to_selected_account(controls):
    c = controls
    summary, _, _ = partial(c)
    accounts, risks = owner._account_terminal(c['run'], summary, c['freeze'], c['fr'])
    assert len(accounts) == 14 + 17 + 4
    assert [r['status'] for r in risks] == ['FAILED_NO_RETRY'] + ['COMPLETE'] * 4


@pytest.mark.parametrize('mutation', ['all_risks_complete', 'missing_stage2', 'missing_diagnostic', 'wrong_failed_risk_origin'])
def test_partial_terminal_cannot_hide_complete_or_shrink_fixed_scope(controls, mutation):
    c = controls
    summary, make_risk, chosen = partial(c)
    if mutation == 'all_risks_complete':
        summary['final_risk_receipt'] = make_risk(chosen, 'COMPLETE')
        error = 'CANNOT_HIDE_COMPLETE_FINAL_SYSTEM'
    elif mutation == 'missing_stage2':
        summary['stage2'].pop()
        error = 'CONDITIONAL_SEVENTEEN'
    elif mutation == 'missing_diagnostic':
        summary['sensitivities'].pop()
        error = 'FOUR_FIXED'
    else:
        r = summary['final_risk_receipt']
        r['identity_sha256'] = 'f' * 64
        write(Path(r['receipt_path']), r)
        error = 'RISK_ORIGIN'
    with pytest.raises(ValueError, match=error):
        owner._account_terminal(c['run'], summary, c['freeze'], c['fr'])


def test_full_child_terminal_reuses_51_cal_source_and_global_budget_helpers(controls, monkeypatch):
    c = controls
    run, parent = c['run'], c['run'].parent / 'parent'
    parent.mkdir()
    monkeypatch.setattr(base.fusion, 'CONTINUATION_RUN', run)
    scope_ref = blob(run / 'generated_scope.json')
    pfr, oldfr, childfr = (blob(run / ('generated_' + name + '.json')) for name in ('predictor', 'parentfusion', 'childfusion'))
    models = [dict(slot=dict(model_id='GENERATED_' + str(i)), status='FAILED' if i == 0 else 'TRAINED') for i in range(228)]
    old = [dict(slot=dict(method='GENERATED_' + str(i)), status='FAILED' if i == 0 else 'TRAINED') for i in range(84)]
    new = [dict(slot=dict(method='GENERATED_CHILD', year=y), status='TRAINED') for y in (2023, 2024, 2025, 2026)]
    facts = dict(parent=parent, scope_ref=scope_ref, prior=1098, scope=dict(parent_custody=dict(
        predictor_freeze_ref=pfr, fusion_freeze_ref=oldfr, parent_fit_log_ref=blob(parent / 'FIT_LOG.jsonl'))),
        spec={}, pf={}, ff={}, audit=dict(candidate_predictors=models, candidate_fusions=old))
    ef = dict(c['freeze'], research_id=base.fusion.CONTINUATION_RESEARCH_ID, continuation_scope_ref=scope_ref,
              prior_fit_units=1098, account_source_scope_ref=scope_ref)
    write(run / 'evaluation/consensus_account_summary.json', c['summary'])
    write(run / 'FIT_LOG.jsonl', dict(event='FIT_STARTED', fit_units=1))
    calls = []
    monkeypatch.setattr(base.fusion, '_continuation_facts', lambda r: facts)
    monkeypatch.setattr(base.fusion, 'reader_run', lambda r: parent)
    monkeypatch.setattr(base.fusion, 'contract', lambda *a: (None, None, None, {}, None, childfr))
    monkeypatch.setattr(base.evaluation, 'contract', lambda r: (r, ef, c['fr']))
    monkeypatch.setattr(base.evaluation, 'recipe_for_run', lambda r: c['recipe'])
    monkeypatch.setattr(base, '_candidate_dispositions', lambda *a: (models, old, {}, []))
    monkeypatch.setattr(base, '_child_fusion_dispositions', lambda *a: (new, {}))
    def calibration(*args):
        assert args[2] is models and args[3] == old + new and args[4] == scope_ref
        calls.append('51cal')
        return dict(ref=blob(run / 'generated51.json'), manifest=dict(status='CALIBRATION_COMPLETED')), [{}] * 51
    monkeypatch.setattr(base, '_final_calibration_completion', calibration)
    monkeypatch.setattr(base, '_child_source_closure', lambda *a: calls.append('source_registry') or dict(actual_input_ref=blob(run / 'generated_input.json')))
    monkeypatch.setattr(base, '_historical_auxiliary', lambda *a: dict(historical_parent_fact=True))
    result = owner.audit_terminal(run)
    assert calls == ['51cal', 'source_registry']
    assert len(result['candidate_predictors']) == 228 and len(result['candidate_fusions']) == 88
    assert result['candidate_predictors'][0]['status'] == result['parent_candidate_fusions'][0]['status'] == 'FAILED'
    assert result['fit_budget']['prior_fit_units'] == 1098 and result['fit_budget']['child_fit_units'] == 1
    assert result['fit_budget']['total_fit_units'] == 1099
    assert not result['complete_selected_system_frozen'] and not result['test_2026_numeric_read_authorized']
    assert not (run / base.TERMINAL_AUDIT_FILENAME).exists()
    (run / 'CONSENSUS_FIT.lock').write_text('GENERATED_ACTIVE_JOB', encoding='utf-8')
    with pytest.raises(ValueError, match='ACTIVE_FIT'):
        owner.audit_terminal(run)


def test_exact_child_and_immutable_closure_owner_are_enforced(controls, monkeypatch):
    monkeypatch.setattr(base.fusion, 'CONTINUATION_RUN', controls['run'])
    with pytest.raises(ValueError, match='EXACT_CHILD_TERMINAL'):
        owner.audit_terminal(controls['run'].parent / 'parent')
    monkeypatch.setattr(owner, 'CLOSURE_OWNER_SHA', 'f' * 64)
    with pytest.raises(ValueError, match='IMMUTABLE_51_CALIBRATION'):
        owner.audit_terminal(controls['run'])

def test_complete_summary_must_use_existing_system_freeze_builder(controls):
    c = controls
    c['summary']['status'] = 'COMPLETE'
    with pytest.raises(ValueError, match='HONEST_CHILD_NONCOMPLETE'):
        owner._account_terminal(c['run'], c['summary'], c['freeze'], c['fr'])


def test_root_publish_is_immutable_and_tracks_final_fitlog(controls, monkeypatch):
    run = controls['run']
    log = run / 'FIT_LOG.jsonl'
    log.write_text('{"event":"GENERATED_METADATA_ONLY"}\n', encoding='utf-8')
    def audit(r):
        assert r == run
        return dict(schema=owner.SCHEMA, status=owner.STATUS,
                    fit_log_ref=base._ref(log), complete_selected_system_frozen=False,
                    test_2026_numeric_read_authorized=False)
    monkeypatch.setattr(owner, '_audit', audit)
    result = owner.publish_terminal_root(run)
    target = run / base.TERMINAL_AUDIT_FILENAME
    original = target.read_bytes()
    assert owner.publish_terminal_root(run) == result
    assert target.read_bytes() == original and not (run / 'CONSENSUS_FIT.lock').exists()
    log.write_text('{"event":"GENERATED_METADATA_ONLY_AFTER_AUDIT"}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='CHILD_TERMINAL_AUDIT_CUSTODY_CHANGED'):
        owner.publish_terminal_root(run)
    assert target.read_bytes() == original


def test_optional_ebm_six_slot_closure_projects_only_metadata_and_keeps_all_attempts(controls, monkeypatch):
    from scripts.research.a2.training import consensus_ebm_teardown_retry as retry
    run=controls['run']
    assert owner._ebm_terminal(run,{}) is None
    monkeypatch.setattr(retry,'fit_one',lambda *a,**k:pytest.fail('no EBM fit'))
    monkeypatch.setattr(retry,'run_all',lambda *a,**k:pytest.fail('no EBM run'))
    source_pins={'generated_code':blob(run/'fake_source.py')}
    monkeypatch.setattr(retry.predictors,'source_pins',lambda:source_pins)
    spec=dict(ordered_slots=[dict(model_id='ebm',year=y,horizon=5) for y in range(2021,2027)],
        source_pins=source_pins,dependency_code_binding={'generated':'f'*64},dependency_paths=['GENERATED_NO_NATIVE_LOAD'],
        seed=20260928,source_qualification_ref=blob(run/'source_qualified.json'),correction_sidecar_ref=blob(run/'sidecar.parquet'),
        max_new_physical_attempts_per_slot=2,max_new_bucket_fit_units=24,primary_core5_selection_includes_retry_ebm=False,
        wide_32_fusion_authorized=False,test_2026_read_authorized=False,real_2026_prediction_publication_allowed=False,
        original_failed_receipt_refs=[])
    for field in retry.AUTHORITY_FIELDS[:-1]:spec[field]=blob(run/(field+'.json'))
    write(run/retry.FREEZE,spec)
    freeze_ref=base._ref(run/retry.FREEZE)
    monkeypatch.setattr(owner,'EBM_FREEZE_SHA',freeze_ref['sha256'])
    with pytest.raises(ValueError,match='TERMINAL_SUMMARY_REQUIRED'):owner._ebm_terminal(run,{})
    monkeypatch.setattr(retry,'contract',lambda r:(r,spec,freeze_ref))
    slots=[];events=[]
    for year in range(2021,2027):
        old_tuple=dict(model_id='ebm',year=year,horizon=5,train_frame_sha256='a'*64,calibration_frame_sha256='b'*64)
        old_path=run/'generated_parent'/str(year)/'receipt.json'
        write(old_path,dict(status='FAILED',model_id='ebm',year=year,horizon=5,fit_units=1,reuse_tuple=old_tuple,
            reuse_tuple_sha256=base.values.digest(old_tuple),failure={'message':'FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'}))
        old_ref=base._ref(old_path);spec['original_failed_receipt_refs'].append(old_ref)
        reuse=dict(freeze_ref=freeze_ref,source_pins=source_pins,dependency_code_binding=spec['dependency_code_binding'],
            dependency_paths=spec['dependency_paths'],original_failed_receipt_ref=old_ref,
            original_reuse_tuple_sha256=base.values.digest(old_tuple),year=year,horizon=5,seed=spec['seed'],
            train_frame_sha256='a'*64,original_calibration_frame_sha256='b'*64,
            effective_calibration_frame_sha256='e'*64 if year==2026 else 'b'*64,
            source_qualification_ref=spec['source_qualification_ref'] if year==2026 else None)
        history=[]
        for number in ((2,3) if year==2023 else (2,)):
            path=run/retry.ROOT/str(year)/f'attempt{number}'/'receipt.json'
            status='FAILED_ENGINEERING' if year==2023 else 'FAILED_SCIENTIFIC_NO_RETRY' if year==2022 else 'TRAINED'
            units=2 if status=='TRAINED' else 1
            record=dict(status=status,phase='COMPLETED' if status=='TRAINED' else 'NATIVE',model_id='ebm',native_model_id='ebm',
                year=year,horizon=5,receipt_path=str(path),fit_units=units,reuse_tuple=reuse,reuse_tuple_sha256=base.values.digest(reuse),
                source_pins=source_pins,retry_source_pins=source_pins,previous_attempt_refs=history.copy(),parent_failure_preserved=True,
                test_2026_rows_read=0,primary_core5_selection_includes_retry_ebm=False,
                calibration={'numeric_poison':'POISON_CALIBRATION_MUST_NOT_BE_JSON_DECODED'})
            if status=='TRAINED':
                record.update(model_ref=blob(path.with_name('model.joblib')),calibration_ref=blob(path.with_name('calibration.parquet')))
            write(path,record);history.append(base._ref(path))
            for _ in range(units):events.append(dict(event='FIT_STARTED',budget_bucket='consensus_ebm_teardown_retry',model_id='ebm',
                year=year,fit_units=1,reuse_tuple_sha256=base.values.digest(reuse)))
        slots.append(dict(slot=dict(model_id='ebm',year=year,horizon=5),
            status='ENGINEERING_RETRY_LIMIT_REACHED' if year==2023 else status,
            receipt_ref=None if year==2023 else history[-1]))
    summary=dict(schema='CONSENSUS_EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1',status='FIXED_SIX_ATTEMPTS_FINISHED',task_id=base.TASK,
        research_id=base.fusion.CONTINUATION_RESEARCH_ID,freeze_ref=freeze_ref,slots=slots,test_2026_read=False,
        original_failures_preserved=True,old_37_plus_14_unchanged=True,test_2026_rows_read=0,real_2026_prediction_published=False)
    summary_path=run/owner.EBM_SUMMARY_FILENAME;write(summary_path,summary)
    log=run/'FIT_LOG.jsonl';log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
    budget=base._child_fit_budget(run,dict(prior=1098,scope={'parent_custody':{'parent_fit_log_ref':blob(run/'generated_parent_fitlog')}}))
    native_json_loads=json.loads
    def guarded_loads(value,*args,**kwargs):
        assert 'POISON_CALIBRATION_MUST_NOT_BE_JSON_DECODED' not in str(value)
        return native_json_loads(value,*args,**kwargs)
    monkeypatch.setattr(json,'loads',guarded_loads)
    result=owner._ebm_terminal(run,budget)
    assert len(result['dispositions'])==6 and result['new_bucket_fit_units']==11
    assert len(result['dispositions'][2]['attempts'])==2 and result['dispositions'][2]['status']=='ENGINEERING_RETRY_LIMIT_REACHED'
    assert result['original_failures_preserved'] and result['old_37_plus_14_unchanged']
    assert not result['native_models_loaded'] and not result['sigma_calibration_observations_read']
    assert not result['primary_core5_selection_includes_retry_ebm'] and result['test_2026_rows_read']==0
    bad=copy.deepcopy(summary);bad['slots'][0]['receipt_ref']=None;write(summary_path,bad)
    with pytest.raises(ValueError,match='SUMMARY_RECEIPT'):owner._ebm_terminal(run,budget)
    bad=copy.deepcopy(summary);bad['slots'].reverse();write(summary_path,bad)
    with pytest.raises(ValueError,match='ORDERED_SIX'):owner._ebm_terminal(run,budget)
    write(summary_path,summary)
    bad_budget=dict(budget,child_fit_units=10)
    with pytest.raises(ValueError,match='SHARED_BUDGET'):owner._ebm_terminal(run,bad_budget)
    path=Path(slots[0]['receipt_ref']['path'])
    record=owner._ebm_metadata(path);record['reuse_tuple']['train_frame_sha256']='d'*64
    write(path,record)
    with pytest.raises(ValueError,match='FULL_EBM_RETRY_TUPLE'):owner._ebm_terminal(run,budget)