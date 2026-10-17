"""Synthetic canonical SEC accounting facts through original B cash lifecycle."""
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
oldtests=load('synthetic_sec_existing_harness',Path('D:/us-tech-quant/tests/research/a2/data/test_reused_pair_ca_sources.py'));oldtests.mod=mod
from scripts.v22 import corporate_action_transition_r1 as ca
from scripts.research.a2.evaluation.reused_policy_pair import ordinary_cash_lifecycle

@pytest.fixture
def h(tmp_path,monkeypatch):
 v=oldtests.Harness(tmp_path,monkeypatch);facts=oldtests.enable_historical_ex_opt_in(v)
 def raw(body):
  if isinstance(body,str):body=body.encode()
  v.sequence+=1;key=f'D:/FAKE_ONLY/bytes_{v.sequence}';p=tmp_path/f'bytes_{v.sequence}';p.write_bytes(body);v.files[key]=p;return dict(path=key,sha256=hashlib.sha256(body).hexdigest())
 v.raw=raw;v.entry['identity_binding'].update(sec_filer_cik=123,sec_legal_name_literal='FAKE ISSUER CORP/TX')
 facts.update(issuer_jurisdiction='US',sec_filer_cik=123,publication_calendar_date='2023-01-13',ex_date_provenance_role='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY')
 cashtext='On January 6, 2023, our Board declared a quarterly cash dividend of $ 2.00 per common share payable on February 1, 2023 to holders of record at the close of business on January 20, 2023.'
 nametext='FAKE ISSUER (Exact name of registrant as specified in its charter)'
 covertext='Common Stock, par value $0.01 per share AAA New York Stock Exchange'
 cb=('<p>'+cashtext+'</p>').encode();nb=('<p>'+nametext+'</p>').encode();vb=('<p>'+covertext+'</p>').encode()
 http=raw(cb+nb+vb)
 header=raw('FILED AS OF DATE: 20230113\nCOMPANY CONFORMED NAME: FAKE ISSUER CORP/TX\nCENTRAL INDEX KEY: 0000000123\nSTATE OF INCORPORATION: DE\n')
 v.cover=dict(schema='HISTORICAL_SEC_ORIGINAL_CASH_COVER_PROJECTION_V1',cik=123,filed_date='2023-01-13',legal_name_literal='FAKE ISSUER CORP/TX',original_http_ref=http,header_ref=header,cover_fragments=[dict(raw_byte_start=len(cb)+len(nb),raw_byte_end=len(cb)+len(nb)+len(vb),raw_fragment_sha256=hashlib.sha256(vb).hexdigest(),text=covertext)])
 v.name=dict(schema='HISTORICAL_SEC_SAME_FILE_REGISTRANT_NAME_CUSTODY_V1',cik=123,filed_date='2023-01-13',SEC_header_name_literal_preserved='FAKE ISSUER CORP/TX',original_http_ref=http,original_name_fragment_ref=raw(nb),source_original_byte_range=[len(cb),len(cb)+len(nb)],visible_text_ref=raw(nametext+'\n'),visible_text_typed_content_sha256=mod._hash(nametext),registrant_name_literal='FAKE ISSUER',context_literal='(Exact name of registrant as specified in its charter)',historical_availability_authority='UNKNOWN',strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 v.source=dict(schema='ISSUER_ORIGINAL_ORDINARY_CASH_FRAGMENT_CUSTODY_V1',ticker='AAA',cik=123,legal_name_literal='FAKE ISSUER CORP/TX',actual_filed_date='2023-01-13',announcement_date='2023-01-13',private_board_declaration_date='2023-01-06',source_publication_date_role='ACTUAL_SEC_FILED_DATE_NOT_PRIVATE_BOARD_DATE',capture_utc='2026-10-10T03:00:00Z',source_url='https://www.sec.gov/Archives/edgar/data/123/FAKE.txt',original_HTTP_ref=http,original_cash_fragment_ref=raw(cb),source_original_byte_range=[0,len(cb)],text_projection_ref=raw(cashtext+'\n'),dividend_paragraph=cashtext,dividend_paragraph_typed_content_sha256=mod._hash(cashtext),historical_availability_authority='UNKNOWN',strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 v.projection=dict(schema='B_FROZEN_HISTORY_SEC_CASH_FACT_SOURCE_PROJECTION_V1',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',cash_evidence_role=mod.SEC_CASH_ROLE,source_scope=mod.SEC_CASH_SOURCE_SCOPE,historical_available_at=None,exchange_notice_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,source_projection=facts,identity_binding=copy.deepcopy(v.entry['identity_binding']),prior_raw_close=copy.deepcopy(v.endpoint),exact_original_unsupported_keys=[v.vendor])
 v.bundle['sec_same_file_cash_fact_scope']=copy.deepcopy(mod.SEC_CASH_SCOPE)
 v.owner.apply_entitlement_lifecycle=ca.apply_entitlement_lifecycle;v.owner.SourceBackedEntitlementEvent=ca.SourceBackedEntitlementEvent;v.owner.SourceBackedTerminalEvent=ca.SourceBackedTerminalEvent
 return v

def refresh(h):
 cover=h.write(h.cover);h.name['same_source_common_listing_projection_ref']=cover;name=h.write(h.name);h.source['same_source_identity_projection_ref']=cover;source=h.write(h.source)
 refs=[source,cover,name,h.source['original_HTTP_ref'],h.source['original_cash_fragment_ref'],h.source['text_projection_ref'],h.cover['header_ref'],h.name['original_name_fragment_ref'],h.name['visible_text_ref']]
 h.projection.update(sec_cash_source_custody_ref=source,same_file_registrant_name_custody_ref=name,source_refs=refs)
 h.bundle['source_refs']=refs;h.entry['fact_ref']=h.write(h.projection)
def bind(h):
 refresh(h);return mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))

def test_seven_day_filing_is_only_retrospective_research_fact(h):
 before=copy.deepcopy(h.original);r=bind(h);e=r['events']['entitlement_events'][0];p=r['receipt']['proofs'][0]
 assert type(e) is ca.ResearchReconstructedCashEvent and e.available_at is None
 assert e.cash_per_old_share==2. and e.currency=='USD' and e.record_date=='2023-01-20' and e.pay_date=='2023-02-01'
 assert h.original==before and r['events']['unsupported_events']==(h.raw_flag,)
 b=p['sec_frozen_cash_binding'];assert b['actual_SEC_filed_date']=='2023-01-13' and b['private_board_declaration_date']=='2023-01-06'
 assert b['exchange_notice_authority']==b['actual_exchange_ex_authority']=='UNKNOWN'
 q=p['historical_ex_adjudication'];assert q['status']=='QUALIFIED_RESEARCH_FROZEN_CASH_FACT' and q['available_at'] is None
 assert q['ex_date_provenance_role']=='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY'
 assert p['historical_availability_qualified'] is False and all(mod.SEC_CASH_SCOPE[k] is False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
 assert ca._validate_research_account_authority(r['events']['entitlement_events'],r['events']['research_account_authority'])['strict_PIT_promotion_eligible'] is False

def test_original_ordinary_cash_clock_is_reused(h):
 r=bind(h);e=r['events']['entitlement_events'][0]
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,receipt=ordinary_cash_lifecycle(h.owner,r['events'],r['ordinary_cash_event_fingerprints'],clone=clone)
 assert ca._entitlement_pay_date(e)=='2023-02-01' and fn.__globals__['_entitlement_pay_date'](e)=='2023-02-02'
 assert receipt['events'][0]['research_cash_not_before_date']=='2023-02-02'

@pytest.mark.parametrize('case',['no_scope','scope_zero','known_available','PIT','actual_ex_authority','notice_authority','private_date_as_public','wrong_cik','cik_bool','wrong_header_name','wrong_name_bridge','bad_name_context','cover_ADS','cover_conflict','raw_cash_tampered','missing_pin','amount','record','pay','duplicate_frozen','wrong_ex','noncash','special','large_cash','wrong_raw_unit','filed2026','capture_naive'])
def test_exact_cash_and_identity_counterexamples_are_rejected(h,case):
 if case=='no_scope':del h.bundle['sec_same_file_cash_fact_scope']
 elif case=='scope_zero':h.bundle['sec_same_file_cash_fact_scope']['strict_PIT']=0
 elif case=='known_available':h.projection['source_projection']['available_at']='2023-01-13T00:00:00Z'
 elif case=='PIT':h.projection['strict_PIT']=True
 elif case=='actual_ex_authority':h.projection['actual_exchange_ex_authority']='QUALIFIED'
 elif case=='notice_authority':h.projection['exchange_notice_authority']='TIMELY'
 elif case=='private_date_as_public':h.projection['source_projection']['publication_calendar_date']='2023-01-06'
 elif case=='wrong_cik':h.cover['cik']=321
 elif case=='cik_bool':h.cover['cik']=True
 elif case=='wrong_header_name':h.cover['legal_name_literal']='OTHER CORP'
 elif case=='wrong_name_bridge':h.name['registrant_name_literal']='OTHER ISSUER'
 elif case=='bad_name_context':h.name['context_literal']='alias assumed from symbol'
 elif case=='cover_ADS':h.cover['cover_fragments'][0]['text']='ADS AAA New York Stock Exchange'
 elif case=='cover_conflict':h.cover['cover_fragments'].append(copy.deepcopy(h.cover['cover_fragments'][0]))
 elif case=='raw_cash_tampered':h.files[h.source['original_cash_fragment_ref']['path']].write_text('counterfeit')
 elif case=='missing_pin':
  refresh(h);h.projection['source_refs'].remove(h.source['original_HTTP_ref']);h.entry['fact_ref']=h.write(h.projection)
  with pytest.raises(ValueError):mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))
  return
 elif case=='amount':h.projection['source_projection']['cash_per_raw_share']=3.
 elif case=='record':h.projection['source_projection']['record_date']='2023-01-23'
 elif case=='pay':h.projection['source_projection']['pay_date']='2023-02-02'
 elif case=='duplicate_frozen':h.projection['source_projection']['frozen_event_exact_row_count']=2
 elif case=='wrong_ex':h.projection['source_projection']['exact_frozen_event_key']=dict(h.vendor,effective_date='2023-01-18')
 elif case=='noncash':h.projection['source_projection']['noncash_flags_absent']=False
 elif case=='special':h.projection['source_projection']['special_or_due_bill_indicator']=True
 elif case=='large_cash':h.projection['source_projection']['prior_raw_close']['raw_close']=8.;h.endpoint['raw_close']=8.;h.projection['prior_raw_close']['raw_close']=8.;h.audit_update()
 elif case=='wrong_raw_unit':h.projection['source_projection']['quantity_coordinate']='ADJUSTED_SHARE'
 elif case=='filed2026':h.source['actual_filed_date']='2026-01-01'
 elif case=='capture_naive':h.source['capture_utc']='2026-10-10T03:00:00'
 with pytest.raises(ValueError):bind(h)

def test_old_usca_publication_condition_is_not_relaxed(h):
 refresh(h);terms=mod._sec_frozen_cash_terms(h.projection,h.entry);facts=copy.deepcopy(terms['historical_ex_adjudication_input'])
 facts['ex_date_provenance_role']='DERIVED_NYSE_NORMAL_EX_FROM_RECORD_DATE_MATCHED_EXACT_FROZEN_EVENT'
 env=dict(path='D:/FAKE_ONLY/facts.json',sha256='e'*64,payload=facts,guard=dict(status='HASH_VERIFIED_PAYLOAD',path='D:/FAKE_ONLY/facts.json',sha256='e'*64,payload_sha256=cash._hash(facts)))
 r=cash.adjudicate_post_verified_cash_ex(env,calendar=[str(x.date()) for x in h.dates],calendar_binding=h.bundle['historical_calendar_binding'],rule_sources=h.bundle['historical_rule_sources'],scope_end_exclusive='2026-01-01',source_scope='FROZEN_PRE2026_NYSE_COMMON_USD')
 assert r['status']=='BLOCKED_SOURCE' and r['reason']=='ADVANCE_PUBLICATION_OR_FIXED_PAY_UNBOUND'


def multi_statement(h):
 selected='On 6 January 2023, the Board of Directors declared a quarterly dividend of $2.00 per share that was payable on 1 February 2023 to shareholders of record at the close of business on 20 January 2023.'
 current='On 15 March 2023, the Board of Directors declared a quarterly dividend of $3.00 per share that is payable on 1 June 2023 to shareholders of record at the close of business on 3 April 2023.'
 name_text='FAKE REGISTERED FULL COMPANY (Exact name of registrant as specified in its charter)'
 cover_text='Common Stock, par value $0.01 per share AAA New York Stock Exchange'
 policy_text='The Board of Directors determines whether to declare cash dividends on our common stock and the timing and amount based on financial condition and other factors it deems relevant.'
 cb=('<p>'+current+'</p>').encode();pb=('<p>'+selected+' '+current+'</p>').encode();ub=('<p>'+policy_text+'</p>').encode();nb=('<p>'+name_text+'</p>').encode();vb=('<p>'+cover_text+'</p>').encode()
 http=h.raw(cb+pb+ub+nb+vb)
 h.entry['identity_binding']['sec_legal_name_literal']='FAKE Issuer'
 h.projection['identity_binding']=copy.deepcopy(h.entry['identity_binding'])
 h.projection['source_projection']['publication_calendar_date']='2023-03-16'
 h.source.update(legal_name_literal='FAKE Issuer',actual_filed_date='2023-03-16',announcement_date='2023-03-16',private_board_declaration_date='2023-03-15',original_HTTP_ref=http,original_cash_fragment_ref=h.raw(cb),source_original_byte_range=[0,len(cb)],text_projection_ref=h.raw(current+'\n'),dividend_paragraph=current,dividend_paragraph_typed_content_sha256=mod._hash(current),
  original_two_statement_paragraph_ref=h.raw(pb),original_two_statement_byte_range=[len(cb),len(cb)+len(pb)],same_source_common_cash_policy_ref=dict(fragment_ref=h.raw(ub),original_byte_range=[len(cb)+len(pb),len(cb)+len(pb)+len(ub)],text_projection_ref=h.raw(policy_text+'\n'),paragraph_typed_content_sha256=mod._hash(policy_text)))
 h.cover.update(filed_date='2023-03-16',legal_name_literal='FAKE Issuer',original_http_ref=http,header_ref=h.raw('FILED AS OF DATE: 20230316\nCOMPANY CONFORMED NAME: FAKE Issuer\nCENTRAL INDEX KEY: 0000000123\nSTATE OF INCORPORATION: DE\n'),cover_fragments=[dict(raw_byte_start=len(cb)+len(pb)+len(ub)+len(nb),raw_byte_end=len(cb)+len(pb)+len(ub)+len(nb)+len(vb),raw_fragment_sha256=hashlib.sha256(vb).hexdigest(),text=cover_text)])
 h.name.update(filed_date='2023-03-16',SEC_header_name_literal_preserved='FAKE Issuer',original_http_ref=http,original_name_fragment_ref=h.raw(nb),source_original_byte_range=[len(cb)+len(pb)+len(ub),len(cb)+len(pb)+len(ub)+len(nb)],visible_text_ref=h.raw(name_text+'\n'),visible_text_typed_content_sha256=mod._hash(name_text),registrant_name_literal='FAKE REGISTERED FULL COMPANY')
 h.projection.update(sec_cash_statement_profile='SAME_FILE_COMMON_POLICY_MULTI_STATEMENT',selected_original_cash_statement=selected)
 h.current,h.selected=current,selected

_original_refresh=refresh
def refresh(h):
 _original_refresh(h)
 policy=h.source.get('same_source_common_cash_policy_ref')
 if policy:
  more=[h.source['original_two_statement_paragraph_ref'],policy['fragment_ref'],policy['text_projection_ref']]
  h.projection['source_refs'].extend(more);h.entry['fact_ref']=h.write(h.projection)

def test_after_payment_filed_report_selects_one_original_quarter_and_common_unit(h):
 multi_statement(h);r=bind(h);e=r['events']['entitlement_events'][0];b=r['receipt']['proofs'][0]['sec_frozen_cash_binding']
 assert e.cash_per_old_share==2. and e.pay_date=='2023-02-01' and e.available_at is None
 assert b['actual_SEC_filed_date']=='2023-03-16' and b['private_board_declaration_date']=='2023-01-06'
 assert b['selected_original_cash_statement']==h.selected and h.current in h.files[h.source['original_two_statement_paragraph_ref']['path']].read_text()
 assert b['sec_legal_name_literal']=='FAKE Issuer' and h.name['registrant_name_literal']=='FAKE REGISTERED FULL COMPANY'
 assert r['receipt']['proofs'][0]['ex_status']=='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY'

@pytest.mark.parametrize('case',['select_other_quarter','invent_selected','not_common_policy','policy_bytes','duplicate_statement','plain_text_digest','wrong_profile','unknown_name_and_header'])
def test_multi_quarter_unit_and_statement_cannot_be_substituted(h,case):
 multi_statement(h)
 if case=='select_other_quarter':h.projection['selected_original_cash_statement']=h.current
 elif case=='invent_selected':h.projection['selected_original_cash_statement']=h.selected.replace('2.00','1.75')
 elif case=='not_common_policy':h.source['same_source_common_cash_policy_ref']['paragraph_typed_content_sha256']='0'*64
 elif case=='policy_bytes':h.files[h.source['same_source_common_cash_policy_ref']['fragment_ref']['path']].write_text('guessed common')
 elif case=='duplicate_statement':
  p=h.source['original_two_statement_paragraph_ref'];h.files[p['path']].write_text('<p>'+h.selected+' '+h.selected+'</p>')
 elif case=='plain_text_digest':h.source['dividend_paragraph_typed_content_sha256']=hashlib.sha256(h.current.encode()).hexdigest()
 elif case=='wrong_profile':h.projection['sec_cash_statement_profile']='PER_SHARE_ALWAYS_COMMON'
 elif case=='unknown_name_and_header':h.projection['identity_binding']['issuer']='DIFFERENT';h.entry['identity_binding']['issuer']='DIFFERENT'
 with pytest.raises(ValueError):bind(h)

@pytest.mark.parametrize('authority',['strict_PIT','production_qualified','quote_qualified','certified_NAV'])
def test_sec_scope_integer_zero_cannot_replace_false(h,authority):
 h.bundle['sec_same_file_cash_fact_scope'][authority]=0
 with pytest.raises(ValueError,match='CA_EXACT_PINNED_SEC_CASH_FACT_SCOPE_REQUIRED'):bind(h)

def test_full_receivable_payment_flow_reuses_frozen_real_owner(h):
 r=bind(h);e=r['events']['entitlement_events'][0]
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,_=ordinary_cash_lifecycle(h.owner,r['events'],r['ordinary_cash_event_fingerprints'],clone=clone)
 def step(day,positions,cashvalue,state=None):
  return fn((e,),positions,cashvalue,execution_date=day,session_open_at=cash._clock(pd.Timestamp(day),9,30),security_tickers=r['events']['entitlement_security_tickers'],quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,research_account_authority=r['events']['research_account_authority'])
 ex=step(e.ex_date,{e.old_security_id:3.},100.)
 assert ex.cash==100. and ex.receivable_value_usd==6. and ex.positions=={e.old_security_id:3.}
 pay=step('2023-02-01',{},ex.cash,ex.state)
 assert pay.cash==100. and pay.receivable_value_usd==6.
 spendable=step('2023-02-02',{},pay.cash,pay.state)
 assert spendable.cash==106. and spendable.receivable_value_usd==0.
 assert r['receipt']['decision_quality_modified'] is False and r['receipt']['broker_payment_proven'] is False

# The report route uses a real synthetic PDF and the existing installed
# extractor. No issuer report, price, risk matrix or account output is loaded.
import io
_REPORT_PACKAGE='C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages/pypdf'

def report_cash(h,profile='MONTH_DECLARATION_STATEMENT',*,cover_change=None,page_change=None):
 from scripts.storage.refresh_sec_event_originals import load_pdf_package
 reader,extractor=load_pdf_package(_REPORT_PACKAGE)
 from pypdf import PdfWriter
 from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
 issuer='FAKE Issuer'
 cover='UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM 10-K For the fiscal year ended December 31, 2022 '+issuer+' (Exact name of registrant as specified in its charter) Texas (State or other jurisdiction of incorporation or organization) Common stock, $0.01 par value Trading Symbol AAA Name of exchange on which registered New York Stock Exchange'
 listing='Our common stock trades on the New York Stock Exchange under the symbol AAA.'
 context='The following table provides details of dividend payments, excluding dividend equivalent rights, in 2022 and 2023, under our Board approved quarterly cash dividend policy:'
 headers='Record Date Payment Date Amount per Share Total Amount (in millions)'
 statement='In December 2022, the Board declared a cash dividend of $2.00 per share payable on February 1, 2023 to stockholders of record on January 20, 2023'
 row='1/20/2023 2/1/2023 $2.00'
 lines=['PART II','ITEM 5. MARKET FOR THE REGISTRANT'+chr(39)+'S COMMON EQUITY, RELATED STOCKHOLDER MATTERS','Market Information',listing,'Dividends',context,headers,'2023 payments',row+' $100',statement+'.']
 if cover_change:cover=cover_change(cover)
 if page_change:lines=page_change(lines)
 writer=PdfWriter()
 for rows in ([cover],lines):
  page=writer.add_blank_page(width=612,height=792)
  font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
  page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
  commands=['BT /F1 8 Tf 12 TL 30 760 Td']
  for line in rows:
   # Synthetic PDF text is ASCII and uses only declared body text.
   literal=line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
   commands.append('('+literal+') Tj T*')
  commands.append('ET');content=DecodedStreamObject();content.set_data(('\n'.join(commands)).encode())
  page[NameObject('/Contents')]=writer._add_object(content)
 buffer=io.BytesIO();writer.write(buffer);raw=buffer.getvalue();pdf=h.raw(raw)
 actual=reader(io.BytesIO(raw));ct=actual.pages[0].extract_text();pt=actual.pages[1].extract_text()
 norm=lambda value:' '.join(value.split())
 digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
 h.report_transport=dict(schema='HISTORICAL_MIRROR_ISSUER_REPORT_ORIGINAL_PDF_TRANSPORT_V1',actual_status=200,original_HTTP_ref=pdf,original_HTTP_sha256=pdf['sha256'],source_url='https://mirror.example/FAKE_2022.pdf',source_publication_date=None,source_role='THIRD_PARTY_PUBLIC_MIRROR_OF_ISSUER_REPORT_NOT_ISSUER_HOSTED_HTTP',historical_availability_authority='UNKNOWN',request_end_utc='2026-10-10T03:00:00Z',strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 selected=dict(original_key={k:h.vendor[k] for k in ('ticker','effective_date','reason','source_fingerprint')},selected_cash_profile=profile,selected_cash_literal=row if profile=='TABLE_ROW' else statement,source_cash_amount_literal='2.00',source_record_date='2023-01-20',source_pay_date='2023-02-01',source_publication_date=None,cash_available_at=None,private_board_day=None)
 selected['selected_cash_literal_typed_content_sha256']=digest(selected['selected_cash_literal'])
 if profile=='MONTH_DECLARATION_STATEMENT':
  selected.update(source_declaration_month_literal='December 2022',source_declaration_month_interval=['2022-12-01','2022-12-31'])
 h.report_full_cover=h.raw(ct+'\n')
 h.report_source=dict(schema='HISTORICAL_ORIGINAL_ISSUER_REPORT_SAME_FILE_COMMON_CASH_CUSTODY_V1',ticker='AAA',source_publication_date=None,cash_available_at=None,source_direct_ex_date=None,historical_availability_authority='UNKNOWN',source_role='THIRD_PARTY_MIRROR_OF_ORIGINAL_ISSUER_REPORT_SAME_FILE_COMMON_CASH',pdf_extract_text_layout_mode='plain_default',extractor_api='PdfReader.pages[page_zero_based].extract_text()',original_report_ref=pdf,source_url=h.report_transport['source_url'],pdf_extractor=extractor,page_zero_based=1,cover_page_zero_based=0,page_text_ref=h.raw(pt),original_page_text_typed_content_sha256=digest(pt),cover_identity_literal=norm(ct),cover_identity_fragment_ref=h.raw(norm(ct)),cover_identity_literal_typed_content_sha256=digest(norm(ct)),source_issuer_literal=issuer,source_report_fiscal_year_ended='2022-12-31',source_currency_literal='$',source_common_class_literal='Common stock, $0.01 par value',source_symbol_literal='AAA',source_listing_literal='New York Stock Exchange',same_report_common_listing_literal=listing,cash_table_context_literal=context,cash_table_headers_literal=headers,cash_sources=[selected],strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 facts=h.projection['source_projection'];facts.update(publication_calendar_date=None)
 h.entry['identity_binding']=h.identity('AAA')
 h.projection.update(schema='B_FROZEN_HISTORY_REPORT_CASH_TABLE_SOURCE_PROJECTION_V1',cash_evidence_role=mod.REPORT_CASH_ROLE,source_scope=mod.REPORT_CASH_SOURCE_SCOPE,identity_binding=copy.deepcopy(h.entry['identity_binding']))
 h.bundle.pop('sec_same_file_cash_fact_scope',None);h.bundle['report_same_file_cash_table_scope']=copy.deepcopy(mod.REPORT_CASH_SCOPE)

_sec_refresh=refresh
def refresh(h):
 if not hasattr(h,'report_source'):
  return _sec_refresh(h)
 transport=h.write(h.report_transport);h.report_source['source_transport_ref']=transport;custody=h.write(h.report_source)
 refs=[transport,custody,h.report_source['original_report_ref'],h.report_source['page_text_ref'],h.report_source['cover_identity_fragment_ref'],h.report_full_cover]
 if hasattr(h,'report_identity'):
  identity_ref=h.write(h.report_identity)
  h.entry['frozen_account_identity_ref']=identity_ref
  h.entry['identity_binding'].update(source_reference=identity_ref['path'],source_fingerprint=identity_ref['sha256'],available_at=None)
  h.projection.update(frozen_account_identity_ref=identity_ref,identity_binding=copy.deepcopy(h.entry['identity_binding']))
  refs.extend([identity_ref,*[h.report_identity[k] for k in ('original_uid_intervals_ref','original_frozen_input_manifest_ref','content_hash_owner_ref','original_held_guard_owner_ref')]])
 h.projection.update(report_cash_source_custody_ref=custody,complete_cover_page_ref=h.report_full_cover,source_refs=refs)
 h.bundle['source_refs']=refs;h.entry['fact_ref']=h.write(h.projection)

@pytest.mark.parametrize('profile',['TABLE_ROW','MONTH_DECLARATION_STATEMENT'])
def test_report_common_chapter_cash_facts_keep_unknown_clocks_and_old_cash_lifecycle(h,profile):
 report_cash(h,profile);before=copy.deepcopy(h.original);r=bind(h);e=r['events']['entitlement_events'][0]
 b=r['receipt']['proofs'][0]['report_frozen_cash_binding']
 assert type(e) is ca.ResearchReconstructedCashEvent and e.available_at is None and e.cash_per_old_share==2.
 assert b['publication_calendar_date'] is None and b['private_board_declaration_date'] is None and b['available_at'] is None
 assert b['historical_availability_authority']==b['actual_exchange_ex_authority']==b['exchange_notice_authority']=='UNKNOWN'
 assert b['selected_cash_profile']==profile and b['currency_basis']=='INFERRED_USD_US_REPORT_NYSE_COMMON_DOLLAR_CONTEXT'
 assert h.original==before and r['events']['unsupported_events']==(h.raw_flag,)
 if profile=='MONTH_DECLARATION_STATEMENT':
  assert b['declaration_month_interval']==dict(start_inclusive='2022-12-01',end_exclusive='2023-01-01',source_literal='December 2022',precision='MONTH_ONLY_NOT_A_DAY_OR_PUBLICATION')
 else:assert b['declaration_month_interval'] is None
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,clock=ordinary_cash_lifecycle(h.owner,r['events'],r['ordinary_cash_event_fingerprints'],clone=clone)
 def step(day,positions,value,state=None):
  return fn((e,),positions,value,execution_date=day,session_open_at=cash._clock(pd.Timestamp(day),9,30),security_tickers=r['events']['entitlement_security_tickers'],quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,research_account_authority=r['events']['research_account_authority'])
 ex=step(e.ex_date,{e.old_security_id:3.},100.);pay=step('2023-02-01',{},ex.cash,ex.state);spendable=step('2023-02-02',{},pay.cash,pay.state)
 assert ex.cash==pay.cash==100. and ex.receivable_value_usd==pay.receivable_value_usd==6.
 assert spendable.cash==106. and spendable.receivable_value_usd==0. and ex.positions=={e.old_security_id:3.}
 assert clock['events'][0]['research_cash_not_before_date']=='2023-02-02'
 assert r['receipt']['proofs'][0]['historical_ex_adjudication']['ex_date_provenance_role']=='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY'

@pytest.mark.parametrize('case',['foreign_charter','preferred','no_common_context','rights_included','duplicate_statement','wrong_amount','other_quarter','prose_is_not_table','month_in_ex','invent_board_day','invent_publication','mirror_claims_issuer','wrong_pdf_pin','extractor_changed','raw_page_changed','missing_scope','identity_unavailable','MKFG'])
def test_report_cannot_grant_currency_class_clock_or_new_identity_authority(h,case):
 if case=='foreign_charter':report_cash(h,cover_change=lambda s:s.replace('Texas','Ontario'))
 elif case=='preferred':report_cash(h,cover_change=lambda s:s.replace('Common stock','Preferred stock'))
 elif case=='no_common_context':report_cash(h,page_change=lambda lines:[v.replace('common stock trades','preferred stock trades') for v in lines])
 elif case=='rights_included':report_cash(h,page_change=lambda lines:[v.replace('excluding dividend equivalent rights','including dividend equivalent rights') for v in lines])
 elif case=='duplicate_statement':report_cash(h,page_change=lambda lines:lines+[lines[-1]])
 else:report_cash(h)
 row=h.report_source['cash_sources'][0]
 if case=='wrong_amount':h.projection['source_projection']['cash_per_raw_share']=3.
 elif case=='other_quarter':row['source_record_date']='2023-04-03'
 elif case=='prose_is_not_table':row['selected_cash_profile']='TABLE_ROW'
 elif case=='month_in_ex':
  row.update(source_declaration_month_literal='January 2023',source_declaration_month_interval=['2023-01-01','2023-01-31'])
 elif case=='invent_board_day':row['private_board_day']='2022-12-15'
 elif case=='invent_publication':h.projection['source_projection']['publication_calendar_date']='2022-12-01'
 elif case=='mirror_claims_issuer':h.report_transport['source_role']='ISSUER_HOSTED_HTTP'
 elif case=='wrong_pdf_pin':h.report_transport['original_HTTP_sha256']='0'*64
 elif case=='extractor_changed':h.report_source['pdf_extractor']['source_tree_sha256']='0'*64
 elif case=='raw_page_changed':h.files[h.report_source['page_text_ref']['path']].write_text('guessed cash terms')
 elif case=='missing_scope':h.bundle.pop('report_same_file_cash_table_scope')
 elif case=='identity_unavailable':h.entry['identity_binding']['available_at']=None;h.projection['identity_binding']=copy.deepcopy(h.entry['identity_binding'])
 elif case=='MKFG':
  h.projection['source_projection']['ticker']='MKFG'
 with pytest.raises(ValueError):bind(h)

def test_report_binding_does_not_relax_old_publication_scope(h):
 report_cash(h);refresh(h);terms=mod._report_frozen_cash_terms(h.projection,h.entry);facts=terms['historical_ex_adjudication_input']
 env=dict(path='D:/FAKE_ONLY/facts.json',sha256='e'*64,payload=facts,guard=dict(status='HASH_VERIFIED_PAYLOAD',path='D:/FAKE_ONLY/facts.json',sha256='e'*64,payload_sha256=cash._hash(facts)))
 r=cash.adjudicate_post_verified_cash_ex(env,calendar=[str(x.date()) for x in h.dates],calendar_binding=h.bundle['historical_calendar_binding'],rule_sources=h.bundle['historical_rule_sources'],scope_end_exclusive='2026-01-01',source_scope='FROZEN_PRE2026_NYSE_COMMON_USD')
 assert r['status']=='BLOCKED_SOURCE' and r['reason']=='ADVANCE_PUBLICATION_OR_FIXED_PAY_UNBOUND'

def report_frozen_identity(h):
 from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
 row=dict(ticker='AAA',effective_start=pd.Timestamp('2022-11-21'),effective_end=pd.Timestamp('2023-02-21'),security_id='123456789',security_id_type='CUSIP',cusip='123456789',issuer_name='FAKE   Issuer',title_of_class='COM',moomoo_transport_code='US.AAA',mapping_status='RESOLVED',mapping_source='SYNTHETIC_ORIGINAL',source_filing='0000000001-22-000001')
 stream=io.BytesIO();pd.DataFrame([row]).to_parquet(stream,index=False);interval=h.raw(stream.getvalue())
 manifest=h.write(dict(sources=dict(uid_intervals=dict(interval,rows=1,bytes=len(stream.getvalue())))))
 encoded=copy.deepcopy(row)
 for field in ('effective_start','effective_end'):encoded[field]=str(row[field].date())
 h.report_identity=dict(schema_version='B_EXISTING_FROZEN_RAW_COMMON_IDENTITY_REUSE_V1',status='EXACT_ORIGINAL_FROZEN_IDENTITY_ROWS_REUSED_NOT_NEW_SECURITY_MASTER',ticker='AAA',original_uid_intervals_ref=interval,original_frozen_input_manifest_ref=manifest,source_identity_columns=list(row),row_count=1,rows=[dict(original_source_row=encoded,original_source_row_content_sha256=content_hash(row))],content_hash_owner_ref=h.raw('synthetic existing hash-owner custody'),original_held_guard_owner_ref=h.raw('synthetic existing held-owner custody'),original_date_type='pandas.Timestamp',encoded_date_representation='YYYY-MM-DD_RECONSTRUCT_PANDAS_TIMESTAMP_BEFORE_ORIGINAL_TYPED_HASH',available_at=None,historical_publication_authority='UNKNOWN',interval_semantics='ORIGINAL_FROZEN_RESEARCH_EFFECTIVE_INTERVAL_NOT_PUBLICATION_TIMESTAMP',interval_extension=False,new_security_master=False,ticker_alias=False,share_quantity_effect=False,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)

def test_report_existing_frozen_common_identity_is_not_a_new_publication_clock(h):
 report_cash(h);report_frozen_identity(h);before=copy.deepcopy(h.original)
 r=bind(h);e=r['events']['entitlement_events'][0];p=r['receipt']['proofs'][0]['identity']
 assert e.old_security_id==h.entry['identity_binding']['security_id'] and e.available_at is None
 assert p['available_at'] is None and p['CUSIP_claim'] is False and p['legal_identity_authority_granted'] is False
 assert p['identity_clock_role']=='ORIGINAL_FROZEN_EFFECTIVE_INTERVAL_NOT_PUBLICATION'
 assert p['original_source_row']['cusip']=='123456789' and p['original_source_row']['issuer_name']=='FAKE   Issuer'
 assert p['original_date_type']=='pandas.Timestamp' and h.original==before
 assert p['historical_availability_qualified'] is False and r['receipt']['decision_quality_modified'] is False
 assert ca._validate_research_account_authority((e,),r['events']['research_account_authority'])['strict_PIT_promotion_eligible'] is False

@pytest.mark.parametrize('case',['row_hash','raw_row_substitution','outside_prior','overlap','preferred_original','publication_alias','manifest_ref'])
def test_report_identity_transport_requires_exact_existing_raw_row_and_interval(h,case):
 report_cash(h);report_frozen_identity(h)
 from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
 item=h.report_identity['rows'][0];row=item['original_source_row']
 if case=='row_hash':item['original_source_row_content_sha256']='0'*64
 elif case=='raw_row_substitution':row['source_filing']='0000000001-22-999999'
 elif case=='outside_prior':row['effective_start']='2023-01-19'
 elif case=='overlap':h.report_identity['rows'].append(copy.deepcopy(item));h.report_identity['row_count']=2
 elif case=='preferred_original':row['title_of_class']='PREF'
 elif case=='publication_alias':h.report_identity['available_at']='2022-12-01T00:00:00Z'
 elif case=='manifest_ref':h.report_identity['original_frozen_input_manifest_ref']=h.write(dict(sources=dict(uid_intervals=dict(path='D:/FAKE_ONLY/other',sha256='0'*64))))
 if case in ('raw_row_substitution','outside_prior','preferred_original'):
  reconstructed=copy.deepcopy(row)
  for field in ('effective_start','effective_end'):reconstructed[field]=pd.Timestamp(row[field])
  item['original_source_row_content_sha256']=content_hash(reconstructed)
 with pytest.raises(ValueError):bind(h)


@pytest.mark.parametrize('profile',['TABLE_ROW','MONTH_DECLARATION_STATEMENT'])
@pytest.mark.parametrize('save_final_lf',[False,True])
def test_report_saved_page_final_lf_preserves_extraction_identity_and_cash_clock(h,profile,save_final_lf):
 report_cash(h,profile)
 original_ref=h.report_source['page_text_ref']
 original_bytes=h.files[original_ref['path']].read_bytes()
 typed_hash=h.report_source['original_page_text_typed_content_sha256']
 saved=original_bytes+(b'\n' if save_final_lf else b'')
 h.report_source['page_text_ref']=h.raw(saved)
 result=bind(h)
 proof=result['receipt']['proofs'][0]
 event=result['events']['entitlement_events'][0]
 assert h.report_source['original_page_text_typed_content_sha256']==typed_hash
 assert proof['report_frozen_cash_binding']['source_cash_page_ref']==h.report_source['page_text_ref']
 assert event.available_at is None and event.cash_per_old_share==2. and event.record_date=='2023-01-20' and event.pay_date=='2023-02-01'
 assert proof['report_frozen_cash_binding']['private_board_declaration_date'] is None

@pytest.mark.parametrize('change',['two_added_lfs','trailing_space','content_changed','typed_hash_including_saved_lf'])
def test_report_saved_page_final_lf_never_normalizes_content_or_typed_hash(h,change):
 report_cash(h)
 original=h.files[h.report_source['page_text_ref']['path']].read_bytes()
 if change=='two_added_lfs':saved=original+b'\n\n'
 elif change=='trailing_space':saved=original+b' '
 elif change=='content_changed':saved=original.replace(b'Market Information',b'Changed Information')
 else:
  saved=original+b'\n'
  text=saved.decode('utf-8')
  h.report_source['original_page_text_typed_content_sha256']=hashlib.sha256(json.dumps(text,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
 h.report_source['page_text_ref']=h.raw(saved)
 with pytest.raises(ValueError,match='CA_REPORT_CASH_ORIGINAL_PAGE_PROJECTION_CHANGED'):
  bind(h)


# R6 keeps original PDF text/literals intact; only derived whitespace keys
# and a physically checked, explicitly opted-in pre-T+1 NYSE rule are new.
def r6_kerning_report(h,profile):
 changes=lambda value:value.replace('Our common stock','Ourc ommons tock').replace('Record Date Payment','Re cord Date Payment').replace('cash dividend of','cash div idend of')
 report_cash(h,profile,cover_change=lambda value:value.replace('Common stock','Commo n stock').replace('New York','New Yo rk'),page_change=lambda rows:[changes(v) for v in rows])
 h.report_source['source_common_class_literal']='Commo n stock, $0.01 par value'
 h.report_source['source_listing_literal']='New Yo rk Stock Exchange'
 h.report_source['same_report_common_listing_literal']=changes(h.report_source['same_report_common_listing_literal'])
 h.report_source['cash_table_headers_literal']=changes(h.report_source['cash_table_headers_literal'])
 row=h.report_source['cash_sources'][0]
 row['selected_cash_literal']=changes(row['selected_cash_literal'])
 row['selected_cash_literal_typed_content_sha256']=hashlib.sha256(json.dumps(row['selected_cash_literal'],sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()

@pytest.mark.parametrize('profile',['TABLE_ROW','MONTH_DECLARATION_STATEMENT'])
def test_r6_report_kerning_keys_keep_raw_literals_hashes_and_unknown_clock(h,profile):
 r6_kerning_report(h,profile)
 original=copy.deepcopy(h.report_source);raw_key=h.report_source['page_text_ref'];raw=h.files[raw_key['path']].read_bytes()
 result=bind(h);proof=result['receipt']['proofs'][0]
 assert h.report_source['cash_sources']==original['cash_sources'] and h.files[raw_key['path']].read_bytes()==raw
 assert h.report_source['original_page_text_typed_content_sha256']==original['original_page_text_typed_content_sha256']
 assert proof['report_frozen_cash_binding']['whitespace_semantic_role']=='WHITESPACE_ONLY_DERIVED_KEYS_RAW_LITERALS_AND_PAGE_HASH_UNCHANGED'
 event=result['events']['entitlement_events'][0]
 assert event.available_at is None and event.cash_per_old_share==2. and event.pay_date=='2023-02-01'

@pytest.mark.parametrize('change',['common_letter','listing_letter','header_letter','statement_letter','two_lfs','CRLF'])
def test_r6_whitespace_keys_cannot_change_characters_or_saved_projection(h,change):
 r6_kerning_report(h,'MONTH_DECLARATION_STATEMENT')
 if change=='common_letter':h.report_source['source_common_class_literal']='Commo m stock, $0.01 par value'
 elif change=='listing_letter':h.report_source['source_listing_literal']='New Yo rk Stock Exchonge'
 elif change=='header_letter':h.report_source['cash_table_headers_literal']=h.report_source['cash_table_headers_literal'].replace('Amount','A mountX')
 elif change=='statement_letter':
  r=h.report_source['cash_sources'][0];r['selected_cash_literal']=r['selected_cash_literal'].replace('stockholders','bondholders')
  r['selected_cash_literal_typed_content_sha256']=hashlib.sha256(json.dumps(r['selected_cash_literal'],sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
 else:
  original=h.files[h.report_source['page_text_ref']['path']].read_bytes()
  h.report_source['page_text_ref']=h.raw(original+b'\n\n' if change=='two_lfs' else original.replace(b'\n',b'\r\n'))
 with pytest.raises(ValueError):bind(h)

def r6_nyse_rule(h):
 from scripts.storage.refresh_sec_event_originals import load_pdf_package
 reader_type,extractor=load_pdf_package(_REPORT_PACKAGE)
 from pypdf import PdfWriter
 from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
 rule4='Current Rule 235 provides that transactions in stocks shall be ex-dividend. The current rule further provides that if the record date or closing of transfer books occurs upon a day other than a business day, Rule 235 shall apply for the second preceding business day.'
 rule24='Holidays thus affecting the ex-dividend dates are: Good Friday (variable date between Mar. 20 and April 23, both inclusive)'
 writer=PdfWriter()
 for index in range(24):
  page=writer.add_blank_page(width=2000,height=792)
  if index not in (3,23):continue
  font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
  page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
  literal=(rule4 if index==3 else rule24).replace('(','\\(').replace(')','\\)')
  content=DecodedStreamObject();content.set_data(('BT /F1 8 Tf 30 760 Td ('+literal+') Tj ET').encode())
  page[NameObject('/Contents')]=writer._add_object(content)
 buffer=io.BytesIO();writer.write(buffer);pdf=h.raw(buffer.getvalue());pdf['bytes']=len(buffer.getvalue())
 rd=reader_type(io.BytesIO(buffer.getvalue()));pages=[]
 for index in (3,23):
  value=rd.pages[index].extract_text()
  pages.append(dict(page_zero_based=index,text=value,text_ref=h.raw(value+'\n'),original_extract_text_sha256=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()))
 h.nyse_transport=dict(actual_status=200,request_url='https://www.nyse.com/publicdocs/nyse/markets/nyse/rule-filings/filings/2024/SR-NYSE-2024-19.pdf',source_role='NYSE_OFFICIAL_PRE2026_RULE_FILING',original_HTTP_ref=pdf,strict_PIT=False)
 h.nyse_source=dict(schema='OFFICIAL_PRE2026_NYSE_RULE235_NECESSARY_PAGE_SOURCE_FACTS_V1',source_document_year=2024,scope='NYSE_RULE235_CURRENT_PRE_TPLUS1_PROSE_AND_GOOD_FRIDAY_HOLIDAY_CLAUSE',strict_PIT=False,algorithm_changed=False,exchange_notice_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',extractor=extractor,original_ref=pdf,original_page_count=24,selected_pages=pages)
 cb=copy.deepcopy(h.bundle['historical_calendar_binding'])
 cal=h.raw(json.dumps([str(d.date()) for d in h.dates]));cb.update(source_reference=cal['path'],source_fingerprint=cal['sha256'])
 h.nyse_calendar_ref=cal;h.bundle['historical_calendar_binding']=cb

_r6_refresh=refresh
def refresh(h):
 _r6_refresh(h)
 if not hasattr(h,'nyse_source'):return
 transport=h.write(h.nyse_transport);h.nyse_source['transport_ref']=transport;source=h.write(h.nyse_source)
 refs=[*h.projection['source_refs'],source,transport,h.nyse_source['original_ref'],*[p['text_ref'] for p in h.nyse_source['selected_pages']],h.nyse_calendar_ref]
 h.projection.update(report_nyse_pre_t1_nonbusiness_rule_ref=source,source_refs=refs)
 h.bundle.update(report_nyse_pre_t1_nonbusiness_record_scope=dict(mod.REPORT_NYSE_PRE_T1_NONBUSINESS_SCOPE,rule_source_ref=source),source_refs=refs)
 h.entry['fact_ref']=h.write(h.projection)

def r6_nonbusiness_report(h):
 report_cash(h,'TABLE_ROW',page_change=lambda rows:[v.replace('1/20/2023','1/21/2023') for v in rows])
 row=h.report_source['cash_sources'][0];row.update(source_record_date='2023-01-21',selected_cash_literal='1/21/2023 2/1/2023 $2.00')
 row['selected_cash_literal_typed_content_sha256']=hashlib.sha256(json.dumps(row['selected_cash_literal'],sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
 h.projection['source_projection']['record_date']='2023-01-21'
 r6_nyse_rule(h)

def test_r6_report_nyse_nonbusiness_optin_uses_second_prior_without_calendar_repair(h):
 r6_nonbusiness_report(h);before=tuple(h.dates);old=copy.deepcopy(h.original)
 result=bind(h);event=result['events']['entitlement_events'][0];proof=result['receipt']['proofs'][0]
 assert event.ex_date=='2023-01-19' and event.record_date=='2023-01-21'
 assert event.available_at is None and h.dates==before and h.original==old and pd.Timestamp('2023-01-21') not in h.dates
 assert proof['historical_ex_adjudication']['nyse_nonbusiness_record_binding']['policy_id']==cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH
 assert proof['historical_ex_adjudication']['actual_exchange_ex_authority']=='UNKNOWN'

@pytest.mark.parametrize('policy',['FROZEN_PRE2026_LEGACY','NYSE_T1_TRANSITION_2024'])
def test_r6_existing_normal_policies_still_reject_nonbusiness_record(h,policy):
 r6_nonbusiness_report(h)
 with pytest.raises(ValueError,match='RECORD_NOT_IN_FROZEN_LEGAL_CALENDAR'):
  cash.normal_cash_ex_date('2023-01-21',h.dates,scope_end_exclusive='2026-01-01',policy=policy)

@pytest.mark.parametrize('change',['receipt_only','typed_hash','page_commit','page_index','official_role','calendar_sha','missing_calendar_pin','scope_authority'])
def test_r6_nyse_rule_requires_actual_pdf_pages_calendar_and_explicit_scope(h,change):
 r6_nonbusiness_report(h)
 if change=='receipt_only':h.nyse_source['selected_pages'][0]['text']='Current Rule 235 second preceding business day'
 elif change=='typed_hash':h.nyse_source['selected_pages'][0]['original_extract_text_sha256']='0'*64
 elif change=='page_commit':
  p=h.nyse_source['selected_pages'][0];p['text_ref']=h.raw(p['text']+' changed')
 elif change=='page_index':h.nyse_source['selected_pages'][0]['page_zero_based']=2
 elif change=='official_role':h.nyse_transport['source_role']='MIRROR'
 elif change=='calendar_sha':h.bundle['historical_calendar_binding']['session_dates_sha256']='0'*64
 elif change=='missing_calendar_pin':
  refresh(h)
  for payload in (h.projection,h.bundle):payload['source_refs']=[r for r in payload['source_refs'] if r!=h.nyse_calendar_ref]
  h.entry['fact_ref']=h.write(h.projection)
  with pytest.raises(ValueError,match='CA_REPORT_CASH_NESTED_SOURCE_PIN_REQUIRED'):
   mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))
  return
 else:
  refresh(h);h.bundle['report_nyse_pre_t1_nonbusiness_record_scope']['strict_PIT']=True
  with pytest.raises(ValueError):mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))
  return
 with pytest.raises(ValueError):bind(h)

def test_r6_nyse_pre_t1_rule_cannot_admit_post_t1_nonbusiness_record(h):
 r6_nonbusiness_report(h);result=bind(h)
 binding=copy.deepcopy(result['receipt']['proofs'][0]['historical_ex_adjudication']['nyse_nonbusiness_record_binding'])
 date=pd.Timestamp('2024-06-19');days=tuple(d for d in h.dates if d!=date)
 binding.update(record_date=str(date.date()));binding['calendar_binding']['session_dates_sha256']=cash._hash([str(d.date()) for d in days])
 with pytest.raises(ValueError,match='NYSE_NONBUSINESS_POST_T1_EFFECTIVE_SOURCE_UNBOUND'):
  cash.normal_cash_ex_date(date,days,scope_end_exclusive='2026-01-01',policy=cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,nyse_nonbusiness_record_binding=binding)

@pytest.mark.parametrize('record',['2023-01-20','2024-05-29'])
def test_r9_pre_t1_binding_applies_cutoff_to_business_record(h,record):
 r6_nonbusiness_report(h);result=bind(h)
 binding=copy.deepcopy(result['receipt']['proofs'][0]['historical_ex_adjudication']['nyse_nonbusiness_record_binding'])
 assert pd.Timestamp(record) in h.dates
 binding.update(record_date=record)
 if record=='2024-05-29':
  with pytest.raises(ValueError,match='NYSE_NONBUSINESS_POST_T1_EFFECTIVE_SOURCE_UNBOUND'):
   cash.normal_cash_ex_date(record,h.dates,scope_end_exclusive='2026-01-01',policy=cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,nyse_nonbusiness_record_binding=binding)
 else:
  actual=cash.normal_cash_ex_date(record,h.dates,scope_end_exclusive='2026-01-01',policy=cash.NYSE_RULE235_PRE_T1_NONBUSINESS_RESEARCH,nyse_nonbusiness_record_binding=binding)
  expected=cash.normal_cash_ex_date(record,h.dates,scope_end_exclusive='2026-01-01')
  assert actual==expected

# Actual streamed report descriptor: source metadata remains unchanged;
# absent transport qualification flags and capture clocks are not invented.
def r11_captured_report(h,profile):
 r6_kerning_report(h,profile)
 s=h.report_source;t=h.report_transport
 raw=h.files[s['original_report_ref']['path']].read_bytes()
 h.report_transport=dict(schema='HISTORICAL_SOURCE_HTTP_TRANSPORT_V1',status_code=200,
  original_HTTP_ref=s['original_report_ref'],actual_captured_body_sha256=s['original_report_ref']['sha256'],
  actual_captured_byte_count=len(raw),capture_complete=True,url=s['source_url'],
  original_publication_date=None,historical_availability_authority='UNKNOWN',
  source_role='THIRD_PARTY_PUBLIC_MIRROR_OF_ORIGINAL_ISSUER_REPORT_NOT_ISSUER_HTTP',
  current_capture_utc=t['request_end_utc'],scope='EXACT2022_ORIGINAL_REPORT_COVER_AND_ITEM5_CASH_ONLY')
 s.update(schema='HUM_ORIGINAL_REPORT_SAME_FILE_COMMON_CASH_CUSTODY_V1',
  source_role='THIRD_PARTY_PUBLIC_MIRROR_OF_ORIGINAL_ISSUER_REPORT',pdf_extract_text_layout_mode=False,
  extractor_api='pypdf.PdfReader.pages[zero_based].extract_text()',
  page_saved_bytes_recipe='UTF8_EXACT_PYPDF_TEXT_PLUS_ONE_TERMINAL_LF',
  projection_normalization_recipe='NONE_RAW_PYPDF_TEXT_PRESERVED_KERNING_SPLITS_DECLARED',
  source_publication_authority='UNKNOWN_NOT_REPORT_METADATA_CREATION_MIRROR_MTIME_OR_URL_YEAR')
 if profile=='MONTH_DECLARATION_STATEMENT':
  row=s['cash_sources'][0]
  row.pop('source_declaration_month_literal');row.pop('source_declaration_month_interval')
  row['declaration_month_interval']=dict(start='2022-12-01',end='2022-12-31',role='SOURCE_DECLARATION_MONTH_ONLY_NOT_PUBLICATION_OR_EXACT_BOARD_DAY')

@pytest.mark.parametrize('profile',['TABLE_ROW','MONTH_DECLARATION_STATEMENT'])
def test_r11_actual_captured_descriptor_keeps_true_clock_raw_literals_and_absent_transport_flags(h,profile):
 r11_captured_report(h,profile);before=copy.deepcopy(h.report_transport)
 # An unrelated request-end value must not override the actual source clock.
 h.report_transport['request_end_utc']='1900-01-01T00:00:00Z';before=copy.deepcopy(h.report_transport)
 original=copy.deepcopy(h.report_source)
 result=bind(h);binding=result['receipt']['proofs'][0]['report_frozen_cash_binding']
 assert binding['source_descriptor_profile']=='ACTUAL_MIRROR_CAPTURED_REPORT_DESCRIPTOR_V1'
 assert binding['current_capture_utc']==str(pd.Timestamp(before['current_capture_utc']))
 assert binding['current_capture_clock_role']=='ACTUAL_CURRENT_CAPTURE_UTC_NOT_HTTP_END_OR_PUBLICATION'
 assert binding['source_transport_flags_role']=='ORIGINAL_TRANSPORT_UNDECLARED_NOT_INVENTED_SOURCE_FLAGS'
 assert all(binding[k] is False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
 assert h.report_transport==before and not any(k in before for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
 assert h.report_source['cash_sources']==original['cash_sources']
 assert binding['transport_role']==original['source_role']
 assert result['events']['entitlement_events'][0].available_at is None

@pytest.mark.parametrize('change',['schema','source_role','transport_role','body_sha','body_bytes','capture_missing','capture_unaware','month_interval','month_statement','currency','common','foreign_charter'])
def test_r11_captured_descriptor_cannot_forge_source_transport_month_currency_or_class(h,change):
 r11_captured_report(h,'MONTH_DECLARATION_STATEMENT')
 s=h.report_source;t=h.report_transport
 if change=='schema':s['schema']='OTHER_REPORT'
 elif change=='source_role':s['source_role']='ISSUER_HTTP'
 elif change=='transport_role':t['source_role']='ISSUER_HTTP'
 elif change=='body_sha':t['actual_captured_body_sha256']='0'*64
 elif change=='body_bytes':t['actual_captured_byte_count']+=1
 elif change=='capture_missing':t.pop('current_capture_utc')
 elif change=='capture_unaware':t['current_capture_utc']='2026-10-10'
 elif change=='month_interval':s['cash_sources'][0]['declaration_month_interval']['end']='2023-01-31'
 elif change=='month_statement':
  row=s['cash_sources'][0];row['selected_cash_literal']=row['selected_cash_literal'].replace('December','November')
  row['selected_cash_literal_typed_content_sha256']=hashlib.sha256(json.dumps(row['selected_cash_literal'],sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
 elif change=='currency':s['source_currency_literal']='EUR'
 elif change=='common':s['source_common_class_literal']='Preferred stock, $0.01 par value'
 elif change=='foreign_charter':s['cover_identity_literal']=s['cover_identity_literal'].replace('Texas','Ontario')
 with pytest.raises(ValueError):bind(h)

# The unit bridge reuses report class/policy and original COM rows.
# Notice terms are checked independently; report and notice cash amounts differ.
def r12_notice(h,date_projection='TEXT',*,publication='2023-01-03'):
 r11_captured_report(h,'TABLE_ROW');report_frozen_identity(h)
 from scripts.research.a2.data import joint_cash_bindings as c
 literal='SYNTHETIC CITY, ST--(BUSINESS WIRE)-- FAKE Issuer (NYSE: AAA) announced today that its Board of Directors has declared a cash dividend to stockholders of $3.00 per share payable on February 1, 2023 to stockholders of record as of the close of business on January 20, 2023.'
 pub=pd.Timestamp(publication);date=pub.strftime('%m/%d/%Y')
 header=('<div class="articleDate" data-aue-prop="publishdate" data-aue-type="text">'+date+'</div>').encode()
 paragraph=('<p>'+literal+'</p>').encode();body=header+b'\n'+paragraph;body_ref=h.raw(body)
 h.notice_transport=dict(schema='HISTORICAL_SOURCE_HTTP_TRANSPORT_V1',status_code=200,url='https://issuer.example/ordinary-quarterly-notice',
  original_HTTP_sha256=body_ref['sha256'],response_bytes=len(body),historical_availability_authority='UNKNOWN',current_capture_utc='2026-10-10T03:00:00Z')
 row=dict(raw_byte_range=[len(header)+1,len(body)],raw_fragment_ref=h.raw(paragraph),visible_text_ref=h.raw(literal+'\n'),
  dividend_paragraph=literal,dividend_paragraph_typed_content_sha256=hashlib.sha256(json.dumps(literal,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest(),
  source_cash_amount_literal='3.00',source_record_date='2023-01-20',source_pay_date='2023-02-01',
  cash_explicit_common_literal=False,source_currency_explicit_USD=False,source_currency_literal='$')
 h.notice_source=dict(schema='HUM_ISSUER_ORIGINAL_ORDINARY_CASH_FRAGMENT_CUSTODY_V1',source_role='ISSUER_HOSTED_ORIGINAL_ORDINARY_CASH_DECLARATION',
  source_publication_role='ABSOLUTE_ORIGINAL_ARTICLEDATE_PUBLISHDATE_HEADER_NOT_PRIVATE_BOARD_DAY',source_publication_date=str(pub.date()),
  announcement_date=str(pub.date()),cash_available_at=None,source_direct_ex_date=None,historical_availability_authority='UNKNOWN',
  source_issuer_literal='FAKE Issuer',same_source_issuer_listing_literal='FAKE Issuer (NYSE: AAA)',same_source_US_context_literal='SYNTHETIC CITY, ST',
  source_currency_explicit_USD=False,source_url=h.notice_transport['url'],original_HTTP_ref=body_ref,original_HTTP_sha256=body_ref['sha256'],
  date_projection_raw_byte_range=[0,len(header)],date_projection_ref=h.raw(header if date_projection=='HTML' else date+'\n'),
  original_header_date_literal=date,cash_sources=[row],strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 h.projection['source_projection']['cash_per_raw_share']=3.
 h.projection.update(schema='B_FROZEN_HISTORY_DATED_NOTICE_COMMON_UNIT_BRIDGE_SOURCE_PROJECTION_V1',
  cash_evidence_role=mod.DATED_COMMON_UNIT_ROLE,source_scope=mod.DATED_COMMON_UNIT_SOURCE_SCOPE)

_r12_refresh=refresh
def refresh(h):
 _r12_refresh(h)
 if not hasattr(h,'notice_source'):return
 transport=h.write(h.notice_transport);h.notice_source['HTTP_transport_ref']=transport;custody=h.write(h.notice_source)
 s=h.notice_source;row=s['cash_sources'][0]
 refs=[*h.projection['source_refs'],transport,custody,s['original_HTTP_ref'],s['date_projection_ref'],row['raw_fragment_ref'],row['visible_text_ref']]
 facts=h.projection['source_projection']
 facts.update(publication_calendar_date=s['source_publication_date'],issuer_source_fingerprint=s['original_HTTP_ref']['sha256'],
  identity_source_fingerprint=h.projection['frozen_account_identity_ref']['sha256'],
  exchange_listing_source_reference=h.projection['report_cash_source_custody_ref']['path'],
  exchange_listing_source_fingerprint=h.projection['report_cash_source_custody_ref']['sha256'])
 h.projection.update(dated_cash_source_custody_ref=custody,source_refs=refs)
 h.bundle.update(dated_notice_frozen_common_unit_scope=copy.deepcopy(mod.DATED_COMMON_UNIT_SCOPE),source_refs=refs)
 h.entry['fact_ref']=h.write(h.projection)

@pytest.mark.parametrize('date_projection',['TEXT','HTML'])
def test_r12_generic_notice_uses_three_source_roles_without_matching_amount_or_inventing_clock(h,date_projection):
 r12_notice(h,date_projection);before=copy.deepcopy(h.original);source=copy.deepcopy(h.notice_source)
 result=bind(h);event=result['events']['entitlement_events'][0];p=result['receipt']['proofs'][0];b=p['dated_common_unit_bridge_binding']
 assert event.cash_per_old_share==3. and h.report_source['cash_sources'][0]['source_cash_amount_literal']=='2.00'
 assert event.available_at is None and type(event) is ca.ResearchReconstructedCashEvent and h.original==before
 assert b['notice_publication_date']=='2023-01-03' and b['report_publication_date'] is None and b['private_board_declaration_date'] is None
 assert b['amount_match_is_not_class_evidence'] is True and b['report_currency_or_amount_not_copied_into_notice'] is True
 assert all(b[k] is False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
 assert b['original_generic_per_share_literal']==source['cash_sources'][0]['dividend_paragraph']
 assert p['identity']['available_at'] is None and p['identity']['legal_identity_authority_granted'] is False
 assert p['identity']['original_source_row']['title_of_class']=='COM'
 assert p['historical_ex_adjudication']['status']=='QUALIFIED_RESEARCH_FROZEN_CASH_FACT'
 assert p['historical_ex_adjudication']['actual_exchange_ex_authority']=='UNKNOWN'
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,_=ordinary_cash_lifecycle(h.owner,result['events'],result['ordinary_cash_event_fingerprints'],clone=clone)
 def step(day,positions,value,state=None):
  return fn((event,),positions,value,execution_date=day,session_open_at=cash._clock(pd.Timestamp(day),9,30),security_tickers=result['events']['entitlement_security_tickers'],quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,research_account_authority=result['events']['research_account_authority'])
 ex=step(event.ex_date,{event.old_security_id:3.},100.)
 pay=step('2023-02-01',{},ex.cash,ex.state);spendable=step('2023-02-02',{},pay.cash,pay.state)
 assert ex.cash==pay.cash==100. and ex.receivable_value_usd==pay.receivable_value_usd==9.
 assert ex.positions=={event.old_security_id:3.} and spendable.cash==109. and spendable.receivable_value_usd==0.

@pytest.mark.parametrize('change',['raw_fragment','date_literal','dateline_literal','issuer_listing','notice_schema','report_issuer','report_common','currency','identity_available','identity_preferred','advance_notice','no_explicit_scope','issuer_fingerprint'])
def test_r12_three_source_bridge_rejects_unbound_units_clocks_identity_and_raw_changes(h,change):
 r12_notice(h,publication='2023-01-15' if change=='advance_notice' else '2023-01-03')
 s=h.notice_source;row=s['cash_sources'][0]
 if change=='raw_fragment':row['raw_fragment_ref']=h.raw(b'<p>guessed declaration</p>')
 elif change=='date_literal':s['original_header_date_literal']='01/04/2023'
 elif change=='dateline_literal':s['same_source_US_context_literal']+='.'
 elif change=='issuer_listing':s['same_source_issuer_listing_literal']='FAKE Issuer (NYSE: BBB)'
 elif change=='notice_schema':s['schema']='OTHER_CASH_SOURCE'
 elif change=='report_issuer':h.report_source['source_issuer_literal']='Other Issuer'
 elif change=='report_common':h.report_source['source_common_class_literal']='Preferred stock, $0.01 par value'
 elif change=='currency':s['source_currency_literal']='CAD'
 elif change=='identity_available':h.report_identity['available_at']='2023-01-01T00:00:00Z'
 elif change=='identity_preferred':
  from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
  item=h.report_identity['rows'][0];item['original_source_row']['title_of_class']='PREF'
  reconstructed=copy.deepcopy(item['original_source_row'])
  for field in ('effective_start','effective_end'):reconstructed[field]=pd.Timestamp(reconstructed[field])
  item['original_source_row_content_sha256']=content_hash(reconstructed)
 elif change in ('no_explicit_scope','issuer_fingerprint'):
  refresh(h)
  if change=='no_explicit_scope':h.bundle.pop('dated_notice_frozen_common_unit_scope')
  else:
   h.projection['source_projection']['issuer_source_fingerprint']='0'*64;h.entry['fact_ref']=h.write(h.projection)
  with pytest.raises(ValueError):mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))
  return
 with pytest.raises(ValueError):bind(h)

# R21 retains its original prefix projection and separates HTTP and extraction clocks.
def r15_prefix_notice(h):
 r12_notice(h,'HTML')
 s=h.notice_source;row=s['cash_sources'][0];body=h.files[s['original_HTTP_ref']['path']].read_bytes()
 stop=body.index(b' announced today')
 start=row['raw_byte_range'][0];prefix_raw=body[start:stop]
 prefix=row['dividend_paragraph'].split(' announced today',1)[0]
 s.pop('same_source_US_context_literal');s.pop('same_source_issuer_listing_literal')
 s.update(source_role='OFFICIAL_ISSUER_HOSTED_HISTORICAL_DECLARATION_CASH_AND_SAME_FILE_LISTING_ONLY',
  ticker='AAA',source_currency_context='US_LOUISVILLE_KY_ONLY_IF_PRESENT_IN_SAME_SOURCE_IDENTITY_PREFIX',
  current_capture_utc='2026-10-10T03:02:00Z',same_source_issuer_listing_prefixes=[dict(raw_byte_range=[start,stop],
   original_identity_prefix_ref=h.raw(prefix_raw),visible_text_ref=h.raw(prefix+'\n'),source_identity_literal=prefix,
   typed_content_sha256=hashlib.sha256(json.dumps(prefix,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest())])
 row['source_cash_explicit_common_literal']=row.pop('cash_explicit_common_literal')
 h.notice_transport=dict(schema='ISSUER_DATED_HISTORY_ORIGINAL_HTML_TRANSPORT_V1',actual_status=200,
  source_url=s['source_url'],original_HTTP_ref=s['original_HTTP_ref'],original_HTTP_sha256=s['original_HTTP_ref']['sha256'],
  original_HTTP_bytes=len(body),request_start_utc='2026-10-10T03:00:00Z',request_end_utc='2026-10-10T03:01:00Z',
  source_publication_date=None,historical_availability_authority='UNKNOWN',error=None,
  strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)

_r15_refresh=refresh
def refresh(h):
 _r15_refresh(h)
 if hasattr(h,'notice_source') and h.notice_source.get('same_source_issuer_listing_prefixes'):
  refs=h.projection['source_refs']
  for item in h.notice_source['same_source_issuer_listing_prefixes']:
   refs.extend([item['original_identity_prefix_ref'],item['visible_text_ref']])
  h.bundle['source_refs']=refs;h.entry['fact_ref']=h.write(h.projection)

def test_r15_original_prefix_notice_keeps_two_capture_roles_and_unknown_identity(h):
 r15_prefix_notice(h);source=copy.deepcopy(h.notice_source);transport=copy.deepcopy(h.notice_transport)
 result=bind(h);p=result['receipt']['proofs'][0];b=p['dated_common_unit_bridge_binding'];e=result['events']['entitlement_events'][0]
 assert b['notice_descriptor_profile']=='ISSUER_DATED_HTML_CASH_PREFIX_CUSTODY_DESCRIPTOR_V1'
 assert b['notice_capture_clock_role']=='ACTUAL_TRANSPORT_HTTP_REQUEST_END_UTC_NOT_PUBLICATION'
 assert pd.Timestamp(b['notice_current_capture_utc'])==pd.Timestamp(transport['request_end_utc'])
 assert pd.Timestamp(b['notice_projection_capture_utc'])==pd.Timestamp(source['current_capture_utc'])
 assert b['notice_publication_date']=='2023-01-03' and e.available_at is None and e.cash_per_old_share==3.
 assert b['original_notice_identity_prefix_ref']==source['same_source_issuer_listing_prefixes'][0]['original_identity_prefix_ref']
 assert p['identity']['available_at'] is None and p['identity']['legal_identity_authority_granted'] is False
 assert all(b[k] is False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV'))
 assert p['historical_ex_adjudication']['status']=='QUALIFIED_RESEARCH_FROZEN_CASH_FACT'

@pytest.mark.parametrize('change',['transport_schema','body_bytes','transport_authority','projection_clock','prefix_raw','prefix_hash','prefix_range','prefix_dateline','common_flag','prefix_listing','missing_prefix_pin'])
def test_r15_prefix_notice_rejects_cross_roles_unbound_subject_or_changed_original(h,change):
 r15_prefix_notice(h);s=h.notice_source;t=h.notice_transport;row=s['cash_sources'][0];prefix=s['same_source_issuer_listing_prefixes'][0]
 if change=='transport_schema':t['schema']='HISTORICAL_SOURCE_HTTP_TRANSPORT_V1'
 elif change=='body_bytes':t['original_HTTP_bytes']+=1
 elif change=='transport_authority':t['strict_PIT']=True
 elif change=='projection_clock':s['current_capture_utc']='2026-10-10T03:00:30Z'
 elif change=='prefix_raw':prefix['original_identity_prefix_ref']=h.raw(b'<p>OTHER Issuer (NYSE: AAA)')
 elif change=='prefix_hash':prefix['typed_content_sha256']='0'*64
 elif change=='prefix_range':prefix['raw_byte_range'][1]=row['raw_byte_range'][1]+1
 elif change=='prefix_dateline':
  prefix['source_identity_literal']=prefix['source_identity_literal'].replace('CITY, ST--','CITY, ST.--')
  prefix['typed_content_sha256']=hashlib.sha256(json.dumps(prefix['source_identity_literal'],sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
 elif change=='common_flag':row['source_cash_explicit_common_literal']=True
 elif change=='prefix_listing':prefix['source_identity_literal']=prefix['source_identity_literal'].replace('NYSE: AAA','NYSE: BBB')
 elif change=='missing_prefix_pin':
  refresh(h);refs=h.projection['source_refs'];refs.remove(prefix['visible_text_ref']);h.bundle['source_refs']=refs;h.entry['fact_ref']=h.write(h.projection)
  with pytest.raises(ValueError):mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))
  return
 with pytest.raises(ValueError):bind(h)
# One source group retains the annual and quarterly classes; it is not a quarterly event.
def pgr_component_fixture(h):
 report_frozen_identity(h)
 annual='annual common share dividend, in the amount of $0.75 per share'
 quarterly='quarterly common share dividend, in the amount of $0.10 per share'
 literal='SYNTHETIC CITY, OHIO, Jan. 03, 2023 (GLOBE NEWSWIRE) -- On January 2, 2023, the Board of Directors of The FAKE Corporation (NYSE:AAA) declared an '+annual+', and a '+quarterly+'.\nBoth the annual and quarterly dividends are payable February 1, 2023, to shareholders of record at the close of business on January 20, 2023 (ex-dividend date of January 19, 2023).'
 raw=('<p>'+literal+'</p>').encode();fragment=h.raw(raw);fragment['bytes']=len(raw);text=h.raw(literal+'\n');text['bytes']=len(literal.encode())+1
 h.pg_source=dict(schema='PGR_ISSUER_ORIGINAL_MULTI_COMPONENT_COMMON_CASH_CUSTODY_V1',source_role='ISSUER_HOSTED_ORIGINAL_CASH_DECLARATION',
  actual_HTTP_status=200,capture_utc='2026-10-10T03:00:00Z',original_HTTP_ref=None,original_HTTP_sha256='c'*64,
  original_HTTP_bytes=10000,full_HTTP_widgets_not_decoded_or_persisted=True,components_aggregated=False,
  publication_date_role='ORIGINAL_VISIBLE_DATELINE_NOT_PRIVATE_BOARD_DATE',historical_availability_authority='UNKNOWN',
  ticker='AAA',listing_literal='NYSE:AAA',issuer_literal='The FAKE Corporation',same_document_US_context_literal='SYNTHETIC CITY, OHIO',
  source_url='https://issuer.example/actual-selected-original-fragment',source_currency_literal='$',explicit_USD_literal_present=False,
  source_publication_date='2023-01-03',private_board_declaration_date='2023-01-02',
  source_record_date='2023-01-20',source_pay_date='2023-02-01',source_direct_ex_date=h.vendor['effective_date'],
  original_key=copy.deepcopy(h.vendor),source_original_byte_range=[100,100+len(raw)],original_cash_fragment_ref=fragment,text_projection_ref=text,
  dividend_paragraph=literal,dividend_paragraph_typed_content_sha256=hashlib.sha256(json.dumps(literal,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest(),
  cash_components=[dict(component_kind=kind,amount=amount,amount_literal='$'+amount+' per share',unit_literal=unit,distinct_component=True)
   for kind,amount,unit in zip(mod.COMPONENT_GROUP_KINDS,('0.75','0.10'),('annual common share dividend','quarterly common share dividend'))],
  strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 h.pg_group=dict(schema='PGR_ORIGINAL_COMMON_CASH_FIXED_COMPONENT_GROUP_SOURCE_PROJECTION_V1',actual_HTTP_status=200,
  actual_capture_utc=h.pg_source['capture_utc'],historical_availability_authority='UNKNOWN',original_HTTP_ref=None,
  original_HTTP_opaque_sha256=h.pg_source['original_HTTP_sha256'],original_HTTP_opaque_bytes=h.pg_source['original_HTTP_bytes'],
  original_cash_fragment_ref=fragment,cash_text_projection_ref=text,original_key=copy.deepcopy(h.vendor),
  component_group_is_not_an_ordinary_quarterly_dividend=True,source_unit='ORIGINAL_COMMON_SHARE_CASH_PER_SHARE',
  private_board_declaration_date='2023-01-02',publication_calendar_date='2023-01-03',record_date='2023-01-20',pay_date='2023-02-01',
  source_direct_ex_date=h.vendor['effective_date'],cash_components=[],strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False)
 for kind,amount,clause in zip(mod.COMPONENT_GROUP_KINDS,('0.75','0.10'),(annual,quarterly)):
  start=raw.index(clause.encode());end=start+len(clause.encode())
  h.pg_group['cash_components'].append(dict(component_kind=kind,source_amount_literal=amount,source_component_literal=clause,
   local_fragment_byte_range=[start,end],original_HTTP_byte_range=[100+start,100+end],
   component_original_bytes_sha256=hashlib.sha256(raw[start:end]).hexdigest(),
   original_cash_fragment_ref=fragment,cash_text_projection_ref=text))
 facts=h.projection['source_projection']
 facts.update(cash_per_raw_share=.85,publication_calendar_date='2023-01-03',ordinary_cash_confirmed=False,common_cash_component_group_confirmed=True)
 h.projection.update(schema='B_FROZEN_HISTORY_SAME_CLOCK_COMMON_CASH_COMPONENT_GROUP_SOURCE_PROJECTION_V1',
  cash_evidence_role=mod.COMPONENT_GROUP_ROLE,source_scope=mod.COMPONENT_GROUP_SOURCE_SCOPE)
 h.bundle['same_clock_common_cash_component_group_scope']=copy.deepcopy(mod.COMPONENT_GROUP_SCOPE)

_before_pg_refresh=refresh
def refresh(h):
 _before_pg_refresh(h)
 if not hasattr(h,'pg_source'):return
 source=h.write(h.pg_source);h.pg_group['source_custody_ref']=source
 for p in h.pg_group['cash_components']:p['source_custody_ref']=source
 group=h.write(h.pg_group);identity=h.write(h.report_identity)
 ib=h.identity('AAA');ib.update(source_reference=identity['path'],source_fingerprint=identity['sha256'],available_at=None)
 h.entry.update(frozen_account_identity_ref=identity,identity_binding=ib)
 refs=[source,group,identity,h.pg_source['original_cash_fragment_ref'],h.pg_source['text_projection_ref'],
  *[h.report_identity[k] for k in ('original_uid_intervals_ref','original_frozen_input_manifest_ref','content_hash_owner_ref','original_held_guard_owner_ref')]]
 facts=h.projection['source_projection'];facts.update(issuer_source_fingerprint=h.pg_source['original_cash_fragment_ref']['sha256'],
  identity_source_fingerprint=identity['sha256'],exchange_listing_source_reference=source['path'],exchange_listing_source_fingerprint=source['sha256'])
 h.projection.update(component_group_source_ref=group,frozen_account_identity_ref=identity,identity_binding=copy.deepcopy(ib),source_refs=refs)
 h.bundle['source_refs']=refs;h.entry['fact_ref']=h.write(h.projection)

def test_pgr_component_group_books_decimal_sum_once_and_retains_two_source_classes_and_clock(h):
 pgr_component_fixture(h);before=copy.deepcopy(h.original);result=bind(h)
 assert len(result['events']['entitlement_events'])==1 and result['receipt']['removed_keys']==1 and h.original==before
 assert result['events']['unsupported_events']==(h.raw_flag,)
 event=result['events']['entitlement_events'][0];p=result['receipt']['proofs'][0];g=p['cash_component_group_binding']
 assert event.cash_per_old_share==.85 and event.action_type=='CASH_DIVIDEND' and event.ex_date==h.vendor['effective_date']
 assert type(event) is ca.ResearchReconstructedCashEvent and event.available_at is None
 assert [part['component_kind'] for part in g['cash_components']]==list(mod.COMPONENT_GROUP_KINDS)
 assert [part['source_amount_literal'] for part in g['cash_components']]==['0.75','0.10'] and g['total_cash_amount_literal']=='0.85'
 assert g['original_full_HTTP_ref'] is None and g['annual_ordinary_or_quarterly_reclassification'] is False
 assert g['source_legal_issuer_literal']=='The FAKE Corporation' and g['original_frozen_issuer_literal']=='FAKE   Issuer'
 assert g['issuer_name_alias_used'] is False and p['identity']['available_at'] is None
 assert p['historical_ex_adjudication']['status']=='QUALIFIED_RESEARCH_FROZEN_CASH_FACT'
 assert result['receipt']['component_group_clock_fingerprints']==[event.event_fingerprint]
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 fn,clock=ordinary_cash_lifecycle(h.owner,result['events'],result['ordinary_cash_event_fingerprints'],clone=clone)
 assert clock['consumption_set_role']=='ORDINARY_PAY_END_CLOCK_SET_PLUS_EXPLICIT_SAME_CLOCK_COMPONENT_GROUPS'
 assert clock['events'][0]['cash_component_group_binding']['cash_components']==g['cash_components']
 def step(day,positions,value,state=None):
  return fn((event,),positions,value,execution_date=day,session_open_at=cash._clock(pd.Timestamp(day),9,30),
   security_tickers=result['events']['entitlement_security_tickers'],quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
   state=state,enabled=True,research_account_authority=result['events']['research_account_authority'])
 ex=step(event.ex_date,{event.old_security_id:4.},100.);pay=step('2023-02-01',{},ex.cash,ex.state);spend=step('2023-02-02',{},pay.cash,pay.state)
 assert ex.positions=={event.old_security_id:4.} and ex.cash==pay.cash==100.
 assert ex.receivable_value_usd==pay.receivable_value_usd==pytest.approx(3.4)
 assert spend.cash==pytest.approx(103.4) and spend.receivable_value_usd==0.
 from dataclasses import fields,replace
 strict_terms={field.name:getattr(event,field.name) for field in fields(ca.SourceBackedEntitlementEvent)}
 strict_terms['available_at']='2023-01-03T00:00:00Z'
 strict=ca.SourceBackedEntitlementEvent(**strict_terms);parallel=replace(strict,event_id='UNMARKED_PARALLEL_CASH')
 with pytest.raises(ValueError,match='DUPLICATE_ENTITLEMENT_ECONOMIC_EVENT'):
  ca.apply_entitlement_lifecycle((strict,parallel),{event.old_security_id:4.},100.,
   execution_date=event.ex_date,session_open_at=cash._clock(pd.Timestamp(event.ex_date),9,30),security_tickers=result['events']['entitlement_security_tickers'],
   quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,enabled=True)

@pytest.mark.parametrize('change',['single_leg','duplicate_leg','different_kind','component_bytes','amount_string','sum','unit','currency','pay_clock','source_clock','full_ref','identity_preferred','identity_available','ordinary_label','notice_late','duplicate_group','duplicate_original_key','wrong_key','no_scope'])
def test_pgr_component_group_rejects_incomplete_duplicate_unbound_units_and_clocks(h,change):
 pgr_component_fixture(h);s=h.pg_source;g=h.pg_group
 if change=='single_leg':g['cash_components'].pop()
 elif change=='duplicate_leg':g['cash_components'][1]=copy.deepcopy(g['cash_components'][0])
 elif change=='different_kind':g['cash_components'][0]['component_kind']='QUARTERLY_COMMON_SHARE_CASH_DIVIDEND'
 elif change=='component_bytes':g['cash_components'][0]['component_original_bytes_sha256']='0'*64
 elif change=='amount_string':g['cash_components'][0]['source_amount_literal']='0.85'
 elif change=='sum':h.projection['source_projection']['cash_per_raw_share']=.86
 elif change=='unit':s['cash_components'][0]['unit_literal']='annual preferred share dividend'
 elif change=='currency':s['source_currency_literal']='CAD'
 elif change=='pay_clock':g['cash_components'][0]['pay_date']='2023-02-02'
 elif change=='source_clock':g['pay_date']='2023-02-02'
 elif change=='full_ref':g['original_HTTP_ref']=h.raw('not a captured original body')
 elif change=='identity_preferred':
  from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
  item=h.report_identity['rows'][0];item['original_source_row']['title_of_class']='PREF'
  row=copy.deepcopy(item['original_source_row'])
  for field in ('effective_start','effective_end'):row[field]=pd.Timestamp(row[field])
  item['original_source_row_content_sha256']=content_hash(row)
 elif change=='identity_available':h.report_identity['available_at']='2023-01-02T00:00:00Z'
 elif change=='ordinary_label':h.projection['source_projection']['ordinary_cash_confirmed']=True
 elif change=='notice_late':s['source_publication_date']='2023-01-18'
 elif change=='duplicate_original_key':h.original['unsupported_events']+=(copy.deepcopy(h.vendor),)
 elif change=='wrong_key':g['original_key']['source_fingerprint']='0'*64
 elif change=='no_scope':h.bundle.pop('same_clock_common_cash_component_group_scope')
 if change=='duplicate_group':
  refresh(h);h.bundle['events'].append(copy.deepcopy(h.entry))
  with pytest.raises(ValueError,match='DUPLICATE_OR_PARALLEL_CASH_EVENT'):
   mod.bind_source_account_descendant(h.owner,h.original,h.bundle,account_dates=h.dates,bundle_ref=h.write(h.bundle))
  return
 with pytest.raises(ValueError):bind(h)

def test_pgr_clock_receipt_rejects_group_proof_subject_change(h):
 pgr_component_fixture(h);result=bind(h);result['events']['entitlement_source_binding']['manifest']['proofs'][0]['cash_component_group_binding']['pay_date']='2023-02-02'
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 with pytest.raises(ValueError,match='PAIR_COMPONENT_GROUP_EXACT_CLOCK_BINDING'):
  ordinary_cash_lifecycle(h.owner,result['events'],result['ordinary_cash_event_fingerprints'],clone=clone)


@pytest.mark.parametrize('change',['valid','unknown_role','wrong_kind','reverse','amount','security','pay','duplicate_proof'])
def test_base_variable_clock_profile_preserves_bound_subject_and_single_payment(h,change):
 # Reuse the existing typed-event harness to isolate the account clock consumer.
 pgr_component_fixture(h);result=bind(h)
 g=result['events']['entitlement_source_binding']['manifest']['proofs'][0]['cash_component_group_binding']
 g['cash_evidence_role']=mod.BASE_VARIABLE_COMPONENT_ROLE
 for part,kind in zip(g['cash_components'],mod.BASE_VARIABLE_COMPONENT_KINDS):part['component_kind']=kind
 if change=='unknown_role':g['cash_evidence_role']+='UNKNOWN'
 elif change=='wrong_kind':g['cash_components'][1]['component_kind']='ANNUAL_COMMON_SHARE_CASH_DIVIDEND'
 elif change=='reverse':g['cash_components'].reverse()
 elif change=='amount':g['cash_per_raw_share']=.9
 elif change=='security':g['security_id']='OTHER'
 elif change=='pay':g['pay_date']='2023-02-02'
 elif change=='duplicate_proof':result['events']['entitlement_source_binding']['manifest']['proofs'].append(copy.deepcopy(result['events']['entitlement_source_binding']['manifest']['proofs'][0]))
 def clone(fn,**changes):
  ns=dict(fn.__globals__);ns.update(changes);f=FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__);f.__kwdefaults__=fn.__kwdefaults__;return f
 if change!='valid':
  with pytest.raises(ValueError,match='PAIR_COMPONENT_GROUP_EXACT_CLOCK_BINDING'):
   ordinary_cash_lifecycle(h.owner,result['events'],result['ordinary_cash_event_fingerprints'],clone=clone)
  return
 fn,clock=ordinary_cash_lifecycle(h.owner,result['events'],result['ordinary_cash_event_fingerprints'],clone=clone)
 assert clock['events'][0]['source_cash_classification']=='EXPLICIT_TOTAL_BASE_AND_VARIABLE_COMMON_CASH_COMPONENT_GROUP_NOT_ORDINARY_RECLASSIFICATION'
 event=result['events']['entitlement_events'][0]
 def step(day,positions,value,state=None):
  return fn((event,),positions,value,execution_date=day,session_open_at=cash._clock(pd.Timestamp(day),9,30),security_tickers=result['events']['entitlement_security_tickers'],quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,state=state,enabled=True,research_account_authority=result['events']['research_account_authority'])
 ex=step(event.ex_date,{event.old_security_id:4.},100.);pay=step('2023-02-01',{},ex.cash,ex.state);spend=step('2023-02-02',{},pay.cash,pay.state);again=step('2023-02-03',{},spend.cash,spend.state)
 assert ex.cash==pay.cash==100. and ex.receivable_value_usd==pay.receivable_value_usd==pytest.approx(3.4)
 assert spend.cash==again.cash==pytest.approx(103.4) and spend.receivable_value_usd==again.receivable_value_usd==0.
