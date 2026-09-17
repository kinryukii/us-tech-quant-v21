"""Focused source fidelity and fail-closed checks; no model or real results."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.storage import refresh_sec_insider_data as m

ACC = '0000000999-26-000001'
RAW = {'sha256': 'a' * 64, 'source_reference': 'https://www.sec.gov/Archives/edgar/data/123/' + ACC + '.txt',
       'retrieval_timestamp_utc': '2026-09-14T09:00:00Z'}
TASK = {'accession': ACC, 'cik': 123, 'form': '4/A', 'filed_date': '2026-09-11'}
XML = '''<ownershipDocument><documentType>4/A</documentType><periodOfReport>2026-09-09</periodOfReport>
<dateOfOriginalSubmission>2026-09-10</dateOfOriginalSubmission><issuer><issuerCik>0000000123</issuerCik>
<issuerName>Example issuer</issuerName><issuerTradingSymbol>EX</issuerTradingSymbol></issuer>
<aff10b5One>true</aff10b5One><reportingOwner><reportingOwnerId><rptOwnerCik>999</rptOwnerCik>
<rptOwnerName>Example officer</rptOwnerName></reportingOwnerId><reportingOwnerRelationship><isDirector>1</isDirector>
<isOfficer>true</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
<transactionDate><value>2026-09-09</value></transactionDate><transactionCoding><transactionFormType>4</transactionFormType>
<transactionCode>F</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>1.000001</value>
<footnoteId id="F1"/></transactionShares><transactionPricePerShare><footnoteId id="F2"/></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>I</value></directOrIndirectOwnership><natureOfOwnership><value>Trust</value>
</natureOfOwnership></ownershipNature></nonDerivativeTransaction><nonDerivativeHolding><securityTitle><value>Preferred</value>
</securityTitle><postTransactionAmounts><sharesOwnedFollowingTransaction><value>0</value></sharesOwnedFollowingTransaction>
</postTransactionAmounts></nonDerivativeHolding></nonDerivativeTable><derivativeTable><derivativeTransaction>
<securityTitle><value>Option</value></securityTitle><conversionOrExercisePrice><value>0.000000001</value></conversionOrExercisePrice>
<transactionDate><value>2026-09-08</value></transactionDate><transactionCoding><transactionCode>M</transactionCode></transactionCoding>
<exerciseDate><value>2027-01-01</value></exerciseDate></derivativeTransaction><derivativeHolding><securityTitle><value>Option B</value>
</securityTitle></derivativeHolding></derivativeTable><footnotes><footnote id="F1">One &amp; two.</footnote>
<footnote id="F2">Weighted price unknown.</footnote></footnotes><ownerSignature><signatureName>Example officer</signatureName>
<signatureDate>2026-09-11</signatureDate></ownerSignature></ownershipDocument>'''


def full(xml=XML, acceptance='20260911180102'):
    return (f'<SEC-DOCUMENT>\nACCESSION NUMBER: {ACC}\n<ACCEPTANCE-DATETIME>{acceptance}\n'
            '<XML>\n' + xml + '\n</XML>').encode()


def tables():
    result = {name: pd.DataFrame(columns=['ACCESSION_NUMBER']) for name in m.TABLES}
    result['SUBMISSION'] = pd.DataFrame([
        {'ACCESSION_NUMBER': ACC, 'DOCUMENT_TYPE': '4/A', 'ISSUERCIK': '0000000123', 'FILING_DATE': '11-SEP-2026',
         'PERIOD_OF_REPORT': '09-SEP-2026', 'AFF10B5ONE': '1'},
        {'ACCESSION_NUMBER': '0000000999-26-000002', 'DOCUMENT_TYPE': '3', 'ISSUERCIK': '123', 'FILING_DATE': '11-SEP-2026'},
        {'ACCESSION_NUMBER': '0000000999-26-000003', 'DOCUMENT_TYPE': '4', 'ISSUERCIK': '456', 'FILING_DATE': '11-SEP-2026'}])
    result['NONDERIV_TRANS'] = pd.DataFrame([{'ACCESSION_NUMBER': ACC, 'TRANS_CODE': 'J', 'TRANS_DATE': '09-SEP-2026',
                                             'TRANS_SHARES': '1.000001', 'TRANS_PRICEPERSHARE': '', 'TRANS_SHARES_FN': 'F1,F2'}])
    result['FOOTNOTES'] = pd.DataFrame([{'ACCESSION_NUMBER': ACC, 'FOOTNOTE_ID': 'F1', 'FOOTNOTE_TXT': 'A "quoted" price'}])
    return result


def test_all_tables_codes_decimal_text_and_amendment_retained():
    result, audit = m.normalize_filing(full(), TASK, RAW, [123], '2026-09-14')
    assert all(result[name] for name in m.TABLES)
    assert result['SUBMISSION'][0]['DATE_OF_ORIG_SUB'] == '2026-09-10'
    assert result['SUBMISSION'][0]['form'] == '4/A'
    assert result['SUBMISSION'][0]['AFF10B5ONE'] == 'true'
    row = result['NONDERIV_TRANS'][0]
    assert row['TRANS_CODE'] == 'F' and row['TRANS_SHARES'] == '1.000001'
    assert row['TRANS_PRICEPERSHARE'] == '' and row['TRANS_PRICEPERSHARE_FN'] == 'F2'
    assert row['DIRECT_INDIRECT_OWNERSHIP'] == 'I'
    assert row['transaction_date'] == date(2026, 9, 9)
    assert row['accepted_at'] == datetime(2026, 9, 11, 22, 1, 2, tzinfo=timezone.utc)
    assert result['DERIV_TRANS'][0]['CONV_EXERCISE_PRICE'] == '0.000000001'
    assert result['DERIV_TRANS'][0]['EXCERCISE_DATE'] == '2027-01-01'
    assert result['REPORTINGOWNER'][0]['RPTOWNER_RELATIONSHIP'] == 'DIRECTOR,OFFICER'
    assert result['FOOTNOTES'][0]['FOOTNOTE_TXT'] == 'One & two.'
    assert audit['status'] == 'PARSED'


def test_bulk_has_unknown_acceptance_and_does_not_filter_transaction_codes():
    result = m.normalize_bulk(tables(), RAW, [123], '2020-01-01', '2026-09-14')
    assert len(result['SUBMISSION']) == 1
    row = result['NONDERIV_TRANS'][0]
    assert row['accepted_at'] is None and row['acceptance_status'] == 'UNKNOWN_IN_BULK'
    assert row['TRANS_CODE'] == 'J' and row['TRANS_SHARES_FN'] == 'F1,F2'
    assert row['TRANS_SHARES'] == '1.000001' and row['TRANS_PRICEPERSHARE'] == ''


def test_bulk_cutoff_uses_filing_date():
    assert not m.normalize_bulk(tables(), RAW, [123], '2020-01-01', '2026-09-10')['SUBMISSION']


def test_bulk_duplicate_accession_rejected():
    data = tables()
    data['SUBMISSION'] = pd.concat([data['SUBMISSION'], data['SUBMISSION'].iloc[[0]]])
    with pytest.raises(ValueError, match='DUPLICATE_BULK_ACCESSION'):
        m.normalize_bulk(data, RAW, [123], '2020-01-01', '2026-09-14')


@pytest.mark.parametrize('replacement,expected', [
    (('ACCESSION NUMBER: ' + ACC, 'ACCESSION NUMBER: 0000000999-26-999999'), 'SEC_HEADER_IDENTITY'),
    (('<ACCEPTANCE-DATETIME>', '<OTHER>'), 'ACCEPTANCE_MISSING'),
    (('<SEC-DOCUMENT>', '<html>'), 'NOT_SEC_FULL_SUBMISSION'),
    (('<documentType>4/A</documentType>', '<documentType>4</documentType>'), 'INDEX_IDENTITY'),
])
def test_wrong_filing_fails_closed(replacement, expected):
    data = full().replace(replacement[0].encode(), replacement[1].encode())
    with pytest.raises(ValueError, match=expected):
        m.normalize_filing(data, TASK, RAW, [123], '2026-09-14')


def test_acceptance_asof_and_winter_timezone():
    with pytest.raises(ValueError, match='ACCEPTANCE_AFTER_AS_OF'):
        m.normalize_filing(full(acceptance='20260915000100'), TASK, RAW, [123], '2026-09-14')
    result, _ = m.normalize_filing(full(acceptance='20260102120000'), TASK, RAW, [123], '2026-09-14')
    assert result['SUBMISSION'][0]['accepted_at'].hour == 17


def test_owner_scope_is_not_issuer_scope():
    task = {**TASK, 'cik': 999}
    result, audit = m.normalize_filing(full(), task, RAW, [999], '2026-09-14')
    assert not result['SUBMISSION']
    assert audit['status'] == 'INDEX_MATCHED_OWNER_OUTSIDE_ISSUER_SCOPE'


def test_unknown_xml_fields_retained_in_source_subtree():
    xml = XML.replace('<securityTitle><value>Common', '<newOptionalField>exact</newOptionalField><securityTitle><value>Common')
    result, _ = m.normalize_filing(full(xml), TASK, RAW, [123], '2026-09-14')
    assert '<newOptionalField>exact</newOptionalField>' in result['NONDERIV_TRANS'][0]['source_xml']


def test_master_index_dates_scope_and_latest():
    raw = ('CIK|Company Name|Form Type|Date Filed|Filename\n-----\n'
           f'123|Example|4/A|2026-09-11|edgar/data/123/{ACC}.txt\n'
           '999|Other|10-K|2026-09-12|edgar/data/999/0000000999-26-000002.txt\n').encode()
    tasks, stats = m.master_tasks(raw, [123], '2026-07-01', '2026-09-14')
    assert len(tasks) == 1 and tasks[0]['form'] == '4/A'
    assert stats['index_max_filed_date'] == '2026-09-12'
    assert stats['matched_form4_filings'] == 1


def test_master_bad_paths_rejected():
    raw = f'CIK|Company Name|Form Type|Date Filed|Filename\n123|A|4|2026-09-11|../../x.txt'.encode()
    with pytest.raises(ValueError, match='INVALID_MASTER_FILING_PATH'):
        m.master_tasks(raw, [123], '2026-07-01', '2026-09-14')


def test_verified_cache_preserves_timestamp_and_detects_mutation(tmp_path):
    path = tmp_path / 'raw.source'
    path.write_bytes(b'original')
    record = {**RAW, 'local_path': str(path), 'sha256': hashlib.sha256(b'original').hexdigest(), 'status': 'CACHED'}
    path.with_suffix('.json').write_text(json.dumps(record))
    assert m.verified_raw(record) == path
    metadata = deepcopy(record)
    metadata['retrieval_timestamp_utc'] = '2026-09-15T00:00:00Z'
    path.with_suffix('.json').write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='RAW_METADATA_MISMATCH'):
        m.verified_raw(record)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='RAW_IDENTITY_MISMATCH'):
        m.verified_raw(record)


def test_zip_parser_preserves_quotes_and_source_decimal_text(tmp_path):
    path = tmp_path / 'quarter.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, frame in tables().items():
            # SEC fields are tab-delimited, not CSV-quote escaped.
            lines = ['\t'.join(frame.columns)]
            for row in frame.fillna('').astype(str).itertuples(index=False, name=None):
                lines.append('\t'.join(row))
            archive.writestr(name + '.tsv', '\n'.join(lines) + '\n')
    parsed = m.zip_tables(path)
    assert parsed['FOOTNOTES'].iloc[0].FOOTNOTE_TXT == 'A "quoted" price'
    assert parsed['NONDERIV_TRANS'].iloc[0].TRANS_SHARES == '1.000001'


def test_incomplete_receipt_never_creates_normalized_output(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'DataStore', lambda _: None)
    paths = type('Paths', (), {'results_root': tmp_path})()
    args = type('Args', (), {'run_id': 'test'})()
    with pytest.raises(ValueError, match='INCOMPLETE_NO_PUBLISHABLE'):
        m.normalize(paths, args, {}, {'status': 'SOURCE_FAILURE'})


def test_cik_scope_is_unique_positive_integer_metadata(tmp_path):
    path = tmp_path / 'scope.json'
    path.write_text(json.dumps({'contract': {'ciks': [999, 123]}}))
    assert m.load_scope(path) == [123, 999]
    path.write_text(json.dumps({'contract': {'ciks': [123, 123]}}))
    with pytest.raises(ValueError, match='INVALID_EXISTING_CIK_SCOPE'):
        m.load_scope(path)


def test_retrieval_timestamp_preserves_original_submicrosecond_precision():
    result = m.timestamp('2026-08-24T07:31:20.0115984+00:00')
    assert result.nanosecond == 400
    assert m.COMMON['retrieved_at'].unit == 'ns'
    assert pa.array([result], type=m.COMMON['retrieved_at'])[0].as_py().nanosecond == 400


def test_existing_normalized_output_refuses_changed_parser_contract(tmp_path):
    path = tmp_path / 'manifest.json'
    contract = {'adapter': {'sha256': 'old'}, 'plan': {'sha256': 'same'}}
    path.write_text(json.dumps({'contract': contract, 'files': {}}))
    assert m.existing_normalized(path, contract, None)['contract'] == contract
    with pytest.raises(ValueError, match='NORMALIZATION_CONTRACT_DIFFERS'):
        m.existing_normalized(path, {**contract, 'adapter': {'sha256': 'new'}}, None)


def recovery_receipts(tmp_path, error='URLError: [WinError 10060] 连接超时'):
    old = {'status': 'SOURCE_FAILURE', 'plan': {'sha256': 'plan'}, 'run_id': 'test',
           'start': '2020-01-01', 'as_of': '2026-09-14', 'index': {}, 'bulk': [],
           'filings': [{'url': 'cached', 'raw': {**RAW, 'local_path': 'cached.source', 'status': 'DOWNLOADED'}},
                       {'url': 'retry', 'raw': {'status': 'FAILED', 'error': error, 'failure_class': 'NETWORK'}}]}
    original = tmp_path / 'sec_insider_acquisition.json'
    original.write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
    recovered = {**deepcopy(old), 'status': 'ACQUIRED_COMPLETE',
                 'previous_acquisition': m.file_identity(original),
                 'recovery_reason': 'TRANSPORT_TIMEOUT_WITH_NO_HTTP_RESPONSE'}
    recovered['filings'][0]['raw']['status'] = 'CACHED'
    recovered['filings'][1]['raw'] = {**RAW, 'status': 'DOWNLOADED'}
    destination = tmp_path / 'sec_insider_acquisition_completed.json'
    destination.write_text(json.dumps(recovered), encoding='utf-8')
    return original, destination, recovered


def test_transport_recovery_reads_utf8_preserves_raw_vintage_and_receipt_chain(tmp_path):
    original, completed, document = recovery_receipts(tmp_path)
    assert m.acquisition_path(tmp_path) == completed
    original.write_text(original.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='PREVIOUS_ACQUISITION_MISMATCH'):
        m.acquisition_path(tmp_path)


def test_transport_recovery_rejects_http_refusal(tmp_path):
    recovery_receipts(tmp_path, 'HTTPError: HTTP Error 403: Forbidden')
    with pytest.raises(ValueError, match='REFUSES_HTTP_OR_NON_TIMEOUT'):
        m.acquisition_path(tmp_path)


def test_transport_recovery_rejects_changed_old_vintage(tmp_path):
    _, completed, document = recovery_receipts(tmp_path)
    document['filings'][0]['raw']['retrieval_timestamp_utc'] = '2026-09-15T00:00:00Z'
    completed.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='CHANGED_EXISTING_VINTAGE'):
        m.acquisition_path(tmp_path)


def test_identical_submission_indexed_for_issuer_and_owner_has_one_filing_and_both_sources():
    seen, aliases = {}, []
    assert m.retain_index_filing(TASK, RAW, seen, aliases)
    owner_task = {**TASK, 'cik': 999}
    owner_raw = {**RAW, 'source_reference': RAW['source_reference'].replace('/123/', '/999/'),
                 'retrieval_timestamp_utc': '2026-09-14T09:01:00Z'}
    # Both master-index identities must still be independently validated against XML.
    rows, _ = m.normalize_filing(full(XML), owner_task, owner_raw, [123, 999], '2026-09-14')
    assert rows['SUBMISSION'][0]['issuer_cik'] == 123
    assert not m.retain_index_filing(owner_task, owner_raw, seen, aliases)
    assert len(seen) == len(aliases) == 1
    assert aliases[0]['canonical_source_url'] == RAW['source_reference']
    assert aliases[0]['source_url'] == owner_raw['source_reference']
    assert aliases[0]['retrieved_at'] == owner_raw['retrieval_timestamp_utc']
    with pytest.raises(ValueError, match='INDEX_IDENTITY_MISMATCH'):
        m.normalize_filing(full(XML), {**owner_task, 'cik': 888}, owner_raw, [123], '2026-09-14')


@pytest.mark.parametrize('field', ['sha256', 'filed_date', 'form'])
def test_same_accession_with_conflicting_bytes_or_dates_is_never_coalesced(field):
    seen, aliases = {}, []
    m.retain_index_filing(TASK, RAW, seen, aliases)
    task, raw = dict(TASK), dict(RAW)
    (raw if field == 'sha256' else task)[field] = 'different'
    with pytest.raises(ValueError, match='CONFLICTING_BYTES_OR_DATES'):
        m.retain_index_filing(task, raw, seen, aliases)


def atom(form='4/A', cik=123, accepted='2026-09-14T06:01:00-04:00', filed='2026-09-14'):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"><updated>2026-09-14T06:10:00-04:00</updated>
<entry><title>{form} - Example ({cik:010d}) (Issuer)</title><category term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={ACC}</id><updated>{accepted}</updated>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; {filed} &lt;b&gt;AccNo:&lt;/b&gt; {ACC}</summary>
<link href="https://www.sec.gov/Archives/edgar/data/123/000000099926000001/{ACC}-index.htm"/>
</entry></feed>'''.encode()


def test_current_feed_preserves_exact_form_and_explicit_timezone():
    anchor, rows = m.current_entries(atom(form='425'))
    assert anchor == pd.Timestamp('2026-09-14T10:10:00Z')
    assert rows[0]['form'] == '425'  # Must not be silently accepted as Form 4.
    assert rows[0]['feed_accepted_at'] == '2026-09-14T10:01:00+00:00'
    assert rows[0]['url'].endswith(ACC + '.txt')


def test_current_feed_missing_identity_rejected():
    with pytest.raises(ValueError, match='ATOM_ENTRY_IDENTITY'):
        m.current_entries(atom().replace(b'(0000000123)', b'(not a CIK)'))


def test_intraday_replay_rejects_missing_filing_and_later_than_anchor(tmp_path):
    path = tmp_path / 'page.source'
    path.write_bytes(atom())
    page = {**RAW, 'source_reference': 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&start=0&count=100&output=atom',
            'local_path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'status': 'CACHED'}
    path.with_suffix('.json').write_text(json.dumps(page))
    anchor, entries = m.current_entries(path.read_bytes())
    document = {'as_of': '2026-09-14', 'scope_ciks': [123], 'pages': [page], 'feed_anchor_utc': anchor.isoformat(),
                'entries': entries, 'status': 'ACQUIRED_COMPLETE', 'failures': [],
                'completed_day_start_boundary': True, 'form4_filings': []}
    with pytest.raises(ValueError, match='INTRADAY_FILING_COMPLETENESS'):
        m.verify_intraday(document, [123], '2026-09-14', None)
    document['entries'] = []
    with pytest.raises(ValueError, match='INTRADAY_ENTRY_COMPLETENESS'):
        m.verify_intraday(document, [123], '2026-09-14', None)
    path.write_bytes(atom(accepted='2026-09-14T06:11:00-04:00'))
    page['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.json').write_text(json.dumps(page))
    assert m.verify_intraday(document, [123], '2026-09-14', None) == []


def test_existing_datastore_reads_typed_filing_date_without_changing_source_numbers(tmp_path):
    from scripts.common.storage_paths import StoragePaths
    from scripts.storage.build_data_catalog import register_file
    from scripts.storage.storage_r2a import CATALOG_SCHEMA_SQL, CATALOG_SCHEMA_VERSION, CATALOG_ROLE, DataStore
    paths = StoragePaths(**{key: tmp_path / key for key in
        ['repo_root', 'data_root', 'cache_root', 'daily_root', 'backtest_root', 'results_root', 'envs_root']})
    for root in vars(paths).values():
        root.mkdir(parents=True)
    rows = m.normalize_bulk(tables(), RAW, [123], '2020-01-01', '2026-09-14')['NONDERIV_TRANS']
    schema = pa.schema([pa.field(key, pa.string()) for key in sorted(set(rows[0]) - set(m.COMMON))] +
                       [pa.field(key, kind) for key, kind in m.COMMON.items()])
    path = paths.data_root / 'transactions.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    catalog = paths.cache_root / 'catalog.sqlite3'
    with sqlite3.connect(catalog) as conn:
        conn.executescript(CATALOG_SCHEMA_SQL)
        conn.executemany('INSERT INTO catalog_metadata(key,value) VALUES (?,?)',
                         [('schema_version', str(CATALOG_SCHEMA_VERSION)), ('catalog_role', CATALOG_ROLE)])
        register_file(conn, 'sec_form4_nonderiv_trans_current', '', '', path, 1, '2026-09-11', '2026-09-11',
                      'SEC_OFFICIAL', {'date_column': 'filing_date'})
    store = DataStore(paths, catalog)
    assert store.read('sec_form4_nonderiv_trans_current', end_date='2025-12-31', date_column='filing_date').empty
    result = store.read('sec_form4_nonderiv_trans_current', start_date='2026-09-01', end_date='2026-09-14', date_column='filing_date')
    assert result.TRANS_SHARES.tolist() == ['1.000001']
