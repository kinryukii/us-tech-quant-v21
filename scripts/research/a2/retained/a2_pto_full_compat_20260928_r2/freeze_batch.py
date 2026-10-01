"""Write-once whole-batch seal before any new 2026 numeric inference/replay."""
import argparse
from datetime import datetime,timezone
from shared import *

CORE_CODE=['shared.py','predictors.py','runtime_bootstrap.py','train_predictors.py',
    'calibration_fusion.py','train_cooperation.py','risk_models.py','rl_control.py',
    'fast_account.py','optimization.py','market_runtime.py','evaluation_predictions.py',
    'portfolio_policy.py','run_suite.py','cached_replay.py','fast_numeric.py','fast_cvar_numeric.py',
    'fast_replay.py','freeze_batch.py','analyze_results.py','verify_ledgers.py']

def mature(value,cutoff,description):
    if pd.Timestamp(value)>=pd.Timestamp(cutoff):raise RuntimeError('IMMATURE_LEARNING:'+description)

def check_prerequisites():
    lock=read_json(ROOT/'DESIGN_LOCK.json')
    if sha(ROOT/'EXPERIMENT_CONTRACT.md')!=lock['contract_sha256']:raise RuntimeError('DESIGN_CONTRACT_CHANGED')
    roster=pd.read_csv(ROOT/'PREDECLARED_PATHS.csv')
    if not roster.equals(paths()):raise RuntimeError('DECLARED_ROSTER_CHANGED')
    summaries=[];physical=[]
    for stage,cutoff in STAGES.items():
        state=read_json(ROOT/'models'/stage/'FIT_STATUS.json')
        if not state.get('complete') or len(state['fits'])!=len(PREDICTORS):raise RuntimeError('BASE_FITS_INCOMPLETE:'+stage)
        if state['fit_2026_rows'] or state['test_2026_rows_read']:raise RuntimeError('BASE_FIT_READ_TEST')
        mature(state['label_end_max'],cutoff,stage)
        if state['feature_order']!=FEATURES or sha(state['sample_keys'])!=state['sample_keys_sha256']:raise RuntimeError('BASE_INPUT_CONTRACT_CHANGED')
        source_files={'pre_panel':PRE_PANEL,'predictors':ROOT/'predictors.py','trainer':ROOT/'train_predictors.py',
            'bootstrap':ROOT/'runtime_bootstrap.py','shared':ROOT/'shared.py','contract':ROOT/'EXPERIMENT_CONTRACT.md'}
        for name,p in source_files.items():
            if sha(p)!=state['source_hashes'][name]:raise RuntimeError('BASE_TRAIN_SOURCE_CHANGED:'+name)
        for record in state['fits']:
            if record['status'] not in ['TRAINED','FAILED']:raise RuntimeError('UNRESOLVED_BASE_FIT')
            if record['status']=='TRAINED' and sha(record['artifact'])!=record['artifact_sha256']:raise RuntimeError('BASE_ARTIFACT_CHANGED')
            physical.extend(record['physical_fit_records'])
        summaries.append({'stage':stage,'logical_fits':len(state['fits']),'label_end_max':state['label_end_max']})
    if len(physical)!=172:raise RuntimeError('ALL_172_PHYSICAL_FITS_REQUIRED')
    counts=read_json(ROOT/'models/FINAL_TRAINING_COUNTS.json')
    if counts.get('physical_attempts',counts.get('physical_completed',counts.get('attempted_physical_fits')))!=172:
        raise RuntimeError('INDEPENDENT_PHYSICAL_COUNT_REQUIRED')
    if counts['physical_successful']+counts['physical_failed']!=172 or counts['fit_2026_rows'] or counts['read_2026_rows'] or counts['generated_2026_predictions']:
        raise RuntimeError('PHYSICAL_COUNT_OR_LEAKAGE_AUDIT_FAILED')
    for name in ['physical','logical']:
        if sha(counts[name+'_coverage_file'])!=counts[name+'_coverage_sha256']:raise RuntimeError('FIT_COVERAGE_CHANGED')
    for period,cutoff in [('2024','2024-01-01'),('2025','2025-01-01'),('final','2026-01-01')]:
        status=read_json(ROOT/'models'/f'calibration_{period}'/'STATUS.json')
        if len(status['records'])!=31 or not status.get('status','').startswith('COMPLETE'):raise RuntimeError('CALIBRATION_INCOMPLETE')
        binding=status['binding']
        for key,name in [('calibration_code','calibration_fusion.py'),('trainer','train_cooperation.py'),('shared','shared.py')]:
            if binding[key]!=sha(ROOT/name):raise RuntimeError('CALIBRATION_SOURCE_CHANGED')
        for p,h in binding['inputs'].items():
            if sha(p)!=h:raise RuntimeError('CALIBRATION_TRAIN_INPUT_CHANGED')
        for record in status['records']:
            if record['status']=='TRAINED':
                mature(record['receipt']['max_label_end'],cutoff,'calibration '+period)
                if record['receipt']['fit_2026_rows']:raise RuntimeError('CALIBRATION_FIT_USED_2026')
                if sha(record['artifact'])!=record['artifact_sha256']:raise RuntimeError('CALIBRATION_ARTIFACT_CHANGED')
    for stage in ['validation','final']:
        status=read_json(ROOT/'models'/f'fusion_{stage}'/'STATUS.json')
        if len(status['records'])!=121 or not status.get('status','').startswith('COMPLETE'):raise RuntimeError('FUSIONS_INCOMPLETE')
        binding=status['binding']
        for key,name in [('code','calibration_fusion.py'),('trainer','train_cooperation.py'),('shared','shared.py')]:
            if binding[key]!=sha(ROOT/name):raise RuntimeError('FUSION_SOURCE_CHANGED')
        if binding['features']!=sha(PRE_PANEL):raise RuntimeError('FUSION_FEATURE_INPUT_CHANGED')
        for year,h in binding['inputs'].items():
            if sha(ROOT/'predictions'/f'mu_oof_{year}.parquet')!=h:raise RuntimeError('FUSION_TRAIN_INPUT_CHANGED')
        for record in status['records']:
            if record['status']=='TRAINED':
                receipt=record['receipt']
                mature(receipt['max_label_end'],STAGES[stage],'fusion '+stage)
                if receipt['fit_2026_rows'] or sha(record['artifact'])!=record['artifact_sha256']:raise RuntimeError('FUSION_CHANGED_OR_LEAKED')
        risk=read_json(ROOT/'models'/f'risk_{stage}_receipt.json')
        mature(risk['max_label_end'],STAGES[stage],'risk '+stage)
        if risk['fit_2026_rows'] or sha(ROOT/'models'/f'risk_{stage}.joblib')!=risk['artifact_sha256']:raise RuntimeError('RISK_CHANGED_OR_LEAKED')
        adapter=read_json(ROOT/'models'/f'risk_scenario_adapter_{stage}.json')
        if adapter['fit_2026_rows'] or sha(ROOT/'models'/f'risk_scenario_adapter_{stage}.npz')!=adapter['adapter_sha256']:raise RuntimeError('SCENARIO_ADAPTER_CHANGED')
        mature(adapter['mature_labels_max'],STAGES[stage],'scenario adapter labels')
        for date in adapter['historical_scenario_dates']:mature(date,STAGES[stage],'scenario adapter date')
    for period in ['2023H2','2024','2025']:
        receipt=read_json(ROOT/'predictions'/f'raw_oof_{period}_receipt.json')
        if receipt['fit_2026_rows'] or receipt['read_2026_rows'] or sha(receipt['file'])!=receipt['sha256']:raise RuntimeError('OOF_CHANGED_OR_LEAKED')
    for period in ['2024','2025']:
        receipt=read_json(ROOT/'predictions'/f'mu_oof_{period}.json')
        if receipt['fit_2026_rows'] or sha(ROOT/'predictions'/f'mu_oof_{period}.parquet')!=receipt['file_sha256']:raise RuntimeError('MU_OOF_CHANGED')
    rl=read_json(ROOT/'models/RL_TRAIN_RECEIPT.json')
    if rl['status']!='COMPLETE' or rl['actual_fit_count']!=4 or rl['zero_control_count']!=4 or rl['fit_2026_rows'] or rl['numeric_2026_prices_read']:raise RuntimeError('RL_INCOMPLETE_OR_LEAKED')
    if sha(ROOT/'fast_account.py')!=rl['common_runtime_source_sha256']:raise RuntimeError('RL_CURRENT_ENVIRONMENT_COMPATIBILITY_REQUIRED')
    for fit in rl['fits']:
        mature(fit['reward_end_max'],STAGES[fit['stage']],'RL reward')
        for field in ['normalization_signal_max','normalization_label_end_max','price_max']:
            mature(fit[field],STAGES[fit['stage']],'RL '+field)
        for p,h in [('path','sha256'),('zero_path','zero_sha256')]:
            if sha(fit[p])!=fit[h]:raise RuntimeError('RL_ACTOR_CHANGED')
    for name in CORE_CODE:
        if not (ROOT/name).exists():raise RuntimeError('CORE_SOURCE_MISSING:'+name)
    return {'base_stages':summaries,'physical_attempts':len(physical),'logical_outputs':31,
        'forecast_streams':152,'risk_profiles':13,'optimizers':4,'declared_paths':8194,
        'calibration_fits_attempted':93,'fusion_fits_attempted':242,'rl_fits':4,'rl_zero_controls':4}

def binding_files():
    files={ROOT/name for name in CORE_CODE}
    files.update(ROOT/name for name in ['EXPERIMENT_CONTRACT.md','DESIGN_LOCK.json','PREDECLARED_PATHS.csv','input_paths.json',
        'COMPATIBILITY_MATRIX.csv','RISK_OPTIMIZER_COMPATIBILITY.csv'])
    files.update((ROOT/'data').glob('*'))
    for p in (ROOT/'models').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and 'rl_draft_attempt_20260928_01' not in p.parts:
            files.add(p)
    for pattern in ['raw_oof*','mu_oof*']:files.update((ROOT/'predictions').glob(pattern))
    files.update(p for p in (ROOT/'audits').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return sorted(p for p in files if p.is_file())

def freeze():
    marker=ROOT/'FROZEN_BEFORE_2026.json'
    if marker.exists():return verify_freeze()
    if (ROOT/'predictions/evaluation_2026').exists() or (ROOT/'results/evaluation_2026').exists():raise RuntimeError('TEST_ALREADY_STARTED_WITHOUT_SEAL')
    prerequisites=check_prerequisites()
    paths_to_bind=binding_files();bindings={str(p.relative_to(ROOT)):sha(p) for p in paths_to_bind}
    receipt={'status':'ENTIRE_BATCH_FROZEN','created_utc':datetime.now(timezone.utc).isoformat(),
        'prerequisites':prerequisites,'bindings':bindings,'fit_2026_rows':0,'new_numeric_2026_inference_started':False,
        'blind_test':False,'prior_exposure_preserved':True,'formal_full_pool_status':'BLOCKED_DATA',
        'no_post_test_tuning':True,'all_failures_preserved':True,'candidate_search_closed':True}
    # Exclusive creation prevents replacing an earlier whole-batch seal.
    import json
    with marker.open('x',encoding='utf-8') as f:json.dump(receipt,f,ensure_ascii=False,indent=2,allow_nan=False)
    return verify_freeze()

def verify_freeze():
    marker=ROOT/'FROZEN_BEFORE_2026.json'
    if not marker.exists():raise RuntimeError('ENTIRE_BATCH_FREEZE_REQUIRED')
    receipt=read_json(marker);mismatches=[]
    for name,expected in receipt['bindings'].items():
        p=ROOT/name
        if not p.exists() or sha(p)!=expected:mismatches.append(name)
    if mismatches:raise RuntimeError('FROZEN_BATCH_CHANGED:'+','.join(mismatches))
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    result=verify_freeze() if args.verify else freeze()
    print(result['status'],len(result['bindings']),'bound files',flush=True)
