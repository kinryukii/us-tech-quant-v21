"""Generated control records and fake artifact bytes only; no real run read."""
from contextlib import contextmanager
from pathlib import Path
import copy
import json
from types import SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.evaluation import consensus_final_freeze as owner


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')


def blob(path):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'GENERATED_ONLY_NOT_A_REAL_MODEL_OR_PARQUET');return owner._ref(path)


@contextmanager
def changed(path,mutator):
    before=path.read_bytes()
    try:
        value=json.loads(before);mutator(value);write(path,value);yield
    finally:path.write_bytes(before)


@pytest.fixture(scope='module')
def controls(tmp_path_factory):
    run=tmp_path_factory.mktemp('frozen_metadata_synthetic')
    spec=dict(model_ids=list(owner.values.FIRST_MODELS),training_plan=dict(years=list(range(2021,2027))))
    spec_ref=blob(run/'source/spec.json');code=blob(run/'source/owner.py');scope_path=run/'ACCOUNT_SOURCE_SCOPE.json';write(scope_path,dict(source_ref=code))
    pf=dict(authorized_spec=spec_ref,source_pins=dict(owner=code),input_binding_sha256='a'*64,membership_sha256='b'*64)
    write(run/'CONSENSUS_PREDICTOR_FREEZE.json',pf);pfr=owner._ref(run/'CONSENSUS_PREDICTOR_FREEZE.json')
    ff=dict(source_pins=dict(owner=code),predictor_freeze_ref=pfr)
    write(run/'CONSENSUS_FUSION_FREEZE.json',ff);ffr=owner._ref(run/'CONSENSUS_FUSION_FREEZE.json')
    ef=dict(account_source_scope_ref=owner._ref(scope_path),recipe=copy.deepcopy(owner.evaluation.RECIPE))
    write(run/owner.evaluation.FREEZE,ef);efr=owner._ref(run/owner.evaluation.FREEZE)
    pslots=owner.predictors.planned_slots(spec);fslots=owner.fusion.planned_slots(spec);prows=[];frows=[];publications={}
    for kind,slots,frozen,fr,rows in (('predictor',pslots,pf,pfr,prows),('fusion',fslots,ff,ffr,frows)):
        for slot in slots:
            year=slot['year'];model=slot['model_id'] if kind=='predictor' else slot['method']
            if kind=='predictor':_,rp,mp,cp=owner.predictors.slot_paths(run,model,year,slot['horizon'])
            else:_,rp,mp=owner.fusion.slot_paths(run,slot['packet_id'],model,year)
            sessions=pd.bdate_range(f'{year-1}-10-01',periods=60)
            reuse=dict(task_id=owner.TASK,model_id=model,year=year,source_pins=frozen['source_pins'],freeze_ref=fr,
                train_maturity_exclusive=str(sessions[0]),calibration_maturity_exclusive=f'{year}-01-01',calibration_sessions=[str(d) for d in sessions])
            if kind=='predictor':reuse.update(horizon=slot['horizon'],authorized_spec=pf['authorized_spec'],input_binding_sha256=pf['input_binding_sha256'],membership_sha256=pf['membership_sha256'])
            else:reuse.update(packet_id=slot['packet_id'],members=slot['members'],predictor_freeze_ref=pfr,
                past_publication_pins=[publications[(owner.fusion.member_key(m),y)] for m in slot['members'] for y in range(2021,year)])
            receipt=dict(status='TRAINED',model_id=model,year=year,source_pins=frozen['source_pins'],receipt_path=str(rp),
                reuse_tuple=reuse,reuse_tuple_sha256=owner.values.digest(reuse),model_sha256=blob(mp)['sha256'])
            if kind=='predictor':receipt.update(horizon=slot['horizon'],calibration_predictions_sha256=blob(cp)['sha256'])
            else:receipt.update(packet_id=slot['packet_id'])
            write(rp,receipt)
            row={k:slot[k] for k in (('model_id','year','horizon') if kind=='predictor' else ('packet_id','method','year'))}
            row.update(status='TRAINED',receipt_path=str(rp))
            if year<2026:
                output=run/'predictions'/('consensus_predictors/'+model+f"/{slot['horizon']}d" if kind=='predictor' else 'consensus_fusion/'+slot['packet_id']+'/'+model)/f'{year}.parquet'
                pub=dict(status='PUBLISHED',test_2026_rows_read=0,source_pins=frozen['source_pins'],fit_receipt_sha256=owner.values.sha(rp),
                    fit_receipt_path=str(rp),reuse_tuple_sha256=receipt['reuse_tuple_sha256'],sha256=blob(output)['sha256'])
                pub_path=output.with_suffix('.receipt.json');write(pub_path,pub);row['status']='PUBLISHED'
                if kind=='predictor':publications[(model+'_'+str(slot['horizon'])+'d',year)]=dict(member=model+'_'+str(slot['horizon'])+'d',year=year,
                    publication_receipt_sha256=owner.values.sha(pub_path),prediction_sha256=pub['sha256'],fit_receipt_sha256=owner.values.sha(rp))
            rows.append(row)
    for path,rows in (('logs/PREDICTOR_PROGRESS.json',prows),('logs/FUSION_PROGRESS.json',frows)):
        write(run/path,dict(status='COMPLETED_ALL_FIXED_SLOTS',slots_complete=len(rows),total_slots=len(rows),rows=rows,test_2026_content_read=False))
    blob(run/'FIT_LOG.jsonl')
    method='equal'
    def account(risk='LW',alloc='cost_aware',diagnostic=None):
        fid=owner.evaluation.flow_id(method,risk,alloc,None if diagnostic is None else diagnostic['tag'])
        root=run/'evaluation/consensus_account'/fid
        fee=copy.deepcopy(owner.evaluation.RECIPE['fee_config'])
        if diagnostic:fee.update(one_way_all_in_bps=diagnostic['one_way_all_in_bps'],fixed_per_fill_usd=diagnostic['fixed_per_fill_usd'])
        r=dict(task_id=owner.TASK,status='COMPLETE',flow_id=fid,fusion_method=method,risk_method=risk,allocation_method=alloc,
            fee_config=fee,receipt_path=str(root/'receipt.json'),freeze_ref=efr,artifacts=dict(state=blob(root/'state.joblib')))
        write(root/'receipt.json',r);return r
    stage1=[]
    for m in owner.evaluation.RECIPE['fusion_methods']:
        fid=owner.evaluation.flow_id(m);root=run/'evaluation/consensus_account'/fid
        r=dict(task_id=owner.TASK,status='COMPLETE',flow_id=fid,fusion_method=m,risk_method='LW',allocation_method='cost_aware',
            fee_config=copy.deepcopy(owner.evaluation.RECIPE['fee_config']),receipt_path=str(root/'receipt.json'),freeze_ref=efr,artifacts=dict(state=blob(root/'state.joblib')))
        write(root/'receipt.json',r);stage1.append(r)
    stage2=[account(p['risk_method'],p['allocation_method']) for p in owner.evaluation.RECIPE['stage2']]
    diagnostics=[account(diagnostic=d) for d in owner.evaluation.RECIPE['diagnostic_sensitivities']]
    def final(r):
        fid=r['flow_id'];root=run/'models/consensus_final_policy'/fid
        f=dict(task_id=owner.TASK,status='COMPLETE',selected_flow=fid,receipt_path=str(root/'receipt.json'),freeze_ref=efr,
            identity_sha256=owner.values.digest(dict(selected_flow=fid,selected_receipt_sha256=owner.values.sha(r['receipt_path']),freeze_ref=efr)),
            artifacts=dict(state=blob(root/'state.joblib')),test_rows_read=0,final_risk_fit_cutoff='2026-01-01 exclusive')
        write(root/'receipt.json',f);return f
    summary=dict(status='COMPLETE',task_id=owner.TASK,freeze_ref=efr,test_2026_rows_read=0,sensitivity_selection_feedback=False,
        conditional_research_only=True,strict_PIT_certified=False,selected_fusion=method,selected_flow=owner.evaluation.flow_id(method),
        stage1=stage1,stage2=stage2,final_risk_receipt=final(stage2[1] if stage2[1]['risk_method']=='LW' else next(r for r in stage2 if r['risk_method']=='LW')),
        sensitivities=diagnostics,sensitivity_final_risk=[final(r) for r in diagnostics])
    write(run/'evaluation/consensus_account_summary.json',summary)
    af=dict(source_pins=dict(owner=code));write(run/'CONSENSUS_AUXILIARY_FREEZE.json',af);afr=owner._ref(run/'CONSENSUS_AUXILIARY_FREEZE.json')
    auxreuse=dict(freeze_ref=afr);auxroot=run/'models/consensus_auxiliary/final_pre2026'
    write(auxroot/'receipt.json',dict(status='TRAINED_WITH_COMPONENT_FAILURES',task_id=owner.TASK,source_pins=af['source_pins'],reuse_tuple=auxreuse,
        reuse_tuple_sha256=owner.values.digest(auxreuse),primary_pto_changed=False,model_sha256=blob(auxroot/'model.joblib')['sha256']))
    return dict(run=run,spec=spec,pf=pf,pfr=pfr,ff=ff,ffr=ffr,ef=ef,efr=efr,af=af,afr=afr,code=code,fslots=fslots,summary=summary)


@pytest.fixture
def bound(controls,monkeypatch):
    c=controls;run=c['run']
    monkeypatch.setattr(owner,'EXPECTED_RUN',run);monkeypatch.setattr(owner,'assert_safe_output_path',lambda *a,**kw:None)
    monkeypatch.setattr(owner.predictors,'contract',lambda *a:(c['spec'],c['pf'],c['pfr']))
    monkeypatch.setattr(owner.fusion,'contract',lambda r,p,m,y:(run,m,c['spec'],c['ff'],next(s for s in c['fslots'] if (s['packet_id'],s['method'],s['year'])==(p,m,y)),c['ffr']))
    monkeypatch.setattr(owner.evaluation,'contract',lambda *a:(run,c['ef'],c['efr']))
    monkeypatch.setattr(owner.downstream,'auxiliary_contract',lambda *a:(c['af'],c['pf'],c['afr']))
    monkeypatch.setattr(owner.registry,'REVIEW_SCOPE',dict(human_ref=c['code']))
    monkeypatch.setattr(owner,'write_json_atomic',write)
    def admitted_metadata_preflight(*,frozen_contract_ref,source_scope_ref):
        scope=owner._metadata(source_scope_ref['path']);api=owner.evaluation.account_inputs
        if scope.get('legacy_source_transport') is not None:
            pin,_,proof=api.source_fact_custody_reader(scope['legacy_source_transport'],scope.get('source_fact_construction_transport'))
        else:pin=owner._pin;proof=None
        records=[scope['source_ref']]+scope.get('test_original_refs',[])
        physical={}
        for record in records:
            path=pin(record);stat=path.stat();physical[str(path)]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
        return dict(scope=scope,pin=pin,physical_stats=physical,metadata_proofs=dict(source_fact_construction_transport=proof),
            frozen_contract_ref=frozen_contract_ref,source_scope_ref=source_scope_ref,numeric_prices_read=False,quote_numeric_evidence_read=False)
    monkeypatch.setattr(owner.evaluation.account_inputs,'metadata_preflight',admitted_metadata_preflight)
    monkeypatch.setattr(owner.predictors,'fit_one',lambda *a,**kw:pytest.fail('no predictor fitting'))
    monkeypatch.setattr(owner.fusion,'fit_one',lambda *a,**kw:pytest.fail('no fusion fitting'))
    monkeypatch.setattr(owner.evaluation.pq,'read_table',lambda *a,**kw:pytest.fail('no parquet decoding'))
    monkeypatch.setattr(owner.evaluation.joblib,'load',lambda *a,**kw:pytest.fail('no model/state loading'))
    return c


def test_metadata_builder_closes_full_plan_and_preserves_exposure_without_test_permission(bound):
    run=bound['run'];result=owner.build(run)
    assert len(result['candidate_predictors'])==228 and len(result['candidate_fusions'])==84
    assert [s['slot']['model_id'] for s in result['selected_predictors']]==[m for m in bound['spec']['model_ids'] if m in owner.fusion.CORE]
    assert result['test_2026_numeric_read_authorized'] is False and result['FAST3_Confirmation_access'] is False
    assert result['test_exposure_scope']['fresh_blind_holdout'] is False and 'OUTCOME_LITERAL_SEEN' in result['test_exposure_scope']['legacy_literal']
    assert result['vintage']=='UNKNOWN_RETAINED' and not (run/owner.FILENAME).exists()


def test_progress_cannot_drop_fixed_candidates_or_open_test_rows(bound):
    p=bound['run']/'logs/PREDICTOR_PROGRESS.json'
    with changed(p,lambda j:j['rows'].pop()):
        with pytest.raises(ValueError,match='CANNOT_SHRINK'):owner.build(bound['run'])
    s=bound['run']/'evaluation/consensus_account_summary.json'
    with changed(s,lambda j:j.update(test_2026_rows_read=1)):
        with pytest.raises(ValueError,match='PRE2026_SELECTION'):owner.build(bound['run'])


def test_unselected_failed_candidate_is_retained_but_selected_failure_blocks(bound):
    run=bound['run'];progress=run/'logs/PREDICTOR_PROGRESS.json'
    for model in (next(m for m in bound['spec']['model_ids'] if m not in owner.fusion.CORE),'ridge'):
        _,rp,_,_=owner.predictors.slot_paths(run,model,2026,5)
        def fail(j):
            for r in j['rows']:
                if (r['model_id'],r['year'],r['horizon'])==(model,2026,5):r['status']='FAILED'
        with changed(rp,lambda j:j.update(status='FAILED')),changed(progress,fail):
            if model=='ridge':
                with pytest.raises(ValueError,match='ALL_FIVE'):owner.build(run)
            else:assert next(r for r in owner.build(run)['candidate_predictors'] if r['slot']==dict(model_id=model,year=2026,horizon=5))['status']=='FAILED'


def test_selected_calibration_bytes_and_maturity_are_required(bound):
    run=bound['run'];_,rp,_,cp=owner.predictors.slot_paths(run,'ridge',2026,5);before=cp.read_bytes()
    try:
        cp.write_bytes(b'changed generated calibration')
        with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):owner.build(run)
    finally:cp.write_bytes(before)
    def later(j):
        j['reuse_tuple']['calibration_maturity_exclusive']='2026-01-02';j['reuse_tuple_sha256']=owner.values.digest(j['reuse_tuple'])
    with changed(rp,later):
        with pytest.raises(ValueError,match='MATURE_CHRONOLOGICAL'):owner.build(run)


def test_selected_fusion_failure_and_past_member_custody_block_freeze(bound):
    run=bound['run'];_,rp,_=owner.fusion.slot_paths(run,'core5','equal',2026)
    progress=run/'logs/FUSION_PROGRESS.json'
    def failrow(j):
        next(r for r in j['rows'] if (r['packet_id'],r['method'],r['year'])==('core5','equal',2026))['status']='FAILED'
    with changed(rp,lambda j:j.update(status='FAILED')),changed(progress,failrow):
        with pytest.raises(ValueError,match='SELECTED_FINAL_FUSION'):owner.build(run)
    def breakpin(j):
        j['reuse_tuple']['past_publication_pins'][0]['prediction_sha256']='0'*64;j['reuse_tuple_sha256']=owner.values.digest(j['reuse_tuple'])
    with changed(rp,breakpin):
        with pytest.raises(ValueError,match='PAST_PUBLICATION_CUSTODY'):owner.build(run)


def test_trained_unselected_fusion_with_missing_current_publication_is_terminal(bound):
    run=bound['run'];p=run/'logs/FUSION_PROGRESS.json'
    def unavailable(j):
        r=next(r for r in j['rows'] if (r['packet_id'],r['method'],r['year'])==('broad29','equal',2025));r.update(status='NOT_TESTABLE',reason='GENERATED missing current member')
    with changed(p,unavailable):
        entry=next(r for r in owner.build(run)['candidate_fusions'] if (r['slot']['packet_id'],r['slot']['method'],r['slot']['year'])==('broad29','equal',2025))
        assert entry['status']=='TRAINED' and entry['publication_disposition']=='NOT_TESTABLE'


def test_final_risk_and_complete_diagnostic_risk_closure_are_mandatory(bound):
    run=bound['run'];s=run/'evaluation/consensus_account_summary.json';rp=Path(bound['summary']['final_risk_receipt']['receipt_path'])
    with changed(rp,lambda j:j.update(status='FAILED_NO_RETRY')),changed(s,lambda j:j['final_risk_receipt'].update(status='FAILED_NO_RETRY')):
        with pytest.raises(ValueError,match='FINAL_RISK_NOT_FROZEN'):owner.build(run)
    with changed(s,lambda j:j['sensitivity_final_risk'].pop()):
        with pytest.raises(ValueError,match='DIAGNOSTIC_FINAL_RISK_CLOSURE'):owner.build(run)


def test_auxiliary_pending_and_active_lock_block_without_numeric_access(bound):
    run=bound['run'];rp=run/'models/consensus_auxiliary/final_pre2026/receipt.json'
    with changed(rp,lambda j:j.update(status='IN_PROGRESS')):
        with pytest.raises(ValueError,match='AUXILIARY_FINAL_DISPOSITION'):owner.build(run)
    lock=run/'CONSENSUS_FIT.lock';lock.write_text('synthetic active')
    try:
        with pytest.raises(ValueError,match='ACTIVE_FIT'):owner.build(run)
    finally:lock.unlink()


def test_final_publication_is_root_explicit_idempotent_and_hash_changes_fail_closed(bound):
    run=bound['run'];path=run/owner.FILENAME
    try:
        result=owner.publish_root(run);before=path.read_bytes()
        assert owner.validate(run)==result==owner.publish_root(run) and path.read_bytes()==before
        _,_,model,_=owner.predictors.slot_paths(run,'ridge',2026,5);original=model.read_bytes()
        try:
            model.write_bytes(b'changed generated model')
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):owner.validate(run)
            with pytest.raises(ValueError):owner.publish_root(run)
            assert path.read_bytes()==before
        finally:model.write_bytes(original)
    finally:
        if path.exists():path.unlink()


def test_ordinary_external_run_is_rejected_before_any_owner_contract(bound,monkeypatch):
    monkeypatch.setattr(owner.predictors,'contract',lambda *a:pytest.fail('wrong run cannot read control records'))
    with pytest.raises(ValueError,match='EXACT_TASK_RUN'):owner.build(bound['run']/'other')


def test_exact_legacy_transport_preserves_historical_refs_without_live_byte_relabelling(bound,monkeypatch):
    run=bound['run'];api=owner.evaluation.account_inputs;base=run/owner.TASK/'custody_regression';base.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(api.existing,'resolve',lambda *a:SimpleNamespace(backtest_root=base,cache_root=base))
    original=[];custody=[]
    for name in ('ca_fe3','owner1775','cash8a'):
        old=base/'frozen'/f'{name}.py';old.parent.mkdir(exist_ok=True);old.write_bytes(('OLD_GENERATED_'+name).encode());custody.append(owner._ref(old))
        live=base/'live'/f'{name}.py';live.parent.mkdir(exist_ok=True);live.write_bytes(('CURRENT_DIFFERENT_'+name).encode())
        original.append(dict(path=str(live),sha256=custody[-1]['sha256']))
    monkeypatch.setattr(api.existing,'OLD_CA',original[0])
    monkeypatch.setattr(api,'LEGACY_SOURCE_FACT_OWNER_REF',original[1])
    monkeypatch.setattr(api,'CONSTRUCTION_SOURCE_REF_WHITELIST',tuple(original[1:]))
    construction=[dict(original_ref=o,custody_ref=c,original_bytes_unchanged=True,old_ref_not_relabelled_as_current_producer=True) for o,c in zip(original[1:],custody[1:])]
    scope=dict(source_ref=owner._ref(original[0]['path']),test_original_refs=original,
        legacy_source_transport=[dict(original_ref=original[0],custody_ref=custody[0],original_bytes_unchanged=True)],source_fact_construction_transport=construction)
    path=base/'scope.json';write(path,scope)
    result=owner._account_source_custody(bound['efr'],owner._ref(path))
    assert result['historical_transport_declarations']['source_fact_construction_transport']==construction
    assert result['construction_transport_proof']['old_ref_not_relabelled_as_current_producer'] is True
    assert result['historical_ref_role']=='SOURCE_FACT_DECLARATIONS_NOT_CURRENT_PRODUCERS'
    observed={r['path']:r['sha256'] for r in result['physical_or_frozen_custody_refs']}
    assert all(observed[c['path']]==c['sha256'] for c in custody)
    assert observed[original[0]['path']]!=original[0]['sha256']
    with changed(path,lambda j:j['source_fact_construction_transport'][0].update(old_ref_not_relabelled_as_current_producer=False)):
        with pytest.raises(ValueError,match='SAME_BYTE_1775_OR_8A'):owner._account_source_custody(bound['efr'],owner._ref(path))
    with changed(path,lambda j:j['source_fact_construction_transport'][0]['original_ref'].update(sha256='0'*64)):
        with pytest.raises(ValueError,match='SAME_BYTE_1775_OR_8A'):owner._account_source_custody(bound['efr'],owner._ref(path))
    for ref in (custody[0],custody[1]):
        p=Path(ref['path']);before=p.read_bytes()
        try:
            p.write_bytes(b'CHANGED_GENERATED_CUSTODY')
            with pytest.raises(ValueError,match='CUSTODY_BYTES_CHANGED|ACCOUNT_SOURCE_CUSTODY_CHANGED'):
                owner._account_source_custody(bound['efr'],owner._ref(path))
        finally:p.write_bytes(before)


def test_account_snapshot_capacity_is_finite_and_checked_before_decode(bound,monkeypatch):
    run=bound['run'];record=copy.deepcopy(bound['summary']['stage2'][1]);path=Path(record['receipt_path']);before=path.read_bytes()
    assert owner.MAX_ACCOUNT_FLOWS==33 and owner.MAX_RISK_BUNDLES==1193
    bundle=lambda i:dict(cache_key=str(i)+'s'*300,method='LW',status='FITTED',budget=dict(preprocessing_estimates=1,estimator_state_estimations=1,total_state_estimations=2,cfg_count=1,seed_count=1))
    record['actual_risk_bundle_budgets']=[bundle(i) for i in range(800)]
    try:
        write(path,record);assert path.stat().st_size>262144
        accepted=owner._account_record(run,record,bound['efr']);assert accepted['status']=='COMPLETE'
    finally:path.write_bytes(before)
    oversized=run/'oversized_generated_metadata.json'
    with oversized.open('wb') as f:f.truncate(owner.ACCOUNT_METADATA_LIMIT+1)
    with monkeypatch.context() as scoped:
        scoped.setattr(owner.json,'loads',lambda *a,**kw:pytest.fail('stat gate must reject before metadata decode'))
        with pytest.raises(ValueError,match='BOUNDED_CANONICAL_METADATA'):owner._metadata(oversized,account=True)
    write(oversized,dict(actual_risk_bundle_budgets=[bundle(i) for i in range(owner.MAX_RISK_BUNDLES+1)]))
    with pytest.raises(ValueError,match='FINITE_PRIMARY_BUNDLE'):owner._metadata(oversized,account=True)
    write(oversized,dict(actual_risk_bundle_budgets=[dict(bundle(0),cache_key='s'*owner.PER_BUNDLE_METADATA_BYTES)]))
    with pytest.raises(ValueError,match='SCHEMA_SIZE_LIMIT'):owner._metadata(oversized,account=True)


@contextmanager
def recovery_controls(c,monkeypatch):
    """Generate the exact recovery history; never inspect a real run."""
    import shutil
    run=c['run'];base=run/owner.RECOVERY_DIRECTORY
    progress_path=run/'logs/FUSION_PROGRESS.json';scientific_path=owner.fusion.slot_paths(run,'core5','nnls',2024)[1]
    fit_log_path=run/'FIT_LOG.jsonl'
    backups={p:p.read_bytes() for p in (progress_path,scientific_path,fit_log_path)}
    try:
        first=json.loads(backups[progress_path]);retries=[];validations=[]
        common=dict(type='ModuleNotFoundError',message="No module named 'common'")
        for method in ('convex','stack_ridge','stack_elastic','stack_hgb','stack_mlp'):
            for year in (2023,2024,2025,2026):
                slot=dict(packet_id='core5',method=method,year=year);rp=owner.fusion.slot_paths(run,'core5',method,year)[1]
                live=owner._metadata(rp);archive=copy.deepcopy(live)
                archive.update(task_id=owner.TASK,status='FAILED',failure=common,fit_units=1 if method=='convex' else 2)
                ap=base/'failed_import_slots/core5'/method/str(year)/'receipt.json';write(ap,archive)
                retries.append(dict(slot=slot,archived_receipt_ref=owner._ref(ap),original_receipt_path=str(rp),
                    expected_reuse_tuple_sha256=archive['reuse_tuple_sha256'],previous_fit_units=archive['fit_units'],root_authorized_engineering_attempt_limit=1))
                validations.append(dict(slot=slot,status=live['status'],same_reuse_tuple=True,
                    reuse_tuple_sha256=live['reuse_tuple_sha256'],receipt_ref=owner._ref(rp)))
                row=next(r for r in first['rows'] if all(r[k]==v for k,v in slot.items()));row.update(status='FAILED',failure=common)
        failure=dict(type='RuntimeError',message='FIT_WORKER_FAILED:ValueError:NNLS_ZERO_OR_INVALID_SUM_NO_SUBSTITUTE')
        failed=owner._metadata(scientific_path);failed.update(status='FAILED',failure=failure);write(scientific_path,failed)
        row=next(r for r in first['rows'] if (r['packet_id'],r['method'],r['year'])==('core5','nnls',2024));row.update(status='FAILED',failure=failure)
        final=copy.deepcopy(first)
        for r in final['rows']:
            if (r['packet_id'],r['method'],r['year']) in [('core5',v['slot']['method'],v['slot']['year']) for v in retries]:
                r.pop('failure',None);r['status']='TRAINED' if r['year']==2026 else 'PUBLISHED'
        write(progress_path,final);write(base/'FIRST_PASS_FUSION_PROGRESS.json',first)
        first_log=b'GENERATED_PREVIOUS_FIT_START_WITH_FAILURE_CONSUMPTION\n'
        (base/'FIRST_PASS_FIT_LOG.jsonl').write_bytes(first_log);fit_log_path.write_bytes(first_log+b'GENERATED_SINGLE_RECOVERY_FIT_START\n')
        probe_path=base/'probe.json';write(probe_path,dict(status='PASS_4_FRESH_PARENT_SPAWN_CASES',source='PURE_SYNTHETIC',records=[
            dict(method=m,parent_preloaded=b,source='PURE_SYNTHETIC',real_inputs_read=False,real_2026_read=False,actual_receipts_changed=False,
                status='PASS_ORIGINAL_WORKER_WITH_PARENT_BOOTSTRAP' if b else 'EXPECTED_COMMON_IMPORT_FAILURE')
            for m in ('convex','stack_ridge') for b in (False,True)]))
        manifest=dict(schema='CONSENSUS_FUSION_PARENT_BOOTSTRAP_ENGINEERING_RECOVERY_R1',
            status='ROOT_AUTHORIZED_SINGLE_IMPORT_ENVIRONMENT_RECOVERY',task_id=owner.TASK,run=str(run),
            test_2026_read_authorized=False,source_spec_seed_parameters_data_sampling_selection_rule_changed=False,
            global_fit_log_preserved=True,fusion_freeze_ref=c['ffr'],source_pins=c['ff']['source_pins'],
            engineering_retry_slots=retries,first_pass_progress_ref=owner._ref(base/'FIRST_PASS_FUSION_PROGRESS.json'),
            first_pass_fit_log_ref=owner._ref(base/'FIRST_PASS_FIT_LOG.jsonl'),synthetic_probe_ref=owner._ref(probe_path),
            scientific_failures_preserved_without_retry=[dict(slot=dict(packet_id='core5',method='nnls',year=2024),failure=failure,receipt_ref=owner._ref(scientific_path))])
        path=base/'RECOVERY_MANIFEST.json';write(path,manifest);ref=owner._ref(path)
        monkeypatch.setattr(owner,'RECOVERY_MANIFEST_SHA256',ref['sha256'])
        job_path=base/'RECOVERY_JOB.json';write(job_path,dict(status='COMPLETED',task_id=owner.TASK,run=str(run),manifest_ref=ref,
            root_engineering_attempt=1,bootstrap='fusion.owner._native(spec[dependency_paths])',test_2026_read_authorized=False,retry_validation=validations))
        yield dict(base=base,manifest=manifest,manifest_ref=ref,job_path=job_path)
    finally:
        for p,b in backups.items():p.write_bytes(b)
        assert base.resolve().is_relative_to(run.resolve())
        if base.exists():shutil.rmtree(base)


def test_exact_import_recovery_closes_twenty_same_tuples_and_keeps_original_fit_consumption(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as controls:
        result=owner.build(bound['run']);history=result['engineering_recovery']
        assert len(history['slots'])==20 and history['previous_failed_fit_units']==36
        assert history['manifest_ref']==controls['manifest_ref']
        assert history['final_fit_log_ref']==result['fit_log_ref']
        assert history['scientific_failures_preserved_without_retry'][0]['slot']['method']=='nnls'
        assert history['scientific_selection_changed'] is False and history['test_2026_read_authorized'] is False
        assert owner._metadata(history['recovery_job_ref']['path'])['status']=='COMPLETED'
        assert not (bound['run']/owner.FILENAME).exists()


def test_recovery_manifest_archive_job_tuple_and_fit_prefix_drift_fail_closed(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as controls:
        run=bound['run'];complete=owner.build(run)
        def validate():
            return owner._engineering_recovery(run,bound['ff'],bound['ffr'],bound['fslots'],complete['candidate_fusions'],owner._ref(run/'FIT_LOG.jsonl'))
        with changed(Path(controls['manifest_ref']['path']),lambda x:x.update(global_fit_log_preserved=False)):
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):validate()
        archive=Path(controls['manifest']['engineering_retry_slots'][0]['archived_receipt_ref']['path'])
        with changed(archive,lambda x:x.update(fit_units=0)):
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):validate()
        with changed(controls['job_path'],lambda x:x.update(status='FAILED_NO_RESTART')):
            with pytest.raises(ValueError,match='RECOVERY_JOB_SUCCESSFUL_TERMINAL'):validate()
        with changed(controls['job_path'],lambda x:x['retry_validation'][0].update(same_reuse_tuple=False)):
            with pytest.raises(ValueError,match='RECOVERY_SAME_TUPLE'):validate()
        with changed(controls['job_path'],lambda x:x['retry_validation'].pop()):
            with pytest.raises(ValueError,match='RECOVERY_TERMINAL_VALIDATION_CANNOT_SHRINK'):validate()
        fit=run/'FIT_LOG.jsonl';before=fit.read_bytes()
        try:
            fit.write_bytes(b'REPLACED_PRIOR_FIT_CONSUMPTION'+before)
            with pytest.raises(ValueError,match='FIRST_PASS_FIT_LOG_PREFIX_CHANGED'):validate()
        finally:fit.write_bytes(before)


@contextmanager
def named_main_controls(c,r1,monkeypatch):
    import shutil
    run=c['run'];base=run/owner.NAMED_MAIN_DIRECTORY;old_job=r1['job_path'];fit=run/'FIT_LOG.jsonl'
    wait_path=run/'logs/ACCOUNT_EVALUATION_RECOVERY_WAIT_JOB.json';backups={p:p.read_bytes() for p in (old_job,fit)}
    try:
        base.mkdir(parents=True)
        original_job=owner._metadata(old_job);before_path=base/'FIRST_LAUNCHER_JOB_BEFORE_STOP.json';write(before_path,original_job)
        failed=copy.deepcopy(original_job);failed.update(status='FAILED_NO_RESTART',retry_validation=[],native_fit_started_in_recovery=False,
            verified_no_child_processes=True,verified_terminated_parent_pid=12345,previous_state_ref=owner._ref(before_path),
            failure=dict(type='LauncherEngineeringFailure',message='WINDOWS_MP_SPAWN_STDIN_MAIN_INVALID_ARGUMENT_BLOCKED_BEFORE_NATIVE_FIT_START'))
        write(old_job,failed)
        write(wait_path,dict(status='FAILED_NO_RESTART',task_id=owner.TASK,run=str(run),upstream_job=str(old_job),
            test_2026_read_authorized=False,failure=dict(type='RuntimeError',message='ENGINEERING_RECOVERY_FAILED_NO_RESTART'),
            evaluation_freeze_ref=c['efr'],source_ref=owner._ref(owner.evaluation.__file__)))
        progress=owner._metadata(run/'logs/FUSION_PROGRESS.json');progress.update(status='RUNNING',rows=progress['rows'][:16],slots_complete=16)
        write(base/'FUSION_PROGRESS.json',progress)
        archive=owner._metadata(r1['manifest']['engineering_retry_slots'][0]['archived_receipt_ref']['path'])
        spawn=copy.deepcopy(archive);spawn.update(status='IN_PROGRESS',fit_units=0);spawn.pop('failure')
        spawn_path=base/'unfitted_spawn_slot/core5/convex/2023/receipt.json';write(spawn_path,spawn)
        event=dict(event='CONSENSUS_FUSION_SLOT_STARTED',packet_id='core5',model_id='convex',year=2023,reuse_tuple_sha256=spawn['reuse_tuple_sha256'])
        first_log=Path(r1['manifest']['first_pass_fit_log_ref']['path']).read_bytes()
        stdin_log=base/'FIT_LOG.jsonl';stdin_log.write_bytes(first_log+json.dumps(event).encode()+b'\n')
        stop_path=base/'STOP_EVIDENCE.json';write(stop_path,dict(status='VERIFIED_UNFITTED_STDIN_PARENT_TERMINATED',fit_units=0,
            no_child_processes=True,parent_pid=12345,source_spec_data_sampling_seed_parameters_changed=False,test_2026_rows_read=0,
            spawn_slot_archived_receipt_ref=owner._ref(spawn_path),native_fit_log_tail=event))
        launcher=blob(base/'named_main_launcher.py')
        manifest=dict(schema='CONSENSUS_FUSION_NAMED_MAIN_ENGINEERING_CORRECTION_R2',status='ROOT_AUTHORIZED_NAMED_MAIN_CALLER_CORRECTION',
            task_id=owner.TASK,run=str(run),root_engineering_attempt=2,source_pins=c['ff']['source_pins'],
            original_recovery_manifest_ref=r1['manifest_ref'],engineering_retry_slots=r1['manifest']['engineering_retry_slots'],
            test_2026_read_authorized=False,source_spec_seed_parameters_data_sampling_selection_rule_changed=False,
            additional_scientific_retries_authorized=False,stdin_recovery_extra_attempt_started_events=1,stdin_recovery_native_fit_started_events=0,
            failed_stdin_recovery_job_ref=owner._ref(old_job),failed_account_wait_job_ref=owner._ref(wait_path),named_main_launcher_ref=launcher,
            first_stdin_progress_ref=owner._ref(base/'FUSION_PROGRESS.json'),first_stdin_fit_log_ref=owner._ref(stdin_log),
            stop_evidence_ref=owner._ref(stop_path),unfitted_spawn_receipt_ref=owner._ref(spawn_path))
        fields=('original_recovery_manifest_ref','failed_stdin_recovery_job_ref','failed_account_wait_job_ref','named_main_launcher_ref',
            'first_stdin_progress_ref','first_stdin_fit_log_ref','stop_evidence_ref','unfitted_spawn_receipt_ref')
        manifest['required_immutable_refs']=[manifest[k] for k in fields]
        manifest_path=base/'LAUNCHER_CORRECTION_MANIFEST_R2.json';write(manifest_path,manifest);manifest_ref=owner._ref(manifest_path)
        monkeypatch.setattr(owner,'NAMED_MAIN_MANIFEST_SHA256',manifest_ref['sha256'])
        fit.write_bytes(stdin_log.read_bytes()+b'GENERATED_NAMED_MAIN_FIT_STARTED_AND_AUXILIARY_COMPLETE\n');snapshot=owner._ref(fit)
        validations=[{k:v for k,v in r.items() if k!='same_reuse_tuple'} for r in original_job['retry_validation']]
        job_path=base/'RECOVERY_JOB_R2.json';write(job_path,dict(status='COMPLETED',task_id=owner.TASK,run=str(run),manifest_ref=manifest_ref,
            root_engineering_attempt=2,named_main_launcher_ref=launcher,retry_validation=validations,test_2026_read_authorized=False,
            fusion_slots=84,auxiliary_status='TRAINED_WITH_COMPONENT_FAILURES',fit_log_ref=snapshot))
        fit.write_bytes(fit.read_bytes()+b'GENERATED_ACCOUNT_FITS_APPEND_AFTER_DOWNSTREAM_JOB\n')
        yield dict(base=base,manifest=manifest,manifest_ref=manifest_ref,manifest_path=manifest_path,job_path=job_path,snapshot_ref=snapshot)
    finally:
        for p,b in backups.items():p.write_bytes(b)
        if wait_path.exists():wait_path.unlink()
        assert base.resolve().is_relative_to(run.resolve())
        if base.exists():shutil.rmtree(base)


def test_named_main_correction_preserves_failed_launcher_and_earlier_log_snapshot(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as r1:
        with named_main_controls(bound,r1,monkeypatch) as r2:
            result=owner.build(bound['run']);history=result['engineering_recovery'];chain=history['named_main_correction']
            assert history['manifest_ref']==r1['manifest_ref'] and chain['manifest_ref']==r2['manifest_ref']
            assert len(history['slots'])==20 and history['previous_failed_fit_units']==36
            assert owner._metadata(chain['failed_stdin_recovery_job_ref']['path'])['status']=='FAILED_NO_RESTART'
            assert chain['own_unfitted_launcher_terminated'] is True and chain['original_stdin_native_fit_started'] is False
            snapshot=chain['completed_downstream_fit_log_snapshot']
            assert snapshot['ref']==r2['snapshot_ref'] and snapshot['ref']['sha256']!=result['fit_log_ref']['sha256']
            assert snapshot['authenticated_prefix_bytes']>chain['first_stdin_fit_log_bytes']
            assert result['test_2026_numeric_read_authorized'] is False and not (bound['run']/owner.FILENAME).exists()


def test_named_main_correction_chain_scope_custody_tuple_and_snapshot_drift_reject(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as r1:
        with named_main_controls(bound,r1,monkeypatch) as r2:
            run=bound['run'];complete=owner.build(run)
            def validate():
                return owner._engineering_recovery(run,bound['ff'],bound['ffr'],bound['fslots'],complete['candidate_fusions'],owner._ref(run/'FIT_LOG.jsonl'))
            with changed(r2['manifest_path'],lambda x:x.update(additional_scientific_retries_authorized=True)):
                with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):validate()
            with changed(r1['job_path'],lambda x:x.update(status='COMPLETED')):
                with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):validate()
            with changed(r2['job_path'],lambda x:x.update(status='FAILED_NO_RESTART')):
                with pytest.raises(ValueError,match='NAMED_MAIN_JOB_SUCCESSFUL_TERMINAL'):validate()
            with changed(r2['job_path'],lambda x:x['retry_validation'][0].update(reuse_tuple_sha256='e'*64)):
                with pytest.raises(ValueError,match='RECOVERY_SAME_TUPLE'):validate()
            with changed(r2['job_path'],lambda x:x['fit_log_ref'].update(sha256='e'*64)):
                with pytest.raises(ValueError,match='DOWNSTREAM_LOG_SNAPSHOT_NOT_PRESERVED'):validate()
            with changed(Path(r2['manifest']['stop_evidence_ref']['path']),lambda x:x.update(fit_units=1)):
                with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):validate()


@contextmanager
def account_cap_controls(c,r4,monkeypatch):
    import shutil
    run=c['run'];base=run/owner.ACCOUNT_RECOVERY_DIRECTORY;base.mkdir(parents=True)
    fit=run/'FIT_LOG.jsonl';fit_before=fit.read_bytes();old_job_path=run/'logs/ACCOUNT_EVALUATION_NAMED_MAIN_R2.json'
    old_freeze_path=run/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json'
    assert old_freeze_path!=run/owner.evaluation.FREEZE
    write(old_freeze_path,c['ef']);old_ref=owner._ref(old_freeze_path);write(base/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json',c['ef'])
    source_root=base/'source_custody';source_root.mkdir();sources={};source_sha={}
    for role,module,name in [('evaluation_runner',owner.evaluation,'evaluation_runner_before_freeze_r2.py'),('joint_policy',owner.evaluation.joint,'joint_policy_before_cap_fix.py')]:
        ap=source_root/name;ap.write_bytes(('GENERATED_ORIGINAL_SOURCE_BYTES_'+role).encode());archive=owner._ref(ap)
        sources[role]=dict(original_ref=dict(path=str(Path(module.__file__)),sha256=archive['sha256']),archived_ref=archive);source_sha[role]=archive['sha256']
    monkeypatch.setattr(owner,'ACCOUNT_SOURCE_CUSTODY_ROOT',source_root);monkeypatch.setattr(owner,'ACCOUNT_OLD_SOURCE_SHA256',source_sha)
    wait_path=Path(r4['manifest']['failed_account_wait_job_ref']['path']);wait=owner._metadata(wait_path)
    wait.update(evaluation_freeze_ref=old_ref,source_ref=sources['evaluation_runner']['original_ref']);write(wait_path,wait)
    r4['manifest']['failed_account_wait_job_ref']=owner._ref(wait_path)
    fields=('original_recovery_manifest_ref','failed_stdin_recovery_job_ref','failed_account_wait_job_ref','named_main_launcher_ref','first_stdin_progress_ref','first_stdin_fit_log_ref','stop_evidence_ref','unfitted_spawn_receipt_ref')
    r4['manifest']['required_immutable_refs']=[r4['manifest'][k] for k in fields];write(r4['manifest_path'],r4['manifest']);r4_ref=owner._ref(r4['manifest_path'])
    monkeypatch.setattr(owner,'NAMED_MAIN_MANIFEST_SHA256',r4_ref['sha256'])
    r4job=owner._metadata(r4['job_path']);r4job['manifest_ref']=r4_ref;write(r4['job_path'],r4job)
    before_job_path=base/'FIRST_ACCOUNT_JOB_BEFORE_STOP.json';write(before_job_path,dict(status='RUNNING_AUTHORIZED_PRE2026_ACCOUNT_REPLAY'))
    old_job=dict(status='FAILED_NO_RESTART',task_id=owner.TASK,run=str(run),test_2026_read_authorized=False,
        terminated_between_native_workers=True,verified_terminated_parent_pid=24680,previous_state_ref=owner._ref(before_job_path),
        failure=dict(type='ConfirmedEngineeringFailure',message='PARTIAL_REBALANCING_REINTRODUCES_WEIGHT_ABOVE_DECLARED_10_PERCENT_CAP'),
        upstream_recovery_job_ref=owner._ref(r4['job_path']))
    write(old_job_path,old_job)
    receipts=[];artifact_names=('accounting_exceptions','daily','diagnostics','entitlements','execution_results','fills','orders','positions','settlement_ledger','state')
    for method,status,units,failure,names in [('equal','FAILED_NO_RETRY',66,dict(type='ValueError',reason='invalid explicit target weights'),['state']),
        ('fixed_weight','IN_PROGRESS',0,None,[]),('median','NOT_TESTABLE',12,dict(type='NotTestable',reason='ACCOUNT_CORPORATE_LIFECYCLE_UNQUALIFIED'),list(artifact_names))]:
        fid=owner.evaluation.flow_id(method);root=base/'first_account_flows'/fid;root.mkdir(parents=True);artifacts={};artifact_custody={}
        for name in names:
            filename=name+('.joblib' if name=='state' else '.parquet');ap=root/filename;ap.write_bytes(('GENERATED_OLD_ARTIFACT_'+name).encode());archive=owner._ref(ap)
            original=dict(path=str(run/'evaluation/consensus_account'/fid/filename),sha256=archive['sha256']);artifacts[name]=original;artifact_custody[name]=dict(original_ref=original,archived_ref=archive)
        identity=owner.values.digest(dict(flow_id=fid,original_cap_repair=False));rp=root/'receipt.json'
        receipt=dict(task_id=owner.TASK,flow_id=fid,status=status,fit_units=units,failure=failure,identity_sha256=identity,freeze_ref=old_ref,
            receipt_path=str(run/'evaluation/consensus_account'/fid/'receipt.json'),artifacts=artifacts);write(rp,receipt)
        receipts.append(dict(flow_id=fid,status=status,fit_units=units,failure=failure,identity_sha256=identity,receipt_ref=owner._ref(rp),artifact_refs=artifacts,artifact_custody=artifact_custody))
    old_log=base/'FIT_LOG.jsonl';old_log.write_bytes(fit_before+b'GENERATED_PRIOR_78_ACCOUNT_FIT_UNITS_PRESERVED\n');fit.write_bytes(old_log.read_bytes()+b'GENERATED_CAP_REPAIRED_ACCOUNT_FIT_UNITS\n')
    current=owner.evaluation.source_pins();launcher=blob(base/'account_named_main.py')
    preflight=base/'preflight.json';write(preflight,dict(task_id=owner.TASK,status='PASS_SYNTHETIC_ONLY_PENDING_INDEPENDENT_REVIEW',source_ref=current['joint_policy']))
    review=base/'review.json';write(review,dict(task_id=owner.TASK,status='PASS_WITH_SCOPE_LIMITS',source_ref=current['joint_policy'],
        engineering_receipt_ref=owner._ref(preflight),real_2026_data_or_observations_read=False,actual_fit_or_replay_by_reviewer=False))
    stop_path=base/'STOP_AND_SOURCE_CUSTODY.json';write(stop_path,dict(status='CONFIRMED_CONTROL_CAP_ENGINEERING_FAILURE_PRESERVED',
        terminated_between_native_workers=True,parent_pid=24680,old_account_job_ref=owner._ref(old_job_path),old_account_freeze_ref=owner._ref(base/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json'),
        old_fit_log_ref=owner._ref(old_log),source_custody=sources,predictor_fusion_auxiliary_refit=False,fit_log_reset=False,test_2026_content_read=False))
    m=dict(schema='CONSENSUS_ACCOUNT_DECLARED_CAP_ENGINEERING_RECOVERY_R3',status='ROOT_AUTHORIZED_EXISTING_CAP_EXECUTION_REPAIR',task_id=owner.TASK,run=str(run),
        root_engineering_attempt=3,recipe_unchanged=True,source_scope_unchanged=True,fit_log_reset=False,model_selection_feedback_from_failure=False,
        predictor_fusion_auxiliary_refit=False,test_2026_read_authorized=False,
        engineering_scope='ENFORCE_EXISTING_EXPLICIT_10_PERCENT_TARGET_CAP_AFTER_FIXED_CONTROLS_NO_SELECTOR_OR_RECIPE_CHANGE',
        source_custody=sources,current_evaluation_source_pins=current,old_account_freeze_ref=old_ref,
        archived_old_account_freeze_ref=owner._ref(base/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE.json'),new_account_freeze_ref=c['efr'],
        old_account_job_ref=owner._ref(old_job_path),old_account_job_before_stop_ref=owner._ref(before_job_path),stop_evidence_ref=owner._ref(stop_path),
        old_fit_log_ref=owner._ref(old_log),named_main_launcher_ref=launcher,policy_preflight_ref=owner._ref(preflight),policy_independent_review_ref=owner._ref(review),
        old_account_receipts=receipts,archived_risk_fit_units=78)
    fields=('old_account_freeze_ref','archived_old_account_freeze_ref','new_account_freeze_ref','old_account_job_ref','old_account_job_before_stop_ref','stop_evidence_ref','old_fit_log_ref','named_main_launcher_ref','policy_preflight_ref','policy_independent_review_ref')
    m['required_immutable_refs']=[m[k] for k in fields]+[sources[k]['archived_ref'] for k in sorted(sources)]+[r['receipt_ref'] for r in receipts]+[r['artifact_custody'][name]['archived_ref'] for r in receipts for name in sorted(r['artifact_custody'])]
    path=base/'ACCOUNT_RECOVERY_MANIFEST_R3.json';write(path,m);ref=owner._ref(path);monkeypatch.setattr(owner,'ACCOUNT_RECOVERY_MANIFEST_SHA256',ref['sha256'])
    job_path=base/'ACCOUNT_JOB_R3.json';job=dict(status='COMPLETED',task_id=owner.TASK,run=str(run),manifest_ref=ref,root_engineering_attempt=3,
        account_freeze_ref=c['efr'],named_main_launcher_ref=launcher,test_2026_read_authorized=False,scientific_result_status='COMPLETE',
        summary_ref=owner._ref(run/'evaluation/consensus_account_summary.json'),final_fit_log_ref=owner._ref(fit));write(job_path,job)
    try:yield dict(base=base,manifest=m,manifest_ref=ref,job_path=job_path,source_root=source_root)
    finally:
        fit.write_bytes(fit_before)
        if old_job_path.exists():old_job_path.unlink()
        if old_freeze_path.exists():old_freeze_path.unlink()
        assert base.resolve().is_relative_to(run.resolve())
        if base.exists():shutil.rmtree(base)


def test_account_cap_recovery_authenticates_old_source_artifact_bytes_and_preserves_78_fit_units(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as r1:
        with named_main_controls(bound,r1,monkeypatch) as r4:
            with account_cap_controls(bound,r4,monkeypatch) as r5:
                result=owner.build(bound['run']);history=result['account_engineering_recovery']
                assert history['manifest_ref']==r5['manifest_ref'] and history['archived_risk_fit_units']==78
                assert len(history['original_account_dispositions'])==3 and history['predictor_fusion_auxiliary_refit'] is False
                old=history['historical_source_custody']['evaluation_runner']['original_ref']
                assert owner.values.sha(old['path'])!=old['sha256']  # old fact is accepted only through archived bytes.
                assert result['test_2026_numeric_read_authorized'] is False
                with changed(r5['job_path'],lambda j:j.update(status='FAILED_SOURCE_GATE')):
                    with pytest.raises(ValueError,match='ACCOUNT_RECOVERY_JOB_SUCCESSFUL_TERMINAL'):owner.build(bound['run'])
                original=Path(history['historical_source_custody']['evaluation_runner']['archived_ref']['path'])
                before=original.read_bytes()
                try:
                    original.write_bytes(b'changed archived old source')
                    with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):owner.build(bound['run'])
                finally:original.write_bytes(before)


def test_no_eligible_account_path_can_only_publish_terminal_audit_without_system_freeze(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as r1:
        with named_main_controls(bound,r1,monkeypatch) as r4:
            with account_cap_controls(bound,r4,monkeypatch) as r5:
                run=bound['run'];summary_path=run/'evaluation/consensus_account_summary.json';backup={summary_path:summary_path.read_bytes()}
                try:
                    summary=copy.deepcopy(bound['summary'])
                    for r in summary['stage1']:
                        path=Path(r['receipt_path']);backup[path]=path.read_bytes();r.update(status='NOT_TESTABLE',reason='UNQUALIFIED_CAUSAL_ACCOUNT_SOURCE');write(path,r)
                    summary=dict(status='NOT_TESTABLE',task_id=owner.TASK,freeze_ref=bound['efr'],reason='NO_COMPLETE_ACCOUNT_CANDIDATE',
                        stage1=summary['stage1'],stage2=[],test_2026_rows_read=0);write(summary_path,summary)
                    job=owner._metadata(r5['job_path']);job.update(scientific_result_status='NOT_TESTABLE',summary_ref=owner._ref(summary_path));write(r5['job_path'],job)
                    with pytest.raises(ValueError,match='COMPLETE_PRE2026_SELECTION'):owner.build(run)
                    result=owner.audit_terminal(run)
                    assert result['status']=='RESEARCH_TERMINAL_NO_COMPLETE_SELECTED_SYSTEM' and result['selected_flow'] is None
                    assert result['complete_selected_system_frozen'] is False and result['test_2026_numeric_read_authorized'] is False
                    assert not (run/owner.FILENAME).exists() and not (run/owner.TERMINAL_AUDIT_FILENAME).exists()
                    audit=owner.publish_terminal_root(run);assert audit==result==owner.publish_terminal_root(run)
                    assert (run/owner.TERMINAL_AUDIT_FILENAME).exists() and not (run/owner.FILENAME).exists()
                    with changed(r5['job_path'],lambda x:x['final_fit_log_ref'].update(sha256='f'*64)):
                        with pytest.raises(ValueError,match='ACCOUNT_RECOVERY_JOB_SUCCESSFUL_TERMINAL'):owner.audit_terminal(run)
                finally:
                    for path,data in backup.items():path.write_bytes(data)
                    audit_path=run/owner.TERMINAL_AUDIT_FILENAME
                    if audit_path.exists():audit_path.unlink()



@contextmanager
def source_environment_controls(c,monkeypatch):
    """Exact path-only environment bridge using generated custody/control bytes."""
    import shutil
    run=c['run'];base=run/owner.SOURCE_ENV_DIRECTORY;base.mkdir(parents=True)
    capbase=run/owner.ACCOUNT_RECOVERY_DIRECTORY;capbase.mkdir(parents=True)
    paths=[run/'ACCOUNT_SOURCE_SCOPE.json',run/'ACCOUNT_SOURCE_SCOPE_R2.json',run/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R2.json',
        run/owner.evaluation.FREEZE,run/'FIT_LOG.jsonl']
    backup={p:p.read_bytes() if p.exists() else None for p in paths}
    source_root=base/'source_archives';source_root.mkdir()
    current=owner.evaluation.source_pins();old_bytes=Path(owner.evaluation.__file__).read_bytes().replace(
        b"FREEZE='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R3.json'",b"FREEZE='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R2.json'",1)
    archive=source_root/'evaluation_runner_before_source_environment_r4.py';archive.write_bytes(old_bytes);old_runner_archive=owner._ref(archive)
    monkeypatch.setattr(owner,'ACCOUNT_SOURCE_CUSTODY_ROOT',source_root)
    monkeypatch.setattr(owner,'SOURCE_ENV_OLD_RUNNER_SHA256',old_runner_archive['sha256'])
    old_runner=dict(path=str(Path(owner.evaluation.__file__)),sha256=old_runner_archive['sha256'])
    cap_pins=copy.deepcopy(current);cap_pins['runner']=old_runner
    cash=run/'source_custody/joint_cash_bindings_8f57_source.py';cash.parent.mkdir(parents=True);cash.write_bytes(b'GENERATED_EXACT_CASH_OWNER_BYTES')
    custody=owner._ref(cash);recovered=base/'generated_original_cash.py';recovered.write_bytes(cash.read_bytes())
    monkeypatch.setattr(owner,'EXACT_CASH_SHA256',custody['sha256']);monkeypatch.setattr(owner,'EXACT_CASH_RECOVERED_PATH',recovered)
    canonical='scripts.research.a2.data.joint_cash_bindings'
    monkeypatch.setattr(owner.evaluation.account_inputs.existing.source,'cash',SimpleNamespace(__name__=canonical,__file__=str(cash)))
    original=dict(path=str(owner.predictors.REPO/'scripts/research/a2/data/joint_cash_bindings.py'),sha256=custody['sha256'])
    transport=dict(schema='EXACT_BYTE_CANONICAL_MODULE_TRANSPORT_R1',canonical_module=canonical,original_ref=original,
        custody_ref=custody,recovered_original_ref=owner._ref(recovered),original_bytes_unchanged=True,current_project_file_modified=False,
        data_clock_changed=False,source_vintage_changed=False)
    scope=dict(source_dependency_refs=dict(joint_cash_bindings=original),unchanged_recipe_marker='generated')
    old_scope=run/'ACCOUNT_SOURCE_SCOPE.json';write(old_scope,scope)
    scope_new=copy.deepcopy(scope);scope_new['source_dependency_refs']['joint_cash_bindings']=custody;scope_new['executable_source_transport']=transport
    new_scope=run/'ACCOUNT_SOURCE_SCOPE_R2.json';write(new_scope,scope_new)
    old_freeze_path=run/'CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R2.json'
    old_freeze=dict(recipe=dict(generated_fixed_recipe=True),account_source_scope_ref=owner._ref(old_scope),source_pins=cap_pins,
        previous_account_freeze_ref=blob(base/'generated_r1_freeze.json'))
    write(old_freeze_path,old_freeze);old_freeze_ref=owner._ref(old_freeze_path)
    new_freeze=copy.deepcopy(old_freeze);new_freeze.update(account_source_scope_ref=owner._ref(new_scope),source_pins=current,
        previous_account_freeze_ref=old_freeze_ref,source_environment_revision=dict(exact_bytes=True))
    write(run/owner.evaluation.FREEZE,new_freeze);new_freeze_ref=owner._ref(run/owner.evaluation.FREEZE)
    old_log=capbase/'FIT_LOG.jsonl';old_log.write_bytes(b'GENERATED_PRIOR_78_RISK_FIT_UNITS\n')
    before_log=base/'before_account_FIT_LOG.jsonl';before_log.write_bytes(old_log.read_bytes())
    log=run/'FIT_LOG.jsonl';log.write_bytes(old_log.read_bytes()+b'GENERATED_NEW_ACCOUNT_FIT_UNITS\n')
    cap_path=capbase/'ACCOUNT_RECOVERY_MANIFEST_R3.json';write(cap_path,dict(generated_only=True));cap_ref=owner._ref(cap_path)
    cap=dict(current_evaluation_source_pins=cap_pins,new_account_freeze_ref=old_freeze_ref,old_fit_log_ref=owner._ref(old_log),
        old_account_job_ref=cap_ref,old_account_job_before_stop_ref=cap_ref,stop_evidence_ref=cap_ref,
        old_account_freeze_ref=old_freeze['previous_account_freeze_ref'],archived_old_account_freeze_ref=old_freeze['previous_account_freeze_ref'],
        old_account_receipts=[],named_main_launcher_ref=blob(capbase/'generated_old_launcher.py'),policy_preflight_ref=cap_ref,policy_independent_review_ref=cap_ref)
    failed_job_path=capbase/'ACCOUNT_JOB_R3.json';write(failed_job_path,dict(status='FAILED_NO_RESTART',task_id=owner.TASK,run=str(run),manifest_ref=cap_ref,
        root_engineering_attempt=3,account_freeze_ref=old_freeze_ref,test_2026_read_authorized=False,
        failure=dict(type='ValueError',message='ACCOUNT_SOURCE_CUSTODY_CHANGED:'+str(Path(original['path'])))))
    launcher=blob(base/'generated_named_launcher.py')
    identity=dict(fresh_named_process=True,bootstrap_executed_once_per_process=True,actual_helper_main_called=False,synthetic_empty_dataclass_roundtrip=True)
    for key in ('parent','spawn_child'):
        identity[key]=dict(actual_helper_ref=dict(launcher,bytes=17),cash_source_ref=dict(custody,bytes=19),actual_helper_main_called=False,
            actual_data_load_or_fit_called=False,canonical_single_bootstrap=True,scope_dep_matches_owner_path=True,e_reader_same_module=True,
            existing_source_cash_same_object=True,d456_fact_owner_cash_same_object=True,private_factory_cash_same_object=True,
            package_and_sysmodules_same_object=True,ca_class_namespace_shared=True,
            live50c_ref=dict(path=original['path'],sha256='c'*64))  # immutable historical observation, never an executable pin.
    proof_path=base/'generated_metadata_preflight.json';write(proof_path,dict(status='PASS_ACTUAL_R4_HELPER_PARENT_AND_SPAWN_PLUS_METADATA_ONLY',
        task_id=owner.TASK,scope_ref=dict(owner._ref(new_scope),bytes=11),evaluation_freeze_ref=dict(new_freeze_ref,bytes=13),
        metadata_only=dict(status='PASS',numeric_prices_read=False,quote_numeric_evidence_read=False),actual_helper_identity=identity,
        boundaries=dict(load_account_inputs_called=False,real_prices_decoded=False,real_features_or_labels_read=False,real_2026_read=False,fits_started=False)))
    m=dict(schema='CONSENSUS_ACCOUNT_EXACT_SOURCE_ENVIRONMENT_RECOVERY_R4',status='ROOT_AUTHORIZED_EXACT_FROZEN_SOURCE_ENVIRONMENT_REPAIR',
        task_id=owner.TASK,run=str(run),root_engineering_attempt=4,account_cap_recovery_manifest_ref=cap_ref,
        canonical_source_bootstrap_at_module_top_level=True,failed_previous_job_additional_fit_units=0,
        fit_log_reset=False,fixed_recipe_changed=False,source_policy_changed=False,data_or_clock_changed=False,native_scientific_retries=False,
        selection_feedback=False,predictor_fusion_auxiliary_refit=False,test_2026_read_authorized=False,
        exact_source_transport=transport,failed_previous_account_job_ref=owner._ref(failed_job_path),old_source_scope_ref=owner._ref(old_scope),
        new_source_scope_ref=owner._ref(new_scope),old_account_freeze_ref=old_freeze_ref,new_account_freeze_ref=new_freeze_ref,
        old_runner_source_ref=old_runner,old_runner_custody_ref=old_runner_archive,current_evaluation_source_pins=current,
        metadata_preflight_ref=owner._ref(proof_path),named_main_launcher_ref=launcher,before_account_fit_log_ref=owner._ref(before_log),
        before_source_gate_fit_log_ref=owner._ref(old_log),before_account_fit_log_ref_current=dict(path=str(log),sha256=owner._ref(old_log)['sha256']),
        foreign_project_source_observation=dict(current_ref=dict(path=original['path'],sha256='f'*64),
            role='HISTORICAL_OBSERVATION_NOT_REQUIRED_EXECUTABLE_PIN',task_wrote_file=False))
    fields=('account_cap_recovery_manifest_ref','failed_previous_account_job_ref','old_source_scope_ref','new_source_scope_ref',
        'old_account_freeze_ref','new_account_freeze_ref','old_runner_custody_ref','metadata_preflight_ref','named_main_launcher_ref','before_account_fit_log_ref')
    m['required_immutable_refs']=[m[k] for k in fields]+[custody,owner._ref(recovered)]
    manifest_path=base/'SOURCE_ENVIRONMENT_RECOVERY_MANIFEST_R4.json';write(manifest_path,m);env_ref=owner._ref(manifest_path)
    monkeypatch.setattr(owner,'SOURCE_ENV_MANIFEST_SHA256',env_ref['sha256'])
    summary=dict(status='NOT_TESTABLE',test_2026_rows_read=0);summary_path=base/'generated_summary.json';write(summary_path,summary)
    job_path=base/'ACCOUNT_JOB_R4.json';write(job_path,dict(status='COMPLETED',task_id=owner.TASK,run=str(run),manifest_ref=env_ref,root_engineering_attempt=4,
        account_freeze_ref=new_freeze_ref,named_main_launcher_ref=launcher,test_2026_read_authorized=False,
        summary_ref=owner._ref(summary_path),scientific_result_status=summary['status'],final_fit_log_ref=owner._ref(log),
        source_scope_ref=m['new_source_scope_ref'],executable_source_ref=custody,predictor_fusion_auxiliary_refit=False))
    try:yield dict(base=base,manifest=m,manifest_path=manifest_path,manifest_ref=env_ref,cap=cap,cap_ref=cap_ref,
        freeze_ref=new_freeze_ref,summary=summary,summary_ref=owner._ref(summary_path),log_ref=owner._ref(log),
        job_path=job_path,failed_job_path=failed_job_path,cash=cash)
    finally:
        for path,data in backup.items():
            if data is None:
                if path.exists():path.unlink()
            else:path.write_bytes(data)
        for path in (base,capbase,run/'source_custody'):
            assert path.resolve().is_relative_to(run.resolve())
            if path.exists():shutil.rmtree(path)


def test_source_environment_bridge_preserves_failed_source_gate_history_and_only_accepts_completed_r4(bound,monkeypatch):
    with source_environment_controls(bound,monkeypatch) as r6:
        environment=owner._source_environment_authority(bound['run'],r6['cap'],r6['cap_ref'])
        authority=dict(manifest=r6['cap'],manifest_ref=r6['cap_ref'],source_environment=environment,
            historical_source_custody={},historical_reference_role='GENERATED_ARCHIVED_CUSTODY')
        history=owner._account_recovery_history(bound['run'],authority,r6['freeze_ref'],r6['summary'],r6['summary_ref'],r6['log_ref'])
        assert owner._metadata(r6['failed_job_path'])['status']=='FAILED_NO_RESTART'
        assert history['source_environment']['source_gate_additional_fit_units']==0
        assert history['source_environment']['manifest_ref']==r6['manifest_ref']
        assert history['archived_risk_fit_units']==78 and history['test_2026_read_authorized'] is False
        assert owner.values.sha(r6['manifest']['old_runner_source_ref']['path'])!=r6['manifest']['old_runner_source_ref']['sha256']
        assert history['source_environment']['before_account_fit_log_ref_current']['sha256']!=r6['log_ref']['sha256']
        assert not (bound['run']/owner.FILENAME).exists()
        with changed(r6['job_path'],lambda j:j.update(status='FAILED_NO_RESTART')):
            with pytest.raises(ValueError,match='ACCOUNT_RECOVERY_JOB_SUCCESSFUL_TERMINAL'):
                owner._account_recovery_history(bound['run'],authority,r6['freeze_ref'],r6['summary'],r6['summary_ref'],r6['log_ref'])


def test_source_environment_bridge_rejects_manifest_custody_old_failure_and_scope_drift(bound,monkeypatch):
    with source_environment_controls(bound,monkeypatch) as r6:
        def verify():return owner._source_environment_authority(bound['run'],r6['cap'],r6['cap_ref'])
        with changed(r6['manifest_path'],lambda m:m.update(failed_previous_job_additional_fit_units=1)):
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):verify()
        before=r6['cash'].read_bytes()
        try:
            r6['cash'].write_bytes(b'INEXACT_GENERATED_CASH_OWNER')
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):verify()
        finally:r6['cash'].write_bytes(before)
        with changed(r6['failed_job_path'],lambda j:j.update(status='COMPLETED')):
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):verify()
        with changed(Path(r6['manifest']['new_source_scope_ref']['path']),lambda s:s.update(unauthorized_recipe=True)):
            with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):verify()
        monkeypatch.setattr(owner.evaluation.account_inputs.existing.source,'cash',SimpleNamespace(
            __name__='scripts.research.a2.data.joint_cash_bindings',__file__=r6['manifest']['exact_source_transport']['original_ref']['path']))
        with pytest.raises(ValueError,match='ROOT_MUST_CANONICAL_BOOTSTRAP_EXACT_8F'):verify()



@pytest.mark.parametrize('year',[2025,2026])
def test_unfitted_not_testable_fusion_null_progress_path_is_canonical_metadata_only(bound,year):
    run=bound['run'];progress=run/'logs/FUSION_PROGRESS.json'
    slot=next(s for s in bound['fslots'] if (s['packet_id'],s['method'],s['year'])==('broad29','equal',year))
    _,rp,_=owner.fusion.slot_paths(run,'broad29','equal',year)
    reason='MISSING_MEMBER_PUBLICATION:GENERATED_UNAVAILABLE_MEMBER:2021'
    receipt=dict(status='NOT_TESTABLE',task_id=owner.TASK,packet_id='broad29',model_id='equal',year=year,
        owner_id=slot['owner_id'],members=slot['members'],reason=reason,fit_units=0,source_pins=bound['ff']['source_pins'],freeze_ref=bound['ffr'])
    def unavailable(j):
        r=next(r for r in j['rows'] if (r['packet_id'],r['method'],r['year'])==('broad29','equal',year))
        r.update(status='NOT_TESTABLE',reason=reason,receipt_path=None)
    with changed(rp,lambda j:(j.clear(),j.update(receipt))),changed(progress,unavailable):
        result=owner.build(run)
        entry=next(r for r in result['candidate_fusions'] if (r['slot']['packet_id'],r['slot']['method'],r['slot']['year'])==('broad29','equal',year))
        assert entry['status']=='NOT_TESTABLE' and entry['artifacts']=={}
        assert entry['receipt']==owner._ref(rp) and entry['unavailable_fit_reason']==reason
        assert entry['progress_receipt_binding']=='CANONICAL_UNFITTED_NOT_TESTABLE_RECEIPT'
        assert result['test_2026_numeric_read_authorized'] is False
        for field,value in [('task_id','WRONG_TASK'),('owner_id',-1),('members',[]),('fit_units',1),('reason','DIFFERENT_REASON')]:
            with changed(rp,lambda j:j.update({field:value})):
                with pytest.raises(ValueError,match='NULL_PROGRESS_RECEIPT_ONLY_FOR_BOUND_UNFITTED_FUSION'):owner.build(run)
        with changed(progress,lambda j:next(r for r in j['rows'] if (r['packet_id'],r['method'],r['year'])==('broad29','equal',year)).update(receipt_path=str(rp.with_name('wrong_receipt.json')))):
            with pytest.raises(ValueError,match='PROGRESS_RECEIPT_PATH_CHANGED'):owner.build(run)
    # A trained or published candidate must retain its exact physical fit path.
    with changed(progress,lambda j:next(r for r in j['rows'] if (r['packet_id'],r['method'],r['year'])==('broad29','equal',year)).update(receipt_path=None)):
        with pytest.raises(ValueError,match='NULL_PROGRESS_RECEIPT_ONLY_FOR_BOUND_UNFITTED_FUSION'):owner.build(run)



def test_stop_custody_binds_exact_archived_freeze_role_even_when_original_has_same_bytes(bound,monkeypatch):
    with recovery_controls(bound,monkeypatch) as r1:
        with named_main_controls(bound,r1,monkeypatch) as r4:
            with account_cap_controls(bound,r4,monkeypatch) as r5:
                run=bound['run'];m=r5['manifest'];stop_path=Path(m['stop_evidence_ref']['path'])
                assert m['old_account_freeze_ref']['sha256']==m['archived_old_account_freeze_ref']['sha256']
                assert owner._metadata(stop_path)['old_account_freeze_ref']==m['archived_old_account_freeze_ref']
                assert owner.build(run)['account_engineering_recovery']['manifest_ref']==r5['manifest_ref']
                # Rebind generated control hashes to reach the semantic guard;
                # same bytes at the original run path cannot replace archive role.
                stop=owner._metadata(stop_path);stop['old_account_freeze_ref']=m['old_account_freeze_ref'];write(stop_path,stop)
                m['stop_evidence_ref']=owner._ref(stop_path);m['required_immutable_refs'][5]=m['stop_evidence_ref']
                manifest_path=r5['base']/'ACCOUNT_RECOVERY_MANIFEST_R3.json';write(manifest_path,m);manifest_ref=owner._ref(manifest_path)
                monkeypatch.setattr(owner,'ACCOUNT_RECOVERY_MANIFEST_SHA256',manifest_ref['sha256'])
                job=owner._metadata(r5['job_path']);job['manifest_ref']=manifest_ref;write(r5['job_path'],job)
                with pytest.raises(ValueError,match='ACCOUNT_STOP_AND_HISTORICAL_CUSTODY_REQUIRED'):owner.build(run)


@pytest.fixture
def child_bound(bound,tmp_path,monkeypatch):
    """Generated parent custody + child records; no research artifacts decoded."""
    parent=bound['run'];run=tmp_path/'exact_continuation';run.mkdir();backups={}
    def alter(path,value):
        backups.setdefault(path,path.read_bytes());write(path,value)
    # The actual final scope has one failed EBM and37 successful predictor slots.
    _,ebm,_,_=owner.predictors.slot_paths(parent,'ebm',2026,5)
    pr=owner._metadata(parent/'logs/PREDICTOR_PROGRESS.json')
    er=owner._metadata(ebm);er.update(status='FAILED',failure='GENERATED_EBM_FAILURE_PRESERVED');alter(ebm,er)
    next(r for r in pr['rows'] if r['model_id']=='ebm' and r['year']==2026 and r['horizon']==5)['status']='FAILED'
    alter(parent/'logs/PREDICTOR_PROGRESS.json',pr)
    for kind,slots in (('predictor',owner.predictors.planned_slots(bound['spec'])),('fusion',bound['fslots'])):
        for slot in slots:
            if slot['year']!=2026:continue
            if kind=='predictor':_,rp,_,_=owner.predictors.slot_paths(parent,slot['model_id'],2026,slot['horizon'])
            else:_,rp,_=owner.fusion.slot_paths(parent,slot['packet_id'],slot['method'],2026)
            r=owner._metadata(rp);r['reuse_tuple'].update(train_frame_sha256='c'*64,calibration_frame_sha256='d'*64)
            r['reuse_tuple_sha256']=owner.values.digest(r['reuse_tuple']);alter(rp,r)
    monkeypatch.setattr(owner.fusion,'CONTINUATION_RUN',run)
    monkeypatch.setattr(owner.fusion,'PARENT_RUN',parent)
    archives={n:blob(run/'historical'/(n+'.py')) for n in ('historical_fusion_adapter_archive_ref','historical_owner_archive_ref')}
    scope_path=run/'CONTINUATION_SCOPE.json';write(scope_path,dict(task_id=owner.TASK,research_id=owner.fusion.CONTINUATION_RESEARCH_ID))
    scope_ref=owner._ref(scope_path);refs=dict(run=str(parent),predictor_freeze_ref=bound['pfr'],fusion_freeze_ref=bound['ffr'],
        parent_fit_log_ref=owner._ref(parent/'FIT_LOG.jsonl'),**archives)
    models,oldf,progress,_=owner._candidate_dispositions(parent,bound['spec'],bound['pf'],bound['pfr'],bound['ff'],bound['ffr'])
    auxiliary=owner._auxiliary_disposition(parent)
    audit=dict(task_id=owner.TASK,run=str(parent),candidate_predictors=models,candidate_fusions=oldf,auxiliary=auxiliary,
        test_2026_numeric_read_authorized=False)
    audit_path=run/'historical/terminal_audit.json';write(audit_path,audit);refs['terminal_audit_ref']=owner._ref(audit_path)
    facts=dict(scope=dict(parent_custody=refs),scope_ref=scope_ref,parent=parent,spec=bound['spec'],pf=bound['pf'],ff=bound['ff'],audit=audit,prior=1098)
    def guarded_facts(r):
        assert Path(r)==run
        for name in ('predictor_freeze_ref','fusion_freeze_ref','parent_fit_log_ref','terminal_audit_ref',*archives):owner._pin(refs[name])
        return facts
    monkeypatch.setattr(owner.fusion,'_continuation_facts',guarded_facts)
    monkeypatch.setattr(owner.fusion,'reader_run',lambda r:guarded_facts(r)['parent'])
    slots=owner.fusion.continuation_slots(bound['spec']);ff=dict(source_pins=dict(owner=bound['code']),ordered_slots=slots,
        predictor_freeze_ref=bound['pfr'],continuation_scope_ref=scope_ref,prior_fit_units=1098)
    write(run/'CONSENSUS_FUSION_FREEZE.json',ff);ffr=owner._ref(run/'CONSENSUS_FUSION_FREEZE.json')
    def fusion_contract(r,p,m,y):
        if Path(r)==run:return run,m,bound['spec'],ff,next(s for s in slots if (s['packet_id'],s['method'],s['year'])==(p,m,y)),ffr
        return parent,m,bound['spec'],bound['ff'],next(s for s in bound['fslots'] if (s['packet_id'],s['method'],s['year'])==(p,m,y)),bound['ffr']
    monkeypatch.setattr(owner.fusion,'contract',fusion_contract)
    rows=[]
    for slot in slots:
        _,rp,mp=owner.fusion.slot_paths(run,slot['packet_id'],slot['method'],slot['year'])
        original=next(e for e in oldf if e['slot']['packet_id']=='core5' and e['slot']['method']=='equal' and e['slot']['year']==slot['year'])
        reuse=copy.deepcopy(owner._metadata(original['receipt']['path'])['reuse_tuple'])
        reuse.update(model_id=slot['method'],owner_id=slot['owner_id'],source_pins=ff['source_pins'],freeze_ref=ffr,
            research_id=owner.fusion.CONTINUATION_RESEARCH_ID,continuation_scope_ref=scope_ref,prior_fit_units=1098)
        r=dict(status='TRAINED',model_id=slot['method'],year=slot['year'],packet_id=slot['packet_id'],receipt_path=str(rp),
            source_pins=ff['source_pins'],reuse_tuple=reuse,reuse_tuple_sha256=owner.values.digest(reuse),model_sha256=blob(mp)['sha256'])
        write(rp,r);row=dict(packet_id=slot['packet_id'],method=slot['method'],year=slot['year'],status='TRAINED',receipt_path=str(rp))
        if slot['year']<2026:
            output=run/'predictions/consensus_fusion/core5'/slot['method']/f"{slot['year']}.parquet"
            write(output.with_suffix('.receipt.json'),dict(status='PUBLISHED',test_2026_rows_read=0,source_pins=ff['source_pins'],
                fit_receipt_sha256=owner.values.sha(rp),fit_receipt_path=str(rp),reuse_tuple_sha256=r['reuse_tuple_sha256'],
                sha256=blob(output)['sha256'],model_sha256=r['model_sha256'],prediction_role='MODEL_OOF',
                packet_id=slot['packet_id'],model_id=slot['method'],year=slot['year']))
            row['status']='PUBLISHED'
        rows.append(row)
    write(run/'logs/FUSION_PROGRESS.json',dict(status='COMPLETED_ALL_FIXED_SLOTS',slots_complete=4,total_slots=4,rows=rows,test_2026_content_read=False))
    (run/'FIT_LOG.jsonl').write_text(json.dumps(dict(event='FIT_STARTED',fit_units=1))+'\n',encoding='utf-8')
    def passed(name):
        path=run/'metadata'/f'{name}.json';write(path,dict(status='PASS_WITH_SCOPE_LIMITS',test_2026_content_read=False));return owner._ref(path)
    code=bound['code'];manifest_path=run/'metadata/source_completion.json'
    manifest=dict(schema='CONSENSUS_SOURCE_COMPLETION_ACCOUNT_INPUT_MANIFEST_R1',status='QUALIFIED_SOURCE_FACTS_FOR_PRE2026_ACCOUNTING_ONLY',
        task_id=owner.TASK,research_id=owner.fusion.CONTINUATION_RESEARCH_ID,scope_start='2023-01-01',scope_end_exclusive='2026-01-01',
        strict_PIT=False,target_support_expansion=False,source_refs=[code])
    for k in ('ordinary_bundle_ref','ordinary_owner_ref','ordinary_cash_owner_ref','special_events_ref','price_links_ref','fx_source_book_ref','fx_parser_ref'):manifest[k]=code
    write(manifest_path,manifest);mr=owner._ref(manifest_path)
    scope=run/'metadata/account_scope.json';write(scope,dict(source_completion_manifest_ref=mr,source_ref=code));scope_pin=owner._ref(scope)
    ef=dict(research_id=owner.fusion.CONTINUATION_RESEARCH_ID,recipe=owner.evaluation.recipe_for_run(run),account_source_scope_ref=scope_pin,
        continuation_scope_ref=scope_ref,prior_fit_units=1098,actual_input_preflight_ref=passed('actual_input'),
        independent_review_refs=[passed('source_review')],research_identity_review_ref=passed('registry_review'),
        account_convention_scope_ref=passed('convention'),account_fx_convention_scope_ref=passed('fx_convention'),
        fx_source_availability_qualification_ref=passed('fx_qualification'))
    newf,_=owner._child_fusion_dispositions(run,ff,ffr,parent,bound['spec'])
    completion=dict(schema=owner.FINAL_CALIBRATION_SCHEMA,status=owner.FINAL_CALIBRATION_STATUS,task_id=owner.TASK,
        research_id=owner.fusion.CONTINUATION_RESEARCH_ID,run=str(run),continuation_scope_ref=scope_ref,
        native_training_refitted=False,original_support_preserved=True,test_2026_content_read=False,cutoff='2026-01-01 exclusive',
        completion_spec_ref=passed('calibration_spec'),correction_sidecar_ref=blob(run/'metadata/sidecar.parquet'),
        source_qualification_ref=passed('calibration_source'),independent_review_refs=[passed('calibration_review')])
    for kind,entries,output in (('predictor',models,'predictor_completions'),('fusion',oldf+newf,'fusion_completions')):
        selected=[e for e in entries if e['status']=='TRAINED' and e['slot']['year']==2026 and (kind=='predictor' or e['slot']['packet_id']=='core5')]
        result=[]
        for i,e in enumerate(selected):
            base=run/'models/consensus_final_calibration_completion'/kind/str(i);old=owner._metadata(e['receipt']['path']);reuse=copy.deepcopy(old['reuse_tuple'])
            reuse.update(calibration_frame_sha256='e'*64,completion_spec_ref=completion['completion_spec_ref'])
            artifacts=dict(model=blob(base/'model.joblib'),calibration=blob(base/'calibration.parquet'))
            r=dict(status='CALIBRATION_COMPLETED',kind=kind,slot=e['slot'],task_id=owner.TASK,research_id=owner.fusion.CONTINUATION_RESEARCH_ID,
                completion_spec_ref=completion['completion_spec_ref'],correction_sidecar_ref=completion['correction_sidecar_ref'],
                original_fit_receipt_ref=e['receipt'],original_model_ref=e['artifacts']['model'],native_training_refitted=False,test_2026_content_read=False,
                reuse_tuple=reuse,reuse_tuple_sha256=owner.values.digest(reuse),original_reuse_tuple_sha256=old['reuse_tuple_sha256'],
                model_sha256=artifacts['model']['sha256'],calibration_sha256=artifacts['calibration']['sha256'])
            write(base/'receipt.json',r);artifacts['receipt']=owner._ref(base/'receipt.json')
            item=dict(slot=e['slot'],status='CALIBRATION_COMPLETED',original_fit_receipt_ref=e['receipt'],original_model_ref=e['artifacts']['model'],
                raw_estimator_and_scaler_reused_same_bytes=True,artifacts=artifacts)
            if kind=='predictor':item['original_calibration_ref']=e['artifacts']['calibration']
            result.append(item)
        completion[output]=result
    completion['fit_log_snapshot_ref']=owner._ref(run/'FIT_LOG.jsonl')
    spec=dict(schema='CONSENSUS_SOURCE_CORRECTION_FINAL_CALIBRATION_SUPPLEMENT_R1',status='AUTHORIZED_PRE2026_CALIBRATION_ONLY',
        task_id=owner.TASK,research_id=owner.fusion.CONTINUATION_RESEARCH_ID,run=str(run),continuation_scope_ref=scope_ref,
        prior_fit_units=1098,max_fit_units=10000,correction_sidecar_ref=completion['correction_sidecar_ref'],
        source_qualification_ref=completion['source_qualification_ref'],independent_review_refs=completion['independent_review_refs'],
        source_pins=dict(owner=bound['code']),native_training_refit_authorized=False,test_2026_read_authorized=False,
        predictor_slots=[e['slot'] for e in completion['predictor_completions']],fusion_slots=[e['slot'] for e in completion['fusion_completions']])
    sp=Path(completion['completion_spec_ref']['path']);write(sp,spec);completion['completion_spec_ref']=owner._ref(sp)
    for entries in (completion['predictor_completions'],completion['fusion_completions']):
        for item in entries:
            rp=Path(item['artifacts']['receipt']['path']);r=owner._metadata(rp)
            r['completion_spec_ref']=completion['completion_spec_ref'];r['reuse_tuple']['completion_spec_ref']=completion['completion_spec_ref']
            r['reuse_tuple_sha256']=owner.values.digest(r['reuse_tuple']);write(rp,r);item['artifacts']['receipt']=owner._ref(rp)
    cp=run/owner.FINAL_CALIBRATION_RELATIVE;write(cp,completion);ef['final_calibration_completion_ref']=owner._ref(cp)
    write(run/owner.evaluation.FREEZE,ef);efr=owner._ref(run/owner.evaluation.FREEZE)
    monkeypatch.setattr(owner.evaluation,'contract',lambda r:(run,ef,efr) if Path(r)==run else (parent,bound['ef'],bound['efr']))
    def metadata_only_preflight(*,frozen_contract_ref,source_scope_ref):
        sc=owner._metadata(owner._pin(source_scope_ref));m=owner._metadata(owner._pin(sc['source_completion_manifest_ref']))
        physical={}
        for ref in [sc['source_ref'],sc['source_completion_manifest_ref'],*m['source_refs'],*[m[k] for k in ('ordinary_bundle_ref','ordinary_owner_ref','ordinary_cash_owner_ref','special_events_ref','price_links_ref','fx_source_book_ref','fx_parser_ref')]]:
            path=owner._pin(ref);stat=path.stat();physical[str(path)]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
        return dict(scope=sc,pin=owner._pin,physical_stats=physical,metadata_proofs=dict(source_fact_construction_transport=None),
            source_dependency_custody_proof=dict(current_source_relabelled=False),source_completion=dict(manifest_ref=sc['source_completion_manifest_ref']),
            frozen_contract_ref=frozen_contract_ref,source_scope_ref=source_scope_ref,numeric_prices_read=False,quote_numeric_evidence_read=False)
    monkeypatch.setattr(owner.evaluation.account_inputs,'metadata_preflight',metadata_only_preflight)
    method=owner.fusion.owner.NNLS_ZERO_ABSTAIN;flow=lambda m,r='LW',a='cost_aware',t=None:owner.evaluation.flow_id(m,r,a,t,run=run)
    def account(m,r='LW',a='cost_aware',diagnostic=None):
        fid=flow(m,r,a,None if diagnostic is None else diagnostic['tag']);base=run/'evaluation/consensus_account'/fid
        fee=copy.deepcopy(ef['recipe']['fee_config'])
        if diagnostic:fee.update(one_way_all_in_bps=diagnostic['one_way_all_in_bps'],fixed_per_fill_usd=diagnostic['fixed_per_fill_usd'])
        item=dict(task_id=owner.TASK,status='COMPLETE',flow_id=fid,fusion_method=m,risk_method=r,allocation_method=a,fee_config=fee,
            receipt_path=str(base/'receipt.json'),freeze_ref=efr,artifacts=dict(state=blob(base/'state.joblib')))
        write(base/'receipt.json',item);return item
    stage1=[account(m) for m in ef['recipe']['fusion_methods']]
    stage2=[account(method,p['risk_method'],p['allocation_method']) for p in ef['recipe']['stage2']]
    diag=[account(method,diagnostic=d) for d in ef['recipe']['diagnostic_sensitivities']]
    def final(r):
        fid=r['flow_id'];base=run/'models/consensus_final_policy'/fid
        record=dict(task_id=owner.TASK,status='COMPLETE',selected_flow=fid,receipt_path=str(base/'receipt.json'),freeze_ref=efr,
            identity_sha256=owner.values.digest(dict(selected_flow=fid,selected_receipt_sha256=owner.values.sha(r['receipt_path']),freeze_ref=efr)),
            artifacts=dict(state=blob(base/'state.joblib')),test_rows_read=0,final_risk_fit_cutoff='2026-01-01 exclusive')
        write(base/'receipt.json',record);return record
    chosen=next(r for r in stage2 if r['risk_method']=='LW' and r['allocation_method']=='cost_aware')
    summary=dict(status='COMPLETE',task_id=owner.TASK,freeze_ref=efr,test_2026_rows_read=0,sensitivity_selection_feedback=False,
        conditional_research_only=True,strict_PIT_certified=False,selected_fusion=method,selected_flow=chosen['flow_id'],stage1=stage1,stage2=stage2,
        sensitivities=diag,final_risk_receipt=final(chosen),sensitivity_final_risk=[final(r) for r in diag]);write(run/'evaluation/consensus_account_summary.json',summary)
    try:yield dict(run=run,parent=parent,ef=ef,efr=efr,ff=ff,ffr=ffr,facts=facts,summary=summary,completion=completion,cp=cp,archives=archives)
    finally:
        for path,data in backups.items():path.write_bytes(data)


def test_child_full_freeze_keeps_228_84_plus_four_and_replaces_final_calibration_only(child_bound):
    c=child_bound;r=owner.build(c['run'])
    assert r['schema']=='CONSENSUS_FINAL_SYSTEM_FREEZE_CONTINUATION_R2'
    assert len(r['candidate_predictors'])==228 and len(r['parent_candidate_fusions'])==84 and len(r['child_candidate_fusions'])==4
    assert len(r['candidate_fusions'])==88 and len(r['account_dispositions'])==14+17+4
    assert len(r['selected_predictors'])==5 and r['selected_fusion']['slot']['method']==owner.fusion.owner.NNLS_ZERO_ABSTAIN
    assert r['fit_budget']['total_fit_units']==1099 and r['fit_budget']['prior_fit_units']==1098
    assert r['final_calibration_completion']['ref']==c['ef']['final_calibration_completion_ref']
    assert r['all_parent_coordinates_exact_equivalent'] is False and r['test_2026_numeric_read_authorized'] is False
    assert r['A2_already_exposed'] is True and r['FAST3_Confirmation_access'] is False
    assert next(e for e in r['candidate_predictors'] if e['slot']==dict(model_id='ebm',year=2026,horizon=5))['status']=='FAILED'
    assert r['auxiliary']['current_source_relabelled'] is False


def test_child_exact_archived_parent_custody_and_terminal_packets_cannot_drift(child_bound):
    c=child_bound;archive=Path(c['archives']['historical_owner_archive_ref']['path']);before=archive.read_bytes()
    try:
        archive.write_bytes(b'changed historical source')
        with pytest.raises(ValueError,match='REFERENCE_BYTES_CHANGED'):owner.build(c['run'])
    finally:archive.write_bytes(before)
    c['facts']['audit']['candidate_fusions']=c['facts']['audit']['candidate_fusions'][:-1]
    with pytest.raises(ValueError,match='IMMUTABLE_PARENT_TERMINAL'):owner.build(c['run'])


@pytest.mark.parametrize('case',['missing','proposed','shrink','future','train_change','artifact_tamper','supplement_unfrozen','log_snapshot_drift'])
def test_child_final_calibration_completion_is_required_and_exact(child_bound,case):
    c=child_bound;completion=copy.deepcopy(c['completion'])
    if case=='missing':c['ef'].pop('final_calibration_completion_ref')
    elif case=='proposed':completion['status']='PROPOSED'
    elif case=='shrink':completion['predictor_completions'].pop()
    elif case in ('future','train_change'):
        e=completion['predictor_completions'][0];rp=Path(e['artifacts']['receipt']['path']);r=owner._metadata(rp)
        if case=='future':r['reuse_tuple']['calibration_sessions'][-1]='2026-01-02'
        else:r['reuse_tuple']['train_frame_sha256']='f'*64
        r['reuse_tuple_sha256']=owner.values.digest(r['reuse_tuple']);write(rp,r);e['artifacts']['receipt']=owner._ref(rp)
    elif case=='artifact_tamper':Path(completion['fusion_completions'][0]['artifacts']['model']['path']).write_bytes(b'tamper')
    elif case=='supplement_unfrozen':
        sp=Path(completion['completion_spec_ref']['path']);value=owner._metadata(sp);value['status']='PROPOSED';write(sp,value)
        completion['completion_spec_ref']=owner._ref(sp)
    else:completion['fit_log_snapshot_ref']['sha256']='0'*64
    if case!='missing':
        write(c['cp'],completion);c['ef']['final_calibration_completion_ref']=owner._ref(c['cp'])
    with pytest.raises(ValueError):owner.build(c['run'])


def test_child_account_scope_source_qualification_budget_and_final_risk_are_hard_gates(child_bound):
    c=child_bound;original=copy.deepcopy(c['ef']['independent_review_refs']);c['ef']['independent_review_refs']=[]
    with pytest.raises(ValueError,match='INDEPENDENT_SOURCE_REVIEWS'):owner.build(c['run'])
    c['ef']['independent_review_refs']=original
    risk=c['summary']['final_risk_receipt'];rp=Path(risk['receipt_path'])
    with changed(rp,lambda r:r.update(status='NOT_TESTABLE')):
        with pytest.raises(ValueError,match='ACCOUNT_SUMMARY_CUSTODY'):owner.build(c['run'])
    log=c['run']/'FIT_LOG.jsonl';log.write_text((json.dumps(dict(event='FIT_STARTED',fit_units=1))+'\n')*8903,encoding='utf-8')
    with pytest.raises(ValueError,match='INHERITED_GLOBAL_FIT_BUDGET'):owner.build(c['run'])


def test_child_metadata_capacity_is_exact_one_added_flow_and_checked_before_decode(child_bound,monkeypatch):
    path=child_bound['run']/'generated_capacity.json'
    bundle=dict(cache_key='x',budget=dict(x=1));extra=owner.MAX_RISK_BUNDLES+1
    write(path,dict(actual_risk_bundle_budgets=[bundle]*extra))
    assert len(owner._metadata(path,account=True,continuation=True)['actual_risk_bundle_budgets'])==extra
    with pytest.raises(ValueError,match='FINITE_PRIMARY_BUNDLE'):owner._metadata(path,account=True)
    write(path,dict(actual_risk_bundle_budgets=[bundle]*(owner.MAX_RISK_BUNDLES+37)))
    with pytest.raises(ValueError,match='FINITE_PRIMARY_BUNDLE'):owner._metadata(path,account=True,continuation=True)
    path.write_bytes(b'x'*(262144+(owner.MAX_RISK_BUNDLES+36)*owner.PER_BUNDLE_METADATA_BYTES+1))
    monkeypatch.setattr(json,'loads',lambda *a,**kw:pytest.fail('stat gate must precede decode'))
    with pytest.raises(ValueError,match='BOUNDED_CANONICAL_METADATA'):owner._metadata(path,account=True,continuation=True)


def test_source_qualified_patch_is_not_fit_authority_and_exact_two_key_role(tmp_path):
    code=blob(tmp_path/'source.py');patch=blob(tmp_path/'patch.parquet');path=tmp_path/'source_qualification.json'
    value=dict(schema='CONSENSUS_SOURCE_QUALIFIED_FINAL_CALIBRATION_LABEL_PATCH_R1',
        status='SOURCE_QUALIFIED_TWO_ORIGINAL_MATURE_KEYS_ONLY_PENDING_CALIBRATION_FIT_AUTHORITY',task_id=owner.TASK,
        research_id=owner.fusion.CONTINUATION_RESEARCH_ID,patch_ref=patch,rows=2,exact_signal_keys=['2025-10-07|BN','2025-10-08|BN'],
        fold_year_key=2026,fold_cutoff_exclusive='2026-01-01',calibration_start='2025-10-07 00:00:00',
        all_changed_keys_calibration_only=True,native_training_rows_changed=0,original_masks_and_support_unchanged=True,
        canonical_inputs_overwritten=False,features_or_prices_or_2026_payload_read=False)
    for role in ('support_ref','official_share_right_ref','source_panel_ref','label_formula_owner_ref','generator_ref'):value[role]=code
    write(path,value);pin=owner._ref(path)
    assert owner._qualified_metadata_ref(pin,name='final_calibration_source',expected_patch=patch)['rows']==2
    with pytest.raises(ValueError,match='QUALIFIED_METADATA'):owner._qualified_metadata_ref(pin,name='actual_input_preflight')
    with pytest.raises(ValueError,match='EXACT_SOURCE_QUALIFIED'):owner._qualified_metadata_ref(pin,name='final_calibration_source',expected_patch=code)
    value['native_training_rows_changed']=1;write(path,value)
    with pytest.raises(ValueError,match='EXACT_SOURCE_QUALIFIED'):owner._qualified_metadata_ref(owner._ref(path),name='final_calibration_source',expected_patch=patch)
