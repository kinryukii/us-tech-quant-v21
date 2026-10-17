"""Synthetic metadata-only C14 current-U binding; no physical research input."""
import copy
import pandas as pd
import pytest
from scripts.research.a2.data import selector_maximal_risk_current as m


def fixture():
    days = pd.bdate_range('2022-12-27', periods=8)
    uids = {'A': '000000001', 'B': '000000002', 'C': '000000003'}
    features = pd.DataFrame([dict(ticker=a, signal_date=d, security_id=uids[a],
        feature_available=True, all_features_finite=True, feature_source=m.discovery.old.FEATURE_TAGS[0])
        for d in days for a in ('A', 'B', 'C')])
    raw_keys = pd.DataFrame([dict(ticker=a, trade_date=d, code='US.' + a) for d in days for a in ('A', 'B', 'C')])
    cursor = m.discovery.MetadataPoolCursor(days)
    pools = {d: cursor.step(d, features.loc[features.signal_date.eq(d)], raw_keys.loc[raw_keys.trade_date.eq(d)]) for d in days}
    requested = days[5:]
    pool = pools[requested[0]]
    signature = dict(ordered_assets=list(pool['assets']), asset_uids=pool['asset_uids'], asset_epochs=pool['asset_epochs'])
    event = dict(event_id='event', decision_date=requested[0].date().isoformat(), decision_asof=m._clock(requested[0]).isoformat(),
        fit_history_cutoff=m._clock(days[4]).isoformat(), current_identity_available_at=m._clock(requested[0]).isoformat(),
        requested_assets=list(pool['assets']), asset_uids=pool['asset_uids'], asset_epochs=pool['asset_epochs'], segment_starts=pool['segment_starts'],
        complete_structural_signature=signature, structural_signature_sha256=m.content_hash(signature),
        dependency_local_event_ids={n:n + 'event' for n in ('PRIMARY', 'QQQ', 'FF48')},
        dependency_local_signature_sha256={n:'a'*64 for n in ('PRIMARY', 'QQQ', 'FF48')},
        history_support=dict(current_identity_blockers={}, source_metadata_blockers={}, parent_origin_count=252, qqq_h5_endpoint_key_support=True))
    raw = pd.DataFrame([dict(signal_date=d, ticker=a, security_uid='CUSIP:' + uids[a], U_t_fingerprint='frozen-U', raw_rank=rank)
        for d in requested for rank, a in enumerate(('C', 'A', 'B'), start=1)], columns=m.RAW_META)
    support = dict(events=[event], daily_support_chain=[dict(decision_date=d.date().isoformat(), decision_asof=m._clock(d).isoformat(), support_epoch_event_id='event') for d in requested])
    return days, features, raw_keys, pools, requested, event, raw, support


def bind():
    _, _, _, pools, requested, event, raw, _ = fixture()
    day = requested[0]
    return raw.loc[raw.signal_date.eq(day)], pools[day], event, m._clock(day), {'identity':'b'*64}


def test_frozen_namespace_only_native_order_epoch_and_separate_raw_rank():
    raw, pool, event, at, pins = bind()
    saved = copy.deepcopy((raw, pool, event, pins))
    current = m.bind_current(raw, pool, event, at, pins)
    assert current['assets'] == ['A', 'B', 'C']
    assert current['asset_uids'] == pool['asset_uids']
    assert current['asset_epochs'] == pool['asset_epochs']
    assert current['segment_starts'] == pool['segment_starts']
    assert current['consumer_uids']['A'] == 'CUSIP:000000001'
    assert current['consumer_namespace_owner_ref'] == m.namespace_source()
    assert current['raw_rank_by_consumer_uid']['CUSIP:000000003'] == 1
    assert current['numeric_read_authority'] is False and current['strict_PIT_promotion_eligible'] is False
    pd.testing.assert_frame_equal(raw, saved[0])
    assert (pool, event, pins) == saved[1:]


@pytest.mark.parametrize('case', ['wrong_cusip', 'bad_format', 'double_prefix', 'missing_asset', 'new_asset', 'duplicate_uid', 'duplicate_ticker', 'bad_rank', 'fingerprint', 'numeric_column', 'future_clock', 'wrong_date', 'blocked', 'source_pin'])
def test_binding_fail_closed(case):
    raw, pool, event, at, pins = copy.deepcopy(bind())
    if case == 'wrong_cusip': raw.loc[raw.index[0], 'security_uid'] = 'CUSIP:999999999'
    if case in ('bad_format', 'double_prefix'):
        uid = 'CUSIP:000000001' if case == 'double_prefix' else 'bad'
        pool['asset_uids']['A'] = uid; event['asset_uids']['A'] = uid
        event['complete_structural_signature']['asset_uids']['A'] = uid
        event['structural_signature_sha256'] = m.content_hash(event['complete_structural_signature'])
    if case == 'missing_asset': raw = raw.iloc[:2].copy(); raw['raw_rank'] = [1, 2]
    if case == 'new_asset': raw.loc[raw.index[0], 'ticker'] = 'NEW'
    if case == 'duplicate_uid': raw.loc[raw.index[0], 'security_uid'] = raw.security_uid.iloc[1]
    if case == 'duplicate_ticker': raw.loc[raw.index[0], 'ticker'] = raw.ticker.iloc[1]
    if case == 'bad_rank':
        raw['raw_rank'] = raw.raw_rank.astype(float)
        raw.loc[raw.index[0], 'raw_rank'] = 1.5
    if case == 'fingerprint': raw.loc[raw.index[0], 'U_t_fingerprint'] = 'other'
    if case == 'numeric_column': raw['score'] = 1.
    if case == 'future_clock': at = pd.Timestamp('2026-01-01T21:00:00Z')
    if case == 'wrong_date': raw['signal_date'] += pd.Timedelta(days=1)
    if case == 'blocked': pool['blocked_assets'] = {'A':'AMBIGUOUS_OR_MISSING_CURRENT_UID'}
    if case == 'source_pin': pins = {'identity':'x'*64}
    with pytest.raises(ValueError): m.bind_current(raw, pool, event, at, pins)


class Reader:
    phase = 'support'
    def __init__(self, days, features, raw):
        self.frames = dict(calendar=pd.DataFrame({'trade_date':days}), prediction_features=features, raw_open_close=raw)
        self.audit = []
    def read(self, name, columns, *, date_field, stop=None):
        expected = dict(calendar=('trade_date',), prediction_features=m.discovery.old.FEATURE_META, raw_open_close=('ticker','trade_date','code'))
        assert tuple(columns) == expected[name]
        frame = self.frames[name]
        self.audit.append((name, tuple(columns), stop))
        mask = pd.to_datetime(frame[date_field]).lt('2026-01-01')
        if stop is not None: mask &= pd.to_datetime(frame[date_field]).lt(stop)
        return frame.loc[mask, list(columns)].copy()


def replay(features=None, support=None):
    days, original, raw_keys, _, requested, _, raw, original_support = fixture()
    reader = Reader(days, original if features is None else features, raw_keys)
    result = list(m.project_current_bindings(reader, raw, original_support if support is None else support,
        {'identity':'b'*64}, required_dates=requested))
    return result, reader


def test_full_history_cursor_and_original_event_binding_are_reused(monkeypatch):
    original = m.native.current_pool_binding
    calls = []
    def checked(*args):
        calls.append(args[2]['decision_asof'])
        return original(*args)
    monkeypatch.setattr(m.native, 'current_pool_binding', checked)
    result, reader = replay()
    assert len(result) == 3 and len(calls) == 1
    assert all(x['segment_starts']['A'] == '2022-12-27' for _, x in result)
    assert len({x['support_epoch_event_id'] for _, x in result}) == 1
    assert len({x['asset_epochs']['A'] for _, x in result}) == 1
    assert {n for n, _, _ in reader.audit} == {'calendar','prediction_features','raw_open_close'}


@pytest.mark.parametrize('case', ['uid_change', 'gap', 'new_eligible', 'wrong_epoch', 'unreplayed_event'])
def test_carry_cannot_stitch_identity_or_invent_epoch(case):
    days, features, raw_keys, _, requested, event, raw, support = fixture()
    day = requested[1]
    if case == 'uid_change': features.loc[features.ticker.eq('A') & features.signal_date.ge(day), 'security_id'] = '000000009'
    if case == 'gap': features = features.loc[~(features.ticker.eq('A') & features.signal_date.eq(days[2]))]
    if case == 'new_eligible': features.loc[features.ticker.eq('C') & features.signal_date.ge(day), 'feature_available'] = False
    if case == 'wrong_epoch':
        event['asset_epochs']['A'] = 'invented'; event['complete_structural_signature']['asset_epochs']['A'] = 'invented'
        event['structural_signature_sha256'] = m.content_hash(event['complete_structural_signature'])
    if case == 'unreplayed_event':
        event['decision_date'] = days[4].date().isoformat(); event['decision_asof'] = m._clock(days[4]).isoformat()
    with pytest.raises(ValueError):
        list(m.project_current_bindings(Reader(days, features, raw_keys), raw, support, {'identity':'b'*64}, required_dates=requested))


def test_future_append_does_not_change_earlier_binding():
    baseline, _ = replay()
    days, features, _, _, _, _, _, _ = fixture()
    extra = features.iloc[-3:].copy(); extra['signal_date'] = days[-1] + pd.Timedelta(days=3)
    extra['security_id'] = 'FUTURE_BAD_UID'
    actual, _ = replay(pd.concat([features, extra], ignore_index=True))
    assert actual == baseline


def test_non_support_reader_rejected_before_any_read():
    days, features, raw_keys, _, requested, _, raw, support = fixture()
    reader = Reader(days, features, raw_keys); reader.phase = 'fit'
    with pytest.raises(ValueError, match='SUPPORT_PHASE'):
        list(m.project_current_bindings(reader, raw, support, {'identity':'b'*64}, required_dates=requested))
    assert not reader.audit


def test_standalone_binding_rejects_changed_namespace_owner_before_mapping(tmp_path, monkeypatch):
    raw, pool, event, at, pins = bind()
    changed = tmp_path / 'changed_namespace_owner.py'
    changed.write_text('"""Synthetic changed source; never imported."""\n', encoding='utf-8')
    monkeypatch.setattr(m.namespace_owner, '__file__', str(changed))
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('changed owner was called before physical source validation')
    monkeypatch.setattr(m.namespace_owner, 'current_map', forbidden)
    monkeypatch.setattr(m.namespace_owner, 'namespace', forbidden)
    with pytest.raises(ValueError, match='^FROZEN_NAMESPACE_OWNER_CHANGED$'):
        m.bind_current(raw, pool, event, at, pins)
    assert not calls


def test_standalone_binding_returns_the_physically_verified_owner_reference(monkeypatch):
    original = m.namespace_source
    references = []
    def checked():
        reference = original()
        references.append(reference)
        return reference
    monkeypatch.setattr(m, 'namespace_source', checked)
    current = m.bind_current(*bind())
    assert len(references) == 1
    assert current['consumer_namespace_owner_ref'] is references[0]
    assert current['namespace_owner_sha256'] == references[0]['sha256'] == m.NAMESPACE_SHA



def test_current_security_coordinate_is_native_risk_return_not_stored_label_schema():
    from scripts.research.a2.risk.shared_risk_engine_r2 import COORDINATE
    from scripts.research.a2.data.shared_risk_inputs_r3 import STORED_LABEL_COORDINATE
    current = m.bind_current(*bind())
    assert COORDINATE == 'shareholder_value_open_return'
    assert current['security_coordinate'] == COORDINATE
    assert current['security_coordinate'] != STORED_LABEL_COORDINATE
    assert current['numeric_read_authority'] is False
    assert current['strict_PIT_promotion_eligible'] is False
