"""R12 forecast recovery routing; frozen predictor/fusion algorithms stay sole owners.

Import, template and metadata preflight never decode research numeric payloads.
A root-frozen scope gates all real work. Private namespaces retain original source
paths/bytes and record this adapter separately; no source-hash impersonation.
"""
from __future__ import annotations
import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import warnings

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import consensus_predictors as predictors
from scripts.research.a2.training import consensus_fusion as fusion
from scripts.research.a2.training import consensus_ebm_teardown_retry as ebm
from scripts.research.a2.training import consensus_final_calibration_completion as finalcal

values=predictors.values
require=predictors.require
FREEZE='CONSENSUS_FORECAST_RECOVERY_FREEZE.json'
SCHEMA='CONSENSUS_FORECAST_RECOVERY_R12'
GATE='AUTHORIZED_PRE2026_FORECAST_RECOVERY'
RESEARCH_ID='CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12'
ELASTIC_CONFIGURATION='SAME_ELASTIC_OBJECTIVE_ALPHA0.0001_L1RATIO0.35_TOL1E-5_CYCLIC_MAXITER25000'


def ref(path):
    path=Path(path).resolve()
    return dict(path=str(path),sha256=values.sha(path))


def metadata(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and path.stat().st_size<=262144,
            'BOUNDED_CANONICAL_FORECAST_METADATA_REQUIRED')
    obj=json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(obj,dict),'FORECAST_METADATA_OBJECT_REQUIRED')
    return obj


def pin(reference):
    path=Path(reference['path'])
    require(path.is_absolute() and path.resolve(strict=True)==path and values.sha(path)==reference['sha256'],
            'FORECAST_REFERENCE_CHANGED')
    return path


def source_pins():
    return dict(adapter=ref(__file__),predictor=predictors.source_pins(),fusion=fusion.source_pins(),
                ebm=ref(ebm.__file__),final_calibration=ref(finalcal.__file__))


def ordered_slots(spec):
    slots=[s for s in fusion.planned_slots(spec) if s['packet_id'] in ('broad29','multih38')]
    for packet in ('broad29','multih38'):
        slots.extend(dict(packet_id=packet,method=fusion.owner.NNLS_ZERO_ABSTAIN,owner_id='NAMED_NNLS_ZERO_ABSTAIN_R1',
                          year=year,members=fusion.packets(spec)[packet]) for year in fusion.YEARS)
    return slots


def contract(run,*,authorized=True):
    run=Path(run).resolve()
    assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    scope=metadata(run/FREEZE)
    require(scope['schema']==SCHEMA and scope['task_id']==predictors.TASK
            and scope['research_id']==RESEARCH_ID and Path(scope['run'])==run,'FORECAST_SCOPE_IDENTITY_CHANGED')
    require(scope['status'] in ('PROPOSED',GATE) and scope['source_pins']==source_pins(),'FORECAST_SCOPE_SOURCE_CHANGED')
    if authorized:require(scope['status']==GATE,'ROOT_FORECAST_FIT_GATE_REQUIRED')
    require(scope['prior_fit_units']==2063 and scope['max_fit_units']==10000
            and scope['max_new_fit_units']==75 and scope['no_fit_budget_reset'] is True,'FORECAST_LIFETIME_BUDGET_CHANGED')
    require(scope['train_and_development_before']=='2026-01-01'
            and scope['test_2026_read_authorized'] is False and scope['confirmation_read_authorized'] is False
            and scope['old_artifacts_overwrite'] is False,'FORECAST_PRE2026_AND_IMMUTABILITY_REQUIRED')
    require(scope['elastic_solver']==dict(model_id='elastic',year=2021,horizon=5,max_iter=25000,
            alpha=.0001,l1_ratio=.35,tol=1e-5,selection='cyclic'),'ELASTIC_OBJECTIVE_OR_SOLVER_PLAN_CHANGED')
    parent=pin(scope['parent_predictor_freeze_ref']).parent
    spec,pf,pfr=predictors.contract(parent,'ridge',2025,5)
    require(pfr==scope['parent_predictor_freeze_ref'] and scope['ordered_fusion_slots']==ordered_slots(spec),
            'FORECAST_PARENT_OR_ORDERED_SLOTS_CHANGED')
    require(scope['recovered_ebm_broad_publication_authorized'] is True,'NEW_EBM_PACKET_AUTHORITY_REQUIRED')
    old=metadata(pin(scope['elastic_original_failure_ref']))
    require(old['status']=='FAILED' and old['model_id']=='elastic' and old['year']==2021 and old['horizon']==5
            and old['failure']['message']=='FIT_WORKER_FAILED:RuntimeError:UNRESOLVED_CONVERGENCE_NO_AUTOMATIC_RETRY',
            'ORIGINAL_ELASTIC_FAILURE_MUST_REMAIN')
    summary=metadata(pin(scope['ebm_summary_ref']))
    require(summary['schema']=='CONSENSUS_EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1'
            and summary['original_failures_preserved'] is True
            and all(e['status']=='TRAINED' for e in summary['slots']),'EBM_COMPLETED_CUSTODY_REQUIRED')
    pin(scope['root_scope_ref']);pin(scope['source_qualification_ref']);pin(scope['correction_sidecar_ref'])
    return run,scope,spec,pf,parent,ref(run/FREEZE)


def metadata_preflight(run):
    run,scope,_,_,_,fr=contract(run,authorized=False)
    return dict(status='PASS_METADATA_ONLY',freeze_ref=fr,slots=len(scope['ordered_fusion_slots']),
                max_new_fit_units=75,numeric_inputs_read=False,models_loaded=False,test_2026_rows_read=0)


def _namespace(path,name,constant_replacement=None):
    path=Path(path);source=path.read_bytes();tree=ast.parse(source,filename=str(path))
    if constant_replacement:
        old,new=constant_replacement;matches=[n for n in ast.walk(tree) if isinstance(n,ast.Constant) and n.value==old]
        require(len(matches)==1,'EXACT_ONE_ELASTIC_CONFIGURATION_ANNOTATION_REQUIRED')
        matches[0].value=new
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    exec(compile(tree,str(path),'exec'),module.__dict__)
    return module


def _elastic_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
    if operation!='predictor' or model_id!='elastic':
        return values._fit_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed)
    try:
        native=values._native(dependencies);model=native.estimator('elastic')
        expected=dict(alpha=.0001,l1_ratio=.35,tol=1e-5,max_iter=2500,selection='cyclic')
        require(all(model.get_params()[k]==v for k,v in expected.items()),'NATIVE_ELASTIC_RECIPE_CHANGED')
        model.set_params(max_iter=25000)
        with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always');pipe.send(('FIT_START','PREDICTOR_SAME_OBJECTIVE_EXTENDED_SOLVER'))
            require(pipe.recv() is True,'PARENT_REJECTED_FIT_BUDGET');model.fit(x,y)
        require(not any(w.category.__name__=='ConvergenceWarning' for w in caught),'ELASTIC_EXTENDED_SOLVER_UNRESOLVED')
        require(np.isfinite(model.coef_).all() and np.isfinite(model.intercept_)
                and np.isfinite(model.dual_gap_) and model.n_iter_<=25000,'ELASTIC_FINITE_CONVERGENCE_CERTIFICATE_REQUIRED')
        meta=dict(solver_only_change=True,max_iter=25000,n_iter=int(model.n_iter_),dual_gap=float(model.dual_gap_),
                  tolerance=1e-5,configuration=ELASTIC_CONFIGURATION,
                  warnings=[dict(category=w.category.__name__,message=str(w.message)) for w in caught])
        pipe.send(('RESULT',model,meta))
    except BaseException as exc:pipe.send(('ERROR',type(exc).__name__,str(exc)))
    finally:pipe.close()


def _values_proxy(prior):
    proxy=SimpleNamespace(**vars(values))
    def component(log,auth,old_prior,model,year,name,token):
        auth=dict(auth,max_new_bucket_fit_units=75)
        return values._component_start(log,auth,prior,model,year,name,token)
    def job(*args,**kwargs):
        kwargs['prior']=prior;kwargs['auth']=dict(kwargs['auth'],max_new_bucket_fit_units=75)
        if kwargs.get('worker_target') is None:kwargs['worker_target']=_elastic_worker
        return values._fit_job(*args,**kwargs)
    proxy._component_start=component;proxy._fit_job=job
    return proxy


def _elastic_namespace(run,scope,spec,pf,fr):
    name='_consensus_elastic_recovery_'+fr['sha256'][:24]
    module=_namespace(predictors.__file__,name,('UNCHANGED_STATEFUL_WORKER_FACTORY_WITH_RIDGE_ALPHA1_OVERRIDE',ELASTIC_CONFIGURATION))
    def local_contract(actual,model,year,horizon):
        require(Path(actual).resolve()==run and (model,year,horizon)==('elastic',2021,5),'EXACT_ELASTIC_RECOVERY_SLOT_REQUIRED')
        contract(run);return spec,pf,fr
    original_frames=module.guarded_frames
    def frames(reader,year,horizon):
        fold,train,cal=original_frames(reader,year,horizon)
        old=metadata(pin(scope['elastic_original_failure_ref']))['reuse_tuple']
        require(module.frame_hash(train)==old['train_frame_sha256']
                and module.frame_hash(cal)==old['calibration_frame_sha256'],'ELASTIC_ORIGINAL_FULL_ROWS_REQUIRED')
        return fold,train,cal
    module.contract=local_contract;module.guarded_frames=frames;module.values=_values_proxy(scope['prior_fit_units'])
    return module


def recover_elastic(run,reader=None):
    run,scope,spec,pf,parent,fr=contract(run)
    reader=reader or predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    module=_elastic_namespace(run,scope,spec,pf,fr)
    return module.predict_one(run,'elastic',2021,5,reader)


def _ebm_fit(scope,year):
    summary=metadata(pin(scope['ebm_summary_ref']))
    entries=[e for e in summary['slots'] if e['slot']==dict(model_id='ebm',year=year,horizon=5)]
    require(len(entries)==1 and entries[0]['status']=='TRAINED','EXACT_TRAINED_EBM_YEAR_REQUIRED')
    receipt=metadata(pin(entries[0]['receipt_ref']));reuse=receipt['reuse_tuple']
    old=metadata(pin(reuse['original_failed_receipt_ref']))['reuse_tuple']
    require(receipt['status']=='TRAINED' and receipt['year']==year and receipt['horizon']==5
            and receipt['source_pins']==predictors.source_pins() and receipt['test_2026_rows_read']==0
            and old['year']==year and old['calibration_maturity_exclusive']==str(pd.Timestamp(f'{year}-01-01')),
            'EBM_FIT_CLOCK_OR_SOURCES_CHANGED')
    pin(receipt['model_ref']);pin(receipt['calibration_ref'])
    return receipt,entries[0]['receipt_ref']


def publish_recovered_ebm(run,year,reader=None):
    require(2021<=year<2026,'EBM_REAL_2026_PUBLICATION_FORBIDDEN')
    run,scope,_,pf,parent,fr=contract(run)
    reader=reader or predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    predictors.reader_integrity(reader,pf);fit,fit_ref=_ebm_fit(scope,year)
    frame=reader.read_prediction_year(year);keys=reader.prediction_keys(year)
    require(pd.to_datetime(frame.signal_date).ge(f'{year}-01-01').all()
            and pd.to_datetime(frame.signal_date).lt(f'{year+1}-01-01').all(),'PRE2026_EBM_FRAME_REQUIRED')
    output=run/'predictions/consensus_predictors/ebm/5d'/f'{year}.parquet';rp=output.with_suffix('.receipt.json')
    frame_sha=predictors.frame_hash(frame);keys_sha=predictors.frame_hash(keys)
    if output.exists() or rp.exists():
        require(output.exists() and rp.exists(),'INCOMPLETE_EBM_PUBLICATION_PRESERVE')
        old=metadata(rp)
        require(old['forecast_recovery_freeze_ref']==fr and old['sha256']==values.sha(output)
                and old['frame_sha256']==frame_sha and old['key_sha256']==keys_sha
                and old['fit_receipt_ref']==fit_ref,'RECOVERED_EBM_PUBLICATION_CHANGED')
        return old
    values._native(fit['reuse_tuple']['dependency_paths']);fitted=joblib.load(fit['model_ref']['path']);fitted.receipt=fit
    pred=fitted.predict_frame(frame,reader)
    out=keys[['signal_date','ticker']].merge(pred,on=['signal_date','ticker'],how='left',validate='one_to_one')
    require(len(pred)==out.prediction.notna().sum(),'EBM_KEYS_CHANGED')
    out['prediction_qualified']=out.prediction.notna();out['year']=year;out['reuse_tuple_sha256']=fit['reuse_tuple_sha256']
    output.parent.mkdir(parents=True,exist_ok=True);out.to_parquet(output,index=False)
    pub=dict(status='PUBLISHED',prediction_role='MODEL_OOF',origin_kind='RECOVERED_EBM',path=str(output),sha256=values.sha(output),
             model_id='ebm',year=year,horizon=5,joint_horizon=5,rows=len(out),frame_sha256=frame_sha,key_sha256=keys_sha,
             forecast_recovery_freeze_ref=fr,fit_receipt_ref=fit_ref,reuse_tuple_sha256=fit['reuse_tuple_sha256'],
             test_2026_rows_read=0,fit_units=0)
    write_json_atomic(rp,pub);return pub


def _recovery_publication(run,scope,pf,parent,fr,member,year,reader):
    model,horizon=member['model_id'],member['horizon']
    if model!='ebm' and (model,year,horizon)!=('elastic',2021,5):
        return fusion.publication(parent,member,year,reader)
    require(2021<=year<2026 and horizon==5,'RECOVERY_MEMBER_PRE2026_ONLY')
    output=run/'predictions/consensus_predictors'/model/'5d'/f'{year}.parquet'
    rp=output.with_suffix('.receipt.json')
    if not output.exists() or not rp.exists():raise fusion.PacketUnavailable('MISSING_RECOVERED_MEMBER:'+model+':'+str(year))
    pub=metadata(rp)
    require(pub['status']=='PUBLISHED' and pub.get('prediction_role','MODEL_OOF')=='MODEL_OOF'
            and (pub['model_id'],pub['year'],pub['horizon'],pub['joint_horizon'])==(model,year,5,5)
            and pub['sha256']==values.sha(output) and pub['test_2026_rows_read']==0,'RECOVERED_MEMBER_PUBLICATION_CHANGED')
    if model=='ebm':
        fit,fit_ref=_ebm_fit(scope,year)
        require(pub['fit_receipt_ref']==fit_ref and pub['forecast_recovery_freeze_ref']==fr,'RECOVERED_EBM_ORIGIN_CHANGED')
    else:
        fit_path=Path(pub['fit_receipt_path']);fit=metadata(fit_path);fit_ref=ref(fit_path)
        require(fit_ref['sha256']==pub['fit_receipt_sha256'] and fit['status']=='TRAINED'
                and fit['reuse_tuple']['freeze_ref']==fr and fit['reuse_tuple']['native_configuration']==ELASTIC_CONFIGURATION
                and fit['model_sha256']==pub['model_sha256']==values.sha(fit['model_path']),
                'RECOVERED_ELASTIC_ORIGIN_CHANGED')
    require(pub['reuse_tuple_sha256']==fit['reuse_tuple_sha256'],'RECOVERED_MEMBER_TUPLE_CHANGED')
    from scripts.research.a2.data.joint_input_binding import guard_parquet
    _,proof=guard_parquet(output,pub['sha256'],['signal_date'])
    bounds=proof['date_bounds']['signal_date'];cut=pd.Timestamp(f'{year}-01-01');end=pd.Timestamp(f'{year+1}-01-01')
    require(proof['rows']==pub['rows'] and (not proof['rows'] or (bounds and all(
        pd.Timestamp(b['min'])>=cut and pd.Timestamp(b['max'])<end for b in bounds))),'RECOVERED_MEMBER_PHYSICAL_CLOCK_CHANGED')
    token=values.digest(dict(publication=ref(rp),fit=fit_ref));cache=getattr(reader,'_consensus_recovery_oof_cache',{})
    if token not in cache:
        frame=pq.read_table(output,columns=['signal_date','ticker','prediction','prediction_qualified','year','reuse_tuple_sha256'],
            filters=[('signal_date','>=',cut),('signal_date','<',end)]).to_pandas()
        require(not frame.duplicated(['signal_date','ticker']).any() and frame.year.eq(year).all()
                and frame.reuse_tuple_sha256.eq(fit['reuse_tuple_sha256']).all()
                and frame.prediction_qualified.eq(frame.prediction.notna()).all(),'RECOVERED_MEMBER_ROW_PROVENANCE_CHANGED')
        cache[token]=frame[['signal_date','ticker','prediction']].rename(columns={'prediction':'expert_'+fusion.member_key(member)})
        reader._consensus_recovery_oof_cache=cache
    return cache[token],dict(member=fusion.member_key(member),year=year,publication_receipt_sha256=values.sha(rp),
                            prediction_sha256=pub['sha256'],fit_receipt_sha256=fit_ref['sha256'])


def bind_fusion(run):
    run,scope,spec,pf,parent,fr=contract(run)
    name='_consensus_fusion_recovery_'+fr['sha256'][:24]
    module=_namespace(fusion.__file__,name)
    frozen=dict(schema=SCHEMA,source_pins=source_pins(),predictor_freeze_ref=scope['parent_predictor_freeze_ref'],
                prior_fit_units=scope['prior_fit_units'],source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY')
    def local_contract(actual,packet,method,year):
        require(Path(actual).resolve()==run,'EXACT_RECOVERY_FUSION_RUN_REQUIRED');contract(run)
        method=fusion.owner.method_name(method)
        matches=[s for s in scope['ordered_fusion_slots'] if (s['packet_id'],s['method'],s['year'])==(packet,method,year)]
        require(len(matches)==1,'UNPLANNED_RECOVERY_FUSION_SLOT')
        return run,method,spec,frozen,matches[0],fr
    proxy=SimpleNamespace(**vars(predictors));proxy.values=_values_proxy(scope['prior_fit_units'])
    def guarded(reader,year,horizon):
        fold,train,cal=predictors.guarded_frames(reader,year,horizon)
        if year==2026:cal=finalcal.apply_patch_to_calibration(cal,horizon,finalcal.read_patch(scope))
        return fold,train,cal
    proxy.guarded_frames=guarded
    proxy.contract=lambda actual,model,year,horizon:predictors.contract(parent,model,year,horizon)
    module.ConsensusInputs=lambda actual,membership:predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    module.predictors=proxy;module.values=proxy.values;module.contract=local_contract;module.reader_run=lambda actual:parent
    module.publication=lambda actual,member,year,reader:_recovery_publication(run,scope,pf,parent,fr,member,year,reader)
    return module


def published_fusion_forecasts(run,method,year,reader=None,*,packet_id='core5'):
    require(year in (2023,2024,2025),'REAL_2026_FUSION_READ_FORBIDDEN')
    _,scope,_,_,parent,_=contract(run)
    if packet_id=='core5':return fusion.published_fusion_forecasts(fusion.CONTINUATION_RUN,method,year,reader,packet_id=packet_id)
    module=bind_fusion(run)
    return module.published_fusion_forecasts(run,method,year,reader,packet_id=packet_id)



def freeze_template(run,root_scope_ref):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    parent=fusion.PARENT_RUN;spec,pf,pfr=predictors.contract(parent,'ridge',2025,5)
    qualification,patch=finalcal._patch_metadata(fusion.CONTINUATION_RUN)
    return dict(schema=SCHEMA,status='PROPOSED',task_id=predictors.TASK,research_id=RESEARCH_ID,run=str(run),
        root_scope_ref=root_scope_ref,source_pins=source_pins(),parent_predictor_freeze_ref=pfr,
        elastic_original_failure_ref=ref(parent/'models/consensus_predictors/elastic/5d/2021/receipt.json'),
        ebm_summary_ref=ref(fusion.CONTINUATION_RUN/'EBM_TEARDOWN_RETRY_ACTUAL_SUMMARY_R1.json'),
        recovered_ebm_broad_publication_authorized=True,
        elastic_solver=dict(model_id='elastic',year=2021,horizon=5,max_iter=25000,alpha=.0001,l1_ratio=.35,tol=1e-5,selection='cyclic'),
        ordered_fusion_slots=ordered_slots(spec),prior_fit_units=2063,max_fit_units=10000,max_new_fit_units=75,
        no_fit_budget_reset=True,train_and_development_before='2026-01-01',test_2026_read_authorized=False,
        confirmation_read_authorized=False,old_artifacts_overwrite=False,
        correction_sidecar_ref=patch['patch_ref'],source_qualification_ref=qualification)


def run_all(run,reader=None):
    run,scope,_,_,parent,fr=contract(run)
    reader=reader or predictors.ConsensusInputs(parent,parent/'derived/consensus100_daily.parquet')
    elastic=recover_elastic(run,reader)
    ebm_publications=[publish_recovered_ebm(run,year,reader) for year in range(2021,2026)]
    module=bind_fusion(run);entries=[]
    slots=sorted(scope['ordered_fusion_slots'],key=lambda s:(s['year'],s['packet_id'],s['method']))
    for slot in slots:
        print('START forecast recovery '+slot['packet_id']+' '+slot['method']+' '+str(slot['year']),flush=True)
        if slot['year']<2026:result=module.predict_one(run,slot['packet_id'],slot['method'],slot['year'],reader)
        else:
            fitted=module.fit_one(run,slot['packet_id'],slot['method'],slot['year'],reader)
            result=fitted.receipt if hasattr(fitted,'receipt') else fitted
        _,rp,_=module.slot_paths(run,slot['packet_id'],slot['method'],slot['year'])
        entries.append(dict(slot=slot,status=result['status'],receipt_ref=ref(rp),
                            publication_ref=ref(Path(result['path']).with_suffix('.receipt.json')) if result.get('status')=='PUBLISHED' else None))
        print('COMPLETE forecast recovery '+slot['packet_id']+' '+slot['method']+' '+str(slot['year'])+' '+result['status'],flush=True)
    result=dict(schema='CONSENSUS_FORECAST_RECOVERY_ACTUAL_SUMMARY_R12',freeze_ref=fr,
                elastic=elastic,ebm_publications=ebm_publications,fusion_slots=entries,
                test_2026_rows_read=0,original_failures_preserved=True)
    write_json_atomic(run/'FORECAST_RECOVERY_ACTUAL_SUMMARY.json',result)
    return result
