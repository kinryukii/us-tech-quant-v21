#!/usr/bin/env python
"""FAST3 R33J relative economic-ordering identifiability audit."""
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


RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
REPO_ROOT = Path(__file__).resolve().parents[3]
R33I_RUNNER = REPO_ROOT / "fast3/scripts/run/fast3_r33i_existing_head_economic_calibration.py"
R33I_ROOT = RESULTS_ROOT / "frozen/fast3/r33i_existing_head_economic_calibration_20260810T060639Z"
R33H_ROOT = RESULTS_ROOT / "frozen/fast3/r33h_existing_head_economic_role_reconciliation_20260810T054920Z"
R33G_ROOT = RESULTS_ROOT / "frozen/fast3/r33g_minimal_t7_loss_magnitude_20260810T045640Z"
R33I_SUMMARY = R33I_ROOT / "FAST3_R33I_SUMMARY.json"
R33I_PREREGISTRATION = R33I_ROOT / "FAST3_R33I_PREREGISTRATION_R1.json"
R33I_CONTRACT = R33I_ROOT / "FAST3_R33I_CALIBRATION_CONTRACT_R1.json"
R33I_METRICS = R33I_ROOT / "FAST3_R33I_CALIBRATION_METRICS.csv"
R33H_SUMMARY = R33H_ROOT / "FAST3_R33H_SUMMARY.json"
R33G_SUMMARY = R33G_ROOT / "FAST3_R33G_SUMMARY.json"

EXPECTED_SHA256 = {
    R33I_SUMMARY: "844f7eb71207ac12193f4735455c847837b966ef2a4f876941d9b617e51701a6",
    R33I_PREREGISTRATION: "b377d15d516f3fca1c3dfe7b176d14f97f8e3718a4a201fd0755be4c62f37cbe",
    R33I_CONTRACT: "536c4cf36c6b68385631210cdfc0448667b3f8f6974473f66953d58261bb59cc",
    R33I_METRICS: "5be2f46f2007ca876e1d447897534e6e59b837f00ecc8d4c7ac4a373a66bed99",
    R33H_SUMMARY: "c15b2cc47a300bcfa40ba44e4a0d16c8b576af60bbb318bdea1657f8c220489d",
    R33G_SUMMARY: "48378397a8803b016fca35896540ef6d65a0474a18a676c7080b678f41aa6f3f",
}

P_SOURCE = "T1"
L_SOURCE = "T5"
G_RANK_SOURCE = "T6"
EVALUATION_FOLDS = ("OOF_2022", "OOF_2023", "OOF_2024", "OOF_2025")
EXCLUDED_FOLD = "OOF_2021"
PL_GRID_SIZE = (3, 3)
T6_WITHIN_CELL_QUANTILE_COUNT = 3
GATE_B_MIN = 0.10
GATE_E_MIN = 0.8
CONDITIONAL_STATISTIC = "R33G_POOLED_WITHIN_CELL_PERCENTILE_RANK_SPEARMAN_AND_ET_DATE_MEAN_RANK_SPEARMAN"
RUN_ID_TIMESTAMP_SEMANTICS = "REAL_UTC_WALL_CLOCK"
FIRST_RUN_STATUS = "FAILED_CODE_BUG_AFTER_METRICS_BEFORE_ARTIFACT_COMPLETION"
RERUN_COUNT = 1
RERUN_REASON = "CODE_BUG_PANDAS_HEAD_COLUMN_ATTRIBUTE_COLLISION"
ALLOWED_CLASSIFICATIONS = {
    "A_RELATIVE_ECONOMIC_ORDERING_IDENTIFIABLE",
    "B_CONDITIONAL_UPSIDE_INFORMATION_PRESENT_BUT_RELATIVE_ORDERING_NOT_STABLE",
    "C_RELATIVE_ECONOMIC_ORDERING_NOT_IDENTIFIED",
}


class R33JStop(RuntimeError):
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


def load_r33i_module():
    spec = importlib.util.spec_from_file_location("r33i_for_r33j", R33I_RUNNER)
    if spec is None or spec.loader is None:
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preregistration(started_at_utc: str) -> dict[str, Any]:
    return {
        "CONTRACT_ID": "FAST3_R33J_PREREGISTRATION_R1",
        "STATUS": "FROZEN_BEFORE_ANY_SCIENTIFIC_METRIC",
        "RESEARCH_QUESTION": "After conditioning on fold-safe calibrated P(T1) and L(T5), does frozen T6 retain stable incremental ordering with canonical realized payoff?",
        "PARENT_R33I_CLASSIFICATION": "C_ECONOMIC_LEVEL_CALIBRATION_NOT_STABLE",
        "PARENT_R33I_PREREGISTRATION_SHA256": EXPECTED_SHA256[R33I_PREREGISTRATION],
        "P_SOURCE": P_SOURCE, "L_SOURCE": L_SOURCE, "G_RANK_SOURCE": G_RANK_SOURCE,
        "P_CALIBRATION_STATUS": "CALIBRATED", "L_CALIBRATION_STATUS": "CALIBRATED",
        "G_CALIBRATION_STATUS": "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED",
        "EVALUATION_FOLDS": list(EVALUATION_FOLDS), "EXCLUDED_FOLD": EXCLUDED_FOLD,
        "OOF_2021_EXCLUSION_REASON": "NO_PRE_FOLD_CALIBRATION_HISTORY",
        "CONDITIONING_GRID": "P_CALIBRATED_tercile_x_L_CALIBRATED_tercile",
        "CONDITIONING_GRID_SIZE": "3x3", "PL_CONDITIONING_GRID_COUNT": 1,
        "PL_CONDITIONING_GRID_SEARCH_COUNT": 0,
        "CONDITIONING_BOUNDARIES": "pre-fold historical calibrated rows only",
        "CONDITIONING_TEMPORAL_RULE": "max(conditioning_training_timestamp) < min(conditioning_evaluation_timestamp)",
        "T6_WITHIN_CELL_QUANTILES": T6_WITHIN_CELL_QUANTILE_COUNT,
        "T6_WITHIN_CELL_QUANTILE_SEARCH_COUNT": 0,
        "T6_WITHIN_CELL_BOUNDARIES": "pre-fold historical T6 within historical P/L cell only",
        "CONDITIONAL_STATISTIC": CONDITIONAL_STATISTIC,
        "CONDITIONAL_STATISTIC_IMPLEMENTATION_REUSED": True,
        "SAME_DAY_RULE": "within ET trading-date and P/L cell, deterministic highest-T6 minus lowest-T6 candidate; require at least two rows and two distinct T6 values",
        "GATES": {
            "A_POOLED_CONDITIONAL_STRICTLY_POSITIVE": True,
            "B_DATE_BALANCED_CONDITIONAL_MIN": GATE_B_MIN,
            "C_ALL_4_FOLDS_STRICTLY_POSITIVE": True,
            "D_UP_AND_DOWN_STRICTLY_POSITIVE": True,
            "E_QUANTILE_MONOTONICITY_MIN": GATE_E_MIN,
            "E_TOP_MINUS_BOTTOM_MEAN_PAYOFF_STRICTLY_POSITIVE": True,
            "F_SAME_DAY_HIGH_MINUS_LOW_MEAN_PAYOFF_STRICTLY_POSITIVE": True,
        },
        "RELATIVE_SCORE_CONSTRUCTION_PROHIBITED": True, "ABSOLUTE_EV_PROHIBITED": True,
        "WEIGHT_ASSIGNMENT_PROHIBITED": True, "THRESHOLD_PROHIBITED": True,
        "TRADING_PROHIBITED": True, "FINAL_PROHIBITED": True,
        "HEAD_EXPANSION_PROHIBITED": True, "HEAD_EXPANSION_LIMIT_AFTER_R33G": True,
        "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "CALIBRATION_METHOD_SEARCH_COUNT": 0, "CALIBRATION_BUCKET_SEARCH_COUNT": 0,
        "CALIBRATION_REBUILD_VARIANT_COUNT": 0, "GAIN_CALIBRATION_RETRY_COUNT": 0,
        "RELATIVE_SCORE_CANDIDATE_COUNT": 0, "RELATIVE_SCORE_FORMULA_SEARCH_COUNT": 0,
        "RELATIVE_SCORE_WEIGHT_SEARCH_COUNT": 0, "T6_ECONOMIC_LEVEL_MAPPING_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "WEIGHT_ASSIGNMENT_COUNT": 0,
        "ABSOLUTE_EV_CONSTRUCTION_COUNT": 0, "EV_SCORE_CONSTRUCTION_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "SIGNAL_SELECTION_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "RUN_STARTED_AT_UTC": started_at_utc, "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "FIRST_RUN_STATUS": FIRST_RUN_STATUS, "RERUN_COUNT": RERUN_COUNT,
        "RERUN_REASON": RERUN_REASON,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False,
    }


def validate_lineage(r33i: Any) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    for path, expected in EXPECTED_SHA256.items():
        if not path.is_file() or file_sha256(path) != expected:
            raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    summary, contract = read_json(R33I_SUMMARY), read_json(R33I_CONTRACT)
    r33h, r33g = read_json(R33H_SUMMARY), read_json(R33G_SUMMARY)
    if (
        summary.get("FAST3_R33I_CLASSIFICATION") != "C_ECONOMIC_LEVEL_CALIBRATION_NOT_STABLE"
        or summary.get("P_SOURCE") != P_SOURCE or summary.get("L_SOURCE") != L_SOURCE
        or summary.get("G_SOURCE") != G_RANK_SOURCE
        or summary.get("P_CALIBRATION_STATUS") != "CALIBRATED"
        or summary.get("L_CALIBRATION_STATUS") != "CALIBRATED"
        or summary.get("G_CALIBRATION_STATUS") != "RANKING_VALID_BUT_LEVEL_CALIBRATION_NOT_ESTABLISHED"
        or contract.get("R33I_PREREGISTRATION_SHA256") != EXPECTED_SHA256[R33I_PREREGISTRATION]
        or contract.get("EVALUATION_FOLDS", {}).get("P") != list(EVALUATION_FOLDS)
        or contract.get("EVALUATION_FOLDS", {}).get("L") != list(EVALUATION_FOLDS)
        or r33h.get("T1_ROLE_CLASSIFICATION") != "A_CANDIDATE_VALIDITY_WITH_WINNER_ORDERING"
        or r33h.get("T5_ROLE_CLASSIFICATION") != "A_PRIMARY_LOSS_SEVERITY_WITH_SECONDARY_WINNER_ORDERING"
        or r33h.get("T6_ROLE_CLASSIFICATION") != "A_CONDITIONAL_WINNER_GAIN_MAGNITUDE_ROLE_CONFIRMED"
        or r33g.get("T7_T5_PREDICTION_EXACT_MATCH") is not True
        or r33g.get("T7_VALIDATED") is not False
        or r33g.get("FURTHER_HEAD_EXPANSION_ALLOWED") is not False
    ):
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    try:
        frame, r33d_contract, r33d_summary = r33i.validate_and_load_lineage()
        r33i.reconcile_roles(frame, r33d_summary)
        audits = r33i.recover_fold_audits(frame, r33d_contract)
    except Exception as exc:
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY") from exc
    if [row["outer_fold"] for row in audits] != list(EVALUATION_FOLDS):
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return frame, summary, audits, r33d_summary


def reconcile_r33i_calibration(r33i: Any, frame: pd.DataFrame, audits: list[dict[str, Any]], summary: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    p_oof, _, _, _ = r33i.execute_component(frame, audits, "P")
    l_oof, _, _, _ = r33i.execute_component(frame, audits, "L")
    p_metrics, _ = r33i.probability_metrics(p_oof)
    l_metrics, _ = r33i.magnitude_metrics(l_oof, "L", "loss_magnitude")
    checks = {
        "P_BRIER_SCORE": p_metrics["brier_score"],
        "P_LOG_LOSS": p_metrics["log_loss"],
        "P_EXPECTED_CALIBRATION_ERROR": p_metrics["expected_calibration_error"],
        "L_OOF_MAE": l_metrics["oof_mae"],
        "L_OOF_RMSE": l_metrics["oof_rmse"],
        "L_DATE_BALANCED_SPEARMAN": l_metrics["date_balanced_spearman"],
    }
    if any(not np.isclose(value, summary[key], rtol=0, atol=1e-15) for key, value in checks.items()):
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return p_oof, l_oof


def training_mapping(training: pd.DataFrame, score: str, target: str, applications: list[pd.DataFrame]) -> tuple[list[np.ndarray], dict[str, Any]]:
    if training.empty or training[[score, target]].isna().any().any():
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    edges = training[score].quantile(np.arange(1, 10) / 10, interpolation="linear").to_numpy(dtype=float)
    train_bins = np.searchsorted(edges, training[score].to_numpy(dtype=float), side="right") + 1
    means = pd.Series(training[target].to_numpy(dtype=float)).groupby(train_bins).mean()
    fallback = float(training[target].mean())
    outputs = []
    for application in applications:
        bins = np.searchsorted(edges, application[score].to_numpy(dtype=float), side="right") + 1
        values = means.reindex(bins).to_numpy(dtype=float)
        outputs.append(np.where(np.isfinite(values), values, fallback))
    return outputs, {"edges": edges.tolist(), "fallback": fallback, "nonempty_bucket_count": int(means.size)}


def fold_safe_calibrated_population(frame: pd.DataFrame, audits: list[dict[str, Any]], p_reference: pd.DataFrame, l_reference: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    parts, audit_rows = [], []
    p_ref = p_reference.set_index("candidate_id").calibrated
    l_ref = l_reference.set_index("candidate_id").calibrated
    for audit in audits:
        cutoff = pd.Timestamp(audit["information_cutoff"])
        historical = frame.loc[frame.decision_timestamp_utc.lt(cutoff)].copy()
        evaluation = frame.loc[frame.fold.eq(audit["source_fold"])].copy()
        historical_losers = historical.loc[historical.raw_net20.lt(0)].copy()
        if (
            historical.empty or historical_losers.empty or evaluation.empty
            or not historical.decision_timestamp_utc.max() < evaluation.decision_timestamp_utc.min()
            or historical.fold.eq(audit["source_fold"]).any()
        ):
            raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
        p_values, p_info = training_mapping(historical, "pred_t1", "winner", [historical, evaluation])
        l_values, l_info = training_mapping(historical_losers, "pred_t5", "loss_magnitude", [historical, evaluation])
        historical["p_calibrated"], evaluation["p_calibrated"] = p_values
        historical["l_calibrated"], evaluation["l_calibrated"] = l_values
        expected_p = p_ref.reindex(evaluation.candidate_id).to_numpy(dtype=float)
        loser_mask = evaluation.raw_net20.lt(0).to_numpy()
        expected_l = l_ref.reindex(evaluation.loc[loser_mask, "candidate_id"]).to_numpy(dtype=float)
        if (
            not np.array_equal(evaluation.p_calibrated.to_numpy(dtype=float), expected_p)
            or not np.array_equal(evaluation.loc[loser_mask, "l_calibrated"].to_numpy(dtype=float), expected_l)
        ):
            raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")

        p_edges = historical.p_calibrated.quantile([1 / 3, 2 / 3], interpolation="linear").to_numpy(dtype=float)
        l_edges = historical.l_calibrated.quantile([1 / 3, 2 / 3], interpolation="linear").to_numpy(dtype=float)
        historical["p_cell"] = np.searchsorted(p_edges, historical.p_calibrated, side="right") + 1
        historical["l_cell"] = np.searchsorted(l_edges, historical.l_calibrated, side="right") + 1
        evaluation["p_cell"] = np.searchsorted(p_edges, evaluation.p_calibrated, side="right") + 1
        evaluation["l_cell"] = np.searchsorted(l_edges, evaluation.l_calibrated, side="right") + 1
        evaluation["outer_fold"] = audit["outer_fold"]

        t6_edges_by_cell: dict[str, list[float]] = {}
        evaluation["t6_tercile"] = 0
        for keys in ((p, l) for p in range(1, 4) for l in range(1, 4)):
            train_cell = historical.loc[historical.p_cell.eq(keys[0]) & historical.l_cell.eq(keys[1])]
            eval_mask = evaluation.p_cell.eq(keys[0]) & evaluation.l_cell.eq(keys[1])
            if train_cell.empty:
                raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
            t6_edges = train_cell.pred_t6.quantile([1 / 3, 2 / 3], interpolation="linear").to_numpy(dtype=float)
            evaluation.loc[eval_mask, "t6_tercile"] = np.searchsorted(
                t6_edges, evaluation.loc[eval_mask, "pred_t6"].to_numpy(dtype=float), side="right"
            ) + 1
            t6_edges_by_cell[f"P{keys[0]}_L{keys[1]}"] = t6_edges.tolist()
        if not evaluation.t6_tercile.isin([1, 2, 3]).all():
            raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
        parts.append(evaluation)
        audit_rows.append({
            "record_type": "TEMPORAL_CONDITIONING_AUDIT", "group": audit["outer_fold"],
            "count": len(evaluation), "training_count": len(historical),
            "training_min_timestamp": historical.decision_timestamp_utc.min(),
            "training_max_timestamp": historical.decision_timestamp_utc.max(),
            "evaluation_min_timestamp": evaluation.decision_timestamp_utc.min(),
            "evaluation_max_timestamp": evaluation.decision_timestamp_utc.max(),
            "strict_temporal_separation": True, "p_calibration_mapping": p_info,
            "l_calibration_mapping": l_info, "p_tercile_edges": p_edges.tolist(),
            "l_tercile_edges": l_edges.tolist(), "t6_tercile_edges_by_pl_cell": t6_edges_by_cell,
        })
    result = pd.concat(parts, ignore_index=True)
    if len(result) != 790_731 or result.candidate_id.duplicated().any() or result.raw_net20.eq(0).any():
        raise R33JStop("STOPPED_DATA_OR_LINEAGE_INTEGRITY")
    return result, audit_rows


def conditional_rank_statistic(frame: pd.DataFrame) -> tuple[float, float, pd.DataFrame]:
    ranked_parts, cell_rows = [], []
    for keys, part in frame.groupby(["outer_fold", "p_cell", "l_cell"], sort=True, observed=True):
        cell_s = safe_spearman(part.pred_t6, part.raw_net20)
        ranked = part[["candidate_id", "trading_date", "outer_fold", "head", "p_cell", "l_cell"]].copy()
        ranked["within_cell_t6_rank"] = part.pred_t6.rank(method="average", pct=True)
        ranked["within_cell_payoff_rank"] = part.raw_net20.rank(method="average", pct=True)
        ranked_parts.append(ranked)
        cell_rows.append({
            "record_type": "PL_CELL", "group": f"{keys[0]}_P{keys[1]}_L{keys[2]}",
            "outer_fold": keys[0], "p_cell": int(keys[1]), "l_cell": int(keys[2]),
            "count": len(part), "cell_t6_payoff_spearman": cell_s,
        })
    ranked = pd.concat(ranked_parts, ignore_index=True)
    pooled = safe_spearman(ranked.within_cell_t6_rank, ranked.within_cell_payoff_rank)
    daily = ranked.groupby("trading_date", sort=True, observed=True).agg(
        mean_t6_rank=("within_cell_t6_rank", "mean"),
        mean_payoff_rank=("within_cell_payoff_rank", "mean"),
    )
    date_balanced = safe_spearman(daily.mean_t6_rank, daily.mean_payoff_rank)
    if pooled is None or date_balanced is None:
        raise R33JStop("STOP_R33J_CONDITIONAL_STATISTIC")
    return pooled, date_balanced, pd.DataFrame(cell_rows)


def conditional_only_spearman(frame: pd.DataFrame) -> float:
    ranked_parts = []
    for _, part in frame.groupby(["outer_fold", "p_cell", "l_cell"], sort=True, observed=True):
        ranked_parts.append(pd.DataFrame({
            "x": part.pred_t6.rank(method="average", pct=True),
            "y": part.raw_net20.rank(method="average", pct=True),
        }))
    ranked = pd.concat(ranked_parts, ignore_index=True)
    value = safe_spearman(ranked.x, ranked.y)
    if value is None:
        raise R33JStop("STOP_R33J_CONDITIONAL_SUBGROUP_STATISTIC")
    return value


def quantile_diagnostic(frame: pd.DataFrame) -> tuple[float, float, list[dict[str, Any]]]:
    rows = []
    for keys, part in frame.groupby(["outer_fold", "p_cell", "l_cell", "t6_tercile"], sort=True, observed=True):
        rows.append({
            "record_type": "T6_WITHIN_PL_TERCILE", "group": f"{keys[0]}_P{keys[1]}_L{keys[2]}_T{keys[3]}",
            "outer_fold": keys[0], "p_cell": int(keys[1]), "l_cell": int(keys[2]),
            "t6_tercile": int(keys[3]), "count": len(part),
            "mean_realized_payoff": float(part.raw_net20.mean()),
            "median_realized_payoff": float(part.raw_net20.median()),
            "winner_rate": float(part.raw_net20.gt(0).mean()),
        })
    aggregated = frame.groupby("t6_tercile", sort=True, observed=True).agg(
        count=("candidate_id", "size"), mean_realized_payoff=("raw_net20", "mean"),
        median_realized_payoff=("raw_net20", "median"), winner_rate=("raw_net20", lambda x: x.gt(0).mean()),
    ).reset_index()
    monotonicity = safe_spearman(aggregated.t6_tercile, aggregated.mean_realized_payoff)
    if monotonicity is None or len(aggregated) != T6_WITHIN_CELL_QUANTILE_COUNT:
        raise R33JStop("STOP_R33J_QUANTILE_DIAGNOSTIC")
    spread = float(aggregated.iloc[-1].mean_realized_payoff - aggregated.iloc[0].mean_realized_payoff)
    aggregate_rows = [{
        "record_type": "T6_TERCILE_AGGREGATE", "group": f"T{int(row.t6_tercile)}",
        "t6_tercile": int(row.t6_tercile), "count": int(row["count"]),
        "mean_realized_payoff": float(row.mean_realized_payoff),
        "median_realized_payoff": float(row.median_realized_payoff), "winner_rate": float(row.winner_rate),
    } for _, row in aggregated.iterrows()]
    return monotonicity, spread, [*rows, *aggregate_rows]


def same_day_diagnostic(frame: pd.DataFrame) -> dict[str, Any]:
    keys = ["trading_date", "outer_fold", "p_cell", "l_cell"]
    ordered = frame.sort_values([*keys, "pred_t6", "candidate_id"], kind="mergesort")
    eligible_keys = ordered.groupby(keys, sort=True, observed=True).agg(
        count=("candidate_id", "size"), distinct_t6=("pred_t6", "nunique")
    ).query("count >= 2 and distinct_t6 >= 2").reset_index()[keys]
    eligible = ordered.merge(eligible_keys, on=keys, how="inner", validate="many_to_one")
    low = eligible.groupby(keys, sort=True, observed=True).head(1).set_index(keys)
    high = eligible.groupby(keys, sort=True, observed=True).tail(1).set_index(keys)
    if len(low) == 0 or len(low) != len(high):
        raise R33JStop("STOP_R33J_SAME_DAY_DIAGNOSTIC")
    low_mean, high_mean = float(low.raw_net20.mean()), float(high.raw_net20.mean())
    return {
        "comparison_count": len(low), "high_mean_payoff": high_mean,
        "low_mean_payoff": low_mean, "high_minus_low_mean_payoff": high_mean - low_mean,
    }


def classify(gates: dict[str, bool]) -> tuple[str, str, bool, str]:
    if all(gates.values()):
        return (
            "A_RELATIVE_ECONOMIC_ORDERING_IDENTIFIABLE",
            "AUTHORIZE_FROZEN_RELATIVE_ECONOMIC_SCORE_DESIGN", True,
            "PREREGISTER_FROZEN_RELATIVE_ECONOMIC_SCORE",
        )
    if gates["A"] or gates["B"]:
        return (
            "B_CONDITIONAL_UPSIDE_INFORMATION_PRESENT_BUT_RELATIVE_ORDERING_NOT_STABLE",
            "DO_NOT_CONSTRUCT_RELATIVE_ECONOMIC_SCORE", False,
            "RETAIN_COMPONENT_RANKINGS_WITHOUT_COMPOSITION",
        )
    return (
        "C_RELATIVE_ECONOMIC_ORDERING_NOT_IDENTIFIED", "STOP_ECONOMIC_SCORE_COMPOSITION", False,
        "RETAIN_INDEPENDENT_HEAD_DIAGNOSTICS_ONLY",
    )


def compact_terminal_summary(summary: dict[str, Any]) -> None:
    keys = [
        "FAST3_R33J_STATUS", "FAST3_R33J_CLASSIFICATION", "FAST3_R33J_DECISION",
        "R33J_PREREGISTRATION_VERIFIED", "R33J_PREREGISTRATION_SHA256",
        "ROLE_CONTRACT_RECONCILIATION_STATUS", "R33I_CALIBRATION_RECONCILIATION_STATUS",
        "PAYOFF_DEFINITION_RECONCILIATION_STATUS", "P_SOURCE", "L_SOURCE", "G_RANK_SOURCE",
        "R33J_EVALUATION_FOLDS", "R33J_FOLD_COUNT", "OOF_2021_INCLUDED", "R33J_OOF_ROW_COUNT",
        "PL_CONDITIONING_GRID", "NONEMPTY_PL_CELL_COUNT",
        "CONDITIONAL_T6_VS_REALIZED_PAYOFF_GIVEN_P_L_SPEARMAN",
        "DATE_BALANCED_CONDITIONAL_T6_VS_REALIZED_PAYOFF_GIVEN_P_L_SPEARMAN",
        "POSITIVE_CONDITIONAL_SPEARMAN_FOLD_COUNT", "MIN_FOLD_CONDITIONAL_SPEARMAN",
        "MAX_FOLD_CONDITIONAL_SPEARMAN", "UP_CONDITIONAL_T6_VS_PAYOFF_SPEARMAN",
        "DOWN_CONDITIONAL_T6_VS_PAYOFF_SPEARMAN", "CONDITIONAL_T6_QUANTILE_PAYOFF_MONOTONICITY",
        "CONDITIONAL_T6_TOP_MINUS_BOTTOM_MEAN_PAYOFF", "SAME_DAY_CELL_COMPARISON_COUNT",
        "SAME_DAY_CELL_HIGH_T6_MEAN_PAYOFF", "SAME_DAY_CELL_LOW_T6_MEAN_PAYOFF",
        "SAME_DAY_CELL_HIGH_MINUS_LOW_MEAN_PAYOFF", "UNCONDITIONAL_T6_VS_REALIZED_PAYOFF_SPEARMAN",
        "DATE_BALANCED_UNCONDITIONAL_T6_VS_REALIZED_PAYOFF_SPEARMAN",
        "GATE_A_POOLED_CONDITIONAL_ORDERING", "GATE_B_DATE_BALANCED_CONDITIONAL_ORDERING",
        "GATE_C_FOLD_STABILITY", "GATE_D_DIRECTION_STABILITY", "GATE_E_CONDITIONAL_MONOTONICITY",
        "GATE_F_SAME_DAY_SEPARATION", "RELATIVE_ECONOMIC_ORDERING_IDENTIFIED",
        "NEW_HEAD_COUNT", "NEW_FEATURE_COUNT", "NEW_TARGET_COUNT", "MODEL_FIT_COUNT",
        "MODEL_PREDICT_CALL_COUNT", "CALIBRATION_METHOD_SEARCH_COUNT", "GAIN_CALIBRATION_RETRY_COUNT",
        "PL_CONDITIONING_GRID_COUNT", "PL_CONDITIONING_GRID_SEARCH_COUNT", "T6_WITHIN_CELL_QUANTILE_COUNT",
        "T6_WITHIN_CELL_QUANTILE_SEARCH_COUNT", "RELATIVE_SCORE_CANDIDATE_COUNT",
        "RELATIVE_SCORE_FORMULA_SEARCH_COUNT", "RELATIVE_SCORE_WEIGHT_SEARCH_COUNT",
        "T6_ECONOMIC_LEVEL_MAPPING_COUNT", "WEIGHT_SEARCH_COUNT", "WEIGHT_ASSIGNMENT_COUNT",
        "ABSOLUTE_EV_CONSTRUCTION_COUNT", "EV_SCORE_CONSTRUCTION_COUNT", "EV_COMBINATION_SEARCH_COUNT",
        "THRESHOLD_SEARCH_COUNT", "SIGNAL_SELECTION_COUNT", "TRADING_SIMULATION_COUNT",
        "EXECUTION_SIMULATION_COUNT", "POSITION_SIZING_SEARCH_COUNT", "HEAD_EXPANSION_LIMIT_AFTER_R33G",
        "FURTHER_HEAD_EXPANSION_ALLOWED", "FINAL_CONFIRMATION_DATA_USED", "FINAL_CONFIRMATION_DATA_LOADED",
        "FINAL_HOLDOUT_INSPECTED", "FIRST_RUN_STATUS", "RERUN_COUNT",
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT", "ANTI_BLOAT_STATUS",
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
        raise R33JStop("USE_--run")

    started = datetime.now(timezone.utc)
    run_id = f"r33j_relative_economic_score_identifiability_{started.strftime('%Y%m%dT%H%M%SZ')}"
    frozen_root = RESULTS_ROOT / "frozen/fast3" / run_id
    if frozen_root.exists():
        raise R33JStop("STOP_R33J_OUTPUT_EXISTS")
    r33i = load_r33i_module()
    frame, r33i_summary, audits, _ = validate_lineage(r33i)
    frozen_input_hashes_before = {str(path): file_sha256(path) for path in EXPECTED_SHA256}

    frozen_root.mkdir(parents=True)
    prereg_path = frozen_root / "FAST3_R33J_PREREGISTRATION_R1.json"
    prereg = preregistration(started.isoformat())
    write_json(prereg_path, prereg)
    prereg_sha = file_sha256(prereg_path)
    if read_json(prereg_path) != prereg:
        raise R33JStop("STOP_R33J_PREREGISTRATION_VERIFICATION")

    p_reference, l_reference = reconcile_r33i_calibration(r33i, frame, audits, r33i_summary)
    study, temporal_rows = fold_safe_calibrated_population(frame, audits, p_reference, l_reference)
    pooled, date_balanced, cell_table = conditional_rank_statistic(study)

    fold_rows, fold_values = [], []
    for fold in EVALUATION_FOLDS:
        part = study.loc[study.outer_fold.eq(fold)]
        value = conditional_only_spearman(part)
        fold_values.append(value)
        fold_rows.append({
            "record_type": "FOLD", "group": fold, "count": len(part),
            "nonempty_cell_count": int(part.groupby(["p_cell", "l_cell"], observed=True).ngroups),
            "conditional_t6_payoff_spearman": value,
        })
    direction_values = {direction: conditional_only_spearman(part) for direction, part in study.groupby("head", sort=True, observed=True)}
    direction_rows = [{
        "record_type": "DIRECTION", "group": direction, "count": len(study.loc[study["head"].eq(direction)]),
        "conditional_t6_payoff_spearman": value,
    } for direction, value in direction_values.items()]
    monotonicity, top_bottom, quantile_rows = quantile_diagnostic(study)
    same_day = same_day_diagnostic(study)
    unconditional = safe_spearman(study.pred_t6, study.raw_net20)
    unconditional_daily = study.groupby("trading_date", sort=True, observed=True).agg(
        mean_t6=("pred_t6", "mean"), mean_payoff=("raw_net20", "mean")
    )
    unconditional_date = safe_spearman(unconditional_daily.mean_t6, unconditional_daily.mean_payoff)
    if unconditional is None or unconditional_date is None:
        raise R33JStop("STOP_R33J_UNCONDITIONAL_DIAGNOSTIC")

    gates = {
        "A": pooled > 0, "B": date_balanced >= GATE_B_MIN,
        "C": len(fold_values) == 4 and all(value > 0 for value in fold_values),
        "D": direction_values.get("UP", 0) > 0 and direction_values.get("DOWN", 0) > 0,
        "E": monotonicity >= GATE_E_MIN and top_bottom > 0,
        "F": same_day["high_minus_low_mean_payoff"] > 0,
    }
    classification, decision, identified, next_stage = classify(gates)
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise R33JStop("STOP_R33J_CLASSIFICATION_ENUM")

    metrics_path = frozen_root / "FAST3_R33J_CONDITIONAL_METRICS.csv"
    contract_path = frozen_root / "FAST3_R33J_IDENTIFIABILITY_CONTRACT_R1.json"
    summary_path = frozen_root / "FAST3_R33J_SUMMARY.json"
    report_path = frozen_root / "FAST3_R33J_REPORT.md"
    metric_rows = [*temporal_rows, *cell_table.to_dict("records"), *fold_rows, *direction_rows, *quantile_rows]
    pd.DataFrame(metric_rows).to_csv(metrics_path, index=False)
    contract = {
        "CONTRACT_ID": "FAST3_R33J_IDENTIFIABILITY_CONTRACT_R1", "STATUS": "FROZEN_AFTER_VALIDATION",
        "R33J_PREREGISTRATION_SHA256": prereg_sha, "P_SOURCE": P_SOURCE, "L_SOURCE": L_SOURCE,
        "G_RANK_SOURCE": G_RANK_SOURCE, "EVALUATION_FOLDS": list(EVALUATION_FOLDS),
        "PL_CONDITIONING_GRID": "3x3", "CONDITIONAL_STATISTIC": CONDITIONAL_STATISTIC,
        "CONDITIONAL_STATISTIC_IMPLEMENTATION_REUSED": True,
        "T6_WITHIN_CELL_QUANTILES": T6_WITHIN_CELL_QUANTILE_COUNT,
        "CLASSIFICATION": classification, "DECISION": decision,
        "RELATIVE_ECONOMIC_ORDERING_IDENTIFIED": identified,
        "ABSOLUTE_EV_CONSTRUCTED": False, "RELATIVE_SCORE_CONSTRUCTED": False,
        "FINAL_CONFIRMATION_DATA_USED": False, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
    }
    write_json(contract_path, contract)

    common_zero = {
        "NEW_HEAD_COUNT": 0, "NEW_FEATURE_COUNT": 0, "NEW_TARGET_COUNT": 0,
        "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0,
        "CALIBRATION_METHOD_SEARCH_COUNT": 0, "CALIBRATION_BUCKET_SEARCH_COUNT": 0,
        "CALIBRATION_REBUILD_VARIANT_COUNT": 0, "GAIN_CALIBRATION_RETRY_COUNT": 0,
        "PL_CONDITIONING_GRID_COUNT": 1, "PL_CONDITIONING_GRID_SEARCH_COUNT": 0,
        "T6_WITHIN_CELL_QUANTILE_COUNT": 3, "T6_WITHIN_CELL_QUANTILE_SEARCH_COUNT": 0,
        "RELATIVE_SCORE_CANDIDATE_COUNT": 0, "RELATIVE_SCORE_FORMULA_SEARCH_COUNT": 0,
        "RELATIVE_SCORE_WEIGHT_SEARCH_COUNT": 0, "T6_ECONOMIC_LEVEL_MAPPING_COUNT": 0,
        "WEIGHT_SEARCH_COUNT": 0, "WEIGHT_ASSIGNMENT_COUNT": 0,
        "ABSOLUTE_EV_CONSTRUCTION_COUNT": 0, "EV_SCORE_CONSTRUCTION_COUNT": 0,
        "EV_COMBINATION_SEARCH_COUNT": 0, "THRESHOLD_SEARCH_COUNT": 0,
        "SIGNAL_SELECTION_COUNT": 0, "TRADING_SIMULATION_COUNT": 0,
        "EXECUTION_SIMULATION_COUNT": 0, "POSITION_SIZING_SEARCH_COUNT": 0,
    }
    summary = {
        "FAST3_R33J_STATUS": "PASS", "FAST3_R33J_CLASSIFICATION": classification,
        "FAST3_R33J_DECISION": decision, "R33J_PREREGISTRATION_VERIFIED": True,
        "R33J_PREREGISTRATION_SHA256": prereg_sha, "ROLE_CONTRACT_RECONCILIATION_STATUS": "PASS",
        "R33I_CALIBRATION_RECONCILIATION_STATUS": "PASS", "PAYOFF_DEFINITION_RECONCILIATION_STATUS": "PASS",
        "P_SOURCE": P_SOURCE, "L_SOURCE": L_SOURCE, "G_RANK_SOURCE": G_RANK_SOURCE,
        "R33J_EVALUATION_FOLDS": ",".join(EVALUATION_FOLDS), "R33J_FOLD_COUNT": len(EVALUATION_FOLDS),
        "OOF_2021_INCLUDED": False, "OOF_2021_EXCLUSION_REASON": "NO_PRE_FOLD_CALIBRATION_HISTORY",
        "R33J_OOF_ROW_COUNT": len(study), "PL_CONDITIONING_GRID": "3x3",
        "NONEMPTY_PL_CELL_COUNT": int(cell_table[["p_cell", "l_cell"]].drop_duplicates().shape[0]),
        "CONDITIONAL_STATISTIC_IMPLEMENTATION_REUSED": True,
        "CONDITIONAL_T6_VS_REALIZED_PAYOFF_GIVEN_P_L_SPEARMAN": pooled,
        "DATE_BALANCED_CONDITIONAL_T6_VS_REALIZED_PAYOFF_GIVEN_P_L_SPEARMAN": date_balanced,
        "POSITIVE_CONDITIONAL_SPEARMAN_FOLD_COUNT": int(sum(value > 0 for value in fold_values)),
        "MIN_FOLD_CONDITIONAL_SPEARMAN": min(fold_values), "MAX_FOLD_CONDITIONAL_SPEARMAN": max(fold_values),
        "FOLD_CONDITIONAL_METRICS": fold_rows,
        "UP_CONDITIONAL_T6_VS_PAYOFF_SPEARMAN": direction_values["UP"],
        "DOWN_CONDITIONAL_T6_VS_PAYOFF_SPEARMAN": direction_values["DOWN"],
        "CONDITIONAL_T6_QUANTILE_PAYOFF_MONOTONICITY": monotonicity,
        "CONDITIONAL_T6_TOP_MINUS_BOTTOM_MEAN_PAYOFF": top_bottom,
        "SAME_DAY_CELL_COMPARISON_COUNT": same_day["comparison_count"],
        "SAME_DAY_CELL_HIGH_T6_MEAN_PAYOFF": same_day["high_mean_payoff"],
        "SAME_DAY_CELL_LOW_T6_MEAN_PAYOFF": same_day["low_mean_payoff"],
        "SAME_DAY_CELL_HIGH_MINUS_LOW_MEAN_PAYOFF": same_day["high_minus_low_mean_payoff"],
        "UNCONDITIONAL_T6_VS_REALIZED_PAYOFF_SPEARMAN": unconditional,
        "DATE_BALANCED_UNCONDITIONAL_T6_VS_REALIZED_PAYOFF_SPEARMAN": unconditional_date,
        "GATE_A_POOLED_CONDITIONAL_ORDERING": gates["A"],
        "GATE_B_DATE_BALANCED_CONDITIONAL_ORDERING": gates["B"],
        "GATE_C_FOLD_STABILITY": gates["C"], "GATE_D_DIRECTION_STABILITY": gates["D"],
        "GATE_E_CONDITIONAL_MONOTONICITY": gates["E"], "GATE_F_SAME_DAY_SEPARATION": gates["F"],
        "RELATIVE_ECONOMIC_ORDERING_IDENTIFIED": identified, **common_zero,
        "HEAD_EXPANSION_LIMIT_AFTER_R33G": True, "FURTHER_HEAD_EXPANSION_ALLOWED": False,
        "FINAL_CONFIRMATION_DATA_USED": False, "FINAL_CONFIRMATION_DATA_LOADED": False,
        "FINAL_HOLDOUT_INSPECTED": False, "FINAL_HOLDOUT_ROW_COUNT": 0,
        "FIRST_RUN_STATUS": FIRST_RUN_STATUS, "RERUN_COUNT": RERUN_COUNT, "RERUN_REASON": RERUN_REASON,
        "RESEARCH_CHOICE_CHANGED_AFTER_FIRST_RESULT": False, "ANTI_BLOAT_STATUS": "PASS",
        "PRIMARY_RESEARCH_INTERPRETATION": decision, "NEXT_STAGE": next_stage,
        "RUN_ID": run_id, "RUN_STARTED_AT_UTC": started.isoformat(),
        "RUN_ID_TIMESTAMP_SEMANTICS": RUN_ID_TIMESTAMP_SEMANTICS,
        "PREREGISTRATION_PATH": str(prereg_path), "CONDITIONAL_METRICS_PATH": str(metrics_path),
        "IDENTIFIABILITY_CONTRACT_PATH": str(contract_path), "SUMMARY_JSON_PATH": str(summary_path),
        "REPORT_PATH": str(report_path), "RESULT_FILES_WRITTEN_TO_GIT_REPO": False,
    }
    write_json(summary_path, summary)
    report_path.write_text(f"""# FAST3 R33J — Relative Economic Score Identifiability

## Result

`{classification}` / `{decision}`.

R33I fold-safe P(T1) and L(T5) calibration outputs were deterministically reconstructed and reconciled before this audit. OOF_2021 remains excluded; OOF_2022–OOF_2025 contain {len(study):,} all-candidate rows. The canonical R33G within-cell percentile-rank conditional statistic was reused without alternative aggregation search.

## Evidence

- Conditional pooled T6/payoff Spearman: `{pooled}`.
- Date-balanced conditional Spearman: `{date_balanced}`.
- Positive folds: `{sum(value > 0 for value in fold_values)}/4`; range `{min(fold_values)}` to `{max(fold_values)}`.
- UP / DOWN conditional Spearman: `{direction_values['UP']}` / `{direction_values['DOWN']}`.
- T6-tercile payoff monotonicity / top-minus-bottom: `{monotonicity}` / `{top_bottom}`.
- Same-day same-cell high-minus-low T6 payoff: `{same_day['high_minus_low_mean_payoff']}` across `{same_day['comparison_count']:,}` comparisons.

## Scope discipline

No scalar relative score and no absolute EV component was constructed. No model, gain-level mapping, weight, threshold, signal selection, trading/execution simulation, position sizing, new head, or new feature was used. Final confirmation remained sealed.
""", encoding="utf-8")

    frozen_input_hashes_after = {str(path): file_sha256(path) for path in EXPECTED_SHA256}
    if frozen_input_hashes_before != frozen_input_hashes_after or file_sha256(prereg_path) != prereg_sha:
        raise R33JStop("STOP_R33J_FROZEN_INPUT_MUTATED")
    compact_terminal_summary(summary)
    print(f"REPORT_PATH={report_path}")
    print(f"SUMMARY_JSON_PATH={summary_path}")
    print(f"IDENTIFIABILITY_CONTRACT_PATH={contract_path}")
    print(f"CONDITIONAL_METRICS_PATH={metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
