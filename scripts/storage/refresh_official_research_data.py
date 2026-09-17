"""Fixed FINRA CNMS and Treasury adapters; reuse storage, raw archive and catalog.

Default pre-2026 intake; --as-of enables separately named current snapshots.
Current downloads are not original PIT vintages; 2026+ rows are observation only.
No security remapping, fitting, price joins or automatic research promotion.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from decimal import Decimal
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve
from scripts.storage.build_data_catalog import register_file, sha256, utc_now
from scripts.storage.storage_r2a import DataStore, CATALOG_ROLE, CATALOG_SCHEMA_VERSION

VINTAGE = 'CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT'
FINRA = 'finra_cnms_short_volume_pre2026'
NOMINAL = 'treasury_nominal_par_yields_pre2026'
REAL = 'treasury_real_par_yields_pre2026'
DATASETS = {FINRA, NOMINAL, REAL}
CURRENT_NAMES = {name: name.replace('_pre2026', '_current') for name in DATASETS}
CURRENT_DATASETS = set(CURRENT_NAMES.values())
VOLUME_COLUMNS = ['short_volume', 'short_exempt_volume', 'total_volume']
FINRA_URL = 'https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt'
TREASURY_URL = ('https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
                '?data={kind}&field_tdr_date_value={year}')
KINDS = {NOMINAL: 'daily_treasury_yield_curve', REAL: 'daily_treasury_real_yield_curve'}
KINDS.update({CURRENT_NAMES[name]: kind for name, kind in list(KINDS.items())})
NS = {'a': 'http://www.w3.org/2005/Atom',
      'm': 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata'}
TENORS = {'1MONTH': 1., '1_5MONTH': 1.5, '2MONTH': 2., '3MONTH': 3., '4MONTH': 4.,
          '6MONTH': 6., **{f'{y}YEAR': float(y * 12) for y in (1, 2, 3, 5, 7, 10, 20, 30)}}


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json_bytes(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('EXISTING_IMMUTABLE_RECORD_DIFFERS')
        return
    with path.open('xb') as handle:
        handle.write(raw)


def snapshot_day(as_of):
    if as_of is None:
        return None
    day = date.fromisoformat(as_of)
    if not date(2026, 1, 1) <= day <= date.today():
        raise ValueError('CURRENT_SNAPSHOT_AS_OF_OUTSIDE_AUTHORIZED_DATE_SCOPE')
    return day


def is_finra(dataset):
    return dataset in {FINRA, CURRENT_NAMES[FINRA]}


def parse_finra(raw, expected_date, *, as_of=None):
    """Preserve provider symbols; ShortVolume already includes exempt shares."""
    day = date.fromisoformat(expected_date)
    upper = snapshot_day(as_of)
    if upper is None and not date(2018, 8, 1) <= day < date(2026, 1, 1):
        raise ValueError('FINRA_PRE2026_INTEGER_SCHEMA_ONLY')
    if upper is not None and not date(2018, 8, 1) <= day <= upper:
        raise ValueError('FINRA_OUTSIDE_SNAPSHOT_BOUNDARY')
    lines = raw.decode('utf-8-sig').splitlines()
    header = 'Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market'
    if len(lines) < 2 or lines[0] != header or not re.fullmatch(r'\d+', lines[-1]):
        raise ValueError('FINRA_HEADER_OR_TRAILER_INVALID')
    if int(lines[-1]) != len(lines) - 2:
        raise ValueError('FINRA_TRAILER_COUNT_MISMATCH')
    frame = pd.read_csv(io.StringIO('\n'.join(lines[:-1])), sep='|', dtype=str, keep_default_na=False)
    if not frame.Date.eq(day.strftime('%Y%m%d')).all():
        raise ValueError('FINRA_WRONG_REQUESTED_DATE')
    if frame.Symbol.duplicated().any() or not frame.Symbol.str.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_\-]{0,13}').all():
        raise ValueError('FINRA_SYMBOL_INVALID_OR_DUPLICATED')
    if not frame.Market.map(lambda x: bool(x) and set(x.split(',')) <= {'B', 'Q', 'N', 'D'}
                            and len(x.split(',')) == len(set(x.split(',')))).all():
        raise ValueError('FINRA_CONSOLIDATED_FACILITY_INVALID')
    for column in ['ShortVolume', 'ShortExemptVolume', 'TotalVolume']:
        fractional = upper is not None and day >= date(2026, 2, 23)
        pattern = r'\d{1,18}(?:\.\d{1,6})?' if fractional else r'\d{1,18}'
        if not frame[column].str.fullmatch(pattern).all():
            if fractional:
                raise ValueError('FINRA_VOLUME_NONNEGATIVE_MAX_SIX_DECIMALS_REQUIRED')
            raise ValueError('FINRA_VOLUME_MUST_BE_NONNEGATIVE_INTEGER')
        frame[column] = (frame[column].map(lambda value: Decimal(value).quantize(Decimal('.000001')))
                         if upper is not None else frame[column].astype('int64'))
    if not ((frame.ShortExemptVolume <= frame.ShortVolume) & (frame.ShortVolume <= frame.TotalVolume)).all():
        raise ValueError('FINRA_VOLUME_ORDER_INVALID')
    frame = frame.rename(columns={'Symbol': 'provider_symbol', 'ShortVolume': 'short_volume',
        'ShortExemptVolume': 'short_exempt_volume', 'TotalVolume': 'total_volume', 'Market': 'reporting_facilities'})
    frame['date'] = expected_date
    frame['short_volume_share'] = (frame.short_volume.astype(float) /
                                   frame.total_volume.astype(float).replace(0, np.nan))
    frame['volume_status'] = np.where(frame.total_volume.eq(0), 'ZERO_TOTAL_VOLUME', 'OBSERVED')
    return frame.drop(columns='Date').sort_values('provider_symbol').reset_index(drop=True)


def parse_treasury(raw, dataset, year, *, as_of=None):
    upper = snapshot_day(as_of)
    allowed = CURRENT_DATASETS if upper is not None else DATASETS
    if dataset not in KINDS or dataset not in allowed or not 2020 <= year <= (upper.year if upper else 2025):
        raise ValueError('TREASURY_REQUEST_OUTSIDE_CONTRACT')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('TREASURY_XML_EXTERNAL_DECLARATION_FORBIDDEN')
    root = ET.fromstring(raw)
    if root.tag != '{' + NS['a'] + '}feed':
        raise ValueError('TREASURY_XML_FEED_INVALID')
    nominal = dataset in {NOMINAL, CURRENT_NAMES[NOMINAL]}
    prefix = 'BC_' if nominal else 'TC_'
    category = 'DailyTreasuryYieldCurveRateDatum' if nominal else 'DailyTreasuryRealYieldCurveRateDatum'
    rows = []
    for entry in root.findall('a:entry', NS):
        cat = entry.find('a:category', NS)
        if cat is None or cat.get('term', '').split('.')[-1] != category:
            raise ValueError('TREASURY_CURVE_IDENTITY_MISMATCH')
        props = entry.find('a:content/m:properties', NS)
        if props is None:
            raise ValueError('TREASURY_PROPERTIES_MISSING')
        fields = {child.tag.split('}')[-1]: child for child in props}
        if len(fields) != len(props) or 'NEW_DATE' not in fields:
            raise ValueError('TREASURY_DUPLICATE_OR_MISSING_FIELDS')
        stamp = pd.Timestamp(fields['NEW_DATE'].text)
        if stamp.tzinfo is not None or stamp.year != year or stamp != stamp.normalize():
            raise ValueError('TREASURY_WRONG_REQUESTED_YEAR_OR_DATE')
        if not {prefix + t for t in ['5YEAR', '10YEAR', '30YEAR']} <= fields.keys():
            raise ValueError('TREASURY_CORE_TENORS_MISSING')
        updated = entry.findtext('a:updated', default='', namespaces=NS)
        if not updated or pd.Timestamp(updated).tzinfo is None:
            raise ValueError('TREASURY_FEED_UPDATE_TIME_INVALID')
        for name, element in fields.items():
            if name in {'NEW_DATE', 'Id', 'DailyTreasuryRealYieldCurveRateDataId', 'BC_30YEARDISPLAY'}:
                continue
            if not name.startswith(prefix) or name[len(prefix):] not in TENORS:
                raise ValueError('TREASURY_UNKNOWN_TENOR:' + name)
            value = np.nan if element.get('{' + NS['m'] + '}null') == 'true' else float(element.text)
            if not pd.isna(value) and not np.isfinite(value):
                raise ValueError('TREASURY_NONFINITE_YIELD')
            rows.append({'date': stamp.strftime('%Y-%m-%d'), 'provider_field': name,
                'tenor_months': TENORS[name[len(prefix):]], 'yield_percent': value,
                'value_status': 'SOURCE_NULL' if pd.isna(value) else 'OBSERVED',
                'feed_updated_at_utc': updated})
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(['date', 'provider_field']).any():
        raise ValueError('TREASURY_EMPTY_OR_DUPLICATE_KEYS')
    if upper is not None:
        frame = frame.loc[frame.date <= upper.isoformat()]
        if frame.empty:
            raise ValueError('TREASURY_NO_OBSERVATIONS_WITHIN_SNAPSHOT_BOUNDARY')
    return frame.sort_values(['date', 'tenor_months']).reset_index(drop=True)


def archive_module(repo):
    source = repo / 'fast6/src/fast6/acquisition.py'
    spec = importlib.util.spec_from_file_location('_official_existing_acquisition', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request_plan(paths, finra_start, finra_end, first_year, last_year, *, as_of=None):
    start, end = date.fromisoformat(finra_start), date.fromisoformat(finra_end)
    upper = snapshot_day(as_of)
    if not date(2018, 8, 1) <= start <= end <= (upper or date(2025, 12, 31)) or not 2020 <= first_year <= last_year <= (upper.year if upper else 2025):
        raise ValueError('INTAKE_PRE2026_SCOPE_REQUIRED')
    store = DataStore(paths)
    metadata = store.metadata('trading_calendar')
    if sha256(metadata['path']) != metadata['source_sha256']:
        raise ValueError('CALENDAR_HASH_MISMATCH')
    if metadata['min_date'] > finra_start or metadata['max_date'] < finra_end:
        raise ValueError('CALENDAR_DOES_NOT_COVER_REQUEST')
    sessions = store.read('trading_calendar', start_date=finra_start, end_date=finra_end,
                          columns=['trade_date'], date_column='trade_date')
    days = pd.to_datetime(sessions.trade_date).dt.strftime('%Y-%m-%d').tolist()
    if not days or days != sorted(set(days)) or len(days) > 1000:
        raise ValueError('CALENDAR_EMPTY_DUPLICATE_OR_INTAKE_TOO_LARGE')
    selected = CURRENT_DATASETS if upper is not None else DATASETS
    tasks = [{'dataset': CURRENT_NAMES[FINRA] if upper else FINRA, 'period': day,
              'url': FINRA_URL.format(day=day.replace('-', ''))} for day in days]
    tasks += [{'dataset': dataset, 'period': str(year), 'url': TREASURY_URL.format(kind=kind, year=year)}
              for dataset, kind in KINDS.items() if dataset in selected for year in range(first_year, last_year + 1)]
    plan = {'tasks': tasks, 'calendar': {'path': metadata['path'], 'sha256': metadata['source_sha256']},
        'finra_range': [finra_start, finra_end], 'treasury_years': [first_year, last_year],
        'archive_code_sha256': sha256(paths.repo_root / 'fast6/src/fast6/acquisition.py'),
        'vintage_semantics': VINTAGE, 'historical_pit_certified': False, 'automatic_factor_promotion': False}
    if upper is not None:
        plan.update({'as_of': as_of, 'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST'})
    return plan


def reusable_inputs(manifest_path, paths):
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(paths.results_root):
        raise ValueError('REUSE_MANIFEST_OUTSIDE_RESULTS_ROOT')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('role') != 'OFFICIAL_RESEARCH_DATA_INTAKE' or manifest.get('status') != 'VALIDATED_DATA_ONLY':
        raise ValueError('REUSE_MANIFEST_NOT_VALIDATED')
    by_url = {}
    for item in manifest['inputs']:
        raw = item['raw']; path = Path(raw['local_path']).resolve()
        if raw['status'] not in {'DOWNLOADED', 'CACHED'} or not path.is_relative_to(paths.cache_root) or sha256(path) != raw['sha256'] or raw['source_reference'] != item['url']:
            raise ValueError('REUSE_RAW_IDENTITY_INVALID')
        if item['url'] in by_url:
            raise ValueError('REUSE_DUPLICATE_URL')
        by_url[item['url']] = {**raw, 'status': 'CACHED'}
    return by_url


def acquire(plan, paths, run_id, *, reuse_manifest=None):
    raw_root = paths.cache_root / 'official_research_intake' / run_id / 'raw'
    capture = archive_module(paths.repo_root)
    previous = reusable_inputs(reuse_manifest, paths) if reuse_manifest else {}
    def fetch(task):
        current_annual = (plan.get('as_of') is not None and not is_finra(task['dataset'])
                          and task['period'] == plan['as_of'][:4])
        if task['url'] in previous and not current_annual:
            return {**task, 'raw': previous[task['url']]}
        time.sleep(.5)  # At most two workers; no source-specific high-rate fanout.
        document = capture.acquire_url(task['url'], task['dataset'],
            'FINRA_OFFICIAL' if is_finra(task['dataset']) else 'US_TREASURY_OFFICIAL',
            'DAILY_CNMS' if is_finra(task['dataset']) else 'ANNUAL_PAR_YIELD_FEED',
            raw_root, timeout=30, retries=1, backoff=2.)
        return {**task, 'raw': asdict(document)}
    items = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for item in pool.map(fetch, plan['tasks']):
            items.append(item)
            if len(items) % 25 == 0 or item['raw']['status'] == 'FAILED':
                print(json.dumps({'downloaded_or_cached': len(items), 'total': len(plan['tasks']),
                    'dataset': item['dataset'], 'period': item['period'], 'status': item['raw']['status']}), flush=True)
    return items


def normalize_items(items, plan, paths):
    upper = snapshot_day(plan.get('as_of'))
    datasets = CURRENT_DATASETS if upper is not None else DATASETS
    if {i['dataset'] for i in items} != datasets:
        raise ValueError('SOURCE_DATASETS_DO_NOT_MATCH_TEMPORAL_SCOPE')
    if [(i['dataset'], i['period'], i['url']) for i in items] != [(i['dataset'], i['period'], i['url']) for i in plan['tasks']]:
        raise ValueError('SOURCE_REQUEST_PLAN_MISMATCH')
    if any(i['raw']['status'] not in {'DOWNLOADED', 'CACHED'} for i in items):
        raise ValueError('INCOMPLETE_SOURCE_COVERAGE_NO_CATALOG_PUBLICATION')
    # Raw status is operational, not part of the immutable dataset identity.
    identities = [{k: item[k] for k in ['dataset', 'period', 'url']} | {'sha256': item['raw']['sha256'],
        'observed_at': item['raw']['retrieval_timestamp_utc']} for item in items]
    normalizer_sha = sha256(__file__)
    contract_hash = hashlib.sha256(json_bytes({'plan': plan, 'inputs': identities, 'normalizer_sha256': normalizer_sha})).hexdigest()
    directory = paths.data_root / 'reference/official_research/versions' / contract_hash[:24]
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for dataset in sorted(datasets):
        selected = [i for i in items if i['dataset'] == dataset]
        final = directory / (dataset + '.parquet')
        temporary = directory / (dataset + '.parquet.tmp')
        writer = None
        dates, total, nulls, symbols = set(), 0, 0, set()
        try:
            for item in selected:
                raw = item['raw']
                content = Path(raw['local_path']).read_bytes()
                if hashlib.sha256(content).hexdigest() != raw['sha256'] or raw['source_reference'] != item['url']:
                    raise ValueError('SOURCE_HASH_OR_URL_MISMATCH')
                observed = pd.Timestamp(raw['retrieval_timestamp_utc'])
                if pd.isna(observed) or observed.tzinfo is None:
                    raise ValueError('SOURCE_OBSERVED_TIME_INVALID')
                frame = (parse_finra(content, item['period'], as_of=plan.get('as_of')) if is_finra(dataset)
                         else parse_treasury(content, dataset, int(item['period']), as_of=plan.get('as_of')))
                if frame.empty:
                    raise ValueError('EMPTY_REQUESTED_DAY_REQUIRES_REVIEW')
                frame['source'] = raw['source']
                frame['source_id'] = raw['sha256']
                frame['observed_at_utc'] = observed.tz_convert('UTC').isoformat()
                frame['available_at_utc'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
                frame['vintage_semantics'] = VINTAGE
                table = pa.Table.from_pandas(frame, preserve_index=False)
                if upper is not None and is_finra(dataset):
                    # Explicit precision keeps every row group identical, including old integer files.
                    for column in VOLUME_COLUMNS:
                        table = table.set_column(table.schema.get_field_index(column), column,
                            pa.array(frame[column], type=pa.decimal128(24, 6)))
                if writer is None:
                    writer = pq.ParquetWriter(temporary, table.schema, compression='zstd')
                writer.write_table(table)
                dates.update(frame.date)
                total += len(frame)
                nulls += int(frame['short_volume_share' if is_finra(dataset) else 'yield_percent'].isna().sum())
                if is_finra(dataset):
                    symbols.update(frame.provider_symbol)
        finally:
            if writer is not None:
                writer.close()
        if pq.ParquetFile(temporary).metadata.num_rows != total:
            raise ValueError('PARQUET_ROUNDTRIP_ROW_COUNT_MISMATCH')
        if is_finra(dataset) and dates != {i['period'] for i in selected}:
            raise ValueError('FINRA_CALENDAR_COVERAGE_MISMATCH')
        if final.exists():
            if sha256(final) != sha256(temporary):
                raise ValueError('EXISTING_VERSION_DIFFERS_PRESERVED')
            temporary.unlink()  # Exact temporary file in the resolved version directory.
        else:
            temporary.replace(final)
        outputs.append({'dataset': dataset, 'path': str(final), 'sha256': sha256(final),
            'row_count': total, 'min_date': min(dates), 'max_date': max(dates), 'observation_dates': len(dates),
            'missing_value_rows': nulls, 'provider_symbols': len(symbols) if is_finra(dataset) else None,
            'source': 'FINRA_OFFICIAL' if is_finra(dataset) else 'US_TREASURY_OFFICIAL'})
    return {'schema_version': 1, 'role': 'OFFICIAL_RESEARCH_DATA_INTAKE', 'status': 'VALIDATED_DATA_ONLY',
        'contract_sha256': contract_hash, 'normalizer_sha256': normalizer_sha, 'plan': plan, 'inputs': items, 'outputs': outputs,
        'vintage_semantics': VINTAGE, 'historical_pit_certified': False,
        'limitations': ['FINRA_CNMS_OFF_EXCHANGE_NOT_TOTAL_MARKET_NOT_SHORT_INTEREST',
            'FINRA_SHORT_VOLUME_INCLUDES_EXEMPT_DO_NOT_ADD_AGAIN', 'PROVIDER_SYMBOL_NOT_HISTORICAL_SECURITY_ID',
            'HISTORICAL_AVAILABLE_AT_UNKNOWN_NULL', 'TREASURY_FEED_UPDATED_NOT_ORIGINAL_RELEASE',
            'TREASURY_YIELDS_PERCENT_NOT_DECIMAL', 'NO_MODEL_OR_EXECUTION_VALIDATION',
            'FINRA_FRACTIONAL_SCHEMA_CHANGE_2026_02_23', '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST']}


def publish_catalog(manifest_path, paths):
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(paths.results_root):
        raise ValueError('MANIFEST_OUTSIDE_RESULTS_ROOT')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('role') != 'OFFICIAL_RESEARCH_DATA_INTAKE' or manifest.get('status') != 'VALIDATED_DATA_ONLY':
        raise ValueError('UNVALIDATED_MANIFEST')
    outputs = manifest['outputs']
    upper = snapshot_day(manifest.get('plan', {}).get('as_of'))
    datasets = CURRENT_DATASETS if upper is not None else DATASETS
    if len(outputs) != 3 or {o['dataset'] for o in outputs} != datasets:
        raise ValueError('MANIFEST_DATASET_SET_INVALID')
    for item in manifest['inputs']:
        raw = item['raw']; path = Path(raw['local_path']).resolve()
        if not path.is_relative_to(paths.cache_root) or sha256(path) != raw['sha256']:
            raise ValueError('RAW_INPUT_IDENTITY_INVALID')
    for output in outputs:
        path = Path(output['path']).resolve()
        if not path.is_relative_to(paths.data_root) or sha256(path) != output['sha256']:
            raise ValueError('OUTPUT_IDENTITY_INVALID')
        footer = pq.ParquetFile(path)
        if footer.metadata.num_rows != output['row_count'] or output['max_date'] > (upper.isoformat() if upper else '2025-12-31'):
            raise ValueError('OUTPUT_ROWS_OR_TEMPORAL_SCOPE_INVALID')
    catalog = paths.cache_root / 'derived/data_catalog/catalog.sqlite3'
    if not catalog.is_file():
        raise ValueError('EXISTING_CATALOG_REQUIRED')
    with sqlite3.connect(catalog, timeout=30) as conn:
        conn.execute('BEGIN IMMEDIATE')
        metadata = dict(conn.execute('SELECT key,value FROM catalog_metadata'))
        if metadata.get('schema_version') != CATALOG_SCHEMA_VERSION or metadata.get('catalog_role') != CATALOG_ROLE:
            raise ValueError('CATALOG_SCHEMA_OR_ROLE_INVALID')
        for output in outputs:
            prior = conn.execute('SELECT min_date,max_date FROM data_files WHERE dataset=? AND is_current=1', (output['dataset'],)).fetchall()
            if any(output['min_date'] > lo or output['max_date'] < hi for lo, hi in prior):
                raise ValueError('EXISTING_COVERAGE_REGRESSION')
            lineage = {'date_column': 'date', 'manifest_path': str(manifest_path), 'manifest_sha256': sha256(manifest_path),
                'vintage_semantics': VINTAGE, 'historical_pit_certified': False, 'available_at_semantics': 'UNKNOWN_NULL',
                'date_coverage': output['observation_dates'], 'limitations': manifest['limitations']}
            if upper is not None:
                lineage.update({'as_of': upper.isoformat(), 'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST'})
            register_file(conn, output['dataset'], '', '', output['path'], output['row_count'],
                          output['min_date'], output['max_date'], output['source'], lineage)
    return {'status': 'CATALOG_REGISTERED', 'datasets': sorted(datasets), 'manifest': str(manifest_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--finra-start', default='2023-01-01')
    parser.add_argument('--finra-end', default='2025-12-31')
    parser.add_argument('--first-year', type=int, default=2020)
    parser.add_argument('--last-year', type=int, default=2025)
    parser.add_argument('--as-of', help='Explicit inclusive date boundary; uses separate *_current datasets')
    parser.add_argument('--reuse-manifest', help='Reuse hash-verified archived raw inputs without copying them')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', args.run_id):
        raise ValueError('INVALID_RUN_ID')
    paths = resolve()
    root = paths.results_root / 'official_research_intake' / args.run_id
    plan = request_plan(paths, args.finra_start, args.finra_end, args.first_year, args.last_year, as_of=args.as_of)
    if args.reuse_manifest:
        plan['reuse_manifest'] = {'path': str(Path(args.reuse_manifest).resolve()), 'sha256': sha256(args.reuse_manifest)}
    if not args.execute:
        print(json.dumps({'requests': len(plan['tasks']), 'plan': plan}, ensure_ascii=False))
        return 0
    save_json(root / 'request_plan.json', plan)
    manifest_path = root / 'manifest.json'
    if not manifest_path.exists():
        items = acquire(plan, paths, args.run_id, reuse_manifest=args.reuse_manifest)
        failures = [i for i in items if i['raw']['status'] == 'FAILED']
        if failures:
            failure_path = root / ('acquisition_failure_' + str(time.time_ns()) + '.json')
            save_json(failure_path, {'failed': failures, 'successful': len(items) - len(failures)})
            raise ValueError('SOURCE_DOWNLOAD_FAILED_SEE_RECEIPT')
        save_json(manifest_path, normalize_items(items, plan, paths))
    if args.register:
        print(json.dumps(publish_catalog(manifest_path, paths)), flush=True)
    else:
        print(json.dumps({'status': 'VALIDATED_NOT_REGISTERED', 'manifest': str(manifest_path)}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
