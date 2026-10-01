"""Train-only correlation structures and auxiliary feature diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest

from fit_supervised import FEATURES, FOLDS, HERE, MODELS, load_fold, scale, scaler_for


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, obj: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(obj, tmp)
    os.replace(tmp, path)


def correlation(cov: np.ndarray) -> np.ndarray:
    diag = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    out = cov / np.outer(diag, diag)
    out = (out + out.T) / 2
    np.fill_diagonal(out, 1.0)
    assert np.linalg.eigvalsh(out).min() >= -1e-7
    return out


def fit_risk(fold: str, panel: pd.DataFrame, prices: pd.DataFrame) -> dict:
    cutoff = pd.Timestamp(FOLDS[fold][0])
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    usable_days = calendar[calendar <= cutoff]
    last121 = usable_days[-121:]
    assert len(last121) == 121
    seen = panel.loc[panel.signal_date.le(cutoff),
                     ["experiment_security_key", "ticker", "signal_date"]].drop_duplicates()
    assert not seen.empty
    transitions = {}
    # Development risk branches had zero usable-day matrix coverage and are
    # preserved byte-for-byte.  The conservative transition guard applies to
    # the not-yet-fitted V25/FINAL structures; no extra fit is authorized.
    for ticker, group in (seen.groupby("ticker") if fold in ("V25", "FINAL") else []):
        first_by_key = group.groupby("experiment_security_key").signal_date.min().sort_values()
        if len(first_by_key) > 1:
            # Only DNA/VSTM have this observed CUSIP transition.  Candidate
            # appearances are conservative evidence, not a backdated UID bridge.
            if ticker not in ("DNA", "VSTM") or len(first_by_key) != 2:
                raise RuntimeError(f"UNREVIEWED_SECURITY_TRANSITION:{ticker}")
            transitions[ticker] = (str(first_by_key.index[0]), str(first_by_key.index[1]),
                                   pd.Timestamp(first_by_key.iloc[1]))
    wide = prices.pivot(index="trade_date", columns="ticker", values="close").reindex(last121)
    columns = []
    keys = []
    excluded = []
    for security_key, group in seen.groupby("experiment_security_key"):
        tickers = sorted(group.ticker.unique())
        assert len(tickers) == 1
        ticker = tickers[0]
        if ticker in transitions:
            old_key, new_key, first_new_seen = transitions[ticker]
            if ((str(security_key) == old_key and last121.max() >= first_new_seen) or
                (str(security_key) == new_key and last121.min() < first_new_seen)):
                excluded.append({"security_key": security_key, "ticker": ticker,
                                 "reason": "OBSERVED_CUSIP_TRANSITION_CROSSES_RISK_WINDOW"})
                continue
        if fold in ("D1", "D2") and ticker in ("DNA", "VSTM") and group.signal_date.min() > last121.min():
            excluded.append({"security_key": security_key, "ticker": ticker,
                             "reason": "CUSIP_TRANSITION_WINDOW_NOT_PROVEN"})
            continue
        if ticker not in wide:
            excluded.append({"security_key": security_key, "ticker": ticker, "reason": "NO_PRICE_COLUMN"})
            continue
        value = wide[ticker].to_numpy(float)
        if not np.isfinite(value).all() or (value <= 0).any():
            excluded.append({"security_key": security_key, "ticker": ticker,
                             "reason": "INCOMPLETE_121_CLOSE_SESSIONS"})
            continue
        ret = value[1:] / value[:-1] - 1.0
        if not np.isfinite(ret).all() or ret.std(ddof=0) <= 1e-12:
            excluded.append({"security_key": security_key, "ticker": ticker,
                             "reason": "NONFINITE_OR_CONSTANT_RETURN"})
            continue
        keys.append(str(security_key))
        columns.append(ret)
    if len(keys) < 4:
        raise RuntimeError(f"RISK_UNIVERSE_TOO_SMALL:{fold}:{len(keys)}")
    matrix = np.column_stack(columns)
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0, ddof=0)
    normal = (matrix - means) / scales
    models = {}
    lw_path = MODELS / f"LW_{fold}.joblib"
    if lw_path.exists():
        lw = joblib.load(lw_path)
    else:
        estimator = LedoitWolf().fit(normal)
        lw = {"security_keys": keys, "training_dates": [str(x.date()) for x in last121[1:]],
              "means": means, "scales": scales,
              "correlation": correlation(estimator.covariance_),
              "covariance_normalized": estimator.covariance_,
              "shrinkage": float(estimator.shrinkage_), "excluded": excluded}
        save(lw_path, lw)
    assert lw["security_keys"] == keys
    models["LW"] = {"path": str(lw_path), "sha256": sha(lw_path),
                    "securities": len(keys), "shrinkage": lw["shrinkage"]}
    pca_path = MODELS / f"PCA_{fold}.joblib"
    if pca_path.exists():
        pca_result = joblib.load(pca_path)
    else:
        components = min(3, len(keys), len(normal))
        estimator = PCA(n_components=components, svd_solver="full").fit(normal)
        common = estimator.components_.T @ np.diag(estimator.explained_variance_) @ estimator.components_
        sample = np.cov(normal, rowvar=False, ddof=0)
        residual = np.maximum(np.diag(sample - common), 0.0)
        cov = common + np.diag(residual)
        pca_result = {"security_keys": keys,
                      "training_dates": [str(x.date()) for x in last121[1:]],
                      "means": means, "scales": scales,
                      "loadings": estimator.components_,
                      "factor_variance": estimator.explained_variance_,
                      "residual_variance": residual,
                      "correlation": correlation(cov),
                      "excluded": excluded}
        save(pca_path, pca_result)
    assert pca_result["security_keys"] == keys
    models["PCA"] = {"path": str(pca_path), "sha256": sha(pca_path),
                     "securities": len(keys), "factors": len(pca_result["factor_variance"])}
    return models


def fit_aux(fold: str, train: pd.DataFrame, scaler: dict) -> dict:
    x = scale(train, scaler)
    models = {}
    for name, estimator in [
        ("KMEANS", KMeans(n_clusters=3, n_init=10, random_state=11)),
        ("ISOLATION", IsolationForest(n_estimators=100, max_samples="auto",
                                      contamination=.01, random_state=11)),
    ]:
        path = MODELS / f"{name}_{fold}.joblib"
        if not path.exists():
            estimator.fit(x)
            save(path, estimator)
        models[name] = {"path": str(path), "sha256": sha(path),
                        "train_rows": len(train), "scaler_sha256": sha(MODELS / f"SCALER_{fold}.joblib")}
    return models


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["development", "post_selection"])
    args = parser.parse_args()
    if args.stage == "post_selection" and not (HERE / "PRIMARY_SELECTION.json").exists():
        raise RuntimeError("PRIMARY_SELECTION_REQUIRED_BEFORE_V25_AND_FINAL")
    folds = ("D1", "D2") if args.stage == "development" else ("V25", "FINAL")
    source = json.loads((HERE / "PRE2026_INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    assert sha(HERE / "PRE2026_SHARED_PANEL.parquet") == source["artifacts"]["PRE2026_SHARED_PANEL.parquet"]
    assert sha(HERE / "PRE2026_PRICE_COORDINATE.parquet") == source["artifacts"]["PRE2026_PRICE_COORDINATE.parquet"]
    panel = pd.read_parquet(HERE / "PRE2026_SHARED_PANEL.parquet")
    prices = pd.read_parquet(HERE / "PRE2026_PRICE_COORDINATE.parquet")
    report_path = HERE / "RISK_DIAGNOSTIC_MANIFEST.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    for fold in folds:
        train, _ = load_fold(panel, fold)
        scaler = scaler_for(fold, train)
        report[fold] = {"train_cutoff": FOLDS[fold][0],
                        "train_rows": len(train),
                        "risk": fit_risk(fold, panel, prices),
                        "diagnostics": fit_aux(fold, train, scaler),
                        "model_fit_count": 4,
                        "fit_only_pre2026": True}
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{fold} risk+diagnostics complete {report[fold]['risk']['LW']['securities']} securities", flush=True)


if __name__ == "__main__":
    main()
