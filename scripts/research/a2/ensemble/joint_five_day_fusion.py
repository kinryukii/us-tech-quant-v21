"""B full-row five-day fusion over genuinely earlier bridged native OOF.

The C pure Fusion/Gate handlers are source-bound and reused through an AST
projection. Only their obsolete population sample hook is replaced with all
caller-proven rows. M43/44 instead reuse B's existing annual primary raw OOF
and learn the residual on canonical 32 features, not on meta member means.
"""
from __future__ import annotations
import ast
import hashlib
import warnings
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd
from dataclasses import dataclass
from scipy.optimize import minimize
from sklearn.linear_model import Ridge,ElasticNet
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from scripts.research.a2.data.joint_input_binding import FEATURES
from scripts.research.a2.training import selector_cooperation as cooperation

SEED=20260928
MEMBERS=("ridge","hgb","xgb_rank","logistic","cat_uncertainty")
METHODS=cooperation.METHODS[:11]
CONTEXT=cooperation.CONTEXT
UNIT="FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN"
_SOURCE=Path(__file__).resolve().parents[1]/"retained/a2_pto_full_compat_20260928_r2/calibration_fusion.py"
_SOURCE_SHA="8cdc72d6ae359f72844ef6079d0fd20d58203f4001635b64f1b490be7cc72724"
_COOP=Path(cooperation.__file__).resolve()
_COOP_SHA="888590fc3a4d385d6cac67df232bfb5920683bc19371d2fa1578405d2c557379"
SPEC={"methods":list(METHODS),"fixed_members":list(MEMBERS),"fixed_weights":[.30,.25,.20,.15,.10],
      "context":list(CONTEXT),"target":UNIT,"sampling":"NONE_ALL_ELIGIBLE_PRIOR_OOF",
      "target_clip":None,"seed":SEED,"uncertainty":"earlier chronological date-half probe; second-half RMS; full-prior refit for future",
      "residual":"existing B annual primary raw OOF + canonical32 secondary; later calibration on genuine composite OOF",
      "C_handler_sha256":_SOURCE_SHA,"C_cooperation_sha256":_COOP_SHA}

class FusionDependencyError(ValueError):pass

def _source_guard():
    for path,expected in ((_SOURCE,_SOURCE_SHA),(_COOP,_COOP_SHA)):
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise FusionDependencyError("FROZEN_FUSION_HANDLER_CHANGED:"+str(path))

@lru_cache(maxsize=1)
def _shared_handler():
    _source_guard()
    from scripts.research.a2.evaluation.joint_sequential_training import bind_runtime
    bind_runtime()
    import torch
    from torch import nn
    tree=ast.parse(_SOURCE.read_text(encoding="utf-8-sig"))
    names={"tree","GateNetwork","Gate","Fusion","fit_fusion"}
    nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
    if {n.name for n in nodes}!=names:raise FusionDependencyError("MISSING_SHARED_FUSION_HANDLER")
    source_spec=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="SPEC" for t in n.targets))
    shared_spec=ast.literal_eval(source_spec.value)
    namespace={"__name__":__name__,"np":np,"pd":pd,"dataclass":dataclass,"minimize":minimize,
        "Ridge":Ridge,"ElasticNet":ElasticNet,"HistGradientBoostingRegressor":HistGradientBoostingRegressor,
        "MLPRegressor":MLPRegressor,"StandardScaler":StandardScaler,"torch":torch,"nn":nn,
        "warnings":warnings,"SEED":SEED,"SPEC":shared_spec,
        "sample":lambda frame:frame.sort_values(["signal_date","ticker"]).reset_index(drop=True),
        "date_weights":date_weights}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(_SOURCE),"exec"),namespace)
    # Canonical module globals allow joblib to restore these source-projected
    # shared classes in a fresh Python process via __getattr__ below.
    for name in ("Fusion","Gate","GateNetwork"):globals()[name]=namespace[name]
    return namespace["fit_fusion"]

def __getattr__(name):
    if name in ("Fusion","Gate","GateNetwork"):
        _shared_handler();return globals()[name]
    raise AttributeError(name)

def date_weights(frame_or_dates):
    dates=frame_or_dates.signal_date if isinstance(frame_or_dates,pd.DataFrame) else pd.Series(frame_or_dates)
    counts=dates.map(dates.value_counts()).to_numpy(float);weight=1/counts
    return weight/weight.mean()

def _truth_guard(frame,cutoff):
    cut=pd.Timestamp(cutoff)
    if cut>pd.Timestamp("2026-01-01"):raise ValueError("FUSION_FIT_CUTOFF_AFTER_PRE2026")
    need={"signal_date","ticker","y_open5","label_mature_date","label_end_date","fit_eligible"}
    if not need.issubset(frame):raise FusionDependencyError("MISSING_B_FIVE_DAY_TRUTH")
    if frame.duplicated(["signal_date","ticker"]).any():raise ValueError("DUPLICATE_FUSION_KEY")
    h=frame.copy()
    for c in ("signal_date","label_mature_date","label_end_date"):h[c]=pd.to_datetime(h[c])
    if any(h[c].ge(pd.Timestamp("2026-01-01")).any() for c in ("signal_date","label_mature_date","label_end_date")):
        raise ValueError("FUSION_CONTENT_CONTAINS_TEST_BOUNDARY")
    mask=h.fit_eligible.eq(True)&h.signal_date.lt(cut)&h.label_mature_date.lt(cut)&h.label_end_date.lt(cut)&np.isfinite(h.y_open5)
    if "trade_eligible" in h:mask&=h.trade_eligible.eq(True)
    return h.loc[mask].copy(),cut

def prepare_fusion_training(history,cutoff):
    h,cut=_truth_guard(history,cutoff)
    if h.empty:raise FusionDependencyError("NO_PRIOR_MATURE_FUSION_OOF")
    for name in MEMBERS:
        required=[name+"__mu",name+"__bridge_cutoff",name+"__bridge_label_mature_max",name+"__source_cutoff"]
        if any(c not in h for c in required):raise FusionDependencyError("MISSING_BRIDGED_NATIVE_MEMBER:"+name)
        cc=pd.to_datetime(h[name+"__bridge_cutoff"]);mature=pd.to_datetime(h[name+"__bridge_label_mature_max"])
        source=pd.to_datetime(h[name+"__source_cutoff"])
        if (cc.isna().any() or mature.isna().any() or source.isna().any()
            or cc.gt(h.signal_date).any() or source.gt(h.signal_date).any() or mature.ge(cc).any()):
            raise ValueError("BRIDGED_META_OOF_CLOCK_VIOLATION:"+name)
        if not np.isfinite(h[name+"__mu"].to_numpy(float)).all():
            raise FusionDependencyError("UNAVAILABLE_MEMBER_DO_NOT_SHRINK:"+name)
    if any(c not in h for c in CONTEXT) or not np.isfinite(h[list(CONTEXT)].to_numpy(float)).all():
        raise FusionDependencyError("UNAVAILABLE_PIT_CONTEXT")
    h["y_next_open"]=h.y_open5
    return h,cut

def _estimated_states(method):
    if method in ("equal","median","fixed_weighted"):return []
    if method=="nnls":return ["weighted_NNLS"]
    if method=="simplex":return ["target_RMS_scale","simplex_weights"]
    if method in ("linear_gate","mlp_gate"):return ["context_StandardScaler","target_RMS_scale","Gate_network"]
    return ["member_StandardScaler",method+"_model"]

def fusion_fit_units(method):
    if method not in METHODS:raise FusionDependencyError("UNREGISTERED_META_METHOD")
    return 2*len(_estimated_states(method))+1

def _fit_shared(method,frame,cutoff):
    _source_guard()
    if method in ("fixed_weighted","nnls"):
        coefficients=np.asarray(SPEC["fixed_weights"],float)
        if method=="nnls":
            weight=np.sqrt(date_weights(frame));columns=[m+"__mu" for m in MEMBERS]
            coefficients,_=cooperation.nnls(frame[columns].to_numpy(float)*weight[:,None],frame.y_open5.to_numpy(float)*weight)
        return cooperation.LinearFusion(method,list(MEMBERS),coefficients),{"rows":len(frame),"coefficients":coefficients.tolist()}
    return _shared_handler()(method,list(MEMBERS),frame,pd.Timestamp(cutoff))

def fit_five_day_fusion(history,cutoff,method):
    if method not in METHODS:raise FusionDependencyError("UNREGISTERED_META_METHOD")
    h,cut=prepare_fusion_training(history,cutoff);states=_estimated_states(method)
    probe_receipt=None;boundary=None
    columns=[m+"__mu" for m in MEMBERS]
    with threadpool_limits(limits=2):
        if not states:
            obj,receipt=_fit_shared(method,h,cut)
            held=h;pred=obj.predict(held[columns].to_numpy(float),held[list(CONTEXT)].to_numpy(float))
        else:
            dates=np.sort(h.signal_date.unique())
            if len(dates)<2:raise FusionDependencyError("CHRONOLOGICAL_META_HISTORY_TOO_SHORT")
            boundary=pd.Timestamp(dates[len(dates)//2])
            first=h.loc[h.signal_date.lt(boundary)&h.label_mature_date.lt(boundary)&h.label_end_date.lt(boundary)]
            held=h.loc[h.signal_date.ge(boundary)]
            if len(first)<100 or len(held)<100:raise FusionDependencyError("CHRONOLOGICAL_META_PROBE_TOO_SMALL")
            probe,probe_receipt=_fit_shared(method,first,boundary)
            pred=probe.predict(held[columns].to_numpy(float),held[list(CONTEXT)].to_numpy(float))
            obj,receipt=_fit_shared(method,h,cut)
    residual=held.y_open5.to_numpy(float)-pred
    if not np.isfinite(residual).all():raise FusionDependencyError("INVALID_CHRONOLOGICAL_META_ERROR")
    rms=max(float(np.sqrt(np.average(residual**2,weights=date_weights(held)))),1e-6)
    report={"method":method,"fit_rows":len(h),"fit_dates":int(h.signal_date.nunique()),
        "cutoff":str(cut),"max_label_maturity":str(h.label_mature_date.max()),
        "estimated_states":["probe_"+s for s in states]+["full_"+s for s in states]+["prior_OOF_error_RMS"],
        "fit_units":fusion_fit_units(method),"probe_boundary":str(boundary) if boundary is not None else None,
        "probe_max_label_mature":str(first.label_mature_date.max()) if states else None,
        "uncertainty_rows":len(held),"uncertainty_source":"chronological second-half true OOF error" if states else "prior true OOF static fusion error",
        "probe_receipt":probe_receipt,"full_receipt":receipt,"unit":UNIT,"spec":SPEC,
        "sampling":"NONE_ALL_ELIGIBLE_ROWS","retained_sampling_hook_overridden":True,"native_base_refits":0,"test2026_rows":0,
        "neural_optimizer_updates":10*(int(np.ceil(len(h)/512))+int(np.ceil(len(first)/512))) if method in ("linear_gate","mlp_gate") else 0}
    return {"method":method,"model":obj,"residual_rms":rms,"cutoff":str(cut),"receipt":report}

def apply_five_day_fusion(frame,bundle):
    if pd.to_datetime(frame.signal_date).lt(pd.Timestamp(bundle["cutoff"])).any():
        raise ValueError("META_APPLIED_TO_ITS_TRAINING_HISTORY")
    if pd.to_datetime(frame.signal_date).ge(pd.Timestamp("2027-01-01")).any():raise ValueError("META_APPLY_OUTSIDE_EVALUATION_BOUNDARY")
    _source_guard();columns=[m+"__mu" for m in MEMBERS]
    required=[*columns,*CONTEXT]
    if any(c not in frame for c in required):raise FusionDependencyError("MISSING_META_APPLICATION_MEMBER")
    available=np.isfinite(frame[required].to_numpy(float)).all(axis=1)
    for name in MEMBERS:
        clocks=[name+"__bridge_cutoff",name+"__bridge_label_mature_max",name+"__source_cutoff"]
        if any(c not in frame for c in clocks):raise FusionDependencyError("MISSING_META_APPLICATION_LINEAGE:"+name)
        cc,mature,source=[pd.to_datetime(frame[c]) for c in clocks]
        valid=cc.notna()&mature.notna()&source.notna()&cc.le(pd.to_datetime(frame.signal_date))&source.le(pd.to_datetime(frame.signal_date))&mature.lt(cc)
        if (available&~valid).any():raise ValueError("META_APPLICATION_FUTURE_MEMBER:"+name)
        available&=valid
    out=frame.copy();out["mu"]=np.nan;out["sigma"]=np.nan
    if available.any():
        out.loc[available,"mu"]=bundle["model"].predict(frame.loc[available,columns].to_numpy(float),frame.loc[available,list(CONTEXT)].to_numpy(float))
        out.loc[available,"sigma"]=bundle["residual_rms"]
    out["meta_available"]=available;out["meta_cutoff"]=pd.Timestamp(bundle["cutoff"]);out["expected_return_coordinate"]=UNIT
    return out

def prepare_residual_training(history,cutoff,method):
    if method not in ("ridge_then_hgb","hgb_then_ridge"):raise FusionDependencyError("UNREGISTERED_RESIDUAL_METHOD")
    h,cut=_truth_guard(history,cutoff);primary="Ridge" if method=="ridge_then_hgb" else "HGB"
    if any(c not in h for c in (primary+"_raw","source_fit_cutoff",*FEATURES)):
        raise FusionDependencyError("MISSING_B_PRIMARY_RAW_OOF_AND_CANONICAL32")
    source=pd.to_datetime(h.source_fit_cutoff)
    if source.isna().any() or source.gt(h.signal_date).any():raise ValueError("PRIMARY_RAW_OOF_CLOCK_VIOLATION")
    if h.empty or not np.isfinite(h[[primary+"_raw",*FEATURES]].to_numpy(float)).all():
        raise FusionDependencyError("UNAVAILABLE_B_PRIMARY_FEATURE_RESIDUAL_INPUT")
    h["residual_target"]=h.y_open5-h[primary+"_raw"]
    return h,cut,primary

def fit_oof_residual(history,cutoff,method):
    h,cut,primary=prepare_residual_training(history,cutoff,method)
    x=h[list(FEATURES)].to_numpy(float);y=h.residual_target.to_numpy(float);w=date_weights(h)
    scaler=StandardScaler().fit(x,sample_weight=w)
    model=HistGradientBoostingRegressor(max_iter=64,max_depth=3,max_leaf_nodes=15,min_samples_leaf=100,
        learning_rate=.05,l2_regularization=1.,early_stopping=False,random_state=SEED) if method=="ridge_then_hgb" else Ridge(alpha=100.)
    with threadpool_limits(limits=2):model.fit(scaler.transform(x),y,sample_weight=w)
    return {"method":method,"primary":primary,"scaler":scaler,"secondary":model,"cutoff":str(cut),
        "receipt":{"fit_rows":len(h),"max_label_maturity":str(h.label_mature_date.max()),
            "fit_units":2,"sampling":"NONE_ALL_ELIGIBLE_PRIOR_PRIMARY_OOF_ROWS","primary_refit_units":0,
            "primary_source":"existing B annual raw OOF","secondary_features":list(FEATURES),
            "target":"y_open5 - primary annual raw OOF","sigma":None,"requires_later_true_composite_OOF_calibration":True}}

def apply_oof_residual(frame,bundle):
    if pd.to_datetime(frame.signal_date).lt(pd.Timestamp(bundle["cutoff"])).any():raise ValueError("RESIDUAL_APPLIED_TO_TRAINING_HISTORY")
    if pd.to_datetime(frame.signal_date).ge(pd.Timestamp("2027-01-01")).any():raise ValueError("RESIDUAL_APPLY_OUTSIDE_EVALUATION_BOUNDARY")
    columns=[bundle["primary"]+"_raw",*FEATURES]
    if any(c not in frame for c in columns):raise FusionDependencyError("MISSING_PRIMARY_APPLICATION_OR32")
    available=np.isfinite(frame[columns].to_numpy(float)).all(axis=1)
    out=frame.copy();out[bundle["method"]+"__raw"]=np.nan
    if available.any():
        out.loc[available,bundle["method"]+"__raw"]=frame.loc[available,columns[0]].to_numpy(float)+bundle["secondary"].predict(bundle["scaler"].transform(frame.loc[available,list(FEATURES)].to_numpy(float)))
    out["residual_available"]=available;out["source_cutoff"]=pd.Timestamp(bundle["cutoff"])
    out["source_label_mature_max"]=pd.Timestamp(bundle["receipt"]["max_label_maturity"])
    return out
