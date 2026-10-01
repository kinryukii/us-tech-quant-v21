"""Annual static63 PIT return-risk adapter; shared estimators and one fit ledger.
Only this binding and worker start callbacks are new. No covariance implementation,
account engine, selection rule, or market-data acquisition is duplicated here.
"""
from __future__ import annotations
from contextlib import ExitStack
import argparse,hashlib,json
from pathlib import Path
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd
from sklearn import covariance as skcov,decomposition as skdec
from scripts.research.a2.risk import joint_risk_estimators as joint
from scripts.research.a2.training import stateful_values as values
from scripts.research.a2.training.stateful_inputs import InputReader,ALLOWED_SOURCES
from scripts.storage.storage_r2a import assert_write_path,write_json_atomic
JOINT_PATH=Path(joint.__file__)
JOINT_SHA='6ae94d300aa2fe2ded9fcb81548f2fb7b0c58c11a24aaed7db846b700a8aea97'
GARCH_PATH=JOINT_PATH.parents[1]/'retained/a2_pto_full_compat_20260928_r2/risk_models.py'
GARCH_SHA='eaec34d05750f1f7ee73c03367e759a8ce16ddc24928877545e693873b43f59e'
ROLE='RISK_STATIC_COVARIANCE'
UNIT='ACCEPTED_FROZEN_PIT32_RET_1D_PROXY_FRACTIONAL'
INDEX_DEF='equal_weight_current_Raw_pool_predecision_PIT_return_proxy'
YEARS=(2023,2024,2025)
METHODS=tuple(joint.CONFIGS)
_YEAR_INPUTS={}

def identity_frame(frame):
    return hashlib.sha256(pd.util.hash_pandas_object(frame,index=True).to_numpy(np.uint64).tobytes()).hexdigest()

def frozen_contract(run_dir,method,year):
    run=Path(run_dir).resolve();assert_write_path(run/'models/risk','backtest')
    cfg=json.loads((run/'run_config.json').read_text());auth=cfg.get('risk_training',{});method=joint.canonical_method(method)
    if cfg.get('strategy_version')!='V24' or cfg.get('training_cutoff_exclusive')!='2026-01-01' or not cfg.get('research_design',{}).get('risk_design_correction_before_first_fit'):
        raise ValueError('RISK_IDENTITY_OR_PREDECLARED_BOUNDARY')
    if auth.get('status')!='FROZEN' or method not in auth.get('methods',[]) or year not in YEARS or year not in auth.get('years',[]):
        raise ValueError('RISK_METHOD_YEAR_NOT_FROZEN')
    pins=dict(module_sha256=values.sha(__file__),joint_source_sha256=values.sha(JOINT_PATH),values_module_sha256=values.sha(values.__file__),input_reader_sha256=values.sha(values.READER_SOURCE),input_manifest_sha256=values.sha(run/'input_manifest.json'),garch_definition_source_sha256=values.sha(GARCH_PATH))
    if pins['joint_source_sha256']!=JOINT_SHA or pins['garch_definition_source_sha256']!=GARCH_SHA or any(auth.get(k)!=z for k,z in pins.items()):
        raise ValueError('RISK_FROZEN_SOURCE_OR_INPUT_CHANGED')
    expected={'lookback_sessions':63,'horizon_multiplier':5,'horizon_rule':'IID_5_X_STATIC_DAILY_COV','fit_timeout_seconds':1800,'budget_bucket':'risk_primary','max_new_bucket_fit_units':72,'max_fit_units':882,'max_model_year_attempts':201}
    if any(auth.get(k)!=z for k,z in expected.items()) or cfg.get('prior_cumulative_fit_units')!=18:
        raise ValueError('RISK_WINDOW_UNITS_OR_FINITE_BUDGET_CHANGED')
    from scripts.research.a2.training.stateful_fusion import _assert_value_finished,method_name
    _assert_value_finished(run,cfg)
    progress=json.loads((run/'logs/fusion_batch_status.json').read_text())
    expected=[(method_name(p['model_id']),p['year']) for p in cfg['fusion_training']['ordered_schedule']]
    actual=[(p['model_id'],p['year']) for p in progress.get('slots',[])]
    if len(expected)!=39 or len(set(expected))!=39 or actual!=expected or progress.get('status')!='ATTEMPTS_FINISHED' or progress.get('expected_slots')!=39 or any(p.get('status') not in ('TRAINED','FAILED','ERROR') for p in progress['slots']):
        raise ValueError('RISK_REQUIRES_EXACT_SERIAL_FUSION39_FINISHED')
    return run,cfg,auth,pins,method

def annual_inputs(reader,year):
    cutoff=pd.Timestamp(f'{year}-01-01');dates=pd.DatetimeIndex(reader.calendar[reader.calendar<cutoff][-63:])
    if len(dates)!=63 or dates.has_duplicates or not dates.is_monotonic_increasing:raise ValueError('RISK_REQUIRES_EXACT63_PRIOR_SESSIONS')
    keys=reader.train_flags;legal=keys.signal_date.lt(cutoff)&keys.feature_available&keys.feature_source.isin(ALLOWED_SOURCES)
    past=keys.loc[legal,['signal_date','ticker','feature_source']].sort_values(['signal_date','ticker'])
    names=tuple(sorted(past.ticker.astype(str).unique()))
    if not names:raise ValueError('RISK_NO_PRIOR_ACCEPTED_ELIGIBLE_KEYS')
    long=reader.read_return_history(names,dates[-1],lookback=63)
    if long.duplicated(['signal_date','ticker']).any() or not set(long.signal_date).issubset(set(dates)):raise ValueError('RISK_RETURN_KEYS_OR_DATES_CHANGED')
    long=long.copy();long.loc[~long.return_available,'ret_1d']=np.nan
    table=long.pivot(index='signal_date',columns='ticker',values='ret_1d').reindex(index=dates,columns=names)
    if np.isinf(table.to_numpy(float)).any():raise ValueError('RISK_INFINITE_RETURN')
    line=dict(assets=list(names),dates=[z.isoformat() for z in dates],cutoff_exclusive=cutoff.isoformat(),historical_eligible_keys_sha256=identity_frame(past),returns_sha256=identity_frame(table),source='InputReader.read_return_history:accepted_PIT32_ret_1d',return_unit=UNIT,return_horizon_sessions=1,labels_used=False,future_membership_used=False,window_sessions=63,annual_static=True,eligibility_upgraded=False)
    return table,line

def fixed_raw_index(reader,dates,cutoff,auth):
    if auth.get('single_index_definition')!=INDEX_DEF:raise ValueError('SINGLE_INDEX_DESIGN_CHANGED')
    prior=reader.pred_flags.loc[reader.pred_flags.signal_date.lt(cutoff)];last=prior.signal_date.max()
    day=prior.loc[prior.signal_date.eq(last)];names=tuple(sorted(day.loc[day.is_raw_top20,'ticker'].astype(str).unique()))
    if len(names)!=20 or not day.raw_top20_set_complete.all() or not day.raw_top20_set_count.eq(20).all():raise ValueError('BLOCKED_INPUT:LAST_PRIOR_RAW20_INCOMPLETE')
    long=reader.read_return_history(names,dates[-1],lookback=63)
    table=long.pivot(index='signal_date',columns='ticker',values='ret_1d').reindex(index=dates,columns=names);table=table.where(np.isfinite(table))
    counts=table.notna().sum(axis=1)
    if counts.eq(0).any():raise ValueError('BLOCKED_INPUT:FIXED_RAW20_INDEX_WHOLE_DATE_MISSING')
    market=table.mean(axis=1);market.attrs['source_id']=INDEX_DEF
    return market,dict(definition=INDEX_DEF,fixed_members=list(names),membership_signal_date=last.isoformat(),cutoff_exclusive=cutoff.isoformat(),observed_member_count_by_date=list(map(int,counts)),index_series_sha256=identity_frame(market),return_unit=UNIT,no_zero_fill=True,no_benchmark_fetch=True)

def risk_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
    method=joint.canonical_method(model_id.removeprefix('RISK::'));components=[];estimates=[]
    def started(name):
        pipe.send(('FIT_START','RISK::'+name))
        if pipe.recv() is not True:raise RuntimeError('PARENT_REJECTED_RISK_FIT_BUDGET')
        components.append(name)
    try:
        if values.sha(JOINT_PATH)!=JOINT_SHA or values.sha(GARCH_PATH)!=GARCH_SHA or values.sha(__file__)!=y['worker_source_sha256']:raise ValueError('RISK_WORKER_SOURCE_CHANGED')
        def wrap_fit(original,name):
            def fit(self,*a,**kw):started(name);return original(self,*a,**kw)
            return fit
        original_prepare,original_estimate,original_minimize=joint._prepare,joint._estimate,joint.minimize
        def prepare(*a,**kw):
            result=original_prepare(*a,**kw)
            if result[2] is not None:
                estimates.extend([dict(component='OBSERVED_COLUMN_MEAN',estimate_units=1),dict(component='MARGINAL_VARIANCE',estimate_units=1)])
            return result
        def estimate(*a,**kw):
            before=len(components);result=original_estimate(*a,**kw);analytical=int(result[2])-(len(components)-before)
            if analytical>0:estimates.append(dict(component='CANONICAL_'+str(a[0])+'_ANALYTICAL_STATE',estimate_units=analytical))
            return result
        def minimize(*a,**kw):started('SHARED_GARCH_MINIMIZE');return original_minimize(*a,**kw)
        with ExitStack() as stack:
            for cls in (skcov.LedoitWolf,skcov.OAS,skdec.PCA,skdec.FactorAnalysis,skcov.GraphicalLasso,skcov.MinCovDet):stack.enter_context(patch.object(cls,'fit',wrap_fit(cls.fit,cls.__name__)))
            stack.enter_context(patch.object(joint,'minimize',minimize));stack.enter_context(patch.object(joint,'_prepare',prepare));stack.enter_context(patch.object(joint,'_estimate',estimate))
            bundle=joint.fit_risk_estimator(method,x,market_returns=y.get('market_returns'),exposure_frame=y.get('exposure_frame'),params=y['params'])
        if sum(z['estimate_units'] for z in estimates)>6:raise RuntimeError('RISK_ANALYTICAL_COUNTER_EXCEEDS_FIXED_SLOT_BOUND')
        if any(z['category']=='ConvergenceWarning' for z in bundle.fitted_state.get('warnings',[])) and bundle.status=='FITTED':bundle.status='FIT_FAILED';bundle.failure_reason='UNRESOLVED_RISK_CONVERGENCE_NO_RETRY'
        pipe.send(('RESULT',bundle,dict(actual_fit_components=components,actual_fit_count=len(components),risk_estimates=estimates,canonical_logical_budget=bundle.budget)))
    except BaseException as exc:pipe.send(('ERROR',type(exc).__name__,str(exc)))
    finally:pipe.close()

def checked_exposure(method,year,cutoff,auth):
    from scripts.research.a2.training.stateful_pit_exposures import load_annual_projection
    pin=auth.get('exposure_input_pins',{}).get(method,{}).get(str(year),{})
    if not pin:raise ValueError('BLOCKED_INPUT:'+method+'_PIT_EXPOSURE_PIN_MISSING')
    item=load_annual_projection(pin,cutoff)
    if not isinstance(item,pd.DataFrame) or item.empty or item.attrs.get('pit_qualified') is not True or not pd.Timestamp(item.attrs['available_at'])<cutoff:raise ValueError('BLOCKED_INPUT:PIT_EXPOSURE_AVAILABILITY_OR_EMPTY')
    return item,dict(pin,input_matrix_sha256=identity_frame(item),factor_columns=list(map(str,item.columns)))

def start_attempt(log,auth,method,year,identity):
    attempts=[e for e in values._events(log) if e.get('event')=='MODEL_YEAR_ATTEMPT_STARTED'];model_id='RISK::'+method
    if any(e.get('model_id')==model_id and e.get('year')==year for e in attempts) or len(attempts)>=201:raise RuntimeError('RISK_SLOT_OR_GLOBAL_ATTEMPT_BUDGET')
    values._append(log,dict(event='MODEL_YEAR_ATTEMPT_STARTED',model_id=model_id,year=year,role=ROLE,budget_bucket='risk_primary',reuse_tuple_sha256=identity))

def fit_annual(method,year,run_dir,reader=None):
    run,cfg,auth,pins,method=frozen_contract(run_dir,method,year)
    if reader is None:reader=InputReader(run)
    elif type(reader) is not InputReader or reader.run!=run:raise ValueError('CANONICAL_RISK_READER_REQUIRED')
    base=dict(method=method,year=year,role=ROLE,source_pins=pins,specification=joint.specs(method),cutoff_exclusive=f'{year}-01-01',return_unit=UNIT,return_horizon_sessions=1,horizon_rule='IID_5_X_STATIC_DAILY_COV',window_sessions=63,annual_static=True,seed=20260928)
    slot=run/'models/risk'/method/str(year);rp=slot/'fit_receipt.json';mp=slot/'risk.joblib';log=run/'FIT_LOG.jsonl'
    if method=='HISTVOL':
        canonical=run/'models/risk/DIAG'/str(year)/'fit_receipt.json'
        prior=json.loads(canonical.read_text());path=Path(prior['model_path'])
        canonical_base=dict(base,method='DIAG',specification=joint.specs('DIAG'))
        canonical_tuple=prior.get('reuse_tuple',{})
        if any(canonical_tuple.get(k)!=z for k,z in canonical_base.items()) or values.digest(canonical_tuple)!=prior.get('reuse_tuple_sha256') or prior.get('method_id')!='DIAG' or prior.get('role')!=ROLE:raise RuntimeError('HISTVOL_CANONICAL_DIAG_TUPLE_CHANGED')
        if prior['status']!='FITTED' or values.sha(path)!=prior['model_sha256'] or not prior.get('scientific_feature_pit_qualified') or prior['reuse_tuple']['source_pins']!=pins or prior['year']!=year:
            raise RuntimeError('HISTVOL_ALIAS_REQUIRES_FITTED_EXACT_DIAG')
        expected=dict(status='EXACT_METHOD_REUSED',method_id=method,canonical_method='DIAG',year=year,role=ROLE,source_pins=pins,reuse_tuple=base,reuse_tuple_sha256=values.digest(base),source_model_path=str(path),source_model_sha256=prior['model_sha256'],source_receipt_path=str(canonical),source_receipt_sha256=values.sha(canonical),fit_units=0,risk_estimate_units=0,scientific_feature_pit_qualified=True,scientific_return_proxy_qualified=True,receipt_path=str(rp),alias_reason='Exact same observed63 diagonal variance; no distinct scientific model-year attempt')
        if rp.exists():
            if json.loads(rp.read_text())!=expected:raise RuntimeError('EXISTING_RISK_ALIAS_CHANGED')
        else:
            slot.mkdir(parents=True,exist_ok=True);write_json_atomic(rp,expected)
            values._append(log,dict(event='RISK_METHOD_EXACT_REUSED',model_id='RISK::HISTVOL',canonical_method='DIAG',year=year,fit_units=0,source_receipt_sha256=expected['source_receipt_sha256']))
        return joblib.load(path),expected
    if rp.exists():
        r=json.loads(rp.read_text());tup=r.get('reuse_tuple',{})
        if r.get('status')!='FITTED' or values.sha(mp)!=r.get('model_sha256') or any(tup.get(k)!=z for k,z in base.items()) or values.digest(tup)!=r.get('reuse_tuple_sha256'):raise RuntimeError('EXISTING_RISK_SLOT_PRESERVED_NO_RETRY')
        return joblib.load(mp),r
    identity=values.digest(base);start_attempt(log,auth,method,year,identity);slot.mkdir(parents=True,exist_ok=True)
    receipt=dict(status='RUNNING',method_id=method,year=year,role=ROLE,reuse_tuple=base,reuse_tuple_sha256=identity,fit_units=0,risk_estimate_units=0,receipt_path=str(rp),model_path=str(mp),transport_legacy_fit_log_role=values.ROLE)
    write_json_atomic(rp,receipt)
    try:
        if method=='NONLINEAR_SHRINKAGE':raise joint.RiskEstimatorBlocked('BLOCKED_DEPENDENCY:GENUINE_NONLINEAR_SHRINKAGE_BACKEND_NOT_SNAPSHOTTED')
        key=(str(run),year,pins['input_manifest_sha256'])
        if key not in _YEAR_INPUTS:_YEAR_INPUTS[key]=annual_inputs(reader,year)
        table,line=_YEAR_INPUTS[key];cutoff=pd.Timestamp(f'{year}-01-01');payload={'worker_source_sha256':pins['module_sha256']};aux={}
        if method=='SINGLE_INDEX':payload['market_returns'],aux=fixed_raw_index(reader,table.index,cutoff,auth)
        if method in ('INDUSTRY','FUNDAMENTAL'):payload['exposure_frame'],aux=checked_exposure(method,year,cutoff,auth)
        reuse=dict(base,input_lineage=line,auxiliary_input_lineage=aux);identity=values.digest(reuse);receipt.update(reuse_tuple=reuse,reuse_tuple_sha256=identity)
        payload['params']=dict(fit_cutoff=cutoff.isoformat(),return_unit=UNIT,return_horizon_sessions=1,source_id=line['source'],information_set_id=identity)
        # Reserve finite analytic-call units before estimation; actual completed states below.
        reservations=sum(e.get('reserved_estimate_units',0) for e in values._events(log) if e.get('event')=='RISK_ESTIMATE_STARTED')
        if reservations+6>352000:raise RuntimeError('RISK_ESTIMATE_FINITE_CAP_EXHAUSTED')
        values._append(log,dict(event='RISK_ESTIMATE_STARTED',model_id='RISK::'+method,year=year,reserved_estimate_units=6,fit_units=0))
        bundle=values._fit_job('risk','RISK::'+method,table,payload,table.index.to_numpy(),None,[],list(table.columns),None,log=log,auth=auth,prior=18,year=year,tuple_sha=identity,receipt=receipt,worker_target=risk_worker)
        meta=receipt['physical_fit_metadata'][-1]['metadata']
        if receipt['fit_units']!=meta['actual_fit_count']:raise RuntimeError('RISK_CHILD_ACK_COUNT_MISMATCH')
        units=sum(e['estimate_units'] for e in meta['risk_estimates']);receipt['risk_estimate_units']=units
        for event in meta['risk_estimates']:values._append(log,dict(event='RISK_ESTIMATE',model_id='RISK::'+method,year=year,role=ROLE,component=event['component'],risk_estimate_units=event['estimate_units'],fit_units=0,reuse_tuple_sha256=identity))
        if bundle.status!='FITTED':raise joint.RiskEstimatorBlocked(bundle.status+':'+bundle.failure_reason)
        current=json.loads((run/'run_config.json').read_text())
        if current.get('risk_training')!=auth or any(values.sha(path)!=pins[k] for k,path in [('module_sha256',__file__),('joint_source_sha256',JOINT_PATH),('values_module_sha256',values.__file__),('input_reader_sha256',values.READER_SOURCE),('input_manifest_sha256',run/'input_manifest.json'),('garch_definition_source_sha256',GARCH_PATH)]):raise ValueError('RISK_SOURCE_OR_AUTH_CHANGED_DURING_FIT')
        joblib.dump(bundle,mp)
        receipt.update(status='FITTED',model_sha256=values.sha(mp),canonical_bundle_identity=bundle.fitted_state['fit_identity_sha256'],scientific_feature_pit_qualified=True,scientific_return_proxy_qualified=True,assets_count=len(bundle.assets),estimated_assets_count=len(bundle.estimated_assets),fitted_dates=list(bundle.fitted_dates),eligibility_upgraded=False)
        write_json_atomic(rp,receipt);values._append(log,dict(event='MODEL_YEAR_COMPLETE',model_id='RISK::'+method,year=year,role=ROLE,status='FITTED',fit_units=receipt['fit_units'],reuse_tuple_sha256=identity))
        return bundle,receipt
    except Exception as exc:
        receipt.update(status='FAILED',failure=dict(type=type(exc).__name__,message=str(exc)));write_json_atomic(rp,receipt)
        values._append(log,dict(event='MODEL_YEAR_FAILED',model_id='RISK::'+method,year=year,role=ROLE,fit_units=receipt['fit_units'],failure=receipt['failure']));raise

def run_batch(run):
    run=Path(run).resolve();reader=InputReader(run);statuses=[]
    for method in METHODS:
        for year in YEARS:
            try:
                _,receipt=fit_annual(method,year,run,reader);status=dict(method_id=method,year=year,status=receipt['status'],fit_units=receipt['fit_units'])
            except Exception as exc:status=dict(method_id=method,year=year,status='FAILED',failure={'type':type(exc).__name__,'message':str(exc)})
            statuses.append(status);write_json_atomic(run/'logs/risk_batch_status.json',dict(status='ATTEMPTS_FINISHED' if len(statuses)==54 else 'RUNNING',slots=statuses,expected_slots=54,test_2026_rows_read=0));print(json.dumps(status,sort_keys=True),flush=True)
    return statuses

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--batch',action='store_true');a=p.parse_args(argv)
    if not a.batch:p.error('only the explicit 18-method annual batch is supported')
    results=run_batch(a.run_dir);return 0 if all(r['status'] in ('FITTED','EXACT_METHOD_REUSED') for r in results) else 2
if __name__=='__main__':raise SystemExit(main())
