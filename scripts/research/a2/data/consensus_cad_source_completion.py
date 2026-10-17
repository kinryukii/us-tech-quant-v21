"""Exact CAD source/consumer connector. Import performs no data reads or runs.



The USD source owners are unchanged. CAD facts use the existing R6 foreign-cash

constructor, original H10 conversion and R6 small-cash AST. Source proof, prior

quote projection and account authority are separate admissions.

"""

from __future__ import annotations

import ast

import copy

from dataclasses import asdict, dataclass

import hashlib

import json

import math

from pathlib import Path

import re

from types import FunctionType, SimpleNamespace

import pandas as pd

from scripts.v22 import corporate_action_transition_r1 as ca

from scripts.research.a2.data import joint_cash_bindings as cash



TASK = 'CONSENSUS100_PTO_3000_20261012_R1'

ENGINEERING = 'ENGINEERING_ONLY_NO_SOURCE_NATIVE_OR_ACCOUNT_READ_AUTHORITY'

CUT = pd.Timestamp('2026-01-01', tz='UTC')

ROOT = Path('D:/us-tech-quant')

RUN = Path('D:/us-tech-quant-backtests/CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2/20261012T025603+0000_4a58260e')

CACHE = Path('D:/us-tech-quant-cache/_maintenance') / TASK / 'source_repair'

MATERIAL_REF = dict(path=str(CACHE/'canada_three_fixed_current_currency_source_material_r23_r1/THREE_FIXED_CANADIAN_CURRENT_CAD_SOURCE_MATERIAL_R1.json'), sha256='5465e780590310ca78a990e2b0eeacd9a19a3acc2eadbbbe8cfedb2332129971')

EARLY_FX_REF = dict(path=str(RUN/'derived/source_completion/EARLY_CAD_H10_THREE_DATED_RELEASE_SOURCE_FACTS_R23_R1.json'), sha256='4dce16189e4bbdb30a6b7a23114dc963ae1efedd5e88c90e86b2af081b957c24')

OLD_FX_REF = dict(path=str(RUN/'derived/source_completion/FED_H10_CAD_SOURCE_FACTS_R1.json'), sha256='16f3c871b9a423c65b4b26855247f8551c15eef622f1c5a770460333fd379a98')

EARLY_FX_QUAL_REF = dict(path=str(Path('D:/us-tech-quant-results/_maintenance')/TASK/'source_repair/CAD_THREE_EARLY_H10_ORIGINAL_PARSER_QUALIFICATION_R23_R2.json'), sha256='e8c60df0720549e0e22fdd75bc3b13e9dd918dfed6b7ea893b2b1f96625e7e2e')

R6_CHECK_REF = dict(path=str(CACHE/'assemble_special_account_sources_r1.py'), sha256='8341204e5bf26ede5ee951ebeff21777932111d56e1252b77911b181e754871f')

PINS = {'ca': (ROOT/'scripts/v22/corporate_action_transition_r1.py', '142c36633e47633fff5c9c63be030536fa7b1dba8a67f8432643c084f4dcdce4'), 'cash': (ROOT/'scripts/research/a2/data/joint_cash_bindings.py', '3aafa77d7637e08032041d884bbd8ad03f6c7fe5e5d08996c51c3a87fa7b7398'), 'fx': (ROOT/'scripts/research/a2/data/consensus_h10_fx_sources.py', 'e053b0c934183408bc13e211251f0208748f9a55ee156cd5cd98d00a9196b99e'), 'inputs': (ROOT/'scripts/research/a2/data/consensus_account_inputs.py', 'dbd16fe143886d9ecb2d2507b2583e05caf0933e1962ab8c43db9b4ed713e31a'), 'shareholder': (ROOT/'scripts/research/a2/evaluation/consensus_shareholder_account.py', '6e12fe1991aa71c8ab958dc48fc33442853ec00d3418e2127869457caa3dc578'), 'routing': (ROOT/'scripts/research/a2/evaluation/consensus_account_source_continuation.py', '87ee6432888e9ba423d7c07cd847fb6959e32700dfa2db9eaa826833a5f1f18b')}

CASES = {

 ('CCJ','2023-11-29'): dict(cik=1009001, accession='0001193125-23-266724', prior='2023-11-28', record='2023-11-30', pay='2023-12-15', amount='0.12', cusip='13321L108', title='Common Stock', sid='FROZEN_RAW_TRANSPORT_CODE:US.CCJ', accepted='2023-10-31T11:38:57+00:00', frequency='annual', currency_literal='currency: Cdn (unless noted)'),

 ('SU','2024-06-04'): dict(cik=311337, accession='0001104659-24-058478', prior='2024-06-03', record='2024-06-04', pay='2024-06-25', amount='0.545', cusip='867224107', title='COM', sid='FROZEN_RAW_TRANSPORT_CODE:US.SU', accepted='2024-05-08T13:30:44+00:00', frequency='quarterly', currency_literal='All financial figures are in Canadian dollars.'),

 ('SU','2024-09-04'): dict(cik=311337, accession='0001104659-24-086595', prior='2024-09-03', record='2024-09-04', pay='2024-09-25', amount='0.545', cusip='867224107', title='COM', sid='FROZEN_RAW_TRANSPORT_CODE:US.SU', accepted='2024-08-07T13:42:50+00:00', frequency='quarterly', currency_literal='All financial figures are in Canadian dollars.')}
ORIGINAL_THREE_KEYS = tuple(CASES)
CCJ2024_MATERIAL_REF = {'path': 'D:\\us-tech-quant-cache\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\ccj_2024_one_current_CAD_source_material_r26_r1\\CCJ2024_ONE_CURRENT_COMMON_CAD_SOURCE_MATERIAL_R26_R3.json', 'sha256': 'e0bb28b04449e3cedc1687260d96db1bf51a3e37a4de5c973b72cd5503570af1'}
CCJ2024_ORIGINAL_BLOCKERS_REF = {'path': 'D:\\us-tech-quant-results\\_maintenance\\CONSENSUS100_PTO_3000_20261012_R1\\source_repair\\CCJ2024_ORIGINAL_FIVEFIELD_SOURCE_METADATA_AUTHORITY_R26_R1.json', 'sha256': 'fa6a23e50514e47ce60ce1524eca2f60e06d74ac0cf498561591ba3291e79119'}
CASES[('CCJ','2024-11-27')] = {'cik': 1009001, 'accession': '0001193125-24-252580', 'prior': '2024-11-26', 'record': '2024-11-27', 'pay': '2024-12-13', 'amount': '0.16', 'cusip': '13321L108', 'title': 'Common Stock', 'sid': 'FROZEN_RAW_TRANSPORT_CODE:US.CCJ', 'accepted': '2024-11-07T11:46:28+00:00', 'frequency': 'annual', 'currency_literal': 'currency: Cdn (unless noted)'}




def require(ok, reason):

    if not ok: raise ValueError(reason)



def digest(value):

    return hashlib.sha256(ca.canonical_bytes(value)).hexdigest()



def file_ref(path):

    path=Path(path)

    with path.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()

    return dict(path=str(path),sha256=sha)



def pin(ref):

    require(set(ref)>= {'path','sha256'} and file_ref(ref['path'])['sha256']==ref['sha256'],'CAD_SOURCE_PIN_CHANGED')

    return Path(ref['path'])



def protected_pins():

    for path,sha in PINS.values(): pin(dict(path=str(path),sha256=sha))

    return {k:dict(path=str(p),sha256=s) for k,(p,s) in PINS.items()}



def _material_event(key):
    if key==('CCJ','2024-11-27'):
        m=json.loads(pin(CCJ2024_MATERIAL_REF).read_text(encoding='utf-8'));require(m['key']==list(key) and m['old_full_member_entire_exact_primary'] is True and m['current_USD_override'] is False and m['original_global_currency_definition_before_current'] is True,'CAD_CCJ2024_EXACT_ORIGINAL_MATERIAL_REQUIRED')
        pieces={p['role']:p for p in m['physical_fragments']};cash_piece=pieces['cash'];currency=pieces['currency'];scope=pieces['nonnumeric_parent_currency_scope_opaque']
        return dict(original_primary_ref=m['old_primary_ref'],actual_HEADER_ref=m['actual_HEADER_ref'],original_current_fragment=dict(ref=cash_piece['ref'],original_byte_range=cash_piece['original_primary_byte_range'],original_complete_native_spacejoin_literal=pin(m['current_native_spacejoin_literal_ref']).read_text(encoding='utf-8')),original_announcement_currency_definition=dict(ref=currency['ref'],original_byte_range=currency['original_primary_byte_range'],document_level_before_current=True,financial_table_or_caption=False,USD_or_other_currency_override_inside_current=False,original_announcement_masthead_layout_proof=dict(cash_paragraph_outside_after_header_table=scope['original_primary_byte_range'][1]<cash_piece['original_primary_byte_range'][0],opaque_ref=scope['ref'])),original_frozen_identity_metadata=m['frozen_identity'])
    value=json.loads(pin(MATERIAL_REF).read_text(encoding='utf-8'))
    matches=[e for e in value['events'] if (e['ticker'],e['effective_date'])==key]
    require(len(matches)==1,'CAD_EXACT_ONE_ORIGINAL_MATERIAL_REQUIRED')
    return matches[0]



def _visible(raw):

    from scripts.storage.refresh_sec_event_originals import FilingText

    parser=FilingText();parser.feed(raw.decode('utf-8'))

    return ' '.join(' '.join(parser.parts).split())



def _piece(full, binding, original):

    require(binding['old_fragment_ref']==original['ref'] and binding['old_primary_byte_range']==original['original_byte_range'],'CAD_ORIGINAL_PHYSICAL_SCOPE_CHANGED')

    a,b=binding['new_full_submission_byte_range'];require(0<=a<b<=full.stat().st_size and b-a<=2048,'CAD_BOUNDED_PHYSICAL_RANGE_REQUIRED')

    with full.open('rb') as stream:stream.seek(a);raw=stream.read(b-a)

    require(raw==pin(original['ref']).read_bytes() and len(raw)==b-a,'CAD_ORIGINAL_FULL_FRAGMENT_MISMATCH')

    return raw



@dataclass(frozen=True)

class SourceQualification:

    key: tuple[str,str]

    event: ca.SourceBackedForeignCashEvent

    receipt: dict

    receipt_sha256: str



@dataclass(frozen=True)

class NativeQualification:

    source: SourceQualification

    proof: dict

    proof_sha256: str





def qualify_source(packet, *, calendar):

    """Physical current-source/clock/identity gate; no RAW or FX scalar input."""

    key=packet['ticker'],packet['ex_date'];require(key in CASES,'CAD_EXACT_FOUR_SOURCE_KEYS_ONLY');case=CASES[key];old=_material_event(key)

    require(packet['declared_currency']=='CAD' and packet['amount_unit']==ca.CAD_PER_RAW_OLD_SHARE and packet['quantity_coordinate']==ca.RAW_OLD_SHARE_COORDINATE,'CAD_DECLARED_CURRENCY_RAW_UNIT_REQUIRED')

    require(packet['old_primary_ref']==old['original_primary_ref'] and packet['old_HEADER_ref']==old['actual_HEADER_ref'],'CAD_ORIGINAL_DOCUMENT_HEADER_IDENTITY_REQUIRED')

    pin(packet['old_primary_ref']);header=pin(packet['old_HEADER_ref']).read_bytes();head=header.split(b'<DOCUMENT>',1)[0]

    stamp=re.search(rb'<ACCEPTANCE-DATETIME>(\d{14})',head);require(stamp is not None,'CAD_ACTUAL_SEC_ACCEPTANCE_REQUIRED')

    accepted=pd.Timestamp(stamp[1].decode()).tz_localize('America/New_York').tz_convert('UTC')

    require(case['accession'].encode() in head and re.search(rb'CENTRAL INDEX KEY:\s*0*'+str(case['cik']).encode()+rb'\b',head) and accepted==pd.Timestamp(case['accepted']) and accepted<cash._clock(pd.Timestamp(key[1]),9,30) and accepted<CUT,'CAD_ACTUAL_PREEX_ISSUER_HEADER_REQUIRED')

    capture=json.loads(pin(packet['capture_ref']).read_text(encoding='utf-8'));full=pin(packet['new_full_ref']);url=f"https://www.sec.gov/Archives/edgar/data/{case['cik']}/{case['accession']}.txt"

    require(capture['response_status']==200 and capture['actual_HTTP_status_observed'] is True and capture['response_url']==url and capture['original_HTTP_ref']['sha256']==packet['new_full_ref']['sha256'] and capture['old_HTTP_status_remains_UNKNOWN'] is True,'CAD_NEW_OBSERVED_HTTP200_ONLY_REQUIRED')

    with full.open('rb') as stream:require(stream.read(len(header))==header,'CAD_ORIGINAL_HEADER_PREFIX_MISMATCH')

    if packet.get('old_full_ref') is not None:require(pin(packet['old_full_ref']).stat().st_size==full.stat().st_size and packet['old_full_ref']['sha256']==packet['new_full_ref']['sha256'],'CAD_OLD_FULL_VERSION_CHANGED')

    pieces={}

    for role,name in [('cash','original_current_fragment'),('currency','original_announcement_currency_definition')]:

        matches=[z for z in packet['physical_bindings'] if z['role']==role];require(len(matches)==1,'CAD_ONE_CURRENT_AND_CURRENCY_SCOPE_REQUIRED');pieces[role]=_piece(full,matches[0],old[name])

    literal=_visible(pieces['cash']);currency=_visible(pieces['currency']);currency_source=old['original_announcement_currency_definition']

    require(literal==old['original_current_fragment']['original_complete_native_spacejoin_literal'] and currency==case['currency_literal'] and currency_source['document_level_before_current'] is True and currency_source['financial_table_or_caption'] is False and currency_source['USD_or_other_currency_override_inside_current'] is False,'CAD_CURRENT_WORDS_AND_DOCUMENT_CURRENCY_REQUIRED')

    spans={z['role']:z['new_full_submission_byte_range'] for z in packet['physical_bindings']};require(spans['currency'][1]<=spans['cash'][0],'CAD_DOCUMENT_CURRENCY_NOT_CURRENT_SCOPE_REQUIRED')

    if key[0]=='CCJ':

        current=re.search(r'declared a 2024 annual dividend of \$(\d+(?:\.\d+)?) per common share, payable on December 13, 2024, to shareholders of record on November 27, 2024' if key==('CCJ','2024-11-27') else r'declared a 2023 annual dividend of \$(\d+(?:\.\d+)?) per common share, payable on December 15, 2023, to shareholders of record on November 30, 2023',literal)

        require(currency_source['original_announcement_masthead_layout_proof']['cash_paragraph_outside_after_header_table'] is True,'CAD_CCJ_MASTHEAD_NOT_FINANCIAL_TABLE_REQUIRED')

    else:

        current=re.search(r'approved a quarterly dividend of \$(\d+(?:\.\d+)?) per share on its common shares, payable',literal)

    require(current is not None and current[1]==case['amount'] and packet['record_date']==case['record'] and packet['pay_date']==case['pay'],'CAD_CURRENT_ORIGINAL_COMMON_CASH_SCHEDULE_REQUIRED')

    identity=packet['identity'];require(identity==old['original_frozen_identity_metadata'],'CAD_ORIGINAL_FROZEN_IDENTITY_PAYLOAD_CHANGED');row=identity['original_source_row'];links=identity['identity_links']

    require(row['ticker']==key[0] and row['cusip']==row['security_id']==case['cusip'] and row['security_id_type']=='CUSIP' and row['title_of_class']==case['title'] and identity['raw_security_id']==case['sid'] and {str(pd.Timestamp(x['signal_date']).date()) for x in links}=={case['prior'],key[1]} and all(x['security_uid']=='CUSIP:'+case['cusip'] and x['accounting_sid']==case['sid'] and x['ticker']==key[0] for x in links),'CAD_EXACT_DATED_COMMON_UID_AND_SID_REQUIRED')

    ex,rule=cash.normal_cash_ex_date(case['record'],calendar,scope_end_exclusive='2026-01-01');require(str(ex.date())==key[1] and str(pd.Timestamp(calendar[pd.DatetimeIndex(calendar).get_loc(ex)-1]).date())==case['prior'],'CAD_ORIGINAL_CALENDAR_COORDINATE_REQUIRED')

    event=ca.SourceBackedForeignCashEvent(event_id='CAD_SOURCE_COMPLETION_'+key[0]+'_'+key[1],action_type='CASH_DIVIDEND',old_security_id=case['sid'],ticker=key[0],ex_date=key[1],record_date=case['record'],pay_date=case['pay'],available_at=case['accepted'],cash_per_old_share=float(current[1]),currency='CAD',amount_unit=ca.CAD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,source_type='TIER1_ISSUER_REGULATOR_EXCHANGE',source_reference=old['original_current_fragment']['ref']['path'],source_fingerprint=old['original_current_fragment']['ref']['sha256'])

    receipt=dict(status='SOURCE_SCHEMA_CLOCK_IDENTITY_ONLY_NOT_NATIVE_OR_ACCOUNT',key=list(key),event_fingerprint=event.event_fingerprint,packet_ref=packet['packet_ref'],material_ref=CCJ2024_MATERIAL_REF if key==('CCJ','2024-11-27') else MATERIAL_REF,declared_currency='CAD',current_amount_literal=current[1],frequency_original=case['frequency'],literal_sha256=hashlib.sha256(literal.encode()).hexdigest(),identity_sha256=digest(identity),source_available_at=case['accepted'],original_calendar_rule=rule,first_publication_at=None,strict_PIT=False,old_comparison_roles_kept=True,new_capture_not_historical_availability=True)

    return SourceQualification(key,event,receipt,digest(receipt))





def _r6_fraction_check(amount_usd, close):

    """Execute original R6 strict25pct AST; do not clone a financial formula."""

    tree=ast.parse(pin(R6_CHECK_REF).read_text(encoding='utf-8'));loops=[n for n in tree.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='event' and isinstance(n.iter,ast.Name) and n.iter.id=='cash'];require(len(loops)==1,'CAD_R6_SMALL_CASH_LOOP_CHANGED')

    body=loops[0].body;matches=[i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fraction' for t in n.targets)];require(len(matches)==1,'CAD_R6_FRACTION_AST_CHANGED');i=matches[0];selected=copy.deepcopy(body[i:i+2]);require(ast.unparse(selected[0])=='fraction = amount_usd / close' and ast.unparse(selected[1])=="check(fraction < 0.25, 'NORMAL_SMALL_CASH_STRICT_25PCT_CHECK_FAILED')",'CAD_R6_STRICT25PCT_AST_CHANGED');namespace=dict(amount_usd=amount_usd,close=close,check=require);exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),str(R6_CHECK_REF['path']),'exec'),namespace);return namespace['fraction']





@dataclass(frozen=True)

class FXQualification:

    old_marks: tuple

    early_marks: tuple

    marks: tuple

    proof: dict

    proof_sha256: str





def _pinned_fx_records(ref):

    # Future authorized numeric stage only. Lexically skip every other field.

    from scripts.research.a2.data.consensus_account_inputs import _JsonProjection

    rows=[]

    with pin(ref).open('rb') as stream:

        q=_JsonProjection(stream);q.descend(('observations',));q.expect(b'[');q.white()

        while q.peek()!=b']':

            row=q.metadata_fields({'currency','rate_unit','observation_date','available_at','currency_per_usd','source_reference','source_fingerprint'})

            require(set(row)=={'currency','rate_unit','observation_date','available_at','currency_per_usd','source_reference','source_fingerprint'},'CAD_EXACT_QUALIFIED_FX_OBSERVATION_FIELDS_REQUIRED');rows.append(row);q.white()

            if q.peek()==b']':break

            q.expect(b',');q.white()

    return rows





def qualify_fx_marks(old_marks, early_marks, *, sources):

    # Only after SOURCE-gated events. This API is not an authorization to read.

    sources=tuple(sources);require(sources and all(type(s) is SourceQualification and s.receipt_sha256==digest(s.receipt) and s.receipt['event_fingerprint']==s.event.event_fingerprint for s in sources),'CAD_SOURCE_GATE_REQUIRED_BEFORE_FX_NUMERIC')

    pin(EARLY_FX_QUAL_REF);old=tuple(old_marks);early=tuple(early_marks)

    expected_old=_pinned_fx_records(OLD_FX_REF);expected_early=_pinned_fx_records(EARLY_FX_REF)

    require([asdict(m) for m in old]==expected_old and [asdict(m) for m in early]==expected_early,'CAD_MARKS_MUST_MATCH_EACH_PINNED_BOOK_PAYLOAD')

    merged=merge_fx_marks(old,early)

    proof=dict(old_book_ref=OLD_FX_REF,early_book_ref=EARLY_FX_REF,early_qualification_ref=EARLY_FX_QUAL_REF,old_payload_sha256=digest(expected_old),early_payload_sha256=digest(expected_early),old_count=len(old),early_count=len(early),merged_count=len(merged),source_receipt_fingerprints=sorted(s.receipt_sha256 for s in sources),old_objects_preserved=True,no_rate_or_version_choice=True,global_latest_release_proved=False,revision_vintage='UNKNOWN')

    return FXQualification(old,early,merged,proof,digest(proof))





def _validate_fx_qualification(value):

    require(type(value) is FXQualification and value.proof_sha256==digest(value.proof) and value.proof['old_book_ref']==OLD_FX_REF and value.proof['early_book_ref']==EARLY_FX_REF and value.proof['early_qualification_ref']==EARLY_FX_QUAL_REF and digest([asdict(m) for m in value.old_marks])==value.proof['old_payload_sha256'] and digest([asdict(m) for m in value.early_marks])==value.proof['early_payload_sha256'],'CAD_QUALIFIED_FX_PAYLOAD_CHANGED')

    require(len(value.marks)==len(value.old_marks)+len(value.early_marks) and all(a is b for a,b in zip(value.marks,value.old_marks+value.early_marks)),'CAD_FX_BOOK_OBJECT_OR_ORDER_CHANGED')

    return value





def qualify_native(source, prior, fx_marks, *, fx_book_refs):

    require(type(source) is SourceQualification and source.receipt_sha256==digest(source.receipt) and source.receipt['event_fingerprint']==source.event.event_fingerprint,'CAD_SOURCE_GATE_REQUIRED_BEFORE_PRIOR_OR_FX')

    case=CASES[source.key];require(prior['ticker']==source.key[0] and prior['trade_date']==case['prior'] and prior['security_uid']=='CUSIP:'+case['cusip'] and prior['security_id']==case['sid'] and prior['price_currency']=='USD' and prior['price_coordinate']=='RAW_CLOSE' and prior['quantity_coordinate']==ca.RAW_OLD_SHARE_COORDINATE and prior['source_coordinate']=='RAW_ACTUAL_SHARE' and prior['same_prior_ex_UID_and_SID'] is True and prior['share_quantity_effect'] is False,'CAD_EXACT_PRIOR_USD_RAW_QUOTE_UID_REQUIRED')

    close=prior['raw_close'];require(type(close) in (int,float) and math.isfinite(close) and close>0,'CAD_POSITIVE_EXACT_PRIOR_CLOSE_REQUIRED');clock=cash._clock(pd.Timestamp(case['prior']),16,0);require(pd.Timestamp(source.event.available_at)<=clock<CUT,'CAD_SOURCE_AVAILABLE_BEFORE_PRIOR_CLOSE_REQUIRED')

    require(fx_book_refs=={'old':OLD_FX_REF,'early':EARLY_FX_REF,'early_qualification':EARLY_FX_QUAL_REF},'CAD_FROZEN_OLD_AND_EARLY_FX_BOOK_REFS_REQUIRED')

    for r in fx_book_refs.values():pin(r)

    fx=_validate_fx_qualification(fx_marks);require(source.receipt_sha256 in fx.proof['source_receipt_fingerprints'],'CAD_FX_SOURCE_RECEIPT_NOT_BOUND');mark=ca.select_foreign_fx_mark(fx.marks,as_of=clock);require(mark is not None,'CAD_PUBLISHED_PRE_PRIOR_FX_MARK_REQUIRED')

    claim=ca.ForeignCashReceivable(source.event.event_id,case['sid'],source.key[1],case['pay'],1.,'CAD',source.event.cash_per_old_share,source.event.source_fingerprint)

    amount_usd=ca.foreign_claim_value_usd((claim,),mark,as_of=clock);fraction=_r6_fraction_check(amount_usd,close)

    proof=dict(status='CAD_R6_SOURCE_TYPE_AND_PUBLISHED_FX_SMALL_CASH_QUALIFIED_NOT_USD_ADJUDICATION',source_receipt=copy.deepcopy(source.receipt),source_receipt_sha256=source.receipt_sha256,event_fingerprint=source.event.event_fingerprint,original_CAD_event=asdict(source.event),prior_raw_projection=copy.deepcopy(prior),selected_original_H10_mark=asdict(mark),FX_asof=str(clock),fx_book_refs=copy.deepcopy(fx_book_refs),qualified_FX_payload_proof=copy.deepcopy(fx.proof),qualified_FX_payload_proof_sha256=fx.proof_sha256,USD_comparator_only_amount=amount_usd,cash_fraction_in_USD=fraction,strict_upper_bound=.25,comparison_owner_ref=R6_CHECK_REF,declared_CAD_amount_was_not_relabelled_USD=True,temporary_one_share_projection_not_account_receivable=True,source_only_no_replay_or_fit=True,strict_PIT=False)

    return NativeQualification(source,proof,digest(proof))





def merge_fx_marks(old_marks, early_marks):

    """Retain every old object and let the original owner reject conflicts."""

    old=tuple(old_marks);early=tuple(early_marks);combined=old+early

    if combined:ca.select_foreign_fx_mark(combined,as_of='2025-12-31T23:59:59+00:00')

    require(all(a is b for a,b in zip(old,combined)),'CAD_OLD_FX_OBJECT_IDENTITY_CHANGED')

    return combined





ORIGINAL_KWARGS_REF = dict(path='D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/continuation/cash_r4/inputs/cash_replay_kwargs.joblib', sha256='abf6d1b0e22651fc87141c214971871332af4ba937716bc8d2e7bc5c7a5d5e4c')
ORIGINAL_BLOCKERS_REF = dict(path=str(Path('D:/us-tech-quant-results/_maintenance')/TASK/'source_repair/CAD_THREE_ORIGINAL_FIVEFIELD_SOURCE_METADATA_BINDING_R25_R1.json'), sha256='7c6a30457c5a181cc4a2c351a1b95e253a10f3a6dfe1dc7994e801357e6fa919')
ORIGINAL_FIELDS = {'ticker','effective_date','reason','source_reference','source_fingerprint'}
ORIGINAL7 = {'corporate_actions','corporate_action_known_at','unsupported_events','entitlement_enabled','entitlement_events','entitlement_security_tickers','entitlement_source_binding'}


def qualify_original_records(original, native, *, original_ref):
    """Bind closed CAD proofs to all five original fields; never infer a removal."""
    from scripts.research.a2.data import consensus_account_inputs as inputs
    require(set(original)==ORIGINAL7 and {k:original_ref[k] for k in ('path','sha256')}==ORIGINAL_KWARGS_REF,'CAD_PROVEN_ORIGINAL7_SOURCE_REF_REQUIRED')
    native=tuple(native);has4=any(n.source.key==('CCJ','2024-11-27') for n in native)
    metadata_ref=CCJ2024_ORIGINAL_BLOCKERS_REF if has4 else ORIGINAL_BLOCKERS_REF
    require(not has4 or all(n.source.key==('CCJ','2024-11-27') for n in native),'CAD_FOURTH_COMPONENT_MUST_BE_SEPARATE_FROM_OLD_THREE')
    metadata=json.loads(pin(metadata_ref).read_text(encoding='utf-8'))
    require(metadata['status']==('PINNED_ORIGINAL194_FIVEFIELD_METADATA_REQUIRES_ACTUAL_SERDE_MATCH' if has4 else 'PASS_EXACT_ORIGINAL7_PREDECODE_AUTHORITY_AND_THREE_FIVEFIELD_METADATA') and {k:metadata['original_kwargs_ref'][k] for k in ('path','sha256')}==ORIGINAL_KWARGS_REF,'CAD_PROVEN_ORIGINAL_FIVEFIELD_AUTHORITY_REQUIRED')
    authority={tuple(r['key']):r for r in metadata['records']}
    require(set(authority)==({('CCJ','2024-11-27')} if has4 else set(ORIGINAL_THREE_KEYS)),'CAD_EXACT_COMPONENT_ORIGINAL_AUTHORITIES_REQUIRED')
    native=tuple(native);require(0<len(native)<=len(CASES) and len({n.source.key for n in native})==len(native),'CAD_EXACT_NATIVE_KEYS_REQUIRED')
    records=[];bindings=[]
    for n in native:
        require(type(n) is NativeQualification and n.proof_sha256==digest(n.proof) and n.source.key in CASES and n.proof['event_fingerprint']==n.source.event.event_fingerprint and n.source.receipt_sha256==digest(n.source.receipt) and n.proof['source_receipt_sha256']==n.source.receipt_sha256 and n.proof['original_CAD_event']==asdict(n.source.event),'CAD_CLOSED_NATIVE_PROOF_REQUIRED')
        expected=authority[n.source.key]['original_record'];require(set(expected)==ORIGINAL_FIELDS,'CAD_EXACT_ORIGINAL_FIVE_FIELDS_REQUIRED')
        matches=[e for e in original['unsupported_events'] if inputs.existing.source._key(e)==authority[n.source.key]['original_record_key']]
        require(len(matches)==1 and matches[0]==expected and inputs.existing.source._key(expected)==authority[n.source.key]['original_record_key'] and expected['ticker']==n.source.event.ticker and str(pd.Timestamp(expected['effective_date']).date())==n.source.event.ex_date,'CAD_EXACT_ORIGINAL_RECORD_ALL_FIELDS_REQUIRED')
        records.append(copy.deepcopy(expected));bindings.append(dict(original_record_key=authority[n.source.key]['original_record_key'],event_fingerprint=n.source.event.event_fingerprint,native_proof_fingerprint=n.proof_sha256,source_receipt_fingerprint=n.source.receipt_sha256))
    proof=dict(status='PASS_CLOSED_CAD_NATIVE_AND_EXACT_ORIGINAL_FIVEFIELD_BINDING',original_kwargs_ref=copy.deepcopy(ORIGINAL_KWARGS_REF),metadata_authority_ref=copy.deepcopy(metadata_ref),removed_exact_original_keys=records,bindings=bindings)
    return dict(proof=proof,proof_sha256=digest(proof))


def merge_cad_completion(combined, native, *, manifest_ref, qualified_fx, original_resolution=None):

    """Original no-choice merger plus explicit FX merge; no account evaluation."""

    from scripts.research.a2.data import consensus_account_inputs as inputs

    native=tuple(native);require(0<len(native)<=len(CASES) and len({n.source.key for n in native})==len(native),'CAD_EXACT_NATIVE_KEYS_REQUIRED')

    for n in native:require(type(n) is NativeQualification and n.proof_sha256==digest(n.proof) and n.source.key in CASES and n.proof['event_fingerprint']==n.source.event.event_fingerprint,'CAD_CLOSED_NATIVE_PROOF_REQUIRED')

    events=tuple(n.source.event for n in native);payload={'entitlement_events':events,'entitlement_security_tickers':{e.old_security_id:e.ticker for e in events},'entitlement_source_binding':{'source_fingerprint':digest([n.proof_sha256 for n in native]),'manifest':{'removed_exact_original_keys':[],'CAD_native_proof_fingerprints':[n.proof_sha256 for n in native]},'security_tickers':{e.old_security_id:e.ticker for e in events}},'research_account_authority':{}}

    if original_resolution is not None:
        require(original_resolution['proof_sha256']==digest(original_resolution['proof']),'CAD_ORIGINAL_RESOLUTION_PROOF_CHANGED')
        proof=original_resolution['proof'];original_view={k:combined[k] for k in ORIGINAL7}
        verified=qualify_original_records(original_view,native,original_ref=proof['original_kwargs_ref'])
        require(verified==original_resolution,'CAD_EXACT_NATIVE_ORIGINAL_RESOLUTION_CHANGED')
        payload['entitlement_source_binding']['manifest'].update(removed_exact_original_keys=copy.deepcopy(proof['removed_exact_original_keys']),CAD_original_resolution=copy.deepcopy(original_resolution))
    result=inputs.merge_completion_descendant(combined,{'events':payload},manifest_ref)

    # Without an explicit closed five-field proof, every original blocker remains.

    fx=_validate_fx_qualification(qualified_fx);old_marks=tuple(combined.get('foreign_fx_marks',()));require(len(old_marks)==len(fx.old_marks) and all(a is b for a,b in zip(old_marks,fx.old_marks)),'CAD_COMBINED_OLD_TRP_MARK_IDENTITY_CHANGED');require(all(n.proof['qualified_FX_payload_proof_sha256']==fx.proof_sha256 for n in native),'CAD_NATIVE_FX_SOURCE_BOOK_PROOF_CHANGED');result['foreign_fx_marks']=merge_fx_marks(old_marks,fx.early_marks)

    return result





def private_shareholder_namespace(native, *, old_trp_fingerprints):

    """One exact private predicate; both account entry points share validator."""

    from scripts.research.a2.evaluation import consensus_shareholder_account as owner

    native=tuple(native);require(all(type(n) is NativeQualification and n.proof_sha256==digest(n.proof) and n.source.key in CASES for n in native),'CAD_NATIVE_SCOPE_PROOFS_REQUIRED');allowed={n.source.event.event_fingerprint:n.source.event for n in native};trp=frozenset(old_trp_fingerprints);require(trp and all(re.fullmatch(r'[0-9a-f]{64}',x) for x in trp),'CAD_ORIGINAL_TRP_FINGERPRINT_SCOPE_REQUIRED')

    def allowed_foreign(event):

        if event.ticker=='TRP':return event.event_fingerprint in trp

        expected=allowed.get(event.event_fingerprint)

        return expected is not None and type(event) is ca.SourceBackedForeignCashEvent and asdict(event)==asdict(expected)

    tree=ast.parse(Path(owner.__file__).read_text(encoding='utf-8'));original=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_task_authority');node=copy.deepcopy(original)

    anchors=[i for i,n in enumerate(node.body) if isinstance(n,ast.If) and any(isinstance(x,ast.Constant) and x.value=='CAD_CASH_EXACT_TRP_COMMON_SCOPE_REQUIRED' for x in ast.walk(n))];require(len(anchors)==1,'CAD_PRIVATE_FOREIGN_SCOPE_AST_ANCHOR_CHANGED');i=anchors[0];old_test=copy.deepcopy(node.body[i].test);node.body[i].test=ast.parse('any(not _cad_allowed_foreign(e) for e in foreign_events)',mode='eval').body

    restored=copy.deepcopy(node);restored.body[i].test=old_test;require(ast.dump(restored,include_attributes=False)==ast.dump(original,include_attributes=False),'CAD_OTHER_AUTHORITY_BUSINESS_AST_CHANGED')

    namespace=dict(vars(owner),_cad_allowed_foreign=allowed_foreign);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),owner.__file__,'exec'),namespace)

    validator=namespace['validate_task_authority']

    for name in ('make_task_authority','run_shareholder_cash_account'):

        old=getattr(owner,name);new=FunctionType(old.__code__,namespace,name=name,argdefs=old.__defaults__,closure=old.__closure__);new.__kwdefaults__=old.__kwdefaults__;namespace[name]=new

    require(namespace['make_task_authority'].__globals__['validate_task_authority'] is validator and namespace['run_shareholder_cash_account'].__globals__['validate_task_authority'] is validator,'CAD_TWO_ACCOUNT_ENTRY_VALIDATOR_IDENTITY_CHANGED')

    namespace['cad_projection_lineage']=dict(exact_new_event_fingerprints=sorted(allowed),original_TRP_fingerprints=sorted(trp),foreign_scope_anchor_count=1,other_authority_business_AST_unchanged=True,account_entry_business_code_unchanged=True,real_account_execution_authorized=False)

    return SimpleNamespace(**namespace)





def private_input_namespace(routed_inputs, shareholder, connector):

    """Rebind existing hook/globals only; no source-loader algorithm changes."""

    namespace=dict(vars(routed_inputs));old_hook=namespace['_routing_connect_supplements']

    def connect(*args):

        combined,composition=old_hook(*args);result=connector(combined)

        return result,dict(original=composition,CAD_connector_source_only=True)

    namespace.update(account=shareholder,_routing_connect_supplements=connect);old=namespace['load_account_inputs'];new=FunctionType(old.__code__,namespace,name=old.__name__,argdefs=old.__defaults__,closure=old.__closure__);new.__kwdefaults__=old.__kwdefaults__;namespace['load_account_inputs']=new

    require(new.__code__ is old.__code__,'CAD_INPUT_LOADER_BUSINESS_CODE_CHANGED')

    return SimpleNamespace(**namespace)





def engineering_capsule(*, source_owner_ref, test_ref, source_material_ref=MATERIAL_REF):

    require(source_material_ref==MATERIAL_REF,'CAD_FIXED_SOURCE_MATERIAL_REQUIRED')

    return dict(schema='CAD_THREE_EXACT_SOURCE_CONSUMER_ENGINEERING_CAPSULE_R1',status=ENGINEERING,task_id=TASK,source_owner_ref=source_owner_ref,test_ref=test_ref,protected_source_pins=protected_pins(),source_material_ref=source_material_ref,FX_book_refs={'old':OLD_FX_REF,'early':EARLY_FX_REF,'early_qualification':EARLY_FX_QUAL_REF},exact_keys=[list(k) for k in CASES],required_actual_SOURCE_HTTP200_count=len(CASES),allowed_future_prior_keys=[dict(ticker=k[0],prior_date=v['prior'],security_uid='CUSIP:'+v['cusip'],security_id=v['sid']) for k,v in CASES.items()],source_stage_before_RAW_or_FX_numeric=True,prior_fit_units=1291,fit_limit=10000,fit_budget_reset=False,actual_SOURCE_native_RAW_FX_numeric_account_or_2026_authorized=False)





def spawn_engineering_identity(queue, source_ref, event_terms):

    """Windows spawn test target: synthetic typed roundtrip, never data loading."""

    require(file_ref(__file__)==source_ref,'CAD_WORKER_SOURCE_VERSION_CHANGED')

    events=tuple(ca.SourceBackedForeignCashEvent(**x) for x in event_terms)

    queue.put(dict(source_ref=source_ref,typed_fingerprints=[e.event_fingerprint for e in events],event_terms=[asdict(e) for e in events],ca_owner_ref=file_ref(ca.__file__),numeric_data_read=False,account_or_fit_run=False))