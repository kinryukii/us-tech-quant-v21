"""Column-scoped reuse of accepted JOINT research inputs.

This adapter never builds a price/universe producer, loads model scores, or
changes a target. Its optional feature extension calls the existing pure
past-only stock-state implementation on the immutable forward-rehab surface.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

FEATURES = [
    'ret_1d','ret_3d','ret_5d','ret_10d','ret_20d','ret_40d','ret_60d','ret_120d',
    'price_vs_ma10','price_vs_ma20','price_vs_ma50','price_vs_ma120',
    'ma10_vs_ma20','ma20_vs_ma50','ma50_vs_ma120',
    'realized_vol_5d','realized_vol_10d','realized_vol_20d','realized_vol_60d',
    'downside_vol_20d','upside_vol_20d','distance_from_high_20d',
    'distance_from_high_60d','distance_from_low_20d','distance_from_low_60d',
    'max_drawdown_20d','max_drawdown_60d','avg_volume_20d','avg_volume_60d',
    'volume_ratio_5d_20d','volume_ratio_20d_60d','avg_dollar_volume_20d',
]
ACCEPTED_FEATURE_TAGS = {
    'FROZEN_RAW_A2_TRAINING_MATRIX_32',
    'FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION',
}
TRAIN_COLUMNS = [
    'signal_date','ticker','security_id','security_id_type','cusip',
    'moomoo_transport_code','active_13f_quarter','quarter_universe_fingerprint',
    'is_max_group',*FEATURES,'feature_available','all_features_finite',
    'feature_source','feature_coordinate','feature_pit_status',
    'execution_date','label_end_date','label_mature_date','endpoint_pair_available',
    'label_available','y_open5','label_coordinate','label_quantity_multiplier',
    'label_common_event_count','label_unsupported_common_event',
]
FEATURE_COLUMNS = [
    'signal_date','ticker',*FEATURES,'required_observations',
    'lookback_121_eligible','all_features_available',
]
FORBIDDEN_COLUMNS = {
    'raw_a2_prediction','raw_a2_rank','raw_a2_oof_split','is_raw_top20',
    'a1_raw_score','a1_rank',
}

def sha256(path: str | Path) -> str:
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()

def guard_parquet(path, expected_sha, date_fields):
    path=Path(path)
    if sha256(path)!=expected_sha:
        raise ValueError(f'Input hash mismatch: {path}')
    file=pq.ParquetFile(path)
    bounds={}
    for field in date_fields:
        if field not in file.schema.names:
            raise ValueError(f'Missing boundary field: {field}')
        index=file.schema.names.index(field)
        values=[]
        for group in range(file.num_row_groups):
            stat=file.metadata.row_group(group).column(index).statistics
            if stat is None or not stat.has_min_max:
                raise ValueError(f'Unproved physical boundary: {path}/{field}/{group}')
            minimum,maximum=str(stat.min),str(stat.max)
            if maximum[:10]>='2026-01-01':
                raise ValueError(f'Forbidden mixed/test input: {path}')
            values.append({'min':minimum,'max':maximum})
        bounds[field]=values
    return file, {'path':str(path),'sha256':expected_sha,
                  'rows':file.metadata.num_rows,'row_groups':file.num_row_groups,
                  'schema':file.schema_arrow.names,'date_bounds':bounds}

def _binding(binding):
    if isinstance(binding, dict):return binding
    return json.loads(Path(binding).read_text(encoding='utf-8'))

def load_training_inputs(binding, fit_cutoff=None):
    """Reuse fixed five-session shareholder labels without score/result columns.

    trade_eligible uses signal-known source/history flags only. fit_eligible adds
    target availability and strictly earlier maturity separately.
    """
    binding=_binding(binding)
    label=binding['sources']['accepted_five_day_panel']
    file,_=guard_parquet(label['path'],label['sha256'],
                         ['signal_date','execution_date','label_end_date','label_mature_date'])
    columns=binding['training_projection_columns']
    if FORBIDDEN_COLUMNS.intersection(columns):
        raise ValueError('Forbidden model/selector result column')
    panel=file.read(columns=columns).to_pandas()
    for field in ('signal_date','execution_date','label_end_date','label_mature_date'):
        panel[field]=pd.to_datetime(panel[field])
    extended=binding.get('extended_five_day_labels')
    if extended:
        label_file,_=guard_parquet(extended['path'],extended['sha256'],
                                   ['signal_date','execution_date','label_end_date','label_mature_date'])
        label_columns=extended['projection_columns']
        labels=label_file.read(columns=['signal_date','ticker',*label_columns]).to_pandas()
        drop_columns=[column for column in label_columns if column in panel.columns]
        panel=panel.drop(columns=drop_columns).merge(labels,on=['signal_date','ticker'],
                                                    how='left',validate='one_to_one',sort=False)
        for field in ('execution_date','label_end_date','label_mature_date'):
            panel[field]=pd.to_datetime(panel[field])
    raw=binding['sources']['raw_prices']
    raw_file,_=guard_parquet(raw['path'],raw['sha256'],['trade_date'])
    raw_keys=raw_file.read(columns=['ticker','trade_date']).to_pandas().rename(columns={'trade_date':'signal_date'})
    raw_keys['signal_date']=pd.to_datetime(raw_keys.signal_date)
    raw_keys=raw_keys.drop_duplicates(['signal_date','ticker'])
    raw_keys['signal_raw_key_present']=True
    panel=panel.merge(raw_keys,how='left',on=['signal_date','ticker'],validate='one_to_one',sort=False)
    panel['signal_raw_key_present']=panel.signal_raw_key_present.eq(True)
    feature_ok=(panel.feature_source.isin(ACCEPTED_FEATURE_TAGS)
                &panel.feature_available.eq(True)&panel.all_features_finite.eq(True)
                &np.isfinite(panel[FEATURES].to_numpy(float)).all(axis=1))
    panel['trade_eligible']=(panel.is_max_group.eq(True)&feature_ok&panel.signal_raw_key_present)
    mature=(panel.label_available.eq(True)&np.isfinite(panel.y_open5)
            &panel.label_end_date.lt(pd.Timestamp('2026-01-01'))
            &panel.label_mature_date.lt(pd.Timestamp('2026-01-01'))
            &panel.execution_date.gt(panel.signal_date)
            &panel.label_end_date.gt(panel.execution_date)
            &panel.label_unsupported_common_event.eq(False))
    if fit_cutoff is not None:
        cutoff=pd.Timestamp(fit_cutoff)
        if cutoff>pd.Timestamp('2026-01-01'):
            raise ValueError('Training cutoff crosses project boundary')
        mature &= panel.signal_date.lt(cutoff)&panel.label_mature_date.lt(cutoff)
    panel['fit_eligible']=panel.trade_eligible&mature
    panel['sample_weight_date_equal']=0.
    counts=panel.loc[panel.fit_eligible].groupby('signal_date').size()
    panel.loc[panel.fit_eligible,'sample_weight_date_equal']=(
        panel.loc[panel.fit_eligible,'signal_date'].map(counts).rdiv(1.))
    return panel

def load_held_features(binding):
    """Return accepted feature keys plus sparse extension, no model outputs."""
    binding=_binding(binding)
    source=binding['sources']['accepted_features']
    file,_=guard_parquet(source['path'],source['sha256'],['signal_date'])
    frame=file.read(columns=['signal_date','ticker',*FEATURES,
                             'lookback_121_eligible','all_features_available']).to_pandas()
    frame=frame.loc[frame.lookback_121_eligible.eq(True)&frame.all_features_available.eq(True),
                    ['signal_date','ticker',*FEATURES]].copy()
    frame['feature_source']='FROZEN_RAW_A2_FULL_PIT32_LEDGER_PROJECTION'
    extension=binding.get('own_held_feature_extension')
    if extension:
        file,_=guard_parquet(extension['path'],extension['sha256'],['signal_date'])
        extra=file.read(columns=['signal_date','ticker',*FEATURES,'feature_source']).to_pandas()
        frame=pd.concat([frame,extra],ignore_index=True)
    if frame.duplicated(['signal_date','ticker']).any():
        raise ValueError('Duplicate feature authority/key')
    frame['feature_available']=True
    return frame.sort_values(['signal_date','ticker'],kind='stable').reset_index(drop=True)

def existing_feature_functions(path):
    """Load only pure functions; do not import research runners or their I/O."""
    tree=ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    names={'build_stock_state_features','_rolling_max_drawdown'}
    body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    if {node.name for node in body}!=names:raise ValueError('Existing pure functions missing')
    namespace={'pd':pd,'np':np,'FEATURE_COLUMNS':FEATURES}
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
    return namespace['build_stock_state_features']


def existing_event_functions(path):
    """Reuse source-backed CA windows and its synthetic checks verbatim."""
    tree=ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    names={'apply_event_windows','synthetic_check'}
    body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    if {node.name for node in body}!=names:raise ValueError('Existing CA functions missing')
    namespace={'pd':pd,'np':np}
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),namespace)
    return namespace['apply_event_windows'],namespace['synthetic_check']

def shareholder_open_targets(keys, raw, calendar, event_records, apply_event_windows):
    """Extend the frozen five-session formula to existing raw endpoint pairs.

    No fabricated endpoint/price/entitlement and no decision-pool filtering.
    This output is a target table; only mature rows may be fitted.
    """
    keys=keys[['signal_date','ticker']].copy()
    keys['signal_date']=pd.to_datetime(keys.signal_date)
    dates=pd.DatetimeIndex(pd.to_datetime(calendar)).sort_values().unique()
    if dates.empty or dates.max()>=pd.Timestamp('2026-01-01'):
        raise ValueError('Calendar crosses the pre2026 input boundary')
    position=dates.get_indexer(keys.signal_date)
    if (position<0).any():raise ValueError('Signal outside common calendar')
    for field,offset in [('execution_date',1),('label_end_date',6)]:
        idx=position+offset;values=np.full(len(keys),np.datetime64('NaT','ns'),dtype='datetime64[ns]')
        inside=idx<len(dates);values[inside]=dates.to_numpy(dtype='datetime64[ns]')[idx[inside]]
        keys[field]=values
    keys['label_mature_date']=keys.label_end_date
    raw=raw[['ticker','trade_date','open']].copy()
    raw['trade_date']=pd.to_datetime(raw.trade_date)
    if raw.trade_date.ge(pd.Timestamp('2026-01-01')).any():raise ValueError('Raw price beyond boundary')
    if raw.duplicated(['ticker','trade_date']).any():raise ValueError('Duplicate raw endpoint')
    entry=raw.rename(columns={'trade_date':'execution_date','open':'entry_open'})
    exit_=raw.rename(columns={'trade_date':'label_end_date','open':'exit_open'})
    frame=keys.merge(entry,on=['ticker','execution_date'],how='left',validate='many_to_one',sort=False)
    frame=frame.merge(exit_,on=['ticker','label_end_date'],how='left',validate='many_to_one',sort=False)
    qty,bad,count=apply_event_windows(frame,event_records)
    endpoint=(np.isfinite(frame.entry_open)&frame.entry_open.gt(0)
              &np.isfinite(frame.exit_open)&frame.exit_open.gt(0)
              &frame.label_end_date.notna())
    available=endpoint&~bad
    frame['endpoint_pair_available']=endpoint
    frame['label_available']=available
    frame['label_quantity_multiplier']=qty
    frame['label_common_event_count']=count
    frame['label_unsupported_common_event']=bad
    frame['y_open5']=np.where(available,(frame.exit_open/frame.entry_open)*qty-1.,np.nan)
    frame['label_coordinate']='SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED'
    frame['target_source']='EXISTING_FULL848_RAW_AND_FROZEN_COMMON_CA_WINDOW_FORMULA'
    return frame.drop(columns=['entry_open','exit_open'])
