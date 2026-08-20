from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33f_existing_head_loss_magnitude_sufficiency.py"
spec = importlib.util.spec_from_file_location("r33f", RUNNER)
r33f = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33f)


def test_only_three_frozen_head_inputs_and_zero_raw_features() -> None:
    assert r33f.PREDICTIVE_INPUTS == ("pred_t1", "pred_t5", "pred_t6")
    contract = r33f.preregistration()
    assert contract["INPUT_FEATURES"] == list(r33f.PREDICTIVE_INPUTS)
    assert contract["NEW_RAW_FEATURE_COUNT"] == 0


def test_exact_three_candidates_and_frozen_parameters() -> None:
    assert len(r33f.CANDIDATE_MAPPINGS) == 3
    assert r33f.RIDGE_ALPHA == 1.0
    assert r33f.M2_GRID == (3, 3)
    assert r33f.M3_GRID == (2, 2, 2)
    assert r33f.CALIBRATION_QUANTILES == 5
    contract = r33f.preregistration()
    assert contract["LOSS_MAPPING_CANDIDATE_COUNT"] == 3
    assert contract["M1"]["ALPHA"] == 1.0
    assert contract["M2"]["GRID"] == "3x3"
    assert contract["M3"]["GRID"] == "2x2x2"


def test_fold_safe_boundaries_use_training_values_only() -> None:
    training = pd.Series(np.arange(12, dtype=float))
    validation_a = pd.Series([-100.0, 100.0])
    validation_b = pd.Series([-1e9, 1e9])
    edges = r33f.training_quantile_edges(training, 3)
    assert np.array_equal(edges, r33f.training_quantile_edges(training, 3))
    assert np.array_equal(r33f.apply_training_edges(validation_a, edges), r33f.apply_training_edges(validation_b, edges))


def test_fold_safe_baselines_use_only_passed_training_losses() -> None:
    mean, median = r33f.fold_safe_baselines(pd.Series([1.0, 2.0, 100.0]))
    assert mean == 103 / 3 and median == 2.0


def test_complexity_priority_is_deterministic() -> None:
    assert r33f.select_first_pass({"M1_RIDGE": True, "M2_T5_T6_3X3": True, "M3_T1_T5_T6_2X2X2": True}) == "M1_RIDGE"
    assert r33f.select_first_pass({"M1_RIDGE": False, "M2_T5_T6_3X3": True, "M3_T1_T5_T6_2X2X2": True}) == "M2_T5_T6_3X3"
    assert r33f.select_first_pass({"M1_RIDGE": False, "M2_T5_T6_3X3": False, "M3_T1_T5_T6_2X2X2": True}) == "M3_T1_T5_T6_2X2X2"
    assert r33f.select_first_pass({}) is None


def test_lineage_duplicate_guard_and_first_fold_coverage_blocker() -> None:
    frame, r33d_contract, r33b_contract = r33f.validate_lineage()
    assert not frame.candidate_id.duplicated().any()
    coverage = r33f.assess_mapping_training_coverage(frame, r33d_contract, r33b_contract)
    assert len(coverage) == 5
    assert coverage[0]["fold"] == "OOF_2021"
    assert coverage[0]["required_original_training_loser_count"] > 0
    assert coverage[0]["available_historical_three_head_loser_prediction_count"] == 0
    assert coverage[0]["coverage_sufficient"] is False


def test_preregistration_written_before_coverage_check_and_external_paths() -> None:
    source = inspect.getsource(r33f.main)
    assert source.index("write_json(prereg_path, prereg)") < source.index("assess_mapping_training_coverage")
    assert r33f.FROZEN_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))
    assert r33f.SCRATCH_ROOT.is_relative_to(Path(r"D:\us-tech-quant-results"))


def test_no_final_search_ev_trading_or_model_execution() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    model_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fit", "predict", "predict_proba"}
    ]
    assert not model_calls
    contract = r33f.preregistration()
    for key in (
        "HYPERPARAMETER_SEARCH_COUNT", "FEATURE_SEARCH_COUNT", "INTERACTION_SEARCH_COUNT",
        "BUCKET_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT", "THRESHOLD_SEARCH_COUNT",
        "EV_COMBINATION_SEARCH_COUNT", "TRADING_SIMULATION_COUNT", "EXECUTION_SIMULATION_COUNT",
        "POSITION_SIZING_SEARCH_COUNT",
    ):
        assert contract[key] == 0
    assert contract["FINAL_CONFIRMATION_DATA_USED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_LOADED"] is False
    assert contract["FINAL_HOLDOUT_INSPECTED"] is False
    assert r33f.ALLOWED_SCIENTIFIC_CLASSIFICATIONS == {
        "A_EXISTING_THREE_HEADS_SUFFICIENT_FOR_LOSS_MAGNITUDE_COMPONENT",
        "B_EXISTING_HEADS_RANK_LOSS_BUT_LEVEL_CALIBRATION_INSUFFICIENT",
        "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE",
    }
    assert not any(RUNNER.parent.glob("*r33f*helper*.py"))
