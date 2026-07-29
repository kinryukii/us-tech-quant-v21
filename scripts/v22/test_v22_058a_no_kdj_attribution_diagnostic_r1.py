from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import v22_058a_no_kdj_attribution_diagnostic_r1 as mod


def sample_trades() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "variant": [mod.TARGET_VARIANT] * 8,
            "study_period": [
                mod.VALIDATION,
                mod.VALIDATION,
                mod.VALIDATION,
                mod.VALIDATION,
                mod.CONFIRMATION,
                mod.CONFIRMATION,
                mod.CONFIRMATION,
                mod.CONFIRMATION,
            ],
            "calendar_year": [
                2023, 2023, 2024, 2024,
                2025, 2025, 2026, 2026,
            ],
            "trade_date": [
                "2023-01-03",
                "2023-01-04",
                "2024-01-03",
                "2024-01-04",
                "2025-01-03",
                "2025-01-04",
                "2026-01-03",
                "2026-01-04",
            ],
            "direction": [
                "LONG", "LONG", "SHORT", "SHORT",
                "LONG", "LONG", "SHORT", "SHORT",
            ],
            "execution_symbol": [
                "SOXL", "TQQQ", "SOXS", "SQQQ",
                "SOXL", "TQQQ", "SOXS", "SQQQ",
            ],
            "exit_reason": [
                "HARD_STOP",
                "NO_PROGRESS_15M",
                "HARD_STOP",
                "FACTOR_INVALIDATION",
                "TRAILING_PROTECTION",
                "NO_PROGRESS_15M",
                "HARD_STOP",
                "FACTOR_INVALIDATION",
            ],
            "holding_minutes": [10, 15, 20, 25, 30, 15, 20, 25],
            "instrument_net_return": [
                0.01, 0.02, -0.03, -0.01,
                0.01, 0.02, -0.04, -0.02,
            ],
            "account_trade_return": [
                0.003, 0.006, -0.009, -0.003,
                0.003, 0.006, -0.012, -0.006,
            ],
            "mfe": [0.02] * 8,
            "mae": [-0.01] * 8,
        }
    )


def test_profit_factor():
    result = mod.profit_factor(
        pd.Series([0.02, 0.01, -0.01])
    )
    assert result == pytest.approx(3.0)


def test_profit_factor_infinite():
    result = mod.profit_factor(pd.Series([0.01, 0.02]))
    assert math.isinf(result)


def test_group_summary():
    result = mod.summarize_group(sample_trades().head(2))
    assert result["trade_count"] == 2
    assert result["mean_net_return"] == pytest.approx(0.015)
    assert result["positive_rate"] == pytest.approx(1.0)


def test_direction_symbol_summary():
    result = mod.direction_symbol_summary(sample_trades())
    assert len(result) == 8
    assert set(result["direction"]) == {"LONG", "SHORT"}


def test_exit_summary():
    result = mod.exit_summary(sample_trades())
    assert "exit_reason" in result.columns
    assert result["trade_count"].sum() == 8


def test_tail_summary():
    result = mod.tail_summary(sample_trades())
    assert set(result["study_period"]) == {
        mod.VALIDATION,
        mod.CONFIRMATION,
    }
    assert result["worst_5_loss_share"].between(0, 1).all()


def test_worst_trades_order():
    result = mod.worst_trades(sample_trades(), count=3)
    assert result.iloc[0]["instrument_net_return"] == pytest.approx(-0.04)
    assert len(result) == 3


def test_direction_period_summary():
    result = mod.direction_period_summary(sample_trades())
    assert len(result) == 4


def test_choose_recommendation_freezes_short():
    direction = mod.direction_period_summary(sample_trades())
    exits = mod.exit_summary(sample_trades())
    tail = mod.tail_summary(sample_trades())
    result = mod.choose_recommendation(direction, exits, tail)
    assert result["short_freeze_recommended"] is True
    assert result["long_freeze_recommended"] is False
    assert result["next_stage"] == (
        "V22.059_FAST3_LONG_ONLY_NO_KDJ_REPLICATION_R1"
    )


def test_format_bps():
    assert mod.format_value("mean_net_return", 0.001) == "10.00"


def test_format_percent():
    assert mod.format_value("positive_rate", 0.5) == "50.00"


def test_default_paths():
    args = mod.parse_args(["--execute"])
    assert "V22.058_FAST3" in args.root
    assert "V22.058A_NO_KDJ" in args.output_dir
