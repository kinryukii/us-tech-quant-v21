"""Official TIC SLT tables 1/4: fixed source archive and current-vintage intake.

Reuse FAST6 raw archive and canonical storage. No catalog mutation or research.
"""
from __future__ import annotations

import argparse
import calendar
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve
from scripts.storage.build_data_catalog import utc_now
from scripts.storage.refresh_cftc_cot import NoRedirect, disk_floor, identity
from scripts.storage.refresh_official_research_data import archive_module, save_json, VINTAGE

BASE = 'https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/'
URLS = {f'table{n}': BASE + f'slt_table{n}.txt' for n in (1, 4)}
URLS.update({f'html{n}': BASE + f'slt_table{n}.html' for n in (1, 4)})
DATASETS = {1: 'treasury_tic_foreign_us_long_term_holdings_current',
            4: 'treasury_tic_long_term_gross_transactions_current'}
COLUMNS = {
    1: ['for_lt_' + asset + '_' + kind for asset in ('total', 'treas', 'agcy', 'corp', 'eqty') for kind in ('pos', 'net', 'valchg')],
    4: [prefix + '_' + kind for kind in ('sale', 'pur') for prefix in
        ('for_lt_total', 'for_lt_treas', 'for_lt_agcy', 'for_lt_corp', 'for_lt_eqty',
         'us_lt_total', 'us_lt_govt_bond', 'us_lt_corp_bond', 'us_lt_eqty')],
}
RAW_BUDGET = 50 * 1024**2
TOTAL_BUDGET = 200 * 1024**2
RESPONSE_BUDGET = 16 * 1024**2
SEMANTICS = {
    'source': 'US_TREASURY_TIC_OFFICIAL', 'units': 'MILLIONS_USD_SOURCE_ROUNDED',
    'date': 'MONTH_START_LABEL_ONLY; holdings are end-month, flows and valuation changes span month',
    'available_at_utc': 'UNKNOWN_NULL; observation dates and retrieval dates are not release timestamps',
    'historical_pit_certified': False, 'vintage_semantics': VINTAGE,
    'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
    'numeric_representation': 'Exact source strings plus Decimal(38,0); n.a. stays null; -0 lexical form retained',
    'sign': 'Table 1 positive net US sales to foreigners increases foreign position; Table 4 sales/purchases from US reporter perspective',
    'geography': 'Source residence/custody geography is not ultimate beneficial owner domicile; country_code is a source entity code, including aggregates',
    'aggregates': 'Countries, regional/global aggregates and Of Which rows overlap; do not sum all rows. Source entity codes preserved without mappings.',
    'regime': 'Expanded SLT transaction and valuation fields start February 2023; earlier n.a. is not zero; no Form S splice or CSLT backcast',
    'regions': 'Regional compositions and all historical values reflect current source revision; footnotes retained, including euro-area composition as of January 2026',
    'holdings_identity': 'Holding changes need not equal net purchases: valuation, other changes and rounding apply',
    'official_index': 'https://home.treasury.gov/data/treasury-international-capital-tic-system-home-page/tic-forms-instructions/securities-b-portfolio-holdings-of-us-and-foreign-securities',
    'latest_release_evidence': 'https://home.treasury.gov/news/press-releases/sb0606',
    'release_evidence_checked_as_of': '2026-09-15',
    'release_evidence_scope': 'June 2026 released August 17; July scheduled September 16, 2026. Schedule does not certify row-level vintage availability.',
    'source_access': 'Free public Treasury downloadable tables; no key or third-party package used',
}


def locations(paths, run_id):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,100}', run_id):
        raise ValueError('INVALID_RUN_ID')
    tail = Path('official_research_intake') / run_id / 'treasury_tic'
    return paths.results_root / tail, paths.cache_root / tail / 'raw'


def verify_capture(path, url, raw_root):
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    raw = record['raw']
    if record['url'] != url or raw['source_reference'] != url or raw['status'] not in {'DOWNLOADED', 'CACHED'} or record['http_response']['status'] != 200:
        raise ValueError('INVALID_CAPTURE_IDENTITY')
    local = Path(raw['local_path']).resolve()
    if not local.is_relative_to(Path(raw_root).resolve()) or local.name != hashlib.sha256(url.encode()).hexdigest() + '.source':
        raise ValueError('INVALID_CAPTURE_PATH')
    body = local.read_bytes()
    meta = json.loads(local.with_suffix('.json').read_text(encoding='utf-8'))
    if hashlib.sha256(body).hexdigest() != raw['sha256'] or meta['sha256'] != raw['sha256'] or meta['source_reference'] != url or meta['byte_count'] != len(body) or meta['retrieval_timestamp_utc'] != raw['retrieval_timestamp_utc']:
        raise ValueError('CAPTURE_RAW_OR_SIDECAR_MUTATED')
    if datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z', '+00:00')).utcoffset() is None:
        raise ValueError('CAPTURE_TIME_INVALID')
    return record, body


def capture(paths, run_id, name):
    root, raw_root = locations(paths, run_id)
    url = URLS[name]
    receipt = root / 'requests' / (name + '.json')
    if receipt.exists():
        return verify_capture(receipt, url, raw_root)
    marker = receipt.with_suffix('.started.json')
    if marker.exists() or (root / 'source_stopped.json').exists():
        raise ValueError('INCOMPLETE_OR_FAILED_ATTEMPT_NO_AUTOMATIC_RETRY')
    disk_floor(root, raw_root)
    if sum(p.stat().st_size for p in raw_root.rglob('*') if p.is_file()) + RESPONSE_BUDGET > RAW_BUDGET:
        raise ValueError('RAW_BUDGET')
    save_json(marker, {'url': url, 'started_at_utc': utc_now()})
    status = {}
    opener = urllib.request.build_opener(NoRedirect)
    def bounded(request_url, timeout):
        try:
            with opener.open(urllib.request.Request(request_url, headers={'User-Agent': 'USTQ-official-TIC-archive/1.0'}), timeout=timeout) as response:
                status.update(status=response.status, final_url=response.url, headers=dict(response.headers))
                if response.status != 200 or response.url != request_url:
                    raise ValueError('NON200_OR_REDIRECT')
                body = response.read(RESPONSE_BUDGET + 1)
                if len(body) > RESPONSE_BUDGET:
                    raise ValueError('RESPONSE_BUDGET')
                return body
        except urllib.error.HTTPError as exc:
            status.update(status=exc.code, headers=dict(exc.headers))
            exc.close()
            raise
    archive = archive_module(paths.repo_root)
    archive._download_once = bounded
    raw = archive.acquire_url(url, name, 'US_TREASURY_TIC', 'SLT_TABLE_' + ('HTML' if name.startswith('html') else 'TSV'), raw_root, 60, 0, 0)
    save_json(receipt, {'url': url, 'raw': asdict(raw), 'http_response': status, 'capture_code': identity(__file__)})
    if raw.status == 'FAILED':
        save_json(root / 'source_stopped.json', {'failed_receipt': identity(receipt), 'retry': False})
        raise ValueError('OFFICIAL_REQUEST_FAILED')
    return verify_capture(receipt, url, raw_root)


def parse_tsv(body, number, as_of):
    upper = date.fromisoformat(as_of)
    lines = body.decode('utf-8-sig').splitlines()
    columns = ['country', 'country_code', 'date'] + COLUMNS[number]
    if not lines or not lines[0].startswith(f'Table {number}:') or not any(line.rstrip('\t') == 'Millions of dollars' for line in lines[:10]):
        raise ValueError('WRONG_TABLE_OR_UNIT')
    matches = [i for i, line in enumerate(lines) if line == '\t'.join(columns)]
    if len(matches) != 1:
        raise ValueError('SOURCE_SCHEMA_CHANGED')
    start = matches[0]
    footer = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip('\t') == 'Definitions:'), None)
    if footer is None:
        raise ValueError('SOURCE_FOOTER_MISSING_OR_TRUNCATED')
    rows, keys, entities = [], set(), defaultdict(list)
    for i in range(start + 1, footer):
        cells = lines[i].split('\t')
        if not any(cells):
            continue
        if len(cells) != len(columns) or not cells[0] or not re.fullmatch(r'\d{5}', cells[1]) or not re.fullmatch(r'\d{4}-\d{2}', cells[2]):
            raise ValueError('SOURCE_RECORD_INVALID')
        period = date.fromisoformat(cells[2] + '-01')
        lower = date(2020, 1, 1) if number == 1 else date(2023, 2, 1)
        if period < lower or period > upper:
            raise ValueError('SOURCE_PERIOD_OUT_OF_SCOPE')
        key = (cells[1], cells[2])
        if key in keys:
            raise ValueError('DUPLICATE_SOURCE_ENTITY_PERIOD')
        keys.add(key)
        for value in cells[3:]:
            if value != 'n.a.' and not re.fullmatch(r'-?\d{1,38}', value):
                raise ValueError('UNKNOWN_VALUE_TOKEN')
        source = dict(zip(columns, cells))
        rows.append((i + 1, source))
        entities[(cells[1], cells[0])].append(cells[2])
    if not rows or not any(r['country_code'] == '99996' and r['country'] == 'Grand Total' for _, r in rows):
        raise ValueError('SOURCE_EMPTY_OR_GRAND_TOTAL_MISSING')
    coverage = []
    for (code, label), periods in sorted(entities.items()):
        ordinals = sorted(int(x[:4]) * 12 + int(x[5:]) for x in periods)
        if any(b != a + 1 for a, b in zip(ordinals, ordinals[1:])):
            raise ValueError('INTERNAL_SOURCE_MONTH_GAP')
        coverage.append({'country_code': code, 'source_label': label, 'rows': len(periods), 'min_period': min(periods), 'max_period': max(periods)})
    return rows, {'original_columns': columns, 'header_lines': lines[:start + 1], 'footer_lines': lines[footer:], 'coverage': coverage}


class TableHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in {'td', 'th'} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append(''.join(self.cell).replace('\xa0', ' ').strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def verify_html(body, number, rows):
    parser = TableHTML()
    parser.feed(body.decode('utf-8-sig'))
    actual = [cells for cells in parser.rows if len(cells) >= 3 and re.fullmatch(r'\d{4}-\d{2}', cells[2])]
    # Treasury's Table 4 HTML export has one extra, entirely blank layout cell.
    # It is not a source field; reject every nonblank or wider extension.
    layout_cells = 0
    if number == 4:
        for cells in actual:
            if len(cells) == 22 and cells[-1] == '':
                cells.pop()
                layout_cells += 1
    expected = [list(record.values()) for _, record in rows]
    if actual != expected:
        raise ValueError('OFFICIAL_HTML_TSV_ROWS_DIFFER')
    return {'status': 'ALL_SOURCE_FIELDS_EQUAL', 'records_compared': len(actual), 'cells_compared': sum(map(len, actual)), 'blank_html_layout_cells_ignored': layout_cells}


def normalize(rows, raw):
    result = []
    for line, source in rows:
        values = {**source, 'source_period': source['date'], 'date': source['date'] + '-01'}
        year, month = map(int, source['date'].split('-'))
        values.update(period_end=f'{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}',
            available_at_utc=None, historical_pit_certified=False, vintage_semantics=VINTAGE,
            source_line=line, source_record_json=json.dumps(source, ensure_ascii=False, separators=(',', ':')),
            retrieved_at_utc=raw['retrieval_timestamp_utc'], source_url=raw['source_reference'], raw_sha256=raw['sha256'],
            unit='MILLIONS_USD_SOURCE_ROUNDED')
        for field, value in list(source.items())[3:]:
            values[field + '_value'] = None if value == 'n.a.' else Decimal(value)
            values[field + '_missing_kind'] = 'SOURCE_NA' if value == 'n.a.' else 'OBSERVED'
        result.append(values)
    schema = pa.schema([(key, pa.decimal128(38, 0) if key.endswith('_value') else pa.int64() if key == 'source_line'
        else pa.bool_() if key == 'historical_pit_certified' else pa.timestamp('us', tz='UTC') if key == 'available_at_utc' else pa.string()) for key in result[0]])
    return pa.Table.from_pylist(result, schema=schema)


def run(paths, run_id, as_of, *, offline_parser_review=False):
    if not date(2026, 1, 1) <= date.fromisoformat(as_of) <= date.today():
        raise ValueError('AS_OF_SCOPE')
    root, raw_root = locations(paths, run_id)
    manifest = root / 'manifest.json'
    if manifest.exists():
        raise ValueError('COMPLETE_RUN_EXISTS_USE_NEW_RUN_ID')
    plan = {'run_id': run_id, 'as_of': as_of, 'source_code': identity(__file__), 'urls': URLS,
        'semantics': SEMANTICS, 'raw_budget': RAW_BUDGET, 'total_budget': TOTAL_BUDGET, 'retries': 0, 'redirects': 0}
    plan_path = root / 'normalization_plan.json'
    if offline_parser_review:
        previous = json.loads(plan_path.read_text(encoding='utf-8'))
        if {k:v for k,v in previous.items() if k != 'source_code'} != {k:v for k,v in plan.items() if k != 'source_code'}:
            raise ValueError('OFFLINE_REVIEW_SCOPE_CHANGED')
        if not all((root / 'requests' / (name + '.json')).exists() for name in URLS):
            raise ValueError('OFFLINE_REVIEW_REQUIRES_ALL_CAPTURES')
        save_json(root / 'normalization_correction.json', {'parent_plan': identity(plan_path), 'source_code': identity(__file__),
            'network_requests': 0, 'reason': 'Table 4 official HTML adds one blank layout cell; compare all 21 actual source fields. Preserve existing byte-identical output.'})
    else:
        save_json(plan_path, plan)
    captures = {name: capture(paths, run_id, name) for name in URLS}
    outputs, details = [], {}
    for number in (1, 4):
        record, body = captures[f'table{number}']
        rows, metadata = parse_tsv(body, number, as_of)
        metadata['html_comparison'] = verify_html(captures[f'html{number}'][1], number, rows)
        metadata['source_na_cells'] = sum(v == 'n.a.' for _, row in rows for v in list(row.values())[3:])
        metadata['lexical_negative_zero_cells'] = sum(v == '-0' for _, row in rows for v in list(row.values())[3:])
        frame = normalize(rows, record['raw'])
        dataset = DATASETS[number]
        output = paths.data_root / 'reference/official_research/treasury_tic' / run_id / record['raw']['sha256'][:24] / (dataset + '.parquet')
        disk_floor(output, raw_root, root)
        if sum(p.stat().st_size for p in raw_root.rglob('*') if p.is_file()) + frame.nbytes * 2 > TOTAL_BUDGET:
            raise ValueError('TOTAL_STORAGE_BUDGET')
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            with output.open('xb') as handle:
                pq.write_table(frame, handle, compression='zstd')
        if not pq.read_table(output).equals(frame):
            raise ValueError('PARQUET_ROUNDTRIP_DIFFERS')
        outputs.append({**identity(output), 'dataset': dataset, 'rows': frame.num_rows, 'date_column': 'date',
            'min_date': min(frame['date'].to_pylist()), 'max_date': max(frame['date'].to_pylist()), 'source': 'US_TREASURY_TIC_OFFICIAL'})
        details[str(number)] = metadata
    result = {'status': 'VALIDATED_DATA_ONLY', 'as_of': as_of, 'outputs': outputs, 'source_details': details,
        'captures': {name: record for name, (record, _) in captures.items()}, 'semantics': SEMANTICS,
        'limitations': [SEMANTICS[key] for key in ('available_at_utc', 'geography', 'aggregates', 'regime', 'regions', 'holdings_identity')],
        'source_code': identity(__file__), 'raw_bytes': sum(len(body) for _, body in captures.values()),
        'normalization_plan': identity(plan_path), 'offline_parser_review': offline_parser_review, 'completed_at_utc': utc_now()}
    save_json(manifest, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--offline-parser-review', action='store_true')
    args = parser.parse_args()
    result = run(resolve(Path(__file__).resolve().parents[2]), args.run_id, args.as_of, offline_parser_review=args.offline_parser_review)
    print(json.dumps({'status': result['status'], 'outputs': result['outputs']}, ensure_ascii=False))
