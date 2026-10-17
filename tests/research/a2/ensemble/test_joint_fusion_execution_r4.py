"""Synthetic-only Stage B source, custody, activation and orchestration guards."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from scripts.research.a2.ensemble import joint_fusion_execution_r4 as e

class Ledger:
    def __init__(self):
        self.status=dict(new_fit_units=0,physical_events=[],failures=[])
        self.snapshots=[]
    def reserve(self,event):
        if any(x["key"]==event["key"] for x in self.status["physical_events"]):
            raise ValueError("NO_RETRY")
        self.status["physical_events"].append(dict(deepcopy(event),status="STARTED",learned_states=1))
        self.status["new_fit_units"]+=1
        self.snapshots.append(deepcopy(self.status))
    def sync(self,events):
        for event in events:
            row=next(x for x in self.status["physical_events"] if x["key"]==event["key"])
            row["status"]={"SUCCEEDED":"FIT_COMPLETE","FAILED":"FIT_FAILURE"}.get(event["status"],"STARTED")
            for field in ("result_sha256","dependencies"):
                if field in event:row[field]=deepcopy(event[field])

def adapter(tmp_path,ledger=None):
    return e.ArtifactLearn(tmp_path,ledger or Ledger(),"a"*64,
        storage_guard=lambda p: p.resolve().is_relative_to(tmp_path.resolve()) or (_ for _ in ()).throw(ValueError("OUTSIDE")))

def inputs():
    return (pd.DataFrame(dict(signal_date=pd.date_range("2022-01-01",periods=10,tz="UTC"),
                             ticker=["S"]*10,x=np.arange(10,dtype=float))),
            np.ones(10))

def test_actual_estimator_cache_unique_artifact_and_reserve_before_fit(tmp_path):
    owner=adapter(tmp_path);learn=owner.for_year(2023);data=inputs()
    def compute():
        assert owner.ledger.status["new_fit_units"]==1
        assert owner.ledger.snapshots[-1]["physical_events"][0]["status"]=="STARTED"
        return Ridge(alpha=100.).fit(np.arange(10)[:,None],np.arange(10))
    a=learn("model_fit","model",data,compute,parameters=dict(alpha=100.))
    b=learn("model_fit","model",data,lambda:pytest.fail("duplicate fit"),parameters=dict(alpha=100.))
    assert a.predict([[2.]])==pytest.approx(b.predict([[2.]]))
    assert len(list((tmp_path/"models/fusion_states").glob("*.joblib")))==1
    assert owner.ledger.status["new_fit_units"]==1
    assert len(learn.cache.usage_log)==2 and len(set(learn.cache.usage_log))==1
    row=owner.ledger.status["physical_events"][0]
    assert row["status"]=="FIT_COMPLETE" and row["result_sha256"]==e.content_hash(row["state_artifact"])

def test_same_ledger_resume_restores_proof_without_fit(tmp_path):
    ledger=Ledger();a=adapter(tmp_path,ledger);a.for_year(2023)("scaler","s",inputs(),lambda:dict(value=2))
    b=adapter(tmp_path,ledger)
    assert b.for_year(2023)("scaler","s",inputs(),lambda:pytest.fail("refit"))==dict(value=2)
    assert ledger.status["new_fit_units"]==1

@pytest.mark.parametrize("status",["FIT_FAILURE","STARTED"])
def test_failed_or_interrupted_reservation_never_retried(tmp_path,status):
    owner=adapter(tmp_path);learn=owner.for_year(2023)
    with pytest.raises(RuntimeError):learn("model_fit","broken",inputs(),lambda:(_ for _ in ()).throw(RuntimeError("failed")))
    ledger=owner.ledger;ledger.status["physical_events"][0]["status"]=status
    restored=adapter(tmp_path,ledger)
    with pytest.raises(ValueError,match="FAILED_OR_RESERVED_STATE_NO_RETRY"):
        restored.for_year(2023)("model_fit","broken",inputs(),lambda:pytest.fail("retry"))
    assert ledger.status["new_fit_units"]==1

def test_artifact_mutation_fails_closed_no_refit(tmp_path):
    owner=adapter(tmp_path);learn=owner.for_year(2023)
    learn("bridge_calibration","rms",inputs(),lambda:1.)
    artifact=owner.ledger.status["physical_events"][0]["state_artifact"]
    from pathlib import Path
    Path(artifact["path"]).write_bytes(b"bad")
    with pytest.raises(ValueError):learn("bridge_calibration","rms",inputs(),lambda:pytest.fail("refit"))
    assert owner.ledger.status["new_fit_units"]==1

def test_input_mutation_is_failed_occupied_not_valid_artifact(tmp_path):
    owner=adapter(tmp_path);data=inputs()
    def mutate():data[0].loc[0,"x"]=100.;return 1.
    with pytest.raises(e.FusionExecutionBlocked):owner.for_year(2023)("scaler","bad",data,mutate)
    assert owner.ledger.status["new_fit_units"]==1
    assert owner.ledger.status["physical_events"][0]["status"]=="FIT_FAILURE"
    assert not list(tmp_path.rglob("*.joblib"))

def test_context_or_values_or_attrs_change_prohibits_false_reuse(tmp_path):
    owner=adapter(tmp_path);data=inputs()
    owner.for_year(2023)("scaler","s",data,lambda:1.)
    changed=deepcopy(data);changed[0].attrs["producer_sha256"]="b"*64
    owner.for_year(2023)("scaler","s",changed,lambda:2.)
    owner.for_year(2024)("scaler","s",data,lambda:3.)
    assert owner.ledger.status["new_fit_units"]==3
    assert len(set(x["key"] for x in owner.ledger.status["physical_events"]))==3

def test_restore_requires_counter_and_proof_consistency(tmp_path):
    owner=adapter(tmp_path);owner.for_year(2023)("scaler","s",inputs(),lambda:1.)
    ledger=owner.ledger;ledger.status["new_fit_units"]+=1
    with pytest.raises(e.FusionExecutionBlocked):adapter(tmp_path,ledger)
    ledger.status["new_fit_units"]-=1
    ledger.status["physical_events"][0]["state_artifact"]["sha256"]="f"*64
    with pytest.raises(e.FusionExecutionBlocked):adapter(tmp_path,ledger)

@pytest.mark.parametrize("clock",["2026-01-01","2025-12-31T23:30:00-05:00","2023-01-01T13:00:00","not-a-date"])
def test_session_clock_cannot_invent_intraday_or_2026_availability(clock):
    with pytest.raises((ValueError,e.FusionExecutionBlocked)):e._session_clock(clock)

def test_session_dates_are_coordinate_assumptions_not_available_at():
    assert e._session_clock("2023-01-01")==pd.Timestamp("2023-01-01",tz="UTC")
    assert e._session_clock("2023-01-01T02:00:00+02:00")==pd.Timestamp("2023-01-01",tz="UTC")
    assert "NOT_AVAILABLE_AT" in e.specification()["source_clock_semantics"]

def native_receipt():
    return dict(schema="B_R4_RAW_NATIVE_OPPORTUNITY_OOF_V1",status="COMPLETE",model="ridge",
        cohort="ANNUAL_2022",target=e.fusion.UNIT,target_clipped=False,raw_native_only=True,
        genuine_selected_recipe_OOF=True,whole_matrix_freeze_sha256="a"*64,
        producer_sha256="b"*64,test2026_rows_read=0,source_fit_cutoff="2022-01-01",
        source_label_mature_max="2021-12-30",selected_capacity_rule_sha256="c"*64,seeds=[20260928],train_rows=600)

@pytest.mark.parametrize("field,value",[
    ("genuine_selected_recipe_OOF",False),("cohort","INNER_2021H2"),
    ("target","MEAN_ER_3D_5D_10D_20D"),("producer_sha256","d"*64),
    ("source_label_mature_max","2022-01-01"),("source_fit_cutoff","2023-01-01"),
    ("seeds",[]),("train_rows",True),("train_rows",0),("raw_native_only",False),("test2026_rows_read",1),
    ("selected_capacity_rule_sha256",None)])
def test_native_receipt_requires_selected_recipe_true_oof_not_bridge(field,value):
    receipt=native_receipt();receipt[field]=value
    with pytest.raises(e.FusionExecutionBlocked):
        e.check_native_receipt(receipt,2022,"ridge","a"*64,"b"*64)

def test_native_receipt_valid_source_cutoff_and_maturity():
    cut,maturity=e.check_native_receipt(native_receipt(),2022,"ridge","a"*64,"b"*64)
    assert maturity<cut and cut==pd.Timestamp("2022-01-01",tz="UTC")

def test_fixed_scientific_scope_and_exact_finite_budget():
    spec=e.specification()
    assert spec["fixed_native_packet"]==["ridge","hgb","xgb","lgb","extra"]
    assert len(spec["methods"])==11 and spec["outer_years"]==[2023,2024,2025]
    assert spec["budget"]["planned_learned_units"]==296<spec["stage_cap"]==300
    assert e.fusion.physical_count_recipe(return_calibration_slots=28,scale_proxy_slots=9,
                                         hgb_stochastic_phases=0)["planned_learned_units"]==284
    assert spec["native_value_calibration"]["roles"]==["huber","linear_q"]
    assert spec["native_scale_proxy"]["roles"]==["ngboost","mlp_dist","cat_uncertainty"]
    assert spec["native_value_calibration"]["interval_coverage_claim"] is False
    assert spec["calibration_catalog"]["probability"].startswith("BLOCKED")
    assert not spec["strict_PIT_promotion_eligible"] and not spec["certified_nav_qualified"]

class Provider:
    def __init__(self):self.calls=[];self.releases=0
    def history(self,members,year,role=e.NATIVE_ROLE,context=True):
        self.calls.append(("history",members,year,role))
        if role==e.META_ROLE and year==2023:raise e.FusionExecutionBlocked("NO_EARLIER_GENUINE_META_OOF")
        return pd.DataFrame(dict(y_open5=[.1,.2],label_mature_date=pd.to_datetime(["2022-01-10","2022-02-10"],utc=True)))
    def current(self,members,year,role=e.NATIVE_ROLE):
        self.calls.append(("current",members,year,role))
        frame=pd.DataFrame(dict(signal_date=pd.to_datetime([f"{year}-03-01"],utc=True),ticker=["S"]))
        for c in e.IDENTITY:frame[c]=["known"]
        for m in members:frame[m+"__mu"]=.1;frame[m+"__scale"]=.2
        for c in e.fusion.CONTEXT:frame[c]=1.
        assert "y_open5" not in frame
        return frame
    def release(self):self.releases+=1

class IdentityScaler:
    def transform(self,x):return x
class IdentityModel:
    def predict(self,x,*context):return x.mean(axis=1)

def test_all_applicable_frozen_slots_continue_with_no_current_y(monkeypatch):
    def meta(*args,**kwargs):
        return dict(status="COMPLETE",qualified=True,model=IdentityModel(),prior_OOF_error_RMS=.2)
    def calibration(*args,**kwargs):
        return dict(scaler=IdentityScaler(),model=IdentityModel(),prior_OOF_error_RMS=.2,fit_units=5)
    monkeypatch.setattr(e.fusion,"fit_meta",meta)
    monkeypatch.setattr(e.fusion,"fit_return_calibration",calibration)
    monkeypatch.setattr(e.fusion,"fit_native_scale_proxy",lambda *a,**k:dict(multiplier=1.,fit_units=1))
    learned=SimpleNamespace(cache=SimpleNamespace(usage_log=[]))
    provider=Provider();outputs=[]
    records=e.execute(provider,lambda year:learned,lambda *args:outputs.append(args))
    assert len(records)==81 and len(outputs)==70 and provider.releases==3
    blocked=[r for r in records if r["status"]=="BLOCKED_OR_FAILED_RETAINED"]
    assert len(blocked)==11 and all(r["role"]=="meta_return_calibration" and r["year"]==2023 for r in blocked)
    assert all("y_open5" not in block.columns for _,_,_,block,*_ in outputs)
    assert set(r["method"] for r in records if r["role"]=="meta")==set(e.fusion.METHODS)

def test_one_failed_slot_does_not_shrink_packet_or_stop_other_methods(monkeypatch):
    def meta(history,cutoff,method,members,*args,**kwargs):
        assert members==e.PACKET
        return dict(status="FAILURE",qualified=False,model=None,prior_OOF_error_RMS=None) if method=="ridge_stack" else dict(
            status="COMPLETE",qualified=True,model=IdentityModel(),prior_OOF_error_RMS=.2)
    monkeypatch.setattr(e.fusion,"fit_meta",meta)
    monkeypatch.setattr(e.fusion,"fit_return_calibration",lambda *a,**k:dict(scaler=IdentityScaler(),model=IdentityModel(),prior_OOF_error_RMS=.2,fit_units=5))
    monkeypatch.setattr(e.fusion,"fit_native_scale_proxy",lambda *a,**k:dict(multiplier=1.,fit_units=1))
    records=e.execute(Provider(),lambda y:SimpleNamespace(cache=SimpleNamespace(usage_log=[])),lambda *a:None)
    assert len(records)==81
    assert len([r for r in records if r["role"]=="meta" and r["status"]=="FAILURE"])==3

def test_activation_rejects_unpinned_stage_b_binding_before_any_numerics(monkeypatch,tmp_path):
    frozen=e.specification()
    monkeypatch.setattr(e.runtime,"guard",lambda *a,**k:dict(pinned_artifacts=[
        dict(path=str(tmp_path/e.SPEC_NAME),sha256="a"*64),dict(path=str(tmp_path/e.SUPPORT_NAME),sha256="a"*64)]))
    monkeypatch.setattr(e.runtime,"sha",lambda *a:"a"*64)
    monkeypatch.setattr(e.runtime,"read_json",lambda p: {} if p.name=="EXECUTION_STATE.json" else frozen)
    with pytest.raises(e.FusionExecutionBlocked,match="INDEPENDENT_FUSION_IMPLEMENTATION_BINDING_REQUIRED"):
        e.activated(tmp_path)


def test_projected_gate_has_unique_artifact_and_fresh_process_restore(tmp_path):
    import subprocess,sys
    e.fusion.prior._shared_handler()
    network=e.fusion.prior.GateNetwork(5,False)
    owner=adapter(tmp_path)
    learned=owner.for_year(2023)("model_fit","gate_serialization",inputs(),lambda:network)
    assert type(learned).__name__=="GateNetwork"
    proof=owner.ledger.status["physical_events"][0]["state_artifact"]
    script="import joblib; obj=joblib.load("+repr(proof["path"])+"); assert type(obj).__name__=='GateNetwork'; print('COLD_RESTORE_OK')"
    result=subprocess.run([sys.executable,"-B","-c",script],cwd=e.REPO,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    assert "COLD_RESTORE_OK" in result.stdout
    assert owner.ledger.status["new_fit_units"]==1


def test_fitted_state_and_source_blocked_output_are_distinct(monkeypatch):
    class SourceGap(Provider):
        def current(self,*args,**kwargs):raise e.FusionExecutionBlocked("ORIGINAL_IDENTITY_PROJECTION_REQUIRED")
    monkeypatch.setattr(e.fusion,"fit_meta",lambda *a,**k:dict(status="COMPLETE",qualified=True,model=IdentityModel(),prior_OOF_error_RMS=.2))
    monkeypatch.setattr(e.fusion,"fit_return_calibration",lambda *a,**k:dict(scaler=IdentityScaler(),model=IdentityModel(),prior_OOF_error_RMS=.2,fit_units=5))
    monkeypatch.setattr(e.fusion,"fit_native_scale_proxy",lambda *a,**k:dict(multiplier=1.,fit_units=1))
    records=e.execute(SourceGap(),lambda y:SimpleNamespace(cache=SimpleNamespace(usage_log=[])),lambda *a:pytest.fail("publish incomplete"))
    assert all(r["oof_qualified"] is False for r in records)
    trained=[r for r in records if r["fit_state_qualified"]]
    assert len(trained)==70
    assert all(r["status"]=="BLOCKED_OR_FAILED_RETAINED" for r in trained)
    assert all(r.get("qualified") is not True for r in records)


def calibration_history():
    dates=pd.date_range("2022-01-01",periods=12,freq="MS",tz="UTC")
    h=pd.DataFrame({"signal_date":np.repeat(dates,50),"ticker":["S"+str(i) for i in range(50)]*12})
    h["security_id"]="known";h["security_id_type"]="SEC";h["cusip"]=None
    h["active_13f_quarter"]="2022Q1";h["quarter_universe_fingerprint"]="a"*64
    h["label_end_date"]=h.signal_date+pd.Timedelta(days=6)
    h["label_mature_date"]=h.label_end_date;h["fit_eligible"]=True
    h["y_open5"]=np.linspace(.01,.02,len(h));h["one__mu"]=np.linspace(.011,.018,len(h))
    h["one__source_cutoff"]=pd.Timestamp("2022-01-01",tz="UTC")
    h["one__source_label_mature_max"]=pd.Timestamp("2021-12-30",tz="UTC")
    h["one__source_sha256"]="b"*64;h["one__producer_role"]=e.META_ROLE
    h.attrs.update(source_inputs_sha256="a"*64,target_binding_sha256="b"*64,
        qualified_oof_contract_sha256="c"*64,target_coordinate=e.fusion.UNIT)
    return h

def test_failed_probe_retains_and_attempts_same_registered_full_phase(tmp_path):
    owner=adapter(tmp_path);base=owner.for_year(2023)
    def learn(kind,name,inputs,compute,parameters=None):
        if name.endswith(":probe") and kind=="bridge_calibration":
            compute=lambda:(_ for _ in ()).throw(RuntimeError("planned probe failure"))
        return base(kind,name,inputs,compute,parameters=parameters)
    learn.cache=base.cache
    h=calibration_history()
    with pytest.raises(RuntimeError,match="planned probe failure"):
        e.fit_return_all_phases(h,"2023-01-01T00:00:00Z",("one",),["one__mu"],learn,name="meta:one")
    rows=owner.ledger.status["physical_events"]
    assert len(rows)==4 and owner.ledger.status["new_fit_units"]==4
    assert sum(x["status"]=="FIT_FAILURE" for x in rows)==1
    assert any(x["name"].endswith(":full") and x["kind"]=="bridge_calibration" and x["status"]=="FIT_COMPLETE" for x in rows)
    assert all("input_projection" in x and x["inputs_sha256"]==e.content_hash(x["input_projection"]) for x in rows)
    with pytest.raises(ValueError,match="FAILED_OR_RESERVED_STATE_NO_RETRY"):
        e.fit_return_all_phases(h,"2023-01-01T00:00:00Z",("one",),["one__mu"],learn,name="meta:one")
    assert owner.ledger.status["new_fit_units"]==4

def test_source_metadata_block_does_not_invent_full_phase(tmp_path):
    owner=adapter(tmp_path);h=calibration_history();h.attrs.pop("qualified_oof_contract_sha256")
    with pytest.raises(ValueError):e.fit_return_all_phases(h,"2023-01-01T00:00:00Z",("one",),["one__mu"],owner.for_year(2023),name="meta:one")
    assert owner.ledger.status["new_fit_units"]==0


@pytest.mark.parametrize("member",["hgb","hgb_q","lgb","lgb_q"])
def test_native_seed_tuple_follows_frozen_actual_training_rows(member):
    receipt=native_receipt();receipt["model"]=member;receipt["train_rows"]=200001
    with pytest.raises(e.FusionExecutionBlocked,match="NATIVE_COMPLETE_FIXED_SEED_PROOF_REQUIRED"):
        e.check_native_receipt(receipt,2022,member,"a"*64,"b"*64)
    receipt["seeds"]=list(e.fusion.SEEDS)
    e.check_native_receipt(receipt,2022,member,"a"*64,"b"*64)
    receipt["train_rows"]=200000
    with pytest.raises(e.FusionExecutionBlocked):e.check_native_receipt(receipt,2022,member,"a"*64,"b"*64)
    receipt["seeds"]=[20260928]
    e.check_native_receipt(receipt,2022,member,"a"*64,"b"*64)


def binding_fixture(monkeypatch,tmp_path):
    from pathlib import Path
    pins=e.code_pins()
    frozen=e.specification()
    breadth=str(Path(e.opportunity.breadth.__file__).resolve())
    original=[deepcopy(p) for p in pins if str(Path(p["path"]).resolve())!=breadth]
    native=str(Path(e.opportunity.__file__).resolve());runmod=str(Path(e.runtime.__file__).resolve())
    wrapper=str(Path(e.__file__).resolve())
    for p in original:
        if str(Path(p["path"]).resolve()) in (native,runmod,wrapper):p["sha256"]="a"*64
    frozen["code_pins"]=original
    mapping=e._pin_map(pins)
    refs=[dict(path=str(tmp_path/name),sha256="b"*64) for name in (
        "PRE_NUMERIC_SEED_CORRECTION_R1.json",e.opportunity.SPEC_NAME,e.opportunity.SUPPORT_NAME,"BUDGET_SCOPE_FREEZE_R1.json")]
    correction=dict(schema="B_R4_PRE_NUMERIC_SEED_CORRECTION_R1",research_id=e.runtime.ID,
        models_added=0,targets_added=0,cutoffs_changed=False,real_numeric_reads=0,real_fit_calls=0,
        outcome_reads=0,test2026_rows_read=0,scientific_retry=0,data_support_changed=False,
        source_key_custody_changed=False,stage_caps=e.runtime.CAPS,
        code_delta=[dict(path=p,old_sha256="a"*64,new_sha256=mapping[p]) for p in (native,breadth)],
        new_spec_ref=refs[1],new_support_ref=refs[2],budget_scope_ref=refs[3])
    matrix=dict(code_pins=pins,pinned_artifacts=refs,conditional_binning_seed_rule_ref=refs[0])
    activation=dict(schema="B_R4_OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_V1",
        original_matrix_sha256="c"*64,transform="JSON_SERIALIZATION_LIST_TUPLE_ONLY",
        opportunity_real_numeric_reads_before_activation=0,opportunity_real_fit_calls_before_activation=0,
        test2026_rows_read=0,
        pinned_artifacts=[dict(path=p,sha256=mapping[p]) for p in (native,breadth)]+refs[:3]+[
            dict(path=str(tmp_path/"WHOLE_MATRIX_FREEZE.json"),sha256="c"*64),
            dict(path=str(e.REPO/"scripts/research/a2/training/joint_opportunity_activation_r4_r1.py"),sha256="d"*64),
            dict(path=str(e.REPO/"tests/research/a2/training/test_joint_opportunity_activation_r4_r1.py"),sha256="d"*64)])
    activation.update({k:True for k in ("no_scientific_change","no_original_frozen_bytes_changed",
        "process_local_only","original_guard_and_runner_unchanged","list_tuple_only",
        "values_number_types_sequence_and_source_changes_rejected","scientific_slots_unchanged",
        "budget_unchanged","input_sources_unchanged")})
    state=dict(opportunity_engineering_binding_ref=dict(path=str(tmp_path/"OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_R1.json"),sha256="c"*64),
        opportunity_engineering_binding_sha256="c"*64)
    monkeypatch.setattr(e.runtime,"read_json",lambda p:state if p.name=="EXECUTION_STATE.json" else (
        activation if p.name=="OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_R1.json" else correction))
    monkeypatch.setattr(e,"code_pins",lambda:deepcopy(pins))
    monkeypatch.setattr(e.runtime,"sha",lambda p:"c"*64)
    monkeypatch.setattr(e.runtime,"_pin",lambda *a:None)
    return frozen,matrix,correction

def test_binding_preserves_original_math_and_records_exact_upstream_changes(monkeypatch,tmp_path):
    frozen,matrix,correction=binding_fixture(monkeypatch,tmp_path)
    result=e.implementation_dependencies(tmp_path,matrix,frozen)
    assert len(result["upstream_code_revisions"])==3
    assert result["pre_numeric_seed_correction_ref"]==matrix["conditional_binning_seed_rule_ref"]
    assert result["original_fusion_code_pins"]==frozen["code_pins"]
    assert len(result["upstream_artifact_refs"])==3

@pytest.mark.parametrize("failure",["math","missing_correction","unpinned_upstream","delta","scientific_scope"])
def test_binding_rejects_any_unbound_or_scientific_upstream_change(monkeypatch,tmp_path,failure):
    from pathlib import Path
    frozen,matrix,correction=binding_fixture(monkeypatch,tmp_path)
    if failure=="math":
        next(p for p in frozen["code_pins"] if Path(p["path"]).name=="joint_fusion_breadth_r4.py")["sha256"]="f"*64
    elif failure=="missing_correction":matrix["pinned_artifacts"]=matrix["pinned_artifacts"][1:]
    elif failure=="unpinned_upstream":matrix["code_pins"]=[]
    elif failure=="delta":correction["code_delta"][0]["new_sha256"]="f"*64
    else:correction["targets_added"]=1
    with pytest.raises(e.FusionExecutionBlocked):e.implementation_dependencies(tmp_path,matrix,frozen)


@pytest.mark.parametrize("failure",["scope","matrix","closure"])
def test_upstream_engineering_binding_cannot_change_science_or_original_pins(monkeypatch,tmp_path,failure):
    frozen,matrix,correction=binding_fixture(monkeypatch,tmp_path)
    activation=e.runtime.read_json(tmp_path/"OPPORTUNITY_ACTIVATION_ENGINEERING_BINDING_R1.json")
    if failure=="scope":activation["scientific_slots_unchanged"]=False
    elif failure=="matrix":activation["original_matrix_sha256"]="f"*64
    else:activation["pinned_artifacts"][0]["sha256"]="f"*64
    with pytest.raises(e.FusionExecutionBlocked):e.implementation_dependencies(tmp_path,matrix,frozen)


def test_upstream_activation_requires_actual_independent_root_pin(monkeypatch,tmp_path):
    frozen,matrix,correction=binding_fixture(monkeypatch,tmp_path)
    state=e.runtime.read_json(tmp_path/"EXECUTION_STATE.json")
    state["opportunity_engineering_binding_sha256"]="f"*64
    with pytest.raises(e.FusionExecutionBlocked,match="ROOT_PINNED_UPSTREAM_ACTIVATION_REQUIRED"):
        e.implementation_dependencies(tmp_path,matrix,frozen)
