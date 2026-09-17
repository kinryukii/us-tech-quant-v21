from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import optuna
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from xgboost import XGBClassifier, XGBRegressor

from .splits import Fold


@dataclass(frozen=True)
class StrongSpec:
    name: str
    family: str
    objective: str
    mode: str
    task: str
    target: str
    tier: str = "secondary"
    orientation: float = 1.0
    quantile: float | None = None


@dataclass
class FittedStrongSpec:
    spec: StrongSpec
    feature_order: list[str]
    models: dict[str, Any]

    def predict_raw(self, frame: pd.DataFrame) -> np.ndarray:
        prediction = np.full(len(frame), np.nan, dtype=float)
        keys = ("POOLED",) if self.spec.mode == "pooled" else ("UP", "DOWN")
        for key in keys:
            positions = np.arange(len(frame)) if key == "POOLED" else np.flatnonzero(frame["head"].eq(key).to_numpy())
            if not len(positions):
                continue
            model = self.models[key]
            values = frame.iloc[positions][self.feature_order]
            if self.spec.task == "classification":
                local = model.predict_proba(values)[:, 1]
            else:
                local = model.predict(values)
            prediction[positions] = np.asarray(local, dtype=float).reshape(-1)
        return prediction

    def predict_score(self, frame: pd.DataFrame) -> np.ndarray:
        return self.spec.orientation * self.predict_raw(frame)


def specifications() -> list[StrongSpec]:
    specs = [
        StrongSpec("lgb_l2_pooled", "LightGBM", "regression", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("lgb_huber_pooled", "LightGBM", "huber", "pooled", "regression", "primary_target", "major"),
        StrongSpec("lgb_fair_pooled", "LightGBM", "fair", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("lgb_l1_pooled", "LightGBM", "regression_l1", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("lgb_l2_directional", "LightGBM", "regression", "directional", "regression", "primary_target", "primary"),
        StrongSpec("xgb_l2_pooled", "XGBoost", "reg:squarederror", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("xgb_pseudohuber_pooled", "XGBoost", "reg:pseudohubererror", "pooled", "regression", "primary_target", "major"),
        StrongSpec("xgb_l1_pooled", "XGBoost", "reg:absoluteerror", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("xgb_l2_directional", "XGBoost", "reg:squarederror", "directional", "regression", "primary_target", "primary"),
        StrongSpec("cat_rmse_pooled", "CatBoost", "RMSE", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("cat_mae_pooled", "CatBoost", "MAE", "pooled", "regression", "primary_target", "primary"),
        StrongSpec("cat_huber_pooled", "CatBoost", "Huber:delta=0.005", "pooled", "regression", "primary_target", "major"),
        StrongSpec("cat_rmse_directional", "CatBoost", "RMSE", "directional", "regression", "primary_target", "primary"),
    ]
    for target, label in (("y_positive", "positive"), ("positive_horizon_majority", "majority")):
        for family, short in (("LightGBM", "lgb"), ("XGBoost", "xgb"), ("CatBoost", "cat")):
            specs.append(StrongSpec(f"{short}_{label}_pooled", family, "binary", "pooled", "classification", target, "classification"))
    specs.append(StrongSpec("lgb_positive_directional", "LightGBM", "binary", "directional", "classification", "y_positive", "classification"))
    for horizon in (5, 10, 15, 30, 60):
        for family, short, objective in (("LightGBM", "lgb", "huber"), ("XGBoost", "xgb", "reg:pseudohubererror"), ("CatBoost", "cat", "Huber:delta=0.005")):
            specs.append(StrongSpec(f"{short}_h{horizon}_pooled", family, objective, "pooled", "regression", f"y_{horizon}m"))
    for quantile in (.05, .10, .25, .50):
        label = f"q{int(quantile * 100):02d}"
        for family, short, objective in (("LightGBM", "lgb", "quantile"), ("XGBoost", "xgb", "reg:quantileerror"), ("CatBoost", "cat", "Quantile")):
            specs.append(StrongSpec(f"{short}_{label}_pooled", family, objective, "pooled", "regression", "primary_target", quantile=quantile))
    for family, short in (("LightGBM", "lgb"), ("XGBoost", "xgb"), ("CatBoost", "cat")):
        specs.append(StrongSpec(f"{short}_severe_pooled", family, "binary", "pooled", "classification", "severe_loss", "classification", orientation=-1.0))
    return specs


def _sample_parameters(trial: optuna.Trial, spec: StrongSpec) -> dict[str, Any]:
    if spec.family == "LightGBM":
        return {
            "learning_rate": trial.suggest_float("learning_rate", .008, .12, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 650),
            "num_leaves": trial.suggest_int("num_leaves", 5, 47),
            "max_depth": trial.suggest_int("max_depth", 2, 9),
            "min_child_samples": trial.suggest_int("min_child_samples", 12, 90),
            "min_split_gain": trial.suggest_float("min_split_gain", 0.0, .05),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-5, 20.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 30.0, log=True),
            "colsample_bytree": trial.suggest_float("feature_fraction", .35, 1.0),
            "subsample": trial.suggest_float("bagging_fraction", .55, 1.0),
            "subsample_freq": trial.suggest_int("bagging_freq", 0, 5),
            "max_bin": trial.suggest_categorical("max_bin", [31, 63, 127, 255]),
        }
    if spec.family == "XGBoost":
        return {
            "learning_rate": trial.suggest_float("learning_rate", .008, .12, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 650),
            "max_depth": trial.suggest_int("max_depth", 2, 8),
            "min_child_weight": trial.suggest_float("min_child_weight", .5, 30.0, log=True),
            "gamma": trial.suggest_float("gamma", 1e-7, .05, log=True),
            "subsample": trial.suggest_float("subsample", .55, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", .35, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-6, 20.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 30.0, log=True),
            "max_bin": trial.suggest_categorical("max_bin", [32, 64, 128, 256]),
        }
    return {
        "depth": trial.suggest_int("depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", .008, .12, log=True),
        "iterations": trial.suggest_int("iterations", 100, 650),
        "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", .5, 30.0, log=True),
        "random_strength": trial.suggest_float("random_strength", 1e-4, 5.0, log=True),
        "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 5.0),
        "border_count": trial.suggest_categorical("border_count", [32, 64, 128, 254]),
    }


def default_parameters(spec: StrongSpec) -> dict[str, Any]:
    if spec.family == "LightGBM":
        return {"learning_rate": .03, "n_estimators": 250, "num_leaves": 15, "max_depth": 5,
                "min_child_samples": 30, "min_split_gain": 0.0, "reg_alpha": .1, "reg_lambda": 3.0,
                "colsample_bytree": .7, "subsample": .8, "subsample_freq": 1, "max_bin": 127}
    if spec.family == "XGBoost":
        return {"learning_rate": .03, "n_estimators": 250, "max_depth": 4, "min_child_weight": 5.0,
                "gamma": 1e-5, "subsample": .8, "colsample_bytree": .7, "reg_alpha": .1,
                "reg_lambda": 3.0, "max_bin": 128}
    return {"depth": 5, "learning_rate": .03, "iterations": 250, "l2_leaf_reg": 5.0,
            "random_strength": .1, "bagging_temperature": 1.0, "border_count": 64}


def estimator(spec: StrongSpec, parameters: dict[str, Any], seed: int, threads: int) -> Any:
    params = dict(parameters)
    if spec.family == "LightGBM":
        common = dict(random_state=seed, n_jobs=threads, verbosity=-1, deterministic=True,
                      force_col_wise=True, feature_fraction_seed=seed, bagging_seed=seed, data_random_seed=seed)
        if spec.task == "classification":
            return LGBMClassifier(objective="binary", **common, **params)
        if spec.objective == "quantile":
            params["alpha"] = spec.quantile
        return LGBMRegressor(objective=spec.objective, **common, **params)
    if spec.family == "XGBoost":
        common = dict(random_state=seed, n_jobs=threads, tree_method="hist", verbosity=0)
        if spec.task == "classification":
            return XGBClassifier(objective="binary:logistic", eval_metric="logloss", **common, **params)
        if spec.objective == "reg:quantileerror":
            params["quantile_alpha"] = spec.quantile
        return XGBRegressor(objective=spec.objective, **common, **params)
    common = dict(random_seed=seed, thread_count=threads, verbose=False, allow_writing_files=False,
                  bootstrap_type="Bayesian")
    if spec.task == "classification":
        return CatBoostClassifier(loss_function="Logloss", **common, **params)
    loss = f"Quantile:alpha={spec.quantile}" if spec.objective == "Quantile" else spec.objective
    return CatBoostRegressor(loss_function=loss, **common, **params)


def fit_spec(spec: StrongSpec, frame: pd.DataFrame, indices: np.ndarray, features: list[str],
             parameters: dict[str, Any], seed: int, threads: int) -> tuple[FittedStrongSpec, int]:
    models: dict[str, Any] = {}
    keys = ("POOLED",) if spec.mode == "pooled" else ("UP", "DOWN")
    for offset, key in enumerate(keys):
        part = frame.loc[indices]
        if key != "POOLED":
            part = part.loc[part["head"].eq(key)]
        if len(part) < 25 or (spec.task == "classification" and part[spec.target].nunique() != 2):
            raise RuntimeError(f"FAST4_R2_MODEL_DOMAIN:{spec.name}:{key}:{len(part)}")
        model = estimator(spec, parameters, seed + offset, threads)
        model.fit(part[features], part[spec.target])
        models[key] = model
    return FittedStrongSpec(spec, list(features), models), len(models)


def trial_budget(spec: StrongSpec, cfg: dict[str, Any]) -> int:
    return int(cfg[{"major": "major_trials_per_outer_fold", "primary": "primary_trials_per_outer_fold",
                    "classification": "classification_trials_per_outer_fold"}.get(spec.tier, "secondary_trials_per_outer_fold")])


def tune_outer_spec(
    spec: StrongSpec,
    frame: pd.DataFrame,
    features: list[str],
    outer_train: np.ndarray,
    outer_valid: np.ndarray,
    inner_folds: list[Fold],
    metric: Callable[[pd.DataFrame, np.ndarray], float],
    storage_url: str,
    study_name: str,
    cfg: dict[str, Any],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, pd.Series, dict[str, Any], FittedStrongSpec, dict[str, int]]:
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=seed, multivariate=True)
    pruner = optuna.pruners.MedianPruner(n_startup_trials=4, n_warmup_steps=1)
    study = optuna.create_study(study_name=study_name, direction="maximize", sampler=sampler,
                                pruner=pruner, storage=storage_url, load_if_exists=True)
    budget = trial_budget(spec, cfg)
    threads = int(cfg["model_threads"])
    counters = {"fit": 0, "predict": 0}

    def objective(trial: optuna.Trial) -> float:
        params = _sample_parameters(trial, spec)
        values: list[float] = []
        for number, fold in enumerate(inner_folds):
            fitted, count = fit_spec(spec, frame, fold.train_index, features, params,
                                     seed + trial.number * 100 + number, threads)
            pred = fitted.predict_score(frame.loc[fold.valid_index])
            if not np.isfinite(pred).all():
                raise RuntimeError(f"FAST4_R2_NONFINITE_PREDICTION:{spec.name}")
            counters["fit"] += count
            counters["predict"] += count
            values.append(metric(frame.loc[fold.valid_index], pred))
            aggregate = float(np.mean(values) - .20 * np.std(values))
            trial.report(aggregate, number)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.mean(values) - .20 * np.std(values))

    remaining = max(0, budget - len(study.trials))
    if remaining:
        study.optimize(objective, n_trials=remaining, n_jobs=int(cfg["optuna_parallel_trials"]),
                       gc_after_trial=True, catch=(ValueError, RuntimeError))
    complete = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    if not complete:
        raise RuntimeError(f"FAST4_R2_ALL_OPTUNA_TRIALS_FAILED:{spec.name}:{study_name}")
    params = dict(study.best_params)
    inner_prediction = pd.Series(np.nan, index=frame.index, dtype=float)
    inner_raw = pd.Series(np.nan, index=frame.index, dtype=float)
    fold_objectives = []
    for number, fold in enumerate(inner_folds):
        fitted, count = fit_spec(spec, frame, fold.train_index, features, params,
                                 seed + 80_000 + number, threads)
        raw = fitted.predict_raw(frame.loc[fold.valid_index])
        pred = spec.orientation * raw
        inner_prediction.loc[fold.valid_index] = pred
        inner_raw.loc[fold.valid_index] = raw
        fold_objectives.append(metric(frame.loc[fold.valid_index], pred))
        counters["fit"] += count
        counters["predict"] += count
    final, count = fit_spec(spec, frame, outer_train, features, params, seed + 90_000, threads)
    outer_raw = final.predict_raw(frame.loc[outer_valid])
    outer_prediction = spec.orientation * outer_raw
    counters["fit"] += count
    counters["predict"] += count
    record = {
        "spec": spec.name, "family": spec.family, "objective": spec.objective, "mode": spec.mode,
        "target": spec.target, "quantile": spec.quantile, "study_name": study_name,
        "requested_trial_count": budget, "study_trial_count": len(study.trials),
        "complete_trial_count": len(complete), "pruned_trial_count": sum(t.state == optuna.trial.TrialState.PRUNED for t in study.trials),
        "failed_trial_count": sum(t.state == optuna.trial.TrialState.FAIL for t in study.trials),
        "best_value": float(study.best_value), "best_parameters": params,
        "best_inner_fold_objectives": fold_objectives,
    }
    counts = {**counters, "trials": len(study.trials)}
    return outer_prediction, outer_raw, inner_prediction, record, final, counts


def model_importance(model: FittedStrongSpec) -> dict[str, float]:
    output = {name: 0.0 for name in model.feature_order}
    used = 0
    for fitted in model.models.values():
        values = getattr(fitted, "feature_importances_", None)
        if values is None:
            continue
        used += 1
        for name, value in zip(model.feature_order, np.asarray(values, dtype=float)):
            output[name] += float(value)
    if used:
        output = {name: value / used for name, value in output.items()}
    return output


def sqlite_storage_url(path: Path) -> str:
    return "sqlite:///" + path.resolve().as_posix()
