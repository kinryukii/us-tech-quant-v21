"""Synthetic access, fit-identity and reuse boundaries; no real numeric pages."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.ensemble import joint_oof_bridge as bridge
from scripts.research.a2.evaluation import joint_native_coverage as native

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding="utf-8")

@pytest.fixture
def native_fixture(tmp_path):
    root=tmp_path/"C_native";root.mkdir()
    src=root/"frozen_source.py";src.write_text("# synthetic source")
    inp=root/"opaque_input.bin";inp.write_bytes(b"synthetic-only-input")
    inputs={k:{"path":str(inp),"sha256":native.digest(inp)} for k in ("training","features","members","raw_oof")}
    design={"version":"V24","line":"C_SELECTOR","target":native.NATIVE_TARGET,
            "base":list(native.NATIVE_NAMES),"years":list(range(2021,2026)),
            "features":list(native.FEATURES),"training_sample":{"max_rows":40000,"seed":native.SEED},
            "sources":{str(src):native.digest(src)},"inputs":inputs}
    write_json(root/"DESIGN_FREEZE.json",design)
    write_json(root/"DESIGN_FREEZE_SHA.json",{"sha256":native.digest(root/"DESIGN_FREEZE.json")})
    model=root/"models/ridge/2021.joblib";model.parent.mkdir(parents=True);model.write_bytes(b"opaque-synthetic-model")
    frame=pd.DataFrame({"signal_date":pd.to_datetime(["2021-01-04","2021-12-31"]),
        "ticker":["A","B"],"security_uid":["idA","idB"],"source_cutoff":pd.Timestamp("2021-01-01"),
        "ridge__raw":[.4,.8],"target":[1000.,2000.],
        "label_end_date":pd.to_datetime(["2021-02-01","2026-01-30"]),"score":[99.,98.]})
    pred=root/"predictions/native_ridge_2021.parquet";pred.parent.mkdir();frame.to_parquet(pred,index=False)
    sampled=root/"derived/training_keys_2021.parquet";sampled.parent.mkdir();pd.DataFrame({"signal_date":pd.to_datetime(["2020-11-02","2020-12-01"]),"ticker":["A","B"],"target_end_date":pd.to_datetime(["2020-11-30","2020-12-31"])}).to_parquet(sampled,index=False)
    spec={"name":"ridge","year":2021,"cutoff":"2021-01-01","max_train_label_end":"2020-12-31",
        "target":native.NATIVE_TARGET,"features":list(native.FEATURES),"seed":native.SEED,
        "sampled_keys_sha256":native.digest(sampled), "training_sha256":native.digest(inp),
        "feature_sha256":native.digest(inp),"design_sha256":native.digest(root/"DESIGN_FREEZE.json")}
    side={"status":"TRAINED","spec":spec,"model_path":str(model),"model_sha256":native.digest(model),
        "prediction_path":str(pred),"prediction_sha256":native.digest(pred),"rows":len(frame)}
    sidepath=root/"models/ridge/2021.json";write_json(sidepath,side)
    return root,frame,side,sidepath,pred

def spy_pages(monkeypatch):
    actual=native.pq.ParquetFile;calls=[]
    class ProjectedOnly:
        def __init__(self,path):self.real=actual(path)
        def __getattr__(self,name):return getattr(self.real,name)
        def read(self,columns=None,**kwargs):
            calls.append(columns)
            assert columns is not None
            assert not {"target","label_end_date","score","candidate_id"}.intersection(columns)
            return self.real.read(columns=columns,**kwargs)
    monkeypatch.setattr(native.pq,"ParquetFile",ProjectedOnly)
    return calls

def test_metadata_and_reader_project_before_forbidden_content(native_fixture,monkeypatch):
    root,_,_,_,_=native_fixture;calls=spy_pages(monkeypatch)
    binding=native.bind_native_design(root)
    record=native.inspect_native_fold(binding,"ridge",2021)
    assert calls==[]
    assert {"target","label_end_date","score"}.issubset(record["excluded_columns"])
    frame=native.read_native_fold(binding,record)
    assert len(calls)==1 and frame.shape[0]==2
    assert frame.source_label_mature_max.eq(pd.Timestamp("2020-12-31")).all()
    assert not {"target","label_end_date","score"}.intersection(frame.columns)

def test_changed_prediction_hash_stops_before_pages(native_fixture,monkeypatch):
    root,frame,_,_,pred=native_fixture;calls=spy_pages(monkeypatch)
    binding=native.bind_native_design(root)
    record=native.inspect_native_fold(binding,"ridge",2021)
    frame["ridge__raw"]+=1;frame.to_parquet(pred,index=False)
    with pytest.raises(native.NativeDependencyError,match="PREDICTION_HASH"):
        native.read_native_fold(binding,record)
    assert calls==[]

@pytest.mark.parametrize("kind",["maturity","future_signal","cutoff","model_hash","identity"])
def test_invalid_native_lineage_or_bytes_deny_pages(native_fixture,monkeypatch,kind):
    root,frame,side,sidepath,pred=native_fixture;calls=spy_pages(monkeypatch)
    binding=native.bind_native_design(root)
    if kind=="maturity":side["spec"]["max_train_label_end"]="2021-01-01"
    elif kind=="model_hash":side["model_sha256"]="wrong"
    elif kind=="identity":side["spec"]["feature_sha256"]="wrong"
    else:
        if kind=="future_signal":frame.loc[1,"signal_date"]=pd.Timestamp("2026-01-02")
        else:frame["source_cutoff"]=pd.Timestamp("2020-01-01")
        frame.to_parquet(pred,index=False);side["prediction_sha256"]=native.digest(pred)
    write_json(sidepath,side)
    with pytest.raises(native.NativeDependencyError):native.inspect_native_fold(binding,"ridge",2021)
    assert calls==[]

def test_missing_source_fold_is_dependency_not_fabrication(native_fixture,monkeypatch):
    root,_,_,_,_=native_fixture;calls=spy_pages(monkeypatch)
    result=native.inspect_native_sources(root,["ridge"])
    assert result["ready_folds"]==1 and result["new_fit_units"]==0
    assert result["prediction_pages_read"]==0 and calls==[]
    assert result["folds"][1]["reason"]=="MISSING_NATIVE_SIDECAR"

def test_fit_key_binds_actual_native_value_and_dependency(native_fixture):
    root,_,_,_,_=native_fixture;binding=native.bind_native_design(root)
    dates=pd.to_datetime(["2021-05-01","2021-06-01"])
    raw=pd.DataFrame({"signal_date":np.repeat(dates,60),"ticker":[str(i) for i in range(60)]*2,
        "source_cutoff":pd.Timestamp("2021-01-01"),"source_label_mature_max":pd.Timestamp("2020-12-31"),
        "ridge__raw":np.arange(120)/100})
    truth=raw[["signal_date","ticker"]].copy();truth["y_open5"]=np.arange(120)/1000
    truth["label_mature_date"]=truth.signal_date+pd.Timedelta(days=10)
    truth["label_end_date"]=truth.label_mature_date
    spec={"native_name":"ridge"}
    train,_=bridge.prepare_native_training(raw,truth,"2022-01-01",spec)
    prior=[{"year":2021,"prediction_sha256":"first","model_sha256":"model"}]
    first=native.bridge_fit_key(binding,prior,train,spec,{"source":"sha"})
    changed=train.copy();changed.loc[0,"ridge__raw"]+=.1
    second=native.bridge_fit_key(binding,prior,changed,spec,{"source":"sha"})
    assert first["joined_predictor_values_sha256"]!=second["joined_predictor_values_sha256"]
    third=native.bridge_fit_key(binding,[{"year":2021,"prediction_sha256":"changed","model_sha256":"model"}],train,spec,{"source":"sha"})
    assert native._json_sha(first)!=native._json_sha(third)

def test_coverage_preserves_own_fit_and_deduplicates_native_evidence():
    coverage=pd.DataFrame({"method_id":["M001","M002","M005"],
        "status":["REAL_5DAY_FIT_AND_CHRONOLOGICAL_OOF_COMPLETE","REGISTERED_NOT_RUN","REAL_5DAY_FIT_AND_CHRONOLOGICAL_OOF_COMPLETE"],
        "evidence":["original-ownfit",np.nan,"original-hgb"]})
    summary={"methods":{name:{"completed_years":[2022,2023,2024,2025]} for name in ("ridge","elastic","hgb","hgb_class")}}
    updated=native.update_native_coverage(coverage,summary)
    assert updated.at[0,"status"]==coverage.at[0,"status"]
    assert updated.at[2,"status"]==coverage.at[2,"status"]
    assert updated.at[1,"status"].startswith("DIFFERENT_TARGET_NATIVE_REUSE")
    assert updated.at[0,"evidence"].startswith("original-ownfit;")
    pd.testing.assert_frame_equal(native.update_native_coverage(updated,summary),updated)


def test_target_coordinate_accepts_real_frozen_config_type():
    assert bridge._target_coordinate({"B_target":{"name":"FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN","horizon_sessions":5}})=="FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN"
    with pytest.raises(bridge.BridgeDependencyError,match="COORDINATE"):
        bridge._target_coordinate({"B_target":{"horizon_sessions":5}})

def test_sampled_key_bytes_are_bound_without_loading_pages(native_fixture,monkeypatch):
    root,_,_,_,_=native_fixture;calls=spy_pages(monkeypatch)
    binding=native.bind_native_design(root)
    (root/"derived/training_keys_2021.parquet").write_bytes(b"changed-opaque-keys")
    with pytest.raises(native.NativeDependencyError,match="SAMPLED_KEYS_HASH"):
        native.inspect_native_fold(binding,"ridge",2021)
    assert calls==[]


def corrected_binding_fixture(native_fixture):
    root,frame,side,sidepath,pred=native_fixture
    source=root/"selector_challenge.py";source.write_text("# synthetic original frozen source")
    original_sha=native.digest(source)
    snapshot=root/"source_prefit_frozen.py";snapshot.write_bytes(source.read_bytes())
    design=json.loads((root/"DESIGN_FREEZE.json").read_text());design["sources"]={str(source):original_sha}
    write_json(root/"DESIGN_FREEZE.json",design)
    write_json(root/"DESIGN_FREEZE_SHA.json",{"sha256":native.digest(root/"DESIGN_FREEZE.json")})
    side["spec"]["design_sha256"]=native.digest(root/"DESIGN_FREEZE.json");write_json(sidepath,side)
    source.write_text("# synthetic corrected readonly array source")
    ledger=root/"FIT_LEDGER_BEFORE_SOURCE_CORRECTION.json";ledger.write_text('{"events":[]}')
    correction={"phase":"POST_BASE_PRE_COOP_INPUT_AND_CONTROL_REPAIR","timestamp":"2026-10-01T10:00:00+00:00",
        "original_sha256":original_sha,"corrected_sha256":native.digest(source),"original_source_snapshot":str(snapshot),
        "economic_outcome_access":False,"model_parameters_changed":False,"selection_rule_changed":False,"successful_stage1_refit":False,
        "zero_fit_attempts":[f"BASE:{name}:{year}" for name in ("tcn","lstm","gru") for year in range(2021,2026)],
        "ledger_original_sha256":native.digest(ledger)}
    write_json(root/"SOURCE_CORRECTION.json",correction)
    write_json(root/"SOURCE_CORRECTION_SYNTHETIC_CHECK.json",{"passed":True})
    return root,frame,side,sidepath,pred,source,correction

def create_synthetic_repair(native_fixture):
    root,frame,side,_,_,source,correction=corrected_binding_fixture(native_fixture)
    original=json.loads(json.dumps(side));original["status"]="FAILED";original["message"]="assignment destination is read-only"
    original["spec"]["name"]="gru"
    original_path=root/"models/gru/2021.json";write_json(original_path,original)
    pred=root/"predictions/native_gru_2021.parquet";frame=frame.rename(columns={"ridge__raw":"gru__raw"});frame.to_parquet(pred,index=False)
    model=root/"models/gru/2021_repair1.joblib";model.write_bytes(b"synthetic repaired model")
    repaired=json.loads(json.dumps(side));repaired["spec"]=dict(original["spec"])
    repaired["spec"].update(executed_orchestrator_sha256=native.digest(source),source_correction_sha256=native.digest(root/"SOURCE_CORRECTION.json"))
    repaired.update(model_path=str(model),model_sha256=native.digest(model),prediction_path=str(pred),prediction_sha256=native.digest(pred))
    repaired_path=root/"models/gru/2021_repair1.json";write_json(repaired_path,repaired)
    return root,original_path,repaired_path,repaired,source

def test_correction_preserves_regular_original_fitted_source(native_fixture,monkeypatch):
    root,_,_,_,_,source,correction=corrected_binding_fixture(native_fixture);calls=spy_pages(monkeypatch)
    binding=native.bind_native_design(root);record=native.inspect_native_fold(binding,"ridge",2021)
    assert binding["current_verified_source_sha256"][str(source)]==correction["corrected_sha256"]
    assert record["fitted_source_sha256"][str(source)]==correction["original_sha256"]
    assert record["authorized_repair"] is None and calls==[]

def test_authorized_repair_selects_sidecar_and_preserves_failed_identity(native_fixture,monkeypatch):
    root,oldpath,repaired_path,_,source=create_synthetic_repair(native_fixture);calls=spy_pages(monkeypatch)
    oldsha=native.digest(oldpath);binding=native.bind_native_design(root)
    record=native.inspect_native_fold(binding,"gru",2021)
    assert record["sidecar_path"]==str(repaired_path)
    assert record["authorized_repair"]["original_failure_sha256"]==oldsha
    assert record["fitted_source_sha256"][str(source)]==native.digest(source)
    assert calls==[]
    frame=native.read_native_fold(binding,record)
    assert "gru__raw" in frame and native.digest(oldpath)==oldsha
    assert not {"target","label_end_date","score"}.intersection(frame)

@pytest.mark.parametrize("change",["correction_sha","model_hash","old_identity","current_source"])
def test_invalid_repair_binding_stops_before_pages(native_fixture,monkeypatch,change):
    root,oldpath,path,repaired,source=create_synthetic_repair(native_fixture);calls=spy_pages(monkeypatch)
    if change=="current_source":
        source.write_text("# unauthorized later source")
        with pytest.raises(native.NativeDependencyError):native.bind_native_design(root)
    else:
        binding=native.bind_native_design(root)
        if change=="correction_sha":repaired["spec"]["source_correction_sha256"]="wrong"
        elif change=="model_hash":repaired["model_sha256"]="wrong"
        else:
            original=json.loads(oldpath.read_text());original["spec"]["training_sha256"]="wrong";write_json(oldpath,original)
        write_json(path,repaired)
        with pytest.raises(native.NativeDependencyError):native.inspect_native_fold(binding,"gru",2021)
    assert calls==[]

def test_native_wave_requires_current_completions_after_source_correction(native_fixture):
    root,_,_,_,_,_,_=corrected_binding_fixture(native_fixture)
    correction=native.bind_native_design(root)["source_correction"]
    write_json(root/"BASE_COMPLETION.json",{"phase":"BASE_ATTEMPTS_COMPLETE","years":list(range(2021,2026)),"candidates":40,"test2026_read":False,"finished_at":"2026-10-01T10:01:00+00:00"})
    write_json(root/"COOPERATION_COMPLETION.json",{"phase":"COOPERATION_ATTEMPTS_COMPLETE","test2026_read":False,"finished_at":"2026-10-01T10:02:00+00:00"})
    write_json(root/"PIPELINE_STATE.json",{"stage":"SELECTION_EVIDENCE_REPAIR1","status":"RUNNING","updated_at":"2026-10-01T10:03:00+00:00"})
    assert native._native_wave_metadata(root,correction)["complete"]
    old=json.loads((root/"BASE_COMPLETION.json").read_text());old["finished_at"]="2026-10-01T09:59:00+00:00";write_json(root/"BASE_COMPLETION.json",old)
    assert not native._native_wave_metadata(root,correction)["complete"]


def test_repair_training_key_physical_maturity_gate_before_pages(native_fixture,monkeypatch):
    root,_,path,repaired,_=create_synthetic_repair(native_fixture);calls=spy_pages(monkeypatch)
    sampled=root/"derived/training_keys_2021.parquet"
    pd.DataFrame({"signal_date":pd.to_datetime(["2020-12-01"]),"ticker":["A"],"target_end_date":pd.to_datetime(["2021-01-01"])}).to_parquet(sampled,index=False)
    newsha=native.digest(sampled);repaired["spec"]["sampled_keys_sha256"]=newsha;write_json(path,repaired)
    oldpath=root/"models/gru/2021.json";old=json.loads(oldpath.read_text());old["spec"]["sampled_keys_sha256"]=newsha;write_json(oldpath,old)
    binding=native.bind_native_design(root)
    with pytest.raises(native.NativeDependencyError,match="PHYSICAL_TRAINING_MATURITY"):
        native.inspect_native_fold(binding,"gru",2021)
    assert calls==[]


def test_repair_schema_distinguishes_svc_margin_from_native_return():
    schema=bridge._schema(pd.DataFrame(columns=["signal_date","ticker","source_cutoff","svc__raw"]),{"native_name":"svc"})
    assert schema["role"]=="decision_margin"
    assert schema["native_columns"]==["svc__raw"]
    assert schema["member"]=="raw_svc"  # same numeric retained transform; only role made explicit
