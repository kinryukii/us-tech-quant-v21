"""R6 pure opportunity adapters around existing native producers.

No file readers, dataset authority, registry, account or training controller.
Caller owns physical predicate projections, current UID/epoch authority, the
whole freeze, fit reservations and artifacts. Missing identities never carry.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge
from scipy.special import ndtr
from scripts.research.a2.data.joint_input_binding import FEATURES, FORBIDDEN_COLUMNS
from scripts.research.a2.training import stateful_mechanism_models as mechanism
from scripts.research.a2.training import stateful_value_extensions as sequence
from scripts.research.a2.training import joint_opportunity_breadth_r4 as opportunity
from scripts.research.a2.ensemble import joint_fusion_breadth_r4 as fusion
from scripts.research.a2.ensemble import joint_five_day_fusion as residual

ID='V24_B_JOINT_METHOD_SPACE_COMPLETION_PRE2026_R6'
REPO=Path(__file__).resolve().parents[4]
TARGET=opportunity.TARGET
BOUNDARY=pd.Timestamp('2026-01-01')
SEED=20260928
LOOKBACKS=(5,20,60)
YEARS=(2022,2023,2024,2025)
MODELS=('TCN','GRU','LSTM','TemporalMLP','LagLinear')
PACKET=(*MODELS,'BayesianRidge')
DISTRIBUTION_PACKET=('BayesianRidge','mlp_dist','ngboost','cat_uncertainty')
FUSIONS=('equal','median','simplex','nnls','ridge_stack','hgb_stack','mlp_stack','linear_gate','mlp_gate','residual_tcn_then_ridge')
PINS={
 'scripts/research/a2/training/stateful_mechanism_models.py':'e7fc26986a48c41676e518d880252623f69dbdbefb1fdedeec806b87ea02f57d',
 'scripts/research/a2/training/stateful_value_extensions.py':'4752aaf98161fb9d92148c852d1a96504e9945fed1254c945774cdf8853f7634',
 'scripts/research/a2/training/joint_opportunity_breadth_r4.py':'165019607b3b27ec259229ecb5c13c84f6aad06d51dbd65cea592ac965817e60',
 'scripts/research/a2/ensemble/joint_fusion_breadth_r4.py':'736f9ff479456ba4ebbc03c5fbf6b591dc241a651a40e3488a94a8306f7d6a93',
 'scripts/research/a2/ensemble/joint_five_day_fusion.py':'955412bd8862133398c7bf2439e0d6ccef7b2f4a31970af873fcefc792976217',
 'scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/models_native.py':'0b90e45b48f6748de2dad86c896502426b0a21cae062ac6f307ef8a52db657a8'}

class OpportunityBlocked(ValueError): pass

def source_pins():
    for relative,digest in PINS.items():
        if hashlib.sha256((REPO/relative).read_bytes()).hexdigest()!=digest:
            raise OpportunityBlocked('NATIVE_PRODUCER_PIN_CHANGED:'+relative)
    return dict(PINS)

def recipes():
    out={name:dict(mechanism.parameters(name,'LOW')) for name in ('TCN','GRU','LSTM')}
    for name in out:
        out[name].update(lookbacks=list(LOOKBACKS),tcn_dilations=[1,2,4,8,16],tcn_kernel=3,
                         tcn_receptive_field=63,dropout=0.,bidirectional=False,normalization='NONE')
    out['TemporalMLP']=dict(mechanism.parameters('MLP','LOW'),representation='OLDEST_TO_CURRENT_FLATTEN_SCALED32_PLUS_MISSING32')
    out['LagLinear']=dict(mechanism.parameters('Ridge','LOW'),representation='OLDEST_TO_CURRENT_FLATTEN_SCALED32_PLUS_MISSING32')
    out['BayesianRidge']=dict(max_iter=300,tol=.001,alpha_1=1e-6,alpha_2=1e-6,
        lambda_1=1e-6,lambda_2=1e-6,alpha_init=None,lambda_init=None,compute_score=False,
        fit_intercept=True,copy_X=True,verbose=False,
        uncertainty='EMPIRICAL_BAYES_PLUGIN_GAUSSIAN;X_POSTERIOR_COV_X_PLUS_NOISE')
    return out

def inner_folds(year):
    if year not in YEARS: raise OpportunityBlocked('ANNUAL_COHORT_NOT_FROZEN')
    y=year-1
    return [dict(id=f'{year}_INNER_Q{q}',cutoff=f'{y}-{m:02d}-01',validation_start=f'{y}-{m:02d}-01',
                 validation_end=(f'{year}-01-01' if q==4 else f'{y}-{m+3:02d}-01'))
            for q,m in ((2,4),(3,7),(4,10))]

def specification():
    spec=dict(schema='B_R6_OPPORTUNITY_NATIVE_ADAPTER_V1',research_id=ID,target=TARGET,
        target_clipped=False,target_cash_complete=False,feature_order=list(FEATURES),
        raw_score_rank_allowed=False,models=list(MODELS),point_packet=list(PACKET),
        distribution_packet=list(DISTRIBUTION_PACKET),fusion_methods=list(FUSIONS),
        lookbacks=list(LOOKBACKS),seed=SEED,capacity='EXISTING_LOW_FIXED',recipes=recipes(),
        annual_genuine_OOF=list(YEARS),inner_folds={str(y):inner_folds(y) for y in YEARS},
        selection='EQUAL_MEAN_OF_THREE_DATE_WEIGHTED_INNER_MSE;TIE_5_20_60;ALL_NINE_COMPLETE',
        inner_predictions_are_genuine_OOF=False,outer_account_length_selection=False,
        inputs='CALLER_PREDICATE_PROJECTED_B32;EXACT_SAME_UID_AND_OBSERVED_EPOCH;NO_CARRY',
        sequence_training_sample={'scientific_identity':'R6_FIXED_DATE_UID_EPOCH_HASH_CAP_48000','cap':48000,'seed':20260928,'quota':'EQUAL_DATE_WITH_AVAILABILITY_WATERFILL;REMAINDER_CALENDAR_ASCENDING','five_models_three_lengths_same_keys':True,'all_dates_preserved':True,'validation_and_OOF_sampled':False,'Bayesian_R4_risk_unchanged':True,'target_or_prediction_for_selection':False},
        missing='CENTERED_ZERO_PLUS_EXPLICIT_MASK;NO_PRICE_FILL;CURRENT_FEATURE_ROW_REQUIRED',
        distribution_lower_tail='FIXED_EQUAL_GAUSSIAN_MIXTURE_CDF_Q10;64_BISECTIONS;UNCALIBRATED_COVERAGE',
        student_t='BLOCKED_NATIVE_IMPLEMENTATION',heteroskedastic='R4_EXACT_REUSE_CANDIDATE_NO_NEW_PREDICTOR',
        fusion_packet_shrink=False,residual_primary='TCN_GENUINE_ANNUAL_OOF',
        output_roles={'CURRENT_ELIGIBLE_ALPHA_OOF':{'eligible_for_policy':False,'domain':'ALL_LEGAL_STRUCTURAL_ELIGIBLE_KEYS'},'FULL_REQUIRED_ELIGIBLE_PLUS_HELD_POLICY_OOF':{'qualification':'ALL_REQUIRED_UID_EPOCH_CLASS_KEYS','partial_publish':False}},
        residual_sigma='NO_INFIT_RMS;2023_BLOCKED_WITHOUT_PRIOR_COMPOSITE_OOF',
        budget=dict(sequence_backend_calls=200,sequence_neural_calls=160,sequence_linear_calls=40,
            sequence_shared_scalers_upper=48,sequence_durable_states_upper=248,
            sequence_parameter_components_upper=408,bayes_posterior_fits=4,bayes_scalers_upper=4,
            fusion_learned_events_upper=103,fusion_parameter_components_upper=115,additional_prior_native_error_scale_states_upper=21),
        scientific_retry=0,strict_PIT_promotion_eligible=False,quote_qualified=False,
        certified_nav_qualified=False,test2026_rows_read=0,source_pins=source_pins())
    return json.loads(json.dumps(spec,sort_keys=True))

def slot_matrix(selected_windows=None):
    selected_windows=selected_windows or {}
    slots=[]
    for year in YEARS:
        for fold in inner_folds(year):
            for length in LOOKBACKS:
                for name in MODELS:
                    slots.append(dict(year=year,phase='INNER',cohort=fold['id'],cutoff=fold['cutoff'],model=name,
                        lookback=length,seed=SEED,capacity='LOW',backend_calls=1,parameter_components=1 if name=='LagLinear' else 2))
        for name in MODELS:
            length=selected_windows.get((year,name),'SELECTED_FROM_THREE_INNER_FOLDS')
            if length!='SELECTED_FROM_THREE_INNER_FOLDS' and length not in LOOKBACKS:
                raise OpportunityBlocked('WINDOW_NOT_FROZEN')
            slots.append(dict(year=year,phase='ANNUAL',cohort=f'ANNUAL_{year}',cutoff=f'{year}-01-01',model=name,
                lookback=length,seed=SEED,capacity='LOW',backend_calls=1,parameter_components=1 if name=='LagLinear' else 2))
    return slots

def select_window(losses):
    if set(losses)!=set(LOOKBACKS): raise OpportunityBlocked('COMPLETE_WINDOW_TRIALS_REQUIRED')
    scores={}
    for length in LOOKBACKS:
        values=np.asarray(losses[length],float)
        if values.shape!=(3,) or not np.isfinite(values).all() or np.any(values<0):
            raise OpportunityBlocked('ALL_THREE_INNER_TRIALS_MUST_COMPLETE')
        scores[length]=float(values.mean())
    return min(LOOKBACKS,key=lambda length:(scores[length],length))

def _dates(series):
    dates=pd.to_datetime(series,errors='raise')
    if dates.isna().any() or dates.dt.tz is not None or dates.ge(BOUNDARY).any() or not dates.eq(dates.dt.normalize()).all():
        raise OpportunityBlocked('PRE2026_NAIVE_SESSION_DATES_REQUIRED')
    return dates

def _known(value):
    return isinstance(value,str) and bool(value.strip()) and not value.upper().startswith(('UNKNOWN','TICKER_','HELD_'))

def _true(series):
    return series.map(lambda v:type(v) in (bool,np.bool_) and bool(v))

def training_metadata(metadata,cutoff):
    cut=pd.Timestamp(cutoff)
    if cut.tz is not None or cut>BOUNDARY: raise OpportunityBlocked('EXCLUSIVE_PRE2026_TRAIN_CUTOFF_REQUIRED')
    need={'signal_date','ticker','execution_date','label_end_date','label_mature_date','fit_eligible','security_uid','asset_epoch','identity_qualified','source_qualified'}
    if not need.issubset(metadata): raise OpportunityBlocked('QUALIFIED_TRAINING_METADATA_REQUIRED')
    for field in ('signal_date','execution_date','label_end_date','label_mature_date'): _dates(metadata[field])
    legal=opportunity.training_mask(metadata,cut)
    for field in ('identity_qualified','source_qualified'): legal &= _true(metadata[field])
    for field in ('security_uid','asset_epoch'): legal &= metadata[field].map(_known)
    if len(metadata)==0 or not legal.all(): raise OpportunityBlocked('UNQUALIFIED_OR_IMMATURE_TRAIN_ROW_NO_DROP')
    return metadata

@dataclass
class Windows:
    keys:pd.DataFrame
    values:np.ndarray
    observed:np.ndarray
    qualified:np.ndarray
    block_reasons:tuple

def build_windows(history,keys,calendar,length,*,feature_order=FEATURES):
    if length not in LOOKBACKS or tuple(feature_order)!=tuple(FEATURES): raise OpportunityBlocked('FROZEN_B32_WINDOW_REQUIRED')
    if set(history)&set(FORBIDDEN_COLUMNS): raise OpportunityBlocked('RAW_SCORE_RANK_FORBIDDEN')
    needed={'signal_date','ticker','security_uid','asset_epoch','identity_qualified','source_qualified'}
    if not needed.issubset(keys) or not (needed|{'feature_available',*FEATURES}).issubset(history):
        raise OpportunityBlocked('UID_EPOCH_WINDOW_METADATA_REQUIRED')
    h=history.copy();k=keys.copy();h['signal_date']=_dates(h.signal_date);k['signal_date']=_dates(k.signal_date)
    if h.duplicated(['signal_date','ticker']).any() or k.duplicated(['signal_date','ticker']).any(): raise OpportunityBlocked('DUPLICATE_EXACT_WINDOW_KEY')
    cal=pd.DatetimeIndex(calendar)
    _dates(pd.Series(cal))
    if not cal.is_unique or not cal.is_monotonic_increasing: raise OpportunityBlocked('ORDERED_UNIQUE_SESSION_CALENDAR_REQUIRED')
    if len(h) and (not len(k) or h.signal_date.max()>k.signal_date.max()): raise OpportunityBlocked('HISTORY_AFTER_REQUESTED_SIGNAL')
    index=h.set_index(['signal_date','ticker']);values=np.full((len(k),length,len(FEATURES)),np.nan)
    observed=np.zeros(values.shape,bool);qualified=np.zeros(len(k),bool);reasons=[]
    # This memo is local to this one exact history/key/cutoff call. Source and
    # UID/epoch qualification stay in the original short-circuit order.
    positions=cal.get_indexer(k.signal_date)
    record_memo={};not_cached=object()
    for i,row in enumerate(k.itertuples(index=False)):
        if not (_known(row.security_uid) and _known(row.asset_epoch) and row.identity_qualified is True and row.source_qualified is True):
            reasons.append('UNKNOWN_OR_UNQUALIFIED_CURRENT_UID_EPOCH');continue
        loc=positions[i]
        if loc<0: reasons.append('MISSING_SIGNAL_SESSION');continue
        dates=cal[max(0,loc-length+1):loc+1];offset=length-len(dates)
        for j,date in enumerate(dates,offset):
            key=(date,row.ticker)
            cached=record_memo.get(key,not_cached)
            if cached is not_cached:
                if key not in index.index:
                    record_memo[key]=None;continue
                cached=[index.loc[key],None,None]
                record_memo[key]=cached
            if cached is None:continue
            record=cached[0]
            if not (_known(record.security_uid) and _known(record.asset_epoch) and record.security_uid==row.security_uid and record.asset_epoch==row.asset_epoch): continue
            if cached[1] is None:
                cached[1]=bool(_true(pd.Series([record.identity_qualified,record.source_qualified,record.feature_available])).all())
            if not cached[1]:continue
            if cached[2] is None:
                x=record[list(FEATURES)].to_numpy(float)
                if np.isinf(x).any(): raise OpportunityBlocked('INFINITE_HISTORY_FEATURE')
                cached[2]=(x,np.isfinite(x))
            x,finite=cached[2]
            values[i,j]=x;observed[i,j]=finite
        qualified[i]=bool(observed[i,-1].all())
        reasons.append(None if qualified[i] else 'NO_LEGAL_COMPLETE_CURRENT_FEATURE_ROW')
    return Windows(k,values,observed,qualified,tuple(reasons))

def _start(callback,*,kind,components,backend_calls=1):
    if callback is None: raise OpportunityBlocked('CALLER_FIT_RESERVATION_CALLBACK_REQUIRED')
    event=dict(kind=kind,components=list(components),learned_units=len(components),backend_calls=backend_calls,scientific_retry=0)
    if callback(event) is False: raise OpportunityBlocked('CALLER_FIT_RESERVATION_REJECTED')

def fit_window_scaler(windows,weights,metadata,cutoff,*,on_fit_started):
    source_pins();training_metadata(metadata,cutoff)
    if len(windows.keys)!=len(metadata) or not windows.qualified.all(): raise OpportunityBlocked('FULL_QUALIFIED_SCALER_DOMAIN_REQUIRED')
    fields=['signal_date','ticker','security_uid','asset_epoch']
    if not windows.keys[fields].reset_index(drop=True).equals(metadata[fields].reset_index(drop=True)):
        raise OpportunityBlocked('EXACT_ORDERED_WINDOW_TRAIN_KEYS_REQUIRED')
    return mechanism.fit_weighted_scaler(windows.values,dict(weights=weights),observed=windows.observed,
        on_fit_started=lambda _: _start(on_fit_started,kind='scaler',components=('SHARED_OBSERVED_WINDOW_SCALER',),backend_calls=0))

def transform_windows(windows,scaler,model):
    if model not in MODELS: raise OpportunityBlocked('SEQUENCE_MODEL_NOT_FROZEN')
    x=windows.values;mask=windows.observed
    z=scaler.transform(x.reshape(-1,len(FEATURES))).reshape(x.shape)
    z=np.where(mask,z,0.)
    if not np.isfinite(z).all(): raise OpportunityBlocked('NONFINITE_TRANSFORMED_WINDOW')
    both=np.concatenate((z,(~mask).astype(float)),axis=2)
    return both.reshape(len(both),-1) if model in ('TemporalMLP','LagLinear') else both

def _long_network():
    return mechanism._clone(sequence._network,{'HIDDEN':16},lambda c:
        (1,2,4,8,16) if c==(1,2,4,8) else ((2,4,8,16,32) if c==(2,4,8,16) else c))

def _sequence_bind(node,native,dependencies,n_channels=None):
    if n_channels!=64: raise OpportunityBlocked('SCALED_B32_PLUS_MASK32_REQUIRED')
    torch=sequence._torch(dependencies);factory=_long_network()
    def make(kind,n_features): return factory(node['family'].lower(),torch)
    return (mechanism._clone(native.fit_torch,{'SEED':SEED,'make_torch_network':make}),
            mechanism._clone(native.predict_torch,{'make_torch_network':make}),torch)

def _node(model_id,payload):
    # Extend only the frozen length enumeration. Original family/seed/parameters
    # validation remains in its owner, without mutating owner module globals.
    node=dict(model_id);extra=dict(payload);length=node.get('lookback')
    if length not in LOOKBACKS: raise OpportunityBlocked('FROZEN_LOOKBACK_REQUIRED')
    if length==60: node['lookback']=20;extra['lookback']=20
    result=mechanism._node(node,extra);result['lookback']=length
    return result

@dataclass
class Model:
    name:str
    lookback:int|None
    native:object
    metadata:dict
    def predict(self,X): return predict(self,X)

def fit_model(name,X,y,weights,metadata,cutoff,*,lookback=None,dependencies=(),on_fit_started=None):
    source_pins();training_metadata(metadata,cutoff)
    if name not in (*MODELS,'BayesianRidge'): raise OpportunityBlocked('NEW_ZOO_OR_UNSUPPORTED_MODEL_FORBIDDEN')
    if name in MODELS and lookback not in LOOKBACKS: raise OpportunityBlocked('FROZEN_LOOKBACK_REQUIRED')
    x=np.asarray(X,float);target=np.asarray(y,float);w=np.asarray(weights,float)
    if len(x)!=len(metadata) or target.shape!=(len(x),) or w.shape!=target.shape or not np.isfinite(x).all() or not np.isfinite(target).all() or not np.isfinite(w).all() or np.any(w<=0):
        raise OpportunityBlocked('FULL_FINITE_UNCLIPPED_TRAIN_INPUT_REQUIRED')
    if name=='BayesianRidge':
        if x.shape!=(len(metadata),len(FEATURES)): raise OpportunityBlocked('BAYESIAN_ORDERED_B32_REQUIRED')
        cfg={k:v for k,v in recipes()[name].items() if k!='uncertainty'}
        obj=BayesianRidge(**cfg)
        _start(on_fit_started,kind='posterior_fit',components=('COEFFICIENT_POSTERIOR_WITH_PLUGIN_ALPHA_LAMBDA',))
        obj.fit(x,target,sample_weight=w)
        info=dict(actual_backend_calls=1,parameter_components=1,learned_noise_precision=True,learned_weight_precision=True,
                  posterior_covariance_is_part_of_same_fit=True,source_pins=source_pins(),target=TARGET)
        return Model(name,None,obj,info),info
    family={'TemporalMLP':'MLP','LagLinear':'Ridge'}.get(name,name)
    if name in ('TemporalMLP','LagLinear'):
        if x.shape!=(len(metadata),lookback*64): raise OpportunityBlocked('EXACT_FLATTENED_HISTORY_SHAPE_REQUIRED')
    elif x.shape!=(len(metadata),lookback,64): raise OpportunityBlocked('EXACT_SEQUENCE_HISTORY_SHAPE_REQUIRED')
    node=dict(family=family,capacity='LOW',seed=SEED,objective=TARGET,lookback=lookback)
    components=('LINEAR_COEFFICIENT_STATE',) if name=='LagLinear' else ('TRUNK','POINT_HEAD')
    callback=lambda _: _start(on_fit_started,kind='model_fit',components=components)
    function=mechanism._clone(mechanism.fit,{'_node':_node,'_torch_bind':_sequence_bind}) if name in ('TCN','GRU','LSTM') else mechanism.fit
    obj,info=function(node,x,dict(target=target,weights=w),quantile=None,dependencies=dependencies,on_fit_started=callback)
    info=dict(info,actual_backend_calls=1,parameter_components=len(components),r6_recipe=recipes()[name],target=TARGET)
    return Model(name,lookback,obj,info),info

def predict(model,X):
    source_pins()
    if not isinstance(model,Model): raise OpportunityBlocked('R6_NATIVE_MODEL_TYPE_REQUIRED')
    if model.name=='BayesianRidge':
        x=np.asarray(X,float)
        if x.ndim!=2 or x.shape[1]!=len(FEATURES) or not np.isfinite(x).all(): raise OpportunityBlocked('BAYESIAN_PREDICTION_B32_REQUIRED')
        mu,sigma=model.native.predict(x,return_std=True)
        return dict(mean=mu,sigma=sigma,q10=mu-1.2815515655446004*sigma,uncertainty='EMPIRICAL_BAYES_PLUGIN_GAUSSIAN')
    function=mechanism._clone(mechanism.predict,{'_torch_bind':_sequence_bind}) if model.name in ('TCN','GRU','LSTM') else mechanism.predict
    return function(model.native,X)

def distribution_ensemble(outputs):
    if tuple(outputs)!=DISTRIBUTION_PACKET: raise OpportunityBlocked('COMPLETE_FIXED_DISTRIBUTION_PACKET_REQUIRED')
    mu=np.stack([np.asarray(outputs[m]['mean'],float) for m in DISTRIBUTION_PACKET])
    sigma=np.stack([np.asarray(outputs[m]['sigma'],float) for m in DISTRIBUTION_PACKET])
    if mu.ndim!=2 or sigma.shape!=mu.shape or not np.isfinite(mu).all() or not np.isfinite(sigma).all() or np.any(sigma<=0):
        raise OpportunityBlocked('FINITE_QUALIFIED_NATIVE_GAUSSIAN_PACKET_REQUIRED')
    mean=mu.mean(0);variance=(sigma**2+mu**2).mean(0)-mean**2
    component_q10=mu-1.2815515655446004*sigma
    lower=component_q10.min(0);lo=lower.copy();hi=component_q10.max(0)
    for _ in range(64):
        mid=(lo+hi)/2;cdf=ndtr((mid[None,:]-mu)/sigma).mean(0)
        lo=np.where(cdf<.1,mid,lo);hi=np.where(cdf>=.1,mid,hi)
    q10=(lo+hi)/2
    return dict(mean=mean,sigma=np.sqrt(np.maximum(variance,0.)),q10=q10,
        q10_lower_bound=lower,lower_tail_semantics='FIXED_EQUAL_GAUSSIAN_MIXTURE_CDF_Q10_UNCALIBRATED_COVERAGE',
        quantile_bisection_iterations=64,optimizer_calls=0,new_fits=0)

def fit_fusion(history,cutoff,method,learn):
    source_pins()
    if method not in FUSIONS[:-1]: raise OpportunityBlocked('NATIVE_FUSION_METHOD_OR_RESIDUAL_INTERFACE_REQUIRED')
    return fusion.fit_meta(history,cutoff,method,PACKET,learn,seeds=(SEED,),fixed_weights=tuple([1/len(PACKET)]*len(PACKET)))

def fit_residual(history,cutoff,*,on_fit_started):
    source_pins()
    h,cut,_=fusion.prepare_history(history,cutoff,('TCN',))
    if any(c not in h for c in FEATURES): raise OpportunityBlocked('PRIOR_GENUINE_TCN_PLUS_B32_REQUIRED')
    # Private, explicitly named alias to reuse the old Ridge residual estimator;
    # scientific primary remains TCN, and the old HGB object is never loaded.
    adapted=h.copy();adapted['HGB_raw']=h['TCN__mu'];adapted['source_fit_cutoff']=h['TCN__source_cutoff']
    for c in ('signal_date','execution_date','label_end_date','label_mature_date','source_fit_cutoff'):
        if c in adapted: adapted[c]=pd.to_datetime(adapted[c],utc=True).dt.tz_localize(None)
    _start(on_fit_started,kind='residual_compound_fit',components=('B32_SCALER','RIDGE_RESIDUAL'),backend_calls=2)
    out=residual.fit_oof_residual(adapted,cut.tz_localize(None),'hgb_then_ridge')
    out.update(method=FUSIONS[-1],primary='TCN',sigma=None,requires_later_true_composite_OOF_calibration=True)
    return out


def fit_native_uncertainty(history,cutoff,name,learn):
    """One existing genuine-earlier-OOF error statistic, no affine/probability map.

    Point RMS is an error-scale proxy only; it never creates Gaussian q10.
    Native Gaussian scale multipliers preserve the declared distribution family.
    Earliest 2022 has no prior genuine head OOF and must remain uncertainty-blocked.
    """
    source_pins()
    if name in MODELS:
        result=fusion.fit_meta(history,cutoff,'equal',(name,),learn,seeds=(SEED,),fixed_weights=(1.,))
        if not result.get('qualified'): return result
        return dict(sigma_error_proxy=result['prior_OOF_error_RMS'],cutoff=result['cutoff'],
                    mean_transform='IDENTITY_NATIVE_B5D',q10=None,
                    uncertainty='GENUINE_EARLIER_NATIVE_OOF_ERROR_RMS_NOT_PROBABILITY_OR_QUANTILE',learned_states=1)
    if name not in ('BayesianRidge','FixedDistributionMixture'):
        raise OpportunityBlocked('UNCERTAINTY_HEAD_NOT_FROZEN')
    result=fusion.fit_native_scale_proxy(history,cutoff,(name,),name+'__mu',name+'__scale',learn,name=name)
    return dict(result,mean_transform='IDENTITY_NATIVE_B5D',uncertainty='GENUINE_EARLIER_NATIVE_GAUSSIAN_SCALE_PROXY_UNCALIBRATED_COVERAGE')


def sample_training_keys(metadata,*,cap=48000):
    """R6 source-only fixed sampling; no y/prediction parameter or row mutation."""
    import hashlib
    if cap!=48000:raise OpportunityBlocked('FROZEN_SEQUENCE_TRAINING_CAP_REQUIRED')
    forbidden=set(FEATURES)|{'y_open5','raw_mu','native_mu','sigma','return','NAV'}
    if forbidden.intersection(metadata.columns):raise OpportunityBlocked('SAMPLING_METADATA_ONLY_NO_VALUES')
    need={'signal_date','ticker','security_uid','asset_epoch','identity_qualified','source_qualified'}
    if not need.issubset(metadata):raise OpportunityBlocked('SAMPLE_QUALIFIED_IDENTITY_REQUIRED')
    data=metadata.copy();data['signal_date']=_dates(data.signal_date)
    if data.duplicated(['signal_date','ticker']).any() or not data.security_uid.map(_known).all() or not data.asset_epoch.map(_known).all() or not _true(data.identity_qualified).all() or not _true(data.source_qualified).all():raise OpportunityBlocked('SAMPLE_UNKNOWN_UID_OR_AMBIGUOUS_KEYS')
    dates=sorted(data.signal_date.unique())
    if not dates or len(dates)>cap:raise OpportunityBlocked('ALL_SAMPLE_DATES_MUST_BE_PRESERVED')
    counts=data.groupby('signal_date',sort=True).size().to_dict();quota={d:0 for d in dates};left=min(cap,len(data))
    while left:
        active=[d for d in dates if quota[d]<counts[d]]
        step=max(1,left//len(active))
        for day in active:
            add=min(step,counts[day]-quota[day],left);quota[day]+=add;left-=add
    selected=[]
    for day,rows in data.groupby('signal_date',sort=True):
        ranked=rows.copy()
        ranked['_fixed_hash']=[hashlib.sha256(json.dumps([SEED,pd.Timestamp(day).date().isoformat(),uid,epoch],separators=(',',':')).encode()).hexdigest() for uid,epoch in rows[['security_uid','asset_epoch']].itertuples(index=False,name=None)]
        selected.append(ranked.sort_values(['_fixed_hash','ticker'],kind='stable').head(quota[day]).drop(columns='_fixed_hash'))
    result=pd.concat(selected,ignore_index=True).sort_values(['signal_date','ticker'],kind='stable').reset_index(drop=True)
    keys=['signal_date','ticker','security_uid','asset_epoch']
    def digest(frame):return hashlib.sha256(pd.util.hash_pandas_object(frame[keys].sort_values(['signal_date','ticker'],kind='stable'),index=False).to_numpy().tobytes()).hexdigest()
    receipt=dict(scientific_identity='R6_FIXED_DATE_UID_EPOCH_HASH_CAP_48000',cap=cap,seed=SEED,full_rows=len(data),selected_rows=len(result),all_dates=len(dates),full_keys_sha256=digest(data),selected_keys_sha256=digest(result),date_quotas={pd.Timestamp(d).date().isoformat():quota[d] for d in dates},target_prediction_reads=0,failure_key_replacement=False)
    result.attrs['sequence_training_sample']=receipt
    return result,receipt


def physical_dag():
    """Metadata-only exact component slots; caps are upper bounds, not quotas."""
    nodes=[]
    for slot in slot_matrix():
        cohort=slot['cohort']+'_L'+str(slot['lookback']) if slot['phase']=='INNER' else slot['cohort']
        node=cohort+':'+slot['model']
        nodes.append(dict(node_id=node,stage='sequence',phase=slot['phase'],year=slot['year'],cohort=slot['cohort'],lookback=slot['lookback'],family=slot['model'],seed=SEED,backend_calls=1,
            component_ids=['LINEAR_COEFFICIENT_STATE'] if slot['model']=='LagLinear' else ['TRUNK','POINT_HEAD'],learned_units=slot['parameter_components'],dependencies=['FROZEN_B5D_METADATA_MATURE_KEYS','EXACT_UID_EPOCH_B32_HISTORY','FIXED_48000_DATE_UID_HASH_SAMPLE','TRAIN_ONLY_COMMON_WINDOW_SCALER'],input_blocker='SOURCE_IDENTITY_MATURITY_OR_INNER_NINE_TRIALS_INCOMPLETE',output_role='CURRENT_ELIGIBLE_ALPHA_OOF'))
    for year in YEARS:
        for cohort in [f['id'] for f in inner_folds(year)]+[f'ANNUAL_{year}']:
            for length in LOOKBACKS:
                nodes.append(dict(node_id=cohort+'_L'+str(length)+':SCALER',stage='sequence_scaler',year=year,cohort=cohort,lookback=length,backend_calls=0,component_ids=['TRAIN_ONLY_OBSERVED_WINDOW_SCALER'],learned_units=1,
                    conditional='ANNUAL_ONLY_IF_AT_LEAST_ONE_MODEL_SELECTED_THIS_LENGTH' if cohort.startswith('ANNUAL') else 'ALL_THREE_FIXED_LENGTHS',dependencies=['SAME_FOLD_FIXED48000_SOURCE_METADATA_KEYS','OBSERVED_SAME_UID_EPOCH_WINDOW']))
        for kind in ('B32_SCALER','COEFFICIENT_POSTERIOR_WITH_PLUGIN_PRECISIONS'):
            nodes.append(dict(node_id=f'ANNUAL_{year}:BayesianRidge:'+kind,stage='bayes',year=year,backend_calls=int(kind!='B32_SCALER'),component_ids=[kind],learned_units=1,dependencies=['FULL_SOURCE_QUALIFIED_MATURE_B32_KEYS_UNSAMPLED'],output_role='CURRENT_ELIGIBLE_ALPHA_OOF'))
    for year in (2023,2024,2025):
        for role in ('MEMBER_SCALER','CONTEXT_SCALER','TARGET_RMS'):
            for phase in ('probe','full'):
                nodes.append(dict(node_id=f'L_{year}:{role}:{phase}',stage='fusion',year=year,phase=phase,backend_calls=0,component_ids=[role],learned_units=1,dependencies=['COMPLETE_SIX_MEMBER_EARLIER_GENUINE_OOF','PROBE_ONLY_PURGED_FIRST_HALF' if phase=='probe' else 'FULL_EARLIER_MATURE_OOF'],shared='SAME_ACTUAL_ROWS_WEIGHTS_AXES_ROLE_PHASE'))
        for method in FUSIONS[:-1]:
            if method not in ('equal','median'):
                for phase in ('probe','full'):
                    components=['TRUNK','POINT_OR_SOFTMAX_HEAD'] if method in ('mlp_stack','mlp_gate') else ['FITTED_META_PARAMETERS']
                    nodes.append(dict(node_id=f'L_{year}:{method}:{phase}',stage='fusion',year=year,phase=phase,method=method,seed=SEED,backend_calls=1,component_ids=components,learned_units=len(components),dependencies=['COMPLETE_SIX_MEMBER_EARLIER_GENUINE_OOF','SAME_PHASE_PREPROCESSING'],input_blocker='NO_PACKET_SHRINK;PRIOR_PROBE_INSUFFICIENT_OR_SOURCE_CLOCK_INVALID'))
            nodes.append(dict(node_id=f'L_{year}:{method}:RMS',stage='fusion',year=year,method=method,backend_calls=0,component_ids=['GENUINE_EARLIER_STATIC_OR_PROBE_HELDOUT_ERROR_RMS'],learned_units=1,dependencies=['EARLIER_GENUINE_OOF_STATIC' if method in ('equal','median') else 'CHRONOLOGICAL_PROBE_HELDOUT'],forbidden='IN_FIT_ERROR;AFFINE_PROBABILITY_QUANTILE_COVERAGE'))
        nodes.append(dict(node_id=f'R6_RESIDUAL_{year}',stage='fusion',year=year,method=FUSIONS[-1],backend_calls=2,component_ids=['B32_SCALER','RIDGE_RESIDUAL'],learned_units=2,dependencies=['TCN_EARLIER_GENUINE_OOF','SAME_B32_MATURE_PRIOR_KEYS'],input_blocker='TCN_PRIOR_UNAVAILABLE'))
        if year>2023:nodes.append(dict(node_id=f'R6_RESIDUAL_{year}:COMPOSITE_RMS',stage='fusion',year=year,backend_calls=0,component_ids=['EARLIER_GENUINE_COMPOSITE_OOF_ERROR_RMS'],learned_units=1,dependencies=['GENUINE_ANNUAL_META_OOF_EARLIER_YEAR'],input_blocker='NO_PRIOR_GENUINE_COMPOSITE_OUTPUT'))
        for member in (*MODELS,'BayesianRidge','FixedDistributionMixture'):
            nodes.append(dict(node_id=f'UNCERTAINTY_{year}:{member}',stage='native_uncertainty',year=year,member=member,backend_calls=0,component_ids=['GENUINE_PRIOR_NATIVE_ERROR_RMS' if member in MODELS else 'GENUINE_PRIOR_NATIVE_SCALE_MULTIPLIER'],learned_units=1,dependencies=['EARLIER_GENUINE_POINT_OR_NATIVE_GAUSSIAN_OOF'],input_blocker='NO_PRIOR_GENUINE_SCALE_OR_POINT_OOF',mean_transform='IDENTITY_NATIVE_B5D'))
    counts={stage:sum(n['learned_units'] for n in nodes if n['stage']==stage) for stage in ('sequence','sequence_scaler','bayes','fusion','native_uncertainty')}
    assert counts==dict(sequence=360,sequence_scaler=48,bayes=8,fusion=107,native_uncertainty=21)
    return dict(schema='B_R6_OPPORTUNITY_PHYSICAL_COMPONENT_DAG_V1',research_id=ID,nodes=nodes,learned_component_upper=counts,total_parameter_component_upper=sum(counts.values()),sequence_backend_calls=200,sequence_train_scaler_upper=48,fusion_actual_components_upper=107,fusion_earlier_conservative_cap=115,deterministic_distribution_fits=0,prior_history_not_reset=True,scientific_retry=0)
