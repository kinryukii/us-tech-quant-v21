from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fast3.backtest.cost_model import RoundTripCost
from fast3.labels.executable_trade_label import ETF_MAP
from fast3.robustness.contract import ContractError, EvaluationContract
from fast3.robustness.ledger import ExperimentLedger, LedgerError
from fast3.robustness.statistics import (deflated_sharpe, generate_cpcv_splits, monthly_concentration,
                                          not_computable, pbo, probabilistic_sharpe)


TARGET = "93626b477aab7ef422da66a421cd6b45b63781ad462c5ecaa430acdcfdde7056"
RECOVERED = Path(r"D:\us-tech-quant-results\frozen\fast3\r27_runner_provenance_recovery_20260806T123749779986Z\recovered_runner.py")
ROOT = Path(__file__).resolve().parents[3]


def contract(**changes):
    fields = dict(contract_version="R27", evaluator_version="R1", dataset_manifest_path="D:/dataset.json", dataset_hash="a"*64,
        label_contract_id="labels", execution_contract_id="next-bar-open", cost_contract_id="10-20bps", split_contract_id="split",
        feature_set_id="features", feature_set_hash="b"*64, model_id="hgb", model_config_hash="c"*64, model_artifact_hash="d"*64,
        frozen_runner_path=str(RECOVERED), frozen_runner_hash=TARGET, recovery_manifest_path="D:/recovery.json", recovery_manifest_hash="e"*64,
        split_manifest_path="D:/split.json", purge_minutes=1440, embargo_minutes=1440,
        train_windows=({"start":"2018-01-01T00:00:00Z","end":"2018-01-02T00:00:00Z","timezone":"UTC"},),
        development_windows=({"start":"2018-01-03T00:00:00Z","end":"2018-01-04T00:00:00Z","timezone":"UTC"},),
        confirmation_windows=({"start":"2018-01-05T00:00:00Z","end":"2018-01-06T00:00:00Z","timezone":"UTC"},),
        final_windows=({"start":"2018-01-07T00:00:00Z","end":"2018-01-08T00:00:00Z","timezone":"UTC"},),
        random_seed=7, top_k_definition="top5", attempted_model_count=1, attempted_configuration_count=4, attempted_seed_count=1,
        source_branch="feature/fast3-007-robustness-gate", source_commit="4213b13bb5529b85a4df40d855452f2a67f99f2f")
    fields.update(changes); return EvaluationContract(**fields)


def record(identifier: str) -> dict:
    return dict(experiment_id=identifier,parent_experiment_id="parent",created_at_utc="2026-01-01T00:00:00Z",source_branch="branch",source_commit="commit",dirty_worktree=False,evaluator_version="R1",evaluation_contract_hash="a"*64,dataset_hash="b"*64,feature_set_hash="c"*64,model_config_hash="d"*64,model_artifact_hash="e"*64,frozen_runner_hash=TARGET,random_seed=1,attempted_model_count=1,attempted_configuration_count=4,attempted_seed_count=1,train_window=[],development_window=[],confirmation_window=[],final_window=[],purge_minutes=1440,embargo_minutes=1440,cost_bps=[10,20],gross_metrics={},net_metrics={},robustness_metrics={},decision="PASS",rejection_reason="",artifact_paths={})


def events():
    stamp=pd.date_range("2020-01-01", periods=24, freq="D", tz="UTC")
    return pd.DataFrame({"event_id":[f"e{x}" for x in range(len(stamp))],"decision_timestamp_et":stamp,"label_end_timestamp_et":stamp+pd.Timedelta(hours=24)})


def windows():
    return [{"block_id":f"D{x}","start":f"2020-01-{1+6*x:02d}T00:00:00Z","end":f"2020-01-{6+6*x:02d}T23:59:59Z","timezone":"UTC"} for x in range(4)]


def test_recovered_runner_hash_and_current_runner_not_overwritten():
    assert RECOVERED.is_file() and hashlib.sha256(RECOVERED.read_bytes()).hexdigest() == TARGET
    current=ROOT/"fast3/scripts/run/fast3_r4_two_stage_direction_hard_r25.py"
    assert hashlib.sha256(current.read_bytes()).hexdigest() == "8a15aae8477f5edf26d17f21f591bf509db3ea856bac52a4fc5c3307f54c78e5"


def test_contract_determinism_validation_and_immutability():
    first=contract(); second=contract(train_windows=tuple(reversed(list(contract().train_windows))))
    assert first.evaluation_contract_hash == second.evaluation_contract_hash
    assert first.evaluation_contract_hash != contract(random_seed=8).evaluation_contract_hash
    with pytest.raises(ContractError): contract(dataset_hash="")
    with pytest.raises(ContractError): contract(feature_set_hash=float("nan"))
    with pytest.raises(FrozenInstanceError): first.random_seed = 8


def test_ledger_append_duplicate_invalid_and_concurrent(tmp_path):
    ledger=ExperimentLedger(tmp_path/"ledger.jsonl"); ledger.append(record("one")); assert len(ledger.path.read_text().splitlines()) == 1
    with pytest.raises(LedgerError): ledger.append(record("one"))
    with pytest.raises(LedgerError): ledger.append({"experiment_id":"bad"})
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(lambda x: ledger.append(record(f"thread-{x}")), range(4)))
    rows=[json.loads(x) for x in ledger.path.read_text().splitlines()]; assert len(rows)==5 and len({x["experiment_id"] for x in rows})==5


def test_cpcv_time_order_purge_embargo_and_determinism():
    first=generate_cpcv_splits(events(),windows(),test_window_count=2,purge_minutes=1440,embargo_minutes=1440)
    second=generate_cpcv_splits(events(),windows(),test_window_count=2,purge_minutes=1440,embargo_minutes=1440)
    assert first == second and len(first)==6
    assert all(x["overlap_violation_count"]==0 and x["time_order_violation_count"]==0 for x in first)
    assert all(x["purge_removed_count"]>=0 and x["embargo_removed_count"]>=0 for x in first)


def test_pbo_psr_dsr_and_concentration_fixtures():
    scores=pd.DataFrame({"candidate_id":["a","a","b","b"],"split_id":["x","y","x","y"],"score":[.9,.8,.2,.1]})
    assert isinstance(pbo(scores),float) and pbo(scores.head(2)) == not_computable("INSUFFICIENT_REAL_CANDIDATES")
    values=[.02,-.01,.03,-.005,.01,.015]
    assert isinstance(probabilistic_sharpe(values)["value"],float)
    assert deflated_sharpe(values,attempted_models=1,attempted_configurations=8,attempted_seeds=1)["value"] <= deflated_sharpe(values,attempted_models=1,attempted_configurations=1,attempted_seeds=1)["value"]
    assert probabilistic_sharpe([.01,.01,.01])["value"] == not_computable("ZERO_VARIANCE_RETURNS")
    assert probabilistic_sharpe([.01])["value"] == not_computable("SHORT_RETURN_SERIES")
    frame=pd.DataFrame({"ts":pd.to_datetime(["2020-01-01","2020-02-01","2020-03-01"],utc=True),"r":[1.,2.,-1.]})
    assert monthly_concentration(frame,timestamp_column="ts",return_column="r")["best_month_contribution_ratio"] == 2/3


def test_existing_execution_cost_mapping_and_safety_flags():
    assert ETF_MAP[("SOXX","UP")] == "SOXL" and ETF_MAP[("SOXX","DOWN")] == "SOXS"
    assert RoundTripCost(10).net_return(0) == -.001 and RoundTripCost(20).net_return(0) == -.002
    assert not any((ROOT/"fast3").rglob("*live*launcher*"))
