"""ABCDE A2-R2 post-hoc mechanism and signal-timing analysis.

The deterministic analysis contract can be frozen without importing or
opening any R1 outcome, prediction, target, model, or price artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr
from sklearn.inspection import partial_dependence


EXPERIMENT_ID = "ABCDE_A2_R2_SIGNAL_LAG_AND_INCREMENTAL_MECHANISM"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
ANALYSIS_CONTRACT_PATH = RESULTS_ROOT / "a2_r2_analysis_contract_r1.json"
FREEZE_WITNESS_PATH = RESULTS_ROOT / "a2_r2_contract_freeze_witness.json"
SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r2_summary.json"
MANIFEST_PATH = RESULTS_ROOT / "a2_r2_manifest.json"
SIGNAL_EVENTS_PATH = RESULTS_ROOT / "signal_entry_events.parquet"
DISAGREEMENT_PATH = RESULTS_ROOT / "a1_a2_disagreement_analysis.parquet"
DAILY_EDGE_PATH = RESULTS_ROOT / "daily_incremental_edge.parquet"
FEATURE_MECHANISM_PATH = RESULTS_ROOT / "feature_mechanism_analysis.json"
STATE_CONDITIONAL_PATH = RESULTS_ROOT / "state_conditional_analysis.parquet"
R1_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING")
R1_SUMMARY_PATH = R1_ROOT / "abcde_a2_r1_summary.json"
R1_OOF_PATH = R1_ROOT / "a2_r1_oof_predictions.parquet"
R1_COMPARISON_PATH = R1_ROOT / "a1_a2_comparison.parquet"
R1_MODEL_PATH = R1_ROOT / "a2_r1_final_hgb.joblib"
R1_MODULE_PATH = REPO_ROOT / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
R1C_FEATURE_PATH = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1C_EXECUTION_CONTRACT_FREEZE_R1\a2_r1_feature_equation_contract.json")
EXPECTED_R1_ARTIFACT_SHA256 = {
    "summary": "df1f4b63270a6974cffb962bfb1df5efb044a268591e37a9ab72cfdf39dcd6e5",
    "oof": "a601b655afddf3e9aac63ea38571fff4dab3caad10400ae2a4a75697feeaf47e",
    "comparison": "b28d871af92c84e37398f6a3a2656bf710c49f9808147276561dbca6e2f32416",
    "model": "17c5c70010424cf0c409f84f5af420dd9d60fc7043a6c029ffbd5897e46f578d",
}
EXPECTED_ANALYSIS_CONTRACT_SHA256 = "513c624cab518658aff1df342b31c80b2ec3a7a5827f74692f898b37b0fc4217"


def canonical_payload(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_payload(value) + b"\n")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def import_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False), temporary,
        compression="zstd", use_dictionary=True, write_statistics=True,
    )
    os.replace(temporary, path)


def dataframe_fingerprint(frame: pd.DataFrame, columns: list[str] | tuple[str, ...]) -> str:
    ordered = frame.loc[:, list(columns)].copy()
    for column in ordered.columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].dt.strftime("%Y-%m-%d")
    hashes = pd.util.hash_pandas_object(ordered, index=False, categorize=True).to_numpy(dtype=np.uint64)
    digest = hashlib.sha256()
    digest.update("|".join(columns).encode("utf-8"))
    digest.update(hashes.tobytes())
    return digest.hexdigest()


def analysis_contract() -> dict[str, Any]:
    return {
        "contract_id": "ABCDE_A2_R2_ANALYSIS_CONTRACT_R1",
        "contract_role": "POST_HOC_MECHANISM_AND_SIGNAL_TIMING_ANALYSIS",
        "primary_questions": [
            "WHAT_STRUCTURE_EXPLAINS_A2_INCREMENT_BEYOND_A1",
            "DOES_A2_REDUCE_A1_SIGNAL_LAG_UNDER_OBJECTIVE_ENTRY_EVENTS",
            "IN_WHICH_FROZEN_INFORMATION_STATES_IS_A2_MORE_RELIABLE",
        ],
        "authoritative_r1_identity": {
            "required_status": "PASS",
            "required_classification": "A_STRONG_INCREMENTAL_NONLINEAR_EDGE",
            "required_daily_universe_identity_status": "PASS",
            "r1_reclassification_allowed": False,
            "final_2025_role": "POST_FINAL_EXPLANATORY_ANALYSIS",
        },
        "signal_entry_event": {
            "models": ["A1", "A2"],
            "top_n": [20, 10],
            "primary_top_n": 20,
            "rank_direction": "RANK_1_IS_BEST",
            "equation": "IN_TOPN_AT_T_AND_NOT_IN_TOPN_ON_EACH_OF_PRIOR_5_TICKER_ELIGIBLE_SIGNAL_DAYS",
            "prior_eligible_day_count": 5,
            "incomplete_prior_history_policy": "NOT_AN_ENTRY_EVENT",
            "repeat_policy": "NEW_EVENT_ALLOWED_ONLY_AFTER_AT_LEAST_5_CONSECUTIVE_ELIGIBLE_NON_TOPN_DAYS",
            "stage_boundary_policy": "PRIOR_DAYS_MUST_EXIST_IN_AUTHORITATIVE_R1_OOF_ROWS;NO_SYNTHETIC_BRIDGE",
        },
        "signal_timing": {
            "benchmark": "QQQ",
            "source": "MOOMOO_DERIVED_CANONICAL_QFQ_CLOSE",
            "pre_windows_trading_days": [5, 3, 1],
            "post_windows_trading_days": [1, 3, 5, 10, 20],
            "pre_equation": "STOCK_RETURN_FROM_T_MINUS_H_TO_T_MINUS_BENCHMARK_RETURN_SAME_DATES",
            "post_equation": "STOCK_RETURN_FROM_T_TO_T_PLUS_H_MINUS_BENCHMARK_RETURN_SAME_DATES",
            "calendar": "QQQ_CANONICAL_TRADING_DATES",
            "missing_endpoint_policy": "KEEP_EVENT_WITH_NAN_WINDOW;NEVER_FILL",
            "epsilon": 1e-12,
            "signal_capture_ratio": "MAX(POST_H_ER,0)/(ABS(PRE_5D_ER)+ABS(POST_H_ER)+1E-12)",
            "pre_to_post_balance": "POST_H_ER-PRE_5D_ER",
            "lag_support_year": "A2_TOP20_PRE5_MEAN<=A1_TOP20_PRE5_MEAN_AND_(A2_MINUS_A1_POST5_MEAN>0_OR_A2_MINUS_A1_POST10_MEAN>0)",
            "lag_no_evidence_year": "A2_TOP20_PRE5_MEAN>A1_TOP20_PRE5_MEAN_AND_A2_MINUS_A1_POST5_MEAN<=0_AND_A2_MINUS_A1_POST10_MEAN<=0",
            "lag_classification": {
                "SUPPORTS_EARLIER_CAPTURE": "LAG_SUPPORT_YEAR_TRUE_FOR_BOTH_2024_AND_2025",
                "NO_EVIDENCE_OF_EARLIER_CAPTURE": "LAG_NO_EVIDENCE_YEAR_TRUE_FOR_BOTH_2024_AND_2025",
                "MIXED": "ALL_OTHER_CASES",
            },
        },
        "disagreement": {
            "rank_percentile": "1-(RANK-1)/(DAILY_FINITE_EVALUATION_COUNT-1)",
            "rank_disagreement": "A2_RANK_PERCENTILE-A1_RANK_PERCENTILE",
            "positive_direction": "HIGHER_MEANS_A2_MORE_BULLISH_THAN_A1",
            "daily_groups": 5,
            "assignment": "SORT_ASCENDING_BY_RANK_DISAGREEMENT_THEN_TICKER;NP_ARRAY_SPLIT_INTO_Q1_TO_Q5",
            "q1": "A2_MAXIMUM_DOWNGRADE",
            "q5": "A2_MAXIMUM_UPGRADE",
            "metrics": ["COUNT", "MEAN_TARGET", "MEDIAN_TARGET", "POSITIVE_FRACTION", "Q5_MINUS_Q1_TARGET_SPREAD"],
            "reporting_scopes": [2023, 2024, 2025, "POOLED"],
        },
        "daily_incremental_edge": {
            "delta_ic": "DAILY_SPEARMAN_A2_MINUS_DAILY_SPEARMAN_A1",
            "delta_top20": "DAILY_A2_TOP20_MEAN_TARGET_MINUS_DAILY_A1_TOP20_MEAN_TARGET",
            "distribution_statistics": ["MEAN", "MEDIAN", "STD_DDOF0", "P10", "P25", "P75", "P90", "POSITIVE_FRACTION"],
            "fat_right_tail_rule": "MEAN_DELTA_IC>MEDIAN_DELTA_IC_AND_P90_DELTA_IC>ABS(P10_DELTA_IC)",
            "robust_not_single_date_rule": "SYMMETRIC_5_PERCENT_TRIMMED_MEAN_DELTA_IC>0",
        },
        "state_slices": {
            "feature_source": "ALL_32_FROZEN_R1_FEATURES_WITHOUT_SELECTION",
            "daily_state_transforms_per_feature": ["CROSS_SECTIONAL_MEDIAN", "CROSS_SECTIONAL_STD_DDOF0"],
            "prediction_diagnostics": [
                "A1_A2_RANK_CORRELATION", "A2_SCORE_CROSS_SECTIONAL_STD",
                "A2_RANK_DISPERSION", "A1_A2_MEAN_ABS_RANK_DIFFERENCE",
            ],
            "quartiles": 4,
            "assignment": "WITHIN_REPORTING_SCOPE_RANK_METHOD_FIRST_THEN_EQUAL_COUNT_ARRAY_SPLIT_Q1_TO_Q4",
            "reporting_scopes": [2023, 2024, 2025, "POOLED"],
            "metrics": ["MEAN_DELTA_IC", "MEAN_DELTA_TOP20", "A2_MEAN_IC", "A1_MEAN_IC", "DATE_COUNT"],
            "interpretation": "DESCRIPTIVE_ONLY_NO_META_FILTER_OR_GATE",
        },
        "feature_mechanism": {
            "model_family": "FROZEN_R1_HIST_GRADIENT_BOOSTING_REGRESSOR_ONLY",
            "development_confirmation_refit": "EXACT_FROZEN_R1_TRAIN_ROWS_AND_CONFIG_FOR_MECHANISM_ONLY",
            "final_model": "AUTHORITATIVE_R1_FINAL_HGB_ARTIFACT",
            "selection_training_count": 0,
            "permutation_importance": {
                "metric": "DROP_IN_MEAN_DAILY_SPEARMAN_RANK_IC",
                "permutation": "WITHIN_SIGNAL_DATE_DETERMINISTIC_PERMUTATION",
                "repeats": 1,
                "seed": 20260816,
                "max_rows_per_stage": 20000,
                "sample_rule": "SMALLEST_SHA256_OF_STAGE_SIGNAL_DATE_TICKER",
            },
            "family_importance": "JOINT_WITHIN_DAY_PERMUTATION_OF_ALL_FEATURES_IN_FROZEN_ECONOMIC_FAMILY",
            "top_feature_count": 6,
            "top_feature_selection": "DESCENDING_POOLED_MEAN_PERMUTATION_IMPORTANCE_THEN_FEATURE_NAME",
            "partial_dependence": {
                "single_feature_grid_resolution": 10,
                "pair_grid_resolution": 6,
                "percentiles": [0.05, 0.95],
                "max_rows_per_stage": 5000,
                "sample_rule": "SMALLEST_SHA256_OF_STAGE_SIGNAL_DATE_TICKER",
            },
            "interaction_pairs": "ALL_15_UNORDERED_PAIRS_AMONG_FROZEN_TOP_6_FEATURES",
            "interaction_measure": "RMS_CENTERED_2D_PDP_NONADDITIVE_RESIDUAL_NORMALIZED_BY_2D_PDP_STD",
            "repeatable_structure_rule": "COMMON_POSITIVE_TOP2_FAMILY_IN_2024_AND_2025_OR_COMMON_TOP5_INTERACTION_PAIR_IN_2024_AND_2025",
            "importance_interpretation": "ASSOCIATIONAL_NOT_CAUSAL_ALPHA",
            "shap": "NOT_REQUIRED_AND_NO_NEW_DEPENDENCY",
        },
        "mechanism_classification": {
            "M1_STRONG_MECHANISTIC_SUPPORT": [
                "DISAGREEMENT_Q5_MINUS_Q1_TARGET_SPREAD_2024>0",
                "DISAGREEMENT_Q5_MINUS_Q1_TARGET_SPREAD_2025>0",
                "A2_MINUS_A1_TOP20_POST5_OR_POST10_EDGE_POSITIVE_IN_2024_AND_2025",
                "REPEATABLE_FEATURE_FAMILY_OR_INTERACTION_STRUCTURE_TRUE",
                "SYMMETRIC_5_PERCENT_TRIMMED_MEAN_DELTA_IC_POSITIVE_IN_2024_AND_2025",
                "ALL_AUDITS_PASS",
            ],
            "M2_PARTIAL_OR_MIXED_MECHANISM": "NOT_M1_AND_ANY_OF_DISAGREEMENT_POOLED_SPREAD_POSITIVE_OR_ANY_2024_2025_POST_EDGE_POSITIVE_OR_REPEATABLE_STRUCTURE_OR_ANY_2024_2025_TRIMMED_MEAN_POSITIVE",
            "M3_INCREMENTAL_EDGE_NOT_MECHANISTICALLY_RESOLVED": "NOT_M1_AND_NOT_M2",
            "FAIL_CLOSED": "ANY_CONTRACT_DATA_LEAKAGE_IDENTITY_OR_REPRODUCIBILITY_FAILURE",
            "r1_classification_change_allowed": False,
        },
        "year_roles": {
            "2023": "DEVELOPMENT_EXPLANATORY",
            "2024": "CONFIRMATION_EXPLANATORY",
            "2025": "POST_FINAL_EXPLANATORY_ANALYSIS",
        },
        "reproducibility": {
            "complete_analysis_runs": 2,
            "required": "RUN1_FINGERPRINT_EQUALS_RUN2_FINGERPRINT",
        },
        "prohibitions": {
            "model_tuning": True,
            "new_model": True,
            "new_feature": True,
            "portfolio_optimization": True,
            "lambda_rank": True,
            "fast_read_or_fit": True,
            "post2025_outcome_read": True,
            "production_adoption": True,
        },
        "production": {
            "A2_R1_MODEL_CHANGED": False,
            "A2_R1_FEATURE_SCHEMA_CHANGED": False,
            "A1_PRODUCTION_CHANGED": False,
            "A2_PRODUCTION_ADOPTED": False,
            "FAST_CHANGED": False,
            "DAILY_CHAIN_CHANGED": False,
            "BROKER_ACTION_COUNT": 0,
            "FAST_CANDIDATE_FEATURES_RESEARCH_ONLY": True,
        },
    }


def freeze_analysis_contract() -> dict[str, Any]:
    contract = analysis_contract()
    payload = canonical_payload(contract) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if ANALYSIS_CONTRACT_PATH.exists():
        existing = ANALYSIS_CONTRACT_PATH.read_bytes()
        if existing != payload:
            raise RuntimeError("EXISTING_R2_ANALYSIS_CONTRACT_DIFFERS_FAIL_CLOSED")
    else:
        temporary = ANALYSIS_CONTRACT_PATH.with_suffix(".json.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, ANALYSIS_CONTRACT_PATH)
    witness = {
        "experiment_id": EXPERIMENT_ID,
        "contract_path": str(ANALYSIS_CONTRACT_PATH),
        "contract_sha256": digest,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "r1_outcome_or_prediction_read_count_before_freeze": 0,
        "target_or_future_return_read_count_before_freeze": 0,
        "status": "PASS_FROZEN_BEFORE_OUTCOME_READ",
    }
    if FREEZE_WITNESS_PATH.exists():
        prior = json.loads(FREEZE_WITNESS_PATH.read_text(encoding="utf-8"))
        if prior.get("contract_sha256") != digest or prior.get("status") != witness["status"]:
            raise RuntimeError("R2_FREEZE_WITNESS_MISMATCH_FAIL_CLOSED")
        witness = prior
    else:
        write_json_atomic(FREEZE_WITNESS_PATH, witness)
    return witness


def validate_authoritative_r1() -> tuple[Any, dict[str, Any], pd.DataFrame, dict[str, list[str]], dict[str, Any]]:
    paths = (R1_SUMMARY_PATH, R1_OOF_PATH, R1_COMPARISON_PATH, R1_MODEL_PATH, R1_MODULE_PATH, R1C_FEATURE_PATH)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError("MISSING_AUTHORITATIVE_R1_ARTIFACT:" + ",".join(missing))
    actual = {
        "summary": sha256_file(R1_SUMMARY_PATH),
        "oof": sha256_file(R1_OOF_PATH),
        "comparison": sha256_file(R1_COMPARISON_PATH),
        "model": sha256_file(R1_MODEL_PATH),
    }
    if actual != EXPECTED_R1_ARTIFACT_SHA256:
        raise RuntimeError(f"R1_ARTIFACT_FINGERPRINT_MISMATCH:{actual}")
    summary = json.loads(R1_SUMMARY_PATH.read_text(encoding="utf-8"))
    checks = {
        "r1_status": summary.get("ABCDE_A2_R1_STATUS") == "PASS",
        "r1_classification": summary.get("ABCDE_A2_R1_CLASSIFICATION") == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE",
        "daily_universe_identity": summary.get("A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS") == "PASS",
        "post2025_target_zero": summary.get("POST2025_TARGET_READ_COUNT") == 0,
        "post2025_outcome_zero": summary.get("POST2025_OUTCOME_READ_COUNT") == 0,
        "feature_count": summary.get("FEATURE_COUNT") == 32,
        "final_one_shot": summary.get("FINAL_EVALUATION_COUNT") == 1,
    }
    if not all(checks.values()):
        raise RuntimeError("R1_PREREQUISITE_STATUS_FAILURE:" + ",".join(k for k, v in checks.items() if not v))
    oof = pq.read_table(R1_OOF_PATH).to_pandas()
    oof["signal_date"] = pd.to_datetime(oof["signal_date"])
    oof["ticker"] = oof["ticker"].astype(str).str.upper()
    oof = oof.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(oof) != 210445 or oof.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("R1_OOF_ROW_IDENTITY_FAILURE")
    if (oof["signal_date"] >= pd.Timestamp("2026-01-01")).any() or not np.isfinite(oof["target"]).all():
        raise RuntimeError("R1_OOF_POST2025_OR_NONFINITE_TARGET_FAILURE")
    feature_contract = json.loads(R1C_FEATURE_PATH.read_text(encoding="utf-8"))
    families: dict[str, list[str]] = {}
    for row in feature_contract["features"]:
        families.setdefault(row["economic_family"], []).append(row["feature_name"])
    r1 = import_module("abcde_a2_r2_r1_helpers", R1_MODULE_PATH)
    audit = {"checks": checks, "artifact_sha256": actual, "oof_rows": len(oof), "oof_max_date": str(oof.signal_date.max().date())}
    return r1, summary, oof, families, audit


def build_entry_events(oof: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for model, rank_column in (("A1", "a1_rank"), ("A2", "a2_rank")):
        for top_n in (20, 10):
            work = oof[["signal_date", "ticker", "split", rank_column]].copy()
            work = work.sort_values(["ticker", "signal_date"], kind="mergesort")
            work["in_top"] = work[rank_column] <= top_n
            grouped = work.groupby("ticker", sort=False)["in_top"]
            prior_complete = work.groupby("ticker", sort=False).cumcount() >= 5
            prior_clear = pd.Series(True, index=work.index)
            for lag in range(1, 6):
                prior_clear &= ~grouped.shift(lag).fillna(True).astype(bool)
            events = work.loc[work["in_top"] & prior_complete & prior_clear, ["signal_date", "ticker", "split"]].copy()
            events["model"] = model
            events["top_n"] = top_n
            pieces.append(events)
    result = pd.concat(pieces, ignore_index=True)
    result["year"] = result["signal_date"].dt.year.astype(np.int16)
    result["year_role"] = result["year"].map({
        2023: "DEVELOPMENT_EXPLANATORY", 2024: "CONFIRMATION_EXPLANATORY",
        2025: "POST_FINAL_EXPLANATORY_ANALYSIS",
    })
    return result.sort_values(["model", "top_n", "signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def attach_signal_paths(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    qqq = prices.loc[prices["ticker"] == "QQQ", ["trade_date", "close"]].dropna().drop_duplicates("trade_date").sort_values("trade_date")
    calendar = pd.DatetimeIndex(qqq["trade_date"])
    qqq_close = pd.Series(qqq["close"].to_numpy(dtype=float), index=calendar)
    positions = pd.Series(np.arange(len(calendar)), index=calendar)
    lookup = prices.set_index(["ticker", "trade_date"])["close"]
    signal_position = result["signal_date"].map(positions)
    signal_close = lookup.reindex(pd.MultiIndex.from_arrays([result["ticker"], result["signal_date"]])).to_numpy(dtype=float)
    benchmark_signal = result["signal_date"].map(qqq_close).to_numpy(dtype=float)
    for direction, windows in (("PRE", (5, 3, 1)), ("POST", (1, 3, 5, 10, 20))):
        for horizon in windows:
            offset = -horizon if direction == "PRE" else horizon
            endpoint_position = signal_position + offset
            valid_position = endpoint_position.between(0, len(calendar) - 1)
            endpoints = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")
            endpoints.loc[valid_position] = calendar[endpoint_position.loc[valid_position].astype(int)]
            endpoint_close = lookup.reindex(pd.MultiIndex.from_arrays([result["ticker"], endpoints])).to_numpy(dtype=float)
            benchmark_endpoint = endpoints.map(qqq_close).to_numpy(dtype=float)
            if direction == "PRE":
                stock_return = signal_close / endpoint_close - 1.0
                benchmark_return = benchmark_signal / benchmark_endpoint - 1.0
            else:
                stock_return = endpoint_close / signal_close - 1.0
                benchmark_return = benchmark_endpoint / benchmark_signal - 1.0
            result[f"{direction}_{horizon}D_ER"] = stock_return - benchmark_return
    for horizon in (1, 3, 5, 10, 20):
        post = result[f"POST_{horizon}D_ER"]
        pre = result["PRE_5D_ER"]
        result[f"SIGNAL_CAPTURE_RATIO_{horizon}D"] = post.clip(lower=0) / (pre.abs() + post.abs() + 1e-12)
        result[f"PRE_TO_POST_BALANCE_{horizon}D"] = post - pre
    return result


def summarize_signal_paths(events: pd.DataFrame) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    value_columns = [
        *(f"PRE_{h}D_ER" for h in (5, 3, 1)),
        *(f"POST_{h}D_ER" for h in (1, 3, 5, 10, 20)),
        *(f"SIGNAL_CAPTURE_RATIO_{h}D" for h in (1, 3, 5, 10, 20)),
        *(f"PRE_TO_POST_BALANCE_{h}D" for h in (1, 3, 5, 10, 20)),
    ]
    for scope in (2023, 2024, 2025, "POOLED"):
        scoped = events if scope == "POOLED" else events.loc[events["year"] == scope]
        for (model, top_n), group in scoped.groupby(["model", "top_n"], sort=True):
            row: dict[str, Any] = {"scope": str(scope), "model": model, "top_n": int(top_n), "event_count": int(len(group))}
            for column in value_columns:
                row[f"{column}_MEAN"] = float(group[column].mean())
                row[f"{column}_MEDIAN"] = float(group[column].median())
                row[f"{column}_FINITE_COUNT"] = int(group[column].notna().sum())
            rows.append(row)
    lookup = {(row["scope"], row["model"], row["top_n"]): row for row in rows}
    yearly: dict[str, Any] = {}
    support: list[bool] = []
    no_evidence: list[bool] = []
    for year in (2024, 2025):
        a1, a2 = lookup[(str(year), "A1", 20)], lookup[(str(year), "A2", 20)]
        pre_delta = a2["PRE_5D_ER_MEAN"] - a1["PRE_5D_ER_MEAN"]
        post5_delta = a2["POST_5D_ER_MEAN"] - a1["POST_5D_ER_MEAN"]
        post10_delta = a2["POST_10D_ER_MEAN"] - a1["POST_10D_ER_MEAN"]
        support_year = pre_delta <= 0 and (post5_delta > 0 or post10_delta > 0)
        no_year = pre_delta > 0 and post5_delta <= 0 and post10_delta <= 0
        support.append(support_year)
        no_evidence.append(no_year)
        yearly[str(year)] = {
            "a2_minus_a1_pre5_mean": pre_delta,
            "a2_minus_a1_post5_mean": post5_delta,
            "a2_minus_a1_post10_mean": post10_delta,
            "lag_support_year": support_year,
            "lag_no_evidence_year": no_year,
        }
    evidence = "SUPPORTS_EARLIER_CAPTURE" if all(support) else "NO_EVIDENCE_OF_EARLIER_CAPTURE" if all(no_evidence) else "MIXED"
    return rows, evidence, yearly


def disagreement_analysis(oof: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    work = oof.copy()
    n = work.groupby("signal_date")["ticker"].transform("size")
    denominator = (n - 1).clip(lower=1)
    work["a1_rank_percentile"] = 1.0 - (work["a1_rank"] - 1.0) / denominator
    work["a2_rank_percentile"] = 1.0 - (work["a2_rank"] - 1.0) / denominator
    work["rank_disagreement"] = work["a2_rank_percentile"] - work["a1_rank_percentile"]
    groups: list[pd.DataFrame] = []
    for _, day in work.groupby("signal_date", sort=True):
        ordered = day.sort_values(["rank_disagreement", "ticker"], kind="mergesort").copy()
        labels = pd.Series(index=ordered.index, dtype="int8")
        for q, indices in enumerate(np.array_split(np.arange(len(ordered)), 5), start=1):
            labels.loc[ordered.index[indices]] = q
        ordered["disagreement_quintile"] = labels.astype(np.int8)
        groups.append(ordered)
    work = pd.concat(groups, ignore_index=True)
    work["year"] = work["signal_date"].dt.year
    rows: list[dict[str, Any]] = []
    spreads: dict[str, float] = {}
    for scope in (2023, 2024, 2025, "POOLED"):
        scoped = work if scope == "POOLED" else work.loc[work["year"] == scope]
        if scoped.empty:
            continue
        stats: dict[int, dict[str, Any]] = {}
        for quintile, group in scoped.groupby("disagreement_quintile", sort=True):
            stats[int(quintile)] = {
                "count": int(len(group)), "mean_target": float(group["target"].mean()),
                "median_target": float(group["target"].median()),
                "positive_fraction": float((group["target"] > 0).mean()),
            }
        spread = stats[5]["mean_target"] - stats[1]["mean_target"]
        spreads[str(scope)] = spread
        for quintile in range(1, 6):
            rows.append({"scope": str(scope), "disagreement_quintile": quintile, **stats[quintile], "q5_minus_q1_target_spread": spread})
    return pd.DataFrame(rows), spreads


def _daily_spearman(score: pd.Series, target: pd.Series) -> float:
    if len(score) < 2 or score.nunique() < 2 or target.nunique() < 2:
        return np.nan
    return float(spearmanr(score.to_numpy(dtype=float), target.to_numpy(dtype=float)).statistic)


def build_daily_edge(oof: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal_date, day in oof.groupby("signal_date", sort=True):
        day = day.copy()
        n = len(day)
        denominator = max(n - 1, 1)
        a1_pct = 1.0 - (day["a1_rank"] - 1.0) / denominator
        a2_pct = 1.0 - (day["a2_rank"] - 1.0) / denominator
        a1_ic = _daily_spearman(day["a1_raw_score"], day["target"])
        a2_ic = _daily_spearman(day["a2_prediction"], day["target"])
        a1_top = day.sort_values(["a1_raw_score", "ticker"], ascending=[False, True], kind="mergesort").head(20)["target"].mean()
        a2_top = day.sort_values(["a2_prediction", "ticker"], ascending=[False, True], kind="mergesort").head(20)["target"].mean()
        rows.append({
            "signal_date": signal_date, "year": int(signal_date.year), "split": str(day["split"].iloc[0]), "row_count": n,
            "a1_ic": a1_ic, "a2_ic": a2_ic, "delta_ic": a2_ic - a1_ic,
            "a1_top20_mean_target": float(a1_top), "a2_top20_mean_target": float(a2_top), "delta_top20": float(a2_top - a1_top),
            "a1_a2_rank_correlation": _daily_spearman(a1_pct, a2_pct),
            "a2_score_cross_sectional_std": float(day["a2_prediction"].std(ddof=0)),
            "a2_rank_dispersion": float(a2_pct.std(ddof=0)),
            "a1_a2_mean_abs_rank_difference": float((a2_pct - a1_pct).abs().mean()),
        })
    return pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)


def distribution(values: pd.Series) -> dict[str, float]:
    finite = values[np.isfinite(values)].to_numpy(dtype=float)
    if len(finite) == 0:
        return {key: np.nan for key in ("mean", "median", "std", "p10", "p25", "p75", "p90", "positive_fraction", "trimmed_mean_5pct")}
    ordered = np.sort(finite)
    trim = int(math.floor(0.05 * len(ordered)))
    trimmed = ordered[trim:len(ordered) - trim] if trim else ordered
    return {
        "mean": float(np.mean(finite)), "median": float(np.median(finite)), "std": float(np.std(finite, ddof=0)),
        "p10": float(np.quantile(finite, 0.10)), "p25": float(np.quantile(finite, 0.25)),
        "p75": float(np.quantile(finite, 0.75)), "p90": float(np.quantile(finite, 0.90)),
        "positive_fraction": float(np.mean(finite > 0)), "trimmed_mean_5pct": float(np.mean(trimmed)),
    }


def daily_edge_summary(daily: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scope in (2023, 2024, 2025, "POOLED"):
        scoped = daily if scope == "POOLED" else daily.loc[daily["year"] == scope]
        ic = distribution(scoped["delta_ic"])
        top = distribution(scoped["delta_top20"])
        result[str(scope)] = {
            "delta_ic": ic, "delta_top20": top,
            "fat_right_tail_incremental_edge": bool(ic["mean"] > ic["median"] and ic["p90"] > abs(ic["p10"])),
            "robust_not_single_date": bool(ic["trimmed_mean_5pct"] > 0),
        }
    return result


def _assign_scope_quartiles(frame: pd.DataFrame, value_column: str) -> pd.Series:
    ordered = frame.sort_values([value_column, "signal_date"], kind="mergesort")
    result = pd.Series(index=frame.index, dtype="int8")
    for quartile, indices in enumerate(np.array_split(np.arange(len(ordered)), 4), start=1):
        result.loc[ordered.index[indices]] = quartile
    return result.astype(np.int8)


def state_conditional_analysis(matrix: pd.DataFrame, oof: pd.DataFrame, daily: pd.DataFrame, feature_columns: tuple[str, ...]) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = oof[["signal_date", "ticker"]]
    states = keys.merge(matrix[["signal_date", "ticker", *feature_columns]], on=["signal_date", "ticker"], how="left", validate="one_to_one")
    daily_states = states.groupby("signal_date", sort=True)[list(feature_columns)].agg(["median", lambda x: x.std(ddof=0)])
    daily_states.columns = [f"{feature}__{'median' if statistic == 'median' else 'std'}" for feature, statistic in daily_states.columns]
    daily_states = daily_states.reset_index().merge(daily, on="signal_date", how="inner", validate="one_to_one")
    diagnostic_columns = (
        "a1_a2_rank_correlation", "a2_score_cross_sectional_std",
        "a2_rank_dispersion", "a1_a2_mean_abs_rank_difference",
    )
    state_columns = [column for column in daily_states.columns if "__" in column]
    rows: list[dict[str, Any]] = []
    relationships: dict[str, Any] = {}
    for scope in (2023, 2024, 2025, "POOLED"):
        scoped = daily_states.copy() if scope == "POOLED" else daily_states.loc[daily_states["year"] == scope].copy()
        relationships[str(scope)] = {}
        for column in [*state_columns, *diagnostic_columns]:
            usable = scoped.loc[np.isfinite(scoped[column])].copy()
            if len(usable) < 4:
                continue
            usable["quartile"] = _assign_scope_quartiles(usable, column)
            kind = "FROZEN_FEATURE_DAILY_STATE" if column in state_columns else "PREDICTION_DIAGNOSTIC"
            for quartile, group in usable.groupby("quartile", sort=True):
                rows.append({
                    "scope": str(scope), "state_kind": kind, "state_feature": column, "quartile": int(quartile),
                    "date_count": int(len(group)), "state_value_mean": float(group[column].mean()),
                    "mean_delta_ic": float(group["delta_ic"].mean()), "mean_delta_top20": float(group["delta_top20"].mean()),
                    "a2_mean_ic": float(group["a2_ic"].mean()), "a1_mean_ic": float(group["a1_ic"].mean()),
                })
            if column in diagnostic_columns:
                relationships[str(scope)][column] = {
                    "spearman_with_delta_ic": _daily_spearman(usable[column], usable["delta_ic"]),
                    "spearman_with_delta_top20": _daily_spearman(usable[column], usable["delta_top20"]),
                }
    return pd.DataFrame(rows), relationships


def _stable_sample(frame: pd.DataFrame, stage: str, maximum: int) -> pd.DataFrame:
    if len(frame) <= maximum:
        return frame.copy().reset_index(drop=True)
    keys = [f"{stage}|{date:%Y-%m-%d}|{ticker}" for date, ticker in zip(frame["signal_date"], frame["ticker"])]
    hashes = np.fromiter((int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") for key in keys), dtype=np.uint64)
    positions = np.argpartition(hashes, maximum - 1)[:maximum]
    return frame.iloc[np.sort(positions)].reset_index(drop=True)


def _within_day_permutation(values: np.ndarray, dates: pd.Series, seed_text: str) -> np.ndarray:
    result = values.copy()
    for signal_date, indices in dates.groupby(dates, sort=True).groups.items():
        seed = int.from_bytes(hashlib.sha256(f"20260816|{seed_text}|{signal_date}".encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        positions = np.asarray(list(indices), dtype=int)
        result[positions] = values[positions][rng.permutation(len(positions))]
    return result


def _mean_daily_ic_from_prediction(frame: pd.DataFrame, prediction: np.ndarray) -> float:
    scored = frame[["signal_date", "target"]].copy()
    scored["prediction"] = prediction
    values = [_daily_spearman(day["prediction"], day["target"]) for _, day in scored.groupby("signal_date", sort=True)]
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    return float(np.mean(finite))


def _pdp_single(model: Any, x: np.ndarray, feature_index: int, grid: int) -> dict[str, Any]:
    result = partial_dependence(model, x, features=[feature_index], kind="average", method="brute", grid_resolution=grid, percentiles=(0.05, 0.95))
    return {"grid": result["grid_values"][0].astype(float).tolist(), "response": result["average"][0].astype(float).tolist()}


def _pdp_interaction(model: Any, x: np.ndarray, first: int, second: int) -> tuple[dict[str, Any], float]:
    pair = partial_dependence(model, x, features=[(first, second)], kind="average", method="brute", grid_resolution=6, percentiles=(0.05, 0.95))
    one = partial_dependence(model, x, features=[first], kind="average", method="brute", grid_resolution=6, percentiles=(0.05, 0.95))
    two = partial_dependence(model, x, features=[second], kind="average", method="brute", grid_resolution=6, percentiles=(0.05, 0.95))
    surface = pair["average"][0].astype(float)
    one_response = one["average"][0].astype(float)
    two_response = two["average"][0].astype(float)
    centered_surface = surface - surface.mean()
    residual = centered_surface - (one_response - one_response.mean())[:, None] - (two_response - two_response.mean())[None, :]
    denominator = float(np.std(surface, ddof=0))
    strength = float(np.sqrt(np.mean(residual ** 2)) / denominator) if denominator > 0 else 0.0
    payload = {
        "first_grid": pair["grid_values"][0].astype(float).tolist(),
        "second_grid": pair["grid_values"][1].astype(float).tolist(),
        "response_surface": surface.tolist(),
        "normalized_interaction_strength": strength,
    }
    return payload, strength


def feature_mechanism_analysis(r1: Any, matrix: pd.DataFrame, families: dict[str, list[str]]) -> tuple[dict[str, Any], int]:
    feature_columns = tuple(r1.FEATURE_COLUMNS)
    stage_models: dict[str, Any] = {}
    stage_evaluations: dict[str, pd.DataFrame] = {}
    refit_count = 0
    for stage, year in r1.STAGES:
        training, evaluation, _ = r1.stage_rows(matrix, year)
        if stage == "FINAL":
            model = joblib.load(R1_MODEL_PATH)
        else:
            model = r1.load_and_validate_frozen_inputs().prereg.make_hgb()
            model.fit(training.loc[:, feature_columns].to_numpy(dtype=float), training["target"].to_numpy(dtype=float))
            refit_count += 1
        stage_models[stage] = model
        stage_evaluations[stage] = evaluation

    feature_rows: list[dict[str, Any]] = []
    family_rows: list[dict[str, Any]] = []
    stage_samples: dict[str, pd.DataFrame] = {}
    for stage, _ in r1.STAGES:
        sample = _stable_sample(stage_evaluations[stage], stage, 20000)
        stage_samples[stage] = sample
        x = sample.loc[:, feature_columns].to_numpy(dtype=float)
        model = stage_models[stage]
        baseline_prediction = model.predict(x)
        baseline_ic = _mean_daily_ic_from_prediction(sample, baseline_prediction)
        for feature_index, feature in enumerate(feature_columns):
            permuted = x.copy()
            permuted[:, feature_index] = _within_day_permutation(permuted[:, feature_index], sample["signal_date"], f"{stage}|{feature}")
            importance = baseline_ic - _mean_daily_ic_from_prediction(sample, model.predict(permuted))
            family = next(name for name, members in families.items() if feature in members)
            feature_rows.append({"stage": stage, "feature": feature, "economic_family": family, "permutation_importance": importance, "baseline_sample_mean_daily_ic": baseline_ic, "sample_rows": len(sample)})
        for family, members in sorted(families.items()):
            permuted = x.copy()
            seed_text = f"{stage}|FAMILY|{family}"
            for signal_date, indices in sample["signal_date"].groupby(sample["signal_date"], sort=True).groups.items():
                seed = int.from_bytes(hashlib.sha256(f"20260816|{seed_text}|{signal_date}".encode()).digest()[:8], "big")
                rng = np.random.default_rng(seed)
                positions = np.asarray(list(indices), dtype=int)
                order = rng.permutation(len(positions))
                member_indices = [feature_columns.index(member) for member in members]
                permuted[np.ix_(positions, member_indices)] = x[np.ix_(positions[order], member_indices)]
            importance = baseline_ic - _mean_daily_ic_from_prediction(sample, model.predict(permuted))
            family_rows.append({"stage": stage, "economic_family": family, "grouped_permutation_importance": importance, "baseline_sample_mean_daily_ic": baseline_ic, "sample_rows": len(sample)})

    feature_frame = pd.DataFrame(feature_rows)
    pooled = feature_frame.groupby(["feature", "economic_family"], as_index=False)["permutation_importance"].mean()
    pooled = pooled.sort_values(["permutation_importance", "feature"], ascending=[False, True], kind="mergesort")
    top_features = pooled.head(6)["feature"].tolist()
    single_pdp: dict[str, Any] = {}
    interactions: list[dict[str, Any]] = []
    for stage, _ in r1.STAGES:
        model = stage_models[stage]
        pdp_sample = _stable_sample(stage_evaluations[stage], stage, 5000)
        x = pdp_sample.loc[:, feature_columns].to_numpy(dtype=float)
        single_pdp[stage] = {}
        for feature in top_features:
            single_pdp[stage][feature] = _pdp_single(model, x, feature_columns.index(feature), 10)
        for first_index, first in enumerate(top_features):
            for second in top_features[first_index + 1:]:
                payload, strength = _pdp_interaction(model, x, feature_columns.index(first), feature_columns.index(second))
                interactions.append({"stage": stage, "first_feature": first, "second_feature": second, **payload})

    family_frame = pd.DataFrame(family_rows)
    positive_top2: dict[str, set[str]] = {}
    interaction_top5: dict[str, set[str]] = {}
    for stage in ("CONFIRMATION", "FINAL"):
        ranked_families = family_frame.loc[(family_frame["stage"] == stage) & (family_frame["grouped_permutation_importance"] > 0)].nlargest(2, "grouped_permutation_importance")
        positive_top2[stage] = set(ranked_families["economic_family"])
        ranked_pairs = sorted(
            (row for row in interactions if row["stage"] == stage),
            key=lambda row: (-row["normalized_interaction_strength"], row["first_feature"], row["second_feature"]),
        )[:5]
        interaction_top5[stage] = {"|".join(sorted((row["first_feature"], row["second_feature"]))) for row in ranked_pairs}
    common_families = sorted(positive_top2["CONFIRMATION"] & positive_top2["FINAL"])
    common_interactions = sorted(interaction_top5["CONFIRMATION"] & interaction_top5["FINAL"])
    repeatable = bool(common_families or common_interactions)
    top_interactions_by_stage = {
        stage: sorted(
            (row for row in interactions if row["stage"] == stage),
            key=lambda row: (-row["normalized_interaction_strength"], row["first_feature"], row["second_feature"]),
        )[:5]
        for stage, _ in r1.STAGES
    }
    payload = {
        "importance_interpretation": "ASSOCIATIONAL_NOT_CAUSAL_ALPHA",
        "permutation_importance": feature_frame.to_dict("records"),
        "family_importance": family_frame.to_dict("records"),
        "pooled_feature_importance": pooled.to_dict("records"),
        "top_incremental_features": top_features,
        "single_feature_partial_dependence": single_pdp,
        "pairwise_interactions_all_15_each_stage": interactions,
        "top_interactions_by_stage": top_interactions_by_stage,
        "common_positive_top2_families_2024_2025": common_families,
        "common_top5_interactions_2024_2025": common_interactions,
        "repeatable_feature_family_or_interaction_structure": repeatable,
        "mechanism_refit_count": refit_count,
    }
    return payload, refit_count


def classify_mechanism(disagreement_spreads: dict[str, float], lag_yearly: dict[str, Any], daily_summary: dict[str, Any], repeatable: bool, audits_pass: bool) -> tuple[str, dict[str, bool]]:
    post_edge = {
        year: lag_yearly[str(year)]["a2_minus_a1_post5_mean"] > 0 or lag_yearly[str(year)]["a2_minus_a1_post10_mean"] > 0
        for year in (2024, 2025)
    }
    robust = {year: daily_summary[str(year)]["delta_ic"]["trimmed_mean_5pct"] > 0 for year in (2024, 2025)}
    conditions = {
        "disagreement_2024_positive": disagreement_spreads["2024"] > 0,
        "disagreement_2025_positive": disagreement_spreads["2025"] > 0,
        "post_edge_2024_positive": post_edge[2024],
        "post_edge_2025_positive": post_edge[2025],
        "repeatable_structure": repeatable,
        "robust_delta_ic_2024_positive": robust[2024],
        "robust_delta_ic_2025_positive": robust[2025],
        "audits_pass": audits_pass,
    }
    if not audits_pass:
        return "FAIL_CLOSED", conditions
    if all(conditions.values()):
        return "M1_STRONG_MECHANISTIC_SUPPORT", conditions
    partial = disagreement_spreads["POOLED"] > 0 or any(post_edge.values()) or repeatable or any(robust.values())
    return ("M2_PARTIAL_OR_MIXED_MECHANISM" if partial else "M3_INCREMENTAL_EDGE_NOT_MECHANISTICALLY_RESOLVED"), conditions


def _analysis_once(r1: Any, oof: pd.DataFrame, matrix: pd.DataFrame, prices: pd.DataFrame, families: dict[str, list[str]]) -> dict[str, Any]:
    events = attach_signal_paths(build_entry_events(oof), prices)
    signal_summary, lag_evidence, lag_yearly = summarize_signal_paths(events)
    disagreement, disagreement_spreads = disagreement_analysis(oof)
    daily = build_daily_edge(oof)
    daily_summary = daily_edge_summary(daily)
    states, diagnostic_relationships = state_conditional_analysis(matrix, oof, daily, tuple(r1.FEATURE_COLUMNS))
    feature_mechanism, refit_count = feature_mechanism_analysis(r1, matrix, families)
    audits_pass = bool(
        not oof.duplicated(["signal_date", "ticker"]).any()
        and (oof["signal_date"] < pd.Timestamp("2026-01-01")).all()
        and len(states) > 0 and len(events) > 0
    )
    classification, gate_conditions = classify_mechanism(
        disagreement_spreads, lag_yearly, daily_summary,
        feature_mechanism["repeatable_feature_family_or_interaction_structure"], audits_pass,
    )
    stable = {
        "signal_path_summary": signal_summary,
        "signal_lag_evidence": lag_evidence,
        "signal_lag_yearly": lag_yearly,
        "disagreement_spreads": disagreement_spreads,
        "daily_edge_summary": daily_summary,
        "diagnostic_relationships": diagnostic_relationships,
        "feature_mechanism": feature_mechanism,
        "mechanism_classification": classification,
        "mechanism_gate_conditions": gate_conditions,
        "events_fingerprint": dataframe_fingerprint(events, list(events.columns)),
        "disagreement_fingerprint": dataframe_fingerprint(disagreement, list(disagreement.columns)),
        "daily_fingerprint": dataframe_fingerprint(daily, list(daily.columns)),
        "states_fingerprint": dataframe_fingerprint(states, list(states.columns)),
    }
    stable["run_fingerprint"] = canonical_fingerprint(stable)
    return {"stable": stable, "events": events, "disagreement": disagreement, "daily": daily, "states": states, "refit_count": refit_count}


def protected_hashes() -> dict[str, str]:
    paths = (
        REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py",
        REPO_ROOT / "config/v21/abcde_compact_v1_freeze_r1.json",
        REPO_ROOT / "scripts/v22/v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py",
        REPO_ROOT / "scripts/v22/v22_044_daily_single_entrypoint_freeze_and_guard_r1.py",
        REPO_ROOT / "config/v21/active_chain_manifest.json",
        REPO_ROOT / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py",
        R1_MODULE_PATH,
        REPO_ROOT / "scripts/v22/abcde_a2_r1c_execution_contract_freeze_r1.py",
    )
    return {path.relative_to(REPO_ROOT).as_posix(): sha256_file(path) for path in paths if path.is_file()}


def run_analysis() -> dict[str, Any]:
    witness = freeze_analysis_contract()
    if witness["contract_sha256"] != EXPECTED_ANALYSIS_CONTRACT_SHA256:
        raise RuntimeError("R2_ANALYSIS_CONTRACT_SHA256_MISMATCH_FAIL_CLOSED")
    frozen_at = datetime.fromisoformat(witness["frozen_at_utc"])
    first_outcome_read_at = datetime.now(timezone.utc)
    if first_outcome_read_at <= frozen_at:
        raise RuntimeError("R2_CONTRACT_FREEZE_ORDER_FAILURE")
    protected_before = protected_hashes()
    r1, r1_summary, oof, families, prerequisite_audit = validate_authoritative_r1()
    inputs = r1.load_and_validate_frozen_inputs()
    cohort = set(inputs.eligibility["ticker"])
    prices = r1.load_prices_through(2025, cohort)
    matrix = r1.attach_targets(r1.materialize_feature_matrix(prices, inputs.eligibility, 2025), prices)
    run1 = _analysis_once(r1, oof, matrix, prices, families)
    run2 = _analysis_once(r1, oof, matrix, prices, families)
    run1_fingerprint = run1["stable"]["run_fingerprint"]
    run2_fingerprint = run2["stable"]["run_fingerprint"]
    reproducibility = "PASS" if run1_fingerprint == run2_fingerprint else "FAIL"
    if reproducibility != "PASS":
        raise RuntimeError("R2_REPRODUCIBILITY_FAILURE")
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise RuntimeError("PROTECTED_R1_OR_PRODUCTION_FILE_CHANGED")

    stable = run1["stable"]
    classification = stable["mechanism_classification"]
    lag_evidence = stable["signal_lag_evidence"]
    if classification in {"M1_STRONG_MECHANISTIC_SUPPORT", "M2_PARTIAL_OR_MIXED_MECHANISM"}:
        next_step = "ABCDE_A2_R3_FROZEN_RANKING_OBJECTIVE_CHALLENGER"
    else:
        next_step = "REASSESS_A2_INFORMATION_TIMING_BEFORE_MODEL_EXPANSION"
    no_early_claim = classification in {"M1_STRONG_MECHANISTIC_SUPPORT", "M2_PARTIAL_OR_MIXED_MECHANISM"} and lag_evidence != "SUPPORTS_EARLIER_CAPTURE"

    write_parquet_atomic(SIGNAL_EVENTS_PATH, run1["events"])
    write_parquet_atomic(DISAGREEMENT_PATH, run1["disagreement"])
    write_parquet_atomic(DAILY_EDGE_PATH, run1["daily"])
    write_parquet_atomic(STATE_CONDITIONAL_PATH, run1["states"])
    write_json_atomic(FEATURE_MECHANISM_PATH, stable["feature_mechanism"])
    total_refits = int(run1["refit_count"] + run2["refit_count"])
    pooled_signal = {
        (row["model"], row["top_n"]): row for row in stable["signal_path_summary"] if row["scope"] == "POOLED"
    }
    summary = {
        "ABCDE_A2_R2_STATUS": "PASS",
        "ABCDE_A2_R2_CLASSIFICATION": classification,
        "ABCDE_A2_R2_DECISION": next_step,
        "R2_RESEARCH_ROLE": "POST_HOC_MECHANISM_AND_SIGNAL_TIMING_ANALYSIS",
        "R2_ANALYSIS_CONTRACT_FROZEN_BEFORE_OUTCOME_READ": True,
        "R2_ANALYSIS_CONTRACT_SHA256": EXPECTED_ANALYSIS_CONTRACT_SHA256,
        "R2_ANALYSIS_CONTRACT_PATH": str(ANALYSIS_CONTRACT_PATH),
        "R1_PREREQUISITE_STATUS": "PASS",
        "R1_ARTIFACT_SHA256": prerequisite_audit["artifact_sha256"],
        "A2_R1_MODEL_CHANGED": False,
        "A2_R1_FEATURE_SCHEMA_CHANGED": False,
        "A1_PRODUCTION_CHANGED": False,
        "A2_PRODUCTION_ADOPTED": False,
        "FAST_CHANGED": False,
        "DAILY_CHAIN_CHANGED": False,
        "BROKER_ACTION_COUNT": 0,
        "POST2025_TARGET_READ_COUNT": 0,
        "POST2025_OUTCOME_READ_COUNT": 0,
        "2026_MODEL_SELECTION_USE_COUNT": 0,
        "MODEL_TRAINING_FOR_SELECTION_COUNT": 0,
        "MECHANISM_REFIT_COUNT": total_refits,
        "SIGNAL_LAG_EVIDENCE": lag_evidence,
        "A2_INCREMENTAL_EDGE_CONFIRMED_WITHOUT_EARLY_SIGNAL_CLAIM": no_early_claim,
        "A1_TOP20_PRE_5D_MEAN": pooled_signal[("A1", 20)]["PRE_5D_ER_MEAN"],
        "A2_TOP20_PRE_5D_MEAN": pooled_signal[("A2", 20)]["PRE_5D_ER_MEAN"],
        "A1_TOP20_POST_5D_MEAN": pooled_signal[("A1", 20)]["POST_5D_ER_MEAN"],
        "A2_TOP20_POST_5D_MEAN": pooled_signal[("A2", 20)]["POST_5D_ER_MEAN"],
        "A1_TOP20_POST_10D_MEAN": pooled_signal[("A1", 20)]["POST_10D_ER_MEAN"],
        "A2_TOP20_POST_10D_MEAN": pooled_signal[("A2", 20)]["POST_10D_ER_MEAN"],
        "A1_TOP20_POST_20D_MEAN": pooled_signal[("A1", 20)]["POST_20D_ER_MEAN"],
        "A2_TOP20_POST_20D_MEAN": pooled_signal[("A2", 20)]["POST_20D_ER_MEAN"],
        "DISAGREEMENT_Q5_MINUS_Q1_TARGET_SPREAD": stable["disagreement_spreads"],
        "DAILY_INCREMENTAL_EDGE_DISTRIBUTION": stable["daily_edge_summary"],
        "SIGNAL_PATH_SUMMARY": stable["signal_path_summary"],
        "SIGNAL_LAG_YEARLY": stable["signal_lag_yearly"],
        "PREDICTION_DIAGNOSTIC_RELATIONSHIPS": stable["diagnostic_relationships"],
        "FEATURE_FAMILY_IMPORTANCE": stable["feature_mechanism"]["family_importance"],
        "TOP_INCREMENTAL_FEATURES": stable["feature_mechanism"]["top_incremental_features"],
        "REPEATABLE_FEATURE_FAMILY_OR_INTERACTION_STRUCTURE": stable["feature_mechanism"]["repeatable_feature_family_or_interaction_structure"],
        "MECHANISM_GATE_CONDITIONS": stable["mechanism_gate_conditions"],
        "FAST_CANDIDATE_FEATURES_RESEARCH_ONLY": True,
        "FAST_PROSPECTIVE_HYPOTHESIS_CANDIDATES": [
            "A1_A2_RANK_DISAGREEMENT", "A2_SCORE_CROSS_SECTIONAL_STD",
            "A1_A2_MEAN_ABS_RANK_DIFFERENCE", "FROZEN_FEATURE_STATE_CONDITIONAL_RELIABILITY",
        ],
        "REPRODUCIBILITY_STATUS": reproducibility,
        "RUN1_FINGERPRINT": run1_fingerprint,
        "RUN2_FINGERPRINT": run2_fingerprint,
        "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "SUMMARY_PATH": str(SUMMARY_PATH),
        "MANIFEST_PATH": str(MANIFEST_PATH),
        "SIGNAL_ENTRY_EVENTS_PATH": str(SIGNAL_EVENTS_PATH),
        "DISAGREEMENT_ANALYSIS_PATH": str(DISAGREEMENT_PATH),
        "DAILY_INCREMENTAL_EDGE_PATH": str(DAILY_EDGE_PATH),
        "FEATURE_MECHANISM_ANALYSIS_PATH": str(FEATURE_MECHANISM_PATH),
        "STATE_CONDITIONAL_ANALYSIS_PATH": str(STATE_CONDITIONAL_PATH),
        "NEXT_AUTHORIZED_STEP": next_step,
        "FAILURE_REASON": None,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
        "year_roles": analysis_contract()["year_roles"],
    }
    write_json_atomic(SUMMARY_PATH, summary)
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "schema_version": "1.0",
        "analysis_contract_frozen_at_utc": witness["frozen_at_utc"],
        "first_r1_outcome_read_at_utc": first_outcome_read_at.isoformat(),
        "contract_frozen_before_outcome_read": first_outcome_read_at > frozen_at,
        "analysis_contract_sha256": EXPECTED_ANALYSIS_CONTRACT_SHA256,
        "run1_fingerprint": run1_fingerprint,
        "run2_fingerprint": run2_fingerprint,
        "reproducibility_status": reproducibility,
        "artifact_sha256": {
            str(SUMMARY_PATH): sha256_file(SUMMARY_PATH),
            str(SIGNAL_EVENTS_PATH): sha256_file(SIGNAL_EVENTS_PATH),
            str(DISAGREEMENT_PATH): sha256_file(DISAGREEMENT_PATH),
            str(DAILY_EDGE_PATH): sha256_file(DAILY_EDGE_PATH),
            str(FEATURE_MECHANISM_PATH): sha256_file(FEATURE_MECHANISM_PATH),
            str(STATE_CONDITIONAL_PATH): sha256_file(STATE_CONDITIONAL_PATH),
        },
        "mechanism_refit_count": total_refits,
        "model_training_for_selection_count": 0,
        "post2025_target_read_count": 0,
        "post2025_outcome_read_count": 0,
    }
    write_json_atomic(MANIFEST_PATH, manifest)
    return summary


def _display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


CORE_FIELDS = (
    "ABCDE_A2_R2_STATUS", "ABCDE_A2_R2_CLASSIFICATION", "ABCDE_A2_R2_DECISION",
    "R2_RESEARCH_ROLE", "R2_ANALYSIS_CONTRACT_FROZEN_BEFORE_OUTCOME_READ", "R2_ANALYSIS_CONTRACT_SHA256",
    "A2_R1_MODEL_CHANGED", "A2_R1_FEATURE_SCHEMA_CHANGED", "A1_PRODUCTION_CHANGED",
    "SIGNAL_LAG_EVIDENCE", "A1_TOP20_PRE_5D_MEAN", "A2_TOP20_PRE_5D_MEAN",
    "A1_TOP20_POST_5D_MEAN", "A2_TOP20_POST_5D_MEAN", "A1_TOP20_POST_10D_MEAN",
    "A2_TOP20_POST_10D_MEAN", "A1_TOP20_POST_20D_MEAN", "A2_TOP20_POST_20D_MEAN",
    "DISAGREEMENT_Q5_MINUS_Q1_TARGET_SPREAD", "TOP_INCREMENTAL_FEATURES",
    "REPEATABLE_FEATURE_FAMILY_OR_INTERACTION_STRUCTURE", "MODEL_TRAINING_FOR_SELECTION_COUNT",
    "MECHANISM_REFIT_COUNT", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT",
    "2026_MODEL_SELECTION_USE_COUNT", "FAST_CANDIDATE_FEATURES_RESEARCH_ONLY", "FAST_CHANGED",
    "DAILY_CHAIN_CHANGED", "BROKER_ACTION_COUNT", "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT",
    "RUN2_FINGERPRINT", "ANTI_BLOAT_STATUS", "RESULTS_ROOT", "SUMMARY_PATH", "NEXT_AUTHORIZED_STEP",
    "FAILURE_REASON",
)


def print_core(summary: dict[str, Any]) -> None:
    for field in CORE_FIELDS:
        print(f"{field}={_display(summary.get(field))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-contract-only", action="store_true")
    args = parser.parse_args(argv)
    witness = freeze_analysis_contract()
    print("R2_ANALYSIS_CONTRACT_FROZEN_BEFORE_OUTCOME_READ=true")
    print(f"R2_ANALYSIS_CONTRACT_SHA256={witness['contract_sha256']}")
    print(f"R2_ANALYSIS_CONTRACT_PATH={ANALYSIS_CONTRACT_PATH}")
    if args.freeze_contract_only:
        return 0
    try:
        summary = run_analysis()
    except Exception as exc:
        summary = {
            "ABCDE_A2_R2_STATUS": "FAIL_CLOSED",
            "ABCDE_A2_R2_CLASSIFICATION": "FAIL_CLOSED",
            "ABCDE_A2_R2_DECISION": "STOP_AND_REPAIR_EXPLICIT_R2_DATA_OR_CONTRACT_FAILURE",
            "R2_ANALYSIS_CONTRACT_FROZEN_BEFORE_OUTCOME_READ": True,
            "R2_ANALYSIS_CONTRACT_SHA256": witness["contract_sha256"],
            "MODEL_TRAINING_FOR_SELECTION_COUNT": 0,
            "POST2025_TARGET_READ_COUNT": 0,
            "POST2025_OUTCOME_READ_COUNT": 0,
            "2026_MODEL_SELECTION_USE_COUNT": 0,
            "BROKER_ACTION_COUNT": 0,
            "A2_R1_MODEL_CHANGED": False,
            "A2_R1_FEATURE_SCHEMA_CHANGED": False,
            "A1_PRODUCTION_CHANGED": False,
            "FAST_CHANGED": False,
            "DAILY_CHAIN_CHANGED": False,
            "NEXT_AUTHORIZED_STEP": "REPAIR_EXPLICIT_R2_DATA_OR_CONTRACT_FAILURE_ONLY",
            "FAILURE_REASON": f"{type(exc).__name__}:{exc}",
        }
        write_json_atomic(SUMMARY_PATH, summary)
        print_core(summary)
        return 2
    print_core(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
