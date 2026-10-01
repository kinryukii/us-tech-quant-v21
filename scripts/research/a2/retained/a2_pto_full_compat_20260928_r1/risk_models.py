"""Twelve frozen pre-2026 risk specifications and shared joint scenarios.

No fitting occurs on import or in RiskBank.  The supervised target is a
one-session absolute-return scale proxy, not an identified conditional sigma.
Scenarios whiten and recolor the common historical joint residuals with the
chosen risk covariance. Rank-deficient histories retain an explicit approximation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import warnings

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

import joblib
import numpy as np
import pandas as pd
from scipy.linalg import eigh
from sklearn.covariance import LedoitWolf, OAS
from sklearn.decomposition import FactorAnalysis
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
import common

FEATURES = [
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d", "realized_vol_20d",
    "realized_vol_60d", "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d",
    "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d", "avg_volume_60d",
    "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
]
RISK_NAMES = (
    "diagonal", "samplecov", "lw", "oas", "pca5", "fa5", "lw_oas",
    "lw_hgb", "lw_mlp", "lw_scale_equal", "lw_garch11", "lw_gjr11",
)
assert FEATURES == common.FEATURES
assert list(RISK_NAMES) == common.RISKS
CUTOFFS = {"validation": "2025-01-01", "final": "2026-01-01"}
SEED = 20260928
MIN_SIGMA = 1e-4
MIN_RISK_OBSERVATIONS = 60
WINDOW = 252
PER_DATE_ROWS = 80
MODEL_ROOT = HERE / "models" / "risk"
PREDICTION_ROOT = HERE / "predictions" / "risk"


def sha(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                              default=str, allow_nan=False), encoding="utf-8")


def psd(matrix, floor=1e-10):
    """Symmetrize and floor eigenvalues without changing the ticker order."""
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("RISK_MATRIX_SHAPE")
    if not np.isfinite(matrix).all():
        raise ValueError("NONFINITE_RISK_MATRIX")
    matrix = (matrix + matrix.T) / 2.
    if len(matrix) == 0:
        return matrix
    values, vectors = eigh(matrix, check_finite=False)
    if values.min() < floor:
        matrix = (vectors * np.maximum(values, floor)) @ vectors.T
    return (matrix + matrix.T) / 2.


def correlation(matrix):
    matrix = psd(matrix)
    sigma = np.sqrt(np.maximum(np.diag(matrix), MIN_SIGMA ** 2))
    value = matrix / np.outer(sigma, sigma)
    return (value + value.T) / 2.


def covariance_structures(returns: pd.DataFrame):
    """Fit seven structures to the same trailing, incomplete joint return panel."""
    if len(returns) != WINDOW or returns.columns.duplicated().any():
        raise ValueError("RISK_HISTORY_WINDOW_OR_KEYS")
    raw = returns.to_numpy(dtype=np.float64)
    observed = np.isfinite(raw)
    counts = observed.sum(axis=0)
    supported = counts >= MIN_RISK_OBSERVATIONS
    if not supported.any():
        raise ValueError("NO_SUPPORTED_RISK_SECURITIES")
    raw = raw[:, supported]
    counts = counts[supported]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        means = np.nanmean(raw, axis=0)
        sigma = np.maximum(np.nanstd(raw, axis=0, ddof=1), MIN_SIGMA)
        joint_z = np.nan_to_num((raw - means) / sigma, nan=0., posinf=0., neginf=0.)
        sample = joint_z.T @ joint_z / (WINDOW - 1)
        lw_model = LedoitWolf().fit(joint_z)
        oas_model = OAS().fit(joint_z)
        lw = lw_model.covariance_
        oas = oas_model.covariance_
        n = len(sigma)
        factors = min(5, n, WINDOW - 1)
        values, vectors = eigh(sample, subset_by_index=[n - factors, n - 1], check_finite=False)
        common = (vectors * np.maximum(values, 0.)) @ vectors.T
        pca = common + np.diag(np.maximum(np.diag(sample - common), 1e-8))
        fa_model = FactorAnalysis(n_components=factors, max_iter=100, tol=.01,
                                 random_state=SEED, svd_method="randomized").fit(joint_z)
        fa = fa_model.get_covariance()
    structures = {
        "diagonal": np.diag(sigma * sigma),
        "samplecov": sample * np.outer(sigma, sigma),
        "lw": lw * np.outer(sigma, sigma),
        "oas": oas * np.outer(sigma, sigma),
        "pca5": pca * np.outer(sigma, sigma),
        "fa5": fa * np.outer(sigma, sigma),
        "lw_oas": (.5 * lw + .5 * oas) * np.outer(sigma, sigma),
    }
    structures = {name: psd(value) for name, value in structures.items()}
    unknown_sigma = max(float(np.quantile(sigma, .9)), MIN_SIGMA)
    audit = {
        "history_rows": WINDOW, "supported_securities": n,
        "unsupported_securities": int((~supported).sum()),
        "minimum_observations": MIN_RISK_OBSERVATIONS,
        "observations_min": int(counts.min()), "observations_max": int(counts.max()),
        "missing_cells": int(np.isnan(raw).sum()), "return_clip": None,
        "missing_method": "center/scale observed cells; missing joint standardized residuals are zero",
        "lw_shrinkage": float(lw_model.shrinkage_), "oas_shrinkage": float(oas_model.shrinkage_),
        "pca_components": factors, "fa_components": factors,
        "fa_iterations": int(fa_model.n_iter_), "fa_converged": not any(
            w.category.__name__ == "ConvergenceWarning" for w in caught),
        "unknown_daily_sigma": unknown_sigma,
        "unknown_sigma_rule": "90th percentile of supported training-history daily sigma",
        "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught],
    }
    return structures, returns.columns.to_numpy(str)[supported], sigma, joint_z, audit


def sample_scale_training(frame: pd.DataFrame, cutoff: str):
    """Select deterministic keys with mature labels; the cap uses no outcomes."""
    required = ["signal_date", "ticker", "y_next_open", "label_end_date", "label_available", *FEATURES]
    absent = sorted(set(required) - set(frame.columns))
    if absent:
        raise ValueError(f"RISK_SCALE_MISSING_COLUMNS:{absent}")
    if frame.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("RISK_SCALE_DUPLICATE_KEYS")
    frame = frame.copy()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame["label_end_date"] = pd.to_datetime(frame.label_end_date)
    if frame.signal_date.isna().any() or not frame.signal_date.lt("2026-01-01").all():
        raise ValueError("RISK_SCALE_INPUT_NOT_PHYSICALLY_PRE2026")
    selected = common.training_sample(frame, cutoff, PER_DATE_ROWS)
    if selected.empty or not selected.label_end_date.gt(selected.signal_date).all():
        raise ValueError("RISK_SCALE_LABEL_MATURITY")
    if not np.isfinite(selected[["y_next_open", *FEATURES]].to_numpy(float)).all():
        raise ValueError("RISK_SCALE_NONFINITE_INPUT")
    selected["sample_hash"] = [hashlib.sha256(f"{d.date()}|{t}|{SEED}".encode("utf-8")).hexdigest()
                               for d, t in zip(selected.signal_date, selected.ticker)]
    selected = selected.sort_values(["signal_date", "sample_hash", "ticker"], kind="mergesort")
    selected = selected.loc[selected.groupby("signal_date", sort=False).cumcount().lt(PER_DATE_ROWS)]
    return selected.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def _price_returns(prices, cutoff):
    prices = prices.copy()
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    if prices.trade_date.isna().any() or not prices.trade_date.lt("2026-01-01").all():
        raise ValueError("RISK_PRICES_NOT_PHYSICALLY_PRE2026")
    if prices.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("RISK_PRICE_DUPLICATE_KEYS")
    prior = prices.loc[prices.trade_date.lt(cutoff)]
    wide = prior.pivot(index="trade_date", columns="ticker", values="close").sort_index().tail(WINDOW + 1)
    if len(wide) != WINDOW + 1:
        raise ValueError("RISK_PRE_CUTOFF_HISTORY_TOO_SHORT")
    wide = wide.where(np.isfinite(wide) & wide.gt(0))
    return wide.pct_change(fill_method=None).iloc[1:]


def _fit_garch(returns, tickers, baseline_sigma):
    from arch import arch_model
    output = {"garch": baseline_sigma.copy(), "gjr": baseline_sigma.copy()}
    records = []
    for index, ticker in enumerate(tickers):
        values = returns[ticker].dropna().to_numpy(float)
        for name, asymmetry in (("garch", 0), ("gjr", 1)):
            record = {"ticker": ticker, "family": name, "observations": len(values),
                      "baseline_sigma": float(baseline_sigma[index]), "status": "FALLBACK"}
            started = time.monotonic()
            try:
                if len(values) < MIN_RISK_OBSERVATIONS:
                    raise ValueError("TOO_FEW_GARCH_OBSERVATIONS")
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    estimator = arch_model(values * 100., mean="Zero", vol="GARCH", p=1,
                                           o=asymmetry, q=1, dist="normal", rescale=False)
                    fitted = estimator.fit(disp="off", update_freq=0, show_warning=False,
                                           options={"maxiter": 100, "ftol": 1e-8})
                    forecast = fitted.forecast(horizon=1, reindex=False)
                    predicted = float(np.sqrt(forecast.variance.iloc[-1, 0]) / 100.)
                record["convergence_flag"] = int(fitted.convergence_flag)
                record["parameters"] = {str(k): float(v) for k, v in fitted.params.items()}
                record["warnings"] = [{"category": w.category.__name__, "message": str(w.message)}
                                      for w in caught]
                if fitted.convergence_flag != 0 or not np.isfinite(predicted) or predicted <= 0:
                    raise ValueError("GARCH_DID_NOT_CONVERGE_TO_POSITIVE_FINITE_SIGMA")
                output[name][index] = max(predicted, MIN_SIGMA)
                record.update(status="FITTED", frozen_next_sigma=float(output[name][index]))
            except Exception as error:
                record.update(fallback_reason=f"{type(error).__name__}: {error}",
                              frozen_next_sigma=float(baseline_sigma[index]))
            record["fit_seconds"] = time.monotonic() - started
            records.append(record)
        if (index + 1) % 100 == 0:
            print(json.dumps({"risk_garch_tickers_processed": index + 1, "of": len(tickers)}), flush=True)
    return output, records


def train_stage(stage):
    if stage not in CUTOFFS:
        raise ValueError("UNKNOWN_RISK_STAGE")
    cutoff = CUTOFFS[stage]
    destination = MODEL_ROOT / stage
    receipt_path = destination / "TRAIN_RECEIPT.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("status") != "PASS":
            raise RuntimeError("EXISTING_RISK_STAGE_NOT_COMPLETE")
        for name, expected in receipt["artifacts_sha256"].items():
            if sha(destination / name) != expected:
                raise RuntimeError("EXISTING_RISK_ARTIFACT_CHANGED")
        return receipt
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("EXISTING_PARTIAL_RISK_STAGE_PRESERVED")
    data_path = HERE / "data" / "pre.parquet"
    price_path = HERE / "data" / "pre_prices.parquet"
    frame = pd.read_parquet(data_path)
    prices = pd.read_parquet(price_path, columns=["trade_date", "ticker", "close"])
    training = sample_scale_training(frame, cutoff)
    returns = _price_returns(prices, cutoff)
    from arch import arch_model  # Dependency check before any output or training.
    import arch
    destination.mkdir(parents=True, exist_ok=False)
    prediction_directory = PREDICTION_ROOT / stage
    prediction_directory.mkdir(parents=True, exist_ok=False)
    keys = training[["signal_date", "ticker", "label_end_date", "sample_hash"]]
    keys.to_parquet(destination / "SCALE_SAMPLE_KEYS.parquet", index=False)
    specification = {
        "status": "PRE_FIT_LOCKED", "stage": stage, "cutoff_exclusive": cutoff,
        "risk_names": list(RISK_NAMES), "features": FEATURES, "seed": SEED,
        "source_sha256": {str(data_path): sha(data_path), str(price_path): sha(price_path),
                          str(Path(__file__)): sha(Path(__file__))},
        "scale_sample_keys_sha256": sha(destination / "SCALE_SAMPLE_KEYS.parquet"),
        "training_rows": len(training), "training_dates": int(training.signal_date.nunique()),
        "training_signal_max": str(training.signal_date.max().date()),
        "training_label_end_max": str(training.label_end_date.max().date()),
        "scale_target": "log(sqrt(y_next_open^2+1e-8)); one-session absolute-return scale proxy",
        "scale_target_is_identified_conditional_sigma": False,
        "sampling": "shared common.training_sample: first 80 smallest SHA256(date|ticker|seed) on each mature buy-eligible date",
        "risk_return_window": WINDOW, "minimum_risk_observations": MIN_RISK_OBSERVATIONS,
        "risk_history_first": str(returns.index.min().date()),
        "risk_history_last": str(returns.index.max().date()),
        "hgb": {"max_iter": 80, "max_depth": 3, "max_leaf_nodes": 15,
                "min_samples_leaf": 100, "learning_rate": .05, "l2_regularization": 5.,
                "early_stopping": False, "random_state": SEED},
        "mlp": {"hidden_layer_sizes": [32, 16], "max_iter": 8, "batch_size": 512,
                "learning_rate_init": .001, "alpha": .01, "early_stopping": False,
                "n_iter_no_change": 9, "random_state": SEED},
        "scale_output_bounds": {"minimum_sigma": MIN_SIGMA,
                                "maximum_sigma": "max(1, max training absolute-return scale target)"},
        "garch": {"mean": "Zero", "p": 1, "q": 1, "gjr_o": 1,
                  "distribution": "normal", "return_units": "percent", "maxiter": 100,
                  "ftol": 1e-8, "rescale": False, "forecast": "frozen final-training one-step sigma"},
        "frozen_during_2026": True, "test2026_rows_read": 0, "hyperparameter_search_count": 0,
        "scenario_dependence": "same historical standardized 252-row joint residual panel, whitened then recolored by selected risk covariance",
        "scenario_risk_readout": "fixed spectral source eigenvalue floor 1e-8, selected frozen covariance square root; add mu after transformation",
        "scenario_limitation": "source rank < requested dimension, including N>251 or duplicate unknown-name proxy histories, gives rank approximation; no independent draws or post-2026 fits",
        "python": platform.python_version(), "arch": arch.__version__,
    }
    write_json(destination / "PRE_FIT_CONTRACT.json", specification)
    started = time.monotonic()
    with threadpool_limits(limits=2):
        matrices, tickers, baseline_sigma, joint_z, structure_audit = covariance_structures(returns)
        x = training[FEATURES].to_numpy(float)
        y_sigma = np.sqrt(training.y_next_open.to_numpy(float) ** 2 + 1e-8)
        log_y = np.log(y_sigma)
        output_sigma_max = max(1., float(y_sigma.max()))
        hgb = HistGradientBoostingRegressor(**specification["hgb"])
        scaler = StandardScaler().fit(x)
        mlp = MLPRegressor(**{**specification["mlp"], "hidden_layer_sizes": (32, 16)})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            hgb.fit(x, log_y)
            mlp.fit(scaler.transform(x), log_y)
        scale_warnings = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
        if mlp.n_iter_ != 8:
            raise RuntimeError("RISK_MLP_FIXED_EIGHT_EPOCH_BUDGET_NOT_CONSUMED")
        garch, garch_records = _fit_garch(returns, tickers, baseline_sigma)
    arrays = {**{f"cov_{name}": value for name, value in matrices.items()},
              "tickers": tickers, "baseline_sigma": baseline_sigma, "joint_z": joint_z,
              "unknown_sigma": np.array(structure_audit["unknown_daily_sigma"]),
              "garch_sigma": garch["garch"], "gjr_sigma": garch["gjr"],
              "output_sigma_max": np.array(output_sigma_max),
              "history_dates": returns.index.to_numpy(dtype="datetime64[ns]")}
    np.savez_compressed(destination / "frozen_risk.npz", **arrays)
    joblib.dump({"features": FEATURES, "stage": stage, "cutoff_exclusive": cutoff,
                 "hgb": hgb, "mlp": mlp, "scaler": scaler},
                destination / "supervised_scale.joblib", compress=3)
    pd.DataFrame(garch_records).to_json(destination / "GARCH_FIT_RECORDS.json", orient="records", indent=2)
    prediction = training[["signal_date", "ticker", "label_end_date"]].copy()
    prediction["actual_abs_return_scale"] = y_sigma
    prediction["hgb_sigma"] = np.exp(np.clip(hgb.predict(x), np.log(MIN_SIGMA), np.log(output_sigma_max)))
    prediction["mlp_sigma"] = np.exp(np.clip(mlp.predict(scaler.transform(x)), np.log(MIN_SIGMA), np.log(output_sigma_max)))
    if not np.isfinite(prediction[["hgb_sigma", "mlp_sigma"]].to_numpy(float)).all():
        raise RuntimeError("NONFINITE_RISK_SCALE_TRAINING_PREDICTION")
    prediction.to_parquet(prediction_directory / "scale_training_predictions.parquet", index=False)
    for name in RISK_NAMES:
        write_json(destination / f"{name}.json", {
            "stage": stage, "name": name, "cutoff_exclusive": cutoff,
            "shared_covariance_artifact": "frozen_risk.npz",
            "shared_supervised_scale_artifact": "supervised_scale.joblib" if name in (
                "lw_hgb", "lw_mlp", "lw_scale_equal") else None,
            "frozen_parameters": True, "fits_after_cutoff": 0,
        })
    files = ["frozen_risk.npz", "supervised_scale.joblib", "GARCH_FIT_RECORDS.json",
             "SCALE_SAMPLE_KEYS.parquet", "PRE_FIT_CONTRACT.json", *[f"{name}.json" for name in RISK_NAMES]]
    receipt = {**specification, "status": "PASS", "structure_audit": structure_audit,
               "supervised_scale_fit_calls": 2, "scaler_fit_calls": 1,
               "hgb_iterations": int(hgb.n_iter_), "mlp_iterations": int(mlp.n_iter_),
               "scale_warnings": scale_warnings, "risk_specifications_materialized": len(RISK_NAMES),
               "garch_fit_attempts": len(garch_records),
               "garch_fit_successes": sum(r["status"] == "FITTED" for r in garch_records),
               "garch_fallbacks": sum(r["status"] != "FITTED" for r in garch_records),
               "garch_fallbacks_by_family": {family: sum(
                   r["family"] == family and r["status"] != "FITTED" for r in garch_records)
                   for family in ("garch", "gjr")},
               "prediction_artifact_sha256": sha(prediction_directory / "scale_training_predictions.parquet"),
               "artifacts_sha256": {name: sha(destination / name) for name in files},
               "fit_seconds": time.monotonic() - started}
    if not all(sha(Path(path)) == expected for path, expected in specification["source_sha256"].items()):
        raise RuntimeError("RISK_FROZEN_SOURCE_DRIFT")
    write_json(receipt_path, receipt)
    print(json.dumps({"stage": stage, "status": "PASS", "risk_names": len(RISK_NAMES),
                      "garch_fit_attempts": len(garch_records), "garch_fallbacks": receipt["garch_fallbacks"],
                      "fit_seconds": receipt["fit_seconds"]}), flush=True)
    return receipt


class RiskBank:
    """Inference only; each requested ticker keeps its position and fallback."""

    def __init__(self, stage="final"):
        if stage not in CUTOFFS:
            raise ValueError("UNKNOWN_RISK_STAGE")
        directory = MODEL_ROOT / stage
        self.receipt = json.loads((directory / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
        if self.receipt["status"] != "PASS" or self.receipt["cutoff_exclusive"] != CUTOFFS[stage]:
            raise ValueError("RISK_STAGE_RECEIPT_INVALID")
        for name, expected in self.receipt["artifacts_sha256"].items():
            if sha(directory / name) != expected:
                raise ValueError(f"RISK_ARTIFACT_HASH_MISMATCH:{name}")
        with np.load(directory / "frozen_risk.npz", allow_pickle=False) as stored:
            self.data = {name: stored[name].copy() for name in stored.files}
        self.lookup = {ticker: index for index, ticker in enumerate(self.data["tickers"].astype(str))}
        self.scale_bundle = joblib.load(directory / "supervised_scale.joblib")
        if self.scale_bundle["features"] != FEATURES or self.scale_bundle["stage"] != stage:
            raise ValueError("RISK_SCALE_FEATURE_OR_STAGE_MISMATCH")
        self.stage = stage
        self.names = RISK_NAMES
        self.fallback_counts = {"unknown_ticker_queries": 0, "missing_supervised_features": 0}
        self.scenario_approximations = {"calls": 0, "rank_deficient_calls": 0}
        self._day_scale_cache = None

    def _indices(self, tickers):
        tickers = [str(t) for t in tickers]
        if len(set(tickers)) != len(tickers):
            raise ValueError("RISK_REQUEST_DUPLICATE_TICKERS")
        indices = np.array([self.lookup.get(t, -1) for t in tickers], dtype=int)
        self.fallback_counts["unknown_ticker_queries"] += int((indices < 0).sum())
        return tickers, indices

    def _baseline(self, indices):
        sigma = np.full(len(indices), float(self.data["unknown_sigma"]))
        known = indices >= 0
        sigma[known] = self.data["baseline_sigma"][indices[known]]
        return sigma

    def _base_covariance(self, name, indices):
        covariance = np.eye(len(indices)) * float(self.data["unknown_sigma"]) ** 2
        known = np.flatnonzero(indices >= 0)
        if len(known):
            covariance[np.ix_(known, known)] = self.data[f"cov_{name}"][np.ix_(indices[known], indices[known])]
        return covariance

    def _learned_scales(self, tickers, indices, day):
        baseline = self._baseline(indices)
        values = {"hgb": baseline.copy(), "mlp": baseline.copy()}
        frame = day.get("frame") if isinstance(day, dict) else day
        if not isinstance(frame, pd.DataFrame) or not {"ticker", *FEATURES}.issubset(frame.columns):
            self.fallback_counts["missing_supervised_features"] += len(tickers)
            return values
        if frame.ticker.astype(str).duplicated().any():
            raise ValueError("RISK_DAY_DUPLICATE_FEATURE_KEYS")
        if self._day_scale_cache is None or self._day_scale_cache[0] is not frame:
            x = frame[FEATURES].to_numpy(float)
            valid = np.isfinite(x).all(axis=1)
            if not valid.all():
                raise ValueError("RISK_DAY_NONFINITE_FEATURES")
            cache = {}
            if len(frame):
                with threadpool_limits(limits=2):
                    low, high = np.log(MIN_SIGMA), np.log(float(self.data["output_sigma_max"]))
                    hgb = np.exp(np.clip(self.scale_bundle["hgb"].predict(x), low, high))
                    mlp = np.exp(np.clip(self.scale_bundle["mlp"].predict(
                        self.scale_bundle["scaler"].transform(x)), low, high))
                cache = {str(t): (float(a), float(b)) for t, a, b in zip(frame.ticker, hgb, mlp)}
            self._day_scale_cache = (frame, cache)
        cache = self._day_scale_cache[1]
        for i, ticker in enumerate(tickers):
            if ticker in cache:
                values["hgb"][i], values["mlp"][i] = cache[ticker]
            else:
                self.fallback_counts["missing_supervised_features"] += 1
        return values

    def covariance(self, risk_name, tickers, day=None):
        if risk_name not in RISK_NAMES:
            raise ValueError(f"UNKNOWN_RISK_NAME:{risk_name}")
        tickers, indices = self._indices(tickers)
        if risk_name in ("diagonal", "samplecov", "lw", "oas", "pca5", "fa5", "lw_oas"):
            return self._base_covariance(risk_name, indices)
        covariance = self._base_covariance("lw", indices)
        corr = covariance / np.outer(np.sqrt(np.diag(covariance)), np.sqrt(np.diag(covariance)))
        sigma = self._baseline(indices)
        if risk_name in ("lw_hgb", "lw_mlp", "lw_scale_equal"):
            scales = self._learned_scales(tickers, indices, day)
            sigma = (scales["hgb"] + scales["mlp"]) / 2. if risk_name == "lw_scale_equal" else scales[risk_name[3:]]
        else:
            known = indices >= 0
            key = "garch_sigma" if risk_name == "lw_garch11" else "gjr_sigma"
            sigma[known] = self.data[key][indices[known]]
        return corr * np.outer(sigma, sigma)

    def scenarios(self, risk_name, tickers, day=None, mu=None):
        """Return 252 correlated scenarios, never independent per-stock draws."""
        tickers, indices = self._indices(tickers)
        covariance = self.covariance(risk_name, tickers, day)
        residuals = np.zeros((WINDOW, len(tickers)))
        known = indices >= 0
        residuals[:, known] = self.data["joint_z"][:, indices[known]]
        # Unknown names use one common observed historical market residual;
        # no independent shocks are fabricated to hide missing risk support.
        if (~known).any():
            common = self.data["joint_z"].mean(axis=1)
            common = common - common.mean()
            common_std = common.std(ddof=1)
            if common_std < 1e-12:
                common = self.data["joint_z"][:, 0]
                common_std = common.std(ddof=1)
            residuals[:, ~known] = (common / max(common_std, 1e-12))[:, None]
        expected = np.zeros(len(tickers)) if mu is None else np.asarray(mu, float).reshape(-1)
        if expected.shape != (len(tickers),) or not np.isfinite(expected).all():
            raise ValueError("RISK_SCENARIO_EXPECTED_RETURN_SHAPE")
        if len(tickers) == 0:
            return np.empty((WINDOW, 0))
        centered = residuals - residuals.mean(axis=0)
        source_covariance = centered.T @ centered / (WINDOW - 1)
        source_values, source_vectors = eigh(source_covariance, check_finite=False)
        target_values, target_vectors = eigh((covariance + covariance.T) / 2., check_finite=False)
        source_inverse_root = (source_vectors * (1. / np.sqrt(np.maximum(source_values, 1e-8)))) @ source_vectors.T
        target_root = (target_vectors * np.sqrt(np.maximum(target_values, 0.))) @ target_vectors.T
        result = centered @ source_inverse_root @ target_root + expected[None, :]
        self.scenario_approximations["calls"] += 1
        self.scenario_approximations["rank_deficient_calls"] += int((source_values < 1e-8).any())
        if not np.isfinite(result).all():
            raise ValueError("NONFINITE_JOINT_SCENARIOS")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=[*CUTOFFS, "all"], default="all")
    args = parser.parse_args()
    for requested in CUTOFFS if args.stage == "all" else [args.stage]:
        train_stage(requested)
