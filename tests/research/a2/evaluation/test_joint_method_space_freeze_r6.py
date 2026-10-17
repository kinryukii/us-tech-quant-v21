"""Synthetic source-only physical DAG and fail-closed freeze checks."""
from copy import deepcopy
import pandas as pd
import pytest
from scripts.research.a2.evaluation import joint_method_space_freeze_r6 as f
from scripts.research.a2.evaluation import joint_method_space_design_r6 as d

def events():
    return [dict(event_id=f'SYNTHETIC_E{i:02d}',decision_asof='2023-01-03T21:00:00+00:00',fit_history_cutoff='2022-12-30T21:00:00+00:00') for i in range(55)]

def test_parameter_components_are_actual_enumerated_nodes():
    nodes=f.fit_nodes(events());assert f.validate_dag(nodes)
    counts={k:sum(n['units'] for n in nodes if n['track']==k) for k in f.FIT_COMPONENTS}
    assert counts==f.FIT_COMPONENTS
    assert len(nodes)==2273
    assert sum(n['track']=='risk' and n['physical_kind']=='scaler' for n in nodes)==110
    assert sum(n['track']=='risk' and n['physical_kind']=='regime_threshold' for n in nodes)==55
    assert len({n['backend_group'] for n in nodes if n['track']=='sequence' and n['component'] not in ('TRAIN_ONLY_OBSERVED_WINDOW_SCALER',)})==200
    assert sum(n['track']=='sequence' and n['component']=='TRAIN_ONLY_OBSERVED_WINDOW_SCALER' for n in nodes)==48
    assert sum(n['track']=='fusion' and n['component']=='POINT_OR_SOFTMAX_HEAD' for n in nodes)==12
    assert sum(n['track']=='fusion' and n['component']=='EARLIER_GENUINE_COMPOSITE_OOF_ERROR_RMS' for n in nodes)==2

def test_dynamic_physical_alias_space_not_116_constant():
    days=pd.bdate_range('2023-01-03',periods=752).strftime('%Y-%m-%d').tolist()
    clock=dict(decision_dates=days,q_dates=days[:143])
    space=d.policy_space();solves,accounts,daily=f.policy_nodes(space,clock)
    n=len(space['physical_paths']);mpc=sum(p['specification'].get('action')=='MPC' for p in space['physical_paths'])
    assert len(solves)==n*143+mpc*752
    assert len(accounts)==n
    assert len({r['node_id'] for r in solves})==len(solves)
    assert all(r['status']=='BLOCKED_ACCOUNT' for r in accounts)
    assert all(r['carried_target']=='not EXACT optimizer reuse' for r in daily)
    proof=d.budget_proof(space,clock,f.FIT_COMPONENTS)
    assert proof['fits']==2273 and proof['policy_solves_upper']==len(solves)

def test_annual_shared_window_has_exact_conditional_dependency():
    nodes=f.fit_nodes(events())
    selected=[n for n in nodes if n['track']=='sequence' and n['phase']=='ANNUAL' and n['component']=='TRUNK']
    assert len(selected)==16
    for n in selected:
        group=n['conditional_dependency_groups'][0]
        assert group['rule']=='EXACT_SELECTED_WINDOW_ONE_OF_5_20_60'
        assert len(group['nodes'])==3
        assert len(n['dependencies'])==18

def test_cycle_duplicate_missing_and_conditional_missing_fail_closed():
    a=f._node('a','s','p','c','x');b=f._node('b','s','p','c','x',['a'])
    assert f.validate_dag([a,b])
    with pytest.raises(f.FreezeBlocked,match='DUPLICATE'):f.validate_dag([a,a])
    bad=deepcopy(a);bad['dependencies']=['b']
    with pytest.raises(f.FreezeBlocked,match='CYCLE'):f.validate_dag([bad,b])
    bad=deepcopy(a);bad['dependencies']=['unknown']
    with pytest.raises(f.FreezeBlocked,match='UNBOUND'):f.validate_dag([bad])
    bad=deepcopy(a);bad['conditional_dependency_groups']=[dict(nodes=['unknown'])]
    with pytest.raises(f.FreezeBlocked,match='UNBOUND'):f.validate_dag([bad])

def test_incomplete_support_and_registry_are_not_boolean_authority():
    missing=f.readiness(None)
    assert 'TYPED_ACCOUNT_UNAVAILABLE_PROOF_NOT_BOUND' in missing
    assert 'policy_provider_status_ref' in missing
    assert 'owner_final_code_refs' in missing
    with pytest.raises(f.FreezeBlocked,match='TRUE_BOOL'):f.readiness(dict(provider_ready=True,full_required_policy_qualified=True))

@pytest.mark.parametrize('value',[{},dict(source_ref='relative.json',sha256='0'*64),dict(source_ref='E:/forbidden.json',sha256='0'*64),dict(source_ref='F:/forbidden.json',sha256='0'*64),dict(source_ref='D:/a.py',sha256='0'*64,omit_body=True)])
def test_bad_physical_reference_never_opens_or_normalizes_away(value):
    with pytest.raises((ValueError,f.FreezeBlocked)):f.checked_ref(value)

def test_risk_context_count_change_is_not_silent_partial_budget():
    with pytest.raises(f.FreezeBlocked,match='55_BY_31'):f.fit_nodes(events()[:-1])

def unavailable():
    value=dict(schema='B_R6_POLICY_PROVIDER_UNAVAILABLE_V1',research_id=d.ID,status='BLOCKED_ACCOUNT',required_domain_preserved=True,
        full_required_support=dict(rows=1052972,qualified=530075,blocked=522897,reasons=dict(MISSING_EXACT_CURRENT_FEATURE_SECURITY_UID=522577,SOURCE_FEATURE_METADATA_UNQUALIFIED=320)),current_eligible_support=dict(rows=530075,qualified=530075,blocked=0,reasons={}))
    value.update({k:False for k in ('provider_ready','full_required_policy_qualified','real_account_admission','unknown_identity_backfill','future_identity_used','alpha_output_grants_policy_qualification','R5_numeric_economic_read','EF_access','provider_fetch','strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified')})
    value.update({k:0 for k in ('unqualified_keys_removed','estimator_fit_count','optimizer_policy_solve_count','account_mechanism_paths','test2026_reads')})
    return value

def test_real_negative_metadata_evidence_closes_binding_not_account():
    v=unavailable();assert f.validate_account_unavailable(v) is False
    for key in ('provider_ready','full_required_policy_qualified','real_account_admission','future_identity_used'):
        bad=deepcopy(v);bad[key]=True
        with pytest.raises(f.FreezeBlocked,match='FALSE'):f.validate_account_unavailable(bad)
    bad=deepcopy(v);bad['full_required_support']['blocked']=0
    with pytest.raises(f.FreezeBlocked,match='COUNTS'):f.validate_account_unavailable(bad)
    bad=deepcopy(v);bad['unqualified_keys_removed']=522897
    with pytest.raises(f.FreezeBlocked,match='ZERO'):f.validate_account_unavailable(bad)
