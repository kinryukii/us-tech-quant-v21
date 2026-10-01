"""Pre-2026 factor covariance and unsupervised A2 diagnostics.

Only ``safe_inputs.load_inputs`` supplies data.  The three fits are made at
strictly earlier cutoffs; inference never updates a fitted object.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.cluster import KMeans
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "risk_artifacts"
SAFE_INPUTS = ROOT.parent / "a2_top20_action_nn_20260925" / "safe_inputs.py"
CUTOFFS = {"fold_2024": pd.Timestamp("2024-01-01"),
           "fold_2025": pd.Timestamp("2025-01-01"),
           "final_pre2026": pd.Timestamp("2026-01-01")}
FEATURES = ["raw_rank_strength", "raw_score_z", "ret_1d", "ret_5d",
            "ret_20d", "realized_vol_20d", "downside_vol_20d",
            "max_drawdown_20d", "volume_ratio_5d_20d", "price_vs_ma20",
            "distance_from_high_20d"]
LOOKBACK_SESSIONS = 252
MIN_TICKER_OBS = 126
MIN_TICKER_COVERAGE = 0.70
MAX_AUX_ROWS = 30000
PCA_COMPONENTS = 5
SEED = 20260925
FULL_PRE2026_PANEL = ROOT / "pre2026_panel.parquet"


def _load_safe_inputs():
    spec = importlib.util.spec_from_file_location("a2_safe_inputs_for_risk_aux", SAFE_INPUTS)
    if spec is None or spec.loader is None:
        raise RuntimeError("safe_inputs unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.load_inputs()


def _returns(prices: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    p = prices.loc[prices.trade_date.lt(cutoff) & prices.ticker.ne("QQQ"),
                   ["trade_date", "ticker", "close"]].copy()
    if p.empty or (p.close <= 0).any() or p.duplicated(["trade_date", "ticker"]).any():
        raise RuntimeError("invalid pre-cutoff price input")
    wide = p.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    # Ratios require consecutive market sessions.  Never forward-fill a missing
    # price, which would manufacture zero returns across listing gaps.
    ret = wide.pct_change(fill_method=None).iloc[-LOOKBACK_SESSIONS:]
    ret = ret.replace([np.inf, -np.inf], np.nan)
    return ret


def _condition(matrix: np.ndarray) -> float:
    vals = np.linalg.eigvalsh(matrix)
    return float(vals[-1] / max(vals[0], 1e-12))


def fit_bundle(panel: pd.DataFrame, prices: pd.DataFrame,
               cutoff: pd.Timestamp) -> tuple[dict, dict]:
    if cutoff > pd.Timestamp("2026-01-01"):
        raise ValueError("post-2025 fit forbidden")
    r = _returns(prices, cutoff)
    if len(r) < LOOKBACK_SESSIONS // 2:
        raise RuntimeError("insufficient risk sessions")
    coverage = r.notna().mean()
    count = r.notna().sum()
    chosen = sorted(coverage.index[(coverage >= MIN_TICKER_COVERAGE) &
                                   (count >= MIN_TICKER_OBS)].astype(str))
    if len(chosen) < PCA_COMPONENTS + 1:
        raise RuntimeError("insufficient covered securities for PCA")
    x = r[chosen].copy()
    x = x.fillna(x.median()).fillna(0.0)
    arr = x.to_numpy(dtype=float)
    mean = arr.mean(axis=0)
    centered = arr - mean
    n_components = min(PCA_COMPONENTS, len(chosen) - 1, len(arr) - 1)
    pca = PCA(n_components=n_components, svd_solver="full", random_state=SEED).fit(centered)
    factors = pca.transform(centered)
    reconstructed = pca.inverse_transform(factors)
    residual = centered - reconstructed
    factor_cov = (pca.components_.T @ np.cov(factors, rowvar=False) @ pca.components_)
    factor_cov += np.diag(np.var(residual, axis=0, ddof=1))
    lw = LedoitWolf(assume_centered=True).fit(centered)
    # Both terms are PSD.  The factor component explicitly retains the PCA risk
    # model; Ledoit-Wolf stabilizes the covariance of a wide, short sample.
    cov = 0.5 * factor_cov + 0.5 * lw.covariance_
    cov = (cov + cov.T) / 2
    eig = np.linalg.eigvalsh(cov)
    if eig[0] < 1e-12:
        cov += np.eye(len(chosen)) * (1e-12 - eig[0])
    fallback_var = float(max(np.quantile(np.diag(cov), 0.90) * 1.5, 1e-6))

    a = panel.loc[panel.signal_date.lt(cutoff), ["signal_date", "ticker", *FEATURES]].copy()
    a = a.sort_values(["signal_date", "ticker"], kind="mergesort")
    if len(a) > MAX_AUX_ROWS:
        a = a.iloc[-MAX_AUX_ROWS:]
    if len(a) < 1000:
        raise RuntimeError("insufficient auxiliary rows")
    raw = a[FEATURES].replace([np.inf, -np.inf], np.nan)
    preprocess = Pipeline([("impute", SimpleImputer(strategy="median")),
                           ("scale", StandardScaler())])
    z = preprocess.fit_transform(raw)
    cluster = KMeans(n_clusters=4, random_state=SEED, n_init=10).fit(z)
    anomaly = IsolationForest(n_estimators=100, max_samples=512,
                              contamination=0.05, random_state=SEED,
                              n_jobs=1).fit(z)
    bundle = {"cutoff": str(cutoff.date()), "tickers": chosen,
              "covariance": cov, "fallback_variance": fallback_var,
              "pca": pca, "ledoit_wolf": lw,
              "preprocess": preprocess, "cluster": cluster,
              "anomaly": anomaly, "features": FEATURES,
              "risk_sessions": len(r), "aux_rows": len(a)}
    diagnostics = {"cutoff": str(cutoff.date()), "risk_sessions": len(r),
                   "eligible_tickers": len(chosen), "all_price_tickers": len(r.columns),
                   "coverage_min": float(coverage[chosen].min()),
                   "coverage_median": float(coverage[chosen].median()),
                   "pca_components": n_components,
                   "pca_explained_variance_ratio": float(pca.explained_variance_ratio_.sum()),
                   "ledoit_wolf_shrinkage": float(lw.shrinkage_),
                   "covariance_min_eigenvalue": float(np.linalg.eigvalsh(cov)[0]),
                   "covariance_condition_number": _condition(cov),
                   "fallback_daily_volatility": float(np.sqrt(fallback_var)),
                   "aux_rows": len(a),
                   "cluster_counts": {str(k): int(v) for k, v in
                                      zip(*np.unique(cluster.labels_, return_counts=True))},
                   "train_anomaly_fraction": float((anomaly.predict(z) == -1).mean())}
    return bundle, diagnostics


def load_bundle(path: str | Path) -> dict:
    bundle = joblib.load(path)
    if pd.Timestamp(bundle["cutoff"]) > pd.Timestamp("2026-01-01"):
        raise RuntimeError("post-2025 model")
    return bundle


def covariance_for(bundle: dict, signal_date: str | pd.Timestamp,
                   tickers: list[str] | tuple[str, ...]) -> np.ndarray:
    """Daily-return covariance in exactly the supplied ticker order.

    A frozen model may score later dates.  It is not updated by this function.
    Unknown securities have conservative standalone risk and zero correlation.
    """
    if pd.Timestamp(signal_date) < pd.Timestamp(bundle["cutoff"]):
        raise ValueError("use the earlier fold bundle for historical inference")
    names = list(tickers)
    if len(names) != len(set(names)):
        raise ValueError("duplicate tickers")
    lookup = {s: i for i, s in enumerate(bundle["tickers"])}
    result = np.eye(len(names), dtype=float) * float(bundle["fallback_variance"])
    known = [(i, lookup[s]) for i, s in enumerate(names) if s in lookup]
    if known:
        dest, src = zip(*known)
        result[np.ix_(dest, dest)] = bundle["covariance"][np.ix_(src, src)]
    return result


def aux_scores(bundle: dict, frame: pd.DataFrame) -> pd.DataFrame:
    """Frozen cluster and anomaly diagnostics; no fitting or policy selection."""
    cols = list(bundle["features"])
    z = bundle["preprocess"].transform(frame[cols].replace([np.inf, -np.inf], np.nan))
    predicted_anomaly = bundle["anomaly"].predict(z)
    return pd.DataFrame({"signal_date": frame.signal_date.to_numpy(),
                         "ticker": frame.ticker.to_numpy(),
                         "cluster": bundle["cluster"].predict(z).astype(int),
                         "anomaly_score": bundle["anomaly"].decision_function(z),
                         "is_anomaly": predicted_anomaly == -1})


def validation_risk_diagnostics(bundle: dict, valid: pd.DataFrame,
                                prices: pd.DataFrame, valid_end: pd.Timestamp) -> dict:
    """Evaluate frozen covariance on pre-2026 next-close Raw Top20 returns."""
    valid_prices = prices.loc[prices.trade_date.lt(valid_end) & prices.ticker.ne("QQQ"),
                              ["trade_date", "ticker", "close"]]
    close = valid_prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    next_ret = close.shift(-1).div(close).sub(1.0)
    predicted_var, realized_ret = [], []
    for date, day in valid.loc[valid.raw_rank.le(20)].groupby("signal_date", sort=True):
        names = day.sort_values("raw_rank").ticker.astype(str).tolist()
        if len(names) != 20 or date not in next_ret.index:
            continue
        actual = next_ret.loc[date].reindex(names)
        if actual.isna().any():
            continue
        weights = np.full(20, 0.05)
        cov_day = covariance_for(bundle, date, names)
        predicted_var.append(float(weights @ cov_day @ weights))
        realized_ret.append(float(weights @ actual.to_numpy(float)))
    result = {"validation_risk_days": len(realized_ret)}
    if realized_ret:
        result["validation_predicted_daily_vol_rms"] = float(np.sqrt(np.mean(predicted_var)))
        result["validation_realized_daily_vol_rms"] = float(np.sqrt(np.mean(np.square(realized_ret))))
        result["validation_realized_to_predicted_risk_ratio"] = float(
            result["validation_realized_daily_vol_rms"] /
            result["validation_predicted_daily_vol_rms"])
    return result


def refresh_validation_diagnostics() -> None:
    """Evaluate saved fold models without adding model fits to the budget."""
    receipt = OUT / "diagnostics.json"
    recorded = json.loads(receipt.read_text(encoding="utf-8"))
    panel, prices, _, _ = _load_safe_inputs()
    for row in recorded["fits"]:
        if not row["name"].startswith("fold_"):
            continue
        cutoff = CUTOFFS[row["name"]]
        end = pd.Timestamp("2025-01-01") if row["name"] == "fold_2024" else pd.Timestamp("2026-01-01")
        valid = panel.loc[panel.signal_date.ge(cutoff) & panel.signal_date.lt(end)]
        bundle = load_bundle(OUT / f"{row['name']}.joblib")
        row.update(validation_risk_diagnostics(bundle, valid, prices, end))
    receipt.write_text(json.dumps(recorded, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(recorded["fits"]).drop(columns=["cluster_counts"]).to_csv(OUT / "trials.csv", index=False)


def refresh_final_aux() -> None:
    """One-time no-label extension of final auxiliary fit to all pre-2026 dates.

    The original final model is retained byte-for-byte. Fold bundles and the
    price/PCA/Ledoit-Wolf risk objects are unchanged. This performs exactly
    three additional fits: preprocessing, KMeans, IsolationForest.
    """
    source_hash = hashlib.sha256(FULL_PRE2026_PANEL.read_bytes()).hexdigest()
    manifest = json.loads((ROOT / "pre2026_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("panel_sha256") != source_hash:
        raise RuntimeError("full pre-2026 panel hash mismatch")
    source = pq.ParquetFile(FULL_PRE2026_PANEL)
    names = source.schema_arrow.names
    if not set(["signal_date", "ticker", *FEATURES]).issubset(names):
        raise RuntimeError("full pre-2026 panel feature schema mismatch")
    idx = names.index("signal_date")
    for i in range(source.metadata.num_row_groups):
        stats = source.metadata.row_group(i).column(idx).statistics
        if stats is None or not stats.has_min_max or pd.Timestamp(stats.max) >= pd.Timestamp("2026-01-01"):
            raise RuntimeError("unproven physical pre-2026 source boundary")
    frame = source.read(columns=["signal_date", "ticker", *FEATURES]).to_pandas()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.empty or frame.signal_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("invalid auxiliary date boundary")
    if frame.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("duplicate auxiliary panel keys")
    frame = frame.sort_values(["signal_date", "ticker"], kind="mergesort")
    full_path = OUT / "final_pre2026.joblib"
    retained_path = OUT / "final_pre2026_before_aux_refresh.joblib"
    revision_path = OUT / "final_aux_revision.json"
    if retained_path.exists() or revision_path.exists():
        raise RuntimeError("final auxiliary refresh already applied")
    prior_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
    recorded = json.loads((OUT / "diagnostics.json").read_text(encoding="utf-8"))
    final = next(row for row in recorded["fits"] if row["name"] == "final_pre2026")
    if final["model_sha256"] != prior_hash:
        raise RuntimeError("diagnostics prior model hash mismatch")
    bundle = load_bundle(full_path)
    prior_cov = np.asarray(bundle["covariance"])
    raw = frame[FEATURES].replace([np.inf, -np.inf], np.nan)
    preprocess = Pipeline([("impute", SimpleImputer(strategy="median")),
                           ("scale", StandardScaler())])
    z = preprocess.fit_transform(raw)
    cluster = KMeans(n_clusters=4, random_state=SEED, n_init=10).fit(z)
    anomaly = IsolationForest(n_estimators=100, max_samples=512,
                              contamination=0.05, random_state=SEED,
                              n_jobs=1).fit(z)
    bundle.update({"preprocess": preprocess, "cluster": cluster,
                   "anomaly": anomaly, "aux_rows": len(frame),
                   "aux_max_signal_date": str(frame.signal_date.max().date()),
                   "aux_source": str(FULL_PRE2026_PANEL)})
    if not np.array_equal(prior_cov, bundle["covariance"]):
        raise RuntimeError("risk matrix changed during auxiliary refresh")
    shutil.copy2(full_path, retained_path)
    temp_path = full_path.with_suffix(".joblib.tmp")
    joblib.dump(bundle, temp_path, compress=3)
    temp_path.replace(full_path)
    updated_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
    final.update({"model_sha256": updated_hash, "aux_rows": len(frame),
                  "aux_max_signal_date": str(frame.signal_date.max().date()),
                  "aux_source_sha256": source_hash,
                  "cluster_counts": {str(k): int(v) for k, v in
                                     zip(*np.unique(cluster.labels_, return_counts=True))},
                  "train_anomaly_fraction": float((anomaly.predict(z) == -1).mean())})
    recorded["aux_revision"] = {
        "reason": "Use all available pre-2026 unlabeled features, independent of old 20-day label maturity",
        "source": str(FULL_PRE2026_PANEL), "source_sha256": source_hash,
        "source_rows": len(frame), "source_max_signal_date": str(frame.signal_date.max().date()),
        "retained_original": str(retained_path), "original_model_sha256": prior_hash,
        "updated_model_sha256": updated_hash,
        "additional_fits": ["preprocess", "KMeans", "IsolationForest"],
        "cumulative_estimator_fits": 15,
        "pca_and_ledoit_wolf_unchanged": True,
        "fold_bundles_unchanged": True}
    (OUT / "diagnostics.json").write_text(json.dumps(recorded, ensure_ascii=False,
                                                       indent=2, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(recorded["fits"]).drop(columns=["cluster_counts"]).to_csv(OUT / "trials.csv", index=False)
    revision_path.write_text(json.dumps(recorded["aux_revision"], ensure_ascii=False,
                                        indent=2) + "\n", encoding="utf-8")
    print(f"FINAL_AUX_REFRESH rows={len(frame)} max_date={frame.signal_date.max().date()} hash={updated_hash}")


def main() -> None:
    if (OUT / "final_aux_revision.json").exists():
        raise RuntimeError("risk artifacts already fitted and revised; preserve frozen outputs")
    panel, prices, _, lineage = _load_safe_inputs()
    if panel.signal_date.max() >= pd.Timestamp("2026-01-01") or prices.trade_date.max() >= pd.Timestamp("2026-01-01"):
        raise RuntimeError("pre-2026 source boundary failed")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, cutoff in CUTOFFS.items():
        bundle, diag = fit_bundle(panel, prices, cutoff)
        path = OUT / f"{name}.joblib"
        joblib.dump(bundle, path, compress=3)
        diag["name"] = name
        diag["model_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if name.startswith("fold_"):
            valid_end = pd.Timestamp("2025-01-01") if name == "fold_2024" else pd.Timestamp("2026-01-01")
            valid = panel.loc[panel.signal_date.ge(cutoff) & panel.signal_date.lt(valid_end)]
            scored = aux_scores(bundle, valid)
            daily = scored.groupby("signal_date").is_anomaly.mean()
            diag["validation_dates"] = int(valid.signal_date.nunique())
            diag["validation_rows"] = len(valid)
            diag["validation_anomaly_fraction"] = float(scored.is_anomaly.mean())
            diag["validation_daily_anomaly_fraction_median"] = float(daily.median())
            known = valid.ticker.isin(bundle["tickers"])
            diag["validation_known_ticker_fraction"] = float(known.mean())
            diag.update(validation_risk_diagnostics(bundle, valid, prices, valid_end))
            scored.to_parquet(OUT / f"{name}_aux_scores.parquet", index=False)
        rows.append(diag)
        print(f"FITTED {name} risk={diag['eligible_tickers']} aux={diag['aux_rows']}", flush=True)
    (OUT / "diagnostics.json").write_text(json.dumps({"lineage": lineage, "fits": rows},
                                              ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(rows).drop(columns=["cluster_counts"]).to_csv(OUT / "trials.csv", index=False)


if __name__ == "__main__":
    main()
    if FULL_PRE2026_PANEL.exists():
        refresh_final_aux()
