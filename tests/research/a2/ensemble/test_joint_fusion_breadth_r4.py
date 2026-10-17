"""Only synthetic R4 genuine-earlier-OOF/catalog/physical callback tests."""
import copy
from collections import Counter
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.ensemble import joint_fusion_breadth_r4 as f
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash,StateCache,StateBudget

MEMBERS=("ridge","hgb","xgb","lgb","extra_trees")
def history(role="GENUINE_ANNUAL_MODEL_OOF"):
    rng=np.random.default_rng(420);dates=pd.date_range("2022-01-01",periods=12,freq="MS",tz="UTC")+pd.Timedelta(days=2)
    h=pd.DataFrame({"signal_date":np.repeat(dates,50),"ticker":[str(i) for i in range(50)]*12})
    h["security_uid"]="UID:"+h.ticker;h["asset_epoch"]="stable"
    h["label_end_date"]=h.signal_date+pd.Timedelta(days=5);h["label_mature_date"]=h.label_end_date
    h["fit_eligible"]=True
    for m in MEMBERS:
        h[m+"__mu"]=rng.normal(0,.1,len(h))
        h[m+"__source_cutoff"]=pd.Timestamp("2022-01-01",tz="UTC")
        h[m+"__source_label_mature_max"]=pd.Timestamp("2021-12-31",tz="UTC")
        h[m+"__source_sha256"]="b"*64;h[m+"__producer_role"]=role
    h["y_open5"]=h[[m+"__mu" for m in MEMBERS]].mean(axis=1)+rng.normal(0,.01,len(h))
    for c in f.CONTEXT:h[c]=rng.normal(size=len(h))
    h.attrs=dict(source_inputs_sha256="a"*64,target_binding_sha256="c"*64,
        qualified_oof_contract_sha256="d"*64,target_coordinate=f.UNIT)
    return h

class Spy:
    def __init__(self,fail=None):
        self.calls=[];self.cache={};self.failed=set();self.fail=fail
    def __call__(self,kind,name,inputs,compute,parameters=None):
        key=content_hash(dict(kind=kind,name=name,inputs=inputs,parameters=parameters))
        if key in self.failed:raise ValueError("FAILED_KEY_NO_RETRY")
        if key not in self.cache:
            self.calls.append((kind,name,key))
            try:
                if self.fail and self.fail(name):raise ValueError("synthetic failed scientific slot")
                self.cache[key]=compute()
            except Exception:
                self.failed.add(key);raise
        return copy.deepcopy(self.cache[key])
    @property
    def counts(self):return Counter(c[0] for c in self.calls)

@pytest.mark.parametrize("method",f.METHODS)
def test_eleven_catalog_families_complete_same_frozen_packet(method):
    h=history();spy=Spy();result=f.fit_meta(h,"2023-01-01T00:00:00Z",method,MEMBERS,spy)
    assert result["qualified"] is True
    assert result["members"]==list(MEMBERS) and result["seeds"]==list(f.SEEDS)
    assert result["prior_OOF_error_RMS"]>0
    assert result["strict_PIT_promotion_eligible"] is False
    x=h[[m+"__mu" for m in MEMBERS]].iloc[:3].to_numpy()
    assert np.isfinite(result["model"].predict(x,h[list(f.CONTEXT)].iloc[:3].to_numpy())).all()

def test_actual_all_catalog_physical_shared_counts_match_recipe():
    h=history();spy=Spy()
    for method in f.METHODS:
        assert f.fit_meta(h,"2023-01-01T00:00:00Z",method,MEMBERS,spy)["qualified"]
    assert spy.counts==Counter(f.physical_count_recipe(years=1,return_calibration_slots=0,hgb_stochastic_phases=0)["planned_per_kind"])
    assert sum(spy.counts.values())==45
    count=len(spy.calls)
    for method in f.METHODS:f.fit_meta(h,"2023-01-01T00:00:00Z",method,MEMBERS,spy)
    assert len(spy.calls)==count

def test_static_methods_have_one_uncertainty_state_and_no_predictor_fit():
    for method in ("equal","median","fixed_weighted"):
        spy=Spy();f.fit_meta(history(),"2023-01-01T00:00:00Z",method,MEMBERS,spy)
        assert spy.counts=={"bridge_calibration":1}

def test_count_257_and_300_cap_inputs_are_explicit_not_unknown_exact_total():
    recipe=f.physical_count_recipe()
    assert recipe["planned_learned_units"]==257
    assert f.physical_count_recipe(scale_proxy_slots=43)["planned_learned_units"]==300
    assert f.physical_count_recipe(seeds=(20260928,))["planned_learned_units"]==209
    with pytest.raises(f.FusionBreadthBlocked):f.physical_count_recipe(seeds=(1,))
    with pytest.raises(f.FusionBreadthBlocked):f.physical_count_recipe(years=True)

@pytest.mark.parametrize("change",[
    "native_future","native_training_prediction","UID_unknown","source_pin_unknown",
    "missing_member","nonfinite_member","target_changed","naive_clock","post2025",
    "unmatured_source","duplicate_key","input_pin_missing"])
def test_no_missing_member_shrink_or_false_genuine_oof(change):
    h=history()
    if change=="native_future":h.loc[0,"ridge__source_cutoff"]=pd.Timestamp("2024-01-01",tz="UTC")
    if change=="native_training_prediction":h.loc[0,"ridge__producer_role"]="IN_TRAINING_PREDICTION"
    if change=="UID_unknown":h.loc[0,"security_uid"]="UNKNOWN"
    if change=="source_pin_unknown":h.loc[0,"ridge__source_sha256"]="bad"
    if change=="missing_member":h=h.drop(columns="ridge__mu")
    if change=="nonfinite_member":h.loc[0,"ridge__mu"]=np.nan
    if change=="target_changed":h.attrs["target_coordinate"]="MEAN_ER_3D_5D_10D_20D"
    if change=="naive_clock":h["signal_date"]=h.signal_date.dt.tz_localize(None)
    if change=="post2025":h.loc[0,"label_mature_date"]=pd.Timestamp("2026-01-01",tz="UTC")
    if change=="unmatured_source":h.loc[0,"ridge__source_label_mature_max"]=h.loc[0,"ridge__source_cutoff"]
    if change=="duplicate_key":h=pd.concat([h,h.iloc[:1]],ignore_index=True)
    if change=="input_pin_missing":h.attrs.pop("source_inputs_sha256")
    spy=Spy()
    with pytest.raises(f.FusionBreadthBlocked):f.fit_meta(h,"2023-01-01T00:00:00Z","equal",MEMBERS,spy)
    assert not spy.calls

def test_no_fitted_value_uncertainty_and_probe_label_purge():
    h=history()
    for m in MEMBERS:h[m+"__mu"]=0.
    boundary=sorted(h.signal_date.unique())[6]
    h["y_open5"]=h.signal_date.ge(boundary).astype(float)
    result=f.fit_meta(h,"2023-01-01T00:00:00Z","ridge_stack",MEMBERS,Spy())
    assert result["prior_OOF_error_RMS"]==pytest.approx(1.)
    assert pd.Timestamp(result["probe_maturity_max"])<boundary
    assert result["model"].predict(np.zeros((2,5)),np.zeros((2,5))).tolist()==pytest.approx([.5,.5])

def test_seed_failure_does_not_drop_failed_seed_or_stop_other_legal_slots():
    spy=Spy(fail=lambda name:"mlp_stack" in name and name.endswith("20260929"))
    result=f.fit_meta(history(),"2023-01-01T00:00:00Z","mlp_stack",MEMBERS,spy)
    assert result["qualified"] is False and result["prior_OOF_error_RMS"] is None
    assert spy.counts=={"scaler":2,"model_fit":6}
    assert len(spy.failed)==2
    count=len(spy.calls)
    f.fit_meta(history(),"2023-01-01T00:00:00Z","mlp_stack",MEMBERS,spy)
    assert len(spy.calls)==count

def test_return_calibration_has_five_states_and_genuine_probe_rms():
    h=history(role="GENUINE_ANNUAL_META_OOF")
    for m in MEMBERS:h[m+"__mu"]=0.
    boundary=sorted(h.signal_date.unique())[6];h["y_open5"]=h.signal_date.ge(boundary).astype(float)
    spy=Spy();result=f.fit_return_calibration(h,"2023-01-01T00:00:00Z",MEMBERS,["ridge__mu"],spy,name="equal")
    assert spy.counts=={"scaler":2,"bridge_calibration":3}
    assert result["prior_OOF_error_RMS"]==pytest.approx(1.) and result["in_fit_RMS_estimated"] is False
    assert result["model"].predict(result["scaler"].transform([[0.]])).item()==pytest.approx(.5)

def test_calibration_will_not_relabel_base_oof_as_meta_oof():
    with pytest.raises(f.FusionBreadthBlocked,match="PRODUCER"):
        f.fit_return_calibration(history(),"2023-01-01T00:00:00Z",MEMBERS,["ridge__mu"],Spy(),name="equal")

def test_native_scale_proxy_uses_true_raw_oof_errors_and_is_not_coverage():
    h=history();h["native_scale"]=.5;h["y_open5"]=h["ridge__mu"]+1.
    spy=Spy();result=f.fit_native_scale_proxy(h,"2023-01-01T00:00:00Z",MEMBERS,"ridge__mu","native_scale",spy,name="distribution")
    assert result["multiplier"]==pytest.approx(2.) and spy.counts=={"bridge_calibration":1}
    assert result["certified_coverage"] is False
    h.loc[0,"native_scale"]=0
    with pytest.raises(f.FusionBreadthBlocked):f.fit_native_scale_proxy(h,"2023-01-01T00:00:00Z",MEMBERS,"ridge__mu","native_scale",Spy(),name="distribution")

def test_numeric_scaler_state_can_use_existing_r2_cache():
    h=history();budget=StateBudget()
    cache=StateCache(budget,source_identity="synthetic",cutoff="2023-01-01T00:00:00Z",
        assets=MEMBERS,return_coordinate=f.UNIT,horizon=5,identity_epoch="synthetic")
    state=f._scaler(h,["ridge__mu"],"full",cache.learn)
    assert isinstance(state,f.ScalerState) and budget.learned_total==1
    again=f._scaler(h,["ridge__mu"],"full",cache.learn)
    assert budget.learned_total==1 and np.array_equal(state.mean,again.mean)

def test_hgb_no_manufactured_deterministic_seed_fits():
    assert f._phase_seeds("hgb_stack",200000,f.SEEDS)==(20260928,)
    assert f._phase_seeds("hgb_stack",200001,f.SEEDS)==f.SEEDS
    spy=Spy();result=f.fit_meta(history(),"2023-01-01T00:00:00Z","hgb_stack",MEMBERS,spy)
    assert result["actual_phase_seeds"]=={"probe":[20260928],"full":[20260928]}
    assert spy.counts=={"scaler":2,"model_fit":2,"bridge_calibration":1}
    assert f.physical_count_recipe(hgb_stochastic_phases=0)["planned_learned_units"]==245


def test_original_native_identity_preserved_without_invented_uid_or_epoch():
    h=history().drop(columns=["security_uid","asset_epoch"])
    h["security_id"]="SEC:123";h["security_id_type"]="SEC_CIK"
    h["cusip"]=None;h["active_13f_quarter"]="2022Q1"
    h["quarter_universe_fingerprint"]="e"*64
    fitted=f.fit_meta(h,"2023-01-01T00:00:00Z","equal",MEMBERS,Spy())
    assert fitted["qualified"] is True
    inputs=f._frame_inputs(h,[m+"__mu" for m in MEMBERS])[0]
    assert set(f.IDENTITY).issubset(inputs.columns)
    assert "security_uid" not in inputs and "asset_epoch" not in inputs
    h["security_id"]="UNKNOWN:123"
    with pytest.raises(f.FusionBreadthBlocked):f.fit_meta(h,"2023-01-01T00:00:00Z","equal",MEMBERS,Spy())


def test_fixed_weight_law_is_original_literal_and_distinct_from_equal():
    h=history();result=f.fit_meta(h,"2023-01-01T00:00:00Z","fixed_weighted",MEMBERS,Spy())
    x=np.array([[0.,1.,2.,3.,4.]])
    assert result["model"].predict(x,np.zeros((1,5)))[0]==pytest.approx(1.5)
    assert result["model"].coefficients.tolist()==[.30,.25,.20,.15,.10]

def test_zero_scale_estimate_retains_failed_reservation_not_successful_state():
    h=history();h["native_scale"]=1.;h[MEMBERS[0]+"__mu"]=h.y_open5
    spy=Spy()
    with pytest.raises(f.FusionBreadthBlocked):f.fit_native_scale_proxy(h,
        "2023-01-01T00:00:00Z",MEMBERS,MEMBERS[0]+"__mu","native_scale",spy,name="zero")
    assert spy.counts=={"bridge_calibration":1} and len(spy.failed)==1
