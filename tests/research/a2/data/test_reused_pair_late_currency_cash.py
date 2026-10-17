"""Synthetic canonical late USD admission; no real research/account/data files read."""
from pathlib import Path
from types import FunctionType
import ast,copy,hashlib,importlib.util,json,sys
import pandas as pd
import pytest
ROOT=Path(__file__).parent

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
from scripts.research.a2.data import joint_cash_bindings as cash
from scripts.research.a2.data import reused_pair_ca_sources as mod
oldtests=load('synthetic_late_currency_existing_harness',Path('D:/us-tech-quant/tests/research/a2/data/test_reused_pair_ca_sources.py'));oldtests.mod=mod
from scripts.v22 import corporate_action_transition_r1 as ca
from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle

@pytest.fixture
def h(tmp_path,monkeypatch):
 v=oldtests.Harness(tmp_path,monkeypatch);facts=oldtests.enable_historical_ex_opt_in(v)
 facts['issuer_jurisdiction']='BM'
 def raw(text):
  v.sequence+=1;key=f'D:/FAKE_ONLY/raw_{v.sequence}.txt';p=tmp_path/f'raw_{v.sequence}.txt';p.write_text(text,encoding='utf-8');v.files[key]=p;return dict(path=key,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
 earlytext='PEMBROKE, Bermuda -- The Board declared a quarterly dividend of $2 per common share on its common shares. The dividend is payable on February 1, 2023, to shareholders of record on January 20, 2023.'
 latecash='The Board of RenaissanceRe declared quarterly dividends of $ 2.00 per common share, payable to common shareholders of record on January 20, 2023, and the Company paid the dividends on February 1, 2023, respectively.'
 dollars='All dollar amounts referred to in this Form 10-Q are in U.S. dollars unless otherwise indicated.'
 early=dict(schema='ISSUER_ORDINARY_CASH_SOURCE_CUSTODY_R1',ticker='AAA',issuer='FAKE Issuer',listing_identity='NYSE:AAA',security_type='COMMON_SHARES',source_url='https://issuer.example/FAKE_pre_ex_announcement',announcement_date='2022-12-01',capture_utc='2026-10-10T01:00:00Z',cash_per_share=2.,record_date='2023-01-20',pay_date='2023-02-01',original_key_date='2023-01-19',original_support_keys=[v.vendor],source_share_unit='EXPLICIT_PER_COMMON_SHARE_ON_ITS_COMMON_SHARES',quarterly_cash_clause=earlytext,original_article_body_ref=raw('<p>'+earlytext+'</p>'),visible_text_ref=raw(earlytext+'\n'),currency='UNKNOWN')
 early_ref=v.write(early)
 late=dict(schema='SAME_EVENT_COMMON_CASH_CURRENCY_CORROBORATION_SOURCE_CUSTODY_R1',ticker='AAA',issuer='FAKE Issuer',source_filing_date='2023-03-01',capture_utc='2026-10-10T02:00:00Z',source_url='https://issuer.example/FAKE_later_report',cash_clause_literal=latecash,currency_definition_literal=dollars,definition_scope='THIS_FORM_10_K_OR_Q_ONLY_EXPLICIT',necessary_original_cash_paragraph_ref=raw('<div>'+latecash+'</div>'),necessary_original_usd_definition_ref=raw('<div>'+dollars+'</div>'),cash_visible_text_ref=raw(latecash+'\n'),currency_visible_text_ref=raw(dollars+'\n'),matches=[dict(original_declared_cash_source_custody_ref=early_ref,original_support_keys=[v.vendor],exact_record_date='2023-01-20',exact_pay_date='2023-02-01',exact_same_declared_common_share_cash_literal='2.00',common_share_coordinate_agrees=True,currency='USD')])
 late_ref=v.write(late)
 nested=[early_ref,late_ref,early['original_article_body_ref'],early['visible_text_ref'],late['necessary_original_cash_paragraph_ref'],late['necessary_original_usd_definition_ref'],late['cash_visible_text_ref'],late['currency_visible_text_ref']]
 projection=dict(schema='B_FROZEN_HISTORY_LATE_CURRENCY_CASH_SOURCE_PROJECTION_V1',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',currency_evidence_role=mod.LATE_CURRENCY_ROLE,source_scope=mod.LATE_CURRENCY_SOURCE_SCOPE,historical_available_at=None,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,source_projection=facts,identity_binding=copy.deepcopy(v.entry['identity_binding']),prior_raw_close=copy.deepcopy(v.endpoint),exact_original_unsupported_keys=[v.vendor],original_cash_source_custody_ref=early_ref,later_same_event_currency_custody_ref=late_ref,source_refs=nested)
 v.entry['fact_ref']=v.write(projection);v.bundle['source_refs'].extend(nested);v.bundle['later_same_event_currency_cash_scope']=copy.deepcopy(mod.LATE_CURRENCY_SCOPE)
 v.early,v.late,v.projection,v.raw=early,late,projection,raw
 v.owner.apply_entitlement_lifecycle=ca.apply_entitlement_lifecycle;v.owner.SourceBackedEntitlementEvent=ca.SourceBackedEntitlementEvent;v.owner.SourceBackedTerminalEvent=ca.SourceBackedTerminalEvent
 return v

def bind(h):
 h.entry['fact_ref']=h.write(h.projection);return mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))

def test_bm_late_usd_is_account_fact_not_pre_ex_availability(h):
 before=copy.deepcopy(h.original);r=bind(h);e=r['events']['entitlement_events'][0];p=r['receipt']['proofs'][0]
 assert isinstance(e,ca.ResearchReconstructedCashEvent) and e.available_at is None
 assert e.cash_per_old_share==2. and e.currency=='USD' and e.record_date=='2023-01-20' and e.pay_date=='2023-02-01'
 assert h.original==before and r['receipt']['removed_keys']==1 and r['events']['unsupported_events']==(h.raw_flag,)
 assert p['historical_availability_qualified'] is False and p['currency_evidence_role']==mod.LATE_CURRENCY_ROLE
 b=p['late_currency_binding'];assert b['original_cash_publication_date']=='2022-12-01' and b['later_report_publication_date']=='2023-03-01'
 assert pd.Timestamp(b['original_cash_current_capture_utc']).year==2026 and b['historical_availability_authority']=='UNKNOWN'
 assert ca._validate_research_account_authority(r['events']['entitlement_events'],r['events']['research_account_authority'])['strict_PIT_promotion_eligible'] is False
 assert all(mod.LATE_CURRENCY_SCOPE[k] is False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))


def test_real_owner_ordinary_clock_applies_without_new_account_engine(h):
 r=bind(h);e=r['events']['entitlement_events'][0]
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,receipt=ordinary_cash_lifecycle(h.owner,r['events'],r['ordinary_cash_event_fingerprints'],clone=clone)
 assert ca._entitlement_pay_date(e)=='2023-02-01' and fn.__globals__['_entitlement_pay_date'](e)=='2023-02-02'
 assert receipt['events'][0]['research_cash_not_before_date']=='2023-02-02'

@pytest.mark.parametrize('change',['no_scope','wrong_scope','availability','PIT','currency','class','jurisdiction','amount','record','pay','duplicate_match','cash_bytes','usd_bytes','usd_report_scope','late_publication','capture_naive','source_pin_missing','different_issuer','unknown_last_event','legacy_schema'])
def test_same_event_currency_admission_rejects_real_counterexamples(h,change):
 if change=='no_scope':del h.bundle['later_same_event_currency_cash_scope']
 elif change=='wrong_scope':h.bundle['later_same_event_currency_cash_scope']['issuer_jurisdiction']='US'
 elif change=='availability':h.projection['source_projection']['available_at']='2022-12-03T00:00:00Z'
 elif change=='PIT':h.projection['strict_PIT']=True
 elif change=='currency':h.projection['source_projection']['currency']='BMD'
 elif change=='class':h.projection['source_projection']['security_type']='AMERICAN_DEPOSITARY_SHARE'
 elif change=='jurisdiction':h.projection['source_projection']['issuer_jurisdiction']='US'
 elif change=='amount':h.projection['source_projection']['cash_per_raw_share']=3.
 elif change=='record':h.projection['source_projection']['record_date']='2023-01-23'
 elif change=='pay':h.projection['source_projection']['pay_date']='2023-02-02'
 elif change=='duplicate_match':h.late['matches'].append(copy.deepcopy(h.late['matches'][0]))
 elif change=='cash_bytes':h.files[h.early['original_article_body_ref']['path']].write_text('counterfeit',encoding='utf-8')
 elif change=='usd_bytes':h.files[h.late['necessary_original_usd_definition_ref']['path']].write_text('counterfeit',encoding='utf-8')
 elif change=='usd_report_scope':h.late['currency_definition_literal']='All issuer dividends always use U.S. dollars.'
 elif change=='late_publication':h.late['source_filing_date']='2026-02-11'
 elif change=='capture_naive':h.late['capture_utc']='2026-10-10T02:00:00'
 elif change=='source_pin_missing':h.projection['source_refs'].remove(h.early['original_article_body_ref'])
 elif change=='different_issuer':h.late['issuer']='Other Issuer'
 elif change=='unknown_last_event':h.late['matches']=[]
 else:h.projection['schema']='B_FROZEN_HISTORY_POST_VERIFIED_CASH_SOURCE_PROJECTION_V1'
 if change in ['duplicate_match','usd_report_scope','late_publication','capture_naive','different_issuer','unknown_last_event']:
  old=h.projection['later_same_event_currency_custody_ref'];new=h.write(h.late);h.projection['later_same_event_currency_custody_ref']=new;h.projection['source_refs']=[new if x==old else x for x in h.projection['source_refs']];h.bundle['source_refs']=[new if x==old else x for x in h.bundle['source_refs']]
 with pytest.raises(ValueError):bind(h)




def test_existing_usca_adjudication_still_blocks_bm_without_new_role(h):
 facts=copy.deepcopy(h.projection['source_projection']);env=dict(path='D:/FAKE_ONLY/facts.json',sha256='e'*64,payload=facts,guard=dict(status='HASH_VERIFIED_PAYLOAD',path='D:/FAKE_ONLY/facts.json',sha256='e'*64,payload_sha256=cash._hash(facts)))
 r=cash.adjudicate_post_verified_cash_ex(env,calendar=[str(x.date()) for x in h.dates],calendar_binding=h.bundle['historical_calendar_binding'],rule_sources=h.bundle['historical_rule_sources'],scope_end_exclusive='2026-01-01',source_scope='FROZEN_PRE2026_NYSE_COMMON_USD')
 assert r['status']=='BLOCKED_SOURCE' and r['reason']=='NORMAL_CASH_IDENTITY_CURRENCY_OR_RAW_UNIT_UNBOUND'


def test_absent_new_scope_preserves_existing_source_declared_common_behavior(tmp_path,monkeypatch):
 v=oldtests.Harness(tmp_path,monkeypatch);r=v.bind();e=r['events']['entitlement_events'][0]
 assert type(e) is ca.SourceBackedEntitlementEvent and e.available_at=='2022-12-03 00:00:00+00:00'
 assert 'later_same_event_currency_cash_scope' not in r['receipt']

@pytest.mark.parametrize('authority',['strict_PIT','production_qualified','quote_qualified','certified_NAV'])
def test_scope_integer_zero_is_not_boolean_false(h,authority):
 h.bundle['later_same_event_currency_cash_scope'][authority]=0
 with pytest.raises(ValueError,match='CA_EXACT_PINNED_LATE_CURRENCY_SCOPE_REQUIRED'):
  bind(h)
