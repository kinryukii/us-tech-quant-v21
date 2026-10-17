"""Generated workflow integration counterexamples; no real run or numeric source."""
import json
import traceback
from pathlib import Path
from types import SimpleNamespace
import joblib
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import full_selector_workflow as w
from scripts.research.a2.data import full_selector_account_inputs as ai
from scripts.research.a2.evaluation import full_selector_accounts as ac

class AccountJournal:
    def __init__(self,run):
        self.run=Path(run);self.calls=0
        self.design=dict(account_path_ids=["RAW"],account_inputs={"source":"GENERATED"},account_config={"initial_cash":3000},friction={"one_way_bps":10})
        self.record=dict(status="NAMED",entered=0,identity=None,artifact=None,error=None)
    def once(self,node,identity,work):
        token=w.c.digest(identity)
        if self.record["status"]=="COMPLETE":
            assert self.record["identity"]==token
            ref=json.loads(self.record["artifact"]);assert w.sha(ref["path"])==ref["sha256"]
            return joblib.load(ref["path"])
        if self.record["status"]!="NAMED":return None
        self.record.update(status="STARTED",identity=token)
        def enter(event):assert self.record["entered"]==0;self.record["entered"]=1
        try:
            self.calls+=1;result=work(enter);assert self.record["entered"]==1
            path=self.run/"node_artifact.joblib";joblib.dump(result,path)
            self.record.update(status="COMPLETE",artifact=json.dumps(w._ref(path)))
            return result
        except Exception:
            self.record.update(status="FAILED",error=traceback.format_exc());return None
    def status(self,node):return self.record.copy()
    def block(self,node,reason):self.record.update(status="BLOCKED_DEPENDENCY",error=reason)

@pytest.fixture
def wired(monkeypatch,tmp_path):
    run=tmp_path;j=AccountJournal(run);source=run/"policy_RAW.parquet";source.write_bytes(b"generated policy pin")
    panel=pd.DataFrame(dict(signal_date=pd.to_datetime(["2024-01-02"]),security_uid=["CUSIP:GENERATED"],ticker=["G"],score=[1.],selected=[True]))
    terminal=dict(policy_refs={"RAW":w._ref(source)})
    monkeypatch.setattr(w.c,"_TaskLedger",lambda p:j)
    monkeypatch.setattr(w,"freeze_policy_terminal",lambda p:terminal)
    monkeypatch.setattr(w.c,"_load_frame",lambda p:(panel.copy(),w._ref(source)))
    monkeypatch.setattr(ai,"load_account_inputs",lambda p:{"source":"GENERATED"})
    monkeypatch.setattr(w,"assert_safe_output_path",lambda *a,**k:None)
    day=pd.DataFrame(dict(date=pd.to_datetime(["2024-01-02"]),path_id=["RAW"],TOTAL_ECONOMIC_NAV=[3000.],LIQUID_NAV=[3000.],research_accounting_qualified=[True]))
    result=SimpleNamespace(daily=day,positions=pd.DataFrame(),orders=pd.DataFrame(),fills=pd.DataFrame(),execution_results=pd.DataFrame(),entitlements=pd.DataFrame(),accounting_exceptions=pd.DataFrame(),metadata={"source":"GENERATED"},audit={"execution_pass":True},prefix_identity={"end_session":"2024-01-02"})
    q={"RAW":{"full_window_complete":True,"mechanism_accounting_consistent":True}}
    calls=[]
    def owner(bound,membership,ids,*,ledger_callback=None,on_backend=None):
        calls.append(ids);assert on_backend is not None;on_backend()
        assert ledger_callback is not None;ledger_callback("daily",day)
        return result,q,pd.DataFrame({"source_identity":["GENERATED"]})
    monkeypatch.setattr(ac,"run_fixed_accounts",owner)
    return SimpleNamespace(run=run,journal=j,source=source,panel=panel,result=result,q=q,calls=calls,owner=owner,terminal=terminal)

def test_complete_account_reuses_original_publication_and_owner_once(wired):
    first=w.run_accounts(wired.run);terminal=w._ref(wired.run/"ACCOUNT_TERMINAL.json")
    publication=first["complete"]["RAW"]["publication"]
    second=w.run_accounts(wired.run)
    assert first==second and len(wired.calls)==1 and wired.journal.calls==1
    assert w.sha(terminal["path"])==terminal["sha256"] and w.sha(publication["path"])==publication["sha256"]
    assert first["complete"]["RAW"]["source_quote_proof"] is not None

@pytest.mark.parametrize("name",["daily.parquet","qualification.json","owner_audit.json"])
def test_changed_published_account_file_cannot_be_rehashed_into_terminal(wired,name):
    first=w.run_accounts(wired.run);terminal=w._ref(wired.run/"ACCOUNT_TERMINAL.json")
    target=wired.run/"accounts"/"RAW"/name
    target.write_bytes(target.read_bytes()+b"generated drift")
    changed=w.sha(target)
    with pytest.raises(ValueError,match="PUBLICATION_PHYSICAL_CHANGED"):w.run_accounts(wired.run)
    assert w.sha(target)==changed and w.sha(terminal["path"])==terminal["sha256"] and len(wired.calls)==1

def test_incomplete_account_publication_preserved_without_overwrite_or_replay(wired):
    target=wired.run/"accounts"/"RAW"/"daily.parquet";target.parent.mkdir(parents=True)
    target.write_bytes(b"interrupted original publication");original=w.sha(target)
    with pytest.raises(ValueError,match="INCOMPLETE_ACCOUNT_PUBLICATION"):w.run_accounts(wired.run)
    with pytest.raises(ValueError,match="INCOMPLETE_ACCOUNT_PUBLICATION"):w.run_accounts(wired.run)
    assert w.sha(target)==original and len(wired.calls)==1

def test_failed_account_keeps_actual_owner_emissions_and_never_replays(wired,monkeypatch):
    calls=[]
    def owner(bound,membership,ids,*,ledger_callback=None,on_backend=None):
        calls.append(ids);assert ledger_callback is not None;on_backend()
        ledger_callback("daily",wired.result.daily)
        ledger_callback("entitlements",pd.DataFrame({"event_id":["GENERATED_UNKNOWN"],"receivable_spendable":[False]}))
        raise ValueError("GENERATED_FULL_WINDOW_QUALIFICATION_FAILED")
    monkeypatch.setattr(ac,"run_fixed_accounts",owner)
    first=w.run_accounts(wired.run);again=w.run_accounts(wired.run)
    assert first==again and calls==[("RAW",)] and wired.journal.status("ACCOUNT|RAW")["entered"]==1
    failure=first["failed"]["RAW"];ref=failure["original_owner_trace"]
    saved=json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    assert saved["status"]=="OWNER_OR_QUALIFICATION_FAILED" and saved["rows"]=={"daily":1,"entitlements":1}
    assert saved["scientific_retry"]==0 and saved["failure"]["reason"]=="GENERATED_FULL_WINDOW_QUALIFICATION_FAILED"
    for item in saved["files"].values():assert w.sha(item["path"])==item["sha256"]
    assert not (wired.run/"accounts"/"RAW"/"daily.parquet").exists()

def test_before_owner_source_failure_has_zero_entry_and_no_fake_trace(wired,monkeypatch):
    def owner(*a,**k):raise ValueError("GENERATED_DATED_IDENTITY_GAP")
    monkeypatch.setattr(ac,"run_fixed_accounts",owner)
    value=w.run_accounts(wired.run)
    assert value["failed"]["RAW"]["entered"] is False
    assert value["failed"]["RAW"]["original_owner_trace"] is None
    assert not (wired.run/"accounts"/"RAW"/"owner_trace").exists()

def test_changed_failed_trace_refused_without_account_retry(wired,monkeypatch):
    def owner(*a,**k):
        k["on_backend"]();k["ledger_callback"]("daily",wired.result.daily)
        raise ValueError("GENERATED_FAILED_OWNER")
    monkeypatch.setattr(ac,"run_fixed_accounts",owner)
    first=w.run_accounts(wired.run);target=wired.run/"accounts"/"RAW"/"owner_trace"/"daily.parquet"
    target.write_bytes(target.read_bytes()+b"generated drift")
    with pytest.raises(ValueError,match="FAILED_ACCOUNT_TRACE_CHANGED"):w.run_accounts(wired.run)
    assert wired.journal.calls==1

def test_changed_frozen_policy_blocks_before_owner_entry(wired):
    wired.source.write_bytes(b"changed frozen policy")
    with pytest.raises(ValueError,match="FROZEN_ACCOUNT_POLICY_CHANGED"):w.run_accounts(wired.run)
    assert wired.calls==[] and wired.journal.record["entered"]==0

def test_member_and_whole_gate_call_original_owner_with_exact_state_axis(monkeypatch,tmp_path):
    names=["T"+str(i).zfill(2) for i in range(22)]
    frame=pd.DataFrame(dict(signal_date=pd.to_datetime(["2024-01-02"]*22),security_uid=["CUSIP:"+n for n in names],ticker=names,score=np.arange(22,dtype=float),selected=[i>=2 for i in range(22)]))
    raw=frame.copy();raw["selected"]=[i<20 for i in range(22)]
    paths=tmp_path/"predictions";paths.mkdir()
    for role in ("RAW","HGB"):(paths/("policy_"+role+".parquet")).write_bytes(role.encode())
    states={f:dict(assets=names[::-1],asset_uids={n:"CUSIP:"+n for n in names},family=f) for f in ("DIAG","LW")}
    seen=[];stored={}
    class J:
        design={"risk_contexts":{"source":"GENERATED"}}
        def once(self,node,identity,work):
            def enter(event):seen.append(("enter",node,event))
            return work(enter)
        def block(self,*a):pytest.fail("Complete synthetic wiring must not block")
    monkeypatch.setattr(w.c,"_TaskLedger",lambda p:J())
    monkeypatch.setattr(w,"FullSelectorReader",lambda p:object())
    monkeypatch.setattr(w.c,"FAMILIES",("DIAG",));monkeypatch.setattr(w.c,"GATES",("LW_VARIANCE",))
    monkeypatch.setattr(w.c,"_load_frame",lambda p:(raw.copy() if "RAW" in str(p) else frame.copy(),{}))
    monkeypatch.setattr(w.c,"validate_policy_domain",lambda *a:None)
    monkeypatch.setattr(w.c,"_store_frame",lambda run,path,value,identity:stored.setdefault(path.name,value.copy()))
    monkeypatch.setattr(w.c,"assemble_selection",lambda p:stored)
    def member(scores,uids,state,**kwargs):
        assert not isinstance(scores,dict) and list(scores)==list(range(21,-1,-1))
        assert tuple(uids)==tuple(state["asset_uids"][a] for a in state["assets"])
        assert kwargs==dict(count=20,max_swaps=20,quality_floor=.975)
        assert seen[-1][0]=="enter"
        seen.append(("member",));return {"members":tuple(names[2:]),"anchor_members":tuple(names[2:]),"objective":.01,"accepted_swaps":[]}
    def gate(kind,hgb_members,raw_members,state):
        assert kind=="LW_VARIANCE" and hgb_members==tuple(names[2:]) and raw_members==tuple(names[:20])
        assert state is states["LW"] and seen[-1][0]=="enter"
        seen.append(("gate",));return {"members":raw_members,"passed":False}
    monkeypatch.setattr(w.risk,"fixed_policy_bounded_swap",member)
    monkeypatch.setattr(w.risk,"fixed_policy_risk_objective",lambda state,members:.02)
    monkeypatch.setattr(w.risk,"fixed_policy_whole_set_gate",gate)
    provider=SimpleNamespace(state=lambda day,family:states[family])
    value=w.risk_policies(tmp_path,provider)
    assert set(value)=={"policy_RISK_DIAG.parquet","policy_GATE_LW_VARIANCE.parquet"}
    assert tuple(value["policy_GATE_LW_VARIANCE.parquet"].loc[lambda f:f.selected,"ticker"])==tuple(names[:20])
    assert [r[0] for r in seen]==["enter","member","enter","gate"]
