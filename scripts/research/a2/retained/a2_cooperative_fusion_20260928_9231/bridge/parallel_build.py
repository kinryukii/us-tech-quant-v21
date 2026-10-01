"""Two read-only ledger expanders; preserve completed serial bridge outputs.

Imports the unchanged bridge_report and its unchanged original accounting code.
Only the final assembly reuses completed outputs instead of re-expanding paths.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
import bridge_report as report

b = report.bridge
pa.set_cpu_count(2)
pa.set_io_thread_count(2)


def source_ledger_paths(year, name):
    directory = ROOT/f'evaluation_{year}/cost_10/{name}'
    return [directory/f'{x}.parquet' for x in b.LEDGERS] + [directory/'metadata.json', directory/'DONE.json']


def check_existing(year, name):
    check = OUT/f'CHECK_{year}_{name}.json'
    path = OUT/f'actual_account_bridge_{year}_{name}.parquet'
    if not check.exists():
        if path.exists():
            raise RuntimeError(f'INCOMPLETE_UNRECEIPTED_OUTPUT_REQUIRES_REVIEW:{path}')
        return None
    summary = json.loads(check.read_text(encoding='utf-8'))
    assert summary['year'] == year and summary['policy'] == name
    assert b.sha(path) == summary['sha256']
    assert (ROOT/summary['path']).resolve() == path.resolve()
    return summary


def worker(index):
    manifest = json.loads((OUT/'PARALLEL_PRE_BUILD.json').read_text(encoding='utf-8'))
    for path, expected in manifest['common_source_sha256'].items():
        assert b.sha(path) == expected, f'PRE_WORKER_SOURCE_CHANGED:{path}'
        b.INPUTS[path] = expected
    features = prices = None
    loaded_year = None
    completed = []
    started = time.monotonic()
    for year, name in manifest['jobs'][str(index)]:
        if check_existing(year, name) is not None:
            raise RuntimeError('WORKER_JOB_ALREADY_COMPLETE_NO_OVERWRITE')
        if loaded_year != year:
            features, prices = b.source_tables(year)
            loaded_year = year
        print(json.dumps(dict(worker=index,starting_bridge=name,year=year)), flush=True)
        summary, _, _ = b.build_path(year, name, features, prices)
        completed.append(summary)
        print(json.dumps(dict(worker=index,finished=name,year=year,rows=summary['rows'],seconds=time.monotonic()-started)), flush=True)
    for path, expected in b.INPUTS.items():
        assert b.sha(path) == expected, f'WORKER_INPUT_CHANGED:{path}'
    b.dump(OUT/f'WORKER_{index}_COMPLETE.json', dict(status='PASS',worker=index,
        completed_paths=[[x['year'],x['policy']] for x in completed],input_sha256=b.INPUTS,
        fit_calls=0,predict_calls=0,replay_calls=0,seconds=time.monotonic()-started))


def cached_path(year, name, features, prices):
    """Use verified machine tables for the unchanged report's final assembly."""
    summary = check_existing(year, name)
    if summary is None:
        raise RuntimeError('MISSING_COMPLETED_PATH')
    frame = b.read_frame(ROOT/summary['path'])
    assert len(frame) == summary['rows']
    last = frame.loc[frame.signal_date.eq(frame.signal_date.max())].copy()
    last['display_priority'] = np.select([last.actual_state_top20,last.target_weight.gt(0),
        last.post_units.gt(0),last.has_recorded_rejection],[0,1,2,3],default=4)
    last = last.loc[last.display_priority.lt(4)].sort_values(['display_priority','actual_state_rank','ticker'],kind='stable')
    examples = []
    for flag in ['high_rank_zero_target','positive_target_no_trade','reconstructed_capacity_limited',
                 'held_without_decision_input','known_glw_input_conflict']:
        sample = frame.loc[frame[flag]].head(3).copy()
        sample['example_category'] = flag
        examples.append(sample)
    return summary,last,pd.concat(examples,ignore_index=True)


def main():
    started = time.monotonic()
    if (OUT/'COMPLETE.json').exists() or (OUT/'PARALLEL_PRE_BUILD.json').exists():
        raise RuntimeError('PRESERVE_EXISTING_PARALLEL_RUN')
    common_paths = [Path(__file__), ROOT/'bridge_report.py', report.OLD,
        ROOT/'EXPERIMENT_CONTRACT.md', ROOT/'policy.py']
    for year in (2025, 2026):
        common_paths += [ROOT/f'evaluation_{year}/cost_10/COMPLETE.json',
                         ROOT/f'evaluation_{year}/cost_10/FROZEN_BEFORE_REPLAY.json']
    common = {str(p):b.sha(p) for p in common_paths}
    carried = []
    remaining = []
    handoff_sources = {}
    for year in (2025, 2026):
        for name in report.NAMES:
            prior = check_existing(year, name)
            if prior is None:
                remaining.append([year, name])
            else:
                carried.append(dict(year=year,policy=name,output_sha256=prior['sha256'],
                    check_sha256=b.sha(OUT/f'CHECK_{year}_{name}.json')))
                for path in source_ledger_paths(year, name):
                    handoff_sources[str(path)] = b.sha(path)
    assert len(carried)+len(remaining) == 14
    jobs = {str(i):remaining[i::2] for i in range(2)}
    b.dump(OUT/'PARALLEL_PRE_BUILD.json',dict(status='FROZEN',created_utc=pd.Timestamp.now(tz='UTC'),
        common_source_sha256=common,completed_serial_paths_preserved=carried,
        completed_serial_source_sha256_resnapshot=handoff_sources,jobs=jobs,workers=2,
        serial_handoff='Original serial process stopped after three complete path checks; unfinished in-memory gate expansion discarded. No completed output rewritten.',
        provenance_limit='Earlier serial in-memory INPUTS map was not persisted. Sources of carried completed checks were rehashed at handoff; current closed ledgers and outputs are preserved and checked again at finalization.',
        no_new_model_prediction_fit_or_replay=True))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    processes = []
    logs = []
    try:
        for index in (0,1):
            log = (OUT/f'worker_{index}.log').open('w',encoding='utf-8')
            logs.append(log)
            processes.append(subprocess.Popen([sys.executable,'-B',str(__file__),'--worker',str(index)],
                cwd=str(ROOT.parent),stdout=log,stderr=subprocess.STDOUT,env=env,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        failures = []
        for index, process in enumerate(processes):
            code = process.wait()
            if code:
                failures.append(dict(worker=index,exit_code=code))
        if failures:
            b.dump(OUT/'PARALLEL_FAILED.json',dict(failures=failures))
            raise RuntimeError(f'PARALLEL_WORKER_FAILED:{failures}')
    finally:
        for log in logs:
            log.close()
    all_sources = {**common,**handoff_sources}
    for index in (0,1):
        receipt = json.loads((OUT/f'WORKER_{index}_COMPLETE.json').read_text(encoding='utf-8'))
        assert receipt['status'] == 'PASS'
        assert receipt['completed_paths'] == jobs[str(index)]
        for path, expected in receipt['input_sha256'].items():
            if path in all_sources and all_sources[path] != expected:
                raise AssertionError(f'CROSS_WORKER_SOURCE_IDENTITY_MISMATCH:{path}')
            all_sources[path] = expected
    for path, expected in all_sources.items():
        assert b.sha(path) == expected, f'FINALIZATION_SOURCE_CHANGED:{path}'
    for prior in carried:
        now = check_existing(prior['year'],prior['policy'])
        assert now['sha256'] == prior['output_sha256']
        assert b.sha(OUT/f"CHECK_{prior['year']}_{prior['policy']}.json") == prior['check_sha256']
    # Reuse original final report generation in an empty owned staging directory.
    # build_path becomes a reader of completed outputs; no account expansion repeats.
    assembly = OUT/'_assembly'
    assembly.mkdir(exist_ok=False)
    report.OUT = assembly
    b.INPUTS = all_sources
    b.build_path = cached_path
    b.source_tables = lambda year: (None,None)
    report.build()
    for path in assembly.iterdir():
        target = OUT/path.name
        if target.exists():
            raise RuntimeError(f'ASSEMBLY_DESTINATION_ALREADY_EXISTS:{target}')
        path.rename(target)
    report.OUT = OUT
    b.dump(OUT/'PARALLEL_COMPLETE.json',dict(status='PASS',workers=2,paths=14,
        completed_serial_paths_reused=len(carried),newly_expanded_paths=len(remaining),
        all_source_hashes_agreed_and_unchanged=True,original_script_sha256_unchanged=b.sha(ROOT/'bridge_report.py')==common[str(ROOT/'bridge_report.py')],
        new_fit_calls=0,new_predict_calls=0,new_replay_calls=0,seconds=time.monotonic()-started))
    report.join_reference()
    print(json.dumps(dict(status='PASS',paths=14,serial_paths_reused=len(carried),seconds=time.monotonic()-started)),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker',type=int,choices=(0,1))
    args = parser.parse_args()
    worker(args.worker) if args.worker is not None else main()
