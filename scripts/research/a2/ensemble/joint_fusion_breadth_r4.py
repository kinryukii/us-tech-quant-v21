"""Pure R4 native-B5D fusion/calibration; caller owns files, qualification and ledger.

Reuse the existing B statistical families/capacities. The old wrapper hardcodes
bridged members and performs hidden preprocessing, so this adapter separates
physical callbacks for a frozen native packet. No reader, account, cache or fit
registry is introduced. Caller-proven OOF pins are required; labels alone are
not upstream proof. Model callbacks must support estimator objects (R2's numeric
StateCache alone does not); scalar/scaler callbacks can use the existing cache.
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import minimize, nnls
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from threadpoolctl import threadpool_limits
from scripts.research.a2.ensemble import joint_five_day_fusion as prior

UNIT = prior.UNIT
METHODS = prior.METHODS
CONTEXT = prior.CONTEXT
SEEDS = (20260928, 20260929, 20260930)
STOCHASTIC = frozenset(("hgb_stack", "mlp_stack", "linear_gate", "mlp_gate"))
SPEC = dict(target=UNIT, sampling="ALL_QUALIFIED_EARLIER_GENUINE_OOF",
    methods=list(METHODS), seeds=list(SEEDS), aggregation="FIXED_EQUAL_ALL_SEEDS",
    fixed_weights=list(prior.SPEC["fixed_weights"]),
    capacity="EXISTING_B_SINGLE_FIXED_CAPACITY_NO_META_SELECTION",
    ridge_alpha=100., elastic_alpha=1e-5, elastic_l1_ratio=.35,
    hgb_iterations=64, hgb_depth=3, hgb_leaf=15, hgb_min_leaf=100,
    nn_epochs=10, nn_hidden=32, gate_hidden=16, nn_batch=512,
    meta_context=list(CONTEXT), scientific_retry=0,
    uncertainty="ONLY_GENUINE_PRIOR_OOF_OR_CHRONOLOGICAL_PROBE_HELDOUT_RMS",
    probability_calibration="BLOCKED_WITHOUT_B_DERIVED_TARGET",
    quantile_coverage_calibration="NO_EXISTING_QUALIFIED_COVERAGE_ALGORITHM",
    strict_PIT_promotion_eligible=False, quote_qualified=False,
    certified_nav_qualified=False, workers=1, library_threads=2)

class FusionBreadthBlocked(ValueError):
    pass

def physical_count_recipe(seeds=SEEDS, *, years=3, return_calibration_slots=22,
                          scale_proxy_slots=0, hgb_stochastic_phases=None):
    """Exact planned counts for all 11 methods with one shared packet per cutoff.

    Scalers and target scale share only identical actual rows/weights/axes/context.
    This is a fixed successful-input recipe, not actual support or an attempt log.
    """
    if tuple(seeds) not in (SEEDS, (20260928,)):
        raise FusionBreadthBlocked("UNFROZEN_SEED_TUPLE")
    if any(type(n) is not int or n < 0 for n in (years, return_calibration_slots, scale_proxy_slots)):
        raise FusionBreadthBlocked("NONNEGATIVE_SLOT_COUNTS_REQUIRED")
    if hgb_stochastic_phases is None:
        hgb_stochastic_phases=2*years
        support_bound="UPPER_BOUND_HGB_ROWS_NOT_YET_QUALIFIED"
    else:
        if type(hgb_stochastic_phases) is not int or not 0<=hgb_stochastic_phases<=2*years:
            raise FusionBreadthBlocked("HGB_PHASE_COUNT_INVALID")
        support_bound="EXACT_GIVEN_FROZEN_QUALIFIED_PHASE_COUNTS"
    models=10+6*len(seeds)  # HGB full-row deterministic baseline: one per phase
    per_year=dict(model_fit=models,scaler=6,bridge_calibration=11)
    totals={k:v*years for k,v in per_year.items()}
    totals["model_fit"]+=(len(seeds)-1)*hgb_stochastic_phases
    totals["scaler"] += 2*return_calibration_slots
    totals["bridge_calibration"] += 3*return_calibration_slots + scale_proxy_slots
    return dict(per_meta_year_base=per_year, planned_per_kind=totals,
        hgb_stochastic_phases=hgb_stochastic_phases,support_count_evidence=support_bound,
        planned_learned_units=sum(totals.values()), new_base_fits=0,
        scientific_retry=0, deterministic_combinations_are_learned_fits=False,
        assumption="All frozen slots qualified; exact shared preprocessing succeeds.",
        risk_and_B_history_not_reset=True)

def _time(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise FusionBreadthBlocked("AWARE_OOF_CLOCK_REQUIRED")
    t = t.tz_convert("UTC")
    if t >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise FusionBreadthBlocked("PRE2026_OOF_BOUNDARY")
    return t

def _sha(value):
    return isinstance(value,str) and len(value)==64 and set(value)<=set("0123456789abcdef")

def _clock_column(frame, column):
    try:
        return pd.Series([_time(v) for v in frame[column]], index=frame.index)
    except (KeyError, TypeError, ValueError):
        raise FusionBreadthBlocked("OOF_CLOCK_INVALID:"+column) from None

IDENTITY = ("security_id", "security_id_type", "cusip", "active_13f_quarter", "quarter_universe_fingerprint")

def identity_columns(history):
    """Preserve one producer's actual identity schema without invented epochs."""
    if {"security_uid","asset_epoch"}.issubset(history.columns):
        fields=("security_uid","asset_epoch")
        if history.asset_epoch.isna().any():raise FusionBreadthBlocked("UNKNOWN_UID_OR_EPOCH")
    elif set(IDENTITY).issubset(history.columns):
        fields=IDENTITY
        for c in ("security_id_type","active_13f_quarter","quarter_universe_fingerprint"):
            if history[c].isna().any():raise FusionBreadthBlocked("ORIGINAL_IDENTITY_PROJECTION_REQUIRED")
    else:raise FusionBreadthBlocked("ORIGINAL_IDENTITY_PROJECTION_REQUIRED")
    uid=history[fields[0]]
    if not uid.map(lambda v:isinstance(v,str) and bool(v.strip()) and not v.upper().startswith("UNKNOWN")).all():
        raise FusionBreadthBlocked("UNKNOWN_UID_OR_EPOCH")
    return fields

def prepare_history(history, cutoff, members, *, value_columns=None, minimum_rows=100,
                    producer_role="GENUINE_ANNUAL_MODEL_OOF"):
    """Prove metadata eligibility before accessing any target/predictor values."""
    cutoff = _time(cutoff); members = tuple(members)
    if not members or len(set(members))!=len(members):
        raise FusionBreadthBlocked("FIXED_UNIQUE_COMPLETE_PACKET_REQUIRED")
    required = ("signal_date","ticker",
        "label_end_date","label_mature_date","fit_eligible","y_open5")
    if any(c not in history for c in required):
        raise FusionBreadthBlocked("OOF_IDENTITY_OR_TRUTH_FIELDS_REQUIRED")
    for field in ("source_inputs_sha256","target_binding_sha256",
                  "qualified_oof_contract_sha256"):
        if not _sha(history.attrs.get(field)):
            raise FusionBreadthBlocked("UPSTREAM_OOF_PIN_REQUIRED:"+field)
    if history.attrs.get("target_coordinate")!=UNIT:
        raise FusionBreadthBlocked("NATIVE_B5D_TARGET_REQUIRED")
    if history.duplicated(["signal_date","ticker"]).any():
        raise FusionBreadthBlocked("DUPLICATE_OOF_KEY")
    if history.ticker.isna().any():raise FusionBreadthBlocked("UNKNOWN_UID_OR_EPOCH")
    identity_columns(history)
    h=history.copy()
    for c in ("signal_date","label_end_date","label_mature_date"):
        h[c]=_clock_column(h,c)
    if any(type(v) not in (bool,np.bool_) for v in h.fit_eligible):
        raise FusionBreadthBlocked("TYPED_FIT_ELIGIBILITY_REQUIRED")
    eligible=h.fit_eligible.eq(True)&h.signal_date.lt(cutoff)&h.label_end_date.lt(cutoff)&h.label_mature_date.lt(cutoff)
    h=h.loc[eligible].copy()
    if len(h)<minimum_rows:
        raise FusionBreadthBlocked("INSUFFICIENT_EARLIER_OOF_ROWS")
    for m in members:
        fields=[m+"__source_cutoff",m+"__source_label_mature_max",
                m+"__source_sha256",m+"__producer_role"]
        if any(c not in h for c in fields):
            raise FusionBreadthBlocked("MEMBER_OOF_LINEAGE_REQUIRED:"+m)
        source=_clock_column(h,fields[0]);mature=_clock_column(h,fields[1])
        if source.gt(h.signal_date).any() or mature.ge(source).any():
            raise FusionBreadthBlocked("GENUINE_OOF_SOURCE_CLOCK_VIOLATION:"+m)
        if not h[fields[2]].map(_sha).all() or not h[fields[3]].eq(producer_role).all():
            raise FusionBreadthBlocked("GENUINE_OOF_PRODUCER_PROOF_REQUIRED:"+m)
    columns=list(value_columns or [m+"__mu" for m in members])
    if any(c not in h for c in columns):
        raise FusionBreadthBlocked("MISSING_MEMBER_NO_PACKET_SHRINK")
    if not np.isfinite(h[columns].to_numpy(float)).all() or not np.isfinite(h.y_open5.to_numpy(float)).all():
        raise FusionBreadthBlocked("NONFINITE_MEMBER_NO_ROW_DROP")
    h.attrs.update(history.attrs)
    return h,cutoff,columns

def _weights(h):
    return prior.date_weights(h)

def _frame_inputs(h, columns):
    # Retain dates, UIDs, epochs, producer clocks and pins in physical identity.
    cols=[c for c in h if c in ("signal_date","ticker","security_uid","asset_epoch",
        "label_end_date","label_mature_date","y_open5",*IDENTITY) or "__source_" in c
        or c.endswith("__producer_role") or c in columns]
    return (h[list(dict.fromkeys(cols))].copy(), _weights(h))

def _learn(learn, kind, name, inputs, compute, parameters):
    if not callable(learn):
        raise FusionBreadthBlocked("CALLER_DURABLE_PHYSICAL_LEARN_REQUIRED")
    return learn(kind,name,inputs,compute,parameters=parameters)

@dataclass
class ScalerState:
    mean:object
    scale:object
    variance:object
    sample_count:object
    def transform(self,x):
        return (np.asarray(x,float)-self.mean)/self.scale

def _fit_scaler(h,columns):
    fitted=StandardScaler().fit(h[columns].to_numpy(float),sample_weight=_weights(h))
    return ScalerState(fitted.mean_,fitted.scale_,fitted.var_,fitted.n_samples_seen_)

def _scaler(h, columns, phase, learn, role="member"):
    state=_learn(learn,"scaler","r4:"+role+"_scaler:"+phase,_frame_inputs(h,columns),
        lambda:_fit_scaler(h,columns),
        dict(role=role,columns=list(columns),phase=phase,capacity="weighted population moments"))
    return state

def _target_scale(h, phase, learn):
    return _learn(learn,"scaler","r4:target_RMS_scale:"+phase,_frame_inputs(h,()),
        lambda:max(float(np.sqrt(np.mean(h.y_open5.to_numpy(float)**2))),1e-6),
        dict(phase=phase,weighting="unweighted target_RMS",role="target_scale"))

@dataclass
class FrozenMeta:
    method:str
    members:tuple
    models:tuple
    scaler:object=None
    coefficients:object=None
    def predict(self,x,context):
        x=np.asarray(x,float);context=np.asarray(context,float)
        if x.ndim!=2 or x.shape[1]!=len(self.members) or not np.isfinite(x).all():
            raise FusionBreadthBlocked("COMPLETE_FUTURE_PACKET_REQUIRED")
        if self.method=="equal":return x.mean(axis=1)
        if self.method=="median":return np.median(x,axis=1)
        if self.method=="fixed_weighted":return x@self.coefficients
        if self.method in ("nnls","simplex"):
            return np.mean([x@c for c in self.models],axis=0)
        xx=self.scaler.transform(context if self.method.endswith("_gate") else x)
        if self.method.endswith("_gate"):
            import torch
            with torch.no_grad():
                return np.mean([(model(torch.tensor(np.clip(xx,-8,8),dtype=torch.float32)).numpy()*x).sum(axis=1) for model in self.models],axis=0)
        return np.mean([model.predict(xx) for model in self.models],axis=0)

def _optimizer(method,h,columns,scaler,scale,seed):
    x=h[columns].to_numpy(float);y=h.y_open5.to_numpy(float);w=_weights(h)
    if method=="nnls":
        root=np.sqrt(w)
        return nnls(x*root[:,None],y*root)[0]
    if method=="simplex":
        xx=x/scale;yy=y/scale
        result=minimize(lambda a:float(np.average((xx@a-yy)**2,weights=w)),
            np.full(x.shape[1],1/x.shape[1]),jac=lambda a:2*xx.T@(w*(xx@a-yy))/w.sum(),
            method="SLSQP",bounds=[(0.,1.)]*x.shape[1],
            constraints=[{"type":"eq","fun":lambda a:a.sum()-1,"jac":lambda a:np.ones_like(a)}],
            options={"maxiter":500,"ftol":1e-10})
        if not result.success:raise FusionBreadthBlocked("SIMPLEX_NOT_CONVERGED")
        return result.x
    if method.endswith("_gate"):
        handler=prior._shared_handler()
        import torch
        torch.manual_seed(seed);torch.set_num_threads(2)
        model=handler.__globals__["GateNetwork"](len(columns),method=="mlp_gate")
        context=np.clip(scaler.transform(h[list(CONTEXT)].to_numpy(float)),-8,8)
        xx=torch.tensor(context,dtype=torch.float32)
        experts=torch.tensor(x/scale,dtype=torch.float32);yy=torch.tensor(y/scale,dtype=torch.float32)
        ww=torch.tensor(w,dtype=torch.float32);opt=torch.optim.Adam(model.parameters(),lr=.001,weight_decay=.0001)
        rng=torch.Generator().manual_seed(seed)
        for _ in range(10):
            order=torch.randperm(len(xx),generator=rng)
            for start in range(0,len(xx),512):
                j=order[start:start+512];opt.zero_grad()
                loss=(ww[j]*((model(xx[j])*experts[j]).sum(dim=1)-yy[j])**2).mean()
                if not torch.isfinite(loss):raise FusionBreadthBlocked("NONFINITE_GATE_OPTIMIZATION")
                loss.backward();opt.step()
        return model.eval()
    models={"ridge_stack":lambda:Ridge(alpha=100.),
        "elastic_stack":lambda:ElasticNet(alpha=1e-5,l1_ratio=.35,max_iter=2500,tol=1e-5,random_state=seed),
        "hgb_stack":lambda:HistGradientBoostingRegressor(max_iter=64,max_depth=3,max_leaf_nodes=15,
            min_samples_leaf=100,learning_rate=.05,l2_regularization=1.,early_stopping=False,random_state=seed),
        "mlp_stack":lambda:MLPRegressor(hidden_layer_sizes=(32,),max_iter=10,n_iter_no_change=11,
            batch_size=512,learning_rate_init=.001,alpha=.0001,random_state=seed,early_stopping=False)}
    model=models[method]()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always");model.fit(scaler.transform(x),y,sample_weight=w)
    convergence=any(c.category.__name__=="ConvergenceWarning" for c in caught)
    if method=="mlp_stack":
        if model.n_iter_!=10:raise FusionBreadthBlocked("FIXED_META_EPOCHS_INCOMPLETE")
        # Max-iteration warning reflects the frozen 10-update budget, not convergence.
        model.r4_fixed_budget_warning=convergence
    elif convergence:
        raise FusionBreadthBlocked("UNRESOLVED_META_CONVERGENCE_NO_RETRY")
    return model

def _phase_seeds(method,rows,seeds):
    # Canonical sklearn _BinMapper subsamples only n>200000; full features,
    # early_stopping=False. No repeated seed fit when randomness is unused.
    return (20260928,) if method=="hgb_stack" and rows<=200000 else tuple(seeds)

def _fit_phase(method,h,columns,phase,members,learn,seeds,weights):
    if method in ("equal","median","fixed_weighted"):
        return FrozenMeta(method,members,(),coefficients=np.asarray(weights,float))
    scaler=None;scale=None
    if method in ("ridge_stack","elastic_stack","hgb_stack","mlp_stack"):
        scaler=_scaler(h,columns,phase,learn)
    if method.endswith("_gate"):
        if any(c not in h for c in CONTEXT) or not np.isfinite(h[list(CONTEXT)].to_numpy(float)).all():
            raise FusionBreadthBlocked("QUALIFIED_CONTEXT_REQUIRED")
        scaler=_scaler(h,list(CONTEXT),phase,learn,"context")
    if method in ("simplex","linear_gate","mlp_gate"):
        scale=_target_scale(h,phase,learn)
    models=[];errors=[]
    for seed in _phase_seeds(method,len(h),seeds) if method in STOCHASTIC else (20260928,):
        try:
            models.append(_learn(learn,"model_fit","r4:meta:"+method+":"+phase+":"+str(seed),
                _frame_inputs(h,columns+list(CONTEXT) if method.endswith("_gate") else columns),
                lambda seed=seed:_optimizer(method,h,columns,scaler,scale,seed),
                dict(method=method,phase=phase,seed=seed,capacity=SPEC,members=list(members))))
        except Exception as exc:
            errors.append(type(exc).__name__+":"+str(exc))
    if errors:raise FusionBreadthBlocked("FROZEN_SEED_SET_FAILED_NO_SHRINK:"+ "|".join(errors))
    return FrozenMeta(method,members,tuple(models),scaler=scaler)

def fit_meta(history,cutoff,method,members,learn,*,seeds=SEEDS,fixed_weights=None):
    if method not in METHODS or tuple(seeds) not in (SEEDS,(20260928,)):
        raise FusionBreadthBlocked("METHOD_OR_SEEDS_NOT_FROZEN")
    h,cut,columns=prepare_history(history,cutoff,members)
    members=tuple(members);weights=tuple(SPEC["fixed_weights"] if fixed_weights is None else fixed_weights)
    if len(weights)!=len(members) or not np.isfinite(weights).all() or min(weights)<0 or not np.isclose(sum(weights),1):
        raise FusionBreadthBlocked("FROZEN_FIXED_WEIGHTS_REQUIRED")
    static=method in ("equal","median","fixed_weighted")
    dates=sorted(h.signal_date.unique());boundary=dates[len(dates)//2]
    first=h.loc[h.signal_date.lt(boundary)&h.label_mature_date.lt(boundary)&h.label_end_date.lt(boundary)].copy()
    held=h if static else h.loc[h.signal_date.ge(boundary)].copy()
    if not static and (len(first)<100 or len(held)<100):
        raise FusionBreadthBlocked("CHRONOLOGICAL_PROBE_INSUFFICIENT")
    models={};errors=[]
    with threadpool_limits(limits=2):
        for phase,frame in (("probe",first),("full",h)) if not static else (("full",h),):
            try:models[phase]=_fit_phase(method,frame,columns,phase,members,learn,seeds,weights)
            except Exception as exc:errors.append(type(exc).__name__+":"+str(exc))
    if errors:
        return dict(status="FAILED_SCIENTIFIC_NO_RETRY",errors=errors,model=models.get("full"),
            prior_OOF_error_RMS=None,qualified=False,scientific_retry=0)
    probe=models["full" if static else "probe"]
    context=held[list(CONTEXT)].to_numpy(float) if all(c in held for c in CONTEXT) else np.empty((len(held),0))
    prediction=probe.predict(held[columns].to_numpy(float),context)
    if not np.isfinite(prediction).all():raise FusionBreadthBlocked("NONFINITE_FROZEN_SEED_AGGREGATE")
    rms=_learn(learn,"bridge_calibration","r4:meta_prior_OOF_RMS:"+method,
        (_frame_inputs(held,columns),prediction),
        lambda:max(float(np.sqrt(np.average((held.y_open5.to_numpy(float)-prediction)**2,weights=_weights(held)))),1e-6),
        dict(method=method,members=list(members),seeds=list(seeds),source="GENUINE_EARLIER_OOF_STATIC" if static else "CHRONOLOGICAL_PROBE_HELDOUT"))
    return dict(status="COMPLETE_FROZEN_MECHANISM_META",model=models["full"],prior_OOF_error_RMS=rms,
        cutoff=cut.isoformat(),probe_boundary=None if static else str(boundary),
        probe_maturity_max=None if static else first.label_mature_date.max().isoformat(),
        members=list(members),seeds=list(seeds),
        actual_phase_seeds={phase:list(_phase_seeds(method,len(frame),seeds) if method in STOCHASTIC else (20260928,))
            for phase,frame in (("probe",first),("full",h)) if phase in models},
        qualified=True,scientific_retry=0,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)

def fit_return_calibration(history,cutoff,members,value_columns,learn,*,name,
                           producer_role="GENUINE_ANNUAL_META_OOF"):
    """Affine value map and independent probe-heldout RMS, never fitted residuals."""
    h,cut,columns=prepare_history(history,cutoff,members,value_columns=value_columns,producer_role=producer_role)
    dates=sorted(h.signal_date.unique());boundary=dates[len(dates)//2]
    first=h.loc[h.signal_date.lt(boundary)&h.label_mature_date.lt(boundary)&h.label_end_date.lt(boundary)].copy()
    held=h.loc[h.signal_date.ge(boundary)].copy()
    if len(first)<100 or len(held)<100:raise FusionBreadthBlocked("CALIBRATION_PROBE_INSUFFICIENT")
    models={}
    for phase,frame in (("probe",first),("full",h)):
        scaler=_scaler(frame,columns,phase,learn,"return_calibration:"+name)
        model=_learn(learn,"bridge_calibration","r4:return_calibrator:"+name+":"+phase,
            _frame_inputs(frame,columns),lambda frame=frame,scaler=scaler:Ridge(alpha=100.).fit(
                scaler.transform(frame[columns].to_numpy(float)),frame.y_open5.to_numpy(float),sample_weight=_weights(frame)),
            dict(name=name,phase=phase,alpha=100.,columns=columns))
        models[phase]=(scaler,model)
    scaler,model=models["probe"];prediction=model.predict(scaler.transform(held[columns].to_numpy(float)))
    rms=_learn(learn,"bridge_calibration","r4:return_calibrator_true_OOF_RMS:"+name,
        (_frame_inputs(held,columns),prediction),lambda:max(float(np.sqrt(
            np.average((held.y_open5.to_numpy(float)-prediction)**2,weights=_weights(held)))),1e-6),
        dict(name=name,source="CHRONOLOGICAL_CALIBRATOR_PROBE_HELDOUT"))
    scaler,model=models["full"]
    return dict(scaler=scaler,model=model,prior_OOF_error_RMS=rms,cutoff=cut.isoformat(),
        fit_units=5,in_fit_RMS_estimated=False,genuine_chronological_uncertainty=True,
        certified_coverage=False)

def fit_native_scale_proxy(history,cutoff,members,mu_column,scale_column,learn,*,name):
    h,cut,columns=prepare_history(history,cutoff,members,value_columns=[mu_column,scale_column])
    if h[scale_column].le(0).any():raise FusionBreadthBlocked("POSITIVE_NATIVE_SCALE_REQUIRED")
    def estimate():
        factor=float(np.sqrt(np.average(
            ((h.y_open5.to_numpy(float)-h[mu_column].to_numpy(float))/h[scale_column].to_numpy(float))**2,weights=_weights(h))))
        if not np.isfinite(factor) or factor<=0:raise FusionBreadthBlocked("NONPOSITIVE_SCALE_PROXY")
        return factor
    multiplier=_learn(learn,"bridge_calibration","r4:native_scale_proxy:"+name,
        _frame_inputs(h,columns),estimate,
        dict(name=name,source="GENUINE_EARLIER_NATIVE_OOF_ERROR",coverage="UNCERTIFIED_SCALE_PROXY"))
    if not np.isfinite(multiplier) or multiplier<=0:raise FusionBreadthBlocked("NONPOSITIVE_SCALE_PROXY")
    return dict(multiplier=multiplier,cutoff=cut.isoformat(),fit_units=1,certified_coverage=False)
