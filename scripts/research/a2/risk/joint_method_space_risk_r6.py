"""R6 fixed risk recipes; pure calculations, no source reader or activation authority.

Caller must independently freeze/qualify the full UID domain and reserve every learn
callback before computation. New R6 identities never authorize retry of equivalent
failed historical inputs. No unknown-security padding, data-dependent method choice,
or production qualification is supplied here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import genpareto
from scipy.optimize import minimize
from sklearn.covariance import GraphicalLasso, LedoitWolf
from sklearn.decomposition import PCA
from scripts.research.a2.risk.joint_risk_estimators import validate_covariance
from scripts.research.a2.risk.event_risk_contract_r5 import conditional_prior_completion

METHODS = ("DCC", "KALMAN", "DYNAMIC_FACTOR", "HUBER", "TYLER", "ROBUST_FACTOR",
           "NONLINEAR", "POET", "GRAPHICAL", "HIER_POSTERIOR", "BAYES_FACTOR",
           "POSTERIOR_PREDICTIVE", "SEMIVARIANCE", "EMPIRICAL_CVAR", "EVT", "AVERAGE")
SPEC = dict(horizon=5, min_classical_rows=30, window=252, factor_count=5,
            floor=1e-12, huber_clip=3., tyler_identity_weight=.1,
            tyler_iterations=100, tyler_tolerance=1e-6, ewma_decay=.94,
            dcc_a=.01, dcc_b=.98, kalman_process_ratio=.01,
            graphical_alpha="min(.5,sqrt(log(max(p,2))/(n/5)))", graphical_iterations=100, graphical_tolerance=1e-4,
            poet_threshold_constant=1., nig_strength=8., nig_shape=3.,
            donor_min_rows=60, donor_min_assets=5, likelihood_weight=.2,
            cvar_alpha=.90, evt_quantile=.95, evt_min_exceedances=30,
            evt_shape_bounds=(-.25,.45),evt_iterations=128,evt_tolerance=2e-6,
            evt_source_profile="R6_CURRENT_FULL_UID_EPOCH_SHAREHOLDER_H5_GENUINE_JOINT_FIXED252",
            average_members=("HUBER", "POET", "POSTERIOR_PREDICTIVE"),
            average_weights=(1/3, 1/3, 1/3), scientific_retry=0)
# Counts are operation recipes, before proven exact sharing, not actual executions.
LEARNED_UPPER = dict(DCC=4, KALMAN=6, DYNAMIC_FACTOR=4, HUBER=2, TYLER=2,
                    ROBUST_FACTOR=4, NONLINEAR=0, POET=4, GRAPHICAL=2,
                    HIER_POSTERIOR=7, BAYES_FACTOR=8, POSTERIOR_PREDICTIVE=7,
                    SEMIVARIANCE=1, EMPIRICAL_CVAR=1, EVT=3, AVERAGE=13)

class RiskInputBlocked(ValueError):
    pass

@dataclass(frozen=True)
class RiskInputs:
    returns: pd.DataFrame
    cutoff: object
    as_of: object
    asset_uids: dict
    source_sha256: str
    mature_max: object
    market: pd.Series | None = None
    synthetic: bool = True
    tail_source_qualified: bool = False
    identity_epochs: dict = field(default_factory=dict)

@dataclass(frozen=True)
class RiskEstimate:
    method: str
    assets: tuple
    covariance: object
    status: str
    representation: str
    notes: dict
    scenarios: object = None
    tail_state: object = None


def _utc(value):
    t = pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None:
        raise RiskInputBlocked("AWARE_PRE2026_CLOCK_REQUIRED")
    t = t.tz_convert("UTC")
    if t >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise RiskInputBlocked("PRE2026_ONLY")
    return t


def validate_inputs(inputs):
    if type(inputs.synthetic) is not bool or type(inputs.tail_source_qualified) is not bool:
        raise RiskInputBlocked("EXPLICIT_BOOLEAN_MODE_AND_TAIL_PROFILE_REQUIRED")
    f = inputs.returns
    if not isinstance(f, pd.DataFrame) or f.empty or not isinstance(f.index, pd.DatetimeIndex):
        raise RiskInputBlocked("NONEMPTY_DATETIME_RETURN_FRAME_REQUIRED")
    if f.index.tz is None or f.index.hasnans or f.index.has_duplicates or not f.index.is_monotonic_increasing:
        raise RiskInputBlocked("UNIQUE_INCREASING_AWARE_ORIGINS_REQUIRED")
    assets = tuple(map(str, f.columns))
    if len(set(assets)) != len(assets) or any(not a.strip() for a in assets):
        raise RiskInputBlocked("UNIQUE_NONEMPTY_ASSETS_REQUIRED")
    if set(inputs.asset_uids) != set(assets) or any(not str(inputs.asset_uids[a]).strip() or
            str(inputs.asset_uids[a]).strip().upper() in {"UNKNOWN", "NONE", "NAN", "NULL", "N/A"} for a in assets):
        raise RiskInputBlocked("EXACT_KNOWN_UID_DOMAIN_REQUIRED")
    if set(inputs.identity_epochs) != set(assets) or any(not str(inputs.identity_epochs[a]).strip() for a in assets):
        raise RiskInputBlocked("EXACT_CURRENT_UID_EPOCH_BINDING_REQUIRED")
    if len(set(map(str, inputs.asset_uids.values()))) != len(assets):
        raise RiskInputBlocked("AMBIGUOUS_UID_DOMAIN")
    if len(inputs.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in inputs.source_sha256):
        raise RiskInputBlocked("PHYSICAL_SOURCE_SHA_REQUIRED")
    cutoff, asof, mature = map(_utc, (inputs.cutoff, inputs.as_of, inputs.mature_max))
    if not cutoff < asof or mature >= cutoff or np.any(f.index.tz_convert("UTC") >= cutoff):
        raise RiskInputBlocked("STRICT_PRIOR_MATURITY_AND_CUTOFF_REQUIRED")
    if np.isinf(f.to_numpy(float)).any():
        raise RiskInputBlocked("INFINITE_OBSERVATION")
    if len(f) > SPEC["window"]:
        raise RiskInputBlocked("CALLER_MUST_BIND_FIXED_252_ORIGIN_WINDOW")
    if inputs.market is not None and (not isinstance(inputs.market, pd.Series) or
            not inputs.market.index.equals(f.index) or not np.isfinite(inputs.market.to_numpy(float)).all()):
        raise RiskInputBlocked("EXACT_ALIGNED_FINITE_MARKET_REQUIRED")
    return assets


class _Calculation:
    def __init__(self, inputs, learn):
        self.inputs, self.learn = inputs, learn
        self.counts = {}; self.backend = 0; self.systems = 0
    def state(self, kind, name, values, compute):
        self.counts[kind] = self.counts.get(kind, 0) + 1
        # Axes, source/cutoff/UID/epoch and frozen parameters must be bound by the
        # shared StateCache owner. Scientific label is deliberately not a key.
        return self.learn(kind, "r6:"+name, (SPEC, values), compute) if self.learn else compute()
    def transform(self, name, values, compute):
        return self.state("deterministic_transform", name, values, compute)


def _normal(f, c):
    def estimate():
        x=f.to_numpy(float); m=np.mean(x,axis=0); v=np.maximum(np.var(x,axis=0,ddof=1),SPEC["floor"])
        return m, v
    mean, variance = c.state("scaler", "mean_and_variance", (f,), estimate)
    x = c.transform("standardized", (f, mean, variance), lambda: (f.to_numpy(float)-mean)/np.sqrt(variance))
    return x, variance


def _pca(z, c, robust=False):
    x = np.clip(z, -SPEC["huber_clip"], SPEC["huber_clip"]) if robust else z
    if min(x.shape) < SPEC["factor_count"]:
        raise RiskInputBlocked("FIXED_FACTOR_COUNT_UNSUPPORTED")
    def estimate():
        c.backend += 1
        p=PCA(n_components=SPEC["factor_count"],svd_solver="full").fit(x)
        return p.components_, p.transform(x)
    return c.state("covariance", "huber_pca" if robust else "pca", (x,), estimate)


def _ewma(x):
    weights=SPEC["ewma_decay"]**np.arange(len(x)-1,-1,-1,dtype=float); weights/=weights.sum()
    mean=weights@x; centered=x-mean
    return (centered*weights[:,None]).T@centered


def _posterior(inputs, c):
    f=inputs.returns; raw=f.to_numpy(float)
    if inputs.market is None:
        raise RiskInputBlocked("BOUND_MARKET_FACTOR_REQUIRED")
    observed=np.isfinite(raw); donors=np.flatnonzero(observed.sum(axis=0)>=SPEC["donor_min_rows"])
    if len(donors)<SPEC["donor_min_assets"]:
        raise RiskInputBlocked("QUALIFIED_DONOR_PRIOR_UNAVAILABLE")
    q=inputs.market
    mean=c.state("scaler","market_mean",(q,),lambda: float(q.mean()))
    x=(q.to_numpy(float)-mean)[:,None]
    def lw():
        c.backend+=1
        return LedoitWolf(assume_centered=True).fit(x).covariance_
    fcov=c.state("covariance","market_lw",(x,),lw)
    design=np.c_[np.ones(len(f)),x]
    def ols():
        c.systems+=len(donors)
        return {str(int(j)):np.linalg.lstsq(design[observed[:,j]],raw[observed[:,j],j],rcond=None)[0] for j in donors}
    betas=c.state("covariance","donor_ols",(f,x,donors),ols)
    variances=c.state("covariance","donor_specific_variance",(f,x,betas),lambda:
        {str(int(j)):max(float(np.mean((raw[observed[:,j],j]-design[observed[:,j]]@betas[str(int(j))])**2)),SPEC["floor"]) for j in donors})
    prior=c.state("covariance","global_variance_prior",(variances,),lambda: float(np.median(list(variances.values()))))
    precision=SPEC["nig_strength"]*np.diag([1.,float(fcov[0,0])]); prior_beta=np.array([0.,1.])
    def coefficient_posterior():
        c.systems+=raw.shape[1]; result=[]
        for j in range(raw.shape[1]):
            a=design[observed[:,j]]; y=raw[observed[:,j],j]; w=SPEC["likelihood_weight"]
            v=np.linalg.inv(precision+w*a.T@a); b=v@(precision@prior_beta+w*a.T@y)
            result.append((b,v))
        return result
    coefficients=c.state("covariance","nig_coefficients",(f,x,fcov),coefficient_posterior)
    def specific_posterior():
        result=[]
        for j,(b,v) in enumerate(coefficients):
            a=design[observed[:,j]]; y=raw[observed[:,j],j]; w=SPEC["likelihood_weight"]
            shape=SPEC["nig_shape"]+.5*w*len(y)
            scale=(SPEC["nig_shape"]-1)*prior+.5*(w*float(y@y)+float(prior_beta@precision@prior_beta)-float(b@np.linalg.solve(v,b)))
            if not np.isfinite(scale) or scale<=0:
                raise RiskInputBlocked("INVALID_NIG_POSTERIOR_SCALE")
            result.append(scale/(shape-1))
        return np.asarray(result)
    specific=c.state("covariance","nig_specific_posterior",(f,x,coefficients,prior),specific_posterior)
    return x, fcov, coefficients, specific


def _covariance(method, inputs, c):
    f=inputs.returns; raw=f.to_numpy(float)
    if method in {"HIER_POSTERIOR","BAYES_FACTOR","POSTERIOR_PREDICTIVE"}:
        x, fcov, coeff, specific=_posterior(inputs,c)
        if method=="BAYES_FACTOR":
            # One-dimensional conjugate inverse-Wishart (inverse-gamma) factor
            # covariance posterior. Empirical prior is explicit, shared, not iid
            # coverage certification for overlapping H5 observations.
            fcov=c.state("covariance","factor_inverse_wishart_posterior",(x,fcov),lambda:
                (2*fcov+SPEC["likelihood_weight"]*x.T@x)/(2+SPEC["likelihood_weight"]*len(x)))
        b=np.asarray([v[0][1:] for v in coeff]); cov=b@fcov@b.T+np.diag(specific)
        if method=="POSTERIOR_PREDICTIVE":
            extra=np.asarray([specific[j]*(v[1][0,0]+float(np.trace(fcov@v[1][1:,1:]))) for j,v in enumerate(coeff)])
            cov+=np.diag(extra)
        return cov
    if method=="SEMIVARIANCE":
        negative=np.minimum(raw,0.)
        return c.state("covariance","uncentered_downside_second_moment",(negative,),lambda: negative.T@negative/len(raw))
    z, variance=_normal(f,c); scale=np.sqrt(variance)
    if method=="HUBER":
        h=np.clip(z,-SPEC["huber_clip"],SPEC["huber_clip"])
        cov=c.state("covariance","huber_second_moment",(h,),lambda: h.T@h/len(h))
    elif method=="GRAPHICAL":
        def graphical():
            c.backend+=1
            alpha=min(.5,np.sqrt(np.log(max(z.shape[1],2))/(len(z)/SPEC["horizon"])))
            m=GraphicalLasso(alpha=alpha,max_iter=SPEC["graphical_iterations"],tol=SPEC["graphical_tolerance"],mode="cd",assume_centered=True).fit(z)
            if m.n_iter_>=SPEC["graphical_iterations"]:
                raise RiskInputBlocked("GRAPHICAL_FIXED_ITERATION_BUDGET_EXHAUSTED")
            return m.covariance_
        cov=c.state("covariance","graphical_lasso",(z,),graphical)
    elif method=="TYLER":
        def tyler():
            p=z.shape[1]; s=np.eye(p); norms=np.einsum("ij,ij->i",z,z)
            if np.any(norms<=SPEC["floor"]):
                raise RiskInputBlocked("TYLER_ZERO_NORM_OBSERVATION")
            for _ in range(SPEC["tyler_iterations"]):
                denom=np.einsum("ij,ij->i",z,np.linalg.solve(s,z.T).T)
                proposal=.9*p*(z/denom[:,None]).T@z/len(z)+.1*np.eye(p)
                proposal*=p/np.trace(proposal)
                if np.max(np.abs(proposal-s))<=SPEC["tyler_tolerance"]:
                    return proposal
                s=proposal
            raise RiskInputBlocked("TYLER_FIXED_ITERATION_BUDGET_EXHAUSTED")
        cov=c.state("covariance","regularized_tyler_trace_shape",(z,),tyler)
    elif method=="DCC":
        longrun=c.state("covariance","dcc_longrun_correlation",(z,),lambda: np.atleast_2d(np.cov(z,rowvar=False)))
        marginal=c.state("covariance","dcc_ewma_marginal_variance",(z,),lambda: np.diag(_ewma(z)))
        def filter_state():
            state=longrun.copy()
            for row in z:
                state=(1-SPEC["dcc_a"]-SPEC["dcc_b"])*longrun+SPEC["dcc_a"]*np.outer(row,row)+SPEC["dcc_b"]*state
            d=np.sqrt(np.diag(state)); return state/np.outer(d,d)
        corr=c.state("covariance","dcc_fixed_parameter_latent_state",(z,longrun),filter_state)
        cov=corr*np.sqrt(np.outer(marginal,marginal))
    elif method=="KALMAN":
        if inputs.market is None: raise RiskInputBlocked("BOUND_MARKET_FACTOR_REQUIRED")
        q=inputs.market; qm=c.state("scaler","market_mean",(q,),lambda: float(q.mean())); x=q.to_numpy(float)-qm
        fv=c.state("covariance","kalman_market_variance",(x,),lambda: float(np.var(x,ddof=1)))
        beta=c.state("covariance","kalman_initial_beta",(z,x),lambda: x@z/max(float(x@x),SPEC["floor"]))
        rv=c.state("covariance","kalman_innovation_variance",(z,x,beta),lambda: np.maximum(np.mean((z-x[:,None]*beta)**2,axis=0),SPEC["floor"]))
        def filter_beta():
            b=beta.copy(); v=rv/max(float(x@x),SPEC["floor"])
            for t,row in enumerate(z):
                v+=SPEC["kalman_process_ratio"]*rv/max(fv,SPEC["floor"])
                gain=v*x[t]/(x[t]*x[t]*v+rv); b+=gain*(row-x[t]*b); v*=1-gain*x[t]
            return b,v
        b,v=c.state("covariance","kalman_filtered_beta_posterior",(z,x,beta,rv),filter_beta)
        cov=np.outer(b,b)*fv+np.diag(rv+fv*v)
    elif method in {"DYNAMIC_FACTOR","ROBUST_FACTOR","POET"}:
        robust=method=="ROBUST_FACTOR"; loadings,factors=_pca(z,c,robust)
        fcov=c.state("covariance","robust_factor_covariance" if robust else "dynamic_factor_ewma" if method=="DYNAMIC_FACTOR" else "pca_factor_covariance",(factors,),lambda: _ewma(factors) if method=="DYNAMIC_FACTOR" else np.atleast_2d(np.cov(factors,rowvar=False)))
        residual=(np.clip(z,-3,3) if robust else z)-factors@loadings
        if method=="POET":
            sample=c.state("covariance","poet_residual_covariance",(residual,),lambda: np.atleast_2d(np.cov(residual,rowvar=False)))
            threshold=np.sqrt(np.log(max(z.shape[1],2))/len(z))*np.sqrt(np.outer(np.diag(sample),np.diag(sample)))
            specific=np.sign(sample)*np.maximum(np.abs(sample)-threshold,0.); np.fill_diagonal(specific,np.diag(sample))
        else:
            specific=np.diag(c.state("covariance","robust_specific_variance" if robust else "pca_specific_variance",(residual,),lambda: np.var(residual,axis=0,ddof=1)))
        cov=loadings.T@fcov@loadings+specific
    else: raise ValueError("UNKNOWN_R6_METHOD:"+method)
    return cov*np.outer(scale,scale)


def source_notes(inputs):
    """Exact input binding only; this never grants source/consumer qualification."""
    return dict(source_sha256=inputs.source_sha256,asset_uids=dict(inputs.asset_uids),
        identity_epochs=dict(inputs.identity_epochs),cutoff=_utc(inputs.cutoff).isoformat(),
        as_of=_utc(inputs.as_of).isoformat(),mature_max=_utc(inputs.mature_max).isoformat(),
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_NAV_qualified=False)


def compute_risk(method, inputs, *, learn=None, prior_covariance=None):
    """Return a mathematical estimate; caller alone qualifies use and activation.

    learn has the existing StateCache.learn(kind,name,inputs,compute) signature.
    In real mode it is mandatory and must be wrapped by the frozen R6 guard.
    """
    if method not in METHODS: raise ValueError("UNKNOWN_R6_METHOD")
    assets=validate_inputs(inputs)
    if not inputs.synthetic and learn is None: raise RiskInputBlocked("REAL_RESERVATION_CALLBACK_REQUIRED")
    bound_prior=prior_covariance
    if isinstance(prior_covariance,RiskEstimate):
        prior=prior_covariance
        if (prior.assets!=assets or prior.notes.get("source_sha256")!=inputs.source_sha256 or
                prior.notes.get("asset_uids")!=inputs.asset_uids or prior.notes.get("identity_epochs")!=inputs.identity_epochs or
                prior.notes.get("cutoff")!=_utc(inputs.cutoff).isoformat()):
            raise RiskInputBlocked("EXACT_PRIOR_SOURCE_UID_EPOCH_CUTOFF_REQUIRED")
        prior_covariance=prior.covariance
    elif prior_covariance is not None and not inputs.synthetic:
        raise RiskInputBlocked("REAL_TYPED_R6_PRIOR_ESTIMATE_REQUIRED")
    c=_Calculation(inputs,learn); raw=inputs.returns.to_numpy(float)
    if method in {"DYNAMIC_FACTOR","ROBUST_FACTOR","POET"} and min(raw.shape)<SPEC["factor_count"]:
        raise RiskInputBlocked("FIXED_FACTOR_COUNT_UNSUPPORTED")
    if method=="NONLINEAR": raise RiskInputBlocked("BLOCKED_DEPENDENCY:GENUINE_NONLINEAR_BACKEND_UNBOUND")
    bayes=method in {"HIER_POSTERIOR","BAYES_FACTOR","POSTERIOR_PREDICTIVE"}
    if method=="EVT" and not inputs.tail_source_qualified:
        raise RiskInputBlocked("BLOCKED_SOURCE:QUALIFIED_POOLED_TAIL_SOURCE_REQUIRED")
    if not bayes and method!="AVERAGE" and (len(raw)<30 or not np.isfinite(raw).all()):
        if prior_covariance is None or method in {"EMPIRICAL_CVAR","EVT","SEMIVARIANCE"}:
            raise RiskInputBlocked("COMPLETE_CLASSICAL_MATURE_SCENARIOS_REQUIRED")
        selected=np.flatnonzero(np.isfinite(raw).all(axis=0))
        if len(raw)<30 or not len(selected): raise RiskInputBlocked("NO_QUALIFIED_CLASSICAL_COMPONENT")
        short=RiskInputs(inputs.returns.iloc[:,selected],inputs.cutoff,inputs.as_of,
                         {assets[j]:inputs.asset_uids[assets[j]] for j in selected},inputs.source_sha256,
                         inputs.mature_max,inputs.market,inputs.synthetic,inputs.tail_source_qualified,
                         {assets[j]:inputs.identity_epochs[assets[j]] for j in selected} if inputs.identity_epochs else {})
        child=compute_risk(method,short,learn=learn)
        result, completion_proof=c.transform("posterior_conditional_completion:"+method,
            (prior_covariance,child.covariance,tuple(map(int,selected))),
            lambda: conditional_prior_completion(prior_covariance,child.covariance,tuple(map(int,selected))))
        completion_proof={**completion_proof,"scientific_method":"R6_CLASSICAL_PLUS_POSTERIOR_CONDITIONAL_COMPLETION"}
        return RiskEstimate("R6::"+method+"::POSTERIOR_CONDITIONAL_COMPLETION",assets,result,
                            "PASS_SYNTHETIC" if inputs.synthetic else "SOURCE_QUALIFICATION_PENDING",
                            "COVARIANCE",dict(child.notes,**source_notes(inputs),completion=completion_proof))
    if method=="AVERAGE":
        members=[compute_risk(m,inputs,learn=learn,prior_covariance=bound_prior) for m in SPEC["average_members"]]
        cov=c.transform("fixed_covariance_average",tuple(m.covariance for m in members),lambda: sum(w*m.covariance for w,m in zip(SPEC["average_weights"],members)))
    elif method=="EMPIRICAL_CVAR":
        tail=c.state("covariance","empirical_marginal_var_es",(inputs.returns,),lambda: _empirical_tail(raw))
        return RiskEstimate("R6::EMPIRICAL_CVAR::JOINT_SCENARIO_TAIL",assets,None,
            "PASS_SYNTHETIC" if inputs.synthetic else "SOURCE_QUALIFICATION_PENDING","TAIL_SCENARIOS",
            dict(**source_notes(inputs),operation_requests=c.counts,backend_calls=c.backend,coefficient_systems=c.systems,covariance_proxy=False),inputs.returns.copy(),tail)
    elif method=="EVT":
        z,_=_normal(inputs.returns,c)
        threshold=c.state("regime_threshold","pooled_tail_threshold",(z,),lambda: float(np.quantile(-z,SPEC["evt_quantile"])))
        excess=(-z).ravel(); excess=excess[excess>threshold]-threshold
        if len(excess)<SPEC["evt_min_exceedances"]: raise RiskInputBlocked("EVT_INSUFFICIENT_POOLED_EXCEEDANCES")
        def fit_tail():
            c.backend+=1
            reference=max(float(excess.mean()),SPEC["floor"])
            def nll(theta):
                shape,log_scale=theta; density=genpareto.logpdf(excess,shape,loc=0,scale=np.exp(log_scale))
                return -float(density.sum()) if np.isfinite(density).all() else 1e30
            fitted=minimize(nll,[0.,np.log(reference)],method="L-BFGS-B",
                bounds=[SPEC["evt_shape_bounds"],(np.log(reference/100),np.log(reference*100))],
                options=dict(maxiter=SPEC["evt_iterations"],ftol=SPEC["evt_tolerance"]))
            shape,log_scale=fitted.x;scale=np.exp(log_scale)
            if not fitted.success or not np.isfinite([shape,scale,fitted.fun]).all() or fitted.fun>=1e29 or shape>=.5 or scale<=0:
                raise RiskInputBlocked("EVT_FIXED_MLE_NOT_QUALIFIED")
            return dict(shape=float(shape),scale=float(scale),threshold=threshold,common_pooled_shape=True,
                        iid_cross_asset_claim=False,coverage_certified=False)
        tail=c.state("covariance","pooled_gpd_tail",(excess,),fit_tail)
        return RiskEstimate("R6::EVT::POOLED_STANDARDIZED_TAIL",assets,None,"PASS_SYNTHETIC" if inputs.synthetic else "SOURCE_QUALIFICATION_PENDING",
                            "TAIL_SCENARIOS",dict(**source_notes(inputs),operation_requests=c.counts,backend_calls=c.backend,coefficient_systems=c.systems,covariance_proxy=False),inputs.returns.copy(),tail)
    else: cov=_covariance(method,inputs,c)
    checked=validate_covariance(cov)
    if isinstance(checked,tuple): cov,check=checked
    else: cov=checked; check={}
    return RiskEstimate("R6::"+method+"::COMPLETE_DOMAIN",assets,cov,
        "PASS_SYNTHETIC" if inputs.synthetic else "SOURCE_QUALIFICATION_PENDING","COVARIANCE",
        dict(**source_notes(inputs),operation_requests=c.counts,backend_calls=c.backend,coefficient_systems=c.systems,
             covariance_validation=check,parameter_selection="fixed; no outer outcomes",
             latent_state_estimation=method in {"DCC","KALMAN"},
             dcc_parameter_optimizer_calls=0 if method=="DCC" else None,
             posterior_model="shared-factor multi-output conditional model; common fixed prior; no per-output tuning" if bayes else None))


def _empirical_tail(raw):
    loss=-raw; threshold=np.quantile(loss,SPEC["cvar_alpha"],axis=0)
    es=np.asarray([loss[loss[:,j]>=threshold[j],j].mean() for j in range(raw.shape[1])])
    return dict(var=threshold,expected_shortfall=es,alpha=SPEC["cvar_alpha"],
                marginal_summary_not_joint_portfolio_CVaR=True)


def specification():
    return dict(schema="B_R6_RISK_METHOD_SPEC_V1",methods=list(METHODS),parameters=SPEC,
        learned_upper_before_sharing=LEARNED_UPPER,primitive_dag=recipe_dag(),real_activation="caller frozen R6 guard + full source/UID qualification",
        source_readiness="UNKNOWN_UNTIL_R6_METADATA_DISCOVERY",nonlinear="BLOCKED_DEPENDENCY",
        evt="pooled standardized GPD; explicit source profile required; not individual asset EVT models",
        evt_source_requirements=dict(profile=SPEC['evt_source_profile'],raw_share_coordinate=True,horizon=5,
            fixed_parent_origins=252,full_ordered_current_UID_epoch_source_cutoff=True,
            genuine_complete_mature_joint_scenarios=True,posterior_fabrication=False,
            backend='existing SciPy fixed GPD likelihood',pre_existing_binary_macro_state_claim=False,
            insufficient_exceedances_after_threshold='FAILED_NONREFUNDABLE_NO_THRESHOLD_RELAXATION'),
        prior_completion="explicit R6 descendant; mature component preserved; original posterior conditional law",
        backend_call_is_not_matrix_dimension=True,failed_equivalent_tuple_retry=False,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_NAV_qualified=False)


def code_pins():
    paths=[Path(__file__),Path(__file__).with_name("joint_risk_estimators.py"),
           Path(__file__).with_name("event_risk_contract_r5.py")]
    return [dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]

# Exact names of planned physical states. All names map to real callback sites.
POSTERIOR_OPS=("market_mean","market_lw","donor_ols","donor_specific_variance",
               "global_variance_prior","nig_coefficients","nig_specific_posterior")
OPERATIONS={
    "DCC":("mean_and_variance","dcc_longrun_correlation","dcc_ewma_marginal_variance","dcc_fixed_parameter_latent_state"),
    "KALMAN":("mean_and_variance","market_mean","kalman_market_variance","kalman_initial_beta","kalman_innovation_variance","kalman_filtered_beta_posterior"),
    "DYNAMIC_FACTOR":("mean_and_variance","pca","dynamic_factor_ewma","pca_specific_variance"),
    "HUBER":("mean_and_variance","huber_second_moment"),
    "TYLER":("mean_and_variance","regularized_tyler_trace_shape"),
    "ROBUST_FACTOR":("mean_and_variance","huber_pca","robust_factor_covariance","robust_specific_variance"),
    "NONLINEAR":(),"POET":("mean_and_variance","pca","pca_factor_covariance","poet_residual_covariance"),
    "GRAPHICAL":("mean_and_variance","graphical_lasso"),"HIER_POSTERIOR":POSTERIOR_OPS,
    "BAYES_FACTOR":POSTERIOR_OPS+("factor_inverse_wishart_posterior",),
    "POSTERIOR_PREDICTIVE":POSTERIOR_OPS,"SEMIVARIANCE":("uncentered_downside_second_moment",),
    "EMPIRICAL_CVAR":("empirical_marginal_var_es",),"EVT":("mean_and_variance","pooled_tail_threshold","pooled_gpd_tail"),
}
OPERATIONS["AVERAGE"]=tuple(dict.fromkeys(op for member in SPEC["average_members"] for op in OPERATIONS[member]))


OPERATION_DEPENDENCIES={
    "mean_and_variance":(),"market_mean":(),"market_lw":("market_mean",),
    "donor_ols":("market_mean",),"donor_specific_variance":("donor_ols","market_mean"),
    "global_variance_prior":("donor_specific_variance",),"nig_coefficients":("market_mean","market_lw"),
    "nig_specific_posterior":("nig_coefficients","global_variance_prior","market_lw","market_mean"),
    "factor_inverse_wishart_posterior":("market_mean","market_lw"),
    "dcc_longrun_correlation":("mean_and_variance",),"dcc_ewma_marginal_variance":("mean_and_variance",),
    "dcc_fixed_parameter_latent_state":("mean_and_variance","dcc_longrun_correlation"),
    "kalman_market_variance":("market_mean",),"kalman_initial_beta":("mean_and_variance","market_mean"),
    "kalman_innovation_variance":("mean_and_variance","market_mean","kalman_initial_beta"),
    "kalman_filtered_beta_posterior":("mean_and_variance","market_mean","kalman_market_variance","kalman_initial_beta","kalman_innovation_variance"),
    "pca":("mean_and_variance",),"huber_pca":("mean_and_variance",),
    "dynamic_factor_ewma":("pca",),"pca_factor_covariance":("pca",),
    "pca_specific_variance":("pca",),"poet_residual_covariance":("pca",),
    "robust_factor_covariance":("huber_pca",),"robust_specific_variance":("huber_pca",),
    "huber_second_moment":("mean_and_variance",),"regularized_tyler_trace_shape":("mean_and_variance",),
    "graphical_lasso":("mean_and_variance",),"uncentered_downside_second_moment":(),
    "empirical_marginal_var_es":(),"pooled_tail_threshold":("mean_and_variance",),
    "pooled_gpd_tail":("mean_and_variance","pooled_tail_threshold"),
}


def recipe_dag():
    """Source-only plan, subject to exact actual source/cohort/cache equality."""
    def kind(op):
        return "scaler" if op in {"mean_and_variance","market_mean"} else "regime_threshold" if op=="pooled_tail_threshold" else "covariance"
    registry={o:dict(name="r6:"+o,kind=kind(o),phase="MATURE_WINDOW_RISK_STATE",
        cohort="complete fixed252 classical cohort" if o in {"mean_and_variance","dcc_longrun_correlation","dcc_ewma_marginal_variance","dcc_fixed_parameter_latent_state","pca","huber_pca","dynamic_factor_ewma","pca_factor_covariance","pca_specific_variance","poet_residual_covariance","robust_factor_covariance","robust_specific_variance","huber_second_moment","regularized_tyler_trace_shape","graphical_lasso","kalman_initial_beta","kalman_innovation_variance","kalman_filtered_beta_posterior"} else "current full UID posterior/factor domain or genuine full joint tail scenarios",
        dependencies=["r6:"+v for v in OPERATION_DEPENDENCIES[o]],
        event_dependency="PRIMARY+QQQ" if o in set(POSTERIOR_OPS)|{"factor_inverse_wishart_posterior","kalman_market_variance","kalman_initial_beta","kalman_innovation_variance","kalman_filtered_beta_posterior"} else "PRIMARY")
        for o in set(v for operations in OPERATIONS.values() for v in operations)}
    return dict(operation_registry=registry,methods={m:dict(operations=[dict(name="r6:"+o,kind=kind(o)) for o in OPERATIONS[m]],
        information_dependencies=["PRIMARY_UID_EPOCH_FIXED252"]+(["QQQ"] if m in {"KALMAN","HIER_POSTERIOR","BAYES_FACTOR","POSTERIOR_PREDICTIVE","AVERAGE"} else []),
        full_domain_requirement="genuine complete joint scenarios" if m in {"SEMIVARIANCE","EMPIRICAL_CVAR","EVT"} else "complete mature classical cohort + explicitly bound posterior completion, or full posterior domain",
        learned_no_sharing_upper=LEARNED_UPPER[m]) for m in METHODS},
        normalizer_state="joint mean-and-variance preprocessing snapshot, not p separate models",
        posterior_joint_model=dict(equation="y[a,t]=intercept[a]+beta[a]*(QQQ[t]-mean_QQQ)+epsilon[a,t]",
            common_factor=True,common_donor_global_variance_prior=True,conditional_independence_given_factor=True,
            common_fixed_hyperparameters=True,per_asset_capacity_seed_optimizer=False,
            joint_coefficient_matrix_state=True,joint_specific_variance_posterior_vector=True,
            actual_conditional_linear_systems="N_donor OLS + N_asset 2x2 posterior; report independently",
            factor_covariance_empirical_bayes=True,overlap_likelihood_weight=.2,coverage_certified=False),
        dcc=dict(estimated_hyperparameters=False,fixed_a=.01,fixed_b=.98,ewma_marginals=True,
                 terminal_filtered_state_is_counted=True,online_daily_updates=False),
        graphical=dict(old_alpha=.01,old_failures_preserved=True,new_alpha=SPEC["graphical_alpha"],
            effective_n="n/5 fixed overlap normalization, not estimated effective sample size",grid=False),
        FF48_dependency=False,source_readiness="UNKNOWN_UNTIL_ACTUAL_R6_METADATA_QUALIFICATION")


def learned_union_upper(event_count,*,include_qualified_evt=True):
    if type(event_count) is not int or event_count<0:raise ValueError("NONNEGATIVE_EXACT_EVENTS_REQUIRED")
    roster=[m for m in METHODS if include_qualified_evt or m!="EVT"]
    names=set(op for m in roster for op in OPERATIONS[m])
    kinds={"scaler":0,"covariance":0,"regime_threshold":0}
    for op in names:
        k="scaler" if op in {"mean_and_variance","market_mean"} else "regime_threshold" if op=="pooled_tail_threshold" else "covariance"
        kinds[k]+=1
    return dict(per_exact_common_event=len(names),events=event_count,total=len(names)*event_count,
        per_kind_per_event=kinds,per_kind_total={k:v*event_count for k,v in kinds.items()},
        conditions=["one fixed mature classical cohort/window per full-domain event","same QQQ/source/cutoff/full UID epoch context",
                    "shared StateCache exact complete input hash and frozen parameters","no per-method identity in cache key"],
        unknown_support_does_not_prove_readiness=True,no_refund=True,scientific_retry=0)


def prior_scale_from_market_states(mean,centered_lw_covariance):
    """1D assume-centered LW is MLE centered second moment; no new fit."""
    cov=np.asarray(centered_lw_covariance,float)
    if cov.shape!=(1,1) or not np.isfinite([mean,cov[0,0]]).all() or cov[0,0]<0:
        raise RiskInputBlocked("EXACT_1D_MARKET_STATE_REQUIRED")
    scale=np.sqrt(float(mean)**2+float(cov[0,0]))
    if scale<=0:raise RiskInputBlocked("POSITIVE_PRIOR_MARKET_RMS_REQUIRED")
    return float(scale)