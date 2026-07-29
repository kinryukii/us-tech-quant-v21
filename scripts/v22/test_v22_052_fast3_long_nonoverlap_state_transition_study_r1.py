from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_052_fast3_long_nonoverlap_state_transition_study_r1 as mod


def valid_summary():
    return {
        "final_status": "PASS",
        "event_study_completed": True,
        "entry_exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def test_01_gate_accepts():
    mod.validate_v22_051(valid_summary())


def test_02_gate_rejects():
    payload = valid_summary()
    payload["broker_action_allowed"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_051(payload)


def test_03_naive_timestamp_rejected():
    with pytest.raises(mod.StudyError):
        mod.normalize_timestamp_utc(pd.Series(pd.to_datetime(["2026-01-01 10:00"])))


def row(**overrides):
    data = {
        "qqq_ret_15m": 0.01,
        "soxx_ret_15m": 0.02,
        "qqq_close": 101.0,
        "qqq_vwap": 100.0,
        "soxx_close": 202.0,
        "soxx_vwap": 200.0,
    }
    data.update(overrides)
    return pd.Series(data)


def test_04_soxl_branch():
    assert mod.long_condition_and_branch(row()) == (True, "SOXL")


def test_05_tqqq_branch():
    assert mod.long_condition_and_branch(row(qqq_ret_15m=0.03)) == (True, "TQQQ")


def test_06_no_short_branch():
    assert mod.long_condition_and_branch(row(qqq_ret_15m=-0.01, soxx_ret_15m=-0.02)) == (False, None)


def transition_frame():
    utc = pd.to_datetime([
        "2026-01-02T14:45:00Z", "2026-01-02T14:46:00Z", "2026-01-02T14:47:00Z",
        "2026-01-02T14:48:00Z", "2026-01-02T14:49:00Z",
    ], utc=True)
    et = utc.tz_convert("America/New_York")
    return pd.DataFrame({
        "signal_timestamp_et": et,
        "trade_date": "2026-01-02",
        "soxx_trade_date": "2026-01-02",
        "qqq_close": [99, 101, 102, 99, 101],
        "qqq_vwap": 100.0,
        "soxx_close": [199, 201, 202, 199, 201],
        "soxx_vwap": 200.0,
        "qqq_ret_15m": [-.01, .01, .02, -.01, .01],
        "soxx_ret_15m": [-.01, .02, .03, -.01, .02],
    }, index=utc)


def test_07_false_to_true_only():
    result = mod.state_transition_candidates(transition_frame())
    assert len(result) == 2


def execution_frame():
    et = pd.date_range("2026-01-02 09:30", "2026-01-02 15:59", freq="1min", tz="America/New_York")
    utc = et.tz_convert("UTC")
    prices = 100 + np.arange(len(et)) * 0.01
    return pd.DataFrame({
        "timestamp_utc": utc,
        "timestamp_et": et,
        "trade_date": "2026-01-02",
        "open": prices,
        "high": prices + .02,
        "low": prices - .02,
        "close": prices,
        "volume": 1000.0,
    })


def candidate_frame(times):
    utc = pd.to_datetime(times, utc=True)
    et = utc.tz_convert("America/New_York")
    return pd.DataFrame({
        "signal_timestamp_utc": utc,
        "signal_timestamp_et": et,
        "trade_date": "2026-01-02",
        "weekday": 4,
        "signal_minute_et": [x.hour * 60 + x.minute for x in et],
        "execution_symbol": "SOXL",
        "qqq_ret_15m": .01,
        "soxx_ret_15m": .02,
        "qqq_vwap_deviation_bps": 10.0,
        "soxx_vwap_deviation_bps": 20.0,
    })


def test_08_next_minute_open_exact_exit():
    trades = mod.schedule_nonoverlap_trades(candidate_frame(["2026-01-02T14:45:00Z"]), {"SOXL": execution_frame(), "TQQQ": execution_frame()}, 30)
    assert trades.iloc[0]["entry_timestamp_utc"] == pd.Timestamp("2026-01-02T14:46:00Z")
    assert trades.iloc[0]["exit_timestamp_utc"] == pd.Timestamp("2026-01-02T15:16:00Z")


def test_09_cost_is_10bps():
    trades = mod.schedule_nonoverlap_trades(candidate_frame(["2026-01-02T14:45:00Z"]), {"SOXL": execution_frame(), "TQQQ": execution_frame()}, 30)
    assert trades.iloc[0]["net_return"] == pytest.approx(trades.iloc[0]["gross_return"] - .001)


def test_10_nonoverlap_cooldown():
    times = ["2026-01-02T14:45:00Z", "2026-01-02T15:20:00Z", "2026-01-02T15:50:00Z", "2026-01-02T16:16:00Z"]
    trades = mod.schedule_nonoverlap_trades(candidate_frame(times), {"SOXL": execution_frame(), "TQQQ": execution_frame()}, 30)
    assert len(trades) == 2


def test_11_late_signal_rejected():
    trades = mod.schedule_nonoverlap_trades(candidate_frame(["2026-01-02T20:30:00Z"]), {"SOXL": execution_frame(), "TQQQ": execution_frame()}, 30)
    assert trades.empty


def test_12_max_three_per_day():
    times = ["2026-01-02T14:45:00Z", "2026-01-02T15:46:00Z", "2026-01-02T16:47:00Z", "2026-01-02T17:48:00Z"]
    trades = mod.schedule_nonoverlap_trades(candidate_frame(times), {"SOXL": execution_frame(), "TQQQ": execution_frame()}, 30)
    assert len(trades) <= 3


def test_13_pit_baseline_prior_only():
    trades = pd.DataFrame({"execution_symbol": ["SOXL"], "weekday": [4], "entry_minute_et": [600], "horizon_minutes": [30], "net_return": [.02]})
    stats = mod.RunningStats(); stats.add(.01); stats.add(.03)
    result = mod.assign_pit_baseline(trades, {mod.baseline_key("SOXL", 4, 600, 30): stats})
    assert result.iloc[0]["matched_unconditional_pit_net"] == pytest.approx(.02)


def test_14_loo_excludes_self():
    trades = pd.DataFrame({"execution_symbol": ["SOXL"], "weekday": [4], "entry_minute_et": [600], "horizon_minutes": [30], "net_return": [.02]})
    stats = mod.RunningStats(); [stats.add(x) for x in (.01, .02, .03)]
    result = mod.assign_loo(trades, {mod.baseline_key("SOXL", 4, 600, 30): stats})
    assert result.iloc[0]["matched_unconditional_loo_net"] == pytest.approx(.02)


def test_15_bootstrap_deterministic():
    values = np.arange(20) / 1000
    a = mod.circular_block_bootstrap_mean(values, 200, 5, 123)
    b = mod.circular_block_bootstrap_mean(values, 200, 5, 123)
    assert a == b


def test_16_periods():
    assert mod.study_period(2020) == mod.PERIODS[0]
    assert mod.study_period(2023) == mod.PERIODS[1]
    assert mod.study_period(2026) == mod.PERIODS[2]


def test_17_policy_constants():
    assert mod.EXECUTION_SYMBOLS == ("TQQQ", "SOXL")
    assert mod.COOLDOWN_MINUTES == 30
    assert mod.MAX_TRADES_PER_DAY == 3
    assert mod.ROUND_TRIP_COST == pytest.approx(.001)
