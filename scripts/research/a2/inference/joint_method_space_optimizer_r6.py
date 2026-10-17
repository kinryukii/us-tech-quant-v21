"""R6 q objective extension over the existing full-candidate owner.

No account, data reader, optimizer platform or source qualification. A caller's
solve(name, inputs, compute) must reserve a whole objective invocation before it
runs; identical contexts may reuse the same result. Controller/closed-form tree
operations are separate deterministic evaluations. R6 carried-target cadence is
an explicit scientific descendant, never old daily-q exact equivalence.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from pathlib import Path
import numpy as np
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.spatial.distance import squareform
from scipy.special import logsumexp
from scipy.optimize import minimize
from scripts.research.a2.portfolio import joint_allocation_methods as owner
from scripts.research.a2.inference.joint_portfolio_policy import _support_projection

METHODS=("MV","GMV","CVAR","SEMIVARIANCE","MAD","ENTROPIC","ERC","RISK_PARITY",
         "MAX_DIV","MIN_CORR","HRP","HERC","ROBUST_MV","ELLIPSOIDAL","COV_ROBUST","DRO",
         "FRACTIONAL_KELLY","LOG_UTILITY","QUADRATIC_UTILITY","TURNOVER_MV","TURNOVER_CVAR",
         "ENTROPY_TURNOVER","PROXIMAL")
NATIVE={"MV":"mean_variance","GMV":"gmv","CVAR":"mean_cvar","SEMIVARIANCE":"mean_semivariance",
        "ERC":"erc","RISK_PARITY":"erc","HRP":"hrp","ROBUST_MV":"robust_mean_variance",
        "QUADRATIC_UTILITY":"mean_variance","TURNOVER_MV":"cost_aware","PROXIMAL":"mean_variance"}
SPEC=dict(risk_penalty=4.,uncertainty_radius=.5,covariance_relative_radius=.1,
          cvar_alpha=.90,cvar_epsilon=.0005,partial_fraction=.5,kelly_fraction=.5,
          iterations=128,tolerance=2e-6,max_q=.1,max_positions=20,
          entropic_scale="caller qualified prior QQQ H5 RMS; no current outcome selection",
          dro_radius="same prior RMS / sqrt(number of genuine mature joint scenarios)",
          herc="single-linkage binary tree; analytical two-sibling equal risk contributions",
          mad_center="fixed supplied genuine forecast mean; no sample-mean fitter",
          scientific_retry=0)

class QInputBlocked(owner.AllocationUnavailable):
    pass

@dataclass(frozen=True)
class QEstimate:
    allocation: owner.AllocationResult
    gross_cap: float
    whole_objective_calls: int
    deterministic_operations: dict
    semantic_equivalence: str = ""


def _context(mu,uncertainty,cov,current,locked,allowed,buy,slots,ranks,scenarios,scale):
    mu,u,cv,cur=map(lambda v:np.asarray(v,float),(mu,uncertainty,cov,current))
    lock,allow,buy=map(lambda v:np.asarray(v,bool),(locked,allowed,buy))
    n=len(mu)
    if any(a.shape!=(n,) for a in (u,cur,lock,allow,buy,np.asarray(ranks))) or cv.shape!=(n,n):
        raise QInputBlocked("EXACT_Q_INPUT_AXES_REQUIRED")
    if not np.isfinite(cv).all() or not np.allclose(cv,cv.T) or np.any(np.diag(cv)<=0):
        raise QInputBlocked("POSITIVE_FINITE_COVARIANCE_REQUIRED")
    try:
        if np.linalg.eigvalsh(cv).min() < -1e-10*max(float(np.max(np.diag(cv))),1e-12):
            raise QInputBlocked("INDEFINITE_COVARIANCE_REQUIRED_BLOCK")
    except np.linalg.LinAlgError as error:
        raise QInputBlocked("COVARIANCE_EIGEN_CHECK_FAILED") from error
    if not np.isfinite(cur).all() or np.any(cur<0) or cur.sum()>1+1e-8:
        raise QInputBlocked("LEGAL_CURRENT_ACCOUNT_REQUIRED")
    if type(slots) is not int or not 0<=slots<=SPEC["max_positions"]:
        raise QInputBlocked("FROZEN_POSITION_SLOTS_REQUIRED")
    ids=(allow&~lock&(buy|(cur>0))); required=ids|(cur>0)
    if not np.isfinite(mu[required]).all() or not np.isfinite(u[required]).all() or np.any(u[required]<0):
        raise QInputBlocked("FULL_ACTUAL_REQUIRED_FORECAST_SUPPORT")
    if scenarios is not None:
        scenarios=np.asarray(scenarios,float)
        if scenarios.ndim!=2 or scenarios.shape[1]!=n or not np.isfinite(scenarios).all() or len(scenarios)<30:
            raise QInputBlocked("COMPLETE_GENUINE_MATURE_JOINT_SCENARIOS_REQUIRED")
    if scale is not None and (not np.isfinite(scale) or scale<=0):
        raise QInputBlocked("POSITIVE_PRIOR_SCALE_REQUIRED")
    return np.where(required,mu,0.),np.where(required,u,0.),cv,cur,lock,allow,buy,np.asarray(ranks),scenarios


def _herc(cov,ids):
    """Exact two-sibling ERC at each tree split; not global constrained ERC."""
    if len(ids)==1: return np.ones(1),0
    c=cov[np.ix_(ids,ids)]; s=np.sqrt(np.diag(c))
    corr=np.clip(c/np.outer(s,s),-1,1); dist=np.sqrt(np.maximum((1-corr)/2,0));np.fill_diagonal(dist,0)
    tree=to_tree(linkage(squareform(dist,checks=False),method="single"))
    operations=0
    def allocate(node):
        nonlocal operations
        if node.is_leaf():
            w=np.zeros(len(ids));w[node.id]=1.;return w
        left,right=allocate(node.left),allocate(node.right)
        vl=float(left@c@left);vr=float(right@c@right)
        if vl<=0 or vr<=0: raise QInputBlocked("HERC_NONPOSITIVE_CHILD_VARIANCE")
        a=np.sqrt(vr)/(np.sqrt(vl)+np.sqrt(vr));operations+=1
        # Cross-covariance cancels when solving two-child RC equality.
        return a*left+(1-a)*right
    return allocate(tree),operations


def _new_objective(method,mu,u,cov,cur,scenarios,scale,cost):
    penalty=SPEC["risk_penalty"]
    if method in {"MAD","ENTROPIC","DRO","TURNOVER_CVAR","ENTROPY_TURNOVER","LOG_UTILITY","FRACTIONAL_KELLY"} and scenarios is None:
        raise QInputBlocked("COMPLETE_GENUINE_MATURE_JOINT_SCENARIOS_REQUIRED")
    if method in {"ENTROPIC","DRO","ENTROPY_TURNOVER"} and scale is None:
        raise QInputBlocked("BOUND_PRIOR_QQQ_SCALE_REQUIRED")
    def objective(w):
        action=cov@w;variance=float(w@action);value=float(mu@w)
        if method=="MAD":
            deviations=scenarios-mu;portfolio=deviations@w
            risk=float(np.mean(np.abs(portfolio)));gradient=deviations.T@np.sign(portfolio)/len(scenarios)
        elif method in {"ENTROPIC","ENTROPY_TURNOVER"}:
            loss=-scenarios@w/scale;normalizer=logsumexp(loss)
            risk=float(scale*(normalizer-np.log(len(scenarios))))
            gradient=-scenarios.T@np.exp(loss-normalizer)
        elif method in {"TURNOVER_CVAR","DRO"}:
            losses,grad,_=owner._smooth_cvar(w[None,:],scenarios[None,:,:]);risk=float(losses[0]);gradient=grad[0]
            if method=="DRO":
                norm=np.linalg.norm(w);radius=scale/np.sqrt(len(scenarios))
                risk+=radius*norm;gradient+=radius*w/max(norm,1e-18)
        elif method=="MAX_DIV":
            root=np.sqrt(max(variance,1e-18));a=np.sqrt(np.diag(cov));numerator=float(a@w)
            return -numerator/root,-a/root+numerator*action/root**3
        elif method=="MIN_CORR":
            sd=np.sqrt(np.diag(cov));corr=cov/np.outer(sd,sd)
            return float(w@corr@w),2*corr@w
        elif method=="ELLIPSOIDAL":
            norm=np.linalg.norm(u*w);radius=SPEC["uncertainty_radius"]
            return .5*penalty*variance-value+radius*norm,penalty*action-mu+radius*(u*u*w)/max(norm,1e-18)
        elif method=="COV_ROBUST":
            diagonal=np.diag(cov);radius=SPEC["covariance_relative_radius"]
            return .5*penalty*(variance+radius*float((w*w)@diagonal))-value,penalty*(action+radius*diagonal*w)-mu
        elif method in {"LOG_UTILITY","FRACTIONAL_KELLY"}:
            wealth=1+scenarios@w
            if np.any(wealth<=0):return 1e30,np.zeros_like(w)
            return -float(np.log(wealth).mean()),-np.mean(scenarios/wealth[:,None],axis=0)
        else:raise QInputBlocked("UNIMPLEMENTED_FIXED_R6_Q")
        result=penalty*risk-value;gradient=penalty*gradient-mu
        if method in {"TURNOVER_CVAR","ENTROPY_TURNOVER"}:
            result+=cost*float(np.abs(w-cur).sum());gradient+=cost*np.sign(w-cur)
        return result,gradient
    return objective


def allocate_q(method,mu,uncertainty,covariance,current,locked,allowed,buy_allowed,slots,ticker_rank,
               *,scenarios=None,prior_scale=None,execution_friction_bps=10.,solve=None,synthetic=True):
    """One frozen q recipe. Actual account context is always part of solve key.

    LOG/FRACTIONAL outputs have an explicit gross_cap. The R6 policy must consume
    this cap; dropping it or re-normalizing target weights would erase Kelly/cash.
    Ordinary old q/G semantics are otherwise reused unchanged.
    """
    if method not in METHODS: raise QInputBlocked("UNKNOWN_R6_Q")
    if execution_friction_bps not in (5.,10.,20.): raise QInputBlocked("FROZEN_COST_ONLY")
    if not synthetic and solve is None: raise QInputBlocked("REAL_SOLVE_RESERVATION_CALLBACK_REQUIRED")
    mu,u,cov,cur,lock,allow,buy,ranks,scenarios=_context(mu,uncertainty,covariance,current,locked,allowed,buy_allowed,slots,ticker_rank,scenarios,prior_scale)
    if method in {"CVAR","SEMIVARIANCE","MAD","ENTROPIC","DRO","TURNOVER_CVAR","ENTROPY_TURNOVER","LOG_UTILITY","FRACTIONAL_KELLY"} and scenarios is None:
        raise QInputBlocked("COMPLETE_GENUINE_MATURE_JOINT_SCENARIOS_REQUIRED")
    if method in {"ENTROPIC","DRO","ENTROPY_TURNOVER"} and prior_scale is None:
        raise QInputBlocked("BOUND_PRIOR_QQQ_SCALE_REQUIRED")
    key_inputs=(mu,u,cov,cur,lock,allow,buy,slots,ranks,scenarios,prior_scale)
    counter=0; deterministic={}
    def call(name,inputs,compute):
        def actual():
            nonlocal counter
            counter+=1
            return compute()
        return solve("r6:q:"+name,(SPEC,inputs),actual) if solve else actual()
    reserved_mass=float(np.where(lock,cur,0.).sum())
    if reserved_mass>=1-1e-12:
        return QEstimate(owner.AllocationResult(np.where(lock,cur,0.),0,0.,np.nan,"RESERVED_FULL_ACCOUNT"),1.,0,dict(reserved_passthrough=1))
    if not np.any(allow&~lock&(buy|(cur>0))) or slots==0:
        raise QInputBlocked("NO_FREE_ACCOUNT_CAPACITY")
    if method in NATIVE:
        native=NATIVE[method]
        # Only actual cost-sensitive objectives include friction in the key.
        cost=execution_friction_bps if native=="cost_aware" else 0.
        if native=="hrp":
            result=owner.allocate_q(native,mu,u,cov,cur,lock,allow,buy,slots,ranks,scenarios=scenarios)
            deterministic["hrp_tree_and_support_projection"]=1
        else:
            result=call(native,key_inputs+(cost,),lambda:owner.allocate_q(native,mu,u,cov,cur,lock,allow,buy,slots,ranks,scenarios=scenarios,execution_friction_bps=cost))
        equivalence="RISK_PARITY_IS_EQUAL_BUDGET_ERC" if method=="RISK_PARITY" else "QUADRATIC_UTILITY_IS_FIXED_LAMBDA_MV" if method=="QUADRATIC_UTILITY" else ""
        if method=="PROXIMAL":
            # Frozen A1-compatible target transform; no second optimizer call.
            reserved=np.where(lock,cur,0.);mass=1-reserved.sum();upper=np.where(allow&~lock&buy,.1,np.where(allow&~lock,np.minimum(cur,.1),0.))
            proposed=.5*cur+.5*result.q; values=np.where(upper>0,proposed-reserved,-np.inf)
            q=reserved+_support_projection(values,upper,mass,slots,ranks)
            result=owner.AllocationResult(q,result.iterations,result.residual,result.objective,"R6_PROXIMAL_FROZEN_MV_PLUS_PARTIAL_PROJECTED",result.equivalence)
            deterministic["partial_adjust_and_support_projection"]=1
            equivalence="SEMANTIC_A1_CONTROLLER_AFTER_SAME_MV_IF_SAME_G_AND_CONTEXT"
        return QEstimate(result,1.,counter,deterministic,equivalence)
    reserved=np.where(lock,cur,0.);mass=1-float(reserved.sum())
    upper=np.where(allow&~lock&buy,.1,np.where(allow&~lock,np.minimum(cur,.1),0.))
    ids=np.flatnonzero(upper>0)
    if mass<=1e-12 or not len(ids) or slots==0:
        raise QInputBlocked("NO_FREE_ACCOUNT_CAPACITY")
    if method=="HERC":
        raw=np.zeros(len(mu));tree,operations=_herc(cov,ids);raw[ids]=mass*tree
        q=reserved+_support_projection(np.where(upper>0,raw,-np.inf),upper,mass,slots,ranks)
        result=owner.AllocationResult(q,0,0.,np.nan,"DETERMINISTIC_BINARY_SIBLING_ERC_THEN_CONSTRAINT_PROJECTION","GLOBAL_CONSTRAINED_ERC_NOT_CLAIMED")
        return QEstimate(result,1.,0,dict(binary_sibling_closed_forms=operations,support_projection=1))
    objective=_new_objective(method,mu,u,cov,cur,scenarios,prior_scale,execution_friction_bps/10000.)
    growth=method in {"LOG_UTILITY","FRACTIONAL_KELLY"}
    x0=_support_projection(np.where(upper>0,mu,-np.inf),upper,mass,slots,ranks)+reserved
    bounds=[(float(cur[i]),float(cur[i])) if lock[i] else (0.,float(upper[i])) for i in range(len(mu))]
    constraints=[dict(type="ineq" if growth else "eq",fun=lambda w: 1-float(w.sum()),jac=lambda w:-np.ones_like(w))]
    if growth:
        # Composition cap remains 10% even when optimal cash is positive.
        constraints.append(dict(type="ineq",fun=lambda w:.1*float(w.sum())-w,jac=lambda w:.1*np.ones((len(w),len(w)))-np.eye(len(w))))
    def perform():
        fitted=minimize(objective,x0,jac=True,method="SLSQP",bounds=bounds,constraints=constraints,
                        options=dict(maxiter=SPEC["iterations"],ftol=SPEC["tolerance"]))
        if not fitted.success or not np.isfinite(fitted.x).all():
            raise QInputBlocked("R6_FIXED_SLSQP_FAILED:"+str(fitted.message))
        return fitted.x,int(fitted.nit),int(fitted.nfev)
    name="constrained_log_utility" if growth else method.lower()
    cost=execution_friction_bps if method in {"TURNOVER_CVAR","ENTROPY_TURNOVER"} else 0.
    w,iterations,evaluations=call(name,key_inputs+(cost,),perform)
    gross=float(w.sum()) if growth else 1.
    if growth and method=="FRACTIONAL_KELLY":
        w=reserved+SPEC["kelly_fraction"]*(w-reserved);gross=float(w.sum())
        deterministic["fractional_Kelly_free_capital_scaling"]=1
    target_mass=max(0.,gross-float(reserved.sum()))
    constrained_upper=np.minimum(upper,.1*gross) if growth else upper
    target=reserved+_support_projection(np.where(upper>0,w-reserved,-np.inf),constrained_upper,target_mass,slots,ranks)
    q=target/gross if growth and gross>1e-12 else target
    if growth and gross>1e-12 and np.any(q>.1+1e-8):
        raise QInputBlocked("LOCKED_GROWTH_COMPOSITION_CAP_INCOMPATIBLE")
    if np.count_nonzero(target>1e-10)>slots+int(lock.sum()) or np.any(target>.1+1e-8) or np.any(target[~buy]>cur[~buy]+1e-8):
        raise QInputBlocked("FINAL_FULL_ACCOUNT_CONSTRAINTS_FAILED")
    deterministic.update(support_projection=1,objective_evaluations=evaluations+1)
    result=owner.AllocationResult(q,iterations,0.,objective(target)[0],"CONTINUOUS_SLSQP_THEN_SUPPORT_PROJECTION_NO_GLOBAL_OPTIMUM",name)
    return QEstimate(result,gross,counter,deterministic)


def solve_upper(paths,clock_count,*,mpc_calls=0):
    """Conservative fixed path/clock proof. HERC/HRP contribute zero backend calls.

    paths is a frozen method roster with one row per physical account. Sharing
    reduces actual charges only with complete equal input/context operation keys.
    """
    if type(clock_count) is not int or clock_count<0 or type(mpc_calls) is not int or mpc_calls<0:
        raise ValueError("NONNEGATIVE_EXACT_COUNTS_REQUIRED")
    if any(p not in METHODS for p in paths): raise ValueError("UNKNOWN_Q_IN_FROZEN_PATHS")
    bound=clock_count*sum(p not in {"HRP","HERC"} for p in paths)+mpc_calls
    return dict(whole_objective_upper=bound,within_20000=bound<=20000,
                deterministic_daily_updates_separate=True,no_assumed_cross_account_reuse=True,
                hrp_herc_backend_calls=0,mpc_calls=mpc_calls)


def specification():
    return dict(schema="B_R6_Q_METHOD_SPEC_V1",methods=list(METHODS),parameters=SPEC,
        aliases=dict(RISK_PARITY="ERC",QUADRATIC_UTILITY="MV",PROXIMAL="MV then frozen partial transform"),
        native_reuse=NATIVE,backend="existing owner or SciPy SLSQP, one fixed call, no retry",
        solve_unit="one complete objective backend invocation; inner gradients/projections/eta arithmetic separately recorded",
        context_key=["forecast/risk/scenario hashes and ordered axes","current/locked/allowed/buy mask/slots/ranks","prior-scale","objective params","cost iff objective consumes cost"],
        cadence="NOT_FROZEN_HERE: R6 carried-target child must freeze source/UID/support monthly clock",
        cash_growth_semantics="gross_cap is mandatory output, applied as cap to separate Gross controller",
        source_qualification="caller-only; no identity or quote promotion")


def code_pins():
    paths=[Path(__file__),Path(owner.__file__),Path(__file__).with_name("joint_portfolio_policy.py"),
           Path(owner.__file__).parents[1]/"retained/a2_pto_full_compat_20260928_r2/optimization.py"]
    return [dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]