"""Synthetic source-unit and pre-materialization read-boundary counterexamples."""
import copy
import socket

import pandas as pd
import pytest
import requests

from scripts.research.a2.options import price_basis as basis
from scripts.research.a2.options.contracts import Invalid


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('price coordinate tests must remain offline')
    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def qualified(tmp_path):
    evidence = tmp_path/'source-contract.txt'
    evidence.write_text('INVENTED source contract', encoding='utf-8')
    return dict(status=basis.STATUS, identity='SPY', provider='INVENTED', source_version='fixture1',
                source_field='close', source_basis='RAW', currency='USD', session='REGULAR',
                date_semantics='Invented New York market date', session_basis='Invented regular close',
                evidence=[dict(path=str(evidence), sha256=basis._file_digest(evidence))])


def row(day='2024-03-04', close=100., **changes):
    return dict(identity='SPY', market_date=day, source_close=close) | changes


def split_qualified(qualified, events, **changes):
    return qualified | dict(source_basis='SPLIT_ADJUSTED', split_basis=dict(
        status='COMPLETE_EVENT_CHAIN', direction='C_ADJ_EQUALS_C_RAW_DIV_F',
        coverage_start='2024-01-01', basis_end='2024-12-31', events=events,
        evidence_ref=qualified['evidence'][0]['path']) | changes)


def split(day, new, old):
    return dict(kind='SPLIT', effective_date=day, new_shares=new, old_shares=old)


def test_raw_does_not_double_apply_split_and_needs_no_yahoo_basis(qualified):
    q = qualified | dict(split_basis={'events': [split('2024-03-05', 2, 1)]})
    result = basis.trade_basis(row(), q)
    assert result['close_trade_basis'] == 100 and result['factor_to_trade_basis'] == 1
    assert result['factor_basis'] == 'RAW_IDENTITY_NO_SPLIT_TRANSFORM'


@pytest.mark.parametrize('events,day,expected', [
    ([split('2024-03-05', 2, 1)], '2024-03-04', 200.),
    ([split('2024-03-05', 1, 5)], '2024-03-04', 20.),
    ([split('2024-03-05', 2, 1), split('2024-04-01', 1, 5)], '2024-03-04', 40.),
    ([split('2024-03-05', 2, 1)], '2024-03-05', 100.),
    ([split('2024-03-05', 2, 1)], '2024-03-06', 100.),
])
def test_forward_reverse_multiple_and_effective_day_units(qualified, events, day, expected):
    assert basis.trade_basis(row(day), split_qualified(qualified, events))['close_trade_basis'] == expected


@pytest.mark.parametrize('events,changes,reason', [
    (None, {}, 'EMPTY_SPLIT_CHAIN_UNPROVED'),
    ([], {}, 'EMPTY_SPLIT_CHAIN_UNPROVED'),
    ([], {'status': 'HTTP_429', 'empty_events_certified': True}, 'SPLIT_CHAIN_UNPROVED'),
    ([], {'direction': None, 'empty_events_certified': True}, 'SPLIT_CHAIN_UNPROVED'),
    ([], {'evidence_ref': 'unbound', 'empty_events_certified': True}, 'SPLIT_CHAIN_UNPROVED'),
    ([split('2024-03-05', 2, 1) | {'kind': 'CASH_DIVIDEND'}], {}, 'NON_SPLIT_ADJUSTMENT'),
    ([split('2024-03-05', 0, 1)], {}, 'INVALID_PRICE_OR_SPLIT_RATIO'),
])
def test_unknown_empty_failed_and_cash_adjustment_never_assume_one(qualified, events, changes, reason):
    with pytest.raises(Invalid, match=reason):
        basis.trade_basis(row(), split_qualified(qualified, events, **changes))


def test_bound_certified_empty_events_have_identity_factor(qualified):
    q = split_qualified(qualified, [], empty_events_certified=True)
    assert basis.trade_basis(row(), q)['factor_to_trade_basis'] == 1


@pytest.mark.parametrize('changes', [{'source_basis': 'UNKNOWN'}, {'source_basis': 'TOTAL_RETURN_ADJUSTED'},
    {'identity': 'QQQ'}, {'currency': 'EUR'}, {'session': 'EXTENDED'}, {'source_version': ''}])
def test_source_contract_cannot_be_relabelled_as_raw(qualified, changes):
    with pytest.raises(Invalid):
        basis.trade_basis(row(), qualified | changes)


@pytest.mark.parametrize('data', [row('2026-01-02'), row('2024-03-03'), row(identity='QQQ'), row(close=None)])
def test_invalid_market_keys_and_null_prices_rejected(qualified, data):
    with pytest.raises(Invalid):
        basis.trade_basis(data, qualified)


@pytest.mark.parametrize('data', [row('2026-01-02'), row('2024-03-03'), row(identity='QQQ')])
def test_real_parquet_read_boundary_rejects_before_economic_projection(tmp_path, qualified, monkeypatch, data):
    path = tmp_path/'invented.parquet'
    pd.DataFrame([data]).to_parquet(path, index=False)
    binding = dict(path=str(path), sha256=basis._file_digest(path), qualification=qualified,
                   allowed_reference_dates=[data['market_date']])
    original, reads = basis.ds.dataset, []
    class AuditedDataset:
        def __init__(self):
            self.delegate = original(path, format='parquet')
            self.schema = self.delegate.schema
        def to_table(self, *, columns):
            reads.append(columns)
            assert 'source_close' not in columns
            return self.delegate.to_table(columns=columns)
    monkeypatch.setattr(basis.ds, 'dataset', lambda *args, **kwargs: AuditedDataset())
    with pytest.raises(Invalid):
        basis.read_trade_references(binding, binding['allowed_reference_dates'])
    assert reads == [['identity', 'market_date']]


def test_parquet_mapping_preserves_input_bytes_and_source_label(tmp_path, qualified):
    path = tmp_path/'invented.parquet'
    pd.DataFrame([row()]).to_parquet(path, index=False)
    before, q = path.read_bytes(), copy.deepcopy(qualified)
    binding = dict(path=str(path), sha256=basis._file_digest(path), qualification=qualified,
                   allowed_reference_dates=['2024-03-04'])
    result = basis.read_trade_references(binding, binding['allowed_reference_dates'])
    assert result.to_dict('records') == [dict(ticker='SPY', date='2024-03-04', close=100.,
                                            adjustment='raw', source='INVENTED', currency='USD')]
    assert path.read_bytes() == before and qualified == q


@pytest.mark.parametrize('changes', [{'currency': 'EUR'}, {'session': 'EXTENDED'}, {'identity': 'QQQ'}])
def test_invalid_units_rejected_before_economic_projection(tmp_path, qualified, monkeypatch, changes):
    path = tmp_path/'invented.parquet'
    pd.DataFrame([row()]).to_parquet(path, index=False)
    binding = dict(path=str(path), sha256=basis._file_digest(path), qualification=qualified | changes,
                   allowed_reference_dates=['2024-03-04'])
    original, reads = basis.ds.dataset, []
    class AuditedDataset:
        def __init__(self):
            self.delegate = original(path, format='parquet')
            self.schema = self.delegate.schema
        def to_table(self, *, columns):
            reads.append(columns)
            assert 'source_close' not in columns
            return self.delegate.to_table(columns=columns)
    monkeypatch.setattr(basis.ds, 'dataset', lambda *args, **kwargs: AuditedDataset())
    with pytest.raises(Invalid, match='PRICE_IDENTITY_UNITS_INVALID'):
        basis.read_trade_references(binding, binding['allowed_reference_dates'])
    assert reads == [['identity', 'market_date']]
