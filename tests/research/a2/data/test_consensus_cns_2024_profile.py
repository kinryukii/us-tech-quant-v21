"""Generated CNS binding cases only; no observed cash, price, or test-year rows."""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from scripts.research.a2.data import consensus_cash_source_profile_completion as p

CNS_AST_ANCHORS = {'_cns_tuple':'29f7e395b5167cd3f5089cd9a49aabf03c52ddd392c2542f15bcd0b3538631d4','_CnsExtend':'643a957167a1cf4e1719de0e929ab86eb133e1fbd88a8af6a339eeddf58c18c1','_cash_owner':'1baad07909d16ed8fc9c6e3362c700c40a5bcc9002d9f85647b9bb82003cceda'}
EXPECTED_BASE_SHA = '3aafa77d7637e08032041d884bbd8ad03f6c7fe5e5d08996c51c3a87fa7b7398'
TUPLES = {
    2024: dict(record='2024-11-11', projected='2024-11-08', notice='a9503', published='2024-10-11', page=2,
        primary='https://www.dtcc.com/-/media/Files/pdf/2024/10/11/a9503.pdf',
        capture='https://web.archive.org/web/20241102074151id_/https://www.dtcc.com/-/media/Files/pdf/2024/10/11/a9503.pdf',
        pdf='f8c59501fe1a7473b2dd19d6bd4cf99d5aafc68102f8214bd7c829bb290c5396',
        section='6b48426e16ab34516a95ee69584d8c95222ca1b58ac192c9841b6bc5abe97b27'),
    2025: dict(record='2025-11-11', projected='2025-11-10', notice='a9648', published='2025-10-02', page=1,
        primary='https://www.dtcc.com/-/media/Files/pdf/2025/10/2/a9648.pdf',
        capture='https://files.dtcc.com/download/assets/a9648/5d1b3be0ceb411f08977de3dd66d09b0',
        pdf='90607850a1cb000ea9c734ab02f74af0b8b45daf87ef84a1df1b441116ab996a',
        section='829f987ac599ed96f03b4979a867039b5906f29580a6221dde7316ef5840dc4d'),
}


def generated_binding(year):
    t = TUPLES[year]
    calendar = pd.bdate_range(f'{year}-11-01', f'{year}-11-15')
    ref = lambda name, digest: dict(path=f'D:/synthetic_cns/{name}', sha256=digest)
    key = dict(ticker='SYN', effective_date=t['projected'], reason='VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY',
               source_reference='generated://original-event', source_fingerprint='c'*64)
    binding = dict(policy_id=p.cash.NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH,
        status='PINNED_NSCC_CNS_BANK_HOLIDAY_RECORD_PROJECTION',
        record_projection_role='ALL_SECURITIES_PUBLISHED_RECORD_DATE_NSCC_CNS_RESEARCH_ONLY',
        published_record_date=t['record'], cns_projected_record_date=t['projected'], notice_number=t['notice'],
        notice_publication_date=t['published'], notice_section='CNS Dividend Processing', notice_page_zero_based=t['page'],
        notice_primary_url=t['primary'], actual_capture_url=t['capture'], published_record_preserved=True,
        cns_settlement_on_published_record_date=False, cns_closing_positions_identical=True,
        market_session_on_published_record_date=True, source_declared_ex_date=None, independent_actual_ex_date=None,
        available_at=None, historical_availability_authority='UNKNOWN', exchange_notice_authority='UNKNOWN',
        actual_exchange_ex_authority='UNKNOWN', strict_PIT=False, production_qualified=False, quote_qualified=False,
        certified_NAV=False, calendar_binding=dict(status='SOURCE_BOUND_LEGAL_SESSION_CALENDAR',
            session_dates_sha256=p.cash._hash([str(day.date()) for day in calendar]),
            source_reference='generated://full-original-trading-calendar', source_fingerprint='d'*64),
        notice_source_ref=ref('notice.pdf',t['pdf']), notice_section_ref=ref('section.txt',t['section']),
        notice_section_source_sha256=t['pdf'], issuer_record_source_ref=ref('issuer.html','a'*64),
        security_identity_source_ref=ref('identity.json','b'*64), exact_original_frozen_event_key=key,
        ticker='SYN', security_id='FROZEN_RAW_TRANSPORT_CODE:US.SYN', listing_identity='NYSE:SYN',
        ex_date=t['projected'], pay_date=f'{year}-11-14')
    facts = dict(ticker='SYN', security_id=binding['security_id'], listing_identity='NYSE:SYN',
        pay_date=binding['pay_date'], exact_frozen_event_key=copy.deepcopy(key), issuer_source_fingerprint='a'*64,
        identity_source_fingerprint='b'*64, ex_date_provenance_role=p.cash.NSCC_CNS_RECORD_RESEARCH_ROLE)
    return binding, calendar, facts


def validate(owner, binding, calendar, facts=None, record=None, end='2026-01-01'):
    return owner.validate_cns_bank_holiday_record_binding(binding,calendar=calendar,
        record_date=record or binding['published_record_date'],scope_end_exclusive=end,facts=facts)


@pytest.fixture(scope='module')
def owner():
    tree=ast.parse(Path(p.__file__).read_text(encoding='utf-8'))
    anchors={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest() for n in tree.body if getattr(n,'name',None) in CNS_AST_ANCHORS}
    assert anchors==CNS_AST_ANCHORS
    assert hashlib.sha256(Path(p.cash.__file__).read_bytes()).hexdigest()==EXPECTED_BASE_SHA
    owner,anchors=p._cash_owner()
    assert anchors['validate_cns_bank_holiday_record_binding']==dict(record_whitelist=1,notice_field=6,source_sha=3)
    assert owner.normal_cash_ex_date.__code__ is p.cash.normal_cash_ex_date.__code__
    assert owner.normal_cash_ex_date.__globals__['validate_cns_bank_holiday_record_binding'] is owner.validate_cns_bank_holiday_record_binding
    return owner


@pytest.mark.parametrize('year',[2024,2025])
def test_exact_tuple_uses_single_native_coordinate_and_preserves_old_2025(owner,year):
    binding,calendar,facts=generated_binding(year)
    before=copy.deepcopy(binding)
    assert validate(owner,binding,calendar,facts)==pd.Timestamp(TUPLES[year]['projected'])
    assert owner.normal_cash_ex_date(binding['published_record_date'],calendar,scope_end_exclusive='2026-01-01',
        policy=p.cash.NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH,cns_bank_holiday_record_binding=binding)==(pd.Timestamp(TUPLES[year]['projected']),'TPLUS1')
    assert binding==before and binding['published_record_date']==f'{year}-11-11'
    if year==2025:
        assert validate(p.cash,binding,calendar,facts)==validate(owner,binding,calendar,facts)
    else:
        with pytest.raises(ValueError,match='EXPLICIT_PRE2026_RECORD_PROJECTION_REQUIRED'):
            validate(p.cash,binding,calendar,facts)
    assert owner.normal_cash_ex_date(binding['published_record_date'],calendar,scope_end_exclusive='2026-01-01')==p.cash.normal_cash_ex_date(binding['published_record_date'],calendar,scope_end_exclusive='2026-01-01')


@pytest.mark.parametrize('field',[ 'notice_source_ref','notice_section_ref','notice_section_source_sha256'])
def test_mixed_2024_2025_source_bytes_cannot_form_valid_tuple(owner,field):
    binding,calendar,_=generated_binding(2024)
    old,_,_=generated_binding(2025)
    binding[field]=copy.deepcopy(old[field])
    with pytest.raises(ValueError,match='EXACT_ORIGINAL_NOTICE_AND_SECTION_REQUIRED'):
        validate(owner,binding,calendar)


@pytest.mark.parametrize('field,value',[
    ('notice_number','a9648'),('notice_page_zero_based',1),
    ('actual_capture_url',TUPLES[2025]['capture']),('published_record_date','2024-11-12')])
def test_notice_and_caller_record_roles_are_not_interchangeable(owner,field,value):
    binding,calendar,_=generated_binding(2024);binding[field]=value
    with pytest.raises(ValueError):validate(owner,binding,calendar,record='2024-11-11')


@pytest.mark.parametrize('mode',['missing_projected','hash_mismatch'])
def test_complete_original_trading_calendar_remains_mandatory(owner,mode):
    binding,calendar,_=generated_binding(2024)
    if mode=='missing_projected':calendar=calendar[calendar!=pd.Timestamp('2024-11-08')]
    else:binding['calendar_binding']['session_dates_sha256']='e'*64
    with pytest.raises(ValueError,match='COMPLETE_ORIGINAL_TRADING_CALENDAR_REQUIRED'):
        validate(owner,binding,calendar)


@pytest.mark.parametrize('field,value',[
    ('available_at','2024-10-11T00:00:00Z'),('actual_exchange_ex_authority','CERTIFIED'),
    ('strict_PIT',True),('independent_actual_ex_date','2024-11-08')])
def test_research_projection_never_creates_publication_or_exchange_certification(owner,field,value):
    binding,calendar,_=generated_binding(2024);binding[field]=value
    with pytest.raises(ValueError,match='EXPLICIT_PRE2026_RECORD_PROJECTION_REQUIRED'):
        validate(owner,binding,calendar)


@pytest.mark.parametrize('mode',['identity','issuer','frozen_key'])
def test_same_security_and_issuer_source_binding_remains_mandatory(owner,mode):
    binding,calendar,facts=generated_binding(2024)
    if mode=='identity':facts['security_id']='FROZEN_RAW_TRANSPORT_CODE:US.OTHER'
    elif mode=='issuer':facts['issuer_source_fingerprint']='f'*64
    else:facts['exact_frozen_event_key']['effective_date']='2024-11-11'
    with pytest.raises(ValueError,match='SAME_ISSUER_IDENTITY_AND_FROZEN_KEY_REQUIRED'):
        validate(owner,binding,calendar,facts)


def test_projected_coordinate_cannot_escape_pre2026_scope_or_explicit_policy(owner):
    binding,calendar,_=generated_binding(2024)
    with pytest.raises(ValueError):validate(owner,binding,calendar,end='2027-01-01')
    with pytest.raises(ValueError,match='EXPLICIT_POLICY_REQUIRED'):
        owner.normal_cash_ex_date('2024-11-11',calendar,scope_end_exclusive='2026-01-01',cns_bank_holiday_record_binding=binding)
    with pytest.raises(ValueError,match='EXCLUSIVE_EXPLICIT_POLICY_REQUIRED'):
        owner.normal_cash_ex_date('2024-11-11',calendar,scope_end_exclusive='2026-01-01',policy=p.cash.NSCC_CNS_BANK_HOLIDAY_RECORD_RESEARCH,cns_bank_holiday_record_binding=binding,source_declared_ex_date='2024-11-08')