from pathlib import Path
import copy,json
from decimal import Decimal
import pandas as pd
import pytest
from scripts.research.a2.data import consensus_cash_source_profile_completion as p

BAC="On January 31, 2024, the Corporation's Board of Directors (the Board) declared a quarterly common stock dividend of $0.24 per share, payable on March 29, 2024 to shareholders of record as of March 1, 2024."
AME="On February 9, 2023, AMETEK's Board of Directors has approved a 14% increase in its quarterly cash dividend on common stock to $0.25 per share from $0.22 per share. The dividend is payable on March 31, 2023 to shareholders of record as of March 10, 2023. This dividend increase will raise the indicated annual rate to $1.00 per share."
STZ="On July 2, 2024, Constellation's board of directors declared a quarterly cash dividend of $1.01 per share of Class A Common Stock payable on August 23, 2024, to stockholders of record as of the close of business on August 14, 2024."

def facts(amount=.24,record='2024-03-01',pay='2024-03-29'):
    return dict(cash_per_raw_share=amount,record_date=record,pay_date=pay)

def test_named_monetary_unit_is_independent_of_cashflow_neighbours():
    r=p.statement_semantics(p.MONETARY_COMMON,BAC,facts(),'2024-02-20')
    assert r['selected_current_amount']=='0.24' and r['original_text_not_rewritten']
    with pytest.raises(ValueError):p._base()._static_submission_cash_statement(BAC,facts(),'2024-02-20')

def test_all_amount_roles_are_preserved_and_no_annual_conversion():
    r=p.statement_semantics(p.CURRENT_PRIOR_ANNUAL,AME,facts(.25,'2023-03-10','2023-03-31'),'2023-02-10')
    assert [(x['role'],x['literal']) for x in r['amount_roles']]==[('CURRENT_QUARTER_DECLARATION','0.25'),('PRIOR_QUARTER_COMPARISON_NOT_CASH','0.22'),('INDICATED_ANNUAL_RATE_NOT_CASH','1.00')]
    assert r['annual_rate_divided_or_inferred'] is False
    for changed in (.22,1.):
        with pytest.raises(ValueError,match='CURRENT_AMOUNT_CHANGED'):p.statement_semantics(p.CURRENT_PRIOR_ANNUAL,AME,facts(changed,'2023-03-10','2023-03-31'),'2023-02-10')

@pytest.mark.parametrize('text',[BAC.replace('common stock','preferred stock'),BAC.replace('$0.24','24 cents'),BAC.replace('March 1, 2024','March 2, 2024'),BAC+' Another dividend of $0.30 per share is payable on April 1, 2024.',BAC.replace('dividend of','stock dividend of')])
def test_unit_clock_and_multiple_payment_negatives(text):
    with pytest.raises(ValueError):p.statement_semantics(p.MONETARY_COMMON,text,facts(),'2024-02-20')

def test_explicit_class_must_match_the_listed_class():
    f=facts(1.01,'2024-08-14','2024-08-23')
    assert p.statement_semantics(p.EXACT_COMMON_CLASS,STZ,f,'2024-07-03',listed_common_class='A')['selected_current_amount']=='1.01'
    for c in (None,'B','C'):
        with pytest.raises(ValueError):p.statement_semantics(p.EXACT_COMMON_CLASS,STZ,f,'2024-07-03',listed_common_class=c)

def test_unknown_or_multiclass_statement_is_never_alias_matched():
    for text in (STZ.replace('Class A','Class D'),STZ.replace('Class A','Class A and Class B')):
        with pytest.raises(ValueError):p.statement_semantics(p.EXACT_COMMON_CLASS,text,facts(1.01,'2024-08-14','2024-08-23'),'2024-07-03',listed_common_class='A')

def test_class_witness_preserves_original_title_and_uid(tmp_path):
    row=dict(ticker='X',cusip='123456789',title_of_class='CL A',effective_start='2024-01-01',effective_end='2024-12-31')
    f=tmp_path/'identity.json';f.write_text(json.dumps(dict(rows=[dict(original_source_row=row)])))
    payload=dict(sec_cash_statement_profile=p.EXACT_COMMON_CLASS,sec_source_transport_profile=p._base().SEC_STATIC_SUBMISSION_PROFILE,frozen_account_identity_ref=dict(path=str(f)),same_file_cash_identity_support_ref={'proof':'generated'})
    entry=dict(prior_raw_close=dict(prior_date='2024-08-13'));facts0=dict(ticker='X')
    w=p._class_binding(payload,entry,facts0,'Class A Common Stock X New York Stock Exchange','Example Inc',lambda r:Path(r['path']))
    assert w['original_frozen_class_literal']=='CL A' and row['title_of_class']=='CL A'
    assert p._class_allowed(payload,entry,facts0,row,w)
    assert not p._class_allowed(payload,entry,facts0,row,dict(w))
    with pytest.raises(ValueError):p._class_binding(payload,entry,facts0,'Class B Common Stock X New York Stock Exchange','Example Inc',lambda r:Path(r['path']))
    row['ticker']='REUSED';assert not p._class_allowed(payload,entry,facts0,row,w)

@pytest.mark.parametrize('text,f,publication,listed',[(STZ,facts(1.01,'2024-08-14','2024-08-23'),'2024-07-03','A'),(BAC,facts(),'2024-02-20',None),(BAC.replace('common stock','Class B common stock'),facts(),'2024-02-20','A')])
def test_old_profile_has_identical_success_or_failure(text,f,publication,listed):
    def outcome(fun):
        try:return ('OK',fun(text,f,publication,listed_common_class=listed))
        except Exception as e:return (type(e).__name__,str(e))
    assert outcome(p._base()._static_submission_cash_statement)==outcome(lambda text,f,pub,**kw:p._statement(p.OLD_STATIC,text,f,pub,**kw))
    assert p._binding_fields(p.OLD_STATIC,None,None,None,None,None)=={}

def test_exact_code_anchor_and_native_functions_retained():
    owner,proof=p._owner()
    assert proof['_sec_primary_html_cash_terms']['statement_call']==1
    assert proof['msft__post_native_cash_raw_namespace']==dict(post_native_schema_only=1)
    for name in ('classify_existing_cash','_read','_pin'):
        assert getattr(owner,name).__code__ is getattr(p._base(),name).__code__
    assert owner.cash._guard.__code__ is p.cash._guard.__code__
    assert owner.cash.normal_cash_ex_date.__code__ is p.cash.normal_cash_ex_date.__code__
    with pytest.raises(ValueError,match='EXACT_PINNED_PROFILE_SCOPE_REQUIRED'):
        p.bind_source_account_descendant(None,{},dict(source_refs=[]),account_dates=['2024-01-02'])


def test_comparison_monetary_common_subject_is_exact_ticker_not_borrowed_cashflow():
    text='On February 5, 2024, the Board of Directors declared a regular quarterly dividend of $0.85 per share of MCO Common Stock, a 10% increase from the prior quarterly dividend of $0.77 per share. The dividend will be payable on March 15, 2024, to stockholders of record at the close of business on February 23, 2024.'
    f=dict(facts(.85,'2024-02-23','2024-03-15'),ticker='MCO')
    r=p.statement_semantics(p.CURRENT_PRIOR_ANNUAL,text,f,'2024-02-13')
    assert [x['literal'] for x in r['amount_roles']]==['0.85','0.77']
    for ticker in ('OTHER',''):
        with pytest.raises(ValueError):p.statement_semantics(p.CURRENT_PRIOR_ANNUAL,text,dict(f,ticker=ticker),'2024-02-13')
    with pytest.raises(ValueError):p.statement_semantics(p.CURRENT_PRIOR_ANNUAL,text.replace('prior quarterly dividend of $0.77','prior quarterly dividend of $0.90'),f,'2024-02-13')


@pytest.mark.parametrize('extra',[' An additional dividend is $0.50 a share.',' Another quarterly dividend is $0.50 per common stock share.'])
def test_unknown_monetary_units_cannot_disappear_from_comparison_audit(extra):
    with pytest.raises(ValueError,match='UNCLASSIFIED_MONETARY'):
        p.statement_semantics(p.CURRENT_PRIOR_ANNUAL,AME+extra,facts(.25,'2023-03-10','2023-03-31'),'2023-02-10')

@pytest.mark.parametrize('profile,text,f,pub,listed',[(p.MONETARY_COMMON,BAC,facts(),'2024-02-20',None),(p.EXACT_COMMON_CLASS,STZ,facts(1.01,'2024-08-14','2024-08-23'),'2024-07-03','A')])
def test_unknown_or_second_monetary_statement_is_hard_blocked(profile,text,f,pub,listed):
    for extra in (' An additional dividend is $0.50 a share.',' A second dividend is $0.50 per share.'):
        with pytest.raises(ValueError):p.statement_semantics(profile,text+extra,f,pub,listed_common_class=listed)

def completion_binding():
    f=dict(facts(),ticker='X',security_id='FROZEN_RAW_TRANSPORT_CODE:US.X')
    raw=dict(ticker='X',security_uid='CUSIP:123456789',accounting_sid=f['security_id'],same_dated_UID_and_SID=True,source_coordinate='RAW_ACTUAL_SHARE',new_legal_CUSIP_authority=False,share_quantity_effect=False,prior_date='2024-02-28',ex_date='2024-02-29')
    row=dict(ticker='X',security_id_type='CUSIP',security_id='123456789',cusip='123456789',title_of_class='COM',effective_start='2024-01-01',effective_end='2024-12-31')
    b=dict(sec_cash_statement_profile=p.MONETARY_COMMON,source_profile_owner_ref=p._ref(p.__file__),source_base_owner_ref=copy.deepcopy(p.BASE_SOURCE_REF),source_completion_profile_scope=copy.deepcopy(p.SCOPE),selected_original_cash_statement=BAC,source_statement_date='2024-02-20',source_unique_listed_common_class=None,source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=raw,original_frozen_raw_CUSIP='123456789',original_frozen_class_literal='COM',original_frozen_class_rewritten=False)
    b['source_profile_completion']=p.statement_semantics(p.MONETARY_COMMON,BAC,f,b['source_statement_date'])
    return b,f

def test_clock_consumer_requires_exact_code_scope_full_roles_and_unchanged_uid():
    b,f=completion_binding();assert p._completion_clock(b,f)
    for field,value in [('source_profile_owner_ref',{}),('source_completion_profile_scope',{}),('source_profile_completion',{}),('original_frozen_class_rewritten',True),('original_frozen_class_literal','CL A')]:
        bad=copy.deepcopy(b);bad[field]=value
        with pytest.raises(ValueError):p._completion_clock(bad,f)
    bad=copy.deepcopy(b);bad['static_submission_dated_raw_identity_proof']['security_uid']='CUSIP:987654321'
    with pytest.raises(ValueError):p._completion_clock(bad,f)

def test_private_cash_default_functions_and_old_profile_adjudication_unchanged():
    owner,anchors=p._cash_owner();assert anchors['adjudicate_post_verified_cash_ex']==dict(roles=1,witness=1,static_profile=2,listed_class=1,qsr_exact_cash_jurisdiction=1,qsr_exact_cash_currency_basis=1)
    assert anchors['validate_cns_bank_holiday_record_binding']==dict(record_whitelist=1,notice_field=6,source_sha=3)
    for name in ('_guard','normal_cash_ex_date','source_derived_security_id'):
        assert getattr(owner,name).__code__ is getattr(p.cash,name).__code__
    args=dict(calendar=['2024-01-02'],calendar_binding={},rule_sources=[],scope_end_exclusive='2026-01-01',source_scope=p._base().SEC_CASH_SOURCE_SCOPE)
    assert owner.adjudicate_post_verified_cash_ex({},**args)==p.cash.adjudicate_post_verified_cash_ex({},**args)


def test_cns_extension_is_only_two_exact_source_tuples_and_normal_calendar_unchanged():
    old=p._cns_tuple('2025-11-11');new=p._cns_tuple('2024-11-11')
    assert old['notice_sha256']==p.cash.NSCC_CNS_2025_NOTICE_SHA256 and old['notice_page_zero_based']==1
    assert new['cns_projected_record_date']=='2024-11-08' and new['notice_page_zero_based']==2
    with pytest.raises(ValueError):p._cns_tuple('2024-10-14')
    owner,_=p._cash_owner();cal=pd.bdate_range('2024-11-01','2024-11-15')
    for record in ('2024-11-08','2024-11-11','2024-11-12'):
        assert owner.normal_cash_ex_date(record,cal,scope_end_exclusive='2026-01-01')==p.cash.normal_cash_ex_date(record,cal,scope_end_exclusive='2026-01-01')


def test_original_prior_interval_and_separate_ex_same_uid_survive_quarter_change():
    b,f=completion_binding();b['source_profile_original_class_row']['effective_end']='2024-02-28'
    assert p._completion_clock(b,f)  # ex2/29 proof separately has the identical dated UID/SID.
    b['source_profile_original_class_row']['effective_end']='2024-02-27'
    with pytest.raises(ValueError):p._completion_clock(b,f)

def test_old_static_class_rejection_never_enters_new_profile_witness():
    assert not p._completion_listed_class(dict(sec_cash_statement_profile=p.OLD_STATIC,original_frozen_class_literal='CL A'),{})


def aapl_cns_source_fixture():
    key=dict(ticker='AAPL',effective_date='2024-11-08',reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY')
    f=dict(ticker='AAPL',sec_filer_cik=320193,security_type='COMMON_STOCK',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,record_date='2024-11-11',pay_date='2024-11-14',ex_date_provenance_role=p.cash.NSCC_CNS_RECORD_RESEARCH_ROLE,security_id='FROZEN_RAW_TRANSPORT_CODE:US.AAPL',exact_frozen_event_key=key,issuer_source_fingerprint='a'*64,identity_source_fingerprint='b'*64)
    transport=dict(schema='STATIC_SEC_SAME_ACCESSION_PARENT_AND_EX99_TRANSPORT_V1',accession=p.AAPL_CNS_STATIC_SCOPE['accession'],issuer_CIK=320193,original_submission_ref=dict(sha256=p.AAPL_CNS_STATIC_SCOPE['full_submission_sha256']),unit_basis='ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION',share_quantity_effect=False,source_publication_not_press_dateline=True,accepted_at_utc='2024-10-31T20:30:25Z')
    raw=dict(same_dated_UID_and_SID=True,accounting_sid=f['security_id'],source_coordinate='RAW_ACTUAL_SHARE',ticker='AAPL',ex_date='2024-11-08',new_legal_CUSIP_authority=False,share_quantity_effect=False)
    cns=dict(p._cns_tuple('2024-11-11'));cns.update(published_record_date='2024-11-11',ticker='AAPL',security_id=f['security_id'],exact_original_frozen_event_key=key,notice_source_ref=dict(sha256=cns.pop('notice_sha256')),notice_section_ref=dict(sha256=cns.pop('section_sha256')),notice_section_source_sha256=p._cns_tuple('2024-11-11')['notice_sha256'],issuer_record_source_ref=dict(sha256='a'*64),security_identity_source_ref=dict(sha256='b'*64),available_at=None,actual_exchange_ex_authority='UNKNOWN',strict_PIT=False,published_record_preserved=True)
    f['cns_bank_holiday_record_binding']=cns
    payload=dict(cns_static_common_opt_in=dict(scope=copy.deepcopy(p.AAPL_CNS_STATIC_SCOPE),owner_ref=p._ref(p.__file__),base_owner_ref=p.BASE_SOURCE_REF),sec_cash_statement_profile=p.OLD_STATIC,sec_source_transport_profile=p._base().SEC_STATIC_SUBMISSION_PROFILE)
    return payload,dict(original_unsupported_keys=[key]),f,transport,raw

def test_exact_aapl_cns_static_witness_keeps_generic_common_and_published_record():
    args=aapl_cns_source_fixture();assert p._cns_common_source_role(*args)==p.cash.NSCC_CNS_RECORD_RESEARCH_ROLE
    assert args[2]['record_date']=='2024-11-11' and args[0]['sec_cash_statement_profile']==p.OLD_STATIC
    owner,a=p._owner();assert a['_sec_primary_html_cash_terms']['cns_source_role']==1 and a['bind_source_account_descendant']==dict(cns_native_static=1)

@pytest.mark.parametrize('kind',['ticker','stockclass','record','pay','submission','futureacceptance','rawsid','noticehash','owner','claim'])
def test_cns_static_full_proof_mismatch_is_blocked(kind):
    payload,entry,f,tr,raw=aapl_cns_source_fixture()
    if kind=='ticker':f['ticker']='OTHER'
    elif kind=='stockclass':f['security_type']='PREFERRED_STOCK'
    elif kind=='record':f['record_date']='2024-11-08'
    elif kind=='pay':f['pay_date']='2024-11-15'
    elif kind=='submission':tr['original_submission_ref']['sha256']='c'*64
    elif kind=='futureacceptance':tr['accepted_at_utc']='2024-11-08T15:00:00Z'
    elif kind=='rawsid':raw['accounting_sid']='OTHER'
    elif kind=='noticehash':f['cns_bank_holiday_record_binding']['notice_source_ref']['sha256']='c'*64
    elif kind=='owner':payload['cns_static_common_opt_in']['owner_ref']={}
    elif kind=='claim':f['cns_bank_holiday_record_binding']['strict_PIT']=True
    with pytest.raises(ValueError):p._cns_common_source_role(payload,entry,f,tr,raw)

def test_static_without_explicit_cns_witness_retains_original_normal_role():
    assert p._cns_common_source_role({},None,None,None,None)=='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY'
    assert p._cns_native_static_allowed({},None) is False


def test_cns_static_pre_parser_dispatch_is_not_source_qualification():
    payload,entry,f,tr,raw=aapl_cns_source_fixture();assert p._cns_static_entry_allowed(payload,entry,f)
    _,a=p._owner();assert a['_sec_frozen_cash_terms']==dict(cns_static_entry_dispatch=1,qsr_exact_subject_jurisdiction=1)
    for kind in ('owner','scope','profile','ticker','record','key'):
        pp,ee,ff=copy.deepcopy((payload,entry,f))
        if kind=='owner':pp['cns_static_common_opt_in']['owner_ref']={}
        elif kind=='scope':pp['cns_static_common_opt_in']['scope']={}
        elif kind=='profile':pp['sec_cash_statement_profile']='OTHER'
        elif kind=='ticker':ff['ticker']='OTHER'
        elif kind=='record':ff['record_date']='2024-11-08'
        else:ee['original_unsupported_keys']=[]
        assert p._cns_static_entry_allowed(pp,ee,ff) is False
    tr['original_submission_ref']['sha256']='c'*64
    with pytest.raises(ValueError):p._cns_common_source_role(payload,entry,f,tr,raw)


def test_native_cns_consumes_original_opt_in_and_separate_validated_terms():
    original,entry,f,tr,raw=aapl_cns_source_fixture()
    terms=dict(historical_ex_adjudication_input=f,sec_frozen_cash_binding=dict(ex_coordinate_role=p.cash.NSCC_CNS_RECORD_RESEARCH_ROLE,static_submission_transport_proof=tr,static_submission_dated_raw_identity_proof=raw))
    assert p._cns_native_static_allowed(original,entry,terms)
    assert not p._cns_native_static_allowed({},entry,terms)
    bad=copy.deepcopy(terms);bad['sec_frozen_cash_binding']['ex_coordinate_role']='NORMAL'
    assert not p._cns_native_static_allowed(original,entry,bad)


CVX_R8="The company's Board of Directors declared an 8 percent increase in the quarterly dividend to one dollar and sixty-three cents ($1.63) per share, payable March 11, 2024, to all holders of common stock as shown on the transfer records of the corporation at the close of business on February 16, 2024."
VISA_R8="On January 23, 2024, the Company's board of directors declared a quarterly cash dividend in the amount of $0.520 per share of class A common stock (determined in the case of class B-1 and C common stock and series A, B and C convertible participating preferred stock on an as-converted basis), payable on March 1, 2024, to all holders of record as of February 9, 2024."

def test_r8_worded_amount_and_transfer_records_are_original_roles():
    f=facts(1.63,'2024-02-16','2024-03-11')
    z=p.statement_semantics(p.WORDED_TRANSFER_RECORD,CVX_R8,f,'2024-02-02')
    assert z['selected_current_amount']=='1.63' and z['increase_percent_literal']=='8'
    assert z['record_role']=='ISSUER_COMMON_HOLDERS_ON_TRANSFER_RECORDS_AT_CLOSE_OF_BUSINESS'
    assert z['prior_amount_reconstructed'] is False and z['original_text_not_rewritten']
    assert z['amount_roles'][0]['worded_amount_literal']=='one dollar and sixty-three cents'

@pytest.mark.parametrize('text',[CVX_R8.replace('sixty-three','sixty-four'),CVX_R8.replace('$1.63','$1.62'),CVX_R8+' Another dividend is $0.50 a share.',CVX_R8.replace('common stock','preferred stock'),CVX_R8.replace('transfer records','record'),CVX_R8.replace('quarterly','annual'),CVX_R8+' Another dividend of two dollars will be paid.',CVX_R8.replace('February 16, 2024','February 17, 2024')])
def test_r8_worded_amount_unknowns_comparisons_and_record_conflicts_fail(text):
    with pytest.raises(ValueError):p.statement_semantics(p.WORDED_TRANSFER_RECORD,text,facts(1.63,'2024-02-16','2024-03-11'),'2024-02-02')

def test_r8_class_a_cash_retains_other_class_context_without_authority():
    z=p.statement_semantics(p.CLASS_A_CONVERSION_CONTEXT,VISA_R8,facts(.52,'2024-02-09','2024-03-01'),'2024-01-25',listed_common_class='A')
    assert z['certified_cash_share_classes']==['A'] and z['other_class_cash_or_quantity_inferred'] is False
    assert 'class B-1 and C' in z['other_class_context_literal']
    assert len(z['amount_roles'])==1 and z['amount_roles'][0]['share_class']=='A'
    t=VISA_R8.replace('class B-1 and C common stock and series A, B and C convertible participating preferred stock','all other outstanding common and preferred stock')
    assert p.statement_semantics(p.CLASS_A_CONVERSION_CONTEXT,t,facts(.52,'2024-02-09','2024-03-01'),'2024-01-25',listed_common_class='A')['selected_current_amount']=='0.520'

@pytest.mark.parametrize('text,listed',[(VISA_R8,None),(VISA_R8,'B'),(VISA_R8.replace('per share of class A','per share of class B'),'A'),(VISA_R8.replace('on an as-converted basis','at a one-for-three conversion'),'A'),(VISA_R8+' Another quarterly dividend is $0.30 per share.','A'),(VISA_R8.replace('class B-1 and C','class D and C'),'A'),(VISA_R8.replace('$0.520','$0.530'),'A')])
def test_r8_class_a_does_not_borrow_other_class_amount_or_quantity(text,listed):
    with pytest.raises(ValueError):p.statement_semantics(p.CLASS_A_CONVERSION_CONTEXT,text,facts(.52,'2024-02-09','2024-03-01'),'2024-01-25',listed_common_class=listed)

def test_r8_original_com_class_a_row_is_retained_separate_from_cover(tmp_path):
    row=dict(ticker='V',cusip='92826C839',title_of_class='COM CL A',effective_start='2024-01-01',effective_end='2024-12-31')
    file=tmp_path/'r8_generated_identity.json';file.write_text(json.dumps(dict(rows=[dict(original_source_row=row)])))
    payload=dict(sec_cash_statement_profile=p.CLASS_A_CONVERSION_CONTEXT,sec_source_transport_profile=p._base().SEC_STATIC_SUBMISSION_PROFILE,frozen_account_identity_ref=dict(path=str(file)),same_file_cash_identity_support_ref={'role':'generated_same_submission'})
    entry=dict(prior_raw_close=dict(prior_date='2024-02-07'));f=dict(ticker='V')
    witness=p._class_binding(payload,entry,f,'Class A Common Stock V New York Stock Exchange','Visa Inc.',lambda r:Path(r['path']))
    assert p._class_allowed(payload,entry,f,row,witness) and witness['original_frozen_class_literal']=='COM CL A'
    assert p._subject_class(p.CLASS_A_CONVERSION_CONTEXT,payload,row,'Class A Common Stock V New York Stock Exchange')
    assert not p._subject_class(p.EXACT_COMMON_CLASS,payload,row,'Class A Common Stock V New York Stock Exchange')
    assert not p._class_allowed(payload,entry,f,row,dict(witness))
    with pytest.raises(ValueError):p._class_binding(payload,entry,f,'Class B Common Stock V New York Stock Exchange','Visa Inc.',lambda r:Path(r['path']))
    row['title_of_class']='CL A';assert not p._class_allowed(payload,entry,f,row,witness)

def test_r8_private_cash_clock_needs_original_uid_and_class_a_exact_witness():
    b,f=completion_binding();b['sec_cash_statement_profile']=p.CLASS_A_CONVERSION_CONTEXT;b['selected_original_cash_statement']=VISA_R8;b['source_unique_listed_common_class']='A';b['original_frozen_class_literal']='COM CL A';b['source_profile_original_class_row']['title_of_class']='COM CL A'
    f.update(cash_per_raw_share=.52,record_date='2024-02-09',pay_date='2024-03-01')
    b['source_statement_date']='2024-01-25';b['source_profile_completion']=p.statement_semantics(p.CLASS_A_CONVERSION_CONTEXT,VISA_R8,f,'2024-01-25',listed_common_class='A')
    assert p._completion_clock(b,f) and p._completion_listed_class(b,f)
    wrong=copy.deepcopy(b);wrong['source_profile_original_class_row']['cusip']='999999999'
    with pytest.raises(ValueError):p._completion_clock(wrong,f)
    wrong=copy.deepcopy(b);wrong['source_profile_completion']['other_class_cash_or_quantity_inferred']=True
    with pytest.raises(ValueError):p._completion_clock(wrong,f)

def test_r8_old_profile_literal_and_normal_cash_owner_stay_unchanged():
    with pytest.raises(ValueError):p.statement_semantics(p.EXACT_COMMON_CLASS,VISA_R8,facts(.52,'2024-02-09','2024-03-01'),'2024-01-25',listed_common_class='A')
    with pytest.raises(ValueError):p._base()._static_submission_cash_statement(CVX_R8,facts(1.63,'2024-02-16','2024-03-11'),'2024-02-02')
    private,proof=p._cash_owner()
    assert private.normal_cash_ex_date.__code__.co_code==p.cash.normal_cash_ex_date.__code__.co_code
    assert proof['adjudicate_post_verified_cash_ex']==dict(roles=1,witness=1,static_profile=2,listed_class=1,qsr_exact_cash_jurisdiction=1,qsr_exact_cash_currency_basis=1)


META_R9="On February 1, 2024, Meta's board of directors declared a cash dividend of $0.50 per share of its outstanding Class A common stock and Class B common stock, payable on March 26, 2024 to stockholders of record as of the close of business on February 22, 2024."

def meta_facts():return dict(ticker='META',cash_per_raw_share=.5,record_date='2024-02-22',pay_date='2024-03-26')

def test_r9_original_same_cash_amount_for_named_classes_keeps_one_target():
    z=p.statement_semantics(p.EQUAL_NAMED_COMMON_CLASSES,META_R9,meta_facts(),'2024-02-01',listed_common_class='A')
    assert z['certified_source_cash_share_classes']==['A','B'] and z['certified_accounting_cash_share_classes']==['A']
    assert len(z['amount_roles'])==1 and not z['other_class_cash_or_quantity_inferred'] and not z['other_class_account_position_created']
    assert z['real_original_source_proof_ref']['sha256']=='5ccff76529b17b58dbefe44a4adedc1c74b818442ad37e44e6989865be8fd24c'
    for profile in (p.CLASS_A_CONVERSION_CONTEXT,p.EXACT_COMMON_CLASS):
        with pytest.raises(ValueError):p.statement_semantics(profile,META_R9,meta_facts(),'2024-02-01',listed_common_class='A')

@pytest.mark.parametrize('text,listed',[(META_R9,'B'),(META_R9,None),(META_R9.replace('Class B common stock','Class B preferred stock'),'A'),(META_R9.replace('Class B common stock','Class C common stock'),'A'),(META_R9.replace('Class B common stock','Class B common stock on an as-converted basis'),'A'),(META_R9+' Class B is paid $0.20 per share.','A'),(META_R9.replace('$0.50','$0.51'),'A'),(META_R9.replace('February 22, 2024','February 23, 2024'),'A')])
def test_r9_class_money_date_and_unit_changes_do_not_pass(text,listed):
    with pytest.raises(ValueError):p.statement_semantics(p.EQUAL_NAMED_COMMON_CLASSES,text,meta_facts(),'2024-02-01',listed_common_class=listed)

def test_r9_class_a_witness_keeps_exact_old_cusip_and_single_listing(tmp_path):
    row=dict(ticker='META',cusip='30303M102',title_of_class='CL A',effective_start='2024-01-01',effective_end='2024-12-31');file=tmp_path/'r9_generated_identity.json';file.write_text(json.dumps(dict(rows=[dict(original_source_row=row)])))
    payload=dict(sec_cash_statement_profile=p.EQUAL_NAMED_COMMON_CLASSES,sec_source_transport_profile=p._base().SEC_STATIC_SUBMISSION_PROFILE,frozen_account_identity_ref=dict(path=str(file)),same_file_cash_identity_support_ref={'role':'generated'})
    entry=dict(prior_raw_close=dict(prior_date='2024-02-20'));f=dict(ticker='META');w=p._class_binding(payload,entry,f,'Class A Common Stock META Nasdaq Global Select Market','Meta Platforms Inc.',lambda r:Path(r['path']))
    assert p._class_allowed(payload,entry,f,row,w) and row['title_of_class']=='CL A'
    with pytest.raises(ValueError):p._class_binding(payload,entry,f,'Class A Common Stock META Nasdaq Class B Common Stock','Meta Platforms Inc.',lambda r:Path(r['path']))
    row['cusip']='999999999';file.write_text(json.dumps(dict(rows=[dict(original_source_row=row)])))
    with pytest.raises(ValueError):p._class_binding(payload,entry,f,'Class A Common Stock META Nasdaq Global Select Market','Meta Platforms Inc.',lambda r:Path(r['path']))

def test_r9_cash_clock_needs_actual_static_source_and_original_raw_cusip():
    b,f=completion_binding();src=p.META_NAMED_COMMON_SCOPE;b['sec_cash_statement_profile']=p.EQUAL_NAMED_COMMON_CLASSES;b['selected_original_cash_statement']=META_R9;b['source_unique_listed_common_class']='A';b['original_frozen_class_literal']='CL A';b['source_profile_original_class_row'].update(ticker='META',title_of_class='CL A',cusip=src['original_CUSIP'],security_id=src['original_CUSIP']);b['original_frozen_raw_CUSIP']=src['original_CUSIP'];b['sec_filer_cik']=1326801
    f.update(meta_facts());f['security_id']=src['raw_accounting_sid'];b['static_submission_dated_raw_identity_proof'].update(ticker='META',security_uid='CUSIP:'+src['original_CUSIP'],accounting_sid=src['raw_accounting_sid'],prior_date=src['prior_date'],ex_date=src['ex_date']);b['source_statement_date']='2024-02-01';b['static_submission_transport_proof']=dict(original_submission_ref=src['full_submission_ref'],accepted_at_utc=src['actual_accepted_at_utc']);b['source_profile_completion']=p.statement_semantics(p.EQUAL_NAMED_COMMON_CLASSES,META_R9,f,'2024-02-01',listed_common_class='A')
    assert p._completion_clock(b,f) and p._completion_listed_class(b,f)
    for key,val in [('sec_filer_cik',999),('static_submission_transport_proof',dict(original_submission_ref={'path':'wrong','sha256':'0'*64},accepted_at_utc=src['actual_accepted_at_utc']))]:
        wrong=copy.deepcopy(b);wrong[key]=val
        with pytest.raises(ValueError):p._completion_clock(wrong,f)
    wrong=copy.deepcopy(b);wrong['source_profile_completion']['amount_roles'][0]['source_common_classes']=['A']
    with pytest.raises(ValueError):p._completion_clock(wrong,f)


MSFT_LITERAL="Microsoft also announced its board of directors declared a quarterly dividend of $0.68 per share. The dividend is payable June 8, 2023, to shareholders of record on May 18, 2023. The ex-dividend date will be May 17, 2023."

def msft_generated_source(tmp_path,monkeypatch,*,unit_markup=None,unit_link='USD_SHARE',published='2023-03-14T21:51:45+00:00',capture='2023-03-14T21:56:09Z',cusip='594918104',class_literal='COM',amount='0.68',row_current_amount='9.99',literal=MSFT_LITERAL):
    import hashlib
    def write(name,data):
        q=tmp_path/name;q.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode());return dict(path=str(q),sha256=hashlib.sha256(q.read_bytes()).hexdigest())
    unit_markup=unit_markup or '<xbrli:unit id="USD_SHARE"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    row=f'<tr><td>Cash dividends declared per common share</td><td><ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="{unit_link}">{row_current_amount}</ix:nonFraction></td></tr>'.encode()
    capital=unit_markup.encode()+b'\n'+row;capref=write('capital.htm',capital);rowref=write('row.opaque',row)
    unit=dict(id='USD_SHARE',byte_start=0,byte_end=len(unit_markup.encode()),original_unit_markup=unit_markup)
    h=write('SEC_header.txt',b'<ACCEPTANCE-DATETIME>20230425160743\nACCESSION NUMBER: 0000950170-23-014423\nCENTRAL INDEX KEY: 789019\nCONFORMED SUBMISSION TYPE: 10-Q\n')
    entry=dict(identity_binding=dict(issuer='MICROSOFT CORP',ticker='MSFT',listing_identity='NASDAQ:MSFT'),prior_raw_close=dict(prior_date='2023-05-16'))
    e=dict(ticker='MSFT',effective_date='2023-05-17',issuer_name_original='Microsoft Corp.',source_published_metadata_utc=published,original_version_available_no_later_than=capture,original_frozen_prior_row=dict(title_of_class=class_literal,cusip=cusip,security_id=cusip,issuer_name='MICROSOFT CORP'),original_frozen_prior_date='2023-05-16',ex_and_prior_RAW_identity=dict(same_dated_cusip_and_accounting_sid=True),original_announcement_cash_or_common_words_added=False,source_available_at_for_engine=None,model_or_label_input_authority_granted=False,issuer_CIK_not_security_UID=True,new_CUSIP_or_ticker_identity_invented=False,independent_cash_common_class_basis=dict(accepted_at_utc='2023-04-25T20:07:43+00:00',accepted_header_ref=h,source_form='10-Q',accession='0000950170-23-014423',source_document_ref=capref,capital_fragment_ref=rowref,capital_fragment_byte_range=[len(unit_markup.encode())+1,len(capital)],original_capital_row_literal='Cash dividends declared per common share '+row_current_amount,USD_per_common_share_unit_metadata=[unit],current_event_dividend_amount_from_capital_row=False),declaration_literal=literal,declaration_literal_sha256=hashlib.sha256(literal.encode()).hexdigest(),declared_amount_literal=amount,issuer_record_date='2023-05-18',announced_pay_date='2023-06-08',issuer_announced_ex_dividend_date='2023-05-17')
    mref=write('materials.json',dict(entries=[e]));scope=copy.deepcopy(p.MSFT_HTML_SIX_SCOPE);scope['material_ref']=mref;monkeypatch.setattr(p,'MSFT_HTML_SIX_SCOPE',scope)
    support=dict(schema=p.MSFT_UNIT_SUPPORT_SCHEMA,scope=scope,source_material_ref=mref,ex_date='2023-05-17',ticker='MSFT',original_CUSIP=cusip,source_material_event_fingerprint=p._base()._hash(e))
    paragraph=('<p>'+literal+'</p>').encode();head=b'2023-03-14';body=head+b'\n'+paragraph;full=write('article.html',body);full['bytes']=len(body);hr=write('head.opaque',head);pr=write('paragraph.opaque',paragraph)
    source=dict(schema_version='B_HISTORICAL_PRIMARY_SOURCE_CAPTURE_V1',source_sec_same_file_submission_header_claim=False,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,http_status=200,received_http_bytes_sha256=full['sha256'],received_bytes=len(body),source_url='https://news.microsoft.com/2023/03/14/generated-test-only/',historical_availability_status='UNKNOWN',original_http_bytes_ref=full,publication_date_expected_from_original_dated_source='2023-03-14',retrieval_timestamp_utc=capture,dated_header_observations=[dict(fragment_ref=hr,original_byte_range=[0,len(head)],literal=head.decode())],cash_fragments=[dict(fragment_ref=pr,original_byte_range=[len(head)+1,len(body)],visible_text=literal,visible_text_utf8_sha256=hashlib.sha256(literal.encode()).hexdigest())])
    return entry,support,source,lambda r:Path(r['path'])

def test_msft_r10_real_unit_direction_and_article_amount_are_separate(tmp_path,monkeypatch):
    entry,support,source,pin=msft_generated_source(tmp_path,monkeypatch)
    binding=p._msft_common_support({},entry,support,pin);owner,anchors=p._owner()
    terms=owner._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=binding)
    assert terms['amount']==.68 and terms['currency_basis']=='EXPLICIT_USD' and terms['source_currency_explicit_USD'] is False
    assert terms['source_currency_separate_SEC_USD_unit'] and terms['source_declared_ex_date'] is None
    assert terms['issuer_observed_ex_date']=='2023-05-17' and terms['available'] is None
    assert terms['separate_common_cash_unit_available_utc']=='2023-04-25T20:07:43+00:00'
    assert len([k for k in anchors if k.startswith('msft_')])==4

@pytest.mark.parametrize('change',['reversed','CAD','two_units','wrong_link'])
def test_msft_r10_original_XBRL_unit_negatives(tmp_path,monkeypatch,change):
    good='<xbrli:unit id="USD_SHARE"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    changed=good.replace('iso4217:USD','iso4217:CAD') if change=='CAD' else good.replace('iso4217:USD','TEMP').replace('xbrli:shares','iso4217:USD').replace('TEMP','xbrli:shares') if change=='reversed' else good.replace('</xbrli:unitNumerator>','<xbrli:measure>iso4217:CAD</xbrli:measure></xbrli:unitNumerator>') if change=='two_units' else good
    e,s,source,pin=msft_generated_source(tmp_path,monkeypatch,unit_markup=changed,unit_link='WRONG' if change=='wrong_link' else 'USD_SHARE')
    with pytest.raises(ValueError):p._msft_common_support({},e,s,pin)

@pytest.mark.parametrize('kwargs',[dict(cusip='111111111'),dict(class_literal='CL A'),dict(published='2023-05-17T14:00:00Z'),dict(capture='2023-05-17T14:00:00Z')])
def test_msft_r10_original_UID_class_and_clock_negatives(tmp_path,monkeypatch,kwargs):
    e,s,source,pin=msft_generated_source(tmp_path,monkeypatch,**kwargs)
    with pytest.raises(ValueError):p._msft_common_support({},e,s,pin)

def test_msft_r10_article_must_match_current_amount_and_exact_cash_clause(tmp_path,monkeypatch):
    e,s,source,pin=msft_generated_source(tmp_path,monkeypatch,amount='.67');b=p._msft_common_support({},e,s,pin)
    with pytest.raises(ValueError,match='ORIGINAL_AMOUNT'):p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b)

def test_msft_r10_cannot_supply_plain_dict_or_mutate_materials(tmp_path,monkeypatch):
    e,s,source,pin=msft_generated_source(tmp_path,monkeypatch);b=p._msft_common_support({},e,s,pin)
    with pytest.raises(ValueError):p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=dict(b))
    s['source_material_event_fingerprint']='changed'
    with pytest.raises(ValueError):p._msft_common_support({},e,s,pin)

def test_msft_r10_default_article_profile_outcome_is_unchanged(tmp_path,monkeypatch):
    e,s,source,pin=msft_generated_source(tmp_path,monkeypatch)
    def result(f):
        try:return ('OK',f(source,pinned=pin))
        except Exception as exc:return (type(exc).__name__,str(exc))
    assert result(p._base()._original_dated_common_cash_terms)==result(p._owner()[0]._original_dated_common_cash_terms)

def test_msft_r10_new_RAW_bridge_never_relabels_V38_or_other_UID():
    b=dict(schema='MSFT_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R10',scope=p.MSFT_HTML_SIX_SCOPE,ticker='MSFT',ex_date='2023-05-17',security_uid='CUSIP:594918104',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.MSFT',source_owner_ref=p._ref(p.__file__))
    assert p._msft_raw_bridge_allowed(b)
    for k,v in [('ticker','OTHER'),('security_uid','CUSIP:000000000'),('ex_date','2026-01-01'),('source_owner_ref',{'path':'fake','sha256':'fake'})]:
        changed=copy.deepcopy(b);changed[k]=v;assert not p._msft_raw_bridge_allowed(changed)
    assert p._msft_raw_bridge_allowed(dict(schema='V38_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R1'))


def test_msft_r10_unicode_digest_obeys_declared_original_UTF8_json_recipe(tmp_path,monkeypatch):
    import hashlib
    literal='REDMOND, Wash. — '+MSFT_LITERAL
    entry,support,source,pin=msft_generated_source(tmp_path,monkeypatch,literal=literal)
    b=p._msft_common_support({},entry,support,pin);terms=p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b)
    expected=hashlib.sha256(json.dumps(literal,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert terms['source_paragraph']==literal and terms['source_original_typed_text_digest']==expected
    assert terms['source_original_typed_text_digest_recipe']=='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT'
    assert expected!=p._base()._hash(literal)


HON_2024="CHARLOTTE, N.C. , Sept. 27, 2024 /PRNewswire/ -- Honeywell ( NASDAQ: HON ) today announced that its Board of Directors has approved an increase in the company's regular annual cash dividend from $4.32 to $4.52 per share. The increase will be effective starting with the fourth-quarter dividend of $1.13 per share, which was declared today, and is payable on December 6, 2024 , out of surplus to holders of record at the close of business on November 15, 2024 ."
HON_2025="CHARLOTTE, N.C., Feb. 14, 2025 /PRNewswire/ -- Honeywell International Inc. (NASDAQ: HON) today announced that its Board of Directors has declared a quarterly dividend payment of $1.13 per share on the Company's common stock. The dividend is payable on March 14, 2025, out of surplus to holders of record at the close of business on February 28, 2025."

def hon_generated_source(tmp_path,monkeypatch,*,year=2024,literal=None,current='1.13',class_literal='COM',first_pub=None,capture=None,unit_currency='USD',concept='us-gaap:CommonStockDividendsPerShareCashPaid'):
    import hashlib
    def write(name,value):
        q=tmp_path/name;q.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());return dict(path=str(q),sha256=hashlib.sha256(q.read_bytes()).hexdigest())
    ex='2024-11-15' if year==2024 else '2025-02-28';prior='2024-11-14' if year==2024 else '2025-02-27';pub='2024-09-27' if year==2024 else '2025-02-14';record=ex;pay='2024-12-06' if year==2024 else '2025-03-14';capture=capture or ('2024-10-08T22:23:41+00:00' if year==2024 else '2025-02-14T17:19:20+00:00');literal=literal or (HON_2024 if year==2024 else HON_2025)
    markup=f'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:{unit_currency}</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';row=f'<tr><td>Cash dividends per share of common stock</td><td><ix:nonFraction name="{concept}" unitRef="usdPerShare">9.99</ix:nonFraction></td></tr>'.encode();raw=markup.encode()+b'\n'+row;doc=write('hon_SEC.htm',raw);rr=write('hon_unit_row.opaque',row);h=write('hon_HEADER.txt',b'<ACCEPTANCE-DATETIME>20241024093757\nACCESSION NUMBER: 0000773840-24-000099\nCENTRAL INDEX KEY: 773840\nCONFORMED SUBMISSION TYPE: 10-Q\n')
    unit=dict(issuer_cik=773840,common_stock_XBRL_concept=concept,accepted_at_utc='2024-10-24T13:37:57+00:00',accepted_header_ref=h,source_form='10-Q',accession='0000773840-24-000099',source_document_ref=doc,capital_fragment_ref=rr,capital_fragment_byte_range=[len(markup.encode())+1,len(raw)],original_capital_row_literal='Cash dividends per share of common stock 9.99',USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=0,byte_end=len(markup.encode()),original_unit_markup=markup)],exact_current_event_dividend_amount_from_capital_row=False,current_event_payment_from_financial_paid_row=False)
    e=dict(ticker='HON',effective_date=ex,source_displayed_publication_date=pub,publicly_available_no_later_than=capture,independent_common_cash_USD_share_basis=unit,actual_first_publication_at=first_pub,actual_first_publication_timestamp_status='UNKNOWN',source_available_at_for_engine=None,source_engine_availability_role='CONSERVATIVE_EXACT_PREEX_ARCHIVE_AVAILABILITY_NOT_FIRST_PUBLICATION_CERTIFICATE',original_literal_rewritten=False,current_amount_annualized_divided_or_inferred=False,financial_CommonStockCashPaid_row_not_current_event_amount_or_payment=True,prior_dated_original_frozen_row=dict(prior_date=prior,original_frozen_prior_row=dict(title_of_class=class_literal,security_id='438516106',cusip='438516106',issuer_name='HONEYWELL INTL INC')),prior_and_ex_RAW_metadata=dict(same_dated_cusip_and_accounting_sid=True,ex_identity=dict(security_uid='CUSIP:438516106',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.HON'),prior_identity=dict(security_uid='CUSIP:438516106',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.HON')),declaration_literal=literal,declaration_literal_sha256=hashlib.sha256(literal.encode()).hexdigest(),explicit_current_quarter_amount_literal=current,comparative_amount_roles=[dict(amount_literal='4.32',role='PREVIOUS_REGULAR_ANNUAL_CASH_RATE_NOT_CURRENT_QUARTER_AMOUNT'),dict(amount_literal='4.52',role='NEW_REGULAR_ANNUAL_CASH_RATE_NOT_CURRENT_QUARTER_AMOUNT')] if year==2024 else [],announced_pay_date=pay,issuer_record_date=record)
    mr=write('hon_material.json',dict(entries=[e]));scope=copy.deepcopy(p.HON_HTML_TWO_SCOPE);scope['material_ref']=mr;monkeypatch.setattr(p,'HON_HTML_TWO_SCOPE',scope);support=dict(schema=p.HON_UNIT_SUPPORT_SCHEMA,scope=scope,source_material_ref=mr,ex_date=ex,ticker='HON',source_material_event_fingerprint=p._base()._hash(e));entry=dict(identity_binding=dict(issuer='HONEYWELL INTL INC',ticker='HON',listing_identity='NASDAQ:HON'),prior_raw_close=dict(prior_date=prior))
    paragraph=('<p>'+literal+'</p>').encode();head=pd.Timestamp(pub).strftime('%B %d, %Y').replace(' 0',' ').encode();body=head+b'\n'+paragraph;full=write('hon_article.html',body);full['bytes']=len(body);hr=write('hon_head.opaque',head);fr=write('hon_cash.opaque',paragraph);source=dict(schema_version='B_HISTORICAL_PRIMARY_SOURCE_CAPTURE_V1',capture_profile='DATED_ISSUER_PRIMARY_HTML_BOUNDED_CASH_AND_DATED_HEADER_ORIGINAL_HTTP_FRAGMENTS',strict_pit_qualified=False,quote_qualified=False,certified_nav_qualified=False,http_status=200,received_http_bytes_sha256=full['sha256'],received_bytes=len(body),source_url='https://www.honeywell.com/generated-historical-test-only/',historical_availability_status='UNKNOWN',original_http_bytes_ref=full,retrieval_timestamp_utc=capture,publication_date_expected_from_original_dated_source=pub,dated_header_observations=[dict(fragment_ref=hr,original_byte_range=[0,len(head)],literal=head.decode())],cash_fragments=[dict(fragment_ref=fr,original_byte_range=[len(head)+1,len(body)],visible_text=literal,visible_text_utf8_sha256=hashlib.sha256(literal.encode()).hexdigest())])
    return entry,support,source,lambda r:Path(r['path'])

@pytest.mark.parametrize('year',[2024,2025])
def test_hon_r11_original_current_quarter_only_and_UNKNOWN_clock(tmp_path,monkeypatch,year):
    e,s,source,pin=hon_generated_source(tmp_path,monkeypatch,year=year);b=p._hon_common_support({},e,s,pin);owner=p._owner()[0];r=owner._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b)
    assert r['amount']==1.13 and r['available'] is None and r['actual_first_publication_at'] is None and r['actual_first_publication_authority']=='UNKNOWN'
    assert r['annual_rate_division_or_inference'] is False and r['current_amount_from_capital_statement'] is False
    assert [a['amount_literal'] for a in r['amount_roles']]==(['4.32','4.52','1.13'] if year==2024 else ['1.13'])
    with pytest.raises(ValueError,match='UNIQUE_DECLARED_COMMON_CASH'):p._base()._original_dated_common_cash_terms(source,pinned=pin)

@pytest.mark.parametrize('kwargs',[dict(current='4.52'),dict(literal=HON_2024.replace('$4.32','$4.31')),dict(literal=HON_2024+' Another payment is $0.50 per share.'),dict(literal=HON_2024.replace('which was declared today','which may be proposed later')),dict(year=2025,literal=HON_2025.replace("Company's common stock","Company's preferred stock"))])
def test_hon_r11_all_money_roles_and_source_statement_negatives(tmp_path,monkeypatch,kwargs):
    e,s,source,pin=hon_generated_source(tmp_path,monkeypatch,**kwargs);b=p._hon_common_support({},e,s,pin)
    with pytest.raises(ValueError):p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b)

@pytest.mark.parametrize('kwargs',[dict(class_literal='CL A'),dict(first_pub='2024-09-27T12:00:00Z'),dict(capture='2024-11-15T15:00:00Z'),dict(unit_currency='CAD'),dict(concept='us-gaap:CommonStockDividendsPerShareDeclared')])
def test_hon_r11_class_unit_and_no_false_first_publication(tmp_path,monkeypatch,kwargs):
    e,s,source,pin=hon_generated_source(tmp_path,monkeypatch,**kwargs)
    with pytest.raises(ValueError):p._hon_common_support({},e,s,pin)


CSX_INCREASE="JACKSONVILLE, Fla. – February 14, 2024 – CSX Corp. (NASDAQ: CSX) announced that the Company’s Board of Directors approved a nine percent increase in its quarterly dividend, from $0.11 to $0.12 per share. The new $0.12 quarterly dividend is payable on March 15, 2024, to shareholders of record at the close of business on February 29, 2024."

def csx_generated_source(tmp_path,monkeypatch,*,ex='2024-02-28',literal=None,first_pub=None,capture=None,currency='USD',concept='us-gaap:CommonStockDividendsPerShareCashPaid',class_literal='COM',sid='FROZEN_RAW_TRANSPORT_CODE:US.CSX'):
    import hashlib
    def write(name,value):
        q=tmp_path/name;q.write_bytes(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode());return dict(path=str(q),sha256=hashlib.sha256(q.read_bytes()).hexdigest())
    data={'2024-02-28':('2024-02-14','2024-02-27','February 29, 2024','March 15, 2024','0.12'),'2024-08-30':('2024-07-10','2024-08-29','August 30, 2024','September 13, 2024','0.12'),'2024-11-29':('2024-10-03','2024-11-27','November 29, 2024','December 13, 2024','0.12'),'2025-05-30':('2025-05-07','2025-05-29','May 30, 2025','June 13, 2025','0.13')};pub,prior,record,pay,amount=data[ex];capture=capture or str(pd.Timestamp(pub,tz='UTC')+pd.Timedelta(days=1));date=pd.Timestamp(pub).strftime('%B %d, %Y').replace(' 0',' ')
    literal=literal or (CSX_INCREASE if ex=='2024-02-28' else f'JACKSONVILLE, Fla. – {date} – CSX Corp. (NASDAQ: CSX) announced that the Company’s Board of Directors approved a ${amount} per share quarterly dividend on the Company’s common stock. The dividend is payable on {pay}, to shareholders of record at the close of business on {record}.')
    markup=f'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:{currency}</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';row_class="Common Stock Dividends," if ex=="2025-05-30" else "Common stock dividends,";row=f'<tr><td>{row_class}$ </td><td><ix:nonFraction name="{concept}" unitRef="usdPerShare">9.99</ix:nonFraction></td><td> per share</td></tr>'.encode();raw=markup.encode()+b'\n'+row;doc=write('csx_SEC.htm',raw);rr=write('csx_unit_row.opaque',row);h=write('csx_HEADER.txt',b'<ACCEPTANCE-DATETIME>20240214100000\nACCESSION NUMBER: 0000277948-24-000010\nCENTRAL INDEX KEY: 277948\nCONFORMED SUBMISSION TYPE: 10-K\n')
    unit=dict(issuer_cik=277948,common_stock_XBRL_concept=concept,accepted_at_utc='2024-02-14T15:00:00+00:00',accepted_header_ref=h,source_form='10-K',accession='0000277948-24-000010',source_document_ref=doc,capital_fragment_ref=rr,capital_fragment_byte_range=[len(markup.encode())+1,len(raw)],original_capital_row_literal=row_class+'$ 9.99 per share',USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=0,byte_end=len(markup.encode()),original_unit_markup=markup)],exact_current_event_dividend_amount_from_capital_row=False,current_event_payment_from_financial_paid_row=False);ur=write('csx_units.json',dict(entries=[unit]))
    projection=dict(ticker='CSX',effective_date=ex,literal=literal,literal_sha256=hashlib.sha256(literal.encode()).hexdigest(),source_displayed_primary_dateline_date=pub,publicly_available_no_later_than=capture,actual_first_publication_at=first_pub,actual_first_publication_timestamp_status='UNKNOWN',source_availability_role='EXACT_PREEX_ARCHIVE_CAPTURE_CONSERVATIVE_UPPER_BOUND_NOT_FIRST_PUBLICATION_CERTIFICATE');pr=write('csx_projection.json',projection)
    e=dict(ticker='CSX',effective_date=ex,source_projection_ref=pr,source_terms_literal=literal,source_primary_dateline_date=pub,source_available_no_later_than=capture,actual_first_publication_at=first_pub,source_availability_role=projection['source_availability_role'],frozen_prior_metadata_selection=dict(prior_date=prior,original_frozen_prior_row=dict(title_of_class=class_literal,cusip='126408103',security_id='126408103',issuer_name='CSX CORP')),original_two_day_RAW_identity=dict(prior_date=prior,same_dated_cusip_and_accounting_sid=True,ex_identity=dict(security_uid='CUSIP:126408103',accounting_sid=sid),prior_identity=dict(security_uid='CUSIP:126408103',accounting_sid=sid)),common_USD_share_source_ref=ur,common_USD_share_source_entry_index=0,capital_original_header_ref=h,capital_original_source_document_ref=doc,capital_original_bounded_row_ref=rr,capital_source_accepted_at_utc=unit['accepted_at_utc'],capital_unit_usage='CLASS_AND_USD_PER_COMMON_SHARE_ONLY_NOT_CURRENT_EVENT_AMOUNT_OR_PAYMENT',issuer_record_date_literal=record,issuer_pay_date_literal=pay)
    mr=write('csx_material.json',dict(entries=[e]));scope=copy.deepcopy(p.CSX_HTML_FOUR_SCOPE);scope['material_ref']=mr;monkeypatch.setattr(p,'CSX_HTML_FOUR_SCOPE',scope);support=dict(schema=p.CSX_UNIT_SUPPORT_SCHEMA,scope=scope,source_material_ref=mr,ex_date=ex,ticker='CSX',original_CUSIP='126408103',source_material_event_fingerprint=p._base()._hash(e));entry=dict(identity_binding=dict(issuer='CSX CORP',ticker='CSX',listing_identity='NASDAQ:CSX'),prior_raw_close=dict(prior_date=prior))
    paragraph=('<p>'+literal+'</p>').encode();head=date.encode();body=head+b'\n'+paragraph;full=write('csx_article.html',body);full['bytes']=len(body);hr=write('csx_head.opaque',head);fr=write('csx_cash.opaque',paragraph);source=dict(schema_version='B_HISTORICAL_PRIMARY_SOURCE_CAPTURE_V1',capture_profile='DATED_ISSUER_PRIMARY_HTML_BOUNDED_CASH_AND_DATED_HEADER_ORIGINAL_HTTP_FRAGMENTS',strict_pit_qualified=False,quote_qualified=False,certified_nav_qualified=False,http_status=200,received_http_bytes_sha256=full['sha256'],received_bytes=len(body),source_url='https://www.csx.com/generated-historical-test-only/',historical_availability_status='UNKNOWN',original_http_bytes_ref=full,retrieval_timestamp_utc=capture,publication_date_expected_from_original_dated_source=pub,dated_header_observations=[dict(fragment_ref=hr,original_byte_range=[0,len(head)],literal=date)],cash_fragments=[dict(fragment_ref=fr,original_byte_range=[len(head)+1,len(body)],visible_text=literal,visible_text_utf8_sha256=hashlib.sha256(literal.encode()).hexdigest())],actual_first_publication_at=None,available_at=None)
    return entry,support,source,lambda r:Path(r['path'])

@pytest.mark.parametrize('ex',p.CSX_HTML_FOUR_SCOPE['exact_ex_dates'])
def test_csx_r12_four_current_original_declarations(tmp_path,monkeypatch,ex):
    e,s,source,pin=csx_generated_source(tmp_path,monkeypatch,ex=ex);b=p._csx_common_support({},e,s,pin);r=p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b)
    assert r['amount']==(0.13 if ex=='2025-05-30' else 0.12) and r['available'] is None and r['actual_first_publication_at'] is None and r['historical_availability_authority']=='UNKNOWN'
    assert r['current_amount_from_capital_statement'] is False and r['percentage_or_prior_amount_calculation'] is False and r['source_paragraph']==source['cash_fragments'][0]['visible_text']
    assert len(r['amount_roles'])==(3 if ex=='2024-02-28' else 1)
    if ex=='2024-02-28':assert [x['amount_literal'] for x in r['amount_roles']]==['0.11','0.12','0.12'] and r['original_percentage_literal']=='nine percent'

@pytest.mark.parametrize('literal',[CSX_INCREASE.replace('The new $0.12','The new $0.13'),CSX_INCREASE.replace('from $0.11','from $0.10'),CSX_INCREASE.replace('nine percent','ten percent'),CSX_INCREASE.replace('approved','proposed'),CSX_INCREASE.replace('quarterly dividend','annual dividend'),CSX_INCREASE+' A second dividend is $0.10 per share.',CSX_INCREASE.replace('March 15, 2024','March 16, 2024')])
def test_csx_r12_all_original_amount_roles_and_dates_fail_closed(tmp_path,monkeypatch,literal):
    e,s,source,pin=csx_generated_source(tmp_path,monkeypatch,literal=literal);b=p._csx_common_support({},e,s,pin)
    with pytest.raises(ValueError):p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b)

@pytest.mark.parametrize('kwargs',[dict(first_pub='2024-02-14T15:00:00Z'),dict(capture='2024-02-28T16:00:00Z'),dict(currency='CAD'),dict(concept='us-gaap:DividendsPerShare'),dict(class_literal='PREFERRED'),dict(sid='FROZEN_RAW_TRANSPORT_CODE:US.OTHER')])
def test_csx_r12_original_unit_UID_and_UNKNOWN_clock_fail_closed(tmp_path,monkeypatch,kwargs):
    e,s,source,pin=csx_generated_source(tmp_path,monkeypatch,**kwargs)
    with pytest.raises(ValueError):p._csx_common_support({},e,s,pin)

@pytest.mark.parametrize('date',['2025-02-28','2025-08-29'])
def test_csx_r12_two_unrecovered_dates_cannot_opt_in(tmp_path,monkeypatch,date):
    e,s,source,pin=csx_generated_source(tmp_path,monkeypatch);s['ex_date']=date
    with pytest.raises(ValueError):p._csx_common_support({},e,s,pin)

def test_csx_r12_no_unvalidated_dict_bypasses_source(tmp_path,monkeypatch):
    e,s,source,pin=csx_generated_source(tmp_path,monkeypatch);b=p._csx_common_support({},e,s,pin)
    with pytest.raises(ValueError):p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=dict(b))

def test_csx_r12_bridge_exact_existing_owner_and_same_RAW_sid():
    b=dict(schema='CSX_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R12',scope=p.CSX_HTML_FOUR_SCOPE,ticker='CSX',ex_date='2024-02-28',security_uid='CUSIP:126408103',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.CSX',source_owner_ref=p._ref(p.__file__))
    assert p._msft_raw_bridge_allowed(b)
    for k,v in [('ex_date','2025-02-28'),('security_uid','CUSIP:OTHER'),('accounting_sid','SOURCE_DERIVED_ISSUER:CSX'),('source_owner_ref',{})]:
        changed=copy.deepcopy(b);changed[k]=v;assert not p._msft_raw_bridge_allowed(changed)


def ally_r13_generated_witness(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    def write(name,o):
        q=tmp_path/name;q.write_text(json.dumps(o),encoding='utf-8');return dict(path=str(q),sha256=hashlib.sha256(q.read_bytes()).hexdigest())
    scope=copy.deepcopy(p.ALLY_STATIC_NYSE_SCOPE);cover=dict(fragment_role='SAME_FILE_COMMON_LISTING_TABLE',text=scope['original_listing_literal'],original_fragment_ref=dict(path=str(tmp_path/'generated_cover.html'),sha256='1'*64),original_byte_range=[100,200]);support=dict(fragments=[cover]);sr=write('original_support.json',support);full=dict(path=str(tmp_path/'generated_full_SGML.opaque'),sha256='2'*64)
    scope['source_draft_ref']=write('original_draft.json',dict(events=[dict(ticker='ALLY',effective_date='2025-10-31',support_ref=sr,full_submission_ref=full)]));monkeypatch.setattr(p,'ALLY_STATIC_NYSE_SCOPE',scope)
    base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=p._base().SEC_STATIC_PRIMARY_BODY_PROFILE);row=dict(title_of_class='COM',ticker='ALLY',cusip='02005N100',security_id='02005N100');raw=dict(security_uid='CUSIP:02005N100',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.ALLY',prior_date='2025-10-30',ex_date='2025-10-31',same_dated_UID_and_SID=True,share_quantity_effect=False)
    base._existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row);base._static_submission_dated_raw_identity=lambda *a,**kw:raw;monkeypatch.setattr(p,'_base',lambda:base)
    payload=dict(ally_exact_original_NYSE_acronym_scope=scope,sec_cash_statement_profile=p.MONETARY_COMMON,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE);entry=dict(identity_binding=dict(issuer='ALLY FINL INC'));facts0=dict(ticker='ALLY',security_id=scope['accounting_sid'],listing_identity='NYSE:ALLY',sec_filer_cik=40729,exact_frozen_event_key=dict(ticker='ALLY',effective_date='2025-10-31'),record_date='2025-10-31',pay_date='2025-11-14',cash_per_raw_share=.30,currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);source=dict(issuer_CIK=40729,original_HTTP_ref=full)
    return [payload,entry,facts0,cover['text'],[],source,support,lambda r:Path(r['path'])],row,raw

def test_ally_r13_exact_original_NYSE_cover_retains_literal_and_raw_identity(tmp_path,monkeypatch):
    args,row,raw=ally_r13_generated_witness(tmp_path,monkeypatch);before=copy.deepcopy(args[:7]);assert p._ally_original_nyse_matches(*args)==[('ALLY','New York Stock Exchange')]
    assert args[:7]==before and row['cusip']=='02005N100' and raw['share_quantity_effect'] is False

@pytest.mark.parametrize('kind',['scope','profile','ticker','ex','record','pay','cik','SID','currency','unit','amount','preferred','cover_ref','body_ref','CUSIP','raw_UID','raw_prior','raw_quantity'])
def test_ally_r13_other_events_classes_units_and_original_refs_rejected(tmp_path,monkeypatch,kind):
    args,row,raw=ally_r13_generated_witness(tmp_path,monkeypatch);payload,entry,f,listing,listed,source,support,pin=args
    if kind=='scope':payload['ally_exact_original_NYSE_acronym_scope']={}
    elif kind=='profile':payload['sec_cash_statement_profile']=p.OLD_STATIC
    elif kind=='ticker':f['ticker']='BAC'
    elif kind=='ex':f['exact_frozen_event_key']['effective_date']='2025-10-30'
    elif kind=='record':f['record_date']='2025-11-01'
    elif kind=='pay':f['pay_date']='2025-11-15'
    elif kind=='cik':source['issuer_CIK']=1
    elif kind=='SID':f['security_id']='FROZEN_RAW_TRANSPORT_CODE:US.OTHER'
    elif kind=='currency':f['currency']='CAD'
    elif kind=='unit':f['amount_unit']='USD_PER_ADR'
    elif kind=='amount':f['cash_per_raw_share']=.31
    elif kind=='preferred':args[3]=listing.replace('Common Stock','Preferred Stock')
    elif kind=='cover_ref':support['fragments'][0]['original_fragment_ref']['sha256']='3'*64
    elif kind=='body_ref':source['original_HTTP_ref']['sha256']='3'*64
    elif kind=='CUSIP':row['cusip']='999999999'
    elif kind=='raw_UID':raw['security_uid']='CUSIP:999999999'
    elif kind=='raw_prior':raw['prior_date']='2025-10-29'
    elif kind=='raw_quantity':raw['share_quantity_effect']=True
    with pytest.raises(ValueError):p._ally_original_nyse_matches(*args)

def test_ally_r13_no_optin_preserves_existing_listing_results_without_reads():
    result=[('BAC','New York Stock Exchange')];assert p._ally_original_nyse_matches({},None,None,'old literal',result,None,None,lambda r:pytest.fail('unexpected source read')) is result
    assert p._ally_original_nyse_matches({},None,None,'Common Stock ALLY NYSE',[],None,None,lambda r:pytest.fail('unexpected source read'))==[]

def test_ally_r13_exact_listing_extension_keeps_old_native_anchors():
    owner,anchors=p._owner();assert anchors['_sec_primary_html_cash_terms']['ally_exact_NYSE_after_original_listing_projection']==1
    assert owner._sec_primary_html_cash_terms.__globals__['_ally_original_nyse_matches'] is p._ally_original_nyse_matches
    assert owner.cash.normal_cash_ex_date.__code__ is p.cash.normal_cash_ex_date.__code__


def elv_r14_generated_current_proof(tmp_path,monkeypatch,*,concept='us-gaap:CommonStockDividendsPerShareDeclared',currency='USD',denominator='shares',context_CIK='0001156039',context_date='2025-10-15',context_member='us-gaap:SubsequentEventMember',amount='1.71',scale='0',accepted='2025-10-21T15:11:08+00:00',first_pub=None,record='2025-12-05',pay='2025-12-19',cusip='036752103'):
    import hashlib
    from types import SimpleNamespace
    def write(name,value):
        q=tmp_path/name;q.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());return dict(path=str(q),sha256=hashlib.sha256(q.read_bytes()).hexdigest())
    unit=f'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:{currency}</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:{denominator}</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'.encode();context=f'<xbrli:context id="c-276"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{context_CIK}</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:SubsequentEventTypeAxis">{context_member}</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>{context_date}</xbrli:startDate><xbrli:endDate>{context_date}</xbrli:endDate></xbrli:period></xbrli:context>'.encode();paragraph=f'<div>On October 15, 2025, our Audit Committee declared a fourth quarter 2025 dividend to shareholders of $<ix:nonFraction unitRef="usdPerShare" contextRef="c-276" decimals="2" name="{concept}" scale="{scale}">{amount}</ix:nonFraction> per share, payable on December 19, 2025 to shareholders of record at the close of business on December 5, 2025.</div>'.encode();raw=unit+context+paragraph;doc=write('elv_generated_SEC.htm',raw);header=write('elv_generated_HEADER.txt',b'<ACCEPTANCE-DATETIME>20251021111108\nCENTRAL INDEX KEY: 1156039\nACCESSION NUMBER: 0001156039-25-000136\nCONFORMED SUBMISSION TYPE: 10-Q\n');parts={}
    from scripts.storage.refresh_sec_event_originals import FilingText
    parser=FilingText();parser.feed(paragraph.decode());visible=' '.join(' '.join(parser.parts).split())
    for name,a,b in [('USD_per_share_unit',0,len(unit)),('current_common_context',len(unit),len(unit)+len(context)),('current_statement',len(unit)+len(context),len(raw))]:parts[name]=dict(byte_range=[a,b],original_fragment_ref=write(name+'.opaque',raw[a:b]),literal=raw[a:b].decode())
    parts['current_statement'].update(visible_literal=visible,visible_literal_sha256=hashlib.sha256(visible.encode()).hexdigest());scope=copy.deepcopy(p.ELV_CURRENT_SCOPE);event=dict(ticker='ELV',ex_date='2025-12-05',prior_date='2025-12-04',issuer_CIK=1156039,original_CUSIP='036752103',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.ELV',record_date=record,pay_date=pay,board_declaration_date='2025-10-15');proof=dict(event=event,current_common_declared_concept=concept,current_amount_from_capital_or_paid_financial_rows=False,first_publication_at=first_pub,engine_available_at=None,historical_availability_authority='UNKNOWN',accepted_at_utc=accepted,source_body_parts=parts,source_document_ref=doc,accepted_header_ref=header,source_form='10-Q',accession='0001156039-25-000136');scope['current_subject_proof_ref']=write('elv_generated_proof.json',proof);monkeypatch.setattr(p,'ELV_CURRENT_SCOPE',scope)
    realbase=p._base();base=SimpleNamespace(SEC_STATIC_SUBMISSION_PROFILE=realbase.SEC_STATIC_SUBMISSION_PROFILE);row=dict(title_of_class='COM',ticker='ELV',cusip=cusip,security_id=cusip);dated=dict(security_uid='CUSIP:'+cusip,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.ELV',prior_date='2025-12-04',ex_date='2025-12-05',same_dated_UID_and_SID=True,share_quantity_effect=False);base._existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row);base._static_submission_dated_raw_identity=lambda *a,**kw:dated;monkeypatch.setattr(p,'_base',lambda:base)
    payload=dict(elv_exact_current_common_dividend_scope=scope,sec_cash_statement_profile=p.ELV_CURRENT_COMMON,sec_source_transport_profile=base.SEC_STATIC_SUBMISSION_PROFILE);entry=dict(identity_binding=dict(issuer='ELEVANCE HEALTH INC FORMERLY'),prior_raw_close=dict(prior_date='2025-12-04'));facts0=dict(ticker='ELV',sec_filer_cik=1156039,security_id='FROZEN_RAW_TRANSPORT_CODE:US.ELV',listing_identity='NYSE:ELV',exact_frozen_event_key=dict(ticker='ELV',effective_date='2025-12-05'),record_date='2025-12-05',pay_date='2025-12-19',cash_per_raw_share=1.71,available_at=None,currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE);return [payload,entry,facts0,scope['original_listing_literal'],lambda r:Path(r['path'])],row,dated

def test_elv_r14_current_common_concept_unit_context_bytes_keep_original_words(tmp_path,monkeypatch):
    args,row,dated=elv_r14_generated_current_proof(tmp_path,monkeypatch);binding=p._elv_current_common_support(*args)
    assert isinstance(binding,p._VerifiedClass) and binding['current_statement_and_common_declared_XBRL_subject_bound'] and binding['source_USD_per_raw_share_unit_bound'] and row['cusip']=='036752103' and dated['share_quantity_effect'] is False
    sem=p.statement_semantics(p.ELV_CURRENT_COMMON,p.ELV_CURRENT_SCOPE['original_EX99_literal'],args[2],'2025-10-21');assert sem['selected_current_amount']=='1.71' and sem['current_amount_from_capital_row'] is False and sem['common_subject_role'].endswith('NOT_COVER_INFERENCE')

@pytest.mark.parametrize('kwargs',[dict(concept='us-gaap:PreferredStockDividendsPerShareDeclared'),dict(currency='CAD'),dict(denominator='ADS'),dict(context_CIK='0000000001'),dict(context_date='2025-10-16'),dict(context_member='us-gaap:ActualMember'),dict(amount='1.70'),dict(scale='6'),dict(accepted='2025-12-05T15:00:00Z'),dict(accepted='1948'),dict(accepted='2025-10-21T15:11:09+00:00'),dict(first_pub='2025-10-21T15:11:08Z'),dict(record='2025-12-04'),dict(pay='2025-12-20'),dict(cusip='999999999')])
def test_elv_r14_wrong_current_concept_units_CIK_dates_amount_and_CUSIP_fail_closed(tmp_path,monkeypatch,kwargs):
    args,row,dated=elv_r14_generated_current_proof(tmp_path,monkeypatch,**kwargs)
    with pytest.raises(ValueError):p._elv_current_common_support(*args)

@pytest.mark.parametrize('kind',['missing_scope','other_event','other_ticker','preferred_cover','raw_SID','source_CIK','changed_body_bytes','changed_fragment_bytes'])
def test_elv_r14_no_other_event_or_cover_or_unpinned_current_bytes(tmp_path,monkeypatch,kind):
    args,row,dated=elv_r14_generated_current_proof(tmp_path,monkeypatch);payload,entry,f,listing,pin=args
    if kind=='missing_scope':payload['elv_exact_current_common_dividend_scope']={}
    elif kind=='other_event':f['exact_frozen_event_key']['effective_date']='2025-09-05'
    elif kind=='other_ticker':f['ticker']='ALLY'
    elif kind=='preferred_cover':args[3]=listing.replace('Common Stock','Preferred Stock')
    elif kind=='raw_SID':f['security_id']='FROZEN_RAW_TRANSPORT_CODE:US.OTHER'
    elif kind=='source_CIK':f['sec_filer_cik']=1
    elif kind=='changed_body_bytes':
        proof=json.loads(Path(p.ELV_CURRENT_SCOPE['current_subject_proof_ref']['path']).read_text());Path(proof['source_document_ref']['path']).write_bytes(b'changed body')
    elif kind=='changed_fragment_bytes':
        proof=json.loads(Path(p.ELV_CURRENT_SCOPE['current_subject_proof_ref']['path']).read_text());Path(proof['source_body_parts']['current_statement']['original_fragment_ref']['path']).write_bytes(b'changed fragment')
    with pytest.raises(ValueError):p._elv_current_common_support(*args)

@pytest.mark.parametrize('literal',['',p.ELV_CURRENT_SCOPE['original_EX99_literal'].replace('$1.71','$1.70'),p.ELV_CURRENT_SCOPE['original_EX99_literal'].replace('Quarterly Dividend ','Annual Dividend '),p.ELV_CURRENT_SCOPE['original_EX99_literal'].replace('fourth quarter 2025','third quarter 2025'),p.ELV_CURRENT_SCOPE['original_EX99_literal'].replace('December 19, 2025','December 20, 2025'),p.ELV_CURRENT_SCOPE['original_EX99_literal']+' Another payment is $8.00 per share.'])
def test_elv_r14_original_EX99_literal_cannot_be_rewritten_or_drop_money(literal):
    with pytest.raises(ValueError):p.statement_semantics(p.ELV_CURRENT_COMMON,literal,dict(ticker='ELV',cash_per_raw_share=1.71,record_date='2025-12-05',pay_date='2025-12-19'),'2025-10-21')

def test_elv_r14_monotary_old_profile_missing_common_subject_still_rejected():
    with pytest.raises(ValueError,match='EXPLICIT_COMMON_STOCK_REQUIRED'):p.statement_semantics(p.MONETARY_COMMON,p.ELV_CURRENT_SCOPE['original_EX99_literal'],dict(ticker='ELV',cash_per_raw_share=1.71,record_date='2025-12-05',pay_date='2025-12-19'),'2025-10-21')


def test_elv_r14_registered_native_statement_dispatch_matches_scope():
    owner,anchors=p._owner()
    assert p.ELV_CURRENT_COMMON in p.PROFILES and p.ELV_CURRENT_COMMON in p.SCOPE['profiles']
    assert p.ELV_CURRENT_COMMON in owner._sec_primary_html_cash_terms.__globals__['PROFILES']
    f=dict(ticker='ELV',cash_per_raw_share=1.71,record_date='2025-12-05',pay_date='2025-12-19')
    assert owner._sec_primary_html_cash_terms.__globals__['_statement'](p.ELV_CURRENT_COMMON,p.ELV_CURRENT_SCOPE['original_EX99_literal'],f,'2025-10-21')==('2025-10-21','1.71','2025-12-19','2025-12-05')


# Synthetic only: fixed historical syntax, generated byte custody, no real prices.
def bac_r16_generated_role_proof(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    def write(name,value):
        target=tmp_path/name
        data=value if isinstance(value,bytes) else (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
        target.write_bytes(data);return dict(path=str(target),sha256=hashlib.sha256(data).hexdigest())
    scope=copy.deepcopy(p.BAC_PERCENT_SCOPE);literal=scope['original_current_literal'];raw=('<div>'+literal+'</div>').encode();raw+=b' '*(466-len(raw));full=write('generated_full.txt',b'prefix'+raw+b'tail');fragment=write('generated_current.html',raw);text=write('generated_current.txt',literal.encode());selected=dict(fragment_role='ORIGINAL_COMMON_CASH_DECLARATION_PRIMARY_BODY',original_byte_range=[6,472],original_fragment_ref=fragment,text_projection_ref=text,text=literal,text_typed_content_sha256=hashlib.sha256(json.dumps(literal,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest());source=write('generated_source.json',dict(original_HTTP_ref=full));support=write('generated_support.json',{});frozen_ref=write('generated_frozen.json',{})
    event={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','accounting_sid','record_date','pay_date','publication_accepted_at_utc','declaration_date')};proof=dict(schema='BAC_EXACT_2023_08_31_CURRENT_ONE_CASH_NONMONETARY_PERCENT_SOURCE_ROLE_PROOF_R16_R1',event=event,selected_original_current_fragment=selected,original_current_literal=literal,original_money_tokens=['0.24'],first_publication_at=None,engine_available_at=None,source_custody_ref=source,common_cover_support_ref=support,original_frozen_identity_ref=frozen_ref,original_same_full_submission_ref=dict(full,bytes=476),primary_member=dict(text_byte_range=[6,472]));scope['source_role_proof_ref']=write('generated_roles.json',proof);monkeypatch.setattr(p,'BAC_PERCENT_SCOPE',scope)
    def pin(ref):
        assert set(ref)=={'path','sha256'}  # Same exact nested-pin shape as original native gate.
        target=Path(ref['path']);assert hashlib.sha256(target.read_bytes()).hexdigest()==ref['sha256'];return target
    realbase=p._base();row=dict(ticker='BAC',title_of_class='COM',cusip='060505104',security_id='060505104',security_id_type='CUSIP',effective_start='2023-01-01',effective_end='2023-12-31');dated=dict(ticker='BAC',security_uid='CUSIP:060505104',accounting_sid=scope['accounting_sid'],prior_date=scope['prior_date'],ex_date=scope['ex_date'],same_dated_UID_and_SID=True,share_quantity_effect=False,source_coordinate='RAW_ACTUAL_SHARE',new_legal_CUSIP_authority=False)
    base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=realbase.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base)
    payload=dict(sec_cash_statement_profile=p.BAC_CURRENT_PERCENT,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE,bac_exact_current_nonmonetary_percent_scope=scope,selected_original_cash_fragment=selected,sec_cash_source_custody_ref=source,same_file_cash_identity_support_ref=support,frozen_account_identity_ref=frozen_ref);entry=dict(identity_binding=dict(issuer='BANK AMER CORP'),prior_raw_close=dict(prior_date=scope['prior_date']));f=dict(ticker='BAC',sec_filer_cik=70858,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='BAC',effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=.24,listing_identity='NYSE:BAC',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None)
    return [payload,entry,f,pin],row,dated,proof,write

def test_bac_r16_exact_profile_registered_in_native_dispatch_and_old_gate_unchanged():
    scope=p.BAC_PERCENT_SCOPE;f=dict(ticker='BAC',sec_filer_cik=70858,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=.24);owner,_=p._owner()
    assert p.BAC_CURRENT_PERCENT in p.PROFILES and p.BAC_CURRENT_PERCENT in p.SCOPE['profiles']
    assert p.BAC_CURRENT_PERCENT in owner._sec_primary_html_cash_terms.__globals__['PROFILES']
    assert owner._sec_primary_html_cash_terms.__globals__['_statement'](p.BAC_CURRENT_PERCENT,scope['original_current_literal'],f,'2023-07-31')==('2023-07-31','0.24','2023-09-29','2023-09-01')
    roles=p.statement_semantics(p.BAC_CURRENT_PERCENT,scope['original_current_literal'],f,'2023-07-31')['amount_roles'];assert roles[1]==dict(role='NONMONETARY_PRIOR_COMPARISON_CONTEXT',original_percent_literal='nine percent',is_cash_amount=False,old_cash_amount_supplied_by_source=False)
    with pytest.raises(ValueError,match='NO_COMPARISON'):p.statement_semantics(p.MONETARY_COMMON,scope['original_current_literal'],f,'2023-07-31')

@pytest.mark.parametrize('change',[('$0.24','$0.25'),('nine percent','ten percent'),('nine percent','9%'),('prior dividend rate','prior dividend rate of $0.22 per share'),('common stock','preferred stock'),('quarterly','annual'),('declared','proposed'),('September 1, 2023','September 2, 2023'),('September 29, 2023','September 28, 2023'),('',' Another quarterly cash dividend of $8.00 per share.')])
def test_bac_r16_original_comparison_and_all_money_cannot_be_rewritten(tmp_path,monkeypatch,change):
    args,*_=bac_r16_generated_role_proof(tmp_path,monkeypatch);literal=p.BAC_PERCENT_SCOPE['original_current_literal'];changed=literal+change[1] if not change[0] else literal.replace(*change)
    with pytest.raises(ValueError):p.statement_semantics(p.BAC_CURRENT_PERCENT,changed,args[2],'2023-07-31')

@pytest.mark.parametrize('kind',['scope','transport','currency','unit','quantity','prior','ticker','CIK','SID','ex','record','pay','amount','CUSIP','class','raw_UID','raw_ex','raw_quantity','selected_fragment','full_body','missing_event_field','event_CUSIP'])
def test_bac_r16_source_role_scope_custody_and_dated_identity_fail_closed(tmp_path,monkeypatch,kind):
    args,row,dated,proof,write=bac_r16_generated_role_proof(tmp_path,monkeypatch);payload,entry,f,pin=args
    if kind=='scope':payload['bac_exact_current_nonmonetary_percent_scope']={}
    elif kind=='transport':payload['sec_source_transport_profile']='OTHER'
    elif kind in ('currency','unit','quantity'):f[dict(currency='currency',unit='amount_unit',quantity='quantity_coordinate')[kind]]='WRONG'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2023-08-29'
    elif kind in ('ticker','CIK','SID','record','pay','amount'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind=='ex':f['exact_frozen_event_key']['effective_date']='2023-09-01'
    elif kind=='CUSIP':row['cusip']='OTHER'
    elif kind=='class':row['title_of_class']='COM NEW'
    elif kind=='raw_UID':dated['security_uid']='CUSIP:OTHER'
    elif kind=='raw_ex':dated['ex_date']='2023-09-01'
    elif kind=='raw_quantity':dated['share_quantity_effect']=True
    elif kind=='selected_fragment':payload['selected_original_cash_fragment']=dict(payload['selected_original_cash_fragment'],original_byte_range=[7,473])
    elif kind=='full_body':Path(proof['original_same_full_submission_ref']['path']).write_bytes(b'altered body')
    else:
        if kind=='missing_event_field':proof['event'].pop('original_CUSIP')
        else:proof['event']['original_CUSIP']='OTHER'
        p.BAC_PERCENT_SCOPE['source_role_proof_ref']=write('mutated_proof.json',proof)
    with pytest.raises((ValueError,AssertionError)):p._class_binding(payload,entry,f,'Common Stock BAC New York Stock Exchange','Bank of America Corporation',pin)

def test_bac_r16_physical_roles_preserve_original_COM_and_source_words(tmp_path,monkeypatch):
    args,row,dated,proof,write=bac_r16_generated_role_proof(tmp_path,monkeypatch);before=copy.deepcopy(args[:3]);assert p._class_binding(*args[:3],'Common Stock BAC New York Stock Exchange','Bank of America Corporation',args[3]) is None
    assert args[:3]==before and row['title_of_class']=='COM' and dated['share_quantity_effect'] is False
    sem=p.statement_semantics(p.BAC_CURRENT_PERCENT,p.BAC_PERCENT_SCOPE['original_current_literal'],args[2],'2023-07-31');assert sem['prior_cash_amount_inferred_from_percent'] is False and sem['current_cash_computed_from_percent_or_prior'] is False


@pytest.mark.parametrize('kind',['accepted_header_time','original_full','dated_prior','CUSIP','amount'])
def test_bac_r16_original_header_transport_and_clock_consumer_cannot_drift(tmp_path,monkeypatch,kind):
    args,row,dated,proof,write=bac_r16_generated_role_proof(tmp_path,monkeypatch);f=args[2];scope=p.BAC_PERCENT_SCOPE
    b,_=completion_binding();b.update(sec_cash_statement_profile=p.BAC_CURRENT_PERCENT,selected_original_cash_statement=scope['original_current_literal'],source_statement_date='2023-07-31',source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=scope['issuer_CIK'],static_submission_transport_proof=dict(original_submission_ref=proof['original_same_full_submission_ref'],accepted_at_utc=scope['publication_accepted_at_utc']))
    b['source_profile_completion']=p.statement_semantics(p.BAC_CURRENT_PERCENT,b['selected_original_cash_statement'],f,'2023-07-31');assert p._completion_clock(b,f)
    if kind=='accepted_header_time':b['static_submission_transport_proof']['accepted_at_utc']='2023-07-31T20:49:58+00:00'
    elif kind=='original_full':b['static_submission_transport_proof']['original_submission_ref']={}
    elif kind=='dated_prior':dated['prior_date']='2023-08-29'
    elif kind=='CUSIP':row['cusip']='999999999'
    elif kind=='amount':f['cash_per_raw_share']=.25
    with pytest.raises(ValueError):p._completion_clock(b,f)


# Synthetic bytes only; reported financial concept numeric contents are unused.
def qcom_r17_generated_policy_proof(tmp_path,monkeypatch,*,currency='USD',denominator='shares'):
    import hashlib
    from types import SimpleNamespace
    def write(name,value):
        target=tmp_path/name;data=value if isinstance(value,bytes) else (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode();target.write_bytes(data);return dict(path=str(target),sha256=hashlib.sha256(data).hexdigest())
    def pin(r):
        assert set(r)=={'path','sha256'}
        target=Path(r['path']);assert hashlib.sha256(target.read_bytes()).hexdigest()==r['sha256'];return target
    scope=copy.deepcopy(p.QCOM_POLICY_SCOPE);literal=scope['original_current_literal'];cashraw=('<div>'+literal+'</div>').encode();cashraw+=b' '*(1676-len(cashraw));unit=f'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:{currency}</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:{denominator}</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'.encode();assert len(unit)<=246;unit+=b' '*(246-len(unit));full=write('generated_full.txt',b'prefix'+unit+cashraw+b'tail');ur=write('generated_unit.html',unit);cr=write('generated_cash.html',cashraw);text=write('generated_cash.txt',literal.encode());source=write('generated_source.json',dict(original_HTTP_ref=full));selected=dict(fragment_role='ORIGINAL_COMMON_CASH_DECLARATION_PRIMARY_BODY',original_byte_range=[252,1928],original_fragment_ref=cr,text_projection_ref=text,text=literal)
    event={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','accounting_sid','record_date','pay_date','policy_announcement_date','quarterly_policy_effective_after_date','current_cash_announcement_date','publication_accepted_at_utc')};proof=dict(schema='QCOM_EXACT_2024_05_30_ORIGINAL_CURRENT_ANNOUNCED_COMMON_CASH_BOUND_QUARTER_POLICY_SOURCE_ROLE_PROOF_R17_R1',event=event,current_native_FilingText_space_join_literal=literal,original_money_tokens=['0.80','0.85','0.85'],first_publication_at=None,engine_available_at=None,source_original_full_submission_ref=dict(full,bytes=1932),original_current_fragment_ref=dict(cr,bytes=1676),selected_original_current_full_byte_range=[252,1928],original_primary_member=dict(text_byte_range=[6,1928]),physical_bounded_bindings=[dict(fragment_role='ORIGINAL_CURRENT_CASH_DECLARATION_PARAGRAPH',full_byte_range=[252,1928],original_fragment_ref=dict(cr,bytes=1676)),dict(fragment_role='ORIGINAL_XBRL_USD_PER_SHARE_UNIT_CONTEXT',full_byte_range=[6,252],original_fragment_ref=dict(ur,bytes=246))]);scope['source_role_proof_ref']=write('generated_proof.json',proof);monkeypatch.setattr(p,'QCOM_POLICY_SCOPE',scope)
    realbase=p._base();row=dict(ticker='QCOM',title_of_class='COM',cusip='747525103',security_id='747525103',security_id_type='CUSIP',effective_start='2024-05-22',effective_end='2024-08-20');dated=dict(ticker='QCOM',security_uid='CUSIP:747525103',accounting_sid=scope['accounting_sid'],prior_date=scope['prior_date'],ex_date=scope['ex_date'],same_dated_UID_and_SID=True,share_quantity_effect=False,source_coordinate='RAW_ACTUAL_SHARE',new_legal_CUSIP_authority=False);base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=realbase.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base)
    payload=dict(sec_cash_statement_profile=p.QCOM_CURRENT_POLICY,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE,qcom_exact_current_announcement_quarter_policy_scope=scope,selected_original_cash_fragment=selected,sec_cash_source_custody_ref=source);entry=dict(identity_binding=dict(issuer='QUALCOMM INC'),prior_raw_close=dict(prior_date=scope['prior_date']));f=dict(ticker='QCOM',sec_filer_cik=804328,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='QCOM',effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=.85,listing_identity='NASDAQ:QCOM',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None)
    return [payload,entry,f,pin],row,dated,proof,write

def test_qcom_r17_registered_current_announced_and_all_three_policy_roles(tmp_path,monkeypatch):
    scope=p.QCOM_POLICY_SCOPE;f=dict(ticker='QCOM',sec_filer_cik=804328,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='QCOM',effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=.85);owner,_=p._owner();assert p.QCOM_CURRENT_POLICY in p.PROFILES and p.QCOM_CURRENT_POLICY in p.SCOPE['profiles'] and p.QCOM_CURRENT_POLICY in owner._sec_primary_html_cash_terms.__globals__['PROFILES']
    assert owner._sec_primary_html_cash_terms.__globals__['_statement'](p.QCOM_CURRENT_POLICY,scope['original_current_literal'],f,'2024-05-01')==('2024-05-01','0.85','2024-06-20','2024-05-30');sem=p.statement_semantics(p.QCOM_CURRENT_POLICY,scope['original_current_literal'],f,'2024-05-01');assert [r['literal'] for r in sem['amount_roles']]==['0.80','0.85','0.85'] and sem['amount_roles'][-1]['role']=='EXPLICIT_CURRENT_ANNOUNCED_COMMON_CASH' and sem['annual_amount_created'] is False and sem['current_amount_from_reported_concept'] is False
    for old in (p.OLD_STATIC,p.MONETARY_COMMON,p.CURRENT_PRIOR_ANNUAL):
        with pytest.raises(ValueError):p._statement(old,scope['original_current_literal'],f,'2024-05-01')
    args,row,dated,proof,write=qcom_r17_generated_policy_proof(tmp_path,monkeypatch);before=copy.deepcopy(args[:3]);assert p._class_binding(*args[:3],'Common Stock QCOM NASDAQ','QUALCOMM Incorporated',args[3]) is None;assert args[:3]==before and row['title_of_class']=='COM' and dated['share_quantity_effect'] is False

@pytest.mark.parametrize('change',[('$ 0.80','$ 0.81'),('$ 0.85','$ 0.86'),('quarterly','annual'),('quarterly',''),('announced','declared'),('March 21, 2024','June 21, 2024'),('June 20, 2024','March 20, 2024'),('May 30, 2024','May 31, 2024'),('common stock','preferred stock'),('',' An annual dividend is $3.40 per share.')])
def test_qcom_r17_no_policy_role_word_date_or_money_can_disappear(tmp_path,monkeypatch,change):
    args,*_=qcom_r17_generated_policy_proof(tmp_path,monkeypatch);literal=p.QCOM_POLICY_SCOPE['original_current_literal'];changed=literal+change[1] if not change[0] else literal.replace(*change)
    with pytest.raises(ValueError):p.statement_semantics(p.QCOM_CURRENT_POLICY,changed,args[2],'2024-05-01')

@pytest.mark.parametrize('kind',['scope','transport','ticker','CIK','SID','ex','event_ticker','record','pay','amount','currency','unit','quantity','prior','CUSIP','class','raw_UID','raw_prior','raw_quantity','selected_range','fragment_ref','full_body','unit_tamper','proof_CUSIP','missing_current_money','wrong_policy_date'])
def test_qcom_r17_exact_source_current_USD_COM_and_dated_identity_fail_closed(tmp_path,monkeypatch,kind):
    args,row,dated,proof,write=qcom_r17_generated_policy_proof(tmp_path,monkeypatch);payload,entry,f,pin=args
    if kind=='scope':payload['qcom_exact_current_announcement_quarter_policy_scope']={}
    elif kind=='transport':payload['sec_source_transport_profile']='OTHER'
    elif kind in ('ticker','CIK','SID','record','pay','amount','currency','unit','quantity'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind in ('ex','event_ticker'):f['exact_frozen_event_key']['effective_date' if kind=='ex' else 'ticker']='2024-03-01' if kind=='ex' else 'OTHER'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2024-05-28'
    elif kind=='CUSIP':row['cusip']='OTHER'
    elif kind=='class':row['title_of_class']='COM NEW'
    elif kind=='raw_UID':dated['security_uid']='CUSIP:OTHER'
    elif kind=='raw_prior':dated['prior_date']='2024-05-28'
    elif kind=='raw_quantity':dated['share_quantity_effect']=True
    elif kind=='selected_range':payload['selected_original_cash_fragment']['original_byte_range']=[253,1929]
    elif kind=='fragment_ref':payload['selected_original_cash_fragment']['original_fragment_ref']=write('changed_fragment.html',b'changed')
    elif kind=='full_body':Path(proof['source_original_full_submission_ref']['path']).write_bytes(b'changed')
    elif kind=='unit_tamper':Path(proof['physical_bounded_bindings'][1]['original_fragment_ref']['path']).write_bytes(b'changed unit')
    else:
        if kind=='proof_CUSIP':proof['event']['original_CUSIP']='OTHER'
        elif kind=='missing_current_money':proof['original_money_tokens']=['0.80','0.85']
        else:proof['event']['quarterly_policy_effective_after_date']='2024-06-21'
        p.QCOM_POLICY_SCOPE['source_role_proof_ref']=write('changed_proof.json',proof)
    with pytest.raises((ValueError,AssertionError)):p._class_binding(*args[:3],'Common Stock QCOM NASDAQ','QUALCOMM Incorporated',pin)

@pytest.mark.parametrize('kwargs',[dict(currency='CAD'),dict(denominator='ADS')])
def test_qcom_r17_original_unit_cannot_be_borrowed_or_changed(tmp_path,monkeypatch,kwargs):
    args,*_=qcom_r17_generated_policy_proof(tmp_path,monkeypatch,**kwargs)
    with pytest.raises(ValueError,match='ORIGINAL_USD_PER_SHARE_UNIT'):p._class_binding(*args[:3],'Common Stock QCOM NASDAQ','QUALCOMM Incorporated',args[3])

@pytest.mark.parametrize('kind',['accepted_header_time','original_full','dated_prior','CUSIP','amount'])
def test_qcom_r17_original_header_and_clock_consumer_are_exact(tmp_path,monkeypatch,kind):
    args,row,dated,proof,write=qcom_r17_generated_policy_proof(tmp_path,monkeypatch);f=args[2];scope=p.QCOM_POLICY_SCOPE;b,_=completion_binding();b.update(sec_cash_statement_profile=p.QCOM_CURRENT_POLICY,selected_original_cash_statement=scope['original_current_literal'],source_statement_date='2024-05-01',source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=scope['issuer_CIK'],static_submission_transport_proof=dict(original_submission_ref=p._path_sha_ref(proof['source_original_full_submission_ref']),accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.QCOM_CURRENT_POLICY,b['selected_original_cash_statement'],f,'2024-05-01');assert p._completion_clock(b,f)
    if kind=='accepted_header_time':b['static_submission_transport_proof']['accepted_at_utc']='2024-05-01T20:06:33+00:00'
    elif kind=='original_full':b['static_submission_transport_proof']['original_submission_ref']={}
    elif kind=='dated_prior':dated['prior_date']='2024-05-28'
    elif kind=='CUSIP':row['cusip']='999999999'
    else:f['cash_per_raw_share']=.80
    with pytest.raises(ValueError):p._completion_clock(b,f)


# R18 fixtures construct only synthetic bounded source bytes; no real data reader.
def r18_write(tmp_path):
    import hashlib
    def write(name,value):
        q=tmp_path/name;q.write_bytes(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode());return dict(path=str(q),sha256=hashlib.sha256(q.read_bytes()).hexdigest())
    def pin(r):
        q=Path(r['path']);p._require(hashlib.sha256(q.read_bytes()).hexdigest()==r['sha256'],'GENERATED_PIN_TAMPER');return q
    return write,pin

def r18_static_generated(tmp_path,monkeypatch,*,ticker='PRMB',change=None):
    import hashlib
    write,pin=r18_write(tmp_path);prmb=ticker=='PRMB';scope=copy.deepcopy(p.PRMB_CURRENT_SCOPE if prmb else p.KBR_CURRENT_SCOPE);profile=scope['profile'];row=dict(ticker=ticker,cusip=scope['original_CUSIP'],security_id=scope['original_CUSIP'],title_of_class='CLASS A COM SHS' if prmb else 'COM',issuer_name='GENERATED ORIGINAL ISSUER',effective_start='2025-11-21' if prmb else '2024-02-22',effective_end='2025-12-31' if prmb else '2024-05-21',security_id_type='CUSIP');dated=dict(prior_date=scope['prior_date'],effective_date=scope['ex_date'],same_dated_cusip_and_accounting_sid=True,ex_identity=dict(security_uid='CUSIP:'+scope['original_CUSIP'],accounting_sid=scope['accounting_sid']),prior_identity=dict(security_uid='CUSIP:'+scope['original_CUSIP'],accounting_sid=scope['accounting_sid']));identity=dict(original_frozen_row=row,event=dated)
    proof=dict(original_frozen_dated_identity=identity);f=dict(ticker=ticker,sec_filer_cik=scope['issuer_CIK'],security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker=ticker,effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(scope['current_amount_literal']),listing_identity='NYSE:'+ticker,currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);entry=dict(prior_raw_close=dict(prior_date=scope['prior_date']))
    if prmb:
        unit=b'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
        context=b'<xbrli:context id="c-360"><xbrli:entity><xbrli:identifier>0002042694</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassAMember</xbrldi:explicitMember><xbrldi:explicitMember dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2025-11-05</xbrli:startDate><xbrli:endDate>2025-11-05</xbrli:endDate></xbrli:period></xbrli:context>'
        statement=b'<p>On November 5, 2025, the Board declared a dividend of $ <ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" contextRef="c-360" unitRef="usdPerShare" scale="0">0.10</ix:nonFraction> per share on outstanding Class A common stock, payable in cash December 5, 2025 to holders on November 25, 2025.</p>'
        if change in ('context_date','class_dimension','entity'):context=context.replace({'context_date':b'2025-11-05','class_dimension':b'CommonClassAMember','entity':b'0002042694'}[change],{'context_date':b'2025-09-30','class_dimension':b'CommonClassBMember','entity':b'0001111111'}[change])
        if change in ('concept','contextRef','unitRef','current_amount'):statement=statement.replace({'concept':b'CommonStockDividendsPerShareDeclared','contextRef':b'c-360','unitRef':b'usdPerShare','current_amount':b'>0.10<'}[change],{'concept':b'PreferredStockDividendsPerShareDeclared','contextRef':b'c-359','unitRef':b'cadPerShare','current_amount':b'>0.11<'}[change])
        if change=='currency':unit=unit.replace(b'iso4217:USD',b'iso4217:CAD')
        doc=write('generated_PRMB.htm',unit+context+statement);parts={}
        for name,start,raw in [('USD_per_share_unit',0,unit),('current_ClassA_context',len(unit),context),('current_tagged_statement',len(unit)+len(context),statement)]:parts[name]=dict(byte_range=[start,start+len(raw)],original_fragment_ref=dict(write(name+'.html',raw),bytes=len(raw)))
        from scripts.storage.refresh_sec_event_originals import FilingText
        parser=FilingText();parser.feed(statement.decode());visible=' '.join(' '.join(parser.parts).split());header=write('generated_PRMB_HEADER.txt',b'<ACCEPTANCE-DATETIME>20251106111816\nACCESSION NUMBER: 0001628280-25-049952\nCENTRAL INDEX KEY: 2042694\n')
        proof.update(event={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','original_frozen_class_literal','accounting_sid','record_date','pay_date','board_declaration_date','press_publication_date','current_amount_literal')},current_class_dimension='us-gaap:CommonClassAMember',current_context_period='2025-11-05',current_source_body_parts=parts,source_document_ref=dict(doc,bytes=len(unit+context+statement)),original_shared_unit_input=dict(accepted_header_ref=header,accepted_at_utc='2025-11-06T16:18:16+00:00',source_form='10-Q',accession='0001628280-25-049952',source_document_ref=doc,capital_fragment_byte_range=parts['current_tagged_statement']['byte_range'],capital_fragment_ref=p._path_sha_ref(parts['current_tagged_statement']['original_fragment_ref']),original_capital_row_literal=visible,USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=0,byte_end=len(unit),original_unit_markup=unit.decode())]))
    else:
        text='Our common stock is listed on the NYSE and trades under the symbol KBR. We expect comparable quarterly cash dividends. On February 19, 2024, the Board declared a dividend of $0.15 per share, paid April 15, 2024.'
        raw=('<p>'+text+'</p>').encode();raw+=b' '*(742-len(raw));doc=write('generated_KBR.htm',raw);rr=write('generated_KBR_note.html',raw);h=write('generated_KBR_HEADER.txt',b'<ACCEPTANCE-DATETIME>20240220121123\nACCESSION NUMBER: 0001357615-24-000016\nCENTRAL INDEX KEY: 1357615\n');proof.update(record_Mar15_from_original_main_EX99_only=True,current_common_primary_source=dict(source_original_primary_ref=dict(doc,bytes=len(raw)),original_current_paragraph_byte_range=[0,742],original_current_paragraph_ref=dict(rr,bytes=742),original_paragraph_complete_literal=text,actual_HEADER_ref=h,actual_HEADER_accepted_at_utc='2024-02-20T17:11:23+00:00'))
    if change=='proof_CUSIP':row['cusip']='OTHER'
    if change=='title':row['title_of_class']='COM'
    if change=='UID':dated['ex_identity']['security_uid']='CUSIP:OTHER'
    if change=='missing_event':proof.get('event',{}).pop('record_date',None)
    if change=='unit_time' and prmb:proof['original_shared_unit_input']['accepted_at_utc']='2025-11-06T16:18:00+00:00'
    scope['proof_ref']=write('generated_R18_proof.json',proof);monkeypatch.setattr(p,'PRMB_CURRENT_SCOPE' if prmb else 'KBR_CURRENT_SCOPE',scope);scope['original_fragment_sha256']='synthetic_main_sha';key='prmb_exact_current_ClassA_scope' if prmb else 'kbr_exact_current_common_scope';payload=dict(sec_cash_statement_profile=profile,sec_source_transport_profile=p._base().SEC_STATIC_SUBMISSION_PROFILE,selected_original_cash_fragment=dict(text=scope['original_current_literal'],original_fragment_ref=dict(sha256='synthetic_main_sha')),frozen_account_identity_ref=write('generated_frozen.json',dict(rows=[dict(original_source_row=row)])),**{key:scope})
    if change=='source_tamper':Path(doc['path']).write_bytes(b'tampered')
    if change=='prior':entry['prior_raw_close']['prior_date']='2024-01-01'
    return payload,entry,f,pin,proof

@pytest.mark.parametrize('ticker',['PRMB','KBR'])
def test_r18_static_exact_registration_literal_roles_and_original_class(tmp_path,monkeypatch,ticker):
    args=r18_static_generated(tmp_path,monkeypatch,ticker=ticker);payload,entry,f,pin,_=args;profile=payload['sec_cash_statement_profile'];scope=p.PRMB_CURRENT_SCOPE if ticker=='PRMB' else p.KBR_CURRENT_SCOPE;owner,_=p._owner();assert profile in p.PROFILES and profile in p.SCOPE['profiles'] and profile in owner._sec_primary_html_cash_terms.__globals__['PROFILES'];before=copy.deepcopy((payload,entry,f));b=p._class_binding(payload,entry,f,'Class A Common Stock PRMB New York Stock Exchange' if ticker=='PRMB' else 'Common Stock KBR New York Stock Exchange','Generated',pin);assert (payload,entry,f)==before
    assert (isinstance(b,p._VerifiedClass) and b['original_frozen_class_literal']=='CLASS A COM SHS') if ticker=='PRMB' else b is None
    sem=p.statement_semantics(profile,scope['original_current_literal'],f,scope['publication_date'],listed_common_class='A' if ticker=='PRMB' else None);assert sem['selected_current_amount']==scope['current_amount_literal'] and sem['board_date_not_publication_date'] and not sem['current_computed_from_prior_or_percentage'];assert [x.get('literal') for x in sem['amount_roles'] if 'literal' in x]==(['0.10'] if ticker=='PRMB' else ['0.135','0.15'])

@pytest.mark.parametrize('change',['context_date','class_dimension','entity','concept','contextRef','unitRef','current_amount','currency','proof_CUSIP','title','UID','missing_event','unit_time','source_tamper','prior'])
def test_r18_PRMB_current_ClassA_context_unit_and_frozen_title_fail_closed(tmp_path,monkeypatch,change):
    payload,entry,f,pin,_=r18_static_generated(tmp_path,monkeypatch,change=change)
    with pytest.raises(ValueError):p._class_binding(payload,entry,f,'Class A Common Stock PRMB New York Stock Exchange','Generated',pin)

@pytest.mark.parametrize('ticker',['PRMB','KBR'])
@pytest.mark.parametrize('kind',['ticker','CIK','SID','ex','record','pay','amount','currency','unit','quantity','available','text'])
def test_r18_static_exact_events_and_original_literal_cannot_expand(tmp_path,monkeypatch,ticker,kind):
    payload,entry,f,pin,_=r18_static_generated(tmp_path,monkeypatch,ticker=ticker)
    if kind=='ex':f['exact_frozen_event_key']['effective_date']='2024-01-01'
    elif kind=='text':payload['selected_original_cash_fragment']['text']+=' An annual dividend of $4.00.'
    else:f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate',available='available_at')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    with pytest.raises(ValueError):p._class_binding(payload,entry,f,'Class A Common Stock PRMB New York Stock Exchange','Generated',pin)

AMAT_R18_CURRENT='SANTA CLARA, Calif. , June 10, 2025 (GLOBE NEWSWIRE) -- Applied Materials, Inc. today announced that its Board of Directors has approved a quarterly cash dividend of $0.46 per share payable on the company’s common stock. The dividend is payable on Sept. 11, 2025 to shareholders of record as of Aug. 21, 2025 .'
AMAT_R18_POLICY='The cash dividend is a key component of Applied’s capital allocation strategy. In March 2025 , Applied announced a 15-percent increase in the quarterly dividend per share, from $0.40 to $0.46 , marking eight consecutive years of dividend increases. Over the past 10 fiscal years through 2024, the company has increased its dividend per share at a compound annual growth rate of approximately 15 percent and distributed nearly 90 percent of free cash flow to shareholders.'

def r18_amat_generated(tmp_path,monkeypatch,*,kind=None):
    import hashlib
    write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.AMAT_HTML_ONE_SCOPE);unit=b'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';prefix=b'<tr><td>Dividends declared ($</td><td><ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="usdPerShare" contextRef="c-3">'
    if kind=='currency':unit=unit.replace(b'iso4217:USD',b'iso4217:CAD')
    if kind=='concept':prefix=prefix.replace(b'CommonStockDividendsPerShareDeclared',b'PreferredStockDividendsPerShareDeclared')
    if kind=='numeric_payload':prefix+=b'9.99'
    doc=write('generated_amat_unit.htm',unit+prefix);rr=write('generated_amat_prefix.html',prefix);header=write('generated_amat_HEADER.txt',b'<ACCEPTANCE-DATETIME>20250522160201\nACCESSION NUMBER: 0000006951-25-000024\nCENTRAL INDEX KEY: 6951\n');unitinput=dict(accepted_header_ref=header,accepted_at_utc='2025-05-22T20:02:01+00:00',source_form='10-Q',accession='0000006951-25-000024',source_document_ref=doc,capital_fragment_ref=rr,capital_fragment_byte_range=[len(unit),len(unit+prefix)],original_capital_row_literal='Dividends declared ($',USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=0,byte_end=len(unit),original_unit_markup=unit.decode())])
    head=b'June  10, 2025';cashraw=('<p>'+AMAT_R18_CURRENT+'</p>').encode();policyraw=('<p>'+AMAT_R18_POLICY+'</p>').encode();body=head+b'\n'+cashraw+b'\n'+policyraw;full=write('generated_amat_article.html',body);full['bytes']=len(body);hr=write('generated_amat_dateline.txt',head);cr=write('generated_amat_cash.html',cashraw);pr=write('generated_amat_policy.html',policyraw);pa=len(head)+1+len(cashraw)+1
    event=dict(ticker='AMAT',ex_date='2025-08-21',prior_date='2025-08-20',issuer_cik=6951,original_CUSIP='038222105',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.AMAT',record_date='2025-08-21',pay_date='2025-09-11',source_primary_dateline_date='2025-06-10',source_displayed_datetime_literal='Jun 10, 2025 at 4:05 PM EDT',source_available_no_later_than='2025-06-10T21:06:11+00:00',current_amount_literal='0.46');row=dict(ticker='AMAT',title_of_class='COM',cusip='038222105',security_id='038222105',issuer_name='APPLIED MATLS INC');dated=dict(prior_date='2025-08-20',effective_date='2025-08-21',same_dated_cusip_and_accounting_sid=True,ex_identity=dict(security_uid='CUSIP:038222105',accounting_sid=event['accounting_sid']),prior_identity=dict(security_uid='CUSIP:038222105',accounting_sid=event['accounting_sid']));roles=[dict(role='PRIOR_QUARTER_POLICY_RATE_NOT_CURRENT_CASH',amount_literal='0.40'),dict(role='POLICY_CURRENT_RATE_CONCORDANCE_NOT_CURRENT_PAYMENT',amount_literal='0.46'),dict(role='NONMONETARY_POLICY_INCREASE_PERCENT',original_literal='15-percent'),dict(role='NONMONETARY_COMPOUND_ANNUAL_GROWTH_CONTEXT',original_literal='15 percent'),dict(role='NONMONETARY_FREE_CASH_FLOW_DISTRIBUTION_CONTEXT',original_literal='90 percent')];proof=dict(event=event,frozen_prior_metadata_selection=dict(original_frozen_row=row,event=dated),original_shared_unit_input=unitinput,actual_first_publication_at=None,engine_available_at=None,historical_availability_authority='UNKNOWN',source_current_cash_not_inferred_from_prior_policy=True,source_cash_not_from_capital_row=True,capital_reported_numeric_payload_not_read=True,source_terms_literal=AMAT_R18_CURRENT,source_terms_literal_sha256=hashlib.sha256(AMAT_R18_CURRENT.encode()).hexdigest(),archive_selected_source=dict(original_selected_fragment_proofs=[{}, {},dict(original_fragment_ref=pr,original_HTML_byte_range=[pa,len(body)],original_complete_text_projection=AMAT_R18_POLICY)]),current_amount_roles=[dict(role='EXPLICIT_APPROVED_CURRENT_QUARTER_COMMON_CASH',amount_literal='0.46')],prior_policy_roles=roles)
    if kind=='CUSIP':row['cusip']='OTHER'
    if kind=='class':row['title_of_class']='COM NEW'
    if kind=='SID':dated['prior_identity']['accounting_sid']='OTHER'
    if kind=='ex':event['ex_date']='2025-08-22'
    if kind=='unit_time':unitinput['accepted_at_utc']='2025-05-22T20:02:00+00:00'
    if kind=='first_pub':proof['actual_first_publication_at']='2025-06-10T20:05:00Z'
    scope['material_ref']=write('generated_amat_proof.json',proof);monkeypatch.setattr(p,'AMAT_HTML_ONE_SCOPE',scope);support=dict(schema=p.AMAT_UNIT_SUPPORT_SCHEMA,scope=scope,source_material_ref=scope['material_ref'],ticker='AMAT',ex_date='2025-08-21',original_CUSIP='038222105',source_material_event_fingerprint=p._base()._hash(proof));entry=dict(identity_binding=dict(issuer='APPLIED MATLS INC',ticker='AMAT',listing_identity='NASDAQ:AMAT',security_id='GENERATED_ORIGINAL_SOURCE_NAMESPACE',identity_kind='SOURCE_DERIVED_ISSUER_COMMON_CLASS'),prior_raw_close=dict(prior_date='2025-08-20'));source=dict(schema_version='B_HISTORICAL_PRIMARY_SOURCE_CAPTURE_V1',capture_profile='DATED_ISSUER_PRIMARY_HTML_BOUNDED_CASH_AND_DATED_HEADER_ORIGINAL_HTTP_FRAGMENTS',strict_pit_qualified=False,quote_qualified=False,certified_nav_qualified=False,http_status=200,received_http_bytes_sha256=full['sha256'],received_bytes=len(body),source_url='https://example.invalid/synthetic-AMAT/',historical_availability_status='UNKNOWN',original_http_bytes_ref=full,retrieval_timestamp_utc=event['source_available_no_later_than'],publication_date_expected_from_original_dated_source='2025-06-10',dated_header_observations=[dict(fragment_ref=hr,original_byte_range=[0,len(head)],literal='June 10, 2025')],cash_fragments=[dict(fragment_ref=cr,original_byte_range=[len(head)+1,len(head)+1+len(cashraw)],visible_text=AMAT_R18_CURRENT,visible_text_utf8_sha256=hashlib.sha256(AMAT_R18_CURRENT.encode()).hexdigest())],actual_first_publication_at=None,available_at=None)
    if kind=='source_tamper':Path(doc['path']).write_bytes(b'tampered')
    return entry,support,source,pin,proof

def test_r18_amat_original_approved_current_and_policy_registration(tmp_path,monkeypatch):
    entry,support,source,pin,proof=r18_amat_generated(tmp_path,monkeypatch);b=p._amat_common_support({},entry,support,pin);owner,_=p._owner();assert owner._frozen_common_cash_namespace.__globals__['AMAT_UNIT_SUPPORT_SCHEMA']==p.AMAT_UNIT_SUPPORT_SCHEMA and p.AMAT_HTML_ONE_SCOPE['profile'] in p.SCOPE['exact_dated_archive_profiles'];terms=owner._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=b);assert terms['amount']==.46 and terms['record']=='2025-08-21' and terms['pay']=='2025-09-11' and terms['available'] is None and terms['amount_roles'][:1]==proof['current_amount_roles'] and terms['amount_roles'][1:]==proof['prior_policy_roles'] and not terms['current_amount_from_capital_statement']

@pytest.mark.parametrize('kind',['currency','concept','numeric_payload','CUSIP','class','SID','ex','unit_time','first_pub','source_tamper'])
def test_r18_amat_separate_original_class_unit_and_dated_identity_fail_closed(tmp_path,monkeypatch,kind):
    entry,support,source,pin,_=r18_amat_generated(tmp_path,monkeypatch,kind=kind)
    with pytest.raises(ValueError):p._amat_common_support({},entry,support,pin)

@pytest.mark.parametrize('kind',['missing_current','wrong_amount','wrong_pay','wrong_record','declared','annual','first_pub','capture','HTTP','full_tamper','policy_tamper','extra_current_role','wrong_current_role'])
def test_r18_amat_exact_approved_current_and_policy_no_inference(tmp_path,monkeypatch,kind):
    entry,support,source,pin,proof=r18_amat_generated(tmp_path,monkeypatch);binding=p._amat_common_support({},entry,support,pin)
    if kind in ('missing_current','wrong_amount','wrong_pay','wrong_record','declared','annual'):
        original=source['cash_fragments'][0]['visible_text'];source['cash_fragments'][0]['visible_text']=original.replace(*{'missing_current':('$0.46',''),'wrong_amount':('$0.46','$0.47'),'wrong_pay':('Sept. 11','Sept. 12'),'wrong_record':('Aug. 21','Aug. 22'),'declared':('approved','declared'),'annual':('quarterly','annual')}[kind])
    elif kind=='first_pub':source['actual_first_publication_at']='2025-06-10T20:05:00Z'
    elif kind=='capture':source['retrieval_timestamp_utc']='2025-08-22T00:00:00Z'
    elif kind=='HTTP':source['http_status']=None
    elif kind=='full_tamper':Path(source['original_http_bytes_ref']['path']).write_bytes(b'tampered')
    elif kind=='extra_current_role':binding['source_material_event']['current_amount_roles'].append(dict(role='EXPLICIT_APPROVED_CURRENT_QUARTER_COMMON_CASH',amount_literal='0.46'))
    elif kind=='wrong_current_role':binding['source_material_event']['current_amount_roles'][0]['amount_literal']='0.40'
    else:Path(proof['archive_selected_source']['original_selected_fragment_proofs'][2]['original_fragment_ref']['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError):p._owner()[0]._original_dated_common_cash_terms(source,pinned=pin,separate_common_binding=binding)

def test_r18_amat_native_RAW_bridge_cannot_generalize_other_events_or_UID():
    bridge=dict(schema='AMAT_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R18',scope=p.AMAT_HTML_ONE_SCOPE,ticker='AMAT',ex_date='2025-08-21',security_uid='CUSIP:038222105',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.AMAT',source_owner_ref=p._ref(p.__file__));assert p._msft_raw_bridge_allowed(bridge)
    for key,value in [('ticker','OTHER'),('ex_date','2025-02-20'),('security_uid','CUSIP:OTHER'),('accounting_sid','OTHER'),('source_owner_ref',{})]:
        changed=copy.deepcopy(bridge);changed[key]=value;assert not p._msft_raw_bridge_allowed(changed)


# Exact APO first-quarter syntax uses generated source only, no real data reader.
def apo_r19_generated(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.APO_FIRST_QUARTER_SCOPE);text=scope['original_current_literal'];raw=('<p>'+text+'</p>').encode();raw+=b' '*(449-len(raw));doc=write('generated_APO_document.htm',raw);cr=write('generated_APO_current.html',raw);full=write('generated_APO_full.txt',b'header'+raw);scope['original_current_fragment_sha256']=cr['sha256'];event={k:scope[k] for k in ('ticker','ex_date','prior_date','issuer_CIK','original_CUSIP','accounting_sid','record_date','pay_date','source_publication_date','publication_accepted_at_utc','quarter_ended_date','current_amount_literal')};proof=dict(event=event,current_native_original_literal=text,original_current_money_tokens=['0.4625'],actual_first_publication_at=None,engine_available_at=None,financial_values_not_current_amount_or_class_override=True,original_main_cash_document_ref=dict(doc,bytes=449),original_current_fragment_ref=dict(cr,bytes=449),original_current_document_byte_range=[0,449],original_main_full_ref=dict(full,bytes=455));newfull=write('generated_APO_new_capture.txt',b'header'+raw);hr=write('generated_APO_header.txt',b'<ACCEPTANCE-DATETIME>20240502063101');oldfull=dict(full,bytes=455);newfull=dict(newfull,bytes=455);proof.update(original_main_HEADER_ref=hr,new_actual_main_full_ref=newfull);receipt=dict(schema='APO_ONE_FINAL_MAIN_NEW_ACTUAL_HTTP_CAPTURE_R1',old_UNKNOWN_status_and_original_source_files_untouched=True,new200_is_current_transport_observation_not_source_publication_clock=True,events=[dict(ticker='APO',effective_date='2024-05-16',original_pins=dict(CIK=1858681,accession='0001858681-24-000044',old_full_SHA=full['sha256'],old_full_bytes=455),old_full_ref=oldfull,successful_new_full_ref=newfull,old_HEADER_ref=hr,source_accepted_at_utc='2024-05-02T10:31:01Z',attempts=[dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_full_matches_old_SHA_size_and_bytewise=True,new_HEADER_prefix_matches_old_exactly=True,new_SEC_HEADER_matches_old_exactly=True)])]);proof['exact_old_new_transport_equivalence_receipt_ref']=write('generated_APO_equivalence.json',receipt);scope['source_role_proof_ref']=write('generated_APO_proof.json',proof);monkeypatch.setattr(p,'APO_FIRST_QUARTER_SCOPE',scope)
    row=dict(ticker='APO',title_of_class='COM',cusip='03769M106',security_id='03769M106',security_id_type='CUSIP',effective_start='2024-02-22',effective_end='2024-05-21');dated=dict(ticker='APO',prior_date='2024-05-15',ex_date='2024-05-16',security_uid='CUSIP:03769M106',accounting_sid=scope['accounting_sid'],same_dated_UID_and_SID=True,source_coordinate='RAW_ACTUAL_SHARE',share_quantity_effect=False,new_legal_CUSIP_authority=False);real=p._base();base=SimpleNamespace(SEC_STATIC_SUBMISSION_PROFILE=real.SEC_STATIC_SUBMISSION_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base)
    payload=dict(sec_cash_statement_profile=p.APO_FIRST_QUARTER,sec_source_transport_profile=base.SEC_STATIC_SUBMISSION_PROFILE,apo_exact_current_first_quarter_scope=scope,selected_original_cash_fragment=dict(text=text,original_fragment_ref=cr));entry=dict(identity_binding=dict(issuer='APOLLO GLOBAL MGMT INC'),prior_raw_close=dict(prior_date='2024-05-15'));f=dict(ticker='APO',sec_filer_cik=1858681,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='APO',effective_date='2024-05-16'),record_date='2024-05-17',pay_date='2024-05-31',cash_per_raw_share=.4625,listing_identity='NYSE:APO',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,f,pin],row,dated,proof,write

def test_apo_r19_exact_registration_original_first_quarter_and_current_roles(tmp_path,monkeypatch):
    owner,_=p._owner();assert p.APO_FIRST_QUARTER in p.PROFILES and p.APO_FIRST_QUARTER in p.SCOPE['profiles'] and p.APO_FIRST_QUARTER in owner._sec_primary_html_cash_terms.__globals__['PROFILES'];args,row,dated,proof,write=apo_r19_generated(tmp_path,monkeypatch);payload,entry,f,pin=args;before=copy.deepcopy(args[:3]);assert p._class_binding(payload,entry,f,'Common Stock APO New York Stock Exchange','Apollo Global Management, Inc.',pin) is None;assert args[:3]==before and row['title_of_class']=='COM';sem=p.statement_semantics(p.APO_FIRST_QUARTER,p.APO_FIRST_QUARTER_SCOPE['original_current_literal'],f,'2024-05-02');assert sem['selected_current_amount']=='0.4625' and sem['quarter_period_end_not_publication_date'] and not sem['current_amount_from_reported_capital'] and sem['amount_roles']==[dict(role='EXPLICIT_CURRENT_COMMON_CASH_FOR_ORIGINAL_NAMED_FIRST_QUARTER',literal='0.4625')]

@pytest.mark.parametrize('change',[('first quarter','second quarter'),('March 31, 2024','December 31, 2023'),('Common Stock','Preferred Stock'),('$0.4625','$0.43'),('May 17, 2024','May 16, 2024'),('May 31, 2024','May 30, 2024'),('has declared','has announced'),('',' Annual dividend is $1.85 per share.')])
def test_apo_r19_no_original_quarter_subject_amount_date_or_words_rewritten(tmp_path,monkeypatch,change):
    args,*_=apo_r19_generated(tmp_path,monkeypatch);text=p.APO_FIRST_QUARTER_SCOPE['original_current_literal'];changed=text+change[1] if not change[0] else text.replace(*change)
    with pytest.raises(ValueError):p.statement_semantics(p.APO_FIRST_QUARTER,changed,args[2],'2024-05-02')

@pytest.mark.parametrize('kind',['scope','transport','ticker','CIK','SID','ex','record','pay','amount','currency','unit','quantity','available','prior','CUSIP','class','dated_UID','dated_prior','fragment_ref','doc_tamper','proof_event','proof_money','firstpub','old_pair','new_pair','header_eq','capture_status'])
def test_apo_r19_exact_current_scope_original_unit_COM_and_physical_refs_fail_closed(tmp_path,monkeypatch,kind):
    args,row,dated,proof,write=apo_r19_generated(tmp_path,monkeypatch);payload,entry,f,pin=args
    if kind=='scope':payload['apo_exact_current_first_quarter_scope']={}
    elif kind=='transport':payload['sec_source_transport_profile']='OTHER'
    elif kind in ('ticker','CIK','SID','record','pay','amount','currency','unit','quantity','available'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate',available='available_at')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind=='ex':f['exact_frozen_event_key']['effective_date']='2024-05-15'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2024-05-14'
    elif kind=='CUSIP':row['cusip']='OTHER'
    elif kind=='class':row['title_of_class']='CL A'
    elif kind=='dated_UID':dated['security_uid']='CUSIP:OTHER'
    elif kind=='dated_prior':dated['prior_date']='2024-05-14'
    elif kind=='fragment_ref':payload['selected_original_cash_fragment']['original_fragment_ref']=write('changed_cash.html',b'changed')
    elif kind=='doc_tamper':Path(proof['original_main_cash_document_ref']['path']).write_bytes(b'changed')
    else:
        if kind=='proof_event':proof['event']['quarter_ended_date']='2024-06-30'
        elif kind=='proof_money':proof['original_current_money_tokens']=['0.43','0.4625']
        elif kind=='firstpub':proof['actual_first_publication_at']='2024-05-02T10:31:01Z'
        else:
            q=json.loads(Path(proof['exact_old_new_transport_equivalence_receipt_ref']['path']).read_text());e=q['events'][0]
            if kind=='old_pair':e['old_full_ref']['path']='OTHER'
            elif kind=='new_pair':e['successful_new_full_ref']['path']='OTHER'
            elif kind=='header_eq':e['attempts'][0]['new_SEC_HEADER_matches_old_exactly']=False
            else:e['attempts'][0]['response_status']=None
            proof['exact_old_new_transport_equivalence_receipt_ref']=write('changed_equivalence.json',q)
        p.APO_FIRST_QUARTER_SCOPE['source_role_proof_ref']=write('changed_proof.json',proof)
    with pytest.raises(ValueError):p._class_binding(payload,entry,f,'Common Stock APO New York Stock Exchange','Apollo Global Management, Inc.',pin)

@pytest.mark.parametrize('kind',['accepted_at','full_ref','CUSIP','prior','publication'])
def test_apo_r19_actual_header_and_quarter_end_are_not_relabelled_clock(tmp_path,monkeypatch,kind):
    args,row,dated,proof,write=apo_r19_generated(tmp_path,monkeypatch);f=args[2];scope=p.APO_FIRST_QUARTER_SCOPE;b,_=completion_binding();b.update(sec_cash_statement_profile=p.APO_FIRST_QUARTER,selected_original_cash_statement=scope['original_current_literal'],source_statement_date='2024-05-02',source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=1858681,static_submission_transport_proof=dict(original_submission_ref=p._path_sha_ref(proof['new_actual_main_full_ref']),accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.APO_FIRST_QUARTER,b['selected_original_cash_statement'],f,'2024-05-02');assert p._completion_clock(b,f)
    if kind=='accepted_at':b['static_submission_transport_proof']['accepted_at_utc']='2024-05-02T10:31:02Z'
    elif kind=='full_ref':b['static_submission_transport_proof']['original_submission_ref']={}
    elif kind=='CUSIP':row['cusip']='OTHER'
    elif kind=='prior':dated['prior_date']='2024-05-14'
    else:b['source_statement_date']='2024-03-31'
    with pytest.raises(ValueError):p._completion_clock(b,f)


# R20 uses generated documents and source-only identity stubs. No actual data IO.
def qcom_r20_generated(tmp_path,monkeypatch,ex):
    from types import SimpleNamespace
    from scripts.storage.refresh_sec_event_originals import FilingText
    write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.QCOM_CONTEXT_SCOPES[ex]);literal=scope['original_current_literal'];needle=scope['current_amount_literal'];at=literal.rfind(needle);tag=('<ix:nonFraction contextRef="'+scope['current_context_ref']+'" unitRef="usdPerShare" name="us-gaap:CommonStockDividendsPerShareDeclared" scale="0">').encode();cash=b'<p>'+literal[:at].encode()+tag+literal[at:at+len(needle)].encode()+b'</ix:nonFraction>'+literal[at+len(needle):].encode()+b'</p>';tagstart=cash.index(tag)
    context=('<xbrli:context id="'+scope['current_context_ref']+'"><xbrli:entity><xbrli:identifier>0000804328</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember</xbrldi:explicitMember><xbrldi:explicitMember dimension="us-gaap:DividendsAxis">'+scope['quarter_member']+'</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>'+scope['current_announcement_date']+'</xbrli:startDate><xbrli:endDate>'+scope['current_announcement_date']+'</xbrli:endDate></xbrli:period></xbrli:context>').encode();unit=b'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';primary=cash+context+unit
    local=pd.Timestamp(scope['publication_accepted_at_utc']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+scope['accession']+'\nCENTRAL INDEX KEY: 0000804328\n').encode();header+=b' '*(65536-len(header));hr=write('generated_header.txt',header);doc=write('generated_primary.htm',primary);full=write('generated_full.txt',header+primary);spans=[('original_complete_Dividends_paragraph',0,len(cash)),('current_CommonStockDeclared_opening_tag',tagstart,tagstart+len(tag)),('current_SubsequentEvent_context_CIK_date_XML',len(cash),len(cash)+len(context)),('original_USD_divide_shares_unit_XML',len(cash)+len(context),len(primary))];bindings=[]
    for role,a,b in spans:bindings.append(dict(fragment_role=role,old_primary_byte_range=[a,b],new_full_submission_byte_range=[65536+a,65536+b],old_fragment_ref=write(role+'.html',primary[a:b])))
    capture=dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_HEADER_prefix_equals_old_exactly=True,new_SEC_HEADER_equals_old_exactly=True,original_HTTP_ref=full,source_accepted_at_utc=scope['publication_accepted_at_utc']);cap=write('generated_capture.json',capture);proof=dict(schema='QCOM_TWO_EXACT_CURRENT_COMMON_QUARTER_CONTEXT_SOURCE_ROLE_PROOF_R20_R1',event=copy.deepcopy({k:v for k,v in scope.items() if k!='source_role_proof_ref'}),actual_first_publication_at=None,engine_available_at=None,reported_capital_values_used=False,new_actual_main_full_ref=dict(full,bytes=65536+len(primary)),new_actual_capture_ref=cap,actual_HEADER_ref=dict(hr,bytes=65536),original_primary_ref=dict(doc,bytes=len(primary)),original_primary_member=dict(text_byte_range=[65536,65536+len(primary)]),physical_original_byte_bindings=bindings,current_original_fragment_ref=bindings[0]['old_fragment_ref']);scope['source_role_proof_ref']=write('generated_proof.json',proof);scopes=copy.deepcopy(p.QCOM_CONTEXT_SCOPES);scopes[ex]=scope;monkeypatch.setattr(p,'QCOM_CONTEXT_SCOPES',scopes)
    row=dict(ticker='QCOM',title_of_class='COM',cusip='747525103',security_id='747525103',security_id_type='CUSIP',effective_start='2025-01-01',effective_end='2025-12-31');dated=dict(ticker='QCOM',security_uid='CUSIP:747525103',accounting_sid=scope['accounting_sid'],prior_date=scope['prior_date'],ex_date=ex,same_dated_UID_and_SID=True,share_quantity_effect=False,source_coordinate='RAW_ACTUAL_SHARE',new_legal_CUSIP_authority=False);real=p._base();base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=real.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base);source=write('generated_source.json',dict(original_HTTP_ref=full));payload=dict(sec_cash_statement_profile=p.QCOM_CURRENT_CONTEXT,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE,qcom_exact_current_quarter_context_scope=scope,sec_cash_source_custody_ref=source,selected_original_cash_fragment=dict(text=literal,original_fragment_ref=bindings[0]['old_fragment_ref'],original_byte_range=bindings[0]['new_full_submission_byte_range']));entry=dict(identity_binding=dict(issuer='QUALCOMM INC'),prior_raw_close=dict(prior_date=scope['prior_date']));facts=dict(ticker='QCOM',sec_filer_cik=804328,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='QCOM',effective_date=ex),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(needle),listing_identity='NASDAQ:QCOM',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,facts,pin],scope,row,dated,proof,capture,write

@pytest.mark.parametrize('ex',['2025-03-06','2025-06-05'])
def test_qcom_r20_two_original_current_quarter_contexts_and_roles(tmp_path,monkeypatch,ex):
    owner,_=p._owner();assert p.QCOM_CURRENT_CONTEXT in p.PROFILES and p.QCOM_CURRENT_CONTEXT in p.SCOPE['profiles'] and p.QCOM_CURRENT_CONTEXT in owner._sec_primary_html_cash_terms.__globals__['PROFILES'];args,scope,row,dated,proof,capture,write=qcom_r20_generated(tmp_path,monkeypatch,ex);before=copy.deepcopy(args[:3]);assert p._class_binding(*args[:3],'Common Stock QCOM Nasdaq','QUALCOMM Incorporated',args[3]) is None;assert args[:3]==before and row['title_of_class']=='COM';sem=p.statement_semantics(p.QCOM_CURRENT_CONTEXT,scope['original_current_literal'],args[2],scope['source_publication_date']);assert [z['literal'] for z in sem['amount_roles']]==scope['original_money_tokens'] and sem['selected_current_amount']==scope['current_amount_literal'] and sem['announced_not_rewritten_as_declared'] and not sem['current_amount_from_reported_concept'] and not sem['annual_rate_divided_or_inferred'];assert p._statement(p.QCOM_CURRENT_CONTEXT,scope['original_current_literal'],args[2],scope['source_publication_date'])==tuple([scope['source_publication_date'],scope['current_amount_literal'],scope['pay_date'],scope['record_date']])

@pytest.mark.parametrize('ex',['2025-03-06','2025-06-05'])
@pytest.mark.parametrize('kind',['scope','ticker','CIK','SID','event','record','pay','amount','currency','unit','quantity','available','prior','CUSIP','class','dated_UID','dated_prior','announced_words','extra_money','selected_ref','selected_span','concept','tag_context','unitRef','context_date','context_CIK','quarter','subsequent','unit_USD','unit_shares','physical_tamper','header_clock','capture_status','capture_ref','firstpub','proof_event'])
def test_qcom_r20_exact_current_physical_common_unit_context_and_identity_fail_closed(tmp_path,monkeypatch,ex,kind):
    args,scope,row,dated,proof,capture,write=qcom_r20_generated(tmp_path,monkeypatch,ex);payload,entry,f,pin=args
    if kind=='scope':payload['qcom_exact_current_quarter_context_scope']={}
    elif kind in ('ticker','CIK','SID','record','pay','amount','currency','unit','quantity','available'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate',available='available_at')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind=='event':f['exact_frozen_event_key']['effective_date']='2024-02-28'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2025-01-01'
    elif kind=='CUSIP':row['cusip']='WRONG'
    elif kind=='class':row['title_of_class']='CL A'
    elif kind=='dated_UID':dated['security_uid']='CUSIP:WRONG'
    elif kind=='dated_prior':dated['prior_date']='2025-01-01'
    elif kind=='announced_words':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('announced','declared')
    elif kind=='extra_money':payload['selected_original_cash_fragment']['text']+=' Annual dividend $3.40.'
    elif kind=='selected_ref':payload['selected_original_cash_fragment']['original_fragment_ref']=write('changed_cash.html',b'changed')
    elif kind=='selected_span':payload['selected_original_cash_fragment']['original_byte_range'][0]+=1
    else:
        if kind=='physical_tamper':Path(proof['original_primary_ref']['path']).write_bytes(b'changed')
        elif kind=='header_clock':
            raw=Path(proof['actual_HEADER_ref']['path']).read_bytes().replace(b'<ACCEPTANCE-DATETIME>',b'<ACCEPTANCE-DATETIME>19990101000000');proof['actual_HEADER_ref']=write('wrong_header.txt',raw)
        elif kind in ('capture_status','capture_ref'):
            if kind=='capture_status':capture['response_status']=None
            else:capture['original_HTTP_ref']=write('wrong_full.txt',b'changed')
            proof['new_actual_capture_ref']=write('wrong_capture.json',capture)
        elif kind=='firstpub':proof['actual_first_publication_at']='2025-01-01'
        elif kind=='proof_event':proof['event']['current_announcement_date']='2025-01-01'
        else:
            role={'concept':'current_CommonStockDeclared_opening_tag','tag_context':'current_CommonStockDeclared_opening_tag','unitRef':'current_CommonStockDeclared_opening_tag','context_date':'current_SubsequentEvent_context_CIK_date_XML','context_CIK':'current_SubsequentEvent_context_CIK_date_XML','quarter':'current_SubsequentEvent_context_CIK_date_XML','subsequent':'current_SubsequentEvent_context_CIK_date_XML','unit_USD':'original_USD_divide_shares_unit_XML','unit_shares':'original_USD_divide_shares_unit_XML'}[kind];z=next(v for v in proof['physical_original_byte_bindings'] if v['fragment_role']==role);a,b=z['old_primary_byte_range'];original=Path(proof['original_primary_ref']['path']).read_bytes();old,new={'concept':(b'CommonStockDividendsPerShareDeclared',b'PreferredStockDividendsDeclared_____'),'tag_context':(scope['current_context_ref'].encode(),b'c-99'),'unitRef':(b'usdPerShare',b'eurPerShare'),'context_date':(scope['current_announcement_date'].encode(),b'2025-01-01'),'context_CIK':(b'0000804328',b'0000804329'),'quarter':(scope['quarter_member'].encode(),b'qcom:O2025Q1DividendsMember'),'subsequent':(b'SubsequentEventMember',b'ReportedPeriodMember_'),'unit_USD':(b'iso4217:USD',b'iso4217:EUR'),'unit_shares':(b'xbrli:shares',b'xbrli:amount')}[kind];changed=original[a:b].replace(old,new);assert len(changed)==b-a;newprimary=original[:a]+changed+original[b:];oldfull=Path(proof['new_actual_main_full_ref']['path']).read_bytes();newfull=oldfull[:65536]+newprimary;proof['original_primary_ref']=write('changed_primary.htm',newprimary);proof['new_actual_main_full_ref']=write('changed_full.txt',newfull);capture['original_HTTP_ref']=proof['new_actual_main_full_ref'];proof['new_actual_capture_ref']=write('changed_capture.json',capture);z['old_fragment_ref']=write('changed_node.html',changed);proof['current_original_fragment_ref']=proof['physical_original_byte_bindings'][0]['old_fragment_ref'];payload['sec_cash_source_custody_ref']=write('changed_source.json',dict(original_HTTP_ref=proof['new_actual_main_full_ref']))
        scope['source_role_proof_ref']=write('changed_proof.json',proof)
    with pytest.raises((ValueError,AssertionError)):p._class_binding(*args[:3],'Common Stock QCOM Nasdaq','QUALCOMM Incorporated',pin)

@pytest.mark.parametrize('ex',['2025-03-06','2025-06-05'])
@pytest.mark.parametrize('bad',['none','clock','current_full'])
def test_qcom_r20_original_engineering_clock_before_RAW(tmp_path,monkeypatch,ex,bad):
    args,scope,row,dated,proof,capture,write=qcom_r20_generated(tmp_path,monkeypatch,ex);b,_=completion_binding();b.update(sec_cash_statement_profile=p.QCOM_CURRENT_CONTEXT,selected_original_cash_statement=scope['original_current_literal'],source_statement_date=scope['source_publication_date'],source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=804328,static_submission_transport_proof=dict(original_submission_ref=p._path_sha_ref(proof['new_actual_main_full_ref']),accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.QCOM_CURRENT_CONTEXT,b['selected_original_cash_statement'],args[2],scope['source_publication_date'])
    if bad=='none':assert p._completion_clock(b,args[2]) is True
    else:
        if bad=='clock':b['static_submission_transport_proof']['accepted_at_utc']='2025-01-01T00:00:00Z'
        else:b['static_submission_transport_proof']['original_submission_ref']=write('another_full.txt',b'wrong')
        with pytest.raises(ValueError):p._completion_clock(b,args[2])


# Exact named-common R21 family; generated source documents only.
def named_ab_r21_generated(tmp_path,monkeypatch,key):
    from types import SimpleNamespace
    write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.NAMED_AB_SCOPES[key]);cash=('<p>'+scope['original_current_literal']+'</p>').encode();size=616 if scope['ticker']=='FCNCA' else 475;cash+=b' '*(size-len(cash));assert len(cash)==size;local=pd.Timestamp(scope['publication_accepted_at_utc']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+scope['accession']+'\nCENTRAL INDEX KEY: '+str(scope['issuer_CIK'])+'\n').encode();header+=b' '*(65536-len(header));hr=write('generated_header.txt',header);cr=write('generated_current.html',cash);doc=write('generated_primary.htm',cash);full=write('generated_full.txt',header+cash);capture=dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_HEADER_prefix_equals_old_exactly=True,new_SEC_HEADER_equals_old_exactly=True,original_HTTP_ref=full,source_accepted_at_utc=scope['publication_accepted_at_utc']);cap=write('generated_capture.json',capture);proof=dict(schema='EXACT_TWO_NAMED_A_B_COMMON_CURRENT_QUARTER_ROLE_PROOF_R21_R1',event={k:v for k,v in scope.items() if k!='source_role_proof_ref'},first_publication_at=None,engine_available_at=None,cash_amount_selected_only_direct_current_literal=True,percentage_or_aggregate_cash_inference=False,published_comparison_inconsistent_not_used=(scope['ticker']=='FCNCA'),new_actual_main_full_ref=dict(full,bytes=65536+size),new_actual_capture_ref=cap,actual_HEADER_ref=hr,original_primary_ref=doc,original_primary_member=dict(text_byte_range=[65536,65536+size]),current_original_fragment_ref=cr,physical_original_byte_bindings=[dict(fragment_role='original_current_common_cash',old_primary_byte_range=[0,size],new_full_submission_byte_range=[65536,65536+size],old_fragment_ref=cr)]);scope['source_role_proof_ref']=write('generated_role_proof.json',proof);scopes=copy.deepcopy(p.NAMED_AB_SCOPES);scopes[key]=scope;monkeypatch.setattr(p,'NAMED_AB_SCOPES',scopes);row=dict(ticker=scope['ticker'],title_of_class='CL A',cusip=scope['original_CUSIP'],security_id=scope['original_CUSIP'],security_id_type='CUSIP',effective_start='2023-01-01',effective_end='2025-12-31');dated=dict(ticker=scope['ticker'],prior_date=scope['prior_date'],ex_date=scope['ex_date'],security_uid='CUSIP:'+scope['original_CUSIP'],accounting_sid=scope['accounting_sid'],same_dated_UID_and_SID=True,share_quantity_effect=False,new_legal_CUSIP_authority=False,source_coordinate='RAW_ACTUAL_SHARE');real=p._base();monkeypatch.setattr(p,'_base',lambda:SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=real.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin));ir=write('generated_original_identity.json',dict(rows=[dict(original_source_row=row)]));sr=write('generated_source.json',dict(original_HTTP_ref=full));payload=dict(sec_cash_statement_profile=p.NAMED_AB_CURRENT,sec_source_transport_profile=real.SEC_STATIC_PRIMARY_BODY_PROFILE,named_ab_exact_current_scope=scope,sec_cash_source_custody_ref=sr,frozen_account_identity_ref=ir,selected_original_cash_fragment=dict(text=scope['original_current_literal'],original_fragment_ref=cr,original_byte_range=[65536,65536+size]));entry=dict(prior_raw_close=dict(prior_date=scope['prior_date']));f=dict(ticker=scope['ticker'],sec_filer_cik=scope['issuer_CIK'],security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker=scope['ticker'],effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(scope['current_amount_literal']),listing_identity=scope['listing_identity'],currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,f,pin],scope,row,dated,proof,capture,write

@pytest.mark.parametrize('key',['FCNCA|2023-11-29','MA|2024-04-08'])
def test_named_ab_r21_exact_registration_roles_class_and_current_literal(tmp_path,monkeypatch,key):
    owner,_=p._owner();assert p.NAMED_AB_CURRENT in p.PROFILES and p.NAMED_AB_CURRENT in p.SCOPE['profiles'] and p.NAMED_AB_CURRENT in p.CLASS_PROFILES and p.NAMED_AB_CURRENT in owner._sec_primary_html_cash_terms.__globals__['PROFILES'];args,scope,row,dated,proof,capture,write=named_ab_r21_generated(tmp_path,monkeypatch,key);before=copy.deepcopy(args[:3]);w=p._class_binding(*args[:3],'Class A Common Stock '+scope['ticker']+' New York Stock Exchange','Original issuer',args[3]);assert p._class_allowed(*args[:3],row,w) and p._subject_class(p.NAMED_AB_CURRENT,args[0],row,'Class A Common Stock');assert args[:3]==before and row['title_of_class']=='CL A';sem=p.statement_semantics(p.NAMED_AB_CURRENT,scope['original_current_literal'],args[2],scope['source_publication_date'],listed_common_class='A');assert sem['selected_current_amount']==scope['current_amount_literal'] and sem['certified_source_cash_share_classes']==['A','B'] and sem['certified_accounting_cash_share_classes']==['A'] and not sem['other_class_account_position_created'] and not sem['percent_or_aggregate_amount_inference'];assert sem['published_percentage_inconsistency_retained_not_used']==(scope['ticker']=='FCNCA');assert len(sem['amount_roles'])==(3 if scope['ticker']=='FCNCA' else 2)

@pytest.mark.parametrize('key',['FCNCA|2023-11-29','MA|2024-04-08'])
@pytest.mark.parametrize('kind',['scope','ticker','CIK','SID','event','record','pay','amount','currency','unit','quantity','available','prior','listing_class','changed_classes','drop_role','add_money','current_ref','current_span','original_primary_tamper','old_current_tamper','capture_status','capture_header_equal','capture_clock','HEADER_CIK','HEADER_clock','proof_event','proof_firstpub','proof_inference','proof_comparison','CUSIP','class'])
def test_named_ab_r21_all_original_roles_units_classes_identity_and_physical_bytes_fail_closed(tmp_path,monkeypatch,key,kind):
    args,scope,row,dated,proof,capture,write=named_ab_r21_generated(tmp_path,monkeypatch,key);payload,entry,f,pin=args;listing='Class A Common Stock';
    if kind=='scope':payload['named_ab_exact_current_scope']={}
    elif kind in ('ticker','CIK','SID','record','pay','amount','currency','unit','quantity','available'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate',available='available_at')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind=='event':f['exact_frozen_event_key']['effective_date']='2024-02-28'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2023-01-01'
    elif kind=='listing_class':listing='Class B Common Stock'
    elif kind=='changed_classes':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('Class B','Class C')
    elif kind=='drop_role':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('219%','218%') if scope['ticker']=='FCNCA' else scope['original_current_literal'].replace('$616 million','$615 million')
    elif kind=='add_money':payload['selected_original_cash_fragment']['text']+=' Annual dividend $2.64.'
    elif kind=='current_ref':payload['selected_original_cash_fragment']['original_fragment_ref']=write('wrong_current.html',b'wrong')
    elif kind=='current_span':payload['selected_original_cash_fragment']['original_byte_range'][0]+=1
    else:
        if kind in ('original_primary_tamper','old_current_tamper'):Path(proof['original_primary_ref' if kind=='original_primary_tamper' else 'current_original_fragment_ref']['path']).write_bytes(b'changed')
        elif kind.startswith('capture_'):
            if kind=='capture_status':capture['response_status']=None
            elif kind=='capture_header_equal':capture['new_SEC_HEADER_equals_old_exactly']=False
            else:capture['source_accepted_at_utc']='2023-01-01T00:00:00Z'
            proof['new_actual_capture_ref']=write('changed_capture.json',capture)
        elif kind.startswith('HEADER_'):
            h=Path(proof['actual_HEADER_ref']['path']).read_bytes();h=h.replace(str(scope['issuer_CIK']).encode(),b'000000') if kind=='HEADER_CIK' else h.replace(b'<ACCEPTANCE-DATETIME>',b'<ACCEPTANCE-DATETIME>19990101000000');proof['actual_HEADER_ref']=write('changed_header.txt',h)
        elif kind=='proof_event':proof['event']['declaration_date']='2023-01-01'
        elif kind=='proof_firstpub':proof['first_publication_at']='2023-01-01'
        elif kind=='proof_inference':proof['percentage_or_aggregate_cash_inference']=True
        elif kind=='proof_comparison':proof['published_comparison_inconsistent_not_used']=not proof['published_comparison_inconsistent_not_used']
        elif kind in ('CUSIP','class'):
            row['cusip' if kind=='CUSIP' else 'title_of_class']='OTHER';payload['frozen_account_identity_ref']=write('wrong_original_identity.json',dict(rows=[dict(original_source_row=row)]))
        scope['source_role_proof_ref']=write('changed_proof.json',proof)
    with pytest.raises((ValueError,AssertionError)):p._class_binding(*args[:3],listing,'Original issuer',pin)

@pytest.mark.parametrize('key',['FCNCA|2023-11-29','MA|2024-04-08'])
@pytest.mark.parametrize('bad',['none','clock','SID','prior','CUSIP'])
def test_named_ab_r21_original_common_class_clock_and_same_UID_before_RAW(tmp_path,monkeypatch,key,bad):
    args,scope,row,dated,proof,capture,write=named_ab_r21_generated(tmp_path,monkeypatch,key);b,_=completion_binding();b.update(sec_cash_statement_profile=p.NAMED_AB_CURRENT,selected_original_cash_statement=scope['original_current_literal'],source_statement_date=scope['source_publication_date'],source_unique_listed_common_class='A',source_profile_original_class_row=row,original_frozen_class_literal='CL A',static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=scope['issuer_CIK'],static_submission_transport_proof=dict(original_submission_ref=p._path_sha_ref(proof['new_actual_main_full_ref']),accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.NAMED_AB_CURRENT,b['selected_original_cash_statement'],args[2],scope['source_publication_date'],listed_common_class='A')
    if bad=='none':assert p._completion_clock(b,args[2]) is True
    else:
        if bad=='clock':b['static_submission_transport_proof']['accepted_at_utc']='2023-01-01T00:00:00Z'
        elif bad=='SID':dated['accounting_sid']='FROZEN_RAW_TRANSPORT_CODE:US.FCNCA' if scope['ticker']=='FCNCA' else 'WRONG'
        elif bad=='prior':dated['prior_date']='2023-01-01'
        else:row['cusip']='OTHER'
        with pytest.raises(ValueError):p._completion_clock(b,args[2])


# R22 generated ordinal-quarter/month-context source fixture. No actual readers.
def ordinal_r22_generated(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts.storage.refresh_sec_event_originals import FilingText
    ex='2024-06-07';write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.ORDINAL_COMMON_SCOPES['BBWI|'+ex]);literal=scope['original_current_literal'];needle=scope['current_amount_literal'];at=literal.rfind(needle);tag=('<ix:nonFraction contextRef="'+scope['current_context_ref']+'" unitRef="usdPerShare" name="us-gaap:CommonStockDividendsPerShareDeclared" scale="0">').encode();cash=b'<p>'+literal[:at].encode()+tag+literal[at:at+len(needle)].encode()+b'</ix:nonFraction>'+literal[at+len(needle):].encode()+b'</p>';tagstart=cash.index(tag)
    context=('<xbrli:context id="'+scope['current_context_ref']+'"><xbrli:entity><xbrli:identifier>0000701985</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>'+scope['current_context_start_date']+'</xbrli:startDate><xbrli:endDate>'+scope['current_context_end_date']+'</xbrli:endDate></xbrli:period></xbrli:context>').encode();unit=b'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';primary=cash+context+unit
    local=pd.Timestamp(scope['publication_accepted_at_utc']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+scope['accession']+'\nCENTRAL INDEX KEY: 0000701985\n').encode();header+=b' '*(65536-len(header));hr=write('generated_header.txt',header);doc=write('generated_primary.htm',primary);full=write('generated_full.txt',header+primary);spans=[('original_current_common_cash',0,len(cash)),('current_CommonStockDeclared_opening_tag',tagstart,tagstart+len(tag)),('current_SubsequentEvent_May_context',len(cash),len(cash)+len(context)),('original_USD_divide_shares_unit',len(cash)+len(context),len(primary))];bindings=[]
    for role,a,b in spans:bindings.append(dict(fragment_role=role,old_primary_byte_range=[a,b],new_full_submission_byte_range=[65536+a,65536+b],old_fragment_ref=write(role+'.html',primary[a:b])))
    capture=dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_HEADER_prefix_equals_old_exactly=True,new_SEC_HEADER_equals_old_exactly=True,original_HTTP_ref=full,source_accepted_at_utc=scope['publication_accepted_at_utc']);cap=write('generated_capture.json',capture);proof=dict(schema='EXACT_CURRENT_ORDINAL_QUARTER_COMMON_MONTH_CONTEXT_ROLE_PROOF_R22_R1',event=copy.deepcopy({k:v for k,v in scope.items() if k!='source_role_proof_ref'}),actual_first_publication_at=None,engine_available_at=None,reported_capital_values_used=False,exact_board_day_inferred=False,quarterly_word_inserted=False,new_actual_main_full_ref=dict(full,bytes=65536+len(primary)),new_actual_capture_ref=cap,actual_HEADER_ref=dict(hr,bytes=65536),original_primary_ref=dict(doc,bytes=len(primary)),original_primary_member=dict(text_byte_range=[65536,65536+len(primary)]),physical_original_byte_bindings=bindings,current_original_fragment_ref=bindings[0]['old_fragment_ref']);scope['source_role_proof_ref']=write('generated_proof.json',proof);scopes=copy.deepcopy(p.ORDINAL_COMMON_SCOPES);scopes['BBWI|'+ex]=scope;monkeypatch.setattr(p,'ORDINAL_COMMON_SCOPES',scopes)
    row=dict(ticker='BBWI',title_of_class='COM',cusip='070830104',security_id='070830104',security_id_type='CUSIP',effective_start='2024-05-22',effective_end='2024-08-20');dated=dict(ticker='BBWI',security_uid='CUSIP:070830104',accounting_sid=scope['accounting_sid'],prior_date=scope['prior_date'],ex_date=ex,same_dated_UID_and_SID=True,share_quantity_effect=False,source_coordinate='RAW_ACTUAL_SHARE',new_legal_CUSIP_authority=False);real=p._base();base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=real.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base);source=write('generated_source.json',dict(original_HTTP_ref=full));payload=dict(sec_cash_statement_profile=p.ORDINAL_CURRENT_COMMON,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE,ordinal_exact_current_common_scope=scope,sec_cash_source_custody_ref=source,selected_original_cash_fragment=dict(text=literal,original_fragment_ref=bindings[0]['old_fragment_ref'],original_byte_range=bindings[0]['new_full_submission_byte_range']));entry=dict(identity_binding=dict(issuer='QUALCOMM INC'),prior_raw_close=dict(prior_date=scope['prior_date']));facts=dict(ticker='BBWI',sec_filer_cik=701985,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='BBWI',effective_date=ex),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(needle),listing_identity='NYSE:BBWI',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,facts,pin],scope,row,dated,proof,capture,write

def test_ordinal_r22_exact_current_507_month_precision_roles_and_registration(tmp_path,monkeypatch):
    owner,_=p._owner();assert p.ORDINAL_CURRENT_COMMON in p.PROFILES and p.ORDINAL_CURRENT_COMMON in p.SCOPE['profiles'] and p.ORDINAL_CURRENT_COMMON in owner._sec_primary_html_cash_terms.__globals__['PROFILES'];args,scope,row,dated,proof,capture,write=ordinal_r22_generated(tmp_path,monkeypatch);before=copy.deepcopy(args[:3]);assert p._class_binding(*args[:3],'Common Stock BBWI The New York Stock Exchange','Bath & Body Works Inc',args[3]) is None;assert args[:3]==before;sem=p.statement_semantics(p.ORDINAL_CURRENT_COMMON,scope['original_current_literal'],args[2],'2024-06-04');assert sem['selected_current_amount']=='0.20' and sem['current_declaration_precision']=='MONTH_ONLY' and sem['current_declared_month']=='2024-05' and sem['exact_board_day_inferred'] is False and sem['quarterly_word_inserted'] is False and sem['current_amount_from_reported_concept'] is False and sem['quarter_authority']=='second quarter 2024 ordinary dividend'

@pytest.mark.parametrize('kind',['scope','ticker','CIK','SID','event','record','pay','amount','currency','unit','quantity','available','prior','CUSIP','class','dated_UID','dated_prior','literal_word','insert_exact_day','insert_quarterly','add_money','current_ref','current_span','concept','tag_context','tag_unit','context_CIK','context_start','context_end','context_axis','unit_USD','unit_shares','source_tamper','header_clock','capture_status','proof_inference','proof_word_rewrite','firstpub'])
def test_ordinal_r22_month_common_concept_unit_literal_clock_and_identity_fail_closed(tmp_path,monkeypatch,kind):
    args,scope,row,dated,proof,capture,write=ordinal_r22_generated(tmp_path,monkeypatch);payload,entry,f,pin=args
    if kind=='scope':payload['ordinal_exact_current_common_scope']={}
    elif kind in ('ticker','CIK','SID','record','pay','amount','currency','unit','quantity','available'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate',available='available_at')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind=='event':f['exact_frozen_event_key']['effective_date']='2024-06-06'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2024-06-05'
    elif kind=='CUSIP':row['cusip']='OTHER'
    elif kind=='class':row['title_of_class']='CL A'
    elif kind=='dated_UID':dated['security_uid']='CUSIP:OTHER'
    elif kind=='dated_prior':dated['prior_date']='2024-06-05'
    elif kind in ('literal_word','insert_exact_day','insert_quarterly','add_money'):
        text=scope['original_current_literal'];payload['selected_original_cash_fragment']['text']=text.replace('second quarter','third quarter') if kind=='literal_word' else text.replace('May 2024','May 1, 2024') if kind=='insert_exact_day' else text.replace('ordinary dividend','ordinary quarterly dividend') if kind=='insert_quarterly' else text+' Annual cash $0.80.'
    elif kind=='current_ref':payload['selected_original_cash_fragment']['original_fragment_ref']=write('wrong_cash.html',b'changed')
    elif kind=='current_span':payload['selected_original_cash_fragment']['original_byte_range'][0]+=1
    else:
        if kind=='source_tamper':Path(proof['original_primary_ref']['path']).write_bytes(b'changed')
        elif kind=='header_clock':proof['actual_HEADER_ref']=write('wrong_header.txt',Path(proof['actual_HEADER_ref']['path']).read_bytes().replace(b'<ACCEPTANCE-DATETIME>',b'<ACCEPTANCE-DATETIME>19990101000000'))
        elif kind=='capture_status':capture['response_status']=None;proof['new_actual_capture_ref']=write('wrong_capture.json',capture)
        elif kind=='proof_inference':proof['exact_board_day_inferred']=True
        elif kind=='proof_word_rewrite':proof['quarterly_word_inserted']=True
        elif kind=='firstpub':proof['actual_first_publication_at']='2024-05-01'
        else:
            role='current_CommonStockDeclared_opening_tag' if kind.startswith('tag') or kind=='concept' else 'current_SubsequentEvent_May_context' if kind.startswith('context') else 'original_USD_divide_shares_unit';z=next(v for v in proof['physical_original_byte_bindings'] if v['fragment_role']==role);a,b=z['old_primary_byte_range'];primary=Path(proof['original_primary_ref']['path']).read_bytes();old,new={'concept':(b'CommonStockDividendsPerShareDeclared',b'PreferredStockDividendsDeclared_____'),'tag_context':(b'c-65',b'c-99'),'tag_unit':(b'usdPerShare',b'eurPerShare'),'context_CIK':(b'0000701985',b'0000701986'),'context_start':(b'2024-05-01',b'2024-04-01'),'context_end':(b'2024-05-31',b'2024-06-01'),'context_axis':(b'SubsequentEventMember',b'ReportedPeriodMember_'),'unit_USD':(b'iso4217:USD',b'iso4217:EUR'),'unit_shares':(b'xbrli:shares',b'xbrli:amount')}[kind];changed=primary[a:b].replace(old,new);assert len(changed)==b-a;primary=primary[:a]+changed+primary[b:];header=Path(proof['new_actual_main_full_ref']['path']).read_bytes()[:65536];proof['original_primary_ref']=write('changed_primary.htm',primary);proof['new_actual_main_full_ref']=write('changed_full.txt',header+primary);capture['original_HTTP_ref']=proof['new_actual_main_full_ref'];proof['new_actual_capture_ref']=write('changed_capture.json',capture);z['old_fragment_ref']=write('changed_node.html',changed);payload['sec_cash_source_custody_ref']=write('changed_source.json',dict(original_HTTP_ref=proof['new_actual_main_full_ref']))
        scope['source_role_proof_ref']=write('changed_proof.json',proof)
    with pytest.raises((ValueError,AssertionError)):p._class_binding(*args[:3],'Common Stock BBWI The New York Stock Exchange','Bath & Body Works Inc',pin)

@pytest.mark.parametrize('bad',['none','acceptance_month_invented_day','wrong_full','prior'])
def test_ordinal_r22_real_June4_acceptance_clock_before_RAW(tmp_path,monkeypatch,bad):
    args,scope,row,dated,proof,capture,write=ordinal_r22_generated(tmp_path,monkeypatch);b,_=completion_binding();b.update(sec_cash_statement_profile=p.ORDINAL_CURRENT_COMMON,selected_original_cash_statement=scope['original_current_literal'],source_statement_date='2024-06-04',source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=701985,static_submission_transport_proof=dict(original_submission_ref=p._path_sha_ref(proof['new_actual_main_full_ref']),accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.ORDINAL_CURRENT_COMMON,b['selected_original_cash_statement'],args[2],'2024-06-04')
    if bad=='none':assert p._completion_clock(b,args[2]) is True
    else:
        if bad=='acceptance_month_invented_day':b['static_submission_transport_proof']['accepted_at_utc']='2024-05-01T00:00:00Z'
        elif bad=='wrong_full':b['static_submission_transport_proof']['original_submission_ref']=write('wrong_full.txt',b'wrong')
        else:dated['prior_date']='2024-06-05'
        with pytest.raises(ValueError):p._completion_clock(b,args[2])


def record_payable_r24_generated(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts.storage.refresh_sec_event_originals import FilingText
    ex='2024-11-14';write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.RECORD_PAYABLE_COMMON_SCOPES['LPLA|'+ex]);literal=scope['original_current_literal'];needle=scope['current_amount_literal'];at=literal.rfind(needle);tag=('<ix:nonFraction contextRef="'+scope['current_context_ref']+'" unitRef="usdPerShare" name="us-gaap:DividendsPayableAmountPerShare" scale="0">').encode();cash=b'<p>'+literal[:at].encode()+tag+literal[at:at+len(needle)].encode()+b'</ix:nonFraction>'+literal[at+len(needle):].encode()+b'</p>';tagstart=cash.index(tag)
    context=('<xbrli:context id="'+scope['current_context_ref']+'"><xbrli:entity><xbrli:identifier>0001397911</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:SubsequentEventTypeAxis">us-gaap:SubsequentEventMember</xbrldi:explicitMember><xbrldi:explicitMember dimension="us-gaap:DividendsAxis">lpla:O2024Q3DividendsMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>'+scope['current_context_instant']+'</xbrli:instant></xbrli:period></xbrli:context>').encode();unit=b'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';primary=cash+context+unit
    local=pd.Timestamp(scope['publication_accepted_at_utc']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+scope['accession']+'\nCENTRAL INDEX KEY: 0001397911\n').encode();header+=b' '*(65536-len(header));hr=write('generated_header.txt',header);doc=write('generated_primary.htm',primary);full=write('generated_full.txt',header+primary);spans=[('original_current_common_cash',0,len(cash)),('current_CommonPayable_opening_tag',tagstart,tagstart+len(tag)),('current_SubsequentEvent_record_context',len(cash),len(cash)+len(context)),('original_USD_divide_shares_unit',len(cash)+len(context),len(primary))];bindings=[]
    for role,a,b in spans:bindings.append(dict(fragment_role=role,old_primary_byte_range=[a,b],new_full_submission_byte_range=[65536+a,65536+b],old_fragment_ref=write(role+'.html',primary[a:b])))
    capture=dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_HEADER_prefix_equals_old_exactly=True,new_SEC_HEADER_equals_old_exactly=True,original_HTTP_ref=full,source_accepted_at_utc=scope['publication_accepted_at_utc']);cap=write('generated_capture.json',capture);proof=dict(schema='EXACT_CURRENT_COMMON_RECORD_DATE_PAYABLE_CONTEXT_PROOF_R24_R1',event=copy.deepcopy({k:v for k,v in scope.items() if k!='source_role_proof_ref'}),actual_first_publication_at=None,engine_available_at=None,reported_capital_values_used=False,exact_board_day_inferred=False,quarterly_word_inserted=False,current_context_role='RECORD_DATE_NOT_ANNOUNCEMENT_DATE',current_context_date_is_record_not_board_or_announcement=True,new_actual_main_full_ref=dict(full,bytes=65536+len(primary)),new_actual_capture_ref=cap,actual_HEADER_ref=dict(hr,bytes=65536),original_primary_ref=dict(doc,bytes=len(primary)),original_primary_member=dict(text_byte_range=[65536,65536+len(primary)]),physical_original_byte_bindings=bindings,current_original_fragment_ref=bindings[0]['old_fragment_ref']);scope['source_role_proof_ref']=write('generated_proof.json',proof);scopes=copy.deepcopy(p.RECORD_PAYABLE_COMMON_SCOPES);scopes['LPLA|'+ex]=scope;monkeypatch.setattr(p,'RECORD_PAYABLE_COMMON_SCOPES',scopes)
    row=dict(ticker='LPLA',title_of_class='COM',cusip='50212V100',security_id='50212V100',security_id_type='CUSIP',effective_start='2024-11-13',effective_end='2024-11-14');dated=dict(ticker='LPLA',security_uid='CUSIP:50212V100',accounting_sid=scope['accounting_sid'],prior_date=scope['prior_date'],ex_date=ex,same_dated_UID_and_SID=True,share_quantity_effect=False,source_coordinate='RAW_ACTUAL_SHARE',new_legal_CUSIP_authority=False);real=p._base();base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=real.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base);source=write('generated_source.json',dict(original_HTTP_ref=full));payload=dict(sec_cash_statement_profile=p.RECORD_PAYABLE_CURRENT_COMMON,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE,record_payable_exact_current_common_scope=scope,sec_cash_source_custody_ref=source,selected_original_cash_fragment=dict(text=literal,original_fragment_ref=bindings[0]['old_fragment_ref'],original_byte_range=bindings[0]['new_full_submission_byte_range']));entry=dict(identity_binding=dict(issuer='LPL FINANCIAL HOLDINGS INC'),prior_raw_close=dict(prior_date=scope['prior_date']));facts=dict(ticker='LPLA',sec_filer_cik=1397911,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='LPLA',effective_date=ex),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(needle),listing_identity='NASDAQ:LPLA',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,facts,pin],scope,row,dated,proof,capture,write

# R24 synthetic record-date context; generated bytes only, no actual source reads.

def test_record_payable_r24_current_Q3_record_instant_roles_and_registration(tmp_path,monkeypatch):
    owner,_=p._owner();assert p.RECORD_PAYABLE_CURRENT_COMMON in p.PROFILES and p.RECORD_PAYABLE_CURRENT_COMMON in p.SCOPE['profiles'] and p.RECORD_PAYABLE_CURRENT_COMMON in owner._sec_primary_html_cash_terms.__globals__['PROFILES']
    args,scope,row,dated,proof,capture,write=record_payable_r24_generated(tmp_path,monkeypatch);before=copy.deepcopy(args[:3]);assert p._class_binding(*args[:3],'Common Stock LPLA Nasdaq Global Select Market','LPL Financial Holdings Inc',args[3]) is None;assert args[:3]==before
    sem=p.statement_semantics(p.RECORD_PAYABLE_CURRENT_COMMON,scope['original_current_literal'],args[2],'2024-11-04');assert sem['selected_current_amount']=='0.30' and sem['current_context_role']=='RECORD_DATE_NOT_ANNOUNCEMENT_DATE' and sem['current_context_instant']==scope['record_date'] and sem['current_amount_concept']=='us-gaap:DividendsPayableAmountPerShare' and sem['quarter_authority']=='lpla:O2024Q3DividendsMember' and sem['exact_board_day_inferred'] is False and sem['quarterly_word_inserted'] is False and sem['current_amount_from_reported_concept'] is False

@pytest.mark.parametrize('kind',['scope','ticker','CIK','SID','event','record','pay','amount','currency','unit','quantity','available','prior','CUSIP','class','dated_UID','dated_prior','literal_word','insert_quarterly','add_money','current_ref','current_span','concept','tag_context','tag_unit','context_CIK','context_instant','context_quarter','context_axis','unit_USD','unit_shares','source_tamper','header_clock','capture_status','capture_accepted','proof_inference','proof_word_rewrite','proof_context_role','proof_context_date_role','firstpub'])
def test_record_payable_r24_current_record_role_physical_unit_identity_fail_closed(tmp_path,monkeypatch,kind):
    args,scope,row,dated,proof,capture,write=record_payable_r24_generated(tmp_path,monkeypatch);payload,entry,f,pin=args
    if kind=='scope':payload['record_payable_exact_current_common_scope']={}
    elif kind in ('ticker','CIK','SID','record','pay','amount','currency','unit','quantity','available'):f[dict(ticker='ticker',CIK='sec_filer_cik',SID='security_id',record='record_date',pay='pay_date',amount='cash_per_raw_share',currency='currency',unit='amount_unit',quantity='quantity_coordinate',available='available_at')[kind]]=1 if kind in ('CIK','amount') else 'WRONG'
    elif kind=='event':f['exact_frozen_event_key']['effective_date']='2024-11-13'
    elif kind=='prior':entry['prior_raw_close']['prior_date']='2024-11-12'
    elif kind=='CUSIP':row['cusip']='OTHER'
    elif kind=='class':row['title_of_class']='CL A'
    elif kind=='dated_UID':dated['security_uid']='CUSIP:OTHER'
    elif kind=='dated_prior':dated['prior_date']='2024-11-12'
    elif kind in ('literal_word','insert_quarterly','add_money'):
        text=scope['original_current_literal'];payload['selected_original_cash_fragment']['text']=text.replace('common stock','preferred stock') if kind=='literal_word' else text.replace('cash dividend','quarterly cash dividend') if kind=='insert_quarterly' else text+' Annual cash $1.20.'
    elif kind=='current_ref':payload['selected_original_cash_fragment']['original_fragment_ref']=write('wrong_cash.html',b'changed')
    elif kind=='current_span':payload['selected_original_cash_fragment']['original_byte_range'][0]+=1
    else:
        if kind=='source_tamper':Path(proof['original_primary_ref']['path']).write_bytes(b'changed')
        elif kind=='header_clock':proof['actual_HEADER_ref']=write('wrong_header.txt',Path(proof['actual_HEADER_ref']['path']).read_bytes().replace(b'<ACCEPTANCE-DATETIME>',b'<ACCEPTANCE-DATETIME>19990101000000'))
        elif kind in ('capture_status','capture_accepted'):
            capture['response_status' if kind=='capture_status' else 'source_accepted_at_utc']=None if kind=='capture_status' else '2024-11-14T00:00:00Z';proof['new_actual_capture_ref']=write('wrong_capture.json',capture)
        elif kind=='proof_inference':proof['exact_board_day_inferred']=True
        elif kind=='proof_word_rewrite':proof['quarterly_word_inserted']=True
        elif kind=='proof_context_role':proof['current_context_role']='ANNOUNCEMENT_DATE'
        elif kind=='proof_context_date_role':proof['current_context_date_is_record_not_board_or_announcement']=False
        elif kind=='firstpub':proof['actual_first_publication_at']='2024-10-30'
        else:
            role='current_CommonPayable_opening_tag' if kind.startswith('tag') or kind=='concept' else 'current_SubsequentEvent_record_context' if kind.startswith('context') else 'original_USD_divide_shares_unit';z=next(v for v in proof['physical_original_byte_bindings'] if v['fragment_role']==role);a,b=z['old_primary_byte_range'];primary=Path(proof['original_primary_ref']['path']).read_bytes()
            old,new={'concept':(b'DividendsPayableAmountPerShare',b'PreferredDividendAmountShare_'),'tag_context':(b'c-457',b'c-999'),'tag_unit':(b'usdPerShare',b'eurPerShare'),'context_CIK':(b'0001397911',b'0001397912'),'context_instant':(b'2024-11-14',b'2024-10-30'),'context_quarter':(b'O2024Q3DividendsMember',b'O2024Q2DividendsMember'),'context_axis':(b'SubsequentEventMember',b'ReportedPeriodMember_'),'unit_USD':(b'iso4217:USD',b'iso4217:EUR'),'unit_shares':(b'xbrli:shares',b'xbrli:amount')}[kind];new=(new+b'_'*len(old))[:len(old)];changed=primary[a:b].replace(old,new);assert changed!=primary[a:b] and len(changed)==b-a;primary=primary[:a]+changed+primary[b:];header=Path(proof['new_actual_main_full_ref']['path']).read_bytes()[:65536];proof['original_primary_ref']=write('changed_primary.htm',primary);proof['new_actual_main_full_ref']=write('changed_full.txt',header+primary);capture['original_HTTP_ref']=proof['new_actual_main_full_ref'];proof['new_actual_capture_ref']=write('changed_capture.json',capture);z['old_fragment_ref']=write('changed_node.html',changed);payload['sec_cash_source_custody_ref']=write('changed_source.json',dict(original_HTTP_ref=proof['new_actual_main_full_ref']))
        scope['source_role_proof_ref']=write('changed_proof.json',proof)
    with pytest.raises((ValueError,AssertionError)):p._class_binding(*args[:3],'Common Stock LPLA Nasdaq Global Select Market','LPL Financial Holdings Inc',pin)

@pytest.mark.parametrize('bad',['none','record_instead_of_accepted','wrong_full','prior'])
def test_record_payable_r24_real_Nov4_acceptance_clock_before_RAW(tmp_path,monkeypatch,bad):
    args,scope,row,dated,proof,capture,write=record_payable_r24_generated(tmp_path,monkeypatch);b,_=completion_binding();b.update(sec_cash_statement_profile=p.RECORD_PAYABLE_CURRENT_COMMON,selected_original_cash_statement=scope['original_current_literal'],source_statement_date='2024-11-04',source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=1397911,static_submission_transport_proof=dict(original_submission_ref=p._path_sha_ref(proof['new_actual_main_full_ref']),accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.RECORD_PAYABLE_CURRENT_COMMON,b['selected_original_cash_statement'],args[2],'2024-11-04')
    if bad=='none':assert p._completion_clock(b,args[2]) is True
    else:
        if bad=='record_instead_of_accepted':b['static_submission_transport_proof']['accepted_at_utc']='2024-11-14T00:00:00Z'
        elif bad=='wrong_full':b['static_submission_transport_proof']['original_submission_ref']=write('wrong_full.txt',b'wrong')
        else:dated['prior_date']='2024-11-12'
        with pytest.raises(ValueError):p._completion_clock(b,args[2])


def qsr_r27_generated(tmp_path,monkeypatch,key):
    from types import SimpleNamespace
    write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.QSR_COMMON_LP_SCOPES[key]);cash=('<p>'+scope['original_current_literal']+'</p>').encode();local=pd.Timestamp(scope['publication_accepted_at_utc']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+scope['accession']+'\nCENTRAL INDEX KEY: 1618756\n').encode();header+=b' '*(65536-len(header));hr=write('qsr_header.txt',header);cr=write('qsr_current.html',cash);doc=write('qsr_primary.htm',cash);full=write('qsr_full.txt',header+cash)
    capture=dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_HEADER_prefix_equals_old_exactly=True,new_SEC_HEADER_equals_old_exactly=True,original_HTTP_ref=full,source_accepted_at_utc=scope['publication_accepted_at_utc']);cap=write('qsr_capture.json',capture)
    markup='<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';prefix='<p>Dividends declared ($<ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="usdPerShare">';unitbody=write('qsr_unit.htm',(markup+prefix).encode());upr=write('qsr_unit_prefix.htm',prefix.encode());ulocal=pd.Timestamp(scope['source_available_at']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');uh=write('qsr_unit_header.txt',('<ACCEPTANCE-DATETIME>'+ulocal+'\nACCESSION NUMBER: 0001618756-25-999999\nCENTRAL INDEX KEY: 1618756\n').encode());unit=dict(source_document_ref=unitbody,accepted_header_ref=uh,accepted_at_utc=scope['source_available_at'],source_form='10-Q',accession='0001618756-25-999999',capital_fragment_byte_range=[len(markup),len(markup+prefix)],capital_fragment_ref=upr,original_capital_row_literal='Dividends declared ($',USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=0,byte_end=len(markup),original_unit_markup=markup)]);proof=dict(schema='QSR_FOUR_EXACT_COMMON_SHARE_LP_QUARTER_CURRENT_UNIT_SOURCE_PROOF_R27_R1',event={k:v for k,v in scope.items() if k!='source_role_proof_ref'},actual_first_publication_at=None,engine_available_at=None,reported_capital_values_used=False,actual_2026_observation_or_payment_read=False,new_actual_main_full_ref=full,new_actual_capture_ref=cap,actual_HEADER_ref=hr,original_primary_ref=doc,current_original_fragment_ref=cr,physical_original_byte_bindings=[dict(fragment_role='cash',old_primary_byte_range=[0,len(cash)],new_full_submission_byte_range=[65536,65536+len(cash)])],original_unit_helper_input=unit,original_unit_helper_args=dict(issuer_cik=1618756,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='Dividends declared ($'));scope['source_role_proof_ref']=write('qsr_proof.json',proof);scopes=copy.deepcopy(p.QSR_COMMON_LP_SCOPES);scopes[key]=scope;monkeypatch.setattr(p,'QSR_COMMON_LP_SCOPES',scopes)
    row=dict(ticker='QSR',title_of_class='COM',cusip='76131D103',security_id='76131D103',security_id_type='CUSIP',effective_start='2025-01-01',effective_end='2025-12-31');dated=dict(ticker='QSR',prior_date=scope['prior_date'],ex_date=scope['ex_date'],security_uid='CUSIP:76131D103',accounting_sid=scope['accounting_sid'],same_dated_UID_and_SID=True,share_quantity_effect=False,new_legal_CUSIP_authority=False,source_coordinate='RAW_ACTUAL_SHARE');real=p._base();base=SimpleNamespace(SEC_STATIC_SUBMISSION_PROFILE=real.SEC_STATIC_SUBMISSION_PROFILE,_pin=pin,_existing_frozen_common_identity=lambda *a,**kw:dict(original_source_row=row),_static_submission_dated_raw_identity=lambda *a,**kw:dated);monkeypatch.setattr(p,'_base',lambda:base);sr=write('qsr_source.json',dict(original_HTTP_ref=full));payload=dict(sec_cash_statement_profile=p.QSR_CURRENT_COMMON_LP,sec_source_transport_profile=base.SEC_STATIC_SUBMISSION_PROFILE,qsr_exact_current_common_lp_scope=scope,sec_cash_source_custody_ref=sr,selected_original_cash_fragment=dict(text=scope['original_current_literal'],original_fragment_ref=cr,original_byte_range=[65536,65536+len(cash)]));entry=dict(identity_binding=dict(issuer='Restaurant Brands International Inc.'),prior_raw_close=dict(prior_date=scope['prior_date']));f=dict(ticker='QSR',sec_filer_cik=1618756,security_id=scope['accounting_sid'],exact_frozen_event_key=dict(ticker='QSR',effective_date=scope['ex_date']),record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(scope['current_amount_literal']),issuer_jurisdiction='CA',listing_identity='NYSE:QSR',currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,f,pin],scope,row,dated,proof,capture,write


@pytest.mark.parametrize('key',tuple(p.QSR_COMMON_LP_SCOPES))
def test_qsr_r27_current_common_lp_quarter_roles_and_independent_original_USD(tmp_path,monkeypatch,key):
    owner,anchors=p._owner();assert p.QSR_CURRENT_COMMON_LP in p.PROFILES and p.QSR_CURRENT_COMMON_LP in p.SCOPE['profiles'];assert owner._sec_frozen_cash_terms.__globals__['_qsr_subject_jurisdiction'] is p._qsr_subject_jurisdiction;assert owner.cash.adjudicate_post_verified_cash_ex.__globals__['_qsr_cash_jurisdiction'] is p._qsr_cash_jurisdiction;args,scope,row,dated,proof,capture,write=qsr_r27_generated(tmp_path,monkeypatch,key);before=copy.deepcopy(args[:3]);assert p._qsr_common_lp_support(*args) is None;assert p._qsr_source_legal_invalid(True,*args[:3],scope['source_listing_literal'],scope['source_registrant_literal'],'Canada',[('QSR','New York Stock Exchange')],args[3]) is False;assert args[:3]==before;sem=p.statement_semantics(p.QSR_CURRENT_COMMON_LP,scope['original_current_literal'],args[2],scope['source_publication_date']);assert sem['amount_roles']==scope['original_amount_roles'] and sem['LP_obligation_retained'] and not sem['LP_account_position_created'] and not sem['annual_rate_divided_or_inferred'] and not sem['quarterly_word_inserted'];assert sem['known_future_payment_schedule_only']==(scope['ex_date']=='2025-12-23') and not sem['actual_2026_payment_or_observation_read']


@pytest.mark.parametrize('kind',['scope','wrongtuple','CID','SID','currency','unit','LPonly','missingquarter','missingpershare','amount','record','header','full','lateunit','source','concept','CUSIP','UID','charter','listing'])
def test_qsr_r27_exact_unit_subject_bytes_roles_and_clock_fail_closed(tmp_path,monkeypatch,kind):
    args,scope,row,dated,proof,capture,write=qsr_r27_generated(tmp_path,monkeypatch,'QSR|2025-03-21');payload,entry,f,pin=args
    if kind=='scope':payload['qsr_exact_current_common_lp_scope']={}
    elif kind=='wrongtuple':f['exact_frozen_event_key']['effective_date']='2025-03-20'
    elif kind=='CID':f['sec_filer_cik']=1
    elif kind=='SID':f['security_id']='US.QSR'
    elif kind=='currency':f['currency']='CAD'
    elif kind=='amount':f['cash_per_raw_share']=2.48
    elif kind=='record':f['record_date']='2025-03-20'
    elif kind=='LPonly':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('per common share and ','per ')
    elif kind=='missingquarter':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('first quarter','period')
    elif kind=='missingpershare':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('per common share','common shares')
    elif kind=='header':Path(proof['actual_HEADER_ref']['path']).write_bytes(b'wrong header')
    elif kind=='full':Path(proof['new_actual_main_full_ref']['path']).write_bytes(b'wrong full')
    elif kind=='source':payload['sec_cash_source_custody_ref']=write('wrong_source.json',dict(original_HTTP_ref=write('otherfull.txt',b'other')))
    elif kind=='unit':
        u=proof['original_unit_helper_input'];b=Path(u['source_document_ref']['path']).read_bytes().replace(b'iso4217:USD',b'iso4217:CAD');u['source_document_ref']=write('cad_unit.htm',b);u['USD_per_common_share_unit_metadata'][0]['original_unit_markup']=u['USD_per_common_share_unit_metadata'][0]['original_unit_markup'].replace('USD','CAD')
    elif kind=='concept':proof['original_unit_helper_args']['concept']='us-gaap:Assets'
    elif kind=='lateunit':proof['original_unit_helper_input']['accepted_at_utc']='2025-03-22T12:00:00+00:00'
    elif kind=='CUSIP':row['cusip']='000000000'
    elif kind=='UID':dated['security_uid']='CUSIP:000000000'
    if kind in ('unit','concept','lateunit'):scope['source_role_proof_ref']=write('bad_proof.json',proof)
    with pytest.raises(ValueError):
        if kind in ('charter','listing'):p._qsr_source_legal_invalid(True,payload,entry,f,'Common Stock QSR New York Stock Exchange' if kind=='listing' else scope['source_listing_literal'],scope['source_registrant_literal'],'Delaware' if kind=='charter' else 'Canada',[('QSR','New York Stock Exchange')],pin)
        else:p._qsr_common_lp_support(*args)


def test_qsr_r27_unchanged_other_issuer_US_guard_and_protected_business():
    import ast
    assert p._qsr_subject_jurisdiction(dict(issuer_jurisdiction='CA'),dict(sec_cash_statement_profile=p.MONETARY_COMMON)) is False
    assert p._qsr_cash_jurisdiction(dict(issuer_jurisdiction='CA',sec_frozen_cash_binding=dict(sec_cash_statement_profile=p.MONETARY_COMMON))) is False
    assert p._qsr_cash_currency_basis(dict(sec_cash_statement_profile=p.MONETARY_COMMON),{},'original')=='original'
    assert p._qsr_source_legal_invalid(True,dict(sec_cash_statement_profile=p.MONETARY_COMMON),{}, {},'', '', '', [],lambda x:None) is True
    owner,_=p._cash_owner();source=Path(p.cash.__file__).read_text();node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='adjudicate_post_verified_cash_ex');comparison=[ast.dump(n) for n in ast.walk(node) if isinstance(n,ast.Compare) and 'small_cash_fraction_strict_upper_bound' in ast.unparse(n)];transformed=p._CashExtend().visit(copy.deepcopy(node));assert comparison==[ast.dump(n) for n in ast.walk(transformed) if isinstance(n,ast.Compare) and 'small_cash_fraction_strict_upper_bound' in ast.unparse(n)];assert p._ref(p.cash.__file__)['sha256']==p.CASH_SHA

@pytest.mark.parametrize('key',tuple(p.QSR_COMMON_LP_SCOPES))
@pytest.mark.parametrize('bad',[False,True])
def test_qsr_r27_original_clock_dual_private_cash_entry_not_US_alias(tmp_path,monkeypatch,key,bad):
    args,scope,row,dated,proof,capture,write=qsr_r27_generated(tmp_path,monkeypatch,key);b,_=completion_binding();b.update(sec_cash_statement_profile=p.QSR_CURRENT_COMMON_LP,selected_original_cash_statement=scope['original_current_literal'],source_statement_date=scope['source_publication_date'],source_unique_listed_common_class=None,source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],sec_filer_cik=1618756,currency_basis=p.QSR_UNIT_CURRENCY_BASIS,static_submission_transport_proof=dict(original_submission_ref=proof['new_actual_main_full_ref'],accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.QSR_CURRENT_COMMON_LP,b['selected_original_cash_statement'],args[2],scope['source_publication_date']);f=copy.deepcopy(args[2]);f['sec_frozen_cash_binding']=b
    if bad:
        f['issuer_jurisdiction']='US'
        with pytest.raises(ValueError):p._completion_clock(b,f)
        assert p._qsr_cash_jurisdiction(f) is False
    else:
        assert p._completion_clock(b,f) and p._qsr_cash_jurisdiction(f)
        assert p._qsr_cash_currency_basis(b,f,'old')==p.QSR_UNIT_CURRENCY_BASIS

def alphabet_r28_generated(tmp_path,monkeypatch,key):
    from types import SimpleNamespace
    write,pin=r18_write(tmp_path);scope=copy.deepcopy(p.ALPHABET_ABC_SCOPES[key]);cash=('<p>'+scope['original_current_literal']+'</p>').encode();local=pd.Timestamp(scope['publication_accepted_at_utc']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');header=('<ACCEPTANCE-DATETIME>'+local+'\nACCESSION NUMBER: '+scope['accession']+'\nCENTRAL INDEX KEY: 1652044\n').encode();header+=b' '*(65536-len(header));hr=write('qsr_header.txt',header);cr=write('qsr_current.html',cash);doc=write('qsr_primary.htm',cash);full=write('qsr_full.txt',header+cash)
    capture=dict(response_status=200,actual_HTTP_status_observed=True,old_HTTP_status_remains_UNKNOWN=True,new_HEADER_prefix_equals_old_exactly=True,new_SEC_HEADER_equals_old_exactly=True,original_HTTP_ref=full,source_accepted_at_utc=scope['publication_accepted_at_utc']);cap=write('qsr_capture.json',capture)
    markup='<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>';prefix='<p>Dividends declared ($<ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="usdPerShare">';unitbody=write('qsr_unit.htm',(markup+prefix).encode());upr=write('qsr_unit_prefix.htm',prefix.encode());ulocal=pd.Timestamp(scope['source_available_at']).tz_convert('America/New_York').strftime('%Y%m%d%H%M%S');uh=write('qsr_unit_header.txt',('<ACCEPTANCE-DATETIME>'+ulocal+'\nACCESSION NUMBER: 0001652044-25-999999\nCENTRAL INDEX KEY: 1652044\n').encode());unit=dict(source_document_ref=unitbody,accepted_header_ref=uh,accepted_at_utc=scope['source_available_at'],source_form='10-Q',accession='0001652044-25-999999',capital_fragment_byte_range=[len(markup),len(markup+prefix)],capital_fragment_ref=upr,original_capital_row_literal='Dividends declared ($',USD_per_common_share_unit_metadata=[dict(id='usdPerShare',byte_start=0,byte_end=len(markup),original_unit_markup=markup)]);proof=dict(schema='ALPHABET_EXACT_ABC_CURRENT_SHARE_CASH_UNIT_SOURCE_ROLE_PROOF_R28_R1',event={k:v for k,v in scope.items() if k!='source_role_proof_ref'},actual_first_publication_at=None,engine_available_at=None,reported_capital_values_used=False,actual_2026_observation_or_payment_read=False,new_actual_main_full_ref=full,new_actual_capture_ref=cap,actual_HEADER_ref=hr,original_primary_ref=doc,current_original_fragment_ref=cr,physical_original_byte_bindings=[dict(fragment_role='cash',old_primary_byte_range=[0,len(cash)],new_full_submission_byte_range=[65536,65536+len(cash)])],original_unit_helper_input=unit,original_unit_helper_args=dict(issuer_cik=1652044,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='Dividends declared ($'));scope['source_role_proof_ref']=write('qsr_proof.json',proof);scopes=copy.deepcopy(p.ALPHABET_ABC_SCOPES);scopes[key]=scope;monkeypatch.setattr(p,'ALPHABET_ABC_SCOPES',scopes)
    row=dict(ticker=scope['ticker'],title_of_class=scope['original_frozen_class_literal'],cusip=scope['original_CUSIP'],security_id=scope['original_CUSIP'],security_id_type='CUSIP',effective_start='2024-01-01',effective_end='2025-12-31');dated=dict(ticker=scope['ticker'],prior_date=scope['prior_date'],ex_date=scope['ex_date'],security_uid='CUSIP:'+scope['original_CUSIP'],accounting_sid=scope['accounting_sid'],same_dated_UID_and_SID=True,share_quantity_effect=False,new_legal_CUSIP_authority=False,source_coordinate='RAW_ACTUAL_SHARE');real=p._base();base=SimpleNamespace(SEC_STATIC_PRIMARY_BODY_PROFILE=real.SEC_STATIC_PRIMARY_BODY_PROFILE,_pin=pin);monkeypatch.setattr(p,'_base',lambda:base);sr=write('alphabet_source.json',dict(original_HTTP_ref=full));ir=write('alphabet_frozen_identity.json',dict(rows=[dict(original_source_row=row)]));ur=write('alphabet_support.json',dict(generated=True));key5=dict(ticker=scope['ticker'],effective_date=scope['ex_date'],reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',source_reference='generated_original_binding',source_fingerprint='a'*64);policyraw=b'<p>The company intends to pay quarterly cash dividends in the future.</p>';policyprimary=write('alphabet_original_policy_primary.htm',policyraw);policyfragment=write('alphabet_original_policy_fragment.htm',policyraw);policy=dict(classifier_result=dict(status='SOURCE_CLASS_VERIFIED_ORDINARY'),original_classifier_function='classify_existing_cash',current_amount_not_from_policy=True,current_wording_not_rewritten=True,source_current_context_quarter_inference=False,contiguous_fragment_ref=policyfragment,source_document_ref=policyprimary,accepted_at_utc='2024-04-26T00:22:11+00:00');scope['policy_classifier_receipt_ref']=write('alphabet_original_policy_mechanical_receipt.json',policy);proof['event']={k:v for k,v in scope.items() if k!='source_role_proof_ref'};proof.update(original5field=key5,original_policy_source_primary_ref=policyprimary,original_policy_contiguous_fragment_ref=policyfragment,original_policy_byte_range=[0,len(policyraw)]);physical=proof['physical_original_byte_bindings'][0];physical['old_fragment_ref']=cr
    for role,literal in [('cover_'+scope['listed_common_class'],scope['source_listing_literal']),('charter','Delaware'),('registrant',scope['source_registrant_literal'])]:
        data=('<p>'+literal+'</p>').encode();body=Path(full['path']).read_bytes();rr=write('alphabet_'+role+'.html',data);proof['physical_original_byte_bindings'].append(dict(fragment_role=role,old_fragment_ref=rr,new_full_submission_byte_range=[len(body),len(body)+len(data)]));full=write('alphabet_extended_full_'+role+'.txt',body+data)
    proof['new_actual_main_full_ref']=full;capture['original_HTTP_ref']=full;proof['new_actual_capture_ref']=write('alphabet_final_capture.json',capture);scope['source_role_proof_ref']=write('alphabet_final_proof.json',proof);scopes[key]=scope;sr=write('alphabet_final_source.json',dict(original_HTTP_ref=full));payload=dict(sec_cash_statement_profile=p.ALPHABET_CURRENT_ABC,sec_source_transport_profile=base.SEC_STATIC_PRIMARY_BODY_PROFILE,alphabet_exact_current_abc_scope=scope,sec_cash_source_custody_ref=sr,same_file_cash_identity_support_ref=ur,frozen_account_identity_ref=ir,selected_original_cash_fragment=dict(text=scope['original_current_literal'],original_fragment_ref=cr,original_byte_range=[65536,65536+len(cash)]));entry=dict(identity_binding=dict(issuer='Alphabet Inc.'),prior_raw_close=dict(prior_date=scope['prior_date']));f=dict(ticker=scope['ticker'],sec_filer_cik=1652044,security_id=scope['accounting_sid'],exact_frozen_event_key=key5,record_date=scope['record_date'],pay_date=scope['pay_date'],cash_per_raw_share=float(scope['current_amount_literal']),issuer_jurisdiction='US',listing_identity=scope['listing_identity'],currency='USD',amount_unit=p.cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=p.cash.RAW_OLD_SHARE_COORDINATE,available_at=None);return [payload,entry,f,pin],scope,row,dated,proof,capture,write,policy


@pytest.mark.parametrize('key',tuple(p.ALPHABET_ABC_SCOPES))
def test_alphabet_r28_exact_A_C_per_share_current_shared_unit_policy_and_no_fake_quarter(tmp_path,monkeypatch,key):
    owner,anchors=p._owner();assert p.ALPHABET_CURRENT_ABC in p.PROFILES and p.ALPHABET_CURRENT_ABC in p.CLASS_PROFILES and p.ALPHABET_CURRENT_ABC in p.SCOPE['profiles'];args,scope,row,dated,proof,capture,write,policy=alphabet_r28_generated(tmp_path,monkeypatch,key);before=copy.deepcopy(args[:3]);binding=p._class_binding(*args[:3],scope['source_listing_literal'],scope['source_registrant_literal'],args[3]);assert p._class_allowed(*args[:3],row,binding) and p._subject_class(p.ALPHABET_CURRENT_ABC,args[0],row,scope['source_listing_literal']);assert args[:3]==before and row['title_of_class']=='CAP STK CL '+scope['listed_common_class'];assert p._alphabet_cover_classes(args[0],scope['source_listing_literal'],set())=={scope['listed_common_class']};sem=p.statement_semantics(p.ALPHABET_CURRENT_ABC,scope['original_current_literal'],args[2],scope['source_publication_date'],listed_common_class=scope['listed_common_class']);assert not sem['quarterly_word_inserted'] and not sem['current_context_quarter_inferred'] and not sem['current_amount_from_policy'] and sem['original_source_action_literal']==scope['source_action_literal'];assert sem['certified_source_cash_share_classes']==['A','B','C'] and sem['certified_accounting_cash_share_classes']==[scope['listed_common_class']] and not sem['other_class_account_position_created'];assert p._qsr_source_legal_invalid(True,*args[:3],scope['source_listing_literal'],scope['source_registrant_literal'],'Delaware',[(scope['ticker'],'Nasdaq Stock Market')],args[3]) is False


@pytest.mark.parametrize('kind',['wrongtuple','CID','SID','classB','aliasCOM','wrongCUSIP','wrongkeyfingerprint','USDunitCAD','wrongconcept','lateunit','policy_status','latepolicy','policy_byte_tamper','cash_tamper','cover_tamper','no_pershare','announced_rewrite','wrongpay','LP_holding'])
def test_alphabet_r28_original_A_C_cash_policy_unit_identity_physical_fail_closed(tmp_path,monkeypatch,kind):
    args,scope,row,dated,proof,capture,write,policy=alphabet_r28_generated(tmp_path,monkeypatch,'GOOG|2024-09-09');payload,entry,f,pin=args
    if kind=='wrongtuple':f['exact_frozen_event_key']['effective_date']='2025-06-09'
    elif kind=='CID':f['sec_filer_cik']=1
    elif kind=='SID':f['security_id']='FROZEN_RAW_TRANSPORT_CODE:US.GOOGL'
    elif kind in ('classB','aliasCOM','wrongCUSIP'):
        row['title_of_class']='CAP STK CL B' if kind=='classB' else 'COM' if kind=='aliasCOM' else row['title_of_class'];row['cusip']='02079K305' if kind=='wrongCUSIP' else row['cusip'];payload['frozen_account_identity_ref']=write('bad_identity.json',dict(rows=[dict(original_source_row=row)]))
    elif kind=='wrongkeyfingerprint':f['exact_frozen_event_key']['source_fingerprint']='b'*64
    elif kind=='USDunitCAD':
        u=proof['original_unit_helper_input'];u['source_document_ref']=write('bad_cad_unit.htm',Path(u['source_document_ref']['path']).read_bytes().replace(b'iso4217:USD',b'iso4217:CAD'));u['USD_per_common_share_unit_metadata'][0]['original_unit_markup']=u['USD_per_common_share_unit_metadata'][0]['original_unit_markup'].replace('USD','CAD')
    elif kind=='wrongconcept':proof['original_unit_helper_args']['concept']='us-gaap:Assets'
    elif kind=='lateunit':proof['original_unit_helper_input']['accepted_at_utc']='2024-09-10T12:00:00+00:00'
    elif kind in ('policy_status','latepolicy'):
        if kind=='policy_status':policy['classifier_result']['status']='LEGACY_NOT_RECLASSIFIED'
        else:policy['accepted_at_utc']='2024-09-10T12:00:00+00:00'
        scope['policy_classifier_receipt_ref']=write('bad_policy.json',policy);proof['event']['policy_classifier_receipt_ref']=scope['policy_classifier_receipt_ref']
    elif kind=='policy_byte_tamper':Path(proof['original_policy_contiguous_fragment_ref']['path']).write_bytes(b'wrong')
    elif kind=='cash_tamper':Path(proof['current_original_fragment_ref']['path']).write_bytes(b'wrong')
    elif kind=='cover_tamper':Path(next(z['old_fragment_ref']['path'] for z in proof['physical_original_byte_bindings'] if z['fragment_role']=='cover_C')).write_bytes(b'wrong')
    elif kind=='no_pershare':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('per share','cash')
    elif kind=='announced_rewrite':payload['selected_original_cash_fragment']['text']=scope['original_current_literal'].replace('announced','declared')
    elif kind=='wrongpay':f['pay_date']='2024-09-17'
    elif kind=='LP_holding':payload['alphabet_exact_current_abc_scope']=dict(scope,other_class_account_position_created=True)
    if kind in ('USDunitCAD','wrongconcept','lateunit','policy_status','latepolicy'):scope['source_role_proof_ref']=write('bad_final_proof.json',proof)
    with pytest.raises(ValueError):p._alphabet_abc_support(*args[:3],scope['source_listing_literal'],pin)


@pytest.mark.parametrize('key',tuple(p.ALPHABET_ABC_SCOPES))
def test_alphabet_r28_real_three_source_maxclock_and_original_A_C_UID_before_RAW(tmp_path,monkeypatch,key):
    args,scope,row,dated,proof,capture,write,policy=alphabet_r28_generated(tmp_path,monkeypatch,key);b,_=completion_binding();b.update(sec_cash_statement_profile=p.ALPHABET_CURRENT_ABC,selected_original_cash_statement=scope['original_current_literal'],source_statement_date=scope['source_publication_date'],source_unique_listed_common_class=scope['listed_common_class'],source_profile_original_class_row=row,static_submission_dated_raw_identity_proof=dated,original_frozen_raw_CUSIP=scope['original_CUSIP'],original_frozen_class_literal=scope['original_frozen_class_literal'],sec_filer_cik=1652044,currency_basis=p.QSR_UNIT_CURRENCY_BASIS,static_submission_transport_proof=dict(original_submission_ref=proof['new_actual_main_full_ref'],accepted_at_utc=scope['publication_accepted_at_utc']));b['source_profile_completion']=p.statement_semantics(p.ALPHABET_CURRENT_ABC,b['selected_original_cash_statement'],args[2],scope['source_publication_date'],listed_common_class=scope['listed_common_class']);assert p._completion_clock(b,args[2]) and p._completion_listed_class(b,args[2]);dated['security_uid']='CUSIP:000000000'
    with pytest.raises(ValueError):p._completion_clock(b,args[2])


def test_alphabet_r28_native_path_SHA_consumer_scope_preserves_producer_ref_metadata():
    for scope in p.ALPHABET_ABC_SCOPES.values():
        assert set(scope['source_role_proof_ref'])=={'path','sha256'}
        producer=copy.deepcopy(scope);producer['source_role_proof_ref']['bytes']=100
        consumer=copy.deepcopy(producer);consumer['source_role_proof_ref']=p._path_sha_ref(consumer['source_role_proof_ref'])
        assert consumer==scope and producer['source_role_proof_ref']['bytes']==100

@pytest.mark.parametrize('kind',['path','SHA','missingref'])
def test_alphabet_r28_pathSHA_wrong_or_missing_scope_ref_fails_before_SOURCE(tmp_path,monkeypatch,kind):
    args,scope,row,dated,proof,capture,write,policy=alphabet_r28_generated(tmp_path,monkeypatch,'GOOG|2024-09-09');assert p._alphabet_abc_support(*args[:3],scope['source_listing_literal'],args[3]) is not None
    consumer=copy.deepcopy(scope)
    if kind=='path':consumer['source_role_proof_ref']['path']=str(tmp_path/'other.json')
    elif kind=='SHA':consumer['source_role_proof_ref']['sha256']='b'*64
    else:del consumer['source_role_proof_ref']
    args[0]['alphabet_exact_current_abc_scope']=consumer
    with pytest.raises(ValueError,match='R28_EXACT_SOURCE_ORIGINAL_COMMON_USD_RAW_UNIT_REQUIRED'):p._alphabet_abc_support(*args[:3],scope['source_listing_literal'],args[3])


HLT_R30_LITERAL = "Hilton's board of directors authorized a regular quarterly cash dividend of $0.15 per share of common stock to b e paid on March 28, 2024 to holders of record of its common stock as of the close of business on February 23, 2024."


def _r30_synthetic_unit_event(tmp_path,ticker='CRM'):
    import hashlib
    cik=1108524 if ticker=='CRM' else 1585689
    def put(name,data):
        f=tmp_path/name;f.write_bytes(data);return dict(path=str(f),sha256=hashlib.sha256(data).hexdigest())
    header=put('header',('CENTRAL INDEX KEY: '+str(cik)+'\n<ACCEPTANCE-DATETIME>20240306163248\nACCESSION NUMBER: 0001108524-24-000005').encode())
    unit=b'<xbrli:unit id="u"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    prefix=b'<p>cash dividend of $<ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="u">'
    spans=[];body=unit+prefix
    values={'original_CRM_cover_symbol':'CRM','original_common_cover_class':'Common Stock, par value $0.001 per share','original_registrant_CIK':'0001108524','original_registrant_name':'Salesforce, Inc.'} if ticker=='CRM' else {'COMMON_LISTING_CELL_0':'Common Stock, $0.01 par value per share','COMMON_LISTING_CELL_1':'HLT','COMMON_LISTING_CELL_2':'New York Stock Exchange','REGISTRANT_NAME':'Hilton Worldwide Holdings Inc.','INCORPORATION':'Delaware'}
    for role,text in values.items():
        part=('<p>'+text+'</p>').encode();a=len(body);body+=part;spans.append(dict(role=role,original_physical_byte_range=[a,len(body)],original_fragment_ref=put(role,part)))
    doc=put('body',body);unitinput=dict(issuer_cik=cik,common_stock_XBRL_concept='us-gaap:CommonStockDividendsPerShareDeclared',exact_current_event_dividend_amount_from_capital_row=False,current_event_payment_from_financial_paid_row=False,numeric_CommonStock_value_body_not_read=True,accepted_header_ref=header,accepted_at_utc='2024-03-06T21:32:48+00:00',source_form='10-K',accession='0001108524-24-000005',source_document_ref=doc,capital_fragment_byte_range=[len(unit),len(unit)+len(prefix)],capital_fragment_ref=put('prefix',prefix),original_capital_row_literal='cash dividend of $',USD_per_common_share_unit_metadata=[dict(id='u',byte_start=0,byte_end=len(unit),original_unit_markup=unit.decode())])
    return dict(ticker=ticker,issuer_cik=cik,unit=unitinput,current_amount_not_from_unit=True,current_source_literal_rewritten=False,independent_common_cover_fragments=spans,source_full_ref=doc,source_available_no_later_than='2024-06-28T01:57:03+00:00',prior_date='2024-07-08',actual_first_publication_at=None,engine_available_at=None,current_source_explicit_common=ticker=='HLT')


def test_r30_common_concept_plus_cover_unit_only_not_generic_visible_phrase(tmp_path):
    event=_r30_synthetic_unit_event(tmp_path)
    assert p._crm_hlt_unit_source(event,lambda r:Path(r['path']))['id']=='u'
    for field,value in [('issuer_cik',999),('common_stock_XBRL_concept','us-gaap:PreferredStockDividendsPerShareDeclared'),('exact_current_event_dividend_amount_from_capital_row',True),('numeric_CommonStock_value_body_not_read',False)]:
        bad=copy.deepcopy(event);bad['unit'][field]=value
        with pytest.raises(ValueError):p._crm_hlt_unit_source(bad,lambda r:Path(r['path']))
    bad=copy.deepcopy(event);bad['independent_common_cover_fragments']=[]
    with pytest.raises(ValueError,match='GENERIC_PHRASE'):p._crm_hlt_unit_source(bad,lambda r:Path(r['path']))


@pytest.mark.parametrize('change',['CAD_UNIT','WRONG_COMMON_TAG','NUMERIC_VALUE','WRONG_SYMBOL','POSTPRIOR_UNIT'])
def test_r30_nonvalue_unit_and_original_common_source_negatives(tmp_path,change):
    event=_r30_synthetic_unit_event(tmp_path);unit=event['unit']
    if change=='CAD_UNIT':unit['USD_per_common_share_unit_metadata'][0]['original_unit_markup']=unit['USD_per_common_share_unit_metadata'][0]['original_unit_markup'].replace('iso4217:USD','iso4217:CAD')
    elif change=='WRONG_COMMON_TAG':Path(unit['capital_fragment_ref']['path']).write_bytes(b'cash dividend')
    elif change=='NUMERIC_VALUE':unit['capital_fragment_byte_range'][1]+=1
    elif change=='WRONG_SYMBOL':Path(event['independent_common_cover_fragments'][0]['original_fragment_ref']['path']).write_text('<p>OTHER</p>')
    else:unit['accepted_at_utc']='2024-07-09T16:00:00+00:00'
    with pytest.raises((ValueError,IndexError)):p._crm_hlt_unit_source(event,lambda r:Path(r['path']))


def test_r30_hlt_authorized_action_fixed_pay_words_preserved(monkeypatch):
    e=dict(source_terms_literal=HLT_R30_LITERAL)
    monkeypatch.setattr(p,'_crm_hlt_source_event',lambda *a:e)
    f=dict(ticker='HLT',security_id='FROZEN_RAW_TRANSPORT_CODE:US.HLT',sec_filer_cik=1585689,exact_frozen_event_key={'effective_date':'2024-02-22'},cash_per_raw_share=.15,record_date='2024-02-23',pay_date='2024-03-28')
    got=p.statement_semantics(p.HLT_AUTHORIZED_COMMON_UNIT,HLT_R30_LITERAL,f,'2024-02-07')
    assert got['original_action_literal']=='authorized' and got['original_text_not_rewritten'] and not got['private_board_date_inferred']
    for text in [HLT_R30_LITERAL.replace('authorized','declared'),HLT_R30_LITERAL.replace('to b e paid on','payable on'),HLT_R30_LITERAL.replace('paid on','paid on or before'),HLT_R30_LITERAL.replace('common stock','preferred stock')]:
        with pytest.raises(ValueError):p.statement_semantics(p.HLT_AUTHORIZED_COMMON_UNIT,text,f,'2024-02-07')
    for key,value in [('ticker','OTHER'),('cash_per_raw_share',.30),('pay_date','2024-03-27'),('sec_filer_cik',1108524)]:
        with pytest.raises(ValueError):p.statement_semantics(p.HLT_AUTHORIZED_COMMON_UNIT,HLT_R30_LITERAL,dict(f,**{key:value}),'2024-02-07')


def test_r30_crm_bridge_exact_scope_not_msft_or_new_identity():
    bridge=dict(schema='CRM_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R30',scope=p.CRM_ONE_SCOPE,ticker='CRM',ex_date='2024-07-09',security_uid='CUSIP:79466L302',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.CRM',source_owner_ref=p._ref(p.__file__))
    assert p._msft_raw_bridge_allowed(bridge)
    for key,value in [('ticker','MSFT'),('security_uid','CUSIP:594918104'),('ex_date','2023-05-18'),('scope',p.MSFT_HTML_SIX_SCOPE)]:assert not p._msft_raw_bridge_allowed(dict(bridge,**{key:value}))


def test_r30_owner_routes_preserve_original_cash_math():
    owner,proof=p._owner()
    assert owner.cash.normal_cash_ex_date.__code__ is p.cash.normal_cash_ex_date.__code__
    assert owner.cash._guard.__code__ is p.cash._guard.__code__
    assert owner._post_native_cash_raw_namespace.__code__.co_names==p._base()._post_native_cash_raw_namespace.__code__.co_names or proof['msft__post_native_cash_raw_namespace']=={'post_native_schema_only':1}
