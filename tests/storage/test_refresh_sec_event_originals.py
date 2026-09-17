import binascii
import hashlib
import json
from dataclasses import dataclass
from types import SimpleNamespace
import pytest
from scripts.storage import refresh_sec_event_originals as events
from scripts.storage.refresh_sec_event_originals import parse_original, ownership_xml_fields, decode_pdf


def example(body=None, accepted='20260911170000'):
    accession='0000320193-26-000123'
    if body is None:
        body=b'<html><style>hide</style><p>Outlook &amp; guidance</p><table><tr><td>Revenue</td><td>$12</td></tr></table><script>hidden()</script></html>'
    payload=(f'<SEC-HEADER>\n<ACCEPTANCE-DATETIME>{accepted}\nACCESSION NUMBER: {accession}\nCENTRAL INDEX KEY: 0000320193\nCONFORMED SUBMISSION TYPE: 8-K\nFILED AS OF DATE: 20260911\n'.encode()+
        b'<DOCUMENT>\n<TYPE>8-K\n<FILENAME>main.htm\n<TEXT><html><p>Main</p></html></TEXT>\n</DOCUMENT>\n'+
        b'<DOCUMENT>\n<TYPE>EX-99.1\n<FILENAME>earnings.htm\n<TEXT>'+body+b'</TEXT>\n</DOCUMENT>')
    row={'cik':320193,'accession':accession,'role':'EARNINGS','form':'8-K','filed_date':'2026-09-11','items':'2.02,9.01','primary_document':'main.htm','accepted_at':'2026-09-11T21:00:00Z','url':'https://www.sec.gov/Archives/edgar/data/320193/'+accession+'.txt'}
    raw={'sha256':hashlib.sha256(payload).hexdigest(),'local_path':'D:/cache/original.txt','retrieval_timestamp_utc':'2026-09-14T00:00:00Z'}
    return payload,row,raw


def test_original_offsets_table_boundaries_and_time():
    payload,row,raw=example()
    filing,docs=parse_original(payload,row,raw)
    assert filing['accepted_at_utc']=='2026-09-11T21:00:00Z'
    assert filing['available_at_utc'] is None
    assert filing['selected_document_count']==2
    assert filing['exhibit_99_count']==1
    exhibit=docs[1]
    original=payload[exhibit['content_start_byte']:exhibit['content_end_byte']]
    assert hashlib.sha256(original).hexdigest()==exhibit['content_sha256']
    assert 'Revenue\t$12' in exhibit['text']
    assert 'Outlook & guidance' in exhibit['text']
    assert 'hide' not in exhibit['text'] and 'hidden' not in exhibit['text']
    assert exhibit['guidance_term_candidate'] is True


def test_winter_acceptance_is_eastern_standard_time():
    p,r,s=example(accepted='20260111170000')
    assert parse_original(p,r,s)[0]['accepted_at_utc']=='2026-01-11T22:00:00Z'


def test_hash_and_accession_conflicts_rejected():
    p,r,s=example()
    with pytest.raises(ValueError,match='HASH'):
        parse_original(p+b'x',r,s)
    with pytest.raises(ValueError,match='ACCESSION'):
        parse_original(p,{**r,'accession':'0000000001-26-000001'},s)


def test_missing_acceptance_rejected():
    p,r,s=example(accepted='')
    with pytest.raises(ValueError,match='ACCEPTANCE'):
        parse_original(p,r,s)


def test_decode_replacement_is_visible_and_raw_is_retained():
    p,r,s=example(body=b'outlook bad byte \xff')
    filing,docs=parse_original(p,r,s)
    assert docs[1]['utf8_replacement_count']==1
    assert filing['source_sha256']==s['sha256']


def test_amendment_and_source_filename_retained():
    p,r,s=example()
    r['form']='8-K/A'
    p=p.replace(b'TYPE: 8-K\n',b'TYPE: 8-K/A\n').replace(b'<TYPE>8-K\n',b'<TYPE>8-K/A\n')
    s['sha256']=hashlib.sha256(p).hexdigest()
    filing,docs=parse_original(p,r,s)
    assert filing['form']=='8-K/A' and docs[0]['is_primary'] is True


def test_initial_filing_cannot_be_relabeled_as_amendment():
    p,r,s=example()
    with pytest.raises(ValueError,match='FORM_MISMATCH'):
        parse_original(p,{**r,'form':'8-K/A'},s)


def test_wrong_cik_or_filed_date_rejected():
    p,r,s=example()
    with pytest.raises(ValueError,match='CIK_MISMATCH'):
        parse_original(p,{**r,'cik':123},s)
    with pytest.raises(ValueError,match='FILED_DATE_MISMATCH'):
        parse_original(p,{**r,'filed_date':'2026-09-10'},s)


def test_filename_cannot_override_wrong_primary_document_type():
    p,r,s=example()
    p=p.replace(b'<TYPE>8-K\n',b'<TYPE>8-K/A\n')
    s['sha256']=hashlib.sha256(p).hexdigest()
    with pytest.raises(ValueError,match='PRIMARY_DOCUMENT_TYPE_MISMATCH'):
        parse_original(p,r,s)


def test_missing_document_and_text_fail_closed():
    p,r,s=example()
    p=p.replace(b'<TEXT>',b'<MISSING>')
    s['sha256']=hashlib.sha256(p).hexdigest()
    with pytest.raises(ValueError,match='TEXT_MISSING'):
        parse_original(p,r,s)


def test_ownership_xml_keeps_repeated_people_and_exact_numeric_strings():
    p,r,s=example(body=b'<XML>\n<?xml version="1.0"?><edgarSubmission><reportingPersons><person><percentOfClass>05.230000</percentOfClass><shares>9007199254740993</shares></person><person><percentOfClass>0</percentOfClass></person></reportingPersons></edgarSubmission>\n</XML>')
    _,docs=parse_original(p,r,s)
    fields=ownership_xml_fields(p,docs[1])
    assert [r['raw_text'] for r in fields]==['05.230000','9007199254740993','0']
    assert 'person[1]' in fields[0]['xml_path']
    assert 'person[2]' in fields[2]['xml_path']
    assert len({r['xml_path'] for r in fields})==3


def test_xml_external_entities_rejected():
    p,r,s=example(body=b'<?xml version="1.0"?><!DOCTYPE edgarSubmission [<!ENTITY x SYSTEM "file:///secret">]><edgarSubmission>&x;</edgarSubmission>')
    _,docs=parse_original(p,r,s)
    with pytest.raises(ValueError,match='ENTITY_DECLARATION'):
        ownership_xml_fields(p,docs[1])


def test_xml_bom_and_namespace_prefix_are_not_silently_skipped():
    p,r,s=example(body=b'<XML>\xef\xbb\xbf<sec:edgarSubmission xmlns:sec="urn:sec"><sec:shares>0100</sec:shares></sec:edgarSubmission></XML>')
    _,docs=parse_original(p,r,s)
    fields=ownership_xml_fields(p,docs[1])
    assert len(fields)==1 and fields[0]['raw_text']=='0100'
    assert fields[0]['xml_tag']=='{urn:sec}shares'


def test_embedded_uuencoded_pdf_never_enters_html_parser():
    binary=b'%PDF-1.5\nPDF payload with <![[ invalid html'
    uu=b'begin 644 document.pdf\n'+b''.join(binascii.b2a_uu(binary[i:i+45]) for i in range(0,len(binary),45))+b'`\nend'
    body=b'<PDF>\n'+uu+b'\n</PDF>'
    assert decode_pdf(body)==binary
    p,r,s=example(body=body)
    _,docs=parse_original(p,r,s)
    assert docs[1]['text']==''
    assert docs[1]['text_extraction_version']=='PDF_ARCHIVED_REQUIRES_TEXT_EXTRACTOR'
    assert docs[1]['decoded_content_sha256']==hashlib.sha256(binary).hexdigest()


def test_incomplete_uu_attachment_rejected():
    with pytest.raises(ValueError,match='INCOMPLETE'):
        decode_pdf(b'<PDF>begin 644 file.pdf\nabc\n</PDF>')


def test_uu_final_group_nonzero_unused_padding_matches_declared_bytes():
    binary = b'%PDF-1.5\nx'
    encoded = binascii.b2a_uu(binary).rstrip(b'\n')
    assert decode_pdf(b'begin 644 x.pdf\n' + encoded[:-2] + b'$!\n`\nend') == binary


def test_uu_trailing_zero_spaces_restored_and_extraneous_groups_rejected():
    binary = b'%PDF-1.5\n' + bytes(20)
    trimmed = binascii.b2a_uu(binary).rstrip(b'\n ')
    assert decode_pdf(b'begin 644 x.pdf\n' + trimmed + b'\nend') == binary
    encoded = binascii.b2a_uu(b'%PDF-1.5\nx').rstrip(b'\n')
    with pytest.raises(ValueError, match='LINE_LENGTH'):
        decode_pdf(b'begin 644 x.pdf\n' + encoded + b'!!!!\nend')


def recovery_fixture(tmp_path, error, failure_class='NETWORK'):
    _,row,_ = example()
    root=tmp_path/'official_research_intake/run/sec_event_originals'
    (root/'acquisition').mkdir(parents=True)
    plan=tmp_path/'plan.json'
    plan.write_text(json.dumps({'rows':[row],'as_of':'2026-09-14'}),encoding='utf-8')
    failed={'row':row,'raw':{'status':'FAILED','failure_class':failure_class,'error':error}}
    original={'acquired':0,'planned':1,'failures':[failed],'status':'INCOMPLETE'}
    (root/'acquisition_result.json').write_text(json.dumps(original),encoding='utf-8')
    return root,plan,SimpleNamespace(results_root=tmp_path,cache_root=tmp_path,repo_root=tmp_path)


def test_transport_recovery_never_retries_http_denial(tmp_path,monkeypatch):
    root,plan,paths=recovery_fixture(tmp_path,'HTTPError: HTTP Error 403: Forbidden')
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    with pytest.raises(ValueError,match='ACCESS_DENIAL'):
        events.acquire(paths,plan,'run',True)
    assert not (root/'acquisition_recovery_started.json').exists()
    assert not events.transport_timeout({'raw':{'failure_class':'NETWORK','error':'HTTPError: timed out 504'}})


@pytest.mark.parametrize('failure_class,error',[
    ('NETWORK','URLError: <urlopen error [WinError 10060] timed out>'),
    ('NETWORK','HTTPError: HTTP Error 503: Service Unavailable'),
    ('UNSUPPORTED','IncompleteRead: IncompleteRead(138358043 bytes read)'),
])
def test_transport_recovery_is_one_attempt_and_preserves_original(tmp_path,monkeypatch,failure_class,error):
    root,plan,paths=recovery_fixture(tmp_path,error,failure_class)
    old=(root/'acquisition_result.json').read_bytes()
    calls=[]
    @dataclass
    class Failure:
        status:str='FAILED'
        failure_class:str='NETWORK'
        error:str='TimeoutError: timed out'
    capture=SimpleNamespace(acquire_url=lambda *a:(calls.append(a[0]) or Failure()))
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    monkeypatch.setattr(events,'archive_module',lambda *_:capture)
    monkeypatch.setattr(events,'configured_user_agent',lambda *_:'synthetic-test')
    first=events.acquire(paths,plan,'run',True)
    second=events.acquire(paths,plan,'run',True)
    assert len(calls)==1 and first==second and first['status']=='INCOMPLETE'
    assert (root/'acquisition_result.json').read_bytes()==old
    assert events.acquisition_path(root,plan).name=='acquisition_recovery_result.json'
    plan.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='CONTRACT'):
        events.acquisition_path(root,plan)


@pytest.mark.parametrize('failure_class,error,expected',[
    ('NETWORK','HTTPError: HTTP Error 403: Forbidden',False),
    ('NETWORK','HTTPError: HTTP Error 429: Too Many Requests',False),
    ('NOT_FOUND','HTTPError: HTTP Error 404: Not Found',False),
    ('NETWORK','HTTPError: HTTP Error 504: timed out',False),
    ('UNSUPPORTED','ValueError: unsupported file format',False),
    ('UNSUPPORTED','IncompleteRead: IncompleteRead(1024 bytes read, 50 more expected)',True),
    ('UNSUPPORTED','ValueError: text mentions IncompleteRead',False),
])
def test_transient_recovery_requires_exact_known_failure(failure_class,error,expected):
    assert events.transport_timeout({'raw':{'failure_class':failure_class,'error':error}}) is expected


def test_incomplete_body_byte_count_is_not_http_denial(tmp_path,monkeypatch):
    root,plan,paths=recovery_fixture(tmp_path,'TimeoutError: timed out')
    prototype=json.loads(plan.read_text(encoding='utf-8'))['rows'][0]
    rows=[{**prototype,'accession':f'0000320193-26-{i:06d}'} for i in range(9)]
    plan.write_text(json.dumps({'rows':rows,'as_of':'2026-09-14'}),encoding='utf-8')
    original={'acquired':0,'planned':len(rows),'failures':[
        {'row':row,'raw':{'status':'FAILED','failure_class':'NETWORK','error':'TimeoutError: timed out'}} for row in rows],
        'status':'INCOMPLETE'}
    (root/'acquisition_result.json').write_text(json.dumps(original),encoding='utf-8')
    calls=[]
    @dataclass
    class Failure:
        status:str='FAILED'
        failure_class:str='UNSUPPORTED'
        error:str='IncompleteRead: IncompleteRead(123403429 bytes read)'
    capture=SimpleNamespace(acquire_url=lambda *a:(calls.append(a[0]) or Failure()))
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    monkeypatch.setattr(events,'archive_module',lambda *_:capture)
    monkeypatch.setattr(events,'configured_user_agent',lambda *_:'synthetic-test')
    result=events.acquire(paths,plan,'run',True)
    assert len(calls)==9 and len(result['failures'])==9
    assert all(x['raw']['failure_class']=='UNSUPPORTED' for x in result['failures'])


def intraday_fixture(tmp_path, forms=('8-K','SCHEDULE 13G/A'), existing=()):
    from pathlib import Path
    from scripts.common.storage_paths import resolve
    from scripts.storage.refresh_sec_insider_data import current_entries
    paths = resolve(repo_root=tmp_path/'repo', **{key:tmp_path/key for key in ['data_root','cache_root','results_root','daily_root','backtest_root','envs_root']})
    paths.cache_root.mkdir(); paths.results_root.mkdir()
    page_path = paths.cache_root/'page.source'
    pieces = []
    for i, form in enumerate(forms,1):
        accession = f'0000320193-26-{i:06d}'
        pieces.append(f'''<entry><title>{form} - Synthetic (0000320193) (Issuer)</title><category term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={accession}</id><updated>2026-09-14T10:00:00-04:00</updated>
<summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2026-09-14</summary>
<link href="https://www.sec.gov/Archives/edgar/data/320193/{accession.replace('-','')}/{accession}-index.htm"/></entry>''')
    payload = ('<feed xmlns="http://www.w3.org/2005/Atom"><updated>2026-09-14T11:00:00-04:00</updated>'+''.join(pieces)+'</feed>').encode()
    page_path.write_bytes(payload)
    raw = {'local_path':str(page_path),'sha256':hashlib.sha256(payload).hexdigest(),'retrieval_timestamp_utc':'2026-09-14T15:01:00Z','status':'CACHED',
        'source_reference':'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&start=0&count=100&output=atom'}
    page_path.with_suffix('.json').write_text(json.dumps(raw),encoding='utf-8')
    anchor, entries = current_entries(payload)
    document = {'as_of':'2026-09-14','scope_ciks':[320193],'pages':[raw],'feed_anchor_utc':anchor.isoformat(),
        'entries':entries,'status':'ACQUIRED_COMPLETE','failures':[],'completed_day_start_boundary':True,'form4_filings':[]}
    snapshot = paths.results_root/'snapshot.json'; snapshot.write_text(json.dumps(document),encoding='utf-8')
    plan = {'as_of':'2026-09-14','ciks':[320193],'rows':list(existing),'earnings_start':'2024-01-01','ownership_start':'2026-07-01',
        'index_stats':{'index_max_filed_date':'2026-09-11'}}
    plan_path = paths.results_root/'plan.json'; plan_path.write_text(json.dumps(plan),encoding='utf-8')
    return paths,plan_path,snapshot,document


def intraday_payload(row, include_item=True, accepted='20260914100000'):
    item = b'ITEM INFORMATION:\tResults of Operations and Financial Condition\n' if include_item else b'ITEM INFORMATION:\tRegulation FD Disclosure\n'
    body = (b'<html>Results of Operations and Financial Condition</html>' if row['role']=='EARNINGS' else
            b'<XML><edgarSubmission><reportingPersons><person><shares>9007199254740993</shares></person></reportingPersons></edgarSubmission></XML>')
    return (f"<SEC-HEADER>\n<ACCEPTANCE-DATETIME>{accepted}\nACCESSION NUMBER: {row['accession']}\nCENTRAL INDEX KEY: 0000320193\nCONFORMED SUBMISSION TYPE: {row['form']}\nFILED AS OF DATE: 20260914\n".encode()+item+
        f"<DOCUMENT>\n<TYPE>{row['form']}\n<FILENAME>primary.htm\n<TEXT>".encode()+body+b'</TEXT>\n</DOCUMENT>')


def fake_intraday_capture(monkeypatch, paths, plan_path, snapshot, *, include_item=True, denied=False):
    from pathlib import Path
    _, candidates, _ = events.intraday_candidates(paths,json.loads(plan_path.read_text(encoding='utf-8')),snapshot)
    by_url = {row['url']:row for row in candidates}; calls = []
    @dataclass
    class Raw:
        status:str
        source_reference:str
        local_path:str|None=None
        sha256:str|None=None
        retrieval_timestamp_utc:str|None=None
        error:str|None=None
        failure_class:str|None=None
    def acquire(url,*args,**kwargs):
        calls.append(url)
        if denied: return Raw('FAILED',url,error='HTTPError: HTTP Error 403: Forbidden',failure_class='HTTP_ACCESS')
        payload = intraday_payload(by_url[url],include_item)
        path = paths.cache_root/(hashlib.sha256(url.encode()).hexdigest()+'.source'); path.write_bytes(payload)
        raw = Raw('DOWNLOADED',url,str(path),hashlib.sha256(payload).hexdigest(),'2026-09-14T15:02:00Z')
        path.with_suffix('.json').write_text(json.dumps({**raw.__dict__,'byte_count':len(payload)}),encoding='utf-8')
        return raw
    monkeypatch.setattr(events,'sec_capture',lambda *_:SimpleNamespace(acquire_url=acquire))
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    monkeypatch.setattr(events.shutil,'disk_usage',lambda *_:SimpleNamespace(free=30*1024**3))
    return calls


def test_intraday_exact_forms_fixed_plan_and_zero_new_proof(tmp_path,monkeypatch):
    paths,plan,snapshot,doc = intraday_fixture(tmp_path,('425','13F-HR','8-K/A'), [{'cik':320193,'accession':'0000320193-26-000003'}])
    calls = fake_intraday_capture(monkeypatch,paths,plan,snapshot)
    result = events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert result['zero_eligible_proven_for_fixed_snapshot'] and result['eligible_filings']==0 and calls==[]
    assert len(result['skipped'])==3 and result['contract']['snapshot']['sha256']==events.sha256_file(snapshot)
    assert events.intraday_events(paths,plan,'run',snapshot)==result


def test_intraday_header_required_body_mention_is_not_earnings(tmp_path,monkeypatch):
    paths,plan,snapshot,_ = intraday_fixture(tmp_path,('8-K',))
    calls = fake_intraday_capture(monkeypatch,paths,plan,snapshot,include_item=False)
    result = events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert len(calls)==1 and result['zero_eligible_proven_for_fixed_snapshot']
    assert result['decision_counts']=={'EXCLUDED_NO_HEADER_ITEM_2_02':1}
    assert result['decisions'][0]['source_sec_header_items']==['Regulation FD Disclosure']


def test_intraday_original_cutoff_and_header_item_proof():
    row={'cik':320193,'accession':'0000320193-26-000001','form':'8-K/A','filed_date':'2026-09-14','items':'','role':'EARNINGS','primary_document':'','url':'https://www.sec.gov/Archives/example.txt'}
    payload=intraday_payload(row)
    raw={'sha256':hashlib.sha256(payload).hexdigest(),'local_path':'fixture','retrieval_timestamp_utc':'2026-09-14T15:00:00Z'}
    status,selected,items=events.classify_intraday_original(payload,row,raw,'2026-09-14T15:00:00Z')
    assert status=='ELIGIBLE' and selected['items']=='2.02' and selected['form']=='8-K/A'
    assert events.classify_intraday_original(payload,row,raw,'2026-09-14T13:59:59Z')[0]=='EXCLUDED_AFTER_SNAPSHOT_CUTOFF'


def test_intraday_http_denial_stops_host_and_never_retries(tmp_path,monkeypatch):
    paths,plan,snapshot,_=intraday_fixture(tmp_path)
    calls=fake_intraday_capture(monkeypatch,paths,plan,snapshot,denied=True)
    first=events.intraday_events(paths,plan,'run',snapshot,execute=True)
    second=events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert first==second and len(calls)==1 and not first['zero_eligible_proven_for_fixed_snapshot']
    assert first['decision_counts']=={'NOT_ATTEMPTED_AFTER_HOST_STOP':1,'SOURCE_FAILURE':1}


def test_intraday_scope_and_snapshot_tamper_rejected(tmp_path,monkeypatch):
    paths,plan,snapshot,document=intraday_fixture(tmp_path,('8-K',))
    document['scope_ciks']=[1]; snapshot.write_text(json.dumps(document),encoding='utf-8')
    with pytest.raises(ValueError,match='SCOPE_MISMATCH'): events.intraday_candidates(paths,json.loads(plan.read_text()),snapshot)
    document['scope_ciks']=[320193]; document['entries']=[]; snapshot.write_text(json.dumps(document),encoding='utf-8')
    with pytest.raises(ValueError,match='ENTRY_COMPLETENESS'): events.intraday_candidates(paths,json.loads(plan.read_text()),snapshot)


def test_intraday_incomplete_snapshot_cannot_prove_zero_eligible(tmp_path,monkeypatch):
    paths,plan,snapshot,document=intraday_fixture(tmp_path,('8-K',))
    document['status']='INTRADAY_UNAVAILABLE_OR_INCOMPLETE'; document['completed_day_start_boundary']=False
    snapshot.write_text(json.dumps(document),encoding='utf-8')
    calls=fake_intraday_capture(monkeypatch,paths,plan,snapshot)
    result=events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert result['status']=='INTRADAY_UNAVAILABLE_OR_INCOMPLETE' and not result['zero_eligible_proven_for_fixed_snapshot'] and calls==[]


def test_intraday_normalize_uses_existing_four_datasets_without_altering_fixed_plan(tmp_path,monkeypatch):
    from pathlib import Path
    import pyarrow.parquet as pq
    payload,row,_=example()
    paths,plan,snapshot,_=intraday_fixture(tmp_path,('SCHEDULE 13G/A',),[row])
    original_plan=plan.read_bytes()
    calls=fake_intraday_capture(monkeypatch,paths,plan,snapshot)
    extra=events.intraday_events(paths,plan,'run',snapshot,execute=True)
    root=paths.results_root/'official_research_intake/run/sec_event_originals'; (root/'acquisition').mkdir(parents=True)
    raw_path=paths.cache_root/'fixed.source'; raw_path.write_bytes(payload)
    raw={'local_path':str(raw_path),'sha256':hashlib.sha256(payload).hexdigest(),'source_reference':row['url'],'retrieval_timestamp_utc':'2026-09-14T00:00:00Z'}
    raw_path.with_suffix('.json').write_text(json.dumps({**raw,'byte_count':len(payload)}),encoding='utf-8')
    (root/'acquisition'/f"{row['cik']}_{row['accession']}.json").write_text(json.dumps({'row':row,'raw':raw}),encoding='utf-8')
    (root/'acquisition_result.json').write_text(json.dumps({'status':'COMPLETE','acquired':1,'failures':[]}),encoding='utf-8')
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    manifest=events.normalize(paths,plan,'run',intraday_snapshot=snapshot)
    assert manifest['filings']==2 and manifest['intraday_added_filings']==1 and len(manifest['outputs'])==4
    fields=pq.read_table(next(x['path'] for x in manifest['outputs'] if x['dataset']=='sec_beneficial_ownership_fields'))
    assert fields['raw_text'].to_pylist()==['9007199254740993']
    assert plan.read_bytes()==original_plan and len(calls)==1


def test_intraday_verifier_revalidation_preserves_parent_and_normalize_uses_new_receipt(tmp_path,monkeypatch):
    paths,plan,snapshot,_ = intraday_fixture(tmp_path)
    verifier = tmp_path/'verifier.py'; verifier.write_text('version = 1\n')
    monkeypatch.setattr(events,'intraday_source',SimpleNamespace(__file__=str(verifier)))
    calls = fake_intraday_capture(monkeypatch,paths,plan,snapshot)
    original = events.intraday_events(paths,plan,'run',snapshot,execute=True)
    root = paths.results_root/'official_research_intake/run/sec_event_originals'
    parent = root/'intraday_result.json'; original_bytes = parent.read_bytes()
    parent_identity = events.file_identity(parent)
    verifier.write_text('version = 2\n')
    monkeypatch.setattr(events,'sec_capture',lambda *_:pytest.fail('Revalidation must not acquire'))
    replayed,receipt = events.intraday_events(paths,plan,'run',snapshot,execute=True,return_receipt=True)
    record = json.loads(receipt.read_text(encoding='utf-8')); frozen = receipt.read_bytes()
    assert parent.read_bytes()==original_bytes and receipt.parent==root/'intraday/revalidations'
    assert record['status']=='REVALIDATED_COMPLETE_FIXED_SNAPSHOT' and record['parent_receipt']==parent_identity
    assert record['previous_verifier_code']==original['contract']['verifier_code']
    assert record['current_verifier_code']==events.file_identity(verifier)
    assert record['result']==replayed and len(record['candidate_receipts'])==2 and len(calls)==2
    assert replayed=={**original,'contract':replayed['contract']}
    assert events.intraday_events(paths,plan,'run',snapshot,return_receipt=True)==(replayed,receipt)
    assert receipt.read_bytes()==frozen
    (root/'acquisition_result.json').write_text(json.dumps({'status':'COMPLETE','acquired':0,'failures':[]}),encoding='utf-8')
    manifest = events.normalize(paths,plan,'run',intraday_snapshot=snapshot)
    assert manifest['intraday_result']==events.file_identity(receipt)
    assert manifest['filings']==2 and manifest['intraday_added_filings']==2
    assert parent.read_bytes()==original_bytes and len(calls)==2


@pytest.mark.parametrize('changed',['plan','snapshot'])
def test_intraday_revalidation_rejects_other_contract_changes(tmp_path,monkeypatch,changed):
    paths,plan,snapshot,_ = intraday_fixture(tmp_path,('8-K',))
    verifier = tmp_path/'verifier.py'; verifier.write_text('version = 1\n')
    monkeypatch.setattr(events,'intraday_source',SimpleNamespace(__file__=str(verifier)))
    calls = fake_intraday_capture(monkeypatch,paths,plan,snapshot)
    events.intraday_events(paths,plan,'run',snapshot,execute=True)
    target = plan if changed=='plan' else snapshot
    target.write_bytes(target.read_bytes()+b'\n')
    verifier.write_text('version = 2\n')
    with pytest.raises(ValueError,match='INTRADAY_EVENT_CONTRACT_MISMATCH'):
        events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert len(calls)==1


def test_intraday_revalidation_rejects_changed_decisions(tmp_path,monkeypatch):
    paths,plan,snapshot,_ = intraday_fixture(tmp_path,('8-K',))
    verifier = tmp_path/'verifier.py'; verifier.write_text('version = 1\n')
    monkeypatch.setattr(events,'intraday_source',SimpleNamespace(__file__=str(verifier)))
    calls = fake_intraday_capture(monkeypatch,paths,plan,snapshot)
    events.intraday_events(paths,plan,'run',snapshot,execute=True)
    root = paths.results_root/'official_research_intake/run/sec_event_originals'
    original = (root/'intraday_result.json').read_bytes()
    verifier.write_text('version = 2\n')
    classify = events.classify_intraday_original
    def changed(*args):
        _,_,items = classify(*args)
        return 'EXCLUDED_NO_HEADER_ITEM_2_02',None,items
    monkeypatch.setattr(events,'classify_intraday_original',changed)
    with pytest.raises(ValueError,match='INTRADAY_EVENT_DECISION_MISMATCH'):
        events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert (root/'intraday_result.json').read_bytes()==original and len(calls)==1
    assert not (root/'intraday/revalidations').exists()


def test_intraday_revalidation_cannot_upgrade_old_source_failure(tmp_path,monkeypatch):
    paths,plan,snapshot,_ = intraday_fixture(tmp_path,('8-K',))
    verifier = tmp_path/'verifier.py'; verifier.write_text('version = 1\n')
    monkeypatch.setattr(events,'intraday_source',SimpleNamespace(__file__=str(verifier)))
    calls = fake_intraday_capture(monkeypatch,paths,plan,snapshot,denied=True)
    previous = events.intraday_events(paths,plan,'run',snapshot,execute=True)
    root = paths.results_root/'official_research_intake/run/sec_event_originals'
    original = (root/'intraday_result.json').read_bytes()
    assert previous['status']=='INTRADAY_UNAVAILABLE_OR_INCOMPLETE'
    verifier.write_text('version = 2\n')
    monkeypatch.setattr(events,'sec_capture',lambda *_:pytest.fail('Failed snapshot must not retry'))
    with pytest.raises(ValueError,match='INTRADAY_EVENT_INCOMPLETE_CANNOT_REVALIDATE'):
        events.intraday_events(paths,plan,'run',snapshot,execute=True)
    assert (root/'intraday_result.json').read_bytes()==original and len(calls)==1
    assert not (root/'intraday/revalidations').exists()


def followup_fixture(tmp_path,monkeypatch):
    root,plan,paths = recovery_fixture(tmp_path,'TimeoutError: timed out')
    prototype = json.loads(plan.read_text(encoding='utf-8'))['rows'][0]
    entries = []
    for i in range(5):
        accession = f'0000320193-26-{i:06d}'
        entries.append({**prototype,'accession':accession,'url':f'https://www.sec.gov/Archives/edgar/data/320193/{accession}.txt'})
    plan.write_text(json.dumps({'rows':entries,'as_of':'2026-09-14'}),encoding='utf-8')
    preserved = root/'acquisition'/f"320193_{entries[0]['accession']}.json"
    preserved.write_text(json.dumps({'row':entries[0],'raw':{'status':'DOWNLOADED','sha256':'preserved-synthetic-source'}}),encoding='utf-8')
    failed = [{'row':row,'raw':{'status':'FAILED','failure_class':'NETWORK','error':'TimeoutError: timed out'}} for row in entries[1:4]]
    failed.append({'row':entries[4],'raw':{'status':'FAILED','failure_class':'NOT_FOUND','error':'HTTPError: HTTP Error 404: Not Found'}})
    (root/'acquisition_result.json').write_text(json.dumps({'acquired':1,'planned':5,'failures':failed,'status':'INCOMPLETE'}),encoding='utf-8')
    calls = []; max_concurrent = [0]; active = [0]
    import threading
    lock = threading.Lock()
    @dataclass
    class Raw:
        status:str
        source_reference:str
        failure_class:str|None=None
        error:str|None=None
    def acquire(url,*args):
        with lock:
            active[0] += 1; max_concurrent[0] = max(max_concurrent[0],active[0]); calls.append(url)
        import time
        time.sleep(.005)
        with lock:
            active[0] -= 1
        return Raw('DOWNLOADED',url) if (root/'acquisition_recovery_result.json').exists() else Raw('FAILED',url,'NETWORK','TimeoutError: timed out')
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    monkeypatch.setattr(events,'archive_module',lambda *_:SimpleNamespace(acquire_url=acquire))
    monkeypatch.setattr(events,'configured_user_agent',lambda *_:'synthetic-test')
    first = events.acquire(paths,plan,'run',recover_transport=True)
    assert first['acquired']==1 and len(first['failures'])==4 and len(calls)==3
    max_concurrent[0] = 0
    return root,plan,paths,preserved,calls,max_concurrent


def test_final_followup_is_serial_one_attempt_and_default_uses_verified_chain(tmp_path,monkeypatch):
    root,plan,paths,preserved,calls,max_concurrent = followup_fixture(tmp_path,monkeypatch)
    identities = {name:events.file_identity(root/name) for name in ('acquisition_result.json','acquisition_recovery_result.json')}
    preserved_identity = events.file_identity(preserved)
    result = events.acquire(paths,plan,'run',recover_remaining_timeouts=True)
    assert result['acquired']==4 and len(result['failures'])==1 and result['failures'][0]['raw']['failure_class']=='NOT_FOUND'
    assert max_concurrent[0]==1 and result['recovery_workers']==1 and len(calls)==6
    assert result['previous_acquisition']==identities['acquisition_recovery_result.json']
    assert result['successful_receipts_before']==result['preserved_receipts_after']==[preserved_identity]
    assert all(events.file_identity(root/name)==identity for name,identity in identities.items())
    assert (root/'acquisition_followup_started.json').exists()
    assert events.acquisition_path(root,plan).name=='acquisition_followup_result.json'
    for kwargs in ({},{'recover_transport':True},{'recover_remaining_timeouts':True}):
        assert events.acquire(paths,plan,'run',**kwargs)==result
    assert len(calls)==6 and events.file_identity(preserved)==preserved_identity


@pytest.mark.parametrize('failure_class,error,expected',[
    ('NETWORK','URLError: <urlopen error [WinError 10060] timed out>',True),
    ('NETWORK','TimeoutError: timed out',True),
    ('NETWORK','HTTPError: HTTP Error 503: Service Unavailable',False),
    ('NETWORK','HTTPError: HTTP Error 504: timed out',False),
    ('NETWORK','HTTPError: HTTP Error 403: Forbidden',False),
    ('NETWORK','HTTPError: HTTP Error 429: Too Many Requests',False),
    ('NOT_FOUND','HTTPError: HTTP Error 404: Not Found',False),
    ('UNSUPPORTED','IncompleteRead: IncompleteRead(1024 bytes read)',False),
    ('UNSUPPORTED','ValueError: unsupported file format',False),
])
def test_final_followup_only_selects_remaining_pure_network_timeouts(failure_class,error,expected):
    assert events.remaining_network_timeout({'raw':{'failure_class':failure_class,'error':error}}) is expected


def test_final_followup_requires_completed_first_recovery_and_refuses_crashed_attempt(tmp_path,monkeypatch):
    root,plan,paths = recovery_fixture(tmp_path,'TimeoutError: timed out')
    monkeypatch.setattr(events,'validate_plan',lambda *_:None)
    with pytest.raises(ValueError,match='FOLLOWUP_REQUIRES_COMPLETED_FIRST_RECOVERY'):
        events.acquire(paths,plan,'run',recover_remaining_timeouts=True)
    (root/'acquisition_followup_started.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='FOLLOWUP_REQUIRES_COMPLETED_FIRST_RECOVERY'):
        events.acquisition_path(root,plan)
    with pytest.raises(ValueError,match='RECOVERY_MODES_ARE_MUTUALLY_EXCLUSIVE'):
        events.acquire(paths,plan,'run',recover_transport=True,recover_remaining_timeouts=True)


def test_final_followup_marker_blocks_all_automatic_reentry(tmp_path,monkeypatch):
    root,plan,paths,_,calls,_ = followup_fixture(tmp_path,monkeypatch)
    (root/'acquisition_followup_started.json').write_text('{}',encoding='utf-8')
    for kwargs in ({},{'recover_transport':True},{'recover_remaining_timeouts':True}):
        with pytest.raises(ValueError,match='FOLLOWUP_INCOMPLETE_REQUIRES_ATTEMPT_REVIEW'):
            events.acquire(paths,plan,'run',**kwargs)
    assert len(calls)==3


@pytest.mark.parametrize('target',['acquisition_result.json','acquisition_recovery_result.json','preserved_receipt'])
def test_final_followup_verifies_both_parents_and_old_success_receipts(tmp_path,monkeypatch,target):
    root,plan,paths,preserved,_,_ = followup_fixture(tmp_path,monkeypatch)
    events.acquire(paths,plan,'run',recover_remaining_timeouts=True)
    path = preserved if target=='preserved_receipt' else root/target
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='RECOVERY_CONTRACT|RECOVERY_PRIOR_RECEIPT_CHANGED'):
        events.acquisition_path(root,plan)
