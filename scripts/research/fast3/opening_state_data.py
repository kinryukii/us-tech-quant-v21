"""Compact frozen opening state and three exact endpoints; offline thin adapter."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from . import opening_data as inherited
from .stock_open_3h import DataStore, resolve, timestamps

TASK_ID = 'FAST3_OPENING_STATE_HORIZON_R1'
TICKERS = ('NVDA', 'AMD', 'AVGO', 'ENPH')
CUTOFF = pd.Timestamp('2026-01-01T00:00:00Z')
HORIZONS = {'H15': ('10:01', '10:02'), 'H60': ('10:46', '10:47'), 'H1230': ('12:30', '12:31')}
MAIN_COLUMNS = ['g', 'abs_g', 'o', 'l', 's', 'e', 'p', 'v', 'q', 'b', 'd', 'abs_d', 'a', 'sq', 'sb']
INTERACTIONS = {'ov': ('o', 'v'), 'oe': ('o', 'e'), 'o_abs_g': ('o', 'abs_g'),
                'oa': ('o', 'a'), 'dv': ('d', 'v'), 'de': ('d', 'e')}
MARKET_COLUMNS = ['q', 'b', 'sq', 'sb']
QUALITY_COLUMNS = ['quality_opening_bar_fraction', 'quality_staleness_minutes',
                   'quality_gap_unit_uncertified', 'quality_volume_unit_uncertified']
UNIT_EXCLUDED = ['g', 'abs_g', 'v', 'a', 'ov', 'o_abs_g', 'oa', 'dv']
UNIT_REASON = 'NO_COMPLETE_HISTORICAL_ASOF_SHARE_UNIT_COVERAGE'
UNIT_LEDGER = Path('D:/us-tech-quant-results/FAST_A2_R0F1_CORPORATE_ACTION_ACCOUNTING_REPAIR_AND_EXACT_R4_RERUN/corporate_action_event_manifest.parquet')
FORMULAS = {
    'g': 'log(open/previous calendar-session exact close) only with certified comparable units; unavailable class excluded',
    'abs_g': 'abs(g)', 'o': 'log1p(inherited opening_return)', 'l': 'log1p(inherited opening_return_5m)',
    's': 'inherited opening_rv=sqrt(sum(diff(log([09:31open,09:31close,...,09:44close]))**2))',
    'e': 'abs(inherited opening_efficiency); full14-bar zero path => 0',
    'p': '2*inherited opening_range_position-1; certified zero known range and exact current endpoint => 0',
    'v': 'log(current complete14-bar volume / mean previous20 true calendar-session volumes with min10 complete windows) only when positive and comparable units; unavailable class excluded',
    'q': 'log1p(inherited opening_QQQ_return)', 'b': 'log1p(inherited opening_SOXX_return)',
    'd': 'o-b', 'abs_d': 'abs(d)', 'a': 'sign(g)*sign(o)', 'sq': 'inherited opening_QQQ_rv',
    'sb': 'inherited opening_SOXX_rv',
    **{key: '*'.join(value)+'; construct before any imputation; raw missing propagation' for key, value in INTERACTIONS.items()},
}


def _log1p_valid(values):
    values = pd.to_numeric(values, errors='raise')
    return np.log1p(values.where(np.isfinite(values) & values.gt(-1)))


def compact_state(old):
    """Only inherited <=09:44 state; no endpoint price or outcome can enter X."""
    keep = ['sample_id', 'ticker', 'security_uid', 'date', 'eligible', 'eligibility_reason',
            'prediction_eligible', 'scope_four_stocks', 'prediction_at_utc', 'feature_cutoff_utc',
            'label_start_utc', 'opening_last_feature_bar_end_utc']
    x = old[[c for c in keep if c in old]].copy()
    x['g'], x['v'] = np.nan, np.nan
    x['abs_g'] = x.g.abs()
    for target, source in [('o', 'opening_return'), ('l', 'opening_return_5m'),
                           ('q', 'opening_QQQ_return'), ('b', 'opening_SOXX_return')]:
        x[target] = _log1p_valid(old[source])
    x['s'], x['sq'], x['sb'] = old.opening_rv, old.opening_QQQ_rv, old.opening_SOXX_rv
    x['e'] = old.opening_efficiency.abs()
    x['p'] = 2*old.opening_range_position-1
    zero_range = old.opening_range.eq(0) & old.opening_return.notna()
    x.loc[zero_range, 'p'] = 0.
    x['d'], x['a'] = x.o-x.b, np.sign(x.g)*np.sign(x.o)
    x['abs_d'] = x.d.abs()
    for name, (left, right) in INTERACTIONS.items():
        x[name] = x[left]*x[right]
    x[MAIN_COLUMNS+list(INTERACTIONS)] = x[MAIN_COLUMNS+list(INTERACTIONS)].replace([np.inf, -np.inf], np.nan)
    x['quality_opening_bar_fraction'] = old.opening_valid_bar_fraction
    x['quality_staleness_minutes'] = old.opening_staleness_minutes
    x['quality_gap_unit_uncertified'] = 1.
    x['quality_volume_unit_uncertified'] = 1.
    x['unit_gap_reason'], x['unit_volume_reason'] = UNIT_REASON, UNIT_REASON
    if x[UNIT_EXCLUDED].notna().any().any():
        raise ValueError('Uncertified unit-dependent feature admitted')
    return x


def read_exact_endpoints(store, files, dates):
    """Existing DataStore path guard plus Arrow exact-time/pre-2026 predicates.

    No complete minute panel is materialized. Only the four specified endpoint
    bars on already inherited exchange dates cross the Arrow/pandas boundary.
    """
    paths = [str(store._check_data_path(Path(p))) for p in files]
    dataset = ds.dataset(paths, format='parquet')
    dtype = dataset.schema.field('timestamp_utc').type
    wanted = pd.concat([timestamps(dates, clock) for clock in ['09:47', '10:01', '10:46', '12:30']]).tolist()
    expression = ((ds.field('timestamp_utc') < pa.scalar(CUTOFF, type=dtype))
                  & ds.field('timestamp_utc').isin(pa.array(wanted, type=dtype)))
    frame = dataset.to_table(columns=['symbol', 'timestamp_utc', 'open', 'high', 'low', 'close', 'volume'], filter=expression).to_pandas()
    frame['timestamp_utc'] = pd.to_datetime(frame.timestamp_utc, utc=True)
    if frame.timestamp_utc.ge(CUTOFF).any():
        raise ValueError('2026 endpoint crossed read boundary')
    return frame


def endpoint_table(frame, calendar):
    x = frame.copy()
    x['timestamp_utc'] = pd.to_datetime(x.timestamp_utc, utc=True)
    if x.timestamp_utc.ge(CUTOFF).any() or x.duplicated(['symbol', 'timestamp_utc']).any():
        raise ValueError('Invalid or duplicate endpoint timestamp')
    et = x.timestamp_utc.dt.tz_convert('America/New_York')
    x['date'], x['clock'] = et.dt.strftime('%Y-%m-%d'), et.dt.strftime('%H:%M')
    x['valid'] = inherited._valid_bar(x)
    cal = calendar.set_index('date')
    rows = []
    for (ticker, date), g in x[x.date.isin(cal.index)].groupby(['symbol', 'date'], sort=True):
        def price(clock, field):
            selected = g[g.clock.eq(clock)]
            return float(selected[field].iloc[0]) if len(selected) == 1 and selected.valid.iloc[0] else np.nan
        row = {'ticker': ticker, 'date': date, 'price_start': price('09:47', 'open')}
        for h, (end, available) in HORIZONS.items():
            row['price_end_'+h] = price(end, 'close')
            start_ok, end_ok = np.isfinite(row['price_start']), np.isfinite(row['price_end_'+h])
            label_start = timestamps([date], '09:46').iloc[0]
            label_end = timestamps([date], end).iloc[0]
            legal = cal.loc[date, 'market_open_utc'] <= label_start and cal.loc[date, 'market_close_utc'] >= label_end
            row['label_reason_'+h] = ('CALENDAR_OUTSIDE_TARGET_SESSION' if not legal else 'OK' if start_ok and end_ok else
                'MISSING_OR_INVALID_BOTH_ENDPOINTS' if not start_ok and not end_ok else
                'MISSING_OR_INVALID_START_0947' if not start_ok else 'MISSING_OR_INVALID_END_'+end.replace(':', ''))
        rows.append(row)
    return pd.DataFrame(rows)


def attach_labels(state, endpoints):
    x = state.merge(endpoints, on=['ticker', 'date'], how='left', validate='one_to_one')
    for h, (end, available) in HORIZONS.items():
        x['label_end_'+h] = timestamps(x.date, end)
        x['label_available_'+h] = timestamps(x.date, available)
        reason = 'label_reason_'+h
        x[reason] = x[reason].fillna('NO_STOCK_MINUTE_SOURCE_OR_SESSION')
        x.loc[~x.eligible, reason] = 'INELIGIBLE_AT_PREDICTION'
        good = x.prediction_eligible & x[reason].eq('OK')
        x['return_'+h] = np.where(good, x['price_end_'+h]/x.price_start-1, np.nan)
        x['y_'+h] = np.where(good, x['return_'+h].gt(0).astype(int), np.nan)
        if not x['label_available_'+h].lt(CUTOFF).all():
            raise ValueError('Label maturity boundary')
    return x


def audit_units(store, repo, start, end):
    """Narrow six-symbol metadata/event check; current-vintage is not as-of proof."""
    checked, events, ledger_records = [], [], []
    failures = (OSError, ValueError, KeyError, TypeError, sqlite3.Error, pa.ArrowException)
    def unavailable(path, role, exc):
        return {'path': str(path), 'role': role, 'status': 'UNVERIFIABLE_OPTIONAL_SOURCE',
                'error_type': type(exc).__name__, 'reason': str(exc),
                'effect': 'Maintain all eight unit-dependent columns as missing; no permission bypass or retry'}
    symbols = list(TICKERS)+['QQQ', 'SOXX']
    sql = "SELECT dataset,ticker,path,source_sha256,lineage_json FROM data_files WHERE is_current=1 AND dataset='corporate_actions_yahoo' AND ticker IN (?,?,?,?,?,?)"
    records, catalog_checked = [], False
    try:
        with sqlite3.connect(store.catalog_path.resolve().as_uri()+'?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            records = [dict(row) for row in conn.execute(sql, symbols)]
        catalog_checked = True
    except failures as exc:
        checked.append(unavailable(store.catalog_path, 'OPTIONAL_ACTION_CATALOG', exc))
    for ref in records:
        try:
            lineage = json.loads(ref['lineage_json'])
            source = inherited._check(ref['path'], ref['source_sha256'])
            safe = {k: lineage.get(k) for k in ['role', 'vintage_semantics', 'requested_start', 'requested_end', 'observed_at', 'date_column', 'identity_semantics']}
            frame = store._read_parquet(Path(ref['path']), start, end,
                ['ticker', 'event_type', 'date', 'event_timestamp_utc', 'event_json', 'observed_at'], 'date')
            splits = frame[frame.event_type.eq('splits')]
            checked.append({**source, 'ticker': ref['ticker'], 'lineage': safe, 'pre2026_event_rows': len(frame),
                            'status': 'REJECTED_AS_COMPLETE_PIT_UNIT_AUTHORITY'})
            events.extend(splits.to_dict('records'))
        except failures as exc:
            checked.append({**unavailable(ref['path'], 'OPTIONAL_PROVIDER_ACTIONS', exc), 'ticker': ref['ticker']})
    try:
        if not UNIT_LEDGER.is_file():
            raise FileNotFoundError('Existing optional event ledger not found')
        ledger = ds.dataset(str(store._check_data_path(UNIT_LEDGER)), format='parquet')
        dtype = ledger.schema.field('event_date').type
        expression = (ds.field('ticker').isin(symbols) & (ds.field('event_date') >= pa.scalar(pd.Timestamp(start), type=dtype))
                      & (ds.field('event_date') <= pa.scalar(pd.Timestamp(end), type=dtype)))
        columns = ['ticker', 'event_date', 'action_type', 'quantity_multiplier', 'source_type',
                   'source_reference', 'source_fact', 'source_fingerprint']
        ledger_records = ledger.to_table(columns=columns, filter=expression).to_pylist()
        checked.append({'path': str(UNIT_LEDGER), 'sha256': inherited.digest(UNIT_LEDGER),
                        'status': 'EVENT_SPECIFIC_SOURCE_FACTS_NOT_COMPLETE_2020_2025_ASOF_COVERAGE'})
    except failures as exc:
        ledger_records = []
        checked.append(unavailable(UNIT_LEDGER, 'OPTIONAL_EXISTING_EVENT_LEDGER', exc))
    reviewed_code = [Path(repo)/'scripts/storage/refresh_free_market.py',
                     Path(repo)/'scripts/v22/corporate_action_transition_r1.py',
                     Path(repo)/'scripts/v22/v22_062pb_fast3_corporate_action_safe_normalization_r1.py']
    code_checks = []
    for path in reviewed_code:
        try:
            code_checks.append({'path': str(path), 'sha256': inherited.digest(path)})
        except failures as exc:
            code_checks.append(unavailable(path, 'OPTIONAL_UNIT_REVIEW_CODE', exc))
    return {'status': 'UNIT_DEPENDENT_FIELD_CLASS_EXCLUDED', 'reason': UNIT_REASON,
        'symbols_checked': symbols, 'date_scope': [start, end], 'records_checked': checked,
        'provider_pre2026_split_events': events, 'existing_source_backed_event_facts': ledger_records,
        'action_catalog_query_verified': catalog_checked,
        'no_action_catalog_entry': sorted(set(symbols)-{r['ticker'] for r in records}) if catalog_checked else None,
        'reviewed_source_code': code_checks,
        'decision': 'Available current-vintage snapshots, individual event facts, or inaccessible optional records do not certify complete historical as-of absence of other actions/share-unit continuity. No-action table absence is not no-action evidence.',
        'excluded_columns': UNIT_EXCLUDED, 'excluded_for': 'all inherited prediction dates, symmetrically M0/M1',
        'repair_count': 0, 'heuristic_jump_or_ratio_repair_used': False,
        'old_normalizer_exclusion': 'V22.062PB infers factors from price jumps/allowed ratios; prohibited by this task',
        'usable_interactions': ['oe', 'de'], 'claim_limit': 'Only remaining qualified same-session interactions are tested; unavailable six-field system is not disproven',
        'no_download': True}


def build_panel(out: Path, prior_run: Path, repo: Path):
    out, prior_run, repo = Path(out), Path(prior_run), Path(repo)
    if out.exists():
        raise ValueError('Output must be a new directory')
    old_data = prior_run/'research-data'
    delivery = json.loads((prior_run/'delivery-manifest.json').read_text(encoding='utf-8'))
    sealed = {v['path']: v['sha256'] for v in delivery['artifacts']}
    checks = []
    for name in ['data_config.json', 'sources.json', 'sample_manifest.parquet']:
        checks.append(inherited._check(old_data/name, sealed['research-data/'+name]))
    old_cfg = json.loads((old_data/'data_config.json').read_text(encoding='utf-8'))
    old_sources = json.loads((old_data/'sources.json').read_text(encoding='utf-8'))
    inherited._check(old_data/'sample_manifest.parquet', old_cfg['sample_manifest_sha256'])
    original_source_ref = old_sources['inherited_sources']
    checks.append(inherited._check(original_source_ref['path'], original_source_ref['sha256']))
    original = json.loads(Path(original_source_ref['path']).read_text(encoding='utf-8'))
    store = DataStore(resolve(repo))
    old = store._read_parquet(old_data/'sample_manifest.parquet', '2020-05-01', '2025-12-31', None, 'date')
    if old.sample_id.duplicated().any() or old.ticker.nunique() != 17:
        raise ValueError('Inherited qualification population changed')
    state = compact_state(old)
    dates = sorted(old.date.unique())
    unit_audit = audit_units(store, repo, dates[0], dates[-1])
    checks.append(inherited._check(original['calendar']['path'], original['calendar']['sha256']))
    calendar = store._read_parquet(Path(original['calendar']['path']), dates[0], dates[-1],
        ['trade_date', 'market_open_utc', 'market_close_utc', 'is_session', 'is_early_close'], 'trade_date')
    calendar = calendar[calendar.is_session].rename(columns={'trade_date': 'date'})
    if sorted(calendar.date.unique()) != dates:
        raise ValueError('Inherited exchange calendar changed')
    tables = []
    for ticker in TICKERS:
        refs = [r for r in original['acquisition'] if r['ticker'] == ticker]
        for ref in refs:
            checks.append(inherited._check(ref['output']['path'], ref['output']['sha256']))
        minute = read_exact_endpoints(store, [r['output']['path'] for r in refs], dates)
        if set(minute.symbol.unique()) != {ticker}:
            raise ValueError('Endpoint source security mismatch')
        tables.append(endpoint_table(minute, calendar))
        print('Exact endpoint adaptation', ticker, len(minute), flush=True)
    full = attach_labels(state, pd.concat(tables, ignore_index=True))
    predicted = full[full.prediction_eligible].copy()
    # H1230 is exactly the prior task's target; this checks deterministic reuse,
    # not model performance and never introduces a new selection criterion.
    for newcol, oldcol in [('price_start', 'price_at_09_46'), ('price_end_H1230', 'price_at_12_30'),
                            ('return_H1230', 'return_remaining'), ('y_H1230', 'y')]:
        a = predicted.set_index('sample_id')[newcol].sort_index()
        b = old[old.prediction_eligible].set_index('sample_id')[oldcol].sort_index()
        np.testing.assert_allclose(a, b, rtol=0, atol=0, equal_nan=True)
    coverage = {'full_grid_rows': len(full), 'parent_tickers': sorted(full.ticker.unique()),
        'parent_eligible_rows': int(full.eligible.sum()), 'four_stock_prediction_rows': len(predicted),
        'prediction_dates': predicted.date.nunique(), 'per_horizon': {},
        'per_ticker': full.groupby('ticker').agg(eligible=('eligible', 'sum'), predictions=('prediction_eligible', 'sum')).reset_index().to_dict('records'),
        'missing_rates': predicted[MAIN_COLUMNS+list(INTERACTIONS)+QUALITY_COLUMNS].isna().mean().to_dict(),
        'unit_excluded_columns': UNIT_EXCLUDED}
    for h in HORIZONS:
        y, r = predicted['y_'+h], predicted['return_'+h]
        coverage['per_horizon'][h] = {'labels': int(y.notna().sum()), 'dates': predicted.loc[y.notna(), 'date'].nunique(),
            'missing_labels': int(y.isna().sum()), 'up': int(y.eq(1).sum()), 'flat': int(r.eq(0).sum()),
            'strict_down': int(r.lt(0).sum()), 'reason_counts': predicted['label_reason_'+h].value_counts().to_dict()}
    common = predicted[[f'y_{h}' for h in HORIZONS]].notna().all(axis=1)
    coverage['common_three_horizon_rows'] = int(common.sum())
    coverage['common_three_horizon_dates'] = predicted.loc[common, 'date'].nunique()
    out.mkdir(parents=True, exist_ok=False)
    full.to_parquet(out/'sample_manifest.parquet', index=False)
    predicted.to_parquet(out/'panel.parquet', index=False)
    sources = {'prior_run': str(prior_run), 'verified_reads': checks, 'unit_audit': unit_audit,
        'inherited_bar_semantics': old_sources['bar_timestamp_semantics'],
        'inherited_same_session_feature_source': {'sample_manifest_sha256': old_cfg['sample_manifest_sha256'],
            'opening_contract': old_cfg['opening_contract'], 'all_75_premarket_features_excluded': 'outside this compact fixed representation, not a finding of no value'},
        'endpoint_reader': 'existing DataStore path guard; Arrow exact-time membership and strict UTC pre2026 predicate before pandas',
        'H1230_prior_target_exact_reuse_check': 'PASS_ZERO_TOLERANCE_ALL_PREDICTION_ROWS',
        'data_root_read_only': True, 'download_calls': 0, 'supervised_fit_count': 0,
        'source_code': {'opening_state_data.py': inherited.digest(__file__), 'opening_data.py': inherited.digest(inherited.__file__)}}
    inherited.write_json(out/'sources.json', sources)
    inherited.write_json(out/'coverage.json', coverage)
    cfg = {'task_id': TASK_ID, 'main_columns': MAIN_COLUMNS, 'interaction_columns': list(INTERACTIONS),
        'quality_columns': QUALITY_COLUMNS, 'market_columns': MARKET_COLUMNS, 'horizons': HORIZONS,
        'formulas': FORMULAS, 'unit_audit': unit_audit, 'coverage': coverage,
        'quality_rule': 'Raw quality values only; modeling supplies all21 numeric missing flags equally to M0/M1 and only4 market flags to BM',
        'sample_rule': 'Four historically eligible stocks; label missingness never removes prediction rows; each horizon evaluated on its own labels',
        'main_clock': {'prediction': '09:45', 'feature_cutoff': '09:44', 'buffer_minutes': 1, 'label_start': '09:46', 'start_bar': '09:47 open'},
        'panel_sha256': inherited.digest(out/'panel.parquet'),
        'sample_manifest_sha256': inherited.digest(out/'sample_manifest.parquet'),
        'sources_sha256': inherited.digest(out/'sources.json'), 'coverage_sha256': inherited.digest(out/'coverage.json'),
        'created_before_first_fit_utc': datetime.now(timezone.utc).isoformat()}
    inherited.write_json(out/'data_config.json', cfg)
    return cfg
