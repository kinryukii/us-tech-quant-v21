"""B R4 native breadth: pure bounded fit helpers; readers/ledger stay with B.

No data/model file is read on import. Reuse the frozen native estimator/network
and loss owners, bypassing their clipped-target/in-sample NativeBundle adapter.
The caller must bind source/UID/maturity, reserve units, and freeze before fit.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from scripts.research.a2.data.joint_input_binding import FEATURES
from scripts.research.a2.training import stateful_values as values

CAPACITIES = ("LOW", "MEDIUM", "HIGH")
SEEDS = (20260928, 20260929, 20260930)
TARGET = "FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN"
NATIVE_SHA = "0b90e45b48f6748de2dad86c896502426b0a21cae062ac6f307ef8a52db657a8"
DEPENDENCIES = (
    "D:/us-tech-quant-envs/frozen_dependency_snapshots/development_contexts/fast3_minute_inventory_r1/fast3_torch_cpu/Lib/site-packages",
    "D:/us-tech-quant-envs/frozen_dependency_snapshots/a2_predict_then_optimize_20260928_r1/third_party",
)
RUNTIME_VERSIONS = dict(sklearn="1.9.0", xgboost="3.4.0", lightgbm="4.7.0",
                        catboost="1.2.10", torch="2.14.0+cpu", ngboost="0.5.11",
                        interpret="0.7.8")
STOCHASTIC = frozenset(("ebm", "rf", "extra", "cat", "mlp", "resnet",
                       "fttransformer", "cat_q", "mlp_q", "mlp_dist", "cat_uncertainty"))
TORCH = frozenset(("resnet", "fttransformer", "mlp_q", "mlp_dist"))
INNER = (dict(id="INNER_2021H1", cutoff="2021-01-01",
              validation_start="2021-01-01", validation_end="2021-07-01"),
         dict(id="INNER_2021H2", cutoff="2021-07-01",
              validation_start="2021-07-01", validation_end="2022-01-01"))
ANNUAL = (2022, 2023, 2024, 2025)
BINNING_STOCHASTIC = frozenset(("hgb","hgb_q","lgb","lgb_q"))
BINNING_SUBSAMPLE = 200000
COHORT_ROWS = {"INNER_2021H1":36445,"INNER_2021H2":72784,
               "ANNUAL_2022":114190,"ANNUAL_2023":207645,
               "ANNUAL_2024":301556,"ANNUAL_2025":402740}


class ScientificFitFailure(RuntimeError):
    """One retained scientific failure; no alternate seed/config retry."""


def _catalog():
    tree = ast.parse(values.NATIVE.read_text(encoding="utf-8"))
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in (
                        "POINT_IDS", "CLASS_IDS", "QUANTILE_IDS", "DISTRIBUTION_IDS", "RANK_IDS"):
                    names[target.id] = ast.literal_eval(node.value)
    if len(names) != 5 or values.sha(values.NATIVE) != NATIVE_SHA:
        raise ValueError("FROZEN_NATIVE_CATALOG_CHANGED")
    return names


def _kind(name):
    for key, roster in _catalog().items():
        if name in roster:
            return dict(POINT_IDS="point", CLASS_IDS="probability", QUANTILE_IDS="quantile",
                        DISTRIBUTION_IDS="distribution", RANK_IDS="rank")[key]
    raise ValueError("UNKNOWN_NATIVE_MODEL:" + str(name))


def applicable_models():
    names = _catalog()
    return tuple(names["POINT_IDS"] + names["QUANTILE_IDS"] + names["DISTRIBUTION_IDS"])


def seeds(name, training_rows=None):
    if training_rows is not None and (type(training_rows) is not int or training_rows<0):
        raise ValueError("BOUND_METADATA_TRAINING_ROWCOUNT_REQUIRED")
    stochastic_bins=(name in BINNING_STOCHASTIC and training_rows is not None
                     and training_rows>BINNING_SUBSAMPLE)
    return SEEDS if name in STOCHASTIC or stochastic_bins else SEEDS[:1]


def learned_states(name):
    kind = _kind(name)
    if kind in ("probability", "rank"):
        return ()
    if name == "mlp_q":
        return ("shared_trunk", "q10_head", "q50_head", "q90_head")
    if kind == "quantile":
        return ("q10_estimator", "q50_estimator", "q90_estimator")
    if kind == "distribution":
        return ("joint_body", "location_head", "scale_head")
    return ("estimator",)


def backend_calls(name):
    return 3 if _kind(name) == "quantile" and name != "mlp_q" else 1


def capacity_config(name, capacity):
    """One literal config per tier; no outcome-dependent override."""
    _kind(name)
    if capacity not in CAPACITIES:
        raise ValueError("UNKNOWN_CAPACITY")
    i = CAPACITIES.index(capacity)
    rounds, depth, leaves = (50, 100, 200)[i], (2, 3, 4)[i], (7, 15, 31)[i]
    if name == "ridge":
        return dict(alpha=(100., 10., 1.)[i], solver="auto", fit_intercept=True)
    if name == "elastic":
        return dict(alpha=(.001, .0001, .00001)[i], l1_ratio=.35, max_iter=10000,
                    tol=1e-5, selection="cyclic", fit_intercept=True)
    if name == "huber":
        return dict(epsilon=1.35, alpha=(.1, .01, .001)[i], max_iter=2000, tol=1e-5)
    if name in ("hgb", "hgb_q"):
        return dict(max_iter=rounds, max_depth=depth, max_leaf_nodes=leaves,
                    min_samples_leaf=100, l2_regularization=5., learning_rate=.05,
                    early_stopping=False)
    if name in ("rf", "extra"):
        return dict(n_estimators=rounds, max_depth=(3, 6, 9)[i],
                    min_samples_leaf=40, max_features=1., n_jobs=2)
    if name == "ebm":
        return dict(interactions=0, max_rounds=(100, 200, 400)[i], outer_bags=2,
                    validation_size=0, early_stopping_rounds=0, smoothing_rounds=0,
                    interaction_smoothing_rounds=0, n_jobs=2)
    if name in ("xgb", "xgb_q"):
        return dict(n_estimators=rounds, max_depth=depth, max_leaves=leaves,
                    min_child_weight=100., reg_lambda=5., learning_rate=.05,
                    tree_method="hist", n_jobs=2, subsample=1., colsample_bytree=1.,
                    verbosity=0)
    if name in ("lgb", "lgb_q"):
        return dict(n_estimators=rounds, max_depth=depth, num_leaves=leaves,
                    min_child_samples=100, reg_lambda=5., learning_rate=.05,
                    n_jobs=2, subsample=1., colsample_bytree=1., verbosity=-1,
                    deterministic=True, force_col_wise=True)
    if name in ("cat", "cat_q", "cat_uncertainty"):
        return dict(iterations=rounds, depth=depth, min_data_in_leaf=100,
                    l2_leaf_reg=5., learning_rate=.05, random_strength=1.,
                    thread_count=2, allow_writing_files=False, verbose=False,
                    bootstrap_type="No")
    if name == "linear_q":
        return dict(alpha=(.001, .0001, .00001)[i], solver="highs",
                    solver_options=dict(time_limit=180.))
    if name == "mlp":
        epochs = (20, 40, 60)[i]
        return dict(hidden_layer_sizes=((16,), (32, 16), (64, 32))[i],
                    activation="relu", solver="adam", alpha=.01, batch_size=512,
                    max_iter=epochs, n_iter_no_change=epochs+1, tol=0.,
                    early_stopping=False, learning_rate_init=.001)
    if name in TORCH:
        return dict(epochs=(6, 12, 24)[i], architecture="EXACT_EXISTING_NATIVE_NETWORK",
                    capacity_axis="FIXED_ARCHITECTURE_OPTIMIZATION_EPOCHS",
                    batch_size=512, learning_rate=.001, weight_decay=.01,
                    target_scale=.1, gradient_clip_norm=2., threads=2,
                    final_epoch_only=True, deterministic_algorithms=True)
    if name == "ngboost":
        return dict(n_estimators=rounds, learning_rate=.05, minibatch_frac=1.,
                    col_sample=1., tol=0., verbose=False,
                    base_depth=depth, base_min_samples_leaf=100)
    raise ValueError("BLOCKED_SOURCE_B_DERIVED_TARGET:" + name)


def specs():
    names = _catalog()
    eligible = applicable_models()
    blocked = tuple(names["CLASS_IDS"] + names["RANK_IDS"])
    return dict(
        schema="B_R4_NATIVE_BREADTH_SPEC_V1", target=TARGET, target_clipped=False,
        target_semantics="SUPPORTED_QUANTITY_5D_NOT_CASH_COMPLETE",
        strict_PIT_promotion_eligible=False, test2026_locked=True,
        catalog={k: list(v) for k, v in names.items()},
        applicable_models=list(eligible),
        blocked_models={n: "BLOCKED_SOURCE_B_DERIVED_TARGET_UNBOUND" for n in blocked},
        capacity_tiers=list(CAPACITIES), configurations_per_tier=1,
        binning_seed_rule=dict(models=sorted(BINNING_STOCHASTIC),threshold=BINNING_SUBSAMPLE,
            metadata_rows_by_cohort=dict(COHORT_ROWS),seeds_lte=list(SEEDS[:1]),seeds_gt=list(SEEDS),
            numerical_or_outcome_selection=False,binning_parameters_unchanged=True),
        model_specs={n: dict(kind=_kind(n), seeds=list(seeds(n)),
                            seeds_by_cohort={k:list(seeds(n,v)) for k,v in COHORT_ROWS.items()},
                            capacities={c: capacity_config(n, c) for c in CAPACITIES},
                            learned_states=list(learned_states(n)),
                            backend_fit_calls=backend_calls(n)) for n in eligible},
        inner=deepcopy(INNER), selected_capacity_years=list(ANNUAL),
        capacity_selection="2021H1/H2 equal-fold native validation loss; LOW tie break",
        annual_prediction_semantics="SELECTED_RECIPE_GENUINE_ANNUAL_OOF",
        early_selected_recipe_OOF_years=[2022], inner_predictions_are_selected_OOF=False,
        selection_losses=dict(point="DATE_EQUAL_MSE", quantile="DATE_EQUAL_PINBALL_MEAN_Q10_Q50_Q90",
                              distribution="DATE_EQUAL_NORMAL_NLL"),
        seed_aggregation="ALL_FIXED_SEEDS_REQUIRED_EQUAL_AGGREGATION_NO_SEED_SELECTION",
        feature_order=list(FEATURES), feature_scaler="ONE_WEIGHTED_TRAIN_SCALER_PER_EXACT_COHORT",
        scaled_models=sorted(set(applicable_models()).intersection(values.SCALED)),
        unscaled_models="ALL_OTHER_NATIVE_MODELS_RETAIN_RAW_FEATURE_MATRIX",
        training_rows="ALL_QUALIFIED_ROWS_NO_SAMPLING", scientific_retry=0,
        return_mappers=0, residual_RMS_fits=0, calibration_owner="B_STAGE_B_EARLIER_GENUINE_OOF",
        native_source=str(values.NATIVE), native_source_sha256=NATIVE_SHA,
        raw_semantics_owner=str(Path(values.__file__).resolve()),
        raw_semantics_owner_sha256=values.sha(values.__file__),
        dependencies=list(DEPENDENCIES), runtime_versions=deepcopy(RUNTIME_VERSIONS),
        accounting=budget())


def budget():
    slots=slot_matrix()
    backend=sum(s["backend_calls"] for s in slots)
    learned=sum(s["learned_units"] for s in slots)
    return dict(logical_family_cohort_slots=220,seed_model_attempts=len(slots),
                estimator_fit_calls=backend,scaler_fit_calls=6,
                learned_model_units=learned,learned_total_upper=learned+6,
                physical_fit_events=backend+6,independent_quantile_heads=3,
                joint_quantile_body_and_head_units=4,joint_distribution_body_and_head_units=3,
                states_per_small_round=81,states_per_large_annual_round=97,
                backend_calls_per_small_round=58,backend_calls_per_large_annual_round=74,
                counting="JOINT_BODY_AND_PARAMETER_HEADS_ARE_LEARNED_VIEWS_OF_ONE_OPTIMIZER_NOT_INDEPENDENT_FITS")


def slot_matrix(selected_capacities=None):
    """The unresolved annual capacity is bound only by the frozen 2021 rule."""
    selected_capacities = selected_capacities or {}
    if set(selected_capacities)-set(applicable_models()):
        raise ValueError("UNKNOWN_SELECTED_MODEL")
    slots = []
    cohorts = [(x["id"], x["cutoff"], "INNER", CAPACITIES) for x in INNER]
    cohorts += [(f"ANNUAL_{y}", f"{y}-01-01", "ANNUAL",
                 ("SELECTED_FROM_2021_INNER",)) for y in ANNUAL]
    for cohort, cutoff, phase, tiers in cohorts:
        for name in applicable_models():
            for tier in tiers:
                capacity = selected_capacities.get(name, tier) if phase == "ANNUAL" else tier
                if capacity not in (*CAPACITIES, "SELECTED_FROM_2021_INNER"):
                    raise ValueError("INVALID_SELECTED_CAPACITY")
                for seed in seeds(name,COHORT_ROWS[cohort]):
                    slots.append(dict(cohort=cohort, cutoff=cutoff, phase=phase, model=name,
                                      capacity=capacity, seed=seed, training_metadata_rows=COHORT_ROWS[cohort],
                                      status="REQUIRES_NEW_FIT_OR_EXACT_REUSE_CHECK",
                                      learned_units=len(learned_states(name)), backend_calls=backend_calls(name)))
    return slots


def training_mask(metadata, cutoff):
    """Metadata only, before feature/target conversion; strict label purge."""
    cut = pd.Timestamp(cutoff)
    if cut > pd.Timestamp("2026-01-01") or cut.tz is not None:
        raise ValueError("PRE2026_NAIVE_EXCLUSIVE_FIT_CUTOFF_REQUIRED")
    required = ("signal_date", "execution_date", "label_end_date", "label_mature_date", "fit_eligible")
    if any(k not in metadata for k in required):
        raise ValueError("TRAINING_METADATA_REQUIRED")
    flags = metadata.fit_eligible.map(lambda x: type(x) in (bool, np.bool_) and bool(x))
    signal, entry, end, mature = [pd.to_datetime(metadata[k]) for k in required[:4]]
    return flags & signal.lt(cut) & mature.lt(cut) & end.lt(cut) & entry.gt(signal) & end.gt(entry)


def validation_mask(metadata, cohort):
    found = [x for x in INNER if x["id"] == cohort]
    if len(found) != 1:
        raise ValueError("FIXED_2021_INNER_COHORT_REQUIRED")
    rule = found[0]
    return training_mask(metadata, rule["validation_end"]) & pd.to_datetime(metadata.signal_date).ge(rule["validation_start"])


def date_weights(dates):
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    if not len(clock) or clock.hasnans or clock.tz is not None or (clock >= pd.Timestamp("2026-01-01")).any():
        raise ValueError("PRE2026_DECISION_CLOCK_REQUIRED")
    _, inv, counts = np.unique(clock.asi8, return_inverse=True, return_counts=True)
    return len(clock)/(len(counts)*counts[inv].astype(float))


def _arrays(X, y=None, weights=None):
    x = np.asarray(X, float)
    if x.ndim != 2 or x.shape[1] != len(FEATURES) or not len(x) or not np.isfinite(x).all():
        raise ValueError("FINITE_ORDERED_PIT32_REQUIRED")
    if y is None:
        return x
    target, weight = np.asarray(y, float), np.asarray(weights, float)
    if target.shape != (len(x),) or weight.shape != target.shape or not np.isfinite(target).all():
        raise ValueError("FINITE_UNCLIPPED_TARGET_REQUIRED")
    if not np.isfinite(weight).all() or (weight <= 0).any():
        raise ValueError("POSITIVE_WEIGHTS_REQUIRED")
    return x, target, weight


def fit_scaler(X, weights, on_fit_started=None):
    x = _arrays(X)
    weight = np.asarray(weights, float)
    if weight.shape != (len(x),) or not np.isfinite(weight).all() or (weight <= 0).any():
        raise ValueError("POSITIVE_WEIGHTS_REQUIRED")
    if on_fit_started:
        on_fit_started(dict(component="SHARED_SCALER", learned_units=1, backend_calls=1))
    return StandardScaler().fit(x, sample_weight=weight)


def bind_native():
    native = values._native(DEPENDENCIES)
    if values.sha(values.NATIVE) != NATIVE_SHA:
        raise ValueError("FROZEN_NATIVE_SOURCE_CHANGED")
    import importlib
    for name, version in RUNTIME_VERSIONS.items():
        module = importlib.import_module(name)
        if getattr(module, "__version__", None) != version:
            raise ValueError("FROZEN_RUNTIME_VERSION_CHANGED:" + name)
    return native


@dataclass
class TorchFit:
    """Reuse native network/loss; adapt only fixed epoch budget and seed."""
    name: str
    config: dict
    seed: int
    payload: dict | None = None
    metadata: dict = field(default_factory=dict)

    def fit(self, x, y, sample_weight):
        import torch
        native = bind_native()
        cfg = self.config
        torch.set_num_threads(cfg["threads"])
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(self.seed)
        model = native.make_torch_network(self.name, x.shape[1])
        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
        xx, yy = torch.tensor(x, dtype=torch.float32), torch.tensor(y/cfg["target_scale"], dtype=torch.float32)
        ww = torch.tensor(sample_weight, dtype=torch.float32)
        generator = torch.Generator().manual_seed(self.seed)
        steps = 0
        for _ in range(cfg["epochs"]):
            order = torch.randperm(len(xx), generator=generator)
            for start in range(0, len(xx), cfg["batch_size"]):
                ids = order[start:start+cfg["batch_size"]]
                optimizer.zero_grad(set_to_none=True)
                loss = native.torch_loss(self.name, model(xx[ids]), yy[ids], ww[ids])
                if not torch.isfinite(loss):
                    raise ScientificFitFailure("NONFINITE_FIXED_NATIVE_NEURAL_LOSS")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["gradient_clip_norm"])
                optimizer.step()
                steps += 1
        self.payload = dict(kind=self.name, n_features=x.shape[1],
                            state={k: v.detach().cpu().numpy().copy() for k, v in model.state_dict().items()})
        self.metadata = dict(epochs=cfg["epochs"], optimizer_steps=steps, final_epoch_only=True)
        return self

    def predict(self, x):
        if self.payload is None:
            raise ValueError("UNFITTED_NEURAL")
        raw = bind_native().predict_torch(self.payload, x)
        return raw*self.config["target_scale"] if self.name != "mlp_dist" else raw


def make_estimator(name, capacity, seed, quantile=None, native=None, training_rows=None):
    cfg = capacity_config(name, capacity)
    if seed not in seeds(name,training_rows):
        raise ValueError("FIXED_SEED_REQUIRED")
    if name in TORCH:
        return TorchFit(name, cfg, seed)
    native = native or bind_native()
    estimator = native.estimator(name, quantile=quantile)
    cfg = deepcopy(cfg)
    if name == "ngboost":
        from sklearn.tree import DecisionTreeRegressor
        cfg["Base"] = DecisionTreeRegressor(max_depth=cfg.pop("base_depth"),
                                           min_samples_leaf=cfg.pop("base_min_samples_leaf"), random_state=seed)
    seed_key = "random_seed" if name.startswith("cat") else "random_state"
    if seed_key in estimator.get_params(deep=False):
        cfg[seed_key] = seed
    estimator.set_params(**cfg)
    return estimator


@dataclass
class NativeFit:
    name: str
    capacity: str
    seed: int
    estimators: tuple
    scaler: object = None
    metadata: dict = field(default_factory=dict)

    def raw_predict(self, X):
        x = _arrays(X)
        if self.scaler is not None:
            x = self.scaler.transform(x)
        with threadpool_limits(limits=2):
            if self.name in TORCH:
                return self.estimators[0].predict(x)
            if _kind(self.name) == "quantile":
                return np.column_stack([model.predict(x) for model in self.estimators])
            if self.name == "ngboost":
                d = self.estimators[0].pred_dist(x)
                return np.column_stack([d.loc, d.scale])
            if self.name == "cat_uncertainty":
                raw = np.asarray(self.estimators[0].predict(x, prediction_type="RawFormulaVal"))
                return np.column_stack([raw[:, 0], np.exp(np.clip(raw[:, 1], -20., 10.))])
            return np.asarray(self.estimators[0].predict(x), float)

    def predict(self, X):
        return values.raw_fields(self.name, self.raw_predict(X))


def fit_model(name, capacity, seed, X, y, weights, *, scaler=None,
              feature_order=FEATURES, on_fit_started=None, native=None):
    if name not in applicable_models():
        raise ValueError("BLOCKED_SOURCE_B_DERIVED_TARGET:" + str(name))
    if list(feature_order) != list(FEATURES):
        raise ValueError("FIXED_FEATURE_ORDER_REQUIRED")
    capacity_config(name, capacity)
    if seed not in seeds(name,len(X)):
        raise ValueError("FIXED_SEED_REQUIRED")
    x, target, weight = _arrays(X, y, weights)
    if name in values.SCALED and scaler is None:
        raise ValueError("EXACT_COHORT_SHARED_SCALER_REQUIRED")
    if name not in values.SCALED and scaler is not None:
        raise ValueError("UNSCALED_NATIVE_REQUIRES_RAW_FEATURE_MATRIX")
    if scaler is not None:
        x = scaler.transform(x)
        if not np.isfinite(x).all():
            raise ValueError("NONFINITE_SHARED_SCALER_OUTPUT")
    estimators, warning_records = [], []
    quantiles = (.1, .5, .9) if _kind(name) == "quantile" and name != "mlp_q" else (None,)
    for q in quantiles:
        model = make_estimator(name, capacity, seed, q, native=native, training_rows=len(x))
        states = (f"q{int(q*100)}_estimator",) if q is not None else learned_states(name)
        if on_fit_started:
            on_fit_started(dict(component="NATIVE_ESTIMATOR", model=name, capacity=capacity,
                                seed=seed, quantile=q, learned_states=list(states),
                                learned_units=len(states), backend_calls=1))
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            model.fit(x, target, sample_weight=weight)
        warning_records += [dict(category=w.category.__name__, message=str(w.message)) for w in caught]
        if any(w.category.__name__ == "ConvergenceWarning" for w in caught) and name != "mlp":
            raise ScientificFitFailure("CONVERGENCE_FAILURE_NO_RETRY")
        cfg = capacity_config(name, capacity)
        if name == "mlp" and model.n_iter_ != cfg["max_iter"]:
            raise ScientificFitFailure("FIXED_MLP_FINAL_ITERATION_NOT_COMPLETED")
        if name == "cat" or name == "cat_q" or name == "cat_uncertainty":
            if model.tree_count_ != cfg["iterations"]:
                raise ScientificFitFailure("FIXED_CAT_ITERATION_NOT_COMPLETED")
        if name == "ngboost" and len(model.base_models) != cfg["n_estimators"]:
            raise ScientificFitFailure("FIXED_NGBOOST_ROUNDS_NOT_COMPLETED")
        estimators.append(model)
    return NativeFit(name, capacity, seed, tuple(estimators), scaler,
                     dict(target=TARGET, target_clipped=False, learned_states=list(learned_states(name)),
                          learned_units=len(learned_states(name)), backend_calls=backend_calls(name),
                          warnings=warning_records, mapper_fits=0, uncertainty_RMS_fits=0))


def aggregate(name, members, training_rows=None):
    """All predeclared seeds; equal moments, no best-seed or missing-seed fallback."""
    fixed_seeds=seeds(name,training_rows)
    if set(members) != set(fixed_seeds):
        raise ValueError("ALL_FIXED_SEEDS_REQUIRED")
    keys = set(next(iter(members.values())))
    if any(set(record) != keys for record in members.values()):
        raise ValueError("NATIVE_SEED_SCHEMA_MISMATCH")
    result = {k: np.mean(np.stack([np.asarray(members[s][k], float) for s in fixed_seeds]), axis=0)
              for k in keys}
    if _kind(name) == "distribution":
        second = np.mean(np.stack([np.asarray(members[s]["native_sigma"])**2 +
                                  np.asarray(members[s]["native_mu"])**2 for s in fixed_seeds]), axis=0)
        result["native_sigma"] = np.sqrt(np.maximum(second-result["native_mu"]**2, 0.))
    if any(not np.isfinite(v).all() for v in result.values()):
        raise ScientificFitFailure("NONFINITE_NATIVE_ENSEMBLE")
    return result


def validation_loss(name, y, predictions, dates):
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    if clock.hasnans or clock.tz is not None or (clock < pd.Timestamp("2021-01-01")).any() or (clock >= pd.Timestamp("2022-01-01")).any():
        raise ValueError("CAPACITY_VALIDATION_2021_ONLY")
    weights = date_weights(clock)
    target = np.asarray(y, float)
    if target.shape != weights.shape or not np.isfinite(target).all():
        raise ValueError("FINITE_VALIDATION_TARGET_REQUIRED")
    kind = _kind(name)
    if kind == "point":
        losses = (target-np.asarray(predictions["native_mu"]))**2
    elif kind == "quantile":
        q = np.column_stack([predictions[k] for k in ("q10", "q50", "q90")])
        errors = target[:, None]-q
        levels = np.asarray([.1, .5, .9])
        losses = np.maximum(levels*errors, (levels-1)*errors).mean(axis=1)
    elif kind == "distribution":
        mu, sigma = np.asarray(predictions["native_mu"]), np.asarray(predictions["native_sigma"])
        if (sigma <= 0).any():
            raise ValueError("POSITIVE_DISTRIBUTION_SCALE_REQUIRED")
        losses = np.log(sigma)+.5*((target-mu)/sigma)**2
    else:
        raise ValueError("BLOCKED_SOURCE_B_DERIVED_TARGET")
    if losses.shape != target.shape or not np.isfinite(losses).all():
        raise ScientificFitFailure("NONFINITE_NATIVE_VALIDATION_LOSS")
    return float(np.average(losses, weights=weights))


def select_capacity(records):
    """Require two complete predeclared inner folds; annual outcomes rejected."""
    if any(r.get("cohort") not in {x["id"] for x in INNER} for r in records):
        raise ValueError("CAPACITY_SELECTION_2021_INNER_ONLY")
    scored = []
    for capacity in CAPACITIES:
        found = [r for r in records if r.get("capacity") == capacity]
        if len(found) != 2 or {r.get("cohort") for r in found} != {x["id"] for x in INNER}:
            continue
        if any(r.get("status") != "COMPLETE" or not np.isfinite(r.get("loss", np.nan)) for r in found):
            continue
        scored.append((float(np.mean([r["loss"] for r in found])), CAPACITIES.index(capacity), capacity))
    if not scored:
        raise ScientificFitFailure("NO_COMPLETE_FIXED_CAPACITY")
    return min(scored)[2]
