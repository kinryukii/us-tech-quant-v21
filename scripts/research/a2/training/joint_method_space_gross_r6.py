"""R6 Gross-only learner adapter; existing native estimator, no new account."""
import numpy as np
import pandas as pd
from scripts.research.a2.training import stateful_mechanism_models as native
from scripts.research.a2.inference.joint_method_space_action_r6 import GRID,quantize_gross
FAMILIES=dict(RIDGE='Ridge',HGB='HGB',CATBOOST='CatBoost',MLP='MLP',QUANTILE='HGBQuantile')
SEED=20260928
TARGET='FIXED_G_GRID_ONE_STEP_REFERENCE_UTILITY_H5_NOT_ACCOUNT_NAV_OPTIMUM'
FEATURES=('mean_mu','mean_sigma','positive_mu_fraction','diagonal_vol_proxy_5d','mean_liquidity','mean_downside_vol20','vol20_dispersion')

def recipes():
    return dict(target=TARGET,feature_order=FEATURES,capacity='LOW',seed=SEED,
      learner_parameters={k:native.parameters(v,'LOW') for k,v in FAMILIES.items()},
      quantile=.1,outer_years=(2023,2024,2025),fixed_mu_packet='R4_EQUAL_GENUINE_OOF',
      reference='signal-known top20 equal names; no Raw score/rank; all required UID/features/targets qualified, no support shrinking by outcome',
      variance_proxy='5 * sum(q_i^2 * PIT32 realized_vol20_i^2), explicit diagonal approximation; no new covariance fit for target',
      aggregation='complete genuine eligible input domain, signal-known mu descending/ticker ascending top20; every required reference target/identity/source present, no date drop',
      previous_reference_G=1.,risk_aversion=.5,one_way_bps=10,grid=GRID.tolist(),
      label_maturity='all reference labels execution/end/mature < annual cutoff before body read',
      components_upper=21,estimator_invocations_upper=15,shared_scaler_upper=3,
      qualifier='not a realized continuous account reward; outer outcome never tunes target or capacity')

def target_grid(reference_h5,variance_proxy,*,previous_g=1.,cost_bps=10):
    y=np.asarray(reference_h5,float);var=np.asarray(variance_proxy,float)
    if y.shape!=var.shape or not np.isfinite(y).all() or not np.isfinite(var).all() or np.any(var<0) or previous_g!=1. or cost_bps!=10:raise ValueError('EXACT_FROZEN_GROSS_TARGET_REQUIRED')
    values=y[...,None]*GRID-.5*var[...,None]*GRID**2-(cost_bps/10000.)*np.abs(GRID-previous_g)
    return GRID[np.argmax(values,axis=-1)]

def fit(kind,x,target,weights,*,dates,mature_dates,cutoff,dependencies=(),on_fit_started=None):
    if kind not in FAMILIES:raise ValueError('UNREGISTERED_GROSS_FAMILY')
    cutoff=pd.Timestamp(cutoff);dates=pd.DatetimeIndex(dates);mature=pd.DatetimeIndex(mature_dates)
    if cutoff>pd.Timestamp('2026-01-01') or len(dates)!=len(x) or len(mature)!=len(x) or dates.hasnans or mature.hasnans or not (dates<cutoff).all() or not (mature<cutoff).all():raise ValueError('PAST_MATURE_GROSS_TRAINING_REQUIRED')
    target=np.asarray(target,float)
    if not np.isin(target,GRID).all():raise ValueError('FROZEN_G_GRID_LABEL_REQUIRED')
    # Caller fits one shared train-only scaler and counts it before this method.
    payload=dict(family=FAMILIES[kind],capacity='LOW',seed=SEED,objective='GROSS',target=target,weights=np.asarray(weights,float))
    return native.fit(kind,x,payload,quantile=.1 if kind=='QUANTILE' else None,dependencies=dependencies,on_fit_started=on_fit_started)

def predict(model,x):
    packet=native.predict(model,x)
    value=packet['q10'] if model.node['family']=='HGBQuantile' else packet.get('mean',packet.get('point'))
    if value is None:raise ValueError('GROSS_PREDICTION_PACKET_REQUIRED')
    return np.asarray([quantize_gross(float(np.clip(v,0,1))) for v in value])


def aggregate_reference(frame,cutoff,*,structural_constant_free=False,certificate_authority=None):
    """Caller-qualified genuine OOF table to date-level Gross supervision.

    Validate the whole requested structural domain before inspecting targets;
    top20 selection uses only signal-known forecast and a fixed ticker tie break.
    Never omit a bad date or an unqualified required reference constituent.
    """
    required={'signal_date','ticker','security_uid','asset_epoch','fit_cutoff',
        'execution_date','label_end_date','label_mature_date','source_qualified',
        'identity_qualified','genuine_chronological_oof','mu','sigma','y_open5',
        'realized_vol_20d','downside_vol_20d','avg_dollar_volume_20d'}
    if type(structural_constant_free) is not bool:raise ValueError('EXPLICIT_CONSTANT_FREE_MODE_REQUIRED')
    if structural_constant_free:required.remove('sigma')
    elif certificate_authority is not None:raise ValueError('TARGET_CERTIFICATE_REQUIRES_NEW_CONSTANT_FREE_ENTRY')
    if not required.issubset(frame):raise ValueError('COMPLETE_GROSS_REFERENCE_COLUMNS_REQUIRED')
    cutoff=pd.Timestamp(cutoff)
    if cutoff>pd.Timestamp('2026-01-01'):raise ValueError('PRE2026_GROSS_REFERENCE_REQUIRED')
    clocks={k:pd.to_datetime(frame[k],errors='raise',utc=True).dt.tz_convert(None) for k in ('signal_date','fit_cutoff','execution_date','label_end_date','label_mature_date')}
    if any(x.isna().any() for x in clocks.values()) or not (clocks['signal_date']<cutoff).all() or not (clocks['fit_cutoff']<clocks['signal_date']).all() or any(not (clocks[k]<cutoff).all() for k in ('execution_date','label_end_date','label_mature_date')):raise ValueError('PRIOR_GENUINE_OOF_AND_MATURE_TARGET_REQUIRED')
    for k in ('source_qualified','identity_qualified','genuine_chronological_oof'):
        if not frame[k].map(lambda x:type(x) in (bool,np.bool_) and bool(x)).all():raise ValueError('FULL_GROSS_REFERENCE_METADATA_UNQUALIFIED')
    if frame.duplicated(['signal_date','ticker']).any() or frame.security_uid.isna().any() or frame.asset_epoch.isna().any():raise ValueError('EXACT_GROSS_UID_DOMAIN_REQUIRED')
    if not frame.security_uid.map(lambda v:isinstance(v,str) and bool(v.strip()) and not v.upper().startswith(('UNKNOWN','TICKER_','HELD_'))).all() or frame.duplicated(['signal_date','security_uid']).any():raise ValueError('EXACT_GROSS_KNOWN_UNIQUE_UID_REQUIRED')
    num=['mu','realized_vol_20d','downside_vol_20d','avg_dollar_volume_20d']+([] if structural_constant_free else ['sigma'])
    if not np.isfinite(frame[num].to_numpy(float)).all() or (not structural_constant_free and (frame.sigma<0).any()) or (frame.realized_vol_20d<0).any() or (frame.downside_vol_20d<0).any():raise ValueError('FULL_GROSS_FEATURE_DOMAIN_NONFINITE')
    result=[]
    for day,all_rows in frame.groupby('signal_date',sort=True):
        ref=all_rows.sort_values(['mu','ticker'],ascending=[False,True],kind='stable').head(20)
        if len(ref)!=20:raise ValueError('FIXED_TOP20_GROSS_REFERENCE_NOT_COMPLETE')
        y=ref.y_open5.to_numpy(float)
        finite_y=np.isfinite(y).all()
        if not finite_y and not structural_constant_free:raise ValueError('ALL_REFERENCE_TARGETS_REQUIRED_NO_DATE_DROP')
        vol=ref.realized_vol_20d.to_numpy(float)
        variance=5*float(np.square(vol).sum())/400
        target=(float(target_grid(np.asarray([y.mean()]),np.asarray([variance]))[0]) if finite_y else
            _certificate_target(ref,variance,cutoff,certificate_authority))
        result.append(dict(signal_date=day,label_mature_date=pd.to_datetime(ref.label_mature_date).max(),
            mean_mu=float(ref.mu.mean()),**({} if structural_constant_free else dict(mean_sigma=float(ref.sigma.mean()))),positive_mu_fraction=float((ref.mu>0).mean()),
            diagonal_vol_proxy_5d=float(np.sqrt(variance)),mean_liquidity=float(ref.avg_dollar_volume_20d.mean()),
            mean_downside_vol20=float(ref.downside_vol_20d.mean()),vol20_dispersion=float(np.std(vol)),
            target=target,
            reference_tickers=tuple(ref.ticker)))
    return pd.DataFrame(result)


def fit_ridge_annual(train_reference, infer_reference, *, cutoff, learn, dependencies=()):
    """Compose one original R6 RIDGE fold over already-qualified top20 references.

    The caller owns complete source/target/OOF qualification and the durable
    ``learn(kind, name, inputs, compute, parameters)`` transaction. It must record
    STARTED before compute and may return an identical completed object instead.
    Inputs contain the actual fitting arrays; no reader/registry/account is made
    here. Each callback compute is single-use. Three learned states are required:
    prior OOF error RMS, one shared scaler, one LOW RIDGE. Two scaler transforms
    and one predictor inference are also durable-owned physical operations.
    Inference labels are
    never accessed. A cash-inclusive target requires its own caller-frozen
    descendant identity; this function does not claim old-target equivalence.
    """
    if not callable(learn):
        raise ValueError('DURABLE_GROSS_LEARN_OWNER_REQUIRED')
    cut = pd.Timestamp(cutoff)
    if pd.isna(cut):
        raise ValueError('EXACT_R6_ANNUAL_GROSS_CUTOFF_REQUIRED')
    if cut.tzinfo is not None:
        cut = cut.tz_convert('UTC').tz_localize(None)
    if cut.year not in (2023, 2024, 2025) or cut != pd.Timestamp(year=cut.year, month=1, day=1):
        raise ValueError('EXACT_R6_ANNUAL_GROSS_CUTOFF_REQUIRED')
    end = pd.Timestamp(year=cut.year + 1, month=1, day=1)
    # Both entire requested domains are checked before the first learned state.
    _validate_annual_reference(train_reference, True, cut)
    _validate_annual_reference(infer_reference, False, cut)
    train = train_reference.copy()
    owned,local,physical_kinds=_annual_operation_owner(learn,cut)
    def rms_compute():
        value = float(np.sqrt(np.mean(np.square(train.y_open5.to_numpy(float) - train.mu.to_numpy(float)))))
        if not np.isfinite(value) or value <= 0:
            raise ValueError('NONFINITE_GROSS_PRIOR_ERROR_RMS')
        return value
    rms = owned('R4_EQUAL_PRIOR_RMS', 'bridge_calibration',
        {k: train[k].to_numpy(copy=True) for k in ('signal_date', 'security_uid', 'asset_epoch', 'mu', 'y_open5')},
        rms_compute, dict(role='UNCALIBRATED_NATIVE_OOF_ERROR_SCALE', packet='R4_EQUAL_GENUINE_OOF', weighting='EQUAL_REFERENCE_CONSTITUENT_ROWS'))
    if not np.isscalar(rms) or not np.isfinite(rms) or rms <= 0:
        raise ValueError('GENUINE_PRIOR_GROSS_ERROR_RMS_REQUIRED')
    train['sigma'] = float(rms)
    supervision = aggregate_reference(train, cut)
    # Reuse the existing pure inference aggregation; no Source/runner is invoked.
    from scripts.research.a2.training.joint_method_space_gross_execution_r6 import inference_reference
    states = inference_reference(infer_reference, float(rms))
    return _fit_ridge_annual_aggregates(supervision,states,cut,owned,local,physical_kinds,dependencies,
        features=FEATURES,prior_rms=rms,learned_count=3,physical_count=6,training_rows=len(train))


def _validate_annual_reference(frame,training,cut,*,allow_target_only=False):
    end=pd.Timestamp(year=cut.year+1,month=1,day=1)
    common = {'signal_date', 'ticker', 'security_uid', 'asset_epoch', 'fit_cutoff',
        'source_qualified', 'identity_qualified', 'genuine_chronological_oof',
        'mu', 'realized_vol_20d', 'downside_vol_20d', 'avg_dollar_volume_20d'}
    truth = {'execution_date', 'label_end_date', 'label_mature_date', 'y_open5'}
    if not isinstance(frame, pd.DataFrame) or frame.empty or not (common | (truth if training else set())).issubset(frame):
        raise ValueError('NONEMPTY_COMPLETE_GROSS_REFERENCE_REQUIRED')
    clocks = {k: pd.to_datetime(frame[k], errors='raise', utc=True).dt.tz_convert(None)
        for k in ('signal_date', 'fit_cutoff', * (('execution_date', 'label_end_date', 'label_mature_date') if training else ()))}
    if any(c.isna().any() for c in clocks.values()) or not (clocks['fit_cutoff'] < clocks['signal_date']).all():
        raise ValueError('GENUINE_PRIOR_GROSS_SOURCE_CLOCK_REQUIRED')
    signal = clocks['signal_date']
    if (training and (not (signal < cut).all() or any(not (clocks[k] < cut).all() for k in truth if k != 'y_open5'))
            or not training and not ((signal >= cut) & (signal < end)).all()):
        raise ValueError('PAST_MATURE_TRAIN_AND_FROZEN_ANNUAL_INFERENCE_REQUIRED')
    if training and (not (clocks['execution_date'] > signal).all()
            or not (clocks['label_end_date'] > clocks['execution_date']).all()
            or not (clocks['label_mature_date'] >= clocks['label_end_date']).all()):
        raise ValueError('ORDERED_GROSS_LABEL_CLOCKS_REQUIRED')
    if training and 'label_available_at' in frame:
        available = pd.to_datetime(frame.label_available_at, errors='raise', utc=True).dt.tz_convert(None)
        required_known=(~frame.y_open5.isna()) if allow_target_only else np.ones(len(frame),dtype=bool)
        if available[required_known].isna().any() or not (available[available.notna()] < cut).all():
            raise ValueError('GROSS_LABEL_AVAILABILITY_NOT_BEFORE_CUTOFF')
    for flag in ('source_qualified', 'identity_qualified', 'genuine_chronological_oof'):
        if not frame[flag].map(lambda v: type(v) in (bool, np.bool_) and bool(v)).all():
            raise ValueError('FULL_GROSS_REFERENCE_METADATA_UNQUALIFIED')
    if (frame.duplicated(['signal_date', 'ticker']).any()
            or frame.duplicated(['signal_date', 'security_uid']).any()
            or frame.asset_epoch.isna().any()
            or not frame.security_uid.map(lambda v: isinstance(v, str) and bool(v.strip())
                and not v.upper().startswith(('UNKNOWN', 'TICKER_', 'HELD_'))).all()):
        raise ValueError('EXACT_GROSS_KNOWN_UNIQUE_UID_REQUIRED')
    if not frame.groupby('signal_date', sort=False).size().eq(20).all():
        raise ValueError('EXACT_PRESELECTED_TOP20_REFERENCE_REQUIRED_NO_SUPPORT_SHRINKING')
    numbers = ['mu', 'realized_vol_20d', 'downside_vol_20d', 'avg_dollar_volume_20d'] + (['y_open5'] if training and not allow_target_only else [])
    if (not np.isfinite(frame[numbers].to_numpy(float)).all()
            or (frame[['realized_vol_20d', 'downside_vol_20d']].to_numpy(float) < 0).any()):
        raise ValueError('FULL_GROSS_REFERENCE_FINITE_REQUIRED')

    if training and allow_target_only and not (np.isfinite(frame.y_open5.to_numpy(float))|frame.y_open5.isna().to_numpy()).all():
        raise ValueError('TARGET_ONLY_MISSING_NAN_NOT_INFINITY_REQUIRED')


def _annual_operation_owner(learn,cut):
    local = {}
    physical_kinds = {}
    learned_tag = 'estimator_learned_state_fit'
    def owned(name, physical_kind, inputs, compute, parameters):
        node = f'GROSS:{name}:{cut.year}'
        local[node] = 0
        physical_kinds[node] = physical_kind
        def once():
            if local[node]:
                raise ValueError('DUPLICATE_GROSS_COMPUTE_FORBIDDEN')
            local[node] = 1
            return compute()
        kind = 'deterministic_transform' if physical_kind == 'deterministic_transform' else learned_tag
        return learn(kind, node, inputs, once,
            dict(parameters, physical_kind=physical_kind, cutoff=str(cut.date())))
    return owned,local,physical_kinds


def _fit_ridge_annual_aggregates(supervision,states,cut,owned,local,physical_kinds,dependencies,*,features,prior_rms,learned_count,physical_count,training_rows):
    x = supervision[list(features)].to_numpy(float)
    infer_x = states[list(features)].to_numpy(float)
    weights = np.ones(len(x))
    if not len(x) or not len(infer_x) or not np.isfinite(x).all() or not np.isfinite(infer_x).all():
        raise ValueError('FINITE_NONEMPTY_GROSS_AGGREGATES_REQUIRED')
    def one_native_fit(compute):
        started = []
        def ack(component):
            if started:
                raise ValueError('UNFROZEN_ADDITIONAL_GROSS_BACKEND')
            started.append(component)
        result = compute(ack)
        if len(started) != 1 or result[1].get('actual_fit_count') != 1:
            raise ValueError('EXACT_ONE_NATIVE_GROSS_FIT_ACK_REQUIRED')
        return result
    scaler, scaler_meta = owned('SCALER', 'scaler', dict(X=x.copy(), weights=weights.copy()),
        lambda: one_native_fit(lambda ack: native.fit_weighted_scaler(x, {'weights': weights}, on_fit_started=ack)),
        dict(feature_order=features, weighting='DATE_EQUAL', scaler='EXISTING_NATIVE_WEIGHTED_STANDARD_SCALER'))
    scaled = np.asarray(owned('SCALER_TRANSFORM_TRAIN', 'deterministic_transform',
        dict(X=x.copy(), scaler_node=f'GROSS:SCALER:{cut.year}'), lambda: scaler.transform(x),
        dict(operation='SCALER_TRANSFORM_TRAIN', feature_order=features)), float)
    scaled_infer = np.asarray(owned('SCALER_TRANSFORM_INFER', 'deterministic_transform',
        dict(X=infer_x.copy(), scaler_node=f'GROSS:SCALER:{cut.year}'), lambda: scaler.transform(infer_x),
        dict(operation='SCALER_TRANSFORM_INFER', feature_order=features)), float)
    if scaled.shape != x.shape or scaled_infer.shape != infer_x.shape or not np.isfinite(scaled).all() or not np.isfinite(scaled_infer).all():
        raise ValueError('FINITE_EXACT_GROSS_SCALED_SHAPES_REQUIRED')
    target = supervision.target.to_numpy(float)
    model, fit_meta = owned('RIDGE', 'model_fit', dict(X=scaled.copy(), target=target.copy(), weights=weights.copy(),
        dates=supervision.signal_date.to_numpy(copy=True), mature_dates=supervision.label_mature_date.to_numpy(copy=True)),
        lambda: one_native_fit(lambda ack: fit('RIDGE', scaled, target, weights,
            dates=supervision.signal_date, mature_dates=supervision.label_mature_date, cutoff=cut,
            dependencies=dependencies, on_fit_started=ack)),
        dict(family='Ridge', capacity='LOW', seed=SEED, learner_parameters=native.parameters('Ridge', 'LOW'), target=TARGET, feature_order=features))
    if (scaler_meta.get('actual_fit_count') != 1 or fit_meta.get('actual_fit_count') != 1
            or model.node.get('family') != 'Ridge' or model.node.get('capacity') != 'LOW'
            or model.node.get('seed') != SEED):
        raise ValueError('EXACT_EXISTING_GROSS_RIDGE_ARTIFACT_REQUIRED')
    packet = owned('RIDGE_INFER', 'deterministic_transform',
        dict(X=scaled_infer.copy(), model_node=f'GROSS:RIDGE:{cut.year}'),
        lambda: native.predict(model, scaled_infer),
        dict(operation='RIDGE_NATIVE_PREDICT', feature_order=features))
    raw_prediction = packet.get('mean', packet.get('point'))
    if raw_prediction is None:
        raise ValueError('GROSS_PREDICTION_PACKET_REQUIRED')
    raw_prediction = np.asarray(raw_prediction, float)
    if raw_prediction.shape != (len(states),) or not np.isfinite(raw_prediction).all():
        raise ValueError('FINITE_EXACT_GROSS_PREDICTION_REQUIRED')
    output = states[['signal_date']].copy()
    output['gross'] = [quantize_gross(float(np.clip(v, 0, 1))) for v in raw_prediction]
    output['method'] = 'RIDGE'
    output['fit_cutoff'] = cut
    output['strict_PIT_promotion_eligible'] = False
    output['full_held_policy_qualified'] = False
    return dict(model=model, scaler=scaler, prior_rms=None if prior_rms is None else float(prior_rms), predictions=output,
        metadata=dict(method='RIDGE', year=cut.year, target=TARGET, required_learned_states=learned_count,
            actual_local_learned_states=sum(n for node, n in local.items() if physical_kinds[node] != 'deterministic_transform'),
            required_physical_operations=physical_count, actual_local_physical_operations=sum(local.values()),
            local_compute_by_node=local, physical_kind_by_node=physical_kinds,
            reference_training_rows=training_rows, supervision_dates=len(supervision), inference_dates=len(states),
            feature_order=features, seed=SEED, learner_parameters=native.parameters('Ridge', 'LOW'),
            scaler_metadata=scaler_meta, model_metadata=fit_meta,
            inference_role='CURRENT_ELIGIBLE_ALPHA_OOF_NOT_FULL_HELD_POLICY', strict_PIT_promotion_eligible=False))


CONSTANT_FREE_FEATURES=tuple(k for k in FEATURES if k!='mean_sigma')
_TARGET_CERTIFICATE_SHA='d4d2ab0187728f51dc6a8a9176553b4dc9ffd31fe98f6de17ab18cd8c607d3ba'

_TARGET_CERTIFICATE_2024_SHA='c887a1f89096f38cb466e13e0b34cc0dff40a010735d00b2c50e62690eb967ea'

def _target_certificate_packets(authority):
    import hashlib,json
    if not isinstance(authority,dict) or set(authority)!={'certificate_bytes'}:
        raise ValueError('EXACT_FROZEN_TARGET_CERTIFICATE_PHYSICAL_PIN_REQUIRED')
    raw=authority['certificate_bytes']
    raw=(raw,) if type(raw) is bytes else raw
    if type(raw) not in (tuple,list) or not raw or any(type(v) is not bytes for v in raw):
        raise ValueError('EXACT_FROZEN_TARGET_CERTIFICATE_PHYSICAL_PIN_REQUIRED')
    fingerprints=[hashlib.sha256(v).hexdigest() for v in raw]
    if (len(set(fingerprints))!=len(fingerprints)
            or any(v not in {_TARGET_CERTIFICATE_SHA,_TARGET_CERTIFICATE_2024_SHA} for v in fingerprints)):
        raise ValueError('EXACT_FROZEN_TARGET_CERTIFICATE_PHYSICAL_PIN_REQUIRED')
    packets=[]
    schemas={_TARGET_CERTIFICATE_SHA:'B_THREE_DATE_GROSS_GRID_NONNEGATIVE_CASH_TARGET_CERTIFICATE_R1',
        _TARGET_CERTIFICATE_2024_SHA:'B_FROZEN_GROSS_GRID_NONNEGATIVE_CASH_TARGET_CERTIFICATE_R2'}
    for sha,body in zip(fingerprints,raw):
        packet=json.loads(body)
        if (packet.get('schema')!=schemas[sha] or packet.get('grid')!=GRID.tolist()
                or packet.get('previous_g')!=1. or packet.get('cost_bps')!=10
                or packet.get('risk_aversion')!=.5):
            raise ValueError('ORIGINAL_TARGET_GRID_COST_PREVIOUS_G_CERTIFICATE_REQUIRED')
        packets.append((sha,packet))
    return packets

def _certificate_target(ref,variance,cutoff,authority):
    """Exact frozen profile(s), including a date with two missing cash claims."""
    import re
    from fractions import Fraction
    packets=_target_certificate_packets(authority)
    if len(ref)!=20 or ref.ticker.nunique()!=20 or ref.security_uid.nunique()!=20:
        raise ValueError('TARGET_CERTIFICATE_COMPLETE_TWENTY_DOMAIN_REQUIRED')
    missing=ref[ref.y_open5.isna()]
    if missing.empty or not np.isfinite(ref.loc[ref.y_open5.notna(),'y_open5'].to_numpy(float)).all():
        raise ValueError('TARGET_CERTIFICATE_REGISTERED_NAN_AND_REMAINING_REAL_LABELS_REQUIRED')
    day=str(pd.Timestamp(missing.iloc[0].signal_date).date())
    missing_keys={(str(v.ticker),str(v.security_uid)) for v in missing.itertuples()}
    matches=[]
    for sha,packet in packets:
        for claim in packet['events']:
            if claim['signal_date']!=day:continue
            parts=claim.get('missing_components',[claim])
            if {(v['ticker'],v['security_uid']) for v in parts}==missing_keys:
                matches.append((sha,claim,parts))
    if len(matches)!=1:raise ValueError('UNREGISTERED_MISSING_CASH_TARGET_KEY_OR_COUNT')
    sha,claim,components=matches[0]
    if (claim.get('complete_reference_rows')!=20
            or claim.get('known_exact_h5_rows')!=20-len(missing)
            or claim.get('missing_exact_h5_rows')!=len(missing)):
        raise ValueError('TARGET_CERTIFICATE_EXACT_MISSING_AND_KNOWN_COUNTS_REQUIRED')
    support=[dict(ticker=str(v.ticker),security_uid=str(v.security_uid),asset_epoch=str(v.asset_epoch))
        for v in ref.sort_values('ticker').itertuples()]
    if support!=claim['reference_support']:
        raise ValueError('TARGET_CERTIFICATE_SOURCE_UID_DOMAIN_OR_CLOCK_MISMATCH')
    if sha==_TARGET_CERTIFICATE_2024_SHA and claim.get('source_cash_only_basis_qualified') is not True:
        raise ValueError('CASH_ONLY_SOURCE_BASIS_NOT_ADMITTED')
    cut=pd.Timestamp(cutoff);cut=cut.tz_localize('UTC') if cut.tzinfo is None else cut.tz_convert('UTC')
    lower_parts=[];F=Fraction.from_float
    for component in components:
        row=missing[(missing.ticker==component['ticker'])&(missing.security_uid==component['security_uid'])]
        if len(row)!=1:raise ValueError('TARGET_CERTIFICATE_EXACT_COMPONENT_UID_REQUIRED')
        row=row.iloc[0]
        if any(str(pd.Timestamp(row[k]).date())!=component[k]
                for k in ('execution_date','label_end_date','label_mature_date')):
            raise ValueError('TARGET_CERTIFICATE_SOURCE_UID_DOMAIN_OR_CLOCK_MISMATCH')
        basis=component['nonnegative_cash_basis']
        if (basis.get('kind')!='POSITIVE_ORDINARY_GROSS_CASH_CLAIM_ONLY_NATIVE_CURRENCY_OR_FX_UNRESOLVED'
                or basis.get('missing_component_domain')!='CASH_PLUS_NONSPENDABLE_RECEIVABLE_USD_VALUE_C_GE_0'
                or basis.get('native_amount_sign')!='POSITIVE_SOURCE_LITERAL'
                or basis.get('value_not_imputed') is not True
                or not isinstance(basis.get('source_refs'),list) or not basis['source_refs']
                or any(not isinstance(v,dict) or not isinstance(v.get('path'),str) or not v['path'].strip()
                    or not re.fullmatch(r'[0-9a-f]{64}',str(v.get('sha256'))) for v in basis['source_refs'])
                or basis.get('security_uid')!=row.security_uid or basis.get('ticker')!=row.ticker):
            raise ValueError('SOURCE_PINNED_NONNEGATIVE_ORDINARY_CASH_BASIS_REQUIRED')
        if (sha==_TARGET_CERTIFICATE_2024_SHA and
                (basis.get('source_cash_only_basis_qualified') is not True
                or basis.get('typed_non_cash_fields_all_absent_or_zero') is not True
                or basis.get('no_new_share_quantity_rule') is not True)):
            raise ValueError('CASH_ONLY_SOURCE_BASIS_NOT_ADMITTED')
        known=pd.Timestamp(basis.get('publication_known_at'))
        if pd.isna(known) or known.tzinfo is None or not known.tz_convert('UTC')<cut:
            raise ValueError('CERTIFICATE_SOURCE_PUBLICATION_NOT_BEFORE_FOLD')
        if 'label_quantity_multiplier' not in ref or float(row.label_quantity_multiplier)!=component['quantity_multiplier']:
            raise ValueError('TARGET_CERTIFICATE_FIXED_SOURCE_QUANTITY_REQUIRED')
        entry=float(component['raw_entry_open']);exit=float(component['raw_exit_open']);q=float(component['quantity_multiplier'])
        if not np.isfinite([entry,exit,q]).all() or min(entry,exit,q)<=0:
            raise ValueError('TARGET_CERTIFICATE_SOURCE_RAW_ENDPOINTS_REQUIRED')
        lower_parts.append(F(q)*F(exit)/F(entry)-1)
    lower=(sum((F(float(v)) for v in ref.y_open5.dropna()),Fraction(0))+sum(lower_parts,Fraction(0)))/20
    var=Fraction(5,400)*sum((F(float(v))**2 for v in ref.realized_vol_20d),Fraction(0))
    grid=[F(float(v)) for v in GRID]
    values=[lower*z-var*z*z/2-Fraction(1,1000)*abs(z-1) for z in grid]
    imax=grid.index(max(grid));margin=min(values[imax]-v for i,v in enumerate(values) if i!=imax)
    declared=Fraction(int(claim['exact_rational_margin']['numerator']),int(claim['exact_rational_margin']['denominator']))
    if (max(grid)!=1 or margin<=0 or margin!=declared or claim.get('unique_grid_target')!=1.
            or float(target_grid(np.asarray([float(lower)]),np.asarray([float(var)]))[0])!=1.):
        raise ValueError('STRICT_UNIQUE_ORIGINAL_GROSS_TARGET_CERTIFICATE_FAILED')
    if not np.isclose(variance,float(var),rtol=1e-14,atol=0):
        raise ValueError('CERTIFICATE_VARIANCE_PROXY_CHANGED')
    return 1.

def fit_ridge_annual_constant_free(train_reference,infer_reference,*,cutoff,learn,
        certificate_authority=None,dependencies=()):
    """Explicit new execution descendant; old R2 and its artifacts stay unchanged.

    No exact RMS is estimated or invented. Six original nonconstant features,
    fixed Grid utility and LOW Ridge remain. Exactly pinned reviewed missing cash labels
    may stay NaN only when their exact pinned target-only profile verifies; unregistered missing rows stay blocked.
    Mathematical constant-feature equivalence is not a float bitwise claim.
    """
    if not callable(learn):raise ValueError('DURABLE_GROSS_LEARN_OWNER_REQUIRED')
    cut=pd.Timestamp(cutoff)
    if pd.isna(cut):raise ValueError('EXACT_R6_ANNUAL_GROSS_CUTOFF_REQUIRED')
    if cut.tzinfo is not None:cut=cut.tz_convert('UTC').tz_localize(None)
    if cut.year not in (2024,2025) or cut!=pd.Timestamp(year=cut.year,month=1,day=1):
        raise ValueError('CONSTANT_FREE_ONLY_NEW_2024_2025_FOLDS_PRESERVE_2023')
    _validate_annual_reference(train_reference,True,cut,allow_target_only=True)
    _validate_annual_reference(infer_reference,False,cut)
    if certificate_authority is not None and not train_reference.y_open5.isna().any():
        raise ValueError('UNUSED_TARGET_CERTIFICATE_NOT_PERMITTED')
    # All certificates and all six-feature arrays are checked before first owner.
    supervision=aggregate_reference(train_reference,cut,structural_constant_free=True,
        certificate_authority=certificate_authority)
    # Same aggregation owner for inference features: zero *row labels* are never
    # created. The nonlabel feature block is a subset of the same fixed aggregation
    # expressions; forecast and PIT risk/liquidity alone determine these values.
    states=_constant_free_inference_reference(infer_reference)
    owned,local,kinds=_annual_operation_owner(learn,cut)
    result=_fit_ridge_annual_aggregates(supervision,states,cut,owned,local,kinds,dependencies,
        features=CONSTANT_FREE_FEATURES,prior_rms=None,learned_count=2,physical_count=5,training_rows=len(train_reference))
    result['metadata'].update(execution_descendant='STRUCTURAL_CONSTANT_FREE_WITH_FROZEN_TARGET_CERTIFICATE_R1',
        RMS_estimated=False,RMS_value_invented=False,old_R2_bitwise_equivalence=False,
        exact_missing_cash_values_recovered=False,
        target_only_certificate_sha256=(_target_certificate_packets(certificate_authority)[0][0]
            if train_reference.y_open5.isna().any() and len(_target_certificate_packets(certificate_authority))==1 else None),
        target_only_certificate_sha256s=tuple(v[0] for v in _target_certificate_packets(certificate_authority))
            if train_reference.y_open5.isna().any() else (),
        target_only_missing_rows=int(train_reference.y_open5.isna().sum()),
        original2023_fit_preserved=True)
    return result

def _constant_free_inference_reference(frame):
    rows=[]
    for day,domain in frame.groupby('signal_date',sort=True):
        ref=domain.sort_values(['mu','ticker'],ascending=[False,True],kind='stable').head(20)
        if len(ref)!=20:raise ValueError('FIXED_TOP20_GROSS_REFERENCE_NOT_COMPLETE')
        vol=ref.realized_vol_20d.to_numpy(float)
        variance=5*float(np.square(vol).sum())/400
        rows.append(dict(signal_date=day,mean_mu=float(ref.mu.mean()),
            positive_mu_fraction=float((ref.mu>0).mean()),diagonal_vol_proxy_5d=float(np.sqrt(variance)),
            mean_liquidity=float(ref.avg_dollar_volume_20d.mean()),
            mean_downside_vol20=float(ref.downside_vol_20d.mean()),vol20_dispersion=float(np.std(vol))))
    return pd.DataFrame(rows)
