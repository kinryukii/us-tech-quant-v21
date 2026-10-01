"""Past-OOF value fusion around retained native Fusion; no selector or account fit.

Only the input reader reads qualified labels/vectors. Frozen expert files contain
MODEL_OOF predictions, not same-fit training predictions. All physical fits use
the value worker ACK protocol and the sole run FIT_LOG.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import importlib, json, sys, warnings
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import nnls
from threadpoolctl import threadpool_limits
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic
from scripts.research.a2.training import stateful_values as values
from scripts.research.a2.training.stateful_inputs import InputReader, FEATURES, ALLOWED_SOURCES, LABEL

SEED=20260928
NATIVE=values.REPO/'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/fusion_models.py'
COMMON=NATIVE.with_name('common.py')
METHODS={32:'equal',33:'median',34:'fixed_weight',35:'nnls',36:'convex',37:'stack_ridge',38:'stack_elastic',39:'stack_hgb',40:'stack_mlp',41:'gate_linear',42:'gate_mlp',43:'residual_first_hgb',44:'residual_last_ridge'}
FIXED_WEIGHTS=np.array([.5,.25,.25])

def method_name(method):
    if isinstance(method,str) and method in METHODS.values():return method
    try:key=int(str(method).lstrip('M'))
    except ValueError as exc:raise ValueError('UNREGISTERED_FUSION_METHOD') from exc
    if key not in METHODS:raise ValueError('UNREGISTERED_FUSION_METHOD')
    return METHODS[key]

def packet_for(method):
    return ('ridge','lgb','hgb') if method_name(method)=='residual_last_ridge' else ('ridge','hgb','lgb')

def fixed_prediction(method,x):
    x=np.asarray(x,float)
    if x.ndim!=2 or x.shape[1]!=3 or not np.isfinite(x).all():raise ValueError('INVALID_THREE_EXPERT_PACKET')
    method=method_name(method)
    if method=='equal':return x.mean(axis=1)
    if method=='median':return np.median(x,axis=1)
    if method=='fixed_weight':return x@FIXED_WEIGHTS
    raise ValueError('FUSION_REQUIRES_FITTED_MODEL')

def meta_eligible(frame,cutoff):
    """Apply information clocks before touching target/prediction numeric cells."""
    cutoff=pd.Timestamp(cutoff)
    signal=pd.to_datetime(frame.signal_date);mature=pd.to_datetime(frame.label_mature_date)
    if frame.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_META_KEYS')
    usable=values._bool(frame.feature_available,'feature_available') & values._bool(frame.label_available,'label_available') & ~values._bool(frame.account_event_unhandled,'account_event_unhandled')
    usable &= signal.lt(cutoff) & mature.lt(cutoff)
    if not frame.loc[usable,'feature_source'].isin(ALLOWED_SOURCES).all() or not frame.loc[usable,'label_coordinate'].eq(LABEL).all():raise ValueError('UNQUALIFIED_META_SOURCE_OR_TARGET')
    return frame.loc[usable].copy()

def _native(dependencies=()):
    values._native(dependencies)
    saved=list(sys.path);old_common=sys.modules.get('common')
    try:
        common=importlib.import_module('scripts.research.a2.retained.a2_predict_then_optimize_20260928_r1.common')
        sys.modules['common']=common
        return importlib.import_module('scripts.research.a2.retained.a2_predict_then_optimize_20260928_r1.fusion_models')
    finally:
        sys.path[:]=saved
        if old_common is None:sys.modules.pop('common',None)
        else:sys.modules['common']=old_common

@contextmanager
def _native_starts(native,started):
    """Observe actual native fit starts without persisting wrappers in objects."""
    originals={}
    def constructor(original,component):
        def make(*args,**kwargs):
            obj=original(*args,**kwargs);bound=obj.fit
            def fit(*a,**kw):
                started(component);delattr(obj,'fit')
                return bound(*a,**kw)
            obj.fit=fit
            return obj
        return make
    for name in ('StandardScaler','Ridge','ElasticNet','HistGradientBoostingRegressor','MLPRegressor'):
        originals[name]=getattr(native,name)
        setattr(native,name,constructor(originals[name],'FUSION_SCALER' if name=='StandardScaler' else 'FUSION_PREDICTOR'))
    originals['Gate']=native.Gate
    def gate(*args,**kwargs):
        obj=originals['Gate'](*args,**kwargs);bound=obj.forward
        def forward(*a,**kw):
            started('FUSION_GATE');delattr(obj,'forward')
            return bound(*a,**kw)
        obj.forward=forward
        return obj
    native.Gate=gate
    originals['minimize']=native.minimize
    def minimize(*a,**kw):
        started('FUSION_SIMPLEX');return originals['minimize'](*a,**kw)
    native.minimize=minimize
    try:yield
    finally:
        for name,original in originals.items():setattr(native,name,original)

@dataclass
class FixedFusion:
    method:str
    weights:np.ndarray|None=None
    def predict(self,x,state):
        return np.asarray(x,float)@self.weights if self.weights is not None else fixed_prediction(self.method,x)

def _fit_arrays(method,x,y,state,weights,started,dependencies=()):
    method=method_name(method);x=np.asarray(x,float);y=np.asarray(y,float)
    if x.shape!=(len(y),3) or len(y)<2 or not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('INVALID_PAST_OOF_TRAINING_PACKET')
    if method in ('equal','median','fixed_weight'):return FixedFusion(method)
    if method=='nnls':
        started('FUSION_NNLS');coef=nnls(x,y)[0]
        if not np.isfinite(coef).all() or coef.sum()<=0:raise ValueError('NNLS_ZERO_OR_INVALID_SUM_NO_SUBSTITUTE')
        return FixedFusion(method,coef/coef.sum())
    state=np.asarray(state,float);weights=np.asarray(weights,float)
    if state.shape!=(len(y),4) or not np.isfinite(state).all() or weights.shape!=(len(y),) or not np.isfinite(weights).all() or np.any(weights<=0):raise ValueError('INVALID_FUSION_STATE_OR_WEIGHTS')
    native=_native(dependencies)
    with _native_starts(native,started):return native.Fusion(method,seed=SEED).fit(x,y,state,weights)

def _fusion_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
    def started(component):
        pipe.send(('FIT_START',component))
        if pipe.recv() is not True:raise RuntimeError('PARENT_REJECTED_FIT_BUDGET')
    try:
        with threadpool_limits(limits=1),warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            model=_fit_arrays(model_id,x,y,dates,quantile,started,dependencies)
        records=[dict(category=w.category.__name__,message=str(w.message)) for w in caught]
        fixed_epochs_completed=False
        if model_id=='stack_mlp':
            fixed_epochs_completed=getattr(model.model.steps[-1][1],'n_iter_',None)==40
            if not fixed_epochs_completed:raise RuntimeError('NATIVE_FUSION_MLP_FIXED40_NOT_COMPLETED')
        if any(w['category']=='ConvergenceWarning' for w in records) and not fixed_epochs_completed:raise RuntimeError('UNRESOLVED_FUSION_CONVERGENCE_NO_RETRY')
        pipe.send(('RESULT',model,dict(warnings=records,native_method=model_id,target_clip='NONE',fixed_epochs_completed=fixed_epochs_completed)))
    except BaseException as exc:pipe.send(('ERROR',type(exc).__name__,str(exc)))
    finally:pipe.close()

def frozen_contract(run,method,year):
    run=Path(run).resolve();assert_write_path(run/'models/fusion','backtest')
    config=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'));auth=config.get('fusion_training',{})
    if config.get('strategy_version')!='V24' or config.get('training_cutoff_exclusive')!='2026-01-01' or year not in (2023,2024,2025):raise ValueError('FUSION_RUN_OR_ANNUAL_BOUNDARY')
    allowed=[method_name(m) for m in auth.get('methods',[])]
    if auth.get('status')!='FROZEN' or auth.get('seed')!=SEED or method not in allowed or year not in auth.get('years',[]):raise ValueError('FUSION_NOT_IN_FROZEN_PLAN')
    pins=dict(module_sha256=values.sha(__file__),native_source_sha256=values.sha(NATIVE),native_common_sha256=values.sha(COMMON),input_reader_sha256=values.sha(values.READER_SOURCE),value_module_sha256=values.sha(values.__file__),input_manifest_sha256=values.sha(run/'input_manifest.json'))
    if any(auth.get(k)!=v for k,v in pins.items()):raise ValueError('FUSION_FROZEN_SOURCE_OR_INPUT_CHANGED')
    if auth.get('fit_timeout_seconds')!=1800 or config.get('prior_cumulative_fit_units')!=18 or any(type(auth.get(k)) is not int or auth[k]<1 for k in ('max_fit_units','max_model_year_attempts')):raise ValueError('FUSION_FINITE_BUDGET_OR_TIMEOUT_REQUIRED')
    return run,config,auth,pins

def _expert_oof(run,auth,model,year):
    pins=[p for p in auth.get('expert_oof',[]) if p['model_id']==model and p['year']==year]
    if len(pins)!=1:raise ValueError('ONE_FROZEN_EXPERT_OOF_PIN_REQUIRED')
    pin=pins[0];path=Path(pin['path']).resolve();receipt_path=Path(pin['receipt_path']).resolve();model_path=Path(pin['model_path']).resolve()
    if path!=run/'predictions/value'/model/f'{year}.parquet' or receipt_path!=run/'models/value'/model/str(year)/'fit_receipt.json' or model_path!=run/'models/value'/model/str(year)/'model.joblib':raise ValueError('CANONICAL_EXPERT_PATH_REQUIRED')
    if any(values.sha(p)!=pin[k] for p,k in ((path,'sha256'),(receipt_path,'receipt_sha256'),(model_path,'model_sha256'))):raise ValueError('FROZEN_EXPERT_BYTES_CHANGED')
    publication_path=path.with_suffix('.receipt.json')
    if values.sha(publication_path)!=pin['prediction_receipt_sha256']:raise ValueError('FROZEN_EXPERT_PUBLICATION_CHANGED')
    publication=json.loads(publication_path.read_text(encoding='utf-8'))
    if publication.get('status')!='PUBLISHED' or publication.get('sha256')!=pin['sha256'] or publication.get('model_sha256')!=pin['model_sha256'] or publication.get('fit_receipt_sha256')!=pin['receipt_sha256'] or publication.get('producer_source_sha256')!=auth['value_module_sha256'] or publication.get('input_manifest_sha256')!=auth['input_manifest_sha256'] or publication.get('year')!=year or publication.get('model_id')!=model or publication.get('test_2026_rows_read')!=0:raise ValueError('UNQUALIFIED_EXPERT_OOF_PUBLICATION')
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    if publication.get('reuse_tuple_sha256')!=receipt.get('reuse_tuple_sha256'):raise ValueError('EXPERT_PUBLICATION_TUPLE_MISMATCH')
    if receipt.get('status') not in ('TRAINED','EXACT_REUSED') or receipt.get('model_id')!=model or receipt.get('year')!=year or receipt.get('scientific_target_qualified') is not True or receipt.get('scientific_feature_pit_qualified') is not True or receipt.get('model_sha256')!=pin['model_sha256']:raise ValueError('UNQUALIFIED_EXPERT_RECEIPT')
    tup=receipt.get('reuse_tuple',{})
    if pd.Timestamp(tup.get('cutoff_exclusive'))!=pd.Timestamp(f'{year}-01-01') or tup.get('label_definition')!=LABEL:raise ValueError('EXPERT_IS_NOT_ITS_ANNUAL_PAST_MODEL_OOF')
    producer=tup.get('source_pins',{})
    expected=dict(module_sha256=auth['value_module_sha256'],input_reader_sha256=auth['input_reader_sha256'],input_manifest_sha256=auth['input_manifest_sha256'],native_source_sha256=values.sha(values.NATIVE))
    if any(producer.get(k)!=v for k,v in expected.items()):raise ValueError('EXPERT_PRODUCER_NOT_CURRENT_FROZEN_VALUE_SOURCE')
    trainmax=pd.Timestamp(receipt.get('train_label_maturity_max'));calmax=pd.Timestamp(receipt.get('calibration_label_maturity_max'));traincut=pd.Timestamp(tup['training_signal_and_label_maturity_exclusive'])
    if pd.isna(trainmax) or pd.isna(calmax) or pd.isna(traincut) or trainmax>=traincut or calmax>=pd.Timestamp(f'{year}-01-01'):raise ValueError('EXPERT_LABEL_MATURITY_NOT_PAST')
    pf=pq.ParquetFile(path)
    date_index=pf.schema_arrow.names.index('signal_date')
    for i in range(pf.num_row_groups):
        st=pf.metadata.row_group(i).column(date_index).statistics
        if not st or not st.has_min_max or pd.Timestamp(st.min)<pd.Timestamp(f'{year}-01-01') or pd.Timestamp(st.max)>=pd.Timestamp(f'{year+1}-01-01') or pd.Timestamp(st.max)>=pd.Timestamp('2026-01-01'):raise ValueError('EXPERT_PHYSICAL_DATE_BOUNDARY')
    required={'signal_date','ticker','prediction','prediction_qualified','year','model_id','model_sha256'}
    if not required.issubset(pf.schema_arrow.names):raise ValueError('EXPERT_OOF_SCHEMA')
    # Guard clocks and provenance before loading any prediction numeric column.
    flags=pd.read_parquet(path,columns=list(required-{'prediction'}))
    dates=pd.to_datetime(flags.signal_date)
    if flags.duplicated(['signal_date','ticker']).any() or not (dates.ge(f'{year}-01-01')&dates.lt(f'{year+1}-01-01')&dates.lt('2026-01-01')).all() or not flags.year.eq(year).all() or not flags.model_id.eq(model).all() or not flags.model_sha256.eq(pin['model_sha256']).all():raise ValueError('EXPERT_OOF_KEYS_TIME_OR_MODEL_LINEAGE')
    available=values._bool(flags.prediction_qualified,'prediction_qualified')
    vector=pd.read_parquet(path,columns=['signal_date','ticker','prediction'],filters=[('prediction_qualified','==',True)])
    expected=flags.loc[available,['signal_date','ticker']].sort_values(['signal_date','ticker']).reset_index(drop=True)
    if not vector[['signal_date','ticker']].sort_values(['signal_date','ticker']).reset_index(drop=True).equals(expected) or not np.isfinite(vector.prediction).all():raise ValueError('EXPERT_QUALIFIED_VECTOR_KEYS_OR_VALUES')
    out=flags[['signal_date','ticker']].merge(vector,on=['signal_date','ticker'],how='left',sort=False,validate='one_to_one')
    out['signal_date']=pd.to_datetime(out.signal_date)
    return out.rename(columns={'prediction':'expert_'+model})

def join_packet(base,expert_frames,packet,require_complete=False):
    result=base.copy();keys=base[['signal_date','ticker']].reset_index(drop=True)
    for model in packet:
        frame=expert_frames[model]
        if frame.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_EXPERT_KEYS')
        result=result.merge(frame[['signal_date','ticker','expert_'+model]],on=['signal_date','ticker'],how='left',sort=False,validate='one_to_one')
    if not result[['signal_date','ticker']].reset_index(drop=True).equals(keys):raise ValueError('FUSION_POOL_KEYS_DROPPED_OR_REORDERED')
    x=result[['expert_'+m for m in packet]].to_numpy(float)
    if np.isinf(x).any() or (require_complete and not np.isfinite(x).all()):raise ValueError('INCOMPLETE_REQUIRED_PAST_OOF_PACKET_NO_SILENT_ROW_DROP')
    return result,x

def _state(frame,x):
    return _native(()).state_features(frame,x)

def state_required(method):
    return method.startswith('gate_') or method.startswith('residual_')

def state_surface(frame,x):
    # This frame is the full inference pool, never a label-filtered training subset.
    valid=values._bool(frame.feature_available,'feature_available').to_numpy() & np.isfinite(x).all(axis=1)
    out=frame[['signal_date','ticker']].copy()
    for i in range(4):out['state_'+str(i)]=np.nan
    if valid.any():out.loc[valid,['state_'+str(i) for i in range(4)]]=_state(frame.loc[valid],x[valid])
    return out

def join_state(rows,surface):
    result=rows[['signal_date','ticker']].merge(surface,on=['signal_date','ticker'],how='left',sort=False,validate='one_to_one')
    if not result[['signal_date','ticker']].equals(rows[['signal_date','ticker']].reset_index(drop=True)):raise ValueError('STATE_KEYS_CHANGED')
    state=result[['state_'+str(i) for i in range(4)]].to_numpy(float)
    if not np.isfinite(state).all():raise ValueError('MISSING_PREDECISION_FUSION_STATE')
    return state

def past_state_surface(reader,experts,packet,years):
    surfaces=[]
    for year in years:
        inference=reader.read_inference(year)
        full,x=join_packet(inference,experts,packet)
        surfaces.append(state_surface(full,x))
    return pd.concat(surfaces,ignore_index=True)

@dataclass
class FusionFit:
    native:object
    sigma:float
    receipt:dict
    auth:dict
    run:Path
    def predict(self,frame,reader=None):
        method=self.receipt['model_id'];year=self.receipt['year'];packet=packet_for(method)
        _,_,current_auth,pins=frozen_contract(self.run,method,year)
        if pins!=self.receipt['reuse_tuple']['source_pins']:raise ValueError('FUSION_INFERENCE_SOURCE_CHANGED')
        dates=pd.to_datetime(frame.signal_date)
        if not (dates.ge(f'{year}-01-01')&dates.lt(f'{year+1}-01-01')).all():raise ValueError('FUSION_INFERENCE_YEAR')
        previous=[p for p in current_auth['expert_oof'] if p['year']<year]
        if previous!=self.receipt['reuse_tuple']['expert_oof_pins']:raise ValueError('PAST_EXPERT_PUBLICATION_PINS_CHANGED')
        experts={m:_expert_oof(self.run,current_auth,m,year) for m in packet}
        joined,x=join_packet(frame,experts,packet)
        valid=values._bool(frame.feature_available,'feature_available').to_numpy()&np.isfinite(x).all(axis=1)
        if not frame.loc[valid,'feature_source'].isin(ALLOWED_SOURCES).all():raise ValueError('FUSION_INFERENCE_SOURCE')
        out=frame[['signal_date','ticker']].copy();out['prediction']=np.nan;out['value_sigma']=np.nan
        if valid.any():
            state=join_state(joined.loc[valid].reset_index(drop=True),state_surface(joined,x)) if state_required(method) else np.zeros((int(valid.sum()),4))
            if not np.isfinite(state).all():raise ValueError('NONFINITE_CURRENT_FUSION_STATE')
            mu=self.native.predict(x[valid],state)
            if not np.isfinite(mu).all():raise ValueError('NONFINITE_FUSION_PREDICTION')
            out.loc[valid,'prediction']=mu;out.loc[valid,'value_sigma']=self.sigma
        out['prediction_qualified']=valid;out['year']=year;out['model_id']=method
        out['model_sha256']=self.receipt['model_sha256'];out['model_reuse_tuple_sha256']=self.receipt['reuse_tuple_sha256'];out['prediction_role']='MODEL_OOF'
        return out

def fit_fusion(method,year,run,reader=None):
    method=method_name(method);run,config,auth,pins=frozen_contract(run,method,year)
    _assert_value_finished(run,config)
    if reader is None:reader=InputReader(run)
    elif type(reader) is not InputReader or reader.run!=run:raise ValueError('CANONICAL_INPUT_READER_REQUIRED')
    fold=reader.annual_fold(year);values.validate_fold(fold);packet=packet_for(method)
    prior_years=sorted(set(p['year'] for p in auth.get('expert_oof',[]) if 2021<=p['year']<year))
    if 2021 not in prior_years or 2022 not in prior_years:raise ValueError('EARLY_2021_2022_PACKET_OOF_REQUIRED')
    experts={m:pd.concat([_expert_oof(run,auth,m,y) for y in prior_years],ignore_index=True) for m in packet}
    train,cal=reader.read_training_fold(year)
    train=meta_eligible(train,fold['calibration_start']);cal=meta_eligible(cal,fold['cutoff_exclusive'])
    train=train.loc[pd.to_datetime(train.signal_date).dt.year.isin(prior_years)].reset_index(drop=True)
    cal=cal.loc[pd.to_datetime(cal.signal_date).isin(fold['calibration_sessions'])].reset_index(drop=True)
    train,x=join_packet(train,experts,packet,True);cal,cx=join_packet(cal,experts,packet,True)
    if len(train)<2 or len(cal)<2:raise ValueError('INSUFFICIENT_PAST_OOF_META_TRAIN_CAL')
    y=train.y_open5.to_numpy(float);cy=cal.y_open5.to_numpy(float)
    if not np.isfinite(y).all() or not np.isfinite(cy).all():raise ValueError('NONFINITE_MATURE_META_TARGET')
    _native(auth.get('dependency_paths',[]))
    if state_required(method):
        surface=past_state_surface(reader,experts,packet,prior_years)
        state=join_state(train,surface);cstate=join_state(cal,surface)
    else:state=np.zeros((len(train),4));cstate=np.zeros((len(cal),4))
    tuple_spec=dict(model_id=method,year=year,seed=SEED,packet=list(packet),fold='ANNUAL_'+str(year),role=values.ROLE,family='OOF_FUSION_'+method,feature_binding=values.feature_binding(),feature_binding_role='UNDERLYING_SOURCE32_NOT_FUSION_ESTIMATOR_INPUTS',model_input_columns=['expert_'+m for m in packet]+(['state_mean_ret20d','state_mean_realized_vol20d','state_breadth_price_vs_ma20_positive','state_expert_disagreement'] if state_required(method) else []),calendar_sha256=fold['calendar_sha256'],calibration_sessions=[d.isoformat() for d in fold['calibration_sessions']],training_signal_and_label_maturity_exclusive=fold['calibration_start'].isoformat(),calibration_label_maturity_exclusive=fold['cutoff_exclusive'].isoformat(),label_definition=LABEL,label_domain='INDIVIDUAL_ELIGIBLE_STOCK',source_pins=pins,expert_oof_pins=[p for p in auth['expert_oof'] if p['year']<year],training_keys_sha256=values.digest(train[['signal_date','ticker']].astype(str).values.tolist()),train_maturity_max=train.label_mature_date.max().isoformat(),cal_maturity_max=cal.label_mature_date.max().isoformat(),cutoff_exclusive=fold['cutoff_exclusive'].isoformat(),calibration_start=fold['calibration_start'].isoformat(),weights='UNIFORM_QUALIFIED_ROWS',native_uncertainty_used=False,target_clip='NONE')
    tuple_sha=values.digest(tuple_spec);slot=run/'models/fusion'/method/str(year);rp=slot/'fit_receipt.json';mp=slot/'model.joblib'
    if rp.exists():
        receipt=json.loads(rp.read_text(encoding='utf-8'))
        if receipt.get('status')!='TRAINED' or receipt.get('reuse_tuple_sha256')!=tuple_sha or values.sha(mp)!=receipt.get('model_sha256'):raise RuntimeError('EXISTING_FUSION_SLOT_NO_SILENT_RETRY')
        result=joblib.load(mp);result.receipt=receipt;return result
    log=run/'FIT_LOG.jsonl';events=values._events(log);attempts=[e for e in events if e.get('event')=='MODEL_YEAR_ATTEMPT_STARTED']
    if any(e.get('model_id')==method and e.get('year')==year for e in attempts) or len(attempts)>=auth['max_model_year_attempts']:raise RuntimeError('FUSION_ATTEMPT_BUDGET_OR_EXISTING_ATTEMPT')
    slot.mkdir(parents=True,exist_ok=True);values._append(log,dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id=method,year=year,reuse_tuple_sha256=tuple_sha))
    receipt=dict(status='RUNNING',model_id=method,year=year,role=values.ROLE,seed=SEED,reuse_tuple=tuple_spec,reuse_tuple_sha256=tuple_sha,scientific_target_qualified=True,scientific_feature_pit_qualified=True,training_rows=len(train),calibration_rows=len(cal),train_label_maturity_max=train.label_mature_date.max().isoformat(),calibration_label_maturity_max=cal.label_mature_date.max().isoformat(),fit_units=0,receipt_path=str(rp),model_path=str(mp),native_insample_diagnostics={'residual_scale':'NOT_USED_FOR_CALIBRATION_OR_POLICY_OR_SELECTION','training_mse':'NOT_USED_FOR_CALIBRATION_OR_POLICY_OR_SELECTION'},uncertainty_authority='ONLY_CHRONOLOGICAL_PAST60_HELDOUT_SIGMA',fusion_rule_kind='FIXED_NONFITTED_COMBINATION' if method in ('equal','median','fixed_weight') else 'LEARNED_ONLY_PAST_MODEL_OOF')
    write_json_atomic(rp,receipt)
    try:
        if method in ('equal','median','fixed_weight'):model=FixedFusion(method)
        else:model=values._fit_job('fusion',method,x,y,state,np.ones(len(y)),auth.get('dependency_paths',[]),list(FEATURES),None,log=log,auth=auth,prior=config['prior_cumulative_fit_units'],year=year,tuple_sha=tuple_sha,receipt=receipt,worker_target=_fusion_worker)
        raw=model.predict(cx,cstate)
        values._component_start(log,auth,config['prior_cumulative_fit_units'],method,year,'HELDOUT_RESIDUAL_SIGMA',tuple_sha);receipt['fit_units']+=1;write_json_atomic(rp,receipt)
        sigma=values.heldout_calibration('ridge',raw,cy)['sigma']
        frozen_contract(run,method,year)
        receipt.update(status='TRAINED',sigma=sigma,uncertainty='CHRONOLOGICAL_HELDOUT_RESIDUAL_SAMPLE_STD_DDOF_1_ONCE')
        result=FusionFit(model,sigma,receipt,auth,run);joblib.dump(result,mp);receipt['model_sha256']=values.sha(mp);write_json_atomic(rp,receipt)
        values._append(log,dict(event='MODEL_YEAR_COMPLETE',model_id=method,year=year,status='TRAINED',fit_units=receipt['fit_units'],reuse_tuple_sha256=tuple_sha,model_sha256=receipt['model_sha256']))
        return result
    except BaseException as exc:
        receipt.update(status='FAILED',failure=dict(type=type(exc).__name__,message=str(exc)));write_json_atomic(rp,receipt)
        values._append(log,dict(event='MODEL_YEAR_FAILED',model_id=method,year=year,fit_units=receipt['fit_units'],failure=receipt['failure']));raise


def publish_prediction(fitted,reader):
    method=fitted.receipt['model_id'];year=fitted.receipt['year']
    output=fitted.run/'predictions/fusion'/method/f'{year}.parquet';rp=output.with_suffix('.receipt.json')
    assert_write_path(output,'backtest');output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        old=json.loads(rp.read_text(encoding='utf-8'))
        if old.get('status')!='PUBLISHED' or old.get('sha256')!=values.sha(output) or old.get('reuse_tuple_sha256')!=fitted.receipt['reuse_tuple_sha256'] or old.get('fit_receipt_sha256')!=values.sha(fitted.receipt['receipt_path']) or old.get('producer_source_sha256')!=values.sha(__file__):raise RuntimeError('EXISTING_FUSION_OOF_PUBLICATION_CHANGED')
        return old
    predictions=fitted.predict(reader.read_inference(year),reader)
    predictions.to_parquet(output,index=False)
    published=dict(status='PUBLISHED',prediction_role='MODEL_OOF',path=str(output),sha256=values.sha(output),year=year,model_id=method,rows=len(predictions),qualified_rows=int(predictions.prediction_qualified.sum()),unavailable_rows=int((~predictions.prediction_qualified).sum()),reuse_tuple_sha256=fitted.receipt['reuse_tuple_sha256'],model_sha256=fitted.receipt['model_sha256'],fit_receipt_path=fitted.receipt['receipt_path'],fit_receipt_sha256=values.sha(fitted.receipt['receipt_path']),producer_source_sha256=values.sha(__file__),input_manifest_sha256=values.sha(fitted.run/'input_manifest.json'),native_insample_diagnostics='NEVER_CALIBRATION_OR_POLICY_OR_SELECTION',numeric_economic_performance_reported=False,test_2026_rows_read=0)
    write_json_atomic(rp,published);return published

def validate_value_batch_complete(config,progress):
    schedule=config.get('value_training',{}).get('ordered_schedule',[])
    expected={(p['model_id'],p['year']) for p in schedule}
    slots=progress.get('slots',[]);actual={(p['model_id'],p['year']) for p in slots}
    if len(schedule)!=93 or len(expected)!=93 or progress.get('status')!='ATTEMPTS_FINISHED' or progress.get('expected_slots')!=93 or len(slots)!=93 or actual!=expected or any(p.get('status') not in ('TRAINED','EXACT_REUSED','FAILED','NOT_ATTEMPTED_COMMON_BLOCK') for p in slots):raise RuntimeError('VALUE_BATCH_NOT_FINISHED_NO_SHARED_FIT_LOG_RACE')

def _assert_value_finished(run,config):
    progress=json.loads((run/'logs/value_batch_status.json').read_text(encoding='utf-8'))
    validate_value_batch_complete(config,progress)
    events=values._events(run/'FIT_LOG.jsonl')
    starts={(e['model_id'],e['year']) for e in events if e.get('event')=='MODEL_YEAR_ATTEMPT_STARTED'}
    finished={(e['model_id'],e['year']) for e in events if e.get('event') in ('MODEL_YEAR_COMPLETE','MODEL_YEAR_FAILED')}
    if starts-finished:raise RuntimeError('A_MODEL_ATTEMPT_STILL_RUNNING_NO_SHARED_LOG_RACE')

def run_batch(run):
    run=Path(run).resolve();config=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'));auth=config.get('fusion_training',{})
    schedule=auth.get('ordered_schedule',[])
    expected={(method_name(m),y) for m in auth.get('methods',[]) for y in auth.get('years',[])}
    actual={(method_name(p['model_id']),p['year']) for p in schedule}
    if len(schedule)!=39 or len(actual)!=39 or len(expected)!=39 or actual!=expected:raise ValueError('EXACT_FROZEN_13_FUSIONS_X3_YEARS_REQUIRED')
    for item in schedule:frozen_contract(run,method_name(item['model_id']),item['year'])
    _assert_value_finished(run,config)
    progress=run/'logs/fusion_batch_status.json';assert_write_path(progress,'backtest')
    if progress.exists():raise RuntimeError('EXISTING_FUSION_BATCH_AUDIT_NO_SILENT_RESTART')
    statuses=[];reader=InputReader(run)
    for item in schedule:
        method=method_name(item['model_id']);year=item['year']
        try:
            fit=fit_fusion(method,year,run,reader);published=publish_prediction(fit,reader)
            status=dict(model_id=method,year=year,status='TRAINED',fit_units=fit.receipt['fit_units'],prediction_receipt=str(Path(published['path']).with_suffix('.receipt.json')))
        except Exception as exc:
            # Preflight/missing expert ERROR is an identified attempted slot, never trained.
            units=sum(e.get('fit_units',0) for e in values._events(run/'FIT_LOG.jsonl') if e.get('event')=='FIT_STARTED' and e.get('model_id')==method and e.get('year')==year)
            status=dict(model_id=method,year=year,status='ERROR',fit_units=units,failure={'type':type(exc).__name__,'message':str(exc)})
        statuses.append(status)
        write_json_atomic(progress,dict(status='RUNNING' if len(statuses)<39 else 'ATTEMPTS_FINISHED',expected_slots=39,slots=statuses,error_slots=sum(p['status']=='ERROR' for p in statuses),fit_log='FIT_LOG.jsonl_SOLE_AUTHORITY',prior_fit_units=18,numeric_economic_performance_reported=False,test_2026_rows_read=0))
        print(json.dumps(status,sort_keys=True),flush=True)
        if status['status']=='ERROR' and ('BUDGET_EXHAUSTED' in status['failure']['message'] or 'FROZEN_SOURCE_OR_INPUT_CHANGED' in status['failure']['message']):break
    return statuses

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--method')
    parser.add_argument('--year',type=int)
    parser.add_argument('--predict',action='store_true')
    parser.add_argument('--batch',action='store_true')
    args=parser.parse_args(argv)
    if args.batch:
        if args.method is not None or args.year is not None:parser.error('batch uses only the frozen ordered_schedule')
        run_batch(args.run_dir);return 0
    if args.method is None or args.year is None:parser.error('method and year are required outside batch')
    config=json.loads((args.run_dir/'run_config.json').read_text(encoding='utf-8-sig'));_assert_value_finished(args.run_dir.resolve(),config)
    reader=InputReader(args.run_dir);fitted=fit_fusion(args.method,args.year,args.run_dir,reader)
    if args.predict:publish_prediction(fitted,reader)
    print(json.dumps({k:fitted.receipt[k] for k in ('status','model_id','year','fit_units','model_path')},sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
