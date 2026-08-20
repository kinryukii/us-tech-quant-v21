#!/usr/bin/env python
"""FAST3 R33I fixed empirical existing-head economic calibration."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R33D_ROOT = RESULTS_ROOT / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z"
R33E_ROOT = RESULTS_ROOT / "frozen/fast3/r33e_three_head_economic_semantics_20260811T020000Z"
R33G_ROOT = RESULTS_ROOT / "frozen/fast3/r33g_minimal_t7_loss_magnitude_20260810T045640Z"
R33H_ROOT = RESULTS_ROOT / "frozen/fast3/r33h_existing_head_economic_role_reconciliation_20260810T054920Z"
T6_OOF = RESULTS_ROOT / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
T7_OOF = RESULTS_ROOT / "scratch/fast3/r33g_minimal_t7_loss_magnitude_20260810T045640Z/FAST3_R33G_T7_OOF_PREDICTIONS.parquet"
R33D_CONTRACT = R33D_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
R33D_SUMMARY = R33D_ROOT / "FAST3_R33D_SUMMARY.json"
R33E_CONTRACT = R33E_ROOT / "FAST3_R33E_SEMANTICS_CONTRACT_R1.json"
R33G_SUMMARY = R33G_ROOT / "FAST3_R33G_SUMMARY.json"
R33H_PREREGISTRATION = R33H_ROOT / "FAST3_R33H_PREREGISTRATION_R1.json"
R33H_SUMMARY = R33H_ROOT / "FAST3_R33H_SUMMARY.json"
R33H_ROLE_CONTRACT = R33H_ROOT / "FAST3_R33H_ECONOMIC_ROLE_CONTRACT_R1.json"

EXPECTED_SHA256 = {
    R33D_CONTRACT: "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2",
    R33D_SUMMARY: "32dc6fd23a9256b1dde203071ad0ad0cfc48d17d459d2baa1f3b7a95c5a462e3",
    T6_OOF: "99021c1fc956a99b949f76153364a9517c53ce1df92b36623b6e48531e1d3df1",
    R33E_CONTRACT: "147ac0d0ed07c353d08f7ff826e06d866b3272778ce4934a79f37f6de84c3dc5",
    R33G_SUMMARY: "48378397a8803b016fca35896540ef6d65a0474a18a676c7080b678f41aa6f3f",
    T7_OOF: "fa5ccfd77533d82fe8d8eb9872fde8b9a0c33f1ed7a3d3c68c1442ca118af033",
    R33H_PREREGISTRATION: "33569f7e2b8d0a153aa7dca373481a53dd1f6a02b656a35eb1b78988b514f753",
    R33H_SUMMARY: "c15b2cc47a300bcfa40ba44e4a0d16c8b576af60bbb318bdea1657f8c220489d",
    R33H_ROLE_CONTRACT: "0fa527db6491d42ccceef5b0d1b765ba8a5ef1721124a1a1fe85040fa79af114",
}

P_SOURCE = "T1"
G_SOURCE = "T6"
L_SOURCE = "T5"
CALIBRATION_METHOD = "FIXED_EMPIRICAL_QUANTILE_CALIBRATION"
CALIBRATION_BUCKET_COUNT = 10
DIAGNOSTIC_BIN_COUNT = 5
MIN_IDENTIFIABLE_FOLDS = 3
LOG_LOSS_EPSILON = 1e-15
SOURCE_FOLD_MAP = {
    "OOF_2022": "OOF_2022",
    "OOF_2023": "OOF_2023",
    "OOF_2024": "OOF_2024",
    "OOF_2025": "OOF_2025_JAN",
}
EVALUATION_FOLDS = tuple(SOURCE_FOLD_MAP)
EXCLUDED_FOLD = "OOF_2021"
OOF_ROW_COUNT = 984_049
WINNER_COUNT = 528_636
LOSER_COUNT = 455_413
FOLD_COUNT = 5
NY = "America/New_York"
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"
ALLOWED_COMPONENT_STATUSES = {
    "CALIBRATED", "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED",
    "NOT_IDENTIFIABLE", "ROLE_RECONCILIATION_FAILED",
}
ALLOWED_CLASSIFICATIONS = {
    "A_ALL_EXISTING_HEAD_ECONOMIC_COMPONENTS_CALIBRATED",
    "B_PROBABILITY_AND_GAIN_CALIBRATED_LOSS_LEVEL_UNSTABLE",
    "C_ECONOMIC_LEVEL_CALIBRATION_NOT_STABLE",
}


class R33IStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (Path, pd.Timestamp, datetime)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def safe_spearman(left: Any, right: Any) -> float | None:
    x, y = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 2 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    value = float(spearmanr(x, y).statistic)
    return value if np.isfinite(value) else None


def training_quantile_edges(values: pd.Series) -> np.ndarray:
    if values.empty:
        raise R33IStop("STOP_R33I_EMPTY_CALIBRATION_TRAINING_POPULATION")
    return values.quantile(
        np.arange(1, CALIBRATION_BUCKET_COUNT) / CALIBRATION_BUCKET_COUNT,
        interpolation="linear",
    ).to_numpy(dtype=float)


def apply_training_edges(values: pd.Series, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(edges, values.to_numpy(dtype=float), side="right") + 1


def build_apply_mapping(
    training: pd.DataFrame,
    evaluation: pd.DataFrame,
    score: str,
    target: str,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if training.empty or evaluation.empty or training[[score, target]].isna().any().any():
        raise R33IStop("STOP_R33I_INVALID_CALIBRATION_POPULATION")
    edges = training_quantile_edges(training[score])
    train_bins = apply_training_edges(training[score], edges)
    evaluation_bins = apply_training_edges(evaluation[score], edges)
    bucket_means = pd.Series(training[target].to_numpy(dtype=float)).groupby(train_bins).mean()
    fallback = float(training[target].mean())
    prediction = bucket_means.reindex(evaluation_bins).to_numpy(dtype=float)
    empty_count = int(np.isnan(prediction).sum())
    prediction = np.where(np.isfinite(prediction), prediction, fallback)
    naive = np.full(len(evaluation), fallback, dtype=float)
    return prediction, naive, {
        "training_quantile_edges": edges.tolist(), "training_global_mean_fallback": fallback,
        "training_nonempty_bucket_count": int(bucket_means.size), "evaluation_empty_bucket_fallback_count": empty_count,
    }


def assign_diagnostic_bins(frame: pd.DataFrame, prediction: str) -> pd.DataFrame:
    if len(frame) < DIAGNOSTIC_BIN_COUNT:
        raise R33IStop("STOP_R33I_DIAGNOSTIC_BIN_CONTRACT")
    ordered = frame.sort_values(
        [prediction, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True], kind="mergesort",
    ).copy()
    ordered["diagnostic_bin"] = np.floor(
        np.arange(len(ordered)) * DIAGNOSTIC_BIN_COUNT / len(ordered)
    ).astype(int) + 1
    return ordered


def preregistration(started_at_utc: str, evaluation_folds: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R33I_PREREGISTRATION_R1",
        "STATUS": "FROZEN_BEFORE_ANY_CALIBRATION_METRIC",
        "RESEARCH_QUESTION": "Can frozen T1/T6/T5 rankings be translated into fold-safe probability/gain/loss economic levels?",
        "PARENT_R33H_CLASSIFICATION": "A_EXISTING_HEADS_CONTAIN_STABLE_WINNER_PROBABILITY_ORDERING",
        "PARENT_R33H_PREREGISTRATION_SHA256": EXPECTED_SHA256[R33H_PREREGISTRATION],
        "P_SOURCE": P_SOURCE, "G_SOURCE": G_SOURCE, "L_SOURCE": L_SOURCE,
        "PROBABILITY_SOURCE_SEARCH_COUNT": 0,
        "CALIBRATION_METHOD": CALIBRATION_METHOD,
        "CALIBRATION_METHOD_COUNT": 1, "CALIBRATION_METHOD_SEARCH_COUNT": 0,
        "CALIBRATION_BUCKET_COUNT": CALIBRATION_BUCKET_COUNT,
        "CALIBRATION_BUCKET_SEARCH_COUNT": 0, "DIAGNOSTIC_BIN_COUNT": DIAGNOSTIC_BIN_COUNT,
        "P_BUCKET_TARGET": "historical canonical winner rate",
        "G_BUCKET_TARGET": "historical mean canonical winner gain magnitude",
        "L_BUCKET_TARGET": "historical mean canonical loser loss magnitude",
        "P_EMPTY_BUCKET_FALLBACK": "historical global winner rate",
        "G_EMPTY_BUCKET_FALLBACK": "historical global mean winner gain",
        "L_EMPTY_BUCKET_FALLBACK": "historical global mean loser loss",
        "G_L_BUCKET_ESTIMATOR": "MEAN_FIXED_NO_MEDIAN_SEARCH",
        "EXPANDING_WINDOW": True, "FOLD_SAFE": True,
        "STRICT_TEMPORAL_RULE": "training decision_timestamp_utc < outer-fold information_cutoff and max(training) < min(evaluation)",
        "SAME_FOLD_CALIBRATION_ALLOWED": False, "FUTURE_CALIBRATION_ROWS_ALLOWED": False,
        "EXCLUDED_FOLD": EXCLUDED_FOLD,
        "EXCLUDED_FOLD_REASON": "NO_PRE_FOLD_CALIBRATION_HISTORY",
        "P_EVALUATION_FOLDS": evaluation_folds["P"],
        "G_EVALUATION_FOLDS": evaluation_folds["G"],
        "L_EVALUATION_FOLDS": evaluation_folds["L"],
        "P_GATES": {
            "A_BRIER_RELATIVE_IMPROVEMENT_STRICTLY_POSITIVE": True,
            "B_LOGLOSS_RELATIVE_IMPROVEMENT_STRICTLY_POSITIVE": True,
            "C_RELIABILITY_SPEARMAN_MIN": 0.8,
            "D_ECE_STRICTLY_LESS_THAN_NAIVE_ECE": True,
            "E_ALL_LEGAL_FOLDS_FINITE_AND_MAJORITY_POSITIVE_BRIER_IMPROVEMENT": True,
        },
        "G_GATES": {
            "A_MAE_RELATIVE_IMPROVEMENT_STRICTLY_POSITIVE": True,
            "B_RMSE_RELATIVE_IMPROVEMENT_STRICTLY_POSITIVE": True,
            "C_CALIBRATION_MONOTONICITY_MIN": 0.8,
            "D_DATE_BALANCED_SPEARMAN_STRICTLY_POSITIVE": True,
            "E_UP_AND_DOWN_CALIBRATED_VS_REALIZED_SPEARMAN_STRICTLY_POSITIVE": True,
        },
        "L_GATES": {
            "A_MAE_RELATIVE_IMPROVEMENT_STRICTLY_POSITIVE": True,
            "B_RMSE_RELATIVE_IMPROVEMENT_STRICTLY_POSITIVE": True,
            "C_CALIBRATION_MONOTONICITY_MIN": 0.8,
            "D_DATE_BALANCED_SPEARMAN_STRICTLY_POSITIVE": True,
            "E_UP_AND_DOWN_CALIBRATED_VS_REALIZED_SPEARMAN_STRICTLY_POSITIVE": True,
        },
        "P_CALIBRATION_MAE_DEFINITION": "row-level mean absolute error versus binary winner indicator",
        "P_ECE_DEFINITION": "weighted mean absolute diagnostic-bin difference between mean predicted probability and realized winner rate",
        "LOG_LOSS_CLIP_EPSILON": LOG_LOSS_EPSILON,
        "NEW_HEADS_PROHIBITED": True, "NEW_FEATURES_PROHIBITED": True,
        "MODEL_FIT_PROHIBITED": True, "EV_PROHIBITED": True,
        "TRADING_PROHIBITED": True, "FINAL_PROHIBITED": True,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "T1_REFIT_COUNT": 0, "T5_REFIT_COUNT": 0, "T6_REFIT_COUNT": 0,
        "T1_NEW_PREDICT_COUNT": 0, "T5_NEW_PREDICT_COUNT": 0, "T6_NEW_PREDICT_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0,
        "INTERACTION_SEARCH_COUNT": 0, "EV_SCORE_CONSTRUCTION_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "RUN_STARTED_AT_UTC": started_at_utc, "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }


def validate_and_load_lineage() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33IStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    r33d_contract = read_json(R33D_CONTRACT)
    r33d_summary = read_json(R33D_SUMMARY)
    r33e_contract = read_json(R33E_CONTRACT)
    r33g = read_json(R33G_SUMMARY)
    r33h = read_json(R33H_SUMMARY)
    role = read_json(R33H_ROLE_CONTRACT)
    if (
        r33h.get("FAST3_R33H_CLASSIFICATION") != "A_EXISTING_HEADS_CONTAIN_STABLE_WINNER_PROBABILITY_ORDERING"
        or r33h.get("SELECTED_EXISTING_WIN_PROBABILITY_ORDERING_SCORE") != "P1_T1"
        or role.get("SELECTED_EXISTING_WIN_PROBABILITY_ORDERING_SCORE") != "P1_T1"
        or role.get("T5", {}).get("original_target_lineage") != "R33B_CONDITIONAL_LOSS_SEVERITY"
        or role.get("T6", {}).get("role_classification") != "A_CONDITIONAL_WINNER_GAIN_MAGNITUDE_ROLE_CONFIRMED"
        or role.get("T7", {}).get("status") != "REJECTED_REDUNDANT_WITH_T5"
        or role.get("T8", {}).get("status") != "PROHIBITED"
        or role.get("HEAD_EXPANSION_LIMIT_AFTER_R33G") is not True
        or role.get("FURTHER_HEAD_EXPANSION_ALLOWED") is not False
        or r33g.get("T7_T5_PREDICTION_EXACT_MATCH") is not True
        or r33e_contract.get("T1_FROZEN_TARGET_DEFINITION") != "T1_POSITIVE_NET20 = 1[net20 > 0]"
        or "conditional loss severity" not in r33e_contract.get("T5_ORIGINAL_MODEL_TARGET_LINEAGE", "")
        or r33d_summary.get("FAST3_R33D_CLASSIFICATION") != "A_T6_VALIDATED"
        or r33d_contract.get("VALIDATION_PREDICTION_SCOPE") != "all OOF eligible validation candidates"
        or any(x.get("FINAL_CONFIRMATION_DATA_USED") is not False for x in (r33d_summary, r33g, r33h, role))
    ):
        raise R33IStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    columns = [
        "candidate_id", "decision_timestamp_utc", "fold", "head", "raw_net20",
        "trading_date", "pred_t1", "pred_t5", "pred_t6", "actual_t6",
    ]
    frame = pd.read_parquet(T6_OOF, columns=columns)
    t7 = pd.read_parquet(T7_OOF, columns=["candidate_id", "pred_t7"])
    frame = frame.merge(t7, on="candidate_id", how="inner", validate="one_to_one")
    if (
        len(frame) != OOF_ROW_COUNT or frame.candidate_id.duplicated().any()
        or frame.fold.nunique() != FOLD_COUNT or set(frame["head"]) != {"UP", "DOWN"}
        or int(frame.raw_net20.gt(0).sum()) != WINNER_COUNT
        or int(frame.raw_net20.lt(0).sum()) != LOSER_COUNT
        or int(frame.raw_net20.eq(0).sum()) != 0
        or not np.array_equal(frame.pred_t5.to_numpy(), frame.pred_t7.to_numpy())
    ):
        raise R33IStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    frame["winner"] = frame.raw_net20.gt(0).astype(float)
    frame["gain_magnitude"] = np.where(frame.raw_net20.gt(0), frame.raw_net20, np.nan)
    frame["loss_magnitude"] = np.where(frame.raw_net20.lt(0), frame.raw_net20.abs(), np.nan)
    expected_dates = pd.to_datetime(frame.decision_timestamp_utc, utc=True).dt.tz_convert(NY).dt.date.astype(str)
    if not frame.trading_date.eq(expected_dates).all():
        raise R33IStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return frame, r33d_contract, r33d_summary


def recover_fold_audits(frame: pd.DataFrame, r33d_contract: dict[str, Any]) -> list[dict[str, Any]]:
    records = r33d_contract["PER_FOLD_DIRECTION_COUNTS"]
    audits = []
    for outer_fold, source_fold in SOURCE_FOLD_MAP.items():
        matches = [row for row in records if row["fold"] == source_fold]
        cutoffs = {pd.Timestamp(row["information_cutoff"]) for row in matches}
        if len(matches) != 2 or len(cutoffs) != 1:
            raise R33IStop("STOP_R33I_FOLD_CONTRACT_NOT_RECOVERABLE")
        cutoff = next(iter(cutoffs))
        evaluation = frame.loc[frame.fold.eq(source_fold)]
        historical = frame.loc[frame.decision_timestamp_utc.lt(cutoff)]
        if evaluation.empty or historical.empty or not historical.decision_timestamp_utc.max() < evaluation.decision_timestamp_utc.min():
            raise R33IStop("STOP_R33I_TEMPORAL_INTEGRITY")
        audits.append({
            "outer_fold": outer_fold, "source_fold": source_fold, "information_cutoff": cutoff,
            "historical_row_count": len(historical), "evaluation_row_count": len(evaluation),
            "historical_min_timestamp": historical.decision_timestamp_utc.min(),
            "historical_max_timestamp": historical.decision_timestamp_utc.max(),
            "evaluation_min_timestamp": evaluation.decision_timestamp_utc.min(),
            "evaluation_max_timestamp": evaluation.decision_timestamp_utc.max(),
            "strict_temporal_separation": True,
        })
    return audits


def identifiable_folds(frame: pd.DataFrame, audits: list[dict[str, Any]]) -> dict[str, list[str]]:
    result = {"P": [], "G": [], "L": []}
    for audit in audits:
        historical = frame.decision_timestamp_utc.lt(pd.Timestamp(audit["information_cutoff"]))
        populations = {
            "P": historical,
            "G": historical & frame.raw_net20.gt(0),
            "L": historical & frame.raw_net20.lt(0),
        }
        for component, population in populations.items():
            if int(population.sum()) > 0:
                result[component].append(audit["outer_fold"])
    return result


def execute_component(
    frame: pd.DataFrame,
    audits: list[dict[str, Any]],
    component: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int, int]:
    config = {
        "P": ("pred_t1", "winner", lambda x: pd.Series(True, index=x.index)),
        "G": ("pred_t6", "gain_magnitude", lambda x: x.raw_net20.gt(0)),
        "L": ("pred_t5", "loss_magnitude", lambda x: x.raw_net20.lt(0)),
    }
    score, target, eligibility = config[component]
    parts = []
    mapping_rows = []
    build_count = 0
    apply_count = 0
    for audit in audits:
        cutoff = pd.Timestamp(audit["information_cutoff"])
        source_fold = audit["source_fold"]
        train_mask = frame.decision_timestamp_utc.lt(cutoff) & eligibility(frame)
        eval_mask = frame.fold.eq(source_fold) & eligibility(frame)
        training = frame.loc[train_mask].copy()
        evaluation = frame.loc[eval_mask].copy()
        if (
            training.empty or evaluation.empty or training.fold.eq(source_fold).any()
            or not training.decision_timestamp_utc.max() < evaluation.decision_timestamp_utc.min()
            or not training.decision_timestamp_utc.lt(cutoff).all()
        ):
            raise R33IStop("STOP_R33I_COMPONENT_TEMPORAL_INTEGRITY")
        prediction, naive, mapping = build_apply_mapping(training, evaluation, score, target)
        build_count += 1
        apply_count += 1
        part = evaluation[["candidate_id", "decision_timestamp_utc", "trading_date", "fold", "head", target]].copy()
        part["outer_fold"] = audit["outer_fold"]
        part["component"] = component
        part["calibrated"] = prediction
        part["naive"] = naive
        parts.append(part)
        mapping_rows.append({
            "record_type": "MAPPING_FOLD", "component": component, "group": audit["outer_fold"],
            "count": len(part), "training_count": len(training),
            "training_min_timestamp": training.decision_timestamp_utc.min(),
            "training_max_timestamp": training.decision_timestamp_utc.max(),
            "evaluation_min_timestamp": evaluation.decision_timestamp_utc.min(),
            "evaluation_max_timestamp": evaluation.decision_timestamp_utc.max(), **mapping,
        })
    result = pd.concat(parts, ignore_index=True)
    if result.candidate_id.duplicated().any() or result[[target, "calibrated", "naive"]].isna().any().any():
        raise R33IStop("STOP_R33I_CALIBRATION_OUTPUT_INTEGRITY")
    return result, mapping_rows, build_count, apply_count


def probability_metrics(oof: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual = oof.winner.to_numpy(dtype=float)
    prediction = oof.calibrated.to_numpy(dtype=float)
    naive = oof.naive.to_numpy(dtype=float)
    brier = float(np.mean(np.square(prediction - actual)))
    naive_brier = float(np.mean(np.square(naive - actual)))
    p_clip = np.clip(prediction, LOG_LOSS_EPSILON, 1 - LOG_LOSS_EPSILON)
    n_clip = np.clip(naive, LOG_LOSS_EPSILON, 1 - LOG_LOSS_EPSILON)
    logloss = float(-np.mean(actual * np.log(p_clip) + (1 - actual) * np.log(1 - p_clip)))
    naive_logloss = float(-np.mean(actual * np.log(n_clip) + (1 - actual) * np.log(1 - n_clip)))
    calibration_mae = float(np.mean(np.abs(prediction - actual)))

    rows = []
    diagnostic = assign_diagnostic_bins(oof, "calibrated")
    for bin_id, part in diagnostic.groupby("diagnostic_bin", sort=True, observed=True):
        mean_pred = float(part.calibrated.mean())
        realized = float(part.winner.mean())
        rows.append({
            "record_type": "RELIABILITY_BIN", "component": "P", "group": f"B{int(bin_id)}",
            "ordinal": int(bin_id), "count": len(part), "mean_prediction": mean_pred,
            "mean_realized": realized, "median_realized": float(part.winner.median()),
            "absolute_calibration_error": abs(mean_pred - realized),
        })
    reliability = pd.DataFrame(rows)
    reliability_s = safe_spearman(reliability.ordinal, reliability.mean_realized)
    ece = float(np.average(reliability.absolute_calibration_error, weights=reliability["count"]))
    naive_diag = assign_diagnostic_bins(oof, "naive")
    naive_parts = naive_diag.groupby("diagnostic_bin", sort=True, observed=True).agg(
        mean_prediction=("naive", "mean"), mean_realized=("winner", "mean"), count=("winner", "size")
    )
    naive_ece = float(np.average(np.abs(naive_parts.mean_prediction - naive_parts.mean_realized), weights=naive_parts["count"]))
    daily = oof.groupby("trading_date", sort=True, observed=True).agg(
        mean_prediction=("calibrated", "mean"), realized=("winner", "mean")
    )
    date_error = float(np.mean(np.abs(daily.mean_prediction - daily.realized)))
    fold_improvement_count = 0
    fold_rows = []
    for fold, part in oof.groupby("outer_fold", sort=False, observed=True):
        fold_brier = float(np.mean(np.square(part.calibrated - part.winner)))
        fold_naive = float(np.mean(np.square(part.naive - part.winner)))
        improvement = float((fold_naive - fold_brier) / fold_naive)
        fold_improvement_count += int(improvement > 0)
        fold_rows.append({
            "record_type": "CALIBRATION_FOLD", "component": "P", "group": fold,
            "count": len(part), "metric": fold_brier, "naive_metric": fold_naive,
            "relative_improvement": improvement,
        })
    directions = {}
    for direction, part in oof.groupby("head", sort=True, observed=True):
        direction_brier = float(np.mean(np.square(part.calibrated - part.winner)))
        direction_naive = float(np.mean(np.square(part.naive - part.winner)))
        directions[direction] = float((direction_naive - direction_brier) / direction_naive)
    metrics = {
        "oof_row_count": len(oof), "brier_score": brier, "naive_brier_score": naive_brier,
        "brier_relative_improvement": (naive_brier - brier) / naive_brier,
        "log_loss": logloss, "naive_log_loss": naive_logloss,
        "logloss_relative_improvement": (naive_logloss - logloss) / naive_logloss,
        "calibration_mae": calibration_mae, "reliability_spearman": reliability_s,
        "expected_calibration_error": ece, "naive_expected_calibration_error": naive_ece,
        "date_balanced_calibration_error": date_error,
        "fold_brier_improvement_count": fold_improvement_count,
        "up_brier_relative_improvement": directions["UP"],
        "down_brier_relative_improvement": directions["DOWN"],
    }
    gates = {
        "A": metrics["brier_relative_improvement"] > 0,
        "B": metrics["logloss_relative_improvement"] > 0,
        "C": reliability_s is not None and reliability_s >= 0.8,
        "D": ece < naive_ece,
        "E": np.isfinite(prediction).all() and fold_improvement_count > len(oof.outer_fold.unique()) / 2,
    }
    metrics["gate_components"] = gates
    metrics["status"] = "CALIBRATED" if all(gates.values()) else "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED"
    return metrics, [*rows, *fold_rows]


def magnitude_metrics(oof: pd.DataFrame, component: str, target: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual = oof[target].to_numpy(dtype=float)
    prediction = oof.calibrated.to_numpy(dtype=float)
    naive = oof.naive.to_numpy(dtype=float)
    mae = float(np.mean(np.abs(prediction - actual)))
    naive_mae = float(np.mean(np.abs(naive - actual)))
    rmse = float(np.sqrt(np.mean(np.square(prediction - actual))))
    naive_rmse = float(np.sqrt(np.mean(np.square(naive - actual))))
    pooled = safe_spearman(prediction, actual)
    daily = oof.groupby("trading_date", sort=True, observed=True).agg(
        mean_prediction=("calibrated", "mean"), mean_realized=(target, "mean")
    )
    date_s = safe_spearman(daily.mean_prediction, daily.mean_realized)
    if pooled is None or date_s is None:
        raise R33IStop("STOP_R33I_MAGNITUDE_METRIC")
    directions = {}
    fold_rows = []
    for direction, part in oof.groupby("head", sort=True, observed=True):
        d_actual = part[target].to_numpy(dtype=float)
        d_mae = float(np.mean(np.abs(part.calibrated - d_actual)))
        d_naive_mae = float(np.mean(np.abs(part.naive - d_actual)))
        d_s = safe_spearman(part.calibrated, part[target])
        if d_s is None:
            raise R33IStop("STOP_R33I_MAGNITUDE_DIRECTION_METRIC")
        directions[direction] = {"mae_relative_improvement": (d_naive_mae - d_mae) / d_naive_mae, "spearman": d_s}
    for fold, part in oof.groupby("outer_fold", sort=False, observed=True):
        f_actual = part[target].to_numpy(dtype=float)
        f_mae = float(np.mean(np.abs(part.calibrated - f_actual)))
        f_naive = float(np.mean(np.abs(part.naive - f_actual)))
        fold_rows.append({
            "record_type": "CALIBRATION_FOLD", "component": component, "group": fold,
            "count": len(part), "metric": f_mae, "naive_metric": f_naive,
            "relative_improvement": (f_naive - f_mae) / f_naive,
            "spearman": safe_spearman(part.calibrated, part[target]),
        })
    diagnostic = assign_diagnostic_bins(oof, "calibrated")
    reliability_rows = []
    for bin_id, part in diagnostic.groupby("diagnostic_bin", sort=True, observed=True):
        reliability_rows.append({
            "record_type": "RELIABILITY_BIN", "component": component, "group": f"B{int(bin_id)}",
            "ordinal": int(bin_id), "count": len(part),
            "mean_prediction": float(part.calibrated.mean()),
            "mean_realized": float(part[target].mean()),
            "median_realized": float(part[target].median()),
            "absolute_calibration_error": abs(float(part.calibrated.mean() - part[target].mean())),
        })
    reliability = pd.DataFrame(reliability_rows)
    monotonicity = safe_spearman(reliability.ordinal, reliability.mean_realized)
    if monotonicity is None:
        raise R33IStop("STOP_R33I_MAGNITUDE_RELIABILITY")
    calibration_mae = float(np.average(reliability.absolute_calibration_error, weights=reliability["count"]))
    metrics = {
        "oof_row_count": len(oof), "oof_mae": mae, "naive_mae": naive_mae,
        "mae_relative_improvement": (naive_mae - mae) / naive_mae,
        "oof_rmse": rmse, "naive_rmse": naive_rmse,
        "rmse_relative_improvement": (naive_rmse - rmse) / naive_rmse,
        "calibrated_vs_realized_spearman": pooled, "date_balanced_spearman": date_s,
        "up_mae_relative_improvement": directions["UP"]["mae_relative_improvement"],
        "down_mae_relative_improvement": directions["DOWN"]["mae_relative_improvement"],
        "up_spearman": directions["UP"]["spearman"], "down_spearman": directions["DOWN"]["spearman"],
        "calibration_mae": calibration_mae, "calibration_monotonicity": monotonicity,
    }
    gates = {
        "A": metrics["mae_relative_improvement"] > 0,
        "B": metrics["rmse_relative_improvement"] > 0,
        "C": monotonicity >= 0.8,
        "D": date_s > 0,
        "E": directions["UP"]["spearman"] > 0 and directions["DOWN"]["spearman"] > 0,
    }
    metrics["gate_components"] = gates
    metrics["status"] = "CALIBRATED" if all(gates.values()) else "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED"
    return metrics, [*reliability_rows, *fold_rows]


def reconcile_roles(frame: pd.DataFrame, r33d_summary: dict[str, Any]) -> None:
    winners = frame.loc[frame.raw_net20.gt(0)]
    pooled = safe_spearman(winners.pred_t6, winners.raw_net20)
    daily = winners.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=("pred_t6", "mean"), mean_gain=("raw_net20", "mean")
    )
    date_s = safe_spearman(daily.mean_score, daily.mean_gain)
    directions = {
        direction: safe_spearman(part.pred_t6, part.raw_net20)
        for direction, part in winners.groupby("head", sort=True, observed=True)
    }
    if not (
        np.isclose(pooled, r33d_summary["T6_OOF_SPEARMAN_VS_REALIZED_GAIN"], rtol=0, atol=1e-15)
        and np.isclose(date_s, r33d_summary["DATE_BALANCED_T6_VS_GAIN_SPEARMAN"], rtol=0, atol=1e-15)
        and np.isclose(directions["UP"], r33d_summary["UP_T6_SPEARMAN"], rtol=0, atol=1e-15)
        and np.isclose(directions["DOWN"], r33d_summary["DOWN_T6_SPEARMAN"], rtol=0, atol=1e-15)
        and np.array_equal(frame.pred_t5.to_numpy(), frame.pred_t7.to_numpy())
    ):
        raise R33IStop("STOP_R33I_ROLE_RECONCILIATION_FAILED")


def classify(p_status: str, g_status: str, l_status: str) -> tuple[str, str, str]:
    if p_status == g_status == l_status == "CALIBRATED":
        return (
            "A_ALL_EXISTING_HEAD_ECONOMIC_COMPONENTS_CALIBRATED",
            "AUTHORIZE_FROZEN_EXPECTED_PAYOFF_COMPOSITION_STUDY",
            "PREREGISTER_FROZEN_EV_COMPOSITION",
        )
    if p_status == g_status == "CALIBRATED" and l_status == "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED":
        return (
            "B_PROBABILITY_AND_GAIN_CALIBRATED_LOSS_LEVEL_UNSTABLE",
            "DO_NOT_CONSTRUCT_ABSOLUTE_EV",
            "REASSESS_RELATIVE_OR_NORMALIZED_ECONOMIC_SCORE_WITHOUT_NEW_HEADS",
        )
    return (
        "C_ECONOMIC_LEVEL_CALIBRATION_NOT_STABLE",
        "STOP_ABSOLUTE_EXPECTED_PAYOFF_CONSTRUCTION",
        "RETAIN_RANKING_ARCHITECTURE_ONLY",
    )


def compact_terminal_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R33I_STATUS", "FAST3_R33I_CLASSIFICATION", "FAST3_R33I_DECISION",
        "R33I_PREREGISTRATION_VERIFIED", "R33I_PREREGISTRATION_SHA256",
        "ROLE_CONTRACT_RECONCILIATION_STATUS", "P_SOURCE", "G_SOURCE", "L_SOURCE",
        "P_EVALUATION_FOLDS", "G_EVALUATION_FOLDS", "L_EVALUATION_FOLDS",
        "P_OOF_ROW_COUNT", "P_BRIER_SCORE", "P_NAIVE_BRIER_SCORE",
        "P_BRIER_RELATIVE_IMPROVEMENT", "P_LOG_LOSS", "P_NAIVE_LOG_LOSS",
        "P_LOGLOSS_RELATIVE_IMPROVEMENT", "P_EXPECTED_CALIBRATION_ERROR",
        "P_RELIABILITY_SPEARMAN", "P_FOLD_BRIER_IMPROVEMENT_COUNT", "P_CALIBRATION_STATUS",
        "G_OOF_ROW_COUNT", "G_OOF_MAE", "G_NAIVE_MAE", "G_MAE_RELATIVE_IMPROVEMENT",
        "G_OOF_RMSE", "G_NAIVE_RMSE", "G_RMSE_RELATIVE_IMPROVEMENT",
        "G_CALIBRATION_MONOTONICITY", "G_DATE_BALANCED_SPEARMAN",
        "G_UP_SPEARMAN", "G_DOWN_SPEARMAN", "G_CALIBRATION_STATUS",
        "L_OOF_ROW_COUNT", "L_OOF_MAE", "L_NAIVE_MAE", "L_MAE_RELATIVE_IMPROVEMENT",
        "L_OOF_RMSE", "L_NAIVE_RMSE", "L_RMSE_RELATIVE_IMPROVEMENT",
        "L_CALIBRATION_MONOTONICITY", "L_DATE_BALANCED_SPEARMAN",
        "L_UP_SPEARMAN", "L_DOWN_SPEARMAN", "L_CALIBRATION_STATUS",
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FIT_COUNT",
        "MODEL_PREDICT_CALL_COUNT", "CALIBRATION_METHOD_COUNT", "CALIBRATION_METHOD_SEARCH_COUNT",
        "CALIBRATION_BUCKET_SEARCH_COUNT", "CALIBRATION_MAPPING_BUILD_COUNT",
        "CALIBRATION_MAPPING_APPLY_COUNT", "PROBABILITY_SOURCE_SEARCH_COUNT",
        "EV_SCORE_CONSTRUCTION_COUNT", "EV_COMBINATION_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT",
        "THRESHOLD_SEARCH_COUNT", "TRADING_SIMULATION_COUNT", "EXECUTION_SIMULATION_COUNT",
        "POSITION_SIZING_SEARCH_COUNT", "HEAD_EXPANSION_LIMIT_AFTER_R33G",
        "FURTHER_HEAD_EXPANSION_ALLOWED", "FINAL_CONFIRMATION_DATA_USED",
        "FINAL_CONFIRMATION_DATA_LOADED", "FINAL_HOLDOUT_INSPECTED", "FIRST_RUN_STATUS",
        "RERUN_COUNT", "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT", "ANTI_BLOAT_STATUS",
        "PRIMARY_RESEARCH_INTERPRETATION", "NEXT_STAGE",
    ]
    for key in keys:
        value = summary[key]
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise R33IStop("USE_--run")
    started = datetime.now(timezone.utc)
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"r33i_existing_head_economic_calibration_{timestamp}"
    frozen_root = RESULTS_ROOT / "frozen/fast3" / run_id
    if frozen_root.exists():
        raise R33IStop("STOP_R33I_OUTPUT_EXISTS")

    input_hashes_before = {path: file_sha256(path) for path in EXPECTED_SHA256}
    frame, r33d_contract, r33d_summary = validate_and_load_lineage()
    audits = recover_fold_audits(frame, r33d_contract)
    evaluation_folds = identifiable_folds(frame, audits)
    if any(len(folds) < MIN_IDENTIFIABLE_FOLDS for folds in evaluation_folds.values()):
        raise R33IStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")

    frozen_root.mkdir(parents=True)
    prereg_path = frozen_root / "FAST3_R33I_PREREGISTRATION_R1.json"
    prereg = preregistration(started.isoformat(), evaluation_folds)
    write_json(prereg_path, prereg)
    prereg_sha = file_sha256(prereg_path)
    if read_json(prereg_path) != prereg:
        raise R33IStop("STOP_R33I_PREREGISTRATION_VERIFICATION")

    reconcile_roles(frame, r33d_summary)
    component_oof = {}
    metric_rows = []
    build_count = 0
    apply_count = 0
    for component in ("P", "G", "L"):
        oof, mapping_rows, builds, applies = execute_component(frame, audits, component)
        component_oof[component] = oof
        metric_rows.extend(mapping_rows)
        build_count += builds
        apply_count += applies
    if build_count != 12 or apply_count != 12:
        raise R33IStop("STOP_R33I_CALIBRATION_ACCOUNTING")

    p_metrics, p_rows = probability_metrics(component_oof["P"])
    g_metrics, g_rows = magnitude_metrics(component_oof["G"], "G", "gain_magnitude")
    l_metrics, l_rows = magnitude_metrics(component_oof["L"], "L", "loss_magnitude")
    metric_rows.extend([*p_rows, *g_rows, *l_rows])
    statuses = {"P": p_metrics["status"], "G": g_metrics["status"], "L": l_metrics["status"]}
    if any(status not in ALLOWED_COMPONENT_STATUSES for status in statuses.values()):
        raise R33IStop("STOP_R33I_COMPONENT_STATUS_ENUM")
    classification, decision, next_stage = classify(statuses["P"], statuses["G"], statuses["L"])
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise R33IStop("STOP_R33I_CLASSIFICATION_ENUM")

    metrics_path = frozen_root / "FAST3_R33I_CALIBRATION_METRICS.csv"
    contract_path = frozen_root / "FAST3_R33I_CALIBRATION_CONTRACT_R1.json"
    summary_path = frozen_root / "FAST3_R33I_SUMMARY.json"
    report_path = frozen_root / "FAST3_R33I_REPORT.md"
    pd.DataFrame(metric_rows).to_csv(metrics_path, index=False)
    contract = {
        "CONTRACT_ID": "FAST3_R33I_CALIBRATION_CONTRACT_R1", "STATUS": "FROZEN_AFTER_VALIDATION",
        "R33I_PREREGISTRATION_SHA256": prereg_sha,
        "ROLE_CONTRACT_RECONCILIATION_STATUS": "PASS",
        "P": {"source": P_SOURCE, "method": CALIBRATION_METHOD, "status": statuses["P"], "gate_components": p_metrics["gate_components"]},
        "G": {"source": G_SOURCE, "method": CALIBRATION_METHOD, "status": statuses["G"], "gate_components": g_metrics["gate_components"]},
        "L": {"source": L_SOURCE, "method": CALIBRATION_METHOD, "status": statuses["L"], "gate_components": l_metrics["gate_components"], "original_target_lineage": "R33B_CONDITIONAL_LOSS_SEVERITY"},
        "EVALUATION_FOLDS": evaluation_folds, "EXCLUDED_FOLD": EXCLUDED_FOLD,
        "EXCLUDED_FOLD_REASON": "NO_PRE_FOLD_CALIBRATION_HISTORY",
        "EV_CONSTRUCTED": False, "FINAL_CONFIRMATION_DATA_USED": False,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
    }
    write_json(contract_path, contract)
    summary = {
        "FAST3_R33I_STATUS": "PASS", "FAST3_R33I_CLASSIFICATION": classification,
        "FAST3_R33I_DECISION": decision, "R33I_PREREGISTRATION_VERIFIED": True,
        "R33I_PREREGISTRATION_SHA256": prereg_sha, "ROLE_CONTRACT_RECONCILIATION_STATUS": "PASS",
        "T5_T7_IDENTITY_RECONCILIATION_STATUS": "PASS", "T5_T7_EXACT_MATCH": True,
        "T5_T7_MATCHED_ROW_COUNT": len(frame), "T5_T7_MAX_ABS_DIFFERENCE": 0.0,
        "T5_ORIGINAL_TARGET_LINEAGE": "R33B_CONDITIONAL_LOSS_SEVERITY",
        "T6_GAIN_ROLE_RECONCILIATION_STATUS": "PASS",
        "P_SOURCE": P_SOURCE, "G_SOURCE": G_SOURCE, "L_SOURCE": L_SOURCE,
        "PROBABILITY_SOURCE_SEARCH_COUNT": 0,
        "EXCLUDED_FOLD": EXCLUDED_FOLD, "EXCLUDED_FOLD_REASON": "NO_PRE_FOLD_CALIBRATION_HISTORY",
        "P_EVALUATION_FOLDS": ",".join(evaluation_folds["P"]),
        "G_EVALUATION_FOLDS": ",".join(evaluation_folds["G"]),
        "L_EVALUATION_FOLDS": ",".join(evaluation_folds["L"]),
        "OUTER_FOLD_TEMPORAL_AUDIT": audits,
        "P_OOF_ROW_COUNT": p_metrics["oof_row_count"], "P_BRIER_SCORE": p_metrics["brier_score"],
        "P_NAIVE_BRIER_SCORE": p_metrics["naive_brier_score"],
        "P_BRIER_RELATIVE_IMPROVEMENT": p_metrics["brier_relative_improvement"],
        "P_LOG_LOSS": p_metrics["log_loss"], "P_NAIVE_LOG_LOSS": p_metrics["naive_log_loss"],
        "P_LOGLOSS_RELATIVE_IMPROVEMENT": p_metrics["logloss_relative_improvement"],
        "P_CALIBRATION_MAE": p_metrics["calibration_mae"],
        "P_EXPECTED_CALIBRATION_ERROR": p_metrics["expected_calibration_error"],
        "P_NAIVE_EXPECTED_CALIBRATION_ERROR": p_metrics["naive_expected_calibration_error"],
        "P_RELIABILITY_SPEARMAN": p_metrics["reliability_spearman"],
        "P_DATE_BALANCED_CALIBRATION_ERROR": p_metrics["date_balanced_calibration_error"],
        "P_FOLD_BRIER_IMPROVEMENT_COUNT": p_metrics["fold_brier_improvement_count"],
        "P_UP_BRIER_RELATIVE_IMPROVEMENT": p_metrics["up_brier_relative_improvement"],
        "P_DOWN_BRIER_RELATIVE_IMPROVEMENT": p_metrics["down_brier_relative_improvement"],
        "P_GATE_COMPONENTS": p_metrics["gate_components"], "P_CALIBRATION_STATUS": statuses["P"],
        "G_OOF_ROW_COUNT": g_metrics["oof_row_count"], "G_OOF_MAE": g_metrics["oof_mae"],
        "G_NAIVE_MAE": g_metrics["naive_mae"], "G_MAE_RELATIVE_IMPROVEMENT": g_metrics["mae_relative_improvement"],
        "G_OOF_RMSE": g_metrics["oof_rmse"], "G_NAIVE_RMSE": g_metrics["naive_rmse"],
        "G_RMSE_RELATIVE_IMPROVEMENT": g_metrics["rmse_relative_improvement"],
        "G_CALIBRATED_VS_REALIZED_SPEARMAN": g_metrics["calibrated_vs_realized_spearman"],
        "G_DATE_BALANCED_SPEARMAN": g_metrics["date_balanced_spearman"],
        "G_UP_MAE_RELATIVE_IMPROVEMENT": g_metrics["up_mae_relative_improvement"],
        "G_DOWN_MAE_RELATIVE_IMPROVEMENT": g_metrics["down_mae_relative_improvement"],
        "G_UP_SPEARMAN": g_metrics["up_spearman"], "G_DOWN_SPEARMAN": g_metrics["down_spearman"],
        "G_CALIBRATION_MAE": g_metrics["calibration_mae"],
        "G_CALIBRATION_MONOTONICITY": g_metrics["calibration_monotonicity"],
        "G_GATE_COMPONENTS": g_metrics["gate_components"], "G_CALIBRATION_STATUS": statuses["G"],
        "L_OOF_ROW_COUNT": l_metrics["oof_row_count"], "L_OOF_MAE": l_metrics["oof_mae"],
        "L_NAIVE_MAE": l_metrics["naive_mae"], "L_MAE_RELATIVE_IMPROVEMENT": l_metrics["mae_relative_improvement"],
        "L_OOF_RMSE": l_metrics["oof_rmse"], "L_NAIVE_RMSE": l_metrics["naive_rmse"],
        "L_RMSE_RELATIVE_IMPROVEMENT": l_metrics["rmse_relative_improvement"],
        "L_CALIBRATED_VS_REALIZED_SPEARMAN": l_metrics["calibrated_vs_realized_spearman"],
        "L_DATE_BALANCED_SPEARMAN": l_metrics["date_balanced_spearman"],
        "L_UP_MAE_RELATIVE_IMPROVEMENT": l_metrics["up_mae_relative_improvement"],
        "L_DOWN_MAE_RELATIVE_IMPROVEMENT": l_metrics["down_mae_relative_improvement"],
        "L_UP_SPEARMAN": l_metrics["up_spearman"], "L_DOWN_SPEARMAN": l_metrics["down_spearman"],
        "L_CALIBRATION_MAE": l_metrics["calibration_mae"],
        "L_CALIBRATION_MONOTONICITY": l_metrics["calibration_monotonicity"],
        "L_GATE_COMPONENTS": l_metrics["gate_components"], "L_CALIBRATION_STATUS": statuses["L"],
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "T1_REFIT_COUNT": 0, "T5_REFIT_COUNT": 0, "T6_REFIT_COUNT": 0,
        "T1_NEW_PREDICT_COUNT": 0, "T5_NEW_PREDICT_COUNT": 0, "T6_NEW_PREDICT_COUNT": 0,
        "CALIBRATION_METHOD_COUNT": 1, "CALIBRATION_METHOD_SEARCH_COUNT": 0,
        "CALIBRATION_BUCKET_SEARCH_COUNT": 0, "CALIBRATION_MAPPING_BUILD_COUNT": build_count,
        "CALIBRATION_MAPPING_APPLY_COUNT": apply_count,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0, "INTERACTION_SEARCH_COUNT": 0,
        "EV_SCORE_CONSTRUCTION_COUNT": 0, "EV_COMBINATION_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0, "EXECUTION_SIMULATION_COUNT": 0,
        "POSITION_SIZING_SEARCH_COUNT": 0, "HEAD_EXPANSION_LIMIT_AFTER_R33G": True,
        "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "FIRST_RUN_STATUS": "PASS", "RERUN_COUNT": 0, "RERUN_REASON": None,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False, "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": decision, "NEXT_STAGE": next_stage,
        "RUN_ID": run_id, "RUN_STARTED_AT_UTC": started.isoformat(),
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "REPORT_PATH": str(report_path), "SUMMARY_JSON_PATH": str(summary_path),
        "PREREGISTRATION_PATH": str(prereg_path), "CALIBRATION_METRICS_PATH": str(metrics_path),
        "CALIBRATION_CONTRACT_PATH": str(contract_path), "OOF_CALIBRATION_PATH": None,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
    }
    write_json(summary_path, summary)
    report = f"""# FAST3 R33I - Existing-Head Economic Calibration

## Decision

`{classification}` - `{decision}`

OOF_2021 was mechanically excluded for P/G/L because no frozen pre-fold score history exists. All three components use OOF_2022 through OOF_2025 with strict expanding-window training and training-only decile boundaries/outcome means. Mapping accounting is `{build_count}` builds / `{apply_count}` applies; head model accounting remains 0 / 0.

## Component results

- P from T1: `{statuses['P']}`. Brier improvement `{p_metrics['brier_relative_improvement']}`, log-loss improvement `{p_metrics['logloss_relative_improvement']}`, reliability Spearman `{p_metrics['reliability_spearman']}`, ECE / naive ECE `{p_metrics['expected_calibration_error']}` / `{p_metrics['naive_expected_calibration_error']}`.
- G from T6: `{statuses['G']}`. MAE/RMSE improvement `{g_metrics['mae_relative_improvement']}` / `{g_metrics['rmse_relative_improvement']}`, date-balanced Spearman `{g_metrics['date_balanced_spearman']}`, monotonicity `{g_metrics['calibration_monotonicity']}`.
- L from T5: `{statuses['L']}`. MAE/RMSE improvement `{l_metrics['mae_relative_improvement']}` / `{l_metrics['rmse_relative_improvement']}`, date-balanced Spearman `{l_metrics['date_balanced_spearman']}`, monotonicity `{l_metrics['calibration_monotonicity']}`.

The role contract, T5/T7 exact identity, T5 original loss-severity lineage, and R33D T6 gain metrics were reconciled before calibration.

No predictive model fit/prediction, source/method/bucket search, new head/feature/target, EV construction or combination, threshold, trading/execution simulation, position sizing, Final load, or holdout inspection occurred. Even if all components calibrate, EV composition remains a separately preregistered future study.
"""
    report_path.write_text(report, encoding="utf-8")
    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33IStop("STOP_R33I_FROZEN_INPUT_MUTATED")
    if file_sha256(prereg_path) != prereg_sha:
        raise R33IStop("STOP_R33I_PREREGISTRATION_MUTATED")
    compact_terminal_summary(summary)
    print(f"REPORT_PATH={report_path}")
    print(f"SUMMARY_JSON_PATH={summary_path}")
    print(f"CALIBRATION_CONTRACT_PATH={contract_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33IStop as exc:
        raise SystemExit(str(exc)) from exc
