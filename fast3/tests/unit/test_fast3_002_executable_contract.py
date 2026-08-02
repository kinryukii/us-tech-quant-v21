from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import shutil

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
from fast3.src.fast3.backtest.cost_model import RoundTripCost
from fast3.src.fast3.backtest.exit_engine import evaluate_exit
from fast3.src.fast3.backtest.portfolio_contract import simulate_primary_portfolio
from fast3.src.fast3.common.contracts import ContractViolation, ExecutableContract
from fast3.src.fast3.labels.executable_trade_label import ETF_MAP, build_executable_trade_labels, stable_event_id
from fast3.src.fast3.validation.nested_purged_walk_forward import NestedPurgedWalkForward
from fast3.src.fast3.compatibility.legacy_v22 import legacy_hash
from fast3.scripts.run.fast3_002_contract_smoke import resolve_output_dir, resolve_result_root

CONFIG = ROOT / "fast3" / "configs" / "contracts" / "FAST3_002_EXECUTABLE_CONTRACT.json"
GUARD_PATH = ROOT / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location("fast3_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(GUARD_SPEC); assert GUARD_SPEC.loader is not None; GUARD_SPEC.loader.exec_module(guard)

def bars(values=None, session="RTH", start="2024-01-02 09:30"):
    values = values or [(100, 100, 100, 100), (100, 101, 99, 100), (100, 100, 100, 100)]
    et = pd.date_range(start, periods=len(values), freq="min", tz="America/New_York")
    return pd.DataFrame({"timestamp_et": et, "timestamp_utc": et.tz_convert("UTC"), "broker_trade_date": [et[0].date().isoformat()] * len(et), "session": session, "open": [x[0] for x in values], "high": [x[1] for x in values], "low": [x[2] for x in values], "close": [x[3] for x in values]})

@pytest.fixture
def contract():
    return ExecutableContract.from_file(CONFIG)

@pytest.fixture
def signals():
    return pd.DataFrame([{"decision_timestamp_et": pd.Timestamp("2024-01-02 09:30", tz="America/New_York"), "underlying_symbol": "SOXX", "direction": "UP"}])

def label(contract, signals, values=None, mode=None):
    return build_executable_trade_labels(signals, {"SOXL": bars(values)}, contract, 10, mode)

def test_01_config_hash_frozen(contract): assert len(contract.config_hash) == 64
def test_02_decision_bar_cannot_fill_same_bar(contract, signals): assert label(contract, signals).entry_timestamp_et.iat[0] > signals.decision_timestamp_et.iat[0]
def test_03_next_bar_open_alignment(contract, signals): assert label(contract, signals).entry_price.iat[0] == 100
def test_04_vwap_proxy_predeclared(contract, signals): assert "VWAP_PROXY" in label(contract, signals, mode="MODE_B_NEXT_BAR_VWAP_PROXY").entry_price_source.iat[0]
def test_05_et_utc_consistent(): assert bars().timestamp_et.dt.tz_convert("UTC").equals(bars().timestamp_utc)
def test_06_broker_trade_date_preserved(): assert bars(start="2024-01-02 23:59").broker_trade_date.iat[0] == "2024-01-02"
def test_07_real_soxl_mapping(): assert ETF_MAP[("SOXX", "UP")] == "SOXL"
def test_08_real_soxs_mapping(): assert ETF_MAP[("SOXX", "DOWN")] == "SOXS"
def test_09_no_underlying_times_three(contract, signals): assert label(contract, signals).trade_symbol.iat[0] == "SOXL"
def test_10_cost_10bps_round_trip(): assert RoundTripCost(10).entry_cost == RoundTripCost(10).exit_cost == .0005
def test_11_cost_20bps_round_trip(): assert RoundTripCost(20).total_cost == .002
def test_12_cost_only_once(): assert RoundTripCost(10).net_return(.03) == pytest.approx(.029)
def test_13_same_bar_stop_first():
    x=evaluate_exit(bars=bars([(100,100,100,100),(100,104,98,100)]),entry_timestamp_et=pd.Timestamp("2024-01-02 09:31",tz="America/New_York"),entry_price=100,max_holding_minutes=60,target_net_return=.03,stop_gross_return=-.015,cost=RoundTripCost(10)); assert x.exit_reason=="STOP" and x.exit_ambiguity
def test_14_fixed_timeout():
    x=evaluate_exit(bars=bars([(100,100,100,100)]*4),entry_timestamp_et=pd.Timestamp("2024-01-02 09:30",tz="America/New_York"),entry_price=100,max_holding_minutes=2,target_net_return=.03,stop_gross_return=-.015,cost=RoundTripCost(10)); assert x.exit_reason=="TIMEOUT"
def test_15_session_exit():
    x=evaluate_exit(bars=bars(session="AFTER_HOURS"),entry_timestamp_et=pd.Timestamp("2024-01-02 09:30",tz="America/New_York"),entry_price=100,max_holding_minutes=60,target_net_return=.03,stop_gross_return=-.015,cost=RoundTripCost(10),force_exit_sessions=("AFTER_HOURS",)); assert x.exit_reason=="SESSION_FORCED"
def test_16_data_end_exit():
    x=evaluate_exit(bars=bars([(100,100,100,100)]),entry_timestamp_et=pd.Timestamp("2024-01-02 09:30",tz="America/New_York"),entry_price=100,max_holding_minutes=60,target_net_return=.03,stop_gross_return=-.015,cost=RoundTripCost(10)); assert x.exit_reason=="DATA_END_CLOSE_PROXY"
def _labels():
    t=pd.Timestamp("2024-01-02 09:30",tz="America/New_York"); return pd.DataFrame([{"event_id":"a","decision_timestamp_et":t,"exit_timestamp_et":t+pd.Timedelta(hours=24),"direction":"UP","net_return":.01,"priority":0},{"event_id":"b","decision_timestamp_et":t+pd.Timedelta(minutes=1),"exit_timestamp_et":t+pd.Timedelta(hours=24),"direction":"UP","net_return":.01,"priority":0}])
def test_17_overlap_rejected(): assert simulate_primary_portfolio(_labels())[1]["REJECTED_OVERLAP_COUNT"] == 1
def test_18_exit_releases_capital():
    x=_labels(); x.loc[0,"exit_timestamp_et"]=x.decision_timestamp_et.iat[0]; assert simulate_primary_portfolio(x)[1]["ACCEPTED_TRADE_COUNT"] == 2
def test_19_opposite_conflict_rejected():
    x=_labels(); x.loc[1,"direction"]="DOWN"; assert simulate_primary_portfolio(x)[1]["REJECTED_CONFLICT_COUNT"] == 1
def test_20_duplicate_event_deduped():
    x=pd.concat([_labels().iloc[:1],_labels().iloc[:1]],ignore_index=True); assert simulate_primary_portfolio(x)[1]["DEDUPED_SIGNAL_COUNT"] == 1
def test_21_stable_event_id(): assert stable_event_id("SOXX","UP",pd.Timestamp("2024-01-02",tz="America/New_York")) == stable_event_id("SOXX","UP",pd.Timestamp("2024-01-02",tz="America/New_York"))
def test_22_purge_removes_overlapping_label():
    t=pd.Timestamp("2024-01-01",tz="America/New_York"); x=pd.DataFrame({"decision_timestamp_et":[t,t+pd.Timedelta(days=2),t+pd.Timedelta(days=4)],"label_end_timestamp_et":[t+pd.Timedelta(days=2),t+pd.Timedelta(days=3),t+pd.Timedelta(days=5)]}); f=list(NestedPurgedWalkForward().split_outer(x,2)); assert all(set(a.train_index).isdisjoint(a.test_index) for a in f)
def test_23_embargo_boundary(): assert NestedPurgedWalkForward(1440,1440).purge_minutes == 1440
def test_24_scaler_fit_train_only():
    class S:
        def fit(self,x): self.mean=float(np.mean(x)); return self
        def transform(self,x): return np.asarray(x)-self.mean
    _,z=NestedPurgedWalkForward().fit_scaler_train_only(S(),np.array([1.,3.]),np.array([100.])); assert z[0] == 98
def test_25_confirmation_forbidden(contract):
    x=pd.DataFrame([{"decision_timestamp_et":pd.Timestamp("2025-02-08",tz="America/New_York"),"underlying_symbol":"SOXX","direction":"UP"}]);
    with pytest.raises(ContractViolation): build_executable_trade_labels(x,{"SOXL":bars()},contract,10)
def test_26_diagnostic_not_executable(contract, signals): assert label(contract,signals,[(100,100,100,100),(100,102,98,100),(100,100,100,100)]).opportunity_label.iat[0] != label(contract,signals,[(100,100,100,100),(100,102,98,100),(100,100,100,100)]).executable_trade_label.iat[0]
def test_27_real_etf_loss_overrides_underlying_up(contract, signals): assert label(contract,signals,[(100,100,100,100),(100,100,98,99),(99,99,99,99)]).net_return.iat[0] < 0
def test_28_portfolio_not_simple_overlap_sum(): assert simulate_primary_portfolio(_labels())[1]["ACCEPTED_TRADE_COUNT"] == 1
def test_29_architecture_guard_passes(): assert not guard.architecture()["violations"]
def test_30_single_source_guard_passes(): assert not guard.single_source()["violations"]
def test_31_registry_hygiene_guard_passes(): assert not guard.registry_hygiene()["violations"]
def test_32_forbidden_patterns_guard_passes():
    x=guard.forbidden_patterns(); assert x["direct_legacy_v22_import_count"] == x["sys_path_hack_count"] == 0
def test_33_bloat_guard_rejects_binary_fixture(tmp_path):
    config=tmp_path/"configs"/"runtime"; config.mkdir(parents=True); shutil.copy(ROOT/"fast3"/"configs"/"runtime"/"FAST3_ANTI_BLOAT_LIMITS.json",config/"FAST3_ANTI_BLOAT_LIMITS.json"); (tmp_path/"forbidden.parquet").write_bytes(b"x"); assert guard.bloat(tmp_path)["violations"]
def test_34_formal_config_is_unique():
    x=json.loads((ROOT/"fast3"/"manifests"/"registries"/"FAST3_CONFIG_REGISTRY.json").read_text()); assert sum(c["canonical"] for c in x["configs"] if c["stage_id"] == "FAST3-002") == 1
def test_35_root_compatibility_targets_exist(): assert guard.compatibility()["compatibility_wrapper_count"] == 3
def test_36_no_repo_result_directory(): assert not (ROOT/"fast3"/"outputs").exists() and not (ROOT/"fast3"/"stages").exists()
def test_37_guard_nonzero_for_constructed_violation(monkeypatch):
    monkeypatch.setattr(guard,"architecture",lambda:{"name":"fixture","violations":["fixture_violation"]}); assert guard.main([]) == 1
def test_38_legacy_adapter_hashes_only_allowed_path(): assert len(legacy_hash("v22_080b")) == 64
def test_39_result_root_resolves_from_state(): assert resolve_result_root() == Path(r"D:\us-tech-quant-results\fast3")
def test_40_non_test_mode_rejects_repo_result_path(monkeypatch):
    monkeypatch.delenv("FAST3_TEST_MODE", raising=False)
    with pytest.raises(ValueError): resolve_output_dir(str(ROOT / "fast3" / "outputs"))
def test_41_test_mode_allows_pytest_tmp_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FAST3_TEST_MODE", "1"); assert resolve_output_dir(str(tmp_path)) == tmp_path
def test_42_result_routing_guard_passes(): assert not guard.result_routing()["violations"]
