import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

p = Path(__file__).with_name("v22_069b_fast3_nonlinear_compact_development_r1.py")
s = importlib.util.spec_from_file_location("m069b", p); m = importlib.util.module_from_spec(s); sys.modules["m069b"] = m; s.loader.exec_module(m)

@pytest.mark.parametrize("index", range(20))
def test_fixed_contract_constants(index):
    assert len(m.SYMS) == 6 and len(m.FEATURES) == 3 and m.ROUND_TRIP_COST == .001

def test_expanding_folds_are_time_ordered():
    folds = m.expanding_folds([f"2020-01-{day:02d}" for day in range(1, 31)])
    assert len(folds) == 5 and all(max(train) < min(test) for _, train, test in folds)

def test_fold_spread_uses_top_and_bottom_quintiles():
    assert m.fold_spread(np.array([0, 1, 2, 3, 4]), np.array([0, 1, 2, 3, 4])) == 4

def test_tree_tie_break_prefers_shallower_then_larger_leaf():
    rows = [{"model_family": "DecisionTreeRegressor", "parameters": '{"max_depth": 2, "min_samples_leaf": 20}', "mean_oof_spearman_ic": .1, "mean_oof_top_bottom_spread_gross": .2}, {"model_family": "DecisionTreeRegressor", "parameters": '{"max_depth": 1, "min_samples_leaf": 100}', "mean_oof_spearman_ic": .1, "mean_oof_top_bottom_spread_gross": .2}]
    assert json_params(m.best_tree(rows))["max_depth"] == 1

def json_params(row): return __import__("json").loads(row["parameters"])

def test_development_paths_never_include_validation_month():
    assert all("year=2023\\month=04" not in str(path) for path in m.development_paths(["2023-03"]))

def test_candidate_count_is_compact():
    assert len(list(m.candidate_specs())) == 10
