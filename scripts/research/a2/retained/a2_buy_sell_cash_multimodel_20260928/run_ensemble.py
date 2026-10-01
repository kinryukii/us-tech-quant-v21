"""Frozen ensemble replays, with H1-only meta weights for H2 validation."""
import argparse,json,time
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from run_experiment import ROOT,LEDGERS,inputs,sha,write,clean,forbid_fit,audit_result,metrics,run_replay
from ensemble_policy import EnsemblePolicy

def main():
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,choices=[2025,2026],required=True)
    p.add_argument('--cost',type=int,choices=[5,10,25],default=10)
    p.add_argument('--half',action='store_true');args=p.parse_args()
    stage='validation' if args.year==2025 else 'final'
    half=args.half and args.year==2025
    names=['ensemble_equal','ensemble_consensus_risk']
    if args.year==2026 or half:names+=['ensemble_stacked']
    label=f'ensemble_{args.year}'+('_H2' if half else '')
    out=ROOT/label/f'cost_{args.cost}'
    if (out/'COMPLETE.json').exists():raise RuntimeError('COMPLETED_RESULT_PRESERVED')
    out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/n for n in ['ENSEMBLE_CONTRACT.md','ensemble_policy.py','ensemble_train.py','run_ensemble.py',
                              'run_experiment.py','adapters.py','engine_v2.py','linear_train.py','neural_train.py','risk_aux.py']]
    for folder in ['linear_artifacts','neural_artifacts','risk_artifacts','ensemble_artifacts']:
        sources += [p for p in (ROOT/folder).rglob('*') if p.suffix in ['.joblib','.pt','.npz','.json']]
    if args.year==2026 or half:assert (ROOT/'ensemble_artifacts/TRAIN_RECEIPT.json').exists()
    guard=forbid_fit()
    panel,prices,calendar,last,asofs,ops,input_paths=inputs(args.year)
    if half:
        calendar=calendar[calendar>='2025-07-01'];panel=panel[panel.signal_date>='2025-07-01']
    first='2025-07-01' if half else f'{args.year}-01-01'
    binding=dict(year=args.year,half=half,cost=args.cost,stage=stage,roster=names,
                 sources={str(p.resolve()):sha(p) for p in sources+input_paths},blind_test=False)
    frozen=out/'FROZEN_BEFORE_REPLAY.json'
    if frozen.exists():assert json.loads(frozen.read_text(encoding='utf-8'))==binding
    else:write(frozen,binding)
    rows=[]
    for name in names:
        folder=out/name
        if (folder/'PATH_COMPLETE.json').exists():
            r=json.loads((folder/'PATH_COMPLETE.json').read_text(encoding='utf-8'))
            assert all(sha(folder/f'{k}.parquet')==v for k,v in r['ledger_sha256'].items())
            rows.append(r['metrics']);continue
        if folder.exists():raise RuntimeError(f'PARTIAL_PATH_REQUIRES_INSPECTION:{folder}')
        folder.mkdir();start=time.monotonic();actor=EnsemblePolicy(name,stage)
        with threadpool_limits(limits=2):
            result=run_replay(prices,calendar,panel,actor,candidate=name,cost_bps=args.cost,
                              capacity_fraction=.01,signal_start=first,signal_end=last,
                              signal_asof=asofs,operational_exits_by_signal=ops)
        for key in LEDGERS:getattr(result,key).to_parquet(folder/f'{key}.parquet',index=False)
        write(folder/'metadata.json',result.metadata)
        audit=audit_result(result,args.cost,panel);row=metrics(result,name,args.year,args.cost)
        row.update(window='H2' if half else 'full_available',seconds=time.monotonic()-start)
        write(folder/'PATH_COMPLETE.json',dict(audit=audit,metrics=row,ledger_sha256={k:sha(folder/f'{k}.parquet') for k in LEDGERS}))
        rows.append(row);pd.DataFrame(rows).to_csv(out/'comparison.csv',index=False)
        print(json.dumps(clean(row)),flush=True)
    assert guard['attempts']==0 and all(sha(p)==h for p,h in binding['sources'].items())
    pd.DataFrame(rows).to_csv(out/'comparison.csv',index=False)
    write(out/'COMPLETE.json',dict(status='PASS',policies=len(rows),fit_attempts=0,sources_unchanged=True,year=args.year,half=half,cost_bps=args.cost))

if __name__=='__main__':main()
