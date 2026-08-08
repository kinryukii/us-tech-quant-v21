import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path(__file__).parents[2] / "scripts" / "run" / "fast3_cleanroom_r2_freeze.py"
SPEC = importlib.util.spec_from_file_location("cleanroom_r2", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def training_frame(rows=250):
    timestamp = pd.date_range("2024-01-02", periods=rows, freq="5min", tz="America/New_York")
    frame = pd.DataFrame({name: np.linspace(-0.1, 0.1, rows) for name in MODULE.R1.FEATURES})
    frame["symbol_code"] = 0
    frame["direction_code"] = 1
    frame["session_code"] = 2
    frame["target_first"] = np.arange(rows) % 2
    frame["candidate_id"] = [f"QQQ|UP|{value}" for value in timestamp.astype(str)]
    return frame


def test_final_training_isolation_uses_strict_frozen_holdout_instant():
    before = MODULE.TRUE_HOLDOUT_START_UTC - pd.Timedelta(nanoseconds=1)
    equal = MODULE.TRUE_HOLDOUT_START_UTC
    frame = pd.DataFrame({"horizon_timestamp_utc": [before, equal]})
    eligible = MODULE.label_safe_final_training_rows(frame)
    assert eligible.horizon_timestamp_utc.tolist() == [before]


def test_numeric_threshold_is_absolute_preholdout_percentile():
    scores = np.array([0.0, 0.1, 0.2, 0.3, 0.4])
    threshold = MODULE.numeric_threshold(scores)
    assert isinstance(threshold, float)
    assert threshold == np.quantile(scores, .95, method="linear")
    assert MODULE.select_by_frozen_threshold(np.array([threshold - .001, threshold, threshold + .001]), threshold).tolist() == [False, True, True]


def test_final_model_reconstruction_is_deterministic_and_reloads(tmp_path):
    frame = training_frame()
    model, evidence = MODULE.model_determinism("HGB", frame)
    path = tmp_path / "UP_HGB_FINAL.joblib"
    MODULE.joblib.dump(model, path)
    reloaded = MODULE.joblib.load(path)
    assert evidence["pass"] is True
    assert np.array_equal(model.predict_proba(frame[list(MODULE.R1.FEATURES)]), reloaded.predict_proba(frame[list(MODULE.R1.FEATURES)]))


def test_economic_contract_is_static_preholdout_input():
    contract = MODULE.economic_contract()
    assert contract["cost_total"] == .002
    assert contract["global_open_position_limit"] == 1
    assert contract["simultaneous_up_down_when_flat"] == "ABSTAIN"


def test_holdout_ledger_schema_guard_rejects_outcome_columns():
    assert MODULE.outcome_blind_schema_pass(["candidate_id", "return_5m", "max_feature_timestamp_utc"])
    assert not MODULE.outcome_blind_schema_pass(["candidate_id", "score"])
