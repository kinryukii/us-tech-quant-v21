"""Small fixed estimator factory and T-only base / C-only sigmoid calibration.

The annual runner owns segment construction and the total fit budget.  This
module checks the supplied segments again, never fits on prediction rows, and
emits one supervised-fit event for each estimator or calibrator invocation.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib
import threading
import warnings

import numpy as np
import pandas as pd
import sklearn
import sklearn.calibration as calibration_api
import sklearn.ensemble._hist_gradient_boosting.binning as hgb_binning
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

SEED = 104729
MAX_THREADS = 2
CUTOFF = pd.Timestamp("2026-01-01T00:00:00Z")
SPEC_ORDER = ("H1", "C1", "C2", "E1", "E2", "S1")
_OPTIMIZER_LOCK = threading.Lock()
_BINNING_LOCK = threading.Lock()


class FitFailure(RuntimeError):
    """A fixed failure reason; the runner records it without changing science."""


def dependency_record():
    records = {}
    for name in ("catboost", "xgboost", "lightgbm"):
        try:
            module = importlib.import_module(name)
            records[name] = {"available": True, "version": module.__version__}
        except (ImportError, OSError) as exc:
            records[name] = {"available": False, "reason": repr(exc)}
    chosen = next((name for name in records if records[name]["available"]), None)
    return {"sklearn": sklearn.__version__, "numpy": np.__version__, "optional_booster": chosen,
            "optional_dependencies": records, "seed": SEED, "cpu_max_threads": MAX_THREADS}


def make_spec(spec_id, view, columns, *, booster=None):
    """Expand one of the six fixed specifications (or the B2 benchmark)."""
    if spec_id not in (*SPEC_ORDER, "B2") or view not in ("A", "B"):
        raise ValueError("Unknown fixed specification or feature view")
    columns = list(columns)
    if not columns or len(columns) != len(set(columns)):
        raise ValueError("Features must be a nonempty unique ordered list")
    if spec_id == "H1":
        family, params, preprocessing = "hgb", dict(max_leaf_nodes=7, max_iter=150,
            learning_rate=0.05, l2_regularization=10, min_samples_leaf=40,
            early_stopping=False, random_state=SEED, class_weight=None), "native_nan"
    elif spec_id in ("C1", "C2"):
        chosen = dependency_record()["optional_booster"]
        if booster is not None and booster != chosen:
            raise ValueError("Booster must follow the frozen installed-dependency priority")
        family, depth, preprocessing = chosen, (2 if spec_id == "C1" else 4), "native_nan"
        if chosen == "catboost":
            params = dict(depth=depth, iterations=300, learning_rate=0.03, l2_leaf_reg=20,
                loss_function="Logloss", task_type="CPU", grow_policy="SymmetricTree",
                use_best_model=False, allow_writing_files=False, has_time=True,
                thread_count=MAX_THREADS, random_seed=SEED, verbose=False, nan_mode="Min")
        elif chosen == "xgboost":
            params = dict(max_depth=depth, n_estimators=300, learning_rate=0.03,
                reg_lambda=20, objective="binary:logistic", tree_method="hist", device="cpu",
                n_jobs=MAX_THREADS, random_state=SEED, early_stopping_rounds=None,
                subsample=1.0, colsample_bytree=1.0, scale_pos_weight=1.0, verbosity=0)
        elif chosen == "lightgbm":
            params = dict(max_depth=depth, num_leaves=2**depth, n_estimators=300,
                learning_rate=0.03, reg_lambda=20, objective="binary", device_type="cpu",
                n_jobs=MAX_THREADS, random_state=SEED, class_weight=None,
                subsample=1.0, colsample_bytree=1.0, verbosity=-1)
        else:
            return {"id": f"{spec_id}_{view}", "spec_id": spec_id, "view": view,
                "columns": columns, "status": "SKIPPED_DEPENDENCY", "family": None}
    elif spec_id in ("E1", "E2"):
        family, preprocessing = "extra_trees", "median_indicator_keep_empty_zero"
        params = dict(max_depth=(3 if spec_id == "E1" else 6), n_estimators=300,
            min_samples_leaf=40, max_features=1.0, bootstrap=False, class_weight=None,
            random_state=SEED, n_jobs=MAX_THREADS)
    elif spec_id == "S1":
        family, preprocessing = "rbf_svc", "median_indicator_keep_empty_zero_standard_scale"
        params = dict(kernel="rbf", C=0.1, gamma="scale", probability=False,
            class_weight=None, tol=0.001, max_iter=100000, random_state=SEED)
    else:
        family, preprocessing = "market_logit", "median_indicator_keep_empty_zero_standard_scale"
        params = dict(C=0.1, max_iter=1500, solver="lbfgs", class_weight=None,
            random_state=SEED)
    return {"id": f"{spec_id}_{view}", "spec_id": spec_id, "view": view,
        "columns": columns, "status": "EXECUTABLE", "family": family,
        "parameters": params, "preprocessing": preprocessing,
        "numerical_compatibility": ({"hgb_all_missing": "native_empty_thresholds_missing_bin_retained",
            "scope": "base_fit_only", "other_columns": "installed_helper_unchanged"}
            if family == "hgb" else None),
        "calibration": {"method": "sigmoid", "estimator": "FrozenEstimator",
            "ensemble": False, "cv": "one_deterministic_score_fold_empty_train_all_C_test",
            "n_jobs": 1, "optimizer_failure": "FAIL", "base_refit_after_calibration": False},
        "weight_rule": "inverse_rows_per_date_then_normalize_current_fit_mean_1"}


def factory(spec):
    """Construct exactly the expanded specification; construction does no fit."""
    expected = make_spec(spec["spec_id"], spec["view"], spec["columns"])
    if spec != expected:
        raise ValueError("Frozen complete model specification mismatch")
    if spec["status"] != "EXECUTABLE":
        raise FitFailure("SKIPPED_DEPENDENCY")
    family, params = spec["family"], spec["parameters"]
    if family == "hgb":
        estimator = HistGradientBoostingClassifier(**params)
    elif family == "catboost":
        estimator = importlib.import_module("catboost").CatBoostClassifier(**params)
    elif family == "xgboost":
        estimator = importlib.import_module("xgboost").XGBClassifier(**params)
    elif family == "lightgbm":
        estimator = importlib.import_module("lightgbm").LGBMClassifier(**params)
    elif family == "extra_trees":
        estimator = ExtraTreesClassifier(**params)
    elif family == "rbf_svc":
        estimator = SVC(**params)
    elif family == "market_logit":
        estimator = LogisticRegression(**params)
    else:
        raise ValueError("Unknown model family")
    if spec["preprocessing"] != "native_nan":
        steps = [("imputer", SimpleImputer(strategy="median", add_indicator=True,
                                          keep_empty_features=True))]
        if spec["preprocessing"].endswith("standard_scale"):
            steps.append(("scale", StandardScaler()))
        steps.append(("model", estimator))
        estimator = Pipeline(steps)
    return estimator


def features(X, columns):
    return X.loc[:, columns].apply(pd.to_numeric, errors="raise").replace([np.inf, -np.inf], np.nan)


def date_weights(dates):
    dates = pd.Series(dates).reset_index(drop=True)
    if dates.empty or dates.isna().any():
        raise ValueError("Missing fit dates")
    weights = 1 / dates.groupby(dates).transform("size").to_numpy(float)
    return weights * (len(weights) / weights.sum())


def _segment(y, dates, label_available_at, *, kind):
    y = np.asarray(y)
    dates = pd.to_datetime(pd.Series(dates).reset_index(drop=True), utc=True)
    maturity = pd.to_datetime(pd.Series(label_available_at).reset_index(drop=True), utc=True)
    if len(y) != len(dates) or len(maturity) != len(dates) or dates.isna().any() or maturity.isna().any():
        raise FitFailure("INVALID_SEGMENT_ROWS_OR_TIMES")
    if not np.array_equal(np.unique(y), np.array([0, 1])):
        raise FitFailure(f"SINGLE_CLASS_OR_INVALID_LABEL_{kind}")
    if not dates.is_monotonic_increasing:
        raise FitFailure("NONCHRONOLOGICAL_TRAINING_ROWS")
    if (dates >= CUTOFF).any() or (maturity >= CUTOFF).any():
        raise FitFailure("PRE2026_MATURITY_BOUNDARY")
    expected = dates.dt.tz_convert(None).dt.strftime("%Y-%m-%d")
    local_maturity_date = maturity.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    if not expected.equals(local_maturity_date):
        raise FitFailure("LABEL_MATURITY_DATE_MISMATCH")
    count = dates.nunique()
    if (kind == "T" and count < 120) or (kind == "C" and count != 60):
        raise FitFailure(f"INSUFFICIENT_OR_INVALID_DATE_COUNT_{kind}")
    return dates, maturity, {"rows": len(y), "dates": count,
        "first_date": expected.iloc[0], "last_date": expected.iloc[-1],
        "max_label_available_at": maturity.max().isoformat()}


def _weight(dates, supplied):
    expected = date_weights(dates)
    if supplied is not None and not np.allclose(np.asarray(supplied, float), expected, rtol=1e-12, atol=1e-12):
        raise ValueError("Weights must be date-equal with current-fit mean exactly one")
    return expected


@dataclass
class BaseFit:
    spec: dict
    estimator: object
    metadata: dict


@dataclass
class CalibratedFit:
    base: BaseFit
    calibrator: object
    metadata: dict


def _event(callback, kind, status, spec, **fields):
    if callback is not None:
        callback({"kind": kind, "status": status, "candidate_id": spec["id"], **fields})


@contextmanager
def _native_empty_hgb_bins(spec, records):
    """Repair sklearn 1.9's empty distinct-values midpoint calculation locally.

    No observed numeric values imply no numeric split thresholds.  The native
    mapper retains the column and its separate missing-value bin.  Nonempty
    columns, including constant columns, use the installed function unchanged.
    """
    if spec["family"] != "hgb":
        yield
        return
    with _BINNING_LOCK:
        original = hgb_binning._find_binning_thresholds
        def checked(col_data, max_bins, sample_weight=None):
            valid = ~np.isnan(col_data)
            if sample_weight is not None:
                valid &= np.asarray(sample_weight) != 0
            if not valid.any():
                records.append({"kind": "empty_native_numeric_thresholds", "observed_values": 0})
                return np.empty(0, dtype=hgb_binning.X_DTYPE)
            return original(col_data, max_bins, sample_weight=sample_weight)
        hgb_binning._find_binning_thresholds = checked
        try:
            yield
        finally:
            hgb_binning._find_binning_thresholds = original


def fit_base(spec, X, y, dates, *, label_available_at, sample_weight=None, on_fit=None):
    dates, maturity, metadata = _segment(y, dates, label_available_at, kind="T")
    matrix = features(X, spec["columns"])
    if len(matrix) != len(y):
        raise FitFailure("INVALID_FEATURE_ROWS")
    weight, estimator = _weight(dates, sample_weight), factory(spec)
    compatibility_records = []
    _event(on_fit, "base", "STARTED", spec, segment=metadata)
    try:
        with threadpool_limits(limits=MAX_THREADS), _native_empty_hgb_bins(spec, compatibility_records), warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            if isinstance(estimator, Pipeline):
                estimator.fit(matrix, np.asarray(y, int), model__sample_weight=weight)
            else:
                estimator.fit(matrix, np.asarray(y, int), sample_weight=weight)
        if any(issubclass(w.category, ConvergenceWarning) for w in seen):
            raise FitFailure("BASE_OPTIMIZER_DID_NOT_CONVERGE")
        core = estimator.steps[-1][1] if isinstance(estimator, Pipeline) else estimator
        if getattr(core, "fit_status_", 0) != 0:
            raise FitFailure("BASE_OPTIMIZER_DID_NOT_CONVERGE")
        if not np.array_equal(np.asarray(estimator.classes_), [0, 1]):
            raise FitFailure("INVALID_CLASS_DIRECTION")
        metadata.update(weight_mean=float(weight.mean()), weight_sum=float(weight.sum()),
            warnings=[str(w.message) for w in seen], cpu_max_threads=MAX_THREADS,
            estimator_parameters=core.get_params(deep=False), numerical_compatibility=compatibility_records)
        if spec["family"] == "catboost":
            metadata["effective_parameters"] = core.get_all_params()
        _event(on_fit, "base", "FINISHED", spec, segment=metadata)
        return BaseFit(spec, estimator, metadata)
    except Exception as exc:
        _event(on_fit, "base", "FAILED", spec, reason=f"{type(exc).__name__}: {exc}")
        raise


@contextmanager
def _checked_sigmoid_optimizer(records):
    """Observe the official optimizer's status, which sklearn otherwise drops.

    Fits are serialized for this scoped module binding and it is always restored.
    No objective, solver option, starting point or fitted coefficient is changed.
    """
    with _OPTIMIZER_LOCK:
        original = calibration_api.minimize
        def checked(*args, **kwargs):
            result = original(*args, **kwargs)
            records.append({"success": bool(result.success), "status": int(result.status),
                "message": str(result.message), "iterations": int(getattr(result, "nit", 0)),
                "objective": float(result.fun)})
            if not result.success or not np.isfinite(result.x).all() or not np.isfinite(result.fun):
                raise FitFailure("CALIBRATION_OPTIMIZER_FAILED")
            return result
        calibration_api.minimize = checked
        try:
            yield
        finally:
            calibration_api.minimize = original


def fit_calibrator(base, X, y, dates, *, label_available_at, sample_weight=None, on_fit=None):
    dates, maturity, metadata = _segment(y, dates, label_available_at, kind="C")
    first_issue = pd.Timestamp(metadata["first_date"] + " 09:45", tz="America/New_York").tz_convert("UTC")
    if base.metadata["last_date"] >= metadata["first_date"] or pd.Timestamp(base.metadata["max_label_available_at"]) >= first_issue:
        raise FitFailure("T_C_OVERLAP_OR_UNMATURED_LABEL")
    matrix, weight = features(X, base.spec["columns"]), _weight(dates, sample_weight)
    if len(matrix) != len(y):
        raise FitFailure("INVALID_FEATURE_ROWS")
    # Exactly one score partition: a FrozenEstimator's fit(empty) is a no-op.
    # This bypasses the default StratifiedKFold without fitting or scoring on T.
    cv = [(np.empty(0, dtype=int), np.arange(len(y), dtype=int))]
    calibrator = CalibratedClassifierCV(FrozenEstimator(base.estimator), method="sigmoid",
        cv=cv, n_jobs=1, ensemble=False)
    optimizer_records = []
    _event(on_fit, "calibration", "STARTED", base.spec, segment=metadata)
    try:
        with threadpool_limits(limits=MAX_THREADS), _checked_sigmoid_optimizer(optimizer_records), warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            calibrator.fit(matrix, np.asarray(y, int), sample_weight=weight)
        if any(issubclass(w.category, ConvergenceWarning) for w in seen) or len(optimizer_records) != 1:
            raise FitFailure("CALIBRATION_OPTIMIZER_UNVERIFIED")
        if not np.array_equal(np.asarray(calibrator.classes_), [0, 1]):
            raise FitFailure("INVALID_CLASS_DIRECTION")
        sigmoid = calibrator.calibrated_classifiers_[0].calibrators[0]
        if not np.isfinite([sigmoid.a_, sigmoid.b_]).all():
            raise FitFailure("NONFINITE_CALIBRATION_COEFFICIENT")
        metadata.update(weight_mean=float(weight.mean()), weight_sum=float(weight.sum()),
            sigmoid_a=float(sigmoid.a_), sigmoid_b=float(sigmoid.b_),
            effective_score_slope=float(-sigmoid.a_), direction_reversal=bool(sigmoid.a_ > 0),
            optimizer=optimizer_records, warnings=[str(w.message) for w in seen],
            base_fit_cutoff=base.metadata["max_label_available_at"],
            calibration_cutoff=metadata["max_label_available_at"],
            score_kind=("decision_margin" if hasattr(base.estimator, "decision_function") else "positive_class_probability"))
        _event(on_fit, "calibration", "FINISHED", base.spec, segment=metadata)
        return CalibratedFit(base, calibrator, metadata)
    except Exception as exc:
        _event(on_fit, "calibration", "FAILED", base.spec,
               reason=f"{type(exc).__name__}: {exc}", optimizer=optimizer_records)
        raise


def predict(bundle, X):
    """Replay only; raw SVC margins are deliberately never called probabilities."""
    matrix, estimator = features(X, bundle.base.spec["columns"]), bundle.base.estimator
    if not np.array_equal(np.asarray(estimator.classes_), [0, 1]):
        raise FitFailure("INVALID_CLASS_DIRECTION")
    with threadpool_limits(limits=MAX_THREADS):
        raw_probability = (np.asarray(estimator.predict_proba(matrix))[:, 1]
            if hasattr(estimator, "predict_proba") else np.full(len(matrix), np.nan))
        raw_score = (np.asarray(estimator.decision_function(matrix)).reshape(-1)
            if hasattr(estimator, "decision_function") else raw_probability.copy())
        calibrated = np.asarray(bundle.calibrator.predict_proba(matrix))[:, 1]
    if not np.isfinite(raw_score).all() or not np.isfinite(calibrated).all() or ((calibrated < 0) | (calibrated > 1)).any():
        raise FitFailure("INVALID_PREDICTIONS")
    return {"raw_score": raw_score, "p_raw": raw_probability, "p_up": calibrated,
            "p_not_up": 1 - calibrated, "predicted_up": (calibrated >= 0.5).astype(int)}
