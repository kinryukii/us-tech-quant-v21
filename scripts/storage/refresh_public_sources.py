"""Versioned public data acquisition using the existing Cboe and FAST6 parsers.

This writes new snapshots only. It does not alter research features, frozen
inputs, a catalog, or its current pointers. BLS records are schedule metadata.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
from importlib.metadata import version
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_vix(repo):
    path = repo / "scripts/v22/v22_056_fast3_cboe_daily_vix_ingest_and_pit_regime_r1.py"
    spec = importlib.util.spec_from_file_location("existing_vix_ingest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def describe_parquet(frame, path, date_column):
    frame.to_parquet(path, index=False)
    check = pd.read_parquet(path)
    if len(frame) != len(check) or list(frame.columns) != list(check.columns):
        raise ValueError("Parquet roundtrip metadata mismatch")
    dates = pd.to_datetime(check[date_column], errors="raise")
    return {"path": str(path.resolve()), "sha256": digest(path),
            "row_count": len(check), "columns": list(check.columns),
            "date_column": date_column,
            "min_date": dates.min().strftime("%Y-%m-%d"),
            "max_date": dates.max().strftime("%Y-%m-%d")}


def annotate_vix_calendar(frame):
    """Expose XNYS alignment without replacing the source's own date semantics."""
    import exchange_calendars as calendars
    frame = frame.copy()
    dates = pd.to_datetime(frame.DATE, errors="raise").dt.normalize()
    calendar = calendars.get_calendar("XNYS", start=dates.min() - pd.Timedelta(days=7),
                                      end=dates.max() + pd.Timedelta(days=7))
    sessions = calendar.sessions.tz_localize(None) if calendar.sessions.tz is not None else calendar.sessions
    frame["is_xnys_session"] = dates.isin(sessions)
    frame["calendar_alignment_status"] = np.where(frame.is_xnys_session,
                                                   "XNYS_SESSION", "OFFICIAL_ROW_OUTSIDE_XNYS_SESSION")
    frame["official_open_outside_high_low"] = (frame.OPEN < frame.LOW) | (frame.OPEN > frame.HIGH)
    metadata = {"reference_calendar": "XNYS", "library": "exchange_calendars",
                "library_version": version("exchange-calendars"),
                "semantics": "CROSS_MARKET_ALIGNMENT_REFERENCE_NOT_CBOE_CALENDAR_AUTHORITY",
                "outside_xnys_session_rows": int((~frame.is_xnys_session).sum()),
                "official_open_outside_high_low_rows": int(frame.official_open_outside_high_low.sum()),
                "retention": "ALL_OFFICIAL_VALUES_AND_DATES_PRESERVED"}
    return frame, metadata


def acquire_vix(repo, root, target):
    module = load_vix(repo)
    raw = module.download_official_csv()
    observed = utc_now()
    raw_path = root / "VIX_History.csv"
    raw_path.write_bytes(raw)
    raw_sha = digest(raw_path)
    frame = module.normalize_vix_csv(raw)
    if not np.isfinite(frame[["OPEN", "HIGH", "LOW", "CLOSE"]]).all().all():
        raise ValueError("VIX contains non-finite OHLC")
    source_max = frame.DATE.max().strftime("%Y-%m-%d")
    frame = frame.loc[frame.DATE <= pd.Timestamp(target)].copy()
    if frame.empty:
        raise ValueError("No VIX rows on or before target")
    # Retain official legacy OPEN exceptions, as the canonical source parser does.
    open_exceptions = int(((frame.OPEN < frame.LOW) | (frame.OPEN > frame.HIGH)).sum())
    frame["source"] = "CBOE_OFFICIAL"
    frame["source_id"] = str(raw_path.resolve())
    frame["observed_at"] = observed
    frame, alignment = annotate_vix_calendar(frame)
    output = describe_parquet(frame, root / "vix_daily.parquet", "DATE")
    return {"status": "SUCCESS", "dataset": "vix_cboe_daily", "output": output,
            "source": "CBOE_OFFICIAL", "source_url": module.SOURCE_URL,
            "raw_path": str(raw_path.resolve()), "raw_sha256": raw_sha,
            "observed_at": observed, "source_max_date": source_max,
            "target_date": target,
            "target_reached": output["max_date"] == target,
            "official_legacy_open_range_exceptions": open_exceptions,
            "calendar_alignment": alignment,
            "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
            "prior_day_features_refreshed": False}


CBOE_HISTORY_PAGE = 'https://www.cboe.com/tradable-products/vix/vix-historical-data'
CBOE_INDICES = ('VVIX', 'VIX9D', 'OVX', 'GVZ', 'VXAPL', 'VXAZN', 'VXEEM')
CBOE_TERMS = 'https://www.cboe.com/terms'


def parse_cboe_index(raw, symbol, target):
    """Preserve published values, including source anomalies, without price features."""
    if symbol not in CBOE_INDICES:
        raise ValueError('UNSUPPORTED_CBOE_INDEX')
    records = list(csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True))
    if len(records) < 2 or any(len(row) != len(records[0]) for row in records):
        raise ValueError('CBOE_CSV_ROW_WIDTH_INVALID')
    original = pd.DataFrame(records[1:], columns=records[0])
    columns = original.columns.tolist()
    if columns not in [['DATE', symbol], ['DATE', 'CLOSE'], ['DATE', 'OPEN', 'HIGH', 'LOW', 'CLOSE']]:
        raise ValueError('UNEXPECTED_CBOE_CSV_SCHEMA')
    dates = pd.to_datetime(original.DATE, format='%m/%d/%Y', errors='raise')
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('CBOE_DATE_NULL_DUPLICATE_OR_UNORDERED')
    frame = pd.DataFrame({'date': dates.dt.strftime('%Y-%m-%d'), 'index_id': symbol,
                          'source_row_number': np.arange(2, len(original) + 2)})
    for name in columns:
        frame['raw_' + name] = original[name]
        if name != 'DATE':
            numeric = pd.to_numeric(original[name], errors='raise')
            if not np.isfinite(numeric).all() or (numeric < 0).any():
                raise ValueError('CBOE_INVALID_INDEX_VALUE')
            frame['close' if name == symbol else name.lower()] = numeric
    frame['official_ohlc_range_exception'] = False
    if 'OPEN' in columns:
        frame['official_ohlc_range_exception'] = ((frame.open < frame.low) | (frame.open > frame.high)
            | (frame.close < frame.low) | (frame.close > frame.high) | (frame.high < frame.low))
    source_max = frame.date.max()
    frame = frame.loc[frame.date <= target].copy().reset_index(drop=True)
    if frame.empty:
        raise ValueError('EMPTY_CBOE_SCOPE')
    return frame, source_max


def validate_cboe_acquisition(acquisition, capture, raw_root, target):
    if acquisition['target'] != target or [i['symbol'] for i in acquisition['items']] != list(CBOE_INDICES):
        raise ValueError('CBOE_ACQUISITION_SCOPE_CHANGED')
    expected = [(acquisition['page'], CBOE_HISTORY_PAGE)] + [(item['raw'],
        f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{item["symbol"]}_History.csv')
        for item in acquisition['items']]
    for raw, url in expected:
        path = raw_root / 'cboe_indices' / (capture.cache_key(url) + '.source')
        if (Path(raw['local_path']).resolve() != path.resolve() or raw['source_reference'] != url
            or raw['source'] != 'CBOE_OFFICIAL' or raw['status'] not in {'DOWNLOADED', 'CACHED'}
            or path.stat().st_size > 8 * 1024**2 or digest(path) != raw['sha256']):
            raise ValueError('CBOE_RAW_IDENTITY_INVALID')
        meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        for name in ('source_reference', 'sha256', 'source', 'retrieval_timestamp_utc'):
            if meta[name] != raw[name]:
                raise ValueError('CBOE_RAW_SIDECAR_MISMATCH')
        observed = pd.Timestamp(raw['retrieval_timestamp_utc'])
        if pd.isna(observed) or observed.tzinfo is None:
            raise ValueError('CBOE_OBSERVATION_TIMESTAMP_REQUIRED')
    parser = capture.LinkParser()
    parser.feed(Path(acquisition['page']['local_path']).read_text(encoding='utf-8'))
    if any(url not in {href for href, label in parser.links} for raw, url in expected[1:]):
        raise ValueError('CBOE_HISTORY_NOT_EXPLICITLY_LINKED')


def acquire_cboe_indices(repo, root, target):
    """Seven explicitly linked public histories, versioned in resolved external roots."""
    import shutil
    import pyarrow.parquet as pq
    from scripts.storage import refresh_official_research_data as common
    paths = common.resolve(repo_root=repo)
    root = root.resolve()
    if not root.is_relative_to(paths.results_root):
        raise ValueError('CBOE_RESULT_ROOT_REQUIRED')
    common.snapshot_day(target)
    if shutil.disk_usage(paths.data_root).free < 20 * 1024**3:
        raise ValueError('DISK_FREE_FLOOR')
    capture = common.archive_module(repo)
    raw_root = paths.cache_root / 'official_research_intake' / root.parent.parent.name / root.parent.name / 'raw'
    def get(url, kind):
        raw = asdict(capture.acquire_url(url, 'cboe_indices', 'CBOE_OFFICIAL', kind, raw_root, 40, 0, 0))
        if raw['status'] not in {'DOWNLOADED', 'CACHED'}:
            common.save_json(root / ('failed_' + hashlib.sha256(url.encode()).hexdigest()[:12] + '.json'), raw)
            raise ValueError('CBOE_SOURCE_REQUEST_FAILED')
        path = Path(raw['local_path']).resolve()
        if not path.is_relative_to(paths.cache_root) or path.stat().st_size > 8 * 1024**2 or digest(path) != raw['sha256']:
            raise ValueError('CBOE_RAW_IDENTITY_OR_BUDGET')
        return raw, path.read_bytes()
    acquisition_path = root / 'acquisition.json'
    if acquisition_path.exists():
        acquisition = json.loads(acquisition_path.read_text(encoding='utf-8'))
        if acquisition['target'] != target:
            raise ValueError('CBOE_ACQUISITION_SCOPE_CHANGED')
    else:
        page, page_bytes = get(CBOE_HISTORY_PAGE, 'OFFICIAL_LINK_INDEX')
        parser = capture.LinkParser(); parser.feed(page_bytes.decode('utf-8'))
        links = {url for url, label in parser.links}
        items = []
        for symbol in CBOE_INDICES:
            url = f'https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv'
            if url not in links:
                raise ValueError('CBOE_HISTORY_NOT_EXPLICITLY_LINKED:' + symbol)
            raw, _ = get(url, 'DAILY_INDEX_HISTORY'); items.append({'symbol': symbol, 'raw': raw})
            time.sleep(.25)
        acquisition = {'target': target, 'page': page, 'items': items}
        common.save_json(acquisition_path, acquisition)
    validate_cboe_acquisition(acquisition, capture, raw_root, target)
    contract = {'as_of': target, 'acquisition_sha256': digest(acquisition_path),
                'normalizer_sha256': digest(__file__), 'shared_sha256': digest(common.__file__)}
    version_id = hashlib.sha256(common.json_bytes(contract)).hexdigest()[:24]
    folder = paths.data_root / 'reference/official_research/cboe_indices' / version_id
    folder.mkdir(parents=True, exist_ok=True)
    outputs = []
    for item in acquisition['items']:
        raw = item['raw']; symbol = item['symbol']
        frame, source_max = parse_cboe_index(Path(raw['local_path']).read_bytes(), symbol, target)
        frame['source'] = 'CBOE_OFFICIAL'; frame['source_id'] = raw['sha256']
        frame['source_url'] = raw['source_reference']; frame['observed_at_utc'] = raw['retrieval_timestamp_utc']
        frame['available_at_utc'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
        frame['vintage_semantics'] = common.VINTAGE
        dataset = 'cboe_' + symbol.lower() + '_daily_current'
        path = folder / (dataset + '.parquet'); temporary = path.with_suffix('.parquet.tmp')
        frame.to_parquet(temporary, index=False, compression='zstd')
        pd.testing.assert_frame_equal(frame, pd.read_parquet(temporary), check_exact=True)
        if path.exists():
            if digest(path) != digest(temporary):
                raise ValueError('PRESERVE_CBOE_EXISTING_VERSION')
            temporary.unlink()
        else:
            temporary.replace(path)
        outputs.append({'dataset': dataset, 'source': 'CBOE_OFFICIAL', 'path': str(path),
            'sha256': digest(path), 'row_count': pq.ParquetFile(path).metadata.num_rows,
            'date_column': 'date', 'min_date': frame.date.min(), 'max_date': frame.date.max(),
            'source_max_date': source_max,
            'source_raw_sha256': raw['sha256'], 'official_range_exceptions': int(frame.official_ohlc_range_exception.sum())})
    return {'status': 'VALIDATED_DATA_ONLY', 'role': 'CBOE_PUBLIC_INDEX_HISTORY', 'contract': contract,
        'outputs': outputs, 'acquisition_path': str(acquisition_path), 'terms_url': CBOE_TERMS,
        'limitations': ['Personal non-commercial research copy; Cboe copyright and notices retained in raw page.',
            'Public download does not grant redistribution or commercial-data licensing rights.',
            'Index histories may contain back-calculated or revised observations; not historical PIT.',
            'Unknown historical availability is null; no imputed dates, computed factors or futures prices.'],
        'historical_pit_certified': False, 'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
        'source': 'CBOE_OFFICIAL', 'dataset': 'cboe_index_histories'}


NFCI_COLUMNS = ('Friday_of_Week', 'NFCI', 'ANFCI', 'Risk', 'Credit', 'Leverage', 'Nonfinancial_Leverage')
NFCI_URLS = {
    'page': 'https://www.chicagofed.org/research/data/nfci/current-data',
    'provider': 'https://data.chicagofed.org/cfed-drm-chicago/NFCI',
    'csv': 'https://api.data.chicagofed.org/NFCI/nfci-data-series-csv.csv',
    'configuration': 'https://api.data.chicagofed.org/NFCI/manifest.json',
    'headline': 'https://api.data.chicagofed.org/NFCI/nfci-headline-and-blurb.html',
    'faq': 'https://api.data.chicagofed.org/NFCI/nfci-faqs-pdf.pdf',
    'technical': 'https://api.data.chicagofed.org/NFCI/nfci-technical-report-pdf.pdf',
    'terms': 'https://www.chicagofed.org/utilities/legal-notices',
}


def parse_nfci(raw, target):
    """Six index levels, not additive contributions; preserve every source token."""
    from decimal import Decimal
    records = list(csv.reader(io.StringIO(raw.decode('utf-8-sig')), strict=True))
    if (len(records) < 2 or records[0] != list(NFCI_COLUMNS)
            or any(len(row) != len(NFCI_COLUMNS) for row in records)):
        raise ValueError('NFCI_SCHEMA_OR_ROW_WIDTH')
    rows = []; previous = None; missing = {key: 0 for key in NFCI_COLUMNS[1:]}
    for ordinal, values in enumerate(records[1:], 2):
        day = datetime.strptime(values[0], '%m/%d/%Y').date()
        if day.weekday() != 4 or (previous is not None and (day - previous).days != 7):
            raise ValueError('NFCI_NONFRIDAY_DUPLICATE_UNORDERED_OR_WEEK_GAP')
        previous = day
        item = {'date': day.isoformat(), 'source_row_number': ordinal}
        for key, value in zip(NFCI_COLUMNS, values, strict=True):
            item['raw_' + key] = value
            if key == 'Friday_of_Week': continue
            if value == '':
                item[key.lower()] = None; missing[key] += 1
            elif re.fullmatch(r'-?\d{1,20}(?:\.\d{1,12})?', value):
                item[key.lower()] = Decimal(value)
            else:
                raise ValueError('NFCI_UNKNOWN_OR_NONFINITE_NUMBER')
        if item['date'] <= target: rows.append(item)
    if not rows: raise ValueError('NFCI_EMPTY_TARGET_SCOPE')
    return rows, {'source_rows': len(records) - 1, 'source_max_date': previous.isoformat(),
                  'source_missing_cells': missing, 'all_source_dates_weekly_friday': True}


def normalize_nfci(acquisition_path, target, *, paths=None):
    """Offline normalization of a frozen official acquisition; no network/catalog."""
    import shutil
    import pyarrow as pa
    import pyarrow.parquet as pq
    from scripts.storage import refresh_official_research_data as common
    from scripts.storage.restore_sec_data import file_identity
    paths = paths or common.resolve()
    common.snapshot_day(target)
    acquisition_path = Path(acquisition_path).resolve()
    if not acquisition_path.is_relative_to(paths.results_root / 'official_research_intake'):
        raise ValueError('NFCI_ACQUISITION_OUTSIDE_RESULTS')
    acquisition = json.loads(acquisition_path.read_text(encoding='utf-8'))
    run_id = acquisition.get('run_id', '')
    if (acquisition.get('role') != 'CHICAGO_FED_NFCI_RAW_INTAKE'
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id)
            or set(acquisition.get('inputs', {})) != set(NFCI_URLS)):
        raise ValueError('NFCI_ACQUISITION_SCOPE')
    report_root = paths.results_root / 'official_research_intake' / run_id / 'nfci'
    if acquisition_path != (report_root / 'acquisition.json').resolve():
        raise ValueError('NFCI_RUN_PATH_MISMATCH')
    raw_root = paths.cache_root / 'official_research_intake' / run_id / 'nfci/raw/nfci'
    bodies = {}; receipts = {}; identities = {}; total = 0
    for name, url in NFCI_URLS.items():
        reference = acquisition['inputs'][name]
        receipt_path = report_root / 'requests' / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        if file_identity(receipt_path) != reference:
            raise ValueError('NFCI_REQUEST_RECEIPT_IDENTITY')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        raw = receipt['raw']; response = receipt['http_response']
        path = raw_root / (hashlib.sha256(url.encode()).hexdigest() + '.source')
        if (Path(raw['local_path']).resolve() != path.resolve() or raw['source_reference'] != url
                or raw['source'] != 'CHICAGO_FED_OFFICIAL' or raw['event_family'] != 'nfci'
                or raw['status'] != 'DOWNLOADED' or response['status'] != 200
                or response.get('final_url') != url or digest(path) != raw['sha256']):
            raise ValueError('NFCI_RAW_SOURCE_OR_HTTP_IDENTITY')
        size = path.stat().st_size; total += size
        if total > 20 * 1024**2: raise ValueError('NFCI_RAW_BUDGET')
        meta_path = path.with_suffix('.json')
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        if meta['byte_count'] != size or response['bytes'] != size or any(meta[key] != raw[key]
                for key in ('sha256', 'source_reference', 'source', 'event_family', 'document_kind', 'retrieval_timestamp_utc')):
            raise ValueError('NFCI_SIDECAR_IDENTITY')
        observed = pd.Timestamp(raw['retrieval_timestamp_utc'])
        if pd.isna(observed) or observed.tzinfo is None:
            raise ValueError('NFCI_OBSERVED_TIMESTAMP')
        bodies[name] = path.read_bytes(); receipts[name] = receipt
        identities[name] = {'raw': file_identity(path), 'sidecar': file_identity(meta_path),
                            'receipt': reference, 'observed_at_utc': raw['retrieval_timestamp_utc']}
    if NFCI_URLS['provider'].encode() not in bodies['page']:
        raise ValueError('NFCI_PROVIDER_NOT_IN_OFFICIAL_PAGE')
    provider = json.loads(bodies['provider'])
    if not isinstance(provider.get('data'), dict) or provider['data'].get('nfciDataSeriesCsvCsv') != NFCI_URLS['csv']:
        raise ValueError('NFCI_CSV_NOT_IN_OFFICIAL_PROVIDER')
    for name in NFCI_URLS:
        expected_parent = (None if name in {'page', 'terms'} else
                           acquisition['inputs']['page' if name == 'provider' else 'provider'])
        if receipts[name].get('parent') != expected_parent:
            raise ValueError('NFCI_PARENT_REQUEST_CHAIN')
        if name not in {'page', 'terms', 'provider'} and NFCI_URLS[name] not in provider['data'].values():
            raise ValueError('NFCI_RESOURCE_NOT_IN_OFFICIAL_PROVIDER')
    contract = {'as_of': target, 'acquisition': file_identity(acquisition_path),
                'normalizer_sha256': digest(__file__), 'shared_sha256': digest(common.__file__), 'inputs': identities}
    manifest_path = report_root / 'manifest.json'
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding='utf-8'))
        if old['contract'] != contract or old['status'] != 'VALIDATED_DATA_ONLY':
            raise ValueError('NFCI_EXISTING_CONTRACT_CHANGED_USE_NEW_RUN')
        for output in old['outputs']:
            path = Path(output['path']).resolve()
            if not path.is_relative_to(paths.data_root) or digest(path) != output['sha256']:
                raise ValueError('NFCI_EXISTING_OUTPUT_CHANGED')
        return old
    rows, audit = parse_nfci(bodies['csv'], target)
    csv_raw = receipts['csv']['raw']
    for row in rows:
        row.update(source='CHICAGO_FED_OFFICIAL', source_url=NFCI_URLS['csv'], source_id=csv_raw['sha256'],
                   observed_at_utc=csv_raw['retrieval_timestamp_utc'], available_at_utc=None,
                   vintage_semantics=common.VINTAGE)
    columns = set(key.lower() for key in NFCI_COLUMNS[1:])
    schema = pa.schema([(key, pa.decimal128(38, 12) if key in columns else pa.int64() if key == 'source_row_number'
                         else pa.timestamp('us', tz='UTC') if key == 'available_at_utc' else pa.string()) for key in rows[0]])
    table = pa.Table.from_pylist(rows, schema=schema)
    if min(shutil.disk_usage(paths.data_root).free, shutil.disk_usage(paths.cache_root).free) < 20 * 1024**3:
        raise ValueError('NFCI_DISK_FREE_FLOOR')
    version = hashlib.sha256(common.json_bytes(contract)).hexdigest()[:24]
    dataset = 'chicago_fed_nfci_weekly_current'
    folder = paths.data_root / 'reference/official_research/nfci' / version
    path = folder / (dataset + '.parquet'); temporary = path.with_suffix('.parquet.tmp')
    if path.exists() or temporary.exists(): raise ValueError('NFCI_PRIOR_PARTIAL_VERSION_PRESERVED')
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, temporary, compression='zstd')
    if not table.equals(pq.read_table(temporary)): raise ValueError('NFCI_PARQUET_ROUNDTRIP')
    temporary.replace(path)
    result = {'status': 'VALIDATED_DATA_ONLY', 'role': 'CHICAGO_FED_NFCI_INTAKE', 'contract': contract,
        'outputs': [{'dataset': dataset, 'source': 'CHICAGO_FED_OFFICIAL', 'path': str(path), 'sha256': digest(path),
                     'bytes': path.stat().st_size, 'row_count': len(rows), 'date_column': 'date',
                     'min_date': rows[0]['date'], 'max_date': rows[-1]['date'], 'source_max_date': audit['source_max_date'],
                     'source_raw_sha256': csv_raw['sha256']}],
        'source': 'CHICAGO_FED_OFFICIAL', 'dataset': dataset, 'acquisition_path': str(acquisition_path), 'qc': audit,
        'series_semantics': {'NFCI': 'STANDARDIZED_BROAD_FINANCIAL_CONDITIONS_INDEX',
            'ANFCI': 'INDEX_ADJUSTED_FOR_ECONOMIC_ACTIVITY_AND_INFLATION',
            'Risk': 'STANDARDIZED_RISK_SUBINDEX', 'Credit': 'STANDARDIZED_CREDIT_SUBINDEX',
            'Leverage': 'STANDARDIZED_LEVERAGE_SUBINDEX', 'Nonfinancial_Leverage': 'STANDARDIZED_NONFINANCIAL_LEVERAGE_SUBINDEX'},
        'index_not_contribution': True, 'unit': 'STANDARDIZED_INDEX', 'date_semantics': 'FRIDAY_OF_OBSERVATION_WEEK_NOT_PUBLICATION_DATE',
        'release_schedule': 'Wednesday 08:30 America/New_York for prior Friday; Thursday when a federal holiday falls Monday through Wednesday.',
        'historical_availability_semantics': 'UNKNOWN_NULL_NOT_INFERRED_FROM_WEEK_END_OR_HTTP_LAST_MODIFIED',
        'revision_semantics': 'FULL_HISTORY_CAN_CHANGE_WITH_INPUT_REVISIONS_AND_REESTIMATED_WEIGHTS',
        'launch_boundary': 'OBSERVATIONS_FROM_1971_ARE_RECONSTRUCTED_HISTORY_NOT_PROOF_OF_PUBLIC_AVAILABILITY_SINCE_1971; EXACT_INITIAL_PUBLICATION_NOT_CERTIFIED',
        'terms_url': NFCI_URLS['terms'], 'usage_scope': 'CURRENT_PERSONAL_NONCOMMERCIAL_RESEARCH_ONLY',
        'historical_pit_certified': False, 'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
        'limitations': ['Federal Reserve Bank of Chicago source attribution retained; no redistribution or commercial license inferred.',
                       'Risk, Credit and Leverage are standardized subindexes, not additive contributions to NFCI.',
                       'Empty source cells remain null; all original numeric/date strings retained.']}
    if file_identity(acquisition_path) != contract['acquisition']: raise ValueError('NFCI_INPUT_CHANGED_DURING_NORMALIZATION')
    common.save_json(manifest_path, result)
    return result


def parse_bls_schedule(raw, year):
    from fast6.archive import TableParser, parse_source_datetime
    parser = TableParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    rows = []
    rejected = []
    for cells in parser.rows:
        if len(cells) < 3 or str(year) not in cells[0]:
            continue
        try:
            timestamp = parse_source_datetime(cells[0], cells[1])
        except ValueError as exc:
            rejected.append({"cells": cells, "error": str(exc)})
            continue
        if timestamp.astimezone(ZoneInfo("America/New_York")).year != year:
            continue
        local = pd.Timestamp(timestamp).tz_convert("America/New_York")
        rows.append({"release_date": local.strftime("%Y-%m-%d"),
                     "release_time_et": local.strftime("%H:%M"),
                     "timezone": "America/New_York",
                     "scheduled_time_utc": timestamp.isoformat().replace("+00:00", "Z"),
                     "release_label": cells[-1], "source_year": year})
    if rejected:
        raise ValueError(f"Unparsed dated BLS calendar rows: {rejected[:5]}")
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("No BLS calendar rows parsed; source layout needs review")
    if frame.duplicated(["scheduled_time_utc", "release_label"]).any():
        raise ValueError("Duplicate BLS calendar release keys")
    return frame.sort_values(["scheduled_time_utc", "release_label"]).reset_index(drop=True)


def acquire_bls(repo, root, year, target):
    sys.path.insert(0, str(repo / "fast6/src"))
    from fast6.acquisition import acquire_url
    url = f"https://www.bls.gov/schedule/{year}/home.htm"
    doc = acquire_url(url, "BLS_CALENDAR", "BLS_OFFICIAL", "release_schedule",
                      root / "raw", timeout=30, retries=0, backoff=1.0)
    result = {"dataset": "bls_release_calendar", "source_url": url,
              "attempted_at": utc_now(), "acquisition": asdict(doc),
              "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
              "content_semantics": "SCHEDULE_ONLY_ACTUAL_RELEASE_UNVERIFIED"}
    if doc.status == "FAILED":
        return {**result, "status": "FAILED"}
    frame = parse_bls_schedule(Path(doc.local_path).read_bytes(), year)
    frame["source"] = "BLS_OFFICIAL"
    frame["source_url"] = url
    frame["source_id"] = doc.local_path
    frame["observed_at"] = doc.retrieval_timestamp_utc
    frame["quality_flag"] = result["content_semantics"]
    frame["vintage_semantics"] = result["vintage_semantics"]
    output = describe_parquet(frame, root / "bls_release_calendar.parquet", "release_date")
    return {**result, "status": "SUCCESS", "output": output,
            "raw_path": doc.local_path, "raw_sha256": doc.sha256,
            "observed_at": doc.retrieval_timestamp_utc,
            "rows_scheduled_on_or_before_target": int((frame.release_date <= target).sum())}


def fred_archive_helpers(repo):
    """Load the existing FAST6 table/time utilities without changing sys.path."""
    if "fast6" not in sys.modules:
        directory = Path(repo) / "fast6/src/fast6"
        spec = importlib.util.spec_from_file_location("fast6", directory / "__init__.py",
                                                     submodule_search_locations=[str(directory)])
        if spec is None or spec.loader is None:
            raise ImportError("Existing FAST6 parser package unavailable")
        package = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = package
        spec.loader.exec_module(package)
    from fast6.archive import TableParser, parse_source_datetime
    return TableParser, parse_source_datetime


def parse_fred_schedule(raw, year, release_id, expected_label, repo=Path("D:/us-tech-quant")):
    """Parse FRED's dated table and explicit US Central schedule, never values."""
    TableParser, parse_source_datetime = fred_archive_helpers(repo)

    class FredTable(TableParser):
        def __init__(self):
            super().__init__()
            self.depth = 0; self.title = []; self.in_title = False
            self.canonical = []; self.description = ""; self.row_links = []; self.links = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "title": self.in_title = True
            if tag == "link" and attrs.get("rel") == "canonical": self.canonical.append(attrs.get("href", ""))
            if tag == "meta" and attrs.get("name") == "description": self.description = attrs.get("content", "")
            if tag == "div" and (self.depth or attrs.get("id") == "release-dates-pager"): self.depth += 1
            if self.depth:
                if tag == "tr": self.links = []
                if tag == "a" and urlparse(attrs.get("href", "")).path == "/release":
                    self.links.append(parse_qs(urlparse(attrs["href"]).query).get("rid"))
                super().handle_starttag(tag, list(attrs.items()))

        def handle_data(self, data):
            if self.in_title: self.title.append(data)
            if self.depth: super().handle_data(data)

        def handle_endtag(self, tag):
            if tag == "title": self.in_title = False
            if self.depth:
                if tag == "tr" and self._row: self.row_links.append(self.links)
                super().handle_endtag(tag)
                if tag == "div": self.depth -= 1

    html = raw.decode("utf-8")
    parser = FredTable(); parser.feed(html); parser.close()
    title = " ".join("".join(parser.title).split())
    expected_title = f"{year} Economic Release Calendar - {expected_label} | FRED | St. Louis Fed"
    if title != expected_title or len(parser.canonical) != 1:
        raise ValueError("FRED page title/canonical identity mismatch")
    canonical = urlparse(parser.canonical[0]); query = parse_qs(canonical.query)
    expected_query = {"rid": [str(release_id)], "view": ["year"],
                      "vs": [f"{year}-01-01"], "ve": [f"{year}-12-31"]}
    if canonical.scheme != "https" or canonical.netloc != "fred.stlouisfed.org" or canonical.path != "/releases/calendar" or any(query.get(k) != v for k, v in expected_query.items()):
        raise ValueError("FRED canonical release/year identity mismatch")
    if "All times are US Central Time." not in " ".join(re.sub(r"<[^>]+>", " ", html).split()):
        raise ValueError("FRED explicit Central timezone declaration missing")
    count = re.fullmatch(r"(\d+) economic release dates for release: " + re.escape(expected_label) + r"\. FRED:.*", parser.description)
    if count is None:
        raise ValueError("FRED release/count description mismatch")
    rows = []; pending = None; complete_pager = False
    for cells, links in zip(parser.rows, parser.row_links, strict=True):
        if len(cells) == 1:
            pager = re.fullmatch(r"Releases 1 - (\d+) of (\d+)", cells[0])
            if pager:
                if pending is not None or complete_pager or int(pager[1]) != int(pager[2]) or int(pager[2]) != len(rows):
                    raise ValueError("Incomplete or repeated FRED pagination")
                complete_pager = True
                continue
            match = re.fullmatch(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) (.+?)( Updated)?", cells[0])
            if not match or pending is not None:
                raise ValueError("Unparsed or unused FRED date row")
            parsed_day = datetime.strptime(match[2], "%B %d, %Y")
            if parsed_day.year != year or parsed_day.strftime("%A") != match[1]:
                raise ValueError("FRED row year/weekday mismatch")
            pending = (parsed_day.date().isoformat(), bool(match[3]))
            continue
        if pending is None:
            if links: raise ValueError("FRED release without date")
            continue  # Table sorting header only.
        if len(cells) != 2 or links != [[str(release_id)]] or cells[1] != expected_label:
            raise ValueError("FRED row release identity mismatch")
        release_date, updated = pending
        unknown = cells[0].strip().upper() in {"", "N/A", "NA", "TBD"}
        stamp = None if unknown else parse_source_datetime(release_date, cells[0], source_timezone="America/Chicago")
        local = None if stamp is None else pd.Timestamp(stamp).tz_convert("America/New_York")
        rows.append({"release_id": int(release_id), "release_label": expected_label,
            "release_date": release_date, "release_time_et": None if local is None else local.strftime("%H:%M"),
            "timezone": "America/New_York", "source_timezone": "America/Chicago",
            "source_time_text": cells[0], "scheduled_time_utc": None if stamp is None else stamp.isoformat().replace("+00:00", "Z"),
            "schedule_time_status": "UNKNOWN_SOURCE_TIME" if unknown else "EXPLICIT_SOURCE_TIME",
            "source_updated_marker": updated, "source_year": year})
        pending = None
    frame = pd.DataFrame(rows)
    if pending is not None or frame.empty or not complete_pager or len(frame) != int(count[1]):
        raise ValueError("Empty/incomplete FRED calendar or advertised count mismatch")
    if frame.duplicated(["release_id", "release_date"]).any():
        raise ValueError("Duplicate FRED calendar release keys")
    return frame.sort_values(["release_date", "release_id"]).reset_index(drop=True)


def normalize_fred_calendar(download_manifest, output_root, target_date, repo=Path("D:/us-tech-quant")):
    """Offline, immutable subset of official FRED release schedules through target."""
    from scripts.storage.restore_sec_data import file_identity, write_frame
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    source_path = Path(download_manifest).resolve()
    raw_manifest = source_path.read_bytes()
    manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
    manifest = json.loads(raw_manifest)
    if manifest.get("provider") != "FRED_ST_LOUIS_FED" or manifest.get("schema_version") != 1:
        raise ValueError("FRED download manifest identity mismatch")
    frames, inputs, audits = [], [], []
    seen = set()
    source_years = set()
    for item in manifest["items"]:
        rid = item["release_id"]
        if type(rid) is not int:
            raise ValueError("FRED release ID must be an integer")
        url = urlparse(item["source_url"]); query = parse_qs(url.query, keep_blank_values=True)
        years = query.get("y", [])
        if (url.scheme != "https" or url.netloc != "fred.stlouisfed.org" or url.path != "/releases/calendar"
                or set(query) != {"rid", "y"} or query.get("rid") != [str(rid)]
                or len(years) != 1 or not re.fullmatch(r"[0-9]{4}", years[0])
                or not 1 <= int(years[0]) <= target.year):
            raise ValueError("FRED source URL identity mismatch")
        year = int(years[0])
        if (year, rid) in seen or item["http_status"] != 200:
            raise ValueError("Duplicate or unsuccessful FRED source")
        seen.add((year, rid)); source_years.add(year)
        path = Path(item["path"]).resolve(); raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"] or len(raw) != item["size_bytes"]:
            raise ValueError("FRED raw source hash/size mismatch")
        observed = pd.Timestamp(item["observed_at"])
        if observed.tzinfo is None or pd.isna(observed):
            raise ValueError("FRED observed_at requires explicit timezone")
        full = parse_fred_schedule(raw, year, rid, item["expected_label"], repo)
        frame = full.loc[full.release_date <= target_date].copy()
        frame["source"] = "FRED_ST_LOUIS_FED"
        frame["source_url"] = item["source_url"]; frame["source_id"] = item["sha256"]
        frame["observed_at"] = item["observed_at"]
        frame["quality_flag"] = "SCHEDULE_ONLY_ACTUAL_RELEASE_UNVERIFIED"
        frame["vintage_semantics"] = "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT"
        frames.append(frame)
        inputs.append({"path": str(path), "sha256": item["sha256"], "observed_at": item["observed_at"]})
        audits.append({"release_id": rid, "release_label": item["expected_label"], "source_year": year, "full_year_rows": len(full),
                       "rows_on_or_before_target": len(frame), "source_max_date": full.release_date.max(),
                       "unknown_time_rows": int(full.scheduled_time_utc.isna().sum())})
    if not frames or sum(map(len, frames)) == 0:
        raise ValueError("No FRED releases on or before target")
    declared = manifest.get("source_years")
    if declared is not None and (not isinstance(declared, list) or any(type(year) is not int for year in declared)
                                 or declared != sorted(source_years)):
        raise ValueError("FRED declared source years mismatch")
    if len(source_years) > 1 or declared is not None:
        required = {10, 11, 46, 50, 192}
        if any({rid for seen_year, rid in seen if seen_year == year} != required for year in source_years):
            raise ValueError("FRED multi-year source requires all five release IDs for every year")
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != manifest_sha:
        raise ValueError("FRED download manifest changed during parse")
    result = pd.concat(frames, ignore_index=True).sort_values(["release_date", "release_id"]).reset_index(drop=True)
    if result.duplicated(["release_id", "release_date"]).any():
        raise ValueError("Duplicate combined FRED calendar release keys")
    release_ids = sorted({rid for _, rid in seen})
    contract = {"schema_version": 1, "provider": "FRED_ST_LOUIS_FED", "target_date": target_date,
                "download_manifest": {"path": str(source_path), "sha256": manifest_sha}, "inputs": inputs,
                "scope": "EXPLICIT_FRED_RELEASE_IDS_NOT_COMPLETE_BLS_CALENDAR", "release_ids": release_ids}
    if len(source_years) > 1:
        contract["source_years"] = sorted(source_years)
    else:
        for audit in audits:
            audit.pop("source_year")  # Keep existing single-year manifest bytes.
    version_id = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:24]
    directory = Path(output_root).resolve() / "versions" / version_id
    output = write_frame(directory / "fred_release_calendar.parquet", result)
    lineage = {"schema_version": 1, "role": "PROVIDER_RELEASE_SCHEDULE", "date_column": "release_date",
        "inputs": inputs, "download_manifest": contract["download_manifest"], "source_timezone": "America/Chicago",
        "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
        "content_semantics": "SCHEDULE_ONLY_ACTUAL_RELEASE_UNVERIFIED",
        "scope": contract["scope"], "release_ids": release_ids,
        "fred_updated_marker_semantics": "PAGE_STATUS_NOT_ACTUAL_PUBLICATION_TIMESTAMP",
        "availability_semantics": "RELEASE_DATES_DO_NOT_GUARANTEE_FRED_DATA_AVAILABILITY"}
    if len(source_years) > 1:
        lineage["source_years"] = contract["source_years"]
    record = {"dataset": "fred_release_calendar", "ticker": "", "adjustment": "", "path": output["path"],
        "row_count": len(result), "min_date": result.release_date.min(), "max_date": result.release_date.max(),
        "source": "FRED_ST_LOUIS_FED", "lineage": lineage}
    report = {"status": "SUCCESS", "contract": contract, "output": output, "catalog_record": record,
              "source_audits": audits, "catalog_written": False, "network_requests": 0}
    report_path = directory / "fred_calendar_manifest.json"
    report_bytes = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    if report_path.exists() and report_path.read_bytes() != report_bytes:
        raise ValueError("Preserving different existing FRED manifest")
    report_path.write_bytes(report_bytes)
    return {"status": "SUCCESS", "manifest": file_identity(report_path), "rows": len(result), "source_audits": audits}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("D:/us-tech-quant"))
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--sources", nargs="+", choices=["vix", "bls", "cboe_indices"], default=["vix", "bls"])
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    target = datetime.strptime(args.target_date, "%Y-%m-%d").date()
    if not args.execute:
        print(json.dumps({"status": "DRY_RUN", "sources": args.sources,
                          "target_date": str(target), "work_root": str(args.work_root)}))
        return 0
    run_root = args.work_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_root.mkdir(parents=True, exist_ok=False)
    results = []
    for source in dict.fromkeys(args.sources):
        destination = run_root / source
        destination.mkdir()
        try:
            result = (acquire_cboe_indices(args.repo, destination, str(target)) if source == 'cboe_indices'
                      else acquire_vix(args.repo, destination, str(target)) if source == "vix"
                      else acquire_bls(args.repo, destination, target.year, str(target)))
        except Exception as exc:
            result = {"status": "FAILED", "source": source, "attempted_at": utc_now(),
                      "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        (destination / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result), flush=True)
    report = {"target_date": str(target), "created_at": utc_now(), "results": results}
    path = run_root / "acquisition_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path)}), flush=True)
    return 0 if all(x["status"] in {"SUCCESS", "VALIDATED_DATA_ONLY"} for x in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
