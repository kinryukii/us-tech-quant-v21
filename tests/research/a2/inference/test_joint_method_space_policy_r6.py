"""Fabricated policy inputs only; no account, source reader or real fits."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import joint_method_space_policy_r6 as p
from scripts.research.a2.evaluation.continuous_research_account import PersistentPolicyContext
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext,TargetDecision


def fixture(role='Q_MV',cost=10):
    space=p.design.policy_space();pid=next(r['path_id'] for r in space['roles'] if r['role']==role)
    if cost!=10:pid+=f'@{cost}bps'
    row=next(r for r in space['physical_paths'] if r['path_id']==pid)
    assets=tuple('S'+str(i) for i in range(12));n=len(assets);zeros=np.zeros((1,n));truth=np.ones((1,n),bool);false=~truth
    common=AccountContext(0,pd.Timestamp('2024-01-03'),pd.Timestamp('2024-01-03T21:00:00Z'),(pid,),np.asarray(assets),zeros.copy(),zeros.copy(),np.array([3000.]),np.array([1.]),np.array([3000.]),false.copy(),np.array([0.]),np.array([0]),np.array([1.]),np.array([20]),truth.copy(),false.copy(),truth.copy(),truth.copy(),false.copy(),20,.1,1.)
    ctx=PersistentPolicyContext(common,zeros.copy(),np.full((1,n),np.datetime64('NaT','ns')),zeros.copy(),zeros.copy(),zeros.copy())
    contract=p.MethodSpacePolicyContract(p.design.ID,'SYNTHETIC_R6','a'*64,'b'*64,(row,),('2024-01-03','2024-01-04','2024-02-01'),('2024-01-03','2024-02-01'),p.source_pins())
    obj=p.MethodSpacePolicy(contract,expected_contract_sha256=contract.digest())
    uids={a:'UID-'+a for a in assets};epochs={a:'E1' for a in assets}
    s=p.PolicySupportReceipt(p.design.ID,contract.source_sha256,str(ctx.signal_asof),'2024-01-02T21:00:00Z',assets,assets,uids,epochs,assets,'c'*64,'d'*64,'SYNTHETIC_SUPPORT','e'*64,'f'*64,asset_sids={a:'SID-'+a for a in assets},security_coordinate='RAW_FRACTIONAL_SECURITY_SHARES')
    spec=row['specification'];prediction=spec.get('prediction','RAW_RANK')
    mu=np.full(n,.012);sigma=np.full(n,.003)
    f=p.PolicyForecast(prediction,assets,uids,epochs,str(ctx.signal_asof),'2023-12-30T21:00:00Z','2024-01-02T21:00:00Z',contract.source_sha256,'1'*64,'2'*64,not bool(spec.get('control')),mu,sigma,mu-sigma,np.full(n,.001),forecast_semantic='FROZEN_RAW_A2_RANK_NO_FIT' if spec.get('control') else 'GENUINE_OOF_OPPORTUNITY')
    riskmethod=spec.get('risk','AVERAGE')
    notes=dict(source_sha256=contract.source_sha256,asset_uids=uids,identity_epochs=epochs,cutoff=s.history_cutoff,as_of=s.signal_asof,risk_support_identity=s.risk_support_identity)
    cov=np.eye(n)*.0001
    state=p.risk_owner.RiskEstimate('R6::'+riskmethod+'::COMPLETE_DOMAIN',assets,cov,'PASS_SYNTHETIC','COVARIANCE',notes)
    scenarios=np.random.default_rng(62).normal(.004,.01,(40,n))
    sr=dict(assets=assets,asset_uids=uids,identity_epochs=epochs,source_sha256=contract.source_sha256,genuine_mature_joint_scenarios=True,mature_max='2024-01-01T21:00:00Z',payload_sha256=p.content_hash(scenarios))
    data=p.MethodSpacePolicyInputs(s,f,f.digest(),state,p.content_hash(state),scenarios=scenarios,scenarios_receipt=sr,prior_scale=.01,gross_inputs=dict(downside_vol=.05,cvar=.01,disagreement=.1),drawdown=0.)
    return obj,data,ctx


def next_day(data,ctx,index=1,date='2024-01-04',current=None):
    asof=pd.Timestamp(date+'T21:00:00Z');common=replace(ctx.common,signal_index=index,signal_date=pd.Timestamp(date),signal_asof=asof)
    if current is not None:
        w=np.asarray(current)[None,:];units=(w>0).astype(float)
        common=replace(common,current_weights=w,current_units=units,cash_weight=np.array([1-w.sum()]),cash=np.array([3000*(1-w.sum())]))
        ctx=replace(ctx,current_units=units)
    ctx=replace(ctx,common=common)
    s=replace(data.support,signal_asof=str(asof),history_cutoff=str(asof-pd.Timedelta(days=1)))
    f=replace(data.forecast,signal_asof=str(asof))
    return replace(data,support=s,forecast=f,expected_forecast_sha256=f.digest()),ctx


def test_thin_consumer_returns_existing_target_decision_with_no_account_fit():
    obj,data,ctx=fixture();r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is not None,r.diagnostic
    assert isinstance(r.decision,TargetDecision)
    assert r.physical_fit_count==r.account_replay_count==0
    assert not r.strict_PIT_promotion_eligible and not r.quote_qualified and not r.certified_nav_qualified
    assert np.isclose(r.decision.weights.sum(),1.)


@pytest.mark.parametrize('bad',['alpha_only','missing','unknown_uid','unknown_epoch','source_false','required_shrink','asset_shrink'])
def test_full_required_source_identity_blocks_without_payload_consumption(bad):
    obj,data,ctx=fixture();s=data.support
    if bad=='alpha_only':s=replace(s,alpha_only_output=True)
    if bad=='missing':s=replace(s,required_missing_count=1)
    if bad=='unknown_uid':s=replace(s,asset_uids=s.asset_uids|{s.assets[0]:'UNKNOWN'})
    if bad=='unknown_epoch':s=replace(s,identity_epochs=s.identity_epochs|{s.assets[0]:'UNKNOWN'})
    if bad=='source_false':s=replace(s,source_qualified_for_mechanism=False)
    if bad=='required_shrink':s=replace(s,required_assets=s.assets[:-1])
    if bad=='asset_shrink':s=replace(s,assets=s.assets[:-1])
    class Provider:
        def qualify_metadata(self,*a):return s
        def load_inputs(self,*a):pytest.fail('Payload consumed before full support qualified')
    obj.provider=Provider();r=obj.evaluate(0,ctx.path_ids[0],ctx)
    assert r.decision is None and r.status.startswith('BLOCKED_')


def test_held_unknown_cannot_be_hidden_by_not_eligible():
    obj,data,ctx=fixture();buy=ctx.buy_allowed.copy();decision=ctx.decision_mask.copy();buy[0,0]=decision[0,0]=False
    current=np.zeros(12);current[0]=.05
    data,ctx=next_day(data,ctx,index=0,date='2024-01-03',current=current)
    ctx=replace(ctx,common=replace(ctx.common,buy_allowed=buy,decision_mask=decision))
    s=replace(data.support,asset_uids=data.support.asset_uids|{data.support.assets[0]:'UNKNOWN'})
    r=obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,support=s))
    assert r.decision is None and 'UID' in r.diagnostic['block_reason']


@pytest.mark.parametrize('bad',['source','uid','epoch','future_cutoff','method','payload_hash','nonfinite'])
def test_exact_risk_binding_has_no_padding_or_fallback(bad):
    obj,data,ctx=fixture();state=data.risk;n=dict(state.notes)
    if bad=='source':n['source_sha256']='0'*64
    if bad=='uid':n['asset_uids']=n['asset_uids']|{state.assets[0]:'OTHER'}
    if bad=='epoch':n['identity_epochs']=n['identity_epochs']|{state.assets[0]:'E2'}
    if bad=='future_cutoff':n['cutoff']='2024-01-04T21:00:00Z'
    if bad=='method':state=replace(state,method='R6::HUBER::COMPLETE_DOMAIN')
    if bad=='nonfinite':state=replace(state,covariance=np.full((12,12),np.nan))
    state=replace(state,notes=n);data=replace(data,risk=state,expected_risk_sha256='0'*64 if bad=='payload_hash' else p.content_hash(state))
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is None and r.status.startswith('BLOCKED_')


def test_monthly_carried_target_is_not_new_exact_q_reuse(monkeypatch):
    obj,data,ctx=fixture();calls=[];original=p.q_owner.allocate_q
    def allocate(*a,**kw):calls.append(1);return original(*a,**kw)
    monkeypatch.setattr(p.q_owner,'allocate_q',allocate)
    first=obj.evaluate(0,ctx.path_ids[0],ctx,data);assert first.decision is not None
    current=first.decision.weights[0]*.95
    data,ctx=next_day(data,ctx,current=current)
    r=obj.evaluate(1,ctx.path_ids[0],ctx,data)
    assert r.decision is not None,r.diagnostic
    assert len(calls)==1 and r.diagnostic['q_state']=='CARRIED_TARGET_NOT_NEW_EXACT_SOLVE'
    assert r.diagnostic['projection']=='DETERMINISTIC_REFEASIBILITY_NOT_OPTIMIZER_EXACT_REUSE'


@pytest.mark.parametrize('change',['buy','lock','required','source','risk_support','epoch'])
def test_structural_or_operational_change_outside_frozen_q_clock_blocks(change):
    obj,data,ctx=fixture();assert obj.evaluate(0,ctx.path_ids[0],ctx,data).decision is not None
    data,ctx=next_day(data,ctx)
    s=data.support
    if change=='buy':
        buy=ctx.buy_allowed.copy();buy[0,0]=False;ctx=replace(ctx,common=replace(ctx.common,buy_allowed=buy));s=replace(s,required_assets=s.assets[1:])
    if change=='lock':
        lock=ctx.reserved_mask.copy();lock[0,0]=True;ctx=replace(ctx,common=replace(ctx.common,reserved_mask=lock))
    if change=='required':
        buy=ctx.buy_allowed.copy();mask=ctx.decision_mask.copy();buy[0,0]=mask[0,0]=False;ctx=replace(ctx,common=replace(ctx.common,buy_allowed=buy,decision_mask=mask));s=replace(s,required_assets=s.assets[1:])
    if change=='source':s=replace(s,source_support_identity='7'*64)
    if change=='risk_support':s=replace(s,risk_support_identity='7'*64)
    if change=='epoch':
        epochs=s.identity_epochs|{s.assets[0]:'E2'};s=replace(s,identity_epochs=epochs)
        f=replace(data.forecast,identity_epochs=epochs);state=replace(data.risk,notes=data.risk.notes|dict(identity_epochs=epochs))
        data=replace(data,forecast=f,expected_forecast_sha256=f.digest(),risk=state,expected_risk_sha256=p.content_hash(state))
    data=replace(data,support=s,scenarios=None)
    r=obj.evaluate(1,ctx.path_ids[0],ctx,data)
    assert r.decision is None and r.status in ('BLOCKED_ACCOUNT','BLOCKED_INPUT')


def test_immutable_115_space_rejects_unregistered_recipe():
    obj,data,ctx=fixture();row=obj.contract.paths[0];changed=row|dict(specification=row['specification']|dict(q='NOT_A_METHOD'))
    c=replace(obj.contract,paths=(changed,))
    with pytest.raises(p.MethodSpacePolicyBlocked,match='UNDECLARED_R6'):
        p.MethodSpacePolicy(c,expected_contract_sha256=c.digest())


def test_kelly_funding_cap_reaches_actual_target(monkeypatch):
    obj,data,ctx=fixture('Q_FRACTIONAL_KELLY')
    allocation=p.q_owner.owner.AllocationResult(np.full(12,1/12),0,0.,0.,'SYNTHETIC')
    monkeypatch.setattr(p.q_owner,'allocate_q',lambda *a,**kw:p.q_owner.QEstimate(allocation,.25,1,{}))
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is not None,r.diagnostic
    assert np.isclose(r.decision.weights.sum(),.25) and r.diagnostic['q_growth_cap']==.25
    assert r.diagnostic['gross_controller_cap']==1. and r.diagnostic['gross_effective_cap']==.25


@pytest.mark.parametrize('cost',[5,10,20])
def test_actual_slippage_cost_sent_to_q_and_action(cost,monkeypatch):
    obj,data,ctx=fixture('Q_TURNOVER_MV',cost);seen=[];original=p.q_owner.allocate_q
    def alloc(*a,**kw):seen.append(kw['execution_friction_bps']);return original(*a,**kw)
    monkeypatch.setattr(p.q_owner,'allocate_q',alloc)
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data);assert r.decision is not None,r.diagnostic
    assert seen==[cost] and obj.friction_contract(ctx.path_ids[0])['one_way_bps']==cost


def test_mpc_fixed_two_step_has_whole_policy_callback_and_branch_counts():
    obj,data,ctx=fixture('DP_ANCHOR');solves=[];evals=[]
    obj.on_policy_solve=lambda *a:solves.append(a);obj.on_evaluation=lambda *a:evals.append(a)
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is not None,r.diagnostic
    assert solves==[('MPC_TWO_STEP_WHOLE_POLICY_SOLVE',1)]
    assert sum(n for k,n in evals if k=='MPC_FINITE_BRANCH_EVALUATION')==9


def test_tail_state_requires_independent_covariance_and_real_scenarios():
    obj,data,ctx=fixture('RISK_EMPIRICAL_CVAR');notes=data.risk.notes
    tail=replace(data.risk,method='R6::EMPIRICAL_CVAR::JOINT_SCENARIO_TAIL',covariance=None,representation='TAIL_SCENARIOS',scenarios=data.scenarios)
    cov=replace(data.risk,method='R6::POSTERIOR_PREDICTIVE::COMPLETE_DOMAIN')
    data=replace(data,risk=tail,expected_risk_sha256=p.content_hash(tail),covariance_support=cov,expected_covariance_sha256=p.content_hash(cov),regime_receipt=dict(state='NORMAL',source_sha256=data.support.source_sha256,source_version_sha256='3'*64,producer_sha256='4'*64,available_at='2024-01-02T21:00:00Z',past_only=True))
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is not None,r.diagnostic
    altered=replace(data,scenarios=data.scenarios+.001,scenarios_receipt=data.scenarios_receipt|dict(payload_sha256=p.content_hash(data.scenarios+.001)))
    assert obj.evaluate(0,ctx.path_ids[0],ctx,altered).decision is None


def test_synthetic_cannot_call_real_account_or_bypass_registry():
    obj,data,ctx=fixture()
    with pytest.raises(p.MethodSpacePolicyBlocked,match='CANONICAL_ADMISSION'):obj(0,ctx)


def test_real_mode_refuses_unfrozen_partial_contract_before_provider_or_reads():
    obj,data,ctx=fixture()
    with pytest.raises(p.MethodSpacePolicyBlocked,match='METHOD_SPACE_143'):
        p.MethodSpacePolicy(obj.contract,expected_contract_sha256=obj.contract.digest(),synthetic=False,run='UNQUALIFIED',freeze_sha256='9'*64)


def test_unimplemented_inputs_keep_typed_block_no_fallback():
    obj,data,ctx=fixture('GROSS_CATBOOST')
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is None and 'GROSS' in r.diagnostic['block_reason']


def test_pins_reference_four_math_owners_and_one_existing_account():
    pins=p.source_pins()
    for suffix in ('joint_method_space_risk_r6.py','joint_method_space_optimizer_r6.py','joint_method_space_action_r6.py','joint_method_space_gross_r6.py','continuous_research_account.py'):
        assert any(k.endswith(suffix) for k in pins)
    assert p.specification()['account_implementation_added'] is False


@pytest.mark.parametrize('change',['sid_unknown','coordinate_unknown'])
def test_source_security_coordinate_never_guessed(change):
    obj,data,ctx=fixture();s=data.support
    if change=='sid_unknown':s=replace(s,asset_sids=s.asset_sids|{s.assets[0]:'UNKNOWN'})
    else:s=replace(s,security_coordinate='UNKNOWN')
    r=obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,support=s))
    assert r.decision is None and 'SID_AND_SECURITY' in r.diagnostic['block_reason']


def test_existing_tail_state_missing_is_source_block_not_new_tail_predictor():
    obj,data,ctx=fixture('TAIL_NO_TRADE')
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is None and r.status=='BLOCKED_SOURCE'
    assert 'EXISTING_FROZEN_TAIL_STATE' in r.diagnostic['block_reason']


def test_regime_conditioned_action_requires_exact_past_only_state():
    obj,data,ctx=fixture('ACTION_TURNOVER_BUDGET')
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is None and r.status=='BLOCKED_SOURCE'
    receipt=dict(state='HIGH_VOL',source_sha256=data.support.source_sha256,source_version_sha256='3'*64,producer_sha256='4'*64,available_at='2024-01-02T21:00:00Z',past_only=True)
    r=obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,regime='HIGH_VOL',regime_receipt=receipt))
    assert r.decision is not None,r.diagnostic
    assert np.abs(r.decision.weights[0]-ctx.current_weights[0]).sum()<=.05+1e-8



def test_pairing_excludes_free_slot_buys_and_uses_signal_known_ties():
    assets=('Z','A','Y','B','FREE');uids={a:'uid'+a for a in assets}
    units=np.array([1,1,0,0,0]);current=np.array([.1,.1,0,0,0]);target=np.array([0,0,.1,.1,.1]);mu=np.array([.02,.02,.04,.04,.03]);sigma=np.array([0,0,.03,0,0])
    pairs=p.fixed_replacement_pairs(assets,uids,units,current,target,mu,sigma,'RPL0')
    assert [(x.entrant,x.incumbent) for x in pairs]==[('B','A'),('Y','Z')]
    assert len(pairs)==2 # the unpaired third entrant is a free-slot BUY
    lower=p.fixed_replacement_pairs(assets,uids,units,current,target,mu,sigma,'RPL4')
    assert lower[1].entrant=='FREE'


def test_replacement_utility_is_usd_and_actual_cost_not_mu_threshold():
    assets=('INC','ENT');cur=np.array([.1,0.]);target=np.array([0.,.05]);mu=np.array([.01,.03]);sigma=np.zeros(2);cov=np.eye(2)*.0001;pair=p.ReplacementPair('ENT','INC')
    utility,detail=p.replacement_delta_utility(pair,assets,cur,target,mu,sigma,cov,3000.,10,'RPL1')
    assert np.isclose(utility,3000*.05*(.03-.01)-.001*3000*.15)
    assert detail['value_coordinate']=='USD' and np.isclose(detail['friction_usd'],.45)


def test_replacement_tail_uses_genuine_joint_portfolio_scenarios():
    assets=('INC','ENT');cur=np.array([.1,0.]);target=np.array([0.,.1]);mu=np.array([.01,.05]);sigma=np.zeros(2);cov=np.eye(2)*.0001;pair=p.ReplacementPair('ENT','INC')
    with pytest.raises((p.MethodSpacePolicyBlocked,IndexError)):
        p.replacement_delta_utility(pair,assets,cur,target,mu,sigma,cov,3000.,10,'RPL3',None)
    raw=np.c_[np.linspace(-.01,.01,40),np.linspace(-.20,.01,40)]
    utility,detail=p.replacement_delta_utility(pair,assets,cur,target,mu,sigma,cov,3000.,10,'RPL3',raw)
    assert utility<0 and detail['marginal_tail_usd']>0



def test_real_provider_without_canonical_full_freeze_never_loads(monkeypatch):
    obj,data,ctx=fixture();dates=tuple(x.date().isoformat() for x in pd.bdate_range('2023-01-03',periods=752));qdates=tuple(sorted(set(dates[:142])|{'2024-01-03'}))
    c=replace(obj.contract,paths=tuple(p.design.policy_space()['physical_paths']),decision_dates=dates,q_dates=qdates)
    calls=[]
    def blocked(*a):calls.append(a);raise ValueError('CANONICAL_ADMISSION_PENDING')
    monkeypatch.setattr(p.runtime,'guard_numeric',blocked)
    with pytest.raises(ValueError,match='CANONICAL_ADMISSION_PENDING'):
        p.MethodSpacePolicy(c,expected_contract_sha256=c.digest(),synthetic=False,run='SYNTHETIC_ONLY',freeze_sha256='9'*64)
    assert len(calls)==1


def test_actual_math_risk_packet_is_not_account_source_authority():
    obj,data,ctx=fixture();bad=replace(data.risk,status='SOURCE_QUALIFICATION_PENDING')
    # This is synthetic evaluation; real-pending packets cannot masquerade as
    # synthetic PASS, and real mode independently requires canonical admission.
    result=obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,risk=bad,expected_risk_sha256=p.content_hash(bad)))
    assert result.decision is None and 'NOT_MECHANISM_INPUT_READY' in result.diagnostic['block_reason']


def test_forecast_not_oof_or_postcutoff_cannot_reach_solver(monkeypatch):
    obj,data,ctx=fixture();calls=[]
    monkeypatch.setattr(p.q_owner,'allocate_q',lambda *a,**kw:calls.append(1))
    f=replace(data.forecast,genuine_chronological_oof=False)
    result=obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,forecast=f,expected_forecast_sha256=f.digest()))
    assert result.decision is None and calls==[]



def test_actual_slots_change_outside_clock_does_not_invent_new_q_capacity():
    obj,data,ctx=fixture();assert obj.evaluate(0,ctx.path_ids[0],ctx,data).decision is not None
    data,ctx=next_day(data,ctx);ctx=replace(ctx,common=replace(ctx.common,available_slots=np.array([10])))
    result=obj.evaluate(1,ctx.path_ids[0],ctx,data)
    assert result.decision is None and result.status=='BLOCKED_ACCOUNT'
    assert 'SUPPORT_CHANGE_OUTSIDE_FROZEN_Q_CLOCK' in result.diagnostic['block_reason']


def test_frozen_account_caps_never_relaxed_by_policy():
    obj,data,ctx=fixture();ctx=replace(ctx,common=replace(ctx.common,max_positions=30))
    result=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert result.decision is None and 'FROZEN_CAPS' in result.diagnostic['block_reason']



def test_q_callback_binds_full_source_uid_epoch_and_payload_context():
    obj,data,ctx=fixture();calls=[]
    def solve(name,inputs,compute):calls.append((name,inputs));return compute()
    obj.solve=solve;result=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert result.decision is not None,result.diagnostic
    metadata=calls[0][1][0]
    assert data.support.asset_uids in metadata and data.support.identity_epochs in metadata
    assert data.expected_risk_sha256 in metadata and data.expected_forecast_sha256 in metadata
    assert data.support.security_coordinate in metadata



def test_final_whole_freeze_sha_is_external_acyclic_contract_binding():
    obj,data,ctx=fixture()
    assert obj.contract.scientific_recipe_sha256=='a'*64
    assert 'science_sha256' not in obj.contract.__dataclass_fields__
    with pytest.raises(p.MethodSpacePolicyBlocked,match='FINAL_WHOLE_FREEZE_SHA'):
        p.MethodSpacePolicy(obj.contract,expected_contract_sha256=obj.contract.digest(),synthetic=False)



@pytest.mark.parametrize('role',['CONTROL_RAW_A2_POLICY','JOINT_SIMPLE_EQUAL'])
def test_frozen_rank_controls_do_not_falsely_claim_ml_oof(role):
    obj,data,ctx=fixture(role)
    assert data.forecast.genuine_chronological_oof is False
    r=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert r.decision is not None,r.diagnostic
    assert r.diagnostic['control_exact_owner_reuse'] is True



@pytest.mark.parametrize('regime,method',[('LOW_VOL','DYNAMIC_FACTOR'),('NORMAL','AVERAGE'),('HIGH_VOL','POSTERIOR_PREDICTIVE')])
def test_same_q_regime_path_consumes_frozen_distinct_risk_method(regime,method):
    obj,data,ctx=fixture('REGIME_Q')
    receipt=dict(state=regime,source_sha256=data.support.source_sha256,source_version_sha256='3'*64,producer_sha256='4'*64,available_at='2024-01-02T21:00:00Z',past_only=True)
    state=replace(data.risk,method='R6::'+method+'::COMPLETE_DOMAIN')
    data=replace(data,regime=regime,regime_receipt=receipt,risk=state,expected_risk_sha256=p.content_hash(state))
    result=obj.evaluate(0,ctx.path_ids[0],ctx,data)
    assert result.decision is not None,result.diagnostic
    assert result.diagnostic['effective_risk_method']==method
    wrong=replace(state,method='R6::HUBER::COMPLETE_DOMAIN')
    assert obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,risk=wrong,expected_risk_sha256=p.content_hash(wrong))).decision is None


def test_none_action_scope_does_not_implicitly_consume_regime_or_tail(monkeypatch):
    obj,data,ctx=fixture('ACTION_SYMMETRIC_BAND');calls=[];original=p.action_owner.action_target
    def action(*a,**kw):calls.append((kw['regime'],kw['tail_elevated']));return original(*a,**kw)
    monkeypatch.setattr(p.action_owner,'action_target',action)
    result=obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,regime='HIGH_VOL',tail_elevated=True))
    assert result.decision is not None,result.diagnostic
    assert calls==[('NORMAL',False)]



def test_native_classical_completion_child_requires_exact_proof_and_parent():
    obj,data,ctx=fixture('Q_MV')
    # AVERAGE cannot be relabeled as an arbitrary classical completion child.
    wrong=replace(data.risk,method='R6::AVERAGE::POSTERIOR_CONDITIONAL_COMPLETION')
    assert obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,risk=wrong,expected_risk_sha256=p.content_hash(wrong))).decision is None
    obj,data,ctx=fixture('ACTION_SYMMETRIC_BAND')
    method=obj.rows[ctx.path_ids[0]]['specification']['risk']
    proof=dict(scientific_method='R6_CLASSICAL_PLUS_POSTERIOR_CONDITIONAL_COMPLETION',estimated_positions=list(range(10)),prior_only_positions=[10,11],observations_fabricated=False,price_filling=False)
    child=replace(data.risk,method='R6::'+method+'::POSTERIOR_CONDITIONAL_COMPLETION',notes=data.risk.notes|dict(completion=proof))
    good=replace(data,risk=child,expected_risk_sha256=p.content_hash(child));r=obj.evaluate(0,ctx.path_ids[0],ctx,good)
    assert r.decision is not None,r.diagnostic
    for bad in (proof|dict(price_filling=True),proof|dict(scientific_method='R5_CLASSICAL_PLUS_HP_CONDITIONAL_COMPLETION'),proof|dict(prior_only_positions=[9,11]),proof|dict(estimated_positions=[])):
        state=replace(child,notes=child.notes|dict(completion=bad))
        assert obj.evaluate(0,ctx.path_ids[0],ctx,replace(data,risk=state,expected_risk_sha256=p.content_hash(state))).decision is None
