from __future__ import annotations

import json
from pathlib import Path
import uuid

import pandas as pd
import pytest

import a2_open_research_engine as engine


def test_split_purges_overlapping_labels() -> None:
    rows=[]
    for date,target_end in [
        ("2020-12-01","2020-12-30"),("2020-12-20","2021-01-20"),
        ("2021-01-04","2021-02-02"),("2021-02-01","2021-03-01"),
    ]:
        rows.append({"signal_date":pd.Timestamp(date),"target_end_date":pd.Timestamp(target_end),"ticker":"A","target":0.0})
    train,valid,audit=engine.split_before_year(pd.DataFrame(rows),2021)
    assert train.signal_date.tolist()==[pd.Timestamp("2020-12-01")]
    assert valid.signal_date.min()==pd.Timestamp("2021-01-04")
    assert audit["max_train_label_maturity"]<audit["validation_start"]


def test_pre2026_guard_rejects_label_maturity_crossing_cutoff() -> None:
    path=Path(r"D:\us-tech-quant-results")/f"_a2_open_guard_test_{uuid.uuid4().hex}.parquet"
    config={"research_dataset":str(path),"cutoff":"2026-01-01T00:00:00","base_features":["ret_1d"]}
    try:
        pd.DataFrame({
            "signal_date":[pd.Timestamp("2025-12-20")],"target_end_date":[pd.Timestamp("2026-01-02")],
            "next_execution_date":[pd.Timestamp("2025-12-22")],"security_id":["A"],"ticker":["A"],
            "report_quarter":["2025Q4"],"target":[0.1],"ret_1d":[0.01],
        }).to_parquet(path,index=False)
        with pytest.raises(engine.GovernanceError,match="POST2025_LABEL_MATURITY_READ"):
            engine.guarded_pre2026_frame(config)
    finally:
        path.unlink(missing_ok=True)


def test_search_space_is_deterministic_and_bounded() -> None:
    config=json.loads(engine.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    first=engine.generate_search_specs(config); second=engine.generate_search_specs(config)
    assert first==second
    assert len(first)==sum(config["trial_budgets"].values())
    assert set(item["family"] for item in first)==set(config["trial_budgets"])
    assert config["top_k_grid"]==[10,15,20,25,30,40]


def test_factor_registry_has_required_lineage_fields() -> None:
    registry=pd.DataFrame(engine.factor_definitions("abc"),columns=engine.FACTOR_COLUMNS)
    assert list(registry.columns)==engine.FACTOR_COLUMNS
    assert registry.factor_id.is_unique
    assert registry.factor_name.is_unique
    assert registry.complexity.max()<=4


def test_trial_ledger_refuses_duplicate_identity() -> None:
    path=Path(r"D:\us-tech-quant-results")/f"_a2_open_ledger_test_{uuid.uuid4().hex}.parquet"
    try:
        ledger=engine.TrialLedger(path)
        row={column:"" for column in engine.LEDGER_COLUMNS}; row["trial_id"]="T1"
        ledger.append([row])
        with pytest.raises(engine.GovernanceError,match="OVERWRITE"):
            ledger.append([row])
    finally:
        path.unlink(missing_ok=True)
