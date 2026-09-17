"""SEC public N-PORT bulk adapter; bounded streaming, original versions retained.

Reuse storage routing, SEC contact configuration, immutable JSON and file hashes.
No catalog publication, security mapping, selection, fitting or inferred PIT dates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import time
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from scripts.common.storage_paths import resolve
from scripts.storage.refresh_13f_quarter import configured_user_agent
from scripts.storage.refresh_official_research_data import save_json, json_bytes, VINTAGE
from scripts.storage.restore_sec_data import file_identity, sha256_file

INDEX_URL = 'https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets'
README_URL = 'https://www.sec.gov/files/nport_readme.pdf'
FORM_URL = 'https://www.sec.gov/files/formn-port.pdf'
RULE_URL = 'https://www.sec.gov/files/rules/final/2025/ic-35538.pdf'
PROPOSAL_URL = 'https://www.sec.gov/rules-regulations/2026/02/s7-2026-05'
MAX_ZIP = 800 * 1024**2
MAX_EXPANDED = 8 * 1024**3
MIN_FREE_DISK = 20 * 1024**3
CHUNK_ROWS = 100_000
BASE_TABLES = ('SUBMISSION', 'REGISTRANT', 'FUND_REPORTED_INFO')
DETAIL_TABLES = ('FUND_REPORTED_HOLDING', 'IDENTIFIERS', 'SECURITIES_LENDING', 'EXPLANATORY_NOTE')
DATASETS = {'FILINGS': 'sec_nport_filings_current',
            'FUND_REPORTED_HOLDING': 'sec_nport_holdings_current',
            'IDENTIFIERS': 'sec_nport_identifiers_current',
            'SECURITIES_LENDING': 'sec_nport_securities_lending_current',
            'EXPLANATORY_NOTE': 'sec_nport_explanatory_notes_current'}
CONTEXT = ('accession', 'filing_date', 'report_date', 'cik', 'series_id', 'series_name', 'form', 'is_amendment')


def quarter_end(quarter):
    if not re.fullmatch(r'20\d{2}q[1-4]', quarter) or quarter < '2019q4':
        raise ValueError('UNSUPPORTED_NPORT_QUARTER')
    return pd.Period(quarter.upper(), freq='Q').end_time.date()


def source_url(quarter):
    quarter_end(quarter)
    return f'https://www.sec.gov/files/dera/data/form-n-port-data-sets/{quarter}_nport.zip'


def download(paths, run_id, quarter, *, session=None):
    """One stream request; denial and incomplete captures stop without rerouting."""
    folder = paths.cache_root / 'official_research_intake' / run_id / 'sec_nport/raw'
    folder.mkdir(parents=True, exist_ok=True)
    path, meta_path = folder / f'{quarter}_nport.zip', folder / f'{quarter}_nport.json'
    url = source_url(quarter)
    if path.exists() or meta_path.exists():
        if not path.exists() or not meta_path.exists():
            raise ValueError('INCOMPLETE_OR_DENIED_CAPTURE_PRESERVED')
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        if meta.get('status') != 'DOWNLOADED' or meta.get('url') != url or meta.get('sha256') != sha256_file(path):
            raise ValueError('RAW_SOURCE_IDENTITY_INVALID')
        return meta
    partial = path.with_suffix('.zip.partial')
    if partial.exists():
        raise ValueError('PARTIAL_CAPTURE_PRESERVED_NEW_RUN_REQUIRED')
    if shutil.disk_usage(folder).free < MIN_FREE_DISK:
        raise ValueError('NPORT_FREE_DISK_BUDGET_INSUFFICIENT')
    user_agent = configured_user_agent(paths.repo_root / 'scripts/v22/stage_sec_pit_taxonomy.py')
    if '@' not in user_agent:
        raise ValueError('CONFIGURED_SEC_CONTACT_REQUIRED')
    client = session or requests.Session()
    meta = {'source': 'SEC_OFFICIAL', 'url': url, 'started_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        time.sleep(.6)
        with client.get(url, headers={'User-Agent': user_agent, 'Accept-Encoding': 'identity'},
                        stream=True, allow_redirects=False, timeout=(20, 90)) as response:
            meta.update(http_status=response.status_code, content_length_header=response.headers.get('Content-Length'),
                        last_modified_header=response.headers.get('Last-Modified'), etag_header=response.headers.get('ETag'))
            if response.status_code != 200:
                raise ValueError(f'NPORT_HTTP_{response.status_code}_STOPPED_NO_ALTERNATE_ROUTE')
            if int(response.headers.get('Content-Length', 0)) > MAX_ZIP:
                raise ValueError('COMPRESSED_BUDGET_EXCEEDED')
            count, digest, checkpoint = 0, hashlib.sha256(), 64 * 1024**2
            with partial.open('xb') as handle:
                for block in response.iter_content(1024**2):
                    if not block:
                        continue
                    count += len(block)
                    if count > MAX_ZIP:
                        raise ValueError('COMPRESSED_BUDGET_EXCEEDED')
                    digest.update(block); handle.write(block)
                    if count >= checkpoint:
                        print(f'NPORT {quarter} downloaded MiB={count // 1024**2}', flush=True)
                        checkpoint += 64 * 1024**2
            if response.headers.get('Content-Length') and count != int(response.headers['Content-Length']):
                raise ValueError('HTTP_CONTENT_LENGTH_MISMATCH')
        with zipfile.ZipFile(partial) as archive:
            if 'SUBMISSION.tsv' not in archive.namelist():
                raise ValueError('NPORT_ZIP_IDENTITY_INVALID')
        partial.replace(path)
        meta.update(status='DOWNLOADED', path=str(path), sha256=digest.hexdigest(), bytes=count,
                    observed_at_utc=datetime.now(timezone.utc).isoformat())
        save_json(meta_path, meta)
        return meta
    except Exception as exc:
        meta.update(status='STOPPED_SOURCE_FAILURE', error_type=type(exc).__name__,
                    error=str(exc), observed_at_utc=datetime.now(timezone.utc).isoformat())
        save_json(meta_path, meta)
        raise


def inspect_archive(archive):
    entries = archive.infolist()
    if len({i.filename for i in entries}) != len(entries) or sum(i.file_size for i in entries) > MAX_EXPANDED:
        raise ValueError('ZIP_DUPLICATE_OR_EXPANSION_BUDGET')
    if any(Path(i.filename).name != i.filename or i.flag_bits & 1 for i in entries):
        raise ValueError('ZIP_UNEXPECTED_PATH_OR_ENCRYPTION')
    required = {t + '.tsv' for t in BASE_TABLES + DETAIL_TABLES} | {'nport_metadata.json'}
    if not required <= set(archive.namelist()):
        raise ValueError('NPORT_REQUIRED_MEMBERS_MISSING')
    metadata = json.loads(archive.read('nport_metadata.json'))
    schemas = {t['url']: t['tableSchema'] for t in metadata['tables']}
    for member in required - {'nport_metadata.json'}:
        if member not in schemas:
            raise ValueError('NPORT_TABLE_SCHEMA_MISSING')
    return schemas


def read_table(archive, name, schemas, chunksize=None):
    member = name + '.tsv'
    columns = [c['name'] for c in schemas[member]['columns']]
    stream = archive.open(member)
    frame = pd.read_csv(stream, sep='\t', dtype=str, keep_default_na=False, na_filter=False,
                        encoding='utf-8-sig', quoting=csv.QUOTE_MINIMAL, chunksize=chunksize)
    if chunksize is None:
        stream.close()
        if list(frame.columns) != columns:
            raise ValueError('TABLE_COLUMNS_DIFFER_FROM_PROVIDER_METADATA')
        return frame
    def iterate():
        try:
            for chunk in frame:
                if list(chunk.columns) != columns:
                    raise ValueError('TABLE_COLUMNS_DIFFER_FROM_PROVIDER_METADATA')
                yield chunk
        finally:
            stream.close()
    return iterate()


def date_column(values):
    return pd.to_datetime(values.replace('', None), format='%d-%b-%Y', errors='raise').dt.strftime('%Y-%m-%d').fillna('')


def filing_frame(archive, schemas, quarter, as_of):
    frames = {name: read_table(archive, name, schemas) for name in BASE_TABLES}
    for frame in frames.values():
        if frame.ACCESSION_NUMBER.eq('').any() or frame.ACCESSION_NUMBER.duplicated().any():
            raise ValueError('BASE_ACCESSION_MISSING_OR_DUPLICATED')
    submissions = frames['SUBMISSION']
    if not submissions.SUB_TYPE.isin(['NPORT-P', 'NPORT-P/A', 'NT NPORT-P']).all():
        raise ValueError('NONPUBLIC_OR_UNSUPPORTED_NPORT_FORM')
    result = submissions.copy()
    for name in ('REGISTRANT', 'FUND_REPORTED_INFO'):
        frame = frames[name]
        if not set(frame.ACCESSION_NUMBER) <= set(submissions.ACCESSION_NUMBER):
            raise ValueError('ORPHAN_BASE_ACCESSION')
        result = result.merge(frame.rename(columns={k: name + '__' + k for k in frame if k != 'ACCESSION_NUMBER'}),
                              on='ACCESSION_NUMBER', how='left', validate='one_to_one').fillna('')
    result['accession'] = result.ACCESSION_NUMBER
    result['filing_date'] = date_column(result.FILING_DATE)
    result['report_date'] = date_column(result.REPORT_DATE)
    if result.filing_date.eq('').any() or result.filing_date.gt(min(as_of, quarter_end(quarter).isoformat())).any():
        raise ValueError('FILING_DATE_MISSING_OR_AFTER_PACKAGE_SCOPE')
    result['form'] = result.SUB_TYPE
    result['is_amendment'] = result.SUB_TYPE.eq('NPORT-P/A')
    result['cik'] = result.REGISTRANT__CIK
    result['series_id'] = result.FUND_REPORTED_INFO__SERIES_ID
    result['series_name'] = result.FUND_REPORTED_INFO__SERIES_NAME
    result['identity_status'] = result.series_id.ne('').map({True: 'PROVIDER_SERIES_ID', False: 'MISSING_SERIES_ID_NOT_INFERRED'})
    result['report_date_status'] = (result.report_date.eq('') | result.report_date.gt(result.filing_date)).map(
        {True: 'SOURCE_REPORT_DATE_REQUIRES_REVIEW', False: 'SOURCE_DATES_RETAINED'})
    return result


def decimal_values(values):
    result = []
    for text in values:
        if text == '':
            result.append(None); continue
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError('NONNUMERIC_SOURCE_VALUE') from exc
        if not value.is_finite():
            raise ValueError('NONFINITE_SOURCE_VALUE')
        result.append(value)
    return pa.array(result, type=pa.decimal128(38, 12))


def attach_context(frame, context, index):
    if 'ACCESSION_NUMBER' in frame:
        accessions = frame.ACCESSION_NUMBER
    else:
        ids = list(set(frame.HOLDING_ID))
        mapping = {}
        for offset in range(0, len(ids), 800):
            batch = ids[offset:offset + 800]
            query = 'SELECT holding_id,accession FROM holdings WHERE holding_id IN (' + ','.join('?' for _ in batch) + ')'
            mapping.update(index.execute(query, batch).fetchall())
        accessions = frame.HOLDING_ID.map(mapping)
    if accessions.isna().any() or not accessions.isin(context.index).all():
        raise ValueError('ORPHAN_HOLDING_OR_ACCESSION')
    for column in CONTEXT:
        frame[column] = accessions.map(context[column])
    return frame


def normalize(paths, run_id, quarter, raw, as_of):
    path = Path(raw['path']).resolve()
    if raw.get('status') != 'DOWNLOADED' or not path.is_relative_to(paths.cache_root) or raw['url'] != source_url(quarter) or sha256_file(path) != raw['sha256']:
        raise ValueError('RAW_SOURCE_IDENTITY_INVALID')
    observed = pd.Timestamp(raw['observed_at_utc'])
    if observed.tzinfo is None or pd.isna(observed):
        raise ValueError('OBSERVED_TIME_INVALID')
    contract = {'quarter': quarter, 'as_of': as_of, 'source_sha256': raw['sha256'],
                'observed_at_utc': raw['observed_at_utc'], 'normalizer_sha256': sha256_file(Path(__file__))}
    digest = hashlib.sha256(json_bytes(contract)).hexdigest()
    destination = paths.data_root / 'reference/official_research/sec_nport' / digest[:24]
    report = paths.results_root / 'official_research_intake' / run_id / 'sec_nport' / quarter
    manifest_path = report / 'manifest.json'
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding='utf-8'))
        if prior['contract'] != contract:
            raise ValueError('EXISTING_RUN_CONTRACT_DIFFERS')
        for output in prior['outputs']:
            if sha256_file(Path(output['path'])) != output['sha256']:
                raise ValueError('EXISTING_OUTPUT_IDENTITY_DIFFERS')
        return prior
    if shutil.disk_usage(paths.data_root).free < MIN_FREE_DISK:
        raise ValueError('NPORT_FREE_DISK_BUDGET_INSUFFICIENT')
    destination.mkdir(parents=True, exist_ok=True)
    working = paths.cache_root / 'official_research_intake' / run_id / 'sec_nport/validation' / digest[:24]
    working.mkdir(parents=True, exist_ok=True)
    index = sqlite3.connect(working / 'holding_keys.sqlite3')
    index.execute('PRAGMA cache_size=-262144')
    index.execute('CREATE TABLE IF NOT EXISTS holdings (holding_id TEXT PRIMARY KEY, accession TEXT NOT NULL)')
    if index.execute('SELECT COUNT(*) FROM holdings').fetchone()[0]:
        index.close(); raise ValueError('PARTIAL_NORMALIZATION_KEYS_PRESERVED')
    outputs = []
    try:
        with zipfile.ZipFile(path) as archive:
            schemas = inspect_archive(archive)
            if archive.testzip() is not None:
                raise ValueError('RAW_ZIP_CRC_FAILURE')
            filings = filing_frame(archive, schemas, quarter, as_of)
            context = filings[list(CONTEXT)].set_index('accession', drop=False)
            def write(name, chunks):
                final = destination / (DATASETS[name] + '.parquet')
                temp = final.with_suffix('.parquet.tmp')
                if final.exists() or temp.exists():
                    raise ValueError('EXISTING_OUTPUT_PRESERVED')
                writer, count, row_offset = None, 0, 0
                null_values, min_date, max_date = 0, None, None
                try:
                    for frame in chunks:
                        frame = frame.copy()
                        if name != 'FILINGS':
                            if name == 'FUND_REPORTED_HOLDING':
                                if frame.HOLDING_ID.eq('').any(): raise ValueError('EMPTY_HOLDING_ID')
                                try:
                                    index.executemany('INSERT INTO holdings VALUES (?,?)', zip(frame.HOLDING_ID, frame.ACCESSION_NUMBER))
                                except sqlite3.IntegrityError as exc:
                                    raise ValueError('DUPLICATE_HOLDING_ID') from exc
                                index.commit()
                            frame = attach_context(frame, context, index)
                        frame['source_row_number'] = range(row_offset + 1, row_offset + len(frame) + 1)
                        frame['source_quarter'] = quarter
                        frame['source_member'] = 'SUBMISSION+REGISTRANT+FUND_REPORTED_INFO' if name == 'FILINGS' else name + '.tsv'
                        frame['source_id'] = raw['sha256']
                        frame['observed_at_utc'] = raw['observed_at_utc']
                        frame['available_at_utc'] = pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns, UTC]')
                        frame['vintage_semantics'] = VINTAGE
                        if len(frame):
                            first, last = frame.filing_date.min(), frame.filing_date.max()
                            min_date = first if min_date is None else min(first, min_date)
                            max_date = last if max_date is None else max(last, max_date)
                        derived_types = {'is_amendment': pa.bool_(), 'source_row_number': pa.int64(),
                                         'available_at_utc': pa.timestamp('ns', tz='UTC')}
                        schema = pa.schema([(col, derived_types.get(col, pa.string())) for col in frame])
                        table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
                        if name == 'FUND_REPORTED_HOLDING':
                            for original, alias in [('BALANCE','balance_numeric'), ('CURRENCY_VALUE','value_usd'), ('PERCENTAGE','percent_net_assets'), ('EXCHANGE_RATE','exchange_rate_numeric')]:
                                values = decimal_values(frame[original]); table = table.append_column(alias, values)
                                if alias == 'value_usd': null_values += values.null_count
                        if writer is None:
                            writer = pq.ParquetWriter(temp, table.schema, compression='zstd')
                        writer.write_table(table)
                        count += len(frame); row_offset += len(frame)
                        if count and count % 500_000 == 0:
                            print(f'NPORT {quarter} {name} rows={count}', flush=True)
                finally:
                    if writer is not None: writer.close()
                if writer is None: raise ValueError('SOURCE_TABLE_HEADER_MISSING')
                if pq.ParquetFile(temp).metadata.num_rows != count: raise ValueError('PARQUET_ROW_COUNT_MISMATCH')
                temp.replace(final)
                outputs.append({'dataset': DATASETS[name], **file_identity(final), 'rows': count, 'row_count': count,
                                'date_column': 'filing_date', 'min_date': min_date,
                                'max_date': max_date, 'source_table': name, 'null_usd_values': null_values})
            write('FILINGS', [filings])
            for name in DETAIL_TABLES:
                write(name, read_table(archive, name, schemas, CHUNK_ROWS))
            members = [{'member': i.filename, 'uncompressed_bytes': i.file_size, 'crc32': f'{i.CRC:08x}'} for i in archive.infolist()]
            manifest = {'role': 'SEC_NPORT_PUBLIC_BULK_INTAKE', 'status': 'VALIDATED_DATA_ONLY',
                'contract': contract, 'source': raw, 'outputs': outputs, 'members': members, 'archive_crc_verified': True,
                'filings': len(filings), 'fund_series': int(filings.series_id.replace('', None).nunique()),
                'amendment_filings': int(filings.is_amendment.sum()),
                'report_date_min': min(filings.loc[filings.report_date.ne(''), 'report_date'], default=None),
                'report_date_max': max(filings.loc[filings.report_date.ne(''), 'report_date'], default=None),
                'missing_series_identity': int(filings.series_id.eq('').sum()),
                'report_date_review_rows': int(filings.report_date_status.eq('SOURCE_REPORT_DATE_REQUIRES_REVIEW').sum()),
                'historical_pit_certified': False, 'available_at_semantics': 'UNKNOWN_NULL_NO_60_DAY_INFERENCE',
                'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING' if quarter >= '2026q1' else 'HISTORICAL_RESEARCH_ONLY_PENDING_PIT_AND_IDENTITY_QUALIFICATION',
                'scope': 'ALL_PUBLIC_FILINGS_AND_ALL_HOLDINGS_IN_SELECTED_OFFICIAL_QUARTER_PACKAGE',
                'latest_bulk_evidence_url': INDEX_URL, 'provider_readme_url': README_URL,
                'unit_evidence_url': FORM_URL, 'effective_rule_delay_url': RULE_URL, '2026_proposal_url': PROPOSAL_URL,
                'limitations': ['PACKAGE_QUARTER_IS_PUBLIC_FILING_COLLECTION_NOT_COMMON_PORTFOLIO_DATE',
                    'NO_PUBLIC_INCREMENT_AFTER_PACKAGE_CUTOFF_IMPORTED', 'AMENDMENTS_RETAINED_NO_LATEST_OVERWRITE',
                    'RAW_ZIP_RETAINS_ALL_TABLES_ONLY_FILINGS_HOLDINGS_IDENTIFIERS_LENDING_NOTES_NORMALIZED',
                    'CURRENCY_VALUE_IS_USD_C2C_CURRENCY_CODE_IS_DENOMINATION_NO_FX_RESCALING',
                    'PER_FUND_FISCAL_QUARTER_PUBLIC_REPORTS_NOT_ALL_MONTHLY_REPORTS',
                    'CURRENT_BULK_EXTRACTION_NOT_SUBSTITUTE_FOR_ORIGINAL_FILING_OR_HISTORICAL_VINTAGE']}
            save_json(manifest_path, manifest)
            index.close()
            key_file = (working / 'holding_keys.sqlite3').resolve()
            if not key_file.is_relative_to(paths.cache_root.resolve()): raise ValueError('CACHE_CLEANUP_PATH_INVALID')
            key_file.unlink()  # Fully validated, disposable FK index; original ZIP remains immutable.
            return manifest
    finally:
        index.close()


def merge_quarters(paths, run_id, manifests, as_of):
    """Stream verified quarter outputs; retain duplicate accessions and source versions."""
    ordered = sorted(manifests, key=lambda item: item['contract']['quarter'])
    quarters = [item['contract']['quarter'] for item in ordered]
    if len(set(quarters)) != len(quarters) or not ordered: raise ValueError('DUPLICATE_OR_EMPTY_PACKAGE_SCOPE')
    inputs = []
    for item in ordered:
        for output in item['outputs']:
            if sha256_file(Path(output['path'])) != output['sha256']: raise ValueError('MERGE_INPUT_IDENTITY_DIFFERS')
        inputs.append({'quarter': item['contract']['quarter'], 'source': item['source'], 'outputs': item['outputs']})
    contract = {'as_of': as_of, 'inputs': inputs, 'normalizer_sha256': sha256_file(Path(__file__))}
    digest = hashlib.sha256(json_bytes(contract)).hexdigest()
    destination = paths.data_root / 'reference/official_research/sec_nport' / digest[:24]
    report = paths.results_root / 'official_research_intake' / run_id / 'sec_nport/manifest.json'
    if report.exists():
        previous = json.loads(report.read_text(encoding='utf-8'))
        if previous['contract'] != contract: raise ValueError('EXISTING_MERGE_CONTRACT_DIFFERS')
        if any(sha256_file(Path(o['path'])) != o['sha256'] for o in previous['outputs']):
            raise ValueError('EXISTING_MERGE_OUTPUT_IDENTITY_DIFFERS')
        return previous
    destination.mkdir(parents=True, exist_ok=True)
    outputs, schema_reviews, accessions, series = [], [], Counter(), set()
    fixed_types = {'is_amendment': pa.bool_(), 'source_row_number': pa.int64(),
                   'available_at_utc': pa.timestamp('ns', tz='UTC'),
                   **{n: pa.decimal128(38,12) for n in ('balance_numeric','value_usd','percent_net_assets','exchange_rate_numeric')}}
    for name,dataset in DATASETS.items():
        if shutil.disk_usage(destination).free < MIN_FREE_DISK: raise ValueError('NPORT_FREE_DISK_BUDGET_INSUFFICIENT')
        sources = [next(o for o in item['outputs'] if o['dataset']==dataset) for item in ordered]
        schemas = [pq.ParquetFile(o['path']).schema_arrow.remove_metadata() for o in sources]
        for schema in schemas:
            for field in schema:
                if field.name in fixed_types:
                    if field.type != fixed_types[field.name]: raise ValueError('MERGE_DERIVED_TYPE_DIFFERENCE_REQUIRES_REVIEW')
                elif not (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)):
                    raise ValueError('MERGE_PROVIDER_TYPE_DIFFERENCE_REQUIRES_REVIEW')
        schema = pa.unify_schemas(schemas, promote_options='permissive')
        schema_reviews.append({'dataset': dataset, 'provider_fields_all_unbounded_strings': True,
            'numeric_types_exact_decimal_no_float_conversion': True,
            'different_source_column_sets': len({tuple(s.names) for s in schemas}) > 1,
            'missing_source_fields': {q:sorted(set(schema.names)-set(s.names)) for q,s in zip(quarters,schemas)},
            'union_rule': 'ONLY_SOURCE_STRING_FIELD_ADDITION_PERMITTED_ABSENT_FIELD_IS_NULL_ORIGINAL_BLANK_STAYS_EMPTY'})
        final = destination / (dataset + '.parquet')
        temp = final.with_suffix('.parquet.tmp')
        if final.exists() or temp.exists(): raise ValueError('MERGE_EXISTING_OUTPUT_PRESERVED')
        count = 0
        with pq.ParquetWriter(temp, schema, compression='zstd') as writer:
            for source in sources:
                for batch in pq.ParquetFile(source['path']).iter_batches(batch_size=CHUNK_ROWS):
                    table = pa.Table.from_batches([batch]).replace_schema_metadata(None)
                    if name == 'FILINGS':
                        accessions.update(table['accession'].to_pylist())
                        series.update(s for s in table['series_id'].to_pylist() if s)
                    columns = [table[f.name].cast(f.type, safe=True) if f.name in table.column_names else pa.nulls(len(table), type=f.type) for f in schema]
                    writer.write_table(pa.Table.from_arrays(columns, schema=schema))
                    count += len(table)
        if count != sum(o['row_count'] for o in sources) or pq.ParquetFile(temp).metadata.num_rows != count:
            raise ValueError('MERGED_ROW_COUNT_DIFFERS')
        temp.replace(final)
        outputs.append({'dataset': dataset, **file_identity(final), 'rows': count, 'row_count': count,
                        'date_column': 'filing_date', 'min_date': min((s['min_date'] for s in sources if s['min_date']),default=None),
                        'max_date': max((s['max_date'] for s in sources if s['max_date']),default=None), 'source_table':name})
        print(f'NPORT MERGED {name} rows={count}', flush=True)
    result = {'role':'SEC_NPORT_PUBLIC_BULK_INTAKE', 'status':'VALIDATED_DATA_ONLY', 'contract':contract,
              'outputs':outputs, 'schema_reviews':schema_reviews, 'quarters':quarters,
              'filings':sum(accessions.values()), 'unique_accessions':len(accessions), 'fund_series':len(series),
              'cross_package_duplicate_accessions':sum(n>1 for n in accessions.values()),
              'cross_package_duplicate_filing_rows':sum(n-1 for n in accessions.values()),
              'amendment_filings':sum(item['amendment_filings'] for item in ordered),
              'missing_series_identity':sum(item['missing_series_identity'] for item in ordered),
              'report_date_review_rows':sum(item['report_date_review_rows'] for item in ordered),
              'source_archive_bytes':sum(item['source'].get('bytes',0) for item in ordered),
              'historical_pit_certified':False, 'available_at_semantics':'UNKNOWN_NULL_NO_60_DAY_INFERENCE',
              'research_usage':'HISTORICAL_INPUT_REQUIRES_PIT_QUALIFICATION_2026_PLUS_OBSERVATION_ONLY',
              'limits':ordered[-1]['limitations']+['CROSS_PACKAGE_DUPLICATE_ACCESSIONS_RETAINED_NO_AUTOMATIC_DEDUPLICATION'],
              'latest_bulk_evidence_url':INDEX_URL, 'provider_readme_url':README_URL,
              'unit_evidence_url':FORM_URL, 'effective_rule_delay_url':RULE_URL, '2026_proposal_url':PROPOSAL_URL}
    save_json(report,result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--quarters', nargs='+', default=['2026q2'])
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--merge', action='store_true', help='Produce five combined files after all selected packages validate')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.run_id): raise ValueError('INVALID_RUN_ID')
    as_of = date.fromisoformat(args.as_of)
    if as_of > date.today() or any(quarter_end(q) > as_of for q in args.quarters): raise ValueError('FUTURE_DATE_SCOPE')
    paths = resolve()
    if not args.execute:
        print(json.dumps({'urls': [source_url(q) for q in args.quarters], 'as_of': args.as_of,
                          'raw_root': str(paths.cache_root), 'data_root': str(paths.data_root)})); return
    manifests = []
    for quarter in args.quarters:
        raw = download(paths, args.run_id, quarter)
        result = normalize(paths, args.run_id, quarter, raw, args.as_of)
        manifests.append(result)
        print(json.dumps({'quarter': quarter, 'status': result['status'], 'filings': result['filings'],
                          'fund_series': result['fund_series'], 'outputs': result['outputs']}), flush=True)
    if args.merge:
        merged = merge_quarters(paths, args.run_id, manifests, args.as_of)
        print(json.dumps({'status':merged['status'],'quarters':merged['quarters'],'outputs':merged['outputs']}),flush=True)


if __name__ == '__main__':
    main()
