"""Chronological, input-only bridge from shared native OOF to JOINT value.

C owns native base/meta fitting. This module fits only a B five-session value
bridge on earlier matured native OOF, using every eligible row and equal date
mass. Native probability/rank/quantiles/distributions remain in their original
coordinate and are never relabelled as native expected shareholder return.
"""
from __future__ import annotations
import ast
import hashlib
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

_RETAINED=Path(__file__).resolve().parents[1]/'retained/a2_pto_full_compat_20260928_r1/fusion.py'
_RETAINED_SHA='5af5e4aa5ec4c6009906bb15f74e67f50778d68589a80f387561d065a4b8d7d0'
_QUANTILE_NORMAL_SPAN=2.563103
_ROLE_ALIASES={'raw':'return','point':'return','regression':'return','mean':'return',
               'prob':'probability','quant':'quantile','dist':'distribution'}

class BridgeDependencyError(ValueError):
    """A required native interface or earlier legal OOF sample is absent."""

@lru_cache(maxsize=1)
def _retained_interfaces():
    if hashlib.sha256(_RETAINED.read_bytes()).hexdigest()!=_RETAINED_SHA:
        raise BridgeDependencyError('RETAINED_INTERFACE_HASH_MISMATCH')
    tree=ast.parse(_RETAINED.read_text(encoding='utf-8-sig'))
    names={'raw_columns','interface_x'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes}!=names:raise BridgeDependencyError('RETAINED_INTERFACE_MISSING')
    namespace={'np':np,'pd':pd}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(_RETAINED),'exec'),namespace)
    return namespace['interface_x']

def _schema(frame,spec):
    name=spec.get('native_name')
    if not name:raise BridgeDependencyError('NATIVE_NAME_REQUIRED')
    prefix=name+'__'
    fields={str(c)[len(prefix):]:str(c) for c in frame.columns if str(c).startswith(prefix)}
    role=spec.get('native_role')
    if role:role=_ROLE_ALIASES.get(role,role)
    else:
        if all(k in fields for k in ('q10','q50','q90')):role='quantile'
        elif 'scale' in fields and ('location' in fields or 'raw' in fields):role='distribution'
        elif 'p' in fields:role='probability'
        elif 'rank' in fields:role='rank'
        elif 'raw' in fields:role='return'
        else:raise BridgeDependencyError('MISSING_NATIVE_INTERFACE:'+name)
    required={'return':['raw'],'probability':['p'],'rank':['rank'],
              'quantile':['q10','q50','q90'],
              'distribution':['location' if 'location' in fields else 'raw','scale']}
    if role not in required:raise BridgeDependencyError('UNKNOWN_NATIVE_ROLE:'+str(role))
    need=required[role]
    if any(field not in fields for field in need):
        raise BridgeDependencyError('MISSING_NATIVE_DEPENDENCY:'+name+':'+','.join(need))
    native=[fields[field] for field in need]
    canonical={'return':['raw_mu'],'probability':['p_up'],'rank':['rank_score'],
               'quantile':['q10','q50','q90'],'distribution':['raw_mu','sigma']}[role]
    return {'native_name':name,'role':role,'native_columns':native,
            'canonical_columns':canonical,'member':{'return':'raw_','probability':'prob_',
            'rank':'rank_','quantile':'quant_','distribution':'dist_'}[role]+name}

def _check_raw(frame,training):
    required={'signal_date','ticker','source_cutoff'}
    if not required.issubset(frame.columns):
        raise BridgeDependencyError('MISSING_OOF_LINEAGE:'+','.join(sorted(required-set(frame.columns))))
    if frame.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_NATIVE_KEY')
    signal=pd.to_datetime(frame.signal_date);source=pd.to_datetime(frame.source_cutoff)
    if signal.isna().any() or source.isna().any():raise ValueError('MISSING_OOF_TIMESTAMP')
    if (source>signal).any():raise ValueError('NATIVE_SOURCE_CUTOFF_AFTER_SIGNAL')
    boundary=pd.Timestamp('2026-01-01' if training else '2027-01-01')
    if signal.ge(boundary).any():raise ValueError('NATIVE_CONTENT_OUTSIDE_TIME_BOUNDARY')
    if 'source_label_mature_max' in frame:
        maturity=pd.to_datetime(frame.source_label_mature_max)
        if maturity.isna().any() or maturity.ge(source).any():
            raise ValueError('NATIVE_BASE_LABEL_MATURITY_NOT_PRIOR_TO_SOURCE_CUTOFF')

def _matrix(frame,schema):
    native=frame[schema['native_columns']].to_numpy(float)
    valid=np.isfinite(native).all(axis=1)
    if schema['role']=='probability':valid&=((native[:,0]>=0)&(native[:,0]<=1))
    if schema['role']=='distribution':valid&=native[:,1]>0
    width=len(schema['native_columns']);matrix=np.full((len(frame),width),np.nan)
    if valid.any():
        view=frame.loc[valid,['signal_date','ticker',*schema['native_columns']]].copy()
        view=view.rename(columns=dict(zip(schema['native_columns'],schema['canonical_columns'])))
        # Retained interface_x computes a full contemporaneous rank percentile
        # here, before any target availability/maturity join or selection.
        matrix[valid]=_retained_interfaces()(schema['member'],view)
    return matrix,valid

def _native_scale(matrix,role):
    if role=='quantile':return (np.sort(matrix,axis=1)[:,2]-np.sort(matrix,axis=1)[:,0])/_QUANTILE_NORMAL_SPAN
    if role=='distribution':return matrix[:,1]
    return None

def _target_coordinate(spec):
    value=spec.get('B_target','FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN')
    if isinstance(value,dict):value=value.get('name')
    if not isinstance(value,str) or not value:raise BridgeDependencyError('B_TARGET_COORDINATE_REQUIRED')
    return value

def prepare_native_training(raw_history,Btruth,cutoff,spec):
    """Return the exact legal fit rows and transformed native interface.

    Shared with the orchestration identity builder so dependency hashing cannot
    use a different availability, maturity, or contemporaneous rank mask.
    """
    spec=dict(spec);cutoff=pd.Timestamp(cutoff)
    if cutoff>pd.Timestamp('2026-01-01'):raise ValueError('BRIDGE_FIT_CUTOFF_AFTER_PRE2026')
    if float(spec.get('alpha',100))!=100.:raise ValueError('BRIDGE_ALPHA_MUST_EQUAL_FROZEN100')
    _check_raw(raw_history,True)
    schema=_schema(raw_history,spec)
    raw=raw_history.loc[pd.to_datetime(raw_history.signal_date).lt(cutoff)].copy()
    raw['signal_date']=pd.to_datetime(raw.signal_date)
    matrix,valid=_matrix(raw,schema)
    for j in range(matrix.shape[1]):raw['_bridge_x_'+str(j)]=matrix[:,j]
    raw['_native_interface_available']=valid
    target=spec.get('target_column','y_open5')
    maturity=spec.get('label_maturity_column','label_mature_date')
    required={'signal_date','ticker',target,maturity}
    if not required.issubset(Btruth.columns):raise BridgeDependencyError('MISSING_B_TRUTH_DEPENDENCY')
    if Btruth.duplicated(['signal_date','ticker']).any():raise ValueError('DUPLICATE_B_TRUTH_KEY')
    truth_columns=['signal_date','ticker',target,maturity]
    for optional in ('label_available','fit_eligible','trade_eligible','label_end_date'):
        if optional in Btruth and optional not in truth_columns:truth_columns.append(optional)
    truth=Btruth[truth_columns].copy();truth['signal_date']=pd.to_datetime(truth.signal_date)
    truth[maturity]=pd.to_datetime(truth[maturity])
    if truth.signal_date.ge(pd.Timestamp('2026-01-01')).any() or truth[maturity].ge(pd.Timestamp('2026-01-01')).any():
        raise ValueError('B_TRUTH_CONTAINS_TEST_CONTENT')
    joined=raw.merge(truth,on=['signal_date','ticker'],how='inner',validate='one_to_one',sort=False)
    eligible=joined._native_interface_available.eq(True)&np.isfinite(joined[target])&joined[maturity].lt(cutoff)
    for optional in ('label_available','fit_eligible','trade_eligible'):
        if optional in joined:eligible&=joined[optional].eq(True)
    if 'label_end_date' in joined:
        eligible&=pd.to_datetime(joined.label_end_date).lt(cutoff)
    train=joined.loc[eligible].copy()
    minimum=int(spec.get('minimum_rows',100))
    if len(train)<minimum:raise BridgeDependencyError('INSUFFICIENT_EARLIER_MATURED_OOF:'+str(len(train)))
    return train,schema

def fit_native_bridge(raw_history,Btruth,cutoff,spec):
    """Fit scaler + alpha100 Ridge on every earlier matured native OOF row."""
    spec=dict(spec);cutoff=pd.Timestamp(cutoff)
    train,schema=prepare_native_training(raw_history,Btruth,cutoff,spec)
    target=spec.get('target_column','y_open5')
    maturity=spec.get('label_maturity_column','label_mature_date')
    x=train[['_bridge_x_'+str(j) for j in range(len(schema["native_columns"]))]].to_numpy(float)
    y=train[target].to_numpy(float)
    weights=1./train.signal_date.map(train.signal_date.value_counts()).to_numpy(float)
    weights/=weights.mean()
    scaler=StandardScaler().fit(x,sample_weight=weights)
    model=Ridge(alpha=100.).fit(scaler.transform(x),y,sample_weight=weights)
    residual=y-model.predict(scaler.transform(x))
    squared=float(np.average(residual**2,weights=weights))
    rms=max(float(np.sqrt(squared)),1e-6)
    native_scale=_native_scale(x,schema['role'])
    scale_ratio=None
    if native_scale is not None:
        second=float(np.average(native_scale**2,weights=weights))
        if not np.isfinite(second) or second<=0:raise BridgeDependencyError('NO_VALID_NATIVE_SCALE_FOR_CALIBRATION')
        scale_ratio=rms/np.sqrt(second)
    lineage=train[['signal_date','ticker','source_cutoff',maturity]].copy()
    digest=hashlib.sha256(pd.util.hash_pandas_object(lineage,index=False).to_numpy().tobytes()).hexdigest()
    return {'schema':schema,'spec':spec,'cutoff':str(cutoff),'scaler':scaler,'model':model,
            'residual_rms':rms,'native_scale_ratio':scale_ratio,
            'fit_units':3+int(scale_ratio is not None),'optimizer_fit_units':2,
            'estimated_states':['StandardScaler','Ridge','residual_RMS']+(['native_scale_ratio'] if scale_ratio is not None else []),
            'native_base_fit_units':0,'fit_rows':len(train),
            'fit_dates':int(train.signal_date.nunique()),'sampling':'NONE_ALL_ELIGIBLE_ROWS',
            'target_clip':None,'date_weighting':'equal date mass, normalized mean weight1',
            'target_weighted_mean':float(np.average(y,weights=weights)),
            'label_mature_max':str(train[maturity].max()),
            'signal_date_max':str(train.signal_date.max()),
            'source_cutoff_max':str(pd.to_datetime(train.source_cutoff).max()),
            'source_cutoffs':sorted(set(map(str,pd.to_datetime(train.source_cutoff)))),
            'oof_lineage_digest':digest,
            'base_label_maturity_verification':'PER_ROW_SOURCE_FIELD' if 'source_label_mature_max' in raw_history else 'REQUIRES_BOUND_C_FIT_RECEIPTS',
            'native_source_receipt':spec.get('native_source_receipt'),
            'native_target':spec.get('native_target','C_NATIVE_RAW_TARGET'),
            'B_target':_target_coordinate(spec),
            'native_fit_row_cap':spec.get('native_fit_row_cap'),
            'reuse_scope':'SHARED_C_NATIVE_OOF_ONLY; B_FULL_ROW_FIVE_DAY_BRIDGE; NO_BASE_OR_META_REFIT',
            'retained_interface_source':str(_RETAINED),'retained_interface_sha256':_RETAINED_SHA,
            'uncertainty_scope':'Prior nativeOOF fitted bridge residual; finite scale is not certified quantile coverage',
            'native_quantile_crossing_rows':int((x[:,0]>x[:,1]).sum()+(x[:,1]>x[:,2]).sum()) if schema['role']=='quantile' else 0}

def apply_native_bridge(raw_fold,bundle):
    """Apply frozen bridge; preserve native fields and rows, no fitting."""
    _check_raw(raw_fold,False)
    cutoff=pd.Timestamp(bundle['cutoff'])
    if pd.to_datetime(raw_fold.signal_date).lt(cutoff).any():raise ValueError('BRIDGE_APPLIED_TO_ITS_TRAINING_HISTORY')
    schema=_schema(raw_fold,bundle['spec'])
    if schema!=bundle['schema']:raise BridgeDependencyError('NATIVE_INTERFACE_CHANGED_AFTER_BRIDGE_FREEZE')
    matrix,valid=_matrix(raw_fold,schema)
    out=raw_fold.copy()
    if 'mu' in out or 'sigma' in out:raise BridgeDependencyError('AMBIGUOUS_UNPREFIXED_NATIVE_MU_SIGMA')
    mu=np.full(len(out),np.nan);sigma=np.full(len(out),np.nan)
    if valid.any():
        x=matrix[valid];mu[valid]=bundle['model'].predict(bundle['scaler'].transform(x))
        native_scale=_native_scale(x,schema['role'])
        if native_scale is None:sigma[valid]=bundle['residual_rms']
        else:sigma[valid]=np.maximum(native_scale,1e-6)*bundle['native_scale_ratio']
    out['mu']=mu;out['sigma']=sigma
    out['bridge_available']=valid
    out['bridge_status']=np.where(valid,'FROZEN_PRIOR_OOF_FIVE_DAY_BRIDGE','MISSING_NATIVE_ROW_INTERFACE')
    out['bridge_cutoff']=cutoff
    out['native_role']=schema['role']
    out['expected_return_coordinate']=_target_coordinate({'B_target':bundle['B_target']})
    out['native_base_refitted_by_B']=False
    return out
