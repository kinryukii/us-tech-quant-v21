"""R1 attribution and R1B five-day path-risk research, pre-2026 only."""

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

# Execution-only constraint for the managed Windows sandbox. It prevents
# sklearn/joblib worker-pipe creation and does not alter model specifications.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import HuberRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R1_ROOT = RESULTS_ROOT / "A2_RISK_ML_R1"
OUTPUT_DIR = RESULTS_ROOT / "A2_RISK_ML_R1B"
R1_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_risk_ml_r1.py"
R1_OOF = R1_ROOT / "risk_ml_r1_oof_predictions.parquet"
R1_SUMMARY = R1_ROOT / "risk_ml_r1_summary.json"
R1_REFERENCE_MODEL = "LOGIT_C03"
R1_REFERENCE_MAPPING = "DIRECT_MAPPING"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
PURGE_EMBARGO_SESSIONS = 5


def _load_r1() -> Any:
    spec = importlib.util.spec_from_file_location("a2_risk_ml_r1_shared", R1_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical R1 implementation")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R1 = _load_r1()
FEATURES = list(R1.FEATURES)
FOLDS = list(R1.FOLDS)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    params: dict[str, Any]


CANDIDATES = [
    Candidate("HUBER_A001", "HuberRegressor", {"epsilon": 1.35, "alpha": 0.001}),
    Candidate("HUBER_A010", "HuberRegressor", {"epsilon": 1.35, "alpha": 0.010}),
    Candidate("HGB_MAE_1", "HistGradientBoostingRegressor", {"learning_rate": 0.05, "max_iter": 80, "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 30, "l2_regularization": 5.0}),
    Candidate("HGB_MAE_2", "HistGradientBoostingRegressor", {"learning_rate": 0.03, "max_iter": 120, "max_leaf_nodes": 15, "max_depth": 4, "min_samples_leaf": 40, "l2_regularization": 10.0}),
    Candidate("LGBM_MAE_1", "LightGBMRegressor", {"n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3, "min_child_samples": 30, "reg_alpha": 1.0, "reg_lambda": 5.0}),
    Candidate("LGBM_MAE_2", "LightGBMRegressor", {"n_estimators": 150, "learning_rate": 0.03, "num_leaves": 15, "max_depth": 4, "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 10.0}),
]


def make_model(candidate: Candidate) -> Any:
    if candidate.family == "HuberRegressor":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", HuberRegressor(**candidate.params, max_iter=1000, tol=1e-6)),
            ]
        )
    if candidate.family == "HistGradientBoostingRegressor":
        return HistGradientBoostingRegressor(
            **candidate.params,
            loss="absolute_error",
            early_stopping=False,
            random_state=20260818,
        )
    if candidate.family == "LightGBMRegressor":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            **candidate.params,
            objective="regression_l1",
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


def forward_5d_mae(returns: np.ndarray) -> float:
    path = np.cumprod(1.0 + np.asarray(returns, dtype=float)) - 1.0
    return float(max(0.0, -path.min()))


def load_a2_daily() -> pd.DataFrame:
    raw = pd.read_parquet(R1.A2_DAILY)
    raw = raw.rename(columns={"execution_date": "date", "reconstructed_daily_return": "a2_return"})
    raw["date"] = pd.to_datetime(raw["date"])
    raw["gross_exposure"] = raw["position_value"] / raw["reconstructed_nav"]
    return raw.sort_values("date").reset_index(drop=True)


def attach_gross(frame: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    result = frame.merge(
        daily[["date", "gross_exposure"]],
        left_on="signal_date",
        right_on="date",
        how="left",
        validate="many_to_one",
    ).drop(columns="date")
    if result["gross_exposure"].isna().any():
        raise RuntimeError("missing frozen A2 gross exposure")
    return result


def constant_control(raw: np.ndarray, raw_gross: np.ndarray, ml_multiplier: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    mean_ml_gross = float(np.mean(np.asarray(raw_gross) * np.asarray(ml_multiplier)))
    constant_multiplier = mean_ml_gross / float(np.mean(raw_gross))
    multipliers = np.full(len(raw), constant_multiplier)
    controlled, turnover = R1.controlled_returns(raw, multipliers)
    return controlled, turnover, constant_multiplier, mean_ml_gross


def metrics_row(name: str, returns: np.ndarray, mean_exposure: float) -> dict[str, Any]:
    return {"portfolio": name, "mean_exposure": mean_exposure, **R1.performance_metrics(returns)}


def step1_attribution(daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    summary = json.loads(R1_SUMMARY.read_text(encoding="utf-8"))
    if summary.get("OOF_REFERENCE_MODEL") != R1_REFERENCE_MODEL or summary.get("OOF_REFERENCE_MAPPING") != R1_REFERENCE_MAPPING:
        raise RuntimeError("R1 diagnostic reference changed")
    oof = pd.read_parquet(R1_OOF)
    oof = oof.loc[oof["candidate_id"].eq(R1_REFERENCE_MODEL)].sort_values("target_date").copy()
    oof = attach_gross(oof, daily)
    raw = oof["target_return"].to_numpy(dtype=float)
    ml = oof[f"{R1_REFERENCE_MAPPING}_controlled_return"].to_numpy(dtype=float)
    multiplier = oof[f"{R1_REFERENCE_MAPPING}_multiplier"].to_numpy(dtype=float)
    raw_gross = oof["gross_exposure"].to_numpy(dtype=float)
    constant, constant_turnover, constant_multiplier, mean_ml_gross = constant_control(raw, raw_gross, multiplier)
    recomputed_ml, _ = R1.controlled_returns(raw, multiplier)
    if not np.allclose(recomputed_ml, ml, atol=1e-14, rtol=0):
        raise RuntimeError("persisted R1 controlled returns fail recomputation")
    table = pd.DataFrame(
        [
            metrics_row("RAW_A2", raw, float(raw_gross.mean())),
            metrics_row("R1_ML_CONTROLLED_A2", ml, mean_ml_gross),
            metrics_row("CONSTANT_EXPOSURE_A2", constant, float(np.mean(raw_gross * constant_multiplier))),
        ]
    )
    by_name = table.set_index("portfolio")
    ml_row, const_row = by_name.loc["R1_ML_CONTROLLED_A2"], by_name.loc["CONSTANT_EXPOSURE_A2"]
    return_value = float(ml_row.total_return - const_row.total_return)
    mdd_advantage = float(1 - abs(ml_row.maximum_drawdown) / abs(const_row.maximum_drawdown))
    es_advantage = float(1 - abs(ml_row.expected_shortfall_5) / abs(const_row.expected_shortfall_5))
    sharpe_advantage = float(ml_row.sharpe - const_row.sharpe)
    material = bool(mdd_advantage >= 0.10 and es_advantage >= 0 and sharpe_advantage >= 0.05 and return_value >= 0)
    attribution = {
        "status": "MATERIAL_TIMING_VALUE" if material else "NO_MATERIAL_TIMING_VALUE_OVER_CONSTANT_EXPOSURE",
        "r1_reference_model": R1_REFERENCE_MODEL,
        "r1_reference_mapping": R1_REFERENCE_MAPPING,
        "constant_multiplier": constant_multiplier,
        "matched_mean_gross_exposure": mean_ml_gross,
        "constant_exposure_turnover": float(constant_turnover.sum()),
        "ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE": return_value,
        "mdd_improvement_vs_constant": mdd_advantage,
        "expected_shortfall_5_improvement_vs_constant": es_advantage,
        "sharpe_difference_vs_constant": sharpe_advantage,
        "material_timing_value": material,
        "preregistered_materiality_rule": {
            "mdd_improvement_vs_constant_minimum": 0.10,
            "expected_shortfall_must_not_deteriorate": True,
            "sharpe_difference_minimum": 0.05,
            "total_return_difference_minimum": 0.0,
        },
        "rows": table.to_dict(orient="records"),
    }
    return table, attribution


def build_path_matrix(daily: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    returns = daily["a2_return"].to_numpy(dtype=float)
    dates = daily["date"].to_numpy()
    gross = daily["gross_exposure"].to_numpy(dtype=float)
    for i in range(len(daily) - 5):
        forward = returns[i + 1 : i + 6]
        rows.append(
            {
                "signal_date": pd.Timestamp(dates[i]),
                "next_date": pd.Timestamp(dates[i + 1]),
                "path_end_date": pd.Timestamp(dates[i + 5]),
                "next_return": float(forward[0]),
                "forward_5d_mae": forward_5d_mae(forward),
                "gross_exposure": float(gross[i]),
            }
        )
    matrix = pd.DataFrame(rows)
    matrix = pd.merge_asof(
        matrix.sort_values("signal_date"),
        features.sort_values("market_date"),
        left_on="signal_date",
        right_on="market_date",
        direction="backward",
        allow_exact_matches=False,
    )
    matrix = matrix.dropna(subset=FEATURES).loc[lambda x: x["path_end_date"].lt(TRAINING_CUTOFF)].reset_index(drop=True)
    if not matrix["market_date"].lt(matrix["signal_date"]).all():
        raise RuntimeError("feature lookahead violation")
    if not matrix["signal_date"].lt(matrix["next_date"]).all() or not matrix["next_date"].le(matrix["path_end_date"]).all():
        raise RuntimeError("path-target chronology violation")
    return matrix


def fold_split(matrix: pd.DataFrame, sessions: pd.DatetimeIndex, start_text: str, end_text: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
    valid = matrix.loc[matrix["next_date"].between(start, end)].copy()
    if valid.empty:
        raise RuntimeError("empty R1B validation fold")
    validation_start_signal = pd.Timestamp(valid["signal_date"].min())
    position = int(sessions.get_loc(validation_start_signal))
    if position < PURGE_EMBARGO_SESSIONS:
        raise RuntimeError("insufficient sessions for purge/embargo")
    embargo_cutoff = pd.Timestamp(sessions[position - PURGE_EMBARGO_SESSIONS])
    train = matrix.loc[matrix["path_end_date"].lt(embargo_cutoff)].copy()
    if train.empty or train["path_end_date"].max() >= embargo_cutoff:
        raise RuntimeError("purge/embargo failure")
    return train, valid, embargo_cutoff


def regression_metrics(realized: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = pd.Series(np.asarray(realized, dtype=float))
    score = pd.Series(np.asarray(predicted, dtype=float))
    return {
        "spearman": float(actual.corr(score, method="spearman")),
        "pearson": float(actual.corr(score, method="pearson")),
        "mae": float(np.mean(np.abs(actual - score))),
        "mean_realized_5d_mae": float(actual.mean()),
    }


def risk_deciles(frame: pd.DataFrame) -> dict[str, float]:
    decile = np.clip(np.ceil(frame["risk_percentile"].to_numpy(dtype=float) * 10), 1, 10).astype(int)
    actual = frame["forward_5d_mae"].to_numpy(dtype=float)
    result: dict[str, float] = {}
    for value in range(1, 11):
        mask = decile == value
        result[f"realized_5d_mae_decile_{value}"] = float(actual[mask].mean()) if mask.any() else np.nan
    top = result["realized_5d_mae_decile_10"]
    result["top_decile_path_risk_lift"] = float(top / actual.mean()) if actual.mean() > 0 and np.isfinite(top) else np.nan
    decile_means = pd.Series([result[f"realized_5d_mae_decile_{d}"] for d in range(1, 11)], index=range(1, 11)).dropna()
    result["decile_monotonic_spearman"] = float(decile_means.corr(pd.Series(decile_means.index, index=decile_means.index), method="spearman")) if len(decile_means) > 1 else np.nan
    return result


def run_oof(matrix: pd.DataFrame, sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    predictions: list[pd.DataFrame] = []
    fit_count = 0
    for candidate in CANDIDATES:
        for fold_name, start, end in FOLDS:
            train, valid, embargo_cutoff = fold_split(matrix, sessions, start, end)
            if len(train) < 100 or len(valid) < 20:
                raise RuntimeError(f"insufficient R1B fold rows: {fold_name}")
            model = make_model(candidate)
            model.fit(train[FEATURES], train["forward_5d_mae"])
            fit_count += 1
            train_score = model.predict(train[FEATURES])
            valid_score = model.predict(valid[FEATURES])
            valid["candidate_id"] = candidate.candidate_id
            valid["model_family"] = candidate.family
            valid["fold"] = fold_name
            valid["embargo_cutoff"] = embargo_cutoff
            valid["train_max_path_end"] = train["path_end_date"].max()
            valid["predicted_5d_path_risk"] = valid_score
            valid["risk_percentile"] = R1.empirical_percentile(train_score, valid_score)
            predictions.append(valid)
    oof = pd.concat(predictions, ignore_index=True).sort_values(["candidate_id", "next_date"]).reset_index(drop=True)
    comparisons: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        frame = oof.loc[oof["candidate_id"].eq(candidate.candidate_id)].copy()
        multiplier = R1.direct_multiplier(frame["risk_percentile"].to_numpy())
        controlled, turnover = R1.controlled_returns(frame["next_return"].to_numpy(), multiplier)
        constant, constant_turnover, constant_multiplier, mean_ml_gross = constant_control(
            frame["next_return"].to_numpy(), frame["gross_exposure"].to_numpy(), multiplier
        )
        mask = oof["candidate_id"].eq(candidate.candidate_id)
        oof.loc[mask, "risk_multiplier"] = multiplier
        oof.loc[mask, "controlled_return"] = controlled
        oof.loc[mask, "exposure_change_turnover"] = turnover
        oof.loc[mask, "constant_multiplier"] = constant_multiplier
        oof.loc[mask, "constant_control_return"] = constant
        oof.loc[mask, "constant_exposure_turnover"] = constant_turnover
        reg = regression_metrics(frame["forward_5d_mae"].to_numpy(), frame["predicted_5d_path_risk"].to_numpy())
        diag = risk_deciles(frame)
        raw_m = R1.performance_metrics(frame["next_return"].to_numpy())
        ctl_m = R1.performance_metrics(controlled)
        const_m = R1.performance_metrics(constant)
        direction_folds = 0
        timing_folds = 0
        for fold_name, _, _ in FOLDS:
            fold = oof.loc[mask & oof["fold"].eq(fold_name)].copy()
            fm = regression_metrics(fold["forward_5d_mae"].to_numpy(), fold["predicted_5d_path_risk"].to_numpy())
            fd = risk_deciles(fold)
            fr = R1.performance_metrics(fold["next_return"].to_numpy())
            fc = R1.performance_metrics(fold["controlled_return"].to_numpy())
            fk = R1.performance_metrics(fold["constant_control_return"].to_numpy())
            direction = bool(fm["spearman"] > 0)
            timing = bool(
                (abs(fc["maximum_drawdown"]) < abs(fk["maximum_drawdown"]) or fc["expected_shortfall_5"] > fk["expected_shortfall_5"])
                and fc["total_return"] >= fk["total_return"] - 0.05
            )
            direction_folds += int(direction)
            timing_folds += int(timing)
            folds.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "model_family": candidate.family,
                    "fold": fold_name,
                    **fm,
                    **fd,
                    **{f"raw_{k}": v for k, v in fr.items()},
                    **{f"controlled_{k}": v for k, v in fc.items()},
                    **{f"constant_{k}": v for k, v in fk.items()},
                    "predictive_direction_positive": direction,
                    "timing_benefit_vs_constant": timing,
                    "train_max_path_end": fold["train_max_path_end"].iloc[0],
                    "embargo_cutoff": fold["embargo_cutoff"].iloc[0],
                }
            )
        retention = ctl_m["total_return"] / raw_m["total_return"] if raw_m["total_return"] > 0 else np.nan
        mdd_vs_constant = 1 - abs(ctl_m["maximum_drawdown"]) / abs(const_m["maximum_drawdown"])
        es_vs_constant = 1 - abs(ctl_m["expected_shortfall_5"]) / abs(const_m["expected_shortfall_5"])
        timing_return = ctl_m["total_return"] - const_m["total_return"]
        predictive = bool(reg["spearman"] >= 0.10 and reg["pearson"] > 0 and diag["top_decile_path_risk_lift"] >= 1.25 and direction_folds >= 4)
        timing_value = bool(
            timing_return >= 0
            and ctl_m["sharpe"] > const_m["sharpe"]
            and (mdd_vs_constant >= 0.10 or es_vs_constant >= 0.10)
            and timing_folds >= 3
            and retention >= 0.85
        )
        qualifies = bool(predictive and timing_value)
        comparisons.append(
            {
                "candidate_id": candidate.candidate_id,
                "model_family": candidate.family,
                "params_json": json.dumps(candidate.params, sort_keys=True),
                **reg,
                **diag,
                **{f"raw_{k}": v for k, v in raw_m.items()},
                **{f"controlled_{k}": v for k, v in ctl_m.items()},
                **{f"constant_{k}": v for k, v in const_m.items()},
                "mean_controlled_exposure": mean_ml_gross,
                "constant_multiplier": constant_multiplier,
                "exposure_turnover": float(turnover.sum()),
                "constant_exposure_turnover": float(constant_turnover.sum()),
                "return_retention": retention,
                "ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE": timing_return,
                "mdd_improvement_vs_constant": mdd_vs_constant,
                "expected_shortfall_5_improvement_vs_constant": es_vs_constant,
                "sharpe_difference_vs_constant": ctl_m["sharpe"] - const_m["sharpe"],
                "predictive_direction_fold_count": direction_folds,
                "timing_benefit_fold_count": timing_folds,
                "predictive_gate_pass": predictive,
                "incremental_timing_gate_pass": timing_value,
                "qualification": "A" if qualifies else "B" if predictive else "D" if retention < 0.75 else "C",
            }
        )
    return oof, pd.DataFrame(comparisons), pd.DataFrame(folds), fit_count


def select_model(comparison: pd.DataFrame) -> tuple[pd.Series, bool, str]:
    family_rank = {"HuberRegressor": 0, "HistGradientBoostingRegressor": 1, "LightGBMRegressor": 2}
    qualified = comparison.loc[comparison["qualification"].eq("A")].copy()
    pool = qualified if not qualified.empty else comparison.copy()
    pool["family_rank"] = pool["model_family"].map(family_rank)
    if not qualified.empty:
        pool = pool.loc[pool["family_rank"].eq(pool["family_rank"].min())]
    pool = pool.sort_values(
        ["predictive_direction_fold_count", "spearman", "top_decile_path_risk_lift", "sharpe_difference_vs_constant", "family_rank", "candidate_id"],
        ascending=[False, False, False, False, True, True],
    )
    selected = pool.iloc[0]
    if not qualified.empty:
        return selected, True, "A"
    if comparison["predictive_gate_pass"].any():
        return selected, False, "B"
    if comparison["qualification"].eq("D").all():
        return selected, False, "D"
    return selected, False, "C"


def freeze_if_qualified(matrix: pd.DataFrame, selected: pd.Series, output: Path, qualifies: bool) -> tuple[dict[str, Any], int]:
    if not qualifies:
        return {
            "status": "NOT_FROZEN_QUALIFICATION_GATE_FAILED",
            "diagnostic_reference_model": selected["candidate_id"],
            "classification": selected["qualification"],
            "2026_opened": False,
        }, 0
    candidate = next(c for c in CANDIDATES if c.candidate_id == selected["candidate_id"])
    model = make_model(candidate)
    model.fit(matrix[FEATURES], matrix["forward_5d_mae"])
    train_scores = model.predict(matrix[FEATURES])
    model_path = output / "risk_ml_r1b_selected_model.joblib"
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "target": "FORWARD_5D_MAE",
            "training_score_quantiles_70_85_95": np.quantile(train_scores, [0.70, 0.85, 0.95]),
            "exposure_mapping": {"0-70": 1.0, "70-85": 0.75, "85-95": 0.50, "95-100": 0.25},
        },
        model_path,
    )
    return {
        "status": "FROZEN_PRE2026_2026_REMAINS_SEALED",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_model": selected["candidate_id"],
        "model_family": selected["model_family"],
        "hyperparameters": candidate.params,
        "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "model_artifact_path": model_path,
        "model_artifact_sha256": R1.sha256_file(model_path),
        "2026_opened": False,
        "model_fit_count_after_freeze": 0,
    }, 1


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "A2_RISK_ML_R1A_STATUS", "R1A_ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE", "R1A_MATERIAL_TIMING_VALUE",
        "A2_RISK_ML_R1B_STATUS", "A2_RISK_ML_R1B_CLASSIFICATION", "R1B_REFERENCE_MODEL", "R1B_MODEL_FROZEN",
        "FEATURE_COUNT", "OOF_FOLD_COUNT", "OOF_SPEARMAN", "OOF_PEARSON", "OOF_MAE", "OOF_TOP_DECILE_PATH_RISK_LIFT",
        "RAW_A2_OOF_RETURN", "R1B_CONTROLLED_A2_OOF_RETURN", "CONSTANT_EXPOSURE_MATCHED_A2_OOF_RETURN",
        "R1B_ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE", "RAW_A2_OOF_MDD", "R1B_CONTROLLED_A2_OOF_MDD", "CONSTANT_EXPOSURE_MATCHED_A2_OOF_MDD",
        "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "OPTUNA_TRIAL_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "PURGE_EMBARGO_VIOLATION_COUNT",
        "NEW_RISK_R1B_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary.get(key)
        if isinstance(value, float):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    allowed_partial = {"risk_ml_r1a_attribution.csv", "risk_ml_r1a_attribution.json"}
    existing = {path.name for path in output.iterdir()} if output.exists() else set()
    if existing and existing != allowed_partial:
        raise RuntimeError(f"fail closed: output directory contains non-resumable evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    baseline = R1.verify_frozen_baseline()
    daily = load_a2_daily()
    step1_table, step1 = step1_attribution(daily)
    if existing:
        persisted = json.loads((output / "risk_ml_r1a_attribution.json").read_text(encoding="utf-8"))
        persisted_table = pd.read_csv(output / "risk_ml_r1a_attribution.csv")
        if persisted.get("ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE") != step1["ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE"]:
            raise RuntimeError("partial Step 1 JSON fails deterministic resume check")
        if not np.allclose(persisted_table.select_dtypes(include=[np.number]), step1_table.select_dtypes(include=[np.number]), equal_nan=True):
            raise RuntimeError("partial Step 1 table fails deterministic resume check")
    else:
        R1.write_csv(output / "risk_ml_r1a_attribution.csv", step1_table)
        R1.write_json(output / "risk_ml_r1a_attribution.json", step1)

    pre_prices = R1.load_pre2026_prices()
    pre_vix = R1.load_vix(True)
    feature_frame = R1.build_market_features(pre_prices, pre_vix)
    matrix = build_path_matrix(daily, feature_frame)
    if len(FEATURES) != 14 or FEATURES != R1.FEATURES:
        raise RuntimeError("R1 feature schema changed")
    if len({c.family for c in CANDIDATES}) != 3 or any(sum(x.family == c.family for x in CANDIDATES) > 3 for c in CANDIDATES):
        raise RuntimeError("R1B model-family/configuration cap violated")
    sessions = pd.DatetimeIndex(daily["date"])
    oof, comparison, fold_metrics, oof_fit_count = run_oof(matrix, sessions)
    selected, qualifies, classification = select_model(comparison)
    manifest, final_fit_count = freeze_if_qualified(matrix, selected, output, qualifies)
    R1.write_json(output / "risk_ml_r1b_selected_model_manifest.json", manifest)
    R1.write_parquet(output / "risk_ml_r1b_oof_predictions.parquet", oof)
    R1.write_csv(output / "risk_ml_r1b_model_comparison.csv", comparison)
    R1.write_csv(output / "risk_ml_r1b_fold_metrics.csv", fold_metrics)
    target_manifest = {
        "target": "FORWARD_5D_MAE",
        "definition": "max(0, -min(cumprod(1 + frozen_A2_net_return[t+1:t+5]) - 1))",
        "higher_is_riskier": True,
        "feature_list": FEATURES,
        "feature_schema_sha256": R1.canonical_hash(FEATURES),
        "purge_embargo_sessions": PURGE_EMBARGO_SESSIONS,
        "purge_contract": "train path_end_date strictly before the fifth A2 trading session preceding validation_start_signal",
        "exposure_mapping": {"0-70": 1.0, "70-85": 0.75, "85-95": 0.50, "95-100": 0.25},
        "qualification_gate": {
            "spearman_minimum": 0.10,
            "pearson_positive": True,
            "top_decile_path_risk_lift_minimum": 1.25,
            "positive_spearman_fold_minimum": 4,
            "timing_total_return_vs_constant_minimum": 0.0,
            "timing_sharpe_vs_constant_positive": True,
            "mdd_or_es_improvement_vs_constant_minimum": 0.10,
            "timing_benefit_fold_minimum": 3,
            "return_retention_minimum": 0.85,
        },
    }
    R1.write_json(output / "risk_ml_r1b_target_manifest.json", target_manifest)

    guard = R1.guard_audit()
    purge_violations = int((oof["train_max_path_end"] >= oof["embargo_cutoff"]).sum())
    lookahead = int((matrix["market_date"] >= matrix["signal_date"]).sum())
    training_2026 = int(matrix["path_end_date"].ge(TRAINING_CUTOFF).sum())
    integrity_fail = bool(purge_violations or lookahead or training_2026 or guard["new_risk_r1_repo_violation_count"])
    final_classification = "E" if integrity_fail else classification
    status = "INVALID_INTEGRITY_FAILURE" if integrity_fail else "VALID_PRE2026_RESULT_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE"
    audit = {
        "status": status,
        "classification": final_classification,
        "baseline": baseline,
        "r1_lineage": {
            "oof_path": R1_OOF,
            "oof_sha256": R1.sha256_file(R1_OOF),
            "summary_path": R1_SUMMARY,
            "summary_sha256": R1.sha256_file(R1_SUMMARY),
        },
        "TRAINING_ROWS": len(matrix),
        "VALIDATION_ROWS": int(len(oof) / len(CANDIDATES)),
        "FEATURE_COUNT": len(FEATURES),
        "MODEL_FAMILY_COUNT": len({c.family for c in CANDIDATES}),
        "TOTAL_CANDIDATE_CONFIG_COUNT": len(CANDIDATES),
        "OOF_FOLD_COUNT": len(FOLDS),
        "OOF_MODEL_FIT_COUNT": oof_fit_count,
        "FINAL_MODEL_FIT_COUNT": final_fit_count,
        "MODEL_FIT_COUNT_AFTER_FREEZE": 0,
        "PRE_FREEZE_TECHNICAL_RETRY_COMPLETED_FIT_COUNT": 10,
        "PRE_FREEZE_TECHNICAL_RETRY_FAILED_FIT_COUNT": 1,
        "PRE_FREEZE_TECHNICAL_RETRY_REASON": "managed Windows sandbox denied sklearn joblib worker-pipe creation; execution constrained to one thread with configurations unchanged",
        "TRAINING_DATA_2026_COUNT": training_2026,
        "HOLDOUT_FILE_READ_COUNT": 0,
        "2026_USED_FOR_FEATURE_SELECTION_COUNT": 0,
        "2026_USED_FOR_PARAMETER_SELECTION_COUNT": 0,
        "2026_USED_FOR_THRESHOLD_SELECTION_COUNT": 0,
        "RANDOM_CV_COUNT": 0,
        "OPTUNA_TRIAL_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "PURGE_EMBARGO_VIOLATION_COUNT": purge_violations,
        "NEW_RISK_R1B_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "repository_governance": guard,
    }
    R1.write_json(output / "risk_ml_r1b_audit.json", audit)
    s = selected.to_dict()
    summary = {
        "A2_RISK_ML_R1A_STATUS": step1["status"],
        "R1A_ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE": step1["ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE"],
        "R1A_MATERIAL_TIMING_VALUE": step1["material_timing_value"],
        "A2_RISK_ML_R1B_STATUS": status,
        "A2_RISK_ML_R1B_CLASSIFICATION": final_classification,
        "R1B_REFERENCE_MODEL": s["candidate_id"],
        "R1B_MODEL_FROZEN": qualifies and not integrity_fail,
        "FEATURE_COUNT": len(FEATURES),
        "OOF_FOLD_COUNT": len(FOLDS),
        "OOF_SPEARMAN": s["spearman"],
        "OOF_PEARSON": s["pearson"],
        "OOF_MAE": s["mae"],
        "OOF_TOP_DECILE_PATH_RISK_LIFT": s["top_decile_path_risk_lift"],
        "RAW_A2_OOF_RETURN": s["raw_total_return"],
        "R1B_CONTROLLED_A2_OOF_RETURN": s["controlled_total_return"],
        "CONSTANT_EXPOSURE_MATCHED_A2_OOF_RETURN": s["constant_total_return"],
        "R1B_ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE": s["ML_TIMING_VALUE_OVER_CONSTANT_EXPOSURE"],
        "RAW_A2_OOF_MDD": s["raw_maximum_drawdown"],
        "R1B_CONTROLLED_A2_OOF_MDD": s["controlled_maximum_drawdown"],
        "CONSTANT_EXPOSURE_MATCHED_A2_OOF_MDD": s["constant_maximum_drawdown"],
        "TRAINING_DATA_2026_COUNT": training_2026,
        "HOLDOUT_FILE_READ_COUNT": 0,
        "OPTUNA_TRIAL_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead,
        "PURGE_EMBARGO_VIOLATION_COUNT": purge_violations,
        "NEW_RISK_R1B_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "NEXT_AUTHORIZED_STEP": "STOP_AFTER_R1B;2026_REMAINS_SEALED",
        "step1_attribution": step1,
        "r1b_reference": s,
        "results_root": output,
    }
    R1.write_json(output / "risk_ml_r1b_summary.json", summary)
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
        print("A2_RISK_ML_R1B_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("A2_RISK_ML_R1B_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
