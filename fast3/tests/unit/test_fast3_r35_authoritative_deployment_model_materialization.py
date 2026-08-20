from __future__ import annotations

import ast
import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


RUNNER = Path(__file__).parents[2] / "scripts/run/fast3_r35_authoritative_deployment_model_materialization.py"
spec = importlib.util.spec_from_file_location("r35", RUNNER)
r35 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(r35)


def test_r33_closeout_and_authoritative_head_set_are_exact() -> None:
    assert r35.sha256(r35.R33_CLOSEOUT) == "9763c4f775940eb5a1b51fc48b4f4e002d2740c8db06e369531a5ae6a31a078b"
    closeout = r35.read_json(r35.R33_CLOSEOUT)
    assert closeout["R33_RESEARCH_PHASE_STATUS"] == "CLOSED"
    assert closeout["AUTHORITATIVE_HEAD_SET"] == ["T1", "T5", "T6"]
    assert closeout["T7_STATUS"] == "REJECTED_REDUNDANT_WITH_T5"
    assert closeout["T8_PLUS_STATUS"] == "PROHIBITED"
    assert closeout["FURTHER_HEAD_EXPANSION_ALLOWED"] is False


def test_source_contracts_are_uniquely_recoverable_and_frozen() -> None:
    source, features, _, _, _, r30a = r35.recover_contracts()
    assert tuple(source) == ("T1", "T5", "T6")
    assert len(features) == 29
    assert all(record["feature_manifest_sha256"] == r35.FEATURE_MANIFEST_SHA256 for record in source.values())
    assert all(record["feature_column_order"] == list(features) for record in source.values())
    assert all(record["hyperparameters"] == r30a.HGB_PARAMS for record in source.values())
    assert all(record["seed"] == 1729 for record in source.values())
    assert all(record["direction_handling"] == "independent UP/DOWN deployment fits" for record in source.values())
    assert source["T1"]["target_definition"] == "T1_POSITIVE_NET20 = 1[net20 > 0]"
    assert source["T5"]["training_eligibility"] == "label_valid == true AND net20 < 0"
    assert source["T6"]["training_eligibility"] == "label_valid == true AND net20 > 0"


def test_training_window_is_exactly_frozen_development_and_excludes_final() -> None:
    manifest = r35.read_json(r35.R32A_LABEL_MANIFEST)
    assert manifest["valid_count"] == 1_456_595
    assert manifest["PROSPECTIVE_ROW_COUNT_IN_LABEL_LEDGER"] == 0
    assert manifest["FINAL_CONFIRMATION_ROW_COUNT_IN_LABEL_LEDGER"] == 0
    assert pd.Timestamp(manifest["timestamp_bounds"][1]) < r35.TRUE_HOLDOUT_START
    prereg = r35.read_json(r35.R32A_PREREG)
    assert prereg["UNIVERSE"] == "full pre-score eligible TRAIN+DEVELOPMENT economic universe"


def test_preregistration_freezes_expected_fit_counts_before_fit() -> None:
    source, _, _, _, _, _ = r35.recover_contracts()
    for head in source:
        source[head].update({
            "training_row_count": 1,
            "training_start": "2018-01-01T00:00:00Z",
            "training_end": "2025-01-01T00:00:00Z",
            "training_population_sha256": "a" * 64,
        })
    prereg = r35.preregistration(source, "2026-08-10T00:00:00+00:00")
    assert prereg["STATUS"] == "FROZEN_BEFORE_FIRST_FIT"
    assert prereg["EXPECTED_FIT_COUNTS"] == {"T1": 2, "T5": 2, "T6": 2}
    assert prereg["EXPECTED_TOTAL_DEPLOYMENT_FIT_COUNT"] == 6
    assert prereg["OOF_REBUILD_ALLOWED"] is False
    assert prereg["FINAL_ALLOWED"] is False
    source_text = inspect.getsource(r35.main)
    assert source_text.index("write_json(prereg_path, prereg)") < source_text.index("fit_and_serialize(")


def test_feature_order_guard_fails_closed_and_finite_prediction_passes() -> None:
    class Dummy:
        def predict(self, frame: pd.DataFrame) -> np.ndarray:
            return frame.to_numpy(dtype=float).sum(axis=1)

    features = ("a", "b")
    good = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    assert np.array_equal(r35.strict_predict(Dummy(), good, features, False), np.array([4.0, 6.0]))
    with pytest.raises(r35.R35Stop, match="STOPPED_DATA_OR_LINEAGE_INTEGRITY"):
        r35.strict_predict(Dummy(), good[["b", "a"]], features, False)


def test_population_hash_is_deterministic_and_identity_sensitive() -> None:
    frame = pd.DataFrame({
        "candidate_id": ["b", "a"],
        "decision_timestamp_utc": pd.to_datetime(["2020-01-02T00:00:00Z", "2020-01-01T00:00:00Z"]),
        "head": ["UP", "DOWN"],
        "target": [0.2, 0.1],
    })
    first = r35.stable_population_sha(frame, "target")
    assert first == r35.stable_population_sha(frame.iloc[::-1], "target")
    changed = frame.copy()
    changed.loc[0, "target"] = 0.3
    assert first != r35.stable_population_sha(changed, "target")


def test_no_search_oof_performance_calibration_prospective_score_trade_or_final() -> None:
    prereg_source, _, _, _, _, _ = r35.recover_contracts()
    prereg = r35.preregistration(prereg_source, "2026-08-10T00:00:00+00:00")
    assert prereg["MODEL_SEARCH_ALLOWED"] is False
    assert prereg["HYPERPARAMETER_SEARCH_ALLOWED"] is False
    assert prereg["TRAINING_WINDOW_SEARCH_ALLOWED"] is False
    assert prereg["PROSPECTIVE_ACTIVATION_ALLOWED"] is False
    assert prereg["ECONOMIC_SCORE_ALLOWED"] is False
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    fit_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"]
    assert len(fit_calls) == 1
    text = RUNNER.read_text(encoding="utf-8")
    for required in (
        '"SCIENTIFIC_PERFORMANCE_METRIC_COUNT": 0',
        '"NEW_OOF_PREDICTION_COUNT": 0',
        '"P_PROSPECTIVE_CALIBRATION_BUILD_COUNT": 0',
        '"R34_PROSPECTIVE_START_CREATED": False',
        '"ABSOLUTE_EV_CONSTRUCTION_COUNT": 0',
        '"TRADING_SIMULATION_COUNT": 0',
        '"FINAL_HOLDOUT_INSPECTED": False',
    ):
        assert required in text


def test_model_names_are_canonical_and_duplicate_copies_are_absent() -> None:
    source = inspect.getsource(r35.fit_and_serialize)
    assert 'f"FAST3_{head}_{direction}_DEPLOYMENT_MODEL.joblib"' in source
    assert "copy" not in source.lower()
    assert "backup" not in source.lower()
    assert "model_v2" not in source.lower()


def test_external_storage_contract_and_source_file_bloat_limit() -> None:
    r35.validate_storage()
    assert r35.RESULTS_ROOT == Path(r"D:\us-tech-quant-results")
    repo = Path(__file__).parents[3]
    files = [
        path.resolve() for path in repo.rglob("*r35*authoritative*deployment*materialization*.py")
        if path.is_file()
    ]
    assert set(files) == {RUNNER.resolve(), Path(__file__).resolve()}


def test_allowed_status_enum_is_closed() -> None:
    assert r35.ALLOWED_STATUSES == {
        "PASS", "STOPPED_AUTHORITATIVE_RESEARCH_CONTRACT_NOT_RECOVERABLE",
        "STOPPED_AUTHORITATIVE_DEPLOYMENT_FIT_FAILED", "STOPPED_DATA_OR_LINEAGE_INTEGRITY",
        "STOPPED_STORAGE_CONTRACT_VIOLATION", "STOPPED_PREREGISTRATION_ORDER_VIOLATION",
        "STOPPED_RESEARCH_CHOICE_CHANGED", "STOPPED_ANTI_BLOAT_VIOLATION",
    }
    assert "PARTIAL_PASS" not in r35.ALLOWED_STATUSES
