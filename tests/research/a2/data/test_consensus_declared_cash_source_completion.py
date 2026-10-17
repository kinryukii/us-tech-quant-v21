from pathlib import Path
import copy,hashlib,json
import pytest
from scripts.research.a2.data import consensus_declared_cash_source_completion as D,consensus_account_inputs as I

def fixture(monkeypatch,tmp_path):
    body=b'<p>Board approved quarterly dividend $0.40 per share of common stock, record December 22, 2025, payable January 16, 2026.</p>';p=tmp_path/'cash.html';p.write_bytes(body);r=dict(path=str(p),sha256=hashlib.sha256(body).hexdigest());monkeypatch.setattr(D,'CASE_CAPSULE_REFS',{'JCI':r});monkeypatch.setattr(D,'_declared_identity',lambda fact:{});monkeypatch.setattr(D,'_declared_common_usd_unit',lambda support,**kw:{});monkeypatch.setattr(D,'_pin',lambda r:Path(r['path']))
    caps=tmp_path/'cap.json';caps.write_text(json.dumps(dict(original_opaque_ref=r,current_original_declared_cash_fragment=dict(fragment_ref=r,physical_byte_range=[0,len(body)]),record_date='2025-12-22',future_announced_pay_date='2026-01-16',original_article_calendar_date='2025-12-04')));capref=dict(path=str(caps),sha256=hashlib.sha256(caps.read_bytes()).hexdigest());monkeypatch.setattr(D,'CASE_CAPSULE_REFS',{'JCI':capref})
    return dict(schema=D.FACT_SCHEMA,source_kind='ISSUER_PRE2026_DECLARED_FIXED_USD_RAW_LISTED_CASH',primary_source_provider='ISSUER_IR',amount_source_role='ORIGINAL_PRE2026_ISSUER_DECLARATION_NOT_VENDOR_PAYMENT_RESULT',ticker='JCI',original5field_key=dict(ticker='JCI',effective_date='2025-12-22',reason='SYNTHETIC',source_reference='SYNTHETIC',source_fingerprint='a'*64),ex_date='2025-12-22',record_date='2025-12-22',pay_date='2026-01-16',declaration_displayed_date='2025-12-04',available_at=None,strict_PIT=False,actual_payment_status_read=False,vendor_payment_amount_read=False,common_usd_unit_support=dict(issuer_CIK=833444),original_current_source_ref=r,current_cash_fragment_ref=r,current_cash_physical_range=[0,len(body)],current_original_cash_text='Board approved quarterly dividend $0.40 per share of common stock, record December 22, 2025, payable January 16, 2026.',declared_cash_amount_decimal='.40',current_action_literal='approved',record_literal='December 22, 2025',pay_literal='January 16, 2026',current_common_literal='common stock',currency='USD',amount_unit='USD_PER_RAW_OLD_SHARE',quantity_coordinate='RAW_OLD_SECURITY_SHARES',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.JCI',original_issuer_source_url='https://synthetic.invalid/2025-12-04',approved_current_capsule_ref=capref)

def test_declared_future_schedule_uses_pre26_literal_original_ca_type(monkeypatch,tmp_path):
    fact=fixture(monkeypatch,tmp_path);event=D._declared_fact_event(I.existing.ca,fact,dict(path='D:/synthetic/fact.json',sha256='b'*64))
    assert type(event) is I.existing.ca.ResearchReconstructedCashEvent and event.pay_date=='2026-01-16' and event.cash_per_old_share==.4 and event.available_at is None and event.source_type=='TIER1_ISSUER_REGULATOR_EXCHANGE'

@pytest.mark.parametrize('bad',('issuer','current_money','payment_result','record_iso','pay_iso','source_text','fake_common','future_displaydate'))
def test_declared_source_hard_boundaries(monkeypatch,tmp_path,bad):
    fact=fixture(monkeypatch,tmp_path)
    if bad=='issuer':fact['common_usd_unit_support']['issuer_CIK']=1108524
    elif bad=='current_money':fact['declared_cash_amount_decimal']='.41'
    elif bad=='payment_result':fact['vendor_payment_amount_read']=True
    elif bad=='record_iso':fact['record_date']='2025-12-23'
    elif bad=='pay_iso':fact['pay_date']='2026-01-17'
    elif bad=='source_text':fact['current_original_cash_text']+=' fake'
    elif bad=='fake_common':fact['current_common_literal']='preferred stock'
    elif bad=='future_displaydate':fact['declaration_displayed_date']='2026-01-01'
    with pytest.raises(ValueError):D._declared_fact_event(I.existing.ca,fact,dict(path='D:/synthetic/fact.json',sha256='b'*64))

def test_declared_native_bridge_pins_original_owner_and_no_cash_math_copy():
    p=Path(D.ORIGINAL_NATIVE_OWNER_REF['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==D.ORIGINAL_NATIVE_OWNER_REF['sha256'];import ast
    text=Path(D.__file__).read_text();tree=ast.parse(text);assert not any(isinstance(x,ast.ClassDef) for x in tree.body);assert 'original_usd_native_binder' in text and 'changes==dict(component_field=1,status=1,profile_field=2)' in text


def unit_fixture(monkeypatch,tmp_path,*,member=False,bad_context=False,oversized_context=False):
    def ref(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    header=b'ACCESSION NUMBER: 0000833444-25-000097\nCONFORMED SUBMISSION TYPE: 10-K\n<ACCEPTANCE-DATETIME>20251114105301\nCENTRAL INDEX KEY: 0000833444\n'
    tag=b'<ix:nonFraction name="us-gaap:CommonStockDividendsPerShareDeclared" unitRef="usdPerShare" contextRef="c-1">'
    unit=b'<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    context=b'<xbrli:context id="c-1"><xbrli:entity><xbrli:identifier>'+(b'999999' if bad_context else b'833444')+b'</xbrli:identifier></xbrli:entity>'+(b'X'*2100 if oversized_context else b'')+b'</xbrli:context>'
    primary=b'<html>'+unit+context+tag+b'NEVER_DECODE_VALUE</ix:nonFraction></html>'
    source=tmp_path/('primary.htm' if member else 'full.txt');body=primary if member else header+primary;source.write_bytes(body)
    hp=tmp_path/'header.bin';hp.write_bytes(header);tp=tmp_path/'tag.bin';tp.write_bytes(tag);up=tmp_path/'unit.bin';up.write_bytes(unit)
    support=dict(issuer_CIK=833444,accession='0000833444-25-000097',form='10-K',accepted_at_utc='2025-11-14T15:53:01+00:00',source_ref=ref(source),accepted_header_ref=ref(hp),common_concept='us-gaap:CommonStockDividendsPerShareDeclared',opening_tag_ref=ref(tp),opening_tag_physical_range=[body.index(tag),body.index(tag)+len(tag)],original_USD_divided_shares_ref=ref(up),unit_physical_range=[body.index(unit),body.index(unit)+len(unit)])
    expected={k:support[k] for k in ('source_ref','accepted_header_ref','accession','form','accepted_at_utc')}
    if member:
        prefix=tmp_path/'submission_prefix.bin';prefix.write_bytes(header+b'<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>primary.htm\n<TEXT>\n<XBRL>\n'+primary[:96]);expected['original_header_prefix_custody_ref']=ref(prefix)
    else:expected['original_header_prefix_custody_ref']=support['source_ref']
    monkeypatch.setattr(D,'APPROVED_UNIT_SUPPORTS',{833444:expected})
    original_read=Path.read_bytes
    def bounded_read(self):
        if self==source:raise AssertionError('FULL_FINANCIAL_DOCUMENT_READ_FORBIDDEN')
        return original_read(self)
    monkeypatch.setattr(Path,'read_bytes',bounded_read)
    return support,expected,source

@pytest.mark.parametrize('member',(False,True))
def test_real_unit_helper_bounded_same_submission(monkeypatch,tmp_path,member):
    support,expected,source=unit_fixture(monkeypatch,tmp_path,member=member)
    result=D._declared_common_usd_unit(support,before='2025-12-22T00:00:00+00:00')
    assert result['issuer_CIK']==833444 and result['unit_id']=='usdPerShare'

@pytest.mark.parametrize('bad',('foreign_header','late_source','wrong_accession','wrong_form','wrong_context','oversized_context','prefix_mismatch','wrong_currency'))
def test_real_unit_helper_source_version_and_context_failclosed(monkeypatch,tmp_path,bad):
    support,expected,source=unit_fixture(monkeypatch,tmp_path,member=True,bad_context=bad=='wrong_context',oversized_context=bad=='oversized_context')
    if bad=='foreign_header':support['accepted_header_ref']=dict(path='D:/unapproved/header',sha256='f'*64)
    elif bad=='late_source':support['source_ref']=dict(path='D:/unapproved/late',sha256='f'*64)
    elif bad=='wrong_accession':support['accession']='0000833444-26-000001'
    elif bad=='wrong_form':support['form']='8-K'
    elif bad=='prefix_mismatch':
        prefix=Path(expected['original_header_prefix_custody_ref']['path']);prefix.write_bytes(prefix.read_bytes().replace(b'<html>',b'<nope>'));expected['original_header_prefix_custody_ref']['sha256']=hashlib.sha256(prefix.read_bytes()).hexdigest()
    elif bad=='wrong_currency':
        source.write_bytes(source.open('rb').read().replace(b'iso4217:USD',b'iso4217:EUR'));support['source_ref']['sha256']=hashlib.sha256(source.open('rb').read()).hexdigest()
    with pytest.raises(ValueError):D._declared_common_usd_unit(support,before='2025-12-22T00:00:00+00:00')

def test_real_unit_helper_late_clock_rejected(monkeypatch,tmp_path):
    support,expected,source=unit_fixture(monkeypatch,tmp_path)
    with pytest.raises(ValueError,match='PREEX'):D._declared_common_usd_unit(support,before='2025-11-14T15:00:00+00:00')
