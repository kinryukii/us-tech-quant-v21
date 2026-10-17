"""Exact current source roles on the frozen canonical cash factory.

The b7c producer stays at its original path. Only named source parsing hooks are
extended; cash, identity, quote and account arithmetic remain canonical.
"""
from pathlib import Path
from types import FunctionType, SimpleNamespace
from decimal import Decimal
import copy,json,re,hashlib,ast,inspect
import pandas as pd
from scripts.research.a2.data import consensus_cash_source_profile_completion as original

ORIGINAL_FACTORY_REF=dict(path=r'D:\us-tech-quant\scripts\research\a2\data\consensus_cash_source_profile_completion.py',sha256='b7c48d0bc705ab4e939702ce83c678231658ff0b432705baccd82300250da926')
BOOK_REF=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\source131native_bulk\GROUP1_APO4_LVS2_CURRENT_COMMON_QUARTER_SOURCE_BOOK.json',sha256='9510d361870d1011cafac8be1393ed6c9ec55dd556a3dc63ed99ff6920b668ea')
CURRENT_QUARTER='SOURCE131_EXACT_CURRENT_COMMON_QUARTER_WITH_ORIGINAL_USD_UNIT'
DATED_CURRENT='SOURCE131_EXACT_DATED_CURRENT_COMMON_DIRECT_ROLE_WITH_ORIGINAL_USD_UNIT'
GROUP2_BOOK_REF=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\source131native_bulk\GROUP2_CEG_ENTG_DIS_SOURCE_ROLE_BOOK.json',sha256='7c5150863338bc0fa4fb8b2fb118db041eeff72c7e256a03a5becbb06927a0a3')
ARCHIVE_BOOK_REF=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\source131native_bulk\GROUP3_BBWI_TWO_ARCHIVED_SOURCE_ROLE_BOOK.json',sha256='1f817eb777effc335b5b0ea89a02114113000eff4d1bccca046b5ed7635f9aa1')
ARCHIVE_ROLE='SOURCE131_EXACT_ARCHIVED_ORIGINAL_REGULAR_COMMON_WITH_PREPRIOR_USD_UNIT'
ARCHIVE_SUPPORT_SCHEMA='SOURCE131_ORIGINAL_ARCHIVED_COMMON_NONVALUE_USD_UNIT_SUPPORT'
ARCHIVE_SCOPE=dict(profile=ARCHIVE_ROLE,book_ref=ARCHIVE_BOOK_REF,exact_events=[['BBWI','2024-08-23'],['BBWI','2024-11-22']],old_source_profiles_unchanged=True,share_quantity_effect=False)
NAMED_CURRENT='SOURCE131_EXACT_CURRENT_NAMED_CLASS_A_B_COMMON_WITH_ORIGINAL_USD_UNIT'
NAMED_BOOK_REF=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\source131native_bulk\GROUP5_FCNCA_FOUR_CURRENT_NAMED_COMMON_ROLE_BOOK_MAPPED_SID_R3.json',sha256='4534cb3558cb437a6a38a426d801721afbc04c2f04fee41c55fbaf2dbcfdbb52')
ANNOUNCED_BOOK_REF=dict(path=r'D:\us-tech-quant-backtests\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\20261012T025603+0000_4a58260e\derived\source_completion\source131native_bulk\GROUP6_ICE_FOUR_CURRENT_ANNOUNCED_COMMON_ROLE_BOOK_COVER_R2.json',sha256='ab593e34bf10dcea534fed0c498db52ee468ae6be2e03809c23c1ed514556572')
KKR_BOOK_REF={'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\source131native_bulk\\GROUP7_KKR_THREE_DIRECT_NAMED_QUARTER_COMMON_ROLE_BOOK_TEXT_R2.json', 'sha256': '492d5599ee51d3a299039df65630bafb6d3f26653af3e66e5e42c6c25e118a79'}
GLW_BOOK_REF={'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\source131native_bulk\\GROUP8_GLW_ONE_ARCHIVED_CURRENT_COMMON_ROLE_BOOK_DATE_R2.json', 'sha256': 'aff05e56085e85cdae455fa8137a9676369411b4fa7313680cdbb091068150c8'}
GLW_ARCHIVE_SCOPE=dict(profile=ARCHIVE_ROLE,book_ref=GLW_BOOK_REF,exact_events=[['GLW','2025-11-14']],old_source_profiles_unchanged=True,share_quantity_effect=False)
FERG_BOOK_REF={'path': 'D:\\us-tech-quant-backtests\\CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2\\20261012T025603+0000_4a58260e\\derived\\source_completion\\source131native_bulk\\GROUP9_FERG_ONE_PUBLISHED_CURRENT_COMMON_TIMETABLE_ROLE_BOOK_MAIN_URL_R2.json', 'sha256': '996780176d288ff4e1ac3bb77c11e4c6b3ac0086de0a655b04f5ddcbec9d3a94'}
FERG_CURRENT='SOURCE131_EXACT_PUBLISHED_CURRENT_COMMON_QUARTER_TIMETABLE_AND_ORIGINAL_USD_UNIT'
NEW_PROFILES=(CURRENT_QUARTER,DATED_CURRENT,NAMED_CURRENT,FERG_CURRENT)
BOOKS=((BOOK_REF,'SOURCE131_EXACT_CURRENT_COMMON_QUARTER_BOOK_GROUP1'),(GROUP2_BOOK_REF,'SOURCE131_EXACT_DATED_CURRENT_COMMON_ROLE_BOOK_GROUP2'),(ARCHIVE_BOOK_REF,'SOURCE131_EXACT_ARCHIVED_CURRENT_COMMON_ROLE_BOOK_GROUP3'),(NAMED_BOOK_REF,'SOURCE131_EXACT_CURRENT_NAMED_COMMON_ROLE_BOOK_GROUP5'),(ANNOUNCED_BOOK_REF,'SOURCE131_EXACT_ANNOUNCED_COMMON_ROLE_BOOK_GROUP6'),(KKR_BOOK_REF,'SOURCE131_EXACT_CURRENT_COMMON_NAMED_QUARTER_BOOK_GROUP7'),(GLW_BOOK_REF,'SOURCE131_EXACT_ARCHIVED_GLW_CURRENT_QUARTER_COMMON_ROLE_BOOK_GROUP8'),(FERG_BOOK_REF,'SOURCE131_EXACT_PUBLISHED_CURRENT_COMMON_TIMETABLE_BOOK_GROUP9'))
require=original._require

def _ref(path):return original._ref(path)
def _pin(ref):return original._base()._pin(original._path_sha_ref(ref))

def _scope(facts,pinned=_pin):
    from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
    key=facts.get('exact_frozen_event_key',{});matches=[]
    for book_ref,schema in BOOKS:
        path=pinned(book_ref);ranges=[]
        with path.open('rb') as f:
            q=_JsonProjection(f);meta=q.metadata_fields({'schema','RAW_prior_read','native_account_fit_2026'})
        require(meta.get('schema')==schema and meta.get('RAW_prior_read') is False and meta.get('native_account_fit_2026') is False,'BULK_REAL_SOURCE_ROLE_BOOK_REQUIRED')
        with path.open('rb') as f:
            q=_JsonProjection(f);q.descend(('events',));q.expect(b'[')
            while True:
                q.white()
                if q.peek()==b']':q.take();break
                start=q.tell();selected=q.metadata_fields({'original5field_key'});end=q.tell()
                if selected.get('original5field_key')==key:ranges.append((start,end))
                q.white();ch=q.take()
                if ch==b']':break
                require(ch==b',','BULK_SOURCE_BOOK_ARRAY_STRUCTURE_CHANGED')
        for a,b in ranges:
            require(b-a<=65536,'BULK_SELECTED_SOURCE_ENTRY_OVER_ORIGINAL65K_LIMIT')
            with path.open('rb') as f:f.seek(a);e=json.loads(f.read(b-a))
            e['_source_book_ref']=book_ref;matches.append(e)
    require(len(matches)==1,'BULK_EXACT_ORIGINAL131_FIVEFIELD_REQUIRED');e=matches[0]
    require(e['original5field_key']==key and e['ticker']==facts.get('ticker') and e['issuer_CIK']==facts.get('sec_filer_cik') and e['accounting_sid']==facts.get('security_id'),'BULK_SOURCE_ISSUER_RAW_IDENTITY_CHANGED')
    return e


def _literal(e,text):
    require(text==e['original_current_literal'] and not re.search(r'\b(?:preferred|ADS|ADR|adjusted|restated|special|due.bill|liquidat\w*)\b',text,re.I),'BULK_ORIGINAL_CURRENT_COMMON_WORDS_REQUIRED')
    if e['literal_family']=='DECLARED_NAMED_QUARTER_ENDED_CURRENT_COMMON_CASH':
        m=re.fullmatch(r'Apollo Global Management, Inc\. has declared a cash dividend of \$(\d+(?:\.\d+)?) per share of its Common Stock for the (first|second|third|fourth) quarter ended ([A-Za-z]+ \d{1,2}, 20\d{2})\. This dividend will be paid on ([A-Za-z]+ \d{1,2}, 20\d{2}) to holders of record at the close of business on ([A-Za-z]+ \d{1,2}, 20\d{2})\.',text)
        require(m is not None and e['ticker']=='APO' and e['issuer_CIK']==1858681,'BULK_REAL_NAMED_QUARTER_DECLARATION_REQUIRED')
        amount,pay,record=m.group(1),m.group(4),m.group(5);roles=[dict(role='EXPLICIT_CURRENT_COMMON_CASH_FOR_NAMED_QUARTER',literal=amount)]
        require(e['quarter_literal']=='for the '+m.group(2)+' quarter ended '+m.group(3) and e['quarter_period_end_date']==str(pd.Timestamp(m.group(3)).date()),'BULK_QUARTER_PERIOD_IS_NOT_PUBLICATION')
    else:
        require(e['literal_family']=='ANNOUNCED_NEXT_QUARTER_WITH_PRIOR_PAID_COMPARISON','BULK_UNPLANNED_SOURCE_GRAMMAR')
        m=re.fullmatch(r'We paid a quarterly dividend of \$(\d+(?:\.\d+)?) per common share during the quarter\. We announced our next quarterly dividend of \$(\d+(?:\.\d+)?) per common share will be paid on ([A-Za-z]+ \d{1,2}, 20\d{2}), to Las Vegas Sands stockholders of record on ([A-Za-z]+ \d{1,2}, 20\d{2})\.',text)
        require(m is not None and e['ticker']=='LVS' and e['issuer_CIK']==1300514,'BULK_REAL_NEXT_QUARTER_COMMON_ANNOUNCEMENT_REQUIRED')
        amount,pay,record=m.group(2),m.group(3),m.group(4);roles=[dict(role='PREVIOUS_PAID_QUARTER_UNUSED',literal=m.group(1)),dict(role='CURRENT_NEXT_QUARTER_ANNOUNCED_DIRECT_PER_COMMON_SHARE',literal=amount)]
    require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==e['original_money_tokens'] and roles==e['amount_roles'] and amount==e['current_amount_literal'] and str(pd.Timestamp(pay).date())==e['pay_date'] and str(pd.Timestamp(record).date())==e['record_date'],'BULK_CURRENT_AMOUNT_DATES_AND_ALL_PRIOR_ROLES_REQUIRED')
    return amount,roles


def _dated_literal(e,text):
    require(text==e['original_current_literal'] and not re.search(r'\b(?:preferred|ADS|ADR|adjusted|restated|special|due.bill|liquidat\w*)\b',text,re.I),'BULK_ORIGINAL_CURRENT_COMMON_WORDS_REQUIRED')
    family=e['literal_family'];date=r'([A-Za-z]+ \d{1,2}, 20\d{2})'
    if family=='DECLARED_CURRENT_COMMON_QUARTER_WEEKDAY_SCHEDULE':
        m=re.fullmatch(r'Dividend Declaration: Our Board of Directors has declared a quarterly dividend of \$(\d+(?:\.\d+)?) per share on our common stock\. The dividend is payable on (Monday|Tuesday|Wednesday|Thursday|Friday), '+date+r', to shareholders of record as of 5 p\.m\. Eastern time on (Monday|Tuesday|Wednesday|Thursday|Friday), '+date+r'\.',text)
        require(m is not None and e['ticker']=='CEG' and e['issuer_CIK']==1868275,'BULK_REAL_CURRENT_COMMON_WEEKDAY_SCHEDULE_REQUIRED')
        amount,pay,record=m.group(1),m.group(3),m.group(5);require(pd.Timestamp(pay).day_name()==m.group(2) and pd.Timestamp(record).day_name()==m.group(4),'BULK_WEEKDAY_DATE_CONTRADICTION');roles=[dict(role='CURRENT_QUARTER_COMMON_DIRECT_LITERAL',literal=amount)]
    elif family=='ANNOUNCED_BOARD_CURRENT_QUARTER_WITH_NONVALUE_COMMON_UNIT':
        m=re.fullmatch(r'On '+date+r', Entegris, Inc\. announced that its board of directors has declared a quarterly cash dividend of \$(\d+(?:\.\d+)?) per share to be paid on '+date+r' to shareholders of record on the close of business on '+date+r'\. A copy of this news release is attached hereto as Exhibit 99\.1 and is incorporated herein by reference\.',text)
        require(m is not None and e['ticker']=='ENTG' and e['issuer_CIK']==1101302 and 'common' not in text.lower(),'BULK_REAL_CURRENT_BOARD_QUARTER_LITERAL_REQUIRED')
        amount,pay,record=m.group(2),m.group(3),m.group(4);roles=[dict(role='CURRENT_QUARTER_DIRECT_LITERAL_INDEPENDENT_COMMON_UNIT',literal=amount)]
        require(pd.Timestamp(m.group(1))<=pd.Timestamp(e['source_publication_date']),'BULK_PUBLICATION_NOT_PRIVATE_BOARD_DATE')
    elif family=='PASSIVE_DECLARED_DIRECT_NAMED_QUARTER_CURRENT_COMMON':
        m=re.fullmatch(r'A dividend of [$](\d+[.]\d+) per share of common stock of KKR & Co[.] Inc[.] has been declared for the (first|second|third|fourth) quarter of (20\d{2}), which will be paid on '+date+r' to holders of record of common stock as of the close of business on '+date+r'[.]',text)
        require(m is not None and e['ticker']=='KKR' and e['issuer_CIK']==1404912 and e['_source_book_ref']==KKR_BOOK_REF and e['current_source_explicit_common'] is True,'BULK_REAL_PASSIVE_CURRENT_COMMON_NAMED_QUARTER_REQUIRED')
        amount,pay,record=m.group(1),m.group(4),m.group(5);roles=[dict(role='DIRECT_DECLARED_CURRENT_NAMED_QUARTER_PER_COMMON_SHARE',literal=amount)]
        require(e['quarter_literal']=='for the '+m.group(2)+' quarter of '+m.group(3),'BULK_CURRENT_NAMED_QUARTER_NOT_POLICY_OR_PUBLICATION')
    elif family=='ANNOUNCED_DIRECT_NAMED_QUARTER_WITH_NONVALUE_COMMON_UNIT':
        m=re.fullmatch(r'On '+date+r', we announced a [$](\d+[.]\d+) per share dividend for the (first|second|third|fourth) quarter of (20\d{2}) (?:with the dividend )?payable on '+date+r' to stockholders of record as of '+date+r'[.]',text)
        require(m is not None and e['ticker']=='ICE' and e['issuer_CIK']==1571949 and e['_source_book_ref']==ANNOUNCED_BOOK_REF and 'common' not in text.lower(),'BULK_REAL_CURRENT_NAMED_QUARTER_ANNOUNCED_LITERAL_REQUIRED')
        amount,pay,record=m.group(2),m.group(5),m.group(6);roles=[dict(role='DIRECT_ANNOUNCED_CURRENT_NAMED_QUARTER_PER_SHARE',literal=amount)]
        require(e['quarter_literal']=='for the '+m.group(3)+' quarter of '+m.group(4) and pd.Timestamp(m.group(1))<=pd.Timestamp(e['source_publication_date']),'BULK_ORIGINAL_ANNOUNCED_QUARTER_NOT_PUBLICATION_REWRITE')
    else:
        require(family=='DIRECT_TWO_INSTALLMENT_CURRENT_CASH','BULK_UNPLANNED_SOURCE_GRAMMAR')
        m=re.fullmatch(r'◦ The Board has declared a cash dividend of \$(\d+(?:\.\d+)?) per share, payable in two installments of \$(\d+(?:\.\d+)?) per share, payable on '+date+r' \(record date '+date+r'\) and '+date+r' \(record date '+date+r'\)',text)
        require(m is not None and e['ticker']=='DIS' and e['issuer_CIK']==1744489 and e['frequency_not_quarterly'] is True and 'quarter' not in text.lower(),'BULK_REAL_DIRECT_TWO_INSTALLMENT_LITERAL_REQUIRED')
        amount,pay,record=m.group(2),m.group(3),m.group(4);roles=[dict(role='TOTAL_TWO_INSTALLMENTS_NOT_CURRENT_AMOUNT',literal=m.group(1)),dict(role='DIRECT_FIRST_INSTALLMENT_RECORD_2025DEC15_PAY_2026JAN15',literal=amount)]
        require(e['unused_second_schedule']==dict(record_date=str(pd.Timestamp(m.group(6)).date()),pay_date=str(pd.Timestamp(m.group(5)).date()),amount_literal=amount,actual2026_read=False) and pd.Timestamp(m.group(6))>=pd.Timestamp('2026-01-01'),'BULK_SECOND_ANNOUNCED_SCHEDULE_RETAINED_UNUSED')
    require(re.findall(r'\$\s*(\d+(?:\.\d+)?)',text)==e['original_money_tokens'] and roles==e['amount_roles'] and amount==e['current_amount_literal'] and str(pd.Timestamp(pay).date())==e['pay_date'] and str(pd.Timestamp(record).date())==e['record_date'],'BULK_CURRENT_AMOUNT_DATES_AND_ALL_PRIOR_ROLES_REQUIRED')
    return amount,roles


def semantics(text,facts,publication,*,listed_common_class=None):
    e=_scope(facts);dated=e['literal_family'] not in ('DECLARED_NAMED_QUARTER_ENDED_CURRENT_COMMON_CASH','ANNOUNCED_NEXT_QUARTER_WITH_PRIOR_PAID_COMPARISON');amount,roles=_dated_literal(e,text) if dated else _literal(e,text)
    require(listed_common_class is None and Decimal(str(facts.get('cash_per_raw_share')))==Decimal(amount) and facts.get('record_date')==e['record_date'] and facts.get('pay_date')==e['pay_date'] and pd.Timestamp(publication)==pd.Timestamp(e['source_publication_date']),'BULK_EXACT_COMMON_CURRENT_AMOUNT_AND_PUBLIC_CLOCK_REQUIRED')
    result=dict(profile=DATED_CURRENT if dated else CURRENT_QUARTER,selected_current_amount=amount,amount_roles=roles,record_date=e['record_date'],pay_date=e['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_book_ref=e.get('_source_book_ref',BOOK_REF),source_role_consumer_ref=_ref(__file__),original_factory_ref=ORIGINAL_FACTORY_REF,original_text_not_rewritten=True,quarter_authority=e['quarter_literal'],quarter_period_end_not_publication=True,current_from_prior_paid_or_reported_concept=False,announced_not_relabelled_declared=True,annual_rate_divided_or_inferred=False)
    if dated:result.update(current_source_explicit_common=e['current_source_explicit_common'],current_currency_word_present=e['current_source_explicit_USD'],frequency_not_quarterly=e.get('frequency_not_quarterly',False))
    return result


def _ferg_semantics(text,facts,publication,*,listed_common_class=None):
    e=_scope(facts);require(e['_source_book_ref']==FERG_BOOK_REF and e['ticker']=='FERG' and e['issuer_CIK']==2011641 and e['literal_family']=='PUBLISHED_CURRENT_COMMON_QUARTER_PAYMENT_TIMETABLE' and text==e['original_current_literal'] and listed_common_class is None,'BULK_FERG_EXACT_PUBLIC_TIMETABLE_ROLE_REQUIRED')
    m=re.fullmatch(r'The timetable for payment of the quarterly divid end of [$](\d+[.]\d+) per share is as follows:',text);require(m is not None,'BULK_FERG_ORIGINAL_TIMETABLE_NOT_DECLARED_REWRITE')
    from scripts.storage.refresh_sec_event_originals import FilingText
    raw=_pin(e['current_timetable_fragment_ref']).read_bytes();require(len(raw)<=2048,'BULK_FERG_SMALL_DATE_TIMETABLE_ONLY');parser=FilingText();parser.feed(raw.decode());dates=' '.join(' '.join(parser.parts).split());require(dates==e['original_timetable_literal'],'BULK_FERG_ORIGINAL_SEPARATE_DATE_TIMETABLE_REQUIRED');d=re.fullmatch(r'Ex-dividend date: ([A-Za-z]+ \d{1,2}, 20\d{2}) Record date: ([A-Za-z]+ \d{1,2}, 20\d{2}) Payment date: ([A-Za-z]+ \d{1,2}, 20\d{2})',dates)
    require(d is not None and str(pd.Timestamp(d.group(1)).date())==e['ex_date'] and str(pd.Timestamp(d.group(2)).date())==e['record_date']==facts.get('record_date') and str(pd.Timestamp(d.group(3)).date())==e['pay_date']==facts.get('pay_date') and Decimal(m.group(1))==Decimal(e['current_amount_literal'])==Decimal(str(facts.get('cash_per_raw_share'))) and pd.Timestamp(publication)==pd.Timestamp(e['source_publication_date']) and e['private_board_day'] is None,'BULK_FERG_DIRECT_CURRENT_AMOUNT_FIXED_PUBLIC_SCHEDULE_REQUIRED')
    require(re.findall(r'[$](\d+[.]\d+)',text)==e['original_money_tokens']==[e['current_amount_literal']] and e['amount_roles']==[dict(role='DIRECT_CURRENT_QUARTER_TIMETABLE_PER_SHARE',literal=m.group(1))],'BULK_FERG_ALL_CURRENT_MONEY_ROLES_REQUIRED')
    return dict(profile=FERG_CURRENT,selected_current_amount=m.group(1),amount_roles=e['amount_roles'],record_date=e['record_date'],pay_date=e['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_book_ref=FERG_BOOK_REF,source_role_consumer_ref=_ref(__file__),original_factory_ref=ORIGINAL_FACTORY_REF,current_source_explicit_common=False,current_currency_word_present=False,published_timetable_not_declared=True,private_board_day_inferred=False,separate_original_cash_and_schedule_not_fake_single_statement=True,current_amount_from_reported_concept=False,annual_rate_divided_or_inferred=False,original_frozen_class_literal=e['original_frozen_class_literal'])


def _support(payload,entry,facts,pinned):
    e=_scope(facts,pinned);require(payload.get('bulk_source_role_book_ref')==e['_source_book_ref'] and payload.get('sec_source_transport_profile') in (original.SEC_STATIC_SUBMISSION_PROFILE,original._base().SEC_STATIC_PRIMARY_BODY_PROFILE) and entry['prior_raw_close']['prior_date']==e['prior_date'] and facts.get('listing_identity')==e['listing_identity'] and facts.get('currency')=='USD' and facts.get('available_at') is None,'BULK_ORIGINAL_STATIC_UNIT_AND_PRIOR_REQUIRED')
    ferg=e['_source_book_ref']==FERG_BOOK_REF
    (_ferg_semantics if ferg else semantics)(payload['selected_original_cash_fragment']['text'],facts,e['source_publication_date'])
    cap=e['actual_main_capture'];current=e['current_source'];header=pinned(original._path_sha_ref(current['source_header_ref'])).read_bytes();full=pinned(original._path_sha_ref(cap['original_HTTP_ref']))
    bounded=e['_source_book_ref']==ANNOUNCED_BOOK_REF
    if bounded:
        custody=e['actual_bounded_member_custody'];require(cap['response_status']==200 and cap['actual_HTTP_status_observed'] and custody['actual_HTTP_status']==200 and custody['old_HTTP_status']=='UNKNOWN' and custody['original_header_exact_equal'] and custody['old_whole_primary_vs_actual_TEXT_bytes_equal']=='UNKNOWN_NOT_CLAIMED' and custody['body_whole_decoded'] is False,'BULK_TRUE_BOUNDED_CURRENT_TRANSPORT_ROLE_REQUIRED')
        with full.open('rb') as stream:prefix=stream.read(65536)
        require(prefix[:prefix.index(b'</SEC-HEADER>')+len(b'</SEC-HEADER>')]==header,'BULK_BOUNDED_ACTUAL_HEADER_ONLY_BYTES_REQUIRED')
        priorbody=pinned(original._path_sha_ref(custody['original_primary_ref']))
        for f in custody['bounded_physical_mappings']:
            if f['role'] not in ('CURRENT_ONLY_CASH','EntityRegistrantName_0','EntityIncorporationStateCountryCode_1','Security12bTitle_2','TradingSymbol_3','SecurityExchangeName_4'):continue
            a,b=f['actual_main_range'];x,y=f['old_primary_range'];require(b-a==y-x<=2048 and f['raw_exact_equal'] and f['all_actual_matches']==[[a,b]],'BULK_UNIQUE_CURRENT_NONVALUE_COVER_MAPPING_REQUIRED')
            with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)
            with priorbody.open('rb') as stream:stream.seek(x);prior=stream.read(y-x)
            require(raw==prior==pinned(original._path_sha_ref(f['physical_ref'])).read_bytes(),'BULK_CURRENT_COVER_ORIGINAL_PHYSICAL_EQUAL_REQUIRED')
    else:
        require(cap['response_status']==200 and cap['actual_HTTP_status_observed'] and cap['old_HTTP_status_remains_UNKNOWN'] and cap['old_full_byte_exact'] and cap['new_HEADER_prefix_equals_old_exactly'] and cap['new_SEC_HEADER_equals_old_exactly'],'BULK_REAL_TRANSPORT_AND_OLD_UNKNOWN_REQUIRED')
        with full.open('rb') as f:require(f.read(65536)==header,'BULK_HEADER_BODY_BYTE_EQUAL_REQUIRED')
    stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.to_datetime(stamp,format='%Y%m%d%H%M%S').tz_localize('America/New_York').tz_convert('UTC')
    require(current['accession'].encode() in header and re.search(rb'CENTRAL INDEX KEY:\s*0*'+str(e['issuer_CIK']).encode()+rb'\b',header) and accepted==pd.Timestamp(e['source_available_at'])==pd.Timestamp(cap['accepted_at_utc'] if bounded else cap['source_accepted_at_utc']),'BULK_ACTUAL_SOURCE_HEADER_CIK_ACCESSION_CLOCK_REQUIRED')
    selected=payload['selected_original_cash_fragment'];a,b=current['original_byte_range'];require(selected['original_byte_range']==[a,b] and b-a<=2048,'BULK_CURRENT_PHYSICAL_RANGE_REQUIRED')
    with full.open('rb') as f:f.seek(a);raw=f.read(b-a)
    require(raw==pinned(original._path_sha_ref(current['fragment_ref'])).read_bytes(),'BULK_ORIGINAL_CURRENT_BYTES_REQUIRED')
    unit=e['unit'];require(unit['issuer_cik']==e['issuer_CIK'] and unit['numeric_value_body_not_read'] and unit['current_amount_not_from_reported_concept'],'BULK_NONVALUE_COMMON_UNIT_ROLE_REQUIRED');require(unit['common_stock_XBRL_concept'] in ('us-gaap:CommonStockDividendsPerShareDeclared','us-gaap:CommonStockDividendsPerShareCashPaid'),'BULK_EXACT_COMMON_NONVALUE_CONCEPT_REQUIRED');original._original_common_cash_usd_unit(unit,lambda r:pinned(original._path_sha_ref(r)),issuer_cik=e['issuer_CIK'],concept=unit['common_stock_XBRL_concept'],class_literal='')
    require(re.fullmatch(rb'<ix:nonFraction\b[^>]*>',pinned(unit['capital_fragment_ref']).read_bytes()) and max(accepted,pd.Timestamp(unit['accepted_at_utc']))<pd.Timestamp(e['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16) and accepted<pd.Timestamp('2026-01-01',tz='UTC'),'BULK_SOURCE_UNIT_PREPRIOR_AND_TAG_VALUE_NOT_READ_REQUIRED')
    class_binding=None
    if ferg:
        require(e['original_frozen_class_literal']=='COMMON     STOCK  NEW' and e['original_CUSIP']=='31488V107' and facts.get('issuer_jurisdiction')=='US' and facts['listing_identity']=='NYSE:FERG','BULK_FERG_UNCHANGED_ORIGINAL_NEW_COMMON_CLASS_REQUIRED')
        for item,role in [(e['current_timetable_original_byte_range'],'DATES'),*[(f['original_byte_range'],f['role']) for f in current['cover_fragments']]]:
            x,y=item;require(0<=x<y<=full.stat().st_size and y-x<=2048,'BULK_FERG_CURRENT_DATE_COVER_PHYSICAL_BOUND_REQUIRED')
            with full.open('rb') as stream:stream.seek(x);body_bytes=stream.read(y-x)
            selected_ref=e['current_timetable_fragment_ref'] if role=='DATES' else next(f['fragment_ref'] for f in current['cover_fragments'] if f['role']==role);require(body_bytes==pinned(original._path_sha_ref(selected_ref)).read_bytes(),'BULK_FERG_CURRENT_NONVALUE_BODY_BYTES_REQUIRED')
        require({f['role']:f['text'] for f in current['cover_fragments']}==dict(REGISTRANT='FERGUSON ENTERPRISES INC.',CHARTER='Delaware',COMMON_TITLE='Common stock, par value $0.0001 per share',SYMBOL='FERG',EXCHANGE='New York Stock Exchange'),'BULK_FERG_SOURCE_US_CHARTER_REAL_COMMON_LISTING_REQUIRED')
        class_binding=dict(status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_CUSIP=e['original_CUSIP'],original_frozen_class_literal=e['original_frozen_class_literal'],source_common_class_literal='Common Stock',no_class_alias=True,original_frozen_class_rewritten=False)
    frozen=original._base()._existing_frozen_common_identity(payload,entry,facts,pinned=pinned,issuer=entry['identity_binding']['issuer'],**({'source_common_class_binding':class_binding} if ferg else {}));require(frozen is not None,'BULK_ORIGINAL_FROZEN_COM_REQUIRED');row=frozen['original_source_row'];dated=original._base()._static_submission_dated_raw_identity(payload,entry,facts,frozen,pinned=pinned)
    require(row['title_of_class']==(e['original_frozen_class_literal'] if ferg else 'COM') and row['cusip']==row['security_id']==e['original_CUSIP'] and dated['security_uid']=='CUSIP:'+e['original_CUSIP'] and dated['accounting_sid']==e['accounting_sid'] and dated['same_dated_UID_and_SID'] and dated['prior_date']==e['prior_date'] and dated['ex_date']==e['ex_date'],'BULK_ORIGINAL_COMMON_CUSIP_DATED_UID_REQUIRED')
    return original._VerifiedClass(profile=FERG_CURRENT,original_frozen_class_literal=e['original_frozen_class_literal'],original_CUSIP=e['original_CUSIP'],ticker='FERG',row_unchanged=True) if ferg else None


def _namespace(anchor,hooks):
    """Clone canonical functions with a closed list of explicit source callbacks."""
    old=anchor.__globals__;ns=dict(old);ns.update(hooks)
    require(ns['__file__']==old['__file__'],'BULK_PHYSICAL_PRODUCER_FILENAME_CANNOT_CHANGE')
    for name,value in tuple(ns.items()):
        if isinstance(value,FunctionType) and value.__globals__ is old:
            clone=FunctionType(value.__code__,ns,name,value.__defaults__,value.__closure__);clone.__kwdefaults__=value.__kwdefaults__;ns[name]=clone
    return SimpleNamespace(**ns)


def _source_whitelist(fn,expected_count):
    constants=list(fn.__code__.co_consts);hits=[]
    for index,value in enumerate(constants):
        if isinstance(value,tuple) and set(original.PROFILES)<=set(value):
            require(not any(profile in value for profile in NEW_PROFILES),'BULK_SOURCE_WHITELIST_ALREADY_CHANGED');constants[index]=(*value,*NEW_PROFILES);hits.append(index)
    require(len(hits)==expected_count,'BULK_EXACT_COMPILED_SOURCE_WHITELIST_ANCHORS_CHANGED')
    clone=FunctionType(fn.__code__.replace(co_consts=tuple(constants)),fn.__globals__,fn.__name__,fn.__defaults__,fn.__closure__);clone.__kwdefaults__=fn.__kwdefaults__
    return clone,hits



def _named_semantics(text,facts,publication,*,listed_common_class=None):
    e=_scope(facts);require(e['_source_book_ref']==NAMED_BOOK_REF and e['ticker']=='FCNCA' and e['issuer_CIK']==798941 and e['literal_family']=='DIRECT_CURRENT_QUARTER_CLASS_A_AND_B_COMMON' and listed_common_class=='A','BULK_EXACT_CURRENT_NAMED_COMMON_SCOPE_REQUIRED')
    date=r'([A-Za-z]+ \d{1,2}, 20\d{2})';m=re.fullmatch(r'(?:On '+date+r'|In January 2025), our Board declared a quarterly dividend on the Class A common stock and Class B common stock of [$](\d+[.]\d+) per common share[.] The dividends are payable on '+date+r' to stockholders of record as of '+date+r'[.]',text)
    require(m is not None and text==e['original_current_literal'] and re.findall(r'[$](\d+[.]\d+)',text)==e['original_money_tokens']==[e['current_amount_literal']] and Decimal(m.group(2))==Decimal(e['current_amount_literal'])==Decimal(str(facts['cash_per_raw_share'])) and str(pd.Timestamp(m.group(3)).date())==facts['pay_date']==e['pay_date'] and str(pd.Timestamp(m.group(4)).date())==facts['record_date']==e['record_date'] and pd.Timestamp(publication)==pd.Timestamp(e['source_publication_date']) and not re.search(r'\bpreferred|depositary|ADR|ADS|annualized|prior|paid\b',text,re.I),'BULK_REAL_NAMED_CLASS_AB_ONE_CURRENT_CASH_REQUIRED')
    require((m.group(1) is None)==e['month_only_board_date_unknown'] and e['private_board_day'] is None and (m.group(1) is None or pd.Timestamp(m.group(1))<=pd.Timestamp(publication)),'BULK_ORIGINAL_MONTH_ONLY_PRIVATE_BOARD_DAY_UNKNOWN')
    roles=[dict(role='DIRECT_CURRENT_QUARTER_EQUAL_CLASS_A_AND_B_COMMON',literal=m.group(2),source_common_classes=['A','B'],accounting_target_class='A')];require(roles==e['amount_roles'],'BULK_CURRENT_NAMED_CLASS_ROLES_REQUIRED')
    return dict(profile=NAMED_CURRENT,selected_current_amount=m.group(2),amount_roles=roles,record_date=e['record_date'],pay_date=e['pay_date'],source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),source_role_book_ref=NAMED_BOOK_REF,source_role_consumer_ref=_ref(__file__),original_factory_ref=ORIGINAL_FACTORY_REF,certified_source_cash_share_classes=['A','B'],certified_accounting_cash_share_classes=['A'],other_class_account_position_created=False,other_class_cash_or_quantity_inferred=False,original_text_not_rewritten=True,private_board_day_inferred=False,current_amount_from_reported_capital=False,annual_rate_divided_or_inferred=False)


def _named_support(payload,entry,facts,listing,pinned):
    e=_scope(facts,pinned);require(e['_source_book_ref']==NAMED_BOOK_REF and payload.get('bulk_source_role_book_ref')==NAMED_BOOK_REF and payload.get('sec_source_transport_profile')==original._base().SEC_STATIC_PRIMARY_BODY_PROFILE and entry['prior_raw_close']['prior_date']==e['prior_date'] and facts['listing_identity']==e['listing_identity']=='NASDAQ:FCNCA' and facts['currency']=='USD' and facts['available_at'] is None,'BULK_NAMED_ORIGINAL_PRIMARY_TRANSPORT_REQUIRED')
    require({x.upper() for x in re.findall(r'\bClass\s+([A-Z])\s+Common\s+Stock',listing,re.I)}=={'A'} and e['identity']['rows'][0]['original_source_row']['title_of_class']=='CL A','BULK_ONE_ORIGINAL_LISTED_AND_FROZEN_CLASS_A_REQUIRED');_named_semantics(payload['selected_original_cash_fragment']['text'],facts,e['source_publication_date'],listed_common_class='A')
    cur=e['current_source'];cust=e['actual_bounded_member_custody'];cap=json.loads(pinned(original._path_sha_ref(cust['actual_capture_ref'])).read_text());header=pinned(original._path_sha_ref(cust['actual_HEADER_ref'])).read_bytes();full=pinned(original._path_sha_ref(cust['actual_full_ref']));require(cap['response_status']==200 and cap['actual_HTTP_status_observed'] and cust['actual_HTTP_status']==200 and cust['old_HTTP_status']=='UNKNOWN' and cust['original_header_exact_equal'] and cust['old_whole_primary_vs_actual_TEXT_bytes_equal']=='UNKNOWN_NOT_CLAIMED' and cust['body_whole_decoded'] is False,'BULK_NAMED_ACTUAL_HEADER_AND_BOUNDED_CUSTODY_ONLY_REQUIRED')
    with full.open('rb') as stream:prefix=stream.read(65536)
    require(prefix[:prefix.index(b'</SEC-HEADER>')+len(b'</SEC-HEADER>')]==header and re.search(rb'CENTRAL INDEX KEY:\s*0*798941\b',header) and cur['accession'].encode() in header,'BULK_NAMED_TRUE_HEADER_ONLY_PHYSICAL_BYTES_REQUIRED')
    stamp=re.search(rb'<ACCEPTANCE-DATETIME>([0-9]{14})',header)[1].decode();accepted=pd.to_datetime(stamp,format='%Y%m%d%H%M%S').tz_localize('America/New_York').tz_convert('UTC');require(accepted==pd.Timestamp(e['source_available_at'])==pd.Timestamp(cust['accepted_at_utc']) and accepted<pd.Timestamp(e['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16),'BULK_NAMED_ACTUAL_SOURCE_PREPRIOR_REQUIRED')
    originalprimary=pinned(original._path_sha_ref(cust['original_primary_ref']))
    for f in cust['bounded_physical_mappings']:
        if f['role'] not in ('CURRENT_ONLY_CASH','EntityRegistrantName_0','EntityIncorporationStateCountryCode_1','Security12bTitle_2','TradingSymbol_3','SecurityExchangeName_4'):continue
        a,b=f['actual_main_range'];x,y=f['old_primary_range'];require(b-a==y-x<=2048 and f['raw_exact_equal'] and f['all_actual_matches']==[[a,b]],'BULK_NAMED_UNIQUE_BOUNDED_CURRENT_COVER_MAPPING_REQUIRED')
        with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)
        with originalprimary.open('rb') as stream:stream.seek(x);old=stream.read(y-x)
        require(raw==old==pinned(original._path_sha_ref(f['physical_ref'])).read_bytes(),'BULK_NAMED_PHYSICAL_CURRENT_COVER_BYTE_EQUAL_REQUIRED')
    u=e['unit'];require(u['issuer_cik']==798941 and u['numeric_value_body_not_read'] and u['current_amount_not_from_reported_concept'],'BULK_NAMED_NONVALUE_UNIT_ONLY_REQUIRED');original._original_common_cash_usd_unit(u,pinned,issuer_cik=798941,concept='us-gaap:CommonStockDividendsPerShareDeclared',class_literal='');require(re.fullmatch(rb'<ix:nonFraction\b[^>]*>',pinned(u['capital_fragment_ref']).read_bytes()) and pd.Timestamp(u['accepted_at_utc'])<pd.Timestamp(e['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16),'BULK_NAMED_NONVALUE_OPENING_AND_UNIT_PREPRIOR_REQUIRED')
    row=e['identity']['rows'][0]['original_source_row'];return original._VerifiedClass(profile=NAMED_CURRENT,original_frozen_class_literal='CL A',original_CUSIP=row['cusip'],ticker='FCNCA',row_unchanged=True,source_common_class_literal='Class A Common Stock',source_original_current_common_classes=['A','B'])


def _named_class_allowed(payload,entry,facts,row,binding):
    if payload['sec_cash_statement_profile']==FERG_CURRENT:
        e=_scope(facts);return isinstance(binding,original._VerifiedClass) and binding['profile']==FERG_CURRENT and row['title_of_class']==binding['original_frozen_class_literal']==e['original_frozen_class_literal']=='COMMON     STOCK  NEW' and row['cusip']==binding['original_CUSIP']==e['original_CUSIP']=='31488V107' and row['ticker']==binding['ticker']==e['ticker']=='FERG' and binding['row_unchanged'] is True
    if payload['sec_cash_statement_profile']!=NAMED_CURRENT:return original._class_allowed(payload,entry,facts,row,binding)
    e=_scope(facts);return isinstance(binding,original._VerifiedClass) and binding['profile']==NAMED_CURRENT and row['title_of_class']==binding['original_frozen_class_literal']=='CL A' and row['cusip']==binding['original_CUSIP']==e['original_CUSIP'] and row['ticker']==binding['ticker']==e['ticker']=='FCNCA' and binding['row_unchanged'] is True


def _named_subject_class(profile,payload,row,listing):
    if profile==FERG_CURRENT:
        e=_scope(payload['source_projection']);return e['_source_book_ref']==FERG_BOOK_REF and row['title_of_class']==e['original_frozen_class_literal']=='COMMON     STOCK  NEW' and row['cusip']==e['original_CUSIP']=='31488V107' and row['ticker']=='FERG' and re.search(r'\bCommon stock\b',listing,re.I) is not None and not re.search(r'\b(?:preferred|ADS|ADR|Class\s+[A-Z])\b',listing,re.I)
    if profile!=NAMED_CURRENT:return original._subject_class(profile,payload,row,listing)
    e=_scope(payload['source_projection']);return row['title_of_class']=='CL A' and row['cusip']==e['original_CUSIP'] and row['ticker']=='FCNCA' and set(re.findall(r'\bClass\s+([A-Z])\s+Common\s+Stock',listing,re.I))=={'A'}


class _VerifiedArchiveSupport(dict):pass


def _archive_event(payload,entry,pinned):
    if payload.get('ticker')=='GLW':
        facts=dict(ticker='GLW',sec_filer_cik=24741,security_id='FROZEN_RAW_TRANSPORT_CODE:US.GLW',exact_frozen_event_key=entry['original_unsupported_keys'][0]);e=_scope(facts,pinned)
        require(e['_source_book_ref']==GLW_BOOK_REF and [e['ticker'],e['ex_date']] in GLW_ARCHIVE_SCOPE['exact_events'] and e['issuer_CIK']==24741 and e['literal_family']=='ARCHIVED_ORIGINAL_CURRENT_QUARTER_PER_SHARE_DECLARATION','BULK_EXACT_GLW_CURRENT_ARCHIVE_REQUIRED');return e
    facts=dict(ticker=payload['ticker'],sec_filer_cik=701985,security_id='FROZEN_RAW_TRANSPORT_CODE:US.'+payload['ticker'],exact_frozen_event_key=entry['original_unsupported_keys'][0]);e=_scope(facts,pinned)
    require(e['_source_book_ref']==ARCHIVE_BOOK_REF and [e['ticker'],e['ex_date']] in ARCHIVE_SCOPE['exact_events'] and e['ticker']=='BBWI' and e['issuer_CIK']==701985 and e['literal_family']=='ARCHIVED_ORIGINAL_REGULAR_QUARTER_PER_SHARE_DECLARATION','BULK_EXACT_ARCHIVED_CURRENT_EVENT_REQUIRED')
    return e


def _archive_support(payload,entry,support,pinned):
    e=_archive_event(payload,entry,pinned);scope=GLW_ARCHIVE_SCOPE if e['_source_book_ref']==GLW_BOOK_REF else ARCHIVE_SCOPE;book_ref=e['_source_book_ref'];concept='us-gaap:CommonStockDividendsPerShareDeclared' if book_ref==GLW_BOOK_REF else 'us-gaap:CommonStockDividendsPerShareCashPaid';require(support.get('schema')==ARCHIVE_SUPPORT_SCHEMA and support.get('scope')==scope and support.get('book_ref')==book_ref and support.get('ex_date')==e['ex_date'] and support.get('source_role_consumer_ref')==_ref(__file__) and support.get('original_factory_ref')==ORIGINAL_FACTORY_REF,'BULK_PHYSICAL_ARCHIVE_CONSUMER_AND_ORIGINAL_FACTORY_REQUIRED')
    require(entry['prior_raw_close']['prior_date']==e['prior_date'] and entry['identity_binding']['ticker']==e['ticker'] and entry['identity_binding']['listing_identity']==e['listing_identity'] and e['current_source_explicit_common'] is False and e['current_source_explicit_USD'] is False,'BULK_ARCHIVE_ORIGINAL_CURRENT_MISSING_WORDS_RETAINED')
    u=e['unit'];require(u['common_stock_XBRL_concept']==concept and u['issuer_cik']==e['issuer_CIK'] and u['numeric_value_body_not_read'] and not u['current_event_payment_from_financial_paid_row'] and u['current_amount_not_from_reported_concept'],'BULK_ARCHIVE_CASHPAID_CLASS_UNIT_ONLY_REQUIRED')
    unit=original._original_common_cash_usd_unit(u,pinned,issuer_cik=e['issuer_CIK'],concept=u['common_stock_XBRL_concept'],class_literal='')
    require(re.fullmatch(rb'<ix:nonFraction\b[^>]*>',pinned(u['capital_fragment_ref']).read_bytes()),'BULK_ARCHIVE_NONVALUE_OPENING_TAG_ONLY_REQUIRED')
    body=pinned(u['source_document_ref']);shown={}
    from scripts.storage.refresh_sec_event_originals import FilingText
    for f in e['nonvalue_common_cover_fragments']:
        if f['role'] in ('common_declared_opening_tag','original_USD_per_share_unit'):continue
        a,b=f['physical_byte_range'];require(0<=a<b<=body.stat().st_size and b-a<=2048,'BULK_ARCHIVE_NONVALUE_COVER_RANGE_REQUIRED')
        with body.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)
        require(raw==pinned(original._path_sha_ref(f['fragment_ref'])).read_bytes(),'BULK_ARCHIVE_ORIGINAL_COVER_BYTES_REQUIRED');parser=FilingText();parser.feed(raw.decode());shown[f['role']]=' '.join(' '.join(parser.parts).split())
    expected=dict(EntityRegistrantName='CORNING INC /NY',EntityIncorporationStateCountryCode='New York',Security12bTitle='Common Stock, $0.50 par value per share',TradingSymbol='GLW',SecurityExchangeName='New York Stock Exchange') if book_ref==GLW_BOOK_REF else dict(EntityCentralIndexKey='0000701985',EntityRegistrantName='BATH & BODY WORKS, INC.',Security12bTitle='Common Stock, $0.50 Par Value',TradingSymbol='BBWI')
    require(shown==expected,'BULK_ARCHIVE_INDEPENDENT_COMMON_COVER_AND_CIK_REQUIRED')
    row=e['identity']['rows'][0]['original_source_row'];require(row['title_of_class']=='COM' and row['security_id']==row['cusip']==e['original_CUSIP'] and entry['identity_binding']['issuer']==row['issuer_name'],'BULK_ARCHIVE_ORIGINAL_FROZEN_COM_REQUIRED')
    latest=max(pd.Timestamp(e['source_available_no_later_than']),pd.Timestamp(u['accepted_at_utc']));require(latest<pd.Timestamp(e['prior_date'],tz='America/New_York')+pd.Timedelta(hours=16) and latest<pd.Timestamp('2026-01-01',tz='UTC') and e['actual_first_publication_at'] is None and e['engine_available_at'] is None,'BULK_ARCHIVE_PREPRIOR_CLOCK_AND_UNKNOWN_PUBLICATION_REQUIRED')
    return _VerifiedArchiveSupport(profile=ARCHIVE_ROLE,status='PINNED_EXACT_CUSIP_SUBJECT_COMMON_STOCK_SH_UNIT',source_common_class_literal='Common Stock',source_CUSIP=e['original_CUSIP'],original_frozen_class_literal='COM',no_class_alias=True,original_frozen_class_rewritten=False,source_legal_issuer_literal=row['issuer_name'],source_listing_identity=e['listing_identity'],source_US_context_literal='EXPLICIT_SEPARATE_SEC_USD_PER_COMMON_SHARE_UNIT',source_material_event=e,source_material_ref=book_ref,available_at=None,historical_availability_authority='UNKNOWN',share_quantity_effect=False,USD_unit_original_metadata=unit)


def _archive_terms(source,binding,projection,pub,capture,full_body):
    require(isinstance(binding,_VerifiedArchiveSupport) and full_body is not None and len(source['cash_fragments'])==1,'BULK_VERIFIED_ARCHIVE_ORIGINAL_BODY_REQUIRED');e=binding['source_material_event'];item=source['cash_fragments'][0];text=projection(item)
    m=re.fullmatch(r'COLUMBUS, Ohio, (Aug[.] 09|Nov[.] 08), 2024 [(]GLOBE NEWSWIRE[)] -- Bath & Body Works, Inc[.] [(]NYSE: BBWI[)] announced today the declaration of its regular quarterly dividend of [$](\d+[.]\d+) per share payable on ([A-Za-z]+ \d{1,2}, 20\d{2}), to shareholders of record at the close of business on ([A-Za-z]+ \d{1,2}, 20\d{2})[.]',text)
    if e.get('ticker')=='GLW':
        require(e.get('_source_book_ref')==GLW_BOOK_REF and e['literal_family']=='ARCHIVED_ORIGINAL_CURRENT_QUARTER_PER_SHARE_DECLARATION','BULK_GLW_REAL_CURRENT_QUARTER_SCOPE_REQUIRED')
        m=re.fullmatch(r'Corning (Incorporated) [’]s [(]NYSE: GLW[)] Board of Directors today declared a quarterly dividend of [$](\d+[.]\d+) per share[.] The dividend will be payable on ([A-Za-z]+ \d{1,2}, 20\d{2}), to shareholders of record on ([A-Za-z]+ \d{1,2}, 20\d{2})[.]',text)
    require(m is not None and text==e['original_current_literal'] and re.findall(r'[$](\d+[.]\d+)',text)==e['original_money_tokens']==[e['current_amount_literal']] and Decimal(m.group(2))==Decimal(e['current_amount_literal']) and str(pd.Timestamp(m.group(3)).date())==e['pay_date'] and str(pd.Timestamp(m.group(4)).date())==e['record_date'] and pub==pd.Timestamp(e['source_publication_date']) and capture==pd.Timestamp(e['source_available_no_later_than']),'BULK_ARCHIVE_REAL_CURRENT_LITERAL_AND_FIXED_DATES_REQUIRED')
    a=e['archive_capture'];require(a['http_status']==200 and a['source_CDX_route']['original']==source['source_url'] and a['actual_CDX_digest']==a['source_CDX_route']['digest'] and original._path_sha_ref(a['opaque_ref'])==original._path_sha_ref(source['original_http_bytes_ref']) and hashlib.sha256(full_body).hexdigest()==a['opaque_ref']['sha256'] and pd.Timestamp(a['source_available_upper_bound_utc'])==capture and source.get('actual_first_publication_at') is None and source.get('available_at') is None,'BULK_EXACT_ARCHIVE_MEMENTO_DIGEST_AND_UNKNOWN_FIRST_PUBLICATION_REQUIRED')
    return dict(issuer=binding['source_legal_issuer_literal'],ticker=e['ticker'],listing=e['listing_identity'],amount=float(Decimal(m.group(2))),record=e['record_date'],pay=e['pay_date'],publication=str(pub.date()),available=None,currency_basis='EXPLICIT_USD',source_currency_explicit_USD=False,source_currency_separate_SEC_USD_unit=True,body_ref=copy.deepcopy(item['fragment_ref']),header_ref=copy.deepcopy(source['dated_header_observations'][0]['fragment_ref']),source_paragraph=text,source_original_typed_text_digest=hashlib.sha256(json.dumps(text,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),source_original_typed_text_digest_recipe='UTF8_JSON_STRING_ENSURE_ASCII_FALSE_SORT_KEYS_COMPACT',source_declared_ex_date=None,source_US_context_literal=binding['source_US_context_literal'],original_source_unit_literal='per share',source_subject_role=ARCHIVE_ROLE,source_registrant_name_literal=binding['source_legal_issuer_literal'],source_issuer_field_role='ORIGINAL_FROZEN_ACCOUNTING_ISSUER_LITERAL_NOT_NAME_ALIAS_OR_NEW_LEGAL_IDENTITY',source_common_cover_class_literal='Common Stock',source_cash_classification_literal='quarterly',source_full_HTTP_sha256=source['received_http_bytes_sha256'],source_full_HTTP_bytes=source['received_bytes'],full_HTTP_body_locally_available=True,current_transport_capture_utc=str(capture.tz_convert('UTC')),capture_is_not_available_at=True,actual_first_publication_at=None,actual_first_publication_authority='UNKNOWN',source_publication_calendar_date_role='ORIGINAL_DISPLAYED_ARTICLE_DATE_NOT_FIRST_PUBLICATION_CERTIFICATE',source_archive_availability_role='EXACT_PREEX_ARCHIVE_CAPTURE_CONSERVATIVE_UPPER_BOUND_NOT_FIRST_PUBLICATION_CERTIFICATE',separate_common_cash_unit_available_utc=e['unit']['accepted_at_utc'],historical_availability_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',actual_SEC_HTTP_or_header_authority=False,source_fragment_physical_sha256=item['fragment_ref']['sha256'],source_text_utf8_sha256=item['visible_text_utf8_sha256'],current_source_explicit_common=False,current_amount_from_capital_statement=False,amount_roles=e['amount_roles'],annual_rate_division_or_inference=False)


def _archive_packet(bundle,bundle_ref,base):
    scope=GLW_ARCHIVE_SCOPE if bundle.get('bulk_exact_archived_current_scope')==GLW_ARCHIVE_SCOPE else ARCHIVE_SCOPE;book_ref=GLW_BOOK_REF if scope==GLW_ARCHIVE_SCOPE else ARCHIVE_BOOK_REF
    require(bundle.get('bulk_exact_archived_current_scope')==scope and bundle.get('post_native_dated_raw_cash_namespace_scope')==original._base().POST_NATIVE_DATED_RAW_CASH_SCOPE and bundle_ref is not None and base._read(bundle_ref)==bundle,'BULK_EXACT_ARCHIVE_NATIVE_PACKET_SCOPE_REQUIRED')
    bridge_ref=bundle['post_native_dated_raw_cash_namespace_bridge_ref'];require(bridge_ref in bundle['source_refs'],'BULK_ARCHIVE_PACKET_PIN_REQUIRED');packet=base._read(bridge_ref);proof_ref=packet['original_native_proof_ref'];require(proof_ref in bundle['source_refs'],'BULK_ARCHIVE_NATIVE_PROOF_PIN_REQUIRED');proof=base._read(proof_ref)
    require(packet['schema']=='SOURCE131_ARCHIVED_ORIGINAL_NAMESPACE_TO_EXACT_DATED_RAW_BRIDGE_PACKET' and packet['scope']==scope and packet['source_role_consumer_ref']==_ref(__file__) and packet['original_factory_ref']==ORIGINAL_FACTORY_REF and packet['current_native_admission'] is False and packet['strict_PIT'] is False and proof['schema']=='SOURCE131_ARCHIVED_ORIGINAL_SOURCE_NAMESPACE_NATIVE_PROOF' and proof['status']=='PASS_ORIGINAL_SOURCE_NAMESPACE_PENDING_RAW_PROJECTION' and proof['source_role_consumer_ref']==_ref(__file__) and proof['original_factory_ref']==ORIGINAL_FACTORY_REF and proof['source_material_ref']==book_ref and proof['strict_PIT'] is False and proof['fit_or_replay_run'] is False,'BULK_ARCHIVE_ORIGINAL_NATIVE_AND_PHYSICAL_CONSUMER_REQUIRED')
    prior=proof['original_native_bundle_ref'];require(prior in bundle['source_refs'] and packet['original_native_bundle_ref']==prior,'BULK_ARCHIVE_ORIGINAL_NATIVE_BUNDLE_CLOSURE_REQUIRED');base._pin(prior);bridges=packet['bridges'];require(len({(b['original_fact_ref']['path'],b['original_fact_ref']['sha256']) for b in bridges})==len(bridges)>0 and all(_archive_bridge_allowed(b) for b in bridges) and {(b['ticker'],b['ex_date']) for b in bridges}=={(p['ticker'],p['effective_date']) for p in proof['entries']},'BULK_ARCHIVE_EXACT_UNAMBIGUOUS_NATIVE_SET_REQUIRED')
    return bridge_ref,proof_ref,bridges,proof['entries']


def _archive_bridge_allowed(bridge):
    if bridge.get('schema')!='SOURCE131_ARCHIVED_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE':return original._msft_raw_bridge_allowed(bridge)
    scope=GLW_ARCHIVE_SCOPE if bridge.get('scope')==GLW_ARCHIVE_SCOPE else ARCHIVE_SCOPE
    return bridge.get('scope')==scope and [bridge.get('ticker'),bridge.get('ex_date')] in scope['exact_events'] and bridge.get('source_role_consumer_ref')==_ref(__file__) and bridge.get('original_factory_ref')==ORIGINAL_FACTORY_REF and bridge.get('accounting_sid')=='FROZEN_RAW_TRANSPORT_CODE:US.'+bridge.get('ticker','') and bridge.get('security_uid')=='CUSIP:'+bridge.get('original_CUSIP','')


def _archive_source_hooks(base,g):
    class Extend(ast.NodeTransformer):
        def __init__(self,name):self.name=name;self.count=0
        def visit_If(self,node):
            self.generic_visit(node)
            if self.name=='_original_dated_common_cash_terms' and ast.unparse(node.test)=='annual':
                # Only the post-header annual branch is the opt-in point.
                if getattr(node,'lineno',None)==2941:self.count+=1;return ast.parse('if isinstance(separate_common_binding,_VerifiedArchiveSupport): return _archive_terms(source,separate_common_binding,projection,pub,capture,full_body)').body+[node]
            if self.name=='_frozen_common_cash_namespace' and ast.unparse(node.test)=='support_ref is not None' and getattr(node,'lineno',None)==3549:
                self.count+=1;node.body=[node.body[0],ast.If(test=ast.parse("support.get('schema')==ARCHIVE_SUPPORT_SCHEMA",mode='eval').body,body=ast.parse('separate_common_binding=_archive_support(payload,entry,support,pinned)').body,orelse=node.body[1:])]
            if self.name=='bind_source_account_descendant' and getattr(node,'lineno',None)==3887:
                self.count+=1;node.body=[ast.If(test=ast.parse("'bulk_exact_archived_current_scope' in bundle",mode='eval').body,body=ast.parse('bridge_ref,old_proof_ref,post_native_bridges,post_native_proofs=_archive_packet(bundle,bundle_ref,_archive_base)').body,orelse=node.body)]
            return node
    g.update(_VerifiedArchiveSupport=_VerifiedArchiveSupport,_archive_terms=_archive_terms,_archive_support=_archive_support,ARCHIVE_SUPPORT_SCHEMA=ARCHIVE_SUPPORT_SCHEMA,_archive_packet=_archive_packet,_archive_base=base,_msft_raw_bridge_allowed=_archive_bridge_allowed)
    proof={}
    for name in ('_original_dated_common_cash_terms','_frozen_common_cash_namespace','bind_source_account_descendant'):
        source_tree=ast.parse(_pin(original.BASE_SOURCE_REF).read_text());node=copy.deepcopy(next(n for n in source_tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
        if name=='bind_source_account_descendant':node=original._Extend(name).visit(node)
        tx_old=original._MsftSourceExtend(name);node=tx_old.visit(node);require(tx_old.counts=={dict(_original_dated_common_cash_terms='article_after_existing_projection_header',_frozen_common_cash_namespace='separate_support_after_pinned_load',bind_source_account_descendant='post_native_setup_preserving_old_V38')[name]:1},'BULK_OLD_ARCHIVE_AST_PIPELINE_CHANGED')
        canonical=ast.dump(node,include_attributes=False);tx=Extend(name);node=tx.visit(node);require(tx.count==1,'BULK_ARCHIVE_EXACT_ORIGINAL_AST_OPTIN_CHANGED:'+name)
        class Strip(ast.NodeTransformer):
            def visit_If(self,item):
                self.generic_visit(item);test=ast.unparse(item.test)
                if test=='isinstance(separate_common_binding, _VerifiedArchiveSupport)':return []
                if test=="support.get('schema') == ARCHIVE_SUPPORT_SCHEMA":return item.orelse
                if test=="'bulk_exact_archived_current_scope' in bundle":return item.orelse
                return item
        stripped=Strip().visit(copy.deepcopy(node));require(ast.dump(stripped,include_attributes=False)==canonical,'BULK_ARCHIVE_OLD_AST_NOT_EXACT_AFTER_SOURCE_OPTIN_STRIP')
        ast.fix_missing_locations(node);exec(compile(ast.Module(body=[node],type_ignores=[]),getattr(base,name).__code__.co_filename,'exec'),g);proof[name]=tx.count;proof[name+'_old_AST_sha256']=hashlib.sha256(canonical.encode()).hexdigest()
    return proof


def _owner():
    require(_ref(original.__file__)==ORIGINAL_FACTORY_REF,'BULK_CANONICAL_B7C_FACTORY_CHANGED');base,anchors=original._owner()
    def statement(profile,text,facts,publication,*,listed_common_class=None):
        return _ferg_semantics(text,facts,publication,listed_common_class=listed_common_class) if profile==FERG_CURRENT else _named_semantics(text,facts,publication,listed_common_class=listed_common_class) if profile==NAMED_CURRENT else semantics(text,facts,publication,listed_common_class=listed_common_class) if profile in NEW_PROFILES else original.statement_semantics(profile,text,facts,publication,listed_common_class=listed_common_class)
    def class_binding(payload,entry,facts,listing,legal,pinned):
        return _named_support(payload,entry,facts,listing,pinned) if payload['sec_cash_statement_profile']==NAMED_CURRENT else _support(payload,entry,facts,pinned) if payload['sec_cash_statement_profile'] in NEW_PROFILES else original._class_binding(payload,entry,facts,listing,legal,pinned)
    # Original completion-clock code keeps the b7c producer identity; its explicit
    # new role callback proves the physical extension and book separately.
    clock_globals=dict(original._completion_clock.__globals__);clock_globals.update(PROFILES=(*original.PROFILES,*NEW_PROFILES),statement_semantics=statement)
    clock_tree=ast.parse(inspect.getsource(original._completion_clock));old_clock_AST=ast.dump(clock_tree,include_attributes=False);clock_node=clock_tree.body[0];matches=[n for n in ast.walk(clock_node) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='allowed' for t in n.targets)];require(len(matches)==1,'BULK_NAMED_EXACT_CLOCK_CLASS_ANCHOR_CHANGED');old_allowed=copy.deepcopy(matches[0].value);matches[0].value=ast.BoolOp(op=ast.Or(),values=[ast.parse("(profile==FERG_CURRENT and title=='COMMON     STOCK  NEW' and listed is None and row.get('cusip')==_scope(facts)['original_CUSIP']=='31488V107' and facts.get('ticker')=='FERG') or (profile==NAMED_CURRENT and title=='CL A' and listed=='A' and row.get('cusip')==_scope(facts)['original_CUSIP'] and facts.get('ticker')=='FCNCA')",mode='eval').body,matches[0].value]);require(ast.dump(matches[0].value.values[1],include_attributes=False)==ast.dump(old_allowed,include_attributes=False),'BULK_NAMED_OLD_CLOCK_PERMISSION_CHANGED');stripped_clock=copy.deepcopy(clock_tree);stripped_allowed=next(n for n in ast.walk(stripped_clock) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='allowed' for t in n.targets));stripped_allowed.value=stripped_allowed.value.values[1];require(ast.dump(stripped_clock,include_attributes=False)==old_clock_AST,'BULK_NAMED_STRIPPED_FULL_CLOCK_AST_CHANGED');clock_globals.update(NAMED_CURRENT=NAMED_CURRENT,FERG_CURRENT=FERG_CURRENT,_scope=_scope);ast.fix_missing_locations(clock_tree);exec(compile(clock_tree,original._completion_clock.__code__.co_filename,'exec'),clock_globals);clock=clock_globals['_completion_clock']
    def listed_class(binding,facts):
        if binding.get('sec_cash_statement_profile')==FERG_CURRENT:
            e=_scope(facts);return clock(binding,facts) and binding.get('original_frozen_class_literal')==e['original_frozen_class_literal']=='COMMON     STOCK  NEW' and binding.get('source_unique_listed_common_class') is None and binding.get('original_frozen_raw_CUSIP')==e['original_CUSIP']=='31488V107'
        if binding.get('sec_cash_statement_profile')!=NAMED_CURRENT:return original._completion_listed_class(binding,facts)
        e=_scope(facts);return clock(binding,facts) and binding.get('original_frozen_class_literal')=='CL A' and binding.get('source_unique_listed_common_class')=='A' and binding.get('original_frozen_raw_CUSIP')==e['original_CUSIP']
    cashowner=_namespace(base.cash.adjudicate_post_verified_cash_ex,dict(PROFILES=(*original.PROFILES,*NEW_PROFILES),_completion_clock=clock,_completion_listed_class=listed_class))
    owner=_namespace(base.bind_source_account_descendant,dict(PROFILES=(*original.PROFILES,*NEW_PROFILES),statement_semantics=statement,_class_binding=class_binding,_class_allowed=_named_class_allowed,_subject_class=_named_subject_class,_completion_clock=clock,cash=cashowner))
    sec,hits=_source_whitelist(owner._sec_primary_html_cash_terms,2)
    owner.bind_source_account_descendant.__globals__['_sec_primary_html_cash_terms']=sec;owner._sec_primary_html_cash_terms=sec
    cashfn,cashhits=_source_whitelist(cashowner.adjudicate_post_verified_cash_ex,1)
    cashfn.__globals__['adjudicate_post_verified_cash_ex']=cashfn;cashowner.adjudicate_post_verified_cash_ex=cashfn
    # _binding_fields/_statement are maintained pure source functions whose own
    # globals live in b7c; clone those two onto the same declared source hooks.
    g=owner.bind_source_account_descendant.__globals__
    for name in ('_binding_fields','_statement'):
        fn=getattr(original,name);cg=dict(fn.__globals__);cg.update(PROFILES=(*original.PROFILES,*NEW_PROFILES),statement_semantics=statement);clone=FunctionType(fn.__code__,cg,name,fn.__defaults__,fn.__closure__);clone.__kwdefaults__=fn.__kwdefaults__;g[name]=clone
    archive_anchors=_archive_source_hooks(base,g)
    for name in ('_original_dated_common_cash_terms','_frozen_common_cash_namespace','bind_source_account_descendant'):setattr(owner,name,g[name])
    return owner,dict(original_factory_ref=ORIGINAL_FACTORY_REF,source_role_consumer_ref=_ref(__file__),source_role_book_refs=[r for r,_ in BOOKS],original_AST_anchors=anchors,archive_SOURCE_AST_optins=archive_anchors,named_SOURCE_class_clock_optins=dict(class_allowed=1,subject_class=1,completion_clock=1),old_completion_clock_AST_sha256=hashlib.sha256(old_clock_AST.encode()).hexdigest(),closed_hooks=['PROFILES','statement_semantics','_class_binding','_completion_clock','cash','_binding_fields','_statement','_class_allowed','_subject_class','_completion_listed_class'],original_physical_filenames_preserved=True,original_cash_arithmetic_code_unchanged=True,compiled_source_whitelist_indices=dict(sec_primary=hits,cash_adjudicate=cashhits),compiled_source_whitelist_old_elements_and_order_preserved=True)


def _sec_frozen_cash_terms(payload,entry,*,source_ref_transport=()):
    owner,_=_owner();return owner._sec_frozen_cash_terms(payload,entry,source_ref_transport=source_ref_transport)


def adjudicate_post_verified_cash_ex(*args,**kwargs):
    owner,_=_owner();return owner.cash.adjudicate_post_verified_cash_ex(*args,**kwargs)



SOURCE_BINDER_ROLE='MASSIVE_VENDOR_USD_NATIVE_BINDER'
VENDOR_NATIVE_SCHEMA='SOURCE131_MASSIVE_V1_ORIGINAL_RAW_LISTED_USD_NATIVE_BUNDLE_R1'

def _vendor_metadata(ref,names):
    from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
    with _pin(ref).open('rb') as stream:return _JsonProjection(stream).metadata_fields(set(names))

def _vendor_identity(fact):
    import io
    from scripts.research.a2.data.consensus_account_inputs import _JsonProjection
    ref=fact['original_raw_identity_links_ref'];path=_pin(ref);head=_vendor_metadata(ref,{'status','mapping_ref','original_projection_ref','original_identity_links_owner_ref'})
    require(head['status']=='PASS_ORIGINAL_IDENTITY_LINKS105_NO_ALIAS_OR_NEW_QUOTE_AUTHORITY','VENDOR_ORIGINAL_RAW_IDENTITY_WITNESS_REQUIRED')
    for name in ('mapping_ref','original_projection_ref','original_identity_links_owner_ref'):_pin(head[name])
    chosen=[]
    with path.open('rb') as stream:
        q=_JsonProjection(stream);q.descend(('entries',));q.expect(b'[');q.white()
        while q.peek()!=b']':
            a=q.tell();meta=q.metadata_fields({'original5field_key'});z=q.tell()
            if meta.get('original5field_key')==fact['original5field_key']:
                require(z-a<=65536,'VENDOR_RAW_IDENTITY_ENTRY65KI');here=stream.tell();stream.seek(a);chosen.append(json.loads(stream.read(z-a)));stream.seek(here)
            q.white();sep=q.take()
            if sep==b']':break
            require(sep==b',','VENDOR_IDENTITY_ARRAY_CHANGED')
    require(len(chosen)==1,'VENDOR_UNIQUE_ORIGINAL_RAW_IDENTITY_REQUIRED');row=chosen[0]
    require(row['accounting_sid']==fact['accounting_sid'] and row['ticker']==fact['ticker'] and row['signal_date']==fact['ex_date'] and row['moomoo_transport_code']=='US.'+fact['ticker'] and row['raw_coordinate']=='RAW_ACTUAL_SHARE','VENDOR_RAW_SID_LISTED_UNIT_CHANGED')
    return row

def _vendor_original_components(fact):
    from scripts.storage import massive_dividend_sources as M
    require(_ref(M.__file__)['sha256']=='22018a77eb7bb4cfd06a71bd249189869735c8e6a076f47089f246c4ea3d5cde','VENDOR_CANONICAL_CAPTURE_PROJECTOR_PIN_REQUIRED')
    originals={}
    for component in fact['vendor_components']:
        checkpoint=_vendor_metadata(component['checkpoint_ref'],{'contract','attempts','pagination_complete','status'});contract=checkpoint['contract'];query=contract.get('query',contract)
        require(contract.get('endpoint')==M.ENDPOINT and query['ticker']==fact['ticker'],'VENDOR_ORIGINAL_ENDPOINT_SUBJECT_REQUIRED')
        successes=[x for x in checkpoint['attempts'] if x.get('http_status')==200]
        require(checkpoint.get('pagination_complete') is not False and successes and all(x.get('next_url_present') is False for x in successes),'VENDOR_ACTUAL_COMPLETE_PAGE_REQUIRED')
        start=query.get('ex_dividend_date.gte',query.get('ex_dividend_date'));end=query.get('ex_dividend_date.lte',query.get('ex_dividend_date'))
        require('2023-01-01'<=start<=fact['ex_date']<=end<'2026-01-01','VENDOR_CAPTURE_DATE_SCOPE_REQUIRED')
        require(any(x.get('raw_ref')==component['raw_ref'] and x.get('http_status')==200 for x in checkpoint['attempts']),'VENDOR_ACTUAL200_RAW_RECEIPT_REQUIRED')
        token=(component['raw_ref']['path'],component['raw_ref']['sha256'])
        if token not in originals:
            body=_pin(component['raw_ref']).read_bytes();selected=M.project_dividends(body,ticker=fact['ticker'],start_date=start,end_date=end,target_dates=[fact['ex_date']]);originals[token]=selected['records']
    records=[row for rows in originals.values() for row in rows];require(len({x['id'] for x in records})==len(records),'VENDOR_ORIGINAL_COMPONENT_ID_DUPLICATE')
    require(sorted(records,key=lambda x:x['id'])==sorted([x['record'] for x in fact['vendor_components']],key=lambda x:x['id']),'VENDOR_FACT_MUST_EQUAL_COMPLETE_ORIGINAL_RAW_COMPONENTS')
    return records

def _vendor_fact_event(ca,fact,projection_ref):
    _vendor_original_components(fact)
    from decimal import Decimal
    require(fact.get('schema')=='SOURCE131_ORIGINAL_MASSIVE_VENDOR_CASH_NATIVE_FACT_R1' and fact.get('source_type')=='TIER3_VENDOR_METADATA' and fact.get('available_at') is None and fact.get('ordinary_cash_confirmed') is False and fact.get('clock_role')=='POST_VERIFIED_ACCOUNTING_ONLY','VENDOR_EXPLICIT_POSTVERIFIED_SOURCE_ROLE_REQUIRED')
    require(fact['original5field_key']['ticker']==fact['ticker'] and fact['original5field_key']['effective_date']==fact['ex_date'] and '2023-01-01'<=fact['ex_date']<'2026-01-01' and fact['pay_date']<'2026-01-01','VENDOR_PRE26_PAYMENTS_ONLY_PENDING_FUTURE_DECLARED_CAPSULE')
    _vendor_identity(fact);components=fact['vendor_components'];require(components and len({x['record']['id'] for x in components})==len(components),'VENDOR_DISTINCT_COMPLETE_COMPONENT_IDS_REQUIRED');amounts=[]
    for component in components:
        record=component['record'];require(component['pagination_complete'] is True,'VENDOR_COMPLETE_COMPONENT_PAGE_REQUIRED');_pin(component['raw_ref']);_pin(component['checkpoint_ref'])
        require(record['ticker']==fact['ticker'] and record['ex_dividend_date']==fact['ex_date'] and record['currency']=='USD' and record['record_date']==fact['record_date'] and record['pay_date']==fact['pay_date'] and record['declaration_date']==fact['declaration_date'] and record['declaration_date']<fact['ex_date'] and not any(k in record for k in ('split_adjusted_cash_amount','historical_adjustment_factor')),'VENDOR_COMPONENT_UNIT_DATES_AND_PREDECL_CHANGED')
        amount=Decimal(component['original_cash_amount_decimal']);require(amount.is_finite() and amount>0 and amount==Decimal(str(record['cash_amount'])),'VENDOR_ORIGINAL_POSITIVE_CASH_AMOUNT_REQUIRED');amounts.append(amount)
    total=sum(amounts,Decimal(0));require(total==Decimal(fact['derived_cash_amount_decimal']),'VENDOR_DERIVED_COMPONENT_SUM_CHANGED')
    require(fact['source_kind']==('COMPOSITE_CASH' if len(components)>1 else 'VENDOR_ORIGINAL_CASH_COMPONENT') and fact['amount_aggregation_role']==('DERIVED_ORIGINAL_COMPONENT_SUM_CREDIT_ONCE' if len(components)>1 else 'SINGLE_ORIGINAL_VENDOR_COMPONENT'),'VENDOR_COMPONENT_SOURCE_KIND_NOT_RECLASSIFIED')
    group=dict(original5field_key=fact['original5field_key'],accounting_sid=fact['accounting_sid'],listed_unit='RAW_ACTUAL_SHARE',currency='USD',dates=dict(ex_dividend_date=fact['ex_date'],record_date=fact['record_date'],pay_date=fact['pay_date'],declaration_date=fact['declaration_date'],currency='USD'),components=sorted([dict(id=c['record']['id'],type=c['record']['distribution_type'],original_amount=c['original_cash_amount_decimal'],rawSHA=c['raw_ref']['sha256']) for c in components],key=lambda x:x['id']),clock_role='POST_VERIFIED_ACCOUNTING_ONLY')
    require(fact.get('canonical_group_definition')==group and fact['group_id']==hashlib.sha256(json.dumps(group,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'VENDOR_CANONICAL_COMPONENT_GROUP_CHANGED')
    return ca.ResearchReconstructedCashEvent(event_id=('SOURCE_COMPONENT_GROUP:' if len(components)>1 else 'SOURCE_VENDOR_CASH:')+fact['group_id'],action_type='CASH_DIVIDEND',old_security_id=fact['accounting_sid'],ticker=fact['ticker'],ex_date=fact['ex_date'],record_date=fact['record_date'],pay_date=fact['pay_date'],available_at=None,cash_per_old_share=float(total),currency='USD',amount_unit=ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,source_type='TIER3_VENDOR_METADATA',source_reference=fact['vendor_endpoint'],source_fingerprint=projection_ref['sha256'],reconstruction_ref=projection_ref['path'],reconstruction_sha256=projection_ref['sha256'],clock_role='POST_VERIFIED_ACCOUNTING_ONLY',source_scope='B_FROZEN_PRE2026_ACCOUNTING_ONLY')

def _bind_vendor_source_descendant(env,original_kwargs,bundle,*,account_dates,bundle_ref):
    import copy,hashlib
    from scripts.research.a2.data import consensus_account_inputs as I
    ca=I.existing.ca;require(_ref(ca.__file__)['sha256']=='142c36633e47633fff5c9c63be030536fa7b1dba8a67f8432643c084f4dcdce4','VENDOR_ORIGINAL_CASH_MATH_OWNER_PIN_REQUIRED')
    require(bundle_ref is not None and _vendor_metadata(bundle_ref,{'schema','completion_binder_owner_ref','event_projection_refs','source_refs'})=={k:bundle[k] for k in ('schema','completion_binder_owner_ref','event_projection_refs','source_refs')} and bundle['schema']==VENDOR_NATIVE_SCHEMA and bundle['completion_binder_owner_ref']==_ref(__file__),'VENDOR_ACTUAL_NATIVE_OWNER_PACKET_REQUIRED')
    for ref in bundle['source_refs']:_pin(ref)
    events=[];keys=[];proofs=[];mapping=dict(original_kwargs['entitlement_security_tickers']);component_ids=set()
    for ref in bundle['event_projection_refs']:
        path=_pin(ref);require(path.stat().st_size<=65536,'VENDOR_NATIVE_FACT65KI');fact=json.loads(path.read_text(encoding='utf-8'));event=_vendor_fact_event(ca,fact,ref)
        require(fact['accounting_sid'] not in mapping or mapping[fact['accounting_sid']]==fact['ticker'],'VENDOR_ORIGINAL_RAW_MAPPING_CONFLICT');mapping[fact['accounting_sid']]=fact['ticker']
        for component in fact['vendor_components']:
            token=(fact['ticker'],component['record']['id']);require(token not in component_ids,'VENDOR_COMPONENT_GLOBAL_CONSUME_ONCE');component_ids.add(token)
        events.append(event);keys.append(fact['original5field_key']);proofs.append(dict(original_record=fact['original5field_key'],component_fingerprints=[event.event_fingerprint]))
    require(len({I.existing.source._key(x) for x in keys})==len(keys)==len(events) and len({x.event_fingerprint for x in events})==len(events),'VENDOR_ONE_SOURCE_GROUP_ONE_NATIVE_EVENT_REQUIRED')
    original_keys={I.existing.source._key(x) for x in original_kwargs['unsupported_events']};require({I.existing.source._key(x) for x in keys}<=original_keys,'VENDOR_EXACT_ORIGINAL_UNSUPPORTED_KEYS_REQUIRED')
    admission=dict(schema='B_FROZEN_HISTORY_POST_VERIFIED_CASH_ADMISSION_V1',scientific_identity='FROZEN_HISTORY_RESEARCH_ACCOUNT',task_id='V24_B_FAST_TRACK_PAIR_COMPLETION_R1',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',accounting_clock_convention='ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION',scope_start='2023-01-01',scope_end_exclusive='2026-01-01',strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,source_contract_ref=bundle_ref,source_binding_fingerprint=I.existing.digest(dict(bundle=bundle_ref,proofs=proofs)),events=[dict(event_fingerprint=e.event_fingerprint,source_projection_ref=dict(path=e.reconstruction_ref,sha256=e.reconstruction_sha256),publication_available_at=None,historical_availability_qualified=False,clock_role='POST_VERIFIED_ACCOUNTING_ONLY') for e in events])
    ca._validate_frozen_history_cash_admission(tuple(events),admission)
    result=dict(original_kwargs);result.update(entitlement_enabled=True,entitlement_events=tuple(events),entitlement_security_tickers=mapping,research_account_authority=dict(frozen_history_cash_admission=admission),entitlement_source_binding=dict(source_fingerprint=I.existing.digest(dict(bundle=bundle_ref,proofs=proofs)),manifest=dict(removed_exact_original_keys=keys,key_to_component_fingerprints=proofs,vendor_source_profile=SOURCE_BINDER_ROLE,original_component_ids_retained=True,source_conflicts_resolved_by_choice=False),security_tickers=mapping,event_fingerprints=[e.event_fingerprint for e in events]))
    return dict(events=result,receipt=dict(status='PASS_SOURCE_ONLY_MASSIVE_ORIGINAL_RAW_LISTED_VENDOR_NATIVE',qualified_count=len(events),vendor_source_profile=SOURCE_BINDER_ROLE,available_at=None,strict_PIT=False,native_component_count=len(component_ids),source_conflicts_resolved_by_choice=False),ordinary_cash_event_fingerprints=[])


def bind_source_account_descendant(env,original_kwargs,bundle,*,account_dates,bundle_ref=None):
    if bundle.get("schema")==VENDOR_NATIVE_SCHEMA:return _bind_vendor_source_descendant(env,original_kwargs,bundle,account_dates=account_dates,bundle_ref=bundle_ref)
    owner,proof=_owner();require(bundle.get('source_profile_completion_scope')==original.SCOPE and bundle_ref is not None and owner._read(bundle_ref)==bundle,'BULK_EXACT_PINNED_ORIGINAL_SCOPE_REQUIRED')
    for r in (ORIGINAL_FACTORY_REF,original.BASE_SOURCE_REF,*[r for r,_ in BOOKS],_ref(__file__)):
        require(r in bundle['source_refs'],'BULK_CANONICAL_AND_EXTENSION_CLOSURE_REQUIRED');owner._pin(r)
    result=owner.bind_source_account_descendant(env,original_kwargs,bundle,account_dates=account_dates,bundle_ref=bundle_ref);result['receipt']['source_role_extension']=proof;return result
