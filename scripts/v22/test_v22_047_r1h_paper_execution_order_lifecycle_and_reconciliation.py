from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path); assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module


h = load(HERE / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py", "r1h_test")


@pytest.fixture
def paper_repo(tmp_path):
    scripts = tmp_path / "scripts" / "v22"; config = tmp_path / "config"
    scripts.mkdir(parents=True); config.mkdir()
    shutil.copy2(HERE / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py", scripts)
    shutil.copy2(HERE / "v22_047_r1b_strategy_plugin_template.py", scripts)
    shutil.copy2(REPO / "config" / "v22_047_r1h_paper_execution.json", config)
    return tmp_path, h.PaperExecutionEngine(tmp_path)


def rth(hour=10, minute=0, second=0):
    return datetime(2026, 7, 14, hour, minute, second, tzinfo=ZoneInfo("America/New_York"))


def arm(engine, now=None, backend="PAPER_LOCAL_SIM"):
    return h.request_paper_arm(engine.paths, dashboard_clicked=True, first_confirmation=True,
                               second_confirmation="CONFIRM_PAPER_SIMULATED_TRADING_ONLY",
                               requested_backend=backend, current=now or rth())


def submit(engine, intent="i-1", **kw):
    defaults = dict(intent_id=intent, symbol="US.QQQ", side="BUY", decimal_quantity="1.125", limit_price="100", current=rth())
    defaults.update(kw); return engine.submit_order(**defaults)


def test_paper_requires_valid_double_confirmation(paper_repo):
    _, e = paper_repo
    with pytest.raises(h.R1HError, match="DOUBLE_CONFIRMATION"):
        h.request_paper_arm(e.paths, dashboard_clicked=True, first_confirmation=True, second_confirmation="NO", current=rth())
    with pytest.raises(h.R1HError, match="DASHBOARD"):
        h.request_paper_arm(e.paths, dashboard_clicked=False, first_confirmation=True, second_confirmation="CONFIRM_PAPER_SIMULATED_TRADING_ONLY", current=rth())


def test_expired_paper_arm_rejects_new_order(paper_repo):
    _, e = paper_repo; arm(e, rth()); order = submit(e, current=rth(10, 31))
    assert order["status"] == "REJECTED" and order["reason_code"] == "PAPER_ARM_EXPIRED"


def test_startup_resets_to_shadow_and_disarmed(paper_repo):
    repo, e = paper_repo; arm(e); e2 = h.PaperExecutionEngine(repo, startup=True); state = h.read_json(e2.paths.authorization)
    assert state["execution_mode"] == "SHADOW" and state["execution_authorization"] == "DISARMED"


def test_real_environment_and_unlock_always_rejected():
    class Adapter: pass
    with pytest.raises(h.R1HError, match="REAL_ENVIRONMENT"):
        h.SimulateOnlyBroker(Adapter(), "TrdEnv.REAL")
    broker = h.SimulateOnlyBroker(Adapter())
    with pytest.raises(h.R1HError, match="UNLOCK_TRADE"):
        broker.unlock_trade(password="never")


def test_decimal_quantity_preserved_without_integer_truncation(paper_repo):
    _, e = paper_repo; arm(e); order = submit(e)
    assert order["decimal_quantity"] == "1.125" and Decimal(order["decimal_quantity"]) != Decimal(order["decimal_quantity"]).to_integral_value()


def test_duplicate_intent_and_restart_do_not_submit_twice(paper_repo):
    repo, e = paper_repo; arm(e); first = submit(e); second = submit(e); restarted = h.PaperExecutionEngine(repo); third = submit(restarted)
    assert first["status"] == "ACKNOWLEDGED" and second["idempotent_replay"] and third["idempotent_replay"]
    assert len([x for x in h.jsonl_rows(e.paths.idempotency) if x["intent_id"] == "i-1"]) == 1


def test_restart_queries_existing_orders_before_allowing_new(paper_repo):
    _, e = paper_repo; arm(e); submit(e); state = e.recover_after_restart(rth(10, 1))
    assert state["state"] == "RECONCILING" and state["new_orders_blocked"] is True
    blocked = submit(e, "i-2", current=rth(10, 2)); assert blocked["status"] == "REJECTED" and blocked["reason_code"] == "RECONCILIATION_NOT_READY"


def test_partial_fill_updates_remaining_quantity(paper_repo):
    _, e = paper_repo; arm(e); submit(e); order = e.process_quote("i-1", {"bid": "99", "ask": "99.5", "timestamp": rth()}, current=rth(), max_fill_quantity="0.500")
    assert order["status"] == "PARTIALLY_FILLED" and order["filled_quantity"] == "0.5" and order["remaining_quantity"] == "0.625"


def test_completed_fill_updates_paper_cash_and_position(paper_repo):
    _, e = paper_repo; arm(e); submit(e); order = e.process_quote("i-1", {"bid": "99", "ask": "99.5", "timestamp": rth()}, current=rth())
    cash, portfolio = h.read_json(e.paths.cash), h.read_json(e.paths.portfolio)
    assert order["status"] == "FILLED" and Decimal(cash["paper_cash"]) < Decimal("100000")
    assert portfolio["positions"]["US.QQQ"]["quantity"] == "1.125"


def test_rejected_order_does_not_alter_position(paper_repo):
    _, e = paper_repo; arm(e); before = h.read_json(e.paths.portfolio); order = submit(e, symbol="US.AAPL")
    assert order["status"] == "REJECTED" and h.read_json(e.paths.portfolio) == before


def test_canceled_order_releases_reserved_cash(paper_repo):
    _, e = paper_repo; arm(e); submit(e); assert Decimal(h.read_json(e.paths.cash)["reserved_cash"]) > 0
    e.cancel_order("i-1", current=rth(10, 1)); cash = h.read_json(e.paths.cash)
    assert cash["reserved_cash"] == "0" and cash["available_paper_cash"] == "100000"


def test_buy_fill_uses_conservative_ask_model(paper_repo):
    _, e = paper_repo; arm(e); submit(e); order = e.process_quote("i-1", {"bid": "99", "ask": "99.5", "timestamp": rth()}, current=rth())
    assert Decimal(order["average_fill_price"]) >= Decimal("99.5")


def test_sell_fill_uses_conservative_bid_model_and_fee(paper_repo):
    _, e = paper_repo; arm(e); submit(e); e.process_quote("i-1", {"bid": "99", "ask": "99.5", "timestamp": rth()}, current=rth())
    submit(e, "i-2", side="SELL", decimal_quantity="0.500", limit_price="98", current=rth(10, 1)); order = e.process_quote("i-2", {"bid": "99", "ask": "99.5", "timestamp": rth(10, 1)}, current=rth(10, 1))
    assert order["status"] == "FILLED" and Decimal(order["average_fill_price"]) <= Decimal("99")
    assert Decimal(h.jsonl_rows(e.paths.deal_ledger)[-1]["fee"]) > 0


def test_stale_quote_blocks_fill(paper_repo):
    _, e = paper_repo; arm(e); submit(e); order = e.process_quote("i-1", {"bid": "99", "ask": "99.5", "timestamp": rth() - timedelta(seconds=30)}, current=rth())
    assert order["status"] == "ACKNOWLEDGED" and order["reason_code"] == "STALE_QUOTE_FILL_BLOCKED"


@pytest.mark.parametrize("when,reason", [(rth(9, 44), "PREMARKET"), (rth(15, 51), "AFTER_HOURS")])
def test_outside_rth_blocks_order(paper_repo, when, reason):
    _, e = paper_repo; arm(e, when); order = submit(e, current=when)
    assert order["status"] == "REJECTED" and reason in order["reason_code"]


def test_1550_cancels_remaining_day_orders(paper_repo):
    _, e = paper_repo; arm(e, rth(15, 49)); submit(e, current=rth(15, 49)); expired = e.expire_day_orders(rth(15, 50))
    assert expired and expired[0]["status"] == "EXPIRED" and h.read_json(e.paths.cash)["reserved_cash"] == "0"


def test_manual_activity_pauses_conflicting_paper_order(paper_repo):
    _, e = paper_repo; arm(e); submit(e); paused = e.handle_manual_activity(["US.QQQ"], rth(10, 1))
    assert paused[0]["status"] == "CANCELED" and h.read_json(e.paths.reconciliation)["state"] == "RECONCILING"


@pytest.mark.parametrize("symbol,asset", [("US.AAPL", "STOCK"), ("US.QQQ260117C00100000", "OPTION")])
def test_out_of_scope_stock_and_any_option_remain_untouched(paper_repo, symbol, asset):
    _, e = paper_repo; arm(e); order = submit(e, symbol=symbol, asset_type=asset)
    assert order["status"] == "REJECTED" and order["reason_code"] == "ASSET_OUT_OF_SCOPE_READ_ONLY"


def test_paper_nav_excludes_manual_holdings_and_qqq_is_independent(paper_repo):
    _, e = paper_repo; perf0 = e.mark_to_market({"US.QQQ": "100"}, rth()); arm(e); submit(e); e.process_quote("i-1", {"bid": "99", "ask": "99.5", "timestamp": rth()}, current=rth()); perf = e.mark_to_market({"US.QQQ": "110"}, rth(10, 2))
    assert perf["manual_holdings_excluded"] is True and Decimal(perf["qqq_buy_hold_return"]) == Decimal("0.1")
    assert "paper_excess_return_vs_qqq" in perf and perf0["paper_strategy_nav"] == "100000"


def test_live_remains_unavailable():
    result = h.request_live_arm(); assert result["error"] == "LIVE_NOT_AVAILABLE" and result["real_trade_api_called"] is False


def test_broker_fractional_rejection_falls_back_and_preserves_reason(paper_repo):
    class Adapter:
        def place_order(self, **kw): raise ValueError("fractional unsupported")
    _, e = paper_repo; e.broker = h.SimulateOnlyBroker(Adapter()); arm(e, backend="PAPER_BROKER_SIM")
    order = submit(e, execution_backend="PAPER_BROKER_SIM")
    assert order["execution_backend"] == "PAPER_LOCAL_SIM" and "fractional unsupported" in order["original_broker_rejection_reason"]
    assert order["broker_fractional_api_confirmed"] is False


def test_broker_sim_deal_reconciliation_is_idempotent(paper_repo):
    class Adapter:
        def place_order(self, **kw): return {"order_id": "sim-123"}
    _, e = paper_repo; e.broker = h.SimulateOnlyBroker(Adapter()); arm(e, backend="PAPER_BROKER_SIM")
    order = submit(e, execution_backend="PAPER_BROKER_SIM"); assert order["broker_order_submitted"] is True
    deal = {"deal_id": "deal-1", "qty": "1.125", "price": "99.5"}
    filled = e.reconcile_broker_order("i-1", {"status": "FILLED"}, [deal], rth(10, 1))
    replay = e.reconcile_broker_order("i-1", {"status": "FILLED"}, [deal], rth(10, 2))
    assert filled["status"] == "FILLED" and replay["filled_quantity"] == "1.125"
    assert len(h.jsonl_rows(e.paths.deal_ledger)) == 1


def test_rebalance_sell_then_wait_then_buy_and_v8_transition_guard():
    direct = h.rebalance_phases({"US.TQQQ": "2"}, "TACTICAL_DEFENSE", [], True)
    assert direct["phase"] == "SELL_EXCESS_FIRST" and "DIRECT_TQQQ_TO_SQQQ" in direct["blocked_reason"]
    wait = h.rebalance_phases({}, "CORE_QQQ", [{"status": "ACKNOWLEDGED", "side": "SELL"}], True)
    assert wait["phase"] == "WAIT_FOR_SELLS_AND_CASH_RECONCILIATION"


def test_required_output_and_ledger_files_exist(paper_repo):
    repo, e = paper_repo; h.write_summary(repo)
    for name in ("r1h_summary.json", "paper_authorization_state.json", "paper_execution_backend.json", "paper_order_state.json", "paper_reconciliation_state.json", "paper_portfolio_snapshot.json", "paper_cash_snapshot.json", "paper_performance_snapshot.json", "paper_order_ledger.jsonl", "paper_deal_ledger.jsonl", "paper_nav_history.csv", "validation_report.md"):
        assert (e.paths.output / name).exists(), name
