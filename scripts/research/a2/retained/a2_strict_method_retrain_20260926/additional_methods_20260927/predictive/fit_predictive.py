"""Fit separately authorized pre-2026 classification and quantile diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


HERE = Path(__file__).resolve().parent
BASE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
MATRIX = BASE / "A2/training_matrix.parquet"
REFERENCE = BASE / "A2/oof_predictions.parquet"
FULL_FEATURES = BASE / "A/score_rank_ledger.parquet"
PRODUCER = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
FROZEN = BASE / "audit/frozen_contracts_before_outcome_read.json"
KEY = ["signal_date", "ticker"]
QUANTILES = (0.1, 0.5, 0.9)
HGB = dict(loss="quantile", learning_rate=0.05, max_iter=200,
           max_leaf_nodes=15, max_depth=3, min_samples_leaf=200,
           l2_regularization=1.0, early_stopping=False, random_state=20260816)
LOGISTIC = dict(C=1.0, class_weight=None, fit_intercept=True, max_iter=300,
                solver="lbfgs", tol=1e-4, random_state=20260816)
EXPECTED_MATRIX_SHA = "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def original_module():
    spec = importlib.util.spec_from_file_location("original_a2_producer_predictive", PRODUCER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_inputs():
    assert sha(MATRIX) == EXPECTED_MATRIX_SHA, "Original training matrix changed"
    assert sha(HERE / "PRE_FIT_CONTRACT.json"), "Missing pre-fit contract"
    original = original_module()
    features = list(original.FEATURE_COLUMNS)
    assert len(features) == 32
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    assert frozen["TARGET"] == "MEAN_ER_3D_5D_10D_20D"
    assert frozen["STAGES"] == [["DEVELOPMENT", 2023], ["CONFIRMATION", 2024], ["FINAL", 2025]]
    matrix = pd.read_parquet(MATRIX, columns=KEY + features + ["target", "target_end_date"])
    matrix = matrix.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert len(matrix) == 520328 and not matrix.duplicated(KEY).any()
    assert matrix.signal_date.min() == pd.Timestamp("2020-06-24")
    assert matrix.signal_date.max() == pd.Timestamp("2025-12-02")
    assert matrix.target_end_date.max() <= pd.Timestamp("2025-12-31")
    assert np.isfinite(matrix[features].to_numpy(float, copy=False)).all()
    assert np.isfinite(matrix.target.to_numpy(float, copy=False)).all()
    ref = pd.read_parquet(REFERENCE, columns=KEY + ["target", "split"])
    ref = ref.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    full = pd.read_parquet(FULL_FEATURES, columns=KEY + features)
    full = full.loc[full.signal_date.dt.year.isin([2023, 2024, 2025])]
    full = full.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert full[KEY].equals(ref[KEY]) and not full.duplicated(KEY).any()
    assert np.isfinite(full[features].to_numpy(float, copy=False)).all()
    # Labels remain NaN where the original horizon did not mature within 2025.
    assert not ref.loc[ref.target.notna(), "signal_date"].ge("2026-01-01").any()
    checks = {
        "matrix_sha256": sha(MATRIX), "reference_sha256": sha(REFERENCE),
        "full_feature_sha256": sha(FULL_FEATURES), "producer_sha256": sha(PRODUCER),
        "frozen_contract_sha256": sha(FROZEN),
        "prefit_contract_sha256": sha(HERE / "PRE_FIT_CONTRACT.json"),
        "train_rows": len(matrix), "train_dates": int(matrix.signal_date.nunique()),
        "train_tickers": int(matrix.ticker.nunique()),
        "train_signal_min": str(matrix.signal_date.min().date()),
        "train_signal_max": str(matrix.signal_date.max().date()),
        "train_target_end_max": str(matrix.target_end_date.max().date()),
        "evaluation_rows": len(full), "evaluation_dates": int(full.signal_date.nunique()),
        "evaluation_tickers": int(full.ticker.nunique()),
        "feature_order": features, "all_features_finite": True,
        "sample_weight": "unit, fit called without sample_weight",
        "source_target": frozen["TARGET"], "fit_2026_rows": 0,
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                        "pandas": pd.__version__, "numpy": np.__version__},
    }
    write_json(HERE / "INPUT_IDENTITY.json", checks)
    return original, features, matrix, full, ref


def fit_one(model, x: np.ndarray, y: np.ndarray, path: Path, record: dict):
    started = time.monotonic()
    model.fit(x, y)
    elapsed = time.monotonic() - started
    joblib.dump(model, path, compress=3)
    iterations = getattr(model[-1] if hasattr(model, "steps") else model, "n_iter_", 0)
    record.update({"fit_count": 1, "fit_seconds": elapsed,
                   "fit_utc": datetime.now(timezone.utc).isoformat(),
                   "model_path": str(path), "model_sha256": sha(path),
                   "n_iter": int(np.max(np.asarray(iterations)))})
    return record


def pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    error = y - pred
    return float(np.mean(np.maximum(q * error, (q - 1.0) * error)))


def run_logistic(original, features, matrix, full, ref):
    out = HERE / "logistic_positive_target"
    out.mkdir(exist_ok=True)
    logs = []
    predictions = []
    for stage, year in original.STAGES:
        train, _, audit = original.stage_rows(matrix, year)
        eval_mask = full.signal_date.dt.year.eq(year).to_numpy()
        evaluation = full.loc[eval_mask, KEY + features]
        y = (train.target.to_numpy(dtype=np.float64) > 0).astype(np.int8)
        assert set(np.unique(y)) == {0, 1}
        model = make_pipeline(StandardScaler(), LogisticRegression(**LOGISTIC))
        record = {**audit, "stage": stage, "year": year, "method": "logistic_positive_target",
                  "positive_rows": int(y.sum()), "negative_rows": int(len(y) - y.sum()),
                  "positive_rate": float(y.mean()), "evaluation_rows_full_pool": len(evaluation)}
        logs.append(fit_one(model, train[features].to_numpy(dtype=np.float64), y,
                            out / f"{stage.lower()}_{year}.joblib", record))
        prob = model.predict_proba(evaluation[features].to_numpy(dtype=np.float64))[:, 1]
        assert np.isfinite(prob).all() and ((prob >= 0) & (prob <= 1)).all()
        pred = evaluation[KEY].copy()
        pred["stage"] = stage
        pred["positive_probability"] = prob
        predictions.append(pred)
        write_json(out / "fit_log.json", logs)
        print("logistic", stage, "fit", round(record["fit_seconds"], 2), "seconds", flush=True)
    merged = pd.concat(predictions, ignore_index=True).sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert merged[KEY].equals(ref[KEY])
    merged.to_parquet(out / "pre2026_oof_probability.parquet", index=False)
    diagnostics = {}
    joined = merged.join(ref[["target"]])
    for stage, part in joined.groupby("stage", sort=False):
        labeled = part.loc[part.target.notna()]
        y = labeled.target.to_numpy(dtype=float) > 0
        p = labeled.positive_probability.to_numpy(dtype=float)
        diagnostics[stage] = {"learning_object": "P(original continuous target > 0)",
                              "evaluation_rows_full_pool": len(part), "labeled_rows": len(labeled),
                              "evaluation_dates": int(part.signal_date.nunique()),
                              "positive_rate": float(y.mean()),
                              "brier": float(brier_score_loss(y, p)),
                              "log_loss": float(log_loss(y, p, labels=[False, True])),
                              "roc_auc": float(roc_auc_score(y, p))}
    write_json(out / "pre2026_validation.json", diagnostics)
    final_y = (matrix.target.to_numpy(dtype=np.float64) > 0).astype(np.int8)
    final = make_pipeline(StandardScaler(), LogisticRegression(**LOGISTIC))
    final_record = {"stage": "FULL_PRE2026", "method": "logistic_positive_target",
                    "train_rows": len(matrix), "train_tickers": int(matrix.ticker.nunique()),
                    "train_signal_max": str(matrix.signal_date.max().date()),
                    "train_target_end_max": str(matrix.target_end_date.max().date()),
                    "positive_rows": int(final_y.sum()), "negative_rows": int(len(final_y) - final_y.sum())}
    logs.append(fit_one(final, matrix[features].to_numpy(dtype=np.float64), final_y,
                        out / "final_full_pre2026.joblib", final_record))
    write_json(out / "fit_log.json", logs)
    return {"fit_count": len(logs), "model_hashes": [x["model_sha256"] for x in logs],
            "oof_sha256": sha(out / "pre2026_oof_probability.parquet")}


def run_distribution(original, features, matrix, full, ref):
    out = HERE / "distribution_quantile_function"
    out.mkdir(exist_ok=True)
    logs = []
    predictions = []
    for stage, year in original.STAGES:
        train, _, audit = original.stage_rows(matrix, year)
        evaluation = full.loc[full.signal_date.dt.year.eq(year), KEY + features]
        x = train[features].to_numpy(dtype=np.float64)
        y = train.target.to_numpy(dtype=np.float64)
        eval_x = evaluation[features].to_numpy(dtype=np.float64)
        pred = evaluation[KEY].copy()
        pred["stage"] = stage
        for q in QUANTILES:
            model = HistGradientBoostingRegressor(**HGB, quantile=q)
            qname = f"q{int(q * 100):02d}"
            record = {**audit, "stage": stage, "year": year, "method": "distribution_quantile_function",
                      "quantile": q, "evaluation_rows_full_pool": len(evaluation)}
            logs.append(fit_one(model, x, y, out / f"{stage.lower()}_{year}_{qname}.joblib", record))
            vals = model.predict(eval_x)
            assert np.isfinite(vals).all()
            pred[qname + "_raw"] = vals
            write_json(out / "fit_log.json", logs)
            print("quantile", stage, q, "fit", round(record["fit_seconds"], 2), "seconds", flush=True)
        raw = pred[["q10_raw", "q50_raw", "q90_raw"]].to_numpy(dtype=float)
        pred["crossing_before_sort"] = (raw[:, 0] > raw[:, 1]) | (raw[:, 1] > raw[:, 2])
        ordered = np.sort(raw, axis=1)
        pred[["q10", "q50", "q90"]] = ordered
        predictions.append(pred)
    oof = pd.concat(predictions, ignore_index=True).sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert oof[KEY].equals(ref[KEY])
    oof.to_parquet(out / "pre2026_oof_distribution.parquet", index=False)
    joined = oof.join(ref[["target"]])
    diagnostics = {}
    for stage, part in joined.groupby("stage", sort=False):
        labeled = part.loc[part.target.notna()]
        y = labeled.target.to_numpy(dtype=float)
        lo = labeled.q10.to_numpy(dtype=float)
        hi = labeled.q90.to_numpy(dtype=float)
        diagnostics[stage] = {
            "distribution_object": "piecewise linear inverse CDF between q10/q50/q90 with constant quantile tails",
            "evaluation_rows_full_pool": len(part), "labeled_rows": len(labeled),
            "evaluation_dates": int(part.signal_date.nunique()),
            "crossing_count_before_sort": int(part.crossing_before_sort.sum()),
            "crossing_rate_before_sort": float(part.crossing_before_sort.mean()),
            "pinball_raw": {f"q{int(q*100):02d}": pinball(y, labeled[f"q{int(q*100):02d}_raw"].to_numpy(dtype=float), q) for q in QUANTILES},
            "pinball_monotone": {f"q{int(q*100):02d}": pinball(y, labeled[f"q{int(q*100):02d}"].to_numpy(dtype=float), q) for q in QUANTILES},
            "central_80_coverage": float(((y >= lo) & (y <= hi)).mean()),
            "central_80_mean_width": float(np.mean(hi - lo)),
        }
    write_json(out / "pre2026_validation.json", diagnostics)
    final_x = matrix[features].to_numpy(dtype=np.float64)
    final_y = matrix.target.to_numpy(dtype=np.float64)
    for q in QUANTILES:
        model = HistGradientBoostingRegressor(**HGB, quantile=q)
        record = {"stage": "FULL_PRE2026", "method": "distribution_quantile_function",
                  "quantile": q, "train_rows": len(matrix), "train_tickers": int(matrix.ticker.nunique()),
                  "train_signal_max": str(matrix.signal_date.max().date()),
                  "train_target_end_max": str(matrix.target_end_date.max().date())}
        logs.append(fit_one(model, final_x, final_y,
                            out / f"final_full_pre2026_q{int(q*100):02d}.joblib", record))
        write_json(out / "fit_log.json", logs)
        print("quantile FULL_PRE2026", q, "fit", round(record["fit_seconds"], 2), "seconds", flush=True)
    return {"fit_count": len(logs), "model_hashes": [x["model_sha256"] for x in logs],
            "oof_sha256": sha(out / "pre2026_oof_distribution.parquet")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("method", choices=["logistic", "distribution", "all"])
    args = parser.parse_args()
    original, features, matrix, full, ref = load_inputs()
    summary = {"source": str(MATRIX), "source_sha256": sha(MATRIX),
               "prefit_contract_sha256": sha(HERE / "PRE_FIT_CONTRACT.json"),
               "2026_input_read": False, "2026_fit_count": 0, "methods": {}}
    if args.method in ("logistic", "all"):
        summary["methods"]["logistic"] = run_logistic(original, features, matrix, full, ref)
        write_json(HERE / "FIT_SUMMARY.json", summary)
    if args.method in ("distribution", "all"):
        summary["methods"]["distribution"] = run_distribution(original, features, matrix, full, ref)
        write_json(HERE / "FIT_SUMMARY.json", summary)


if __name__ == "__main__":
    main()
