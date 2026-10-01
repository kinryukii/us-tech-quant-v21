"""Serial processes limit RAM; every stage retains an explicit completion gate."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from integrity import ROOT, read, write, verify_freeze

def main():
    verify_freeze()
    stages = [
        ('predict_2025', ['run_retest.py', '--predict', '2025']),
        ('predict_2026', ['run_retest.py', '--predict', '2026']),
        ('replay_2025', ['run_retest.py', '--run', '2025']),
        ('replay_2026', ['run_retest.py', '--run', '2026']),
        ('audit_2025', ['run_retest.py', '--audit', '2025']),
        ('audit_2026', ['run_retest.py', '--audit', '2026']),
        ('analysis', ['analyze_retest.py']),
    ]
    result = ROOT / 'results'
    result.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    environment['OMP_NUM_THREADS'] = '2'
    environment['MKL_NUM_THREADS'] = '2'
    state_path = ROOT / 'RUN_STATE.json'
    previous = read(state_path) if state_path.exists() else {}
    completed = previous.get('completed_stages', [])
    for name, args in stages:
        state = {'state': 'RUNNING_FROZEN_BASELINE_INTERVENTION', 'phase': name,
                 'completed_stages': completed, 'controller_pid': os.getpid(),
                 'updated_utc': datetime.now(timezone.utc).isoformat(),
                 'declared_paths_per_year': 8247, 'declared_account_years': 16494,
                 'new_original_base_model_fit_calls': 0,
                 'post_test_search_allowed': False, 'blind_test': False,
                 'future_history_stage': 'FIXED_1_3_5_7_9_YEARS_AFTER_THIS_BATCH'}
        write(state_path, state)
        log_path = result / f'{name}.log'
        print('PHASE', name, 'START', flush=True)
        with log_path.open('a', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-B', '-u', *args], cwd=ROOT,
                                       env=environment, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            state['worker_pid'] = process.pid
            write(state_path, state)
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
            code = process.wait()
        if code:
            state.update(state='STOPPED_RUNTIME_FAILURE_PRESERVE_OUTPUTS', exit_code=code,
                         diagnostic_log=str(log_path), updated_utc=datetime.now(timezone.utc).isoformat())
            write(state_path, state)
            raise SystemExit(code)
        if name not in completed:
            completed.append(name)
        print('PHASE', name, 'COMPLETE', flush=True)
    verify_freeze()
    write(state_path, {'state': 'FIXED_RESEARCH_RETEST_COMPLETE_FORMAL_FULLPOOL_BLOCKED_DATA',
          'phase': 'fixed_list_complete', 'completed_stages': completed,
          'declared_account_years': 16494, 'post_test_search_allowed': False,
          'blind_test': False, 'updated_utc': datetime.now(timezone.utc).isoformat(),
          'delivery': str(ROOT / 'results/analysis/REPORT.md'),
          'next_stage': 'separate historical-data 1/3/5/7/9-year baseline assessment'})
    print('FIXED_RETEST_COMPLETE', flush=True)

if __name__ == '__main__':
    main()
