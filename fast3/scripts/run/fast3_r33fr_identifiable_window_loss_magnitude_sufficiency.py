#!/usr/bin/env python
"""FAST3 R33F-R identifiable-window existing-head loss sufficiency test."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
PARENT_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r33f_existing_head_loss_magnitude_sufficiency.py"
PARENT_ROOT = RESULTS_ROOT / "frozen/fast3/r33f_existing_head_loss_magnitude_sufficiency_20260811T040000Z"
PARENT_PREREGISTRATION = PARENT_ROOT / "FAST3_R33F_PREREGISTRATION_R1.json"
PARENT_SUMMARY = PARENT_ROOT / "FAST3_R33F_SUMMARY.json"
PARENT_PREREGISTRATION_SHA256 = "804c71c672a1ac563206b981cc1ba0eb6bf4674b567a31541899bed90f203503"
PARENT_SUMMARY_SHA256 = "9ed9b582f2d6d25eb297f8669caf682574cfb0989edcfa5f88d9a6bf705d1086"

PREDICTIVE_INPUTS = ("pred_t1", "pred_t5", "pred_t6")
CANDIDATE_MAPPINGS = ("M1_RIDGE", "M2_T5_T6_3X3", "M3_T1_T5_T6_2X2X2")
COMPLEXITY_PRIORITY = CANDIDATE_MAPPINGS
RIDGE_ALPHA = 1.0
M2_GRID = (3, 3)
M3_GRID = (2, 2, 2)
CALIBRATION_QUANTILES = 5
SOURCE_FOLD_MAP = {
    "OOF_2022": "OOF_2022",
    "OOF_2023": "OOF_2023",
    "OOF_2024": "OOF_2024",
    "OOF_2025": "OOF_2025_JAN",
}
EVALUATION_OUTER_FOLDS = tuple(SOURCE_FOLD_MAP)
EXCLUDED_OUTER_FOLD = "OOF_2021"
OUTER_FOLD_COUNT = 4
GATE_A = 0.15
GATE_B = 0.15
GATE_C_POSITIVE_FOLDS = 4
GATE_E = 0.02
GATE_F = 0.8
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"
ALLOWED_SCIENTIFIC_CLASSIFICATIONS = {
    "A_EXISTING_THREE_HEADS_SUFFICIENT_FOR_LOSS_MAGNITUDE_COMPONENT",
    "B_EXISTING_HEADS_RANK_LOSS_BUT_LEVEL_CALIBRATION_INSUFFICIENT",
    "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE",
}


class R33FRStop(RuntimeError):
    pass


def import_parent_runner() -> Any:
    spec = importlib.util.spec_from_file_location("r33fr_parent_r33f", PARENT_RUNNER)
    if spec is None or spec.loader is None:
        raise R33FRStop("STOP_R33FR_PARENT_RUNNER_IMPORT")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def assign_fixed_equal_count_bins(frame: pd.DataFrame, score: str, bins: int, output: str) -> pd.DataFrame:
    if bins != CALIBRATION_QUANTILES or len(frame) < bins:
        raise R33FRStop("STOP_R33FR_FIXED_CALIBRATION_BIN_CONTRACT")
    ordered = frame.sort_values(
        [score, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True],
        kind="mergesort",
    ).copy()
    ordered[output] = np.floor(np.arange(len(ordered)) * bins / len(ordered)).astype(int) + 1
    return ordered


def training_quantile_edges(training_values: pd.Series, bins: int) -> np.ndarray:
    if training_values.empty or bins < 2:
        raise R33FRStop("STOP_R33FR_INVALID_TRAINING_BIN_INPUT")
    return training_values.quantile(np.arange(1, bins) / bins, interpolation="linear").to_numpy(dtype=float)


def apply_training_edges(values: pd.Series, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(edges, values.to_numpy(dtype=float), side="right") + 1


def preregistration(run_started_at_utc: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R33FR_PREREGISTRATION_R1",
        "STATUS": "FROZEN_BEFORE_ANY_MAPPING_FIT",
        "PARENT_STUDY": "FAST3_R33F",
        "PARENT_STATUS": "STOPPED_DATA_OR_LINEAGE_INTEGRITY",
        "PARENT_R33F_PREREGISTRATION_SHA256": PARENT_PREREGISTRATION_SHA256,
        "PARENT_SCIENTIFIC_RESULTS_OBSERVED": False,
        "PARENT_MAPPING_METRICS_OBSERVED": False,
        "REPAIR_TYPE": "IDENTIFIABILITY_WINDOW_RESTRICTION",
        "REPAIR_REASON": "OOF_2021_HAS_NO_PRE_2021_FOLD_SAFE_T1_T5_T6_MAPPING_TRAINING_INPUTS",
        "RESEARCH_DESIGN_CHANGE_REASON": "IDENTIFIABILITY_ONLY",
        "RESEARCH_QUESTION": "Within identifiable OOF_2022-OOF_2025, are frozen T1/T5/T6 sufficient for conditional loser loss magnitude?",
        "EXCLUDED_OUTER_FOLD": EXCLUDED_OUTER_FOLD,
        "OOF_2021_INCLUDED": False,
        "OOF_2021_EXCLUSION_REASON": "NO_PRE_2021_FOLD_SAFE_THREE_HEAD_MAPPING_TRAINING_INPUTS",
        "EVALUATION_OUTER_FOLDS": list(EVALUATION_OUTER_FOLDS),
        "SOURCE_FOLD_MAP": SOURCE_FOLD_MAP,
        "OUTER_FOLD_COUNT": OUTER_FOLD_COUNT,
        "EXPANDING_WINDOW_RULE": "mapping training rows have frozen OOF T1/T5/T6 and decision_timestamp_utc strictly before outer-fold information_cutoff",
        "STRICT_TEMPORAL_ASSERTION": "max(mapping_training_decision_timestamp) < min(mapping_evaluation_decision_timestamp)",
        "INPUT_FEATURES": list(PREDICTIVE_INPUTS),
        "NEW_RAW_FEATURE_COUNT": 0,
        "CANDIDATE_MAPPINGS": list(CANDIDATE_MAPPINGS),
        "LOSS_MAPPING_CANDIDATE_COUNT": 3,
        "M1": {"TYPE": "Ridge", "ALPHA": RIDGE_ALPHA, "TRAINING_ONLY_STANDARDIZATION": True, "INTERCEPT": True, "NEGATIVE_PREDICTION_CLIP": 0.0},
        "M2": {"GRID": "3x3", "INPUTS": ["pred_t5", "pred_t6"], "BOUNDARIES": "training-fold terciles", "CELL_VALUE": "training loser mean loss", "EMPTY_CELL_FALLBACK": "training loser global mean"},
        "M3": {"GRID": "2x2x2", "INPUTS": list(PREDICTIVE_INPUTS), "BOUNDARIES": "training-fold medians", "CELL_VALUE": "training loser mean loss", "EMPTY_CELL_FALLBACK": "training loser global mean"},
        "BASELINES": ["training-fold loser mean", "training-fold loser median"],
        "PRIMARY_COMPARATOR": "BETTER_CONSTANT_BASELINE_BY_OOF_MAE",
        "CALIBRATION_QUANTILES": CALIBRATION_QUANTILES,
        "DATE_BALANCED_DEFINITION": "Spearman across ET trading-date means of prediction and realized loss; identical to R33D/R33E date-mean definition",
        "SUFFICIENCY_GATES": {
            "A_POOLED_SPEARMAN_MIN": GATE_A,
            "B_DATE_BALANCED_SPEARMAN_MIN": GATE_B,
            "C_POSITIVE_FOLD_COUNT": "4_of_4",
            "C_NO_FOLD_SPEARMAN_AT_OR_BELOW": -0.05,
            "D_UP_AND_DOWN_STRICTLY_POSITIVE": True,
            "E_OOF_MAE_RELATIVE_IMPROVEMENT_MIN": GATE_E,
            "F_QUANTILE_MEAN_LOSS_SPEARMAN_MIN": GATE_F,
            "F_TOP_MEAN_LOSS_STRICTLY_GREATER_THAN_BOTTOM": True,
        },
        "FOLD_STABILITY_GATE_CHANGE_FROM_R33F": "4_OF_5_TO_4_OF_4",
        "FOLD_STABILITY_GATE_CHANGE_REASON": "OOF_2021_NON_IDENTIFIABLE",
        "SELECTION_RULE": "FIRST_PASS_BY_PREDECLARED_COMPLEXITY_ORDER",
        "COMPLEXITY_PRIORITY": list(COMPLEXITY_PRIORITY),
        "EXPECTED_MAPPING_FIT_COUNT": 12,
        "EXPECTED_MAPPING_PREDICT_CALL_COUNT": 12,
        "T5_ORIGINAL_TARGET_LINEAGE": "R33B_CONDITIONAL_LOSS_SEVERITY",
        "T5_HAS_STABLE_WINNER_RATE_ORDERING": True,
        "T5_IS_CALIBRATED_WIN_PROBABILITY": False,
        "HEAD_REPREDICTION_ALLOWED": False,
        "T7_MODEL_CREATED": False,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False,
        "FINAL_HOLDOUT_ROW_COUNT": 0,
        "SEARCH_AND_SIMULATION_COUNTS": {
            "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0,
            "INTERACTION_SEARCH_COUNT": 0, "BUCKET_SEARCH_COUNT": 0,
            "WEIGHT_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
            "EV_COMBINATION_SEARCH_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
            "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        },
        "RUN_STARTED_AT_UTC": run_started_at_utc,
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }


def validate_parent_and_lineage() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], Any]:
    if (
        not PARENT_PREREGISTRATION.is_file()
        or not PARENT_SUMMARY.is_file()
        or file_sha256(PARENT_PREREGISTRATION) != PARENT_PREREGISTRATION_SHA256
        or file_sha256(PARENT_SUMMARY) != PARENT_SUMMARY_SHA256
    ):
        raise R33FRStop("STOP_R33FR_PARENT_LINEAGE_INTEGRITY")
    parent_summary = read_json(PARENT_SUMMARY)
    if (
        parent_summary.get("FAST3_R33F_STATUS") != "STOPPED_DATA_OR_LINEAGE_INTEGRITY"
        or parent_summary.get("FAST3_R33F_CLASSIFICATION") is not None
        or parent_summary.get("LOSS_MAPPING_FIT_COUNT") != 0
        or parent_summary.get("LOSS_MAPPING_PREDICT_CALL_COUNT") != 0
        or any(parent_summary.get(f"{m}_GATE_STATUS") != "NOT_EVALUATED" for m in ("M1", "M2", "M3"))
    ):
        raise R33FRStop("STOP_R33FR_PARENT_LINEAGE_INTEGRITY")
    parent = import_parent_runner()
    frame, r33d_contract, r33b_contract = parent.validate_lineage()
    if set(PREDICTIVE_INPUTS) - set(frame.columns):
        raise R33FRStop("STOP_R33FR_THREE_HEAD_INPUT_INTEGRITY")
    return frame, r33d_contract, r33b_contract, parent


def recover_outer_fold_contract(frame: pd.DataFrame, r33d_contract: dict[str, Any]) -> list[dict[str, Any]]:
    records = r33d_contract.get("PER_FOLD_DIRECTION_COUNTS", [])
    audits: list[dict[str, Any]] = []
    for outer_fold, source_fold in SOURCE_FOLD_MAP.items():
        matches = [row for row in records if row.get("fold") == source_fold]
        cutoffs = {pd.Timestamp(row["information_cutoff"]) for row in matches}
        if len(matches) != 2 or {row.get("direction") for row in matches} != {"UP", "DOWN"} or len(cutoffs) != 1:
            raise R33FRStop("STOP_R33FR_OUTER_FOLD_CONTRACT_NOT_UNIQUELY_RECOVERABLE")
        cutoff = next(iter(cutoffs))
        evaluation = frame.loc[frame.fold.eq(source_fold)]
        training = frame.loc[frame.decision_timestamp_utc.lt(cutoff)]
        training_losers = training.loc[training.raw_net20.lt(0)]
        evaluation_losers = evaluation.loc[evaluation.raw_net20.lt(0)]
        if training_losers.empty or evaluation_losers.empty:
            raise R33FRStop("STOP_R33FR_EMPTY_IDENTIFIABLE_FOLD")
        train_max = training_losers.decision_timestamp_utc.max()
        eval_min = evaluation_losers.decision_timestamp_utc.min()
        if (
            not train_max < eval_min
            or training_losers.fold.eq(source_fold).any()
            or not training_losers.decision_timestamp_utc.lt(cutoff).all()
            or not evaluation.fold.eq(source_fold).all()
        ):
            raise R33FRStop("STOP_R33FR_TEMPORAL_OR_FOLD_LEAKAGE")
        audits.append({
            "outer_fold": outer_fold,
            "source_fold": source_fold,
            "information_cutoff": cutoff,
            "training_row_count": len(training),
            "training_loser_count": len(training_losers),
            "training_min_timestamp": training_losers.decision_timestamp_utc.min(),
            "training_max_timestamp": train_max,
            "evaluation_row_count": len(evaluation),
            "evaluation_loser_count": len(evaluation_losers),
            "evaluation_min_timestamp": eval_min,
            "evaluation_max_timestamp": evaluation_losers.decision_timestamp_utc.max(),
            "same_outer_fold_training_row_count": int(training_losers.fold.eq(source_fold).sum()),
            "strict_temporal_assertion_pass": True,
        })
    if tuple(row["outer_fold"] for row in audits) != EVALUATION_OUTER_FOLDS:
        raise R33FRStop("STOP_R33FR_OUTER_FOLD_IDENTITY")
    return audits


def ridge_mapping(training: pd.DataFrame, evaluation: pd.DataFrame) -> np.ndarray:
    x_train = training.loc[:, PREDICTIVE_INPUTS].to_numpy(dtype=float)
    x_eval = evaluation.loc[:, PREDICTIVE_INPUTS].to_numpy(dtype=float)
    center = x_train.mean(axis=0)
    scale = x_train.std(axis=0, ddof=0)
    if not np.isfinite(scale).all() or np.any(scale <= 0):
        raise R33FRStop("STOP_R33FR_RIDGE_STANDARDIZATION")
    model = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
    model.fit((x_train - center) / scale, training.loss_magnitude.to_numpy(dtype=float))
    return np.clip(model.predict((x_eval - center) / scale), 0.0, None)


def table_mapping(
    training: pd.DataFrame,
    evaluation: pd.DataFrame,
    features: tuple[str, ...],
    bins: tuple[int, ...],
) -> np.ndarray:
    if len(features) != len(bins):
        raise R33FRStop("STOP_R33FR_TABLE_MAPPING_CONTRACT")
    train_keys: list[np.ndarray] = []
    eval_keys: list[np.ndarray] = []
    for feature, bin_count in zip(features, bins, strict=True):
        edges = training_quantile_edges(training[feature], bin_count)
        train_keys.append(apply_training_edges(training[feature], edges))
        eval_keys.append(apply_training_edges(evaluation[feature], edges))
    train_key = pd.MultiIndex.from_arrays(train_keys)
    eval_key = pd.MultiIndex.from_arrays(eval_keys)
    cell_means = pd.Series(training.loss_magnitude.to_numpy(dtype=float), index=train_key).groupby(level=list(range(len(features)))).mean()
    fallback = float(training.loss_magnitude.mean())
    prediction = cell_means.reindex(eval_key).to_numpy(dtype=float)
    return np.where(np.isfinite(prediction), prediction, fallback)


def date_balanced_spearman(frame: pd.DataFrame, prediction: str) -> float | None:
    daily = frame.groupby("trading_date", sort=True, observed=True).agg(
        mean_prediction=(prediction, "mean"), mean_realized_loss=("loss_magnitude", "mean")
    )
    return safe_spearman(daily.mean_prediction, daily.mean_realized_loss)


def calibration_diagnostic(oof: pd.DataFrame, prediction: str, mapping: str) -> tuple[pd.DataFrame, float, float]:
    binned = assign_fixed_equal_count_bins(oof, prediction, CALIBRATION_QUANTILES, "quantile")
    rows = []
    for quantile, part in binned.groupby("quantile", sort=True, observed=True):
        rows.append({
            "record_type": "CALIBRATION_QUANTILE", "mapping": mapping,
            "group": f"Q{int(quantile)}", "ordinal": int(quantile), "count": len(part),
            "mean_prediction": float(part[prediction].mean()),
            "mean_realized_loss": float(part.loss_magnitude.mean()),
            "median_realized_loss": float(part.loss_magnitude.median()),
        })
    table = pd.DataFrame(rows)
    monotonicity = safe_spearman(table.ordinal, table.mean_realized_loss)
    if monotonicity is None or len(table) != CALIBRATION_QUANTILES:
        raise R33FRStop("STOP_R33FR_CALIBRATION_METRIC")
    spread = float(table.iloc[-1].mean_realized_loss - table.iloc[0].mean_realized_loss)
    return table, monotonicity, spread


def evaluate_mapping(
    oof: pd.DataFrame,
    prediction: str,
    mapping: str,
    baseline_prediction: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], pd.DataFrame]:
    actual = oof.loss_magnitude.to_numpy(dtype=float)
    predicted = oof[prediction].to_numpy(dtype=float)
    baseline = oof[baseline_prediction].to_numpy(dtype=float)
    mae = float(np.mean(np.abs(actual - predicted)))
    rmse = float(np.sqrt(np.mean(np.square(actual - predicted))))
    baseline_mae = float(np.mean(np.abs(actual - baseline)))
    relative_improvement = float((baseline_mae - mae) / baseline_mae)
    pooled = safe_spearman(predicted, actual)
    date_s = date_balanced_spearman(oof, prediction)
    if pooled is None or date_s is None:
        raise R33FRStop("STOP_R33FR_PRIMARY_METRIC")
    fold_rows: list[dict[str, Any]] = []
    fold_spearmans: list[float] = []
    for fold, part in oof.groupby("outer_fold", sort=False, observed=True):
        fold_actual = part.loss_magnitude.to_numpy(dtype=float)
        fold_pred = part[prediction].to_numpy(dtype=float)
        fold_base = part[baseline_prediction].to_numpy(dtype=float)
        fold_mae = float(np.mean(np.abs(fold_actual - fold_pred)))
        fold_base_mae = float(np.mean(np.abs(fold_actual - fold_base)))
        fold_s = safe_spearman(fold_pred, fold_actual)
        if fold_s is None:
            raise R33FRStop("STOP_R33FR_FOLD_METRIC")
        fold_spearmans.append(fold_s)
        fold_rows.append({
            "record_type": "FOLD", "mapping": mapping, "group": fold, "count": len(part),
            "mae": fold_mae, "mae_relative_improvement": (fold_base_mae - fold_mae) / fold_base_mae,
            "spearman": fold_s,
        })
    directions: dict[str, float] = {}
    direction_rows = []
    for direction, part in oof.groupby("head", sort=True, observed=True):
        direction_s = safe_spearman(part[prediction], part.loss_magnitude)
        if direction_s is None:
            raise R33FRStop("STOP_R33FR_DIRECTION_METRIC")
        direction_mae = float(np.mean(np.abs(part.loss_magnitude - part[prediction])))
        direction_baseline_mae = float(np.mean(np.abs(part.loss_magnitude - part[baseline_prediction])))
        directions[direction] = direction_s
        direction_rows.append({
            "record_type": "DIRECTION", "mapping": mapping, "group": direction, "count": len(part),
            "mae": direction_mae,
            "mae_relative_improvement": (direction_baseline_mae - direction_mae) / direction_baseline_mae,
            "spearman": direction_s,
        })
    calibration, quantile_s, spread = calibration_diagnostic(oof, prediction, mapping)
    gates = {
        "A": pooled >= GATE_A,
        "B": date_s >= GATE_B,
        "C": len(fold_spearmans) == OUTER_FOLD_COUNT and all(value > 0 for value in fold_spearmans) and all(value > -0.05 for value in fold_spearmans),
        "D": directions.get("UP", 0.0) > 0 and directions.get("DOWN", 0.0) > 0,
        "E": relative_improvement >= GATE_E,
        "F": quantile_s >= GATE_F and spread > 0,
    }
    result = {
        "mapping": mapping, "oof_mae": mae, "oof_rmse": rmse,
        "oof_mae_relative_improvement": relative_improvement, "oof_spearman": pooled,
        "date_balanced_spearman": date_s,
        "positive_spearman_fold_count": sum(value > 0 for value in fold_spearmans),
        "minimum_fold_spearman": min(fold_spearmans),
        "up_spearman": directions["UP"], "down_spearman": directions["DOWN"],
        "quantile_monotonicity": quantile_s, "top_minus_bottom_mean_loss": spread,
        "gate_components": gates, "gate_status": "PASS" if all(gates.values()) else "FAIL",
        "stable_ranking_A_to_D": all(gates[key] for key in ("A", "B", "C", "D")),
    }
    summary_row = {"record_type": "SUMMARY", "group": "OOF", **{k: v for k, v in result.items() if k != "gate_components"}}
    summary_row.update({f"gate_{key}": value for key, value in gates.items()})
    rows = [summary_row, *fold_rows, *direction_rows]
    return result, rows, calibration


def select_first_pass(results: dict[str, dict[str, Any]]) -> str | None:
    for mapping in COMPLEXITY_PRIORITY:
        if results.get(mapping, {}).get("gate_status") == "PASS":
            return mapping
    return None


def classify(results: dict[str, dict[str, Any]]) -> tuple[str, str, bool | str, str]:
    selected = select_first_pass(results)
    if selected is not None:
        return (
            "A_EXISTING_THREE_HEADS_SUFFICIENT_FOR_LOSS_MAGNITUDE_COMPONENT",
            "NO_NEW_LOSS_HEAD_REQUIRED", False,
            "PREREGISTER_THREE_HEAD_ECONOMIC_CALIBRATION",
        )
    if any(result["stable_ranking_A_to_D"] for result in results.values()):
        return (
            "B_EXISTING_HEADS_RANK_LOSS_BUT_LEVEL_CALIBRATION_INSUFFICIENT",
            "LOSS_MAGNITUDE_COMPONENT_NOT_CLOSED", "UNRESOLVED",
            "PREREGISTER_MINIMAL_NEW_LOSS_HEAD_NECESSITY_TEST",
        )
    return (
        "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE",
        "NEW_LOSS_MAGNITUDE_COMPONENT_JUSTIFIED_FOR_FUTURE_STUDY", True,
        "PREREGISTER_MINIMAL_T7_STUDY",
    )


def execute_mappings(frame: pd.DataFrame, audits: list[dict[str, Any]]) -> tuple[pd.DataFrame, int, int]:
    parts: list[pd.DataFrame] = []
    fit_count = 0
    predict_count = 0
    for audit in audits:
        cutoff = pd.Timestamp(audit["information_cutoff"])
        source_fold = audit["source_fold"]
        training = frame.loc[frame.decision_timestamp_utc.lt(cutoff) & frame.raw_net20.lt(0)].copy()
        evaluation = frame.loc[frame.fold.eq(source_fold) & frame.raw_net20.lt(0)].copy()
        training["loss_magnitude"] = training.raw_net20.abs()
        evaluation["loss_magnitude"] = evaluation.raw_net20.abs()
        if (
            training.empty or evaluation.empty
            or training[list(PREDICTIVE_INPUTS) + ["loss_magnitude"]].isna().any().any()
            or evaluation[list(PREDICTIVE_INPUTS) + ["loss_magnitude"]].isna().any().any()
            or training.fold.eq(source_fold).any()
            or not training.decision_timestamp_utc.max() < evaluation.decision_timestamp_utc.min()
        ):
            raise R33FRStop("STOP_R33FR_MAPPING_POPULATION_INTEGRITY")
        evaluation["outer_fold"] = audit["outer_fold"]
        evaluation["baseline_mean"] = float(training.loss_magnitude.mean())
        evaluation["baseline_median"] = float(training.loss_magnitude.median())
        evaluation["M1_prediction"] = ridge_mapping(training, evaluation)
        fit_count += 1
        predict_count += 1
        evaluation["M2_prediction"] = table_mapping(training, evaluation, ("pred_t5", "pred_t6"), M2_GRID)
        fit_count += 1
        predict_count += 1
        evaluation["M3_prediction"] = table_mapping(training, evaluation, PREDICTIVE_INPUTS, M3_GRID)
        fit_count += 1
        predict_count += 1
        parts.append(evaluation)
    oof = pd.concat(parts, ignore_index=True)
    if (
        fit_count != 12 or predict_count != 12 or oof.candidate_id.duplicated().any()
        or oof[["baseline_mean", "baseline_median", "M1_prediction", "M2_prediction", "M3_prediction"]].isna().any().any()
        or tuple(oof.outer_fold.drop_duplicates()) != EVALUATION_OUTER_FOLDS
    ):
        raise R33FRStop("STOP_R33FR_OOF_MAPPING_INTEGRITY")
    return oof, fit_count, predict_count


def compact_terminal_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R33FR_STATUS", "FAST3_R33FR_CLASSIFICATION", "FAST3_R33FR_DECISION",
        "PARENT_R33F_STATUS", "R33FR_REPAIR_TYPE", "R33FR_PREREGISTRATION_VERIFIED",
        "R33FR_PREREGISTRATION_SHA256", "OOF_2021_INCLUDED", "OOF_2021_EXCLUSION_REASON",
        "OUTER_FOLD_COUNT", "OUTER_FOLDS", "LOSER_SAMPLE_COUNT", "BASELINE_MEAN_MAE",
        "BASELINE_MEDIAN_MAE", "BETTER_CONSTANT_BASELINE",
    ]
    for prefix in ("M1", "M2", "M3"):
        keys.extend([
            f"{prefix}_OOF_MAE", f"{prefix}_OOF_MAE_RELATIVE_IMPROVEMENT", f"{prefix}_OOF_SPEARMAN",
            f"{prefix}_DATE_BALANCED_SPEARMAN", f"{prefix}_POSITIVE_SPEARMAN_FOLD_COUNT",
            f"{prefix}_UP_SPEARMAN", f"{prefix}_DOWN_SPEARMAN", f"{prefix}_QUANTILE_MONOTONICITY",
            f"{prefix}_GATE_STATUS",
        ])
    keys.extend([
        "SELECTED_EXISTING_HEAD_LOSS_MAPPING", "SELECTION_RULE", "NEW_LOSS_MAGNITUDE_HEAD_JUSTIFIED",
        "NEW_HEAD_COUNT", "T7_MODEL_CREATED", "T7_MODEL_FIT_COUNT", "T7_MODEL_PREDICT_COUNT",
        "NEW_RAW_FEATURE_COUNT", "NEW_TARGET_COUNT", "LOSS_MAPPING_CANDIDATE_COUNT",
        "LOSS_MAPPING_FIT_COUNT", "LOSS_MAPPING_PREDICT_CALL_COUNT", "HYPERPARAMETER_SEARCH_COUNT",
        "FEATURE_SEARCH_COUNT", "INTERACTION_SEARCH_COUNT", "BUCKET_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT",
        "THRESHOLD_SEARCH_COUNT", "EV_COMBINATION_SEARCH_COUNT", "TRADING_SIMULATION_COUNT",
        "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT", "FINAL_CONFIRMATION_DATA_USED",
        "FINAL_CONFIRMATION_DATA_LOADED", "FINAL_HOLDOUT_INSPECTED", "FINAL_HOLDOUT_ROW_COUNT",
        "FIRST_RUN_STATUS", "RERUN_COUNT", "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT",
        "RUN_ID_TIMESTAMP_SEMANTICS", "ANTI_BLOAT_STATUS", "PRIMARY_RESEARCH_INTERPRETATION", "NEXT_STAGE",
    ])
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
        raise R33FRStop("USE_--run")

    started = datetime.now(timezone.utc)
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"r33fr_identifiable_window_loss_magnitude_sufficiency_{timestamp}"
    frozen_root = RESULTS_ROOT / "frozen/fast3" / run_id
    scratch_root = RESULTS_ROOT / "scratch/fast3" / run_id
    if frozen_root.exists() or scratch_root.exists():
        raise R33FRStop("STOP_R33FR_OUTPUT_EXISTS")

    frame, r33d_contract, _, parent = validate_parent_and_lineage()
    audits = recover_outer_fold_contract(frame, r33d_contract)
    frozen_root.mkdir(parents=True)
    prereg_path = frozen_root / "FAST3_R33FR_PREREGISTRATION_R1.json"
    prereg = preregistration(started.isoformat())
    write_json(prereg_path, prereg)
    prereg_sha = file_sha256(prereg_path)
    if read_json(prereg_path) != prereg or prereg_sha is None:
        raise R33FRStop("STOP_R33FR_PREREGISTRATION_VERIFICATION")

    oof, fit_count, predict_count = execute_mappings(frame, audits)
    oof_expected = int(frame.loc[frame.fold.isin(SOURCE_FOLD_MAP.values()) & frame.raw_net20.lt(0)].shape[0])
    if len(oof) != oof_expected or not np.allclose(oof.loss_magnitude, oof.raw_net20.abs(), rtol=0, atol=0):
        raise R33FRStop("STOP_R33FR_LOSS_MAGNITUDE_RECONCILIATION")

    actual = oof.loss_magnitude.to_numpy(dtype=float)
    baseline_mean_mae = float(np.mean(np.abs(actual - oof.baseline_mean.to_numpy(dtype=float))))
    baseline_median_mae = float(np.mean(np.abs(actual - oof.baseline_median.to_numpy(dtype=float))))
    baseline_mean_rmse = float(np.sqrt(np.mean(np.square(actual - oof.baseline_mean.to_numpy(dtype=float)))))
    baseline_median_rmse = float(np.sqrt(np.mean(np.square(actual - oof.baseline_median.to_numpy(dtype=float)))))
    if baseline_mean_mae <= baseline_median_mae:
        better_baseline = "MEAN"
        baseline_column = "baseline_mean"
    else:
        better_baseline = "MEDIAN"
        baseline_column = "baseline_median"

    results: dict[str, dict[str, Any]] = {}
    metric_rows: list[dict[str, Any]] = []
    prediction_columns = {
        "M1_RIDGE": "M1_prediction", "M2_T5_T6_3X3": "M2_prediction",
        "M3_T1_T5_T6_2X2X2": "M3_prediction",
    }
    for mapping, prediction in prediction_columns.items():
        result, rows, calibration = evaluate_mapping(oof, prediction, mapping, baseline_column)
        results[mapping] = result
        metric_rows.extend(rows)
        metric_rows.extend(calibration.to_dict("records"))
    classification, decision, new_head_justified, next_stage = classify(results)
    selected = select_first_pass(results)
    if classification not in ALLOWED_SCIENTIFIC_CLASSIFICATIONS:
        raise R33FRStop("STOP_R33FR_CLASSIFICATION_ENUM")

    scratch_root.mkdir(parents=True)
    oof_path = scratch_root / "FAST3_R33FR_OOF_LOSS_MAPPING.parquet"
    oof_columns = [
        "candidate_id", "decision_timestamp_utc", "trading_date", "outer_fold", "fold", "head",
        "loss_magnitude", "pred_t1", "pred_t5", "pred_t6", "baseline_mean", "baseline_median",
        "M1_prediction", "M2_prediction", "M3_prediction",
    ]
    oof[oof_columns].to_parquet(oof_path, index=False)
    metrics_path = frozen_root / "FAST3_R33FR_MAPPING_METRICS.csv"
    pd.DataFrame(metric_rows).to_csv(metrics_path, index=False)
    summary_path = frozen_root / "FAST3_R33FR_SUMMARY.json"
    report_path = frozen_root / "FAST3_R33FR_REPORT.md"

    summary: dict[str, Any] = {
        "FAST3_R33FR_STATUS": "PASS",
        "FAST3_R33FR_CLASSIFICATION": classification,
        "FAST3_R33FR_DECISION": decision,
        "PARENT_STUDY": "FAST3_R33F", "PARENT_R33F_STATUS": "STOPPED_DATA_OR_LINEAGE_INTEGRITY",
        "PARENT_SCIENTIFIC_RESULTS_OBSERVED": False, "PARENT_MAPPING_METRICS_OBSERVED": False,
        "R33FR_REPAIR_TYPE": "IDENTIFIABILITY_WINDOW_RESTRICTION",
        "REPAIR_REASON": "OOF_2021_HAS_NO_PRE_2021_FOLD_SAFE_T1_T5_T6_MAPPING_TRAINING_INPUTS",
        "RESEARCH_DESIGN_CHANGE_REASON": "IDENTIFIABILITY_ONLY",
        "R33FR_PREREGISTRATION_VERIFIED": True, "R33FR_PREREGISTRATION_SHA256": prereg_sha,
        "PARENT_R33F_PREREGISTRATION_SHA256": PARENT_PREREGISTRATION_SHA256,
        "OOF_2021_INCLUDED": False,
        "OOF_2021_EXCLUSION_REASON": "NO_PRE_2021_FOLD_SAFE_THREE_HEAD_MAPPING_TRAINING_INPUTS",
        "OUTER_FOLD_COUNT": OUTER_FOLD_COUNT, "OUTER_FOLDS": ",".join(EVALUATION_OUTER_FOLDS),
        "FOLD_STABILITY_GATE_CHANGE_FROM_R33F": "4_OF_5_TO_4_OF_4",
        "FOLD_STABILITY_GATE_CHANGE_REASON": "OOF_2021_NON_IDENTIFIABLE",
        "OUTER_FOLD_TEMPORAL_AUDIT": audits,
        "LOSER_SAMPLE_COUNT": len(oof), "OOF_ROW_COUNT": len(oof),
        "OOF_UNIQUE_CANDIDATE_ID_COUNT": int(oof.candidate_id.nunique()),
        "OOF_DUPLICATE_COUNT": int(oof.candidate_id.duplicated().sum()),
        "OOF_MISSING_PREDICTION_COUNT": int(oof[list(prediction_columns.values())].isna().any(axis=1).sum()),
        "LOSS_MAGNITUDE_RECONCILIATION_STATUS": "PASS",
        "BASELINE_MEAN_MAE": baseline_mean_mae, "BASELINE_MEDIAN_MAE": baseline_median_mae,
        "BASELINE_MEAN_RMSE": baseline_mean_rmse, "BASELINE_MEDIAN_RMSE": baseline_median_rmse,
        "BETTER_CONSTANT_BASELINE": better_baseline,
        "BETTER_CONSTANT_BASELINE_BY_OOF_MAE": better_baseline,
        "SELECTED_EXISTING_HEAD_LOSS_MAPPING": selected,
        "SELECTION_RULE": "FIRST_PASS_BY_PREDECLARED_COMPLEXITY_ORDER",
        "NEW_LOSS_MAGNITUDE_HEAD_JUSTIFIED": new_head_justified,
        "T5_ORIGINAL_TARGET_LINEAGE": "R33B_CONDITIONAL_LOSS_SEVERITY",
        "T5_HAS_STABLE_WINNER_RATE_ORDERING": True,
        "T5_IS_CALIBRATED_WIN_PROBABILITY": False,
        "NEW_HEAD_COUNT": 0, "T7_MODEL_CREATED": False, "T7_MODEL_FIT_COUNT": 0, "T7_MODEL_PREDICT_COUNT": 0,
        "NEW_RAW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "LOSS_MAPPING_CANDIDATE_COUNT": 3, "LOSS_MAPPING_FIT_COUNT": fit_count,
        "LOSS_MAPPING_PREDICT_CALL_COUNT": predict_count,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0, "INTERACTION_SEARCH_COUNT": 0,
        "BUCKET_SEARCH_COUNT": 0, "WEIGHT_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "TRADING_SIMULATION_COUNT": 0, "EXECUTION_SIMULATION_COUNT": 0,
        "POSITION_SIZING_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "FIRST_RUN_STATUS": "PASS", "RERUN_COUNT": 0, "RERUN_REASON": None,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
        "RUN_ID": run_id, "RUN_STARTED_AT_UTC": started.isoformat(),
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": (
            "EXISTING_THREE_HEADS_SUFFICIENT_FOR_LOSS_MAGNITUDE_COMPONENT" if classification.startswith("A_")
            else "EXISTING_HEADS_RANK_LOSS_BUT_LEVEL_CALIBRATION_INSUFFICIENT" if classification.startswith("B_")
            else "EXISTING_THREE_HEADS_INSUFFICIENT_FOR_STABLE_LOSS_MAGNITUDE_INFORMATION"
        ),
        "NEXT_STAGE": next_stage,
        "REPORT_PATH": str(report_path), "SUMMARY_JSON_PATH": str(summary_path),
        "PREREGISTRATION_PATH": str(prereg_path), "MAPPING_METRICS_PATH": str(metrics_path),
        "OOF_MAPPING_PATH": str(oof_path),
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
    }
    for short, mapping in (("M1", "M1_RIDGE"), ("M2", "M2_T5_T6_3X3"), ("M3", "M3_T1_T5_T6_2X2X2")):
        result = results[mapping]
        summary.update({
            f"{short}_OOF_MAE": result["oof_mae"],
            f"{short}_OOF_RMSE": result["oof_rmse"],
            f"{short}_OOF_MAE_RELATIVE_IMPROVEMENT": result["oof_mae_relative_improvement"],
            f"{short}_OOF_SPEARMAN": result["oof_spearman"],
            f"{short}_DATE_BALANCED_SPEARMAN": result["date_balanced_spearman"],
            f"{short}_POSITIVE_SPEARMAN_FOLD_COUNT": result["positive_spearman_fold_count"],
            f"{short}_UP_SPEARMAN": result["up_spearman"], f"{short}_DOWN_SPEARMAN": result["down_spearman"],
            f"{short}_QUANTILE_MONOTONICITY": result["quantile_monotonicity"],
            f"{short}_TOP_MINUS_BOTTOM_MEAN_LOSS": result["top_minus_bottom_mean_loss"],
            f"{short}_GATE_COMPONENTS": result["gate_components"], f"{short}_GATE_STATUS": result["gate_status"],
        })
    write_json(summary_path, summary)
    temporal_lines = "\n".join(
        f"- {row['outer_fold']}: train losers {row['training_loser_count']} from {row['training_min_timestamp']} through {row['training_max_timestamp']}; evaluate losers {row['evaluation_loser_count']} from {row['evaluation_min_timestamp']} through {row['evaluation_max_timestamp']}."
        for row in audits
    )
    gate_lines = "\n".join(
        f"- {mapping}: {result['gate_status']}; gates {result['gate_components']}; MAE improvement {result['oof_mae_relative_improvement']:.6f}; pooled/date-balanced Spearman {result['oof_spearman']:.6f}/{result['date_balanced_spearman']:.6f}."
        for mapping, result in results.items()
    )
    report = f"""# FAST3 R33F-R — Identifiable-Window Existing-Head Loss-Magnitude Sufficiency

## Frozen repair

R33F-R changes only evaluation-window identifiability. OOF_2021 is excluded because no frozen T1/T5/T6 rows exist before its 2020-12-31 mapping cutoff. Parent R33F observed no mapping metrics and made no scientific classification. This is not a performance-driven redesign.

## Temporal audit

{temporal_lines}

Every mapping-training row is a historical frozen OOF loser strictly before the source fold information cutoff. Every fold satisfies `max(training timestamp) < min(evaluation timestamp)` and contains zero same-outer-fold training rows.

## Results

Fold-safe constant baseline MAE: mean `{baseline_mean_mae:.12f}`, median `{baseline_median_mae:.12f}`; comparator `{better_baseline}`.

{gate_lines}

Classification: `{classification}`. Decision: `{decision}`. Selected mapping by the frozen first-pass complexity order: `{selected}`. New loss head justified: `{new_head_justified}`. Next stage: `{next_stage}`.

T5 retains its original `R33B_CONDITIONAL_LOSS_SEVERITY` target lineage. R33E winner-rate ordering is not interpreted as calibrated win probability.

No T7, raw feature, target, hyperparameter/feature/bucket/weight/threshold search, EV combination, trading/execution simulation, position sizing, Final load, or holdout inspection occurred.
"""
    report_path.write_text(report, encoding="utf-8")

    parent_hashes_after = {
        PARENT_PREREGISTRATION: file_sha256(PARENT_PREREGISTRATION),
        PARENT_SUMMARY: file_sha256(PARENT_SUMMARY),
    }
    if (
        parent_hashes_after[PARENT_PREREGISTRATION] != PARENT_PREREGISTRATION_SHA256
        or parent_hashes_after[PARENT_SUMMARY] != PARENT_SUMMARY_SHA256
        or file_sha256(parent.THREE_HEAD_OOF) != parent.EXPECTED_SHA256[parent.THREE_HEAD_OOF]
    ):
        raise R33FRStop("STOP_R33FR_FROZEN_INPUT_MUTATED")
    compact_terminal_summary(summary)
    print(f"REPORT_PATH={report_path}")
    print(f"SUMMARY_JSON_PATH={summary_path}")
    print(f"OOF_MAPPING_PATH={oof_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33FRStop as exc:
        raise SystemExit(str(exc)) from exc
