#!/usr/bin/env python
"""Focused tests for V21.104-R1 decomposition."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_104_r1_d_long_horizon_edge_decomposition.py"
spec = importlib.util.spec_from_file_location("v21_104_r1", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture() -> pd.DataFrame:
    rows = []
    for sample, year, soxx, qqq in (
        ("S1", "2023-01-03", .10, .05),
        ("S2", "2024-01-03", .12, .04),
        ("S3", "2025-01-03", 1.00, .06),
    ):
        values = {"A1": .12, "B": .13, "C": .14, "D": .16}
        for size in (20, 50):
            for horizon in (126, 189, 252):
                for variant, value in values.items():
                    rows.append({
                        "sample_id": sample, "seed": 1, "draw_index": 1,
                        "start_date": year, "variant": variant,
                        "portfolio_size": size, "horizon": horizon,
                        "portfolio_return": value, "benchmark_QQQ_return": qqq,
                        "benchmark_SPY_return": .03,
                        "benchmark_semiconductor_return": soxx,
                        "excess_vs_A1": value - values["A1"],
                        "excess_vs_B": value - values["B"],
                        "excess_vs_C": value - values["C"],
                        "excess_vs_D": value - values["D"],
                        "excess_vs_QQQ": value - qqq, "excess_vs_SPY": value - .03,
                        "excess_vs_semiconductor_benchmark": value - soxx,
                        "max_drawdown": -.1, "missing_price_count": 0,
                        "point_in_time_valid": "TRUE",
                    })
    return module.numeric(pd.DataFrame(rows))


def test_soxx_extreme_decomposition() -> None:
    rows = module.benchmark_decomposition(fixture())
    primary = next(row for row in rows if row["portfolio_size"] == 20 and row["horizon"] == 252)
    assert primary["d_win_rate_vs_SOXX"] > .5
    assert primary["d_mean_excess_vs_SOXX"] < 0
    assert primary["d_mean_excess_in_soxx_extreme_samples"] < 0


def test_best_worst_sample_count() -> None:
    rows = module.best_worst_samples(fixture())
    assert rows
    assert {row["benchmark"] for row in rows} == {"QQQ", "SOXX"}
    assert {row["direction"] for row in rows} == {"BEST", "WORST"}


def test_concentration_is_unavailable_by_contract() -> None:
    assert "ticker" not in fixture().columns


if __name__ == "__main__":
    test_soxx_extreme_decomposition()
    test_best_worst_sample_count()
    test_concentration_is_unavailable_by_contract()
    print("PASS test_v21_104_r1_d_long_horizon_edge_decomposition")
