"""Pure risk estimators over caller-isolated, matured return observations.

No market/result readers, output paths, sample selection, or eligibility upgrades
live here. Retained risk runners bind old roots/populations and cannot be imported;
their covariance primitives and shared-GARCH pure definition are reused instead.
Different caller assets, dates, return units or horizons are different fit identities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import json
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf, OAS
from threadpoolctl import threadpool_limits

SEED = 20260928
COMMON = {
    "seed": SEED, "configs": 1, "seeds": 1,
    "window": "ALL_CALLER_PROVIDED_MATURED_PAST_ROWS",
    "min_observations": 30, "variance_floor": 1e-12,
    "numerical_ridge_relative": 1e-10, "numerical_ridge_absolute": 1e-12,
    "missing_returns": "observed-column mean; absent centered observations=0; coverage retained",
    "unknown_assets": "prior fitted median marginal variance, independent correlation; no eligibility upgrade",
    "maturity": "caller must isolate rows with matured labels before fit cutoff",
}
CONFIGS = {
    "DIAG": {}, "SCOV": {"ddof": 1}, "LW": {"assume_centered": True},
    "OAS": {"assume_centered": True},
    "CONSTANT_CORR": {"average": "all off-diagonal sample correlations"},
    "PCA": {"n_components": 5, "svd_solver": "full"},
    "FA": {"n_components": 5, "max_iter": 100, "tol": .001, "svd_method": "lapack"},
    "SINGLE_INDEX": {"factor": "caller market return", "regression": "centered OLS"},
    "INDUSTRY": {"regression_ridge": 1e-8, "exposures": "caller PIT qualified"},
    "FUNDAMENTAL": {"regression_ridge": 1e-8, "exposures": "caller PIT qualified"},
    "EWMA": {"decay": .94, "weights": "every caller row has positive weight"},
    "HISTVOL": {"ddof": 1, "structure": "diagonal; same window as DIAG"},
    "GARCH": {"shared_parameters": True, "max_iter": 200, "stationarity_cap": .995,
              "correlation": "LW", "source": "retained r2::_fit_garch(asymmetric=False)"},
    "GJR_GARCH": {"shared_parameters": True, "max_iter": 200, "stationarity_cap": .995,
                  "correlation": "LW", "source": "retained r2::_fit_garch(asymmetric=True)"},
    "GRAPHICAL_LASSO": {"alpha": .01, "max_iter": 100, "tol": 1e-4, "mode": "cd"},
    "ROBUST_COV": {"estimator": "MinCovDet", "support_fraction": None},
    "NONLINEAR_SHRINKAGE": {"backend": None, "missing_backend": "BLOCKED_DEPENDENCY; no LW substitute"},
    "COV_ENSEMBLE": {"members": ["LW", "OAS"], "weights": [.5, .5]},
}
ALIASES = {
    "DIAGONAL": "DIAG", "DIAGONAL_DIAG": "DIAG",
    "SAMPLE": "SCOV", "SAMPLE_COVARIANCE": "SCOV", "SAMPLE_COV": "SCOV",
    "LEDOIT_WOLF": "LW", "LEDOITWOLF": "LW",
    "CONSTANT_CORRELATION": "CONSTANT_CORR", "PCA_FACTOR_MODEL": "PCA",
    "FA_RISK_MODEL": "FA", "FACTOR_ANALYSIS": "FA",
    "SINGLE_INDEX_MODEL": "SINGLE_INDEX", "INDUSTRY_FACTOR_MODEL": "INDUSTRY",
    "FUNDAMENTAL_FACTOR_MODEL": "FUNDAMENTAL", "EWMA_COVARIANCE": "EWMA",
    "HISTORICAL_VOLATILITY": "HISTVOL", "HISTORICAL_VOL": "HISTVOL",
    "SHARED_GARCH": "GARCH", "GARCH_1_1": "GARCH",
    "SHARED_GJR": "GJR_GARCH", "GJR": "GJR_GARCH",
    "GRAPHICAL_LASSO": "GRAPHICAL_LASSO", "MIN_COV_DET": "ROBUST_COV",
    "MINCOVDET": "ROBUST_COV", "ROBUST_COVARIANCE": "ROBUST_COV",
    "COVARIANCE_ENSEMBLE": "COV_ENSEMBLE", "BLEND_LW_OAS": "COV_ENSEMBLE",
}
BINDINGS = {"fit_cutoff", "return_unit", "return_horizon_sessions", "source_id", "information_set_id"}


def canonical_method(method_id):
    name = str(method_id).strip().upper().replace("-", "_").replace(" ", "_")
    name = name.replace("/", "_").replace("(", "_").replace(")", "").replace(",", "_")
    name = ALIASES.get(name, name)
    if name not in CONFIGS:
        raise ValueError(f"UNKNOWN_RISK_METHOD:{method_id}")
    return name


def specs(method_id=None):
    """JSON-serializable one-config/one-seed specifications; no inferred window."""
    if method_id is None:
        return {name: {**copy.deepcopy(COMMON), **copy.deepcopy(config)}
                for name, config in CONFIGS.items()}
    name = canonical_method(method_id)
    return {**copy.deepcopy(COMMON), **copy.deepcopy(CONFIGS[name])}


@dataclass
class RiskBundle:
    method_id: str
    status: str
    assets: tuple[str, ...]
    fitted_dates: tuple[str, ...]
    estimated_assets: tuple[str, ...] = ()
    covariance: np.ndarray | None = None
    fallback_variance: float | None = None
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)
    fitted_state: dict = field(default_factory=dict)
    specification: dict = field(default_factory=dict)
    budget: dict = field(default_factory=dict)
    failure_reason: str = ""


class RiskEstimatorBlocked(ValueError):
    pass


def validate_covariance(matrix, *, regularize=True):
    """Finite symmetric PSD check with a declared roundoff-only diagonal ridge."""
    value = np.asarray(matrix, dtype=float)
    if value.ndim != 2 or value.shape[0] != value.shape[1] or not len(value):
        raise ValueError("RISK_MATRIX_SHAPE_INVALID")
    if not np.isfinite(value).all() or not np.allclose(value, value.T, rtol=1e-10, atol=1e-12):
        raise ValueError("RISK_MATRIX_NONFINITE_OR_ASYMMETRIC")
    value = (value + value.T)*.5
    if np.any(np.diag(value) < 0):
        raise ValueError("RISK_MATRIX_NEGATIVE_MARGINAL")
    off_diagonal = value.copy()
    np.fill_diagonal(off_diagonal, 0.)
    if not np.any(off_diagonal):
        return value, {"psd_check": "NONNEGATIVE_DIAGONAL", "diagonal_ridge_added": 0.}
    ridge = COMMON["numerical_ridge_absolute"] + COMMON["numerical_ridge_relative"]*float(np.diag(value).max())
    checked = value.copy()
    checked.flat[::len(value)+1] += ridge
    try:
        np.linalg.cholesky(checked)
    except np.linalg.LinAlgError as exc:
        raise ValueError("RISK_MATRIX_NOT_PSD_WITH_DECLARED_ROUNDOFF_RIDGE") from exc
    return (checked if regularize else value), {"psd_check": "CHOLESKY_WITH_DECLARED_ROUNDOFF_RIDGE",
                                                "diagonal_ridge_added": ridge if regularize else 0.}


def _parameters(method, params):
    config = specs(method)
    for name, value in (params or {}).items():
        if name in BINDINGS:
            config[name] = str(value) if name != "return_horizon_sessions" else value
        elif name not in config or value != config[name]:
            raise ValueError(f"RISK_PARAMETER_DIFFERS_FROM_FROZEN_CONFIG:{name}")
    if "return_horizon_sessions" in config:
        horizon = config["return_horizon_sessions"]
        if isinstance(horizon, bool) or int(horizon) != horizon or horizon <= 0:
            raise ValueError("RETURN_HORIZON_MUST_BE_POSITIVE_INTEGER")
        config["return_horizon_sessions"] = int(horizon)
    return config


def _prepare(returns_frame, config):
    if not isinstance(returns_frame, pd.DataFrame) or returns_frame.empty:
        raise ValueError("NONEMPTY_RETURN_DATAFRAME_REQUIRED")
    frame = returns_frame.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("RETURN_INDEX_MUST_BE_DATETIME")
    if frame.index.hasnans or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("RETURN_DATES_MUST_BE_UNIQUE_INCREASING")
    names = tuple(map(str, frame.columns))
    if len(set(names)) != len(names) or any(not name.strip() for name in names):
        raise ValueError("RETURN_ASSETS_MUST_BE_UNIQUE_NONEMPTY")
    if "fit_cutoff" in config:
        cutoff = pd.Timestamp(config["fit_cutoff"])
        if pd.isna(cutoff) or cutoff.tzinfo != frame.index.tz or np.any(frame.index >= cutoff):
            raise ValueError("RETURN_INDEX_NOT_STRICTLY_BEFORE_CALLER_CUTOFF")
    raw = frame.to_numpy(float)
    if np.isinf(raw).any():
        raise ValueError("INFINITE_RETURN_OBSERVATION")
    observed = np.isfinite(raw)
    counts = observed.sum(axis=0)
    qualify = counts >= config["min_observations"]
    coverage = pd.DataFrame({"asset": names, "observations": counts,
                             "history_qualified_for_estimation": qualify,
                             "strategy_eligibility_upgraded": False})
    if not qualify.any():
        return names, coverage, None
    positions = np.flatnonzero(qualify)
    known = raw[:, positions]
    mean = np.nanmean(known, axis=0)
    variance = np.nanvar(known, axis=0, ddof=1)
    variance = np.maximum(variance, config["variance_floor"])
    centered = np.where(np.isfinite(known), known-mean, 0.)
    state = {"positions": positions, "mean": mean, "marginal_variance": variance,
             "centered": centered, "observed": observed[:, positions],
             "missing_cells_mean_imputed": int((~observed[:, positions]).sum())}
    return names, coverage, state


def _blocked(bundle, status, reason):
    bundle.status, bundle.failure_reason = status, reason
    return bundle



def _correlation(covariance):
    covariance = np.asarray(covariance, float)
    scale = np.sqrt(np.maximum(np.diag(covariance), COMMON["variance_floor"]))
    correlation = covariance / np.outer(scale, scale)
    correlation = (correlation+correlation.T)*.5
    np.fill_diagonal(correlation, 1.)
    return correlation


def _shared_garch_definition():
    # Reuse just the frozen pure definition; do not import its legacy ROOT,
    # train_risk, readers, module globals, or runners.
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "retained" / "a2_pto_full_compat_20260928_r2" / "risk_models.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_fit_garch")
    definition = ast.Module(body=[node], type_ignores=[])
    namespace = {"np": np, "minimize": minimize}
    exec(compile(definition, str(path), "exec"), namespace)
    digest = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    return namespace["_fit_garch"], digest


def _single_index(state, index, market_returns, config):
    if not isinstance(market_returns, pd.Series):
        raise RiskEstimatorBlocked("BLOCKED_INPUT:CALLER_MARKET_RETURN_SERIES_REQUIRED")
    if not isinstance(market_returns.index, pd.DatetimeIndex) or market_returns.index.has_duplicates:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:MARKET_RETURN_DATE_INDEX_INVALID")
    if "fit_cutoff" in config and np.any(market_returns.index >= pd.Timestamp(config["fit_cutoff"])):
        raise RiskEstimatorBlocked("BLOCKED_INPUT:MARKET_RETURN_REACHES_CALLER_CUTOFF")
    factor = market_returns.reindex(index).to_numpy(float)
    if not np.isfinite(factor).all():
        raise RiskEstimatorBlocked("BLOCKED_INPUT:MARKET_RETURN_REQUIRED_ON_EVERY_CALLER_ROW")
    factor = factor-factor.mean()
    denominator = float(factor@factor)
    if denominator <= COMMON["variance_floor"]:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:MARKET_FACTOR_HAS_NO_IDENTIFIABLE_VARIANCE")
    x = state["centered"]
    beta = factor@x/denominator
    residual = x-factor[:, None]*beta
    factor_variance = denominator/(len(index)-1)
    specific = np.maximum(np.var(residual, axis=0, ddof=1), COMMON["variance_floor"])
    covariance = factor_variance*np.outer(beta, beta)+np.diag(specific)
    return covariance, {"beta": beta, "factor_variance": factor_variance,
                        "specific_variance": specific, "factor_unit": "same period-return unit as caller assets",
                        "market_source_id": market_returns.attrs.get("source_id", "CALLER_UNSPECIFIED")}, 3


def _exposure_factor(state, index, assets, exposure_frame, config):
    if not isinstance(exposure_frame, pd.DataFrame) or exposure_frame.empty:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:CALLER_PIT_EXPOSURE_FRAME_REQUIRED")
    # Static fit-cutoff exposures: assets x factor columns. A dated panel must be
    # bound by the caller to a single legal as-of exposure matrix first.
    if isinstance(exposure_frame.index, pd.MultiIndex) or exposure_frame.index.has_duplicates:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:UNIQUE_ASSET_INDEX_ASOF_EXPOSURE_MATRIX_REQUIRED")
    if exposure_frame.attrs.get("pit_qualified") is not True or not exposure_frame.attrs.get("source_id"):
        raise RiskEstimatorBlocked("BLOCKED_INPUT:EXPOSURE_PIT_QUALIFICATION_AND_SOURCE_REQUIRED")
    available = exposure_frame.attrs.get("available_at")
    bound = pd.Timestamp(config.get("fit_cutoff", index[-1]))
    if available is None or pd.isna(pd.Timestamp(available)) or pd.Timestamp(available).tzinfo != bound.tzinfo or pd.Timestamp(available) > bound:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:EXPOSURE_AVAILABILITY_NOT_BOUND_BEFORE_FIT")
    if len(set(map(str, exposure_frame.columns))) != len(exposure_frame.columns):
        raise RiskEstimatorBlocked("BLOCKED_INPUT:DUPLICATE_EXPOSURE_FACTOR_COLUMNS")
    frame = exposure_frame.copy()
    frame.index = frame.index.map(str)
    if frame.index.has_duplicates:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:DUPLICATE_NORMALIZED_EXPOSURE_ASSETS")
    raw = frame.reindex(assets).to_numpy(float)
    complete = np.isfinite(raw).all(axis=1)
    selected = np.flatnonzero(complete)
    if len(selected) < 2:
        raise RiskEstimatorBlocked("BLOCKED_INPUT:INSUFFICIENT_PIT_EXPOSURE_COVERED_ASSETS")
    raw = raw[selected]
    scales = np.sqrt(np.mean(raw*raw, axis=0))
    active = scales > np.finfo(float).eps
    if not active.any():
        raise RiskEstimatorBlocked("BLOCKED_INPUT:NO_NONZERO_IDENTIFIED_EXPOSURE_FACTOR")
    factor_names = np.asarray(frame.columns, dtype=str)[active].tolist()
    loadings = raw[:, active]/scales[active]
    x = state["centered"][:, selected]
    # Normalize exposure columns before fixed numerical ridge, keeping the
    # portfolio covariance invariant to merely changing factor measurement units.
    inverse = np.linalg.solve(loadings.T@loadings + np.eye(loadings.shape[1])*config["regression_ridge"],
                              loadings.T)
    factor_returns = x@inverse.T
    residual = x-factor_returns@loadings.T
    factor_covariance = np.atleast_2d(np.cov(factor_returns, rowvar=False, ddof=1))
    specific = np.maximum(np.var(residual, axis=0, ddof=1), COMMON["variance_floor"])
    covariance = loadings@factor_covariance@loadings.T+np.diag(specific)
    detail = {"estimated_asset_subset": [assets[i] for i in selected], "factor_names": factor_names,
              "normalized_exposure_loadings": loadings, "exposure_column_scales": scales[active],
              "factor_covariance": factor_covariance, "specific_variance": specific,
              "factor_unit": "caller period-return per normalized exposure",
              "exposure_source_id": frame.attrs["source_id"], "exposure_available_at": str(available),
              "exposure_assets_missing": [name for name, valid in zip(assets, complete) if not valid],
              "factor_columns_with_no_loading": np.asarray(frame.columns, dtype=str)[~active].tolist(),
              "factor_return_regressions": len(index), "physical_crosssectional_solutions": len(index),
              "logical_estimation_count_definition": "exposure normalization, factor covariance, specific variance; factor-return projection is transform"}
    # The inverse depends only on the caller exposure matrix and fixed ridge.
    # Applying it to each return row is a physical transform, not a new fitted
    # mechanism. Count normalization/covariance/specific-variance fitted states;
    # retain every physical cross-sectional solution in diagnostics above.
    return covariance, detail, 3


def _estimate(method, state, index, assets, market_returns, exposure_frame, config):
    x = state["centered"]
    variance = state["marginal_variance"]
    detail = {}
    count = 1
    if method in {"DIAG", "HISTVOL"}:
        covariance = np.diag(variance)
    elif method == "SCOV":
        covariance = np.atleast_2d(np.cov(x, rowvar=False, ddof=1))
    elif method in {"LW", "OAS"}:
        model = (LedoitWolf if method == "LW" else OAS)(assume_centered=True).fit(x)
        covariance = model.covariance_
        detail["shrinkage"] = float(model.shrinkage_)
    elif method == "CONSTANT_CORR":
        sample = np.atleast_2d(np.cov(x, rowvar=False, ddof=1))
        correlation = _correlation(sample)
        n = len(variance)
        rho = float((correlation.sum()-n)/(n*(n-1))) if n > 1 else 0.
        rho = float(np.clip(rho, -1/(n-1), 1)) if n > 1 else 0.
        correlation = np.full((n, n), rho)
        np.fill_diagonal(correlation, 1.)
        covariance = correlation*np.sqrt(np.outer(variance, variance))
        detail["constant_correlation"] = rho
    elif method in {"PCA", "FA"}:
        from sklearn.decomposition import PCA, FactorAnalysis
        if min(x.shape) < config["n_components"]:
            raise RiskEstimatorBlocked("BLOCKED_INPUT:FIXED_FACTOR_COUNT_EXCEEDS_CALLER_MATRIX_DIMENSIONS")
        if method == "PCA":
            model = PCA(n_components=config["n_components"], svd_solver="full", random_state=SEED).fit(x)
            common = model.components_.T@np.diag(model.explained_variance_)@model.components_
            sample_variance = np.var(x, axis=0, ddof=1)
            specific = np.maximum(sample_variance-np.diag(common), COMMON["variance_floor"])
            covariance = common+np.diag(specific)
            detail = {"components": model.components_, "factor_variance": model.explained_variance_,
                      "specific_variance": specific}
        else:
            model = FactorAnalysis(n_components=config["n_components"], max_iter=config["max_iter"],
                                   tol=config["tol"], svd_method="lapack", random_state=SEED).fit(x)
            covariance = model.get_covariance()
            detail = {"components": model.components_, "specific_variance": model.noise_variance_,
                      "iterations": int(model.n_iter_), "fixed_iteration_budget_exhausted": model.n_iter_ >= config["max_iter"]}
            if detail["fixed_iteration_budget_exhausted"]:
                raise RiskEstimatorBlocked("FIT_FAILED:FA_FIXED_ITERATION_BUDGET_EXHAUSTED")
    elif method == "SINGLE_INDEX":
        return _single_index(state, index, market_returns, config)
    elif method in {"INDUSTRY", "FUNDAMENTAL"}:
        return _exposure_factor(state, index, assets, exposure_frame, config)
    elif method == "EWMA":
        weights = config["decay"]**np.arange(len(x)-1, -1, -1, dtype=float)
        if np.any(weights <= 0):
            raise RiskEstimatorBlocked("FIT_FAILED:EWMA_NUMERIC_WEIGHTS_UNDERFLOW_NO_ROWS_DROPPED")
        weights /= weights.sum()
        weighted_mean = weights@x
        demeaned = x-weighted_mean
        covariance = (demeaned.T*weights)@demeaned/(1-float(weights@weights))
        detail = {"decay": config["decay"], "effective_observations": 1/float(weights@weights),
                  "weighted_mean_shift": weighted_mean, "positive_weight_rows": int((weights>0).sum())}
    elif method in {"GARCH", "GJR_GARCH"}:
        sigma = np.sqrt(variance)
        standardized = np.where(state["observed"], x/sigma, np.nan)
        function, definition_sha = _shared_garch_definition()
        parameters, fit = function(standardized, method == "GJR_GARCH")
        if not fit["success"] or not np.isfinite(parameters).all():
            raise RiskEstimatorBlocked("FIT_FAILED:SHARED_GARCH_PARAMETER_ESTIMATION_NOT_CONVERGED")
        h = np.ones(len(variance))
        omega, alpha, beta = parameters[:3]
        gamma = parameters[3] if len(parameters) == 4 else 0.
        for row in standardized:
            observed = np.isfinite(row)
            shock = np.where(observed, row*row, h)
            negative = np.where(observed & (row < 0), row*row, 0.)
            h = np.maximum(omega+alpha*shock+beta*h+gamma*negative, 1e-8)
        lw = LedoitWolf(assume_centered=True).fit(x)
        correlation = _correlation(lw.covariance_)
        covariance = correlation*np.sqrt(np.outer(variance*h, variance*h))
        detail = {"shared_parameters": parameters, "filter_final_h": h, "parameter_fit": fit,
                  "pure_definition_sha256": definition_sha, "correlation_shrinkage": float(lw.shrinkage_)}
        count = 2
    elif method in {"GRAPHICAL_LASSO", "ROBUST_COV"}:
        from sklearn.covariance import GraphicalLasso, MinCovDet
        normalized = x/np.sqrt(variance)
        if method == "GRAPHICAL_LASSO":
            model = GraphicalLasso(alpha=config["alpha"], max_iter=config["max_iter"],
                                   tol=config["tol"], mode=config["mode"], assume_centered=True).fit(normalized)
            if model.n_iter_ >= config["max_iter"]:
                raise RiskEstimatorBlocked("FIT_FAILED:GRAPHICAL_LASSO_FIXED_ITERATION_BUDGET_EXHAUSTED")
            detail["iterations"] = int(model.n_iter_)
        else:
            if len(x) <= x.shape[1]:
                raise RiskEstimatorBlocked("BLOCKED_INPUT:MINCOVDET_REQUIRES_MORE_OBSERVATION_ROWS_THAN_ASSETS")
            model = MinCovDet(support_fraction=config["support_fraction"], assume_centered=True,
                              random_state=SEED).fit(normalized)
            detail["robust_support_rows"] = int(model.support_.sum())
            detail["robust_support_mask"] = model.support_
            detail["all_input_rows_presented"] = len(x)
        covariance = model.covariance_*np.sqrt(np.outer(variance, variance))
        detail["marginal_standardization"] = "prior observed return standard deviations"
    elif method == "COV_ENSEMBLE":
        lw = LedoitWolf(assume_centered=True).fit(x)
        oas = OAS(assume_centered=True).fit(x)
        covariance = .5*(lw.covariance_+oas.covariance_)
        detail = {"component_shrinkage": {"LW": float(lw.shrinkage_), "OAS": float(oas.shrinkage_)},
                  "component_weights": [.5, .5]}
        count = 2
    elif method == "NONLINEAR_SHRINKAGE":
        raise RiskEstimatorBlocked("BLOCKED_DEPENDENCY:GENUINE_NONLINEAR_SHRINKAGE_BACKEND_NOT_SNAPSHOTTED")
    else:
        raise ValueError(f"UNIMPLEMENTED_REGISTERED_RISK_METHOD:{method}")
    return covariance, detail, count


def fit_risk_estimator(method_id, returns_frame, *, market_returns=None,
                       exposure_frame=None, params=None):
    """Estimate from all caller rows; dates alone cannot certify label maturity."""
    method = canonical_method(method_id)
    config = _parameters(method, params)
    names, coverage, state = _prepare(returns_frame, config)
    bundle = RiskBundle(method, "FIT_PENDING", names,
                        tuple(value.isoformat() for value in returns_frame.index),
                        coverage=coverage, specification=config,
                        budget={"preprocessing_estimates": 1, "estimator_state_estimations": 0,
                                "total_state_estimations": 1, "cfg_count": 1, "seed_count": 1})
    bundle.fitted_state = {"return_observation_rows": len(returns_frame),
                           "window_first": bundle.fitted_dates[0], "window_last": bundle.fitted_dates[-1],
                           "return_unit": config.get("return_unit", "CALLER_UNSPECIFIED"),
                           "return_horizon_sessions": config.get("return_horizon_sessions"),
                           "caller_label_maturity_validation_required": True}
    if state is None:
        return _blocked(bundle, "BLOCKED_INPUT", "NO_ASSET_HAS_REQUIRED_PRIOR_OBSERVATIONS")
    bundle.estimated_assets = tuple(names[i] for i in state["positions"])
    bundle.fallback_variance = float(np.median(state["marginal_variance"]))
    bundle.fitted_state.update(mean=state["mean"], prior_marginal_variance=state["marginal_variance"],
                               missing_cells_mean_imputed=state["missing_cells_mean_imputed"])
    with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=2):
        warnings.simplefilter("always")
        try:
            covariance, details, count = _estimate(method, state, returns_frame.index,
                                                   bundle.estimated_assets, market_returns,
                                                   exposure_frame, config)
            covariance, psd = validate_covariance(covariance)
        except RiskEstimatorBlocked as error:
            status, _, reason = str(error).partition(":")
            if status == "FIT_FAILED":
                attempted = 2 if method in {"GARCH", "GJR_GARCH"} else 1
                bundle.budget["estimator_state_estimations"] = attempted
                bundle.budget["total_state_estimations"] += attempted
                bundle.budget["failed_fit_count_convention"] = "conservative attempted state estimates"
            bundle.fitted_state["warnings"] = [{"category": w.category.__name__, "message": str(w.message)} for w in captured]
            return _blocked(bundle, status, reason)
        except (ValueError, np.linalg.LinAlgError, FloatingPointError) as error:
            attempted = locals().get("count", 2 if method in {"COV_ENSEMBLE", "GARCH", "GJR_GARCH"} else 1)
            bundle.budget["estimator_state_estimations"] = attempted
            bundle.budget["total_state_estimations"] += attempted
            bundle.budget["failed_fit_count_convention"] = "conservative attempted state estimates"
            bundle.fitted_state["warnings"] = [{"category": w.category.__name__, "message": str(w.message)} for w in captured]
            return _blocked(bundle, "FIT_FAILED", f"{type(error).__name__}:{error}")
    if "estimated_asset_subset" in details:
        subset = details["estimated_asset_subset"]
        bundle.estimated_assets = tuple(subset)
        bundle.coverage["dependency_available_for_estimation"] = bundle.coverage.asset.isin(subset)
    bundle.covariance = covariance
    bundle.status = "FITTED"
    bundle.fitted_state.update(details)
    bundle.fitted_state.update(psd)
    bundle.fitted_state["warnings"] = [{"category": w.category.__name__, "message": str(w.message)} for w in captured]
    bundle.budget["estimator_state_estimations"] = count
    bundle.budget["total_state_estimations"] += count
    identity = hashlib.sha256(json.dumps({"assets": names, "dates": bundle.fitted_dates,
                                         "method": method, "specification": config},
                                        sort_keys=True, separators=(",", ":")).encode())
    identity.update(np.ascontiguousarray(returns_frame.to_numpy(float)).tobytes())
    if method == "SINGLE_INDEX":
        identity.update(pd.util.hash_pandas_object(market_returns, index=True).to_numpy().tobytes())
        identity.update(str(market_returns.attrs.get("source_id", "")).encode())
    elif method in {"INDUSTRY", "FUNDAMENTAL"}:
        identity.update(pd.util.hash_pandas_object(exposure_frame, index=True).to_numpy().tobytes())
        identity.update(json.dumps({"columns": tuple(map(str, exposure_frame.columns)),
                                   "source_id": exposure_frame.attrs.get("source_id"),
                                   "available_at": str(exposure_frame.attrs.get("available_at"))},
                                  sort_keys=True).encode())
    bundle.fitted_state["fit_identity_sha256"] = identity.hexdigest()
    return bundle


def risk_matrix(bundle, assets, *, return_metadata=False):
    """Frozen covariance in requested order; unknown risk names stay independent."""
    if bundle.status != "FITTED" or bundle.covariance is None:
        raise RiskEstimatorBlocked(f"{bundle.status}:{bundle.failure_reason}")
    requested = tuple(map(str, assets))
    if not requested or len(set(requested)) != len(requested) or any(not name.strip() for name in requested):
        raise ValueError("REQUESTED_RISK_ASSETS_MUST_BE_UNIQUE_NONEMPTY")
    positions = {name: i for i, name in enumerate(bundle.estimated_assets)}
    known = np.array([name in positions for name in requested], bool)
    result = np.eye(len(requested))*bundle.fallback_variance
    destination = np.flatnonzero(known)
    source = [positions[requested[i]] for i in destination]
    result[np.ix_(destination, destination)] = bundle.covariance[np.ix_(source, source)]
    result, psd = validate_covariance(result, regularize=False)
    metadata = {"unknown_assets": [name for name, valid in zip(requested, known) if not valid],
                "fallback_variance": bundle.fallback_variance, "strategy_eligibility_upgraded": False,
                "method_id": bundle.method_id, "return_unit": bundle.fitted_state["return_unit"],
                "return_horizon_sessions": bundle.fitted_state["return_horizon_sessions"], **psd}
    return (result, metadata) if return_metadata else result
