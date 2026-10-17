"""Synthetic postdecision source gates and exact-key H5 projection only."""
from copy import deepcopy
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data import selector_constrained_outcomes as h


@pytest.fixture
def bundle():
    days=pd.bdate_range("2025-01-01",periods=30);date=days[10]
    keys=pd.DataFrame(dict(signal_date=[date,date],security_uid=["CUSIP:123456789","CUSIP:987654321"],ticker=["AAA","BBB"]))
    origin=pd.DataFrame(dict(signal_date=[date,date],ticker=["AAA","BBB"],security_id=["123456789","987654321"],
                            security_id_type="CUSIP",cusip=["123456789","987654321"]))
    members=pd.DataFrame([(d,t,u) for d in days for t,u in (("AAA","123456789"),("BBB","987654321"))],
                         columns=["signal_date","ticker","cusip"])
    labels=pd.DataFrame(dict(signal_date=[date,date],ticker=["AAA","BBB"],execution_date=days[11],label_end_date=days[16],
        label_mature_date=days[16],label_coordinate=h.H5_COORDINATE,label_available=True,
        endpoint_pair_available=True,label_unsupported_common_event=False))
    return h.requested_keys(keys),days,origin,members,labels


def docs(keys):
    refs={n:dict(path=f"{n}_MOCK.parquet",sha256=v) for n,v in h.SOURCE_SHA.items()}
    sources={str(Path(p)):h.owner.sha(p) for p in (h.__file__,h.owner.__file__,h.identity_owner.__file__,h.namespace_owner.__file__)}
    d=dict(research_id=h.RESEARCH_ID,official_freeze=True,formal_freeze_applied=True,
        mechanism_research_eligible=True,strict_PIT_promotion_eligible=False,test2026_locked=True,
        new2026_estimation_authorized=False,h5_sources=refs,sources=sources)
    r=dict(status="PASS",design_sha256="D"*64,source_pins=sources)
    g=dict(status="PASS",research_id=h.RESEARCH_ID,design_sha256="D"*64,review_sha256="R"*64,
        decision_frozen=True,outcome_reads_before_gate=0,requested_keys_sha256=h.content_hash(keys),
        score_assembly_ref=dict(path="A_MOCK",sha256="A"*64),solve_ledger_ref=dict(path="L_MOCK",sha256="L"*64))
    return dict(D=d,R=r,G=g)


def mocked_gates(monkeypatch,bundle):
    state=docs(bundle[0]);refs=[dict(path=x,sha256=x*64) for x in "DRG"]
    monkeypatch.setattr(h,"_json_ref",lambda ref:state[ref["path"]])
    monkeypatch.setattr(h,"_ref",lambda ref:Path(ref["path"]))
    return state,refs


def test_full_identity_window_and_maturity_qualifies(bundle):
    out=h.qualify_metadata(*bundle)
    assert len(out)==2 and out.qualified.all() and out.return_value.isna().all()
    assert out.predecessor_uid.equals(out.security_uid)
    assert out.predecessor_date.eq(bundle[1][9]).all()


@pytest.mark.parametrize("mode",["uid_change","membership_gap","predecessor_change","origin_uid","origin_cusip",
 "origin_type","missing_origin","missing_label","duplicate_membership","duplicate_origin","duplicate_label",
 "wrong_entry","wrong_end","mature_early","unsupported","unavailable","endpoint","coordinate"])
def test_metadata_fail_closed_without_outcome_or_key_drop(bundle,mode):
    keys,days,origin,members,labels=[x.copy() for x in bundle];date=days[10]
    idx=members.ticker.eq("BBB")
    if mode=="uid_change":members.loc[idx & members.signal_date.eq(days[13]),"cusip"]="111111111"
    if mode=="membership_gap":members=members.loc[~(idx & members.signal_date.eq(days[13]))]
    if mode=="predecessor_change":members.loc[idx & members.signal_date.eq(days[9]),"cusip"]="111111111"
    if mode=="origin_uid":origin.loc[origin.ticker.eq("BBB"),"security_id"]="111111111"
    if mode=="origin_cusip":origin.loc[origin.ticker.eq("BBB"),"cusip"]="111111111"
    if mode=="origin_type":origin.loc[origin.ticker.eq("BBB"),"security_id_type"]="TICKER"
    if mode=="missing_origin":origin=origin.loc[origin.ticker.ne("BBB")]
    if mode=="missing_label":labels=labels.loc[labels.ticker.ne("BBB")]
    if mode=="duplicate_membership":members=pd.concat([members,members.loc[idx & members.signal_date.eq(days[13])]])
    if mode=="duplicate_origin":origin=pd.concat([origin,origin.loc[origin.ticker.eq("BBB")]])
    if mode=="duplicate_label":labels=pd.concat([labels,labels.loc[labels.ticker.eq("BBB")]])
    at=labels.ticker.eq("BBB")
    if mode=="wrong_entry":labels.loc[at,"execution_date"]=days[12]
    if mode=="wrong_end":labels.loc[at,"label_end_date"]=days[15]
    if mode=="mature_early":labels.loc[at,"label_mature_date"]=days[15]
    if mode=="unsupported":labels.loc[at,"label_unsupported_common_event"]=True
    if mode=="unavailable":labels.loc[at,"label_available"]=False
    if mode=="endpoint":labels.loc[at,"endpoint_pair_available"]=False
    if mode=="coordinate":labels.loc[at,"label_coordinate"]="MEAN_ER_3D_5D_10D_20D"
    out=h.qualify_metadata(keys,days,origin,members,labels)
    assert len(out)==2 and out.loc[out.ticker.eq("AAA"),"qualified"].all()
    assert not out.loc[out.ticker.eq("BBB"),"qualified"].any() and out.return_value.isna().all()


@pytest.mark.parametrize("mode",["future","duplicate","ticker","date","uid"])
def test_requested_key_contract(bundle,mode):
    keys=bundle[0].copy()
    if mode=="future":keys.loc[0,"signal_date"]=pd.Timestamp("2026-01-01")
    if mode=="duplicate":keys=pd.concat([keys,keys.iloc[:1]])
    if mode=="ticker":keys.loc[0,"ticker"]=""
    if mode=="date":keys.loc[0,"signal_date"]=pd.NaT
    if mode=="uid":keys.loc[0,"security_uid"]=None
    with pytest.raises(ValueError):h.requested_keys(keys)


@pytest.mark.parametrize("part,key,value",[("D","official_freeze",False),("D","strict_PIT_promotion_eligible",True),
 ("D","test2026_locked",False),("D","new2026_estimation_authorized",True),("R","status","FAIL"),
 ("R","design_sha256","x"*64),("G","status","PENDING"),("G","decision_frozen",False),
 ("G","outcome_reads_before_gate",1),("G","requested_keys_sha256","x"*64),("G","review_sha256","x"*64)])
def test_no_reader_or_y_before_all_gates(bundle,monkeypatch,part,key,value):
    state,refs=mocked_gates(monkeypatch,bundle);state[part][key]=value
    monkeypatch.setattr(h,"H5ProjectedReader",lambda *a:(_ for _ in ()).throw(AssertionError("NO READER BEFORE GATE")))
    with pytest.raises(ValueError):h.read_h5(*refs,bundle[0])


def test_source_pin_mismatch_rejected_before_reader(bundle,monkeypatch):
    state,refs=mocked_gates(monkeypatch,bundle);state["D"]["sources"][str(Path(h.__file__))]="x"*64
    state["R"]["source_pins"]=deepcopy(state["D"]["sources"])
    monkeypatch.setattr(h,"H5ProjectedReader",lambda *a:(_ for _ in ()).throw(AssertionError("NO READER")))
    with pytest.raises(ValueError):h.read_h5(*refs,bundle[0])


def test_source_refs_exact_original_four_hashes(bundle,monkeypatch):
    state,refs=mocked_gates(monkeypatch,bundle);state["D"]["h5_sources"]["labels"]["sha256"]="x"*64
    with pytest.raises(ValueError):h.gates(*refs,bundle[0])


def test_inherited_predicate_reader_is_not_copied():
    assert h.H5ProjectedReader.read is h.owner.ProjectedReader.read


def test_only_proved_origin_ticker_y_is_projected(bundle,monkeypatch):
    state,refs=mocked_gates(monkeypatch,bundle);keys,days,origin,members,labels=bundle
    members=members.copy();members.loc[members.ticker.eq("BBB") & members.signal_date.eq(days[13]),"cusip"]="111111111"
    frames=dict(calendar=pd.DataFrame(dict(trade_date=days)),identity=origin,membership=members,labels=labels.assign(y_open5=[.02,.8]))
    calls=[]
    class Reader:
        def __init__(self,refs):self.phase="support";self.audit=[]
        def read(self,name,columns,*,date_field,start=None,stop=None,day=None,tickers=None,**kwargs):
            calls.append((name,columns,self.phase,day,tickers));f=frames[name]
            if "y_open5" in columns:
                assert self.phase=="postdecision" and tickers==("AAA",)
            keep=pd.Series(True,index=f.index)
            if start is not None:keep &= f[date_field].ge(start)
            if stop is not None:keep &= f[date_field].lt(stop)
            if day is not None:keep &= f[date_field].eq(day)
            if tickers is not None:keep &= f.ticker.isin(tickers)
            out=f.loc[keep,list(columns)].copy();self.audit.append(dict(source=name,columns=list(columns),rows=len(out)))
            return out
    monkeypatch.setattr(h,"H5ProjectedReader",Reader)
    out,receipt=h.read_h5(*refs,keys)
    assert out.loc[out.ticker.eq("AAA"),"return_value"].iloc[0]==.02
    assert out.loc[out.ticker.eq("BBB"),"return_value"].isna().all() and not out.loc[out.ticker.eq("BBB"),"qualified"].any()
    assert len([x for x in calls if "y_open5" in x[1]])==1
    assert receipt["numeric_origin_keys"]==1 and receipt["requested_keys"]==2
    assert receipt["outcome_reads_before_gate"]==0 and not receipt["strict_PIT_promotion_eligible"]
