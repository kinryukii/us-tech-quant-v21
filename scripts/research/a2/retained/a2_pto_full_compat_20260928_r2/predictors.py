"""Frozen 31 logical predictors / 43 physical fitting specifications.

Every prediction keeps its statistical meaning. Conversion of probability,
quantile, robust location and rank scores to expected returns is a separate
time-legal OOF calibration module. No evaluation file is read here.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import time
import traceback
import warnings

from runtime_bootstrap import bootstrap

RUNTIME = bootstrap()

import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesRegressor, HistGradientBoostingClassifier,
                             HistGradientBoostingRegressor, RandomForestClassifier,
                             RandomForestRegressor)
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import ElasticNet, HuberRegressor, LogisticRegression, QuantileRegressor, Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
import torch
from torch import nn

SEED = 20260928
FEATURE_COUNT = 32
QUANTILES = (.1, .5, .9)
POINT_NAMES = ("ridge", "elastic", "huber", "ebm", "rf", "extra", "hgb", "xgb", "lgb", "cat", "mlp", "resnet", "fttransformer")
PROBABILITY_NAMES = ("logistic", "rf_class", "hgb_class", "xgb_class", "lgb_class", "cat_class", "mlp_class")
QUANTILE_NAMES = ("linear_q", "hgb_q", "xgb_q", "lgb_q", "cat_q", "mlp_q")
DISTRIBUTION_NAMES = ("ngboost", "gaussian_mlp", "cat_uncertainty")
RANK_NAMES = ("xgb_rank", "lgb_rank")
NAMES = POINT_NAMES + PROBABILITY_NAMES + QUANTILE_NAMES + DISTRIBUTION_NAMES + RANK_NAMES

TREE_HGB = dict(max_iter=64, max_depth=3, max_leaf_nodes=15, min_samples_leaf=100,
                learning_rate=.05, l2_regularization=1., early_stopping=False, random_state=SEED)
TREE_RF = dict(n_estimators=64, max_depth=3, min_samples_leaf=100, max_features=1.,
               n_jobs=2, random_state=SEED)
TREE_XGB = dict(n_estimators=64, max_depth=3, min_child_weight=20, learning_rate=.05,
                subsample=1., colsample_bytree=1., reg_lambda=1., tree_method="hist",
                n_jobs=2, random_state=SEED, verbosity=0)
TREE_LGB = dict(n_estimators=64, max_depth=3, num_leaves=8, min_child_samples=100,
                learning_rate=.05, reg_lambda=1., n_jobs=2, random_state=SEED,
                deterministic=True, force_col_wise=True, verbosity=-1)
TREE_CAT = dict(iterations=64, depth=3, learning_rate=.05, l2_leaf_reg=3., thread_count=2,
                random_seed=SEED, verbose=False, allow_writing_files=False)
NEURAL_SPEC = dict(epochs=10, batch_size=512, learning_rate=.001, weight_decay=.0001,
                   hidden=32, feature_clip=[-8., 8.], target_standardization="train mean/std only",
                   seed=SEED, threads=2, dropout=0.)


def hyperparameters(name: str) -> dict:
    if name not in NAMES:
        raise ValueError(f"UNKNOWN_PREDICTOR:{name}")
    if name == "ridge":
        return dict(alpha=100., solver="lsqr", tol=1e-6)
    if name == "elastic":
        return dict(alpha=1e-6, l1_ratio=.35, max_iter=2500, tol=1e-5, selection="cyclic", precompute=True,
                    random_state=SEED, convergence_extension_max_iter=10000)
    if name == "huber":
        return dict(epsilon=1.35, alpha=1e-4, max_iter=500, tol=1e-5, convergence_extension_max_iter=2000)
    if name == "logistic":
        return dict(C=.3, max_iter=400, solver="lbfgs", random_state=SEED, convergence_extension_max_iter=1200)
    if name == "ebm":
        return dict(max_rounds=64, max_leaves=3, min_samples_leaf=100, interactions=4, outer_bags=1,
                    inner_bags=0, smoothing_rounds=0, interaction_smoothing_rounds=0, validation_size=0,
                    early_stopping_rounds=0, learning_rate=.05, n_jobs=2, random_state=SEED)
    if name in ("rf", "extra", "rf_class"):
        return copy.deepcopy(TREE_RF)
    if name.startswith("hgb"):
        return {**TREE_HGB, **({"quantiles": list(QUANTILES)} if name.endswith("_q") else {})}
    if name.startswith("xgb"):
        return {**TREE_XGB, **({"quantiles": list(QUANTILES)} if name.endswith("_q") else {}),
                **({"objective": "rank:pairwise", "relevance_bins": 5} if name.endswith("_rank") else {})}
    if name.startswith("lgb"):
        return {**TREE_LGB, **({"quantiles": list(QUANTILES)} if name.endswith("_q") else {}),
                **({"objective": "lambdarank", "relevance_bins": 5, "label_gain": [0, 1, 3, 7, 15]} if name.endswith("_rank") else {})}
    if name.startswith("cat"):
        return {**TREE_CAT, **({"quantiles": list(QUANTILES)} if name.endswith("_q") else {}),
                **({"loss_function": "RMSEWithUncertainty", "target_standardization": "train mean/std only"} if name.endswith("_uncertainty") else {})}
    if name == "linear_q":
        return dict(alpha=.0001, solver="highs", quantiles=list(QUANTILES), solver_options={"time_limit": 180.})
    if name == "ngboost":
        return dict(n_estimators=64, learning_rate=.03, natural_gradient=True, distribution="Normal",
                    base=dict(max_depth=3, min_samples_leaf=100, random_state=SEED), random_state=SEED)
    result = {**NEURAL_SPEC, "architecture": name}
    if name == "fttransformer":
        result.update(token_dim=16, heads=2, layers=1, feedforward_dim=32)
    if name == "mlp_q":
        result["quantiles"] = list(QUANTILES)
    return result


SPECS = {name: hyperparameters(name) for name in NAMES}


class MLP(nn.Module):
    def __init__(self, outputs=1):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(FEATURE_COUNT, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, outputs))

    def forward(self, x):
        return self.net(x)


class ResidualBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.LayerNorm(32), nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, 32))

    def forward(self, x):
        return x + self.net(x)


class TabularResNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.input = nn.Linear(FEATURE_COUNT, 32)
        self.blocks = nn.Sequential(ResidualBlock(), ResidualBlock())
        self.output = nn.Sequential(nn.LayerNorm(32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):
        return self.output(self.blocks(self.input(x)))


class FTTransformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.token_weight = nn.Parameter(torch.empty(FEATURE_COUNT, 16))
        self.token_bias = nn.Parameter(torch.zeros(FEATURE_COUNT, 16))
        self.cls = nn.Parameter(torch.zeros(1, 1, 16))
        nn.init.normal_(self.token_weight, std=.02)
        layer = nn.TransformerEncoderLayer(d_model=16, nhead=2, dim_feedforward=32,
                                           dropout=0., activation="gelu", batch_first=True, norm_first=True)
        self.transformer = nn.TransformerEncoder(layer, num_layers=1, enable_nested_tensor=False)
        self.output = nn.Sequential(nn.LayerNorm(16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, x):
        tokens = x[:, :, None] * self.token_weight[None, :, :] + self.token_bias[None, :, :]
        cls = self.cls.expand(len(x), -1, -1)
        hidden = self.transformer(torch.cat((cls, tokens), dim=1))
        return self.output(hidden[:, 0])


@dataclass
class TorchRegressor:
    architecture: str
    mode: str = "regression"
    quantile: float | None = None

    def fit(self, x, y):
        torch.set_num_threads(2)
        torch.manual_seed(SEED)
        torch.use_deterministic_algorithms(True)
        self.y_mean = 0. if self.mode == "classification" else float(np.mean(y))
        self.y_scale = 1. if self.mode == "classification" else max(float(np.std(y)), 1e-8)
        target = np.asarray((y-self.y_mean)/self.y_scale, np.float32)
        xx = torch.tensor(np.clip(x, -8., 8.), dtype=torch.float32)
        yy = torch.tensor(target, dtype=torch.float32)
        outputs = 2 if self.mode == "gaussian" else 1
        self.model = TabularResNet() if self.architecture == "resnet" else FTTransformer() if self.architecture == "fttransformer" else MLP(outputs)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=.001, weight_decay=.0001)
        generator = torch.Generator().manual_seed(SEED)
        self.epoch_losses = []
        self.updates = 0
        self.model.train()
        for epoch in range(10):
            order = torch.randperm(len(xx), generator=generator)
            total, count = 0., 0
            for first in range(0, len(xx), 512):
                idx = order[first:first+512]
                output = self.model(xx[idx])
                predicted = output[:, 0]
                if self.mode == "classification":
                    loss = nn.functional.binary_cross_entropy_with_logits(predicted, yy[idx])
                elif self.mode == "quantile":
                    error = yy[idx]-predicted
                    loss = torch.maximum(self.quantile*error, (self.quantile-1.)*error).mean()
                elif self.mode == "gaussian":
                    log_scale = output[:, 1].clamp(-6., 2.)
                    loss = (log_scale + .5*((yy[idx]-predicted)/torch.exp(log_scale)).square()).mean()
                else:
                    loss = (predicted-yy[idx]).square().mean()
                if not torch.isfinite(loss):
                    raise RuntimeError(f"NONFINITE_NEURAL_LOSS:{self.architecture}:{self.mode}:{epoch}")
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 5.)
                optimizer.step()
                self.updates += 1
                total += float(loss.detach())*len(idx)
                count += len(idx)
            self.epoch_losses.append(total/count)
        self.model.eval()
        return self

    def predict(self, x):
        if not len(x):
            return np.empty((0, 2)) if self.mode == "gaussian" else np.empty(0)
        chunks = []
        self.model.eval()
        with torch.inference_mode():
            for first in range(0, len(x), 1024):
                xx = torch.tensor(np.clip(x[first:first+1024], -8., 8.), dtype=torch.float32)
                chunks.append(self.model(xx).numpy())
        result = np.concatenate(chunks)
        if self.mode == "classification":
            return 1./(1.+np.exp(-np.clip(result[:, 0].astype(float), -80., 80.)))
        if self.mode == "gaussian":
            return np.column_stack((result[:, 0]*self.y_scale+self.y_mean,
                                    np.exp(np.clip(result[:, 1], -6., 2.))*self.y_scale))
        return result[:, 0].astype(float)*self.y_scale+self.y_mean


@dataclass
class FittedPredictor:
    name: str
    scaler: StandardScaler
    models: list
    fit_status: list
    y_mean: float = 0.
    y_scale: float = 1.


def _make_estimator(name, quantile=None):
    parameters = hyperparameters(name)
    parameters.pop("convergence_extension_max_iter", None)
    if name == "ridge": return Ridge(**parameters)
    if name == "elastic": return ElasticNet(**parameters)
    if name == "huber": return HuberRegressor(**parameters)
    if name == "logistic": return LogisticRegression(**parameters)
    if name == "ebm":
        from interpret.glassbox import ExplainableBoostingRegressor
        return ExplainableBoostingRegressor(**parameters)
    if name == "rf": return RandomForestRegressor(**TREE_RF)
    if name == "extra": return ExtraTreesRegressor(**TREE_RF)
    if name == "rf_class": return RandomForestClassifier(**TREE_RF)
    if name == "hgb": return HistGradientBoostingRegressor(**TREE_HGB)
    if name == "hgb_class": return HistGradientBoostingClassifier(**TREE_HGB)
    if name == "hgb_q": return HistGradientBoostingRegressor(**TREE_HGB, loss="quantile", quantile=quantile)
    if name.startswith("xgb"):
        from xgboost import XGBClassifier, XGBRanker, XGBRegressor
        if name == "xgb_class": return XGBClassifier(**TREE_XGB, objective="binary:logistic")
        if name == "xgb_rank": return XGBRanker(**TREE_XGB, objective="rank:pairwise")
        return XGBRegressor(**TREE_XGB, objective="reg:quantileerror", quantile_alpha=quantile) if quantile is not None else XGBRegressor(**TREE_XGB, objective="reg:squarederror")
    if name.startswith("lgb"):
        from lightgbm import LGBMClassifier, LGBMRanker, LGBMRegressor
        if name == "lgb_class": return LGBMClassifier(**TREE_LGB, objective="binary")
        if name == "lgb_rank": return LGBMRanker(**TREE_LGB, objective="lambdarank", label_gain=[0, 1, 3, 7, 15])
        return LGBMRegressor(**TREE_LGB, objective="quantile", alpha=quantile) if quantile is not None else LGBMRegressor(**TREE_LGB, objective="regression")
    if name.startswith("cat"):
        from catboost import CatBoostClassifier, CatBoostRegressor
        if name == "cat_class": return CatBoostClassifier(**TREE_CAT, loss_function="Logloss")
        loss = "RMSEWithUncertainty" if name == "cat_uncertainty" else f"Quantile:alpha={quantile}" if quantile is not None else "RMSE"
        return CatBoostRegressor(**TREE_CAT, loss_function=loss)
    if name == "linear_q": return QuantileRegressor(quantile=quantile, alpha=.0001, solver="highs", solver_options={"time_limit": 180.})
    if name == "ngboost":
        from ngboost import NGBRegressor
        from ngboost.distns import Normal
        from sklearn.tree import DecisionTreeRegressor
        return NGBRegressor(Dist=Normal, Base=DecisionTreeRegressor(max_depth=3, min_samples_leaf=100, random_state=SEED),
                            n_estimators=64, learning_rate=.03, natural_gradient=True, random_state=SEED, verbose=False)
    mode = "classification" if name == "mlp_class" else "quantile" if name == "mlp_q" else "gaussian" if name == "gaussian_mlp" else "regression"
    return TorchRegressor(name, mode, quantile)


def rank_training_data(x, y, dates):
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "y": y, "index": np.arange(len(y))})
    frame = frame.sort_values(["date", "index"], kind="stable")
    rank = frame.groupby("date", sort=False)["y"].rank(method="average", pct=True)
    relevance = np.minimum(np.floor(rank.to_numpy()*5), 4).astype(int)
    sizes = frame.groupby("date", sort=False).size().to_numpy(int)
    return x[frame["index"].to_numpy(int)], relevance, sizes


def _fit_one(estimator, x, y, name, dates, quantile=None):
    started = time.monotonic()
    repair = None
    caught = []
    fit_kwargs = {}
    if name in RANK_NAMES:
        x, y, groups = rank_training_data(x, y, dates)
        fit_kwargs["group"] = groups
    if name == "lgb_rank": fit_kwargs["eval_at"] = [20]
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        with threadpool_limits(limits=2):
            estimator.fit(x, y, **fit_kwargs)
        caught += [{"category": type(w.message).__name__, "message": str(w.message)} for w in records]
    unconverged = any(w["category"] == "ConvergenceWarning" for w in caught)
    if unconverged and name in ("elastic", "huber", "logistic"):
        max_iter = hyperparameters(name)["convergence_extension_max_iter"]
        estimator.set_params(max_iter=max_iter)
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            with threadpool_limits(limits=2): estimator.fit(x, y, **fit_kwargs)
            repair_warnings = [{"category": type(w.message).__name__, "message": str(w.message)} for w in records]
        repair = {"same_objective": True, "same_data": True, "max_iter": max_iter, "warnings": repair_warnings}
        unconverged = any(w["category"] == "ConvergenceWarning" for w in repair_warnings)
    probe = estimator.predict(x[:min(len(x), 128)])
    if not np.isfinite(probe).all(): raise RuntimeError(f"NONFINITE_FIT_OUTPUT:{name}:{quantile}")
    return dict(name=name, quantile=quantile, status="FAILED" if unconverged else "TRAINED", convergence="WARNING" if unconverged else "NO_CONVERGENCE_WARNING",
                warnings=caught, numerical_extension=repair, seconds=time.monotonic()-started,
                **({"failure": {"exception": "UnresolvedConvergenceWarning", "message": "The one allowed same-objective numerical continuation did not converge."}} if unconverged else {}),
                iterations=np.asarray(getattr(estimator, "n_iter_", [])).tolist(),
                **({"epochs": 10, "updates": estimator.updates, "epoch_losses": estimator.epoch_losses} if isinstance(estimator, TorchRegressor) else {}))


def fit(name, X, y, dates, checkpoint=None, resume=None):
    if name not in NAMES: raise ValueError(f"UNKNOWN_PREDICTOR:{name}")
    X, y = np.asarray(X, float), np.asarray(y, float)
    if X.ndim != 2 or X.shape != (len(y), FEATURE_COUNT) or len(y) != len(dates): raise ValueError("INPUT_SHAPE")
    if not len(y) or not np.isfinite(X).all() or not np.isfinite(y).all(): raise ValueError("NONFINITE_OR_EMPTY_TRAIN_INPUT")
    scaler = StandardScaler().fit(X)
    if resume is not None:
        if resume.name != name or not np.array_equal(resume.scaler.mean_, scaler.mean_) or not np.array_equal(resume.scaler.scale_, scaler.scale_):
            raise RuntimeError("PARTIAL_FIT_SAMPLE_CHANGED")
        scaler = resume.scaler
    x = scaler.transform(X)
    target = (y > 0).astype(int) if name in PROBABILITY_NAMES else y
    if name in PROBABILITY_NAMES and len(np.unique(target)) != 2: raise RuntimeError("CLASSIFICATION_REQUIRES_BOTH_CLASSES")
    y_mean, y_scale = 0., 1.
    if name == "cat_uncertainty":
        y_mean, y_scale = float(y.mean()), max(float(y.std()), 1e-8)
        target = (y-y_mean)/y_scale
    models = list(resume.models) if resume is not None else []
    records = list(resume.fit_status) if resume is not None else []
    quantiles = QUANTILES if name in QUANTILE_NAMES else (None,)
    for quantile in quantiles[len(records):]:
        started = time.monotonic()
        model = None
        try:
            model = _make_estimator(name, quantile)
            record = _fit_one(model, x, target, name, dates, quantile)
        except Exception as exc:
            record = dict(name=name, quantile=quantile, status="FAILED", convergence="FAILED",
                          seconds=time.monotonic()-started,
                          failure={"exception": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        records.append(record)
        models.append(model)
        partial = FittedPredictor(name, scaler, models, records, y_mean, y_scale)
        if checkpoint is not None:
            checkpoint(partial)
    return FittedPredictor(name, scaler, models, records, y_mean, y_scale)


def predict_raw(fitted, X, dates=None):
    X = np.asarray(X, float)
    if X.ndim != 2 or X.shape[1] != FEATURE_COUNT or not np.isfinite(X).all(): raise ValueError("NONFINITE_OR_SHAPE_PREDICT_INPUT")
    x = fitted.scaler.transform(X)
    name, model = fitted.name, fitted.models[0]
    if any(record["status"] != "TRAINED" for record in fitted.fit_status):
        raise RuntimeError(f"PREDICTOR_HAS_FAILED_PHYSICAL_SPEC:{name}")
    with threadpool_limits(limits=2):
        if name in PROBABILITY_NAMES:
            result = {"p": np.asarray(model.predict(x) if isinstance(model, TorchRegressor) else model.predict_proba(x)[:, 1], float)}
        elif name in QUANTILE_NAMES:
            result = {key: np.asarray(m.predict(x), float) for key, m in zip(("q10", "q50", "q90"), fitted.models)}
        elif name == "ngboost":
            distribution = model.pred_dist(x)
            result = {"location": np.asarray(distribution.params["loc"], float), "scale": np.asarray(distribution.params["scale"], float)}
        elif name == "gaussian_mlp":
            value = model.predict(x)
            result = {"location": value[:, 0], "scale": value[:, 1]}
        elif name == "cat_uncertainty":
            value = np.asarray(model.predict(x, prediction_type="RawFormulaVal"), float)
            result = {"location": value[:, 0]*fitted.y_scale+fitted.y_mean,
                      "scale": np.exp(np.clip(value[:, 1], -20., 20.))*fitted.y_scale,
                      "raw_log_scale": value[:, 1]}
        elif name in RANK_NAMES:
            result = {"rank": np.asarray(model.predict(x), float)}
        else:
            result = {"raw": np.asarray(model.predict(x), float)}
    for key, value in result.items():
        if value.shape != (len(X),) or not np.isfinite(value).all(): raise RuntimeError(f"NONFINITE_OR_SHAPE_OUTPUT:{name}:{key}")
    if "p" in result and ((result["p"] < 0).any() or (result["p"] > 1).any()): raise RuntimeError("PROBABILITY_OUT_OF_BOUNDS")
    if "scale" in result and (result["scale"] <= 0).any(): raise RuntimeError("NONPOSITIVE_DISTRIBUTION_SCALE")
    return result
