"""A2 RISK-ML-R2 portfolio-aware Q90 tail-risk research, pre-2026 only."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import QuantileRegressor
from sklearn.metrics import mean_pinball_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_RISK_ML_R2"
R1B_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_risk_ml_r1b.py"
PRIMARY_QUANTILE = 0.90
VOL_TARGET = 0.15
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")


def _load_r1b() -> Any:
    spec = importlib.util.spec_from_file_location("a2_risk_ml_r1b_shared", R1B_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical R1B implementation")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R1B = _load_r1b()
R1 = R1B.R1
MARKET_FEATURES = list(R1.FEATURES)
PORTFOLIO_FEATURES = [
    "PORTFOLIO_WEIGHTED_REALIZED_VOL_60D",
    "HOLDING_RETURN_DISPERSION_20D",
    "HOLDING_BREADTH_20D",
    "A2_SCORE_DISPERSION",
]
FEATURES = MARKET_FEATURES + PORTFOLIO_FEATURES
FOLDS = list(R1.FOLDS)
A2_ROOT = R1.BASELINE_ROOT / "A2"
TOP20_PATH = A2_ROOT / "top20_selections.parquet"
A2_TRAINING_MATRIX = A2_ROOT / "training_matrix.parquet"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    params: dict[str, Any]


CANDIDATES = [
    Candidate("LINEAR_Q90_A001", "QuantileRegressor", {"alpha": 0.001}),
    Candidate("LINEAR_Q90_A010", "QuantileRegressor", {"alpha": 0.010}),
    Candidate("HGB_Q90_1", "HistGradientBoostingRegressor", {"learning_rate": 0.05, "max_iter": 80, "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 30, "l2_regularization": 5.0}),
    Candidate("HGB_Q90_2", "HistGradientBoostingRegressor", {"learning_rate": 0.03, "max_iter": 120, "max_leaf_nodes": 15, "max_depth": 4, "min_samples_leaf": 40, "l2_regularization": 10.0}),
    Candidate("LGBM_Q90_1", "LightGBMRegressor", {"n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3, "min_child_samples": 30, "reg_alpha": 1.0, "reg_lambda": 5.0}),
    Candidate("LGBM_Q90_2", "LightGBMRegressor", {"n_estimators": 150, "learning_rate": 0.03, "num_leaves": 15, "max_depth": 4, "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 10.0}),
]


def make_model(candidate: Candidate) -> Any:
    if candidate.family == "QuantileRegressor":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", QuantileRegressor(quantile=PRIMARY_QUANTILE, solver="highs", fit_intercept=True, **candidate.params)),
            ]
        )
    if candidate.family == "HistGradientBoostingRegressor":
        return HistGradientBoostingRegressor(
            **candidate.params,
            loss="quantile",
            quantile=PRIMARY_QUANTILE,
            early_stopping=False,
            random_state=20260818,
        )
    if candidate.family == "LightGBMRegressor":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            **candidate.params,
            objective="quantile",
            alpha=PRIMARY_QUANTILE,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            random_state=20260818,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
            verbosity=-1,
        )
    raise ValueError(candidate.family)


def build_portfolio_state() -> tuple[pd.DataFrame, dict[str, Any]]:
    top = pd.read_parquet(TOP20_PATH)
    top["signal_date"] = pd.to_datetime(top["signal_date"])
    holding = pd.read_parquet(
        A2_TRAINING_MATRIX,
        columns=["signal_date", "ticker", "ret_20d", "realized_vol_60d"],
    )
    holding["signal_date"] = pd.to_datetime(holding["signal_date"])
    merged = top.merge(holding, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    rows: list[dict[str, Any]] = []
    incomplete_dates: list[str] = []
    for date, group in merged.groupby("signal_date", sort=True):
        if len(group) != 20 or group["ticker"].nunique() != 20:
            raise RuntimeError(f"frozen Top20 cardinality failure: {date}")
        if group[["ret_20d", "realized_vol_60d", "a2_prediction"]].isna().any().any():
            incomplete_dates.append(str(pd.Timestamp(date).date()))
            continue
        rows.append(
            {
                "portfolio_information_date": pd.Timestamp(date),
                "PORTFOLIO_WEIGHTED_REALIZED_VOL_60D": float(group["realized_vol_60d"].mean()),
                "HOLDING_RETURN_DISPERSION_20D": float(group["ret_20d"].std(ddof=0)),
                "HOLDING_BREADTH_20D": float(group["ret_20d"].gt(0).mean()),
                "A2_SCORE_DISPERSION": float(group["a2_prediction"].std(ddof=0)),
                "top20_count": 20,
            }
        )
    state = pd.DataFrame(rows).sort_values("portfolio_information_date").reset_index(drop=True)
    if state[PORTFOLIO_FEATURES].isna().any().any():
        raise RuntimeError("nonfinite portfolio-state feature")
    return state, {
        "complete_portfolio_state_dates": len(state),
        "incomplete_portfolio_state_date_count": len(incomplete_dates),
        "incomplete_dates": incomplete_dates,
        "last_complete_portfolio_information_date": state["portfolio_information_date"].max(),
        "sector_hhi_status": "DROPPED_NO_PIT_SECTOR_HISTORY",
        "beta_idio_correlation_status": "DROPPED_INCOMPLETE_AUTHORITATIVE_HOLDING_RETURN_HISTORY",
        "portfolio_churn_status": "DROPPED_A2_SCORE_DISPERSION_HAS_CLEANER_FROZEN_COVERAGE",
    }


def build_r2_matrix() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    daily = R1B.load_a2_daily()
    market = R1.build_market_features(R1.load_pre2026_prices(), R1.load_vix(True))
    matrix = R1B.build_path_matrix(daily, market)
    state, state_audit = build_portfolio_state()
    matrix = matrix.merge(
        state,
        left_on="market_date",
        right_on="portfolio_information_date",
        how="inner",
        validate="many_to_one",
    ).sort_values("signal_date").reset_index(drop=True)
    if not matrix["portfolio_information_date"].lt(matrix["signal_date"]).all():
        raise RuntimeError("portfolio-state timing violation")
    if not matrix["portfolio_information_date"].eq(matrix["market_date"]).all():
        raise RuntimeError("portfolio-state and market cutoff dates diverge")
    return matrix, daily, state_audit


def rolling_unconditional_q90(matrix: pd.DataFrame, valid: pd.DataFrame) -> np.ndarray:
    predictions = []
    for row in valid.itertuples(index=False):
        history = matrix.loc[matrix["path_end_date"].lt(row.signal_date), "forward_5d_mae"]
        if len(history) < 100:
            raise RuntimeError("insufficient matured history for rolling Q90 baseline")
        predictions.append(float(history.quantile(PRIMARY_QUANTILE)))
    return np.asarray(predictions)


def qpredict(model: Any, frame: pd.DataFrame) -> np.ndarray:
    return np.maximum(0.0, np.asarray(model.predict(frame[FEATURES]), dtype=float))


def regression_diagnostics(frame: pd.DataFrame) -> dict[str, float]:
    actual = frame["forward_5d_mae"].to_numpy(dtype=float)
    predicted = frame["predicted_q90"].to_numpy(dtype=float)
    baseline = frame["baseline_q90"].to_numpy(dtype=float)
    loss = float(mean_pinball_loss(actual, predicted, alpha=PRIMARY_QUANTILE))
    baseline_loss = float(mean_pinball_loss(actual, baseline, alpha=PRIMARY_QUANTILE))
    spearman = float(pd.Series(actual).corr(pd.Series(predicted), method="spearman"))
    pearson = float(pd.Series(actual).corr(pd.Series(predicted), method="pearson"))
    decile = np.clip(np.ceil(frame["risk_percentile"].to_numpy(dtype=float) * 10), 1, 10).astype(int)
    result: dict[str, float] = {
        "pinball_loss": loss,
        "baseline_pinball_loss": baseline_loss,
        "pinball_improvement": 1.0 - loss / baseline_loss if baseline_loss > 0 else np.nan,
        "spearman": spearman,
        "pearson": pearson,
    }
    for value in range(1, 11):
        mask = decile == value
        result[f"realized_5d_mae_decile_{value}"] = float(actual[mask].mean()) if mask.any() else np.nan
    top = result["realized_5d_mae_decile_10"]
    result["top_decile_mae_lift"] = top / float(actual.mean()) if actual.mean() > 0 and np.isfinite(top) else np.nan
    severe = actual >= baseline
    top_mask = decile == 10
    result["unconditional_severe_loss_incidence"] = float(severe.mean())
    result["top_decile_severe_loss_incidence"] = float(severe[top_mask].mean()) if top_mask.any() else np.nan
    result["top_decile_severe_loss_lift"] = (
        result["top_decile_severe_loss_incidence"] / result["unconditional_severe_loss_incidence"]
        if result["unconditional_severe_loss_incidence"] > 0 and np.isfinite(result["top_decile_severe_loss_incidence"])
        else np.nan
    )
    return result


def permutation_rows(model: Any, valid: pd.DataFrame, candidate: Candidate, fold: str, original_loss: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coefficient: dict[str, float] = {}
    if candidate.family == "QuantileRegressor":
        coefficient = dict(zip(FEATURES, model.named_steps["model"].coef_, strict=True))
    for index, feature in enumerate(FEATURES):
        permuted = valid.copy()
        order = np.random.default_rng(20260818 + index).permutation(len(valid))
        permuted[feature] = valid[feature].to_numpy()[order]
        loss = mean_pinball_loss(valid["forward_5d_mae"], qpredict(model, permuted), alpha=PRIMARY_QUANTILE)
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "model_family": candidate.family,
                "fold": fold,
                "feature_group": "MARKET_STATE" if feature in MARKET_FEATURES else "PORTFOLIO_STATE",
                "feature": feature,
                "pinball_loss_increase": float(loss - original_loss),
                "coefficient": coefficient.get(feature, np.nan),
            }
        )
    for group_name, columns, seed in [
        ("MARKET_STATE", MARKET_FEATURES, 20261001),
        ("PORTFOLIO_STATE", PORTFOLIO_FEATURES, 20261002),
    ]:
        permuted = valid.copy()
        order = np.random.default_rng(seed).permutation(len(valid))
        permuted[columns] = valid[columns].to_numpy()[order]
        loss = mean_pinball_loss(valid["forward_5d_mae"], qpredict(model, permuted), alpha=PRIMARY_QUANTILE)
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "model_family": candidate.family,
                "fold": fold,
                "feature_group": group_name,
                "feature": "__GROUP__",
                "pinball_loss_increase": float(loss - original_loss),
                "coefficient": np.nan,
            }
        )
    return rows


def strategy_metrics(name: str, returns: np.ndarray, exposure: np.ndarray) -> dict[str, Any]:
    return {"strategy": name, "mean_exposure": float(np.mean(exposure)), **R1.performance_metrics(returns)}


def relative_improvement(ml_value: float, control_value: float) -> float:
    return 1.0 - abs(ml_value) / abs(control_value) if control_value < 0 else np.nan


def run_oof(matrix: pd.DataFrame, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    predictions: list[pd.DataFrame] = []
    importances: list[dict[str, Any]] = []
    fit_count = 0
    for candidate in CANDIDATES:
        for fold_name, start, end in FOLDS:
            train, valid, embargo_cutoff = R1B.fold_split(matrix, sessions, start, end)
            if len(train) < 100 or len(valid) < 20:
                raise RuntimeError(f"insufficient R2 fold rows: {fold_name}")
            model = make_model(candidate)
            model.fit(train[FEATURES], train["forward_5d_mae"])
            fit_count += 1
            train_score = qpredict(model, train)
            valid["predicted_q90"] = qpredict(model, valid)
            valid["baseline_q90"] = rolling_unconditional_q90(matrix, valid)
            valid["risk_percentile"] = R1.empirical_percentile(train_score, valid["predicted_q90"].to_numpy())
            valid["candidate_id"] = candidate.candidate_id
            valid["model_family"] = candidate.family
            valid["fold"] = fold_name
            valid["embargo_cutoff"] = embargo_cutoff
            valid["train_max_path_end"] = train["path_end_date"].max()
            loss = mean_pinball_loss(valid["forward_5d_mae"], valid["predicted_q90"], alpha=PRIMARY_QUANTILE)
            importances.extend(permutation_rows(model, valid, candidate, fold_name, float(loss)))
            predictions.append(valid)
    oof = pd.concat(predictions, ignore_index=True).sort_values(["candidate_id", "next_date"]).reset_index(drop=True)
    importance = pd.DataFrame(importances)
    comparisons: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        mask = oof["candidate_id"].eq(candidate.candidate_id)
        frame = oof.loc[mask].copy()
        ml_multiplier = R1.direct_multiplier(frame["risk_percentile"].to_numpy())
        ml_return, ml_turnover = R1.controlled_returns(frame["next_return"].to_numpy(), ml_multiplier)
        constant_return, constant_turnover, constant_multiplier, mean_ml_gross = R1B.constant_control(
            frame["next_return"].to_numpy(), frame["gross_exposure"].to_numpy(), ml_multiplier
        )
        vol_multiplier = np.minimum(1.0, VOL_TARGET / frame["QQQ_REALIZED_VOL_20D"].to_numpy(dtype=float))
        vol_return, vol_turnover = R1.controlled_returns(frame["next_return"].to_numpy(), vol_multiplier)
        for column, values in [
            ("ml_multiplier", ml_multiplier), ("ml_return", ml_return), ("ml_turnover", ml_turnover),
            ("constant_multiplier", np.full(len(frame), constant_multiplier)), ("constant_return", constant_return), ("constant_turnover", constant_turnover),
            ("vol_target_multiplier", vol_multiplier), ("vol_target_return", vol_return), ("vol_target_turnover", vol_turnover),
        ]:
            oof.loc[mask, column] = values
        predictive = regression_diagnostics(frame)
        raw_m = R1.performance_metrics(frame["next_return"].to_numpy())
        constant_m = R1.performance_metrics(constant_return)
        vol_m = R1.performance_metrics(vol_return)
        ml_m = R1.performance_metrics(ml_return)
        positive_direction_folds = 0
        useful_economic_folds = 0
        for fold_name, _, _ in FOLDS:
            fold = oof.loc[mask & oof["fold"].eq(fold_name)].copy()
            pdx = regression_diagnostics(fold)
            direction = bool(pdx["pinball_improvement"] > 0 and pdx["spearman"] > 0)
            positive_direction_folds += int(direction)
            metrics = {
                "raw": R1.performance_metrics(fold["next_return"].to_numpy()),
                "constant": R1.performance_metrics(fold["constant_return"].to_numpy()),
                "vol_target": R1.performance_metrics(fold["vol_target_return"].to_numpy()),
                "ml": R1.performance_metrics(fold["ml_return"].to_numpy()),
            }
            ml_fold, constant_fold, vol_fold = metrics["ml"], metrics["constant"], metrics["vol_target"]
            useful = bool(
                (ml_fold["expected_shortfall_5"] > max(constant_fold["expected_shortfall_5"], vol_fold["expected_shortfall_5"])
                 or abs(ml_fold["maximum_drawdown"]) < min(abs(constant_fold["maximum_drawdown"]), abs(vol_fold["maximum_drawdown"])))
                and ml_fold["sharpe"] >= max(constant_fold["sharpe"], vol_fold["sharpe"]) - 0.05
                and ml_fold["total_return"] >= max(constant_fold["total_return"], vol_fold["total_return"]) - 0.05
            )
            useful_economic_folds += int(useful)
            row: dict[str, Any] = {
                "candidate_id": candidate.candidate_id,
                "model_family": candidate.family,
                "fold": fold_name,
                **pdx,
                "predictive_direction_positive": direction,
                "useful_economic_direction": useful,
                "train_max_path_end": fold["train_max_path_end"].iloc[0],
                "embargo_cutoff": fold["embargo_cutoff"].iloc[0],
            }
            for strategy, values in metrics.items():
                exposure_column = {"raw": "gross_exposure", "constant": "constant_multiplier", "vol_target": "vol_target_multiplier", "ml": "ml_multiplier"}[strategy]
                row[f"{strategy}_mean_exposure"] = float((fold["gross_exposure"] * fold[exposure_column]).mean()) if strategy != "raw" else float(fold["gross_exposure"].mean())
                row.update({f"{strategy}_{key}": value for key, value in values.items()})
            fold_rows.append(row)
        imp = importance.loc[(importance["candidate_id"].eq(candidate.candidate_id)) & importance["feature"].eq("__GROUP__")]
        portfolio_imp = imp.loc[imp["feature_group"].eq("PORTFOLIO_STATE"), "pinball_loss_increase"]
        market_imp = imp.loc[imp["feature_group"].eq("MARKET_STATE"), "pinball_loss_increase"]
        portfolio_reproducible = bool(portfolio_imp.mean() > 0 and portfolio_imp.gt(0).sum() >= 3)
        predictive_gate = bool(
            predictive["pinball_improvement"] >= 0.10
            and predictive["spearman"] >= 0.10
            and predictive["top_decile_mae_lift"] >= 1.25
            and predictive["top_decile_severe_loss_lift"] >= 1.25
            and positive_direction_folds >= 4
        )
        constant_mdd_rel = relative_improvement(ml_m["maximum_drawdown"], constant_m["maximum_drawdown"])
        vol_mdd_rel = relative_improvement(ml_m["maximum_drawdown"], vol_m["maximum_drawdown"])
        constant_es_rel = relative_improvement(ml_m["expected_shortfall_5"], constant_m["expected_shortfall_5"])
        vol_es_rel = relative_improvement(ml_m["expected_shortfall_5"], vol_m["expected_shortfall_5"])
        beats_constant = bool(
            ml_m["sharpe"] > constant_m["sharpe"]
            and (constant_mdd_rel >= 0.10 or constant_es_rel >= 0.10)
            and ml_m["expected_shortfall_5"] > constant_m["expected_shortfall_5"]
            and ml_m["total_return"] >= constant_m["total_return"] - 0.05
        )
        beats_vol = bool(
            ml_m["sharpe"] > vol_m["sharpe"]
            and (vol_mdd_rel >= 0.10 or vol_es_rel >= 0.10)
            and ml_m["expected_shortfall_5"] > vol_m["expected_shortfall_5"]
            and ml_m["total_return"] >= vol_m["total_return"] - 0.05
        )
        return_retention = ml_m["total_return"] / raw_m["total_return"] if raw_m["total_return"] > 0 else np.nan
        economics_gate = bool(beats_constant and beats_vol and useful_economic_folds >= 4 and return_retention >= 0.85)
        classification = "A" if predictive_gate and portfolio_reproducible and economics_gate else "B" if predictive_gate and portfolio_reproducible else "D" if return_retention < 0.75 and ml_m["sharpe"] < min(constant_m["sharpe"], vol_m["sharpe"]) else "C"
        row = {
            "candidate_id": candidate.candidate_id,
            "model_family": candidate.family,
            "params_json": json.dumps(candidate.params, sort_keys=True),
            **predictive,
            **{f"raw_{key}": value for key, value in raw_m.items()},
            **{f"constant_{key}": value for key, value in constant_m.items()},
            **{f"vol_target_{key}": value for key, value in vol_m.items()},
            **{f"ml_{key}": value for key, value in ml_m.items()},
            "raw_mean_exposure": float(frame["gross_exposure"].mean()),
            "constant_mean_exposure": mean_ml_gross,
            "vol_target_mean_exposure": float((frame["gross_exposure"] * vol_multiplier).mean()),
            "ml_mean_exposure": mean_ml_gross,
            "ml_exposure_turnover": float(ml_turnover.sum()),
            "constant_exposure_turnover": float(constant_turnover.sum()),
            "vol_target_exposure_turnover": float(vol_turnover.sum()),
            "ML_RETURN_VALUE_OVER_CONSTANT": ml_m["total_return"] - constant_m["total_return"],
            "ML_MDD_VALUE_OVER_CONSTANT": abs(constant_m["maximum_drawdown"]) - abs(ml_m["maximum_drawdown"]),
            "ML_ES_VALUE_OVER_CONSTANT": ml_m["expected_shortfall_5"] - constant_m["expected_shortfall_5"],
            "ML_RETURN_VALUE_OVER_VOL_TARGET": ml_m["total_return"] - vol_m["total_return"],
            "ML_MDD_VALUE_OVER_VOL_TARGET": abs(vol_m["maximum_drawdown"]) - abs(ml_m["maximum_drawdown"]),
            "ML_ES_VALUE_OVER_VOL_TARGET": ml_m["expected_shortfall_5"] - vol_m["expected_shortfall_5"],
            "positive_direction_folds": positive_direction_folds,
            "useful_economic_direction_folds": useful_economic_folds,
            "market_group_pinball_importance": float(market_imp.mean()),
            "portfolio_group_pinball_importance": float(portfolio_imp.mean()),
            "portfolio_group_positive_importance_folds": int(portfolio_imp.gt(0).sum()),
            "predictive_gate_pass": predictive_gate,
            "portfolio_information_reproducible": portfolio_reproducible,
            "beats_constant_gate": beats_constant,
            "beats_vol_target_gate": beats_vol,
            "economics_gate_pass": economics_gate,
            "return_retention": return_retention,
            "qualification": classification,
        }
        comparisons.append(row)
    return oof, pd.DataFrame(comparisons), pd.DataFrame(fold_rows), importance, fit_count


def select_candidate(comparison: pd.DataFrame) -> tuple[pd.Series, str]:
    family_rank = {"QuantileRegressor": 0, "HistGradientBoostingRegressor": 1, "LightGBMRegressor": 2}
    rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    frame = comparison.copy()
    frame["qualification_rank"] = frame["qualification"].map(rank)
    frame["family_rank"] = frame["model_family"].map(family_rank)
    best_class = frame["qualification_rank"].min()
    pool = frame.loc[frame["qualification_rank"].eq(best_class)].copy()
    if best_class <= 1:
        pool = pool.loc[pool["family_rank"].eq(pool["family_rank"].min())]
    selected = pool.sort_values(
        ["positive_direction_folds", "pinball_improvement", "spearman", "top_decile_mae_lift", "family_rank", "candidate_id"],
        ascending=[False, False, False, False, True, True],
    ).iloc[0]
    return selected, str(selected["qualification"])


def selected_importance(importance: pd.DataFrame, candidate_id: str) -> pd.DataFrame:
    frame = importance.loc[importance["candidate_id"].eq(candidate_id)].copy()
    return (
        frame.groupby(["feature_group", "feature"], as_index=False)
        .agg(
            mean_pinball_loss_increase=("pinball_loss_increase", "mean"),
            positive_importance_folds=("pinball_loss_increase", lambda x: int((x > 0).sum())),
            mean_coefficient=("coefficient", "mean"),
        )
        .sort_values("mean_pinball_loss_increase", ascending=False)
        .reset_index(drop=True)
    )


def freeze_if_a(matrix: pd.DataFrame, selected: pd.Series, output: Path, classification: str) -> tuple[dict[str, Any], int]:
    if classification != "A":
        return {
            "status": "NOT_FROZEN_QUALIFICATION_GATE_FAILED",
            "diagnostic_candidate": selected["candidate_id"],
            "classification": classification,
            "2026_opened": False,
        }, 0
    candidate = next(item for item in CANDIDATES if item.candidate_id == selected["candidate_id"])
    model = make_model(candidate)
    model.fit(matrix[FEATURES], matrix["forward_5d_mae"])
    scores = qpredict(model, matrix)
    path = output / "risk_ml_r2_selected_model.joblib"
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "quantile": PRIMARY_QUANTILE,
            "score_quantiles_70_85_95": np.quantile(scores, [0.70, 0.85, 0.95]),
            "exposure_mapping": {"0-70": 1.0, "70-85": 0.75, "85-95": 0.50, "95-100": 0.25},
        },
        path,
    )
    return {
        "status": "FROZEN_PRE2026_2026_REMAINS_SEALED",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_model": selected["candidate_id"],
        "model_family": selected["model_family"],
        "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "model_artifact_path": path,
        "model_artifact_sha256": R1.sha256_file(path),
        "2026_opened": False,
        "model_fit_count_after_freeze": 0,
    }, 1


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "A2_RISK_ML_R2_STATUS", "A2_RISK_ML_R2_CLASSIFICATION", "TOTAL_FEATURE_COUNT", "PORTFOLIO_STATE_FEATURE_COUNT",
        "SELECTED_MODEL", "MODEL_FROZEN", "OOF_PINBALL_IMPROVEMENT", "OOF_SPEARMAN", "OOF_TOP_DECILE_MAE_LIFT", "POSITIVE_DIRECTION_FOLDS",
        "RAW_A2_RETURN", "CONSTANT_RETURN", "VOL_TARGET_RETURN", "ML_RETURN", "RAW_A2_MDD", "CONSTANT_MDD", "VOL_TARGET_MDD", "ML_MDD",
        "RAW_A2_ES5", "CONSTANT_ES5", "VOL_TARGET_ES5", "ML_ES5", "ML_RETURN_VALUE_OVER_CONSTANT", "ML_RETURN_VALUE_OVER_VOL_TARGET",
        "ML_MDD_VALUE_OVER_CONSTANT", "ML_MDD_VALUE_OVER_VOL_TARGET", "ML_ES_VALUE_OVER_CONSTANT", "ML_ES_VALUE_OVER_VOL_TARGET",
        "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "NEW_RISK_R2_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary.get(key)
        if isinstance(value, float):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    baseline = R1.verify_frozen_baseline()
    if len(FEATURES) > 22 or len(PORTFOLIO_FEATURES) > 8 or len(CANDIDATES) > 9 or len({c.family for c in CANDIDATES}) > 3:
        raise RuntimeError("R2 complexity cap violation")
    matrix, daily, state_audit = build_r2_matrix()
    sessions = pd.DatetimeIndex(daily["date"])
    oof, comparison, fold_metrics, importance, oof_fit_count = run_oof(matrix, sessions)
    selected, classification = select_candidate(comparison)
    interpretation = selected_importance(importance, selected["candidate_id"])
    manifest, final_fit_count = freeze_if_a(matrix, selected, output, classification)
    selected_oof = oof.loc[oof["candidate_id"].eq(selected["candidate_id"])].sort_values("next_date")
    strategy_table = pd.DataFrame(
        [
            strategy_metrics("RAW_A2", selected_oof["next_return"].to_numpy(), selected_oof["gross_exposure"].to_numpy()),
            strategy_metrics("CONSTANT_EXPOSURE_MATCHED_A2", selected_oof["constant_return"].to_numpy(), (selected_oof["gross_exposure"] * selected_oof["constant_multiplier"]).to_numpy()),
            strategy_metrics("SIMPLE_VOL_TARGET_A2", selected_oof["vol_target_return"].to_numpy(), (selected_oof["gross_exposure"] * selected_oof["vol_target_multiplier"]).to_numpy()),
            strategy_metrics("ML_RISK_CONTROLLED_A2", selected_oof["ml_return"].to_numpy(), (selected_oof["gross_exposure"] * selected_oof["ml_multiplier"]).to_numpy()),
        ]
    )
    feature_manifest = {
        "total_feature_count": len(FEATURES),
        "market_state_feature_count": len(MARKET_FEATURES),
        "portfolio_state_feature_count": len(PORTFOLIO_FEATURES),
        "market_state_features": MARKET_FEATURES,
        "portfolio_state_features": PORTFOLIO_FEATURES,
        "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "portfolio_feature_contract": {
            "PORTFOLIO_WEIGHTED_REALIZED_VOL_60D": "equal-weight mean of frozen holding-level 60D realized volatility",
            "HOLDING_RETURN_DISPERSION_20D": "cross-sectional population standard deviation of frozen Top20 20D returns",
            "HOLDING_BREADTH_20D": "fraction of frozen Top20 with positive 20D return",
            "A2_SCORE_DISPERSION": "cross-sectional population standard deviation of frozen A2 Top20 predictions",
        },
        "risk_decision_timestamp": R1.RISK_DECISION_TIMESTAMP,
        "feature_information_cutoff": R1.FEATURE_INFORMATION_CUTOFF,
        "portfolio_state_audit": state_audit,
        "primary_quantile": PRIMARY_QUANTILE,
        "vol_target_control": {"realized_volatility_feature": "QQQ_REALIZED_VOL_20D", "annualized_target": VOL_TARGET, "maximum_exposure": 1.0},
    }
    guard = R1.guard_audit()
    lookahead = int((matrix["market_date"] >= matrix["signal_date"]).sum() + (matrix["portfolio_information_date"] >= matrix["signal_date"]).sum())
    purge_violations = int((oof["train_max_path_end"] >= oof["embargo_cutoff"]).sum())
    training_2026 = int(matrix["path_end_date"].ge(TRAINING_CUTOFF).sum())
    integrity_fail = bool(lookahead or purge_violations or training_2026 or guard["new_risk_r1_repo_violation_count"])
    final_classification = "E" if integrity_fail else classification
    status = "INVALID_INTEGRITY_FAILURE" if integrity_fail else "VALID_PRE2026_RESULT_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE"
    if integrity_fail and manifest.get("status", "").startswith("FROZEN"):
        raise RuntimeError("integrity failure detected after attempted freeze")
    R1.write_parquet(output / "risk_ml_r2_oof_predictions.parquet", oof)
    R1.write_csv(output / "risk_ml_r2_model_comparison.csv", comparison)
    R1.write_csv(output / "risk_ml_r2_fold_metrics.csv", fold_metrics)
    R1.write_csv(output / "risk_ml_r2_feature_importance.csv", interpretation)
    R1.write_csv(output / "risk_ml_r2_strategy_metrics.csv", strategy_table)
    R1.write_json(output / "risk_ml_r2_feature_manifest.json", feature_manifest)
    R1.write_json(output / "risk_ml_r2_selected_model_manifest.json", manifest)
    audit = {
        "status": status,
        "classification": final_classification,
        "baseline": baseline,
        "TRAINING_ROWS": len(matrix),
        "VALIDATION_ROWS": int(len(oof) / len(CANDIDATES)),
        "TOTAL_FEATURE_COUNT": len(FEATURES),
        "PORTFOLIO_STATE_FEATURE_COUNT": len(PORTFOLIO_FEATURES),
        "MODEL_FAMILY_COUNT": len({c.family for c in CANDIDATES}),
        "TOTAL_CANDIDATE_CONFIG_COUNT": len(CANDIDATES),
        "OOF_FOLD_COUNT": len(FOLDS),
        "OOF_MODEL_FIT_COUNT": oof_fit_count,
        "FINAL_MODEL_FIT_COUNT": final_fit_count,
        "MODEL_FIT_COUNT_AFTER_FREEZE": 0,
        "TRAINING_DATA_2026_COUNT": training_2026,
        "HOLDOUT_FILE_READ_COUNT": 0,
        "2026_USED_FOR_FEATURE_SELECTION_COUNT": 0,
        "2026_USED_FOR_PARAMETER_SELECTION_COUNT": 0,
        "2026_USED_FOR_THRESHOLD_SELECTION_COUNT": 0,
        "RANDOM_CV_COUNT": 0,
        "OPTUNA_TRIAL_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "PURGE_EMBARGO_VIOLATION_COUNT": purge_violations,
        "NEW_RISK_R2_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "repository_governance": guard,
        "portfolio_state": state_audit,
    }
    R1.write_json(output / "risk_ml_r2_audit.json", audit)
    s = selected.to_dict()
    summary = {
        "A2_RISK_ML_R2_STATUS": status,
        "A2_RISK_ML_R2_CLASSIFICATION": final_classification,
        "TOTAL_FEATURE_COUNT": len(FEATURES),
        "PORTFOLIO_STATE_FEATURE_COUNT": len(PORTFOLIO_FEATURES),
        "SELECTED_MODEL": s["candidate_id"],
        "MODEL_FROZEN": classification == "A" and not integrity_fail,
        "OOF_PINBALL_IMPROVEMENT": s["pinball_improvement"],
        "OOF_SPEARMAN": s["spearman"],
        "OOF_TOP_DECILE_MAE_LIFT": s["top_decile_mae_lift"],
        "POSITIVE_DIRECTION_FOLDS": int(s["positive_direction_folds"]),
        "RAW_A2_RETURN": s["raw_total_return"],
        "CONSTANT_RETURN": s["constant_total_return"],
        "VOL_TARGET_RETURN": s["vol_target_total_return"],
        "ML_RETURN": s["ml_total_return"],
        "RAW_A2_MDD": s["raw_maximum_drawdown"],
        "CONSTANT_MDD": s["constant_maximum_drawdown"],
        "VOL_TARGET_MDD": s["vol_target_maximum_drawdown"],
        "ML_MDD": s["ml_maximum_drawdown"],
        "RAW_A2_ES5": s["raw_expected_shortfall_5"],
        "CONSTANT_ES5": s["constant_expected_shortfall_5"],
        "VOL_TARGET_ES5": s["vol_target_expected_shortfall_5"],
        "ML_ES5": s["ml_expected_shortfall_5"],
        "ML_RETURN_VALUE_OVER_CONSTANT": s["ML_RETURN_VALUE_OVER_CONSTANT"],
        "ML_RETURN_VALUE_OVER_VOL_TARGET": s["ML_RETURN_VALUE_OVER_VOL_TARGET"],
        "ML_MDD_VALUE_OVER_CONSTANT": s["ML_MDD_VALUE_OVER_CONSTANT"],
        "ML_MDD_VALUE_OVER_VOL_TARGET": s["ML_MDD_VALUE_OVER_VOL_TARGET"],
        "ML_ES_VALUE_OVER_CONSTANT": s["ML_ES_VALUE_OVER_CONSTANT"],
        "ML_ES_VALUE_OVER_VOL_TARGET": s["ML_ES_VALUE_OVER_VOL_TARGET"],
        "TRAINING_DATA_2026_COUNT": training_2026,
        "HOLDOUT_FILE_READ_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "NEW_RISK_R2_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "NEXT_AUTHORIZED_STEP": "STOP_AFTER_R2;2026_REMAINS_SEALED",
        "selected_diagnostic": s,
        "interpretability": interpretation.to_dict(orient="records"),
        "results_root": output,
    }
    R1.write_json(output / "risk_ml_r2_summary.json", summary)
    print_summary(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    try:
        run(args.output_dir.resolve())
        return 0
    except Exception as exc:
        print("A2_RISK_ML_R2_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("A2_RISK_ML_R2_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
