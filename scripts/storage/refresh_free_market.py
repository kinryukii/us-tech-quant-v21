"""Checkpointed public Yahoo chart snapshots, separate from Moomoo price authority.

The older V21.196 chart reader fixes two dates and discards adjusted close,
actions and response identity. This adapter retains those source facts and
uses the existing storage roots, catalog registration and integrity contracts.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from scripts.common.storage_paths import resolve
from scripts.storage.build_data_catalog import PRICE_COLUMNS, sha256, utc_now

SOURCE = 'YAHOO_CHART'
DATASET = 'prices_daily_yahoo'
BASIS = 'split_adjusted'


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_versioned_parquet(frame, directory, stem):
    """Name by actual output bytes, including retrieval vintage metadata."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / ('.' + uuid.uuid4().hex + '.parquet.tmp')
    frame.to_parquet(temporary, index=False)
    digest = sha256(temporary)
    destination = directory / f'{stem}_{digest[:20]}.parquet'
    if destination.exists():
        if sha256(destination) != digest:
            raise ValueError('VERSION_HASH_COLLISION_OR_FILE_CHANGED')
        temporary.unlink()
    else:
        temporary.replace(destination)
    return destination


def normalize_chart(payload, ticker, symbol, start, end, source_id, observed):
    """Keep Yahoo's split-adjusted OHLC and separate dividend-adjusted close.

    Provider transport identity does not establish historical security identity.
    Invalid original rows are listed explicitly; never forward-fill missing bars.
    """
    chart = payload.get('chart', {})
    results = chart.get('result')
    if chart.get('error') or not isinstance(results, list) or len(results) != 1:
        raise ValueError('PROVIDER_ERROR_OR_NO_RESULT')
    result = results[0]
    meta = result.get('meta', {})
    if meta.get('symbol') != symbol:
        raise ValueError('PROVIDER_SYMBOL_MISMATCH')
    if meta.get('currency') != 'USD' or meta.get('exchangeTimezoneName') != 'America/New_York':
        raise ValueError('UNSUPPORTED_CURRENCY_OR_EXCHANGE_TIMEZONE')
    if meta.get('instrumentType') not in {'EQUITY', 'ETF'}:
        raise ValueError('UNSUPPORTED_INSTRUMENT_TYPE')
    timestamps = result.get('timestamp') or []
    indicators = result.get('indicators', {})
    quotes = indicators.get('quote') or []
    if len(quotes) != 1 or not timestamps:
        raise ValueError('NO_DAILY_BARS')
    values = quotes[0]
    for field in ['open', 'high', 'low', 'close', 'volume']:
        if len(values.get(field, [])) != len(timestamps):
            raise ValueError('OHLCV_ARRAY_LENGTH_MISMATCH')
    adjusted = indicators.get('adjclose') or []
    adj = adjusted[0].get('adjclose', []) if len(adjusted) == 1 else [None] * len(timestamps)
    if len(adj) != len(timestamps):
        raise ValueError('ADJUSTED_CLOSE_ARRAY_LENGTH_MISMATCH')
    dates = pd.to_datetime(timestamps, unit='s', utc=True).tz_convert('America/New_York').strftime('%Y-%m-%d')
    frame = pd.DataFrame({f: values[f] for f in ['open', 'high', 'low', 'close', 'volume']})
    frame['date'] = dates
    frame['adjusted_close'] = adj
    frame['source_timestamp_utc'] = pd.to_datetime(timestamps, unit='s', utc=True)
    frame = frame.loc[frame.date.between(start, end)].copy()
    if frame.duplicated('date').any():
        raise ValueError('DUPLICATE_DAILY_DATE')
    numeric = frame[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric, errors='coerce')
    valid = np.isfinite(numeric).all(axis=1) & (numeric[['open', 'high', 'low', 'close']] > 0).all(axis=1)
    valid &= (numeric.volume >= 0) & (numeric.high >= numeric[['open', 'close', 'low']].max(axis=1))
    valid &= numeric.low <= numeric[['open', 'close', 'high']].min(axis=1)
    rejected = frame.loc[~valid, ['date']].assign(reason='NULL_OR_INVALID_OHLCV').to_dict('records')
    frame = frame.loc[valid].copy()
    if frame.empty:
        raise ValueError('NO_VALID_DAILY_BARS')
    frame[numeric.columns] = numeric.loc[valid]
    adjnum = pd.to_numeric(frame.adjusted_close, errors='coerce')
    if ((frame.adjusted_close.notna()) & (~np.isfinite(adjnum) | (adjnum <= 0))).any():
        raise ValueError('INVALID_ADJUSTED_CLOSE')
    frame['adjusted_close'] = adjnum
    frame['ticker'] = ticker
    frame['adjustment'] = BASIS
    frame['source'] = SOURCE
    frame['provider_code'] = meta['symbol']
    frame['turnover'] = np.nan
    frame['source_id'] = source_id
    frame['observed_at'] = observed
    frame['currency'] = meta['currency']
    actions = []
    for category, events in (result.get('events') or {}).items():
        for event_id, event in events.items():
            ts = pd.Timestamp(event['date'], unit='s', tz='UTC')
            event_date = ts.tz_convert('America/New_York').strftime('%Y-%m-%d')
            if start <= event_date <= end:
                actions.append({'ticker': ticker, 'provider_code': symbol, 'event_type': category,
                    'event_id': str(event_id), 'date': event_date, 'event_timestamp_utc': ts.isoformat(),
                    'event_json': json.dumps(event, sort_keys=True), 'source': SOURCE,
                    'source_id': source_id, 'observed_at': observed})
    frame = frame[PRICE_COLUMNS + ['adjusted_close', 'source_timestamp_utc', 'currency']].sort_values('date').reset_index(drop=True)
    return frame, actions, meta, rejected


class RequestGate:
    def __init__(self, seconds=0.6):
        self.seconds = seconds
        self.lock = threading.Lock()
        self.last = 0.0
        self.stop = threading.Event()

    def wait(self):
        with self.lock:
            delay = max(0.0, self.last + self.seconds - time.monotonic())
            if delay:
                time.sleep(delay)
            if self.stop.is_set():
                raise RuntimeError('PROVIDER_STOPPED_AFTER_ACCESS_OR_RATE_LIMIT')
            self.last = time.monotonic()


def acquire_one(ticker, symbol, start, end, root, data_root, gate, retry_transient=False, identity_source=None):
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9._/\-]{0,31}', ticker) or '..' in ticker:
        raise ValueError('INVALID_TICKER')
    contract = {'provider': SOURCE, 'ticker': ticker, 'symbol': symbol, 'start': start, 'end': end, 'interval': '1d'}
    if ticker != symbol:
        if not isinstance(identity_source, str) or not identity_source.startswith('https://'):
            raise ValueError('NONIDENTICAL_SYMBOL_REQUIRES_EXPLICIT_MAPPING_EVIDENCE')
        contract['transport_mapping_evidence'] = identity_source
    key = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:24]
    checkpoint = root / 'checkpoints' / f'{key}.json'
    saved = None
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved['contract'] != contract:
            raise ValueError('CHECKPOINT_CONTRACT_MISMATCH')
        for record in saved.get('files', []):
            if not Path(record['path']).is_file() or sha256(record['path']) != record['sha256']:
                raise ValueError('CHECKPOINT_FILE_MISSING_OR_CHANGED')
        transient = saved.get('error') in {'NETWORK_FAILURE', 'HTTP_500', 'HTTP_502', 'HTTP_503', 'HTTP_504'}
        if saved['status'] == 'SUCCESS' or not (retry_transient and transient):
            return saved
    row = {'contract': contract, 'status': 'FAILED', 'files': []}
    if saved is not None:
        row['prior_attempts'] = saved.get('prior_attempts', []) + [{k: v for k, v in saved.items() if k != 'prior_attempts'}]
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='')
    p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    p2 = int((datetime.fromisoformat(end) + timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp())
    params = {'period1': p1, 'period2': p2, 'interval': '1d', 'events': 'div,splits,capitalGains', 'includeAdjustedClose': 'true'}
    try:
        response = None
        for attempt in range(3):
            gate.wait()
            try:
                response = requests.get(url, params=params, headers={'User-Agent': 'US-Tech-Quant data maintenance', 'Accept': 'application/json'}, timeout=40)
            except requests.RequestException:
                if attempt == 2:
                    raise RuntimeError('NETWORK_FAILURE')
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code in {401, 403, 429}:
                gate.stop.set()
                raise RuntimeError(f'PROVIDER_ACCESS_OR_RATE_LIMIT_HTTP_{response.status_code}')
            if response.status_code < 500 or attempt == 2:
                break
            time.sleep(2 * (attempt + 1))
        observed = utc_now()
        raw = response.content
        digest = hashlib.sha256(raw).hexdigest()
        raw_path = root / 'raw' / f'{key}_{digest[:20]}.json'
        raw_path.write_bytes(raw)
        row.update(http_status=response.status_code, observed_at=observed, source_url=response.url)
        row['files'].append({'path': str(raw_path), 'sha256': digest, 'role': 'RAW_HTTP_RESPONSE'})
        if response.status_code != 200:
            raise ValueError(f'HTTP_{response.status_code}')
        frame, actions, meta, rejected = normalize_chart(response.json(), ticker, symbol, start, end, digest, observed)
        destination = data_root / 'providers/yahoo/stocks' / quote(ticker, safe='') / 'versions'
        destination.mkdir(parents=True, exist_ok=True)
        out = write_versioned_parquet(frame, destination, 'daily_split_adjusted')
        output = {'path': str(out), 'sha256': sha256(out), 'role': 'NORMALIZED_DAILY', 'row_count': len(frame), 'min_date': frame.date.min(), 'max_date': frame.date.max()}
        row['files'].append(output)
        lineage = {'schema_version': 1, 'role': 'PROVIDER_DAILY_PRICE_SNAPSHOT', 'provider': SOURCE,
            'date_column': 'date', 'price_basis': 'SPLIT_ADJUSTED', 'currency': 'USD',
            'exchange_timezone': 'America/New_York', 'provider_symbol': meta['symbol'],
            'vintage_semantics': 'CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT',
            'inputs': [{'path': str(raw_path), 'sha256': digest}], 'source_url': response.url,
            'observed_at': observed, 'requested_start': start, 'requested_end': end,
            'adjusted_close_semantics': 'YAHOO_DIVIDEND_AND_SPLIT_ADJUSTED_CLOSE_SEPARATE_FROM_OHLC',
            'identity_semantics': 'EXACT_PROVIDER_TRANSPORT_SYMBOL_NOT_HISTORICAL_IDENTITY_CERTIFICATION',
            'rejected_rows': rejected, 'source_metadata': meta}
        if identity_source:
            lineage['transport_mapping_evidence'] = identity_source
        row['catalog_record'] = {'dataset': DATASET, 'ticker': ticker, 'adjustment': BASIS, 'path': str(out),
            'row_count': len(frame), 'min_date': frame.date.min(), 'max_date': frame.date.max(),
            'source': SOURCE, 'lineage': lineage}
        if actions:
            af = pd.DataFrame(actions).sort_values(['date', 'event_type', 'event_id'])
            if af.duplicated(['ticker', 'event_type', 'event_id']).any():
                raise ValueError('DUPLICATE_CORPORATE_ACTION')
            action_path = write_versioned_parquet(af, destination, 'actions')
            row['files'].append({'path': str(action_path), 'sha256': sha256(action_path), 'role': 'CORPORATE_ACTIONS', 'row_count': len(af)})
            row['actions_catalog_record'] = {'dataset': 'corporate_actions_yahoo', 'ticker': ticker,
                'adjustment': '', 'path': str(action_path), 'row_count': len(af), 'min_date': af.date.min(),
                'max_date': af.date.max(), 'source': SOURCE, 'lineage': {**lineage, 'role': 'PROVIDER_CORPORATE_ACTIONS', 'price_basis': 'NOT_APPLICABLE'}}
        row.update(status='SUCCESS', row_count=len(frame), min_date=frame.date.min(), max_date=frame.date.max(), rejected_row_count=len(rejected))
    except (ValueError, RuntimeError) as exc:
        row['error'] = str(exc)
    write_json(checkpoint, row)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2018-01-01')
    parser.add_argument('--end', required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--tickers', nargs='+')
    parser.add_argument('--symbol-map', type=Path, help='JSON ticker -> {provider_symbol,evidence_url}; explicit verified aliases only')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--retry-transient-failures', action='store_true',
                        help='Retry cached network/HTTP 5xx failures, preserving earlier attempt evidence')
    args = parser.parse_args(argv)
    start, end = (datetime.strptime(s, '%Y-%m-%d').date() for s in (args.start, args.end))
    if start > end or end >= datetime.now(timezone.utc).date():
        raise ValueError('Require a past completed-date window')
    if not 1 <= args.workers <= 4:
        raise ValueError('workers must be 1..4')
    paths = resolve()
    mappings = json.loads(args.symbol_map.read_text(encoding='utf-8')) if args.symbol_map else {}
    if not isinstance(mappings, dict):
        raise ValueError('symbol map must be an object')
    for ticker, mapping in mappings.items():
        if not isinstance(mapping, dict) or set(mapping) != {'provider_symbol', 'evidence_url'}:
            raise ValueError('symbol map requires provider_symbol and evidence_url')
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9._/\-]{0,31}', str(mapping['provider_symbol'])) or '..' in mapping['provider_symbol']:
            raise ValueError('invalid provider symbol mapping')
        if not str(mapping['evidence_url']).startswith('https://'):
            raise ValueError('mapping requires HTTPS evidence')
    catalog = paths.cache_root / 'derived/data_catalog/catalog.sqlite3'
    if args.tickers:
        tickers = sorted(set(args.tickers))
    else:
        from scripts.storage.manage_data import acquisition_tickers
        from scripts.storage.storage_r2a import DataStore
        tickers = acquisition_tickers(DataStore())
    print(json.dumps({'status': 'PLAN', 'count': len(tickers), 'start': str(start), 'end': str(end), 'provider': SOURCE}), flush=True)
    if not args.execute:
        return 0
    root = args.work_root.resolve()
    if paths.cache_root not in root.parents:
        raise ValueError('work root must be within configured cache root')
    for part in ['raw', 'checkpoints']:
        (root / part).mkdir(parents=True, exist_ok=True)
    gate = RequestGate()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(acquire_one, t, mappings.get(t, {}).get('provider_symbol', t), str(start), str(end),
            root, paths.data_root, gate, args.retry_transient_failures, mappings.get(t, {}).get('evidence_url')): t for t in tickers}
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            if len(results) % 25 == 0 or row['status'] != 'SUCCESS':
                print(json.dumps({'completed': len(results), 'total': len(tickers), 'ticker': row['contract']['ticker'], 'status': row['status'], 'error': row.get('error')}), flush=True)
    results.sort(key=lambda x: x['contract']['ticker'])
    report = {'schema_version': 1, 'provider': SOURCE, 'start': str(start), 'end': str(end),
        'completed_at': utc_now(), 'attempted_symbols': len(results),
        'successful_symbols': sum(r['status'] == 'SUCCESS' for r in results),
        'target_reached_symbols': sum(r.get('max_date') == str(end) for r in results), 'results': results}
    write_json(root / 'acquisition_report.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
