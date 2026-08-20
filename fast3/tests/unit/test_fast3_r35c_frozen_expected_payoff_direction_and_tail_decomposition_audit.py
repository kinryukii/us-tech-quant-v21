import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


PATH = Path(__file__).parents[2] / "scripts/run/fast3_r35c_frozen_expected_payoff_direction_and_tail_decomposition_audit.py"
SPEC = importlib.util.spec_from_file_location("r35c", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_fixed_deciles_are_score_only_and_deterministic():
    frame = pd.DataFrame({"expected_payoff_raw": [1.0] * 10, "timestamp": pd.date_range("2024-01-01", periods=10, tz="UTC"), "decision_key": list("abcdefghij")})
    assert MODULE.fixed_deciles(frame).within_decile.tolist() == list(range(1, 11))


def test_direction_percentile_rank_uses_average_ties():
    frame = pd.DataFrame({
        "direction": ["UP", "UP", "UP", "DOWN", "DOWN"],
        "expected_payoff_raw": [1.0, 1.0, 3.0, 2.0, 4.0],
    })
    actual = MODULE.direction_percentile_rank(frame).to_numpy()
    np.testing.assert_allclose(actual, [.5, .5, 1.0, .5, 1.0])


def test_tail_stats_uses_exact_worst_five_percent_count():
    values = pd.Series([-2.0] + [-1.0] * 5 + [0.0] * 94)
    stats = MODULE.tail_stats(values)
    assert stats["worst5_row_count"] == 5
    assert stats["worst5_mean"] == -1.2
