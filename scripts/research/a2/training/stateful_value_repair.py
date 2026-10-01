"""One EBM transport repair; frozen value math, inputs and ledger stay canonical.

The retained value worker is unchanged. Only its RESULT pipe is wrapped: the
dedicated worker synchronously closes its own idle reusable loky executor before
forwarding RESULT, then the original five-second join/exit-zero check still runs.
No executor is created, no process is killed here, and no fit error is suppressed.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import time

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic
from scripts.research.a2.training import stateful_values as values

GENERATION = 'technical_repair_1'
LEDGER_ID = 'VALUE_REPAIR::ebm::technical_repair_1'
YEARS = (2023, 2024, 2025)
FAILURE = 'FIT_WORKER_DID_NOT_EXIT_CLEANLY_AFTER_RESULT'
VALUES_SHA = '307169fc3bb7a4b944409246f4ede98aa880370b91f07e941a5b6906958fefa8'
JOBLIB_VERSION = '1.5.3'
CLEANUP_PINS = {
    'reusable_executor_sha256': '77d92cad39c94bce78f4eab9d221b4f2ee69121b8c6e1437a126144aad2dc0d4',
    'process_executor_sha256': '40f48a7add0e0805abea0ff67c7c0fb78ca341a009b237de25814f88a852f511',
}


def transport_binding():
    from joblib.externals.loky import process_executor, reusable_executor
    pins = dict(repair_transport_sha256=values.sha(__file__),
                module_sha256=values.sha(values.__file__),
                native_source_sha256=values.sha(values.NATIVE),
                input_reader_sha256=values.sha(values.READER_SOURCE),
                joblib_version=joblib.__version__,
                reusable_executor_sha256=values.sha(reusable_executor.__file__),
                process_executor_sha256=values.sha(process_executor.__file__))
    if pins['module_sha256'] != VALUES_SHA or pins['joblib_version'] != JOBLIB_VERSION:
        raise ValueError('REPAIR_TRANSPORT_CANONICAL_VALUES_OR_JOBLIB_CHANGED')
    if any(pins[key] != value for key, value in CLEANUP_PINS.items()):
        raise ValueError('REPAIR_LOKY_CLEANUP_IMPLEMENTATION_CHANGED')
    return pins


def validate_owned_idle(pool, worker_pid):
    pending = getattr(pool, '_pending_work_items', None)
    processes = getattr(pool, '_processes', None)
    if not isinstance(pending, dict) or pending:
        raise RuntimeError('REPAIR_EXECUTOR_NOT_PROVEN_IDLE')
    if not isinstance(processes, dict):
        raise RuntimeError('REPAIR_EXECUTOR_PROCESS_OWNERSHIP_UNAVAILABLE')
    children = list(processes.values())
    if any(getattr(child, '_parent_pid', None) != worker_pid for child in children):
        raise RuntimeError('REPAIR_EXECUTOR_HAS_NONOWNED_CHILD')
    if getattr(getattr(pool, '_flags', None), 'broken', None):
        raise RuntimeError('REPAIR_EXECUTOR_BROKEN')
    return children


def cleanup_existing_owned_executor():
    """Only an existing executor owned by this dedicated spawned worker."""
    if mp.parent_process() is None:
        raise RuntimeError('REPAIR_CLEANUP_REQUIRES_DEDICATED_CHILD_WORKER')
    from joblib.externals.loky import reusable_executor
    pool = reusable_executor._executor  # Reading the singleton never creates one.
    proof = dict(worker_pid=os.getpid(), executor_created=False,
                 pending_work_items=0, kill_workers=False, cleanup_completed=False)
    if pool is None:
        return dict(proof, executor_present=False, owned_children=0,
                    child_exitcodes=[], cleanup_completed=True)
    children = validate_owned_idle(pool, os.getpid())
    started = time.monotonic()
    pool.shutdown(wait=True, kill_workers=False)
    if any(child.is_alive() for child in children) or any(child.exitcode != 0 for child in children):
        raise RuntimeError('REPAIR_OWNED_CHILD_DID_NOT_EXIT_CLEANLY')
    return dict(proof, executor_present=True, owned_children=len(children),
                child_exitcodes=[child.exitcode for child in children],
                cleanup_seconds=time.monotonic()-started, cleanup_completed=True)


class _ResultPipe:
    def __init__(self, pipe):
        self.pipe = pipe

    def send(self, message):
        if message[0] == 'RESULT':
            if getattr(message[1], 'has_fitted_', False) is not True:
                raise RuntimeError('REPAIR_EBM_FIT_COMPLETION_NOT_PROVEN')
            metadata = dict(message[2])
            metadata['worker_cleanup'] = cleanup_existing_owned_executor()
            message = ('RESULT', message[1], metadata)
        self.pipe.send(message)

    def recv(self):
        return self.pipe.recv()

    def close(self):
        self.pipe.close()


def repair_worker(pipe, operation, model_id, x, y, dates, quantile,
                  dependencies, features, observed):
    try:
        if operation != 'predictor' or model_id != LEDGER_ID or quantile is not None:
            raise ValueError('REPAIR_WORKER_EBM_PREDICTOR_ONLY')
        if not isinstance(observed, dict) or observed != transport_binding():
            raise ValueError('REPAIR_WORKER_SOURCE_PINS_CHANGED')
        if len(features) != 32:
            raise ValueError('REPAIR_WORKER_FROZEN32_REQUIRED')
    except BaseException as exc:
        pipe.send(('ERROR', type(exc).__name__, str(exc)))
        pipe.close()
        return
    # ACKs/errors/fit math are unchanged; only RESULT is intercepted.
    values._fit_worker(_ResultPipe(pipe), operation, 'ebm', x, y, dates,
                       quantile, dependencies, features, None)


def validate_finished_batches(config, value_progress, fusion_progress, events):
    from scripts.research.a2.training.stateful_fusion import (
        method_name, validate_value_batch_complete)
    validate_value_batch_complete(config, value_progress)
    schedule = config.get('fusion_training', {}).get('ordered_schedule', [])
    expected = {(method_name(item['model_id']), item['year']) for item in schedule}
    slots = fusion_progress.get('slots', [])
    actual = {(method_name(item['model_id']), item['year']) for item in slots}
    if (len(schedule) != 39 or len(expected) != 39 or len(slots) != 39
            or actual != expected or fusion_progress.get('status') != 'ATTEMPTS_FINISHED'
            or fusion_progress.get('expected_slots') != 39
            or any(item.get('status') not in ('TRAINED', 'ERROR') for item in slots)):
        raise RuntimeError('FUSION39_NOT_FINISHED_NO_SHARED_FIT_LOG_RACE')
    starts = {(event['model_id'], event['year']) for event in events
              if event.get('event') == 'MODEL_YEAR_ATTEMPT_STARTED'}
    finished = {(event['model_id'], event['year']) for event in events
                if event.get('event') in ('MODEL_YEAR_COMPLETE', 'MODEL_YEAR_FAILED')}
    if starts-finished:
        raise RuntimeError('OUTSTANDING_ATTEMPT_NO_SHARED_FIT_LOG_RACE')


def frozen_contract(run_dir, year, check_stage=True):
    if year not in YEARS:
        raise ValueError('REPAIR_ONLY_FROZEN_2023_2024_2025')
    run, config, original_auth, source_pins = values.frozen_contract(run_dir, 'ebm', year)
    auth = config.get('value_repair', {})
    expected = dict(status='FROZEN', method='ebm', generation=GENERATION,
                    years=list(YEARS), seed=values.SEED, fit_timeout_seconds=1800,
                    max_fit_units=882, max_model_year_attempts=201,
                    budget_bucket='value_meta_technical', max_new_bucket_fit_units=384,
                    exclusive_fit_log_stage='VALUE_REPAIR_AFTER_VALUE93_FUSION39')
    if any(auth.get(key) != value for key, value in expected.items()):
        raise ValueError('EBM_SINGLE_TECHNICAL_REPAIR_NOT_FROZEN')
    transport = transport_binding()
    if auth.get('repair_transport_sha256') != transport['repair_transport_sha256']:
        raise ValueError('REPAIR_SOURCE_NOT_FROZEN')
    if auth.get('source_pins') != source_pins:
        raise ValueError('REPAIR_ORIGINAL_SOURCE_PINS_CHANGED')
    if auth.get('dependency_paths') != original_auth.get('dependency_paths', []):
        raise ValueError('REPAIR_ORIGINAL_DEPENDENCIES_CHANGED')
    pins = auth.get('old_failed_receipts', [])
    if len(pins) != 3 or {pin.get('year') for pin in pins} != set(YEARS):
        raise ValueError('REPAIR_EXACT_THREE_OLD_FAILURE_PINS_REQUIRED')
    pin = next(pin for pin in pins if pin['year'] == year)
    old_path = run/'models/value/ebm'/str(year)/'fit_receipt.json'
    if Path(pin['receipt_path']).resolve() != old_path.resolve() or values.sha(old_path) != pin['receipt_sha256']:
        raise ValueError('REPAIR_OLD_FAILURE_RECEIPT_CHANGED')
    old = json.loads(old_path.read_text(encoding='utf-8'))
    if (old.get('status') != 'FAILED' or old.get('model_id') != 'ebm'
            or old.get('year') != year or old.get('fit_units') != 1
            or old.get('failure', {}).get('message') != FAILURE
            or old.get('reuse_tuple_sha256') != pin.get('reuse_tuple_sha256')
            or values.digest(old.get('reuse_tuple')) != pin.get('reuse_tuple_sha256')
            or old.get('reuse_tuple', {}).get('source_pins') != source_pins):
        raise ValueError('REPAIR_OLD_FAILURE_IDENTITY_OR_CAUSE_MISMATCH')
    if check_stage:
        value_progress = json.loads((run/'logs/value_batch_status.json').read_text(encoding='utf-8'))
        fusion_progress = json.loads((run/'logs/fusion_batch_status.json').read_text(encoding='utf-8'))
        validate_finished_batches(config, value_progress, fusion_progress, values._events(run/'FIT_LOG.jsonl'))
        for progress_path in (run/'logs').glob('*batch_status.json'):
            progress = json.loads(progress_path.read_text(encoding='utf-8'))
            if progress.get('status') == 'RUNNING':
                raise RuntimeError('ANOTHER_BATCH_RUNNING_NO_SHARED_FIT_LOG_RACE:'+progress_path.name)
    return run, config, auth, source_pins, transport, pin, old


def original_scientific_tuple(train, cal, fold, binding, source_pins):
    """Same EBM tuple as values.train_annual, including exact input digests."""
    original = dict(values.scientific_tuple(train, cal, fold, binding),
                    model_id='ebm', family='ebm', source_pins=source_pins, seed=values.SEED,
                    native_factory='models_native.estimator_or_fit_torch_RAW_PREDICT_ONLY',
                    target_clipping='NONE', native_statistics_used=False,
                    weights='UNIFORM_ROWS_NO_SELECTION', preprocessing='NONE_REQUIRE_FINITE',
                    fit_timeout_seconds=values.FIT_TIMEOUT)
    original['configuration'] = 'EXACT_PINNED_NATIVE_COMPACT_FACTORY_ONE_CONFIGURATION_NO_SEARCH'
    original['preprocessor'] = original['preprocessing']
    return original


def repair_annual(year, run_dir, reader=None):
    run, config, auth, pins, transport, old_pin, old = frozen_contract(run_dir, year)
    from scripts.research.a2.training.stateful_inputs import InputReader
    if reader is None:
        reader = InputReader(run)
    elif type(reader) is not InputReader or reader.run != run:
        raise ValueError('CANONICAL_INPUT_READER_REQUIRED')
    fold = dict(reader.annual_fold(year), year=year)
    values.validate_fold(fold)
    binding = values.feature_binding()
    train, cal = reader.read_training_fold(year)
    train = values.guarded_rows(train, fold['calibration_start'], binding['features'])
    cal = values.guarded_rows(cal, fold['cutoff_exclusive'], binding['features'], fold['calibration_sessions'])
    if len(train) < 2 or len(cal) < 2:
        raise ValueError('BLOCKED_DATA_CHRONOLOGICAL_TRAIN_CALIBRATION')
    original = original_scientific_tuple(train, cal, fold, binding, pins)
    if original != old['reuse_tuple'] or values.digest(original) != old_pin['reuse_tuple_sha256']:
        raise ValueError('REPAIR_SCIENTIFIC_TUPLE_NOT_IDENTICAL')
    reuse = dict(original, source_pins=dict(pins, repair_transport_sha256=transport['repair_transport_sha256']),
                 technical_repair_generation=GENERATION, old_failed_receipt_sha256=old_pin['receipt_sha256'],
                 original_scientific_tuple_sha256=old_pin['reuse_tuple_sha256'])
    tuple_sha = values.digest(reuse)
    slot = run/'models/value/ebm'/str(year)/GENERATION
    rp, model_path = slot/'fit_receipt.json', slot/'model.joblib'
    assert_write_path(rp, 'backtest')
    if not slot.resolve().is_relative_to(run.resolve()):
        raise ValueError('REPAIR_SLOT_OUTSIDE_OWN_RUN')
    if rp.exists():
        receipt = json.loads(rp.read_text(encoding='utf-8'))
        if (receipt.get('status') != 'TRAINED' or receipt.get('generation') != GENERATION
                or receipt.get('reuse_tuple_sha256') != tuple_sha
                or values.sha(model_path) != receipt.get('model_sha256')):
            raise RuntimeError('EXISTING_REPAIR_SLOT_NO_SECOND_RETRY')
        result = joblib.load(model_path)
        result.receipt = receipt
        return result
    log = run/'FIT_LOG.jsonl'
    attempts = [event for event in values._events(log) if event.get('event') == 'MODEL_YEAR_ATTEMPT_STARTED']
    if any(event.get('model_id') == LEDGER_ID and event.get('year') == year for event in attempts):
        raise RuntimeError('SINGLE_EBM_REPAIR_ALREADY_ATTEMPTED')
    if len(attempts) >= auth['max_model_year_attempts']:
        raise RuntimeError('MODEL_YEAR_ATTEMPT_BUDGET_EXHAUSTED')
    slot.mkdir(parents=True, exist_ok=True)
    values._append(log, dict(event='MODEL_YEAR_ATTEMPT_STARTED', model_id=LEDGER_ID, year=year,
                            generation=GENERATION, reuse_tuple_sha256=tuple_sha))
    receipt = dict(status='RUNNING', model_id='ebm', ledger_model_id=LEDGER_ID, year=year,
                   generation=GENERATION, role=values.ROLE, seed=values.SEED, fit_units=0,
                   reuse_tuple=reuse, reuse_tuple_sha256=tuple_sha, model_path=str(model_path),
                   receipt_path=str(rp), old_failed_receipt=dict(old_pin),
                   training_rows=len(train), calibration_rows=len(cal),
                   train_label_maturity_max=train.label_mature_date.max().isoformat(),
                   calibration_label_maturity_max=cal.label_mature_date.max().isoformat(),
                   scientific_target_qualified=True, scientific_feature_pit_qualified=True,
                   dependency_paths=list(auth['dependency_paths']),
                   repair_transport=transport, warnings=[])
    write_json_atomic(rp, receipt)
    try:
        native = values._native(auth['dependency_paths'])
        bundle = native.NativeBundle('ebm', list(binding['features']))
        x = values.transform(None, train[binding['features']].to_numpy(float))
        y = train.y_open5.to_numpy(float)  # Guarded mature shareholder target; never clipped.
        bundle.estimator_object = values._fit_job(
            'predictor', LEDGER_ID, x, y, train.signal_date.to_numpy(), None,
            auth['dependency_paths'], binding['features'], transport,
            log=log, auth=auth, prior=config['prior_cumulative_fit_units'], year=year,
            tuple_sha=tuple_sha, receipt=receipt, worker_target=repair_worker)
        cx = values.transform(None, cal[binding['features']].to_numpy(float))
        with threadpool_limits(limits=1):
            raw = bundle.raw_predict(cx)
        values._component_start(log, auth, config['prior_cumulative_fit_units'], LEDGER_ID,
                                year, 'HELDOUT_RESIDUAL_SIGMA', tuple_sha)
        receipt['fit_units'] += 1
        write_json_atomic(rp, receipt)
        calibration = values.heldout_calibration('ebm', raw, cal.y_open5.to_numpy(float))
        # Preserve old bytes/source gates, but the current attempt is legitimately outstanding.
        frozen_contract(run, year, check_stage=False)
        receipt['status'] = 'TRAINED'
        result = values.ValueFit(bundle, calibration, receipt)
        joblib.dump(result, model_path)
        receipt['model_sha256'] = values.sha(model_path)
        receipt['calibration'] = calibration
        write_json_atomic(rp, receipt)
        values._append(log, dict(event='MODEL_YEAR_COMPLETE', model_id=LEDGER_ID, year=year,
                                generation=GENERATION, status='TRAINED', fit_units=receipt['fit_units'],
                                reuse_tuple_sha256=tuple_sha, model_sha256=receipt['model_sha256']))
        return result
    except BaseException as exc:
        receipt.update(status='FAILED', failure=dict(type=type(exc).__name__, message=str(exc)))
        write_json_atomic(rp, receipt)
        values._append(log, dict(event='MODEL_YEAR_FAILED', model_id=LEDGER_ID, year=year,
                                generation=GENERATION, fit_units=receipt['fit_units'], failure=receipt['failure']))
        raise


def publish_prediction(fitted, reader, run_dir, year):
    frozen_contract(run_dir, year)
    if (fitted.receipt.get('generation') != GENERATION or fitted.receipt.get('year') != year
            or fitted.receipt.get('model_id') != 'ebm'):
        raise ValueError('ONLY_QUALIFIED_EBM_TECHNICAL_REPAIR_PUBLICATION')
    return values.publish_prediction(fitted, reader, run_dir, year)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--year', type=int, choices=YEARS, required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--predict', action='store_true')
    args = parser.parse_args(argv)
    if args.check_only:
        frozen_contract(args.run_dir, args.year)
        print(json.dumps(dict(status='READY', method='ebm', year=args.year, actual_fit_started=0)))
        return 0
    from scripts.research.a2.training.stateful_inputs import InputReader
    frozen_contract(args.run_dir, args.year)
    reader = InputReader(Path(args.run_dir).resolve())
    fitted = repair_annual(args.year, args.run_dir, reader=reader)
    if args.predict:
        publish_prediction(fitted, reader, args.run_dir, args.year)
    print(json.dumps({key: fitted.receipt[key] for key in ('status', 'model_id', 'year', 'generation', 'fit_units', 'model_path')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
