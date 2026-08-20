from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[2] / "scripts/run/fast3_r43c_regime_information_family_incremental_test_r1.py"
SPEC = importlib.util.spec_from_file_location("r43c", SCRIPT)
R = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def test_manifest_freezes_minimal_seven_member_family_before_fit():
    manifest = R.feature_manifest("fixed", {})
    assert manifest["STATUS"] == "FROZEN_BEFORE_R43C_TARGET_READ_AND_MODEL_FIT"
    assert manifest["REGIME_FEATURE_COUNT"] == 7
    assert tuple(manifest["REGIME_FEATURE_NAMES"]) == R.REGIME_FEATURES
    assert manifest["EXCLUDED_CANDIDATE"]["name"] == "market_vol_regime_interaction"
    assert manifest["EXCLUDED_CANDIDATE"]["status"] == "NOT_INCLUDED_MINIMAL_FAMILY"
    assert manifest["REGIME_MODEL_FIT_BUDGET"] == 20
    assert manifest["BASELINE_REFIT_ALLOWED"] is False
    assert manifest["FULL_SAMPLE_REFIT_ALLOWED"] is False


def test_trailing_percentile_uses_only_fixed_lookback_and_minimum():
    history = np.arange(1.0, 31.0)
    assert R.empirical_percentile(history, 25.0, 20, 20) == 0.75
    assert np.isnan(R.empirical_percentile(history[:19], 25.0, 20, 20))
    assert np.isnan(R.empirical_percentile(history, np.nan, 20, 20))


def test_model_config_matches_r43b_structure_and_only_extends_feature_mask():
    reg = R.model_config("regressor"); cls = R.model_config("classifier")
    for key, value in R.HGB_STRUCTURE.items():
        assert reg[key] == cls[key] == value
    assert reg["loss"] == "squared_error" and cls["loss"] == "log_loss"
    assert len(reg["categorical_features"]) == 21
    assert sum(reg["categorical_features"]) == 2
    manifest = R.feature_manifest("fixed", {})
    assert manifest["MODEL_CONFIG"] == R.HGB_STRUCTURE
    assert manifest["INCREMENTAL_GATE"]["MIN_DELTA_SPEARMAN"] == .02
    assert manifest["INCREMENTAL_GATE"]["MIN_DELTA_Q5_Q1"] == .0005


def test_stable_quintiles_and_ordering_are_frozen():
    frame = pd.DataFrame({
        "direction": ["UP"] * 10, "prediction": [1.0] * 10,
        "decision_timestamp_utc": pd.date_range("2020-01-01", periods=10, tz="UTC"),
        "candidate_id": [str(i) for i in range(10)],
    })
    buckets = R.stable_quintiles(frame, "prediction")
    assert buckets.value_counts().to_dict() == {q: 2 for q in R.QUINTILES}
    assert R.ordering([1, 2, 3, 4, 5]) == "MONOTONIC_POSITIVE"
    assert R.ordering([1, 2, 3, 2, 5]) == "MOSTLY_POSITIVE"
    assert R.ordering([5, 4, 3, 2, 1]) == "MONOTONIC_NEGATIVE"


def test_incremental_acceptance_cannot_be_replaced_by_absolute_or_secondary():
    primary = pd.DataFrame([
        {"direction": "UP", "spearman": R.BASELINE_REFERENCE["UP"]["spearman"] + .019,
         "q5_q1": R.BASELINE_REFERENCE["UP"]["q5_q1"] + .001, "ordering": "MOSTLY_POSITIVE", "q5_mean": .01},
        {"direction": "DOWN", "spearman": -.1, "q5_q1": -.01, "ordering": "NON_MONOTONIC", "q5_mean": -.01},
    ])
    tails = pd.DataFrame([{"direction": head, "tail_robustness": True} for head in ("UP", "DOWN")])
    fold_flags = {head: {"REGIME_FOLD_STABILITY": True, "MAJORITY_FOLD_NON_DEGRADATION": True,
                         "FOLD_DEGRADATION_COUNT": 0} for head in ("UP", "DOWN")}
    flags, classification, retained = R.evaluate(primary, pd.DataFrame(), tails, fold_flags)
    assert flags["UP_REGIME_PRIMARY_INCREMENTAL_ACCEPTANCE"] is False
    assert classification == "C_REGIME_INFORMATION_NOT_INCREMENTALLY_USEFUL"
    assert retained is False


def test_source_has_no_search_or_forbidden_model_family():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("GridSearchCV", "RandomizedSearchCV", "XGB", "LightGBM", "RandomForest", "ExtraTrees"):
        assert forbidden not in source
    assert '"SHAP_ALLOWED": False' in source
    assert '"REGIME_MODEL_FIT_BUDGET": 20' in source
    assert '"MIN_DELTA_SPEARMAN": .02' in source
    assert '"MIN_DELTA_Q5_Q1": .0005' in source
