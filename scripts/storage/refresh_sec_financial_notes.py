"""Archive SEC financial statements and notes; preserve dimensional and custom facts."""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import re
import shutil
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve
from scripts.storage.refresh_official_research_data import archive_module, save_json, VINTAGE
from scripts.storage.refresh_13f_quarter import configured_user_agent
from scripts.storage.restore_sec_data import file_identity, sha256_file

INDEX_URL = 'https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets'
FAMILY = 'sec_financial_notes'
SCOPE = Path('D:/us-tech-quant-data/sec/incremental_20260913/incremental_manifest.json')
TABLES = ('sub', 'num', 'txt', 'ren', 'pre', 'cal', 'tag', 'dim')
DICTIONARIES = {'tag', 'dim'}
TIMEZONE_RULE = 'America/New_York; DST-aware; ambiguous/nonexistent local times remain unknown'
NORMALIZER_VERSION = 'sec-notes-stream-v2-source-dialects'
REQUIRED = {
    'sub': {'adsh', 'cik', 'filed', 'accepted'}, 'tag': {'tag', 'version'},
    'dim': {'segments'}, 'num': {'adsh', 'tag', 'version', 'dimh', 'iprx', 'value'},
    'txt': {'adsh', 'tag', 'version', 'dimh', 'iprx', 'value'},
    'ren': {'adsh', 'report'}, 'pre': {'adsh', 'tag', 'version'},
    'cal': {'adsh', 'ptag', 'pversion', 'ctag', 'cversion'},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def accepted_utc(value):
    if not value:
        return None, 'SOURCE_EMPTY'
    try:
        local = datetime.fromisoformat(value)
        if local.tzinfo is not None:
            raise ValueError('expected local time')
        zone = ZoneInfo('America/New_York')
        early, late = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
        if early.utcoffset() != late.utcoffset():
            return None, 'AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME'
        utc = early.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) != local:
            return None, 'NONEXISTENT_LOCAL_TIME'
        return utc, 'PARSED_SOURCE_LOCAL_TIME'
    except ValueError:
        return None, 'INVALID_SOURCE_LOCAL_TIME'


def period_end(period):
    match = re.fullmatch(r'(20\d{2})(?:_([01]\d)|q([1-4]))', period)
    if not match:
        raise ValueError('INVALID_SOURCE_PERIOD')
    year, month = int(match[1]), int(match[2] or int(match[3]) * 3)
    return date(year, month, calendar.monthrange(year, month)[1])


def member_dialect(zipped, member):
    """Detect old literal-quote TSV without ever consuming subsequent records."""
    physical_rows = wrong_width = literal_quotes = 0
    examples = []
    with zipped.open(member) as stream:
        header_bytes = stream.readline()
        header = header_bytes.decode('utf-8-sig').rstrip('\r\n').split('\t')
        byte_offset = len(header_bytes)
        for physical_rows, raw in enumerate(stream, 1):
            row_offset = byte_offset
            byte_offset += len(raw)
            line = raw.rstrip(b'\r\n')
            if line.count(b'\t') != len(header)-1:
                wrong_width += 1
                continue
            if b'"' not in line:
                continue
            for name, value in zip(header, line.split(b'\t')):
                if value.startswith(b'"') and not re.fullmatch(rb'"(?:[^"]|"")*"', value):
                    literal_quotes += 1
                    if len(examples) < 10:
                        examples.append({'physical_row': physical_rows, 'column': name,
                                         'member_byte_offset': row_offset,
                                         'value_sha256': hashlib.sha256(value).hexdigest()})
    multiline_validated = False
    strict_rows = None
    if literal_quotes:
        # A quoted multiline value may coincidentally have the declared tab
        # count on every physical line. Compare complete logical records too.
        try:
            csv.field_size_limit(64 * 1024**2)
            with zipped.open(member) as binary:
                reader = csv.reader(io.TextIOWrapper(binary, encoding='utf-8-sig', newline=''), delimiter='\t', strict=True)
                if next(reader) != header:
                    raise ValueError('INCONSISTENT_QUOTED_RECORD_WIDTH')
                strict_rows = 0
                for row in reader:
                    if len(row) != len(header):
                        raise ValueError('INCONSISTENT_QUOTED_RECORD_WIDTH')
                    strict_rows += 1
            multiline_validated = True
        except (csv.Error, ValueError):
            strict_rows = None
            if wrong_width:
                raise ValueError('AMBIGUOUS_MIXED_LITERAL_QUOTES_AND_EMBEDDED_DELIMITERS:' + json.dumps({
                    'member': member, 'physical_rows': physical_rows, 'wrong_width': wrong_width, 'samples': examples})) from None
        if multiline_validated and not wrong_width and strict_rows != physical_rows:
            raise ValueError('AMBIGUOUS_QUOTED_AND_LITERAL_RECORD_BOUNDARIES:' + json.dumps({
                'member': member, 'physical_rows': physical_rows, 'quoted_rows': strict_rows, 'samples': examples}))
    return {'mode': 'LITERAL_TSV' if literal_quotes and not multiline_validated else 'QUOTED_TSV',
            'physical_rows': physical_rows, 'physical_rows_wrong_width': wrong_width,
            'non_csv_leading_quote_fields': literal_quotes, 'quote_evidence_sample': examples,
            'multiline_quoted_records_validated': multiline_validated,
            'strict_quoted_rows': strict_rows,
            'basis': 'Mode is inferred from source structure, not provider-certified. Literal mode requires fixed-width physical records plus invalid strict quoted records; original quotes are preserved. Competing valid record boundaries fail closed. Balanced-only literal quotes cannot be distinguished from valid CSV wrapping; raw is retained.'}


def batches(zipped, member, table, block_size=8 * 1024**2, dialect=None):
    """Preserve valid quoted TSV and evidence-verified historical literal TSV."""
    dialect = dialect or member_dialect(zipped, member)
    with zipped.open(member) as stream:
        header = stream.readline().decode('utf-8-sig').rstrip('\r\n').split('\t')
        if len(header) != len(set(header)) or not REQUIRED[table] <= set(header):
            raise ValueError(f'INVALID_SOURCE_HEADER:{table}:{header}')
        if table == 'dim' and not {'dimhash', 'dimh'} & set(header):
            raise ValueError('MISSING_DIMENSION_HASH')
        reader = pacsv.open_csv(stream,
            read_options=pacsv.ReadOptions(column_names=header, block_size=block_size, use_threads=False),
            parse_options=pacsv.ParseOptions(delimiter='\t', quote_char='"' if dialect['mode'] == 'QUOTED_TSV' else False,
                                            double_quote=True, newlines_in_values=dialect['mode'] == 'QUOTED_TSV'),
            convert_options=pacsv.ConvertOptions(column_types={x: pa.string() for x in header},
                null_values=[], strings_can_be_null=False))
        yield pa.Table.from_batches([], schema=reader.schema)
        rows = 0
        for batch in reader:
            rows += len(batch)
            yield pa.Table.from_batches([batch])
        if not dialect['physical_rows_wrong_width'] and rows != dialect['physical_rows']:
            raise ValueError('PARSER_CONSUMED_PHYSICAL_RECORD_BOUNDARIES:' + member)


def verified_item(root, task, paths=None):
    item = json.loads((root/'acquisition'/f"{task['period']}.json").read_text(encoding='utf-8'))
    raw = item['raw']; path = Path(raw['local_path'])
    if paths is not None:
        expected = (paths.cache_root/'official_research_intake'/root.parent.name/'raw'/FAMILY).resolve()
        if expected not in path.resolve().parents:
            raise ValueError('RAW_OUTSIDE_AUTHORIZED_INTAKE_CACHE')
    if item['period'] != task['period'] or item['url'] != task['url'] or raw['source_reference'] != task['url']:
        raise ValueError('ACQUISITION_PLAN_MISMATCH')
    if raw['status'] == 'FAILED' or sha256_file(path) != raw['sha256']:
        raise ValueError('RAW_IDENTITY_MISMATCH')
    observed = datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z', '+00:00'))
    if observed.utcoffset() != timezone.utc.utcoffset(observed):
        raise ValueError('RAW_OBSERVED_NOT_UTC')
    sidecar = path.with_suffix('.json')
    if sidecar.exists():
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        for field in ('source_reference', 'sha256', 'retrieval_timestamp_utc'):
            if metadata[field] != raw[field]:
                raise ValueError('RAW_SIDECAR_MISMATCH')
    return item


def add_lineage(frame, table, item, row_start, selected, as_of):
    size = len(frame)
    if any(c.startswith('source_') or c in {'filing_date', 'accepted_at_utc', 'available_at_utc',
            'observed_at_utc', 'archive_period_end', 'accepted_parse_status', 'timezone_rule'} for c in frame.column_names):
        raise ValueError('SOURCE_METADATA_COLUMN_COLLISION')
    frame = frame.append_column('source_row', pa.array(range(row_start, row_start+size), type=pa.int64()))
    if table == 'dim' and 'dimhash' in frame.column_names:
        if 'dimh' in frame.column_names and frame['dimh'].to_pylist() != frame['dimhash'].to_pylist():
            raise ValueError('DIMENSION_ALIAS_CONFLICT')
        if 'dimh' not in frame.column_names:
            frame = frame.append_column('dimh', frame['dimhash'])
    if table not in DICTIONARIES:
        frame = frame.filter(pc.is_in(frame['adsh'], value_set=pa.array(list(selected), type=pa.string())))
        entries = [selected[x] for x in frame['adsh'].to_pylist()]
    else:
        entries = [(None, None, 'NOT_APPLICABLE_DICTIONARY')] * len(frame)
    raw = item['raw']; size = len(frame)
    columns = {
        'source_period': (item['period'], pa.string()), 'source_sha256': (raw['sha256'], pa.string()),
        'source_member': (item['member'], pa.string()), 'source_url': (item['url'], pa.string()),
        'archive_period_end': (period_end(item['period']), pa.date32()),
        'observed_at_utc': (datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z', '+00:00')), pa.timestamp('us', tz='UTC')),
        'available_at_utc': (None, pa.timestamp('us', tz='UTC')),
        'timezone_rule': (TIMEZONE_RULE, pa.string()),
    }
    for name, (value, dtype) in columns.items():
        frame = frame.append_column(name, pa.repeat(pa.scalar(value, type=dtype), size))
    for index, name, dtype in [(0, 'filing_date', pa.date32()), (1, 'accepted_at_utc', pa.timestamp('us', tz='UTC')),
                               (2, 'accepted_parse_status', pa.string())]:
        frame = frame.append_column(name, pa.array([x[index] for x in entries], type=dtype))
    if 'value' in frame.column_names:
        frame = frame.append_column('source_value_is_empty', pc.equal(frame['value'], ''))
    return frame


def normalize_period(paths, root, plan, task, contract, block_size=8 * 1024**2):
    item = verified_item(root, task, paths)
    identity = digest({'contract': contract, 'raw': item['raw']['sha256'], 'period': task['period']})[:24]
    receipt_path = root/'normalization'/contract['id']/f"{task['period']}.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt['identity'] != identity:
            raise ValueError('PERIOD_CONTRACT_MISMATCH')
        for output in receipt['outputs'].values():
            if sha256_file(Path(output['path'])) != output['sha256']:
                raise ValueError('NORMALIZED_CACHE_HASH_MISMATCH')
        return receipt
    target = paths.cache_root/'official_research_intake'/root.parent.name/'derived'/FAMILY/identity
    target.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target).free < 8 * 1024**3:
        raise RuntimeError('NOTES_NORMALIZATION_STORAGE_BUDGET')
    result = {'identity': identity, 'source_period': task['period'], 'raw': item['raw'], 'outputs': {},
              'source_rows': {}, 'source_empty_fields': {}, 'accepted_parse_status': {}, 'scope_ciks': len(plan['ciks'])}
    needed_tags, needed_dims = set(), set()
    selected, all_adsh = {}, set()
    with ZipFile(item['raw']['local_path']) as zipped:
        members = {}
        for table in TABLES:
            matches = [x for x in zipped.namelist() if Path(x).name in {table+'.tsv', table+'.txt'}]
            if len(matches) != 1:
                raise ValueError(f'AMBIGUOUS_OR_MISSING_MEMBER:{table}')
            members[table] = matches[0]
        try:
            result['source_parsing'] = {table: member_dialect(zipped, member) for table, member in members.items()}
        except ValueError as error:
            save_json(root/'normalization_failures'/contract['id']/f"{task['period']}.json", {
                'status': 'SOURCE_PARSING_REQUIRES_REVIEW', 'identity': identity,
                'source_period': task['period'], 'raw': item['raw'], 'error': str(error)})
            raise
        for batch in batches(zipped, members['sub'], 'sub', block_size, result['source_parsing']['sub']):
            for row in batch.to_pylist():
                if row['adsh'] in all_adsh or not row['adsh'] or not re.fullmatch(r'\d+', row['cik']):
                    raise ValueError('INVALID_OR_DUPLICATE_SUB_IDENTITY')
                all_adsh.add(row['adsh'])
                if int(row['cik']) in plan['ciks']:
                    filed = datetime.strptime(row['filed'], '%Y%m%d').date() if row['filed'] else None
                    if filed and filed > date.fromisoformat(plan['as_of']):
                        raise ValueError('FILING_AFTER_AS_OF')
                    accepted, status = accepted_utc(row['accepted'])
                    selected[row['adsh']] = (filed, accepted, status)
                    result['accepted_parse_status'][status] = result['accepted_parse_status'].get(status, 0)+1
        result['source_submissions'] = len(all_adsh); result['selected_submissions'] = len(selected)
        result['filing_date_min'] = min((x[0] for x in selected.values() if x[0]), default=None)
        result['filing_date_max'] = max((x[0] for x in selected.values() if x[0]), default=None)
        for key in ('filing_date_min', 'filing_date_max'):
            result[key] = result[key].isoformat() if result[key] else None
        for table in TABLES:
            output = target/f'{table}.parquet'; temporary = output.with_suffix('.parquet.tmp')
            if output.exists() or temporary.exists():
                raise ValueError(f'UNRECEIPTED_OUTPUT_REQUIRES_REVIEW:{temporary}')
            count = 0; selected_count = 0; writer = None; empties = {}
            try:
                for batch in batches(zipped, members[table], table, block_size, result['source_parsing'][table]):
                    source_count = len(batch)
                    if table not in DICTIONARIES and source_count:
                        if pc.any(pc.invert(pc.is_in(batch['adsh'], value_set=pa.array(list(all_adsh))))).as_py():
                            raise ValueError(f'SOURCE_ADSH_MISSING_FROM_SUB:{table}')
                    frame = add_lineage(batch, table, {**item, 'member': members[table]}, count+1, selected, plan['as_of'])
                    count += source_count
                    for column in batch.column_names:
                        empties[column] = empties.get(column, 0)+(pc.sum(pc.cast(pc.equal(frame[column], ''), pa.int64())).as_py() or 0)
                    if table in {'num', 'txt', 'pre'}:
                        needed_tags.update(zip(frame['tag'].to_pylist(), frame['version'].to_pylist()))
                    if table in {'num', 'txt'}:
                        needed_dims.update(frame['dimh'].to_pylist())
                    if table == 'cal':
                        needed_tags.update(zip(frame['ptag'].to_pylist(), frame['pversion'].to_pylist()))
                        needed_tags.update(zip(frame['ctag'].to_pylist(), frame['cversion'].to_pylist()))
                    if table == 'tag':
                        needed_tags.difference_update(zip(frame['tag'].to_pylist(), frame['version'].to_pylist()))
                    if table == 'dim':
                        needed_dims.difference_update(frame['dimh'].to_pylist())
                    if writer is None:
                        writer = pq.ParquetWriter(temporary, frame.schema, compression='zstd')
                    if len(frame):
                        writer.write_table(frame)
                    selected_count += len(frame)
            finally:
                if writer:
                    writer.close()
            if pq.ParquetFile(temporary).metadata.num_rows != selected_count:
                raise ValueError('PARQUET_ROW_COUNT_MISMATCH')
            temporary.rename(output)
            result['source_rows'][table] = count; result['source_empty_fields'][table] = empties
            result['outputs'][table] = {**file_identity(output), 'rows': selected_count,
                'source_columns': [x for x in batch.column_names],
                'date_column': 'archive_period_end' if table in DICTIONARIES else 'filing_date'}
            print(json.dumps({'period': task['period'], 'table': table, 'source_rows': count, 'rows': selected_count}), flush=True)
    result['dictionary_links'] = {'unresolved_tag_keys': len(needed_tags), 'unresolved_dimension_keys': len(needed_dims),
        'unresolved_tag_sample': sorted(needed_tags)[:20], 'unresolved_dimension_sample': sorted(needed_dims)[:20],
        'join_scope': 'source_period + source_sha256 + provider keys; all source dictionary rows retained'}
    save_json(receipt_path, result)
    return result


def merge_periods(paths, root, plan, contract, receipts):
    if {x['source_period'] for x in receipts} != {x['period'] for x in plan['tasks']}:
        raise ValueError('INCOMPLETE_PERIOD_COVERAGE')
    manifest_path = root/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['contract'] != contract:
            raise ValueError('FINAL_CONTRACT_MISMATCH')
        for output in manifest['outputs'].values():
            if sha256_file(Path(output['path'])) != output['sha256']:
                raise ValueError('FINAL_OUTPUT_HASH_MISMATCH')
        return manifest
    identity = digest({'contract': contract, 'periods': [x['identity'] for x in receipts]})[:24]
    target = paths.data_root/'reference/official_research/versions'/identity
    target.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for table in TABLES:
        entries = [x['outputs'][table] for x in receipts]
        schema = pa.unify_schemas([pq.read_schema(x['path']) for x in entries])
        output = target/f'sec_financial_notes_{table}_current.parquet'
        temp = output.with_suffix('.parquet.tmp')
        if output.exists() or temp.exists():
            raise ValueError(f'UNRECEIPTED_MERGE_REQUIRES_REVIEW:{temp}')
        with pq.ParquetWriter(temp, schema, compression='zstd') as writer:
            for entry in entries:
                for batch in pq.ParquetFile(entry['path']).iter_batches(batch_size=32768):
                    frame = pa.Table.from_batches([batch])
                    frame = pa.Table.from_arrays([frame[f.name] if f.name in frame.column_names else pa.nulls(len(frame), type=f.type) for f in schema], schema=schema)
                    writer.write_table(frame)
        rows = sum(x['rows'] for x in entries)
        if pq.ParquetFile(temp).metadata.num_rows != rows:
            raise ValueError('MERGED_ROW_COUNT_MISMATCH')
        temp.rename(output)
        outputs[table] = {**file_identity(output), 'rows': rows, 'dataset': output.stem,
                         'date_column': entries[0]['date_column'], 'source_periods': len(entries)}
        print(json.dumps({'merged_table': table, 'rows': rows, 'bytes': output.stat().st_size}), flush=True)
    manifest = {'status': 'COMPLETE_OFFICIAL_INDEX_COVERAGE', 'as_of': plan['as_of'], 'contract': contract,
        'scope': plan['scope'], 'scope_ciks': len(plan['ciks']), 'periods': [x['source_period'] for x in receipts],
        'latest_source_period': max((x['source_period'] for x in receipts), key=period_end), 'outputs': outputs,
        'selected_submissions': sum(x['selected_submissions'] for x in receipts),
        'filing_date_min': min((x['filing_date_min'] for x in receipts if x['filing_date_min']), default=None),
        'filing_date_max': max((x['filing_date_max'] for x in receipts if x['filing_date_max']), default=None),
        'dictionary_links': {key: sum(x['dictionary_links'][key] for x in receipts) for key in ('unresolved_tag_keys', 'unresolved_dimension_keys')},
        'vintage_semantics': VINTAGE, 'historical_pit_certified': False,
        'research_usage': plan['research_usage'], 'available_at_semantics': 'Unknown source-dataset historical publication times; all available_at_utc are null. accepted_at_utc is filing header time, not dataset availability.',
        'timezone_rule': TIMEZONE_RULE,
        'source_semantics': 'Original string fields, blank strings and literal zero retained. Absent historical schema fields merge as null. No numeric conversion, iprx reduction, amendment deduplication, or CIK identity expansion. TAG/DIM dictionaries remain complete per archive.',
        'source_parsing': {x['source_period']: x['source_parsing'] for x in receipts},
        'quote_semantics': 'Valid CSVW quoted members retain quoted parsing. A historical member with non-CSV leading quotes is parsed literally only after every physical line has the declared tab field count; those quotes remain source text. Ambiguous mixed line formats fail closed.',
        'source_row_semantics': 'One-based logical parsed record ordinal within the ZIP member, before CIK filtering. Literal TSV mode has one record per physical line; quoted mode can include embedded newlines.',
        'missingness_statistics': 'Per-period source_empty_fields counts source blank strings in retained rows, not dropped out-of-scope rows. Native source nulls are not inferred from literal text. Schema-absent fields alone become null during merge.',
        'provider_limitations': ['Current retrieved revision only; not historical vintages.', 'Provider numerical facts are already rounded to four decimal places; no recovery of lost precision.', 'ddate/qtrs may be provider-rounded; durp/datp/dcml retained.', 'TXT may be stripped/truncated; escaped/srclen/txtlen/footlen and flags retained.', 'DIM source dimhash retained with dimh alias because documentation calls this key dimh.', 'REN reflects renderer used for this dataset publication.'],
        'normalization_receipts': [str(root/'normalization'/contract['id']/f"{x['source_period']}.json") for x in receipts]}
    save_json(manifest_path, manifest)
    return manifest


def normalize(paths, run_id, as_of, period=None):
    root = paths.results_root/'official_research_intake'/run_id/FAMILY
    plan_path = root/'plan.json'; plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan['as_of'] != as_of or not plan['ciks'] or len(plan['ciks']) != len(set(plan['ciks'])):
        raise ValueError('NORMALIZATION_PLAN_MISMATCH')
    contract = {'version': NORMALIZER_VERSION, 'plan_sha256': sha256_file(plan_path), 'parser_sha256': sha256_file(Path(__file__))}
    contract['id'] = digest(contract)[:24]
    if period and period not in {x['period'] for x in plan['tasks']}:
        raise ValueError('PERIOD_NOT_IN_OFFICIAL_PLAN')
    receipts = []
    for task in plan['tasks']:
        if (not period or period == task['period']) and (root/'acquisition'/f"{task['period']}.json").exists():
            receipts.append(normalize_period(paths, root, plan, task, contract))
    if len(receipts) == len(plan['tasks']):
        return merge_periods(paths, root, plan, contract, receipts)
    progress = {'status': 'NORMALIZED_AVAILABLE_PERIODS', 'periods': [x['source_period'] for x in receipts], 'required_periods': len(plan['tasks']), 'contract': contract}
    print(json.dumps(progress), flush=True)
    return progress


def official_links(raw, start_year, as_of):
    parser = archive_module(Path('D:/us-tech-quant')).LinkParser()
    parser.feed(Path(raw['local_path']).read_text(encoding='utf-8'))
    result = []
    for href, label in parser.links:
        url = urljoin(INDEX_URL, href)
        name = Path(urlparse(url).path).name
        match = re.fullmatch(r'(20\d{2})(?:_([01]\d)|q([1-4]))_notes\.zip', name)
        if not match:
            continue
        if urlparse(url).hostname != 'www.sec.gov' or urlparse(url).scheme != 'https':
            raise ValueError('UNEXPECTED_OFFICIAL_DOWNLOAD_HOST')
        year = int(match[1]); month = int(match[2] or int(match[3]) * 3)
        if start_year <= year and f'{year}-{month:02d}' <= as_of[:7]:
            result.append({'period': name.removesuffix('_notes.zip'), 'url': url, 'label': label})
    if not result or len({x['period'] for x in result}) != len(result):
        raise ValueError('EMPTY_OR_DUPLICATE_OFFICIAL_NOTES_INDEX')
    return result


def acquire(paths, run_id, start_year, as_of, probe=None):
    root = paths.results_root/'official_research_intake'/run_id/'sec_financial_notes'
    raw_root = paths.cache_root/'official_research_intake'/run_id/'raw'
    capture = archive_module(paths.repo_root)
    capture.USER_AGENT = configured_user_agent(paths.repo_root/'scripts/v22/stage_sec_pit_taxonomy.py')
    plan_path = root/'plan.json'
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        if plan['start_year'] != start_year or plan['as_of'] != as_of:
            raise ValueError('RUN_CONTRACT_MISMATCH')
    else:
        if probe:
            raw = json.loads(Path(probe).read_text(encoding='utf-8'))['raw']
            if raw['source_reference'] != INDEX_URL or sha256_file(Path(raw['local_path'])) != raw['sha256']:
                raise ValueError('INDEX_REUSE_IDENTITY_MISMATCH')
        else:
            raw = asdict(capture.acquire_url(INDEX_URL, FAMILY+'_index', 'SEC', 'OFFICIAL_INDEX', raw_root, 90, 0, 0))
            if raw['status'] == 'FAILED':
                raise RuntimeError(raw['error'])
        scope = json.loads(SCOPE.read_text(encoding='utf-8'))['contract']['ciks']
        if not scope or any(not isinstance(x, int) or x <= 0 for x in scope):
            raise ValueError('INVALID_EXISTING_CIK_SCOPE')
        plan = {'as_of': as_of, 'start_year': start_year, 'scope': file_identity(SCOPE),
                'ciks': sorted(set(scope)), 'index_raw': raw, 'tasks': official_links(raw, start_year, as_of),
                'vintage_semantics': VINTAGE, 'historical_pit_certified': False,
                'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST',
                'max_raw_bytes': 22 * 1024**3}
        save_json(plan_path, plan)
    total = 0
    for task in plan['tasks']:
        receipt_path = root/'acquisition'/f"{task['period']}.json"
        if receipt_path.exists():
            item = json.loads(receipt_path.read_text(encoding='utf-8'))
            if item['url'] != task['url'] or sha256_file(Path(item['raw']['local_path'])) != item['raw']['sha256']:
                raise ValueError('RAW_REUSE_IDENTITY_MISMATCH')
        else:
            if shutil.disk_usage(paths.cache_root).free < 20 * 1024**3 or total > plan['max_raw_bytes']:
                raise RuntimeError('NOTES_STORAGE_BUDGET_EXCEEDED')
            raw = capture.acquire_url(task['url'], FAMILY, 'SEC', 'OFFICIAL_XBRL_NOTES_ZIP', raw_root, 900, 0, 0)
            item = {**task, 'raw': asdict(raw)}
            if raw.status == 'FAILED':
                save_json(root/'acquisition_failure.json', item)
                raise RuntimeError(raw.error)
            save_json(receipt_path, item)
            time.sleep(.55)
        total += Path(item['raw']['local_path']).stat().st_size
        print(json.dumps({'period': task['period'], 'raw_bytes_total': total, 'status': item['raw']['status']}), flush=True)
    save_json(root/'acquisition_complete.json', {'as_of': as_of, 'periods': len(plan['tasks']), 'raw_bytes': total})
    return root


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True); parser.add_argument('--as-of', required=True)
    parser.add_argument('--start-year', type=int, default=2020); parser.add_argument('--probe')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--normalize', action='store_true', help='Stream acquired ZIP receipts; merge only when the complete official plan is normalized')
    parser.add_argument('--period', help='Normalize only this already acquired official period')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.run_id) or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', args.as_of) or not 2009 <= args.start_year <= int(args.as_of[:4]):
        raise ValueError('INVALID_INTAKE_CONTRACT')
    paths = resolve()
    if args.normalize:
        normalize(paths, args.run_id, args.as_of, args.period)
    elif args.execute:
        acquire(paths, args.run_id, args.start_year, args.as_of, args.probe)
    else:
        print(json.dumps({'index_url': INDEX_URL, 'start_year': args.start_year, 'as_of': args.as_of}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
