"""Fixed-slot coordinator; all numeric authority remains with the native adapter."""
from pathlib import Path
import argparse,json,time
from scripts.research.a2.training import consensus_predictors as owner
from scripts.research.a2.data.consensus_training_inputs import ConsensusInputs
from scripts.storage.storage_r2a import write_json_atomic

def run_plan(run):
    run=Path(run).resolve()
    f=json.loads((run/'CONSENSUS_PREDICTOR_FREEZE.json').read_text(encoding='utf-8'))
    assert f['status']=='AUTHORIZED_PRE2026_TRAINING_ONLY'
    reader=ConsensusInputs(run,run/'derived/consensus100_daily.parquet')
    progress=run/'logs/PREDICTOR_PROGRESS.json';started=time.time();rows=[]
    for i,slot in enumerate(f['ordered_slots']):
        model,year,h=slot['model_id'],slot['year'],slot['horizon']
        print(json.dumps(dict(event='START',slot=i+1,total=len(f['ordered_slots']),**slot)),flush=True)
        if year<2026:r=owner.predict_one(run,model,year,h,reader=reader)
        else:
            fitted=owner.fit_one(run,model,year,h,reader=reader)
            r=fitted.receipt if isinstance(fitted,owner.ConsensusPredictor) else fitted
        row={**slot,'status':r['status'],'receipt_path':r.get('receipt_path',r.get('fit_receipt_path')),
             'failure':r.get('failure'),'elapsed_total_seconds':round(time.time()-started,1)}
        rows.append(row)
        write_json_atomic(progress,dict(status='RUNNING',slots_complete=len(rows),total_slots=len(f['ordered_slots']),
            rows=rows,failed=sum(x['status'] not in ('PUBLISHED','TRAINED') for x in rows),test_2026_content_read=False))
        print(json.dumps(dict(event='COMPLETE',slot=i+1,**row)),flush=True)
    write_json_atomic(progress,dict(status='COMPLETED_ALL_FIXED_SLOTS',slots_complete=len(rows),total_slots=len(rows),rows=rows,
        failed=sum(x['status'] not in ('PUBLISHED','TRAINED') for x in rows),test_2026_content_read=False))
    print(json.dumps(dict(event='PLAN_COMPLETE',slots=len(rows),failed=sum(x['status'] not in ('PUBLISHED','TRAINED') for x in rows))),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);a=p.parse_args();run_plan(a.run)
if __name__=='__main__':main()
