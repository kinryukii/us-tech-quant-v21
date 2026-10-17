"""Synthetic frozen objects only: no real model, price, label or 2026 result I/O."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.inference import frozen_a94_values as c

_ORIGINAL_LOAD = c.three._load_frozen_model


class FrozenScaler:
    def __init__(self):
        self.mean_ = np.array([.01] * 32)
        self.scale_ = np.array([2.] * 32)
    def transform(self, x):
        return (x - self.mean_) / self.scale_
    def fit(self, *a, **k):
        raise AssertionError("No scaler fitting")
    fit_transform = fit


class FrozenIsotonic:
    def __init__(self):
        self.X_thresholds_ = np.array([0., 1.])
        self.y_thresholds_ = np.array([.1, .2])
    def predict(self, scores):
        return np.interp(scores, self.X_thresholds_, self.y_thresholds_)
    def fit(self, *a, **k):
        raise AssertionError("No isotonic fitting")


class FrozenNative:
    def __init__(self, name, features):
        self.model_id = name
        self.features = list(features)
        self.scaler = FrozenScaler() if name in c.values.SCALED else None
    def raw_predict(self, x):
        if self.model_id == "hgb_q":
            return np.column_stack((x[:,0]+.03, x[:,0]-.01, x[:,0]+.01))
        if self.model_id == "ngboost":
            return np.column_stack((x[:,0], np.full(len(x), .9)))
        return x[:,0]
    def fit(self, *a, **k):
        raise AssertionError("No estimator fitting")


class FrozenFusion:
    def __init__(self, method):
        self.method = method
        self.seen = []
    def predict(self, x, state):
        self.seen.append((x.copy(), state.copy()))
        return x.mean(axis=1) + (state[:,0] if self.method == "gate_linear" else 0)
    def fit(self, *a, **k):
        raise AssertionError("No fusion fitting")


def ref(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def context(tmp_path, monkeypatch):
    features = tuple(c.values.feature_binding()["features"])
    frame = pd.DataFrame({name:[.01, .03, np.nan] for name in features})
    frame["signal_date"] = pd.to_datetime(["2026-01-05"] * 3)
    frame["ticker"] = ["S0", "S1", "S2"]
    frame["security_id"] = ["SID0", "SID1", None]
    frame["feature_available"] = [True, True, False]
    frame["input_present"] = [True, True, False]
    frame["feature_source"] = [next(iter(c.values.SOURCES))] * 3
    states = {}; objects = {}; old = dict(value_models=[], risk_models=[])
    manifest = ref(tmp_path / "input_manifest.json", dict(synthetic=True))
    model_loads = []
    def make(name, kind):
        folder = tmp_path / "models" / ("risk" if kind == "risk" else "fusion" if kind == "fusion" else "value") / name / "2025"
        model_ref = ref(folder / ("risk.joblib" if kind == "risk" else "model.joblib"), dict(fake_serialized_state=name))
        pins = {"input_manifest_sha256":manifest["sha256"], "input_reader_sha256":c.values.sha(c.values.READER_SOURCE)}
        if kind == "risk":
            pins.update(module_sha256=c.values.sha(c.risk_owner.__file__), joint_source_sha256=c.values.sha(c.risk.__file__),
                values_module_sha256=c.values.sha(c.values.__file__), garch_definition_source_sha256=c.values.sha(c.risk_owner.GARCH_PATH))
        elif kind == "fusion":
            pins.update(module_sha256=c.values.sha(c.fusion.__file__), native_source_sha256=c.values.sha(c.fusion.NATIVE),
                native_common_sha256=c.values.sha(c.fusion.COMMON), value_module_sha256=c.values.sha(c.values.__file__))
        else:
            pins.update(module_sha256=c.values.sha(c.values.__file__), native_source_sha256=c.values.sha(c.values.NATIVE))
        tup = dict(cutoff_exclusive="2025-01-01", source_pins=pins,
            feature_binding=c.values.feature_binding(), training_signal_and_label_maturity_exclusive="2024-10-07",
            calibration_label_maturity_exclusive="2025-01-01")
        receipt = dict(status="FITTED" if kind == "risk" else "TRAINED", year=2025,
            model_id=name, model_path=model_ref["path"], model_sha256=model_ref["sha256"],
            scientific_feature_pit_qualified=True, scientific_target_qualified=True,
            train_label_maturity_max="2024-10-04", calibration_label_maturity_max="2024-12-31", dependency_paths=[])
        if kind == "risk":
            dates = pd.bdate_range("2024-10-02", "2024-12-31").difference(pd.to_datetime(["2024-11-28", "2024-12-25"]))
            assert len(dates) == 63
            iso = [d.isoformat() for d in dates]
            tup.update(annual_static=True, window_sessions=63, return_horizon_sessions=1,
                return_unit=c.risk_owner.UNIT, horizon_rule="IID_5_X_STATIC_DAILY_COV",
                input_lineage=dict(dates=iso, assets=["S0", "S1"]))
            receipt.update(method_id=name, fitted_dates=iso, scientific_return_proxy_qualified=True)
            model = c.risk.RiskBundle(name,"FITTED",("S0","S1"),tuple(iso),estimated_assets=("S0","S1"),
                covariance=np.array([[.01,.002],[.002,.04]]), fallback_variance=.025,
                fitted_state=dict(return_horizon_sessions=1,return_unit=c.risk_owner.UNIT), specification=dict(fit_cutoff="2025-01-01"))
        elif kind == "fusion":
            tup["expert_oof_pins"] = [dict(year=2024, synthetic=True)]
            model = c.fusion.FusionFit(FrozenFusion(name), .07, receipt, {}, tmp_path)
        else:
            cal = dict(model_id=name,kind="point",offset=.02,sigma=.08)
            if name == "xgb_rank":
                cal.update(kind="isotonic",isotonic=FrozenIsotonic())
            model = c.values.ValueFit(FrozenNative(name,features),cal,receipt)
        receipt["reuse_tuple"] = tup
        receipt["reuse_tuple_sha256"] = c.values.digest(tup)
        receipt_ref = ref(folder / "fit_receipt.json", receipt)
        objects[model_ref["path"]] = model
        key = ("old_risk:"+name if kind == "risk" else "old_value:fusion::"+name if kind == "fusion" else "fusion_expert:lgb" if name == "lgb" else "old_value:"+name)
        states[key] = dict(model_ref=model_ref,receipt_ref=receipt_ref)
        if name != "lgb":
            old["risk_models" if kind == "risk" else "value_models"].append(dict(
                **({"risk_id":name} if kind=="risk" else {"model_id":"fusion::"+name if kind=="fusion" else name}),metadata=deepcopy(receipt)))
        return key
    for name in ("hgb","ridge","extra","hgb_q","huber","mlp","ngboost","xgb","xgb_rank","lgb"):
        make(name,"value")
    for method in ("equal","convex","stack_ridge","gate_linear"):
        make(method,"fusion")
    for method in ("DIAG","SCOV","OAS","LW","CONSTANT_CORR","PCA","FA","FUNDAMENTAL","EWMA","GARCH","GJR_GARCH","COV_ENSEMBLE"):
        make(method,"risk")
    old_ref = ref(tmp_path / "old_states.json", old)
    source_ref = ref(tmp_path / "qualified_source.json",dict(synthetic=True))
    qual = dict(full_pit32_pool=dict(origin="ORIGINAL_24_MANAGER_FULL_PIT32_INFERENCE_POOL",
        source_ref=source_ref,feature_order_sha256=c.values.digest(list(features)),
        sessions={"2026-01-05":c.pool_session_commitment(frame,features)}))
    qual_ref = ref(tmp_path / "qualification.json",qual)
    prov = dict(source_qualification_ref=qual_ref,source_refs=dict(action_inputs=source_ref))
    auth = c.admission.ValidatedDescriptiveAuthority(c.profile.TASK,"SYNTHETIC",pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06"),pd.Timestamp("2026-10-07T18:42:01.905856Z"),pd.Timestamp("2023-01-01"),
        ("SYNTHETIC_PATH",),json.dumps(prov),c.admission._SEAL,("SYNTHETIC_PATH",))
    contract = dict(state_refs=states,metadata_refs=dict(old_states=old_ref),
        raw_selector_binding=dict(ordered_32_features=list(features)))
    monkeypatch.setattr(c.profile,"_roots",lambda:(tmp_path.resolve(),))
    monkeypatch.setattr(c.profile,"frozen_profile_contract",lambda:deepcopy(contract))
    monkeypatch.setattr(c.values,"_native",lambda *args:None)
    def state_features(day,x):
        assert set(day.ticker)=={"S0","S1"}
        return day.groupby("signal_date")[["ret_20d","realized_vol_20d","price_vs_ma20","ret_1d"]].transform("mean").to_numpy()
    monkeypatch.setattr(c.fusion,"_native",lambda *args:SimpleNamespace(state_features=state_features))
    monkeypatch.setattr(c.fusion,"frozen_contract",lambda run,method,year:(run,{},
        dict(expert_oof=[dict(year=2024,synthetic=True)]),objects[states["old_value:fusion::"+method]["model_ref"]["path"]].receipt["reuse_tuple"]["source_pins"]))
    def load(path,objective):
        model_loads.append(str(path));return objects[str(path)]
    monkeypatch.setattr(c.three,"_load_frozen_model",load)
    loader = c.FrozenStateLoader(auth)
    return SimpleNamespace(loader=loader,frame=frame,pool=c.bind_pool(loader,frame),states=states,objects=objects,
        loads=model_loads,auth=auth,features=features,contract=contract,qualification=qual,qual_path=Path(qual_ref["path"]))


@pytest.mark.parametrize("name",["hgb","ridge","extra","hgb_q","huber","mlp","ngboost","xgb","xgb_rank","lgb"])
def test_original_transform_calibration_diagnostics_sigma_and_keys(context,name):
    key = "fusion_expert:lgb" if name=="lgb" else "old_value:"+name
    state = context.loader.load(key)
    before = deepcopy(state.model.calibration)
    out = c.predict_value(state,context.pool).frame
    assert out.ticker.tolist()==["S0","S1","S2"]
    assert out.prediction_qualified.tolist()==[True,True,False]
    assert out.value_sigma.iloc[:2].tolist()==[.08,.08] and pd.isna(out.prediction.iloc[2])
    assert out.year.eq(2025).all() and out.evaluation_year.eq(2026).all()
    assert out.prediction_role.eq("FROZEN_FORWARD_INFERENCE").all()
    if name=="xgb_rank":
        assert np.allclose(out.prediction.iloc[:2],[.101,.103])
        assert np.array_equal(state.model.calibration["isotonic"].X_thresholds_,before["isotonic"].X_thresholds_)
    elif name=="hgb_q":
        assert np.allclose(out.prediction.iloc[:2],[.04,.06])
        assert out.q10.iloc[0] < out.q90.iloc[0] and out.raw_q10.iloc[0] > out.raw_q50.iloc[0]
    else:
        assert np.allclose(out.prediction.iloc[:2],[.02,.03] if name in c.values.SCALED else [.03,.05])
    if name=="ngboost":assert out.native_sigma.iloc[:2].eq(.9).all()
    assert len(context.loads)==1


@pytest.mark.parametrize("method",["equal","convex","stack_ridge","gate_linear"])
def test_fusion_uses_original_three_experts_complete_surface_and_fixed_sigma(context,method):
    experts={n:c.predict_value(context.loader.load("fusion_expert:lgb" if n=="lgb" else "old_value:"+n),context.pool) for n in ("ridge","hgb","lgb")}
    state=context.loader.load("old_value:fusion::"+method)
    out=c.predict_fusion(state,context.pool,experts).frame
    assert out.ticker.tolist()==["S0","S1","S2"] and out.prediction_qualified.tolist()==[True,True,False]
    assert out.value_sigma.iloc[:2].eq(.07).all() and pd.isna(out.prediction.iloc[2])
    assert state.model.receipt["year"]==2025
    if method=="gate_linear":assert np.allclose(state.model.native.seen[0][1][:,0],[.02,.02])
    with pytest.raises(ValueError,match="THREE_ORIGINAL_EXPERTS"):
        c.predict_fusion(state,context.pool,{"ridge":experts["ridge"]})


@pytest.mark.parametrize("change",["subset","feature","order","label","2027","unqualified"])
def test_bad_pool_rejected_before_numeric_prediction(context,change):
    frame=context.frame.copy()
    if change=="subset":frame=frame.iloc[:1]
    elif change=="feature":frame.loc[0,"ret_1d"]+=1
    elif change=="order":frame=frame.iloc[::-1]
    elif change=="label":frame["y_open5"]=1.
    elif change=="2027":frame["signal_date"]=pd.Timestamp("2027-01-04")
    else:
        context.qual_path.write_text(json.dumps({}),encoding="utf-8")
    with pytest.raises(ValueError):c.bind_pool(context.loader,frame)
    assert context.loads==[]


def test_bound_pool_mutation_and_handle_replacement_rejected(context):
    state=context.loader.load("old_value:hgb")
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):
        c.predict_value(replace(state,key="old_value:ridge"),context.pool)
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):
        c.predict_value(replace(state,authority=replace(state.authority,end=pd.Timestamp("2027-01-04"))),context.pool)
    context.pool.frame.loc[0,"ret_20d"]+=1
    with pytest.raises(ValueError,match="POOL_MUTATED"):c.predict_value(state,context.pool)


def test_unknown_replaced_model_and_maturity_fail_before_deserialize(context):
    with pytest.raises(ValueError,match="UNKNOWN_OR_UNBOUND"):context.loader.load("old_value:unknown")
    replaced=deepcopy(context.states["old_value:hgb"]["model_ref"]);replaced["sha256"]="f"*64
    with pytest.raises(ValueError,match="REPLACED_STATE_REFERENCE"):context.loader.load("old_value:hgb",model_ref=replaced)
    assert context.loads==[]
    receipt=deepcopy(context.loader._metadata["old_value:hgb"]);receipt["calibration_label_maturity_max"]="2025-01-02"
    with pytest.raises(ValueError,match="MATURITY"):c._maturity(receipt,"value")


@pytest.mark.parametrize("method",["DIAG","SCOV","OAS","LW","CONSTANT_CORR","PCA","FA","FUNDAMENTAL","EWMA","GARCH","GJR_GARCH","COV_ENSEMBLE"])
def test_static_risk_exact_original_unknown_behavior_and_single_horizon_conversion(context,method):
    state=context.loader.load("old_risk:"+method)
    matrix,meta=c.risk_matrix_frozen(state,["S1","UNKNOWN","S0"])
    assert np.allclose(matrix,[[.2,0,.01],[0,.125,0],[.01,0,.05]])
    assert meta["unknown_assets"]==["UNKNOWN"] and meta["strategy_eligibility_upgraded"] is False
    assert meta["return_horizon_sessions"]==1 and meta["return_horizon_sessions_output"]==5
    with pytest.raises(ValueError):c.risk_matrix_frozen(state,[])
    with pytest.raises(ValueError):c.risk_matrix_frozen(state,["S0","S0"])


def test_risk_provider_preserves_lowercase_diag_and_rejects_missing_method(context):
    state=context.loader.load("old_risk:OAS")
    provider,metadata=c.risk_provider({"OAS":state},pd.to_datetime(["2026-01-05"]),np.array([[.2,.3]]))
    assert np.allclose(provider(0,np.array([0,1]),["S0","S1"],"diag20_reference"),np.diag([.04,.09]))
    assert np.allclose(provider(0,np.array([0]),["S0","S1"],"OAS"),[[.05]])
    assert len(metadata)==1
    with pytest.raises(ValueError,match="NO_SUBSTITUTE"):provider(0,np.array([0]),["S0","S1"],"PCA")


def test_no_fit_or_real_input_reader_and_legacy_guards_untouched():
    import ast
    tree=ast.parse(Path(c.__file__).read_text(encoding="utf-8"))
    called={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not called & {"fit","fit_transform","partial_fit","train_annual","fit_fusion","read_parquet","download"}
    assert "INFERENCE_OUTSIDE_AUTHORIZED_ANNUAL_PRE2026_SCOPE" in Path(c.values.__file__).read_text(encoding="utf-8")
    assert "FUSION_INFERENCE_YEAR" in Path(c.fusion.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("field",["model","model_ref_json","receipt_ref_json","receipt_json"])
def test_state_handle_cannot_be_replaced_while_preserving_private_stamp(context,field):
    state=context.loader.load("old_value:hgb")
    changed=object() if field=="model" else "{}"
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):
        c.predict_value(replace(state,**{field:changed}),context.pool)


def test_mutated_expert_forward_output_rejected_instead_of_relabelled_as_frozen(context):
    experts={n:c.predict_value(context.loader.load("fusion_expert:lgb" if n=="lgb" else "old_value:"+n),context.pool) for n in ("ridge","hgb","lgb")}
    state=context.loader.load("old_value:fusion::gate_linear")
    experts["hgb"].frame.loc[0,"prediction"]+=1
    with pytest.raises(ValueError,match="EXPERT_FORWARD_PACKET"):
        c.predict_fusion(state,context.pool,experts)


def test_source_hash_failure_stops_before_deserialization(context,monkeypatch):
    monkeypatch.setattr(c.values,"sha",lambda path:"0"*64)
    with pytest.raises(ValueError,match="SOURCE_CHANGED"):
        context.loader.load("old_value:hgb")
    assert context.loads==[]


@pytest.mark.parametrize("name", ["hgb", "ridge", "extra", "hgb_q", "huber", "mlp", "ngboost", "xgb", "xgb_rank", "lgb"])
@pytest.mark.parametrize("already_bound", [False, True])
def test_all_valuefit_states_use_exact_legacy_alias_and_restore(context, monkeypatch, name, already_bound):
    import sys
    main = sys.modules["__main__"]
    if already_bound:
        monkeypatch.setattr(main, "ValueFit", c.values.ValueFit, raising=False)
    else:
        monkeypatch.delattr(main, "ValueFit", raising=False)
    monkeypatch.setattr(c.three, "_load_frozen_model", _ORIGINAL_LOAD)
    def load_only(path):
        assert main.ValueFit is c.values.ValueFit
        return context.objects[str(path)]
    monkeypatch.setattr(c.three.joblib, "load", load_only)
    key = "fusion_expert:lgb" if name == "lgb" else "old_value:" + name
    assert context.loader.load(key).model is context.objects[context.states[key]["model_ref"]["path"]]
    if already_bound:
        assert main.ValueFit is c.values.ValueFit
    else:
        assert not hasattr(main, "ValueFit")


@pytest.mark.parametrize("name", ["hgb", "lgb"])
def test_non_ngboost_valuefit_namespace_conflict_rejects_before_load(context, monkeypatch, name):
    import sys
    main = sys.modules["__main__"]; conflicting = object()
    monkeypatch.setattr(main, "ValueFit", conflicting, raising=False)
    monkeypatch.setattr(c.three, "_load_frozen_model", _ORIGINAL_LOAD)
    monkeypatch.setattr(c.three.joblib, "load", lambda *a: pytest.fail("conflicting namespace loaded"))
    key = "fusion_expert:lgb" if name == "lgb" else "old_value:" + name
    with pytest.raises(ValueError, match="NAMESPACE_CONFLICT"):
        context.loader.load(key)
    assert main.ValueFit is conflicting


@pytest.mark.parametrize("name", ["hgb", "lgb"])
@pytest.mark.parametrize("already_bound", [False, True])
def test_non_ngboost_valuefit_namespace_restores_after_error(context, monkeypatch, name, already_bound):
    import sys
    main = sys.modules["__main__"]
    if already_bound:
        monkeypatch.setattr(main, "ValueFit", c.values.ValueFit, raising=False)
    else:
        monkeypatch.delattr(main, "ValueFit", raising=False)
    monkeypatch.setattr(c.three, "_load_frozen_model", _ORIGINAL_LOAD)
    def fail(path):
        assert main.ValueFit is c.values.ValueFit
        raise RuntimeError("SYNTHETIC_LEGACY_LOAD_FAILED")
    monkeypatch.setattr(c.three.joblib, "load", fail)
    key = "fusion_expert:lgb" if name == "lgb" else "old_value:" + name
    with pytest.raises(RuntimeError, match="SYNTHETIC_LEGACY_LOAD_FAILED"):
        context.loader.load(key)
    if already_bound:
        assert main.ValueFit is c.values.ValueFit
    else:
        assert not hasattr(main, "ValueFit")


@pytest.mark.parametrize("bad",[None,"origin","manifest","rule","variant"])
def test_consensus_pool_requires_own_source_and_exact_membership_contract(context,tmp_path,bad):
    from dataclasses import replace
    contract=deepcopy(context.contract)
    source=ref(tmp_path/"consensus_source.json",dict(synthetic=True))
    rule=dict(selection_rule="MANAGER_COUNT_WEIGHT_SUM",rank_column="consensus_rank",size=100)
    contract["raw_selector_binding"].update(universe_variant="CONSENSUS100",
        application_pool_origin="CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL",
        universe_source_ref=source,original_universe_contract=rule)
    q=deepcopy(context.qualification);proof=q["full_pit32_pool"]
    proof.update(origin="CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL",universe_variant="CONSENSUS100",
        universe_source_ref=source,universe_contract_sha256=c.values.digest(rule))
    if bad=="origin":proof["origin"]="ORIGINAL_24_MANAGER_FULL_PIT32_INFERENCE_POOL"
    elif bad=="manifest":proof["universe_source_ref"]={**source,"sha256":"0"*64}
    elif bad=="rule":proof["universe_contract_sha256"]=c.values.digest({**rule,"size":101})
    elif bad=="variant":proof["universe_variant"]="ORIGINAL24"
    prov=json.loads(context.auth.provenance_json)
    prov["source_qualification_ref"]=ref(tmp_path/"consensus_qualification.json",q)
    auth=replace(context.auth,task_id=c.profile.ALL_TASK,provenance_json=json.dumps(prov))
    loader=SimpleNamespace(authority=auth,_check=lambda:contract)
    if bad:
        with pytest.raises(ValueError):c.bind_pool(loader,context.frame)
    else:
        bound=c.bind_pool(loader,context.frame)
        pd.testing.assert_frame_equal(bound.frame,context.frame)
