"""A2 Stock-Risk R6: execution-aligned bad-asymmetry classification."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUTPUT_DIR = RESULTS_ROOT / "A2_STOCK_RISK_R6"
R4_SCRIPT = REPO_ROOT / "scripts" / "v22" / "a2_stock_risk_r4.py"
R3R_ROOT = RESULTS_ROOT / "A2_STOCK_RISK_R3A_R3R"
R3R_OOF_PATH = R3R_ROOT / "r3r_oof_predictions.parquet"
R3R_SIGNAL_HASH = "636d87b1fb0c8981d95cfc41524dbfd6e7afa86f361f27432b6799412a649399"
R3R_REFERENCE_MODEL = "LGBM_STOCK_Q90_1"
TRAINING_CUTOFF = pd.Timestamp("2026-01-01")
MAE_SEVERE_QUANTILE = 0.90
MFE_COMPENSATION_QUANTILE = 0.50
R6_INTERVENTION_PERCENTILE = 0.90
R6_INTERVENTION_MULTIPLIER = 0.50

# Preregistered predictive gate; economic results never participate in selection.
PREDICTIVE_MIN_POSITIVE_FOLDS = 4
PREDICTIVE_MIN_AUROC = 0.60
PREDICTIVE_MIN_AP_LIFT = 1.50
PREDICTIVE_MIN_TOP_DECILE_LIFT = 2.00


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R4 = _load_module(R4_SCRIPT, "a2_stock_risk_r4_for_r6")
R3 = R4.R3


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    params: dict[str, Any]


# Six fixed low-capacity configurations, two per authorized family.
CANDIDATES = [
    Candidate("LOGISTIC_BAD_ASYM_C010", "LogisticRegression", {"C": 0.10}),
    Candidate("LOGISTIC_BAD_ASYM_C100", "LogisticRegression", {"C": 1.00}),
    Candidate("HGB_BAD_ASYM_1", "HistGradientBoostingClassifier", {"learning_rate": 0.05, "max_iter": 80, "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 40, "l2_regularization": 5.0}),
    Candidate("HGB_BAD_ASYM_2", "HistGradientBoostingClassifier", {"learning_rate": 0.03, "max_iter": 120, "max_leaf_nodes": 15, "max_depth": 4, "min_samples_leaf": 60, "l2_regularization": 10.0}),
    Candidate("LGBM_BAD_ASYM_1", "LightGBMClassifier", {"n_estimators": 100, "learning_rate": 0.03, "num_leaves": 7, "max_depth": 3, "min_child_samples": 40, "reg_alpha": 1.0, "reg_lambda": 5.0}),
    Candidate("LGBM_BAD_ASYM_2", "LightGBMClassifier", {"n_estimators": 150, "learning_rate": 0.03, "num_leaves": 15, "max_depth": 4, "min_child_samples": 60, "reg_alpha": 1.0, "reg_lambda": 10.0}),
]


def make_model(candidate: Candidate) -> Any:
    if candidate.family == "LogisticRegression":
        return Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(**candidate.params, l1_ratio=0.0, class_weight="balanced", solver="lbfgs", max_iter=1000, random_state=20260818)),
        ])
    if candidate.family == "HistGradientBoostingClassifier":
        return HistGradientBoostingClassifier(**candidate.params, early_stopping=False, random_state=20260818)
    if candidate.family == "LightGBMClassifier":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            **candidate.params, objective="binary", class_weight="balanced", subsample=0.8,
            subsample_freq=1, colsample_bytree=0.8, random_state=20260818, n_jobs=1,
            deterministic=True, force_col_wise=True, verbosity=-1,
        )
    raise ValueError(candidate.family)


def _balanced_weights(y: np.ndarray) -> np.ndarray:
    count = np.bincount(y.astype(int), minlength=2)
    if np.any(count == 0):
        raise RuntimeError("bad-asymmetry training fold lacks both classes")
    return np.where(y == 1, len(y) / (2.0 * count[1]), len(y) / (2.0 * count[0]))


def fit_model(model: Any, candidate: Candidate, x: pd.DataFrame, y: np.ndarray) -> None:
    if candidate.family == "HistGradientBoostingClassifier":
        model.fit(x, y, sample_weight=_balanced_weights(y))
    else:
        model.fit(x, y)


def predict_probability(model: Any, frame: pd.DataFrame) -> np.ndarray:
    probability = np.asarray(model.predict_proba(frame[R3.FEATURES])[:, 1], dtype=float)
    if not (np.isfinite(probability).all() and ((probability >= 0) & (probability <= 1)).all()):
        raise RuntimeError("invalid classifier probability")
    return probability


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if R3.R1.sha256_file(R3R_OOF_PATH) != R3R_SIGNAL_HASH:
        raise RuntimeError("authoritative R3R signal hash mismatch")
    labeled, score_panel, corrected, daily, positions, r3r_oof, r3r_summary = R4.load_inputs()
    if len(R3.FEATURES) != 22 or r3r_summary.get("R3R_REFERENCE_MODEL") != R3R_REFERENCE_MODEL:
        raise RuntimeError("R3R information-set contract mismatch")
    required = ["post_entry_5d_mae", "post_entry_5d_mfe", "post_entry_forward_5d_return"]
    if len(corrected) != len(score_panel) or corrected[required].isna().any().any():
        raise RuntimeError("execution-aligned outcome coverage is not 100 percent")
    if pd.to_datetime(corrected.target_end_date).ge(TRAINING_CUTOFF).any():
        raise RuntimeError("execution-aligned outcomes cross the 2026 firewall")
    labeled = score_panel.merge(corrected, on=["signal_date", "ticker"], validate="one_to_one")
    labeled = labeled.rename(columns={
        "post_entry_forward_1d_return": "next_day_stock_return",
        "post_entry_forward_5d_return": "forward_5d_stock_return",
        "post_entry_5d_mae": "forward_5d_stock_mae",
        "post_entry_5d_mfe": "forward_5d_stock_mfe",
    })
    if labeled.groupby("signal_date").size().ne(20).any():
        raise RuntimeError("R6 panel does not preserve exact Top20 date groups")
    return labeled, score_panel, corrected, daily, positions, r3r_oof, r3r_summary


def event_labels(frame: pd.DataFrame, mae_threshold: float, mfe_threshold: float) -> tuple[np.ndarray, np.ndarray]:
    severe = frame.forward_5d_stock_mae.to_numpy(dtype=float) >= mae_threshold
    weak_mfe = frame.forward_5d_stock_mfe.to_numpy(dtype=float) <= mfe_threshold
    negative = frame.forward_5d_stock_return.to_numpy(dtype=float) < 0
    return (severe & weak_mfe).astype(int), (severe & negative).astype(int)


def predictive_metrics(frame: pd.DataFrame) -> dict[str, float]:
    y = frame.bad_asymmetry_5d.to_numpy(dtype=int)
    p = frame.predicted_bad_asymmetry_risk.to_numpy(dtype=float)
    if len(np.unique(y)) != 2:
        raise RuntimeError("bad-asymmetry evaluation fold lacks both classes")
    base = float(y.mean())
    top = frame.risk_percentile.ge(R6_INTERVENTION_PERCENTILE)
    top_rate = float(frame.loc[top, "bad_asymmetry_5d"].mean())
    decile = np.clip(np.ceil(frame.risk_percentile.to_numpy(dtype=float) * 10), 1, 10).astype(int)
    decile_rate = pd.Series(y).groupby(decile).mean().sort_index()
    decile_direction = float(decile_rate.corr(pd.Series(decile_rate.index, index=decile_rate.index), method="spearman"))
    return {
        "validation_rows": len(frame), "base_event_frequency": base,
        "auroc": float(roc_auc_score(y, p)), "average_precision": float(average_precision_score(y, p)),
        "average_precision_lift": float(average_precision_score(y, p) / base),
        "brier_score": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "top_decile_event_rate": top_rate, "top_decile_bad_asymmetry_lift": top_rate / base,
        "risk_decile_incidence_spearman": decile_direction,
    }


def predictive_gate(metrics: dict[str, float] | pd.Series) -> bool:
    return bool(
        metrics["positive_direction_folds"] >= PREDICTIVE_MIN_POSITIVE_FOLDS
        and metrics["auroc"] >= PREDICTIVE_MIN_AUROC
        and metrics["average_precision_lift"] >= PREDICTIVE_MIN_AP_LIFT
        and metrics["top_decile_bad_asymmetry_lift"] >= PREDICTIVE_MIN_TOP_DECILE_LIFT
    )


def run_oof(panel: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    sessions = pd.DatetimeIndex(daily.execution_date)
    predictions: list[pd.DataFrame] = []
    fit_count = 0
    for candidate in CANDIDATES:
        for fold_name, start, end in R3.FOLDS:
            train, valid, cutoff = R3.fold_split(panel, sessions, start, end)
            mae_threshold = float(train.forward_5d_stock_mae.quantile(MAE_SEVERE_QUANTILE))
            mfe_threshold = float(train.forward_5d_stock_mfe.quantile(MFE_COMPENSATION_QUANTILE))
            y_train, secondary_train = event_labels(train, mae_threshold, mfe_threshold)
            y_valid, secondary_valid = event_labels(valid, mae_threshold, mfe_threshold)
            model = make_model(candidate)
            fit_model(model, candidate, train[R3.FEATURES], y_train)
            fit_count += 1
            training_probability = predict_probability(model, train)
            valid = valid.copy()
            valid["predicted_bad_asymmetry_risk"] = predict_probability(model, valid)
            valid["risk_percentile"] = R3.R1.empirical_percentile(training_probability, valid.predicted_bad_asymmetry_risk.to_numpy())
            valid["bad_asymmetry_5d"] = y_valid
            valid["bad_severe_negative_5d"] = secondary_valid
            valid["training_bad_asymmetry_base_rate"] = float(y_train.mean())
            valid["training_secondary_base_rate"] = float(secondary_train.mean())
            valid["fold_mae_severe_threshold"] = mae_threshold
            valid["fold_mfe_compensation_threshold"] = mfe_threshold
            valid["candidate_id"] = candidate.candidate_id
            valid["model_family"] = candidate.family
            valid["fold"] = fold_name
            valid["train_max_target_end"] = train.target_end_date.max()
            valid["embargo_cutoff"] = cutoff
            predictions.append(valid)
    oof = pd.concat(predictions, ignore_index=True).sort_values(["candidate_id", "signal_date", "ticker"]).reset_index(drop=True)
    comparison_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        frame = oof.loc[oof.candidate_id.eq(candidate.candidate_id)].copy()
        aggregate = predictive_metrics(frame)
        positive_folds = 0
        for fold_name, _, _ in R3.FOLDS:
            fold = frame.loc[frame.fold.eq(fold_name)]
            metric = predictive_metrics(fold)
            positive = bool(metric["auroc"] > 0.50 and metric["average_precision_lift"] > 1.0 and metric["top_decile_bad_asymmetry_lift"] > 1.0)
            positive_folds += int(positive)
            fold_rows.append({"candidate_id": candidate.candidate_id, "model_family": candidate.family, "fold": fold_name, **metric, "predictive_direction_positive": positive, "train_max_target_end": fold.train_max_target_end.iloc[0], "embargo_cutoff": fold.embargo_cutoff.iloc[0]})
        row = {"candidate_id": candidate.candidate_id, "model_family": candidate.family, "params_json": json.dumps(candidate.params, sort_keys=True), **aggregate, "positive_direction_folds": positive_folds}
        row["predictive_gate_pass"] = predictive_gate(row)
        comparison_rows.append(row)
    return oof, pd.DataFrame(comparison_rows), pd.DataFrame(fold_rows), fit_count


def select_candidate(comparison: pd.DataFrame) -> tuple[pd.Series, bool]:
    eligible = comparison.loc[comparison.predictive_gate_pass].copy()
    pool = eligible if not eligible.empty else comparison.copy()
    # Predictive-only ordering; family complexity is the final tiebreaker.
    complexity = {"LogisticRegression": 0, "HistGradientBoostingClassifier": 1, "LightGBMClassifier": 2}
    pool["family_complexity"] = pool.model_family.map(complexity)
    selected = pool.sort_values(
        ["positive_direction_folds", "average_precision_lift", "top_decile_bad_asymmetry_lift", "auroc", "family_complexity"],
        ascending=[False, False, False, False, True],
    ).iloc[0]
    return selected, bool(selected.predictive_gate_pass)


def risk_deciles(selected: pd.DataFrame) -> pd.DataFrame:
    frame = selected.copy()
    frame["risk_decile"] = np.clip(np.ceil(frame.risk_percentile * 10), 1, 10).astype(int)
    return frame.groupby("risk_decile", sort=True).agg(
        observation_count=("ticker", "size"), bad_asymmetry_incidence=("bad_asymmetry_5d", "mean"),
        secondary_bad_severe_negative_incidence=("bad_severe_negative_5d", "mean"),
        mean_post_entry_5d_mae=("forward_5d_stock_mae", "mean"),
        mean_post_entry_5d_mfe=("forward_5d_stock_mfe", "mean"),
        mean_final_5d_return=("forward_5d_stock_return", "mean"),
    ).reset_index()


def winner_loser_capture(selected: pd.DataFrame, old_r3r: pd.DataFrame) -> pd.DataFrame:
    frame = selected.copy()
    if "old_r3r_risk_percentile" not in frame:
        old = old_r3r.loc[old_r3r.candidate_id.eq(R3R_REFERENCE_MODEL)].copy()
        old = old[["signal_date", "ticker", "risk_percentile"]].rename(columns={"risk_percentile": "old_r3r_risk_percentile"})
        frame = frame.merge(old, on=["signal_date", "ticker"], validate="one_to_one")
    rows: list[dict[str, Any]] = []
    for signal, percentile in [("R6_BAD_ASYMMETRY", "risk_percentile"), ("R3R_MAE", "old_r3r_risk_percentile")]:
        top = frame[percentile].ge(0.90)
        loss_contribution = float(-0.05 * frame.loc[top & frame.forward_5d_stock_return.lt(0), "forward_5d_stock_return"].sum())
        winner_contribution = float(0.05 * frame.loc[top & frame.forward_5d_stock_return.gt(0), "forward_5d_stock_return"].sum())
        row: dict[str, Any] = {"risk_signal": signal, "top_decile_count": int(top.sum()), "loss_contribution_in_top_decile": loss_contribution, "winner_contribution_in_top_decile": winner_contribution}
        for count in (50, 100):
            row[f"worst_{count}_capture"] = float(frame.nsmallest(count, "forward_5d_stock_return")[percentile].ge(0.90).mean())
            row[f"best_{count}_capture"] = float(frame.nlargest(count, "forward_5d_stock_return")[percentile].ge(0.90).mean())
        row["worst100_to_best100_capture_ratio"] = row["worst_100_capture"] / row["best_100_capture"] if row["best_100_capture"] > 0 else np.inf
        row["loss_to_winner_contribution_ratio"] = loss_contribution / winner_contribution if winner_contribution > 0 else np.inf
        rows.append(row)
    return pd.DataFrame(rows)


def scaling_attribution(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, column in [("R3_RAW_MAE_RISK_SCALING_A2", "r3_multiplier"), ("R6_BAD_ASYMMETRY_SCALING_A2", "r6_multiplier")]:
        removed = 0.05 * (1.0 - scored[column])
        contribution = removed * scored.forward_5d_stock_return
        avoided = float(-contribution.loc[scored.forward_5d_stock_return < 0].sum())
        sacrificed = float(contribution.loc[scored.forward_5d_stock_return > 0].sum())
        rows.append({"strategy": name, "gross_loss_avoided": avoided, "gross_winner_upside_sacrificed": sacrificed, "net_scaling_value": avoided - sacrificed, "loss_avoided_to_winner_sacrificed_ratio": avoided / sacrificed if sacrificed > 0 else np.inf})
    return pd.DataFrame(rows)


def portfolio_economics(scored: pd.DataFrame, positions: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    scored = scored.copy()
    scored["raw_multiplier"] = 1.0
    scored["stock_vol_multiplier"] = np.clip(R3.STOCK_VOL_TARGET / scored.REALIZED_VOL_20D, R3.STOCK_VOL_MIN_MULTIPLIER, 1.0)
    scored["r3_multiplier"] = R3.R1.direct_multiplier(scored.old_r3r_risk_percentile.to_numpy())
    scored["r6_multiplier"] = np.where(scored.risk_percentile.ge(R6_INTERVENTION_PERCENTILE), R6_INTERVENTION_MULTIPLIER, 1.0)
    definitions = [
        ("RAW_A2", "raw_multiplier"), ("STOCK_VOL_SCALING_A2", "stock_vol_multiplier"),
        ("R3_RAW_MAE_RISK_SCALING_A2", "r3_multiplier"), ("R6_BAD_ASYMMETRY_SCALING_A2", "r6_multiplier"),
    ]
    targets = {name: R3.target_maps(scored, column) for name, column in definitions}
    simulations = {name: R3.simulate(targets[name], positions)[0] for name, _ in definitions}
    scored["constant_multiplier"] = float(simulations["R6_BAD_ASYMMETRY_SCALING_A2"].target_exposure.mean())
    targets["CONSTANT_EXPOSURE_MATCHED_A2"] = R3.target_maps(scored, "constant_multiplier")
    simulations["CONSTANT_EXPOSURE_MATCHED_A2"] = R3.simulate(targets["CONSTANT_EXPOSURE_MATCHED_A2"], positions)[0]
    authoritative = daily.set_index("execution_date").reconstructed_daily_return.reindex(simulations["RAW_A2"].date)
    identity_error = float(np.max(np.abs(simulations["RAW_A2"].daily_return.to_numpy() - authoritative.to_numpy())))
    if identity_error > 1e-4 or authoritative.isna().any():
        raise RuntimeError("R6 raw A2 simulation identity failure")
    simulations["RAW_A2"] = simulations["RAW_A2"].copy()
    simulations["RAW_A2"]["daily_return"] = authoritative.to_numpy()
    order = ["RAW_A2", "CONSTANT_EXPOSURE_MATCHED_A2", "STOCK_VOL_SCALING_A2", "R3_RAW_MAE_RISK_SCALING_A2", "R6_BAD_ASYMMETRY_SCALING_A2"]
    metrics = pd.DataFrame([R3.strategy_row(name, simulations[name], R3.overlay_turnover(targets[name], targets["RAW_A2"])) for name in order])
    metrics["raw_identity_max_abs_error"] = identity_error
    return metrics, simulations


def fold_economics(simulations: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    useful_count = 0
    for fold_name, start, end in R3.FOLDS:
        values: dict[str, dict[str, float]] = {}
        for name, daily in simulations.items():
            window = daily.loc[daily.date.between(start, end)]
            values[name] = {**R3.R1.performance_metrics(window.daily_return), "mean_exposure": float(window.target_exposure.mean())}
        constant, r6 = values["CONSTANT_EXPOSURE_MATCHED_A2"], values["R6_BAD_ASYMMETRY_SCALING_A2"]
        useful = bool(r6["total_return"] >= constant["total_return"] - 0.02 and r6["sharpe"] >= constant["sharpe"] and (abs(r6["maximum_drawdown"]) < abs(constant["maximum_drawdown"]) or r6["expected_shortfall_5"] > constant["expected_shortfall_5"]))
        useful_count += int(useful)
        for name, metric in values.items():
            rows.append({"fold": fold_name, "strategy": name, **metric, "r6_useful_economic_direction": useful})
    return pd.DataFrame(rows), useful_count


def economic_values(metrics: pd.DataFrame) -> dict[str, float | bool]:
    by = metrics.set_index("strategy")
    raw, constant, r6 = by.loc["RAW_A2"], by.loc["CONSTANT_EXPOSURE_MATCHED_A2"], by.loc["R6_BAD_ASYMMETRY_SCALING_A2"]
    values: dict[str, float | bool] = {
        "RETURN_RETENTION_VS_RAW": float(r6.total_return / raw.total_return) if raw.total_return > 0 else np.nan,
        "MDD_REDUCTION_VS_RAW": float(1.0 - abs(r6.maximum_drawdown) / abs(raw.maximum_drawdown)),
        "ES5_IMPROVEMENT_VS_RAW": float(1.0 - abs(r6.expected_shortfall_5) / abs(raw.expected_shortfall_5)),
        "RETURN_VALUE_OVER_CONSTANT": float(r6.total_return - constant.total_return),
        "SHARPE_VALUE_OVER_CONSTANT": float(r6.sharpe - constant.sharpe),
        "MDD_VALUE_OVER_CONSTANT": float(abs(constant.maximum_drawdown) - abs(r6.maximum_drawdown)),
        "ES_VALUE_OVER_CONSTANT": float(r6.expected_shortfall_5 - constant.expected_shortfall_5),
    }
    values["MATERIALLY_BEATS_CONSTANT"] = bool(values["SHARPE_VALUE_OVER_CONSTANT"] >= 0.05 and (values["MDD_VALUE_OVER_CONSTANT"] >= 0.05 * abs(constant.maximum_drawdown) or values["ES_VALUE_OVER_CONSTANT"] >= 0.05 * abs(constant.expected_shortfall_5)) and values["RETURN_VALUE_OVER_CONSTANT"] >= -0.02)
    return values


def classify(predictive_pass: bool, metrics: pd.DataFrame | None, attribution: pd.DataFrame | None, captures: pd.DataFrame, useful_folds: int, integrity_failure: bool = False) -> tuple[str, dict[str, Any]]:
    if integrity_failure:
        return "E", {}
    if not predictive_pass or metrics is None or attribution is None:
        return "C", {"reason": "preregistered predictive gate failed; position rule not applied"}
    values = economic_values(metrics)
    attr = attribution.set_index("strategy")
    r3, r6 = attr.loc["R3_RAW_MAE_RISK_SCALING_A2"], attr.loc["R6_BAD_ASYMMETRY_SCALING_A2"]
    capture = captures.set_index("risk_signal")
    c3, c6 = capture.loc["R3R_MAE"], capture.loc["R6_BAD_ASYMMETRY"]
    balance = bool(
        r6.loss_avoided_to_winner_sacrificed_ratio >= 1.25 * r3.loss_avoided_to_winner_sacrificed_ratio
        and c6.worst100_to_best100_capture_ratio >= 1.25 * c3.worst100_to_best100_capture_ratio
    )
    pass_a = bool(values["RETURN_RETENTION_VS_RAW"] >= 0.90 and (values["MDD_REDUCTION_VS_RAW"] >= 0.10 or values["ES5_IMPROVEMENT_VS_RAW"] >= 0.15) and values["MATERIALLY_BEATS_CONSTANT"] and balance and useful_folds >= 4)
    pass_b = bool(values["RETURN_RETENTION_VS_RAW"] >= 0.85 and balance and useful_folds >= 3 and (values["SHARPE_VALUE_OVER_CONSTANT"] > 0 or values["MDD_VALUE_OVER_CONSTANT"] > 0 or values["ES_VALUE_OVER_CONSTANT"] > 0))
    destructive = bool(values["RETURN_RETENTION_VS_RAW"] < 0.75 or (values["RETURN_VALUE_OVER_CONSTANT"] < -0.10 and values["SHARPE_VALUE_OVER_CONSTANT"] < 0))
    values.update({"LOSER_WINNER_BALANCE_IMPROVEMENT_GATE": balance, "A_GATE_PASS": pass_a, "B_GATE_PASS": pass_b})
    return ("A" if pass_a else "B" if pass_b else "D" if destructive else "C"), values


def print_summary(summary: dict[str, Any]) -> None:
    keys = [
        "A2_STOCK_RISK_R6_STATUS", "A2_STOCK_RISK_R6_CLASSIFICATION", "BAD_ASYMMETRY_BASE_RATE",
        "REFERENCE_MODEL", "OOF_AUROC", "OOF_AVERAGE_PRECISION", "TOP_DECILE_BAD_ASYMMETRY_LIFT", "POSITIVE_DIRECTION_FOLDS",
        "TOP_DECILE_WORST100_CAPTURE", "TOP_DECILE_BEST100_CAPTURE", "RAW_A2_RETURN", "CONSTANT_RETURN", "STOCK_VOL_RETURN", "R3_RETURN", "R6_RETURN",
        "RAW_A2_MDD", "CONSTANT_MDD", "R6_MDD", "RAW_A2_ES5", "CONSTANT_ES5", "R6_ES5",
        "R6_RETURN_RETENTION", "R6_MDD_REDUCTION", "R6_ES5_IMPROVEMENT", "R6_GROSS_LOSS_AVOIDED",
        "R6_GROSS_WINNER_UPSIDE_SACRIFICED", "R6_NET_SCALING_VALUE", "R6_USEFUL_ECONOMIC_FOLDS",
        "TRAINING_DATA_2026_COUNT", "HOLDOUT_FILE_READ_COUNT", "LOOKAHEAD_VIOLATION_COUNT", "NEW_RISK_R6_REPO_VIOLATION_COUNT", "NEXT_AUTHORIZED_STEP",
    ]
    for key in keys:
        value = summary.get(key, "NA")
        if isinstance(value, float) and np.isfinite(value):
            value = f"{value:.12g}"
        print(f"{key}={value}")


def run(output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"fail closed: output directory not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    panel, _, corrected, daily, positions, old_r3r, r3r_summary = load_inputs()
    oof, comparison, fold_predictive, fit_count = run_oof(panel, daily)
    selected_row, predictive_pass = select_candidate(comparison)
    selected = oof.loc[oof.candidate_id.eq(selected_row.candidate_id)].copy()
    old = old_r3r.loc[old_r3r.candidate_id.eq(R3R_REFERENCE_MODEL), ["signal_date", "ticker", "risk_percentile"]].rename(columns={"risk_percentile": "old_r3r_risk_percentile"})
    selected = selected.merge(old, on=["signal_date", "ticker"], validate="one_to_one")
    deciles = risk_deciles(selected)
    captures = winner_loser_capture(selected, old_r3r)

    metrics: pd.DataFrame | None = None
    fold_economic = pd.DataFrame()
    attribution: pd.DataFrame | None = None
    useful_folds = 0
    if predictive_pass:
        selected["r3_multiplier"] = R3.R1.direct_multiplier(selected.old_r3r_risk_percentile.to_numpy())
        selected["r6_multiplier"] = np.where(selected.risk_percentile.ge(R6_INTERVENTION_PERCENTILE), R6_INTERVENTION_MULTIPLIER, 1.0)
        attribution = scaling_attribution(selected)
        metrics, simulations = portfolio_economics(selected, positions, daily)
        fold_economic, useful_folds = fold_economics(simulations)

    guard = R3.R1.guard_audit()
    lookahead = int((panel.information_date >= panel.signal_date).sum() + (oof.train_max_target_end >= oof.embargo_cutoff).sum())
    integrity_failure = bool(
        lookahead or guard["new_risk_r1_repo_violation_count"] or len(corrected) != len(panel)
        or pd.to_datetime(panel.signal_date).ge(TRAINING_CUTOFF).any()
    )
    classification, gate_details = classify(predictive_pass, metrics, attribution, captures, useful_folds, integrity_failure)
    status = "VALID_PRE2026_R6_RESULT" + ("_WITH_PREEXISTING_REPO_GOVERNANCE_FAILURE" if guard["repository_guard_status"] != "PASS" else "")
    if integrity_failure:
        status = "FAIL_CLOSED_INTEGRITY"

    capture = captures.set_index("risk_signal").loc["R6_BAD_ASYMMETRY"]
    summary: dict[str, Any] = {
        "A2_STOCK_RISK_R6_STATUS": status, "A2_STOCK_RISK_R6_CLASSIFICATION": classification,
        "BAD_ASYMMETRY_BASE_RATE": float(selected.bad_asymmetry_5d.mean()), "REFERENCE_MODEL": selected_row.candidate_id,
        "OOF_AUROC": float(selected_row.auroc), "OOF_AVERAGE_PRECISION": float(selected_row.average_precision),
        "TOP_DECILE_BAD_ASYMMETRY_LIFT": float(selected_row.top_decile_bad_asymmetry_lift),
        "POSITIVE_DIRECTION_FOLDS": int(selected_row.positive_direction_folds),
        "TOP_DECILE_WORST100_CAPTURE": float(capture.worst_100_capture), "TOP_DECILE_BEST100_CAPTURE": float(capture.best_100_capture),
        "TRAINING_DATA_2026_COUNT": 0, "HOLDOUT_FILE_READ_COUNT": 0, "2026_USED_FOR_FEATURE_SELECTION_COUNT": 0,
        "2026_USED_FOR_PARAMETER_SELECTION_COUNT": 0, "2026_USED_FOR_THRESHOLD_SELECTION_COUNT": 0,
        "LOOKAHEAD_VIOLATION_COUNT": lookahead, "NEW_RISK_R6_REPO_VIOLATION_COUNT": guard["new_risk_r1_repo_violation_count"],
        "NEXT_AUTHORIZED_STEP": "STOP_AFTER_R6;DO_NOT_OPEN_2026", "predictive_gate_pass": predictive_pass,
        "economic_gate_details": gate_details,
    }
    if metrics is not None and attribution is not None:
        by = metrics.set_index("strategy")
        raw, constant, stock_vol, r3, r6 = [by.loc[name] for name in ["RAW_A2", "CONSTANT_EXPOSURE_MATCHED_A2", "STOCK_VOL_SCALING_A2", "R3_RAW_MAE_RISK_SCALING_A2", "R6_BAD_ASYMMETRY_SCALING_A2"]]
        attr = attribution.set_index("strategy").loc["R6_BAD_ASYMMETRY_SCALING_A2"]
        summary.update({
            "RAW_A2_RETURN": raw.total_return, "CONSTANT_RETURN": constant.total_return, "STOCK_VOL_RETURN": stock_vol.total_return, "R3_RETURN": r3.total_return, "R6_RETURN": r6.total_return,
            "RAW_A2_MDD": raw.maximum_drawdown, "CONSTANT_MDD": constant.maximum_drawdown, "R6_MDD": r6.maximum_drawdown,
            "RAW_A2_ES5": raw.expected_shortfall_5, "CONSTANT_ES5": constant.expected_shortfall_5, "R6_ES5": r6.expected_shortfall_5,
            "R6_RETURN_RETENTION": gate_details["RETURN_RETENTION_VS_RAW"], "R6_MDD_REDUCTION": gate_details["MDD_REDUCTION_VS_RAW"], "R6_ES5_IMPROVEMENT": gate_details["ES5_IMPROVEMENT_VS_RAW"],
            "R6_GROSS_LOSS_AVOIDED": attr.gross_loss_avoided, "R6_GROSS_WINNER_UPSIDE_SACRIFICED": attr.gross_winner_upside_sacrificed,
            "R6_NET_SCALING_VALUE": attr.net_scaling_value, "R6_USEFUL_ECONOMIC_FOLDS": useful_folds,
        })

    audit = {
        "summary": summary, "r3r_signal_path": str(R3R_OOF_PATH), "r3r_signal_sha256": R3R_SIGNAL_HASH,
        "r3r_reference_summary": r3r_summary, "execution_reference_coverage": len(corrected) / len(panel),
        "feature_count": len(R3.FEATURES), "feature_list": R3.FEATURES, "new_feature_count": 0,
        "model_family_count": len(set(item.family for item in CANDIDATES)), "total_candidate_config_count": len(CANDIDATES),
        "total_model_fit_count": fit_count, "oof_fold_count": len(R3.FOLDS), "random_cv_count": 0,
        "optuna_trial_count": 0, "threshold_search_count": 0, "exposure_mapping_search_count": 0,
        "primary_target": "MAE>=fold-training Q90 AND MFE<=fold-training Q50", "secondary_target_used_for_selection": False,
        "predictive_gate": {"positive_folds": PREDICTIVE_MIN_POSITIVE_FOLDS, "auroc": PREDICTIVE_MIN_AUROC, "average_precision_lift": PREDICTIVE_MIN_AP_LIFT, "top_decile_lift": PREDICTIVE_MIN_TOP_DECILE_LIFT},
        "position_rule_applied": predictive_pass, "repository_governance": guard,
    }
    R3.R1.write_parquet(output / "r6_oof_predictions.parquet", oof)
    R3.R1.write_csv(output / "r6_model_comparison.csv", comparison)
    R3.R1.write_csv(output / "r6_predictive_fold_metrics.csv", fold_predictive)
    R3.R1.write_csv(output / "r6_risk_deciles.csv", deciles)
    R3.R1.write_csv(output / "r6_winner_loser_capture.csv", captures)
    if metrics is not None and attribution is not None:
        R3.R1.write_csv(output / "r6_strategy_metrics.csv", metrics)
        R3.R1.write_csv(output / "r6_strategy_fold_metrics.csv", fold_economic)
        R3.R1.write_csv(output / "r6_scaling_attribution.csv", attribution)
    R3.R1.write_json(output / "r6_audit.json", audit)
    R3.R1.write_json(output / "r6_summary.json", summary)
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
        print("A2_STOCK_RISK_R6_STATUS=FAIL_CLOSED", file=sys.stderr)
        print("A2_STOCK_RISK_R6_CLASSIFICATION=E", file=sys.stderr)
        print(f"FAIL_CLOSED_REASON={type(exc).__name__}:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
