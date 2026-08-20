from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r43b_current_information_set_economic_baseline_r1.py"
SPEC = importlib.util.spec_from_file_location("r43b", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_preregistration_freezes_features_models_folds_and_fit_budget():
    contract = R.preregistration("fixed", {})
    assert contract["BASELINE_FEATURE_COUNT"] == 14
    assert tuple(contract["BASELINE_FEATURES"]) == R.FEATURES
    assert contract["OOF_FOLD_COUNT"] == 5
    assert contract["MODEL_FIT_BUDGET"] == 20
    assert contract["PRIMARY_REGRESSION_FIT_BUDGET"] == 10
    assert contract["SECONDARY_CLASSIFICATION_FIT_BUDGET"] == 10
    assert contract["PARAMETER_SEARCH_ALLOWED"] is False
    assert contract["FULL_SAMPLE_REFIT_ALLOWED"] is False


def test_hgb_config_is_single_fixed_family_with_minimal_regressor_mapping():
    reg = R.model_config("regressor"); cls = R.model_config("classifier")
    for key in R.HGB_STRUCTURE:
        assert reg[key] == cls[key] == R.HGB_STRUCTURE[key]
    assert reg["loss"] == "squared_error" and cls["loss"] == "log_loss"
    assert sum(reg["categorical_features"]) == 2
    assert R.CATEGORICAL_FEATURES == ("symbol_code", "session_code")


def test_stable_quintiles_and_ordering_rules_are_exact():
    frame = pd.DataFrame({
        "head": ["UP"] * 10, "pred": [1.0] * 10,
        "decision_timestamp_utc": pd.date_range("2020-01-01", periods=10, tz="UTC"),
        "candidate_id": [str(i) for i in range(10)],
    })
    buckets = R.stable_quintiles(frame, "pred")
    assert buckets.value_counts().to_dict() == {q: 2 for q in R.QUINTILES}
    assert R.ordering([1, 2, 3, 4, 5]) == "MONOTONIC_POSITIVE"
    assert R.ordering([1, 2, 3, 2, 5]) == "MOSTLY_POSITIVE"
    assert R.ordering([5, 4, 3, 2, 1]) == "MONOTONIC_NEGATIVE"
    assert R.ordering([1, 3, 2, 4, 2]) == "NON_MONOTONIC"


def test_classification_primary_gate_cannot_be_replaced_by_secondary():
    primary = pd.DataFrame([
        {"direction": "UP", "spearman": .06, "q5_minus_q1_realized_y_econ_mean": .001,
         "primary_ordering": "MOSTLY_POSITIVE"},
        {"direction": "DOWN", "spearman": -.1, "q5_minus_q1_realized_y_econ_mean": -.001,
         "primary_ordering": "NON_MONOTONIC"},
    ])
    quintiles = pd.DataFrame([
        {"direction": head, "quintile": q, "realized_y_econ_mean": i * .001}
        for head in ("UP", "DOWN") for i, q in enumerate(R.QUINTILES)
    ])
    folds = {head: {"FOLD_STABILITY_GATE": head == "UP"} for head in ("UP", "DOWN")}
    classification, flags = R.classify(primary, quintiles, folds)
    assert classification == "A_CURRENT_INFORMATION_SET_HAS_INDEPENDENT_ECONOMIC_SIGNAL"
    assert flags["CURRENT_INFORMATION_SET_HAS_ECONOMIC_SIGNAL"] is True


def test_source_forbids_search_and_full_sample_refit():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("GridSearchCV", "RandomizedSearchCV", "XGB", "LightGBM", "RandomForest", "ExtraTrees"):
        assert forbidden not in source
    assert '"MODEL_FIT_BUDGET": 20' in source
    assert '"FULL_SAMPLE_REFIT_ALLOWED": False' in source
    assert '"FUTURE_FAMILY_MIN_DELTA_SPEARMAN": 0.02' in source
    assert '"FUTURE_FAMILY_MIN_DELTA_Q5_Q1": 0.0005' in source


def test_model_manifest_paths_are_portable_across_atomic_publish():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"path": f"models/{reg_path.name}"' in source
    assert '"path": f"models/{cls_path.name}"' in source
    assert '"path": str(reg_path)' not in source
    assert '"path": str(cls_path)' not in source
