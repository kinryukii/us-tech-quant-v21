"""R10 mechanism acceptance: pure or temporary synthetic fixtures only.
The physical worker is stubbed; no real fits, data, accounts or provider reads.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_mechanism as m


def config():
    return {"scientific_identity":m.IDENTITY,**m.AUTHORITY,"account_authorized":False,
            "source_activated":False,"model_specifications":{"source_pins":{}},"dependency_paths":[]}


def local_frame():
    return pd.DataFrame({"signal_date":pd.to_datetime(["2024-02-01","2024-02-01","2024-02-02"]),
                         "label_mature_date":pd.to_datetime(["2024-02-09"]*3),"label_qualified":[True]*3,
                         "target":[.2,-.1,.3],"reference_action":[1.,1.,0.],"base_weight":[.5,.5,1.]})


def patch_io(monkeypatch):
    def save(path,value):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        Path(path).write_text(json.dumps(m.clean(value),default=str),encoding="utf-8")
    def append(path,event):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with Path(path).open("a",encoding="utf-8") as f:f.write(json.dumps(event)+"\n")
    monkeypatch.setattr(m,"save",save);monkeypatch.setattr(m.fit_owner,"_append",append)


def test_paired_binary_regret_date_balanced_with_frozen_mass():
    daily,metric=m.local_regret(local_frame(),[0,1,1])
    assert daily.regret.tolist()==pytest.approx([.15,0])
    assert daily.improvement.tolist()==pytest.approx([-.1,.3])
    assert metric["date_balanced_improvement"]==pytest.approx(.1)
    assert metric["coverage"]==1
    assert metric["metric_role"]=="LOCAL_CONDITIONAL_BINARY_ACTION_NOT_ACCOUNT_OR_FULL_ORACLE"


def test_partial_action_regret_and_unknown_pair_remain_conditional():
    f=local_frame();f.loc[1,"label_qualified"]=False
    daily,metric=m.local_regret(f,[.5,1,1])
    assert metric["coverage"]==pytest.approx(2/3)
    assert daily.regret.iloc[0]==pytest.approx(.1)
    assert "NOT_ACCOUNT_OR_FULL_ORACLE" in metric["metric_role"]
    assert metric.get("full_pair_oracle_qualified") is not True


@pytest.mark.parametrize("bad",[-.1,1.1,2.])
def test_action_outside_unit_interval_rejected(bad):
    with pytest.raises(ValueError):m.local_regret(local_frame(),[bad,0,1])


@pytest.mark.parametrize("bad",[0.,-1.,np.nan,np.inf])
def test_invalid_mass_rejected(bad):
    f=local_frame();f.loc[0,"base_weight"]=bad
    with pytest.raises(ValueError):m.local_regret(f,[0,1,1])


def test_unbound_maturity_is_fail_closed():
    f=local_frame();f.loc[0,"label_mature_date"]=pd.NaT
    _,metric=m.local_regret(f,[0,1,1])
    assert metric["legal_rows"]==2


@pytest.mark.parametrize("clock",["signal_date","label_mature_date"])
def test_future_clock_regret_rejected(clock):
    f=local_frame();f.loc[0,clock]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):m.local_regret(f,[0,1,1])


@pytest.mark.parametrize("flag",list(m.AUTHORITY)+["account_authorized","source_activated"])
@pytest.mark.parametrize("mode",["opposite","null","missing"])
def test_authority_requires_explicit_literal_flags(flag,mode):
    f=config()
    if mode=="opposite":f[flag]=not f[flag]
    elif mode=="null":f[flag]=None
    else:f.pop(flag)
    with pytest.raises(ValueError):m.authority_check(f)


def test_role_weights_date_and_action_role_balance_without_y():
    f=local_frame();f["action_type"]=[0,1,0]
    w=m.role_weights(f)
    np.testing.assert_allclose(w,[.75,.75,1.5])
    f.target=-100*f.target
    np.testing.assert_array_equal(w,m.role_weights(f))


def test_mature_train_all_legal_rows_no_cap_and_strict_own_clock():
    n=12021
    f=pd.DataFrame({"signal_date":[pd.Timestamp("2023-04-01")]*n,"sample_id":[str(i) for i in range(n)],
                    "label_mature_date":[pd.Timestamp("2023-04-08")]*n,"label_qualified":True,"target":.1})
    assert len(m.mature_train(f,"2024-01-01"))==n
    f.loc[0,"label_mature_date"]=pd.Timestamp("2024-01-01")
    f.loc[1,"signal_date"]=pd.Timestamp("2024-01-01")
    assert len(m.mature_train(f,"2024-01-01"))==n-2


def test_physical_failure_charges_budget_and_never_refits(tmp_path,monkeypatch):
    patch_io(monkeypatch);design=config();(tmp_path/"FROZEN_DESIGN.json").write_text(json.dumps(design),encoding="utf-8")
    called=[]
    def worker(operation,model_id,x,payload,dates,*args,**kw):
        m.fit_owner._component_start(kw["log"],kw["auth"],kw["prior"],model_id,kw["year"],"SYNTHETIC_TEST_ONLY",kw["tuple_sha"])
        kw["receipt"]["fit_units"]=1;called.append(model_id)
        raise RuntimeError("SYNTHETIC_PLANNED_FAILURE_NO_NATIVE_FIT")
    monkeypatch.setattr(m.fit_owner,"_fit_job",worker)
    spec=dict(slot_id="FIXTURE",family="ridge",capacity="LOW",seed=1,year=2024,bucket="ACTION_VALUE")
    x=np.ones((3,2));y=np.arange(3.);w=np.ones(3);d=pd.date_range("2023-01-02",periods=3).to_numpy()
    model,r=m.physical_job(tmp_path,design,spec,x,y,w,d,["a","b"])
    assert model is None and r["status"]=="FAILED" and r["fit_units"]==1
    model,again=m.physical_job(tmp_path,design,spec,x,y,w,d,["a","b"])
    assert len(called)==1 and again["scientific_tuple_sha256"]==r["scientific_tuple_sha256"]
    starts=[e for e in m.fit_owner._events(tmp_path/"FIT_LOG.jsonl") if e["event"]=="FIT_STARTED"]
    assert sum(e["fit_units"] for e in starts)==1
    with pytest.raises(ValueError,match="IDENTITY_CHANGED"):
        m.physical_job(tmp_path,design,spec,x,y+1,w,d,["a","b"])


@pytest.mark.parametrize("bucket,amount",[("ACTION_VALUE",420),("SHARED_RISK_LEARNED",220)])
def test_budget_before_worker_component_start(tmp_path,monkeypatch,bucket,amount):
    patch_io(monkeypatch);log=tmp_path/"FIT_LOG.jsonl"
    log.write_text(json.dumps({"event":"FIT_STARTED","fit_units":amount,"budget_bucket":bucket})+"\n",encoding="utf-8")
    auth={"max_fit_units":1200,"max_new_bucket_fit_units":m.CAPS[bucket],"budget_bucket":bucket}
    with pytest.raises(RuntimeError,match="BUCKET_EXHAUSTED"):
        m.fit_owner._component_start(log,auth,0,"FIXTURE",2024,"SYNTHETIC_NO_FIT","tuple")
    assert len(m.fit_owner._events(log))==1


def test_global1200_before_worker_start(tmp_path,monkeypatch):
    patch_io(monkeypatch);log=tmp_path/"FIT_LOG.jsonl"
    log.write_text(json.dumps({"event":"FIT_STARTED","fit_units":1200,"budget_bucket":"OTHER"})+"\n",encoding="utf-8")
    with pytest.raises(RuntimeError,match="CUMULATIVE_FIT_BUDGET_EXHAUSTED"):
        m.fit_owner._component_start(log,{"max_fit_units":1200,"budget_bucket":"ACTION_VALUE"},0,"FIXTURE",2024,"NO_FIT","tuple")


def test_physical_job_rejects_bad_authority_before_worker_or_paths(tmp_path,monkeypatch):
    monkeypatch.setattr(m.fit_owner,"_fit_job",lambda *a,**k:pytest.fail("worker called"))
    bad=config();bad["account_qualified"]=True
    with pytest.raises(ValueError):
        m.physical_job(tmp_path,bad,{"slot_id":"NO_WRITE","year":2024,"bucket":"ACTION_VALUE"},np.ones((1,1)),np.ones(1),np.ones(1),np.array(["2023-01-01"]),["a"])
    assert list(tmp_path.iterdir())==[]


def test_scaler_shared_across_capacity_and_seeds_no_extra_ensemble_fit(tmp_path,monkeypatch):
    from scripts.research.a2.training import stateful_mechanism_models as models
    patch_io(monkeypatch);scaler_calls=[];jobs=[]
    class IdentityScaler:
        def transform(self,x):return x
    def scaler(*a,**kw):
        scaler_calls.append(1);return IdentityScaler(),{"status":"TRAINED","fit_units":1}
    def job(run,design,spec,x,target,weights,dates,features,**kw):
        jobs.append((spec["family"],spec["capacity"],spec["seed"],len(x)))
        path=tmp_path/(spec["slot_id"]+".json")
        return {"fixture":True},{**spec,"status":"TRAINED","fit_units":1,"receipt_path":str(path)}
    def publish(run,spec,frame,pred):
        path=tmp_path/(spec["slot_id"]+".parquet")
        return {"path":str(path),"rows":len(frame)}
    monkeypatch.setattr(m,"scaler_job",scaler);monkeypatch.setattr(m,"physical_job",job)
    monkeypatch.setattr(models,"predict",lambda model,x:{"mean":np.zeros(len(x))})
    monkeypatch.setattr(m,"publish_prediction",publish);monkeypatch.setattr(m,"update_progress",lambda *a:None)
    f=pd.DataFrame({"signal_date":list(pd.bdate_range("2023-02-01",periods=30))+list(pd.bdate_range("2024-02-01",periods=8)),
                    "sample_id":[str(i) for i in range(38)],"label_mature_date":list(pd.bdate_range("2023-02-02",periods=30))+list(pd.bdate_range("2024-02-02",periods=8)),
                    "label_qualified":True,"target":.01,"reference_action":1.,"base_weight":1.,"fixture_feature":1.})
    receipt,pub=m.model_role(tmp_path,config(),f,["fixture_feature"],bucket="ACTION_VALUE",group="ENTRY",horizon="MEAN",year=2024,families=["ridge","mlp"],capacities=list(m.CAPACITIES))
    assert len(scaler_calls)==1
    assert len(jobs)==3*(1+3)
    assert len(pub)==6
    assert all(p["dependency_role"]=="ZERO_FIT_EQUAL_ENSEMBLE_NO_BEST_SEED" for p in pub)
    assert len(receipt)==13


def series_fixture():
    dates=pd.bdate_range("2024-02-01",periods=60).append(pd.bdate_range("2025-02-03",periods=60))
    return dates,np.random.default_rng(8).normal(0,.02,len(dates))


def test_max_t_two_formal_years_with_shared_dates_and_determinism():
    dates,noise=series_fixture()
    a=pd.Series(.1+noise,index=dates);b=pd.Series(.12+noise,index=dates)
    result=m.simultaneous_bounds({"a":a,"b":b},bootstrap=199,block=20,seed=1)
    again=m.simultaneous_bounds({"a":a,"b":b},bootstrap=199,block=20,seed=1)
    assert result==again
    for r in result.values():
        assert r["status"]=="MECHANISM_SUPPORTED" and r["ci_status"]=="PASS"
        assert r["yearly_improvement"]["2023"] is None
        assert r["dates"]==120 and r["independent_holdout"] is False
    assert result["a"]["critical_max_t"]==result["b"]["critical_max_t"]


def test_2023_prefix_cannot_rescue_negative2024():
    dates,noise=series_fixture()
    values=np.where(dates.year==2024,-.01,.1)+noise*.1
    prefix=pd.Series(100.,index=pd.bdate_range("2023-10-02",periods=60))
    s=pd.concat([prefix,pd.Series(values,index=dates)])
    result=m.simultaneous_bounds({"a":s},bootstrap=199,block=20,seed=2)["a"]
    assert result["status"]=="NO_SUPPORT"
    assert result["yearly_improvement"]["2023"] is None
    assert result["pooled_improvement"]<.1


def test_missing_one_formal_year_not_supported():
    dates,noise=series_fixture();s=pd.Series(.1+noise[:60],index=dates[:60])
    r=m.simultaneous_bounds({"a":s},bootstrap=99,block=10)["a"]
    assert r["status"]=="NO_SUPPORT" and r["yearly_improvement"]["2025"] is None


def test_future_ci_input_rejected_before_year_filter():
    s=pd.Series([1.],index=pd.DatetimeIndex(["2026-01-01"]))
    with pytest.raises(ValueError):m.simultaneous_bounds({"future":s},bootstrap=9)


def test_insufficient_ci_not_promoted():
    s=pd.Series(np.arange(10)/100,index=pd.bdate_range("2025-01-02",periods=10))
    r=m.simultaneous_bounds({"small":s},bootstrap=19)["small"]
    assert r["ci_status"]=="CI_NOT_TESTABLE" and r["status"]=="NO_SUPPORT"


def oracle_frame():
    f=pd.DataFrame({"signal_date":pd.to_datetime(["2024-03-01"]*3),"ticker":["INCUMBENT"]*3,
                    "security_id":["SID_I"]*3,"sample_id":["SELL_I","PAIR_A_I","PAIR_B_I"],
                    "target":[.1,.2,.3],"label_qualified":[True]*3,
                    "label_mature_date":pd.to_datetime(["2024-03-12"]*3),"action_type":[0,1,1]})
    f["required_actionset_count"]=len(f)
    f["required_actionset_sha256"]=m.digest(sorted(f.sample_id.tolist()))
    return f


def test_full_incumbent_oracle_compares_complete_predeclared_actions():
    out=m.full_incumbent_oracle(oracle_frame(),[.4,.3,.1]).iloc[0]
    assert out.complete_action_labels and out.planned_actions==3 and out.known_action_labels==3
    assert out.chosen_sample_id=="SELL_I"
    assert out.oracle_advantage==pytest.approx(.3)
    assert out.realized_local_advantage==pytest.approx(.1)
    assert out.local_regret==pytest.approx(.2)
    assert out.status=="LOCAL_COMPLETE_ORACLE"


@pytest.mark.parametrize("kind",["label_unknown","missing_partner","missing_manifest","wrong_sha","wrong_count"])
def test_full_oracle_unknown_or_missing_pair_never_removed_from_actionset(kind):
    f=oracle_frame();scores=[.4,.3,.1]
    if kind=="label_unknown":f.loc[2,"label_qualified"]=False
    elif kind=="missing_partner":f=f.iloc[:2];scores=scores[:2]
    elif kind=="missing_manifest":f=f.drop(columns=["required_actionset_count","required_actionset_sha256"])
    elif kind=="wrong_sha":f["required_actionset_sha256"]="f"*64
    else:f["required_actionset_count"]=2
    out=m.full_incumbent_oracle(f,scores).iloc[0]
    assert not out.complete_action_labels and np.isnan(out.local_regret) and np.isnan(out.oracle_advantage)
    assert out.status.startswith("BLOCKED_")


def test_full_oracle_hold_reference_and_tie_is_key_deterministic():
    f=oracle_frame()
    hold=m.full_incumbent_oracle(f,[-1,-1,-1]).iloc[0]
    assert hold.chosen_sample_id=="HOLD_REFERENCE" and hold.realized_local_advantage==0
    assert hold.local_regret==pytest.approx(.3)
    first=m.full_incumbent_oracle(f,[.5,.5,.5]).iloc[0]
    shuffled=m.full_incumbent_oracle(f.iloc[[2,0,1]],[.5,.5,.5]).iloc[0]
    assert first.chosen_sample_id==shuffled.chosen_sample_id=="PAIR_A_I"


def test_full_oracle_future_maturity_is_rejected():
    f=oracle_frame();f.loc[2,"label_mature_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError):m.full_incumbent_oracle(f,[.4,.3,.1])


def test_full_oracle_unknown_sid_is_fail_closed():
    f=oracle_frame();f["security_id"]=None
    out=m.full_incumbent_oracle(f,[.4,.3,.1]).iloc[0]
    assert not out.complete_action_labels and np.isnan(out.local_regret)


def test_structured_actionset_metadata_is_label_independent_and_publication_preserved(tmp_path):
    from types import SimpleNamespace
    d=pd.Timestamp("2024-03-01")
    single=pd.DataFrame([{**{c:.1 for c in m.SINGLE},"signal_date":d,"ticker":"I","security_id":"SID_I",
                          "target":.1,"label_qualified":True,"label_mature_date":pd.Timestamp("2024-03-12")}])
    pair=pd.DataFrame([{**{c:.1 for c in m.PAIR},"signal_date":d,"entrant":"E"+str(j),"incumbent":"I","incumbent_sid":"SID_I",
                        "pair_id":"PAIR"+str(j),"pre_label_group_weight":.5,"supported_training_group_weight":.5,"target":.1*j,"label_qualified":True,
                        "label_mature_date":pd.Timestamp("2024-03-12")} for j in (1,2)])
    frames=SimpleNamespace(heads={5:{"ENTRY":single,"INCUMBENT":single,"CONTINUATION":single,"REPLACE":pair}})
    first=m.structured_action_frame(frames,5)["INCUMBENT"]
    assert first.required_actionset_count.eq(3).all()
    assert first.required_actionset_sha256.eq(m.digest(sorted(first.sample_id.astype(str)))).all()
    pair.loc[1,"label_qualified"]=False;pair.loc[1,"target"]=np.nan
    pair["supported_training_group_weight"]=[1.,0.]
    second=m.structured_action_frame(frames,5)["INCUMBENT"]
    assert second.sample_id.tolist()==first.sample_id.tolist()
    assert second.required_actionset_count.tolist()==first.required_actionset_count.tolist()
    assert second.required_actionset_sha256.tolist()==first.required_actionset_sha256.tolist()
    replacement=second.loc[second.action_type.eq(1)]
    assert replacement.pre_label_group_weight.tolist()==[.5,.5]
    assert replacement.base_weight.tolist()==[1.,0.]
    assert replacement.entrant_ticker.tolist()==["E1","E2"]
    assert pd.api.types.is_numeric_dtype(second.entrant)
    publication=m.publish_prediction(tmp_path,{"slot_id":"SYNTHETIC_ONLY"},second,{"mean":np.zeros(len(second))})
    stored=pd.read_parquet(publication["path"])
    assert len(stored)==3
    assert stored.required_actionset_count.eq(3).all()
    assert stored.required_actionset_sha256.tolist()==second.required_actionset_sha256.tolist()
