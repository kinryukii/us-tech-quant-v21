"""Spawn processes around unchanged build_delivery.run; default does no full run.

The original audit_all local callable is cloudpickled once per executor, loaded
once by each worker initializer, and never attached to individual task payloads.
--proof audits a fixed representative set only. --run requires separate root
authorization and executes the original complete run without skipping any gate.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import joblib
from joblib.externals import cloudpickle
import build_delivery as b
from common import sha, read, write, clean, forecasts

ORIGINAL_THREAD_EXECUTOR = b.ThreadPoolExecutor
WORKER_FUNCTION = None
WORKER_INFO = None
POOL_EVENTS = []
RUN_MODE = 'proof'


def source_metadata():
    return {'caller_path': str(Path(__file__).resolve()), 'caller_sha256': sha(Path(__file__)),
            'original_path': str(Path(b.__file__).resolve()), 'original_sha256': sha(Path(b.__file__)),
            'global_freeze_sha256': sha(ROOT / 'GLOBAL_FREEZE.json'), 'mode': RUN_MODE,
            'joblib_version': joblib.__version__, 'cloudpickle_version': cloudpickle.__version__,
            'caller_directly_bound_by_global': False}


def worker_initialize(payload, metadata):
    global WORKER_FUNCTION, WORKER_INFO
    init_started = time.perf_counter()
    assert str(Path(b.__file__).resolve()) == metadata['original_path'], 'WORKER_ORIGINAL_MODULE_PATH_MISMATCH'
    assert str(Path(__file__).resolve()) == metadata['caller_path'], 'WORKER_CALLER_PATH_MISMATCH'
    assert sha(Path(b.__file__)) == metadata['original_sha256'], 'WORKER_ORIGINAL_SOURCE_CHANGED'
    assert sha(Path(__file__)) == metadata['caller_sha256'], 'WORKER_CALLER_SOURCE_CHANGED'
    assert sha(ROOT / 'GLOBAL_FREEZE.json') == metadata['global_freeze_sha256'], 'WORKER_GLOBAL_FREEZE_DOCUMENT_CHANGED'
    assert hashlib.sha256(payload).hexdigest() == metadata['closure_sha256'], 'WORKER_CLOSURE_PAYLOAD_CHANGED'
    assert joblib.__version__ == metadata['joblib_version'] and cloudpickle.__version__ == metadata['cloudpickle_version']
    WORKER_FUNCTION = cloudpickle.loads(payload)
    initialized_wall_ns = time.time_ns()
    WORKER_INFO = {**metadata, 'pid': os.getpid(), 'closure_loads': 1,
                   'source_guard_and_closure_load_seconds': time.perf_counter() - init_started,
                   'pool_launch_to_initializer_ready_seconds': (initialized_wall_ns - metadata['pool_launch_wall_ns']) / 1e9,
                   'worker_source_guards': 'PASS', 'full_global_artifact_guard_scope': 'original caller gate_inputs, not a substitute in initializer'}
    write(ROOT / 'diagnostics' / f'DELIVERY_PROCESS_{metadata["mode"].upper()}_WORKER_{os.getpid()}.json', WORKER_INFO)


def invoke_original(task):
    assert WORKER_FUNCTION is not None, 'WORKER_CLOSURE_NOT_INITIALIZED'
    # PID is transport bookkeeping; caller yields the original unmodified dict.
    return WORKER_FUNCTION(task), os.getpid()


class CloudpickleProcessExecutor:
    """Drop-in context manager/map for the exact original audit_all usage."""
    def __init__(self, max_workers=None, **kwargs):
        if kwargs:
            raise TypeError('Unsupported original executor constructor options: ' + str(sorted(kwargs)))
        self.max_workers = max(1, min(int(max_workers or 4), 4))
        self.pool = None
        self.event = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.pool is not None:
            self.pool.shutdown(wait=True)
        if self.event is not None:
            self.event['shutdown_complete'] = True
        return False

    def map(self, fn, *iterables, timeout=None, chunksize=1):
        if self.pool is not None or len(iterables) != 1:
            raise ValueError('Adapter supports one map and one task iterable, exactly as original audit_all')
        assert Path(inspect.getsourcefile(fn)).resolve() == Path(b.__file__).resolve(), 'CALLABLE_NOT_ORIGINAL_DELIVERY_SOURCE'
        assert fn.__qualname__ == 'audit_all.<locals>.one', 'CALLABLE_NOT_ORIGINAL_AUDIT_ALL_ONE'
        started = time.perf_counter()
        payload = cloudpickle.dumps(fn)
        metadata = {**source_metadata(), 'closure_sha256': hashlib.sha256(payload).hexdigest(),
                    'closure_size_bytes': len(payload), 'qualname': fn.__qualname__,
                    'closure_serialization_calls': 1, 'serialize_seconds': time.perf_counter() - started,
                    'pool_launch_wall_ns': time.time_ns()}
        self.event = {**metadata, 'max_workers': self.max_workers, 'context': 'spawn',
                      'result_count': 0, 'tasks_by_worker': {}, 'task_closure_payloads': 0,
                      'map_started_utc': datetime.now(timezone.utc).isoformat(), 'shutdown_complete': False}
        POOL_EVENTS.append(self.event)
        self.pool = ProcessPoolExecutor(max_workers=self.max_workers, mp_context=mp.get_context('spawn'),
                                        initializer=worker_initialize, initargs=(payload, metadata))
        process_results = self.pool.map(invoke_original, iterables[0], timeout=timeout, chunksize=chunksize)
        for original_result, pid in process_results:
            self.event['result_count'] += 1
            key = str(pid)
            self.event['tasks_by_worker'][key] = self.event['tasks_by_worker'].get(key, 0) + 1
            yield original_result


@contextmanager
def replaced_executor(executor):
    previous = b.ThreadPoolExecutor
    b.ThreadPoolExecutor = executor
    try:
        yield
    finally:
        b.ThreadPoolExecutor = previous


def exact_dict(left, right, path='root'):
    assert type(left) is type(right), 'TYPE_MISMATCH:' + path
    if isinstance(left, dict):
        assert list(left) == list(right), 'DICT_KEY_ORDER_MISMATCH:' + path
        for key in left:
            exact_dict(left[key], right[key], path + '.' + str(key))
    elif isinstance(left, (tuple, list)):
        assert len(left) == len(right)
        for i, (a, c) in enumerate(zip(left, right)):
            exact_dict(a, c, path + '[' + str(i) + ']')
    elif isinstance(left, (float, np.floating)):
        assert np.isnan(left) == np.isnan(right), 'NAN_MASK_MISMATCH:' + path
        assert np.isfinite(left) == np.isfinite(right), 'FINITE_MASK_MISMATCH:' + path
        assert np.isinf(left) == np.isinf(right), 'INF_MASK_MISMATCH:' + path
        assert (np.isnan(left) and np.isnan(right)) or left == right, 'NUMERIC_EXACT_MISMATCH:' + path
    elif isinstance(left, np.ndarray):
        np.testing.assert_array_equal(left, right)
    else:
        assert left == right, 'VALUE_MISMATCH:' + path


def proof_forecast_inputs(year):
    """Proof reuses preserved PASS diagnostics, not full forecast_provenance."""
    from pyarrow.parquet import read_schema
    path = ROOT / f'input/eval_{year}/features.parquet'
    has_gate = 'new_buy_eligible' in read_schema(path).names
    features = b._parquet(path, ['signal_date','ticker'] + (['new_buy_eligible'] if has_gate else []))
    keys = set(zip(features.signal_date.dt.strftime('%Y-%m-%d'), features.ticker.astype(str)))
    assert len(keys) == len(features)
    eligible = features.new_buy_eligible.eq(True) if has_gate else pd.Series(True, index=features.index)
    buy_keys = set(zip(features.loc[eligible,'signal_date'].dt.strftime('%Y-%m-%d'), features.loc[eligible,'ticker'].astype(str)))
    metrics_path = ROOT / f'diagnostics/forecast_metrics/{year}/FORECAST_METRICS.csv'
    metrics = b._csv(metrics_path)
    assert len(metrics) == 152 and metrics.forecast_id.is_unique and metrics.status.eq('PASS').all()
    receipt_path = metrics_path.with_name('RECEIPT.json')
    receipt = read(receipt_path)
    assert receipt['no_parameter_fitting'] and receipt['no_model_selection']
    assert receipt['forecasts_reported'] == receipt['forecasts_expected'] == 152
    if year == 2026:
        assert receipt['global_freeze_sha256'] == sha(ROOT / 'GLOBAL_FREEZE.json')
    statuses = metrics.set_index('forecast_id').status.to_dict()
    return {'keys': keys, 'buy_eligible_keys': buy_keys, 'forecast_status': statuses}, {
        'features_sha256': sha(path), 'saved_metrics_sha256': sha(metrics_path), 'saved_receipt_sha256': sha(receipt_path),
        'key_count': len(keys), 'new_buy_key_count': len(buy_keys), 'saved_PASS_statuses': len(statuses),
        'scope': 'Saved diagnostic PASS reuse for orchestration proof only; not replacement for full original forecast_provenance'}


def proof():
    global RUN_MODE
    RUN_MODE = 'proof'
    started = time.perf_counter()
    original_meta = source_metadata()
    freeze, contract, roster, tables, controls = b.gate_inputs()
    fixed_ids = ['single__ridge__diag__mv','single__ridge__diag__robust','single__ridge__none__equal_top20',
                 'all_outputs__convex__lw__cvar','single__extra__diag__cvar','all_outputs__target_blend__lw__mv']
    selected = {year: tables[year].set_index('strategy_id').loc[fixed_ids].reset_index() for year in b.YEARS}
    selected_controls = {year: controls[year].set_index('strategy_id').loc[list(b.CONTROLS)].reset_index() for year in b.YEARS}
    contexts, context_receipts = {}, {}
    for year in b.YEARS:
        contexts[year], context_receipts[str(year)] = proof_forecast_inputs(year)
    captured = {}
    class CaptureExecutor:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def map(self, fn, tasks):
            captured['fn'], captured['tasks'] = fn, list(tasks)
            return iter(())
    with replaced_executor(CaptureExecutor):
        empty = b.audit_all(selected, selected_controls, roster, contexts, freeze, workers=4)
    assert empty.empty and len(captured['tasks']) == 22
    fn, tasks = captured['fn'], captured['tasks']
    t0 = time.perf_counter()
    with ORIGINAL_THREAD_EXECUTOR(max_workers=2) as pool:
        reference_dicts = list(pool.map(fn, tasks))
    thread_seconds = time.perf_counter() - t0
    assert all(row['status'] == 'PASS' for row in reference_dicts), 'REFERENCE_REPRESENTATIVE_AUDIT_FAILED'
    print(f'Original one, 2 threads: {len(tasks)} PASS in {thread_seconds:.3f}s', flush=True)
    t0 = time.perf_counter()
    with CloudpickleProcessExecutor(max_workers=4) as pool:
        process_dicts = list(pool.map(fn, tasks))
    process_seconds = time.perf_counter() - t0
    for i, (left, right) in enumerate(zip(reference_dicts, process_dicts)):
        exact_dict(left, right, str(i))
    reference, process = pd.DataFrame(reference_dicts), pd.DataFrame(process_dicts)
    pd.testing.assert_frame_equal(reference, process, check_exact=True, check_dtype=True, check_names=True, check_like=False)
    assert reference.isna().equals(process.isna()), 'DATAFRAME_NAN_MASK_MISMATCH'
    numeric = reference.select_dtypes(include=[np.number]).columns
    assert np.array_equal(np.isfinite(reference[numeric]), np.isfinite(process[numeric]))
    assert np.array_equal(np.isinf(reference[numeric]), np.isinf(process[numeric]))
    metadata = source_metadata()
    assert metadata == original_meta, 'PROOF_SOURCE_CHANGED'
    work_event = POOL_EVENTS[-1]
    rows = []
    for task, result in zip(tasks, process_dicts):
        year, row, control = task
        rows.append({'year': year, 'strategy_id': row['strategy_id'], 'control': control, 'status': result['status'],
                     'dict_keys_and_types_exact': True, 'numeric_exact': True, 'finite_inf_nan_masks_exact': True,
                     'nan_fields': [key for key, value in result.items() if isinstance(value, (float,np.floating)) and np.isnan(value)],
                     'fixture_trades': row.get('trades'), 'fixture_stale_days': row.get('stale_valuation_days'),
                     'fixture_uncertified_days': row.get('uncertified_valuation_days'),
                     'original_done_sha256': sha(ROOT / (f'evaluation_controls_{year}' if control else f'evaluation_{year}') / row['strategy_id'] / 'DONE.json')})
    receipt = {**metadata, 'status': 'PASS_ORIGINAL_AUDIT_PROCESS_EQUIVALENCE', 'created_utc': datetime.now(timezone.utc).isoformat(),
               'global_artifacts_verified_by_original_gate_inputs': len(freeze['artifact_sha256']),
               'full_run_started': False, 'original_thread_full_run_stopped': False,
               'fit_calls': 0, 'replay_calls': 0, 'account_prediction_statistics_writes': 0,
               'sample_scope': 'fixed 6 PTO fixtures per window including 2025 three pilots, trading, cash, CVaR, target; all five controls per window',
               'forecast_proof_context': context_receipts, 'original_one_not_copied': True,
               'dataframe_shape': list(reference.shape), 'dataframe_columns_exact': reference.columns.tolist(),
               'dataframe_dtypes_exact': {key:str(value) for key,value in reference.dtypes.items()},
               'dataframe_nan_cells': int(reference.isna().to_numpy().sum()),
               'strict_dataframe_check': 'pd.testing.assert_frame_equal(check_exact=True, check_dtype=True, check_names=True, check_like=False)',
               'numeric_max_difference': 0., 'rows': rows, 'pool_event': work_event,
               'throughput_once': {'tasks':len(tasks), 'reference_threads':2, 'process_workers':4,
                    'thread_seconds':thread_seconds, 'process_seconds_including_spawn':process_seconds,
                    'thread_tasks_per_second':len(tasks)/thread_seconds, 'process_tasks_per_second':len(tasks)/process_seconds,
                    'elapsed_speedup':thread_seconds/process_seconds,
                    'scope':'One fixed representative benchmark, not extrapolation guarantee; process measured after reference and cache/order may matter'},
               'elapsed_seconds': time.perf_counter()-started,
               'full_run_behavior': 'temporarily replace only b.ThreadPoolExecutor; invoke original b.run(workers=4), retaining every original gate/check/source guard and all 10116 accounts'}
    reference_path = ROOT / 'diagnostics/DELIVERY_PROCESS_PROOF_REFERENCE.pkl'
    process_path = ROOT / 'diagnostics/DELIVERY_PROCESS_PROOF_PROCESS.pkl'
    reference.to_pickle(reference_path)
    process.to_pickle(process_path)
    receipt['strict_dataframe_artifact_sha256'] = {str(path.relative_to(ROOT)).replace('\\','/'):sha(path)
                                                 for path in [reference_path, process_path]}
    receipt['worker_initializer_receipts'] = {str(path.relative_to(ROOT)).replace('\\','/'):sha(path)
        for path in sorted((ROOT / 'diagnostics').glob('DELIVERY_PROCESS_PROOF_WORKER_*.json'))
        if read(path)['closure_sha256'] == work_event['closure_sha256'] and read(path)['caller_sha256'] == metadata['caller_sha256']}
    worker_receipts = [read(ROOT / path) for path in receipt['worker_initializer_receipts']]
    receipt['initialization_observed_seconds'] = {
        'closure_serialize_once': work_event['serialize_seconds'],
        'worker_guard_and_load_min': min(r['source_guard_and_closure_load_seconds'] for r in worker_receipts),
        'worker_guard_and_load_max': max(r['source_guard_and_closure_load_seconds'] for r in worker_receipts),
        'pool_launch_to_ready_min': min(r['pool_launch_to_initializer_ready_seconds'] for r in worker_receipts),
        'pool_launch_to_ready_max': max(r['pool_launch_to_initializer_ready_seconds'] for r in worker_receipts),
        'scope':'Pool startup/import/source guards/deserialization readiness; audit work is excluded from each worker readiness timestamp'}
    write(ROOT / 'diagnostics/DELIVERY_PROCESS_PROOF.json', receipt)
    print(json.dumps({'status':receipt['status'], 'rows':len(rows), 'throughput_once':receipt['throughput_once'],
                      'closure_size_bytes':work_event['closure_size_bytes'], 'closure_sha256':work_event['closure_sha256'],
                      'dataframe_nan_cells':receipt['dataframe_nan_cells']}), flush=True)


def full_run():
    global RUN_MODE
    RUN_MODE = 'full'
    proof_path = ROOT / 'diagnostics/DELIVERY_PROCESS_PROOF.json'
    proven = read(proof_path)
    metadata = source_metadata()
    assert proven['status'] == 'PASS_ORIGINAL_AUDIT_PROCESS_EQUIVALENCE'
    assert proven['caller_sha256'] == metadata['caller_sha256'] and proven['original_sha256'] == metadata['original_sha256']
    assert proven['global_freeze_sha256'] == metadata['global_freeze_sha256'], 'FULL_RUN_PROOF_SOURCE_DRIFT'
    write(ROOT / 'diagnostics/DELIVERY_PROCESS_FULL_STARTED.json', {**metadata, 'created_utc':datetime.now(timezone.utc).isoformat(),
          'proof_sha256':sha(proof_path), 'original_complete_run_called':True, 'account_replay_or_fitting':False})
    try:
        with replaced_executor(CloudpickleProcessExecutor):
            b.run(workers=4)
        status = 'ORIGINAL_FULL_DELIVERY_RUN_RETURNED'
    except BaseException as error:
        write(ROOT / 'diagnostics/DELIVERY_PROCESS_FULL_FAILURE.json', {**metadata, 'status':'ORIGINAL_FULL_RUN_RAISED',
              'type':type(error).__name__, 'error':str(error), 'pool_events':POOL_EVENTS})
        raise
    assert source_metadata() == metadata, 'FULL_RUN_CALLER_OR_ORIGINAL_SOURCE_CHANGED'
    write(ROOT / 'diagnostics/DELIVERY_PROCESS_FULL_RECEIPT.json', {**metadata, 'status':status,
          'proof_sha256':sha(proof_path), 'original_run_unchanged':True, 'pool_events':POOL_EVENTS,
          'fit_calls':0, 'replay_calls':0, 'no_original_gate_or_audit_skipped':True,
          'output_verification_sha256':sha(ROOT / 'report/FINAL_VERIFICATION.json')})


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--proof', action='store_true')
    group.add_argument('--run', action='store_true', help='Full original run; only after separate explicit root authorization')
    args = parser.parse_args()
    if args.proof:
        proof()
    elif args.run:
        full_run()
    else:
        print('READY: default opens no evaluation results; --proof only representative audits; --run requires explicit root start authorization.')


if __name__ == '__main__':
    main()
