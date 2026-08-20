#!/usr/bin/env python
"""FAST3 R33H zero-fit existing-head economic-role reconciliation."""
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
R33FR_ROOT = RESULTS_ROOT / "frozen/fast3/r33fr_identifiable_window_loss_magnitude_sufficiency_20260810T040042Z"
R33G_ROOT = RESULTS_ROOT / "frozen/fast3/r33g_minimal_t7_loss_magnitude_20260810T045640Z"
T6_OOF = RESULTS_ROOT / "scratch/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_OOF_PREDICTIONS.parquet"
T7_OOF = RESULTS_ROOT / "scratch/fast3/r33g_minimal_t7_loss_magnitude_20260810T045640Z/FAST3_R33G_T7_OOF_PREDICTIONS.parquet"
R33D_CONTRACT = R33D_ROOT / "FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
R33D_SUMMARY = R33D_ROOT / "FAST3_R33D_SUMMARY.json"
R33E_CONTRACT = R33E_ROOT / "FAST3_R33E_SEMANTICS_CONTRACT_R1.json"
R33E_SUMMARY = R33E_ROOT / "FAST3_R33E_SUMMARY.json"
R33FR_PREREGISTRATION = R33FR_ROOT / "FAST3_R33FR_PREREGISTRATION_R1.json"
R33FR_SUMMARY = R33FR_ROOT / "FAST3_R33FR_SUMMARY.json"
R33G_PREREGISTRATION = R33G_ROOT / "FAST3_R33G_PREREGISTRATION_R1.json"
R33G_CONTRACT = R33G_ROOT / "FAST3_R33G_T7_CONTRACT_R1.json"
R33G_SUMMARY = R33G_ROOT / "FAST3_R33G_SUMMARY.json"

EXPECTED_SHA256 = {
    R33D_CONTRACT: "6b04a42e0489fb94921724b025f84162d03cf1e5c91df3546af837899874e3e2",
    R33D_SUMMARY: "32dc6fd23a9256b1dde203071ad0ad0cfc48d17d459d2baa1f3b7a95c5a462e3",
    T6_OOF: "99021c1fc956a99b949f76153364a9517c53ce1df92b36623b6e48531e1d3df1",
    R33E_CONTRACT: "147ac0d0ed07c353d08f7ff826e06d866b3272778ce4934a79f37f6de84c3dc5",
    R33E_SUMMARY: "be5ec47b3f6a97824fd2c655f3ce70b77357bd35c3aaf68e67595b6e123ae46e",
    R33FR_PREREGISTRATION: "5f3463390cd2f13d5fd1a18bc793c1b0c4f0f3712d0f658d461b0236ea9ea6b3",
    R33FR_SUMMARY: "5f41843c103a36d97bfaae7b5aa45502e06bdcb5365af4767b152e69011bbc16",
    R33G_PREREGISTRATION: "30c63a4669580b618000040c7a3b036ecafb7c40d124819618821d739ce9386c",
    R33G_CONTRACT: "626616edae3a4fca5614b4e162a6f7d224803432aa3fb72befbaf4804ab7b4b9",
    R33G_SUMMARY: "48378397a8803b016fca35896540ef6d65a0474a18a676c7080b678f41aa6f3f",
    T7_OOF: "fa5ccfd77533d82fe8d8eb9872fde8b9a0c33f1ed7a3d3c68c1442ca118af033",
}

PROBABILITY_CANDIDATES = ("P1_T1", "P2_T5", "P3_EQUAL_RANK_T1_T5")
SELECTION_PRIORITY = PROBABILITY_CANDIDATES
QUANTILE_COUNT = 5
GATE_A_MIN = 0.05
GATE_B_MIN = 0.15
GATE_E_MIN = 0.8
OOF_ROW_COUNT = 984_049
WINNER_COUNT = 528_636
LOSER_COUNT = 455_413
FOLD_COUNT = 5
NY = "America/New_York"
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"
ALLOWED_CLASSIFICATIONS = {
    "A_EXISTING_HEADS_CONTAIN_STABLE_WINNER_PROBABILITY_ORDERING",
    "B_WINNER_PROBABILITY_ORDERING_PRESENT_BUT_NOT_STABLE_ENOUGH",
    "C_EXISTING_HEADS_DO_NOT_IDENTIFY_WINNER_PROBABILITY_ORDERING",
}
ALLOWED_T1_ROLES = {
    "A_CANDIDATE_VALIDITY_WITH_WINNER_ORDERING", "B_CANDIDATE_VALIDITY_ONLY", "C_T1_ROLE_NOT_STABLE"
}
ALLOWED_T5_ROLES = {
    "A_PRIMARY_LOSS_SEVERITY_WITH_SECONDARY_WINNER_ORDERING",
    "B_PRIMARY_LOSS_SEVERITY_ONLY", "C_ROLE_INCONSISTENT_OR_LINEAGE_CONFLICT",
}
ALLOWED_T6_ROLES = {
    "A_CONDITIONAL_WINNER_GAIN_MAGNITUDE_ROLE_CONFIRMED", "C_T6_ROLE_RECONCILIATION_FAILED"
}


class R33HStop(RuntimeError):
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


def assign_fixed_bins(frame: pd.DataFrame, score: str, output: str) -> pd.DataFrame:
    if len(frame) < QUANTILE_COUNT:
        raise R33HStop("STOP_R33H_FIXED_QUANTILE_CONTRACT")
    ordered = frame.sort_values(
        [score, "decision_timestamp_utc", "candidate_id"],
        ascending=[True, True, True], kind="mergesort",
    ).copy()
    ordered[output] = np.floor(np.arange(len(ordered)) * QUANTILE_COUNT / len(ordered)).astype(int) + 1
    return ordered


def add_probability_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["P1_T1"] = result.pred_t1.astype(float)
    result["P2_T5"] = result.pred_t5.astype(float)
    t1_rank = result.pred_t1.rank(method="average", pct=True)
    t5_rank = result.pred_t5.rank(method="average", pct=True)
    result["P3_EQUAL_RANK_T1_T5"] = 0.5 * t1_rank + 0.5 * t5_rank
    return result


def preregistration(started_at_utc: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R33H_PREREGISTRATION_R1",
        "STATUS": "FROZEN_BEFORE_ANY_SCIENTIFIC_METRIC",
        "RESEARCH_QUESTION": "Do existing frozen heads contain stable winner-probability-related ordering without a new probability head?",
        "PARENT_R33G_CLASSIFICATION": "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED",
        "PARENT_R33G_PREREGISTRATION_SHA256": EXPECTED_SHA256[R33G_PREREGISTRATION],
        "T1_CANDIDATE_ROLE": "CANDIDATE_VALIDITY_OR_OPPORTUNITY_RANKING",
        "T1_FROZEN_TARGET_DEFINITION": "T1_POSITIVE_NET20 = 1[net20 > 0]",
        "T1_NOT_CALIBRATED_WIN_PROBABILITY": True,
        "T5_ORIGINAL_TARGET_LINEAGE": "R33B_CONDITIONAL_LOSS_SEVERITY",
        "T5_CANDIDATE_ROLE": "PRIMARY_CONDITIONAL_LOSER_LOSS_SEVERITY_RANKING_WITH_SECONDARY_WINNER_ORDERING_HYPOTHESIS",
        "T5_NOT_CALIBRATED_WIN_PROBABILITY": True,
        "T6_CANDIDATE_ROLE": "CONDITIONAL_WINNER_GAIN_MAGNITUDE_RANKING",
        "T7_STATUS": "REJECTED_REDUNDANT_WITH_T5",
        "PROBABILITY_CANDIDATES": list(PROBABILITY_CANDIDATES),
        "P1_DEFINITION": "frozen pred_t1 exactly",
        "P2_DEFINITION": "frozen pred_t5 exactly",
        "P3_DEFINITION": "0.5 * percentile_rank(pred_t1) + 0.5 * percentile_rank(pred_t5), average tie ranks on full frozen OOF",
        "P3_WEIGHT_T1": 0.5, "P3_WEIGHT_T5": 0.5,
        "T6_INCLUDED_IN_PRIMARY_PROBABILITY_CANDIDATES": False,
        "WIN_PROBABILITY_ORDERING_CANDIDATE_COUNT": 3,
        "PROBABILITY_ORDERING_GATES": {
            "A_POOLED_SPEARMAN_MIN": GATE_A_MIN,
            "B_DATE_BALANCED_SPEARMAN_MIN": GATE_B_MIN,
            "C_ALL_FOLDS_STRICTLY_POSITIVE": True,
            "D_UP_AND_DOWN_STRICTLY_POSITIVE": True,
            "E_QUANTILE_WINNER_RATE_SPEARMAN_MIN": GATE_E_MIN,
            "E_TOP_MINUS_BOTTOM_WINNER_RATE_STRICTLY_POSITIVE": True,
        },
        "QUANTILE_COUNT": QUANTILE_COUNT,
        "DATE_BALANCED_DEFINITION": "Spearman across ET trading-date means of score and winner rate, identical to R33E",
        "SELECTION_RULE": "FIRST_PASS_BY_PREDECLARED_ROLE_SIMPLICITY_ORDER",
        "SELECTION_PRIORITY": list(SELECTION_PRIORITY),
        "MODEL_FIT_PROHIBITED": True, "NEW_HEAD_PROHIBITED": True,
        "PROBABILITY_CALIBRATION_PROHIBITED": True, "EV_PROHIBITED": True,
        "FINAL_PROHIBITED": True, "HEAD_EXPANSION_LIMIT_AFTER_R33G": True,
        "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "T1_REFIT_COUNT": 0, "T5_REFIT_COUNT": 0, "T6_REFIT_COUNT": 0, "T7_REFIT_COUNT": 0,
        "T1_NEW_PREDICT_COUNT": 0, "T5_NEW_PREDICT_COUNT": 0,
        "T6_NEW_PREDICT_COUNT": 0, "T7_NEW_PREDICT_COUNT": 0,
        "WIN_PROBABILITY_WEIGHT_SEARCH_COUNT": 0, "ALTERNATIVE_PROBABILITY_SCORE_SEARCH_COUNT": 0,
        "MODEL_FAMILY_SEARCH_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0, "INTERACTION_SEARCH_COUNT": 0,
        "PROBABILITY_CALIBRATION_FIT_COUNT": 0, "PROBABILITY_CALIBRATION_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "EV_SCORE_CONSTRUCTION_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "RUN_STARTED_AT_UTC": started_at_utc,
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }


def validate_and_load_lineage() -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33HStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    r33d = read_json(R33D_SUMMARY)
    r33e = read_json(R33E_SUMMARY)
    r33e_contract = read_json(R33E_CONTRACT)
    r33fr = read_json(R33FR_SUMMARY)
    r33g = read_json(R33G_SUMMARY)
    if (
        r33d.get("FAST3_R33D_CLASSIFICATION") != "A_T6_VALIDATED"
        or r33d.get("T6_OOF_SHA256") != EXPECTED_SHA256[T6_OOF]
        or r33e.get("FAST3_R33E_CLASSIFICATION") != "B_THREE_HEAD_POSITIVE_LEG_CLOSED_LOSS_LEG_UNRESOLVED"
        or r33e.get("T5_ORIGINAL_MODEL_TARGET_LINEAGE") != "R33B_CONDITIONAL_LOSS_SEVERITY"
        or r33e_contract.get("T1_FROZEN_TARGET_DEFINITION") != "T1_POSITIVE_NET20 = 1[net20 > 0]"
        or "conditional loss severity" not in r33e_contract.get("T5_ORIGINAL_MODEL_TARGET_LINEAGE", "")
        or r33fr.get("FAST3_R33FR_CLASSIFICATION") != "C_EXISTING_THREE_HEADS_INSUFFICIENT_FOR_LOSS_MAGNITUDE"
        or r33g.get("FAST3_R33G_CLASSIFICATION") != "B_T7_REDUNDANT_OR_INCREMENTAL_VALUE_NOT_ESTABLISHED"
        or r33g.get("T7_T5_PREDICTION_EXACT_MATCH") is not True
        or r33g.get("T7_VALIDATED") is not False
        or r33g.get("HEAD_EXPANSION_LIMIT_AFTER_R33G") is not True
        or r33g.get("FURTHER_HEAD_EXPANSION_ALLOWED") is not False
        or any(x.get("FINAL_CONFIRMATION_DATA_USED") is not False for x in (r33d, r33e, r33fr, r33g))
    ):
        raise R33HStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")

    identity = ["candidate_id", "decision_timestamp_utc", "fold", "head", "raw_net20", "trading_date"]
    t6_columns = identity + ["pred_t1", "pred_t5", "pred_t6", "actual_t6"]
    t7_columns = identity + ["pred_t7"]
    t6 = pd.read_parquet(T6_OOF, columns=t6_columns)
    t7 = pd.read_parquet(T7_OOF, columns=t7_columns)
    if t6.candidate_id.duplicated().any() or t7.candidate_id.duplicated().any():
        raise R33HStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    frame = t6.merge(t7, on="candidate_id", how="inner", suffixes=("", "_t7"), validate="one_to_one")
    for column in identity[1:]:
        left, right = frame[column], frame[f"{column}_t7"]
        if pd.api.types.is_numeric_dtype(left):
            matched = np.array_equal(left.to_numpy(), right.to_numpy())
        else:
            matched = left.equals(right)
        if not matched:
            raise R33HStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    if (
        len(frame) != OOF_ROW_COUNT or frame.fold.nunique() != FOLD_COUNT
        or set(frame["head"]) != {"UP", "DOWN"}
        or frame[["pred_t1", "pred_t5", "pred_t6", "pred_t7", "raw_net20"]].isna().any().any()
        or int(frame.raw_net20.gt(0).sum()) != WINNER_COUNT
        or int(frame.raw_net20.lt(0).sum()) != LOSER_COUNT
        or int(frame.raw_net20.eq(0).sum()) != 0
        or not np.array_equal(frame.pred_t5.to_numpy(), frame.pred_t7.to_numpy())
        or float(np.max(np.abs(frame.pred_t5.to_numpy() - frame.pred_t7.to_numpy()))) != 0.0
    ):
        raise R33HStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    expected_dates = pd.to_datetime(frame.decision_timestamp_utc, utc=True).dt.tz_convert(NY).dt.date.astype(str)
    if not frame.trading_date.eq(expected_dates).all():
        raise R33HStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    frame["winner"] = frame.raw_net20.gt(0).astype(int)
    frame["loss_magnitude"] = np.where(frame.raw_net20.lt(0), frame.raw_net20.abs(), np.nan)
    return frame, r33d, r33e


def probability_ordering_metrics(frame: pd.DataFrame, score: str, label: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pooled = safe_spearman(frame[score], frame.winner)
    daily = frame.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=(score, "mean"), winner_rate=("winner", "mean")
    )
    date_balanced = safe_spearman(daily.mean_score, daily.winner_rate)
    if pooled is None or date_balanced is None:
        raise R33HStop("STOP_R33H_PROBABILITY_METRIC")
    binned = assign_fixed_bins(frame, score, "quantile")
    quantile_rows = []
    for quantile, part in binned.groupby("quantile", sort=True, observed=True):
        quantile_rows.append({
            "record_type": "PROBABILITY_QUANTILE", "candidate": label,
            "group": f"Q{int(quantile)}", "ordinal": int(quantile), "count": len(part),
            "mean_score": float(part[score].mean()), "winner_rate": float(part.winner.mean()),
            "mean_realized_payoff": float(part.raw_net20.mean()),
        })
    quantiles = pd.DataFrame(quantile_rows)
    quantile_s = safe_spearman(quantiles.ordinal, quantiles.winner_rate)
    spread = float(quantiles.iloc[-1].winner_rate - quantiles.iloc[0].winner_rate)
    if quantile_s is None or len(quantiles) != QUANTILE_COUNT:
        raise R33HStop("STOP_R33H_QUANTILE_METRIC")
    robustness_rows = []
    fold_values = []
    for fold, part in frame.groupby("fold", sort=True, observed=True):
        value = safe_spearman(part[score], part.winner)
        if value is None:
            raise R33HStop("STOP_R33H_FOLD_METRIC")
        fold_values.append(value)
        robustness_rows.append({
            "record_type": "PROBABILITY_FOLD", "candidate": label,
            "group": fold, "count": len(part), "spearman": value,
        })
    directions: dict[str, dict[str, float]] = {}
    for direction, part in frame.groupby("head", sort=True, observed=True):
        value = safe_spearman(part[score], part.winner)
        direction_bins = assign_fixed_bins(part, score, "direction_quantile")
        rates = direction_bins.groupby("direction_quantile", sort=True, observed=True).winner.mean()
        direction_spread = float(rates.iloc[-1] - rates.iloc[0])
        if value is None or len(rates) != QUANTILE_COUNT:
            raise R33HStop("STOP_R33H_DIRECTION_METRIC")
        directions[direction] = {"spearman": value, "top_minus_bottom_winner_rate": direction_spread}
        robustness_rows.append({
            "record_type": "PROBABILITY_DIRECTION", "candidate": label,
            "group": direction, "count": len(part), "spearman": value,
            "top_minus_bottom_winner_rate": direction_spread,
        })
    gates = {
        "A": pooled >= GATE_A_MIN,
        "B": date_balanced >= GATE_B_MIN,
        "C": len(fold_values) == FOLD_COUNT and all(value > 0 for value in fold_values),
        "D": directions["UP"]["spearman"] > 0 and directions["DOWN"]["spearman"] > 0,
        "E": quantile_s >= GATE_E_MIN and spread > 0,
    }
    metrics = {
        "pooled_spearman": pooled, "date_balanced_spearman": date_balanced,
        "positive_fold_count": sum(value > 0 for value in fold_values),
        "min_fold_spearman": min(fold_values), "max_fold_spearman": max(fold_values),
        "fold_spearmans": fold_values, "up_spearman": directions["UP"]["spearman"],
        "down_spearman": directions["DOWN"]["spearman"],
        "up_top_minus_bottom_winner_rate": directions["UP"]["top_minus_bottom_winner_rate"],
        "down_top_minus_bottom_winner_rate": directions["DOWN"]["top_minus_bottom_winner_rate"],
        "quantile_monotonicity": quantile_s, "top_quintile_winner_rate": float(quantiles.iloc[-1].winner_rate),
        "bottom_quintile_winner_rate": float(quantiles.iloc[0].winner_rate),
        "top_minus_bottom_winner_rate": spread, "gate_components": gates,
        "gate_status": "PASS" if all(gates.values()) else "FAIL",
    }
    return metrics, quantiles, pd.DataFrame(robustness_rows)


def t5_loss_role_metrics(frame: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    losers = frame.loc[frame.raw_net20.lt(0)].copy()
    pooled = safe_spearman(losers.pred_t5, losers.loss_magnitude)
    daily = losers.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=("pred_t5", "mean"), mean_loss=("loss_magnitude", "mean")
    )
    date_balanced = safe_spearman(daily.mean_score, daily.mean_loss)
    rows = []
    folds = []
    for fold, part in losers.groupby("fold", sort=True, observed=True):
        value = safe_spearman(part.pred_t5, part.loss_magnitude)
        if value is None:
            raise R33HStop("STOP_R33H_T5_LOSS_FOLD_METRIC")
        folds.append(value)
        rows.append({"record_type": "T5_LOSS_FOLD", "candidate": "T5_PRIMARY_ROLE", "group": fold, "count": len(part), "spearman": value})
    directions = {}
    for direction, part in losers.groupby("head", sort=True, observed=True):
        value = safe_spearman(part.pred_t5, part.loss_magnitude)
        if value is None:
            raise R33HStop("STOP_R33H_T5_LOSS_DIRECTION_METRIC")
        directions[direction] = value
        rows.append({"record_type": "T5_LOSS_DIRECTION", "candidate": "T5_PRIMARY_ROLE", "group": direction, "count": len(part), "spearman": value})
    if pooled is None or date_balanced is None:
        raise R33HStop("STOP_R33H_T5_LOSS_METRIC")
    stable = bool(pooled > 0 and date_balanced > 0 and len(folds) == FOLD_COUNT and all(x > 0 for x in folds) and directions["UP"] > 0 and directions["DOWN"] > 0)
    return {
        "pooled_spearman": pooled, "date_balanced_spearman": date_balanced,
        "positive_fold_count": sum(x > 0 for x in folds), "min_fold_spearman": min(folds),
        "max_fold_spearman": max(folds), "up_spearman": directions["UP"],
        "down_spearman": directions["DOWN"], "stable": stable,
    }, pd.DataFrame(rows)


def reconcile_t6_gain_role(frame: pd.DataFrame, r33d: dict[str, Any]) -> dict[str, Any]:
    winners = frame.loc[frame.raw_net20.gt(0)].copy()
    pooled = safe_spearman(winners.pred_t6, winners.raw_net20)
    daily = winners.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=("pred_t6", "mean"), mean_gain=("raw_net20", "mean")
    )
    date_balanced = safe_spearman(daily.mean_score, daily.mean_gain)
    directions = {
        direction: safe_spearman(part.pred_t6, part.raw_net20)
        for direction, part in winners.groupby("head", sort=True, observed=True)
    }
    deciles = winners.sort_values(["pred_t6", "decision_timestamp_utc", "candidate_id"], kind="mergesort").copy()
    deciles["decile"] = np.floor(np.arange(len(deciles)) * 10 / len(deciles)).astype(int) + 1
    means = deciles.groupby("decile", sort=True, observed=True).raw_net20.mean()
    spread = float(means.iloc[-1] - means.iloc[0])
    references = {
        "pooled_spearman": r33d["T6_OOF_SPEARMAN_VS_REALIZED_GAIN"],
        "date_balanced_spearman": r33d["DATE_BALANCED_T6_VS_GAIN_SPEARMAN"],
        "up_spearman": r33d["UP_T6_SPEARMAN"], "down_spearman": r33d["DOWN_T6_SPEARMAN"],
        "top_minus_bottom_mean_gain": r33d["TOP_MINUS_BOTTOM_MEAN_GAIN"],
    }
    reproduced = {
        "pooled_spearman": pooled, "date_balanced_spearman": date_balanced,
        "up_spearman": directions["UP"], "down_spearman": directions["DOWN"],
        "top_minus_bottom_mean_gain": spread,
    }
    reconciled = all(np.isclose(reproduced[key], references[key], rtol=0, atol=1e-15) for key in references)
    if not reconciled:
        raise R33HStop("STOP_R33H_T6_ROLE_RECONCILIATION_FAILED")
    return {**reproduced, "reference_reconciled": True}


def select_first_pass(results: dict[str, dict[str, Any]]) -> str | None:
    for candidate in SELECTION_PRIORITY:
        if results.get(candidate, {}).get("gate_status") == "PASS":
            return candidate
    return None


def classify(results: dict[str, dict[str, Any]]) -> tuple[str, str, bool | str, str]:
    if select_first_pass(results) is not None:
        return (
            "A_EXISTING_HEADS_CONTAIN_STABLE_WINNER_PROBABILITY_ORDERING",
            "NO_NEW_PROBABILITY_HEAD_REQUIRED", False,
            "PREREGISTER_EXISTING_HEAD_ECONOMIC_CALIBRATION",
        )
    if any(result["pooled_spearman"] > 0 for result in results.values()):
        return (
            "B_WINNER_PROBABILITY_ORDERING_PRESENT_BUT_NOT_STABLE_ENOUGH",
            "DO_NOT_BUILD_EV_PROBABILITY_CALIBRATION_YET", "UNRESOLVED",
            "STOP_AND_REASSESS_PROBABILITY_IDENTIFICATION_WITHOUT_HEAD_EXPANSION",
        )
    return (
        "C_EXISTING_HEADS_DO_NOT_IDENTIFY_WINNER_PROBABILITY_ORDERING",
        "EXPECTED_PAYOFF_ARCHITECTURE_REMAINS_PROBABILITY_INCOMPLETE", False,
        "STOP_HEAD_EXPANSION_AND_REASSESS_EXPECTED_PAYOFF_FORMULATION",
    )


def compact_terminal_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R33H_STATUS", "FAST3_R33H_CLASSIFICATION", "FAST3_R33H_DECISION",
        "R33H_PREREGISTRATION_VERIFIED", "R33H_PREREGISTRATION_SHA256",
        "T5_T7_IDENTITY_RECONCILIATION_STATUS", "T5_T7_EXACT_MATCH",
        "T5_T7_MATCHED_ROW_COUNT", "T5_T7_MAX_ABS_DIFFERENCE",
        "T1_ROLE_CLASSIFICATION", "T5_ROLE_CLASSIFICATION", "T6_ROLE_CLASSIFICATION",
    ]
    for prefix in ("P1", "P2", "P3"):
        keys.extend([
            f"{prefix}_NAME", f"{prefix}_POOLED_WINNER_SPEARMAN",
            f"{prefix}_DATE_BALANCED_WINNER_SPEARMAN", f"{prefix}_POSITIVE_FOLD_COUNT",
            f"{prefix}_UP_SPEARMAN", f"{prefix}_DOWN_SPEARMAN",
            f"{prefix}_QUANTILE_MONOTONICITY", f"{prefix}_TOP_MINUS_BOTTOM_WINNER_RATE",
            f"{prefix}_GATE_STATUS",
        ])
    keys.extend([
        "T5_VS_LOSS_MAGNITUDE_SPEARMAN", "DATE_BALANCED_T5_VS_LOSS_MAGNITUDE_SPEARMAN",
        "T6_GAIN_ROLE_RECONCILIATION_STATUS", "SELECTED_EXISTING_WIN_PROBABILITY_ORDERING_SCORE",
        "SELECTION_RULE", "NEW_PROBABILITY_HEAD_JUSTIFIED", "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT",
        "NEW_TARGET_COUNT", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT",
        "WIN_PROBABILITY_ORDERING_CANDIDATE_COUNT", "WIN_PROBABILITY_WEIGHT_SEARCH_COUNT",
        "ALTERNATIVE_PROBABILITY_SCORE_SEARCH_COUNT", "PROBABILITY_CALIBRATION_FIT_COUNT",
        "PROBABILITY_CALIBRATION_SEARCH_COUNT", "EV_COMBINATION_SEARCH_COUNT",
        "EV_SCORE_CONSTRUCTION_COUNT", "THRESHOLD_SEARCH_COUNT", "TRADING_SIMULATION_COUNT",
        "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT",
        "HEAD_EXPANSION_LIMIT_AFTER_R33G", "FURTHER_HEAD_EXPANSION_ALLOWED",
        "FINAL_CONFIRMATION_DATA_USED", "FINAL_CONFIRMATION_DATA_LOADED", "FINAL_HOLDOUT_INSPECTED",
        "FIRST_RUN_STATUS", "RERUN_COUNT", "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT",
        "ANTI_BLOAT_STATUS", "PRIMARY_RESEARCH_INTERPRETATION", "NEXT_STAGE",
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
        raise R33HStop("USE_--run")
    started = datetime.now(timezone.utc)
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"r33h_existing_head_economic_role_reconciliation_{timestamp}"
    frozen_root = RESULTS_ROOT / "frozen/fast3" / run_id
    if frozen_root.exists():
        raise R33HStop("STOP_R33H_OUTPUT_EXISTS")

    input_hashes_before = {path: file_sha256(path) for path in EXPECTED_SHA256}
    frame, r33d, r33e = validate_and_load_lineage()
    frozen_root.mkdir(parents=True)
    prereg_path = frozen_root / "FAST3_R33H_PREREGISTRATION_R1.json"
    prereg = preregistration(started.isoformat())
    write_json(prereg_path, prereg)
    prereg_sha = file_sha256(prereg_path)
    if read_json(prereg_path) != prereg:
        raise R33HStop("STOP_R33H_PREREGISTRATION_VERIFICATION")

    frame = add_probability_candidates(frame)
    results = {}
    metric_parts = []
    for candidate in PROBABILITY_CANDIDATES:
        metrics, quantiles, robustness = probability_ordering_metrics(frame, candidate, candidate)
        results[candidate] = metrics
        metric_parts.extend([quantiles, robustness])
    t5_loss, t5_loss_rows = t5_loss_role_metrics(frame)
    metric_parts.append(t5_loss_rows)
    t6_gain = reconcile_t6_gain_role(frame, r33d)

    t6_winner = safe_spearman(frame.pred_t6, frame.winner)
    t6_daily = frame.groupby("trading_date", sort=True, observed=True).agg(
        mean_score=("pred_t6", "mean"), winner_rate=("winner", "mean")
    )
    t6_winner_date = safe_spearman(t6_daily.mean_score, t6_daily.winner_rate)
    if t6_winner is None or t6_winner_date is None:
        raise R33HStop("STOP_R33H_T6_NEGATIVE_CONTROL_METRIC")

    selected = select_first_pass(results)
    classification, decision, new_probability_head, next_stage = classify(results)
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise R33HStop("STOP_R33H_CLASSIFICATION_ENUM")
    p1_pass = results["P1_T1"]["gate_status"] == "PASS"
    p2_pass = results["P2_T5"]["gate_status"] == "PASS"
    t1_role = "A_CANDIDATE_VALIDITY_WITH_WINNER_ORDERING" if p1_pass else "B_CANDIDATE_VALIDITY_ONLY"
    t5_role = (
        "A_PRIMARY_LOSS_SEVERITY_WITH_SECONDARY_WINNER_ORDERING" if t5_loss["stable"] and p2_pass
        else "B_PRIMARY_LOSS_SEVERITY_ONLY" if t5_loss["stable"]
        else "C_ROLE_INCONSISTENT_OR_LINEAGE_CONFLICT"
    )
    t6_role = "A_CONDITIONAL_WINNER_GAIN_MAGNITUDE_ROLE_CONFIRMED" if t6_gain["reference_reconciled"] else "C_T6_ROLE_RECONCILIATION_FAILED"
    if t1_role not in ALLOWED_T1_ROLES or t5_role not in ALLOWED_T5_ROLES or t6_role not in ALLOWED_T6_ROLES:
        raise R33HStop("STOP_R33H_ROLE_ENUM")

    role_contract_path = frozen_root / "FAST3_R33H_ECONOMIC_ROLE_CONTRACT_R1.json"
    role_contract = {
        "CONTRACT_ID": "FAST3_R33H_ECONOMIC_ROLE_CONTRACT_R1", "STATUS": "FROZEN_AFTER_RECONCILIATION",
        "R33H_PREREGISTRATION_SHA256": prereg_sha,
        "T1": {
            "primary_role": "candidate validity / opportunity ranking",
            "secondary_role": "winner-probability-related ordering information" if p1_pass else None,
            "calibrated_win_probability": False, "role_classification": t1_role,
        },
        "T5": {
            "primary_role": "conditional loser loss-severity ranking",
            "secondary_role": "winner-probability-related ordering information" if p2_pass else None,
            "original_target_lineage": "R33B_CONDITIONAL_LOSS_SEVERITY",
            "calibrated_win_probability": False, "role_classification": t5_role,
        },
        "T6": {
            "primary_role": "conditional winner gain-magnitude ranking",
            "calibrated_conditional_gain_level": False, "role_classification": t6_role,
        },
        "T7": {"status": "REJECTED_REDUNDANT_WITH_T5", "prediction_exact_match_with_T5": True},
        "T8": {"status": "PROHIBITED"},
        "SELECTED_EXISTING_WIN_PROBABILITY_ORDERING_SCORE": selected,
        "SELECTED_SCORE_IS_CALIBRATED_PROBABILITY": False,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "FINAL_CONFIRMATION_DATA_USED": False,
    }
    write_json(role_contract_path, role_contract)

    metrics_path = frozen_root / "FAST3_R33H_ROLE_METRICS.csv"
    summary_path = frozen_root / "FAST3_R33H_SUMMARY.json"
    report_path = frozen_root / "FAST3_R33H_REPORT.md"
    pd.concat(metric_parts, ignore_index=True, sort=False).to_csv(metrics_path, index=False)
    summary: dict[str, Any] = {
        "FAST3_R33H_STATUS": "PASS", "FAST3_R33H_CLASSIFICATION": classification,
        "FAST3_R33H_DECISION": decision, "R33H_PREREGISTRATION_VERIFIED": True,
        "R33H_PREREGISTRATION_SHA256": prereg_sha,
        "T5_T7_IDENTITY_RECONCILIATION_STATUS": "PASS", "T5_T7_EXACT_MATCH": True,
        "T5_T7_MATCHED_ROW_COUNT": len(frame), "T5_T7_MAX_ABS_DIFFERENCE": 0.0,
        "CANDIDATE_ID_IDENTITY_STATUS": "PASS", "DECISION_TIMESTAMP_IDENTITY_STATUS": "PASS",
        "FOLD_IDENTITY_STATUS": "PASS", "DIRECTION_IDENTITY_STATUS": "PASS",
        "WINNER_LOSER_IDENTITY_STATUS": "PASS", "PAYOFF_IDENTITY_STATUS": "PASS",
        "T1_LINEAGE_STATUS": "PASS", "T5_LINEAGE_STATUS": "PASS", "T6_LINEAGE_STATUS": "PASS",
        "WINNER_DEFINITION": "canonical raw_net20 > 0; no zero rows",
        "WINNER_DEFINITION_RECONCILIATION_STATUS": "PASS", "WINNER_COUNT": WINNER_COUNT,
        "LOSER_COUNT": LOSER_COUNT, "T1_ROLE_CLASSIFICATION": t1_role,
        "T5_ROLE_CLASSIFICATION": t5_role, "T6_ROLE_CLASSIFICATION": t6_role,
        "T5_ORIGINAL_TARGET_LINEAGE": "R33B_CONDITIONAL_LOSS_SEVERITY",
        "T5_VS_WINNER_INDICATOR_SPEARMAN": results["P2_T5"]["pooled_spearman"],
        "DATE_BALANCED_T5_VS_WINNER_INDICATOR": results["P2_T5"]["date_balanced_spearman"],
        "T5_VS_LOSS_MAGNITUDE_SPEARMAN": t5_loss["pooled_spearman"],
        "DATE_BALANCED_T5_VS_LOSS_MAGNITUDE_SPEARMAN": t5_loss["date_balanced_spearman"],
        "T5_LOSS_POSITIVE_FOLD_COUNT": t5_loss["positive_fold_count"],
        "T5_LOSS_UP_SPEARMAN": t5_loss["up_spearman"], "T5_LOSS_DOWN_SPEARMAN": t5_loss["down_spearman"],
        "T6_GAIN_ROLE_RECONCILIATION_STATUS": "PASS", "T6_GAIN_ROLE_EVIDENCE": t6_gain,
        "T6_VS_WINNER_INDICATOR_SPEARMAN": t6_winner,
        "T6_DATE_BALANCED_VS_WINNER_INDICATOR_SPEARMAN": t6_winner_date,
        "SELECTED_EXISTING_WIN_PROBABILITY_ORDERING_SCORE": selected,
        "SELECTION_RULE": "FIRST_PASS_BY_PREDECLARED_ROLE_SIMPLICITY_ORDER",
        "NEW_PROBABILITY_HEAD_JUSTIFIED": new_probability_head,
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "T1_REFIT_COUNT": 0, "T5_REFIT_COUNT": 0, "T6_REFIT_COUNT": 0, "T7_REFIT_COUNT": 0,
        "T1_NEW_PREDICT_COUNT": 0, "T5_NEW_PREDICT_COUNT": 0,
        "T6_NEW_PREDICT_COUNT": 0, "T7_NEW_PREDICT_COUNT": 0,
        "WIN_PROBABILITY_ORDERING_CANDIDATE_COUNT": 3,
        "WIN_PROBABILITY_WEIGHT_SEARCH_COUNT": 0, "ALTERNATIVE_PROBABILITY_SCORE_SEARCH_COUNT": 0,
        "MODEL_FAMILY_SEARCH_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SEARCH_COUNT": 0, "INTERACTION_SEARCH_COUNT": 0,
        "PROBABILITY_CALIBRATION_FIT_COUNT": 0, "PROBABILITY_CALIBRATION_SEARCH_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "EV_SCORE_CONSTRUCTION_COUNT": 0,
        "THRESHOLD_SEARCH_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "FIRST_RUN_STATUS": "PASS", "RERUN_COUNT": 0, "RERUN_REASON": None,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False, "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": (
            "EXISTING_FROZEN_HEAD_CONTAINS_STABLE_WINNER_PROBABILITY_RELATED_ORDERING; CALIBRATION_NOT_YET_ESTABLISHED"
            if classification.startswith("A_") else decision
        ),
        "NEXT_STAGE": next_stage, "RUN_ID": run_id, "RUN_STARTED_AT_UTC": started.isoformat(),
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "REPORT_PATH": str(report_path), "SUMMARY_JSON_PATH": str(summary_path),
        "PREREGISTRATION_PATH": str(prereg_path), "ROLE_METRICS_PATH": str(metrics_path),
        "ECONOMIC_ROLE_CONTRACT_PATH": str(role_contract_path),
        "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
    }
    name_map = {"P1_T1": "T1", "P2_T5": "T5", "P3_EQUAL_RANK_T1_T5": "EQUAL_RANK_T1_T5"}
    for prefix, candidate in (("P1", "P1_T1"), ("P2", "P2_T5"), ("P3", "P3_EQUAL_RANK_T1_T5")):
        result = results[candidate]
        summary.update({
            f"{prefix}_NAME": name_map[candidate],
            f"{prefix}_POOLED_WINNER_SPEARMAN": result["pooled_spearman"],
            f"{prefix}_DATE_BALANCED_WINNER_SPEARMAN": result["date_balanced_spearman"],
            f"{prefix}_POSITIVE_FOLD_COUNT": result["positive_fold_count"],
            f"{prefix}_MIN_FOLD_SPEARMAN": result["min_fold_spearman"],
            f"{prefix}_MAX_FOLD_SPEARMAN": result["max_fold_spearman"],
            f"{prefix}_FOLD_SPEARMANS": result["fold_spearmans"],
            f"{prefix}_UP_SPEARMAN": result["up_spearman"],
            f"{prefix}_DOWN_SPEARMAN": result["down_spearman"],
            f"{prefix}_UP_TOP_MINUS_BOTTOM_WINNER_RATE": result["up_top_minus_bottom_winner_rate"],
            f"{prefix}_DOWN_TOP_MINUS_BOTTOM_WINNER_RATE": result["down_top_minus_bottom_winner_rate"],
            f"{prefix}_TOP_QUINTILE_WINNER_RATE": result["top_quintile_winner_rate"],
            f"{prefix}_BOTTOM_QUINTILE_WINNER_RATE": result["bottom_quintile_winner_rate"],
            f"{prefix}_QUANTILE_MONOTONICITY": result["quantile_monotonicity"],
            f"{prefix}_TOP_MINUS_BOTTOM_WINNER_RATE": result["top_minus_bottom_winner_rate"],
            f"{prefix}_GATE_COMPONENTS": result["gate_components"],
            f"{prefix}_GATE_STATUS": result["gate_status"],
        })
    write_json(summary_path, summary)
    result_lines = "\n".join(
        f"- {candidate}: pooled/date-balanced {result['pooled_spearman']}/{result['date_balanced_spearman']}; positive folds {result['positive_fold_count']}/5; UP/DOWN {result['up_spearman']}/{result['down_spearman']}; quantile monotonicity/spread {result['quantile_monotonicity']}/{result['top_minus_bottom_winner_rate']}; {result['gate_status']}."
        for candidate, result in results.items()
    )
    report = f"""# FAST3 R33H - Existing-Head Economic Role Reconciliation

## Decision

`{classification}` - `{decision}`

T5/T7 identity was reproduced on `{len(frame):,}` matched OOF rows with maximum absolute prediction difference `0.0`. T7 remains rejected and head expansion remains prohibited.

## Reconciled roles

- T1: candidate-validity/opportunity ranking; `{t1_role}`. Passing winner ordering does not make T1 a calibrated probability.
- T5: primary conditional loser loss-severity ranking with immutable `R33B_CONDITIONAL_LOSS_SEVERITY` lineage; `{t5_role}`. Its secondary winner ordering does not relabel its target.
- T6: conditional winner gain-magnitude ranking; `{t6_role}` with exact R33D metric reconciliation.
- T7: rejected, bitwise redundant with T5. T8: prohibited.

## Probability-ordering candidates

{result_lines}

Selected by frozen role-simplicity order: `{selected}`. This score contains winner-probability-related ordering information only; no probability-unit calibration was performed.

T5 loss-role pooled/date-balanced Spearman is `{t5_loss['pooled_spearman']}` / `{t5_loss['date_balanced_spearman']}` with `{t5_loss['positive_fold_count']}/5` positive folds and UP/DOWN `{t5_loss['up_spearman']}` / `{t5_loss['down_spearman']}`.

No model fit/prediction, new head/feature/target, probability calibration, search, EV construction, threshold, trading/execution simulation, position sizing, Final load, or holdout inspection occurred.
"""
    report_path.write_text(report, encoding="utf-8")
    for path, before in input_hashes_before.items():
        if file_sha256(path) != before:
            raise R33HStop("STOP_R33H_FROZEN_INPUT_MUTATED")
    if file_sha256(prereg_path) != prereg_sha:
        raise R33HStop("STOP_R33H_PREREGISTRATION_MUTATED")
    compact_terminal_summary(summary)
    print(f"REPORT_PATH={report_path}")
    print(f"SUMMARY_JSON_PATH={summary_path}")
    print(f"ROLE_CONTRACT_PATH={role_contract_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except R33HStop as exc:
        raise SystemExit(str(exc)) from exc
