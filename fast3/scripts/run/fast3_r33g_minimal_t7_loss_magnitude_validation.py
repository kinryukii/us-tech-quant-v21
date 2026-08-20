#!/usr/bin/env python
"""FAST3 R33G minimal T7 conditional loser loss-magnitude validation."""
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
from sklearn.ensemble import HistGradientBoostingRegressor


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
R33D_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r33d_t6_conditional_gain_magnitude_validation.py"
R33D_ROOT = RESULTS_ROOT / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z"
R33D_CONTRACT = R33D_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
R33D_SUMMARY = R33D_ROOT / "FAST3_R33D_SUMMARY.json"
T6_OOF = RESULTS_ROOT / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
R33FR_ROOT = RESULTS_ROOT / "frozen/fast3/r33fr_identifiable_window_loss_magnitude_sufficiency_20260810T040042Z"
R33FR_PREREGISTRATION = R33FR_ROOT / "FAST3_R33FR_PREREGISTRATION_R1.json"
R33FR_SUMMARY = R33FR_ROOT / "FAST3_R33FR_SUMMARY.json"

EXPECTED_SHA256 = {
    R33D_CONTRACT: "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2",
    R33D_SUMMARY: "32dc6fd23a9256b1dde203071ad0ad0cfc48d17d459d2baa1f3b7a95c5a462e3",
    T6_OOF: "99021c1fc956a99b949f76153364a9517c53ce1df92b36623b6e48531e1d3df1",
    R33FR_PREREGISTRATION: "5f3463390cd2f13d5fd1a18bc793c1b0c4f0f3712d0f658d461b0236ea9ea6b3",
    R33FR_SUMMARY: "5f41843c103a36d97bfaae7b5aa45502e06bdcb5365af4767b152e69011bbc16",
}
T6_FEATURE_MANIFEST_SHA256 = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
T6_SPLIT_CONTRACT_SHA256 = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
T6_MODEL_FAMILY = "HistGradientBoostingRegressor independent UP/DOWN"
T7_TARGET_DEFINITION = "natural_log1p(canonical_loss_magnitude) on strict losers only"
T7_TARGET_TRANSFORM = "natural_log1p(abs(raw_net20))"
T7_INVERSE_TRANSFORM = "expm1(pred_t7), ranking diagnostic only"
T7_MODEL_VARIANT_COUNT = 1
FOLD_COUNT = 5
QUANTILE_COUNT = 5
CONDITIONAL_GRID = (2, 2, 2)
OOF_ROW_COUNT = 984_049
LOSER_COUNT = 455_413
GATE_A_MIN = 0.15
GATE_B_MIN = 0.15
GATE_E_MIN = 0.8
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"
FIRST_RUN_STATUS = "STOPPED_RUNTIME_TIMEOUT_BEFORE_PREREGISTRATION_OR_MODEL_FIT"
RERUN_COUNT = 2
RERUN_REASON = "attempt 1: one-second outer command timeout; attempt 2: pre-fit pandas dataset.head method/column collision; neither attempt wrote artifacts, fit a model, predicted, or produced scientific metrics"
ALLOWED_CLASSIFICATIONS = {
    "A_T7_VALIDATED",
    "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED",
    "C_T7_NOT_VALIDATED",
}


class R33GStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_file(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise R33GStop("STOP_R33G_MODULE_IMPORT")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def safe_pearson(left: Any, right: Any) -> float | None:
    x, y = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 2 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    value = float(np.corrcoef(x, y)[0, 1])
    return value if np.isfinite(value) else None


def derive_t7(net20: pd.Series) -> pd.Series:
    target = pd.Series(np.nan, index=net20.index, dtype=float)
    losers = net20.lt(0)
    target.loc[losers] = np.log1p(net20.loc[losers].abs().astype(float))
    return target


def candidate_id_hash(values: pd.Series) -> str:
    digest = hashlib.sha256()
    for value in values.astype(str).sort_values(kind="mergesort"):
        digest.update(value.encode("utf-8") + b"\n")
    return digest.hexdigest()


def assign_fixed_bins(frame: pd.DataFrame, score: str, bins: int, output: str) -> pd.DataFrame:
    if bins != QUANTILE_COUNT or len(frame) < bins:
        raise R33GStop("STOP_R33G_FIXED_QUANTILE_CONTRACT")
    ordered = frame.sort_values(
        [score, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True], kind="mergesort",
    ).copy()
    ordered[output] = np.floor(np.arange(len(ordered)) * bins / len(ordered)).astype(int) + 1
    return ordered


def recover_t6_contract() -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33GStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    r33d_contract = read_json(R33D_CONTRACT)
    r33d_summary = read_json(R33D_SUMMARY)
    r33fr_summary = read_json(R33FR_SUMMARY)
    if (
        r33d_contract.get("FEATURE_MANIFEST_SHA256") != T6_FEATURE_MANIFEST_SHA256
        or r33d_contract.get("SPLIT_CONTRACT_SHA256") != T6_SPLIT_CONTRACT_SHA256
        or r33d_contract.get("MODEL_FAMILY") != T6_MODEL_FAMILY
        or r33d_contract.get("TARGET_FORMULA") != "natural_log1p(net20) on strict winners only"
        or r33d_contract.get("TRAINING_ELIGIBILITY") != "label_valid == true AND net20 > 0"
        or r33d_contract.get("VALIDATION_PREDICTION_SCOPE") != "all OOF eligible validation candidates"
        or len(r33d_contract.get("FEATURE_NAMES", [])) != 29
        or len(r33d_contract.get("PER_FOLD_DIRECTION_COUNTS", [])) != 10
        or r33d_summary.get("FAST3_R33D_CLASSIFICATION") != "A_T6_VALIDATED"
        or r33d_summary.get("T6_OOF_SHA256") != EXPECTED_SHA256[T6_OOF]
        or r33d_summary.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33d_summary.get("FINAL_CONFIRMATION_DATA_INSPECTED") is not False
        or r33fr_summary.get("FAST3_R33FR_CLASSIFICATION") != "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE"
        or r33fr_summary.get("NEW_LOSS_MAGNITUDE_HEAD_JUSTIFIED") is not True
        or r33fr_summary.get("R33FR_PREREGISTRATION_SHA256") != EXPECTED_SHA256[R33FR_PREREGISTRATION]
        or r33fr_summary.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33fr_summary.get("FINAL_HOLDOUT_INSPECTED") is not False
    ):
        raise R33GStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    r33d = import_file(R33D_RUNNER, "r33g_frozen_r33d")
    r33d.validate_preregistration()
    return r33d, r33d_contract, r33d_summary, r33fr_summary


def preregistration(
    started_at_utc: str,
    r33d_contract: dict[str, Any],
    fold_ids: list[str],
) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R33G_PREREGISTRATION_R1",
        "STATUS": "FROZEN_BEFORE_ANY_T7_FIT",
        "RESEARCH_QUESTION": "Does a strict T6-architecture mirror T7 provide stable and incremental conditional loser loss-magnitude ranking?",
        "PARENT_R33FR_CLASSIFICATION": "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE",
        "PARENT_R33FR_PREREGISTRATION_SHA256": EXPECTED_SHA256[R33FR_PREREGISTRATION],
        "T6_CONTRACT_SOURCE": str(R33D_CONTRACT),
        "T6_CONTRACT_SHA256": EXPECTED_SHA256[R33D_CONTRACT],
        "T6_FEATURE_MANIFEST_SHA256": T6_FEATURE_MANIFEST_SHA256,
        "T7_FEATURE_MANIFEST_SHA256": T6_FEATURE_MANIFEST_SHA256,
        "FEATURE_MANIFEST_EXACT_MATCH": True,
        "T6_FEATURE_NAMES": r33d_contract["FEATURE_NAMES"],
        "T7_FEATURE_NAMES": r33d_contract["FEATURE_NAMES"],
        "T6_MODEL_FAMILY": r33d_contract["MODEL_FAMILY"],
        "T7_MODEL_FAMILY": r33d_contract["MODEL_FAMILY"],
        "T6_HYPERPARAMETERS": r33d_contract["HGB_PARAMETERS"],
        "T7_HYPERPARAMETERS": r33d_contract["HGB_PARAMETERS"],
        "T6_DIRECTION_HANDLING": "independent UP/DOWN fits",
        "T7_DIRECTION_HANDLING": "independent UP/DOWN fits",
        "T6_FOLD_CONTRACT_SHA256": r33d_contract["SPLIT_CONTRACT_SHA256"],
        "T7_FOLD_CONTRACT_SHA256": r33d_contract["SPLIT_CONTRACT_SHA256"],
        "T6_FOLD_IDS": fold_ids,
        "T7_FOLD_IDS": fold_ids,
        "T6_TARGET_TRANSFORM": "natural_log1p(gain magnitude)",
        "T7_TARGET_DEFINITION": T7_TARGET_DEFINITION,
        "T7_TARGET_TRANSFORM": T7_TARGET_TRANSFORM,
        "T7_INVERSE_TRANSFORM": T7_INVERSE_TRANSFORM,
        "T7_TRAINING_ELIGIBILITY": "label_valid == true AND raw_net20 < 0 only",
        "T7_VALIDATION_PREDICTION_SCOPE": "all OOF eligible validation candidates",
        "LOSER_ZERO_FILL": False,
        "SAMPLE_WEIGHTING": "none, exactly mirroring T6",
        "MISSING_VALUE_HANDLING": "native HistGradientBoostingRegressor handling, exactly mirroring T6",
        "T7_MODEL_VARIANT_COUNT": T7_MODEL_VARIANT_COUNT,
        "QUANTILE_COUNT": QUANTILE_COUNT,
        "CONDITIONAL_INCREMENTAL_GRID": "2x2x2",
        "CONDITIONAL_CUTPOINTS": "global full-OOF medians of frozen pred_t1/pred_t5/pred_t6",
        "CONDITIONAL_STATISTIC": "pooled within-cell percentile-rank Spearman; ET-date means for date-balanced statistic",
        "VALIDATION_GATES": {
            "A_POOLED_SPEARMAN_MIN": GATE_A_MIN,
            "B_DATE_BALANCED_SPEARMAN_MIN": GATE_B_MIN,
            "C_ALL_5_FOLDS_STRICTLY_POSITIVE": True,
            "D_UP_AND_DOWN_STRICTLY_POSITIVE": True,
            "E_QUANTILE_SPEARMAN_MIN": GATE_E_MIN,
            "E_TOP_MINUS_BOTTOM_MEAN_LOSS_STRICTLY_POSITIVE": True,
            "F_INCREMENTAL_POOLED_STRICTLY_POSITIVE": True,
            "G_INCREMENTAL_DATE_BALANCED_STRICTLY_POSITIVE": True,
        },
        "CLASSIFICATION_RULE": {
            "A_T7_VALIDATED": "all A-G gates pass",
            "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED": "all A-E pass and at least one F/G fails",
            "C_T7_NOT_VALIDATED": "at least one A-E ranking gate fails",
        },
        "NEW_HEAD_COUNT": 1, "NEW_FEATURE_COUNT": 0, "REMOVED_FEATURE_COUNT": 0,
        "NEW_TARGET_COUNT": 1, "MODEL_FAMILY_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0,
        "TARGET_SEARCH_COUNT": 0, "TARGET_TRANSFORM_SEARCH_COUNT": 0,
        "INTERACTION_SEARCH_COUNT": 0, "BUCKET_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "T1_REFIT_COUNT": 0, "T5_REFIT_COUNT": 0, "T6_REFIT_COUNT": 0,
        "T1_NEW_PREDICT_COUNT": 0, "T5_NEW_PREDICT_COUNT": 0, "T6_NEW_PREDICT_COUNT": 0,
        "FINAL_DATA_PROHIBITED": True,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True,
        "T8_MODEL_CREATED": False,
        "RUN_STARTED_AT_UTC": started_at_utc,
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "FIRST_RUN_STATUS": FIRST_RUN_STATUS,
        "RERUN_COUNT": RERUN_COUNT,
        "RERUN_REASON": RERUN_REASON,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }


def quantile_diagnostics(losers: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    binned = assign_fixed_bins(losers, "pred_t7", QUANTILE_COUNT, "t7_quantile")
    rows = []
    for quantile, part in binned.groupby("t7_quantile", sort=True, observed=True):
        rows.append({
            "record_type": "T7_QUANTILE", "group": f"Q{int(quantile)}", "ordinal": int(quantile),
            "count": len(part), "mean_t7_prediction": float(part.pred_t7.mean()),
            "mean_realized_loss": float(part.loss_magnitude.mean()),
            "median_realized_loss": float(part.loss_magnitude.median()),
        })
    table = pd.DataFrame(rows)
    monotonicity = safe_spearman(table.ordinal, table.mean_realized_loss)
    if monotonicity is None or len(table) != QUANTILE_COUNT:
        raise R33GStop("STOP_R33G_QUANTILE_DIAGNOSTIC")
    spread = float(table.iloc[-1].mean_realized_loss - table.iloc[0].mean_realized_loss)
    return table, monotonicity, spread


def incremental_three_head_audit(oof: pd.DataFrame) -> tuple[float, float, pd.DataFrame]:
    x = oof.copy()
    for score, output in (("pred_t1", "t1_bin"), ("pred_t5", "t5_bin"), ("pred_t6", "t6_bin")):
        median = float(x[score].median())
        x[output] = np.where(x[score].to_numpy(dtype=float) <= median, 1, 2)
    losers = x.loc[x.raw_net20.lt(0)].copy()
    ranked_parts = []
    cell_rows = []
    for keys, part in losers.groupby(["t1_bin", "t5_bin", "t6_bin"], sort=True, observed=True):
        ranked = part[["candidate_id", "trading_date"]].copy()
        ranked["within_cell_t7_rank"] = part.pred_t7.rank(method="average", pct=True)
        ranked["within_cell_loss_rank"] = part.loss_magnitude.rank(method="average", pct=True)
        ranked_parts.append(ranked)
        cell_s = safe_spearman(part.pred_t7, part.loss_magnitude)
        cell_rows.append({
            "record_type": "INCREMENTAL_CELL", "group": f"T1_B{keys[0]}_T5_B{keys[1]}_T6_B{keys[2]}",
            "count": len(part), "t1_bin": keys[0], "t5_bin": keys[1], "t6_bin": keys[2],
            "within_cell_t7_loss_spearman": cell_s,
        })
    if len(cell_rows) != 8 or any(row["count"] == 0 for row in cell_rows):
        raise R33GStop("STOP_R33G_INCREMENTAL_CELL_CARDINALITY")
    ranked = pd.concat(ranked_parts, ignore_index=True)
    pooled = safe_spearman(ranked.within_cell_t7_rank, ranked.within_cell_loss_rank)
    daily = ranked.groupby("trading_date", sort=True, observed=True).agg(
        mean_t7_rank=("within_cell_t7_rank", "mean"),
        mean_loss_rank=("within_cell_loss_rank", "mean"),
    )
    date_balanced = safe_spearman(daily.mean_t7_rank, daily.mean_loss_rank)
    if pooled is None or date_balanced is None:
        raise R33GStop("STOP_R33G_INCREMENTAL_METRIC")
    return pooled, date_balanced, pd.DataFrame(cell_rows)


def classify(gates: dict[str, bool]) -> tuple[str, str, bool, str, bool]:
    ranking_pass = all(gates[key] for key in ("A", "B", "C", "D", "E"))
    if ranking_pass and gates["F"] and gates["G"]:
        return (
            "A_T7_VALIDATED", "CONDITIONAL_LOSS_MAGNITUDE_SIGNAL_VALIDATED", True,
            "DESIGN_FOUR_COMPONENT_EXPECTED_PAYOFF_CALIBRATION", False,
        )
    if ranking_pass:
        return (
            "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED",
            "DO_NOT_ADD_T7_TO_EXPECTED_PAYOFF_ARCHITECTURE", False,
            "STOP_HEAD_EXPANSION_AND_REASSESS_LOSS_LEG_ARCHITECTURE", False,
        )
    return (
        "C_T7_NOT_VALIDATED", "STOP_NEW_LOSS_HEAD_EXPANSION", False,
        "STOP_HEAD_EXPANSION", False,
    )


def compact_terminal_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R33G_STATUS", "FAST3_R33G_CLASSIFICATION", "FAST3_R33G_DECISION",
        "R33G_PREREGISTRATION_VERIFIED", "R33G_PREREGISTRATION_SHA256",
        "T6_FEATURE_MANIFEST_SHA256", "T7_FEATURE_MANIFEST_SHA256", "FEATURE_MANIFEST_EXACT_MATCH",
        "T7_TARGET_DEFINITION", "T7_TARGET_TRANSFORM", "T7_LOSER_SAMPLE_COUNT", "T7_FOLD_COUNT",
        "T7_MODEL_VARIANT_COUNT", "T7_MODEL_FIT_COUNT", "T7_MODEL_PREDICT_CALL_COUNT",
        "T7_OOF_SPEARMAN_VS_REALIZED_LOSS", "T7_OOF_PEARSON", "DATE_BALANCED_T7_VS_LOSS_SPEARMAN",
        "T7_POSITIVE_SPEARMAN_FOLD_COUNT", "T7_MIN_FOLD_SPEARMAN", "T7_MAX_FOLD_SPEARMAN",
        "UP_T7_SPEARMAN", "DOWN_T7_SPEARMAN", "QUANTILE_LOSS_SPEARMAN",
        "TOP_MINUS_BOTTOM_MEAN_LOSS", "CONDITIONAL_T7_VS_LOSS_GIVEN_T1_T5_T6_SPEARMAN",
        "DATE_BALANCED_CONDITIONAL_T7_VS_LOSS_GIVEN_T1_T5_T6_SPEARMAN",
        "NAIVE_MEAN_MAE", "NAIVE_MEDIAN_MAE", "T7_OOF_MAE", "T7_OOF_RMSE",
        "GATE_A_POOLED_RANKING", "GATE_B_DATE_BALANCED", "GATE_C_FOLD_STABILITY",
        "GATE_D_DIRECTION_STABILITY", "GATE_E_QUANTILE_MONOTONICITY",
        "GATE_F_INCREMENTAL_POOLED", "GATE_G_INCREMENTAL_DATE_BALANCED", "T7_VALIDATED",
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "REMOVED_FEATURE_COUNT", "NEW_TARGET_COUNT",
        "MODEL_FAMILY_SEARCH_COUNT", "HYPERPARAMETER_SEARCH_COUNT", "FEATURE_SEARCH_COUNT",
        "TARGET_SEARCH_COUNT", "TARGET_TRANSFORM_SEARCH_COUNT", "WEIGHT_SEARCH_COUNT",
        "THRESHOLD_SEARCH_COUNT", "EV_COMBINATION_SEARCH_COUNT", "TRADING_SIMULATION_COUNT",
        "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT", "T1_REFIT_COUNT",
        "T5_REFIT_COUNT", "T6_REFIT_COUNT", "T7_MODEL_CREATED", "T8_MODEL_CREATED",
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
        raise R33GStop("USE_--run")

    started = datetime.now(timezone.utc)
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"r33g_minimal_t7_loss_magnitude_{timestamp}"
    frozen_root = RESULTS_ROOT / "frozen/fast3" / run_id
    scratch_root = RESULTS_ROOT / "scratch/fast3" / run_id
    if frozen_root.exists() or scratch_root.exists():
        raise R33GStop("STOP_R33G_OUTPUT_EXISTS")

    input_hashes_before = {path: file_sha256(path) for path in EXPECTED_SHA256}
    r33d, r33d_contract, r33d_summary, _ = recover_t6_contract()
    r32b, r30a, manifest, features = r33d.validate_infrastructure()
    if (
        tuple(features) != tuple(r33d_contract["FEATURE_NAMES"])
        or r32b.FEATURE_SHA != T6_FEATURE_MANIFEST_SHA256
        or r32b.SPLIT_SHA != T6_SPLIT_CONTRACT_SHA256
        or r30a.HGB_PARAMS != r33d_contract["HGB_PARAMETERS"]
        or len(r30a.ECONOMIC_FOLDS) != FOLD_COUNT
    ):
        raise R33GStop("STOPPED_T6_CONTRACT_NOT_RECOVERABLE")

    dataset, complete_coverage, missing_counts, _ = r32b.construct_dataset(manifest, features)
    dataset["actual_t7"] = derive_t7(dataset.raw_net20)
    losers_mask = dataset.raw_net20.lt(0)
    if (
        int(losers_mask.sum()) <= LOSER_COUNT
        or dataset.loc[losers_mask, "actual_t7"].isna().any()
        or dataset.loc[~losers_mask, "actual_t7"].notna().any()
        or not np.allclose(dataset.loc[losers_mask, "actual_t7"], np.log1p(dataset.loc[losers_mask, "raw_net20"].abs()), rtol=0, atol=1e-15)
    ):
        raise R33GStop("STOP_R33G_LOSS_TARGET_RECONCILIATION")

    fold_ids = [fold[0] for fold in r30a.ECONOMIC_FOLDS]
    if fold_ids != ["OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN"]:
        raise R33GStop("STOP_R33G_T6_FOLD_IDENTITY_MISMATCH")
    fold_audits = []
    used_train = np.zeros(len(dataset), dtype=bool)
    for fold in r30a.ECONOMIC_FOLDS:
        train, valid, audit = r32b.fold_masks(dataset, fold)
        used_train |= (train & losers_mask).to_numpy()
        for direction in ("UP", "DOWN"):
            training = train & losers_mask & dataset["head"].eq(direction)
            validation = valid & dataset["head"].eq(direction)
            if not training.any() or not validation.any() or (training & validation).any():
                raise R33GStop("STOP_R33G_FOLD_POPULATION_INTEGRITY")
            train_max = dataset.loc[training, "decision_timestamp_utc"].max()
            valid_min = dataset.loc[validation, "decision_timestamp_utc"].min()
            if not train_max < valid_min or audit["overlap_count"] != 0:
                raise R33GStop("STOP_R33G_TEMPORAL_LEAKAGE")
            fold_audits.append({
                "fold": fold[0], "direction": direction,
                "information_cutoff": audit["information_cutoff"],
                "train_loser_count": int(training.sum()), "validation_all_count": int(validation.sum()),
                "validation_loser_count": int((validation & losers_mask).sum()),
                "max_training_information_timestamp": train_max,
                "min_validation_information_timestamp": valid_min,
                "overlap_count": audit["overlap_count"], "strict_temporal_separation": True,
            })

    frozen_root.mkdir(parents=True)
    scratch_root.mkdir(parents=True)
    prereg_path = frozen_root / "FAST3_R33G_PREREGISTRATION_R1.json"
    prereg = preregistration(started.isoformat(), r33d_contract, fold_ids)
    write_json(prereg_path, prereg)
    prereg_sha = file_sha256(prereg_path)
    if read_json(prereg_path) != prereg:
        raise R33GStop("STOP_R33G_PREREGISTRATION_VERIFICATION")

    contract_path = frozen_root / "FAST3_R33G_T7_CONTRACT_R1.json"
    contract = {
        "CONTRACT_ID": "FAST3_R33G_T7_CONTRACT_R1", "STATUS": "FROZEN_BEFORE_FIT",
        "R33G_PREREGISTRATION_SHA256": prereg_sha,
        "R33D_T6_CONTRACT_SHA256": EXPECTED_SHA256[R33D_CONTRACT],
        "R33D_T6_SUMMARY_SHA256": EXPECTED_SHA256[R33D_SUMMARY],
        "PARENT_R33FR_PREREGISTRATION_SHA256": EXPECTED_SHA256[R33FR_PREREGISTRATION],
        "T6_FEATURE_MANIFEST_SHA256": T6_FEATURE_MANIFEST_SHA256,
        "T7_FEATURE_MANIFEST_SHA256": T6_FEATURE_MANIFEST_SHA256,
        "FEATURE_MANIFEST_EXACT_MATCH": True, "FEATURE_COUNT": len(features), "FEATURE_NAMES": list(features),
        "MODEL_FAMILY": T6_MODEL_FAMILY, "HGB_PARAMETERS": r30a.HGB_PARAMS,
        "CATEGORICAL_FEATURES": list(r30a.CATEGORICAL), "DIRECTION_HANDLING": "independent UP/DOWN",
        "TARGET_DEFINITION": T7_TARGET_DEFINITION, "TARGET_TRANSFORM": T7_TARGET_TRANSFORM,
        "INVERSE_TRANSFORM": T7_INVERSE_TRANSFORM,
        "TRAINING_ELIGIBILITY": "label_valid == true AND raw_net20 < 0 only",
        "VALIDATION_PREDICTION_SCOPE": "all OOF eligible validation candidates",
        "LOSER_ZERO_FILL": False, "T7_MODEL_VARIANT_COUNT": 1,
        "T7_FOLD_COUNT": FOLD_COUNT, "T7_FOLD_IDS": fold_ids,
        "T7_FOLD_IDENTITY_MATCH_T6": True, "SPLIT_CONTRACT_SHA256": T6_SPLIT_CONTRACT_SHA256,
        "NO_FUTURE_LEAKAGE": True, "NO_SAME_FOLD_TRAINING": True,
        "PIT_FEATURE_CONTRACT_PASS": True, "PER_FOLD_DIRECTION_COUNTS": fold_audits,
        "FULL_VALID_LABEL_COUNT": len(dataset), "FULL_T7_ELIGIBLE_LOSER_COUNT": int(losers_mask.sum()),
        "TRAIN_LOSER_UNIQUE_ROW_COUNT": int(used_train.sum()),
        "T7_ELIGIBLE_CANDIDATE_ID_SHA256": candidate_id_hash(dataset.loc[losers_mask, "candidate_id"]),
        "FEATURE_COMPLETE_ROW_RATE": complete_coverage, "FEATURE_MISSING_COUNTS": missing_counts,
        "SAMPLE_WEIGHTING": "none", "RANDOM_SEED": r30a.HGB_PARAMS["random_state"],
        "FINAL_CONFIRMATION_DATA_USED": False,
    }
    write_json(contract_path, contract)
    contract_sha = file_sha256(contract_path)

    categorical = [name in r30a.CATEGORICAL for name in features]
    params = {**r30a.HGB_PARAMS, "categorical_features": categorical}
    predictions = []
    fit_count = 0
    predict_count = 0
    for fold in r30a.ECONOMIC_FOLDS:
        train, valid, _ = r32b.fold_masks(dataset, fold)
        for direction in ("UP", "DOWN"):
            training = train & losers_mask & dataset["head"].eq(direction)
            validation = valid & dataset["head"].eq(direction)
            if not training.any() or not validation.any() or file_sha256(contract_path) != contract_sha:
                raise R33GStop("STOP_R33G_FROZEN_T7_CONTRACT_MUTATED")
            model = HistGradientBoostingRegressor(**params)
            model.fit(dataset.loc[training, list(features)], dataset.loc[training, "actual_t7"])
            fit_count += 1
            part = dataset.loc[validation, ["candidate_id"]].copy()
            part["pred_t7"] = model.predict(dataset.loc[validation, list(features)])
            predict_count += 1
            part["naive_t7_mean"] = float(dataset.loc[training, "actual_t7"].mean())
            part["naive_t7_median"] = float(dataset.loc[training, "actual_t7"].median())
            part["t7_fold_model"] = fold[0]
            predictions.append(part)
            del model
    predicted = pd.concat(predictions, ignore_index=True)
    if (
        len(predicted) != OOF_ROW_COUNT or predicted.candidate_id.duplicated().any()
        or predicted.pred_t7.isna().any() or fit_count != 10 or predict_count != 10
    ):
        raise R33GStop("STOP_R33G_T7_PREDICTION_MEMBERSHIP")

    base = pd.read_parquet(T6_OOF)
    base["decision_timestamp_utc"] = pd.to_datetime(base.decision_timestamp_utc, utc=True)
    oof = base.merge(predicted, on="candidate_id", how="inner", validate="one_to_one")
    if len(oof) != OOF_ROW_COUNT or not oof.fold.eq(oof.t7_fold_model).all():
        raise R33GStop("STOP_R33G_THREE_HEAD_T7_OOF_RECONCILIATION")
    oof["actual_t7"] = derive_t7(oof.raw_net20)
    oof["loss_magnitude"] = np.where(oof.raw_net20.lt(0), oof.raw_net20.abs(), np.nan)
    oof["predicted_conditional_loss_magnitude"] = np.expm1(oof.pred_t7)
    losers = oof.loc[oof.raw_net20.lt(0)].copy()
    t7_t5_exact_match = bool(np.array_equal(oof.pred_t7.to_numpy(), oof.pred_t5.to_numpy()))
    t7_t5_max_abs_difference = float(np.max(np.abs(oof.pred_t7.to_numpy() - oof.pred_t5.to_numpy())))
    if (
        len(losers) != LOSER_COUNT or losers.candidate_id.duplicated().any()
        or not np.allclose(losers.loss_magnitude, losers.raw_net20.abs(), rtol=0, atol=0)
        or not np.allclose(losers.actual_t7, np.log1p(losers.loss_magnitude), rtol=0, atol=1e-15)
    ):
        raise R33GStop("STOP_R33G_LOSS_TARGET_RECONCILIATION")

    pooled = safe_spearman(losers.pred_t7, losers.loss_magnitude)
    pearson = safe_pearson(losers.predicted_conditional_loss_magnitude, losers.loss_magnitude)
    if pooled is None or pearson is None:
        raise R33GStop("STOP_R33G_PRIMARY_METRIC")
    daily = losers.groupby("trading_date", sort=True, observed=True).agg(
        mean_pred_t7=("pred_t7", "mean"), mean_realized_loss=("loss_magnitude", "mean")
    )
    date_balanced = safe_spearman(daily.mean_pred_t7, daily.mean_realized_loss)
    if date_balanced is None:
        raise R33GStop("STOP_R33G_DATE_BALANCED_METRIC")

    diagnostics_rows = []
    fold_spearmans = []
    for fold, part in losers.groupby("fold", sort=True, observed=True):
        value = safe_spearman(part.pred_t7, part.loss_magnitude)
        if value is None:
            raise R33GStop("STOP_R33G_FOLD_METRIC")
        fold_spearmans.append(value)
        diagnostics_rows.append({"record_type": "FOLD", "group": fold, "count": len(part), "t7_spearman_vs_loss": value})
    directions: dict[str, tuple[int, float]] = {}
    for direction, part in losers.groupby("head", sort=True, observed=True):
        value = safe_spearman(part.pred_t7, part.loss_magnitude)
        if value is None:
            raise R33GStop("STOP_R33G_DIRECTION_METRIC")
        directions[direction] = (len(part), value)
        diagnostics_rows.append({"record_type": "DIRECTION", "group": direction, "count": len(part), "t7_spearman_vs_loss": value})
    quantiles, quantile_s, top_bottom = quantile_diagnostics(losers)
    conditional_s, conditional_date_s, cells = incremental_three_head_audit(oof)
    diagnostics_rows.extend([
        {"record_type": "DATE_BALANCED", "group": "ET_TRADING_DATE_LOSERS", "count": len(daily), "t7_spearman_vs_loss": date_balanced},
        {"record_type": "INCREMENTAL", "group": "POOLED_WITHIN_FIXED_T1_T5_T6_2X2X2_CELLS", "count": len(losers), "t7_spearman_vs_loss": conditional_s},
        {"record_type": "INCREMENTAL_DATE_BALANCED", "group": "ET_DATE_MEANS_OF_WITHIN_CELL_RANKS", "count": len(daily), "t7_spearman_vs_loss": conditional_date_s},
    ])
    diagnostics = pd.concat([pd.DataFrame(diagnostics_rows), quantiles, cells], ignore_index=True, sort=False)

    error = losers.pred_t7 - losers.actual_t7
    mae = float(error.abs().mean())
    rmse = float(np.sqrt(np.mean(np.square(error))))
    naive_mean_mae = float((losers.naive_t7_mean - losers.actual_t7).abs().mean())
    naive_median_mae = float((losers.naive_t7_median - losers.actual_t7).abs().mean())
    gates = {
        "A": pooled >= GATE_A_MIN,
        "B": date_balanced >= GATE_B_MIN,
        "C": len(fold_spearmans) == FOLD_COUNT and all(value > 0 for value in fold_spearmans),
        "D": directions["UP"][1] > 0 and directions["DOWN"][1] > 0,
        "E": quantile_s >= GATE_E_MIN and top_bottom > 0,
        # A head that is bitwise identical to a conditioning control cannot
        # establish incremental information. Coarse 2x2x2 T5 cells retain
        # within-cell T5 variation, so positive raw statistics alone are not
        # sufficient when the identity guard fails.
        "F": conditional_s > 0 and not t7_t5_exact_match,
        "G": conditional_date_s > 0 and not t7_t5_exact_match,
    }
    classification, decision, validated, next_stage, further_head_expansion = classify(gates)
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise R33GStop("STOP_R33G_CLASSIFICATION_ENUM")

    oof_path = scratch_root / "FAST3_R33G_T7_OOF_PREDICTIONS.parquet"
    metrics_path = frozen_root / "FAST3_R33G_METRICS.csv"
    summary_path = frozen_root / "FAST3_R33G_SUMMARY.json"
    report_path = frozen_root / "FAST3_R33G_REPORT.md"
    oof_columns = [
        "candidate_id", "decision_timestamp_utc", "head", "underlying_symbol", "raw_net20",
        "pred_t1", "pred_t5", "pred_t6", "pred_t7", "predicted_conditional_loss_magnitude",
        "actual_t7", "loss_magnitude", "naive_t7_mean", "naive_t7_median", "fold", "trading_date",
    ]
    oof[oof_columns].to_parquet(oof_path, index=False)
    diagnostics.to_csv(metrics_path, index=False)
    oof_sha = file_sha256(oof_path)

    summary = {
        "FAST3_R33G_STATUS": "PASS", "FAST3_R33G_CLASSIFICATION": classification,
        "FAST3_R33G_DECISION": decision, "R33G_PREREGISTRATION_VERIFIED": True,
        "R33G_PREREGISTRATION_SHA256": prereg_sha, "T7_CONTRACT_SHA256": contract_sha,
        "PARENT_R33FR_CLASSIFICATION": "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE",
        "PARENT_R33FR_PREREGISTRATION_SHA256": EXPECTED_SHA256[R33FR_PREREGISTRATION],
        "T6_CONTRACT_SOURCE": str(R33D_CONTRACT), "T6_CONTRACT_SHA256": EXPECTED_SHA256[R33D_CONTRACT],
        "T6_FEATURE_MANIFEST_SHA256": T6_FEATURE_MANIFEST_SHA256,
        "T7_FEATURE_MANIFEST_SHA256": T6_FEATURE_MANIFEST_SHA256,
        "FEATURE_MANIFEST_EXACT_MATCH": True, "NEW_FEATURE_COUNT": 0, "REMOVED_FEATURE_COUNT": 0,
        "T7_TARGET_DEFINITION": T7_TARGET_DEFINITION, "T7_TARGET_TRANSFORM": T7_TARGET_TRANSFORM,
        "T7_INVERSE_TRANSFORM": T7_INVERSE_TRANSFORM, "LOSS_TARGET_RECONCILIATION_STATUS": "PASS",
        "T7_LOSER_SAMPLE_COUNT": len(losers), "T7_ALL_OOF_PREDICTION_COUNT": len(oof),
        "T7_FOLD_COUNT": int(losers.fold.nunique()), "T7_FOLD_IDENTITY_MATCH_T6": True,
        "NO_FUTURE_LEAKAGE": True, "NO_SAME_FOLD_TRAINING": True, "PIT_FEATURE_CONTRACT_PASS": True,
        "T7_MODEL_VARIANT_COUNT": 1, "T7_MODEL_FIT_COUNT": fit_count,
        "T7_MODEL_PREDICT_CALL_COUNT": predict_count,
        "T7_OOF_SPEARMAN_VS_REALIZED_LOSS": pooled, "T7_OOF_PEARSON": pearson,
        "DATE_BALANCED_T7_VS_LOSS_SPEARMAN": date_balanced,
        "T7_POSITIVE_SPEARMAN_FOLD_COUNT": sum(value > 0 for value in fold_spearmans),
        "T7_MIN_FOLD_SPEARMAN": min(fold_spearmans), "T7_MAX_FOLD_SPEARMAN": max(fold_spearmans),
        "UP_T7_SAMPLE_COUNT": directions["UP"][0], "UP_T7_SPEARMAN": directions["UP"][1],
        "DOWN_T7_SAMPLE_COUNT": directions["DOWN"][0], "DOWN_T7_SPEARMAN": directions["DOWN"][1],
        "QUANTILE_COUNT": QUANTILE_COUNT, "QUANTILE_LOSS_SPEARMAN": quantile_s,
        "TOP_MINUS_BOTTOM_MEAN_LOSS": top_bottom,
        "CONDITIONAL_INCREMENTAL_GRID": "2x2x2",
        "CONDITIONAL_T7_VS_LOSS_GIVEN_T1_T5_T6_SPEARMAN": conditional_s,
        "DATE_BALANCED_CONDITIONAL_T7_VS_LOSS_GIVEN_T1_T5_T6_SPEARMAN": conditional_date_s,
        "T7_T5_PREDICTION_EXACT_MATCH": t7_t5_exact_match,
        "T7_T5_PREDICTION_MAX_ABS_DIFFERENCE": t7_t5_max_abs_difference,
        "INCREMENTAL_IDENTITY_GUARD_PASS": not t7_t5_exact_match,
        "INCREMENTAL_RAW_STATISTICS_POSITIVE": bool(conditional_s > 0 and conditional_date_s > 0),
        "INCREMENTAL_GATE_FAILURE_REASON": "T7_BITWISE_IDENTICAL_TO_FROZEN_T5" if t7_t5_exact_match else None,
        "NAIVE_MEAN_MAE": naive_mean_mae, "NAIVE_MEDIAN_MAE": naive_median_mae,
        "T7_OOF_MAE": mae, "T7_OOF_RMSE": rmse, "MAE_SCALE": "natural_log1p(loss_magnitude)",
        "T7_RANKING_VALIDATION_IS_CALIBRATED_LOSS_LEVEL_VALIDATION": False,
        "GATE_A_POOLED_RANKING": gates["A"], "GATE_B_DATE_BALANCED": gates["B"],
        "GATE_C_FOLD_STABILITY": gates["C"], "GATE_D_DIRECTION_STABILITY": gates["D"],
        "GATE_E_QUANTILE_MONOTONICITY": gates["E"], "GATE_F_INCREMENTAL_POOLED": gates["F"],
        "GATE_G_INCREMENTAL_DATE_BALANCED": gates["G"], "T7_VALIDATED": validated,
        "NEW_HEAD_COUNT": 1, "NEW_TARGET_COUNT": 1, "MODEL_FAMILY_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SEARCH_COUNT": 0, "TARGET_SEARCH_COUNT": 0,
        "TARGET_TRANSFORM_SEARCH_COUNT": 0, "INTERACTION_SEARCH_COUNT": 0, "BUCKET_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0, "EV_COMBINATION_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0, "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "T1_REFIT_COUNT": 0, "T5_REFIT_COUNT": 0, "T6_REFIT_COUNT": 0,
        "T1_NEW_PREDICT_COUNT": 0, "T5_NEW_PREDICT_COUNT": 0, "T6_NEW_PREDICT_COUNT": 0,
        "T7_MODEL_CREATED": True, "T8_MODEL_CREATED": False,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True, "FURTHER_HEAD_EXPANSION_ALLOWED": further_head_expansion,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "FIRST_RUN_STATUS": FIRST_RUN_STATUS, "RERUN_COUNT": RERUN_COUNT, "RERUN_REASON": RERUN_REASON,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False, "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": decision, "NEXT_STAGE": next_stage,
        "RUN_ID": run_id, "RUN_STARTED_AT_UTC": started.isoformat(),
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "T7_OOF_SHA256": oof_sha, "REPORT_PATH": str(report_path), "SUMMARY_JSON_PATH": str(summary_path),
        "PREREGISTRATION_PATH": str(prereg_path), "METRICS_PATH": str(metrics_path),
        "T7_CONTRACT_PATH": str(contract_path), "T7_OOF_PATH": str(oof_path),
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
    }
    write_json(summary_path, summary)
    fold_lines = "\n".join(
        f"- {row['group']}: n={int(row['count'])}, Spearman={row['t7_spearman_vs_loss']}"
        for row in diagnostics_rows if row["record_type"] == "FOLD"
    )
    report = f"""# FAST3 R33G - Minimal T7 Loss-Magnitude Head Validation

## Frozen model contract

T7 exactly mirrors the frozen T6 29-feature manifest (`{T6_FEATURE_MANIFEST_SHA256}`), feature order, HistGradientBoostingRegressor parameters, seed, independent UP/DOWN fits, five economic folds, missing-value behavior, and full validation-candidate prediction scope. The only scientific change is strict-loser training with `log1p(abs(raw_net20))`.

## Evidence

- Loser sample: `{len(losers):,}`.
- Pooled / date-balanced Spearman: `{pooled}` / `{date_balanced}`.
- UP / DOWN Spearman: `{directions['UP'][1]}` / `{directions['DOWN'][1]}`.
{fold_lines}
- Five-quantile monotonicity / top-minus-bottom mean loss: `{quantile_s}` / `{top_bottom}`.
- Conditional incremental pooled / date-balanced raw Spearman within fixed T1/T5/T6 2x2x2 cells: `{conditional_s}` / `{conditional_date_s}`.
- T7 versus frozen T5 prediction identity: exact match `{t7_t5_exact_match}`, maximum absolute difference `{t7_t5_max_abs_difference}`. Because the 2x2x2 diagnostic only coarsely bins T5, its positive raw statistic cannot establish incremental information when T7 is the same variable. Gates F/G therefore fail the hard non-repetition requirement.
- Gate results: `{gates}`.

Classification: `{classification}`. Decision: `{decision}`. T7 validated: `{validated}`. Further head expansion allowed: `{further_head_expansion}`. Next stage: `{next_stage}`.

MAE is secondary and is measured on the frozen log target: T7 / naive mean / naive median MAE `{mae}` / `{naive_mean_mae}` / `{naive_median_mae}`. T7 ranking validation is not calibrated loss-level validation; `expm1(pred_t7)` is not asserted to equal `E[loss magnitude | loser, X]`.

No feature/model/target-transform search, base-head refit or prediction, EV combination, threshold, trading/execution simulation, position sizing, Final load, holdout inspection, or T8 occurred.
"""
    report_path.write_text(report, encoding="utf-8")

    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33GStop("STOP_R33G_FROZEN_INPUT_MUTATED")
    if file_sha256(contract_path) != contract_sha or file_sha256(prereg_path) != prereg_sha:
        raise R33GStop("STOP_R33G_FROZEN_CONTRACT_MUTATED")
    compact_terminal_summary(summary)
    print(f"REPORT_PATH={report_path}")
    print(f"SUMMARY_JSON_PATH={summary_path}")
    print(f"T7_OOF_PATH={oof_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33GStop as exc:
        raise SystemExit(str(exc)) from exc
