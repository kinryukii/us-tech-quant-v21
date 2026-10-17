"""Fixed learning-objective adapters on the unchanged 32-feature selector input.

No data reader, scaler, calibration, risk representation or search lives here.
The runner owns full-pool boundary labels, sampled keys, clocks and reservations.
Architectures and estimator capacities come from the retained predictor owner.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import importlib
import sys
import warnings

import numpy as np
import pandas as pd

SEED = 20260928
FEATURE_COUNT = 32
PAIR_PARTNERS = 4
ROLE_IDS = (
    "BOUNDARY_LOGISTIC", "BOUNDARY_RF", "BOUNDARY_EXTRA", "BOUNDARY_HGB",
    "BOUNDARY_XGB", "BOUNDARY_LGB", "BOUNDARY_CAT", "BOUNDARY_MLP",
    "PAIRWISE_LINEAR", "PAIRWISE_MLP", "PAIRWISE_RESNET", "PAIRWISE_FT",
    "LISTWISE_MLP", "LISTWISE_RESNET", "LISTWISE_FT",
    "RANK_XGB_NDCG", "RANK_LGB_XENDCG", "RANK_CAT_YETIRANK",
)
OWNER = "scripts/research/a2/retained/a2_pto_full_compat_20260928_r2/predictors.py"
_NEURAL_CAPACITY = dict(
    epochs=10, batch_size=512, learning_rate=.001, weight_decay=.0001,
    hidden=32, feature_clip=[-8., 8.], seed=SEED, threads=2, dropout=0.,
    target_standardization="NONE", gradient_clip_norm=5.,
    checkpoint="FINAL_EPOCH_ONLY", optimizer="Adam",
    row_permutation="torch.randperm; generator seed 20260928; ten fixed epochs",
)
_CAPACITIES = {
    "logistic": dict(C=.3, max_iter=400, solver="lbfgs", random_state=SEED),
    "rf": dict(n_estimators=64, max_depth=3, min_samples_leaf=100,
               max_features=1., n_jobs=2, random_state=SEED),
    "hgb": dict(max_iter=64, max_depth=3, max_leaf_nodes=15,
                min_samples_leaf=100, learning_rate=.05, l2_regularization=1.,
                early_stopping=False, random_state=SEED),
    "xgb": dict(n_estimators=64, max_depth=3, min_child_weight=20,
                learning_rate=.05, subsample=1., colsample_bytree=1.,
                reg_lambda=1., tree_method="hist", n_jobs=2,
                random_state=SEED, verbosity=0),
    "lgb": dict(n_estimators=64, max_depth=3, num_leaves=8,
                min_child_samples=100, learning_rate=.05, reg_lambda=1.,
                n_jobs=2, random_state=SEED, deterministic=True,
                force_col_wise=True, verbosity=-1),
    "cat": dict(iterations=64, depth=3, learning_rate=.05, l2_leaf_reg=3.,
                thread_count=2, random_seed=SEED, verbose=False,
                allow_writing_files=False),
}


def role_specs():
    """Return the complete ordered, immutable-by-copy scientific specification."""
    specs = {}
    for role in ROLE_IDS:
        kind = role.split("_", 1)[0]
        family = role.split("_")[1].lower()
        if family == "extra":
            capacity = _CAPACITIES["rf"]
        elif family in ("mlp", "resnet", "ft"):
            capacity = {**_NEURAL_CAPACITY, "architecture":
                        {"ft": "fttransformer"}.get(family, family)}
            if family == "ft":
                capacity.update(token_dim=16, heads=2, layers=1,
                                feedforward_dim=32)
        else:
            capacity = _CAPACITIES["logistic" if family == "linear" else family]
        if family == "linear":
            capacity = {**capacity, "fit_intercept": False}
        spec = dict(
            role_id=role, family=family, objective_family=kind,
            seed=SEED, feature_count=FEATURE_COUNT, capacity_owner=OWNER,
            capacity=copy.deepcopy(capacity), estimator_fit_calls=1,
            scaler_fit_calls=0, target_stat_estimation=0, scientific_retry=0,
            external_row_weight="UNIT; retained common day-balanced sample",
            score_direction="HIGHER_FIRST", configurations=1,
            backend_version_policy="EXACT_LOADED_VERSION_AND_ORIGIN_PINNED_IN_PARENT_DESIGN",
            information_set="UNCHANGED_CANONICAL_RAW_A2_32_FEATURES",
            target="MEAN_ER_3D_5D_10D_20D; evaluation values unchanged",
        )
        if kind == "BOUNDARY":
            spec.update(
                objective="BINARY_CROSS_ENTROPY",
                training_label="RUNNER_FULL_MATURE_TRAIN_POOL_TOP_MIN_20; target desc then UID asc; take common sampled keys afterwards",
                class_balance="NONE", class_threshold="NONE",
                final_selection_score="NATIVE_BOUNDARY_PROBABILITY",
            )
        elif kind == "PAIRWISE":
            spec.update(
                objective="PAIRWISE_LOGISTIC_ORDER",
                pair_construction="WITHIN_SAMPLED_DATE; every input row is anchor; min(4,n_group-1) uniform distinct partners; excludes self; independent of target",
                pair_seed=SEED, pair_weight="1/number_of_drawn_partners per anchor; ties retain zero loss; row-equivalent anchor mean",
                pair_label="SIGN(raw target_i - raw target_j); tie=0",
                final_selection_score="NATIVE_LINEAR_OR_NEURAL_LOGIT",
                empty_group="INPUT_ROWS_RETAINED_ZERO_LOSS; no substitute pair",
            )
        elif kind == "LISTWISE":
            spec.update(
                objective="SAMPLED_GROUP_TOP20_MASS_CROSS_ENTROPY",
                gain="RUNNER_FULL_MATURE_TRAIN_POOL_TOP20_INDICATOR",
                probability_transform="indicator / sampled_group_positive_count",
                group_weight="n_group; total group loss divided by total sampled rows",
                group_permutation="torch.randperm groups; same fixed torch generator seed",
                batch_semantics="whole groups; row budget 512; oversized single group is never split",
                empty_positive_group="INPUT_ROWS_RETAINED_ZERO_LOSS; no substitute labels or samples",
                final_selection_score="NATIVE_NEURAL_LOGIT",
            )
        else:
            spec.update(
                training_label="OLD_SAMPLED_GROUP_AVERAGE_PCT_RANK; floor(rank*5), clipped to 4",
                ranking_group="DECISION_DATE", object_weight="UNIT", group_weight="UNIT",
                final_selection_score="NATIVE_RANK_SCORE",
            )
            if role == "RANK_XGB_NDCG":
                spec.update(
                    objective="rank:ndcg", gain=[0, 1, 3, 7, 15],
                    native_params=dict(
                        objective="rank:ndcg", lambdarank_pair_method="mean",
                        lambdarank_num_pair_per_sample=4,
                        lambdarank_ndcg_exp_gain=True, eval_metric="ndcg@20"),
                )
            elif role == "RANK_LGB_XENDCG":
                spec.update(
                    objective="rank_xendcg", gain=[0, 1, 3, 7, 15],
                    native_params=dict(
                        objective="rank_xendcg", label_gain=[0, 1, 3, 7, 15],
                        objective_seed=SEED, lambdarank_truncation_level=20,
                        lambdarank_norm=True),
                )
            else:
                spec.update(
                    objective="YetiRank:mode=Classic;permutations=10;decay=0.85",
                    gain="NATIVE_CLASSIC_YETIRANK_ON_FIXED_0_TO_4_RELEVANCE",
                    native_params=dict(
                        loss_function="YetiRank:mode=Classic;permutations=10;decay=0.85",
                        task_type="CPU", bootstrap_type="No"),
                    permutations=10, decay=.85,
                )
        specs[role] = spec
    return specs


def _predictors(runtime):
    if runtime is not None:
        if isinstance(runtime, dict):
            return runtime["predictors"]
        if isinstance(runtime, (tuple, list)):
            return runtime[5]
        return runtime
    # Import existing source/runtime only; no experiment files are accessed.
    from scripts.research.a2.training import selector_challenge as prior
    for folder in (prior.DEP, prior.TORCH_DEP, prior.RETAINED):
        if str(folder) not in sys.path:
            sys.path.append(str(folder))
    if "runtime_bootstrap" not in sys.modules:
        prior.module("runtime_bootstrap", prior.RETAINED / "runtime_bootstrap.py")
    name = "_v24_algorithm_objective_predictors"
    if name not in sys.modules:
        prior.module(name, prior.RETAINED / "predictors.py")
    return sys.modules[name]


def _input(X, y=None, dates=None, boundary_labels=None):
    x = np.asarray(X, dtype=float)
    if x.ndim != 2 or x.shape[1] != FEATURE_COUNT or not np.isfinite(x).all():
        raise ValueError("OBJECTIVE_FINITE_32_FEATURE_INPUT_REQUIRED")
    if y is None:
        return x
    target = np.asarray(y, dtype=float)
    labels = np.asarray(boundary_labels, dtype=float)
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    if (len(x) == 0 or target.shape != (len(x),) or labels.shape != (len(x),)
            or len(clock) != len(x) or clock.hasnans or not np.isfinite(target).all()
            or not np.isin(labels, (0., 1.)).all()):
        raise ValueError("OBJECTIVE_COMMON_FINITE_TRAIN_INPUT_REQUIRED")
    return x, target, clock, labels


def date_groups(dates):
    """Stable row positions grouped by sorted decision clock."""
    clock = pd.DatetimeIndex(pd.to_datetime(dates))
    if clock.hasnans:
        raise ValueError("GROUP_CLOCK_REQUIRED")
    return [np.flatnonzero(clock == date).astype(np.int64)
            for date in clock.unique().sort_values()]


def pair_plan(dates, seed=SEED):
    """Pair selection never inspects target values and preserves every anchor."""
    if seed != SEED:
        raise ValueError("PAIR_SEED_FROZEN")
    groups = date_groups(dates)
    count = len(dates)
    partners = np.full((count, PAIR_PARTNERS), -1, dtype=np.int64)
    rng = np.random.default_rng(seed)
    for group in groups:
        for anchor in group:
            others = group[group != anchor]
            k = min(PAIR_PARTNERS, len(others))
            if k:
                partners[anchor, :k] = rng.choice(others, k, replace=False)
    return partners


def pair_rows(X, y, partners):
    """Expand fixed partners for the linear pairwise estimator, not new samples."""
    x = np.asarray(X, dtype=float)
    target = np.asarray(y, dtype=float)
    rows, columns = np.nonzero(partners >= 0)
    other = partners[rows, columns]
    signs = np.sign(target[rows] - target[other])
    counts = (partners >= 0).sum(axis=1)
    weights = 1. / counts[rows]
    non_tie = signs != 0
    return (x[rows[non_tie]] - x[other[non_tie]],
            (signs[non_tie] > 0).astype(int), weights[non_tie],
            dict(drawn_pairs=len(rows), tied_pairs=int((~non_tie).sum()),
                 no_partner_rows=int((counts == 0).sum()),
                 training_input_rows=len(x), external_rows_dropped=0))


def pairwise_loss(scores, target, partners, anchors=None):
    """Row-equivalent differentiable pair loss; tie/singleton anchors contribute 0."""
    import torch
    if anchors is None:
        anchors = torch.arange(len(target), device=scores.device)
    selected = torch.as_tensor(partners, dtype=torch.long, device=scores.device)[anchors]
    valid = selected >= 0
    safe = selected.clamp_min(0)
    signs = torch.sign(target[anchors, None] - target[safe])
    losses = torch.nn.functional.softplus(
        -signs.to(scores.dtype) * (scores[anchors, None] - scores[safe]))
    losses = losses * valid * (signs != 0)
    denominator = valid.sum(dim=1).clamp_min(1)
    return (losses.sum(dim=1) / denominator).mean()


def listwise_loss(scores, boundary_labels, groups, total_rows=None):
    """Group mass cross entropy with fixed row-equivalent group weighting."""
    import torch
    total = scores.sum() * 0.
    count = 0
    for group in groups:
        idx = torch.as_tensor(group, dtype=torch.long, device=scores.device)
        label = boundary_labels[idx]
        mass = label.sum()
        if float(mass.detach()) > 0:
            total = total - len(group) * (
                label / mass * torch.log_softmax(scores[idx], dim=0)).sum()
        count += len(group)
    denominator = total_rows if total_rows is not None else count
    if denominator <= 0:
        raise ValueError("LISTWISE_INPUT_ROWS_REQUIRED")
    return total / denominator


def _native_factory(role, pred):
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier, HistGradientBoostingClassifier
    if role in ("BOUNDARY_LOGISTIC", "PAIRWISE_LINEAR"):
        params = pred.hyperparameters("logistic").copy()
        params.pop("convergence_extension_max_iter", None)
        if role == "PAIRWISE_LINEAR":
            params["fit_intercept"] = False
        return LogisticRegression(**params)
    if role == "BOUNDARY_RF":
        return RandomForestClassifier(**pred.TREE_RF)
    if role == "BOUNDARY_EXTRA":
        return ExtraTreesClassifier(**pred.TREE_RF)
    if role == "BOUNDARY_HGB":
        return HistGradientBoostingClassifier(**pred.TREE_HGB)
    if role.startswith("BOUNDARY_XGB") or role == "RANK_XGB_NDCG":
        from xgboost import XGBClassifier, XGBRanker
        return (XGBClassifier(**pred.TREE_XGB, objective="binary:logistic")
                if role.startswith("BOUNDARY") else
                XGBRanker(**pred.TREE_XGB, **role_specs()[role]["native_params"]))
    if role.startswith("BOUNDARY_LGB") or role == "RANK_LGB_XENDCG":
        from lightgbm import LGBMClassifier, LGBMRanker
        return (LGBMClassifier(**pred.TREE_LGB, objective="binary")
                if role.startswith("BOUNDARY") else
                LGBMRanker(**pred.TREE_LGB, **role_specs()[role]["native_params"]))
    if role.startswith("BOUNDARY_CAT") or role == "RANK_CAT_YETIRANK":
        from catboost import CatBoostClassifier, CatBoostRanker
        return (CatBoostClassifier(**pred.TREE_CAT, loss_function="Logloss")
                if role.startswith("BOUNDARY") else
                CatBoostRanker(**pred.TREE_CAT, **role_specs()[role]["native_params"]))
    raise ValueError("NATIVE_OBJECTIVE_ROLE_REQUIRED")


def _verify_capacity(pred):
    for key, name in (("rf", "TREE_RF"), ("hgb", "TREE_HGB"),
                      ("xgb", "TREE_XGB"), ("lgb", "TREE_LGB"),
                      ("cat", "TREE_CAT")):
        if getattr(pred, name) != _CAPACITIES[key]:
            raise ValueError("RETAINED_CAPACITY_CHANGED:" + name)
    linear = pred.hyperparameters("logistic").copy()
    linear.pop("convergence_extension_max_iter", None)
    if linear != _CAPACITIES["logistic"]:
        raise ValueError("RETAINED_LOGISTIC_CAPACITY_CHANGED")


def _version_for(estimator):
    name = type(estimator).__module__.split(".", 1)[0]
    module = importlib.import_module(name)
    return dict(module=name, version=getattr(module, "__version__", None),
                origin=str(getattr(module, "__file__", "")))


@dataclass
class NeuralObjective:
    """Persist only weights and an existing architecture identity, never an alias class."""
    architecture: str
    network: object

    def __getstate__(self):
        return dict(architecture=self.architecture,
                    weights={key: value.detach().cpu() for key, value
                             in self.network.state_dict().items()})

    def __setstate__(self, state):
        pred = _predictors(None)
        self.architecture = state["architecture"]
        self.network = (pred.MLP() if self.architecture == "MLP"
                        else pred.TabularResNet() if self.architecture == "RESNET"
                        else pred.FTTransformer() if self.architecture == "FT"
                        else None)
        if self.network is None:
            raise ValueError("PERSISTED_ARCHITECTURE_NOT_FROZEN")
        self.network.load_state_dict(state["weights"], strict=True)
        self.network.eval()

    def eval(self):
        self.network.eval()
        return self

    def __call__(self, x):
        return self.network(x)


@dataclass
class FittedObjective:
    role: str
    estimator: object
    metadata: dict
    neural: bool = False


def _group_batches(groups, order):
    current, rows = [], 0
    for position in order:
        group = groups[int(position)]
        if current and rows + len(group) > 512:
            yield current
            current, rows = [], 0
        current.append(group)
        rows += len(group)
    if current:
        yield current


def _fit_neural(role, x, y, dates, boundary, pred, on_fit_call=None):
    import torch
    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)
    family = role.split("_")[1]
    network = (pred.MLP() if family == "MLP" else pred.TabularResNet()
               if family == "RESNET" else pred.FTTransformer())
    xx = torch.tensor(np.clip(x, -8., 8.), dtype=torch.float32)
    labels = torch.tensor(boundary, dtype=torch.float32)
    target = torch.tensor(y, dtype=torch.float64)
    groups = date_groups(dates)
    partner = pair_plan(dates) if role.startswith("PAIRWISE") else None
    optimizer = torch.optim.Adam(network.parameters(), lr=.001, weight_decay=.0001)
    generator = torch.Generator().manual_seed(SEED)
    metadata = dict(epochs=10, updates=0, epoch_losses=[],
                    listwise_zero_positive_groups=int(sum(boundary[g].sum() == 0 for g in groups)),
                    singleton_group_rows=sum(len(g) for g in groups if len(g) == 1))
    if partner is not None:
        anchors, columns = np.nonzero(partner >= 0)
        others = partner[anchors, columns]
        metadata.update(drawn_pairs=len(anchors),
                        tied_pairs=int((y[anchors] == y[others]).sum()),
                        no_partner_rows=int(((partner >= 0).sum(1) == 0).sum()),
                        training_input_rows=len(x), external_rows_dropped=0)
    network.train()
    if on_fit_call is not None:
        on_fit_call(dict(operation="estimator_fit", role=role))
    for _ in range(10):
        total, rows = 0., 0
        if role.startswith("LISTWISE"):
            order = torch.randperm(len(groups), generator=generator).numpy()
            batches = _group_batches(groups, order)
        else:
            order = torch.randperm(len(xx), generator=generator)
            batches = [order[first:first+512] for first in range(0, len(xx), 512)]
        for batch in batches:
            optimizer.zero_grad()
            if role.startswith("LISTWISE"):
                selected = np.concatenate(batch)
                values = network(xx[selected])[:, 0]
                local_groups, start = [], 0
                for group in batch:
                    local_groups.append(np.arange(start, start+len(group)))
                    start += len(group)
                loss = listwise_loss(values, labels[selected], local_groups)
                batch_count = len(selected)
            elif role.startswith("PAIRWISE"):
                anchors = batch.numpy()
                plan = partner[anchors]
                counts = (plan >= 0).sum(axis=1)
                left = network(xx[anchors])[:, 0]
                right = network(xx[plan.clip(min=0).reshape(-1)])[:, 0].reshape(-1, PAIR_PARTNERS)
                signs = torch.sign(target[anchors, None] - target[plan.clip(min=0)])
                valid = torch.tensor(plan >= 0)
                losses = torch.nn.functional.softplus(
                    -signs.to(left.dtype) * (left[:, None] - right))
                loss = ((losses * valid * (signs != 0)).sum(1)
                        / torch.tensor(counts.clip(min=1))).mean()
                batch_count = len(anchors)
            else:
                values = network(xx[batch])[:, 0]
                loss = torch.nn.functional.binary_cross_entropy_with_logits(values, labels[batch])
                batch_count = len(batch)
            if not torch.isfinite(loss):
                raise RuntimeError("NONFINITE_FIXED_NEURAL_OBJECTIVE")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 5.)
            optimizer.step()
            total += float(loss.detach()) * batch_count
            rows += batch_count
            metadata["updates"] += 1
        metadata["epoch_losses"].append(total / rows)
    network.eval()
    metadata["backend"] = dict(module="torch", version=torch.__version__,
                               origin=str(torch.__file__))
    return NeuralObjective(family, network), metadata


def fit(role, X, y, dates, boundary_labels, runtime=None, on_fit_call=None):
    """Exactly one estimator fit, on runner-scaled common sampled input rows."""
    if role not in ROLE_IDS:
        raise ValueError("UNKNOWN_FROZEN_OBJECTIVE_ROLE:" + str(role))
    x, target, clock, boundary = _input(X, y, dates, boundary_labels)
    pred = _predictors(runtime)
    _verify_capacity(pred)
    neural = role in ("BOUNDARY_MLP", "PAIRWISE_MLP", "PAIRWISE_RESNET", "PAIRWISE_FT",
                      "LISTWISE_MLP", "LISTWISE_RESNET", "LISTWISE_FT")
    metadata = dict(spec=role_specs()[role], estimator_fit_calls=1, scaler_fit_calls=0,
                    target_stat_estimation=0, scientific_retries=0, training_rows=len(x))
    if role.startswith("BOUNDARY") and len(np.unique(boundary)) != 2:
        raise ValueError("BOUNDARY_REQUIRES_BOTH_CLASSES_NO_REBALANCE")
    if neural:
        estimator, extra = _fit_neural(role, x, target, clock, boundary, pred, on_fit_call=on_fit_call)
        metadata.update(extra)
    else:
        estimator = _native_factory(role, pred)
        fit_x, fit_y, kwargs = x, boundary, {}
        if role == "PAIRWISE_LINEAR":
            fit_x, fit_y, pair_weight, extra = pair_rows(x, target, pair_plan(clock))
            metadata.update(extra)
            if len(fit_y) == 0 or len(np.unique(fit_y)) != 2:
                raise ValueError("PAIRWISE_REQUIRES_NON_TIED_BOTH_CLASS_PAIRS")
            kwargs["sample_weight"] = pair_weight
        elif role.startswith("RANK"):
            fit_x, fit_y, sizes = pred.rank_training_data(x, target, clock)
            if role == "RANK_CAT_YETIRANK":
                kwargs["group_id"] = np.repeat(np.arange(len(sizes)), sizes)
            else:
                kwargs["group"] = sizes
                if role == "RANK_LGB_XENDCG":
                    kwargs["eval_at"] = [20]
            metadata.update(groups=len(sizes), relevance_bins=5,
                            relevance_gain=role_specs()[role]["gain"])
        from threadpoolctl import threadpool_limits
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with threadpool_limits(limits=2):
                if on_fit_call is not None:
                    on_fit_call(dict(operation="estimator_fit", role=role))
                estimator.fit(fit_x, fit_y, **kwargs)
        metadata["warnings"] = [dict(category=type(w.message).__name__, message=str(w.message))
                                for w in caught]
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            raise RuntimeError("UNRESOLVED_CONVERGENCE_NO_RETRY")
        metadata["backend"] = _version_for(estimator)
    return FittedObjective(role, estimator, metadata, neural)


def predict(fitted, X):
    """Frozen native probability/logit/rank score, with no alternative scoring."""
    x = _input(X)
    if not isinstance(fitted, FittedObjective) or fitted.role not in ROLE_IDS:
        raise ValueError("FROZEN_OBJECTIVE_FIT_REQUIRED")
    if not len(x):
        return np.empty(0, dtype=float)
    if fitted.neural:
        import torch
        chunks = []
        fitted.estimator.eval()
        with torch.inference_mode():
            for first in range(0, len(x), 1024):
                xx = torch.tensor(np.clip(x[first:first+1024], -8., 8.), dtype=torch.float32)
                score = fitted.estimator(xx)[:, 0]
                if fitted.role.startswith("BOUNDARY"):
                    score = torch.sigmoid(score)
                chunks.append(score.numpy())
        score = np.concatenate(chunks).astype(float)
    else:
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=2):
            if fitted.role.startswith("BOUNDARY"):
                score = np.asarray(fitted.estimator.predict_proba(x)[:, 1], float)
            elif fitted.role == "PAIRWISE_LINEAR":
                score = np.asarray(fitted.estimator.decision_function(x), float)
            else:
                score = np.asarray(fitted.estimator.predict(x), float)
    if score.shape != (len(x),) or not np.isfinite(score).all():
        raise ValueError("OBJECTIVE_NONFINITE_OR_SHAPE_PREDICTION")
    if fitted.role.startswith("BOUNDARY") and ((score < 0).any() or (score > 1).any()):
        raise ValueError("BOUNDARY_PROBABILITY_OUT_OF_RANGE")
    return score
