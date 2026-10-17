"""Pure descriptive adapter around the existing continuous-account metric owner.

No account execution, source reads, estimator fitting or winner selection occurs
here. Complete, account-truth-qualified frozen sessions are required before any
NAV or economic column is consumed. Partial paths expose coverage only.
"""
from collections.abc import Mapping
import hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.training.stateful_final_action import _full_metrics
from scripts.research.a2.training.stateful_research_account import _distribution

FLAGS = dict(strict_PIT=False, production_qualified=False, quote_qualified=False,
             certified_NAV=False, new_training=0,
             scope='EXPOSED_PRE2026_FROZEN_HISTORY_MECHANISM_RESEARCH',
             scientific_winner=None, selection_performed=False)
DAILY = ('TOTAL_ECONOMIC_NAV', 'LIQUID_NAV', 'cash', 'transaction_cost_amount',
         'buy_notional', 'sell_notional', 'turnover', 'research_gross',
         'research_cash_weight', 'receivable_value_usd')
EMPTY = dict(positions=('path_id', 'date', 'ticker', 'index_units', 'market_value', 'holding_age'),
             fills=('path_id', 'signal_date', 'execution_date', 'ticker', 'side',
                    'index_units_before', 'index_units_after'),
             actions=('path_id', 'signal_date', 'policy_action'))


def _need(condition, reason):
    if not condition:
        raise ValueError(reason)


def _dates(values):
    dates = pd.DatetimeIndex(pd.to_datetime(values))
    _need(not dates.hasnans and dates.tz is None and dates.equals(dates.normalize()),
          'REUSED_ECONOMIC_SESSION_LABEL_INVALID')
    _need(((dates >= '2023-01-01') & (dates < '2026-01-01')).all(),
          'REUSED_ECONOMIC_PRE2026_ONLY')
    return dates


def _table(frames, name, path_id, required=()):
    frame = frames.get(name, pd.DataFrame())
    _need(isinstance(frame, pd.DataFrame), 'REUSED_ECONOMIC_FRAME_REQUIRED:' + name)
    if frame.empty:
        return pd.DataFrame(columns=tuple(dict.fromkeys(('path_id', *required, *frame.columns))))
    _need('path_id' in frame, 'REUSED_ECONOMIC_PATH_COLUMN_MISSING:' + name)
    local = frame.loc[frame.path_id.eq(path_id)].copy()
    _need(set(required).issubset(local), 'REUSED_ECONOMIC_SCHEMA_MISSING:' + name)
    return local


def _numeric(frame, columns, name):
    for column in columns:
        values = frame[column].to_numpy(float)
        _need(np.isfinite(values).all() and np.all(values >= 0),
              'REUSED_ECONOMIC_NONFINITE_OR_NEGATIVE:' + name + '.' + column)


def _session_counts(frame, dates, label):
    if frame.empty:
        return pd.Series(0, index=dates, dtype=int)
    # Orders exist at their signal clock, including the final unexecuted orders.
    # Fills and execution results exist only at their actual execution clock.
    column = 'signal_date' if label == 'orders' else (
        'execution_date' if 'execution_date' in frame else 'signal_date')
    _need(column in frame, 'REUSED_ECONOMIC_ACTION_CLOCK_MISSING:' + label)
    clock = _dates(frame[column])
    if label == 'orders' and 'execution_date' in frame:
        missing = frame.execution_date.isna().to_numpy()
        if missing.any():
            _need('status' in frame and frame.loc[missing, 'status'].eq('no_next_session').all()
                  and (clock[missing] == dates[-1]).all(),
                  'REUSED_ECONOMIC_UNBOUND_ORDER_EXECUTION_CLOCK')
        execution = _dates(frame.loc[~missing, 'execution_date'])
        _need(execution.isin(dates).all() and (execution > clock[~missing]).all(),
              'REUSED_ECONOMIC_ORDER_EXECUTION_CLOCK_INVALID')
    _need(clock.isin(dates).all(), 'REUSED_ECONOMIC_ACTION_OUTSIDE_SESSIONS:' + label)
    return pd.Series(1, index=clock).groupby(level=0).sum().reindex(dates, fill_value=0)


def evaluate_reused_account(candidate, frames, *, expected_sessions,
                            account_truth_passed, complete, first_failure=None):
    """Adapt qualified standard account frames; initial capital is the fixed USD 3000.

    The caller owns account-truth checks and physical source binding. No partial
    return, cost or relative winner is produced, including when NAV is available.
    Missing policy-action semantics stay UNKNOWN rather than guessed from trades.
    """
    _need(isinstance(candidate, Mapping), 'REUSED_ECONOMIC_CANDIDATE_REQUIRED')
    path_id = candidate['candidate_id']
    expected = _dates(expected_sessions)
    _need(len(expected) == 752 and not expected.has_duplicates
          and expected.is_monotonic_increasing
          and str(expected[0].date()) == '2023-01-03'
          and str(expected[-1].date()) == '2025-12-31',
          'REUSED_ECONOMIC_FROZEN_752_CALENDAR_REQUIRED')
    daily = _table(frames, 'daily', path_id, ('date',))
    observed = _dates(daily.date)
    _need(not observed.has_duplicates and observed.isin(expected).all(),
          'REUSED_ECONOMIC_DAILY_KEYS_INVALID')
    date_sha = hashlib.sha256(('\n'.join(map(lambda x: str(x.date()), expected)) + '\n').encode()).hexdigest()
    coverage = dict(expected_sessions=752, observed_sessions=len(observed),
                    missing_sessions=752-len(observed),
                    first_session=str(observed.min().date()) if len(observed) else None,
                    last_session=str(observed.max().date()) if len(observed) else None,
                    expected_session_sha256=date_sha)
    result = dict(path_id=path_id, coverage=coverage, first_failure=first_failure,
                  account_truth_passed=account_truth_passed is True, **FLAGS)
    if complete is not True or account_truth_passed is not True:
        result.update(status='PARTIAL_OR_UNQUALIFIED_COVERAGE_ONLY', economic_metrics=None)
        return result
    daily = daily.sort_values('date', kind='stable')
    _need(_dates(daily.date).equals(expected), 'REUSED_ECONOMIC_COMPLETE_CALENDAR_MISMATCH')
    _need(first_failure is None, 'REUSED_ECONOMIC_COMPLETE_WITH_FIRST_FAILURE')
    _need(set(DAILY).issubset(daily), 'REUSED_ECONOMIC_SCHEMA_MISSING:daily')
    _numeric(daily, DAILY, 'daily')
    _need(daily.TOTAL_ECONOMIC_NAV.gt(0).all(), 'REUSED_ECONOMIC_NAV_MUST_BE_POSITIVE')
    daily['date'] = _dates(daily.date)
    local = dict(daily=daily)
    for name, columns in EMPTY.items():
        local[name] = _table(frames, name, path_id, columns[1:])
    positions, fills = local['positions'], local['fills']
    for frame, name, clock in ((positions, 'positions', 'date'), (fills, 'fills', 'execution_date')):
        if not frame.empty:
            frame[clock] = _dates(frame[clock])
            _need(frame[clock].isin(expected).all(), 'REUSED_ECONOMIC_ROWS_OUTSIDE_SESSIONS:' + name)
    if not positions.empty:
        _need('research_raw_market_value' in positions,
              'REUSED_ECONOMIC_RAW_POSITION_VALUE_REQUIRED')
        _numeric(positions, ('research_raw_market_value',), 'positions')
        # Only a private metrics view uses independently observed exact raw Close.
        # Engine marks/ledger values remain unchanged for decision/account custody.
        positions['market_value'] = positions.research_raw_market_value
    _numeric(positions, ('index_units', 'market_value', 'holding_age'), 'positions')
    _numeric(fills, ('index_units_before', 'index_units_after'), 'fills')
    _need(not positions.duplicated(['date', 'ticker']).any(), 'REUSED_ECONOMIC_DUPLICATE_POSITION')
    _need(fills.side.isin(('BUY', 'SELL')).all(), 'REUSED_ECONOMIC_UNKNOWN_FILL_SIDE')
    if not fills.empty:
        fills['signal_date'] = _dates(fills.signal_date)
        _need((fills.signal_date < fills.execution_date).all(), 'REUSED_ECONOMIC_NEXT_OPEN_REQUIRED')
    for name in ('entitlements', 'learned_action_decisions'):
        if name in frames:
            local[name] = _table(frames, name, path_id)
    # Keep the existing owner's returns, drawdown, cost and holding calculations.
    metrics = _full_metrics(candidate, local)
    action_semantics = 'actions' in frames and 'policy_action' in frames['actions']
    if not action_semantics:
        metrics.update(action_counts=None, BUY_SKIP_count=None, HOLD_SELL_count=None,
                       policy_action_semantics='UNKNOWN_NOT_EMITTED_BY_PAIR_POLICY',
                       learned_decision_counts=None, learned_kind_counts=None,
                       REPLACE_count=None, REPLACE_identification='UNKNOWN_NO_PAIRED_DECISION_ID')
    else:
        metrics['policy_action_semantics'] = 'EXPLICIT_CALLER_SUPPLIED_ACTION_ROWS'
    orders = _table(frames, 'orders', path_id)
    results = _table(frames, 'execution_results', path_id)
    order_counts = _session_counts(orders, expected, 'orders')
    fill_counts = _session_counts(fills, expected, 'fills')
    execution_counts = _session_counts(results, expected, 'execution_results')
    metrics.update(order_count=len(orders), order_session_clock='SIGNAL_DATE',
                   execution_session_clock='ACTUAL_EXECUTION_DATE',
                   terminal_unexecuted_order_count=(int(orders.execution_date.isna().sum())
                       if 'execution_date' in orders else 0),
                   execution_result_count=len(results),
                   fill_side_counts={str(k): int(v) for k, v in fills.side.value_counts().items()},
                   execution_status_counts=({str(k): int(v) for k, v in results.status.value_counts().items()}
                                            if 'status' in results else {}),
                   no_order_sessions=int(order_counts.eq(0).sum()),
                   no_order_meaning='NO_ORDER_OBSERVED_IS_NOT_A_HOLD_DECISION',
                   orders_per_session=_distribution(order_counts),
                   fills_per_session=_distribution(fill_counts))
    yearly = {}
    for year, group in daily.groupby(daily.date.dt.year, sort=True):
        dates = _dates(group.date)
        yearly[str(year)] = dict(sessions=len(group),
            total_return=metrics['annual_return'][str(year)],
            max_drawdown=metrics['annual_MaxDD'][str(year)],
            actual_cost_usd=float(group.transaction_cost_amount.sum()),
            turnover=float(group.turnover.sum()),
            gross_distribution=_distribution(group.research_gross),
            cash_distribution=_distribution(group.research_cash_weight),
            order_count=int(order_counts.reindex(dates).sum()),
            fill_count=int(fill_counts.reindex(dates).sum()),
            execution_result_count=int(execution_counts.reindex(dates).sum()))
    result.update(status='COMPLETE_752_DESCRIPTIVE_RESEARCH', economic_metrics=metrics,
                  yearly=yearly, initial_capital=3000., annual_reset=False)
    return result


def compare_reused_pair(simple, joint):
    """Descriptive differences only for exact same complete frozen interval."""
    result = dict(simple_path_id=simple['path_id'], joint_path_id=joint['path_id'], **FLAGS)
    complete = 'COMPLETE_752_DESCRIPTIVE_RESEARCH'
    if simple.get('status') != complete or joint.get('status') != complete:
        result.update(status='PAIR_NOT_ECONOMICALLY_COMPARABLE', differences=None)
        return result
    _need(simple['coverage']['expected_session_sha256'] == joint['coverage']['expected_session_sha256']
          and simple['initial_capital'] == joint['initial_capital'], 'REUSED_PAIR_INTERVAL_OR_CAPITAL_MISMATCH')
    a, b = simple['economic_metrics'], joint['economic_metrics']
    differences = dict(cumulative_return=b['cumulative_return']-a['cumulative_return'],
        max_drawdown=b['MaxDD']-a['MaxDD'], turnover=b['turnover']-a['turnover'],
        actual_cost_usd=b['cost_drag']['actual_cost_usd']-a['cost_drag']['actual_cost_usd'],
        fill_count=b['trade_count']-a['trade_count'], order_count=b['order_count']-a['order_count'])
    yearly = {year: {key: joint['yearly'][year][key]-simple['yearly'][year][key]
                      for key in ('total_return', 'max_drawdown', 'actual_cost_usd', 'turnover', 'order_count', 'fill_count')}
              for year in ('2023', '2024', '2025')}
    result.update(status='MATCHED_COMPLETE_DESCRIPTIVE_DIFFERENCES',
                  difference_coordinate='JOINT_MINUS_SIMPLE', differences=differences, yearly_differences=yearly,
                  inference='NO_INFERENTIAL_WINNER_OR_PRODUCTION_PROMOTION')
    return result
