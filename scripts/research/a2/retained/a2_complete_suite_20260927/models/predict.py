"""Read-only frozen model adapters. No training or market data file reads."""
from __future__ import annotations
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PREDICTIVE_NAMES = ("ridge", "elastic_net", "hgb", "mlp", "logistic", "q10", "q50", "q90", "pca_ridge")


@lru_cache(maxsize=1)
def registry():
    return json.loads((HERE / "model_registry.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=16)
def load_model(name):
    record = registry()["models"][name]
    path = Path(record["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], f"ARTIFACT_CHANGED:{name}"
    if path.suffix == ".pt":
        import torch
        return torch.load(path, map_location="cpu", weights_only=True)
    return joblib.load(path)


def _values(frame, one_day=False):
    features = registry()["feature_order"]
    if not {"signal_date", "ticker", *features}.issubset(frame.columns):
        raise ValueError("Missing identity or frozen feature columns")
    if frame.empty or frame[["signal_date", "ticker"]].isna().any().any() or frame.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("Empty panel, missing identities or duplicate decision keys")
    if one_day and (frame.signal_date.nunique() != 1 or len(frame) < 20):
        raise ValueError("State/RL adapter requires one full eligible day with at least 20 candidates")
    values = frame[features].to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite frozen features")
    return values


def predict_panel(frame):
    """Preserve input keys/order and return nine frozen prediction columns.

    Probabilities are ranking scores, not returns. Quantiles are raw estimator
    outputs; callers may sort the three knots for a distribution readout but
    must not relabel the median or quantile average as expected return.
    """
    values = _values(frame)
    result = frame[["signal_date", "ticker"]].copy()
    for name in PREDICTIVE_NAMES:
        model = load_model(name)
        result[name] = model.predict_proba(values)[:, 1] if name == "logistic" else model.predict(values)
    assert np.isfinite(result[list(PREDICTIVE_NAMES)].to_numpy(float)).all()
    return result


def _state(day):
    values = _values(day, one_day=True)
    return np.r_[np.median(values, axis=0), np.quantile(values, .75, axis=0) - np.quantile(values, .25, axis=0), len(day)].reshape(1, -1)


def predict_state(day):
    """Frozen state diagnostics; lower anomaly_score indicates more unusual."""
    state = _state(day)
    anomaly = load_model("anomaly")
    return {"cluster_id": int(load_model("cluster").predict(state)[0]),
            "anomaly_score": float(anomaly.decision_function(state)[0]),
            "anomaly_flag": bool(anomaly.predict(state)[0] == -1)}


def score_rl(day, previous_target_names=None):
    """Frozen sequential TOP20 ranking, using previous target membership."""
    values = _values(day, one_day=True)
    policy = load_model("rl_policy")
    assert list(policy["feature_order"]) == registry()["feature_order"]
    transformed = np.clip(load_model("rl_scaler").transform(values), -10, 10)
    held = day.ticker.astype(str).isin(previous_target_names or set()).to_numpy(float)
    weight = policy["weight"].numpy().astype(float)
    result = day[["signal_date", "ticker"]].copy()
    result["rl"] = np.column_stack([transformed, held]) @ weight
    result = result.sort_values(["rl", "ticker"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    result["rank"] = np.arange(1, len(result) + 1, dtype=np.int32)
    return result


policy_rank_full_pre2026 = score_rl
