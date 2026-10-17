"""Bounded synthetic-only QA/measurement; never opens research ledgers or models."""
from pathlib import Path
import argparse, ast, ctypes, hashlib, importlib.util, json, sys, time, types
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from scripts.common.storage_paths import resolve_cache_path, resolve_results_path, assert_safe_output_path
TASK = 'A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1'
CACHE = resolve_cache_path('_maintenance', TASK, 'daily_projection_candidate_20261016_r1')
RESULT = resolve_results_path('_maintenance', TASK, 'DAILY_PROJECTION_SYNTHETIC_QA_20261016_R1.json')
READER = resolve_cache_path('_maintenance', 'A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1', 'a_all_quant_metrics.py')
CONSUMER = resolve_cache_path('_maintenance', TASK, 'recover_saved_account_metrics_20261015.py')
OWNER = REPO/'scripts/research/a2/evaluation/stateful_frozen_six_path.py'
CANDIDATE = Path(__file__).with_name('saved_account_daily_projection_candidate.py')

def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def save(p, x, kind='cache'):
    assert_safe_output_path(p, kind=kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8') as f: json.dump(x, f, ensure_ascii=False, allow_nan=False, indent=2)
def need(ok, msg):
    if not ok: raise ValueError(msg)
def function(p, name, ns):
    tree=ast.parse(p.read_text(encoding='utf-8')); nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    need(len(nodes)==1, 'ONE_FROZEN_FUNCTION_REQUIRED')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),'exec'),ns)
    return ns[name]
def setup():
    import numpy as np, pandas as pd, pyarrow.parquet as pq
    spec=importlib.util.spec_from_file_location('_daily_candidate',CANDIDATE);c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
    need(sha(READER)==c.READER_SHA and sha(CONSUMER)==c.CONSUMER_SHA,'SOURCE_CHANGED')
    need(sha(OWNER)=='c315aadb1e67cbf74fadfcc5acd9233e6fbea2b77492b8db8f2f6f3b96d0564e','NAV_OWNER_CHANGED')
    checked={}
    def physical(ref):
        p=Path(ref['path']);s=p.stat();key=(str(p),ref['sha256']);stamp=(s.st_size,s.st_mtime_ns)
        if checked.get(key)!=stamp: need(sha(p)==ref['sha256'],'SYNTHETIC_SHA_CHANGED');checked[key]=stamp
        return p
    ns={'pd':pd,'np':np,'pq':pq,'profile':types.SimpleNamespace(_physical=physical),'need':need}
    base=function(READER,'daily_for',ns);candidate,proof=c.build_consumer_daily_reader(base,CONSUMER)
    metric=function(OWNER,'nav_descriptive_metrics',{'pd':pd,'np':np,'_require':need})
    return np,pd,pq,c,base,candidate,metric,proof

def artifact(p): return {'path':str(p),'sha256':sha(p)}
def info(): return json.loads((CACHE/'fixture.json').read_text(encoding='utf-8'))
def consumer_projection(d,metric):
    return {'stats':metric(d.date,d.TOTAL_ECONOMIC_NAV,3000.),'cash':float(d.cash.iloc[-1]),'receivable':float(d.receivable_value_usd.iloc[-1])}
def identity(x): return hashlib.sha256(json.dumps(x,sort_keys=True,allow_nan=False).encode()).hexdigest()
def peak_working_set():
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_uint32),('PageFaultCount',ctypes.c_uint32)]+[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    k=ctypes.WinDLL('kernel32');k.GetCurrentProcess.restype=ctypes.c_void_p
    ps=ctypes.WinDLL('psapi');p=Counters();p.cb=ctypes.sizeof(p)
    need(ps.GetProcessMemoryInfo(ctypes.c_void_p(k.GetCurrentProcess()),ctypes.byref(p),p.cb),'PEAK_MEMORY_UNAVAILABLE')
    return p.PeakWorkingSetSize

def validate():
    np,pd,pq,c,base,candidate,metric,proof=setup()
    import pyarrow as pa
    assert_safe_output_path(CACHE,kind='cache');CACHE.mkdir(parents=True,exist_ok=True)
    need(not (CACHE/'fixture.json').exists(),'SYNTHETIC_QA_ALREADY_EXISTS_REUSE')
    dates=pd.bdate_range('2001-01-02',periods=253);ids=[f'SYNTH_{i:03d}' for i in range(85)];frames=[]
    for i,cid in enumerate(ids):
        step=np.arange(len(dates),dtype=float);nav=np.full(len(dates),3000.) if i%7==0 else 3000.+step*.17+np.sin(step*.4)*3.
        recv=step*.01
        frames.append(pd.DataFrame({'date':dates,'path_id':cid,'TOTAL_ECONOMIC_NAV':nav,'LIQUID_NAV':nav-recv,'cash':3000.-step*.1,'receivable_value_usd':recv}))
    frame=pd.concat(frames,ignore_index=True).sample(frac=1,random_state=83)
    fixture=CACHE/'synthetic_daily.parquet';pq.write_table(pa.Table.from_pandas(frame,preserve_index=False),fixture)
    w={'start':str(dates[0].date()),'end':str(dates[-1].date()),'execution_sessions':252};a=artifact(fixture)
    digests=[]
    for cid in ids:
        left=base(a,cid,w);right=candidate(a,cid,w)
        pd.testing.assert_frame_equal(left[list(c.COLUMNS)],right,check_exact=True)
        x=consumer_projection(left,metric);y=consumer_projection(right,metric);need(identity(x)==identity(y),'CONSUMER_OUTPUT_DIFF');digests.append(identity(x))
    errors=[];small=frame[frame.path_id.eq(ids[1])].sort_values('date').iloc[:3].copy();sw={'start':str(small.date.iloc[0].date()),'end':str(small.date.iloc[-1].date()),'execution_sessions':2}
    cases=[('missing_'+col,small.drop(columns=[col]),sw,ids[1]) for col in small.columns]
    cases += [('duplicate_date',pd.concat([small,small.iloc[[1]]]),sw,ids[1]),('missing_date',small.iloc[:2],sw,ids[1]),('unknown_identity',small,sw,'ABSENT')]
    for col in ('TOTAL_ECONOMIC_NAV','cash'):
        bad=small.copy();bad.loc[bad.index[0],col]=2999.;cases.append(('bad_initial_'+col,bad,sw,ids[1]))
    for label,data,window,cid in cases:
        p=CACHE/(label+'.parquet');pq.write_table(pa.Table.from_pandas(data,preserve_index=False),p);aa=artifact(p);out=[]
        for f in (base,candidate):
            try:f(aa,cid,window);out.append(('SUCCESS',None))
            except Exception as exc:out.append((type(exc).__name__,str(exc)))
        need(out[0]==out[1] and out[0][0]!='SUCCESS','FAILURE_GATE_DIFF:'+label);errors.append(label)
    metadata={'artifact':a,'window':w,'candidate_ids':ids,'synthetic_only':True,'max_date':w['end'],'rows':len(frame),'columns':list(frame.columns)}
    save(CACHE/'fixture.json',metadata)
    save(CACHE/'validation.json',{'status':'PASS','exact_valid_identities':len(ids),'failure_gate_cases':errors,'consumer_digest':identity(digests),'ast_proof':proof,'new_real_data_read':0,'new_fit_predict_account_replay':0})
    return {'status':'PASS','valid_identities':len(ids),'failure_cases':len(errors),'synthetic_rows':len(frame)}

def bench(mode):
    np,pd,pq,c,base,candidate,metric,proof=setup();meta=info();f=base if mode=='baseline' else candidate;digests=[];sizes=[];started=time.perf_counter()
    for cid in meta['candidate_ids']:
        d=f(meta['artifact'],cid,meta['window']);sizes.append(int(d.memory_usage(index=True,deep=True).sum()));digests.append(identity(consumer_projection(d,metric)))
    elapsed=time.perf_counter()-started
    result={'mode':mode,'synthetic_only':True,'calls':len(sizes),'elapsed_seconds':elapsed,'peak_process_working_set_bytes':peak_working_set(),'max_return_frame_bytes':max(sizes),'sum_return_frame_bytes':sum(sizes),'consumer_digest':identity(digests),'measurement':'One fresh sequential process per mode;85 synthetic reads plus same NAV owner;not a whole-window or production forecast.'}
    save(CACHE/(mode+'_bench.json'),result)
    return result

def summarize():
    checks=json.loads((CACHE/'validation.json').read_text(encoding='utf-8'));b=json.loads((CACHE/'baseline_bench.json').read_text(encoding='utf-8'));c=json.loads((CACHE/'candidate_bench.json').read_text(encoding='utf-8'))
    need(checks['consumer_digest']==b['consumer_digest']==c['consumer_digest'],'BENCH_CONSUMER_OUTPUT_DIFF')
    result={'schema':'DAILY_PROJECTION_SYNTHETIC_OPTIMIZATION_QA_R1','status':'SYNTHETIC_VALIDATED_INACTIVE_CANDIDATE','candidate_ref':artifact(CANDIDATE),'validator_ref':artifact(Path(__file__)),'validation':checks,'baseline':b,'candidate':c,'changes':{'elapsed_seconds':c['elapsed_seconds']-b['elapsed_seconds'],'peak_process_working_set_bytes':c['peak_process_working_set_bytes']-b['peak_process_working_set_bytes'],'max_return_frame_bytes':c['max_return_frame_bytes']-b['max_return_frame_bytes']},'scope':'Synthetic2001 only;no real ledgers/models/prices/outcomes read.85 identities x253 rows, not the real100-window workload.','active_frozen_pipeline_modified':False,'installed':False,'adoption_blocker':'Active consumer, pipeline, aggregate and receipts bind original source hashes. No admitted hot-swap or checkpoint reuse transition for this candidate; cannot inject into current instance.','limitations':['One bounded synthetic measurement per mode;OS/Arrow allocator noise may dominate whole-process peak.','Per-frame column saving does not imply equivalent reduction in account-worker RAM.','No genuine whole-workload speed or peak-memory benefit claimed without measurement.']}
    save(RESULT,result,'results');return {'status':result['status'],'result_ref':artifact(RESULT),'baseline':b,'candidate':c,'changes':result['changes'],'installed':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['validate','bench','summarize']);p.add_argument('--mode',choices=['baseline','candidate']);args=p.parse_args()
    out=validate() if args.command=='validate' else (bench(args.mode) if args.command=='bench' and args.mode else summarize())
    print(json.dumps(out,ensure_ascii=False,allow_nan=False))
