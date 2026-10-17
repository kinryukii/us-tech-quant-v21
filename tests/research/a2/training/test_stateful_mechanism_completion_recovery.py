"""Completion-only control flow is synthetic; no model, account or data reads."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_mechanism as r
from scripts.research.a2.training import stateful_execution as e
from scripts.research.a2.training import stateful_mechanism_evaluation as v

@pytest.fixture
def recovery(monkeypatch):
    run=Path("C:/synthetic-r10-run").resolve()
    names=("ACTION_BATCH","HAZARD_CONTINUATION_BATCH","SEQUENCE_BATCH","SHARED_RISK_BATCH",
           "RISK_ACTION_BATCH","FUSION_BATCH","SEQUENCE_FUSION_BATCH","GROSS_BATCH")
    docs={name+".json":{"status":"COMPLETE","publications":[{"synthetic":name}]} for name in names}
    docs["FROZEN_DESIGN.json"]={}
    docs["run_config.json"]={"frozen_design_sha256":"SYNTHETIC_SHA"}
    docs["SHARED_RISK_BATCH.json"].update(path=str(run/"risk.joblib"),sha256="SYNTHETIC_SHA")
    docs["GROSS_BATCH.json"].update(derived_grid_path=str(run/"gross.parquet"),derived_grid_sha256="SYNTHETIC_SHA")
    calls=[]
    monkeypatch.setattr(r,"read_json",lambda path:docs[Path(path).name])
    monkeypatch.setattr(r,"authority_check",lambda d:calls.append("authority"))
    monkeypatch.setattr(r.fit_owner,"sha",lambda p:"SYNTHETIC_SHA")
    @contextmanager
    def lock(*args,**kw):
        calls.append("lock")
        yield "synthetic-no-file"
        calls.append("unlock")
    monkeypatch.setattr(e,"continuation_lock",lock)
    monkeypatch.setattr(r.inputs.ReadPermit,"from_files",lambda *a:object())
    bundle=SimpleNamespace(frames=object())
    monkeypatch.setattr(r.inputs,"build_real_frames",lambda *a:bundle)
    monkeypatch.setattr(r,"structured_action_frame",lambda f,h:{"horizon":h})
    monkeypatch.setattr(r.joblib,"load",lambda p:{"exact_existing_risk":True})
    monkeypatch.setattr(r,"risk_consumer_tables",lambda *a:("features","context","flat"))
    gross=pd.DataFrame({"signal_date":pd.to_datetime(["2025-01-02"]),
                        "label_mature_date":pd.to_datetime(["2025-01-10"]),
                        "target":[.01],"label_qualified":[True],"sample_id":["synthetic"]})
    monkeypatch.setattr(r.inputs,"guard_sources",lambda *a:{"OWN_GROSS":{"file_fingerprint":{"size":10,"mtime_ns":20}}})
    monkeypatch.setattr(pd,"read_parquet",lambda path:gross.copy())
    stat=Path.stat
    monkeypatch.setattr(Path,"stat",lambda path,*a,**k:
        SimpleNamespace(st_size=10,st_mtime_ns=20) if path==run/"gross.parquet" else stat(path,*a,**k))
    def forbidden(*a,**k):pytest.fail("completion-only must never enter scientific dispatcher")
    for name in ("physical_job","run_actions","run_continuation_hazard","run_sequences",
                 "run_shared_risk","run_risk_action","run_fusions","run_sequence_fusions","run_gross"):
        monkeypatch.setattr(r,name,forbidden)
    def complete(actual_run,design,actual_bundle,frames,pubs,**kw):
        assert actual_run==run and actual_bundle is bundle
        assert tuple(frames)==(*r.inputs.HORIZONS,"MEAN")
        assert pubs==[{"synthetic":name} for name in names]
        assert kw["risk_result"]=={"exact_existing_risk":True}
        assert kw["risk_features"]=="features" and kw["risk_flat"]=="flat"
        pd.testing.assert_frame_equal(kw["gross_frame"],gross)
        calls.append("complete")
        return {"status":"SYNTHETIC_COMPLETE"}
    monkeypatch.setattr(v,"complete_study",complete)
    return run,docs,calls

def test_completion_only_dispatch_never_fits_and_preserves_ledgers(recovery):
    run,docs,calls=recovery
    assert r.complete_existing(run)=={"status":"SYNTHETIC_COMPLETE"}
    assert calls==["authority","lock","complete","unlock"]

@pytest.mark.parametrize("status",["RUNNING","FAILED",None])
def test_completion_only_rejects_nonterminal_batches_before_reads(recovery,status):
    run,docs,calls=recovery
    docs["FUSION_BATCH.json"]["status"]=status
    with pytest.raises(ValueError,match="ALL_TERMINAL"):r.complete_existing(run)
    assert calls==["authority"]

def test_completion_only_rejects_own_artifact_digest_drift(recovery):
    run,docs,calls=recovery
    docs["SHARED_RISK_BATCH.json"]["sha256"]="DRIFTED"
    with pytest.raises(ValueError,match="CUSTODY_OR_SHA"):r.complete_existing(run)
    assert calls==["authority"]

def test_completion_only_rejects_external_artifact_path(recovery):
    run,docs,calls=recovery
    docs["GROSS_BATCH.json"]["derived_grid_path"]="C:/other-run/gross.parquet"
    with pytest.raises(ValueError,match="CUSTODY_OR_SHA"):r.complete_existing(run)
    assert calls==["authority"]
