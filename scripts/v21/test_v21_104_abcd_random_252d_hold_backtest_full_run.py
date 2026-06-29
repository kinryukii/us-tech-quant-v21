#!/usr/bin/env python
"""Focused tests for V21.104 summaries and decisions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_104_abcd_random_252d_hold_backtest_full_run.py"
spec = importlib.util.spec_from_file_location("v21_104", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def sample_rows() -> list[dict[str, object]]:
    rows = []
    returns = {
        "A1": [0.10, 0.12, -0.05, 0.08],
        "B": [0.11, 0.13, -0.04, 0.09],
        "C": [0.12, 0.14, -0.03, 0.10],
        "D": [0.15, 0.16, -0.02, 0.12],
    }
    for index in range(4):
        for variant, values in returns.items():
            value = values[index]
            rows.append({
                "sample_id": f"S{index}", "seed": 1, "draw_index": index,
                "start_date": "2024-01-02", "variant": variant,
                "portfolio_size": 20, "horizon": 252,
                "portfolio_return": value, "benchmark_QQQ_return": .05,
                "benchmark_SPY_return": .04,
                "benchmark_semiconductor_return": .06,
                "excess_vs_A1": value - returns["A1"][index],
                "excess_vs_B": value - returns["B"][index],
                "excess_vs_C": value - returns["C"][index],
                "excess_vs_D": value - returns["D"][index],
                "excess_vs_QQQ": value - .05, "excess_vs_SPY": value - .04,
                "excess_vs_semiconductor_benchmark": value - .06,
                "missing_price_count": 0, "point_in_time_valid": "TRUE",
                "survivorship_bias_warning": "TRUE",
            })
    return rows


def test_summary_has_required_metrics() -> None:
    result = module.summaries(sample_rows())
    assert len(result) == 4
    d = next(row for row in result if row["variant"] == "D")
    assert d["sample_count"] == 4
    assert d["win_rate_vs_A1"] == 1.0
    assert "p5_excess_vs_QQQ" in d
    assert d["pit_factor_approximation_warning_count"] == 4


def test_pairwise_contract() -> None:
    result = module.pairwise_comparisons(sample_rows())
    d_a1 = next(row for row in result if row["left"] == "D" and row["right"] == "A1")
    assert d_a1["paired_sample_count"] == 4
    assert d_a1["left_win_rate"] == 1.0
    assert any(row["right"] == "SOXX" for row in result)


def test_decision_blocks_leakage() -> None:
    summary = pd.DataFrame(module.summaries(sample_rows()))
    status, _, _ = module.decision(summary, leakage_failures=1, core_ok=True)
    assert status == module.FAIL_BLOCKER


def test_decision_can_confirm_edge() -> None:
    summary = pd.DataFrame(module.summaries(sample_rows()))
    status, _, facts = module.decision(summary, leakage_failures=0, core_ok=True)
    assert status == module.PASS
    assert facts["d_top20_252d_win_rate_vs_A1"] > .55


if __name__ == "__main__":
    test_summary_has_required_metrics()
    test_pairwise_contract()
    test_decision_blocks_leakage()
    test_decision_can_confirm_edge()
    print("PASS test_v21_104_abcd_random_252d_hold_backtest_full_run")
