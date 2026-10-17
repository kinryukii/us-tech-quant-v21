"""C12 controller checks use synthetic frames, mocked readers and backend spies.

No real artifact, outcome, native estimator fit, provider or locked-year row is
read. File-backed ledger probes write only pytest's approved external temp root.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_boundary_decision as sut
from scripts.research.a2.evaluation import selector_boundary_evidence as ev


def raw_frame(dates):
    return pd.DataFrame([dict(signal_date=pd.Timestamp(date), security_uid=f"UID:{rank:03d}",
        raw_rank=rank,raw_score=(49-rank)/100.,ticker=f"S{rank:03d}",U_t_fingerprint="SYNTHETIC_FULL48")
        for date in dates for rank in range(1,49)])


def pair_meta(dates):
    p = sut.pairs.geometry(raw_frame(dates))
    p["label_end_date"] = p.signal_date+pd.Timedelta(days=28)
    return p


def fresh_ledger(digest="synthetic-design"):
    dag = sut.physical_dag()
    return dict(research_id=sut.RESEARCH_ID,design_sha256=digest,hard_cap=380,active_ceiling=122,scientific_retry=0,
                slots={s["id"]:{**s,"status":"PENDING","charged":False,"backend_entered":False} for s in dag["active_slots"]})


def capacity_records():
    return [dict(capacity=cap,fold_cutoff=cut,status="COMPLETE",dates=10,sum_daily_utility=.1)
            for cap in sut.est.CAPACITIES for cut in sut.CUTS[:2]]


def test_exact_partial_dag_reservation_and_component_budget():
    dag = sut.physical_dag()
    assert len(dag["active_slots"]) == dag["active_physical_ceiling"] == 122
    assert sum(s["kind"]=="estimator" for s in dag["active_slots"]) == 119
    assert sum(s["kind"]=="scaler" for s in dag["active_slots"]) == 3
    assert len({s["id"] for s in dag["active_slots"]}) == 122
    assert dag["hard_cap"] == 380 and dag["scientific_retry"] == 0
    assert dag["blocked_outer_head_years"] == 18 and dag["blocked_nominal_slots_are_not_reservations"]
    assert len(sut.pairs.ROLES) == len(sut.est.PARADIGMS) == 9
    for p in sut.est.PARADIGMS:
        got = sut.components(p)
        if p in sut.est.STOCHASTIC: assert got == [(s,None) for s in sut.est.SEEDS]
        elif p == "QUANTILE_HGB": assert got == [(sut.est.SEEDS[0],q) for q in sut.est.QUANTILES]
        else: assert got == [(sut.est.SEEDS[0],None)]


def test_required_dates_strict_maturity_and_whole_date_exclusion():
    meta = pair_meta(["2023-06-01","2023-12-01"])
    meta.loc[meta.signal_date.eq("2023-12-01"),"label_end_date"] = pd.Timestamp("2024-01-01")
    ix = sut.required_dates(meta,None,"2024-01-01")
    assert len(ix)==200 and meta.iloc[ix].signal_date.eq("2023-06-01").all()
    meta.loc[0,"label_end_date"] = pd.Timestamp("2024-01-01")
    assert len(sut.required_dates(meta,None,"2024-01-01")) == 0


def test_required_missing_maturity_blocks_and_future_append_cannot_change_past():
    original = pair_meta(["2023-06-01"])
    later = pair_meta(["2024-06-01"])
    assert len(sut.required_dates(pd.concat([original,later],ignore_index=True),None,"2024-01-01")) == 200
    original.loc[0,"label_end_date"] = pd.NaT
    with pytest.raises(ValueError,match="BLOCKED_LABEL"):
        sut.required_dates(original,None,"2024-01-01")


def test_capacity_selection_date_mass_and_predeclared_ties():
    records = capacity_records()
    assert sut.choose_capacity(records)[0] == "LOW"
    for r in records:
        if r["capacity"]=="MID": r["sum_daily_utility"] = .11
    assert sut.choose_capacity(records)[0] == "MID"
    records = capacity_records()
    for r in records:
        if r["capacity"]=="HIGH" and r["fold_cutoff"]==sut.CUTS[0]:
            r.update(dates=1,sum_daily_utility=.08)
        elif r["capacity"]=="HIGH": r.update(dates=100,sum_daily_utility=0.)
    assert sut.choose_capacity(records)[0] == "LOW"  # do not mean equally across folds


@pytest.mark.parametrize("problem",["duplicate_fold","failed_fold","zero_dates"])
def test_incomplete_two_folds_cannot_select_capacity(problem):
    records = [r for r in capacity_records() if r["capacity"]=="LOW"]
    if problem=="duplicate_fold": records[1]["fold_cutoff"] = records[0]["fold_cutoff"]
    elif problem=="failed_fold": records[1]["status"] = "FAILED"
    else: records[1]["dates"] = 0
    assert sut.choose_capacity(records)[0] is None


def test_matching_utility_is_sum_edges_over20_and_keeps_zero_replacement_dates():
    raw = raw_frame(["2024-03-01","2024-03-04"])
    g = sut.pairs.geometry(raw)
    realized = np.full(len(g),.04)
    prediction = np.zeros(len(g))
    first = np.flatnonzero(g.signal_date.eq("2024-03-01"))
    prediction[first] = 1.
    utility = sut.matching_utility(g,prediction,sut.pairs.ROLES[1],realized,raw)
    assert utility["matched_pairs"] == 10 and utility["dates"] == 2
    assert utility["sum_daily_utility"] == pytest.approx(.02)
    assert utility["mean_utility"] == pytest.approx(.01)
    one = np.zeros(len(g));one[first[0]] = 1.
    large = realized.copy();large[first[0]] = .2
    one_utility = sut.matching_utility(g,one,sut.pairs.ROLES[1],large,raw)
    assert one_utility["sum_daily_utility"] == pytest.approx(.01)
    assert one_utility["sum_daily_utility"] < utility["sum_daily_utility"]
    large[0] = np.nan
    with pytest.raises(ValueError,match="BLOCKED_LABEL"):
        sut.matching_utility(g,one,sut.pairs.ROLES[1],large,raw)


@pytest.mark.parametrize("problem",["design","budget","missing_slot","slot_identity","complete_no_entry",
                                      "reserved_no_charge","entry_no_charge","blocked_entry","pending_charged"])
def test_ledger_binding_and_actual_entry_validation(problem):
    value = fresh_ledger();sid = next(iter(value["slots"]));slot = value["slots"][sid]
    if problem=="design": value["design_sha256"] = "other"
    elif problem=="budget": value["active_ceiling"] = 123
    elif problem=="missing_slot": del value["slots"][sid]
    elif problem=="slot_identity": slot["cutoff"] = "2026-01-01"
    elif problem=="complete_no_entry": slot.update(status="COMPLETE",charged=True)
    elif problem=="reserved_no_charge": slot.update(status="RESERVED",charged=False)
    elif problem=="entry_no_charge": slot.update(status="FAILED",charged=False,backend_entered=True)
    elif problem=="blocked_entry": slot.update(status="BLOCKED",charged=True,backend_entered=True)
    elif problem=="pending_charged": slot["charged"] = True
    with pytest.raises(ValueError):sut.validate_ledger(value,"synthetic-design",sut.physical_dag())


@pytest.fixture
def ledger_run(tmp_path):
    run = tmp_path/"synthetic_run";run.mkdir()
    sut.putj(run/"DESIGN_FREEZE.json",dict(synthetic_only=True))
    sut.putj(run/"FIT_LEDGER.json",fresh_ledger(sut.sha(run/"DESIGN_FREEZE.json")))
    return run,sut.Ledger(run)


def test_ledger_one_entry_failed_reservation_no_retry_and_budget(ledger_run):
    run, ledger = ledger_run
    sid = next(iter(ledger.value["slots"]))
    assert ledger.claim(sid)
    assert not ledger.claim(sid)
    with pytest.raises(ValueError,match="NO_BACKEND"):
        ledger.finish(sid,"COMPLETE")
    ledger.enter(sid,dict(operation="SYNTHETIC_SPY"))
    with pytest.raises(ValueError,match="ONE_BACKEND"):
        ledger.enter(sid,dict(operation="SYNTHETIC_SECOND_ENTRY_FORBIDDEN"))
    ledger.finish(sid,"FAILED",reason="synthetic failure")
    assert not sut.Ledger(run).claim(sid)
    assert ledger.value["slots"][sid]["charged"] and ledger.value["slots"][sid]["backend_entered"]
    with pytest.raises(ValueError,match="PRESERVE_TERMINAL"):
        ledger.finish(sid,"COMPLETE")
    ledger.value["active_ceiling"] = 1
    next_sid = next(s for s in ledger.value["slots"] if s!=sid)
    with pytest.raises(RuntimeError,match="BUDGET_EXHAUSTED"):ledger.claim(next_sid)


class JoblibSpy:
    def __init__(self): self.models={};self.loads=0
    def dump(self,obj,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"SYNTHETIC_MODEL_SPY")
        self.models[str(path)]=obj
    def load(self,path): self.loads+=1;return self.models[str(path)]


class ScalerSpy:
    def __init__(self): self.calls=[]
    def fit(self,x,sample_weight):self.calls.append((x.copy(),sample_weight.copy()));return self
    def transform(self,x):return np.asarray(x)


def test_scaler_exact_reuse_date_mass_and_feature_identity(ledger_run,monkeypatch):
    run,ledger=ledger_run;spy=ScalerSpy();jb=JoblibSpy()
    monkeypatch.setattr(sut,"StandardScaler",lambda:spy)
    meta=pair_meta(["2023-06-01"]);x=np.zeros((200,114));order=list(sut.pairs.feature_order(sut.pairs.BASE32))
    model,ix=sut.scaler_for(run,ledger,sut.CUTS[0],x,meta,order,jb)
    assert model is spy and len(ix)==200 and len(spy.calls)==1
    assert spy.calls[0][1].sum()==pytest.approx(1.)
    repeated,_=sut.scaler_for(run,ledger,sut.CUTS[0],x,meta,order,jb)
    assert repeated is spy and len(spy.calls)==1 and jb.loads==1
    x[0,0]=1.
    with pytest.raises(ValueError,match="REUSE_IDENTITY"):
        sut.scaler_for(run,ledger,sut.CUTS[0],x,meta,order,jb)


def test_prefit_cutoff_guard_failed_slot_does_not_retry(ledger_run,monkeypatch):
    run,ledger=ledger_run;meta=pair_meta(["2023-06-01"]);meta["label_end_date"]=pd.Timestamp(sut.CUTS[0])
    calls=[]
    monkeypatch.setattr(sut.est,"fit",lambda *a,**k:calls.append("FORBIDDEN_FIT"))
    x=np.zeros((200,114));y=np.ones(200);tasks=np.ones((200,4));seed=sut.est.SEEDS[0]
    args=(run,ledger,"HGB","LOW",sut.CUTS[0],seed,None,ScalerSpy(),np.arange(200),x,y,tasks,meta,object(),JoblibSpy())
    assert sut.fit_component(*args) is None and calls==[]
    assert sut.fit_component(*args) is None and calls==[]
    sid=f"{sut.CUTS[0]}_HGB_LOW_{seed}_None"
    assert ledger.value["slots"][sid]["status"]=="FAILED"
    assert ledger.value["slots"][sid]["charged"] and not ledger.value["slots"][sid]["backend_entered"]


def test_component_callback_then_completed_exact_reuse(ledger_run,monkeypatch):
    run,ledger=ledger_run;meta=pair_meta(["2023-06-01"]);calls=[];jb=JoblibSpy()
    model=SimpleNamespace(metadata=dict(synthetic=True))
    def fit(*args,**kwargs):
        calls.append(1);kwargs["on_fit_call"](dict(operation="SYNTHETIC_FIT_SPY"));return model
    monkeypatch.setattr(sut.est,"fit",fit)
    x=np.zeros((200,114));y=np.ones(200);tasks=np.ones((200,4));seed=sut.est.SEEDS[0]
    args=(run,ledger,"HGB","LOW",sut.CUTS[0],seed,None,ScalerSpy(),np.arange(200),x,y,tasks,meta,object(),jb)
    assert sut.fit_component(*args) is model
    assert sut.fit_component(*args) is model and len(calls)==1 and jb.loads==1
    sid=f"{sut.CUTS[0]}_HGB_LOW_{seed}_None"
    assert ledger.value["slots"][sid]["status"]=="COMPLETE"


@pytest.mark.parametrize("paradigm",["CAT","MLP","MULTITASK_MLP","QUANTILE_HGB"])
def test_bundle_requires_every_predeclared_seed_or_quantile(monkeypatch,paradigm):
    parts=sut.components(paradigm);calls=[];combines=[]
    def fit(*a,**k):
        seed,q=a[5:7];calls.append((seed,q));return None if (seed,q)==parts[1] else SimpleNamespace(seed=seed,q=q)
    monkeypatch.setattr(sut,"fit_component",fit)
    monkeypatch.setattr(sut.est,"predict",lambda model,x:np.zeros((2,4)) if paradigm=="MULTITASK_MLP" else np.zeros(2))
    monkeypatch.setattr(sut.est,"combine_predictions",lambda *a:combines.append(a))
    result,detail=sut.prediction_bundle(None,None,paradigm,"LOW",sut.CUTS[0],None,None,None,None,None,None,np.zeros((2,114)),None,None)
    assert result is None and detail["missing_components"]==[parts[1]]
    assert calls==parts and combines==[]


@pytest.fixture
def reader_inputs(monkeypatch,tmp_path):
    dates=["2023-06-01","2024-03-01","2024-08-01","2025-03-01"]
    raw=raw_frame(dates);g=sut.pairs.geometry(raw);order=list(sut.pairs.feature_order(sut.pairs.BASE32))
    x=pd.concat([g.copy(),pd.DataFrame(np.zeros((len(g),len(order))),columns=order)],axis=1)
    meta=raw[sut.KEY].copy();meta["label_end_date"]=meta.signal_date+pd.Timedelta(days=28)
    labels=meta.loc[meta.signal_date.lt("2025-01-01"),sut.KEY].copy()
    labels["target_end_date"]=labels.signal_date+pd.Timedelta(days=28)
    labels["target_end_date_20d"]=labels.target_end_date
    labels["target"]=np.tile(np.arange(48)/100.,3)
    for field in ("ER_3D","ER_5D","ER_10D","ER_20D"):labels[field]=labels.target
    documents={"pairs.parquet":g,"features.parquet":x,"frame.parquet":raw,"raw_score.parquet":meta}
    pins={name:dict(path=str(tmp_path/name),sha256="synthetic") for name in documents}
    receipt=dict(pairs=pins["pairs.parquet"],features=pins["features.parquet"],frame=pins["frame.parquet"])
    design=dict(raw_score=pins["raw_score.parquet"],horizon_labels=dict(path=str(tmp_path/"labels.parquet"),sha256="synthetic"),
                pair_key_sha256=sut.pairs.pair_key_sha256(g),feature_order=order)
    reads=[]
    monkeypatch.setattr(sut,"pin",lambda value:Path(value["path"]))
    monkeypatch.setattr(sut,"pre2026",lambda path,columns,date:documents[Path(path).name][columns].copy())
    monkeypatch.setattr(sut.shared,"prove_label_boundary",lambda *a,**k:None)
    def read_table(path,columns,filters):
        reads.append(copy.deepcopy(filters));return SimpleNamespace(to_pandas=lambda:labels[columns].copy())
    monkeypatch.setattr(sut.pq,"read_table",read_table)
    monkeypatch.setattr(sut,"EXPECTED_DATES",(1,2,3))
    return design,receipt,documents,labels,reads


def test_reader_numeric_projection_strict_pre2025_and_full_pair_binding(reader_inputs):
    design,receipt,documents,labels,reads=reader_inputs
    g,x,raw,meta,xx,yy,tasks=sut.data_before_2025(Path("unused"),design,receipt)
    assert len(g)==800 and len(meta)==len(xx)==len(yy)==len(tasks)==600
    assert meta.signal_date.lt("2025-01-01").all()
    assert all(tuple(v[:2])!=("signal_date",">=") or pd.Timestamp(v[2])<pd.Timestamp("2025-01-01") for v in reads[0])
    assert ("signal_date","<",pd.Timestamp("2025-01-01")) in reads[0]
    assert ("target_end_date","<",pd.Timestamp("2025-01-01")) in reads[0]


@pytest.mark.parametrize("problem",["missing_label","uid_swap","maturity_mismatch","missing_clock","feature_order"])
def test_reader_missing_or_wrong_identity_blocks_required_geometry(reader_inputs,problem):
    design,receipt,docs,labels,_=reader_inputs
    before=sut.pairs.pair_key_sha256(docs["pairs.parquet"])
    if problem=="missing_label":labels.drop(index=labels.index[20],inplace=True)
    elif problem=="uid_swap":labels.loc[20,"security_uid"]="UID:REPLACED_IDENTITY"
    elif problem=="maturity_mismatch":docs["raw_score.parquet"].loc[20,"label_end_date"]-=pd.Timedelta(days=1)
    elif problem=="missing_clock":docs["raw_score.parquet"].loc[20,"label_end_date"]=pd.NaT
    else:
        docs["features.parquet"].loc[[0,1],list(sut.pairs.PAIR_KEYS)]=docs["features.parquet"].loc[[1,0],list(sut.pairs.PAIR_KEYS)].to_numpy()
    with pytest.raises(ValueError,match="BLOCKED_LABEL|FEATURE_ORDER"):
        sut.data_before_2025(Path("unused"),design,receipt)
    assert sut.pairs.pair_key_sha256(docs["pairs.parquet"])==before


@pytest.fixture
def synthetic_checked(monkeypatch,tmp_path):
    root=tmp_path/"freeze";design_hash="synthetic-design-sha";review_hash="synthetic-review-sha"
    required=[Path(sut.__file__),Path(sut.pairs.__file__),Path(sut.est.__file__),Path(ev.__file__),
              sut.REPO/"scripts/research/a2/training/stateful_inputs.py",
              sut.REPO/"scripts/research/a2/evaluation/selector_boundary_delivery.py"]
    sources={str(p):"synthetic-source-sha" for p in required}
    pins={name:dict(path=str(tmp_path/(name+".json")),sha256="synthetic-"+name) for name in
          ("raw_score","features","horizon_labels","pair_freeze","input_qualification","physical_dag")}
    design=dict(sources=sources,pair_key_sha256="geometry-sha",capacity_specs={"spy":"NO_NATIVE_RUNTIME"},**pins)
    receipt=dict(pair_key_sha256="geometry-sha",target_values_read=0,
                 **{name:dict(path=str(tmp_path/("receipt_"+name)),sha256="synthetic-receipt-"+name) for name in ("pairs","features","frame")})
    docs={str(root/"DESIGN_FREEZE.json"):design,str(root/"DESIGN_FREEZE_SHA.json"):dict(sha256=design_hash,formal_review_sha256=review_hash),
          str(root/"FORMAL_FREEZE_REVIEW.json"):dict(status="PASS",design_sha256=design_hash,source_pins=copy.deepcopy(sources)),
          pins["pair_freeze"]["path"]:receipt,pins["physical_dag"]["path"]:sut.physical_dag()}
    hashes={str(root/"DESIGN_FREEZE.json"):design_hash,str(root/"FORMAL_FREEZE_REVIEW.json"):review_hash,**sources}
    hashes.update({v["path"]:v["sha256"] for v in pins.values()});hashes.update({receipt[k]["path"]:receipt[k]["sha256"] for k in ("pairs","features","frame")})
    monkeypatch.setattr(sut,"paths",lambda root:dict(synthetic=True))
    monkeypatch.setattr(sut,"readj",lambda path:docs[str(path)])
    monkeypatch.setattr(sut,"sha",lambda path:hashes[str(path)])
    def pin(value):
        if hashes[value["path"]]!=value["sha256"]:raise ValueError("SYNTHETIC_PIN_CHANGED")
        return Path(value["path"])
    monkeypatch.setattr(sut,"pin",pin)
    monkeypatch.setattr(sut,"runtime",lambda root:(None,)*6)
    monkeypatch.setattr(sut.est,"capacity_specs",lambda runtime:{"spy":"NO_NATIVE_RUNTIME"})
    monkeypatch.setattr(ev,"validate_design",lambda design:None)
    return root,design,docs,hashes


def test_checked_formal_pair_native_dag_pass(synthetic_checked):
    root,design,docs,hashes=synthetic_checked
    assert sut.checked(root)[1] is design


@pytest.mark.parametrize("problem",["review_fail","source_changed","dag_changed","pair_changed","native_changed"])
def test_checked_refuses_changed_frozen_contract(synthetic_checked,problem):
    root,design,docs,hashes=synthetic_checked
    if problem=="review_fail":docs[str(root/"FORMAL_FREEZE_REVIEW.json")]["status"]="FAIL"
    elif problem=="source_changed":hashes[next(iter(design["sources"]))]="changed-source"
    elif problem=="dag_changed":docs[design["physical_dag"]["path"]]["active_physical_ceiling"]=123
    elif problem=="pair_changed":docs[design["pair_freeze"]["path"]]["pair_key_sha256"]="another-geometry"
    else:design["capacity_specs"]={"changed":"native"}
    with pytest.raises(ValueError,match="FORMAL_REVIEW|PIN_CHANGED|DAG_CHANGED|PAIR_NATIVE"):
        sut.checked(root)




@pytest.mark.parametrize("missing",["selector_boundary_decision.py","selector_boundary_pairs.py",
                                    "selector_boundary_estimators.py","selector_boundary_evidence.py","stateful_inputs.py","selector_boundary_delivery.py"])
def test_checked_missing_required_own_source_cannot_pass(synthetic_checked,missing):
    root,design,docs,_=synthetic_checked
    key=next(path for path in design["sources"] if Path(path).name==missing)
    del design["sources"][key]
    docs[str(root/"FORMAL_FREEZE_REVIEW.json")]["source_pins"]=copy.deepcopy(design["sources"])
    with pytest.raises(ValueError,match="SOURCE.*CLOSURE|SOURCE.*REQUIRED"):
        sut.checked(root)


def test_estimator_without_backend_entry_cannot_be_marked_complete(ledger_run,monkeypatch):
    run,ledger=ledger_run;meta=pair_meta(["2023-06-01"])
    monkeypatch.setattr(sut.est,"fit",lambda *a,**k:SimpleNamespace(metadata=dict(synthetic=True)))
    x=np.zeros((200,114));y=np.ones(200);tasks=np.ones((200,4));seed=sut.est.SEEDS[0]
    result=sut.fit_component(run,ledger,"HGB","LOW",sut.CUTS[0],seed,None,ScalerSpy(),np.arange(200),
                             x,y,tasks,meta,object(),JoblibSpy())
    assert result is None
    slot=ledger.value["slots"][f"{sut.CUTS[0]}_HGB_LOW_{seed}_None"]
    assert slot["status"]=="FAILED" and slot["charged"] and not slot["backend_entered"]



def test_final_pipeline_freeze_prevents_any_new_label_read_or_fit(ledger_run,monkeypatch):
    run,_=ledger_run
    (run/"FINAL_PIPELINES_FREEZE.json").write_text("SYNTHETIC_SEALED_PIPELINE",encoding="utf-8")
    monkeypatch.setattr(sut,"checked",lambda root:({}, {}, {}))
    monkeypatch.setattr(sut,"runtime",lambda root:(None,)*6)
    def forbidden(*a,**k):raise AssertionError("NO_LABEL_READ_AFTER_FINAL_FREEZE")
    monkeypatch.setattr(sut,"data_before_2025",forbidden)
    with pytest.raises(FileExistsError,match="NO_RETRAIN_AFTER_FINAL"):
        sut.train(run)


def test_interrupted_reserved_slot_is_not_retried_or_falsely_finalized(ledger_run,monkeypatch):
    run,ledger=ledger_run;reserved=next(iter(ledger.value["slots"]))
    assert ledger.claim(reserved)
    meta=pair_meta(["2023-06-01"]);g=meta[list(sut.pairs.PAIR_KEYS)];x=np.zeros((200,114))
    design=dict(feature_order=list(sut.pairs.feature_order(sut.pairs.BASE32)),blocked_outer_years={"2023":sut.GAP,"2024":sut.GAP})
    monkeypatch.setattr(sut,"checked",lambda root:({},design,{}))
    monkeypatch.setattr(sut,"runtime",lambda root:(None,None,None,None,JoblibSpy(),object()))
    monkeypatch.setattr(sut,"data_before_2025",lambda *a:(g,None,raw_frame(["2023-06-01"]),meta,x,np.zeros(200),np.zeros((200,4))))
    monkeypatch.setattr(sut,"scaler_for",lambda *a:(None,np.arange(200)))
    def forbidden(*a,**k):raise AssertionError("SCIENTIFIC_RETRY_FORBIDDEN")
    monkeypatch.setattr(sut.est,"fit",forbidden)
    with pytest.raises(ValueError,match="UNRESOLVED_RESERVED"):
        sut.train(run)
    after=sut.Ledger(run)
    assert after.value["slots"][reserved]["status"]=="RESERVED"
    assert after.value["slots"][reserved]["charged"] and not after.claim(reserved)
    assert not (run/"FINAL_PIPELINES_FREEZE.json").exists()
