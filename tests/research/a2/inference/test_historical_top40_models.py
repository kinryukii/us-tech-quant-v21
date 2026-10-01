"""Synthetic-only contract tests; no real model is trained or downloaded."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import joblib
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[4] / "scripts/research/a2/inference/historical_top40_models.py"
SPEC = importlib.util.spec_from_file_location("historical_top40_models_under_test", MODULE_PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class FakeModel:
    fit_calls = 0

    def get_params(self):
        return {"max_iter": 2, "random_state": 123}

    def fit(self, features, target):
        type(self).fit_calls += 1
        self.seen_rows = len(features)
        self.n_features_in_ = features.shape[1]
        return self


def original_split_shape(matrix, year):
    first = matrix.loc[matrix.signal_date.dt.year.eq(year), "signal_date"].min()
    training = matrix.loc[matrix.signal_date.lt(pd.Timestamp(f"{year}-01-01")) & matrix.target_end_date.lt(first)].copy()
    return training, matrix.loc[matrix.signal_date.dt.year.eq(year)].copy(), {"leakage_row_count": 0}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    paths = SimpleNamespace(**{key: tmp_path / key for key in
        ("repo_root", "backtest_root", "daily_root", "cache_root", "results_root")})
    baseline = paths.results_root / "A_VS_A2_QUARTERLY_13F_R1"
    folder = baseline / "A2"
    folder.mkdir(parents=True)
    features = ["feature_1", "feature_2"]
    rows = [
        ("2022-11-01", "2022-11-30"), ("2022-12-01", "2022-12-30"),
        ("2022-12-20", "2023-01-10"),  # Must be purged from the 2023 fit.
        ("2023-01-03", "2023-02-01"), ("2023-11-30", "2023-12-29"),
        ("2024-01-02", "2024-02-01"), ("2024-12-02", "2024-12-31"),
        ("2025-01-02", "2025-02-01"), ("2025-12-02", "2025-12-31"),
    ]
    frame = pd.DataFrame(rows, columns=["signal_date", "target_end_date"])
    for col in frame:
        frame[col] = pd.to_datetime(frame[col])
    frame["ticker"] = "SYNTHETIC"
    frame[features[0]] = 1.0
    frame[features[1]] = 2.0
    frame["target"] = 0.1
    refs = {"training": folder / "training_matrix.parquet", "freeze": baseline / "freeze.json",
            "source": tmp_path / "feature_source.py", "params_source": tmp_path / "params_source.py",
            "full_model": folder / "full_pre2026.joblib"}
    frame.to_parquet(refs["training"], index=False)
    refs["source"].write_text("# synthetic feature source\n", encoding="utf-8")
    refs["params_source"].write_text("# synthetic model constructor\n", encoding="utf-8")
    joblib.dump(FakeModel(), refs["full_model"])
    for name in ("source", "params_source", "full_model"):
        refs[name + "_sha256"] = m._digest(refs[name])
    vintage_rows = []
    for year, first in [(2023, "2023-01-03"), (2024, "2024-01-02"), (2025, "2025-01-02")]:
        part = frame.loc[frame.signal_date.lt(f"{year}-01-01") & frame.target_end_date.lt(first)]
        vintage_rows.append({"year": year, "prediction_min_date": first, "training_row_count": len(part),
            "train_max_date": str(part.signal_date.max().date()), "train_target_end_max": str(part.target_end_date.max().date()),
            "full_training_matrix_sha256": m._digest(refs["training"]),
            "effective_model_vintage_fingerprint": str(year), "training_row_identity_sha256": "synthetic-row-identity",
            "prediction_behavior_sha256": "synthetic-prediction-behavior"})
    a2 = {"feature_schema": features, "effective_model_vintages": vintage_rows,
          "training_row_count": len(frame), "hyperparameters": FakeModel().get_params(),
          "source_fingerprint": refs["source_sha256"], "prereg_fingerprint": refs["params_source_sha256"],
          "supplemental_full_pre2026_model": {"sha256": refs["full_model_sha256"], "used_for_frozen_oof_predictions": False}}
    freeze = {"contracts": {"A2": a2}}

    def save_freeze():
        refs["freeze"].write_text(json.dumps(freeze), encoding="utf-8")
        refs["freeze_sha256"] = m._digest(refs["freeze"])

    save_freeze()
    FakeModel.fit_calls = 0
    monkeypatch.setattr(m, "_references", lambda unused: refs)
    source = SimpleNamespace(FEATURE_COLUMNS=features, stage_rows=original_split_shape)
    params = SimpleNamespace(HGB_CONFIG=FakeModel().get_params(), make_hgb=FakeModel)
    monkeypatch.setattr(m, "_load_module", lambda path, name: params if "params" in name else source)
    return SimpleNamespace(paths=paths, output=paths.daily_root / "historical_top40/synthetic-run",
                           refs=refs, frame=frame, freeze=freeze, save_freeze=save_freeze, source=source)


def test_plan_never_fits_or_creates_output_and_2026_references_original(setup):
    result = m.build_models(setup.paths, setup.output)
    assert result["status"] == "PLANNED"
    assert result["model_fit_count"] == FakeModel.fit_calls == 0
    assert not setup.output.exists()
    assert result["artifacts"]["2023"]["training_row_count"] == 2
    assert result["artifacts"]["2026"]["path"] == str(setup.refs["full_model"])
    assert result["artifacts"]["2026"]["status"] == "FROZEN_REFERENCE"


def test_fixed_yearly_build_and_complete_manifest_resume(setup):
    original_hash = m._digest(setup.refs["full_model"])
    built = m.build_models(setup.paths, setup.output, execute=True)
    assert built["status"] == "READY"
    assert built["model_fit_count"] == FakeModel.fit_calls == 3
    assert joblib.load(built["artifacts"]["2023"]["path"]).seen_rows == 2
    assert m._digest(setup.refs["full_model"]) == original_hash
    resumed = m.build_models(setup.paths, setup.output, execute=True)
    assert resumed["model_fit_count"] == 0
    assert FakeModel.fit_calls == 3
    assert all(resumed["artifacts"][str(year)]["status"] == "REUSED" for year in (2023, 2024, 2025))


def test_resume_rejects_changed_complete_manifest(setup):
    result = m.build_models(setup.paths, setup.output, years=(2023,), execute=True)
    path = Path(result["artifacts"]["2023"]["manifest_path"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["created_at"] = "changed"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(m.ModelContractError, match="MANIFEST_FINGERPRINT"):
        m.build_models(setup.paths, setup.output, years=(2023,), execute=True)
    assert FakeModel.fit_calls == 1


def test_source_drift_and_row_count_fail_before_fit(setup):
    setup.refs["params_source"].write_text("# changed constructor")
    with pytest.raises(m.ModelContractError, match="SOURCE_HASH_MISMATCH"):
        m.build_models(setup.paths, setup.output, execute=True)
    setup.refs["params_source"].write_text("# synthetic model constructor\n", encoding="utf-8")
    setup.freeze["contracts"]["A2"]["effective_model_vintages"][0]["training_row_count"] += 1
    setup.save_freeze()
    with pytest.raises(m.ModelContractError, match="FOLD_ROW_COUNT_MISMATCH"):
        m.build_models(setup.paths, setup.output, execute=True)
    assert FakeModel.fit_calls == 0


def test_2026_label_boundary_rejected_even_with_matching_file_hash(setup):
    setup.frame.loc[0, "target_end_date"] = pd.Timestamp("2026-01-02")
    setup.frame.to_parquet(setup.refs["training"], index=False)
    for row in setup.freeze["contracts"]["A2"]["effective_model_vintages"]:
        row["full_training_matrix_sha256"] = m._digest(setup.refs["training"])
    setup.save_freeze()
    with pytest.raises(m.ModelContractError, match="TRAINING_2026_DATE_FORBIDDEN"):
        m.build_models(setup.paths, setup.output, execute=True)
    assert FakeModel.fit_calls == 0
    assert not setup.output.exists()


def test_changed_split_and_frozen_output_are_rejected(setup):
    with pytest.raises(m.ModelContractError, match="FROZEN_OUTPUT_FORBIDDEN"):
        m.build_models(setup.paths, setup.refs["training"].parent / "bad-run", execute=True)
    setup.source.stage_rows = lambda matrix, year: (matrix.iloc[:3], None, {"leakage_row_count": 0})
    with pytest.raises(m.ModelContractError, match="ORIGINAL_STAGE_SPLIT_MISMATCH"):
        m.build_models(setup.paths, setup.output, years=(2023,), execute=True)
    assert FakeModel.fit_calls == 0
    assert not (setup.output / "models/.build.lock").exists()


def test_resume_rejects_model_bytes_changed(setup):
    result = m.build_models(setup.paths, setup.output, years=(2024,), execute=True)
    Path(result["artifacts"]["2024"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(m.ModelContractError, match="SOURCE_HASH_MISMATCH"):
        m.build_models(setup.paths, setup.output, years=(2024,), execute=True)
    assert FakeModel.fit_calls == 1
