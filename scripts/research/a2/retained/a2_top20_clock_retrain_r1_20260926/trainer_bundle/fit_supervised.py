"""Shared bounded supervised fits on the isolated pre-2026 panel."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, mean_pinball_loss
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from prepare import FEATURES, ROOT

SEEDS = (2026092501, 2026092502)
FOLDS = (("2024", pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")),
         ("2025", pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01")))
END = pd.Timestamp("2026-01-01")
SPECS = ("RIDGE", "ELASTIC", "LOGISTIC", "HGB", "MLP", "Q10", "Q50", "Q90")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_for(name: str, seed: int):
    if name == "RIDGE":
        core = Ridge(alpha=100.0)
    elif name == "ELASTIC":
        core = ElasticNet(alpha=.005, l1_ratio=.35, max_iter=2000, tol=1e-5, random_state=seed)
    elif name == "LOGISTIC":
        core = LogisticRegression(C=.3, max_iter=300, random_state=seed)
    elif name == "HGB":
        core = HistGradientBoostingRegressor(max_iter=140, max_leaf_nodes=15, min_samples_leaf=100,
                                             learning_rate=.04, l2_regularization=10.0,
                                             early_stopping=False, random_state=seed)
    elif name == "MLP":
        core = MLPRegressor(hidden_layer_sizes=(64, 32), activation="relu", solver="adam",
                            alpha=.03, learning_rate_init=.0007, batch_size=256,
                            max_iter=140, n_iter_no_change=25, early_stopping=False,
                            shuffle=True, random_state=seed, tol=1e-5)
    elif name in {"Q10", "Q50", "Q90"}:
        q = {"Q10": .1, "Q50": .5, "Q90": .9}[name]
        core = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=120,
                                             max_leaf_nodes=15, min_samples_leaf=100,
                                             learning_rate=.04, l2_regularization=10.0,
                                             early_stopping=False, random_state=seed)
    else:
        raise ValueError(name)
    return Pipeline([("impute", SimpleImputer(strategy="median")),
                     ("scale", StandardScaler()), ("model", core)])


def daily_ic(frame: pd.DataFrame, column: str) -> float:
    values = []
    for _, day in frame.groupby("signal_date"):
        good = day.loc[day.y5.notna() & day[column].notna()]
        if len(good) >= 8 and good[column].nunique() > 1 and good.y5.nunique() > 1:
            values.append(float(spearmanr(good[column], good.y5).statistic))
    return float(np.mean(values)) if values else float("nan")


def run() -> None:
    if os.environ.get("R1_VERIFIED_ISOLATION") != "1":
        raise RuntimeError("ISOLATED_RUNTIME_REQUIRED")
    manifest = json.loads((ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    if digest(ROOT / "data" / "panel.parquet") != manifest["panel_sha256"]:
        raise RuntimeError("PRE2026_PANEL_CHANGED")
    if (ROOT / "pre2026_oof.parquet").exists():
        raise RuntimeError("SUPERVISED_ALREADY_RUN")
    panel = pd.read_parquet(ROOT / "data" / "panel.parquet")
    assert panel.signal_date.max() < END and set(FEATURES).issubset(panel.columns)
    assert not any("target" in name or name.startswith("y") or "future" in name for name in FEATURES)
    mature = (panel.label_end_date_5.notna() & np.isfinite(panel.y5)
              & np.isfinite(panel.y5_cost_positive))
    if not panel.loc[mature, "y5_cost_positive"].isin([0., 1.]).all():
        raise RuntimeError("CLASS_LABEL_OUTSIDE_BINARY_DOMAIN")
    if not ((panel.loc[mature, "y5"] > .001).to_numpy()
            == panel.loc[mature, "y5_cost_positive"].to_numpy(bool)).all():
        raise RuntimeError("CLASS_LABEL_RETURN_MISMATCH")
    (ROOT / "models").mkdir(exist_ok=True)
    trial_rows = []
    prediction_frames = []
    artifacts = {}
    for fold, start, stop in (*FOLDS, ("FINAL", END, END)):
        train = panel.loc[panel.signal_date.lt(start) & panel.label_end_date_5.lt(start)
                          & mature].copy()
        valid = None if fold == "FINAL" else panel.loc[panel.signal_date.ge(start) & panel.signal_date.lt(stop)].copy()
        if train.empty or train.label_end_date_5.max() >= start:
            raise RuntimeError(f"FOLD_MATURITY_FAILURE:{fold}")
        if valid is not None:
            scored = valid[["signal_date", "ticker", "security_id", "raw_rank", "raw_score", "entry_date",
                            "label_end_date_5", "y5", "label_status"]].copy()
            scored["fold"] = fold
        for name in SPECS:
            for seed in (SEEDS if name == "MLP" else SEEDS[:1]):
                tick = time.time()
                model = model_for(name, seed)
                label = train.y5_cost_positive if name == "LOGISTIC" else train.y5
                model.fit(train[FEATURES], label)
                core = model.named_steps["model"]
                if valid is not None:
                    prediction = (model.predict_proba(valid[FEATURES])[:, 1] if name == "LOGISTIC"
                                  else model.predict(valid[FEATURES]))
                    col = f"pred_{name.lower()}" + (f"_{seed}" if name == "MLP" else "")
                    scored[col] = prediction
                    known = (valid.label_end_date_5.lt(stop) & np.isfinite(valid.y5)
                             & np.isfinite(valid.y5_cost_positive))
                    if name == "LOGISTIC":
                        y = valid.loc[known, "y5_cost_positive"].to_numpy(float)
                        p = np.clip(prediction[known.to_numpy()], 1e-6, 1 - 1e-6)
                        metrics = {"log_loss": float(log_loss(y, p)), "brier": float(brier_score_loss(y, p)),
                                   "event_rate": float(y.mean()), "predicted_rate": float(p.mean())}
                    elif name.startswith("Q"):
                        y = valid.loc[known, "y5"].to_numpy(float)
                        p = prediction[known.to_numpy()]
                        q = {"Q10": .1, "Q50": .5, "Q90": .9}[name]
                        metrics = {"pinball": float(mean_pinball_loss(y, p, alpha=q)),
                                   "empirical_below": float(np.mean(y <= p))}
                    else:
                        y = valid.loc[known, "y5"].to_numpy(float)
                        p = prediction[known.to_numpy()]
                        metrics = {"mae": float(np.mean(np.abs(y - p))), "daily_ic": daily_ic(scored, col)}
                else:
                    path = ROOT / "models" / f"{name.lower()}_{seed}.joblib"
                    joblib.dump(model, path, compress=3)
                    artifacts[f"{name}_{seed}"] = {"path": str(path.relative_to(ROOT)), "sha256": digest(path),
                                                  "train_rows": len(train), "train_max_signal": str(train.signal_date.max()),
                                                  "train_max_label_end": str(train.label_end_date_5.max())}
                    metrics = {}
                diagnostic = {}
                if name == "MLP":
                    diagnostic = {"iterations": int(core.n_iter_),
                                  "initial_train_loss": float(core.loss_curve_[0]),
                                  "last_train_loss": float(core.loss_curve_[-1]),
                                  "weight_bias_parameter_count": int(sum(w.size for w in core.coefs_) + sum(b.size for b in core.intercepts_))}
                    if diagnostic["initial_train_loss"] <= diagnostic["last_train_loss"]:
                        raise RuntimeError("MLP_NO_TRAINING_PROGRESS")
                trial_rows.append({"fold": fold, "model": name, "seed": seed, "status": "FIT_COMPLETE",
                                   "train_rows": len(train), "train_dates": train.signal_date.nunique(),
                                   "train_max_signal": train.signal_date.max(),
                                   "train_max_label_end": train.label_end_date_5.max(),
                                   "valid_rows": 0 if valid is None else len(valid),
                                   "valid_dates": 0 if valid is None else valid.signal_date.nunique(),
                                   "fit_seconds": time.time() - tick, **metrics, **diagnostic})
                print(f"FIT {fold} {name} seed={seed} seconds={time.time()-tick:.1f}", flush=True)
        if valid is not None:
            scored["pred_mlp_mean"] = 0.5 * (scored[f"pred_mlp_{SEEDS[0]}"] + scored[f"pred_mlp_{SEEDS[1]}"])
            scored["quantile_crossing"] = (scored.pred_q10.gt(scored.pred_q50) | scored.pred_q50.gt(scored.pred_q90))
            prediction_frames.append(scored)
    oof = pd.concat(prediction_frames, ignore_index=True)
    oof.to_parquet(ROOT / "pre2026_oof.parquet", index=False)
    trials = pd.DataFrame(trial_rows)
    trials.to_csv(ROOT / "supervised_trials.csv", index=False)
    report = {"status": "ALL_SUPERVISED_FITS_COMPLETE", "fit_count": len(trials),
              "train_cutoff_exclusive": "2026-01-01", "folds": [f[0] for f in FOLDS],
              "features": FEATURES, "target": "next XNYS open to open five sessions later gross price-coordinate return",
              "classification": "y5>0.001 gross return; 10bp complete buy/sell cost",
              "quantiles": [.1, .5, .9], "quantile_crossing_oof_rows": int(oof.quantile_crossing.sum()),
              "quantile_crossing_oof_fraction": float(oof.quantile_crossing.mean()),
              "artifacts": artifacts, "oof_sha256": digest(ROOT / "pre2026_oof.parquet"),
              "trials_sha256": digest(ROOT / "supervised_trials.csv"),
              "input_sha256": manifest["panel_sha256"], "model_selection_uses_2026": False}
    (ROOT / "supervised_manifest.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"SUPERVISED_COMPLETE fits={len(trials)} oof_rows={len(oof)}")


if __name__ == "__main__":
    run()
