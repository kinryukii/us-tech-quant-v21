#!/usr/bin/env python
"""FAST3 R33F fail-closed existing-head loss-mapping sufficiency audit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
RUN_ID = "r33f_existing_head_loss_magnitude_sufficiency_20260811T040000Z"
FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3" / RUN_ID
SCRATCH_ROOT = RESULTS_ROOT / "scratch/fast3" / RUN_ID

R33E_ROOT = RESULTS_ROOT / "frozen/fast3/r33e_three_head_economic_semantics_20260811T020000Z"
R33D_ROOT = RESULTS_ROOT / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z"
R33B_ROOT = RESULTS_ROOT / "frozen/fast3/r33b_conditional_loss_severity_20260810T200000Z"
R33E_SUMMARY = R33E_ROOT / "FAST3_R33E_SUMMARY.json"
R33E_CONTRACT = R33E_ROOT / "FAST3_R33E_SEMANTICS_CONTRACT_R1.json"
R33E_DIAGNOSTICS = R33E_ROOT / "FAST3_R33E_DIAGNOSTICS.csv"
R33D_SUMMARY = R33D_ROOT / "FAST3_R33D_SUMMARY.json"
R33D_CONTRACT = R33D_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
R33B_CONTRACT = R33B_ROOT / "FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1.json"
THREE_HEAD_OOF = RESULTS_ROOT / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"

EXPECTED_SHA256 = {
    R33E_SUMMARY: "be5ec47b3f6a97824fd2c655f3ce70b77357bd35c3aaf68e67595b6e123ae46e",
    R33E_CONTRACT: "147ac0d0ed07c353d08f7ff826e06d866b3272778ce4934a79f37f6de84c3dc5",
    R33E_DIAGNOSTICS: "c7e63ca9de907852b67fb220d033d82510e83578562d42421bd8931793018078",
    R33D_SUMMARY: "32dc6fd23a9256b1dde203071ad0ad0cfc48d17d459d2baa1f3b7a95c5a462e3",
    R33D_CONTRACT: "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2",
    R33B_CONTRACT: "d491b24943fc484577449b375a1bed3f34aa122773c0f007e674951193d1db3a",
    THREE_HEAD_OOF: "99021c1fc956a99b949f76153364a9517c53ce1df92b36623b6e48531e1d3df1",
}

PREDICTIVE_INPUTS = ("pred_t1", "pred_t5", "pred_t6")
CANDIDATE_MAPPINGS = ("M1_RIDGE", "M2_T5_T6_3X3", "M3_T1_T5_T6_2X2X2")
COMPLEXITY_PRIORITY = CANDIDATE_MAPPINGS
RIDGE_ALPHA = 1.0
M2_GRID = (3, 3)
M3_GRID = (2, 2, 2)
CALIBRATION_QUANTILES = 5
FOLD_COUNT = 5
OOF_ROW_COUNT = 984_049
LOSER_COUNT = 455_413
NY = "America/New_York"
ALLOWED_SCIENTIFIC_CLASSIFICATIONS = {
    "A_EXISTING_THREE_HEADS_SUFFICIENT_FOR_LOSS_MAGNITUDE_COMPONENT",
    "B_EXISTING_HEADS_RANK_LOSS_BUT_LEVEL_CALIBRATION_INSUFFICIENT",
    "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE",
}


class R33FStop(RuntimeError):
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
    if isinstance(value, (Path, pd.Timestamp)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def fold_safe_baselines(training_loss: pd.Series) -> tuple[float, float]:
    if training_loss.empty or training_loss.isna().any() or not training_loss.gt(0).all():
        raise R33FStop("STOP_R33F_EMPTY_OR_INVALID_TRAINING_LOSS")
    return float(training_loss.mean()), float(training_loss.median())


def training_quantile_edges(training_values: pd.Series, bins: int) -> np.ndarray:
    if training_values.empty or bins < 2:
        raise R33FStop("STOP_R33F_INVALID_TRAINING_BIN_INPUT")
    edges = training_values.quantile(np.arange(1, bins) / bins).to_numpy(dtype=float)
    return edges


def apply_training_edges(values: pd.Series, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(edges, values.to_numpy(dtype=float), side="right") + 1


def select_first_pass(gates: dict[str, bool]) -> str | None:
    for mapping in COMPLEXITY_PRIORITY:
        if gates.get(mapping) is True:
            return mapping
    return None


def validate_lineage() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33FStop("STOP_R33F_DATA_OR_LINEAGE_INTEGRITY")
    r33e = read_json(R33E_SUMMARY)
    r33d = read_json(R33D_SUMMARY)
    r33d_contract = read_json(R33D_CONTRACT)
    r33b_contract = read_json(R33B_CONTRACT)
    if (
        r33e.get("FAST3_R33E_CLASSIFICATION") != "B_THREE_HEAD_POSITIVE_LEG_CLOSED_LOSS_LEG_UNRESOLVED"
        or r33e.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33e.get("FINAL_HOLDOUT_INSPECTED") is not False
        or r33d.get("FAST3_R33D_CLASSIFICATION") != "A_T6_VALIDATED"
        or r33d.get("T6_OOF_SHA256") != EXPECTED_SHA256[THREE_HEAD_OOF]
        or r33d.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33d.get("FINAL_CONFIRMATION_DATA_INSPECTED") is not False
        or r33d_contract.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33b_contract.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33d_contract.get("VALIDATION_PREDICTION_SCOPE") != "all OOF eligible validation candidates"
        or r33b_contract.get("VALIDATION_PREDICTION_SCOPE") != "ALL OOF-eligible validation candidates"
    ):
        raise R33FStop("STOP_R33F_DATA_OR_LINEAGE_INTEGRITY")
    columns = [
        "candidate_id", "decision_timestamp_utc", "head", "raw_net20",
        "pred_t1", "pred_t5", "pred_t6", "fold", "trading_date",
    ]
    frame = pd.read_parquet(THREE_HEAD_OOF, columns=columns)
    if (
        len(frame) != OOF_ROW_COUNT
        or frame.candidate_id.duplicated().any()
        or frame[list(PREDICTIVE_INPUTS) + ["raw_net20"]].isna().any().any()
        or frame.fold.nunique() != FOLD_COUNT
        or set(frame["head"]) != {"UP", "DOWN"}
        or int(frame.raw_net20.lt(0).sum()) != LOSER_COUNT
        or int(frame.raw_net20.eq(0).sum()) != 0
    ):
        raise R33FStop("STOP_R33F_DATA_OR_LINEAGE_INTEGRITY")
    expected_dates = frame.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
    if (
        not frame.trading_date.eq(expected_dates).all()
        or frame.decision_timestamp_utc.min() != pd.Timestamp("2021-01-01T00:00:00Z")
        or frame.decision_timestamp_utc.max() >= pd.Timestamp("2025-02-01T05:00:00Z")
    ):
        raise R33FStop("STOP_R33F_DATA_OR_LINEAGE_INTEGRITY")
    return frame, r33d_contract, r33b_contract


def assess_mapping_training_coverage(
    frame: pd.DataFrame,
    r33d_contract: dict[str, Any],
    r33b_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    winner_records = r33d_contract["PER_FOLD_DIRECTION_COUNTS"]
    loser_records = r33b_contract["PER_FOLD_DIRECTION_COUNTS"]
    fold_order = ["OOF_2021", "OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025_JAN"]
    rows = []
    for fold in fold_order:
        winner_fold = [row for row in winner_records if row["fold"] == fold]
        loser_fold = [row for row in loser_records if row["fold"] == fold]
        cutoffs = {pd.Timestamp(row["information_cutoff"]) for row in winner_fold}
        if len(winner_fold) != 2 or len(loser_fold) != 2 or len(cutoffs) != 1:
            raise R33FStop("STOP_R33F_DATA_OR_LINEAGE_INTEGRITY")
        cutoff = next(iter(cutoffs))
        historical = frame.decision_timestamp_utc.lt(cutoff)
        available_all = int(historical.sum())
        available_losers = int((historical & frame.raw_net20.lt(0)).sum())
        required_train_losers = int(sum(row["train_loss_count"] for row in loser_fold))
        required_train_winners = int(sum(row["train_winner_count"] for row in winner_fold))
        rows.append(
            {
                "fold": fold,
                "information_cutoff": cutoff,
                "required_original_training_loser_count": required_train_losers,
                "required_original_training_winner_count": required_train_winners,
                "available_historical_three_head_prediction_count": available_all,
                "available_historical_three_head_loser_prediction_count": available_losers,
                "coverage_sufficient": bool(available_losers > 0),
            }
        )
    return rows


def preregistration() -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R33F_PREREGISTRATION_R1",
        "STATUS": "FROZEN_BEFORE_ANY_MAPPING_FIT",
        "RESEARCH_QUESTION": "Are frozen T1/T5/T6 outputs sufficient for a stable conditional loser loss-magnitude estimator?",
        "INPUT_FEATURES": list(PREDICTIVE_INPUTS),
        "NEW_RAW_FEATURE_COUNT": 0,
        "CANDIDATE_MAPPINGS": list(CANDIDATE_MAPPINGS),
        "LOSS_MAPPING_CANDIDATE_COUNT": len(CANDIDATE_MAPPINGS),
        "M1": {"TYPE": "Ridge with training-fold standardization and intercept", "ALPHA": RIDGE_ALPHA, "NEGATIVE_PREDICTION_CLIP": 0.0},
        "M2": {"TYPE": "fixed T5 x T6 training-fold calibration table", "GRID": "3x3", "CELL_VALUE": "training loser mean loss", "EMPTY_CELL_FALLBACK": "training loser global mean"},
        "M3": {"TYPE": "fixed T1 x T5 x T6 training-fold median-split table", "GRID": "2x2x2", "CELL_VALUE": "training loser mean loss", "EMPTY_CELL_FALLBACK": "training loser global mean"},
        "CALIBRATION_QUANTILES": CALIBRATION_QUANTILES,
        "BASELINES": ["training-fold loser mean", "training-fold loser median"],
        "SUFFICIENCY_GATES": {
            "A_POOLED_SPEARMAN_MIN": 0.15,
            "B_DATE_BALANCED_SPEARMAN_MIN": 0.15,
            "C_POSITIVE_FOLD_COUNT_MIN": 4,
            "C_MINIMUM_ALLOWED_FOLD_SPEARMAN_STRICTLY_GREATER_THAN": -0.05,
            "D_UP_SPEARMAN_STRICTLY_GREATER_THAN": 0.0,
            "D_DOWN_SPEARMAN_STRICTLY_GREATER_THAN": 0.0,
            "E_OOF_MAE_RELATIVE_IMPROVEMENT_MIN": 0.02,
            "F_CALIBRATION_QUANTILE_SPEARMAN_MIN": 0.8,
            "F_TOP_MEAN_LOSS_STRICTLY_GREATER_THAN_BOTTOM": True,
        },
        "COMPLEXITY_PRIORITY": "M1_RIDGE > M2_T5_T6_3X3 > M3_T1_T5_T6_2X2X2",
        "SELECTION_RULE": "FIRST_PASS_BY_PREDECLARED_COMPLEXITY_ORDER",
        "FOLD_COUNT": FOLD_COUNT,
        "EXPECTED_MAPPING_FIT_COUNT_IF_EXECUTABLE": 15,
        "EXPECTED_MAPPING_PREDICT_CALL_COUNT_IF_EXECUTABLE": 15,
        "FOLD_SAFE_TRAINING_PREDICTION_COVERAGE_REQUIRED_BEFORE_FIT": True,
        "FUTURE_OOF_ROWS_ALLOWED_AS_EARLIER_FOLD_TRAINING": False,
        "HEAD_REPREDICTION_ALLOWED": False,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False,
        "FINAL_HOLDOUT_ROW_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0,
        "INTERACTION_SEARCH_COUNT": 0,
        "BUCKET_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0,
        "POSITION_SIZING_SEARCH_COUNT": 0,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise R33FStop("USE_--run")
    if FROZEN_ROOT.exists() or SCRATCH_ROOT.exists():
        raise R33FStop("STOP_R33F_OUTPUT_EXISTS")

    input_hashes_before = {path: file_sha256(path) for path in EXPECTED_SHA256}
    frame, r33d_contract, r33b_contract = validate_lineage()
    losers = frame.loc[frame.raw_net20 < 0].copy()
    losers["loss_magnitude"] = -losers.raw_net20
    if len(losers) != LOSER_COUNT or not losers.loss_magnitude.gt(0).all():
        raise R33FStop("STOP_R33F_DATA_OR_LINEAGE_INTEGRITY")

    FROZEN_ROOT.mkdir(parents=True)
    prereg_path = FROZEN_ROOT / "FAST3_R33F_PREREGISTRATION_R1.json"
    prereg = preregistration()
    write_json(prereg_path, prereg)
    prereg_sha = file_sha256(prereg_path)
    coverage = assess_mapping_training_coverage(frame, r33d_contract, r33b_contract)
    insufficient = [row for row in coverage if not row["coverage_sufficient"]]
    if not insufficient:
        raise R33FStop("STOP_R33F_UNEXPECTED_EXECUTABLE_PATH_REQUIRES_MAPPING_IMPLEMENTATION")

    status = "STOPPED_DATA_OR_LINEAGE_INTEGRITY"
    decision = "STOP_NO_FOLD_SAFE_THREE_HEAD_TRAINING_PREDICTIONS_FOR_OOF_2021"
    blocker = (
        "The frozen T1/T5/T6 ledgers begin at 2021-01-01, while OOF_2021 mapping training "
        "must end before the 2020-12-31 information cutoff. Historical training losers exist "
        "but have no frozen three-head outputs. Future-fold training or head re-prediction is prohibited."
    )
    mapping_rows = []
    for mapping in CANDIDATE_MAPPINGS:
        mapping_rows.append(
            {
                "mapping": mapping,
                "status": "NOT_RUN_DATA_OR_LINEAGE_INTEGRITY",
                "oof_mae": None,
                "oof_mae_relative_improvement": None,
                "oof_spearman": None,
                "date_balanced_spearman": None,
                "positive_spearman_fold_count": None,
                "up_spearman": None,
                "down_spearman": None,
                "gate_status": "NOT_EVALUATED",
            }
        )
    metrics_path = FROZEN_ROOT / "FAST3_R33F_MAPPING_METRICS.csv"
    pd.DataFrame(mapping_rows).to_csv(metrics_path, index=False)
    summary_path = FROZEN_ROOT / "FAST3_R33F_SUMMARY.json"
    report_path = FROZEN_ROOT / "FAST3_R33F_REPORT.md"
    first = insufficient[0]
    summary = {
        "FAST3_R33F_STATUS": status,
        "FAST3_R33F_CLASSIFICATION": None,
        "FAST3_R33F_DECISION": decision,
        "DATA_OR_LINEAGE_BLOCKER": blocker,
        "R33F_PREREGISTRATION_VERIFIED": True,
        "R33F_PREREGISTRATION_SHA256": prereg_sha,
        "LOSER_SAMPLE_COUNT": len(losers),
        "PLANNED_OOF_ROW_COUNT": len(losers),
        "MAPPING_OOF_ROW_COUNT": 0,
        "OOF_UNIQUE_CANDIDATE_ID_COUNT": 0,
        "OOF_DUPLICATE_COUNT": 0,
        "OOF_MISSING_PREDICTION_COUNT": len(losers),
        "FOLD_SAFE_MAPPING_TRAINING_COVERAGE": coverage,
        "BLOCKED_FOLD_COUNT": len(insufficient),
        "FIRST_BLOCKED_FOLD": first["fold"],
        "FIRST_BLOCKED_INFORMATION_CUTOFF": first["information_cutoff"],
        "FIRST_BLOCKED_REQUIRED_TRAINING_LOSER_COUNT": first["required_original_training_loser_count"],
        "FIRST_BLOCKED_AVAILABLE_THREE_HEAD_TRAINING_LOSER_COUNT": first["available_historical_three_head_loser_prediction_count"],
        "BASELINE_MEAN_MAE": None,
        "BASELINE_MEDIAN_MAE": None,
        "BASELINE_MEAN_RMSE": None,
        "BASELINE_MEDIAN_RMSE": None,
        "M1_OOF_MAE": None,
        "M1_OOF_MAE_RELATIVE_IMPROVEMENT": None,
        "M1_OOF_SPEARMAN": None,
        "M1_DATE_BALANCED_SPEARMAN": None,
        "M1_POSITIVE_SPEARMAN_FOLD_COUNT": None,
        "M1_UP_SPEARMAN": None,
        "M1_DOWN_SPEARMAN": None,
        "M1_GATE_STATUS": "NOT_EVALUATED",
        "M2_OOF_MAE": None,
        "M2_OOF_MAE_RELATIVE_IMPROVEMENT": None,
        "M2_OOF_SPEARMAN": None,
        "M2_DATE_BALANCED_SPEARMAN": None,
        "M2_POSITIVE_SPEARMAN_FOLD_COUNT": None,
        "M2_UP_SPEARMAN": None,
        "M2_DOWN_SPEARMAN": None,
        "M2_GATE_STATUS": "NOT_EVALUATED",
        "M3_OOF_MAE": None,
        "M3_OOF_MAE_RELATIVE_IMPROVEMENT": None,
        "M3_OOF_SPEARMAN": None,
        "M3_DATE_BALANCED_SPEARMAN": None,
        "M3_POSITIVE_SPEARMAN_FOLD_COUNT": None,
        "M3_UP_SPEARMAN": None,
        "M3_DOWN_SPEARMAN": None,
        "M3_GATE_STATUS": "NOT_EVALUATED",
        "SELECTED_EXISTING_HEAD_LOSS_MAPPING": None,
        "SELECTION_RULE": "FIRST_PASS_BY_PREDECLARED_COMPLEXITY_ORDER",
        "NEW_LOSS_MAGNITUDE_HEAD_JUSTIFIED": "UNRESOLVED",
        "NEW_HEAD_COUNT": 0,
        "NEW_RAW_FEATURE_COUNT": 0,
        "NEW_TARGET_COUNT": 0,
        "LOSS_MAPPING_CANDIDATE_COUNT": len(CANDIDATE_MAPPINGS),
        "LOSS_MAPPING_FIT_COUNT": 0,
        "LOSS_MAPPING_PREDICT_CALL_COUNT": 0,
        "NEW_HEAD_MODEL_FIT_COUNT": 0,
        "NEW_HEAD_MODEL_PREDICT_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0,
        "INTERACTION_SEARCH_COUNT": 0,
        "BUCKET_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0,
        "POSITION_SIZING_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False,
        "FINAL_HOLDOUT_ROW_COUNT": 0,
        "FIRST_RUN_STATUS": status,
        "RERUN_COUNT": 0,
        "RERUN_REASON": None,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
        "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": "R33F_NOT_IDENTIFIABLE_WITH_CURRENT_FROZEN_THREE_HEAD_OOF_COVERAGE",
        "NEXT_STAGE": "STOP_AND_RESTORE_FOLD_SAFE_T1_T5_T6_TRAINING_PREDICTION_LINEAGE",
        "REPORT_PATH": str(report_path),
        "SUMMARY_JSON_PATH": str(summary_path),
        "PREREGISTRATION_PATH": str(prereg_path),
        "MAPPING_METRICS_PATH": str(metrics_path),
        "OOF_MAPPING_PATH": None,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "R33F_NEW_SOURCE_FILE_COUNT": 1,
        "R33F_NEW_TEST_FILE_COUNT": 1,
        "NEW_HELPER_FILE_COUNT": 0,
    }
    write_json(summary_path, summary)
    report = f"""# FAST3 R33F — Existing-Head Loss-Magnitude Sufficiency Study

## Status

`{status}` — `{decision}`

The M1/M2/M3 candidates and all sufficiency gates were frozen before any mapping fit. The audit then stopped because the five-fold mapping contract is not executable from the available frozen head ledgers.

- Frozen T1/T5/T6 prediction coverage starts: `2021-01-01T00:00:00Z`.
- OOF_2021 mapping-training information cutoff: `{first['information_cutoff']}`.
- Required historical OOF_2021 training losers: `{first['required_original_training_loser_count']}`.
- Historical losers with all three frozen head outputs before cutoff: `{first['available_historical_three_head_loser_prediction_count']}`.

Using later OOF folds to train the 2021 mapping would introduce future leakage. Re-predicting historical rows would violate the R33F no-head-prediction contract. Dropping OOF_2021 would violate the fixed five-fold/full-OOF contract. Therefore no baseline or mapping metric is scientifically assigned, no A/B/C classification is emitted, and `NEW_LOSS_MAGNITUDE_HEAD_JUSTIFIED` remains `UNRESOLVED`.

No mapping fit, head fit/prediction, raw feature, final data, search, EV, trading, or execution operation occurred.
"""
    report_path.write_text(report, encoding="utf-8")
    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33FStop("STOP_R33F_FROZEN_INPUT_MUTATED")
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33FStop as exc:
        raise SystemExit(str(exc)) from exc
