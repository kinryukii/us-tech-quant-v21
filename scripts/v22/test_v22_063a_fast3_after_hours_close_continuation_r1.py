from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_063a_fast3_after_hours_close_continuation_r1 as mod


def valid_overnight():
    return {
        "final_status": "PASS",
        "final_decision": (
            "OVERNIGHT_VWAP_MEAN_REVERSION_"
            "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
        ),
        "v22_062pr_validated": True,
        "premarket_forward_chain_modified": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def valid_forward():
    return {
        "final_status": "PASS",
        "v22_062pb_validated": True,
        "research_cutoff_date": "2026-07-24",
        "forward_holdout_only": True,
        "rule_change_requires_reset": True,
        "sole_exit_variant": "PREMARKET_0925",
        "historical_pre_cutoff_outcomes_used_for_qualification": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def valid_rth():
    return {
        "final_status": "PASS",
        "final_decision": (
            "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED"
        ),
        "v22_062pr_validated": True,
        "premarket_forward_chain_modified": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }


def synthetic_full_day(
    trade_date: str = "2026-01-05",
    base: float = 100.0,
) -> pd.DataFrame:
    rth = pd.date_range(
        f"{trade_date} 09:30",
        periods=390,
        freq="min",
        tz="America/New_York",
    )
    after = pd.date_range(
        f"{trade_date} 16:00",
        periods=240,
        freq="min",
        tz="America/New_York",
    )
    timestamps = rth.append(after)
    close = base + np.arange(len(timestamps)) * 0.001
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps.tz_convert("UTC"),
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": np.full(len(timestamps), 1000.0),
        }
    )


def extracted(base: float = 100.0):
    return mod.normalize_and_extract(
        synthetic_full_day(base=base),
    )


def ah_grid(base: float = 100.0) -> pd.DataFrame:
    ah, _, _, _ = extracted(base)
    return mod.session_grid(ah)


def rth_context(
    close: float = 101.0,
    vwap: float = 100.0,
    ret30: float = 0.01,
) -> pd.Series:
    return pd.Series(
        {
            "trade_date": "2026-01-05",
            "rth_close": close,
            "rth_vwap": vwap,
            "rth_return_30m": ret30,
        }
    )


def force_long_grids():
    qqq = ah_grid(102.0)
    soxx = ah_grid(202.0)
    for grid, level in ((qqq, 102.0), (soxx, 202.0)):
        grid.loc[30:35, "normalized_close"] = np.linspace(
            level + 1.0,
            level + 1.5,
            6,
        )
        grid.loc[30:35, "normalized_open"] = grid.loc[
            30:35,
            "normalized_close",
        ]
        grid.loc[30:35, "ret_15m"] = 0.01
        grid.loc[30:35, "normalized_momentum_15m"] = 2.0
        grid.loc[30:35, "vwap"] = level
        grid.loc[30:35, "tradability_proxy_pass"] = True
    return qqq, soxx


def test_validate_lineage():
    mod.validate_lineage(
        valid_overnight(),
        valid_forward(),
        valid_rth(),
    )


def test_validate_lineage_rejects():
    source = valid_overnight()
    source["parameter_sweep_executed"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_lineage(source, valid_forward(), valid_rth())


def test_extract_after_hours_and_rth():
    ah, rth, recognized, unresolved = extracted()
    assert len(ah) == 240
    assert len(rth) == 1
    assert recognized.empty
    assert unresolved.empty


def test_rth_return_30m():
    _, rth, _, _ = extracted()
    assert rth.iloc[0]["rth_return_30m"] > 0


def test_normalize_split():
    frame = synthetic_full_day().head(10)
    frame.loc[5:, ["open", "high", "low", "close"]] /= 10.0
    _, _, recognized, unresolved = mod.normalize_and_extract(
        frame,
    )
    assert len(recognized) == 1
    assert unresolved.empty


def test_session_grid_length():
    assert len(ah_grid()) == 240


def test_tradability_proxy():
    assert bool(ah_grid().loc[60, "tradability_proxy_pass"])


def test_sparse_rejected():
    ah, _, _, _ = extracted()
    grid = mod.session_grid(ah.iloc[::5].copy())
    assert not bool(grid.loc[60, "tradability_proxy_pass"])


def test_build_long_candidate():
    qqq, soxx = force_long_grids()
    candidate, reasons = mod.build_candidate(
        "2026-01-05",
        qqq,
        soxx,
        rth_context(101.0, 100.0, 0.01),
        rth_context(201.0, 200.0, 0.01),
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert not reasons
    assert candidate is not None
    assert candidate["direction"] == "LONG"


def test_candidate_requires_rth_context():
    qqq, soxx = force_long_grids()
    candidate, _ = mod.build_candidate(
        "2026-01-05",
        qqq,
        soxx,
        rth_context(101.0, 100.0, -0.01),
        rth_context(201.0, 200.0, -0.01),
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert candidate is None


def test_candidate_blocked_by_event():
    qqq, soxx = force_long_grids()
    events = pd.DataFrame(
        {
            "timestamp_utc": [
                pd.Timestamp("2026-01-05 22:00:00+00:00")
            ]
        }
    )
    candidate, reasons = mod.build_candidate(
        "2026-01-05",
        qqq,
        soxx,
        rth_context(),
        rth_context(201.0, 200.0, 0.01),
        {"QQQ": events, "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert candidate is None
    assert any("SCALE_EVENT" in reason for reason in reasons)


def test_exit_minutes():
    assert mod.exit_minute("FIXED_30M", 60) == 90
    assert mod.exit_minute("FIXED_60M", 60) == 120
    assert mod.exit_minute("SESSION_1955", 60) == 235


def test_return_from_grid():
    result = mod.return_from_grid(ah_grid(), 60, 90)
    assert result is not None
    assert result[1]["holding_minutes"] == 30


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    ) == pytest.approx(3.0)


def test_positive_profit_share():
    assert mod.positive_profit_share(
        pd.Series([0.8, 0.1, 0.1, -0.1]),
        1,
    ) == pytest.approx(0.8)


def test_cumulative_return():
    assert mod.cumulative_return(
        pd.Series([0.10, -0.10])
    ) == pytest.approx(-0.01)


def test_maximum_drawdown():
    assert mod.maximum_drawdown(
        pd.Series([0.10, -0.20, 0.10])
    ) == pytest.approx(-0.20)


def test_choose_insufficient():
    frame = pd.DataFrame(
        {
            "exit_variant": list(mod.EXIT_VARIANTS),
            "sample_pass": [False, False, False],
            "research_candidate_for_independent_replication": [
                False,
                False,
                False,
            ],
        }
    )
    decision, supported = mod.choose_decision(frame)
    assert decision == (
        "AFTER_HOURS_CLOSE_CONTINUATION_"
        "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    )
    assert supported == []


def test_choose_supported():
    frame = pd.DataFrame(
        {
            "exit_variant": list(mod.EXIT_VARIANTS),
            "sample_pass": [True, True, True],
            "research_candidate_for_independent_replication": [
                False,
                True,
                False,
            ],
        }
    )
    decision, supported = mod.choose_decision(frame)
    assert "REQUIRES_INDEPENDENT_REPLICATION" in decision
    assert supported == ["FIXED_60M"]


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.063N_FAST3" in args.v22_063n_summary
    assert "V22.062PR_FAST3" in args.v22_062pr_summary
    assert "V22.063R1_FAST3" in args.v22_063r1_summary


def test_policy_constants():
    assert mod.SIGNAL_START == 30
    assert mod.SIGNAL_END == 150
    assert mod.SESSION_EXIT_MINUTE == 235
    assert mod.FIXED_ACCOUNT_WEIGHT == 0.20


def test_standalone_helpers_present():
    assert callable(mod.index_canonical)
    assert callable(mod.load_symbol_full)
    assert callable(mod.snap_split_factor)
    assert callable(mod.study_period)


def test_study_period_mapping():
    assert mod.study_period(2020) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2024) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == "2025-2026_YTD_CONFIRMATION"


def test_symbol_month_from_path():
    path = (
        mod.Path("root")
        / "symbol=US.SOXL"
        / "year=2026"
        / "month=7"
        / "part.parquet"
    )
    assert mod.symbol_month_from_path(path) == (
        "SOXL",
        "2026",
        "07",
    )


def test_split_factor_forward_and_reverse():
    assert mod.snap_split_factor(20.0)[0] == pytest.approx(20.0)
    assert mod.snap_split_factor(0.05)[0] == pytest.approx(0.05)


def test_split_factor_rejects_unrecognized_ratio():
    assert mod.snap_split_factor(1.37) is None


def test_module_has_no_runtime_dependency_loader():
    assert not hasattr(mod, "load_dependency")
