"""C10 full-date weighted consumers with three predeclared capacity tiers.

The frozen objective owner supplies labels, relevance, pair plans and native
factories. This adapter only adds date-balanced consumer weights and explicitly
bounded capacity. It owns no reader, scaler, target construction or selection.
The runner must enforce each chronological cutoff and common 20D maturity.
"""
from __future__ import annotations

import copy
import hashlib
import math
import warnings

import numpy as np
import pandas as pd

from scripts.research.a2.training import selector_algorithm_objectives as obj

SEED = obj.SEED
FEATURE_COUNT = obj.FEATURE_COUNT
PARADIGMS = ("POINT_HGB", "BOUNDARY_HGB", "PAIRWISE_MLP", "LISTWISE_MLP", "RANK_XGB_NDCG")
CAPACITIES = ("LOW", "MEDIUM", "HIGH")
DATE_WEIGHT_POLICY = "N/(D*N_t); mean-one rows; equal total mass per decision date"
NATIVE_NAN_SENTINEL = "NaN_NATIVE_SENTINEL"


def date_weights(dates):
    """Mean-one full-row weights, also consumed by the runner's weighted scaler."""
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    if not len(clock) or clock.hasnans:
        raise ValueError("FULL_DATE_CLOCK_REQUIRED")
    _, inverse, counts = np.unique(clock.asi8, return_inverse=True, return_counts=True)
    return len(clock) / (len(counts) * counts[inverse].astype(float))


def _native(paradigm, pred):
    if paradigm in ("POINT_HGB", "RIDGE"):
        return pred._make_estimator("hgb" if paradigm == "POINT_HGB" else "ridge")
    return obj._native_factory(paradigm, pred)


def capacity_specs(runtime=None):
    """Exact LOW native parameters; only declared mechanical capacity changes."""
    pred = obj._predictors(runtime)
    specs = {}
    for paradigm in ("POINT_HGB", "BOUNDARY_HGB", "RANK_XGB_NDCG", "RIDGE"):
        low = copy.deepcopy(_native(paradigm, pred).get_params(deep=False))
        # XGB native NaN missing is an exact parameter, not JSON numeric data.
        # Freeze an explicit symbol and restore only this parameter before fit.
        missing = low.get("missing")
        if isinstance(missing, (float, np.floating)) and np.isnan(missing):
            low["missing"] = NATIVE_NAN_SENTINEL
        specs[paradigm] = {"LOW": low}
        if paradigm == "RIDGE":
            continue
        for capacity, rounds, depth, leaves in (("MEDIUM", 128, 4, 31), ("HIGH", 256, 5, 63)):
            spec = copy.deepcopy(low)
            if paradigm == "RANK_XGB_NDCG":
                spec.update(n_estimators=rounds, max_depth=depth)
            else:
                spec.update(max_iter=rounds, max_depth=depth, max_leaf_nodes=leaves)
            specs[paradigm][capacity] = spec
    for paradigm in ("PAIRWISE_MLP", "LISTWISE_MLP"):
        low = obj.role_specs()[paradigm]["capacity"]
        specs[paradigm] = {}
        for capacity, hidden, epochs in (("LOW", 32, 10), ("MEDIUM", 64, 20), ("HIGH", 128, 30)):
            spec = copy.deepcopy(low)
            spec.update(hidden=hidden, epochs=epochs)
            if capacity != "LOW":
                spec["row_permutation"] = "torch.randperm; generator seed 20260928; configured fixed epochs"
            specs[paradigm][capacity] = spec
    return specs


def _checked_pair_plan(partners, clock):
    """Validate cached target-independent topology without redrawing its pairs."""
    original = np.asarray(partners)
    if original.dtype.kind not in "iu" or original.shape != (len(clock), obj.PAIR_PARTNERS):
        raise ValueError("FROZEN_PAIR_PLAN_SHAPE_OR_TYPE")
    plan = original.astype(np.int64, copy=False)
    if (plan < -1).any() or (plan >= len(clock)).any():
        raise ValueError("FROZEN_PAIR_PLAN_RANGE")
    valid = plan >= 0
    safe = plan.clip(min=0)
    _, inverse, counts = np.unique(clock.asi8, return_inverse=True, return_counts=True)
    expected = np.minimum(obj.PAIR_PARTNERS, counts[inverse] - 1)
    if not np.array_equal(valid.sum(1), expected):
        raise ValueError("FROZEN_PAIR_PLAN_PARTNER_COUNT")
    if ((plan == np.arange(len(clock))[:, None]) & valid).any():
        raise ValueError("FROZEN_PAIR_PLAN_SELF_PARTNER")
    if ((clock.asi8[safe] != clock.asi8[:, None]) & valid).any():
        raise ValueError("FROZEN_PAIR_PLAN_CROSS_DATE")
    ordered = np.sort(plan, axis=1)
    if ((ordered[:, 1:] == ordered[:, :-1]) & (ordered[:, 1:] >= 0)).any():
        raise ValueError("FROZEN_PAIR_PLAN_DUPLICATE_PARTNER")
    return plan


def _pair_loss(left, right, signs, valid, weights):
    """Minimal weighted extension of the owner's row-equivalent pair loss."""
    import torch
    losses = torch.nn.functional.softplus(-signs.to(left.dtype) * (left[:, None] - right))
    per_anchor = (losses * valid * (signs != 0)).sum(1) / valid.sum(1).clamp_min(1)
    return (per_anchor * weights.to(left.dtype)).mean()


def weighted_pairwise_loss(scores, target, partners, weights=None, anchors=None):
    """Same plan/sign/tie denominator as owner; vectorized mean-one anchor weights."""
    import torch
    if anchors is None:
        anchors = torch.arange(len(target), device=scores.device)
    plan = torch.as_tensor(partners, dtype=torch.long, device=scores.device)[anchors]
    safe = plan.clamp_min(0)
    signs = torch.sign(target[anchors, None] - target[safe])
    row_weights = (torch.ones(len(target), dtype=scores.dtype, device=scores.device)
                   if weights is None else torch.as_tensor(weights, dtype=scores.dtype, device=scores.device))
    return _pair_loss(scores[anchors], scores[safe], signs, plan >= 0, row_weights[anchors])


def date_balanced_listwise_loss(scores, boundary, groups):
    """Equal date mean of the owner's unchanged single-date mass cross entropy."""
    import torch
    if not groups:
        raise ValueError("LISTWISE_DATES_REQUIRED")
    return torch.stack([obj.listwise_loss(scores, boundary, [group]) for group in groups]).mean()


def _network(hidden):
    """Built-in Sequential persists actual width without the old 32-wide loader."""
    from torch import nn
    return nn.Sequential(nn.Linear(FEATURE_COUNT, hidden), nn.ReLU(),
                         nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1))


def _fit_neural(paradigm, x, target, clock, boundary, spec, weights, plan, on_fit_call, capacity):
    import torch
    torch.set_num_threads(spec["threads"])
    torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)
    network = _network(spec["hidden"])
    xx = torch.tensor(np.clip(x, *spec["feature_clip"]), dtype=torch.float32)
    labels = torch.tensor(boundary, dtype=torch.float32)
    yy = torch.tensor(target, dtype=torch.float64)
    ww = torch.tensor(weights, dtype=torch.float32)
    groups = obj.date_groups(clock)
    optimizer = torch.optim.Adam(network.parameters(), lr=spec["learning_rate"], weight_decay=spec["weight_decay"])
    generator = torch.Generator().manual_seed(SEED)
    metadata = dict(epochs=spec["epochs"], updates=0, epoch_losses=[],
                    parameter_count=sum(p.numel() for p in network.parameters()),
                    batch_size=spec["batch_size"], training_input_rows=len(x), external_rows_dropped=0,
                    singleton_group_rows=sum(len(g) for g in groups if len(g) == 1),
                    listwise_zero_positive_groups=sum(int(boundary[g].sum() == 0) for g in groups))
    if plan is not None:
        anchors, columns = np.nonzero(plan >= 0)
        metadata.update(drawn_pairs=len(anchors), tied_pairs=int((target[anchors] == target[plan[anchors, columns]]).sum()),
                        no_partner_rows=int(((plan >= 0).sum(1) == 0).sum()),
                        pair_plan_sha256=hashlib.sha256(np.asarray(plan, dtype="<i8").tobytes()).hexdigest())
    network.train()
    if on_fit_call is not None:
        on_fit_call(dict(operation="estimator_fit", role=paradigm, paradigm=paradigm, capacity=capacity))
    for _ in range(spec["epochs"]):
        total, denominator = 0., 0
        if paradigm == "LISTWISE_MLP":
            batches = obj._group_batches(groups, torch.randperm(len(groups), generator=generator).numpy())
        else:
            order = torch.randperm(len(xx), generator=generator)
            batches = (order[first:first + spec["batch_size"]] for first in range(0, len(xx), spec["batch_size"]))
        for batch in batches:
            optimizer.zero_grad()
            if paradigm == "LISTWISE_MLP":
                selected = np.concatenate(batch)
                values = network(xx[selected])[:, 0]
                local, start = [], 0
                for group in batch:
                    local.append(np.arange(start, start + len(group)))
                    start += len(group)
                loss = date_balanced_listwise_loss(values, labels[selected], local)
                batch_count = len(batch)
            else:
                anchors = batch.numpy()
                selected = plan[anchors]
                safe = selected.clip(min=0)
                left = network(xx[anchors])[:, 0]
                right = network(xx[safe.reshape(-1)])[:, 0].reshape(-1, obj.PAIR_PARTNERS)
                signs = torch.sign(yy[anchors, None] - yy[safe])
                loss = _pair_loss(left, right, signs, torch.tensor(selected >= 0), ww[anchors])
                batch_count = len(anchors)
            if not torch.isfinite(loss):
                raise RuntimeError("NONFINITE_SUFFICIENCY_NEURAL_OBJECTIVE_NO_RETRY")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), spec["gradient_clip_norm"])
            optimizer.step()
            metadata["updates"] += 1
            total += float(loss.detach()) * batch_count
            denominator += batch_count
        metadata["epoch_losses"].append(total / denominator)
    network.eval()
    metadata["backend"] = dict(module="torch", version=torch.__version__, origin=str(torch.__file__))
    metadata["update_budget"] = (spec["epochs"] * math.ceil(len(x) / spec["batch_size"])
                                 if paradigm == "PAIRWISE_MLP" else
                                 spec["epochs"] * sum(1 for _ in obj._group_batches(groups, np.arange(len(groups)))))
    # Whole-group packing can depend on permutation, so observed updates remain
    # authoritative; the frozen upper bound is epochs * number of dates.
    if paradigm == "LISTWISE_MLP":
        metadata["update_budget_upper"] = spec["epochs"] * len(groups)
    return network, metadata


def fit(paradigm, X_scaled, y, dates, boundary, capacity="LOW", runtime=None,
        pair_plan=None, on_fit_call=None):
    """One estimator fit on runner-scaled rows; no retry, scaler or target fit."""
    if paradigm not in (*PARADIGMS, "RIDGE"):
        raise ValueError("UNKNOWN_SUFFICIENCY_PARADIGM:" + str(paradigm))
    if capacity not in CAPACITIES or (paradigm == "RIDGE" and capacity != "LOW"):
        raise ValueError("UNKNOWN_OR_UNAUTHORIZED_CAPACITY:" + str(capacity))
    x, target, clock, labels = obj._input(X_scaled, y, dates, boundary)
    if clock.tz is not None or (clock >= pd.Timestamp("2026-01-01")).any():
        raise ValueError("PRE2026_NAIVE_TRAIN_CLOCK_REQUIRED")
    weights = date_weights(clock)
    if paradigm == "BOUNDARY_HGB" and len(np.unique(labels)) != 2:
        raise ValueError("BOUNDARY_REQUIRES_BOTH_CLASSES_NO_REBALANCE")
    if pair_plan is not None and paradigm != "PAIRWISE_MLP":
        raise ValueError("PAIR_PLAN_ONLY_FOR_PAIRWISE_MLP")
    plan = None
    if paradigm == "PAIRWISE_MLP":
        plan = _checked_pair_plan(obj.pair_plan(clock) if pair_plan is None else pair_plan, clock)
    pred = obj._predictors(runtime)
    spec = capacity_specs(pred)[paradigm][capacity]
    metadata = dict(paradigm=paradigm, capacity=capacity, spec=copy.deepcopy(spec),
                    estimator_fit_calls=1, scaler_fit_calls=0, target_stat_estimation=0,
                    scientific_retries=0, training_rows=len(x), groups=len(clock.unique()),
                    external_rows_dropped=0, external_row_weight=DATE_WEIGHT_POLICY,
                    row_weight_sum=float(weights.sum()), row_weight_min=float(weights.min()),
                    row_weight_max=float(weights.max()), seed=SEED,
                    maturity_authority="RUNNER_COMMON_20D_END_BEFORE_EACH_FIT_CUTOFF",
                    final_selection_score="NATIVE_SCORE_HIGHER_FIRST",
                    checkpoint="FINAL_FIT_OR_FINAL_EPOCH_ONLY")
    neural = paradigm in ("PAIRWISE_MLP", "LISTWISE_MLP")
    if neural:
        estimator, extra = _fit_neural(paradigm, x, target, clock, labels, spec, weights, plan, on_fit_call, capacity)
        metadata.update(extra)
        metadata["pair_plan_source"] = "CALLER_CACHED_TARGET_INDEPENDENT_PLAN" if pair_plan is not None else "OWNER_SEED_PLAN_ONCE"
    else:
        fit_params = copy.deepcopy(spec)
        if fit_params.get("missing") == NATIVE_NAN_SENTINEL:
            fit_params["missing"] = np.nan
        estimator = _native(paradigm, pred).set_params(**fit_params)
        fit_x, fit_y, kwargs = x, target, dict(sample_weight=weights)
        if paradigm == "BOUNDARY_HGB":
            fit_y = labels
        elif paradigm == "RANK_XGB_NDCG":
            fit_x, fit_y, sizes = pred.rank_training_data(x, target, clock)
            kwargs = dict(group=sizes, sample_weight=np.ones(len(sizes), dtype=float))
            metadata.update(group_weight="UNIT_QUERY; equal decision-date mass", relevance_bins=5,
                            relevance_gain=obj.role_specs()[paradigm]["gain"],
                            relevance_owner="retained predictors.rank_training_data; unchanged average-pct rank 5 bins")
        from threadpoolctl import threadpool_limits
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with threadpool_limits(limits=2):
                if on_fit_call is not None:
                    on_fit_call(dict(operation="estimator_fit", role=paradigm, paradigm=paradigm, capacity=capacity))
                estimator.fit(fit_x, fit_y, **kwargs)
        metadata["warnings"] = [dict(category=type(w.message).__name__, message=str(w.message)) for w in caught]
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            raise RuntimeError("UNRESOLVED_CONVERGENCE_NO_RETRY")
        metadata["backend"] = obj._version_for(estimator)
    fitted = obj.FittedObjective(paradigm, estimator, metadata, neural)
    predict(fitted, x[:min(len(x), 128)])
    return fitted


def predict(fitted, X_scaled):
    """Reuse objective score semantics; point/Ridge add the missing native branch."""
    if not isinstance(fitted, obj.FittedObjective) or fitted.role not in (*PARADIGMS, "RIDGE"):
        raise ValueError("SUFFICIENCY_FIT_REQUIRED")
    if fitted.role not in ("POINT_HGB", "RIDGE"):
        return obj.predict(fitted, X_scaled)
    x = obj._input(X_scaled)
    if not len(x):
        return np.empty(0, dtype=float)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        score = np.asarray(fitted.estimator.predict(x), dtype=float)
    if score.shape != (len(x),) or not np.isfinite(score).all():
        raise ValueError("SUFFICIENCY_NONFINITE_OR_SHAPE_PREDICTION")
    return score
