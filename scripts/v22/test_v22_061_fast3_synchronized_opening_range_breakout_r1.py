from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import v22_061_fast3_synchronized_opening_range_breakout_r1 as mod


def valid_v22_060():
    return {
        "final_status": "PASS",
        "final_decision": (
            "NO_RISK_SCALER_OR_EXIT_ARCHITECTURE_QUALIFIED"
        ),
        "v22_059_validated": True,
        "v22_059a_validated": True,
        "source_variant": "NO_VIX_CONTROL",
        "canonical_partition_count_read": 0,
        "etf_minute_data_read": False,
        "backtest_entry_signal_regenerated": False,
        "parameter_sweep_executed": False,
        "risk_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "recommended_exit_variant": None,
        "risk_metrics_pass": False,
        "tradable_edge_pass": False,
        "hard_stop_capture_problem": False,
        "next_stage": "STOP_CURRENT_FAST3_ENTRY_ARCHITECTURE",
    }


def valid_v22_056():
    return {
        "final_status": "PASS",
        "final_decision": (
            "OFFICIAL_CBOE_DAILY_VIX_READY_FOR_PRIOR_DAY_REGIME_FILTER"
        ),
        "prior_day_shift_validated": True,
        "daily_vix_regime_ready": True,
        "intraday_vix_data_ready": False,
        "intraday_vix_features_allowed": False,
        "vix_proxy_substitution_used": False,
        "data_ready_for_daily_vix_multifactor_backtest": True,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def minute_day(
    trade_date: str = "2026-01-05",
    drift: float = 0.01,
    breakout: str | None = None,
) -> pd.DataFrame:
    timestamp_et = pd.date_range(
        f"{trade_date} 09:30",
        periods=390,
        freq="min",
        tz="America/New_York",
    )
    minute = timestamp_et.hour * 60 + timestamp_et.minute
    close = 100.0 + np.arange(390) * drift
    if breakout == "LONG":
        close[30:] += 1.0
    elif breakout == "SHORT":
        close[30:] -= 2.0

    open_price = close - drift / 2.0
    high = np.maximum(open_price, close) + 0.05
    low = np.minimum(open_price, close) - 0.05
    return pd.DataFrame(
        {
            "timestamp_utc": timestamp_et.tz_convert("UTC"),
            "timestamp_et": timestamp_et,
            "trade_date": trade_date,
            "minute_et": minute,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(390, 1000.0),
        }
    )


def aligned_long_day():
    qqq = minute_day(drift=0.001)
    soxx = minute_day(drift=0.0015)
    # Keep opening range stable, then create a synchronous breakout at 10:05.
    for frame, jump in [(qqq, 1.0), (soxx, 1.5)]:
        mask = frame["minute_et"] >= 605
        frame.loc[mask, ["open", "high", "low", "close"]] += jump
    return mod.align_signal_days(qqq, soxx)


def test_validate_v22_060():
    mod.validate_v22_060(valid_v22_060())


def test_validate_v22_060_rejects():
    summary = valid_v22_060()
    summary["risk_metrics_pass"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_060(summary)


def test_validate_v22_056():
    mod.validate_v22_056(valid_v22_056())


def test_study_period():
    assert mod.study_period(2020) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2024) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == (
        "2025-2026_YTD_CONFIRMATION"
    )


def test_symbol_month_path():
    path = (
        mod.Path("x")
        / "symbol=US.QQQ"
        / "year=2025"
        / "month=7"
        / "a.parquet"
    )
    assert mod.symbol_month_from_path(path) == (
        "QQQ",
        "2025",
        "07",
    )


def test_enrich_opening_range():
    result = mod.enrich_minute_day(minute_day())
    assert result["opening_range_complete"].all()
    assert result["opening_range_high"].notna().all()
    assert result["opening_range_low"].notna().all()


def test_enrich_vwap():
    result = mod.enrich_minute_day(minute_day())
    assert result["vwap"].notna().all()


def test_enrich_ret15():
    result = mod.enrich_minute_day(minute_day())
    assert result["ret_15m"].iloc[:15].isna().all()
    assert result["ret_15m"].iloc[15:].notna().all()


def test_incomplete_opening_range():
    frame = minute_day().iloc[1:].reset_index(drop=True)
    result = mod.enrich_minute_day(frame)
    assert not result["opening_range_complete"].any()


def test_aggregate_complete_5m():
    result = mod.aggregate_complete_5m(minute_day())
    assert len(result) == 78
    assert (result["minute_count"] == 5).all()


def test_rsi_length():
    result = mod.rsi_wilder(
        pd.Series(np.arange(50, dtype=float))
    )
    assert len(result) == 50


def test_kdj_length():
    frame = minute_day().head(40)
    k, d, j = mod.kdj(frame)
    assert len(k) == len(frame)
    assert len(d) == len(frame)
    assert len(j) == len(frame)


def test_diagnostic_factors():
    bars = mod.aggregate_complete_5m(minute_day())
    result = mod.add_diagnostic_factors(bars)
    assert {
        "rsi14",
        "macd_hist",
        "kdj_k",
        "kdj_d",
        "kdj_j",
    }.issubset(result.columns)


def test_prior_abs_percentile_warmup():
    values = pd.Series(
        np.sin(np.arange(400) / 7.0) / 100.0
    )
    result = mod.rolling_prior_abs_percentile(values)
    assert result.iloc[:253].isna().all()


def test_align_signal_days():
    result = aligned_long_day()
    assert not result.empty
    assert "qqq_vwap" in result.columns
    assert "soxx_vwap" in result.columns


def test_long_candidate():
    result = mod.build_first_candidate(aligned_long_day())
    assert result is not None
    assert result["direction"] == "LONG"
    assert result["execution_symbol"] in {"SOXL", "TQQQ"}
    assert result["signal_minute_et"] >= mod.SIGNAL_START


def test_max_one_candidate():
    result = mod.build_first_candidate(aligned_long_day())
    assert isinstance(result, dict)


def test_cost_adjusted_return():
    result = mod.cost_adjusted_return(100.0, 101.0)
    expected = (
        101.0 * (1.0 - mod.EXIT_COST)
        / (100.0 * (1.0 + mod.ENTRY_COST))
        - 1.0
    )
    assert result == pytest.approx(expected)


def test_exact_fixed_exit():
    day = minute_day()
    table = mod.execution_index(day)
    entry_timestamp = table.index[31]
    row = table.loc[entry_timestamp]
    assert mod.exact_exit_timestamp(
        entry_timestamp,
        row,
        "FIXED_30M",
    ) == entry_timestamp + pd.Timedelta(minutes=30)


def test_exact_session_exit():
    day = minute_day()
    table = mod.execution_index(day)
    entry_timestamp = table.index[31]
    row = table.loc[entry_timestamp]
    target = mod.exact_exit_timestamp(
        entry_timestamp,
        row,
        "SESSION_1555",
    )
    assert int(target.tz_convert("America/New_York").hour) == 15
    assert int(target.tz_convert("America/New_York").minute) == 55


def sample_candidate():
    aligned = aligned_long_day()
    return mod.build_first_candidate(aligned)


def test_simulate_candidate():
    candidate = sample_candidate()
    result = mod.simulate_candidate(
        candidate,
        minute_day(drift=0.002),
        {},
    )
    assert len(result) == 3
    assert {row["exit_variant"] for row in result} == set(
        mod.EXIT_VARIANTS
    )


def test_baseline_is_prior_only():
    baseline = {}
    day = minute_day(drift=0.002)
    candidate = sample_candidate()
    first = mod.simulate_candidate(candidate, day, baseline)
    assert all(row["pit_baseline_count"] == 0 for row in first)
    mod.update_baseline_for_day("SOXL", day, baseline)
    second = mod.simulate_candidate(
        {**candidate, "execution_symbol": "SOXL"},
        day,
        baseline,
    )
    assert all(row["pit_baseline_count"] == 1 for row in second)


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    ) == pytest.approx(3.0)


def test_max_drawdown():
    assert mod.maximum_drawdown(
        pd.Series([0.10, -0.20, 0.10])
    ) == pytest.approx(-0.20)


def test_cumulative_return():
    assert mod.cumulative_return(
        pd.Series([0.10, -0.10])
    ) == pytest.approx(-0.01)


def test_choose_insufficient():
    frame = pd.DataFrame(
        {
            "exit_variant": list(mod.EXIT_VARIANTS),
            "sample_evaluable": [False, False, False],
            "research_candidate_for_next_stage": [
                False,
                False,
                False,
            ],
        }
    )
    decision, supported = mod.choose_decision(frame)
    assert decision == (
        "ORB_BASELINE_INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    )
    assert supported == []


def test_choose_supported():
    frame = pd.DataFrame(
        {
            "exit_variant": list(mod.EXIT_VARIANTS),
            "sample_evaluable": [True, True, True],
            "research_candidate_for_next_stage": [
                False,
                True,
                False,
            ],
        }
    )
    decision, supported = mod.choose_decision(frame)
    assert decision == (
        "ORB_BASELINE_CANDIDATE_SUPPORTED_FOR_INDEPENDENT_REPLICATION"
    )
    assert supported == ["FIXED_60M"]


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.060_FAST3" in args.v22_060_summary
    assert "V22.056_FAST3" in args.v22_056_summary
    assert "vix_daily.parquet" in args.vix_daily
    assert "moomoo_24h_1m" in args.canonical_root


def test_policy_constants():
    assert mod.OPENING_RANGE_END - mod.RTH_START + 1 == 30
    assert mod.SIGNAL_START == 600
    assert mod.SIGNAL_END == 870
    assert mod.FIXED_ACCOUNT_WEIGHT == 0.33
    assert mod.ENTRY_COST == 0.0005
    assert mod.EXIT_COST == 0.0005
