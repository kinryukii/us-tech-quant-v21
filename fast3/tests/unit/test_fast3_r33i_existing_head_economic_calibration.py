from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33i_existing_head_economic_calibration.py"
spec = importlib.util.spec_from_file_location("r33i", RUNNER)
r33i = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33i)


@functools.lru_cache(maxsize=1)
def frozen_inputs():
    return r33i.validate_and_load_lineage()


def test_sources_are_exactly_t1_t6_t5_without_reselection() -> None:
    assert (r33i.P_SOURCE, r33i.G_SOURCE, r33i.L_SOURCE) == ("T1", "T6", "T5")
    contract = r33i.preregistration("2026-08-10T00:00:00+00:00", {"P": list(r33i.EVALUATION_FOLDS), "G": list(r33i.EVALUATION_FOLDS), "L": list(r33i.EVALUATION_FOLDS)})
    assert contract["P_SOURCE"] == "T1" and contract["G_SOURCE"] == "T6" and contract["L_SOURCE"] == "T5"
    assert contract["PROBABILITY_SOURCE_SEARCH_COUNT"] == 0


def test_only_fixed_empirical_deciles_and_five_diagnostic_bins() -> None:
    assert r33i.CALIBRATION_METHOD == "FIXED_EMPIRICAL_QUANTILE_CALIBRATION"
    assert r33i.CALIBRATION_BUCKET_COUNT == 10
    assert r33i.DIAGNOSTIC_BIN_COUNT == 5
    contract = r33i.preregistration("2026-08-10T00:00:00+00:00", {"P": [], "G": [], "L": []})
    assert contract["CALIBRATION_METHOD_COUNT"] == 1
    assert contract["CALIBRATION_METHOD_SEARCH_COUNT"] == 0
    assert contract["CALIBRATION_BUCKET_SEARCH_COUNT"] == 0
    assert contract["G_L_BUCKET_ESTIMATOR"] == "MEAN_FIXED_NO_MEDIAN_SEARCH"
    assert contract["P_BUCKET_TARGET"] == "historical canonical winner rate"


def test_training_only_edges_outcomes_and_deterministic_fallback() -> None:
    training = pd.DataFrame({"score": np.arange(20, dtype=float), "target": np.arange(20, dtype=float) / 10})
    evaluation_a = pd.DataFrame({"score": [-100.0, 100.0], "target": [999.0, 999.0]})
    evaluation_b = evaluation_a.copy()
    evaluation_b["target"] = [-999.0, -999.0]
    pred_a, naive_a, info_a = r33i.build_apply_mapping(training, evaluation_a, "score", "target")
    pred_b, naive_b, info_b = r33i.build_apply_mapping(training, evaluation_b, "score", "target")
    assert np.array_equal(pred_a, pred_b) and np.array_equal(naive_a, naive_b)
    assert info_a == info_b
    degenerate = pd.DataFrame({"score": np.zeros(10), "target": np.arange(10, dtype=float)})
    outside = pd.DataFrame({"score": [-1.0], "target": [123.0]})
    fallback_prediction, _, fallback_info = r33i.build_apply_mapping(degenerate, outside, "score", "target")
    assert fallback_prediction[0] == degenerate.target.mean()
    assert fallback_info["evaluation_empty_bucket_fallback_count"] == 1


def test_expanding_window_excludes_2021_and_has_no_future_or_same_fold_rows() -> None:
    frame, contract, _ = frozen_inputs()
    audits = r33i.recover_fold_audits(frame, contract)
    assert r33i.EXCLUDED_FOLD == "OOF_2021"
    assert [row["outer_fold"] for row in audits] == ["OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025"]
    assert all(row["strict_temporal_separation"] for row in audits)
    assert all(row["historical_max_timestamp"] < row["evaluation_min_timestamp"] for row in audits)
    identifiable = r33i.identifiable_folds(frame, audits)
    assert all(folds == list(r33i.EVALUATION_FOLDS) for folds in identifiable.values())


def test_zero_head_fit_prediction_and_no_new_architecture() -> None:
    contract = r33i.preregistration("2026-08-10T00:00:00+00:00", {"P": [], "G": [], "L": []})
    for key in (
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FIT_COUNT",
        "MODEL_PREDICT_CALL_COUNT", "T1_REFIT_COUNT", "T5_REFIT_COUNT", "T6_REFIT_COUNT",
        "T1_NEW_PREDICT_COUNT", "T5_NEW_PREDICT_COUNT", "T6_NEW_PREDICT_COUNT",
    ):
        assert contract[key] == 0
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    model_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"fit", "predict", "predict_proba"}
    ]
    assert not model_calls


def test_no_method_bucket_feature_ev_threshold_trading_or_final_search() -> None:
    contract = r33i.preregistration("2026-08-10T00:00:00+00:00", {"P": [], "G": [], "L": []})
    for key in (
        "CALIBRATION_METHOD_SEARCH_COUNT", "CALIBRATION_BUCKET_SEARCH_COUNT",
        "HYPERPARAMETER_SEARCH_COUNT", "FEATURE_SEARCH_COUNT", "INTERACTION_SEARCH_COUNT",
        "EV_SCORE_CONSTRUCTION_COUNT", "EV_COMBINATION_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT",
        "THRESHOLD_SEARCH_COUNT", "TRADING_SIMULATION_COUNT", "EXECUTION_SIMULATION_COUNT",
        "POSITION_SIZING_SEARCH_COUNT",
    ):
        assert contract[key] == 0
    assert contract["EV_PROHIBITED"] is True and contract["TRADING_PROHIBITED"] is True
    assert contract["FINAL_PROHIBITED"] is True
    assert contract["FINAL_CONFIRMATION_DATA_USED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_LOADED"] is False
    assert contract["FINAL_HOLDOUT_INSPECTED"] is False
    assert contract["HEAD_EXPANSION_LIMIT_AFTER_R33G"] is True
    assert contract["FURTHER_HEAD_EXPANSION_ALLOWED"] is False


def test_role_reconciliation_is_required_and_classification_enum_is_closed() -> None:
    frame, _, r33d = frozen_inputs()
    r33i.reconcile_roles(frame, r33d)
    assert r33i.classify("CALIBRATED", "CALIBRATED", "CALIBRATED")[0] == "A_ALL_EXISTING_HEAD_ECONOMIC_COMPONENTS_CALIBRATED"
    assert r33i.classify("CALIBRATED", "CALIBRATED", "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED")[0] == "B_PROBABILITY_AND_GAIN_CALIBRATED_LOSS_LEVEL_UNSTABLE"
    assert r33i.classify("CALIBRATED", "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED", "CALIBRATED")[0] == "C_ECONOMIC_LEVEL_CALIBRATION_NOT_STABLE"
    assert len(r33i.ALLOWED_CLASSIFICATIONS) == 3
    assert len(r33i.ALLOWED_COMPONENT_STATUSES) == 4


def test_preregistration_precedes_role_metrics_and_external_storage() -> None:
    source = inspect.getsource(r33i.main)
    prereg_index = source.index("write_json(prereg_path, prereg)")
    assert prereg_index < source.index("reconcile_roles(frame, r33d_summary)")
    assert prereg_index < source.index("execute_component(frame, audits, component)")
    assert prereg_index < source.index("probability_metrics(component_oof")
    assert r33i.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    assert not any(RUNNER.parent.glob("*r33i*helper*.py"))
