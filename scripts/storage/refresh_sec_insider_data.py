"""Archive and normalize SEC Form 4/4A without constructing a research signal.

Reuse official quarterly raw ZIPs, FAST6 acquisition, storage routing and catalog
file identities. Eight SEC tables remain separate; numeric source text is never
rounded. Bulk filing dates are not acceptance timestamps. No catalog mutation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.common.storage_paths import resolve
from scripts.storage.refresh_13f_quarter import configured_user_agent
from scripts.storage.refresh_official_research_data import archive_module, save_json
from scripts.storage.restore_sec_data import file_identity, sha256_file
from scripts.storage.storage_r2a import DataStore

TABLES = ('SUBMISSION', 'REPORTINGOWNER', 'NONDERIV_TRANS', 'NONDERIV_HOLDING',
          'DERIV_TRANS', 'DERIV_HOLDING', 'FOOTNOTES', 'OWNER_SIGNATURE')
SOURCE_PAGE = 'https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets'
README = 'https://www.sec.gov/files/insider_transactions_readme.pdf'
VINTAGE = 'CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT'
FIELDS = {
    'SECURITY_TITLE': 'securityTitle', 'TRANS_DATE': 'transactionDate',
    'DEEMED_EXECUTION_DATE': 'deemedExecutionDate',
    'TRANS_FORM_TYPE': 'transactionCoding/transactionFormType',
    'TRANS_CODE': 'transactionCoding/transactionCode',
    'EQUITY_SWAP_INVOLVED': 'transactionCoding/equitySwapInvolved',
    'TRANS_TIMELINESS': 'transactionTimeliness',
    'TRANS_SHARES': 'transactionAmounts/transactionShares',
    'TRANS_TOTAL_VALUE': 'transactionAmounts/transactionTotalValue',
    'TRANS_PRICEPERSHARE': 'transactionAmounts/transactionPricePerShare',
    'TRANS_ACQUIRED_DISP_CD': 'transactionAmounts/transactionAcquiredDisposedCode',
    'SHRS_OWND_FOLWNG_TRANS': 'postTransactionAmounts/sharesOwnedFollowingTransaction',
    'VALU_OWND_FOLWNG_TRANS': 'postTransactionAmounts/valueOwnedFollowingTransaction',
    'DIRECT_INDIRECT_OWNERSHIP': 'ownershipNature/directOrIndirectOwnership',
    'NATURE_OF_OWNERSHIP': 'ownershipNature/natureOfOwnership',
    'CONV_EXERCISE_PRICE': 'conversionOrExercisePrice',
    'EXERCISE_DATE': 'exerciseDate', 'EXPIRATION_DATE': 'expirationDate',
    'UNDLYNG_SEC_TITLE': 'underlyingSecurity/underlyingSecurityTitle',
    'UNDLYNG_SEC_SHARES': 'underlyingSecurity/underlyingSecurityShares',
    'UNDLYNG_SEC_VALUE': 'underlyingSecurity/underlyingSecurityValue',
}
COMMON = {'accession': pa.string(), 'issuer_cik': pa.int64(), 'form': pa.string(),
          'filing_date': pa.date32(), 'accepted_at': pa.timestamp('us', tz='UTC'),
          'acceptance_status': pa.string(), 'transaction_date': pa.date32(),
          'source_url': pa.string(), 'source_sha256': pa.string(),
          'retrieved_at': pa.timestamp('ns', tz='UTC'), 'source_member': pa.string(),
          'source_row': pa.int64(), 'source_format': pa.string(), 'source_xml': pa.string()}


@lru_cache(maxsize=8192)
def iso_day(value):
    if value in (None, ''):
        return None
    for fmt in ('%Y-%m-%d', '%d-%b-%Y'):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            pass
    raise ValueError('INVALID_SEC_DATE:' + str(value))


def timestamp(value):
    if not value:
        raise ValueError('MISSING_RETRIEVAL_TIMESTAMP')
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError('SOURCE_TIMESTAMP_WITHOUT_TIMEZONE')
    return result.tz_convert('UTC')


def verified_raw(record, store=None):
    path = Path(record['local_path'])
    if store:
        path = store._check_data_path(path)
    if record.get('status') == 'FAILED' or sha256_file(path) != record.get('sha256'):
        raise ValueError('RAW_IDENTITY_MISMATCH')
    timestamp(record.get('retrieval_timestamp_utc'))
    if not re.fullmatch(r'https://www\.sec\.gov/(?:(?:files|Archives)/[^\s]+|cgi-bin/browse-edgar\?action=getcurrent&[^\s]+)', record['source_reference']):
        raise ValueError('UNEXPECTED_SEC_SOURCE_URL')
    if record.get('status') != 'REUSED_LEGACY_VERIFIED':
        metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        for key in ('sha256', 'source_reference', 'retrieval_timestamp_utc'):
            if metadata.get(key) != record.get(key):
                raise ValueError('RAW_METADATA_MISMATCH:' + key)
    return path


def master_tasks(raw, ciks, start, as_of):
    lines = raw.decode('latin-1').splitlines()
    header = 'CIK|Company Name|Form Type|Date Filed|Filename'
    if lines.count(header) != 1:
        raise ValueError('INVALID_MASTER_INDEX_HEADER')
    allowed, tasks, days = set(ciks), {}, []
    for line in lines[lines.index(header) + 1:]:
        if not line or set(line.strip()) == {'-'}:
            continue
        cells = line.split('|')
        if len(cells) != 5 or not cells[0].isdigit():
            raise ValueError('INVALID_MASTER_INDEX_ROW')
        cik, _, form, filed, filename = cells
        iso_day(filed)
        days.append(filed)
        if int(cik) not in allowed or form not in ('4', '4/A') or not start <= filed <= as_of:
            continue
        if not re.fullmatch(r'edgar/data/\d+/\d{10}-\d{2}-\d{6}\.txt', filename):
            raise ValueError('INVALID_MASTER_FILING_PATH')
        task = dict(cik=int(cik), form=form, filed_date=filed, filename=filename,
                    accession=Path(filename).stem, url='https://www.sec.gov/Archives/' + filename)
        if filename in tasks and tasks[filename] != task:
            raise ValueError('CONFLICTING_MASTER_INDEX_FILING')
        tasks[filename] = task
    if not days:
        raise ValueError('EMPTY_MASTER_INDEX')
    return sorted(tasks.values(), key=lambda x: (x['filed_date'], x['accession'], x['cik'])), {
        'index_min_filed_date': min(days), 'index_max_filed_date': max(days),
        'index_total_rows': len(days), 'matched_form4_filings': len(tasks)}


def load_scope(path):
    document = json.loads(path.read_text(encoding='utf-8'))
    ciks = document['contract']['ciks']
    if not ciks or any(type(cik) is not int or cik <= 0 for cik in ciks) or len(ciks) != len(set(ciks)):
        raise ValueError('INVALID_EXISTING_CIK_SCOPE')
    return sorted(ciks)


def legacy_bulk(path):
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if document.get('status') != 'PASS_COMPLETE':
        raise ValueError('LEGACY_ACQUISITION_NOT_COMPLETE')
    records = []
    for row in document['rows']:
        raw = path.parent.parent / 'raw_zip' / (row['quarter'].lower() + '_form345.zip')
        identity = file_identity(raw)
        if not row['valid'] or identity['bytes'] != row['file_size'] or identity['sha256'] != row['sha256'].lower():
            raise ValueError('LEGACY_RAW_IDENTITY_MISMATCH')
        records.append({'quarter': row['quarter'].upper(), 'raw': {
            'event_family': 'SEC_INSIDER_BULK', 'source': 'SEC_OFFICIAL',
            'source_reference': row['source'], 'document_kind': 'QUARTER_FORM345',
            'local_path': str(raw), 'sha256': identity['sha256'],
            'retrieval_timestamp_utc': row['download_timestamp_utc'], 'status': 'REUSED_LEGACY_VERIFIED'}})
    return records


def sec_capture(paths, stopped):
    capture = archive_module(paths.repo_root)
    capture.USER_AGENT = configured_user_agent(paths.repo_root / 'scripts/v22/stage_sec_pit_taxonomy.py')
    lock, last = threading.Lock(), [0.0]

    def once(url, timeout):
        with lock:
            wait = .51 - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            if stopped.is_set():
                raise RuntimeError('SOURCE_STOPPED_AFTER_FAILURE')
            last[0] = time.monotonic()
        request = urllib.request.Request(url, headers={'User-Agent': capture.USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError('NON200:' + str(response.status))
            return response.read()

    capture._download_once = once  # Only this isolated imported module instance.
    return capture


def acquisition_path(root):
    """Keep the failed attempt immutable and verify a bounded transport recovery."""
    original = root / 'sec_insider_acquisition.json'
    completed = root / 'sec_insider_acquisition_completed.json'
    if not completed.exists():
        return original
    previous = json.loads(original.read_text(encoding='utf-8'))
    current = json.loads(completed.read_text(encoding='utf-8'))
    if current.get('previous_acquisition') != file_identity(original):
        raise ValueError('RECOVERY_PREVIOUS_ACQUISITION_MISMATCH')
    if previous.get('status') != 'SOURCE_FAILURE' or current.get('recovery_reason') != 'TRANSPORT_TIMEOUT_WITH_NO_HTTP_RESPONSE':
        raise ValueError('RECOVERY_REASON_NOT_AUTHORIZED_TRANSPORT_TIMEOUT')
    errors = [item['raw'] for item in previous['filings']
              if item.get('raw', {}).get('status') == 'FAILED'
              and item['raw'].get('error') != 'RuntimeError: SOURCE_STOPPED_AFTER_FAILURE']
    if not errors or any(item.get('failure_class') != 'NETWORK'
                         or 'HTTPError' in item.get('error', '')
                         or not re.search(r'10060|timed out|TimeoutError', item.get('error', ''), re.I)
                         for item in errors):
        raise ValueError('RECOVERY_REFUSES_HTTP_OR_NON_TIMEOUT_FAILURE')
    for key in ('plan', 'run_id', 'start', 'as_of', 'index', 'bulk'):
        if current.get(key) != previous.get(key):
            raise ValueError('RECOVERY_SCOPE_OR_RAW_CHANGED:' + key)
    old_success = {item['url']: item['raw'] for item in previous['filings']
                   if item.get('raw', {}).get('sha256')}
    for item in current['filings']:
        if item['url'] in old_success:
            for key in ('sha256', 'source_reference', 'retrieval_timestamp_utc', 'local_path'):
                if item['raw'].get(key) != old_success[item['url']].get(key):
                    raise ValueError('RECOVERY_CHANGED_EXISTING_VINTAGE:' + key)
    return completed


def acquire(paths, args, ciks):
    root = paths.results_root / 'official_research_intake' / args.run_id
    rawroot = paths.cache_root / 'official_research_intake' / args.run_id / 'raw'
    receipt_path, plan_path = root / 'sec_insider_acquisition.json', root / 'sec_insider_plan.json'
    if receipt_path.exists():
        return json.loads(plan_path.read_text(encoding='utf-8')), json.loads(acquisition_path(root).read_text(encoding='utf-8'))
    stopped = threading.Event()
    capture = sec_capture(paths, stopped)

    def get(url, family, kind):
        return asdict(capture.acquire_url(url, family, 'SEC_OFFICIAL', kind, rawroot, timeout=60, retries=0, backoff=0))

    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        if (plan['ciks'], plan['start'], plan['as_of']) != (ciks, args.start, args.as_of):
            raise ValueError('EXISTING_PLAN_SCOPE_MISMATCH')
        bulk = plan['bulk_existing'].copy()
    else:
        day = date.fromisoformat(args.as_of)
        quarter = (day.month - 1) // 3 + 1
        index = get(f'https://www.sec.gov/Archives/edgar/full-index/{day.year}/QTR{quarter}/master.idx',
                    'SEC_INSIDER_INDEX', 'QUARTER_MASTER_INDEX')
        if index['status'] == 'FAILED':
            save_json(root / 'sec_insider_index_failure.json', index)
            raise ValueError('OFFICIAL_INDEX_UNAVAILABLE')
        tasks, _ = master_tasks(verified_raw(index).read_bytes(), ciks,
                               f'{day.year}-{3 * quarter - 2:02d}-01', args.as_of)
        bulk = legacy_bulk(args.legacy_manifest)
        plan = dict(schema_version=1, run_id=args.run_id, start=args.start, as_of=args.as_of,
                    ciks=ciks, ciks_manifest=file_identity(args.ciks_manifest),
                    legacy_manifest=file_identity(args.legacy_manifest), index=index,
                    bulk_existing=bulk, filing_tasks=tasks, minimum_request_interval_seconds=.51)
        save_json(plan_path, plan)
    expected = pd.period_range(args.start, args.as_of, freq='Q')[:-1]
    present = {item['quarter'] for item in bulk}
    bulk_failed = False
    for period in expected:
        if str(period) in present:
            continue
        route = 'datastandardsinnovation' if period >= pd.Period('2026Q2') else 'structureddata'
        url = f'https://www.sec.gov/files/{route}/data/insider-transactions-data-sets/{str(period).lower()}_form345.zip'
        doc = get(url, 'SEC_INSIDER_BULK', 'QUARTER_FORM345')
        bulk.append({'quarter': str(period), 'raw': doc})
        if doc['status'] == 'FAILED':
            bulk_failed = True
            break  # Do not substitute a different endpoint after denial.

    def fetch(task):
        if stopped.is_set():
            return {**task, 'status': 'NOT_REQUESTED_AFTER_SOURCE_FAILURE'}
        raw = get(task['url'], 'SEC_INSIDER_FILINGS', 'FULL_FORM4_TXT')
        status = raw['status']
        if status == 'FAILED':
            stopped.set()
        elif not Path(raw['local_path']).read_bytes().startswith(b'<SEC-DOCUMENT>'):
            status = 'INVALID_SEC_TXT'
            stopped.set()
        return {**task, 'raw': raw, 'status': status}

    filings = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for number, item in enumerate(pool.map(fetch, plan['filing_tasks']), 1):
            filings.append(item)
            if number % 200 == 0:
                print(json.dumps({'filings_processed': number, 'total': len(plan['filing_tasks']),
                                  'source_stopped': stopped.is_set()}), flush=True)
    receipt = dict(schema_version=1, run_id=args.run_id, start=args.start, as_of=args.as_of,
                   plan=file_identity(plan_path), index=plan['index'], bulk=bulk, filings=filings,
                   status='SOURCE_FAILURE' if stopped.is_set() or bulk_failed else 'ACQUIRED_COMPLETE')
    save_json(receipt_path, receipt)
    return plan, receipt


def zip_tables(path):
    with zipfile.ZipFile(path) as archive:
        names = {Path(name).stem.upper(): name for name in archive.namelist() if name.endswith('.tsv')}
        if set(names) != set(TABLES) or archive.testzip() is not None:
            raise ValueError('BULK_TABLE_OR_CRC_MISMATCH')
        # All source fields, including decimal text and literal quotes, are retained.
        return {name: pd.read_csv(archive.open(member), sep='\t', dtype=str, keep_default_na=False,
                                  quoting=csv.QUOTE_NONE) for name, member in names.items()}


def current_entries(payload):
    """Parse the official all-form Atom feed; type=4 is only a prefix filter."""
    root = ET.fromstring(payload)
    namespace = {'a': 'http://www.w3.org/2005/Atom'}
    if root.tag != '{http://www.w3.org/2005/Atom}feed':
        raise ValueError('NOT_SEC_ATOM_FEED')
    updated = timestamp(root.findtext('a:updated', namespaces=namespace))
    entries = []
    for entry in root.findall('a:entry', namespace):
        title = entry.findtext('a:title', '', namespace)
        ciks = re.findall(r'\((\d{10})\)', title)
        accession = re.search(r'accession-number=(\d{10}-\d{2}-\d{6})$', entry.findtext('a:id', '', namespace))
        filed = re.search(r'<b>Filed:</b>\s*(\d{4}-\d{2}-\d{2})', entry.findtext('a:summary', '', namespace))
        category = entry.find('a:category', namespace)
        link = entry.find('a:link', namespace)
        if len(ciks) != 1 or not accession or not filed or category is None or link is None:
            raise ValueError('ATOM_ENTRY_IDENTITY_OR_DATE_MISSING')
        cik, accession = int(ciks[0]), accession[1]
        match = re.fullmatch(r'https://www\.sec\.gov/Archives/(edgar/data/\d+/\d{18}/)' +
                             re.escape(accession) + r'-index\.html?', link.attrib.get('href', ''))
        if not match:
            raise ValueError('ATOM_NONOFFICIAL_OR_UNSUPPORTED_FILING_LINK')
        filename = match[1] + accession + '.txt'
        entries.append({'cik': cik, 'form': category.attrib['term'], 'filed_date': filed[1],
                        'accession': accession, 'filename': filename,
                        'url': 'https://www.sec.gov/Archives/' + filename,
                        'feed_accepted_at': timestamp(entry.findtext('a:updated', namespaces=namespace)).isoformat(),
                        'feed_title': title})
    return updated, entries


def intraday_once(paths, args, ciks):
    """One bounded all-form metadata sweep, then only scoped new Form 4 TXT."""
    root = paths.results_root / 'official_research_intake' / args.run_id
    destination = root / 'sec_intraday_filings_snapshot.json'
    if destination.exists():
        return json.loads(destination.read_text(encoding='utf-8'))
    rawroot = paths.cache_root / 'official_research_intake' / args.run_id / 'raw'
    stopped = threading.Event()
    capture = sec_capture(paths, stopped)
    pages, entries, failures, anchor, complete = [], {}, [], None, False
    for page in range(20):
        url = ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&start='
               + str(page * 100) + '&count=100&output=atom')
        raw = asdict(capture.acquire_url(url, 'SEC_INSIDER_INTRADAY', 'SEC_OFFICIAL',
                     'CURRENT_FILINGS_ATOM', rawroot, timeout=30, retries=0, backoff=0))
        if raw['status'] == 'FAILED':
            failures.append(raw)
            break
        updated, rows = current_entries(verified_raw(raw).read_bytes())
        anchor = anchor or updated
        pages.append(raw)
        for row in rows:
            if row['filed_date'] == args.as_of and timestamp(row['feed_accepted_at']) <= anchor and row['cik'] in ciks:
                key = (row['cik'], row['accession'])
                if key in entries and entries[key] != row:
                    raise ValueError('INTRADAY_FEED_CHANGED_DURING_CAPTURE')
                entries[key] = row
        if not rows or len(rows) < 100 or any(row['filed_date'] < args.as_of for row in rows):
            complete = True
            break
    filings = []
    if complete:
        for row in sorted(entries.values(), key=lambda x: (x['accession'], x['cik'])):
            if row['form'] not in ('4', '4/A'):
                continue
            raw = asdict(capture.acquire_url(row['url'], 'SEC_INSIDER_INTRADAY', 'SEC_OFFICIAL',
                         'FULL_FORM4_TXT', rawroot, timeout=45, retries=0, backoff=0))
            filings.append({**row, 'raw': raw, 'status': raw['status']})
            if raw['status'] == 'FAILED':
                failures.append(raw)
                break
    document = {'schema_version': 1, 'as_of': args.as_of, 'scope_ciks': ciks,
                'status': 'ACQUIRED_COMPLETE' if complete and not failures else 'INTRADAY_UNAVAILABLE_OR_INCOMPLETE',
                'source': 'SEC_CURRENT_FILINGS_ATOM', 'feed_anchor_utc': anchor.isoformat() if anchor else None,
                'completed_day_start_boundary': complete, 'pages': pages, 'failures': failures,
                'entries': sorted(entries.values(), key=lambda x: (x['accession'], x['cik'])),
                'form4_filings': filings, 'max_pages': 20,
                'semantics': 'One current-feed snapshot bounded by first feed update time; not the full future calendar day.'}
    save_json(destination, document)
    return document


def verify_intraday(document, ciks, as_of, store):
    if document['as_of'] != as_of or document['scope_ciks'] != ciks:
        raise ValueError('INTRADAY_SCOPE_MISMATCH')
    expected, boundary = {}, False
    for page, raw in enumerate(document['pages']):
        url = ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&start='
               + str(page * 100) + '&count=100&output=atom')
        if raw['source_reference'] != url or page >= 20:
            raise ValueError('INTRADAY_PAGE_SCOPE_MISMATCH')
        updated, rows = current_entries(verified_raw(raw, store).read_bytes())
        if page == 0 and updated.isoformat() != document['feed_anchor_utc']:
            raise ValueError('INTRADAY_ANCHOR_MISMATCH')
        for row in rows:
            if row['filed_date'] == as_of and timestamp(row['feed_accepted_at']) <= timestamp(document['feed_anchor_utc']) and row['cik'] in ciks:
                key = (row['cik'], row['accession'])
                if key in expected and expected[key] != row:
                    raise ValueError('INTRADAY_FEED_CONFLICT')
                expected[key] = row
        boundary = not rows or len(rows) < 100 or any(row['filed_date'] < as_of for row in rows)
    if document['entries'] != sorted(expected.values(), key=lambda x: (x['accession'], x['cik'])):
        raise ValueError('INTRADAY_ENTRY_COMPLETENESS_MISMATCH')
    if document['status'] != 'ACQUIRED_COMPLETE':
        return []
    candidates = {key: row for key, row in expected.items() if row['form'] in ('4', '4/A')}
    filings = {(item['cik'], item['accession']): item for item in document['form4_filings']}
    if (not boundary or document['failures'] or not document['completed_day_start_boundary'] or
            set(candidates) != set(filings) or len(filings) != len(document['form4_filings'])):
        raise ValueError('INTRADAY_FILING_COMPLETENESS_MISMATCH')
    for key, row in candidates.items():
        item = filings[key]
        if any(item.get(field) != value for field, value in row.items()) or item['raw']['source_reference'] != row['url']:
            raise ValueError('INTRADAY_FILING_IDENTITY_MISMATCH')
        verified_raw(item['raw'], store)
    return list(filings.values())


def common_row(row, raw, source_format, member, source_row, accepted=None):
    accession = row['ACCESSION_NUMBER']
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
        raise ValueError('INVALID_ACCESSION')
    return dict(accession=accession, issuer_cik=int(row['ISSUERCIK']), form=row['DOCUMENT_TYPE'],
                filing_date=iso_day(row['FILING_DATE']), accepted_at=accepted,
                acceptance_status='KNOWN_SEC_HEADER' if accepted else 'UNKNOWN_IN_BULK',
                transaction_date=None, source_url=raw['source_reference'], source_sha256=raw['sha256'],
                retrieved_at=timestamp(raw['retrieval_timestamp_utc']), source_member=member,
                source_row=source_row, source_format=source_format, source_xml=None)


def normalize_bulk(tables, raw, ciks, start, as_of):
    sub = tables['SUBMISSION']
    required = {'ACCESSION_NUMBER', 'DOCUMENT_TYPE', 'ISSUERCIK', 'FILING_DATE'}
    if not required.issubset(sub.columns):
        raise ValueError('BULK_SUBMISSION_FIELDS_MISSING')
    allowed = {str(cik) for cik in ciks}
    selected = sub.loc[sub.DOCUMENT_TYPE.isin(['4', '4/A']) &
                       sub.ISSUERCIK.str.lstrip('0').isin(allowed)].copy()
    selected['__day'] = selected.FILING_DATE.map(iso_day)
    selected = selected.loc[selected.__day.between(iso_day(start), iso_day(as_of))].drop(columns=['__day'])
    if selected.ACCESSION_NUMBER.duplicated().any():
        raise ValueError('DUPLICATE_BULK_ACCESSION')
    parents = {row['ACCESSION_NUMBER']: row for row in selected.to_dict('records')}
    common = {key: common_row(row, raw, 'SEC_QUARTER_TSV', '', 0) for key, row in parents.items()}
    result = {}
    for name in TABLES:
        source = tables[name]
        if 'ACCESSION_NUMBER' not in source.columns:
            raise ValueError('BULK_TABLE_ACCESSION_MISSING')
        records = []
        for ordinal, row in enumerate(source.to_dict('records'), 2):
            accession = row['ACCESSION_NUMBER']
            if accession not in parents:
                continue
            records.append({**row, **common[accession], 'source_member': name + '.tsv',
                            'source_row': ordinal, 'transaction_date': iso_day(row.get('TRANS_DATE'))})
        result[name] = records
    return result


def element_value(element, path):
    found = element.find(path)
    if found is None:
        return None, None
    child = found.find('value')
    value = child.text if child is not None else found.text
    ids = [node.attrib['id'] for node in found.iter('footnoteId') if 'id' in node.attrib]
    return value.strip() if value else '', ','.join(ids) if ids else None


def normalize_filing(payload, task, raw, ciks, as_of):
    if not payload.startswith(b'<SEC-DOCUMENT>'):
        raise ValueError('NOT_SEC_FULL_SUBMISSION')
    text = payload.decode('utf-8-sig')
    accessions = re.findall(r'ACCESSION NUMBER:\s*(\d{10}-\d{2}-\d{6})', text)
    dates = re.findall(r'<ACCEPTANCE-DATETIME>(\d{14})', text)
    if accessions != [task['accession']] or len(dates) != 1:
        raise ValueError('SEC_HEADER_IDENTITY_OR_ACCEPTANCE_MISSING')
    accepted = datetime.strptime(dates[0], '%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    cutoff = datetime.combine(iso_day(as_of) + timedelta(days=1), datetime.min.time(), ZoneInfo('America/New_York'))
    if accepted >= cutoff:
        raise ValueError('ACCEPTANCE_AFTER_AS_OF')
    documents = []
    for xml in re.findall(r'<XML>(.*?)</XML>', text, re.S):
        root = ET.fromstring(xml.strip())
        for node in root.iter():
            node.tag = node.tag.split('}')[-1]
        if root.tag == 'ownershipDocument':
            documents.append(root)
    if len(documents) != 1:
        raise ValueError('EXPECTED_ONE_OWNERSHIP_DOCUMENT')
    root = documents[0]
    form, issuer = root.findtext('documentType'), int(root.findtext('issuer/issuerCik'))
    owner_ciks = [int(node.findtext('reportingOwnerId/rptOwnerCik')) for node in root.findall('reportingOwner')]
    if form not in ('4', '4/A') or form != task['form'] or task['cik'] not in [issuer, *owner_ciks]:
        raise ValueError('SEC_DOCUMENT_INDEX_IDENTITY_MISMATCH')
    if issuer not in ciks:
        return {name: [] for name in TABLES}, {'status': 'INDEX_MATCHED_OWNER_OUTSIDE_ISSUER_SCOPE', 'issuer_cik': issuer}
    parent = {'ACCESSION_NUMBER': task['accession'], 'FILING_DATE': task['filed_date'],
              'DOCUMENT_TYPE': form, 'ISSUERCIK': root.findtext('issuer/issuerCik')}
    for key, path in {'PERIOD_OF_REPORT': 'periodOfReport', 'DATE_OF_ORIG_SUB': 'dateOfOriginalSubmission',
                      'NOT_SUBJECT_SEC16': 'notSubjectToSection16', 'ISSUERNAME': 'issuer/issuerName',
                      'ISSUERTRADINGSYMBOL': 'issuer/issuerTradingSymbol', 'REMARKS': 'remarks',
                      'AFF10B5ONE': 'aff10b5One'}.items():
        parent[key] = root.findtext(path)
    result = {name: [] for name in TABLES}

    def append(name, row, node, ordinal):
        base = common_row(parent, raw, 'SEC_FULL_TXT_XML', name, ordinal, accepted)
        base['source_xml'] = ET.tostring(node, encoding='unicode')
        base['transaction_date'] = iso_day(row.get('TRANS_DATE'))
        result[name].append({'ACCESSION_NUMBER': task['accession'], **row, **base})

    # The header subtree excludes repeated transactions/owners, all of which have
    # their own table rows. The full original document is always archived.
    header = ET.Element('ownershipDocumentHeader')
    for node in root:
        if node.tag not in ('reportingOwner', 'nonDerivativeTable', 'derivativeTable', 'footnotes', 'ownerSignature'):
            header.append(node)
    append('SUBMISSION', parent, header, 1)
    for ordinal, node in enumerate(root.findall('reportingOwner'), 1):
        fields = {'RPTOWNERCIK': 'reportingOwnerId/rptOwnerCik', 'RPTOWNERNAME': 'reportingOwnerId/rptOwnerName',
                  'RPTOWNER_TITLE': 'reportingOwnerRelationship/officerTitle', 'RPTOWNER_TXT': 'reportingOwnerRelationship/otherText'}
        for suffix, xml in [('STREET1', 'Street1'), ('STREET2', 'Street2'), ('CITY', 'City'),
                            ('STATE', 'State'), ('ZIPCODE', 'ZipCode'), ('STATE_DESC', 'StateDescription')]:
            fields['RPTOWNER_' + suffix] = 'reportingOwnerAddress/rptOwner' + xml
        row = {key: node.findtext(path) for key, path in fields.items()}
        row['RPTOWNER_RELATIONSHIP'] = ','.join(label for tag, label in
            [('isDirector', 'DIRECTOR'), ('isOfficer', 'OFFICER'), ('isTenPercentOwner', 'TENPERCENTOWNER'), ('isOther', 'OTHER')]
            if node.findtext('reportingOwnerRelationship/' + tag, '').lower() in ('1', 'true'))
        append('REPORTINGOWNER', row, node, ordinal)
    for name, path in [('NONDERIV_TRANS', 'nonDerivativeTable/nonDerivativeTransaction'),
                       ('NONDERIV_HOLDING', 'nonDerivativeTable/nonDerivativeHolding'),
                       ('DERIV_TRANS', 'derivativeTable/derivativeTransaction'),
                       ('DERIV_HOLDING', 'derivativeTable/derivativeHolding')]:
        for ordinal, node in enumerate(root.findall(path), 1):
            row = {}  # Do not manufacture SEC quarterly surrogate keys from XML.
            for key, field in FIELDS.items():
                value, refs = element_value(node, field)
                row[key], row[key + '_FN'] = value, refs
            # SEC's derivative transaction TSV spells this field EXCERCISE.
            if name == 'DERIV_TRANS':
                row['EXCERCISE_DATE'] = row.pop('EXERCISE_DATE')
                row['EXCERCISE_DATE_FN'] = row.pop('EXERCISE_DATE_FN')
            _, row['EQUITY_SWAP_TRANS_CD_FN'] = element_value(node, 'transactionCoding')
            append(name, row, node, ordinal)
    for ordinal, node in enumerate(root.findall('footnotes/footnote'), 1):
        append('FOOTNOTES', {'FOOTNOTE_ID': node.attrib.get('id'), 'FOOTNOTE_TXT': ''.join(node.itertext())}, node, ordinal)
    for ordinal, node in enumerate(root.findall('ownerSignature'), 1):
        append('OWNER_SIGNATURE', {'OWNERSIGNATURENAME': node.findtext('signatureName'),
                                   'OWNERSIGNATUREDATE': node.findtext('signatureDate')}, node, ordinal)
    return result, {'status': 'PARSED', 'issuer_cik': issuer, 'accepted_at': accepted.isoformat()}


def schemas_for(bulk):
    names = {table: set() for table in TABLES}
    for item in bulk:
        with zipfile.ZipFile(item['raw']['local_path']) as archive:
            for table in TABLES:
                names[table].update(archive.open(table + '.tsv').readline().decode('utf-8-sig').strip().split('\t'))
    names['SUBMISSION'].add('AFF10B5ONE')
    for table in ('NONDERIV_TRANS', 'NONDERIV_HOLDING', 'DERIV_TRANS', 'DERIV_HOLDING'):
        for key in FIELDS:
            names[table].update((key, key + '_FN'))
        names[table].add('EQUITY_SWAP_TRANS_CD_FN')
        if table == 'DERIV_TRANS':
            names[table].update(('EXCERCISE_DATE', 'EXCERCISE_DATE_FN'))
    return {name: pa.schema([pa.field(key, pa.string()) for key in sorted(columns)] +
                            [pa.field(key, kind) for key, kind in COMMON.items()]) for name, columns in names.items()}


def normalization_contract(root, args):
    contract = {'plan': file_identity(root / 'sec_insider_plan.json'),
            'acquisition': file_identity(acquisition_path(root)),
            'adapter': file_identity(Path(__file__)), 'cik_scope': file_identity(args.ciks_manifest)}
    if getattr(args, 'intraday', False):
        contract['intraday_snapshot'] = file_identity(root / 'sec_intraday_filings_snapshot.json')
    return contract


def existing_normalized(manifest_path, contract, store):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('contract') != contract:
        raise ValueError('EXISTING_NORMALIZATION_CONTRACT_DIFFERS_USE_NEW_RUN')
    for item in manifest['files'].values():
        if file_identity(store._check_data_path(Path(item['path'])))['sha256'] != item['sha256']:
            raise ValueError('NORMALIZED_OUTPUT_CHANGED')
    return manifest


def retain_index_filing(task, raw, seen, aliases):
    """One submission may be indexed under both issuer and reporting-owner CIKs."""
    previous = seen.get(task['accession'])
    identity = (task['form'], task['filed_date'], raw['sha256'])
    if previous is None:
        seen[task['accession']] = (identity, raw['source_reference'])
        return True
    if previous[0] != identity:
        raise ValueError('CONFLICTING_BYTES_OR_DATES_FOR_INDEX_ACCESSION')
    aliases.append({'accession': task['accession'], 'index_cik': task['cik'],
                    'source_url': raw['source_reference'], 'source_sha256': raw['sha256'],
                    'retrieved_at': raw['retrieval_timestamp_utc'], 'canonical_source_url': previous[1]})
    return False


def normalize(paths, args, plan, receipt):
    store = DataStore(paths)
    root = paths.results_root / 'official_research_intake' / args.run_id
    manifest_path = root / 'sec_insider_manifest.json'
    if receipt.get('status') != 'ACQUIRED_COMPLETE':
        raise ValueError('ACQUISITION_INCOMPLETE_NO_PUBLISHABLE_OUTPUT')
    if receipt['plan'] != file_identity(root / 'sec_insider_plan.json'):
        raise ValueError('ACQUISITION_PLAN_HASH_MISMATCH')
    expected = {str(q) for q in pd.period_range(args.start, args.as_of, freq='Q')[:-1]}
    bulk = sorted([item for item in receipt['bulk'] if item['quarter'] in expected], key=lambda item: item['quarter'])
    if {x['quarter'] for x in bulk} != expected or len(bulk) != len(expected):
        raise ValueError('MISSING_OR_DUPLICATE_BULK_QUARTERS')
    old = {x['quarter']: x['raw'] for x in legacy_bulk(args.legacy_manifest)}
    for item in bulk:
        if item['raw']['status'] == 'REUSED_LEGACY_VERIFIED' and item['raw'] != old.get(item['quarter']):
            raise ValueError('LEGACY_LINEAGE_MISMATCH')
        verified_raw(item['raw'], store)
    index = verified_raw(receipt['index'], store)
    day = date.fromisoformat(args.as_of)
    current_start = f'{day.year}-{3 * ((day.month - 1) // 3) + 1:02d}-01'
    tasks, index_summary = master_tasks(index.read_bytes(), plan['ciks'], current_start, args.as_of)
    if tasks != plan['filing_tasks']:
        raise ValueError('INDEX_PLAN_COMPLETENESS_MISMATCH')
    by_url = {item['url']: item for item in receipt['filings']}
    if len(by_url) != len(receipt['filings']) or set(by_url) != {x['url'] for x in tasks}:
        raise ValueError('FILING_ACQUISITION_COMPLETENESS_MISMATCH')
    for task in tasks:
        item = by_url[task['url']]
        if any(item.get(key) != value for key, value in task.items()) or item['raw']['source_reference'] != task['url']:
            raise ValueError('FILING_ACQUISITION_IDENTITY_MISMATCH')
        verified_raw(item['raw'], store)
    intraday = None
    if getattr(args, 'intraday', False):
        intraday = json.loads((root / 'sec_intraday_filings_snapshot.json').read_text(encoding='utf-8'))
        supplement = verify_intraday(intraday, plan['ciks'], args.as_of, store)
        if intraday['status'] == 'ACQUIRED_COMPLETE':
            existing = {task['accession'] for task in tasks}
            for item in supplement:
                if item['accession'] in existing:
                    continue
                task = {key: item[key] for key in ('cik', 'form', 'filed_date', 'filename', 'accession', 'url')}
                if item['raw']['source_reference'] != task['url'] or task['form'] not in ('4', '4/A') or task['filed_date'] != args.as_of:
                    raise ValueError('INTRADAY_FILING_IDENTITY_MISMATCH')
                tasks.append(task)
                by_url[task['url']] = item
                existing.add(task['accession'])
    contract = normalization_contract(root, args)
    if manifest_path.exists():
        return existing_normalized(manifest_path, contract, store)
    version = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:24]
    output = store._check_data_path(paths.data_root / 'reference/official_research/versions' / version, must_exist=False)
    output.mkdir(parents=True, exist_ok=True)
    schemas = schemas_for(bulk)
    temporary = {name: output / ('sec_form4_' + name.lower() + '_current.parquet.tmp') for name in TABLES}
    if any(path.exists() for path in temporary.values()):
        raise ValueError('PRESERVE_INCOMPLETE_NORMALIZATION_OUTPUT')
    writers = {name: pq.ParquetWriter(path, schemas[name], compression='zstd') for name, path in temporary.items()}
    counts, ranges, transactions, acceptances, amendments, issuers, seen = {}, {}, {}, {}, {}, set(), set()
    exclusions, parts, aliases, current_seen = [], [], [], {}

    def append(frames, label):
        records = frames['SUBMISSION']
        keys = {row['accession'] for row in records}
        if len(keys) != len(records) or seen.intersection(keys):
            raise ValueError('DUPLICATE_CROSS_SOURCE_ACCESSION')
        seen.update(keys)
        issuers.update(row['issuer_cik'] for row in records)
        for row in records:
            acceptances[row['acceptance_status']] = acceptances.get(row['acceptance_status'], 0) + 1
            amendments[row['form']] = amendments.get(row['form'], 0) + 1
        for name, rows in frames.items():
            if not rows:
                continue
            unknown = set().union(*(set(row) for row in rows)) - set(schemas[name].names)
            if unknown:
                raise ValueError('UNDECLARED_SOURCE_FIELDS:' + str(sorted(unknown)))
            writers[name].write_table(pa.Table.from_pylist(rows, schema=schemas[name]))
            counts[name] = counts.get(name, 0) + len(rows)
            days = [row['filing_date'] for row in rows]
            lo, hi = ranges.get(name, (min(days), max(days)))
            ranges[name] = (min(lo, min(days)), max(hi, max(days)))
            if name.endswith('_TRANS'):
                for row in rows:
                    key = str(row.get('TRANS_CODE') or 'SOURCE_MISSING')
                    transactions[key] = transactions.get(key, 0) + 1
        parts.append({'source': label, 'rows': {name: len(rows) for name, rows in frames.items()}})

    try:
        for item in bulk:
            frames = normalize_bulk(zip_tables(Path(item['raw']['local_path'])), item['raw'], plan['ciks'], args.start, args.as_of)
            append(frames, item['quarter'])
            print(json.dumps({'normalized_quarter': item['quarter'], 'filings': len(frames['SUBMISSION'])}), flush=True)
        # Batch current filings to avoid thousands of tiny Parquet row groups.
        batch = {name: [] for name in TABLES}
        for number, task in enumerate(tasks, 1):
            raw = by_url[task['url']]['raw']
            frames, audit = normalize_filing(Path(raw['local_path']).read_bytes(), task, raw, plan['ciks'], args.as_of)
            # Validate each indexed CIK against XML before coalescing byte-identical
            # references. Keep all acquisition records and explicit alias lineage.
            keep = retain_index_filing(task, raw, current_seen, aliases)
            if keep and audit['status'] != 'PARSED':
                exclusions.append({'accession': task['accession'], **audit})
            if keep:
                for name, rows in frames.items():
                    batch[name].extend(rows)
            if number % 250 == 0 or number == len(tasks):
                append(batch, 'current_batch_' + str(number))
                batch = {name: [] for name in TABLES}
    finally:
        for writer in writers.values():
            writer.close()
    files = {}
    for name, temporary_path in temporary.items():
        digest = sha256_file(temporary_path)
        target = output / ('sec_form4_' + name.lower() + '_current_' + digest[:20] + '.parquet')
        if target.exists():
            raise ValueError('OUTPUT_PATH_ALREADY_EXISTS')
        temporary_path.replace(target)
        lo, hi = ranges.get(name, (None, None))
        files[name] = {**file_identity(target), 'dataset': 'sec_form4_' + name.lower() + '_current',
                       'rows': counts.get(name, 0), 'date_column': 'filing_date',
                       'min_date': str(lo) if lo else None, 'max_date': str(hi) if hi else None}
    manifest = dict(schema_version=1, status='NORMALIZED_COMPLETE_FOR_DECLARED_INDEX', run_id=args.run_id,
                    start=args.start, as_of=args.as_of, contract=contract, files=files,
                    source_page=SOURCE_PAGE, source_readme=README, index_freshness=index_summary,
                    scope_cik_count=len(plan['ciks']), issuer_ciks_with_filings=len(issuers),
                    filing_count=len(seen), form_counts=amendments, transaction_code_counts=transactions,
                    acceptance_counts=acceptances, bulk_quarters=len(bulk),
                    current_index_filings=index_summary['matched_form4_filings'],
                    current_index_unique_accessions=len({task['accession'] for task in plan['filing_tasks']}),
                    duplicate_index_aliases=aliases,
                    intraday_form4_filings_added=len(tasks) - index_summary['matched_form4_filings'],
                    intraday_snapshot=None if intraday is None else {
                        key: intraday[key] for key in ('status', 'feed_anchor_utc', 'completed_day_start_boundary')},
                    excluded_owner_matches=exclusions, partitions=parts, vintage_policy=VINTAGE,
                    limitations=['2026+ is authorized for acquisition and data-quality checks only; no research or fitting.',
                                 'Issuer CIK scope is the existing current identity scope, not a historical membership universe.',
                                 'Bulk filing dates are not acceptance timestamps; UNKNOWN_IN_BULK remains null.',
                                 '4/A stays a separate filing; no amendment-to-original matching or silent replacement.',
                                 'All numeric values remain source text; missing/footnote-only prices are not zeros.',
                                 'As-of is a date ceiling. The index maximum filing date and capture time state actual freshness.',
                                 'Quarterly data can omit filing metadata; original archived sources remain necessary.'])
    save_json(manifest_path, manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--ciks-manifest', type=Path)
    parser.add_argument('--legacy-manifest', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--intraday', action='store_true', help='After fixed-quarter acquisition, capture one bounded all-form current feed and new scoped Form4 TXT')
    args = parser.parse_args(argv)
    paths = resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.run_id) or not iso_day(args.start) <= iso_day(args.as_of) <= date.today():
        raise ValueError('INVALID_RUN_OR_DATE_SCOPE')
    args.ciks_manifest = args.ciks_manifest or paths.data_root / 'sec/incremental_20260913/incremental_manifest.json'
    args.legacy_manifest = args.legacy_manifest or paths.cache_root / 'a2_form4_insider_purchase_alpha_r1/sec_insider_bulk/manifests/host_download_result.json'
    store = DataStore(paths)
    for path in (args.ciks_manifest, args.legacy_manifest):
        store._check_data_path(path)
    ciks = load_scope(args.ciks_manifest)
    if not args.execute:
        print(json.dumps({'status': 'PLAN_ONLY', 'cik_count': len(ciks), 'start': args.start, 'as_of': args.as_of,
                          'minimum_request_interval_seconds': .51, 'source': SOURCE_PAGE}))
        return
    plan, receipt = acquire(paths, args, ciks)
    if plan['ciks'] != ciks or plan['start'] != args.start or plan['as_of'] != args.as_of:
        raise ValueError('ACQUISITION_SCOPE_MISMATCH')
    if receipt.get('status') != 'ACQUIRED_COMPLETE':
        raise ValueError('ACQUISITION_INCOMPLETE_NO_PUBLISHABLE_OUTPUT')
    if args.intraday:
        intraday_once(paths, args, ciks)
    manifest = normalize(paths, args, plan, receipt)
    print(json.dumps({key: manifest[key] for key in ('status', 'filing_count', 'form_counts', 'index_freshness')}))


if __name__ == '__main__':
    main()
