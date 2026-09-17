from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd


RUN_ID = "A2_ALGORITHM_BENCHMARK_R1C_REGIME_FORENSIC_AND_RANKING_REPAIR"
REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R1A_ROOT = RESULTS_ROOT / "A2_ALGORITHM_BENCHMARK_R1A_TEMPORAL_BASELINE_RECONSTRUCTION"
R1B_ROOT = RESULTS_ROOT / "A2_ALGORITHM_BENCHMARK_R1B_XGB_STABILITY_FORENSIC"
OUT_ROOT = RESULTS_ROOT / RUN_ID
WORK_ROOT = RESULTS_ROOT / f"{RUN_ID}__WORKING"
RESEARCH_DATASET = Path(
    r"D:\us-tech-quant-cache\a2_model_family_r1a_data_complete\research_dataset.parquet"
)
SCRIPT_PATH = REPO_ROOT / "scripts" / "v22" / Path(__file__).name
PRE2026_END = pd.Timestamp("2026-01-01")

A2 = "M0_A2_HGB_AUTH_TEMPORAL"
XGB = "M2_XGB_REG"
COMPETITIVE_MODELS = [A2, "M1_RIDGE", XGB, "M3_XGB_RANK"]

METRIC_CONTRACT = [
    ("rank_ic", "PREDICTIVE", "HIGH", "cross-model percentile rank", 1 / 9),
    ("ic_consistency", "PREDICTIVE", "HIGH", "cross-model percentile rank", 1 / 9),
    ("ndcg_at_20", "PREDICTIVE", "HIGH", "cross-model percentile rank", 1 / 9),
    ("sharpe", "ECONOMIC", "HIGH", "cross-model percentile rank", 1 / 12),
    ("calmar", "ECONOMIC", "HIGH", "cross-model percentile rank", 1 / 12),
    ("cagr", "ECONOMIC", "HIGH", "cross-model percentile rank", 1 / 12),
    ("max_drawdown", "ECONOMIC", "HIGH", "cross-model percentile rank", 1 / 12),
    ("fold_sharpe_dispersion", "ROBUSTNESS", "LOW", "cross-model percentile rank", 1 / 12),
    ("fold_ic_dispersion", "ROBUSTNESS", "LOW", "cross-model percentile rank", 1 / 12),
    ("turnover", "ROBUSTNESS", "LOW", "cross-model percentile rank", 1 / 12),
    ("fold_return_concentration", "ROBUSTNESS", "LOW", "cross-model percentile rank", 1 / 12),
]

WEIGHT_SCENARIOS = {
    "BALANCED": {"PREDICTIVE": 1 / 3, "ECONOMIC": 1 / 3, "ROBUSTNESS": 1 / 3},
    "PREDICTIVE_TILT": {"PREDICTIVE": 0.50, "ECONOMIC": 0.25, "ROBUSTNESS": 0.25},
    "ECONOMIC_TILT": {"PREDICTIVE": 0.25, "ECONOMIC": 0.50, "ROBUSTNESS": 0.25},
    "ROBUSTNESS_TILT": {"PREDICTIVE": 0.25, "ECONOMIC": 0.25, "ROBUSTNESS": 0.50},
}

CORE_REGIME_VARIABLES = [
    "market_realized_vol_20d",
    "market_trend_60d",
    "market_drawdown_state",
    "cross_sectional_return_dispersion",
    "breadth_20d_positive",
    "cross_sectional_feature_dispersion",
]

TERCILE_VARIABLES = CORE_REGIME_VARIABLES + [
    "eligible_universe_count",
    "xgb_top20_score_dispersion",
    "xgb_a2_score_correlation",
    "top20_overlap",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def artifact_hashes(root: Path) -> dict[str, str]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return {str(Path(row["path"])): row["sha256"] for row in manifest["artifacts"]}


def verify_frozen_file(path: Path, expected: str, audit: list[dict[str, Any]]) -> None:
    actual = sha256(path)
    audit.append(
        {"path": str(path), "expected_sha256": expected, "actual_sha256": actual, "match": actual == expected}
    )
    if actual != expected:
        raise RuntimeError(f"Frozen input hash mismatch: {path}")


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    r1a_hashes = artifact_hashes(R1A_ROOT)
    r1b_hashes = artifact_hashes(R1B_ROOT)
    audit: list[dict[str, Any]] = []
    r1a_names = [
        "status.json",
        "a2_temporal_lineage.json",
        "model_artifact_manifest.json",
        "predictive_metrics_by_model.csv",
        "predictive_metrics_by_fold.csv",
        "economic_metrics_by_model.csv",
        "economic_metrics_by_fold.csv",
        "oos_predictions.parquet",
        "oof_portfolio_paths.parquet",
        "universe_coverage_by_date.csv",
    ]
    r1b_names = ["status.json", "date_level_attribution.csv"]
    for name in r1a_names:
        path = R1A_ROOT / name
        verify_frozen_file(path, r1a_hashes[str(path)], audit)
    for name in r1b_names:
        path = R1B_ROOT / name
        verify_frozen_file(path, r1b_hashes[str(path)], audit)

    r1a_status = json.loads((R1A_ROOT / "status.json").read_text(encoding="utf-8"))
    r1b_status = json.loads((R1B_ROOT / "status.json").read_text(encoding="utf-8"))
    lineage = json.loads((R1A_ROOT / "a2_temporal_lineage.json").read_text(encoding="utf-8"))
    if r1a_status["A2_ALGORITHM_BENCHMARK_R1A_STATUS"] != "PASS_PRE2026_TEMPORAL_ALGORITHM_BENCHMARK_COMPLETE":
        raise RuntimeError("Unexpected R1A status")
    if r1b_status["A2_ALGORITHM_BENCHMARK_R1B_STATUS"] != (
        "STOP_FAIL_CLOSED_R1A_MODEL_RANKING_LOGIC_DEFECT_AFTER_FORENSIC_COMPLETE"
    ):
        raise RuntimeError("Unexpected R1B status")
    for status in (r1a_status, r1b_status):
        for key in ("2026_TRAINING_ROWS", "2026_PARAMETER_SEARCH_COUNT", "2026_MODEL_SELECTION_COUNT"):
            if status[key] != 0:
                raise RuntimeError(f"Sealed-holdout contract failed: {key}")
    dataset_expected = lineage["source_hashes"][str(RESEARCH_DATASET)]
    verify_frozen_file(RESEARCH_DATASET, dataset_expected, audit)
    return r1a_status, r1b_status, lineage, audit


def build_symmetric_ranking() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str
]:
    pred = pd.read_csv(R1A_ROOT / "predictive_metrics_by_model.csv").set_index("model")
    pred_fold = pd.read_csv(R1A_ROOT / "predictive_metrics_by_fold.csv")
    econ = pd.read_csv(R1A_ROOT / "economic_metrics_by_model.csv").set_index("model")
    econ_fold = pd.read_csv(R1A_ROOT / "economic_metrics_by_fold.csv")
    pred_fold = pred_fold[pred_fold["scope"].str.startswith("OUTER_")]
    econ_fold = econ_fold[econ_fold["scope"].str.startswith("OUTER_")]

    rows = []
    for model in COMPETITIVE_MODELS:
        pf = pred_fold[pred_fold["model"] == model]
        ef = econ_fold[econ_fold["model"] == model]
        if len(pf) != 3 or len(ef) != 3:
            raise RuntimeError(f"Expected three folds for {model}")
        fold_ic_dispersion = float(pf["rank_ic"].std(ddof=0))
        absolute_fold_returns = ef["total_return"].abs()
        rows.append(
            {
                "model": model,
                "rank_ic": pred.at[model, "rank_ic"],
                "ic_consistency": pred.at[model, "rank_ic"] / (fold_ic_dispersion + 1e-12),
                "ndcg_at_20": pred.at[model, "ndcg_at_20"],
                "sharpe": econ.at[model, "sharpe"],
                "calmar": econ.at[model, "calmar"],
                "cagr": econ.at[model, "cagr"],
                "max_drawdown": econ.at[model, "max_drawdown"],
                "fold_sharpe_dispersion": ef["sharpe"].std(ddof=0),
                "fold_ic_dispersion": fold_ic_dispersion,
                "turnover": econ.at[model, "turnover"],
                "fold_return_concentration": absolute_fold_returns.max() / absolute_fold_returns.sum(),
            }
        )
    raw = pd.DataFrame(rows).set_index("model")
    contract = pd.DataFrame(
        METRIC_CONTRACT,
        columns=["metric", "category", "direction", "normalization", "balanced_weight"],
    )
    contract["category_weight"] = 1 / 3
    contract["within_category_weight"] = contract.groupby("category")["metric"].transform(
        lambda values: 1 / len(values)
    )

    rank_table = pd.DataFrame(index=raw.index)
    normalized = pd.DataFrame(index=raw.index)
    for metric, _, direction, _, _ in METRIC_CONTRACT:
        ascending = direction == "LOW"
        rank_table[f"{metric}_rank"] = raw[metric].rank(method="average", ascending=ascending)
        normalized[metric] = (len(raw) - rank_table[f"{metric}_rank"]) / (len(raw) - 1)
    for category in ("PREDICTIVE", "ECONOMIC", "ROBUSTNESS"):
        metrics = contract.loc[contract["category"] == category, "metric"].tolist()
        rank_table[f"{category.lower()}_rank_average"] = rank_table[
            [f"{metric}_rank" for metric in metrics]
        ].mean(axis=1)
    rank_table["overall_rank_average"] = rank_table[[column for column in rank_table if column.endswith("_rank")]].mean(axis=1)

    sensitivity_rows = []
    composites = pd.DataFrame(index=raw.index)
    for scenario, category_weights in WEIGHT_SCENARIOS.items():
        score = pd.Series(0.0, index=raw.index)
        for category, category_weight in category_weights.items():
            metrics = contract.loc[contract["category"] == category, "metric"].tolist()
            score += normalized[metrics].mean(axis=1) * category_weight
        composites[f"{scenario.lower()}_composite"] = score
        order = score.sort_values(ascending=False, kind="mergesort").index.tolist()
        for rank, model in enumerate(order, start=1):
            sensitivity_rows.append(
                {"scenario": scenario, "model": model, "rank": rank, "composite_score": score[model]}
            )
    sensitivity = pd.DataFrame(sensitivity_rows)
    winners = sensitivity[sensitivity["rank"] == 1]["model"].nunique()
    sensitivity_status = (
        "MODEL_RANKING_NOT_ROBUST_TO_REASONABLE_WEIGHTING"
        if winners > 1
        else "MODEL_RANKING_ROBUST_TO_PREDEFINED_REASONABLE_WEIGHTING"
    )
    return raw.reset_index(), rank_table.reset_index(), composites.reset_index(), contract, sensitivity, sensitivity_status


def assert_pre2026_dates(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        dates = pd.to_datetime(frame[column], errors="coerce")
        if dates.dropna().ge(PRE2026_END).any():
            raise RuntimeError(f"2026 date encountered in {column}")


def market_state_by_prediction_date(paths: pd.DataFrame, prediction_dates: pd.Series) -> pd.DataFrame:
    paths = paths.copy()
    if "scope" in paths.columns:
        paths = paths[paths["scope"] == "POOLED_OOF"].copy()
        if paths.empty:
            raise RuntimeError("Canonical POOLED_OOF benchmark path is missing")
    paths["execution_date"] = pd.to_datetime(paths["execution_date"])
    benchmark_mismatch = int(paths.groupby("execution_date")["benchmark_return"].nunique(dropna=False).gt(1).sum())
    if benchmark_mismatch:
        raise RuntimeError("Benchmark return differs across models")
    benchmark = (
        paths.groupby("execution_date", as_index=False)["benchmark_return"].first().sort_values("execution_date")
    )
    benchmark["market_nav"] = (1 + benchmark["benchmark_return"]).cumprod()
    benchmark["market_peak"] = benchmark["market_nav"].cummax()
    rows = []
    for date in sorted(pd.to_datetime(prediction_dates).unique()):
        history = benchmark[benchmark["execution_date"] <= date]
        returns = history["benchmark_return"]
        rows.append(
            {
                "prediction_date": pd.Timestamp(date),
                "market_realized_vol_20d": returns.tail(20).std(ddof=0) * math.sqrt(252) if len(returns) >= 20 else np.nan,
                "market_trend_60d": (1 + returns.tail(60)).prod() - 1 if len(returns) >= 60 else np.nan,
                "market_drawdown_state": (
                    history["market_nav"].iloc[-1] / history["market_peak"].iloc[-1] - 1 if len(history) else np.nan
                ),
                "market_information_max_date": history["execution_date"].max() if len(history) else pd.NaT,
            }
        )
    result = pd.DataFrame(rows)
    violations = result["market_information_max_date"] > result["prediction_date"]
    if violations.any():
        raise RuntimeError("Market regime used future returns")
    return result


def feature_state_by_date(features: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    rows = []
    for date, group in features.groupby("prediction_date", sort=True):
        scale_ratios = []
        for feature in feature_names:
            values = group[feature].dropna().to_numpy(dtype=float)
            if len(values):
                q25, q75 = np.quantile(values, [0.25, 0.75])
                scale_ratios.append((q75 - q25) / (np.median(np.abs(values)) + 1e-12))
        rows.append(
            {
                "prediction_date": date,
                "cross_sectional_return_dispersion": group["ret_20d"].std(ddof=0),
                "cross_sectional_feature_dispersion": np.median(scale_ratios),
                "breadth_20d_positive": (group["ret_20d"] > 0).mean(),
                "feature_row_count": len(group),
            }
        )
    return pd.DataFrame(rows)


def score_and_disagreement(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    a2 = predictions[predictions["model"] == A2].copy()
    xgb = predictions[predictions["model"] == XGB].copy()
    keys = ["prediction_date", "security_id"]
    identity = a2[keys].merge(xgb[keys], on=keys, how="outer", indicator=True)
    universe_mismatch_count = int((identity["_merge"] != "both").sum())
    paired = a2[keys + ["raw_score"]].merge(
        xgb[keys + ["raw_score"]], on=keys, suffixes=("_a2", "_xgb"), validate="one_to_one"
    )
    score_corr = paired.groupby("prediction_date").apply(
        lambda group: group["raw_score_a2"].corr(group["raw_score_xgb"], method="spearman"),
        include_groups=False,
    )

    a2_selected = a2[a2["selected_top20"]].copy()
    xgb_selected = xgb[xgb["selected_top20"]].copy()
    selected = a2_selected[
        ["prediction_date", "security_id", "ticker", "realized_forward_target", "fold_id", "raw_score"]
    ].merge(
        xgb_selected[
            ["prediction_date", "security_id", "ticker", "realized_forward_target", "fold_id", "raw_score"]
        ],
        on=["prediction_date", "security_id"],
        how="outer",
        suffixes=("_a2", "_xgb"),
        indicator=True,
        validate="one_to_one",
    )
    selected["group"] = selected["_merge"].map(
        {"both": "COMMON", "left_only": "A2_ONLY", "right_only": "XGB_ONLY"}
    ).astype(str)
    selected["ticker"] = selected["ticker_a2"].combine_first(selected["ticker_xgb"])
    selected["fold_id"] = selected["fold_id_a2"].combine_first(selected["fold_id_xgb"])
    selected["realized_forward_target"] = selected["realized_forward_target_a2"].combine_first(
        selected["realized_forward_target_xgb"]
    )
    both = selected["_merge"] == "both"
    if not np.allclose(
        selected.loc[both, "realized_forward_target_a2"],
        selected.loc[both, "realized_forward_target_xgb"],
        equal_nan=True,
    ):
        raise RuntimeError("Realized targets differ between models")

    date_group = selected.groupby(["prediction_date", "group"])["realized_forward_target"].mean().unstack()
    overlap = selected[selected["group"] == "COMMON"].groupby("prediction_date").size() / 20.0
    score_dispersion = predictions[predictions["selected_top20"]].groupby(
        ["prediction_date", "model"]
    )["raw_score"].std(ddof=0).unstack()
    daily = pd.DataFrame(index=sorted(predictions["prediction_date"].unique()))
    daily.index.name = "prediction_date"
    daily["xgb_a2_score_correlation"] = score_corr
    daily["top20_overlap"] = overlap
    daily["a2_top20_score_dispersion"] = score_dispersion[A2]
    daily["xgb_top20_score_dispersion"] = score_dispersion[XGB]
    daily["xgb_replacement_spread"] = date_group["XGB_ONLY"] - date_group["A2_ONLY"]
    return daily.reset_index(), selected, universe_mismatch_count


def disagreement_by_fold(selected: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    def metrics(group: pd.DataFrame) -> pd.Series:
        values = group["realized_forward_target"]
        return pd.Series(
            {
                "observation_count": len(values),
                "mean_realized_return": values.mean(),
                "median_realized_return": values.median(),
                "hit_rate": (values > 0).mean(),
                "tail_loss_q05": values.quantile(0.05),
                "tail_gain_q95": values.quantile(0.95),
            }
        )

    table = selected.groupby(["fold_id", "group"], observed=True).apply(metrics, include_groups=False).reset_index()
    attribution: dict[str, str] = {}
    for fold_id in sorted(table["fold_id"].unique()):
        fold = table[table["fold_id"] == fold_id].set_index("group")
        better_winners = fold.at["XGB_ONLY", "tail_gain_q95"] > fold.at["A2_ONLY", "tail_gain_q95"]
        avoids_losers = fold.at["XGB_ONLY", "tail_loss_q05"] > fold.at["A2_ONLY", "tail_loss_q05"]
        attribution[fold_id] = (
            "C_BOTH" if better_winners and avoids_losers else
            "A_BETTER_WINNER_INCLUSION" if better_winners else
            "B_LOSER_AVOIDANCE" if avoids_losers else
            "D_NEITHER_OR_NOISE"
        )
    return table, attribution


def assign_fixed_terciles(series: pd.Series) -> tuple[pd.Series, dict[str, float]]:
    valid = series.dropna()
    ranks = valid.rank(method="average", pct=True)
    labels = pd.Series(index=series.index, dtype="object")
    labels.loc[valid.index] = np.where(ranks <= 1 / 3, "LOW", np.where(ranks <= 2 / 3, "MID", "HIGH"))
    return labels, {"q33": valid.quantile(1 / 3), "q67": valid.quantile(2 / 3)}


def relative_pnl_by_tercile(regime: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    thresholds: dict[str, Any] = {}
    for variable in TERCILE_VARIABLES:
        groups, cuts = assign_fixed_terciles(regime[variable])
        thresholds[variable] = cuts
        working = regime.assign(tercile=groups).dropna(subset=["tercile"])
        scopes = [("POOLED_PRE2026", working)] + list(working.groupby("fold_id", sort=True))
        for scope, scope_frame in scopes:
            for tercile, group in scope_frame.groupby("tercile", sort=False):
                relative = group["xgb_minus_a2_net_return"]
                rows.append(
                    {
                        "regime_variable": variable,
                        "scope": scope,
                        "tercile": tercile,
                        "date_count": len(group),
                        "xgb_minus_a2_average_return": relative.mean(),
                        "xgb_minus_a2_sharpe_contribution": (
                            relative.mean() / relative.std(ddof=0) * math.sqrt(252)
                            if relative.std(ddof=0) > 0 else np.nan
                        ),
                        "xgb_replacement_spread": group["xgb_replacement_spread"].mean(),
                        "top20_overlap": group["top20_overlap"].mean(),
                    }
                )
    return pd.DataFrame(rows), thresholds


def feature_importance(lineage: dict[str, Any], audit: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    model_manifest = json.loads((R1A_ROOT / "model_artifact_manifest.json").read_text(encoding="utf-8"))
    features = lineage["feature_names"]
    rows = []
    vectors = {}
    for artifact in model_manifest["artifacts"]:
        if artifact["model"] != XGB:
            continue
        path = Path(artifact["path"])
        verify_frozen_file(path, artifact["sha256"], audit)
        estimator = joblib.load(path)
        importance = np.asarray(estimator.feature_importances_, dtype=float)
        if len(importance) != len(features):
            raise RuntimeError("XGB importance length differs from frozen feature contract")
        vectors[artifact["fold_id"]] = importance
        for feature, value in zip(features, importance):
            rows.append({"fold_id": artifact["fold_id"], "feature": feature, "native_gain_importance": value})
    table = pd.DataFrame(rows)
    fold_summary = {}
    for fold_id, values in vectors.items():
        order = np.argsort(values)[::-1]
        fold_summary[fold_id] = {
            "hhi": float(np.square(values / values.sum()).sum()),
            "top5_share": float(values[order[:5]].sum() / values.sum()),
            "top5_features": [features[index] for index in order[:5]],
        }
    correlations = pd.DataFrame(vectors).corr(method="spearman")
    return table, {
        "xgb_native_importance_by_fold": fold_summary,
        "xgb_importance_rank_correlation": correlations.to_dict(),
        "a2_hgb_importance_status": "NATIVE_IMPORTANCE_UNAVAILABLE_NO_NEW_PERMUTATION_OR_SHAP_RUN",
        "interpretation_scope": "READ_ONLY_FROZEN_XGB_NATIVE_IMPORTANCE_NOT_FEATURE_SELECTION",
    }


def fold_regime_summary(regime: pd.DataFrame) -> pd.DataFrame:
    aggregations = {
        "market_realized_vol_20d": "mean",
        "cross_sectional_return_dispersion": "mean",
        "breadth_20d_positive": "mean",
        "market_trend_60d": "mean",
        "market_drawdown_state": "mean",
        "cross_sectional_feature_dispersion": "mean",
        "authoritative_13f_universe_count": "mean",
        "eligible_universe_count": "mean",
        "a2_top20_score_dispersion": "mean",
        "xgb_top20_score_dispersion": "mean",
        "xgb_a2_score_correlation": "mean",
        "top20_overlap": "mean",
        "xgb_replacement_spread": "mean",
        "xgb_minus_a2_net_return": ["mean", "sum"],
    }
    table = regime.groupby("fold_id").agg(aggregations)
    table.columns = ["_".join(column).rstrip("_") for column in table.columns]
    return table.reset_index()


def classify_regime_dependence(
    fold_summary: pd.DataFrame, regime: pd.DataFrame, conditional: pd.DataFrame
) -> tuple[str, dict[str, Any]]:
    by_fold = fold_summary.set_index("fold_id")
    z_scores = {}
    for variable in CORE_REGIME_VARIABLES:
        pooled_std = regime[variable].std(ddof=0)
        reference = by_fold.loc[["OUTER_2024", "OUTER_2025"], f"{variable}_mean"].mean()
        z_scores[variable] = (
            (by_fold.at["OUTER_2023", f"{variable}_mean"] - reference) / pooled_std
            if pooled_std and np.isfinite(pooled_std) else 0.0
        )
    moderate = sum(abs(value) >= 0.5 for value in z_scores.values())
    strong = sum(abs(value) >= 1.0 for value in z_scores.values())
    pnl = by_fold["xgb_minus_a2_net_return_sum"]
    consistent_gradients = {}
    for variable in CORE_REGIME_VARIABLES:
        rows = conditional[conditional["regime_variable"] == variable]
        gradients = {}
        for scope, group in rows.groupby("scope"):
            values = group.set_index("tercile")["xgb_minus_a2_average_return"]
            gradients[scope] = values.get("HIGH", np.nan) - values.get("LOW", np.nan)
        fold_values = [gradients.get(f"OUTER_{year}", np.nan) for year in (2023, 2024, 2025)]
        pooled = gradients.get("POOLED_PRE2026", np.nan)
        same_direction = (
            np.isfinite(pooled)
            and all(np.isfinite(value) for value in fold_values)
            and all(np.sign(value) == np.sign(pooled) for value in fold_values)
        )
        consistent_gradients[variable] = {
            "pooled_high_minus_low": pooled,
            "fold_high_minus_low": dict(zip(["OUTER_2023", "OUTER_2024", "OUTER_2025"], fold_values)),
            "same_direction_all_folds": bool(same_direction),
        }
    consistent_count = sum(row["same_direction_all_folds"] for row in consistent_gradients.values())
    strong_rule = strong >= 3 and pnl["OUTER_2023"] > 0 and (pnl[["OUTER_2024", "OUTER_2025"]] <= 0).all()
    if strong_rule:
        classification = "R3_STRONG_PRE2026_REGIME_DEPENDENCE_BUT_NOT_DEPLOYABLE"
    elif (moderate >= 2 or consistent_count >= 2) and pnl["OUTER_2023"] > pnl[["OUTER_2024", "OUTER_2025"]].mean():
        classification = "R2_DESCRIPTIVE_REGIME_DEPENDENCE"
    else:
        classification = "R1_NO_CLEAR_REGIME_PATTERN"
    return classification, {
        "predefined_rule": "R3 requires >=3 core variables |2023-vs-2024/25 pooled-z|>=1 plus positive 2023 and nonpositive both later-fold relative PnL; R2 requires stronger 2023 relative PnL plus either >=2 core variables |z|>=0.5 or >=2 core variables whose fixed-tercile HIGH-minus-LOW relative-return gradient has the same sign in every fold and pooled; otherwise R1",
        "core_variable_2023_vs_2024_2025_pooled_z": z_scores,
        "moderate_variable_count": moderate,
        "strong_variable_count": strong,
        "consistent_fixed_tercile_gradient_count": consistent_count,
        "fixed_tercile_gradient_evidence": consistent_gradients,
        "regime_gate_created": False,
    }


def ordered_models(table: pd.DataFrame, column: str) -> str:
    return ">".join(table.sort_values([column, "model"], kind="mergesort")["model"])


def main() -> None:
    if OUT_ROOT.exists():
        raise RuntimeError("R1C output root already exists; preserving existing evidence")
    if WORK_ROOT.exists():
        if any(WORK_ROOT.iterdir()):
            raise RuntimeError("R1C working root contains evidence; preserving it")
    else:
        WORK_ROOT.mkdir(parents=False)
    r1a_status, r1b_status, lineage, input_audit = verify_inputs()

    raw, rank_average, composite, metric_contract, sensitivity, sensitivity_status = build_symmetric_ranking()
    predictions = pd.read_parquet(
        R1A_ROOT / "oos_predictions.parquet",
        columns=[
            "prediction_date", "ticker", "security_id", "model", "raw_score", "selected_top20",
            "realized_forward_target", "fold_id", "authoritative_13f_universe_count", "eligible_universe_count",
        ],
        filters=[("model", "in", [A2, XGB])],
    )
    predictions["prediction_date"] = pd.to_datetime(predictions["prediction_date"])
    assert_pre2026_dates(predictions, ["prediction_date"])
    if set(predictions["fold_id"].unique()) != {"OUTER_2023", "OUTER_2024", "OUTER_2025"}:
        raise RuntimeError("Unexpected fold set")

    score_state, selected, universe_mismatch_count = score_and_disagreement(predictions)
    disagreement, disagreement_attribution = disagreement_by_fold(selected)
    a2_predictions = predictions[predictions["model"] == A2].copy()

    feature_columns = ["signal_date", "security_id"] + lineage["feature_names"]
    features = pd.read_parquet(
        RESEARCH_DATASET,
        columns=feature_columns,
        filters=[("signal_date", ">=", pd.Timestamp("2023-01-01")), ("signal_date", "<", PRE2026_END)],
    ).rename(columns={"signal_date": "prediction_date"})
    features["prediction_date"] = pd.to_datetime(features["prediction_date"])
    assert_pre2026_dates(features, ["prediction_date"])
    feature_keys = a2_predictions[["prediction_date", "security_id"]]
    features = feature_keys.merge(features, on=["prediction_date", "security_id"], how="left", validate="one_to_one")
    if features[lineage["feature_names"]].isna().all(axis=1).any():
        raise RuntimeError("Missing frozen feature row for an OOS security-date")
    feature_state = feature_state_by_date(features, lineage["feature_names"])

    paths = pd.read_parquet(
        R1A_ROOT / "oof_portfolio_paths.parquet",
        columns=["execution_date", "model", "benchmark_return", "scope"],
    )
    assert_pre2026_dates(paths, ["execution_date"])
    market_state = market_state_by_prediction_date(paths, a2_predictions["prediction_date"])

    universe = a2_predictions.groupby("prediction_date", as_index=False).agg(
        fold_id=("fold_id", "first"),
        authoritative_13f_universe_count=("authoritative_13f_universe_count", "first"),
        eligible_universe_count=("eligible_universe_count", "first"),
    )
    relative = pd.read_csv(R1B_ROOT / "date_level_attribution.csv", parse_dates=["execution_date", "prediction_date"])
    relative = relative.dropna(subset=["prediction_date"])[
        ["prediction_date", "execution_date", "xgb_minus_a2_net_return"]
    ]
    assert_pre2026_dates(relative, ["prediction_date", "execution_date"])
    regime = universe.merge(market_state, on="prediction_date", validate="one_to_one")
    regime = regime.merge(feature_state, on="prediction_date", validate="one_to_one")
    regime = regime.merge(score_state, on="prediction_date", validate="one_to_one")
    regime = regime.merge(relative, on="prediction_date", validate="one_to_one")
    if len(regime) != a2_predictions["prediction_date"].nunique():
        raise RuntimeError("Regime date coverage mismatch")

    conditional, tercile_thresholds = relative_pnl_by_tercile(regime)
    fold_summary = fold_regime_summary(regime)
    regime_classification, classification_evidence = classify_regime_dependence(
        fold_summary, regime, conditional
    )
    importance, importance_summary = feature_importance(lineage, input_audit)

    raw.to_csv(WORK_ROOT / "raw_model_metrics.csv", index=False)
    rank_average.to_csv(WORK_ROOT / "model_rank_average.csv", index=False)
    composite.to_csv(WORK_ROOT / "model_composite_ranking.csv", index=False)
    metric_contract.to_csv(WORK_ROOT / "ranking_metric_contract.csv", index=False)
    sensitivity.to_csv(WORK_ROOT / "ranking_weight_sensitivity.csv", index=False)
    regime.to_parquet(WORK_ROOT / "pit_regime_state_by_date.parquet", index=False)
    fold_summary.to_csv(WORK_ROOT / "regime_by_fold.csv", index=False)
    conditional.to_csv(WORK_ROOT / "relative_pnl_by_regime_tercile.csv", index=False)
    disagreement.to_csv(WORK_ROOT / "top20_disagreement_by_fold.csv", index=False)
    importance.to_csv(WORK_ROOT / "xgb_native_feature_importance_by_fold.csv", index=False)
    write_json(WORK_ROOT / "tercile_thresholds.json", tercile_thresholds)
    write_json(WORK_ROOT / "top20_attribution.json", disagreement_attribution)
    write_json(WORK_ROOT / "feature_importance_summary.json", importance_summary)
    write_json(WORK_ROOT / "regime_classification.json", classification_evidence)
    write_json(WORK_ROOT / "safe_read_audit.json", input_audit)

    predictive_order = ordered_models(rank_average, "predictive_rank_average")
    economic_order = ordered_models(rank_average, "economic_rank_average")
    balanced_order = ">".join(
        composite.sort_values(["balanced_composite", "model"], ascending=[False, True], kind="mergesort")["model"]
    )
    replacement_by_fold = (
        fold_summary.set_index("fold_id")["xgb_replacement_spread_mean"].to_dict()
    )
    status = {
        "A2_ALGORITHM_BENCHMARK_R1C_STATUS": "PASS_PRE2026_REGIME_FORENSIC_AND_SYMMETRIC_RANKING_REPAIR_COMPLETE",
        "MODEL_RANKING_LOGIC_STATUS": "PASS_SYMMETRIC_ABSOLUTE_METRICS",
        "MODEL_RANKING_WEIGHT_SENSITIVITY": sensitivity_status,
        "XGB_REGIME_CLASSIFICATION": regime_classification,
        "2023_XGB_REPLACEMENT_SPREAD": replacement_by_fold["OUTER_2023"],
        "2024_XGB_REPLACEMENT_SPREAD": replacement_by_fold["OUTER_2024"],
        "2025_XGB_REPLACEMENT_SPREAD": replacement_by_fold["OUTER_2025"],
        "PRE2026_MODEL_ORDER_PREDICTIVE": predictive_order,
        "PRE2026_MODEL_ORDER_ECONOMIC": economic_order,
        "PRE2026_MODEL_ORDER_BALANCED": balanced_order,
        "A2_AUTHORITATIVE_BASELINE_STATUS": "UNCHANGED",
        "TEMPORAL_VIOLATION_COUNT": 0,
        "UNIVERSE_MISMATCH_COUNT": universe_mismatch_count,
        "MODEL_FIT_COUNT": 0,
        "PARAMETER_SEARCH_COUNT": 0,
        "REGIME_GATE_COUNT": 0,
        "2026_ARTIFACT_READ_COUNT": 0,
        "2026_TRAINING_ROWS": 0,
        "2026_PARAMETER_SEARCH_COUNT": 0,
        "2026_MODEL_SELECTION_COUNT": 0,
        "2026_HOLDOUT_STATUS": "SEALED_NOT_USED",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_R1C",
    }
    if universe_mismatch_count:
        raise RuntimeError("A2/XGB universe mismatch")
    write_json(WORK_ROOT / "status.json", status)

    report = [
        f"# {RUN_ID}",
        "",
        "R1C repairs only the ranking methodology and performs descriptive pre-2026 attribution. R1A and R1B are unchanged.",
        "",
        "## Ranking",
        "",
        "Every competitive model, including A2, is scored on the same absolute metrics. No comparator-relative fold-beat count is used. The balanced composite gives equal total weight to predictive, economic, and robustness categories; predefined tilts are sensitivity diagnostics, not model selection.",
        "",
        f"- Predictive order: {predictive_order}",
        f"- Economic order: {economic_order}",
        f"- Balanced order: {balanced_order}",
        f"- Weight sensitivity: {sensitivity_status}",
        "",
        "## Regime forensic",
        "",
        f"Classification: {regime_classification}. This is descriptive and does not authorize a regime gate.",
        "Market state uses only benchmark returns dated on or before each prediction date. Cross-sectional states use the frozen same-date PIT feature matrix. Terciles are fixed rank terciles over the complete pre-2026 OOS period and are not optimized against outcomes.",
        "",
        "## Model disagreement",
        "",
        *[f"- {fold}: {value}" for fold, value in disagreement_attribution.items()],
        "",
        "XGB native feature importance is read from hash-verified frozen artifacts. A2 HGB has no native importance; no new permutation importance, SHAP evaluation, feature selection, fitting, or prediction was run.",
        "",
        "## Governance",
        "",
        "2026 remains sealed. Training rows, parameter searches, model selections, model fits, and regime gates created by R1C are all zero.",
    ]
    (WORK_ROOT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    source_hashes = {row["path"]: row["actual_sha256"] for row in input_audit}
    source_hashes[str(SCRIPT_PATH)] = sha256(SCRIPT_PATH)
    write_json(WORK_ROOT / "source_hash_manifest.json", source_hashes)
    artifacts = []
    for path in sorted(WORK_ROOT.iterdir(), key=lambda item: item.name):
        if path.name in {"freeze_manifest.json", "sha256_manifest.txt"}:
            continue
        artifacts.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    freeze = {
        "run_id": RUN_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "DESCRIPTIVE_PRE2026_RESEARCH_NO_DEPLOYMENT_RULE",
        "r1a_modified": False,
        "r1b_modified": False,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "status": status,
    }
    write_json(WORK_ROOT / "freeze_manifest.json", freeze)
    sha_lines = []
    for path in sorted(WORK_ROOT.iterdir(), key=lambda item: item.name):
        if path.name != "sha256_manifest.txt":
            sha_lines.append(f"{sha256(path)}  {path.name}")
    (WORK_ROOT / "sha256_manifest.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    WORK_ROOT.rename(OUT_ROOT)

    for key, value in status.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
