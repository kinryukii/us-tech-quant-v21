from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
from fast3.backtest.cost_model import RoundTripCost
from fast3.backtest.exit_engine import evaluate_exit
from fast3.backtest.portfolio_contract import simulate_primary_portfolio
from fast3.common.contracts import ContractViolation, ExecutableContract
from fast3.labels.executable_trade_label import ETF_MAP, build_executable_trade_labels, stable_event_id
from fast3.validation.nested_purged_walk_forward import NestedPurgedWalkForward
from fast3.compatibility.legacy_v22 import legacy_hash

CONFIG = ROOT / "fast3" / "configs" / "contracts" / "FAST3_002_EXECUTABLE_CONTRACT.json"
GUARD_PATH = ROOT / "fast3" / "scripts" / "audit" / "run_fast3_guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location("fast3_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(GUARD_SPEC); assert GUARD_SPEC.loader is not None; GUARD_SPEC.loader.exec_module(guard)
RUNNER_PATH = ROOT / "fast3" / "scripts" / "run" / "fast3_002_contract_smoke.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("fast3_002_contract_smoke", RUNNER_PATH)
runner = importlib.util.module_from_spec(RUNNER_SPEC); assert RUNNER_SPEC.loader is not None; RUNNER_SPEC.loader.exec_module(runner)
resolve_output_dir, resolve_result_root = runner.resolve_output_dir, runner.resolve_result_root

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
def test_35_canonical_compatibility_targets_exist():
    result = guard.compatibility()
    assert result["compatibility_wrapper_count"] == 3
    assert not result["violations"]

def test_canonical_compatibility_rejects_missing_target(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "REPO", tmp_path)
    target = tmp_path / "fast3/compatibility"
    target.mkdir(parents=True)
    for name in ("run_fast3_overnight_autopilot.ps1", "start_codex_fast3_full_chain.ps1"):
        (target / name).write_text("# synthetic canonical launcher")
    result = guard.compatibility()
    assert result["violations"] == ["compatibility_missing:start_codex_v22_080a.ps1"]
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
def test_42_result_routing_guard_passes():
    result = guard.result_routing()
    legacy = result["legacy_junction"]
    assert not result["violations"]
    assert result["repository_result_file_count"] == 0
    assert result["legacy_compatibility_status"] == "REMOVED_FINALIZED"
    assert result["legacy_logical_path_exists"] is False
    assert result["recursively_scanned"] is False
    assert legacy == {
        "logical_path": str(ROOT / ".local_results"),
        "resolved_target": None,
        "link_type": None,
        "classification": "REMOVED_FINALIZED",
        "legacy_compatibility_status": "REMOVED_FINALIZED",
        "legacy_logical_path_exists": False,
        "physical_link_exists": False,
        "approval_reason": "retired legacy logical path is absent; Junction removal finalized",
        "recursively_scanned": False,
        "violations": [],
    }


def _make_junction(logical: Path, target: Path):
    completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(logical), str(target)], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert os.path.lexists(logical)


def _junction_fixture(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    results = tmp_path / "results"; results.mkdir()
    data = tmp_path / "data"; data.mkdir()
    target = results / "runtime" / "local_results"; target.mkdir(parents=True)
    return repo, results, data, target


def _classify_temp_junction(repo, results, data, target):
    logical = repo / ".local_results"
    return guard.classify_legacy_external_junction(
        logical, repo_root=repo, approved_results_root=results,
        canonical_data_root=data, approved_target=results / "runtime" / "local_results",
    )


def test_43_reintroduced_approved_external_junction_is_rejected_without_scanning(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    (target / "FAST3_historical.parquet").write_bytes(b"outside")
    _make_junction(repo / ".local_results", target)
    result = _classify_temp_junction(repo, results, data, target)
    assert result["classification"] == "REJECTED_LEGACY_JUNCTION_REINTRODUCED"
    assert "LEGACY_JUNCTION_REINTRODUCED" in result["violations"]
    assert result["recursively_scanned"] is False
    assert guard._repository_result_scan(repo) == []


def test_44_plain_local_results_directory_is_rejected(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    (repo / ".local_results").mkdir()
    violations = _classify_temp_junction(repo, results, data, target)["violations"]
    assert "LEGACY_JUNCTION_REINTRODUCED" in violations
    assert "legacy_junction_not_reparse_point" in violations


def test_45_junction_into_repository_is_rejected(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    internal = repo / "internal"; internal.mkdir()
    _make_junction(repo / ".local_results", internal)
    violations = _classify_temp_junction(repo, results, data, target)["violations"]
    assert "LEGACY_JUNCTION_REINTRODUCED" in violations
    assert "legacy_junction_target_inside_repository" in violations


def test_46_junction_into_canonical_data_is_rejected(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    _make_junction(repo / ".local_results", data)
    violations = _classify_temp_junction(repo, results, data, target)["violations"]
    assert "LEGACY_JUNCTION_REINTRODUCED" in violations
    assert "legacy_junction_target_inside_canonical_data_root" in violations


def test_47_junction_to_unapproved_external_path_is_rejected(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    other = tmp_path / "other"; other.mkdir()
    _make_junction(repo / ".local_results", other)
    violations = _classify_temp_junction(repo, results, data, target)["violations"]
    assert "LEGACY_JUNCTION_REINTRODUCED" in violations
    assert "legacy_junction_target_outside_approved_results_root" in violations


def test_48_junction_with_missing_target_is_rejected(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    _make_junction(repo / ".local_results", target)
    target.rmdir()
    violations = _classify_temp_junction(repo, results, data, target)["violations"]
    assert "LEGACY_JUNCTION_REINTRODUCED" in violations
    assert "legacy_junction_target_unresolvable" in violations


@pytest.mark.parametrize("suffix", [".parquet", ".bin", ".pickle"])
def test_49_repository_binary_result_files_are_rejected_without_following_junction(tmp_path, suffix):
    repo, results, data, target = _junction_fixture(tmp_path)
    outputs = repo / "outputs"; outputs.mkdir()
    (outputs / f"FAST3_real{suffix}").write_bytes(b"repository")
    _make_junction(repo / ".local_results", target)
    files = guard._repository_result_scan(repo)
    assert [path.name for path in files] == [f"FAST3_real{suffix}"]
    bloat_root = tmp_path / "bloat"; (bloat_root / "configs" / "runtime").mkdir(parents=True)
    shutil.copy(ROOT / "fast3" / "configs" / "runtime" / "FAST3_ANTI_BLOAT_LIMITS.json", bloat_root / "configs" / "runtime" / "FAST3_ANTI_BLOAT_LIMITS.json")
    (bloat_root / f"real{suffix}").write_bytes(b"repository")
    assert guard.bloat(bloat_root)["violations"]


def test_50_windows_case_and_normalization_cannot_bypass_approval(tmp_path):
    repo, results, data, target = _junction_fixture(tmp_path)
    escaped = results / "runtime" / "other"; escaped.mkdir(parents=True)
    _make_junction(repo / ".local_results", escaped)
    result = _classify_temp_junction(repo, results, data, escaped)
    assert "LEGACY_JUNCTION_REINTRODUCED" in result["violations"]
    assert "legacy_junction_target_not_approved_compatibility_target" in result["violations"]
    # Case variants still identify the same policy root, but a different canonical target remains rejected.
    assert guard._is_within(escaped, Path(str(results).upper()))


STORAGE_RUNNERS = (
    "run_fast3_minimal_empirical_validation_agent.ps1",
    "run_fast3_event_factor_law_discovery_agent.ps1",
    "run_fast3_event_factor_law_discovery_r2_agent.ps1",
    "run_fast3_event_factor_cohort_r3_agent.ps1",
    "run_fast3_r3_economic_integrity_audit_agent.ps1",
)
STORAGE_AGENT_DIR = ROOT / "scripts" / "fast3" / "agent"


def _storage_contract_result(external_root=r"D:\us-tech-quant-results"):
    helper = STORAGE_AGENT_DIR / "fast3_storage_contract_r1.ps1"
    command = (
        f"& {{ . '{helper}'; Resolve-Fast3StorageContract -RepoRoot '{ROOT}' "
        f"-ExternalResultsRoot '{external_root}' -CacheRoot 'D:\\us-tech-quant-cache' | ConvertTo-Json -Compress }}"
    )
    completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_51_all_active_runners_default_to_external_storage_contract():
    contract = _storage_contract_result()
    assert set(contract) >= {"RuntimeRoot", "ScratchRoot", "FrozenRoot", "ArchiveRoot", "CacheRoot"}
    assert all(not guard._is_within(Path(contract[key]), ROOT) for key in ("RuntimeRoot", "ScratchRoot", "FrozenRoot", "ArchiveRoot", "CacheRoot"))
    for name in STORAGE_RUNNERS:
        source = (STORAGE_AGENT_DIR / name).read_text(encoding="utf-8")
        assert ".local_results" not in source
        assert "Resolve-Fast3StorageContract" in source
        assert "$RuntimeResultsBase" in source and "$FrozenResultsBase" in source


def test_52_legacy_runner_argument_maps_only_to_approved_external_target():
    legacy = _storage_contract_result(str(ROOT / ".local_results"))
    assert legacy["ResultsRoot"] == r"D:\us-tech-quant-results"
    assert legacy["LegacyCompatibilityRoot"] == r"D:\us-tech-quant-results\runtime\local_results"
    assert legacy["configured_path"] == r"D:\us-tech-quant\.local_results"
    assert legacy["resolved_path"] == r"D:\us-tech-quant-results\runtime\local_results"
    assert legacy["classification"] == "LEGACY_PATH_ALIAS_AFTER_JUNCTION_REMOVAL"
    assert legacy["physical_link_exists"] is False
    assert legacy["approval_reason"] == "exact retired legacy path mapped to approved external runtime target"
    assert _storage_contract_result(r"D:\us-tech-quant-results")["RuntimeRoot"] == r"D:\us-tech-quant-results\runtime"


def test_53_unapproved_legacy_runner_argument_fails_closed():
    helper = STORAGE_AGENT_DIR / "fast3_storage_contract_r1.ps1"
    command = (
        f"& {{ . '{helper}'; Resolve-Fast3StorageContract -RepoRoot '{ROOT}' "
        "-ExternalResultsRoot 'D:\\us-tech-quant-data' -CacheRoot 'D:\\us-tech-quant-cache' }"
    )
    completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], text=True, capture_output=True)
    assert completed.returncode != 0
    assert "approved" in completed.stderr.lower()


@pytest.mark.parametrize("path", [
    r"D:\us-tech-quant\.LOCAL_RESULTS",
    r"D:\us-tech-quant\.local_results\\",
    r"D:\us-tech-quant\subdir\\..\.local_results",
    r"D:\us-tech-quant\.local_results\child",
    r"D:\us-tech-quant\other-missing-path",
])
def test_54_only_exact_missing_legacy_alias_is_accepted(path):
    helper = STORAGE_AGENT_DIR / "fast3_storage_contract_r1.ps1"
    command = (
        f"& {{ . '{helper}'; Resolve-Fast3StorageContract -RepoRoot '{ROOT}' "
        f"-ExternalResultsRoot '{path}' -CacheRoot 'D:\\us-tech-quant-cache' }}"
    )
    completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], text=True, capture_output=True)
    assert completed.returncode != 0
