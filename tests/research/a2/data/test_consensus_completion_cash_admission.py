"""Generated admission composition only; no real source qualification or I/O."""
from copy import deepcopy

import pytest
from scripts.research.a2.data import consensus_account_inputs as inputs

ca = inputs.existing.ca


def event(event_id, ticker, day, token, amount=.2):
    projection = 'D:/generated_only/' + event_id + '.json'
    return ca.ResearchReconstructedCashEvent(
        event_id=event_id, action_type='CASH_DIVIDEND',
        old_security_id='GENERATED_RAW:' + ticker, ticker=ticker,
        ex_date=day, record_date=day, pay_date='2025-06-06',
        available_at=None, cash_per_old_share=amount, currency='USD',
        amount_unit=ca.USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=ca.RAW_OLD_SHARE_COORDINATE,
        source_type='TIER2_LOCAL_CANONICAL', source_reference=projection,
        source_fingerprint=token * 64, reconstruction_ref=projection,
        reconstruction_sha256=token * 64,
        source_scope='B_FROZEN_PRE2026_ACCOUNTING_ONLY')


def admission(events, token):
    value = dict(
        schema='B_FROZEN_HISTORY_POST_VERIFIED_CASH_ADMISSION_V1',
        scientific_identity='FROZEN_HISTORY_RESEARCH_ACCOUNT',
        task_id='V24_B_FAST_TRACK_PAIR_COMPLETION_R1',
        clock_role='POST_VERIFIED_ACCOUNTING_ONLY',
        accounting_clock_convention='ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION',
        scope_start='2023-01-01', scope_end_exclusive='2026-01-01',
        strict_PIT=False, production_qualified=False, quote_qualified=False,
        certified_NAV=False,
        source_contract_ref=dict(path='D:/generated_only/contract_' + token + '.json', sha256=token * 64),
        source_binding_fingerprint=token * 64,
        events=[dict(event_fingerprint=e.event_fingerprint,
                     source_projection_ref=dict(path=e.reconstruction_ref, sha256=e.reconstruction_sha256),
                     publication_available_at=e.available_at,
                     historical_availability_qualified=False,
                     clock_role='POST_VERIFIED_ACCOUNTING_ONLY') for e in events])
    # This is the real owner validator, not a substitute for actual native source admission.
    ca._validate_frozen_history_cash_admission(events, value)
    return value


def bundle(events, cash_admission):
    mappings = {e.old_security_id: e.ticker for e in events}
    return dict(entitlement_events=tuple(events), unsupported_events=(),
                entitlement_security_tickers=mappings,
                entitlement_source_binding=dict(
                    source_fingerprint='f' * 64, security_tickers=mappings,
                    manifest=dict(removed_exact_original_keys=[])),
                research_account_authority=dict(frozen_history_cash_admission=cash_admission))


def test_reconstructed_admissions_merge_and_corroboration_preserves_original_fingerprint():
    old = event('old_cash', 'S', '2025-06-03', 'a')
    corroboration = event('new_corroboration', 'S', '2025-06-03', 'b')
    new = event('new_cash', 'T', '2025-06-04', 'c', .3)
    old_admission = admission((old,), 'd')
    new_admission = admission((corroboration, new), 'e')
    original = bundle((old,), old_admission)
    untouched = deepcopy(original)
    native = dict(events=bundle((corroboration, new), new_admission))
    manifest = dict(path='D:/generated_only/current_composition.json', sha256='9' * 64)
    result = inputs.merge_completion_descendant(original, native, manifest)
    fingerprints = {e.event_fingerprint for e in result['entitlement_events']}
    assert fingerprints == {old.event_fingerprint, new.event_fingerprint}
    assert corroboration.event_fingerprint not in fingerprints
    assert result['entitlement_events'][0] == old
    merged = result['research_account_authority']['frozen_history_cash_admission']
    ca._validate_frozen_history_cash_admission(result['entitlement_events'], merged)
    assert merged['source_contract_ref'] == manifest
    assert merged['task_id'] == old_admission['task_id']
    entries = {entry['event_fingerprint']: entry for entry in merged['events']}
    assert entries[old.event_fingerprint] == old_admission['events'][0]
    assert entries[new.event_fingerprint] == new_admission['events'][1]
    assert entries[old.event_fingerprint]['source_projection_ref']['path'] == old.reconstruction_ref
    assert entries[new.event_fingerprint]['source_projection_ref']['path'] == new.reconstruction_ref
    assert merged['source_binding_fingerprint'] != old_admission['source_binding_fingerprint']
    assert original == untouched


def test_individually_valid_generated_cash_or_admission_conflicts_are_rejected():
    old = event('old_cash', 'S', '2025-06-03', 'a')
    original = bundle((old,), admission((old,), 'd'))
    changed = event('contradictory_cash', 'S', '2025-06-03', 'b', .21)
    native = dict(events=bundle((changed,), admission((changed,), 'e')))
    manifest = dict(path='D:/generated_only/current_composition.json', sha256='9' * 64)
    with pytest.raises(ValueError, match='COMPLETION_CASH_SOURCE_CONFLICT_NO_CHOICE'):
        inputs.merge_completion_descendant(original, native, manifest)
    # Same typed event identity, but ambiguous admission provenance metadata.
    conflicting = admission((old,), 'e')
    conflicting['events'][0]['source_edition_metadata'] = 'different_generated_transport_annotation'
    ca._validate_frozen_history_cash_admission((old,), conflicting)
    with pytest.raises(ValueError, match='COMPLETION_CASH_ADMISSION_CONFLICT'):
        inputs.merge_completion_descendant(original, dict(events=bundle((old,), conflicting)), manifest)
    assert original['entitlement_events'] == (old,)
    assert 'source_edition_metadata' not in original['research_account_authority']['frozen_history_cash_admission']['events'][0]
