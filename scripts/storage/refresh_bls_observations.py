"""BLS monthly snapshots using existing FAST6 acquisition and value parser.

Reference months are not publication timestamps. Current revisions are retained;
2026+ observations may not be used for training, tuning, or backtesting.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import pandas as pd

from scripts.common.storage_paths import resolve
from scripts.storage.build_data_catalog import sha256
from scripts.storage.refresh_official_research_data import archive_module, json_bytes, save_json, VINTAGE
from scripts.storage.refresh_public_sources import fred_archive_helpers
from scripts.storage.refresh_free_market import write_versioned_parquet

DATASET = 'bls_economic_observations_current'
ENDPOINT = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
DISCLAIMER = ('BLS.gov cannot vouch for the data or analyses derived from these data '
              'after the data have been retrieved from BLS.gov.')


def series_specs():
    # Provider series identities, not strategy factors or research selections.
    definitions = [
        ('CUSR0000SA0', 'CPI', 'All items'),
        ('CUSR0000SA0L1E', 'CPI', 'All items less food and energy'),
        ('CUSR0000SAF1', 'CPI', 'Food'),
        ('CUSR0000SAF11', 'CPI', 'Food at home'),
        ('CUSR0000SA0E', 'CPI', 'Energy'),
        ('CUSR0000SAH1', 'CPI', 'Shelter'),
        ('CUSR0000SASLE', 'CPI', 'Services less energy services'),
        ('CUSR0000SACL1E', 'CPI', 'Commodities less food and energy commodities'),
        ('CUSR0000SEHA', 'CPI', 'Rent of primary residence'),
        ('CUSR0000SEHC', 'CPI', 'Owners equivalent rent of residences'),
        ('CUSR0000SETA02', 'CPI', 'Used cars and trucks'),
        ('WPSFD4', 'PPI', 'Final demand'),
        ('CES0000000001', 'PAYROLLS', 'Total nonfarm'),
        ('CES0500000001', 'PAYROLLS', 'Total private'),
        ('CES2000000001', 'PAYROLLS', 'Construction'),
        ('CES3000000001', 'PAYROLLS', 'Manufacturing'),
        ('CES5000000001', 'PAYROLLS', 'Information'),
        ('CES5500000001', 'PAYROLLS', 'Financial activities'),
        ('CES6000000001', 'PAYROLLS', 'Professional and business services'),
        ('CES6054000001', 'PAYROLLS', 'Professional scientific and technical services'),
        ('CES6054150001', 'PAYROLLS', 'Computer systems design and related services'),
        ('CES6056132001', 'PAYROLLS', 'Temporary help services'),
        ('CES6500000001', 'PAYROLLS', 'Private education and health services'),
        ('CES7000000001', 'PAYROLLS', 'Leisure and hospitality'),
        ('CES0500000002', 'HOURS', 'Average weekly hours all employees total private'),
        ('CES0500000003', 'EARNINGS', 'Average hourly earnings all employees total private'),
        ('CES1000000001', 'PAYROLLS', 'Mining and logging'),
        ('CES4000000001', 'PAYROLLS', 'Trade transportation and utilities'),
        ('CES9000000001', 'PAYROLLS', 'Government'),
        ('CES8000000001', 'PAYROLLS', 'Other services'),
        ('LNS14000000', 'LABOR_FORCE', 'Unemployment rate ages 16 and over'),
        ('LNS11300000', 'LABOR_FORCE', 'Labor force participation rate ages 16 and over'),
        ('LNS12300000', 'LABOR_FORCE', 'Employment population ratio ages 16 and over'),
        ('LNS14000060', 'LABOR_FORCE', 'Unemployment rate ages 25 to 54'),
        ('LNS11300060', 'LABOR_FORCE', 'Labor force participation rate ages 25 to 54'),
        ('LNS12300060', 'LABOR_FORCE', 'Employment population ratio ages 25 to 54'),
        ('JTS000000000000000JOL', 'JOLTS', 'Total nonfarm job openings'),
        ('JTS000000000000000HIL', 'JOLTS', 'Total nonfarm hires'),
        ('JTS000000000000000QUL', 'JOLTS', 'Total nonfarm quits'),
        ('JTS000000000000000LDL', 'JOLTS', 'Total nonfarm layoffs and discharges'),
    ]
    units = {'CPI': 'INDEX_1982_84_100', 'PPI': 'INDEX_200911_100', 'PAYROLLS': 'THOUSANDS_OF_PERSONS',
             'HOURS': 'HOURS_PER_WEEK', 'EARNINGS': 'DOLLARS_PER_HOUR', 'LABOR_FORCE': 'PERCENT',
             'JOLTS': 'THOUSANDS_OF_PERSONS'}
    return {sid: {'event_family': family, 'event_type': sid, 'title': title,
                  'units': ('INDEX_198212_100' if sid == 'CUSR0000SEHC' else
                            'THOUSANDS_OF_POSITIONS' if sid.endswith('JOL') else units[family]),
                  'seasonal_adjustment': 'SEASONALLY_ADJUSTED', 'revision_status': 'REVISION_PRONE',
                  'frequency': 'MONTHLY', 'metadata_url': 'https://data.bls.gov/timeseries/' + sid}
            for sid, family, title in definitions}


def request_plan(paths, run_id, start_year, as_of):
    upper = date.fromisoformat(as_of)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id) or not 2010 <= start_year <= upper.year or upper > date.today():
        raise ValueError('INVALID_RUN_OR_DATE_SCOPE')
    specs = series_specs(); identifiers = list(specs)
    tasks = []
    for first in range(start_year, upper.year + 1, 10):
        for offset in range(0, len(identifiers), 20):
            ids = identifiers[offset:offset + 20]
            tasks.append({'raw_root': str(paths.cache_root/'official_research_intake'/run_id/'raw'),
                'bls_api': {'endpoint': ENDPOINT, 'series': {sid: specs[sid] for sid in ids},
                            'start_year': first, 'end_year': min(first + 9, upper.year)},
                'network': {'max_retries': 0, 'timeout_seconds': 30, 'backoff_seconds': 1}})
    if len(tasks) > 24:
        raise ValueError('BLS_UNREGISTERED_REQUEST_BUDGET_EXCEEDED')
    return {'schema_version': 1, 'dataset': DATASET, 'as_of': as_of, 'start_year': start_year,
            'tasks': tasks, 'series_specs': specs,
            'archive_code_sha256': sha256(paths.repo_root/'fast6/src/fast6/acquisition.py'),
            'parser_code_sha256': sha256(paths.repo_root/'fast6/src/fast6/archive.py'),
            'api_key_required': False, 'reuse_across_runs': False}


def verified_payload(item, paths):
    config, raw = item['config'], item['raw']
    if raw['status'] not in {'DOWNLOADED', 'CACHED'} or raw['source_reference'] != ENDPOINT:
        raise ValueError('BLS_RAW_FAILED_OR_WRONG_ENDPOINT')
    path = Path(raw['local_path']).resolve()
    if not path.is_relative_to(paths.cache_root) or sha256(path) != raw['sha256']:
        raise ValueError('BLS_RAW_IDENTITY_INVALID')
    api = config['bls_api']
    if api['endpoint'] != ENDPOINT or not 1 <= len(api['series']) <= 25 or not 0 <= api['end_year'] - api['start_year'] < 10:
        raise ValueError('BLS_REQUEST_LIMIT_OR_ENDPOINT_INVALID')
    meta = json.loads(path.with_suffix('.meta.json').read_text(encoding='utf-8'))
    # JSON object keys may be sorted when manifests are saved. The archive's
    # explicit array preserves the order actually used in the POST payload.
    ordered_ids = meta.get('series_ids')
    if (not isinstance(ordered_ids, list) or len(ordered_ids) != len(set(ordered_ids)) or
            set(ordered_ids) != set(api['series'])):
        raise ValueError('BLS_REQUEST_SERIES_IDENTITY_INVALID')
    payload = {'seriesid': ordered_ids, 'startyear': api['start_year'], 'endyear': api['end_year'], 'catalog': True}
    request_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (meta['request_sha256'] != request_sha or meta['sha256'] != raw['sha256'] or
            meta['source_reference'] != ENDPOINT or meta['retrieval_timestamp_utc'] != raw['retrieval_timestamp_utc']):
        raise ValueError('BLS_REQUEST_OR_VINTAGE_IDENTITY_INVALID')
    observed = pd.Timestamp(raw['retrieval_timestamp_utc'])
    if pd.isna(observed) or observed.tzinfo is None:
        raise ValueError('BLS_OBSERVED_TIME_INVALID')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('status') != 'REQUEST_SUCCEEDED':
        raise ValueError('BLS_API_UNSUCCESSFUL')
    allowed = {'The catalog has been disabled for this request.'}
    allowed |= {'Unable to get Catalog Data for series ' + sid for sid in api['series']}
    if any(message not in allowed for message in data.get('message', [])):
        raise ValueError('BLS_API_WARNING_REQUIRES_REVIEW:' + str(data.get('message')))
    series = data.get('Results', {}).get('series', [])
    if len(series) != len(api['series']) or {s['seriesID'] for s in series} != set(api['series']):
        raise ValueError('BLS_PARTIAL_OR_DUPLICATE_SERIES')
    annotations = []
    for source in series:
        if not source.get('data'):
            raise ValueError('BLS_EMPTY_SERIES:' + source['seriesID'])
        for row in source['data']:
            if not re.fullmatch(r'M(0[1-9]|1[0-2])', row.get('period', '')):
                raise ValueError('BLS_UNEXPECTED_PERIOD_NOT_MONTHLY')
            if not re.fullmatch(r'\d{4}', str(row.get('year', ''))) or not api['start_year'] <= int(row['year']) <= api['end_year']:
                raise ValueError('BLS_YEAR_OUTSIDE_REQUEST')
            value = row.get('value')
            if not isinstance(value, str) or (value not in {'-', '.', ''} and not re.fullmatch(r'-?\d+(?:\.\d+)?', value)):
                raise ValueError('BLS_INVALID_NUMERIC_VALUE')
            if row.get('latest', 'false') not in {'false', 'true'} or not isinstance(row.get('footnotes', []), list):
                raise ValueError('BLS_ANNOTATION_SCHEMA_INVALID')
            annotations.append({'series_id': source['seriesID'], 'reference_period': row['year'] + '-' + row['period'][1:],
                                'source_latest': row.get('latest') == 'true',
                                'footnotes_json': json.dumps(row.get('footnotes', []), sort_keys=True, ensure_ascii=False)})
    return data, pd.DataFrame(annotations)


def normalize_document(item, paths, as_of):
    payload, annotations = verified_payload(item, paths)
    # Load and call the canonical monthly-value parser; do not join release calendars.
    fred_archive_helpers(paths.repo_root)
    from fast6.archive import normalize_bls_api_values
    document = archive_module(paths.repo_root).RawDocument(**item['raw'])
    frame, status = normalize_bls_api_values(item['config'], [document])
    if status != 'AVAILABLE':
        raise ValueError('BLS_EXISTING_PARSER_INCOMPLETE:' + status)
    frame = frame.merge(annotations, on=['series_id', 'reference_period'], validate='one_to_one')
    frame = frame.rename(columns={'value': 'value_text'})
    frame['value'] = pd.to_numeric(frame.value_text.replace({'-': None, '.': None, '': None}), errors='raise').astype(float)
    if np.isinf(frame.value).any():
        raise ValueError('BLS_NONFINITE_VALUE')
    frame['value_status'] = np.where(frame.value.isna(), 'SOURCE_MISSING', 'OBSERVED')
    frame['date'] = frame.reference_period + '-01'
    frame['reference_period_end'] = (pd.to_datetime(frame.date) + pd.offsets.MonthEnd(0)).dt.strftime('%Y-%m-%d')
    frame = frame.loc[frame.reference_period_end <= as_of].copy()
    if frame.empty:
        raise ValueError('BLS_NO_COMPLETE_REFERENCE_PERIOD_WITHIN_AS_OF')
    specs = item['config']['bls_api']['series']
    frame['title'] = frame.series_id.map(lambda sid: specs[sid]['title'])
    frame['metadata_url'] = frame.series_id.map(lambda sid: specs[sid]['metadata_url'])
    frame['frequency'] = 'MONTHLY'
    frame['source_id'] = item['raw']['sha256']
    frame['observed_at_utc'] = frame.retrieval_timestamp
    frame['available_at_utc'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
    frame['date_semantics'] = 'REFERENCE_PERIOD_START_NOT_PUBLICATION'
    frame['vintage_semantics'] = VINTAGE
    return frame, payload.get('message', [])


def normalize_all(items, plan, paths):
    if len(items) != len(plan['tasks']):
        raise ValueError('BLS_INCOMPLETE_REQUEST_PLAN')
    frames, messages = [], []
    for item, task in zip(items, plan['tasks'], strict=True):
        api = item['config']['bls_api']
        if (api['endpoint'], set(api['series']), api['start_year'], api['end_year']) != (task['bls_api']['endpoint'], set(task['bls_api']['series']), task['bls_api']['start_year'], task['bls_api']['end_year']):
            raise ValueError('BLS_REQUEST_PLAN_MISMATCH')
        # Use accepted per-series metadata, never metadata supplied by a downloaded response.
        item = {**item, 'config': task}
        frame, warnings = normalize_document(item, paths, plan['as_of'])
        frames.append(frame); messages.append(warnings)
    frame = pd.concat(frames, ignore_index=True).sort_values(['date', 'series_id']).reset_index(drop=True)
    if frame.duplicated(['series_id', 'date']).any() or set(frame.series_id) != set(plan['series_specs']):
        raise ValueError('BLS_OUTPUT_DUPLICATE_OR_MISSING_SERIES')
    audits = []
    for sid, group in frame.groupby('series_id', sort=True):
        expected = pd.period_range(str(plan['start_year']) + '-01', group.reference_period.max(), freq='M').astype(str)
        absent = sorted(set(expected) - set(group.reference_period))
        if absent:
            raise ValueError('BLS_MISSING_MONTHS:' + sid + ':' + ','.join(absent))
        latest = group.loc[group.source_latest, 'reference_period'].tolist()
        maximum = group.reference_period.max()
        if latest != [maximum]:
            raise ValueError('BLS_LATEST_MARKER_MISSING_OR_NOT_MAXIMUM:' + sid)
        audits.append({'series_id': sid, **plan['series_specs'][sid], 'row_count': len(group),
            'min_reference_period': group.reference_period.min(), 'max_reference_period': maximum,
            'missing_value_rows': int(group.value.isna().sum()), 'source_latest_reference_period': latest[0],
            'freshness_status': 'LATEST_OBSERVATION_MARKED_BY_BLS_API',
            'missing_value_details': group.loc[group.value.isna(), ['reference_period', 'value_text', 'footnotes_json']].to_dict('records')})
    identity = {'plan': plan, 'inputs': [{'sha256': i['raw']['sha256'], 'observed_at': i['raw']['retrieval_timestamp_utc']} for i in items],
                'adapter_code_sha256': sha256(__file__)}
    contract_sha = hashlib.sha256(json_bytes(identity)).hexdigest()
    directory = paths.data_root/'reference/official_research/versions'/contract_sha[:24]
    output = write_versioned_parquet(frame, directory, DATASET)
    roundtrip = pd.read_parquet(output)
    if not roundtrip.equals(frame):
        raise ValueError('BLS_PARQUET_ROUNDTRIP_MISMATCH')
    record = {'dataset': DATASET, 'ticker': '', 'adjustment': '', 'path': str(output), 'sha256': sha256(output),
              'row_count': len(frame), 'min_date': frame.date.min(), 'max_date': frame.date.max(), 'source': 'BLS_OFFICIAL',
              'lineage': {'date_column': 'date', 'date_semantics': 'REFERENCE_PERIOD_START_NOT_PUBLICATION',
                  'as_of': plan['as_of'], 'vintage_semantics': VINTAGE, 'historical_pit_certified': False,
                  'available_at_semantics': 'UNKNOWN_NULL', 'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
                  'series_count': len(audits), 'terms_url': 'https://www.bls.gov/developers/termsOfService.htm',
                  'attribution': 'U.S. Bureau of Labor Statistics; retrieved ' + max(frame.observed_at_utc),
                  'required_disclaimer': DISCLAIMER}}
    return {'schema_version': 1, 'role': 'BLS_OFFICIAL_OBSERVATIONS', 'status': 'VALIDATED_DATA_ONLY',
            'dataset': DATASET, 'plan': plan, 'inputs': items, 'contract_sha256': contract_sha,
            'adapter_code_sha256': identity['adapter_code_sha256'], 'outputs': [record], 'catalog_records': [record],
            'series_freshness': audits, 'api_messages': messages, 'catalog_written': False,
            'limitations': ['REFERENCE_MONTH_NOT_RELEASE_TIME', 'CURRENT_REVISIONS_NOT_HISTORICAL_VINTAGES',
                           'API_CATALOG_DISABLED_METADATA_FROM_OFFICIAL_SERIES_DEFINITIONS',
                           'SECTOR_AND_AGGREGATE_SERIES_CAN_OVERLAP_NOT_40_INDEPENDENT_FACTORS',
                           'SOURCE_MISSING_VALUES_PRESERVED_WITH_FOOTNOTES', 'NO_MODEL_OR_EXECUTION_VALIDATION']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--start-year', type=int, default=2010)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    paths = resolve(); plan = request_plan(paths, args.run_id, args.start_year, args.as_of)
    root = paths.results_root/'official_research_intake'/args.run_id
    if not args.execute:
        print(json.dumps({'requests': len(plan['tasks']), 'series': len(plan['series_specs']), 'plan': plan})); return 0
    save_json(root/'bls_request_plan.json', plan)
    manifest_path = root/'bls_manifest.json'
    if not manifest_path.exists():
        capture = archive_module(paths.repo_root); items = []
        for config in plan['tasks']:
            document = capture.acquire_bls_api(config)
            items.append({'config': config, 'raw': asdict(document)})
            print(json.dumps({'request': len(items), 'total': len(plan['tasks']), 'status': document.status}), flush=True)
            if document.status == 'FAILED':
                save_json(root/('bls_failure_' + str(time.time_ns()) + '.json'), {'items': items})
                raise ValueError('BLS_ACQUISITION_FAILED_STOPPED_TO_PRESERVE_QUOTA')
            time.sleep(1)
        save_json(manifest_path, normalize_all(items, plan, paths))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['plan'] != plan or manifest.get('status') != 'VALIDATED_DATA_ONLY' or manifest.get('dataset') != DATASET:
        raise ValueError('BLS_EXISTING_MANIFEST_PLAN_OR_STATUS_INVALID')
    for item in manifest['inputs']:
        verified_payload(item, paths)
    for output in manifest['outputs']:
        path = Path(output['path']).resolve()
        if not path.is_relative_to(paths.data_root) or sha256(path) != output['sha256']:
            raise ValueError('BLS_EXISTING_OUTPUT_IDENTITY_INVALID')
    print(json.dumps({'status': 'VALIDATED_NOT_REGISTERED', 'manifest': str(manifest_path)}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
