"""Ten cash-event exact-key proposal under the original forward-PIT contract.

No parent ledger is modified and no model/preprocessor is loaded.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

HERE=Path(__file__).resolve().parent
R4=HERE.parent/'r4_continuation'/'R4_FINAL_CANDIDATE_INPUT_GATE.parquet'
K=['cusip','title_of_class','quarter','signal_date','ticker','moomoo_transport_code']
first=pd.read_csv(HERE/'FIRST_TRANCHE_PRIMARY_EVENT_AND_VALUE_PROOF.csv')
first_ranges=pd.read_csv(HERE/'FIRST_TRANCHE_EVENT_ONLY_SAFE_INTERVALS.csv')
second=pd.read_csv(HERE/'SECOND_TRANCHE_PRIMARY_EVENT_VERDICTS.csv')
first_keys=pd.read_parquet(HERE/'FIRST_TRANCHE_291_EXACT_CANDIDATE_KEYS.parquet')
second_keys=pd.read_parquet(HERE/'SECOND_TRANCHE_294_EXACT_CANDIDATE_KEYS.parquet')
all_events=[]; all_keys=[]
finra='https://www.finra.org/rules-guidance/rulebooks/finra-rules/11140'
for code in sorted(set(first.original_code)|set(second.original_code)):
    is_first=code in set(first.original_code)
    if is_first:
        p=first.loc[first.original_code.eq(code)].iloc[0]
        r=first_ranges.loc[first_ranges.original_code.eq(code)].iloc[0]
        date=pd.Timestamp(r.first_event_date)
        stop=pd.Timestamp(r.first_next_unproved_event)
        amount=float(p.total_cash_div); prior=float(p.prior_raw_close)
        factor=float(p.factor_a); floor=float(p.simple_cash_floor_a_5)
        public=str(p.source_public_date); url=str(p.primary_source_url)
        body=HERE/'raw'/'AXP_2025_12_17.html' if code=='US.AXP' else None
        tier='SAVED_ISSUER_ORIGINAL_HTML' if body else 'DIRECT_PRIMARY_PAGE_RENDER_AND_SAVED_EXCERPT'
        explicit=code in {'US.FERG','US.ROP'}
        extra_url='https://www.ropertech.com/news-releases/news-release-details/correction-roper-technologies-inc' if code=='US.ROP' else ''
        keys=first_keys.loc[first_keys.moomoo_transport_code.eq(code),K].copy()
    else:
        p=second.loc[second.original_code.eq(code)].iloc[0]
        date=pd.Timestamp(p.event_date_from_vendor_rehab)
        stop=pd.Timestamp(p.next_unproved_event_exclusive)
        amount=float(p.cash_dividend); prior=float(p.prior_raw_close)
        factor=float(p.consumed_factor_a); floor=float(p.cash_floor5_factor_a)
        public=str(p.issuer_public_date); url=str(p.issuer_original_url)
        body=Path(p.issuer_original_path)
        tier='SAVED_ISSUER_ORIGINAL_BODY'
        explicit=code=='US.JPM' # Direct issuer history, separate from saved announcement.
        extra_url=str(p.direct_history_url) if code=='US.JPM' else ''
        keys=second_keys.loc[second_keys.moomoo_transport_code.eq(code),K].copy()
    assert public<str(date.date())
    assert amount/prior<0.25 and factor==floor
    assert body is None or body.exists()
    body_hash=hashlib.sha256(body.read_bytes()).hexdigest() if body else ''
    block=pq.read_table(R4,filters=[('moomoo_transport_code','==',code)]).to_pandas()
    block=block.loc[block.signal_date.ge(date)&block.signal_date.lt(stop)].copy()
    joined=keys.merge(block,on=K,how='inner',validate='one_to_one')
    assert len(joined)==len(keys)==len(block),(code,len(joined),len(keys),len(block))
    assert joined.first_consumed_2026_event.eq(date).all(),code
    assert joined.final_input_gate.eq('UNKNOWN_CONSUMED_2026_EVENT_PUBLICATION_TIME').all(),code
    for col in ['raw_on_signal','rehab_pass','coordinate_match','lookback_121_eligible','has_32_finite','version_checked']:
        assert joined[col].fillna(False).astype(bool).all(),(code,col)
    for col in ['multi_cusip_transport_interval_pending','proven_lifecycle_ineligible','proven_121_ineligible','unexplained_raw_jump_dependency','no_frozen_coordinate_overlap']:
        assert not joined[col].fillna(False).astype(bool).any(),(code,col)
    keys['event_code']=code;keys['event_date']=str(date.date());keys['next_unproved_event_exclusive']=str(stop.date())
    if code=='US.FERG':
        ex_basis='CONTEMPORANEOUS_ISSUER_EXDATE'
    elif code in {'US.JPM','US.ROP'}:
        ex_basis='RETROSPECTIVE_ISSUER_HISTORY_EXDATE_PLUS_FINRA_11140_B1'
    else:
        ex_basis='FINRA_11140_B1_NORMAL_RECORD_EQUALS_EXDATE_CORROBORATED_BY_ORIGINAL_VENDOR_EXDATE'
    keys['record_date']=str(date.date());keys['exdate_basis']=ex_basis
    keys['cash_amount_public_before_signal']=amount;keys['original_raw_prior_close']=prior;keys['consumed_factor_a']=factor;keys['factor_b']=0.0
    keys['source_public_date']=public;keys['source_url']=url;keys['source_body_sha256']=body_hash;keys['source_tier']=tier
    keys['historical_vendor_receipt_proven']=False
    keys['proposed_input_gate']='INPUT_VERIFIED_THIS_GATE'
    all_keys.append(keys)
    all_events.append({'event_code':code,'cusip':str(p.cusip),'title_of_class':str(p.title_of_class),'public_date':public,'record_date':str(date.date()),'original_vendor_exdate':str(date.date()),
                       'exdate_basis':keys.exdate_basis.iloc[0],'cash_amount':amount,'prior_raw_date':str(p.prior_raw_date)[:10],
                       'prior_raw_close':prior,'cash_to_prior_raw_close_pct':100*amount/prior,'consumed_factor_a':factor,'reproduced_floor5_factor_a':floor,
                       'source_url':url,'additional_direct_primary_url':extra_url,'source_tier':tier,'saved_original_body_sha256':body_hash,
                       'finra_rule_url':finra,'first_signal':str(keys.signal_date.min().date()),'last_signal':str(keys.signal_date.max().date()),
                       'next_unproved_event_exclusive':str(stop.date()),'exact_candidate_keys':len(keys),'all_other_r4_gates_pass':True,
                       'historical_vendor_receipt_proven':False,'proposed_gate_upgrade':len(keys)})

events=pd.DataFrame(all_events).sort_values('event_code')
overlay=pd.concat(all_keys,ignore_index=True)
assert len(overlay)==585 and not overlay.duplicated(K).any()
assert events.exact_candidate_keys.sum()==585
events.to_csv(HERE/'TEN_CASH_EVENTS_ORIGINAL_CONTRACT_VERDICTS.csv',index=False)
overlay.to_parquet(HERE/'TEN_CASH_EVENTS_585_EXACT_KEY_PASS_PROPOSAL.parquet',index=False)
summary={'events':10,'exact_unique_proposed_keys':len(overlay),'first_tranche_keys':291,'second_tranche_keys':294,
         'normal_cash_below_25_percent':True,'public_amount_and_record_before_first_signal':True,
         'original_vendor_exdate_equals_record_date':True,'cash_factor_floor5_exact':True,'all_other_r4_input_gates_pass':True,
         'independent_issuer_exdate_required_by_original_contract':False,'saved_original_http_bytes_required_by_original_contract':False,
         'historical_vendor_receipt_required_by_original_contract':False,'actual_vendor_historical_receipt_proven':False,
         'parent_ledger_modified':False,'model_fit_calls':0,'preprocessor_fit_calls':0,
         'limits':'Proposal stops before next unproved event on each code. FINRA 11140(b)(1) is the normal rule when definitive information was received sufficiently in advance; public announcements predate record dates and the original vendor ex-dates corroborate the normal designation. Issuer direct ex-date is separately identified and historical vendor actual receipt is not claimed.'}
(HERE/'TEN_CASH_EVENTS_ORIGINAL_CONTRACT_REPORT.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
print(events[['event_code','exact_candidate_keys','cash_to_prior_raw_close_pct','exdate_basis']].to_string(index=False))
