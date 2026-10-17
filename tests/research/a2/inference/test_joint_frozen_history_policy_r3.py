"""Only fabricated pre2026 inputs; direct common account reuse, no fitting/readers."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import joint_frozen_history_policy_r3 as policy
from scripts.research.a2.portfolio import shared_joint_adapter_r2 as ad
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.evaluation.joint_frozen_history_r3 import ACCOUNT
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays

# Only source-defined synthetic helpers are loaded; no pytest tests execute.
_helper=Path(__file__).resolve().parents[1]/'portfolio'/'test_shared_joint_adapter_r2.py'
_spec=importlib.util.spec_from_file_location('_family_synthetic_adapter_fixture',_helper)
_f=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_f)


def make(prediction='P0',q='Q0',action='A0',gross='G0',cost=10,mode='SUPPORT_DISCOVERY',risk='RD',allow_weak=False):
    (state,mu,sigma,ctx),activation,use=_f.mechanism_fixture("RD" if risk=="NONE" else risk)
    activation=replace(activation,allow_weak_prior_rms=allow_weak)
    state=replace(state,coverage={a:dict(uid='uid-'+a) for a in state.assets})
    use=replace(use,risk_state_sha256=ad.risk_state_sha256(state)).seal()
    master=tuple(state.assets)+('INACTIVE_OUTSIDE_POOL',)
    vectors=('current_units','current_weights','reserved_mask','buy_allowed','sell_restricted',
             'input_present','decision_mask','operational_mask')
    fields={name:np.concatenate((getattr(ctx,name),np.zeros((1,1),dtype=getattr(ctx,name).dtype)),axis=1) for name in vectors}
    ctx=replace(ctx,path_ids=('FAMILY_SYNTHETIC',),tickers=np.asarray(master),**fields)
    row=policy.FrozenFamilyRow(ctx.path_ids[0],prediction,risk,q,action,gross,cost,
        'MAIN' if cost==10 else 'SENSITIVITY_NO_SELECTION')
    refs=(policy.FrozenProducerRef('B_META_equal' if prediction=='P2' else 'EXISTING_'+prediction,
        '1'*64,'2'*64,'prior_OOF_error_RMS' if prediction=='P2' else 'stored_mu',
        policy.P2_RMS_SEMANTIC if prediction=='P2' else prediction+'_EXISTING_STORED_FORECAST'),)
    contract=policy.FrozenFamilyPolicyContract(activation.research_id,activation.run_id,
        activation.family_freeze_sha256,'d'*64,'e'*64,activation.scientific_contract_sha256,
        (row,),{prediction+':2024':refs},policy.source_pins())
    token=policy.FrozenFamilyPolicyToken(contract.research_id,contract.run_id,contract.family_freeze_sha256,
        (row.id,),mode)
    pool=policy.FrozenRiskPoolReceipt(master,state.assets,str(state.cutoff),state.identity_epoch,
        (True,)*len(state.assets)+(False,),(True,)*len(state.assets)+(False,),
        tuple('uid-'+a for a in state.assets)+(None,),contract.source_contract_sha256)
    p2=None
    if prediction=='P2':
        p2=replace(_f.frozen_oof(len(state.assets)),synthetic=False,status='PASS_FROZEN_HISTORY_MECHANISM',
            mechanism_source_receipt=dict(state.source_receipt)).seal()
        mu=np.asarray(p2.calibrated_mu).mean(axis=0)
    if risk=='NONE':
        mu=np.append(mu,np.nan); sigma=np.append(sigma,np.nan)
    forecast=policy.FrozenForecastSlice(prediction,master if risk=='NONE' else state.assets,str(ctx.signal_asof),str(state.cutoff),
        str(state.cutoff),tuple(mu),tuple(sigma),refs,contract.source_contract_sha256,
        contract.family_freeze_sha256,contract.prediction_clarification_sha256,
        ad.P2_MEMBERS if prediction in ('P1','P2') else ())
    inputs=policy.FamilyPolicyInputs(forecast,forecast.digest(),state,use,use.frozen_sha256,
        pool,pool.digest(),str(ctx.signal_asof-pd.Timedelta(days=1)),p2,p2.frozen_sha256 if p2 else '')
    def provider(day,row,local):
        f=replace(inputs.forecast,signal_asof=str(local.signal_asof))
        return replace(inputs,forecast=f,expected_forecast_sha256=f.digest(),
            prior_cutoff=str(pd.Timestamp(local.signal_asof)-pd.Timedelta(days=1)))
    obj=policy.FrozenHistoryFamilyPolicy(contract,expected_contract_sha256=contract.digest(),
        activation=activation,expected_activation_sha256=activation.digest(),token=token,
        expected_token_sha256=token.digest(),input_provider=provider)
    return obj,inputs,ctx


def evaluate(obj,inputs,ctx): return obj.evaluate(0,ctx.path_ids[0],ctx,inputs)


@pytest.mark.parametrize('prediction',['P0','P1','P2'])
def test_existing_alpha_roles_transport_exact_frozen_risk_domain_without_padding_or_refit(prediction):
    obj,inputs,ctx=make(prediction)
    result=evaluate(obj,inputs,ctx)
    assert result.status=='MECHANISM_POLICY_INPUTS_QUALIFIED_UNCERTIFIED',result.diagnostic
    assert result.decision.weights.shape==ctx.current_weights.shape
    assert not result.decision.explicit_mask[0,-1] and result.decision.weights[0,-1]==0
    assert result.diagnostic['transported_unknown_risk_cells']==0
    assert result.diagnostic['forecast_support_basis']=='ACTUAL_PIT_BUY_ELIGIBLE_UNION_HELD'
    assert result.physical_fit_count==result.account_replay_count==0
    assert not result.strict_PIT_promotion_eligible and not result.certified_NAV and not result.quote_qualified
    assert inputs.risk_state.covariance.shape==(len(ctx.tickers)-1,len(ctx.tickers)-1)
    if prediction=='P2':
        assert result.diagnostic['uncertainty_origin'].startswith(policy.P2_RMS_SEMANTIC)
        assert not result.diagnostic['calibrated_uncertainty_certified']


@pytest.mark.parametrize('required',['held','eligible'])
def test_any_actual_required_asset_outside_prior_frozen_risk_domain_blocks(required):
    obj,inputs,ctx=make()
    fields={}
    if required=='held':
        units=ctx.current_units.copy(); units[0,-1]=1.; fields['current_units']=units
    else:
        buy=ctx.buy_allowed.copy(); decision=ctx.decision_mask.copy()
        buy[0,-1]=decision[0,-1]=True; fields.update(buy_allowed=buy,decision_mask=decision)
    result=evaluate(obj,inputs,replace(ctx,**fields))
    assert result.decision is None and result.status=='BLOCKED_MECHANISM_POLICY'
    assert result.diagnostic['missing_required_risk_assets']==('INACTIVE_OUTSIDE_POOL',)


@pytest.mark.parametrize('mutation',['pool_shrink','uid_swap','pool_cutoff','full_state_block','covariance_padding'])
def test_no_label_based_pool_shrink_unknown_uid_padding_or_short_history_cash_fallback(mutation):
    obj,inputs,ctx=make()
    pool,state=inputs.pool_receipt,inputs.risk_state
    if mutation=='pool_shrink': pool=replace(pool,prior_accepted_features=(False,)+pool.prior_accepted_features[1:])
    if mutation=='uid_swap': pool=replace(pool,prior_known_uids=('other-uid',)+pool.prior_known_uids[1:])
    if mutation=='pool_cutoff': pool=replace(pool,cutoff='2024-01-30T00:00:00Z')
    if mutation=='full_state_block': state=replace(state,status='BLOCKED',covariance=None,notes={'block_reason':'FULL_POOL_SHORT_HISTORY'})
    if mutation=='covariance_padding': state=replace(state,covariance=np.eye(len(ctx.tickers)))
    result=evaluate(obj,replace(inputs,pool_receipt=pool,expected_pool_sha256=pool.digest(),risk_state=state),ctx)
    assert result.decision is None and result.status=='BLOCKED_MECHANISM_POLICY'
    assert result.account_replay_count==result.physical_fit_count==0


@pytest.mark.parametrize('mutation',['producer_field','producer_sha','source_contract','clarification','future_clock','prediction_role','members','promotion','body_sha'])
def test_frozen_forecast_exact_producer_receipt_column_clock_and_family_binding(mutation):
    obj,inputs,ctx=make('P1'); f=inputs.forecast
    if mutation=='producer_field': f=replace(f,producer_refs=(replace(f.producer_refs[0],value_field='member_sigma'),))
    if mutation=='producer_sha': f=replace(f,producer_refs=(replace(f.producer_refs[0],producer_sha256='7'*64),))
    if mutation=='source_contract': f=replace(f,source_contract_sha256='7'*64)
    if mutation=='clarification': f=replace(f,prediction_clarification_sha256='7'*64)
    if mutation=='future_clock': f=replace(f,available_at='2026-01-01T00:00:00Z')
    if mutation=='prediction_role': f=replace(f,prediction='P0')
    if mutation=='members': f=replace(f,members=f.members[:-1])
    if mutation=='promotion': f=replace(f,calibrated_uncertainty_certified=True)
    changed=replace(inputs,forecast=f,expected_forecast_sha256='0'*64 if mutation=='body_sha' else f.digest())
    assert evaluate(obj,changed,ctx).decision is None


def test_p2_does_not_use_member_bridge_sigma_or_reestimate_frozen_prior_oof_rms():
    obj,inputs,ctx=make('P2',gross='G2')
    clean=evaluate(obj,inputs,ctx)
    # Stored member sigma is neither equal prior OOF RMS nor a calibration claim.
    f=replace(inputs.forecast,uncertainty=(1e6,)*len(inputs.forecast.assets))
    changed=evaluate(obj,replace(inputs,forecast=f,expected_forecast_sha256=f.digest()),ctx)
    np.testing.assert_array_equal(clean.decision.weights,changed.decision.weights)
    p=replace(inputs.p2_receipt,prior_targets=tuple(tuple(_f._UnreadablePriorTarget() for _ in inputs.risk_state.assets)
        for _ in inputs.p2_receipt.origins))
    poison=evaluate(obj,replace(inputs,p2_receipt=p),ctx)
    np.testing.assert_array_equal(clean.decision.weights,poison.decision.weights)


@pytest.mark.parametrize('prediction',['P0','P1','P2'])
def test_inactive_forecast_nan_preserves_full_risk_pool_but_required_forecast_gap_blocks(prediction):
    obj,inputs,ctx=make(prediction)
    buy=ctx.buy_allowed.copy(); decision=ctx.decision_mask.copy(); buy[0,-2]=False; decision[0,-2]=False
    ctx=replace(ctx,buy_allowed=buy,decision_mask=decision)
    clean=evaluate(obj,inputs,ctx)
    f=replace(inputs.forecast,mu=inputs.forecast.mu[:-1]+(np.nan,),uncertainty=inputs.forecast.uncertainty[:-1]+(np.nan,))
    p=inputs.p2_receipt
    if p:
        current=np.asarray(p.calibrated_mu).copy(); current[:,-1]=np.nan
        p=replace(p,calibrated_mu=tuple(map(tuple,current)),frozen_prior_oof_rms=p.frozen_prior_oof_rms[:-1]+(np.nan,)).seal()
    dirty=evaluate(obj,replace(inputs,forecast=f,expected_forecast_sha256=f.digest(),p2_receipt=p,
        expected_p2_sha256=p.frozen_sha256 if p else ''),ctx)
    assert dirty.decision is not None,dirty.diagnostic
    np.testing.assert_array_equal(clean.decision.weights,dirty.decision.weights)
    f=replace(f,mu=(np.nan,)+f.mu[1:])
    assert evaluate(obj,replace(inputs,forecast=f,expected_forecast_sha256=f.digest()),ctx).decision is None


def test_q2_requires_exact_source_bound_true_h5_mature_scenarios():
    obj,inputs,ctx=make(q='Q2')
    assert evaluate(obj,inputs,ctx).decision is None
    scenario=_f.mechanism_scenarios(inputs.risk_state,inputs.risk_use_receipt)
    clean=evaluate(obj,replace(inputs,scenarios=scenario,expected_scenario_sha256=scenario.frozen_sha256),ctx)
    assert clean.decision is not None,clean.diagnostic
    bad=replace(scenario,horizon_sessions=3).seal()
    assert evaluate(obj,replace(inputs,scenarios=bad,expected_scenario_sha256=bad.frozen_sha256),ctx).decision is None


@pytest.mark.parametrize('cost',[5,10,20])
def test_q3_cost_sensitivity_matches_unchanged_common_account_friction_contract(cost):
    obj,inputs,ctx=make(q='Q3',cost=cost)
    result=evaluate(obj,inputs,ctx)
    assert result.decision is not None,result.diagnostic
    assert result.diagnostic['signal_turnover_penalty_bps']==cost
    assert result.diagnostic['account_execution_friction_bps']==obj.friction_contract(ctx.path_ids[0])['one_way_bps']==cost
    assert obj.friction_contract(ctx.path_ids[0])['fee_bps']==0


def test_support_discovery_token_cannot_replay_account_and_unregistered_path_is_typed_block():
    obj,inputs,ctx=make()
    with pytest.raises(policy.FamilyPolicyBlocked,match='ACCOUNT_REPLAY_TOKEN_REQUIRED'): obj(0,ctx)
    assert obj.evaluate(0,'not-registered',ctx).decision is None


def test_thin_family_policy_is_callable_by_same_continuous_account_on_fabricated_pre2026_inputs():
    obj,inputs,ctx=make(mode='ACCOUNT_REPLAY')
    dates=pd.bdate_range('2024-02-01',periods=7); prices=np.full((len(dates),len(ctx.tickers)),100.)
    flags=np.ones(prices.shape,bool); flags[:,-1]=False
    market=MarketArrays(dates,ctx.tickers,prices.copy(),prices.copy(),adv=np.full(prices.shape,1e8),
        input_present=flags,new_buy_eligible=flags,
        signal_asof=[(d+pd.Timedelta(hours=16)).tz_localize('America/New_York') for d in dates])
    replay=run_continuous_account(market,ctx.path_ids,obj,ACCOUNT,
        execution_friction=obj.friction_contract(ctx.path_ids[0]))
    assert len(obj.diagnostics)==len(dates) and not any('block_reason' in r for r in obj.diagnostics)
    assert replay.metadata['path_ids']==list(ctx.path_ids) or tuple(replay.metadata['path_ids'])==ctx.path_ids
    assert replay.daily.iloc[0].cash==3000 and not replay.accounting_exceptions.shape[0]
    assert all(d['source_authority']=='UNKNOWN' for d in obj.diagnostics)


@pytest.mark.parametrize('mutation',['unknown_requested_uid','unknown_dropped','duplicate_uid'])
def test_prior_requested_feature_raw_pool_never_drops_unknown_or_ambiguous_identity(mutation):
    obj,inputs,ctx=make(); p=inputs.pool_receipt
    if mutation=='unknown_requested_uid': p=replace(p,prior_known_uids=(None,)+p.prior_known_uids[1:])
    if mutation=='duplicate_uid': p=replace(p,prior_known_uids=(p.prior_known_uids[1],)+p.prior_known_uids[1:])
    if mutation=='unknown_dropped':
        p=replace(p,prior_accepted_features=p.prior_accepted_features[:-1]+(True,),
            prior_raw_rows=p.prior_raw_rows[:-1]+(True,))
    result=evaluate(obj,replace(inputs,pool_receipt=p,expected_pool_sha256=p.digest()),ctx)
    assert result.decision is None
    assert 'UNKNOWN_OR_AMBIGUOUS_UID' in result.diagnostic['block_reason']


@pytest.mark.parametrize('mutation',['lineage','source_sha'])
def test_mutable_mapping_inside_frozen_contract_cannot_change_after_construction(mutation):
    obj,inputs,ctx=make()
    if mutation=='lineage':
        refs=(replace(inputs.forecast.producer_refs[0],producer_sha256='9'*64),)
        obj.contract.forecast_lineage['P0:2024']=refs
        f=replace(inputs.forecast,producer_refs=refs)
        inputs=replace(inputs,forecast=f,expected_forecast_sha256=f.digest())
    if mutation=='source_sha': obj.contract.source_sha256[next(iter(obj.contract.source_sha256))]='9'*64
    result=evaluate(obj,inputs,ctx)
    assert result.decision is None and result.diagnostic['block_reason']=='FROZEN_FAMILY_CONTRACT_OR_TOKEN_MUTATION'
    with pytest.raises(policy.FamilyPolicyBlocked,match='CONTRACT_OR_TOKEN_MUTATION'):
        obj.friction_contract(ctx.path_ids[0])


def test_family_p2_never_relabels_bridge_fit_residual_as_equal_prior_genuine_oof_rms():
    obj,inputs,ctx=make('P2',allow_weak=True)
    p=replace(inputs.p2_receipt,genuine_chronological_oof=False,
        prior_rms_coverage='BRIDGE_IN_TRAINING_RESIDUAL_FROZEN_RMS').seal()
    result=evaluate(obj,replace(inputs,p2_receipt=p,expected_p2_sha256=p.frozen_sha256),ctx)
    assert result.decision is None
    assert result.diagnostic['block_reason']=='FAMILY_P2_REQUIRES_FROZEN_GENUINE_EQUAL_PRIOR_OOF_RMS'


@pytest.mark.parametrize('shape',['short','matrix','sigma_short'])
def test_p2_malformed_frozen_forecast_shape_returns_typed_block(shape):
    obj,inputs,ctx=make('P2'); f=inputs.forecast
    if shape=='short': f=replace(f,mu=f.mu[:-1])
    if shape=='matrix': f=replace(f,mu=(f.mu,))
    if shape=='sigma_short': f=replace(f,uncertainty=f.uncertainty[:-1])
    result=evaluate(obj,replace(inputs,forecast=f,expected_forecast_sha256=f.digest()),ctx)
    assert result.decision is None and result.diagnostic['block_reason']=='FORECAST_FULL_RISK_POOL_VECTOR_TOPOLOGY_REQUIRED'


@pytest.mark.parametrize('q',['RAW_FIXED_SCORE','SIMPLE_EQUAL'])
def test_raw_control_transport_never_converts_unused_inactive_forecast_sentinel(q):
    obj,inputs,ctx=make('RAW_RANK',q=q,risk='NONE')
    clean=evaluate(obj,inputs,ctx)
    assert clean.decision is not None,clean.diagnostic
    f=replace(inputs.forecast,mu=inputs.forecast.mu[:-1]+('INACTIVE_NOT_A_NUMBER',),
        uncertainty=inputs.forecast.uncertainty[:-1]+('INACTIVE_NOT_A_NUMBER',))
    dirty=evaluate(obj,replace(inputs,forecast=f,expected_forecast_sha256=f.digest()),ctx)
    assert dirty.decision is not None,dirty.diagnostic
    np.testing.assert_array_equal(clean.decision.weights,dirty.decision.weights)
    f=replace(f,mu=('REQUIRED_MISSING',)+f.mu[1:])
    assert evaluate(obj,replace(inputs,forecast=f,expected_forecast_sha256=f.digest()),ctx).decision is None
