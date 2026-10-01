"""Stage-frozen daily risk estimates and common-calendar joint scenarios.

No fitting is performed at import or during inference. ``fit`` requires the
root experiment contract to exist, writes only new stage directories, and
physically reads the isolated pre-2026 price file. Unknown securities remain
in every output with an explicit conservative variance and coverage record.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import warnings
from collections import OrderedDict

import joblib
import numpy as np
import pandas as pd
from scipy.linalg import eigh
from scipy.special import ndtr, ndtri
from scipy.stats import rankdata
from sklearn.covariance import LedoitWolf, OAS
from sklearn.decomposition import FactorAnalysis
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from common import RISKS


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "risk_artifacts"
STAGES = {"validation": "2025-01-01", "final": "2026-01-01"}
RISK_NAMES = tuple(RISKS)
SEED = 20260928
MIN_OBSERVATIONS = 126
MIN_DAILY_VOL = .01
UNKNOWN_DAILY_VOL = .08
SCENARIO_COUNT = 64
RISK_SPEC = {
    "members": list(RISK_NAMES), "stages": STAGES, "daily_return_window": 252,
    "tail_price_dates": 253, "minimum_observations": MIN_OBSERVATIONS,
    "return_clip_for_risk_only": [-.5, .5], "minimum_daily_vol": MIN_DAILY_VOL,
    "unknown_daily_vol": UNKNOWN_DAILY_VOL,
    "missing": "within pre-cutoff window per-security observed mean; standardized missing=0; no forward fill",
    "insufficient_history": "keep security, conservative independent .08 daily sigma; disclose coverage",
    "factor_count": 5, "factor_analysis_max_iter": 100, "factor_analysis_tol": .001,
    "factor_analysis_svd": "lapack", "seed": SEED,
    "matrix_cooperation": {"blend_lw_oas": ["lw", "oas"], "blend_pca_fa": ["pca", "fa"]},
    "supervised_second_moment_target": "(clip(next_open_return,-.20,.20)/.02)^2; prediction times .0004",
    "supervised_interpretation": "conditional second moment proxy, including squared mean; not an unbiased conditional variance",
    "supervised_sample_rows": 30000,
    "supervised_hgb": {"max_iter": 100, "max_depth": 3, "max_leaf_nodes": 15,
                       "min_samples_leaf": 100, "l2_regularization": 5.,
                       "learning_rate": .05, "early_stopping": False},
    "supervised_mlp": {"hidden_layer_sizes": [32, 16], "max_iter": 20,
                       "n_iter_no_change": 21, "early_stopping": False,
                       "alpha": .01, "learning_rate_init": .001,
                       "batch_size": 256, "shuffle": True},
    "supervised_variance_prediction_bounds": [.0001, .04],
    "scenario_count": SCENARIO_COUNT,
    "scenario_rows": "round(linspace(0,251,64)); same frozen calendar rows for all securities",
    "scenario_dependence": "historical rank normal scores whitened and recolored to requested daily covariance correlation; no independent random samples",
    "scenario_unknown_rank": "same frozen market-average rank score; never independent random generation",
    "scenario_marginals": "native sigma, or q10/q50/q90 piecewise inverse-CDF with normal tails; absent uses selected risk sigma; recenter columns to provider mu",
    "scenario_marginal_scale": "native shape times selected risk sigma / frozen historical sigma; native uncertainty is preserved; fallback starts with historical sigma",
    "scenario_unknown_limitation": "shared market rank proxy can be rank deficient and correlated despite diagonal unknown covariance; disclose achieved rank/correlation discrepancy; no claim of exact independent unknown copula",
    "cache_limit_entries_per_kind": 4096,
    "max_refits": 0, "hyperparameter_searches": 0,
}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False, default=str), encoding="utf-8")


def prepare_returns(prices, cutoff):
    """Time-filter before selecting the fixed covariance window."""
    frame = prices.loc[pd.to_datetime(prices.trade_date).lt(cutoff),
                       ["trade_date", "ticker", "close"]].copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if frame.empty or frame.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("EMPTY_OR_DUPLICATE_RISK_PRICE_INPUT")
    frame.loc[~np.isfinite(frame.close) | frame.close.le(0), "close"] = np.nan
    wide = frame.pivot(index="trade_date", columns="ticker", values="close").sort_index().tail(253)
    if len(wide) != 253:
        raise ValueError("RISK_REQUIRES_253_PAST_PRICE_DATES")
    returns = wide.pct_change(fill_method=None).iloc[1:].replace([np.inf, -np.inf], np.nan)
    assert len(returns) == 252 and returns.index.max() < pd.Timestamp(cutoff)
    return returns


def _correlation(covariance):
    covariance = (np.asarray(covariance, float) + np.asarray(covariance, float).T) / 2
    scale = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    correlation = covariance / np.outer(scale, scale)
    # Fixed numerical ridge is applied to the correlation and renormalized.
    correlation = (correlation + correlation.T) / 2 + np.eye(len(scale)) * 1e-8
    correlation /= np.sqrt(np.outer(np.diag(correlation), np.diag(correlation)))
    return correlation


def estimate_matrices(returns):
    """Fit only the declared statistical risk members on the same observations."""
    counts = returns.notna().sum()
    retained = returns.loc[:, counts.ge(MIN_OBSERVATIONS)]
    if len(retained.columns) < 5:
        raise ValueError("RISK_REQUIRES_FIVE_HISTORY_QUALIFIED_SECURITIES")
    raw = retained.to_numpy(float)
    clipped = np.clip(raw, -.5, .5)
    means = np.nanmean(clipped, axis=0)
    vol = np.maximum(np.nanstd(clipped, axis=0, ddof=1), MIN_DAILY_VOL)
    standardized = np.nan_to_num((clipped - means) / vol, nan=0.)
    captured = []
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
        warnings.simplefilter("always")
        lw = LedoitWolf().fit(standardized)
        oas = OAS().fit(standardized)
        historical = np.cov(standardized, rowvar=False, ddof=1)
        correlations = {"historical": _correlation(historical),
                        "lw": _correlation(lw.covariance_), "oas": _correlation(oas.covariance_)}
        count = len(vol)
        vals, vecs = eigh(correlations["historical"], subset_by_index=[count - 5, count - 1])
        common = (vecs * vals) @ vecs.T
        pca = common + np.diag(np.maximum(1 - np.diag(common), 1e-8))
        correlations["pca"] = _correlation(pca)
        fa = FactorAnalysis(n_components=5, max_iter=100, tol=.001,
                            svd_method="lapack", random_state=SEED).fit(standardized)
        correlations["fa"] = _correlation(fa.get_covariance())
        captured = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    matrices = {"diag": np.diag(vol ** 2)}
    matrices.update({name: corr * np.outer(vol, vol) for name, corr in correlations.items()})
    matrices["blend_lw_oas"] = .5 * (matrices["lw"] + matrices["oas"])
    matrices["blend_pca_fa"] = .5 * (matrices["pca"] + matrices["fa"])
    for matrix in matrices.values():
        np.linalg.cholesky(matrix)
    coverage = pd.DataFrame({"ticker": returns.columns.astype(str),
                             "observations": counts.to_numpy(int),
                             "history_qualified": counts.to_numpy(int) >= MIN_OBSERVATIONS})
    ranks = np.column_stack([rankdata(standardized[:, i], method="average") / 253
                             for i in range(standardized.shape[1])])
    market = standardized.mean(axis=1)
    market_ranks = rankdata(market, method="average") / 253
    details = {"securities_qualified": len(vol), "securities_insufficient": int((counts < MIN_OBSERVATIONS).sum()),
               "lw_shrinkage": float(lw.shrinkage_), "oas_shrinkage": float(oas.shrinkage_),
               "fa_iterations": int(fa.n_iter_),
               "fa_budget_exhausted": bool(fa.n_iter_ >= 100),
               "warnings": captured, "risk_missing_cells": int(np.isnan(raw).sum()),
               "risk_clipped_cells": int((np.abs(raw) > .5).sum())}
    arrays = {"tickers": retained.columns.to_numpy(str), "daily_vol": vol,
              "rank_uniforms": ranks, "market_rank_uniforms": market_ranks,
              "return_dates": returns.index.to_numpy("datetime64[ns]")}
    arrays.update({f"cov_{name}": value for name, value in matrices.items()})
    return arrays, coverage, details


def _training_inputs(stage, training_frame, feature_columns):
    if training_frame is None or feature_columns is None:
        import data_contract as contract
        if feature_columns is None:
            feature_columns = list(contract.FEATURES)
        if training_frame is None:
            training_frame = contract.load_stage_training(stage)
    frame = training_frame.copy()
    cutoff = pd.Timestamp(STAGES[stage])
    if (len(feature_columns) != 32 or len(frame) != 30000
            or frame.signal_date.ge(cutoff).any() or frame.label_end_date.ge(cutoff).any()
            or frame.label_end_date.le(frame.signal_date).any()):
        raise ValueError("SUPERVISED_RISK_SAMPLE_OR_TIME_CONTRACT_MISMATCH")
    target = frame.y_train.to_numpy(float) if "y_train" in frame else np.clip(frame.y_next_open.to_numpy(float), -.2, .2)
    x = frame[list(feature_columns)].to_numpy(float)
    weights = frame.sample_weight.to_numpy(float) if "sample_weight" in frame else np.ones(len(frame))
    if not np.isfinite(x).all() or not np.isfinite(target).all() or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("INVALID_SUPERVISED_RISK_INPUT")
    return frame, x, (target / .02) ** 2, weights, list(feature_columns)


class RiskBank:
    def __init__(self, stage="final", risk_name="lw", artifact_root=None, load=True):
        if stage not in STAGES or risk_name not in RISK_NAMES:
            raise ValueError("UNKNOWN_RISK_STAGE_OR_MEMBER")
        self.stage, self.risk_name = stage, risk_name
        self.artifact_root = Path(artifact_root) if artifact_root is not None else OUT
        self._cache, self._scenario_cache = OrderedDict(), OrderedDict()
        self._scenario_metadata_cache = {}
        self.last_coverage, self.last_scenario_metadata = {}, {}
        if load:
            self.load()

    def fit(self, stage=None, training_frame=None, feature_columns=None, prices=None,
            experiment_contract=None, reuse_completed=True):
        stage = self.stage if stage is None else stage
        if stage != self.stage or stage not in STAGES:
            raise ValueError("RISK_FIT_STAGE_MISMATCH")
        contract_path = Path(experiment_contract) if experiment_contract is not None else ROOT / "contract.json"
        if not contract_path.is_file():
            raise RuntimeError("ROOT_EXPERIMENT_CONTRACT_REQUIRED_BEFORE_RISK_FIT")
        implementation = self.artifact_root / "IMPLEMENTATION_SPEC.json"
        if not implementation.is_file():
            raise RuntimeError("IMPLEMENTATION_SPEC_REQUIRED_BEFORE_RISK_FIT")
        bound = json.loads(implementation.read_text(encoding="utf-8"))
        if (bound["root_contract_sha256"] != sha(contract_path)
                or bound["risk_spec"] != RISK_SPEC
                or bound["risk_code_sha256"] != sha(Path(__file__))):
            raise RuntimeError("IMPLEMENTATION_SPEC_CHANGED_BEFORE_RISK_FIT")
        dest = self.artifact_root / stage
        if (dest / "TRAIN_RECEIPT.json").is_file() and reuse_completed:
            self.load()
            if self.receipt.get("implementation_spec_sha256") != sha(implementation):
                raise RuntimeError("COMPLETED_RISK_FIT_IMPLEMENTATION_MISMATCH")
            return self.receipt
        if dest.exists() and any(dest.iterdir()):
            raise RuntimeError(f"EXISTING_RISK_STAGE_PRESERVED:{dest}")
        price_path = ROOT / "input/pre2026_prices.parquet"
        if prices is None:
            prices = pd.read_parquet(price_path, columns=["trade_date", "ticker", "close"])
        if pd.to_datetime(prices.trade_date).ge("2026-01-01").any():
            raise ValueError("NON_PRE2026_PHYSICAL_RISK_PRICE_INPUT")
        returns = prepare_returns(prices, STAGES[stage])
        frame, x, y, weights, features = _training_inputs(stage, training_frame, feature_columns)
        source_hashes = {str(price_path): sha(price_path)} if price_path.exists() else {}
        for path in [ROOT / "input/pre2026.parquet", ROOT / f"input/stage_{stage}_keys.parquet"]:
            if path.exists():
                source_hashes[str(path)] = sha(path)
        dest.mkdir(parents=True, exist_ok=True)
        design = {"status": "PRE_FIT_LOCKED", "stage": stage, "cutoff_exclusive": STAGES[stage],
                  "created_utc": datetime.now(timezone.utc).isoformat(), "specification": RISK_SPEC,
                  "feature_order": features, "source_sha256": source_hashes,
                  "producer_sha256": sha(Path(__file__)), "experiment_contract_sha256": sha(contract_path),
                  "implementation_spec_sha256": sha(implementation),
                  "train_signal_max": str(frame.signal_date.max().date()),
                  "train_label_end_max": str(frame.label_end_date.max().date()),
                  "risk_return_first": str(returns.index.min().date()),
                  "risk_return_last": str(returns.index.max().date()), "fit_2026_rows": 0}
        write_json(dest / "PRE_FIT_CONTRACT.json", design)
        start = time.monotonic()
        arrays, coverage, details = estimate_matrices(returns)
        np.savez_compressed(dest / "frozen_risk.npz", **arrays)
        coverage.to_parquet(dest / "history_coverage.parquet", index=False)
        fits = []
        estimators = {
            "hgbvol": HistGradientBoostingRegressor(**RISK_SPEC["supervised_hgb"], random_state=SEED),
            "mlpvol": make_pipeline(StandardScaler(), MLPRegressor(
                hidden_layer_sizes=(32, 16), max_iter=20, n_iter_no_change=21,
                early_stopping=False, alpha=.01, learning_rate_init=.001,
                batch_size=256, shuffle=True, random_state=SEED)),
        }
        for name, estimator in estimators.items():
            started = time.monotonic()
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                if name == "mlpvol":
                    # Both scaler and network see only the same frozen stage sample.
                    estimator.fit(x, y, standardscaler__sample_weight=weights,
                                  mlpregressor__sample_weight=weights)
                else:
                    estimator.fit(x, y, sample_weight=weights)
            path = dest / f"{name}.joblib"
            joblib.dump(estimator, path, compress=3)
            terminal = estimator[-1] if name == "mlpvol" else estimator
            fits.append({"name": name, "rows": len(x), "fit_seconds": time.monotonic() - started,
                         "iterations": int(terminal.n_iter_),
                         "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught],
                         "fixed_budget_exhausted": bool(name == "mlpvol" and terminal.n_iter_ >= 20),
                         "artifact": str(path), "artifact_sha256": sha(path)})
        artifact_names = ["frozen_risk.npz", "history_coverage.parquet", "hgbvol.joblib", "mlpvol.joblib"]
        receipt = {**design, "status": "PASS", "fit_seconds": time.monotonic() - start,
                   "statistical_fits": details, "supervised_fits": fits,
                   "fit_operation_counts": {"historical": 1, "diag": 1, "ledoit_wolf": 1,
                                            "oas": 1, "pca5": 1, "factor_analysis5": 1,
                                            "hgb_second_moment": 1, "mlp_second_moment": 1,
                                            "scaler": 1, "equal_matrix_blends": 2},
                   "artifacts_sha256": {name: sha(dest / name) for name in artifact_names},
                   "source_files_unchanged": all(sha(p) == value for p, value in source_hashes.items())}
        if not receipt["source_files_unchanged"]:
            raise RuntimeError("RISK_SOURCE_CHANGED_DURING_FIT")
        write_json(dest / "TRAIN_RECEIPT.json", receipt)
        self.load()
        return receipt

    def load(self):
        dest = self.artifact_root / self.stage
        receipt = json.loads((dest / "TRAIN_RECEIPT.json").read_text(encoding="utf-8"))
        if (receipt["status"] != "PASS" or receipt["stage"] != self.stage
                or receipt["cutoff_exclusive"] != STAGES[self.stage]
                or receipt["fit_2026_rows"] != 0):
            raise ValueError("RISK_RECEIPT_STAGE_OR_TIME_MISMATCH")
        for name, digest in receipt["artifacts_sha256"].items():
            if sha(dest / name) != digest:
                raise ValueError(f"RISK_ARTIFACT_HASH_MISMATCH:{name}")
        with np.load(dest / "frozen_risk.npz", allow_pickle=False) as archive:
            self.arrays = {name: archive[name].copy() for name in archive.files}
        self.lookup = {str(t): i for i, t in enumerate(self.arrays["tickers"])}
        self.history_coverage = pd.read_parquet(dest / "history_coverage.parquet")
        self.coverage_lookup = self.history_coverage.set_index("ticker").observations.to_dict()
        self.features = receipt["feature_order"]
        self.vol_models = {name: joblib.load(dest / f"{name}.joblib") for name in ["hgbvol", "mlpvol"]}
        self.receipt = receipt
        self._cache.clear()
        self._scenario_cache.clear()
        self._scenario_metadata_cache.clear()
        return self

    def _base_covariance(self, names, risk_name):
        base_name = "lw" if risk_name in {"lw_hgb_vol", "lw_mlp_vol"} else risk_name
        key = (base_name, tuple(names))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key].copy()
        covariance = np.eye(len(names)) * UNKNOWN_DAILY_VOL ** 2
        ids = [(i, self.lookup[t]) for i, t in enumerate(names) if t in self.lookup]
        if ids:
            dst, src = zip(*ids)
            covariance[np.ix_(dst, dst)] = self.arrays[f"cov_{base_name}"][np.ix_(src, src)]
        self._cache[key] = covariance.copy()
        if len(self._cache) > RISK_SPEC["cache_limit_entries_per_kind"]:
            self._cache.popitem(last=False)
        return covariance

    def predict_signal_vol(self, features, risk_name=None):
        risk_name = self.risk_name if risk_name is None else risk_name
        if risk_name not in {"lw_hgb_vol", "lw_mlp_vol"}:
            return None
        x = features[self.features].to_numpy(float) if isinstance(features, pd.DataFrame) else np.asarray(features, float)
        if x.ndim != 2 or x.shape[1] != len(self.features) or not np.isfinite(x).all():
            raise ValueError("INVALID_SUPERVISED_SIGNAL_RISK_FEATURES")
        member = "hgbvol" if risk_name == "lw_hgb_vol" else "mlpvol"
        with threadpool_limits(limits=2):
            second_moment = self.vol_models[member].predict(x) * .0004
        return np.sqrt(np.clip(second_moment, MIN_DAILY_VOL ** 2, .04))

    def covariance(self, names, signalvol=None, risk_name=None, features=None, return_metadata=False):
        names = [str(t) for t in names]
        risk_name = self.risk_name if risk_name is None else risk_name
        if risk_name not in RISK_NAMES or len(set(names)) != len(names):
            raise ValueError("INVALID_RISK_MEMBER_OR_DUPLICATE_SUPPORT")
        covariance = self._base_covariance(names, risk_name)
        if signalvol is None and risk_name in {"lw_hgb_vol", "lw_mlp_vol"}:
            if features is None:
                raise ValueError("SUPERVISED_RISK_REQUIRES_FROZEN_SIGNAL_VOL_OR_FEATURES")
            signalvol = self.predict_signal_vol(features, risk_name)
        if signalvol is not None:
            sigma = np.array([signalvol[t] for t in names], float) if isinstance(signalvol, dict) else np.asarray(signalvol, float)
            if sigma.shape != (len(names),) or not np.isfinite(sigma).all() or (sigma <= 0).any():
                raise ValueError("INVALID_SIGNAL_VOLATILITY")
            sigma = np.maximum(sigma, MIN_DAILY_VOL)
            # Missing historical correlation does not receive optimistic learned volatility.
            sigma[[t not in self.lookup for t in names]] = UNKNOWN_DAILY_VOL
            covariance = _correlation(covariance) * np.outer(sigma, sigma)
        unknown = [t for t in names if t not in self.lookup]
        metadata = {"stage": self.stage, "risk_member": risk_name, "support_count": len(names),
                    "known_risk_count": len(names) - len(unknown), "unknown_tickers": unknown,
                    "observations": {t: int(self.coverage_lookup.get(t, 0)) for t in names},
                    "minimum_history_observations": MIN_OBSERVATIONS,
                    "supervised_volatility": signalvol is not None,
                    "daily_variance_floor": MIN_DAILY_VOL ** 2}
        self.last_coverage = metadata
        return (covariance, metadata) if return_metadata else covariance

    def _joint_uniforms(self, names, covariance, cache_key):
        if cache_key in self._scenario_cache:
            self._scenario_cache.move_to_end(cache_key)
            return self._scenario_cache[cache_key].copy()
        if not names:
            return np.empty((SCENARIO_COUNT, 0))
        raw = np.column_stack([self.arrays["rank_uniforms"][:, self.lookup[t]] if t in self.lookup
                               else self.arrays["market_rank_uniforms"] for t in names])
        normal = ndtri(np.clip(raw, 1 / 506, 1 - 1 / 506))
        normal -= normal.mean(axis=0)
        empirical = normal.T @ normal / max(1, len(normal) - 1)
        vals, vecs = eigh(empirical)
        whiten = (vecs * (1 / np.sqrt(np.maximum(vals, 1e-8)))) @ vecs.T
        target = _correlation(covariance)
        vals, vecs = eigh(target)
        recolor = (vecs * np.sqrt(np.maximum(vals, 1e-8))) @ vecs.T
        scores = normal @ whiten @ recolor
        # A shared unknown-history proxy can have insufficient rank. Preserve
        # marginal scale and explicitly report the unmatched dependence.
        score_scale = np.std(scores, axis=0, ddof=1)
        scores /= np.maximum(score_scale, 1e-8)
        achieved = scores.T @ scores / (len(scores) - 1)
        self._scenario_metadata_cache[cache_key] = {
            "historical_rank_score_rank": int(np.linalg.matrix_rank(empirical, tol=1e-8)),
            "target_support_dimension": len(names),
            "rank_deficient": bool(np.linalg.matrix_rank(empirical, tol=1e-8) < len(names)),
            "pre_subsample_correlation_max_error": float(np.max(np.abs(achieved - target))),
            "exact_dependence_match_claimed": False,
        }
        rows = np.rint(np.linspace(0, len(normal) - 1, SCENARIO_COUNT)).astype(int)
        uniforms = np.clip(ndtr(scores[rows]), 1e-4, 1 - 1e-4)
        self._scenario_cache[cache_key] = uniforms.copy()
        if len(self._scenario_cache) > RISK_SPEC["cache_limit_entries_per_kind"]:
            old, _ = self._scenario_cache.popitem(last=False)
            self._scenario_metadata_cache.pop(old, None)
        return uniforms

    def scenarios(self, names, mu, marginals=None, risk_name=None, features=None,
                  signalvol=None, return_metadata=False):
        names = [str(t) for t in names]
        mu = np.asarray(mu, float)
        if mu.shape != (len(names),) or not np.isfinite(mu).all():
            raise ValueError("INVALID_SCENARIO_MEAN")
        risk_name = self.risk_name if risk_name is None else risk_name
        covariance, coverage = self.covariance(names, signalvol=signalvol, risk_name=risk_name,
                                               features=features, return_metadata=True)
        base_name = "lw" if risk_name in {"lw_hgb_vol", "lw_mlp_vol"} else risk_name
        cache_key = (base_name, tuple(names))
        # Learned signal scales change marginal volatility, not frozen LW correlation.
        uniforms = self._joint_uniforms(names, self._base_covariance(names, risk_name), cache_key)
        scenario_sigma = np.sqrt(np.diag(covariance))
        historical_sigma = np.array([self.arrays["daily_vol"][self.lookup[t]] if t in self.lookup
                                     else UNKNOWN_DAILY_VOL for t in names])
        marginals = {} if marginals is None else dict(marginals)
        if "q" in marginals and not all(key in marginals for key in ["q10", "q50", "q90"]):
            packed = np.asarray(marginals["q"], float)
            if packed.shape != (len(names), 3):
                raise ValueError("INVALID_PACKED_NATIVE_QUANTILE_SHAPE")
            marginals.update(dict(zip(["q10", "q50", "q90"], packed.T)))
        sigma = np.asarray(marginals.get("sigma", historical_sigma), float)
        sigma = np.maximum(np.broadcast_to(sigma, (len(names),)), MIN_DAILY_VOL)
        if not np.isfinite(sigma).all():
            raise ValueError("NONFINITE_NATIVE_SCENARIO_SIGMA")
        z = ndtri(uniforms)
        samples = mu + sigma * z
        quantile_count = 0
        if all(key in marginals for key in ["q10", "q50", "q90"]):
            q = np.column_stack([np.asarray(marginals[key], float) for key in ["q10", "q50", "q90"]])
            if q.shape != (len(names), 3):
                raise ValueError("INVALID_NATIVE_QUANTILES")
            finite_quantiles = np.isfinite(q).all(axis=1)
            quantile_count = int(finite_quantiles.sum())
            q.sort(axis=1)
            q10, q50, q90 = q.T
            left_scale = np.maximum((q50 - q10) / abs(ndtri(.1)), MIN_DAILY_VOL)
            right_scale = np.maximum((q90 - q50) / ndtri(.9), MIN_DAILY_VOL)
            quantile_samples = np.where(uniforms < .1, q10 + left_scale * (z - ndtri(.1)),
                       np.where(uniforms < .5, q10 + (q50 - q10) * (uniforms - .1) / .4,
                       np.where(uniforms < .9, q50 + (q90 - q50) * (uniforms - .5) / .4,
                                q90 + right_scale * (z - ndtri(.9)))))
            samples[:, finite_quantiles] = quantile_samples[:, finite_quantiles]
            adapter = "native_quantile_piecewise_normal_tails_with_sigma_fallback"
        else:
            samples = mu + sigma * z
            adapter = "native_sigma_normal_shape" if "sigma" in marginals else "frozen_historical_residual_normal_fallback"
        samples = (samples - samples.mean(axis=0)) * (scenario_sigma / historical_sigma)
        unknown_mask = np.array([t not in self.lookup for t in names])
        if unknown_mask.any():
            empirical_scale = np.std(samples[:, unknown_mask], axis=0, ddof=1)
            samples[:, unknown_mask] *= np.maximum(1., UNKNOWN_DAILY_VOL / np.maximum(empirical_scale, 1e-8))
        samples += mu
        if not np.isfinite(samples).all():
            raise ValueError("NONFINITE_JOINT_SCENARIOS")
        metadata = {**coverage, "scenario_count": SCENARIO_COUNT,
                    "marginal_adapter": adapter, "independent_scenarios": False,
                    "calendar_row_indices": np.rint(np.linspace(0, 251, SCENARIO_COUNT)).astype(int).tolist(),
                    "mean_matching_error": float(np.abs(samples.mean(axis=0) - mu).max(initial=0)),
                    "dependence": "historical_rank_normal_whiten_recolor_to_selected_covariance",
                    "unknown_rank_fallback": "shared_frozen_market_rank",
                    "native_uncertainty_preserved": True,
                    "native_quantile_support_count": quantile_count,
                    "sigma_fallback_support_count": len(names) - quantile_count,
                    "risk_scale_ratio": (scenario_sigma / historical_sigma).tolist(),
                    **self._scenario_metadata_cache.get(cache_key, {})}
        self.last_scenario_metadata = metadata
        return (samples, metadata) if return_metadata else samples

    def covariance_batch(self, supports, risk_name=None, signalvol=None, features=None):
        values = [self.covariance(names, risk_name=risk_name,
                                  signalvol=None if signalvol is None else signalvol[i],
                                  features=None if features is None else features[i])
                  for i, names in enumerate(supports)]
        return np.stack(values)

    def scenarios_batch(self, supports, means, marginals=None, risk_name=None,
                        signalvol=None, features=None):
        values = [self.scenarios(names, means[i], risk_name=risk_name,
                                marginals=None if marginals is None else marginals[i],
                                signalvol=None if signalvol is None else signalvol[i],
                                features=None if features is None else features[i])
                  for i, names in enumerate(supports)]
        return np.stack(values)

    def cache_info(self):
        return {"covariance_entries": len(self._cache), "copula_entries": len(self._scenario_cache),
                "limit_per_kind": RISK_SPEC["cache_limit_entries_per_kind"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=STAGES)
    arguments = parser.parse_args()
    bank = RiskBank(arguments.stage, load=False)
    receipt = bank.fit()
    print(json.dumps({"stage": arguments.stage, "status": receipt["status"],
                      "fit_seconds": receipt["fit_seconds"], "fit_2026_rows": 0}), flush=True)
