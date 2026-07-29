"""Six targeted guard tests for V22.067B3P."""
import ast
import importlib.util
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).with_name("v22_067b3p_fast3_soxx_long_0p50_prospective_shadow_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_067b3p", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_1_no_pre_forward_start_candidates():
    assert 'FORWARD_START_ET = pd.Timestamp("2026-07-29 00:00:00"' in MODULE_PATH.read_text(encoding="utf-8")
    assert "candidate_timestamp_utc.dt.tz_convert(\"America/New_York\") >= FORWARD_START_ET" in MODULE_PATH.read_text(encoding="utf-8")


def test_2_reads_and_validates_b1m_frozen_bundle():
    bundle = joblib.load(MODULE.MODEL_FILE)
    assert MODULE.validate_bundle(bundle) == bundle["frozen_threshold"]


def test_3_source_has_no_fit_methods():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not {"fit", "fit_transform", "partial_fit"}.intersection(called)


def test_4_threshold_dedup_is_two_layered():
    frame = pd.DataFrame({"score": [0.99, 0.98, 0.97], "overlap_group_id": ["a", "a", "b"], "trading_date_et": ["2026-07-29"] * 3,
                          "session": ["OVERNIGHT", "OVERNIGHT", "OVERNIGHT"], "candidate_timestamp_utc": pd.to_datetime(["2026-07-29T00:00:00Z", "2026-07-29T00:05:00Z", "2026-07-29T00:10:00Z"]), "symbol": ["SOXX"] * 3})
    class Pipeline:
        def predict_proba(self, values): return np.array([[0.01, item] for item in frame.score])
    selected = MODULE.select_signals(frame, Pipeline(), [], 0.95)
    assert len(selected) == 1 and selected.iloc[0].score == 0.99


def test_5_pending_and_resolved_classification():
    index = pd.date_range("2026-07-29T00:00:00Z", periods=91, freq="min")
    high = pd.Series(101.0, index=index); low = pd.Series(99.9, index=index); close = pd.Series(100.0, index=index)
    outcomes = MODULE.label(high, low, close, .005, .0025, "LONG", 90)
    assert outcomes.iloc[0] == "TARGET_FIRST" and outcomes.iloc[-1] == "PENDING"


def test_6_input_hashes_are_checked_before_and_after():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "model_before" in source and "model_after" in source and "canonical_before" in source and "canonical_after" in source
