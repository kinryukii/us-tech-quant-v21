from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import (average_precision_score, brier_score_loss, log_loss,
                             mean_absolute_error, mean_squared_error, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .evaluation import profit_factor, spearman, stable_bucket, tail_mean


def group_metrics(values: pd.Series, total: int | None = None) -> dict[str, Any]:
    x = pd.Series(values).dropna().astype(float)
    denominator = len(x) if total is None else total
    return {
        "N": int(len(x)), "coverage": float(len(x) / denominator) if denominator else 0.0,
        "mean": float(x.mean()) if len(x) else np.nan,
        "median": float(x.median()) if len(x) else np.nan,
        "win_rate": float(x.gt(0).mean()) if len(x) else np.nan,
        "profit_factor": profit_factor(x),
        "std": float(x.std(ddof=1)) if len(x) > 1 else np.nan,
        "q25": float(x.quantile(.25)) if len(x) else np.nan,
        "q10": float(x.quantile(.10)) if len(x) else np.nan,
        "q05": float(x.quantile(.05)) if len(x) else np.nan,
        "worst_1pct": tail_mean(x, .01), "cvar": tail_mean(x, .10),
    }


def economic_score_metrics(frame: pd.DataFrame, score: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    data = frame.loc[frame[score].notna() & frame.primary_target.notna()].copy()
    if len(data) < 20 or data[score].nunique() < 2:
        return {"OOF_N": len(data), "spearman": np.nan}, [], {}
    data["decile"] = stable_bucket(data, score, 10)
    deciles = []
    for bucket, part in data.groupby("decile", sort=True):
        deciles.append({"decile": f"Q{bucket}", **group_metrics(part.primary_target, len(data))})
    q1, q10 = deciles[0], deciles[-1]
    global_metrics = {
        "OOF_N": int(len(data)), "spearman": spearman(data.primary_target, data[score]),
        "pearson": float(data.primary_target.corr(data[score])),
        "rmse": float(mean_squared_error(data.primary_target, data[score]) ** .5),
        "mae": float(mean_absolute_error(data.primary_target, data[score])),
        "q10_q1_mean": float(q10["mean"] - q1["mean"]),
        "q10_q1_median": float(q10["median"] - q1["median"]),
    }
    ordered = data.sort_values([score, "decision_timestamp_utc", "candidate_id"],
                               ascending=[False, True, True], kind="mergesort")
    top: dict[str, dict[str, Any]] = {}
    for fraction in (.30, .20, .10, .05):
        n = max(1, int(np.ceil(fraction * len(ordered))))
        top[f"TOP{int(fraction * 100)}"] = group_metrics(ordered.head(n).primary_target, len(ordered))
    return global_metrics, deciles, top


def inner_economic_objective(frame: pd.DataFrame, prediction: np.ndarray) -> float:
    data = frame[["candidate_id", "decision_timestamp_utc", "primary_target"]].copy()
    data["score"] = np.asarray(prediction, dtype=float)
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 25 or data.score.nunique() < 3:
        return -1e9
    scale = float(data.primary_target.std(ddof=1))
    if not np.isfinite(scale) or scale <= 0:
        return -1e9
    data["quintile"] = stable_bucket(data, "score", 5)
    means = data.groupby("quintile", sort=True).primary_target.mean()
    low, top = data.loc[data.quintile.eq(1), "primary_target"], data.loc[data.quintile.eq(5), "primary_target"]
    rank = np.nan_to_num(spearman(data.primary_target, data.score), nan=-1.0)
    spread = float((top.mean() - low.mean()) / scale)
    top_mean, top_median = float(top.mean() / scale), float(top.median() / scale)
    monotonicity = np.nan_to_num(spearman(pd.Series(np.arange(1, 6)), means.reset_index(drop=True)), nan=-1.0)
    tail_penalty = max(0.0, float((data.primary_target.quantile(.10) - top.quantile(.10)) / scale))
    return float(rank + .30 * spread + .15 * top_mean + .10 * top_median + .10 * monotonicity - .15 * tail_penalty)


def probability_metrics(frame: pd.DataFrame, probability: str, label: str) -> dict[str, Any]:
    data = frame[[probability, label]].dropna()
    if data.empty or data[label].nunique() < 2:
        return {"N": len(data), "status": "INSUFFICIENT_CLASSES"}
    p = data[probability].clip(1e-8, 1 - 1e-8)
    return {
        "N": int(len(data)), "base_rate": float(data[label].mean()),
        "auroc": float(roc_auc_score(data[label], p)),
        "pr_auc": float(average_precision_score(data[label], p)),
        "brier": float(brier_score_loss(data[label], p)),
        "log_loss": float(log_loss(data[label], p, labels=[0, 1])),
        "calibration_by_decile": [
            {"bucket": int(bucket), "N": int(len(part)), "mean_probability": float(part[probability].mean()),
             "event_rate": float(part[label].mean())}
            for bucket, part in data.assign(bucket=stable_bucket(data.assign(
                candidate_id=np.arange(len(data)).astype(str), decision_timestamp_utc=pd.Timestamp("2000-01-01", tz="UTC")), probability, 10)).groupby("bucket")
        ],
    }


def _fit_ridge(x: pd.DataFrame, y: pd.Series, alpha: float) -> Pipeline:
    model = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=alpha))])
    model.fit(x, y)
    return model


def crossfit_ridge_stack(inner_base: pd.DataFrame, outer_base: pd.DataFrame, target: pd.Series,
                         fold_labels: pd.Series) -> tuple[pd.Series, np.ndarray, dict[str, Any], Pipeline]:
    columns = list(inner_base.columns)
    valid = inner_base.notna().all(axis=1) & target.notna() & fold_labels.notna()
    labels = sorted(fold_labels.loc[valid].unique())
    candidates = (1.0, 10.0, 100.0, 1000.0)
    results: list[tuple[float, float, pd.Series]] = []
    for alpha in candidates:
        prediction = pd.Series(np.nan, index=inner_base.index, dtype=float)
        for position in range(1, len(labels)):
            train_labels, valid_label = set(labels[:position]), labels[position]
            train = valid & fold_labels.isin(train_labels)
            holdout = valid & fold_labels.eq(valid_label)
            if train.sum() < 25 or holdout.sum() < 5:
                continue
            model = _fit_ridge(inner_base.loc[train, columns], target.loc[train], alpha)
            prediction.loc[holdout] = model.predict(inner_base.loc[holdout, columns])
        objective = inner_economic_objective(pd.DataFrame({
            "candidate_id": inner_base.index.astype(str),
            "decision_timestamp_utc": pd.Timestamp("2000-01-01", tz="UTC"),
            "primary_target": target,
        }).loc[prediction.notna()], prediction.loc[prediction.notna()].to_numpy())
        results.append((objective, alpha, prediction))
    objective, alpha, crossfit = max(results, key=lambda row: (row[0], -row[1]))
    final = _fit_ridge(inner_base.loc[valid, columns], target.loc[valid], alpha)
    outer_prediction = final.predict(outer_base[columns])
    return crossfit, np.asarray(outer_prediction, dtype=float), {"alpha": alpha, "inner_objective": objective,
                                                                 "crossfit_row_count": int(crossfit.notna().sum())}, final


def _zfit(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    mean = frame.mean()
    scale = frame.std(ddof=1).replace(0, 1).fillna(1)
    return mean, scale


def risk_adjusted_score(inner_base: pd.DataFrame, outer_base: pd.DataFrame, target: pd.Series) -> tuple[pd.Series, np.ndarray, dict[str, Any]]:
    components = pd.DataFrame(index=inner_base.index)
    outer_components = pd.DataFrame(index=outer_base.index)
    definitions = {
        "expected": ["lgb_huber_pooled", "xgb_pseudohuber_pooled", "cat_huber_pooled"],
        "q10": ["lgb_q10_pooled", "xgb_q10_pooled", "cat_q10_pooled"],
        "safe": ["lgb_severe_pooled", "xgb_severe_pooled", "cat_severe_pooled"],
        "positive": ["lgb_positive_pooled", "xgb_positive_pooled", "cat_positive_pooled"],
    }
    for name, columns in definitions.items():
        components[name] = inner_base[columns].mean(axis=1)
        outer_components[name] = outer_base[columns].mean(axis=1)
    valid = components.notna().all(axis=1) & target.notna()
    mean, scale = _zfit(components.loc[valid])
    zinner, zouter = (components - mean) / scale, (outer_components - mean) / scale
    candidates = []
    for lower_tail in (0.0, .25, .5, 1.0):
        for severe in (0.0, .25, .5, 1.0):
            for positive in (0.0, .25, .5):
                score = zinner.expected + lower_tail * zinner.q10 + severe * zinner.safe + positive * zinner.positive
                data = pd.DataFrame({"candidate_id": score.index.astype(str),
                                     "decision_timestamp_utc": pd.Timestamp("2000-01-01", tz="UTC"),
                                     "primary_target": target})
                objective = inner_economic_objective(data.loc[valid], score.loc[valid].to_numpy())
                candidates.append((objective, lower_tail, severe, positive, score))
    objective, lower_tail, severe, positive, score = max(candidates, key=lambda row: row[0])
    outer = zouter.expected + lower_tail * zouter.q10 + severe * zouter.safe + positive * zouter.positive
    return score, outer.to_numpy(), {"lower_tail_weight": lower_tail, "severe_loss_weight": severe,
                                     "positive_probability_weight": positive, "inner_objective": objective,
                                     "component_mean": mean.to_dict(), "component_scale": scale.to_dict()}


def normalized_mean_score(inner_base: pd.DataFrame, outer_base: pd.DataFrame, columns: list[str]) -> tuple[pd.Series, np.ndarray]:
    valid = inner_base[columns].notna().all(axis=1)
    mean, scale = _zfit(inner_base.loc[valid, columns])
    return ((inner_base[columns] - mean) / scale).mean(axis=1), (((outer_base[columns] - mean) / scale).mean(axis=1)).to_numpy()


def choose_abstention(inner_frame: pd.DataFrame, score: pd.Series, fold_labels: pd.Series,
                      outer_score: np.ndarray, coverages: list[float]) -> tuple[np.ndarray, dict[str, Any]]:
    valid = score.notna() & inner_frame.primary_target.notna() & fold_labels.notna()
    candidates = []
    scale = float(inner_frame.loc[valid, "primary_target"].std(ddof=1))
    for coverage in coverages:
        threshold = float(score.loc[valid].quantile(1 - coverage))
        selected = valid & score.ge(threshold)
        supported_folds = int(fold_labels.loc[selected].value_counts().ge(3).sum())
        if selected.sum() < max(20, int(np.ceil(.08 * valid.sum()))) or supported_folds < 2:
            objective = -1e9
        else:
            values = inner_frame.loc[selected, "primary_target"]
            pf = profit_factor(values)
            pf_term = np.log(max(float(pf), 1e-6)) if np.isfinite(pf) else 2.0
            tail_penalty = max(0.0, float(-values.quantile(.10) / scale))
            fold_means = inner_frame.loc[selected].assign(_fold=fold_labels.loc[selected]).groupby("_fold").primary_target.mean()
            objective = float(values.mean() / scale + .25 * values.median() / scale + .10 * pf_term
                              - .15 * tail_penalty - .20 * fold_means.std(ddof=0) / scale)
        candidates.append((objective, coverage, threshold, int(selected.sum()), supported_folds))
    objective, coverage, threshold, selected_count, supported_folds = max(candidates, key=lambda row: (row[0], row[3]))
    selection = np.asarray(outer_score >= threshold, dtype=bool)
    return selection, {"policy": "TRADE_IF_NESTED_SCORE_GE_INNER_FROZEN_QUANTILE_THRESHOLD",
                       "coverage_semantics": coverage, "absolute_threshold": threshold,
                       "inner_selected_count": selected_count, "inner_supported_fold_count": supported_folds,
                       "inner_selection_objective": objective, "candidate_coverages": list(coverages)}


def stability_table(frame: pd.DataFrame, score: str, selected: str) -> pd.DataFrame:
    data = frame.copy()
    data["year"] = pd.to_datetime(data.decision_timestamp_utc, utc=True).dt.year.astype(str)
    minutes = data.get("minutes_since_rth_open", pd.Series(np.nan, index=data.index))
    data["time_of_day"] = pd.cut(minutes, [-np.inf, 60, 180, 300, np.inf], labels=["OPEN", "MID_AM", "MID_PM", "CLOSE"])
    vix = data.get("vix_percentile_252d", pd.Series(np.nan, index=data.index))
    data["volatility_regime"] = pd.cut(vix, [-np.inf, .33, .67, np.inf], labels=["LOW", "MID", "HIGH"])
    rows = []
    for column in ("year", "validation_slice", "head", "underlying_symbol", "volatility_regime", "time_of_day"):
        for value, part in data.groupby(column, observed=True, dropna=False, sort=True):
            selected_part = part.loc[part[selected].fillna(False)]
            rows.append({"slice_type": column, "slice": str(value), "N": int(len(part)),
                         "spearman": spearman(part.primary_target, part[score]) if len(part) >= 10 else np.nan,
                         "mean": float(part.primary_target.mean()), "median": float(part.primary_target.median()),
                         "top20_mean": float(part.nlargest(max(1, int(np.ceil(.2 * len(part)))), score).primary_target.mean()) if len(part) else np.nan,
                         "top10_mean": float(part.nlargest(max(1, int(np.ceil(.1 * len(part)))), score).primary_target.mean()) if len(part) else np.nan,
                         "profit_factor": profit_factor(part.primary_target),
                         "selected_N": int(len(selected_part)), "selected_mean": float(selected_part.primary_target.mean()) if len(selected_part) else np.nan,
                         "selected_median": float(selected_part.primary_target.median()) if len(selected_part) else np.nan,
                         "selected_profit_factor": profit_factor(selected_part.primary_target)})
    return pd.DataFrame(rows)


def status_from_slices(table: pd.DataFrame, slice_type: str, metric: str = "spearman") -> str:
    rows = table.loc[(table.slice_type == slice_type) & table[metric].notna()]
    if len(rows) < 2:
        return "INSUFFICIENT_SUPPORT"
    positive = int(rows[metric].gt(0).sum())
    return "PASS_MAJORITY_POSITIVE" if positive > len(rows) / 2 else "MIXED" if positive else "FAIL_ALL_NONPOSITIVE"


def blockwise_permutation_test(frame: pd.DataFrame, score: str, block: str, count: int, seed: int) -> dict[str, Any]:
    observed = spearman(frame.primary_target, frame[score])
    rng = np.random.default_rng(seed)
    null = np.empty(count, dtype=float)
    groups = [indices.to_numpy() for _, indices in frame.groupby(block, sort=True).groups.items()]
    original = frame.primary_target.to_numpy(copy=True)
    for number in range(count):
        permuted = original.copy()
        for positions in groups:
            permuted[positions] = rng.permutation(original[positions])
        null[number] = spearman(pd.Series(permuted), frame[score].reset_index(drop=True))
    p = float((1 + np.sum(null >= observed)) / (count + 1))
    return {"statistic": "GENUINE_NESTED_OOF_SPEARMAN_BLOCKWISE_TARGET_PERMUTATION", "count": count,
            "seed": seed, "observed": observed, "empirical_p_one_sided": p,
            "null_mean": float(np.mean(null)), "null_std": float(np.std(null, ddof=1)),
            "null_q95": float(np.quantile(null, .95)), "null_q99": float(np.quantile(null, .99))}
