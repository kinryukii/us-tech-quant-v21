"""Run existing adapters for 21 official current datasets and preserve history.

This thin coordinator uses existing provider parsers and register_file. It never
trains, opens research outcomes, or publishes a pre2026 dataset. The public BLS
release-calendar page is separate from the successful BLS observations API.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from scripts.storage.build_data_catalog import register_file
from scripts.storage.storage_r2a import DataStore

KEYS = {
    'finra_cnms_short_volume_current': ['date', 'provider_symbol'],
    'treasury_nominal_par_yields_current': ['date', 'provider_field'],
    'treasury_real_par_yields_current': ['date', 'provider_field'],
    'bls_economic_observations_current': ['date', 'series_id'],
    'frb_h10_daily_current': ['date', 'provider_series'],
    'frb_g17_technology_industry_monthly_current': ['date', 'provider_series'],
    'cftc_tff_futures_only_major_financial_current': ['date', 'cftc_contract_market_code'],
    'treasury_tic_foreign_us_long_term_holdings_current': ['date', 'country_code'],
    'treasury_tic_long_term_gross_transactions_current': ['date', 'country_code'],
    **{f'treasury_fiscaldata_{name}_current': ['record_date', 'src_line_nbr']
       for name in ('debt_to_penny', 'operating_cash_balance', 'avg_interest_rates')},
    'treasury_fiscaldata_auctions_query_current': ['auction_date', 'cusip', 'issue_date'],
    'vix_cboe_daily': ['DATE'],
    **{f'cboe_{name}_daily_current': ['date', 'index_id']
       for name in ('vvix', 'vix9d', 'ovx', 'gvz', 'vxapl', 'vxazn', 'vxeem')},
}
UNITS = {'units', 'seasonal_adjustment', 'tenor_months', 'provider_unit', 'provider_unit_mult',
         'quote_convention', 'provider_currency', 'provider_seasonal_adjustment',
         'unit_label', 'unit_semantics', 'contract_units', 'unit', 'source_unit'}
OBSERVED = {'observed_at', 'observed_at_utc', 'retrieved_at_utc', 'retrieval_timestamp'}
STREAMING_KEY_THRESHOLD = 500_000


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('IMMUTABLE_RECEIPT_DIFFERS:' + str(path))
    else:
        with path.open('xb') as stream:
            stream.write(raw)


def key_values(table, keys):
    columns = [table[name].to_pylist() for name in keys]
    values = list(zip(*columns))
    if any(any(value is None for value in row) for row in values):
        raise ValueError('NULL_COMPOSITE_KEY')
    return values


def date_text(value):
    return value.date().isoformat() if isinstance(value, datetime) else str(value)


def merge_preserving_keys(old_path, new_path, output_path, keys, date_column):
    """Stream the large FINRA table; retain old-only keys, prefer complete new rows."""
    old_file = pq.ParquetFile(old_path)
    new = pq.read_table(new_path)
    if not old_file.schema_arrow.equals(new.schema, check_metadata=False):
        raise ValueError('SCHEMA_CHANGED_REQUIRES_PROVIDER_REVIEW')
    if not set(keys).issubset(new.column_names) or date_column not in new.column_names:
        raise ValueError('MISSING_AUTHORITY_KEY_OR_DATE_COLUMN')
    new = new.sort_by([(key, 'ascending') for key in keys])
    new_keys = key_values(new, keys)
    if len(new_keys) != len(set(new_keys)):
        raise ValueError('NEW_DUPLICATE_COMPOSITE_KEY')
    new_index = {key: index for index, key in enumerate(new_keys)}
    units = sorted(UNITS & set(new.column_names))
    observed = sorted(OBSERVED & set(new.column_names))
    if not observed:
        raise ValueError('OBSERVED_VINTAGE_COLUMN_REQUIRED')
    new_units = {name: new[name].to_pylist() for name in units}
    new_observed = {name: new[name].to_pylist() for name in observed}
    schema = old_file.schema_arrow
    old_count = kept = overlapping = 0
    all_dates = set(date_text(day) for day in new[date_column].to_pylist())
    old_dates = set()
    # FINRA's canonical writer is ordered by session and provider symbol.
    # Enforce that instead of storing ten million keys in memory.
    ordered_large = old_file.metadata.num_rows > STREAMING_KEY_THRESHOLD
    if ordered_large and keys != ['date', 'provider_symbol']:
        raise ValueError('LARGE_TABLE_WITHOUT_VERIFIED_STREAM_ORDER')
    seen = set()
    previous = None
    incoming_cursor = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise ValueError('MERGED_OUTPUT_ALREADY_EXISTS')
    with pq.ParquetWriter(output_path, schema, compression='zstd') as writer:
        for batch in old_file.iter_batches(batch_size=65536):
            table = pa.Table.from_batches([batch], schema=schema)
            batch_keys = key_values(table, keys)
            if ordered_large:
                if any(a >= b for a, b in zip(batch_keys, batch_keys[1:])) or (previous is not None and previous >= batch_keys[0]):
                    raise ValueError('OLD_DUPLICATE_OR_UNORDERED_COMPOSITE_KEY')
                previous = batch_keys[-1]
            else:
                if len(set(batch_keys)) != len(batch_keys) or seen.intersection(batch_keys):
                    raise ValueError('OLD_DUPLICATE_COMPOSITE_KEY')
                seen.update(batch_keys)
            mask = []
            old_units = {name: table[name].to_pylist() for name in units}
            old_observed = {name: table[name].to_pylist() for name in observed}
            for index, key in enumerate(batch_keys):
                incoming = new_index.get(key)
                keep = incoming is None
                mask.append(keep)
                if not keep:
                    for name in units:
                        if old_units[name][index] != new_units[name][incoming]:
                            raise ValueError('UNIT_OR_SERIES_CONVENTION_CHANGED:' + name)
                    for name in observed:
                        earlier, later = old_observed[name][index], new_observed[name][incoming]
                        if earlier is None or later is None:
                            raise ValueError('MISSING_OBSERVED_VINTAGE:' + name)
                        a = datetime.fromisoformat(str(earlier).replace('Z', '+00:00'))
                        b = datetime.fromisoformat(str(later).replace('Z', '+00:00'))
                        if a.tzinfo is None or b.tzinfo is None or b < a:
                            raise ValueError('NEW_VINTAGE_OLDER_OR_TIMEZONE_UNKNOWN')
            selected = table.filter(pa.array(mask))
            if ordered_large:
                # Keep the large FINRA output ordered for the next daily merge,
                # including old-only symbols retained inside revised sessions.
                stop = bisect_right(new_keys, batch_keys[-1], lo=incoming_cursor)
                incoming = new.slice(incoming_cursor, stop-incoming_cursor).cast(schema)
                combined = pa.concat_tables([selected, incoming])
                if combined.num_rows:
                    writer.write_table(combined.sort_by([(key, 'ascending') for key in keys]))
                incoming_cursor = stop
            elif selected.num_rows:
                writer.write_table(selected)
            old_count += table.num_rows
            kept += selected.num_rows
            overlapping += table.num_rows - selected.num_rows
            days = {date_text(day) for day in table[date_column].to_pylist()}
            old_dates.update(days)
            all_dates.update(days)
        remaining = new.slice(incoming_cursor if ordered_large else 0).cast(schema)
        if remaining.num_rows:
            writer.write_table(remaining)
    expected = old_count + new.num_rows - overlapping
    if pq.ParquetFile(output_path).metadata.num_rows != expected or old_count != old_file.metadata.num_rows:
        raise ValueError('MERGED_ROW_COUNT_MISMATCH')
    if not old_dates.issubset(all_dates):
        raise ValueError('HISTORICAL_DATE_COVERAGE_REGRESSION')
    return {'old_rows': old_count, 'new_rows': new.num_rows, 'overlap_keys_replaced': overlapping,
            'old_only_rows_retained': kept, 'row_count': expected, 'date_coverage': len(all_dates),
            'min_date': min(all_dates), 'max_date': max(all_dates), 'unit_columns_checked': units,
            'observed_columns_checked': observed, 'all_old_keys_preserved': True,
            'all_new_rows_preserved': True, 'merge_rule': 'NEWER_OBSERVED_ROW_WINS_ON_PROVIDER_COMPOSITE_KEY'}


def receipt_output(item):
    receipt = load(item['receipt'])
    blocks = receipt.get('results', [receipt])
    for block in blocks:
        if block.get('status') not in {'SUCCESS', 'VALIDATED_DATA_ONLY'}:
            continue
        outputs = block.get('outputs', [])
        if block.get('output'):
            outputs = [{**block['output'], 'dataset': block['dataset'], 'source': block['source']}]
        for output in outputs:
            if output['dataset'] == item['source']:
                return output, block
    raise ValueError('SUCCESSFUL_OUTPUT_NOT_BOUND_TO_PROVIDER_RECEIPT')


def publish_verified_report(report_path, run_id, paths=None):
    if not re.fullmatch(r'[a-z0-9_-]{3,80}', run_id):
        raise ValueError('INVALID_PUBLICATION_RUN_ID')
    report = load(report_path)
    store = DataStore(paths)
    output_root = store.paths.data_root / 'reference/official_research/current_publication' / run_id
    evidence_root = store.paths.results_root / 'official_research_intake' / run_id / 'publication'
    report_target = Path(report_path).with_name('publish_other_data_report.json')
    summary = {'as_of': report['as_of'], 'run_id': run_id, 'results': [], 'frozen_research_modified': False}
    prepared = []
    with sqlite3.connect(store.catalog_path, timeout=30) as conn:
        untouched = conn.execute("SELECT dataset,ticker,adjustment,path,source_sha256,is_current FROM data_files WHERE dataset LIKE '%_pre2026'").fetchall()
    for item in report['sources']:
        name = item['source']
        if item['status'] not in {'SUCCESS', 'VALIDATED_DATA_ONLY'}:
            summary['results'].append({'dataset': name, 'status': 'NOT_REGISTERED_SOURCE_FAILED', 'error': item.get('error')})
            continue
        try:
            if name not in KEYS:
                raise ValueError('DATASET_NOT_IN_BOUNDED_OFFICIAL_ALLOWLIST')
            output, provider = receipt_output(item)
            new_path = Path(output['path']).resolve()
            new_hash = output['sha256']
            if not any(new_path.is_relative_to(root.resolve()) for root in (store.paths.data_root, store.paths.cache_root)):
                raise ValueError('OUTPUT_OUTSIDE_EXISTING_DATA_OR_CACHE_ROOT')
            if sha(new_path) != new_hash or pq.ParquetFile(new_path).metadata.num_rows != output.get('row_count', output.get('rows')):
                raise ValueError('NEW_OUTPUT_IDENTITY_FAILED')
            old = store.metadata(name)
            if old['format'] != 'parquet' or old['source'] != output['source']:
                raise ValueError('PRIOR_FORMAT_OR_PROVIDER_SOURCE_CHANGED')
            old_hash = old['source_sha256']
            if sha(old['path']) != old_hash:
                raise ValueError('OLD_OUTPUT_IDENTITY_FAILED')
            date_column = output.get('date_column', old['lineage'].get('date_column', 'date'))
            merged = output_root / (name + '.parquet')
            stats = merge_preserving_keys(Path(old['path']), new_path, merged, KEYS[name], date_column)
            if stats['min_date'] > old['min_date'] or stats['max_date'] < old['max_date']:
                raise ValueError('CATALOG_COVERAGE_REGRESSION')
            if sha(old['path']) != old_hash or sha(new_path) != new_hash:
                raise ValueError('INPUT_CHANGED_DURING_MERGE')
            manifest_path = evidence_root / (name + '.json')
            manifest = {'dataset': name, 'status': 'PREPARED_HISTORY_PRESERVING_CURRENT',
                        'date_column': date_column, 'composite_key': KEYS[name], 'as_of': report['as_of'],
                        'prior_catalog_metadata': old,
                        'new_provider_receipt': {'path': item['receipt'], 'sha256': sha(item['receipt'])},
                        'new_output': output, 'new_provider_semantics': {key: provider[key] for key in
                            ('limitations', 'semantics', 'series_freshness', 'release', 'vintage_semantics') if key in provider},
                        'output': {'path': str(merged), 'sha256': sha(merged), **stats},
                        'source_code_sha256': sha(__file__), 'old_file_unchanged': True}
            save_new(manifest_path, manifest)
            lineage = {'date_column': date_column, 'as_of': report['as_of'],
                       'manifest_path': str(manifest_path), 'manifest_sha256': sha(manifest_path),
                       'input_sources': [{'path': old['path'], 'sha256': old_hash, 'role': 'PRIOR_SELECTED_HISTORY'},
                                         {'path': str(new_path), 'sha256': new_hash, 'role': 'LATEST_PROVIDER_OBSERVATIONS'}],
                       'composite_key': KEYS[name], 'date_coverage': stats['date_coverage'],
                       'merge_rule': stats['merge_rule'], 'all_old_keys_preserved': True,
                       'unit_columns_checked': stats['unit_columns_checked'],
                       'observed_columns_preserved': stats['observed_columns_checked'],
                       'vintage_semantics': 'CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT',
                       'historical_pit_certified': False, 'available_at_semantics': 'UNKNOWN_NULL',
                       'automatic_factor_promotion': False,
                       'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST'}
            prepared.append((name, old, output['source'], merged, stats, lineage))
            summary['results'].append({'dataset': name, 'status': 'PREPARED', 'new_current_path': str(merged),
                                       'prior_path': old['path'], 'receipt': str(manifest_path), **stats})
            print(json.dumps({'dataset': name, 'status': 'PREPARED', 'rows': stats['row_count']}), flush=True)
        except Exception as exc:
            summary['results'].append({'dataset': name, 'status': 'NOT_REGISTERED', 'error': str(exc)})
            print(json.dumps({'dataset': name, 'status': 'NOT_REGISTERED', 'error': str(exc)}), flush=True)
    with sqlite3.connect(store.catalog_path, timeout=30) as conn:
        conn.execute('BEGIN IMMEDIATE')
        for name, old, source, merged, stats, lineage in prepared:
            current = conn.execute('SELECT path,source_sha256 FROM data_files WHERE dataset=? AND ticker=? AND adjustment=? AND is_current=1', (name, '', '')).fetchall()
            if current != [(old['path'], old['source_sha256'])]:
                raise ValueError('CATALOG_CHANGED_CONCURRENTLY:' + name)
            register_file(conn, name, '', '', merged, stats['row_count'], stats['min_date'], stats['max_date'], source, lineage)
        if conn.execute("SELECT dataset,ticker,adjustment,path,source_sha256,is_current FROM data_files WHERE dataset LIKE '%_pre2026'").fetchall() != untouched:
            raise ValueError('PRE2026_DATASET_POINTERS_CHANGED')
    for item in summary['results']:
        if item['status'] != 'PREPARED':
            continue
        current = store.metadata(item['dataset'])
        date_column = current['lineage']['date_column']
        sample = store.read(item['dataset'], start_date=item['max_date'], end_date=item['max_date'],
                            columns=KEYS[item['dataset']], date_column=date_column)
        if current['path'] != item['new_current_path'] or sample.empty or sample.duplicated(KEYS[item['dataset']]).any():
            raise ValueError('DATASTORE_CURRENT_READBACK_FAILED:' + item['dataset'])
        item.update(status='REGISTERED_AND_DATASTORE_READ_VERIFIED', latest_readback_rows=len(sample))
    summary.update(completed_at_utc=datetime.now(timezone.utc).isoformat(),
                   registered_datasets=sum(item['status']=='REGISTERED_AND_DATASTORE_READ_VERIFIED' for item in summary['results']),
                   pre2026_dataset_pointers_unchanged=True, source_files_overwritten=False)
    save_new(report_target, summary)
    save_new(evidence_root/'publication_report.json', summary)
    print(json.dumps({'registered_datasets': summary['registered_datasets'], 'report': str(report_target)}), flush=True)
    return summary


def current_source_jobs(paths, run_id, as_of, latest_completed_session, store=None):
    """Fixed provider CLI contracts; only FINRA/H10/BLS request incremental scope."""
    if not re.fullmatch(r'[a-z0-9_-]{3,80}', run_id):
        raise ValueError('INVALID_RUN_ID')
    today = date.fromisoformat(as_of)
    target = date.fromisoformat(latest_completed_session)
    if target > today:
        raise ValueError('COMPLETED_SESSION_AFTER_AS_OF')
    store = store or DataStore(paths)

    def overlap(dataset, fallback):
        try:
            last = date.fromisoformat(store.metadata(dataset)['max_date'])
        except (KeyError, FileNotFoundError):
            return fallback
        return (min(last, target) - timedelta(days=2)).isoformat()

    root = paths.results_root / 'official_research_intake' / run_id
    common = ['--run-id', run_id, '--as-of', as_of]
    return [
        ('scripts.storage.refresh_public_sources', ['--repo', paths.repo_root, '--work-root', paths.cache_root/'official_research_intake'/run_id/'public',
             '--target-date', as_of, '--sources', 'vix', 'cboe_indices', '--execute']),
        ('scripts.storage.refresh_official_research_data', [*common,
             '--finra-start', overlap('finra_cnms_short_volume_current', latest_completed_session),
             '--finra-end', latest_completed_session, '--first-year', str(target.year), '--last-year', str(target.year), '--execute']),
        ('scripts.storage.refresh_bls_observations', [*common,
             '--start-year', str(today.year-1 if today.month<=2 else today.year), '--execute']),
        ('scripts.storage.refresh_frb_h10', [*common,
             '--start-date', overlap('frb_h10_daily_current', (target-timedelta(days=14)).isoformat())]),
        ('scripts.storage.refresh_frb_g17', [*common, '--execute']),
        ('scripts.storage.refresh_cftc_cot', [*common, '--execute']),
        ('scripts.storage.refresh_treasury_tic', common),
        ('scripts.storage.refresh_fiscaldata', [*common, '--tables', 'debt_to_penny', 'operating_cash_balance',
             'avg_interest_rates', 'auctions_query', '--execute']),
    ]


def run_current_sources(paths, run_id, as_of, latest_completed_session, emit_progress=lambda message: None, runner=None):
    """Run the existing eight provider jobs, then publish verified 21-dataset rows.

    ``runner(module, arguments, log_path)`` may reuse the application's existing
    subprocess wrapper. Unique run_id is required; never resumes a failed source
    request automatically or silently publishes an acquisition failure.
    """
    run_id = str(run_id).lower()
    jobs = current_source_jobs(paths, run_id, as_of, latest_completed_session)
    root = paths.results_root / 'official_research_intake' / run_id
    if root.exists():
        raise ValueError('CURRENT_SOURCE_RUN_REQUIRES_UNIQUE_ID')
    root.mkdir(parents=True)

    def default_runner(module, arguments, log_path):
        with log_path.open('w', encoding='utf-8') as stream:
            try:
                process = subprocess.run([str(paths.python_exe), '-B', '-m', module, *map(str, arguments)],
                    cwd=paths.repo_root, stdout=stream, stderr=subprocess.STDOUT, timeout=3600,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                return {'module': module, 'exit_code': process.returncode, 'log_path': str(log_path)}
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {'module': module, 'exit_code': -1, 'log_path': str(log_path), 'error': str(exc)}

    invoke = runner or default_runner
    receipts = []
    # Provider adapters already own their rate limits; separate sources execute
    # independently, while all catalog publication happens only after joining.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    emit_progress('更新 21 个已配置公开数据集；各来源失败单独记录。')
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(invoke, module, args, root/(module.rsplit('.', 1)[-1]+'.log')): module
                   for module, args in jobs}
        for future in as_completed(futures):
            module = futures[future]
            try:
                receipts.append(future.result())
            except Exception as exc:
                receipts.append({'module': module, 'exit_code': -1, 'error': str(exc)})
    manifest_paths = [root/name for name in ('manifest.json', 'bls_manifest.json', 'frb_h10/manifest.json',
        'frb_g17/manifest.json', 'cftc_cot/manifest.json', 'treasury_tic/manifest.json',
        'fiscaldata/debt_to_penny/manifest.json', 'fiscaldata/operating_cash_balance/manifest.json',
        'fiscaldata/avg_interest_rates/manifest.json', 'fiscaldata/auctions_query/manifest.json')]
    manifest_paths += sorted((paths.cache_root/'official_research_intake'/run_id/'public').glob('*/acquisition_report.json'))
    sources = []
    for path in manifest_paths:
        if not path.is_file():
            continue
        manifest = load(path)
        for block in manifest.get('results', [manifest]):
            if block.get('status') not in {'SUCCESS', 'VALIDATED_DATA_ONLY'}:
                continue
            outputs = block.get('outputs', [])
            if block.get('output'):
                outputs = [{**block['output'], 'dataset': block['dataset']}]
            for output in outputs:
                sources.append({'source': output['dataset'], 'status': block['status'],
                    'receipt': str(path), 'output_path': output['path'], 'sha256': output['sha256']})
    names = [row['source'] for row in sources]
    if len(names) != len(set(names)):
        raise ValueError('DUPLICATE_DATASET_RECEIPTS_IN_RUN')
    for missing in sorted(set(KEYS)-set(names)):
        sources.append({'source': missing, 'status': 'ACQUISITION_NOT_VALIDATED',
                        'error': 'No successful provider receipt; see job logs.'})
    acquisition = {'schema_version': 1, 'as_of': as_of, 'latest_completed_market_session': latest_completed_session,
                   'sources': sources, 'jobs': receipts,
                   'skipped_sources': [{'source': 'BLS_RELEASE_SCHEDULE', 'reason': 'PREVIOUS_HTTP403_NOT_RETRIED; BLS_OBSERVATIONS_API_INCLUDED'}]}
    report_path = root/'current_acquisition_report.json'
    save_new(report_path, acquisition)
    emit_progress('合并各来源完整历史并校验单位、观察时间及数据主键，然后更新目录。')
    publication = publish_verified_report(report_path, run_id, paths)
    return {'status': 'UPDATED' if publication['registered_datasets']==len(KEYS) else 'PARTIAL',
            'registered_datasets': publication['registered_datasets'], 'expected_datasets': len(KEYS),
            'acquisition_report': str(report_path), 'publication': publication, 'jobs': receipts,
            'skipped_sources': acquisition['skipped_sources']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--update-report', type=Path)
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--as-of')
    parser.add_argument('--latest-completed-session')
    args = parser.parse_args()
    if args.execute:
        if not args.as_of or not args.latest_completed_session:
            parser.error('--execute requires --as-of and --latest-completed-session')
        result = run_current_sources(DataStore().paths, args.run_id, args.as_of, args.latest_completed_session)
        print(json.dumps(result), flush=True)
    else:
        publish_verified_report(args.update_report, args.run_id)
