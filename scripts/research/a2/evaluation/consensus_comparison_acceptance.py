"""Read-only R12 acceptance over pinned existing owner ledgers; no replay or fitting.

The frozen master owns ranking and sensitivities. E owns annual statistics; the
cash owner owns fees/calendars/settlement. All observed performance is development.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import io
from datetime import date, datetime
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
from scripts.research.a2.data.joint_input_binding import guard_parquet
from scripts.research.a2.evaluation import consensus_comparison_run as comparison
from scripts.research.a2.evaluation import consensus_evaluation_run as evaluator
from scripts.research.a2.evaluation import consensus_cash_account as cash

MASTER_SHA = '4e4e29a67ba09e0a541d5af93e7128556d4ae894bab5b2230fa38575be9d7332'
SCHEMA = 'CONSENSUS_COMPARISON_ACCEPTANCE_R12'
TERMINAL = {'COMPLETE', 'INPUT_QUALIFICATION_BLOCKED', 'FAILED_NO_RETRY',
            'NOT_TESTABLE', 'BUDGET_EXHAUSTED_NOT_COMPLETED', 'EXACT_ALIAS_REUSED'}
BUDGET_REASONS = ('CUMULATIVE_FIT_BUDGET_EXHAUSTED', 'PHYSICAL_LEARNED_CAP_EXCEEDED',
                  'FIT_BUDGET_EXHAUSTED', 'BUDGET_EXHAUSTED_NOT_COMPLETED',
                  'GLOBAL_FIT_BUDGET_REJECTED', 'PHYSICAL_KIND_CAP_EXCEEDED')
ORDER = ['FULL_ACCOUNT_CERTIFICATION', 'NET_TOTAL_RETURN_DESC', 'MAX_DRAWDOWN_ASC',
         'TOTAL_FEES_ASC', 'COORDINATE_ID_ASC']
CONDITIONS = [dict(fixed_per_fill_usd=0, one_way_all_in_bps=5),
              dict(fixed_per_fill_usd=0, one_way_all_in_bps=25),
              dict(fixed_per_fill_usd=.5, one_way_all_in_bps=10)]
LEDGERS = ('daily', 'fills', 'positions', 'orders', 'execution_results',
           'settlement_ledger', 'entitlements', 'accounting_exceptions', 'diagnostics', 'state')
META_FIELDS = ('account_config', 'fee_config', 'continuous_account', 'annual_reset',
    'unit', 'path_ids', 'max_positions', 'max_target_weight', 'max_target_invested',
    'terminal_liquidation', 'independent_accounts', 'decision_clock', 'execution_clock',
    'consensus_cash_adapter', 'consensus_shareholder_bridge', 'normal_trade_settlement',
    'settlement_semantics', 'available_cash_semantics', 'accounting_exception_count',
    'conditional_shareholder_research_only', 'quote_vintage_status', 'certified_NAV')
require = comparison.require
ref = comparison.ref


class Unqualified(ValueError):
    """A terminal account lacks evidence required for selection."""


def qualify(ok, reason):
    if not ok:
        raise Unqualified(reason)


def _json(value):
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, (datetime, date)) and not isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json(v) for v in value]
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return None if pd.isna(value) else str(pd.Timestamp(value))
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _immutable_json(path, value, kind):
    assert_safe_output_path(path, kind=kind, paths=resolve())
    text = json.dumps(_json(value), sort_keys=True, indent=2, allow_nan=False)+'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_text(encoding='utf8') == text, 'ACCEPTANCE_IMMUTABLE_EXPORT_CHANGED')
    else:
        path.write_text(text, encoding='utf8')
    return ref(path)


def _own_pin(run, reference, expected=None):
    require(isinstance(reference, dict) and set(reference) >= {'path', 'sha256'}, 'EXACT_OWN_RUN_PIN_REQUIRED')
    path = Path(reference['path']).resolve()
    require(path.is_relative_to(run) and (expected is None or path == expected.resolve()),
            'ACCEPTANCE_CROSS_RUN_OR_UNEXPECTED_PATH')
    return comparison.pin(reference)


def _context(run, status_index_ref):
    run = Path(run).resolve()
    assert_safe_output_path(run, kind='backtest', paths=resolve())
    master = ref(run/comparison.SCOPE_FILE)
    require(master['sha256'] == MASTER_SHA, 'EXACT_FROZEN_MASTER_REQUIRED')
    scope = comparison.metadata(master['path'])
    frozen, planned, matrix = comparison.plan(run, scope)
    selection = scope['selection']
    require(selection['all_planned_coordinates_terminal_before_ranking'] is True
        and selection['base_order'] == ORDER and selection['development_only'] is True
        and selection['ineligible_or_missing_is_not_zero_return'] is True
        and selection['no_fusion_preselection'] is True
        and scope['independent_holdout_claim'] is False, 'FROZEN_SELECTION_RULE_REQUIRED')
    sensitivity = scope['sensitivities']
    require(sensitivity['conditions'] == CONDITIONS and sensitivity['maximum_extra_accounts'] == 12
        and sensitivity['all_accounts_restarted_empty'] is True and sensitivity['no_retuning'] is True
        and sensitivity['selection'] == 'TOP_THREE_FULLY_CERTIFIED_BASE_COORDINATES_PLUS_NEUTRAL_IF_CERTIFIED_DEDUPLICATED',
        'FROZEN_SENSITIVITY_PLAN_REQUIRED')
    require(sum(r['exact_alias_of'] is None for r in planned) == 323, 'EXACT323_REPRESENTATIVES_REQUIRED')
    expected = run/'evaluation/consensus_comparison/status_index.json'
    index_ref = status_index_ref or ref(expected)
    index = comparison.metadata(_own_pin(run, index_ref, expected))
    require(index['schema'] == 'CONSENSUS_COMPARISON_STATUS_R12'
        and len(index['coordinates']) == 383, 'EXACT_STATUS_INDEX_REQUIRED')
    rows = index['coordinates']
    for row, original in zip(rows, planned):
        require(all(row.get(k) == v for k, v in original.items() if k != 'status'),
                'STATUS_INDEX_FROZEN_COORDINATE_CHANGED')
        require(type(row.get('actual_account_attempted')) is bool, 'EXPLICIT_ATTEMPT_STATUS_REQUIRED')
    by_id = {r['coordinate_id']: r for r in rows}
    for row in rows:
        if row['exact_alias_of'] is not None:
            target = by_id[row['exact_alias_of']]
            if row['status'] in TERMINAL:
                require(row.get('alias_is_independent_mechanism') is False
                    and row.get('alias_target_status') == target['status']
                    and row.get('receipt_ref') == target.get('receipt_ref')
                    and row['status'] == ('EXACT_ALIAS_REUSED' if target['status'] == 'COMPLETE' else target['status']),
                    'EXACT_ALIAS_DISPOSITION_CHANGED')
    return run, scope, frozen, matrix, master, index_ref, rows


def _receipt(run, row, frozen):
    coordinate = comparison.extension.Coordinate(*(row[k] for k in ('forecast_pack', 'risk_combination', 'decision_method')))
    flow = 'matrix__'+coordinate.identity
    root = run/'evaluation/consensus_account'/flow
    path = _own_pin(run, row['receipt_ref'], root/'receipt.json')
    receipt = comparison.metadata(path, 16*1024*1024)
    require(receipt.get('matrix_coordinate') == asdict(coordinate)
        and receipt.get('matrix_scope_identity') == comparison.extension._digest(frozen)
        and receipt.get('flow_id') == flow and Path(receipt['receipt_path']).resolve() == path,
        'EXACT_MATRIX_ACCOUNT_RECEIPT_REQUIRED')
    _own_pin(run, receipt['freeze_ref'])
    return root, receipt


def _budget(run):
    path = run/'FIT_LOG.jsonl'
    require(path.exists(), 'GLOBAL_FIT_LOG_REQUIRED_FOR_ACCEPTANCE')
    before = ref(path)
    units, events = 0, Counter()
    with path.open('rb') as handle:
        for line in handle:
            require(len(line) <= 65536, 'BOUNDED_FIT_EVENT_REQUIRED')
            if not line.strip():
                continue
            record = _JsonProjection(io.BytesIO(line)).metadata_fields({'event', 'fit_units'})
            event = record.get('event')
            require(isinstance(event, str), 'FIT_EVENT_METADATA_REQUIRED')
            events[event] += 1
            if event == 'FIT_STARTED':
                require(type(record.get('fit_units')) is int and record['fit_units'] == 1,
                        'PHYSICAL_COMPONENT_ONE_UNIT_REQUIRED')
                units += 1
    require(ref(path) == before, 'FIT_LOG_CHANGED_DURING_ACCEPTANCE')
    require(2063+units <= 10000, 'GLOBAL_CUMULATIVE_FIT_CAP_BREACHED')
    return dict(fit_log_ref=before, metadata_projection_columns=['event', 'fit_units'],
                prior_fit_units=2063, actual_started_units=units, cumulative_fit_units=2063+units,
                maximum_fit_units=10000, remaining_fit_units=10000-2063-units,
                global_cap_reached=2063+units==10000, event_counts=dict(events), failed_attempts_retained=True)


def _budget_reason(value):
    if isinstance(value, dict):
        return value.get('budget_exhausted') is True or any(_budget_reason(v) for k, v in value.items()
            if k in ('reason', 'failure', 'status', 'budget_exhausted'))
    return isinstance(value, str) and any(token in value for token in BUDGET_REASONS)


def export_owner_audits(run, status_index_ref=None):
    """Explicit post-run observer: decode account state, never any risk-cache value.

    Only R12 DiskRiskCache snapshots are accepted; unpickling that class restores
    immutable references. The exporter never calls its values/items/getitem APIs.
    """
    run, scope, frozen, matrix, master, index_ref, rows = _context(run, status_index_ref)
    require(all(r['status'] in TERMINAL for r in rows), 'ALL_PLANNED_DISPOSITIONS_REQUIRED')
    exported = {}
    for row in rows:
        if row['exact_alias_of'] is not None or not row.get('receipt_ref'):
            continue
        root, receipt = _receipt(run, row, frozen)
        pin = receipt.get('artifacts', {}).get('state')
        if pin is None:
            continue
        path = _own_pin(run, pin, root/'state.joblib')
        state = joblib.load(path)
        require(ref(path) == pin, 'ACCOUNT_STATE_CHANGED_DURING_EXPORT')
        require(type(state.get('risk_cache')) is comparison.DiskRiskCache
            and state['risk_cache'].root.is_relative_to(run/'evaluation/consensus_comparison'),
            'R12_REFERENCE_ONLY_RISK_CACHE_REQUIRED')
        if not all(k in state for k in ('metadata', 'audit', 'final_state', 'freeze_ref')):
            continue
        require(state['freeze_ref'] == receipt['freeze_ref'], 'OWNER_STATE_FREEZE_CHANGED')
        final = state['final_state']
        value = dict(schema='CONSENSUS_OWNER_ACCOUNT_AUDIT_EXPORT_R12', master_scope_ref=master,
            status_index_ref=index_ref, matrix_scope_ref=matrix, receipt_ref=row['receipt_ref'], state_ref=pin,
            freeze_ref=receipt['freeze_ref'], flow_id=receipt['flow_id'],
            audit=state['audit'], metadata={k:state['metadata'][k] for k in META_FIELDS if k in state['metadata']},
            final_qualification={k:final[k] for k in ('accounting_qualified', 'research_accounting_qualified', 'last_session') if k in final},
            risk_cache_values_loaded=False, source='ORIGINAL_ACCOUNT_OWNER_FIELDS_NO_RECALCULATION')
        exported[row['coordinate_id']] = _immutable_json(root/'owner_audit.json', value, 'backtest')
    return dict(schema='CONSENSUS_OWNER_AUDIT_EXPORT_INDEX_R12', master_scope_ref=master,
                status_index_ref=index_ref, owner_audit_refs=exported)


def _calendar(run, reference, master):
    pin = reference or ref(run/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json')
    value = comparison.metadata(_own_pin(run, pin, run/'COMPARISON_QUALIFIED_ACCOUNT_CALENDAR.json'))
    require(value['schema'] == 'CONSENSUS_COMPARISON_ACCOUNT_CALENDAR_R12'
        and value['master_scope_ref'] == master and value['full_account_calendar'] is True
        and value['market_values_exported'] is False
        and value['source'] == 'ACTUAL_C_QUALIFIED_LOADED_ARRAYS_METADATA_ONLY', 'EXACT_QUALIFIED_ACCOUNT_CALENDAR_REQUIRED')
    dates = cash.validate_calendar(value['account_sessions'])
    settlement = cash.validate_calendar(value['settlement_sessions'])
    require(all(len(calendar)>500 and calendar.min()>=pd.Timestamp('2023-01-01')
        and calendar.max()<pd.Timestamp('2026-01-01') and set(calendar.year)=={2023,2024,2025}
        for calendar in (dates,settlement)), 'FULL_CONTINUOUS_DEVELOPMENT_CALENDAR_REQUIRED')
    # Exchange and settlement-bank holidays differ. Preserve only the original
    # cash owner's interval coverage; never synthesize or intersect either set.
    require(settlement[0]<=dates[0] and settlement[-1]>=dates[-1],
            'ORIGINAL_SETTLEMENT_CALENDAR_INTERVAL_COVERAGE_REQUIRED')
    with _own_pin(run,value['consumer_freeze_ref']).open('rb') as handle:
        consumer = _JsonProjection(handle).metadata_fields({'reader_scope_ref'})
    require('reader_scope_ref' in consumer, 'EXACT_CONSUMER_READER_SCOPE_REF_REQUIRED')
    with _own_pin(run,consumer['reader_scope_ref']).open('rb') as handle:
        reader = _JsonProjection(handle).metadata_fields({'calendar_ref','settlement_calendar_ref'})
    for exported,original in (('calendar_source_ref','calendar_ref'),
                              ('settlement_calendar_source_ref','settlement_calendar_ref')):
        reference=value.get(exported)
        require(isinstance(reference,dict) and set(reference)>={'path','sha256'}
            and reference==reader.get(original), 'EXACT_QUALIFIED_CALENDAR_SOURCE_REFS_REQUIRED')
    return dates, settlement, value, pin


def _frame(run, root, receipt, name, columns, clocks=(), optional=(), optional_clocks=()):
    reference = receipt['artifacts'][name]
    path = _own_pin(run, reference, root/(name+'.parquet'))
    file = pq.ParquetFile(path)
    if file.metadata.num_rows:
        file, _ = guard_parquet(path, reference['sha256'], clocks)
    for field in optional_clocks:
        qualify(field in file.schema.names or file.metadata.num_rows == 0, 'OWNER_LEDGER_CLOCK_MISSING:'+field)
        if field not in file.schema.names:continue
        index = file.schema.names.index(field)
        for group in range(file.num_row_groups):
            column = file.metadata.row_group(group).column(index)
            stat = column.statistics
            if pa.types.is_null(file.schema_arrow.field(field).type):continue
            require(stat is not None, 'UNPROVED_OPTIONAL_ACCOUNT_CLOCK')
            if stat.num_values:
                require(stat.has_min_max and str(stat.max)[:10]<'2026-01-01', 'FORBIDDEN_OPTIONAL_ACCOUNT_CLOCK')
    missing = set(columns)-set(file.schema.names)
    qualify(not missing or file.metadata.num_rows == 0, 'OWNER_LEDGER_COLUMNS_MISSING:'+name+':'+','.join(sorted(missing)))
    selected = [c for c in (*columns, *optional) if c in file.schema.names]
    return file.read(columns=selected).to_pandas()


def _diagnostic_summary(run, root, receipt):
    if 'diagnostics' not in receipt.get('artifacts',{}):return Counter(),False,False
    table = _frame(run,root,receipt,'diagnostics',['json'])
    counts, exhausted, not_testable = Counter(),False,False
    for raw in table.get('json',[]):
        detail = _JsonProjection(io.BytesIO(str(raw).encode())).metadata_fields({'signal_date','status','reason'})
        if detail.get('signal_date') is not None:
            require(pd.Timestamp(detail['signal_date'])<pd.Timestamp('2026-01-01'), 'PRE2026_DIAGNOSTIC_METADATA_REQUIRED')
        counts[str(detail.get('status','UNKNOWN'))+':'+str(detail.get('reason',''))] += 1
        exhausted |= _budget_reason(detail)
        not_testable |= 'NOT_TESTABLE' in str(detail.get('status',''))
    return counts,exhausted,not_testable


def _owner_proof(run, root, receipt, row, index_ref, master, last_date, owner_ref):
    pin = owner_ref or (ref(root/'owner_audit.json') if (root/'owner_audit.json').exists() else None)
    qualify(pin is not None, 'ORIGINAL_OWNER_AUDIT_EXPORT_MISSING')
    proof = comparison.metadata(_own_pin(run, pin, root/'owner_audit.json'))
    require(proof['schema'] == 'CONSENSUS_OWNER_ACCOUNT_AUDIT_EXPORT_R12'
        and proof['master_scope_ref'] == master and proof['status_index_ref'] == index_ref
        and proof['receipt_ref'] == row['receipt_ref'] and proof['state_ref'] == receipt['artifacts']['state']
        and proof['freeze_ref'] == receipt['freeze_ref'] and proof['flow_id'] == receipt['flow_id']
        and proof['risk_cache_values_loaded'] is False, 'OWNER_AUDIT_EXACT_PINS_REQUIRED')
    _own_pin(run, proof['state_ref'], root/'state.joblib')
    meta, audit, final = proof['metadata'], proof['audit'], proof['final_qualification']
    expected = dict(base_currency='USD', initial_nav=3000., initial_cash=3000., initial_holdings=[],
        fractional_shares=True, integer_share_rounding=False, cash_interest=0, transaction_cost_bps=0,
        financing=False, borrowed_cash=False, long_only=True, max_positions=20, max_weight=.1,
        max_invested=.95, capacity_fraction=.01)
    qualify(meta.get('account_config') == expected and meta.get('fee_config') == asdict(cash.FeeConfig())
        and all(meta.get(k) is True for k in ('continuous_account', 'consensus_cash_adapter',
            'consensus_shareholder_bridge', 'independent_accounts'))
        and meta.get('annual_reset') is False and meta.get('terminal_liquidation') is False
        and meta.get('path_ids') == [receipt['flow_id']] and meta.get('max_positions') == 20
        and meta.get('max_target_weight') == .1 and meta.get('max_target_invested') == .95,
        'ORIGINAL_EMPTY_CASH_FRACTIONAL_ACCOUNT_CONTRACT_UNQUALIFIED')
    for key in ('cash_identity_error_max', 'cost_identity_error_max', 'self_finance_error_max',
                'nav_identity_error_max', 'actual_cash_flow_identity_error_max'):
        v = audit.get(key)
        qualify(isinstance(v, (int, float)) and np.isfinite(v) and 0 <= v <= 1e-5,
                'ORIGINAL_OWNER_AUDIT_FAILED:'+key)
    qualify(audit.get('capacity_violations') == 0 and audit.get('next_open_violations') == 0
        and audit.get('max_actual_names', 21) <= 20 and audit.get('minimum_cash', -1) >= -cash.TOL,
        'ORIGINAL_OWNER_EXECUTION_AUDIT_FAILED')
    for key in ('accounting_qualified', 'research_accounting_qualified'):
        qualify(key in final and np.asarray(final[key]).shape == (1,) and np.asarray(final[key]).dtype == np.dtype(bool)
            and np.asarray(final[key]).tolist() == [True], 'FINAL_ACCOUNT_QUALIFICATION_MISSING_OR_FALSE:'+key)
    qualify(pd.Timestamp(final.get('last_session')) == last_date, 'FINAL_OWNER_SESSION_INCOMPLETE')
    qualify(meta.get('accounting_exception_count') == 0, 'OWNER_ACCOUNTING_EXCEPTIONS')
    return pin


def _account(run, row, frozen, index_ref, master, calendar, owner_ref, diagnostic_summary=None):
    root, receipt = _receipt(run, row, frozen)
    result = dict(receipt_ref=row['receipt_ref'], receipt_status=receipt['status'], budget_incomplete=_budget_reason(receipt))
    qualify(row['status'] == receipt['status'] == 'COMPLETE', 'ACCOUNT_NOT_COMPLETE')
    qualify(row['actual_account_attempted'] is True, 'ACCOUNT_NOT_ACTUALLY_ATTEMPTED')
    qualify(not result['budget_incomplete'], 'CUMULATIVE_FIT_BUDGET_EXHAUSTED')
    qualify(all(k in receipt['artifacts'] for k in LEDGERS), 'REQUIRED_OWNER_LEDGER_MISSING')
    dates, settlement, cal, cal_ref = calendar
    require(receipt['freeze_ref'] == cal['consumer_freeze_ref'], 'ACCOUNT_CALENDAR_CONSUMER_PIN_CHANGED')
    for name in LEDGERS:
        _own_pin(run, receipt['artifacts'][name], root/(name+('.joblib' if name=='state' else '.parquet')))
    daily = _frame(run, root, receipt, 'daily', ['path_id','date','nav','certified_nav','cash',
        'accounting_qualified','transaction_cost_amount','turnover','actual_name_count',
        'settled_cash','unsettled_cash','corporate_receivable'], ['date'], optional=['fx_conversion_fee_usd'])
    qualify(pd.DatetimeIndex(pd.to_datetime(daily.date)).equals(dates), 'CONTINUOUS_ACCOUNT_CALENDAR_INCOMPLETE')
    qualify(daily.path_id.eq(receipt['flow_id']).all(), 'ACCOUNT_PATH_MISMATCH')
    nav = daily.nav.to_numpy(float)
    qualify(np.isfinite(nav).all() and (nav>0).all() and np.isfinite(daily.certified_nav).all()
        and np.allclose(nav, daily.certified_nav, rtol=0, atol=1e-8)
        and daily.accounting_qualified.eq(True).all(), 'CERTIFIED_ACCOUNT_NAV_INCOMPLETE')
    qualify(np.isclose(nav[0],3000.) and np.isclose(daily.cash.iloc[0],3000.)
        and daily.actual_name_count.iloc[0]==0 and (daily.cash>=-cash.TOL).all()
        and (daily.actual_name_count<=20).all(), 'EMPTY_INITIAL_ACCOUNT_OR_CASH_NAME_CONSTRAINT_FAILED')
    owner_pin = _owner_proof(run, root, receipt, row, index_ref, master, dates[-1], owner_ref)
    exceptions = pq.ParquetFile(receipt['artifacts']['accounting_exceptions']['path']).metadata.num_rows
    qualify(exceptions==0, 'ACCOUNTING_EXCEPTIONS_PRESENT')
    fills = _frame(run, root, receipt, 'fills', ['path_id','signal_date','execution_date','ticker','side',
        'notional','index_units','transaction_cost','settlement_date'], ['signal_date','execution_date'])
    positions = _frame(run, root, receipt, 'positions', ['path_id','date','ticker','index_units','weight'], ['date'])
    orders = _frame(run, root, receipt, 'orders', ['path_id','signal_date','execution_date','ticker',
        'decision_semantic','target_weight','adapted_target_weight','signal_reserved'], ['signal_date','execution_date'])
    executions = _frame(run, root, receipt, 'execution_results', ['path_id','signal_date','execution_date','status','reason'], ['signal_date','execution_date'])
    ledger = _frame(run, root, receipt, 'settlement_ledger', ['path_id','execution_date','settlement_date',
        'net_sale_proceeds','actual_settlement_session'], ['execution_date'], optional_clocks=['actual_settlement_session'])
    for table in (fills, positions, orders, executions, ledger):
        qualify(table.empty or table.path_id.eq(receipt['flow_id']).all(), 'INDEPENDENT_ACCOUNT_LEDGER_PATH_MISMATCH')
    if not fills.empty:
        qualify(np.isfinite(fills.notional).all() and (fills.notional>0).all()
            and np.allclose(fills.transaction_cost,cash.fee_for_notional(fills.notional,cash.FeeConfig()),rtol=0,atol=1e-8),
            'ORIGINAL_FEE_FUNCTION_MISMATCH')
        qualify(pd.to_datetime(fills.execution_date).isin(dates).all()
            and (pd.to_datetime(fills.execution_date)>pd.to_datetime(fills.signal_date)).all(), 'FILL_CLOCK_OUTSIDE_ACCOUNT')
    trade_fees = float(fills.transaction_cost.sum()) if not fills.empty else 0.
    qualify(np.isclose(trade_fees,daily.transaction_cost_amount.sum(),atol=1e-8), 'FILL_DAILY_FEE_MISMATCH')
    sales = fills.loc[fills.side.eq('SELL')] if not fills.empty else fills
    qualify(len(ledger)==(sales.groupby('execution_date').ngroups if len(sales) else 0), 'SETTLEMENT_LEDGER_MISSING_OR_EXTRA')
    for _, entry in ledger.iterrows():
        day = pd.Timestamp(entry.execution_date)
        due = cash.settlement_date(day,settlement,trading_calendar=dates)
        actual = dates[dates>=due][0] if due is not None and (dates>=due).any() else pd.NaT
        group = sales.loc[pd.to_datetime(sales.execution_date).eq(day)]
        qualify((pd.isna(entry.settlement_date) and due is None) or pd.Timestamp(entry.settlement_date)==due,
                'ORIGINAL_SETTLEMENT_DUE_MISMATCH')
        qualify((pd.isna(entry.actual_settlement_session) and pd.isna(actual)) or pd.Timestamp(entry.actual_settlement_session)==actual,
                'ORIGINAL_SETTLEMENT_RELEASE_CLOCK_MISMATCH')
        qualify(np.isclose(entry.net_sale_proceeds,(group.notional-group.transaction_cost).sum(),atol=1e-8), 'SETTLEMENT_NET_SALE_MISMATCH')
    diagnostic_counts,diagnostic_budget,diagnostic_nt = diagnostic_summary or _diagnostic_summary(run,root,receipt)
    qualify(not diagnostic_budget, 'CUMULATIVE_FIT_BUDGET_EXHAUSTED')
    qualify(not diagnostic_nt, 'OWNER_POLICY_NOT_TESTABLE')
    annual = evaluator.annual_statistics(daily)
    peaks = np.maximum.accumulate(np.r_[3000.,nav])[1:]
    fingerprints = _fingerprints(row['coordinate_id'],orders,fills)
    result.update(qualified=True, owner_audit_ref=owner_pin, ledger_refs=receipt['artifacts'],
        net_total_return=float(nav[-1]/3000.-1), max_drawdown=float(-np.min(nav/peaks-1)),
        total_fees=float(sum(s['fees'] for s in annual['annual_statistics'])), trade_fees=trade_fees,
        total_turnover=annual['total_turnover'], annual_statistics=annual['annual_statistics'],
        sessions=len(daily),fills=len(fills),orders=len(orders),holdings_rows=len(positions),
        max_actual_names=int(daily.actual_name_count.max()),
        mean_actual_names=float(daily.actual_name_count.mean()),
        minimum_settled_cash=float(daily.settled_cash.min()), maximum_unsettled_cash=float(daily.unsettled_cash.max()),
        max_observed_position_weight=float(positions.weight.max()) if len(positions) else 0.,
        execution_reason_counts=dict(Counter(executions.get('reason',[]))),diagnostic_reason_counts=dict(diagnostic_counts),
        certification='CONDITIONAL_SHAREHOLDER_RESEARCH_ACCOUNT_NO_STRICT_PIT_CLAIM', calendar_ref=cal_ref)
    return result, fingerprints


def _fingerprints(coordinate_id, orders, fills):
    """Group each owner ledger once; preserve the original per-day hash bytes."""
    def grouped(table, clock):
        if table.empty:return {}
        return {pd.Timestamp(day):comparison.extension._digest(_json(
            group.drop(columns=['path_id'],errors='ignore').sort_values(
                [c for c in group.columns if c!='path_id']).to_dict('records')))
            for day,group in table.groupby(pd.to_datetime(table[clock]),sort=False)}
    decisions, trades = grouped(orders,'signal_date'), grouped(fills,'execution_date')
    empty = comparison.extension._digest([])
    return [dict(coordinate_id=coordinate_id,date=str(day.date()),
        decision_sha256=decisions.get(day,empty),fills_sha256=trades.get(day,empty))
        for day in sorted(decisions.keys() | trades.keys())]


def summarize(run, status_index_ref=None, *, calendar_ref=None, owner_audit_refs=None):
    """Return an honest terminal comparison and unexecuted frozen sensitivity plan.

    No joblib loading occurs here. Call export_owner_audits explicitly after the
    run; all numeric reads are only this run's exact pinned pre2026 owner ledgers.
    """
    run, scope, frozen, matrix, master, index_ref, rows = _context(run,status_index_ref)
    budget = _budget(run)
    all_terminal = all(r['status'] in TERMINAL for r in rows)
    report = dict(schema=SCHEMA,acceptance_source_ref=ref(__file__),master_scope_ref=master,matrix_scope_ref=matrix,status_index_ref=index_ref,
        read_scope=dict(own_run=str(run),before='2026-01-01',test2026_read=False,confirmation_read=False,
            model_payloads_read=False,development_only=True,independent_holdout_claim=False),
        planned_labels=383,independent_representatives=323,exact_aliases=60,
        aliases_are_independent_mechanisms=False,all_planned_coordinates_terminal=all_terminal,
        budget=budget,ranking_rule=ORDER,max_drawdown_convention='NONNEGATIVE_PEAK_TO_TROUGH_LOSS_MAGNITUDE',
        coordinates=[],ranking=[],sensitivity_plan=[],daily_decision_trade_fingerprints=[])
    if not all_terminal:
        report['coordinates']=[{k:r.get(k) for k in ('coordinate_id','forecast_pack','risk_combination',
            'decision_method','actual_account_attempted','status','reason','exact_alias_of')} for r in rows]
        report.update(status='WAITING_FOR_TERMINAL_COORDINATES',selection_status='SELECTION_DEFERRED',comparison_complete=False,
            unresolved_coordinate_ids=[r['coordinate_id'] for r in rows if r['status'] not in TERMINAL])
        return report
    calendar = _calendar(run,calendar_ref,master)
    results = {}
    for row in rows:
        if row['exact_alias_of'] is not None:
            continue
        result=dict(coordinate_id=row['coordinate_id'],forecast_pack=row['forecast_pack'],risk_combination=row['risk_combination'],
            decision_method=row['decision_method'],actual_account_attempted=row['actual_account_attempted'],
            status=row['status'],reason=row.get('reason'),qualified=False,exact_alias_of=None,
            net_total_return=None,max_drawdown=None,total_fees=None,budget_incomplete=_budget_reason(row))
        diagnostic_summary = None
        if row.get('receipt_ref'):
            root, receipt = _receipt(run,row,frozen)
            diagnostic_summary = _diagnostic_summary(run,root,receipt)
            result.update(receipt_ref=row['receipt_ref'],receipt_status=receipt['status'],
                diagnostic_reason_counts=dict(diagnostic_summary[0]),
                budget_incomplete=result['budget_incomplete'] or _budget_reason(receipt) or diagnostic_summary[1],
                failure=receipt.get('failure'))
        if row['status']=='COMPLETE':
            try:
                qualify(bool(row.get('receipt_ref')), 'ORIGINAL_ACCOUNT_RECEIPT_MISSING')
                qualify(not result['budget_incomplete'], 'CUMULATIVE_FIT_BUDGET_EXHAUSTED')
                account, fingerprints = _account(run,row,frozen,index_ref,master,calendar,(owner_audit_refs or {}).get(row['coordinate_id']),diagnostic_summary)
                result.update(account)
                report['daily_decision_trade_fingerprints'].extend(fingerprints)
            except Unqualified as error:
                result.update(qualification_failure=str(error),budget_incomplete=result['budget_incomplete'] or _budget_reason(str(error)))
        results[row['coordinate_id']]=result
    ranked=sorted((r for r in results.values() if r['qualified']),key=lambda r:(-r['net_total_return'],r['max_drawdown'],r['total_fees'],r['coordinate_id']))
    for rank, row in enumerate(ranked,1):
        row['rank']=rank
    for row in rows:
        if row['exact_alias_of'] is None:
            report['coordinates'].append(results[row['coordinate_id']])
        else:
            target=results[row['exact_alias_of']]
            report['coordinates'].append(dict(target,coordinate_id=row['coordinate_id'],forecast_pack=row['forecast_pack'],
                risk_combination=row['risk_combination'],decision_method=row['decision_method'],status=row['status'],
                actual_account_attempted=False,exact_alias_of=row['exact_alias_of'],independent_rank=None,
                rank=None,alias_is_independent_mechanism=False,representative_rank=target.get('rank')))
    report['ranking']=[r['coordinate_id'] for r in ranked]
    budget_incomplete=any(r['budget_incomplete'] for r in results.values())
    missing_attempts=[r['coordinate_id'] for r in results.values() if not r['actual_account_attempted']]
    fully_complete=len(ranked)==323 and not budget_incomplete and not missing_attempts
    report.update(status='COMPLETE' if fully_complete else 'TERMINAL_INCOMPLETE',comparison_complete=fully_complete,
        selection_status='QUALIFIED_DEVELOPMENT_SELECTION' if ranked else 'NO_QUALIFIED_SELECTION',
        selected_coordinate_id=ranked[0]['coordinate_id'] if ranked else None,
        budget_exhaustion_is_incomplete=budget_incomplete,
        comparison_truncated_by_budget=budget_incomplete,missing_actual_attempts=missing_attempts,
        representative_disposition_counts=dict(Counter(r['status'] for r in results.values())),
        actual_account_attempts=sum(r['actual_account_attempted'] for r in results.values()),
        qualified_representatives=len(ranked),unqualified_representatives=323-len(ranked),
        selection_caveat='DEVELOPMENT_ONLY; DISPOSITIONS_COMPLETE_DOES_NOT_MEAN_ALL_METHODS_EXECUTED_OR_CERTIFIED')
    bases=[r['coordinate_id'] for r in ranked[:3]]
    neutral=tuple(scope['comparison']['neutral_coordinate'])
    neutral_row=next((r for r in report['coordinates'] if tuple(r[k] for k in ('forecast_pack','risk_combination','decision_method'))==neutral),None)
    if neutral_row and neutral_row['qualified']:
        representative=neutral_row['exact_alias_of'] or neutral_row['coordinate_id']
        if representative not in bases:bases.append(representative)
    for base in bases:
        for condition in CONDITIONS:
            report['sensitivity_plan'].append(dict(base_coordinate_id=base,fee_condition=condition,
                initial_cash=3000,empty_independent_account=True,status='PLANNED_NOT_ATTEMPTED',
                executed=False,execution_authorized_by_this_report=False,no_retuning=True,base_owner_receipt_ref=results[base]['receipt_ref']))
    require(len(report['sensitivity_plan'])<=12,'FROZEN_SENSITIVITY_MAXIMUM_EXCEEDED')
    report['output_schema']=dict(coordinate_metrics='nullable numeric; missing/unqualified never zero performance',
        aliases='representative metrics repeated with exact_alias_of; no independent rank or mechanism claim',
        daily_comparison='same date decision and actual fill fingerprints, account path excluded',
        provenance='exact master/index/calendar/receipt/ledger/state/audit/FIT_LOG pins; original source qualification retained')
    require(ref(index_ref['path'])==index_ref,'STATUS_INDEX_CHANGED_DURING_ACCEPTANCE')
    return report


def write_report(report, output_dir=None):
    """Immutable JSON plus flat comparable metrics and daily signature CSVs."""
    require(report['schema']==SCHEMA,'ACCEPTANCE_REPORT_SCHEMA_REQUIRED')
    run=Path(report['read_scope']['own_run'])
    root=Path(output_dir) if output_dir else resolve().results_root/'_maintenance'/evaluator.TASK/'comparison_acceptance'/run.name
    assert_safe_output_path(root,kind='results',paths=resolve())
    pins={}
    fingerprint_columns=['coordinate_id','date','decision_sha256','fills_sha256']
    for name,rows in [('coordinate_metrics',report['coordinates']),
                      ('daily_decision_trade_fingerprints',report['daily_decision_trade_fingerprints']),
                      ('sensitivity_execution_plan',report['sensitivity_plan'])]:
        table=pd.DataFrame([{k:(json.dumps(_json(v),sort_keys=True) if isinstance(v,(dict,list)) else v)
            for k,v in row.items()} for row in rows])
        if name=='daily_decision_trade_fingerprints':
            if table.empty:table=table.reindex(columns=fingerprint_columns)
            fingerprint_columns=list(table.columns)
        path=root/(name+'.csv');text=table.to_csv(index=False,lineterminator='\n')
        root.mkdir(parents=True,exist_ok=True)
        if path.exists():require(path.read_text(encoding='utf8')==text,'ACCEPTANCE_IMMUTABLE_EXPORT_CHANGED')
        else:path.write_text(text,encoding='utf8')
        pins[name]=ref(path)
    # Keep the in-memory API unchanged. Avoid recursively copying/indenting a
    # second copy of the potentially 240k-row CSV in JSON metadata.
    serialized=dict(report)
    serialized['daily_decision_trade_fingerprints']=dict(
        artifact_ref=pins['daily_decision_trade_fingerprints'],
        row_count=len(report['daily_decision_trade_fingerprints']),format='CSV',inline_rows=False,
        schema=dict(columns=fingerprint_columns,record_unit='ONE_COORDINATE_DATE_DECISION_AND_FILL_HASH_PAIR'))
    pins['report']=_immutable_json(root/'acceptance.json',serialized,'results')
    return pins
