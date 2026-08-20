from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r33fr_identifiable_window_loss_magnitude_sufficiency.py"
spec = importlib.util.spec_from_file_location("r33fr", RUNNER)
r33fr = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r33fr)


def test_identifiability_repair_is_only_preregistered_design_change() -> None:
    contract = r33fr.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["PARENT_STUDY"] == "FAST3_R33F"
    assert contract["PARENT_STATUS"] == "STOPPED_DATA_OR_LINEAGE_INTEGRITY"
    assert contract["PARENT_R33F_PREREGISTRATION_SHA256"] == r33fr.PARENT_PREREGISTRATION_SHA256
    assert contract["PARENT_SCIENTIFIC_RESULTS_OBSERVED"] is False
    assert contract["PARENT_MAPPING_METRICS_OBSERVED"] is False
    assert contract["REPAIR_TYPE"] == "IDENTIFIABILITY_WINDOW_RESTRICTION"
    assert contract["RESEARCH_DESIGN_CHANGE_REASON"] == "IDENTIFIABILITY_ONLY"


def test_2021_excluded_and_exact_four_frozen_outer_folds() -> None:
    contract = r33fr.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["OOF_2021_INCLUDED"] is False
    assert contract["EXCLUDED_OUTER_FOLD"] == "OOF_2021"
    assert tuple(contract["EVALUATION_OUTER_FOLDS"]) == ("OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025")
    assert contract["OUTER_FOLD_COUNT"] == 4
    assert contract["SOURCE_FOLD_MAP"]["OOF_2025"] == "OOF_2025_JAN"
    assert contract["FOLD_STABILITY_GATE_CHANGE_FROM_R33F"] == "4_OF_5_TO_4_OF_4"
    assert contract["SUFFICIENCY_GATES"]["C_POSITIVE_FOLD_COUNT"] == "4_of_4"


def test_actual_frozen_fold_contract_has_historical_only_training_rows() -> None:
    frame, r33d_contract, _, _ = r33fr.validate_parent_and_lineage()
    audits = r33fr.recover_outer_fold_contract(frame, r33d_contract)
    assert [row["outer_fold"] for row in audits] == list(r33fr.EVALUATION_OUTER_FOLDS)
    assert all(row["strict_temporal_assertion_pass"] for row in audits)
    assert all(row["same_outer_fold_training_row_count"] == 0 for row in audits)
    assert all(row["training_max_timestamp"] < row["evaluation_min_timestamp"] for row in audits)
    assert audits[0]["training_min_timestamp"] == pd.Timestamp("2021-01-01T00:00:00Z")


def test_only_three_heads_and_exact_three_mapping_contracts() -> None:
    contract = r33fr.preregistration("2026-08-10T00:00:00+00:00")
    assert r33fr.PREDICTIVE_INPUTS == ("pred_t1", "pred_t5", "pred_t6")
    assert contract["INPUT_FEATURES"] == list(r33fr.PREDICTIVE_INPUTS)
    assert contract["NEW_RAW_FEATURE_COUNT"] == 0
    assert contract["LOSS_MAPPING_CANDIDATE_COUNT"] == 3
    assert contract["CANDIDATE_MAPPINGS"] == list(r33fr.CANDIDATE_MAPPINGS)
    assert contract["M1"]["ALPHA"] == 1.0
    assert contract["M2"]["GRID"] == "3x3"
    assert contract["M3"]["GRID"] == "2x2x2"
    assert contract["CALIBRATION_QUANTILES"] == 5


def test_mapping_boundaries_and_predictions_are_training_fold_only() -> None:
    training = pd.DataFrame({
        "pred_t1": np.arange(12, dtype=float),
        "pred_t5": np.arange(12, dtype=float) * 2,
        "pred_t6": np.arange(12, dtype=float) * 3,
        "loss_magnitude": np.linspace(0.01, 0.12, 12),
    })
    evaluation_a = pd.DataFrame({
        "pred_t1": [2.5, 8.5], "pred_t5": [5.0, 17.0], "pred_t6": [7.5, 25.5],
        "loss_magnitude": [0.001, 999.0],
    })
    evaluation_b = evaluation_a.copy()
    evaluation_b["loss_magnitude"] = [111.0, 222.0]
    edges = r33fr.training_quantile_edges(training.pred_t5, 3)
    assert np.array_equal(edges, r33fr.training_quantile_edges(training.pred_t5, 3))
    assert np.allclose(
        r33fr.table_mapping(training, evaluation_a, ("pred_t5", "pred_t6"), (3, 3)),
        r33fr.table_mapping(training, evaluation_b, ("pred_t5", "pred_t6"), (3, 3)),
    )
    assert np.allclose(r33fr.ridge_mapping(training, evaluation_a), r33fr.ridge_mapping(training, evaluation_b))


def test_loss_definition_and_date_balanced_aggregation_are_deterministic() -> None:
    frame = pd.DataFrame({
        "candidate_id": ["a", "b", "c", "d", "e"],
        "decision_timestamp_utc": pd.to_datetime([
            "2022-01-01T00:00:00Z", "2022-01-01T00:05:00Z", "2022-01-02T00:00:00Z",
            "2022-01-02T00:05:00Z", "2022-01-03T00:00:00Z",
        ]),
        "trading_date": ["2021-12-31", "2021-12-31", "2022-01-01", "2022-01-01", "2022-01-02"],
        "raw_net20": [-0.01, -0.02, -0.03, -0.04, -0.05],
        "loss_magnitude": [0.01, 0.02, 0.03, 0.04, 0.05],
        "prediction": [0.01, 0.02, 0.03, 0.04, 0.05],
    })
    assert np.array_equal(frame.loss_magnitude, frame.raw_net20.abs())
    first = r33fr.date_balanced_spearman(frame, "prediction")
    second = r33fr.date_balanced_spearman(frame.sample(frac=1, random_state=7), "prediction")
    assert first == second == 1.0


def test_gate_classification_and_complexity_priority_are_deterministic() -> None:
    passed = {name: {"gate_status": "PASS", "stable_ranking_A_to_D": True} for name in r33fr.CANDIDATE_MAPPINGS}
    assert r33fr.select_first_pass(passed) == "M1_RIDGE"
    passed["M1_RIDGE"]["gate_status"] = "FAIL"
    assert r33fr.select_first_pass(passed) == "M2_T5_T6_3X3"
    passed["M2_T5_T6_3X3"]["gate_status"] = "FAIL"
    assert r33fr.select_first_pass(passed) == "M3_T1_T5_T6_2X2X2"
    classification, _, _, _ = r33fr.classify(passed)
    assert classification.startswith("A_")
    failed = {name: {"gate_status": "FAIL", "stable_ranking_A_to_D": False} for name in r33fr.CANDIDATE_MAPPINGS}
    assert r33fr.classify(failed)[0].startswith("C_")
    failed["M2_T5_T6_3X3"]["stable_ranking_A_to_D"] = True
    assert r33fr.classify(failed)[0].startswith("B_")
    assert r33fr.ALLOWED_SCIENTIFIC_CLASSIFICATIONS == {r33fr.classify(passed)[0], r33fr.classify(failed)[0], r33fr.classify({name: {"gate_status": "FAIL", "stable_ranking_A_to_D": False} for name in r33fr.CANDIDATE_MAPPINGS})[0]}


def test_preregistration_precedes_fit_and_storage_timestamp_final_t7_guards() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    main_source = inspect.getsource(r33fr.main)
    assert main_source.index("write_json(prereg_path, prereg)") < main_source.index("execute_mappings(frame, audits)")
    assert r33fr.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    contract = r33fr.preregistration("2026-08-10T00:00:00+00:00")
    assert contract["RUN_ID_TIMESTAMP_SEMANTICS"] == "REAL_UTC_WALL_CLOCK"
    assert contract["T7_MODEL_CREATED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_USED"] is False
    assert contract["FINAL_CONFIRMATION_DATA_LOADED"] is False
    assert contract["FINAL_HOLDOUT_INSPECTED"] is False
    assert contract["FINAL_HOLDOUT_ROW_COUNT"] == 0
    assert all(value == 0 for value in contract["SEARCH_AND_SIMULATION_COUNTS"].values())
    assert "HistGradientBoosting" not in source and "XGBoost" not in source and "EV score" not in source
