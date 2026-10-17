"""Exact-child terminal evidence; reuse the immutable final-closure owner.

No fit, estimator, account replay, numeric parquet decoder or selection occurs.
Only Root may publish after all active jobs finish. This is never a system freeze.
"""
from __future__ import annotations
import argparse
from io import BytesIO
from pathlib import Path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.evaluation import consensus_final_freeze as base

CLOSURE_OWNER_SHA = '8e1a811f43c7de19c23bdfbf44badf8329df21d9d4d591513019a29c34e82d9a'
EVALUATION_OWNER_SHA = 'acbe5224a155969ee28fbc13bdba858744a6e7439bc60a777a0f274d8f9c3b6f'
SCHEMA = 'CONSENSUS_RESEARCH_TERMINAL_AUDIT_CONTINUATION_R2'
STATUS = 'RESEARCH_TERMINAL_NO_COMPLETE_SELECTED_SYSTEM'
require = base.require


def _context(run):
    require(base.values.sha(base.__file__) == CLOSURE_OWNER_SHA, 'IMMUTABLE_51_CALIBRATION_CLOSURE_OWNER_CHANGED')
    require(base.values.sha(base.evaluation.__file__) == EVALUATION_OWNER_SHA, 'FROZEN_CHILD_EVALUATION_OWNER_CHANGED')
    run = Path(run).resolve()
    require(run == base.fusion.CONTINUATION_RUN.resolve(), 'EXACT_CHILD_TERMINAL_RUN_REQUIRED')
    return base._run(run)


EBM_SUMMARY_FILENAME = 'EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1.json'
EBM_FREEZE_SHA = 'd29602fe06e576da709f02b8f02bbaa889cd67dcff2c64d63a0f1d2615b667e5'
_EBM_RECEIPT_FIELDS = {'status', 'phase', 'model_id', 'native_model_id', 'year', 'horizon', 'receipt_path',
    'fit_units', 'reuse_tuple', 'reuse_tuple_sha256', 'source_pins', 'retry_source_pins', 'previous_attempt_refs',
    'parent_failure_preserved', 'test_2026_rows_read', 'primary_core5_selection_includes_retry_ebm',
    'model_ref', 'calibration_ref', 'native_checkpoint_ref', 'native_model_reused_ref', 'failure'}


def _ebm_metadata(path):
    # Reuse the source owner's lexical projection; never decode scalar sigma or calibration rows.
    path = Path(path)
    require(path.stat().st_size <= 65536, 'BOUNDED_EBM_RECEIPT_METADATA_REQUIRED')
    base._pin(base._ref(path), path)
    with path.open('rb') as handle:
        return base.evaluation.account_inputs._JsonProjection(handle).metadata_fields(_EBM_RECEIPT_FIELDS)


def _ebm_terminal(run, budget):
    path = run / EBM_SUMMARY_FILENAME
    if not path.exists():
        require(not (run / 'CONSENSUS_EBM_TEARDOWN_RETRY_FREEZE.json').exists(),
                'FROZEN_EBM_RETRY_TERMINAL_SUMMARY_REQUIRED')
        return None
    from scripts.research.a2.training import consensus_ebm_teardown_retry as retry
    _, spec, freeze_ref = retry.contract(run)
    require(freeze_ref == dict(path=str(run / retry.FREEZE), sha256=EBM_FREEZE_SHA), 'EXACT_EBM_RETRY_FREEZE_REQUIRED')
    summary = base._metadata(path)
    require(summary.get('schema') == 'CONSENSUS_EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1'
            and summary.get('status') == 'FIXED_SIX_ATTEMPTS_FINISHED' and summary.get('task_id') == base.TASK
            and summary.get('research_id') == base.fusion.CONTINUATION_RESEARCH_ID and summary.get('freeze_ref') == freeze_ref
            and summary.get('original_failures_preserved') is True and summary.get('old_37_plus_14_unchanged') is True
            and summary.get('test_2026_read') is False and summary.get('test_2026_rows_read') == 0
            and summary.get('real_2026_prediction_published') is False, 'HONEST_EBM_SIX_SLOT_TERMINAL_REQUIRED')
    expected_slots = [dict(model_id='ebm', year=year, horizon=5) for year in range(2021, 2027)]
    rows = summary['slots']
    require([row['slot'] for row in rows] == expected_slots == spec['ordered_slots']
            and len(spec['original_failed_receipt_refs']) == 6, 'EXACT_ORDERED_SIX_EBM_DISPOSITIONS_REQUIRED')
    require(spec['max_new_physical_attempts_per_slot'] == 2 and spec['max_new_bucket_fit_units'] == 24
            and spec['primary_core5_selection_includes_retry_ebm'] is False and spec['wide_32_fusion_authorized'] is False
            and spec['test_2026_read_authorized'] is False and spec['real_2026_prediction_publication_allowed'] is False,
            'EBM_RETRY_CANNOT_CHANGE_PRIMARY_SELECTION_OR_TEST_SCOPE')
    if summary.get('queue_claim_ref') is not None:
        queue_path = base._pin(summary['queue_claim_ref'], run / 'EBM_TEARDOWN_RETRY_QUEUE_CLAIM_R1.json')
        queue = base._metadata(queue_path)
        require(queue.get('schema') == 'CONSENSUS_EBM_AFTER_PTO_QUEUE_R1' and queue.get('freeze_ref') == freeze_ref
                and queue.get('test_2026_values_allowed') is False, 'EBM_QUEUE_CUSTODY_CHANGED')
    dispositions, fit_counts = [], {}
    for row, original_ref in zip(rows, spec['original_failed_receipt_refs']):
        year = row['slot']['year']
        original = _ebm_metadata(base._pin(original_ref))
        old = original['reuse_tuple']
        require(original['status'] == 'FAILED' and original['model_id'] == old['model_id'] == 'ebm'
                and original['year'] == old['year'] == year and original['horizon'] == old['horizon'] == 5
                and original['fit_units'] == 1 and original['failure']['message'] == 'FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'
                and original['reuse_tuple_sha256'] == base.values.digest(old), 'ORIGINAL_EBM_FAILURE_OR_IDENTITY_CHANGED')
        attempts, refs, reuse = [], [], None
        for number in (2, 3):
            receipt_path = run / retry.ROOT / str(year) / f'attempt{number}' / 'receipt.json'
            if not receipt_path.exists():
                require(number == 3 and len(attempts) == 1, 'CANONICAL_EBM_RETRY_ATTEMPT_MISSING')
                continue
            require(not attempts or attempts[-1]['status'] in {'FAILED_ENGINEERING', 'IN_PROGRESS'},
                    'NO_EBM_ATTEMPT_AFTER_TERMINAL_SUCCESS_OR_SCIENTIFIC_FAILURE')
            record = _ebm_metadata(receipt_path)
            effective = record['reuse_tuple']['effective_calibration_frame_sha256']
            require(isinstance(effective, str) and len(effective) == 64 and all(ch in '0123456789abcdef' for ch in effective),
                    'EBM_EFFECTIVE_CALIBRATION_FRAME_HASH_REQUIRED')
            expected = dict(freeze_ref=freeze_ref, source_pins=spec['source_pins'],
                dependency_code_binding=spec['dependency_code_binding'], dependency_paths=spec['dependency_paths'],
                original_failed_receipt_ref=original_ref, original_reuse_tuple_sha256=original['reuse_tuple_sha256'],
                year=year, horizon=5, seed=spec['seed'], train_frame_sha256=old['train_frame_sha256'],
                original_calibration_frame_sha256=old['calibration_frame_sha256'], effective_calibration_frame_sha256=effective,
                source_qualification_ref=spec['source_qualification_ref'] if year == 2026 else None)
            require(record['reuse_tuple'] == expected and (reuse is None or reuse == expected)
                    and record['reuse_tuple_sha256'] == base.values.digest(expected)
                    and (year == 2026 or effective == old['calibration_frame_sha256']), 'FULL_EBM_RETRY_TUPLE_CHANGED')
            reuse = expected
            require(record['model_id'] == record['native_model_id'] == 'ebm' and record['year'] == year and record['horizon'] == 5
                    and record['receipt_path'] == str(receipt_path) and record['retry_source_pins'] == spec['source_pins']
                    and record['source_pins'] == retry.predictors.source_pins() and record['previous_attempt_refs'] == refs
                    and record['parent_failure_preserved'] is True and record['test_2026_rows_read'] == 0
                    and record['primary_core5_selection_includes_retry_ebm'] is False
                    and type(record['fit_units']) is int and 0 <= record['fit_units'] <= 2,
                    'EBM_ATTEMPT_SOURCE_HISTORY_OR_SCOPE_CHANGED')
            require(record['status'] in {'TRAINED', 'FAILED_SCIENTIFIC_NO_RETRY', 'FAILED_ENGINEERING', 'IN_PROGRESS'},
                    'EBM_ATTEMPT_DISPOSITION_REQUIRED')
            artifacts = {}
            for field, filename in (('model_ref', 'model.joblib'), ('calibration_ref', 'calibration.parquet'),
                                    ('native_checkpoint_ref', 'native_checkpoint.joblib')):
                if field in record:
                    base._pin(record[field], receipt_path.parent / filename); artifacts[field] = record[field]
            if record.get('native_model_reused_ref') is not None:
                require(number == 3 and attempts[0]['artifacts'].get('native_checkpoint_ref') == record['native_model_reused_ref'],
                        'EBM_NATIVE_REUSE_CUSTODY_CHANGED')
                base._pin(record['native_model_reused_ref']); artifacts['native_model_reused_ref'] = record['native_model_reused_ref']
            if record['status'] == 'TRAINED':
                require(record['phase'] == 'COMPLETED' and {'model_ref', 'calibration_ref'} <= artifacts.keys()
                        and record['fit_units'] >= 1, 'TRAINED_EBM_MODEL_AND_SIGMA_CALIBRATION_REFS_REQUIRED')
            refs.append(base._ref(receipt_path))
            attempts.append(dict(status=record['status'], receipt_ref=refs[-1], fit_units=record['fit_units'],
                                 reuse_tuple_sha256=record['reuse_tuple_sha256'], artifacts=artifacts))
        if row['status'] == 'ENGINEERING_RETRY_LIMIT_REACHED':
            require(row['receipt_ref'] is None and len(attempts) == 2
                    and all(a['status'] in {'FAILED_ENGINEERING', 'IN_PROGRESS'} for a in attempts),
                    'EBM_RETRY_LIMIT_REQUIRES_BOTH_PRESERVED_ATTEMPTS')
        else:
            require(row['status'] in {'TRAINED', 'FAILED_SCIENTIFIC_NO_RETRY'} and attempts[-1]['status'] == row['status']
                    and row['receipt_ref'] == refs[-1], 'EBM_SUMMARY_RECEIPT_OR_DISPOSITION_CHANGED')
        fit_counts[(year, base.values.digest(reuse))] = sum(a['fit_units'] for a in attempts)
        dispositions.append(dict(slot=row['slot'], status=row['status'], original_failed_receipt_ref=original_ref,
                                 attempts=attempts))
    # The original shared global counter remains authoritative; isolate only this fixed bucket.
    base._pin(budget['child_fit_log_ref'], run / 'FIT_LOG.jsonl')
    seen = dict.fromkeys(fit_counts, 0)
    with (run / 'FIT_LOG.jsonl').open('rb') as stream:
        while True:
            line = stream.readline(65537)
            if not line: break
            require(len(line) <= 65536, 'CHILD_FIT_LOG_RECORD_TOO_LARGE')
            if not line.strip(): continue
            event = base.evaluation.account_inputs._JsonProjection(BytesIO(line)).metadata_fields(
                {'event', 'budget_bucket', 'model_id', 'year', 'fit_units', 'reuse_tuple_sha256'})
            if event.get('event') == 'FIT_STARTED' and event.get('budget_bucket') == 'consensus_ebm_teardown_retry':
                key = event.get('year'), event.get('reuse_tuple_sha256')
                require(key in seen and event.get('fit_units') == 1 and event.get('model_id') == 'ebm',
                        'EBM_PHYSICAL_FIT_TUPLE_OR_UNIT_CHANGED')
                seen[key] += 1
    base._pin(budget['child_fit_log_ref'], run / 'FIT_LOG.jsonl')
    require(seen == fit_counts and sum(seen.values()) <= 24 and sum(seen.values()) <= budget['child_fit_units'],
            'EBM_PHYSICAL_FIT_RECEIPT_AND_SHARED_BUDGET_MISMATCH')
    return dict(summary_ref=base._ref(path), freeze_ref=freeze_ref, source_pins=spec['source_pins'],
        authority_refs={field: spec[field] for field in retry.AUTHORITY_FIELDS[:-1]},
        source_qualification_ref=spec['source_qualification_ref'], correction_sidecar_ref=spec['correction_sidecar_ref'],
        dispositions=dispositions, new_bucket_fit_units=sum(seen.values()), max_new_bucket_fit_units=24,
        old_37_plus_14_unchanged=True, original_failures_preserved=True,
        native_models_loaded=False, sigma_calibration_observations_read=False,
        primary_core5_selection_includes_retry_ebm=False, wide_32_fusion_authorized=False,
        real_2026_prediction_published=False, test_2026_rows_read=0)

def _partial_risk(run, record, freeze_ref):
    if record['status'] == 'COMPLETE':
        return base._account_record(run, record, freeze_ref, final_risk=True, continuation=True)
    require(record['status'] in {'FAILED_NO_RETRY', 'NOT_TESTABLE'}, 'TERMINAL_RISK_MUST_BE_FINISHED')
    flow = record['selected_flow']
    path = run / 'models/consensus_final_policy' / flow / 'receipt.json'
    require(Path(record['receipt_path']) == path and base._metadata(path) == record
            and record['task_id'] == base.TASK and record['freeze_ref'] == freeze_ref,
            'TERMINAL_RISK_DISPOSITION_CUSTODY_CHANGED')
    expected = base.values.digest(dict(selected_flow=flow,
        selected_receipt_sha256=base.values.sha(run / 'evaluation/consensus_account' / flow / 'receipt.json'),
        freeze_ref=freeze_ref))
    require(record['identity_sha256'] == expected and record.get('test_rows_read', 0) == 0,
            'TERMINAL_RISK_ORIGIN_OR_TEST_BOUNDARY_CHANGED')
    for name, pin in record.get('artifacts', {}).items():
        base._pin(pin, path.parent / (name + '.joblib' if name == 'state' else name + '.parquet'))
    return dict(flow_id=flow, status=record['status'], receipt=base._ref(path), artifacts=record.get('artifacts', {}))


def _account_terminal(run, summary, ef, ef_ref):
    recipe = ef['recipe']
    require(len(recipe['fusion_methods']) == 14 and len(recipe['stage2']) == 17
            and len(recipe['diagnostic_sensitivities']) == 4, 'EXACT_CHILD_TERMINAL_RECIPE_REQUIRED')
    require(summary['status'] in {'NOT_TESTABLE', 'FINAL_RISK_NOT_FROZEN_NO_TEST_USE'}
            and summary['task_id'] == base.TASK and summary['freeze_ref'] == ef_ref
            and summary['test_2026_rows_read'] == 0
            and summary.get('sensitivity_selection_feedback', False) is False,
            'HONEST_CHILD_NONCOMPLETE_TERMINAL_REQUIRED')
    flow = lambda method, risk='LW', allocation='cost_aware', tag=None: base.evaluation.flow_id(
        method, risk, allocation, tag, run=run)
    stage1, stage2 = summary['stage1'], summary['stage2']
    require([r['flow_id'] for r in stage1] == [flow(m) for m in recipe['fusion_methods']],
            'ALL_FOURTEEN_STAGE1_DISPOSITIONS_REQUIRED')
    method = summary.get('selected_fusion')
    diagnostics = summary.get('sensitivities', [])
    risks = []
    if method is None:
        require(summary['status'] == 'NOT_TESTABLE' and stage2 == []
                and not summary.get('selected_flow') and not summary.get('final_risk_receipt')
                and diagnostics == [] and not summary.get('sensitivity_final_risk')
                and not any(r['status'] == 'COMPLETE' for r in stage1),
                'NO_WINNER_TERMINAL_CANNOT_HIDE_SUCCESSFUL_STAGE1')
    else:
        require(method in recipe['fusion_methods']
                and len([r for r in stage1 if r['fusion_method'] == method and r['status'] == 'COMPLETE']) == 1
                and [r['flow_id'] for r in stage2] == [flow(method, p['risk_method'], p['allocation_method']) for p in recipe['stage2']],
                'CONDITIONAL_SEVENTEEN_STAGE2_DISPOSITIONS_REQUIRED')
        if summary['status'] == 'NOT_TESTABLE':
            require(not any(r['status'] == 'COMPLETE' for r in stage2)
                    and not summary.get('selected_flow') and not summary.get('final_risk_receipt')
                    and diagnostics == [] and not summary.get('sensitivity_final_risk'),
                    'NO_WINNER_TERMINAL_CANNOT_HIDE_SUCCESSFUL_STAGE2')
        else:
            selected = [r for r in stage2 if r['flow_id'] == summary['selected_flow']]
            require(len(selected) == 1 and selected[0]['status'] == 'COMPLETE'
                    and selected[0]['fusion_method'] == method and selected[0]['fee_config'] == recipe['fee_config'],
                    'PARTIAL_TERMINAL_SELECTED_ACCOUNT_REQUIRED')
            chosen = selected[0]
            require([r['flow_id'] for r in diagnostics] == [flow(method, chosen['risk_method'], chosen['allocation_method'], d['tag'])
                    for d in recipe['diagnostic_sensitivities']], 'FOUR_FIXED_POST_SELECTION_DIAGNOSTICS_REQUIRED')
            primary = summary['final_risk_receipt']
            require(primary['selected_flow'] == summary['selected_flow'], 'PRIMARY_FINAL_RISK_FLOW_CHANGED')
            diagnostic_risk = summary['sensitivity_final_risk']
            require([r['selected_flow'] for r in diagnostic_risk] == [r['flow_id'] for r in diagnostics if r['status'] == 'COMPLETE'],
                    'CONDITIONAL_DIAGNOSTIC_RISK_SCOPE_CHANGED')
            require(any(r['status'] != 'COMPLETE' for r in [primary] + diagnostic_risk),
                    'PARTIAL_TERMINAL_CANNOT_HIDE_COMPLETE_FINAL_SYSTEM')
            risks = [_partial_risk(run, r, ef_ref) for r in [primary] + diagnostic_risk]
    accounts = [base._account_record(run, r, ef_ref, continuation=True) for r in stage1 + stage2 + diagnostics]
    return accounts, risks


def _audit(run):
    facts = base.fusion._continuation_facts(run)
    parent = base.fusion.reader_run(run)
    require(parent == facts['parent'], 'CHILD_READER_PARENT_CHANGED')
    refs = facts['scope']['parent_custody']
    spec, pf, old_ff = facts['spec'], facts['pf'], facts['ff']
    pf_ref = refs['predictor_freeze_ref']
    _, _, _, ff, _, ff_ref = base.fusion.contract(run, 'core5', base.fusion.owner.NNLS_ZERO_ABSTAIN, 2026)
    _, ef, ef_ref = base.evaluation.contract(run)
    require(ef['research_id'] == base.fusion.CONTINUATION_RESEARCH_ID
            and ef['recipe'] == base.evaluation.recipe_for_run(run)
            and ef['continuation_scope_ref'] == facts['scope_ref'] and ef['prior_fit_units'] == facts['prior'],
            'CHILD_TERMINAL_RECIPE_OR_LINEAGE_CHANGED')
    models, old_fusions, progress, _ = base._candidate_dispositions(parent, spec, pf, pf_ref, old_ff, refs['fusion_freeze_ref'])
    require(models == facts['audit']['candidate_predictors'] and old_fusions == facts['audit']['candidate_fusions']
            and len(models) == 228 and len(old_fusions) == 84, 'IMMUTABLE_COMPLETE_PARENT_DISPOSITIONS_REQUIRED')
    new_fusions, child_progress = base._child_fusion_dispositions(run, ff, ff_ref, parent, spec)
    fusions = old_fusions + new_fusions
    summary_path = run / 'evaluation/consensus_account_summary.json'
    summary = base._metadata(summary_path, summary=True, continuation=True)
    accounts, risks = _account_terminal(run, summary, ef, ef_ref)
    completion, _ = base._final_calibration_completion(run, ef, models, fusions, facts['scope_ref'])
    source_custody = base._child_source_closure(ef, ef_ref)
    budget = base._child_fit_budget(run, facts)
    ebm_retry = _ebm_terminal(run, budget)
    result = dict(schema=SCHEMA, status=STATUS, task_id=base.TASK, research_id=base.fusion.CONTINUATION_RESEARCH_ID,
        run=str(run), parent_run=str(parent), scientific_result_status=summary['status'],
        source_pins=dict(adapter=base._ref(__file__), immutable_metadata_closure_owner=base._ref(base.__file__),
                        frozen_evaluation_owner=base._ref(base.evaluation.__file__)),
        continuation_scope_ref=facts['scope_ref'], parent_custody=refs, predictor_freeze_ref=pf_ref,
        parent_fusion_freeze_ref=refs['fusion_freeze_ref'], fusion_freeze_ref=ff_ref, evaluation_freeze_ref=ef_ref,
        selection_summary_ref=base._ref(summary_path), progress_refs=dict(parent=progress, child_fusion=child_progress),
        candidate_predictors=models, parent_candidate_fusions=old_fusions, child_candidate_fusions=new_fusions,
        candidate_fusions=fusions, final_calibration_completion=completion, account_dispositions=accounts,
        partial_risk_dispositions=risks, account_source_scope_ref=ef['account_source_scope_ref'],
        account_source_custody=source_custody, fit_budget=budget, auxiliary=base._historical_auxiliary(parent, facts['audit']),
        selected_fusion=summary.get('selected_fusion'), selected_flow=summary.get('selected_flow'),
        original_failures_preserved=True, complete_selected_system_frozen=False,
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY', vintage='UNKNOWN_RETAINED', strict_PIT_certified=False,
        A2_already_exposed=True, fresh_blind_holdout=False, selection_feedback=False,
        test_2026_numeric_read_authorized=False, FAST3_Confirmation_access=False,
        audit_role='RESEARCH_TERMINAL_EVIDENCE_ONLY_NO_MODEL_SUBSTITUTE_OR_TEST_ACCESS')
    if ebm_retry is not None:
        result['additional_ebm_teardown_retry'] = ebm_retry
    result['semantic_sha256'] = base.values.digest(result)
    return result


def audit_terminal(run=None):
    return _audit(_context(base.fusion.CONTINUATION_RUN if run is None else run))


def publish_terminal_root(run=None):
    run = _context(base.fusion.CONTINUATION_RUN if run is None else run)
    path = run / base.TERMINAL_AUDIT_FILENAME
    if path.exists():
        stored = base._metadata(path, summary=True, continuation=True)
        require(stored == audit_terminal(run), 'CHILD_TERMINAL_AUDIT_CUSTODY_CHANGED')
        return stored
    with base.predictors.fit_lock(run):
        require(not (run / 'CONSENSUS_DOWNSTREAM.lock').exists() and not path.exists(), 'ACTIVE_OR_EXISTING_CHILD_TERMINAL_AUDIT')
        write_json_atomic(path, _audit(run))
    stored = base._metadata(path, summary=True, continuation=True)
    require(stored == audit_terminal(run), 'CHILD_TERMINAL_AUDIT_CUSTODY_CHANGED')
    return stored


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, default=base.fusion.CONTINUATION_RUN)
    parser.add_argument('--publish-terminal-root', action='store_true')
    args = parser.parse_args(argv)
    result = publish_terminal_root(args.run) if args.publish_terminal_root else audit_terminal(args.run)
    print(base.json.dumps(result, indent=2, default=str))
    return result


if __name__ == '__main__':
    main()
