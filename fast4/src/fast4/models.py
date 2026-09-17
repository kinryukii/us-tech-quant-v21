from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import (ExtraTreesClassifier, ExtraTreesRegressor,
                              HistGradientBoostingClassifier, HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .evaluation import composite_objective
from .splits import Fold


@dataclass(frozen=True)
class Spec:
    name: str
    family: str
    mode: str
    task: str
    target: str
    orientation: float = 1.0
    quantile: float | None = None


@dataclass
class FittedSpec:
    spec: Spec
    feature_order: list[str]
    models: dict[str, Any]

    def predict_raw(self, frame: pd.DataFrame) -> np.ndarray:
        output = np.full(len(frame), np.nan)
        keys = ("POOLED",) if self.spec.mode == "pooled" else ("UP", "DOWN")
        for key in keys:
            positions = np.arange(len(frame)) if key == "POOLED" else np.flatnonzero(frame["head"].eq(key).to_numpy())
            if len(positions) == 0:
                continue
            model = self.models[key]
            x = frame.iloc[positions][self.feature_order]
            if self.spec.task == "classification":
                prediction = model.predict_proba(x)[:, 1]
            else:
                prediction = model.predict(x)
            output[positions] = prediction
        return output

    def predict_score(self, frame: pd.DataFrame) -> np.ndarray:
        return self.spec.orientation * self.predict_raw(frame)


@dataclass
class Fast4ProductionModel:
    feature_order: list[str]
    architecture: str
    base_specs: list[Spec]
    base_models: dict[str, FittedSpec]
    meta_model: Any | None

    def base_predictions(self, frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({spec.name: self.base_models[spec.name].predict_score(frame) for spec in self.base_specs}, index=frame.index)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        base = self.base_predictions(frame)
        if self.architecture == "cross_fitted_stack":
            return self.meta_model.predict(base[[spec.name for spec in self.base_specs]])
        if self.architecture == "pooled_ensemble":
            return base[["primary_hgb_pooled", "primary_extra_pooled", "primary_rf_pooled"]].mean(axis=1).to_numpy()
        if self.architecture == "directional_ensemble":
            return base[["primary_hgb_directional", "primary_extra_directional"]].mean(axis=1).to_numpy()
        if self.architecture == "multi_horizon_average":
            return base[[f"horizon_{h}m_hgb_pooled" for h in (5, 10, 15, 30, 60)]].mean(axis=1).to_numpy()
        return base[self.architecture].to_numpy()


def specifications() -> list[Spec]:
    specs = [
        Spec("primary_hgb_pooled", "hist_gradient_boosting", "pooled", "regression", "primary_target"),
        Spec("primary_hgb_directional", "hist_gradient_boosting", "directional", "regression", "primary_target"),
        Spec("primary_extra_pooled", "extra_trees", "pooled", "regression", "primary_target"),
        Spec("primary_extra_directional", "extra_trees", "directional", "regression", "primary_target"),
        Spec("primary_rf_pooled", "random_forest", "pooled", "regression", "primary_target"),
        Spec("positive_hgb_pooled", "hist_gradient_boosting", "pooled", "classification", "y_positive"),
        Spec("positive_hgb_directional", "hist_gradient_boosting", "directional", "classification", "y_positive"),
        Spec("positive_extra_pooled", "extra_trees", "pooled", "classification", "y_positive"),
        Spec("majority_hgb_pooled", "hist_gradient_boosting", "pooled", "classification", "positive_horizon_majority"),
    ]
    specs.extend(Spec(f"horizon_{h}m_hgb_pooled", "hist_gradient_boosting", "pooled", "regression", f"y_{h}m") for h in (5, 10, 15, 30, 60))
    specs.extend([
        Spec("q10_hgb_pooled", "hist_gradient_boosting", "pooled", "regression", "primary_target", quantile=.10),
        Spec("q25_hgb_pooled", "hist_gradient_boosting", "pooled", "regression", "primary_target", quantile=.25),
        Spec("q50_hgb_pooled", "hist_gradient_boosting", "pooled", "regression", "primary_target", quantile=.50),
        Spec("severe_loss_hgb_pooled", "hist_gradient_boosting", "pooled", "classification", "severe_loss", orientation=-1.0),
    ])
    return specs


def parameter_candidates(spec: Spec) -> list[dict[str, Any]]:
    if spec.family == "hist_gradient_boosting":
        return [
            {"learning_rate": .03, "max_iter": 220, "max_leaf_nodes": 7, "min_samples_leaf": 15, "l2_regularization": 1.0, "max_bins": 63, "loss_variant": "squared_error"},
            {"learning_rate": .05, "max_iter": 160, "max_leaf_nodes": 15, "min_samples_leaf": 25, "l2_regularization": 3.0, "max_bins": 127, "loss_variant": "absolute_error"},
            {"learning_rate": .08, "max_iter": 120, "max_leaf_nodes": 7, "min_samples_leaf": 40, "l2_regularization": 10.0, "max_bins": 63, "loss_variant": "squared_error"},
        ]
    if spec.family == "extra_trees":
        return [
            {"n_estimators": 160, "max_depth": 4, "min_samples_leaf": 4, "max_features": .65},
            {"n_estimators": 200, "max_depth": 7, "min_samples_leaf": 8, "max_features": 1.0},
            {"n_estimators": 240, "max_depth": None, "min_samples_leaf": 16, "max_features": .75},
        ]
    return [
        {"n_estimators": 160, "max_depth": 4, "min_samples_leaf": 5, "max_features": .65, "max_samples": .8},
        {"n_estimators": 200, "max_depth": 7, "min_samples_leaf": 10, "max_features": 1.0, "max_samples": .9},
        {"n_estimators": 240, "max_depth": None, "min_samples_leaf": 18, "max_features": .75, "max_samples": .8},
    ]


def _estimator(spec: Spec, parameters: dict[str, Any], seed: int) -> Any:
    params = dict(parameters)
    loss_variant = params.pop("loss_variant", "squared_error")
    if spec.family == "hist_gradient_boosting":
        if spec.task == "classification":
            model = HistGradientBoostingClassifier(loss="log_loss", early_stopping=False, random_state=seed, **params)
        else:
            loss = "quantile" if spec.quantile is not None else loss_variant
            kwargs = {"quantile": spec.quantile} if spec.quantile is not None else {}
            model = HistGradientBoostingRegressor(loss=loss, early_stopping=False, random_state=seed, **params, **kwargs)
    elif spec.family == "extra_trees":
        cls = ExtraTreesClassifier if spec.task == "classification" else ExtraTreesRegressor
        model = cls(random_state=seed, n_jobs=-1, bootstrap=False, **params)
    else:
        cls = RandomForestClassifier if spec.task == "classification" else RandomForestRegressor
        model = cls(random_state=seed, n_jobs=-1, bootstrap=True, **params)
    return Pipeline([("imputer", SimpleImputer(strategy="median", keep_empty_features=True)), ("model", model)])


def fit_spec(spec: Spec, frame: pd.DataFrame, indices: np.ndarray, features: list[str],
             parameters: dict[str, Any], seed: int) -> tuple[FittedSpec, int]:
    models, fits = {}, 0
    keys = ("POOLED",) if spec.mode == "pooled" else ("UP", "DOWN")
    for offset, key in enumerate(keys):
        part = frame.loc[indices]
        if key != "POOLED":
            part = part.loc[part["head"].eq(key)]
        if len(part) < 20 or (spec.task == "classification" and part[spec.target].nunique() != 2):
            raise RuntimeError(f"STOP_FAST4_MODEL_TRAINING_DOMAIN:{spec.name}:{key}:{len(part)}")
        model = _estimator(spec, parameters, seed + offset)
        model.fit(part[features], part[spec.target])
        models[key] = model
        fits += 1
    return FittedSpec(spec, features, models), fits


def tune_and_predict(spec: Spec, frame: pd.DataFrame, outer_train: np.ndarray, outer_valid: np.ndarray,
                     inner: list[Fold], features: list[str], seed: int) -> tuple[np.ndarray, pd.Series, dict[str, Any], FittedSpec, dict[str, int]]:
    trials, fit_count, predict_count = [], 0, 0
    for trial_number, parameters in enumerate(parameter_candidates(spec), start=1):
        predictions = pd.Series(index=frame.index, dtype=float)
        fold_scores = []
        for inner_number, fold in enumerate(inner, start=1):
            fitted, fits = fit_spec(spec, frame, fold.train_index, features, parameters, seed + 1000 * trial_number + inner_number)
            pred = fitted.predict_score(frame.loc[fold.valid_index])
            predictions.loc[fold.valid_index] = pred
            fit_count += fits
            predict_count += len(fitted.models)
            fold_scores.append(composite_objective(frame.loc[fold.valid_index], pred))
        objective = float(np.mean(fold_scores))
        trials.append({"trial": trial_number, "parameters": parameters, "fold_objectives": fold_scores, "objective": objective, "inner_oof": predictions})
    best = max(trials, key=lambda item: (item["objective"], -item["trial"]))
    final_model, fits = fit_spec(spec, frame, outer_train, features, best["parameters"], seed + 9000)
    outer_prediction = final_model.predict_score(frame.loc[outer_valid])
    fit_count += fits
    predict_count += len(final_model.models)
    record = {"spec": spec.name, "selected_trial": best["trial"], "selected_parameters": best["parameters"],
              "selected_inner_objective": best["objective"],
              "all_trial_objectives": [{"trial": item["trial"], "parameters": item["parameters"], "objective": item["objective"], "fold_objectives": item["fold_objectives"]} for item in trials]}
    return outer_prediction, best["inner_oof"], record, final_model, {"fit": fit_count, "predict": predict_count, "trials": len(trials)}


def fit_meta(inner_predictions: pd.DataFrame, target: pd.Series) -> Any:
    valid = inner_predictions.notna().all(axis=1) & target.notna()
    if valid.sum() < 50:
        raise RuntimeError("STOP_FAST4_STACK_INNER_OOF_INSUFFICIENT")
    model = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=10.0))])
    model.fit(inner_predictions.loc[valid], target.loc[valid])
    return model


def modal_parameters(selection_records: list[dict[str, Any]], spec_name: str) -> dict[str, Any]:
    values = [record["selected_parameters"] for record in selection_records if record["spec"] == spec_name]
    encoded = [str(sorted(value.items())) for value in values]
    winner = Counter(encoded).most_common(1)[0][0]
    return values[encoded.index(winner)]


def architecture_dependencies(architecture: str, specs: list[Spec]) -> list[Spec]:
    by_name = {spec.name: spec for spec in specs}
    if architecture == "cross_fitted_stack":
        return specs
    if architecture == "pooled_ensemble":
        return [by_name[name] for name in ("primary_hgb_pooled", "primary_extra_pooled", "primary_rf_pooled")]
    if architecture == "directional_ensemble":
        return [by_name[name] for name in ("primary_hgb_directional", "primary_extra_directional")]
    if architecture == "multi_horizon_average":
        return [by_name[f"horizon_{h}m_hgb_pooled"] for h in (5, 10, 15, 30, 60)]
    return [by_name[architecture]]


def refit_production(frame: pd.DataFrame, features: list[str], architecture: str, specs: list[Spec],
                     selections: list[dict[str, Any]], oof: pd.DataFrame, seed: int) -> tuple[Fast4ProductionModel, dict[str, int]]:
    dependencies = architecture_dependencies(architecture, specs)
    models, fits = {}, 0
    all_index = frame.index.to_numpy()
    for i, spec in enumerate(dependencies):
        parameters = modal_parameters(selections, spec.name)
        fitted, count = fit_spec(spec, frame, all_index, features, parameters, seed + 20000 + i)
        models[spec.name] = fitted
        fits += count
    meta = None
    if architecture == "cross_fitted_stack":
        columns = [spec.name for spec in dependencies]
        valid = oof[columns].notna().all(axis=1)
        meta = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=10.0))])
        meta.fit(oof.loc[valid, columns], oof.loc[valid, "primary_target"])
        fits += 1
    return Fast4ProductionModel(features, architecture, dependencies, models, meta), {"fit": fits, "predict": 0}
