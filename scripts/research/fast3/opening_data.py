"""Thin offline data adapter for the fixed FAST3 09:45 information study.

The old frozen complete sample manifest owns eligibility and the 75 A values.
Only the new endpoint label and the explicitly enumerated 18 opening fields are
constructed here. Source bytes and the prior experiment are never rewritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

TASK_ID = 'FAST3_STOCK_0945_INFORMATION_ALGORITHM_STUDY_R1'
TICKERS = ['NVDA', 'AMD', 'AVGO', 'ENPH']
CUTOFF = pd.Timestamp('2026-01-01T00:00:00Z')
OPENING_COLUMNS = [
    'opening_gap', 'opening_return', 'opening_return_5m', 'opening_rv',
    'opening_range', 'opening_range_position', 'opening_efficiency',
    'opening_drawdown', 'opening_relative_volume', 'opening_last5_volume_share',
    'opening_QQQ_return', 'opening_SOXX_return', 'opening_relative_QQQ_return',
    'opening_relative_SOXX_return', 'opening_QQQ_rv', 'opening_SOXX_rv',
    'opening_staleness_minutes', 'opening_valid_bar_fraction',
]
MARKET_OPENING_COLUMNS = ['opening_QQQ_return', 'opening_SOXX_return',
                          'opening_QQQ_rv', 'opening_SOXX_rv']
OPENING_CONTRACT = {
    'prediction_time': '09:45', 'feature_bar_end_cutoff': '09:44',
    'feature_availability_buffer_minutes': 1,
    'label_start_time': '09:46', 'label_start_bar': '09:47 open',
    'label_end_time': '12:30', 'label_end_bar': '12:30 close',
    'label_available_time': '12:31', 'timezone': 'America/New_York',
    'window': '14 exact END-labelled bars 09:31..09:44 inclusive',
    'valid_bar': 'finite positive coherent OHLC and finite volume > 0',
    'current_price': 'exact 09:44 close; never carry forward a missing endpoint',
    'previous_close': 'exact real calendar close of immediately preceding trading day, including half days; no skip over missing dates',
    'path': 'P=(09:31 open,09:31 close,...,09:44 close); r=diff(log(P)); all 14 valid bars required for rv/efficiency/volume fields',
    'range': 'high/low of available valid W bars; range/open requires valid 09:31 open; position/drawdown require exact 09:44 close and known high/low, independently of opening-bar availability',
    'volume_history': 'mean of complete-window volumes in exactly previous 20 exchange sessions, min 10 nonmissing; missing sessions remain inside window',
    'zero_denominator': 'NaN except efficiency=0 for a complete constant-price path',
    'missing': 'field-local NaN; no feature-completeness row filtering; no daily/ETF/next-price endpoint replacement',
    'formulas': dict(zip(OPENING_COLUMNS, [
        'open_0930 / previous_session_exact_close - 1',
        'close_0944 / open_0930 - 1', 'close_0944 / close_0939 - 1',
        'sqrt(sum(r*r))', '(known_high-known_low)/open_0930',
        '(close_0944-known_low)/(known_high-known_low)',
        'log(close_0944/open_0930)/sum(abs(r)); zero path => 0',
        'close_0944/known_high-1', 'complete_W_volume / past_20_session_mean_W_volume',
        'sum(volume ends 09:40..09:44)/complete_W_volume',
        'QQQ close_0944/open_0930-1', 'SOXX close_0944/open_0930-1',
        'opening_return-opening_QQQ_return', 'opening_return-opening_SOXX_return',
        'QQQ sqrt(sum(r*r))', 'SOXX sqrt(sum(r*r))',
        '(09:44-last_valid_W_bar_end) in minutes; no W bar => NaN',
        'valid_W_bar_count/14; no W bar => 0',
    ])),
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                                   default=str, allow_nan=False), encoding='utf-8')


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _check(path, expected):
    actual = digest(path)
    if actual != expected:
        raise ValueError('Frozen source hash mismatch: ' + str(path))
    return {'path': str(path), 'sha256': actual}


def _old_module(repo):
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    path = Path(repo) / 'scripts/research/fast3/stock_open_3h.py'
    spec = importlib.util.spec_from_file_location('fast3_0945_inherited_entry', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_minute_read(store, files):
    """Existing DataStore predicate is applied before pandas materialization."""
    result = store._read_parquet([Path(p) for p in files], '2020-05-01T00:00:00Z',
        '2025-12-31T23:59:59.999999999Z',
        ['symbol', 'timestamp_utc', 'open', 'high', 'low', 'close', 'volume'], 'timestamp_utc')
    if len(result) and (pd.to_datetime(result.timestamp_utc, utc=True) >= CUTOFF).any():
        raise ValueError('Read boundary allowed a 2026 minute')
    return result


def _valid_bar(g):
    p = g[['open', 'high', 'low', 'close']].astype(float)
    return (np.isfinite(p).all(axis=1) & p.gt(0).all(axis=1)
            & np.isfinite(g.volume) & g.volume.gt(0)
            & p.high.ge(p[['open', 'close', 'low']].max(axis=1))
            & p.low.le(p[['open', 'close', 'high']].min(axis=1)))


def _exact(g, minute, column):
    z = g[g.m.eq(minute)]
    return float(z[column].iloc[0]) if len(z) == 1 and bool(z.valid.iloc[0]) else np.nan


def summarize_minutes(frame, calendar):
    """One symbol/day summary. No future bar participates in opening fields.

    Calendar has date, market_open_utc and market_close_utc, already filtered to
    pre-2026 exchange sessions. Rows for wholly absent sessions are reintroduced
    before lag or rolling operations, so 20 sessions never means 20 observations.
    """
    x = frame.copy()
    if x.empty:
        return pd.DataFrame()
    x['timestamp_utc'] = pd.to_datetime(x.timestamp_utc, utc=True)
    if x.timestamp_utc.ge(CUTOFF).any():
        raise ValueError('2026 timestamp reached opening summary')
    if x.duplicated(['symbol', 'timestamp_utc']).any():
        raise ValueError('Duplicate minute keys')
    et = x.timestamp_utc.dt.tz_convert('America/New_York')
    x['date'], x['m'] = et.dt.strftime('%Y-%m-%d'), et.dt.hour * 60 + et.dt.minute
    x['valid'] = _valid_bar(x)
    x = x.sort_values('timestamp_utc')
    cal = calendar.set_index('date')
    dates = sorted(cal.index)
    close_minutes = pd.to_datetime(cal.market_close_utc, utc=True).dt.tz_convert('America/New_York')
    close_minutes = (close_minutes.dt.hour * 60 + close_minutes.dt.minute).to_dict()
    rows = []
    for (ticker, date), g in x[x.date.isin(dates)].groupby(['symbol', 'date'], sort=True):
        close_m = close_minutes[date]
        row = {'ticker': ticker, 'date': date,
               '_regular_close': _exact(g, close_m, 'close'),
               '_opening_price': _exact(g, 571, 'open'),
               'price_at_09_46': _exact(g, 587, 'open'),
               'price_at_12_30': _exact(g, 750, 'close'),
               '_window_volume': np.nan,
               'opening_last_feature_bar_end_utc': pd.NaT,
               **dict.fromkeys(OPENING_COLUMNS, np.nan)}
        legal = (pd.Timestamp(cal.loc[date, 'market_open_utc']).tz_convert('America/New_York').strftime('%H:%M') <= '09:46'
                 and close_m >= 750)
        start_ok = np.isfinite(row['price_at_09_46'])
        end_ok = np.isfinite(row['price_at_12_30'])
        row['label_reason'] = ('SESSION_ENDS_BEFORE_LABEL_OR_OPENS_AFTER_START' if not legal else
            'OK' if start_ok and end_ok else 'MISSING_OR_INVALID_BOTH_ENDPOINTS' if not start_ok and not end_ok else
            'MISSING_OR_INVALID_START_0947' if not start_ok else 'MISSING_OR_INVALID_END_1230')
        w = g[g.m.between(571, 584) & g.valid]
        row['opening_valid_bar_fraction'] = len(w) / 14
        if len(w):
            row['opening_staleness_minutes'] = float(584 - w.m.max())
            row['opening_last_feature_bar_end_utc'] = w.timestamp_utc.iloc[-1]
            current, opening = _exact(g, 584, 'close'), row['_opening_price']
            high, low = float(w.high.max()), float(w.low.min())
            row['opening_return'] = current / opening - 1
            row['opening_return_5m'] = current / _exact(g, 579, 'close') - 1
            row['opening_range'] = (high - low) / opening
            row['opening_range_position'] = (current - low) / (high - low) if high > low else np.nan
            row['opening_drawdown'] = current / high - 1
            if len(w) == 14:
                changes = np.diff(np.log(np.r_[opening, w.close.to_numpy(float)]))
                row['opening_rv'] = float(np.sqrt(np.sum(changes ** 2)))
                total = float(np.abs(changes).sum())
                row['opening_efficiency'] = float(np.log(current/opening)/total) if total > 0 else 0.0
                row['_window_volume'] = float(w.volume.sum())
                row['opening_last5_volume_share'] = float(w.loc[w.m.ge(580), 'volume'].sum() / w.volume.sum())
        rows.append(row)
    z = pd.DataFrame(rows)
    grid = pd.MultiIndex.from_product([sorted(x.symbol.unique()), dates], names=['ticker', 'date'])
    z = z.set_index(['ticker', 'date']).reindex(grid).reset_index()
    z['label_reason'] = z.label_reason.fillna('NO_STOCK_MINUTE_SOURCE_OR_SESSION')
    z['opening_valid_bar_fraction'] = z.opening_valid_bar_fraction.fillna(0.0)
    z['opening_gap'] = z._opening_price / z.groupby('ticker')._regular_close.shift(1) - 1
    base = z.groupby('ticker')._window_volume.transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    z['opening_relative_volume'] = z._window_volume / base.where(base.gt(0))
    return z.drop(columns=['_regular_close', '_opening_price', '_window_volume'])


def assert_inherited_inputs(old, new, columns):
    left = old.set_index('sample_id')[columns].sort_index()
    right = new.set_index('sample_id')[columns].sort_index()
    pd.testing.assert_frame_equal(left, right, check_exact=True)
    return {'status': 'PASS', 'feature_count': len(columns), 'rows': len(left),
            'comparison': 'exact values, types, row keys and missing states; B contains the same physical A columns'}


def assemble_panel(old, summaries, features_a, old_baseline, clocks):
    """Pure assembly: label validity never selects the prediction population."""
    inherited_meta = ['ticker', 'date', 'sample_id', 'eligible', 'eligibility_reason', 'sector',
        'pit_security_id', 'pit_cik', 'pit_sic4', 'pit_identity_accession', 'pit_sec_accession',
        'pit_sec_lineage_hash', 'pit_identity_available_at', 'pit_sic_available_at',
        'pit_sec_available_at', 'last_feature_bar_end_utc']
    panel = old[list(dict.fromkeys([c for c in inherited_meta if c in old] + features_a))].copy()
    panel['premarket_prediction_at_utc'] = old.prediction_at_utc
    panel['prediction_at_utc'] = clocks(panel.date, '09:45:00')
    panel['feature_cutoff_utc'] = clocks(panel.date, '09:44:00')
    panel['label_start_utc'] = clocks(panel.date, '09:46:00')
    panel['label_end_utc'] = clocks(panel.date, '12:30:00')
    panel['label_available_at_utc'] = clocks(panel.date, '12:31:00')
    panel['security_uid'] = panel.get('pit_security_id', panel.ticker)
    for field in ['pit_identity_available_at', 'pit_sic_available_at', 'pit_sec_available_at']:
        if field in panel:
            available = pd.to_datetime(panel[field], utc=True)
            if (available.notna() & available.gt(panel.premarket_prediction_at_utc)).any():
                raise ValueError('Inherited A PIT violation: ' + field)
    available = pd.to_datetime(panel.last_feature_bar_end_utc, utc=True)
    if (available.notna() & available.gt(panel.premarket_prediction_at_utc-pd.Timedelta(minutes=1))).any():
        raise ValueError('Inherited A minute availability violation')
    stock = pd.concat([summaries[t] for t in TICKERS if t in summaries], ignore_index=True)
    # Market placeholders within stock summaries are filled only from market observations.
    stock = stock.drop(columns=MARKET_OPENING_COLUMNS + ['opening_relative_QQQ_return', 'opening_relative_SOXX_return'])
    panel = panel.merge(stock, on=['ticker', 'date'], how='left', validate='one_to_one')
    for ticker in ['QQQ', 'SOXX']:
        market = summaries[ticker][['date', 'opening_return', 'opening_rv']].rename(columns={
            'opening_return': f'opening_{ticker}_return', 'opening_rv': f'opening_{ticker}_rv'})
        panel = panel.merge(market, on='date', how='left', validate='many_to_one')
        panel[f'opening_relative_{ticker}_return'] = panel.opening_return-panel[f'opening_{ticker}_return']
    panel['scope_four_stocks'] = panel.ticker.isin(TICKERS)
    panel['prediction_eligible'] = panel.eligible & panel.scope_four_stocks
    panel['label_reason'] = panel.label_reason.fillna('NO_STOCK_MINUTE_SOURCE_OR_SESSION')
    panel.loc[~panel.eligible, 'label_reason'] = 'INELIGIBLE_AT_PREDICTION'
    panel['evaluable'] = panel.prediction_eligible & panel.label_reason.eq('OK')
    panel['return_remaining'] = np.where(panel.evaluable, panel.price_at_12_30/panel.price_at_09_46-1, np.nan)
    panel['y'] = np.where(panel.evaluable, panel.return_remaining.gt(0).astype(int), np.nan)
    panel['label_up'] = panel.y
    panel['flat'] = np.where(panel.evaluable, panel.return_remaining.eq(0).astype(int), np.nan)
    panel['strict_down'] = np.where(panel.evaluable, panel.return_remaining.lt(0).astype(int), np.nan)
    panel['data_quality'] = np.where(panel.opening_valid_bar_fraction.eq(1), 'OPENING_COMPLETE', 'OPENING_PARTIAL_OR_MISSING')
    panel[OPENING_COLUMNS] = panel[OPENING_COLUMNS].replace([np.inf, -np.inf], np.nan)
    if not panel.label_available_at_utc.lt(CUTOFF).all():
        raise ValueError('New label maturity exceeds training boundary')
    last = pd.to_datetime(panel.opening_last_feature_bar_end_utc, utc=True)
    if (last.notna() & last.gt(panel.feature_cutoff_utc)).any():
        raise ValueError('Opening availability violation')
    comparison = assert_inherited_inputs(old, panel, features_a)
    config = {'feature_columns_A': features_a, 'feature_columns_B': features_a + OPENING_COLUMNS,
              'baseline_columns_A': old_baseline, 'baseline_columns_B': old_baseline + MARKET_OPENING_COLUMNS,
              'opening_contract': OPENING_CONTRACT, 'inherited_A_B_comparison': comparison}
    return panel, config


def build_panel(out: Path, old_run: Path, repo: Path):
    out, old_run, repo = Path(out), Path(old_run), Path(repo)
    if out.exists():
        raise ValueError('New output must not exist: ' + str(out))
    old_entry = _old_module(repo)
    source_dir = old_run / 'research-data'
    delivery = _read_json(old_run / 'delivery-manifest.json')
    sealed = {a['path']: a['sha256'] for a in delivery['artifacts']}
    for name in ['sources.json', 'freeze.json', 'bar_timestamp_semantics.json', 'sample_manifest.parquet']:
        _check(source_dir/name, sealed['research-data/'+name])
    freeze, sources = _read_json(source_dir/'freeze.json'), _read_json(source_dir/'sources.json')
    features_a = freeze['feature_columns']
    if len(features_a) != 75 or len(set(features_a)) != 75:
        raise ValueError('Inherited A must have exactly the frozen 75 unique columns')
    semantics = _read_json(source_dir/'bar_timestamp_semantics.json')
    if semantics['declared_convention'] != 'MINUTE_END_STAMP' or any(
        r['match_fraction'] < .95 or r['compared_days'] < 5 for r in semantics['records'] if r['clock'] in ['09:31', '16:00']):
        raise ValueError('Prior same-provider timestamp certification is insufficient')
    _check(source_dir/'sample_manifest.parquet', freeze['sample_manifest_sha256'])
    store = old_entry.DataStore(old_entry.resolve(repo))
    old = store._read_parquet(source_dir/'sample_manifest.parquet', '2020-05-01', '2025-12-31', None, 'date')
    if old.date.max() >= '2026-01-01' or old.sample_id.duplicated().any() or old.ticker.nunique() != 17:
        raise ValueError('Invalid inherited full qualification population')
    source_checks = [_check(sources['calendar']['path'], sources['calendar']['sha256'])]
    calendar = store._read_parquet(Path(sources['calendar']['path']), old.date.min(), old.date.max(),
        ['trade_date', 'market_open_utc', 'market_close_utc', 'is_session', 'is_early_close'], 'trade_date')
    calendar = calendar[calendar.is_session].rename(columns={'trade_date': 'date'})
    if sorted(calendar.date.unique()) != sorted(old.date.unique()):
        raise ValueError('Inherited sample calendar differs from existing calendar')
    summaries = {}
    for ticker in TICKERS + ['QQQ', 'SOXX']:
        if ticker in TICKERS:
            references = [r for r in sources['acquisition'] if r['ticker'] == ticker]
            for ref in references:
                source_checks.append(_check(ref['manifest'], ref['manifest_sha256']))
                for kind in ['raw', 'output']:
                    source_checks.append(_check(ref[kind]['path'], ref[kind]['sha256']))
            files = [r['output']['path'] for r in references]
        else:
            references = [r for r in sources['market'] if f'symbol={ticker}' in Path(r['path']).as_posix()]
            source_checks.extend(_check(r['path'], r['sha256']) for r in references)
            files = [r['path'] for r in references]
        if not files:
            raise ValueError('Necessary frozen minute references missing: ' + ticker)
        print('Opening summary', ticker, len(files), flush=True)
        summaries[ticker] = summarize_minutes(safe_minute_read(store, files), calendar)
    panel, config = assemble_panel(old, summaries, features_a, freeze['baseline_columns'], old_entry.timestamps)
    predictions = panel[panel.prediction_eligible].copy()
    out.mkdir(parents=True, exist_ok=False)
    panel.to_parquet(out/'sample_manifest.parquet', index=False)
    predictions.to_parquet(out/'panel.parquet', index=False)
    labelled = predictions[predictions.evaluable]
    coverage = {'full_grid_rows': len(panel), 'parent_tickers': sorted(panel.ticker.unique()),
        'parent_eligible_rows': int(panel.eligible.sum()), 'four_stock_grid_rows': int(panel.scope_four_stocks.sum()),
        'four_stock_eligible_predictions': len(predictions), 'prediction_dates': predictions.date.nunique(),
        'evaluable_rows': len(labelled), 'evaluable_dates': labelled.date.nunique(),
        'unlabelled_predictions': int((~predictions.evaluable).sum()),
        'flat_count': int(labelled.flat.sum()), 'strict_down_count': int(labelled.strict_down.sum()),
        'up_count': int(labelled.y.sum()),
        'parent_eligible_coverage': len(labelled)/int(panel.eligible.sum()),
        'four_stock_label_coverage': len(labelled)/len(predictions) if len(predictions) else None,
        'label_reason_counts': panel.label_reason.value_counts().to_dict(),
        'unlabelled_prediction_reasons': predictions.loc[~predictions.evaluable, 'label_reason'].value_counts().to_dict(),
        'opening_quality_counts': predictions.data_quality.value_counts().to_dict(),
        'missing_rates_all_predictions': predictions[features_a+OPENING_COLUMNS].isna().mean().to_dict(),
        'per_stock': panel.groupby('ticker').agg(eligible=('eligible', 'sum'), predictions=('prediction_eligible', 'sum'), evaluable=('evaluable', 'sum')).reset_index().to_dict('records')}
    write_json(out/'coverage.json', coverage)
    write_json(out/'sources.json', {'old_delivery_manifest': {'path': str(old_run/'delivery-manifest.json'), 'sha256': digest(old_run/'delivery-manifest.json')},
        'inherited_sources': {'path': str(source_dir/'sources.json'), 'sha256': digest(source_dir/'sources.json')},
        'inherited_sample_manifest': {'path': str(source_dir/'sample_manifest.parquet'), 'sha256': digest(source_dir/'sample_manifest.parquet')},
        'verified_source_files': source_checks, 'inherited_pit': sources['pit'], 'bar_timestamp_semantics': semantics,
        'data_root_read_only': True, 'acquisition_calls': 0, 'new_supervised_fits': 0,
        'mixed_year_read_boundary': 'existing DataStore Arrow predicate strictly before UTC 2026, prior to pandas',
        'limitations': ['Inherited 13F/SIC-qualified four-stock conditional population; original 17-stock denominator retained',
            'Vendor raw historical OHLC is a 2026 downloaded vintage; complete historical revision vintages unavailable',
            'Unadjusted cross-session opening gaps may include stock-split discontinuities; no future adjustment factors introduced',
            'No inherited model scores, no updated 09:45 A inputs, no new download or broker connection'],
        'source_code': {'opening_data.py': digest(__file__), 'inherited_entry': digest(Path(old_entry.__file__))}})
    config.update(task_id=TASK_ID, schema_version=1, stock_universe=TICKERS,
        panel_sha256=digest(out/'panel.parquet'), sample_manifest_sha256=digest(out/'sample_manifest.parquet'),
        prediction_panel='panel.parquet', prediction_rows_include_missing_labels=True,
        coverage_metadata={'path': str(out/'coverage.json'), 'sha256': digest(out/'coverage.json'), **coverage},
        created_before_first_fit=datetime.now(timezone.utc).isoformat())
    write_json(out/'data_config.json', config)
    return config
