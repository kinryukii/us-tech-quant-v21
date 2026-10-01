import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location('raw_display_subject',
    Path(__file__).parents[1] / 'adapters/raw_stock_price_reader.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def frame(open=9.54, close=9.85, date='2026-09-22'):
    return pd.DataFrame([dict(trade_date=pd.Timestamp(date), open=open,
        close=close, high=max(open, close), low=min(open, close), volume=123)])


def test_quotes_remain_dollars_and_dates_are_not_filled():
    rows = subject._combine([frame(), frame(10., 11., '2026-09-24')], 'CHPT', '2026-09-22', '2026-09-24')
    assert [row['date'] for row in rows] == ['2026-09-22', '2026-09-24']
    assert rows[0]['raw_open'] == 9.54
    assert rows[0]['raw_close'] == 9.85
    assert rows[0]['currency'] == 'USD'
    assert rows[0]['adjustment'] == 'RAW'


def test_conflicting_vintages_are_not_silently_selected():
    with pytest.raises(ValueError, match='CONFLICTING_OVERLAP_RAW_PRICE'):
        subject._combine([frame(), frame(open=9.55)], 'CHPT', '2026-09-22', '2026-09-22')


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 0., -1.])
def test_invalid_quote_never_appears_as_usd(value):
    with pytest.raises(ValueError, match='RAW_DISPLAY_INVALID_PRICE'):
        subject._combine([frame(open=value)], 'CHPT', '2026-09-22', '2026-09-22')


def test_hash_failure_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(subject, '_checked_json', lambda ref: (_ for _ in ()).throw(
        ValueError('RAW_DISPLAY_REFERENCE_HASH_MISMATCH')))
    result = subject.read_raw_stock_prices({}, 'CHPT', '2026-09-22', '2026-09-22', paths=object())
    assert result['status'] == 'UNAVAILABLE'
    assert result['rows'] == ()
    assert result['error'] == 'RAW_DISPLAY_REFERENCE_HASH_MISMATCH'


def test_reverse_split_preserves_real_quotes_and_only_rebases_before_event():
    rows = subject._combine([frame(.65, .70, '2025-07-25'),
                             frame(13., 14., '2025-07-28')], 'CHPT', '2025-07-25', '2025-07-28')
    actions = [dict(event_date='2025-07-28', price_multiplier=20.)]
    adjusted = subject._with_split_display(rows, actions, '2025-07-28')
    assert adjusted[0]['raw_open'] == .65
    assert adjusted[0]['split_adjusted_open'] == 13.
    assert adjusted[1]['split_adjusted_open'] == 13.
    assert adjusted[1]['raw_open'] == 13.
    before = subject._with_split_display(rows[:1], actions, '2025-07-25')
    assert before[0]['split_adjusted_open'] == .65


def binding_fixture(monkeypatch):
    from scripts.research.a2.evaluation import demo_performance_prices
    from types import SimpleNamespace
    refs = lambda path: dict(path=path, sha256='hash')
    h = dict(start_date='2023-01-03', outputs={'ranked': refs('full-ranked')}, price_manifest=refs('inputs'))
    a2 = dict(source_id='A2_UPDATED_RESEARCH', ranking_end_date='2026-09-22',
        ranking_manifest=refs('hist'), evaluation_contract=refs('contract'))
    entry = dict(ticker='CHPT', cusips=['OLD', 'NEW'], code='US.CHPT')
    docs = {'a2': a2, 'hist': h, 'contract': {'ranking_manifest': refs('hist')}, 'inputs': {'lineage': [entry]}}
    monkeypatch.setattr(subject, '_checked_json', lambda ref: docs[ref['path']])
    monkeypatch.setattr(subject.base, '_ref', lambda ref: (ref['path'], ref['sha256']))
    monkeypatch.setattr(subject.base, '_hash', lambda path: 'hash')
    seen = []
    def table(path, **kwargs):
        seen.append(path)
        return SimpleNamespace(to_pylist=lambda: [dict(target_date='2023-01-03', security_id='OLD'),
            dict(target_date='2026-09-22', security_id='NEW')])
    monkeypatch.setattr(subject.base.pq, 'read_table', table)
    monkeypatch.setattr(demo_performance_prices, '_raw', lambda *args: frame())
    monkeypatch.setattr(subject, '_split_actions', lambda *args: [])
    return refs('a2'), seen


def test_reader_uses_full_ranked_and_date_bounded_identity(monkeypatch):
    ref, seen = binding_fixture(monkeypatch)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2026-09-01', '2026-09-22', paths=object())
    assert result['status'] == 'READY'
    assert seen == ['full-ranked']
    assert result['rows'][0]['raw_open'] == 9.54
    assert result['rows'][0]['raw_close'] == 9.85


def test_unproven_multi_cusip_range_stays_ambiguous(monkeypatch):
    ref, _ = binding_fixture(monkeypatch)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2023-01-03', '2026-09-22', paths=object())
    assert result['status'] == 'UNAVAILABLE'
    assert result['error'] == 'RAW_DISPLAY_AMBIGUOUS_SECURITY_IDENTITY'


def test_explicit_identity_must_exist_in_requested_period(monkeypatch):
    ref, _ = binding_fixture(monkeypatch)
    result = subject.read_raw_stock_prices(ref, 'CHPT', '2026-09-01', '2026-09-22',
        paths=object(), security_id='OLD')
    assert result['status'] == 'UNAVAILABLE'
    assert result['error'] == 'RAW_DISPLAY_SECURITY_IDENTITY_MISMATCH'


def test_split_reader_excludes_future_noop_and_reports_mixed_action(monkeypatch):
    from types import SimpleNamespace
    records = [dict(code='US.X', ex_div_date=day, join_base=old, join_ert=new,
                    forward_adj_factorA=a, forward_adj_factorB=b)
               for day, old, new, a, b in [('2025-01-02', 1., 1., 1., 0.),
                   ('2025-01-03', 20., 1., 20., .5),
                   ('2025-01-04', 20., 1., 20., 0.),
                   ('2027-01-01', 10., 1., 10., 0.)]]
    monkeypatch.setattr(subject.base.pq, 'read_table', lambda _: SimpleNamespace(to_pandas=lambda: pd.DataFrame(records)))
    result = subject._split_actions(dict(code='US.X', rehab=dict(path='p', sha256='s')),
        lambda *args: 'p', '2026-09-22')
    assert [row['event_date'] for row in result] == ['2025-01-03', '2025-01-04']
    assert result[0]['price_multiplier'] is None
    assert result[1]['price_multiplier'] == 20.


def test_identity_chain_is_not_enabled_for_unknown_ticker_or_changed_evidence(monkeypatch):
    spec = importlib.util.spec_from_file_location('identity_display_subject',
        Path(__file__).parents[1] / 'adapters/stock_identity_display.py')
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    assert identity.read_identity_chain({}, 'UNKNOWN')['status'] == 'UNVERIFIED'
    monkeypatch.setattr(identity, '_json', lambda ref: (_ for _ in ()).throw(ValueError('changed evidence')))
    assert identity.read_identity_chain({}, 'CHPT')['status'] == 'UNVERIFIED'
    with pytest.raises(ValueError):
        identity.validate_identity_chain({'status': 'VERIFIED', 'ticker': 'CHPT', 'parent_a2_manifest': {}})
