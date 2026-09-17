from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("v22_047_r1b_auto_trading_control_component.py")
SPEC = importlib.util.spec_from_file_location("v22_047_r1b", MODULE_PATH)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def config(**overrides):
    cfg = json.loads(json.dumps(m.DEFAULT_CONFIG))
    for section, values in overrides.items():
        cfg[section].update(values)
    return cfg


def market():
    return {
        "benchmark": {"symbol": "US.QQQ", "last": 600.0},
        "execution_quotes": {
            "US.IQQ": {"bid": 24.98, "ask": 25.00, "age_seconds": 1.0},
            "US.TQQQ": {"bid": 79.95, "ask": 80.00, "age_seconds": 1.0},
            "US.SQQQ": {"bid": 34.98, "ask": 35.00, "age_seconds": 1.0},
        },
    }


def account(**kwargs):
    payload = {
        "net_liquidation_value_usd": 400.0,
        "available_cash_usd": 400.0,
        "realized_pnl_today_usd": 0.0,
        "realized_pnl_week_usd": 0.0,
        "open_order_count": 0,
        "positions": {"US.IQQ": 0, "US.TQQQ": 0, "US.SQQQ": 0},
    }
    payload.update(kwargs)
    return payload


def decision(symbol="US.IQQ", notional=100.0):
    return m.StrategyDecision(
        action="ENTER_LONG",
        symbol=symbol,
        target_notional_usd=notional,
        confidence=0.7,
        reason_code="TEST_ENTRY",
    )


def benchmark(block=False, status="OUTPERFORMING_QQQ"):
    return m.BenchmarkMetrics(
        status=status,
        observation_count=20,
        strategy_return=0.01,
        qqq_return=0.0,
        excess_return=0.01,
        underperformance_threshold=-0.02,
        block_new_entries=block,
        reason_code="TEST",
    )


def test_fixed_benchmark_and_symbols():
    assert m.BENCHMARK_SYMBOL == "US.QQQ"
    assert m.ALLOWED_EXECUTION_SYMBOLS == ("US.IQQ", "US.TQQQ", "US.SQQQ")


def test_config_rejects_benchmark_change():
    cfg = config(component={"benchmark_symbol": "US.NDX"})
    with pytest.raises(m.ComponentError, match="IMMUTABLE"):
        m.validate_config(cfg)


def test_config_rejects_symbol_scope_change():
    cfg = config(component={"allowed_execution_symbols": ["US.IQQ"]})
    with pytest.raises(m.ComponentError, match="EXACTLY"):
        m.validate_config(cfg)


def test_parse_hold_decision():
    d = m.parse_strategy_decision({"action": "HOLD", "reason_code": "NONE"})
    assert d.action == "HOLD"
    assert d.symbol is None


@pytest.mark.parametrize("symbol", m.ALLOWED_EXECUTION_SYMBOLS)
def test_all_three_execution_symbols_allowed(symbol):
    d = m.parse_strategy_decision({
        "action": "ENTER_LONG",
        "symbol": symbol,
        "target_notional_usd": 100,
        "confidence": 0.5,
        "reason_code": "TEST",
    })
    assert d.symbol == symbol


def test_invalid_execution_symbol_rejected():
    with pytest.raises(m.ComponentError, match="INVALID_EXECUTION_SYMBOL"):
        m.parse_strategy_decision({
            "action": "ENTER_LONG",
            "symbol": "US.AAPL",
            "target_notional_usd": 100,
            "confidence": 0.5,
        })


def test_off_switch_blocks_everything():
    a = m.build_authorization("OFF", decision(), account(), benchmark(), config(), execute_requested=True, live_confirmation=m.LIVE_CONFIRMATION_EXPECTED)
    assert not a.order_intent_allowed
    assert not a.broker_action_allowed


def test_shadow_creates_plan_without_broker_action():
    a = m.build_authorization("SHADOW", decision(), account(), benchmark(), config(), execute_requested=True, live_confirmation="")
    assert a.order_intent_allowed
    assert not a.broker_action_allowed


def test_paper_requires_execute_flag():
    a = m.build_authorization("PAPER", decision(), account(), benchmark(), config(), execute_requested=False, live_confirmation="")
    assert a.order_intent_allowed
    assert not a.broker_action_allowed


def test_paper_execute_allows_broker_action():
    a = m.build_authorization("PAPER", decision(), account(), benchmark(), config(), execute_requested=True, live_confirmation="")
    assert a.broker_action_allowed


def test_live_requires_confirmation():
    a = m.build_authorization("LIVE", decision(), account(), benchmark(), config(), execute_requested=True, live_confirmation="WRONG")
    assert not a.broker_action_allowed
    assert a.order_intent_allowed


def test_live_confirmation_allows_broker_action():
    a = m.build_authorization("LIVE", decision(), account(), benchmark(), config(), execute_requested=True, live_confirmation=m.LIVE_CONFIRMATION_EXPECTED)
    assert a.broker_action_allowed


def test_flatten_only_blocks_entry():
    a = m.build_authorization("FLATTEN_ONLY", decision(), account(), benchmark(), config(), execute_requested=True, live_confirmation=m.LIVE_CONFIRMATION_EXPECTED)
    assert not a.order_intent_allowed


def test_flatten_only_allows_exit_intent():
    d = m.StrategyDecision(action="EXIT", reason_code="TEST_EXIT")
    acct = account(positions={"US.IQQ": 2, "US.TQQQ": 0, "US.SQQQ": 0})
    a = m.build_authorization("FLATTEN_ONLY", d, acct, benchmark(), config(), execute_requested=True, live_confirmation="")
    assert a.order_intent_allowed
    intent = m.build_order_intent(d, a, market(), acct, benchmark(), config())
    assert intent and intent.side == "SELL" and intent.symbol == "US.IQQ" and intent.quantity == 2


def test_existing_position_blocks_new_entry():
    acct = account(positions={"US.IQQ": 1, "US.TQQQ": 0, "US.SQQQ": 0})
    a = m.build_authorization("SHADOW", decision("US.TQQQ"), acct, benchmark(), config(), execute_requested=False, live_confirmation="")
    assert not a.new_entry_allowed


def test_open_order_blocks_new_entry():
    acct = account(open_order_count=1)
    a = m.build_authorization("SHADOW", decision(), acct, benchmark(), config(), execute_requested=False, live_confirmation="")
    assert not a.new_entry_allowed


def test_daily_loss_blocks_entry_but_not_exit():
    acct = account(realized_pnl_today_usd=-6.0)
    entry_auth = m.build_authorization("SHADOW", decision(), acct, benchmark(), config(), execute_requested=False, live_confirmation="")
    assert not entry_auth.new_entry_allowed
    acct["positions"] = {"US.IQQ": 1, "US.TQQQ": 0, "US.SQQQ": 0}
    exit_decision = m.StrategyDecision(action="EXIT", reason_code="EXIT")
    exit_auth = m.build_authorization("SHADOW", exit_decision, acct, benchmark(), config(), execute_requested=False, live_confirmation="")
    assert exit_auth.exit_allowed


def test_underperformance_blocks_new_entry():
    a = m.build_authorization("SHADOW", decision(), account(), benchmark(block=True, status="UNDERPERFORMING_QQQ"), config(), execute_requested=False, live_confirmation="")
    assert not a.new_entry_allowed


def test_benchmark_insufficient_data_does_not_block():
    state = m.RuntimeState(samples=[])
    metrics = m.compute_benchmark_metrics(state, 400, 600, config(benchmark={"minimum_observations": 3}))
    assert metrics.status == "INSUFFICIENT_DATA"
    assert not metrics.block_new_entries


def test_benchmark_underperformance_calculation():
    state = m.RuntimeState(samples=[
        {"nav": 400.0, "qqq": 500.0},
        {"nav": 399.0, "qqq": 510.0},
    ])
    cfg = config(benchmark={"minimum_observations": 3, "underperformance_threshold_pct": -0.02})
    metrics = m.compute_benchmark_metrics(state, 396.0, 520.0, cfg)
    assert metrics.strategy_return == pytest.approx(-0.01)
    assert metrics.qqq_return == pytest.approx(0.04)
    assert metrics.excess_return == pytest.approx(-0.05)
    assert metrics.block_new_entries


def test_order_notional_is_capped():
    d = decision("US.IQQ", 1000.0)
    a = m.build_authorization("SHADOW", d, account(), benchmark(), config(), execute_requested=False, live_confirmation="")
    intent = m.build_order_intent(d, a, market(), account(), benchmark(), config())
    assert intent is not None
    assert intent.quantity == 4
    assert intent.notional_usd == pytest.approx(100.0)


def test_tqqq_quantity_uses_quote_and_cap():
    d = decision("US.TQQQ", 120.0)
    a = m.build_authorization("SHADOW", d, account(), benchmark(), config(), execute_requested=False, live_confirmation="")
    intent = m.build_order_intent(d, a, market(), account(), benchmark(), config())
    assert intent and intent.quantity == 1


def test_sqqq_quantity_uses_quote_and_cap():
    d = decision("US.SQQQ", 120.0)
    a = m.build_authorization("SHADOW", d, account(), benchmark(), config(), execute_requested=False, live_confirmation="")
    intent = m.build_order_intent(d, a, market(), account(), benchmark(), config())
    assert intent and intent.quantity == 3


def test_quote_validation_rejects_stale_quote():
    mk = market()
    mk["execution_quotes"]["US.IQQ"]["age_seconds"] = 99
    with pytest.raises(m.ComponentError, match="STALE_QUOTE"):
        m.validate_snapshots(mk, account(), config())


def test_switch_live_requires_explicit_confirmation(tmp_path):
    path = tmp_path / "switch.json"
    with pytest.raises(m.ComponentError, match="EXPLICIT_CONFIRMATION"):
        m.set_switch_state(path, "LIVE", "", "TEST", False)


def test_switch_state_roundtrip(tmp_path):
    path = tmp_path / "switch.json"
    state = m.set_switch_state(path, "SHADOW", "test", "pytest", False)
    assert state["mode"] == "SHADOW"
    assert m.read_switch_state(path)["mode"] == "SHADOW"


def test_strategy_plugin_error_fails_closed(tmp_path, monkeypatch):
    plugin = tmp_path / "bad_plugin.py"
    plugin.write_text("def generate_decision(context):\n    raise RuntimeError('boom')\n", encoding="utf-8")
    func = m.load_strategy_callable(plugin, "generate_decision")
    with pytest.raises(RuntimeError, match="boom"):
        func({})


def test_benchmark_pause_uses_recovery_threshold():
    state = m.RuntimeState(
        samples=[{"nav": 400.0, "qqq": 500.0}, {"nav": 400.0, "qqq": 500.0}],
        benchmark_pause_active=True,
    )
    cfg = config(benchmark={
        "minimum_observations": 3,
        "underperformance_threshold_pct": -0.02,
        "recovery_threshold_pct": -0.005,
    })
    still_paused = m.compute_benchmark_metrics(state, 400.0, 504.0, cfg)
    assert still_paused.excess_return == pytest.approx(-0.008)
    assert still_paused.block_new_entries
    recovered = m.compute_benchmark_metrics(state, 400.0, 501.0, cfg)
    assert recovered.excess_return == pytest.approx(-0.002, abs=1e-9)
    assert not recovered.block_new_entries
    assert recovered.status == "QQQ_BENCHMARK_GUARD_RECOVERED"


def test_flatten_only_execute_with_live_confirmation_authorizes_exit():
    d = m.StrategyDecision(action="EXIT", reason_code="TEST_EXIT")
    acct = account(positions={"US.IQQ": 1, "US.TQQQ": 0, "US.SQQQ": 0})
    auth = m.build_authorization(
        "FLATTEN_ONLY",
        d,
        acct,
        benchmark(),
        config(),
        execute_requested=True,
        live_confirmation=m.LIVE_CONFIRMATION_EXPECTED,
    )
    assert auth.broker_action_allowed
    assert auth.exit_allowed


def a2_shadow_plan(symbols=None):
    names = list(symbols or ["US.NVDA", *[f"US.A2T{index:02d}" for index in range(2, 21)]])
    targets = {symbol: 1.0 / len(names) for symbol in names}
    return {
        "safety_profile_id": m.A2_SHADOW_PROFILE_ID,
        "broker_submission_allowed": False,
        "target_date": "2026-08-24",
        "authorized_top20": names,
        "target_weights": targets,
        "target_cash_weight": 0.0,
        "current_portfolio": {
            "as_of": "2026-08-24", "cash": 1000.0, "total_equity": 1000.0,
            "positions": [], "gross_exposure": 0.0, "cash_weight": 1.0,
        },
        "actions": [
            {
                "security": symbol, "current_weight": 0.0, "target_weight": weight,
                "delta_weight": weight, "planned_delta_weight": weight * 0.999,
                "action": "BUY", "reason": "RAW_A2_TOP20_NEW_POSITION",
                "current_shares": 0.0, "current_mark_price": None,
            }
            for symbol, weight in targets.items()
        ],
    }


def test_a2_shadow_profile_accepts_authorized_equity_and_reuses_order_intent_schema():
    plan = a2_shadow_plan()
    prices = {symbol: 100.0 for symbol in plan["authorized_top20"]}
    first = m.build_a2_shadow_order_intents(plan, prices)
    second = m.build_a2_shadow_order_intents(plan, prices)
    assert first == second
    assert first["status"] == "PASS"
    assert first["profile_id"] == m.A2_SHADOW_PROFILE_ID
    assert first["shadow_only"] and not first["broker_submission_allowed"]
    assert len(first["order_intents"]) == 20
    nvda = next(row for row in first["order_intents"] if row["symbol"] == "US.NVDA")
    assert set(nvda) == set(m.OrderIntent.__dataclass_fields__)
    assert nvda["action"] == "BUY" and nvda["side"] == "BUY"


def test_a2_shadow_profile_rejects_out_of_scope_new_equity():
    plan = a2_shadow_plan()
    plan["actions"].append({
        "security": "US.OUTSIDE", "current_weight": 0.0, "target_weight": 0.01,
        "delta_weight": 0.01, "planned_delta_weight": 0.01, "action": "BUY",
        "reason": "INVALID", "current_shares": 0.0, "current_mark_price": None,
    })
    with pytest.raises(m.ComponentError, match="OUTSIDE_AUTHORIZED_TOP20"):
        m.build_a2_shadow_order_intents(plan, {symbol: 100.0 for symbol in plan["authorized_top20"]})


def test_a2_shadow_profile_allows_out_of_scope_current_position_exit_only():
    plan = a2_shadow_plan()
    plan["current_portfolio"] = {
        "as_of": "2026-08-24", "cash": 900.0, "total_equity": 1000.0,
        "positions": [{"symbol": "US.OLD", "shares": 1.0, "mark_price": 100.0}],
        "gross_exposure": 0.1, "cash_weight": 0.9,
    }
    plan["actions"].append({
        "security": "US.OLD", "current_weight": 0.1, "target_weight": 0.0,
        "delta_weight": -0.1, "planned_delta_weight": -0.1, "action": "EXIT",
        "reason": "NO_LONGER_IN_RAW_A2_TOP20", "current_shares": 1.0,
        "current_mark_price": 100.0,
    })
    prices = {symbol: 100.0 for symbol in plan["authorized_top20"]}
    result = m.build_a2_shadow_order_intents(plan, prices)
    exit_intent = next(row for row in result["order_intents"] if row["symbol"] == "US.OLD")
    assert exit_intent["action"] == "EXIT" and exit_intent["side"] == "SELL"


def test_a2_shadow_profile_rejects_more_than_twenty_targets():
    plan = a2_shadow_plan([f"US.A2T{index:02d}" for index in range(1, 22)])
    with pytest.raises(m.ComponentError, match="MAX_TARGET_POSITIONS"):
        m.build_a2_shadow_order_intents(plan, {symbol: 100.0 for symbol in plan["authorized_top20"]})


def test_a2_shadow_profile_rejects_short_leverage_and_negative_cash():
    prices = {symbol: 100.0 for symbol in a2_shadow_plan()["authorized_top20"]}
    short = a2_shadow_plan()
    short["target_weights"][short["authorized_top20"][0]] = -0.01
    with pytest.raises(m.ComponentError, match="SHORT_TARGET"):
        m.build_a2_shadow_order_intents(short, prices)
    leveraged = a2_shadow_plan()
    leveraged["target_weights"] = {symbol: 0.051 for symbol in leveraged["authorized_top20"]}
    with pytest.raises(m.ComponentError, match="MAX_TARGET_WEIGHT|TARGET_LEVERAGE"):
        m.build_a2_shadow_order_intents(leveraged, prices)
    negative_cash = a2_shadow_plan()
    negative_cash["target_cash_weight"] = -0.01
    with pytest.raises(m.ComponentError, match="NEGATIVE_TARGET_CASH"):
        m.build_a2_shadow_order_intents(negative_cash, prices)


def test_legacy_profile_still_rejects_nvda_after_a2_profile_extension():
    with pytest.raises(m.ComponentError, match="INVALID_EXECUTION_SYMBOL"):
        m.parse_strategy_decision({
            "action": "ENTER_LONG", "symbol": "US.NVDA",
            "target_notional_usd": 100, "confidence": 0.5,
        })
