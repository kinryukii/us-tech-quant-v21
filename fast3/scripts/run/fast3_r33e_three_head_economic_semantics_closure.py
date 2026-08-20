#!/usr/bin/env python
"""FAST3 R33E read-only three-head economic-semantics closure audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


SOURCE_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
RUN_ID = "r33e_three_head_economic_semantics_20260811T020000Z"
FROZEN_ROOT = RESULTS_ROOT / "frozen/fast3" / RUN_ID

R33C_ROOT = RESULTS_ROOT / "frozen/fast3/r33c_architecture_design_20260810T220000Z"
R33D_ROOT = RESULTS_ROOT / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z"
R33C_SUMMARY = R33C_ROOT / "FAST3_R33C_SUMMARY.json"
R33C_ARCHITECTURE = R33C_ROOT / "FAST3_R33C_ARCHITECTURE_DESIGN_R1.json"
R33D_SUMMARY = R33D_ROOT / "FAST3_R33D_SUMMARY.json"
R33D_CONTRACT = R33D_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
R33D_OOF = RESULTS_ROOT / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"

EXPECTED_SHA256 = {
    R33C_SUMMARY: "30be62215fd720b3fb71895e67e98acff4860b17106298e3ab6ca17b31ad54db",
    R33C_ARCHITECTURE: "1652bd597425907185fd96c002656f91a814bc59c92469336745cd2930139958",
    R33D_SUMMARY: "32dc6fd23a9256b1dde203071ad0ad0cfc48d17d459d2baa1f3b7a95c5a462e3",
    R33D_CONTRACT: "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2",
    R33D_OOF: "99021c1fc956a99b949f76153364a9517c53ce1df92b36623b6e48531e1d3df1",
}
OOF_ROW_COUNT = 984_049
WINNER_COUNT = 528_636
LOSER_COUNT = 455_413
FOLD_COUNT = 5
HEAD_BUCKET_COUNT = 5
LOSS_JOINT_BUCKET_COUNT = 3
R33D_RECONCILIATION_BIN_COUNT = 10
NY = "America/New_York"

# Frozen before R33E outcomes are summarized. These are architecture-diagnostic
# materiality gates, not searched trading or prediction thresholds.
LOSS_MIN_ABS_POOLED_SPEARMAN = 0.10
LOSS_MIN_ABS_DATE_BALANCED_SPEARMAN = 0.20
LOSS_MIN_SAME_SIGN_FOLD_COUNT = 4
LOSS_REQUIRED_SAME_SIGN_DIRECTION_COUNT = 2
LOSS_MIN_ABS_TOP_BOTTOM_RELATIVE_SPREAD = 0.15

ALLOWED_CLASSIFICATIONS = {
    "A_THREE_HEAD_ECONOMIC_SEMANTICS_CLOSED",
    "B_THREE_HEAD_POSITIVE_LEG_CLOSED_LOSS_LEG_UNRESOLVED",
    "C_HEAD_SEMANTICS_NOT_STABLE",
}


class R33EStop(RuntimeError):
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


def safe_spearman(left: Any, right: Any) -> float | None:
    x, y = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 2 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return None
    value = float(spearmanr(x, y).statistic)
    return value if np.isfinite(value) else None


def assign_fixed_bins(frame: pd.DataFrame, score: str, bins: int, output: str) -> pd.DataFrame:
    if len(frame) < bins:
        raise R33EStop(f"STOP_R33E_TOO_FEW_ROWS_FOR_{output}")
    ordered = frame.sort_values(
        [score, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True],
        kind="mergesort",
    ).copy()
    ordered[output] = np.floor(np.arange(len(ordered)) * bins / len(ordered)).astype(int) + 1
    return ordered


def loss_magnitude(net20: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=net20.index, dtype=float)
    losers = net20.lt(0)
    result.loc[losers] = net20.loc[losers].abs()
    return result


def validate_lineage() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33EStop("STOP_R33E_DATA_OR_LINEAGE_INTEGRITY")
    r33c = read_json(R33C_SUMMARY)
    r33d = read_json(R33D_SUMMARY)
    architecture = read_json(R33C_ARCHITECTURE)
    contract = read_json(R33D_CONTRACT)
    if (
        r33c.get("FAST3_R33C_CLASSIFICATION") != "B_T1_T5_INSUFFICIENT_CONDITIONAL_GAIN_HEAD_REQUIRED"
        or r33d.get("FAST3_R33D_CLASSIFICATION") != "A_T6_VALIDATED"
        or r33d.get("T6_OOF_SHA256") != EXPECTED_SHA256[R33D_OOF]
        or r33d.get("T6_ALL_OOF_PREDICTION_COUNT") != OOF_ROW_COUNT
        or r33d.get("T6_WINNER_SAMPLE_COUNT") != WINNER_COUNT
        or r33d.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33d.get("FINAL_CONFIRMATION_DATA_INSPECTED") is not False
        or r33c.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or r33c.get("FINAL_CONFIRMATION_DATA_INSPECTED") is not False
        or architecture.get("SELECTED_ARCHITECTURE") != "T1 + T5 + T6"
        or contract.get("FINAL_CONFIRMATION_DATA_USED") is not False
        or contract.get("VALIDATION_PREDICTION_SCOPE") != "all OOF eligible validation candidates"
    ):
        raise R33EStop("STOP_R33E_DATA_OR_LINEAGE_INTEGRITY")

    columns = [
        "candidate_id", "decision_timestamp_utc", "head", "underlying_symbol", "raw_net20",
        "pred_t1", "pred_t5", "pred_t6", "actual_t6", "fold", "trading_date",
    ]
    frame = pd.read_parquet(R33D_OOF, columns=columns)
    if (
        len(frame) != OOF_ROW_COUNT
        or frame.candidate_id.duplicated().any()
        or frame[["raw_net20", "pred_t1", "pred_t5", "pred_t6"]].isna().any().any()
        or frame.fold.nunique() != FOLD_COUNT
        or set(frame["head"]) != {"UP", "DOWN"}
        or int(frame.raw_net20.gt(0).sum()) != WINNER_COUNT
        or int(frame.raw_net20.lt(0).sum()) != LOSER_COUNT
        or int(frame.raw_net20.eq(0).sum()) != 0
    ):
        raise R33EStop("STOP_R33E_DATA_OR_LINEAGE_INTEGRITY")
    expected_dates = frame.decision_timestamp_utc.dt.tz_convert(NY).dt.date.astype(str)
    if (
        not frame.trading_date.eq(expected_dates).all()
        or frame.decision_timestamp_utc.max() >= pd.Timestamp("2025-02-01T05:00:00Z")
        or frame.loc[frame.raw_net20 > 0, "actual_t6"].isna().any()
        or frame.loc[frame.raw_net20 < 0, "actual_t6"].notna().any()
        or not np.allclose(
            frame.loc[frame.raw_net20 > 0, "actual_t6"],
            np.log1p(frame.loc[frame.raw_net20 > 0, "raw_net20"]),
            rtol=0,
            atol=1e-15,
        )
    ):
        raise R33EStop("STOP_R33E_DATA_OR_LINEAGE_INTEGRITY")
    return frame, r33c, r33d


def mean_within_date_spearman(frame: pd.DataFrame, score: str, outcome: str) -> tuple[float, int]:
    values = []
    for _, part in frame.groupby("trading_date", sort=True, observed=True):
        value = safe_spearman(part[score], part[outcome])
        if value is not None:
            values.append(value)
    if not values:
        raise R33EStop("STOP_R33E_EMPTY_WITHIN_DATE_DIAGNOSTIC")
    return float(np.mean(values)), len(values)


def probability_semantics(
    frame: pd.DataFrame,
    score: str,
    head_name: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    x = frame.copy()
    x["winner"] = x.raw_net20.gt(0).astype(int)
    pooled = safe_spearman(x[score], x.winner)
    binned = assign_fixed_bins(x, score, HEAD_BUCKET_COUNT, "bucket")
    bucket_rows = []
    for bucket, part in binned.groupby("bucket", sort=True, observed=True):
        daily = part.groupby("trading_date", sort=True, observed=True).agg(
            winner_rate=("winner", "mean"), mean_net20=("raw_net20", "mean")
        )
        bucket_rows.append(
            {
                "record_type": f"{head_name}_PROBABILITY_BUCKET",
                "group": f"BUCKET_{int(bucket)}",
                "ordinal": int(bucket),
                "count": len(part),
                "mean_score": float(part[score].mean()),
                "winner_rate": float(part.winner.mean()),
                "mean_net20": float(part.raw_net20.mean()),
                "date_balanced_winner_rate": float(daily.winner_rate.mean()),
                "date_balanced_mean_net20": float(daily.mean_net20.mean()),
            }
        )
    buckets = pd.DataFrame(bucket_rows)
    quantile_s = safe_spearman(buckets.ordinal, buckets.winner_rate)
    top_bottom = float(buckets.iloc[-1].winner_rate - buckets.iloc[0].winner_rate)
    by_date = x.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=(score, "mean"), winner_rate=("winner", "mean")
    )
    date_s = safe_spearman(by_date.mean_score, by_date.winner_rate)
    within_date_s, within_date_count = mean_within_date_spearman(x, score, "winner")

    robustness_rows = []
    fold_positive = 0
    for fold, part in x.groupby("fold", sort=True, observed=True):
        value = safe_spearman(part[score], part.winner)
        fold_positive += int(value is not None and value > 0)
        robustness_rows.append(
            {"record_type": f"{head_name}_PROBABILITY_FOLD", "group": fold, "count": len(part), "spearman": value}
        )
    direction_values: dict[str, float] = {}
    for direction, part in x.groupby("head", sort=True, observed=True):
        value = safe_spearman(part[score], part.winner)
        if value is None:
            raise R33EStop("STOP_R33E_HEAD_DIRECTION_METRIC")
        direction_values[direction] = value
        robustness_rows.append(
            {"record_type": f"{head_name}_PROBABILITY_DIRECTION", "group": direction, "count": len(part), "spearman": value}
        )
    if any(value is None for value in (pooled, quantile_s, date_s)):
        raise R33EStop("STOP_R33E_HEAD_SEMANTICS_METRIC")
    stable = bool(
        pooled > 0
        and quantile_s > 0
        and date_s > 0
        and within_date_s > 0
        and fold_positive >= 3
        and direction_values["UP"] > 0
        and direction_values["DOWN"] > 0
        and top_bottom > 0
    )
    metrics = {
        "pooled_spearman": pooled,
        "quantile_winner_rate_spearman": quantile_s,
        "top_minus_bottom_winner_rate": top_bottom,
        "date_balanced_spearman": date_s,
        "mean_within_date_spearman": within_date_s,
        "within_date_count": within_date_count,
        "fold_count": int(x.fold.nunique()),
        "positive_spearman_fold_count": fold_positive,
        "up_spearman": direction_values["UP"],
        "down_spearman": direction_values["DOWN"],
        "stable": stable,
    }
    return metrics, buckets, pd.DataFrame(robustness_rows)


def t6_semantics(
    frame: pd.DataFrame,
    r33d: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    winners = frame.loc[frame.raw_net20 > 0].copy()
    pooled = safe_spearman(winners.pred_t6, winners.raw_net20)
    by_date = winners.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=("pred_t6", "mean"), mean_gain=("raw_net20", "mean")
    )
    date_s = safe_spearman(by_date.mean_score, by_date.mean_gain)
    within_date_s, within_date_count = mean_within_date_spearman(winners, "pred_t6", "raw_net20")
    reference = assign_fixed_bins(winners, "pred_t6", R33D_RECONCILIATION_BIN_COUNT, "bucket")
    reference_means = reference.groupby("bucket", sort=True, observed=True).raw_net20.mean()
    reference_spread = float(reference_means.iloc[-1] - reference_means.iloc[0])

    binned = assign_fixed_bins(winners, "pred_t6", HEAD_BUCKET_COUNT, "bucket")
    bucket_rows = []
    for bucket, part in binned.groupby("bucket", sort=True, observed=True):
        daily_gain = part.groupby("trading_date", sort=True, observed=True).raw_net20.mean()
        bucket_rows.append(
            {
                "record_type": "T6_GAIN_BUCKET",
                "group": f"BUCKET_{int(bucket)}",
                "ordinal": int(bucket),
                "count": len(part),
                "mean_score": float(part.pred_t6.mean()),
                "mean_gain": float(part.raw_net20.mean()),
                "median_gain": float(part.raw_net20.median()),
                "date_balanced_mean_gain": float(daily_gain.mean()),
            }
        )
    buckets = pd.DataFrame(bucket_rows)
    quantile_s = safe_spearman(buckets.ordinal, buckets.mean_gain)
    robustness_rows = []
    fold_positive = 0
    for fold, part in winners.groupby("fold", sort=True, observed=True):
        value = safe_spearman(part.pred_t6, part.raw_net20)
        fold_positive += int(value is not None and value > 0)
        robustness_rows.append(
            {"record_type": "T6_GAIN_FOLD", "group": fold, "count": len(part), "spearman": value}
        )
    directions: dict[str, float] = {}
    for direction, part in winners.groupby("head", sort=True, observed=True):
        value = safe_spearman(part.pred_t6, part.raw_net20)
        if value is None:
            raise R33EStop("STOP_R33E_T6_DIRECTION_METRIC")
        directions[direction] = value
        robustness_rows.append(
            {"record_type": "T6_GAIN_DIRECTION", "group": direction, "count": len(part), "spearman": value}
        )
    reconciled = bool(
        np.isclose(pooled, r33d["T6_OOF_SPEARMAN_VS_REALIZED_GAIN"], rtol=0, atol=1e-15)
        and np.isclose(date_s, r33d["DATE_BALANCED_T6_VS_GAIN_SPEARMAN"], rtol=0, atol=1e-15)
        and np.isclose(directions["UP"], r33d["UP_T6_SPEARMAN"], rtol=0, atol=1e-15)
        and np.isclose(directions["DOWN"], r33d["DOWN_T6_SPEARMAN"], rtol=0, atol=1e-15)
        and np.isclose(reference_spread, r33d["TOP_MINUS_BOTTOM_MEAN_GAIN"], rtol=0, atol=1e-15)
    )
    if not reconciled:
        raise R33EStop("STOP_R33E_T6_LINEAGE_JOIN_DEFINITION_MISMATCH")
    if quantile_s is None:
        raise R33EStop("STOP_R33E_T6_QUANTILE_METRIC")
    stable = bool(
        pooled > 0
        and date_s > 0
        and within_date_s > 0
        and quantile_s > 0
        and fold_positive >= 3
        and directions["UP"] > 0
        and directions["DOWN"] > 0
    )
    metrics = {
        "winner_count": len(winners),
        "pooled_spearman": pooled,
        "date_balanced_spearman": date_s,
        "mean_within_date_spearman": within_date_s,
        "within_date_count": within_date_count,
        "positive_spearman_fold_count": fold_positive,
        "up_spearman": directions["UP"],
        "down_spearman": directions["DOWN"],
        "five_bucket_gain_spearman": quantile_s,
        "r33d_ten_decile_top_minus_bottom_mean_gain": reference_spread,
        "r33d_reference_reconciled": reconciled,
        "stable": stable,
    }
    return metrics, buckets, pd.DataFrame(robustness_rows)


def loss_distribution_stats(losers: pd.DataFrame) -> dict[str, float | int]:
    loss = losers.loss_magnitude
    median = float(loss.median())
    return {
        "count": len(loss),
        "mean": float(loss.mean()),
        "median": median,
        "p05": float(loss.quantile(0.05)),
        "p25": float(loss.quantile(0.25)),
        "p75": float(loss.quantile(0.75)),
        "p95": float(loss.quantile(0.95)),
        "std": float(loss.std(ddof=1)),
        "median_absolute_deviation": float((loss - median).abs().median()),
    }


def loss_head_diagnostic(
    losers: pd.DataFrame,
    score: str,
    head_name: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pooled = safe_spearman(losers[score], losers.loss_magnitude)
    binned = assign_fixed_bins(losers, score, HEAD_BUCKET_COUNT, "bucket")
    bucket_rows = []
    for bucket, part in binned.groupby("bucket", sort=True, observed=True):
        daily = part.groupby("trading_date", sort=True, observed=True).loss_magnitude.mean()
        bucket_rows.append(
            {
                "record_type": f"{head_name}_LOSS_BUCKET",
                "group": f"BUCKET_{int(bucket)}",
                "ordinal": int(bucket),
                "count": len(part),
                "mean_score": float(part[score].mean()),
                "mean_loss_magnitude": float(part.loss_magnitude.mean()),
                "median_loss_magnitude": float(part.loss_magnitude.median()),
                "date_balanced_mean_loss_magnitude": float(daily.mean()),
            }
        )
    buckets = pd.DataFrame(bucket_rows)
    quantile_s = safe_spearman(buckets.ordinal, buckets.mean_loss_magnitude)
    top_bottom = float(buckets.iloc[-1].mean_loss_magnitude - buckets.iloc[0].mean_loss_magnitude)
    relative_spread = float(top_bottom / losers.loss_magnitude.mean())
    by_date = losers.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=(score, "mean"), mean_loss=("loss_magnitude", "mean")
    )
    date_s = safe_spearman(by_date.mean_score, by_date.mean_loss)
    within_date_s, within_date_count = mean_within_date_spearman(losers, score, "loss_magnitude")
    if any(value is None for value in (pooled, quantile_s, date_s)):
        raise R33EStop("STOP_R33E_LOSS_METRIC")
    sign = 1 if pooled > 0 else -1 if pooled < 0 else 0
    robustness_rows = []
    same_sign_folds = 0
    for fold, part in losers.groupby("fold", sort=True, observed=True):
        value = safe_spearman(part[score], part.loss_magnitude)
        same = bool(value is not None and sign != 0 and value * sign > 0)
        same_sign_folds += int(same)
        robustness_rows.append(
            {"record_type": f"{head_name}_LOSS_FOLD", "group": fold, "count": len(part), "spearman": value, "same_sign_as_pooled": same}
        )
    same_sign_directions = 0
    directions: dict[str, float] = {}
    for direction, part in losers.groupby("head", sort=True, observed=True):
        value = safe_spearman(part[score], part.loss_magnitude)
        if value is None:
            raise R33EStop("STOP_R33E_LOSS_DIRECTION_METRIC")
        directions[direction] = value
        same = bool(sign != 0 and value * sign > 0)
        same_sign_directions += int(same)
        robustness_rows.append(
            {"record_type": f"{head_name}_LOSS_DIRECTION", "group": direction, "count": len(part), "spearman": value, "same_sign_as_pooled": same}
        )
    materially_stable = bool(
        abs(pooled) >= LOSS_MIN_ABS_POOLED_SPEARMAN
        and abs(date_s) >= LOSS_MIN_ABS_DATE_BALANCED_SPEARMAN
        and same_sign_folds >= LOSS_MIN_SAME_SIGN_FOLD_COUNT
        and same_sign_directions == LOSS_REQUIRED_SAME_SIGN_DIRECTION_COUNT
        and abs(relative_spread) >= LOSS_MIN_ABS_TOP_BOTTOM_RELATIVE_SPREAD
    )
    metrics = {
        "pooled_spearman": pooled,
        "quantile_mean_loss_spearman": quantile_s,
        "top_minus_bottom_mean_loss": top_bottom,
        "top_minus_bottom_relative_mean_loss": relative_spread,
        "date_balanced_spearman": date_s,
        "mean_within_date_spearman": within_date_s,
        "within_date_count": within_date_count,
        "same_sign_fold_count": same_sign_folds,
        "same_sign_direction_count": same_sign_directions,
        "up_spearman": directions["UP"],
        "down_spearman": directions["DOWN"],
        "materially_stable_heterogeneity": materially_stable,
    }
    return metrics, buckets, pd.DataFrame(robustness_rows)


def joint_loss_cells(losers: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    t5 = assign_fixed_bins(losers, "pred_t5", LOSS_JOINT_BUCKET_COUNT, "t5_bucket")
    both = assign_fixed_bins(t5, "pred_t6", LOSS_JOINT_BUCKET_COUNT, "t6_bucket")
    rows = []
    for (t5_bucket, t6_bucket), part in both.groupby(["t5_bucket", "t6_bucket"], sort=True, observed=True):
        daily = part.groupby("trading_date", sort=True, observed=True).loss_magnitude.mean()
        rows.append(
            {
                "record_type": "T5_T6_JOINT_LOSS_CELL",
                "group": f"T5_B{int(t5_bucket)}_T6_B{int(t6_bucket)}",
                "t5_bucket": int(t5_bucket),
                "t6_bucket": int(t6_bucket),
                "count": len(part),
                "mean_loss_magnitude": float(part.loss_magnitude.mean()),
                "median_loss_magnitude": float(part.loss_magnitude.median()),
                "date_balanced_mean_loss_magnitude": float(daily.mean()),
            }
        )
    cells = pd.DataFrame(rows)
    if len(cells) != LOSS_JOINT_BUCKET_COUNT ** 2:
        raise R33EStop("STOP_R33E_JOINT_CELL_CARDINALITY")
    relative_range = float(
        (cells.mean_loss_magnitude.max() - cells.mean_loss_magnitude.min()) / losers.loss_magnitude.mean()
    )
    return cells, relative_range


def classify(
    t1_stable: bool,
    t5_stable: bool,
    t6_stable: bool,
    loss_unresolved: bool,
) -> tuple[str, str, str, bool | str]:
    if not (t1_stable and t5_stable and t6_stable):
        return (
            "C_HEAD_SEMANTICS_NOT_STABLE",
            "AT_LEAST_ONE_FROZEN_HEAD_ECONOMIC_SEMANTIC_IS_NOT_STABLE",
            "STOP_EXPECTED_PAYOFF_ARCHITECTURE_PROGRESSION",
            "UNRESOLVED",
        )
    if loss_unresolved:
        return (
            "B_THREE_HEAD_POSITIVE_LEG_CLOSED_LOSS_LEG_UNRESOLVED",
            "THREE_HEAD_POSITIVE_LEG_CLOSED_BUT_LOSS_MAGNITUDE_COMPONENT_UNRESOLVED",
            "PREREGISTER_LOSS_MAGNITUDE_COMPONENT_STUDY",
            "UNRESOLVED",
        )
    return (
        "A_THREE_HEAD_ECONOMIC_SEMANTICS_CLOSED",
        "THREE_HEAD_ECONOMIC_SEMANTICS_CLOSED_WITH_FROZEN_CONSTANT_LOSS_PRIOR",
        "DESIGN_FROZEN_THREE_HEAD_EV_MAPPING",
        False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise R33EStop("USE_--run")
    if FROZEN_ROOT.exists():
        raise R33EStop("STOP_R33E_OUTPUT_EXISTS")

    input_hashes_before = {path: file_sha256(path) for path in EXPECTED_SHA256}
    frame, r33c, r33d = validate_lineage()
    FROZEN_ROOT.mkdir(parents=True)
    semantics_contract_path = FROZEN_ROOT / "FAST3_R33E_SEMANTICS_CONTRACT_R1.json"
    semantics_contract = {
        "CONTRACT_ID": "FAST3_R33E_SEMANTICS_CONTRACT_R1",
        "STATUS": "FROZEN_BEFORE_DESCRIPTIVE_STATISTICS",
        "T1_PREREGISTERED_INTERPRETATION": "opportunity / candidate validity information; higher T1 means higher candidate economic validity/quality ranking",
        "T1_FROZEN_TARGET_DEFINITION": "T1_POSITIVE_NET20 = 1[net20 > 0]",
        "T1_NOT_GAIN_MAGNITUDE_PREDICTOR": True,
        "T5_PREREGISTERED_INTERPRETATION": "winner / positive-payoff probability ranking information; higher T5 means higher P(realized payoff > 0 | candidate information)",
        "T5_NOT_MAGNITUDE_PREDICTOR_IN_R33E": True,
        "T5_ORIGINAL_MODEL_TARGET_LINEAGE": "R33B conditional loss severity log1p(abs(loss)) on strict losers; preserved and not relabeled",
        "T5_R33E_SEMANTIC_TEST_SCOPE": "behavioral OOF winner-probability ordering hypothesis only",
        "T6_PREREGISTERED_INTERPRETATION": "higher T6 means higher conditional winner gain ranking",
        "T6_LEVEL_EQUALS_EXPECTED_GAIN": False,
        "HEAD_BUCKET_COUNT": HEAD_BUCKET_COUNT,
        "LOSS_JOINT_GRID": f"{LOSS_JOINT_BUCKET_COUNT}x{LOSS_JOINT_BUCKET_COUNT} fixed T5 x T6 bins",
        "R33D_RECONCILIATION_BIN_COUNT": R33D_RECONCILIATION_BIN_COUNT,
        "HEAD_SEMANTICS_STABLE_GATE": "pooled > 0 AND quantile monotonicity > 0 AND date-balanced > 0 AND mean-within-date > 0 AND >=3/5 positive folds AND UP > 0 AND DOWN > 0 AND top-bottom > 0 (T6 uses gain equivalent)",
        "LOSS_MATERIAL_STABILITY_GATE": {
            "minimum_abs_pooled_spearman": LOSS_MIN_ABS_POOLED_SPEARMAN,
            "minimum_abs_date_balanced_spearman": LOSS_MIN_ABS_DATE_BALANCED_SPEARMAN,
            "minimum_same_sign_fold_count": LOSS_MIN_SAME_SIGN_FOLD_COUNT,
            "required_same_sign_direction_count": LOSS_REQUIRED_SAME_SIGN_DIRECTION_COUNT,
            "minimum_abs_top_bottom_relative_mean_loss_spread": LOSS_MIN_ABS_TOP_BOTTOM_RELATIVE_SPREAD,
            "decision": "any one of T1/T5/T6 satisfying all conditions makes loss magnitude component unresolved",
        },
        "BUCKET_SEARCH_ALLOWED": False,
        "MODEL_EXECUTION_ALLOWED": False,
        "EV_MAPPING_EXECUTED": False,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_HOLDOUT_INSPECTED": False,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }
    write_json(semantics_contract_path, semantics_contract)
    semantics_contract_sha = file_sha256(semantics_contract_path)

    t1, t1_buckets, t1_robustness = probability_semantics(frame, "pred_t1", "T1")
    t5, t5_buckets, t5_robustness = probability_semantics(frame, "pred_t5", "T5")
    t6, t6_buckets, t6_robustness = t6_semantics(frame, r33d)

    losers = frame.loc[frame.raw_net20 < 0].copy()
    losers["loss_magnitude"] = loss_magnitude(losers.raw_net20)
    if losers.loss_magnitude.isna().any() or not np.allclose(losers.loss_magnitude, -losers.raw_net20):
        raise R33EStop("STOP_R33E_LOSS_MAGNITUDE_DEFINITION")
    distribution = loss_distribution_stats(losers)
    loss_t1, loss_t1_buckets, loss_t1_robustness = loss_head_diagnostic(losers, "pred_t1", "T1")
    loss_t5, loss_t5_buckets, loss_t5_robustness = loss_head_diagnostic(losers, "pred_t5", "T5")
    loss_t6, loss_t6_buckets, loss_t6_robustness = loss_head_diagnostic(losers, "pred_t6", "T6")
    joint_cells, joint_relative_range = joint_loss_cells(losers)
    materially_stable_heads = [
        name
        for name, metrics in (("T1", loss_t1), ("T5", loss_t5), ("T6", loss_t6))
        if metrics["materially_stable_heterogeneity"]
    ]
    loss_unresolved = bool(materially_stable_heads)
    classification, decision, next_stage, loss_head_required = classify(
        t1["stable"], t5["stable"], t6["stable"], loss_unresolved
    )
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise R33EStop("STOP_R33E_CLASSIFICATION_ENUM")

    diagnostics = pd.concat(
        [
            t1_buckets,
            t5_buckets,
            t6_buckets,
            t1_robustness,
            t5_robustness,
            t6_robustness,
            loss_t1_buckets,
            loss_t5_buckets,
            loss_t6_buckets,
            loss_t1_robustness,
            loss_t5_robustness,
            loss_t6_robustness,
            joint_cells,
        ],
        ignore_index=True,
        sort=False,
    )
    diagnostics_path = FROZEN_ROOT / "FAST3_R33E_DIAGNOSTICS.csv"
    report_path = FROZEN_ROOT / "FAST3_R33E_REPORT.md"
    summary_path = FROZEN_ROOT / "FAST3_R33E_SUMMARY.json"
    diagnostics.to_csv(diagnostics_path, index=False)

    t1_status = "STABLE_CANDIDATE_VALIDITY_RANKING" if t1["stable"] else "UNSTABLE_CANDIDATE_VALIDITY_RANKING"
    t5_status = "STABLE_WINNER_PROBABILITY_RANKING" if t5["stable"] else "UNSTABLE_WINNER_PROBABILITY_RANKING"
    t6_status = "STABLE_CONDITIONAL_WINNER_GAIN_RANKING" if t6["stable"] else "UNSTABLE_CONDITIONAL_WINNER_GAIN_RANKING"
    loss_status = "LOSS_MAGNITUDE_COMPONENT_UNRESOLVED" if loss_unresolved else "LOSS_MAGNITUDE_HEAD_NOT_REQUIRED"
    summary = {
        "FAST3_R33E_STATUS": "PASS",
        "FAST3_R33E_CLASSIFICATION": classification,
        "FAST3_R33E_DECISION": decision,
        "T1_ECONOMIC_SEMANTICS_STATUS": t1_status,
        "T5_ECONOMIC_SEMANTICS_STATUS": t5_status,
        "T6_ECONOMIC_SEMANTICS_STATUS": t6_status,
        "T1_EVIDENCE": t1,
        "T5_EVIDENCE": t5,
        "T6_EVIDENCE": t6,
        "T5_ORIGINAL_MODEL_TARGET_LINEAGE": "R33B_CONDITIONAL_LOSS_SEVERITY",
        "T5_R33E_SEMANTIC_HYPOTHESIS": "WINNER_PROBABILITY_RANKING",
        "LOSS_MAGNITUDE_DIAGNOSTIC_STATUS": loss_status,
        "LOSS_MAGNITUDE_HEAD_REQUIRED": loss_head_required,
        "LOSS_MAGNITUDE_DISTRIBUTION": distribution,
        "LOSS_T1_DIAGNOSTIC": loss_t1,
        "LOSS_T5_DIAGNOSTIC": loss_t5,
        "LOSS_T6_DIAGNOSTIC": loss_t6,
        "LOSS_MATERIALLY_STABLE_HEADS": materially_stable_heads,
        "LOSS_T5_T6_3X3_RELATIVE_MEAN_RANGE": joint_relative_range,
        "NEW_HEAD_COUNT": 0,
        "NEW_TARGET_COUNT": 0,
        "NEW_FEATURE_COUNT": 0,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "HYPERPARAMETER_SEARCH_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0,
        "BUCKET_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0,
        "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False,
        "FINAL_HOLDOUT_INSPECTED": False,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "FIRST_RUN_STATUS": "PASS",
        "RERUN_REASON": None,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
        "R33E_NEW_SOURCE_FILE_COUNT": 1,
        "R33E_NEW_TEST_FILE_COUNT": 1,
        "NEW_HELPER_FILE_COUNT": 0,
        "ANTI_BLOAT_STATUS": "PASS",
        "R33C_SUMMARY_SHA256": EXPECTED_SHA256[R33C_SUMMARY],
        "R33D_SUMMARY_SHA256": EXPECTED_SHA256[R33D_SUMMARY],
        "R33D_T6_OOF_SHA256": EXPECTED_SHA256[R33D_OOF],
        "SEMANTICS_CONTRACT_SHA256": semantics_contract_sha,
        "PRIMARY_RESEARCH_INTERPRETATION": decision,
        "NEXT_STAGE": next_stage,
        "REPORT_PATH": str(report_path),
        "SUMMARY_JSON_PATH": str(summary_path),
        "DIAGNOSTICS_PATH": str(diagnostics_path),
        "SEMANTICS_CONTRACT_PATH": str(semantics_contract_path),
    }
    write_json(summary_path, summary)

    report = f"""# FAST3 R33E — Three-Head Economic Semantics Closure

## Preregistered semantics

- T1: opportunity/candidate-validity ranking, not gain magnitude.
- T5: winner/positive-payoff-probability ranking, not magnitude.
- T6: conditional winner-gain ranking only; its level is not `E[gain | winner, X]`.

The frozen T5 model-target lineage remains R33B conditional loss severity. R33E does not relabel that training target; it tests the newly preregistered winner-probability behavior directly on frozen OOF predictions.

## Decision

`{classification}` — `{decision}`

1. T1 semantics: `{t1_status}`. Pooled/date-balanced/within-date Spearman `{t1['pooled_spearman']}` / `{t1['date_balanced_spearman']}` / `{t1['mean_within_date_spearman']}`; positive folds `{t1['positive_spearman_fold_count']}/5`; UP/DOWN `{t1['up_spearman']}` / `{t1['down_spearman']}`; top-minus-bottom winner rate `{t1['top_minus_bottom_winner_rate']}`.
2. T5 semantics: `{t5_status}`. Pooled/date-balanced/within-date Spearman `{t5['pooled_spearman']}` / `{t5['date_balanced_spearman']}` / `{t5['mean_within_date_spearman']}`; positive folds `{t5['positive_spearman_fold_count']}/5`; UP/DOWN `{t5['up_spearman']}` / `{t5['down_spearman']}`; top-minus-bottom winner rate `{t5['top_minus_bottom_winner_rate']}`.
3. T6 semantics: `{t6_status}`. R33D pooled/date-balanced/UP/DOWN/top-bottom references are exactly reconciled: `{t6['r33d_reference_reconciled']}`.
4. Loser magnitude: `{loss_status}`. Count/mean/median/p05/p25/p75/p95/std/MAD: `{distribution['count']}` / `{distribution['mean']}` / `{distribution['median']}` / `{distribution['p05']}` / `{distribution['p25']}` / `{distribution['p75']}` / `{distribution['p95']}` / `{distribution['std']}` / `{distribution['median_absolute_deviation']}`.
5. Heads meeting the preregistered cross-fold/date/direction material loss-heterogeneity gate: `{materially_stable_heads}`. Fixed T5 x T6 3 x 3 relative mean-loss range: `{joint_relative_range}`.

No model fit/prediction, new head/target/feature, bucket search, EV/weight/threshold search, trading/execution simulation, or final-holdout operation occurred.

## OUT_OF_SCOPE_OBSERVATIONS

- Any next loss-component study must be separately preregistered; R33E did not create or train T7.
"""
    report_path.write_text(report, encoding="utf-8")

    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33EStop("STOP_R33E_FROZEN_INPUT_MUTATED")
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33EStop as exc:
        raise SystemExit(str(exc)) from exc
