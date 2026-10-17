"""Fixed native gross-forecast slots for the authorized consensus pool.

No research I/O or fitting on import. The root-owned reader supplies legal rows;
this adapter reuses the native worker and heldout calibrators without inherited
A-run identities, in-sample statistics, sample caps, or automatic fit retries.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import stateful_values as values
from scripts.research.a2.data.consensus_training_inputs import ConsensusInputs, FEATURES, mature_keys

REPO=Path(__file__).resolve().parents[4]
TASK='CONSENSUS100_PTO_3000_20261012_R1'
ALIAS={'rbf_svm':'svc'}
SECONDARY=('ridge','hgb','xgb')
BOUNDARY=pd.Timestamp('2026-01-01')


def require(ok,message):
    if not ok:raise ValueError(message)


def source_pins():
    paths=dict(adapter=Path(__file__),values=Path(values.__file__),native=values.NATIVE,
        extensions=values.EXTENSION_SOURCE,input_reader=REPO/'scripts/research/a2/data/consensus_training_inputs.py',
        feature_list=values.FEATURE_SOURCE,feature_check=values.FEATURE_CHECK,
        input_constants=values.READER_SOURCE,svc_factory=REPO/'scripts/research/fast3/calibrated_models.py')
    return {name:dict(path=str(path),sha256=values.sha(path)) for name,path in paths.items()}


def planned_slots(spec):
    years=spec['training_plan']['years'];models=spec['model_ids']
    require(years==list(range(2021,2027)) and len(models)==29 and len(set(models))==29,'EXACT_AUTHORIZED_29_MODELS_AND_6_CUTOFFS_REQUIRED')
    require(set(ALIAS.get(m,m) for m in models)==set(values.FIRST_MODELS),'AUTHORIZED_NATIVE_FAMILIES_CHANGED')
    primary=[dict(model_id=m,year=y,horizon=5) for y in years for m in models]
    secondary=[dict(model_id=m,year=y,horizon=h) for y in years for h in (3,10,20) for m in SECONDARY]
    return primary+secondary


def frame_hash(frame):
    values_hash=pd.util.hash_pandas_object(frame,index=False).to_numpy(np.uint64)
    return values.digest(dict(columns=list(frame.columns),dtypes=[str(d) for d in frame.dtypes],
                              rows=len(frame),content=__import__('hashlib').sha256(values_hash.tobytes()).hexdigest()))


def spec_path():
    return resolve(REPO).results_root/'_maintenance'/TASK/'AUTHORIZED_RESEARCH_SPEC.json'


def freeze_template(run):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(REPO))
    sp=spec_path();spec=json.loads(sp.read_text(encoding='utf-8'))
    require(spec['task_id']==TASK,'TASK_SPEC_CHANGED')
    return dict(schema='CONSENSUS_PREDICTOR_FREEZE_R1',status='PROPOSED',task_id=TASK,
        authorized_spec=dict(path=str(sp),sha256=values.sha(sp)),source_pins=source_pins(),
        input_binding_sha256=values.sha(run/'derived/PHYSICAL_SOURCE_BINDING.json'),
        membership_sha256=values.sha(run/'derived/consensus100_daily.parquet'),
        ordered_slots=planned_slots(spec),max_fit_units=10000,final_cutoff_training_only_authorized=False,
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',strict_PIT_certified=False)


def contract(run,model_id,year,horizon):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(REPO))
    freeze_path=run/'CONSENSUS_PREDICTOR_FREEZE.json'
    f=json.loads(freeze_path.read_text(encoding='utf-8'))
    require(f['status']=='AUTHORIZED_PRE2026_TRAINING_ONLY' and f['task_id']==TASK,'PREDICTOR_FREEZE_REQUIRED')
    require(f['source_pins']==source_pins(),'FROZEN_PREDICTOR_SOURCE_CHANGED')
    sp=Path(f['authorized_spec']['path']);require(sp==spec_path() and values.sha(sp)==f['authorized_spec']['sha256'],'AUTHORIZED_SPEC_HASH_CHANGED')
    spec=json.loads(sp.read_text(encoding='utf-8'));plan=spec['training_plan']
    require(f['ordered_slots']==planned_slots(spec),'SLOT_PLAN_CHANGED')
    require(dict(model_id=model_id,year=year,horizon=horizon) in f['ordered_slots'],'UNPLANNED_METHOD_YEAR_HORIZON')
    require(plan['seed']==values.SEED and plan['calibration_sessions']==60 and plan['physical_fit_timeout_seconds']==values.FIT_TIMEOUT,'NATIVE_CAPACITY_OR_CALIBRATION_CHANGED')
    require(plan['quantiles']==[.1,.5,.9] and plan['sample_cap'] is None and plan['weights']=='UNIFORM_LEGAL_ROWS','ROW_SELECTION_OR_HEADS_CHANGED')
    require(f['max_fit_units']==plan['max_physical_fit_components']==10000,'GLOBAL_FIT_BUDGET_CHANGED')
    require(f['source_policy']==spec['source_policy']=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY','SOURCE_POLICY_CHANGED')
    if year==2026:require(f['final_cutoff_training_only_authorized'] is True,'FINAL_CUTOFF_NEEDS_ROOT_GATE')
    require(values.sha(run/'derived/PHYSICAL_SOURCE_BINDING.json')==f['input_binding_sha256'],'BOUND_INPUT_MANIFEST_CHANGED')
    require(values.sha(run/'derived/consensus100_daily.parquet')==f['membership_sha256'],'POOL_BYTES_CHANGED')
    return spec,f,dict(path=str(freeze_path),sha256=values.sha(freeze_path))


def reader_integrity(reader,frozen):
    require(reader.membership_sha256==frozen['membership_sha256'],'READER_POOL_IDENTITY_CHANGED')
    for name,ref in reader.records.items():
        st=Path(ref['path']).stat()
        require(dict(size=st.st_size,mtime_ns=st.st_mtime_ns)==ref['file_fingerprint'],'BOUND_READER_SOURCE_CHANGED:'+name)
    if getattr(reader,'_consensus_physical_verified',None)!=frozen['input_binding_sha256']:
        from scripts.research.a2.data.joint_input_binding import guard_parquet
        for name,ref in reader.records.items():
            import pyarrow as pa
            import pyarrow.parquet as pq
            schema=pq.ParquetFile(ref['path']).schema_arrow
            typed={field.name for field in schema if pa.types.is_timestamp(field.type) or pa.types.is_date(field.type)}
            named={c for c in ref['schema'] if c.endswith('_date') or c=='trade_date' or c.startswith('target_end_date_')}
            clocks=list(ref['date_bounds'])
            require(clocks and (typed|named)<=set(clocks),'ALL_PHYSICAL_CLOCKS_REQUIRED:'+name)
            _,proof=guard_parquet(ref['path'],ref['sha256'],clocks)
            require(proof['rows']==ref['rows'] and proof['schema']==ref['schema'],'PHYSICAL_SCHEMA_OR_ROWS_CHANGED:'+name)
        reader._consensus_physical_verified=frozen['input_binding_sha256']


def cached(reader,key,loader,kind):
    cache=getattr(reader,'_consensus_predictor_cache',{})
    if cache.get(kind,{}).get('key')!=key:cache[kind]=dict(key=key,frame=loader())
    reader._consensus_predictor_cache=cache
    return cache[kind]['frame']


def guarded_frames(reader,year,horizon):
    fold=reader.annual_fold(year);dates=pd.DatetimeIndex(reader.calendar)
    require(not dates.has_duplicates and dates.is_monotonic_increasing and (dates<BOUNDARY).all(),'PRE2026_CALENDAR_REQUIRED')
    prior=dates[dates<pd.Timestamp(f'{year}-01-01')]
    require(len(prior)>=60 and pd.DatetimeIndex(fold['calibration_sessions']).equals(prior[-60:]),'EXACT_60_CHRONOLOGICAL_CALIBRATION_REQUIRED')
    require(pd.Timestamp(fold['cutoff_exclusive'])==pd.Timestamp(f'{year}-01-01')<=BOUNDARY and pd.Timestamp(fold['calibration_start'])==prior[-60],'INVALID_FIT_CLOCK')
    frames=reader.read_training_fold(year,horizon)
    for stage,frame in zip(('train','calibration'),frames):
        expected=mature_keys(frame,fold,stage,horizon)
        require(len(frame)==len(expected) and frame[['signal_date','ticker']].reset_index(drop=True).equals(expected[['signal_date','ticker']]),'UNQUALIFIED_OR_UNORDERED_TRAINING_ROWS')
        require(len(frame)>=2 and frame.label_coordinate.eq(values.LABEL).all(),'LEGAL_SHAREHOLDER_BRIDGE_ROWS_REQUIRED')
        require(np.isfinite(frame[[*FEATURES,'target','y_open5']].to_numpy(float)).all(),'NONFINITE_TRAINING_VALUES')
    require(len(frames)==2,'TRAIN_AND_CALIBRATION_REQUIRED')
    return fold,frames[0],frames[1]


@contextmanager
def fit_lock(run):
    path=Path(run)/'CONSENSUS_FIT.lock'
    with path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(dict(pid=os.getpid(),created=time.time())))
    try:yield
    finally:path.unlink()


def slot_paths(run,model_id,year,horizon):
    root=Path(run)/'models/consensus_predictors'/model_id/f'{horizon}d'/str(year)
    return root,root/'receipt.json',root/'model.joblib',root/'calibration_predictions.parquet'


def raw_predict(bundle,owner_id,frame,reader):
    if owner_id in values.EXTENSIONS:
        from scripts.research.a2.training.stateful_value_extensions import raw_predict as extension_predict
        x,observed=values.extension_inputs(owner_id,reader,frame,list(FEATURES))
        return extension_predict(bundle,x,observed)
    x=values.transform(bundle.scaler,frame[list(FEATURES)].to_numpy(float))
    with threadpool_limits(limits=1):return bundle.raw_predict(x)


@dataclass
class ConsensusPredictor:
    native:object
    calibration:dict
    bridge:dict|None
    receipt:dict

    def mapped(self,raw):
        if self.bridge is None:return values.calibrated_values(self.calibration,raw)
        scalar=values.raw_fields(self.receipt['native_model_id'],raw)['native_mu']
        mean=self.bridge['intercept']+self.bridge['slope']*scalar
        return mean,np.full(len(mean),self.calibration['sigma'])

    def predict_frame(self,frame,reader):
        require(source_pins()==self.receipt['source_pins'],'PREDICTION_SOURCE_CHANGED')
        dates=pd.to_datetime(frame.signal_date);year=self.receipt['year']
        require(year<2026 and (dates>=pd.Timestamp(f'{year}-01-01')).all() and (dates<pd.Timestamp(f'{year+1}-01-01')).all(),'PREDICTION_OUTSIDE_PRE2026_ANNUAL_SCOPE')
        require(not frame.duplicated(['signal_date','ticker']).any(),'DUPLICATE_PREDICTION_KEYS')
        require(frame.feature_available.eq(True).all() and frame.feature_source.isin(values.SOURCES).all(),'UNQUALIFIED_PREDICTION_ROWS')
        require(np.isfinite(frame[list(FEATURES)].to_numpy(float)).all(),'NONFINITE_QUALIFIED_PREDICTION_FEATURES')
        out=frame[['signal_date','ticker']].copy();owner=self.receipt['native_model_id']
        if len(frame):
            raw=raw_predict(self.native,owner,frame,reader);mean,sigma=self.mapped(raw)
            require(np.isfinite(mean).all() and np.isfinite(sigma).all() and (sigma>0).all(),'INVALID_FORECAST_OR_SIGMA')
            out['prediction']=mean;out['value_sigma']=sigma
            for name,array in values.raw_fields(owner,raw).items():out[name]=array
        else:out['prediction']=pd.Series(dtype=float);out['value_sigma']=pd.Series(dtype=float)
        return out


def fit_one(run,model_id,year,horizon=5,reader=None):
    run=Path(run).resolve();spec,frozen,freeze_ref=contract(run,model_id,year,horizon)
    root,receipt_path,model_path,cal_path=slot_paths(run,model_id,year,horizon)
    existing=json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else None
    if existing and existing['status']!='TRAINED':return existing
    reader=reader or ConsensusInputs(run,run/'derived/consensus100_daily.parquet');reader_integrity(reader,frozen)
    key=(year,horizon,frozen['input_binding_sha256'],frozen['membership_sha256'])
    fold,train,cal=cached(reader,key,lambda:guarded_frames(reader,year,horizon),'training')
    feature_binding=values.feature_binding();require(tuple(feature_binding['features'])==FEATURES,'FEATURE_ORDER_CHANGED')
    owner=ALIAS.get(model_id,model_id)
    reuse=dict(task_id=TASK,model_id=model_id,native_model_id=owner,alias=ALIAS.get(model_id),year=year,horizon=horizon,
        primary_horizon=5,source_pins=frozen['source_pins'],authorized_spec=frozen['authorized_spec'],freeze_ref=freeze_ref,
        input_binding_sha256=frozen['input_binding_sha256'],membership_sha256=frozen['membership_sha256'],feature_binding=feature_binding,
        train_frame_sha256=frame_hash(train),calibration_frame_sha256=frame_hash(cal),seed=values.SEED,
        native_configuration='UNCHANGED_STATEFUL_WORKER_FACTORY_WITH_RIDGE_ALPHA1_OVERRIDE',
        target_definition=spec['target_plan']['primary_5d' if horizon==5 else 'secondary_3_10_20d'],
        train_maturity_exclusive=str(fold['calibration_start']),calibration_maturity_exclusive=str(fold['cutoff_exclusive']),
        calibration_sessions=[str(x) for x in fold['calibration_sessions']],bridge='NONE' if horizon==5 else 'HELDOUT_OLS_NATIVE_SCALAR_TO_Y_OPEN5')
    tuple_sha=values.digest(reuse)
    if existing:
        require(existing['reuse_tuple_sha256']==tuple_sha and existing['reuse_tuple']==reuse,'COMPLETED_CHECKPOINT_IDENTITY_CHANGED')
        require(values.sha(model_path)==existing['model_sha256'] and values.sha(cal_path)==existing['calibration_predictions_sha256'],'COMPLETED_CHECKPOINT_BYTES_CHANGED')
        values._native(spec['dependency_paths']);fitted=joblib.load(model_path);fitted.receipt=existing;return fitted
    require(not root.exists(),'UNRECEIPTED_SLOT_PRESERVE_NO_RETRY')
    auth=dict(max_fit_units=10000,budget_bucket=f'consensus_predictors_{horizon}d')
    log=run/'FIT_LOG.jsonl';receipt=dict(status='IN_PROGRESS',model_id=model_id,native_model_id=owner,year=year,horizon=horizon,
        receipt_path=str(receipt_path),model_path=str(model_path),source_pins=frozen['source_pins'],fit_units=0,reuse_tuple=reuse,reuse_tuple_sha256=tuple_sha,
        train_rows=len(train),calibration_rows=len(cal),strict_PIT_certified=False,source_policy=frozen['source_policy'])
    with fit_lock(run):
        root.mkdir(parents=True);write_json_atomic(receipt_path,receipt)
        values._append(log,dict(event='CONSENSUS_SLOT_STARTED',model_id=model_id,year=year,horizon=horizon,reuse_tuple_sha256=tuple_sha))
        def statistical(component):
            values._component_start(log,auth,0,owner,year,component,tuple_sha);receipt['fit_units']+=1;write_json_atomic(receipt_path,receipt)
        def job(operation,x,y=None,quantile=None,observed=None):
            return values._fit_job(operation,owner,x,y,train.signal_date.to_numpy(),quantile,spec['dependency_paths'],list(FEATURES),observed,
                log=log,auth=auth,prior=0,year=year,tuple_sha=tuple_sha,receipt=receipt)
        try:
            native=values._native(spec['dependency_paths']);x=train[list(FEATURES)].to_numpy(float);y=train.target.to_numpy(float)
            if owner in ('logistic','svc'):require(len(np.unique(y>0))==2 and (cal.target>0).sum()>=2 and (cal.target<=0).sum()>=2,'CLASSIFICATION_TRAIN_CAL_CLASSES_REQUIRED')
            if owner in values.EXTENSIONS:
                ex,mask=values.extension_inputs(owner,reader,train,list(FEATURES));bundle=job('extension',ex,y,observed=mask)
            else:
                bundle=native.NativeBundle(owner,list(FEATURES))
                if owner in values.SCALED:bundle.scaler=job('scaler',x)
                xx=values.transform(bundle.scaler,x)
                bundle.estimator_object=[job('predictor',xx,y,quantile=q) for q in (.1,.5,.9)] if owner in values.QUANTILE and owner not in values.TORCH else job('predictor',xx,y)
            raw=raw_predict(bundle,owner,cal,reader);fields=values.raw_fields(owner,raw);bridge=None
            if horizon!=5:
                statistical('HELDOUT_OLS_BRIDGE_TO_PRIMARY5D')
                design=np.column_stack([np.ones(len(cal)),fields['native_mu']]);coef=np.linalg.lstsq(design,cal.y_open5.to_numpy(float),rcond=None)[0]
                require(np.isfinite(coef).all(),'INVALID_HELDOUT_BRIDGE')
                bridge=dict(intercept=float(coef[0]),slope=float(coef[1]),input_horizon=horizon,output_horizon=5,fit_scope='PAST_60_SESSION_CALIBRATION_Y_OPEN5_ONLY')
                statistical('HELDOUT_BRIDGE_RESIDUAL_SIGMA')
                sigma=float(np.std(cal.y_open5.to_numpy(float)-design@coef,ddof=1));require(np.isfinite(sigma) and sigma>0,'NONPOSITIVE_HELDOUT_BRIDGE_SIGMA')
                calibration=dict(model_id=owner,kind='secondary_bridge',sigma=sigma,native_sigma_calibrated=False)
            else:
                isotonic=None
                if owner in values.RANK or owner=='svc':isotonic=job('isotonic',fields['rank_score'] if owner in values.RANK else fields['svc_margin'],cal.target.to_numpy(float))
                elif owner=='logistic' or owner=='huber' or owner in values.QUANTILE:statistical('HELDOUT_CLASS_AMPLITUDES' if owner=='logistic' else 'HELDOUT_MEAN_OFFSET')
                statistical('HELDOUT_RESIDUAL_SIGMA')
                calibration=values.heldout_calibration(owner,raw,cal.target.to_numpy(float),isotonic=isotonic)
            fitted=ConsensusPredictor(bundle,calibration,bridge,receipt);mean,sigma=fitted.mapped(raw)
            diagnostic=cal[['signal_date','ticker','target','y_open5']].copy()
            for name,array in fields.items():diagnostic[name]=array
            diagnostic['prediction_primary5d']=mean;diagnostic['value_sigma']=sigma;diagnostic['scope']='PAST_HELDOUT_CALIBRATION_USED_FOR_FIT_NOT_OOF_EVALUATION'
            diagnostic.to_parquet(cal_path,index=False)
            if hasattr(bundle,'_torch_model'):bundle._torch_model=None
            if hasattr(bundle,'_model'):bundle._model=None
            joblib.dump(fitted,model_path)
            receipt.update(status='TRAINED',model_sha256=values.sha(model_path),calibration_predictions_sha256=values.sha(cal_path),
                calibration={k:v for k,v in calibration.items() if k!='isotonic'},bridge=bridge)
            write_json_atomic(receipt_path,receipt);values._append(log,dict(event='CONSENSUS_SLOT_COMPLETE',model_id=model_id,year=year,horizon=horizon,fit_units=receipt['fit_units'],reuse_tuple_sha256=tuple_sha))
            return fitted
        except Exception as exc:
            receipt.update(status='FAILED',failure=dict(type=type(exc).__name__,message=str(exc)))
            write_json_atomic(receipt_path,receipt);values._append(log,dict(event='CONSENSUS_SLOT_FAILED',model_id=model_id,year=year,horizon=horizon,fit_units=receipt['fit_units'],failure=receipt['failure']))
            return receipt


def predict_one(run,model_id,year,horizon=5,reader=None):
    require(year<2026,'2026_PREDICTION_REQUIRES_ROOT_SEPARATE_TEST_GATE')
    spec,frozen,_=contract(run,model_id,year,horizon);run=Path(run).resolve()
    reader=reader or ConsensusInputs(run,run/'derived/consensus100_daily.parquet');reader_integrity(reader,frozen)
    fitted=fit_one(run,model_id,year,horizon,reader)
    if isinstance(fitted,dict):return fitted
    frame=cached(reader,(year,frozen['input_binding_sha256'],frozen['membership_sha256']),lambda:reader.read_prediction_year(year),'prediction')
    keys=reader.prediction_keys(year);frame_sha=frame_hash(frame);key_sha=frame_hash(keys)
    output=run/'predictions/consensus_predictors'/model_id/f'{horizon}d/{year}.parquet';rp=output.with_suffix('.receipt.json')
    if output.exists() or rp.exists():
        require(output.exists() and rp.exists(),'INCOMPLETE_PREDICTION_CHECKPOINT_PRESERVE')
        r=json.loads(rp.read_text(encoding='utf-8'))
        require(r['sha256']==values.sha(output) and r['reuse_tuple_sha256']==fitted.receipt['reuse_tuple_sha256'] and r['frame_sha256']==frame_sha and r['key_sha256']==key_sha and r['model_sha256']==fitted.receipt['model_sha256'] and r['fit_receipt_sha256']==values.sha(fitted.receipt['receipt_path']),'PREDICTION_CHECKPOINT_CHANGED')
        return r
    pred=fitted.predict_frame(frame,reader)
    require(not keys.duplicated(['signal_date','ticker']).any(),'DUPLICATE_PREDICTION_METADATA_KEYS')
    out=keys[['signal_date','ticker']].merge(pred,on=['signal_date','ticker'],how='left',validate='one_to_one')
    require(len(frame)==out.prediction.notna().sum(),'PREDICTION_FRAME_KEYS_NOT_IN_CAUSAL_POOL')
    out['prediction_qualified']=out.prediction.notna();out['model_id']=model_id;out['native_model_id']=ALIAS.get(model_id,model_id)
    out['target_horizon']=horizon;out['joint_horizon']=5;out['year']=year;out['reuse_tuple_sha256']=fitted.receipt['reuse_tuple_sha256']
    output.parent.mkdir(parents=True,exist_ok=True);out.to_parquet(output,index=False)
    r=dict(status='PUBLISHED',path=str(output),sha256=values.sha(output),frame_sha256=frame_sha,key_sha256=key_sha,
        model_id=model_id,year=year,horizon=horizon,joint_horizon=5,rows=len(out),unavailable_rows=int((~out.prediction_qualified).sum()),
        model_sha256=fitted.receipt['model_sha256'],fit_receipt_path=fitted.receipt['receipt_path'],fit_receipt_sha256=values.sha(fitted.receipt['receipt_path']),
        reuse_tuple_sha256=fitted.receipt['reuse_tuple_sha256'],source_pins=frozen['source_pins'],test_2026_rows_read=0)
    write_json_atomic(rp,r);return r


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--model',required=True);p.add_argument('--year',type=int,required=True);p.add_argument('--horizon',type=int,default=5)
    a=p.parse_args(argv);result=predict_one(a.run,a.model,a.year,a.horizon) if a.year<2026 else fit_one(a.run,a.model,a.year,a.horizon)
    print(json.dumps(result.receipt if isinstance(result,ConsensusPredictor) else result,ensure_ascii=False))


if __name__=='__main__':main()
