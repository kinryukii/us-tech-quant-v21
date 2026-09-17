from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import subprocess
import shutil
import time
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "v22_047_r1d_live_market_account_bridge.py"
PLUGIN_PATH = HERE / "v22_047_r1b_strategy_plugin_template.py"
spec = importlib.util.spec_from_file_location("v22_047_r1d_test", MODULE_PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def profile(path: Path, host="127.0.0.1", port=18441):
    path.write_text(json.dumps({"host": host, "port": port}), encoding="utf-8")


def test_fixed_symbol_roles_and_endpoint_contract(tmp_path):
    assert m.BENCHMARK_SYMBOL == "US.QQQ"
    assert m.EXECUTION_SYMBOLS == ("US.IQQ", "US.TQQQ", "US.SQQQ")
    path = tmp_path / "profile.json"
    profile(path)
    assert m.load_connection_profile(path)["port"] == 18441


@pytest.mark.parametrize("host,port", [("0.0.0.0", 18441), ("127.0.0.1", 11111)])
def test_wrong_endpoint_rejected(tmp_path, host, port):
    path = tmp_path / "profile.json"
    profile(path, host, port)
    with pytest.raises(m.R1DError):
        m.load_connection_profile(path)


def test_sensitive_connection_fields_rejected(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"host": "127.0.0.1", "port": 18441, "password": "secret"}), encoding="utf-8")
    with pytest.raises(m.R1DError, match="SENSITIVE"):
        m.load_connection_profile(path)


def test_strategy_template_exact_unconfigured_contract():
    spec2 = importlib.util.spec_from_file_location("strategy_r1d_test", PLUGIN_PATH)
    assert spec2 and spec2.loader
    plugin = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(plugin)
    result = plugin.generate_decision({})
    assert result == {"action": "HOLD", "symbol": None, "target_notional_usd": 0.0,
                      "confidence": 0.0, "reason_code": "STRATEGY_NOT_CONFIGURED", "metadata": {}}


def test_no_broker_mutation_calls_in_source():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden = {"place_order", "modify_order", "cancel_order", "cancel_all_order", "unlock_trade"}
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not forbidden.intersection(called)


def test_ui_is_loopback_and_live_paper_unavailable():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in text
    assert "NOT AVAILABLE IN R1D" in text
    assert '(HOST, port)' in text


def test_failed_snapshots_are_fail_closed():
    market = m.failed_market("test")
    account = m.failed_account("test")
    assert market["snapshot_ready"] is False
    assert market["all_quotes_fresh"] is False
    assert account["account_snapshot_ready"] is False


def test_quote_age_parses_new_york_timestamp():
    now = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    timestamp, age = m.parse_quote_time("2026-07-13 10:00:00", now)
    assert timestamp is not None
    assert age == pytest.approx(0.0)


def test_masked_id_does_not_expose_value():
    result = m.masked_id("123456789")
    assert result.startswith("MASKED_")
    assert "123456789" not in result


def test_trade_rows_remove_sensitive_identifiers():
    clean = m.safe_trade_rows([{"code": "US.IQQ", "order_id": "secret-order", "acc_id": 123,
                                "qty": 2, "price": 25, "order_status": "SUBMITTED"}])
    assert clean == [{"code": "US.IQQ", "stock_name": None, "trd_side": None,
                      "order_type": None, "order_status": "SUBMITTED", "qty": 2, "price": 25,
                      "create_time": None, "updated_time": None, "dealt_qty": None,
                      "dealt_avg_price": None, "last_err_msg": None}]
    assert "secret-order" not in json.dumps(clean)


def test_single_instance_reclaims_stale_lock(tmp_path):
    lock_path = tmp_path / "engine.lock"
    lock_path.write_text("99999999", encoding="ascii")
    lock = m.SingleInstance(lock_path)
    lock.acquire()
    assert lock.acquired
    lock.release()
    assert not lock_path.exists()


def test_current_process_is_detected_alive():
    assert m.SingleInstance.alive(os.getpid()) is True


@pytest.mark.parametrize("owner", ["", "invalid", "0", "-1", str(os.getpid())])
def test_single_instance_preserves_unknown_and_legacy_live_owners(tmp_path, owner):
    path = tmp_path / "service.lock"
    path.write_text(owner, encoding="ascii")
    lock = m.SingleInstance(path)
    with pytest.raises(m.R1DError):
        lock.acquire()
    lock.release()
    assert path.read_text(encoding="ascii") == owner


def test_single_instance_release_preserves_changed_owner(tmp_path):
    path = tmp_path / "service.lock"
    lock = m.SingleInstance(path)
    lock.acquire()
    path.write_text("99999999", encoding="ascii")
    lock.release()
    assert not lock.acquired
    assert path.read_text(encoding="ascii") == "99999999"


def test_single_instance_release_does_not_hide_unlink_denial(tmp_path, monkeypatch):
    path = tmp_path / "service.lock"
    lock = m.SingleInstance(path)
    lock.acquire()
    original_unlink = Path.unlink
    def denied_unlink(target, *args, **kwargs):
        if target == path:
            raise PermissionError("synthetic persistent unlink denial")
        return original_unlink(target, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", denied_unlink)
    with pytest.raises(PermissionError, match="synthetic persistent"):
        lock.release()
    assert not lock.acquired
    assert path.read_text(encoding="ascii") == str(os.getpid())


_LOCK_TEST_CHILD = r'''
import importlib.util, json, os, sys, time
from pathlib import Path
source, root, role = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location('synthetic_lock_source', source)
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
spec.loader.exec_module(module)
def wait(path):
    deadline = time.monotonic() + 10
    while not path.exists() and time.monotonic() < deadline: time.sleep(.01)
    assert path.exists(), str(path)
original_alive = module.SingleInstance.alive
def paused_alive(pid):
    result = original_alive(pid)
    if role != 'crash' and pid == 99999999 and not result:
        (root / (role + '.ready')).touch()
        wait(root / (role + '.go'))
    return result
module.SingleInstance.alive = staticmethod(paused_alive)
lock = module.SingleInstance(root / 'service.lock')
try:
    try:
        lock.acquire()
        value = {'acquired': True, 'pid': os.getpid()}
    except module.R1DError as exc:
        value = {'acquired': False, 'pid': os.getpid(), 'error': str(exc)}
    temporary = root / (role + '.result.tmp')
    temporary.write_text(json.dumps(value))
    temporary.replace(root / (role + '.result.json'))
    if role == 'crash': os._exit(23)
    if lock.acquired: wait(root / (role + '.stop'))
finally:
    lock.release()
'''


def _wait_for_lock_test(condition):
    deadline = time.monotonic() + 10
    while not condition() and time.monotonic() < deadline:
        time.sleep(.01)
    assert condition(), "Synthetic lock process did not reach its bounded checkpoint"


def test_single_instance_concurrent_stale_claim_keeps_one_readable_owner(tmp_path):
    path = tmp_path / "service.lock"
    path.write_text("99999999", encoding="ascii")
    processes = []
    def start(role):
        process = subprocess.Popen([sys.executable, "-B", "-c", _LOCK_TEST_CHILD, str(MODULE_PATH), str(tmp_path), role],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(process)
        return process
    def result(role):
        _wait_for_lock_test(lambda: (tmp_path / f"{role}.result.json").exists())
        return json.loads((tmp_path / f"{role}.result.json").read_text())
    try:
        first = start("a")
        _wait_for_lock_test(lambda: (tmp_path / "a.ready").exists())
        start("b")
        _wait_for_lock_test(lambda: (tmp_path / "b.ready").exists() or (tmp_path / "b.result.json").exists())
        (tmp_path / "a.go").touch()
        first_result = result("a")
        (tmp_path / "b.go").touch()
        second_result = result("b")
        assert first_result["acquired"] and not second_result["acquired"]
        assert first.poll() is None
        owner = str(first_result["pid"])
        assert path.read_text(encoding="ascii") == owner
        assert path.stat().st_size == len(owner)  # EOF byte lock adds no file bytes.
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell:
            reader = tmp_path / "read-pid.ps1"
            reader.write_text("param($LockPath)\nGet-Content -LiteralPath $LockPath -Raw\n")
            read = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(reader), str(path)],
                capture_output=True, text=True, timeout=10)
            assert read.returncode == 0, read.stderr
            assert read.stdout.strip() == owner
    finally:
        for role in ("a", "b"):
            (tmp_path / f"{role}.go").touch()
            (tmp_path / f"{role}.stop").touch()
        for process in processes:
            _, error = process.communicate(timeout=12)
            assert process.returncode == 0, error.decode(errors="replace")
    assert not path.exists()
    restarted = m.SingleInstance(path)
    restarted.acquire()
    restarted.release()
    assert not path.exists()


def test_single_instance_crash_releases_os_lock_and_preserves_restart(tmp_path):
    process = subprocess.run([sys.executable, "-B", "-c", _LOCK_TEST_CHILD, str(MODULE_PATH), str(tmp_path), "crash"],
        capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert process.returncode == 23, process.stderr
    prior = json.loads((tmp_path / "crash.result.json").read_text())
    assert prior["acquired"] and not m.SingleInstance.alive(prior["pid"])
    path = tmp_path / "service.lock"
    assert path.read_text(encoding="ascii") == str(prior["pid"])
    lock = m.SingleInstance(path)
    lock.acquire()
    assert path.read_text(encoding="ascii") == str(os.getpid())
    lock.release()
    assert not path.exists()


class FakeBridge:
    def tcp_ready(self):
        return True

    def market_snapshot(self):
        quotes = {}
        prices = {"US.QQQ": 600.0, "US.IQQ": 25.0, "US.TQQQ": 80.0, "US.SQQQ": 35.0}
        for symbol, last in prices.items():
            quotes[symbol] = {"symbol": symbol, "latest_price": last, "bid": last - .01, "ask": last + .01,
                              "mid": last, "spread_absolute": .02, "spread_ratio": .02 / last,
                              "quote_timestamp": m.utc_iso(), "quote_age_seconds": 0.0,
                              "market_status": "REGULAR", "session_type": "REGULAR", "data_fresh": True}
        return {"schema_version": 1, "snapshot_at_utc": m.utc_iso(), "snapshot_ready": True,
                "all_quotes_fresh": True, "market_status": "REGULAR", "session_type": "REGULAR",
                "quotes": quotes, "qqq_klines": {k: {"ready": True, "bars": []} for k in m.KLINE_TYPES},
                "benchmark": {"symbol": "US.QQQ", "last": 600.0},
                "execution_quotes": {s: {"bid": quotes[s]["bid"], "ask": quotes[s]["ask"], "age_seconds": 0.0}
                                     for s in m.EXECUTION_SYMBOLS}, "source": "TEST"}

    def account_snapshot(self):
        return {"schema_version": 1, "snapshot_at_utc": m.utc_iso(), "account_snapshot_ready": True,
                "account_type": "REAL", "account_reference": "MASKED_TEST", "net_liquidation_value_usd": 400.0,
                "available_cash_usd": 400.0, "buying_power_usd": 400.0,
                "positions": {s: 0.0 for s in m.EXECUTION_SYMBOLS}, "positions_detail": [],
                "open_order_count": 0, "open_orders": [], "today_deals": [],
                "realized_pnl_today_usd": 0.0, "unrealized_pnl_today_usd": 0.0,
                "realized_pnl_week_usd": 0.0, "today_pnl_usd": 0.0, "source": "TEST"}


def create_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "v22").mkdir(parents=True)
    (repo / "config").mkdir()
    for name in ("v22_047_r1b_auto_trading_control_component.py", "v22_047_r1b_strategy_plugin_template.py"):
        (repo / "scripts" / "v22" / name).write_text((HERE / name).read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "config" / "v22_047_r1b_auto_trading_control.json").write_text(
        (HERE.parents[1] / "config" / "v22_047_r1b_auto_trading_control.json").read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "config" / "moomoo_opend_connection.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": 18441}), encoding="utf-8")
    return repo


def test_full_cycle_reuses_plugin_and_control_shadow_only(tmp_path):
    repo = create_repo(tmp_path)
    engine = m.Engine(repo, bridge=FakeBridge())
    summary = engine.cycle()
    out = repo / "outputs" / "v22" / m.OUTPUT_FOLDER
    strategy = json.loads((out / "strategy_decision.json").read_text(encoding="utf-8"))
    control = json.loads((out / "control_decision.json").read_text(encoding="utf-8"))
    intent = json.loads((out / "shadow_order_intent.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "PASS_R1D_SHADOW_CYCLE"
    assert strategy["strategy_configured"] is False
    assert strategy["strategy_action"] == "HOLD"
    assert strategy["strategy_reason_code"] == "STRATEGY_NOT_CONFIGURED"
    assert control["r1b_control_component_called"] is True
    assert control["effective_execution_mode"] == "SHADOW_ONLY"
    assert control["broker_action_allowed"] is False
    assert control["trade_api_called"] is False
    assert intent["order_intent_created"] is False


def test_account_failure_blocks_authorization(tmp_path):
    class FailedAccountBridge(FakeBridge):
        def account_snapshot(self):
            return m.failed_account("test")
    repo = create_repo(tmp_path)
    engine = m.Engine(repo, bridge=FailedAccountBridge())
    engine.cycle()
    out = repo / "outputs" / "v22" / m.OUTPUT_FOLDER
    control = json.loads((out / "control_decision.json").read_text(encoding="utf-8"))
    assert control["account_snapshot_ready"] is False
    assert control["broker_action_allowed"] is False


@pytest.mark.parametrize("include_history", (None, False))
def test_quote_only_probe_keeps_symbols_and_closes_context(tmp_path, include_history):
    history_calls, quote_calls, closed = [], [], []

    class QuoteContext:
        def get_market_snapshot(self, symbols):
            quote_calls.append(tuple(symbols))
            return 0, [{"code": symbol, "last_price": 10.0, "bid_price": 9.9,
                        "ask_price": 10.1, "update_time": "2025-01-02 10:00:00"}
                       for symbol in symbols]

        def request_history_kline(self, **kwargs):
            history_calls.append(kwargs)
            return 0, []

        def close(self):
            closed.append(True)

    bridge = m.MoomooReadOnlyBridge({"host": "127.0.0.1", "port": 18441}, tmp_path)
    bridge.moomoo = SimpleNamespace(OpenQuoteContext=lambda **kwargs: QuoteContext(),
        KLType=SimpleNamespace(**{key: key for key in m.KLINE_TYPES}), AuType=SimpleNamespace(QFQ="QFQ"))
    result = bridge.market_snapshot() if include_history is None else bridge.market_snapshot(include_history=False)
    assert quote_calls == [m.QUOTE_SYMBOLS]
    assert result["snapshot_ready"] is True
    assert set(result["quotes"]) == set(m.QUOTE_SYMBOLS)
    assert closed == [True]
    if include_history is None:
        assert [call["ktype"] for call in history_calls] == list(m.KLINE_TYPES)
        assert all(call["code"] == m.BENCHMARK_SYMBOL for call in history_calls)
    else:
        assert history_calls == [] and result["qqq_klines"] == {}
    assert not list(tmp_path.iterdir())


def test_exited_child_with_open_process_handle_is_not_alive_and_lock_is_reusable(tmp_path):
    # Keep Popen's native handle open after wait: OpenProcess can still succeed
    # for a Windows process that has terminated.
    with subprocess.Popen([sys.executable, "-B", "-c", "pass"],
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as child:
        assert child.wait(timeout=15) == 0
        assert m.SingleInstance.alive(child.pid) is False
        path = tmp_path / "engine.lock"
        path.write_text(str(child.pid), encoding="ascii")
        lock = m.SingleInstance(path)
        lock.acquire()
        assert lock.acquired and path.read_text(encoding="ascii") == str(os.getpid())
        lock.release()
        assert not path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
@pytest.mark.parametrize("handle,wait_result,error", ((0, 0, 5), (1, 0xFFFFFFFF, 0)))
def test_uncertain_windows_process_query_preserves_live_lock(tmp_path, monkeypatch, handle, wait_result, error):
    import ctypes
    kernel = SimpleNamespace(OpenProcess=lambda *args: handle,
        WaitForSingleObject=lambda *args: wait_result, CloseHandle=lambda *args: 1)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error)
    lock = m.SingleInstance(tmp_path / "engine.lock")
    lock.path.write_text("12345", encoding="ascii")
    with pytest.raises(m.R1DError, match="ALREADY_RUNNING"):
        lock.acquire()
    assert lock.path.read_text(encoding="ascii") == "12345"


def test_continuous_engine_cycles_are_not_crash_recovery(tmp_path):
    engine = m.Engine(create_repo(tmp_path), bridge=FakeBridge())
    assert engine.cycle()["crash_recovery_detected"] is False
    assert engine.cycle()["crash_recovery_detected"] is False


def test_engine_disconnect_and_reconnect_use_synthetic_bridge_only(tmp_path):
    class ConnectionBridge(FakeBridge):
        connected = True
        def tcp_ready(self):
            return self.connected
    bridge = ConnectionBridge()
    engine = m.Engine(create_repo(tmp_path), bridge=bridge)
    for connected in (True, False, True):
        bridge.connected = connected
        result = engine.cycle()
        assert result["opend_status"] == ("CONNECTED" if connected else "DISCONNECTED")
        assert m.read_json(engine.output_dir / "market_snapshot.json")["snapshot_ready"] is connected
        assert m.read_json(engine.output_dir / "account_snapshot.json")["account_snapshot_ready"] is connected
        control = m.read_json(engine.output_dir / "control_decision.json")
        assert control["broker_action_allowed"] is False
        assert control["trade_api_called"] is False


def test_engine_fatal_exit_records_failure_releases_lock_and_restarts(tmp_path):
    class FailingBridge(FakeBridge):
        calls = 0
        def tcp_ready(self):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("SYNTHETIC_FATAL_BRIDGE")
            return True
    repo = create_repo(tmp_path)
    engine = m.Engine(repo, bridge=FailingBridge())
    engine.interval = 0
    assert engine.run() == 2
    assert m.read_json(engine.output_dir / "engine_state.json")["engine_status"] == "FAILED"
    assert m.read_json(engine.output_dir / "engine_heartbeat.json")["status"] == "FAILED"
    assert not engine.lock.path.exists()
    replacement = m.Engine(repo, bridge=FakeBridge())
    assert replacement.run(once=True) == 0
    assert m.read_json(engine.output_dir / "engine_state.json")["engine_status"] == "CLEAN_STOP"
    assert not replacement.lock.path.exists()
