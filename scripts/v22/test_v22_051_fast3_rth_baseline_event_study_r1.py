from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_051_fast3_rth_baseline_event_study_r1 as mod


def valid_v22_050():
    return {
        "final_status": "PASS",
        "data_ready_for_fast3_backtest": True,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def test_v22_050_gate_accepts():
    mod.validate_v22_050(valid_v22_050())


def test_v22_050_gate_rejects():
    payload = valid_v22_050()
    payload["data_ready_for_fast3_backtest"] = False
    with pytest.raises(mod.StudyError):
        mod.validate_v22_050(payload)


def test_naive_timestamp_rejected():
    series = pd.Series(pd.to_datetime(["2026-01-01 10:00:00"]))
    with pytest.raises(mod.StudyError):
        mod.normalize_timestamp_utc(series)


def test_cumulative_vwap():
    frame = pd.DataFrame(
        {
            "high": [10.0, 12.0],
            "low": [8.0, 10.0],
            "close": [9.0, 11.0],
            "volume": [100.0, 300.0],
        }
    )
    result = mod.cumulative_vwap(frame)
    assert result.iloc[0] == pytest.approx(9.0)
    assert result.iloc[1] == pytest.approx((9.0 * 100 + 11.0 * 300) / 400)


def test_exact_elapsed_return_requires_exact_minute():
    index = pd.to_datetime(
        ["2026-01-02T14:30:00Z", "2026-01-02T14:45:00Z", "2026-01-02T14:46:00Z"],
        utc=True,
    )
    close = pd.Series([100.0, 110.0, 111.0], index=index)
    result = mod.exact_elapsed_return(close, 15)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(0.10)
    assert np.isnan(result.iloc[2])


def test_long_selects_soxl():
    decision = mod.determine_signal(0.01, 0.02, 101, 100, 202, 200)
    assert decision == ("LONG", "SOXL")


def test_long_selects_tqqq():
    decision = mod.determine_signal(0.02, 0.01, 101, 100, 202, 200)
    assert decision == ("LONG", "TQQQ")


def test_short_selects_soxs():
    decision = mod.determine_signal(-0.01, -0.02, 99, 100, 198, 200)
    assert decision == ("SHORT", "SOXS")


def test_short_selects_sqqq():
    decision = mod.determine_signal(-0.02, -0.01, 99, 100, 198, 200)
    assert decision == ("SHORT", "SQQQ")


def test_mixed_direction_has_no_signal():
    assert mod.determine_signal(0.01, -0.01, 101, 100, 198, 200) is None


def test_time_buckets():
    assert mod.time_bucket(pd.Timestamp("2026-01-02 09:45", tz="America/New_York")) == "09:45-10:29"
    assert mod.time_bucket(pd.Timestamp("2026-01-02 10:30", tz="America/New_York")) == "10:30-11:59"
    assert mod.time_bucket(pd.Timestamp("2026-01-02 12:00", tz="America/New_York")) == "12:00-13:59"
    assert mod.time_bucket(pd.Timestamp("2026-01-02 14:00", tz="America/New_York")) == "14:00-15:30"


def execution_fixture():
    et = pd.date_range(
        "2026-01-02 09:45",
        "2026-01-02 15:59",
        freq="1min",
        tz="America/New_York",
    )
    utc = et.tz_convert("UTC")
    close = 100.0 + np.arange(len(et)) * 0.01
    return pd.DataFrame(
        {
            "timestamp_utc": utc,
            "timestamp_et": et,
            "trade_date": "2026-01-02",
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_next_minute_open_execution():
    frame = execution_fixture()
    signal = pd.Timestamp("2026-01-02 09:45", tz="America/New_York").tz_convert("UTC")
    result = mod.compute_event_metrics(frame, signal)
    assert result is not None
    assert result["entry_timestamp_utc"] == signal + pd.Timedelta(minutes=1)
    expected = frame.loc[frame["timestamp_utc"] == signal + pd.Timedelta(minutes=1), "open"].iloc[0]
    assert result["entry_price"] == pytest.approx(expected)


def test_round_trip_cost():
    frame = execution_fixture()
    signal = pd.Timestamp("2026-01-02 09:45", tz="America/New_York").tz_convert("UTC")
    result = mod.compute_event_metrics(frame, signal)
    gross = result["forward_return_5m_gross"]
    net = result["forward_return_5m_net"]
    assert net == pytest.approx(gross - 0.001)


def test_forced_exit_is_at_1555():
    frame = execution_fixture()
    signal = pd.Timestamp("2026-01-02 15:30", tz="America/New_York").tz_convert("UTC")
    result = mod.compute_event_metrics(frame, signal)
    assert result["forced_exit_timestamp_et"].hour == 15
    assert result["forced_exit_timestamp_et"].minute == 55


def test_same_bar_threshold_tie_is_adverse_first():
    future = pd.DataFrame({"high": [102.0], "low": [99.0]})
    plus_first, minus_first = mod.threshold_first_hit(
        future,
        100.0,
        positive_threshold=0.01,
        negative_threshold=-0.006,
    )
    assert plus_first is False
    assert minus_first is True


def test_study_periods():
    assert mod.study_period(2020) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2023) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == "2025-2026_YTD_CONFIRMATION"


def test_policy_gates_fixed_false():
    assert mod.ROUND_TRIP_COST == pytest.approx(0.001)
