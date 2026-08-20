import importlib.util
from pathlib import Path

import pandas as pd


MODULE = Path(__file__).parents[2] / "scripts/run/fast3_r35b_frozen_oof_expected_payoff_economic_ordering_evaluation.py"
SPEC = importlib.util.spec_from_file_location("r35b", MODULE)
R35B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R35B)


def test_fixed_deciles_are_outcome_blind_and_tie_stable():
    frame = pd.DataFrame({"expected_payoff_raw": [1.0] * 20, "timestamp": pd.date_range("2025-01-01", periods=20, tz="UTC"), "decision_key": [f"k{i:02d}" for i in range(20)]})
    result = R35B.assign_fixed_deciles(frame)
    assert result.decile.tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10]
    assert R35B.safe_spearman(pd.Series([1, 2, 3]), pd.Series([1, 2, 3])) == 1.0
