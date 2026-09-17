"""Bounded pooled stock opening-to-12:30 research. Offline build/train/predict.

Run from the repository with: python -m scripts.research.fast3.stock_open_3h.
Market-data acquisition reuses scripts/storage/refresh_minute_data.py separately.
This entry never acquires data, changes source archives, or places orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[3]
from scripts.common.storage_paths import resolve
from scripts.storage.storage_r2a import DataStore

ACQUIRED = ['NVDA','AMD','AVGO','ENPH']
RUN = 'stock_open_3h_20260914'
SEED = 104729


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False), encoding='utf-8')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def local_module(name):
    spec = importlib.util.spec_from_file_location('fast3_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def timestamps(dates, clock):
    return pd.to_datetime(pd.Series(dates).astype(str) + ' ' + clock).dt.tz_localize('America/New_York').dt.tz_convert('UTC')


def minute_summary(frame, early_close_dates=()):
    """Provider END-labelled bars; exact endpoints, 1-minute feature latency.

    A bar stamped 09:31 covers regular-session opening 09:30 through 09:31.
    The label ends at the close of the bar stamped 12:30, never 12:31.
    Only completed bars with end <=09:24 are available to 09:25 features.
    """
    x = frame.copy()
    if x.empty:
        return pd.DataFrame()
    x['timestamp_utc'] = pd.to_datetime(x.timestamp_utc, utc=True)
    if (x.timestamp_utc >= pd.Timestamp('2026-01-01', tz='UTC')).any():
        raise ValueError('2026 timestamp reached summary')
    if x.duplicated(['symbol', 'timestamp_utc']).any():
        raise ValueError('Duplicate minute keys: no silent keep-last')
    et = x.timestamp_utc.dt.tz_convert('America/New_York')
    x['date'] = et.dt.strftime('%Y-%m-%d')
    x['m'] = et.dt.hour * 60 + et.dt.minute
    x = x.sort_values('timestamp_utc')
    rows = []
    for (ticker, date), g in x.groupby(['symbol', 'date'], sort=True):
        opening = g.loc[g.m.eq(571)]
        endpoint = g.loc[g.m.eq(750)]
        row = {'ticker': ticker, 'date': date, 'open_price': np.nan, 'price_12_30': np.nan,
               'label_reason': 'MISSING_OPEN_AND_ENDPOINT', 'last_feature_bar_end_utc': pd.NaT}
        if len(opening) == 1:
            row['open_price'] = float(opening.open.iloc[0])
        if len(endpoint) == 1:
            row['price_12_30'] = float(endpoint.close.iloc[0])
        valid_open = len(opening) == 1 and np.isfinite(row['open_price']) and row['open_price'] > 0 and opening.volume.iloc[0] > 0
        valid_end = len(endpoint) == 1 and np.isfinite(row['price_12_30']) and row['price_12_30'] > 0 and endpoint.volume.iloc[0] > 0
        if valid_open and valid_end:
            row['label_reason'] = 'OK'
        elif valid_open:
            row['label_reason'] = 'MISSING_OR_NO_TRADE_ENDPOINT'
        elif valid_end:
            row['label_reason'] = 'MISSING_OR_NO_TRADE_OPEN'
        pm = g[g.m.between(241, 564)]
        if len(pm):
            p0, p1 = float(pm.open.iloc[0]), float(pm.close.iloc[-1])
            traded = pm[pm.volume.gt(0)]
            row.update(pm_return=p1 / p0 - 1, pm_range=(pm.high.max() - pm.low.min()) / p0,
                       pm_log_volume=np.log1p(pm.volume.sum()), pm_log_turnover=np.log1p(pm.turnover.sum()),
                       pm_traded_minutes=len(traded), pm_observed_minutes=len(pm), pm_zero_volume_fraction=float(pm.volume.eq(0).mean()),
                       pm_volatility=float(np.log(pm.close).diff().std()),
                       last_feature_bar_end_utc=pm.timestamp_utc.iloc[-1])
            vwap = pm.turnover.sum() / pm.volume.sum() if pm.volume.sum() > 0 else np.nan
            row['pm_relative_vwap'] = p1 / vwap - 1 if vwap > 0 else np.nan
            for n in [30, 60]:
                w = pm[pm.m.gt(564 - n)]
                row[f'pm_return_{n}m'] = p1 / w.open.iloc[0] - 1 if len(w) else np.nan
        rth = g[g.m.between(571, 960)]
        closebar = g[g.m.eq(960)]
        # Observed-session lag summaries require normal-session endpoints;
        # retain minute coverage explicitly instead of assuming interior completeness.
        if valid_open and len(closebar) == 1 and date not in early_close_dates:
            row.update(rth_return=closebar.close.iloc[0] / row['open_price'] - 1,
                       rth_range=(rth.high.max() - rth.low.min()) / row['open_price'],
                       rth_log_volume=np.log1p(rth.volume.sum()),
                       rth_observed_minutes=len(rth),
                       rth_volatility=np.log(rth.close).diff().std())
        rows.append(row)
    return pd.DataFrame(rows)


def add_lags(summary, session_dates=None):
    x = summary.sort_values(['ticker', 'date']).copy()
    if session_dates is not None:
        grid = pd.MultiIndex.from_product([x.ticker.unique(), session_dates], names=['ticker','date'])
        x = x.set_index(['ticker','date']).reindex(grid).reset_index()
    rth = ['rth_return','rth_range','rth_log_volume','rth_volatility','rth_observed_minutes']
    for c in rth:
        if c not in x:
            x[c] = np.nan
        x['lag_' + c] = x.groupby('ticker')[c].shift(1)
    for n in [5,20]:
        x[f'lag_rth_return_mean_{n}'] = x.groupby('ticker')['rth_return'].transform(lambda s: s.shift(1).rolling(n, min_periods=3).mean())
        x[f'lag_rth_return_std_{n}'] = x.groupby('ticker')['rth_return'].transform(lambda s: s.shift(1).rolling(n, min_periods=3).std())
    return x.drop(columns=rth)


def read_minutes(store, files):
    cols = ['symbol','timestamp_utc','open','high','low','close','volume','turnover']
    return store._read_parquet([Path(p) for p in files], '2020-05-01T00:00:00Z',
                               '2025-12-31T23:59:59.999999999Z', cols, 'timestamp_utc')


def available_inputs(paths):
    base = paths.cache_root / 'fast3' / RUN / 'acquired'
    report = json.loads((base / 'acquisition_report.json').read_text())
    if report['status'] not in ['ACQUIRED','PARTIAL','FAILED'] or len(report['results']) != len(report['plan']):
        raise ValueError('Acquisition plan is still running/incomplete; cannot freeze partial arrival')
    key = lambda v: (v['ticker'], v['start'], v['end'])
    if sorted(key(r['item']) for r in report['results']) != sorted(key(r) for r in report['plan']):
        raise ValueError('Acquisition completion does not cover the full fixed plan')
    if any(r['status'] not in ['ACQUIRED','REUSED','FAILED'] for r in report['results']):
        raise ValueError('Acquisition includes unfinished interval')
    references = []
    for r in report['results']:
        if r['status'] == 'FAILED':
            continue
        item = r['item']
        p = base/'intervals'/item['ticker']/(item['start']+'_'+item['end'])/'manifest.json'
        m = json.loads(p.read_text())
        if m['status'] != 'ACQUIRED' or m['item'] != item or m['item']['end'] >= '2026-01-01' or m['output']['sha256'] != r['output']['sha256']:
            raise ValueError('Invalid acquisition checkpoint')
        for key in ['raw', 'output']:
            if digest(m[key]['path']) != m[key]['sha256']:
                raise ValueError('Acquisition source changed')
        codes = pq.ParquetFile(m['raw']['path']).read(columns=['code']).column('code').to_pylist()
        if not codes or any(c != m['item']['code'] for c in codes):
            raise ValueError('Raw provider identity mismatch')
        references.append({'ticker': m['item']['ticker'], 'manifest': str(p), 'manifest_sha256': digest(p), **m})
    return references


def calendar(store):
    with sqlite3.connect('file:' + store.catalog_path.as_posix() + '?mode=ro', uri=True) as c:
        rows = c.execute("SELECT dataset,ticker,path,min_date,max_date FROM data_files WHERE is_current=1 AND dataset LIKE '%calendar%'").fetchall()
    # Select the existing exchange session calendar, never create a new calendar.
    options = [r for r in rows if r[0] in ['trading_calendar','trading_calendar_xnys','market_trading_calendar']]
    if not options:
        raise ValueError('No existing calendar selected: ' + repr(rows))
    row = options[0]
    dataset = ds.dataset(row[2], format='parquet')
    names = dataset.schema.names
    date_col = next((c for c in ['session_date','date','trade_date','calendar_date'] if c in names), None)
    if date_col is None:
        raise ValueError('Calendar date field not recognized: ' + repr(names))
    x = store._read_parquet(Path(row[2]), '2020-05-22', '2025-12-31', None, date_col)
    if 'is_open' in x:
        x = x[x.is_open.astype(bool)]
    if 'is_session' in x:
        x = x[x.is_session.astype(bool)]
    if 'market' in x:
        x = x[x.market.astype(str).isin(['US','XNYS','NYSE'])]
    dates = sorted(pd.to_datetime(x[date_col]).dt.strftime('%Y-%m-%d').unique())
    if 'is_early_close' not in x:
        raise ValueError('Existing calendar lacks certified early-close flag')
    early = sorted(pd.to_datetime(x.loc[x.is_early_close.astype(bool), date_col]).dt.strftime('%Y-%m-%d').unique())
    return dates, {'dataset': row[0], 'path': row[2], 'sha256': digest(row[2]), 'rows': len(x),
                   'early_close_dates': early}


def verify_bar_end_semantics(store, references, early_close_dates):
    """Cross-check time semantics against independent same-provider daily OHLC.

    Uses each source symbol's first and last complete acquired intervals, never
    prediction scores. Records end and alternative-start matches without moving
    the fixed 12:30 target. Each symbol must support the declared end convention.
    """
    rows = []
    for ticker in ACQUIRED:
        refs = sorted([r for r in references if r['ticker'] == ticker], key=lambda r:r['item']['start'])
        if not refs:
            continue
        refs = [refs[0]] if len(refs) == 1 else [refs[0],refs[-1]]
        x = read_minutes(store, [r['output']['path'] for r in refs])
        et = x.timestamp_utc.dt.tz_convert('America/New_York')
        x['date'],x['clock'] = et.dt.strftime('%Y-%m-%d'),et.dt.strftime('%H:%M')
        daily = store.daily(ticker, 'raw', x.date.min(), x.date.max(), columns=['date','open','close'])
        daily['date'] = pd.to_datetime(daily.date).dt.strftime('%Y-%m-%d')
        for clock,column in [('09:30','open'),('09:31','open'),('15:59','close'),('16:00','close')]:
            mask = x.clock.eq(clock)
            if column == 'close':
                mask &= ~x.date.isin(early_close_dates)
            z = x[mask].merge(daily, on='date', suffixes=('_minute','_daily'))
            matched = int(np.isclose(z[column+'_minute'],z[column+'_daily'],atol=.0001,rtol=0).sum())
            rows.append({'ticker':ticker,'clock':clock,'field':column,'compared_days':len(z),'matched_days':matched,
                         'match_fraction':matched/len(z) if len(z) else None})
        supports = [r for r in rows if r['ticker']==ticker and r['clock'] in ['09:31','16:00']]
        if any(r['compared_days'] < 5 or r['match_fraction'] < .95 for r in supports):
            raise ValueError('End-stamp cross-check insufficient: '+repr(supports))
    return {'declared_convention':'MINUTE_END_STAMP','open_bar':'09:31 open','target_bar':'12:30 close',
            'method':'pre-fit provider daily O/C cross-check on first/last acquired intervals; no target-score comparison',
            'minimum_compared_days_per_symbol_endpoint':5,'required_match_fraction':.95,'records':rows}


def build_panel(out):
    paths = resolve(REPO)
    store = DataStore(paths)
    out.mkdir(parents=True, exist_ok=False)
    references = available_inputs(paths)
    acquisition_report = paths.cache_root / 'fast3' / RUN / 'acquired/acquisition_report.json'
    # Preserve the exact terminal plan/failure record even if acquisition is later rerun.
    (out / 'acquisition-report.json').write_bytes(acquisition_report.read_bytes())
    dates, cal = calendar(store)
    early_close_dates = set(cal['early_close_dates'])
    stamp_audit = verify_bar_end_semantics(store, references, early_close_dates)
    write_json(out / 'bar_timestamp_semantics.json', stamp_audit)
    pit = local_module('pit_inputs')
    scope = pit.universe_download_plan()
    desired_tickers = scope['symbols']
    scope['acquisition_tickers'] = ACQUIRED
    scope['unacquired_ticker_reasons'] = {t:'NO_REMAINING_HISTORY_QUOTA_NOT_IN_ALREADY_TOUCHED_SET' for t in desired_tickers if t not in ACQUIRED}
    write_json(out / 'historical_universe_scope.json', scope)
    skeleton = pd.MultiIndex.from_product([desired_tickers, dates], names=['ticker','date']).to_frame(index=False)
    skeleton['prediction_at_utc'] = timestamps(skeleton.date, '09:25:00')
    skeleton['label_end_utc'] = timestamps(skeleton.date, '12:30:00')
    skeleton['label_available_at_utc'] = timestamps(skeleton.date, '12:31:00')
    skeleton['sample_id'] = skeleton.ticker + '|' + skeleton.date
    panel, pit_manifest = pit.add_pit_features(skeleton)
    tables = []
    for ticker in ACQUIRED:
        refs = [r for r in references if r['ticker'] == ticker]
        if not refs:
            continue
        print('Summarizing', ticker, len(refs), 'intervals', flush=True)
        x = read_minutes(store, [r['output']['path'] for r in refs])
        tables.append(add_lags(minute_summary(x, early_close_dates), dates))
    if not tables:
        raise ValueError('No acquired stock minutes')
    summary = pd.concat(tables, ignore_index=True)
    panel = panel.merge(summary, on=['ticker','date'], how='left', validate='one_to_one')
    panel['label_reason'] = panel.label_reason.fillna('NO_STOCK_MINUTE_SOURCE_OR_SESSION')
    panel.loc[~panel.eligible, 'label_reason'] = 'INELIGIBLE_AT_PREDICTION'
    ok = panel.eligible & panel.label_reason.eq('OK')
    panel['return_3h'] = np.where(ok, panel.price_12_30 / panel.open_price - 1, np.nan)
    panel['y'] = np.where(ok, panel.return_3h.gt(0).astype(int), np.nan)
    panel['flat'] = np.where(ok, panel.return_3h.eq(0).astype(int), np.nan)
    source_features = sorted(c for c in summary if c.startswith(('pm_', 'lag_')))
    market_refs = []
    market_features = []
    for ticker in ['QQQ','SOXX']:
        # Original pre-2026 partitions only; current tail/reconciliation is not read.
        root = paths.data_root / f'fast3/moomoo_24h_1m/canonical/symbol={ticker}'
        files = sorted(p for p in root.glob('year=*/month=*/data.parquet') if 'year=2026' not in p.as_posix() and 2020 <= int(p.parent.parent.name[5:]) <= 2025)
        m = add_lags(minute_summary(read_minutes(store, files), early_close_dates), dates)
        keep = [c for c in m if c.startswith(('pm_','lag_'))]
        names = {c: f'market_{ticker}_{c}' for c in keep}
        market_features.extend(names.values())
        panel = panel.merge(m[['date'] + keep].rename(columns=names), on='date', how='left', validate='many_to_one')
        market_refs.extend({'path': str(p), 'sha256': digest(p)} for p in files)
    features = source_features + market_features + pit_manifest['feature_columns']
    baseline = market_features + pit_manifest.get('baseline_columns', pit_manifest.get('baseline_features', []))
    if not (panel.loc[ok,'label_available_at_utc'] < pd.Timestamp('2026-01-01',tz='UTC')).all():
        raise ValueError('Label maturity cutoff')
    available = panel.last_feature_bar_end_utc.notna()
    if not (panel.loc[available, 'last_feature_bar_end_utc'] <= panel.loc[available, 'prediction_at_utc'] - pd.Timedelta(minutes=1)).all():
        raise ValueError('Feature availability violation')
    numeric = panel[features].replace([np.inf,-np.inf], np.nan)
    panel[features] = numeric
    panel.to_parquet(out / 'sample_manifest.parquet', index=False)
    labelled = panel[ok].copy()
    labelled.to_parquet(out / 'panel.parquet', index=False)
    config = {'schema_version': 1, 'seed': SEED, 'feature_columns': features, 'baseline_columns': baseline,
              'candidate_ids': ['logit_c01','logit_c1','hgb_leaf7','hgb_leaf15'],
              'candidate_contract': {'logit_C': [.1,1], 'logit_max_iter': 1500, 'hgb_max_iter':150,
                                     'hgb_learning_rate':.05,'hgb_max_leaf_nodes':[7,15],
                                     'hgb_l2_regularization':10,'hgb_min_samples_leaf':40,'early_stopping':False,
                                     'imputer':'fold_train_median_with_indicator_keep_empty', 'scaler':'fold_train_standard_for_logit',
                                     'calibration':None,'ensemble':None},
              'outer_years':[2022,2023,2024,2025], 'inner_years':[2021,2022,2023,2024,2025],
              'train_start':'2020-01-01','min_train_days':120,'min_validation_days':60,
              'primary_metric':'equal_trading_day_log_loss', 'threshold':.5,'reliability_edges':list(np.arange(11)/10),
              'bootstrap':{'unit':'trading_day','method':'moving_block','block_length':20,'replications':1000,'seed':SEED},
              'adoption_rule':'both_baseline_paired_delta_ci_upper_below_zero_and_3_oos_years_and_250_dates; PIT vintage limitations also preclude production adoption',
              'bar_semantics':'end_stamp; RTH open=09:31 open; endpoint=12:30 close; features end<=09:24',
              'panel_sha256':digest(out/'panel.parquet'), 'sample_manifest_sha256':digest(out/'sample_manifest.parquet'),
              'created_before_first_fit':datetime.now(timezone.utc).isoformat()}
    write_json(out / 'sources.json', {'calendar':cal,'acquisition':references,'market':market_refs,'pit':pit_manifest,
                                     'acquisition_report':{'source_path':str(acquisition_report),
                                         'frozen_path':str(out/'acquisition-report.json'),
                                         'sha256':digest(out/'acquisition-report.json')},
                                     'source_code':{p.name:digest(p) for p in Path(__file__).parent.glob('*.py')}})
    coverage = {'potential_grid_rows':len(panel),'eligible_rows':int(panel.eligible.sum()),'labelled_rows':len(labelled),
                'labelled_dates':labelled.date.nunique(),'labelled_tickers':sorted(labelled.ticker.unique()),
                'flat_count':int(labelled.flat.sum()),'reason_counts':panel.label_reason.value_counts().to_dict(),
                'eligible_label_coverage':float(len(labelled)/panel.eligible.sum()) if panel.eligible.sum() else None,
                'missing_rates':{k:float(v) for k,v in labelled[features].isna().mean().items()},
                'symbol_coverage':panel.groupby('ticker').agg(eligible=('eligible','sum'),labelled=('y','count')).reset_index().to_dict('records')}
    write_json(out / 'coverage.json', coverage)
    config['coverage_metadata'] = {'path':str(out/'coverage.json'),'sha256':digest(out/'coverage.json'),**coverage}
    write_json(out / 'freeze.json', config)
    print(json.dumps(coverage, default=str), flush=True)


def main():
    paths = resolve(REPO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['build','train','predict'])
    parser.add_argument('--dataset', type=Path, default=paths.results_root/'fast3'/RUN/'research-data')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--study', choices=['open_3h', 'opening_0945', 'opening_state_horizon', 'share_unit_full_state'], default='open_3h')
    parser.add_argument('--old-run', type=Path, default=paths.results_root/'fast3'/RUN)
    parser.add_argument('--horizon', choices=['H15','H60','H1230'], default='H1230')
    parser.add_argument('--unit-evidence', type=Path)
    args = parser.parse_args()
    if args.study in ('opening_state_horizon','share_unit_full_state'):
        from . import opening_state_data, opening_state_study
        output = args.output or args.dataset.parent/'evaluation'
        if args.mode == 'build':
            if args.study=='share_unit_full_state':
                if not args.unit_evidence:
                    parser.error('share_unit_full_state build requires --unit-evidence')
                from . import share_unit_data
                share_unit_data.build_panel(args.dataset,args.old_run,REPO,args.unit_evidence)
            else:
                prior = paths.results_root/'fast3'/'stock_0945_direction_r1'/'20260914T140516Z'
                opening_state_data.build_panel(args.dataset, prior, REPO)
            opening_state_study.freeze_state(args.dataset, output)
        elif args.mode == 'train':
            from threadpoolctl import threadpool_limits
            with threadpool_limits(limits=2):
                opening_state_study.train_state(args.dataset, output)
        else:
            if not all([args.model,args.input,args.output]):
                parser.error('predict requires --model --input --output')
            if args.output.exists():
                raise ValueError('Prediction output exists')
            import joblib
            opening_state_study.predict_state_offline(joblib.load(args.model), pd.read_parquet(args.input), args.horizon).to_parquet(args.output,index=False)
        return
    if args.study == 'opening_0945':
        from . import opening_data, opening_study
        if args.mode == 'build':
            opening_data.build_panel(args.dataset, args.old_run, REPO)
            opening_study.freeze(args.dataset, args.output or args.dataset.parent/'evaluation')
        elif args.mode == 'train':
            from threadpoolctl import threadpool_limits
            with threadpool_limits(limits=2):
                opening_study.train(args.dataset, args.output or args.dataset.parent/'evaluation')
        else:
            if not all([args.model, args.input, args.output]):
                parser.error('predict requires --model --input --output')
            if args.output.exists():
                raise ValueError('Prediction output exists')
            import joblib
            opening_study.predict_final(joblib.load(args.model), pd.read_parquet(args.input)).to_parquet(args.output, index=False)
        return
    if args.mode == 'build':
        build_panel(args.dataset)
    elif args.mode == 'train':
        config = json.loads((args.dataset/'freeze.json').read_text())
        if digest(args.dataset/'panel.parquet') != config['panel_sha256']:
            raise ValueError('Frozen panel changed')
        x = pd.read_parquet(args.dataset/'panel.parquet')
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=4):
            result = local_module('modeling').train_research(x, config, args.output or args.dataset.parent/'evaluation')
        print(json.dumps(result,default=str),flush=True)
    else:
        if not all([args.model,args.input,args.output]):
            parser.error('predict requires --model --input --output')
        import joblib
        if args.output.exists():
            raise ValueError('Prediction output exists')
        predictions = local_module('modeling').predict_model(joblib.load(args.model), pd.read_parquet(args.input))
        predictions.to_parquet(args.output,index=False)


if __name__ == '__main__':
    main()
