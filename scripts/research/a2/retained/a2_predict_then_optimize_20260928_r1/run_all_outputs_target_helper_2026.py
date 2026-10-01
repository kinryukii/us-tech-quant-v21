"""One-process orchestration of the frozen 31 all_outputs target routes.

Calls the unmodified public initialize/chunk_worker functions. It never calls
the grid main function and writes no global comparison or completion file.
The monitor reads leaf completion files and writes only its own diagnostics.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

import pandas as pd

from common import ROOT, read, write, sha
from freeze_batch import validate_global_freeze
import run_replays as replay


SELF = Path(__file__).resolve()
PROGRESS = ROOT / 'diagnostics/TARGET_ALL_OUTPUTS_HELPER_2026_PROGRESS.json'
RECEIPT = ROOT / 'diagnostics/TARGET_ALL_OUTPUTS_HELPER_2026_RECEIPT.json'


def utc():
    return datetime.now(timezone.utc).isoformat()


def leaf_status(specs):
    completed = failed = 0
    active = []
    attempts = []
    for s in specs:
        folder = ROOT / 'evaluation_2026' / s['strategy_id']
        if (folder / 'DONE.json').is_file():
            try:
                if read(folder / 'DONE.json')['status'] == 'REPLAY_COMPLETE':
                    completed += 1
            except (OSError, ValueError, KeyError):
                active.append(s['strategy_id'])
        elif (folder / 'FAILURE.json').is_file():
            failed += 1
        elif folder.exists():
            active.append(s['strategy_id'])
        if (folder / 'attempts').exists():
            attempts.append(s['strategy_id'])
    return dict(completed=completed, failed=failed, active=active, attempts=attempts)


def main():
    started = utc()
    frozen = validate_global_freeze()
    frozen_sha = sha(ROOT / 'GLOBAL_FREEZE.json')
    self_sha = sha(SELF)
    covered_path = ROOT / 'COMBINATION_COVERAGE.csv'
    assert sha(covered_path) == frozen['artifact_sha256']['COMBINATION_COVERAGE.csv']
    specs = [s for s in replay.strategies()
             if s['route'] == 'target_fusion' and s['coalition'] == 'all_outputs']
    coverage = pd.read_csv(covered_path)
    covered = coverage.loc[coverage.route.eq('target_fusion') & coverage.coalition.eq('all_outputs')]
    ids = [s['strategy_id'] for s in specs]
    assert len(specs) == len(set(ids)) == len(covered) == 31
    assert set(ids) == set(covered.strategy_id)
    assert all(len(s['members']) == 31 for s in specs)
    for s in specs:
        bound = covered.loc[covered.strategy_id.eq(s['strategy_id'])].iloc[0]
        assert all(str(bound[k]) == str(s[k]) for k in ['route', 'coalition', 'risk', 'optimizer', 'forecast_id'])
        folder = ROOT / 'evaluation_2026' / s['strategy_id']
        if folder.exists() and not (folder / 'DONE.json').is_file():
            raise RuntimeError('PREEXISTING_UNFINISHED_TARGET_LEAF:' + s['strategy_id'])
    assert PROGRESS.relative_to(ROOT).as_posix() not in frozen['artifact_sha256']
    assert RECEIPT.relative_to(ROOT).as_posix() not in frozen['artifact_sha256']
    if RECEIPT.exists() or PROGRESS.exists():
        raise RuntimeError('HELPER_DIAGNOSTICS_ALREADY_EXIST; preserve previous helper run')
    sources = {p: h for p, h in frozen['artifact_sha256'].items()}
    forecasts = {str(Path('predictions/forecasts/2026') / ('single__' + m + '.parquet')):
                 sha(ROOT / 'predictions/forecasts/2026' / ('single__' + m + '.parquet'))
                 for m in specs[0]['members']}
    plan = dict(status='STARTING_FROZEN_PUBLIC_CHUNK', pid=os.getpid(), started_utc=started,
        helper_source=str(SELF.relative_to(ROOT)), helper_source_sha256=self_sha,
        global_freeze_sha256=frozen_sha, strategy_ids=ids, expected=31, year=2026,
        route='target_fusion', coalition='all_outputs', resume=True,
        orchestration='validate_global_freeze; initialize(2026); chunk_worker((specs, True))',
        original_frozen_sha256=sources, forecast_sha256=forecasts,
        global_comparison_or_complete_writes=False, fitting_allowed=False)
    write(PROGRESS, plan)
    print(json.dumps(dict(status=plan['status'], pid=os.getpid(), expected=31,
                         global_freeze_sha256=frozen_sha)), flush=True)
    replay.initialize(2026)
    assert replay.ENV['guard']['attempts'] == 0
    # Inspect installed guards without making even a deliberate fitting call.
    import torch
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from models_native import NativeBundle
    guards = dict(native=NativeBundle.fit.__func__.__name__ == 'denied',
        pipeline=Pipeline.fit.__name__ == 'denied', scaler=StandardScaler.fit.__name__ == 'denied',
        adam=torch.optim.Adam.step.__name__ == 'denied', sgd=torch.optim.SGD.step.__name__ == 'denied',
        hgbvol=replay.ENV['risk'].vol_models['hgbvol'].fit.__name__ == 'denied',
        mlpvol=replay.ENV['risk'].vol_models['mlpvol'].fit.__name__ == 'denied')
    assert all(guards.values())
    stop = threading.Event()
    alerts = []
    tail_notified = False
    monitor_error = []

    def monitor():
        nonlocal tail_notified
        while not stop.wait(20):
            try:
                status = leaf_status(specs)
                payload = dict(plan, status='RUNNING_ORIGINAL_CHUNK', updated_utc=utc(),
                    guard_fit_attempts=replay.ENV['guard']['attempts'], installed_fit_guards=guards, **status)
                write(PROGRESS, payload)
                print(json.dumps(dict(kind='helper_progress', updated_utc=payload['updated_utc'],
                                      **status)), flush=True)
                if status['attempts']:
                    alert = dict(kind='UNEXPECTED_ATTEMPT_ARCHIVE', routes=status['attempts'], at_utc=utc())
                    alerts.append(alert)
                    print(json.dumps(alert), flush=True)
                tail = list((ROOT / 'evaluation_2026').glob('cross_structure__target_blend__*'))
                if tail and not tail_notified and status['completed'] + status['failed'] < 31:
                    tail_notified = True
                    alert = dict(kind='MAIN_APPROACHING_LAST_TARGET_GROUPS', at_utc=utc(),
                                 helper_completed=status['completed'], helper_failed=status['failed'])
                    alerts.append(alert)
                    print(json.dumps(alert), flush=True)
            except Exception as error:
                monitor_error.append(type(error).__name__ + ':' + str(error))
                print(json.dumps(dict(kind='MONITOR_ERROR', reason=monitor_error[-1])), flush=True)

    thread = threading.Thread(target=monitor, name='helper-readonly-leaf-monitor', daemon=True)
    thread.start()
    begin = time.monotonic()
    try:
        rows = replay.chunk_worker((specs, True))
    finally:
        stop.set()
        thread.join()
    assert len(rows) == 31 and {r['strategy_id'] for r in rows} == set(ids)
    assert replay.ENV['guard']['attempts'] == 0
    for row in rows:
        if row['status'] == 'REPLAY_COMPLETE':
            folder = ROOT / 'evaluation_2026' / row['strategy_id']
            assert row['model_batch_freeze_sha256'] == frozen_sha
            assert row['guard_fit_attempts'] == 0
            for path, digest in row['ledger_sha256'].items():
                assert sha(folder / path) == digest
    validate_global_freeze()
    assert sha(ROOT / 'GLOBAL_FREEZE.json') == frozen_sha and sha(SELF) == self_sha
    assert all(sha(ROOT / p) == h for p, h in forecasts.items())
    receipt = dict(plan, status='FINISHED_ORIGINAL_PUBLIC_CHUNK', finished_utc=utc(),
        seconds=time.monotonic()-begin, completed=sum(r['status'] == 'REPLAY_COMPLETE' for r in rows),
        failed=sum(r['status'] == 'FAILED' for r in rows), guard_fit_attempts=0,
        installed_fit_guards=guards, all_frozen_sha256_unchanged=True,
        all_forecast_sha256_unchanged=True, all_completed_leaf_ledgers_hash_verified=True,
        alerts=alerts, monitor_errors=monitor_error,
        output_receipts={r['strategy_id']: sha(ROOT / 'evaluation_2026' / r['strategy_id'] /
            ('DONE.json' if r['status'] == 'REPLAY_COMPLETE' else 'FAILURE.json')) for r in rows},
        failures=[r for r in rows if r['status'] == 'FAILED'])
    write(RECEIPT, receipt)
    write(PROGRESS, {k: v for k, v in receipt.items()
                     if k not in {'original_frozen_sha256', 'forecast_sha256'}})
    print(json.dumps(dict(status=receipt['status'], completed=receipt['completed'],
                         failed=receipt['failed'], guard_fit_attempts=0,
                         receipt=str(RECEIPT.relative_to(ROOT)))), flush=True)


if __name__ == '__main__':
    main()
