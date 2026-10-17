"""Original-owner metadata ETA at one natural checkpoint; no scientific inputs.

The external d266c3 progress counter remains unchanged. This one-shot command
reads only the frozen planned calendar and checkpoint filesystem metadata.
"""
from pathlib import Path
import argparse, datetime as dt, hashlib, json, os, tempfile, time
from scripts.common.storage_paths import resolve_cache_path, resolve_results_path, assert_safe_output_path
TASK='A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1'
ORIGINAL='A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1'
CALENDAR_SHA='903e6b72d8c1c55f7214b1761f8a6ee607faca5caa5e9d67210d94eb5ba60f3a'
ROOT=Path('D:/us-tech-quant-backtests')/ORIGINAL/'20261009T040010+0000_ebc89ace/derived/consensus_all_a/sealed153_account_recovery_20261015/accounts'
UTC=dt.timezone.utc

def need(x,s):
    if not x:raise ValueError(s)
def at(x):return dt.datetime.fromtimestamp(x,UTC).isoformat().replace('+00:00','Z')
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def put(p,obj,kind,exclusive=False):
    assert_safe_output_path(p,kind=kind);p.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(obj,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    if exclusive:
        with p.open('x',encoding='utf-8') as f:f.write(content)
    else:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=p.parent,prefix='owner-eta-',suffix='.tmp',delete=False) as f:f.write(content);tmp=f.name
        os.replace(tmp,p)

def calculate(windows,completed,observed):
    n=len(completed);ids=[f'RANDOM_{i:03d}' for i in range(1,101)]
    need(set(windows)==set(ids) and n>=3 and sorted(completed)==ids[:n],'CALENDAR_OR_CHECKPOINT_SCOPE')
    intervals=[]
    for i in range(3,n+1):
        if i in (31,40):continue
        wid=ids[i-1];seconds=completed[wid]-completed[ids[i-2]];sessions=windows[wid]['execution_sessions']
        need(seconds>0 and sessions>0,'NORMAL_INTERVAL_REQUIRED')
        intervals.append({'window_id':wid,'seconds':seconds,'planned_execution_sessions':sessions})
    need(bool(intervals),'NORMAL_INTERVAL_REQUIRED')
    rate=lambda rows:sum(x['seconds'] for x in rows)/sum(x['planned_execution_sessions'] for x in rows)
    recent=intervals[-5:];recent_rate=rate(recent);all_rate=rate(intervals)
    remaining=sum(windows[wid]['execution_sessions'] for wid in ids[n:]);anchor=completed[ids[n-1]]
    low=anchor+remaining*min(recent_rate,all_rate)*.85;high=anchor+remaining*max(recent_rate,all_rate)*1.25
    return {'schema':'EXECUTION_ONLY_ETA_R1','observed_utc':at(observed),'anchor_utc':at(anchor),
      'account_finish_earliest_utc':at(low),'account_finish_latest_utc':at(high),
      'whole_finish_earliest_utc':at(low+3600),'whole_finish_latest_utc':at(high+7200),
      'basis':'ORIGINAL_OWNER_FROZEN_REMAINING_WORK'}, {
      'complete_windows':n,'remaining_windows':100-n,'recent_eligible_intervals':recent,
      'recent5_seconds_per_planned_session':recent_rate,'all_eligible_seconds_per_planned_session':all_rate,
      'remaining_planned_execution_sessions':remaining,'account_finish_recent_speed_utc':at(anchor+remaining*recent_rate),
      'excluded_intervals':['RANDOM001 pilot','RANDOM002 startup','RANDOM031 interrupted','RANDOM040 interrupted'],
      'report_and_original_acceptance_hours':[1,2],'past_recovery_costs_already_in_anchor':True,
      'recovery_cost_added_again':False,'planning_range_not_confidence_or_guarantee':True}

def self_test():
    windows={f'RANDOM_{i:03d}':{'execution_sessions':10} for i in range(1,101)}
    base=dt.datetime(2001,1,1,tzinfo=UTC).timestamp()
    times={f'RANDOM_{i:03d}':base+10*i+(120 if i>=31 else 0)+(240 if i>=40 else 0) for i in range(1,56)}
    out,d=calculate(windows,times,base+1000)
    need(d['remaining_windows']==45 and d['remaining_planned_execution_sessions']==450,'SYNTHETIC_REMAINING')
    need(d['recent5_seconds_per_planned_session']==d['all_eligible_seconds_per_planned_session']==1,'SYNTHETIC_INTERRUPTION_EXCLUSION')
    need(out['anchor_utc']==at(times['RANDOM_055']),'SYNTHETIC_ANCHOR')
    need(out['account_finish_earliest_utc']==at(times['RANDOM_055']+450*.85),'SYNTHETIC_LOWER')
    need(out['whole_finish_latest_utc']==at(times['RANDOM_055']+450*1.25+7200),'SYNTHETIC_WHOLE')
    return {'synthetic_arithmetic_checks':5,'status':'PASS','science_or_benchmark_runs':0}

def run(target):
    need(target==55,'ONLY_REQUESTED_RANDOM055_REFRESH')
    cache=resolve_cache_path('_maintenance',TASK);results=resolve_results_path('_maintenance',TASK)
    status_path=cache/'RANDOM055_ETA_REFRESH_STATUS_20261016_R1.json'
    status={'schema':'ONE_SHOT_EXECUTION_ETA_REFRESH_R1','status':'WAITING_NATURAL_CHECKPOINT','pid':os.getpid(),
      'started_utc':at(time.time()),'target_window':'RANDOM_055','new_scientific_runs':0,'job_unchanged':True,'source_ref':ref(Path(__file__))}
    put(status_path,status,'cache',True)
    try:
        deadline=time.monotonic()+2*3600;target_path=ROOT/'RANDOM_055/WINDOW_COMPLETION.json'
        while not target_path.is_file():
            need(time.monotonic()<deadline,'NATURAL_CHECKPOINT_WAIT_TIMEOUT')
            time.sleep(30)
        time.sleep(1)
        calendar=resolve_results_path('_maintenance',ORIGINAL,'RANDOM_WINDOWS.json');content=calendar.read_bytes()
        need(hashlib.sha256(content).hexdigest()==CALENDAR_SHA,'FROZEN_CALENDAR_CHANGED')
        windows={w['window_id']:w for w in json.loads(content.decode('utf-8-sig'))['windows'] if w['window_id'].startswith('RANDOM_')}
        completed={wid:(ROOT/wid/'WINDOW_COMPLETION.json').stat().st_mtime for wid in windows if (ROOT/wid/'WINDOW_COMPLETION.json').is_file()}
        projection,details=calculate(windows,completed,time.time())
        artifact=results/'POST_LOAD_RANDOM055_ENGINEERING_ETA_20261016_R1.json'
        evidence={'schema':'ORIGINAL_OWNER_NATURAL055_EXECUTION_ETA_R1',**projection,'details':details,
          'calendar_ref':{'path':str(calendar),'sha256':CALENDAR_SHA},'generator_ref':ref(Path(__file__)),
          'load_context':'Requested after B1 restart2026-10-16T06:42:43Z;estimates use actual normal checkpoint timing;no new resource or performance tests.',
          'old_exit_cause':'UNKNOWN','optimization_candidate_still_not_adopted':True,'new_scientific_values_read':0,'worker_paused_or_restarted':False}
        put(artifact,evidence,'results',True);projection['engineering_ref']=ref(artifact);status['engineering_ref']=ref(artifact)
        pure=resolve_cache_path('_maintenance','resource_coordination_20261015','A_PURE_EXECUTION_ETA_R1.json');put(pure,projection,'cache')
        status.update(status='GENERATED',finished_utc=at(time.time()),engineering_ref=ref(artifact),pure_projection_ref=ref(pure),rolling_record='NOT_READ_OR_WRITTEN_BY_METADATA_WAITER')
        put(status_path,status,'cache');print(json.dumps(status,ensure_ascii=False),flush=True)
    except Exception as exc:
        status.update(status='FAILED_CHECK_ENGINEERING_OUTPUT_REFS',error_class=type(exc).__name__,error_code=str(exc),finished_utc=at(time.time()))
        put(status_path,status,'cache');raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--after-window',type=int);a=p.parse_args()
    if a.self_test:print(json.dumps(self_test()))
    else:run(a.after_window)
