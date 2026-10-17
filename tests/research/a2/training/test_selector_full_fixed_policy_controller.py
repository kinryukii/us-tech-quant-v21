"""Synthetic-only full-selector controller contracts; no real input bodies."""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_full_fixed_policy as c


def vectors(days=("2023-05-03","2023-08-03","2024-02-05","2024-08-05","2025-02-05"),n=21):
    rows=[]
    for day in days:
        for i in range(n):
            row=dict(signal_date=pd.Timestamp(day),security_uid=f"UID{i:03}",ticker=f"T{i:03}",U_t_fingerprint="synthetic_"+day,feature_source_present=True)
            row.update({f:float(i+1)/100+j/1000 for j,f in enumerate(c.FEATURES)})
            rows.append(row)
    return pd.DataFrame(rows).sort_values(c.KEYS,kind="stable").reset_index(drop=True)


def labels(v):
    h=v[c.KEYS+["U_t_fingerprint"]].copy()
    h["target"]=np.where(np.arange(len(h))%2==0,.01,-.02)
    for day in (3,5,10,20):h["ER_"+str(day)+"D"]=h.target
    h["target_end_date"]=h.signal_date+pd.Timedelta(days=28)
    return h


class Reader:
    def __init__(self,v):
        self.v=v;self.keys=v[c.KEYS+["ticker","U_t_fingerprint"]].copy()
        self.h=labels(v);self.manifest={"input_sources":{"hlabels":{"path":"synthetic","sha256":"none"},"raw":{"path":"synthetic_raw","sha256":"none"}}}
        self.qualification={"training":{},"outer_sessions":v.signal_date.nunique(),"outer_rows":len(v)}
        for cut in c.CUTS:
            h=self.h.loc[self.h.signal_date.lt(cut)&self.h.target_end_date.lt(cut)]
            self.qualification["training"][cut]={"rows":len(h),"key_sha256":c.keys_digest(h)}
    def features(self,start,stop):return self.v.loc[self.v.signal_date.ge(start)&self.v.signal_date.lt(stop)].copy().reset_index(drop=True)
    def labels(self,start,cut):return self.h.loc[self.h.signal_date.ge(start)&self.h.signal_date.lt(cut)&self.h.target_end_date.lt(cut)].copy().reset_index(drop=True)


class MemoryJournal:
    def __init__(self):self.calls=[];self.blocks=[];self.aliases=[];self.design={"dag":{"nodes":c.learners.single_training_dag()["nodes"]}}
    def once(self,node,identity,work):
        seen=[]
        def entered(event=None):seen.append(event)
        result=work(entered);assert len(seen)==1
        self.calls.append((node,identity,seen[0]));return result
    def block(self,node,reason):self.blocks.append((node,reason))
    def alias(self,node,source,identity):self.aliases.append((node,source,identity));return True


@pytest.fixture
def journal(tmp_path,monkeypatch):
    monkeypatch.setattr(c,"assert_safe_output_path",lambda *a,**k:None)
    j=c._TaskLedger.__new__(c._TaskLedger);j.run=tmp_path;j.design={"dag":{"nodes":[]}}
    j.db=sqlite3.connect(":memory:")
    j.db.execute("CREATE TABLE nodes (node_id TEXT PRIMARY KEY,kind TEXT,status TEXT,entered INTEGER DEFAULT 0,identity TEXT,artifact TEXT,error TEXT)")
    j.db.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY,node_id TEXT,action TEXT,payload TEXT,utc TEXT)")
    yield j
    j.db.close()


def add(j,*nodes):
    j.db.executemany("INSERT INTO nodes(node_id,kind,status) VALUES (?,'SYNTHETIC','NAMED')",[(n,) for n in nodes]);j.db.commit()


def test_complete_resume_exact_identity_and_artifact(journal):
    add(journal,"model");calls=[]
    def fit(entered):entered({"operation":"synthetic"});calls.append(1);return {"value":7}
    assert journal.once("model",{"seed":1},fit)=={"value":7}
    assert journal.once("model",{"seed":1},fit)=={"value":7} and len(calls)==1
    with pytest.raises(ValueError,match="REUSE_IDENTITY"):journal.once("model",{"seed":2},fit)
    ref=json.loads(journal.status("model")["artifact"]);Path(ref["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError,match="ARTIFACT_CHANGED"):journal.once("model",{"seed":1},fit)


@pytest.mark.parametrize("status",["STARTED","FAILED","SOURCE_NOT_TESTABLE","BLOCKED_DEPENDENCY"])
def test_started_or_failed_no_retry(journal,status):
    add(journal,"model");journal.db.execute("UPDATE nodes SET status=? WHERE node_id='model'",(status,));journal.db.commit()
    assert journal.once("model",{},lambda entered:pytest.fail("scientific retry")) is None


def test_reservation_without_actual_callback_is_failed(journal):
    add(journal,"scaler");assert journal.once("scaler",{},lambda entered:dict(fake=True)) is None
    assert journal.status("scaler")["status"]=="FAILED" and journal.status("scaler")["entered"]==0


def test_mid_alias_no_additional_actual_entry(journal):
    add(journal,"selected","mid")
    def fit(entered):entered({"operation":"synthetic"});return {"coef":3}
    journal.once("selected",{"capacity":"MID"},fit)
    assert journal.alias("mid","selected",{"capacity":"MID"})
    assert journal.once("mid",{"capacity":"MID"},lambda e:pytest.fail("alias refit"))=={"coef":3}
    assert journal.status("mid")["entered"]==0
    assert journal.status("mid")["artifact"]==journal.status("selected")["artifact"]
    ref=json.loads(journal.status("mid")["artifact"]);Path(ref["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError,match="ALIAS_ARTIFACT"):journal.alias("mid","selected",{"capacity":"MID"})


def test_composite_actual_callbacks_and_exact_resume(journal):
    add(journal,"META_SCALER|a","META_MODEL|a");calls=[]
    def work(observe):
        for n in ("META_SCALER|a","META_MODEL|a"):observe({"node_id":n,"actual_operation_entered":True})
        calls.append(1);return ({"model":True},{"events":2})
    result=journal.composite_once(("META_SCALER|a","META_MODEL|a"),{"source":"OOF"},work)
    assert result==({"model":True},{"events":2})
    assert journal.composite_once(("META_SCALER|a","META_MODEL|a"),{"source":"OOF"},work)==result and len(calls)==1
    assert all(journal.status(n)["entered"]==1 for n in ("META_SCALER|a","META_MODEL|a"))


def test_partial_composite_cannot_replay_preprocessing(journal):
    add(journal,"scale","model");journal.db.execute("UPDATE nodes SET status='STARTED',entered=1 WHERE node_id='scale'");journal.db.commit()
    assert journal.composite_once(("scale","model"),{},lambda o:pytest.fail("partial replay")) is None
    assert journal.status("scale")["status"]=="STARTED" and journal.status("model")["status"]=="BLOCKED_DEPENDENCY"


def test_missing_composite_callback_is_failed(journal):
    add(journal,"scale","model")
    def work(observe):observe({"node_id":"scale","actual_operation_entered":True});return ({},{})
    assert journal.composite_once(("scale","model"),{},work) is None
    assert journal.status("scale")["status"]=="FAILED" and journal.status("model")["status"]=="BLOCKED_DEPENDENCY"


def test_worker_runtime_once_uses_cache_directory(tmp_path,monkeypatch):
    cfg={"cache_directory":str(tmp_path/"taskcache"),"cache_root":str(tmp_path/"differentroot")}
    (tmp_path/"run_config.json").write_text(json.dumps(cfg),encoding="utf-8");calls=[]
    monkeypatch.setattr(c,"assert_safe_output_path",lambda *a,**k:None)
    def rt(run):calls.append(1);return (cfg,*([None]*9))
    monkeypatch.setattr(c,"runtime",rt);c._WORKER_RUNTIMES.clear()
    assert c.worker_runtime(tmp_path) is c.worker_runtime(tmp_path)
    assert len(calls)==1 and (tmp_path/"taskcache/temp").exists()


def test_top20_full_u_negative_ties_and_no_nan_shrink():
    v=vectors(("2024-02-05",),25);v["score"]=-.1
    p=c.top20(v);assert p.loc[p.selected,"security_uid"].tolist()==[f"UID{i:03}" for i in range(20)]
    assert p.target_weight.sum()==pytest.approx(1.) and len(p)==25
    v.loc[24,"score"]=np.nan
    with pytest.raises(ValueError,match="NO_MODEL_DOMAIN_SHRINK"):c.top20(v)


def test_catalogue_66_and_exact738_ceiling():
    roles,contrasts=c.catalog();assert len(roles)==66 and len({r["policy_id"] for r in roles})==66 and len(contrasts)==95
    d=c.learners.single_training_dag();assert d["learned_operation_ceiling"]+d["hybrid_separate_ceiling"]["learned_operations"]==738
    assert d["counts"]["CALIBRATOR"]==10 and d["counts"]["META_MODEL"]==32 and d["counts"]["META_SCALER"]==28 and d["counts"]["META_TARGET_SCALE"]==14


def test_validation_native_point_mse_and_day_weights():
    v=vectors(("2023-08-03","2023-09-04"),21);h=labels(v);bank=v[c.KEYS].copy();bank["native_point"]=h.target+.03;bank["score"]=np.arange(len(bank))
    r=c._validation_record("RIDGE","2023-07-01","2024-01-01","MID",bank,h,v)
    assert r["native_loss"]=="MSE" and r["sum_loss"]==pytest.approx(2*.03**2) and r["dates"]==2


@pytest.mark.parametrize("role",["LOGIT","LINEAR_SVM"])
def test_validation_uses_native_probability_brier(role):
    v=vectors(("2023-08-03",),21);h=labels(v);bank=v[c.KEYS].copy();bank["native_prob"]=.5;bank["score"]=999
    r=c._validation_record(role,"2023-07-01","2024-01-01","LOW",bank,h,v)
    assert r["sum_loss"]==pytest.approx(.25) and r["native_loss"]=="BRIER_SIGN"


@pytest.mark.parametrize("role",["PAIRWISE_RANKER","LAMBDAMART","LISTWISE_MLP"])
def test_native_rank_validation_rejects_partial_mature_day(role):
    v=vectors(("2023-08-03",),21);h=labels(v).iloc[:-1];bank=v[c.KEYS].copy();bank["score"]=0.
    with pytest.raises(ValueError,match="MATURE_FULL_DAY"):c._validation_record(role,"2023-07-01","2024-01-01","MID",bank,h,v)


def test_future_validation_label_cannot_select_capacity():
    v=vectors(("2023-08-03",));h=labels(v);h.target_end_date=pd.Timestamp("2024-01-01");bank=v[c.KEYS].copy();bank["native_point"]=0.
    with pytest.raises(ValueError,match="PAST_MATURE_LABELS"):c._validation_record("RIDGE","2023-07-01","2024-01-01","MID",bank,h,v)


def test_capacity_all_required_folds_low_tie():
    records=[dict(cutoff=cut,capacity=cap,status="COMPLETE",sum_loss=1.,dates=1) for cut in ("2024-01-01","2024-07-01") for cap in c.learners.CAPACITIES]
    chosen,_=c._choose_capacity(records,("2024-01-01","2024-07-01"));assert chosen=="LOW"
    records[0]["status"]="TRAINING_FAILED";chosen,_=c._choose_capacity(records,("2024-01-01","2024-07-01"));assert chosen=="MID"


def test_platt_ten_actual_nodes_past_oof_only(tmp_path):
    v=vectors(("2023-05-03",),21);reader=Reader(v);h=v[c.KEYS].copy()
    h["source_kind"]="MODEL_OOF";h["source_cutoff"]=pd.Timestamp("2023-04-01");h["max_train_label_end"]=pd.Timestamp("2023-03-01");h["cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE";h["native_margin"]=np.linspace(-1,1,len(h))
    j=MemoryJournal()
    for cut in c.CUTS[1:]:
        for cap in c.learners.CAPACITIES if cut!=c.CUTS[-1] else ("MID",):
            model=c._platt(tmp_path,j,reader,cut,cap,[h],logical="SELECTED" if cut==c.CUTS[-1] else "")
            assert model is not None
    assert len(j.calls)==10 and all(a[0].startswith("PLATT|LINEAR_SVM|") for a in j.calls)
    assert all(a[2]["operation"].startswith("past_full_OOF_Platt") for a in j.calls)
    h.source_kind="IN_SAMPLE"
    with pytest.raises(ValueError,match="GENUINE_PAST_OOF"):c._platt(tmp_path,j,reader,"2024-01-01","MID",[h])


def test_platt_cannot_fit_one_class_or_raw_fallback(tmp_path):
    v=vectors(("2023-05-03",));reader=Reader(v);reader.h.target=.02;j=MemoryJournal();h=v[c.KEYS].copy()
    h["source_kind"]="MODEL_OOF";h["source_cutoff"]=pd.Timestamp("2023-04-01");h["max_train_label_end"]=pd.Timestamp("2023-03-01");h["cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE";h["native_margin"]=0.
    assert c._platt(tmp_path,j,reader,"2023-07-01","LOW",[h]) is None and not j.calls


def test_prediction_artifacts_exact_reuse_and_clock_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(c,"assert_safe_output_path",lambda *a,**k:None)
    v=vectors(("2024-02-05",));v["score"]=.01;path=tmp_path/"predictions/a.parquet"
    r=c._store_frame(tmp_path,path,v,{"seed":1});assert c._store_frame(tmp_path,path,v,{"seed":1})==r
    with pytest.raises(ValueError,match="EXACT_REUSE_CHANGED"):c._store_frame(tmp_path,path,v,{"seed":2})
    calls=[]
    original=pd.read_parquet
    def guard(path,sha,clocks):calls.append("footer")
    def read(*args,**kwargs):assert calls==["footer"];calls.append("body");return original(*args,**kwargs)
    monkeypatch.setattr(c,"guard_parquet",guard);monkeypatch.setattr(pd,"read_parquet",read)
    body,_=c._load_frame(path);assert c._frame_hash(body)==r["frame_sha256"] and calls==["footer","body"]


def test_prediction_physical_2026_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(c,"assert_safe_output_path",lambda *a,**k:None)
    v=vectors(("2026-01-02",));v["score"]=0.
    with pytest.raises(ValueError,match="PHYSICAL_PRE2026"):c._store_frame(tmp_path,tmp_path/"bad.parquet",v,{})


def test_full_domain_success_rejects_missing_uid_and_wrong_fingerprint():
    v=vectors(("2023-08-03","2024-02-05","2025-02-05"));reader=Reader(v);v["score"]=0.;p=c.top20(v)
    assert c.validate_policy_domain(p,reader)
    with pytest.raises(ValueError,match="IDENTICAL_FULL_U_DOMAIN"):c.validate_policy_domain(p.iloc[:-1],reader)
    p.loc[0,"U_t_fingerprint"]="wrong"
    with pytest.raises(ValueError,match="IDENTICAL_FULL_U_DOMAIN"):c.validate_policy_domain(p,reader)


def test_annual_2024_uses_jan_model_and_2025_mid_alias(tmp_path,monkeypatch):
    v=vectors(("2022-08-03","2023-05-03","2023-08-03","2024-02-05","2024-08-05","2025-02-05"));reader=Reader(v);j=MemoryJournal();calls=[];stored={};published={}
    def bundle(run,journal,reader,pool,role,cut,cap,logical="",rt=None,alias_from=None):
        calls.append((cut,cap,logical,alias_from));return {"role":role,"capacity":cap,"cutoff":cut,"training_keys":"synthetic","max_train_label_end":str(pd.Timestamp(cut)-pd.Timedelta(days=1))}
    def predict(b,vectors,calibrator=None):
        p=vectors[c.KEYS+["ticker","U_t_fingerprint"]].copy();p["score"]=0.;p["native_point"]=0.;p["source_cutoff"]=pd.Timestamp(b["cutoff"]);p["source_capacity"]=b["capacity"];p["source_kind"]="MODEL_OOF";p["max_train_label_end"]=pd.Timestamp(b["max_train_label_end"]);p["cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE";return p
    def store(run,path,frame,identity):stored[str(path)]=frame.copy();return {"path":str(path),"sha256":"synthetic"}
    monkeypatch.setattr(c,"_bundle",bundle);monkeypatch.setattr(c,"_predict",predict);monkeypatch.setattr(c,"_store_frame",store)
    monkeypatch.setattr(c,"_validation_record",lambda role,cut,end,cap,*a:dict(cutoff=cut,end=end,capacity=cap,status="COMPLETE",sum_loss=0. if cap=="MID" else 1.,dates=1))
    monkeypatch.setattr(c,"_publish_policy",lambda run,reader,role,forecast,raw:published.setdefault(role,forecast.copy()))
    c._train_role(tmp_path,j,reader,(None,)*10,"RIDGE",v)
    annual=stored[str(tmp_path/"predictions/annual_native/RIDGE_2024.parquet")]
    assert annual.source_cutoff.eq(pd.Timestamp("2024-01-01")).all() and set(annual.signal_date.dt.month)=={2,8}
    assert ("2025-01-01","MID","","SELECTED") in calls
    assert str(tmp_path/"predictions/fixed_mid/RIDGE_2025.parquet") in stored
    assert set(published["RIDGE"].signal_date.dt.year)=={2024,2025}


def test_fusion_inputs_exact_six_mid_past_oof_and_all_mature_keys(tmp_path,monkeypatch):
    v=vectors(("2023-08-03","2024-02-05","2024-08-05"));reader=Reader(v)
    def load(path):
        cut=Path(path).stem.split("_")[0];end=c.CUTS[c.CUTS.index(cut)+1];p=reader.features(cut,end)[c.KEYS+["ticker","U_t_fingerprint"]].copy()
        p["source_kind"]="MODEL_OOF";p["source_cutoff"]=pd.Timestamp(cut);p["source_capacity"]="MID";p["max_train_label_end"]=pd.Timestamp(cut)-pd.Timedelta(days=1);p["cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE";p["native_point"]=.01;p["native_q50"]=.02
        return p,{}
    monkeypatch.setattr(c,"_load_frame",load)
    frame,x,context=c._fusion_inputs(tmp_path,reader,"2024-01-01")
    assert len(frame)==21 and x.shape==(21,32) and context.shape==(21,5)
    assert all(frame[m+"__source_capacity"].eq("MID").all() for m in c.FUSION_MEMBERS)
    assert all(frame[m+"__source_cutoff"].lt("2024-01-01").all() for m in c.FUSION_MEMBERS)
    original=load
    def incomplete(path):
        p,r=original(path)
        if Path(path).parent.name=="HGB":p=p.iloc[:-1]
        return p,r
    monkeypatch.setattr(c,"_load_frame",incomplete)
    with pytest.raises(ValueError,match="SIX_FIXED_MID_OOF_KEYS"):c._fusion_inputs(tmp_path,reader,"2024-01-01")


def test_fusion_controller_exact32_28_14_callbacks(tmp_path,monkeypatch):
    v=vectors(("2023-08-03","2024-02-05","2025-02-05"));reader=Reader(v);j=MemoryJournal();entered=[];stored=[];published=[]
    def composite(nodes,identity,work):
        def observe(event):assert event["node_id"] in nodes;entered.append(event)
        result=work(observe);assert {e["node_id"] for e in entered if e["year"]==identity["year"] and e["method"]==identity["method"]}==set(nodes);return result
    j.composite_once=composite
    monkeypatch.setattr(c,"_TaskLedger",lambda run:j);monkeypatch.setattr(c,"FullSelectorReader",lambda run:reader)
    monkeypatch.setattr(c,"worker_runtime",lambda run:(None,)*8+(SimpleNamespace(SPEC={"synthetic":True}),None));monkeypatch.setattr(c,"_raw_reference",lambda reader:v)
    def inputs(run,reader,cut):
        f=reader.labels("2023-07-01",cut).rename(columns={"target_end_date":"label_end_date"})
        for m in c.FUSION_MEMBERS:f[m+"__mu"]=.01
        return f,np.ones((len(f),32)),np.ones((len(f),5))
    def forecast(run,reader,year):
        f=reader.features(str(year)+"-01-01",str(year+1)+"-01-01");return f[c.KEYS+["ticker","U_t_fingerprint"]],np.ones((len(f),6)),np.ones((len(f),32)),np.ones((len(f),5))
    def fit(module,method,frame,cut,x,context,expected_full_day_uids,on_state):
        year=pd.Timestamp(cut).year
        for n in c.learners.single_training_dag()["nodes"]:
            if n.get("method")==method and n.get("year")==year:on_state(dict(node_id=n["node_id"],kind=n["kind"],year=year,method=method,actual_operation_entered=True))
        return {"synthetic":True},{"method":method,"rows":len(frame)}
    monkeypatch.setattr(c,"_fusion_inputs",inputs);monkeypatch.setattr(c,"_fusion_forecast",forecast);monkeypatch.setattr(c.cooperation,"fit_full_stock_fusion",fit)
    monkeypatch.setattr(c.cooperation,"predict_full_stock_fusion",lambda model,mu,x,context:np.zeros(len(mu)))
    monkeypatch.setattr(c,"_store_frame",lambda run,path,frame,identity:stored.append(str(path)))
    monkeypatch.setattr(c,"_publish_policy",lambda run,reader,role,forecast,raw:published.append(role));monkeypatch.setattr(c,"assemble_selection",lambda *a:{"synthetic":True})
    c.train_fusion(tmp_path)
    counts={kind:sum(e["kind"]==kind for e in entered) for kind in ("META_MODEL","META_SCALER","META_TARGET_SCALE")}
    assert counts=={"META_MODEL":32,"META_SCALER":28,"META_TARGET_SCALE":14}
    assert len(published)==12 and len(stored)==24


class CachingJournal(MemoryJournal):
    def __init__(self):
        super().__init__();self.cache={};self.design={"dag":{"nodes":c.learners.single_training_dag()["nodes"]+c.hybrid_training_dag()["nodes"]}}
    def once(self,node,identity,work):
        if node in self.cache:
            token,result=self.cache[node];assert token==c.digest(identity);return result
        result=super().once(node,identity,work);self.cache[node]=(c.digest(identity),result);return result


def risk_provider(tmp_path,calls,mutate=None):
    source=tmp_path/"risk_metadata.json";source.write_text('{"synthetic":true}',encoding="utf-8")
    def provider(*,family,signal_date,full_axis):
        calls.append((family,signal_date,full_axis.copy()));f=full_axis.copy()
        f[c.learners.SINGLE_RISK_COLUMNS[0]]=np.arange(len(f))/10000+.001
        f[c.learners.SINGLE_RISK_COLUMNS[1]]=np.arange(len(f))/20000-.0001
        q=dict(status="PASS",family=family,signal_date=str(signal_date),input_max_date=str(signal_date),full_axis_sha256=c.keys_digest(full_axis),native_H5=True,axis_complete=True,source_ref=dict(path=str(source.resolve()),sha256=c.sha(source)))
        out=dict(frame=f.iloc[::-1].copy(),qualified_ref=q)
        if mutate:mutate(out)
        return out
    return provider


def test_hybrid144_states_exact_and_no_fixed_mid_alias_nodes():
    d=c.hybrid_training_dag();assert d["counts"]=={"SCALER":24,"ESTIMATOR":120} and len(d["nodes"])==144
    assert c.learners.single_training_dag()["learned_operation_ceiling"]+len(d["nodes"])==738
    assert all(n["representation"]=="SINGLE_HYBRID_U34" for n in d["nodes"])
    assert not any(n.get("conditional_alias") or n["node_id"].startswith("PLATT|") for n in d["nodes"])


def test_hybrid_fullaxis_risk_reorder_matches_uid_not_position(tmp_path):
    v=vectors(("2023-08-03",));reader=Reader(v);calls=[];h=c._HybridReader(reader,"DIAG",risk_provider(tmp_path,calls))
    result=h.features("2023-07-01","2024-01-01")
    np.testing.assert_allclose(result[c.learners.SINGLE_RISK_COLUMNS[0]],np.arange(len(v))/10000+.001)
    assert result[c.KEYS].equals(v[c.KEYS]) and len(result)==len(v) and len(calls)==1
    h.features("2023-07-01","2024-01-01");assert len(calls)==1


@pytest.mark.parametrize("fault",["missing_uid","nan","negative_variance","wrong_family","future_input","non_native","unqualified","wrong_axis"])
def test_hybrid_risk_gap_typed_before_scaler(tmp_path,fault):
    v=vectors(("2022-08-03",));reader=Reader(v);calls=[]
    def mutate(out):
        if fault=="missing_uid":out["frame"]=out["frame"].iloc[:-1]
        elif fault=="nan":out["frame"].iloc[0,out["frame"].columns.get_loc(c.learners.SINGLE_RISK_COLUMNS[1])]=np.nan
        elif fault=="negative_variance":out["frame"][c.learners.SINGLE_RISK_COLUMNS[0]]=-.001
        elif fault=="wrong_family":out["qualified_ref"]["family"]="OTHER"
        elif fault=="future_input":out["qualified_ref"]["input_max_date"]="2025-01-01"
        elif fault=="non_native":out["qualified_ref"]["native_H5"]=False
        elif fault=="unqualified":out["qualified_ref"]["status"]="FAIL"
        else:out["qualified_ref"]["full_axis_sha256"]="changed"
    h=c._HybridReader(reader,"DIAG",risk_provider(tmp_path,calls,mutate));j=CachingJournal()
    with pytest.raises(c.HybridRiskUnavailable):
        pool=c._pool(h,"2023-07-01");c._bundle(tmp_path,j,h,pool,"RIDGE","2023-07-01","LOW",node_role="HYBRID_RIDGE_DIAG",rt=(None,)*10)
    assert not j.calls


def test_hybrid_maturity_first_and_risk_reference_fullU(tmp_path):
    v=vectors(("2022-08-03","2023-06-28"));reader=Reader(v);reader.h=reader.h.loc[~((reader.h.signal_date==pd.Timestamp("2022-08-03")) & reader.h.security_uid.eq("UID020"))]
    eligible=reader.labels("2020-01-01","2023-07-01");reader.qualification["training"]["2023-07-01"]={"rows":len(eligible),"key_sha256":c.keys_digest(eligible)}
    calls=[];h=c._HybridReader(reader,"DIAG",risk_provider(tmp_path,calls));pool=c._pool(h,"2023-07-01")
    assert len(pool)==20 and len(calls)==1 and len(calls[0][2])==21
    assert pool.signal_date.eq(pd.Timestamp("2022-08-03")).all()
    assert not any(day==pd.Timestamp("2023-06-28") for _,day,_ in calls)


def test_hybrid_actual_controller120_estimator24_scaler_callbacks(tmp_path,monkeypatch):
    v=vectors(("2022-08-03","2023-05-03","2023-08-03","2024-02-05","2024-08-05","2025-02-05"));reader=Reader(v);j=CachingJournal();calls=[];fit_calls=[];published=[];stored=[]
    monkeypatch.setattr(c,"_TaskLedger",lambda run:j);monkeypatch.setattr(c,"FullSelectorReader",lambda run:reader);monkeypatch.setattr(c,"worker_runtime",lambda run:(None,)*10);monkeypatch.setattr(c,"_raw_reference",lambda reader:v)
    def fit(role,x,y,tasks,dates,uids,cap,seed,q=None,runtime=None,on_fit=None,*,fit_cutoff,label_end_dates,expected_full_day_uids,representation):
        assert x.shape[1]==34 and representation=="SINGLE_HYBRID_U34" and len(x)==len(y)==len(dates)
        assert all(pd.Timestamp(t)<pd.Timestamp(fit_cutoff) for t in label_end_dates)
        on_fit(dict(operation="synthetic_native_backend"));fit_calls.append((role,cap,seed,q));return dict(role=role,q=q)
    def predict(model,x):
        assert x.shape[1]==34
        return {"q"+str(int(model["q"]*100)):np.full(len(x),model["q"]*.01)} if model["q"] is not None else {"point":np.full(len(x),.001)}
    monkeypatch.setattr(c.learners,"fit_single_component",fit);monkeypatch.setattr(c.learners,"predict_component",predict)
    monkeypatch.setattr(c,"_store_frame",lambda run,path,frame,identity:stored.append(str(path)) or {"path":str(path)})
    monkeypatch.setattr(c,"_publish_policy",lambda run,reader,role,forecast,raw:published.append((role,forecast.copy())))
    monkeypatch.setattr(c,"assemble_selection",lambda *a:dict(synthetic=True))
    c.train_hybrids(tmp_path,risk_provider(tmp_path,calls))
    assert len(fit_calls)==120 and sum(node.startswith("SCALER|") for node,_,_ in j.calls)==24 and len(j.calls)==144
    assert len(published)==6 and all(name.startswith("HYBRID_") for name,_ in published)
    assert all(set(frame.signal_date.dt.year)=={2024,2025} for _,frame in published)
    assert not any("fixed_mid" in path or "QUANTILE_Q10" in path for path in stored)
    assert all(len(identity["feature_order"])==34 and identity["risk_refs"] for _,identity,_ in j.calls)


def test_train_hybrids_missing_source_no_alpha_fit(tmp_path,monkeypatch):
    v=vectors(("2022-08-03","2023-08-03","2024-02-05","2024-08-05","2025-02-05"));reader=Reader(v);j=CachingJournal();failed=[]
    monkeypatch.setattr(c,"_TaskLedger",lambda run:j);monkeypatch.setattr(c,"FullSelectorReader",lambda run:reader);monkeypatch.setattr(c,"worker_runtime",lambda run:(None,)*10);monkeypatch.setattr(c,"_raw_reference",lambda reader:v)
    monkeypatch.setattr(c,"_role_failure",lambda run,cid,exc:failed.append((cid,type(exc).__name__)))
    monkeypatch.setattr(c,"assemble_selection",lambda *a:dict(synthetic=True))
    c.train_hybrids(tmp_path,lambda **kwargs:dict(status="SOURCE_NOT_TESTABLE"))
    assert len(failed)==6 and all(kind=="HybridRiskUnavailable" for _,kind in failed) and not j.calls
    assert len(j.blocks)==144

@pytest.mark.parametrize("defect",["missing_uid","missing_day"])
def test_platt_every_legal_mature_past_oof_key_before_fit(tmp_path,defect):
    v=vectors(("2023-05-03","2023-05-10"),21);reader=Reader(v);h=v[c.KEYS].copy()
    h["source_kind"]="MODEL_OOF";h["source_cutoff"]=pd.Timestamp("2023-04-01");h["max_train_label_end"]=pd.Timestamp("2023-03-01");h["cutoff_clock"]="MIDNIGHT_BEFORE_DECISION_CLOSE";h["native_margin"]=np.linspace(-1,1,len(h))
    h=h.iloc[:-1] if defect=="missing_uid" else h.loc[h.signal_date.eq("2023-05-03")]
    j=MemoryJournal()
    with pytest.raises(ValueError,match="EVERY_LEGAL_MATURE_PAST_OOF_KEY"):
        c._platt(tmp_path,j,reader,"2023-07-01","MID",[h])
    assert j.calls==[]


def _frozen_entry_fixture(tmp_path):
    source=tmp_path/"pure_source.py";source.write_text("synthetic=True\n",encoding="utf-8")
    config=tmp_path/"run_config.json";config.write_text(json.dumps({"research_id":c.ID,"resource_policy":{"threads":2}}),encoding="utf-8")
    manifest=tmp_path/"input_manifest.json";manifest.write_text(json.dumps({"synthetic":True}),encoding="utf-8")
    design=dict(research_id=c.ID,run_config_sha256=c.sha(config),sources={str(source):c.sha(source)},dag={"nodes":[{"node_id":"MODEL|SYNTHETIC","kind":"ESTIMATOR"}]})
    designpath=tmp_path/"DESIGN_FREEZE.json";designpath.write_text(json.dumps(design),encoding="utf-8")
    gate=dict(status="PASS",design_sha256=c.sha(designpath),input_manifest_sha256=c.sha(manifest))
    (tmp_path/"FREEZE_ACCEPTANCE.json").write_text(json.dumps(gate),encoding="utf-8")
    return source,config,manifest,designpath,gate


@pytest.mark.parametrize("defect,reason",[("config","FROZEN_RUN_CONFIG"),("manifest","FROZEN_INPUT_MANIFEST"),("source","EXECUTABLE_SOURCE"),("gate","INDEPENDENT_FREEZE"),("design","INDEPENDENT_FREEZE")])
def test_core_entry_rejects_changed_frozen_object_before_reader_runtime(tmp_path,monkeypatch,defect,reason):
    source,config,manifest,designpath,gate=_frozen_entry_fixture(tmp_path)
    monkeypatch.setattr(c,"assert_safe_output_path",lambda *a,**k:None)
    monkeypatch.setattr(c,"FullSelectorReader",lambda *a,**k:pytest.fail("reader entered before freeze gate"))
    monkeypatch.setattr(c,"worker_runtime",lambda *a,**k:pytest.fail("runtime entered before freeze gate"))
    if defect=="gate":
        gate["status"]="PENDING";(tmp_path/"FREEZE_ACCEPTANCE.json").write_text(json.dumps(gate),encoding="utf-8")
    else:
        target={"config":config,"manifest":manifest,"source":source,"design":designpath}[defect]
        target.write_bytes(target.read_bytes()+b" ")
    with pytest.raises(ValueError,match=reason):c.train_primary(tmp_path,("RIDGE",))
    assert not (tmp_path/"TASK_LEDGER.sqlite").exists()


def test_core_frozen_entry_exact_source_config_namespace_without_fit(tmp_path,monkeypatch):
    _frozen_entry_fixture(tmp_path);monkeypatch.setattr(c,"assert_safe_output_path",lambda *a,**k:None)
    j=c._TaskLedger(tmp_path)
    assert j.db.execute("SELECT node_id,status,entered FROM nodes").fetchall()==[("MODEL|SYNTHETIC","NAMED",0)]
    j.db.close()

