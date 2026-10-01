"""Read-only D1/D2/V25 prediction and train-frozen diagnostic summaries."""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from fit_supervised import HERE, load_fold, scale
from policy_engine import selected_prediction


def summarize(fold: str) -> dict:
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["label_end_date"] = pd.to_datetime(panel.label_end_date)
    panel["label_available_at_utc"] = pd.to_datetime(panel.label_available_at_utc, utc=True)
    _, val = load_fold(panel, fold)
    if len(val) == 0:
        return {"fold": fold, "validation_rows": 0}
    y = val.gross_return_decimal.to_numpy(float)
    up = val.up_label.to_numpy(bool)
    up_float = up.astype(float)
    families = {}
    for family in ("RIDGE", "ELASTIC", "HGB", "MLP", "HGB_NO13F"):
        p = selected_prediction(fold, family)
        assert p.signal_date.tolist() == val.signal_date.tolist()
        assert p.experiment_security_key.tolist() == val.experiment_security_key.tolist()
        pred = p.prediction.to_numpy(float)
        families[family] = {"mse_decimal": float(np.mean((pred - y)**2)),
                            "mean_prediction_decimal": float(np.mean(pred))}
    logistic = selected_prediction(fold, "LOGISTIC")
    probability = logistic.prediction.to_numpy(float)
    assert logistic.signal_date.tolist() == val.signal_date.tolist()
    bins = np.minimum((probability * 5).astype(int), 4)
    families["LOGISTIC"] = {
        "brier": float(np.mean((probability - up)**2)),
        "log_loss": float(np.mean(-up_float * np.log(np.clip(probability, 1e-9, 1)) -
                                  (1 - up_float) * np.log(np.clip(1 - probability, 1e-9, 1)))),
        "fixed_probability_bins": [{"bin": i, "count": int((bins == i).sum()),
                                    "observed_up_rate": float(np.mean(up[bins == i])) if (bins == i).any() else None,
                                    "mean_forecast": float(np.mean(probability[bins == i])) if (bins == i).any() else None}
                                   for i in range(5)]}
    q = selected_prediction(fold, "QUANTILE")
    qraw = q[["q10", "q50", "q90"]].to_numpy(float)
    cross = (np.diff(qraw, axis=1) < 0).any(axis=1)
    ordered = np.sort(qraw, axis=1)
    families["QUANTILE"] = {"raw_cross_fraction": float(cross.mean()),
                            "interval_80_coverage": float(np.mean((y >= ordered[:, 0]) & (y <= ordered[:, 2]))),
                            "interval_width_decimal": float(np.mean(ordered[:, 2] - ordered[:, 0])),
                            "pinball_decimal": {str(prob): float(np.mean(np.maximum(prob * (y - qraw[:, i]),
                                                                (prob - 1) * (y - qraw[:, i]))))
                                                for i, prob in enumerate((.1, .5, .9))}}
    scaler = joblib.load(HERE / "models" / f"SCALER_{fold}.joblib")
    x = scale(val, scaler)
    cluster = joblib.load(HERE / "models" / f"KMEANS_{fold}.joblib").predict(x)
    anomaly = joblib.load(HERE / "models" / f"ISOLATION_{fold}.joblib").predict(x)
    hgb = selected_prediction(fold, "HGB").prediction.to_numpy(float)
    return {"fold": fold, "validation_rows": len(val), "validation_days": int(val.signal_date.nunique()),
            "families": families,
            "diagnostics": {"scaled_feature_abs_mean": float(np.abs(x).mean()),
                            "cluster": [{"id": i, "rows": int((cluster == i).sum()),
                                         "hgb_mse_decimal": float(np.mean((hgb[cluster == i] - y[cluster == i])**2))}
                                        for i in range(3)],
                            "anomaly_rows": int((anomaly == -1).sum()),
                            "anomaly_hgb_mse_decimal": float(np.mean((hgb[anomaly == -1] - y[anomaly == -1])**2))
                            if (anomaly == -1).any() else None}}


if __name__ == "__main__":
    result = {f: summarize(f) for f in ("D1", "D2")}
    if (HERE / "PRIMARY_SELECTION.json").exists() and (HERE / "predictions" / "V25_HGB_max_leaf_nodes7.parquet").exists():
        result["V25"] = summarize("V25")
    (HERE / "PREDICTION_DIAGNOSTICS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({f: {"rows": v["validation_rows"],
                          "quantile_coverage": v["families"]["QUANTILE"]["interval_80_coverage"]}
                      for f, v in result.items()}))
