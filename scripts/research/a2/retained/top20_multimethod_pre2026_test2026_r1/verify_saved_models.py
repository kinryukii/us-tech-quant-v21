"""Read-only restoration check on saved fold predictions; no estimator fit."""
from __future__ import annotations

import hashlib
import json

import joblib
import numpy as np
import pandas as pd

from fit_supervised import HERE, load_fold, predict_saved, scale


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    log = pd.read_csv(HERE / "FIT_LOG.csv")
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    fold_frames = {}
    for fold in log.fold.unique():
        train, val = load_fold(panel, fold)
        fold_frames[fold] = train if fold == "FINAL" else val
    checks = []
    for record in log.itertuples():
        key, family, fold = record.key, record.family, record.fold
        meta = json.loads((HERE / "models" / f"{key}.json").read_text(encoding="utf-8"))
        model = HERE / "models" / f"{key}{'.pt' if family == 'MLP' else '.joblib'}"
        scaler_path = HERE / "models" / f"SCALER_{fold}.joblib"
        assert sha(model) == meta["model_sha256"] == record.model_sha256
        assert sha(scaler_path) == meta["scaler_sha256"]
        scaler = joblib.load(scaler_path)
        frame = fold_frames[fold]
        prediction_dir = HERE / ("final_insample_predictions" if fold == "FINAL" else "predictions")
        saved = pd.read_parquet(prediction_dir / f"{key}.parquet")
        if len(saved) != len(frame):
            raise RuntimeError(f"RESTORE_LENGTH:{key}")
        positions = np.unique(np.linspace(0, len(frame) - 1, min(8, len(frame)), dtype=int))
        x = scale(frame.iloc[positions], scaler, family == "HGB_NO13F")
        cfg = meta["config"]
        if family == "MLP":
            cfg = {"hidden": tuple(cfg["hidden"])}
        recovered = predict_saved(model, family, x, cfg)
        expected = saved.prediction.to_numpy(float)[positions]
        max_abs = float(np.max(np.abs(recovered - expected)))
        if max_abs > 1e-12:
            raise RuntimeError(f"RESTORE_PREDICTION_MISMATCH:{key}:{max_abs}")
        checks.append({"key": key, "fold": fold, "family": family,
                       "model_sha256": meta["model_sha256"],
                       "scaler_sha256": meta["scaler_sha256"],
                       "checked_rows": len(positions), "max_abs_prediction_error": max_abs})
    report = {"status": "PASS", "fit_artifacts_read_only_checked": len(checks),
              "max_abs_prediction_error": max(c["max_abs_prediction_error"] for c in checks),
              "checks": checks}
    (HERE / "MODEL_RESTORE_CHECK.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "fit_artifacts_read_only_checked", "max_abs_prediction_error")}))


if __name__ == "__main__":
    main()
