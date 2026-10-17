"""C12 single-component estimators on already frozen Raw-boundary pair rows.

Reuse native factories and C10 capacity/architecture conventions; this module
owns no data reader, pair construction, scaler, model selection or resolver.
The runner binds pair geometry, common 20D maturity and every chronological
cutoff before passing labels. No default retired runtime is loaded here.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import math
import warnings
import numpy as np
import pandas as pd
from scripts.research.a2.training import selector_algorithm_objectives as obj

PARADIGMS = ("LOGIT", "RIDGE", "HUBER", "HGB", "XGB", "CAT", "MLP", "MULTITASK_MLP", "QUANTILE_HGB")
CAPACITIES = ("LOW", "MID", "HIGH")
SEEDS = (20260928, 20260929, 20260930)
QUANTILES = (.1, .5, .9)
STOCHASTIC = ("CAT", "MLP", "MULTITASK_MLP")
FEATURE_COUNT = 114  # 3 blocks: BASE32 + rank/score/change2 + two past-availability flags
WEIGHT_POLICY = "date mass 1; equal challenger mass; equal incumbent mass within challenger; no outcome weighting"
REGULARIZATION_POLICY = "native absolute sample_weight, never rescaled to N; fixed native alpha/C semantics"


def _runtime(runtime):
    if runtime is None:
        raise ValueError("BLOCKED_QUALIFIED_NATIVE_RUNTIME_REQUIRED")
    return obj._predictors(runtime)


def capacity_specs(runtime):
    """Native defaults plus exactly three mechanical, outcome-blind tiers."""
    pred = _runtime(runtime)
    names = dict(LOGIT="logistic", RIDGE="ridge", HUBER="huber", HGB="hgb", XGB="xgb", CAT="cat", QUANTILE_HGB="hgb")
    specs = {}
    for role, name in names.items():
        native = copy.deepcopy(pred.hyperparameters(name))
        native.pop("convergence_extension_max_iter", None)
        specs[role] = {}
        for capacity, factor, rounds, depth, leaves in zip(CAPACITIES, (10., 1., .1), (64, 128, 256), (3, 4, 5), (15, 31, 63)):
            spec = copy.deepcopy(native)
            if role == "LOGIT": spec["C"] = native["C"] / factor
            elif role in ("RIDGE", "HUBER"): spec["alpha"] = native["alpha"] * factor
            elif role in ("HGB", "QUANTILE_HGB"):
                spec.update(max_iter=rounds, max_depth=depth, max_leaf_nodes=leaves)
            elif role == "XGB": spec.update(n_estimators=rounds, max_depth=depth)
            elif role == "CAT": spec.update(iterations=rounds, depth=depth)
            specs[role][capacity] = spec
    native_nn = obj.role_specs()["PAIRWISE_MLP"]["capacity"]
    for role in ("MLP", "MULTITASK_MLP"):
        specs[role] = {}
        for capacity, hidden, epochs in zip(CAPACITIES, (32, 64, 128), (10, 20, 30)):
            spec = copy.deepcopy(native_nn)
            spec.update(hidden=hidden, epochs=epochs, input_features=FEATURE_COUNT,
                        outputs=4 if role == "MULTITASK_MLP" else 1,
                        target_standardization="NONE", objective="DATE_WEIGHTED_MEAN_SQUARED_EDGE",
                        row_permutation="torch.randperm; fixed component seed; configured fixed epochs")
            specs[role][capacity] = spec
    return specs


def pair_weights(dates, challenger_uids, incumbent_uids):
    """All fixed 20x10 pairs survive; weight is independent of target values."""
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    challenger, incumbent = np.asarray(challenger_uids, dtype=object), np.asarray(incumbent_uids, dtype=object)
    if (not len(clock) or clock.hasnans or clock.tz is not None
            or (clock >= pd.Timestamp("2026-01-01")).any()
            or challenger.shape != (len(clock),) or incumbent.shape != (len(clock),)):
        raise ValueError("PRE2026_COMPLETE_PAIR_CLOCK_REQUIRED")
    if (not all(isinstance(u, str) and bool(u.strip()) for u in challenger)
            or not all(isinstance(u, str) and bool(u.strip()) for u in incumbent)):
        raise ValueError("PAIR_SECURITY_UID_REQUIRED")
    frame = pd.DataFrame(dict(date=clock, challenger=challenger, incumbent=incumbent))
    if frame.duplicated(["date", "challenger", "incumbent"]).any():
        raise ValueError("DUPLICATE_FROZEN_PAIR")
    weights = np.empty(len(frame), dtype=float)
    for _, indices in frame.groupby("date", sort=False).indices.items():
        group = frame.iloc[indices]
        if (len(group) != 200 or group.challenger.nunique() != 20 or group.incumbent.nunique() != 10
                or set(group.challenger) & set(group.incumbent)
                or not group.groupby("challenger").incumbent.nunique().eq(10).all()):
            raise ValueError("FROZEN_FULL_20_CHALLENGER_10_INCUMBENT_GEOMETRY_REQUIRED")
        counts = group.groupby("challenger").incumbent.transform("size").to_numpy(float)
        weights[indices] = 1. / (group.challenger.nunique() * counts)
    return weights


def _x(X):
    x = np.asarray(X, dtype=float)
    if x.ndim != 2 or x.shape[1] != FEATURE_COUNT or not np.isfinite(x).all():
        raise ValueError("FINITE_FROZEN_114_PAIR_FEATURES_REQUIRED")
    return x


@dataclass
class FittedBoundary:
    paradigm: str
    capacity: str
    seed: int
    quantile: float | None
    estimator: object
    metadata: dict
    neural: bool = False


def _network(hidden, outputs):
    from torch import nn
    return nn.Sequential(nn.Linear(FEATURE_COUNT, hidden), nn.ReLU(),
                         nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, outputs))


def weighted_edge_loss(prediction, target, weights, *, training_rows, training_date_mass):
    """Uniform row minibatch estimator of full date-average, also for four tasks."""
    error = (prediction - target).square().mean(dim=1)
    return (error * weights).sum() * training_rows / (training_date_mass * len(error))


def _fit_neural(x, target, weights, spec, seed, event, on_fit_call):
    import torch
    torch.set_num_threads(spec["threads"])
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    network = _network(spec["hidden"], spec["outputs"])
    xx = torch.tensor(np.clip(x, *spec["feature_clip"]), dtype=torch.float32)
    yy = torch.tensor(target.reshape(len(x), spec["outputs"]), dtype=torch.float32)
    ww = torch.tensor(weights, dtype=torch.float32)
    optimizer = torch.optim.Adam(network.parameters(), lr=spec["learning_rate"], weight_decay=spec["weight_decay"])
    generator = torch.Generator().manual_seed(seed)
    metadata = dict(epochs=spec["epochs"], updates=0, epoch_losses=[],
                    parameter_count=sum(p.numel() for p in network.parameters()),
                    update_budget=spec["epochs"] * math.ceil(len(x) / spec["batch_size"]))
    if on_fit_call is not None: on_fit_call(event)
    network.train()
    for _ in range(spec["epochs"]):
        order = torch.randperm(len(xx), generator=generator)
        total, count = 0., 0
        for start in range(0, len(xx), spec["batch_size"]):
            indices = order[start:start + spec["batch_size"]]
            optimizer.zero_grad()
            loss = weighted_edge_loss(network(xx[indices]), yy[indices], ww[indices],
                                      training_rows=len(x), training_date_mass=float(weights.sum()))
            if not torch.isfinite(loss): raise RuntimeError("NONFINITE_BOUNDARY_NEURAL_LOSS_NO_RETRY")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), spec["gradient_clip_norm"])
            optimizer.step()
            total += float(loss.detach()) * len(indices); count += len(indices)
            metadata["updates"] += 1
        metadata["epoch_losses"].append(total / count)
    network.eval()
    metadata["backend"] = dict(module="torch", version=torch.__version__, origin=str(torch.__file__))
    return network, metadata


def fit(paradigm, X_scaled, y, dates, challenger_uids, incumbent_uids, capacity="LOW", *,
        runtime=None, seed=SEEDS[0], quantile=None, on_fit_call=None):
    """Exactly one seed/quantile estimator; validation never substitutes rows."""
    if paradigm not in PARADIGMS or capacity not in CAPACITIES:
        raise ValueError("FROZEN_BOUNDARY_PARADIGM_AND_CAPACITY_REQUIRED")
    if seed not in (SEEDS if paradigm in STOCHASTIC else (SEEDS[0],)):
        raise ValueError("FROZEN_REQUIRED_SEED_POLICY")
    if (paradigm == "QUANTILE_HGB" and quantile not in QUANTILES) or (paradigm != "QUANTILE_HGB" and quantile is not None):
        raise ValueError("ONE_PREDECLARED_QUANTILE_PER_COMPONENT_REQUIRED")
    pred = _runtime(runtime)
    x = _x(X_scaled)
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    weights = pair_weights(clock, challenger_uids, incumbent_uids)
    target = np.asarray(y, dtype=float)
    shape = (len(x), 4) if paradigm == "MULTITASK_MLP" else (len(x),)
    if len(clock) != len(x) or target.shape != shape or not np.isfinite(target).all():
        raise ValueError("BLOCKED_LABEL_ALL_FROZEN_PAIR_EDGES_REQUIRED")
    if paradigm == "LOGIT" and len(np.unique(target > 0)) != 2:
        raise ValueError("BLOCKED_LABEL_LOGIT_BOTH_CLASSES_REQUIRED_NO_REBALANCE")
    spec = capacity_specs(pred)[paradigm][capacity]
    if paradigm == "CAT": spec["random_seed"] = seed
    if paradigm in ("MLP", "MULTITASK_MLP"): spec["seed"] = seed
    if paradigm == "QUANTILE_HGB": spec.update(loss="quantile", quantile=quantile)
    event = dict(operation="estimator_fit", paradigm=paradigm, capacity=capacity, seed=seed, quantile=quantile)
    metadata = dict(paradigm=paradigm, capacity=capacity, seed=seed, quantile=quantile,
                    spec=copy.deepcopy(spec), estimator_fit_calls=1, scaler_fit_calls=0,
                    target_stat_estimation=0, scientific_retries=0, training_rows=len(x),
                    training_dates=clock.nunique(), external_rows_dropped=0, row_weight_sum=float(weights.sum()),
                    row_weight_min=float(weights.min()), row_weight_max=float(weights.max()),
                    external_row_weight=WEIGHT_POLICY, regularization_policy=REGULARIZATION_POLICY,
                    target_standardization="NONE", checkpoint="FINAL_FIT_OR_FINAL_EPOCH_ONLY",
                    final_selection_score=("NATIVE_PAIR_SIGN_PROBABILITY" if paradigm == "LOGIT" else
                        "Q10_ELIGIBILITY_Q50_MATCHING_Q90_DIAGNOSTIC_NO_QUANTILE_REORDER" if paradigm == "QUANTILE_HGB" else
                        "EQUAL_MEAN_FOUR_ORDERED_HORIZON_EDGES" if paradigm == "MULTITASK_MLP" else "NATIVE_PREDICTED_PAIR_EDGE"),
                    maturity_authority="RUNNER_COMMON_20D_END_STRICTLY_BEFORE_EACH_FIT_CUTOFF")
    neural = paradigm in ("MLP", "MULTITASK_MLP")
    if neural:
        estimator, extra = _fit_neural(x, target, weights, spec, seed, event, on_fit_call)
        metadata.update(extra)
    else:
        names = dict(LOGIT="logistic", RIDGE="ridge", HUBER="huber", HGB="hgb", XGB="xgb", CAT="cat", QUANTILE_HGB="hgb_q")
        estimator = (pred._make_estimator(names[paradigm], quantile=quantile) if paradigm == "QUANTILE_HGB"
                     else pred._make_estimator(names[paradigm]))
        params = copy.deepcopy(spec)
        if paradigm == "CAT": params["random_seed"] = seed
        estimator.set_params(**params)
        fit_y = (target > 0).astype(int) if paradigm == "LOGIT" else target
        from threadpoolctl import threadpool_limits
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with threadpool_limits(limits=2):
                if on_fit_call is not None: on_fit_call(event)
                estimator.fit(x, fit_y, sample_weight=weights)
        metadata["warnings"] = [dict(category=type(w.message).__name__, message=str(w.message)) for w in caught]
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            raise RuntimeError("UNRESOLVED_CONVERGENCE_NO_RETRY")
        metadata["backend"] = obj._version_for(estimator)
    fitted = FittedBoundary(paradigm, capacity, seed, quantile, estimator, metadata, neural)
    predict(fitted, x[:min(len(x), 128)])
    return fitted


def predict(fitted, X_scaled):
    if not isinstance(fitted, FittedBoundary) or fitted.paradigm not in PARADIGMS:
        raise ValueError("BOUNDARY_FITTED_COMPONENT_REQUIRED")
    x = _x(X_scaled)
    outputs = 4 if fitted.paradigm == "MULTITASK_MLP" else 1
    if not len(x): return np.empty((0, 4)) if outputs == 4 else np.empty(0)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        if fitted.neural:
            import torch
            with torch.no_grad():
                values = fitted.estimator(torch.tensor(np.clip(x, *fitted.metadata["spec"]["feature_clip"]), dtype=torch.float32)).numpy()
            values = values if outputs == 4 else values[:, 0]
        elif fitted.paradigm == "LOGIT":
            probability = np.asarray(fitted.estimator.predict_proba(x), dtype=float)
            classes = np.asarray(getattr(fitted.estimator, "classes_", [0, 1]))
            if probability.shape != (len(x), 2) or not np.array_equal(classes, [0, 1]):
                raise ValueError("NATIVE_PAIR_SIGN_POSITIVE_CLASS_REQUIRED")
            values = probability[:, 1]
        else: values = np.asarray(fitted.estimator.predict(x), dtype=float)
    expected = (len(x), 4) if outputs == 4 else (len(x),)
    if values.shape != expected or not np.isfinite(values).all():
        raise ValueError("FINITE_COMPLETE_COMPONENT_PREDICTIONS_REQUIRED")
    if fitted.paradigm == "LOGIT" and ((values < 0).any() or (values > 1).any()):
        raise ValueError("VALID_PAIR_SIGN_PROBABILITY_REQUIRED")
    return values


def combine_predictions(paradigm, components):
    """Every registered seed/quantile is required, never select an alternative."""
    if paradigm not in PARADIGMS: raise ValueError("FROZEN_BOUNDARY_PARADIGM_REQUIRED")
    keys = QUANTILES if paradigm == "QUANTILE_HGB" else SEEDS if paradigm in STOCHASTIC else (SEEDS[0],)
    if set(components) != set(keys): raise ValueError("ALL_PREDECLARED_COMPONENTS_REQUIRED_NO_SEED_SELECTION")
    arrays = [np.asarray(components[k], dtype=float) for k in keys]
    if not arrays or any(a.shape != arrays[0].shape or not np.isfinite(a).all() for a in arrays):
        raise ValueError("COMPLETE_EQUAL_SHAPE_COMPONENTS_REQUIRED")
    if paradigm == "MULTITASK_MLP":
        if arrays[0].ndim != 2 or arrays[0].shape[1] != 4: raise ValueError("FOUR_ORDERED_HORIZON_EDGES_REQUIRED")
        return np.mean(arrays, axis=0).mean(axis=1)
    if any(a.ndim != 1 for a in arrays): raise ValueError("SCALAR_PAIR_COMPONENT_REQUIRED")
    if paradigm == "QUANTILE_HGB": return np.column_stack(arrays)
    return np.mean(arrays, axis=0)
