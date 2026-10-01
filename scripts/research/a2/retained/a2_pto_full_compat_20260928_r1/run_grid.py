"""Dispatch the unchanged registered replay tasks, with resumable coverage."""
from common import *
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from replay_all import initializer,group_task
from freeze_all import verify_freeze

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=[2025,2026],required=True)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--exclude-batch',type=int,action='append',default=[])
    a=p.parse_args()
    if a.year==2026:verify_freeze()
    paths=json.loads((ROOT/'REGISTRY.json').read_text(encoding='utf-8'))['strategies'];tasks=[];number=0
    for risk in RISKS:
        for opt in OPTIMIZERS:
            task=(a.year,number,[x for x in paths if x['risk']==risk and x['optimizer']==opt]);number+=1
            if task[1] in a.exclude_batch:continue
            done=ROOT/f'results/{a.year}/batch_{task[1]:03d}/COMPLETE.json'
            if not done.exists():tasks.append(task)
    def snapshot():
        records=[]
        for i in range(36):
            folder=ROOT/f'results/{a.year}/batch_{i:03d}'
            for name in ['COMPLETE.json','FAILED.json']:
                if (folder/name).exists():records.append(json.loads((folder/name).read_text(encoding='utf-8')));break
        write_json(ROOT/f'results/{a.year}/PROGRESS.json',{'completed_batches':records,'registered_accounts':11088})
        if len(records)==36:write_json(ROOT/f'results/{a.year}/ALL_BATCHES.json',{'records':records,'registered_accounts':11088})
    print('DISPATCH',a.year,'pending_batches',len(tasks),'excluded_in_progress',a.exclude_batch,flush=True)
    with ProcessPoolExecutor(max_workers=a.workers,initializer=initializer,initargs=(a.year,)) as pool:
        futures=[pool.submit(group_task,t) for t in tasks]
        for future in as_completed(futures):
            record=future.result();print(record['year'],record['batch'],record['status'],round(record['seconds'],1),flush=True);snapshot()
    snapshot()
    if a.year==2026:verify_freeze()

if __name__=='__main__':main()
