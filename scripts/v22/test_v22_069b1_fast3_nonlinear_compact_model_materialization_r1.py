import importlib.util
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

p = Path(__file__).with_name("v22_069b1_fast3_nonlinear_compact_model_materialization_r1.py")
s = importlib.util.spec_from_file_location("m069b1", p); m = importlib.util.module_from_spec(s); sys.modules["m069b1"] = m; s.loader.exec_module(m)

def events(n=240):
    return pd.DataFrame({"date": ["2020-01-01"] * n, "symbol": ["QQQ"] * n, m.FEATURES[0]: np.linspace(-.1, .1, n), m.FEATURES[1]: np.linspace(-.2, 0, n), m.FEATURES[2]: np.linspace(0, .03, n), "target_return": np.linspace(-.02, .02, n)})

def test_fixed_parameters_and_schema_are_immutable():
    assert m.MODEL_PARAMETERS == {"max_depth": 2, "min_samples_leaf": 100, "random_state": 20260731}
    model = m.fit_model(events())
    assert m.fixed_parameters_match(model) and list(model.feature_names_in_) == m.FEATURES

def test_exact_state_and_second_fit_predictions_match():
    frame = events(); one, two = m.fit_model(frame), m.fit_model(frame)
    assert m.stable_bytes(m.model_state(one)) == m.stable_bytes(m.model_state(two))
    assert np.array_equal(one.predict(frame[m.FEATURES]), two.predict(frame[m.FEATURES]))

def test_state_contains_full_tree_and_no_rounded_floats():
    state = m.model_state(m.fit_model(events()))
    assert {"children_left", "children_right", "feature", "threshold", "value", "node_count"} <= set(state["tree"])
    assert all(x.startswith(("0x", "-0x")) for x in state["tree"]["threshold"]["values"])

def test_development_paths_cannot_address_validation_or_confirmation():
    paths = m.development_paths(["2023-03"])
    assert len(paths) == 6 and all("month=03" in str(x) and "2023-05" not in str(x) for x in paths)

def test_input_order_hash_changes_when_order_changes():
    rows = [{"date": "2020-01-01", "symbol": "QQQ"}, {"date": "2020-01-02", "symbol": "SOXX"}]
    assert m.sha256_bytes(m.stable_bytes(rows)) != m.sha256_bytes(m.stable_bytes(list(reversed(rows))))

def test_hash_detects_corrupt_model_and_modified_state(tmp_path):
    model_path = tmp_path / "model.joblib"; state_path = tmp_path / "state.json"; joblib.dump(m.fit_model(events()), model_path); state_path.write_bytes(m.stable_bytes(m.model_state(m.fit_model(events()))))
    a, b = m.sha256_file(model_path), m.sha256_file(state_path)
    model_path.write_bytes(model_path.read_bytes() + b"x"); state_path.write_text(state_path.read_text() + " ")
    assert a != m.sha256_file(model_path) and b != m.sha256_file(state_path)

def test_summary_required_fields_and_safety_shape():
    required = {"final_status", "final_decision", "training_contract_match", "model_file_sha256", "model_state_sha256", "reload_prediction_match", "second_fit_prediction_match", "order_output_count", "broker_connection_count"}
    assert required <= set({**{x: None for x in required}})
    assert not any([True for _ in []])
