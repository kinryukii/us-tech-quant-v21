"""Fixed-scope official CFTC TFF Futures Only archive; no catalog publication.

GitHub discovery: moshejs/commitments-of-traders (MIT); no third-party code used.
Only the official publicreporting.cftc.gov API supplies observations.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve
from scripts.storage.build_data_catalog import sha256, utc_now
from scripts.storage.refresh_official_research_data import archive_module, json_bytes, save_json, VINTAGE

DATASET = 'cftc_tff_futures_only_major_financial_current'
BASE = 'https://publicreporting.cftc.gov'
RESOURCE = BASE + '/resource/gpe5-46if.json'
METADATA = BASE + '/api/views/gpe5-46if.json'
START = '2010-07-27'
CODES = ('020601', '020604', '042601', '043602', '043607', '044601',
         '045601', '096742', '097741', '098662', '099741', '1170E1',
         '124603', '134741', '13874A', '209742', '232741', '239742')
PAGE_SIZE = 500
RAW_BUDGET = 200 * 1024 * 1024
TOTAL_BUDGET = 500 * 1024 * 1024
RESPONSE_BUDGET = 4 * 1024 * 1024
EXTRA = {'date': pa.string(), 'available_at_utc': pa.timestamp('us', tz='UTC'),
         'retrieved_at_utc': pa.string(), 'source_url': pa.string(),
         'raw_sha256': pa.string(), 'source_row_json': pa.string(),
         'historical_pit_certified': pa.bool_()}
SEMANTICS = {
    'frequency': 'WEEKLY_REPORTING; normally Tuesday positions released Friday',
    'date_semantics': 'CFTC position report period; not publication or retrieval date',
    'available_at_utc': 'UNKNOWN_NULL; schedule does not establish historical availability',
    'vintage_semantics': VINTAGE, 'historical_pit_certified': False,
    'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
    'scope': 'Fixed current major contract codes; not historical investible universe. No exchange/code stitching.',
    'classification': 'Dealer/intermediary, asset manager/institutional, leveraged funds, other reportables, nonreportables; futures only.',
    'source_values': 'All 90 original fields retained as source strings/null; omitted fields distinguished in source_row_json. No numeric coercion or zero filling.',
    'units': 'Source contract_units retained per row; positions and open interest are contracts; pct fields are percentages; traders fields are counts.',
    'revisions': 'Current revised provider history. Bookend rowsUpdatedAt and aggregate comparison detects change during pagination; not an atomic historical vintage.',
    'launch': 'TFF launched 2010-07-22; selected history starts 2010-07-27. No prelaunch backcast.',
    'data_policy': {'url': 'https://www.cftc.gov/WebPolicy/index.htm', 'terms': 'CFTC government information is public domain; acknowledge CFTC; third-party protected contributions are excluded.'},
    'method_urls': ['https://www.cftc.gov/PressRoom/PressReleases/5857-10', 'https://www.cftc.gov/idc/groups/public/%40commitmentsoftraders/documents/file/tfmexplanatorynotes.pdf', BASE + '/stories/s/COT-Help/p2fg-u73y/'],
    'github_discovery': {'url': 'https://github.com/moshejs/commitments-of-traders/blob/main/src/index.ts', 'license': 'MIT software license only', 'use': 'Resource ID and SoQL query syntax reference; no package installed or source copied'},
}


def identity(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path), 'bytes': path.stat().st_size}


def disk_floor(*targets):
    for target in targets:
        existing = Path(target).resolve()
        while not existing.exists():
            existing = existing.parent
        if shutil.disk_usage(existing).free < 20 * 1024 ** 3:
            raise ValueError('DISK_FREE_BELOW_20_GIB')


def locations(paths, run_id):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,100}', run_id):
        raise ValueError('INVALID_RUN_ID')
    tail = Path('official_research_intake') / run_id / 'cftc_cot'
    return paths.results_root / tail, paths.cache_root / tail / 'raw'


def api_url(**params):
    return RESOURCE + '?' + urllib.parse.urlencode(params)


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def schema_fields(document):
    if document.get('id') != 'gpe5-46if' or document.get('name') != 'TFF - Futures Only' or document.get('provenance') != 'official':
        raise ValueError('OFFICIAL_DATASET_IDENTITY_MISMATCH')
    columns = [{'name': c['fieldName'], 'type': c['dataTypeName']} for c in document['columns'] if not c['fieldName'].startswith(':')]
    names = [c['name'] for c in columns]
    if len(names) != len(set(names)) or set(names) & EXTRA.keys() or not {'id', 'cftc_contract_market_code', 'report_date_as_yyyy_mm_dd', 'futonly_or_combined', 'open_interest_all'} <= set(names):
        raise ValueError('SOURCE_SCHEMA_INVALID')
    if any(c['type'] not in {'text', 'calendar_date', 'number'} for c in columns):
        raise ValueError('UNSUPPORTED_SOURCE_TYPE')
    return columns


def period(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00\.000', value):
        raise ValueError('INVALID_REPORT_PERIOD')
    return date.fromisoformat(value[:10]).isoformat()


def verify_capture(receipt_path, expected_url, raw_root):
    receipt_path = Path(receipt_path)
    record = strict_json(receipt_path.read_bytes())
    raw = record['raw']
    path = Path(raw['local_path']).resolve() if raw.get('local_path') else None
    if record['url'] != expected_url or record['http_response'].get('status') != 200 or raw.get('source_reference') != expected_url or raw.get('status') not in {'DOWNLOADED', 'CACHED'}:
        raise ValueError('CAPTURE_REQUEST_OR_STATUS_INVALID')
    if path is None or not path.is_relative_to(Path(raw_root).resolve()) or path.name != hashlib.sha256(expected_url.encode()).hexdigest() + '.source':
        raise ValueError('CAPTURE_PATH_INVALID')
    body = path.read_bytes()
    sidecar = strict_json(path.with_suffix('.json').read_bytes())
    observed = raw.get('retrieval_timestamp_utc')
    if not observed or datetime.fromisoformat(observed.replace('Z', '+00:00')).utcoffset() is None:
        raise ValueError('CAPTURE_OBSERVED_TIME_MISSING')
    if hashlib.sha256(body).hexdigest() != raw['sha256'] or sidecar.get('sha256') != raw['sha256'] or sidecar.get('source_reference') != expected_url or sidecar.get('byte_count') != len(body) or sidecar.get('retrieval_timestamp_utc') != observed:
        raise ValueError('CAPTURE_SIDECAR_OR_HASH_MISMATCH')
    return record, strict_json(body)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Capture:
    """One attempt per receipt, zero redirects/retries, immutable FAST6 raw cache."""
    def __init__(self, paths, run_id):
        self.root, self.raw_root = locations(paths, run_id)
        self.archive = archive_module(paths.repo_root)
        self.opener = urllib.request.build_opener(NoRedirect)
        self.last_request = 0.0

    def get(self, name, url):
        if not re.fullmatch(r'[a-z0-9_]+', name) or urllib.parse.urlsplit(url).scheme != 'https' or urllib.parse.urlsplit(url).netloc != 'publicreporting.cftc.gov' or not (url == METADATA or url.startswith(RESOURCE + '?')):
            raise ValueError('FIXED_OFFICIAL_ENDPOINT_REQUIRED')
        output = self.root / 'requests' / (name + '.json')
        if output.exists():
            verify_capture(output, url, self.raw_root)
            return output
        if (self.root / 'source_stopped.json').exists():
            raise RuntimeError('SOURCE_STOPPED_NO_AUTOMATIC_RETRY')
        marker = output.with_suffix('.started.json')
        if marker.exists():
            raise RuntimeError('INCOMPLETE_ATTEMPT_NO_AUTOMATIC_RETRY')
        used = sum(p.stat().st_size for p in self.raw_root.rglob('*') if p.is_file())
        if used + RESPONSE_BUDGET > RAW_BUDGET:
            raise ValueError('RAW_STORAGE_BUDGET')
        disk_floor(self.raw_root, self.root)
        save_json(marker, {'url': url, 'started_at_utc': utc_now()})
        status = {}
        def bounded(request_url, timeout):
            time.sleep(max(0, 1.05 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                request = urllib.request.Request(request_url, headers={'User-Agent': 'USTQ-CFTC-official-research/1.0', 'Accept': 'application/json'})
                with self.opener.open(request, timeout=timeout) as response:
                    status.update(status=response.status, headers=dict(response.headers), final_url=response.url)
                    if response.status != 200 or response.url != request_url:
                        raise ValueError('NON200_OR_REDIRECT_RESPONSE')
                    data = response.read(RESPONSE_BUDGET + 1)
                    if len(data) > RESPONSE_BUDGET:
                        raise ValueError('RESPONSE_STORAGE_BUDGET')
                    return data
            except urllib.error.HTTPError as exc:
                status.update(status=exc.code, headers=dict(exc.headers))
                exc.close()
                raise
        self.archive._download_once = bounded
        raw = self.archive.acquire_url(url, name, 'CFTC', 'TFF_FUTURES_ONLY_JSON', self.raw_root, 60, 0, 0)
        save_json(output, {'url': url, 'raw': asdict(raw), 'http_response': status, 'completed_at_utc': utc_now()})
        if raw.status == 'FAILED':
            save_json(self.root / 'source_stopped.json', {'failed_receipt': identity(output), 'status': status.get('status'), 'reason': 'ONE_ATTEMPT_FAILED_SOURCE_STOPPED'})
            raise RuntimeError('OFFICIAL_REQUEST_FAILED_SOURCE_STOPPED')
        verify_capture(output, url, self.raw_root)
        return output


def where_clause(as_of):
    day = date.fromisoformat(as_of)
    if day < date.fromisoformat(START) or day > date.today():
        raise ValueError('INVALID_AS_OF')
    return "report_date_as_yyyy_mm_dd >= '" + START + "T00:00:00.000' AND report_date_as_yyyy_mm_dd <= '" + as_of + "T23:59:59.999' AND cftc_contract_market_code in (" + ','.join("'" + c + "'" for c in CODES) + ')'


def aggregate_url(where):
    return api_url(**{'$select': 'cftc_contract_market_code,count(*) as row_count,min(report_date_as_yyyy_mm_dd) as first_date,max(report_date_as_yyyy_mm_dd) as last_date', '$where': where, '$group': 'cftc_contract_market_code', '$order': 'cftc_contract_market_code', '$limit': 100})


def aggregate_stats(rows):
    stats = {}
    for row in rows:
        code = row['cftc_contract_market_code']
        count = int(row['row_count'])
        if code not in CODES or code in stats or count <= 0:
            raise ValueError('INVALID_SCOPE_AGGREGATE')
        stats[code] = {'row_count': count, 'min_date': period(row['first_date']), 'max_date': period(row['last_date'])}
    if set(stats) != set(CODES):
        raise ValueError('INCOMPLETE_CONTRACT_SCOPE')
    return stats


def acquire(paths, run_id, as_of):
    capture = Capture(paths, run_id)
    root, raw_root = capture.root, capture.raw_root
    result_path = root / 'acquisition.json'
    if result_path.exists():
        result = strict_json(result_path.read_bytes())
        if result['plan']['as_of'] != as_of or result['plan']['adapter'] != identity(__file__):
            raise ValueError('ACQUISITION_CONTRACT_CHANGED')
        validate_acquisition(result, raw_root)
        return result_path
    where = where_clause(as_of)
    meta_path = capture.get('metadata_before', METADATA)
    _, meta = verify_capture(meta_path, METADATA, raw_root)
    fields = schema_fields(meta)
    latest_url = api_url(**{'$select': 'max(report_date_as_yyyy_mm_dd) as latest,count(*) as total', '$limit': 1})
    latest_path = capture.get('latest_before', latest_url)
    _, latest = verify_capture(latest_path, latest_url, raw_root)
    latest_date = period(latest[0]['latest'])
    if latest_date > as_of:
        raise ValueError('OFFICIAL_LATEST_BEYOND_AS_OF')
    scope_url = aggregate_url(where)
    scope_path = capture.get('scope_before', scope_url)
    _, scope = verify_capture(scope_path, scope_url, raw_root)
    stats = aggregate_stats(scope)
    total = sum(s['row_count'] for s in stats.values())
    if total > 20000 or any(s['max_date'] != latest_date for s in stats.values()):
        raise ValueError('SCOPE_SIZE_OR_LATEST_MISMATCH')
    plan = {'run_id': run_id, 'as_of': as_of, 'start_date': START, 'codes': list(CODES), 'where': where,
            'fields': fields, 'latest_date': latest_date, 'expected': stats, 'expected_rows': total,
            'page_size': PAGE_SIZE, 'adapter': identity(__file__), 'archive': identity(paths.repo_root / 'fast6/src/fast6/acquisition.py'),
            'metadata_rows_updated_at': meta['rowsUpdatedAt'], 'semantics': SEMANTICS,
            'budgets': {'raw_bytes': RAW_BUDGET, 'total_bytes': TOTAL_BUDGET}}
    save_json(root / 'request_plan.json', plan)
    refs = {'metadata_before': identity(meta_path), 'latest_before': identity(latest_path), 'scope_before': identity(scope_path)}
    pages = []
    for offset in range(0, total, PAGE_SIZE):
        url = api_url(**{'$where': where, '$order': 'report_date_as_yyyy_mm_dd,cftc_contract_market_code,id', '$limit': PAGE_SIZE, '$offset': offset})
        path = capture.get(f'page_{offset:05d}', url)
        pages.append({'offset': offset, 'url': url, 'receipt': identity(path)})
        print(json.dumps({'offset': offset, 'expected_rows': total}), flush=True)
    for name, url in [('scope_after', scope_url), ('latest_after', latest_url), ('metadata_after', METADATA)]:
        refs[name] = identity(capture.get(name, url))
    result = {'status': 'ACQUIRED_FIXED_SCOPE', 'plan': plan, 'plan_file': identity(root / 'request_plan.json'), 'references': refs, 'pages': pages, 'completed_at_utc': utc_now()}
    validate_acquisition(result, raw_root)
    save_json(result_path, result)
    return result_path


def checked_receipt(ref, url, raw_root):
    if identity(ref['path']) != ref:
        raise ValueError('RECEIPT_HASH_CHANGED')
    return verify_capture(ref['path'], url, raw_root)


def validate_acquisition(result, raw_root):
    plan = result['plan']
    if identity(result['plan_file']['path']) != result['plan_file'] or strict_json(Path(result['plan_file']['path']).read_bytes()) != plan:
        raise ValueError('PLAN_CHANGED')
    if plan['codes'] != list(CODES) or plan['start_date'] != START or plan['where'] != where_clause(plan['as_of']) or plan['page_size'] != PAGE_SIZE:
        raise ValueError('FIXED_SCOPE_CHANGED')
    docs = {}
    for name, ref in result['references'].items():
        url = METADATA if name.startswith('metadata') else aggregate_url(plan['where']) if name.startswith('scope') else api_url(**{'$select': 'max(report_date_as_yyyy_mm_dd) as latest,count(*) as total', '$limit': 1})
        _, docs[name] = checked_receipt(ref, url, raw_root)
    if set(docs) != {'metadata_before', 'metadata_after', 'scope_before', 'scope_after', 'latest_before', 'latest_after'}:
        raise ValueError('BOOKENDS_MISSING')
    for phase in ['before', 'after']:
        if schema_fields(docs['metadata_' + phase]) != plan['fields'] or docs['metadata_' + phase]['rowsUpdatedAt'] != plan['metadata_rows_updated_at'] or aggregate_stats(docs['scope_' + phase]) != plan['expected'] or period(docs['latest_' + phase][0]['latest']) != plan['latest_date']:
            raise ValueError('SOURCE_CHANGED_DURING_PAGINATION')
    if docs['latest_before'] != docs['latest_after'] or docs['scope_before'] != docs['scope_after']:
        raise ValueError('SOURCE_AGGREGATE_CHANGED')
    if plan['expected_rows'] != sum(s['row_count'] for s in plan['expected'].values()) or [p['offset'] for p in result['pages']] != list(range(0, plan['expected_rows'], PAGE_SIZE)):
        raise ValueError('PAGINATION_GAP_OR_COUNT_CHANGED')
    return plan


def normalized_rows(result, raw_root):
    plan = validate_acquisition(result, raw_root)
    names = {c['name'] for c in plan['fields']}
    number_fields = {c['name'] for c in plan['fields'] if c['type'] == 'number'}
    seen_ids, seen_keys = set(), set()
    actual = {c: [] for c in CODES}
    previous_order = None
    missing_cells = 0
    for page in result['pages']:
        expected_url = api_url(**{'$where': plan['where'], '$order': 'report_date_as_yyyy_mm_dd,cftc_contract_market_code,id', '$limit': PAGE_SIZE, '$offset': page['offset']})
        if page['url'] != expected_url:
            raise ValueError('PAGE_QUERY_CHANGED')
        record, rows = checked_receipt(page['receipt'], expected_url, raw_root)
        if not isinstance(rows, list) or len(rows) != min(PAGE_SIZE, plan['expected_rows'] - page['offset']):
            raise ValueError('PAGE_LENGTH_MISMATCH')
        for row in rows:
            if not isinstance(row, dict) or set(row) - names or any(v is not None and not isinstance(v, str) for v in row.values()):
                raise ValueError('UNKNOWN_FIELD_OR_NONSTRING_SOURCE_VALUE')
            day, code = period(row['report_date_as_yyyy_mm_dd']), row['cftc_contract_market_code']
            key = (code, day)
            order = (day, code, row['id'])
            if code not in CODES or not START <= day <= plan['as_of'] or row['futonly_or_combined'] != 'FutOnly':
                raise ValueError('ROW_OUTSIDE_FIXED_SCOPE')
            if row['id'] in seen_ids or key in seen_keys or previous_order is not None and order <= previous_order:
                raise ValueError('DUPLICATE_OR_UNSORTED_SOURCE_ROW')
            for field in number_fields:
                value = row.get(field)
                if value is not None:
                    try:
                        if not Decimal(value).is_finite():
                            raise ValueError('NONFINITE_SOURCE_NUMBER')
                    except InvalidOperation:
                        pass  # Preserve provider suppression/non-numeric tokens, never coerce to zero.
            seen_ids.add(row['id']); seen_keys.add(key); previous_order = order
            actual[code].append(day)
            missing_cells += sum(row.get(n) is None for n in names)
            yield {**{name: row.get(name) for name in names}, 'date': day, 'available_at_utc': None,
                   'retrieved_at_utc': record['raw']['retrieval_timestamp_utc'], 'source_url': expected_url,
                   'raw_sha256': record['raw']['sha256'], 'source_row_json': json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False),
                   'historical_pit_certified': False}
    counts = {c: {'row_count': len(days), 'min_date': min(days), 'max_date': max(days)} for c, days in actual.items()}
    if counts != plan['expected']:
        raise ValueError('ACTUAL_SCOPE_AGGREGATE_MISMATCH')


def normalize(paths, run_id, acquisition_path):
    root, raw_root = locations(paths, run_id)
    if Path(acquisition_path).resolve() != (root / 'acquisition.json').resolve():
        raise ValueError('ACQUISITION_OUTSIDE_RUN')
    result = strict_json(Path(acquisition_path).read_bytes())
    plan = validate_acquisition(result, raw_root)
    contract = {'as_of': plan['as_of'], 'acquisition': identity(acquisition_path), 'normalizer': identity(__file__), 'semantics': SEMANTICS}
    output_manifest = root / 'manifest.json'
    if output_manifest.exists():
        manifest = strict_json(output_manifest.read_bytes())
        if manifest['contract'] != contract:
            raise ValueError('COMPLETED_MANIFEST_CONTRACT_CHANGED_USE_NEW_RUN')
        for page in result['pages']:
            checked_receipt(page['receipt'], page['url'], raw_root)
        for item in manifest['outputs']:
            if identity(item['path']) != {k: item[k] for k in ['path', 'sha256', 'bytes']}:
                raise ValueError('OUTPUT_HASH_CHANGED')
        return output_manifest
    version = hashlib.sha256(json_bytes(contract)).hexdigest()[:20]
    output = paths.data_root / 'reference/official_research/cftc_cot' / version / (DATASET + '.parquet')
    disk_floor(output.parent, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.with_suffix('.tmp.parquet').exists():
        raise ValueError('UNPUBLISHED_OUTPUT_EXISTS_NO_OVERWRITE')
    rows = list(normalized_rows(result, raw_root))
    schema = pa.schema([(c['name'], pa.string()) for c in plan['fields']] + list(EXTRA.items()))
    table = pa.Table.from_pylist(rows, schema=schema)
    raw_used = sum(p.stat().st_size for p in raw_root.rglob('*') if p.is_file())
    if raw_used + table.nbytes * 2 > TOTAL_BUDGET:
        raise ValueError('TOTAL_STORAGE_BUDGET')
    tmp = output.with_suffix('.tmp.parquet')
    pq.write_table(table, tmp, compression='zstd', row_group_size=1000)
    if not pq.read_table(tmp).equals(table):
        raise ValueError('PARQUET_ROUNDTRIP_MISMATCH')
    tmp.rename(output)
    columns = [c['name'] for c in plan['fields']]
    tokens = {}
    for row in rows:
        for c in plan['fields']:
            if c['type'] == 'number' and row[c['name']] is not None:
                try:
                    Decimal(row[c['name']])
                except InvalidOperation:
                    key = c['name'] + ':' + row[c['name']]
                    tokens[key] = tokens.get(key, 0) + 1
    qc = {'rows': len(rows), 'source_columns': len(columns), 'source_null_cells': sum(row[c] is None for row in rows for c in columns), 'numeric_source_tokens': tokens,
          'unique_id_count': len({r['id'] for r in rows}), 'unique_contract_date_count': len({(r['cftc_contract_market_code'], r['date']) for r in rows}),
          'latest_report_date': max(r['date'] for r in rows), 'pagination_bookends_equal': True, 'raw_bytes_including_sidecars': raw_used,
          'per_contract': plan['expected'], 'parquet_roundtrip': 'PASS'}
    item = {**identity(output), 'dataset': DATASET, 'rows': len(rows), 'date_column': 'date', 'min_date': min(r['date'] for r in rows), 'max_date': max(r['date'] for r in rows),
            'source': 'CFTC official TFF Futures Only publicreporting.cftc.gov/gpe5-46if', 'schema_version': 'cftc_tff_major_financial_v1'}
    save_json(output_manifest, {'status': 'VALIDATED_DATA_ONLY', 'as_of': plan['as_of'], 'coverage': 'FIXED_18_CONTRACT_SCOPE_CURRENT_VINTAGE', 'contract': contract, 'plan': plan, 'outputs': [item], 'qc': qc, 'completed_at_utc': utc_now()})
    return output_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--execute', action='store_true', help='Fixed scope official acquisition; never registers catalog')
    args = parser.parse_args()
    paths = resolve()
    root, _ = locations(paths, args.run_id)
    acquisition_path = acquire(paths, args.run_id, args.as_of) if args.execute else root / 'acquisition.json'
    if strict_json(acquisition_path.read_bytes())['plan']['as_of'] != args.as_of:
        raise ValueError('CLI_AS_OF_DIFFERS_FROM_FROZEN_ACQUISITION')
    print(normalize(paths, args.run_id, acquisition_path))


if __name__ == '__main__':
    main()
