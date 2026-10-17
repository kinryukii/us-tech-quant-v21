"""Synthetic metric adapter checks; no files, accounts or market outcomes read."""
from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation.reused_policy_pair_economics import (
    evaluate_reused_account, compare_reused_pair,
)


def fixture(path='SIMPLE'):
    weekdays = pd.bdate_range('2023-01-03', '2025-12-31')
    dates = weekdays[np.linspace(0, len(weekdays)-1, 752).astype(int)]
    nav = np.linspace(2400., 4500., 752)
    daily = pd.DataFrame(dict(path_id=path, date=dates, TOTAL_ECONOMIC_NAV=nav,
        LIQUID_NAV=nav, cash=nav, transaction_cost_amount=np.full(752, .25),
        buy_notional=np.full(752, 10.), sell_notional=np.full(752, 5.),
        turnover=np.full(752, .01), research_gross=np.zeros(752),
        research_cash_weight=np.ones(752), receivable_value_usd=np.zeros(752)))
    fills = pd.DataFrame([dict(path_id=path, signal_date=dates[0], execution_date=dates[1],
                              ticker='SYN', side='BUY', index_units_before=0., index_units_after=1.)])
    orders = pd.DataFrame([dict(path_id=path, signal_date=dates[0], execution_date=dates[1])])
    executions = orders.assign(status='FILLED')
    candidate = dict(candidate_id=path, scientific_tuple_sha256='synthetic-frozen-tuple',
                     execution_friction=dict(one_way_bps=10))
    return candidate, dict(daily=daily, fills=fills, orders=orders, execution_results=executions), dates


def evaluate(candidate, frames, dates, **kwargs):
    return evaluate_reused_account(candidate, frames, expected_sessions=dates,
        account_truth_passed=kwargs.pop('account_truth_passed', True),
        complete=kwargs.pop('complete', True), **kwargs)


def test_complete_annual_returns_and_drawdown_reuse_continuous_owner():
    c, f, d = fixture()
    result = evaluate(c, f, d)
    assert result['status'] == 'COMPLETE_752_DESCRIPTIVE_RESEARCH'
    m = result['economic_metrics']
    assert m['cumulative_return'] == pytest.approx(.5)
    assert m['MaxDD'] == pytest.approx(-.2)
    previous = 3000.
    for year, g in f['daily'].groupby(f['daily'].date.dt.year):
        last = float(g.TOTAL_ECONOMIC_NAV.iloc[-1])
        assert result['yearly'][str(year)]['total_return'] == pytest.approx(last/previous-1)
        assert result['yearly'][str(year)]['actual_cost_usd'] == pytest.approx(len(g)*.25)
        previous = last
    assert set(result['yearly']) == {'2023', '2024', '2025'}
    assert m['cost_drag']['actual_cost_usd'] == pytest.approx(188.)
    assert m['turnover'] == pytest.approx(7.52)
    assert m['action_counts'] is None and m['HOLD_SELL_count'] is None
    assert m['policy_action_semantics'].startswith('UNKNOWN')
    assert m['fill_side_counts'] == {'BUY': 1}
    assert m['order_count'] == 1 and m['no_order_sessions'] == 751
    assert result['certified_NAV'] is False and result['strict_PIT'] is False
    assert result['scientific_winner'] is None


def test_partial_never_reads_economic_columns_or_claims_metrics():
    c, f, d = fixture()
    f['daily'] = f['daily'][['path_id', 'date']].iloc[:100]
    result = evaluate(c, f, d, complete=False, first_failure={'code': 'EXACT_REQUIRED_INPUT_UNAVAILABLE'})
    assert result['economic_metrics'] is None and 'yearly' not in result
    assert result['coverage']['observed_sessions'] == 100
    assert result['first_failure']['code'] == 'EXACT_REQUIRED_INPUT_UNAVAILABLE'


def test_truth_failed_complete_flag_cannot_admit_economic_read():
    c, f, d = fixture()
    f['daily'] = f['daily'][['path_id', 'date']]
    result = evaluate(c, f, d, account_truth_passed=False)
    assert result['economic_metrics'] is None
    assert result['status'] == 'PARTIAL_OR_UNQUALIFIED_COVERAGE_ONLY'


def test_complete_requires_every_frozen_session_not_merely_both_endpoints():
    c, f, d = fixture(); f['daily'] = f['daily'].drop(index=100)
    with pytest.raises(ValueError, match='COMPLETE_CALENDAR_MISMATCH'):
        evaluate(c, f, d)


@pytest.mark.parametrize('column,value', [('TOTAL_ECONOMIC_NAV', np.nan),
    ('LIQUID_NAV', -1), ('turnover', np.inf), ('transaction_cost_amount', -1)])
def test_invalid_economic_values_fail_before_owner(column, value):
    c, f, d = fixture(); f['daily'].loc[100, column] = value
    with pytest.raises(ValueError, match='NONFINITE_OR_NEGATIVE'):
        evaluate(c, f, d)


def test_duplicate_and_future_dates_rejected_even_on_partial():
    c, f, d = fixture(); f['daily'].loc[1, 'date'] = d[0]
    with pytest.raises(ValueError, match='DAILY_KEYS_INVALID'):
        evaluate(c, f, d, complete=False)
    f['daily'].loc[1, 'date'] = pd.Timestamp('2026-01-02')
    with pytest.raises(ValueError, match='PRE2026_ONLY'):
        evaluate(c, f, d, complete=False)


def test_frozen_calendar_cannot_be_shortened_or_renamed_complete():
    c, f, d = fixture()
    with pytest.raises(ValueError, match='FROZEN_752_CALENDAR_REQUIRED'):
        evaluate(c, f, d[:-1])


def test_full_with_failure_is_contradictory():
    c, f, d = fixture()
    with pytest.raises(ValueError, match='COMPLETE_WITH_FIRST_FAILURE'):
        evaluate(c, f, d, first_failure={'code': 'X'})


def test_no_order_is_not_fabricated_hold_or_skip():
    c, f, d = fixture(); f['orders'] = pd.DataFrame(); f['fills'] = pd.DataFrame()
    result = evaluate(c, f, d)
    m = result['economic_metrics']
    assert m['order_count'] == 0 and m['trade_count'] == 0
    assert m['no_order_sessions'] == 752
    assert m['BUY_SKIP_count'] is None and m['HOLD_SELL_count'] is None


def test_pair_reports_only_complete_exact_interval_descriptive_differences():
    c, f, d = fixture(); simple = evaluate(c, f, d)
    c2, f2, d2 = fixture('JOINT'); f2['daily']['TOTAL_ECONOMIC_NAV'] *= 1.1
    f2['daily']['LIQUID_NAV'] *= 1.1
    joint = evaluate(c2, f2, d2)
    pair = compare_reused_pair(simple, joint)
    assert pair['status'] == 'MATCHED_COMPLETE_DESCRIPTIVE_DIFFERENCES'
    assert pair['differences']['cumulative_return'] == pytest.approx(.15)
    assert pair['differences']['actual_cost_usd'] == pytest.approx(0)
    assert pair['scientific_winner'] is None
    partial = evaluate(c2, f2, d2, complete=False)
    blocked = compare_reused_pair(simple, partial)
    assert blocked['differences'] is None
    changed = deepcopy(joint); changed['coverage']['expected_session_sha256'] = 'different'
    with pytest.raises(ValueError, match='INTERVAL_OR_CAPITAL_MISMATCH'):
        compare_reused_pair(simple, changed)


def test_position_coverage_and_next_open_constraints_are_not_invented():
    c, f, d = fixture(); f['fills'].loc[0, 'signal_date'] = d[1]
    with pytest.raises(ValueError, match='NEXT_OPEN_REQUIRED'):
        evaluate(c, f, d)


def test_concentration_uses_raw_outcome_position_values_without_mutating_engine_ledger():
    c, f, d = fixture()
    f['positions'] = pd.DataFrame([
        dict(path_id='SIMPLE', date=d[0], ticker='SYN_A', index_units=2.,
             market_value=9999., research_raw_market_value=600., holding_age=1),
        dict(path_id='SIMPLE', date=d[0], ticker='SYN_B', index_units=1.,
             market_value=8888., research_raw_market_value=300., holding_age=1),
    ])
    result = evaluate(c, f, d)
    metrics = result['economic_metrics']
    assert metrics['max_single_name_realized_weight'] == pytest.approx(.25)
    assert metrics['concentration_HHI_distribution']['max'] == pytest.approx(.25**2 + .125**2)
    assert f['positions'].market_value.tolist() == [9999., 8888.]


def test_nonempty_positions_cannot_use_engine_mark_as_raw_outcome_coordinate():
    c, f, d = fixture()
    f['positions'] = pd.DataFrame([dict(path_id='SIMPLE', date=d[0], ticker='SYN',
        index_units=1., market_value=100., holding_age=1)])
    with pytest.raises(ValueError, match='RAW_POSITION_VALUE_REQUIRED'):
        evaluate(c, f, d)


def test_orders_use_signal_clock_and_preserve_final_no_next_session_rows():
    c, f, d = fixture()
    f['orders'] = pd.concat([f['orders'], pd.DataFrame([
        dict(path_id='SIMPLE', signal_date=d[-1], execution_date=pd.NaT,
             status='no_next_session')])], ignore_index=True)
    result = evaluate(c, f, d)
    assert result['economic_metrics']['order_count'] == 2
    assert result['economic_metrics']['terminal_unexecuted_order_count'] == 1
    assert result['economic_metrics']['no_order_sessions'] == 750
    assert result['yearly']['2023']['order_count'] == 1
    assert result['yearly']['2025']['order_count'] == 1
    assert result['economic_metrics']['trade_count'] == 1
    assert result['economic_metrics']['cost_drag']['actual_cost_usd'] == pytest.approx(188.)
    assert pd.isna(f['orders'].execution_date.iloc[-1])


@pytest.mark.parametrize('day,status', [(0, 'no_next_session'), (-1, 'FILLED')])
def test_missing_order_execution_clock_rejects_nonterminal_or_filled_order(day, status):
    c, f, d = fixture()
    f['orders'] = pd.DataFrame([dict(path_id='SIMPLE', signal_date=d[day],
                                   execution_date=pd.NaT, status=status)])
    with pytest.raises(ValueError, match='UNBOUND_ORDER_EXECUTION_CLOCK'):
        evaluate(c, f, d)


def test_missing_actual_execution_clock_is_never_filled_from_signal_date():
    c, f, d = fixture()
    f['execution_results'].loc[0, 'execution_date'] = pd.NaT
    with pytest.raises(ValueError, match='SESSION_LABEL_INVALID'):
        evaluate(c, f, d)
