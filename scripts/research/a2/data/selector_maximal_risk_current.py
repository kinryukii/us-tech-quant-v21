"""C14 full-U metadata binding over the frozen R5 identity owners.

No bank, state, label, score, feature value or outcome is opened here. The caller
supplies a reviewed support-phase ProjectedReader and frozen support metadata.
Native UID/epoch ownership stays with R5; the frozen CUSIP namespace owner alone
maps those UIDs to C14 keys. This module grants no numeric read authority.
"""
from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import pandas as pd
from scripts.research.a2.data import joint_event_risk_support_r5 as discovery
from scripts.research.a2.data import selector_shared_risk_consumer as namespace_owner
from scripts.research.a2.evaluation import joint_event_risk_execution_r5 as native
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock, COORDINATE
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

RAW_META = ('signal_date', 'ticker', 'security_uid', 'U_t_fingerprint', 'raw_rank')
NAMESPACE_SHA = '71a57696ba1596ee03c17939d561b75cfcd9870969aadc32991fc4e0dbf79fd3'
BOUNDARY = pd.Timestamp('2026-01-01')


def need(value, reason):
    if not value:
        raise ValueError(reason)


def namespace_source():
    path = Path(namespace_owner.__file__).resolve()
    need(hashlib.sha256(path.read_bytes()).hexdigest() == NAMESPACE_SHA,
         'FROZEN_NAMESPACE_OWNER_CHANGED')
    return dict(path=str(path), sha256=NAMESPACE_SHA)


def raw_metadata(frame):
    need(tuple(frame.columns) == RAW_META, 'EXACT_C14_METADATA_COLUMNS_ONLY')
    out = frame.copy()
    out['signal_date'] = pd.to_datetime(out.signal_date)
    need(not out.empty and out.signal_date.notna().all() and out.signal_date.dt.tz is None
         and out.signal_date.lt(BOUNDARY).all(), 'PRE2026_CURRENT_KEYS_REQUIRED')
    need(not out.duplicated(['signal_date', 'ticker']).any(), 'UNIQUE_CURRENT_TICKER_KEYS_REQUIRED')
    for _, part in out.groupby('signal_date', sort=False):
        namespace_owner.current_map(part)
        need(part.U_t_fingerprint.map(discovery.known).all()
             and part.U_t_fingerprint.nunique() == 1, 'ONE_FROZEN_FULL_U_FINGERPRINT_REQUIRED')
        ranks = pd.to_numeric(part.raw_rank, errors='coerce')
        need(ranks.notna().all() and ranks.eq(ranks.astype(int)).all()
             and sorted(ranks.tolist()) == list(range(1, len(part) + 1)), 'COMPLETE_RAW_RANK_PERMUTATION_REQUIRED')
    return out


def bind_current(c_raw_metadata, pool, event, current_clock, source_pins, *, dependency='PRIMARY'):
    """Pure full-domain binding; native strings/epochs are never normalized."""
    namespace_ref = namespace_source()
    raw = raw_metadata(c_raw_metadata)
    at = pd.Timestamp(current_clock)
    need(at.tzinfo is not None and at < pd.Timestamp('2026-01-01', tz='UTC'),
         'PRE2026_EXPLICIT_CURRENT_CLOCK_REQUIRED')
    day = at.tz_convert('America/New_York').tz_localize(None).normalize()
    need(at == _clock(day) and raw.signal_date.eq(day).all(), 'EXACT_CURRENT_CLOSE_DATE_REQUIRED')
    need(pd.Timestamp(event['decision_asof']) <= at, 'FUTURE_EVENT_WITNESS_FORBIDDEN')
    assets = tuple(pool['assets'])
    need(assets and assets == tuple(sorted(set(assets))) and not pool['blocked_assets'],
         'FULL_ORDERED_UNBLOCKED_NATIVE_U_REQUIRED')
    expected = dict(assets=list(event['requested_assets']), asset_uids=event['asset_uids'],
                    asset_epochs=event['asset_epochs'], segment_starts=event['segment_starts'], blocked_assets={})
    actual = discovery.pool_identity(pool)
    actual['assets'] = list(actual['assets'])
    need(actual == expected, 'CURRENT_CURSOR_EVENT_UID_EPOCH_OR_FULL_U_CHANGED')
    signature = event['complete_structural_signature']
    need(content_hash(signature) == event['structural_signature_sha256']
         and signature['ordered_assets'] == list(assets)
         and signature['asset_uids'] == pool['asset_uids']
         and signature['asset_epochs'] == pool['asset_epochs'], 'ORIGINAL_EVENT_STRUCTURAL_WITNESS_CHANGED')
    native_uids = pool['asset_uids']
    need(set(native_uids) == set(assets) and len(set(native_uids.values())) == len(assets),
         'ONE_TO_ONE_NATIVE_UID_REQUIRED')
    # Reuse the frozen strict nine-character CUSIP owner, never strip/guess IDs.
    consumer_uids = {a: namespace_owner.namespace(native_uids[a]) for a in assets}
    need(namespace_owner.current_map(raw) == consumer_uids, 'EXACT_FULL_U_CANONICAL_CUSIP_MISMATCH')
    need(source_pins and all(isinstance(v, str) and len(v) == 64
         and set(v) <= set('0123456789abcdef') for v in source_pins.values()),
         'EXACT_NATIVE_SOURCE_PINS_REQUIRED')
    return dict(assets=list(assets), asset_uids=copy.deepcopy(native_uids),
        asset_epochs=copy.deepcopy(pool['asset_epochs']), segment_starts=copy.deepcopy(pool['segment_starts']),
        consumer_uids=consumer_uids, security_coordinate=COORDINATE,
        source_support_identity=native.source_support_identity(event, dependency, source_pins),
        raw_rank_by_consumer_uid=dict(zip(raw.security_uid, raw.raw_rank.astype(int))),
        U_t_fingerprint=raw.U_t_fingerprint.iloc[0], current_identity_asof=at.isoformat(),
        support_epoch_event_id=event['event_id'], namespace_owner_sha256=namespace_ref['sha256'],
        consumer_namespace_owner_ref=namespace_ref,
        c14_current_key_sha256=content_hash(raw.sort_values('raw_rank').astype(str).values.tolist()),
        numeric_read_authority=False, strict_PIT_promotion_eligible=False)


def project_current_bindings(reader, c_raw_metadata, support, source_pins, *, required_dates, dependency='PRIMARY'):
    """Replay every calendar session through original cursor, yielding keys only.

    The original event is checked at its original Close via current_pool_binding.
    Carry days retain that event and require an independently replayed identical
    full U/UID/epoch/segment witness; event clocks are never rewritten.
    """
    need(reader.phase == 'support', 'SUPPORT_PHASE_READER_ONLY')
    namespace_source()
    raw = raw_metadata(c_raw_metadata)
    requested = pd.DatetimeIndex(pd.to_datetime(list(required_dates)))
    need(not requested.empty and requested.tz is None and not requested.has_duplicates
         and requested.is_monotonic_increasing and requested.max() < BOUNDARY
         and list(pd.DatetimeIndex(sorted(raw.signal_date.unique()))) == list(requested),
         'EXACT_FROZEN_CURRENT_DATE_MASK_REQUIRED')
    end = requested[-1]
    # Native reader stop is exclusive and disallows 2026; physical pre2026 guard
    # and its mandatory predicate cover the final legal day when stop is omitted.
    stop = end + pd.Timedelta(days=1)
    stop = None if stop >= BOUNDARY else stop
    calendar = reader.read('calendar', ('trade_date',), date_field='trade_date', stop=stop)
    days, _ = _calendar(calendar.trade_date)
    need(set(requested) <= set(days), 'CURRENT_DATES_NOT_IN_NATIVE_CALENDAR')
    features = reader.read('prediction_features', discovery.old.FEATURE_META, date_field='signal_date', stop=stop)
    raw_keys = reader.read('raw_open_close', ('ticker', 'trade_date', 'code'), date_field='trade_date', stop=stop)
    features['signal_date'] = pd.to_datetime(features.signal_date)
    raw_keys['trade_date'] = pd.to_datetime(raw_keys.trade_date)
    event_rows = support['events']
    events = {e['event_id']: e for e in event_rows}
    need(len(events) == len(event_rows), 'UNIQUE_ORIGINAL_EVENT_IDS_REQUIRED')
    daily_rows = support['daily_support_chain']
    daily = {pd.Timestamp(d['decision_date']): d for d in daily_rows}
    need(len(daily) == len(daily_rows) and set(requested) <= set(daily), 'COMPLETE_NATIVE_DAILY_SUPPORT_REQUIRED')
    feature_days = {d: x for d, x in features.groupby('signal_date', sort=False)}
    raw_days = {d: x for d, x in raw_keys.groupby('trade_date', sort=False)}
    consumer_days = {d: x for d, x in raw.groupby('signal_date', sort=False)}
    cursor = discovery.MetadataPoolCursor(days)
    verified = set()
    for day in days:
        if day > end:
            break
        today = feature_days.get(day, features.iloc[:0])
        today_raw = raw_days.get(day, raw_keys.iloc[:0])
        pool = cursor.step(day, today, today_raw)
        if day not in consumer_days:
            continue
        d = daily[day]
        need(pd.Timestamp(d['decision_asof']) == _clock(day), 'EXACT_NATIVE_DAILY_CLOSE_REQUIRED')
        event = events[d['support_epoch_event_id']]
        if day == pd.Timestamp(event['decision_date']):
            history = features.loc[features.signal_date.le(day)]
            checked, _, _ = native.current_pool_binding(history, today_raw, event, days)
            need(discovery.pool_identity(checked) == discovery.pool_identity(pool),
                 'NATIVE_CURRENT_BINDING_CURSOR_DISAGREEMENT')
            verified.add(event['event_id'])
        need(event['event_id'] in verified, 'ORIGINAL_EVENT_WITNESS_NOT_REPLAYED')
        yield day, bind_current(consumer_days[day], pool, event, _clock(day), source_pins, dependency=dependency)
