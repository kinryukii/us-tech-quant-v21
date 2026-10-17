"""Sequential adapter orchestration; no estimator or scientific-rule copies."""
from pathlib import Path
import argparse,json,time
import joblib
from scripts.common.storage_paths import resolve,assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import consensus_predictors as predictors,consensus_fusion as fusion,consensus_auxiliary as auxiliary
from scripts.research.a2.data.consensus_training_inputs import ConsensusInputs

values=predictors.values
require=predictors.require
COMPONENTS=['kmeans5','gmm5','isolation_forest100','pca5','fa5']
TRAIN_PARTITION='FINAL_PRE2026_FOLD_TRAIN_ONLY_EXCLUDING_CAL60'


def emit(event,**payload):print(json.dumps(dict(event=event,**payload),allow_nan=False),flush=True)


def ready(run):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    require(not (run/'CONSENSUS_FIT.lock').exists(),'UPSTREAM_OR_OTHER_FIT_ACTIVE_NO_LOCK_COMPETITION')
    data_run=fusion.reader_run(run)
    progress=fusion.metadata(data_run/'logs/PREDICTOR_PROGRESS.json')
    require(progress['status']=='COMPLETED_ALL_FIXED_SLOTS' and progress['slots_complete']==progress['total_slots']==228,'ALL_228_PREDICTOR_SLOTS_MUST_FINISH_FIRST')
    return run


def expected_fusion_slots(run):
    return 4 if Path(run).resolve()==fusion.CONTINUATION_RUN else 84


def auxiliary_source_pins():
    return dict(runner=dict(path=str(Path(__file__)),sha256=values.sha(__file__)),
        auxiliary=dict(path=str(Path(auxiliary.__file__)),sha256=values.sha(auxiliary.__file__)),predictor_sources=predictors.source_pins())


def auxiliary_freeze_template(run):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    pf=run/'CONSENSUS_PREDICTOR_FREEZE.json'
    return dict(schema='CONSENSUS_AUXILIARY_FREEZE_R1',task_id=predictors.TASK,status='PROPOSED',source_pins=auxiliary_source_pins(),
        predictor_freeze_ref=dict(path=str(pf),sha256=values.sha(pf)),year_key=2026,final_cutoff_training_only_authorized=False,
        feature_order=list(predictors.FEATURES),components=COMPONENTS,training_partition=TRAIN_PARTITION,seed=auxiliary.SEED,
        max_fit_units=10000,fit_timeout_seconds=1800,source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',strict_PIT_certified=False,
        diagnostics_only=True,worker_thread_limit=1,rl_environment='NOT_BOUND_NOT_TESTABLE')


def auxiliary_contract(run):
    run=Path(run).resolve();path=run/'CONSENSUS_AUXILIARY_FREEZE.json';f=fusion.metadata(path)
    expected=auxiliary_freeze_template(run);expected.update(status='AUTHORIZED_PRE2026_TRAINING_ONLY',final_cutoff_training_only_authorized=True)
    require(f==expected,'EXACT_AUTHORIZED_AUXILIARY_FREEZE_REQUIRED')
    _,pf,pf_ref=predictors.contract(run,'ridge',2026,5)
    require(f['predictor_freeze_ref']==pf_ref,'AUXILIARY_PREDICTOR_FREEZE_CHANGED')
    return f,pf,dict(path=str(path),sha256=values.sha(path))


def _auxiliary_worker(pipe,operation,model_id,frame,y,dates,quantile,dependencies,features,observed):
    def started(event):
        pipe.send(('FIT_START',event['component']))
        if pipe.recv() is not True:raise RuntimeError('PARENT_REJECTED_FIT_BUDGET')
    try:
        require(operation=='auxiliary' and model_id=='native_auxiliary5' and y is None and quantile is None,'AUXILIARY_FEATURE_ONLY_WORKER_REQUIRED')
        with values.threadpool_limits(limits=1):
            fitted=auxiliary.fit_auxiliary(frame,cutoff=observed['cutoff'],source_contract=observed['source_contract'],on_fit_started=started)
        pipe.send(('RESULT',fitted,dict(operation='NATIVE_AUXILIARY5_OWNER',primary_pto_changed=False)))
    except BaseException as error:pipe.send(('ERROR',type(error).__name__,str(error)))
    finally:pipe.close()


def run_auxiliary(run,reader=None):
    run=ready(run);frozen,pf,freeze_ref=auxiliary_contract(run)
    root=run/'models/consensus_auxiliary/final_pre2026';rp=root/'receipt.json';mp=root/'model.joblib'
    existing=fusion.metadata(rp) if rp.exists() else None
    if existing and existing['status'] not in ('TRAINED_DIAGNOSTICS','TRAINED_WITH_COMPONENT_FAILURES'):return existing
    data_run=fusion.reader_run(run);reader=reader or ConsensusInputs(data_run,data_run/'derived/consensus100_daily.parquet')
    predictors.reader_integrity(reader,pf)
    fold,train,_=predictors.guarded_frames(reader,2026,5)
    columns=['signal_date','ticker','feature_available','feature_source',*predictors.FEATURES]
    if 'feature_available_at' in train:columns.append('feature_available_at')
    frame=train[columns].copy()
    source_contract=dict(feature_source_qualified=True,feature_order=list(predictors.FEATURES),source_pins=frozen['source_pins'],
        input_binding_sha256=pf['input_binding_sha256'],membership_sha256=pf['membership_sha256'],predictor_freeze_ref=frozen['predictor_freeze_ref'],
        source_policy=frozen['source_policy'],strict_PIT_certified=False,training_partition=TRAIN_PARTITION)
    reuse=dict(task_id=predictors.TASK,freeze_ref=freeze_ref,source_contract=source_contract,train_frame_sha256=predictors.frame_hash(frame),
        year_key=2026,cutoff=str(fold['calibration_start']),final_cutoff_exclusive=str(fold['cutoff_exclusive']),
        calibration_sessions_excluded=[str(d) for d in fold['calibration_sessions']],components=COMPONENTS,seed=auxiliary.SEED)
    tuple_sha=values.digest(reuse)
    if existing:
        require(existing['reuse_tuple']==reuse and existing['reuse_tuple_sha256']==tuple_sha and existing['model_sha256']==values.sha(mp),'AUXILIARY_COMPLETED_CHECKPOINT_CHANGED')
        return existing
    require(not root.exists(),'UNRECEIPTED_AUXILIARY_SLOT_PRESERVE')
    receipt=dict(status='IN_PROGRESS',task_id=predictors.TASK,reuse_tuple=reuse,reuse_tuple_sha256=tuple_sha,receipt_path=str(rp),model_path=str(mp),
        source_pins=frozen['source_pins'],fit_units=0,train_rows=len(frame),calibration_rows_fitted=0,primary_pto_changed=False,
        strict_PIT_certified=False,rl={m:auxiliary.fit_account_rl(m,None,on_fit_started=None) for m in ('reinforce','ppo')})
    with predictors.fit_lock(run):
        root.mkdir(parents=True);write_json_atomic(rp,receipt)
        try:
            fitted=values._fit_job('auxiliary','native_auxiliary5',frame,None,None,None,(),list(predictors.FEATURES),
                dict(cutoff=reuse['cutoff'],source_contract=source_contract),log=run/'FIT_LOG.jsonl',auth=dict(max_fit_units=10000,budget_bucket='consensus_auxiliary'),
                prior=0,year=2026,tuple_sha=tuple_sha,receipt=receipt,worker_target=_auxiliary_worker)
            auxiliary_contract(run)
            if isinstance(fitted,dict):receipt.update(status=fitted['status'],owner_receipt=fitted)
            else:
                require(isinstance(fitted,auxiliary.AuxiliaryFit),'CANONICAL_AUXILIARY_ARTIFACT_REQUIRED')
                joblib.dump(fitted,mp)
                failed=sum(v['status']!='FITTED' for v in fitted.receipt['methods'].values())
                receipt.update(status='TRAINED_WITH_COMPONENT_FAILURES' if failed else 'TRAINED_DIAGNOSTICS',model_sha256=values.sha(mp),owner_receipt=fitted.receipt)
            write_json_atomic(rp,receipt)
        except Exception as error:
            receipt.update(status='FAILED_NO_RETRY',failure=dict(type=type(error).__name__,message=str(error)));write_json_atomic(rp,receipt)
    return receipt


def run_fusion(run,reader=None):
    run=ready(run)
    frozen=fusion.metadata(run/'CONSENSUS_FUSION_FREEZE.json');slots=frozen['ordered_slots']
    require(len(slots)==expected_fusion_slots(run),'EXACT_FIXED_FUSION_SLOTS_REQUIRED')
    for s in (slots[0],slots[-1]):fusion.contract(run,s['packet_id'],s['method'],s['year'])
    data_run=fusion.reader_run(run);reader=reader or ConsensusInputs(data_run,data_run/'derived/consensus100_daily.parquet')
    progress=run/'logs/FUSION_PROGRESS.json';rows=[];started=time.monotonic()
    for i,s in enumerate(slots):
        fields={k:s[k] for k in ('packet_id','method','year')};emit('FUSION_START',slot=i+1,total=len(slots),**fields)
        if s['year']<2026:result=fusion.predict_one(run,s['packet_id'],s['method'],s['year'],reader=reader)
        else:
            fitted=fusion.fit_one(run,s['packet_id'],s['method'],s['year'],reader=reader)
            result=fitted if isinstance(fitted,dict) else fitted.receipt
        row=dict(**fields,status=result['status'],receipt_path=result.get('receipt_path',result.get('fit_receipt_path')),failure=result.get('failure'),reason=result.get('reason'))
        rows.append(row)
        summary=dict(status='RUNNING',slots_complete=len(rows),total_slots=len(slots),rows=rows,elapsed_seconds=round(time.monotonic()-started,1),test_2026_content_read=False)
        write_json_atomic(progress,summary);emit('FUSION_COMPLETE',slot=i+1,**row)
    summary['status']='COMPLETED_ALL_FIXED_SLOTS';write_json_atomic(progress,summary);emit('FUSION_PLAN_COMPLETE',slots=len(slots))
    return summary


def run_plan(run,stage='all',reader=None):
    require(stage in ('all','fusion','auxiliary'),'REGISTERED_DOWNSTREAM_STAGE_REQUIRED')
    run=ready(run)
    require(run!=fusion.CONTINUATION_RUN or stage=='fusion','CONTINUATION_ONLY_FOUR_FIXED_FUSION_SLOTS')
    lock=run/'CONSENSUS_DOWNSTREAM.lock'
    with lock.open('x',encoding='utf-8') as stream:stream.write(json.dumps(dict(stage=stage)))
    try:
        if stage in ('all','fusion'):
            planned=fusion.metadata(run/'CONSENSUS_FUSION_FREEZE.json')['ordered_slots']
            require(len(planned)==expected_fusion_slots(run),'EXACT_FIXED_FUSION_SLOTS_REQUIRED')
            for slot in (planned[0],planned[-1]):fusion.contract(run,slot['packet_id'],slot['method'],slot['year'])
        if stage in ('all','auxiliary'):auxiliary_contract(run)
        data_run=fusion.reader_run(run);reader=reader or ConsensusInputs(data_run,data_run/'derived/consensus100_daily.parquet')
        result={}
        if stage in ('all','fusion'):result['fusion']=run_fusion(run,reader)
        if stage in ('all','auxiliary'):
            emit('AUXILIARY_START');result['auxiliary']=run_auxiliary(run,reader);emit('AUXILIARY_COMPLETE',status=result['auxiliary']['status'])
        return result
    finally:lock.unlink()


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--stage',choices=['all','fusion','auxiliary'],default='all')
    args=parser.parse_args(argv);run_plan(args.run,args.stage)


if __name__=='__main__':main()
