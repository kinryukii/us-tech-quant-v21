"""Pure synthetic C10 consumer guards: no estimator fit or real source access."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import selector_training_sufficiency as sut
from scripts.research.a2.evaluation import selector_sufficiency_evidence as evaluator


def frame(dates, sizes=None):
    sizes = sizes or [21]*len(dates)
    rows = []
    for date, n in zip(dates, sizes):
        date = pd.Timestamp(date)
        for uid in range(n):
            rows.append(dict(signal_date=date, security_uid=uid, ticker=f"T{uid:03d}",
                U_t_fingerprint=f"SYNTHETIC_U_{n}", target=float(uid)/100.,
                target_end_date=date+pd.Timedelta(days=1), label_end_date=date+pd.Timedelta(days=1), x=float(uid)))
    return pd.DataFrame(rows)


@pytest.fixture
def run(tmp_path):
    root = tmp_path/"consumer"
    root.mkdir()
    sut.putj(root/"DESIGN_FREEZE.json",dict(synthetic_only=True))
    return root


def ledger(run, events=None):
    events = copy.deepcopy(events or [])
    return dict(design_freeze_sha256=sut.sha(run/"DESIGN_FREEZE.json"), events=events,
        charged_backend_ceiling=len(events), actual_backend_entered=sum(e["entered"] for e in events),
        backend_completed=sum(e["completed"] for e in events), scientific_retries=0)


def event(kind, paradigm, cutoff, capacity, **extra):
    return dict(physical_id=sut.node_id(kind,paradigm,cutoff,capacity),kind=kind,paradigm=paradigm,
        cutoff=cutoff,capacity=capacity,attempt=1,status="RESERVED",entered=0,completed=0,**extra)


def records(year=2023, paradigm=None):
    p = paradigm or sut.PARADIGMS[0]
    output = {}
    for cap in sut.CAPACITIES:
        for start,end in sut.folds(year):
            output[f"{p}|{start}|{cap}"] = dict(status="COMPLETE",fit_cutoff=start,validation_end=end,
                max_label_end=str((pd.Timestamp(end)-pd.Timedelta(days=1)).date()),
                dates=10,sum_daily_utility=1.)
    return output


def test_consumer_and_evaluator_role_contract_agree():
    assert sut.ALL_ROLES == evaluator.ALL_ROLES
    assert sut.NEW_ROLES == evaluator.NEW_ROLES and sut.REFERENCES == evaluator.REFERENCES
    assert len(sut.ROLES) == 16 and len(sut.ALL_ROLES) == 17
    assert len(sut.NEW_ROLES) == 11 and len(sut.REFERENCES) == 6


def test_full_pool_maturity_and_future_append_invariance():
    source = frame(["2022-12-01","2022-12-30","2023-01-03"])
    source.loc[source.signal_date.eq("2022-12-30"),"target_end_date"] = pd.Timestamp("2023-01-01")
    expected = sut.full_pool(source,"2023-01-01")
    assert expected.signal_date.nunique() == 1 and expected.signal_date.eq("2022-12-01").all()
    future = frame(["2026-01-02"])
    future["target"] = np.nan
    appended = pd.concat([source,future],ignore_index=True)
    pd.testing.assert_frame_equal(sut.full_pool(appended,"2023-01-01"),expected)
    assert sut.key_digest(expected) == sut.key_digest(sut.full_pool(appended,"2023-01-01"))


def test_original_rows_are_retained_without_40k_sampling():
    source = frame(["2022-01-03","2022-02-01"],[21000,21000])
    result = sut.full_pool(source,"2023-01-01")
    assert len(result) == 42000
    assert result[["signal_date","security_uid","ticker"]].duplicated().sum() == 0


def test_row_weights_equal_total_date_and_mean_one():
    dates = frame(["2022-01-03","2022-01-04"],[21,63]).signal_date
    weights = sut.row_weights(dates)
    totals = pd.Series(weights).groupby(dates.reset_index(drop=True)).sum()
    np.testing.assert_allclose(totals.to_numpy(),[42.,42.])
    assert np.isclose(weights.sum(),84.) and np.isclose(weights.mean(),1.)
    assert np.all(weights>0)


@pytest.mark.parametrize("dates",[[],[pd.NaT]])
def test_row_weights_unknown_clock_rejected(dates):
    with pytest.raises(ValueError,match="WEIGHT_CLOCK_REQUIRED"):
        sut.row_weights(dates)


def test_inner_clock_filters_whole_dates_before_score_selection():
    source = frame(["2022-01-03","2022-02-01","2022-03-01"])
    source.loc[source.signal_date.eq("2022-02-01")&source.security_uid.eq(20),"target"] = np.nan
    source.loc[source.signal_date.eq("2022-03-01")&source.security_uid.eq(20),"label_end_date"] = pd.Timestamp("2022-07-01")
    original = source.copy(deep=True)
    result = sut.inner_frame(source,"2022-01-01","2022-07-01")
    assert result.signal_date.nunique()==1 and len(result)==21 and result.security_uid.nunique()==21
    pd.testing.assert_frame_equal(source,original)
    future = frame(["2026-01-02"])
    pd.testing.assert_frame_equal(sut.inner_frame(pd.concat([source,future],ignore_index=True),
        "2022-01-01","2022-07-01"),result)


@pytest.mark.parametrize("source",[
    frame(["2022-01-03"],[19]),
    frame(["2022-08-01"]),
])
def test_inner_full_u_and_min20_required(source):
    with pytest.raises(ValueError,match="INNER_FULL_U_MATURE_DATES_REQUIRED"):
        sut.inner_frame(source,"2022-01-01","2022-07-01")


def test_utility_fixed_top20_uid_tie_and_equal_date_observations():
    source=frame(["2022-01-03","2022-01-04"],[21,63])
    daily=sut.utility(np.zeros(len(source)),source)
    np.testing.assert_allclose(daily.to_numpy(),[.095,.095])
    assert len(daily)==2


@pytest.mark.parametrize("uid",[0,20])
def test_utility_never_skips_missing_selected_or_full_u_label(uid):
    source=frame(["2022-01-03"])
    source.loc[source.security_uid.eq(uid),"target"]=np.nan
    with pytest.raises(ValueError):
        sut.utility(np.zeros(len(source)),source)


@pytest.mark.parametrize("scores",[np.zeros(20),np.r_[np.zeros(20),np.nan]])
def test_utility_requires_complete_finite_score_array(scores):
    with pytest.raises(ValueError,match="INNER_FINITE_FULL_U_SCORE_REQUIRED"):
        sut.utility(scores,frame(["2022-01-03"]))


def test_choose_capacity_lowest_tier_tie_and_only_requested_year():
    data=records(); p=sut.PARADIGMS[0]
    expected=sut.choose_capacity(data,2023,p)
    assert expected[0]=="LOW" and len(expected[1])==3
    extra=records(2025,p)
    for row in extra.values():row["sum_daily_utility"]=1e12
    assert sut.choose_capacity({**data,**extra},2023,p)==expected


def test_choose_capacity_requires_both_folds_not_one_lucky_fold():
    data=records();p=sut.PARADIGMS[0]
    first,second=sut.folds(2023)
    data[f"{p}|{first[0]}|HIGH"]["sum_daily_utility"]=1e9
    data[f"{p}|{second[0]}|HIGH"]["status"]="FAILED_DEPENDENCY"
    choice,eligible=sut.choose_capacity(data,2023,p)
    assert choice=="LOW" and [c for c,_,_ in eligible]==["LOW","MEDIUM"]
    assert sut.choose_capacity({},2023,p)==(None,[])


def test_choose_capacity_pools_dates_not_equal_fold_means():
    data=records();p=sut.PARADIGMS[0]
    first,second=sut.folds(2023)
    for cap in sut.CAPACITIES:
        data[f"{p}|{first[0]}|{cap}"]["dates"]=10
        data[f"{p}|{second[0]}|{cap}"]["dates"]=1
    data[f"{p}|{first[0]}|LOW"]["sum_daily_utility"]=0.
    data[f"{p}|{second[0]}|LOW"]["sum_daily_utility"]=.9
    for start,_ in sut.folds(2023):
        row=data[f"{p}|{start}|MEDIUM"];row["sum_daily_utility"]=.1*row["dates"]
        data[f"{p}|{start}|HIGH"]["sum_daily_utility"]=-1.
    assert sut.choose_capacity(data,2023,p)[0]=="MEDIUM"


@pytest.mark.parametrize("field,value",[
    ("fit_cutoff","2023-01-01"),("validation_end","2023-01-01"),
    ("max_label_end","2022-07-01"),("max_label_end",None),
    ("dates",0),("sum_daily_utility",np.nan),
])
def test_choose_capacity_fold_identity_maturity_and_finite_metric(field,value):
    data=records();p=sut.PARADIGMS[0]
    data[f"{p}|2022-01-01|LOW"][field]=value
    with pytest.raises(ValueError,match="INNER_SELECTION_USED_FUTURE_OR_CHANGED_FOLD"):
        sut.choose_capacity(data,2023,p)


def test_physical_plan_conditional_115_names_but_only_110_calls(run):
    rows=[event("scaler","SHARED",cut,"WEIGHTED") for cut in sut.CUTS]
    rows += [event("estimator",p,cut,c) for cut in sut.CUTS[:-1] for p in sut.PARADIGMS for c in sut.CAPACITIES]
    rows += [event("estimator",p,sut.CUTS[-1],c) for p in sut.PARADIGMS for c in ("LOW","MEDIUM")]
    rows += [event("estimator","RIDGE",f"{y}-01-01","LOW") for y in sut.YEARS]
    assert len(sut.allowed_nodes())==115 and len(rows)==110
    L=ledger(run,rows)
    assert sut.ledger_checked(run,L)["charged_backend_ceiling"]==110
    assert sum(e["kind"]=="estimator" for e in rows)==103
    extra=event("estimator",sut.PARADIGMS[0],sut.CUTS[-1],"HIGH")
    with pytest.raises(ValueError,match="ONLY_ONE_SELECTED_2025_CAPACITY"):
        sut.ledger_checked(run,ledger(run,rows+[extra]))


@pytest.mark.parametrize("mutation",["duplicate","attempt","physical_id","unplanned","telemetry","counter","retry","freeze"])
def test_ledger_identity_dedup_budget_and_no_retry_guards(run,mutation):
    row=event("estimator",sut.PARADIGMS[0],sut.CUTS[0],"LOW")
    L=ledger(run,[row])
    if mutation=="duplicate":L=ledger(run,[row,row])
    elif mutation=="attempt":L["events"][0]["attempt"]=2
    elif mutation=="physical_id":L["events"][0]["physical_id"]=sut.node_id("estimator",sut.PARADIGMS[1],sut.CUTS[0],"LOW")
    elif mutation=="unplanned":
        L["events"][0]["cutoff"]="2026-01-01";L["events"][0]["physical_id"]=sut.node_id("estimator",sut.PARADIGMS[0],"2026-01-01","LOW")
    elif mutation=="telemetry":L["events"][0]["completed"]=1
    elif mutation=="counter":L["charged_backend_ceiling"]=0
    elif mutation=="retry":L["scientific_retries"]=1
    else:L["design_freeze_sha256"]="0"*64
    with pytest.raises(ValueError):
        sut.ledger_checked(run,L)


def test_reservation_failure_retained_and_never_retried(run):
    L=ledger(run);p=sut.PARADIGMS[0];cut=sut.CUTS[0]
    e=sut.reserve(run,L,"estimator",p,cut,"LOW")
    assert L["charged_backend_ceiling"]==1 and L["actual_backend_entered"]==0
    with pytest.raises(ValueError,match="UNFINISHED_ATTEMPT_NO_SCIENTIFIC_RETRY"):
        sut.artifact(run,L,"estimator",p,cut,"LOW")
    with pytest.raises(ValueError,match="NO_DUPLICATE_ATTEMPT"):
        sut.reserve(run,L,"estimator",p,cut,"LOW")
    e["status"]="FAILED"
    assert sut.artifact(run,L,"estimator",p,cut,"LOW") is False
    assert sut.ledger_checked(run,L)["charged_backend_ceiling"]==1


def test_second_entered_call_forbidden_and_success_counter_required(run):
    L=ledger(run);e=sut.reserve(run,L,"scaler","SHARED",sut.CUTS[0],"WEIGHTED")
    sut.entered(run,L,e)
    with pytest.raises(ValueError,match="SECOND_BACKEND_CALL_FORBIDDEN"):
        sut.entered(run,L,e)
    e["status"]="TRAINED"
    with pytest.raises(ValueError,match="SUCCESS_CALL_MISSING"):
        sut.ledger_checked(run,L)
    sut.completed(run,L,e)
    assert sut.ledger_checked(run,L)["backend_completed"]==1


@pytest.mark.parametrize("mutation",["cutoff","paradigm","capacity","physical_id","bytes"])
def test_persisted_artifact_bound_to_original_physical_identity(run,mutation):
    p=sut.PARADIGMS[0];cut=sut.CUTS[0]
    art=run/"fake-model.bin";art.write_bytes(b"SYNTHETIC_NEVER_DESERIALIZED")
    row=event("estimator",p,cut,"LOW")
    row.update(status="TRAINED",entered=1,completed=1,receipt_path=str(run/"model-receipt.json"))
    rec=dict(design_freeze_sha256=sut.sha(run/"DESIGN_FREEZE.json"),artifact=dict(path=str(art),sha256=sut.sha(art)),
        cutoff=cut,paradigm=p,capacity="LOW",physical_id=row["physical_id"])
    sut.putj(Path(row["receipt_path"]),rec)
    L=ledger(run,[row])
    assert sut.artifact(run,L,"estimator",p,cut,"LOW")==rec
    if mutation=="bytes":art.write_bytes(b"CHANGED")
    else:
        rec[mutation]="CHANGED";sut.putj(Path(row["receipt_path"]),rec)
    with pytest.raises(ValueError,match="PERSISTED_"):
        sut.artifact(run,L,"estimator",p,cut,"LOW")


@pytest.mark.parametrize("marker",["INPUT_QUALIFICATION.json","DESIGN_FREEZE.json"])
def test_qualification_never_overwrites_existing_or_freeze(tmp_path,monkeypatch,marker):
    root=tmp_path/"qualify";root.mkdir();path=root/marker;path.write_bytes(b"PRESERVE")
    def forbidden(*args):raise AssertionError("No data read before preservation check")
    monkeypatch.setattr(sut.old,"read_inputs",forbidden)
    with pytest.raises(FileExistsError,match="PRESERVE_EXISTING_INPUT_QUALIFICATION"):
        sut.qualify(root,{},None)
    assert path.read_bytes()==b"PRESERVE"


def test_synthetic_qualification_stores_all_original_mature_keys(tmp_path,monkeypatch):
    root=tmp_path/"qualification";root.mkdir()
    dates=["2021-08-02","2022-01-03","2022-07-01","2023-01-03","2023-07-03","2024-01-02","2024-07-01"]
    source=frame(dates)
    monkeypatch.setattr(sut.old,"read_inputs",lambda *a:(source.copy(),source.copy()))
    receipt=sut.qualify(root,dict(features=["x"]),None)
    assert receipt["fit_calls"]==receipt["test2026_rows_read"]==receipt["F_accesses"]==0
    assert len(receipt["training"])==7 and len(receipt["validation"])==6
    for cut,info in receipt["training"].items():
        expected=sut.full_pool(source,cut)
        assert info["rows"]==len(expected) and info["key_digest"]==sut.key_digest(expected)
        assert np.isclose(info["sum_weights"],len(expected))
        assert Path(info["keys"]["path"]).is_file()
    for info in receipt["validation"]:
        assert info["rows"]==21 and info["dates"]==1 and pd.Timestamp(info["max_label_end"])<pd.Timestamp(info["validation_end"])


def test_tiny_assembly_calls_existing_rank_owner_with_pandas(run,monkeypatch):
    (run/"predictions").mkdir()
    cid=sut.NEW_ROLES[0]
    panels=[]
    for year in sut.YEARS:
        part=frame([f"{year}-01-03"])[sut.KEYS].copy()
        part["score"]=-part.security_uid.astype(float)
        part["candidate_id"]=cid;part["source_kind"]="MODEL_OOF";part["source_cutoff"]=pd.Timestamp(f"{year}-01-01")
        panels.append(part)
    raw=pd.concat(panels,ignore_index=True)[sut.KEYS]
    rawpath=run/"raw.parquet";raw.to_parquet(rawpath,index=False)
    d=dict(score_reuse={sut.evidence.RAW:dict(path=str(rawpath),sha256=sut.sha(rawpath))})
    L=ledger(run);sut.putj(run/"FIT_LEDGER.json",L)
    model=run/"model.bin";model.write_bytes(b"SYNTHETIC_MODEL_NEVER_LOADED")
    for year,part in zip(sut.YEARS,panels):
        path=run/f"predictions/native_{cid}_{year}.parquet";part.to_parquet(path,index=False)
        sut.putj(path.with_suffix(".json"),dict(role=cid,year=year,selected_capacity="LOW",selection_lineage=None,
            prediction=dict(path=str(path),sha256=sut.sha(path)),fit=dict(path=str(model),sha256=sut.sha(model)),
            physical_id=sut.node_id("estimator",sut.PARADIGMS[0],f"{year}-01-01","LOW"),
            design_freeze_sha256=sut.sha(run/"DESIGN_FREEZE.json")))
    monkeypatch.setattr(sut,"checked",lambda root:({},d))
    monkeypatch.setattr(sut,"bind_references",lambda *a:{})
    original=sut.prior.rank_panel;calls=[]
    def rank_owner(panel,pandas):
        assert pandas is pd
        calls.append(len(panel))
        return original(panel,pandas)
    monkeypatch.setattr(sut.prior,"rank_panel",rank_owner)
    sut.assemble(run)
    result=sut.readj(run/"SCORE_ASSEMBLY.json")
    assert calls==[63] and result["complete_candidates"]==[cid]
    assert len(result["failed_or_untestable"])==10 and result["forecast2026_rows"]==0
    panel=pd.read_parquet(result["score_paths"][cid]["path"])
    assert panel.groupby("signal_date")["rank"].max().eq(21).all()


def inner_record_fixture(run):
    start,end="2022-01-01","2022-07-01"
    dates=pd.DatetimeIndex(["2022-01-03","2022-01-04"])
    daily=pd.DataFrame(dict(signal_date=dates,top20_mean_utility=[.1,-.05]))
    path=run/"inner-daily.parquet";daily.to_parquet(path,index=False)
    keypath=run/"inner-key-fixture.bin";keypath.write_bytes(b"SYNTHETIC_VALIDATION_KEYS")
    model=run/"inner-model-fixture.bin";model.write_bytes(b"SYNTHETIC_MODEL_NEVER_LOADED")
    q=dict(keys=dict(path=str(keypath),sha256=sut.sha(keypath)),dates=2,max_label_end="2022-01-05")
    fit=dict(artifact=dict(path=str(model),sha256=sut.sha(model)),
        physical_id=sut.node_id("estimator",sut.PARADIGMS[0],start,"LOW"))
    row=dict(status="COMPLETE",design_freeze_sha256=sut.sha(run/"DESIGN_FREEZE.json"),
        validation_keys=copy.deepcopy(q["keys"]),fit_cutoff=start,validation_end=end,
        max_label_end=q["max_label_end"],fit=copy.deepcopy(fit["artifact"]),physical_id=fit["physical_id"],
        daily=dict(path=str(path),sha256=sut.sha(path)),dates=2,
        sum_daily_utility=float(daily.top20_mean_utility.sum()),
        mean_daily_utility=float(daily.top20_mean_utility.mean()))
    return row,q,start,end,fit,dates,daily


def test_inner_resume_record_valid_and_hash_bound(run):
    row,q,start,end,fit,dates,_=inner_record_fixture(run)
    assert sut.check_inner_record(row,run,q,start,end,fit,dates) is None


@pytest.mark.parametrize("mutation",["freeze","keys","model","daily_bytes","sum","future_date","outside_inner_fold"])
def test_inner_resume_lineage_and_cached_utility_cannot_change(run,mutation):
    row,q,start,end,fit,dates,daily=inner_record_fixture(run)
    if mutation=="freeze":row["design_freeze_sha256"]="0"*64
    elif mutation=="keys":row["validation_keys"]["sha256"]="0"*64
    elif mutation=="model":row["fit"]["sha256"]="0"*64
    elif mutation=="daily_bytes":Path(row["daily"]["path"]).write_bytes(b"CHANGED_AFTER_RECEIPT")
    elif mutation=="sum":row["sum_daily_utility"]+=.1
    else:
        daily.loc[1,"signal_date"]=pd.Timestamp("2026-01-02" if mutation=="future_date" else "2022-08-01")
        daily.to_parquet(row["daily"]["path"],index=False)
        row["daily"]["sha256"]=sut.sha(row["daily"]["path"])
        dates=pd.DatetimeIndex(daily.signal_date)
    with pytest.raises(ValueError):
        sut.check_inner_record(row,run,q,start,end,fit,dates)
