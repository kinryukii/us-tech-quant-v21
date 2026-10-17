"""Synthetic NEW37 states/inputs only; no actual model or test-data reads."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler
from scripts.research.a2.inference import frozen_a94_actions as c


class Estimator:
    classes_ = np.array([0, 1])
    def __init__(self, point=.02):
        self.point = point; self.seen = []
    def predict(self, x):
        self.seen.append(x.copy()); return np.full(len(x), self.point)
    def predict_proba(self, x):
        self.seen.append(x.copy()); return np.tile([.4, .6], (len(x), 1))
    def pred_dist(self, x):
        loc = np.full(len(x), self.point); sd = np.full(len(x), .01)
        return SimpleNamespace(loc=loc, scale=sd, params=dict(loc=loc, scale=sd), ppf=lambda q: loc + sd * (q-.5))
    def fit(self, *a, **k):
        raise AssertionError("NO_FIT")


def ref(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def scaler(width):
    obj = StandardScaler()
    obj.mean_, obj.scale_, obj.var_ = np.full(width, .01), np.full(width, 2.), np.full(width, 4.)
    obj.n_features_in_, obj.n_samples_seen_ = width, 100
    return obj


R6_IDS = ["R6_"+o.upper()+"_"+l.upper() for o in ("buy","hold","replace","duration","distribution") for l in ("linear","tree","neural")]
FAMILIES = ("ridge", "elasticnet", "logistic", "hgb", "xgb", "lgb", "catboost", "extratrees", "mlp", "resnet", "hgb_quantile", "ngboost", "gaussian_mlp", "gaussian_mlp4h")
R10_IDS = ["R10_DIRECT_MEAN4_"+f.upper() for f in FAMILIES] + ["R10_SEQUENCE_"+f.upper()+"_L5_MID" for f in ("tcn","gru","lstm")] + ["R10_HAZARD_"+f.upper()+"_LOW" for f in ("logistic","hgb","xgb","catboost","mlp")]


@pytest.fixture
def context(tmp_path, monkeypatch):
    pins = c.r10.source_pins()
    source_ref = ref(tmp_path/"source.json", dict(synthetic=True))
    manifest = ref(tmp_path/"r6"/"input_manifest.json",dict(synthetic=True))
    r6contract = ref(tmp_path/"r6_contract.json", dict(specification_sha256="a"*64,input_manifest_sha256=manifest["sha256"]))
    r10contract = ref(tmp_path/"r10_contract.json", dict(model_specifications=dict(source_pins=pins)))
    rows, scales, candidates, states, objects = [], [], [], {}, {}
    def add(row, features, model, kind):
        root = tmp_path/"r6" if kind=="r6" else tmp_path/"r10"
        folder = root/"models"/("decision" if kind=="r6" else "mechanism")/row["slot_id"]
        mp = ref(folder/"model.joblib",dict(synthetic=row["slot_id"]))
        row.update(status="TRAINED",year=2025,model_path=mp["path"],model_sha256=mp["sha256"])
        if kind=="r6":
            tup = dict(slot={k:row[k] for k in ("stage","objective","learner","year","slot_id")},seed=c.r6.SEED,
                feature_order=list(features),calibration_start="2024-10-07",training_signal_max="2024-09-24",
                training_maturity_max="2024-10-02",contract_sha256="a"*64,input_manifest_sha256=manifest["sha256"])
        else:
            tup = {k:row[k] for k in ("slot_id","family","capacity","seed","objective","year")}
            tup.update(features=list(features),design_sha256=r10contract["sha256"],x_shape=[20,*model.metadata["feature_shape"]] if kind=="r10" else [100,len(features)])
            if kind=="r10":tup.update(group=row["group"],cutoff_exclusive="2025-01-01")
            row.update(feature_order=list(features),feature_count=len(features))
        receipt = dict(status="TRAINED",year=2025,seed=row.get("seed"),objective=row["objective"],
            learner=row.get("learner"),model_path=mp["path"],model_sha256=mp["sha256"],scientific_tuple=tup,
            scientific_tuple_sha256=c.base.values.digest(tup))
        rp = ref(folder/"fit_receipt.json", receipt);row["receipt_ref"]=rp
        objects[mp["path"]]=model
        states[("new_scaler:" if kind=="scaler" else "new_model:")+row["slot_id"]]=dict(model_ref=mp,receipt_ref=rp)
        (scales if kind=="scaler" else rows).append(row)
    for objective in ("buy","hold","replace","duration","distribution"):
        for learner in ("linear","tree","neural"):
            columns = c.decision.PAIR if objective=="replace" else c.decision.SINGLE
            features=tuple(columns)+tuple(x+"__missing" for x in columns)
            meta=dict(source_sha256=c.r6.source_sha256(),native_source_sha256=c.r6.NATIVE_SHA256,
                specifications=c.r6.specifications(),seed=c.r6.SEED,input_features=list(features),
                sklearn_version=importlib.metadata.version("scikit-learn"),ngboost_version="SYNTHETIC",torch_version="SYNTHETIC")
            est=[Estimator(.03),Estimator(-.01),Estimator(.01)] if objective=="distribution" and learner=="linear" else Estimator()
            model=c.r6.Model(objective,learner,est,None if learner=="tree" else scaler(len(features)),features,(),meta)
            slot=f"{objective}_{learner}_2025"
            add(dict(slot_id=slot,stage="R6",objective=objective,learner=learner,seed=c.r6.SEED),features,model,"r6")
            candidates.append(dict(candidate_id="R6_"+objective.upper()+"_"+learner.upper(),model_ids=[slot],external_scaler_ids=[]))
    groups=[("ACTION_VALUE_ENTRY_HMEAN_2025","ENTRY",FAMILIES,"LOW"),
        ("ACTION_VALUE_INCUMBENT_HMEAN_2025","INCUMBENT",FAMILIES,"LOW"),
        ("HAZARD_SEQUENCE_JOINTSEQ_L5_2025","JOINT_SEQUENCE",("tcn","gru","lstm"),"MID"),
        ("HAZARD_SEQUENCE_HAZARD_H5_2025","HAZARD",("logistic","hgb","xgb","catboost","mlp"),"LOW")]
    bindings={}
    for prefix, group, families, capacity in groups:
        raw=c.role_features("R10:"+group)
        names=raw if group=="JOINT_SEQUENCE" else tuple(raw)+tuple("missing_"+f for f in raw)
        sid=prefix+"_SCALER"
        add(dict(slot_id=sid,family="SCALER",capacity="SHARED",seed=None,objective="PREPROCESSOR"),names,scaler(len(names)),"scaler")
        for family in families:
            members=[]
            for seed in c.mechanism.seed_list(family):
                slot=f"{prefix}_{family}_{capacity}_{seed}";members.append(slot)
                node=dict(family=c.r10.canonical_family(family),capacity=capacity,seed=seed,objective="HAZARD" if group=="HAZARD" else "ADVANTAGE" if group=="JOINT_SEQUENCE" else "advantage",lookback=5)
                est={.1:Estimator(.03),.5:Estimator(-.01),.9:Estimator(.01)} if family=="hgb_quantile" else Estimator(.01+.01*(seed-c.r10.SEEDS[0]))
                meta=dict(source_pins=pins,feature_shape=[5,len(names)] if group=="JOINT_SEQUENCE" else [len(names)],classifier=family=="logistic" or group=="HAZARD")
                add(dict(slot_id=slot,group=group,objective=node["objective"],family=family,capacity=capacity,seed=seed),names,c.r10.MechanismModel(node,est,meta,()),"r10")
            bindings[group,family]=members
    for family in FAMILIES:
        model_ids=bindings["ENTRY",family]+bindings["INCUMBENT",family]
        candidates.append(dict(candidate_id="R10_DIRECT_MEAN4_"+family.upper(),model_ids=model_ids,external_scaler_ids=["ACTION_VALUE_ENTRY_HMEAN_2025_SCALER","ACTION_VALUE_INCUMBENT_HMEAN_2025_SCALER"] if c.r10.canonical_family(family) in c.r10.SCALED_FAMILIES else []))
    for family in ("tcn","gru","lstm"):
        candidates.append(dict(candidate_id="R10_SEQUENCE_"+family.upper()+"_L5_MID",model_ids=bindings["JOINT_SEQUENCE",family],external_scaler_ids=["HAZARD_SEQUENCE_JOINTSEQ_L5_2025_SCALER"]))
    for family in ("logistic","hgb","xgb","catboost","mlp"):
        candidates.append(dict(candidate_id="R10_HAZARD_"+family.upper()+"_LOW",model_ids=bindings["HAZARD",family],external_scaler_ids=["HAZARD_SEQUENCE_HAZARD_H5_2025_SCALER"] if c.r10.canonical_family(family) in c.r10.SCALED_FAMILIES else []))
    assert len(rows)==81 and len(scales)==4 and len(candidates)==37
    newer=ref(tmp_path/"new_states.json",dict(model_states=rows,external_scaler_states=scales,candidate_rows=candidates,
        authority_refs=dict(R6_contract=r6contract,R10_contract=r10contract)))
    old=ref(tmp_path/"old_states.json",dict(value_models=[],risk_models=[]))
    qual={"action_feature_inputs":{},"action_packet_coverage":dict(future_unmatured_probe_outcomes_read=0,
        outcome_columns_in_model_features=0,new_fit_count=0,matured_probe_state=dict(source_ref=source_ref,key_sha256="e"*64,
        causal_rule="previous_probe_mature_date < current_signal_date",prior_probe_mature_before_current_decision=True,
        as_of_utc="2026-01-06T12:00:00Z"))}
    qr=ref(tmp_path/"qualification.json",qual)
    prov=dict(source_qualification_ref=qr,source_refs=dict(action_inputs=source_ref))
    auth=c.base.admission.ValidatedDescriptiveAuthority(c.base.profile.TASK,"SYNTHETIC",pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06"),pd.Timestamp("2026-10-07T18:42:01.905856Z"),pd.Timestamp("2023-01-01"),
        tuple(r["candidate_id"] for r in candidates),json.dumps(prov),c.base.admission._SEAL,tuple(r["candidate_id"] for r in candidates))
    contract=dict(state_refs=states,metadata_refs=dict(old_states=old,new_states=newer),raw_selector_binding=dict(ordered_32_features=list(c.base.values.feature_binding()["features"])))
    monkeypatch.setattr(c.base.profile,"_roots",lambda:(tmp_path.resolve(),))
    monkeypatch.setattr(c.base.profile,"frozen_profile_contract",lambda:deepcopy(contract))
    monkeypatch.setattr(c.joblib,"load",lambda path:objects[str(path)])
    native=SimpleNamespace(predict_torch=lambda est,x:np.tile([.2,-2.],(len(x),1)))
    monkeypatch.setattr(c.base.values,"_native",lambda *a:native)
    monkeypatch.setattr(c.r6,"_native",lambda *a:native)
    original_import=c.r6.importlib.import_module
    monkeypatch.setattr(c.r6.importlib,"import_module",lambda name,*a:SimpleNamespace(__version__="SYNTHETIC") if name in ("ngboost","torch") else original_import(name,*a))
    monkeypatch.setattr(c.r10,"_torch_bind",lambda node,*a:(None,lambda est,x:np.tile([.2,-2.] if node["family"]=="GaussianMLP" else [.1,-2.]*4 if node["family"]=="GaussianMLP4H" else [.2],(len(x),1)),None))
    monkeypatch.setattr(StandardScaler, "fit", lambda *a, **k: pytest.fail("NO_SCALER_REFIT"))
    monkeypatch.setattr(c.r6, "fit", lambda *a, **k: pytest.fail("NO_R6_REFIT"))
    monkeypatch.setattr(c.r10, "fit", lambda *a, **k: pytest.fail("NO_R10_REFIT"))
    loader=c.FrozenActionLoader(auth)
    def publish(role, *, empty=False, unavailable=False):
        features=c.role_features(role);n=0 if empty else 2
        frame=pd.DataFrame({name:np.full(n,.02) for name in features}) if role!="R10:JOINT_SEQUENCE" else pd.DataFrame(index=range(n))
        frame["signal_date"]=pd.to_datetime(["2026-01-05"]*n);frame["sample_id"]=["sample"+str(i) for i in range(n)]
        frame["ticker"]=["S"+str(i) for i in range(n)];frame["security_id"]=["SID"+str(i) for i in range(n)]
        frame["incumbent"]=["I"+str(i) for i in range(n)];frame["incumbent_sid"]=["ISID"+str(i) for i in range(n)]
        frame["entrant_ticker"]=["E"+str(i) for i in range(n)];frame["entrant_sid"]=["ESID"+str(i) for i in range(n)]
        frame["cohort_age_sessions"]=np.zeros(n);frame["proxy_entrant"]=np.ones(n,bool)
        if role in ("R10:INCUMBENT","R10:JOINT_SEQUENCE"):frame["action_type"]=np.arange(n,dtype=float)
        if n and role!="R10:JOINT_SEQUENCE":frame.loc[0,features[0]]=np.nan
        tensor=np.full((n,5,len(features)),.02) if role=="R10:JOINT_SEQUENCE" else None
        mask=np.ones(n,bool)
        if unavailable and n:mask[-1]=False
        qual["action_feature_inputs"][role]=dict(status="SOURCE_BOUND_COMPLETE_ORIGINAL_COMPUTED_STATE",source_ref=source_ref,
            new_fit_count=0,outcome_columns_in_model_features=0,computed_signal_dates=["2026-01-05"],
            prior_probe_mature_before_current_decision=True,commitment=c.input_commitment(frame,features,tensor,mask))
        qr.update(ref(Path(qr["path"]),qual));prov["source_qualification_ref"]=qr
        object.__setattr__(auth,"provenance_json",json.dumps(prov))
        return c.bind_action_input(loader,role,frame,tensor=tensor,supported=mask)
    return SimpleNamespace(loader=loader,publish=publish,objects=objects,states=states,qual=qual,qual_ref=qr,prov=prov,auth=auth)


def candidate_predictions(context, name, **input_options):
    predictions={}
    for slot in context.loader._candidates[name]["model_ids"]:
        h=context.loader.load("new_model:"+slot);row=c._state(h)
        if h.kind=="r6":
            single=c.predict_r6(h,context.publish("R6:"+row["objective"],**input_options))
            predictions[slot]=(single,c.predict_r6(h,context.publish("R6:distribution_pair",**input_options))) if row["objective"]=="distribution" else single
        else:
            value=context.publish("R10:"+row["group"],**input_options)
            suffix=f"_{row['family']}_{row['capacity']}_{row['seed']}"
            scaler=context.loader.load("new_scaler:"+slot[:-len(suffix)]+"_SCALER") if c.r10.canonical_family(row["family"]) in c.r10.SCALED_FAMILIES else None
            predictions[slot]=c.predict_r10(h,value,scaler=scaler)
    return predictions


@pytest.mark.parametrize("name",R6_IDS+R10_IDS)
def test_all37_exact81_members_original_encoder_native_scalers_and_decoders(context,name):
    predictions=candidate_predictions(context,name)
    perdate=c.decode_candidate(context.loader,name,predictions)
    proposals=[p for day in perdate.values() for p in day]
    assert proposals and all(p["local_resolver"] in ("R6","R10") for p in proposals)
    for item in predictions.values():
        for output in item if isinstance(item,tuple) else (item,):
            assert len(output.frame)==2 and output.frame.signal_date.eq(pd.Timestamp("2026-01-05")).all()
            c._output(output)
            assert json.loads(output.state.receipt_json)["year"]==2025


@pytest.mark.parametrize("name",["R10_DIRECT_MEAN4_RIDGE","R10_SEQUENCE_GRU_L5_MID","R10_HAZARD_MLP_LOW"])
def test_source_computed_empty_is_legal_but_missing_packet_is_not(context,name):
    predictions=candidate_predictions(context,name,empty=True)
    assert c.decode_candidate(context.loader,name,predictions)=={}
    with pytest.raises(ValueError,match="MEMBER_SET"):
        c.decode_candidate(context.loader,name,{})


def test_actual_native_quantile_rearrangement_is_not_relabelled_as_mean(context):
    output=next(iter(candidate_predictions(context,"R10_DIRECT_MEAN4_HGB_QUANTILE").values()))
    assert output.frame.q50.eq(.01).all() and "mean" not in output.frame


def test_exact_equal_seed_mean_keeps_all_original_members(context):
    predictions=candidate_predictions(context,"R10_DIRECT_MEAN4_CATBOOST")
    proposals=c.decode_candidate(context.loader,"R10_DIRECT_MEAN4_CATBOOST",predictions)[pd.Timestamp("2026-01-05")]
    assert proposals[0]["source_score"]==pytest.approx(.02)
    predictions.pop(next(iter(predictions)))
    with pytest.raises(ValueError,match="MEMBER_SET"):c.decode_candidate(context.loader,"R10_DIRECT_MEAN4_CATBOOST",predictions)


@pytest.mark.parametrize("field",["key","kind","authority","model","metadata_json","receipt_json","refs_json","features"])
def test_state_replacement_cannot_self_certify(context,field):
    h=context.loader.load("new_model:buy_tree_2025")
    value=object() if field in ("authority","model") else () if field=="features" else "REPLACED"
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):c._state(replace(h,**{field:value}))


def test_model_metadata_or_scaler_state_mutation_rejected(context):
    h=context.loader.load("new_model:buy_linear_2025");h.model.scaler.mean_[0]+=1
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):c._state(h)
    h=context.loader.load("new_model:hold_tree_2025");h.model.metadata["seed"]+=1
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):c._state(h)


def test_input_and_output_mutations_rejected(context):
    h=context.loader.load("new_model:buy_tree_2025");value=context.publish("R6:buy")
    output=c.predict_r6(h,value);output.frame.loc[0,"p_superior"]+=.1
    with pytest.raises(ValueError,match="OUTPUT_CHANGED"):c._output(output)
    value.frame.loc[0,"raw_score"]+=1
    with pytest.raises(ValueError,match="BOUND_INPUT_CHANGED"):c.predict_r6(h,value)


def test_unknown_replaced_model_references_stop_before_load(context,monkeypatch):
    monkeypatch.setattr(c.joblib,"load",lambda *a:pytest.fail("unauthorized model load"))
    with pytest.raises(ValueError,match="UNKNOWN_ACTION_STATE"):context.loader.load("new_model:UNKNOWN")
    h=context.states["new_model:buy_tree_2025"]["model_ref"]
    with pytest.raises(ValueError,match="REPLACED_ACTION_REFERENCE"):context.loader.load("new_model:buy_tree_2025",model_ref={**h,"sha256":"f"*64})


@pytest.mark.parametrize("defect",["missing","future_probe","model_outcome","unfit","noncausal"])
def test_missing_or_noncausal_producer_is_not_empty_action_success(context,defect):
    value=context.publish("R6:duration");q=deepcopy(context.qual)
    if defect=="missing":q["action_feature_inputs"].clear()
    if defect=="future_probe":q["action_packet_coverage"]["future_unmatured_probe_outcomes_read"]=1
    if defect=="model_outcome":q["action_feature_inputs"]["R6:duration"]["outcome_columns_in_model_features"]=1
    if defect=="unfit":q["action_feature_inputs"]["R6:duration"]["new_fit_count"]=1
    if defect=="noncausal":q["action_packet_coverage"]["matured_probe_state"]["prior_probe_mature_before_current_decision"]=False
    qr=ref(Path(context.qual_ref["path"]),q);context.prov["source_qualification_ref"]=qr
    object.__setattr__(context.auth,"provenance_json",json.dumps(context.prov))
    with pytest.raises(ValueError):c.bind_action_input(context.loader,"R6:duration",value.frame)


def test_2027_and_outcomes_forbidden(context):
    value=context.publish("R6:buy");frame=value.frame.copy();frame["signal_date"]=pd.Timestamp("2027-01-05")
    with pytest.raises(ValueError):c.bind_action_input(context.loader,"R6:buy",frame)
    frame=value.frame.copy();frame["y_open5"]=.1
    with pytest.raises(ValueError,match="OUTCOME"):c.bind_action_input(context.loader,"R6:buy",frame)


def test_source_code_has_no_fit_no_real_reader_and_original_guards_still_present():
    import ast
    tree=ast.parse(Path(c.__file__).read_text(encoding="utf-8"))
    called={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not called & {"fit","fit_transform","partial_fit","read_parquet","download","build_frames","build_samples","sequence_dataset"}
    assert "2026_LOCKED" in Path(c.mechanism.inputs.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("prefix",["ACTION_VALUE_ENTRY_HMEAN_2025", "ACTION_VALUE_INCUMBENT_HMEAN_2025", "HAZARD_SEQUENCE_JOINTSEQ_L5_2025", "HAZARD_SEQUENCE_HAZARD_H5_2025"])
def test_all_four_shared_scalers_are_frozen_and_handle_bound(context,prefix):
    state=context.loader.load("new_scaler:"+prefix+"_SCALER")
    before=(state.model.mean_.copy(),state.model.scale_.copy())
    c._state(state)
    assert np.array_equal(state.model.mean_,before[0]) and np.array_equal(state.model.scale_,before[1])
    state.model.scale_[0]+=1
    with pytest.raises(ValueError,match="HANDLE_CHANGED"):c._state(state)


def test_original_missing_flags_and_transform_order_are_preserved(context):
    h=context.loader.load("new_model:buy_linear_2025");value=context.publish("R6:buy")
    expected,_=c.decision.encode_features(value.frame,value.features)
    expected=h.model.scaler.transform(expected)
    c.predict_r6(h,value)
    assert np.array_equal(h.model.estimator.seen[-1],expected)
    slot="ACTION_VALUE_ENTRY_HMEAN_2025_ridge_LOW_20260928"
    h=context.loader.load("new_model:"+slot);value=context.publish("R10:ENTRY")
    shared=context.loader.load("new_scaler:ACTION_VALUE_ENTRY_HMEAN_2025_SCALER")
    expected,_=c.mechanism.encode(value.frame,value.features)
    expected=np.nan_to_num(shared.model.transform(expected),nan=0.)
    before=shared.model.mean_.copy()
    c.predict_r10(h,value,scaler=shared)
    assert np.array_equal(h.model.estimator.seen[-1],expected)
    assert np.array_equal(shared.model.mean_,before)


def test_unknown_sequence_stays_unknown_and_all_replacements_keep_sid(context):
    predictions=candidate_predictions(context,"R10_SEQUENCE_TCN_L5_MID",unavailable=True)
    assert all(pd.isna(p.frame["mean"].iloc[-1]) for p in predictions.values())
    proposals=c.decode_candidate(context.loader,"R10_SEQUENCE_TCN_L5_MID",predictions)[pd.Timestamp("2026-01-05")]
    assert proposals[-1]["decision"]=="REFERENCE"
    predictions=candidate_predictions(context,"R10_DIRECT_MEAN4_RIDGE")
    proposals=c.decode_candidate(context.loader,"R10_DIRECT_MEAN4_RIDGE",predictions)[pd.Timestamp("2026-01-05")]
    replacement=[p for p in proposals if p["kind"]=="REPLACE"]
    assert replacement and replacement[0]["entrant_security_id"]=="ESID1"
    assert [p["source_order"] for p in proposals]==list(range(len(proposals)))


def test_distribution_pair_orders_follow_single_orders(context):
    predictions=candidate_predictions(context,"R6_DISTRIBUTION_TREE")
    proposals=c.decode_candidate(context.loader,"R6_DISTRIBUTION_TREE",predictions)[pd.Timestamp("2026-01-05")]
    assert len(proposals)==4 and [p["source_order"] for p in proposals]==[0,1,2,3]


def test_wrong_shared_scaler_and_truncated_distribution_roles_rejected(context):
    slot="ACTION_VALUE_ENTRY_HMEAN_2025_ridge_LOW_20260928"
    h=context.loader.load("new_model:"+slot);value=context.publish("R10:ENTRY")
    wrong=context.loader.load("new_scaler:ACTION_VALUE_INCUMBENT_HMEAN_2025_SCALER")
    with pytest.raises(ValueError,match="SCALER_IDENTITY_CHANGED"):c.predict_r10(h,value,scaler=wrong)
    predictions=candidate_predictions(context,"R6_DISTRIBUTION_TREE")
    key=next(iter(predictions));predictions[key]=predictions[key][0]
    with pytest.raises(ValueError,match="ORIGINAL_ACTION_ROLES"):c.decode_candidate(context.loader,"R6_DISTRIBUTION_TREE",predictions)



def test_distribution_roles_have_original_order_even_if_caller_reverses_tuple(context):
    predictions=candidate_predictions(context,"R6_DISTRIBUTION_TREE")
    expected=c.decode_candidate(context.loader,"R6_DISTRIBUTION_TREE",predictions)
    slot=next(iter(predictions));predictions[slot]=tuple(reversed(predictions[slot]))
    assert c.decode_candidate(context.loader,"R6_DISTRIBUTION_TREE",predictions)==expected


def test_old57_only_scope_cannot_load_or_decode_new37(context,monkeypatch):
    old=replace(context.auth,allowed_path_ids=(*context.auth.allowed_path_ids,"OLD_ONLY"),runtime_policy_ids=("OLD_ONLY",))
    loader=c.FrozenActionLoader(old)
    monkeypatch.setattr(c.joblib,"load",lambda *a:pytest.fail("OLD57 scope deserialized NEW37 state"))
    with pytest.raises(ValueError,match="OUTSIDE_SCOPED_POLICY"):loader.load("new_model:buy_tree_2025")
    with pytest.raises(ValueError,match="RUNTIME_POLICY_VALIDATION"):c.decode_candidate(loader,"R6_BUY_TREE",{})


def test_scoped_candidate_state_closure_excludes_other_models_and_scalers(context,monkeypatch):
    narrow=replace(context.auth,runtime_policy_ids=("R6_BUY_TREE",))
    loader=c.FrozenActionLoader(narrow)
    assert loader.load("new_model:buy_tree_2025").kind=="r6"
    monkeypatch.setattr(c.joblib,"load",lambda *a:pytest.fail("outside candidate closure deserialized"))
    with pytest.raises(ValueError,match="OUTSIDE_SCOPED_POLICY"):loader.load("new_model:hold_tree_2025")
    with pytest.raises(ValueError,match="OUTSIDE_SCOPED_POLICY"):loader.load("new_scaler:ACTION_VALUE_ENTRY_HMEAN_2025_SCALER")
    with pytest.raises(ValueError,match="RUNTIME_POLICY_VALIDATION"):c.decode_candidate(loader,"R6_HOLD_TREE",{})


def test_shared_scaler_is_available_to_each_authorized_candidate_that_requires_it(context):
    for candidate in ("R10_DIRECT_MEAN4_RIDGE","R10_DIRECT_MEAN4_MLP"):
        scoped=replace(context.auth,runtime_policy_ids=(candidate,))
        loader=c.FrozenActionLoader(scoped)
        assert loader.load("new_scaler:ACTION_VALUE_ENTRY_HMEAN_2025_SCALER").kind=="scaler"


@pytest.mark.parametrize("role",["R6:buy","R6:hold","R6:replace","R6:duration","R6:distribution","R6:distribution_pair"])
def test_r6_rows_have_no_extra_support_mask_freedom(context,role):
    # Original build_samples excludes feature-unavailable rows before publication;
    # its marginal/classifier publisher has no post-prediction mask parameter.
    with pytest.raises(ValueError,match="ORIGINAL_SUPPORT_MASK_CHANGED"):
        context.publish(role,unavailable=True)



def test_forward_state_native_actions_controller_and_original_engine_are_connected(context, monkeypatch, tmp_path, record_property):
    # Reuse the state owner's synthetic history/probes. No actual2026 input exists.
    import importlib.util
    from scripts.research.a2.inference import frozen_a94_state as state
    from scripts.research.a2.evaluation import stateful_frozen_a94 as seam
    helper_path=Path(__file__).with_name("test_frozen_a94_state.py")
    spec=importlib.util.spec_from_file_location("_a94_state_synthetic_fixture",helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    paths=[Path(module.__file__) for module in (state,c,seam,c.decision,c.r6,c.mechanism,c.r10,c.packets,seam.replay)]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    record_property("helper_sha256_before",json.dumps(before,sort_keys=True))
    # The original resolver chooses among positive SELL/REPLACE actions. Give
    # the synthetic sequence estimator distinct signs instead of a tied vote;
    # the original model predictor, token scaler and decoder remain in charge.
    fixture_torch_bind=c.r10._torch_bind
    def sequence_estimator(node,*args):
        if node["family"] in ("TCN","GRU","LSTM"):
            return (None,lambda est,x:np.where(x[:,-1,-1]<0.,.2,-.2)[:,None],None)
        return fixture_torch_bind(node,*args)
    monkeypatch.setattr(c.r10,"_torch_bind",sequence_estimator)
    cal,pred=helper._history()
    fillers=[]
    for i in range(17):
        filler=pred.loc[pred.ticker.eq("A")].copy()
        filler["ticker"]="F%02d"%i;filler["security_id"]="SID_F%02d"%i
        filler["raw_a2_rank"]=i+4;fillers.append(filler)
    pred=pd.concat([pred,*fillers],ignore_index=True)
    pred.loc[pred.ticker.eq("D"),["is_raw_top20","new_buy_eligible"]]=False
    pred.loc[pred.ticker.eq("D"),"raw_a2_rank"]=21
    pred["raw_top20_set_complete"]=True
    pred["raw_a2_prediction"]=.1-pred.raw_a2_rank*.001
    tail=pred.loc[pred.signal_date.eq(cal[-1])].copy();tail["signal_date"]=pd.Timestamp("2026-01-06")
    pred=pd.concat([pred,tail],ignore_index=True);cal=cal.append(pd.DatetimeIndex(["2026-01-06"]))
    dates=pd.to_datetime(["2026-01-02","2026-01-05","2026-01-06"])
    proto=replace(context.auth,start=dates[0],end=dates[-1])
    r6probe,h5probe=helper._labels(pred,cal),helper._labels(pred,cal,True)
    action_ref=context.prov["source_refs"]["action_inputs"]
    computed=[]
    for day in dates:
        clock=day.tz_localize("America/New_York")+pd.Timedelta(hours=16)
        r6past=r6probe.loc[r6probe.label_mature_date.lt(day)&r6probe.observation_available_at.le(clock)]
        h5past=h5probe.loc[h5probe.label_mature_date.lt(day)&h5probe.observation_available_at.le(clock)]
        computed.append(state.build_current_state(proto,pred.loc[pred.signal_date.le(day)],cal[cal<=day],day,
            decision_as_of=clock,r6_probe_rows=r6past,native_h5_probe_rows=h5past,action_source_ref=action_ref))
    roles={role:pd.concat([item.role_frames[role] for item in computed],ignore_index=True) for role in computed[0].role_frames}
    tensor=np.concatenate([item.joint_sequence for item in computed],axis=0)
    sequence_mask=np.concatenate([item.sequence_supported for item in computed])
    qual=deepcopy(context.qual)
    qual["action_feature_inputs"]={}
    for role,frame in roles.items():
        features=c.role_features(role)
        x=tensor if role=="R10:JOINT_SEQUENCE" else None
        mask=sequence_mask if x is not None else (frame.e_friction.notna()&frame.i_friction.notna()).to_numpy() if role=="R10:INCUMBENT" else np.ones(len(frame),bool)
        qual["action_feature_inputs"][role]=dict(status="SOURCE_BOUND_COMPLETE_ORIGINAL_COMPUTED_STATE",source_ref=action_ref,
            new_fit_count=0,outcome_columns_in_model_features=0,computed_signal_dates=[str(d.date()) for d in dates],
            prior_probe_mature_before_current_decision=True,commitment=c.input_commitment(frame,features,x,mask))
    qref=ref(tmp_path/"forward_action_qualification.json",qual)
    provenance={**context.prov,"source_qualification_ref":qref}
    admitted=replace(proto,provenance_json=json.dumps(provenance))
    loader=c.FrozenActionLoader(admitted)
    bound={}
    for role,frame in roles.items():
        bound[role]=c.bind_action_input(loader,role,frame,tensor=tensor if role=="R10:JOINT_SEQUENCE" else None,
            supported=sequence_mask if role=="R10:JOINT_SEQUENCE" else None)
    actions={}
    for candidate,row in loader._candidates.items():
        publications={}
        for slot in row["model_ids"]:
            h=loader.load("new_model:"+slot);meta=c._state(h)
            if h.kind=="r6":
                single=c.predict_r6(h,bound["R6:"+meta["objective"]])
                publications[slot]=(single,c.predict_r6(h,bound["R6:distribution_pair"])) if meta["objective"]=="distribution" else single
            else:
                suffix=f"_{meta['family']}_{meta['capacity']}_{meta['seed']}"
                scale=loader.load("new_scaler:"+slot[:-len(suffix)]+"_SCALER") if c.r10.canonical_family(meta["family"]) in c.r10.SCALED_FAMILIES else None
                publications[slot]=c.predict_r10(h,bound["R10:"+meta["group"]],scaler=scale)
        decoded=c.decode_candidate(loader,candidate,publications)
        # Only source-proven computed dates may materialize a zero-row day.
        assert all(p["computed_signal_dates"]==[str(d.date()) for d in dates] for p in qual["action_feature_inputs"].values())
        actions[candidate]={d:decoded.get(d,[]) for d in dates}
    names=["A","C","D",*["F%02d"%i for i in range(17)],"B"]
    shape=(len(dates),len(names));mask=np.ones(shape,bool);top=mask.copy();top[:,names.index("D")]=False
    buy=top.copy();buy[0,names.index("B")]=False
    assert all(pred.loc[pred.signal_date.eq(d)].is_raw_top20.sum()==20 for d in dates)
    sid={(d,t):"SID_"+t for d in dates for t in names}
    rows=[]
    ids=["SYNTHETIC_OLD_%02d"%i for i in range(57)]+list(loader._candidates)
    for i,cid in enumerate(ids):
        bps=5 if i==0 else 20 if i==1 else 10
        candidate=dict(candidate_id=cid,scientific_tuple_sha256=hashlib.sha256(cid.encode()).hexdigest(),
            action="raw",action_cost_mode="blind",control="none",gross="fixed",risk="diag20_reference",forecast="none",value_model="ridge",
            execution_friction=dict(authority="HYPOTHETICAL_RESEARCH_SCENARIO",benchmark="NEXT_RAW_OPEN",fee_bps=0,
                kind="FIXED_ADVERSE_OPEN_SLIPPAGE",one_way_bps=bps,scenario_id="ADVERSE_OPEN_"+str(bps)+"BPS_USD3000"))
        rows.append(dict(candidate_id=cid,source_group="OLD57" if i<57 else "NEW37",specification=candidate,
            scientific_tuple_sha256=candidate["scientific_tuple_sha256"]))
    inv=ref(tmp_path/"forward_synthetic_inventory.json",dict(candidates=rows))
    new_ids=ids[57:]
    payload=[dict(candidate_id=cid,sessions=[dict(signal_date=str(d.date()),proposals=actions[cid][d]) for d in dates]) for cid in new_ids]
    sidrows=sorted([[str(d.date()),ticker,value] for (d,ticker),value in sid.items()])
    coverage=dict(qual["action_packet_coverage"],source_ref=action_ref,candidate_ids=new_ids,
        decision_dates=[str(d.date()) for d in dates],action_packets_sha256=seam._digest(payload),sid_by_key_sha256=seam._digest(sidrows),
        computed_sessions={cid:{str(d.date()):dict(status="COMPUTED_WITH_PROPOSALS" if actions[cid][d] else "COMPUTED_NO_PROPOSALS",proposal_count=len(actions[cid][d])) for d in dates} for cid in new_ids})
    controller_qual={**qual,"task_id":c.base.profile.TASK,"source_refs":context.prov["source_refs"],"action_packet_coverage":coverage}
    controller_qref=ref(tmp_path/"controller_qualification.json",controller_qual)
    provenance.update(candidate_manifest_ref=inv,source_qualification_ref=controller_qref,
        candidate_bindings=[{k:r[k] for k in ("candidate_id","specification","scientific_tuple_sha256")} for r in rows])
    all_auth=replace(admitted,allowed_path_ids=tuple(ids),runtime_policy_ids=(),provenance_json=json.dumps(provenance))
    batch=[b for b in seam.prepare_batches(all_auth,[r["specification"] for r in rows]) if b.source_group=="NEW37"][0]
    market=seam.replay.MarketArrays(dates,names,np.full(shape,10.),np.full(shape,10.),input_present=mask.copy(),new_buy_eligible=buy.copy(),
        signal_asof=[d.tz_localize("America/New_York")+pd.Timedelta(hours=16) for d in dates])
    account=dict(base_currency="USD",initial_nav=3000.,initial_cash=3000.,initial_holdings=[],fractional_shares=True,
        integer_share_rounding=False,transaction_cost_bps=0.,cash_interest=0.,financing=False,borrowed_cash=False,long_only=True,
        max_weight=1.,max_positions=20,max_invested=1.,capacity_fraction=None)
    security={"SID_"+t:t for t in names}
    source=dict(entitlement_enabled=True,entitlement_events=(),entitlement_security_tickers=security,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",source_fingerprint="d"*64,
            quantity_coordinate="RAW_OLD_SECURITY_SHARES",event_fingerprints=[],security_tickers=security))
    original_overlay=seam.FinalActionOverlay;original_engine=seam.replay.execute_market;captured=[]
    def observe_original_overlay(*args,**kwargs):
        instance=original_overlay(*args,**kwargs);captured.append(instance);return instance
    monkeypatch.setattr(seam,"FinalActionOverlay",observe_original_overlay)
    result,frames=seam.execute_batch(batch,market=market,packets={"ridge":dict(mu=np.full(shape,.03),sigma=np.full(len(dates),.001),lineage=np.full(len(dates),"SYNTHETIC"))},
        top=top,qualified=mask.copy(),vol=np.full(shape,.02),account=account,stock_present=mask.copy(),raw_selector_present=mask.copy(),
        account_source_kwargs=source,action_packets=actions,sid_by_key=sid)
    assert seam.replay.execute_market is original_engine and type(captured[0]) is original_overlay
    audit=pd.DataFrame(captured[0].action_audit)
    applied=audit.loc[audit.consumer_status.eq("APPLIED")]
    for path,kind in (("R6_BUY_TREE","BUY"),("R6_REPLACE_TREE","REPLACE"),("R10_HAZARD_LOGISTIC_LOW","SELL"),("R10_SEQUENCE_TCN_L5_MID","SELL")):
        assert ((applied.path_id==path)&(applied.kind==kind)&applied.signal_date.eq(dates[1])).any()
    fills=frames["fills"]
    assert ((fills.path_id=="R6_BUY_TREE")&(fills.ticker=="B")&(fills.side=="BUY")&fills.execution_date.eq(dates[2])).any()
    assert ((fills.path_id=="R6_REPLACE_TREE")&(fills.ticker=="A")&(fills.side=="SELL")&fills.execution_date.eq(dates[2])).any()
    assert ((fills.path_id=="R10_HAZARD_LOGISTIC_LOW")&(fills.ticker=="A")&(fills.side=="SELL")&fills.execution_date.eq(dates[2])).any()
    assert ((fills.path_id=="R10_SEQUENCE_TCN_L5_MID")&(fills.ticker=="A")&(fills.side=="SELL")&fills.execution_date.eq(dates[2])).any()
    evidence={}
    for path,ticker,side in (("R6_BUY_TREE","B","BUY"),("R6_REPLACE_TREE","A","SELL"),
            ("R10_HAZARD_LOGISTIC_LOW","A","SELL"),("R10_SEQUENCE_TCN_L5_MID","A","SELL")):
        evidence[path]=dict(ticker=ticker,side=side,signal_date=str(dates[1].date()),execution_date=str(dates[2].date()),
            fill_count=int(((fills.path_id==path)&(fills.ticker==ticker)&(fills.side==side)&fills.signal_date.eq(dates[1])&fills.execution_date.eq(dates[2])).sum()))
        assert evidence[path]["fill_count"]>0
    record_property("verified_next_open_fills",json.dumps(evidence,sort_keys=True))
    assert result.metadata["annual_reset"] is False
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    record_property("helper_sha256_after",json.dumps(after,sort_keys=True))
    record_property("nonempty_engine_paths","R6_BUY_TREE:BUY,R6_REPLACE_TREE:REPLACE,R10_HAZARD_LOGISTIC_LOW:SELL,R10_SEQUENCE_TCN_L5_MID:SELL")
    assert after==before



def test_all_a_l10_binds_its_own_source_commitment_not_l5(context):
    from dataclasses import replace
    old=context.publish("R10:JOINT_SEQUENCE")
    role=old.role;frame=old.frame.copy();tensor=np.repeat(old.tensor[:,:1,:],10,axis=1);mask=old.supported.copy()
    cid="ORIGINAL_L10";rows={cid:dict(lookback=10,required_action_roles=[role])}
    proof=deepcopy(context.qual["action_feature_inputs"][role])
    proof["commitment"]=c.input_commitment(frame,old.features,tensor,mask)
    context.qual["action_feature_inputs"][role+":L10"]=proof
    qref=ref(Path(context.qual_ref["path"]),context.qual)
    provenance=deepcopy(context.prov);provenance["source_qualification_ref"]=qref
    auth=replace(context.auth,task_id=c.base.profile.ALL_TASK,allowed_path_ids=(cid,),runtime_policy_ids=(cid,),
        provenance_json=json.dumps(provenance))
    loader=SimpleNamespace(_check=lambda:None,authority=auth,_candidates=rows)
    value=c.bind_action_input(loader,role,frame,tensor=tensor,supported=mask,lookback=10)
    assert value.tensor.shape[1]==10
    with pytest.raises(ValueError,match="SEQUENCE_LENGTH"):
        c.bind_action_input(loader,role,frame,tensor=old.tensor,supported=mask,lookback=5)
    with pytest.raises(ValueError,match="SEQUENCE_MASK"):
        c.bind_action_input(loader,role,frame,tensor=old.tensor,supported=mask,lookback=10)
    del context.qual["action_feature_inputs"][role+":L10"]
    qref=ref(Path(context.qual_ref["path"]),context.qual);provenance["source_qualification_ref"]=qref
    loader.authority=replace(auth,provenance_json=json.dumps(provenance))
    with pytest.raises(ValueError,match="QUALIFIED_ACTION_FORWARD"):
        c.bind_action_input(loader,role,frame,tensor=tensor,supported=mask,lookback=10)
