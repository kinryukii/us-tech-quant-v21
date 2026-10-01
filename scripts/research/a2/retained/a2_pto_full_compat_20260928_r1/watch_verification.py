"""Finite, read-only incremental proof of the 72 registered replay batches.

Only a changed set/content of COMPLETE records launches the verifier. Its full
SHA256 cache reuses already proved accounts; incomplete accounts never pass.
Both windows are always requested, and the final account total is exactly 22176.
No model, policy, engine, or learning code is modified by this watcher.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd

from independent_verify import ROOT, Evidence, Sources, clean, sha, source_prediction_coverage


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def snapshot(root):
    complete,failed,partial={},[],[]
    for year in [2025,2026]:
        for batch in sorted((root/f'results/{year}').glob('batch_*')):
            seal=batch/'COMPLETE.json'
            failure=batch/'FAILED.json'
            key=f'{year}/{batch.name}'
            if seal.exists():complete[key]=sha(seal)
            elif failure.exists():failed.append({'batch':key,'evidence':json.loads(failure.read_text(encoding='utf-8'))})
            else:partial.append(key)
    return complete,failed,partial


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval',type=float,default=20.,help='bounded polling seconds, maximum 30')
    parser.add_argument('--once',action='store_true',help='one current-snapshot proof without waiting for new seals')
    args=parser.parse_args()
    if not 1 <= args.interval <= 30:raise ValueError('poll interval must be 1..30 seconds')
    root=ROOT
    registry=json.loads((root/'REGISTRY.json').read_text(encoding='utf-8'))
    count=len(registry['strategies'])
    if count != 11088:raise ValueError('registered account count must be 11088 per year')
    expected={f'{year}/batch_{i:03d}' for year in [2025,2026] for i in range(36)}
    output=root/'audits/verification_watch'
    output.mkdir(parents=True,exist_ok=True)
    lock=output/'WATCHER.lock'
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('another verifier watcher owns '+str(lock))
    os.write(descriptor,str(os.getpid()).encode());os.close(descriptor)
    state={'status':'RUNNING','pid':os.getpid(),'started_utc':pd.Timestamp.now(tz='UTC').isoformat(),
           'expected_batches':72,'expected_accounts':22176,'years':[2025,2026],
           'poll_seconds':args.interval,'new_fit_calls':0,'parameter_updates':0,
           'watcher_code_sha256':sha(Path(__file__)),'runs':[]}
    state_path=root/'audits/VERIFICATION_WATCH_STATUS.json'
    last_complete=None
    try:
        # Independently prove final forecasts before consuming any account metric.
        sources=Sources(root,2026)
        ev=Evidence(2026,'FINAL_PREDICTION_SOURCE_KEYS')
        coverage=source_prediction_coverage(root,sources,registry,ev)
        write_json(root/'audits/FINAL_PREDICTION_SOURCE_VERIFICATION.json',coverage)
        state['final_prediction_source_status']=coverage['status']
        if coverage['status'] != 'PASS':
            state.update(status='FAILED_FINAL_PREDICTION_SOURCE',source_failure_counts=coverage['failures_by_check'])
            write_json(state_path,state)
            print('SUBSTANTIVE_FAILURE FINAL_PREDICTION_SOURCE',flush=True)
            return 1
        del sources
        while True:
            complete,failed,partial=snapshot(root)
            state.update(last_poll_utc=pd.Timestamp.now(tz='UTC').isoformat(),sealed_batches=len(complete),
                         missing_batch_seals=sorted(expected-set(complete)),partial_batches=partial)
            if failed:
                state.update(status='FAILED_REPLAY',replay_failures=failed)
                write_json(state_path,state)
                print('SUBSTANTIVE_FAILURE REPLAY',json.dumps([x['batch'] for x in failed]),flush=True)
                return 1
            if set(complete)-expected:
                state.update(status='FAILED_UNREGISTERED_BATCH',unexpected_batches=sorted(set(complete)-expected))
                write_json(state_path,state)
                print('SUBSTANTIVE_FAILURE UNREGISTERED_BATCH',flush=True)
                return 1
            if complete != last_complete:
                number=len(state['runs'])+1
                path=output/f'run_{number:04d}_{time.time_ns()}.log'
                started=time.monotonic()
                state.update(status='VERIFYING',current_log=str(path.relative_to(root)),triggered_complete_sha256=complete)
                write_json(state_path,state)
                print('INCREMENTAL_PROOF',number,'sealed',len(complete),flush=True)
                with path.open('w',encoding='utf-8') as log:
                    process=subprocess.run([sys.executable,str(root/'independent_verify.py'),
                        '--year','2025','--year','2026'],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=False)
                report_path=root/'INDEPENDENT_VERIFICATION.json'
                report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
                run={'run':number,'seconds':round(time.monotonic()-started,3),'exit_code':process.returncode,
                     'report_status':report.get('status'),'report_sha256':sha(report_path) if report_path.exists() else None,
                     'log':str(path.relative_to(root)),'triggered_batches':len(complete),
                     'verified_accounts':sum(y.get('verified_accounts',0) for y in report.get('years',{}).values()),
                     'cache_reused_batches':sum(b.get('cache_reused',False) for y in report.get('years',{}).values() for b in y.get('completed_batches',[]))}
                state['runs'].append(run)
                if process.returncode or not report.get('all_completed_batches_pass',False):
                    state.update(status='FAILED_INDEPENDENT_PROOF',last_run=run)
                    # Original failures and their hashes survive subsequent diagnosis.
                    stamp=f'{number:04d}_{time.time_ns()}'
                    for name in ['INDEPENDENT_VERIFICATION.json','INDEPENDENT_VERIFICATION_FAILURES.csv','INDEPENDENT_VERIFICATION_DRIFT.csv']:
                        source=root/name
                        if source.exists():(output/f'failure_{stamp}_{name}').write_bytes(source.read_bytes())
                    write_json(state_path,state)
                    print('SUBSTANTIVE_FAILURE INDEPENDENT_PROOF',number,flush=True)
                    return 1
                state.update(status='WAITING_NEW_COMPLETE',verified_accounts=run['verified_accounts'],last_run=run)
                # Any seals arriving during this proof trigger the next run; the
                # previous seal set, rather than a later snapshot, is remembered.
                last_complete=complete
                print('PROOF_PASS',number,'accounts',run['verified_accounts'],'cached',run['cache_reused_batches'],flush=True)
                if report.get('status')=='PASS_COMPLETE':
                    if (set(report.get('years',{})) != {'2025','2026'} or run['verified_accounts'] != 22176 or
                        any(y.get('verified_accounts') != 11088 for y in report['years'].values())):
                        raise ValueError('a complete report must prove precisely both registered 11088-account windows')
                    current,_,_=snapshot(root)
                    if set(current) != expected:raise ValueError('complete proof is missing canonical batch seals')
                    state.update(status='PASS_COMPLETE',finished_utc=pd.Timestamp.now(tz='UTC').isoformat(),
                                 completed_batches=72,verified_accounts=22176)
                    write_json(state_path,state)
                    print('PASS_COMPLETE 72_BATCHES 22176_ACCOUNTS',flush=True)
                    return 0
            write_json(state_path,state)
            if args.once:return 0
            time.sleep(args.interval)
    except Exception as exc:
        import traceback
        state.update(status='WATCH_EXCEPTION',reason=str(exc),traceback=traceback.format_exc())
        write_json(state_path,state)
        print('SUBSTANTIVE_FAILURE WATCH_EXCEPTION',str(exc),flush=True)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    raise SystemExit(main())
