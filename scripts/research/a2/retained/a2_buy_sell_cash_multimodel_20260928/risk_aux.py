"""New stage-isolated risk fits and diagnostic-only clustering/anomaly models."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import joblib
import numpy as np
import pandas as pd
from scipy.linalg import eigh
import sklearn
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "risk_artifacts"
PRICE_SOURCE = ROOT / "a2_strict_method_retrain_20260926/results/pre2026_original_price_coordinate.parquet"
FEATURE_SOURCE = ROOT / "a2_latest_effective_joint_20260927/data/pre2026_joint_context.parquet"
FEATURE_MANIFEST = ROOT / "a2_latest_effective_joint_20260927/data/JOINT_DATA_AUDIT.json"
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
SEED = 20260928
UNKNOWN_DAILY_VOL = .08
MINIMUM_DAILY_VOL = .01


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def feature_names():
    return json.loads(FEATURE_MANIFEST.read_text(encoding="utf-8"))["features"]


def sample_by_key(frame, cutoff, limit=20000):
    """Sample only signal/ticker keys; no outcome, price, or test-dependent choices."""
    eligible = frame.loc[frame.signal_date.lt(cutoff)].copy()
    if eligible.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("DUPLICATE_DIAGNOSTIC_KEYS")
    key = eligible.signal_date.dt.strftime("%Y-%m-%d") + "|" + eligible.ticker.astype(str)
    eligible["sample_hash"] = [hashlib.sha256(k.encode("utf-8")).hexdigest() for k in key]
    return eligible.sort_values(["sample_hash", "signal_date", "ticker"], kind="stable").head(limit)


def returns_before(prices, cutoff):
    prior = prices.loc[prices.trade_date.lt(cutoff)]
    if prior.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("DUPLICATE_PRICE_KEYS")
    wide = prior.pivot(index="trade_date", columns="ticker", values="close").sort_index().tail(253)
    if len(wide) != 253:
        raise ValueError("RISK_WINDOW_TOO_SHORT")
    returns = wide.pct_change(fill_method=None).iloc[1:]
    returns = returns.where(np.isfinite(returns))
    returns = returns.loc[:, returns.notna().sum().ge(200)]
    if len(returns.columns) < 5:
        raise ValueError("RISK_SECURITIES_TOO_FEW")
    return returns


def fit_stage(stage, prices, features, columns, source_hashes):
    cutoff = STAGES[stage]
    dest = OUT / stage
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "PRE_FIT_CONTRACT.json").exists():
        raise RuntimeError(f"EXISTING_FIT_PRESERVED: {dest}")
    returns = returns_before(prices, cutoff)
    sampled = sample_by_key(features, cutoff)
    assert returns.index.max() < pd.Timestamp(cutoff)
    assert sampled.signal_date.max() < pd.Timestamp(cutoff)
    values = sampled[columns].to_numpy(float)
    assert np.isfinite(values).all()
    sample_keys = sampled[["signal_date", "ticker", "sample_hash"]].reset_index(drop=True)
    sample_keys.to_csv(dest / "diagnostic_sample_keys.csv", index=False)
    contract = {
        "stage": stage, "cutoff_exclusive": cutoff,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hashes,
        "producer_sha256": sha(Path(__file__)),
        "feature_order": columns,
        "risk": {"return_rows": len(returns), "securities": len(returns.columns),
                 "return_first": str(returns.index.min().date()),
                 "return_last": str(returns.index.max().date()),
                 "minimum_return_observations": 200, "tail_price_dates": 253,
                 "risk_only_return_clip": [-.5, .5], "factors": 5,
                 "minimum_daily_vol": MINIMUM_DAILY_VOL,
                 "unknown_daily_vol": UNKNOWN_DAILY_VOL,
                 "missing_method": "standardized missing returns imputed zero; shrunk correlation diagonal renormalized"},
        "diagnostics": {"sample_rows": len(sampled), "max_sample_rows": 20000,
                        "sample_first": str(sampled.signal_date.min().date()),
                        "sample_last": str(sampled.signal_date.max().date()),
                        "sample_signal_days": int(sampled.signal_date.nunique()),
                        "sample_rule": "smallest SHA256(YYYY-MM-DD|ticker), deterministic, no outcome access",
                        "sample_key_sha256": sha(dest / "diagnostic_sample_keys.csv"),
                        "clusters": 5, "kmeans_n_init": 10,
                        "isolation_trees": 100, "isolation_contamination": .02,
                        "isolation_max_samples": 256,
                        "seed": SEED, "purpose": "diagnostic_only_no_trading_veto"},
        "fit_2026_rows": 0, "reads_2026_data": False,
        "price_coordinate": "affine adjusted research index; not certified shareholder total return",
    }
    write(dest / "PRE_FIT_CONTRACT.json", contract)
    started = time.monotonic()
    raw = returns.to_numpy(float)
    clipped = np.clip(raw, -.5, .5)
    means = np.nanmean(clipped, axis=0)
    vol = np.maximum(np.nanstd(clipped, axis=0, ddof=1), MINIMUM_DAILY_VOL)
    standardized = np.nan_to_num((clipped - means) / vol, nan=0.)
    with threadpool_limits(limits=2):
        lw = LedoitWolf().fit(standardized)
        scale = np.sqrt(np.diag(lw.covariance_))
        corr = lw.covariance_ / np.outer(scale, scale)
        cov = corr * np.outer(vol, vol)
        cov = (cov + cov.T) * .5
        n = len(vol)
        factor_values, factor_loadings = eigh(cov, subset_by_index=[n - 5, n - 1])
        common = (factor_loadings * factor_values) @ factor_loadings.T
        residual = np.maximum(np.diag(cov - common), 1e-8)
        factor = common + np.diag(residual)
        np.linalg.cholesky(cov)
        np.linalg.cholesky(factor)
        scaler = StandardScaler().fit(values)
        scaled = scaler.transform(values)
        clusters = KMeans(n_clusters=5, n_init=10, random_state=SEED).fit(scaled)
        anomaly = IsolationForest(n_estimators=100, contamination=.02,
                                  max_samples=256, random_state=SEED, n_jobs=1).fit(scaled)
    np.savez_compressed(dest / "frozen_covariance.npz", tickers=returns.columns.to_numpy(str),
                        covariance=cov, factor_covariance=factor,
                        factor_loadings=factor_loadings, factor_variances=factor_values,
                        residual_variance=residual)
    joblib.dump({"scaler": scaler, "cluster": clusters, "anomaly": anomaly,
                 "features": columns, "stage": stage, "cutoff_exclusive": cutoff},
                dest / "diagnostics.joblib", compress=3)
    scores = anomaly.decision_function(scaled)
    assert np.isfinite(scores).all()
    receipt = {**contract, "status": "PASS", "fit_seconds": time.monotonic() - started,
               "model_fit_calls": 3, "scaler_fit_calls": 1, "factor_decompositions": 1,
               "shrinkage": float(lw.shrinkage_),
               "factor_variance_share": float(factor_values.sum() / np.trace(cov)),
               "risk_clipped_cells": int((np.abs(raw) > .5).sum()),
               "risk_missing_cells": int(np.isnan(raw).sum()),
               "training_anomaly_count": int((anomaly.predict(scaled) == -1).sum()),
               "cluster_counts": {str(i): int((clusters.labels_ == i).sum()) for i in range(5)},
               "source_files_unchanged": all(sha(path) == value for path, value in source_hashes.items()),
               "artifacts_sha256": {name: sha(dest / name) for name in
                                    ["frozen_covariance.npz", "diagnostics.joblib", "diagnostic_sample_keys.csv"]},
               "python": platform.python_version(), "sklearn": sklearn.__version__}
    assert receipt["source_files_unchanged"]
    write(dest / "TRAIN_RECEIPT.json", receipt)
    print(json.dumps({k: receipt[k] for k in ["stage", "status", "cutoff_exclusive", "fit_seconds",
                                             "model_fit_calls", "scaler_fit_calls", "factor_decompositions"]}), flush=True)
    return receipt


def load_receipt(stage):
    if stage not in STAGES:
        raise ValueError(f"UNKNOWN_STAGE: {stage}")
    dest = OUT / stage
    receipt = json.loads((dest / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
    if receipt["stage"] != stage or receipt["cutoff_exclusive"] != STAGES[stage]:
        raise ValueError("RISK_STAGE_RECEIPT_MISMATCH")
    for name, expected in receipt["artifacts_sha256"].items():
        if sha(dest / name) != expected:
            raise ValueError(f"FROZEN_ARTIFACT_HASH_MISMATCH: {name}")
    return dest, receipt


class FrozenRisk:
    def __init__(self, stage="final"):
        dest, self.receipt = load_receipt(stage)
        self.stage = stage
        with np.load(dest / "frozen_covariance.npz", allow_pickle=False) as data:
            self.lookup = {str(t): i for i, t in enumerate(data["tickers"])}
            self.cov = data["covariance"].copy()
            self.factor = data["factor_covariance"].copy()

    def covariance_for(self, names, factor=False):
        names = [str(name) for name in names]
        source = self.factor if factor else self.cov
        result = np.eye(len(names)) * UNKNOWN_DAILY_VOL ** 2
        pairs = [(i, self.lookup[t]) for i, t in enumerate(names) if t in self.lookup]
        if pairs:
            ix, src = zip(*pairs)
            result[np.ix_(ix, ix)] = source[np.ix_(src, src)]
        return result


class FrozenDiagnostics:
    def __init__(self, stage="final"):
        dest, self.receipt = load_receipt(stage)
        self.stage = stage
        self.bundle = joblib.load(dest / "diagnostics.joblib")
        if self.bundle["stage"] != stage or self.bundle["cutoff_exclusive"] != STAGES[stage]:
            raise ValueError("DIAGNOSTIC_STAGE_MISMATCH")

    def predict(self, frame):
        values = frame[self.bundle["features"]].to_numpy(float)
        if not np.isfinite(values).all():
            raise ValueError("NONFINITE_DIAGNOSTIC_FEATURES")
        if len(values) == 0:
            return pd.DataFrame(columns=["cluster", "anomaly_score", "is_anomaly"], index=frame.index)
        scaled = self.bundle["scaler"].transform(values)
        with threadpool_limits(limits=2):
            labels = self.bundle["cluster"].predict(scaled)
            scores = self.bundle["anomaly"].decision_function(scaled)
        return pd.DataFrame({"cluster": labels, "anomaly_score": scores,
                             "is_anomaly": scores < 0}, index=frame.index)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["all", *STAGES], default="all")
    args = parser.parse_args()
    columns = feature_names()
    prices = pd.read_parquet(PRICE_SOURCE, columns=["ticker", "trade_date", "close"])
    features = pd.read_parquet(FEATURE_SOURCE, columns=["signal_date", "ticker", *columns])
    assert prices.trade_date.notna().all() and prices.trade_date.lt("2026-01-01").all()
    assert features.signal_date.notna().all() and features.signal_date.lt("2026-01-01").all()
    source_hashes = {str(path): sha(path) for path in [PRICE_SOURCE, FEATURE_SOURCE, FEATURE_MANIFEST]}
    stages = STAGES if args.stage == "all" else [args.stage]
    receipts = [fit_stage(stage, prices, features, columns, source_hashes) for stage in stages]
    if args.stage == "all":
        write(OUT / "TRAIN_RECEIPT.json", {"status": "PASS", "stages": list(STAGES),
              "model_fit_calls": sum(x["model_fit_calls"] for x in receipts),
              "scaler_fit_calls": sum(x["scaler_fit_calls"] for x in receipts),
              "factor_decompositions": sum(x["factor_decompositions"] for x in receipts),
              "fit_2026_rows": 0, "test_outcomes_read": False,
              "stage_receipts_sha256": {stage: sha(OUT / stage / "TRAIN_RECEIPT.json") for stage in STAGES}})


if __name__ == "__main__":
    main()
