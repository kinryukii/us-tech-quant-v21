"""Fixed FAST3 share-unit recovery; no market API, model fitting, or label changes."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from . import opening_data as common
from . import opening_state_data as parent_data
from .stock_open_3h import DataStore, resolve, timestamps

TASK_ID = 'FAST3_SHARE_UNIT_RECOVERY_AND_FULL_STATE_TEST_R1'
PARENT_MANIFEST_SHA256 = '248b16becdee99433be806566e5e12537091a8596aff89732e4f8e25feb2b383'
TICKERS = parent_data.TICKERS
CUTOFF = parent_data.CUTOFF
RECOVERED = parent_data.UNIT_EXCLUDED
NEW_INTERACTIONS = ['ov', 'o_abs_g', 'oa', 'dv']
QUARTERS = tuple(f'{y}Q{q}' for y in (2023, 2024, 2025) for q in (1, 2, 3, 4))
RAW_BASIS = 'RAW_OWN_DATE_SHARES'
CHANGED_COLUMNS = RECOVERED + ['quality_gap_unit_uncertified', 'quality_volume_unit_uncertified',
                             'unit_gap_reason', 'unit_volume_reason']
FIXED_AUDIT_DATES = {
    'NVDA': ['2021-01-29', '2021-07-19', '2021-07-20', '2021-07-21', '2024-06-07', '2024-06-10', '2024-06-11'],
    'AVGO': ['2021-02-12', '2024-07-12', '2024-07-15', '2024-07-16'],
    'AMD': ['2020-12-31'], 'ENPH': ['2021-01-15'],
}
NON_EVENT_AUDIT = {'NVDA': '2021-01-29', 'AVGO': '2021-02-12', 'AMD': '2020-12-31', 'ENPH': '2021-01-15'}


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def canonical_events(records):
    """Accept explicit pure events once; ignore cash, never affine price factors."""
    events, seen = [], {}
    for item in records:
        event = dict(item)
        if event['event_type'] == 'CASH_DIVIDEND':
            continue
        if event['event_type'] not in ('PURE_FORWARD_SPLIT', 'PURE_REVERSE_SPLIT'):
            raise ValueError('Uncertified complex share action')
        effective = pd.Timestamp(event['event_effective_time_UTC'])
        available = pd.Timestamp(event['historically_available_by_UTC'])
        if effective.tzinfo is None or available.tzinfo is None:
            raise ValueError('Share action requires explicit timezones')
        r = float(event['new_shares_per_old_share'])
        if not np.isfinite(r) or r <= 0:
            raise ValueError('Invalid share ratio')
        key = (event['ticker'], effective.isoformat(), event['event_type'])
        if key in seen:
            if seen[key] != r:
                raise ValueError('Conflicting duplicate share event')
            continue
        seen[key] = r
        event.update(event_effective_time_UTC=effective.tz_convert('UTC'),
                     historically_available_by_UTC=available.tz_convert('UTC'))
        events.append(event)
    return sorted(events, key=lambda x: (x['ticker'], x['event_effective_time_UTC']))


def share_factor(events, ticker, historical_time, decision_time):
    """Only already effective, already knowable events between the two units."""
    s, d = pd.Timestamp(historical_time), pd.Timestamp(decision_time)
    if s.tzinfo is None or d.tzinfo is None or s > d or d >= CUTOFF:
        raise ValueError('Invalid historical share-unit interval')
    k = 1.
    for event in canonical_events(events):
        effective = event['event_effective_time_UTC']
        if event['ticker'] != ticker or effective >= CUTOFF or not (s < effective <= d):
            continue
        if event['historically_available_by_UTC'] > d:
            raise ValueError('Action was not knowable at decision')
        k *= event['new_shares_per_old_share']
    return k


def map_units(price, volume, factor, price_basis=RAW_BASIS, volume_basis=RAW_BASIS):
    """Price and volume bases are independent; already mapped values stay mapped."""
    if not np.isfinite(factor) or factor <= 0:
        raise ValueError('Invalid conversion factor')
    allowed = {RAW_BASIS, 'DECISION_SHARE_UNITS'}
    if price_basis not in allowed or volume_basis not in allowed:
        raise ValueError('Unbound or incompatible price/volume source units')
    return (price / factor if price_basis == RAW_BASIS else price,
            volume * factor if volume_basis == RAW_BASIS else volume)


def load_unit_evidence(directory, calendar):
    directory = Path(directory)
    binding = _json(directory/'source_binding.json')
    official = _json(directory/'official_unit_semantics.json')
    checks = [common._check(directory/'scoped_rehab_events.parquet', binding['scoped_output_sha256'])]
    for name in ['source_binding.json', 'official_unit_semantics.json', 'scoped_original_query_status.csv']:
        checks.append({'path': str(directory/name), 'sha256': common.digest(directory/name)})
    status = pd.read_csv(directory/'scoped_original_query_status.csv')
    if status.code.duplicated().any() or set(status.code) != {'US.'+t for t in TICKERS} or not status.status.eq('PASS').all():
        raise ValueError('Missing successful full-history source response')
    if binding['status'] != 'EXISTING_SUCCESSFUL_FULL_HISTORY_CACHE_REUSED':
        raise ValueError('Unexpected unit source binding')
    dataset = ds.dataset(str(directory/'scoped_rehab_events.parquet'), format='parquet')
    data = dataset.to_table(filter=(ds.field('code').isin(['US.'+t for t in TICKERS])
        & (ds.field('ex_div_date') >= '2020-12-31') & (ds.field('ex_div_date') < '2026-01-01'))).to_pandas()
    if len(data) != sum(r['retained_rows'] for r in binding['cached_response_counts']):
        raise ValueError('Scoped event count differs from full-response lineage')
    if data.duplicated(['code', 'ex_div_date']).any():
        raise ValueError('Multiple unclassified source records on event date')
    complex_fields = ['per_share_div_ratio', 'per_share_trans_ratio', 'allotment_ratio', 'stk_spo_ratio', 'spin_off_ratio']
    if any(pd.to_numeric(data[c], errors='raise').fillna(0).ne(0).any() for c in complex_fields):
        raise ValueError('Complex action requires explicit local isolation; automatic share mapping refused')
    real = data[data.split_ratio.notna() & data.split_ratio.ne(0) & data.split_ratio.ne(1)]
    evidence = {(x['ticker'], x['event_effective_date']): x for x in official['events']}
    calendar = calendar.set_index('date')
    events = []
    for row in real.to_dict('records'):
        ticker, date = row['code'].removeprefix('US.'), row['ex_div_date']
        item = dict(evidence[(ticker, date)])
        factor = 1 / float(row['split_ratio'])
        if factor != item['new_shares_per_old_share'] or row['split_ratio'] != item['expected_provider_split_ratio']:
            raise ValueError('Official/source ratio direction conflict')
        if pd.notna(row['split_base']) and pd.notna(row['split_ert']) and row['split_base'] > 0:
            if row['split_ert']/row['split_base'] != factor:
                raise ValueError('Conflicting duplicate ratio fields')
        if pd.Timestamp(item['event_effective_time_UTC']) != pd.Timestamp(calendar.loc[date, 'market_open_utc']):
            raise ValueError('Official implementation is not actual regular market open')
        item['historically_available_by_UTC'] = pd.Timestamp(
            item['conservative_historically_available_by_date_NY'], tz='America/New_York').tz_convert('UTC')
        item['source_reference'] = [item['source_url'], str(directory/'scoped_rehab_events.parquet')]
        item['source_split_ratio'] = row['split_ratio']
        item['cash_same_record_excluded'] = None if pd.isna(row['per_cash_div']) else float(row['per_cash_div'])
        events.append(item)
    if {(x['ticker'], x['event_effective_date']) for x in events} != set(evidence):
        raise ValueError('Provider and official event set differ')
    return canonical_events(events), {'binding': binding, 'official': official, 'verified_reads': checks,
        'cash_only_rows_ignored': len(data)-len(real), 'pure_share_events': events,
        'absence_scope': 'Successful full provider response, source-conditional absence; not universal no-action proof',
        'price_unit_basis': RAW_BASIS, 'volume_unit_basis': RAW_BASIS,
        'revision_limit': 'Limited historical share-unit certification; original downloaded OHLCV revision vintage remains 2026'}


def read_needed_minutes(store, refs, calendar, prediction_dates):
    dates = calendar.date.tolist()
    indices = [dates.index(d) for d in prediction_dates]
    first = max(0, min(indices)-20)
    wanted_dates = dates[first:max(indices)+1]
    history_calendar = calendar[calendar.date.isin(wanted_dates)].copy()
    previous_dates = {dates[i-1] for i in indices if i > 0}
    files = [r['output']['path'] for r in refs]
    paths = [str(store._check_data_path(Path(p))) for p in files]
    dataset = ds.dataset(paths, format='parquet')
    dtype = dataset.schema.field('timestamp_utc').type
    opening_times = pd.concat([timestamps(wanted_dates, f'09:{m}') for m in range(31, 45)]).tolist()
    close_times = pd.to_datetime(calendar.loc[calendar.date.isin(previous_dates), 'market_close_utc'], utc=True).tolist()
    expression = ((ds.field('timestamp_utc') < pa.scalar(CUTOFF, type=dtype))
                  & ds.field('timestamp_utc').isin(pa.array(opening_times+close_times, type=dtype)))
    frame = dataset.to_table(columns=['symbol', 'timestamp_utc', 'open', 'high', 'low', 'close', 'volume',
                                     'turnover', 'source', 'adjustment_type'], filter=expression).to_pandas()
    frame['timestamp_utc'] = pd.to_datetime(frame.timestamp_utc, utc=True)
    if frame.timestamp_utc.ge(CUTOFF).any() or frame.duplicated(['symbol', 'timestamp_utc']).any():
        raise ValueError('Invalid minute read boundary or duplicate source bars')
    if not frame.source.eq('moomoo_opend').all() or not frame.adjustment_type.eq('NONE').all():
        raise ValueError('Mixed minute source or price-adjustment basis')
    return frame, history_calendar


def raw_binding_audit(store, refs, ticker):
    dates = FIXED_AUDIT_DATES[ticker]
    selected = [r for r in refs if any(r['item']['start'] <= d <= r['item']['end'] for d in dates)]
    clocks = [f'09:{m:02}' for m in range(31, 45)]+['16:00']
    keys = [d+' '+c+':00' for d in dates for c in clocks]
    raw_paths = [str(store._check_data_path(Path(r['raw']['path']))) for r in selected]
    raw = ds.dataset(raw_paths, format='parquet').to_table(
        filter=ds.field('time_key').isin(keys), columns=['code', 'time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover']).to_pandas()
    raw['timestamp_utc'] = pd.to_datetime(raw.time_key).dt.tz_localize('America/New_York').dt.tz_convert('UTC').astype('datetime64[ns, UTC]')
    normalized = ds.dataset([str(store._check_data_path(Path(r['output']['path']))) for r in selected], format='parquet')
    dtype = normalized.schema.field('timestamp_utc').type
    norm = normalized.to_table(filter=ds.field('timestamp_utc').isin(pa.array(raw.timestamp_utc.tolist(), type=dtype)),
        columns=['timestamp_utc', 'open', 'high', 'low', 'close', 'volume', 'turnover']).to_pandas()
    norm['timestamp_utc'] = pd.to_datetime(norm.timestamp_utc, utc=True).astype('datetime64[ns, UTC]')
    if len(raw) != len(keys) or raw.timestamp_utc.duplicated().any() or norm.timestamp_utc.duplicated().any():
        raise ValueError('Fixed unit audit has missing/duplicate source bars')
    if not raw.code.eq('US.'+ticker).all():
        raise ValueError('Fixed source audit identity mismatch')
    columns = ['open', 'high', 'low', 'close', 'volume', 'turnover']
    pd.testing.assert_frame_equal(raw.set_index('timestamp_utc')[columns].sort_index(),
        norm.set_index('timestamp_utc')[columns].sort_index(), check_dtype=False, check_exact=True)
    raw['ticker'] = ticker
    raw['turnover_per_volume'] = raw.turnover/raw.volume
    raw['strict_inside_ohlc'] = raw.turnover_per_volume.ge(raw.low) & raw.turnover_per_volume.le(raw.high)
    raw['ohlc_boundary_difference'] = np.maximum(raw.turnover_per_volume-raw.high, 0)+np.minimum(raw.turnover_per_volume-raw.low, 0)
    raw['boundary_difference_bps'] = raw.ohlc_boundary_difference/((raw.high+raw.low)/2)*10000
    raw['audit_role'] = np.where(raw.time_key.str[:10].eq(NON_EVENT_AUDIT[ticker]), 'FIXED_NON_EVENT', 'ALL_RELEVANT_SPLIT_SIDES')
    if not raw.loc[raw.audit_role.eq('ALL_RELEVANT_SPLIT_SIDES'), 'strict_inside_ohlc'].all():
        raise ValueError('Split-side volume dimensional consistency conflicts with raw price basis')
    return raw


def summarize_unit_inputs(frame, calendar):
    """Complete opening volume and exact regular close, with all calendar holes."""
    x = frame.copy()
    x['timestamp_utc'] = pd.to_datetime(x.timestamp_utc, utc=True)
    if x.timestamp_utc.ge(CUTOFF).any() or x.duplicated(['symbol', 'timestamp_utc']).any():
        raise ValueError('Minute boundary/identity violation')
    et = x.timestamp_utc.dt.tz_convert('America/New_York')
    x['date'], x['minute'] = et.dt.strftime('%Y-%m-%d'), et.dt.hour*60+et.dt.minute
    x['valid'] = common._valid_bar(x)
    cal = calendar.set_index('date')
    rows = []
    for date in calendar.date:
        bars = x[x.date.eq(date)]
        window = bars[bars.minute.between(571, 584) & bars.valid]
        opening = bars[bars.minute.eq(571) & bars.valid]
        close = bars[bars.timestamp_utc.eq(cal.loc[date, 'market_close_utc']) & bars.valid]
        rows.append({'date': date, 'opening_price': float(opening.open.iloc[0]) if len(opening)==1 else np.nan,
            'window_volume': float(window.volume.sum()) if len(window)==14 else np.nan,
            'regular_close': float(close.close.iloc[0]) if len(close)==1 else np.nan,
            'valid_opening_bars': len(window), 'regular_close_utc': cal.loc[date, 'market_close_utc'],
            'opening_unit_time_utc': cal.loc[date, 'market_open_utc']})
    return pd.DataFrame(rows)


def recover_ticker(predictions, inputs, events):
    inputs = inputs.set_index('date')
    dates = inputs.index.tolist()
    rows = []
    for row in predictions.itertuples():
        i = dates.index(row.date)
        current = inputs.loc[row.date]
        record = {'sample_id': row.sample_id, 'ticker': row.ticker, 'date': row.date, 'g': np.nan, 'v': np.nan,
                  'g_certified': True, 'v_certified': True, 'g_reason': 'OK', 'v_reason': 'OK',
                  'history_calendar_sessions': min(i, 20), 'history_valid_windows': 0,
                  'previous_close_factor': np.nan, 'raw_previous_close': np.nan, 'mapped_previous_close': np.nan,
                  'raw_opening_price': current.opening_price, 'raw_window_volume': current.window_volume}
        if i == 0:
            record['g_reason'] = 'NO_PREVIOUS_CALENDAR_SESSION'
        else:
            prior = inputs.iloc[i-1]
            k = share_factor(events, row.ticker, prior.regular_close_utc, row.prediction_at_utc)
            mapped, _ = map_units(prior.regular_close, np.nan, k)
            record.update(previous_close_factor=k, raw_previous_close=prior.regular_close, mapped_previous_close=mapped)
            if np.isfinite(current.opening_price) and np.isfinite(mapped) and mapped > 0:
                record['g'] = float(np.log(current.opening_price/mapped))
            else:
                record['g_reason'] = 'MISSING_OR_INVALID_EXACT_OPEN_OR_PREVIOUS_SESSION_CLOSE'
        history = inputs.iloc[max(0, i-20):i]
        mapped_volumes = []
        for past in history.itertuples():
            if not np.isfinite(past.window_volume):
                continue
            k = share_factor(events, row.ticker, past.opening_unit_time_utc, row.prediction_at_utc)
            _, volume = map_units(np.nan, past.window_volume, k)
            mapped_volumes.append(volume)
        record['history_valid_windows'] = len(mapped_volumes)
        record['mapped_history_mean_volume'] = float(np.mean(mapped_volumes)) if mapped_volumes else np.nan
        if not np.isfinite(current.window_volume):
            record['v_reason'] = 'MISSING_OR_INVALID_CURRENT_COMPLETE14_WINDOW'
        elif len(mapped_volumes) < 10:
            record['v_reason'] = 'FEWER_THAN_10_VALID_WINDOWS_IN_PREVIOUS20_CALENDAR_SESSIONS'
        else:
            record['v'] = float(np.log(current.window_volume/np.mean(mapped_volumes)))
        rows.append(record)
    return pd.DataFrame(rows)


def core_gate(panel, audit):
    if (panel.sample_id.duplicated().any() or audit.sample_id.duplicated().any()
            or len(panel) != len(audit) or set(panel.sample_id) != set(audit.sample_id)):
        raise ValueError('Unit certification rows differ from original prediction denominator')
    x = panel.merge(audit[['sample_id', 'g_certified', 'v_certified']], on='sample_id', how='left', validate='one_to_one')
    x['joint'] = x.g_certified & x.v_certified & np.isfinite(x.g) & np.isfinite(x.v)
    periods = pd.PeriodIndex(x.date, freq='Q').astype(str)
    quarters = []
    for ticker in TICKERS:
        for quarter in QUARTERS:
            sub = x[x.ticker.eq(ticker) & (periods == quarter)]
            ratio = float(sub.joint.mean()) if len(sub) else None
            quarters.append({'ticker': ticker, 'quarter': quarter, 'eligible_prediction_rows': len(sub),
                'g_v_joint_rows': int(sub.joint.sum()), 'g_v_joint_fraction': ratio,
                'status': 'N/A_NO_HISTORICALLY_ELIGIBLE_ROWS' if ratio is None else 'PASS' if ratio >= .9 else 'FAIL'})
    folds = []
    for quarter in (*QUARTERS, 'FINAL'):
        boundary = CUTOFF if quarter == 'FINAL' else pd.Timestamp(pd.Period(quarter, freq='Q').start_time, tz='UTC')
        for h in parent_data.HORIZONS:
            train = panel[panel['y_'+h].notna() & panel['label_available_'+h].lt(min(boundary, CUTOFF))]
            row = {'quarter': quarter, 'horizon': h, 'train_rows': len(train), 'train_dates': train.date.nunique(), 'interactions': {}}
            for column in NEW_INTERACTIONS:
                values = train.loc[np.isfinite(train[column]), column]
                row['interactions'][column] = {'finite_rows': len(values), 'unique_values': values.nunique(),
                    'variance': float(values.var(ddof=0)) if len(values) else None,
                    'status': 'PASS' if len(values) and values.nunique()>1 and values.var(ddof=0)>0 else 'FAIL'}
            row['status'] = 'PASS' if row['train_dates']>=180 and all(v['status']=='PASS' for v in row['interactions'].values()) else 'FAIL'
            folds.append(row)
    passed = all(r['status'] != 'FAIL' for r in quarters) and all(r['status']=='PASS' for r in folds)
    return {'status': 'PASS' if passed else 'FAIL', 'minimum_joint_fraction': .9,
        'denominator': 'unchanged original historically eligible prediction rows; independent of all horizon labels',
        'stock_quarter': quarters, 'training_folds': folds,
        'full_state_test': 'READY_FOR_FROZEN_FULL_SIX_INTERACTION_STUDY' if passed else 'NOT_RUN_INPUT_GAP'}


def apply_recovery(full, audit):
    result = full.copy()
    joined = audit.set_index('sample_id').reindex(result.sample_id)
    scope = result.prediction_eligible.to_numpy()
    for column in ('g', 'v'):
        result.loc[scope, column] = joined.loc[result.loc[scope, 'sample_id'], column].to_numpy()
        result.loc[scope, 'unit_'+('gap' if column=='g' else 'volume')+'_reason'] = joined.loc[result.loc[scope, 'sample_id'], column+'_reason'].to_numpy()
        certified = joined.loc[result.loc[scope, 'sample_id'], column+'_certified']
        if certified.isna().any():
            raise ValueError('Missing unit certification for eligible prediction')
        result.loc[scope, 'quality_'+('gap' if column=='g' else 'volume')+'_unit_uncertified'] = (~certified.astype(bool)).astype(float).to_numpy()
    result['abs_g'] = result.g.abs()
    result['a'] = np.sign(result.g)*np.sign(result.o)
    for name in NEW_INTERACTIONS:
        left, right = parent_data.INTERACTIONS[name]
        result[name] = result[left]*result[right]
    unchanged = [c for c in full.columns if c not in CHANGED_COLUMNS]
    pd.testing.assert_frame_equal(result[unchanged], full[unchanged], check_exact=True)
    if len(result) != len(full) or result.sample_id.duplicated().any():
        raise ValueError('Recovery changed original prediction identity')
    return result


def build_panel(out, parent_run, repo, unit_evidence_path):
    out, parent_run, repo = Path(out), Path(parent_run), Path(repo)
    if out.exists():
        raise ValueError('Recovery output must be a new directory')
    directory = parent_run/'research-data'
    parent_check = common._check(parent_run/'delivery-manifest.json', PARENT_MANIFEST_SHA256)
    sealed = {x['path']: x['sha256'] for x in _json(parent_run/'delivery-manifest.json')['artifacts']}
    checks = [parent_check]+[common._check(directory/name, sealed['research-data/'+name])
              for name in ('data_config.json', 'sources.json', 'sample_manifest.parquet', 'panel.parquet')]
    config, lineage = _json(directory/'data_config.json'), _json(directory/'sources.json')
    old_opening_sources = _json(Path(lineage['prior_run'])/'research-data/sources.json')
    ref = old_opening_sources['inherited_sources']
    checks.append(common._check(ref['path'], ref['sha256']))
    source = _json(ref['path'])
    store = DataStore(resolve(repo))
    full = store._read_parquet(directory/'sample_manifest.parquet', '2020-05-01', '2025-12-31', None, 'date')
    original_predictions = store._read_parquet(directory/'panel.parquet', '2020-05-01', '2025-12-31', None, 'date')
    pd.testing.assert_frame_equal(full[full.prediction_eligible].reset_index(drop=True), original_predictions.reset_index(drop=True), check_exact=True)
    if full.ticker.nunique()!=17 or set(original_predictions.ticker)!=set(TICKERS) or full.sample_id.duplicated().any():
        raise ValueError('Original historical qualification population drift')
    checks.append(common._check(source['calendar']['path'], source['calendar']['sha256']))
    calendar = store._read_parquet(Path(source['calendar']['path']), full.date.min(), full.date.max(),
        ['trade_date', 'market_open_utc', 'market_close_utc', 'is_session', 'is_early_close'], 'trade_date')
    calendar = calendar[calendar.is_session].rename(columns={'trade_date': 'date'}).sort_values('date')
    events, unit_evidence = load_unit_evidence(unit_evidence_path, calendar)
    acquisition_ref = source['acquisition_report']
    checks.append(common._check(acquisition_ref['frozen_path'], acquisition_ref['sha256']))
    acquisition = _json(acquisition_ref['frozen_path'])
    ingest = 'scripts/v22/v22_049_fast3_six_etf_24h_minute_data_ingest_r1.py'
    checks.append(common._check(repo/ingest, acquisition['source_code_sha256'][ingest]))
    audits, summaries, bindings, scopes = [], [], [], []
    for ticker in TICKERS:
        selected = original_predictions[original_predictions.ticker.eq(ticker)]
        idx = calendar.date.tolist().index(selected.date.min())
        start = calendar.date.iloc[max(0, idx-20)]
        refs = [r for r in source['acquisition'] if r['ticker']==ticker and r['item']['end']>=start
                and r['item']['start']<=selected.date.max()]
        for ref in refs:
            if ref['contract'] != {'adjustment': 'NONE', 'extended_time': False, 'frequency': 'K_1M',
                                   'native_timestamp_timezone': 'America/New_York', 'session': 'ALL'}:
                raise ValueError('Source request adjustment/session contract changed')
            checks.append(common._check(ref['manifest'], ref['manifest_sha256']))
            for kind in ('raw', 'output'):
                checks.append(common._check(ref[kind]['path'], ref[kind]['sha256']))
        bindings.append(raw_binding_audit(store, refs, ticker))
        frame, cal = read_needed_minutes(store, refs, calendar, selected.date.tolist())
        if set(frame.symbol.unique()) != {ticker}:
            raise ValueError('Source identity mismatch')
        summarized = summarize_unit_inputs(frame, cal)
        summaries.append(summarized.assign(ticker=ticker))
        audits.append(recover_ticker(selected, summarized, events))
        scopes.append({'ticker': ticker, 'first_prediction': selected.date.min(), 'last_prediction': selected.date.max(),
            'necessary_prior20_start': start, 'calendar_sessions': len(cal), 'minute_bars_read': len(frame),
            'history_rule': 'Previous20 true sessions, min10 complete14-bar windows; exact prior-session close including13:00 early close'})
        print('Share-unit recovery', ticker, len(selected), len(frame), flush=True)
    audit = pd.concat(audits, ignore_index=True)
    binding_bars = pd.concat(bindings, ignore_index=True)
    recovered = apply_recovery(full, audit)
    # New descriptive metadata only; no pre-existing non-recovery column changes.
    recovered['data_quality'] = np.where(~recovered.prediction_eligible, 'OUTSIDE_ORIGINAL_PREDICTION_SCOPE',
        np.where(np.isfinite(recovered.g) & np.isfinite(recovered.v),
            'SOURCE_BOUND_SHARE_UNITS;G_V_AVAILABLE', 'SOURCE_BOUND_SHARE_UNITS;LOCAL_INPUT_MISSING'))
    predicted = recovered[recovered.prediction_eligible].copy()
    gate = core_gate(predicted, audit)
    unit_evidence.update(status='SOURCE_BOUND_RAW_PRICE_AND_VOLUME_WITH_DOCUMENTED_AGGREGATION_LIMIT',
        field_source_audit={'bars': len(binding_bars), 'raw_normalized_exact_equal': True,
            'strict_vwap_inside_ohlc': int(binding_bars.strict_inside_ohlc.sum()),
            'deviations_preserved': int((~binding_bars.strict_inside_ohlc).sum()),
            'tolerance_reclassification': False,
            'interpretation': 'NONE quantity/price contract, frozen actual request, exact field passthrough and all fixed split-side native-price consistency jointly support own-date share units; non-event aggregate deviations are retained, not converted or filtered'},
        current_fit_count=0, new_market_requests=0, ledger_permission_denial_not_retried=True,
        source_scopes=scopes, recovery_columns=RECOVERED)
    coverage = dict(config['coverage'])
    coverage.update(missing_rates=predicted[parent_data.MAIN_COLUMNS+list(parent_data.INTERACTIONS)+parent_data.QUALITY_COLUMNS].isna().mean().to_dict(),
        unit_excluded_columns=[], restored_columns=RECOVERED, core_input_gate=gate)
    out.mkdir(parents=True, exist_ok=False)
    recovered.to_parquet(out/'sample_manifest.parquet', index=False)
    predicted.to_parquet(out/'panel.parquet', index=False)
    audit.to_parquet(out/'unit_recovery_rows.parquet', index=False)
    binding_bars.to_parquet(out/'unit_source_bar_audit.parquet', index=False)
    pd.concat(summaries, ignore_index=True).to_parquet(out/'unit_input_daily.parquet', index=False)
    common.write_json(out/'coverage.json', coverage)
    common.write_json(out/'sources.json', {'parent_result_root': str(parent_run), 'verified_reads': checks,
        'unit_evidence': unit_evidence, 'bar_semantics': lineage['inherited_bar_semantics'],
        'unchanged_columns_exact': [c for c in full.columns if c not in CHANGED_COLUMNS],
        'unchanged_invariant': 'All original labels, qualification, IDs, clocks, other main effects and oe/de exact',
        'old_source_exclusion_mapping': {field: {'actual_parent_code': 'compact_state sets g/v NaN, dependent formulas propagate',
            'parent_reason': parent_data.UNIT_REASON, 'categories': ['A_UNCONSUMED_EXISTING_METADATA', 'E_UNBOUND_SOURCE_UNITS', 'F_OPTIONAL_LEDGER_DENIED'],
            'affected_original_prediction_rows': int(original_predictions[field].isna().sum()),
            'recovered_finite_rows': int(np.isfinite(predicted[field]).sum())} for field in RECOVERED},
        'source_code': {'share_unit_data.py': common.digest(__file__)}, 'data_root_read_only': True})
    config.update(task_id=TASK_ID, parent_result_root=str(parent_run), unit_audit=unit_evidence,
        parent_manifest_sha256=PARENT_MANIFEST_SHA256,
        data_quality='SOURCE_BOUND_SHARE_UNITS;ROW_LOCAL_AVAILABILITY_REPORTED',
        core_input_gate=gate, coverage=coverage, unit_recovery_status='RECOVERED' if gate['status']=='PASS' else 'PARTIAL',
        main_columns=parent_data.MAIN_COLUMNS, interaction_columns=list(parent_data.INTERACTIONS),
        formulas={**config['formulas'], 'g': 'log(exact09:31open / exact previous calendar close divided by K)',
            'v': 'log(complete14-bar volume / mean(previous20 true-session complete volumes multiplied by respective K), min10)',
            'a': 'sign(g)*sign(o)', 'abs_g': 'abs(g)'},
        panel_sha256=common.digest(out/'panel.parquet'), sample_manifest_sha256=common.digest(out/'sample_manifest.parquet'),
        sources_sha256=common.digest(out/'sources.json'), coverage_sha256=common.digest(out/'coverage.json'))
    common.write_json(out/'data_config.json', config)
    return config
