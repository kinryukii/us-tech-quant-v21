"""Bounded direct-decision native estimators; no research I/O or fit on import.

The caller owns legal rows, state/label construction, date/regret weights, annual
folds, attempt budgets, source authority and OOF publication. This module owns
only one frozen learner per objective and preserves native distribution outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.metadata
from pathlib import Path
import warnings

import numpy as np
from scipy.special import ndtr
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from scripts.research.a2.training import stateful_values as values

SEED = 20260928
QUANTILES = (.1, .5, .9)
NORMAL_Q = np.array([-1.2815515655446004, 0., 1.2815515655446004])
OBJECTIVES = ("buy", "hold", "replace", "duration", "distribution", "gross")
LEARNERS = ("linear", "tree", "neural")
NATIVE_SHA256 = "0b90e45b48f6748de2dad86c896502426b0a21cae062ac6f307ef8a52db657a8"


def source_sha256():
    return values.sha(Path(__file__))


def specifications():
    return dict(seed=SEED, objectives=list(OBJECTIVES), learners=list(LEARNERS),
        classification=dict(
            linear=dict(native="logistic", C=1., solver="lbfgs", max_iter=1000),
            tree=dict(native="hgb_cls", max_iter=100, max_leaf_nodes=15,
                      min_samples_leaf=20, early_stopping=False),
            neural=dict(native="mlp_cls", hidden_layer_sizes=[32, 16],
                        max_iter=40, batch_size=256, early_stopping=False,
                        n_iter_no_change=10000, tol=0.)),
        distribution=dict(
            linear=dict(native="linear_q", quantiles=list(QUANTILES),
                        alpha=.0001, solver="highs", p_negative="INTERVAL_ONLY"),
            tree=dict(native="ngboost", rounds=100, distribution="Normal"),
            neural=dict(native="mlp_dist", epochs=12, joint_heads=2,
                        target_scale=.1, native_seed=SEED)),
        preprocessing="TRAIN_ONLY_WEIGHTED_STANDARD_SCALER_LINEAR_NEURAL",
        input="CALLER_FIXED_FINITE_FEATURES_AND_MISSING_FLAGS",
        fit_units=dict(classification=dict(linear=2, tree=1, neural=2),
                       distribution=dict(linear=4, tree=1, neural=2)),
        target_clipping="NONE", calibrator_fits=0, scientific_retries=0,
        cpu_threads=2, native_source_sha256=NATIVE_SHA256,
        neural_final_epoch_only=True, linear_quantile_rearrangement="SORT_THREE_HEADS")


def _native(dependencies):
    if values.sha(values.NATIVE) != NATIVE_SHA256:
        raise ValueError("DECISION_NATIVE_SOURCE_CHANGED")
    native = values._native(dependencies)
    if native.SEED != SEED:
        raise ValueError("DECISION_NATIVE_SEED_CHANGED")
    return native


def _matrix(X, width=None):
    x = np.asarray(X, dtype=float)
    if x.ndim != 2 or x.shape[1] < 1 or (width is not None and x.shape[1] != width):
        raise ValueError("DECISION_FEATURE_MATRIX_SHAPE")
    if not np.isfinite(x).all():
        raise ValueError("DECISION_CALLER_FINITE_INPUT_REQUIRED")
    return x


def _inputs(objective, learner, X, target, weights, features):
    if objective not in OBJECTIVES or learner not in LEARNERS:
        raise ValueError("UNKNOWN_FROZEN_DECISION_OBJECTIVE_OR_LEARNER")
    names = tuple(map(str, features))
    if not names or len(set(names)) != len(names):
        raise ValueError("DECISION_UNIQUE_ORDERED_FEATURES_REQUIRED")
    x = _matrix(X, len(names))
    y, w = np.asarray(target, dtype=float), np.asarray(weights, dtype=float)
    if len(x) < 2 or y.shape != (len(x),) or w.shape != y.shape:
        raise ValueError("DECISION_TARGET_OR_WEIGHT_SHAPE")
    if not np.isfinite(y).all() or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError("DECISION_INVALID_TARGET_OR_WEIGHTS")
    if objective != "distribution":
        allowed = np.arange(5) if objective == "gross" else np.array([0, 1])
        if not np.isin(y, allowed).all() or len(np.unique(y[w > 0])) < 2:
            raise ValueError("DECISION_CLASS_TARGET_OR_POSITIVE_WEIGHT_CLASSES")
        y = y.astype(np.int64)
    return x, y, w, names


@dataclass
class Model:
    objective: str
    learner: str
    estimator: object
    scaler: object
    features: tuple
    dependencies: tuple
    metadata: dict


def fit(objective, learner, X, target, sample_weight, *, features,
        dependencies=(), on_fit_started=None):
    """Fit one declared slot; callbacks run immediately before each actual fit."""
    x, y, weights, names = _inputs(objective, learner, X, target, sample_weight, features)
    dependencies = tuple(map(str, dependencies))
    native = _native(dependencies)
    components = []

    def started(component):
        if on_fit_started is not None:
            on_fit_started(component)
        components.append(component)

    scaler = None
    neural_metadata = {}
    with threadpool_limits(limits=2), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if learner != "tree":
            scaler = StandardScaler()
            started("DECISION_FEATURE_SCALER")
            scaler.fit(x, sample_weight=weights)
            x = scaler.transform(x)
            if not np.isfinite(x).all():
                raise ValueError("DECISION_NONFINITE_SCALED_FEATURES")
        if objective != "distribution":
            native_id = dict(linear="logistic", tree="hgb_cls", neural="mlp_cls")[learner]
            estimator = native.estimator(native_id)
            params = specifications()["classification"][learner].copy()
            params.pop("native")
            if "hidden_layer_sizes" in params:
                params["hidden_layer_sizes"] = tuple(params["hidden_layer_sizes"])
            estimator.set_params(**params, random_state=SEED)
            started("DECISION_CLASSIFIER")
            estimator.fit(x, y, sample_weight=weights)
            if learner == "neural" and estimator.n_iter_ != 40:
                raise RuntimeError("DECISION_MLP_FIXED40_NOT_COMPLETED")
            if learner == "tree" and estimator.n_iter_ != 100:
                raise RuntimeError("DECISION_TREE_FIXED100_NOT_COMPLETED")
            if learner == "linear" and any(type(w.message).__name__ == "ConvergenceWarning" for w in caught):
                raise RuntimeError("DECISION_LINEAR_UNRESOLVED_CONVERGENCE_NO_RETRY")
        elif learner == "linear":
            estimator = []
            for q in QUANTILES:
                head = native.estimator("linear_q", quantile=q)
                started("DECISION_QUANTILE_Q" + str(int(q * 100)))
                head.fit(x, y, sample_weight=weights)
                estimator.append(head)
        elif learner == "tree":
            estimator = native.estimator("ngboost")
            started("DECISION_NGBOOST_NORMAL")
            estimator.fit(x, y, sample_weight=weights)
            if len(estimator.base_models) != 100:
                raise RuntimeError("DECISION_NGBOOST_FIXED100_NOT_COMPLETED")
        else:
            torch = importlib.import_module("torch")
            if torch.version.cuda is not None or not any(
                    Path(torch.__file__).resolve().is_relative_to(Path(p).resolve())
                    for p in dependencies):
                raise ValueError("DECISION_FROZEN_TORCH_CPU_ORIGIN_REQUIRED")
            started("DECISION_GAUSSIAN_NEURAL")
            estimator, neural_metadata = native.fit_torch("mlp_dist", x, y, weights)
            if neural_metadata.get("epochs") != 12:
                raise RuntimeError("DECISION_GAUSSIAN_FIXED12_NOT_COMPLETED")
    metadata = dict(objective=objective, learner=learner, seed=SEED,
        model_role="DIRECT_DECISION_NATIVE_OUTPUT",
        source_sha256=source_sha256(), native_source_sha256=NATIVE_SHA256,
        specifications=specifications(), input_features=list(names),
        training_rows=len(y), weight_sum=float(weights.sum()),
        actual_fit_count=len(components), actual_fit_components=components,
        sklearn_version=importlib.metadata.version("scikit-learn"),
        cpu_threads=2, target_clipped=False, calibration_fits=0,
        scientific_retries=0, training_state_estimation="SCALER_ONLY",
        warnings=[dict(category=type(w.message).__name__, message=str(w.message)) for w in caught],
        neural_metadata=neural_metadata)
    if objective == "distribution" and learner == "tree":
        metadata["ngboost_version"] = importlib.import_module("ngboost").__version__
    if objective == "distribution" and learner == "neural":
        metadata["torch_version"] = importlib.import_module("torch").__version__
    model = Model(objective, learner, estimator, scaler, names, dependencies, metadata)
    # Only an output-shape/finite smoke guard, never training quality or selection.
    predict(model, np.asarray(X, dtype=float)[:2])
    return model


def _native_distribution(model, x):
    native = _native(model.dependencies)
    if model.learner == "linear":
        raw = np.column_stack([head.predict(x) for head in model.estimator])
        q = np.sort(raw, axis=1)
        lower = np.where(q[:, 2] < 0, .9, np.where(q[:, 1] < 0, .5,
                         np.where(q[:, 0] < 0, .1, 0.)))
        upper = np.where(q[:, 0] >= 0, .1, np.where(q[:, 1] >= 0, .5,
                         np.where(q[:, 2] >= 0, .9, 1.)))
        return dict(q10=q[:, 0], q50=q[:, 1], q90=q[:, 2],
            raw_q10=raw[:, 0], raw_q50=raw[:, 1], raw_q90=raw[:, 2],
            p_negative=np.full(len(x), np.nan),
            p_negative_lower=lower, p_negative_upper=upper, width=q[:, 2] - q[:, 0])
    if model.learner == "tree":
        distribution = model.estimator.pred_dist(x)
        loc, scale = np.asarray(distribution.loc), np.asarray(distribution.scale)
    else:
        raw = native.predict_torch(model.estimator, x)
        loc, scale = raw[:, 0] * .1, (np.logaddexp(0., raw[:, 1]) + 1e-3) * .1
    if not np.isfinite(loc).all() or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError("DECISION_NATIVE_DISTRIBUTION_INVALID")
    q = loc[:, None] + scale[:, None] * NORMAL_Q[None, :]
    p = ndtr(-loc / scale)
    return dict(q10=q[:, 0], q50=q[:, 1], q90=q[:, 2], loc=loc, scale=scale,
        p_negative=p, p_negative_lower=p.copy(), p_negative_upper=p.copy(),
        width=q[:, 2] - q[:, 0])


def predict(model, X):
    """Return native probabilities or tail coordinates; never calibrated mu."""
    if type(model) is not Model:
        raise ValueError("DECISION_MODEL_TYPE_REQUIRED")
    if model.metadata.get("source_sha256") != source_sha256() or (
            model.metadata.get("native_source_sha256") != NATIVE_SHA256):
        raise ValueError("DECISION_MODEL_SOURCE_PIN_CHANGED")
    x = _matrix(X, len(model.features))
    _native(model.dependencies)
    if model.metadata.get('seed') != SEED or model.metadata.get('specifications') != specifications():
        raise ValueError('DECISION_MODEL_FROZEN_SPEC_CHANGED')
    if tuple(model.metadata.get('input_features', ())) != model.features:
        raise ValueError('DECISION_MODEL_FEATURE_ORDER_CHANGED')
    if model.metadata.get('sklearn_version') != importlib.metadata.version('scikit-learn'):
        raise ValueError('DECISION_SKLEARN_VERSION_CHANGED')
    if model.objective == 'distribution' and model.learner in ('tree', 'neural'):
        package = 'ngboost' if model.learner == 'tree' else 'torch'
        if model.metadata.get(package + '_version') != importlib.import_module(package).__version__:
            raise ValueError('DECISION_OPTIONAL_BACKEND_VERSION_CHANGED')
    if model.scaler is not None and len(x):
        x = model.scaler.transform(x)
    if not np.isfinite(x).all():
        raise ValueError("DECISION_NONFINITE_INFERENCE_FEATURES")
    if model.objective == "distribution":
        if len(x) == 0:
            keys = ["q10", "q50", "q90", "p_negative", "p_negative_lower",
                    "p_negative_upper", "width"]
            if model.learner == "linear":
                keys += ["raw_q10", "raw_q50", "raw_q90"]
            else:
                keys += ["loc", "scale"]
            return {key: np.empty(0) for key in keys}
        with threadpool_limits(limits=2):
            result = _native_distribution(model, x)
        if any(not np.isfinite(v).all() for key, v in result.items()
               if key != "p_negative" or model.learner != "linear"):
            raise ValueError("DECISION_NONFINITE_DISTRIBUTION_OUTPUT")
        return result
    classes = np.asarray(model.estimator.classes_, dtype=np.int64)
    nclasses = 5 if model.objective == "gross" else 2
    probability = np.zeros((len(x), nclasses))
    if len(x):
        with threadpool_limits(limits=2):
            probability[:, classes] = model.estimator.predict_proba(x)
    if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ValueError("DECISION_CLASS_PROBABILITY_INVALID")
    if len(x) and not np.allclose(probability.sum(axis=1), 1., rtol=1e-10, atol=1e-10):
        raise ValueError("DECISION_CLASS_PROBABILITY_MASS")
    action = probability.argmax(axis=1)
    result = dict(probabilities=probability, classes=np.arange(nclasses), action=action)
    if model.objective == "gross":
        result["gross"] = action / 4.
    else:
        result["p_failure" if model.objective == "duration" else "p_superior"] = probability[:, 1]
    return result


def worker(pipe, operation, model_id, x, y, dates, quantile, dependencies, features, observed):
    """Existing values._fit_job worker_target; no caller budget bypass."""
    def started(component):
        pipe.send(("FIT_START", component))
        if pipe.recv() is not True:
            raise RuntimeError("PARENT_REJECTED_DECISION_FIT_BUDGET")
    try:
        if operation != "decision" or not isinstance(y, dict):
            raise ValueError("DECISION_WORKER_OPERATION_OR_TARGET_SCHEMA")
        if y.get("source_sha256") != source_sha256() or y.get("seed") != SEED:
            raise ValueError("DECISION_FROZEN_SOURCE_OR_SEED_CHANGED")
        if quantile is not None or observed is not None:
            raise ValueError("DECISION_CALLER_QUANTILE_OR_OBSERVED_OVERRIDE_FORBIDDEN")
        model = fit(y["objective"], y["learner"], x, y["target"], y["sample_weight"],
                    features=features, dependencies=dependencies, on_fit_started=started)
        pipe.send(("RESULT", model, dict(model.metadata, model_id=model_id)))
    except BaseException as exc:
        pipe.send(("ERROR", type(exc).__name__, str(exc)))
    finally:
        pipe.close()

