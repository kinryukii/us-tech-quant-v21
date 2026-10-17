"""Finite R12 forecast add-on; original fusion owns every numeric operation.

Three named IPC retries preserve failed tuples; nine causal 2022 publications
use 2021 OOF only. Import/template/preflight never open numeric inputs or models.
"""
from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace, FunctionType

import pandas as pd

from scripts.research.a2.training import consensus_forecast_recovery as recovery
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic

values, require, fusion = recovery.values, recovery.require, recovery.fusion
FREEZE = 'CONSENSUS_FORECAST_COMPLETION_FREEZE.json'
ADMISSION = 'CONSENSUS_FORECAST_COMPLETION_ADMISSION.json'
SCHEMA = 'CONSENSUS_FORECAST_COMPLETION_R12'
GATE = 'AUTHORIZED_PRE2026_FORECAST_COMPLETION'
REVIEW = 'ACCEPTED_INDEPENDENT_METADATA_REVIEW'
TERMINAL_SCHEMA = 'CONSENSUS_FORECAST_RECOVERY_TERMINAL_CUSTODY_R12'
RETRY = 'NAMED_COMMON_PARENT_BOOTSTRAP_SAME_INPUT_RETRY_R1'
RETRIES = (('broad29', 'convex', 2, 1), ('broad29', 'stack_ridge', 3, 2), ('multih38', 'convex', 2, 1))
ref, pin, metadata = recovery.ref, recovery.pin, recovery.metadata


def source_pins():
    return dict(adapter=ref(__file__), original_recovery=recovery.source_pins())


def ordered_slots(spec):
    packets = fusion.packets(spec)
    retries = [dict(packet_id=p, method=m, year=2023,
        owner_id=next(k for k, v in fusion.owner.METHODS.items() if v == m), members=packets[p],
        purpose=RETRY, max_new_fit_units=units) for p, m, units, _ in RETRIES]
    upstream = [dict(packet_id=p, method=m, year=2022,
        owner_id=('NAMED_NNLS_ZERO_ABSTAIN_R1' if m == fusion.owner.NNLS_ZERO_ABSTAIN else
                  next(k for k, v in fusion.owner.METHODS.items() if v == m)), members=packets[p],
        purpose='CAUSAL_2022_UPSTREAM_FOR_RL_2022_ONLY', max_new_fit_units=1 if m == 'equal' else 2)
        for p in ('core5', 'broad29', 'multih38') for m in ('equal', 'convex', fusion.owner.NNLS_ZERO_ABSTAIN)]
    return retries + upstream


def _original_failures(run, spec, recovery_ref):
    result = []
    for (packet, method, _, lost), slot in zip(RETRIES, ordered_slots(spec)[:3]):
        path = run/'models/consensus_fusion'/packet/method/'2023/receipt.json'
        old = metadata(path); reuse = old['reuse_tuple']
        require(old['status'] == 'FAILED' and old['fit_units'] == lost
            and old['failure'] == dict(type='ModuleNotFoundError', message="No module named 'common'")
            and (old['packet_id'], old['model_id'], old['year']) == (packet, method, 2023)
            and old['reuse_tuple_sha256'] == values.digest(reuse)
            and reuse['freeze_ref'] == recovery_ref and reuse['members'] == slot['members']
            and reuse['source_pins'] == recovery.source_pins()
            and reuse['seed'] == values.SEED and reuse['target_definition'] == values.LABEL,
            'EXACT_ORIGINAL_IPC_FAILURE_AND_LOST_UNITS_REQUIRED')
        result.append(dict(slot=dict(packet_id=packet, method=method, year=2023),
            original_failure_ref=ref(path), original_reuse_tuple_sha256=old['reuse_tuple_sha256'],
            original_spent_fit_units=lost))
    return result


def _prefix_facts(log, size):
    require(type(size) is int and size >= 0 and size <= log.stat().st_size, 'IMMUTABLE_FIT_PREFIX_SIZE_REQUIRED')
    digest = hashlib.sha256(); used = records = consumed = 0; tuples = {}
    with log.open('rb') as stream:
        while consumed < size:
            line = stream.readline(min(65537, size-consumed+1))
            require(line and line.endswith(b'\n') and len(line) <= 65536 and consumed+len(line) <= size,
                    'BOUNDED_COMPLETE_FIT_PREFIX_RECORD_REQUIRED')
            consumed += len(line); digest.update(line)
            if not line.strip(): continue
            event = recovery.json.loads(line); records += 1
            if event.get('event') == 'FIT_STARTED':
                require(event.get('fit_units') == 1, 'ORIGINAL_PHYSICAL_FIT_UNIT_CHANGED')
                used += 1; token = event['reuse_tuple_sha256']; tuples[token] = tuples.get(token, 0)+1
    return dict(path=str(log), bytes=size, sha256=digest.hexdigest(), records=records,
                fit_started_units=used), tuples


def _terminal(run, reference, original_scope, original_ref, failures):
    terminal = metadata(pin(reference))
    require(terminal['schema'] == TERMINAL_SCHEMA and terminal['status'] == 'TERMINAL'
        and terminal['run'] == str(run) and terminal['original_recovery_freeze_ref'] == original_ref
        and terminal['original_stage_process_stopped'] is True
        and type(terminal['original_stage_process_id']) is int and terminal['original_stage_process_id'] > 0,
        'ORIGINAL_STAGE_TERMINAL_CUSTODY_REQUIRED')
    status_path = pin(terminal['original_process_status_ref'])
    require(status_path == run/'FORECAST_RECOVERY_PROCESS_STATUS.json', 'EXACT_ORIGINAL_PROCESS_STATUS_REQUIRED')
    status = metadata(status_path)
    require(status['status'] == 'PLAN_TERMINAL_CHECK_RECEIPTS'
        and status['pid'] == terminal['original_stage_process_id']
        and status['summary_ref'] == terminal['original_summary_ref']
        and status['prior_fit_units'] == 2063 and status['max_new_fit_units'] == 75
        and status['fit_failures_not_subtracted'] is True and status['test2026_rows_read'] == 0,
        'ORIGINAL_PROCESS_RUNNING_OR_TERMINAL_STATUS_DISAGREES')
    summary_path = pin(terminal['original_summary_ref'])
    require(summary_path == run/'FORECAST_RECOVERY_ACTUAL_SUMMARY.json', 'EXACT_ORIGINAL_RECOVERY_SUMMARY_REQUIRED')
    summary = metadata(summary_path)
    entries = summary['fusion_slots']; planned = original_scope['ordered_fusion_slots']
    require(summary['schema'] == 'CONSENSUS_FORECAST_RECOVERY_ACTUAL_SUMMARY_R12'
        and summary['freeze_ref'] == original_ref and summary['original_failures_preserved'] is True
        and summary['test_2026_rows_read'] == 0 and len(entries) == len(planned) == 40,
        'ORIGINAL_RECOVERY_FULL_TERMINAL_STATUS_REQUIRED')
    indexed = {(e['slot']['packet_id'], e['slot']['method'], e['slot']['year']): e for e in entries}
    require(len(indexed) == 40 and set(indexed) == {(s['packet_id'], s['method'], s['year']) for s in planned},
            'EXACT_ORIGINAL_40_TERMINAL_SLOTS_REQUIRED')
    for slot in planned:
        key = (slot['packet_id'], slot['method'], slot['year']); entry = indexed[key]
        path = run/'models/consensus_fusion'/key[0]/key[1]/str(key[2])/'receipt.json'
        require(entry['slot'] == slot and pin(entry['receipt_ref']) == path,
                'EXACT_ORIGINAL_SLOT_RECEIPT_REQUIRED')
        receipt = metadata(path)
        status = 'TRAINED' if entry['status'] == 'PUBLISHED' else entry['status']
        require(status in ('TRAINED', 'FAILED', 'NOT_TESTABLE') and receipt['status'] == status
            and (receipt['packet_id'], receipt['model_id'], receipt['year']) == key,
            'ORIGINAL_STAGE_RUNNING_OR_TERMINAL_STATUS_DISAGREES')
    log = run/'FIT_LOG.jsonl'; actual, tuples = _prefix_facts(log, terminal['fit_log_prefix']['bytes'])
    require(terminal['fit_log_prefix'] == actual, 'ORIGINAL_FIT_LOG_PREFIX_CHANGED')
    require(all(tuples.get(f['original_reuse_tuple_sha256'], 0) == f['original_spent_fit_units'] for f in failures),
            'ORIGINAL_FOUR_FAILED_FIT_UNITS_MUST_REMAIN')
    return actual


def freeze_template(run, root_scope_ref, *, stage_terminal_ref=None):
    run, original, spec, _, _, original_ref = recovery.contract(run)
    pin(root_scope_ref)
    return dict(schema=SCHEMA, status='PROPOSED', task_id=recovery.predictors.TASK,
        research_id=recovery.RESEARCH_ID, run=str(run), root_scope_ref=root_scope_ref,
        original_recovery_freeze_ref=original_ref, source_pins=source_pins(),
        ordered_slots=ordered_slots(spec), original_failures=_original_failures(run, spec, original_ref),
        stage_terminal_ref=stage_terminal_ref, prior_fit_units=2063, max_fit_units=10000,
        max_new_fit_units=22, retry_fit_units_upper=7, upstream_fit_units_upper=15,
        original_phase_max_new_fit_units=original['max_new_fit_units'], no_fit_budget_reset=True,
        original_failed_receipts_and_tuples_preserved=True, original_artifacts_overwrite=False,
        seed=values.SEED, calibration_sessions=60, native_recipe='UNCHANGED_ORIGINAL_FUSION_OWNER',
        sigma_rule='ONLY_PAST_60_SESSION_RESIDUAL_SAMPLE_STD_NO_MU_SHIFT',
        train_and_development_before='2026-01-01', test_2026_read_authorized=False,
        confirmation_read_authorized=False,
        causal_upstream=dict(fusion_publication_year=2022, input_oof_years=[2021],
            all_fitting_labels_before='2022-01-01', calibration='ORIGINAL_PRE2022_LAST_60_LEGAL_SESSIONS',
            rl_reward_training_years=[2022], development_comparison_years=[2023, 2024, 2025],
            weights_2023_must_never_train_rl_2021_2022=True))


def contract(run, *, authorized=True):
    run = Path(run).resolve(); assert_safe_output_path(run, kind='backtest', paths=resolve(recovery.predictors.REPO))
    scope = metadata(run/FREEZE)
    actual_run, original, spec, pf, parent, original_ref = recovery.contract(run)
    require(actual_run == run and scope == dict(freeze_template(run, scope['root_scope_ref'],
        stage_terminal_ref=scope['stage_terminal_ref']), status=scope['status']), 'COMPLETION_FROZEN_SCOPE_CHANGED')
    require(scope['status'] in ('PROPOSED', GATE), 'COMPLETION_STATUS_CHANGED')
    prefix = None
    if scope['stage_terminal_ref'] is not None:
        prefix = _terminal(run, scope['stage_terminal_ref'], original, original_ref, scope['original_failures'])
    if authorized:
        require(scope['status'] == GATE and prefix is not None, 'ROOT_COMPLETION_AND_ORIGINAL_TERMINAL_GATE_REQUIRED')
        admission = metadata(run/ADMISSION)
        require(admission['schema'] == SCHEMA+'_ADMISSION' and admission['status'] == REVIEW
            and admission['freeze_ref'] == ref(run/FREEZE) and admission['source_pins'] == source_pins()
            and admission['numeric_inputs_read'] is False and admission['models_loaded'] is False
            and admission['test_2026_rows_read'] == 0 and admission['confirmation_read_authorized'] is False,
            'EXACT_COMPLETION_INDEPENDENT_METADATA_ADMISSION_REQUIRED')
    return run, scope, spec, pf, parent, ref(run/FREEZE), prefix


def metadata_preflight(run):
    _, scope, _, _, _, frozen, prefix = contract(run, authorized=False)
    return dict(status='PASS_METADATA_ONLY', freeze_ref=frozen, slots=len(scope['ordered_slots']),
        max_new_fit_units=22, original_stage_terminal=prefix is not None,
        numeric_inputs_read=False, models_loaded=False, test_2026_rows_read=0)


def admission_template(run):
    _, _, _, _, _, frozen, _ = contract(run, authorized=False)
    return dict(schema=SCHEMA+'_ADMISSION', status='PROPOSED', freeze_ref=frozen,
        source_pins=source_pins(), numeric_inputs_read=False, models_loaded=False,
        test_2026_rows_read=0, confirmation_read_authorized=False)


def stage_terminal_template(run, original_summary_ref, original_stage_process_id):
    run, original, spec, _, _, original_ref = recovery.contract(run)
    log = run/'FIT_LOG.jsonl'; prefix, _ = _prefix_facts(log, log.stat().st_size)
    result = dict(schema=TERMINAL_SCHEMA, status='PROPOSED', run=str(run),
        original_recovery_freeze_ref=original_ref, original_summary_ref=original_summary_ref,
        original_process_status_ref=ref(run/'FORECAST_RECOVERY_PROCESS_STATUS.json'),
        original_stage_process_id=original_stage_process_id, original_stage_process_stopped=False,
        fit_log_prefix=prefix)
    # Root supplies process-terminal evidence; absence of a lock is insufficient.
    return result


def _proof(run, scope, fr, slot, packet):
    fold, train, cal, _, _, _, _, pins = packet; year = slot['year']
    dates = lambda frame, field: pd.to_datetime(frame[field])
    require(all(dates(frame, 'signal_date').ge('2021-01-01').all()
        and dates(frame, 'signal_date').lt(f'{year}-01-01').all()
        and dates(frame, 'label_mature_date').lt(f'{year}-01-01').all() for frame in (train, cal)),
        'CAUSAL_PRIOR_OOF_SIGNALS_AND_ALL_FITTING_LABELS_REQUIRED')
    proof = dict(schema=SCHEMA+'_INPUT_PROOF', freeze_ref=fr,
        slot={k: slot[k] for k in ('packet_id', 'method', 'year')},
        train_frame_sha256=recovery.predictors.frame_hash(train),
        calibration_frame_sha256=recovery.predictors.frame_hash(cal),
        train_maturity_exclusive=str(fold['calibration_start']),
        calibration_maturity_exclusive=str(fold['cutoff_exclusive']),
        calibration_sessions=[str(d) for d in fold['calibration_sessions']], past_publication_pins=pins,
        input_oof_years=list(range(2021, year)), all_fitting_labels_before=f'{year}-01-01',
        actual_max_train_label_mature=str(dates(train, 'label_mature_date').max()),
        actual_max_calibration_label_mature=str(dates(cal, 'label_mature_date').max()),
        original_failure_ref=None)
    require({p['year'] for p in pins} == set(range(2021, year)), 'EXACT_PRIOR_YEAR_OOF_CUSTODY_REQUIRED')
    if year == 2023:
        failed = next(f for f in scope['original_failures'] if f['slot'] == proof['slot'])
        old = metadata(pin(failed['original_failure_ref']))['reuse_tuple']
        expected = dict(task_id=recovery.predictors.TASK, packet_id=slot['packet_id'], model_id=slot['method'],
            owner_id=slot['owner_id'], year=year, members=slot['members'], seed=values.SEED,
            predictor_freeze_ref=metadata(pin(scope['original_recovery_freeze_ref']))['parent_predictor_freeze_ref'],
            fixed_weights=None, target_definition=values.LABEL,
            state_basis='UNUSED', weights='UNIFORM_LEGAL_ROWS', native_uncertainty_used=False, target_clip='NONE')
        expected.update({k: proof[k] for k in ('train_frame_sha256', 'calibration_frame_sha256',
            'train_maturity_exclusive', 'calibration_maturity_exclusive', 'calibration_sessions', 'past_publication_pins')})
        require({k: v for k, v in old.items() if k not in ('source_pins', 'freeze_ref')} == expected,
                'ORIGINAL_RETRY_TRAIN_CAL_RECIPE_SEED_TARGET_OR_OOF_CUSTODY_CHANGED')
        proof['original_failure_ref'] = failed['original_failure_ref']
    path = run/'derived/consensus_forecast_completion_input_proofs'/slot['packet_id']/slot['method']/f'{year}.json'
    if path.exists(): require(metadata(path) == proof, 'IMMUTABLE_COMPLETION_INPUT_PROOF_CHANGED')
    else: write_json_atomic(path, proof)
    return proof


def bind_fusion(run):
    run, scope, spec, _, _, fr, prefix = contract(run)
    require(not (run/'CONSENSUS_FIT.lock').exists(), 'SHARED_FIT_OWNER_ACTIVE_NO_COMPLETION_CONCURRENCY')
    name = '_consensus_forecast_completion_'+fr['sha256'][:24]
    if name in sys.modules:
        module = sys.modules[name]
        require(getattr(module, '_completion_ref', None) == fr, 'COMPLETION_PRIVATE_NAMESPACE_CHANGED')
        return module
    base = recovery.bind_fusion(run)
    module = recovery._namespace(fusion.__file__, name)
    frozen = dict(schema=SCHEMA, source_pins=source_pins(), prior_fit_units=2063,
        predictor_freeze_ref=base.contract(run, 'broad29', 'convex', 2023)[3]['predictor_freeze_ref'],
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY')
    slots = {(s['packet_id'], s['method'], s['year']): s for s in scope['ordered_slots']}
    def local_contract(actual, packet, method, year):
        require(Path(actual).resolve() == run, 'EXACT_COMPLETION_RUN_REQUIRED')
        contract(run); method = fusion.owner.method_name(method)
        require((packet, method, year) in slots, 'UNPLANNED_COMPLETION_SLOT')
        output = run/'predictions/consensus_fusion'/packet/method/f'{year}.parquet'
        published = output.with_suffix('.receipt.json')
        if output.exists() or published.exists():
            require(output.exists() and published.exists()
                and Path(metadata(published)['fit_receipt_path']) == module.slot_paths(run, packet, method, year)[1]
                and metadata(published)['source_pins'] == frozen['source_pins'],
                'EXISTING_ORIGINAL_PUBLICATION_MUST_NEVER_BE_OVERWRITTEN')
        return run, method, spec, frozen, slots[(packet, method, year)], fr
    def slot_paths(actual, packet, method, year):
        root = Path(actual)/'models/consensus_forecast_completion'/packet/method/str(year)
        return root, root/'receipt.json', root/'model.joblib'
    def training_packet(actual, slot, year, reader):
        packet = module._original_training_packet(actual, slot, year, reader)
        _proof(run, scope, fr, slot, packet)
        return packet
    proxy = SimpleNamespace(**vars(values))
    def auth_for(auth, receipt, year):
        slot = slots[(receipt['packet_id'], receipt['model_id'], year)]
        return dict(auth, max_fit_units=min(10000, 2063+prefix['fit_started_units']+22),
            max_new_bucket_fit_units=slot['max_new_fit_units'],
            budget_bucket='consensus_forecast_completion__'+slot['packet_id']+'__'+slot['method']+'__'+str(year))
    def component(log, auth, prior, model, year, component_name, token):
        # The original sigma call supplies no receipt; the immutable token's
        # current slot is read from the exact newly written add-on receipt.
        matches = [s for s in slots.values() if s['method'] == model and s['year'] == year
            and module.slot_paths(run, s['packet_id'], model, year)[1].exists()
            and metadata(module.slot_paths(run, s['packet_id'], model, year)[1]).get('reuse_tuple_sha256') == token]
        require(len(matches) == 1, 'EXACT_COMPLETION_COMPONENT_SLOT_REQUIRED')
        return values._component_start(log, auth_for(auth, dict(packet_id=matches[0]['packet_id'], model_id=model), year),
            2063, model, year, component_name, token)
    def job(*args, **kwargs):
        require(args[0] == 'fusion', 'ONLY_ORIGINAL_FUSION_FIT_OPERATION_REQUIRED')
        fusion.owner._native(args[6])  # Before parent Pipe.recv / pickle decoding.
        kwargs.update(prior=2063, auth=auth_for(kwargs['auth'], kwargs['receipt'], kwargs['year']))
        return values._fit_job(*args, **kwargs)
    proxy._component_start, proxy._fit_job = component, job
    module.values, module.predictors = proxy, base.predictors
    module.ConsensusInputs, module.reader_run, module.publication = base.ConsensusInputs, base.reader_run, base.publication
    module.contract, module.slot_paths, module.source_pins = local_contract, slot_paths, source_pins
    module._original_training_packet = module.training_packet; module.training_packet = training_packet
    # Only the original publication reader's pre2026 year gate is widened.
    original = module.published_fusion_forecasts; constants = original.__code__.co_consts
    require(constants.count((2023, 2024, 2025)) == 1, 'EXACT_ORIGINAL_PUBLICATION_YEAR_GATE_REQUIRED')
    code = original.__code__.replace(co_consts=tuple((2022, 2023, 2024, 2025) if c == (2023, 2024, 2025) else c for c in constants))
    widened = FunctionType(code, module.__dict__, original.__name__, original.__defaults__, original.__closure__)
    widened.__kwdefaults__ = copy.deepcopy(original.__kwdefaults__)
    module.published_fusion_forecasts = widened
    module._completion_ref = fr
    return module


def run_all(run, reader=None):
    module = bind_fusion(run); run, scope, _, _, _, fr, _ = contract(run)
    entries = []
    for slot in scope['ordered_slots']:
        result = module.predict_one(run, slot['packet_id'], slot['method'], slot['year'], reader)
        _, rp, _ = module.slot_paths(run, slot['packet_id'], slot['method'], slot['year'])
        entries.append(dict(slot=slot, status=result['status'], receipt_ref=ref(rp) if rp.exists() else None,
            publication_ref=ref(Path(result['path']).with_suffix('.receipt.json')) if result.get('status') == 'PUBLISHED' else None))
    summary = dict(schema=SCHEMA+'_ACTUAL_SUMMARY', freeze_ref=fr, slots=entries,
        original_failures_preserved=True, original_lost_fit_units=4, max_new_fit_units=22,
        test_2026_rows_read=0, rl_reward_training_years=[2022])
    write_json_atomic(run/'FORECAST_COMPLETION_ACTUAL_SUMMARY.json', summary)
    return summary


def published_fusion_forecasts(run, method, year, reader=None, *, packet_id='core5'):
    require(year in (2022, 2023, 2024, 2025), 'COMPLETION_REAL_2026_PUBLICATION_FORBIDDEN')
    method = fusion.owner.method_name(method)
    addon = (year == 2022 and packet_id in ('core5', 'broad29', 'multih38')
        and method in ('equal', 'convex', fusion.owner.NNLS_ZERO_ABSTAIN)) or (
        year == 2023 and (packet_id, method) in {(p, m) for p, m, _, _ in RETRIES})
    if not addon:
        require(year != 2022, 'UNPLANNED_2022_UPSTREAM_PUBLICATION')
        return recovery.published_fusion_forecasts(run, method, year, reader, packet_id=packet_id)
    module = bind_fusion(run)
    frame, published = module.published_fusion_forecasts(run, method, year, reader, packet_id=packet_id)
    return frame, dict(published, completion_route=SCHEMA, completion_freeze_ref=module._completion_ref)
