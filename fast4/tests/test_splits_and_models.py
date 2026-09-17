from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast4.models import Spec, fit_spec  # noqa: E402
from fast4.splits import BLOCKS, inner_folds, outer_folds  # noqa: E402


def synthetic_frame() -> pd.DataFrame:
    rows = []
    for year, block in zip(range(2020, 2026), BLOCKS):
        for day in range(1, 21):
            ts = pd.Timestamp(year=year, month=1, day=day, hour=14, tz="UTC")
            rows.append({"candidate_id": f"{block}-{day}", "decision_timestamp_utc": ts,
                         "entry_timestamp": ts + pd.Timedelta(minutes=1), "target_end_timestamp_utc": ts + pd.Timedelta(minutes=61),
                         "trading_date": str(ts.date()), "validation_slice": block, "head": "UP" if day % 2 else "DOWN",
                         "x1": float(day), "x2": float(year - 2020), "primary_target": (day - 10) / 1000,
                         "y_positive": int(day > 10)})
    return pd.DataFrame(rows)


def test_chronological_purge_embargo_overlap_and_determinism() -> None:
    frame = synthetic_frame()
    first = outer_folds(frame)
    second = outer_folds(frame.copy())
    assert [(f.name, f.train_index.tolist(), f.valid_index.tolist()) for f in first] == [(f.name, f.train_index.tolist(), f.valid_index.tolist()) for f in second]
    for fold in first:
        train, valid = frame.loc[fold.train_index], frame.loc[fold.valid_index]
        assert set(train.candidate_id).isdisjoint(valid.candidate_id)
        assert train.target_end_timestamp_utc.max() < valid.decision_timestamp_utc.min() - pd.Timedelta(minutes=60)
        inner = inner_folds(frame, fold.train_index)
        for nested in inner:
            assert set(frame.loc[nested.train_index, "candidate_id"]).isdisjoint(frame.loc[nested.valid_index, "candidate_id"])
            assert frame.loc[nested.train_index, "target_end_timestamp_utc"].max() < frame.loc[nested.valid_index, "decision_timestamp_utc"].min() - pd.Timedelta(minutes=60)


def test_model_finite_serialization_reload_and_feature_order(tmp_path: Path) -> None:
    frame = synthetic_frame()
    spec = Spec("test", "hist_gradient_boosting", "pooled", "regression", "primary_target")
    params = {"learning_rate": .05, "max_iter": 30, "max_leaf_nodes": 7, "min_samples_leaf": 10,
              "l2_regularization": 1., "max_bins": 63, "loss_variant": "squared_error"}
    fitted, count = fit_spec(spec, frame, frame.index.to_numpy(), ["x1", "x2"], params, 4401)
    prediction = fitted.predict_score(frame)
    assert count == 1 and np.isfinite(prediction).all() and fitted.feature_order == ["x1", "x2"]
    path = tmp_path / "model.joblib"
    joblib.dump(fitted, path)
    reloaded = joblib.load(path)
    assert np.allclose(prediction, reloaded.predict_score(frame), rtol=0, atol=1e-12)
    directional = Spec("directional", "hist_gradient_boosting", "directional", "regression", "primary_target")
    fitted_directional, direction_count = fit_spec(directional, frame, frame.index.to_numpy(), ["x1", "x2"], params, 4401)
    assert direction_count == 2 and np.isfinite(fitted_directional.predict_score(frame)).all()
