"""One fixed SPY2024 archive diagnostic; observations never become execution Quotes."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from io import StringIO
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import DataStore
from .contracts import Fees, Invalid, TEMPLATE, calendar, require
from .contract_continuity import clean, continuity_key, crossed, number_status
from .expression import choose_atm_contract, choose_expiry
from .frontier import conditional_cash_point, solve_price_frontier, _tick
from .historical_quotes import _write_json
from .public_history import inspect_parquet, _file_digest

TASK = 'OPTIONS_SPY2024_OBSERVED_FRONTIER_DIAGNOSTIC_R1'
CONTINUATION_TASK = 'OPTIONS_SPY2024_AUTHENTICATED_REFERENCE_FETCH_AND_CONTINUE_R1'
COMPAT_TASK = 'OPTIONS_SPY2024_COMPLETE_COMPAT_TRAIN_R1'
OBSERVED_PARENT = '20260915T141215Z'
VERSION = '37f6c456fe1a4775c875673fb8ef907d5cd2fd66'
REFERENCE_COLUMNS = ['ticker', 'date', 'close', 'adjustment', 'source', 'currency']
IDS = ['date', 'symbol', 'contract_id', 'expiration', 'strike', 'type']
RIGHTS = ['root', 'multiplier', 'deliverable', 'adjustment_status']


def make_plan():
    cal, plan, excluded = calendar(), [], []
    for e in cal.sessions[cal.sessions.year == 2024]:
        i = cal.sessions.get_loc(e)
        s, h = cal.sessions[i-1], cal.sessions[i+5]
        row = dict(decision_id='SPY2024:'+str(e.date()), reference_date=str(s.date()),
                   entry_date=str(e.date()), exit_date=str(h.date()))
        if s.year != 2024 or h.year != 2024:
            excluded.append(row | {'reason': 'REFERENCE_BEFORE_2024' if s.year != 2024 else 'EXIT_AFTER_2024'})
            continue
        row.update(entry_early_close=cal.session_close(e).tz_convert('America/New_York').hour < 16,
                   exit_early_close=cal.session_close(h).tz_convert('America/New_York').hour < 16)
        plan.append(row)
    return [r | {'plan_weight': 1/len(plan)} for r in plan], excluded


def _scope(frame):
    dates = pd.to_datetime(frame['date'], errors='raise')
    require(dates.notna().all() and dates.dt.year.eq(2024).all()
            and dates.eq(dates.dt.normalize()).all(), 'OBSERVATION_OUTSIDE_2024')


def read_references(binding):
    """Existing Arrow reader filters the cross-year file before materialization."""
    start, end = binding['projection_dates']
    require('2024-01-01' <= start <= end <= '2024-12-31', 'REFERENCE_PROJECTION_OUTSIDE_2024')
    require(binding['columns'] == ['ticker', 'date', 'close', 'adjustment', 'source', 'currency'], 'REFERENCE_COLUMNS_CHANGED')
    stock = DataStore()
    current = stock.metadata('prices_daily_massive', 'SPY', 'raw')
    require(current['path'] == binding['path'] and current['source_sha256'] == binding['source_sha256'], 'REFERENCE_BINDING_CHANGED')
    require(current['lineage']['price_basis'] == 'RAW' and current['lineage']['currency'] == 'USD', 'REF_NOT_RAW_USD')
    frame = stock.daily('SPY', 'raw', start, end, columns=binding['columns'], provider='massive')
    _scope(frame)
    return frame


def continuation_parent(manifest, results_root):
    """Verify the one authorized parent before accepting a new reference input."""
    binding = manifest['observed_parent']
    run = Path(binding['run']).resolve()
    require(run == results_root/TEMPLATE/'spy2024_observed_frontier'/OBSERVED_PARENT,
            'OBSERVED_PARENT_BOUNDARY')
    require(_file_digest(run/'run_manifest.json') == binding['manifest_sha256'], 'OBSERVED_PARENT_CHANGED')
    parent = json.loads((run/'run_manifest.json').read_bytes())
    require(parent['task_id'] == TASK and parent['status'] == 'COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC',
            'OBSERVED_PARENT_NOT_COMPLETE')
    for field in ('research_identity', 'plan', 'calendar_exclusions', 'reference_binding',
                  'source_documents', 'source_qualification', 'source_status', 'parent_cache',
                  'parent_run', 'parent_manifest_sha256', 'fee_parent_config', 'fee_parent_sha256',
                  'fee_profile', 'fees', 'domain', 'specification'):
        require(manifest[field] == parent[field], 'CONTINUATION_SPECIFICATION_CHANGED')
    records = parent['entry_lock']['records']
    raw = json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False)
    require(hashlib.sha256(raw.encode()).hexdigest() == parent['entry_lock']['sha256'],
            'OBSERVED_PARENT_ENTRY_LOCK_CHANGED')
    require(len(records) == 246 and [r['decision_id'] for r in records] ==
            [r['decision_id'] for r in manifest['plan']], 'OBSERVED_PARENT_PLAN_CHANGED')
    require(sum(r['selection_status'] == 'SELECTED' for r in records) == 70 and
            sum(r['selection_reason'] == 'REFERENCE_MISSING' for r in records) == 176,
            'OBSERVED_PARENT_COVERAGE_CHANGED')
    require(_file_digest(run/'observed_frontier.csv') == parent['result_sha256'],
            'OBSERVED_PARENT_RESULT_CHANGED')
    return parent


def add_missing_references(existing, binding, parent):
    """Read only the qualified, hash-bound missing-s projection; never replace a row."""
    missing = [r['reference_date'] for r in parent['entry_lock']['records']
               if r['selection_reason'] == 'REFERENCE_MISSING']
    require(binding['allowed_reference_dates'] == missing and
            all('2024-01-01' <= d <= '2024-12-31' for d in missing), 'REFERENCE_ADDITION_SCOPE_CHANGED')
    if binding['qualification'].get('status') == 'QUALIFIED_TRADE_BASIS_USD_DAILY_REFERENCE':
        from .price_basis import read_trade_references
        additions = read_trade_references(binding, missing)
        require(not set(additions.date) & set(existing.date), 'REFERENCE_ADDITION_OVERWRITES_PARENT')
        return pd.concat([existing, additions], ignore_index=True), set(additions.date)
    require(binding['columns'] == REFERENCE_COLUMNS, 'REFERENCE_COLUMNS_CHANGED')
    qualification = binding['qualification']
    require(qualification['status'] == 'QUALIFIED_RAW_USD_DAILY_REFERENCE' and
            qualification['provider'] == 'MASSIVE' and qualification['adjusted'] is False and
            qualification['currency'] == 'USD' and clean(qualification['date_semantics']) and
            clean(qualification['session_basis']) and qualification['evidence'], 'REFERENCE_ADDITIONS_NOT_QUALIFIED')
    for evidence in qualification['evidence']:
        require(_file_digest(Path(evidence['path'])) == evidence['sha256'], 'REFERENCE_EVIDENCE_CHANGED')
    path = Path(binding['path'])
    require(_file_digest(path) == binding['sha256'], 'REFERENCE_ADDITIONS_CHANGED')
    records = json.loads(path.read_bytes())
    require(isinstance(records, list) and 0 < len(records) <= len(missing), 'REFERENCE_ADDITIONS_EMPTY_OR_OVERSIZED')
    require(all(isinstance(r, dict) and set(r) == set(REFERENCE_COLUMNS) for r in records),
            'REFERENCE_COLUMNS_CHANGED')
    additions = pd.DataFrame(records, columns=REFERENCE_COLUMNS)
    _scope(additions)
    require(additions.date.map(lambda d: isinstance(d, str) and d in missing).all()
            and additions.date.is_unique, 'REFERENCE_ADDITION_KEY_INVALID')
    require(not set(additions.date) & set(existing.date), 'REFERENCE_ADDITION_OVERWRITES_PARENT')
    require(additions.ticker.eq('SPY').all() and additions.adjustment.eq('raw').all() and
            additions.currency.eq('USD').all() and additions.source.map(lambda v: bool(clean(v))).all() and
            additions.close.map(lambda v: number_status(v, positive=True) == 'VALID_POSITIVE').all(),
            'REFERENCE_ADDITIONS_NOT_RAW_USD')
    return pd.concat([existing, additions], ignore_index=True), set(additions.date)


def reconcile_parent_entries(entry_records, parent):
    current = {r['decision_id']: r for r in entry_records}
    original = [r for r in parent['entry_lock']['records'] if r['selection_status'] == 'SELECTED']
    require(all(current.get(r['decision_id']) == r for r in original), 'OBSERVED_PARENT_SELECTION_CHANGED')


def continuation_summary(panel, parent, parent_run, added_dates):
    """Reconcile old outcomes at stored precision; report groups with unchanged plan weights."""
    prior = pd.read_csv(Path(parent_run)/'observed_frontier.csv', float_precision='round_trip')
    selected = {r['decision_id'] for r in parent['entry_lock']['records'] if r['selection_status'] == 'SELECTED'}
    old = panel.decision_id.isin(selected)
    # CSV round-trips preserve the parent's stored float representation and nullable types.
    current = pd.read_csv(StringIO(panel.to_csv(index=False)), float_precision='round_trip')
    try:
        pd.testing.assert_frame_equal(prior.loc[prior.decision_id.isin(selected)].reset_index(drop=True),
            current.loc[old, prior.columns].reset_index(drop=True), check_dtype=False, check_exact=True)
    except (AssertionError, KeyError):
        raise Invalid('OBSERVED_PARENT_RESULT_CHANGED') from None
    fresh = panel.reference_date.isin(added_dates)
    groups = {}
    for name, mask in [('prior_reconciled', old), ('newly_referenced', fresh),
                       ('still_reference_missing', ~old & ~fresh)]:
        part = panel.loc[mask]
        groups[name] = dict(rows=len(part), original_plan_weight=float(part.plan_weight.sum()),
                           summary=summarize(part) if len(part) else None)
    prior_old = prior.decision_id.isin(selected)
    return dict(parent_selected_reconciled=len(selected), parent_q_reconciled=int(prior.loc[prior_old, 'q'].notna().sum()),
        parent_cash_reconciled=int(prior.loc[prior_old, 'conditional_wealth_difference'].notna().sum()),
        parent_frontiers_reconciled=int(prior.loc[prior_old, 'B_min_cash'].notna().sum()),
        parent_outcomes_identical=True, full_plan_rows=len(panel), full_plan_recomputed_once=True,
        group_coverage_denominator='EACH_GROUP_ROWS; PLAN_WEIGHTS_REMAIN_1/246', groups=groups)


def _identity(row, version):
    code = clean(row.get('contract_id'))
    match = re.fullmatch(r'([A-Z0-9.]+)(\d{6})([CP])(\d{8})', code or '')
    if not match or clean(row.get('symbol')) != 'SPY':
        return None, 'IDENTITY_INCOMPLETE_OR_INVALID'
    root, expiry, cp, strike = match.groups()
    try:
        expiry = datetime.strptime(expiry, '%y%m%d').date().isoformat()
        exact = Decimal(str(row['strike']))
        right = {'call': 'C', 'put': 'P', 'CALL': 'C', 'PUT': 'P', 'C': 'C', 'P': 'P'}.get(row['type'])
        if root != 'SPY':
            return None, 'NONSTANDARD_ROOT'
        if (clean(row.get('expiration')) != expiry or right != cp or not exact.is_finite()
                or exact <= 0 or exact != Decimal(strike)/1000):
            return None, 'IDENTITY_COMPONENT_CONFLICT'
        if any(clean(row.get(k)) is not None and str(row[k]) != expected
               for k, expected in [('root', root), ('deliverable', '100_UNDERLYING_SHARES'), ('adjustment_status', 'STANDARD')]):
            return None, 'KNOWN_RIGHTS_CONFLICT'
        if clean(row.get('multiplier')) is not None and Decimal(str(row['multiplier'])) != 100:
            return None, 'KNOWN_RIGHTS_CONFLICT'
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return None, 'IDENTITY_COMPONENT_CONFLICT'
    key = continuity_key({'source': 'ETF_2024', 'act_symbol': root, 'source_contract_id': code}, version)
    return dict(option_code=code, expiry=expiry, strike=float(exact), exact_strike=str(exact),
                call_put='CALL' if cp == 'C' else 'PUT', root=root, source_continuity_key=key), 'VALID_SOURCE_IDENTITY'


def select_entries(plan, identities, references, version):
    """Only entry identity and prior-session raw close; no quote/exit input."""
    require(version == VERSION, 'SOURCE_VERSION_CHANGED')
    _scope(identities); _scope(references)
    require(not {'bid', 'ask', 'exit_bid', 'exit_ask'} & set(identities.columns), 'SELECTION_MUST_BE_PRICE_BLIND')
    days = {d: g for d, g in identities.groupby('date', sort=False)}
    refs = {d: g for d, g in references.groupby('date', sort=False)}
    rows = []
    for item in plan:
        r = dict(item, selection_status='NOT_SELECTED', selection_reason='REFERENCE_MISSING',
                 selected_contract_id=None, reference_close=None, source_continuity_key=None,
                 source_kind='ARCHIVED_OBSERVED_SNAPSHOT', evidence_grade='SOURCE_DOCUMENTED_SNAPSHOT',
                 series_rights='UNVERIFIED_STANDARD_CONTRACT_AMOUNT_ASSUMPTION')
        rows.append(r)
        ref = refs.get(item['reference_date'])
        group = days.get(item['entry_date'], pd.DataFrame(columns=IDS))
        r['source_entry_identity_rows'] = len(group)
        if ref is None or not len(ref):
            continue
        if len(ref) != 1:
            r['selection_reason'] = 'REFERENCE_CONFLICT'; continue
        value = ref.iloc[0]
        if (value.get('adjustment') != 'raw' or value.get('currency') != 'USD'
                or not clean(value.get('source')) or number_status(value['close'], positive=True) != 'VALID_POSITIVE'):
            r['selection_reason'] = 'REF_NOT_RAW_USD'; continue
        r['reference_close'] = float(value['close'])
        if not len(group):
            r['selection_reason'] = 'ENTRY_CHAIN_MISSING'; continue
        # DTE uses identity fields only; identity conflicts never consult prices.
        dte = (pd.to_datetime(group.expiration, errors='coerce') - pd.Timestamp(item['entry_date'])).dt.days
        band = group.loc[dte.between(30, 60)]
        candidates, rejects, seen = [], Counter(), {}
        for raw in band.to_dict('records'):
            candidate, reason = _identity(raw, version)
            if candidate is None:
                rejects[reason] += 1; continue
            if candidate['call_put'] != 'CALL':
                continue
            candidate['dte'] = (pd.Timestamp(candidate['expiry']) - pd.Timestamp(item['entry_date'])).days
            code = candidate['option_code']
            seen.setdefault(code, []).append(candidate)
        for code, records in seen.items():
            if len({json.dumps(x, sort_keys=True) for x in records}) != 1:
                rejects['IDENTITY_KEY_CONFLICT'] += len(records)
            else:
                candidates.append(records[0])
        r['eligible_identity_count'] = len(candidates)
        r['identity_rejections'] = json.dumps(dict(rejects), sort_keys=True)
        expiry = choose_expiry(candidates, 45)
        chosen = choose_atm_contract(candidates, expiry['expiry'], 'CALL', r['reference_close']) if expiry else None
        if chosen is None:
            r['selection_reason'] = 'NO_ELIGIBLE_SOURCE_CALL'; continue
        r.update(selection_status='SELECTED', selection_reason='PRIOR_RAW_CLOSE_ANCHORED',
                 selected_contract_id=chosen['option_code'], selected_expiration=chosen['expiry'],
                 selected_strike=chosen['exact_strike'], selected_root=chosen['root'],
                 source_continuity_key=chosen['source_continuity_key'])
    return pd.DataFrame(rows)


def _lookup(groups, date, code, version, expected_key):
    group = groups.get((date, code))
    if group is None:
        return None, 'MISSING'
    fields = [k for k in IDS+['bid', 'ask']+RIGHTS if k in group.columns]
    unique = group[fields].drop_duplicates()
    if len(unique) != 1:
        return None, 'CONFLICT'
    record = unique.iloc[0].to_dict()
    identity, reason = _identity(record, version)
    if not identity or identity['source_continuity_key'] != expected_key:
        return None, reason
    for side in ['bid', 'ask']:
        if number_status(record.get(side)) not in ('VALID_POSITIVE', 'ZERO_OBSERVED'):
            return record, side.upper()+'_'+number_status(record.get(side))
    if crossed(record['bid'], record['ask']):
        return record, 'CROSSED'
    return record, 'VALID'


def analyse_locked(entries, observations, fees, domain):
    _scope(observations)
    groups = {(str(d), str(c)): g for (d, c), g in observations.groupby(['date', 'contract_id'], dropna=True)}
    counters = dict(source_observation_analysis_calls=0, conditional_amount_calls=0, solver_calls=0,
                    solver_kernel_calls=0, real_r1_evaluate_calls=0)
    rows = []
    for item in entries.to_dict('records'):
        counters['source_observation_analysis_calls'] += 1
        r = item | dict(q=None, q_status='NOT_SELECTED', cash_status='NOT_EVALUATED',
            cash_reason=item['selection_reason'], B_min_cash=None, frontier_status='NOT_EVALUATED',
            margin_quote=None, conditional_wealth_difference=None, conditional_cash=None,
            conditional_position_quantity=None, root_wealth=None, neighbor_bid=None, neighbor_wealth=None)
        rows.append(r)
        if item['selection_status'] != 'SELECTED':
            continue
        entry, er = _lookup(groups, item['entry_date'], item['selected_contract_id'], VERSION, item['source_continuity_key'])
        exit_row, xr = _lookup(groups, item['exit_date'], item['selected_contract_id'], VERSION, item['source_continuity_key'])
        for label, record, status in [('entry', entry, er), ('exit', exit_row, xr)]:
            r[label+'_quote_status'] = status
            r[label+'_ask'] = record.get('ask') if record else None
            r[label+'_bid'] = record.get('bid') if record else None
        r['q_status'] = 'ENTRY_'+er
        if er != 'VALID' or number_status(entry['ask'], positive=True) != 'VALID_POSITIVE':
            r['cash_reason'] = r['q_status'] = 'ENTRY_'+(er if er != 'VALID' else 'ZERO_ASK'); continue
        if item['entry_early_close']:
            r['cash_reason'] = r['q_status'] = 'TIME_AMBIGUOUS'; continue
        ask = float(entry['ask'])
        exit_usable = xr == 'VALID' and not item['exit_early_close']
        if exit_usable:
            r['q'] = float(exit_row['bid'])/ask-1
            r['q_status'] = 'CALCULATED'
        else:
            r['q_status'] = 'TIME_AMBIGUOUS' if item['exit_early_close'] else 'EXIT_'+xr
        if entry['bid'] == 0:
            r['cash_reason'] = 'ZERO_ENTRY_BID_OUTSIDE_AMOUNT_DOMAIN'
            continue
        actual_bid = float(exit_row['bid']) if exit_usable else None
        point = conditional_cash_point(ask, actual_bid, fees)
        counters['conditional_amount_calls'] += 1
        r.update(cash_status=point['status'], cash_reason=point['reason'],
                 conditional_cash=point['cash'], conditional_position_quantity=point['position_quantity'],
                 entry_fill_price=point['entry_fill_price'], exit_fill_price=point['exit_fill_price'],
                 entry_fee=point['entry_fee'], exit_fee=point['exit_fee'], remaining_entry_cash=point['entry_cash'])
        if not exit_usable and point['status'] == 'UNRESOLVED':
            r['cash_reason'] = r['q_status']
        if point['status'] == 'CLOSED':
            r['conditional_wealth_difference'] = point['net_wealth'] - 10000
        if not domain['ask_min'] <= ask <= domain['ask_max']:
            r['frontier_status'] = 'OUTSIDE_DOMAIN'; continue
        counters['solver_calls'] += 1
        lo = max(_tick(domain['bid_min']), int((Decimal(str(fees.option_slippage))*100).to_integral_value(rounding=ROUND_CEILING)))
        frontier = solve_price_frontier(lambda tick: conditional_cash_point(ask, tick/100, fees),
            direction='required_exit_bid', lower_tick=lo, upper_tick=_tick(domain['bid_max']),
            control_wealth=10000, tolerance_usd=domain['tolerance_usd'])
        counters['solver_kernel_calls'] += frontier['kernel_evaluations']
        r['frontier_status'] = frontier['status']
        r['B_min_cash'] = frontier['price']
        r['frontier_reason'] = frontier['reason']
        r['frontier_kernel_calls'] = frontier['kernel_evaluations']
        if frontier['root'] is not None:
            r['root_wealth'] = frontier['root']['net_wealth']
            r['neighbor_bid'] = frontier['neighbor_price']
            r['neighbor_wealth'] = (frontier['neighbor'] or {}).get('net_wealth')
        if frontier['price'] is not None and exit_usable:
            r['margin_quote'] = actual_bid-frontier['price']
    return pd.DataFrame(rows), counters


def summarize(panel):
    n = len(panel)
    def stats(column):
        values = panel[column].dropna()
        return dict(count=len(values), mean=float(values.mean()) if len(values) else None,
                    median=float(values.median()) if len(values) else None,
                    decision_days=int(panel.loc[panel[column].notna(), 'entry_date'].nunique()),
                    months=int(panel.loc[panel[column].notna(), 'entry_date'].str[:7].nunique()),
                    positive=int((values > 0).sum()), negative=int((values < 0).sum()), zero=int((values == 0).sum()),
                    coverage=len(values)/n, unidentified_weight=float(panel.loc[panel[column].isna(), 'plan_weight'].sum()))
    return dict(planned=n, selected=int(panel.selection_status.eq('SELECTED').sum()),
        unresolved=int(panel.cash_status.eq('UNRESOLVED').sum()), decision_days=panel.entry_date.nunique(),
        months=panel.entry_date.str[:7].nunique(), q=stats('q'), cash=stats('conditional_wealth_difference'),
        margin=stats('margin_quote'), frontier_count=int(panel.B_min_cash.notna().sum()),
        q_positive_cash_negative=int(((panel.q > 0) & (panel.conditional_wealth_difference < 0)).sum()),
        q_decision_months=panel.loc[panel.q.notna(), 'entry_date'].str[:7].nunique(),
        selection_reasons=panel.selection_reason.value_counts().to_dict(),
        quote_reasons=panel.q_status.value_counts().to_dict(), cash_reasons=panel.cash_reason.value_counts().to_dict(),
        overlapping_labels='FIVE_SESSION_WINDOWS_OVERLAP; NOT_INDEPENDENT_TRIALS',
        interpretation='COMPLETE_CASE_DESCRIPTIONS_NOT_FULL_YEAR_POLICY_RETURN')


def run_observed(output, *, source_run=None, offline=False, reference_override=None):
    paths, output = resolve(), Path(output).resolve()
    original_root = paths.results_root/TEMPLATE/'spy2024_observed_frontier'
    continuation_root = paths.results_root/TEMPLATE/'spy2024_reference_completion'
    compat_root = paths.results_root/TEMPLATE/'spy2024_complete_compat_train'
    compat_output = output.parent.parent == compat_root and output.name in ('observed', 'observed_offline')
    require(output.parent in (original_root, continuation_root) or compat_output, 'OUTPUT_BOUNDARY')
    require(not (source_run and reference_override), 'REFERENCE_OVERRIDE_SOURCE_RUN_CONFLICT')
    new_override = reference_override is not None
    if new_override:
        override_path = Path(reference_override).resolve()
        require(compat_output and output.name == 'observed' and not output.exists() and
                override_path.parent == output.parent, 'REFERENCE_OVERRIDE_BOUNDARY')
        override = json.loads(override_path.read_bytes())
        require(override['task_id'] == COMPAT_TASK, 'REFERENCE_OVERRIDE_TASK_CHANGED')
        parent_binding = override['observed_parent']
        parent_path = Path(parent_binding['run'])/'run_manifest.json'
        require(Path(parent_binding['run']).resolve() == original_root/OBSERVED_PARENT and
                _file_digest(parent_path) == parent_binding['manifest_sha256'], 'OBSERVED_PARENT_CHANGED')
        m = json.loads(parent_path.read_bytes())
        m.update(task_id=COMPAT_TASK, status='FROZEN_BEFORE_ENTRY_SELECTION',
                 observed_parent=parent_binding, reference_additions=override['reference_additions'],
                 reference_override=dict(path=str(override_path), sha256=_file_digest(override_path)))
        m.pop('entry_lock', None)
    elif source_run is not None:
        source_run = Path(source_run).resolve()
        require(offline and source_run.parent == output.parent and not output.exists(), 'OFFLINE_NEW_OUTPUT_REQUIRED')
        m = json.loads((source_run/'run_manifest.json').read_bytes())
        require(m['status'] == 'COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC', 'SOURCE_RUN_NOT_COMPLETE')
        m['offline_source_run'] = str(source_run)
        m.pop('entry_lock', None)
    else:
        m = json.loads((output/'run_manifest.json').read_bytes())
        require(m['status'] == 'FROZEN_BEFORE_ENTRY_SELECTION' or
                (m['task_id'] == COMPAT_TASK and m['status'] == 'ENTRY_LOCKED_BEFORE_OPTION_PRICES'),
                'PRESERVE_PRIOR_RUN')
    checkpoint = m.get('entry_lock') if m['status'] == 'ENTRY_LOCKED_BEFORE_OPTION_PRICES' else None
    continuing = m['task_id'] in (CONTINUATION_TASK, COMPAT_TASK)
    require((m['task_id'] == COMPAT_TASK and compat_output) or
            (m['task_id'] == CONTINUATION_TASK and output.parent == continuation_root) or
            (m['task_id'] == TASK and output.parent == original_root and
             'reference_additions' not in m and 'observed_parent' not in m), 'OUTPUT_TASK_BOUNDARY')
    require(m['source_qualification']['grade'] == 'SOURCE_DOCUMENTED_SNAPSHOT', 'SOURCE_NOT_QUALIFIED')
    observed_parent = continuation_parent(m, paths.results_root) if continuing else None
    require(not (output/'observed_frontier.csv').exists(), 'PRESERVE_PRIOR_RESULTS')
    plan, exclusions = make_plan()
    require(plan == m['plan'] and exclusions == m['calendar_exclusions'], 'FROZEN_CALENDAR_CHANGED')
    require(_file_digest(Path(m['fee_parent_config'])) == m['fee_parent_sha256'], 'FEE_PARENT_CHANGED')
    fee_parent = json.loads(Path(m['fee_parent_config']).read_bytes())
    require(m['fees'] == fee_parent['fee_profiles'][m['fee_profile']] and m['domain'] == fee_parent['domain'], 'FROZEN_COST_DOMAIN_CHANGED')
    for doc in m['source_documents']:
        require(_file_digest(Path(doc['path'])) == doc['sha256'], 'SOURCE_DOCUMENT_CHANGED')
    parent = Path(m['parent_run'])/'run_manifest.json'
    require(_file_digest(parent) == m['parent_manifest_sha256'], 'PARENT_MANIFEST_CHANGED')
    require(m['reference_binding']['projection_dates'] == [min(r['reference_date'] for r in plan), max(r['reference_date'] for r in plan)], 'REFERENCE_DATES_CHANGED')
    references = read_references(m['reference_binding'])
    added_dates = set()
    if continuing:
        references, added_dates = add_missing_references(references, m['reference_additions'], observed_parent)
    if source_run is not None:
        output.mkdir()
    m['result_root'] = str(output)
    etf = m['source_status']['ETF_2024']; raw = Path(m['parent_cache'])/etf['file']
    require(_file_digest(raw) == etf['sha256'] and etf['commit'] == VERSION, 'OPTION_SOURCE_CHANGED')
    _, footer = inspect_parquet(raw, year=2024)
    require(footer == etf['footer'], 'OPTION_DATE_FOOTER_CHANGED')
    dataset = ds.dataset(raw, format='parquet')
    # Dates/identities first; no quote price crosses selection.
    source_dates = dataset.to_table(columns=['date']).to_pandas()['date'].value_counts()
    sessions = set(calendar().sessions.strftime('%Y-%m-%d'))
    m['non_session_source_rows'] = {str(d): int(n) for d, n in source_dates.items() if d not in sessions}
    identities = dataset.to_table(columns=IDS+[k for k in RIGHTS if k in dataset.schema.names],
        filter=ds.field('date').isin([p['entry_date'] for p in plan]) & (ds.field('type') == 'call')).to_pandas()
    if continuing:
        qualification = m['reference_additions']['qualification']
        overlap_path = Path(qualification['overlap_evidence'])
        require(_file_digest(overlap_path) == qualification['overlap_evidence_sha256'], 'OVERLAP_EVIDENCE_CHANGED')
        overlaps = json.loads(overlap_path.read_bytes())
        require([r['date'] for r in overlaps] == ['2024-09-13', '2024-09-16', '2024-09-17'], 'OVERLAP_SCOPE_CHANGED')
        parent_by_date = {r['reference_date']: r for r in observed_parent['entry_lock']['records']}
        diagnostics = []
        for overlap in overlaps:
            old, fetched = parent_by_date[overlap['date']], overlap['fetched_close']
            require(overlap['old_close'] == old['reference_close'] and overlap['old_reference_replaced'] is False,
                    'OVERLAP_PARENT_REFERENCE_CHANGED')
            diagnostic = dict(reference_date=overlap['date'], entry_date=old['entry_date'],
                parent_contract_id=old['selected_contract_id'], parent_strike=old.get('selected_strike'),
                diagnostic_contract_id=None, diagnostic_strike=None, changed=None, status='UNAVAILABLE')
            if fetched is None:
                diagnostic['reason'] = 'FETCHED_REFERENCE_UNAVAILABLE'
            elif fetched == old['reference_close']:
                diagnostic.update(status='UNCHANGED_REFERENCE', changed=False,
                    diagnostic_contract_id=old['selected_contract_id'], diagnostic_strike=old.get('selected_strike'))
            else:
                require(number_status(fetched, positive=True) == 'VALID_POSITIVE', 'OVERLAP_REFERENCE_INVALID')
                item = next(p for p in plan if p['reference_date'] == overlap['date'])
                diagnostic_ref = pd.DataFrame([dict(ticker='SPY', date=overlap['date'], close=fetched,
                    adjustment='raw', source=(qualification['provider'] if m['task_id'] == COMPAT_TASK
                                              else 'MASSIVE_CUSTOM_BARS'), currency='USD')])
                choice = select_entries([item], identities.loc[identities.date.eq(old['entry_date'])],
                                        diagnostic_ref, VERSION).iloc[0]
                if choice.selection_status == 'SELECTED' and old['selection_status'] == 'SELECTED':
                    changed = choice.selected_contract_id != old['selected_contract_id']
                    diagnostic.update(status='SELECTION_CHANGED' if changed else 'SELECTION_UNCHANGED', changed=changed,
                        diagnostic_contract_id=choice.selected_contract_id, diagnostic_strike=choice.selected_strike)
                else:
                    diagnostic['reason'] = choice.selection_reason
            diagnostics.append(diagnostic)
        m['overlap_entry_diagnostic'] = dict(records=diagnostics,
            input_scope='FIXED_OVERLAP_PRIOR_CLOSE_AND_ENTRY_IDENTITIES_ONLY', actual_references_replaced=False)
    entries = select_entries(plan, identities, references, VERSION)
    entry_records = [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in entries.to_dict('records')]
    if continuing:
        reconcile_parent_entries(entry_records, observed_parent)
    entry_raw = json.dumps(entry_records, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if checkpoint:
        require(entry_records == checkpoint['records'] and
                hashlib.sha256(entry_raw.encode()).hexdigest() == checkpoint['sha256'], 'ENTRY_CHECKPOINT_CHANGED')
    m['entry_lock'] = dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        sha256=hashlib.sha256(entry_raw.encode()).hexdigest(), records=json.loads(entry_raw),
        prices_read_before_lock='REFERENCE_CLOSE_S_ONLY; NO_OPTION_BID_ASK_OR_EXIT_INPUT')
    if checkpoint:
        m['entry_lock'] = checkpoint
    m['status'] = 'ENTRY_LOCKED_BEFORE_OPTION_PRICES'
    m['actual_loaded_sources'] = {str(paths.repo_root/name): _file_digest(paths.repo_root/name) for name in [
        'scripts/research/a2/options/spy_observed_frontier.py', 'scripts/research/a2/options/frontier.py',
        'scripts/research/a2/options/expression.py', 'scripts/research/a2/options/cli.py',
        'scripts/research/a2/options/contracts.py', 'scripts/research/a2/options/contract_continuity.py',
        'scripts/storage/storage_r2a.py', 'scripts/v22/r9a_trade_ledger.py']}
    if m['task_id'] == COMPAT_TASK:
        adapter = paths.repo_root/'scripts/research/a2/options/price_basis.py'
        m['actual_loaded_sources'][str(adapter)] = _file_digest(adapter)
    if new_override:
        output.mkdir()
    _write_json(output/'run_manifest.json', m)
    predicate = None
    for row in entries.loc[entries.selection_status.eq('SELECTED')].to_dict('records'):
        for day in (row['entry_date'], row['exit_date']):
            term = (ds.field('date') == day) & (ds.field('contract_id') == row['selected_contract_id'])
            predicate = term if predicate is None else predicate | term
    observations = dataset.to_table(columns=IDS+['bid', 'ask']+[k for k in RIGHTS if k in dataset.schema.names],
        filter=predicate if predicate is not None else ds.field('date') == '1900-01-01').to_pandas()
    panel, calls = analyse_locked(entries, observations, Fees(**m['fees']), m['domain'])
    require(len(panel) == len(plan) and panel.decision_id.is_unique, 'PLAN_DENOMINATOR_CHANGED')
    if continuing:
        m['continuation'] = continuation_summary(panel, observed_parent, m['observed_parent']['run'], added_dates)
    panel.to_csv(output/'observed_frontier.csv', index=False)
    m.update(status='COMPLETE_CONDITIONAL_ARCHIVE_DIAGNOSTIC', offline=offline,
        summary=summarize(panel), calls=calls, real_r1_evaluate_calls=0, real_r1_pairs=0,
        source_identity_rows_materialized=len(identities), source_quote_rows_materialized=len(observations),
        raw_reference_rows_materialized=len(references), option_download_requests=0, cli_network_requests=0,
        result_sha256=_file_digest(output/'observed_frontier.csv'),
        completed_at_utc=datetime.now(timezone.utc).isoformat())
    if source_run is not None:
        prior = json.loads((source_run/'run_manifest.json').read_bytes())
        require(m['result_sha256'] == prior['result_sha256'] and m['entry_lock']['sha256'] == prior['entry_lock']['sha256'], 'OFFLINE_CONTENT_CHANGED')
        m['offline_content_identical'] = True
    _write_json(output/'run_manifest.json', m)
    return {k: m[k] for k in ['status', 'summary', 'calls', 'result_sha256', 'cli_network_requests',
                            *(['continuation'] if continuing else [])]}
