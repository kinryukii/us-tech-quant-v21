from copy import deepcopy
from types import SimpleNamespace
import json,hashlib
import pandas as pd
import pytest
from scripts.research.a2.inference import frozen_a94_values as c

def build(tmp_path,monkeypatch,n=100,variant=None):
    variant=variant or "TOP"+str(n);features=list(c.values.feature_binding()["features"])
    dates=["2026-01-02","2026-01-05"];names={d:["S%03d"%i for i in range(j,n+j)] for j,d in enumerate(dates)}
    rows=[dict(signal_date=pd.Timestamp(d),ticker=t,security_id="SID_"+t,feature_available=True,input_present=True,
        feature_source=next(iter(c.values.SOURCES)),**{f:float(i)/100 for f in features}) for d in dates for i,t in enumerate(names[d])]
    base=pd.DataFrame(rows);extra=base.iloc[[0]].copy();extra["signal_date"]=pd.Timestamp(dates[1]);frame=pd.concat([base,extra],ignore_index=True)
    def write(name,obj):
        p=tmp_path/(name+".json");p.write_text(json.dumps(obj,sort_keys=True),encoding="utf8")
        return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    leaf=lambda name:write(name,{"synthetic":name})
    source=leaf("source");universe=leaf("universe");pool=leaf("pool");support=leaf("support")
    original=dict(origin="FROZEN_RAW_CONSENSUS_SENSITIVITY_POOL",universe_variant="CONSENSUS_SENSITIVITY",pool_variant_id=variant,n=n,
        cohort_count=24 if variant.startswith("LOO_") else 25,excluded_manager="akre" if variant.startswith("LOO_") else None,
        universe_source_ref=universe,source_manifest_ref=universe,physical_pool_ref=pool,source_ref=source,
        feature_order_sha256=c.values.digest(features),sessions={d:c.pool_session_commitment(base[base.signal_date.eq(pd.Timestamp(d))],features) for d in dates})
    first={}
    for d in dates:
        for t in names[d]:first.setdefault(t,d)
    proof=dict(original,origin="CONSENSUS_SENSITIVITY_ASOF_HOLDING_VALUE_SUPPORT",role="OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY",
        domain_policy="CURRENT_POOL_UNION_PREVIOUSLY_EFFECTIVE_MEMBERS_ASOF",no_future_first_membership=True,no_new_buy_eligibility=True,
        daily_top100_sessions=deepcopy(original["sessions"]),daily_top100_tickers=names,first_membership_by_ticker=first)
    proof.pop("source_ref");proof.pop("physical_pool_ref")
    manifest=dict(task_id=c.profile.REPAIR_TASK,pool_variant_id=variant,physical_support_ref=support,physical_daily_top100_ref=pool,
        source_features_ref=leaf("features"),source_dated_identity_ref=leaf("identity"),source_flags_ref=leaf("flags"),
        commitment_owner_source_ref=leaf("historical_source_bytes"))
    raw=dict(application_pool_origin=original["origin"],universe_variant="CONSENSUS_SENSITIVITY",universe_source_ref=universe,
        ordered_32_features=features,n=n)
    auth=SimpleNamespace(task_id=c.profile.REPAIR_TASK,provenance_json="")
    contract=dict(raw_selector_binding=raw,full_pit32_pool=original)
    loader=SimpleNamespace(authority=auth,_check=lambda:contract)
    def freeze(x=frame):
        proof["sessions"]={str(pd.Timestamp(d).date()):c.pool_session_commitment(g,features) for d,g in x.groupby("signal_date",sort=False)}
        manifest["value_holding_support"]=deepcopy(proof);mr=write("manifest",manifest)
        qualified=dict(proof,support_manifest_ref=mr,source_ref=source)
        contract["full_pit32_value_support"]=deepcopy(qualified)
        qr=write("qualification",dict(full_pit32_pool=original,full_pit32_value_support=qualified))
        auth.provenance_json=json.dumps(dict(source_qualification_ref=qr,source_refs={"action_inputs":source}))
    monkeypatch.setattr(c.profile,"_roots",lambda:(tmp_path.resolve(),))
    def valid_dates(a,ds):
        assert a is auth
        assert pd.DatetimeIndex(ds).min()>=pd.Timestamp(dates[0]) and pd.DatetimeIndex(ds).max()<=pd.Timestamp(dates[-1])
    monkeypatch.setattr(c.admission,"validate_descriptive_input_dates",valid_dates);freeze()
    return SimpleNamespace(loader=loader,frame=frame,proof=proof,original=original,manifest=manifest,contract=contract,auth=auth,freeze=freeze,write=write)

@pytest.mark.parametrize("n,variant",[(100,"TOP100"),(200,"TOP200"),(300,"TOP300"),(400,"TOP400"),(100,"LOO_akre_TOP100")])
def test_each_scoped_size_preserves_current_rows_and_offpool_holding(tmp_path,monkeypatch,n,variant):
    x=build(tmp_path,monkeypatch,n,variant);before=x.frame.copy(deep=True);out=c.bind_value_support(x.loader,x.frame)
    pd.testing.assert_frame_equal(out.frame,before);pd.testing.assert_frame_equal(x.frame,before)
    assert out.frame.groupby("signal_date").size().tolist()==[n,n+1]

@pytest.mark.parametrize("kind",["future_member","changed_current_value","missing_current_row","early_first","missing_day","short_current_members","buy_flag","wrong_manifest_task","wrong_manifest_pool","swapped_proof","source_mutation","old_authority","unsupported_n"])
def test_repair_support_rejects_source_or_causal_drift(tmp_path,monkeypatch,kind):
    x=build(tmp_path,monkeypatch,200);f=x.frame.copy()
    if kind=="future_member":
        e=f.loc[f.ticker.eq("S200")].copy();e["signal_date"]=pd.Timestamp("2026-01-02");f=pd.concat([f,e],ignore_index=True)
    elif kind=="changed_current_value":f.loc[0,"ret_1d"]+=1
    elif kind=="missing_current_row":f=f.drop(index=0)
    elif kind=="early_first":x.proof["first_membership_by_ticker"]["S200"]="2026-01-02"
    elif kind=="missing_day":f=f[f.signal_date.eq(pd.Timestamp("2026-01-02"))]
    elif kind=="short_current_members":x.proof["daily_top100_tickers"]["2026-01-02"].pop()
    elif kind=="buy_flag":f["is_max_group"]=True
    elif kind=="wrong_manifest_task":x.manifest["task_id"]=c.profile.ALL_TASK
    elif kind=="wrong_manifest_pool":x.manifest["physical_daily_top100_ref"]=x.manifest["physical_support_ref"]
    elif kind=="old_authority":x.auth.task_id=c.profile.ALL_TASK
    elif kind=="unsupported_n":x.contract["raw_selector_binding"]["n"]=500
    x.freeze(f)
    if kind=="swapped_proof":x.contract["full_pit32_value_support"]["pool_variant_id"]="TOP300"
    if kind=="source_mutation":
        from pathlib import Path
        Path(x.manifest["commitment_owner_source_ref"]["path"]).write_text("changed",encoding="utf8")
    with pytest.raises((ValueError,AssertionError)):c.bind_value_support(x.loader,f)

@pytest.mark.parametrize("field",["no_future_first_membership","no_new_buy_eligibility"])
def test_even_rehashed_weakened_support_claim_rejected(tmp_path,monkeypatch,field):
    x=build(tmp_path,monkeypatch,200);x.proof[field]=False;x.freeze()
    with pytest.raises(ValueError,match="VALUE_SUPPORT_ROLE_REQUIRED"):c.bind_value_support(x.loader,x.frame)
