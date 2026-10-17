"""Frozen pre2026 OOF -> existing joint policy -> continuous shareholder owner.

This runner never fits predictors/fusion or reads test data. Numerical inputs are
constructed only after the exact evaluation/source gates. Registered risk and
allocation names are not a claim of coverage by the seventeen primary paths.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from types import FunctionType, MethodType, SimpleNamespace
import argparse
import copy
import json
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.special import ndtr
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.training import consensus_fusion as fusion
from scripts.research.a2.training import consensus_predictors as predictors
from scripts.research.a2.data import consensus_account_inputs as account_inputs
from scripts.research.a2.data.consensus_training_inputs import ConsensusInputs, exact_key_filters, ALLOWED_SOURCES
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.inference import consensus_joint_policy as joint
from scripts.research.a2.evaluation import consensus_shareholder_account as shareholder
from scripts.research.a2.evaluation import consensus_cash_account as cash

TASK=predictors.TASK
BOUNDARY=pd.Timestamp('2026-01-01')
YEARS=(2023,2024,2025)
FREEZE='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R3.json'
GATE='AUTHORIZED_PRE2026_ACCOUNT_REPLAY'
SCENARIO_METHODS=('mean_cvar','mean_semivariance','log_growth')
RECIPE=dict(years=list(YEARS),packet_id='core5',fusion_methods=list(fusion.PACKET_METHODS['core5']),
    stage1=dict(risk_method='LW',allocation_method='cost_aware'),
    stage2=joint.catalogue()['primary_paths']+joint.catalogue()['allocation_paths'],
    lookback_sessions=120,fee_config=asdict(cash.FeeConfig()),continuous_account=True,
    selection='MEAN_ANNUAL_COST_NET_CONDITIONAL_NAV_SHARPE; LOW_TOTAL_TURNOVER; LEXICAL_FLOW_ID',
    normal_compatibility='p_up=ndtr(mu/sigma); q10/q90=mu +/- 1.28155*sigma; NOT_NATIVE_QUANTILE_CALIBRATION',
    forecast_unit=joint.UNIT,scenario_source=None,diagnostic_sensitivities=[
        dict(tag='cost5',one_way_all_in_bps=5.,fixed_per_fill_usd=0.,lookback_sessions=120),
        dict(tag='cost25',one_way_all_in_bps=25.,fixed_per_fill_usd=0.,lookback_sessions=120),
        dict(tag='ticket50c',one_way_all_in_bps=10.,fixed_per_fill_usd=.5,lookback_sessions=120),
        dict(tag='lookback60',one_way_all_in_bps=10.,fixed_per_fill_usd=0.,lookback_sessions=60)],
    sensitivity_role='DIAGNOSTICS_ONLY_SELECTED_FUSION_RISK_ALLOCATION; NO_SELECTION_FEEDBACK',
    risk_attempt_units=2,max_fit_units=10000,
    fit_timeout_seconds=1800,final_risk_fit_before_test=True,strict_PIT_certified=False)
values=predictors.values
require=predictors.require


class NotTestable(ValueError):pass


def ref(path):return dict(path=str(Path(path)),sha256=values.sha(path))


def source_pins():
    modules={'runner':__file__,'account_inputs':account_inputs.__file__,'shareholder':shareholder.__file__,
        'cash':cash.__file__,'joint_policy':joint.__file__,'risk_owner':joint.risk.__file__,
        'allocation_owner':joint.allocation.__file__,'continuous_owner':shareholder.owner.__file__,
        'corporate_owner':shareholder.ca.__file__,'training_inputs':predictors.ConsensusInputs.__module__}
    modules['training_inputs']=__import__(modules['training_inputs'],fromlist=['x']).__file__
    return {name:ref(path) for name,path in modules.items()}


ACCOUNT_CONVENTION_SHA='71ccae1d26b09cd972747a1876f7750b940e5b133abac5010c0a7bf28045eba8'


def recipe_for_run(run):
    result=copy.deepcopy(RECIPE)
    if Path(run).resolve()==fusion.CONTINUATION_RUN:
        result['fusion_methods'].append(fusion.owner.NNLS_ZERO_ABSTAIN)
    return result


def account_convention_ref(run):
    path=Path(run)/'ACCOUNT_CONVENTION_SCOPE.json'
    pin=ref(path);require(pin['sha256']==ACCOUNT_CONVENTION_SHA,'ACCOUNT_CONVENTION_CHANGED')
    frozen=fusion.metadata(path)
    require(frozen['schema']=='CONSENSUS_SOURCE_COMPLETION_ACCOUNT_CONVENTION_R1'
        and frozen['research_id']==fusion.CONTINUATION_RESEARCH_ID and frozen['task_id']==TASK
        and frozen['status']=='FROZEN_BEFORE_NEW_ACCOUNT_REPLAY_OR_SELECTION'
        and frozen['selection_outcomes_seen_before_this_freeze'] is False,'ACCOUNT_CONVENTION_NOT_PRECOMMITTED')
    return pin


def freeze_template(run,*,source_scope_ref=None):
    run=Path(run).resolve();paths=resolve(predictors.REPO)
    assert_safe_output_path(run,kind='backtest',paths=paths)
    scope=source_scope_ref or ref(paths.results_root/'_maintenance'/TASK/'ACCOUNT_SOURCE_SCOPE.json')
    reader_root=fusion.reader_run(run)
    result=dict(schema='CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R1',status='PROPOSED',task_id=TASK,
        run=str(run),source_pins=source_pins(),account_source_scope_ref=scope,
        fusion_freeze_ref=ref(run/'CONSENSUS_FUSION_FREEZE.json'),
        predictor_freeze_ref=ref(reader_root/'CONSENSUS_PREDICTOR_FREEZE.json'),
        authorized_spec=ref(predictors.spec_path()),recipe=recipe_for_run(run),
        source_policy='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY',test_2026_read_authorized=False)
    if run==fusion.CONTINUATION_RUN:
        result.update(schema='CONSENSUS_ACCOUNT_EVALUATION_CONTINUATION_R2',research_id=fusion.CONTINUATION_RESEARCH_ID,
            continuation_scope_ref=ref(run/'CONTINUATION_SCOPE.json'),account_convention_scope_ref=account_convention_ref(run),
            account_fx_convention_scope_ref=copy.deepcopy(shareholder.FX_CONVENTION_REF),
            fx_source_availability_qualification_ref=copy.deepcopy(shareholder.FX_AVAILABILITY_REF),
            prior_fit_units=fusion.metadata(run/'CONTINUATION_SCOPE.json')['budget']['prior_fit_units'])
    return result


def contract(run):
    run=Path(run).resolve();assert_safe_output_path(run,kind='backtest',paths=resolve(predictors.REPO))
    path=run/FREEZE;f=fusion.metadata(path)
    child=run==fusion.CONTINUATION_RUN
    schema='CONSENSUS_ACCOUNT_EVALUATION_CONTINUATION_R2' if child else 'CONSENSUS_ACCOUNT_EVALUATION_FREEZE_R1'
    require(f['schema']==schema and f['task_id']==TASK
        and f['status']==GATE and f['run']==str(run),'EVALUATION_FREEZE_REQUIRED')
    require(f['recipe']==recipe_for_run(run) and f['source_pins']==source_pins(),'EVALUATION_FROZEN_RECIPE_OR_SOURCE_CHANGED')
    require(f['source_policy']=='FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY'
        and f['test_2026_read_authorized'] is False,'EVALUATION_PRE2026_SCOPE_REQUIRED')
    reader_root=fusion.reader_run(run)
    if child:
        require(f['research_id']==fusion.CONTINUATION_RESEARCH_ID and f['account_convention_scope_ref']==account_convention_ref(run)
            and f['continuation_scope_ref']==ref(run/'CONTINUATION_SCOPE.json')
            and f.get('account_fx_convention_scope_ref')==shareholder.FX_CONVENTION_REF
            and f.get('fx_source_availability_qualification_ref')==shareholder.FX_AVAILABILITY_REF
            and f['prior_fit_units']==fusion.metadata(run/'CONTINUATION_SCOPE.json')['budget']['prior_fit_units'],
            'EVALUATION_CONTINUATION_LINEAGE_CHANGED')
    for key,expected in [('fusion_freeze_ref',run/'CONSENSUS_FUSION_FREEZE.json'),
            ('predictor_freeze_ref',reader_root/'CONSENSUS_PREDICTOR_FREEZE.json'),('authorized_spec',predictors.spec_path())]:
        r=f[key];require(Path(r['path'])==expected and values.sha(expected)==r['sha256'],'EVALUATION_DEPENDENCY_FREEZE_CHANGED:'+key)
    scope=f['account_source_scope_ref'];shareholder._metadata_ref(scope,scope=True,child=child)
    require(fusion.metadata(scope['path']).get('numeric_read_authorization')==account_inputs.GATE,'ACCOUNT_SOURCE_NUMERIC_GATE_REQUIRED')
    return run,f,ref(path)


def flow_id(method,risk_method='LW',allocation_method='cost_aware',tag=None,*,run=None):
    require(method in (RECIPE if run is None else recipe_for_run(run))['fusion_methods'],'UNPLANNED_CORE5_FUSION')
    return 'core5__'+method+'__'+risk_method+'__'+allocation_method+('' if tag is None else '__diagnostic_'+tag)


def qualified_vectors(reader,scope):
    """Current daily100 eligibility before projecting any ADV/return numeric."""
    flags=reader.pred_flags.copy();flags.signal_date=pd.to_datetime(flags.signal_date)
    pool=reader.membership.loc[reader.membership.ticker.notna(),['signal_date','ticker']].copy()
    pool.signal_date=pd.to_datetime(pool.signal_date)
    require(not pool.duplicated(['signal_date','ticker']).any(),'DAILY100_AMBIGUOUS_IDENTITY')
    keys=pool.merge(flags,on=['signal_date','ticker'],how='inner',validate='one_to_one')
    keys=keys.loc[keys.feature_available.eq(True)&keys.feature_source.isin(ALLOWED_SOURCES)&keys.signal_date.lt(BOUNDARY)].copy()
    require(not keys.empty,'NO_CAUSAL_DAILY100_FEATURE_KEYS')
    record=reader.records['prediction_feature_panel']
    source=scope['signal_adv_source_ref']
    require(source==dict(path=record['path'],sha256=record['sha256']),'ADV_MUST_BE_PINNED_PREDICTION_FEATURE_SOURCE')
    vectors=reader._vectors('prediction_feature_panel',['signal_date','ticker','avg_dollar_volume_20d','ret_1d'],
        exact_key_filters(keys,'ticker',[("feature_available","==",True),("feature_source","in",list(ALLOWED_SOURCES))]))
    vectors.signal_date=pd.to_datetime(vectors.signal_date)
    legal=keys[['signal_date','ticker']].merge(vectors,on=['signal_date','ticker'],how='left',validate='one_to_one')
    require(len(legal)==len(keys) and np.isfinite(legal[['avg_dollar_volume_20d','ret_1d']].to_numpy(float)).all()
        and legal.avg_dollar_volume_20d.ge(0).all(),'NONFINITE_CAUSAL_ADV_OR_DAILY_RETURNS')
    adv=legal.loc[legal.signal_date.ge('2023-01-01'),['signal_date','ticker','avg_dollar_volume_20d']].rename(columns={'avg_dollar_volume_20d':'adv'})
    adv['available_at']=(adv.signal_date+pd.Timedelta(hours=16)).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
    adv.attrs['source_ref']=copy.deepcopy(source)
    returns=legal.pivot(index='signal_date',columns='ticker',values='ret_1d').sort_index()
    returns.attrs.update(source_id=values.digest(source),source_ref=copy.deepcopy(source),unit='DAILY_DECIMAL_RETURN',
        eligibility='CURRENT_DAILY100_QUALIFIED_KEYS; monthly owner fits only current decision assets plus held')
    return adv,returns,keys


def compatible_forecasts(frame):
    require(not frame.duplicated(['signal_date','ticker']).any(),'DUPLICATE_FUSION_OOF_KEY')
    f=frame.loc[frame.prediction_qualified.eq(True),['signal_date','ticker','prediction','value_sigma']].rename(columns={'prediction':'mu','value_sigma':'sigma'}).copy()
    require(np.isfinite(f[['mu','sigma']].to_numpy(float)).all() and f.sigma.gt(0).all(),'INVALID_FUSION_MU_SIGMA')
    f['p_up']=ndtr(f.mu/f.sigma);f['q10']=f.mu-1.28155*f.sigma;f['q50']=f.mu;f['q90']=f.mu+1.28155*f.sigma
    f.attrs.update(unit=joint.UNIT,compatibility_assumption=RECIPE['normal_compatibility'])
    return f


def validate_past_publication_pins(run,members,year,pins):
    """Hash-only closure of the producer's exact past OOF packet custody."""
    expected=[(fusion.member_key(m),y,m) for m in members for y in range(2021,year)]
    require([(p['member'],p['year']) for p in pins]==[(key,y) for key,y,_ in expected],
        'FUSION_PAST_PUBLICATION_PACKET_CHANGED')
    for pin,(key,y,member) in zip(pins,expected):
        output=run/'predictions/consensus_predictors'/member['model_id']/f"{member['horizon']}d/{y}.parquet"
        publication_receipt=output.with_suffix('.receipt.json')
        _,fit_receipt,_,_=predictors.slot_paths(run,member['model_id'],y,member['horizon'])
        for path,sha_key in ((output,'prediction_sha256'),(publication_receipt,'publication_receipt_sha256'),
                (fit_receipt,'fit_receipt_sha256')):
            if not path.exists():raise NotTestable('MISSING_FUSION_TRAINING_PUBLICATION:'+key+':'+str(y))
            require(values.sha(path)==pin[sha_key],'FUSION_PAST_PUBLICATION_CUSTODY_CHANGED:'+key+':'+str(y))


def published_forecasts(run,method,reader):
    """Only existing annual core5 publication; never call a fit/publish entry."""
    frames=[];pins=[]
    if Path(run).resolve()==fusion.CONTINUATION_RUN:
        for year in YEARS:
            try:frame,pin=fusion.published_fusion_forecasts(run,method,year,reader)
            except fusion.PacketUnavailable as error:raise NotTestable(str(error)) from error
            frames.append(frame);pins.append(pin)
        return compatible_forecasts(pd.concat(frames,ignore_index=True)),pins
    for year in YEARS:
        _,method,_,frozen,slot,freeze_ref=fusion.contract(run,'core5',method,year)
        output=run/'predictions/consensus_fusion/core5'/method/f'{year}.parquet';rp=output.with_suffix('.receipt.json')
        if not output.exists() or not rp.exists():raise NotTestable('MISSING_FUSION_PUBLICATION:'+method+':'+str(year))
        pub=fusion.metadata(rp)
        if pub.get('status')!='PUBLISHED':raise NotTestable('UNPUBLISHED_FUSION:'+method+':'+str(year))
        require(pub.get('prediction_role')=='MODEL_OOF' and (pub['packet_id'],pub['model_id'],pub['year'])==('core5',method,year)
            and pub['test_2026_rows_read']==0 and Path(pub['path'])==output and pub['sha256']==values.sha(output)
            and pub['source_pins']==frozen['source_pins'],'FUSION_OOF_PUBLICATION_CUSTODY_CHANGED')
        _,fr,mp=fusion.slot_paths(run,'core5',method,year)
        require(Path(pub['fit_receipt_path'])==fr and pub['fit_receipt_sha256']==values.sha(fr),'FUSION_FIT_RECEIPT_CHANGED')
        fit=fusion.metadata(fr);reuse=fit['reuse_tuple'];fold=reader.annual_fold(year)
        require(fit['status']=='TRAINED' and (fit['packet_id'],fit['model_id'],fit['year'])==('core5',method,year)
            and reuse['members']==slot['members'] and reuse['freeze_ref']==freeze_ref
            and fit['source_pins']==frozen['source_pins'] and reuse['source_pins']==frozen['source_pins']
            and fit['reuse_tuple_sha256']==values.digest(reuse)==pub['reuse_tuple_sha256']
            and pub['model_sha256']==fit['model_sha256']==values.sha(mp),'FUSION_FITTED_STATE_CUSTODY_CHANGED')
        require(pd.Timestamp(reuse['train_maturity_exclusive'])==pd.Timestamp(fold['calibration_start'])
            and pd.Timestamp(reuse['calibration_maturity_exclusive'])==pd.Timestamp(f'{year}-01-01')
            and reuse['calibration_sessions']==[str(d) for d in fold['calibration_sessions']], 'FUSION_CALIBRATION_NOT_CHRONOLOGICAL')
        validate_past_publication_pins(run,slot['members'],year,reuse['past_publication_pins'])
        current_member_pins=[]
        # Missing current packet member cannot be silently replaced by surviving members.
        for member in slot['members']:
            member_path=run/'predictions/consensus_predictors'/member['model_id']/f"5d/{year}.parquet"
            mr=member_path.with_suffix('.receipt.json')
            if not member_path.exists() or not mr.exists():raise NotTestable('MISSING_CORE5_MEMBER:'+member['model_id']+':'+str(year))
            receipt=fusion.metadata(mr)
            require(receipt.get('status')=='PUBLISHED' and receipt['sha256']==values.sha(member_path)
                and receipt['source_pins']==frozen['source_pins']['predictor_sources'] and receipt['test_2026_rows_read']==0
                and (receipt['model_id'],receipt['year'],receipt['horizon'])==(member['model_id'],year,5),'CORE5_MEMBER_PUBLICATION_CHANGED')
            current_member_pins.append(dict(member=fusion.member_key(member),year=year,publication=ref(mr),predictions=ref(member_path)))
        _,proof=guard_parquet(output,pub['sha256'],['signal_date']);bounds=proof['date_bounds']['signal_date']
        require(proof['rows']==pub['rows'] and (not proof['rows'] or (bounds and all(pd.Timestamp(b['min'])>=pd.Timestamp(f'{year}-01-01')
            and pd.Timestamp(b['max'])<pd.Timestamp(f'{year+1}-01-01') for b in bounds))),'FUSION_PHYSICAL_OOF_YEAR_CHANGED')
        frame=pq.read_table(output,columns=['signal_date','ticker','prediction','value_sigma','prediction_qualified','prediction_role','year','reuse_tuple_sha256'],
            filters=[('signal_date','>=',pd.Timestamp(f'{year}-01-01')),('signal_date','<',pd.Timestamp(f'{year+1}-01-01'))]).to_pandas()
        require(frame.year.eq(year).all() and frame.prediction_role.eq('MODEL_OOF').all()
            and frame.reuse_tuple_sha256.eq(pub['reuse_tuple_sha256']).all(),'FUSION_ROW_ORIGIN_CHANGED')
        expected=reader.prediction_keys(year)[['signal_date','ticker']].sort_values(['signal_date','ticker']).reset_index(drop=True)
        require(frame[['signal_date','ticker']].sort_values(['signal_date','ticker']).reset_index(drop=True).equals(expected),'FUSION_PACKET_ROW_KEYS_INCOMPLETE')
        metadata_flags=reader.prediction_keys(year)[['signal_date','ticker','feature_available','feature_source']]
        qualified=metadata_flags.feature_available.eq(True)&metadata_flags.feature_source.isin(ALLOWED_SOURCES)
        availability=metadata_flags.assign(expected_qualified=qualified).merge(frame[['signal_date','ticker','prediction_qualified']],on=['signal_date','ticker'],validate='one_to_one')
        if not availability.prediction_qualified.eq(availability.expected_qualified).all():raise NotTestable('INCOMPLETE_CORE5_MEMBER_ROW_PACKET:'+method+':'+str(year))
        frames.append(frame);pins.append(dict(year=year,publication=ref(rp),predictions=ref(output),fit_receipt=ref(fr),
            current_member_pins=current_member_pins,member_pin_scope='CURRENT_HASHES_OBSERVED_BY_ACCOUNT_REPLAY; PRODUCER_RECEIPT_HAS_NO_CURRENT_MEMBER_PIN_FIELD'))
    return compatible_forecasts(pd.concat(frames,ignore_index=True)),pins


def annual_statistics(daily):
    f=daily.sort_values('date').copy();f['date']=pd.to_datetime(f.date)
    require(not f.date.duplicated().any() and f.date.ge('2023-01-01').all() and f.date.lt(BOUNDARY).all(),'CONTINUOUS_PRE2026_ACCOUNT_REQUIRED')
    require(np.isfinite(f.nav).all() and f.nav.gt(0).all(),'FINITE_POSITIVE_CONDITIONAL_NAV_REQUIRED')
    if 'accounting_qualified' in f and not f.accounting_qualified.eq(True).all():raise NotTestable('ACCOUNT_CORPORATE_LIFECYCLE_UNQUALIFIED')
    fx=f.get('fx_conversion_fee_usd',pd.Series(0.,index=f.index)).astype(float)
    trade=f.transaction_cost_amount.astype(float)
    require(np.isfinite(fx).all() and fx.ge(0.).all() and np.isfinite(trade).all() and trade.ge(0.).all(),'FINITE_NONNEGATIVE_ACCOUNT_FEES_REQUIRED')
    f['all_cost_amount']=trade+fx
    prior=f.nav.shift(1).fillna(3000.);f['cost_net_return']=f.nav/prior-1.
    stats=[]
    for year in YEARS:
        g=f.loc[f.date.dt.year.eq(year)]
        if len(g)<2:raise NotTestable('INSUFFICIENT_ACCOUNT_YEAR:'+str(year))
        returns=g.cost_net_return.to_numpy(float);std=float(np.std(returns,ddof=1));mean=float(np.mean(returns))
        sharpe=0. if std<=1e-15 else float(np.sqrt(252.)*mean/std)
        stats.append(dict(year=year,rows=len(g),cost_net_sharpe=sharpe,mean_daily_return=mean,std_daily_return=std,
            flat_cash_result=bool(np.all(np.abs(returns)<=1e-15)),zero_variance_convention='SHARPE_ZERO_NO_POSITIVE_PERFORMANCE_CLAIM',
            turnover=float(g.turnover.sum()),fees=float(g.all_cost_amount.sum()),trade_fees=float(g.transaction_cost_amount.sum()),fx_conversion_fees=float(fx.loc[g.index].sum()),nav_begin=float(prior.loc[g.index].iloc[0]),nav_end=float(g.nav.iloc[-1])))
    return dict(mean_annual_cost_net_sharpe=float(np.mean([s['cost_net_sharpe'] for s in stats])),
        total_turnover=float(f.turnover.sum()),annual_statistics=stats,source_vintage='UNKNOWN_RETAINED',metric='CONDITIONAL_NAV_NO_STRICT_PIT_CLAIM')


def select_best(receipts):
    available=[r for r in receipts if r.get('status')=='COMPLETE']
    if not available:raise NotTestable('NO_COMPLETE_ACCOUNT_CANDIDATE')
    return sorted(available,key=lambda r:(-r['statistics']['mean_annual_cost_net_sharpe'],r['statistics']['total_turnover'],r['flow_id']))[0]


def _risk_worker(pipe,operation,model_id,x,y,dates,quantile,dependencies,features,observed):
    """Same ACK/deadline parent as other fits; existing risk numerical owner."""
    try:
        require(operation=='risk','RISK_WORKER_OPERATION_REQUIRED')
        require(model_id in joint.PRIMARY_RISKS,'PRIMARY_RISK_WORKER_ONLY')
        for component in ('RISK_INPUT_PREPROCESSING_ATTEMPT','RISK_ESTIMATOR_STATE_ATTEMPT'):
            pipe.send(('FIT_START',component));require(pipe.recv() is True,'GLOBAL_FIT_BUDGET_REJECTED')
        bundle=joint.risk.fit_risk_estimator(model_id,x,params=observed)
        require(0<=bundle.budget['total_state_estimations']<=RECIPE['risk_attempt_units'],'RISK_ACTUAL_BUDGET_EXCEEDS_RESERVED_ATTEMPTS')
        require(all(pd.Timestamp(d)<pd.Timestamp(observed['fit_cutoff'])<=BOUNDARY for d in bundle.fitted_dates),'RISK_FIT_CLOCK_CHANGED')
        pipe.send(('RESULT',bundle,dict(actual_bundle_budget=bundle.budget,status=bundle.status,failed_reason=bundle.failure_reason)))
    except BaseException as error:pipe.send(('ERROR',type(error).__name__,str(error)))
    finally:pipe.close()


def make_policy(forecasts,returns,config,fee_config,run,receipt,shared_cache,identity):
    pending={};log=run/'FIT_LOG.jsonl';auth=dict(max_fit_units=10000,budget_bucket='consensus_account_primary_risk')
    prior=fusion.metadata(run/'CONTINUATION_SCOPE.json')['budget']['prior_fit_units'] if run==fusion.CONTINUATION_RUN else 0
    def started(event):
        token=values.digest(dict(source_pins=source_pins(),event=event))
        require(not any(e.get('event')=='FIT_STARTED' and e.get('reuse_tuple_sha256')==token for e in values._events(log)),
            'RISK_FAILED_OR_UNCHECKPOINTED_ATTEMPT_NO_RETRY')
        pending.update(event=event,token=token)
    def bounded_fit(method,past,*,params):
        require(pending.get('event',{}).get('method')==method,'RISK_START_CALLBACK_REQUIRED')
        return values._fit_job('risk',method,past,None,None,None,(),[],params,
            log=log,auth=auth,prior=prior,year=pd.Timestamp(params['fit_cutoff']).year,tuple_sha=pending['token'],
            receipt=receipt,worker_target=_risk_worker)
    policy=joint.ConsensusJointPolicy(forecasts,returns,config=config,fee_config=fee_config,
        shared_risk_cache=shared_cache,on_risk_fit_started=started)
    # Private binding of the owner's exact _risk bytecode; no global mutation or
    # duplicated window/asset/covariance implementation.
    proxy=SimpleNamespace(**vars(joint.risk));proxy.fit_risk_estimator=bounded_fit
    native=joint.ConsensusJointPolicy._risk
    clone=FunctionType(native.__code__,{**native.__globals__,'risk':proxy},argdefs=native.__defaults__,closure=native.__closure__)
    clone.__kwdefaults__=native.__kwdefaults__;policy._risk=MethodType(clone,policy)
    return policy


def _save_artifact(path,value,kind):
    assert_safe_output_path(path,kind='backtest',paths=resolve(predictors.REPO))
    if kind=='frame':value.to_parquet(path,index=False)
    else:joblib.dump(value,path)
    return ref(path)


def _reuse_receipt(root,identity,cache):
    rp=root/'receipt.json'
    if not rp.exists():
        require(not root.exists(),'UNRECEIPTED_ACCOUNT_FLOW_PRESERVE');return None
    old=fusion.metadata(rp);require(old['identity_sha256']==identity,'ACCOUNT_FLOW_CHECKPOINT_IDENTITY_CHANGED')
    for pin in old.get('artifacts',{}).values():require(values.sha(pin['path'])==pin['sha256'],'ACCOUNT_ARTIFACT_HASH_CHANGED')
    if 'state' in old.get('artifacts',{}):cache.update(joblib.load(old['artifacts']['state']['path'])['risk_cache'])
    return old


def evaluate_flow(run,method,risk_method,allocation_method,forecasts,returns,loaded,freeze_ref,publication_pins,cache,*,diagnostic=None):
    require(diagnostic is None or diagnostic in RECIPE['diagnostic_sensitivities'],'UNPLANNED_ACCOUNT_SENSITIVITY')
    fee=copy.deepcopy(RECIPE['fee_config']);lookback=120
    if diagnostic is not None:
        fee.update(one_way_all_in_bps=diagnostic['one_way_all_in_bps'],fixed_per_fill_usd=diagnostic['fixed_per_fill_usd']);lookback=diagnostic['lookback_sessions']
    fid=flow_id(method,risk_method,allocation_method,None if diagnostic is None else diagnostic['tag'],run=run);root=run/'evaluation/consensus_account'/fid;rp=root/'receipt.json'
    identity=values.digest(dict(flow_id=fid,fee_config=fee,lookback_sessions=lookback,freeze_ref=freeze_ref,publications=publication_pins,
        forecast_sha256=predictors.frame_hash(forecasts),returns_sha256=predictors.frame_hash(returns.reset_index()),
        source_scope_ref=loaded['source_scope_ref']))
    old=_reuse_receipt(root,identity,cache)
    if old:return old
    root.mkdir(parents=True);receipt=dict(status='IN_PROGRESS',task_id=TASK,flow_id=fid,fusion_method=method,risk_method=risk_method,
        allocation_method=allocation_method,fee_config=fee,lookback_sessions=lookback,diagnostic_only=diagnostic is not None,identity_sha256=identity,freeze_ref=freeze_ref,publication_pins=publication_pins,
        fit_units=0,receipt_path=str(rp),artifacts={},source_vintage='UNKNOWN_RETAINED',strict_PIT_certified=False)
    write_json_atomic(rp,receipt)
    if allocation_method in SCENARIO_METHODS:
        receipt.update(status='NOT_TESTABLE',reason='NO_QUALIFIED_MATURE_Y_OPEN5_SCENARIOS; DAILY_RETURN_COMPOUNDING_IS_NOT_A_SUBSTITUTE')
        write_json_atomic(rp,receipt);return receipt
    policy=make_policy(forecasts,returns,joint.PolicyConfig(risk_method,allocation_method,lookback),cash.FeeConfig(**fee),run,receipt,cache,identity)
    try:
        events=loaded['events'];kwargs={k:events[k] for k in ('corporate_actions','corporate_action_known_at','unsupported_events','entitlement_events','entitlement_security_tickers','entitlement_source_binding','research_ca_accounting_convention','foreign_fx_marks') if k in events}
        replay=shareholder.run_shareholder_cash_account(loaded['market'],[fid],policy,task_authority=loaded['task_authority'],
            settlement_calendar=loaded['settlement_calendar'],fee_config=policy.fee_config,usable_a=loaded['usable_a'],**kwargs)
        for name in ('daily','fills','positions','orders','execution_results','settlement_ledger','entitlements','accounting_exceptions'):
            frame=getattr(replay,name,None)
            if isinstance(frame,pd.DataFrame):receipt['artifacts'][name]=_save_artifact(root/(name+'.parquet'),frame,'frame')
        diagnostics=pd.DataFrame([dict(json=json.dumps(d,sort_keys=True,default=str)) for d in policy.diagnostics])
        receipt['artifacts']['diagnostics']=_save_artifact(root/'diagnostics.parquet',diagnostics,'frame')
        state=dict(config=asdict(policy.config),risk_cache=cache,monthly_state_keys=policy.monthly_state_keys,
            final_raw_units=replay.final_state['fractional_shares'],tickers=list(loaded['market'].tickers),
            final_state=replay.final_state,metadata=replay.metadata,audit=replay.audit,freeze_ref=freeze_ref,
            stock_distribution_forced_exit_inventory_tickers=tuple(replay.final_state.get('stock_distribution_forced_exit_inventory_tickers',())))
        receipt['artifacts']['state']=_save_artifact(root/'state.joblib',state,'state')
        if any(d.get('status')=='NOT_TESTABLE_RISK_PRESERVE_UNITS' for d in policy.diagnostics):raise NotTestable('PRIMARY_RISK_INPUT_OR_ESTIMATION_BLOCKED')
        nav=replay.daily.nav.to_numpy(float);peaks=np.maximum.accumulate(np.r_[3000.,nav])[1:]
        cash_rejections=replay.execution_results.loc[replay.execution_results.reason.eq('INSUFFICIENT_CASH')&replay.execution_results.side.eq('BUY')]
        unsettled_dates=set(replay.daily.loc[replay.daily.unsettled_cash.gt(cash.TOL),'date'])
        trade_fees=float(replay.fills.transaction_cost.sum())
        fx_fees=float(replay.daily.get('fx_conversion_fee_usd',pd.Series(dtype=float)).sum())
        if fx_fees:
            journal_fees=float(replay.entitlements.get('fx_conversion_fee_usd',pd.Series(dtype=float)).fillna(0.).sum())
            require(np.isclose(fx_fees,journal_fees,rtol=1e-10,atol=1e-10),'FX_DAILY_AND_ENTITLEMENT_FEE_SUM_MISMATCH')
        diagnostics_summary=dict(total_fees=trade_fees+fx_fees,trade_fees=trade_fees,fx_conversion_fees=fx_fees,total_turnover=float(replay.daily.turnover.sum()),
            max_drawdown=float(np.min(nav/peaks-1.)),fills=len(replay.fills),cash_limited_fill_count=int(replay.fills.cash_limited.sum()),
            settlement_blocked_proxy_count=int(cash_rejections.execution_date.isin(unsettled_dates).sum()),
            settlement_proxy_scope='BUY INSUFFICIENT_CASH while unsettled receivable>0; co-occurrence, not counterfactual causation')
        receipt.update(status='COMPLETE',statistics=annual_statistics(replay.daily),diagnostics_summary=diagnostics_summary,actual_budget_scope='GLOBAL_SHARED_CACHE_SNAPSHOT_NOT_INCREMENTAL_FIT_COUNT',actual_risk_bundle_budgets=[dict(cache_key=str(key),method=b.method_id,status=b.status,budget=b.budget) for key,b in policy.risk_cache.items()])
    except Exception as error:
        if 'state' not in receipt['artifacts']:
            receipt['artifacts']['state']=_save_artifact(root/'state.joblib',dict(risk_cache=cache),'state')
        receipt.update(status='NOT_TESTABLE' if isinstance(error,NotTestable) else 'FAILED_NO_RETRY',failure=dict(type=type(error).__name__,reason=str(error)))
    write_json_atomic(rp,receipt);return receipt


def freeze_selected_risk(run,selected,forecasts,returns,loaded,freeze_ref,cache):
    root=run/'models/consensus_final_policy'/selected['flow_id'];rp=root/'receipt.json'
    identity=values.digest(dict(selected_flow=selected['flow_id'],selected_receipt_sha256=values.sha(selected['receipt_path']),freeze_ref=freeze_ref))
    old=_reuse_receipt(root,identity,cache)
    if old:return old
    root.mkdir(parents=True);r=dict(status='IN_PROGRESS',task_id=TASK,identity_sha256=identity,selected_flow=selected['flow_id'],
        receipt_path=str(rp),fit_units=0,artifacts={},freeze_ref=freeze_ref)
    write_json_atomic(rp,r)
    try:
        state=joblib.load(selected['artifacts']['state']['path'])
        policy=make_policy(forecasts,returns,joint.PolicyConfig(**state['config']),cash.FeeConfig(**selected['fee_config']),run,r,cache,identity)
        policy.monthly_state_keys=state['monthly_state_keys'].copy()
        last=pd.Timestamp(loaded['market'].dates[-1]);pool=loaded['pool']
        latest=pool.loc[pool.signal_date.eq(last)&pool.identity_present.eq(True)&pool.ticker.notna(),'ticker']
        forecast_names=set(forecasts.loc[forecasts.signal_date.eq(last),'ticker'])
        latest=set(latest)&forecast_names
        held=np.asarray(state['tickers'])[(np.asarray(state['final_raw_units'])>joint.EPS).any(axis=0)]
        forced=set(state.get('stock_distribution_forced_exit_inventory_tickers',()))
        require(forced<=set(held) and not (forced&latest),'FINAL_MECHANICAL_EXIT_INVENTORY_CONFLICT')
        assets=sorted((latest|set(held))-forced);require(bool(assets),'NO_FINAL_KNOWN_ASSETS')
        policy.freeze_final_risk(assets)
        final_key=policy.monthly_state_keys[BOUNDARY.to_period('M').start_time];bundle=policy.risk_cache[final_key]
        require(bundle.status=='FITTED','FINAL_RISK_NOT_FITTED')
        payload={**state,'risk_cache':cache,'monthly_state_keys':policy.monthly_state_keys,'final_risk_key':final_key,
            'final_known_assets':assets,'final_risk_frozen_before_test':True,'forecast_unit':joint.UNIT,'recipe':recipe_for_run(run)}
        r['artifacts']['state']=_save_artifact(root/'state.joblib',payload,'state')
        r.update(status='COMPLETE',final_risk_fit_cutoff='2026-01-01 exclusive',test_rows_read=0,actual_final_risk_budget=bundle.budget)
    except Exception as error:
        r['artifacts']['state']=_save_artifact(root/'state.joblib',dict(risk_cache=cache),'state')
        r.update(status='FAILED_NO_RETRY',failure=dict(type=type(error).__name__,reason=str(error)))
    write_json_atomic(rp,r);return r


def catalogue_coverage():
    primary={p['risk_method'] for p in RECIPE['stage2']};alloc={p['allocation_method'] for p in RECIPE['stage2']}
    return dict(full_registered_risk_names=list(joint.RISK_METHODS),full_registered_allocation_names=list(joint.ALLOCATION_METHODS),
        primary_account_paths=copy.deepcopy(RECIPE['stage2']),primary_paths_are_not_all44=True,
        outside_primary_risk=[dict(method=m,status='NOT_ATTEMPTED_OUTSIDE_FIXED_PRIMARY_RECIPE',requires='method-specific source/dependency admission; no surrogate') for m in joint.RISK_METHODS if m not in primary],
        outside_primary_allocation=[dict(method=m,status='NOT_ATTEMPTED_OUTSIDE_FIXED_PRIMARY_RECIPE',requires='method-specific source/dependency admission; no surrogate') for m in joint.ALLOCATION_METHODS if m not in alloc],
        scenario_paths=[dict(method=m,status='NOT_TESTABLE',reason='NO_QUALIFIED_MATURE_Y_OPEN5_SCENARIOS') for m in SCENARIO_METHODS])


def unavailable_publication(run,method,freeze_ref,error):
    fid=flow_id(method,run=run);root=run/'evaluation/consensus_account'/fid;rp=root/'receipt.json'
    identity=values.digest(dict(flow_id=fid,freeze_ref=freeze_ref,unavailable_publication=str(error)))
    old=_reuse_receipt(root,identity,{})
    if old:return old
    root.mkdir(parents=True)
    r=dict(status='NOT_TESTABLE',task_id=TASK,flow_id=fid,fusion_method=method,risk_method='LW',allocation_method='cost_aware',
        identity_sha256=identity,freeze_ref=freeze_ref,reason=str(error),fit_units=0,receipt_path=str(rp),artifacts={},
        missing_packet_is_not_partial_fusion=True,source_vintage='UNKNOWN_RETAINED',strict_PIT_certified=False)
    write_json_atomic(rp,r);return r


def run_all(run):
    run,f,freeze_ref=contract(run)
    with predictors.fit_lock(run):
        bound=account_inputs.metadata_preflight(frozen_contract_ref=freeze_ref,source_scope_ref=f['account_source_scope_ref'])
        reader_root=fusion.reader_run(run);reader=ConsensusInputs(reader_root,reader_root/'derived/consensus100_daily.parquet')
        _,pf,_=predictors.contract(reader_root,'ridge',2023,5);predictors.reader_integrity(reader,pf)
        adv,returns,_=qualified_vectors(reader,bound['scope'])
        loaded=account_inputs.load_account_inputs(bound,signal_adv_by_key=adv)
        require(pd.DatetimeIndex(loaded['market'].dates).min()>=pd.Timestamp('2023-01-01')
            and pd.DatetimeIndex(loaded['market'].dates).max()<BOUNDARY,'ACCOUNT_PIPELINE_PRE2026_REQUIRED')
        cache={};stage1=[];forecasts={};publication_pins={}
        for method in f.get('recipe',recipe_for_run(run))['fusion_methods']:
            try:
                frames,pins=published_forecasts(run,method,reader);forecasts[method]=frames;publication_pins[method]=pins
                stage1.append(evaluate_flow(run,method,'LW','cost_aware',frames,returns,loaded,freeze_ref,pins,cache))
            except NotTestable as error:stage1.append(unavailable_publication(run,method,freeze_ref,error))
        try:best=select_best(stage1)
        except NotTestable as error:
            summary=dict(status='NOT_TESTABLE',task_id=TASK,freeze_ref=freeze_ref,reason=str(error),stage1=stage1,stage2=[],catalogue_coverage=catalogue_coverage(),test_2026_rows_read=0)
            write_json_atomic(run/'evaluation/consensus_account_summary.json',summary);return summary
        method=best['fusion_method'];stage2=[]
        for path in RECIPE['stage2']:
            stage2.append(evaluate_flow(run,method,path['risk_method'],path['allocation_method'],forecasts[method],returns,loaded,freeze_ref,publication_pins[method],cache))
        try:final=select_best(stage2)
        except NotTestable as error:
            summary=dict(status='NOT_TESTABLE',task_id=TASK,freeze_ref=freeze_ref,reason=str(error),selected_fusion=method,stage1=stage1,stage2=stage2,catalogue_coverage=catalogue_coverage(),test_2026_rows_read=0)
            write_json_atomic(run/'evaluation/consensus_account_summary.json',summary);return summary
        final_risk=freeze_selected_risk(run,final,forecasts[method],returns,loaded,freeze_ref,cache)
        sensitivities=[];sensitivity_final_risk=[]
        for diagnostic in RECIPE['diagnostic_sensitivities']:
            result=evaluate_flow(run,method,final['risk_method'],final['allocation_method'],forecasts[method],returns,loaded,freeze_ref,publication_pins[method],cache,diagnostic=diagnostic)
            sensitivities.append(result)
            if result['status']=='COMPLETE':sensitivity_final_risk.append(freeze_selected_risk(run,result,forecasts[method],returns,loaded,freeze_ref,cache))
        final_frozen=final_risk['status']=='COMPLETE' and all(r['status']=='COMPLETE' for r in sensitivity_final_risk)
        summary=dict(status='COMPLETE' if final_frozen else 'FINAL_RISK_NOT_FROZEN_NO_TEST_USE',task_id=TASK,
            freeze_ref=freeze_ref,selected_fusion=method,selected_flow=final['flow_id'],stage1=stage1,stage2=stage2,
            final_risk_receipt=final_risk,sensitivities=sensitivities,sensitivity_final_risk=sensitivity_final_risk,sensitivity_selection_feedback=False,catalogue_coverage=catalogue_coverage(),conditional_research_only=True,strict_PIT_certified=False,test_2026_rows_read=0)
        write_json_atomic(run/'evaluation/consensus_account_summary.json',summary);return summary


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);args=p.parse_args(argv)
    result=run_all(Path(args.run));print(json.dumps(dict(status=result['status'],selected_fusion=result.get('selected_fusion'),selected_flow=result.get('selected_flow')),ensure_ascii=False))


if __name__=='__main__':main()
