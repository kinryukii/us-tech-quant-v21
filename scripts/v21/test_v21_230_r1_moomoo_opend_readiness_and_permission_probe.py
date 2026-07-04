from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_230_r1_moomoo_opend_readiness_and_permission_probe.py")
spec = importlib.util.spec_from_file_location("v21_230_r1", MODULE_PATH)
v230r1 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v230r1)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_guard(root: Path, *, policy_ok: bool = True) -> None:
    policy = {
        "default_data_source_policy": "MOOMOO_ONLY" if policy_ok else "MIXED",
        "yfinance_allowed_by_default": False,
        "yahoo_allowed_by_default": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    write(root / "config/v21/data_source_policy.json", json.dumps(policy))
    write(
        root / "scripts/v21/v21_data_source_policy_guard.py",
        """
import json
from pathlib import Path

def load_data_source_policy(policy_path=None):
    path = Path(policy_path) if policy_path else Path(__file__).resolve().parents[2] / "config/v21/data_source_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))

def assert_yfinance_disabled(context):
    if load_data_source_policy().get("yfinance_allowed_by_default") is not False:
        raise RuntimeError("forbidden provider enabled")

def assert_moomoo_only_policy(context, allow_diagnostic_external=False):
    policy = load_data_source_policy()
    if policy.get("default_data_source_policy") != "MOOMOO_ONLY":
        raise RuntimeError("not moomoo only")
    assert_yfinance_disabled(context)

def policy_flags_for_summary():
    return load_data_source_policy()
""".lstrip(),
    )


def make_v230_inputs(root: Path) -> Path:
    out = root / "outputs/v21/V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
    write(out / "v21_230_summary.json", json.dumps({"final_status": "WARN_V21_230_MOOMOO_ONLY_REFETCH_DRY_RUN_READY_WITH_PREREQUISITES"}))
    write(out / "dry_run_policy_gate.json", json.dumps({"dry_run_only": True, "actual_historical_fetch_allowed_now": False}))
    write(out / "ticker_universe_resolution.csv", "ticker,resolved_symbol,market,included_in_dram,included_in_abcde,included_in_active_universe\nDRAM,US.DRAM,US,True,True,True\nNVDA,US.NVDA,US,False,True,True\nMU,US.MU,US,False,True,True\nAAPL,US.AAPL,US,False,True,True\nAMD,US.AMD,US,False,True,True\nAVGO,US.AVGO,US,False,True,True\n")
    for name in [
        "moomoo_refetch_dry_run_plan.csv",
        "moomoo_frequency_plan.csv",
        "moomoo_adjustment_plan.csv",
        "dram_intraday_refetch_plan.csv",
        "abcde_daily_refetch_plan.csv",
        "v21_231_execution_prerequisites.csv",
    ]:
        write(out / name, "name,value\nx,y\n")
    return out


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    make_guard(root)
    make_v230_inputs(root)
    return root


def test_fails_if_v21_230_input_artifacts_are_missing(tmp_path):
    root = tmp_path / "repo"
    make_guard(root)
    summary = v230r1.run(root, tmp_path / "out", no_moomoo_import=True, disable_network_probe=True)
    assert summary["final_status"] == v230r1.FAIL_INPUT_STATUS


def test_imports_and_uses_policy_guard(tmp_path):
    root = make_repo(tmp_path)
    summary = v230r1.run(root, tmp_path / "out", no_moomoo_import=True, disable_network_probe=True)
    assert summary["policy_guard_found"] is True
    assert summary["policy_guard_passed"] is True


def test_never_imports_yfinance():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text


def test_does_not_import_moomoo_or_futu_at_module_import_time():
    assert "moomoo" not in sys.modules
    assert "futu" not in sys.modules
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_supports_no_moomoo_import(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    summary = v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    assert summary["moomoo_import_attempted"] is False
    rows = read_csv(out / "moomoo_import_probe.csv")
    assert all(r["import_attempted"] == "False" for r in rows)


def test_supports_disable_network_probe(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    summary = v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    assert summary["opend_connection_attempted"] is False
    rows = read_csv(out / "opend_connection_probe.csv")
    assert rows[0]["error_type"] == "NOT_PROBED_DISABLED_BY_FLAG"


def test_creates_policy_gate_with_bulk_historical_fetch_disabled(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    gate = json.loads((out / "opend_probe_policy_gate.json").read_text(encoding="utf-8"))
    assert gate["bulk_historical_fetch_allowed_now"] is False
    assert gate["canonical_rebuild_allowed_now"] is False


def test_includes_dram_in_probe_sample_when_present(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    rows = read_csv(out / "ticker_symbol_probe.csv")
    assert rows[0]["ticker"] == "DRAM"


def test_limits_ticker_probe_count_to_cli_value(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    summary = v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True, max_symbol_probe_count=3)
    assert summary["ticker_probe_count"] == 3
    assert len(read_csv(out / "ticker_symbol_probe.csv")) == 3


def test_does_not_fetch_historical_bars(tmp_path):
    root = make_repo(tmp_path)
    summary = v230r1.run(root, tmp_path / "out", no_moomoo_import=True, disable_network_probe=True)
    assert summary["historical_bulk_fetch_performed"] is False
    assert summary["moomoo_historical_fetch_used"] is False


def test_does_not_write_cache_or_canonical_market_data(tmp_path):
    root = make_repo(tmp_path)
    cache_like = root / "data"
    v230r1.run(root, tmp_path / "out", no_moomoo_import=True, disable_network_probe=True)
    assert not cache_like.exists()


def test_creates_v21_231_go_no_go_gate(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    assert (out / "v21_231_go_no_go_gate.csv").exists()


def test_returns_warn_if_opend_connection_fails_without_policy_violation(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setattr(v230r1, "socket_probe", lambda *args, **kwargs: ([{"check_name": "local_opend_socket", "host": "127.0.0.1", "port": 11111, "attempted": "True", "passed": "False", "latency_ms": 1, "error_type": "ConnectionRefusedError", "error_message": "refused", "severity": "WARN", "notes": ""}], False))
    summary = v230r1.run(root, tmp_path / "out", no_moomoo_import=True)
    assert summary["final_status"] == v230r1.WARN_STATUS


class FakeQuoteContext:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def get_market_snapshot(self, symbols):
        return (0, [{"code": symbols[0], "last_price": 1.0}])

    def request_history_kline(self):
        raise AssertionError("historical bars must not be requested")

    def close(self):
        return None


class FakeSdk:
    RET_OK = 0
    __version__ = "test"
    OpenQuoteContext = FakeQuoteContext


def test_returns_pass_when_mocked_opend_import_and_capabilities_pass(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setattr(v230r1, "socket_probe", lambda *args, **kwargs: ([{"check_name": "local_opend_socket", "host": "127.0.0.1", "port": 11111, "attempted": "True", "passed": "True", "latency_ms": 1, "error_type": "", "error_message": "", "severity": "INFO", "notes": ""}], True))
    monkeypatch.setattr(v230r1, "guarded_import_probe", lambda no_import: ([{"module_name": "moomoo", "import_attempted": "True", "import_passed": "True", "version": "test", "error_type": "", "error_message": "", "notes": ""}], FakeSdk, True))
    summary = v230r1.run(root, tmp_path / "out")
    assert summary["final_status"] == v230r1.PASS_STATUS
    assert summary["v21_231_ready"] is True


def test_returns_fail_on_policy_violation(tmp_path):
    root = tmp_path / "repo"
    make_guard(root, policy_ok=False)
    make_v230_inputs(root)
    summary = v230r1.run(root, tmp_path / "out", no_moomoo_import=True, disable_network_probe=True)
    assert summary["final_status"] == v230r1.FAIL_POLICY_STATUS


def test_writes_no_yfinance_enforcement_audit(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    rows = read_csv(out / "no_yfinance_enforcement_audit.csv")
    assert rows and rows[0]["passed"] == "True"


def test_keeps_broker_and_official_adoption_disabled(tmp_path):
    root = make_repo(tmp_path)
    summary = v230r1.run(root, tmp_path / "out", no_moomoo_import=True, disable_network_probe=True)
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_does_not_unlock_trade_or_perform_broker_actions(tmp_path):
    root = make_repo(tmp_path)
    out = tmp_path / "out"
    v230r1.run(root, out, no_moomoo_import=True, disable_network_probe=True)
    text = MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "unlock_trade(" not in text
    assert "place_order(" not in text
    assert "modify_order(" not in text
    assert "cancel_order(" not in text
    gate = json.loads((out / "opend_probe_policy_gate.json").read_text(encoding="utf-8"))
    assert gate["trade_unlock_allowed"] is False
    assert gate["broker_action_allowed"] is False
