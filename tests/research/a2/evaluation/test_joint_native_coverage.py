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
    sampled=root/"derived/training_keys_2021.parquet";sampled.parent.mkdir();frame[["signal_date","ticker"]].to_parquet(sampled,index=False)
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
