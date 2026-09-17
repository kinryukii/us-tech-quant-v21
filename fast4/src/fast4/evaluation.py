from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error, mean_squared_error


def spearman(y: pd.Series, score: pd.Series) -> float:
    return float(pd.Series(score).corr(pd.Series(y), method="spearman")) if pd.Series(score).nunique() > 1 else np.nan


def stable_bucket(frame: pd.DataFrame, score: str, count: int = 10) -> pd.Series:
    ordered = frame.sort_values([score, "decision_timestamp_utc", "candidate_id"], kind="mergesort")
    values = np.minimum(np.floor(np.arange(len(ordered)) * count / max(len(ordered), 1)).astype(int) + 1, count)
    result = pd.Series(index=ordered.index, data=values)
    return result.reindex(frame.index)


def profit_factor(values: pd.Series) -> float:
    gains, losses = values[values > 0].sum(), -values[values < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf") if gains > 0 else np.nan


def tail_mean(values: pd.Series, fraction: float) -> float:
    ordered = values.dropna().sort_values(kind="mergesort")
    n = max(1, int(np.ceil(fraction * len(ordered))))
    return float(ordered.iloc[:n].mean()) if len(ordered) else np.nan


def group_metrics(values: pd.Series) -> dict[str, Any]:
    x = values.dropna().astype(float)
    return {
        "count": len(x), "mean": float(x.mean()), "median": float(x.median()),
        "positive_rate": float(x.gt(0).mean()), "profit_factor": profit_factor(x),
        "q10": float(x.quantile(.10)), "q05": float(x.quantile(.05)),
        "worst_1pct": tail_mean(x, .01), "cvar_10pct": tail_mean(x, .10),
        "std": float(x.std(ddof=1)),
    }


def economic_metrics(frame: pd.DataFrame, score: str) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    data = frame.loc[frame[score].notna() & frame.primary_target.notna()].copy()
    data["decile"] = stable_bucket(data, score, 10)
    deciles = []
    for decile, part in data.groupby("decile", sort=True):
        deciles.append({"decile": f"Q{decile}", **group_metrics(part.primary_target)})
    table = pd.DataFrame(deciles)
    q1 = table.loc[table.decile.eq("Q1")].iloc[0]
    q10 = table.loc[table.decile.eq("Q10")].iloc[0]
    global_metrics = {
        "row_count": len(data), "spearman": spearman(data.primary_target, data[score]),
        "pearson": float(data.primary_target.corr(data[score])),
        "rmse": float(mean_squared_error(data.primary_target, data[score]) ** .5),
        "mae": float(mean_absolute_error(data.primary_target, data[score])),
        "q10_minus_q1_mean": float(q10["mean"] - q1["mean"]),
        "q10_minus_q1_median": float(q10["median"] - q1["median"]),
        "q10_profit_factor": float(q10["profit_factor"]),
        "q10_tail_q10": float(q10["q10"]), "q10_cvar": float(q10["cvar_10pct"]),
    }
    top = {}
    ordered = data.sort_values([score, "decision_timestamp_utc", "candidate_id"], ascending=[False, True, True], kind="mergesort")
    for fraction in (.05, .10, .20, .30):
        n = max(1, int(np.ceil(fraction * len(ordered))))
        top[f"top_{int(fraction * 100)}pct"] = group_metrics(ordered.head(n).primary_target)
    return global_metrics, table, top


def composite_objective(frame: pd.DataFrame, prediction: np.ndarray) -> float:
    data = frame[["candidate_id", "decision_timestamp_utc", "primary_target"]].copy()
    data["prediction"] = prediction
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 25 or data.prediction.nunique() < 2:
        return -1e9
    std = float(data.primary_target.std(ddof=1))
    if not np.isfinite(std) or std <= 0:
        return -1e9
    data["quintile"] = stable_bucket(data, "prediction", 5)
    low = data.loc[data.quintile.eq(1), "primary_target"]
    high = data.loc[data.quintile.eq(5), "primary_target"]
    rank = spearman(data.primary_target, data.prediction)
    spread = (high.mean() - low.mean()) / std
    top_mean = high.mean() / std
    top_median = high.median() / std
    tail_penalty = max(0.0, -(high.quantile(.05) - data.primary_target.quantile(.05)) / std)
    return float(np.nan_to_num(rank, nan=-1.0) + .25 * spread + .10 * top_mean + .10 * top_median - .10 * tail_penalty)


def probability_metrics(frame: pd.DataFrame, probability: str, label: str) -> dict[str, Any]:
    data = frame[[probability, label]].dropna()
    p = data[probability].clip(1e-8, 1 - 1e-8)
    return {
        "row_count": len(data), "base_rate": float(data[label].mean()),
        "brier": float(brier_score_loss(data[label], p)),
        "logloss": float(log_loss(data[label], p, labels=[0, 1])),
    }


def slice_metrics(frame: pd.DataFrame, score: str, slice_column: str) -> pd.DataFrame:
    rows = []
    for value, part in frame.groupby(slice_column, dropna=False, sort=True):
        if len(part) < 10:
            rows.append({"slice_type": slice_column, "slice": str(value), "N": len(part), "status": "LOW_SAMPLE"})
            continue
        part = part.copy()
        part["decile"] = stable_bucket(part, score, 10)
        top = part.loc[part.decile.eq(10), "primary_target"]
        low = part.loc[part.decile.eq(1), "primary_target"]
        rows.append({
            "slice_type": slice_column, "slice": str(value), "N": len(part),
            "spearman": spearman(part.primary_target, part[score]),
            "q10_minus_q1": float(top.mean() - low.mean()), "top_decile_mean": float(top.mean()),
            "top_decile_median": float(top.median()), "win_rate": float(top.gt(0).mean()),
            "profit_factor": profit_factor(top), "q10": float(top.quantile(.10)), "status": "EVALUATED",
        })
    return pd.DataFrame(rows)


def stability_status(table: pd.DataFrame, slice_type: str) -> str:
    data = table.loc[(table.slice_type.eq(slice_type)) & table.status.eq("EVALUATED")]
    if data.empty:
        return "INSUFFICIENT_SAMPLE"
    positive = int((data.spearman > 0).sum())
    return "PASS_MAJORITY_POSITIVE" if positive > len(data) / 2 else "MIXED" if positive else "FAIL_ALL_NONPOSITIVE"
