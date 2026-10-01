"""Frozen inference on full available candidate contexts, not old TOP20."""
import argparse,time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from shared import *
from market_runtime import prepare_market
from predictors import predict_raw
from train_predictors import output_columns
from train_cooperation import apply_calibration,CooperationRuntime
from calibration_fusion import SPEC as FUSION_SPEC,inputs as calibration_inputs
from risk_models import RiskRuntime

def apply_available_calibrators(raw,period):
    status=read_json(ROOT/'models'/f'calibration_{period}'/'STATUS.json')
    result=raw[['signal_date','ticker']].copy()
    for record in status['records']:
        name=record['name'];mu=np.full(len(raw),np.nan);uncertainty=mu.copy();p=mu.copy()
        if record['status']=='TRAINED':
            artifact=Path(record['artifact'])
            if sha(artifact)!=record['artifact_sha256']:raise RuntimeError('FROZEN_CALIBRATOR_CHANGED')
            valid=np.isfinite(calibration_inputs(raw,name)).all(axis=1)
            if valid.any():
                model=joblib.load(artifact);value,scale,probability=model.predict(raw.loc[valid])
                mu[valid]=value;uncertainty[valid]=scale
                if probability is not None:p[valid]=probability
        result[name+'__mu']=mu;result[name+'__uncertainty']=uncertainty
        if name in PROB:result[name+'__calibrated_p']=p
    return result

def make_predictions(year):
    if year==2026:
        from freeze_batch import verify_freeze
        verify_freeze()
    out=ROOT/'predictions'/f'evaluation_{year}';out.mkdir(exist_ok=True,parents=True)
    if (out/'COMPLETE.json').exists():
        receipt=read_json(out/'COMPLETE.json')
        for name,expected in receipt['artifacts'].items():
            if sha(out/name)!=expected:raise RuntimeError('EVALUATION_PREDICTIONS_CHANGED')
        return receipt
    stage='validation' if year==2025 else 'final'
    prepared=prepare_market(year);frame=prepared.panel.copy()
    frame=frame.loc[frame.runtime_input_usable].reset_index(drop=True)
    x=frame[FEATURES].to_numpy(float);dates=frame.signal_date.to_numpy()
    result=frame[['signal_date','ticker']].copy()
    status=read_json(ROOT/'models'/stage/'FIT_STATUS.json');failures={}
    if not status.get('complete') or len(status['fits'])!=31:raise RuntimeError('ALL_DECLARED_BASE_FITS_MUST_RESOLVE')
    binding={name:sha(ROOT/name) for name in ['evaluation_predictions.py','shared.py','calibration_fusion.py','train_cooperation.py','risk_models.py','market_runtime.py']}
    for r in status['fits']:
        name=r['name']
        if r['status']=='TRAINED':
            if sha(r['artifact'])!=r['artifact_sha256']:raise RuntimeError('FROZEN_BASE_MODEL_CHANGED')
            with threadpool_limits(limits=2):raw=predict_raw(joblib.load(r['artifact']),x,dates)
            for key,value in raw.items():result[f'{name}__{key}']=value
        else:
            failures[name]=r.get('failure',r.get('error','BASE_FAILED'))
            for col in output_columns(name):result[f'{name}__{col}']=np.nan
    result.to_parquet(out/'raw.parquet',index=False)
    mu=apply_available_calibrators(result,'2025' if year==2025 else 'final');mu.to_parquet(out/'calibrated.parquet',index=False)
    cooperation=CooperationRuntime(stage)
    context=frame[FUSION_SPEC['context']].to_numpy(float)
    with threadpool_limits(limits=2):streams=cooperation.predict_streams(mu,context)
    d,n=len(prepared.market.dates),len(prepared.market.tickers)
    cube=np.full((d,len(cooperation.stream_ids),n),np.nan)
    ri=frame.signal_date.map(prepared.date_index).to_numpy(int);ci=frame.ticker.map(prepared.ticker_index).to_numpy(int)
    stream_records=[];stream_columns={'signal_date':frame.signal_date,'ticker':frame.ticker}
    for k,key in enumerate(cooperation.stream_ids):
        values=streams[key];cube[ri,k,ci]=values;stream_columns[key]=values
        stream_records.append({'stream_id':key,'status':'AVAILABLE' if np.isfinite(values).all() else 'FAILED_MEMBER_OR_CALIBRATION',
            'predictable_rows':int(np.isfinite(values).sum()),'candidate_context_rows':len(values),'failure':str(cooperation.failures.get(key,''))})
    pd.DataFrame(stream_columns).to_parquet(out/'streams.parquet',index=False)
    np.savez_compressed(out/'forecast_cube.npz',mu=cube,stream_ids=np.asarray(cooperation.stream_ids),
        dates=prepared.market.dates.to_numpy(),tickers=prepared.market.tickers)
    pd.DataFrame(stream_records).to_csv(out/'STREAM_COVERAGE.csv',index=False)
    # Every raw candidate remains represented, including the unavailable original keys.
    if year==2026:
        full=pd.read_parquet(ROOT/'data/full_candidate_availability.parquet')
        full=full.merge(result[['signal_date','ticker']].assign(prediction_context_materialized=True),
            on=['signal_date','ticker'],how='left',validate='one_to_one')
        full['prediction_context_materialized']=full.prediction_context_materialized.fillna(False)
        from market_runtime import KNOWN_INPUT_CONFLICTS
        conflict=np.asarray([(pd.Timestamp(d),str(t)) in KNOWN_INPUT_CONFLICTS
            for d,t in zip(full.signal_date,full.ticker)],bool)
        full['evaluation_known_conflict']=conflict
        full['evaluation_prediction_available']=full.prediction_context_materialized&~conflict
        full['evaluation_unavailable_reason']=np.where(conflict,'UNAVAILABLE_KNOWN_CONFLICT',
            np.where(full.prediction_context_materialized,'','ORIGINAL_CONTEXT_UNAVAILABLE'))
        full.to_parquet(out/'ALL_ORIGINAL_CANDIDATE_PREDICTION_COVERAGE.parquet',index=False)
    risk=RiskRuntime(joblib.load(ROOT/'models'/f'risk_{stage}.joblib'),prepared.market.tickers)
    scales=np.zeros((d,len(RISKS),n))
    for i,date in enumerate(prepared.market.dates):
        if prepared.market.signal_mask[i]:risk.prepare_day(date,prepared.features[i])
        for r,name in enumerate(RISKS):scales[i,r]=risk.scales.get(name,risk.sigma) if hasattr(risk,'scales') else risk.sigma
    cache={'scales':scales,'dates':prepared.market.dates.to_numpy(),'tickers':prepared.market.tickers}
    for key,r in risk.correlations.items():cache['corr_'+key]=r;cache['scenario_'+key]=risk.scenarios[key]
    np.savez_compressed(out/'risk_cache.npz',**cache)
    receipt={'status':'COMPLETE','year':year,'stage':stage,'fit_2026_rows':0,'fit_calls':0,
        'original_pool_formal_status':'BLOCKED_DATA' if year==2026 else 'HISTORICAL_INPUT_LIMITATIONS',
        'context_rows':len(frame),'old_A2_top20_filter':False,'base_failures':failures,'streams':stream_records,
        'source_binding':binding,'artifacts':{p.name:sha(p) for p in out.iterdir() if p.is_file()},
        'risk_filter_note':'frozen coefficients with decision-time historical inputs; no parameter refitting',
        'old_batch_unchanged':True,'blind_test':False}
    write_json(out/'COMPLETE.json',receipt)
    if year==2026:
        from freeze_batch import verify_freeze
        verify_freeze()
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,required=True,choices=[2025,2026]);a=parser.parse_args()
    from run_suite import forbidden_fit_guard
    t=time.monotonic();restore_guard=forbidden_fit_guard()
    try:receipt=make_predictions(a.year)
    finally:restore_guard()
    print(a.year,receipt['status'],round(time.monotonic()-t,2),flush=True)
