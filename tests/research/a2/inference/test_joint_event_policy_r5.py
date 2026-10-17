"""Synthetic event receipts only; no files/data/models/accounts are consumed."""
from dataclasses import fields, replace
from pathlib import Path
import importlib.util
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import joint_event_policy_r5 as ep
from scripts.research.a2.inference import joint_frozen_history_policy_r3 as parent
from scripts.research.a2.portfolio import shared_joint_adapter_r2 as ad
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

_spec=importlib.util.spec_from_file_location('_event_parent_synthetic_fixture',
    Path(__file__).with_name('test_joint_frozen_history_policy_r3.py'))
_fixture=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_fixture)


def make(prediction='P0',q='Q0',action='A0',gross='G0',cost=10,
         fit='2024-02-01T00:00:00Z',decision='2024-02-08T00:00:00Z',risk='RD'):
    old,data,ctx=_fixture.make(prediction,q,action,gross,cost)
    prior=replace(old.contract.rows[0],risk=risk)
    family=ep.PARENT_FAMILIES[risk]
    method='R5_'+family+'_EVENT_WITH_HP_COMPLETION'
    b=ep.EventMethodBinding(risk,method,family,'EVENT_CLASSICAL_WITH_PRIOR_COMPLETION',
        'b'*64,'a'*64,'BLOCKED_UNBOUND_HORIZONS' if risk=='RM' else 'READY')
    kwargs={f.name:getattr(old.activation,f.name) for f in fields(ad.FrozenMechanismActivation)}
    kwargs['allowed_risk_methods']=(method,)
    act=ep.FrozenEventMechanismActivation(**kwargs,method_bindings=(b,),bank_manifest_sha256='9'*64,
        event_source_sha256=ep.source_pins())
    fit=pd.Timestamp(fit); decision=pd.Timestamp(decision)
    sessions=pd.DatetimeIndex(data.risk_use_receipt.legal_sessions)
    cutoff=sessions[sessions.get_indexer([fit])[0]-1]
    receipt=dict(data.risk_state.source_receipt,cutoff=str(cutoff),available_at=str(cutoff))
    coverage={a:dict(uid='uid-'+a,identity_epoch='epoch-'+a) for a in data.risk_state.assets}
    state=replace(data.risk_state,as_of=fit,cutoff=cutoff,source_receipt=receipt,method=method,coverage=coverage)
    uids={a:coverage[a]['uid'] for a in state.assets}; epochs={a:coverage[a]['identity_epoch'] for a in state.assets}
    support={'dependency_local_event_ids':{'PRIMARY':'synthetic-epoch-1'},'source_sha256':receipt['source_sha256']}
    identity=ep.event.structural_identity(assets=state.assets,uids=uids,epochs=epochs,
        security_coordinate=state.return_coordinate,source_support_identity=support)
    state=replace(state,notes={'event_policy_binding':dict(parent_risk=risk,
        representation=b.representation,recipe_sha256=b.recipe_sha256,model_producer_sha256=b.producer_sha256,
        structural_identity=identity,source_support_identity_sha256=content_hash(support),
        asset_uid_epoch_sha256=content_hash(dict(uids=uids,epochs=epochs)))})
    use=ep.EventRiskStateUseReceipt(state.risk_state_id,ad.risk_state_sha256(state),
        ad.FrozenSourceBinding.from_receipt(receipt),state.assets,state.identity_epoch,method,str(fit),str(cutoff),
        '',data.risk_use_receipt.legal_sessions,witness=ep.event.EventWitness(str(decision),identity,identity,True,True),
        bank_manifest_sha256=act.bank_manifest_sha256,model_producer_sha256=b.producer_sha256,
        asset_uids=uids,asset_epochs=epochs,source_support_identity=support,representation=b.representation,
        parent_risk=risk,recipe_sha256=b.recipe_sha256).seal()
    row=replace(prior,risk=method)
    kwargs={f.name:getattr(old.contract,f.name) for f in fields(parent.FrozenFamilyPolicyContract)}
    kwargs['rows']=(row,)
    contract=ep.FrozenEventFamilyPolicyContract(**kwargs,parent_rows=(prior,),parent_policy_binding_sha256='6'*64,
        parent_rows_sha256=content_hash((prior,)),contrast_binding_sha256='7'*64,event_source_sha256=ep.source_pins())
    ctx=replace(ctx,signal_asof=decision,signal_date=decision)
    master=tuple(ctx.tickers)
    pool=ep.CurrentEventRiskPoolReceipt(master,state.assets,str(decision),state.identity_epoch,(),(),(),
        contract.source_contract_sha256,current_pool_asof=str(decision),
        current_accepted_features=(True,)*len(state.assets)+(False,),
        current_raw_rows=(True,)*len(state.assets)+(False,),current_uids=tuple(uids.values())+(None,),
        current_epochs=tuple(epochs.values())+(None,),source_support_identity=support)
    f=replace(data.forecast,signal_asof=str(decision))
    data=replace(data,forecast=f,expected_forecast_sha256=f.digest(),risk_state=state,risk_use_receipt=use,
        expected_risk_use_sha256=use.frozen_sha256,pool_receipt=pool,expected_pool_sha256=pool.digest(),
        prior_cutoff=str(sessions[sessions.get_indexer([decision])[0]-1]))
    def provider(day,row,local): return data
    obj=ep.EventFamilyPolicy(contract,expected_contract_sha256=contract.digest(),activation=act,
        expected_activation_sha256=act.digest(),token=old.token,expected_token_sha256=old.token.digest(),input_provider=provider)
    return obj,data,ctx,old


def evaluate(obj,data,ctx): return obj.evaluate(0,ctx.path_ids[0],ctx,data)

def qualified(obj,data,ctx):
    out=evaluate(obj,data,ctx)
    assert out.decision is not None,out.diagnostic
    assert out.physical_fit_count==out.account_replay_count==0
    assert not out.strict_PIT_promotion_eligible and not out.certified_NAV and not out.quote_qualified
    return out


@pytest.mark.parametrize('prediction',['P0','P1','P2'])
def test_exact_old_forecast_lineage_and_numeric_q_G_action_are_reused(prediction):
    obj,data,ctx,old=make(prediction)
    actual=qualified(obj,data,ctx)
    baseline=_fixture.evaluate(old,_fixture.make(prediction)[1],ctx)
    assert baseline.decision is not None,baseline.diagnostic
    np.testing.assert_allclose(actual.decision.weights,baseline.decision.weights,atol=1e-13)
    assert obj.contract.forecast_lineage==old.contract.forecast_lineage
    if prediction=='P2': assert actual.diagnostic['uncertainty_origin'].startswith(parent.P2_RMS_SEMANTIC)


def test_event_can_fit_off_native_refresh_and_carry_across_month_without_next_event():
    obj,data,ctx,_=make(fit='2024-02-12T00:00:00Z',decision='2024-03-05T00:00:00Z')
    qualified(obj,data,ctx)
    assert data.risk_use_receipt.next_refresh_as_of==''
    assert pd.Timestamp(data.pool_receipt.cutoff)>pd.Timestamp(data.risk_use_receipt.fit_cutoff)
    assert pd.Timestamp(data.prior_cutoff)>pd.Timestamp(data.risk_use_receipt.fit_cutoff)


@pytest.mark.parametrize('change',['structural','source','maturity','decision','model','bank','recipe','future_date','cutoff','calendar','proof','state_uid','epoch'])
def test_current_witness_model_source_uid_and_exact_clock_fail_closed(change):
    obj,data,ctx,_=make()
    use,state=data.risk_use_receipt,data.risk_state
    if change=='structural': use=replace(use,witness=replace(use.witness,current_structural_identity='8'*64))
    if change=='source': use=replace(use,witness=replace(use.witness,source_still_valid=False))
    if change=='maturity': use=replace(use,witness=replace(use.witness,maturity_still_valid=False))
    if change=='decision': use=replace(use,witness=replace(use.witness,decision_asof=use.fit_as_of))
    if change=='model': use=replace(use,model_producer_sha256='8'*64)
    if change=='bank': use=replace(use,bank_manifest_sha256='8'*64)
    if change=='recipe': use=replace(use,recipe_sha256='8'*64)
    if change=='future_date': use=replace(use,next_refresh_as_of='2024-03-01T00:00:00Z')
    if change=='cutoff': use=replace(use,fit_cutoff='2024-01-30T00:00:00Z')
    if change=='calendar': use=replace(use,legal_sessions=use.legal_sessions[1:])
    if change=='proof': state=replace(state,notes={})
    if change=='state_uid': state=replace(state,coverage={**state.coverage,state.assets[0]:dict(uid='other',identity_epoch=use.asset_epochs[state.assets[0]])})
    if change=='epoch': use=replace(use,asset_epochs={**use.asset_epochs,state.assets[0]:'changed'})
    use=replace(use,risk_state_sha256=ad.risk_state_sha256(state)).seal()
    out=evaluate(obj,replace(data,risk_state=state,risk_use_receipt=use,expected_risk_use_sha256=use.frozen_sha256),ctx)
    assert out.decision is None,out.diagnostic


@pytest.mark.parametrize('change',['pool_asof','prior_cutoff','naive','unknown_uid','duplicate_uid','unknown_epoch','shrink','source','legacy'])
def test_current_requested_pool_is_not_prior_fit_domain_or_unknown_identity(change):
    obj,data,ctx,_=make()
    pool=data.pool_receipt
    if change=='pool_asof': pool=replace(pool,current_pool_asof=str(data.risk_state.cutoff),cutoff=str(data.risk_state.cutoff))
    if change=='prior_cutoff': data=replace(data,prior_cutoff=str(ctx.signal_asof))
    if change=='naive': pool=replace(pool,current_pool_asof='2024-02-08',cutoff='2024-02-08')
    if change=='unknown_uid': pool=replace(pool,current_uids=('UNKNOWN',)+pool.current_uids[1:])
    if change=='duplicate_uid': pool=replace(pool,current_uids=(pool.current_uids[1],)+pool.current_uids[1:])
    if change=='unknown_epoch': pool=replace(pool,current_epochs=('?',)+pool.current_epochs[1:])
    if change=='shrink': pool=replace(pool,current_accepted_features=(False,)+pool.current_accepted_features[1:])
    if change=='source': pool=replace(pool,source_support_identity={'different':'source'})
    if change=='legacy': pool=replace(pool,prior_accepted_features=(True,))
    out=evaluate(obj,replace(data,pool_receipt=pool,expected_pool_sha256=pool.digest()),ctx)
    assert out.decision is None,out.diagnostic


@pytest.mark.parametrize('required',['units','weight','eligible'])
def test_actual_held_or_buy_eligible_outside_bank_never_shrinks_to_cash(required):
    obj,data,ctx,_=make()
    if required=='units':
        a=ctx.current_units.copy(); a[0,-1]=1; ctx=replace(ctx,current_units=a)
    elif required=='weight':
        a=ctx.current_weights.copy(); a[0,-1]=.01; ctx=replace(ctx,current_weights=a)
    else:
        a=ctx.buy_allowed.copy(); b=ctx.decision_mask.copy(); a[0,-1]=b[0,-1]=True
        ctx=replace(ctx,buy_allowed=a,decision_mask=b)
    out=evaluate(obj,data,ctx)
    assert out.decision is None and out.diagnostic['missing_required_risk_assets']==('INACTIVE_OUTSIDE_POOL',)


@pytest.mark.parametrize('cost',[5,10,20])
@pytest.mark.parametrize('q,action,gross',[('Q0','A0','G0'),('Q1','A1','G1'),('Q3','A2','G2')])
def test_parent_recipe_cost_and_path_current_state_transport_unchanged(cost,q,action,gross):
    obj,data,ctx,old=make(q=q,action=action,gross=gross,cost=cost)
    actual=qualified(obj,data,ctx)
    _,olddata,_=_fixture.make(q=q,action=action,gross=gross,cost=cost)
    baseline=_fixture.evaluate(old,olddata,ctx)
    assert baseline.decision is not None,baseline.diagnostic
    np.testing.assert_allclose(actual.decision.weights,baseline.decision.weights,atol=1e-13)
    assert obj.friction_contract(ctx.path_ids[0])['one_way_bps']==cost


def test_rm_unbound_horizons_remain_typed_block_not_hp_substitute():
    obj,data,ctx,_=make(risk='RM')
    out=evaluate(obj,data,ctx)
    assert out.decision is None and out.diagnostic['block_reason']=='BLOCKED_UNBOUND_HORIZONS'


def test_q2_without_typed_genuine_tail_scenarios_remains_blocked():
    obj,data,ctx,_=make(q='Q2')
    out=evaluate(obj,data,ctx)
    assert out.decision is None and 'SCENARIO' in out.diagnostic['block_reason']


def test_primary_hp_cannot_replace_unrelated_classical_family():
    obj,_,_,_=make()
    b=obj.activation.method_bindings[0]
    with pytest.raises(parent.FamilyPolicyBlocked,match='CLASSICAL_FAMILY'):
        replace(b,representation='EVENT_HIERARCHICAL_PRIOR').validate()
    with pytest.raises(parent.FamilyPolicyBlocked,match='RELATED_EVENT'):
        replace(b,family='SHR_HP').validate()


def test_support_token_never_starts_account_and_no_business_implementation_is_added():
    obj,data,ctx,_=make()
    with pytest.raises(parent.FamilyPolicyBlocked,match='ACCOUNT_REPLAY_TOKEN'):
        obj(0,ctx)
    assert ep.EventFamilyPolicy.__call__ is parent.FrozenHistoryFamilyPolicy.__call__
    assert ep.EventFamilyPolicy.friction_contract is parent.FrozenHistoryFamilyPolicy.friction_contract


def test_mutated_activation_contract_and_parent_tuple_are_rejected():
    obj,data,ctx,_=make()
    obj.contract.forecast_lineage['P0:2024']=()
    assert evaluate(obj,data,ctx).decision is None
    obj,data,ctx,_=make()
    bad=replace(obj.contract,rows=(replace(obj.contract.rows[0],gross='G2'),))
    with pytest.raises(parent.FamilyPolicyBlocked,match='TUPLE_CHANGED'):
        ep.EventFamilyPolicy(bad,expected_contract_sha256=bad.digest(),activation=obj.activation,
            expected_activation_sha256=obj.activation.digest(),token=obj.token,expected_token_sha256=obj.token.digest(),
            input_provider=obj.provider)


@pytest.mark.parametrize('when',['2024-02-08','2025-12-31T23:30:00-05:00'])
def test_naive_or_utc_2026_decision_is_blocked(when):
    obj,data,ctx,_=make()
    assert evaluate(obj,data,replace(ctx,signal_asof=pd.Timestamp(when))).decision is None


@pytest.mark.parametrize('family',['OAS','CONSTANT_CORRELATION','PCA_FACTOR','TAIL_CVAR'])
def test_additional_bank_families_have_explicit_bindings_without_expanding_parent_paths(family):
    b=ep.EventMethodBinding(family,'R5::'+family+'::prior_or_completion',family,
        'EVENT_CLASSICAL_WITH_PRIOR_COMPLETION','b'*64,'a'*64)
    b.validate()
    obj,_,_,_=make()
    assert len(obj.contract.rows)==len(obj.contract.parent_rows)==1


def test_estimator_explicit_colon_method_is_accepted_without_parent_name_alias():
    obj,data,ctx,_=make()
    method='R5::EWMA::prior_or_completion'
    b=replace(obj.activation.method_bindings[0],method=method)
    act=replace(obj.activation,method_bindings=(b,),allowed_risk_methods=(method,))
    row=replace(obj.contract.rows[0],risk=method)
    contract=replace(obj.contract,rows=(row,))
    state=replace(data.risk_state,method=method)
    use=replace(data.risk_use_receipt,method=method,risk_state_sha256=ad.risk_state_sha256(state)).seal()
    data=replace(data,risk_state=state,risk_use_receipt=use,expected_risk_use_sha256=use.frozen_sha256)
    obj=ep.EventFamilyPolicy(contract,expected_contract_sha256=contract.digest(),activation=act,
        expected_activation_sha256=act.digest(),token=obj.token,expected_token_sha256=obj.token.digest(),
        input_provider=lambda *args:data)
    qualified(obj,data,ctx)
