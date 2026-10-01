"""Bind reused models and supplementary evidence before 2026 replay."""
from pathlib import Path
import json,hashlib
import pandas as pd
ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'a2_latest_effective_joint_20260927'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    fit=read(OLD/'joint_linear_tree_artifacts/FIT_RECEIPT.json');rows=[]
    for stage in ['validation','final']:
        for name in ['ridge','elastic_net','logistic','hgb','q10','q50','q90']:
            record=next(r for r in fit['fits'] if r['stage']==stage and r['name']==name)
            repair=[r for r in fit.get('numerical_repairs',[]) if r['stage']==stage and r['name']==name and r.get('used_for_policy')]
            record=repair[-1] if repair else record;p=Path(record['artifact'])
            assert sha(p)==record['artifact_sha256']
            rows.append(dict(stage=stage,name=name,path=str(p),sha256=sha(p),fit_in_this_version=False))
    prior=read(OLD/'evaluation_2026/cost_10/FROZEN_BEFORE_SCORING.json')
    inherited={str(OLD/p):h for p,h in prior['source_hashes'].items()}
    assert all(sha(Path(p))==h for p,h in inherited.items())
    reuse=dict(status='PASS',used_supervised_models=rows,all_old_frozen_source_sha256=inherited,
        reuse_reason='Single-step counterfactual features, sampled dates, states and reward unchanged; residual-capacity allocator is an explicit new execution policy. Neural holding trajectories changed, requiring fresh fits.',
        fresh_neural_receipt=str(ROOT/'neural_artifacts/TRAIN_RECEIPT.json'),
        supervised_fit_in_this_version=False,risk_and_auxiliary_fit_in_this_version=False)
    write(ROOT/'MODEL_REUSE.json',reuse)
    extra=ROOT/'ADDITIONAL_CONSUMED_INPUT_SEAL.json'
    if extra.exists():raise RuntimeError('Supplementary seal already exists; do not silently rebind')
    ops=ROOT/'data/operational_exit_evidence.csv'
    assert ops.exists(),'Freeze operational evidence before 2026 run'
    paths=[ops,ROOT/'data/DATA_RECEIPT.json',ROOT/'MODEL_REUSE.json',
           ROOT/'evidence/events/event_qualification.parquet',ROOT/'evidence/events/security_day_qualification.parquet',
           ROOT/'evidence/identity/identity_lifecycle_qualification.json']
    hashes={str(p):sha(p) for p in paths}
    hashes.update({p:h for p,h in inherited.items() if str(OLD/'models') in p})
    write(extra,dict(status='FROZEN_BEFORE_2026_REPLAY',created_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        source_sha256=hashes,scope='Operational CSV, qualification data and all old baseline model sources supplement each run seal',
        qualification='2025 baseline sources were already bound by the old frozen seal and preservation check before validation; supplementary ops seal precedes all 2026 replays.'))
    print(json.dumps(dict(supervised_models=len(rows),inherited_sources=len(inherited),supplementary_sources=len(hashes))))


if __name__=='__main__':main()
