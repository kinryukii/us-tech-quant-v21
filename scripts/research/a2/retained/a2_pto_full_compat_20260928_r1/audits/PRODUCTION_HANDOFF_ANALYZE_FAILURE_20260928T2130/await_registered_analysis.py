"""Wait for the existing fixed jobs, then run only complete-list analysis.

This does not dispatch replay tasks, fit models, change candidates, or select a
strategy. Visual QA and final delivery remain separate review steps.
"""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'FINALIZATION_STATE.json'


def read(relative):
    try:
        return json.loads((ROOT / relative).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save(record):
    record.update(created_utc=datetime.now(timezone.utc).isoformat(),
                  pid=os.getpid(), executable=sys.executable,
                  fit_calls=0, replay_dispatches=0, new_candidates=0,
                  selection_or_tuning_calls=0)
    STATE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')


def barriers():
    counts = {}
    for year in [2025, 2026]:
        count = 0
        for number in range(36):
            folder = Path(f'results/{year}/batch_{number:03d}')
            failed = read(folder / 'FAILED.json')
            if failed:
                raise RuntimeError('EXISTING_REPLAY_FAILED:' + str(folder))
            done = read(folder / 'COMPLETE.json')
            if done:
                if done.get('status') != 'REPLAYED' or done.get('accounts') != 308:
                    raise RuntimeError('INVALID_REGISTERED_SEAL:' + str(folder))
                count += 1
        counts[str(year)] = count
    independent = read('INDEPENDENT_VERIFICATION.json') or {}
    targets = read('analysis/TARGET_FUSION_DECISION_RECEIPT.json') or {}
    quality = read('analysis/SOLVER_QUALITY_RECEIPT.json') or {}
    ready = (counts == {'2025': 36, '2026': 36}
             and independent.get('status') == 'PASS_COMPLETE'
             and independent.get('coverage_complete') is True
             and targets.get('complete') is True
             and targets.get('observed_expert_rows') == 7488
             and quality.get('complete') is True)
    return ready, dict(completed_batches=counts,
                       independent_status=independent.get('status'),
                       target_contributions_complete=targets.get('complete', False),
                       solver_quality_complete=quality.get('complete', False))


def run(script, *arguments):
    save(dict(status='RUNNING_DERIVATIVE_ANALYSIS', script=script,
              arguments=list(arguments)))
    print('RUN_DERIVATIVE', script, *arguments, flush=True)
    with (ROOT / 'finalization.log').open('a', encoding='utf-8') as log:
        log.write('\n' + datetime.now(timezone.utc).isoformat() + ' ' + script + '\n')
        log.flush()
        completed = subprocess.run([sys.executable, str(ROOT / script), *arguments],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode:
        raise RuntimeError('DERIVATIVE_ANALYSIS_FAILED:' + script)


def main():
    previous = None
    last_notice = 0.0
    while True:
        ready, state = barriers()
        key = json.dumps(state, sort_keys=True)
        if key != previous or time.monotonic() - last_notice >= 45:
            save(dict(status='WAITING_EXISTING_REGISTERED_JOBS', **state))
            print(json.dumps(state, ensure_ascii=False), flush=True)
            previous = key
            last_notice = time.monotonic()
        if ready:
            break
        time.sleep(20)
    run('target_expert_analysis.py', '--require-complete')
    run('solver_quality_analysis.py', '--require-complete')
    run('analyze.py')
    receipt = read('analysis/ANALYSIS_RECEIPT.json') or {}
    if not receipt.get('complete') or receipt.get('rows') != 22176:
        raise RuntimeError('EXACT_REGISTERED_ANALYSIS_NOT_COMPLETE')
    run('dimension_reports.py')
    save(dict(status='READY_FOR_PRODUCTION_FIGURES_AND_VISUAL_QA',
              analysis_rows=22176, registered_jobs_complete=True,
              final_delivery_complete=False,
              next_steps=['figures.py and visual QA', 'verify_completion.py',
                          'build_report.py', 'inspect final report and deliver']))
    print('READY_FOR_PRODUCTION_FIGURES_AND_VISUAL_QA', flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        save(dict(status='FAILED_NO_AUTOMATIC_LEARNING_RECOVERY',
                  reason=type(error).__name__ + ':' + str(error),
                  traceback=traceback.format_exc()))
        raise
