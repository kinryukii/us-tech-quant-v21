#!/usr/bin/env python
"""Focused contract tests for V21.103."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_103_abcd_random_long_horizon_backtest_spec.py"
spec = importlib.util.spec_from_file_location("v21_103", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_sampling_is_reproducible_and_eligible() -> None:
    eligible = [f"2025-01-{day:02d}" for day in range(1, 21)]
    first = module.sample_dates(eligible, (7, 8), 10)
    second = module.sample_dates(eligible, (7, 8), 10)
    assert first == second
    assert len(first) == 20
    assert {row["start_date"] for row in first}.issubset(set(eligible))


def test_rank_variants_uses_expected_weights_and_pit_date() -> None:
    index = ["2025-01-02"]
    columns = ["AAA", "BBB", "CCC"]
    features = {
        "base": pd.DataFrame([[90.0, 60.0, 30.0]], index=index, columns=columns),
        "momentum": pd.DataFrame([[10.0, 70.0, 100.0]], index=index, columns=columns),
        "dynamic_weight": pd.Series([0.15], index=index),
    }
    ranked = module.rank_variants(features, index[0])
    assert ranked["A1"].iloc[0]["ticker"] == "AAA"
    assert ranked["D"].iloc[0]["ticker"] == "BBB"
    assert np.isclose(ranked["D"].iloc[0]["momentum_weight"], 0.40)
    assert all(set(frame["max_input_date"].unique()) == {index[0]} for frame in ranked.values())


def test_missing_price_policy_reweights_remaining_positions() -> None:
    panel = pd.DataFrame(
        {
            "AAA": [100.0, 110.0, 120.0],
            "BBB": [100.0, np.nan, 80.0],
        },
        index=["2025-01-01", "2025-01-02", "2025-01-03"],
    )
    path, missing = module.equal_weight_path(panel, ["AAA", "BBB"], 0, 2)
    assert missing == 1
    assert np.isclose(path[1], 1.10)
    assert np.isclose(path[2], 1.00)


def test_turnover_and_transaction_cost_convention() -> None:
    assert np.isclose(module.turnover(set(), {"AAA", "BBB"}), 1.0)
    assert np.isclose(module.turnover({"AAA", "BBB"}, {"BBB", "CCC"}), 0.5)
    assert np.isclose(0.5 * 10 / 10000.0, 0.0005)


def test_decision_logic_blocks_leakage() -> None:
    frame = pd.DataFrame([{
        "variant": "D", "horizon": 252, "transaction_cost_bps": 0,
        "mode": "RANDOM_252D_HOLD", "mean_excess_vs_A1": .01,
        "mean_excess_vs_QQQ": .01, "win_rate_vs_A1": .6,
        "win_rate_vs_QQQ": .6, "p5_return": -.2, "turnover_mean": 0,
    }])
    status, _ = module.decide(frame, leakage_count=1, core_data_ok=True)
    assert status == module.FAIL_BLOCKER


def test_output_directory_is_immutable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "run"
        module.ensure_immutable_output(output)
        (output / "marker.txt").write_text("x", encoding="utf-8")
        try:
            module.ensure_immutable_output(output)
        except RuntimeError:
            pass
        else:
            raise AssertionError("non-empty output directory must be rejected")


if __name__ == "__main__":
    test_sampling_is_reproducible_and_eligible()
    test_rank_variants_uses_expected_weights_and_pit_date()
    test_missing_price_policy_reweights_remaining_positions()
    test_turnover_and_transaction_cost_convention()
    test_decision_logic_blocks_leakage()
    test_output_directory_is_immutable()
    print("PASS test_v21_103_abcd_random_long_horizon_backtest_spec")
