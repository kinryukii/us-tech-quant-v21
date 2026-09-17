"""Invented daily observations; no historical payloads or executable Quote fiction."""
import socket
import copy
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from scripts.research.a2.options import expression, spy_observed_frontier as observed
from scripts.research.a2.options.contracts import Fees, Invalid, calendar


VERSION = '37f6c456fe1a4775c875673fb8ef907d5cd2fd66'
DOMAIN = dict(tick=.01, ask_min=.21, ask_max=120., bid_min=.01, bid_max=200.,
              option_spread=.2, stock_spread=.1, tolerance_usd=1e-8)
FEES = Fees(option_slippage=.1, stock_slippage=.01)
IDENTITY_COLUMNS = ['date', 'symbol', 'contract_id', 'expiration', 'strike', 'type']


def test_zero_entry_bid_keeps_ratio_but_not_conditional_amount_or_frontier():
    panel, calls = analyse(entry_rows=[quote(bid=0., ask=2.)])
    row = panel.iloc[0]
    assert row.q_status == 'CALCULATED' and row.q == pytest.approx(.25)
    assert row.cash_reason == 'ZERO_ENTRY_BID_OUTSIDE_AMOUNT_DOMAIN'
    assert pd.isna(row.conditional_wealth_difference) and pd.isna(row.B_min_cash)
    assert calls['conditional_amount_calls'] == calls['solver_calls'] == 0


@pytest.fixture(autouse=True)
def prohibit_network_and_execution_replay(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Daily observation tests cannot request a source or manufacture executable replay inputs')
    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(expression, 'evaluate', forbidden)
    monkeypatch.setattr(expression, 'replay_arm', forbidden)


def plan_row(**changes):
    return dict(decision_id='INVENTED:2024-03-05', reference_date='2024-03-04',
                entry_date='2024-03-05', exit_date='2024-03-12',
                entry_early_close=False, exit_early_close=False, plan_weight=1.) | changes


def contract_id(strike='500', expiration='2024-04-19', *, root='SPY', right='C'):
    strike_code = int(Decimal(str(strike)) * 1000)
    return root + pd.Timestamp(expiration).strftime('%y%m%d') + right + f'{strike_code:08d}'


def identity(day='2024-03-05', strike='500', expiration='2024-04-19', **changes):
    return dict(date=day, symbol='SPY', contract_id=contract_id(strike, expiration),
                expiration=expiration, strike=strike, type='call') | changes


def quote(day='2024-03-05', *, bid=1.9, ask=2., **changes):
    return identity(day, **changes) | {'bid': bid, 'ask': ask}


def reference(day='2024-03-04', close=500., **changes):
    return dict(date=day, close=close, adjustment='raw', source='MASSIVE_GROUPED', currency='USD') | changes


def identities(*rows):
    return pd.DataFrame(list(rows), columns=IDENTITY_COLUMNS)


def references(*rows):
    return pd.DataFrame(list(rows), columns=['date', 'close', 'adjustment', 'source', 'currency'])


def observations(*rows):
    return pd.DataFrame(list(rows)) if rows else pd.DataFrame(columns=IDENTITY_COLUMNS + ['bid', 'ask'])


def select(plan=None, rows=None, refs=None):
    return observed.select_entries(plan or [plan_row()], identities(*(rows or [identity()])),
                                   references(*(refs or [reference()])), VERSION)


def analyse(entry_rows=None, exit_rows=None, *, entries=None, fees=FEES, domain=None):
    entries = select() if entries is None else entries
    rows = (entry_rows if entry_rows is not None else [quote()]) + (
        exit_rows if exit_rows is not None else [quote('2024-03-12', bid=2.5, ask=2.6)])
    return observed.analyse_locked(entries, observations(*rows), fees, domain or dict(DOMAIN))


def test_plan_comes_from_calendar_has_full_denominator_and_keeps_half_days():
    plan, exclusions = observed.make_plan()
    sessions = [day.date().isoformat() for day in calendar().sessions_in_range('2024-01-01', '2024-12-31')]
    expected = [(sessions[i - 1], sessions[i], sessions[i + 5]) for i in range(1, len(sessions) - 5)]
    assert [(row['reference_date'], row['entry_date'], row['exit_date']) for row in plan] == expected
    assert len({row['decision_id'] for row in plan}) == len(plan)
    assert len(exclusions) == len(sessions) - len(plan)
    assert sum(row['plan_weight'] for row in plan) == pytest.approx(1.)
    assert all(row['plan_weight'] == pytest.approx(1. / len(plan)) for row in plan)
    july = next(row for row in plan if row['entry_date'] == '2024-07-03')
    assert july['entry_early_close'] is True
    assert all(day.startswith('2024-') for row in plan for day in
               (row['reference_date'], row['entry_date'], row['exit_date']))


def test_selection_uses_previous_raw_close_not_entry_close_or_exit_observations():
    plan = [plan_row()]
    entry_ids = [identity(strike='500'), identity(strike='510')]
    ref = [reference(close=500.), reference('2024-03-05', close=510.)]
    base = observed.select_entries(plan, identities(*entry_ids), references(*ref), VERSION)
    future = identity('2024-03-12', strike='510')
    changed = observed.select_entries(plan, identities(future, *reversed(entry_ids)), references(*ref), VERSION)
    assert base.iloc[0].selected_contract_id == contract_id('500')
    assert base.iloc[0].reference_close == 500.
    pd.testing.assert_frame_equal(base, changed)
    winning, _ = analyse(entries=base)
    losing, _ = analyse(exit_rows=[quote('2024-03-12', bid=.05, ask=.06)], entries=base)
    missing, _ = analyse(exit_rows=[], entries=base)
    assert [panel.iloc[0].selected_contract_id for panel in (winning, losing, missing)] == [contract_id()] * 3
    pd.testing.assert_frame_equal(base, changed)


def test_expiry_then_strike_rule_ignores_future_chain_and_entry_quote_quality():
    rows = [identity(expiration='2024-04-18'), identity(expiration='2024-04-20'),
            identity(strike='499', expiration='2024-04-19'), identity(strike='501', expiration='2024-04-19')]
    chosen = select(rows=rows)
    # Reuse the original tie rule without defining a second selector.
    expected = expression.choose_atm_contract([
        {'expiry': '2024-04-19', 'call_put': 'CALL', 'strike': float(strike), 'option_code': contract_id(strike)}
        for strike in ('499', '501')], '2024-04-19', 'CALL', 500.)['option_code']
    assert chosen.iloc[0].selected_contract_id == expected
    selected_identity = next(row for row in rows if row['contract_id'] == expected)
    other = next(row for row in rows if row['contract_id'] != expected)
    entries = [selected_identity | {'bid': 100., 'ask': 101.}, other | {'bid': 1., 'ask': 1.1}]
    exits = [selected_identity | {'date': '2024-03-12', 'bid': 200., 'ask': 201.}]
    panel, _ = analyse(entry_rows=entries, exit_rows=exits, entries=chosen)
    assert panel.iloc[0].selected_contract_id == expected
    assert panel.iloc[0].cash_status == 'NOT_OPENED'
    assert 'BUDGET' in panel.iloc[0].cash_reason
    assert pd.isna(panel.iloc[0].conditional_wealth_difference)


@pytest.mark.parametrize('changes', [{'adjustment': 'qfq'}, {'adjustment': 'split_adjusted'},
                                   {'currency': None}, {'currency': 'EUR'}, {'source': ''}])
def test_reference_raw_usd_and_source_are_required(changes):
    entries = select(refs=[reference(**changes)])
    assert entries.iloc[0].selection_status != 'SELECTED'
    assert pd.isna(entries.iloc[0].selected_contract_id)
    assert entries.iloc[0].selection_reason == 'REF_NOT_RAW_USD'


def test_entry_close_does_not_fill_a_missing_previous_session_reference():
    entries = observed.select_entries([plan_row()], identities(identity()),
                                      references(reference('2024-03-05')), VERSION)
    assert entries.iloc[0].selection_status == 'NOT_SELECTED'
    assert entries.iloc[0].selection_reason == 'REFERENCE_MISSING'
    assert pd.isna(entries.iloc[0].selected_contract_id)


def test_missing_chain_and_exit_keep_original_rows_weights_and_unresolved_position():
    plan = [plan_row(plan_weight=.5), plan_row(decision_id='INVENTED:2024-03-06',
        reference_date='2024-03-05', entry_date='2024-03-06', exit_date='2024-03-13', plan_weight=.5)]
    entries = observed.select_entries(plan, identities(identity()),
        references(reference(), reference('2024-03-05')), VERSION)
    panel, _ = analyse(exit_rows=[], entries=entries)
    assert len(entries) == len(panel) == 2
    assert panel.decision_id.tolist() == [row['decision_id'] for row in plan]
    assert panel.plan_weight.tolist() == [.5, .5]
    assert panel.q.isna().all() and panel.conditional_wealth_difference.isna().all()
    funded = panel.iloc[0]
    assert funded.cash_status == 'UNRESOLVED'
    assert funded.conditional_position_quantity == 1
    assert funded.conditional_cash == pytest.approx(9789.)
    assert entries.iloc[1].selection_status != 'SELECTED'


@pytest.mark.parametrize('side', ['entry', 'exit'])
def test_half_day_retains_plan_but_does_not_invent_snapshot_clock(side):
    plan = [plan_row(**{side + '_early_close': True})]
    locked = select(plan=plan)
    panel, _ = analyse(entries=locked)
    assert len(panel) == 1 and panel.iloc[0].plan_weight == 1.
    assert panel.iloc[0].q_status == 'TIME_AMBIGUOUS'
    assert panel.iloc[0].cash_reason == 'TIME_AMBIGUOUS'
    assert pd.isna(panel.iloc[0].q) and pd.isna(panel.iloc[0].conditional_wealth_difference)


def test_nontrading_source_date_is_not_moved_to_the_planned_entry():
    entries = select(rows=[identity('2024-03-03')])
    assert entries.iloc[0].selection_status != 'SELECTED'
    assert pd.isna(entries.iloc[0].selected_contract_id)


@pytest.mark.parametrize('bid,expected_q', [(0., -1.), (.05, -.975)])
def test_observed_zero_and_low_bid_have_q_but_no_supported_conditional_amount(bid, expected_q):
    panel, _ = analyse(exit_rows=[quote('2024-03-12', bid=bid, ask=bid + .01)])
    row = panel.iloc[0]
    assert row.q_status == 'CALCULATED' and row.q == pytest.approx(expected_q)
    assert row.cash_status == 'UNRESOLVED' and row.cash_reason
    assert pd.isna(row.conditional_wealth_difference)
    assert row.conditional_position_quantity == 1


def test_missing_bid_is_not_observed_zero_or_a_loss_label():
    panel, _ = analyse(exit_rows=[quote('2024-03-12', bid=None, ask=2.6)])
    row = panel.iloc[0]
    assert row.q_status != 'CALCULATED' and pd.isna(row.q)
    assert pd.isna(row.conditional_wealth_difference)
    assert row.cash_status == 'UNRESOLVED' and row.conditional_position_quantity == 1


def test_non_grid_actual_quotes_preserve_amount_and_grid_margin_can_have_opposite_sign():
    panel, _ = analyse(entry_rows=[quote(bid=1.995, ask=2.005)],
                       exit_rows=[quote('2024-03-12', bid=2.229, ask=2.239)])
    row = panel.iloc[0]
    assert row.q == pytest.approx(2.229 / 2.005 - 1.)
    assert row.B_min_cash == pytest.approx(2.23)
    assert row.margin_quote == pytest.approx(-.001)
    assert row.cash_status == 'CLOSED'
    assert row.conditional_wealth_difference == pytest.approx(.4, abs=1e-8)
    assert row.conditional_cash == pytest.approx(10000.4)
    assert row.conditional_position_quantity == 0


@pytest.mark.parametrize('entry_changes', [{'ask': 0., 'bid': 0.}, {'ask': None},
                                         {'ask': float('nan')}, {'ask': 2., 'bid': 2.1}])
def test_invalid_entry_quote_cannot_be_replaced_by_a_second_contract(entry_changes):
    entries = select(rows=[identity(), identity(strike='501')])
    bad = quote() | entry_changes
    panel, _ = analyse(entry_rows=[bad, quote(strike='501')], entries=entries)
    row = panel.iloc[0]
    assert row.selected_contract_id == contract_id()
    assert row.q_status != 'CALCULATED' and pd.isna(row.q)
    assert row.cash_status != 'CLOSED' and pd.isna(row.conditional_wealth_difference)


@pytest.mark.parametrize('changes', [
    {'contract_id': None},
    {'contract_id': contract_id(root='SPY1')},
    {'contract_id': contract_id(right='P')},
    {'contract_id': contract_id(expiration='2024-04-18')},
    {'contract_id': contract_id(strike='501')},
    {'strike': '500.00000001'},
])
def test_inconsistent_or_null_entry_identity_is_not_a_contract(changes):
    entries = select(rows=[identity(**changes)])
    assert entries.iloc[0].selection_status != 'SELECTED'
    assert pd.isna(entries.iloc[0].selected_contract_id)


def test_adjusted_root_suffix_exit_is_not_joined_to_standard_entry():
    panel, _ = analyse(exit_rows=[quote('2024-03-12', contract_id=contract_id(root='SPY1'), bid=20., ask=21.)])
    row = panel.iloc[0]
    assert row.selected_contract_id == contract_id()
    assert row.q_status != 'CALCULATED' and pd.isna(row.q)
    assert row.cash_status == 'UNRESOLVED' and row.conditional_position_quantity == 1


def test_duplicate_conflicting_exit_quotes_are_never_last_wins():
    exits = [quote('2024-03-12', bid=2.5, ask=2.6), quote('2024-03-12', bid=25., ask=26.)]
    first, _ = analyse(exit_rows=exits)
    reverse, _ = analyse(exit_rows=list(reversed(exits)))
    for panel in (first, reverse):
        row = panel.iloc[0]
        assert row.q_status != 'CALCULATED' and pd.isna(row.q)
        assert row.cash_status == 'UNRESOLVED' and row.conditional_position_quantity == 1
    assert first.iloc[0].cash_reason == reverse.iloc[0].cash_reason


def test_known_post_entry_rights_change_preserves_position_and_unknown_terminal_amount():
    panel, _ = analyse(entry_rows=[quote(multiplier=100, deliverable='100_UNDERLYING_SHARES', adjustment_status='STANDARD')],
        exit_rows=[quote('2024-03-12', bid=2.5, ask=2.6, multiplier=10,
                         deliverable='CASH_AND_SHARES', adjustment_status='ADJUSTED')])
    row = panel.iloc[0]
    assert row.selected_contract_id == contract_id()
    assert row.cash_status == 'UNRESOLVED'
    assert row.conditional_position_quantity == 1 and pd.isna(row.conditional_wealth_difference)


def test_missing_size_and_delta_do_not_block_documented_snapshot_description():
    panel, _ = analyse()
    row = panel.iloc[0]
    assert row.q_status == 'CALCULATED' and row.cash_status == 'CLOSED'
    assert row.q == pytest.approx(.25)
    assert row.conditional_wealth_difference == pytest.approx(28.)


def test_summary_keeps_calendar_denominator_and_unidentified_weight():
    plan = [plan_row(plan_weight=.5), plan_row(decision_id='INVENTED:2024-03-06',
        reference_date='2024-03-05', entry_date='2024-03-06', exit_date='2024-03-13', plan_weight=.5)]
    entries = observed.select_entries(plan, identities(identity()),
        references(reference(), reference('2024-03-05')), VERSION)
    panel, _ = analyse(exit_rows=[quote('2024-03-12', bid=2.1, ask=2.2)], entries=entries)
    summary = observed.summarize(panel)
    assert summary['planned'] == 2 and summary['selected'] == 1
    assert summary['decision_days'] == 2 and summary['months'] == 1
    assert summary['q']['count'] == summary['cash']['count'] == 1
    assert summary['q']['mean'] == summary['q']['median'] == pytest.approx(.05)
    assert summary['cash']['mean'] == summary['cash']['median'] == pytest.approx(-12.)
    assert summary['q']['coverage'] == summary['cash']['coverage'] == pytest.approx(.5)
    assert summary['q']['unidentified_weight'] == summary['cash']['unidentified_weight'] == pytest.approx(.5)
    assert summary['q_positive_cash_negative'] == 1
    assert summary['frontier_count'] == 1


def test_analysis_does_not_mutate_locked_entries_or_observations():
    entries = select()
    rows = observations(quote(), quote('2024-03-12', bid=2.5, ask=2.6))
    before_entries, before_rows = entries.copy(deep=True), rows.copy(deep=True)
    panel, calls = observed.analyse_locked(entries, rows, FEES, dict(DOMAIN))
    pd.testing.assert_frame_equal(entries, before_entries)
    pd.testing.assert_frame_equal(rows, before_rows)
    assert len(panel) == 1 and isinstance(calls, dict)
    for name in ('entry_at', 'exit_at', 'available_at', 'bid_size', 'ask_size'):
        if name in panel:
            assert panel[name].isna().all()
    if 'source_authorized' in panel:
        assert not panel['source_authorized'].eq(True).any()


def reference_binding(tmp_path, **changes):
    return dict(projection_dates=['2024-01-01', '2024-12-31'],
        columns=['ticker', 'date', 'close', 'adjustment', 'source', 'currency'],
        path=str(tmp_path / 'invented-bound-reference.parquet'), source_sha256='a' * 64) | changes


@pytest.mark.parametrize('dates', [['2024-01-01', '2026-01-01'], ['2026-01-01', '2026-01-02']])
def test_reference_2026_projection_rejected_before_reader_construction(tmp_path, monkeypatch, dates):
    calls = []
    def forbidden_store(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail('A non-2024 projection must reject before touching DataStore or its catalog')
    monkeypatch.setattr(observed, 'DataStore', forbidden_store)
    with pytest.raises(Invalid, match='REFERENCE_PROJECTION_OUTSIDE_2024'):
        observed.read_references(reference_binding(tmp_path, projection_dates=dates))
    assert calls == []


def test_reference_reader_gets_exact_bound_provider_dates_and_six_columns(tmp_path, monkeypatch):
    binding = reference_binding(tmp_path)
    expected = references(reference(), reference('2024-03-05'))
    expected.insert(0, 'ticker', 'SPY')
    events = []
    class FakeStore:
        def __init__(self):
            events.append(('construct',))
        def metadata(self, dataset, ticker, adjustment):
            events.append(('metadata', dataset, ticker, adjustment))
            return {'path': binding['path'], 'source_sha256': binding['source_sha256'],
                    'lineage': {'price_basis': 'RAW', 'currency': 'USD'}}
        def daily(self, ticker, adjustment, start, end, *, columns, provider):
            events.append(('daily', ticker, adjustment, start, end, list(columns), provider))
            return expected.copy(deep=True)
    monkeypatch.setattr(observed, 'DataStore', FakeStore)
    actual = observed.read_references(binding)
    assert events == [('construct',), ('metadata', 'prices_daily_massive', 'SPY', 'raw'),
        ('daily', 'SPY', 'raw', '2024-01-01', '2024-12-31', binding['columns'], 'massive')]
    pd.testing.assert_frame_equal(actual, expected)
    assert not (tmp_path / 'invented-bound-reference.parquet').exists()


@pytest.mark.parametrize('bad_date', ['2025-01-02', '2026-01-02'])
def test_scope_rejects_outside_year_row_instead_of_filtering_it_away(bad_date):
    source = observations(quote(), quote(bad_date))
    before = source.copy(deep=True)
    with pytest.raises(Invalid, match='OBSERVATION_OUTSIDE_2024'):
        observed._scope(source)
    pd.testing.assert_frame_equal(source, before)


def test_reference_reader_rejects_returned_2026_row_even_with_legal_requested_bounds(tmp_path, monkeypatch):
    binding = reference_binding(tmp_path)
    class LeakyStore:
        def metadata(self, *args):
            return {'path': binding['path'], 'source_sha256': binding['source_sha256'],
                    'lineage': {'price_basis': 'RAW', 'currency': 'USD'}}
        def daily(self, *args, **kwargs):
            return references(reference(), reference('2026-01-02')).assign(ticker='SPY')
    monkeypatch.setattr(observed, 'DataStore', LeakyStore)
    with pytest.raises(Invalid, match='OBSERVATION_OUTSIDE_2024'):
        observed.read_references(binding)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding='utf-8')
    return observed._file_digest(path)


def addition_binding(tmp_path, rows=None):
    path = tmp_path/'new-reference.json'
    evidence = tmp_path/'qualification.json'
    evidence_sha = write_json(evidence, {'fixture': 'INVENTED_NO_MARKET_SOURCE'})
    rows = [reference(ticker='SPY')] if rows is None else rows
    return dict(path=str(path), sha256=write_json(path, rows), columns=observed.REFERENCE_COLUMNS,
        allowed_reference_dates=['2024-03-04'], qualification=dict(
            status='QUALIFIED_RAW_USD_DAILY_REFERENCE', provider='MASSIVE', adjusted=False, currency='USD',
            date_semantics='Invented NY aggregate start date', session_basis='Invented daily aggregate period',
            evidence=[dict(path=str(evidence), sha256=evidence_sha)]))


def missing_parent():
    return {'entry_lock': {'records': [plan_row(selection_reason='REFERENCE_MISSING')]}}


def test_reference_addition_only_missing_keys_and_preserves_parent_values(tmp_path):
    existing = references(reference('2024-03-05', close=510.)).assign(ticker='SPY')
    before = existing.copy(deep=True)
    result, dates = observed.add_missing_references(existing, addition_binding(tmp_path), missing_parent())
    assert dates == {'2024-03-04'} and len(result) == 2
    pd.testing.assert_frame_equal(result.iloc[:1].reset_index(drop=True), before)


@pytest.mark.parametrize('rows,reason', [
    ([], 'REFERENCE_ADDITIONS_EMPTY_OR_OVERSIZED'),
    ([reference(ticker='SPY'), reference(ticker='SPY')], 'REFERENCE_ADDITIONS_EMPTY_OR_OVERSIZED'),
    ([reference('2024-03-05', ticker='SPY')], 'REFERENCE_ADDITION_KEY_INVALID'),
    ([reference('2026-03-04', ticker='SPY')], 'OBSERVATION_OUTSIDE_2024'),
    ([reference(ticker='QQQ')], 'REFERENCE_ADDITIONS_NOT_RAW_USD'),
    ([reference(ticker='SPY', adjustment='adjusted')], 'REFERENCE_ADDITIONS_NOT_RAW_USD'),
    ([reference(ticker='SPY', currency='CAD')], 'REFERENCE_ADDITIONS_NOT_RAW_USD'),
    ([reference(ticker='SPY', close=0.)], 'REFERENCE_ADDITIONS_NOT_RAW_USD'),
    ([reference(ticker='SPY', bid=1.)], 'REFERENCE_COLUMNS_CHANGED'),
])
def test_reference_additions_reject_empty_out_of_scope_or_unqualified_rows(tmp_path, rows, reason):
    with pytest.raises(Invalid, match=reason):
        observed.add_missing_references(references(), addition_binding(tmp_path, rows), missing_parent())


def test_reference_addition_rejects_replacement_and_changed_evidence(tmp_path):
    binding = addition_binding(tmp_path)
    with pytest.raises(Invalid, match='REFERENCE_ADDITION_OVERWRITES_PARENT'):
        observed.add_missing_references(references(reference()), binding, missing_parent())
    binding['qualification']['evidence'][0]['sha256'] = '0'*64
    with pytest.raises(Invalid, match='REFERENCE_EVIDENCE_CHANGED'):
        observed.add_missing_references(references(), binding, missing_parent())


@pytest.fixture
def invented_continuation(tmp_path, monkeypatch):
    """A complete invented 246-row parent; only 70 old references and two additions."""
    paths = SimpleNamespace(results_root=tmp_path/'results', repo_root=tmp_path/'repo')
    parent_run = paths.results_root/observed.TEMPLATE/'spy2024_observed_frontier'/observed.OBSERVED_PARENT
    output = paths.results_root/observed.TEMPLATE/'spy2024_reference_completion'/'invented'
    parent_run.mkdir(parents=True)
    output.mkdir(parents=True)
    plan, exclusions = observed.make_plan()
    refs = references(*(reference(r['reference_date']) for r in plan[176:])).assign(ticker='SPY')
    source = []
    for row in plan:
        expiry = (pd.Timestamp(row['entry_date']) + pd.Timedelta(days=45)).date().isoformat()
        source.extend([quote(row['entry_date'], expiration=expiry), quote(row['exit_date'], expiration=expiry)])
        if row['reference_date'] == '2024-09-13':
            source.append(quote(row['entry_date'], expiration=expiry, strike='510'))
    source = pd.DataFrame(source).drop_duplicates()
    raw = tmp_path/'invented-options.parquet'
    source.to_parquet(raw, index=False)
    ids = source.loc[source.date.isin([r['entry_date'] for r in plan]), IDENTITY_COLUMNS]
    entries = observed.select_entries(plan, ids, refs, VERSION)
    old_panel, calls = observed.analyse_locked(entries, source, FEES, DOMAIN)
    old_panel.to_csv(parent_run/'observed_frontier.csv', index=False)
    records = [{k: None if pd.isna(v) else v for k, v in r.items()} for r in entries.to_dict('records')]
    entry_raw = json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False)
    public_parent = tmp_path/'invented-public'
    public_sha = write_json(public_parent/'run_manifest.json', {'fixture': True})
    fee_path = tmp_path/'invented-fees.json'
    fee_sha = write_json(fee_path, {'fee_profiles': {'frozen': asdict(FEES)}, 'domain': DOMAIN})
    parent = dict(task_id=observed.TASK, research_identity=observed.TEMPLATE,
        status='COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC', plan=plan, calendar_exclusions=exclusions,
        reference_binding=dict(projection_dates=[plan[0]['reference_date'], plan[-1]['reference_date']],
            columns=observed.REFERENCE_COLUMNS), source_documents=[],
        source_qualification={'grade': 'SOURCE_DOCUMENTED_SNAPSHOT'}, parent_cache=str(tmp_path),
        source_status={'ETF_2024': dict(file=raw.name, sha256=observed._file_digest(raw), commit=VERSION, footer={})},
        parent_run=str(public_parent), parent_manifest_sha256=public_sha,
        fee_parent_config=str(fee_path), fee_parent_sha256=fee_sha, fee_profile='frozen', fees=asdict(FEES),
        domain=DOMAIN, specification={'fixture': 'INVENTED'},
        entry_lock=dict(records=records, sha256=hashlib.sha256(entry_raw.encode()).hexdigest()),
        result_sha256=observed._file_digest(parent_run/'observed_frontier.csv'),
        summary=observed.summarize(old_panel))
    parent_sha = write_json(parent_run/'run_manifest.json', parent)
    additions = addition_binding(tmp_path, [reference(r['reference_date'], ticker='SPY') for r in plan[:2]])
    additions['allowed_reference_dates'] = [r['reference_date'] for r in plan[:176]]
    overlap_path = tmp_path/'invented-overlap.json'
    overlap_sha = write_json(overlap_path, [dict(date=d, old_close=500., fetched_close=None,
        difference=None, equal_at_frozen_tolerance=None, old_reference_replaced=False)
        for d in ['2024-09-13', '2024-09-16', '2024-09-17']])
    additions['qualification'].update(overlap_evidence=str(overlap_path), overlap_evidence_sha256=overlap_sha)
    manifest = copy.deepcopy(parent)
    manifest.update(task_id=observed.CONTINUATION_TASK, status='FROZEN_BEFORE_ENTRY_SELECTION',
        observed_parent=dict(run=str(parent_run), manifest_sha256=parent_sha), reference_additions=additions)
    write_json(output/'run_manifest.json', manifest)
    monkeypatch.setattr(observed, 'resolve', lambda: paths)
    monkeypatch.setattr(observed, 'read_references', lambda binding: refs.copy(deep=True))
    monkeypatch.setattr(observed, 'inspect_parquet', lambda *a, **kw: (None, {}))
    for name in ['spy_observed_frontier.py', 'frontier.py', 'expression.py', 'cli.py', 'contracts.py', 'contract_continuity.py']:
        path = paths.repo_root/'scripts/research/a2/options'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# invented source binding', encoding='utf-8')
    for name in ['scripts/storage/storage_r2a.py', 'scripts/v22/r9a_trade_ledger.py']:
        path = paths.repo_root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# invented source binding', encoding='utf-8')
    return SimpleNamespace(output=output, parent_run=parent_run, parent=parent, manifest=manifest)


def test_continuation_full_plan_parent_reconciliation_groups_and_offline(invented_continuation):
    fixture = invented_continuation
    result = observed.run_observed(fixture.output)
    assert result['summary']['planned'] == 246 and result['summary']['selected'] == 72
    continuation = result['continuation']
    assert continuation['parent_selected_reconciled'] == 70
    assert continuation['parent_q_reconciled'] == continuation['parent_cash_reconciled'] == 67
    assert continuation['parent_frontiers_reconciled'] == 69
    assert continuation['parent_outcomes_identical']
    assert result['calls']['source_observation_analysis_calls'] == 246
    groups = continuation['groups']
    assert [groups[k]['rows'] for k in ('prior_reconciled', 'newly_referenced', 'still_reference_missing')] == [70, 2, 174]
    assert sum(g['original_plan_weight'] for g in groups.values()) == pytest.approx(1.)
    assert groups['newly_referenced']['original_plan_weight'] == pytest.approx(2/246)
    assert groups['prior_reconciled']['summary']['decision_days'] == 70
    for name in ('q', 'cash'):
        assert groups['prior_reconciled']['summary'][name]['decision_days'] == 67
        assert groups['prior_reconciled']['summary'][name]['months'] == 4
        assert groups['newly_referenced']['summary'][name]['decision_days'] == 2
        assert result['summary'][name]['decision_days'] == 69
    offline = fixture.output.with_name('invented_offline')
    repeated = observed.run_observed(offline, source_run=fixture.output, offline=True)
    assert repeated['result_sha256'] == result['result_sha256']
    assert repeated['continuation'] == continuation
    assert repeated['cli_network_requests'] == 0
    main_manifest = json.loads((fixture.output/'run_manifest.json').read_bytes())
    offline_manifest = json.loads((offline/'run_manifest.json').read_bytes())
    assert main_manifest['result_root'] == str(fixture.output)
    assert offline_manifest['result_root'] == str(offline)
    assert offline_manifest['offline_source_run'] == str(fixture.output)
    for field in ('parent_cache', 'reference_binding', 'reference_additions', 'observed_parent'):
        assert offline_manifest[field] == main_manifest[field]


def test_continuation_changed_old_selection_rejects_before_option_prices(invented_continuation, monkeypatch):
    fixture = invented_continuation
    original = observed.select_entries
    def changed(*args):
        frame = original(*args)
        frame.loc[frame.reference_date.eq(fixture.parent['plan'][176]['reference_date']), 'reference_close'] += 1
        return frame
    monkeypatch.setattr(observed, 'select_entries', changed)
    monkeypatch.setattr(observed, 'analyse_locked', lambda *a: pytest.fail('Selection conflict must stop before economics'))
    with pytest.raises(Invalid, match='OBSERVED_PARENT_SELECTION_CHANGED'):
        observed.run_observed(fixture.output)
    assert not (fixture.output/'observed_frontier.csv').exists()


def test_continuation_changed_old_outcome_is_not_published(invented_continuation, monkeypatch):
    fixture = invented_continuation
    original = observed.analyse_locked
    def changed(*args):
        panel, calls = original(*args)
        panel.loc[panel.reference_date.eq(fixture.parent['plan'][176]['reference_date']), 'q'] += .001
        return panel, calls
    monkeypatch.setattr(observed, 'analyse_locked', changed)
    with pytest.raises(Invalid, match='OBSERVED_PARENT_RESULT_CHANGED'):
        observed.run_observed(fixture.output)
    assert not (fixture.output/'observed_frontier.csv').exists()


def test_original_task_cannot_use_continuation_root_or_additions(invented_continuation):
    fixture = invented_continuation
    fixture.manifest['task_id'] = observed.TASK
    write_json(fixture.output/'run_manifest.json', fixture.manifest)
    with pytest.raises(Invalid, match='OUTPUT_TASK_BOUNDARY'):
        observed.run_observed(fixture.output)


def test_continuation_rejects_empty_additions_without_old_rerun(invented_continuation, monkeypatch):
    fixture = invented_continuation
    binding = fixture.manifest['reference_additions']
    binding['sha256'] = write_json(Path(binding['path']), [])
    write_json(fixture.output/'run_manifest.json', fixture.manifest)
    monkeypatch.setattr(observed.ds, 'dataset', lambda *a, **kw: pytest.fail('No new input must not read option dataset'))
    with pytest.raises(Invalid, match='REFERENCE_ADDITIONS_EMPTY_OR_OVERSIZED'):
        observed.run_observed(fixture.output)


def test_hidden_entry_fake_http_reaches_real_cli_cash_frontier_and_offline(invented_continuation, monkeypatch, capsys):
    from scripts.research.a2.options import authenticated_reference as authenticated
    fixture = invented_continuation
    missing = [row['reference_date'] for row in fixture.parent['plan'][:176]]
    cache_root = fixture.output.parents[3]/'invented-cache'
    cache = cache_root/fixture.output.name
    frozen = copy.deepcopy(fixture.parent)
    frozen.update(task_id=authenticated.TASK, status='FROZEN_AWAITING_SAFE_LOCAL_CREDENTIAL_INPUT',
        parent_run=str(fixture.parent_run), parent_manifest_sha256=observed._file_digest(fixture.parent_run/'run_manifest.json'),
        completion_parent_manifest_sha256='1'*64, cache=str(cache), http_budget={},
        missing_reference_keys=fixture.parent['plan'][:176], overlap_keys=['2024-09-13', '2024-09-16', '2024-09-17'],
        overlap_rule={'numeric_equal_abs_usd': 0.}, daily_semantics_evidence=dict(
            status=authenticated.SEMANTICS, date_semantics='Invented NY daily start',
            session_basis='Invented whole daily period',
            evidence=fixture.manifest['reference_additions']['qualification']['evidence']))
    write_json(fixture.output/'run_manifest.json', frozen)
    monkeypatch.setattr(authenticated, '_context', lambda output: (frozen, fixture.parent, missing, cache_root, cache))
    monkeypatch.delenv('MASSIVE_API_KEY', raising=False)
    key = 'invented-hidden-key-never-network'
    prompts, http_calls = [], []
    def hidden():
        prompts.append('HIDDEN_INPUT')
        return key
    def fake_http(url, *, params, api_key, headers, timeout, allow_redirects):
        assert url == authenticated.URL and params == authenticated.PARAMS
        assert api_key == key and allow_redirects is False
        http_calls.append('INVENTED_RESPONSE_ONLY')
        dates = missing[:2]+frozen['overlap_keys']
        return 200, dict(ticker='SPY', adjusted=False, status='OK', resultsCount=len(dates),
            queryCount=len(dates), results=[dict(c=500.,
                t=int(pd.Timestamp(day, tz='America/New_York').timestamp()*1000)) for day in dates])
    monkeypatch.setattr(authenticated.cli, '_hidden_massive_key', hidden)
    monkeypatch.setattr(authenticated, '_history_get', fake_http)
    assert authenticated.main(['--output', str(fixture.output), '--prompt-api-key']) == 0
    assert prompts == ['HIDDEN_INPUT'] and http_calls == ['INVENTED_RESPONSE_ONLY']
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(printed) == 3  # Actual economic CLI, actual offline CLI, wrapper receipt.
    assert printed[-1]['daily_http_shared'] == printed[-1]['economic_cli_runs'] == printed[-1]['offline_cli_runs'] == 1
    assert printed[-1]['recovered_reference_keys'] == 2
    manifest = json.loads((fixture.output/'run_manifest.json').read_bytes())
    offline = fixture.output.with_name(fixture.output.name+'_offline')
    repeat = json.loads((offline/'run_manifest.json').read_bytes())
    assert manifest['summary']['planned'] == 246 and manifest['summary']['selected'] == 72
    assert manifest['calls']['source_observation_analysis_calls'] == 246
    assert manifest['calls']['conditional_amount_calls'] > 0 and manifest['calls']['solver_calls'] > 0
    assert manifest['continuation']['parent_selected_reconciled'] == 70
    assert manifest['continuation']['parent_cash_reconciled'] == 67
    assert manifest['continuation']['parent_frontiers_reconciled'] == 69
    assert manifest['result_sha256'] == repeat['result_sha256'] and repeat['offline_content_identical'] is True
    assert manifest['result_root'] == str(fixture.output) and repeat['result_root'] == str(offline)
    assert repeat['offline_source_run'] == str(fixture.output)
    for root in (fixture.output, offline, cache_root):
        assert all(key.encode() not in path.read_bytes() for path in root.rglob('*') if path.is_file())


def test_overlap_diagnostic_can_change_strike_without_changing_actual_parent_selection(invented_continuation):
    fixture = invented_continuation
    qualification = fixture.manifest['reference_additions']['qualification']
    path = Path(qualification['overlap_evidence'])
    overlaps = json.loads(path.read_bytes())
    overlaps[0].update(fetched_close=510., difference=10., equal_at_frozen_tolerance=False)
    qualification['overlap_evidence_sha256'] = write_json(path, overlaps)
    write_json(fixture.output/'run_manifest.json', fixture.manifest)
    result = observed.run_observed(fixture.output)
    manifest = json.loads((fixture.output/'run_manifest.json').read_bytes())
    diagnostic = manifest['overlap_entry_diagnostic']['records'][0]
    assert diagnostic['status'] == 'SELECTION_CHANGED' and diagnostic['changed'] is True
    assert Decimal(diagnostic['parent_strike']) == 500 and Decimal(diagnostic['diagnostic_strike']) == 510
    actual = next(r for r in manifest['entry_lock']['records'] if r['reference_date'] == '2024-09-13')
    assert actual['selected_contract_id'] == diagnostic['parent_contract_id']
    assert Decimal(actual['selected_strike']) == 500 and actual['reference_close'] == 500.
    assert result['continuation']['parent_outcomes_identical'] is True
    assert manifest['overlap_entry_diagnostic']['actual_references_replaced'] is False
    assert [r['status'] for r in manifest['overlap_entry_diagnostic']['records'][1:]] == ['UNAVAILABLE', 'UNAVAILABLE']


@pytest.fixture
def invented_compat(invented_continuation):
    from scripts.research.a2.options import price_basis
    fixture = invented_continuation
    paths = observed.resolve()
    run = paths.results_root/observed.TEMPLATE/'spy2024_complete_compat_train'/'invented'
    run.mkdir(parents=True)
    output, source = run/'observed', run/'reference-source.parquet'
    missing = fixture.manifest['reference_additions']['allowed_reference_dates']
    pd.DataFrame([dict(identity='SPY', market_date=d, source_close=500.) for d in missing[:2]]).to_parquet(source, index=False)
    qualification = fixture.manifest['reference_additions']['qualification'] | dict(
        status=price_basis.STATUS, identity='SPY', provider='INVENTED_RAW', source_version='fixture1',
        source_field='close', source_basis='RAW', currency='USD', session='REGULAR')
    binding = dict(task_id=observed.COMPAT_TASK, observed_parent=fixture.manifest['observed_parent'],
        reference_additions=dict(path=str(source), sha256=observed._file_digest(source),
                                allowed_reference_dates=missing, qualification=qualification))
    override = run/'reference_binding.json'
    write_json(override, binding)
    (paths.repo_root/'scripts/research/a2/options/price_basis.py').write_text('# invented source binding', encoding='utf-8')
    return SimpleNamespace(output=output, override=override, parent_run=fixture.parent_run)


def test_explicit_trade_basis_override_reaches_real_cli_and_offline(invented_compat, capsys):
    from scripts.research.a2.options import cli
    fixture = invented_compat
    output, override = fixture.output, fixture.override
    parent_before = {p.name: p.read_bytes() for p in fixture.parent_run.iterdir() if p.is_file()}
    assert cli.main(['--mode', 'spy2024-observed-frontier', '--output', str(output),
                     '--reference-override', str(override)]) == 0
    result = json.loads((output/'run_manifest.json').read_bytes())
    assert result['summary']['planned'] == 246 and result['summary']['selected'] == 72
    continuation = result['continuation']
    assert continuation['parent_selected_reconciled'] == 70
    assert continuation['parent_cash_reconciled'] == continuation['parent_q_reconciled'] == 67
    assert continuation['parent_frontiers_reconciled'] == 69 and continuation['parent_outcomes_identical']
    offline = output.with_name('observed_offline')
    assert cli.main(['--mode', 'spy2024-observed-frontier', '--output', str(offline),
                     '--source-run', str(output), '--offline']) == 0
    repeated = json.loads((offline/'run_manifest.json').read_bytes())
    assert repeated['result_sha256'] == result['result_sha256'] and repeated['offline_content_identical']
    assert parent_before == {p.name: p.read_bytes() for p in fixture.parent_run.iterdir() if p.is_file()}
    assert repeated['cli_network_requests'] == result['cli_network_requests'] == 0


def test_compat_resumes_locked_entry_checkpoint_without_refreezing(invented_compat, monkeypatch):
    fixture = invented_compat
    original = observed.analyse_locked
    def interrupted(*args, **kwargs):
        raise RuntimeError('invented interruption after entry lock')
    monkeypatch.setattr(observed, 'analyse_locked', interrupted)
    with pytest.raises(RuntimeError, match='invented interruption'):
        observed.run_observed(fixture.output, reference_override=fixture.override)
    checkpoint = json.loads((fixture.output/'run_manifest.json').read_bytes())
    assert checkpoint['status'] == 'ENTRY_LOCKED_BEFORE_OPTION_PRICES'
    assert not (fixture.output/'observed_frontier.csv').exists()
    tampered = copy.deepcopy(checkpoint)
    tampered['entry_lock']['records'][0]['reference_close'] += 1
    write_json(fixture.output/'run_manifest.json', tampered)
    with pytest.raises(Invalid, match='ENTRY_CHECKPOINT_CHANGED'):
        observed.run_observed(fixture.output)
    write_json(fixture.output/'run_manifest.json', checkpoint)
    monkeypatch.setattr(observed, 'analyse_locked', original)
    result = observed.run_observed(fixture.output)
    resumed = json.loads((fixture.output/'run_manifest.json').read_bytes())
    assert result['continuation']['parent_outcomes_identical']
    assert resumed['entry_lock'] == checkpoint['entry_lock']


def test_reference_override_is_never_accepted_by_default_cli(tmp_path, capsys):
    from scripts.research.a2.options import cli
    assert cli.main(['--reference-override', str(tmp_path/'unopened.json')]) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'REFERENCE_OVERRIDE_REQUIRES_OBSERVED'
