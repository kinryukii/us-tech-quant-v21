"""Input-only frozen family transport into current Q/action/G and common account.

No numeric readers, risk/alpha fits, selector, optimizer or account are added.
Caller qualification binds prior feature/raw/UID pool and exact existing alpha
producer/receipt/column semantics before an economic replay token can be issued.
The caller must also prove the frozen P2 RMS payload originated in the pinned
B_META_equal artifact; a matching producer label is not that upstream proof.
"""
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import Mapping
from types import MappingProxyType
import numpy as np
import pandas as pd
from scripts.research.a2.portfolio import shared_joint_adapter_r2 as ad
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.inference.joint_portfolio_policy import JointResearchPolicy
from scripts.research.a2.evaluation.joint_method_accounts import PARAMETERS
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

POOL_RULE = "PRIOR_ACCEPTED_FEATURE_AND_RAW_ROW_AND_KNOWN_UID_NO_LABEL_OR_OUTCOME_SCREEN"
WEAK_SCOPE = "UNCERTIFIED_UNCERTAINTY_PROXY_NO_COVERAGE_CLAIM"
P2_RMS_SEMANTIC = "B_META_equal.prior_OOF_error_RMS"


class FamilyPolicyBlocked(ad.AdapterBlocked):
    pass


def source_pins():
    from scripts.research.a2.evaluation import continuous_research_account, joint_method_accounts
    from scripts.research.a2.inference import joint_portfolio_policy, joint_stateful_policy
    from scripts.research.a2.portfolio import joint_allocation_methods
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account
    modules = (ad, continuous_research_account, joint_method_accounts, joint_portfolio_policy,
               joint_stateful_policy, joint_allocation_methods, fast_account)
    paths = [Path(m.__file__).resolve() for m in modules]+[Path(__file__).resolve()]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


@dataclass(frozen=True)
class FrozenFamilyRow:
    id: str
    prediction: str
    risk: str
    optimizer: str
    action: str
    gross: str
    cost_bps: int = 10
    scope: str = "MAIN"
    seed: int = 20260928
    configs: int = 1


@dataclass(frozen=True)
class FrozenProducerRef:
    producer_id: str
    producer_sha256: str
    receipt_sha256: str
    value_field: str
    semantic: str


@dataclass(frozen=True)
class FrozenFamilyPolicyContract:
    research_id: str
    run_id: str
    family_freeze_sha256: str
    prediction_clarification_sha256: str
    alpha_reuse_receipt_sha256: str
    source_contract_sha256: str
    rows: tuple[FrozenFamilyRow, ...]
    # Keys are exact prediction:application-year, never guessed from column names.
    forecast_lineage: Mapping[str, tuple[FrozenProducerRef, ...]]
    source_sha256: Mapping[str, str]
    strict_PIT_promotion_eligible: bool = False
    quote_qualified: bool = False
    certified_NAV: bool = False

    def digest(self): return content_hash(self)


@dataclass(frozen=True)
class FrozenFamilyPolicyToken:
    research_id: str
    run_id: str
    family_freeze_sha256: str
    path_ids: tuple[str, ...]
    mode: str = "SUPPORT_DISCOVERY"
    strict_PIT_promotion_eligible: bool = False

    def digest(self): return content_hash(self)


@dataclass(frozen=True)
class FrozenRiskPoolReceipt:
    master_assets: tuple[str, ...]
    assets: tuple[str, ...]
    cutoff: str
    identity_epoch: str
    prior_accepted_features: tuple[bool, ...]
    prior_raw_rows: tuple[bool, ...]
    prior_known_uids: tuple[str | None, ...]
    source_contract_sha256: str
    pool_rule: str = POOL_RULE

    def digest(self): return content_hash(self)

    def validate(self, state, master, expected_sha, contract):
        if self.digest() != expected_sha or self.pool_rule != POOL_RULE:
            raise FamilyPolicyBlocked("EXACT_PRIOR_INPUT_POOL_RECEIPT_REQUIRED")
        if (self.master_assets != tuple(master) or len(set(master)) != len(master) or
                self.assets != tuple(state.assets) or self.identity_epoch != state.identity_epoch or
                self.source_contract_sha256 != contract.source_contract_sha256 or
                ad._stamp(self.cutoff, "pool_cutoff") != ad._stamp(state.cutoff, "risk_cutoff")):
            raise FamilyPolicyBlocked("RISK_POOL_MASTER_ASSETS_CUTOFF_OR_EPOCH_MISMATCH")
        n = len(master)
        if not all(len(v) == n for v in (self.prior_accepted_features, self.prior_raw_rows, self.prior_known_uids)):
            raise FamilyPolicyBlocked("FULL_PRIOR_POOL_METADATA_TOPOLOGY_REQUIRED")
        if any(type(v) is not bool for v in self.prior_accepted_features+self.prior_raw_rows):
            raise FamilyPolicyBlocked("EXPLICIT_PRIOR_POOL_FLAGS_REQUIRED")
        selected = tuple(a for a, feature, raw in zip(master, self.prior_accepted_features,
            self.prior_raw_rows) if feature and raw)
        uids=tuple(self.prior_known_uids[self.master_assets.index(a)] for a in selected)
        if any(not isinstance(uid,str) or not uid.strip() for uid in uids) or len(set(uids))!=len(uids):
            raise FamilyPolicyBlocked("FULL_REQUESTED_PRIOR_POOL_UNKNOWN_OR_AMBIGUOUS_UID")
        if selected != self.assets:
            raise FamilyPolicyBlocked("PRIOR_POOL_SHRINK_OR_RISK_PADDING_FORBIDDEN")
        for asset in selected:
            uid = self.prior_known_uids[self.master_assets.index(asset)]
            if state.coverage.get(asset, {}).get("uid") != uid:
                raise FamilyPolicyBlocked("RISK_POOL_KNOWN_UID_SWAP")


@dataclass(frozen=True)
class FrozenForecastSlice:
    prediction: str
    assets: tuple[str, ...]
    signal_asof: str
    fit_cutoff: str
    available_at: str
    mu: tuple[float, ...]
    uncertainty: tuple[float, ...]
    producer_refs: tuple[FrozenProducerRef, ...]
    source_contract_sha256: str
    family_freeze_sha256: str
    prediction_clarification_sha256: str
    members: tuple[str, ...] = ()
    uncertainty_scope: str = WEAK_SCOPE
    strict_PIT_promotion_eligible: bool = False
    calibrated_uncertainty_certified: bool = False

    def digest(self): return content_hash(self)


@dataclass(frozen=True)
class FamilyPolicyInputs:
    forecast: FrozenForecastSlice
    expected_forecast_sha256: str
    risk_state: object = None
    risk_use_receipt: object = None
    expected_risk_use_sha256: str = ""
    pool_receipt: FrozenRiskPoolReceipt | None = None
    expected_pool_sha256: str = ""
    prior_cutoff: str = ""
    p2_receipt: object = None
    expected_p2_sha256: str = ""
    scenarios: object = None
    expected_scenario_sha256: str = ""


@dataclass(frozen=True)
class FamilyPolicyResult:
    path_id: str
    status: str
    decision: object
    diagnostic: Mapping[str, object]
    physical_fit_count: int = 0
    account_replay_count: int = 0
    strict_PIT_promotion_eligible: bool = False
    certified_NAV: bool = False
    quote_qualified: bool = False


def _transport(ctx, row, columns):
    common = ctx.common if hasattr(ctx, "common") else ctx
    vectors = ("current_units", "current_weights", "reserved_mask", "buy_allowed", "sell_restricted",
               "input_present", "decision_mask", "operational_mask")
    scalars = ("cash", "cash_weight", "nav", "reserved_weight", "reserved_slots", "available_budget", "available_slots")
    values = {k: np.asarray(getattr(common,k))[row:row+1,columns].copy() for k in vectors}
    values.update({k: np.asarray(getattr(common,k))[row:row+1].copy() for k in scalars})
    return replace(common, path_ids=(common.path_ids[row],), tickers=np.asarray(common.tickers)[columns].copy(), **values)


class FrozenHistoryFamilyPolicy:
    """Qualification uses evaluate; account invocation additionally needs a token.

    input_provider(day, FrozenFamilyRow, single_master_ctx) returns frozen input
    dependencies. It must not fit, fetch or load account outcomes. A typed BLOCK
    aborts account invocation; no cash-only substitute or automatic replay lives
    here. Caller groups paths by cost and calls the unchanged common account.
    """
    def __init__(self, contract, *, expected_contract_sha256, activation, expected_activation_sha256,
                 token, expected_token_sha256, input_provider):
        if (not isinstance(contract,FrozenFamilyPolicyContract) or contract.digest()!=expected_contract_sha256 or
                not isinstance(activation,ad.FrozenMechanismActivation) or activation.digest()!=expected_activation_sha256 or
                not isinstance(token,FrozenFamilyPolicyToken) or token.digest()!=expected_token_sha256):
            raise FamilyPolicyBlocked("FROZEN_FAMILY_ACTIVATION_CONTRACT_TOKEN_REQUIRED")
        if (contract.strict_PIT_promotion_eligible is not False or contract.quote_qualified is not False or
                contract.certified_NAV is not False or token.strict_PIT_promotion_eligible is not False or
                token.mode not in ("SUPPORT_DISCOVERY","ACCOUNT_REPLAY") or
                (contract.research_id,contract.run_id,contract.family_freeze_sha256) !=
                    (activation.research_id,activation.run_id,activation.family_freeze_sha256) or
                (token.research_id,token.run_id,token.family_freeze_sha256) !=
                    (contract.research_id,contract.run_id,contract.family_freeze_sha256) or
                contract.source_contract_sha256!=activation.scientific_contract_sha256 or
                not all(ad._sha(v) for v in (contract.family_freeze_sha256,contract.prediction_clarification_sha256,
                    contract.alpha_reuse_receipt_sha256,contract.source_contract_sha256)) or
                contract.source_sha256 != source_pins() or not callable(input_provider)):
            raise FamilyPolicyBlocked("EXACT_UNCERTIFIED_FAMILY_SOURCE_BINDING_REQUIRED")
        self.rows = MappingProxyType({r.id:r for r in contract.rows})
        if len(self.rows)!=len(contract.rows) or not set(token.path_ids).issubset(self.rows) or len(set(token.path_ids))!=len(token.path_ids):
            raise FamilyPolicyBlocked("EXACT_UNIQUE_FROZEN_FAMILY_PATHS_REQUIRED")
        for r in contract.rows:
            if (r.configs!=1 or r.seed!=20260928 or type(r.cost_bps) is not int or r.cost_bps not in (5,10,20) or
                    r.scope not in ("MAIN","SENSITIVITY_NO_SELECTION") or
                    (r.scope=="MAIN" and r.cost_bps!=10) or
                    (r.risk!="NONE" and (r.risk not in activation.allowed_risk_methods or r.prediction not in ("P0","P1","P2") or
                        r.optimizer not in activation.allowed_q_roles or r.action not in activation.allowed_action_roles or r.gross not in activation.allowed_gross_roles)) or
                    (r.risk=="NONE" and (r.prediction!="RAW_RANK" or r.optimizer not in ("RAW_FIXED_SCORE","SIMPLE_EQUAL")))):
                raise FamilyPolicyBlocked("UNDECLARED_FAMILY_COMBINATION_OR_SENSITIVITY")
        self.contract,self.activation,self.token=contract,activation,token
        self.activation_sha=expected_activation_sha256; self.provider=input_provider
        self.contract_sha=expected_contract_sha256; self.token_sha=expected_token_sha256
        self.diagnostics=[]

    def _validate_frozen_contract(self):
        if self.contract.digest()!=self.contract_sha or self.token.digest()!=self.token_sha:
            raise FamilyPolicyBlocked("FROZEN_FAMILY_CONTRACT_OR_TOKEN_MUTATION")

    def friction_contract(self, path_id):
        self._validate_frozen_contract()
        row=self.rows[path_id]
        return dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE",one_way_bps=row.cost_bps,fee_bps=0,
            benchmark="NEXT_RAW_OPEN",authority="HYPOTHETICAL_RESEARCH_SCENARIO",
            scenario_id=self.contract.research_id+"::"+str(row.cost_bps)+"bps")

    def evaluate(self, day, path_id, ctx, inputs=None):
        row=self.rows.get(path_id)
        if row is None:
            return FamilyPolicyResult(path_id,"BLOCKED_MECHANISM_POLICY",None,{"block_reason":"UNDECLARED_FAMILY_PATH"})
        record=dict(path_id=path_id,prediction=row.prediction,risk=row.risk,cost_bps=row.cost_bps,
            scope=row.scope,source_authority="UNKNOWN",strict_PIT_promotion_eligible=False,
            calibrated_uncertainty_certified=False,family_freeze_sha256=self.contract.family_freeze_sha256)
        try:
            self._validate_frozen_contract()
            if path_id not in self.token.path_ids or tuple(ctx.path_ids)!=(path_id,):
                raise FamilyPolicyBlocked("PATH_CONTEXT_OR_TOKEN_MISMATCH")
            asof=ad._stamp(ctx.signal_asof,"decision_asof")
            self.activation.validate(self.activation_sha,asof)
            data=inputs if inputs is not None else self.provider(day,row,ctx)
            if not isinstance(data,FamilyPolicyInputs): raise FamilyPolicyBlocked("TYPED_FROZEN_POLICY_INPUTS_REQUIRED")
            f=data.forecast
            if not isinstance(f,FrozenForecastSlice) or f.digest()!=data.expected_forecast_sha256:
                raise FamilyPolicyBlocked("FROZEN_FORECAST_SLICE_MUTATION")
            key=row.prediction+":"+str(asof.year)
            if (f.prediction!=row.prediction or f.producer_refs!=self.contract.forecast_lineage.get(key) or
                    not f.producer_refs or any(not ad._sha(v.producer_sha256) or not ad._sha(v.receipt_sha256) or
                        not v.producer_id or not v.value_field or not v.semantic for v in f.producer_refs) or
                    f.source_contract_sha256!=self.contract.source_contract_sha256 or
                    f.family_freeze_sha256!=self.contract.family_freeze_sha256 or
                    f.prediction_clarification_sha256!=self.contract.prediction_clarification_sha256 or
                    f.strict_PIT_promotion_eligible is not False or f.calibrated_uncertainty_certified is not False or
                    f.uncertainty_scope!=WEAK_SCOPE or ad._stamp(f.signal_asof,"forecast_asof")!=asof or
                    not ad._stamp(f.fit_cutoff,"forecast_cutoff") <= ad._stamp(f.available_at,"forecast_available") <= asof or
                    not ad._pre2026(ad._stamp(f.fit_cutoff,"forecast_cutoff"))):
                raise FamilyPolicyBlocked("FORECAST_PRODUCER_RECEIPT_COLUMN_SEMANTIC_OR_CLOCK_MISMATCH")
            master=tuple(str(v) for v in ctx.tickers)
            if row.risk=="NONE":
                if f.assets!=master: raise FamilyPolicyBlocked("RAW_CONTROL_MASTER_COORDINATE_MISMATCH")
                needed=(ctx.current_units[0]>ad.EPS) | (ctx.current_weights[0]>ad.EPS) | (ctx.decision_mask[0]&ctx.buy_allowed[0])
                mu,sigma=ad._required_forecasts(f.mu,f.uncertainty,len(master),needed)
                kind="raw" if row.optimizer=="RAW_FIXED_SCORE" else "simple"
                policy=JointResearchPolicy((path_id,),mu[None,None,:],sigma[None,None,:],{},
                    roles={path_id:dict(kind=kind)},parameters=PARAMETERS)
                decision=policy(0,ctx)
            else:
                state=data.risk_state
                if state is None or state.status!="PASS_FROZEN_HISTORY_MECHANISM":
                    raise FamilyPolicyBlocked("FULL_POOL_RISK_STATE_BLOCKED:"+str(getattr(state,"notes",{}).get("block_reason","MISSING_STATE")))
                if state.method!=row.risk or not isinstance(data.pool_receipt,FrozenRiskPoolReceipt):
                    raise FamilyPolicyBlocked("FROZEN_RISK_METHOD_OR_PRIOR_POOL_REQUIRED")
                data.pool_receipt.validate(state,master,data.expected_pool_sha256,self.contract)
                columns=pd.Index(master).get_indexer(state.assets)
                if np.any(columns<0): raise FamilyPolicyBlocked("RISK_STATE_ASSET_NOT_IN_MASTER")
                in_pool=np.zeros(len(master),bool); in_pool[columns]=True
                required=(ctx.current_units[0]>ad.EPS) | (ctx.current_weights[0]>ad.EPS) | (ctx.decision_mask[0] & ctx.buy_allowed[0])
                missing=tuple(np.asarray(master)[required & ~in_pool])
                if missing:
                    record["missing_required_risk_assets"]=missing
                    raise FamilyPolicyBlocked("ACTUAL_REQUIRED_ASSET_OUTSIDE_FROZEN_RISK_DOMAIN")
                if f.assets!=tuple(state.assets): raise FamilyPolicyBlocked("FORECAST_EXACT_RISK_POOL_COORDINATE_MISMATCH")
                local=_transport(ctx,0,columns)
                required=(local.current_units[0]>ad.EPS) | (local.current_weights[0]>ad.EPS) | (local.decision_mask[0]&local.buy_allowed[0])
                support=ad.FrozenForecastSupport(tuple(state.assets),tuple(np.asarray(state.assets)[required]),str(asof)).seal()
                mu,sigma=np.asarray(f.mu,dtype=object),np.asarray(f.uncertainty,dtype=object)
                if mu.shape!=(len(state.assets),) or sigma.shape!=mu.shape:
                    raise FamilyPolicyBlocked("FORECAST_FULL_RISK_POOL_VECTOR_TOPOLOGY_REQUIRED")
                if row.prediction in ("P1","P2") and f.members!=ad.P2_MEMBERS:
                    raise FamilyPolicyBlocked("CANONICAL_FIVE_BRIDGED_MEMBER_LINEAGE_REQUIRED")
                if row.prediction=="P2":
                    if not any(v.producer_id=="B_META_equal" and v.semantic==P2_RMS_SEMANTIC and v.value_field=="prior_OOF_error_RMS" for v in f.producer_refs):
                        raise FamilyPolicyBlocked("EXACT_B_META_EQUAL_PRIOR_OOF_ERROR_RMS_SOURCE_REQUIRED")
                    p=data.p2_receipt
                    if p is None: raise FamilyPolicyBlocked("FROZEN_P2_RECEIPT_REQUIRED")
                    if (not isinstance(p,ad.FrozenCalibratedOOFReceipt) or
                            p.prior_rms_coverage!="GENUINE_CHRONOLOGICAL_OOF_RMS" or p.genuine_chronological_oof is not True):
                        raise FamilyPolicyBlocked("FAMILY_P2_REQUIRES_FROZEN_GENUINE_EQUAL_PRIOR_OOF_RMS")
                    output=ad.compute_p2_disagreement(p,assets=state.assets,as_of=asof,prior_cutoff=data.prior_cutoff,
                        expected_source=ad.FrozenSourceBinding.from_receipt(state.source_receipt),expected_receipt_sha256=data.expected_p2_sha256,
                        execution_mode="frozen_history_mechanism",mechanism_activation=self.activation,
                        expected_activation_sha256=self.activation_sha,forecast_support=support,
                        expected_forecast_support_sha256=support.frozen_sha256)
                    if not np.allclose(np.asarray(mu[required],float),output.calibrated_mean[required],rtol=1e-12,atol=1e-15):
                        raise FamilyPolicyBlocked("P2_MEAN_MUST_EQUAL_FROZEN_FIVE_MEMBER_MEAN")
                    sigma=output.sigma
                    record.update(uncertainty_origin=P2_RMS_SEMANTIC+" + population_var(five bridged mu)",weak_source=True,
                        calibrated_uncertainty_certified=False,p2_receipt_sha256=output.receipt_sha256)
                result=ad.SharedJointAdapter(q_role=row.optimizer,action_role=row.action,gross_role=row.gross).evaluate(
                    state,mu,sigma,local,expected_source=ad.FrozenSourceBinding.from_receipt(state.source_receipt),
                    prior_cutoff=data.prior_cutoff,execution_mode="frozen_history_mechanism",mechanism_activation=self.activation,
                    expected_activation_sha256=self.activation_sha,state_use_receipt=data.risk_use_receipt,
                    expected_state_use_sha256=data.expected_risk_use_sha256,scenarios=data.scenarios,
                    expected_scenario_sha256=data.expected_scenario_sha256,cost_bps=row.cost_bps,
                    forecast_support=support,expected_forecast_support_sha256=support.frozen_sha256)
                weights=np.zeros((1,len(master))); explicit=np.zeros((1,len(master)),bool)
                weights[0,columns]=result.target.weights; explicit[0,columns]=result.target.explicit_mask
                decision=TargetDecision(weights,explicit,"FROZEN_EXACT_RISK_POOL_TRANSPORT")
                record.update(risk_state_id=state.risk_state_id,risk_pool_assets=tuple(state.assets),
                    required_forecast_assets=support.required_assets,forecast_support_sha256=support.frozen_sha256,
                    forecast_support_basis=support.basis,
                    transported_unknown_risk_cells=0,signal_turnover_penalty_bps=result.execution_friction_bps,
                    account_execution_friction_bps=result.account_execution_friction_bps)
            return FamilyPolicyResult(path_id,"MECHANISM_POLICY_INPUTS_QUALIFIED_UNCERTIFIED",decision,record)
        except (ad.AdapterBlocked,ValueError,TypeError,KeyError,AttributeError) as error:
            record["block_reason"]=str(error)
            return FamilyPolicyResult(path_id,"BLOCKED_MECHANISM_POLICY",None,record)

    def __call__(self,day,ctx):
        self._validate_frozen_contract()
        if self.token.mode!="ACCOUNT_REPLAY": raise FamilyPolicyBlocked("ACCOUNT_REPLAY_TOKEN_REQUIRED_NO_SUPPORT_REPLAY")
        if len({self.rows[p].cost_bps for p in ctx.path_ids})!=1:
            raise FamilyPolicyBlocked("COMMON_ACCOUNT_PATHS_MUST_SHARE_EXACT_COST_CONTRACT")
        weights=np.zeros_like(ctx.current_weights); masks=np.zeros_like(ctx.decision_mask)
        for r,path in enumerate(ctx.path_ids):
            local=_transport(ctx,r,np.arange(len(ctx.tickers)))
            result=self.evaluate(day,path,local); self.diagnostics.append(result.diagnostic)
            if result.decision is None: raise FamilyPolicyBlocked(path+":"+str(result.diagnostic["block_reason"]))
            weights[r]=result.decision.weights[0]; masks[r]=result.decision.explicit_mask[0]
        return TargetDecision(weights,masks,"FROZEN_HISTORY_FAMILY_R3")
