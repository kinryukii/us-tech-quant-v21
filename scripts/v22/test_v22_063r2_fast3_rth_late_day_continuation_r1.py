from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import v22_063r2_fast3_rth_late_day_continuation_r1 as mod


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


def valid_ah():
    return {
        "final_status": "PASS",
        "final_decision": (
            "NO_AFTER_HOURS_CLOSE_CONTINUATION_CANDIDATE_QUALIFIED"
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


def synthetic_rth(
    trade_date: str = "2026-01-05",
    base: float = 100.0,
) -> pd.DataFrame:
    timestamps = pd.date_range(
        f"{trade_date} 09:30",
        periods=390,
        freq="min",
        tz="America/New_York",
    )
    close = base + np.arange(390) * 0.01
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps.tz_convert("UTC"),
            "trade_date": trade_date,
            "session_minute": np.arange(390),
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": np.full(390, 1000.0),
        }
    )


def grid(base: float = 100.0) -> pd.DataFrame:
    normalized, _, _ = mod.normalize_scale_series(
        synthetic_rth(base=base)
    )
    return mod.session_grid(normalized)


def forced_long_grids():
    qqq = grid(100.0)
    soxx = grid(200.0)
    for current in (qqq, soxx):
        current.loc[240:245, "normalized_close"] += 3.0
        current.loc[240:245, "normalized_open"] = current.loc[
            240:245, "normalized_close"
        ]
        current.loc[240:245, "ret_15m"] = 0.01
        current.loc[240:245, "ret_60m"] = 0.02
        current.loc[240:245, "normalized_momentum_60m"] = 2.0
        current.loc[240:245, "vwap"] = (
            current.loc[240:245, "normalized_close"] - 1.0
        )
        current.loc[240:245, "prior_15m_high"] = (
            current.loc[240:245, "normalized_close"] - 0.1
        )
        current.loc[240:245, "tradability_proxy_pass"] = True
        current["session_complete"] = True
    return qqq, soxx


def test_validate_lineage():
    mod.validate_lineage(
        valid_rth(),
        valid_ah(),
        valid_forward(),
    )


def test_validate_lineage_rejects():
    source = valid_ah()
    source["parameter_sweep_executed"] = True
    with pytest.raises(mod.StudyError):
        mod.validate_lineage(
            valid_rth(),
            source,
            valid_forward(),
        )


def test_study_period():
    assert mod.study_period(2020) == "2018-2022_DEVELOPMENT"
    assert mod.study_period(2024) == "2023-2024_VALIDATION"
    assert mod.study_period(2026) == (
        "2025-2026_YTD_CONFIRMATION"
    )


def test_symbol_month_path():
    path = (
        mod.Path("x")
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


def test_snap_split():
    factor, error = mod.snap_split_factor(10.0)
    assert factor == pytest.approx(10.0)
    assert error == pytest.approx(0.0)


def test_snap_rejects():
    assert mod.snap_split_factor(1.37) is None


def test_session_grid():
    current = grid()
    assert len(current) == 390
    assert bool(current["session_complete"].iloc[0])


def test_tradability():
    current = grid()
    assert bool(current.loc[240, "tradability_proxy_pass"])


def test_build_long_candidate():
    qqq, soxx = forced_long_grids()
    candidate, reasons = mod.build_candidate(
        "2026-01-05",
        qqq,
        soxx,
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert not reasons
    assert candidate is not None
    assert candidate["direction"] == "LONG"
    assert candidate["execution_symbol"] in {"TQQQ", "SOXL"}


def test_event_blocks_candidate():
    qqq, soxx = forced_long_grids()
    events = pd.DataFrame(
        {
            "timestamp_utc": [
                pd.Timestamp("2026-01-05 19:00:00+00:00")
            ]
        }
    )
    candidate, reasons = mod.build_candidate(
        "2026-01-05",
        qqq,
        soxx,
        {"QQQ": events, "SOXX": pd.DataFrame()},
        {"QQQ": pd.DataFrame(), "SOXX": pd.DataFrame()},
    )
    assert candidate is None
    assert any("SCALE_EVENT" in reason for reason in reasons)


def test_exit_minutes():
    assert mod.exit_minute("FIXED_30M", 250) == 280
    assert mod.exit_minute("FIXED_60M", 250) == 310
    assert mod.exit_minute("SESSION_1555", 250) == 385


def test_return_from_grid():
    current = grid()
    result = mod.return_from_grid(current, 250, 280)
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
        "RTH_LATE_DAY_CONTINUATION_"
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
    assert decision == (
        "RTH_LATE_DAY_CONTINUATION_CANDIDATE_"
        "REQUIRES_INDEPENDENT_REPLICATION"
    )
    assert supported == ["FIXED_60M"]


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.063R1_FAST3" in args.v22_063r1_summary
    assert "V22.063A_FAST3" in args.v22_063a_summary
    assert "V22.062PR_FAST3" in args.v22_062pr_summary


def test_policy_constants():
    assert mod.SIGNAL_START == 240
    assert mod.SIGNAL_END == 324
    assert mod.SESSION_EXIT_MINUTE == 385
    assert mod.FIXED_ACCOUNT_WEIGHT == 0.20
