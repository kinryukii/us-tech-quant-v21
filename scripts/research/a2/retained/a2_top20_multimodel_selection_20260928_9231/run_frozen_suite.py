"""Run the four predeclared frozen scenarios, at most two processes at once."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import json,os,subprocess,sys,time

ROOT=Path(__file__).resolve().parent

def run(year,cost):
    log=ROOT/f'evaluation_{year}_{cost}.log'
    out=ROOT/f'evaluation_{year}/cost_{cost}/COMPLETE.json'
    if out.exists():return dict(year=year,cost=cost,status='PRESERVED_EXISTING_COMPLETE')
    env=os.environ.copy();env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',LOKY_MAX_CPU_COUNT='2')
    with log.open('w',encoding='utf-8') as stream:
        code=subprocess.call([sys.executable,'-u',str(ROOT/'evaluate.py'),'--year',str(year),'--cost',str(cost)],
                             cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env=env)
    print(json.dumps(dict(year=year,cost=cost,exit_code=code,log=str(log))),flush=True)
    if code:raise RuntimeError(f'Scenario failed: {year}/{cost}; inspect {log}')
    return dict(year=year,cost=cost,exit_code=code)

def main():
    # Meta fits and review must finish before reading any 2026 numerical price.
    needed=[ROOT/'ensemble_artifacts/final_TRAIN_RECEIPT.json',
            ROOT/'ensemble_artifacts/validation_TRAIN_RECEIPT.json',ROOT/'READY_FOR_EVALUATION.json']
    start=time.monotonic()
    while not all(path.exists() for path in needed):
        if time.monotonic()-start>1800:raise TimeoutError('Frozen training/review not complete after 30 minutes')
        time.sleep(3)
    result=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=[pool.submit(run,y,c) for y,c in [(2025,10),(2026,10),(2026,5),(2026,25)]]
        for task in as_completed(pending):result.append(task.result())
    (ROOT/'SCENARIOS_COMPLETE.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
