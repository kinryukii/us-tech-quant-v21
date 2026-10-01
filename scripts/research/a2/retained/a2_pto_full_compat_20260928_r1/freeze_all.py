"""Complete-list preflight and irreversible batch learning freeze; never fit."""
from common import *
from datetime import datetime,timezone

def require(ok,why):
    if not ok:raise RuntimeError(why)

def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))

def verify_freeze():
    record=read('FREEZE.json')
    require(record['status']=='FROZEN_ALL_LEARNING_PRE2026','INVALID_FULL_BATCH_FREEZE')
    require(record['coverage']['member_stages']==93 and record['coverage']['pto_strategies']==11088,'INCOMPLETE_FREEZE_COVERAGE')
    for path,h in record['artifact_sha256'].items():require(sha(ROOT/path)==h,'FROZEN_ARTIFACT_CHANGED:'+path)
    return record

def main():
    require(not (ROOT/'FREEZE.json').exists(),'REFUSE_OVERWRITE_FREEZE')
    require(not (ROOT/'data/test.parquet').exists(),'TEST_DATA_PRECEDES_FULL_FREEZE')
    require(not list((ROOT/'predictions/base/final').glob('*.parquet')),'TEST_INFERENCE_PRECEDES_FULL_FREEZE')
    require(not list((ROOT/'results/2026').glob('batch_*')),'TEST_REPLAY_PRECEDES_FULL_FREEZE')
    streams,paths=registry();registered=read('REGISTRY.json')
    require(len(streams)==75 and len(paths)==11088,'REGISTERED_LIST_SIZE_CHANGED')
    require(registered['strategies']==paths,'REGISTERED_STRATEGIES_CHANGED')
    fits=0
    for stage,cutoff in CUTOFFS.items():
        for member in MEMBERS:
            r=read(f'models/base/{member}/{stage}_RECEIPT.json')
            require(r['status']=='PASS','BASE_MEMBER_NOT_COMPLETED:'+stage+':'+member)
            require(r['features']==FEATURES and r['cutoff_exclusive']==cutoff,'BASE_CONTRACT_MISMATCH')
            require(pd.Timestamp(r['train_label_end_max'])<pd.Timestamp(cutoff),'BASE_LABEL_LEAKAGE')
            require(r['fit_2026_rows']==0 and r['prediction_2026_rows']==0,'BASE_READ_TEST_ROWS')
            require(r['source_sha256']==sha(DATA_SOURCE),'BASE_SOURCE_CHANGED')
            artifact=ROOT/f'models/base/{member}/{stage}.joblib'
            require(sha(artifact)==r['artifact_sha256'],'BASE_ARTIFACT_CHANGED')
            fits+=r['estimator_fit_count']
    require(fits==129,'BASE_ESTIMATOR_FIT_COVERAGE')
    require(read('models/base/VERIFICATION.json')['status']=='PASS','BASE_VERIFICATION_REQUIRED')
    for stage in ['validation','final']:
        r=read(f'models/fusion/{stage}/RECEIPT.json')
        require(r['status']=='COMPLETE' and not r['failures'],'FUSION_INCOMPLETE')
        require(len(r['adapters'])==31 and len(r['fusions'])==44,'FUSION_COVERAGE')
        require(r['reads_2026_rows']==0 and not r['fits_on_in_sample_base_predictions'],'FUSION_TIME_VIOLATION')
        for row in r['adapters']+r['fusions']:
            require(pd.Timestamp(row['label_end_max'])<pd.Timestamp(CUTOFFS[stage]),'FUSION_LABEL_LEAKAGE')
        for row in r['fusions']:
            require(sha(ROOT/f'models/fusion/{stage}/{row["stream"]}.joblib')==row['artifact_sha256'],'FUSION_ARTIFACT_CHANGED')
        risk=read(f'models/risk/{stage}/TRAIN_RECEIPT.json')
        require(risk['status']=='PASS' and risk['risk_names']==RISKS,'RISK_COVERAGE')
        require(risk['test2026_rows_read']==0 and pd.Timestamp(risk['training_label_end_max'])<pd.Timestamp(CUTOFFS[stage]),'RISK_LABEL_LEAKAGE')
        require(pd.Timestamp(risk['risk_history_last'])<pd.Timestamp(CUTOFFS[stage]),'RISK_HISTORY_LEAKAGE')
        for name in RISKS:require((ROOT/f'models/risk/{stage}/{name}.json').exists(),'RISK_INTERFACE_MISSING')
        rl=read(f'models/rl/{stage}/TRAIN_RECEIPT.json')
        require(rl['status']=='PASS' and rl['test2026_rows_read']==0,'RL_TRAINING_INCOMPLETE')
        require(pd.Timestamp(rl['reward_end_last'])<pd.Timestamp(CUTOFFS[stage]),'RL_REWARD_LEAKAGE')
        for name in ['reinforce_updated','reinforce_zero','ppo_updated','ppo_zero']:
            require((ROOT/f'models/rl/{stage}/{name}.pt').exists(),'RL_POLICY_MISSING')
    for name in ['risk','rl']:require(read(f'models/{name}/VERIFICATION.json')['status']=='PASS','VERIFICATION_REQUIRED:'+name)
    require(read('audits/POLICY_FUSION_VERIFICATION.json')['status']=='PASS','POLICY_FUSION_VERIFICATION_REQUIRED')
    require(read('audits/BATCH_ENGINE_CONFORMANCE.json')['status']=='PASS_SYNTHETIC_MARKET_ONLY','ENGINE_VERIFICATION_REQUIRED')
    require(read('audits/DATA_CONTRACT_VERIFICATION.json')['training_2026_rows_read']==0,'DATA_LEARNING_BOUNDARY')
    inputs=read('data/PRE_DATA_RECEIPT.json')
    for path,h in inputs['input_sha256'].items():require(sha(path)==h,'OLD_PRE_SOURCE_CHANGED:'+path)
    for path,h in inputs['output_sha256'].items():require(sha(ROOT/'data'/path)==h,'PRE_INPUT_CHANGED')
    frozen=set()
    for folder in ['models/base','models/fusion','models/risk','models/rl','predictions/base/development','predictions/base/validation','predictions/streams/validation']:
        frozen.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p))
    for path in ['data/pre.parquet','data/pre_prices.parquet','data/pre_calendar.parquet','data/PRE_DATA_RECEIPT.json',
        'common.py','nn_models.py','predictions_train.py','fusion.py','risk_models.py','rl_policy.py','policy.py','batch_engine.py',
        'prepare_data.py','replay_all.py','freeze_all.py','EXPERIMENT_CONTRACT.md','OPTIMIZATION_IMPLEMENTATION.md',
        'USER_CLARIFICATIONS.md','REGISTRY.json','COMPATIBILITY_MATRIX.csv','RL_PROTOCOL.md','RL_REGISTRY.json',
        'audits/DATA_CONTRACT_VERIFICATION.json','audits/BATCH_ENGINE_CONFORMANCE.json','audits/POLICY_FUSION_VERIFICATION.json']:
        require((ROOT/path).exists(),'FROZEN_FILE_MISSING:'+path);frozen.add(ROOT/path)
    record={'status':'FROZEN_ALL_LEARNING_PRE2026','created_utc':datetime.now(timezone.utc).isoformat(),
        'coverage':{'base_members':31,'member_stages':93,'actual_supervised_estimators':fits,'prediction_streams':75,
            'adapter_stages':62,'fusion_stages':88,'risk_specification_stages':24,'rl_policy_stages':8,'pto_strategies':11088},
        'fit_2026_rows':0,'test_2026_inference_before_freeze':0,'test_2026_account_replays_before_freeze':0,
        'all_learning_completed':True,'future_learning_or_candidate_search_authorized':False,
        'previous_2026_exposure':'Preserved: prior batches and qualification diagnostics exposed 2026; this is a frozen retrospective evaluation, never a blind test.',
        'formal_full_pool_status':'BLOCKED_DATA','full_candidate_keys':111868,'unknown_candidate_keys':47271,
        'artifact_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(frozen)}}
    write_json(ROOT/'FREEZE.json',record)
    verify_freeze()
    print(json.dumps({'status':record['status'],'coverage':record['coverage'],'frozen_files':len(frozen)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
