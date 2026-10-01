"""Fresh method fits against the frozen A2 matrix; never writes into A2."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SOURCE = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
PRODUCER = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_r1_nonlinear_cross_sectional_modeling.py")
HGB_SOURCE = Path(r"D:\us-tech-quant\scripts\v22\abcde_a2_nonlinear_alpha_baseline_r1.py")
HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FEATURES = (
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120",
    "ma10_vs_ma20", "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d",
    "realized_vol_20d", "realized_vol_60d", "downside_vol_20d", "upside_vol_20d",
    "distance_from_high_20d", "distance_from_high_60d", "distance_from_low_20d",
    "distance_from_low_60d", "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d",
    "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
)
HGB = dict(loss="squared_error", learning_rate=0.05, max_iter=200, max_leaf_nodes=15,
           max_depth=3, min_samples_leaf=200, l2_regularization=1.0,
           early_stopping=False, random_state=20260816)
SPECS = {
    "hgb": {"class": "HistGradientBoostingRegressor", "parameters": HGB},
    "ridge": {"class": "Ridge", "parameters": {"alpha": 10.0, "fit_intercept": True, "max_iter": 10000, "solver": "lsqr", "tol": 1e-6}, "internal_representation": "StandardScaler fitted on training rows only"},
    "elastic_net": {"class": "ElasticNet", "parameters": {"alpha": 0.001, "l1_ratio": 0.5, "fit_intercept": True, "max_iter": 3000, "tol": 1e-4, "selection": "cyclic", "random_state": 20260816}, "internal_representation": "StandardScaler fitted on training rows only"},
    "mlp": {"class": "MLPRegressor", "parameters": {"hidden_layer_sizes": [32], "activation": "relu", "solver": "adam", "alpha": 1.0, "batch_size": 512, "learning_rate_init": 0.001, "max_iter": 100, "tol": 1e-4, "n_iter_no_change": 10, "early_stopping": False, "shuffle": True, "random_state": 20260816}, "internal_representation": "StandardScaler fitted on training rows only"},
    "quantile_50_diagnostic": {"class": "HistGradientBoostingRegressor", "parameters": {**HGB, "loss": "quantile", "quantile": 0.5}, "learning_object": "conditional median of original continuous target; no strategy mapping frozen"},
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, default=str, allow_nan=False), encoding="utf-8")


def model_for(name: str):
    if name == "hgb":
        return HistGradientBoostingRegressor(**HGB)
    if name == "ridge":
        return make_pipeline(StandardScaler(), Ridge(**SPECS[name]["parameters"]))
    if name == "elastic_net":
        return make_pipeline(StandardScaler(), ElasticNet(**SPECS[name]["parameters"]))
    if name == "mlp":
        p = dict(SPECS[name]["parameters"])
        p["hidden_layer_sizes"] = tuple(p["hidden_layer_sizes"])
        return make_pipeline(StandardScaler(), MLPRegressor(**p))
    if name == "quantile_50_diagnostic":
        return HistGradientBoostingRegressor(**SPECS[name]["parameters"])
    raise ValueError(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("method", choices=list(SPECS))
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    source_paths = [SOURCE / "A2/training_matrix.parquet", SOURCE / "A2/oof_predictions.parquet", SOURCE / "A/score_rank_ledger.parquet", PRODUCER, HGB_SOURCE]
    hashes = {str(p): sha(p) for p in source_paths}
    frozen = json.loads((SOURCE / "audit/frozen_contracts_before_outcome_read.json").read_text(encoding="utf-8"))
    assert frozen["HGB_CONFIG"] == HGB
    spec = importlib.util.spec_from_file_location("original_a2_producer", PRODUCER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert tuple(module.FEATURE_COLUMNS) == FEATURES
    matrix = pd.read_parquet(source_paths[0]).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    oof_ref = pd.read_parquet(source_paths[1])
    full = pd.read_parquet(source_paths[2], columns=["signal_date", "ticker", *FEATURES])
    assert len(matrix) == 520328 and not matrix.duplicated(["signal_date", "ticker"]).any()
    assert np.isfinite(matrix.loc[:, FEATURES].to_numpy(float)).all()
    assert matrix.target.notna().all() and matrix.target_end_date.lt("2026-01-01").all()
    assert matrix.merge(full, on=["signal_date", "ticker"], suffixes=("", "_full"), validate="one_to_one").shape[0] == len(matrix)
    assert np.array_equal(matrix.loc[:, FEATURES].to_numpy(float), full.merge(matrix[["signal_date", "ticker"]], on=["signal_date", "ticker"], validate="one_to_one").sort_values(["signal_date", "ticker"], kind="mergesort").loc[:, FEATURES].to_numpy(float))
    full = full.loc[full.signal_date.dt.year.isin([2023, 2024, 2025])].copy()
    key_ref = oof_ref[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    key_full = full[["signal_date", "ticker"]].sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert key_ref.equals(key_full)
    method = args.method
    method_dir = OUT / method
    method_dir.mkdir(exist_ok=True)
    write_json(OUT / "common_frozen.json", {"source_sha256": hashes, "frozen_contract": frozen, "feature_order": FEATURES,
        "same_sample_weight": "unit weights; original fit omitted sample_weight", "same_missing_mask": "all training and evaluation features finite",
        "method_specs": SPECS, "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__}})
    all_preds = []
    fit_logs = []
    for stage, year in module.STAGES:
        # stage_rows is the original purge and maturity gate. It sees only the frozen labeled matrix.
        training, _, audit = module.stage_rows(matrix, year)
        evaluation = full.loc[full.signal_date.dt.year.eq(year)].sort_values(["signal_date", "ticker"], kind="mergesort").copy()
        model = model_for(method)
        start = time.monotonic()
        model.fit(training.loc[:, FEATURES].to_numpy(float), training.target.to_numpy(float))
        duration = time.monotonic() - start
        pred = model.predict(evaluation.loc[:, FEATURES].to_numpy(float))
        assert np.isfinite(pred).all()
        evaluation["prediction"] = pred
        evaluation["rank"] = module._prediction_rank(evaluation, "prediction")
        evaluation["stage"] = stage
        all_preds.append(evaluation[["signal_date", "ticker", "stage", "prediction", "rank"]])
        artifact = method_dir / f"{stage.lower()}_{year}.joblib"
        joblib.dump(model, artifact, compress=3)
        fit_logs.append({**audit, "stage": stage, "method": method, "fit_count": 1, "fit_seconds": duration,
                         "train_tickers": int(training.ticker.nunique()), "evaluation_tickers": int(evaluation.ticker.nunique()),
                         "model_sha256": sha(artifact), "model_path": str(artifact), "fit_utc": datetime.now(timezone.utc).isoformat(),
                         "iterations": getattr(model[-1] if hasattr(model, "steps") else model, "n_iter_", None)})
        write_json(method_dir / "fit_log.json", fit_logs)
        print(method, stage, "fit", round(duration, 2), "sec", flush=True)
    preds = pd.concat(all_preds, ignore_index=True).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    assert preds[["signal_date", "ticker"]].equals(key_ref)
    preds.to_parquet(method_dir / "pre2026_oof.parquet", index=False)
    comparison = preds.merge(oof_ref[["signal_date", "ticker", "target", "a2_prediction", "a2_rank"]], on=["signal_date", "ticker"], validate="one_to_one")
    comparison["squared_error"] = (comparison.prediction - comparison.target) ** 2
    comparison["absolute_error"] = (comparison.prediction - comparison.target).abs()
    metrics = {}
    for stage, g in comparison.groupby("stage"):
        labeled = g[g.target.notna()]
        top = g[g["rank"].le(20)].merge(oof_ref.loc[oof_ref.a2_rank.le(20), ["signal_date", "ticker"]].assign(original_top=True), on=["signal_date", "ticker"], how="left")
        metrics[stage] = {"evaluation_rows": len(g), "labeled_rows": len(labeled), "dates": g.signal_date.nunique(), "tickers": g.ticker.nunique(),
                          "mse": float(labeled.squared_error.mean()), "mae": float(labeled.absolute_error.mean()),
                          "top20_overlap_daily_mean": float(top.original_top.fillna(False).groupby(top.signal_date).sum().mean())}
        if method == "hgb":
            metrics[stage]["old_a2_max_abs_prediction_difference"] = float((g.prediction - g.a2_prediction).abs().max())
            metrics[stage]["old_a2_rank_mismatch_rows"] = int((g["rank"] != g.a2_rank).sum())
    write_json(method_dir / "pre2026_metrics.json", metrics)
    final = model_for(method)
    start = time.monotonic()
    final.fit(matrix.loc[:, FEATURES].to_numpy(float), matrix.target.to_numpy(float))
    artifact = method_dir / "final_full_pre2026.joblib"
    joblib.dump(final, artifact, compress=3)
    fit_logs.append({"stage": "FULL_PRE2026", "method": method, "fit_count": 1, "fit_seconds": time.monotonic() - start,
                     "train_rows": len(matrix), "train_tickers": matrix.ticker.nunique(), "model_sha256": sha(artifact),
                     "model_path": str(artifact), "fit_utc": datetime.now(timezone.utc).isoformat(),
                     "iterations": getattr(final[-1] if hasattr(final, "steps") else final, "n_iter_", None)})
    write_json(method_dir / "fit_log.json", fit_logs)
    print(method, "FULL_PRE2026 complete", flush=True)


if __name__ == "__main__":
    main()
