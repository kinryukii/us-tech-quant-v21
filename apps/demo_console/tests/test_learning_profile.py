"""Pure metadata projections; no frozen files, fitted models or outcomes read."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from apps.demo_console.adapters.artifact_reader import ArtifactError
from apps.demo_console.adapters.system_status_reader import learning_profile
from apps.demo_console.models import LearningProfile


def _vintage(year=2025, **changes):
    record = {
        "year": year, "vintage": "SYNTHETIC",
        "train_max_date": f"{year - 1}-12-02",
        "train_target_end_max": f"{year - 1}-12-31",
        "prediction_min_date": f"{year}-01-02",
        "prediction_max_date": f"{year}-12-30",
        "training_row_count": 31, "prediction_count": 17,
        "effective_model_vintage_fingerprint": "a" * 64,
        "serialized_model_artifact_status": "SERIALIZED_STAGE_MODEL_NOT_PERSISTED_BY_FROZEN_RUN",
    }
    return {**record, **changes}


def _manifest(**changes):
    alpha = {
        "feature_schema": ["ret_1d", "avg_volume_20d"],
        "hyperparameters": {"learning_rate": .05, "early_stopping": False, "max_iter": 200},
        "target": "Synthetic target definition",
        "effective_model_vintages": [_vintage(2025), _vintage(2023)],
        "source_fingerprint": "b" * 64,
        # These global fields must not replace a historical vintage's limits.
        "max_training_date": "2025-12-02", "training_row_count": 999,
        "supplemental_full_pre2026_model": {"used_for_frozen_oof_predictions": False},
    }
    return {"contracts": {"A2": {**alpha, **changes}}}


def test_missing_optional_metadata_stays_unknown_without_inventing_model_details():
    for manifest in ({}, {"contracts": {}}, {"contracts": {"A2": {}}}):
        assert learning_profile(manifest) == LearningProfile()


def test_projection_preserves_source_values_and_each_vintage_without_additional_io(monkeypatch):
    manifest = _manifest()
    before = deepcopy(manifest)

    def unexpected_open(*args, **kwargs):
        raise AssertionError("A metadata projection must not open another artifact")

    monkeypatch.setattr(Path, "open", unexpected_open)
    profile = learning_profile(manifest)
    assert manifest == before
    assert profile.feature_columns == ("ret_1d", "avg_volume_20d")
    assert {key: json.loads(value) for key, value in profile.parameters} == before["contracts"]["A2"]["hyperparameters"]
    assert profile.target == "Synthetic target definition"
    assert profile.source_fingerprint == "b" * 64
    assert [vintage.year for vintage in profile.vintages] == [2023, 2025]
    assert [(vintage.train_max_date, vintage.train_target_end_max, vintage.training_row_count)
            for vintage in profile.vintages] == [
                ("2022-12-02", "2022-12-31", 31), ("2024-12-02", "2024-12-31", 31)]
    assert all(vintage.prediction_count == 17 for vintage in profile.vintages)
    assert all(vintage.serialized_status == "SERIALIZED_STAGE_MODEL_NOT_PERSISTED_BY_FROZEN_RUN"
               for vintage in profile.vintages)
    with pytest.raises(FrozenInstanceError):
        profile.target = "Different target"
    with pytest.raises(FrozenInstanceError):
        profile.vintages[0].year = 2024


@pytest.mark.parametrize("changes", [
    {"train_target_end_max": "2025-01-02"},  # Equality still exposes a not-yet-prior label.
    {"train_max_date": "2025-01-01"},
    {"prediction_min_date": "2025-12-31"},
    {"prediction_max_date": "2026-01-01"},
    {"prediction_min_date": "2024-12-31"},
    {"train_max_date": "not-a-date"},
    {"year": 2024},
    {"year": True},
    {"training_row_count": 0},
    {"prediction_count": -1},
    {"training_row_count": 31.0},
    {"prediction_count": True},
])
def test_declared_vintages_reject_overlap_post2025_coverage_and_invalid_counts(changes):
    record = _vintage()
    record.update(changes)
    with pytest.raises(ArtifactError):
        learning_profile(_manifest(effective_model_vintages=[record]))


def test_duplicate_years_are_rejected_even_with_different_names_and_fingerprints():
    duplicate = _vintage(vintage="ANOTHER_NAME", effective_model_vintage_fingerprint="c" * 64)
    with pytest.raises(ArtifactError, match="DUPLICATE_YEAR"):
        learning_profile(_manifest(effective_model_vintages=[_vintage(), duplicate]))


@pytest.mark.parametrize("changes", [
    {"feature_schema": ["ret_1d", "ret_1d"]},
    {"feature_schema": ["ret_1d", None]},
    {"feature_schema": "ret_1d"},
    {"hyperparameters": []},
    {"hyperparameters": {"learning_rate": {"value": .05}}},
    {"hyperparameters": {"learning_rate": float("nan")}},
    {"hyperparameters": {"learning_rate": float("inf")}},
    {"hyperparameters": {"learning_rate": .05, 1: "not-a-parameter-name"}},
    {"target": ["not a scalar target definition"]},
])
def test_invalid_declared_schema_and_parameters_fail_with_an_artifact_error(changes):
    with pytest.raises(ArtifactError):
        learning_profile(_manifest(**changes))


@pytest.mark.parametrize("records", [None, {}, [None], ["2025"], [{}], [_vintage(vintage=None)]])
def test_malformed_declared_vintages_are_not_silently_coerced_or_raw_runtime_errors(records):
    with pytest.raises(ArtifactError):
        learning_profile(_manifest(effective_model_vintages=records))


def test_absent_optional_vintage_identity_does_not_claim_a_serialized_model():
    record = _vintage()
    record.pop("effective_model_vintage_fingerprint")
    record.pop("serialized_model_artifact_status")
    vintage = learning_profile(_manifest(effective_model_vintages=[record])).vintages[0]
    assert vintage.fingerprint == "" and vintage.serialized_status == ""
