"""Synthetic only: no imports of data runners, market files or existing models."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts.research.a2.training import joint_opportunity_execution_r4 as worker
from scripts.research.a2.training import joint_opportunity_breadth_r4 as breadth

def _pin(path,frame):
    frame.to_parquet(path,index=False)
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

@pytest.fixture
def source(tmp_path):
    dates=pd.to_datetime(["2020-06-24","2021-01-05","2021-06-29","2021-07-06",
                          "2021-12-28","2022-01-05","2023-01-05","2024-01-05","2025-01-06"])
    base=pd.DataFrame(dict(signal_date=dates,ticker=["T"]*len(dates)))
    panel=base.copy()
    for c in worker.IDENTITY:panel[c]="EXISTING_"+c
    panel["moomoo_transport_code"]="US.T";panel["is_max_group"]=True
    panel["feature_available"]=True;panel["all_features_finite"]=True
    panel["feature_source"]="FROZEN_RAW_A2_TRAINING_MATRIX_32"
    panel["feature_coordinate"]="FROZEN";panel["feature_pit_status"]="EXISTING"
    for c in breadth.FEATURES:panel[c]=np.arange(len(panel),dtype=float)+.1
    label=base.copy()
    label["execution_date"]=dates+pd.Timedelta(days=1)
    label["label_end_date"]=dates+pd.Timedelta(days=8)
    label["label_mature_date"]=label.label_end_date
    label["endpoint_pair_available"]=True;label["label_available"]=True
    label["label_coordinate"]="SOURCE_SUPPORTED_QUANTITY_ONLY"
    label["label_unsupported_common_event"]=False
    label["y_open5"]=np.arange(len(label),dtype=float)/10
    # Folds must purge immature end-of-half/year observations by metadata first.
    for c in worker.LABEL_META:panel[c]=label[c]
    held=panel[worker.KEYS+breadth.FEATURES].copy()
    held["lookback_121_eligible"]=True;held["all_features_available"]=True
    raw=base.rename(columns={"signal_date":"trade_date"})
    pins=dict(panel=_pin(tmp_path/"panel.parquet",panel),
              label=_pin(tmp_path/"label.parquet",label),
              held=_pin(tmp_path/"held.parquet",held),
              raw_keys=_pin(tmp_path/"raw.parquet",raw))
    return pins

def test_import_and_catalogue_do_not_read_data():
    assert breadth.budget()["learned_total_upper"]==864
    assert breadth.budget()["physical_fit_events"]==634
    assert len(breadth.slot_matrix())==464
    assert len(breadth.specs()["blocked_models"])==9

def test_metadata_reader_denies_numeric_before_body(source):
    reader=worker.FoldReader(source)
    with pytest.raises(worker.OpportunityBlocked,match="METADATA_ONLY"):
        reader.read("label",["y_open5"])
    assert reader.audit==[]
    meta=reader.metadata()
    assert "y_open5" not in meta and not set(breadth.FEATURES).intersection(meta)
    assert meta.fit_eligible.all()

def test_training_projection_purges_future_and_immature(source):
    reader=worker.FoldReader(source,numeric=True)
    train=reader.training("2021-07-01")
    assert train.signal_date.max()==pd.Timestamp("2021-01-05")
    assert len(train)==2
    target_reads=[r for r in reader.audit if "y_open5" in r["columns"]]
    assert len(target_reads)==1
    assert target_reads[0]["mature_before"]=="2021-07-01"
    assert pd.Timestamp(target_reads[0]["stop"])==pd.Timestamp("2021-07-01")

def test_inner_loss_truth_does_not_cross_fixed_2021(source):
    reader=worker.FoldReader(source,numeric=True)
    first=reader.inner_validation("INNER_2021H1")
    second=reader.inner_validation("INNER_2021H2")
    assert first.signal_date.tolist()==[pd.Timestamp("2021-01-05")]
    assert second.signal_date.tolist()==[pd.Timestamp("2021-07-06")]
    assert reader.audit[-1]["mature_before"]=="2022-01-01"

def test_annual_inference_never_reads_y(source):
    reader=worker.FoldReader(source,numeric=True)
    out=reader.annual_prediction(2025)
    assert "y_open5" not in out
    assert out.identity_qualified.all()
    assert out.signal_date.dt.year.eq(2025).all()
    assert not any("y_open5" in r["columns"] for r in reader.audit)

def test_context_owner_only_reads_requested_existing_features(source):
    reader=worker.FoldReader(source,numeric=True)
    out=reader.prediction_features(2024,["ret_1d","ret_20d"])
    assert set(breadth.FEATURES).intersection(out)=={"ret_1d","ret_20d"}
    assert not any("y_open5" in r["columns"] for r in reader.audit)
    with pytest.raises(worker.OpportunityBlocked,match="EXISTING_CONTEXT"):
        reader.prediction_features(2024,["news_embedding"])

def test_truth_hydration_strictly_earlier_and_no_future_outcomes(source):
    reader=worker.FoldReader(source,numeric=True)
    out=reader.read_earlier_truth("2024-01-01",[2022,2023],["ret_1d"])
    assert out.signal_date.dt.year.tolist()==[2022,2023]
    assert out.label_mature_date.lt("2024-01-01").all()
    assert all(r["mature_before"]=="2024-01-01" for r in reader.audit
               if "y_open5" in r["columns"])
    with pytest.raises(worker.OpportunityBlocked,match="EARLIER_GENUINE"):
        reader.read_earlier_truth("2024-01-01",[2024])
    with pytest.raises(worker.OpportunityBlocked,match="FULL_FREEZE|FROZEN"):
        worker.FoldReader(source).read_earlier_truth("2024-01-01",[2023])

def test_raw_keys_not_raw_prices(source):
    reader=worker.FoldReader(source);reader.metadata()
    raw=[r for r in reader.audit if r["source"]=="raw_keys"]
    assert raw[0]["columns"]==["ticker","trade_date"]

def test_numeric_gap_blocks_whole_fold_instead_of_drop(source):
    pin=source["panel"];p=Path(pin["path"])
    f=pd.read_parquet(p);f.loc[0,"ret_1d"]=np.nan
    source["panel"]=_pin(p,f)
    reader=worker.FoldReader(source,numeric=True)
    with pytest.raises(worker.OpportunityBlocked,match="NO_ROW_FILTER"):
        reader.training("2021-01-01")

def test_physical_boundary_checked_before_any_body(source):
    p=Path(source["panel"]["path"]);f=pd.read_parquet(p)
    f.loc[0,"signal_date"]=pd.Timestamp("2026-01-02")
    source["panel"]=_pin(p,f)
    with pytest.raises(ValueError,match="Forbidden mixed"):
        worker.FoldReader(source,numeric=True)

def test_stale_source_pin_rejected(source):
    source["held"]["sha256"]="0"*64
    with pytest.raises(ValueError,match="hash mismatch"):
        worker.FoldReader(source)

def test_joint_views_reserve_durably_before_fit():
    ledger=SimpleNamespace(reserve=lambda e:captured.append(dict(e)))
    captured=[];events=[]
    identity=dict(cohort="INNER_2021H1",train_values_sha256="f"*64)
    cb=worker._event_callback(ledger,identity,events)
    cb(dict(component="NATIVE_ESTIMATOR",model="mlp_q",learned_states=[
        "shared_trunk","q10_head","q50_head","q90_head"]))
    assert len(captured)==4
    assert len({e["parameters"]["physical_optimizer_call_id"] for e in captured})==1
    assert len({e["key"] for e in captured})==4
    assert all(e["status"]=="STARTED" for e in events)
    cb(dict(component="SHARED_SCALER"))
    assert captured[-1]["kind"]=="scaler"

def test_fit_activation_precedes_data_read(monkeypatch,tmp_path):
    def fail(*args):raise worker.OpportunityBlocked("NOT_FROZEN")
    monkeypatch.setattr(worker.runtime,"guard",fail)
    monkeypatch.setattr(worker,"source_binding",lambda *a:pytest.fail("source read before freeze"))
    with pytest.raises(worker.OpportunityBlocked,match="NOT_FROZEN"):
        worker.run_training(tmp_path)

def test_old_models_not_loaded_when_frame_differs(monkeypatch,source,tmp_path):
    reader=worker.FoldReader(source,numeric=True)
    train=reader.training("2021-01-01")
    monkeypatch.setattr(worker.joblib,"load",lambda *a:pytest.fail("illegal old load"))
    model,status=worker.exact_reuse(tmp_path,{},train,"INNER_2021H1","ridge","MEDIUM",20260928)
    assert model is None and status=="NON_EQUIVALENT_TRAINING_FRAME"

def test_old_no_july_or_nonmedium_reuse(monkeypatch,source,tmp_path):
    train=worker.FoldReader(source,numeric=True).training("2021-07-01")
    monkeypatch.setattr(worker.joblib,"load",lambda *a:pytest.fail("illegal old load"))
    assert worker.exact_reuse(tmp_path,{},train,"INNER_2021H2","hgb","MEDIUM",20260928)[1]=="NO_EXISTING_SEMIANNUAL_MODEL"
    assert worker.exact_reuse(tmp_path,{},train,"INNER_2021H1","hgb","HIGH",20260928)[1]=="NOT_AN_EXACT_REUSE_SLOT"

def test_all_seed_failures_retained_no_retry(monkeypatch,source,tmp_path):
    train=worker.FoldReader(source,numeric=True).training("2021-01-01")
    prediction=worker.FoldReader(source,numeric=True).inner_validation("INNER_2021H1")
    ledger=SimpleNamespace(status=dict(records=[]),checkpoint=lambda:None,sync=lambda events:None,
                           reserve=lambda event:reserved.append(event))
    reserved=[];called=[]
    monkeypatch.setattr(worker,"exact_reuse",lambda *a:(None,"NOT_EQUIVALENT"))
    def fail(name,capacity,seed,*a,**kw):
        called.append(seed)
        kw["on_fit_started"](dict(component="NATIVE_ESTIMATOR",learned_states=["estimator"]))
        raise breadth.ScientificFitFailure("FIXED_SYNTHETIC_FAILURE")
    monkeypatch.setattr(breadth,"fit_model",fail)
    out=worker._group(tmp_path,ledger,{},train,prediction,"extra","INNER_2021H1",
                      "2021-01-01","LOW","f"*64,None,None)
    assert out["status"]=="FAILURE" and called==list(breadth.SEEDS)
    assert len(reserved)==3 and ledger.status["records"][0]["learned_states"]==3
    out=worker._group(tmp_path,ledger,{},train,prediction,"extra","INNER_2021H1",
                      "2021-01-01","LOW","f"*64,None,None)
    assert out["status"]=="FAILED_PRESERVED" and len(called)==3

def test_capacity_freeze_requires_only_inner_receipts(monkeypatch,tmp_path):
    monkeypatch.setattr(breadth,"applicable_models",lambda:("ridge",))
    rows=[]
    for tier,loss in zip(breadth.CAPACITIES,[3,1,2]):
        for cohort in ("INNER_2021H1","INNER_2021H2"):
            path=tmp_path/f"{cohort}_{tier}.json"
            path.write_text(json.dumps(dict(loss=loss)),encoding="utf-8")
            rows.append(dict(model="ridge",cohort=cohort,capacity=tier,status="COMPLETE",
                receipt_ref=dict(path=str(path),sha256=worker.runtime.sha(path))))
    # A future performance row may coexist, but cannot enter selection.
    rows.append(dict(model="ridge",cohort="ANNUAL_2025",capacity="HIGH",status="COMPLETE",
                     outcome="SENTINEL_DO_NOT_READ"))
    written=[]
    monkeypatch.setattr(worker.runtime,"write",lambda run,name,value,**k:written.append(value))
    selected=worker.freeze_selected_capacities(tmp_path,SimpleNamespace(status=dict(records=rows)),"f"*64)
    assert selected["capacities"]=={"ridge":"MEDIUM"} and selected["annual_outcomes_read"]==0
    assert written[0]["selection_scope"]=="2021H1/H2_ONLY"

def test_prediction_output_has_no_truth_and_clear_OOF_role(monkeypatch,source,tmp_path):
    frame=worker.FoldReader(source,numeric=True).annual_prediction(2022)
    monkeypatch.setattr(worker,"assert_safe_output_path",lambda *a,**k:None)
    monkeypatch.setattr(worker.runtime,"write",lambda *a,**k:None)
    receipt=dict(capacity="LOW",source_fit_cutoff="2022-01-01",source_label_mature_max="2021-12-31")
    out=worker._output(tmp_path,"ridge","ANNUAL_2022",frame,
                      dict(native_mu=np.ones(len(frame))),receipt)
    f=pd.read_parquet(out["artifact"]["path"])
    assert "y_open5" not in f and "native_mu" in f
    assert f.source_fit_cutoff.eq(pd.Timestamp("2022-01-01")).all()
    assert f.fold_year.eq(2022).all()

def test_date_weights_match_original_mean_one_formula():
    dates=pd.to_datetime(["2020-07-01","2020-07-01","2020-07-02"])
    old=1/pd.Series(dates).map(pd.Series(dates).value_counts()).to_numpy(float)
    old=old/old.mean()
    np.testing.assert_array_equal(old,breadth.date_weights(dates))


def test_prepare_projects_each_fold_before_metadata_decode(monkeypatch,source,tmp_path):
    monkeypatch.setattr(worker,"specification",lambda run:dict(source_binding={"sha256":"f"*64}))
    monkeypatch.setattr(worker,"source_binding",lambda run:({},source,{},tmp_path))
    written=[]
    monkeypatch.setattr(worker.runtime,"write",lambda run,name,value,**kw:written.append((name,value)))
    _,support=worker.prepare(tmp_path)
    assert support["native_numeric_read"]==0 and len(support["nodes"])==6
    audit=support["metadata_projection_audit"]
    assert all(pd.Timestamp(r["stop"])==pd.Timestamp("2021-01-01") for r in audit[:3])
    assert all(r["start"]=="2021-01-01" and pd.Timestamp(r["stop"])==pd.Timestamp("2021-07-01")
               for r in audit[3:6])
    assert not any(set(r["columns"]).intersection(worker.NUMERIC) for r in audit)
    assert [name for name,_ in written]==[worker.SPEC_NAME,worker.SUPPORT_NAME]

class SyntheticEstimator:
    def predict(self,X):
        return np.zeros(len(X))

def test_complete_inner_then_annual_pipeline_and_durable_count(monkeypatch,source,tmp_path):
    # Tiny synthetic real scalers and fixed output estimator; no project source data/old models.
    from contextlib import nullcontext
    monkeypatch.setattr(worker.runtime,"stage_writer",lambda *a:nullcontext())
    matrix={"pinned_artifacts":[]}
    monkeypatch.setattr(worker,"activated",lambda *a:(matrix,{}))
    (tmp_path/"WHOLE_MATRIX_FREEZE.json").write_text("{}",encoding="utf-8")
    (tmp_path/worker.SPEC_NAME).write_text("{}",encoding="utf-8")
    (tmp_path/worker.SUPPORT_NAME).write_text("{}",encoding="utf-8")
    monkeypatch.setattr(worker,"source_binding",lambda *a:({},source,{},tmp_path))
    monkeypatch.setattr(breadth,"applicable_models",lambda:("ridge",))
    monkeypatch.setattr(breadth,"bind_native",lambda:None)
    monkeypatch.setattr(worker,"exact_reuse",lambda *a:(None,"SYNTHETIC_NOT_EQUIVALENT"))
    monkeypatch.setattr(worker,"assert_safe_output_path",lambda *a,**k:None)
    def writer(run,name,value,**kw):
        path=Path(run)/name;path.parent.mkdir(parents=True,exist_ok=True)
        if kw.get("immutable") and path.exists():
            assert json.loads(path.read_text(encoding="utf-8"))==value
        path.write_text(json.dumps(value,default=str),encoding="utf-8")
        return worker.runtime.sha(path)
    monkeypatch.setattr(worker.runtime,"write",writer)
    class Ledger:
        def __init__(self,*a,**k):
            self.status=dict(records=[],physical_events=[],new_fit_units=0,status="READY")
        def checkpoint(self):pass
        def reserve(self,event):
            assert not any(e["key"]==event["key"] for e in self.status["physical_events"])
            self.status["physical_events"].append(event)
            self.status["new_fit_units"]+=1
        def sync(self,events):pass
    monkeypatch.setattr(worker.runtime,"StageLedger",Ledger)
    calls=[]
    def fit_model(name,capacity,seed,X,y,weights,**kwargs):
        calls.append((name,capacity,seed))
        kwargs["on_fit_started"](dict(component="NATIVE_ESTIMATOR",model=name,
            learned_states=["estimator"],learned_units=1,backend_calls=1))
        return breadth.NativeFit(name,capacity,seed,(SyntheticEstimator(),),kwargs["scaler"])
    monkeypatch.setattr(breadth,"fit_model",fit_model)
    status=worker.run_training(tmp_path,phase="all")
    assert status["new_fit_units"]==16  # 6 shared scalers + 6 inner + 4 annual models.
    assert len(calls)==10
    assert json.loads((tmp_path/"SELECTED_CAPACITY_R4.json").read_text())["capacities"]=={"ridge":"LOW"}
    for year in breadth.ANNUAL:
        receipt=json.loads((tmp_path/f"receipts/OPPORTUNITY_ridge_{year}.json").read_text())
        assert receipt["genuine_selected_recipe_OOF"] is True
        assert receipt["target_clipped"] is False and receipt["target_cash_complete"] is False
        assert "loss" not in receipt
        f=pd.read_parquet(receipt["artifact"]["path"])
        assert "y_open5" not in f and f.signal_date.dt.year.eq(year).all()
    assert not any("y_open5" in r["columns"] and r["mature_before"]=="None"
                   for r in json.loads((tmp_path/"OPPORTUNITY_EXECUTION_RECEIPT.json").read_text())["source_projection_audit"])
