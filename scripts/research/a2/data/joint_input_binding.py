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


def cash_inclusive_shareholder_open_targets(keys, raw, calendar, event_records,
        apply_event_windows, *, cash_events=(), cutoff,
        label_only_post_verified_cash=False, research_cash_authority=None,
        cash_publication_proofs=()):
    """New, pure H5 economic-label descendant; never changes the old label.

    ``event_records`` must retain every unadjudicated common event after exact
    source-backed cash classification by the existing cash binder. ``cash_events``
    are its strictly publication-dated USD/raw-old-share entitlements, not
    post-verified research events by default. Explicit label-only opt-in admits
    ordinary USD ResearchReconstructedCashEvent via the unchanged B owner,
    with a separate exact source-pinned publication knowledge proof. This never
    mutates event.available_at or grants historical decision/account eligibility.
    The caller owns complete event/identity/quote
    source coverage; this function grants no historical/PIT/source authority.

    The original window owner supplies final and pre-ex raw quantities. The
    entitlement owner alone creates, pays and values cash claims. Unit-lot value
    at exit is raw stock value + paid cash + still-nonspendable receivables.
    Entry-ex events are excluded; exit-ex events are included. Maturity and all
    supplied publication clocks must be strictly before the caller's fold cutoff.
    Unknown terms/identity/clocks stay blocked, never dropped or filled.
    """
    from scripts.v22.corporate_action_transition_r1 import (
        SourceBackedEntitlementEvent, ResearchReconstructedCashEvent,
        CASH_ENTITLEMENT_FAMILIES, RAW_OLD_SHARE_COORDINATE,
        apply_entitlement_lifecycle, _validate_research_account_authority,
    )
    boundary = pd.Timestamp('2026-01-01', tz='UTC')
    cut = pd.Timestamp(cutoff)
    if pd.isna(cut) or cut.tzinfo is None or cut.tz_convert('UTC') > boundary:
        raise ValueError('CASH_H5_EXPLICIT_PRE2026_FOLD_CUTOFF_REQUIRED')
    cut = cut.tz_convert('UTC')
    dates = pd.DatetimeIndex(pd.to_datetime(calendar))
    if (dates.empty or dates.tz is not None or dates.hasnans or dates.has_duplicates
            or not dates.is_monotonic_increasing or not dates.equals(dates.normalize())
            or dates.max() >= pd.Timestamp('2026-01-01')):
        raise ValueError('CASH_H5_PRE2026_LEGAL_SESSION_CALENDAR_REQUIRED')
    required = {'signal_date', 'ticker', 'security_id'}
    if not required.issubset(keys) or keys.duplicated(['signal_date', 'ticker']).any():
        raise ValueError('CASH_H5_EXACT_SIGNAL_SECURITY_KEYS_REQUIRED')
    if keys.duplicated(['signal_date', 'security_id']).any():
        raise ValueError('CASH_H5_AMBIGUOUS_SAME_DAY_SECURITY_IDENTITY')
    known = keys.security_id.map(lambda value: isinstance(value, str) and bool(value.strip())
        and not any(tag in value.upper() for tag in ('UNKNOWN', 'PLACEHOLDER', 'FROZEN_VENDOR:', 'UNCONFIRMED')))
    if not known.all():
        raise ValueError('CASH_H5_KNOWN_SECURITY_ID_REQUIRED')
    clock = lambda day, hour: (pd.Timestamp(day) + pd.Timedelta(hours=hour,
        minutes=30 if hour == 9 else 0)).tz_localize('America/New_York').tz_convert('UTC')
    signal_days = pd.DatetimeIndex(pd.to_datetime(keys.signal_date))
    raw_days = pd.DatetimeIndex(pd.to_datetime(raw.trade_date))
    if (signal_days.tz is not None or raw_days.tz is not None or signal_days.hasnans or raw_days.hasnans
            or any(clock(day, 16) >= cut for day in signal_days)
            or any(clock(day, 9) >= cut for day in raw_days)):
        raise ValueError('CASH_H5_INPUT_CLOCK_NOT_BEFORE_FOLD_CUTOFF')
    events = tuple(cash_events)
    if type(label_only_post_verified_cash) is not bool:
        raise ValueError('CASH_H5_EXPLICIT_LABEL_ONLY_BOOLEAN_REQUIRED')
    if (not label_only_post_verified_cash and
            (research_cash_authority is not None or tuple(cash_publication_proofs))):
        raise ValueError('CASH_H5_LABEL_ONLY_OPT_IN_REQUIRED')
    allowed = ((SourceBackedEntitlementEvent, ResearchReconstructedCashEvent)
        if label_only_post_verified_cash else (SourceBackedEntitlementEvent,))
    if any(type(event) not in allowed for event in events):
        raise ValueError('CASH_H5_STRICT_SOURCE_DATED_CASH_EVENTS_REQUIRED')
    if len({event.event_id for event in events}) != len(events):
        raise ValueError('CASH_H5_DUPLICATE_CASH_EVENT_ID')
    reconstructed = tuple(e for e in events if type(e) is ResearchReconstructedCashEvent)
    label_known_at = {}
    validated_authority = None
    if reconstructed:
        # The old authority remains the unique source/terms admission owner.
        # This does not turn its accounting-only admission into label knowledge.
        if (not isinstance(research_cash_authority, dict) or
                research_cash_authority.get('schema') != 'B_FROZEN_HISTORY_CASH_ACCOUNT_AUTHORITY_V1'):
            raise ValueError('CASH_H5_ORIGINAL_B_CASH_AUTHORITY_REQUIRED')
        validated_authority = _validate_research_account_authority(events, research_cash_authority)
        proofs = tuple(cash_publication_proofs)
        if (any(not isinstance(p, dict) for p in proofs)
                or len({p.get('event_fingerprint') for p in proofs}) != len(proofs)
                or sorted(p.get('event_fingerprint', '') for p in proofs)
                    != sorted(e.event_fingerprint for e in reconstructed)):
            raise ValueError('CASH_H5_EXACT_LABEL_PUBLICATION_PROOFS_REQUIRED')
        for event in reconstructed:
            proof = next(p for p in proofs if p['event_fingerprint'] == event.event_fingerprint)
            exact = dict(schema='B_CASH_LABEL_PUBLICATION_BOUND_PROOF_V1',
                clock_role='LABEL_KNOWLEDGE_ONLY_NOT_DECISION_AVAILABILITY',
                publication_bound_status='SOURCE_BOUND_CONSERVATIVE_UPPER_BOUND',
                event_fingerprint=event.event_fingerprint, security_id=event.old_security_id,
                ticker=event.ticker, ex_date=event.ex_date,
                publication_bound_proof_ref=dict(path=event.reconstruction_ref,
                    sha256=event.reconstruction_sha256))
            if any(type(proof.get(k)) is not type(v) or proof.get(k) != v for k, v in exact.items()):
                raise ValueError('CASH_H5_LABEL_PUBLICATION_SUBJECT_OR_SOURCE_PIN_MISMATCH')
            known_at = pd.Timestamp(proof.get('publication_known_at'))
            if pd.isna(known_at) or known_at.tzinfo is None:
                raise ValueError('CASH_H5_LABEL_PUBLICATION_KNOWLEDGE_CLOCK_REQUIRED')
            known_at = known_at.tz_convert('UTC')
            if not known_at < cut:
                raise ValueError('CASH_H5_LABEL_PUBLICATION_NOT_BEFORE_FOLD_CUTOFF')
            if event.available_at is not None and known_at < pd.Timestamp(event.available_at).tz_convert('UTC'):
                raise ValueError('CASH_H5_LABEL_PUBLICATION_KNOWLEDGE_MAY_NOT_BACKDATE_SOURCE')
            label_known_at[event.event_fingerprint] = known_at
    elif research_cash_authority is not None or tuple(cash_publication_proofs):
        raise ValueError('CASH_H5_LABEL_PROOFS_WITHOUT_RECONSTRUCTED_EVENTS')
    records = tuple(event_records)
    frame = shareholder_open_targets(keys, raw, dates, records, apply_event_windows)
    frame['security_id'] = keys.security_id.to_numpy()
    frame['label_quantity_event_count'] = frame.label_common_event_count
    frame['label_cash_event_count'] = 0
    frame['label_cash_paid_per_entry_share'] = np.nan
    frame['label_cash_receivable_per_entry_share'] = np.nan
    frame['label_available_at'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
    frame['cash_label_reason'] = 'UNQUALIFIED_OR_MISSING_ENDPOINT_OR_QUANTITY_EVENT'
    frame['y_open5'] = np.nan
    frame['label_coordinate'] = 'CASH_INCLUSIVE_SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_V1'
    frame['target_source'] = 'EXISTING_RAW_AND_QUANTITY_OWNER_PLUS_SOURCE_BACKED_ENTITLEMENT_OWNER_V1'
    frame['strict_PIT_promotion_eligible'] = False
    if reconstructed:
        frame['label_only_post_verified_cash'] = True
        frame['target_source'] = 'EXISTING_RAW_AND_QUANTITY_OWNER_PLUS_LABEL_ONLY_POST_VERIFIED_CASH_OWNER_V1'
    # Price lookup is after the original endpoint validation; no replacement mark.
    opening = raw.set_index(['ticker', pd.to_datetime(raw.trade_date)]).open
    positions = {day: i for i, day in enumerate(dates)}
    for i, row in frame.iterrows():
        eligible = bool(row.label_available)
        frame.at[i, 'label_available'] = False
        if not eligible or pd.isna(row.label_end_date):
            continue
        entry, end = pd.Timestamp(row.execution_date), pd.Timestamp(row.label_end_date)
        mature = clock(row.label_mature_date, 16)
        if not mature < cut:
            frame.at[i, 'cash_label_reason'] = 'LABEL_NOT_MATURE_BEFORE_FOLD_CUTOFF'
            continue
        relevant = tuple(event for event in events if event.ticker == row.ticker
            and entry < pd.Timestamp(event.ex_date) <= end)
        frame.at[i, 'label_cash_event_count'] = len(relevant)
        frame.at[i, 'label_common_event_count'] = int(row.label_quantity_event_count) + len(relevant)
        available_at = mature
        try:
            # Additional quantity-clock proof is required only in this new target.
            # The old owner and all old labels keep their original semantics.
            for event in records:
                day = pd.Timestamp(event['event_date'])
                if event['ticker'] != row.ticker or not entry < day <= end:
                    continue
                available = pd.Timestamp(event.get('available_at'))
                if (pd.isna(available) or available.tzinfo is None
                        or not available.tz_convert('UTC') < cut
                        or available.tz_convert('UTC') > clock(day, 9)):
                    raise ValueError('QUANTITY_EVENT_SOURCE_CLOCK_UNKNOWN_OR_LATE')
                sid = event.get('security_id', event.get('old_security_id'))
                if sid != row.security_id:
                    raise ValueError('QUANTITY_EVENT_SECURITY_ID_UNKNOWN_OR_MISMATCH')
            for event in relevant:
                if type(event) is ResearchReconstructedCashEvent:
                    event.__post_init__(source_scope='B_FROZEN_PRE2026_ACCOUNTING_ONLY')
                else:
                    event.__post_init__()  # Revalidate deserialized/corrupted terms.
                if event.action_type not in CASH_ENTITLEMENT_FAMILIES:
                    raise ValueError('UNSUPPORTED_CASH_EVENT_FAMILY')
                if event.old_security_id != row.security_id:
                    raise ValueError('CASH_EVENT_SECURITY_ID_MISMATCH')
                available = (label_known_at[event.event_fingerprint]
                    if type(event) is ResearchReconstructedCashEvent else pd.Timestamp(event.available_at))
                if not available.tz_convert('UTC') < cut:
                    raise ValueError('CASH_EVENT_SOURCE_NOT_BEFORE_FOLD_CUTOFF')
                available_at = max(available_at, available.tz_convert('UTC'))
                if pd.Timestamp(event.ex_date) not in positions:
                    raise ValueError('CASH_EVENT_EX_NOT_LEGAL_SESSION')
            cash, receivable, state = 0., 0., None
            lifecycle_kwargs = {}
            historical_fingerprints = {e.event_fingerprint for e in relevant
                if type(e) is ResearchReconstructedCashEvent}
            if historical_fingerprints:
                # Exact subset transport; all terms validation and arithmetic
                # remain in the existing owner, including its authority check.
                admission = validated_authority['frozen_history_cash_admission']
                scoped_admission = dict(admission, events=[dict(item)
                    for item in admission['events']
                    if item['event_fingerprint'] in historical_fingerprints])
                lifecycle_kwargs['research_account_authority'] = dict(validated_authority,
                    frozen_history_cash_admission=scoped_admission)
            for di in range(positions[entry] + 1, positions[end] + 1) if relevant else ():
                day = dates[di]
                # Snapshot raw-old shares strictly before this ex session.
                # Multiplication remains solely inside the original owner.
                probe = pd.DataFrame({'ticker': [row.ticker], 'execution_date': [entry],
                                      'label_end_date': [dates[di - 1]]})
                quantity, blocked, _ = apply_event_windows(probe, records)
                if bool(blocked[0]) or not np.isfinite(quantity[0]) or quantity[0] <= 0:
                    raise ValueError('PRE_EX_QUANTITY_UNQUALIFIED')
                applied = apply_entitlement_lifecycle(relevant,
                    {row.security_id: float(quantity[0])}, cash,
                    execution_date=day, session_open_at=clock(day, 9),
                    security_tickers={row.security_id: row.ticker},
                    quantity_coordinate=RAW_OLD_SHARE_COORDINATE, state=state, enabled=True,
                    **lifecycle_kwargs)
                if not applied.accounting_qualified:
                    raise ValueError('CASH_ENTITLEMENT_UNQUALIFIED:' + str(applied.state.blocked_events))
                cash, receivable, state = applied.cash, applied.receivable_value_usd, applied.state
            entry_open, exit_open = float(opening.loc[(row.ticker, entry)]), float(opening.loc[(row.ticker, end)])
            value = (float(row.label_quantity_multiplier) * exit_open + cash + receivable) / entry_open - 1.
            if not np.isfinite(value):
                raise ValueError('CASH_H5_NONFINITE_UNIT_LOT_VALUE')
        except (ValueError, TypeError, KeyError) as error:
            frame.at[i, 'cash_label_reason'] = str(error)
            frame.at[i, 'label_unsupported_common_event'] = True
            continue
        frame.at[i, 'label_available'] = True
        frame.at[i, 'y_open5'] = value
        frame.at[i, 'label_cash_paid_per_entry_share'] = cash
        frame.at[i, 'label_cash_receivable_per_entry_share'] = receivable
        frame.at[i, 'label_available_at'] = available_at
        frame.at[i, 'cash_label_reason'] = 'QUALIFIED_CALLER_SOURCE_COVERAGE_REQUIRED'
    return frame
