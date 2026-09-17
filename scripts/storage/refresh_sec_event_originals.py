"""Acquire fixed SEC earnings and beneficial-ownership originals; no signal inference."""
from __future__ import annotations

import argparse
import binascii
import hashlib
import io
import json
import re
import shutil
import sqlite3
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict
from pathlib import Path

from scripts.common.storage_paths import resolve
from scripts.storage.refresh_official_research_data import archive_module, save_json, VINTAGE
from scripts.storage.refresh_13f_quarter import configured_user_agent, import_source
from scripts.storage.restore_sec_data import sha256_file, file_identity
from scripts.storage.refresh_sec_disclosures import index_candidates
from scripts.storage.storage_r2a import DataStore
from scripts.storage.refresh_sec_insider_data import verify_intraday, sec_capture
from scripts.storage import refresh_sec_insider_data as intraday_source


def discover(plan_path, scope_path, bulk, database, master, as_of, earnings_start, ownership_start):
    """Reuse only raw disclosure metadata and the already approved CIK identity scope."""
    ciks = json.loads(scope_path.read_text(encoding='utf-8'))['contract']['ciks']
    rows = {}; missing = []
    def consume(obj, cik, source):
        recent = obj.get('filings', {}).get('recent', obj)
        for i, accession in enumerate(recent.get('accessionNumber', [])):
            def value(key):
                values = recent.get(key, []); return values[i] if i < len(values) else ''
            filed = value('filingDate'); form = value('form')
            earnings = form in ('8-K','8-K/A') and earnings_start <= filed <= as_of
            ownership = bool(re.fullmatch(r'(?:SC|SCHEDULE) 13[DG](?:/A)?',form)) and ownership_start <= filed <= as_of
            if earnings or ownership:
                rows[(cik,accession)] = {'cik':cik,'accession':accession,'form':form,
                    'filed_date':filed,'items':value('items'),'accepted_at':value('acceptanceDateTime'),
                    'primary_document':value('primaryDocument'),'estimated_bytes':value('size'),
                    'role':'EARNINGS' if earnings else 'BENEFICIAL_OWNERSHIP',**source}
    with zipfile.ZipFile(bulk) as archive:
        for cik in ciks:
            member = f'CIK{cik:010d}.json'
            try:
                payload = archive.read(member)
            except KeyError:
                missing.append(cik); continue
            obj = json.loads(payload)
            consume(obj,cik,{'discovery_kind':'EXISTING_BULK','discovery_member':member,
                            'discovery_sha256':hashlib.sha256(payload).hexdigest()})
            for item in obj.get('filings',{}).get('files',[]):
                if item['filingTo'] >= min(earnings_start,ownership_start) and item['filingFrom'] <= as_of:
                    payload = archive.read(item['name'])
                    consume(json.loads(payload),cik,{'discovery_kind':'EXISTING_BULK_HISTORY',
                        'discovery_member':item['name'],'discovery_sha256':hashlib.sha256(payload).hexdigest()})
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
        for cik in ciks:
            url = f'https://data.sec.gov/submissions/CIK{cik:010d}.json'
            cached = connection.execute('SELECT body_zlib,sha256,fetched_utc FROM responses WHERE url=? AND status=200',(url,)).fetchone()
            if cached:
                payload = zlib.decompress(cached[0])
                if hashlib.sha256(payload).hexdigest() != cached[1]:
                    raise ValueError('DISCOVERY_API_CACHE_HASH_MISMATCH')
                consume(json.loads(payload),cik,{'discovery_kind':'EXISTING_INCREMENTAL_API',
                    'discovery_url':url,'discovery_sha256':cached[1],'discovery_observed_at':cached[2]})
    index_payload = master.read_bytes()
    dates = re.findall(rb'\|(20\d{2}-\d{2}-\d{2})\|edgar/data/',index_payload)
    if not dates:
        raise ValueError('MASTER_HAS_NO_FILINGS')
    index_end = min(as_of,max(dates).decode())
    quarter_start = f'{index_end[:4]}-{((int(index_end[5:7])-1)//3)*3+1:02d}-01'
    _, indexed, stats = index_candidates(index_payload,ciks,quarter_start,index_end)
    relevant = indexed.loc[indexed.form.isin(['8-K','8-K/A','SCHEDULE 13D','SCHEDULE 13D/A','SCHEDULE 13G','SCHEDULE 13G/A','SC 13D','SC 13D/A','SC 13G','SC 13G/A'])]
    unknown = [{'cik':r.cik,'accession':r.accession,'form':r.form,'filename':r.filename}
               for r in relevant.itertuples(index=False) if (r.cik,r.accession) not in rows]
    if unknown:
        save_json(plan_path.with_name(plan_path.stem+'_discovery_gaps.json'),{'missing_current_metadata':unknown})
        raise ValueError('REFRESH_SUBMISSIONS_METADATA_FOR_INDEXED_CANDIDATES_BEFORE_DISCOVERY')
    selected = [r for r in rows.values() if r['role']=='BENEFICIAL_OWNERSHIP' or '2.02' in str(r['items'])]
    selected.sort(key=lambda r:(r['filed_date'],r['cik'],r['accession']),reverse=True)
    for row in selected:
        row['url'] = f"https://www.sec.gov/Archives/edgar/data/{row['cik']}/{row['accession']}.txt"
    plan = {'as_of':as_of,'earnings_start':earnings_start,'ownership_start':ownership_start,
        'ciks':ciks,'scope':file_identity(scope_path),'bulk':file_identity(bulk),
        'incremental_database':str(database),'master':file_identity(master),'index_stats':stats,
        'missing_bulk_ciks':missing,'rows':selected}
    save_json(plan_path,plan)
    return plan


class FilingText(HTMLParser):
    """Keep table boundaries; exclude executable/style payloads from searchable text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []; self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if not self.hidden and tag in ('p', 'div', 'br', 'tr', 'table', 'li'):
            self.parts.append('\n')
        if not self.hidden and tag in ('td', 'th'):
            self.parts.append('\t')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ('p', 'div', 'tr', 'table', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def source_field(payload, field):
    match = re.search(rb'^<' + field.encode('ascii') + rb'>[^\S\r\n]*([^\r\n]*)', payload, re.M | re.I)
    return match[1].strip().decode('utf-8', errors='strict') if match else ''


def canonical_form(value):
    value = re.sub(r'\s+', ' ', value.strip().upper())
    return re.sub(r'^(?:SC|SCHEDULE)\s*(13[DG])', r'SCHEDULE \1', value)


def decode_pdf(content):
    body = content.strip()
    if body.upper().startswith(b'<PDF>') and body.upper().endswith(b'</PDF>'):
        body = body[5:-6].strip()
    if body.startswith(b'begin '):
        lines = body.splitlines()
        if lines[-1].strip() != b'end':
            raise ValueError('INCOMPLETE_UUENCODED_ATTACHMENT')
        chunks = []
        for line in lines[1:-1]:
            if not line:
                continue
            if any(c < 32 or c > 96 for c in line):
                raise ValueError('INVALID_UUENCODED_CHARACTER')
            size = (line[0] - 32) & 63
            required = (size * 4 + 5) // 3
            if size > 45 or len(line) > 1 + 4 * ((size + 2) // 3):
                raise ValueError('INVALID_UUENCODED_LINE_LENGTH')
            # SEC archives can strip trailing spaces (zero sextets); CPython's
            # decoder restores these according to the leading byte count.
            try:
                chunk = binascii.a2b_uu(line)
            except binascii.Error:
                # CPython 3.12 uu.decode's compatibility rule for broken
                # encoders: ignore only unused trailing characters in the
                # final 4-character group; the declared byte count is binding.
                chunk = binascii.a2b_uu(line[:required])
            if len(chunk) != size:
                raise ValueError('UUENCODED_BYTE_COUNT_MISMATCH')
            chunks.append(chunk)
        body = b''.join(chunks)
    if not body.startswith(b'%PDF-'):
        raise ValueError('ATTACHMENT_IS_NOT_PDF')
    return body


def load_pdf_package(path):
    if path is None:
        return None, None
    path = Path(path).resolve()
    if path.name != 'pypdf' or not (path/'__init__.py').is_file():
        raise ValueError('EXPECTED_INSTALLED_PYPDF_PACKAGE')
    module = import_source(path/'__init__.py','pypdf')
    tree = [{'path':str(p.relative_to(path)),'sha256':sha256_file(p)} for p in sorted(path.rglob('*.py'))]
    identity = {'path':str(path),'version':module.__version__,
                'source_tree_sha256':hashlib.sha256(json.dumps(tree,sort_keys=True).encode()).hexdigest()}
    return module.PdfReader, identity


def validate_raw_receipt(paths, row, raw):
    path = DataStore(paths)._check_data_path(Path(raw['local_path']))
    if not path.is_relative_to(paths.cache_root) or raw['source_reference'] != row['url']:
        raise ValueError('RAW_PATH_OR_SOURCE_URL_MISMATCH')
    sidecar = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    for key in ('source_reference','sha256','retrieval_timestamp_utc'):
        if sidecar.get(key) != raw.get(key):
            raise ValueError('RAW_SIDECAR_IDENTITY_MISMATCH')
    if sidecar['byte_count'] != path.stat().st_size:
        raise ValueError('RAW_BYTE_COUNT_MISMATCH')
    stamp = datetime.fromisoformat(raw['retrieval_timestamp_utc'].replace('Z','+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('RAW_OBSERVATION_TIME_WITHOUT_TIMEZONE')
    return path


def parse_original(payload, row, raw, pdf_reader=None):
    digest = hashlib.sha256(payload).hexdigest()
    if digest != raw['sha256']:
        raise ValueError('ORIGINAL_HASH_MISMATCH')
    header = payload.split(b'<DOCUMENT>', 1)[0]
    accession = re.search(rb'ACCESSION NUMBER:\s*(\d{10}-\d{2}-\d{6})', header)
    if not accession or accession[1].decode() != row['accession']:
        raise ValueError('ORIGINAL_ACCESSION_MISMATCH')
    source_ciks = {int(x) for x in re.findall(rb'CENTRAL INDEX KEY:\s*(\d+)', header)}
    if row['cik'] not in source_ciks:
        raise ValueError('ORIGINAL_CIK_MISMATCH')
    source_form = re.search(rb'CONFORMED SUBMISSION TYPE:[ \t]*([^\r\n]+)', header)
    if source_form and canonical_form(source_form[1].decode('ascii')) != canonical_form(row['form']):
        raise ValueError('ORIGINAL_FORM_MISMATCH')
    source_filed = re.search(rb'FILED AS OF DATE:\s*(\d{8})', header)
    if source_filed and source_filed[1].decode() != row['filed_date'].replace('-', ''):
        raise ValueError('ORIGINAL_FILED_DATE_MISMATCH')
    accepted_raw = source_field(header, 'ACCEPTANCE-DATETIME')
    if not re.fullmatch(r'\d{14}', accepted_raw):
        raise ValueError('ORIGINAL_ACCEPTANCE_MISSING')
    local = datetime.strptime(accepted_raw, '%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('America/New_York'))
    accepted_utc = local.astimezone(ZoneInfo('UTC')).isoformat().replace('+00:00', 'Z')
    metadata = {key: row.get(key, '') for key in ('cik', 'accession', 'form', 'filed_date', 'items', 'role')}
    metadata.update({'accepted_at_utc': accepted_utc, 'accepted_source_raw': accepted_raw,
        'discovery_accepted_at': row.get('accepted_at', ''), 'source_url': raw.get('source_reference', row['url']),
        'source_sha256': digest, 'source_path': raw['local_path'],
        'observed_at_utc': raw['retrieval_timestamp_utc'], 'available_at_utc': None,
        'cik_role':'DISCOVERY_CIK_NOT_ASSUMED_ISSUER' if row['role']=='BENEFICIAL_OWNERSHIP' else 'REGISTRANT_OR_COREGISTRANT',
        'historical_pit_certified': False, 'vintage_semantics': VINTAGE})
    documents = []; types = []; replacements = 0
    for ordinal, match in enumerate(re.finditer(rb'<DOCUMENT>\s*(.*?)</DOCUMENT>', payload, re.S | re.I), 1):
        part = match[1]; doc_type = source_field(part, 'TYPE'); filename = source_field(part, 'FILENAME')
        types.append(doc_type)
        filename_match = filename == str(row.get('primary_document','')).rsplit('/',1)[-1]
        type_match = canonical_form(doc_type) == canonical_form(row['form'])
        if filename_match and not type_match:
            raise ValueError('ORIGINAL_PRIMARY_DOCUMENT_TYPE_MISMATCH')
        primary = filename_match if row.get('primary_document') else type_match
        chosen = type_match or (row['role'] == 'EARNINGS' and bool(re.match(r'EX-99(?:\.|$)', doc_type)))
        if not chosen:
            continue
        text = re.search(rb'<TEXT>(.*?)</TEXT>', part, re.S | re.I)
        if text is None:
            raise ValueError('ORIGINAL_DOCUMENT_TEXT_MISSING')
        content = text[1]
        decoded_hash = None; replacement_count = 0; extraction_error = None
        is_pdf = filename.lower().endswith('.pdf') or content.strip().upper().startswith(b'<PDF>') or content.strip().startswith(b'%PDF-')
        if is_pdf:
            binary = decode_pdf(content); decoded_hash = hashlib.sha256(binary).hexdigest()
            plain = ''; extraction = 'PDF_ARCHIVED_REQUIRES_TEXT_EXTRACTOR'
            if pdf_reader is not None:
                if len(binary) > 64 * 1024**2:
                    extraction = 'PDF_ARCHIVED_EXCEEDS_64_MIB_TEXT_EXTRACTION_LIMIT'
                else:
                    try:
                        reader = pdf_reader(io.BytesIO(binary), strict=False)
                        # Layout mode drops rotated text. Plain mode preserves all
                        # four supported orientations; table structure stays unverified.
                        plain = '\n\f\n'.join(page.extract_text(orientations=(0,90,180,270)) or '' for page in reader.pages)
                        extraction = 'PDF_TEXT_ALL_ORIENTATIONS_UNREVIEWED' if plain.strip() else 'PDF_NO_EXTRACTABLE_TEXT'
                    except Exception as exc:
                        extraction = 'PDF_TEXT_EXTRACTION_FAILED'; extraction_error = f'{type(exc).__name__}: {exc}'[:300]
        elif content.strip().startswith(b'begin '):
            plain = ''; extraction = 'BINARY_ATTACHMENT_ARCHIVED'
        else:
            decoded = content.decode('utf-8', errors='replace'); replacement_count = decoded.count('\ufffd')
            if re.search(r'<(?:html|xml|div|p|table|\?xml)\b', decoded, re.I):
                extractor = FilingText(); extractor.feed(decoded); decoded = ''.join(extractor.parts)
            lines = [re.sub(r'[ \r\f\v]+', ' ', x).strip(' ') for x in decoded.split('\n')]
            plain = '\n'.join(x for x in lines if x.strip()).strip()
            extraction = 'HTML_TEXT_TABLE_BOUNDARIES_V1'
        replacements += replacement_count
        start = match.start(1) + text.start(1); end = match.start(1) + text.end(1)
        documents.append({**metadata, 'document_ordinal': ordinal, 'document_type': doc_type,
            'document_filename': filename, 'is_primary': primary, 'content_start_byte':start,
            'content_end_byte':end, 'content_sha256':hashlib.sha256(content).hexdigest(),
            'text':plain, 'guidance_term_candidate': bool(re.search(r'\b(?:guidance|outlook|forecast)\b', plain, re.I)),
            'text_extraction_version':extraction, 'text_extraction_error':extraction_error,
            'decoded_content_sha256':decoded_hash, 'utf8_replacement_count':replacement_count})
    if not documents or not any(d['is_primary'] for d in documents):
        raise ValueError('ORIGINAL_HAS_NO_MATCHING_PRIMARY_OR_EXHIBIT')
    metadata.update({'source_document_count':len(types), 'selected_document_count':len(documents),
        'exhibit_99_count':sum(d['document_type'].startswith('EX-99') for d in documents),
        'source_document_types_json':json.dumps(types), 'utf8_replacement_count':replacements})
    return metadata, documents


def ownership_xml_fields(payload, document):
    content = payload[document['content_start_byte']:document['content_end_byte']].strip()
    if content.upper().startswith(b'<XML>') and content.upper().endswith(b'</XML>'):
        content = content[5:-6].strip()
    content = content.removeprefix(b'\xef\xbb\xbf').lstrip()
    appears_xml = bool(re.search(rb'<(?:[A-Za-z_][\w.-]*:)?edgarSubmission\b',content[:2048])) or content.startswith(b'<?xml')
    if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        if appears_xml:
            raise ValueError('OWNERSHIP_XML_ENTITY_DECLARATION')
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        if appears_xml:
            raise ValueError('MALFORMED_OWNERSHIP_XML')
        return []
    if root.tag.rsplit('}', 1)[-1] != 'edgarSubmission':
        return []
    base = {key:document[key] for key in ('cik','accession','form','filed_date','accepted_at_utc',
        'source_url','source_sha256','source_path','observed_at_utc','available_at_utc',
        'document_ordinal','document_filename','content_sha256')}
    result = []
    def walk(element, path):
        if not len(element):
            result.append({**base,'xml_leaf_ordinal':len(result)+1,
                'xml_path':'/'+ '/'.join(f"{tag.rsplit('}',1)[-1]}[{i}]" for tag,i in path),
                'qualified_path_json':json.dumps(path,ensure_ascii=False), 'xml_tag':element.tag,
                'field_name':element.tag.rsplit('}',1)[-1], 'raw_text':element.text,
                'attributes_json':json.dumps(element.attrib,sort_keys=True,ensure_ascii=False)})
        counts = {}
        for child in element:
            counts[child.tag] = counts.get(child.tag,0)+1
            walk(child,path+[(child.tag,counts[child.tag])])
    walk(root,[(root.tag,1)])
    return result


def intraday_candidates(paths, plan, snapshot_path):
    snapshot_path = DataStore(paths)._check_data_path(Path(snapshot_path))
    if not snapshot_path.is_relative_to(paths.results_root):
        raise ValueError('INTRADAY_SNAPSHOT_OUTSIDE_RESULTS')
    document = json.loads(snapshot_path.read_text(encoding='utf-8'))
    verify_intraday(document, plan['ciks'], plan['as_of'], DataStore(paths))
    if document['status'] != 'ACQUIRED_COMPLETE':
        return document, [], []
    existing = {(row['cik'], row['accession']) for row in plan['rows']}
    candidates, skipped = [], []
    for entry in document['entries']:
        role = ('EARNINGS' if entry['form'] in ('8-K', '8-K/A') else
                'BENEFICIAL_OWNERSHIP' if re.fullmatch(r'(?:SC|SCHEDULE) 13[DG](?:/A)?', entry['form']) else None)
        reason = 'FORM_OUTSIDE_EVENT_SCOPE' if role is None else 'ALREADY_IN_FIXED_PLAN' if (entry['cik'],entry['accession']) in existing else None
        if reason:
            skipped.append({'cik':entry['cik'], 'accession':entry['accession'], 'form':entry['form'], 'reason':reason})
            continue
        candidates.append({key:entry[key] for key in ('cik','accession','form','filed_date','url')} | {
            'role':role, 'items':'', 'primary_document':'', 'accepted_at':entry['feed_accepted_at'],
            'discovery_kind':'SEC_FROZEN_CURRENT_FEED', 'discovery_snapshot_sha256':sha256_file(snapshot_path)})
    return document, candidates, skipped


def classify_intraday_original(payload, row, raw, cutoff):
    metadata, _ = parse_original(payload, row, raw)
    header = payload.split(b'<DOCUMENT>',1)[0]
    items = [x.decode('utf-8',errors='strict').strip() for x in re.findall(rb'^ITEM INFORMATION:[ \t]*([^\r\n]*)',header,re.M|re.I)]
    if datetime.fromisoformat(metadata['accepted_at_utc'].replace('Z','+00:00')) > datetime.fromisoformat(cutoff):
        return 'EXCLUDED_AFTER_SNAPSHOT_CUTOFF', None, items
    if row['role'] == 'EARNINGS':
        if not any(re.sub(r'\s+',' ',item).casefold() == 'results of operations and financial condition' for item in items):
            return 'EXCLUDED_NO_HEADER_ITEM_2_02', None, items
        row = {**row, 'items':'2.02'}
    return 'ELIGIBLE', row, items


def intraday_events(paths, plan_path, run_id, snapshot_path, *, execute=False, return_receipt=False):
    """Acquire once or verify per-candidate receipts; never alter the fixed event plan."""
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    validate_plan(plan, paths)
    document, candidates, skipped = intraday_candidates(paths, plan, snapshot_path)
    root = paths.results_root/'official_research_intake'/run_id/'sec_event_originals'
    result_path = root/'intraday_result.json'
    contract = {'plan':file_identity(plan_path), 'snapshot':file_identity(Path(snapshot_path)),
                'verifier_code':file_identity(Path(intraday_source.__file__))}
    parent_identity = file_identity(result_path) if result_path.exists() else None
    previous = json.loads(result_path.read_text(encoding='utf-8')) if parent_identity else None
    revalidate = previous is not None and previous['contract'] != contract
    if revalidate:
        old_contract = previous['contract']
        if (set(old_contract) != set(contract) or
            {k:v for k,v in old_contract.items() if k != 'verifier_code'} !=
            {k:v for k,v in contract.items() if k != 'verifier_code'}):
            raise ValueError('INTRADAY_EVENT_CONTRACT_MISMATCH')
        if previous['status'] != 'COMPLETE_FIXED_SNAPSHOT':
            raise ValueError('INTRADAY_EVENT_INCOMPLETE_CANNOT_REVALIDATE')
    if not execute and previous is None:
        raise ValueError('INTRADAY_EVENTS_NOT_ACQUIRED')
    stopped = threading.Event()
    capture = sec_capture(paths, stopped) if execute and previous is None else None
    decisions = []; candidate_receipts = []
    for row in candidates:
        receipt_path = root/'intraday/acquisition'/f"{row['cik']}_{row['accession']}.json"
        receipt_identity = file_identity(receipt_path) if receipt_path.exists() else None
        if receipt_identity:
            item = json.loads(receipt_path.read_text(encoding='utf-8'))
            if item['candidate'] != row:
                raise ValueError('INTRADAY_EVENT_CANDIDATE_MISMATCH')
        elif not execute or previous:
            raise ValueError('INTRADAY_EVENT_RECEIPT_MISSING')
        elif stopped.is_set():
            item = {'candidate':row, 'status':'NOT_ATTEMPTED_AFTER_HOST_STOP', 'raw':None}
        else:
            if shutil.disk_usage(paths.cache_root).free < 20*1024**3:
                raise ValueError('INTRADAY_EVENT_STORAGE_BUDGET')
            raw = asdict(capture.acquire_url(row['url'], 'SEC_EVENT_INTRADAY', 'SEC', 'COMPLETE_SUBMISSION_TXT',
                paths.cache_root/'official_research_intake'/run_id/'raw', 180, 0, 0))
            item = {'candidate':row, 'raw':raw}
            if raw['status'] == 'FAILED':
                item['status'] = 'SOURCE_FAILURE'
            else:
                try:
                    payload = validate_raw_receipt(paths,row,raw).read_bytes()
                    status, selected, items = classify_intraday_original(payload,row,raw,document['feed_anchor_utc'])
                    item.update(status=status,row=selected,source_sec_header_items=items)
                except Exception as exc:
                    item.update(status='SOURCE_PARSE_FAILURE',error=f'{type(exc).__name__}: {exc}'[:300])
        if item['raw'] and item['raw']['status'] != 'FAILED':
            payload = validate_raw_receipt(paths,row,item['raw']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item['raw']['sha256']:
                raise ValueError('INTRADAY_EVENT_RAW_HASH_MISMATCH')
            try:
                status, selected, items = classify_intraday_original(payload,row,item['raw'],document['feed_anchor_utc'])
            except Exception as exc:
                if item['status'] != 'SOURCE_PARSE_FAILURE' or item.get('error') != f'{type(exc).__name__}: {exc}'[:300]:
                    raise ValueError('INTRADAY_EVENT_PARSE_FAILURE_MISMATCH') from exc
            else:
                if (item['status'],item.get('row'),item.get('source_sec_header_items')) != (status,selected,items):
                    raise ValueError('INTRADAY_EVENT_DECISION_MISMATCH')
        if item['raw'] and re.search(r'HTTP Error (?:401|403|429)\b|NON200:(?:401|403|429)\b', item['raw'].get('error') or ''):
            stopped.set()
        if not receipt_path.exists():
            save_json(receipt_path,item)
        current_receipt = file_identity(receipt_path)
        if receipt_identity and current_receipt != receipt_identity:
            raise ValueError('INTRADAY_EVENT_RECEIPT_CHANGED_DURING_VERIFY')
        candidate_receipts.append(current_receipt)
        decisions.append(item)
    counts = {status:sum(x['status']==status for x in decisions) for status in sorted({x['status'] for x in decisions})}
    complete = document['status']=='ACQUIRED_COMPLETE' and all(x['status']=='ELIGIBLE' or x['status'].startswith('EXCLUDED_') for x in decisions)
    result = {'contract':contract,'status':'COMPLETE_FIXED_SNAPSHOT' if complete else 'INTRADAY_UNAVAILABLE_OR_INCOMPLETE',
        'snapshot_status':document['status'],'feed_anchor_utc':document['feed_anchor_utc'],
        'completed_day_start_boundary':document['completed_day_start_boundary'],
        'scope_ciks':len(plan['ciks']),'scoped_snapshot_entries':len(document['entries']),
        'event_form_candidates':len(candidates),'skipped':skipped,'decisions':decisions,'decision_counts':counts,
        'eligible_filings':counts.get('ELIGIBLE',0),
        'zero_eligible_proven_for_fixed_snapshot':complete and counts.get('ELIGIBLE',0)==0,
        'item_2_02_evidence':'SEC-HEADER ITEM INFORMATION equals Results of Operations and Financial Condition; body mentions alone excluded.',
        'historical_pit_certified':False,'coverage_semantics':'Only the frozen official snapshot cutoff; no claim of a completed future calendar day.'}
    if previous is not None:
        expected = {**previous, 'contract':contract} if revalidate else previous
        if result != expected:
            raise ValueError('INTRADAY_EVENT_RESULT_MISMATCH')
        if file_identity(result_path) != parent_identity:
            raise ValueError('INTRADAY_EVENT_PARENT_CHANGED_DURING_VERIFY')
    if previous is None:
        save_json(result_path,result)
    effective_path = result_path
    if revalidate:
        record = {'status':'REVALIDATED_COMPLETE_FIXED_SNAPSHOT', 'parent_receipt':parent_identity,
                  'previous_verifier_code':previous['contract']['verifier_code'],
                  'current_verifier_code':contract['verifier_code'],
                  'event_verifier_code':file_identity(Path(__file__)),
                  'candidate_receipts':candidate_receipts, 'result':result,
                  'semantics':'Same archived snapshot and identical original decisions; no acquisition or status upgrade.'}
        version = hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
        effective_path = root/'intraday/revalidations'/f'{version}.json'
        if effective_path.exists():
            if json.loads(effective_path.read_text(encoding='utf-8')) != record:
                raise ValueError('INTRADAY_EVENT_REVALIDATION_CHANGED')
        else:
            save_json(effective_path,record)
    return (result,effective_path) if return_receipt else result


def normalize(paths, plan_path, run_id, pdf_package=None, intraday_snapshot=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    root = paths.results_root/'official_research_intake'/run_id/'sec_event_originals'
    acquisition = acquisition_path(root, plan_path)
    pdf_reader, pdf_identity = load_pdf_package(pdf_package)
    extra, extra_path = intraday_events(paths,plan_path,run_id,intraday_snapshot,return_receipt=True) if intraday_snapshot else (None,None)
    extra_identity = file_identity(extra_path) if extra else None
    manifest_path = root/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        expected = {'plan':file_identity(plan_path),
                    'acquisition_result':file_identity(acquisition),
                    'normalizer_code':file_identity(Path(__file__)), 'pdf_extractor':pdf_identity,
                    'intraday_result':extra_identity}
        if any(manifest.get(key) != value for key,value in expected.items()):
            raise ValueError('EXISTING_EVENT_MANIFEST_CONTRACT_MISMATCH')
        for output in manifest['outputs']:
            if sha256_file(DataStore(paths)._check_data_path(Path(output['path']))) != output['sha256']:
                raise ValueError('NORMALIZED_OUTPUT_CHANGED')
        return manifest
    result = json.loads(acquisition.read_text(encoding='utf-8'))
    if result['status'] not in ('COMPLETE', 'INCOMPLETE'):
        raise ValueError('EVENT_ACQUISITION_STATE_INVALID')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    validate_plan(plan, paths)
    output_root = paths.cache_root/'official_research_intake'/run_id/'sec_event_normalize'/sha256_file(Path(__file__))[:16]
    final_root = paths.data_root/'reference/official_research/versions'/run_id/'sec_event_originals'
    output_root.mkdir(parents=True, exist_ok=True)
    final_root.mkdir(parents=True, exist_ok=True)
    writers = {}; buffers = {}; counts = {}; schemas = {}; dates = {}; output_files = {}
    def append(dataset, row):
        if dataset not in buffers:
            buffers[dataset] = []; counts[dataset] = 0; dates[dataset] = []
        buffers[dataset].append(row); counts[dataset] += 1; dates[dataset].append(row['filed_date'])
        if len(buffers[dataset]) >= 50:
            flush(dataset)
    def flush(dataset):
        values = buffers[dataset]
        if not values:
            return
        table = pa.Table.from_pylist(values, schema=schemas.get(dataset))
        if dataset not in writers:
            schema = table.schema
            # Unknown historical availability must remain nullable strings across batches.
            schema = pa.schema([pa.field(f.name, pa.string() if pa.types.is_null(f.type) else f.type) for f in schema])
            schemas[dataset] = schema; table = pa.Table.from_pylist(values, schema=schema)
            path = output_root/f'{dataset}.parquet'
            if path.exists():
                raise ValueError('UNMANIFESTED_OUTPUT_EXISTS:' + str(path))
            output_files[dataset] = path
            writers[dataset] = pq.ParquetWriter(path, schema, compression='zstd')
        writers[dataset].write_table(table); buffers[dataset] = []
    unavailable = []
    sources = [(row,None) for row in plan['rows']]
    if extra:
        sources.extend((item['row'],item) for item in extra['decisions'] if item['status']=='ELIGIBLE')
    try:
        for i, (row, item) in enumerate(sources, 1):
            if item is None:
                receipt = root/'acquisition'/f"{row['cik']}_{row['accession']}.json"
                if not receipt.exists():
                    unavailable.append({key:row[key] for key in ('cik','accession','role','url','filed_date')})
                    continue
                item = json.loads(receipt.read_text(encoding='utf-8'))
            if item['row'] != row:
                raise ValueError('NORMALIZATION_PLAN_RECEIPT_MISMATCH')
            payload = validate_raw_receipt(paths,row,item['raw']).read_bytes()
            metadata, documents = parse_original(payload, row, item['raw'],pdf_reader)
            append('sec_event_filings', metadata)
            dataset = 'sec_earnings_documents' if row['role'] == 'EARNINGS' else 'sec_beneficial_ownership_documents'
            for doc in documents:
                append(dataset, doc)
                if row['role'] == 'BENEFICIAL_OWNERSHIP' and doc['is_primary']:
                    for leaf in ownership_xml_fields(payload,doc):
                        append('sec_beneficial_ownership_fields',leaf)
            if i % 500 == 0:
                print(json.dumps({'normalized_filings':i, 'total':len(plan['rows'])}),flush=True)
        for key in buffers:
            flush(key)
    finally:
        for writer in writers.values():
            writer.close()
    outputs = []
    if len(plan['rows']) - len(unavailable) != result['acquired']:
        raise ValueError('ACQUISITION_NORMALIZATION_COUNT_MISMATCH')
    for dataset, path in output_files.items():
        if pq.ParquetFile(path).metadata.num_rows != counts[dataset]:
            raise ValueError('NORMALIZED_COUNT_MISMATCH')
        target = final_root/path.name
        if target.exists():
            if sha256_file(target) != sha256_file(path):
                raise ValueError('IMMUTABLE_FINAL_OUTPUT_CONFLICT')
        else:
            path.rename(target)
        path = target
        outputs.append({'dataset':dataset, **file_identity(path), 'row_count':counts[dataset],
            'min_date':min(dates[dataset]), 'max_date':max(dates[dataset]), 'date_column':'filed_date'})
    manifest = {'role':'SEC_EVENT_ORIGINALS_INTAKE', 'status':'VALIDATED_WITH_SOURCE_GAPS' if unavailable or (extra and extra['status']!='COMPLETE_FIXED_SNAPSHOT') else 'VALIDATED_DATA_ONLY',
        'as_of':plan['as_of'], 'plan':file_identity(plan_path), 'outputs':outputs,
        'earnings_start':plan['earnings_start'], 'ownership_start':plan['ownership_start'],
        'latest_index_filed_date':plan['index_stats']['index_max_filed_date'],
        'scope_ciks':len(plan['ciks']), 'filings':len(sources)-len(unavailable), 'unavailable':unavailable,
        'intraday_result':extra_identity, 'intraday_cutoff_utc':extra['feed_anchor_utc'] if extra else None,
        'intraday_added_filings':extra['eligible_filings'] if extra else 0,
        'acquisition_result':file_identity(acquisition), 'normalizer_code':file_identity(Path(__file__)), 'vintage_semantics':VINTAGE,
        'pdf_extractor':pdf_identity,
        'historical_pit_certified':False, 'automatic_factor_promotion':False,
        'guidance_term_semantics':'UNREVIEWED_LEXICAL_CANDIDATE_NOT_NORMALIZED_GUIDANCE',
        'coverage_limit':'SEC_ITEM_2_02_EARNINGS_ONLY_NOT_ALL_IR_OR_STANDALONE_GUIDANCE; OWNERSHIP_CURRENT_QUARTER',
        'research_usage':'2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST'}
    save_json(manifest_path, manifest)
    return manifest


def validate_plan(plan, paths):
    if not plan['rows'] or len(plan['rows']) > 20000:
        raise ValueError('EMPTY_OR_OVERSIZED_EVENT_PLAN')
    for key in ('scope', 'bulk', 'master'):
        item = plan[key]
        if sha256_file(Path(item['path'])) != item['sha256']:
            raise ValueError('DISCOVERY_SOURCE_CHANGED:' + key)
    ciks = set(plan['ciks']); seen = set()
    for row in plan['rows']:
        key = (row['cik'], row['accession'])
        if key in seen or row['cik'] not in ciks or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', row['accession']):
            raise ValueError('EVENT_IDENTITY_CONFLICT')
        seen.add(key)
        if row['role'] == 'EARNINGS':
            valid = row['form'] in ('8-K', '8-K/A') and '2.02' in str(row['items'])
            start = plan['earnings_start']
        elif row['role'] == 'BENEFICIAL_OWNERSHIP':
            valid = bool(re.fullmatch(r'(?:SC|SCHEDULE) 13[DG](?:/A)?', row['form']))
            start = plan['ownership_start']
        else:
            valid = False; start = ''
        if not valid or not start <= row['filed_date'] <= plan['as_of']:
            raise ValueError('EVENT_OUTSIDE_DECLARED_SCOPE')
        if row['url'] != f"https://www.sec.gov/Archives/edgar/data/{row['cik']}/{row['accession']}.txt":
            raise ValueError('UNEXPECTED_SEC_ORIGINAL_URL')


def transport_timeout(item):
    """Compatibility name for the explicitly bounded transient-recovery set."""
    raw = item.get('raw', {})
    error = raw.get('error', '')
    if raw.get('failure_class') == 'NETWORK':
        if error.startswith('HTTPError: HTTP Error 503:'):
            return True
        return ('HTTPError' not in error
                and bool(re.search(r'10060|timed out|TimeoutError', error, re.I)))
    # FAST6 classifies http.client.IncompleteRead as UNSUPPORTED. This is an
    # interrupted response body, not a format failure; it has no complete raw.
    return (raw.get('failure_class') == 'UNSUPPORTED' and
            bool(re.fullmatch(r'IncompleteRead: IncompleteRead\(\d+ bytes read(?:, \d+ more expected)?\)', error)))


def remaining_network_timeout(item):
    raw = item.get('raw', {})
    error = raw.get('error', '')
    return (raw.get('failure_class') == 'NETWORK' and 'HTTPError' not in error
            and bool(re.search(r'10060|timed out|TimeoutError', error, re.I)))


def verify_recovery_chain_step(root, plan_path, original, recovered, eligible):
    old = json.loads(original.read_text(encoding='utf-8'))
    new = json.loads(recovered.read_text(encoding='utf-8'))
    if eligible is remaining_network_timeout and (old.get('status') != 'INCOMPLETE' or
            new.get('recovery_reason') != 'EXPLICIT_REVIEW_FINAL_SINGLE_SERIAL_NETWORK_TIMEOUT_RETRY' or
            new.get('recovery_workers') != 1):
        raise ValueError('FOLLOWUP_SCOPE_OR_EXECUTION_CHANGED')
    expected = sorted((x['row']['cik'],x['row']['accession']) for x in old['failures'] if eligible(x))
    if (new.get('previous_acquisition') != file_identity(original) or
            new.get('plan') != file_identity(plan_path) or
            new.get('recovery_candidates') != [list(x) for x in expected] or
            new.get('successful_receipts_before') != new.get('preserved_receipts_after')):
        raise ValueError('RECOVERY_CONTRACT_OR_EXISTING_VINTAGE_MISMATCH')
    for item in new['successful_receipts_before']:
        path = Path(item['path']).resolve()
        if path.parent != (root/'acquisition').resolve() or file_identity(path) != item:
            raise ValueError('RECOVERY_PRIOR_RECEIPT_CHANGED_AFTER_COMPLETION')
    return recovered


def acquisition_path(root, plan_path):
    original = root/'acquisition_result.json'
    recovered = root/'acquisition_recovery_result.json'
    followup = root/'acquisition_followup_result.json'
    if not recovered.exists():
        if followup.exists() or (root/'acquisition_followup_started.json').exists():
            raise ValueError('FOLLOWUP_REQUIRES_COMPLETED_FIRST_RECOVERY')
        if (root/'acquisition_recovery_started.json').exists():
            raise ValueError('RECOVERY_INCOMPLETE_REQUIRES_ATTEMPT_REVIEW')
        return original
    verify_recovery_chain_step(root,plan_path,original,recovered,transport_timeout)
    if not followup.exists():
        if (root/'acquisition_followup_started.json').exists():
            raise ValueError('FOLLOWUP_INCOMPLETE_REQUIRES_ATTEMPT_REVIEW')
        return recovered
    return verify_recovery_chain_step(root,plan_path,recovered,followup,remaining_network_timeout)


def acquire(paths, plan_path, run_id, recover_transport=False, recover_remaining_timeouts=False):
    if recover_transport and recover_remaining_timeouts:
        raise ValueError('RECOVERY_MODES_ARE_MUTUALLY_EXCLUSIVE')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    validate_plan(plan, paths)
    root = paths.results_root/'official_research_intake'/run_id/'sec_event_originals'
    destination = root/'acquisition_result.json'
    previous = None; recovery = {}; selected = plan['rows']; count = 0; failures = []
    if recover_transport or recover_remaining_timeouts:
        kind = 'followup' if recover_remaining_timeouts else 'recovery'
        if (root/f'acquisition_{kind}_result.json').exists():
            return json.loads(acquisition_path(root,plan_path).read_text(encoding='utf-8'))
        eligible = remaining_network_timeout if recover_remaining_timeouts else transport_timeout
        if recover_remaining_timeouts:
            destination = root/'acquisition_recovery_result.json'
            if not destination.exists() or acquisition_path(root,plan_path) != destination:
                raise ValueError('FOLLOWUP_REQUIRES_COMPLETED_FIRST_RECOVERY')
        previous = json.loads(destination.read_text(encoding='utf-8'))
        if recover_remaining_timeouts and previous.get('status') != 'INCOMPLETE':
            raise ValueError('FOLLOWUP_REQUIRES_INCOMPLETE_FIRST_RECOVERY')
        if any(re.search(r'HTTPError: HTTP Error (403|429)\b',x.get('raw',{}).get('error','')) for x in previous['failures']):
            raise ValueError('RECOVERY_REFUSES_HOST_ACCESS_DENIAL')
        candidates = [x['row'] for x in previous['failures'] if eligible(x)]
        expected_rows = {(x['cik'],x['accession']):x for x in plan['rows']}
        if not candidates or any(expected_rows.get((x['cik'],x['accession'])) != x for x in candidates):
            raise ValueError('RECOVERY_NO_VALID_TRANSPORT_CANDIDATES')
        existing = [file_identity(p) for p in sorted((root/'acquisition').glob('*.json'))]
        if len(existing) != previous['acquired']:
            raise ValueError('RECOVERY_INITIAL_RECEIPT_COUNT_MISMATCH')
        recovery = {'previous_acquisition':file_identity(destination),'plan':file_identity(plan_path),
                    'recovery_candidates':sorted([x['cik'],x['accession']] for x in candidates),
                    'successful_receipts_before':existing}
        if recover_remaining_timeouts:
            recovery.update(recovery_reason='EXPLICIT_REVIEW_FINAL_SINGLE_SERIAL_NETWORK_TIMEOUT_RETRY',recovery_workers=1)
        marker = root/f'acquisition_{kind}_started.json'
        if marker.exists():
            raise ValueError('RECOVERY_ALREADY_ATTEMPTED_NO_AUTOMATIC_REPEAT')
        save_json(marker,recovery)
        selected = candidates; count = previous['acquired']
        failures = [x for x in previous['failures'] if not eligible(x)]
        destination = root/f'acquisition_{kind}_result.json'
    elif destination.exists():
        return json.loads(acquisition_path(root,plan_path).read_text(encoding='utf-8'))
    raw_root = paths.cache_root/'official_research_intake'/run_id/'raw'
    capture = archive_module(paths.repo_root)
    user_agent = configured_user_agent(paths.repo_root/'scripts/v22/stage_sec_pit_taxonomy.py')
    lock = threading.Lock(); stop = threading.Event(); next_request = [0.0]; byte_count = [0]
    def limited_get(url, timeout):
        with lock:
            delay = next_request[0] - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            next_request[0] = time.monotonic() + .36
        if stop.is_set():
            raise RuntimeError('SEC_EVENT_HOST_STOPPED')
        if shutil.disk_usage(paths.cache_root).free < 20 * 1024**3 or byte_count[0] > 40 * 1024**3:
            stop.set(); raise RuntimeError('EVENT_STORAGE_BUDGET_EXCEEDED')
        request = urllib.request.Request(url, headers={'User-Agent': user_agent})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get('Content-Length')
            if length and int(length) > 256 * 1024**2:
                raise ValueError('EVENT_SINGLE_DOCUMENT_EXCEEDS_256_MIB')
            payload = response.read(256 * 1024**2 + 1)
            if len(payload) > 256 * 1024**2:
                raise ValueError('EVENT_SINGLE_DOCUMENT_EXCEEDS_256_MIB')
            if length and int(length) != len(payload):
                raise ValueError('EVENT_INCOMPLETE_HTTP_BODY')
            with lock:
                byte_count[0] += len(payload)
            return payload
    capture._download_once = limited_get
    save_json(root/'contract.json', {'plan': file_identity(plan_path), 'as_of': plan['as_of'],
        'candidate_count': len(plan['rows']), 'vintage_semantics': VINTAGE,
        'historical_pit_certified': False, 'automatic_factor_promotion': False,
        'research_usage': '2026_PLUS_OBSERVATION_ONLY_NO_TRAINING_TUNING_OR_BACKTEST'})
    def fetch(row):
        receipt = root/'acquisition'/f"{row['cik']}_{row['accession']}.json"
        if receipt.exists():
            item = json.loads(receipt.read_text(encoding='utf-8'))
            if item['row'] != row or sha256_file(Path(item['raw']['local_path'])) != item['raw']['sha256']:
                raise ValueError('EVENT_RAW_REUSE_MISMATCH')
            return True, None
        if stop.is_set():
            return False, {'accession': row['accession'], 'status': 'NOT_ATTEMPTED_AFTER_HOST_STOP'}
        doc = capture.acquire_url(row['url'], 'sec_event_originals', 'SEC', 'COMPLETE_SUBMISSION_TXT', raw_root, 180, 0, 0)
        item = {'row': row, 'raw': asdict(doc)}
        if doc.status == 'FAILED':
            if re.search(r'\bHTTP Error (?:403|429)\b', str(doc.error)) or 'STORAGE_BUDGET' in str(doc.error):
                stop.set()
            return False, item
        save_json(receipt, item)
        return True, None
    iterator = iter(selected)
    workers = 1 if recover_remaining_timeouts else 8
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active = {pool.submit(fetch, row) for row in [next(iterator, None) for _ in range(workers)] if row}
        while active:
            done, active = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                okay, failure = future.result()
                count += int(okay)
                if failure:
                    failures.append(failure)
                if not stop.is_set():
                    row = next(iterator, None)
                    if row:
                        active.add(pool.submit(fetch, row))
            if count and count % 100 == 0:
                print(json.dumps({'acquired': count, 'total': len(plan['rows']), 'downloaded_bytes': byte_count[0], 'failed':len(failures)}), flush=True)
    result = {'acquired': count, 'planned': len(plan['rows']), 'failures': failures,
              'status': 'COMPLETE' if count == len(plan['rows']) and not failures else 'INCOMPLETE',
              'downloaded_bytes_current_process': byte_count[0]}
    if previous is not None:
        recovery['preserved_receipts_after'] = [file_identity(Path(x['path'])) for x in recovery['successful_receipts_before']]
        if recovery['successful_receipts_before'] != recovery['preserved_receipts_after']:
            raise ValueError('RECOVERY_CHANGED_PRIOR_SUCCESSFUL_RECEIPT')
        result.update(recovery)
    save_json(destination, result)
    print(json.dumps({'status':result['status'],'acquired':count,'planned':len(plan['rows']),
                      'failure_count':len(failures),'receipt':str(destination)}), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True); parser.add_argument('--plan', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--recover-transport', action='store_true',help='One bounded retry of transport timeouts, incomplete bodies, or HTTP 503; preserve first result and refuse HTTP denial')
    parser.add_argument('--recover-remaining-timeouts', action='store_true',help='Explicitly reviewed final serial retry of pure network timeouts remaining after the completed first recovery')
    parser.add_argument('--normalize', action='store_true')
    parser.add_argument('--intraday-snapshot',help='Verified frozen SEC all-form snapshot; acquire eligible new events before normalization')
    parser.add_argument('--pdf-package',help='Optional existing pypdf package directory; no dependency install or global path changes')
    parser.add_argument('--build-plan', action='store_true')
    parser.add_argument('--as-of'); parser.add_argument('--earnings-start',default='2024-01-01')
    parser.add_argument('--ownership-start'); parser.add_argument('--master')
    parser.add_argument('--scope-manifest',default='D:/us-tech-quant-data/sec/incremental_20260913/incremental_manifest.json')
    parser.add_argument('--submissions-bulk',default='D:/us-tech-quant-cache/sec_fundamental_pit_r1/bulk/submissions.zip')
    parser.add_argument('--submissions-cache',default='D:/us-tech-quant-data/sec/incremental_20260913/raw_cache/sec_raw_cache.sqlite')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.run_id):
        raise ValueError('INVALID_RUN_ID')
    paths = resolve(); plan = Path(args.plan).resolve()
    if not plan.is_relative_to(paths.results_root):
        raise ValueError('PLAN_OUTSIDE_RESULTS_ROOT')
    if args.build_plan:
        if not args.as_of or not args.ownership_start or not args.master:
            raise ValueError('BUILD_PLAN_REQUIRES_AS_OF_OWNERSHIP_START_AND_MASTER')
        discover(plan,Path(args.scope_manifest),Path(args.submissions_bulk),Path(args.submissions_cache),
                 Path(args.master),args.as_of,args.earnings_start,args.ownership_start)
    if args.recover_transport and args.recover_remaining_timeouts:
        raise ValueError('RECOVERY_MODES_ARE_MUTUALLY_EXCLUSIVE')
    if (args.recover_transport or args.recover_remaining_timeouts) and not args.execute:
        raise ValueError('RECOVERY_REQUIRES_EXECUTE')
    if args.execute:
        result = acquire(paths, plan, args.run_id,args.recover_transport,args.recover_remaining_timeouts)
        if result['status'] != 'COMPLETE':
            return 2
    if args.intraday_snapshot:
        intraday_events(paths,plan,args.run_id,Path(args.intraday_snapshot),execute=True)
        args.normalize = True
    if args.normalize:
        print(json.dumps(normalize(paths, plan, args.run_id,args.pdf_package,args.intraday_snapshot)))
        return 0
    if args.execute:
        return 0
    value = json.loads(plan.read_text(encoding='utf-8'))
    validate_plan(value, paths)
    print(json.dumps({'as_of': value['as_of'], 'candidates':len(value['rows'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
