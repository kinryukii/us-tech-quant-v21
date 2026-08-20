from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r43d_path_shape_information_family_incremental_test_r1.py"
SPEC = importlib.util.spec_from_file_location("r43d", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_manifest_freezes_exact_eight_atomic_features_and_excludes_regime():
    manifest = R.feature_manifest("fixed", {})
    assert manifest["STATUS"] == "FROZEN_BEFORE_R43D_TARGET_READ_AND_MODEL_FIT"
    assert manifest["PATH_SHAPE_FEATURE_COUNT"] == 8
    assert tuple(manifest["PATH_SHAPE_FEATURE_NAMES"]) == R.PATH_FEATURES
    assert manifest["PATH_MODEL_FEATURE_COUNT"] == 22
    assert manifest["INTERACTIONS_ALLOWED"] is False
    assert manifest["REGIME_OR_VIX_FEATURES_ALLOWED"] is False
    assert manifest["R43C_REGIME_FAMILY_EXCLUDED"] is True
    assert manifest["MODEL_FIT_BUDGET"] == 20


def test_linear_path_has_exact_efficiency_excursion_location_and_consistency():
    close = np.arange(100.0, 181.0)
    high = close + .1; low = close - .1
    up = R.path_values(close, high, low, 80, 1)
    down = R.path_values(close, high, low, 80, -1)
    assert np.isclose(up["return_acceleration_5v15"], (180 / 175 - 1) - (180 / 165 - 1) / 3)
    assert up["trend_efficiency_15m"] == 1.0
    assert up["trend_efficiency_60m"] == 1.0
    assert up["predecision_mfe_15m"] > 0 and up["predecision_mae_15m"] == 0
    assert np.isclose(up["drawdown_from_favorable_extreme_15m"], 0)
    assert up["close_location_15m"] > .99
    assert up["directional_path_consistency_15m"] == 1.0
    assert down["predecision_mfe_15m"] == 0 and down["predecision_mae_15m"] < 0
    assert down["drawdown_from_favorable_extreme_15m"] < 0
    assert down["close_location_15m"] < .01
    assert down["directional_path_consistency_15m"] == 0.0


def test_flat_path_preserves_required_nan_semantics():
    close = np.ones(61) * 100; high = close.copy(); low = close.copy()
    values = R.path_values(close, high, low, 60, 1)
    assert np.isnan(values["trend_efficiency_15m"])
    assert np.isnan(values["trend_efficiency_60m"])
    assert np.isnan(values["close_location_15m"])
    assert values["directional_path_consistency_15m"] == 0.0


def test_model_config_exactly_reuses_r43b_structure():
    reg = R.model_config("regressor"); cls = R.model_config("classifier")
    for key, value in R.HGB_STRUCTURE.items(): assert reg[key] == cls[key] == value
    assert reg["loss"] == "squared_error" and cls["loss"] == "log_loss"
    assert len(reg["categorical_features"]) == 22
    assert sum(reg["categorical_features"]) == 2


def test_incremental_gate_requires_both_deltas_fold_and_tail():
    primary = pd.DataFrame([
        {"direction": "UP", "spearman": R.BASELINE_REFERENCE["UP"]["spearman"] + .02,
         "q5_q1": R.BASELINE_REFERENCE["UP"]["q5_q1"] + .0005, "ordering": "NON_MONOTONIC", "q5_mean": -.01},
        {"direction": "DOWN", "spearman": -.2, "q5_q1": -.02, "ordering": "NON_MONOTONIC", "q5_mean": -.01},
    ])
    tails = pd.DataFrame([{"direction": "UP", "tail_robustness": False},
                          {"direction": "DOWN", "tail_robustness": None}])
    folds = {head: {"PATH_FOLD_STABILITY": False, "MAJORITY_FOLD_NON_DEGRADATION": True,
                    "FOLD_DEGRADATION_COUNT": 0} for head in ("UP", "DOWN")}
    flags, classification, retained, accepted = R.evaluate(primary, tails, folds)
    assert flags["UP_PATH_PRIMARY_INCREMENTAL_ACCEPTANCE"] is False
    assert classification == "C_PATH_SHAPE_INFORMATION_NOT_INCREMENTALLY_USEFUL"
    assert retained is False and accepted == "NONE"


def test_source_forbids_search_and_new_family_contamination():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("GridSearchCV", "RandomizedSearchCV", "XGB", "LightGBM", "RandomForest", "ExtraTrees"):
        assert forbidden not in source
    assert '"MODEL_FIT_BUDGET": 20' in source
    assert '"MIN_DELTA_SPEARMAN": .02' in source
    assert '"MIN_DELTA_Q5_Q1": .0005' in source
