"""Synthetic production bindings: no real reader, estimator or outcome access."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import selector_frozen_history_risk as production
from scripts.research.a2.training import selector_monthly_risk as kernel


def test_only_four_scientific_roles_and_two_references():
    assert len(production.ROLES)==6
    assert len(production.head_columns("MONTHLY_FIXED_CORE_RIDGE"))==20
    assert len(production.head_columns("MONTHLY_COVERAGE_FLAG_ONLY_HGB"))==10
    assert production.head_columns(kernel.REFERENCES[0])==production.head_columns(kernel.preflight.ROLES[0])
    with pytest.raises(ValueError,match="FIFTH_ROLE"):
        production.head_columns("EXTRA_MODEL")


def test_monthly_cutoff_on_first_session_and_exact_jan1_annual():
    monthly=dict(kind="RISK",method="DIAG",cadence="MONTHLY",cutoff="2023-01-03T00:00:00")
    annual=dict(kind="RISK",method="DIAG",cadence="ANNUAL",cutoff="2023-01-01T00:00:00")
    future=dict(monthly,cutoff="2023-02-01T00:00:00")
    assert production.effective_slot([annual,monthly,future],"2023-01-03","DIAG","MONTHLY") is monthly
    assert production.effective_slot([annual,monthly,future],"2023-01-03","DIAG","ANNUAL") is annual
    with pytest.raises(kernel.ExecutionBlocked,match="NO_LEGAL"):
        production.effective_slot([future],"2023-01-03","DIAG","MONTHLY")


def test_identity_reversion_retains_full_u_as_unknown(monkeypatch):
    calls=[]
    monkeypatch.setattr(kernel,"project_full_pool",lambda bundle,names:calls.append(names) or np.zeros((len(names),3)))
    keys=pd.DataFrame({"security_uid":["A","B","C"]})
    result=production.epoch_projection(object(),{"A":"oldA","B":"sameB"},keys,["newA","sameB","newC"])
    assert result.shape==(3,3)
    assert calls==[["UNKNOWN_EPOCH:A:newA","B","UNKNOWN_EPOCH:C:newC"]]


def test_actual_estimation_unreachable_without_freeze(monkeypatch,tmp_path):
    called=[]
    monkeypatch.setattr(production.kernel,"checked",lambda run:(_ for _ in ()).throw(kernel.ExecutionBlocked("FREEZE_MISSING")))
    monkeypatch.setattr(production,"FrozenHistoryReader",lambda *a:called.append("REAL_READER"))
    monkeypatch.setattr(production.prior,"runtime",lambda *a:called.append("REAL_RUNTIME"))
    with pytest.raises(kernel.ExecutionBlocked,match="FREEZE_MISSING"):
        production.run_training(tmp_path)
    assert called==[]


def test_future_label_never_passes_guard_or_sampler(monkeypatch):
    dates=pd.to_datetime(["2022-02-01","2022-03-01"])
    history=pd.DataFrame({"signal_date":dates,"ticker":["A","B"],"security_uid":["A","B"],
        "U_t_fingerprint":["U1","U2"],"target":[.1,.2],
        "label_end_date":pd.to_datetime(["2022-02-20","2023-01-03"]),
        "source_kind":["CALIBRATED_OOF"]*2,"source_cutoff":pd.to_datetime(["2022-01-01"]*2)})
    for name in production.head_columns("MONTHLY_FIXED_CORE_RIDGE"):
        history[name]=1.
    current=history.iloc[:1].copy()
    seen=[]
    cal=SimpleNamespace(sample=lambda frame:seen.append(frame.label_end_date.tolist()) or (_ for _ in ()).throw(RuntimeError("STOP_BEFORE_FIT")))
    with pytest.raises(RuntimeError,match="STOP_BEFORE_FIT"):
        production.fit_head_arrays("MONTHLY_FIXED_CORE_RIDGE",history,current,pd.Timestamp("2023-01-01"),cal)
    assert seen==[[pd.Timestamp("2022-02-20")]]


def test_failed_head_leftover_prediction_cannot_enter_assembly(monkeypatch,tmp_path):
    run=tmp_path/"synthetic_assembly"
    run.mkdir()
    raw=run/"synthetic_raw.parquet"
    keys=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]),"security_uid":["A"]})
    keys.to_parquet(raw,index=False)
    role=kernel.preflight.ROLES[0]
    for year in (2023,2024,2025):
        path=run/f"predictions/native_{role}_{year}.parquet"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b"FAILED_LEFTOVER_MUST_NEVER_BE_READ")
    evaluation=production.prior.REPO/"scripts/research/a2/evaluation"
    sources={str(path):production.prior.sha(path) for path in (
        evaluation/"selector_frozen_history_evidence.py",evaluation/"selector_evidence.py",evaluation/"selector_account_compare.py")}
    context={"design_sha256":"synthetic"}
    design={"sources":sources,"score_reuse":{"RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE":{
        "path":str(raw),"sha256":production.prior.sha(raw)}}}
    monkeypatch.setattr(production,"checked",lambda run:(context,design))
    monkeypatch.setattr(production,"ledger_events",lambda ctx:{
        f"ANNUAL_HEAD:{role}:{year}":{"status":"FAILED"} for year in (2023,2024,2025)})
    def synthetic_output(run,relative):
        path=Path(run)/relative
        kernel.storage_paths.assert_safe_output_path(path,kind="cache")
        path.parent.mkdir(parents=True,exist_ok=True)
        return path
    from pathlib import Path
    monkeypatch.setattr(production,"output",synthetic_output)
    original=pd.read_parquet
    def read(path,*args,**kwargs):
        assert Path(path)==raw,"FAILED_NATIVE_NUMERIC_READ"
        return original(path,*args,**kwargs)
    monkeypatch.setattr(pd,"read_parquet",read)
    result=production.assemble(run)
    assert result["complete_candidates"]==[] and result["complete_fixed_references"]==[]
    assert role in result["failed_or_untestable"]
    assert result["strict_PIT_promotion_eligible"] is False
