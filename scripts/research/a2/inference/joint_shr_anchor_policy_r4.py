"""Four explicitly authorized R4 SHR anchors over existing Q0/A0/G0 primitives.

Original R3 method/status guards remain intact. No fitting, input reader,
account engine, source certification, altered covariance or candidate search.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt
from scripts.research.a2.portfolio.shared_joint_adapter_r2 import (
    AdapterBlocked, _stamp, _pre2026, _required_forecasts, risk_state_sha256, EPS)
from scripts.research.a2.inference.joint_frozen_history_policy_r3 import _transport
from scripts.research.a2.portfolio.joint_allocation_methods import allocate_q, exposure, TradingControlPolicy
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

METHODS=("SHR_HP", "SHR_EB", "SHR_CC", "SHR_FACTOR")

@dataclass(frozen=True)
class AnchorContract:
    research_id: str
    matrix_sha256: str
    source_authority_sha256: str
    scope_authorisation_sha256: str
    cost_bps: int=10
    prediction: str="P0"
    optimizer: str="Q0"
    action: str="A0"
    gross: str="G0"
    strict_PIT_promotion_eligible: bool=False
    quote_qualified: bool=False
    certified_nav_qualified: bool=False
    def digest(self): return content_hash(self)
    def validate(self, expected):
        if self.digest()!=expected or self.research_id!="V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4":
            raise AdapterBlocked("EXACT_R4_ANCHOR_CONTRACT_REQUIRED")
        if (self.cost_bps,self.prediction,self.optimizer,self.action,self.gross)!=(10,"P0","Q0","A0","G0"):
            raise AdapterBlocked("ONLY_FOUR_AUTHORISED_P0_Q0_A0_G0_10BPS_ANCHORS")
        if any((self.strict_PIT_promotion_eligible,self.quote_qualified,self.certified_nav_qualified)):
            raise AdapterBlocked("SHR_ANCHOR_CANNOT_UPGRADE_AUTHORITY")
        for value in (self.matrix_sha256,self.source_authority_sha256,self.scope_authorisation_sha256):
            if len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
                raise AdapterBlocked("EXACT_FROZEN_ANCHOR_SHA_REQUIRED")

@dataclass(frozen=True)
class AnchorUse:
    method: str
    risk_state_id: str
    risk_state_sha256: str
    as_of: str
    cutoff: str
    next_refresh_as_of: str
    pool_assets: tuple
    pool_uids: tuple
    source_authority_sha256: str
    p0_receipt_sha256: str
    p0_fit_cutoff: str
    p0_matured_max: str
    synthetic: bool=False
    def digest(self): return content_hash(self)

class ShrAnchorPolicy:
    """input_provider is qualification-bound; blocked dependency aborts the path."""
    def __init__(self,contract,expected_contract_sha256,input_provider,*,mode="SUPPORT_DISCOVERY"):
        contract.validate(expected_contract_sha256)
        if mode not in ("SUPPORT_DISCOVERY","ACCOUNT_REPLAY") or not callable(input_provider):
            raise AdapterBlocked("EXPLICIT_ANCHOR_PHASE_REQUIRED")
        self.contract,self.expected,self.provider,self.mode=contract,expected_contract_sha256,input_provider,mode
        self.diagnostics=[]

    def evaluate(self,day,path_id,ctx,data=None):
        self.contract.validate(self.expected)
        data=self.provider(day,path_id,ctx) if data is None else data
        use,state=data["use"],data["state"]
        if not isinstance(use,AnchorUse) or use.digest()!=data["expected_use_sha256"]:
            raise AdapterBlocked("EXACT_SHR_USE_RECEIPT_REQUIRED")
        if (use.method not in METHODS or path_id!="R4_SHR_ANCHOR_"+use.method
            or state.method!=use.method or use.risk_state_id!=state.risk_state_id
            or use.risk_state_sha256!=risk_state_sha256(state)):
            raise AdapterBlocked("SHR_STATE_ID_OR_METHOD_SUBSTITUTION")
        receipt = SourceReceipt(**state.source_receipt) if isinstance(state.source_receipt,dict) else state.source_receipt
        if not isinstance(receipt, SourceReceipt):
            raise AdapterBlocked("TYPED_SHR_SOURCE_RECEIPT_REQUIRED")
        if (state.status!="CONDITIONAL_FROZEN_HISTORY_MECHANISM" or state.horizon!=5
            or state.blocked_assets or use.pool_assets!=tuple(state.assets)
            or use.source_authority_sha256!=self.contract.source_authority_sha256
            or receipt.scientific_contract_sha256!=use.source_authority_sha256
            or receipt.scientific_contract_identity!=self.contract.research_id
            or receipt.synthetic!=use.synthetic):
            raise AdapterBlocked("SHR_CONDITIONAL_FULL_POOL_SOURCE_REQUIRED")
        if use.synthetic and self.mode=="ACCOUNT_REPLAY":
            raise AdapterBlocked("SYNTHETIC_CANNOT_ACTIVATE_REAL_ACCOUNT")
        asof=_stamp(ctx.signal_asof,"decision_asof"); cutoff=_stamp(use.cutoff,"use_cutoff")
        receipt.validate(cutoff)
        fit=_stamp(use.as_of,"fit_asof"); refresh=_stamp(use.next_refresh_as_of,"refresh")
        if (asof.tzinfo is None or not _pre2026(asof) or not cutoff<fit<=asof<refresh
            or _stamp(state.as_of,"state_asof")!=fit or _stamp(state.cutoff,"state_cutoff")!=cutoff
            or not _stamp(use.p0_fit_cutoff,"p0_exclusive_fit_cutoff")<=fit
            or not _stamp(use.p0_matured_max,"p0_latest_matured_observation")<=cutoff
            or not _stamp(use.p0_matured_max,"p0_latest_matured_observation")<_stamp(use.p0_fit_cutoff,"p0_exclusive_fit_cutoff")
            or len(use.p0_receipt_sha256)!=64):
            raise AdapterBlocked("SHR_OR_P0_FUTURE_CUTOFF_OR_EXPIRED_QUARTER")
        if tuple(data["current_pool_assets"])!=use.pool_assets or tuple(data["current_pool_uids"])!=use.pool_uids:
            raise AdapterBlocked("DAILY_FULL_POOL_OR_SECURITY_IDENTITY_CHANGED")
        if any(state.coverage.get(a,{}).get("uid")!=uid for a,uid in zip(use.pool_assets,use.pool_uids)):
            raise AdapterBlocked("EXACT_SOURCE_SECURITY_UID_REQUIRED")
        master=tuple(map(str,ctx.tickers)); columns=pd.Index(master).get_indexer(state.assets)
        if np.any(columns<0) or len(ctx.path_ids)!=1 or ctx.path_ids[0]!=path_id:
            raise AdapterBlocked("EXACT_MASTER_PATH_COORDINATE_REQUIRED")
        required=(ctx.current_units[0]>EPS)|(ctx.current_weights[0]>EPS)|(ctx.decision_mask[0]&ctx.buy_allowed[0])
        in_pool=np.zeros(len(master),bool); in_pool[columns]=True
        if np.any(required&~in_pool):
            raise AdapterBlocked("ACTUAL_REQUIRED_ASSET_OUTSIDE_FROZEN_SHR_DOMAIN")
        local=_transport(ctx,0,columns);n=len(columns)
        required=(local.current_units[0]>EPS)|(local.current_weights[0]>EPS)|(local.decision_mask[0]&local.buy_allowed[0])
        mean,sigma=_required_forecasts(data["mu"],data["uncertainty"],n,required)
        covariance=np.asarray(state.covariance,float)
        if (covariance.shape!=(n,n) or not np.isfinite(covariance).all()
            or not np.allclose(covariance,covariance.T,atol=1e-12,rtol=0)
            or np.linalg.eigvalsh(covariance).min()<-1e-12 or np.any(np.diag(covariance)<=0)):
            raise AdapterBlocked("INVALID_UNCHANGED_SHR_COVARIANCE")
        if (local.max_positions,local.max_weight,local.max_invested)!=(20,.1,1.):
            raise AdapterBlocked("FROZEN_ACCOUNT_FEASIBILITY_REQUIRED")
        current=np.asarray(local.current_weights[0],float)
        ranks=np.argsort(np.argsort(np.asarray(state.assets),kind="stable"),kind="stable")
        capture=[]
        def base(_,gated):
            held=gated.current_units[0]>EPS; modeled=gated.decision_mask[0]
            locked=gated.reserved_mask[0]|(held&~modeled&~gated.operational_mask[0])
            reserved=np.where(locked,current,0.)
            allowed=modeled&~locked&(gated.buy_allowed[0]|held)
            solved=allocate_q("mean_variance",mean,sigma,covariance,current,locked,allowed,
                gated.buy_allowed[0],20-int(locked.sum()),ranks)
            composition,gross=exposure(solved.q,covariance,reserved,"fixed",mu=mean,uncertainty=sigma)
            capture.append(solved)
            return TargetDecision((gross*composition-reserved)[None,:],(modeled&~locked)[None,:])
        decision=TradingControlPolicy(base,"partial_rebalance")(0,local)
        effective=np.where(decision.explicit_mask[0],decision.weights[0],current)
        if (not np.isfinite(effective).all() or np.any(effective<-EPS) or effective.sum()>1+EPS
            or np.count_nonzero(effective>EPS)>20 or np.any(effective[decision.explicit_mask[0]]>.1+EPS)
            or np.any(effective[~local.buy_allowed[0]]>current[~local.buy_allowed[0]]+EPS)):
            raise AdapterBlocked("SHR_ACTION_TARGET_FEASIBILITY_FAILED")
        weights=np.zeros_like(ctx.current_weights); masks=np.zeros_like(ctx.decision_mask)
        weights[0,columns]=decision.weights[0];masks[0,columns]=decision.explicit_mask[0]
        self.diagnostics.append(dict(path_id=path_id,risk_state_id=state.risk_state_id,
            as_of=str(asof),status="CONDITIONAL_MECHANISM_POLICY_INPUTS_QUALIFIED",
            covariance_modified=False,source_authority_upgraded=False,q_solver_status=capture[0].status))
        return TargetDecision(weights,masks,"R4_SHR_ANCHOR_EXACT_POOL_TRANSPORT")
    def __call__(self,day,ctx):
        if self.mode!="ACCOUNT_REPLAY":
            raise AdapterBlocked("QUALIFICATION_ONLY_NO_ECONOMIC_REPLAY")
        return self.evaluate(day,ctx.path_ids[0],ctx)
