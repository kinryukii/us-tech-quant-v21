from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_062p_fast3_premarket_gap_range_r1 as mod


def valid_062n():
    return {
        "final_status": "PASS",
        "final_decision": "NO_OVERNIGHT_BASELINE_CANDIDATE_QUALIFIED",
        "v22_061_validated": True,
        "v22_056_validated": True,
        "rth_orb_architecture_used": False,
        "pullback_reentry_architecture_used": False,
        "session_name": "OVERNIGHT",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "parameter_sweep_executed": False,
        "session_window_sweep_executed": False,
        "initial_range_length_sweep_executed": False,
        "liquidity_threshold_sweep_executed": False,
        "indicator_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "canonical_partition_count_indexed": 582,
        "supported_exit_variants_for_replication": [],
    }


def valid_056():
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


def synthetic_premarket(
    session_date: str = "2026-01-06",
    base: float = 100.0,
    drift: float = 0.001,
    jump_minute: int | None = None,
    jump: float = 0.0,
) -> pd.DataFrame:
    timestamp_et = pd.date_range(
        f"{session_date} 04:00",
        periods=330,
        freq="min",
        tz="America/New_York",
    )
    close = base + np.arange(330) * drift
    if jump_minute is not None:
        close[jump_minute:] += jump

    open_price = close - drift / 2.0
    high = np.maximum(open_price, close) + 0.02
    low = np.minimum(open_price, close) - 0.02
    return pd.DataFrame(
        {
            "timestamp_utc": timestamp_et.tz_convert("UTC"),
            "timestamp_et": timestamp_et,
            "local_date": session_date,
            "minute_et": (
                timestamp_et.hour * 60 + timestamp_et.minute
            ),
            "session_minute": np.arange(330, dtype=np.int16),
            "row_type": "PREMARKET",
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(330, 100.0),
        }
    )


def prior(close: float = 99.0):
    return {
        "prior_close_date": "2026-01-05",
        "prior_close_timestamp_utc": pd.Timestamp(
            "2026-01-05 20:59:00+00:00"
        ),
        "prior_rth_close": close,
    }


def long_grids():
    qqq = synthetic_premarket(
        drift=0.0005,
        jump_minute=130,
        jump=1.0,
    )
    soxx = synthetic_premarket(
        base=200.0,
        drift=0.0008,
        jump_minute=130,
        jump=2.0,
    )
    return mod.session_grid(qqq), mod.session_grid(soxx)


def test_validate_062n():
    mod.validate_v22_062n(valid_062n())


def test_validate_062n_rejects():
    summary = valid_062n()
    summary["vix_entry_gate_used"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_v22_062n(summary)


def test_validate_056():
    mod.validate_v22_056(valid_056())


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


def test_get_session_with_retained_index_columns():
    source = synthetic_premarket()
    table = source.set_index(
        ["local_date", "session_minute"],
        drop=False,
    ).sort_index()
    result = mod.get_session(table, "2026-01-06")
    assert len(result) == 330
    assert list(result["session_minute"].head(3)) == [0, 1, 2]


def test_prior_close_is_strictly_earlier():
    closes = pd.DataFrame(
        {
            "prior_close_date": [
                "2026-01-05",
                "2026-01-06",
            ],
            "prior_close_timestamp_utc": pd.to_datetime(
                [
                    "2026-01-05 20:59:00+00:00",
                    "2026-01-06 20:59:00+00:00",
                ]
            ),
            "prior_rth_close": [99.0, 101.0],
        }
    )
    closes["prior_close_date_timestamp"] = pd.to_datetime(
        closes["prior_close_date"]
    )
    result = mod.prior_close_for_session(
        closes,
        "2026-01-06",
    )
    assert result is not None
    assert result["prior_close_date"] == "2026-01-05"
    assert result["prior_rth_close"] == pytest.approx(99.0)


def test_session_grid_length():
    grid = mod.session_grid(synthetic_premarket())
    assert len(grid) == 330


def test_initial_range_complete():
    grid = mod.session_grid(synthetic_premarket())
    assert bool(grid["initial_range_complete"].iloc[0])


def test_initial_range_incomplete():
    day = synthetic_premarket().loc[
        lambda frame: frame["session_minute"] >= 20
    ]
    grid = mod.session_grid(day)
    assert not bool(grid["initial_range_complete"].iloc[0])


def test_exact_30m_return():
    grid = mod.session_grid(
        synthetic_premarket(drift=0.01)
    )
    expected = grid.loc[160, "close"] / grid.loc[130, "close"] - 1.0
    assert grid.loc[160, "ret_30m"] == pytest.approx(expected)


def test_tradability_proxy():
    grid = mod.session_grid(
        synthetic_premarket(drift=0.01)
    )
    assert bool(grid.loc[180, "tradability_proxy_pass"])


def test_tradability_proxy_rejects_sparse():
    day = synthetic_premarket().iloc[::5].copy()
    grid = mod.session_grid(day)
    assert not bool(grid.loc[180, "tradability_proxy_pass"])


def test_diagnostic_keys():
    grid = mod.session_grid(synthetic_premarket())
    result = mod.diagnostic_5m_at(grid, 200)
    assert set(result) == {
        "rsi14",
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "kdj_k",
        "kdj_d",
        "kdj_j",
    }


def test_long_candidate():
    qqq, soxx = long_grids()
    result = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        prior(99.0),
        prior(198.0),
    )
    assert result is not None
    assert result["direction"] == "LONG"
    assert result["execution_symbol"] in {"SOXL", "TQQQ"}
    assert result["signal_session_minute"] >= mod.SIGNAL_START


def test_gap_direction_required():
    qqq, soxx = long_grids()
    result = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        prior(500.0),
        prior(500.0),
    )
    assert result is None


def test_max_one_candidate():
    qqq, soxx = long_grids()
    result = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        prior(99.0),
        prior(198.0),
    )
    assert isinstance(result, dict)


def test_cost_adjusted_return():
    result = mod.cost_adjusted_long_return(100.0, 101.0)
    expected = (
        101.0 * (1.0 - mod.EXIT_COST)
        / (100.0 * (1.0 + mod.ENTRY_COST))
        - 1.0
    )
    assert result == pytest.approx(expected)


def test_exit_minutes():
    assert mod.exit_minute(150, "FIXED_30M") == 180
    assert mod.exit_minute(150, "FIXED_60M") == 210
    assert mod.exit_minute(150, "PREMARKET_0925") == 325


def test_signal_end_keeps_60m_in_premarket():
    latest_entry = mod.SIGNAL_END + 1
    assert mod.exit_minute(
        latest_entry,
        "FIXED_60M",
    ) <= mod.PREMARKET_EXIT_MINUTE


def test_return_from_grid():
    grid = mod.session_grid(
        synthetic_premarket(drift=0.01)
    )
    result = mod.return_from_grid(grid, 150, "FIXED_30M")
    assert result is not None
    assert result[1]["holding_minutes"] == 30


def test_simulate_candidate():
    qqq, soxx = long_grids()
    candidate = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        prior(99.0),
        prior(198.0),
    )
    grids = {
        "QQQ": qqq,
        "SOXX": soxx,
        "TQQQ": mod.session_grid(
            synthetic_premarket(base=50.0, drift=0.01)
        ),
        "SOXL": mod.session_grid(
            synthetic_premarket(base=40.0, drift=0.015)
        ),
        "SQQQ": mod.session_grid(
            synthetic_premarket(base=30.0, drift=-0.005)
        ),
        "SOXS": mod.session_grid(
            synthetic_premarket(base=20.0, drift=-0.007)
        ),
    }
    rows = mod.simulate_candidate(candidate, grids)
    assert len(rows) == 3
    assert {row["exit_variant"] for row in rows} == set(
        mod.EXIT_VARIANTS
    )


def test_pair_baseline_count():
    qqq, soxx = long_grids()
    candidate = mod.build_candidate(
        "2026-01-06",
        qqq,
        soxx,
        prior(99.0),
        prior(198.0),
    )
    grids = {
        "QQQ": qqq,
        "SOXX": soxx,
        "TQQQ": mod.session_grid(synthetic_premarket(base=50.0)),
        "SOXL": mod.session_grid(synthetic_premarket(base=40.0)),
        "SQQQ": mod.session_grid(synthetic_premarket(base=30.0)),
        "SOXS": mod.session_grid(synthetic_premarket(base=20.0)),
    }
    rows = mod.simulate_candidate(candidate, grids)
    assert all(
        row["direction_pair_baseline_count"] == 2
        for row in rows
    )


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    ) == pytest.approx(3.0)


def test_maximum_drawdown():
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
        "PREMARKET_BASELINE_INCONCLUSIVE_INSUFFICIENT_TRADABLE_SAMPLE"
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
        "PREMARKET_BASELINE_CANDIDATE_SUPPORTED_FOR_INDEPENDENT_REPLICATION"
    )
    assert supported == ["FIXED_60M"]


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.062N_FAST3" in args.v22_062n_summary
    assert "V22.056_FAST3" in args.v22_056_summary
    assert "vix_daily.parquet" in args.vix_daily
    assert "moomoo_24h_1m" in args.canonical_root


def test_policy_constants():
    assert mod.PREMARKET_LENGTH == 330
    assert mod.INITIAL_RANGE_END - mod.INITIAL_RANGE_START + 1 == 120
    assert mod.SIGNAL_START == 120
    assert mod.SIGNAL_END == 264
    assert mod.PREMARKET_EXIT_MINUTE == 325
    assert mod.FIXED_ACCOUNT_WEIGHT == 0.20
    assert mod.ENTRY_COST == 0.0005
    assert mod.EXIT_COST == 0.0005
