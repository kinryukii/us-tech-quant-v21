"""Generated real typed terminal+cash composition; no data/replay/source admission."""
from copy import deepcopy
from dataclasses import asdict,replace
import hashlib
from pathlib import Path
import pytest
from scripts.research.a2.data import consensus_account_inputs as inputs
ca=inputs.existing.ca
fixture_path=Path(__file__).with_name('test_consensus_completion_cash_admission.py')
fixtures=inputs.existing._load_python(dict(path=str(fixture_path),sha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest()),'_consensus_generated_cash_admission_fixtures')
MANIFEST=dict(path='D:/generated_only/terminal_completion.json',sha256='9'*64)

def terminal():
 return ca.ResearchReconstructedTerminalEvent(event_id='retained_terminal',old_security_id='GENERATED_RAW:TERM',ticker='TERM',effective_at='2025-06-05T09:30:00-04:00',available_at=None,cash_per_old_share=12.5,currency='USD',amount_unit=ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,quantity_source_reference='D:/generated_only/terminal_raw_quantity.json',quantity_source_fingerprint='c'*64,source_type='TIER2_LOCAL_CANONICAL',source_reference='D:/generated_only/terminal_source.json',source_fingerprint='a'*64,reconstruction_ref='D:/generated_only/terminal_reconstruction.json',reconstruction_sha256='b'*64)

def retained_bundle(cash,term):
 value=fixtures.bundle((cash,term),fixtures.admission((cash,),'d'))
 # Existing qualification is a caller precondition. This generated opaque seal
 # only tests preservation; it never claims a real source admission.
 value['research_account_authority']['terminal_source_authority']=dict(generated=True,event_fingerprints=[term.event_fingerprint],original_admission_ref=dict(path='D:/generated_only/terminal_admission.json',sha256='f'*64))
 return value

def test_real_typed_terminal_cash_merge_preserves_original_source_and_admissions():
 old=fixtures.event('old_cash','S','2025-06-03','a');term=terminal();assert not hasattr(term,'ex_date')
 original=retained_bundle(old,term);before=deepcopy(original)
 corroboration=fixtures.event('cash_corroboration','S','2025-06-03','b');new=fixtures.event('new_cash','T','2025-06-04','c',.3)
 native=fixtures.bundle((term,corroboration,new),fixtures.admission((corroboration,new),'e'))
 result=inputs.merge_completion_descendant(original,dict(events=native),MANIFEST);by_id={e.event_id:e for e in result['entitlement_events']}
 assert set(by_id)=={term.event_id,old.event_id,new.event_id}
 assert asdict(by_id[term.event_id])==asdict(term) and by_id[term.event_id].event_fingerprint==term.event_fingerprint
 assert result['research_account_authority']['terminal_source_authority']==before['research_account_authority']['terminal_source_authority']
 merged=result['research_account_authority']['frozen_history_cash_admission'];ca._validate_frozen_history_cash_admission(result['entitlement_events'],merged)
 entries={e['event_fingerprint']:e for e in merged['events']};assert set(entries)=={old.event_fingerprint,new.event_fingerprint}
 assert entries[old.event_fingerprint]==before['research_account_authority']['frozen_history_cash_admission']['events'][0]
 assert asdict(by_id[old.event_id])==asdict(old) and asdict(by_id[new.event_id])==asdict(new) and original==before

def test_unknown_terminal_and_cash_conflict_cannot_disappear_on_mixed_merge():
 old=fixtures.event('old_cash','S','2025-06-03','a');term=terminal();original=retained_bundle(old,term);before=deepcopy(original)
 unknown=replace(term,event_id='new_unknown_terminal',cash_per_old_share=13.);assert unknown.event_fingerprint!=term.event_fingerprint
 native=fixtures.bundle((unknown,),None)
 with pytest.raises(ValueError,match='COMPLETION_NONCASH_FACT_MUST_ALREADY_BE_QUALIFIED'):inputs.merge_completion_descendant(original,dict(events=native),MANIFEST)
 changed=fixtures.event('contradictory_cash','S','2025-06-03','b',.21);native=fixtures.bundle((term,changed),fixtures.admission((changed,),'e'))
 with pytest.raises(ValueError,match='COMPLETION_CASH_SOURCE_CONFLICT_NO_CHOICE'):inputs.merge_completion_descendant(original,dict(events=native),MANIFEST)
 assert original==before

def test_special_ten_uses_existing_effective_day_for_retained_terminal(monkeypatch):
 old=fixtures.event('old_cash','S','2025-06-03','a');term=terminal();original=retained_bundle(old,term);before=deepcopy(original);special=[]
 for i in range(10):
  event=ca.SourceBackedEntitlementEvent(event_id=f'generated_special_{i}',action_type='CASH_DIVIDEND',old_security_id=f'GENERATED_RAW:SP{i}',ticker=f'SP{i}',ex_date='2025-06-16',record_date='2025-06-16',pay_date='2025-06-20',available_at='2025-06-02T12:00:00Z',cash_per_old_share=.25,currency='USD',amount_unit=ca.USD_PER_RAW_OLD_SHARE,quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,source_type='TIER2_LOCAL_CANONICAL',source_reference=f'D:/generated_only/special_{i}.json',source_fingerprint=hashlib.sha256(f'generated_special_{i}'.encode()).hexdigest())
  special.append(dict(type=type(event).__name__,terms=asdict(event),event_fingerprint=event.event_fingerprint))
 catalogue=dict(schema='CONSENSUS_QUALIFIED_SPECIAL_ACCOUNT_CATALOGUE_R1',status='QUALIFIED_SOURCE_FACTS_PRE2026_ACCOUNTING_ONLY',events=special,corporate_action_replacements=[],resolved_unsupported_records=[])
 calls=[];effective_day=ca._entitlement_effective_day
 def observed(event):calls.append(event.event_id);return effective_day(event)
 monkeypatch.setattr(ca,'_entitlement_effective_day',observed)
 result=inputs.apply_special_completion(original,catalogue,MANIFEST);assert term.event_id in calls and not hasattr(term,'ex_date')
 by_id={e.event_id:e for e in result['entitlement_events']};assert len(by_id)==12 and asdict(by_id[term.event_id])==asdict(term)
 assert by_id[term.event_id].event_fingerprint==term.event_fingerprint and result['research_account_authority']==before['research_account_authority']
 assert asdict(by_id[old.event_id])==asdict(old) and original==before
