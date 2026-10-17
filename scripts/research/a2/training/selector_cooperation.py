"""Pure selector cooperation over the retained statistical adapters; no I/O."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import nnls

UNIT = "Raw MEAN_ER_3D_5D_10D_20D decimal"
MEMBERS = ("ridge", "hgb", "xgb_rank", "logistic", "cat_uncertainty")
CONTEXT = ("ret_1d", "ret_20d", "realized_vol_20d", "realized_vol_60d", "volume_ratio_5d_20d")
METHODS = ("equal", "median", "fixed_weighted", "nnls", "simplex", "ridge_stack",
           "elastic_stack", "hgb_stack", "mlp_stack", "linear_gate", "mlp_gate",
           "ridge_then_hgb", "hgb_then_ridge")
SPEC = {"methods": METHODS, "unit": UNIT, "target_adapter": "y_next_open = target; values unchanged",
        "base_lineage": "MODEL_OOF, source_cutoff < signal_date, label_end_date < fit cutoff",
        "meta_lineage": "CALIBRATED_OOF; every member calibration_cutoff < signal_date and calibration_max_label_end < calibration_cutoff",
        "seed": 20260928, "max_rows": 40000, "sampling": "retained sample; deterministic day-balanced quota",
        "date_weighting": "retained date_weights; equal total weight per date",
        "contexts": CONTEXT, "fixed_members": MEMBERS, "fixed_weights": (.30, .25, .20, .15, .10),
        "nnls": "weighted scipy.optimize.nnls; nonnegative, unnormalized, no intercept",
        "uncertainty": "chronological date half; probe trained only on labels mature before boundary; second-half residual RMS and scale; future calibrator refit all earlier mature OOF",
        "probability_label": "target > 0", "svc": "raw decision score; not PROB",
        "residual": "root fits on 32 features against true stage1 annual OOF; not retained meta residual",
        "architecture_search": False}

@dataclass
class LinearFusion:
    method: str
    members: list
    coefficients: np.ndarray
    def predict(self, mu, context=None):
        x = np.asarray(mu, dtype=float)
        if x.ndim != 2 or x.shape[1] != len(self.members) or not np.isfinite(x).all():
            raise ValueError("INVALID_FUSION_MEMBER_MATRIX")
        return x @ self.coefficients


def _guard(frame, cutoff, kind):
    h = frame.copy()
    required = {"signal_date", "ticker", "security_uid", "U_t_fingerprint", "target",
                "label_end_date", "source_kind", "source_cutoff"}
    if not required.issubset(h) or h.empty or h[list(required)].isna().any().any():
        raise ValueError("MISSING_OOF_IDENTITY_OR_LINEAGE")
    cut = pd.Timestamp(cutoff)
    if cut > pd.Timestamp("2026-01-01"):
        raise ValueError("FIT_CUTOFF_AFTER_PRE2026")
    for key in ("signal_date", "label_end_date", "source_cutoff"):
        h[key] = pd.to_datetime(h[key])
    if (h.duplicated(["signal_date", "ticker"]).any() or not h.source_kind.eq(kind).all()
            or not h.source_cutoff.lt(h.signal_date).all()
            or not h.signal_date.lt(cut).all() or not h.label_end_date.lt(cut).all()
            or not np.isfinite(h.target.to_numpy(float)).all()):
        raise ValueError("OOF_LINEAGE_OR_MATURITY_VIOLATION")
    h["y_next_open"] = h.target
    return h, cut


def _sampling(module):
    if module.SEED != SPEC["seed"] or module.MAX_ROWS != SPEC["max_rows"]:
        raise ValueError("RETAINED_SAMPLING_SPEC_CHANGED")


def fit_calibration(module, name, history, cutoff):
    _sampling(module)
    h, cut = _guard(history, cutoff, "MODEL_OOF")
    if not np.isfinite(module.inputs(h, name)).all():
        raise ValueError("UNAVAILABLE_BASE_PREDICTION_DO_NOT_DROP")
    if name in module.DISTRIBUTION and (not np.isfinite(h[f"{name}__scale"]).all() or h[f"{name}__scale"].le(0).any()):
        raise ValueError("INVALID_BASE_DISTRIBUTION_SCALE_DO_NOT_DROP")
    dates = np.sort(h.signal_date.unique())
    if len(dates) < 2:
        raise ValueError("CHRONOLOGICAL_UNCERTAINTY_HISTORY_TOO_SHORT")
    boundary = pd.Timestamp(dates[len(dates) // 2])
    first = h.loc[h.signal_date.lt(boundary) & h.label_end_date.lt(boundary)]
    second = h.loc[h.signal_date.ge(boundary)]
    if first.empty or second.empty:
        raise ValueError("NO_MATURE_CHRONOLOGICAL_UNCERTAINTY_SPLIT")
    probe, probe_receipt = module.fit_calibration(name, first, boundary)
    held = module.sample(second)
    mu, provisional_scale, _ = probe.predict(held)
    residual = held.target.to_numpy(float) - mu
    weights = module.date_weights(held.signal_date)
    sigma = held[f"{name}__scale"].to_numpy(float) if name in module.DISTRIBUTION else provisional_scale
    if not np.isfinite(residual).all() or not np.isfinite(sigma).all() or np.any(sigma <= 0):
        raise ValueError("INVALID_HELDOUT_UNCERTAINTY")
    rms = max(float(np.sqrt(np.average(residual ** 2, weights=weights))), 1e-6)
    multiplier = float(np.sqrt(np.average((residual / np.maximum(sigma, 1e-6)) ** 2, weights=weights)))
    obj, receipt = module.fit_calibration(name, h, cut)
    obj.residual_rms = rms
    if name in module.DISTRIBUTION:
        obj.scale_multiplier = multiplier
    receipt.pop("residual_rms_in_fit", None)
    amplitude = 2 if name in module.PROB else 0
    receipt.update(unit=UNIT, calibration_unit=UNIT, spec=SPEC, reused_source_spec=module.SPEC,
        source_kind="MODEL_OOF", max_label_end=str(h.label_end_date.max()),
        uncertainty_boundary=str(boundary), uncertainty_first_rows=len(first), uncertainty_heldout_rows=len(held),
        probe_max_label_end=probe_receipt["max_label_end"], uncertainty_heldout_max_label_end=str(held.label_end_date.max()),
        residual_rms_chronological_holdout=rms, scale_multiplier=multiplier,
        scale_multiplier_applied=name in module.DISTRIBUTION, legacy_in_fit_uncertainty_discarded=True,
        delegated_calibration_calls=2, preprocessing_fit_count=2, model_fit_count=2,
        uncertainty_statistical_fit_count=2, signed_amplitude_mapping_fit_count=amplitude,
        signed_amplitude_scalar_parameter_count=2 * amplitude, total_fit_count=6 + amplitude)
    return obj, receipt


def fit_fusion(module, method, members, frame, cutoff):
    _sampling(module)
    if method not in METHODS[:11] or tuple(members) != MEMBERS:
        raise ValueError("UNREGISTERED_FUSION_OR_MEMBER_ORDER")
    h, cut = _guard(frame, cutoff, "CALIBRATED_OOF")
    for name in members:
        cc, ml = f"{name}__calibration_cutoff", f"{name}__calibration_max_label_end"
        if cc not in h or ml not in h or h[[cc, ml]].isna().any().any():
            raise ValueError("MISSING_CALIBRATED_OOF_LINEAGE")
        cc_values, ml_values = pd.to_datetime(h[cc]), pd.to_datetime(h[ml])
        if not cc_values.lt(h.signal_date).all() or not ml_values.lt(cc_values).all():
            raise ValueError("CALIBRATED_OOF_CLOCK_VIOLATION")
    columns = [f"{name}__mu" for name in members]
    if not np.isfinite(h[columns].to_numpy(float)).all():
        raise ValueError("UNAVAILABLE_MEMBER_DO_NOT_DROP")
    learned, preprocessing, target_scale = 0, 0, 0
    if method in ("fixed_weighted", "nnls"):
        sampled = module.sample(h)
        coefficients = np.asarray(SPEC["fixed_weights"], float)
        if method == "nnls":
            weight = np.sqrt(module.date_weights(sampled.signal_date))
            coefficients, _ = nnls(sampled[columns].to_numpy(float) * weight[:, None], sampled.target.to_numpy(float) * weight)
            learned = 1
        obj = LinearFusion(method, list(members), coefficients)
        receipt = {"method": method, "members": list(members), "rows": len(sampled), "coefficients": coefficients.tolist()}
    else:
        obj, receipt = module.fit_fusion(method, list(members), h, cut)
        learned = int(method not in ("equal", "median"))
        preprocessing = int(method not in ("equal", "median", "simplex"))
        target_scale = int(method in ("simplex", "linear_gate", "mlp_gate"))
    receipt.update(unit=UNIT, spec=SPEC, reused_source_spec=module.SPEC, source_kind="CALIBRATED_OOF",
        cutoff_exclusive=str(cut.date()), max_signal=str(h.signal_date.max()), max_label_end=str(h.label_end_date.max()),
        preprocessing_fit_count=preprocessing, model_fit_count=learned, statistical_fit_count=target_scale,
        total_fit_count=preprocessing + learned + target_scale, coefficient_normalization=False if method == "nnls" else None)
    return obj, receipt


# Explicit new full-stock profile. Legacy fit_fusion/calibration defaults above
# keep their old sampler, member order and source contract.
FULL_STOCK_MEMBERS=("RIDGE","HGB","XGB","CAT","MLP","QUANTILE_HGB")
FULL_STOCK_METHODS=("equal","median","simplex","nnls","ridge_stack","elastic_stack",
    "hgb_stack","mlp_stack","linear_gate","mlp_gate","ridge_then_hgb","hgb_then_ridge")
FULL_STOCK_STOCHASTIC=("mlp_stack","linear_gate","mlp_gate")
FULL_STOCK_SEEDS=(20260928,20260929,20260930)


@dataclass
class FullStockFusion:
    kind: str
    model: object = None
    scaler: object = None
    base_index: int = 0
    models: object = None
    seeds: object = None


def _full_stock_oof(frame,cutoff,base32,context,expected_full_day_uids):
    h=frame.copy();cut=pd.Timestamp(cutoff)
    required={"signal_date","security_uid","U_t_fingerprint","label_end_date","target"}
    if h.empty or not required.issubset(h):raise ValueError("FULL_STOCK_OOF_IDENTITY_REQUIRED")
    if cut.tz is not None or cut>pd.Timestamp("2026-01-01"):raise ValueError("FULL_STOCK_CUTOFF_PRE2026_REQUIRED")
    for field in ("signal_date","label_end_date"):h[field]=pd.to_datetime(h[field])
    if h[list(required)].isna().any().any() or h.duplicated(["signal_date","security_uid"]).any():raise ValueError("FULL_STOCK_OOF_DUPLICATE_OR_UNKNOWN")
    if not h.signal_date.lt(cut).all() or not h.label_end_date.lt(cut).all() or not h.label_end_date.gt(h.signal_date).all():raise ValueError("FULL_STOCK_MATURE_PAST_OOF_REQUIRED")
    if not h.groupby("signal_date").U_t_fingerprint.nunique().eq(1).all():raise ValueError("FULL_STOCK_OOF_FINGERPRINT_AMBIGUOUS")
    expected={pd.Timestamp(k):tuple(v) for k,v in expected_full_day_uids.items()}
    if set(expected)!=set(h.signal_date.unique()):raise ValueError("FULL_STOCK_OOF_ALL_DATES_REQUIRED")
    for day,g in h.groupby("signal_date",sort=True):
        uids=tuple(g.security_uid)
        if any(not isinstance(v,str) or not v.strip() or v=="UNKNOWN" for v in uids) or uids!=tuple(sorted(uids)) or uids!=expected[day]:
            raise ValueError("FULL_STOCK_OOF_EXACT_FULL_UID_AXIS_REQUIRED")
    for member in FULL_STOCK_MEMBERS:
        fields=[member+"__"+suffix for suffix in ("mu","source_kind","source_cutoff","source_capacity","max_train_label_end","cutoff_clock")]
        if not set(fields).issubset(h) or h[fields].isna().any().any():raise ValueError("FULL_STOCK_ALL_SIX_REAL_OOF_MEMBERS_REQUIRED")
        source=pd.to_datetime(h[member+"__source_cutoff"]);last=pd.to_datetime(h[member+"__max_train_label_end"])
        if not h[member+"__source_kind"].eq("MODEL_OOF").all() or not h[member+"__source_capacity"].eq("MID").all() or not h[member+"__cutoff_clock"].eq("MIDNIGHT_BEFORE_DECISION_CLOSE").all() or not source.le(h.signal_date).all() or not last.lt(source).all():
            raise ValueError("FULL_STOCK_GENUINE_FIXED_MID_OOF_REQUIRED")
    mu=h[[m+"__mu" for m in FULL_STOCK_MEMBERS]].to_numpy(float);y=h.target.to_numpy(float)
    xx=np.asarray(base32,float);cx=np.asarray(context,float)
    if mu.shape!=(len(h),6) or not np.isfinite(mu).all() or not np.isfinite(y).all() or xx.shape!=(len(h),32) or cx.shape!=(len(h),5) or np.isinf(xx).any() or np.isinf(cx).any():
        raise ValueError("FULL_STOCK_OOF_ARRAY_ALIGNMENT_REQUIRED")
    if np.isnan(xx).all(0).any() or np.isnan(cx).all(0).any():raise ValueError("FULL_STOCK_PAST_FEATURE_MEAN_UNAVAILABLE")
    from scripts.research.a2.training.selector_sufficiency_estimators import date_weights
    return h,mu,y,xx,cx,date_weights(h.signal_date)


def _observed_retained_gate(module,nonlinear,mu,context,y,w,seed,state):
    """Instrument the existing Gate.fit; preserve its network and update loop.

    Only this new profile uses a date-weighted target RMS. The original method
    and all legacy callers stay unchanged. Every callback precedes its actual
    scaler/statistical/model operation; no reservation emits an operation.
    """
    import inspect,textwrap
    source=textwrap.dedent(inspect.getsource(module.Gate.fit))
    edits={
        "self.scaler=StandardScaler().fit(context,sample_weight=weights)":
            "_state('META_SCALER','StandardScaler.fit'); self.scaler=StandardScaler().fit(context,sample_weight=weights)",
        "scale=max(float(np.sqrt(np.mean(y*y))),1e-6)":
            "_state('META_TARGET_SCALE','weighted_target_RMS'); scale=max(float(np.sqrt(np.average(y*y,weights=weights))),1e-6)",
        "for _ in range(10):": "_state('META_MODEL','retained_Gate_10_epoch_fit')\n    for _ in range(10):"}
    for old,new in edits.items():
        if source.count(old)!=1:raise ValueError("RETAINED_GATE_SOURCE_INTERFACE_CHANGED")
        source=source.replace(old,new)
    # Missing context coordinates mean its fitted past mean, not a new channel.
    source=source.replace("self.scaler.transform(context)","np.nan_to_num(self.scaler.transform(context),nan=0.0)")
    namespace=dict(module.Gate.fit.__globals__,SEED=seed,_state=state)
    exec(compile(source,inspect.getsourcefile(module.Gate.fit),"exec"),namespace)
    gate=module.Gate(nonlinear);namespace["fit"](gate,mu,context,y,w)
    return gate


def fit_full_stock_fusion(module,method,frame,cutoff,base32,context,*,expected_full_day_uids,on_state=None,seed=None):
    """Full genuine-OOF six-member new profile; no sampler or hidden outer refit.

    on_state receives one event per actually entered META_MODEL/META_SCALER/
    META_TARGET_SCALE operation. Stochastic methods average all three seeds.
    """
    if method not in FULL_STOCK_METHODS:raise ValueError("FULL_STOCK_FUSION_METHOD_NOT_FROZEN")
    h,mu,y,xx,cx,w=_full_stock_oof(frame,cutoff,base32,context,expected_full_day_uids)
    if method in FULL_STOCK_STOCHASTIC and seed is None:
        fits=[fit_full_stock_fusion(module,method,h,cutoff,xx,cx,expected_full_day_uids=expected_full_day_uids,on_state=on_state,seed=s) for s in FULL_STOCK_SEEDS]
        return FullStockFusion("seed_ensemble",models=[a[0] for a in fits],seeds=FULL_STOCK_SEEDS),dict(method=method,seed_policy=list(FULL_STOCK_SEEDS),events=[e for _,r in fits for e in r["events"]],rows=len(h),members=list(FULL_STOCK_MEMBERS))
    seed=FULL_STOCK_SEEDS[0] if seed is None else seed
    if seed not in (FULL_STOCK_SEEDS if method in FULL_STOCK_STOCHASTIC else FULL_STOCK_SEEDS[:1]):raise ValueError("FULL_STOCK_SEED_NOT_FROZEN")
    year=pd.Timestamp(cutoff).year;events=[]
    def state(kind,operation):
        suffix=f"|{seed}" if method in FULL_STOCK_STOCHASTIC else ""
        event=dict(kind=kind,node_id=f"{kind}|{method}|{year}{suffix}",method=method,year=year,seed=seed,operation=operation,actual_operation_entered=True)
        if on_state is not None:on_state(event)
        events.append(event)
    from scipy.optimize import minimize
    from sklearn.preprocessing import StandardScaler
    def scaled(source):
        state("META_SCALER","StandardScaler.fit");scaler=StandardScaler().fit(source,sample_weight=w)
        return scaler,np.nan_to_num(scaler.transform(source),nan=0.0)
    if method in ("equal","median"):
        result=FullStockFusion("native",module.Fusion(method,list(FULL_STOCK_MEMBERS)))
    elif method=="nnls":
        state("META_MODEL","scipy.optimize.nnls");root=np.sqrt(w);coef,_=nnls(mu*root[:,None],y*root)
        result=FullStockFusion("linear",LinearFusion(method,list(FULL_STOCK_MEMBERS),coef))
    elif method=="simplex":
        state("META_TARGET_SCALE","weighted_target_RMS");scale=max(float(np.sqrt(np.average(y*y,weights=w))),1e-6);x=mu/scale;target=y/scale
        state("META_MODEL","scipy.optimize.minimize_SLSQP")
        solved=minimize(lambda a:float(np.average((x@a-target)**2,weights=w)),np.full(6,1/6),
            jac=lambda a:2*x.T@(w*(x@a-target))/w.sum(),method="SLSQP",bounds=[(0.,1.)]*6,
            constraints=[dict(type="eq",fun=lambda a:a.sum()-1,jac=lambda a:np.ones(6))],options=dict(maxiter=500,ftol=1e-10))
        if not solved.success:raise RuntimeError("FULL_STOCK_SIMPLEX_NOT_CONVERGED_NO_RETRY")
        result=FullStockFusion("linear",LinearFusion(method,list(FULL_STOCK_MEMBERS),solved.x))
    elif method in ("linear_gate","mlp_gate"):
        gate=_observed_retained_gate(module,method=="mlp_gate",mu,cx,y,w,seed,state);result=FullStockFusion("gate",gate)
    else:
        residual=method in ("ridge_then_hgb","hgb_then_ridge");index=0 if method=="ridge_then_hgb" else 1
        source=xx if residual else mu;scaler,x=scaled(source)
        target=y-mu[:,index] if residual else y
        if method in ("ridge_stack","hgb_then_ridge"):model=module.Ridge(alpha=100.)
        elif method=="elastic_stack":model=module.ElasticNet(alpha=1e-5,l1_ratio=.35,max_iter=2500,tol=1e-5,random_state=FULL_STOCK_SEEDS[0])
        elif method in ("hgb_stack","ridge_then_hgb"):model=module.tree()
        else:model=module.MLPRegressor(hidden_layer_sizes=(32,),max_iter=10,batch_size=512,learning_rate_init=.001,alpha=.0001,random_state=seed,early_stopping=False)
        state("META_MODEL","residual_genuine_OOF_stage2_fit" if residual else "full_OOF_meta_estimator_fit")
        model.fit(x,target,sample_weight=w)
        result=FullStockFusion("residual" if residual else "stack",model,scaler,index)
    receipt=dict(method=method,members=list(FULL_STOCK_MEMBERS),events=events,rows=len(h),dates=h.signal_date.nunique(),
        cutoff=str(pd.Timestamp(cutoff)),max_label_end=str(h.label_end_date.max()),source_kind="MODEL_OOF",source_capacity="MID",
        date_weights="N/(D*N_t)",sampling="NONE",seed=seed,scientific_retry=0,
        residual_source="TRUE_PAST_OOF_mu" if method in ("ridge_then_hgb","hgb_then_ridge") else None,
        model_fit_count=sum(e["kind"]=="META_MODEL" for e in events),scaler_fit_count=sum(e["kind"]=="META_SCALER" for e in events),target_scale_count=sum(e["kind"]=="META_TARGET_SCALE" for e in events))
    return result,receipt


def predict_full_stock_fusion(fitted,mu,base32,context):
    members=np.asarray(mu,float);xx=np.asarray(base32,float);cx=np.asarray(context,float)
    if members.ndim!=2 or members.shape[1]!=6 or not np.isfinite(members).all() or xx.shape!=(len(members),32) or cx.shape!=(len(members),5) or np.isinf(xx).any() or np.isinf(cx).any():raise ValueError("FULL_STOCK_FORECAST_ALL_SIX_AND32_REQUIRED")
    if fitted.kind=="seed_ensemble":
        if fitted.seeds!=FULL_STOCK_SEEDS or len(fitted.models)!=3:raise ValueError("FULL_STOCK_ALL_THREE_META_SEEDS_REQUIRED")
        value=np.mean([predict_full_stock_fusion(f,members,xx,cx) for f in fitted.models],axis=0)
    elif fitted.kind in ("native","linear"):value=fitted.model.predict(members,cx)
    elif fitted.kind=="gate":
        # Gate.predict uses its fitted scaler; fill missing original coordinates
        # with that past mean before calling its retained prediction method.
        value=fitted.model.predict(members,np.where(np.isnan(cx),fitted.model.scaler.mean_,cx))
    elif fitted.kind=="residual":value=members[:,fitted.base_index]+fitted.model.predict(np.nan_to_num(fitted.scaler.transform(xx),nan=0.0))
    elif fitted.kind=="stack":value=fitted.model.predict(fitted.scaler.transform(members))
    else:raise ValueError("FULL_STOCK_FUSION_ARTIFACT_REQUIRED")
    value=np.asarray(value,float)
    if value.shape!=(len(members),) or not np.isfinite(value).all():raise ValueError("FULL_STOCK_FINITE_COMPLETE_PREDICTIONS_REQUIRED")
    return value
