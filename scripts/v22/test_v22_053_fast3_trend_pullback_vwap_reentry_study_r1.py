from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_053_fast3_trend_pullback_vwap_reentry_study_r1 as mod


def valid_v22_052():
    return {
        "final_status": "PASS",
        "final_decision": "NO_LONG_NONOVERLAP_CANDIDATE_QUALIFIED",
        "data_ready_for_v22_053": False,
        "entry_filter_optimization_executed": False,
        "exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def test_v22_052_failed_architecture_gate_accepts():
    mod.validate_v22_052(valid_v22_052())


def test_v22_052_gate_rejects_unexpected_ready_state():
    payload = valid_v22_052()
    payload["data_ready_for_v22_053"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_052(payload)


def test_naive_timestamp_rejected():
    series = pd.Series(pd.to_datetime(["2026-01-02 10:00"]))
    with pytest.raises(mod.StudyError):
        mod.normalize_timestamp_utc(series)


def base_row(**updates):
    row = {
        "qqq_ret_30m": 0.01,
        "soxx_ret_30m": 0.02,
        "qqq_vwap_slope_15m": 0.001,
        "soxx_vwap_slope_15m": 0.002,
        "qqq_close": 101.0,
        "qqq_vwap": 100.0,
        "soxx_close": 202.0,
        "soxx_vwap": 200.0,
        "qqq_previous_high": 100.5,
        "soxx_previous_high": 201.5,
        "qqq_touch_prior_5m": True,
        "soxx_touch_prior_5m": True,
        "qqq_all_closes_above_vwap_prior_5m": True,
        "soxx_all_closes_above_vwap_prior_5m": True,
    }
    row.update(updates)
    return pd.Series(row)


def test_soxx_lead_selects_soxl():
    assert mod.pullback_reentry_condition_and_branch(
        base_row()
    ) == (True, "SOXL")


def test_qqq_lead_selects_tqqq():
    row = base_row(
        qqq_ret_30m=0.03,
        soxx_ret_30m=0.02,
    )
    assert mod.pullback_reentry_condition_and_branch(
        row
    ) == (True, "TQQQ")


def test_negative_higher_timeframe_trend_rejected():
    row = base_row(qqq_ret_30m=-0.01)
    assert mod.pullback_reentry_condition_and_branch(
        row
    ) == (False, None)


def test_missing_vwap_touch_rejected():
    row = base_row(soxx_touch_prior_5m=False)
    assert mod.pullback_reentry_condition_and_branch(
        row
    ) == (False, None)


def test_close_below_vwap_during_pullback_rejected():
    row = base_row(
        soxx_all_closes_above_vwap_prior_5m=False
    )
    assert mod.pullback_reentry_condition_and_branch(
        row
    ) == (False, None)


def test_no_reentry_breakout_rejected():
    row = base_row(
        soxx_close=201.4,
        soxx_previous_high=201.5,
    )
    assert mod.pullback_reentry_condition_and_branch(
        row
    ) == (False, None)


def aligned_fixture():
    utc = pd.date_range(
        "2026-01-02T15:00:00Z",
        periods=3,
        freq="1min",
        tz="UTC",
    )
    et = utc.tz_convert("America/New_York")
    rows = []
    for i, timestamp in enumerate(utc):
        active = i in (0, 2)
        rows.append(
            {
                "signal_timestamp_et": et[i],
                "trade_date": "2026-01-02",
                "soxx_trade_date": "2026-01-02",
                "qqq_ret_15m": 0.01,
                "soxx_ret_15m": 0.02,
                "qqq_ret_30m": 0.01,
                "soxx_ret_30m": 0.02,
                "qqq_vwap_slope_15m": 0.001,
                "soxx_vwap_slope_15m": 0.002,
                "qqq_close": 101.0,
                "qqq_vwap": 100.0,
                "soxx_close": 202.0 if active else 201.0,
                "soxx_vwap": 200.0,
                "qqq_previous_high": 100.5,
                "soxx_previous_high": 201.5,
                "qqq_touch_prior_5m": True,
                "soxx_touch_prior_5m": True,
                "qqq_all_closes_above_vwap_prior_5m": True,
                "soxx_all_closes_above_vwap_prior_5m": True,
            }
        )
    return pd.DataFrame(rows, index=utc)


def test_state_transition_only():
    candidates = mod.state_transition_candidates(
        aligned_fixture()
    )
    assert len(candidates) == 2


def execution_fixture():
    et = pd.date_range(
        "2026-01-02 09:30",
        "2026-01-02 15:59",
        freq="1min",
        tz="America/New_York",
    )
    utc = et.tz_convert("UTC")
    prices = 100.0 + np.arange(len(et)) * 0.01
    return pd.DataFrame(
        {
            "timestamp_utc": utc,
            "timestamp_et": et,
            "trade_date": "2026-01-02",
            "open": prices,
            "high": prices + 0.02,
            "low": prices - 0.02,
            "close": prices,
            "volume": 1000.0,
        }
    )


def candidate_fixture(times):
    utc = pd.to_datetime(times, utc=True)
    et = utc.tz_convert("America/New_York")
    return pd.DataFrame(
        {
            "signal_timestamp_utc": utc,
            "signal_timestamp_et": et,
            "trade_date": "2026-01-02",
            "weekday": 4,
            "signal_minute_et": [
                value.hour * 60 + value.minute
                for value in et
            ],
            "execution_symbol": "SOXL",
            "selected_signal_asset": "SOXX",
            "qqq_ret_15m": 0.01,
            "soxx_ret_15m": 0.02,
            "qqq_ret_30m": 0.01,
            "soxx_ret_30m": 0.02,
            "qqq_vwap_slope_15m": 0.001,
            "soxx_vwap_slope_15m": 0.002,
            "qqq_vwap_deviation_bps": 10.0,
            "soxx_vwap_deviation_bps": 20.0,
            "selected_touch_prior_5m": True,
            "selected_previous_high": 100.0,
        }
    )


def test_next_minute_open_and_exact_exit():
    frame = execution_fixture()
    trades = mod.schedule_nonoverlap_trades(
        candidate_fixture(["2026-01-02T15:00:00Z"]),
        {"SOXL": frame, "TQQQ": frame},
        30,
    )
    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["entry_timestamp_utc"] == pd.Timestamp(
        "2026-01-02T15:01:00Z"
    )
    assert row["exit_timestamp_utc"] == pd.Timestamp(
        "2026-01-02T15:31:00Z"
    )


def test_round_trip_cost_is_ten_bps():
    frame = execution_fixture()
    trades = mod.schedule_nonoverlap_trades(
        candidate_fixture(["2026-01-02T15:00:00Z"]),
        {"SOXL": frame, "TQQQ": frame},
        30,
    )
    row = trades.iloc[0]
    assert row["net_return"] == pytest.approx(
        row["gross_return"] - 0.001
    )


def test_nonoverlap_and_cooldown():
    frame = execution_fixture()
    candidates = candidate_fixture(
        [
            "2026-01-02T15:00:00Z",
            "2026-01-02T15:20:00Z",
            "2026-01-02T16:01:00Z",
        ]
    )
    trades = mod.schedule_nonoverlap_trades(
        candidates,
        {"SOXL": frame, "TQQQ": frame},
        30,
    )
    assert len(trades) == 2


def test_max_three_trades_per_day():
    assert mod.MAX_TRADES_PER_DAY == 3


def test_late_signal_rejected_for_full_horizon():
    frame = execution_fixture()
    trades = mod.schedule_nonoverlap_trades(
        candidate_fixture(["2026-01-02T20:30:00Z"]),
        {"SOXL": frame, "TQQQ": frame},
        30,
    )
    assert trades.empty


def test_pit_baseline_uses_prior_history():
    trades = pd.DataFrame(
        {
            "execution_symbol": ["SOXL"],
            "weekday": [4],
            "entry_minute_et": [600],
            "horizon_minutes": [30],
            "net_return": [0.02],
        }
    )
    key = mod.baseline_key("SOXL", 4, 600, 30)
    stats = mod.RunningStats()
    stats.add(0.01)
    stats.add(0.03)
    result = mod.assign_pit_baseline(
        trades,
        {key: stats},
    )
    assert result["matched_unconditional_pit_net"].iloc[0] == pytest.approx(
        0.02
    )


def test_leave_one_out_excludes_current_trade():
    trades = pd.DataFrame(
        {
            "execution_symbol": ["SOXL"],
            "weekday": [4],
            "entry_minute_et": [600],
            "horizon_minutes": [30],
            "net_return": [0.02],
        }
    )
    key = mod.baseline_key("SOXL", 4, 600, 30)
    stats = mod.RunningStats()
    for value in (0.01, 0.02, 0.03):
        stats.add(value)
    result = mod.assign_loo(trades, {key: stats})
    assert result["matched_loo_count"].iloc[0] == 2
    assert result["matched_unconditional_loo_net"].iloc[0] == pytest.approx(
        0.02
    )


def test_bootstrap_is_deterministic():
    values = np.arange(20, dtype=float) / 1000
    first = mod.circular_block_bootstrap_mean(
        values,
        200,
        5,
        123,
    )
    second = mod.circular_block_bootstrap_mean(
        values,
        200,
        5,
        123,
    )
    assert first == second


def test_period_mapping():
    assert mod.study_period(2020) == mod.PERIODS[0]
    assert mod.study_period(2023) == mod.PERIODS[1]
    assert mod.study_period(2026) == mod.PERIODS[2]


def test_policy_constants():
    assert mod.EXECUTION_SYMBOLS == ("TQQQ", "SOXL")
    assert mod.ROUND_TRIP_COST == pytest.approx(0.001)
    assert mod.COOLDOWN_MINUTES == 30


def test_default_input_is_v22_052_summary():
    args = mod.parse_args(["--execute"])
    assert str(args.v22_052_summary).endswith(
        r"V22.052_FAST3_LONG_NONOVERLAP_STATE_TRANSITION_STUDY_R1\v22_052_summary.json"
    )
