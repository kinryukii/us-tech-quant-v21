from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
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
