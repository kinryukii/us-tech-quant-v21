"""Bind every learned artifact before the first 2026 forecast or account replay."""
from common import *
from datetime import datetime,timezone
import argparse
import pandas as pd

RUNTIME_FILES=['common.py','contract.json','DESIGN_LOCK.json','freeze_batch.py','data_contract.py','POOL_POLICY_CLARIFICATION.json',
    'models_native.py','train_models.py','predict_saved.py','fusion_models.py','train_fusion.py','risk_models.py','optimizers.py',
    'accelerated_optimizer.py','accelerated_solver.py','cached_risk_inference.py','engine_v2.py','engine_cached.py','engine_fast_inputs.py','run_replays.py',
    'rl_controls.py','run_control_replays.py','forecast_metrics.py','PREDICTION_LINK_CONTRACT.json','EQUAL_TOP20_HELD_ONLY_CLARIFICATION.json',
    'MODULE_INTERFACE_CONTRACT.json','FORECAST_ROSTER.csv','COMBINATION_COVERAGE.csv','INPUT_OUTPUT_COMPATIBILITY.csv']

def validate_global_freeze():
    freeze=read(ROOT/'GLOBAL_FREEZE.json')
    assert freeze['status']=='FROZEN' and freeze['fit_2026_rows']==0
    bad=[path for path,h in freeze['artifact_sha256'].items() if not (ROOT/path).is_file() or sha(ROOT/path)!=h]
    if bad:raise RuntimeError('GLOBAL_FROZEN_ARTIFACT_CHANGED:'+str(bad[:12]))
    assert sha(ROOT/'contract.json')==read(ROOT/'DESIGN_LOCK.json')['contract_sha256']
    return freeze

def main():
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');a=p.parse_args()
    if a.verify:
        f=validate_global_freeze();print(json.dumps({'status':'FROZEN_HASHES_VERIFIED','files':len(f['artifact_sha256'])}));return
    if (ROOT/'GLOBAL_FREEZE.json').exists():raise RuntimeError('BATCH_ALREADY_FROZEN')
    for stage in ['early','validation','final']:
        for model in PROVIDERS:
            path=ROOT/'models'/stage/(model+'.joblib');assert path.is_file(),path
            receipt=read(path.with_name(model+'_FIT_RECEIPT.json'))
            assert receipt['status']=='PASS',(stage,model,receipt['status'])
            assert receipt['artifact_sha256']==sha(path),(stage,model,'artifact_hash')
            assert receipt['train_label_end_max']<{'early':'2024-01-01','validation':'2025-01-01','final':'2026-01-01'}[stage]
    for stage in ['validation','final']:
        for group in COALITIONS:
            for method in FUSIONS:
                path=ROOT/'fusion_artifacts'/stage/(group+'__'+method+'.joblib');assert path.is_file()
                receipt=read(path.with_suffix('.json'))
                assert receipt['artifact_sha256']==sha(path) and receipt['input_sha256']==sha(ROOT/receipt['input_path'])
                assert receipt['label_end_max']<{'validation':'2025-01-01','final':'2026-01-01'}[stage]
        assert read(ROOT/'risk_artifacts'/stage/'TRAIN_RECEIPT.json')['fit_2026_rows']==0
        for method in ['reinforce','ppo']:
            receipt=read(ROOT/'rl_artifacts'/(stage+'_'+method)/'TRAIN_RECEIPT.json')
            assert receipt['status']=='COMPLETE_FIXED_BUDGET'
    for f in RUNTIME_FILES:assert (ROOT/f).is_file(),f
    objects=[ROOT/f for f in RUNTIME_FILES]
    for subdir in ['models','fusion_artifacts','risk_artifacts','rl_artifacts','input']:
        objects.extend(p for p in (ROOT/subdir).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for stage in ['early','validation']:
        objects.extend((ROOT/'predictions/native'/stage).glob('*.parquet'))
    objects.extend((ROOT/'predictions').glob('FUSION_OOF*.parquet'))
    objects.extend((ROOT/'predictions/forecasts/2025').glob('*.parquet'))
    hashes={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(set(objects))}
    write(ROOT/'GLOBAL_FREEZE.json',dict(status='FROZEN',created_utc=datetime.now(timezone.utc).isoformat(),
       experiment='A2_PREDICT_THEN_OPTIMIZE_R1',contract_sha256=sha(ROOT/'contract.json'),
       artifact_sha256=hashes,fit_2026_rows=0,test2026_results_observed_in_this_batch=0,
       formal_full_pool_status=read(ROOT/'INPUT_AUDIT.json')['evaluation_2026']['full_original_pool_test_status'],
       previous_exposure_retained=True,candidate_change_allowed=False,all_31_native_stages_and_all_fusions_risks_rl_present=True))
    print(json.dumps({'status':'FROZEN','files':len(hashes)}))

if __name__=='__main__':main()
