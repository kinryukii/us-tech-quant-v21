"""Pure synthetic source transport; no market, labels, fits, or real source files."""
from pathlib import Path
from datetime import datetime
import copy,hashlib,importlib.util,re,sys
import pandas as pd
import pytest
from scripts.research.a2.data import reused_pair_ca_sources as mod
from scripts.research.a2.data import joint_cash_bindings as cash

@pytest.fixture
def submission(tmp_path):
 header=b'<ACCEPTANCE-DATETIME>20250206160000\nACCESSION NUMBER: 0000000123-25-000001\nCENTRAL INDEX KEY: 123\nCONFORMED SUBMISSION TYPE: 8-K\nFILED AS OF DATE: 20250206\n'
 parent=b'<html><p>Fake Issuer Corporation</p><p>Delaware</p><table>Common Stock FAKE Nasdaq Global Select Market</table></html>'
 clause='Our board of directors declared a quarterly cash dividend of $0.25 per share of common stock, payable on February 13, 2025, to stockholders of record on February 10, 2025.'
 child=('<html><p>'+clause+'</p></html>').encode()
 original=header+b'<DOCUMENT>\n<TYPE>8-K\n<FILENAME>fake8k.htm\n<TEXT>'+parent+b'</TEXT>\n</DOCUMENT>\n<DOCUMENT>\n<TYPE>EX-99.1\n<FILENAME>fakeex99.htm\n<TEXT>'+child+b'</TEXT>\n</DOCUMENT>'
 p=tmp_path/'static.txt';p.write_bytes(original);bodyref={'path':str(p),'sha256':hashlib.sha256(original).hexdigest()}
 docs=[]
 for m in re.finditer(rb'<DOCUMENT>\s*(.*?)</DOCUMENT>',original,re.S):
  x=m[1];t=re.search(rb'<TEXT>(.*?)</TEXT>',x,re.S);docs.append({'type':re.search(rb'<TYPE>([^\n]+)',x)[1].decode(),'filename':re.search(rb'<FILENAME>([^\n]+)',x)[1].decode(),'text_byte_range':[m.start(1)+t.start(1),m.start(1)+t.end(1)]})
 parentdoc,childdoc=docs
 cover=[]
 for role,needle in [('SAME_FILE_REGISTRANT_NAME',b'<p>Fake Issuer Corporation</p>'),('SAME_FILE_US_CHARTER',b'<p>Delaware</p>'),('SAME_FILE_COMMON_LISTING_TABLE',b'<table>Common Stock FAKE Nasdaq Global Select Market</table>')]:
  i=original.index(needle);cover.append({'fragment_role':role,'original_byte_range':[i,i+len(needle)]})
 i=original.index(clause.encode());selected={'original_byte_range':[i,i+len(clause.encode())]}
 binding={'schema':'STATIC_SEC_SAME_ACCESSION_PARENT_AND_EX99_TRANSPORT_V1','accession':'0000000123-25-000001','issuer_CIK':123,'original_submission_ref':bodyref,'accepted_at_utc':'2025-02-06T21:00:00+00:00','attachment_published_at_utc':'2025-02-06T21:00:00+00:00','unit_basis':'ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION','source_publication_not_press_dateline':True,'share_quantity_effect':False,'parent_document':parentdoc,'cash_attachment_document':childdoc}
 source={'original_HTTP_ref':bodyref,'static_submission_binding':binding};support={'fragments':cover};payload={'selected_original_cash_fragment':selected}
 row={'adsh':'0000000123-25-000001','cik':123,'filed_date':datetime(2025,2,6),'accepted_datetime':datetime(2025,2,6,16),'form':'8-K','instance':'fake8k.htm'}
 facts={'exact_frozen_event_key':{'effective_date':'2025-02-10'},'cash_per_raw_share':0.25,'record_date':'2025-02-10','pay_date':'2025-02-13'}
 def pinned(ref):
  q=Path(ref['path']);assert hashlib.sha256(q.read_bytes()).hexdigest()==ref['sha256'];return q
 return source,support,payload,row,facts,pinned,clause

def test_same_submission_parent_and_attachment_are_source_only(submission):
 source,support,payload,row,facts,pinned,clause=submission
 proof=mod._validate_static_sec_submission(source,support,payload,row,facts,pinned=pinned)
 assert proof['share_quantity_effect'] is False and proof['strict_PIT'] is False
 assert proof['attachment_published_at_utc']==proof['accepted_at_utc']
 assert mod._static_submission_cash_statement(clause,facts,row['filed_date'])==('2025-02-06','0.25','February 13, 2025','February 10, 2025')

@pytest.mark.parametrize('case',['wrong_accession','wrong_cik','wrong_primary','child_is_parent','cash_in_cover','cover_in_child','earlier_attachment','pre_ex_fail','unit_factor','changed_parent_range'])
def test_static_source_counterexamples_remain_closed(submission,case):
 source,support,payload,row,facts,pinned,_=submission
 if case=='wrong_accession':row['adsh']='0000000123-25-000002'
 elif case=='wrong_cik':row['cik']=456
 elif case=='wrong_primary':row['instance']='other.htm'
 elif case=='child_is_parent':source['static_submission_binding']['cash_attachment_document']=source['static_submission_binding']['parent_document']
 elif case=='cash_in_cover':payload['selected_original_cash_fragment']['original_byte_range']=support['fragments'][0]['original_byte_range']
 elif case=='cover_in_child':support['fragments'][0]['original_byte_range']=payload['selected_original_cash_fragment']['original_byte_range']
 elif case=='earlier_attachment':source['static_submission_binding']['attachment_published_at_utc']='2025-02-05T21:00:00+00:00'
 elif case=='pre_ex_fail':facts['exact_frozen_event_key']['effective_date']='2025-02-06'
 elif case=='unit_factor':source['static_submission_binding']['unit_basis']='INFERRED_FROM_VENDOR_PRICE_RATIO'
 elif case=='changed_parent_range':source['static_submission_binding']['parent_document']['text_byte_range'][0]+=1
 with pytest.raises(ValueError):mod._validate_static_sec_submission(source,support,payload,row,facts,pinned=pinned)

@pytest.mark.parametrize('case',['amount','record','pay','retroadjusted','multiple_cash','not_cash','explicit_class'])
def test_original_literal_unit_and_clocks_are_not_guessed(submission,case):
 _,_,_,row,facts,_,text=submission
 if case=='amount':facts['cash_per_raw_share']=0.5
 elif case=='record':facts['record_date']='2025-02-11'
 elif case=='pay':facts['pay_date']='2025-02-14'
 elif case=='retroadjusted':text+=' This amount is split adjusted.'
 elif case=='not_cash':text=text.replace('cash ','')
 elif case=='explicit_class':text=text.replace('per share of common stock','per Class B share')
 elif case=='multiple_cash':text+=' A dividend of $0.50 per common share is also payable on March 1, 2025, to stockholders of record on February 20, 2025.'
 with pytest.raises(ValueError):mod._static_submission_cash_statement(text,facts,row['filed_date'])

def test_new_source_profile_uses_existing_cash_adjudication_without_changing_old_gate(tmp_path,monkeypatch):
 spec=importlib.util.spec_from_file_location('synthetic_existing_cash_profile',Path(__file__).with_name('test_reused_pair_sec_cash.py'));m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 h=m.h.__wrapped__(tmp_path,monkeypatch);m.refresh(h);terms=mod._sec_frozen_cash_terms(h.projection,h.entry);oldfacts=copy.deepcopy(terms['historical_ex_adjudication_input'])
 def run(facts,scope=mod.SEC_CASH_SOURCE_SCOPE):
  env={'path':'D:/FAKE_ONLY/new_submission.json','sha256':'f'*64,'payload':facts,'guard':{'status':'HASH_VERIFIED_PAYLOAD','path':'D:/FAKE_ONLY/new_submission.json','sha256':'f'*64,'payload_sha256':cash._hash(facts)}}
  return cash.adjudicate_post_verified_cash_ex(env,calendar=[str(d.date()) for d in h.dates],calendar_binding=h.bundle['historical_calendar_binding'],rule_sources=h.bundle['historical_rule_sources'],scope_end_exclusive='2026-01-01',source_scope=scope)
 before=run(oldfacts);assert before['status']=='QUALIFIED_RESEARCH_FROZEN_CASH_FACT'
 facts=copy.deepcopy(oldfacts);b=facts['sec_frozen_cash_binding'];b.update(source_transport_profile=mod.SEC_STATIC_SUBMISSION_PROFILE,sec_cash_statement_profile='STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION',source_statement_date_role='STATIC_SUBMISSION_PUBLIC_ACCEPTANCE_DAY_NOT_BOARD_DATE',source_statement_date='2023-01-13',private_board_declaration_date=None,source_frozen_common_identity_role=mod.FROZEN_COMMON_NAMESPACE_ROLE,source_CUSIP=None,source_common_CUSIP_identity_custody_ref=None,source_legal_CUSIP_claim=False,new_legal_identity_authority=False,strict_PIT=False,production_qualified=False,quote_qualified=False,certified_NAV=False,static_submission_transport_proof={'schema':'STATIC_SEC_SAME_ACCESSION_PARENT_AND_EX99_TRANSPORT_V1','unit_basis':'ORIGINAL_PRE_EX_CURRENT_COMMON_SHARE_DECLARATION','source_publication_not_press_dateline':True,'share_quantity_effect':False,'accepted_at_utc':'2023-01-13T15:00:00+00:00'})
 b.update(issuer_relation_role='EXACT_DATED_FROZEN_COM_AND_STATIC_UNIQUE_COMMON_SYMBOL',issuer_name_alias_used=False,static_submission_dated_raw_identity_proof={'same_dated_UID_and_SID':True,'accounting_sid':facts['security_id'],'new_legal_CUSIP_authority':False,'share_quantity_effect':False})
 result=run(facts);assert result['status']=='QUALIFIED_RESEARCH_FROZEN_CASH_FACT',result
 for name in ('cash_per_raw_share','record_date','pay_date'):assert result['source_facts'][name]==before['source_facts'][name] if 'source_facts' in result else facts[name]==oldfacts[name]
 assert run(facts,'FROZEN_PRE2026_NYSE_COMMON_USD')['status']=='BLOCKED_SOURCE'
 b['static_submission_transport_proof']['share_quantity_effect']=True;assert run(facts)['status']=='BLOCKED_SOURCE'
@pytest.mark.parametrize('case',[None,'reused_ticker','mismatched_sid','non_common','nonunique','late_acceptance','class_a_cover_class_b_cash','after1730_next_filed_day','unmocked_raw','unmocked_class_a_match','unmocked_class_b_conflict','uppercase_nasdaq','unmocked_primary_8k','unmocked_primary_10q','unmocked_primary_10k'])
def test_full_native_source_profile_constructs_cash_terms_from_same_submission(submission,tmp_path,monkeypatch,case):
 """The external frozen identity seed is synthetic; its old owner has separate regression."""
 import json
 import pyarrow as pa
 import pyarrow.parquet as pq
 from scripts.storage.refresh_sec_event_originals import FilingText
 from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
 source,support,payload,row,facts,pinned,clause=submission
 if case in ('class_a_cover_class_b_cash','after1730_next_filed_day','unmocked_class_a_match','unmocked_class_b_conflict','uppercase_nasdaq'):
  body=Path(source['original_HTTP_ref']['path']);raw=body.read_bytes()
  if case in ('class_a_cover_class_b_cash','unmocked_class_a_match','unmocked_class_b_conflict'):
   raw=raw.replace(b'<table>Common Stock FAKE Nasdaq Global Select Market</table>',b'<table>Class A Common Stock FAKE Nasdaq Global Select Market</table>');clause=clause.replace('per share of common stock','per Class B share');raw=raw.replace(b'per share of common stock',b'per Class B share')
   if case=='unmocked_class_a_match':clause=clause.replace('Class B','Class A');raw=raw.replace(b'per Class B share',b'per Class A share')
  elif case=='uppercase_nasdaq':raw=raw.replace(b'Nasdaq Global Select Market',b'NASDAQ GLOBAL SELECT MARKET')
  else:
   raw=raw.replace(b'20250206160000',b'20250206183000').replace(b'FILED AS OF DATE: 20250206',b'FILED AS OF DATE: 20250207');row['filed_date']=datetime(2025,2,7);row['accepted_datetime']=datetime(2025,2,6,18,30);source['static_submission_binding']['accepted_at_utc']=source['static_submission_binding']['attachment_published_at_utc']='2025-02-06T23:30:00+00:00'
  body.write_bytes(raw);rr={'path':str(body),'sha256':hashlib.sha256(raw).hexdigest()};source['original_HTTP_ref']=rr;source['static_submission_binding']['original_submission_ref']=rr;docs=[]
  for m in re.finditer(rb'<DOCUMENT>\s*(.*?)</DOCUMENT>',raw,re.S):
   x=m[1];t=re.search(rb'<TEXT>(.*?)</TEXT>',x,re.S);docs.append({'type':re.search(rb'<TYPE>([^\n]+)',x)[1].decode(),'filename':re.search(rb'<FILENAME>([^\n]+)',x)[1].decode(),'text_byte_range':[m.start(1)+t.start(1),m.start(1)+t.end(1)]})
  source['static_submission_binding']['parent_document'],source['static_submission_binding']['cash_attachment_document']=docs
  if case in ('class_a_cover_class_b_cash','unmocked_class_a_match','unmocked_class_b_conflict'):
   needle=b'<table>Class A Common Stock FAKE Nasdaq Global Select Market</table>';i=raw.index(needle);support['fragments'][2]['original_byte_range']=[i,i+len(needle)];i=raw.index(clause.encode());payload['selected_original_cash_fragment']['original_byte_range']=[i,i+len(clause.encode())]
  if case=='uppercase_nasdaq':
   needle=b'<table>Common Stock FAKE NASDAQ GLOBAL SELECT MARKET</table>';i=raw.index(needle);support['fragments'][2]['original_byte_range']=[i,i+len(needle)]
 if case and case.startswith('unmocked_primary_'):
  form={'unmocked_primary_8k':'8-K','unmocked_primary_10q':'10-Q','unmocked_primary_10k':'10-K'}[case]
  body=Path(source['original_HTTP_ref']['path']);raw=body.read_bytes();raw=raw.replace(b'CONFORMED SUBMISSION TYPE: 8-K',b'CONFORMED SUBMISSION TYPE: '+form.encode()).replace(b'<TYPE>8-K',b'<TYPE>'+form.encode(),1)
  raw=raw.replace(b'</table></html>',b'</table><p>'+clause.encode()+b'</p></html>',1).replace(b'<html><p>'+clause.encode()+b'</p></html>',b'<html><p>No cash statement.</p></html>')
  body.write_bytes(raw);rr={'path':str(body),'sha256':hashlib.sha256(raw).hexdigest()};source['original_HTTP_ref']=rr;row['form']=form;docs=[]
  for m in re.finditer(rb'<DOCUMENT>\s*(.*?)</DOCUMENT>',raw,re.S):
   x=m[1];z=re.search(rb'<TEXT>(.*?)</TEXT>',x,re.S);docs.append({'type':re.search(rb'<TYPE>([^\n]+)',x)[1].decode(),'filename':re.search(rb'<FILENAME>([^\n]+)',x)[1].decode(),'text_byte_range':[m.start(1)+z.start(1),m.start(1)+z.end(1)]})
  b=source['static_submission_binding'];b.update(schema='STATIC_SEC_SAME_ACCESSION_PRIMARY_BODY_CASH_TRANSPORT_V1',original_submission_ref=rr,parent_document=docs[0],cash_attachment_document=docs[0],cash_document_role='ORIGINAL_PRIMARY_SEC_BODY_CURRENT_COMMON_CASH_DECLARATION',cash_document_published_at_utc=b['accepted_at_utc'])
  for f in support['fragments']:
   needle=raw[slice(*f['original_byte_range'])] if form=='8-K' else None
  needles=[b'<p>Fake Issuer Corporation</p>',b'<p>Delaware</p>',b'<table>Common Stock FAKE Nasdaq Global Select Market</table>']
  for f,needle in zip(support['fragments'],needles):i=raw.index(needle);f['original_byte_range']=[i,i+len(needle)]
  i=raw.index(clause.encode());payload['selected_original_cash_fragment']['original_byte_range']=[i,i+len(clause.encode())]
 if case=='nonunique':
  body=Path(source['original_HTTP_ref']['path']);raw=body.read_bytes();old=b'<table>Common Stock FAKE Nasdaq Global Select Market</table>';new=b'<table>Common Stock FAKE Nasdaq Global Select Market OTHER Nasdaq Global Select Market</table>';raw=raw.replace(old,new);body.write_bytes(raw);rr={'path':str(body),'sha256':hashlib.sha256(raw).hexdigest()};source['original_HTTP_ref']=rr;source['static_submission_binding']['original_submission_ref']=rr
  docs=[]
  for m in re.finditer(rb'<DOCUMENT>\s*(.*?)</DOCUMENT>',raw,re.S):
   x=m[1];t=re.search(rb'<TEXT>(.*?)</TEXT>',x,re.S);docs.append({'type':re.search(rb'<TYPE>([^\n]+)',x)[1].decode(),'filename':re.search(rb'<FILENAME>([^\n]+)',x)[1].decode(),'text_byte_range':[m.start(1)+t.start(1),m.start(1)+t.end(1)]})
  source['static_submission_binding']['parent_document'],source['static_submission_binding']['cash_attachment_document']=docs
  i=raw.index(new);support['fragments'][2]['original_byte_range']=[i,i+len(new)];i=raw.index(clause.encode());payload['selected_original_cash_fragment']['original_byte_range']=[i,i+len(clause.encode())]
 files=[]
 def save(name,value):
  p=tmp_path/name
  if isinstance(value,bytes):p.write_bytes(value)
  else:p.write_text(json.dumps(value,default=lambda v:v.isoformat(),sort_keys=True),encoding='utf-8')
  r={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()};files.append(r);return r
 def fragment(item,role):
  body=Path(source['original_HTTP_ref']['path']).read_bytes();raw=body[slice(*item['original_byte_range'])];parser=FilingText();parser.feed(raw.decode());text=' '.join(' '.join(parser.parts).split())
  r=dict(item,fragment_role=role,original_fragment_ref=save(str(len(files))+'.html',raw),text_projection_ref=save(str(len(files))+'.txt',(text+'\n').encode()),text=text,text_typed_content_sha256=mod._hash(text))
  return r
 support['fragments']=[fragment(x,x['fragment_role']) for x in support['fragments']]
 selected=fragment(payload['selected_original_cash_fragment'],'ORIGINAL_COMMON_CASH_DECLARATION_EX99');payload['selected_original_cash_fragment']=selected
 metadata=dict(name='Fake Issuer Corporation',**row);columns=['name','cik','adsh','form','filed_date','accepted_datetime','instance'];mp=tmp_path/'metadata.parquet';pq.write_table(pa.Table.from_pylist([metadata]),mp);mr={'path':str(mp),'sha256':hashlib.sha256(mp.read_bytes()).hexdigest()};files.append(mr)
 url='https://www.sec.gov/Archives/edgar/data/123/0000000123-25-000001.txt';flags={k:False for k in ('strict_PIT','production_qualified','quote_qualified','certified_NAV')}
 filed_day=str(row['filed_date'].date())
 source.update(schema='HISTORICAL_SEC_ORIGINAL_CASH_AND_COMMON_COVER_CUSTODY_V1',ticker='FAKE',source_original_ticker='FAKE',source_url=url,issuer_CIK=123,source_form=row['form'],source_publication_date=filed_day,metadata_ref=mr,capture_utc='2026-10-12T00:00:00+00:00',cash_fragments=[selected],**flags)
 tr=save('transport.json',dict(schema='HISTORICAL_FIXED_SEC_FREE_CA_SOURCE_TRANSPORT_V1',actual_HTTP_status=200,original_HTTP_ref=source['original_HTTP_ref'],source_url=url,source_metadata_ref=mr,actual_metadata_row={k:(filed_day if k=='filed_date' else metadata[k]) for k in ('name','cik','adsh','filed_date','instance')},**flags));source['HTTP_transport_ref']=tr
 sr=save('source.json',source);support.update(schema='HISTORICAL_SEC_EXACT_ORIGINAL_CASH_AND_IDENTITY_SIDECAR_V1',original_HTTP_ref=source['original_HTTP_ref'],original_source_custody_ref=sr,source_url=url,**flags);ur=save('support.json',support)
 md=save('metadata.json',dict(schema='EXACT_PRE2026_SEC_FILING_METADATA_ROW_PROJECTION_CUSTODY_V1',original_metadata_columns=columns,original_metadata_row_datetime_encoding_recipe='FILED_DATE_AND_ACCEPTED_DATETIME_ISO8601_RECONSTRUCT_DATETIME_FROMISOFORMAT_BEFORE_CONTENT_HASH',historical_availability_authority='UNKNOWN',original_metadata_ref=mr,original_metadata_row=metadata,original_metadata_row_content_sha256=content_hash(metadata),exact_predicate={'cik':123,'adsh':row['adsh']},source_primary_HTML_url=url,**flags))
 fr=save('frozen_identity.json',{'synthetic_identity_seed':True});files.append(source['original_HTTP_ref'])
 frozen={'identity':{'security_id':'CUSIP:123456789'},'original_source_row':{'ticker':'FAKE','title_of_class':'COM','cusip':'123456789','issuer_name':'FAKE ISSUER CORP'}}
 if case not in ('unmocked_raw','unmocked_class_a_match','unmocked_class_b_conflict','unmocked_primary_8k','unmocked_primary_10q','unmocked_primary_10k'):monkeypatch.setattr(mod,'_existing_frozen_common_identity',lambda *a,**k:frozen)
 facts.update(clock_role='POST_VERIFIED_ACCOUNTING_ONLY',available_at=None,issuer_jurisdiction='US',security_type='COMMON_STOCK',currency='USD',amount_unit=cash.USD_PER_RAW_OLD_SHARE,quantity_coordinate=cash.RAW_OLD_SHARE_COORDINATE,ticker='FAKE',security_id='CUSIP:123456789',listing_identity='NASDAQ:FAKE',sec_filer_cik=123,publication_calendar_date=filed_day,ex_date_provenance_role='EXACT_FROZEN_EVENT_MATCHES_NORMAL_CALENDAR_RESEARCH_ONLY',issuer_source_fingerprint=selected['original_fragment_ref']['sha256'],identity_source_fingerprint=fr['sha256'])
 entry={'identity_binding':{'issuer':'FAKE ISSUER CORP'},'prior_raw_close':{'prior_date':'2025-02-07','synthetic_only':True},'original_unsupported_keys':[facts['exact_frozen_event_key']]}
 if case in ('unmocked_raw','unmocked_class_a_match','unmocked_class_b_conflict','unmocked_primary_8k','unmocked_primary_10q','unmocked_primary_10k'):
  cols=['ticker','effective_start','effective_end','security_id','security_id_type','cusip','issuer_name','title_of_class','moomoo_transport_code','mapping_status','mapping_source','source_filing']
  original=dict(ticker='FAKE',effective_start=pd.Timestamp('2025-02-06'),effective_end=pd.Timestamp('2025-02-11'),security_id='123456789',security_id_type='CUSIP',cusip='123456789',issuer_name='FAKE ISSUER CORP',title_of_class='COM',moomoo_transport_code='US.FAKE',mapping_status='RESOLVED',mapping_source='SYNTHETIC_PRIOR_FILING',source_filing='SYNTHETIC_13F')
  interval=tmp_path/'interval.parquet';pq.write_table(pa.Table.from_pylist([original]),interval);ir={'path':str(interval),'sha256':hashlib.sha256(interval.read_bytes()).hexdigest()};files.append(ir)
  manifest=save('family_manifest.json',{'sources':{'uid_intervals':dict(ir,bytes=interval.stat().st_size)}})
  ch=save('synthetic_hash_owner.py',b'# synthetic pinned source owner');hg=save('synthetic_held_guard.py',b'# synthetic pinned held guard')
  reuse=dict(schema_version='B_EXISTING_FROZEN_RAW_COMMON_IDENTITY_REUSE_V1',status='EXACT_ORIGINAL_FROZEN_IDENTITY_ROWS_REUSED_NOT_NEW_SECURITY_MASTER',ticker='FAKE',available_at=None,historical_publication_authority='UNKNOWN',interval_semantics='ORIGINAL_FROZEN_RESEARCH_EFFECTIVE_INTERVAL_NOT_PUBLICATION_TIMESTAMP',original_date_type='pandas.Timestamp',encoded_date_representation='YYYY-MM-DD_RECONSTRUCT_PANDAS_TIMESTAMP_BEFORE_ORIGINAL_TYPED_HASH',row_count=1,rows=[dict(original_source_row=original,original_source_row_content_sha256=content_hash(original))],original_uid_intervals_ref=ir,original_frozen_input_manifest_ref=manifest,content_hash_owner_ref=ch,original_held_guard_owner_ref=hg,source_identity_columns=cols,**{k:False for k in ('interval_extension','new_security_master','ticker_alias','share_quantity_effect',*flags)})
  fr=save('unmocked_frozen_identity.json',reuse);facts['identity_source_fingerprint']=fr['sha256']
  core=dict(security_id=cash.source_derived_security_id('FAKE ISSUER CORP','FAKE','NASDAQ:FAKE'),identity_kind='SOURCE_DERIVED_ISSUER_COMMON_CLASS',issuer='FAKE ISSUER CORP',ticker='FAKE',listing_identity='NASDAQ:FAKE',security_type='COMMON_STOCK')
  entry['identity_binding']=dict(core,identity_payload_sha256=mod._hash(core),available_at=None,source_reference=fr['path'],source_fingerprint=fr['sha256']);entry['frozen_account_identity_ref']=fr
 calendarp=tmp_path/'calendar.parquet';pq.write_table(pa.Table.from_pylist([{'trade_date':pd.Timestamp(x)} for x in ('2025-02-06','2025-02-07','2025-02-10','2025-02-11')]),calendarp)
 datedp=tmp_path/'dated.parquet';dq=[{'signal_date':pd.Timestamp(x),'ticker':'OTHER' if case=='reused_ticker' else 'FAKE','security_id':'123456789','moomoo_transport_code':'US.FAKE'} for x in ('2025-02-07','2025-02-10')];pq.write_table(pa.Table.from_pylist(dq),datedp)
 mp=save('mapping.json',{'records':[{'ticker':'FAKE','start':'2025-02-06','end':'2025-02-11','coordinate':'RAW_ACTUAL_SHARE','sid':'CUSIP:987654321' if case=='mismatched_sid' else 'CUSIP:123456789'}],'basis_by_ticker':{}})
 ib=save('bank.json',{'rows':[{'ticker':'FAKE','observed_decision_security_ids':['123456789']}]})
 cr={'path':str(calendarp),'sha256':hashlib.sha256(calendarp.read_bytes()).hexdigest()};dr={'path':str(datedp),'sha256':hashlib.sha256(datedp.read_bytes()).hexdigest()};files.extend((cr,dr))
 bridge={'schema':'STATIC_SEC_EXACT_DATED_RAW_COMMON_UID_BRIDGE_V1','role':'EXACT_DATED_FROZEN_COM_AND_STATIC_UNIQUE_COMMON_SYMBOL','ticker':'FAKE','source_coordinate':'RAW_ACTUAL_SHARE','new_legal_CUSIP_authority':False,'issuer_CIK_is_security_UID':False,'share_quantity_effect':False,'calendar_ref':cr,'dated_identity_ref':dr,'mapping_ref':mp,'identity_projection_ref':ib}
 payload.update(schema='B_FROZEN_HISTORY_SEC_CASH_FACT_SOURCE_PROJECTION_V1',clock_role='POST_VERIFIED_ACCOUNTING_ONLY',cash_evidence_role=mod.SEC_CASH_ROLE,source_scope=mod.SEC_CASH_SOURCE_SCOPE,historical_available_at=None,exchange_notice_authority='UNKNOWN',actual_exchange_ex_authority='UNKNOWN',source_projection=facts,identity_binding=entry['identity_binding'],prior_raw_close=entry['prior_raw_close'],exact_original_unsupported_keys=entry['original_unsupported_keys'],sec_source_transport_profile=mod.SEC_STATIC_SUBMISSION_PROFILE,sec_cash_statement_profile='STATIC_SEC_SUBMISSION_ORIGINAL_COMMON_CASH_DECLARATION',sec_cash_source_custody_ref=sr,same_file_cash_identity_support_ref=ur,historical_sec_filing_metadata_ref=md,frozen_account_identity_ref=fr,source_frozen_common_identity_role=mod.FROZEN_COMMON_NAMESPACE_ROLE,source_common_CUSIP_identity_custody_ref=None,static_submission_dated_raw_identity_binding=bridge,source_refs=files,**flags)
 if case and case.startswith('unmocked_primary_'):payload['sec_source_transport_profile']=mod.SEC_STATIC_PRIMARY_BODY_PROFILE
 if case=='non_common':frozen['original_source_row']['title_of_class']='PREFERRED'
 elif case=='late_acceptance':facts['exact_frozen_event_key']['effective_date']='2025-02-06'
 if case not in (None,'after1730_next_filed_day','unmocked_raw','unmocked_class_a_match','uppercase_nasdaq','unmocked_primary_8k','unmocked_primary_10q','unmocked_primary_10k'):
  with pytest.raises((ValueError,AssertionError),match='CA_SEC_HTML_REAL_US_COMMON_LEGAL_LISTING_REQUIRED' if case=='nonunique' else None):mod._sec_frozen_cash_terms(payload,entry)
  return
 result=mod._sec_frozen_cash_terms(payload,entry)
 assert result['sec_frozen_cash_binding']['issuer_name_alias_used'] is False
 assert result['sec_frozen_cash_binding']['original_and_source_issuer_names_equal'] is False
 assert result['sec_frozen_cash_binding']['static_submission_dated_raw_identity_proof']['security_uid']=='CUSIP:123456789'
 assert result['cash_per_common_share']==0.25 and result['record_date']=='2025-02-10' and result['pay_date']=='2025-02-13'
 if case in ('unmocked_raw','unmocked_class_a_match','unmocked_class_b_conflict','unmocked_primary_8k','unmocked_primary_10q','unmocked_primary_10k'):
  fi=result['frozen_account_identity_binding'];assert fi['identity']['security_id']==facts['security_id']=='CUSIP:123456789'
  assert fi['identity']['identity_kind']=='EXACT_DATED_FROZEN_RAW_ACCOUNTING_SID'
  assert fi['original_source_derived_identity']==core and fi['original_source_derived_identity']['security_id']!=facts['security_id']
 assert result['availability_bound']=={'available_at':None}
 if case=='after1730_next_filed_day':
  assert result['sec_frozen_cash_binding']['actual_SEC_filed_date']=='2025-02-07'
  assert result['sec_frozen_cash_binding']['source_statement_date']=='2025-02-06'
 assert result['sec_frozen_cash_binding']['static_submission_transport_proof']['accession']==row['adsh']
 assert result['sec_frozen_cash_binding']['source_legal_CUSIP_claim'] is False
@pytest.mark.parametrize('declared,listed,allowed',[('A','A',True),('B','A',False),('A and Class B','A',False),('D','D',False),('A',None,False)])
def test_static_explicit_class_source_requires_one_exact_class(submission,declared,listed,allowed):
 _,_,_,row,facts,_,clause=submission
 text=clause.replace('per share of common stock','per Class '+declared+' share')
 if allowed:
  assert mod._static_submission_cash_statement(text,facts,row['filed_date'],listed_common_class=listed)[1]=='0.25'
 else:
  with pytest.raises(ValueError):mod._static_submission_cash_statement(text,facts,row['filed_date'],listed_common_class=listed)


@pytest.mark.parametrize('case',[None,'old_profile','wrong_cash_doc','missing_role','cash_in_attachment','after_ex'])
def test_primary_body_opt_in_keeps_exact_document_and_pre_ex_guards(submission,case):
 source,support,payload,row,facts,pinned,clause=submission
 body=Path(source['original_HTTP_ref']['path']);raw=body.read_bytes();raw=raw.replace(b'</table></html>',b'</table><p>'+clause.encode()+b'</p></html>',1)
 body.write_bytes(raw);rr={'path':str(body),'sha256':hashlib.sha256(raw).hexdigest()};source['original_HTTP_ref']=rr;docs=[]
 for m in re.finditer(rb'<DOCUMENT>\s*(.*?)</DOCUMENT>',raw,re.S):
  x=m[1];z=re.search(rb'<TEXT>(.*?)</TEXT>',x,re.S);docs.append({'type':re.search(rb'<TYPE>([^\n]+)',x)[1].decode(),'filename':re.search(rb'<FILENAME>([^\n]+)',x)[1].decode(),'text_byte_range':[m.start(1)+z.start(1),m.start(1)+z.end(1)]})
 b=source['static_submission_binding'];b.update(schema='STATIC_SEC_SAME_ACCESSION_PRIMARY_BODY_CASH_TRANSPORT_V1',original_submission_ref=rr,parent_document=docs[0],cash_attachment_document=docs[0],cash_document_role='ORIGINAL_PRIMARY_SEC_BODY_CURRENT_COMMON_CASH_DECLARATION',cash_document_published_at_utc=b['accepted_at_utc'])
 payload['sec_source_transport_profile']=mod.SEC_STATIC_PRIMARY_BODY_PROFILE;i=raw.index(clause.encode());payload['selected_original_cash_fragment']['original_byte_range']=[i,i+len(clause.encode())]
 if case=='old_profile':payload['sec_source_transport_profile']=mod.SEC_STATIC_SUBMISSION_PROFILE
 elif case=='wrong_cash_doc':b['cash_attachment_document']=docs[1]
 elif case=='missing_role':del b['cash_document_role']
 elif case=='cash_in_attachment':i=raw.rindex(clause.encode());payload['selected_original_cash_fragment']['original_byte_range']=[i,i+len(clause.encode())]
 elif case=='after_ex':facts['exact_frozen_event_key']['effective_date']='2025-02-06'
 if case is not None:
  with pytest.raises(ValueError):mod._validate_static_sec_submission(source,support,payload,row,facts,pinned=pinned)
  return
 proof=mod._validate_static_sec_submission(source,support,payload,row,facts,pinned=pinned)
 assert proof['parent_document']==proof['cash_attachment_document'] and proof['cash_document_published_at_utc']==proof['accepted_at_utc']
