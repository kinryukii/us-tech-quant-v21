"""FINAL fitted-in predictions, explicitly separate from historical OOF validation."""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from fit_supervised import HERE, model_key, predict_saved, load_fold, scale


def main() -> None:
    if not (HERE / "PRIMARY_SELECTION.json").exists():
        raise RuntimeError("PRIMARY_REQUIRED")
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    train, _ = load_fold(panel, "FINAL")
    scaler = joblib.load(HERE / "models" / "SCALER_FINAL.joblib")
    selected = json.loads((HERE / "DEVELOPMENT_SELECTION.json").read_text(encoding="utf-8"))["selection_only_D1_D2"]
    output_dir = HERE / "final_insample_predictions"
    output_dir.mkdir(exist_ok=True)
    saved = 0
    for family in ("RIDGE", "ELASTIC", "LOGISTIC", "HGB", "MLP", "QUANTILE", "HGB_NO13F"):
        cfg = selected[family]
        x = scale(train, scaler, family == "HGB_NO13F")
        suffixes = [(None, None)]
        if family == "MLP":
            suffixes = [(seed, None) for seed in (11, 29, 47)]
        elif family == "QUANTILE":
            suffixes = [(None, q) for q in (.1, .5, .9)]
        for seed, quantile in suffixes:
            key = model_key("FINAL", family, cfg, seed=seed, quantile=quantile)
            path = HERE / "models" / f"{key}{'.pt' if family == 'MLP' else '.joblib'}"
            if not path.exists():
                raise RuntimeError(f"FINAL_MODEL_NOT_FROZEN:{key}")
            prediction = predict_saved(path, family, x, cfg)
            if len(prediction) != len(train) or not np.isfinite(prediction).all():
                raise RuntimeError(f"FINAL_INSAMPLE_PREDICTION_INVALID:{key}")
            out = train[["signal_date", "ticker", "experiment_security_key",
                         "gross_return_decimal", "up_label"]].copy()
            out["prediction"] = prediction
            out["model_key"] = key
            out.to_parquet(output_dir / f"{key}.parquet", index=False)
            saved += 1
    print(json.dumps({"prediction_files": saved, "rows_per_file": len(train),
                      "status": "FINAL_FITTED_IN_ONLY_NOT_OOF"}))


if __name__ == "__main__":
    main()
