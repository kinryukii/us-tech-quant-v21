"""Isolated synthetic metadata and execution-queue tests; no project source data."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import copy
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import joint_short_risk_execution_r4 as runner
from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt, RiskInput
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, content_hash
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock, STORED_LABEL_COORDINATE


def test_source_support_from_flags_uid_and_epoch_never_numeric():
    date=pd.Timestamp("2024-01-02")
    labels=pd.DataFrame(dict(ticker=["A","B","C","D"],signal_date=date,label_available=True,
        endpoint_pair_available=[True,True,False,True],label_unsupported_common_event=False,
        label_coordinate=STORED_LABEL_COORDINATE))
    base=pd.DataFrame(dict(ticker=["A","B","C","D"],signal_date=date,security_id=["UID_A","BAD","UID_C","UID_D"]))
    history=pd.DataFrame(dict(ticker=["A","B","C","D"],signal_date=date,identity_epoch=["E_A","E_B","E_C","WRONG"]))
    pool=dict(asset_uids={a:"UID_"+a for a in "ABCD"},asset_epochs={a:"E_"+a for a in "ABCD"},history=history)
    inputs=SimpleNamespace(observations=pd.DataFrame(dict(asset=list("ABCD"),origin_at=_clock(date),return_value="not accessed")))
    keys=runner.source_support_keys(inputs,labels,base,pool)
    assert keys.qualified.tolist()==[True,False,False,False]
    assert list(keys.columns)==["asset","origin_at","qualified"]
    with pytest.raises(ValueError):
        runner.source_support_keys(inputs,pd.concat([labels,labels.iloc[:1]]),base,pool)


def test_qqq_metadata_requires_actual_entry_and_endpoint_keys():
    days,closes=_calendar(pd.bdate_range("2024-01-01","2024-02-15"))
    inputs=SimpleNamespace(observations=pd.DataFrame(dict(origin_at=closes[:10],asset="A")))
    meta=pd.DataFrame(dict(ticker="QQQ",trade_date=days))
    source=dict(sources=dict(qqq_qfq_years=[dict(year=2024,sha256="a"*64)]),research_id=runner.ID,family_design_freeze_sha256="d"*64)
    science=dict(actual_snapshot_timestamp="2026-10-03T00:00:00+00:00",scientific_contract_identity=runner.ID,scientific_contract_sha256="b"*64)
    # Use an actual typed input to exercise dataclass replace.
    stock=SourceReceipt("STOCK","V1","c"*64,pd.Timestamp("2020-01-01",tz="UTC"))
    typed=RiskInput(("A",),closes,inputs.observations,stock,{"A":"A"})
    result=runner.qqq_metadata_only(typed,meta,source,science,days,closes[-1])
    assert len(result.qqq_observations)==10
    assert result.qqq_observations.return_value.isna().all()
    missing=meta.loc[~meta.trade_date.eq(days[6])]
    reduced=runner.qqq_metadata_only(typed,missing,source,science,days,closes[-1])
    assert len(reduced.qqq_observations)<10
    with pytest.raises(ValueError,match="DUPLICATE"):
        runner.qqq_metadata_only(typed,pd.concat([meta,meta.iloc[:1]]),source,science,days,closes[-1])


def test_schedule_fixed_12_and_compact_support_keeps_key_identity():
    days,_=_calendar(pd.bdate_range("2022-01-01","2025-12-31"))
    schedule=runner.quarterly_schedule(days)
    assert len(schedule)==12
    assert schedule[0]["as_of"].startswith("2023-01-02")
    assert schedule[-1]["as_of"].startswith("2025-10-01")
    proof=dict(qualified_keys=[["A","2023-01-01"]],metadata_proof_sha256="a"*64,source_support_sha256="b"*64)
    compact=runner.compact_proof(proof)
    assert "qualified_keys" not in compact and compact["metadata_proof_sha256"]=="a"*64


def test_bank_records_distinct_r4_methods_source_only_and_baseline_once():
    ref=dict(path="D:/us-tech-quant-backtests/synthetic/file.json",sha256="a"*64)
    spec=dict(source_authority_ref=ref,producer_code_pins=[ref],recipe={"horizon":5})
    record=dict(risk_node="SHR_HP@2023",method="SHR_HP",as_of="2023-01-03T21:00:00+00:00",cutoff="2022-12-30T21:00:00+00:00",
        assets=["A","B"],asset_uids={"A":"UID_A","B":"UID_B"},asset_epochs={"A":"EA","B":"EB"},
        status="CONDITIONAL_FROZEN_HISTORY_MECHANISM",artifact_ref=ref,learned_states=7,fit_dependency_ids=["b"*64])
    ledger=dict(records=[record,{**record,"risk_node":"SHR_DYNAMIC@2023","method":"SHR_DYNAMIC","status":"BLOCKED_METADATA","artifact_ref":None}],
                new_fit_units=7,physical_events=[])
    bank=runner.bank_metadata(spec,{},ledger,spec_ref=ref,support_ref=ref,ledger_ref=ref)
    assert len(bank["states"])==len(bank["blocked_or_unverified_diagnostics"])==1
    assert bank["count_receipt"]["cumulative_b_lower_bound"]==1883
    assert bank["states"][0]["method"]=="SHR_HP"
    assert not bank["states"][0]["account_qualification_granted"]
    assert bank["state_contract"]["original_r3_min30_unchanged"]
    assert "covariance" not in bank["states"][0]


@pytest.mark.parametrize("defect",["new_asset","uid","method","expired","future","2026"])
def test_consumer_cannot_expand_or_alias_risk_state(defect):
    entry=dict(admission="CONDITIONAL_SOURCE_ONLY_EXACT_STATE",method="SHR_HP",assets=["A","B"],
               asset_uids={"A":"UID_A","B":"UID_B"},as_of="2023-01-03T21:00:00+00:00")
    args=dict(ordered_assets=("A","B"),current_uids=entry["asset_uids"],signal_asof="2023-03-20T20:00:00+00:00",expected_method="SHR_HP")
    assert runner.qualify_consumption(entry,**args)
    if defect=="new_asset": args["ordered_assets"]+=("NEW",)
    elif defect=="uid": args["current_uids"]={"A":"WRONG","B":"UID_B"}
    elif defect=="method": args["expected_method"]="R0"
    elif defect=="expired": args["signal_asof"]="2023-04-03T20:00:00+00:00"
    elif defect=="future": args["signal_asof"]="2023-01-02T21:00:00+00:00"
    else: args["signal_asof"]="2026-01-02T21:00:00+00:00"
    with pytest.raises(ValueError,match="BLOCKED"):
        runner.qualify_consumption(entry,**args)


def test_full_requested_pool_loader_never_requests_partial_uid(monkeypatch):
    seen={}
    def load(reader,source,science,days,cutoff,**kwargs):
        seen.update(kwargs)
        return {"assets":["BAD_UID"]},None,{"reason":"REQUESTED_UID_UNBOUND"}
    monkeypatch.setattr(runner.old,"load_period",load)
    with pytest.raises(ValueError,match="FULL_REQUESTED_POOL"):
        runner.load_context(None,{}, {},None,pd.Timestamp("2023-01-01",tz="UTC"),numeric=False)
    assert seen=={"numeric":False}


def test_whole_matrix_risk_artifact_pins_required(monkeypatch,tmp_path):
    spec=dict(research_id=runner.ID,recipe=runner.risk.specification(),producer_code_pins=[])
    sup=dict(specification_ref={"path":str(tmp_path/runner.SPEC),"sha256":"a"*64},groups=[{}]*12,nodes=[{}]*72)
    budget_ref={"path":str(tmp_path/"BUDGET.json"),"sha256":"a"*64}
    monkeypatch.setattr(runner,"guard",lambda *args:{"budget_scope_ref":budget_ref,"pinned_artifacts":[budget_ref]})
    monkeypatch.setattr(runner.old,"_pin",lambda *args:None)
    monkeypatch.setattr(runner.old,"read_json",lambda p:spec if Path(p).name==runner.SPEC else sup)
    monkeypatch.setattr(runner.old,"sha",lambda p:"a"*64)
    with pytest.raises(ValueError,match="MISSING_RISK_INPUT_PIN"):
        runner._fit_guard(tmp_path,"b"*64)


def test_forbidden_drive_source_reference_rejected_before_file_pin(monkeypatch,tmp_path):
    authority=dict(strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False,
                   source_inputs_ref={"path":"F:/forbidden/source.json","sha256":"a"*64})
    monkeypatch.setattr(runner.old,"read_json",lambda p:authority)
    monkeypatch.setattr(runner.old,"_pin",lambda *args:pytest.fail("forbidden file pin attempted"))
    with pytest.raises(ValueError,match="NO_EF_ACCESS"):
        runner._source(tmp_path)


def test_recovery_cache_reuses_existing_physical_state_without_reservation(monkeypatch,tmp_path):
    days,closes=_calendar(pd.bdate_range("2022-01-01","2025-12-31"))
    asof=pd.Timestamp(runner.quarterly_schedule(days)[0]["as_of"])
    receipt=SourceReceipt("SYNTHETIC","V1","a"*64,pd.Timestamp("2020-01-01",tz="UTC"))
    inputs=RiskInput(("A",),closes,pd.DataFrame(),receipt,{"A":"UID_A"})
    cache=runner.risk.make_cache(inputs,as_of=asof)
    cache.learn("covariance","synthetic_existing",(1,),lambda:np.eye(1))
    monkeypatch.setattr(runner,"assert_safe_output_path",lambda *args,**kwargs:None)
    reference=runner._save_cache(tmp_path,cache,asof.isoformat())
    ledger=SimpleNamespace(status={"new_fit_units":1},reserve=lambda event:pytest.fail("exact state re-reserved"))
    restored=runner._restore_cache(tmp_path,ledger,inputs,asof.isoformat(),reference)
    np.testing.assert_array_equal(restored.learn("covariance","synthetic_existing",(1,),lambda:pytest.fail("state recomputed")),np.eye(1))
    assert restored.budget.learned_total==1


def test_fit_queue_continues_all_72_metadata_blocked_nodes(monkeypatch,tmp_path):
    from contextlib import nullcontext
    days,_=_calendar(pd.bdate_range("2022-01-01","2025-12-31"))
    schedule=runner.quarterly_schedule(days)
    groups=[dict(**g,block_reason="MISSING_INPUT",metadata_qualification=None) for g in schedule]
    nodes=[dict(risk_node=m+"@"+g["as_of"],method=m,as_of=g["as_of"],cutoff=g["cutoff"],
                numeric_check_eligible=False,metadata_block_reason="MISSING_INPUT") for g in schedule for m in runner.risk.METHODS]
    ref={"path":"D:/us-tech-quant-backtests/synthetic/file.json","sha256":"a"*64}
    spec=dict(source_authority_ref=ref,producer_code_pins=[],recipe={"horizon":5})
    sup=dict(groups=groups,nodes=nodes)
    saved={}
    class Ledger:
        def __init__(self,*args,**kwargs):
            self.status=dict(records=[],new_fit_units=0,physical_events=[],failures=[])
            saved["ledger"]=self
        def checkpoint(self): pass
    class Reader:
        def __init__(self,*args,**kwargs): pass
        def read(self,*args,**kwargs): return pd.DataFrame({"trade_date":days})
    monkeypatch.setattr(runner,"_fit_guard",lambda *args:(spec,sup))
    monkeypatch.setattr(runner,"_source",lambda *args:({}, {},ref))
    monkeypatch.setattr(runner,"StageLedger",Ledger)
    monkeypatch.setattr(runner,"CapturingReader",Reader)
    monkeypatch.setattr(runner,"stage_writer",lambda *args:nullcontext())
    monkeypatch.setattr(runner,"_ref",lambda *args:ref)
    monkeypatch.setattr(runner.old,"write",lambda run,name,value,**kw:saved.update({name:value}))
    monkeypatch.setattr(runner.risk,"fit_risk",lambda *args,**kwargs:pytest.fail("metadata blocked node fitted"))
    result=runner.fit(tmp_path,expected_matrix_sha="b"*64)
    assert result["diagnostics"]==72 and result["risk_states"]==0
    assert len(saved["ledger"].status["records"])==72
    assert all(r["learned_states"]==0 for r in saved["ledger"].status["records"])
    assert result["test2026_rows_read"]==result["account_attempts"]==0



def test_support_large_metadata_exception_is_restricted_to_exact_r4_names():
    with pytest.raises(ValueError,match='EXACT_R4_METADATA_SUPPORT_NAME_REQUIRED'):
        runner.read_support('OTHER_INPUT.json')
