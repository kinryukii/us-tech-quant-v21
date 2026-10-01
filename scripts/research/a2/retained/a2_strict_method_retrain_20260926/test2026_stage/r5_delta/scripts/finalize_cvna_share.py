"""Exact-key CVNA split event closure proposal; parent ledger remains untouched."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
R4=HERE.parent/'r4_continuation'/'R4_FINAL_CANDIDATE_INPUT_GATE.parquet'
R3=Path(r'D:\us-tech-quant-results\A2_STRICT_METHOD_RETRAIN_20260926\results\test2026\identity_feature_application_20260926_r3')
OCC=HERE/'raw_share_events'/'CVNA_OCC_58924.pdf'
ALERT=HERE/'raw_share_events'/'CVNA_2026_05_07_MIAX.html'
PROXY=HERE/'raw_share_events'/'CVNA_2026_proxy.pdf'
FACTOR=Path(r'D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet')
assert all(p.exists() for p in [OCC,ALERT,PROXY,FACTOR])
prefix=json.loads((HERE/'SHARE_EVENT_PREFIX_CHECKS.json').read_text(encoding='utf-8'))
cvna=next(x for x in prefix if x['code']=='US.CVNA')
assert cvna['all_prefix_exact'] and cvna['factor_a']==0.2 and cvna['factor_b']==0.0
event=pd.read_parquet(R3/'CONSUMED_REHAB_EVENT_AUDIT.parquet',filters=[('original_code','==','US.CVNA')])
event=event.loc[event.event_date.eq(pd.Timestamp('2026-05-08'))]
assert len(event)==1 and bool(event.share_event.iloc[0]) and event.factor_a.iloc[0]==0.2
block=pq.read_table(R4,filters=[('moomoo_transport_code','==','US.CVNA')]).to_pandas()
block=block.loc[block.signal_date.ge(pd.Timestamp('2026-05-08'))].copy()
assert len(block)==94 and block.signal_date.max()==pd.Timestamp('2026-09-22')
assert block.cusip.eq('146869102').all() and block.title_of_class.eq('CL A').all()
assert block.first_consumed_2026_event.eq(pd.Timestamp('2026-05-08')).all()
assert block.final_input_gate.eq('UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME').all()
for col in ['raw_on_signal','rehab_pass','coordinate_match','lookback_121_eligible','has_32_finite','version_checked']:
    assert block[col].fillna(False).astype(bool).all(),col
for col in ['multi_cusip_transport_interval_pending','proven_lifecycle_ineligible','proven_121_ineligible','unexplained_raw_jump_dependency','no_frozen_coordinate_overlap']:
    assert not block[col].fillna(False).astype(bool).any(),col
key=['cusip','title_of_class','quarter','signal_date','ticker','moomoo_transport_code']
assert not block.duplicated(key).any()
block['r4_event_public_ratio_proven']=True
block['r4_event_issuer_proxy_sha256']=hashlib.sha256(PROXY.read_bytes()).hexdigest()
block['r4_event_exchange_alert_sha256']=hashlib.sha256(ALERT.read_bytes()).hexdigest()
block['r4_event_occ_original_sha256']=hashlib.sha256(OCC.read_bytes()).hexdigest()
block['r4_consumed_factor_a']=0.2
block['r4_consumed_factor_b']=0.0
block['r4_event_effective_date']='2026-05-08'
block['r4_event_result']='PUBLIC_5_FOR_1_CLASS_A_SPLIT_AND_CONSUMED_VALUE_REPRODUCED'
block['r4_input_result_subject_to_parent_gate']='INPUT_VERIFIED_THIS_GATE'
block[key+['r4_event_public_ratio_proven','r4_event_issuer_proxy_sha256','r4_event_exchange_alert_sha256','r4_event_occ_original_sha256','r4_consumed_factor_a','r4_consumed_factor_b','r4_event_effective_date','r4_event_result','r4_input_result_subject_to_parent_gate']].to_parquet(HERE/'CVNA_94_SHARE_EVENT_EXACT_KEY_PASS_OVERLAY.parquet',index=False)
report={
 'event':'CVNA 5-for-1 Class A forward split','event_ex_date':'2026-05-08','issuer_proxy_filed_date':'2026-03-25','exchange_alert_date':'2026-05-07','OCC_memo_date':'2026-05-07',
 'issuer_proxy_original_url':'https://investors.carvana.com/~/media/Files/C/Carvana-IR/documents/carvana-co-2026-proxy-statement-definitive.pdf',
 'exchange_alert_original_url':'https://www.miaxglobal.com/alert/2026/05/07/miax-exchange-group-options-markets-corporate-action-alert-carvana-co-cvna-0',
 'OCC_memo_original_url':'https://www.miaxglobal.com/sites/default/files/alert-files/CVNA_Split_58924.pdf',
 'issuer_proxy_sha256':hashlib.sha256(PROXY.read_bytes()).hexdigest(), 'exchange_alert_sha256':hashlib.sha256(ALERT.read_bytes()).hexdigest(), 'OCC_memo_sha256':hashlib.sha256(OCC.read_bytes()).hexdigest(),
 'original_cusip_and_class':'146869102 CL A','OCC_deliverable_cusip_and_class':'146869102 Class A Common','original_rehab_snapshot_sha256':hashlib.sha256(FACTOR.read_bytes()).hexdigest(),
 'consumed_factor_a':0.2,'consumed_factor_b':0.0,'share_event':True,'original_full_vs_prefix_32_features':cvna['checks'],
 'exact_candidate_keys_proposed_pass':len(block),'first_signal':str(block.signal_date.min().date()),'last_signal':str(block.signal_date.max().date()),
 'all_other_r4_input_checks_true':True,'historical_vendor_version_receipt_proven':False,'parent_ledger_modified':False,
 'interpretation':'Original forward-only adjustment uses A=0.2/B=0 for the 5-for-1 Class A split on the public ex-distribution date. The May 7 OCC primary memo confirms ex-date, ratio and the unchanged original Class A CUSIP; issuer proxy predates event. No prior 2026 adjustment event exists for CVNA. All 94 fixed-window original candidate keys pass other r4 checks; exact prefix 32-feature results match the full build. This supports an event-dependency closure proposal under the original contract, while actual historical vendor receipt remains unobserved.'}
(HERE/'CVNA_94_SHARE_EVENT_VERDICT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'keys':len(block),'first':report['first_signal'],'last':report['last_signal'],'sha':report['OCC_memo_sha256']},indent=2))
