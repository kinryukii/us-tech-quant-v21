"""Fixed pure-selector formulations missing from the retained predictor factory.

The caller owns canonical column order, predeclared common sampled keys, fold
cutoffs, label maturity, and UID/session-correct PIT lag construction. This
module performs no I/O, sampling, model selection, calibration or allocation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
import warnings

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA, FactorAnalysis
from sklearn.ensemble import IsolationForest
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Ridge
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

SEED = 20260928
FEATURE_COUNT = 32
MAX_TRAIN_ROWS = 40000
SEQUENCE_NAMES = ("tcn", "lstm", "gru")
AUXILIARY_NAMES = ("pca_ridge", "fa_ridge", "kmeans_ridge", "gmm_ridge", "iforest_ridge")
NAMES = ("svc",) + SEQUENCE_NAMES + AUXILIARY_NAMES
SPEC = {
    "seed": SEED,
    "max_train_rows": MAX_TRAIN_ROWS,
    "sampling": "caller-provided identical deterministic day-balanced common keys; no internal sampling",
    "feature_count": FEATURE_COUNT,
    "feature_order": "caller-bound canonical Raw A2 32 features",
    "selection": "one fixed configuration per name; no search or retries",
    "svc": {
        "kernel": "rbf", "C": 1.0, "gamma": "scale", "probability": False,
        "cache_size": 256, "max_iter": 1000, "tol": 0.001,
        "class_weight": None, "shrinking": True, "random_state": SEED,
        "label": "raw selector target > 0",
        "score": "decision_function; higher means positive class",
        "preprocessing": "StandardScaler fit on caller-provided training rows only",
        "convergence_warning": "fail; no continuation",
    },
    "sequence": {
        "lag_sessions": 8, "feature_count": FEATURE_COUNT,
        "order": "oldest to current decision session; caller-owned same-UID PIT past joins",
        "mask": "shape N,8,32; one=missing, zero=available; masked values forced to zero",
        "input_channels": 64,
        "missing_policy": "retain every caller-provided prediction key, including all-missing lags",
        "normalization": "caller provides train-only normalized finite lags; no internal feature scaler",
        "target_standardization": "weighted training mean/std only, scale floor 1e-8",
        "hidden": 16, "epochs": 10, "batch_size": 512,
        "learning_rate": 0.001, "weight_decay": 0.0001,
        "optimizer": "AdamW", "loss": "weighted MSE on standardized target",
        "gradient_clip_norm": 2.0, "device": "cpu", "threads": 2,
        "deterministic_algorithms": True, "final_epoch_only": True,
        "tcn": {
            "layers": 2, "kernel_size": 3, "dilations": [1, 3],
            "causal_left_padding": [2, 6], "receptive_field": 9,
            "activation": "ReLU", "readout": "last session Linear(16,1)",
            "dropout": 0.0,
        },
        "lstm": {"layers": 1, "bias": True, "bidirectional": False,
                 "dropout": 0.0, "readout": "last session Linear(16,1)"},
        "gru": {"layers": 1, "bias": True, "bidirectional": False,
                "dropout": 0.0, "readout": "last session Linear(16,1)"},
    },
    "auxiliary": {
        "input": "same canonical 32 finite training features",
        "feature_scaler": "weighted fold-local StandardScaler",
        "unsupervised_fit": "unweighted caller-provided fixed common training keys",
        "augmentation": "original 32 standardized features followed by auxiliary outputs",
        "augmented_scaler": "weighted fold-local StandardScaler",
        "ridge": {"alpha": 100.0, "solver": "lsqr", "tol": 1e-6,
                  "max_iter": 1000, "fit_intercept": True},
        "pca_ridge": {"n_components": 16, "svd_solver": "randomized",
                      "iterated_power": 3, "random_state": SEED},
        "fa_ridge": {"n_components": 8, "max_iter": 60, "tol": 0.01,
                     "svd_method": "randomized", "random_state": SEED},
        "kmeans_ridge": {"n_clusters": 3, "n_init": 10, "max_iter": 100,
                         "algorithm": "lloyd", "random_state": SEED},
        "gmm_ridge": {"n_components": 3, "covariance_type": "diag", "n_init": 1,
                      "max_iter": 100, "tol": 0.001, "reg_covar": 1e-6,
                      "init_params": "kmeans", "random_state": SEED},
        "iforest_ridge": {"n_estimators": 64, "max_samples": 256,
                          "max_features": 1.0, "contamination": "auto",
                          "bootstrap": False, "n_jobs": 2, "random_state": SEED},
        "outputs": {"pca_ridge": "16 components", "fa_ridge": "8 latent factors",
                    "kmeans_ridge": "3 cluster distances",
                    "gmm_ridge": "3 mixture probabilities",
                    "iforest_ridge": "one score_samples anomaly score"},
    },
}


def _matrix(values):
    x = np.asarray(values, dtype=float)
    if x.ndim != 2 or x.shape[1] != FEATURE_COUNT or not np.isfinite(x).all():
        raise ValueError("FINITE_CANONICAL_32_FEATURE_MATRIX_REQUIRED")
    return x


def _sequence(values, missing_mask):
    x = np.asarray(values, dtype=np.float32)
    mask = np.asarray(missing_mask, dtype=np.float32)
    if x.ndim != 3 or x.shape[1:] != (8, FEATURE_COUNT) or mask.shape != x.shape:
        raise ValueError("SEQUENCE_AND_MASK_REQUIRE_SHAPE_N_8_32")
    if not np.isfinite(x).all() or not np.isfinite(mask).all() or not np.isin(mask, [0, 1]).all():
        raise ValueError("FINITE_NORMALIZED_LAGS_AND_BINARY_MISSING_MASK_REQUIRED")
    x = np.where(mask == 1, 0.0, x)
    return np.concatenate([x, mask], axis=2)


def _training(y, count, sample_weight):
    target = np.asarray(y, dtype=float)
    weight = np.ones(count, dtype=float) if sample_weight is None else np.asarray(sample_weight, dtype=float)
    if not 0 < count <= MAX_TRAIN_ROWS or target.shape != (count,) or weight.shape != target.shape:
        raise ValueError("PREDECLARED_TRAINING_ROWS_OR_TARGET_WEIGHT_SHAPE_INVALID")
    if not np.isfinite(target).all() or not np.isfinite(weight).all() or np.any(weight <= 0):
        raise ValueError("FINITE_TARGET_AND_POSITIVE_WEIGHTS_REQUIRED")
    return target, weight / weight.mean()


def _finite_score(values, count):
    result = np.asarray(values, dtype=float)
    if result.shape != (count,) or not np.isfinite(result).all():
        raise RuntimeError("FORMULATION_MUST_SCORE_EVERY_INPUT_KEY_WITH_A_FINITE_SCALAR")
    return result


def _auxiliary(name):
    parameters = deepcopy(SPEC["auxiliary"][name])
    factories = {"pca_ridge": PCA, "fa_ridge": FactorAnalysis,
                 "kmeans_ridge": KMeans, "gmm_ridge": GaussianMixture,
                 "iforest_ridge": IsolationForest}
    return factories[name](**parameters)


def _augmentation(name, auxiliary, x):
    if name == "gmm_ridge":
        extra = auxiliary.predict_proba(x)
    elif name == "iforest_ridge":
        extra = auxiliary.score_samples(x)[:, None]
    else:
        extra = auxiliary.transform(x)
    return np.column_stack([x, extra])


@dataclass
class TabularFit:
    name: str
    scaler: object
    estimator: object
    auxiliary: object = None
    augmented_scaler: object = None
    metadata: dict = field(default_factory=dict)

    def predict(self, X, *, missing_mask=None):
        x = _matrix(X)
        if not len(x):
            return np.empty(0, dtype=float)
        with threadpool_limits(limits=2):
            z = self.scaler.transform(x)
            if self.name == "svc":
                value = self.estimator.decision_function(z)
            else:
                z = self.augmented_scaler.transform(_augmentation(self.name, self.auxiliary, z))
                value = self.estimator.predict(z)
        return _finite_score(value, len(x))


def _network(name):
    import torch
    from torch import nn

    class SequenceNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            if name == "tcn":
                self.first = nn.Conv1d(64, 16, kernel_size=3, dilation=1)
                self.second = nn.Conv1d(16, 16, kernel_size=3, dilation=3)
            else:
                recurrent = nn.LSTM if name == "lstm" else nn.GRU
                self.recurrent = recurrent(64, 16, num_layers=1, batch_first=True,
                                           bidirectional=False, dropout=0.0, bias=True)
            self.output = nn.Linear(16, 1)

        def forward(self, x):
            if name == "tcn":
                z = x.transpose(1, 2)
                z = torch.relu(self.first(nn.functional.pad(z, (2, 0))))
                z = torch.relu(self.second(nn.functional.pad(z, (6, 0))))
                z = z[:, :, -1]
            else:
                z, _ = self.recurrent(x)
                z = z[:, -1, :]
            return self.output(z).flatten()

    if name not in SEQUENCE_NAMES:
        raise ValueError("UNKNOWN_SEQUENCE_FORMULATION")
    return SequenceNetwork()


@dataclass
class SequenceFit:
    name: str
    state: dict
    target_mean: float
    target_scale: float
    metadata: dict = field(default_factory=dict)
    _model: object = field(default=None, repr=False, compare=False)

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_model"] = None
        return state

    def predict(self, X, *, missing_mask):
        import torch
        x = _sequence(X, missing_mask)
        if not len(x):
            return np.empty(0, dtype=float)
        torch.set_num_threads(2)
        if self._model is None:
            self._model = _network(self.name)
            self._model.load_state_dict({k: torch.from_numpy(v.copy()) for k, v in self.state.items()})
            self._model.eval()
        parts = []
        with torch.no_grad():
            for start in range(0, len(x), 512):
                value = self._model(torch.from_numpy(x[start:start + 512]))
                parts.append(value.numpy().astype(float) * self.target_scale + self.target_mean)
        return _finite_score(np.concatenate(parts), len(x))


def fit(name, X, y, *, missing_mask=None, sample_weight=None):
    """One bounded fit on caller-owned purged, predeclared common training keys."""
    if name not in NAMES:
        raise ValueError("UNKNOWN_SELECTOR_FORMULATION")
    x = _sequence(X, missing_mask) if name in SEQUENCE_NAMES else _matrix(X)
    target, weight = _training(y, len(x), sample_weight)
    metadata = {"name": name, "train_rows": len(x), "spec": deepcopy(SPEC),
                "internal_sample_selection": False, "supervised_estimator_fit_count": 1,
                "seed": SEED, "warnings": []}
    if name in SEQUENCE_NAMES:
        import torch
        torch.manual_seed(SEED)
        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(True)
        mean = float(np.average(target, weights=weight))
        scale = max(float(np.sqrt(np.average((target - mean) ** 2, weights=weight))), 1e-8)
        xx = torch.from_numpy(x)
        yy = torch.tensor((target - mean) / scale, dtype=torch.float32)
        ww = torch.tensor(weight, dtype=torch.float32)
        model = _network(name)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.0001)
        generator = torch.Generator().manual_seed(SEED)
        model.train()
        for _ in range(10):
            order = torch.randperm(len(xx), generator=generator)
            for start in range(0, len(xx), 512):
                ids = order[start:start + 512]
                optimizer.zero_grad(set_to_none=True)
                loss = torch.sum(ww[ids] * (model(xx[ids]) - yy[ids]) ** 2) / ww[ids].sum()
                if not torch.isfinite(loss):
                    raise RuntimeError("NONFINITE_SEQUENCE_TRAINING_LOSS")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                optimizer.step()
        state = {k: v.detach().cpu().numpy().copy() for k, v in model.state_dict().items()}
        metadata.update(epochs=10, optimizer_steps=10 * math.ceil(len(x) / 512),
                        internal_feature_scaler_fit_count=0, target_scaler_fit_count=1)
        return SequenceFit(name, state, mean, scale, metadata)
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
        warnings.simplefilter("always")
        scaler = StandardScaler().fit(x, sample_weight=weight)
        z = scaler.transform(x)
        if name == "svc":
            event = (target > 0).astype(int)
            if not np.array_equal(np.unique(event), [0, 1]):
                raise ValueError("SVC_REQUIRES_BOTH_FROZEN_LABEL_CLASSES")
            parameters = {k: deepcopy(SPEC["svc"][k]) for k in
                          ("kernel", "C", "gamma", "probability", "cache_size", "max_iter",
                           "tol", "class_weight", "shrinking", "random_state")}
            model = SVC(**parameters).fit(z, event, sample_weight=weight)
            if model.fit_status_ != 0 or any(issubclass(w.category, ConvergenceWarning) for w in caught):
                raise RuntimeError("SVC_FIXED_BUDGET_DID_NOT_CONVERGE")
            result = TabularFit(name, scaler, model, metadata=metadata)
            metadata.update(feature_scaler_fit_count=1, unsupervised_fit_count=0)
        else:
            components = SPEC["auxiliary"][name].get("n_components", 3)
            if len(z) <= components:
                raise ValueError("AUXILIARY_FIXED_COMPONENT_BUDGET_REQUIRES_MORE_TRAIN_ROWS")
            auxiliary = _auxiliary(name).fit(z)
            augmented = _augmentation(name, auxiliary, z)
            augmented_scaler = StandardScaler().fit(augmented, sample_weight=weight)
            model = Ridge(**SPEC["auxiliary"]["ridge"]).fit(
                augmented_scaler.transform(augmented), target, sample_weight=weight)
            result = TabularFit(name, scaler, model, auxiliary, augmented_scaler, metadata)
            metadata.update(feature_scaler_fit_count=2, unsupervised_fit_count=1,
                            augmented_feature_count=augmented.shape[1])
        metadata["warnings"] = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    return result
