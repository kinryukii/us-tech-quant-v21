from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).with_name("abcde_a2_nonlinear_alpha_baseline_r1.py")
spec = importlib.util.spec_from_file_location("abcde_a2_r1", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_training_cutoff_removes_every_2026_row():
    frame = pd.DataFrame({"signal_date": ["2025-12-31", "2026-01-01"], "value": [1, 2]})
    eligible = mod.enforce_pre2026(frame)
    assert eligible["value"].tolist() == [1]
    assert pd.to_datetime(eligible.signal_date).max() < mod.TRAINING_BOUNDARY


def test_expanding_temporal_folds_are_strict_and_pre2026():
    mod.validate_temporal_folds()
    for fold in mod.PLANNED_FOLDS:
        assert pd.Timestamp(fold["train_end"]) < pd.Timestamp(fold["test_start"])
        assert pd.Timestamp(fold["test_end"]) < mod.TRAINING_BOUNDARY


def test_feature_lag_and_target_forward_alignment():
    good = pd.DataFrame({
        "feature_information_timestamp": ["2025-01-02 16:00"],
        "signal_timestamp": ["2025-01-02 16:00"],
        "target_start_timestamp": ["2025-01-03 09:30"],
        "target_end_timestamp": ["2025-01-09 16:00"],
    })
    mod.validate_information_alignment(good)
    bad_feature = good.copy()
    bad_feature["feature_information_timestamp"] = "2025-01-02 16:01"
    with pytest.raises(mod.ContractStop, match="POST_SIGNAL"):
        mod.validate_information_alignment(bad_feature)
    bad_target = good.copy()
    bad_target["target_start_timestamp"] = "2025-01-02 16:00"
    with pytest.raises(mod.ContractStop, match="STRICTLY_FORWARD"):
        mod.validate_information_alignment(bad_target)


def test_fixed_hgb_is_deterministic_under_same_input_and_config():
    rng = np.random.default_rng(7)
    x = rng.normal(size=(600, 4))
    y = x[:, 0] * x[:, 1] - 0.25 * x[:, 2] ** 2
    first = mod.make_hgb().fit(x, y).predict(x)
    second = mod.make_hgb().fit(x, y).predict(x)
    assert np.array_equal(first, second)
    assert mod.HGB_CONFIG["random_state"] == 20260816


def test_real_a1_freeze_identity_is_unchanged():
    audit = mod.audit_a1_identity()
    assert audit["status"] == "PASS"
    assert audit["source_script_sha256"] == audit["expected_source_script_sha256"]
    assert audit["contract_sha256"] == audit["expected_contract_sha256"]


def test_fail_closed_summary_has_schema_and_zero_fit_or_broker(tmp_path):
    a1 = {"status": "PASS"}
    price = {"status": "PASS", "authoritative_price_source": "MOOMOO", "historical_data_start": "2020-01-02", "historical_data_end": "2025-12-31", "moomoo_api_request_count": 0}
    pit = {"status": "FAIL_CLOSED", "reason": "NO_PIT_UNIVERSE"}
    summary = mod.build_fail_closed_summary(tmp_path.resolve(), a1, price, pit)
    assert set(mod.SUMMARY_FIELDS).issubset(summary)
    assert summary["TRAINING_2026_ROW_COUNT"] == 0
    assert summary["MODEL_FIT_COUNT"] == 0
    assert summary["BROKER_ACTION_COUNT"] == 0
    assert summary["FAST_INTEGRATION_COUNT"] == 0
    assert summary["A1_CHANGED"] is False
    assert summary["DAILY_CHAIN_CHANGED"] is False
    assert summary["OOF_PREDICTION_PATH"] == "NOT_CREATED_FAIL_CLOSED"


def test_module_has_no_broker_or_fast_dependency():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "OpenTradeContext" not in text
    assert "place_order" not in text
    assert "import fast3" not in text
    assert "from fast3" not in text
