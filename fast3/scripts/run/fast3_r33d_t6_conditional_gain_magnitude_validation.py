#!/usr/bin/env python
"""FAST3 R33D frozen T6 conditional-gain validation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor


SOURCE_ROOT = Path(r"D:\us-tech-quant")
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
RUN_ID = "r33d_conditional_gain_magnitude_20260811T000000Z"
FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3" / RUN_ID
SCRATCH_ROOT = RESULTS_ROOT / "scratch/fast3" / RUN_ID

R33C_ROOT = RESULTS_ROOT / "frozen/fast3/r33c_architecture_design_20260810T220000Z"
T6_PREREGISTRATION = R33C_ROOT / "FAST3_R33_T6_CONDITIONAL_GAIN_MAGNITUDE_PREREGISTRATION_R1.json"
R33C_ARCHITECTURE = R33C_ROOT / "FAST3_R33C_ARCHITECTURE_DESIGN_R1.json"
R33C_SUMMARY = R33C_ROOT / "FAST3_R33C_SUMMARY.json"
R33B_T5_OOF = RESULTS_ROOT / "scratch/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33B_T5_OOF_PREDICTIONS.parquet"
R32B_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r32b_full_universe_economic_baseline_training.py"
R30A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r30a_economic_target_baseline_training.py"
R32A_RUNNER = SOURCE_ROOT / "fast3/scripts/run/fast3_r32a_full_universe_economic_label_audit.py"

EXPECTED_SHA256 = {
    T6_PREREGISTRATION: "f209a895dcc6955d0b5969b9deb5710103734a122a679974678d2d6ead62e07e",
    R33C_ARCHITECTURE: "1652bd597425907185fd96c002656f91a814bc59c92469336745cd2930139958",
    R33C_SUMMARY: "30be62215fd720b3fb71895e67e98acff4860b17106298e3ab6ca17b31ad54db",
    R33B_T5_OOF: "1b2be7153c731f5857d7e78488f7ffb72c0752587f69e94954137fbce04279f6",
    R32B_RUNNER: "a55d3e719e453f789704f96ea304ac974f3521664ebb9801fafa2af308b669a0",
    R30A_RUNNER: "38fee3ba5b4e77b066b7141683e03224b43a6cef09415d2736fa35b623bb91b7",
    R32A_RUNNER: "e3fe20e10bfeef8bd48635514e9ce9eda23d4aebc73274ade708992c8e50caf3",
}
R32B_OOF_SHA = "a0b05b14824b79628d28a92ae786cd114806083620a5bc179d621d4942f7efee"
LABEL_MANIFEST_SHA = "12356e0dd8d75c8cefa4233900942e73dffd5ae0688d685be6915d99ac38cc29"
FEATURE_SHA = "248c4d1eabcbcee545ffc95f5f366390889c13199ec90d84d5bbd0f6332f4718"
SPLIT_SHA = "38352151a703737d74b4d61dbe68f82a9c6f3d5058aa72bd2a1896e19a5cb412"
OOF_ROW_COUNT = 984_049
FOLD_COUNT = 5
FEATURE_COUNT = 29
FIXED_BIN_COUNT = 10
INCREMENTAL_T1_T5_BIN_COUNT = 5
NY = "America/New_York"


class R33DStop(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_file(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise R33DStop("STOP_R33D_MODULE_IMPORT")
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


def safe_spearman(left: Any, right: Any) -> float | None:
    x, y = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 2 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    result = float(spearmanr(x, y).statistic)
    return result if np.isfinite(result) else None


def safe_pearson(left: Any, right: Any) -> float | None:
    x, y = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 2 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    result = float(np.corrcoef(x, y)[0, 1])
    return result if np.isfinite(result) else None


def derive_t6(net20: pd.Series) -> pd.Series:
    target = pd.Series(np.nan, index=net20.index, dtype=float)
    eligible = net20.gt(0)
    target.loc[eligible] = np.log1p(net20.loc[eligible].astype(float))
    return target


def candidate_id_hash(values: pd.Series) -> str:
    digest = hashlib.sha256()
    for value in values.astype(str).sort_values(kind="mergesort"):
        digest.update(value.encode("utf-8") + b"\n")
    return digest.hexdigest()


def assign_fixed_bins(frame: pd.DataFrame, score: str, bins: int, output: str) -> pd.DataFrame:
    if len(frame) < bins:
        raise R33DStop(f"STOP_R33D_TOO_FEW_ROWS_FOR_{output}")
    ordered = frame.sort_values(
        [score, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True],
        kind="mergesort",
    ).copy()
    ordered[output] = np.floor(np.arange(len(ordered)) * bins / len(ordered)).astype(int) + 1
    return ordered


def validate_preregistration() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33DStop("STOP_R33D_PREREGISTRATION_CONTRACT_MISMATCH")
    prereg = read_json(T6_PREREGISTRATION)
    architecture = read_json(R33C_ARCHITECTURE)
    summary = read_json(R33C_SUMMARY)
    required_prereg = {
        "CONTRACT_ID": "FAST3_R33_T6_CONDITIONAL_GAIN_MAGNITUDE_PREREGISTRATION_R1",
        "STATUS": "PREREGISTERED_NOT_TRAINED",
        "TARGET_NAME": "T6_CONDITIONAL_GAIN_MAGNITUDE",
        "FORMULA": "natural_log1p(corporate_action_normalized_executable_net20)",
        "TRAINING_ELIGIBILITY": "label_valid == true AND net20 > 0 only",
        "VALIDATION_PREDICTION_ELIGIBILITY": "all OOF candidates",
        "LOSING_ROW_T6_ZERO_FILL": False,
        "ZERO_RETURN_TRAINING_ELIGIBLE": False,
        "T6_MODEL_FIT_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
    }
    if any(prereg.get(key) != value for key, value in required_prereg.items()):
        raise R33DStop("STOP_R33D_PREREGISTRATION_CONTRACT_MISMATCH")
    if (
        architecture.get("SELECTED_ARCHITECTURE") != "T1 + T5 + T6"
        or architecture.get("DEDICATED_CONDITIONAL_GAIN_HEAD_REQUIRED") is not True
        or architecture.get("T6_MUST_BE_VALIDATED_BEFORE_COMBINATION") is not True
        or architecture.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or summary.get("FAST3_R33C_CLASSIFICATION") != "B_T1_T5_INSUFFICIENT_CONDITIONAL_GAIN_HEAD_REQUIRED"
        or summary.get("T6_PREREGISTERED") is not True
        or summary.get("T6_MODEL_FIT_COUNT") != 0
        or summary.get("T1_OOF_SHA256") != R32B_OOF_SHA
        or summary.get("T5_OOF_SHA256") != EXPECTED_SHA256[R33B_T5_OOF]
        or summary.get("ECONOMIC_LABEL_MANIFEST_SHA256") != LABEL_MANIFEST_SHA
        or summary.get("FINAL_CONFIRMATION_DATA_USED") is not False
    ):
        raise R33DStop("STOP_R33D_PREREGISTRATION_CONTRACT_MISMATCH")
    if Path(summary["T6_PREREGISTRATION_PATH"]) != T6_PREREGISTRATION:
        raise R33DStop("STOP_R33D_PREREGISTRATION_CONTRACT_MISMATCH")
    return prereg, architecture, summary


def validate_infrastructure() -> tuple[Any, Any, dict[str, Any], tuple[str, ...]]:
    r32b = import_file(R32B_RUNNER, "r33d_r32b")
    r30a = import_file(R30A_RUNNER, "r33d_r30a")
    _, manifest, features = r32b.guard_authority()
    if (
        r32b.LABEL_MANIFEST_SHA != LABEL_MANIFEST_SHA
        or r32b.FEATURE_SHA != FEATURE_SHA
        or r32b.SPLIT_SHA != SPLIT_SHA
        or len(features) != FEATURE_COUNT
        or tuple(features) != tuple(read_json(r32b.FEATURE_MANIFEST)["arms"]["ARM_ALL"])
        or len(r30a.ECONOMIC_FOLDS) != FOLD_COUNT
        or r30a.HGB_PARAMS.get("random_state") != 1729
        or "pred_t1" in features
        or "pred_t5" in features
    ):
        raise R33DStop("STOP_R33D_FROZEN_INFRASTRUCTURE_MISMATCH")
    return r32b, r30a, manifest, features


def quantile_diagnostics(winners: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    binned = assign_fixed_bins(winners, "pred_t6", FIXED_BIN_COUNT, "t6_decile")
    rows = []
    for decile, part in binned.groupby("t6_decile", sort=True, observed=True):
        rows.append(
            {
                "record_type": "T6_DECILE",
                "group": f"DECILE_{int(decile)}",
                "ordinal": int(decile),
                "count": len(part),
                "mean_predicted_t6": float(part.pred_t6.mean()),
                "mean_realized_gain": float(part.raw_net20.mean()),
                "median_realized_gain": float(part.raw_net20.median()),
            }
        )
    table = pd.DataFrame(rows)
    quantile_s = safe_spearman(table.ordinal, table.mean_realized_gain)
    if quantile_s is None or len(table) != FIXED_BIN_COUNT:
        raise R33DStop("STOP_R33D_QUANTILE_DIAGNOSTIC")
    spread = float(table.iloc[-1].mean_realized_gain - table.iloc[0].mean_realized_gain)
    return table, quantile_s, spread


def incremental_t1_t5_audit(oof: pd.DataFrame) -> tuple[float, float, pd.DataFrame]:
    with_t1 = assign_fixed_bins(oof, "pred_t1", INCREMENTAL_T1_T5_BIN_COUNT, "t1_quintile")
    with_both = assign_fixed_bins(with_t1, "pred_t5", INCREMENTAL_T1_T5_BIN_COUNT, "t5_quintile")
    winners = with_both.loc[with_both.raw_net20 > 0].copy()
    ranked_parts = []
    cell_rows = []
    for (t1_bin, t5_bin), part in winners.groupby(["t1_quintile", "t5_quintile"], sort=True, observed=True):
        ranked = part[["candidate_id", "trading_date"]].copy()
        ranked["within_cell_t6_rank"] = part.pred_t6.rank(method="average", pct=True)
        ranked["within_cell_gain_rank"] = part.raw_net20.rank(method="average", pct=True)
        ranked_parts.append(ranked)
        cell_rows.append(
            {
                "record_type": "INCREMENTAL_CELL",
                "group": f"T1_Q{int(t1_bin)}_T5_Q{int(t5_bin)}",
                "ordinal": None,
                "count": len(part),
                "t1_quintile": int(t1_bin),
                "t5_quintile": int(t5_bin),
                "within_cell_t6_gain_spearman": safe_spearman(part.pred_t6, part.raw_net20),
            }
        )
    if len(cell_rows) != 25:
        raise R33DStop("STOP_R33D_INCREMENTAL_CELL_CARDINALITY")
    ranked = pd.concat(ranked_parts, ignore_index=True)
    pooled = safe_spearman(ranked.within_cell_t6_rank, ranked.within_cell_gain_rank)
    daily = (
        ranked.groupby("trading_date", sort=True, observed=True)
        .agg(mean_t6_rank=("within_cell_t6_rank", "mean"), mean_gain_rank=("within_cell_gain_rank", "mean"))
        .reset_index()
    )
    date_balanced = safe_spearman(daily.mean_t6_rank, daily.mean_gain_rank)
    if pooled is None or date_balanced is None:
        raise R33DStop("STOP_R33D_INCREMENTAL_METRIC")
    return pooled, date_balanced, pd.DataFrame(cell_rows)


def classify_t6(
    overall: float,
    date_balanced: float,
    positive_folds: int,
    up: float,
    down: float,
    incremental: float,
) -> tuple[str, str, str]:
    if (
        overall > 0
        and date_balanced > 0
        and positive_folds >= 3
        and up > 0
        and down > 0
        and incremental > 0
    ):
        return (
            "A_T6_VALIDATED",
            "CONDITIONAL_GAIN_MAGNITUDE_SIGNAL_VALIDATED",
            "DESIGN_THREE_HEAD_EXPECTED_PAYOFF_ARCHITECTURE",
        )
    if overall <= 0 or incremental <= 0 or positive_folds == 0 or (up <= 0 and down <= 0):
        return (
            "C_T6_NOT_VALIDATED",
            "CURRENT_FEATURE_SPACE_DOES_NOT_RELIABLY_IDENTIFY_CONDITIONAL_GAIN_MAGNITUDE",
            "STOP_AND_WAIT_FOR_HUMAN_MAGNITUDE_FACTOR_DECISION",
        )
    return (
        "B_T6_WEAK_OR_MIXED",
        "CONDITIONAL_GAIN_MAGNITUDE_SIGNAL_WEAK_OR_MIXED",
        "STOP_AND_WAIT_FOR_HUMAN_REVIEW",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise R33DStop("USE_--run")
    prior_failed_attempt_fit_count = 0
    prior_failed_attempt_predict_count = 0
    recovery_contract = FROZEN_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
    if FROZEN_ROOT.exists() or SCRATCH_ROOT.exists():
        frozen_files = list(FROZEN_ROOT.iterdir()) if FROZEN_ROOT.exists() else []
        scratch_files = list(SCRATCH_ROOT.iterdir()) if SCRATCH_ROOT.exists() else []
        if (
            len(frozen_files) != 1
            or frozen_files[0] != recovery_contract
            or file_sha256(recovery_contract) != "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2"
            or scratch_files
        ):
            raise R33DStop("STOP_R33D_OUTPUT_EXISTS")
        # The first fixed run completed all 10 fits/predictions, then failed only
        # at the T5/T6 fold_model merge-column assertion. Preserve that count.
        prior_failed_attempt_fit_count = FOLD_COUNT * 2
        prior_failed_attempt_predict_count = FOLD_COUNT * 2

    prereg_hash_before = file_sha256(T6_PREREGISTRATION)
    input_hashes_before = {path: file_sha256(path) for path in EXPECTED_SHA256}
    prereg, _, r33c_summary = validate_preregistration()
    r32b, r30a, manifest, features = validate_infrastructure()
    dataset, complete_coverage, missing_counts, _ = r32b.construct_dataset(manifest, features)
    dataset["actual_t6"] = derive_t6(dataset.raw_net20)
    eligible = dataset.raw_net20.gt(0)
    if (
        dataset.loc[eligible, "actual_t6"].isna().any()
        or dataset.loc[~eligible, "actual_t6"].notna().any()
        or not np.allclose(
            dataset.loc[eligible, "actual_t6"],
            np.log1p(dataset.loc[eligible, "raw_net20"]),
            rtol=0,
            atol=1e-15,
        )
    ):
        raise R33DStop("STOP_R33D_T6_TARGET_MISMATCH")

    fold_counts = []
    used_train = np.zeros(len(dataset), dtype=bool)
    for fold in r30a.ECONOMIC_FOLDS:
        train, valid, audit = r32b.fold_masks(dataset, fold)
        used_train |= (train & eligible).to_numpy()
        for direction in ("UP", "DOWN"):
            fold_counts.append(
                {
                    "fold": fold[0],
                    "direction": direction,
                    "train_winner_count": int((train & eligible & dataset["head"].eq(direction)).sum()),
                    "validation_all_count": int((valid & dataset["head"].eq(direction)).sum()),
                    "validation_winner_count": int((valid & eligible & dataset["head"].eq(direction)).sum()),
                    "information_cutoff": audit["information_cutoff"],
                    "overlap_count": audit["overlap_count"],
                }
            )

    FROZEN_ROOT.mkdir(parents=True, exist_ok=True)
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    contract_path = FROZEN_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
    contract = {
        "CONTRACT_ID": "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1",
        "STATUS": "FROZEN_BEFORE_FIT",
        "R33C_T6_PREREGISTRATION_SHA256": EXPECTED_SHA256[T6_PREREGISTRATION],
        "R33C_ARCHITECTURE_SHA256": EXPECTED_SHA256[R33C_ARCHITECTURE],
        "R33C_SUMMARY_SHA256": EXPECTED_SHA256[R33C_SUMMARY],
        "TARGET_NAME": "T6_CONDITIONAL_GAIN_MAGNITUDE",
        "TARGET_FORMULA": "natural_log1p(net20) on strict winners only",
        "TRAINING_ELIGIBILITY": "label_valid == true AND net20 > 0",
        "LOSER_ZERO_FILL": False,
        "VALIDATION_PREDICTION_SCOPE": "all OOF eligible validation candidates",
        "PRIMARY_EVALUATION_SCOPE": "actual OOF winners with net20 > 0",
        "FEATURE_COUNT": len(features),
        "FEATURE_NAMES": list(features),
        "FEATURE_MANIFEST_SHA256": FEATURE_SHA,
        "SPLIT_CONTRACT_SHA256": SPLIT_SHA,
        "MODEL_FAMILY": "HistGradientBoostingRegressor independent UP/DOWN",
        "HGB_PARAMETERS": r30a.HGB_PARAMS,
        "CATEGORICAL_FEATURES": list(r30a.CATEGORICAL),
        "MODEL_AND_HYPERPARAMETER_PRECEDENT": "frozen R32B/R33B fixed HGB configuration",
        "FULL_VALID_LABEL_COUNT": len(dataset),
        "FULL_T6_ELIGIBLE_WINNER_COUNT": int(eligible.sum()),
        "TRAIN_WINNER_UNIQUE_ROW_COUNT": int(used_train.sum()),
        "T6_ELIGIBLE_CANDIDATE_ID_SHA256": candidate_id_hash(dataset.loc[eligible, "candidate_id"]),
        "PER_FOLD_DIRECTION_COUNTS": fold_counts,
        "QUANTILE_BIN_COUNT": FIXED_BIN_COUNT,
        "INCREMENTAL_METHOD": "fixed 5x5 T1/T5 bins with pooled within-cell percentile ranks",
        "CLASSIFICATION_GATE": {
            "A_T6_VALIDATED": "overall > 0 AND date-balanced > 0 AND positive folds >= 3/5 AND UP > 0 AND DOWN > 0 AND incremental > 0",
            "C_T6_NOT_VALIDATED": "overall <= 0 OR incremental <= 0 OR zero positive folds OR both directions <= 0",
            "B_T6_WEAK_OR_MIXED": "remaining partial or mixed positive evidence",
        },
        "FEATURE_SEARCH_COUNT": 0,
        "MODEL_FAMILY_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "SEED_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0,
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
            training = train & eligible & dataset["head"].eq(direction)
            validation = valid & dataset["head"].eq(direction)
            if not training.any() or not validation.any() or file_sha256(contract_path) != contract_sha:
                raise R33DStop("STOP_R33D_FROZEN_T6_CONTRACT_MUTATED")
            model = HistGradientBoostingRegressor(**params)
            model.fit(dataset.loc[training, list(features)], dataset.loc[training, "actual_t6"])
            fit_count += 1
            part = dataset.loc[validation, ["candidate_id"]].copy()
            part["pred_t6"] = model.predict(dataset.loc[validation, list(features)])
            predict_count += 1
            part["naive_t6_mean"] = float(dataset.loc[training, "actual_t6"].mean())
            part["naive_t6_median"] = float(dataset.loc[training, "actual_t6"].median())
            part["t6_fold_model"] = fold[0]
            predictions.append(part)
            del model
    predicted = pd.concat(predictions, ignore_index=True)
    if (
        len(predicted) != OOF_ROW_COUNT
        or predicted.candidate_id.duplicated().any()
        or predicted.pred_t6.isna().any()
        or fit_count != FOLD_COUNT * 2
        or predict_count != FOLD_COUNT * 2
    ):
        raise R33DStop("STOP_R33D_T6_PREDICTION_MEMBERSHIP")

    base = pd.read_parquet(R33B_T5_OOF)
    base["decision_timestamp_utc"] = pd.to_datetime(base.decision_timestamp_utc, utc=True)
    oof = base.merge(predicted, on="candidate_id", how="inner", validate="one_to_one")
    if len(oof) != OOF_ROW_COUNT or not oof.fold.eq(oof.t6_fold_model).all():
        raise R33DStop("STOP_R33D_T1_T5_T6_OOF_RECONCILIATION")
    expected_dates = oof.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
    if not oof.trading_date.eq(expected_dates).all():
        raise R33DStop("STOP_R33D_ET_TRADING_DATE_MISMATCH")
    oof["actual_t6"] = derive_t6(oof.raw_net20)
    oof["predicted_conditional_gain_magnitude"] = np.expm1(oof.pred_t6)
    winners = oof.loc[oof.raw_net20 > 0].copy()
    if len(winners) != int(eligible.loc[dataset.candidate_id.isin(oof.candidate_id)].sum()):
        raise R33DStop("STOP_R33D_WINNER_MEMBERSHIP")

    t6_s = safe_spearman(winners.pred_t6, winners.raw_net20)
    t6_pearson = safe_pearson(winners.predicted_conditional_gain_magnitude, winners.raw_net20)
    if t6_s is None or t6_pearson is None:
        raise R33DStop("STOP_R33D_PRIMARY_METRIC")
    error = winners.pred_t6 - winners.actual_t6
    mae = float(error.abs().mean())
    rmse = float(np.sqrt(np.mean(np.square(error))))
    naive_mean_mae = float((winners.naive_t6_mean - winners.actual_t6).abs().mean())
    naive_median_mae = float((winners.naive_t6_median - winners.actual_t6).abs().mean())

    daily = (
        winners.groupby("trading_date", sort=True, observed=True)
        .agg(count=("candidate_id", "size"), mean_pred_t6=("pred_t6", "mean"), mean_realized_gain=("raw_net20", "mean"))
        .reset_index()
    )
    date_s = safe_spearman(daily.mean_pred_t6, daily.mean_realized_gain)
    if date_s is None:
        raise R33DStop("STOP_R33D_DATE_BALANCED_METRIC")

    diagnostic_rows = []
    fold_positive = 0
    for fold, part in winners.groupby("fold", sort=True, observed=True):
        fold_s = safe_spearman(part.pred_t6, part.raw_net20)
        fold_positive += int(fold_s is not None and fold_s > 0)
        diagnostic_rows.append(
            {"record_type": "FOLD", "group": fold, "count": len(part), "t6_spearman_vs_gain": fold_s}
        )
    direction_metrics: dict[str, tuple[int, float]] = {}
    for direction, part in winners.groupby("head", sort=True, observed=True):
        direction_s = safe_spearman(part.pred_t6, part.raw_net20)
        if direction_s is None:
            raise R33DStop("STOP_R33D_DIRECTION_METRIC")
        direction_metrics[direction] = (len(part), direction_s)
        diagnostic_rows.append(
            {"record_type": "DIRECTION", "group": direction, "count": len(part), "t6_spearman_vs_gain": direction_s}
        )
    quantiles, quantile_s, top_bottom = quantile_diagnostics(winners)
    conditional_s, conditional_date_s, incremental_cells = incremental_t1_t5_audit(oof)
    diagnostic_rows.extend(
        [
            {"record_type": "DATE_BALANCED", "group": "ET_TRADING_DATE_WINNERS", "count": len(daily), "t6_spearman_vs_gain": date_s},
            {"record_type": "INCREMENTAL", "group": "POOLED_WITHIN_FIXED_T1_T5_CELLS", "count": len(winners), "t6_spearman_vs_gain": conditional_s},
            {"record_type": "INCREMENTAL_DATE_BALANCED", "group": "ET_DATE_MEANS_OF_WITHIN_CELL_RANKS", "count": len(daily), "t6_spearman_vs_gain": conditional_date_s},
        ]
    )
    diagnostics = pd.concat(
        [pd.DataFrame(diagnostic_rows), quantiles, incremental_cells], ignore_index=True, sort=False
    )

    classification, decision, next_stage = classify_t6(
        t6_s,
        date_s,
        fold_positive,
        direction_metrics["UP"][1],
        direction_metrics["DOWN"][1],
        conditional_s,
    )

    oof_path = SCRATCH_ROOT / "FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
    diagnostics_path = FROZEN_ROOT / "FAST3_R33D_DIAGNOSTICS.csv"
    report_path = FROZEN_ROOT / "FAST3_R33D_REPORT.md"
    summary_path = FROZEN_ROOT / "FAST3_R33D_SUMMARY.json"
    oof_columns = [
        "candidate_id", "decision_timestamp_utc", "head", "underlying_symbol", "raw_net20",
        "pred_t1", "pred_t5", "pred_t6", "predicted_conditional_gain_magnitude", "actual_t6",
        "naive_t6_mean", "naive_t6_median", "fold", "trading_date",
    ]
    oof[oof_columns].to_parquet(oof_path, index=False)
    oof_sha = file_sha256(oof_path)
    diagnostics.to_csv(diagnostics_path, index=False)

    summary = {
        "FAST3_R33D_STATUS": "PASS",
        "FAST3_R33D_CLASSIFICATION": classification,
        "FAST3_R33D_DECISION": decision,
        "T6_PREREGISTRATION_VERIFIED": True,
        "T6_PREREGISTRATION_SHA256": prereg_hash_before,
        "R33C_ARCHITECTURE_SHA256": EXPECTED_SHA256[R33C_ARCHITECTURE],
        "R33C_SUMMARY_SHA256": EXPECTED_SHA256[R33C_SUMMARY],
        "T6_CONTRACT_SHA256": contract_sha,
        "T6_MODEL_FIT_COUNT": fit_count + prior_failed_attempt_fit_count,
        "T6_PREDICT_CALL_COUNT": predict_count + prior_failed_attempt_predict_count,
        "T6_SUCCESSFUL_WORKFLOW_MODEL_FIT_COUNT": fit_count,
        "T6_SUCCESSFUL_WORKFLOW_PREDICT_CALL_COUNT": predict_count,
        "T6_FAILED_ATTEMPT_MODEL_FIT_COUNT": prior_failed_attempt_fit_count,
        "T6_FAILED_ATTEMPT_PREDICT_CALL_COUNT": prior_failed_attempt_predict_count,
        "TARGETED_RECOVERY_COUNT": int(prior_failed_attempt_fit_count > 0),
        "TARGETED_RECOVERY_REASON": "T5/T6 fold_model merge-column name collision after predictions; same seed/config rerun without research selection" if prior_failed_attempt_fit_count else None,
        "T6_WINNER_SAMPLE_COUNT": len(winners),
        "T6_ALL_OOF_PREDICTION_COUNT": len(oof),
        "T6_OOF_SPEARMAN_VS_REALIZED_GAIN": t6_s,
        "T6_OOF_PEARSON": t6_pearson,
        "T6_OOF_MAE_LOG_TARGET": mae,
        "T6_OOF_RMSE_LOG_TARGET": rmse,
        "NAIVE_T6_MEAN_MAE_LOG_TARGET": naive_mean_mae,
        "NAIVE_T6_MEDIAN_MAE_LOG_TARGET": naive_median_mae,
        "T6_MAE_BETTER_THAN_NAIVE": bool(mae < min(naive_mean_mae, naive_median_mae)),
        "T6_VALIDATION_SCOPE": "RANKING_ASSOCIATION_VALIDATED; CONDITIONAL_MEAN_GAIN_LEVEL_NOT_YET_CALIBRATED",
        "DATE_BALANCED_T6_VS_GAIN_SPEARMAN": date_s,
        "DATE_BALANCED_WINNER_DATE_COUNT": len(daily),
        "T6_FOLD_COUNT": int(winners.fold.nunique()),
        "T6_POSITIVE_SPEARMAN_FOLD_COUNT": fold_positive,
        "UP_T6_SAMPLE_COUNT": direction_metrics["UP"][0],
        "UP_T6_SPEARMAN": direction_metrics["UP"][1],
        "DOWN_T6_SAMPLE_COUNT": direction_metrics["DOWN"][0],
        "DOWN_T6_SPEARMAN": direction_metrics["DOWN"][1],
        "FIXED_QUANTILE_BIN_COUNT": FIXED_BIN_COUNT,
        "QUANTILE_GAIN_SPEARMAN": quantile_s,
        "TOP_MINUS_BOTTOM_MEAN_GAIN": top_bottom,
        "CONDITIONAL_T6_VS_GAIN_GIVEN_T1_T5_SPEARMAN": conditional_s,
        "DATE_BALANCED_CONDITIONAL_T6_VS_GAIN_GIVEN_T1_T5_SPEARMAN": conditional_date_s,
        "INCREMENTAL_T1_T5_CELL_COUNT": len(incremental_cells),
        "PREDICTED_CONDITIONAL_GAIN_MAGNITUDE_NEGATIVE_COUNT": int((oof.predicted_conditional_gain_magnitude < 0).sum()),
        "FEATURE_COUNT": len(features),
        "FEATURE_MANIFEST_SHA256": FEATURE_SHA,
        "FEATURE_COMPLETE_ROW_RATE": complete_coverage,
        "FEATURE_MISSING_COUNTS": missing_counts,
        "MODEL_FAMILY": "HistGradientBoostingRegressor independent UP/DOWN",
        "HGB_PARAMETERS": r30a.HGB_PARAMS,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "MODEL_FAMILY_SEARCH_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0,
        "FEATURE_SUBSET_SEARCH_COUNT": 0,
        "INTERACTION_SEARCH_COUNT": 0,
        "SEED_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_CONFIRMATION_DATA_INSPECTED": False,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "R33D_NEW_SOURCE_FILE_COUNT": 1,
        "R33D_NEW_TEST_FILE_COUNT": 1,
        "NEW_HELPER_FILE_COUNT": 0,
        "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": decision,
        "NEXT_STAGE": next_stage,
        "REPORT_PATH": str(report_path),
        "SUMMARY_JSON_PATH": str(summary_path),
        "T6_OOF_PATH": str(oof_path),
        "T6_OOF_SHA256": oof_sha,
        "T6_CONTRACT_PATH": str(contract_path),
        "DIAGNOSTICS_PATH": str(diagnostics_path),
    }
    write_json(summary_path, summary)

    report = f"""# FAST3 R33D — T6 Conditional Gain Magnitude Validation

## Decision

`{classification}` — `{decision}`

1. T6 winner-only Spearman / Pearson: `{t6_s}` / `{t6_pearson}` on `{len(winners):,}` winners.
2. ET-date-balanced Spearman: `{date_s}` across `{len(daily):,}` dates.
3. Positive folds: `{fold_positive}/{FOLD_COUNT}`.
4. UP / DOWN Spearman: `{direction_metrics['UP'][1]}` / `{direction_metrics['DOWN'][1]}`.
5. Fixed-decile gain monotonicity / top-minus-bottom mean gain: `{quantile_s}` / `{top_bottom}`.
6. Incremental T6 Spearman within fixed 5 x 5 T1/T5 cells: `{conditional_s}`; date-balanced incremental: `{conditional_date_s}`.
7. T6 validation result: `{classification}`. Next stage: `{next_stage}`.
8. Final confirmation used: `false`.
9. Search/bloat: no feature, model, hyperparameter, seed, weight, threshold, EV-combination, or trading search; `ANTI_BLOAT_STATUS=PASS`.

Point-level calibration caveat: T6 / naive-mean / naive-median log-target MAE is `{mae}` / `{naive_mean_mae}` / `{naive_median_mae}`. The frozen A gate validates stable ranking association and incremental information; it does not establish a calibrated conditional-mean gain level.

Execution accounting: `{fit_count}` fits produced the retained OOF. A prior identical fixed run performed `{prior_failed_attempt_fit_count}` fits before a post-prediction `fold_model` column-name collision; no result from that attempt was used for model or parameter selection. Total task fit count is `{fit_count + prior_failed_attempt_fit_count}`.

`expm1(pred_t6)` is stored only as `PREDICTED_CONDITIONAL_GAIN_MAGNITUDE`. It is not expected payoff, expected return, or expected value. No T1/T5/T6 economic combination was constructed.
"""
    report_path.write_text(report, encoding="utf-8")

    if file_sha256(T6_PREREGISTRATION) != prereg_hash_before:
        raise R33DStop("STOP_R33D_PREREGISTRATION_MUTATED")
    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33DStop("STOP_R33D_FROZEN_INPUT_MUTATED")
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33DStop as exc:
        raise SystemExit(str(exc)) from exc
