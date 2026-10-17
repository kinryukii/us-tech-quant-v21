"""R8 metadata-only label foundation and all-incumbent support adapter.
Reuses frozen R6 cohort formation. No y, score, model, price or account reads.
Metadata support is necessary evidence, never target/source/account authority.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_inputs as inputs

R8='V24_A_STATE_AND_LABEL_FOUNDATION_PRE2026_R8'
PAIR_ID='A_R8_PAIR_SUPPORT_EXPANSION_ALL_ELIGIBLE_R6_COHORT_INCUMBENTS_R1'
FORBIDDEN=frozenset((*inputs.FEATURES,'y','y_open5','target','edge','basket_y','open','close','alpha','beta','raw_a2_prediction','prediction','score','nav','cash'))
BASE_FLAGS=('signal_date','ticker','security_id','feature_available','label_available','account_event_unhandled','label_unsupported_common_event','label_mature_date','label_coordinate')

def metadata_read(path,columns,expected_sha,date_column='signal_date'):
    """Prove physical pre2026 bounds and custody BEFORE reading columns."""
    path=Path(path);columns=list(columns)
    if set(columns)&FORBIDDEN:raise ValueError('NUMERIC_TARGET_OR_MARKET_READ_FORBIDDEN')
    if inputs.sha(path)!=expected_sha:raise ValueError('SOURCE_CUSTODY_MISMATCH')
    pf=pq.ParquetFile(path);names=pf.schema_arrow.names
    if not set(columns).issubset(names) or date_column not in names:raise ValueError('METADATA_SCHEMA_MISSING')
    for i in range(pf.num_row_groups):
        st=pf.metadata.row_group(i).column(names.index(date_column)).statistics
        if st is None or not st.has_min_max or pd.Timestamp(st.max)>=inputs.BOUNDARY:raise ValueError('SOURCE_NOT_PHYSICALLY_PRE2026')
    before=path.stat();frame=pq.read_table(path,columns=columns).to_pandas();after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED_DURING_METADATA_READ')
    if date_column in frame:
        frame[date_column]=pd.to_datetime(frame[date_column])
        if frame[date_column].isna().any() or frame[date_column].ge(inputs.BOUNDARY).any():raise ValueError('METADATA_TIME_BOUNDARY')
    return frame

def _flag(series,want):
    valid=series.notna()&series.isin([True,False,0,1])
    return valid&series.eq(want)

def _sid(series):return series.map(decision._valid_sid)

def label_reasons(frame):
    """No numerical y check: explicit metadata-only qualification level."""
    f=frame.copy()
    if not set(BASE_FLAGS).issubset(f):raise ValueError('LABEL_FLAGS_INCOMPLETE')
    f['signal_date']=pd.to_datetime(f.signal_date);f['label_mature_date']=pd.to_datetime(f.label_mature_date)
    if f.signal_date.isna().any() or f.signal_date.ge(inputs.BOUNDARY).any() or f.duplicated(['signal_date','ticker']).any():raise ValueError('LABEL_KEYS_OR_BOUNDARY')
    r={
      'LABEL_UNAVAILABLE':~_flag(f.label_available,True),
      'ACCOUNT_EVENT_UNHANDLED':~_flag(f.account_event_unhandled,False),
      'UNSUPPORTED_COMMON_EVENT':~_flag(f.label_unsupported_common_event,False),
      'MATURITY_UNBOUND':f.label_mature_date.isna(),
      'MATURITY_OUTSIDE_PRE2026':f.label_mature_date.ge(inputs.BOUNDARY),
      'FEATURE_UNAVAILABLE':~_flag(f.feature_available,True),
      'SID_UNKNOWN':~_sid(f.security_id),
      'LABEL_COORDINATE_CHANGED':~f.label_coordinate.eq(inputs.LABEL),
    }
    if 'endpoint_pair_available' in f:r['ENDPOINT_PAIR_UNAVAILABLE']=~_flag(f.endpoint_pair_available,True)
    out=f[list(BASE_FLAGS)].copy()
    for name,mask in r.items():out[name]=mask.astype(bool)
    out['metadata_supported']=~pd.DataFrame(r).any(axis=1)
    codes=np.full(len(f),'',dtype=object)
    for name,mask in r.items():codes=np.where(mask.to_numpy(),np.where(codes!='',codes+'|'+name,name),codes)
    out['reason_codes']=codes
    out['target_value_checked']=False
    return out

def structural_keys(pred,calendar):
    """Exact old cohort/entry mechanics; placeholders are NOT source features.
    Only BUY/HOLD/old REPLACE structural keys are consumed. Empty labels prevent
    every target calculation. Dummy feature values are discarded, not exported.
    Duration qualification is intentionally not reconstructed by this adapter.
    """
    forbidden=set(pred)&FORBIDDEN
    if forbidden:raise ValueError('STRUCTURAL_INPUT_MUST_BE_METADATA_ONLY')
    f=pred.copy();f['signal_date']=pd.to_datetime(f.signal_date)
    if f.signal_date.ge(inputs.BOUNDARY).any():raise ValueError('2026_LOCKED')
    for name in ('feature_available','is_raw_top20','new_buy_eligible','raw_top20_set_complete'):
        if name not in f or not f[name].notna().all() or not f[name].isin([True,False,0,1]).all():raise ValueError('STATE_FLAG_UNBOUND:'+name)
    for name in inputs.FEATURES:f[name]=np.nan
    f['raw_a2_prediction']=np.nan
    labels=pd.DataFrame(columns=decision.LABEL_COLS)
    samples,audit=decision.build_samples(f,labels,calendar)
    result={}
    for role in ('buy','hold','replace'):
        keep=['signal_date','ticker','security_id','sample_id']
        if role!='replace':keep+=['cohort_age_sessions','raw_rank']
        else:keep+=['incumbent','incumbent_sid']
        x=samples[role]
        result[role]=x[keep].copy() if not x.empty else pd.DataFrame(columns=keep)
    result['audit']={k:audit[k] for k in ('entrant_opportunities','incumbent_proxy_opportunities','sid_breaks','pair_selected_before_y')}
    return result

def all_incumbent_pairs(keys):
    """Ex-ante all eligible partners; no label parameter or replacement search."""
    e=keys['buy'].rename(columns={'ticker':'entrant','security_id':'entrant_sid'})
    i=keys['hold'].rename(columns={'ticker':'incumbent','security_id':'incumbent_sid'})
    e=e.loc[_sid(e.entrant_sid),['signal_date','entrant','entrant_sid']]
    i=i.loc[_sid(i.incumbent_sid),['signal_date','incumbent','incumbent_sid','cohort_age_sessions','raw_rank']]
    p=e.merge(i,on='signal_date',how='inner',validate='many_to_many')
    p=p.loc[p.entrant.ne(p.incumbent)].sort_values(['signal_date','entrant','raw_rank','incumbent'],na_position='last').reset_index(drop=True)
    if p.duplicated(['signal_date','entrant','incumbent']).any():raise ValueError('DUPLICATE_PAIR')
    p['pair_count_before_labels']=p.groupby(['signal_date','entrant']).entrant.transform('size')
    p['pre_label_group_weight']=1/p.pair_count_before_labels
    p['pair_id']=[str(d.date())+'_'+str(e)+'_'+str(i) for d,e,i in zip(p.signal_date,p.entrant,p.incumbent)]
    return p

def attach_pair_metadata(pairs,annotations):
    """Selected pair keys stay fixed even when either partner is unsupported."""
    p=pairs.copy()
    for side,ticker,sid in [('e','entrant','entrant_sid'),('i','incumbent','incumbent_sid')]:
        a=annotations[['signal_date','ticker','security_id','metadata_supported','label_mature_date','reason_codes']].rename(columns={'ticker':ticker,'security_id':side+'_label_sid','metadata_supported':side+'_metadata_supported','label_mature_date':side+'_maturity','reason_codes':side+'_reason_codes'})
        p=p.merge(a,on=['signal_date',ticker],how='left',validate='many_to_one')
        p[side+'_supported']=p[side+'_metadata_supported'].eq(True)&p[side+'_label_sid'].eq(p[sid])&_sid(p[sid])
    p['pair_metadata_supported']=p.e_supported&p.i_supported
    p['pair_maturity']=p[['e_maturity','i_maturity']].max(axis=1)
    p['supported_pair_count']=p.groupby(['signal_date','entrant']).pair_metadata_supported.transform('sum')
    p['supported_training_group_weight']=np.divide(p.pair_metadata_supported.astype(float),p.supported_pair_count,out=np.zeros(len(p)),where=p.supported_pair_count.to_numpy()>0)
    return p

def fold_support(frame,calibration_start,cutoff):
    start=pd.Timestamp(calibration_start);cut=pd.Timestamp(cutoff)
    if cut>inputs.BOUNDARY or start>=cut:raise ValueError('FOLD_TIME_BOUNDARY')
    return frame.pair_metadata_supported.eq(True)&frame.signal_date.lt(start)&frame.pair_maturity.notna()&frame.pair_maturity.lt(start)
