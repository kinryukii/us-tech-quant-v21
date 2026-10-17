import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace
from scripts.research.a2.risk.event_risk_contract_r5 import (
    structural_identity, EventWitness, event_calendar, conditional_prior_completion)


def identity(uid="U1"):
    return structural_identity(assets=("A",),uids={"A":uid},epochs={"A":"E1"},
        security_coordinate="RAW_SHARE",source_support_identity={"sha256":"a"*64})


def test_structural_change_and_unknown_block():
    assert identity()!=identity("U2")
    with pytest.raises(ValueError,match="UNKNOWN"):
        identity("UNKNOWN")
    with pytest.raises(ValueError,match="OUTCOME"):
        structural_identity(assets=("A",),uids={"A":"U1"},epochs={"A":"E1"},
            security_coordinate="RAW_SHARE",source_support_identity={"NAV":1})


def test_event_reuse_never_looks_at_next_event():
    s=identity()
    EventWitness("2023-02-22T21:00:00Z",s,s,True,True).validate("2023-01-03T21:00:00Z")
    with pytest.raises(ValueError,match="STRUCTURAL_CHANGE"):
        EventWitness("2023-02-22T21:00:00Z",identity("U2"),s,True,True).validate("2023-01-03T21:00:00Z")
    with pytest.raises(ValueError,match="SUPPORT_INVALID"):
        EventWitness("2023-02-22T21:00:00Z",s,s,False,True).validate("2023-01-03T21:00:00Z")


def test_event_clock_accepts_midquarter_exact_close_only():
    sessions=pd.to_datetime(["2023-02-21T21:00Z","2023-02-22T21:00Z"],utc=True)
    a,c,_=event_calendar(SimpleNamespace(sessions=sessions),sessions[1])
    assert a==sessions[1] and c==sessions[0]
    with pytest.raises(ValueError,match="EXACT_CURRENT"):
        event_calendar(SimpleNamespace(sessions=sessions),"2023-02-22T20:00Z")


def test_completion_preserves_classical_block_and_schur():
    h=np.array([[2.,.2,.5],[.2,1.,.1],[.5,.1,1.5]])
    c=np.array([[.8,.1],[.1,2.]])
    result,proof=conditional_prior_completion(h,c,(0,1))
    np.testing.assert_allclose(result[:2,:2],c,atol=1e-12)
    np.testing.assert_allclose(result[2:,2:],h[2:,2:],atol=1e-12)
    old=h[2:,2:]-h[2:,:2]@np.linalg.solve(h[:2,:2],h[:2,2:])
    new=result[2:,2:]-result[2:,:2]@np.linalg.solve(c,result[:2,2:])
    np.testing.assert_allclose(new,old,atol=1e-12)
    assert np.linalg.eigvalsh(result).min()>0 and proof["observations_fabricated"] is False


def test_completion_rejects_indefinite_prior():
    with pytest.raises(ValueError,match="POSITIVE_DEFINITE"):
        conditional_prior_completion(np.array([[1.,2.],[2.,1.]]),np.ones((1,1)),(0,))


def test_whitespace_unknown_and_kernel_path_binding(tmp_path):
    from scripts.research.a2.risk.event_risk_contract_r5 import bind_pinned_kernel
    with pytest.raises(ValueError,match="UNKNOWN"):
        identity(" UNKNOWN ")
    path=tmp_path/"unrelated.py";path.write_text("unused",encoding="utf-8")
    with pytest.raises(ValueError,match="SOURCE_PATH_MISMATCH"):
        bind_pinned_kernel(identity,physical_path=path,expected_sha256="a"*64,dependencies={"pytest":pytest})


@pytest.mark.parametrize("new,risk",[(-1,-1),(1070,1070),(True,True),(1,0)])
def test_r5_ledger_rejects_invalid_restored_counters(monkeypatch,tmp_path,new,risk):
    from scripts.research.a2.evaluation import joint_r5_runtime as runtime
    root=tmp_path/"run";(root/"work").mkdir(parents=True)
    import json
    (root/"R5_SCIENCE_AND_EXECUTION_FREEZE.json").write_text(json.dumps({"maximum_new_fit_units":1056}))
    (root/"work/FIT_STATUS.json").write_text(json.dumps(dict(inherited_fit_units=3027,
        fit_attempts=3027+int(new),new_fit_units=new,risk_fit_units=risk,test2026_rows_read=0)))
    monkeypatch.setattr(runtime,"guard",lambda *args,**kwargs:root)
    with pytest.raises(ValueError,match="COUNTER"):
        runtime.R5FitLedger(root,expected_freeze_sha256="b"*64)


def test_numeric_registry_requires_exact_frozen_metadata_scope(monkeypatch,tmp_path):
    from scripts.research.a2.evaluation import joint_r5_runtime as runtime
    from scripts.maintenance import research_registry
    row=dict(status="OPEN",parent_entity_id="V24_B_JOINT_MAXIMAL_BREADTH_PRE2026_R4",
        source_contract_ref=str(tmp_path/"SOURCE_AUTHORITY.json"),metadata=dict(
            event_science_freeze_sha256="a"*64,event_source_authority_sha256="b"*64,
            strict_PIT_promotion_eligible=False,fit_authority=False,formal_freeze_authority=False))
    monkeypatch.setattr(runtime.parent,"read_json",lambda path:{"registry_root":"synthetic"})
    monkeypatch.setattr(research_registry,"query_registry",lambda *args,**kw:
        {"status":"PASS","count":1,"entities":[row]})
    freeze={"source_authority_ref":{"sha256":"b"*64}}
    runtime._registered_scope(tmp_path,freeze,"a"*64)
    row["metadata"]["event_science_freeze_sha256"]="c"*64
    with pytest.raises(ValueError,match="EXACT_FREEZE"):
        runtime._registered_scope(tmp_path,freeze,"a"*64)
    monkeypatch.setattr(research_registry,"query_registry",lambda *args,**kw:
        {"status":"PASS","count":0,"entities":[]})
    with pytest.raises(ValueError,match="ACCEPTED_R5"):
        runtime._registered_scope(tmp_path,freeze,"a"*64)
