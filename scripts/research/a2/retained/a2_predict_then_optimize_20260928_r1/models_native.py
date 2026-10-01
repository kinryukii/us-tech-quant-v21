"""Frozen native predictors for the Predict-then-Optimize experiment.

No fit occurs on import. Native outputs retain their statistical meaning;
explicit, train-only adapters provide the separate ``mu`` decision interface.
External implementations are imported lazily and are never substituted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
import sys
import warnings

sys.dont_write_bytecode = True
THIRD_PARTY = Path(__file__).resolve().parent / "third_party"
if THIRD_PARTY.is_dir():
    sys.path.insert(0, str(THIRD_PARTY))

import joblib
import numpy as np
import pandas as pd
from scipy.special import ndtr
from sklearn.ensemble import (ExtraTreesRegressor, HistGradientBoostingClassifier,
                              HistGradientBoostingRegressor, RandomForestClassifier,
                              RandomForestRegressor)
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import (ElasticNet, HuberRegressor, LogisticRegression,
                                 QuantileRegressor, Ridge)
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor
from threadpoolctl import threadpool_limits

SEED = 20260928
QUANTILES = np.array([.1, .5, .9])
QUANTILE_MEAN_WEIGHTS = np.array([.3, .4, .3])
NORMAL_Q = np.array([-1.2815515655446004, 0., 1.2815515655446004])
OUTPUT_COLUMNS = ["mu", "sigma", "p_up", "q10", "q50", "q90"]
POINT_IDS = ("ridge", "elastic", "huber", "ebm", "rf", "extra", "hgb", "xgb",
             "lgb", "cat", "mlp", "resnet", "fttransformer")
CLASS_IDS = ("logistic", "rf_cls", "hgb_cls", "xgb_cls", "lgb_cls", "cat_cls", "mlp_cls")
QUANTILE_IDS = ("linear_q", "hgb_q", "xgb_q", "lgb_q", "cat_q", "mlp_q")
DISTRIBUTION_IDS = ("ngboost", "mlp_dist", "cat_uncertainty")
RANK_IDS = ("xgb_rank", "lgb_rank")
MODEL_IDS = POINT_IDS + CLASS_IDS + QUANTILE_IDS + DISTRIBUTION_IDS + RANK_IDS
assert len(MODEL_IDS) == 31 and len(set(MODEL_IDS)) == 31

TREE_SPEC = dict(max_iter=100, max_depth=3, max_leaf_nodes=15, min_samples_leaf=100,
                 l2_regularization=5., learning_rate=.05, early_stopping=False,
                 random_state=SEED)
MLP_SPEC = dict(hidden_layer_sizes=(32, 16), activation="relu", solver="adam",
                alpha=.01, batch_size=512, max_iter=20, n_iter_no_change=21,
                early_stopping=False, learning_rate_init=.001, random_state=SEED)
RF_SPEC = dict(n_estimators=100, max_depth=6, min_samples_leaf=40,
               max_features=1., n_jobs=2, random_state=SEED)
XGB_SPEC = dict(n_estimators=100, max_depth=3, max_leaves=15, min_child_weight=100.,
                reg_lambda=5., learning_rate=.05, tree_method="hist", n_jobs=2,
                subsample=1., colsample_bytree=1., random_state=SEED, verbosity=0)
LGB_SPEC = dict(n_estimators=100, max_depth=3, num_leaves=15, min_child_samples=100,
                reg_lambda=5., learning_rate=.05, n_jobs=2, random_state=SEED,
                subsample=1., colsample_bytree=1., verbosity=-1, deterministic=True,
                force_col_wise=True)
CAT_SPEC = dict(iterations=100, depth=3, min_data_in_leaf=100, l2_leaf_reg=5.,
                learning_rate=.05, random_seed=SEED, thread_count=2,
                allow_writing_files=False, verbose=False, bootstrap_type="No")


def kind_for(model_id):
    for kind, names in [("point", POINT_IDS), ("probability", CLASS_IDS),
                        ("quantile", QUANTILE_IDS), ("distribution", DISTRIBUTION_IDS),
                        ("rank", RANK_IDS)]:
        if model_id in names:
            return kind
    raise ValueError(f"UNKNOWN_NATIVE_MODEL:{model_id}")


def specs():
    """Serializable pre-fit specifications, including adapter limitations."""
    return dict(seed=SEED, point=list(POINT_IDS), probability=list(CLASS_IDS),
        quantile=list(QUANTILE_IDS), distribution=list(DISTRIBUTION_IDS), rank=list(RANK_IDS),
        hgb=TREE_SPEC, mlp=MLP_SPEC, random_trees=RF_SPEC, xgb=XGB_SPEC, lgb=LGB_SPEC,
        cat=CAT_SPEC, ridge=dict(alpha=10., solver="auto"),
        elastic=dict(alpha=.0001, l1_ratio=.35, max_iter=2500, tol=1e-5),
        huber=dict(epsilon=1.35, alpha=.01, max_iter=500),
        ebm=dict(interactions=0, max_rounds=200, outer_bags=2, validation_size=0,
                 early_stopping_rounds=0, smoothing_rounds=0, interaction_smoothing_rounds=0,
                 n_jobs=2, random_state=SEED),
        linear_quantile=dict(alpha=.0001, solver="highs", quantiles=QUANTILES.tolist()),
        neural=dict(epochs=12, batch_size=512, learning_rate=.001, weight_decay=.01,
                    resnet_width=32, resnet_blocks=2, ft_token_dim=8, ft_heads=2,
                    ft_layers=2, target_scale=.1, final_epoch_only=True,
                    deterministic=True, CPU_threads=2),
        ngboost=dict(n_estimators=100, learning_rate=.05, distribution="Normal",
                     base_depth=3, base_min_samples_leaf=100, minibatch_frac=1.,
                     col_sample=1., tol=0., early_stopping_rounds=None,
                     numerical_line_search_guard="64 finite downscales; exact zero/unrepresentable update or no improvement returns zero; never ends boosting rounds"),
        adapters=dict(probability="p_up*train_mean_positive+(1-p_up)*train_mean_nonpositive",
            quantile="sorted(q10,q50,q90)@[.3,.4,.3]+train_weighted_mean_residual",
            huber="robust_location+train_weighted_mean_residual",
            rank="isotonic(score->clipped_return), train-only in-sample adaptation; not OOF calibration",
            point_sigma="train residual RMS; homoskedastic and in-sample, not a calibrated distribution",
            quantile_sigma="(q90-q10)/(2*1.2815515655446004), normal-equivalent diagnostic",
            classification_sigma="mixture second moment from train conditional classes"))


def _import(name):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ImportError(f"NATIVE_DEPENDENCY_UNAVAILABLE:{name}; no substitute authorized") from exc


def _bounded_ngboost_line_search(self, resids, start, y, sample_weight=None, scale_init=1):
    """Protect the upstream tol=0 zero-gradient loop without early stopping.

    NGBoost 0.5.11's shrink loop never terminates when its update rounds to zero
    and norm < tol is impossible. Returning a zero step keeps all 100 boosting
    rounds. The native objective and native gradient are unchanged.
    """
    self.numerical_line_search_guard_count_ = getattr(self, "numerical_line_search_guard_count_", 0)
    initial_loss = self.Manifold(start.T).total_score(y, sample_weight)
    scale = float(scale_init)
    for _ in range(10):
        update = resids*scale
        loss = self.Manifold((start-update).T).total_score(y, sample_weight)
        if not np.isfinite(loss) or loss > initial_loss or scale > 256:
            break
        scale *= 2.
    for _ in range(64):
        update = resids*scale
        proposed = start-update
        if np.array_equal(proposed, start) or not np.any(update):
            self.numerical_line_search_guard_count_ += 1
            scale = 0.
            break
        loss = self.Manifold(proposed.T).total_score(y, sample_weight)
        if np.isfinite(loss) and loss < initial_loss:
            break
        scale *= .5
    else:
        self.numerical_line_search_guard_count_ += 1
        scale = 0.
    self.scalings.append(scale)
    return scale


def _fixed_ngboost_class():
    if "FixedBudgetNGBRegressor" not in globals():
        globals()["FixedBudgetNGBRegressor"] = type("FixedBudgetNGBRegressor",
            (_import("ngboost").NGBRegressor,),
            {"line_search": _bounded_ngboost_line_search, "__module__": __name__})
    return globals()["FixedBudgetNGBRegressor"]


def __getattr__(name):
    # A fresh deserializer recreates the lazy, native NGBoost subclass by name.
    if name == "FixedBudgetNGBRegressor":
        return _fixed_ngboost_class()
    raise AttributeError(name)


def estimator(model_id, quantile=None):
    """Create exactly one predeclared native implementation."""
    if model_id == "ridge":
        return Ridge(alpha=10., solver="auto")
    if model_id == "elastic":
        return ElasticNet(alpha=.0001, l1_ratio=.35, max_iter=2500, tol=1e-5,
                          selection="cyclic", random_state=SEED)
    if model_id == "huber":
        return HuberRegressor(epsilon=1.35, alpha=.01, max_iter=500)
    if model_id == "ebm":
        return _import("interpret.glassbox").ExplainableBoostingRegressor(**specs()["ebm"])
    if model_id == "rf":
        return RandomForestRegressor(**RF_SPEC)
    if model_id == "extra":
        return ExtraTreesRegressor(**RF_SPEC)
    if model_id in ("hgb", "hgb_q"):
        return HistGradientBoostingRegressor(**TREE_SPEC, **({"loss": "quantile", "quantile": quantile}
                                                           if model_id == "hgb_q" else {}))
    if model_id == "mlp":
        return MLPRegressor(**MLP_SPEC)
    if model_id == "logistic":
        return LogisticRegression(C=.3, max_iter=400, solver="lbfgs", random_state=SEED)
    if model_id == "rf_cls":
        return RandomForestClassifier(**RF_SPEC)
    if model_id == "hgb_cls":
        return HistGradientBoostingClassifier(**TREE_SPEC)
    if model_id == "mlp_cls":
        return MLPClassifier(**MLP_SPEC)
    if model_id == "linear_q":
        return QuantileRegressor(quantile=float(quantile), alpha=.0001, solver="highs")
    if model_id in ("xgb", "xgb_cls", "xgb_q", "xgb_rank"):
        module = _import("xgboost")
        if model_id == "xgb_cls":
            return module.XGBClassifier(**XGB_SPEC, objective="binary:logistic", eval_metric="logloss")
        if model_id == "xgb_rank":
            return module.XGBRanker(**XGB_SPEC, objective="rank:pairwise")
        return module.XGBRegressor(**XGB_SPEC, **({"objective": "reg:quantileerror",
                                                 "quantile_alpha": float(quantile)}
                                                if model_id == "xgb_q" else {"objective": "reg:squarederror"}))
    if model_id in ("lgb", "lgb_cls", "lgb_q", "lgb_rank"):
        module = _import("lightgbm")
        if model_id == "lgb_cls":
            return module.LGBMClassifier(**LGB_SPEC, objective="binary")
        if model_id == "lgb_rank":
            return module.LGBMRanker(**LGB_SPEC, objective="lambdarank", label_gain=[0, 1, 3, 7, 15])
        return module.LGBMRegressor(**LGB_SPEC, **({"objective": "quantile", "alpha": float(quantile)}
                                                 if model_id == "lgb_q" else {"objective": "regression"}))
    if model_id in ("cat", "cat_cls", "cat_q", "cat_uncertainty"):
        module = _import("catboost")
        if model_id == "cat_cls":
            return module.CatBoostClassifier(**CAT_SPEC, loss_function="Logloss")
        loss = "RMSEWithUncertainty" if model_id == "cat_uncertainty" else (
            f"Quantile:alpha={float(quantile)}" if model_id == "cat_q" else "RMSE")
        return module.CatBoostRegressor(**CAT_SPEC, loss_function=loss)
    if model_id == "ngboost":
        module = _import("ngboost")
        normal = _import("ngboost.distns").Normal
        return _fixed_ngboost_class()(Dist=normal,
            Base=DecisionTreeRegressor(max_depth=3, min_samples_leaf=100, random_state=SEED),
            n_estimators=100, learning_rate=.05, minibatch_frac=1., col_sample=1.,
            random_state=SEED, verbose=False, tol=0.)
    if model_id in ("resnet", "fttransformer", "mlp_q", "mlp_dist"):
        return None
    raise ValueError(f"UNKNOWN_NATIVE_MODEL:{model_id}")


def weighted_mean(value, weight):
    return float(np.average(np.asarray(value, float), weights=np.asarray(weight, float)))


def probability_amplitudes(y, weight):
    y, weight = np.asarray(y, float), np.asarray(weight, float)
    positive = y > 0
    if not positive.any() or positive.all():
        raise ValueError("BOTH_RETURN_CLASSES_REQUIRED")
    return dict(positive_mean=weighted_mean(y[positive], weight[positive]),
                nonpositive_mean=weighted_mean(y[~positive], weight[~positive]),
                positive_second_moment=weighted_mean(y[positive] ** 2, weight[positive]),
                nonpositive_second_moment=weighted_mean(y[~positive] ** 2, weight[~positive]))


def probability_to_moments(p_up, amplitude):
    p = np.asarray(p_up, float)
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("INVALID_NATIVE_PROBABILITY")
    mu = p * amplitude["positive_mean"] + (1-p) * amplitude["nonpositive_mean"]
    second = p * amplitude["positive_second_moment"] + (1-p) * amplitude["nonpositive_second_moment"]
    return mu, np.sqrt(np.maximum(second-mu ** 2, 1e-10))


def quantile_to_moments(raw_quantiles, offset=0.):
    q = np.asarray(raw_quantiles, float)
    if q.ndim != 2 or q.shape[1] != 3 or not np.isfinite(q).all():
        raise ValueError("QUANTILE_ADAPTER_REQUIRES_FINITE_N_BY_3")
    q = np.sort(q, axis=1)
    mu = q @ QUANTILE_MEAN_WEIGHTS + float(offset)
    sigma = np.maximum((q[:, 2]-q[:, 0]) / (2*NORMAL_Q[2]), 1e-5)
    return q, mu, sigma


def relevance_for_dates(y, dates):
    """Daily five-bin relevance; equal returns have equal relevance."""
    frame = pd.DataFrame(dict(y=np.asarray(y, float), date=pd.to_datetime(dates)))
    percentile = frame.groupby("date", sort=False).y.rank(method="average", pct=True)
    return np.minimum((percentile.to_numpy()*5).astype(np.int32), 4)


def group_lengths(dates):
    dates = pd.to_datetime(dates)
    if len(dates) == 0 or not dates.is_monotonic_increasing:
        raise ValueError("RANK_TRAINING_REQUIRES_CHRONOLOGICAL_CONTIGUOUS_GROUPS")
    return pd.Series(dates).groupby(dates, sort=True).size().to_numpy(np.int32)


def make_torch_network(kind, n_features):
    """Small explicit architectures; no external architecture substitution."""
    torch = _import("torch")
    nn = torch.nn

    class ResidualBlock(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(nn.LayerNorm(32), nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, 32))
        def forward(self, x):
            return x+self.net(x)

    class TabularResNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.input = nn.Linear(n_features, 32)
            self.blocks = nn.Sequential(ResidualBlock(), ResidualBlock())
            self.output = nn.Sequential(nn.LayerNorm(32), nn.ReLU(), nn.Linear(32, 1))
        def forward(self, x):
            return self.output(self.blocks(self.input(x))).flatten()

    class FTTransformer(nn.Module):
        def __init__(self):
            super().__init__()
            self.token_weight = nn.Parameter(torch.empty(n_features, 8))
            self.token_bias = nn.Parameter(torch.zeros(n_features, 8))
            self.cls = nn.Parameter(torch.zeros(1, 1, 8))
            nn.init.normal_(self.token_weight, std=.1)
            layer = nn.TransformerEncoderLayer(d_model=8, nhead=2, dim_feedforward=32,
                dropout=0., activation="relu", batch_first=True, norm_first=True)
            self.encoder = nn.TransformerEncoder(layer, num_layers=2, enable_nested_tensor=False)
            self.output = nn.Sequential(nn.LayerNorm(8), nn.Linear(8, 1))
        def forward(self, x):
            tokens = x[:, :, None]*self.token_weight[None]+self.token_bias[None]
            tokens = torch.cat([self.cls.expand(len(x), -1, -1), tokens], dim=1)
            return self.output(self.encoder(tokens)[:, 0]).flatten()

    if kind == "resnet":
        return TabularResNet()
    if kind == "fttransformer":
        return FTTransformer()
    output = 3 if kind == "mlp_q" else 2
    if kind not in ("mlp_q", "mlp_dist"):
        raise ValueError(f"UNKNOWN_TORCH_NATIVE:{kind}")
    return nn.Sequential(nn.Linear(n_features, 32), nn.ReLU(), nn.Linear(32, 16),
                         nn.ReLU(), nn.Linear(16, output))


def torch_loss(kind, prediction, target, weights):
    torch = _import("torch")
    if kind == "mlp_q":
        error = target[:, None]-prediction
        quantiles = prediction.new_tensor(QUANTILES)
        per_row = torch.maximum(quantiles*error, (quantiles-1)*error).mean(dim=1)
    elif kind == "mlp_dist":
        sigma = torch.nn.functional.softplus(prediction[:, 1])+1e-3
        per_row = torch.log(sigma)+.5*((target-prediction[:, 0])/sigma)**2
    else:
        per_row = (prediction-target)**2
    return torch.sum(weights*per_row)/weights.sum()


def fit_torch(kind, x, y, weight):
    torch = _import("torch")
    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    model = make_torch_network(kind, x.shape[1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.01)
    xx = torch.tensor(np.asarray(x, np.float32))
    yy = torch.tensor(np.asarray(y, np.float32)/.1)
    ww = torch.tensor(np.asarray(weight, np.float32))
    generator = torch.Generator().manual_seed(SEED)
    losses = []
    for epoch in range(12):
        model.train()
        order = torch.randperm(len(xx), generator=generator)
        loss_sum, weight_sum = 0., 0.
        for start in range(0, len(xx), 512):
            ids = order[start:start+512]
            optimizer.zero_grad(set_to_none=True)
            loss = torch_loss(kind, model(xx[ids]), yy[ids], ww[ids])
            if not torch.isfinite(loss):
                raise RuntimeError(f"NONFINITE_NATIVE_NEURAL_LOSS:{kind}:{epoch}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
            optimizer.step()
            batch_weight = float(ww[ids].sum())
            loss_sum += float(loss.detach())*batch_weight
            weight_sum += batch_weight
        losses.append(loss_sum/weight_sum)
    model.eval()
    state = {k: v.detach().cpu().numpy().copy() for k, v in model.state_dict().items()}
    return dict(kind=kind, n_features=x.shape[1], state=state), dict(
        epochs=12, loss_by_epoch=losses, final_epoch_only=True, optimizer_steps=12*int(np.ceil(len(x)/512)))


def predict_torch(payload, x, batch_size=2048):
    torch = _import("torch")
    torch.set_num_threads(2)
    model = make_torch_network(payload["kind"], payload["n_features"])
    model.load_state_dict({key: torch.tensor(value) for key, value in payload["state"].items()})
    model.eval()
    parts = []
    with torch.no_grad():
        for start in range(0, len(x), batch_size):
            parts.append(model(torch.tensor(np.asarray(x[start:start+batch_size], np.float32))).numpy())
    if not parts:
        width = 3 if payload["kind"] == "mlp_q" else (2 if payload["kind"] == "mlp_dist" else None)
        return np.empty((0, width)) if width else np.empty(0)
    return np.concatenate(parts)


@dataclass
class NativeBundle:
    model_id: str
    features: list[str]
    estimator_object: object = None
    scaler: object = None
    adapter: dict = field(default_factory=dict)
    fit_receipt: dict = field(default_factory=dict)
    _torch_model: object = field(default=None, repr=False, compare=False)

    def matrix(self, frame):
        if isinstance(frame, pd.DataFrame):
            missing = set(self.features)-set(frame.columns)
            if missing:
                raise ValueError(f"NATIVE_FEATURES_MISSING:{sorted(missing)}")
            x = frame[self.features].to_numpy(float)
        else:
            x = np.asarray(frame, float)
        if x.ndim != 2 or x.shape[1] != len(self.features) or not np.isfinite(x).all():
            raise ValueError("NATIVE_REQUIRES_FINITE_ORDERED_FEATURE_MATRIX")
        return x if self.scaler is None else self.scaler.transform(x)

    def _torch(self, x):
        # Restore once per in-memory bundle to keep daily replay practical.
        torch = _import("torch")
        if self._torch_model is None:
            self._torch_model = make_torch_network(self.model_id, len(self.features))
            self._torch_model.load_state_dict({k: torch.tensor(v) for k, v in self.estimator_object["state"].items()})
            self._torch_model.eval()
        parts = []
        with torch.no_grad():
            for start in range(0, len(x), 2048):
                parts.append(self._torch_model(torch.tensor(np.asarray(x[start:start+2048], np.float32))).numpy())
        return np.concatenate(parts) if parts else np.empty(0)

    def raw_predict(self, x):
        kind = kind_for(self.model_id)
        if self.model_id in ("resnet", "fttransformer", "mlp_q", "mlp_dist"):
            return self._torch(x)*.1 if self.model_id != "mlp_dist" else self._torch(x)
        if kind == "quantile":
            return np.column_stack([model.predict(x) for model in self.estimator_object])
        if kind == "probability":
            return np.asarray(self.estimator_object.predict_proba(x))[:, 1]
        if self.model_id == "ngboost":
            distribution = self.estimator_object.pred_dist(x)
            return np.column_stack([distribution.loc, distribution.scale])
        if self.model_id == "cat_uncertainty":
            # CatBoost objective's raw second coordinate is log(sigma).
            # https://catboost.ai/docs/en/concepts/loss-functions-regression
            raw = np.asarray(self.estimator_object.predict(x, prediction_type="RawFormulaVal"))
            return np.column_stack([raw[:, 0], np.exp(np.clip(raw[:, 1], -20., 10.))])
        return np.asarray(self.estimator_object.predict(x), float)

    def predict(self, frame):
        x = self.matrix(frame)
        if len(x) == 0:
            return pd.DataFrame(columns=OUTPUT_COLUMNS, dtype=float)
        with threadpool_limits(limits=2):
            raw = self.raw_predict(x)
        kind, n = kind_for(self.model_id), len(x)
        output = {col: np.full(n, np.nan) for col in OUTPUT_COLUMNS}
        if kind == "probability":
            output["p_up"] = raw
            output["mu"], output["sigma"] = probability_to_moments(raw, self.adapter)
        elif kind == "quantile":
            q, output["mu"], output["sigma"] = quantile_to_moments(raw, self.adapter.get("offset", 0.))
            output.update(zip(["q10", "q50", "q90"], q.T))
        elif kind == "distribution":
            if self.model_id == "mlp_dist":
                from scipy.special import log_expit
                mu, sigma = raw[:, 0]*.1, (-log_expit(-raw[:, 1])+1e-3)*.1
            else:
                mu, sigma = raw[:, 0], raw[:, 1]
            sigma = np.maximum(sigma, 1e-5)
            output["mu"], output["sigma"] = mu, sigma
            output["p_up"] = ndtr(mu/sigma)
            output.update(zip(["q10", "q50", "q90"], (mu[:, None]+sigma[:, None]*NORMAL_Q).T))
        elif kind == "rank":
            output["mu"] = self.adapter["isotonic"].predict(raw)
            output["sigma"] = np.full(n, self.adapter["residual_sigma"])
            output["native_rank_score"] = raw
        else:
            output["mu"] = raw+self.adapter.get("offset", 0.)
            output["sigma"] = np.full(n, self.adapter["residual_sigma"])
            output["native_point_location"] = raw
        if kind == "quantile":
            output.update(zip(["raw_q10", "raw_q50", "raw_q90"], raw.T))
        result = pd.DataFrame(output)
        if not np.isfinite(result[["mu", "sigma"]].to_numpy()).all() or not result.sigma.gt(0).all():
            raise RuntimeError(f"NONFINITE_NATIVE_OUTPUT:{self.model_id}")
        native_cols = ["p_up"] if kind == "probability" else (
            ["q10", "q50", "q90"] if kind == "quantile" else OUTPUT_COLUMNS if kind == "distribution" else [])
        if native_cols and not np.isfinite(result[native_cols].to_numpy()).all():
            raise RuntimeError(f"NONFINITE_NATIVE_STATISTICAL_OUTPUT:{self.model_id}")
        return result

    @classmethod
    def fit(cls, model_id, frame, y, weights, features, *, rank_relevance=None, dates=None):
        """Fit once to already purged stage rows; record every warning."""
        bundle = cls(model_id, list(features))
        kind = kind_for(model_id)
        x, y, weights = np.asarray(frame[features], float), np.asarray(y, float), np.asarray(weights, float)
        if x.shape != (len(y), len(features)) or weights.shape != y.shape or len(y) == 0:
            raise ValueError("INVALID_NATIVE_TRAINING_SHAPES")
        if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(weights).all() or np.any(weights <= 0):
            raise ValueError("NONFINITE_NATIVE_TRAINING_DATA")
        if np.any(np.abs(y) > .2+1e-12):
            raise ValueError("NATIVE_TRAINING_TARGET_MUST_BE_PRECLIPPED")
        if model_id in ("ridge", "elastic", "huber", "logistic", "mlp", "mlp_cls", "linear_q",
                        "resnet", "fttransformer", "mlp_q", "mlp_dist"):
            bundle.scaler = StandardScaler().fit(x, sample_weight=weights)
            x = bundle.scaler.transform(x)
        with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=2):
            warnings.simplefilter("always")
            if model_id in ("resnet", "fttransformer", "mlp_q", "mlp_dist"):
                bundle.estimator_object, neural_receipt = fit_torch(model_id, x, y, weights)
                bundle.fit_receipt.update(neural_receipt)
            elif kind == "quantile":
                bundle.estimator_object = []
                for quantile in QUANTILES:
                    model = estimator(model_id, quantile)
                    model.fit(x, y, sample_weight=weights)
                    bundle.estimator_object.append(model)
            else:
                model = estimator(model_id)
                if kind == "rank":
                    if dates is None or rank_relevance is None:
                        raise ValueError("RANK_REQUIRES_STAGE_ONLY_DAILY_RELEVANCE_AND_DATES")
                    groups = group_lengths(dates)
                    relevance = np.asarray(rank_relevance, np.int32)
                    if relevance.shape != y.shape or np.any((relevance < 0) | (relevance > 4)):
                        raise ValueError("INVALID_RANK_RELEVANCE")
                    if model_id == "xgb_rank":
                        model.fit(x, relevance, group=groups, sample_weight=np.ones(len(groups)))
                    else:
                        model.fit(x, relevance, group=groups, sample_weight=weights)
                    bundle.fit_receipt["rank_training_groups"] = groups.tolist()
                else:
                    model.fit(x, (y > 0).astype(int) if kind == "probability" else y, sample_weight=weights)
                bundle.estimator_object = model
            if kind == "probability":
                bundle.adapter = probability_amplitudes(y, weights)
            elif kind == "quantile":
                _, mean_proxy, _ = quantile_to_moments(bundle.raw_predict(x))
                bundle.adapter = dict(offset=weighted_mean(y-mean_proxy, weights),
                    semantics="three-quantile integral approximation plus train-only in-sample residual offset",
                    quantile_crossing_rule="deterministic per-row sorting")
            elif kind == "rank":
                scores = bundle.raw_predict(x)
                calibration = IsotonicRegression(out_of_bounds="clip").fit(scores, y, sample_weight=weights)
                residual = y-calibration.predict(scores)
                bundle.adapter = dict(isotonic=calibration,
                    residual_sigma=max(np.sqrt(weighted_mean(residual**2, weights)), 1e-5),
                    semantics="stage-train-only in-sample score-to-return adapter; not OOF calibration")
            elif kind == "point":
                prediction = bundle.raw_predict(x)
                offset = weighted_mean(y-prediction, weights) if model_id == "huber" else 0.
                residual = y-prediction-offset
                bundle.adapter = dict(offset=offset,
                    residual_sigma=max(np.sqrt(weighted_mean(residual**2, weights)), 1e-5),
                    semantics="robust location + train-only residual offset" if model_id == "huber" else
                              "point regression; residual sigma is in-sample homoskedastic diagnostic")
            bundle.fit_receipt["warnings"] = [dict(category=w.category.__name__, message=str(w.message)) for w in captured]
        models = bundle.estimator_object if isinstance(bundle.estimator_object, list) else [bundle.estimator_object]
        bundle.fit_receipt.update(model_id=model_id, native_kind=kind, sample_count=len(y),
            sample_weight_sum=float(weights.sum()), fit_calls=3 if kind == "quantile" and model_id != "mlp_q" else 1,
            adapter_fit_scope="purged stage training rows only; no evaluation labels",
            observed_iterations=[getattr(model, "n_iter_", getattr(model, "tree_count_", None)) for model in models])
        if model_id == "ngboost":
            bundle.fit_receipt["boosting_rounds_completed"] = len(bundle.estimator_object.base_models)
            bundle.fit_receipt["numerical_line_search_guard_count"] = getattr(bundle.estimator_object, "numerical_line_search_guard_count_", 0)
            if len(bundle.estimator_object.base_models) != 100:
                raise RuntimeError("NATIVE_NGBOOST_FIXED_100_ROUND_BUDGET_NOT_COMPLETED")
        if model_id in ("mlp", "mlp_cls") and bundle.estimator_object.n_iter_ != 20:
            raise RuntimeError(f"NATIVE_MLP_FIXED_EPOCH_BUDGET_NOT_COMPLETED:{model_id}")
        bundle._torch_model = None
        return bundle

    def save(self, path):
        self._torch_model = None
        joblib.dump(self, path, compress=3)

    @classmethod
    def load(cls, path):
        result = joblib.load(path)
        if not isinstance(result, cls) or result.model_id not in MODEL_IDS:
            raise ValueError("INVALID_NATIVE_BUNDLE_ARTIFACT")
        result._torch_model = None
        return result


if __name__ == "__main__":
    print(json.dumps(specs(), ensure_ascii=False, indent=2))
