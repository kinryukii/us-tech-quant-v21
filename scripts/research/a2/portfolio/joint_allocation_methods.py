"""V24 allocation and exposure variants over the single common JOINT policy.

Inputs are caller-proven PIT forecasts, frozen five-session risk and scenarios.
All candidates remain in the cardinality projection; no Raw Top20 prefilter.
"""
from __future__ import annotations
from dataclasses import dataclass
import ast
import hashlib
from pathlib import Path
import numpy as np
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform
from scipy.sparse.linalg import cg, LinearOperator

from scripts.research.a2.inference.joint_portfolio_policy import (
    JointResearchPolicy, InfeasiblePolicy, EPS, _support_projection, _capped_mass, _covariance_action,
)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.optimization import _smooth_cvar
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision

SPEC = dict(horizon_sessions=5, annualization=252/5, iterations=128, tolerance=2e-6,max_q=.1,
            risk_penalty=4., uncertainty_penalty=.5, shrinkage=.5, l2_weight=.01,
            l1_turnover=.001,l2_turnover=.01,turnover_limit=.20,
            cvar_alpha=.90,cvar_epsilon=.0005,bl_tau=.05,
            no_trade_band=.0025,minimum_trade_usd=1.,partial_rebalance=.5,
            risk_budget="fixed 1+(stable ticker rank mod 3), normalized",
            volatility_target_annual=.10, fixed_gross=1.)
ALIASES = {"mean_es":"mean_cvar","kelly":"log_growth",
           "concentration_penalty":"l2_weight",
           "cost_aware":"mean_variance","l1_weight":"mean_variance",
           "risk_constrained_cash":"volatility_targeting", "turnover_limit":"mean_variance",
           "uncertainty_penalty":"robust_mean_variance"}
ALLOCATION_METHODS = (
    "equal_weight","positive_equal","inverse_volatility","gmv","erc","risk_budgeting","hrp",
    "mean_variance","robust_mean_variance","mean_cvar","mean_es","mean_semivariance",
    "kelly","log_growth","expected_return_shrinkage","uncertainty_penalty","black_litterman",
    "l2_weight","l1_weight","concentration_penalty","reference_regularization",
    "tracking_error","cost_aware","l1_turnover","l2_turnover","turnover_limit",
)
CONTROL_METHODS = ("no_trade_band","buy_hold_hysteresis","partial_rebalance","minimum_trade",
                   "discrete_allocation","fractional_allocation","participation_constraint","liquidity_constraint","turnover_limit")
GROSS_METHODS = ("fixed","volatility_targeting","risk_constrained_cash","dynamic",
                 "separate_composition_exposure")


class AllocationUnavailable(InfeasiblePolicy):
    pass


@dataclass
class AllocationResult:
    q: np.ndarray
    iterations: int
    residual: float
    objective: float
    status: str
    equivalence: str = ""
    global_optimum_claim: bool = False


def _hrp(covariance, ids):
    sub = covariance[np.ix_(ids,ids)] if covariance.ndim==2 else np.diag(covariance[ids])
    sd = np.sqrt(np.maximum(np.diag(sub),1e-12))
    corr = np.clip(sub/np.outer(sd,sd),-1,1)
    distance = np.sqrt(np.maximum(0,(1-corr)/2))
    np.fill_diagonal(distance,0)
    order = leaves_list(linkage(squareform(distance,checks=False),method="single"))
    result = np.ones(len(ids))
    clusters = [list(order)]
    while clusters:
        following=[]
        for cluster in clusters:
            if len(cluster)<2:
                continue
            a,b=cluster[:len(cluster)//2],cluster[len(cluster)//2:]
            def variance(indices):
                c=sub[np.ix_(indices,indices)]
                w=1/np.maximum(np.diag(c),1e-12)
                w/=w.sum()
                return float(w@c@w)
            va,vb=variance(a),variance(b)
            fraction=vb/max(va+vb,1e-12)
            result[a]*=fraction;result[b]*=1-fraction
            following.extend([a,b])
        clusters=following
    return result/result.sum()


def allocate_q(method,mu,uncertainty,covariance,current,locked,allowed,buy_allowed,slots,ticker_rank,
               *, scenarios=None,reference=None,parameters=None):
    """Constrained full-candidate solve; numerical limits remain explicit."""
    if method not in ALLOCATION_METHODS:
        raise AllocationUnavailable("UNKNOWN_ALLOCATION_METHOD")
    requested=method
    method=ALIASES.get(method,method)
    for key,value in (parameters or {}).items():
        if key not in SPEC or value != SPEC[key]:
            raise ValueError("UNREGISTERED_ALLOCATION_PARAMETER:"+key)
    spec={**SPEC,**(parameters or {})}
    if spec["horizon_sessions"]!=5 or spec["cvar_alpha"]!=.90 or spec["cvar_epsilon"]!=.0005:
        raise ValueError("UNREGISTERED_ALLOCATION_OBJECTIVE")
    mu,uncertainty,covariance,current=map(lambda x:np.asarray(x,float),(mu,uncertainty,covariance,current))
    locked,allowed,buy_allowed=map(lambda x:np.asarray(x,bool),(locked,allowed,buy_allowed))
    n=len(mu);reserved=np.where(locked,current,0.)
    mass=1-float(reserved.sum())
    cap=float(spec.get("max_q",.1))
    upper=np.where(allowed&buy_allowed,cap,np.where(allowed,np.minimum(current,cap),0.))
    ids=np.flatnonzero(upper>EPS)
    if mass<-EPS or not np.isfinite(current).all():
        raise AllocationUnavailable("INVALID_RESERVED_COMPOSITION")
    if mass<=EPS:
        return AllocationResult(reserved,0,0,np.nan,"RESERVED_FULL_ACCOUNT")
    if not len(ids) or np.any(~np.isfinite(mu[ids])) or np.any(~np.isfinite(uncertainty[ids])):
        raise AllocationUnavailable("NO_AVAILABLE_FINITE_FORECAST")
    variance=np.diag(covariance) if covariance.ndim==2 else covariance
    if variance.shape!=(n,) or not np.isfinite(variance).all() or np.any(variance<=0):
        raise AllocationUnavailable("INVALID_FROZEN_FIVE_SESSION_RISK")
    clean=np.zeros(n);clean[ids]=mu[ids]
    equivalence=("LONG_ONLY_SIMPLEX_L1_CONSTANT_NO_SPARSITY_IDENTIFICATION" if requested=="l1_weight"
                 else "ZERO_FEE_COST_OBJECTIVE_EQUIVALENT_TO_MV" if requested=="cost_aware"
                 else "TURNOVER_LIMIT_APPLIED_TO_ACCOUNT_TARGET_W_AFTER_Q_G" if requested=="turnover_limit"
                 else f"EXACT_OBJECTIVE_ALIAS:{requested}->{method}" if requested in ALIASES else "")
    values=np.full(n,-np.inf)
    values[ids]=clean[ids]
    if method=="positive_equal":
        upper[clean<=0]=0.
        ids=np.flatnonzero(upper>EPS)
    if method in {"equal_weight","positive_equal","inverse_volatility","hrp"}:
        raw=np.zeros(n)
        if method in {"equal_weight","positive_equal"}:
            support=_support_projection(values,upper,mass,slots,ticker_rank)>EPS
            raw[support]=mass/int(support.sum())
        elif method=="inverse_volatility":
            values[ids]=1/np.sqrt(variance[ids])
            support=_support_projection(values,upper,mass,slots,ticker_rank)>EPS
            raw[support]=1/np.sqrt(variance[support])
            raw*=mass/raw.sum()
        else:
            raw[ids]=mass*_hrp(covariance,ids)
        q=reserved+_support_projection(raw,upper,mass,slots,ticker_rank)
        return AllocationResult(q,0,0,np.nan,"DETERMINISTIC_CONSTRAINED_ALLOCATION",equivalence)
    if method in {"mean_cvar","mean_semivariance","log_growth"}:
        if scenarios is None:
            raise AllocationUnavailable("BLOCKED_MATURE_JOINT_SCENARIOS")
        scenarios=np.asarray(scenarios,float)
        if scenarios.ndim!=2 or scenarios.shape[1]!=n or not np.isfinite(scenarios).all():
            raise AllocationUnavailable("INVALID_JOINT_SCENARIO_INPUT")
    if method in {"reference_regularization","tracking_error"}:
        if reference is None:
            raise AllocationUnavailable("BLOCKED_FROZEN_REFERENCE_PORTFOLIO")
        reference=np.asarray(reference,float)
        if reference.shape!=(n,) or not np.isfinite(reference).all() or np.any(reference<0) or reference.sum()<=0:
            raise AllocationUnavailable("INVALID_REFERENCE_PORTFOLIO")
        reference=reference/reference.sum()
    penalty=float(spec["risk_penalty"])
    effective=clean.copy()
    if method in {"robust_mean_variance","uncertainty_penalty"}:
        effective[ids]-=spec["uncertainty_penalty"]*uncertainty[ids]
    if method=="expected_return_shrinkage":
        effective*=spec["shrinkage"]
    if method=="black_litterman":
        prior=penalty*_covariance_action(covariance,reserved+np.where(upper>0,mass/len(ids),0))
        sub=covariance[np.ix_(ids,ids)] if covariance.ndim==2 else np.diag(covariance[ids])
        omega=np.maximum(uncertainty[ids]**2,1e-8)
        operator=LinearOperator(sub.shape,matvec=lambda x:spec["bl_tau"]*(sub@x)+omega*x)
        view,info=cg(operator,clean[ids]-prior[ids],rtol=1e-6,maxiter=64)
        if info!=0:
            raise AllocationUnavailable("BLACK_LITTERMAN_FIXED_SOLVER_LIMIT")
        effective[ids]=prior[ids]+spec["bl_tau"]*(sub@view)
    budgets=np.zeros(n)
    active=(upper>EPS)|locked
    budgets[active]=(1+np.asarray(ticker_rank)[active]%3) if method=="risk_budgeting" else 1
    budgets/=max(budgets.sum(),1)
    covariance_norm=np.max(np.abs(covariance).sum(axis=1)) if covariance.ndim==2 else np.max(covariance)
    step=1/max(penalty*covariance_norm+2*spec["l2_weight"]+2*spec["l2_turnover"],1e-6)
    free=_support_projection(values,upper,mass,slots,ticker_rank)
    def objective_gradient(w):
        risk=_covariance_action(covariance,w)
        objective=.5*penalty*float(w@risk)-float(effective@w)
        gradient=penalty*risk-effective
        if method=="gmv":
            objective=.5*float(w@risk);gradient=risk
        elif method in {"erc","risk_budgeting"}:
            total=float(w@risk)
            if total<=EPS:
                raise AllocationUnavailable("NONPOSITIVE_RISK_BUDGET_VARIANCE")
            contribution=w*risk/total
            error=contribution-budgets
            objective=float(error@error)
            gradient=2/total*(error*risk+_covariance_action(covariance,error*w)-2*float(error@contribution)*risk)
        elif method=="mean_cvar":
            loss,grad,_=_smooth_cvar(w[None,:],scenarios[None,:,:])
            objective=penalty*float(loss[0])-float(effective@w)
            gradient=penalty*grad[0]-effective
        elif method=="mean_semivariance":
            portfolio=scenarios@w
            downside=np.minimum(portfolio,0)
            objective=penalty*float(np.mean(downside**2))-float(effective@w)
            gradient=2*penalty*(scenarios.T@downside)/len(scenarios)-effective
        elif method=="log_growth":
            wealth=1+scenarios@w
            if np.any(wealth<=0):
                return np.inf,np.zeros(n)
            objective=-float(np.log(wealth).mean())
            gradient=-np.mean(scenarios/wealth[:,None],axis=0)
        elif method=="l2_weight":
            objective+=spec["l2_weight"]*float(w@w);gradient+=2*spec["l2_weight"]*w
        elif method=="reference_regularization":
            delta=w-reference
            objective+=spec["l2_weight"]*float(delta@delta);gradient+=2*spec["l2_weight"]*delta
        elif method=="tracking_error":
            delta=w-reference;tracking=_covariance_action(covariance,delta)
            objective+=.5*penalty*float(delta@tracking);gradient+=penalty*tracking
        elif method=="l1_turnover":
            delta=w-current
            objective+=spec["l1_turnover"]*float(np.abs(delta).sum());gradient+=spec["l1_turnover"]*np.sign(delta)
        elif method=="l2_turnover":
            delta=w-current
            objective+=spec["l2_turnover"]*float(delta@delta);gradient+=2*spec["l2_turnover"]*delta
        return objective,gradient
    if method=="turnover_limit":
        fixed_turnover=float(np.abs(reserved-current).sum())
        if fixed_turnover>spec["turnover_limit"]+EPS or abs(current.sum()-1)>1e-7:
            raise AllocationUnavailable("TURNOVER_LIMIT_INFEASIBLE_COMPOSITION_FROM_CURRENT_STATE")
        free=np.where(locked,0,current)
    best=free.copy();best_obj,_=objective_gradient(free+reserved);residual=np.inf
    for iteration in range(1,int(spec["iterations"])+1):
        objective,gradient=objective_gradient(free+reserved)
        local_step=min(step,.05/max(float(np.abs(gradient[ids]).max()),1e-8)) if method in {"erc","risk_budgeting","log_growth","mean_cvar"} else step
        candidate_values=np.full(n,-np.inf)
        candidate_values[ids]=free[ids]-local_step*gradient[ids]
        following=_support_projection(candidate_values,upper,mass,slots,ticker_rank)
        if method=="turnover_limit":
            delta=following+reserved-current
            turn=float(np.abs(delta).sum())
            if turn>spec["turnover_limit"]:
                fraction=spec["turnover_limit"]/turn
                proposal=current+fraction*delta
                if np.count_nonzero(proposal>EPS)>int(slots)+int(locked.sum()):
                    raise AllocationUnavailable("TURNOVER_CARDINALITY_INTERSECTION_UNSUPPORTED")
                following=proposal-reserved
        residual=float(np.max(np.abs(following-free))/local_step)
        obj,_=objective_gradient(following+reserved)
        if obj<best_obj:
            best,best_obj=following.copy(),obj
        free=following
        if residual<=spec["tolerance"]:
            break
    if not np.isfinite(best_obj):
        raise AllocationUnavailable("NO_FINITE_FEASIBLE_ALLOCATION_OBJECTIVE")
    return AllocationResult(best+reserved,iteration,residual,best_obj,
                            "APPROXIMATE_PROJECTED_FIXED_POINT" if residual<=spec["tolerance"]
                            else "APPROXIMATE_FIXED_ITERATION_LIMIT",equivalence)


def exposure(q,covariance,reserved,method,*,mu=None,uncertainty=None):
    """Independent Gross, with 5-session risk converted by 252/5."""
    if method not in GROSS_METHODS:
        raise AllocationUnavailable("UNKNOWN_EXPOSURE_METHOD")
    if method in {"fixed","separate_composition_exposure"}:
        return np.asarray(q),1.
    q,reserved=np.asarray(q,float),np.asarray(reserved,float)
    if np.any(reserved>q+EPS) or not np.allclose(q[reserved>EPS],reserved[reserved>EPS],atol=1e-10):
        raise AllocationUnavailable("INVALID_RESERVED_COMPOSITION_FOR_GROSS")
    r=float(reserved.sum())
    if r>=1-EPS:
        return reserved/r,r
    v=(q-reserved)/(1-r)
    if method=="dynamic":
        if mu is None or uncertainty is None:
            raise AllocationUnavailable("BLOCKED_DYNAMIC_EXPOSURE_FORECAST")
        valid=np.isfinite(mu)&np.isfinite(uncertainty)
        if not valid[q>EPS].all():
            raise AllocationUnavailable("DYNAMIC_EXPOSURE_UNKNOWN_FORECAST")
        confidence=float(q@np.where(valid,mu,0))/max(float(q@np.where(valid,uncertainty,0)),1e-8)
        gross=max(r,float(np.clip(confidence,0,1)))
    else:
        a=float(v@_covariance_action(covariance,v))
        b=float(v@_covariance_action(covariance,reserved))
        c=float(reserved@_covariance_action(covariance,reserved))
        target=SPEC["volatility_target_annual"]**2/SPEC["annualization"]
        if not np.isfinite([a,b,c]).all() or a<=0 or c < -EPS:
            raise AllocationUnavailable("RISK_CASH_INVALID_JOINT_VARIANCE")
        full=a*(1-r)**2+2*b*(1-r)+c
        if full<=target:
            gross=1.
        else:
            discriminant=b*b+a*(target-c)
            if discriminant<0:
                raise AllocationUnavailable("RISK_CASH_INFEASIBLE")
            lower=(-b-np.sqrt(discriminant))/a
            upper=(-b+np.sqrt(discriminant))/a
            feasible_low=max(0.,lower)
            feasible_high=min(1-r,upper)
            if feasible_high < feasible_low-EPS:
                raise AllocationUnavailable("RISK_CASH_NO_FEASIBLE_FREE_EXPOSURE_INTERVAL")
            gross=float(np.clip(r+feasible_high,r,1))
    if gross<=EPS:
        return q,0.
    weights=reserved+(gross-r)*v
    return weights/gross,gross


_CALL_CACHE = None


def _v24_call(self,day,ctx):
    """Source-bound single comparison extension permits the authorized G=0."""
    global _CALL_CACHE
    if _CALL_CACHE is not None:
        return _CALL_CACHE(self,day,ctx)
    from scripts.research.a2.inference import joint_portfolio_policy as common
    raw=Path(common.__file__).read_bytes()
    expected="c116bd9dcf28e9a6f53a3b183d2335febd02ae1ef4bbfe90a827b70dcd27352f"
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError("FROZEN_JOINT_POLICY_CHANGED")
    cls=next(n for n in ast.parse(raw.decode("utf-8-sig")).body if isinstance(n,ast.ClassDef) and n.name=="JointResearchPolicy")
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="__call__")
    changed=0
    for part in ast.walk(node):
        if (isinstance(part,ast.Compare) and isinstance(part.left,ast.Constant) and part.left.value==0
            and len(part.ops)==2 and isinstance(part.ops[0],ast.Lt)
            and isinstance(part.comparators[0],ast.Name) and part.comparators[0].id=="gross"):
            part.ops[0]=ast.LtE();changed+=1
    if changed!=1:
        raise ValueError("ZERO_GROSS_CONTRACT_PROJECTION_NOT_EXACT")
    namespace=dict(common.__dict__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(common.__file__),"exec"),namespace)
    _CALL_CACHE=namespace["__call__"]
    return _CALL_CACHE(self,day,ctx)


class JointAllocationPolicy(JointResearchPolicy):
    """One fixed allocation/exposure configuration per instance; same engine."""
    def __init__(self,*args,method="mean_variance",gross_method="fixed",
                 scenarios_by_year=None,reference_by_day=None,**kwargs):
        super().__init__(*args,**kwargs)
        if len(self.role_ids)!=1:
            raise ValueError("ONE_FIXED_ALLOCATION_CONFIG_PER_INSTANCE")
        self.method,self.gross_method=method,gross_method
        self.scenarios_by_year=scenarios_by_year or {}
        self.reference_by_day=reference_by_day or {}
        self.allocation_receipts=[]
    def __call__(self,day,ctx):
        self.day,self.year=day,ctx.signal_date.year
        result=_v24_call(self,day,ctx)
        return TradingControlPolicy(lambda _day,_ctx:result,"turnover_limit")(day,ctx) if self.method=="turnover_limit" else result
    def _optimize(self,mean,uncertainty,covariance,step,current,locked,allowed,buy_allowed,slots,ticker_rank):
        result=allocate_q(self.method,mean,uncertainty,covariance,current,locked,allowed,buy_allowed,slots,ticker_rank,
            scenarios=self.scenarios_by_year.get(self.year),reference=self.reference_by_day.get(self.day),
            parameters={"max_q":self.max_q,"iterations":self.iterations,"tolerance":self.tolerance})
        self.allocation_receipts.append(dict(day=self.day,method=self.method,status=result.status,equivalence=result.equivalence))
        return result.q,result.iterations,result.residual,result.objective,result.status
    def _exposure(self,q,covariance,reserved,kind):
        return exposure(q,covariance,reserved,self.gross_method,mu=self.mu[self.day,0],
                        uncertainty=self.uncertainty[self.day,0])


class TradingControlPolicy:
    """Order controls preserve units through the existing TargetDecision mask."""
    def __init__(self,base_policy,control):
        if control not in CONTROL_METHODS:
            raise AllocationUnavailable("UNKNOWN_TRADING_CONTROL")
        if control=="discrete_allocation":
            raise AllocationUnavailable("BLOCKED_INTEGER_EXECUTION_CONTRACT_FRACTIONAL_COMMON_ENGINE")
        if control=="buy_hold_hysteresis":
            raise AllocationUnavailable("REUSE_RULE_STATEFUL_POLICY_HYSTERESIS_BEFORE_Q")
        self.base,self.control=base_policy,control
    def __call__(self,day,ctx):
        result=self.base(day,ctx)
        if self.control in {"fractional_allocation","participation_constraint","liquidity_constraint"}:
            return result  # These are common execution gates, never duplicate fits.
        target,explicit=result.weights.copy(),result.explicit_mask.copy()
        current=ctx.current_weights
        if self.control=="turnover_limit":
            target=current.copy()
            for r in range(len(ctx.path_ids)):
                remaining=SPEC["turnover_limit"]
                desired=result.weights[r]
                ids=np.flatnonzero(explicit[r]&(current[r]>desired+EPS))
                exits=ids[np.lexsort((ctx.tickers[ids],-((desired[ids]<=EPS).astype(int)),current[r,ids]))]
                for c in exits:
                    change=min(remaining,float(current[r,c]-desired[c]))
                    target[r,c]-=change;remaining-=change
                held_count=int(np.count_nonzero(target[r]>EPS))
                ids=np.flatnonzero(explicit[r]&(desired>target[r]+EPS))
                ordered=ids[np.lexsort((ctx.tickers[ids],-(desired[ids]-target[r,ids])))]
                for c in ordered:
                    if target[r,c]<=EPS and held_count>=ctx.max_positions:
                        continue
                    change=min(remaining,float(desired[c]-target[r,c]))
                    if target[r,c]<=EPS and change>EPS:
                        held_count+=1
                    target[r,c]+=change;remaining-=change
            return TargetDecision(target,explicit,"V24_ORDER_TURNOVER_LIMIT")
        if self.control=="partial_rebalance":
            if hasattr(self.base,"roles") and all(self.base.roles[p].get("rho")==SPEC["partial_rebalance"] for p in ctx.path_ids):
                return result
            selected=target>EPS
            target[selected]=np.minimum(ctx.max_weight,(1-SPEC["partial_rebalance"])*current[selected]+SPEC["partial_rebalance"]*target[selected])
        else:
            delta=np.abs(target-current)
            tiny=(delta<SPEC["no_trade_band"]) if self.control=="no_trade_band" else (delta*ctx.nav[:,None]<SPEC["minimum_trade_usd"])
            explicit[tiny&(ctx.current_units>EPS)]=False
            target[tiny]=0.
        return TargetDecision(target,explicit,"V24_TRADING_CONTROL:"+self.control)

