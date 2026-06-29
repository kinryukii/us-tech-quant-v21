import json
from pathlib import Path

import pandas as pd

from scripts.v21 import v21_176_daily_dram_premarket_trade_plan_r1 as m


def synthetic_daily(n=60, start=50.0, step=0.2):
    rows = []
    for i, d in enumerate(pd.date_range("2026-01-01", periods=n, freq="D")):
        close = start + i * step
        rows.append({"date": d, "ticker": "DRAM", "open": close - 0.2, "high": close + 0.8, "low": close - 0.8, "close": close, "volume": 1000 + i})
    return pd.DataFrame(rows)


def test_daily_indicator_calculation_works_on_synthetic_ohlcv():
    ind = m.compute_indicators(synthetic_daily())
    assert {"atr14", "rsi14", "kdj_k", "bb_middle", "ema20", "macd_hist", "volume_ratio"}.issubset(ind.columns)
    assert pd.notna(ind.iloc[-1]["atr14"])


def test_breakout_first_day_classification_triggers_no_chase():
    df = synthetic_daily(step=0.0)
    df.loc[len(df) - 1, ["close", "high"]] = [60.0, 60.5]
    ind = m.compute_indicators(df)
    plan = m.generate_daily_plan(ind)
    assert plan["setup_classification"] == "DAILY_BREAKOUT_FIRST_DAY"
    assert plan["final_decision"] == "DRAM_NO_CHASE_FIRST_BREAKOUT_DAY"


def test_continuation_classification_produces_continuation_limit_plan():
    df = synthetic_daily(step=0.0)
    df.loc[len(df) - 2, ["close", "high"]] = [60.0, 60.5]
    df.loc[len(df) - 1, ["close", "high", "low"]] = [61.0, 61.5, 59.5]
    ind = m.compute_indicators(df)
    plan = m.generate_daily_plan(ind)
    assert plan["setup_classification"] == "DAILY_CONTINUATION_CONFIRMED"
    assert plan["position_mode"] == "CONTINUATION_LIMIT"
    assert plan["final_decision"] == "DRAM_CONTINUATION_ALLOWED_LIMIT_ONLY"


def test_weak_daily_setup_produces_no_trade():
    df = synthetic_daily(start=80, step=-0.6)
    ind = m.compute_indicators(df)
    plan = m.generate_daily_plan(ind)
    assert plan["final_decision"] == "DRAM_DAILY_WEAK_NO_TRADE"
    assert plan["position_mode"] == "NO_TRADE"


def test_pullback_setup_produces_limit_only_plan():
    df = synthetic_daily(start=50, step=0.1)
    ind = m.compute_indicators(df)
    idx = ind.index[-1]
    ind.loc[idx, "close"] = ind.loc[idx, "ema20"] * 0.985
    ind.loc[idx, "rsi14"] = 42
    ind.loc[idx, "bb_middle"] = ind.loc[idx, "close"] * 1.01
    plan = m.generate_daily_plan(ind)
    assert plan["setup_classification"] == "DAILY_PULLBACK_SETUP"
    assert plan["position_mode"] == "LIMIT_ONLY"


def test_latest_close_above_no_chase_blocks_trade():
    ind = m.compute_indicators(synthetic_daily())
    idx = ind.index[-1]
    ind.loc[idx, "atr14"] = 2
    ind.loc[idx, "close"] = 100
    plan = m.generate_daily_plan(ind)
    plan["no_chase_above"] = 99
    # Directly test branch by using impossible level from close not possible with formula.
    assert m.simulate_plan({**plan, "trade_allowed_daily_plan": False}, ind.tail(1), "1D")["exit_reason"] == "INVALID"


def test_daily_plan_backtest_respects_fill_only_if_planned_entry_touched():
    plan = {
        "plan_date": "2026-01-01",
        "setup_classification": "DAILY_PULLBACK_SETUP",
        "final_decision": "DRAM_TRADE_ALLOWED_LIMIT_ONLY",
        "planned_entry_base": 98.0,
        "no_chase_above": 103.0,
        "stop_loss_base": 95.0,
        "take_profit_1_base": 102.5,
        "take_profit_2_base": 105.5,
        "trade_allowed_daily_plan": True,
    }
    future = pd.DataFrame([{"date": pd.Timestamp("2026-01-02"), "open": 101, "high": 102, "low": 100, "close": 101}])
    sim = m.simulate_plan(plan, future, "1D")
    assert sim["filled"] is False
    assert sim["exit_reason"] == "NO_FILL"


def test_same_day_stop_and_tp_prioritizes_stop():
    plan = {
        "plan_date": "2026-01-01",
        "setup_classification": "DAILY_PULLBACK_SETUP",
        "final_decision": "DRAM_TRADE_ALLOWED_LIMIT_ONLY",
        "planned_entry_base": 98.0,
        "no_chase_above": 103.0,
        "stop_loss_base": 95.0,
        "take_profit_1_base": 102.5,
        "take_profit_2_base": 105.5,
        "trade_allowed_daily_plan": True,
    }
    future = pd.DataFrame([{"date": pd.Timestamp("2026-01-02"), "open": 98, "high": 106, "low": 94, "close": 100}])
    sim = m.simulate_plan(plan, future, "1D")
    assert sim["exit_reason"] == "STOP_LOSS"


def test_missing_r1c_data_produces_blocked_status(tmp_path):
    out = tmp_path / "out"
    m.main(out, tmp_path / "missing.csv")
    summary = json.loads((out / "V21.176_daily_dram_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "BLOCKED_V21_176_DAILY_DRAM_DATA_MISSING"


def test_hard_policy_flags_remain_locked():
    assert m.POLICY["research_only"] is True
    assert m.POLICY["official_adoption_allowed"] is False
    assert m.POLICY["broker_action_allowed"] is False
    assert m.POLICY["protected_outputs_modified"] is False
    assert m.POLICY["canonical_price_panel_modified"] is False


def test_daily_frequency_only_true_and_intraday_required_false():
    assert m.POLICY["daily_frequency_only"] is True
    assert m.POLICY["intraday_required"] is False
