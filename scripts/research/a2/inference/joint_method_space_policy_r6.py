"""R6 finite method-space consumer of existing math and persistent account APIs.

No data reader, fitter, fill, mark or account is added. Actual providers are
source-pinned by the full science freeze and must qualify metadata before any
forecast/bank payload is loaded. A carried target is not an exact new solve.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import inspect
from pathlib import Path
from typing import Mapping
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import joint_method_space_design_r6 as design
from scripts.research.a2.evaluation import joint_method_space_runtime_r6 as runtime
from scripts.research.a2.inference import joint_method_space_optimizer_r6 as q_owner
from scripts.research.a2.inference import joint_method_space_action_r6 as action_owner
from scripts.research.a2.training import joint_method_space_gross_r6 as gross_owner
from scripts.research.a2.risk import joint_method_space_risk_r6 as risk_owner
from scripts.research.a2.inference.joint_frozen_history_policy_r3 import _transport
from scripts.research.a2.portfolio import shared_joint_adapter_r2 as adapter_owner
from scripts.research.a2.inference.joint_portfolio_policy import _support_projection,JointResearchPolicy,EPS
from scripts.research.a2.evaluation.joint_method_accounts import PARAMETERS
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

TAIL_COVARIANCE_SUPPORT={'EMPIRICAL_CVAR':'POSTERIOR_PREDICTIVE','EVT':'POSTERIOR_PREDICTIVE'}
REGIME_RISK_MAP={'LOW_VOL':'DYNAMIC_FACTOR','NORMAL':'AVERAGE','HIGH_VOL':'POSTERIOR_PREDICTIVE'}
QUALIFIED='QUALIFIED_FULL_REQUIRED_FROM_FROZEN_R6_SUPPORT'

class MethodSpacePolicyBlocked(ValueError):
    pass

def _fail(reason):raise MethodSpacePolicyBlocked(reason)
def _sha(v):return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)
def _clock(value):
    t=pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None or t>=pd.Timestamp('2026-01-01',tz='UTC'):_fail('AWARE_PRE2026_POLICY_CLOCK_REQUIRED')
    return t.tz_convert('UTC')
def _known(value):return isinstance(value,str) and bool(value.strip()) and value.upper() not in ('UNKNOWN','NONE','NAN','NULL','N/A')

def source_pins():
    from scripts.research.a2.evaluation import continuous_research_account
    from scripts.research.a2.inference import joint_frozen_history_policy_r3,joint_portfolio_policy
    modules=(design,runtime,q_owner,action_owner,gross_owner,risk_owner,continuous_research_account,
             joint_frozen_history_policy_r3,joint_portfolio_policy)
    paths={Path(m.__file__).resolve() for m in modules}|{Path(__file__).resolve()}
    for pin in q_owner.code_pins()+risk_owner.code_pins():paths.add(Path(pin['path']).resolve())
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

@dataclass(frozen=True)
class MethodSpacePolicyContract:
    research_id: str
    run_id: str
    scientific_recipe_sha256: str
    source_sha256: str
    paths: tuple
    decision_dates: tuple
    q_dates: tuple
    source_code_pins: Mapping
    provider_source_ref: str=''
    provider_source_sha256: str=''
    support_refs: Mapping=field(default_factory=dict)
    forecast_lineage: Mapping=field(default_factory=dict)
    tail_covariance_support: Mapping=field(default_factory=lambda:dict(TAIL_COVARIANCE_SUPPORT))
    strict_PIT_promotion_eligible: bool=False
    quote_qualified: bool=False
    certified_nav_qualified: bool=False
    def digest(self):return content_hash(self)

@dataclass(frozen=True)
class PolicySupportReceipt:
    research_id: str
    source_sha256: str
    signal_asof: str
    history_cutoff: str
    master_assets: tuple
    assets: tuple
    asset_uids: Mapping
    identity_epochs: Mapping
    required_assets: tuple
    source_support_identity: str
    risk_support_identity: str
    support_ref: str
    support_sha256: str
    support_row_sha256: str
    full_required_policy_identity: bool=True
    required_missing_count: int=0
    alpha_only_output: bool=False
    source_qualified_for_mechanism: bool=True
    current_identity_qualified: bool=True
    asset_sids: Mapping=field(default_factory=dict)
    security_coordinate: str=""
    def digest(self):return content_hash(self)

@dataclass(frozen=True)
class PolicyForecast:
    prediction: str
    assets: tuple
    asset_uids: Mapping
    identity_epochs: Mapping
    signal_asof: str
    fit_cutoff: str
    available_at: str
    source_sha256: str
    producer_sha256: str
    selected_recipe_sha256: str
    genuine_chronological_oof: bool
    mu: object
    sigma: object
    q10: object=None
    disagreement: object=None
    forecast_semantic: str="GENUINE_OOF_OPPORTUNITY"
    def digest(self):return content_hash(self)

@dataclass(frozen=True)
class FrozenGrossPrediction:
    kind: str
    value: float
    fit_cutoff: str
    signal_asof: str
    source_sha256: str
    producer_sha256: str
    selected_recipe_sha256: str
    target: str=gross_owner.TARGET
    genuine_chronological_oof: bool=True

@dataclass(frozen=True)
class ReplacementPair:
    entrant: str
    incumbent: str
    marginal_variance: float=0.
    marginal_tail: float=0.

def fixed_replacement_pairs(assets,uids,current_units,current_weights,target_weights,mu,sigma,kind):
    """Frozen signal-known one-to-one rule. Free-slot BUY is never paired."""
    assets=tuple(assets);units,current,target,mu,sigma=map(lambda x:np.asarray(x,float),(current_units,current_weights,target_weights,mu,sigma))
    n=len(assets)
    if kind not in ('RPL0','RPL1','RPL2','RPL3','RPL4') or any(x.shape!=(n,) for x in (units,current,target,mu,sigma)) or not all(np.isfinite(x).all() for x in (units,current,target,mu,sigma)):_fail('FIXED_REPLACEMENT_FULL_AXES_REQUIRED')
    if set(uids)!=set(assets) or any(not _known(v) for v in uids.values()):_fail('FIXED_REPLACEMENT_KNOWN_UID_REQUIRED')
    values=mu-sigma if kind=='RPL4' else mu
    incumbents=np.flatnonzero((units>EPS)&(target<=EPS));entrants=np.flatnonzero((units<=EPS)&(target>EPS))
    entrants=sorted(entrants,key=lambda i:(-float(values[i]),assets[i],uids[assets[i]]))
    incumbents=sorted(incumbents,key=lambda i:(float(values[i]),assets[i],uids[assets[i]]))
    return tuple(ReplacementPair(assets[a],assets[b]) for a,b in zip(entrants,incumbents))

def empirical_portfolio_cvar(scenarios,weights):
    scenarios=np.asarray(scenarios,float);weights=np.asarray(weights,float)
    if scenarios.ndim!=2 or scenarios.shape[1]!=len(weights) or len(scenarios)<30 or not np.isfinite(scenarios).all():_fail('REPLACEMENT_GENUINE_JOINT_SCENARIOS_REQUIRED')
    loss=-(scenarios@weights);threshold=float(np.quantile(loss,.9))
    return threshold+float(np.maximum(loss-threshold,0).mean())/.1

def replacement_delta_utility(pair,assets,current,target,mu,sigma,covariance,nav,cost_bps,kind,scenarios=None):
    """All value, friction and marginal-risk terms are in account USD."""
    a,b=assets.index(pair.entrant),assets.index(pair.incumbent)
    matched=min(float(current[b]),float(target[a]));value_scale=float(nav)*matched
    friction=float(cost_bps)/10000.*float(nav)*(float(current[b])+float(target[a]))
    after=np.asarray(current,float).copy();after[b]=0.;after[a]=target[a]
    variance_increment=.5*float(nav)*float(after@covariance@after-current@covariance@current)
    tail_increment=(float(nav)*(empirical_portfolio_cvar(scenarios,after)-empirical_portfolio_cvar(scenarios,current)) if kind=='RPL3' else 0.)
    utility=action_owner.replacement_utility(kind,value_scale*mu[a],value_scale*mu[b],friction=friction,
        marginal_variance=variance_increment,marginal_tail=tail_increment,
        entrant_sigma=value_scale*sigma[a],incumbent_sigma=value_scale*sigma[b])
    return utility,dict(matched_weight=matched,value_coordinate='USD',friction_usd=friction,
                       marginal_variance_usd=variance_increment,marginal_tail_usd=tail_increment)

@dataclass(frozen=True)
class MethodSpacePolicyInputs:
    support: PolicySupportReceipt
    forecast: PolicyForecast
    expected_forecast_sha256: str
    risk: object=None
    expected_risk_sha256: str=''
    covariance_support: object=None
    expected_covariance_sha256: str=''
    scenarios: object=None
    scenarios_receipt: Mapping=field(default_factory=dict)
    prior_scale: float | None=None
    gross_prediction: FrozenGrossPrediction | None=None
    gross_inputs: Mapping=field(default_factory=dict)
    regime: str='NORMAL'
    tail_elevated: bool=False
    replacement_pairs: tuple=()
    replacement_mapping_sha256: str=''
    drawdown: float | None=None
    realized_turnover_previous: float | None=None
    regime_receipt: Mapping=field(default_factory=dict)
    tail_receipt: Mapping=field(default_factory=dict)

@dataclass(frozen=True)
class MethodSpacePolicyResult:
    path_id: str
    status: str
    decision: object
    diagnostic: Mapping
    physical_fit_count: int=0
    account_replay_count: int=0
    strict_PIT_promotion_eligible: bool=False
    quote_qualified: bool=False
    certified_nav_qualified: bool=False

class MethodSpacePolicy:
    """Thin TargetDecision callable; common account owns all accounting/execution.

    Provider protocol: qualify_metadata(day,row,ctx), validate_receipt(receipt),
    then load_inputs(day,row,ctx,receipt). Real qualification implementation must
    be physically pinned in the full freeze. No boolean-only provider admission.
    solve(name,inputs,compute) is the pre-reservation/exact-cache callback; MPC
    requires a separate pre-reservation callback because it is a policy solve.
    """
    def __init__(self,contract,*,expected_contract_sha256,provider=None,synthetic=True,
                 run=None,freeze_sha256=None,solve=None,on_policy_solve=None,on_evaluation=None):
        if not isinstance(contract,MethodSpacePolicyContract) or contract.digest()!=expected_contract_sha256:_fail('EXACT_R6_POLICY_CONTRACT_REQUIRED')
        if type(synthetic) is not bool:_fail('EXPLICIT_SYNTHETIC_MODE_REQUIRED')
        if contract.research_id!=design.ID or not all(_sha(x) for x in (contract.scientific_recipe_sha256,contract.source_sha256)):_fail('R6_POLICY_SCIENCE_SOURCE_IDENTITY_REQUIRED')
        if any(getattr(contract,k) is not False for k in ('strict_PIT_promotion_eligible','quote_qualified','certified_nav_qualified')):_fail('UNCERTIFIED_MECHANISM_ONLY')
        if dict(contract.source_code_pins)!=source_pins():_fail('POLICY_PINNED_OWNER_CODE_CHANGED')
        original={p['path_id']:p for p in design.policy_space()['physical_paths']}
        if len(contract.paths)!=len({p['path_id'] for p in contract.paths}) or not contract.paths:_fail('UNIQUE_FROZEN_METHOD_PATHS_REQUIRED')
        for p in contract.paths:
            if p!=original.get(p['path_id']):_fail('UNDECLARED_R6_METHOD_SPACE_OR_RECIPE')
        dates=list(contract.decision_dates);qdates=list(contract.q_dates)
        if dates!=sorted(set(dates)) or qdates!=sorted(set(qdates)) or not set(qdates)<=set(dates) or not dates or dates[-1]>='2026-01-01':_fail('EXACT_PRE2026_POLICY_CLOCK_REQUIRED')
        if contract.tail_covariance_support!=TAIL_COVARIANCE_SUPPORT:_fail('FROZEN_TAIL_COVARIANCE_SUPPORT_MAPPING_REQUIRED')
        self.contract,self.contract_sha,self.provider,self.synthetic=contract,expected_contract_sha256,provider,synthetic
        self.rows={p['path_id']:p for p in contract.paths};self.solve=solve
        self.on_policy_solve,self.on_evaluation=on_policy_solve,on_evaluation
        self.run=run;self.freeze_sha256=freeze_sha256;self.cache={};self.memories={};self.diagnostics=[]
        if not synthetic:
            if not _sha(freeze_sha256):_fail('EXPLICIT_FINAL_WHOLE_FREEZE_SHA_REQUIRED')
            if len(contract.paths)!=len(original) or len(dates)!=752 or len(qdates)!=143:_fail('FULL_FROZEN_METHOD_SPACE_143_Q_CLOCK_REQUIRED')
            self._real_guard()
            if solve is None or on_policy_solve is None or on_evaluation is None:_fail('REAL_DURABLE_BUDGET_AND_COUNTER_CALLBACKS_REQUIRED')
            if provider is None or not all(callable(getattr(provider,k,None)) for k in ('qualify_metadata','validate_receipt','load_inputs')):_fail('QUALIFIED_METADATA_FIRST_REAL_PROVIDER_REQUIRED')
            p=Path(inspect.getfile(type(provider))).resolve()
            if str(p)!=contract.provider_source_ref or hashlib.sha256(p.read_bytes()).hexdigest()!=contract.provider_source_sha256:_fail('EXACT_FROZEN_REAL_PROVIDER_SOURCE_REQUIRED')

    def _real_guard(self):
        runtime.guard_numeric(self.run,self.freeze_sha256)
        f=runtime.parent.read_json(Path(self.run)/runtime.FILENAME)
        ref=f.get('policy_consumer_contract_ref',{})
        if ref.get('semantic_digest')!=self.contract_sha:_fail('FULL_SCIENCE_POLICY_CONTRACT_BINDING_REQUIRED')
        runtime.parent._pin(ref['source_ref'],ref['sha256'],'R6_POLICY_CONSUMER_CONTRACT')
        if content_hash(runtime.parent.read_json(ref['source_ref']))!=self.contract_sha:_fail('FROZEN_POLICY_CONTRACT_BODY_REQUIRED')

    def _count(self,name,units=1):
        if self.on_evaluation:self.on_evaluation(name,units)

    def friction_contract(self,path_id):
        row=self.rows[path_id]
        return dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE',one_way_bps=row['primary_bps'],fee_bps=0,
                    benchmark='NEXT_RAW_OPEN',authority='HYPOTHETICAL_RESEARCH_SCENARIO',scenario_id=design.ID+'::'+str(row['primary_bps'])+'bps')

    def _support(self,receipt,ctx):
        if not isinstance(receipt,PolicySupportReceipt):_fail('TYPED_FULL_POLICY_SUPPORT_REQUIRED')
        master=tuple(map(str,ctx.tickers));assets=receipt.assets
        required_mask=(ctx.current_units[0]>EPS)|(ctx.current_weights[0]>EPS)|(ctx.decision_mask[0]&ctx.buy_allowed[0])
        required=tuple(np.asarray(master)[required_mask])
        if (receipt.research_id!=design.ID or receipt.source_sha256!=self.contract.source_sha256 or receipt.master_assets!=master or
            receipt.required_assets!=required or len(set(assets))!=len(assets) or not set(required)<=set(assets)):_fail('FULL_REQUIRED_ELIGIBLE_PLUS_HELD_DOMAIN_MISMATCH')
        if (receipt.full_required_policy_identity is not True or type(receipt.required_missing_count) is not int or receipt.required_missing_count!=0 or
            receipt.alpha_only_output is not False or receipt.source_qualified_for_mechanism is not True or receipt.current_identity_qualified is not True):_fail('BLOCKED_INPUT_FULL_REQUIRED_POLICY_IDENTITY')
        if set(receipt.asset_uids)!=set(assets) or set(receipt.identity_epochs)!=set(assets) or any(not _known(v) for v in list(receipt.asset_uids.values())+list(receipt.identity_epochs.values())) or len(set(receipt.asset_uids.values()))!=len(assets):_fail('BLOCKED_INPUT_UNKNOWN_OR_AMBIGUOUS_HELD_UID_EPOCH')
        if set(receipt.asset_sids)!=set(assets) or any(not _known(v) for v in receipt.asset_sids.values()) or len(set(receipt.asset_sids.values()))!=len(assets) or not _known(receipt.security_coordinate):_fail('BLOCKED_INPUT_KNOWN_SID_AND_SECURITY_COORDINATE_REQUIRED')
        if not _clock(receipt.history_cutoff)<_clock(receipt.signal_asof)==_clock(ctx.signal_asof):_fail('STRICT_PRIOR_POLICY_SUPPORT_CLOCK')
        if not all(_sha(v) for v in (receipt.source_support_identity,receipt.risk_support_identity,receipt.support_sha256,receipt.support_row_sha256)):_fail('EXACT_FROZEN_SOURCE_SUPPORT_PROOF_REQUIRED')
        if not self.synthetic:
            if self.contract.support_refs.get(receipt.support_ref)!=receipt.support_sha256:_fail('UNBOUND_SUPPORT_SIDECAR_REFERENCE')
            attestation=self.provider.validate_receipt(receipt)
            if attestation!={'status':QUALIFIED,'receipt_sha256':receipt.digest()}:_fail('FULL_FROZEN_QUALIFICATION_READER_ATTESTATION_REQUIRED')
        return required_mask

    def _carry_guard(self,s,ctx,path_id,date):
        cache=self.cache.get(path_id)
        if cache is None or date in self.contract.q_dates:return
        master=tuple(map(str,ctx.tickers));columns=pd.Index(master).get_indexer(s.assets)
        if np.any(columns<0):_fail('RISK_ASSET_OUTSIDE_ACCOUNT_MASTER')
        local=_transport(ctx,0,columns);held=local.current_units[0]>EPS;modeled=local.decision_mask[0]
        lock=local.reserved_mask[0]|local.sell_restricted[0]|(held&~modeled&~local.operational_mask[0])
        state_key=content_hash((s.assets,s.asset_uids,s.identity_epochs,s.asset_sids,s.security_coordinate,s.source_support_identity,s.risk_support_identity))
        slots=min(int(local.available_slots[0]),20-int(lock.sum()))
        operational_key=content_hash((lock,local.buy_allowed[0],modeled,slots,s.required_assets))
        if cache['state_key']!=state_key or cache['operational_key']!=operational_key:
            _fail('BLOCKED_ACCOUNT_SUPPORT_CHANGE_OUTSIDE_FROZEN_Q_CLOCK')

    def _forecast(self,f,support,ctx,raw_control=False):
        if not isinstance(f,PolicyForecast) or f.assets!=support.assets or f.asset_uids!=support.asset_uids or f.identity_epochs!=support.identity_epochs or f.source_sha256!=support.source_sha256:_fail('FORECAST_FULL_REQUIRED_UID_EPOCH_SOURCE_MISMATCH')
        if not _clock(f.fit_cutoff)<_clock(f.available_at)<=_clock(f.signal_asof)==_clock(ctx.signal_asof):_fail('GENUINE_PRIOR_OOF_FORECAST_CLOCK_REQUIRED')
        if raw_control:
            if f.forecast_semantic!='FROZEN_RAW_A2_RANK_NO_FIT' or f.genuine_chronological_oof is not False or f.prediction!='RAW_RANK':_fail('FROZEN_RAW_A2_CONTROL_RANK_NO_FIT_SEMANTIC_REQUIRED')
        elif f.genuine_chronological_oof is not True or f.forecast_semantic!='GENUINE_OOF_OPPORTUNITY':_fail('GENUINE_PRIOR_OOF_FORECAST_CLOCK_REQUIRED')
        if not _sha(f.producer_sha256) or not _sha(f.selected_recipe_sha256):_fail('FROZEN_OOF_PRODUCER_AND_RECIPE_REQUIRED')
        if not self.synthetic and self.contract.forecast_lineage.get(f.prediction+':'+str(_clock(ctx.signal_asof).year))!=(f.producer_sha256,f.selected_recipe_sha256):_fail('EXACT_FROZEN_ANNUAL_FORECAST_LINEAGE_REQUIRED')
        return np.asarray(f.mu,float),np.asarray(f.sigma,float)

    def _risk(self,state,support,method,expected_sha):
        if not isinstance(state,risk_owner.RiskEstimate) or content_hash(state)!=expected_sha or state.assets!=support.assets:_fail('TYPED_EXACT_FULL_DOMAIN_RISK_ESTIMATE_REQUIRED')
        expected='R6::'+method+'::COMPLETE_DOMAIN'
        classical={'DCC','KALMAN','DYNAMIC_FACTOR','HUBER','TYLER','ROBUST_FACTOR','POET','GRAPHICAL'}
        completion_method='R6::'+method+'::POSTERIOR_CONDITIONAL_COMPLETION'
        allowed={expected}
        if method=='EMPIRICAL_CVAR':allowed={'R6::EMPIRICAL_CVAR::JOINT_SCENARIO_TAIL'}
        if method=='EVT':allowed={'R6::EVT::POOLED_STANDARDIZED_TAIL'}
        if method in classical:allowed.add(completion_method)
        if state.method not in allowed:_fail('RISK_METHOD_LINEAGE_MISMATCH')
        if state.method==completion_method:
            proof=state.notes.get('completion',{})
            positions=proof.get('estimated_positions',[]);short=proof.get('prior_only_positions',[])
            if (proof.get('scientific_method')!='R6_CLASSICAL_PLUS_POSTERIOR_CONDITIONAL_COMPLETION' or proof.get('observations_fabricated') is not False or proof.get('price_filling') is not False or not isinstance(positions,list) or not isinstance(short,list) or not positions or any(type(i) is not int for i in positions+short) or len(set(positions+short))!=len(state.assets) or set(positions+short)!=set(range(len(state.assets)))):_fail('EXACT_R6_CLASSICAL_PARENT_COMPLETION_PROOF_REQUIRED')
        if state.status not in (('PASS_SYNTHETIC',) if self.synthetic else ('SOURCE_QUALIFICATION_PENDING',)):_fail('RISK_ESTIMATOR_NOT_MECHANISM_INPUT_READY')
        n=state.notes
        if (n.get('source_sha256')!=support.source_sha256 or n.get('asset_uids')!=support.asset_uids or n.get('identity_epochs')!=support.identity_epochs or
            _clock(n.get('cutoff'))>_clock(support.history_cutoff) or not _clock(n.get('cutoff'))<_clock(n.get('as_of'))<=_clock(support.signal_asof) or n.get('risk_support_identity')!=support.risk_support_identity):_fail('RISK_SOURCE_UID_EPOCH_OR_PRIOR_CLOCK_MISMATCH')
        return state

    def evaluate(self,day,path_id,ctx,inputs=None):
        row=self.rows.get(path_id);record=dict(path_id=path_id,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
        try:
            if row is None:_fail('UNDECLARED_R6_PATH')
            if self.contract.digest()!=self.contract_sha or dict(self.contract.source_code_pins)!=source_pins():_fail('FROZEN_POLICY_CONTRACT_OR_CODE_MUTATION')
            date=_clock(ctx.signal_asof).date().isoformat()
            if date not in self.contract.decision_dates or tuple(ctx.path_ids)!=(path_id,):_fail('FROZEN_DECISION_PATH_CONTEXT_REQUIRED')
            if not self.synthetic:self._real_guard()
            if inputs is None:
                support=self.provider.qualify_metadata(day,row,ctx)
                self._support(support,ctx)  # before any forecast/bank read
                self._carry_guard(support,ctx,path_id,date)
                inputs=self.provider.load_inputs(day,row,ctx,support)
                if inputs.support!=support:_fail('PROVIDER_SUPPORT_SWAPPED_AFTER_QUALIFICATION')
            elif not self.synthetic:_fail('REAL_INPUTS_MUST_USE_FROZEN_METADATA_FIRST_PROVIDER')
            if not isinstance(inputs,MethodSpacePolicyInputs):_fail('TYPED_R6_POLICY_PAYLOAD_REQUIRED')
            data=inputs;s=data.support;required=self._support(s,ctx);f=data.forecast
            self._carry_guard(s,ctx,path_id,date)
            if f.digest()!=data.expected_forecast_sha256:_fail('FROZEN_FORECAST_PAYLOAD_MUTATION')
            mu,sigma=self._forecast(f,s,ctx,raw_control=bool(row['specification'].get('control')))
            spec=row['specification'];cost=row['primary_bps'];master=tuple(map(str,ctx.tickers))
            columns=pd.Index(master).get_indexer(s.assets)
            if np.any(columns<0):_fail('RISK_ASSET_OUTSIDE_ACCOUNT_MASTER')
            local=_transport(ctx,0,columns);n=len(s.assets);held=local.current_units[0]>EPS;current=local.current_weights[0]
            if local.max_positions!=20 or local.max_weight!=.1 or local.max_invested!=1. or not 0<=int(local.available_slots[0])<=20:_fail('BLOCKED_ACCOUNT_FROZEN_CAPS_OR_ACTUAL_SLOTS_REQUIRED')
            if mu.shape!=(n,) or sigma.shape!=(n,):_fail('FULL_REQUIRED_FORECAST_AXES_REQUIRED')
            needed=(local.current_units[0]>EPS)|(local.current_weights[0]>EPS)|(local.decision_mask[0]&local.buy_allowed[0])
            mu,sigma=adapter_owner._required_forecasts(mu,sigma,n,needed)
            if spec.get('control'):
                if f.prediction!='RAW_RANK' or s.assets!=master:_fail('RAW_CONTROL_EXACT_MASTER_RANK_REQUIRED')
                kind='raw' if spec['control']=='CONTROL_RAW_A2_POLICY' else 'simple'
                decision=JointResearchPolicy((path_id,),mu[None,None,:],sigma[None,None,:],{},roles={path_id:dict(kind=kind)},parameters=PARAMETERS)(0,ctx)
                return MethodSpacePolicyResult(path_id,'POLICY_TARGET_QUALIFIED_MECHANISM_UNCERTIFIED',decision,record|dict(control_exact_owner_reuse=True))
            if f.prediction!=spec['prediction']:_fail('FROZEN_FORECAST_ROLE_MISMATCH')
            if spec.get('regime')!='NONE' or spec.get('gross')=='REGIME':
                r=data.regime_receipt
                if (r.get('state')!=data.regime or data.regime not in ('LOW_VOL','NORMAL','HIGH_VOL') or r.get('source_sha256')!=s.source_sha256 or not _sha(r.get('source_version_sha256')) or not _sha(r.get('producer_sha256')) or not _clock(r.get('available_at'))<=_clock(s.signal_asof) or r.get('past_only') is not True):_fail('BLOCKED_SOURCE_EXACT_PAST_ONLY_REGIME_RECEIPT_REQUIRED')
                if not self.synthetic and self.contract.support_refs.get(r.get('source_ref'))!=r.get('source_version_sha256'):_fail('UNBOUND_REGIME_SOURCE_VERSION')
            if spec.get('tail')!='NONE':
                r=data.tail_receipt
                if (r.get('pre_existing_frozen_binary_state') is not True or type(data.tail_elevated) is not bool or r.get('elevated')!=data.tail_elevated or r.get('source_sha256')!=s.source_sha256 or not _sha(r.get('source_version_sha256')) or not _sha(r.get('producer_sha256')) or not _clock(r.get('available_at'))<=_clock(s.signal_asof)):_fail('BLOCKED_SOURCE_EXISTING_FROZEN_TAIL_STATE_REQUIRED')
                if not self.synthetic and self.contract.support_refs.get(r.get('source_ref'))!=r.get('source_version_sha256'):_fail('UNBOUND_EXISTING_TAIL_SOURCE_VERSION')
            effective_risk=REGIME_RISK_MAP[data.regime] if spec.get('regime')=='RISK_CONDITIONED' else spec['risk']
            record['effective_risk_method']=effective_risk
            risk=self._risk(data.risk,s,effective_risk,data.expected_risk_sha256)
            covariance_state=risk
            if risk.representation=='TAIL_SCENARIOS':
                covariance_state=self._risk(data.covariance_support,s,self.contract.tail_covariance_support[spec['risk']],data.expected_covariance_sha256)
                if risk.notes.get('cutoff')!=covariance_state.notes.get('cutoff'):_fail('TAIL_AND_COVARIANCE_SHARED_CUTOFF_REQUIRED')
            if covariance_state.representation!='COVARIANCE':_fail('COVARIANCE_SUPPORT_NOT_SCENARIO_SYNTHESIS')
            cov=np.asarray(covariance_state.covariance,float)
            if cov.shape!=(n,n) or not np.isfinite(cov).all() or not np.allclose(cov,cov.T) or np.any(np.diag(cov)<=0) or np.linalg.eigvalsh(cov).min()<-1e-12:_fail('FINITE_PSD_EXACT_COVARIANCE_REQUIRED')
            if data.scenarios is not None:
                r=data.scenarios_receipt
                if (r.get('assets')!=s.assets or r.get('asset_uids')!=s.asset_uids or r.get('identity_epochs')!=s.identity_epochs or r.get('source_sha256')!=s.source_sha256 or r.get('genuine_mature_joint_scenarios') is not True or not _clock(r.get('mature_max'))<_clock(s.history_cutoff) or r.get('payload_sha256')!=content_hash(data.scenarios)):_fail('GENUINE_FULL_DOMAIN_MATURE_SCENARIOS_REQUIRED')
            if risk.representation=='TAIL_SCENARIOS' and (data.scenarios is None or content_hash(data.scenarios)!=content_hash(risk.scenarios)):_fail('TAIL_ORIGINAL_GENUINE_SCENARIOS_REQUIRED')
            modeled=local.decision_mask[0];lock=local.reserved_mask[0]|local.sell_restricted[0]|(held&~modeled&~local.operational_mask[0])
            allowed=modeled&~lock&(local.buy_allowed[0]|held);slots=min(int(local.available_slots[0]),20-int(lock.sum()));ranks=np.argsort(np.argsort(np.asarray(s.assets),kind='stable'),kind='stable')
            state_key=content_hash((s.assets,s.asset_uids,s.identity_epochs,s.asset_sids,s.security_coordinate,s.source_support_identity,s.risk_support_identity))
            operational_key=content_hash((lock,local.buy_allowed[0],modeled,slots,s.required_assets))
            cache=self.cache.get(path_id);is_q_date=date in self.contract.q_dates
            if cache and not is_q_date and (cache['state_key']!=state_key or cache['operational_key']!=operational_key):_fail('BLOCKED_ACCOUNT_SUPPORT_CHANGE_OUTSIDE_FROZEN_Q_CLOCK')
            if spec['replacement']=='RPL3' and data.scenarios is None:_fail('REPLACEMENT_GENUINE_JOINT_SCENARIOS_REQUIRED')
            adjusted_mu=action_owner.uncertainty_mu(spec['uncertainty'],mu,sigma=sigma,q10=f.q10,disagreement=f.disagreement)
            if is_q_date:
                solve_context=(self.contract.research_id,self.contract.scientific_recipe_sha256,self.contract.source_sha256,
                    s.assets,s.asset_uids,s.identity_epochs,s.asset_sids,s.security_coordinate,
                    s.source_support_identity,s.risk_support_identity,data.expected_forecast_sha256,
                    data.expected_risk_sha256,data.expected_covariance_sha256)
                bound_solve=(lambda name,values,compute:self.solve(name,(solve_context,values),compute)) if self.solve else None
                estimate=q_owner.allocate_q(spec['q'],adjusted_mu,sigma,cov,current,lock,allowed,local.buy_allowed[0],slots,ranks,
                    scenarios=data.scenarios,prior_scale=data.prior_scale,execution_friction_bps=cost,solve=bound_solve,synthetic=self.synthetic)
                self.cache[path_id]=cache=dict(q=estimate.allocation.q.copy(),gross_cap=estimate.gross_cap,state_key=state_key,operational_key=operational_key,as_of=date)
                record.update(q_state='FROZEN_Q_CLOCK_SOLVE_OR_EXACT_COMPLETE_CONTEXT_CACHE',whole_objective_calls=estimate.whole_objective_calls)
                for name,units in estimate.deterministic_operations.items():self._count('Q_'+name,units)
            elif cache is None:_fail('NO_LEGAL_PRIOR_CARRIED_TARGET')
            else:record.update(q_state='CARRIED_TARGET_NOT_NEW_EXACT_SOLVE',whole_objective_calls=0)
            q=np.asarray(cache['q']);kwargs=dict(data.gross_inputs)
            # Risk/uncertainty input is computed from the current frozen q and
            # qualified covariance, not copied from an account's future reward.
            kwargs.update(portfolio_vol=float(np.sqrt(q@cov@q*252/5)),mu=float(mu@q),sigma=float(sigma@q),breadth=float(np.mean(mu>0)),drawdown=data.drawdown if data.drawdown is not None else 0.,regime=data.regime,dd=spec['drawdown'])
            if spec['gross'] in gross_owner.FAMILIES:
                g=data.gross_prediction
                pin=hashlib.sha256(Path(gross_owner.__file__).read_bytes()).hexdigest()
                if (not isinstance(g,FrozenGrossPrediction) or g.kind!=spec['gross'] or g.target!=gross_owner.TARGET or g.source_sha256!=s.source_sha256 or g.producer_sha256!=pin or not _sha(g.selected_recipe_sha256) or g.genuine_chronological_oof is not True or not _clock(g.fit_cutoff)<_clock(g.signal_asof)==_clock(ctx.signal_asof)):_fail('FROZEN_PRIOR_LEARNED_GROSS_PREDICTION_REQUIRED')
                kwargs['learned']=g.value
            if spec['gross']=='DRAWDOWN' and data.drawdown is None:_fail('BLOCKED_ACCOUNT_CONTINUOUS_DRAWDOWN_PREFIX_REQUIRED')
            gross_controller=action_owner.gross_value(spec['gross'],**kwargs)
            gross=min(gross_controller,float(cache['gross_cap']))
            record.update(gross_controller_cap=gross_controller,q_growth_cap=float(cache['gross_cap']),gross_effective_cap=gross)
            target=gross*q
            if spec['action']=='REPLACEMENT_COST':
                pairs=fixed_replacement_pairs(s.assets,s.asset_uids,local.current_units[0],current,target,mu,sigma,spec['replacement'])
                if data.replacement_pairs and data.replacement_pairs!=pairs:_fail('CALLER_REPLACEMENT_PAIRS_DIFFER_FROM_FROZEN_RULE')
                mapping_hash=content_hash((s.assets,s.asset_uids,local.current_units[0],current,target,mu,sigma,spec['replacement'],pairs))
                if data.replacement_mapping_sha256 and data.replacement_mapping_sha256!=mapping_hash:_fail('FROZEN_REPLACEMENT_MAPPING_CONTEXT_MISMATCH')
                record['replacement_mapping_sha256']=mapping_hash;record['replacement_pairs']=len(pairs)
                original_target=target.copy()
                for pair in pairs:
                    a,b=s.assets.index(pair.entrant),s.assets.index(pair.incumbent)
                    if lock[b]:_fail('BLOCKED_ACCOUNT_REPLACEMENT_INCUMBENT_LOCKED')
                    utility,detail=replacement_delta_utility(pair,s.assets,current,original_target,mu,sigma,cov,float(ctx.nav[0]),cost,spec['replacement'],data.scenarios)
                    if utility<=0:target[a]=0.;target[b]=current[b]
                    self._count('REPLACEMENT_UTILITY_EVALUATION')
            memory=self.memories.setdefault(path_id,action_owner.StatefulActionMemory())
            if spec['action']=='COOLDOWN':
                memory.observe(int(ctx.signal_index),float(ctx.nav[0]))
                if data.realized_turnover_previous is not None:memory.record_realized_turnover(int(ctx.signal_index)-1,data.realized_turnover_previous)
            if spec['action']=='MPC':
                if spec.get('planner')!='TWO_STEP' or action_owner.SPEC['mpc_horizon']!=2:_fail('FROZEN_TWO_STEP_MPC_REQUIRED')
                proposed=action_owner.two_step_planner(current,target,adjusted_mu,cov,cost_bps=cost,on_solve=self.on_policy_solve,on_evaluation=self.on_evaluation)
            else:
                if not hasattr(ctx,'holding_age'):_fail('BLOCKED_ACCOUNT_ACTUAL_HOLDING_AGE_REQUIRED')
                age=np.asarray(ctx.holding_age[0])[columns]
                action_kind='DIRECT' if spec['action']=='REPLACEMENT_COST' else spec['action']
                proposed=action_owner.action_target(action_kind,current,target,nav=float(ctx.nav[0]),cost_bps=cost,mu=adjusted_mu,sigma=sigma,holding_age=age,session=int(ctx.signal_index),memory=memory,regime=data.regime if spec.get('regime') in ('BAND_CONDITIONED','ACTION_BUDGET_CONDITIONED') else 'NORMAL',tail_elevated=data.tail_elevated if spec.get('tail')!='NONE' else False,on_evaluation=self.on_evaluation)
            # Preserve exact units for no-trade/locked held names. Only the
            # existing deterministic capped-cardinality projection is reused.
            preserve=lock|(held&np.isclose(proposed,current,rtol=0,atol=EPS)&~local.operational_mask[0])
            reserved=np.where(preserve,current,0.);reserved_mass=float(reserved.sum())
            if reserved_mass>gross+1e-8:_fail('BLOCKED_ACCOUNT_RESERVED_MASS_EXCEEDS_GROSS_CAP')
            upper=np.where(modeled&~preserve&local.buy_allowed[0],.1,np.where(modeled&~preserve,np.minimum(current,.1),0.))
            mass=max(0.,min(gross,float(proposed.sum()))-reserved_mass)
            final=reserved+_support_projection(np.where(upper>0,proposed-reserved,-np.inf),upper,mass,min(slots,20-int(preserve.sum())),ranks)
            explicit=modeled&~preserve
            effective=np.where(explicit,final,current)
            if (not np.isfinite(effective).all() or np.any(effective<-EPS) or effective.sum()>1+EPS or np.count_nonzero(effective>EPS)>20 or np.any(effective[explicit]>.1+EPS) or np.any(effective[~local.buy_allowed[0]]>current[~local.buy_allowed[0]]+EPS)):_fail('BLOCKED_ACCOUNT_ACTION_TARGET_FEASIBILITY')
            self._count('DAILY_ACTION_GROSS_SUPPORT_PROJECTION');record.update(projection='DETERMINISTIC_REFEASIBILITY_NOT_OPTIMIZER_EXACT_REUSE',requested_gross=gross,effective_gross=float(effective.sum()),risk_payload_sha256=data.expected_risk_sha256)
            weights=np.zeros_like(ctx.current_weights);masks=np.zeros_like(ctx.decision_mask)
            weights[0,columns]=np.where(explicit,final,0.);masks[0,columns]=explicit
            return MethodSpacePolicyResult(path_id,'POLICY_TARGET_QUALIFIED_MECHANISM_UNCERTIFIED',TargetDecision(weights,masks,'R6_METHOD_SPACE_SHARED_ACCOUNT'),record)
        except (ValueError,TypeError,KeyError,AttributeError,IndexError) as error:
            reason=str(error);status='BLOCKED_ACCOUNT' if 'ACCOUNT' in reason else 'BLOCKED_SOURCE' if 'SOURCE' in reason or 'PINNED' in reason else 'BLOCKED_INPUT'
            return MethodSpacePolicyResult(path_id,status,None,record|dict(block_reason=reason))

    def __call__(self,day,ctx):
        if self.synthetic:_fail('REAL_COMMON_ACCOUNT_CALL_REQUIRES_CANONICAL_ADMISSION')
        self._real_guard()
        if len({self.rows[p]['primary_bps'] for p in ctx.path_ids})!=1:_fail('COMMON_ACCOUNT_PATHS_MUST_SHARE_ACTUAL_FRICTION')
        weights=np.zeros_like(ctx.current_weights);masks=np.zeros_like(ctx.decision_mask)
        for r,path in enumerate(ctx.path_ids):
            local=_transport(ctx,r,np.arange(len(ctx.tickers)))
            # Keep the existing persistent context's actual holding metadata.
            if hasattr(ctx,'holding_age'):
                from scripts.research.a2.evaluation.continuous_research_account import PersistentPolicyContext
                local=PersistentPolicyContext(local,np.asarray(ctx.holding_age)[r:r+1],np.asarray(ctx.entry_date)[r:r+1],np.asarray(ctx.entry_price)[r:r+1],np.asarray(ctx.entry_execution_open)[r:r+1],np.asarray(ctx.current_units)[r:r+1])
            result=self.evaluate(day,path,local);self.diagnostics.append(result.diagnostic)
            if result.decision is None:_fail(path+':'+result.status+':'+result.diagnostic['block_reason'])
            weights[r]=result.decision.weights[0];masks[r]=result.decision.explicit_mask[0]
        return TargetDecision(weights,masks,'R6_METHOD_SPACE_SHARED_PERSISTENT_ACCOUNT')

def specification():
    return dict(schema='B_R6_METHOD_SPACE_POLICY_CONSUMER_V1',research_id=design.ID,
        account_owner='continuous_research_account.run_continuous_account; common TargetDecision',
        path_space='exact design.policy_space physical paths; no added tuples',
        controls='frozen RawA2 rank with NO_FIT semantic; not claimed genuine learned OOF; exact shared control owner',
        final_freeze_binding='constructor explicit final freeze_sha256; contract scientific_recipe_sha256 is acyclic frozen method recipe semantic identity',
        target_clock='monthly first and observed frozen structural metadata clock only',
        carried_target='not optimizer exact reuse; daily Action/Gross projection deterministic and counted',
        operational_support_change_outside_q_clock='BLOCKED_ACCOUNT_SUPPORT_CHANGE_OUTSIDE_FROZEN_Q_CLOCK',
        required_domain='FULL_REQUIRED_ELIGIBLE_PLUS_HELD_POLICY_OOF; metadata first, no alpha-only promotion',
        regime_risk_map=REGIME_RISK_MAP,regime_action_scope='only BAND_CONDITIONED or ACTION_BUDGET_CONDITIONED; NONE uses NORMAL; Gross REGIME only changes G',
        tail_action_scope='only non-NONE tail consumes pre-existing elevated flag',
        risk_method_lineage='exact native full-domain or approved classical parent posterior conditional completion; exact EMPIRICAL_CVAR joint-scenario and EVT pooled-tail IDs',
        tail_covariance_support=TAIL_COVARIANCE_SUPPORT,tail_scenarios='genuine mature full-domain observations, never posterior generated',
        real_provider='full freeze physical code pin + exact frozen source sidecar + qualification-reader attestation',
        growth='controller on frozen G grid; effective=min(controller,continuous Kelly/q cap), continuous cap allowed as independent constraint; reserved incompatibility typed BLOCKED_ACCOUNT',
        replacement_pairing='inc units>EPS and qtarget<=EPS; ent units<=EPS and qtarget>EPS; ent value descending/inc ascending; ticker thenUID; min pairs; free-slot BUY excluded',
        replacement_value='nav*min(current_inc,target_ent)*mu; RPL4 subtractsigma; actualUSDtwo-way cost; coeff1',
        replacement_variance='.5*nav*(variance_after-variance_before)',replacement_tail='nav*(empiricalCVaRafter-before); fixedalpha.9; q90+meanpositiveexcess/.1',
        mpc_horizon=2,cost_bps=(5,10,20),real_activation='canonical guard_numeric and full physical contract body',
        physical_fit_count=0,account_implementation_added=False,strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
