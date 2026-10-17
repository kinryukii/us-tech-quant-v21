
def _pre_vendor_source_text(text):
    import ast
    tree=ast.parse(text);names={'_vendor_metadata','_vendor_identity','_vendor_original_components','_vendor_fact_event','_bind_vendor_source_descendant'}
    tree.body=[n for n in tree.body if not (isinstance(n,ast.FunctionDef) and n.name in names)]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name=='bind_source_account_descendant':
            gate=node.body[0];assert isinstance(gate,ast.If) and 'VENDOR_NATIVE_SCHEMA' in ast.unparse(gate.test);node.body.pop(0)
    return ast.unparse(tree)


from pathlib import Path
import copy,json
import pytest
from scripts.research.a2.data import consensus_cash_source_bulk_completion as p

APO="Apollo Global Management, Inc. has declared a cash dividend of $0.43 per share of its Common Stock for the fourth quarter ended December 31, 2023. This dividend will be paid on February 29, 2024 to holders of record at the close of business on February 20, 2024."
LVS="We paid a quarterly dividend of $0.22 per common share during the quarter. We announced our next quarterly dividend of $0.20 per common share will be paid on February 14, 2024, to Las Vegas Sands stockholders of record on February 6, 2024."

def scope(kind):
    apo=kind=='APO';amount='0.43' if apo else '0.20';text=APO if apo else LVS
    e=dict(ticker=kind,issuer_CIK=1858681 if apo else 1300514,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.'+kind,original_current_literal=text,current_amount_literal=amount,record_date='2024-02-20' if apo else '2024-02-06',pay_date='2024-02-29' if apo else '2024-02-14',source_publication_date='2024-02-08' if apo else '2024-01-24',quarter_literal='for the fourth quarter ended December 31, 2023' if apo else 'next quarterly dividend',quarter_period_end_date='2023-12-31',literal_family='DECLARED_NAMED_QUARTER_ENDED_CURRENT_COMMON_CASH' if apo else 'ANNOUNCED_NEXT_QUARTER_WITH_PRIOR_PAID_COMPARISON',original_money_tokens=[amount] if apo else ['0.22',amount],amount_roles=[dict(role='EXPLICIT_CURRENT_COMMON_CASH_FOR_NAMED_QUARTER',literal=amount)] if apo else [dict(role='PREVIOUS_PAID_QUARTER_UNUSED',literal='0.22'),dict(role='CURRENT_NEXT_QUARTER_ANNOUNCED_DIRECT_PER_COMMON_SHARE',literal=amount)],original5field_key=dict(ticker=kind,effective_date='2024-02-16' if apo else '2024-02-05',reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference='SYNTHETIC_ORIGINAL_KEY',source_fingerprint='1'*64))
    return e

def facts(e):return dict(ticker=e['ticker'],sec_filer_cik=e['issuer_CIK'],security_id=e['accounting_sid'],exact_frozen_event_key=e['original5field_key'],cash_per_raw_share=float(e['current_amount_literal']),record_date=e['record_date'],pay_date=e['pay_date'])

@pytest.mark.parametrize('kind',['APO','LVS'])
def test_source_current_quarter_roles_are_original_and_not_other_quarters(monkeypatch,kind):
    e=scope(kind);monkeypatch.setattr(p,'_scope',lambda *a:e);r=p.semantics(e['original_current_literal'],facts(e),e['source_publication_date'])
    assert r['selected_current_amount']==e['current_amount_literal'] and r['amount_roles']==e['amount_roles']
    assert r['original_text_not_rewritten'] and not r['current_from_prior_paid_or_reported_concept']
    assert r['original_factory_ref']==p.ORIGINAL_FACTORY_REF and r['source_role_consumer_ref']==p._ref(p.__file__)
    assert r['quarter_period_end_not_publication'] and r['announced_not_relabelled_declared']

@pytest.mark.parametrize('mutation',['AMOUNT','RECORD','PAY','PUBLICATION','CLASS'])
def test_current_cash_and_fixed_schedule_semantic_negatives(monkeypatch,mutation):
    e=scope('LVS');monkeypatch.setattr(p,'_scope',lambda *a:e);f=facts(e);pub=e['source_publication_date'];listed=None
    if mutation=='AMOUNT':f['cash_per_raw_share']=.22
    elif mutation=='RECORD':f['record_date']='2024-02-07'
    elif mutation=='PAY':f['pay_date']='2024-02-15'
    elif mutation=='PUBLICATION':pub='2023-12-31'
    else:listed='A'
    with pytest.raises(ValueError):p.semantics(e['original_current_literal'],f,pub,listed_common_class=listed)

@pytest.mark.parametrize('change',['PREFERRED','ANNUAL','APPENDED_AMOUNT','WRONG_QUARTER','PRIOR_AS_CURRENT'])
def test_exact_current_source_grammar_and_all_monetary_role_negatives(change):
    e=scope('APO');text=e['original_current_literal']
    if change=='PREFERRED':text=text.replace('Common Stock','Preferred Stock')
    elif change=='ANNUAL':text=text.replace('fourth quarter','annual period')
    elif change=='APPENDED_AMOUNT':text+=' Another dividend of $0.90.'
    elif change=='WRONG_QUARTER':e['quarter_period_end_date']='2024-12-31'
    else:e['amount_roles']=[dict(role='PREVIOUS_PAID_QUARTER_UNUSED',literal='0.43')]
    with pytest.raises(ValueError):p._literal(e,text)


def test_exact_source_book_original_full_fivefield_no_alias_or_issuer_substitution(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'BOOKS',((p.BOOK_REF,'SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1'),))
    e=scope('APO');f=facts(e);book=dict(schema='SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1',RAW_prior_read=False,native_account_fit_2026=False,events=[e]);file=tmp_path/'book.json';file.write_text(json.dumps(book));pin=lambda r:file
    assert {k:v for k,v in p._scope(f,pin).items() if k!='_source_book_ref'}==e
    for change in [('ticker','LVS'),('sec_filer_cik',999),('security_id','NEW_UID')]:
        with pytest.raises(ValueError):p._scope(dict(f,**{change[0]:change[1]}),pin)
    bad=copy.deepcopy(f);bad['exact_frozen_event_key']['source_fingerprint']='2'*64
    with pytest.raises(ValueError):p._scope(bad,pin)


def test_closed_factory_hooks_preserve_real_filenames_and_cash_code_objects():
    old,_=p.original._owner();new,proof=p._owner()
    assert p._ref(p.original.__file__)==p.ORIGINAL_FACTORY_REF
    assert all(proof['archive_SOURCE_AST_optins'][name]==1 for name in ('_original_dated_common_cash_terms','_frozen_common_cash_namespace','bind_source_account_descendant'))
    assert new.bind_source_account_descendant.__globals__['__file__']==old.bind_source_account_descendant.__globals__['__file__']
    assert new.cash.adjudicate_post_verified_cash_ex.__code__.co_code==old.cash.adjudicate_post_verified_cash_ex.__code__.co_code
    assert new.cash.normal_cash_ex_date.__code__ is old.cash.normal_cash_ex_date.__code__
    assert new.cash._guard.__code__ is old.cash._guard.__code__
    assert proof['original_physical_filenames_preserved'] and proof['original_cash_arithmetic_code_unchanged']


def test_old_profile_behavior_remains_canonical():
    new,_=p._owner();text="On January 31, 2024, the Corporation's Board of Directors (the Board) declared a quarterly common stock dividend of $0.24 per share, payable on March 29, 2024 to shareholders of record as of March 1, 2024."
    f=dict(cash_per_raw_share=.24,record_date='2024-03-01',pay_date='2024-03-29')
    got=new.bind_source_account_descendant.__globals__['statement_semantics'](p.original.MONETARY_COMMON,text,f,'2024-02-20')
    assert got==p.original.statement_semantics(p.original.MONETARY_COMMON,text,f,'2024-02-20')



def test_exact_three_compiled_source_whitelist_changes_only():
    old,_=p.original._owner();new,proof=p._owner()
    pairs=[(old._sec_primary_html_cash_terms,new._sec_primary_html_cash_terms,2),(old.cash.adjudicate_post_verified_cash_ex,new.cash.adjudicate_post_verified_cash_ex,1)]
    for a,b,count in pairs:
        assert a.__code__.co_code==b.__code__.co_code and a.__code__.co_names==b.__code__.co_names
        changed=[i for i,(x,y) in enumerate(zip(a.__code__.co_consts,b.__code__.co_consts)) if x!=y]
        assert len(changed)==count and len(a.__code__.co_consts)==len(b.__code__.co_consts)
        for i in changed:assert b.__code__.co_consts[i][:-len(p.NEW_PROFILES)]==a.__code__.co_consts[i] and b.__code__.co_consts[i][-len(p.NEW_PROFILES):]==p.NEW_PROFILES
    assert old._sec_frozen_cash_terms.__code__.co_code==new._sec_frozen_cash_terms.__code__.co_code
    assert old._sec_frozen_cash_terms.__code__.co_names==new._sec_frozen_cash_terms.__code__.co_names
    assert old._sec_frozen_cash_terms.__code__.co_consts==new._sec_frozen_cash_terms.__code__.co_consts
    assert proof['compiled_source_whitelist_old_elements_and_order_preserved']


def test_source_book_lexically_skips_unselected_payload_before_decode(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'BOOKS',((p.BOOK_REF,'SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1'),))
    e=scope('APO');other=dict(original5field_key={'ticker':'OTHER'},unapproved_payload='FORBIDDEN_MARKER'*6000)
    f=tmp_path/'book.json';f.write_text(json.dumps(dict(schema='SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1',RAW_prior_read=False,native_account_fit_2026=False,events=[other,e])))
    loads=p.json.loads;decoded=[]
    def safe_decode(raw,*a,**kw):
        text=raw.decode() if isinstance(raw,bytes) else raw
        assert 'FORBIDDEN_MARKER' not in text
        decoded.append(len(text));return loads(raw,*a,**kw)
    monkeypatch.setattr(p.json,'loads',safe_decode)
    assert {k:v for k,v in p._scope(facts(e),lambda r:f).items() if k!='_source_book_ref'}==e and max(decoded)<65536


@pytest.mark.parametrize('case',['DUPLICATE','SELECTED_TOO_LARGE','UNAPPROVED_NATIVE_BOOK'])
def test_original65k_selected_entry_and_unique_fivefield_fail_closed(tmp_path,case,monkeypatch):
    monkeypatch.setattr(p,'BOOKS',((p.BOOK_REF,'SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1'),))
    e=scope('APO');events=[e,e] if case=='DUPLICATE' else [e]
    if case=='SELECTED_TOO_LARGE':e['extra_source_payload']='x'*65536
    book=dict(schema='SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1',RAW_prior_read=False,native_account_fit_2026=case=='UNAPPROVED_NATIVE_BOOK',events=events);f=tmp_path/'book.json';f.write_text(json.dumps(book))
    with pytest.raises(ValueError):p._scope(facts(e),lambda r:f)


CEG="Dividend Declaration: Our Board of Directors has declared a quarterly dividend of $0.3525 per share on our common stock. The dividend is payable on Tuesday, March 19, 2024, to shareholders of record as of 5 p.m. Eastern time on Friday, March 8, 2024."
ENTG="On October 15, 2025, Entegris, Inc. announced that its board of directors has declared a quarterly cash dividend of $0.10 per share to be paid on November 19, 2025 to shareholders of record on the close of business on October 29, 2025. A copy of this news release is attached hereto as Exhibit 99.1 and is incorporated herein by reference."
DIS="◦ The Board has declared a cash dividend of $1.50 per share, payable in two installments of $0.75 per share, payable on January 15, 2026 (record date December 15, 2025) and July 22, 2026 (record date June 30, 2026)"

def dated_scope(kind):
    vals={'CEG':(CEG,1868275,'0.3525','2024-03-08','2024-03-19','2024-02-27','DECLARED_CURRENT_COMMON_QUARTER_WEEKDAY_SCHEDULE','CURRENT_QUARTER_COMMON_DIRECT_LITERAL'),'ENTG':(ENTG,1101302,'0.10','2025-10-29','2025-11-19','2025-10-15','ANNOUNCED_BOARD_CURRENT_QUARTER_WITH_NONVALUE_COMMON_UNIT','CURRENT_QUARTER_DIRECT_LITERAL_INDEPENDENT_COMMON_UNIT'),'DIS':(DIS,1744489,'0.75','2025-12-15','2026-01-15','2025-11-13','DIRECT_TWO_INSTALLMENT_CURRENT_CASH','DIRECT_FIRST_INSTALLMENT_RECORD_2025DEC15_PAY_2026JAN15')}
    text,cik,amount,record,pay,pub,family,role=vals[kind]
    e=dict(ticker=kind,issuer_CIK=cik,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.'+kind,original_current_literal=text,current_amount_literal=amount,record_date=record,pay_date=pay,source_publication_date=pub,literal_family=family,current_source_explicit_common=kind=='CEG',current_source_explicit_USD=False,quarter_literal='quarterly' if kind!='DIS' else None,original_money_tokens=['1.50','0.75'] if kind=='DIS' else [amount],amount_roles=[dict(role=role,literal=amount)],original5field_key=dict(ticker=kind,effective_date=record,reason='SOURCE_TEST',source_reference='SYNTHETIC',source_fingerprint='1'*64),_source_book_ref=p.GROUP2_BOOK_REF)
    if kind=='DIS':e.update(amount_roles=[dict(role='TOTAL_TWO_INSTALLMENTS_NOT_CURRENT_AMOUNT',literal='1.50'),dict(role=role,literal=amount)],frequency_not_quarterly=True,unused_second_schedule=dict(record_date='2026-06-30',pay_date='2026-07-22',amount_literal=amount,actual2026_read=False))
    return e

@pytest.mark.parametrize('kind',['CEG','ENTG','DIS'])
def test_new_real_source_families_preserve_current_money_frequency_and_original_words(monkeypatch,kind):
    e=dated_scope(kind);monkeypatch.setattr(p,'_scope',lambda *a:e);r=p.semantics(e['original_current_literal'],facts(e),e['source_publication_date'])
    assert r['profile']==p.DATED_CURRENT and r['selected_current_amount']==e['current_amount_literal'] and r['amount_roles']==e['amount_roles']
    assert r['original_text_not_rewritten'] and not r['annual_rate_divided_or_inferred'] and r['current_source_explicit_common']==(kind=='CEG')
    assert r['frequency_not_quarterly']==(kind=='DIS') and r['source_role_book_ref']==p.GROUP2_BOOK_REF

@pytest.mark.parametrize('mutation',['WEEKDAY','ANNUAL_TOTAL','SECOND_AS_CURRENT','SECOND_DATE','CURRENT_COMMON_WORD_INSERTED','LATE_PUBLICATION'])
def test_source_role_family_specific_negatives(mutation):
    e=dated_scope('CEG' if mutation=='WEEKDAY' else 'ENTG' if mutation in ('CURRENT_COMMON_WORD_INSERTED','LATE_PUBLICATION') else 'DIS');text=e['original_current_literal']
    if mutation=='WEEKDAY':text=text.replace('Tuesday','Monday');e['original_current_literal']=text
    elif mutation=='ANNUAL_TOTAL':e['current_amount_literal']='1.50'
    elif mutation=='SECOND_AS_CURRENT':e['record_date']='2026-06-30';e['pay_date']='2026-07-22'
    elif mutation=='SECOND_DATE':e['unused_second_schedule']['record_date']='2026-07-01'
    elif mutation=='CURRENT_COMMON_WORD_INSERTED':text=text.replace('per share','per share of common stock');e['original_current_literal']=text
    else:e['source_publication_date']='2025-10-14'
    with pytest.raises(ValueError):p._dated_literal(e,text)


def test_old_six_semantics_identical_to_frozen6fa_source_snapshot(monkeypatch):
    import importlib.util
    snap=Path(r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\source_custody\consensus_cash_source_bulk_completion_6fa78dcc_group1_r2.py')
    spec=importlib.util.spec_from_file_location('_source131_frozen6fa_test',snap);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    for kind in ('APO','LVS'):
        e=scope(kind);monkeypatch.setattr(p,'_scope',lambda *a:e);monkeypatch.setattr(old,'_scope',lambda *a:e)
        current=p.semantics(e['original_current_literal'],facts(e),e['source_publication_date']);previous=old.semantics(e['original_current_literal'],facts(e),e['source_publication_date'])
        for r in (current,previous):r.pop('source_role_consumer_ref')
        assert current==previous


def test_original_primary_body_transport_keeps_canonical_membership_guard():
    import marshal
    old,_=p.original._owner();new,_=p._owner()
    assert marshal.dumps(old._validate_static_sec_submission.__code__)==marshal.dumps(new._validate_static_sec_submission.__code__)
    assert p.original._base().SEC_STATIC_PRIMARY_BODY_PROFILE=='SEC_STATIC_SUBMISSION_PARENT_COMMON_COVER_AND_PRIMARY_BODY_CASH'
    assert p.original._base().SEC_STATIC_PRIMARY_BODY_SCOPE['cash_document_role']=='ORIGINAL_PRIMARY_SEC_BODY_CURRENT_COMMON_CASH_DECLARATION'


BBWI='COLUMBUS, Ohio, Aug. 09, 2024 (GLOBE NEWSWIRE) -- Bath & Body Works, Inc. (NYSE: BBWI) announced today the declaration of its regular quarterly dividend of $0.20 per share payable on September 6, 2024, to shareholders of record at the close of business on August 23, 2024.'

def archive_event():
    import hashlib
    full=b'SYNTHETIC_ARCHIVED_ORIGINAL_BODY';sha=hashlib.sha256(full).hexdigest();r=dict(path='SYNTHETIC_OPAQUE',sha256=sha)
    e=dict(ticker='BBWI',ex_date='2024-08-23',listing_identity='NYSE:BBWI',original_current_literal=BBWI,original_money_tokens=['0.20'],current_amount_literal='0.20',record_date='2024-08-23',pay_date='2024-09-06',source_publication_date='2024-08-09',source_available_no_later_than='2024-08-15T10:36:00+00:00',unit=dict(accepted_at_utc='2024-06-04T20:55:29+00:00'),archive_capture=dict(http_status=200,source_CDX_route=dict(original='https://issuer.example/BBWI-current',digest='SYNTHETICDIGEST'),actual_CDX_digest='SYNTHETICDIGEST',opaque_ref=r,source_available_upper_bound_utc='2024-08-15T10:36:00+00:00'),amount_roles=[dict(role='DIRECT_CURRENT_REGULAR_QUARTER_PER_SHARE',literal='0.20')])
    item=dict(fragment_ref=dict(path='SYNTHETIC_CASH',sha256='1'*64),visible_text_utf8_sha256=hashlib.sha256(BBWI.encode()).hexdigest());source=dict(cash_fragments=[item],dated_header_observations=[dict(fragment_ref=dict(path='SYNTHETIC_DATE',sha256='2'*64))],source_url='https://issuer.example/BBWI-current',original_http_bytes_ref=r,received_http_bytes_sha256=sha,received_bytes=len(full),actual_first_publication_at=None,available_at=None);binding=p._VerifiedArchiveSupport(source_material_event=e,source_legal_issuer_literal='BATH & BODY WORKS INC',source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT');return e,source,binding,full


def test_archive_current_literal_preserves_missing_common_and_cashpaid_unit_only():
    import pandas as pd
    e,source,binding,full=archive_event();r=p._archive_terms(source,binding,lambda item:BBWI,pd.Timestamp(e['source_publication_date']),pd.Timestamp(e['source_available_no_later_than']),full)
    assert r['amount']==.20 and r['ticker']=='BBWI' and r['source_subject_role']==p.ARCHIVE_ROLE
    assert r['current_source_explicit_common'] is False and r['source_currency_explicit_USD'] is False
    assert r['source_currency_separate_SEC_USD_unit'] is True and not r['current_amount_from_capital_statement']
    assert r['amount_roles']==e['amount_roles'] and r['source_paragraph']==BBWI

@pytest.mark.parametrize('mutation',['AMOUNT','PAY','RECORD','DIGEST','CAPTURE','COMMON_INSERTED','MISSING_SUPPORT'])
def test_archive_source_role_negatives(mutation):
    import pandas as pd
    e,source,binding,full=archive_event();text=BBWI
    if mutation=='AMOUNT':e['current_amount_literal']='.22'
    elif mutation=='PAY':e['pay_date']='2024-09-09'
    elif mutation=='RECORD':e['record_date']='2024-08-26'
    elif mutation=='DIGEST':e['archive_capture']['actual_CDX_digest']='WRONG'
    elif mutation=='CAPTURE':e['source_available_no_later_than']='2024-08-16T00:00:00+00:00'
    elif mutation=='COMMON_INSERTED':text=text.replace('per share','per common share');e['original_current_literal']=text
    else:binding={}
    with pytest.raises(ValueError):p._archive_terms(source,binding,lambda item:text,pd.Timestamp('2024-08-09'),pd.Timestamp('2024-08-15T10:36:00+00:00'),full)


def test_archive_packet_does_not_impersonate_old_ticker_or_producer_identity():
    bridge=dict(schema='SOURCE131_ARCHIVED_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE',scope=p.ARCHIVE_SCOPE,ticker='BBWI',ex_date='2024-08-23',source_role_consumer_ref=p._ref(p.__file__),original_factory_ref=p.ORIGINAL_FACTORY_REF,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.BBWI',original_CUSIP='070830104',security_uid='CUSIP:070830104')
    assert p._archive_bridge_allowed(bridge)
    assert not p._archive_bridge_allowed(dict(bridge,ticker='HON'))
    assert not p._archive_bridge_allowed(dict(bridge,source_role_consumer_ref=p.ORIGINAL_FACTORY_REF))


def test_archive_three_optins_strip_to_canonical_source_AST_and_math_unchanged():
    import ast,copy,marshal
    from pathlib import Path
    base,_=p.original._owner();new,proof=p._owner();tree=ast.parse(Path(p.original.BASE_SOURCE_REF['path']).read_text())
    class Strip(ast.NodeTransformer):
        def visit_If(self,node):
            self.generic_visit(node);test=ast.unparse(node.test)
            if test=='isinstance(separate_common_binding, _VerifiedArchiveSupport)':return []
            if test=="support.get('schema') == ARCHIVE_SUPPORT_SCHEMA":return node.orelse
            if test=="'bulk_exact_archived_current_scope' in bundle":return node.orelse
            return node
    # Reconstruction is the pinned old factory pipeline; only the three explicit SOURCE opt-ins differ.
    for name in ('_original_dated_common_cash_terms','_frozen_common_cash_namespace','bind_source_account_descendant'):
        node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
        if name=='bind_source_account_descendant':node=p.original._Extend(name).visit(node)
        node=p.original._MsftSourceExtend(name).visit(node);ast.fix_missing_locations(node)
        canonical=ast.dump(node,include_attributes=False)
        # Actual maintained source hook has one protected AST opt-in at each node, asserted by factory.
        assert proof['archive_SOURCE_AST_optins'][name]==1 and proof['archive_SOURCE_AST_optins'][name+'_old_AST_sha256']==__import__('hashlib').sha256(canonical.encode()).hexdigest()
    assert marshal.dumps(base._post_native_cash_raw_namespace.__code__)==marshal.dumps(new._post_native_cash_raw_namespace.__code__)
    assert marshal.dumps(base.cash.normal_cash_ex_date.__code__)==marshal.dumps(new.cash.normal_cash_ex_date.__code__)


def test_original_FilingText_cover_entity_and_current_cash_entities_roles_distinct():
    from scripts.storage.refresh_sec_event_originals import FilingText
    tag='<ix:nonNumeric contextRef="c-1" name="dei:EntityRegistrantName">BATH &amp; BODY WORKS, INC.</ix:nonNumeric>'
    parser=FilingText();parser.feed(tag);assert ' '.join(' '.join(parser.parts).split())=='BATH & BODY WORKS, INC.'
    parser=FilingText();parser.feed('<p>'+BBWI.replace(' & ',' &amp; ')+'</p>');assert ' '.join(' '.join(parser.parts).split())==BBWI


FCNCA='On January 24, 2024, our Board declared a quarterly dividend on the Class A common stock and Class B common stock of $1.64 per common share. The dividends are payable on March 15, 2024 to stockholders of record as of February 29, 2024.'

def named_scope(month=False):
    text=FCNCA if not month else 'In January 2025, our Board declared a quarterly dividend on the Class A common stock and Class B common stock of $1.95 per common share. The dividends are payable on March 17, 2025 to stockholders of record as of February 28, 2025.'
    amount='1.95' if month else '1.64';record='2025-02-28' if month else '2024-02-29';pay='2025-03-17' if month else '2024-03-15'
    e=dict(ticker='FCNCA',issuer_CIK=798941,accounting_sid='SOURCE_ISSUER_COMMON_CLASS:8f80e8fde715d99d8f5783939d45cad40ef2eeae3c566d5dbdbb507e305f401c',original_CUSIP='31946M103',_source_book_ref=p.NAMED_BOOK_REF,literal_family='DIRECT_CURRENT_QUARTER_CLASS_A_AND_B_COMMON',original_current_literal=text,original_money_tokens=[amount],current_amount_literal=amount,record_date=record,pay_date=pay,source_publication_date='2025-02-21' if month else '2024-02-23',month_only_board_date_unknown=month,private_board_day=None,amount_roles=[dict(role='DIRECT_CURRENT_QUARTER_EQUAL_CLASS_A_AND_B_COMMON',literal=amount,source_common_classes=['A','B'],accounting_target_class='A')],original5field_key=dict(ticker='FCNCA',effective_date=record,reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='1'*64));return e

@pytest.mark.parametrize('month',[False,True])
def test_named_current_AB_samecash_accounting_A_and_unknown_private_day(monkeypatch,month):
    e=named_scope(month);monkeypatch.setattr(p,'_scope',lambda *a:e);r=p._named_semantics(e['original_current_literal'],facts(e),e['source_publication_date'],listed_common_class='A')
    assert r['selected_current_amount']==e['current_amount_literal'] and r['certified_source_cash_share_classes']==['A','B'] and r['certified_accounting_cash_share_classes']==['A']
    assert not r['other_class_account_position_created'] and not r['private_board_day_inferred'] and not r['annual_rate_divided_or_inferred']

@pytest.mark.parametrize('change',['AMOUNT','B_AS_ACCOUNT_TARGET','OTHER_CLASS','PRIOR_SENTENCE','JAN_DAY_INFERRED','WRONG_PUBLISH','PAY','RECORD'])
def test_named_current_class_money_date_private_clock_negatives(monkeypatch,change):
    e=named_scope(True);f=facts(e);text=e['original_current_literal'];listed='A';pub=e['source_publication_date']
    if change=='AMOUNT':f['cash_per_raw_share']=1.64
    elif change=='B_AS_ACCOUNT_TARGET':listed='B'
    elif change=='OTHER_CLASS':text=text.replace('Class B','Class C');e['original_current_literal']=text
    elif change=='PRIOR_SENTENCE':text+=' We paid a prior dividend of $0.75.';e['original_current_literal']=text
    elif change=='JAN_DAY_INFERRED':e['private_board_day']='2025-01-24'
    elif change=='WRONG_PUBLISH':pub='2025-01-24'
    elif change=='PAY':f['pay_date']='2025-03-18'
    else:f['record_date']='2025-03-01'
    monkeypatch.setattr(p,'_scope',lambda *a:e)
    with pytest.raises(ValueError):p._named_semantics(text,f,pub,listed_common_class=listed)


def test_named_frozen_CL_A_class_binding_no_COM_alias_or_other_cusip(monkeypatch):
    e=named_scope();monkeypatch.setattr(p,'_scope',lambda *a:e);payload=dict(sec_cash_statement_profile=p.NAMED_CURRENT);row=dict(title_of_class='CL A',cusip=e['original_CUSIP'],ticker='FCNCA');binding=p.original._VerifiedClass(profile=p.NAMED_CURRENT,original_frozen_class_literal='CL A',original_CUSIP=e['original_CUSIP'],ticker='FCNCA',row_unchanged=True)
    assert p._named_class_allowed(payload,{},facts(e),row,binding)
    assert not p._named_class_allowed(payload,{},facts(e),dict(row,title_of_class='COM'),binding)
    assert not p._named_class_allowed(payload,{},facts(e),dict(row,cusip='999999999'),binding)


def test_named_exact_SOURCE_three_class_clock_optins_preserve_old_fullclock_AST():
    import inspect,ast,hashlib,marshal
    owner,proof=p._owner();old,_=p.original._owner();expected=hashlib.sha256(ast.dump(ast.parse(inspect.getsource(p.original._completion_clock)),include_attributes=False).encode()).hexdigest()
    assert proof['named_SOURCE_class_clock_optins']==dict(class_allowed=1,subject_class=1,completion_clock=1)
    assert proof['old_completion_clock_AST_sha256']==expected
    assert marshal.dumps(owner._static_submission_dated_raw_identity.__code__)==marshal.dumps(old._static_submission_dated_raw_identity.__code__)
    assert marshal.dumps(owner._post_native_cash_raw_namespace.__code__)==marshal.dumps(old._post_native_cash_raw_namespace.__code__)
    assert marshal.dumps(owner.cash.normal_cash_ex_date.__code__)==marshal.dumps(old.cash.normal_cash_ex_date.__code__)


def test_actual_HEADER_only_ends_at_SEC_HEADER_not_following_wrapper_newline():
    header=b'<SEC-DOCUMENT>sample\n<SEC-HEADER>sample\n<ACCEPTANCE-DATETIME>20240223162020\n</SEC-HEADER>'
    full=header+b'\n<DOCUMENT>synthetic current body</DOCUMENT>'
    assert full[:full.index(b'</SEC-HEADER>')+len(b'</SEC-HEADER>')]==header
    assert full.split(b'<DOCUMENT>',1)[0]!=header
    assert full[:full.index(b'</SEC-HEADER>')+len(b'</SEC-HEADER>')]!=header.replace(b'20240223',b'20240224')


def test_new_named_cash_listed_class_callback_is_closed_exact_source_hook(monkeypatch):
    owner,proof=p._owner();assert '_completion_listed_class' in proof['closed_hooks']
    old,_=p.original._owner();fn=owner.cash.adjudicate_post_verified_cash_ex.__globals__['_completion_listed_class']
    assert fn(dict(sec_cash_statement_profile=p.original.MONETARY_COMMON),{}) is False
    import marshal
    assert owner.cash.adjudicate_post_verified_cash_ex.__code__.co_code==old.cash.adjudicate_post_verified_cash_ex.__code__.co_code
    assert marshal.dumps(owner.cash.normal_cash_ex_date.__code__)==marshal.dumps(old.cash.normal_cash_ex_date.__code__)


@pytest.mark.parametrize('mutation',['WRONG_CLASS','LATE_CLOCK','WRONG_CUSIP'])
def test_new_named_listed_cash_source_callback_wrongclass_clock_and_cusip(monkeypatch,mutation):
    owner,_=p._owner();fn=owner.cash.adjudicate_post_verified_cash_ex.__globals__['_completion_listed_class'];e=named_scope();monkeypatch.setattr(p,'_scope',lambda *a:e)
    # The callback's captured canonical clock is exercised separately by existing
    # complete clock witness tests; here supply that witness true only for the
    # synthetic metadata clock, so wrong role fields remain independent negatives.
    cells=dict(fn.__code__.co_freevars and zip(fn.__code__.co_freevars,fn.__closure__) or [])
    import types
    make=lambda x:(lambda:x).__closure__[0]
    def clock(binding,facts):
        if binding.get('source_statement_date')!='2024-02-23':raise ValueError('EXACT_ORIGINAL_PUBLIC_CLOCK_REQUIRED')
        return True
    closure=tuple(make(clock) if name=='clock' else cell for name,cell in zip(fn.__code__.co_freevars,fn.__closure__))
    testfn=types.FunctionType(fn.__code__,fn.__globals__,fn.__name__,fn.__defaults__,closure)
    b=dict(sec_cash_statement_profile=p.NAMED_CURRENT,original_frozen_class_literal='CL A',source_unique_listed_common_class='A',original_frozen_raw_CUSIP=e['original_CUSIP'],source_statement_date='2024-02-23')
    assert testfn(b,facts(e))
    if mutation=='WRONG_CLASS':b['original_frozen_class_literal']='COM'
    elif mutation=='WRONG_CUSIP':b['original_frozen_raw_CUSIP']='999999999'
    else:b['source_statement_date']='2026-01-01'
    if mutation=='LATE_CLOCK':
        with pytest.raises(ValueError):testfn(b,facts(e))
    else:assert testfn(b,facts(e)) is False


ICE='On May 1, 2025, we announced a $0.48 per share dividend for the second quarter of 2025 with the dividend payable on June 30, 2025 to stockholders of record as of June 13, 2025.'

def ice_scope():
    e=dict(ticker='ICE',issuer_CIK=1571949,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.ICE',_source_book_ref=p.ANNOUNCED_BOOK_REF,literal_family='ANNOUNCED_DIRECT_NAMED_QUARTER_WITH_NONVALUE_COMMON_UNIT',original_current_literal=ICE,current_amount_literal='0.48',pay_date='2025-06-30',record_date='2025-06-13',source_publication_date='2025-05-01',quarter_literal='for the second quarter of 2025',original_money_tokens=['0.48'],amount_roles=[dict(role='DIRECT_ANNOUNCED_CURRENT_NAMED_QUARTER_PER_SHARE',literal='0.48')],current_source_explicit_common=False,current_source_explicit_USD=False,original5field_key=dict(ticker='ICE',effective_date='2025-06-13',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='1'*64));return e


def test_announced_current_named_quarter_missingcommon_directcash_not_policy(monkeypatch):
    e=ice_scope();monkeypatch.setattr(p,'_scope',lambda *a:e);r=p.semantics(ICE,facts(e),e['source_publication_date'])
    assert r['profile']==p.DATED_CURRENT and r['selected_current_amount']=='0.48' and r['current_source_explicit_common'] is False
    assert r['quarter_authority']=='for the second quarter of 2025' and r['announced_not_relabelled_declared']
    assert not r['annual_rate_divided_or_inferred'] and not r['current_from_prior_paid_or_reported_concept']

@pytest.mark.parametrize('change',['QUARTER','AMOUNT','COMMON_INSERTED','ANNOUNCED_REWRITTEN','PUBLICATION','PAY','RECORD'])
def test_announced_named_quarter_current_source_negatives(change):
    e=ice_scope();text=e['original_current_literal']
    if change=='QUARTER':e['quarter_literal']='for the first quarter of 2025'
    elif change=='AMOUNT':e['current_amount_literal']='0.45'
    elif change=='COMMON_INSERTED':text=text.replace('per share','per common share');e['original_current_literal']=text
    elif change=='ANNOUNCED_REWRITTEN':text=text.replace('announced','declared');e['original_current_literal']=text
    elif change=='PUBLICATION':e['source_publication_date']='2025-04-30'
    elif change=='PAY':e['pay_date']='2025-07-01'
    else:e['record_date']='2025-06-16'
    with pytest.raises(ValueError):p._dated_literal(e,text)



def test_ICE_c2_NYSE_cover_and_c3_CHX_are_distinct_original_listing_roles():
    import ast,re,copy
    tree=ast.parse(Path(p.original.BASE_SOURCE_REF['path']).read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_sec_primary_html_cash_terms')
    assignment=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='listings' for t in n.targets))
    rejection=next(n for n in fn.body if isinstance(n,ast.If) and any(isinstance(x,ast.Constant) and x.value=='CA_SEC_HTML_REAL_US_COMMON_LEGAL_LISTING_REQUIRED' for x in ast.walk(n)))
    node=ast.FunctionDef(name='original_listing_guard',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='listing')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[copy.deepcopy(assignment),copy.deepcopy(rejection),ast.Return(value=ast.Name(id='listings',ctx=ast.Load()))],decorator_list=[])
    owner=p.original._base();ns=dict(re=re,submission_profile=True,name_key=lambda x:x,legal_name='SYNTHETIC_ISSUER',row=dict(name='SYNTHETIC_ISSUER'),US_state='Delaware',_US_CHARTER_STATE_NAMES=owner._US_CHARTER_STATE_NAMES,source=dict(source_original_ticker='ICE'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'ORIGINAL_SOURCE_LISTING_SYNTHETIC_PROJECTION','exec'),ns)
    assert ns['original_listing_guard']('Common Stock, $0.01 par value per share ICE New York Stock Exchange')==[('ICE','New York Stock Exchange')]
    with pytest.raises(ValueError,match='CA_SEC_HTML_REAL_US_COMMON_LEGAL_LISTING_REQUIRED'):ns['original_listing_guard']('Common Stock, $0.01 par value per share ICE CHX')


def kkr_scope(quarter='first',year='2025',amount='0.185'):
    text=f'A dividend of ${amount} per share of common stock of KKR & Co. Inc. has been declared for the {quarter} quarter of {year}, which will be paid on May 27, 2025 to holders of record of common stock as of the close of business on May 12, 2025.'
    return dict(ticker='KKR',issuer_CIK=1404912,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.KKR',_source_book_ref=p.KKR_BOOK_REF,literal_family='PASSIVE_DECLARED_DIRECT_NAMED_QUARTER_CURRENT_COMMON',original_current_literal=text,current_amount_literal=amount,pay_date='2025-05-27',record_date='2025-05-12',source_publication_date='2025-05-01',quarter_literal=f'for the {quarter} quarter of {year}',original_money_tokens=[amount],amount_roles=[dict(role='DIRECT_DECLARED_CURRENT_NAMED_QUARTER_PER_COMMON_SHARE',literal=amount)],current_source_explicit_common=True,current_source_explicit_USD=False,original5field_key=dict(ticker='KKR',effective_date='2025-05-12',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='1'*64))

@pytest.mark.parametrize('quarter,year,amount',[('fourth','2023','0.165'),('first','2025','0.185'),('second','2025','0.185')])
def test_kkr_current_namedquarter_passive_direct_common_cash_roles(monkeypatch,quarter,year,amount):
    e=kkr_scope(quarter,year,amount);monkeypatch.setattr(p,'_scope',lambda *a:e);r=p.semantics(e['original_current_literal'],facts(e),e['source_publication_date'])
    assert r['profile']==p.DATED_CURRENT and r['selected_current_amount']==amount and r['source_role_book_ref']==p.KKR_BOOK_REF
    assert r['quarter_authority']==e['quarter_literal'] and r['current_source_explicit_common'] is True and r['current_currency_word_present'] is False
    assert not r['current_from_prior_paid_or_reported_concept'] and not r['annual_rate_divided_or_inferred']

@pytest.mark.parametrize('change',['QUARTER','AMOUNT','RECORD','PAY','PREFERRED','ANNUAL_POLICY','CURRENT_COMMON_FLAG','OTHER_ISSUER','OTHER_BOOK'])
def test_kkr_namedquarter_source_role_negatives(change):
    e=kkr_scope();text=e['original_current_literal']
    if change=='QUARTER':e['quarter_literal']='for the second quarter of 2025'
    elif change=='AMOUNT':e['current_amount_literal']='0.165'
    elif change=='RECORD':e['record_date']='2025-05-13'
    elif change=='PAY':e['pay_date']='2025-05-28'
    elif change=='PREFERRED':text=text.replace('common stock','preferred stock');e['original_current_literal']=text
    elif change=='ANNUAL_POLICY':text=text.replace('has been declared for the first quarter of 2025','is intended for future quarters');e['original_current_literal']=text
    elif change=='CURRENT_COMMON_FLAG':e['current_source_explicit_common']=False
    elif change=='OTHER_ISSUER':e['issuer_CIK']=1858681
    else:e['_source_book_ref']=p.BOOK_REF
    with pytest.raises(ValueError):p._dated_literal(e,text)


def test_kkr_SOURCE_single_leaf_strip_preserves_old_all_function_AST():
    import ast,hashlib
    oldpath=Path(r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\source_custody\consensus_cash_source_bulk_completion_eb670419_ice_c2cover_r2.py')
    assert hashlib.sha256(oldpath.read_bytes()).hexdigest()=='eb6704194c6b2a231db1cbb1fe52413c5db43c6747fd8f09327c7fb227aae0f7'
    old=ast.parse(oldpath.read_text());new=ast.parse(_pre_vendor_source_text(Path(p.__file__).read_text()));oldnodes={n.name:n for n in old.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))};newnodes={n.name:n for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))};assert set(newnodes)==set(oldnodes)|{'_ferg_semantics'}
    class Strip(ast.NodeTransformer):
        count=0
        def visit_If(self,node):
            if ast.dump(node.test,include_attributes=False)==ast.dump(ast.parse("family=='PASSIVE_DECLARED_DIRECT_NAMED_QUARTER_CURRENT_COMMON'",mode='eval').body,include_attributes=False):
                self.count+=1;return self.visit(node.orelse[0])
            return self.generic_visit(node)
    strip=Strip();stripped=strip.visit(copy.deepcopy(newnodes['_dated_literal']));assert strip.count==1
    for name,node in oldnodes.items():
        if name in ('_archive_event','_archive_support','_archive_terms','_archive_packet','_archive_bridge_allowed','_support','_named_class_allowed','_named_subject_class','_owner'):continue
        assert ast.dump(node,include_attributes=False)==ast.dump(stripped if name=='_dated_literal' else newnodes[name],include_attributes=False),name


GLW="Corning Incorporated ’s (NYSE: GLW) Board of Directors today declared a quarterly dividend of $0.28 per share. The dividend will be payable on December 12, 2025, to shareholders of record on November 14, 2025."


def glw_archive_parts(tmp_path):
    import hashlib
    e,source,binding,body=archive_event()
    e.update(ticker='GLW',ex_date='2025-11-14',issuer_CIK=24741,_source_book_ref=p.GLW_BOOK_REF,listing_identity='NYSE:GLW',literal_family='ARCHIVED_ORIGINAL_CURRENT_QUARTER_PER_SHARE_DECLARATION',original_current_literal=GLW,original_money_tokens=['0.28'],current_amount_literal='0.28',record_date='2025-11-14',pay_date='2025-12-12',source_publication_date='2025-10-08',source_available_no_later_than='2025-11-10T03:55:40+00:00',amount_roles=[dict(role='DIRECT_CURRENT_QUARTER_PER_SHARE_FROM_ORIGINAL_IR',literal='0.28')])
    e['archive_capture']['source_available_upper_bound_utc']=e['source_available_no_later_than']
    source['cash_fragments'][0]['visible_text_utf8_sha256']=hashlib.sha256(GLW.encode()).hexdigest()
    binding.update(source_material_event=e,source_legal_issuer_literal='CORNING INC')
    return e,source,binding,body


def test_glw_archive_current_IR_literal_separate_declared_unit_and_date(tmp_path):
    import pandas as pd
    e,source,binding,body=glw_archive_parts(tmp_path);r=p._archive_terms(source,binding,lambda item:GLW,pd.Timestamp(e['source_publication_date']),pd.Timestamp(e['source_available_no_later_than']),body)
    assert r['amount']==.28 and r['record']=='2025-11-14' and r['pay']=='2025-12-12' and r['current_source_explicit_common'] is False
    assert r['actual_first_publication_at'] is None and r['source_publication_calendar_date_role']=='ORIGINAL_DISPLAYED_ARTICLE_DATE_NOT_FIRST_PUBLICATION_CERTIFICATE'
    assert r['source_paragraph']==GLW and not r['current_amount_from_capital_statement']

@pytest.mark.parametrize('change',['AMOUNT','RECORD','PAY','DATE','CAPTURE','BOOK','COMMON_REWRITE'])
def test_glw_exact_archive_SOURCE_literal_clock_role_negatives(tmp_path,change):
    import pandas as pd
    e,source,binding,body=glw_archive_parts(tmp_path);text=GLW;pub=pd.Timestamp(e['source_publication_date']);capture=pd.Timestamp(e['source_available_no_later_than'])
    if change=='AMOUNT':e['current_amount_literal']='0.27'
    elif change=='RECORD':e['record_date']='2025-11-15'
    elif change=='PAY':e['pay_date']='2025-12-13'
    elif change=='DATE':pub=pd.Timestamp('2025-10-09')
    elif change=='CAPTURE':capture=pd.Timestamp('2025-11-11T03:55:40+00:00')
    elif change=='BOOK':e['_source_book_ref']=p.ARCHIVE_BOOK_REF
    else:text=text.replace('per share','per common share');e['original_current_literal']=text
    with pytest.raises(ValueError):p._archive_terms(source,binding,lambda item:text,pub,capture,body)

@pytest.mark.parametrize('ticker,scope,sid,day',[('GLW','GLW','FROZEN_RAW_TRANSPORT_CODE:US.GLW','2025-11-14'),('BBWI','BBWI','FROZEN_RAW_TRANSPORT_CODE:US.BBWI','2024-08-23')])
def test_new_GLW_and_old_BBWI_real_scope_bridge_remain_separate(ticker,scope,sid,day):
    scope=p.GLW_ARCHIVE_SCOPE if scope=='GLW' else p.ARCHIVE_SCOPE
    b=dict(schema='SOURCE131_ARCHIVED_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE',scope=scope,ticker=ticker,ex_date=day,source_role_consumer_ref=p._ref(p.__file__),original_factory_ref=p.ORIGINAL_FACTORY_REF,accounting_sid=sid,original_CUSIP='SYNTHETIC',security_uid='CUSIP:SYNTHETIC')
    assert p._archive_bridge_allowed(b)
    assert not p._archive_bridge_allowed(dict(b,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.OTHER'))
    assert not p._archive_bridge_allowed(dict(b,ticker='OTHER'))
    assert not p._archive_bridge_allowed(dict(b,ex_date='2025-01-01'))


def test_GLW_SOURCE_delta_all_other_functions_classes_identical_to_frozen79199():
    import ast,hashlib
    oldpath=Path(r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\source_custody\consensus_cash_source_bulk_completion_79199c26_kkr_text_r2.py')
    assert hashlib.sha256(oldpath.read_bytes()).hexdigest()=='79199c266982e4a99f11b8a88df75c951acf40c7600ac70910ca3e0c351b740d'
    defs=lambda text:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    old=defs(oldpath.read_text());new=defs(_pre_vendor_source_text(Path(p.__file__).read_text()));assert set(new)==set(old)|{'_ferg_semantics'}
    changed={name for name in old if old[name]!=new[name]};assert changed=={'_archive_event','_archive_support','_archive_terms','_archive_packet','_archive_bridge_allowed','_support','_named_class_allowed','_named_subject_class','_owner'}


FERG='The timetable for payment of the quarterly divid end of $0.83 per share is as follows:'
FERG_DATES='Ex-dividend date: March 21, 2025 Record date: March 21, 2025 Payment date: May 6, 2025'


def ferg_scope(tmp_path,monkeypatch):
    datefile=tmp_path/'date.html';datefile.write_text(FERG_DATES)
    e=dict(ticker='FERG',issuer_CIK=2011641,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.FERG',_source_book_ref=p.FERG_BOOK_REF,literal_family='PUBLISHED_CURRENT_COMMON_QUARTER_PAYMENT_TIMETABLE',original_current_literal=FERG,original_timetable_literal=FERG_DATES,current_timetable_fragment_ref=dict(path=str(datefile),sha256='SYNTHETIC'),current_amount_literal='0.83',ex_date='2025-03-21',record_date='2025-03-21',pay_date='2025-05-06',source_publication_date='2025-03-11',private_board_day=None,original_money_tokens=['0.83'],amount_roles=[dict(role='DIRECT_CURRENT_QUARTER_TIMETABLE_PER_SHARE',literal='0.83')],original_frozen_class_literal='COMMON     STOCK  NEW',original_CUSIP='31488V107',original5field_key=dict(ticker='FERG',effective_date='2025-03-21',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='1'*64))
    monkeypatch.setattr(p,'_scope',lambda *a:e);monkeypatch.setattr(p,'_pin',lambda *a:datefile);return e


def test_FERG_public_timetable_keeps_two_original_fragments_and_frozen_title(tmp_path,monkeypatch):
    e=ferg_scope(tmp_path,monkeypatch);r=p._ferg_semantics(FERG,facts(e),e['source_publication_date'])
    assert r['selected_current_amount']=='0.83' and r['published_timetable_not_declared'] and r['separate_original_cash_and_schedule_not_fake_single_statement']
    assert r['original_frozen_class_literal']=='COMMON     STOCK  NEW' and not r['private_board_day_inferred'] and not r['current_amount_from_reported_concept']

@pytest.mark.parametrize('change',['AMOUNT','RECORD','PAY','PUBLICATION','BOARD_DAY','DECLARED_REWRITE','COMMON_REWRITE','OTHER_BOOK','OTHER_ISSUER','LISTED_A'])
def test_FERG_exact_public_timetable_role_negatives(tmp_path,monkeypatch,change):
    e=ferg_scope(tmp_path,monkeypatch);f=facts(e);text=FERG;pub=e['source_publication_date'];listed=None
    if change=='AMOUNT':f['cash_per_raw_share']=.84
    elif change=='RECORD':f['record_date']='2025-03-22'
    elif change=='PAY':f['pay_date']='2025-05-07'
    elif change=='PUBLICATION':pub='2025-03-10'
    elif change=='BOARD_DAY':e['private_board_day']='2025-03-11'
    elif change=='DECLARED_REWRITE':text=text.replace('The timetable for payment of','The Board declared');e['original_current_literal']=text
    elif change=='COMMON_REWRITE':text=text.replace('per share','per common share');e['original_current_literal']=text
    elif change=='OTHER_BOOK':e['_source_book_ref']=p.GROUP2_BOOK_REF
    elif change=='OTHER_ISSUER':e['issuer_CIK']=701985
    else:listed='A'
    with pytest.raises(ValueError):p._ferg_semantics(text,f,pub,listed_common_class=listed)


def test_FERG_exact_frozen_COMMON_STOCK_NEW_not_COM_alias_or_other_class(tmp_path,monkeypatch):
    e=ferg_scope(tmp_path,monkeypatch);payload=dict(sec_cash_statement_profile=p.FERG_CURRENT,source_projection=facts(e));row=dict(title_of_class='COMMON     STOCK  NEW',cusip='31488V107',ticker='FERG');binding=p.original._VerifiedClass(profile=p.FERG_CURRENT,original_frozen_class_literal=row['title_of_class'],original_CUSIP=row['cusip'],ticker='FERG',row_unchanged=True)
    assert p._named_class_allowed(payload,{},facts(e),row,binding) and p._named_subject_class(p.FERG_CURRENT,payload,row,'Common stock, par value $0.0001 per share FERG New York Stock Exchange')
    assert not p._named_class_allowed(payload,{},facts(e),dict(row,title_of_class='COM'),binding)
    assert not p._named_subject_class(p.FERG_CURRENT,payload,dict(row,cusip='000000000'),'Common stock FERG')
    assert not p._named_subject_class(p.FERG_CURRENT,payload,row,'Class A Common Stock FERG')


def test_FERG_source_delta_keeps_all_archive_and_other_functions_AST_frozen91a1():
    import ast,hashlib
    oldpath=Path(r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\source_custody\consensus_cash_source_bulk_completion_91a1c34c_glw_date_r2.py');assert hashlib.sha256(oldpath.read_bytes()).hexdigest()=='91a1c34cec3299b121c8663c8f0691735fba726cbf11315484dc248a790f966b'
    defs=lambda text:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    old=defs(oldpath.read_text());new=defs(_pre_vendor_source_text(Path(p.__file__).read_text()));assert set(new)==set(old)|{'_ferg_semantics'};assert {name for name in old if old[name]!=new[name]}=={'_support','_named_class_allowed','_named_subject_class','_owner'}


def _vendor_fixture(monkeypatch):
    from scripts.research.a2.data import consensus_cash_source_bulk_completion as source,consensus_account_inputs as inputs
    monkeypatch.setattr(source,'_vendor_identity',lambda fact:{'accounting_sid':fact['accounting_sid']})
    monkeypatch.setattr(source,'_vendor_original_components',lambda fact:[x['record'] for x in fact['vendor_components']])
    monkeypatch.setattr(source,'_pin',lambda ref:None)
    common=dict(ticker='BABA',ex_dividend_date='2024-06-13',record_date='2024-06-13',pay_date='2024-07-12',declaration_date='2024-05-14',currency='USD')
    components=[dict(record=dict(common,id='regular',distribution_type='recurring',cash_amount=1.0),pagination_complete=True,raw_ref=dict(path='D:/synthetic/raw1',sha256='a'*64),checkpoint_ref=dict(path='D:/synthetic/cp1',sha256='b'*64),original_cash_amount_decimal='1.0'),dict(record=dict(common,id='special',distribution_type='special',cash_amount=.66),pagination_complete=True,raw_ref=dict(path='D:/synthetic/raw1',sha256='a'*64),checkpoint_ref=dict(path='D:/synthetic/cp1',sha256='b'*64),original_cash_amount_decimal='.66')]
    fact=dict(schema='SOURCE131_ORIGINAL_MASSIVE_VENDOR_CASH_NATIVE_FACT_R1',source_type='TIER3_VENDOR_METADATA',available_at=None,ordinary_cash_confirmed=False,clock_role='POST_VERIFIED_ACCOUNTING_ONLY',ticker='BABA',ex_date='2024-06-13',record_date='2024-06-13',pay_date='2024-07-12',declaration_date='2024-05-14',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.BABA',original5field_key=dict(ticker='BABA',effective_date='2024-06-13',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='c'*64),vendor_components=components,derived_cash_amount_decimal='1.66',source_kind='COMPOSITE_CASH',amount_aggregation_role='DERIVED_ORIGINAL_COMPONENT_SUM_CREDIT_ONCE',group_id='d'*64,vendor_endpoint='https://api.massive.com/stocks/v1/dividends')
    import hashlib,json
    group=dict(original5field_key=fact['original5field_key'],accounting_sid=fact['accounting_sid'],listed_unit='RAW_ACTUAL_SHARE',currency='USD',dates={k:common[k] for k in ('ex_dividend_date','record_date','pay_date','declaration_date','currency')},components=sorted([dict(id=c['record']['id'],type=c['record']['distribution_type'],original_amount=c['original_cash_amount_decimal'],rawSHA=c['raw_ref']['sha256']) for c in components],key=lambda x:x['id']),clock_role='POST_VERIFIED_ACCOUNTING_ONLY');fact['canonical_group_definition']=group;fact['group_id']=hashlib.sha256(json.dumps(group,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return source,inputs.existing.ca,fact,dict(path='D:/synthetic/fact.json',sha256='e'*64)

def test_vendor_composite_native_original_ca_type_credit_once(monkeypatch):
    source,ca,fact,ref=_vendor_fixture(monkeypatch);event=source._vendor_fact_event(ca,fact,ref)
    assert isinstance(event,ca.ResearchReconstructedCashEvent) and event.action_type=='CASH_DIVIDEND' and event.cash_per_old_share==1.66 and event.available_at is None
    assert event.event_id.startswith('SOURCE_COMPONENT_GROUP:') and fact['ordinary_cash_confirmed'] is False
    quantity=7.5;assert quantity*event.cash_per_old_share==pytest.approx(sum(quantity*x['record']['cash_amount'] for x in fact['vendor_components']))

@pytest.mark.parametrize('bad',('duplicate_id','currency','date','total','missing_page','future_pay','group_hash','group_role'))
def test_vendor_component_source_scope_negatives(monkeypatch,bad):
    source,ca,fact,ref=_vendor_fixture(monkeypatch)
    if bad=='duplicate_id':fact['vendor_components'][1]['record']['id']='regular'
    elif bad=='currency':fact['vendor_components'][1]['record']['currency']='EUR'
    elif bad=='date':fact['vendor_components'][1]['record']['pay_date']='2024-07-13'
    elif bad=='total':fact['derived_cash_amount_decimal']='1.67'
    elif bad=='missing_page':fact['vendor_components'][1]['pagination_complete']=False
    elif bad=='future_pay':fact['pay_date']='2026-01-01'
    elif bad=='group_hash':fact['group_id']='0'*64
    elif bad=='group_role':fact['canonical_group_definition']['listed_unit']='FUTURE_SPLIT_ADJUSTED'
    with pytest.raises(ValueError):source._vendor_fact_event(ca,fact,ref)

def test_vendor_leaf_preserves_all_old_functions_after_exact_dispatch_strip():
    import ast
    from scripts.research.a2.data import consensus_cash_source_bulk_completion as source
    oldpath=Path('D:/us-tech-quant-backtests/CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2/20261012T025603+0000_4a58260e/source_custody/consensus_cash_source_bulk_completion_b4fb4188_ferg_mainurl_r2.py')
    old=ast.parse(oldpath.read_text(encoding='utf-8'));new=ast.parse(Path(source.__file__).read_text(encoding='utf-8'));od={x.name:x for x in old.body if isinstance(x,(ast.FunctionDef,ast.ClassDef))};nd={x.name:x for x in new.body if isinstance(x,(ast.FunctionDef,ast.ClassDef))}
    assert set(nd)-set(od)=={'_vendor_metadata','_vendor_identity','_vendor_original_components','_vendor_fact_event','_bind_vendor_source_descendant'}
    dispatch=nd['bind_source_account_descendant'].body.pop(0);assert isinstance(dispatch,ast.If) and 'VENDOR_NATIVE_SCHEMA' in ast.unparse(dispatch.test)
    for name,node in od.items():assert ast.dump(node,include_attributes=False)==ast.dump(nd[name],include_attributes=False),name

@pytest.mark.parametrize('page',({'pagination_complete':False,'attempts':[]},{'pagination_complete':True,'attempts':[{'next_url_present':True}]}))
def test_vendor_real_capture_incomplete_page_cannot_be_overridden_by_fact(monkeypatch,page):
    from scripts.research.a2.data import consensus_cash_source_bulk_completion as source
    from scripts.storage import massive_dividend_sources as M
    monkeypatch.setattr(source,'_vendor_metadata',lambda ref,names:dict(page,contract=dict(endpoint=M.ENDPOINT,query=dict(ticker='BABA',ex_dividend_date='2024-06-13'))))
    fact=dict(ticker='BABA',ex_date='2024-06-13',vendor_components=[dict(checkpoint_ref={},pagination_complete=True)])
    with pytest.raises(ValueError,match='VENDOR_ACTUAL_COMPLETE_PAGE_REQUIRED'):source._vendor_original_components(fact)

@pytest.mark.parametrize('explicit_page',(True,None))
def test_vendor_real200_no_next_accepts_window_and_original_probe_schema(monkeypatch,tmp_path,explicit_page):
    import json
    from scripts.research.a2.data import consensus_cash_source_bulk_completion as source
    from scripts.storage import massive_dividend_sources as M
    record=dict(ticker='X',id='X1',ex_dividend_date='2024-06-13',record_date='2024-06-13',pay_date='2024-07-12',declaration_date='2024-05-14',currency='USD',cash_amount=1.,distribution_type='recurring',frequency=4)
    raw=tmp_path/'raw.json';raw.write_text(json.dumps(dict(results=[record],status='OK')));rr=dict(path=str(raw),sha256=source._ref(raw)['sha256'])
    cp=dict(contract=dict(endpoint=M.ENDPOINT,query=dict(ticker='X',ex_dividend_date='2024-06-13')),attempts=[dict(http_status=200,next_url_present=False,raw_ref=rr)])
    if explicit_page is not None:cp['pagination_complete']=explicit_page
    monkeypatch.setattr(source,'_vendor_metadata',lambda ref,names:cp);monkeypatch.setattr(source,'_pin',lambda ref:raw)
    fact=dict(ticker='X',ex_date='2024-06-13',vendor_components=[dict(checkpoint_ref={},raw_ref=rr,record=record)])
    assert source._vendor_original_components(fact)==[record]
