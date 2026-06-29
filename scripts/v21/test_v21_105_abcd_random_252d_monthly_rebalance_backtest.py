#!/usr/bin/env python
"""Focused tests for V21.105 summary and decision contracts."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_105_abcd_random_252d_monthly_rebalance_backtest.py"
spec = importlib.util.spec_from_file_location("v21_105", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def rows() -> pd.DataFrame:
    output = []
    values = {"A1": .10, "B": .11, "C": .12, "D": .16}
    for sample in range(20):
        for variant, value in values.items():
            row = {
                "sample_id": f"S{sample}", "variant": variant, "portfolio_size": 20,
                "transaction_cost_bps": 10, "portfolio_return": value,
                "gross_portfolio_return": value + .01, "transaction_cost_drag": .01,
                "benchmark_QQQ_return": .05, "benchmark_SPY_return": .04,
                "benchmark_SOXX_return": .08, "max_drawdown": -.10,
                "turnover": 3.0, "annualized_turnover": 3.0,
                "missing_price_count": 0, "point_in_time_valid": "TRUE",
                "survivorship_bias_warning": "TRUE", "pit_factor_approximation_warning": "TRUE",
            }
            for name, other in values.items():
                row[f"excess_vs_{name}"] = value - other
            row["excess_vs_QQQ"] = value - .05
            row["excess_vs_SPY"] = value - .04
            row["excess_vs_SOXX"] = value - .08
            output.append(row)
    return pd.DataFrame(output)


def test_summary_contract() -> None:
    result = pd.DataFrame(module.summaries(rows()))
    d = result[result["variant"].eq("D")].iloc[0]
    assert d["sample_count"] == 20
    assert d["win_rate_vs_A1"] == 1.0
    assert math.isclose(d["transaction_cost_drag"], .01)
    assert set(module.SUMMARY_FIELDS).issubset(result.columns)


def test_pairwise_includes_all_required_pairs() -> None:
    result = pd.DataFrame(module.pairwise(rows()))
    pairs = set(zip(result["left"], result["right"]))
    assert set(module.PAIR_LIST).issubset(pairs)


def test_leakage_blocks_decision() -> None:
    summary = pd.DataFrame(module.summaries(rows()))
    hold = pd.DataFrame([{
        "variant": "D", "portfolio_size": 20, "transaction_cost_bps": 10,
        "mean_return_change": 0.0, "median_return_change": 0.0, "p5_return_change": 0.0,
    }])
    status, _, _ = module.classify(summary, hold, 1, False, False)
    assert status == module.FAIL_BLOCKER


if __name__ == "__main__":
    test_summary_contract()
    test_pairwise_includes_all_required_pairs()
    test_leakage_blocks_decision()
    print("PASS test_v21_105_abcd_random_252d_monthly_rebalance_backtest")
