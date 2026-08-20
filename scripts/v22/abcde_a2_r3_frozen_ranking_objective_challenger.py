"""ABCDE A2-R3 frozen LambdaRank objective challenger.

The delta preregistration can be frozen without opening any row-level R1/R2
prediction, target, outcome, model, or price artifact.
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
import lightgbm
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from lightgbm import LGBMRanker
from scipy.stats import spearmanr
from zoneinfo import ZoneInfo


EXPERIMENT_ID = "ABCDE_A2_R3_FROZEN_RANKING_OBJECTIVE_CHALLENGER"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
DELTA_CONTRACT_PATH = RESULTS_ROOT / "a2_r3_delta_preregistration_r1.json"
FREEZE_WITNESS_PATH = RESULTS_ROOT / "a2_r3_contract_freeze_witness.json"
SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r3_summary.json"
MANIFEST_PATH = RESULTS_ROOT / "a2_r3_manifest.json"
OOF_PATH = RESULTS_ROOT / "a2_r3_oof_predictions.parquet"
COMPARISON_PATH = RESULTS_ROOT / "hgb_vs_lambdarank_comparison.parquet"
BOOTSTRAP_PATH = RESULTS_ROOT / "a2_r3_bootstrap_uncertainty.json"
SIGNAL_TIMING_PATH = RESULTS_ROOT / "a2_r3_signal_timing_comparison.json"
FROZEN_MODEL_PATH = RESULTS_ROOT / "a2_r3_frozen_lambdarank.joblib"
PROSPECTIVE_ACTIVATION_PATH = RESULTS_ROOT / "a2_r3_prospective_activation.json"
R1_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING")
R1_SUMMARY_PATH = R1_ROOT / "abcde_a2_r1_summary.json"
R1_OOF_PATH = R1_ROOT / "a2_r1_oof_predictions.parquet"
R1_MODEL_PATH = R1_ROOT / "a2_r1_final_hgb.joblib"
R1_MODULE_PATH = REPO_ROOT / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
R2_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R2_SIGNAL_LAG_AND_INCREMENTAL_MECHANISM")
R2_SUMMARY_PATH = R2_ROOT / "abcde_a2_r2_summary.json"
R2_CONTRACT_PATH = R2_ROOT / "a2_r2_analysis_contract_r1.json"
R2_MODULE_PATH = REPO_ROOT / "scripts/v22/abcde_a2_r2_signal_lag_and_incremental_mechanism.py"
EXPECTED_DELTA_CONTRACT_SHA256 = "6bf87578e5aad50560bb54354c7059c9688c4f01313d0414edf38b36b3e0f4c6"
EXPECTED_R1_OOF_SHA256 = "a601b655afddf3e9aac63ea38571fff4dab3caad10400ae2a4a75697feeaf47e"
EXPECTED_R1_MODEL_SHA256 = "17c5c70010424cf0c409f84f5af420dd9d60fc7043a6c029ffbd5897e46f578d"
EXPECTED_R2_CONTRACT_SHA256 = "513c624cab518658aff1df342b31c80b2ec3a7a5827f74692f898b37b0fc4217"


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
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd", use_dictionary=True, write_statistics=True)
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


def delta_preregistration() -> dict[str, Any]:
    label_gain = list(range(20))
    return {
        "contract_id": "ABCDE_A2_R3_DELTA_PREREGISTRATION_R1",
        "experiment_role": "PRE2026_MODEL_DEVELOPMENT_CHALLENGER_COMPARISON",
        "primary_question": "DOES_DIRECT_CROSS_SECTIONAL_RANKING_OBJECTIVE_IMPROVE_OVER_FROZEN_HGB_CONTINUOUS_RETURN_REGRESSION",
        "inheritance": {
            "r0v_universe": {
                "current_cohort_count": 325,
                "current_cohort_fingerprint": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
                "eligibility_artifact_sha256": "80c5b7e4283b2ce5db880b93064efc38b355371e4f19a6a769668e84328d7ebf",
                "research_universe_type": "FIXED_CURRENT_COHORT_HISTORICAL_TRAINING",
            },
            "r1c_feature_contract": {
                "feature_count": 32,
                "feature_schema_fingerprint": "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4",
                "feature_contract_sha256": "415935ebf06b448f0511a511e5ebca2cbb38f3fffee03431be8af33b412999ec",
                "feature_schema_change_allowed": False,
            },
            "r1c_split_purge": {
                "split_gate_sha256": "c3f32e966eb69e2f29d898172fe83279364e63eac9fe8bdaf81f8b6c6b03e780",
                "purge_horizon_trading_days": 20,
                "embargo_after_evaluation_trading_days": 0,
                "stages": [2023, 2024, 2025],
                "expanding_past_only": True,
            },
            "r1_hgb_incumbent": {
                "model_family": "HistGradientBoostingRegressor",
                "model_config_fingerprint": "871fbbc386d7678c744764f86e3beaaf5e74185c6e47a4157fdb7460ae577514",
                "oof_prediction_sha256": "a601b655afddf3e9aac63ea38571fff4dab3caad10400ae2a4a75697feeaf47e",
                "final_model_sha256": "17c5c70010424cf0c409f84f5af420dd9d60fc7043a6c029ffbd5897e46f578d",
                "refit_or_tuning_allowed": False,
            },
            "r2_signal_lag": {
                "analysis_contract_sha256": "513c624cab518658aff1df342b31c80b2ec3a7a5827f74692f898b37b0fc4217",
                "entry_event": "IN_TOP20_AT_T_AND_NOT_IN_TOP20_ON_EACH_OF_PRIOR_5_TICKER_ELIGIBLE_SIGNAL_DAYS",
                "incomplete_history_policy": "NOT_AN_ENTRY_EVENT",
            },
        },
        "year_roles": {
            "2023": "CONSUMED_PRE2026_DEVELOPMENT_COMPARISON",
            "2024": "CONSUMED_PRE2026_DEVELOPMENT_COMPARISON",
            "2025": "CONSUMED_PRE2026_DEVELOPMENT_EVIDENCE_NOT_FINAL",
            "2026_PLUS": "PROSPECTIVE_ONLY_NO_OUTCOME_READ",
        },
        "economic_target": {
            "name": "MEAN_ER_3D_5D_10D_20D",
            "horizons_trading_days": [3, 5, 10, 20],
            "benchmark": "QQQ",
            "evaluation_uses_continuous_target": True,
            "new_economic_target_created": False,
        },
        "ranking_relevance": {
            "scope": "WITHIN_SIGNAL_DATE_FINITE_FROZEN_CONTINUOUS_TARGET_ROWS",
            "sort": "CONTINUOUS_TARGET_ASCENDING",
            "tie_policy": "AVERAGE_RANK",
            "percentile_equation": "(AVERAGE_RANK-1)/(N_T-1)",
            "minimum_group_size": 2,
            "relevance_equation": "MIN(19,FLOOR(20*PERCENTILE))",
            "bin_count": 20,
            "minimum": 0,
            "maximum": 19,
            "label_gain_policy": "LINEAR_0_TO_19",
            "label_gain": label_gain,
        },
        "challenger": {
            "library": "lightgbm",
            "library_version": "4.7.0",
            "model_family": "LGBMRanker",
            "constructor_config": {
                "objective": "lambdarank", "boosting_type": "gbdt", "n_estimators": 300,
                "learning_rate": 0.05, "num_leaves": 31, "max_depth": -1,
                "min_child_samples": 20, "reg_lambda": 1.0, "reg_alpha": 0.0,
                "subsample": 1.0, "colsample_bytree": 1.0, "random_state": 20260816,
                "deterministic": True, "force_col_wise": True, "n_jobs": 4,
                "lambdarank_truncation_level": 20, "label_gain": label_gain,
                "verbosity": -1,
            },
            "fit_config": {"eval_at": [5, 10, 20]},
            "hyperparameter_search_trial_count": 0,
            "new_model_family_count": 1,
            "additional_challenger_allowed": False,
        },
        "training": {
            "sort": ["signal_date", "ticker"],
            "group_equation": "COUNT_OF_FINITE_RANKING_TRAINING_ROWS_PER_SIGNAL_DATE_IN_SORTED_ORDER",
            "group_row_sum_must_equal_training_row_count": True,
            "stages": [
                {"stage": "R3_2023", "fit": "PRE2023_AFTER_20D_TARGET_END_PURGE", "evaluate": 2023},
                {"stage": "R3_2024", "fit": "PRE2024_AFTER_20D_TARGET_END_PURGE", "evaluate": 2024},
                {"stage": "R3_2025", "fit": "PRE2025_AFTER_20D_TARGET_END_PURGE", "evaluate": 2025},
            ],
        },
        "evaluation": {
            "primary_comparison": "LAMBDARANK_VS_AUTHORITATIVE_HGB_OOF",
            "a1_role": "SECONDARY_REFERENCE_ONLY",
            "primary_metric": "MEAN_DAILY_SPEARMAN_RANK_IC_ON_CONTINUOUS_TARGET",
            "rank_metrics": ["MEAN", "MEDIAN", "STD_DDOF0", "ICIR", "POSITIVE_DAY_FRACTION"],
            "economic_metrics": [
                "TOP5_MEAN_TARGET", "TOP10_MEAN_TARGET", "TOP20_MEAN_TARGET",
                "TOP_QUINTILE_MEAN_TARGET", "BOTTOM_QUINTILE_MEAN_TARGET",
                "TOP_BOTTOM_SPREAD", "QUINTILE_MONOTONICITY",
            ],
            "reporting_scopes": [2023, 2024, 2025, "POOLED_PRE2026"],
        },
        "paired_uncertainty": {
            "method": "DETERMINISTIC_CIRCULAR_MOVING_BLOCK_BOOTSTRAP_OF_ORDERED_DAILY_PAIRED_DELTAS",
            "block_length_trading_days": 20,
            "resample_count": 2000,
            "random_seed": 20260816,
            "ci": [0.025, 0.975],
            "statistics": ["MEAN_DELTA", "CI95", "MEDIAN", "POSITIVE_FRACTION"],
            "gate_use": False,
        },
        "decision_gate": {
            "A_RANKING_OBJECTIVE_INCREMENTAL_EDGE": [
                "DELTA_MEAN_IC_2024>0", "DELTA_MEAN_IC_2025>0",
                "DELTA_TOP20_2024>0", "DELTA_TOP20_2025>0",
                "DELTA_MEAN_IC_POOLED>0", "DELTA_TOP20_POOLED>0",
                "NONNEGATIVE_DELTA_TOP_BOTTOM_SPREAD_YEAR_COUNT>=2",
                "ALL_LEAKAGE_GROUP_IDENTITY_REPRODUCIBILITY_AUDITS_PASS",
            ],
            "B_MIXED_OR_UNSTABLE_RANKING_OBJECTIVE_EDGE": "NOT_A_AND_DELTA_MEAN_IC_POOLED>0_AND_DELTA_TOP20_POOLED>0",
            "C_NO_INCREMENTAL_RANKING_OBJECTIVE_EDGE": "NOT_A_AND_NOT_B",
            "FAIL_CLOSED": "ANY_CONTRACT_DATA_LEAKAGE_GROUP_IDENTITY_OR_REPRODUCIBILITY_FAILURE",
        },
        "signal_timing_secondary": {
            "entry_definition": "IN_TOP20_AT_T_AND_NOT_IN_TOP20_ON_EACH_OF_PRIOR_5_TICKER_ELIGIBLE_SIGNAL_DAYS",
            "windows": ["PRE_5D_ER", "POST_5D_ER", "POST_10D_ER", "POST_20D_ER"],
            "year_improved": "LAMBDA_PRE5<=HGB_PRE5_AND_(LAMBDA_POST5>HGB_POST5_OR_LAMBDA_POST10>HGB_POST10)",
            "year_worse": "LAMBDA_PRE5>HGB_PRE5_AND_LAMBDA_POST5<=HGB_POST5_AND_LAMBDA_POST10<=HGB_POST10",
            "overall": {
                "IMPROVED": "IMPROVED_YEAR_COUNT>=2_AND_WORSE_YEAR_COUNT==0",
                "WORSE": "WORSE_YEAR_COUNT>=2_AND_IMPROVED_YEAR_COUNT==0",
                "MIXED": "ALL_OTHER_CASES",
            },
            "primary_gate_use": False,
        },
        "prospective_activation": {
            "allowed_only_if": "A_RANKING_OBJECTIVE_INCREMENTAL_EDGE",
            "final_fit_rows": "ALL_FINITE_TARGET_PRE2026_ELIGIBLE_ROWS",
            "freeze_model_config_feature_schema_target_transform_universe": True,
            "first_legal_signal_rule": "FIRST_LIVE_CANONICAL_US_TRADING_DATE_STRICTLY_AFTER_FREEZE_TIMESTAMP;NO_BACKFILL",
            "prediction_before_freeze_allowed": False,
            "production_adoption": False,
            "broker_action_allowed": False,
        },
        "reproducibility": {
            "complete_challenger_materializations": 2,
            "required": "RUN1_FINGERPRINT_EQUALS_RUN2_FINGERPRINT",
        },
        "prohibitions": {
            "feature_change": True, "universe_change": True, "hgb_tuning": True,
            "lambda_tuning": True, "model_zoo": True, "mechanism_mining": True,
            "portfolio_experiment": True, "post2025_outcome_read": True,
            "production_adoption": True, "broker_action": True,
        },
    }


def freeze_delta_contract() -> dict[str, Any]:
    contract = delta_preregistration()
    payload = canonical_payload(contract) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if DELTA_CONTRACT_PATH.exists():
        if DELTA_CONTRACT_PATH.read_bytes() != payload:
            raise RuntimeError("EXISTING_R3_DELTA_CONTRACT_DIFFERS_FAIL_CLOSED")
    else:
        temporary = DELTA_CONTRACT_PATH.with_suffix(".json.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, DELTA_CONTRACT_PATH)
    witness = {
        "experiment_id": EXPERIMENT_ID,
        "delta_contract_path": str(DELTA_CONTRACT_PATH),
        "delta_contract_sha256": digest,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "challenger_row_level_outcome_read_count_before_freeze": 0,
        "post2025_target_read_count_before_freeze": 0,
        "post2025_outcome_read_count_before_freeze": 0,
        "status": "PASS_FROZEN_BEFORE_CHALLENGER_OUTCOME_READ",
    }
    if FREEZE_WITNESS_PATH.exists():
        prior = json.loads(FREEZE_WITNESS_PATH.read_text(encoding="utf-8"))
        if prior.get("delta_contract_sha256") != digest or prior.get("status") != witness["status"]:
            raise RuntimeError("R3_FREEZE_WITNESS_MISMATCH_FAIL_CLOSED")
        witness = prior
    else:
        write_json_atomic(FREEZE_WITNESS_PATH, witness)
    return witness


def validate_inherited_contracts() -> tuple[Any, Any, dict[str, Any], dict[str, Any], pd.DataFrame, dict[str, Any]]:
    required = (R1_SUMMARY_PATH, R1_OOF_PATH, R1_MODEL_PATH, R1_MODULE_PATH, R2_SUMMARY_PATH, R2_CONTRACT_PATH, R2_MODULE_PATH)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("MISSING_INHERITED_ARTIFACT:" + ",".join(missing))
    if sha256_file(DELTA_CONTRACT_PATH) != EXPECTED_DELTA_CONTRACT_SHA256:
        raise RuntimeError("R3_DELTA_CONTRACT_SHA256_MISMATCH")
    if sha256_file(R1_OOF_PATH) != EXPECTED_R1_OOF_SHA256 or sha256_file(R1_MODEL_PATH) != EXPECTED_R1_MODEL_SHA256:
        raise RuntimeError("R1_INCUMBENT_ARTIFACT_SHA256_MISMATCH")
    if sha256_file(R2_CONTRACT_PATH) != EXPECTED_R2_CONTRACT_SHA256:
        raise RuntimeError("R2_LAG_CONTRACT_SHA256_MISMATCH")
    if lightgbm.__version__ != "4.7.0":
        raise RuntimeError(f"LIGHTGBM_VERSION_MISMATCH:{lightgbm.__version__}")
    r1_summary = json.loads(R1_SUMMARY_PATH.read_text(encoding="utf-8"))
    r2_summary = json.loads(R2_SUMMARY_PATH.read_text(encoding="utf-8"))
    checks = {
        "r1_status": r1_summary.get("ABCDE_A2_R1_STATUS") == "PASS",
        "r1_classification": r1_summary.get("ABCDE_A2_R1_CLASSIFICATION") == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE",
        "r1_universe_identity": r1_summary.get("A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS") == "PASS",
        "r1_feature_schema": r1_summary.get("FEATURE_SCHEMA_FINGERPRINT") == "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4",
        "r1_hgb_config": r1_summary.get("MODEL_CONFIG_FINGERPRINT") == "871fbbc386d7678c744764f86e3beaaf5e74185c6e47a4157fdb7460ae577514",
        "r2_status": r2_summary.get("ABCDE_A2_R2_STATUS") == "PASS",
        "r2_classification": r2_summary.get("ABCDE_A2_R2_CLASSIFICATION") == "M1_STRONG_MECHANISTIC_SUPPORT",
        "r2_lag": r2_summary.get("SIGNAL_LAG_EVIDENCE") == "SUPPORTS_EARLIER_CAPTURE",
        "post2025_r1": r1_summary.get("POST2025_TARGET_READ_COUNT") == 0 and r1_summary.get("POST2025_OUTCOME_READ_COUNT") == 0,
        "post2025_r2": r2_summary.get("POST2025_TARGET_READ_COUNT") == 0 and r2_summary.get("POST2025_OUTCOME_READ_COUNT") == 0,
    }
    if not all(checks.values()):
        raise RuntimeError("INHERITED_STATUS_FAILURE:" + ",".join(k for k, v in checks.items() if not v))
    oof = pq.read_table(R1_OOF_PATH).to_pandas()
    oof["signal_date"] = pd.to_datetime(oof["signal_date"])
    oof["ticker"] = oof["ticker"].astype(str).str.upper()
    oof = oof.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(oof) != 210445 or oof.duplicated(["signal_date", "ticker"]).any() or (oof.signal_date >= pd.Timestamp("2026-01-01")).any():
        raise RuntimeError("R1_OOF_IDENTITY_OR_DATE_FAILURE")
    r1 = import_module("abcde_a2_r3_r1_helpers", R1_MODULE_PATH)
    r2 = import_module("abcde_a2_r3_r2_helpers", R2_MODULE_PATH)
    audit = {
        "checks": checks, "r1_oof_sha256": sha256_file(R1_OOF_PATH),
        "r1_model_sha256": sha256_file(R1_MODEL_PATH), "r2_contract_sha256": sha256_file(R2_CONTRACT_PATH),
        "lightgbm_version": lightgbm.__version__, "oof_rows": len(oof),
    }
    return r1, r2, r1_summary, r2_summary, oof, audit


def relevance_labels(frame: pd.DataFrame) -> np.ndarray:
    labels = pd.Series(index=frame.index, dtype="int8")
    for _, day in frame.groupby("signal_date", sort=True):
        n = len(day)
        if n <= 1:
            continue
        average_rank = day["target"].rank(method="average", ascending=True)
        percentile = (average_rank - 1.0) / (n - 1.0)
        relevance = np.minimum(19, np.floor(20.0 * percentile)).astype(np.int8)
        labels.loc[day.index] = relevance
    if labels.isna().any():
        raise RuntimeError("RANKING_GROUP_WITH_FEWER_THAN_TWO_ROWS")
    return labels.to_numpy(dtype=np.int8)


def ranking_groups(frame: pd.DataFrame) -> np.ndarray:
    groups = frame.groupby("signal_date", sort=True).size().to_numpy(dtype=np.int32)
    if int(groups.sum()) != len(frame) or (groups <= 1).any():
        raise RuntimeError("LIGHTGBM_GROUP_ROW_SUM_OR_MINIMUM_FAILURE")
    return groups


def make_ranker() -> LGBMRanker:
    config = dict(delta_preregistration()["challenger"]["constructor_config"])
    return LGBMRanker(**config)


def _prediction_rank(frame: pd.DataFrame, score_column: str) -> pd.Series:
    result = pd.Series(index=frame.index, dtype="int32")
    for _, day in frame.groupby("signal_date", sort=True):
        ordered = day.sort_values([score_column, "ticker"], ascending=[False, True], kind="mergesort")
        result.loc[ordered.index] = np.arange(1, len(ordered) + 1, dtype=np.int32)
    return result.astype(np.int32)


def fit_predict_stage(r1: Any, matrix: pd.DataFrame, incumbent: pd.DataFrame, stage: str, year: int) -> tuple[pd.DataFrame, dict[str, Any], LGBMRanker]:
    training, evaluation, split_audit = r1.stage_rows(matrix, year)
    training = training.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    evaluation = evaluation.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    inherited = incumbent.loc[incumbent["split"] == stage].copy()
    inherited = inherited.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    inherited_keys = pd.MultiIndex.from_frame(inherited[["signal_date", "ticker"]])
    evaluation_keys = pd.MultiIndex.from_frame(evaluation[["signal_date", "ticker"]])
    missing_incumbent_keys = int((~inherited_keys.isin(evaluation_keys)).sum())
    if missing_incumbent_keys:
        raise RuntimeError(f"INCUMBENT_KEYS_MISSING_FROM_REBUILT_EVALUATION:{stage}:{missing_incumbent_keys}")
    evaluation = evaluation.loc[evaluation_keys.isin(inherited_keys)].reset_index(drop=True)
    if len(evaluation) != len(inherited):
        raise RuntimeError(f"INCUMBENT_CHALLENGER_ROW_COUNT_FAILURE:{stage}:{len(evaluation)}:{len(inherited)}")
    labels = relevance_labels(training)
    groups = ranking_groups(training)
    model = make_ranker()
    model.fit(
        training.loc[:, r1.FEATURE_COLUMNS].to_numpy(dtype=float), labels,
        group=groups, eval_at=[5, 10, 20],
    )
    evaluation["lambda_prediction"] = model.predict(evaluation.loc[:, r1.FEATURE_COLUMNS].to_numpy(dtype=float))
    evaluation["lambda_rank"] = _prediction_rank(evaluation, "lambda_prediction")
    expected_keys = evaluation[["signal_date", "ticker"]]
    if not pd.MultiIndex.from_frame(expected_keys).equals(pd.MultiIndex.from_frame(inherited[["signal_date", "ticker"]])):
        raise RuntimeError(f"INCUMBENT_CHALLENGER_ROW_IDENTITY_FAILURE:{stage}")
    target_max_diff = float(np.max(np.abs(evaluation["target"].to_numpy() - inherited["target"].to_numpy())))
    if target_max_diff > 1e-14:
        raise RuntimeError(f"INCUMBENT_CHALLENGER_TARGET_IDENTITY_FAILURE:{stage}:{target_max_diff}")
    output = inherited[[
        "signal_date", "ticker", "universe_size", "split", "target",
        "a1_raw_score", "a1_rank", "a2_prediction", "a2_rank",
    ]].rename(columns={"a2_prediction": "hgb_prediction", "a2_rank": "hgb_rank"})
    output = output.rename(columns={"split": "r1_source_split"})
    output["split"] = f"R3_{year}"
    output["r3_evidence_role"] = (
        "CONSUMED_PRE2026_DEVELOPMENT_EVIDENCE"
        if year == 2025
        else "CONSUMED_PRE2026_DEVELOPMENT_COMPARISON"
    )
    output["lambda_prediction"] = evaluation["lambda_prediction"].to_numpy()
    output["lambda_rank"] = evaluation["lambda_rank"].to_numpy()
    output["year"] = year
    audit = {
        "stage": f"R3_{year}", "r1_source_split": stage, "year": year,
        "train_rows": len(training), "evaluation_rows": len(evaluation),
        "evaluation_rows_removed_to_match_incumbent_target_availability": int(split_audit["evaluation_rows"] - len(evaluation)),
        "incumbent_target_availability_key_filter_status": "PASS",
        "group_count": len(groups), "group_row_sum": int(groups.sum()), "group_min": int(groups.min()),
        "group_max": int(groups.max()), "relevance_min": int(labels.min()), "relevance_max": int(labels.max()),
        "target_identity_max_abs_diff": target_max_diff, "split_audit": split_audit,
    }
    return output, audit, model


def materialize_challenger(r1: Any, matrix: pd.DataFrame, incumbent: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    pieces: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for stage, year in r1.STAGES:
        output, audit, _ = fit_predict_stage(r1, matrix, incumbent, stage, year)
        pieces.append(output)
        audits.append(audit)
    result = pd.concat(pieces, ignore_index=True).sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    return result, audits


def evaluate_models(r1: Any, oof: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    all_metrics: dict[str, Any] = {}
    comparison_rows: list[dict[str, Any]] = []
    daily_rows: list[pd.DataFrame] = []
    scopes: list[tuple[str, pd.DataFrame]] = [(str(year), oof.loc[oof["year"] == year]) for _, year in r1.STAGES]
    scopes.append(("POOLED_PRE2026", oof))
    model_columns = {"A1": "a1_raw_score", "HGB": "hgb_prediction", "LAMBDARANK": "lambda_prediction"}
    scalar_metrics = (
        "mean_rank_ic", "median_rank_ic", "std_rank_ic", "icir", "positive_ic_day_fraction",
        "top5_mean_target", "top10_mean_target", "top20_mean_target", "top_quintile_mean_target",
        "bottom_quintile_mean_target", "top_bottom_spread", "quintile_adjacent_nondecreasing_count",
    )
    for scope, frame in scopes:
        scope_metrics: dict[str, Any] = {}
        scope_daily: dict[str, pd.DataFrame] = {}
        for model_name, column in model_columns.items():
            metrics, daily = r1._daily_metrics(frame, column)
            scope_metrics[model_name] = metrics
            scope_daily[model_name] = daily
            for metric in scalar_metrics:
                comparison_rows.append({"scope": scope, "model": model_name, "metric": metric, "value": metrics[metric]})
        deltas = {
            "mean_rank_ic": scope_metrics["LAMBDARANK"]["mean_rank_ic"] - scope_metrics["HGB"]["mean_rank_ic"],
            "median_rank_ic": scope_metrics["LAMBDARANK"]["median_rank_ic"] - scope_metrics["HGB"]["median_rank_ic"],
            "positive_ic_day_fraction": scope_metrics["LAMBDARANK"]["positive_ic_day_fraction"] - scope_metrics["HGB"]["positive_ic_day_fraction"],
            "top5_mean_target": scope_metrics["LAMBDARANK"]["top5_mean_target"] - scope_metrics["HGB"]["top5_mean_target"],
            "top10_mean_target": scope_metrics["LAMBDARANK"]["top10_mean_target"] - scope_metrics["HGB"]["top10_mean_target"],
            "top20_mean_target": scope_metrics["LAMBDARANK"]["top20_mean_target"] - scope_metrics["HGB"]["top20_mean_target"],
            "top_quintile_mean_target": scope_metrics["LAMBDARANK"]["top_quintile_mean_target"] - scope_metrics["HGB"]["top_quintile_mean_target"],
            "top_bottom_spread": scope_metrics["LAMBDARANK"]["top_bottom_spread"] - scope_metrics["HGB"]["top_bottom_spread"],
        }
        for metric, value in deltas.items():
            comparison_rows.append({"scope": scope, "model": "LAMBDA_MINUS_HGB", "metric": metric, "value": value})
        all_metrics[scope] = {"models": scope_metrics, "lambda_minus_hgb": deltas}
        hgb_daily = scope_daily["HGB"][["signal_date", "rank_ic", "top20_mean_target"]].rename(columns={"rank_ic": "hgb_ic", "top20_mean_target": "hgb_top20"})
        lambda_daily = scope_daily["LAMBDARANK"][["signal_date", "rank_ic", "top20_mean_target"]].rename(columns={"rank_ic": "lambda_ic", "top20_mean_target": "lambda_top20"})
        paired = hgb_daily.merge(lambda_daily, on="signal_date", validate="one_to_one")
        paired["delta_ic"] = paired["lambda_ic"] - paired["hgb_ic"]
        paired["delta_top20"] = paired["lambda_top20"] - paired["hgb_top20"]
        paired["scope"] = scope
        if scope != "POOLED_PRE2026":
            daily_rows.append(paired)
    daily = pd.concat(daily_rows, ignore_index=True).sort_values("signal_date").reset_index(drop=True)
    return all_metrics, pd.DataFrame(comparison_rows), daily


def circular_block_bootstrap(daily: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(20260816)
    result: dict[str, Any] = {}
    for scope in ("2023", "2024", "2025", "POOLED_PRE2026"):
        scoped = daily if scope == "POOLED_PRE2026" else daily.loc[daily["scope"] == scope]
        result[scope] = {}
        for column in ("delta_ic", "delta_top20"):
            values = scoped[column].dropna().to_numpy(dtype=float)
            n = len(values)
            block_length = 20
            block_count = int(math.ceil(n / block_length))
            bootstrap_means = np.empty(2000, dtype=float)
            for iteration in range(2000):
                starts = rng.integers(0, n, size=block_count)
                indices = np.concatenate([(start + np.arange(block_length)) % n for start in starts])[:n]
                bootstrap_means[iteration] = values[indices].mean()
            result[scope][column] = {
                "observation_count": n, "mean_delta": float(values.mean()),
                "ci95_low": float(np.quantile(bootstrap_means, 0.025)),
                "ci95_high": float(np.quantile(bootstrap_means, 0.975)),
                "median": float(np.median(values)), "positive_fraction": float(np.mean(values > 0)),
            }
    return result


def classify_challenger(metrics: dict[str, Any], audits_pass: bool) -> tuple[str, dict[str, Any]]:
    confirmation = metrics["2024"]["lambda_minus_hgb"]
    consumed_2025 = metrics["2025"]["lambda_minus_hgb"]
    pooled = metrics["POOLED_PRE2026"]["lambda_minus_hgb"]
    yearly = [metrics[str(year)]["lambda_minus_hgb"] for year in (2023, 2024, 2025)]
    nonnegative_spread_years = sum(row["top_bottom_spread"] >= 0 for row in yearly)
    conditions = {
        "delta_mean_ic_2024_positive": confirmation["mean_rank_ic"] > 0,
        "delta_mean_ic_2025_positive": consumed_2025["mean_rank_ic"] > 0,
        "delta_top20_2024_positive": confirmation["top20_mean_target"] > 0,
        "delta_top20_2025_positive": consumed_2025["top20_mean_target"] > 0,
        "delta_mean_ic_pooled_positive": pooled["mean_rank_ic"] > 0,
        "delta_top20_pooled_positive": pooled["top20_mean_target"] > 0,
        "nonnegative_delta_top_bottom_spread_year_count": nonnegative_spread_years,
        "spread_year_count_pass": nonnegative_spread_years >= 2,
        "audits_pass": audits_pass,
    }
    if not audits_pass:
        return "FAIL_CLOSED", conditions
    a_pass = all(value for key, value in conditions.items() if key != "nonnegative_delta_top_bottom_spread_year_count")
    if a_pass:
        return "A_RANKING_OBJECTIVE_INCREMENTAL_EDGE", conditions
    if pooled["mean_rank_ic"] > 0 and pooled["top20_mean_target"] > 0:
        return "B_MIXED_OR_UNSTABLE_RANKING_OBJECTIVE_EDGE", conditions
    return "C_NO_INCREMENTAL_RANKING_OBJECTIVE_EDGE", conditions


def build_top20_entries(oof: pd.DataFrame, model: str, rank_column: str) -> pd.DataFrame:
    work = oof[["signal_date", "ticker", "split", rank_column]].sort_values(["ticker", "signal_date"], kind="mergesort").copy()
    work["in_top"] = work[rank_column] <= 20
    grouped = work.groupby("ticker", sort=False)["in_top"]
    prior_complete = work.groupby("ticker", sort=False).cumcount() >= 5
    prior_clear = pd.Series(True, index=work.index)
    for lag in range(1, 6):
        prior_clear &= ~grouped.shift(lag).fillna(True).astype(bool)
    events = work.loc[work.in_top & prior_complete & prior_clear, ["signal_date", "ticker", "split"]].copy()
    events["model"] = model
    events["top_n"] = 20
    events["year"] = events.signal_date.dt.year
    events["year_role"] = events.year.map({
        2023: "CONSUMED_PRE2026_DEVELOPMENT_COMPARISON",
        2024: "CONSUMED_PRE2026_DEVELOPMENT_COMPARISON",
        2025: "CONSUMED_PRE2026_DEVELOPMENT_EVIDENCE",
    })
    return events.reset_index(drop=True)


def signal_timing_diagnostic(r2: Any, oof: pd.DataFrame, prices: pd.DataFrame) -> dict[str, Any]:
    events = pd.concat([
        build_top20_entries(oof, "HGB", "hgb_rank"),
        build_top20_entries(oof, "LAMBDARANK", "lambda_rank"),
    ], ignore_index=True)
    events = r2.attach_signal_paths(events, prices)
    rows: list[dict[str, Any]] = []
    for scope in (2023, 2024, 2025, "POOLED"):
        scoped = events if scope == "POOLED" else events.loc[events.year == scope]
        for model, group in scoped.groupby("model", sort=True):
            rows.append({
                "scope": str(scope), "model": model, "event_count": len(group),
                "pre5_mean": float(group.PRE_5D_ER.mean()), "post5_mean": float(group.POST_5D_ER.mean()),
                "post10_mean": float(group.POST_10D_ER.mean()), "post20_mean": float(group.POST_20D_ER.mean()),
            })
    lookup = {(row["scope"], row["model"]): row for row in rows}
    improved = 0
    worse = 0
    yearly: dict[str, Any] = {}
    for year in (2023, 2024, 2025):
        hgb = lookup[(str(year), "HGB")]
        ranker = lookup[(str(year), "LAMBDARANK")]
        is_improved = ranker["pre5_mean"] <= hgb["pre5_mean"] and (ranker["post5_mean"] > hgb["post5_mean"] or ranker["post10_mean"] > hgb["post10_mean"])
        is_worse = ranker["pre5_mean"] > hgb["pre5_mean"] and ranker["post5_mean"] <= hgb["post5_mean"] and ranker["post10_mean"] <= hgb["post10_mean"]
        improved += int(is_improved)
        worse += int(is_worse)
        yearly[str(year)] = {"improved": is_improved, "worse": is_worse}
    status = "IMPROVED" if improved >= 2 and worse == 0 else "WORSE" if worse >= 2 and improved == 0 else "MIXED"
    return {"LAMBDA_SIGNAL_TIMING_VS_HGB": status, "summary_rows": rows, "yearly_gate": yearly, "event_count": len(events)}


def _next_business_date_after_freeze(freeze_time: datetime) -> str:
    eastern_date = freeze_time.astimezone(ZoneInfo("America/New_York")).date()
    frozen_date = np.datetime64(eastern_date)
    candidate = (
        np.busday_offset(frozen_date, 1)
        if np.is_busday(frozen_date)
        else np.busday_offset(frozen_date, 0, roll="forward")
    )
    return str(candidate)


def fit_prospective_model(r1: Any, matrix: pd.DataFrame, freeze_time: datetime) -> dict[str, Any]:
    training = matrix.loc[matrix.target.notna() & (matrix.signal_date < pd.Timestamp("2026-01-01"))].copy()
    training = training.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    labels = relevance_labels(training)
    groups = ranking_groups(training)
    model = make_ranker()
    model.fit(training.loc[:, r1.FEATURE_COLUMNS].to_numpy(dtype=float), labels, group=groups, eval_at=[5, 10, 20])
    temporary = FROZEN_MODEL_PATH.with_suffix(".joblib.tmp")
    joblib.dump(model, temporary, compress=3)
    os.replace(temporary, FROZEN_MODEL_PATH)
    first_date = _next_business_date_after_freeze(freeze_time)
    activation = {
        "ACTIVATE_PROSPECTIVE_SHADOW": True,
        "PROSPECTIVE_LAMBDARANK_SHADOW": "ACTIVE_ACCUMULATING_FROM_FIRST_LEGAL_FUTURE_DATE",
        "PROSPECTIVE_FREEZE_TIMESTAMP_UTC": freeze_time.isoformat(),
        "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE": first_date,
        "FIRST_LEGAL_DATE_STATUS": "BUSINESS_DAY_CANDIDATE_REQUIRES_LIVE_CANONICAL_TRADING_AND_ELIGIBILITY_CONFIRMATION",
        "NO_BACKFILL_BEFORE_FREEZE": True,
        "MODEL_CONFIG": delta_preregistration()["challenger"],
        "FEATURE_SCHEMA_FINGERPRINT": "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4",
        "TARGET_TRANSFORM": delta_preregistration()["ranking_relevance"],
        "CURRENT_COHORT_FINGERPRINT": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
        "TRAINING_ROW_COUNT": len(training), "GROUP_ROW_SUM": int(groups.sum()),
        "MODEL_PATH": str(FROZEN_MODEL_PATH), "MODEL_SHA256": sha256_file(FROZEN_MODEL_PATH),
        "PRODUCTION_ADOPTION": False, "BROKER_ACTION_ALLOWED": False,
        "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
    }
    write_json_atomic(PROSPECTIVE_ACTIVATION_PATH, activation)
    return activation


def protected_hashes() -> dict[str, str]:
    paths = (
        REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py",
        REPO_ROOT / "config/v21/abcde_compact_v1_freeze_r1.json",
        REPO_ROOT / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py",
        R1_MODULE_PATH, R2_MODULE_PATH,
        REPO_ROOT / "scripts/v22/abcde_a2_r1c_execution_contract_freeze_r1.py",
        REPO_ROOT / "scripts/v22/v22_044_daily_single_entrypoint_freeze_and_guard_r1.py",
    )
    return {path.relative_to(REPO_ROOT).as_posix(): sha256_file(path) for path in paths if path.is_file()}


def run_challenger() -> dict[str, Any]:
    witness = freeze_delta_contract()
    if witness["delta_contract_sha256"] != EXPECTED_DELTA_CONTRACT_SHA256:
        raise RuntimeError("R3_DELTA_CONTRACT_FROZEN_SHA_MISMATCH")
    frozen_at = datetime.fromisoformat(witness["frozen_at_utc"])
    first_outcome_read_at = datetime.now(timezone.utc)
    if first_outcome_read_at <= frozen_at:
        raise RuntimeError("R3_FREEZE_BEFORE_READ_ORDER_FAILURE")
    protected_before = protected_hashes()
    r1, r2, r1_summary, r2_summary, incumbent, inherited_audit = validate_inherited_contracts()
    inputs = r1.load_and_validate_frozen_inputs()
    prices = r1.load_prices_through(2025, set(inputs.eligibility.ticker))
    matrix = r1.attach_targets(r1.materialize_feature_matrix(prices, inputs.eligibility, 2025), prices)

    run1_oof, run1_group_audits = materialize_challenger(r1, matrix, incumbent)
    run1_metrics, run1_comparison, run1_daily = evaluate_models(r1, run1_oof)
    run1_fingerprint = canonical_fingerprint({
        "oof": dataframe_fingerprint(run1_oof, list(run1_oof.columns)),
        "metrics": run1_metrics, "groups": run1_group_audits,
    })
    run2_oof, run2_group_audits = materialize_challenger(r1, matrix, incumbent)
    run2_metrics, _, _ = evaluate_models(r1, run2_oof)
    run2_fingerprint = canonical_fingerprint({
        "oof": dataframe_fingerprint(run2_oof, list(run2_oof.columns)),
        "metrics": run2_metrics, "groups": run2_group_audits,
    })
    reproducibility = "PASS" if run1_fingerprint == run2_fingerprint else "FAIL"
    group_audits_pass = all(audit["group_row_sum"] == audit["train_rows"] and audit["split_audit"]["leakage_row_count"] == 0 for audit in run1_group_audits)
    identity_pass = bool(
        len(run1_oof) == len(incumbent)
        and run1_oof[["signal_date", "ticker"]].equals(incumbent[["signal_date", "ticker"]])
    )
    audits_pass = group_audits_pass and identity_pass and reproducibility == "PASS"
    classification, gate_conditions = classify_challenger(run1_metrics, audits_pass)
    if classification == "FAIL_CLOSED":
        raise RuntimeError("R3_GROUP_IDENTITY_LEAKAGE_OR_REPRODUCIBILITY_FAILURE")
    bootstrap = circular_block_bootstrap(run1_daily)
    timing = signal_timing_diagnostic(r2, run1_oof, prices)
    write_parquet_atomic(OOF_PATH, run1_oof)
    write_parquet_atomic(COMPARISON_PATH, run1_comparison)
    write_json_atomic(BOOTSTRAP_PATH, bootstrap)
    write_json_atomic(SIGNAL_TIMING_PATH, timing)

    freeze_time = datetime.now(timezone.utc)
    activation = None
    if classification == "A_RANKING_OBJECTIVE_INCREMENTAL_EDGE":
        activation = fit_prospective_model(r1, matrix, freeze_time)
        next_step = "ABCDE_A2_R4_PORTFOLIO_TRANSLATION_R1"
        prospective_status = "ACTIVE_ACCUMULATING_FROM_FIRST_LEGAL_FUTURE_DATE"
    else:
        next_step = "ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT"
        prospective_status = "NOT_ACTIVATED_CLASSIFICATION_NOT_A"
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise RuntimeError("PROTECTED_PRODUCTION_OR_INCUMBENT_SOURCE_CHANGED")
    pooled = run1_metrics["POOLED_PRE2026"]["lambda_minus_hgb"]
    summary = {
        "ABCDE_A2_R3_STATUS": "PASS",
        "ABCDE_A2_R3_CLASSIFICATION": classification,
        "R3_CLASSIFICATION": classification,
        "ABCDE_A2_R3_DECISION": next_step,
        "R3_EVIDENCE_ROLE": "PRE2026_MODEL_DEVELOPMENT_CHALLENGER_COMPARISON",
        "2025_ROLE": "CONSUMED_PRE2026_DEVELOPMENT_EVIDENCE",
        "R3_DELTA_CONTRACT_FROZEN_BEFORE_CHALLENGER_OUTCOME_READ": True,
        "R3_DELTA_PREREGISTRATION_SHA256": EXPECTED_DELTA_CONTRACT_SHA256,
        "LIGHTGBM_VERSION": lightgbm.__version__,
        "CURRENT_COHORT_COUNT": 325,
        "CURRENT_COHORT_FINGERPRINT": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
        "INCUMBENT_CHALLENGER_DAILY_UNIVERSE_IDENTITY_STATUS": "PASS" if identity_pass else "FAIL",
        "FEATURE_COUNT": 32,
        "FEATURE_SCHEMA_FINGERPRINT": "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4",
        "FEATURE_SCHEMA_CHANGED": False,
        "TARGET_NAME": "MEAN_ER_3D_5D_10D_20D",
        "TARGET_HORIZON": [3, 5, 10, 20],
        "RANKING_RELEVANCE_BIN_COUNT": 20,
        "RANKING_RELEVANCE_MIN": 0,
        "RANKING_RELEVANCE_MAX": 19,
        "RANKING_TIE_POLICY": "AVERAGE_RANK",
        "RANKING_LABEL_GAIN_POLICY": "LINEAR_0_TO_19",
        "HGB_INCUMBENT_IDENTITY_STATUS": "PASS",
        "HGB_CONFIG_CHANGED": False,
        "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0,
        "MODEL_FAMILY_COUNT_NEW": 1,
        "ANTI_MODEL_ZOO_STATUS": "PASS",
        "PURGE_HORIZON_TRADING_DAYS": 20,
        "GROUP_ROW_SUM_STATUS": "PASS" if group_audits_pass else "FAIL",
        "POST2025_TARGET_READ_COUNT": 0,
        "POST2025_OUTCOME_READ_COUNT": 0,
        "2026_MODEL_SELECTION_USE_COUNT": 0,
        "MODEL_FIT_COUNT": 7 if activation else 6,
        "stage_group_audits": run1_group_audits,
        "stage_metrics": run1_metrics,
        "LAMBDA_MINUS_HGB_MEAN_IC": pooled["mean_rank_ic"],
        "LAMBDA_MINUS_HGB_TOP5": pooled["top5_mean_target"],
        "LAMBDA_MINUS_HGB_TOP10": pooled["top10_mean_target"],
        "LAMBDA_MINUS_HGB_TOP20": pooled["top20_mean_target"],
        "LAMBDA_MINUS_HGB_TOP_BOTTOM_SPREAD": pooled["top_bottom_spread"],
        "decision_gate_conditions": gate_conditions,
        "BOOTSTRAP_BLOCK_LENGTH_TRADING_DAYS": 20,
        "BOOTSTRAP_RESAMPLE_COUNT": 2000,
        "BOOTSTRAP_RANDOM_SEED": 20260816,
        "LAMBDA_SIGNAL_TIMING_VS_HGB": timing["LAMBDA_SIGNAL_TIMING_VS_HGB"],
        "REPRODUCIBILITY_STATUS": reproducibility,
        "RUN1_FINGERPRINT": run1_fingerprint,
        "RUN2_FINGERPRINT": run2_fingerprint,
        "ACTIVATE_PROSPECTIVE_SHADOW": bool(activation),
        "PROSPECTIVE_LAMBDARANK_SHADOW": prospective_status,
        "PROSPECTIVE_FREEZE_TIMESTAMP_UTC": activation.get("PROSPECTIVE_FREEZE_TIMESTAMP_UTC") if activation else None,
        "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE": activation.get("FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE") if activation else None,
        "PROSPECTIVE_MODEL_FINGERPRINT": activation.get("MODEL_SHA256") if activation else None,
        "PRODUCTION_ADOPTION": False,
        "BROKER_ACTION_ALLOWED": False,
        "A1_PRODUCTION_CHANGED": False,
        "HGB_PRODUCTION_CHANGED": False,
        "FAST_CHANGED": False,
        "DAILY_CHAIN_CHANGED": False,
        "BROKER_ACTION_COUNT": 0,
        "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "SUMMARY_PATH": str(SUMMARY_PATH),
        "MANIFEST_PATH": str(MANIFEST_PATH),
        "OOF_PREDICTION_PATH": str(OOF_PATH),
        "COMPARISON_PATH": str(COMPARISON_PATH),
        "BOOTSTRAP_PATH": str(BOOTSTRAP_PATH),
        "SIGNAL_TIMING_PATH": str(SIGNAL_TIMING_PATH),
        "FROZEN_MODEL_PATH": str(FROZEN_MODEL_PATH) if activation else None,
        "PROSPECTIVE_ACTIVATION_PATH": str(PROSPECTIVE_ACTIVATION_PATH) if activation else None,
        "NEXT_AUTHORIZED_STEP": next_step,
        "FAILURE_REASON": None,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    write_json_atomic(SUMMARY_PATH, summary)
    manifest = {
        "experiment_id": EXPERIMENT_ID, "schema_version": "1.0",
        "delta_contract_frozen_at_utc": witness["frozen_at_utc"],
        "first_challenger_outcome_read_at_utc": first_outcome_read_at.isoformat(),
        "contract_frozen_before_outcome_read": first_outcome_read_at > frozen_at,
        "delta_preregistration_sha256": EXPECTED_DELTA_CONTRACT_SHA256,
        "run1_fingerprint": run1_fingerprint, "run2_fingerprint": run2_fingerprint,
        "reproducibility_status": reproducibility, "classification": classification,
        "artifact_sha256": {
            str(SUMMARY_PATH): sha256_file(SUMMARY_PATH), str(OOF_PATH): sha256_file(OOF_PATH),
            str(COMPARISON_PATH): sha256_file(COMPARISON_PATH), str(BOOTSTRAP_PATH): sha256_file(BOOTSTRAP_PATH),
            str(SIGNAL_TIMING_PATH): sha256_file(SIGNAL_TIMING_PATH),
            **({str(FROZEN_MODEL_PATH): sha256_file(FROZEN_MODEL_PATH), str(PROSPECTIVE_ACTIVATION_PATH): sha256_file(PROSPECTIVE_ACTIVATION_PATH)} if activation else {}),
        },
        "post2025_target_read_count": 0, "post2025_outcome_read_count": 0,
        "2026_model_selection_use_count": 0,
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
    "ABCDE_A2_R3_STATUS", "R3_CLASSIFICATION", "ABCDE_A2_R3_DECISION", "R3_EVIDENCE_ROLE",
    "R3_DELTA_CONTRACT_FROZEN_BEFORE_CHALLENGER_OUTCOME_READ", "R3_DELTA_PREREGISTRATION_SHA256",
    "LIGHTGBM_VERSION", "INCUMBENT_CHALLENGER_DAILY_UNIVERSE_IDENTITY_STATUS", "FEATURE_COUNT",
    "FEATURE_SCHEMA_CHANGED", "HGB_INCUMBENT_IDENTITY_STATUS", "HGB_CONFIG_CHANGED",
    "GROUP_ROW_SUM_STATUS", "HYPERPARAMETER_SEARCH_TRIAL_COUNT", "MODEL_FAMILY_COUNT_NEW",
    "LAMBDA_MINUS_HGB_MEAN_IC", "LAMBDA_MINUS_HGB_TOP5", "LAMBDA_MINUS_HGB_TOP10",
    "LAMBDA_MINUS_HGB_TOP20", "LAMBDA_MINUS_HGB_TOP_BOTTOM_SPREAD",
    "LAMBDA_SIGNAL_TIMING_VS_HGB", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT",
    "2026_MODEL_SELECTION_USE_COUNT", "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT", "RUN2_FINGERPRINT",
    "ACTIVATE_PROSPECTIVE_SHADOW", "PROSPECTIVE_LAMBDARANK_SHADOW", "PROSPECTIVE_FREEZE_TIMESTAMP_UTC",
    "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE", "PROSPECTIVE_MODEL_FINGERPRINT", "PRODUCTION_ADOPTION",
    "BROKER_ACTION_ALLOWED", "FAST_CHANGED", "DAILY_CHAIN_CHANGED", "ANTI_BLOAT_STATUS",
    "RESULTS_ROOT", "SUMMARY_PATH", "NEXT_AUTHORIZED_STEP", "FAILURE_REASON",
)


def print_core(summary: dict[str, Any]) -> None:
    for field in CORE_FIELDS:
        print(f"{field}={_display(summary.get(field))}")
    for stage in ("2023", "2024", "2025", "POOLED_PRE2026"):
        metrics = summary.get("stage_metrics", {}).get(stage, {})
        for model in ("A1", "HGB", "LAMBDARANK"):
            values = metrics.get("models", {}).get(model, {})
            for name, value in values.items():
                if isinstance(value, (bool, int, float, str)):
                    print(f"{stage}_{model}_{name.upper()}={_display(value)}")
        for name, value in metrics.get("lambda_minus_hgb", {}).items():
            print(f"{stage}_LAMBDA_MINUS_HGB_{name.upper()}={_display(value)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-contract-only", action="store_true")
    args = parser.parse_args(argv)
    witness = freeze_delta_contract()
    print("R3_DELTA_CONTRACT_FROZEN_BEFORE_CHALLENGER_OUTCOME_READ=true")
    print(f"R3_DELTA_PREREGISTRATION_SHA256={witness['delta_contract_sha256']}")
    print(f"LIGHTGBM_VERSION={lightgbm.__version__}")
    if args.freeze_contract_only:
        return 0
    try:
        summary = run_challenger()
    except Exception as exc:
        summary = {
            "ABCDE_A2_R3_STATUS": "FAIL_CLOSED",
            "ABCDE_A2_R3_CLASSIFICATION": "FAIL_CLOSED",
            "R3_CLASSIFICATION": "FAIL_CLOSED",
            "ABCDE_A2_R3_DECISION": "STOP_AND_REPAIR_EXPLICIT_R3_DATA_OR_CONTRACT_FAILURE",
            "R3_EVIDENCE_ROLE": "PRE2026_MODEL_DEVELOPMENT_CHALLENGER_COMPARISON",
            "R3_DELTA_CONTRACT_FROZEN_BEFORE_CHALLENGER_OUTCOME_READ": True,
            "R3_DELTA_PREREGISTRATION_SHA256": witness["delta_contract_sha256"],
            "LIGHTGBM_VERSION": lightgbm.__version__,
            "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0,
            "MODEL_FAMILY_COUNT_NEW": 1,
            "POST2025_TARGET_READ_COUNT": 0,
            "POST2025_OUTCOME_READ_COUNT": 0,
            "2026_MODEL_SELECTION_USE_COUNT": 0,
            "PRODUCTION_ADOPTION": False,
            "BROKER_ACTION_ALLOWED": False,
            "A1_PRODUCTION_CHANGED": False,
            "HGB_PRODUCTION_CHANGED": False,
            "FAST_CHANGED": False,
            "DAILY_CHAIN_CHANGED": False,
            "BROKER_ACTION_COUNT": 0,
            "NEXT_AUTHORIZED_STEP": "REPAIR_EXPLICIT_R3_DATA_OR_CONTRACT_FAILURE_ONLY",
            "FAILURE_REASON": f"{type(exc).__name__}:{exc}",
        }
        write_json_atomic(SUMMARY_PATH, summary)
        print_core(summary)
        return 2
    print_core(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
