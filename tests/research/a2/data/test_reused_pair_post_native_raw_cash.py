"""Generated post-native cash mapping: source/economics stay unchanged."""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
import copy,json,hashlib
import pandas as pd,pyarrow as pa,pyarrow.parquet as pq
import pytest
from scripts.research.a2.data import reused_pair_ca_sources as source
from scripts.v22 import corporate_action_transition_r1 as ca

@pytest.fixture
def generated(tmp_path):
 def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 def save(name,data):
  p=tmp_path/name;p.write_text(json.dumps(data),encoding='utf-8');return ref(p)
 def parquet(name,rows):
  p=tmp_path/name;pq.write_table(pa.Table.from_pylist(rows),p);return ref(p)
 cal=parquet('calendar.parquet',[{'trade_date':pd.Timestamp(d)} for d in ('2025-02-07','2025-02-10','2025-02-11')])
 dated=parquet('dated.parquet',[{'signal_date':pd.Timestamp(d),'ticker':'FAKE','security_id':'123456789','moomoo_transport_code':'US.FAKE'} for d in ('2025-02-07','2025-02-10')])
 mp=save('mapping.json',{'records':[{'ticker':'FAKE','start':'2025-02-07','end':'2025-02-11','coordinate':'RAW_ACTUAL_SHARE','sid':'FROZEN_RAW_TRANSPORT_CODE:US.FAKE'}],'basis_by_ticker':{}})
 ip=save('identity.json',{'rows':[{'ticker':'FAKE','observed_decision_security_ids':['123456789']} ]})
 raw=parquet('raw.parquet',[{'ticker':'FAKE','trade_date':pd.Timestamp('2025-02-07'),'close':100.}])
 fact=save('fact.json',{'synthetic':'native source facts already checked by binder'})
 ident=save('frozen_identity.json',{'synthetic':'original source row native validated'})
 sid='SOURCE_ISSUER_COMMON_CLASS:'+'a'*64
 event=ca.ResearchReconstructedCashEvent('OLD_NATIVE_EVENT','CASH_DIVIDEND',sid,'FAKE','2025-02-10','2025-02-10','2025-02-13',None,.25,'USD',ca.USD_PER_RAW_OLD_SHARE,ca.RAW_OLD_SHARE_COORDINATE,'TIER1_ISSUER_REGULATOR_EXCHANGE','https://www.sec.gov/Archives/synthetic.htm','b'*64,reconstruction_ref=fact['path'],reconstruction_sha256=fact['sha256'],source_scope='B_FROZEN_PRE2026_ACCOUNTING_ONLY')
 entry={'identity_binding':{'issuer':'Fake Issuer Corporation'},'fact_ref':fact,'frozen_account_identity_ref':ident,'prior_raw_close':{'prior_date':'2025-02-07','raw_close':100.,'raw_row_present':True},'original_unsupported_keys':[{'ticker':'FAKE','effective_date':'2025-02-10'}]}
 bridge=dict(schema='V38_EXACT_DATED_ORIGINAL_UID_RAW_NAMESPACE_BRIDGE_R1',ticker='FAKE',ex_date='2025-02-10',prior_date='2025-02-07',original_fact_ref=fact,original_frozen_identity_ref=ident,original_security_id=sid,accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.FAKE',security_uid='CUSIP:123456789',same_pre_ex_and_ex_UID_and_SID=True,prior_raw_close_current_matches_legacy=True,raw_row_present=True,source_coordinate='RAW_ACTUAL_SHARE',source_refs=dict(calendar_ref=cal,dated_identity_ref=dated,mapping_ref=mp,identity_projection_ref=ip,raw_price_ref=raw),identity_links=[dict(ticker='FAKE',signal_date=d,security_uid='CUSIP:123456789',accounting_sid='FROZEN_RAW_TRANSPORT_CODE:US.FAKE') for d in ('2025-02-07','2025-02-10')],**{k:False for k in ('issuer_CIK_is_security_UID','new_legal_CUSIP_authority','old_source_producer_relabelled','payload_security_id_rewritten','share_quantity_effect')})
 return SimpleNamespace(_frozen_ca_module=ca),event,entry,{'original_source_row':{'cusip':'123456789'}},bridge

@pytest.mark.parametrize('case',[None,'changed_source','changed_sid','changed_uid','changed_close','wrong_class_role','quantity_effect','rewritten_payload','ticker_reuse','changed_native_typed','changed_native_fp','missing_stats','no_minmax','future_append'])
def test_post_native_cash_mapping_only_changes_event_namespace(generated,case,monkeypatch):
 owner,event,entry,identity,bridge=generated;original=asdict(event)
 native=dict(original_fact_ref=copy.deepcopy(entry['fact_ref']),original_typed_event=asdict(event),original_event_fingerprint=event.event_fingerprint,original_payload_unchanged=True,native_economic_fields_unmodified=True)
 if case=='changed_source':bridge['original_fact_ref']['sha256']='f'*64;entry=copy.deepcopy(entry);entry['fact_ref']['sha256']='e'*64
 elif case=='changed_sid':bridge['accounting_sid']='CUSIP:987654321'
 elif case=='changed_uid':identity['original_source_row']['cusip']='987654321'
 elif case=='changed_close':entry['prior_raw_close']['raw_close']=99.
 elif case=='wrong_class_role':bridge['new_legal_CUSIP_authority']=True
 elif case=='quantity_effect':bridge['share_quantity_effect']=True
 elif case=='rewritten_payload':bridge['payload_security_id_rewritten']=True
 elif case=='ticker_reuse':bridge['ticker']='OTHER'
 elif case=='changed_native_typed':native['original_typed_event']['cash_per_old_share']=.5
 elif case=='changed_native_fp':native['original_event_fingerprint']='0'*64
 elif case in ('missing_stats','future_append'):
  p=Path(bridge['source_refs']['raw_price_ref']['path']);rows=[{'ticker':'FAKE','trade_date':pd.Timestamp('2025-02-07'),'close':100.}]
  if case=='future_append':rows.append({'ticker':'FAKE','trade_date':pd.Timestamp('2026-01-02'),'close':9999.})
  pq.write_table(pa.Table.from_pylist(rows),p,write_statistics=case!='missing_stats');bridge['source_refs']['raw_price_ref']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
 elif case=='no_minmax':
  old_pf=pq.ParquetFile
  def fake_pf(p,*a,**kw):
   if Path(p)!=Path(bridge['source_refs']['raw_price_ref']['path']):return old_pf(p,*a,**kw)
   col=SimpleNamespace(path_in_schema='trade_date',statistics=SimpleNamespace(has_min_max=False,min=None,max=None))
   group=SimpleNamespace(num_columns=1,column=lambda j:col)
   return SimpleNamespace(metadata=SimpleNamespace(num_row_groups=1,row_group=lambda j:group))
  monkeypatch.setattr(pq,'ParquetFile',fake_pf)

 if case is not None:
  with pytest.raises(ValueError):source._post_native_cash_raw_namespace(owner,event,entry,identity,bridge,native_proof=native)
  return
 new,proof=source._post_native_cash_raw_namespace(owner,event,entry,identity,bridge,native_proof=native)
 assert asdict(event)==original and new.old_security_id==bridge['accounting_sid']
 assert proof['original_typed_event']==original
 assert proof['original_event_fingerprint']==event.event_fingerprint!=new.event_fingerprint
 assert all(getattr(event,k)==getattr(new,k) for k in ('cash_per_old_share','record_date','pay_date','available_at','source_fingerprint','reconstruction_ref','reconstruction_sha256','amount_unit','quantity_coordinate'))
 assert proof['cash_economic_fields_unchanged'] and proof['original_small_cash_adjudication_preserved_with_identical_raw_endpoint']
