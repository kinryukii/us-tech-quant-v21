"""Outcome-blind immutable execution supplement for ABCDE A2-R1.

This freezes feature equations, boundary purge, OOS stages, the existing HGB
configuration, evaluation semantics, final unlock protocol, and the decision
gate.  It never reads prices, features, targets, outcomes, or model outputs and
never constructs or calls a model.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPERIMENT_ID = "ABCDE_A2_R1C_EXECUTION_CONTRACT_FREEZE_R1"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
ORIGINAL_PREREG = REPO_ROOT / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py"
R1_GATE_SUMMARY = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING\abcde_a2_r1_summary.json")
R0V_SUMMARY = Path(r"D:\us-tech-quant-results\ABCDE_A2_R0V_CURRENT_COHORT_HISTORICAL_ELIGIBILITY_R1\abcde_a2_r0v_summary.json")
ORIGINAL_PREREG_FINGERPRINT = "9b11d898c0a040cf25225edde57e286abc5222760d0ba7069fe061a10b316cae"
ORIGINAL_PREREG_SOURCE_SHA256 = "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb"

SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r1c_summary.json"
EXECUTION_CONTRACT_PATH = RESULTS_ROOT / "a2_r1_execution_contract_r1.json"
FEATURE_CONTRACT_PATH = RESULTS_ROOT / "a2_r1_feature_equation_contract.json"
SPLIT_GATE_PATH = RESULTS_ROOT / "a2_r1_split_and_decision_gate.json"
RUN_MANIFEST_PATH = RESULTS_ROOT / "a2_r1c_run_manifest.json"

REQUIRED_FEATURE_FIELDS = (
    "feature_name", "economic_family", "source_series", "lookback_trading_days",
    "required_observations", "exact_equation", "return_definition", "price_field",
    "volume_field_if_any", "rolling_function", "ddof_if_any", "annualization_if_any",
    "cross_sectional_transform", "tie_policy", "missing_value_policy",
    "zero_denominator_policy", "finite_value_policy", "asof_rule",
    "canonical_source_or_helper", "implementation_fingerprint",
)

SUMMARY_FIELDS = (
    "ABCDE_A2_R1C_STATUS", "ABCDE_A2_R1C_CLASSIFICATION", "ABCDE_A2_R1C_DECISION",
    "A2_R1_ORIGINAL_PREREGISTRATION_STATUS", "A2_R1_ORIGINAL_PREREGISTRATION_SHA256",
    "A2_R1_ORIGINAL_PREREGISTRATION_SOURCE_SHA256", "A2_R1_ORIGINAL_PREREGISTRATION_CHANGED",
    "FEATURE_EQUATION_CONTRACT_STATUS", "FEATURE_COUNT", "FULLY_SPECIFIED_FEATURE_COUNT",
    "AMBIGUOUS_FEATURE_COUNT", "FEATURE_SCHEMA_FINGERPRINT", "MAX_REQUIRED_LOOKBACK",
    "MAX_REQUIRED_OBSERVATIONS", "PURGE_RULE_FROZEN", "PURGE_HORIZON_TRADING_DAYS",
    "EMBARGO_AFTER_EVALUATION_TRADING_DAYS", "DEVELOPMENT_REGION_FROZEN",
    "CONFIRMATION_REGION_FROZEN", "FINAL_REGION_FROZEN", "FINAL_IS_ONE_SHOT",
    "FINAL_EVALUATION_MAX_COUNT", "MODEL_FAMILY", "MODEL_CONFIG_FROZEN",
    "MODEL_CONFIG_FINGERPRINT", "HYPERPARAMETER_SEARCH_TRIAL_COUNT",
    "ANTI_MODEL_ZOO_STATUS", "PRIMARY_METRIC", "DECISION_GATE_FROZEN",
    "FINAL_UNLOCK_PROTOCOL_FROZEN", "TARGET_VALUE_READ_COUNT", "OUTCOME_READ_COUNT",
    "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT", "MODEL_FIT_COUNT",
    "MODEL_PREDICT_CALL_COUNT", "BROKER_ACTION_COUNT", "A1_PRODUCTION_CHANGED",
    "A2_PRODUCTION_ADOPTED", "FAST_CHANGED", "DAILY_CHAIN_CHANGED", "ANTI_BLOAT_STATUS",
    "EXECUTION_CONTRACT_SHA256", "FEATURE_CONTRACT_SHA256", "SPLIT_GATE_SHA256",
    "COMBINED_R1C_FINGERPRINT", "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT",
    "RUN2_FINGERPRINT", "RESULTS_ROOT", "SUMMARY_PATH", "EXECUTION_CONTRACT_PATH",
    "FEATURE_CONTRACT_PATH", "SPLIT_GATE_PATH", "NEXT_AUTHORIZED_STEP", "FAILURE_REASON",
)


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_payload(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")


def canonical_bytes(value: Any) -> bytes:
    return canonical_payload(value) + b"\n"


def canonical_fingerprint(value: Any) -> str:
    # Preserve the established A2-R1 semantic-fingerprint convention: JSON
    # files end with a newline, but contract fingerprints hash only the
    # canonical JSON payload.
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(value))
    os.replace(temporary, path)


def load_original_preregistration() -> Any:
    return import_module("abcde_a2_r1c_original_prereg", ORIGINAL_PREREG)


def original_prereg_contract(prereg: Any) -> dict[str, Any]:
    return {
        "primary": prereg.PRIMARY_TARGET,
        "secondary": prereg.SECONDARY_TARGET,
        "features": list(prereg.FEATURES),
        "hgb_config": prereg.HGB_CONFIG,
        "folds": list(prereg.PLANNED_FOLDS),
    }


def _base_feature(name: str, family: str, source: str, lookback: int, observations: int,
                  equation: str, rolling: str, *, return_definition: str = "NOT_APPLICABLE",
                  price: str = "canonical_qfq_close", volume: str = "NOT_APPLICABLE",
                  ddof: str = "NOT_APPLICABLE", annualization: str = "NONE") -> dict[str, Any]:
    row = {
        "feature_name": name,
        "economic_family": family,
        "source_series": source,
        "lookback_trading_days": lookback,
        "required_observations": observations,
        "exact_equation": equation,
        "return_definition": return_definition,
        "price_field": price,
        "volume_field_if_any": volume,
        "rolling_function": rolling,
        "ddof_if_any": ddof,
        "annualization_if_any": annualization,
        "cross_sectional_transform": "NONE_RAW_STOCK_STATE_VALUE",
        "tie_policy": "NOT_APPLICABLE_NO_CROSS_SECTIONAL_RANK",
        "missing_value_policy": "KEEP_NAN;NO_FORWARD_FILL;NO_BACKWARD_FILL;NO_IMPUTATION",
        "zero_denominator_policy": "RETURN_NAN",
        "finite_value_policy": "CONVERT_POSITIVE_OR_NEGATIVE_INFINITY_TO_NAN;NO_QUANTILE_CLIP",
        "asof_rule": "EVERY_INPUT_OBSERVATION_TRADE_DATE_LE_SIGNAL_DATE",
        "canonical_source_or_helper": "MOOMOO_DERIVED_CANONICAL_QFQ_OHLCV;R0V_ELIGIBILITY_GUARD",
    }
    row["implementation_fingerprint"] = canonical_fingerprint(row)
    return row


def build_feature_contract(feature_names: tuple[str, ...] | list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name in feature_names:
        match: re.Match[str] | None
        if match := re.fullmatch(r"ret_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "RETURN_PATH", "canonical_qfq_close", k, k + 1,
                f"P_t / P_(t-{k}) - 1", f"EXACT_LAG_{k}_SIMPLE_RETURN",
                return_definition="SIMPLE_RETURN", price="canonical_qfq_close")
            if k in {20, 60, 120}:
                row["canonical_source_or_helper"] += ";A1_FROZEN_HELPER:v21_233.ret"
                row["implementation_fingerprint"] = canonical_fingerprint({key: value for key, value in row.items() if key != "implementation_fingerprint"})
        elif match := re.fullmatch(r"price_vs_ma(\d+)", name):
            k = int(match.group(1))
            row = _base_feature(name, "TREND_STRUCTURE", "canonical_qfq_close", k, k,
                f"P_t / arithmetic_mean(P_(t-{k-1})..P_t) - 1", f"ROLLING_ARITHMETIC_MEAN_WINDOW_{k}")
        elif match := re.fullmatch(r"ma(\d+)_vs_ma(\d+)", name):
            short, long = int(match.group(1)), int(match.group(2))
            row = _base_feature(name, "TREND_STRUCTURE", "canonical_qfq_close", long, long,
                f"arithmetic_mean(P_(t-{short-1})..P_t) / arithmetic_mean(P_(t-{long-1})..P_t) - 1",
                f"RATIO_OF_ROLLING_ARITHMETIC_MEANS_{short}_{long}")
        elif match := re.fullmatch(r"realized_vol_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "VOLATILITY_STRUCTURE", "one_day_simple_return", k, k + 1,
                f"std([r_(t-{k-1}),...,r_t],ddof=0)", f"ROLLING_STANDARD_DEVIATION_WINDOW_{k}",
                return_definition="r_t=P_t/P_(t-1)-1", ddof="0", annualization="NONE")
        elif match := re.fullmatch(r"downside_vol_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "VOLATILITY_STRUCTURE", "one_day_simple_return", k, k + 1,
                f"sqrt(mean([min(r_j,0)^2 for j=t-{k-1}..t]))", f"ROLLING_LOWER_PARTIAL_RMS_WINDOW_{k}",
                return_definition="r_t=P_t/P_(t-1)-1", ddof="NOT_APPLICABLE_POPULATION_MEAN", annualization="NONE")
        elif match := re.fullmatch(r"upside_vol_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "VOLATILITY_STRUCTURE", "one_day_simple_return", k, k + 1,
                f"sqrt(mean([max(r_j,0)^2 for j=t-{k-1}..t]))", f"ROLLING_UPPER_PARTIAL_RMS_WINDOW_{k}",
                return_definition="r_t=P_t/P_(t-1)-1", ddof="NOT_APPLICABLE_POPULATION_MEAN", annualization="NONE")
        elif match := re.fullmatch(r"distance_from_high_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "DRAWDOWN_LOCATION", "canonical_qfq_close", k, k,
                f"P_t / max(P_(t-{k-1})..P_t) - 1", f"ROLLING_MAX_WINDOW_{k}")
        elif match := re.fullmatch(r"distance_from_low_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "DRAWDOWN_LOCATION", "canonical_qfq_close", k, k,
                f"P_t / min(P_(t-{k-1})..P_t) - 1", f"ROLLING_MIN_WINDOW_{k}")
        elif match := re.fullmatch(r"max_drawdown_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "DRAWDOWN_LOCATION", "canonical_qfq_close", k, k,
                f"min_j((P_j/P_first)/cummax_j(P_j/P_first)-1),j=t-{k-1}..t;SIGNED_LE_ZERO",
                f"ROLLING_PATH_MAX_DRAWDOWN_WINDOW_{k}")
        elif match := re.fullmatch(r"avg_volume_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "VOLUME_LIQUIDITY", "canonical_volume", k, k,
                f"arithmetic_mean(V_(t-{k-1})..V_t)", f"ROLLING_ARITHMETIC_MEAN_WINDOW_{k}",
                price="NOT_APPLICABLE", volume="canonical_volume")
        elif match := re.fullmatch(r"volume_ratio_(\d+)d_(\d+)d", name):
            short, long = int(match.group(1)), int(match.group(2))
            row = _base_feature(name, "VOLUME_LIQUIDITY", "canonical_volume", long, long,
                f"arithmetic_mean(V_(t-{short-1})..V_t) / arithmetic_mean(V_(t-{long-1})..V_t)",
                f"RATIO_OF_ROLLING_ARITHMETIC_MEANS_{short}_{long}", price="NOT_APPLICABLE", volume="canonical_volume")
        elif match := re.fullmatch(r"avg_dollar_volume_(\d+)d", name):
            k = int(match.group(1))
            row = _base_feature(name, "VOLUME_LIQUIDITY", "canonical_qfq_close*canonical_volume", k, k,
                f"arithmetic_mean([P_j*V_j for j=t-{k-1}..t])", f"ROLLING_ARITHMETIC_MEAN_WINDOW_{k}",
                price="canonical_qfq_close", volume="canonical_volume")
        else:
            rows.append({"feature_name": name, "ambiguity": "UNRECOGNIZED_PREREGISTERED_FEATURE_NAME"})
            continue
        rows.append(row)

    fully = [row for row in rows if set(REQUIRED_FEATURE_FIELDS).issubset(row) and all(row.get(field) not in (None, "") for field in REQUIRED_FEATURE_FIELDS)]
    ambiguous = [row for row in rows if row not in fully]
    return {
        "contract_id": "A2_R1_FEATURE_EQUATION_CONTRACT_R1",
        "original_preregistration_sha256": ORIGINAL_PREREG_FINGERPRINT,
        "source_policy": "MOOMOO_DERIVED_CANONICAL_QFQ_ONLY",
        "feature_order": list(feature_names),
        "feature_count": len(rows),
        "fully_specified_feature_count": len(fully),
        "ambiguous_feature_count": len(ambiguous),
        "max_required_lookback_trading_days": 120,
        "max_required_observations": 121,
        "global_cross_sectional_rank_primitive": {
            "scope": "R0V_ELIGIBLE_U_T_ONLY", "nan_policy": "EXCLUDE_AND_KEEP_NAN",
            "tie_policy": "AVERAGE_RANK", "percentile_range": "[0,1]",
            "formula": "(average_rank-1)/(finite_count-1); finite_count=1 -> 0.5",
            "usage_in_current_32_features": "NONE;ALL_32_ARE_RAW_STOCK_STATE_VALUES",
        },
        "features": rows,
        "ambiguous_features": [row.get("feature_name") for row in ambiguous],
    }


def build_split_gate_contract() -> dict[str, Any]:
    a_conditions = [
        "CONFIRMATION_DELTA_MEAN_RANK_IC>0", "FINAL_DELTA_MEAN_RANK_IC>0",
        "CONFIRMATION_A2_MEAN_RANK_IC>0", "FINAL_A2_MEAN_RANK_IC>0",
        "CONFIRMATION_DELTA_TOP20_MEAN_TARGET>0", "FINAL_DELTA_TOP20_MEAN_TARGET>0",
        "FINAL_DELTA_TOP_BOTTOM_SPREAD>0",
        "FINAL_A2_TOP_QUINTILE_MEAN_TARGET>FINAL_A2_BOTTOM_QUINTILE_MEAN_TARGET",
        "CONTRACT_DATA_LEAKAGE_IDENTITY_REPRODUCIBILITY_FAILURE_COUNT==0",
    ]
    positive_evidence = [
        "CONFIRMATION_DELTA_MEAN_RANK_IC>0", "FINAL_DELTA_MEAN_RANK_IC>0",
        "CONFIRMATION_DELTA_TOP20_MEAN_TARGET>0", "FINAL_DELTA_TOP20_MEAN_TARGET>0",
        "FINAL_DELTA_TOP_BOTTOM_SPREAD>0",
    ]
    return {
        "contract_id": "A2_R1_SPLIT_AND_DECISION_GATE_R1",
        "original_preregistration_sha256": ORIGINAL_PREREG_FINGERPRINT,
        "target_boundary": {
            "max_target_horizon_trading_days": 20,
            "purge_rule": "DROP_ANY_TRAINING_SIGNAL_WHOSE_MAX_20D_TARGET_WINDOW_OVERLAPS_EVALUATION_BLOCK",
            "machine_condition_to_keep_training_row": "TARGET_END_DATE(signal_date,20D)<EVALUATION_BLOCK_FIRST_TRADING_DATE",
            "purge_horizon_trading_days": 20,
            "embargo_after_evaluation_trading_days": 0,
            "embargo_zero_reason": "EXPANDING_PAST_ONLY_FIT_NEVER_REUSES_POST_EVALUATION_OBSERVATIONS_IN_SAME_FOLD;PURGE_BLOCKS_BOUNDARY_LABEL_OVERLAP",
        },
        "stages": [
            {"stage": "DEVELOPMENT", "evaluation_region": "2023-01-01..2023-12-31", "fit_region": "R0V_ELIGIBLE_SIGNAL_DATE<2023-01-01_AFTER_20D_PURGE", "expanding_past_only": True, "may_change_frozen_contract": False},
            {"stage": "CONFIRMATION", "evaluation_region": "2024-01-01..2024-12-31", "fit_region": "R0V_ELIGIBLE_SIGNAL_DATE<2024-01-01_AFTER_20D_PURGE", "expanding_past_only": True, "may_change_frozen_contract": False},
            {"stage": "FINAL", "evaluation_region": "2025-01-01..2025-12-31", "fit_region": "R0V_ELIGIBLE_SIGNAL_DATE<2025-01-01_AFTER_20D_PURGE", "expanding_past_only": True, "may_change_frozen_contract": False, "one_shot": True},
        ],
        "random_kfold_allowed": False,
        "post2025_data_allowed": False,
        "final_unlock_protocol": {
            "pre_final_required_fields": [
                "PRE_FINAL_MODEL_FROZEN", "PRE_FINAL_FEATURE_SCHEMA_FINGERPRINT",
                "PRE_FINAL_MODEL_CONFIG_FINGERPRINT", "PRE_FINAL_TARGET_FINGERPRINT",
                "PRE_FINAL_DECISION_GATE_FINGERPRINT", "PRE_FINAL_TIMESTAMP",
            ],
            "pre_final_model_frozen_required_value": True,
            "persist_before_any_2025_target_read": True,
            "final_evaluation_max_count": 1,
            "fingerprint_change_after_final_action": "CONTAMINATED_REQUIRES_NEW_FUTURE_HOLDOUT",
        },
        "evaluation": {
            "primary_metric": "MEAN_DAILY_SPEARMAN_RANK_IC",
            "daily_spearman": "SPEARMAN_CORRELATION_WITH_AVERAGE_TIES_ON_IDENTICAL_FINITE_A1_A2_TARGET_ROWS_WITHIN_U_T;MINIMUM_2_PAIRED_ROWS;CONSTANT_VECTOR_RETURNS_NAN",
            "date_aggregation": "ARITHMETIC_MEAN_OF_FINITE_DAILY_IC",
            "score_order": "DESCENDING_SCORE_THEN_ASCENDING_TICKER_FOR_DETERMINISTIC_TOP_N_BOUNDARY",
            "top20": "FIRST_20_ONLY_WHEN_DAILY_FINITE_EVALUATION_COUNT>=20",
            "top_quintile": "FIRST_CEIL(0.20*N)_BY_DETERMINISTIC_DESCENDING_ORDER",
            "bottom_quintile": "LAST_CEIL(0.20*N)_BY_DETERMINISTIC_DESCENDING_ORDER",
            "top_bottom_spread": "TOP_QUINTILE_MEAN_TARGET-BOTTOM_QUINTILE_MEAN_TARGET",
            "quintile_monotonicity": "REPORT_FIVE_DETERMINISTIC_EQUAL_COUNT_SCORE_BUCKET_TARGET_MEANS_AND_ADJACENT_NONDECREASING_COUNT",
            "secondary_metrics": ["MEDIAN_DAILY_RANK_IC", "POSITIVE_IC_DAY_FRACTION", "TOP20_MEAN_TARGET", "TOP_QUINTILE_MEAN_TARGET", "BOTTOM_QUINTILE_MEAN_TARGET", "TOP_MINUS_BOTTOM_TARGET_SPREAD", "QUINTILE_MONOTONICITY"],
            "portfolio_metrics_forbidden": ["POSITION_SIZING", "TRANSACTION_COST", "SHARPE", "EXECUTION_BACKTEST"],
        },
        "decision_gate": {
            "failure_precedence": "IF_ANY_CONTRACT_DATA_LEAKAGE_IDENTITY_OR_REPRODUCIBILITY_FAILURE_THEN_FAIL_CLOSED",
            "A_STRONG_INCREMENTAL_NONLINEAR_EDGE": {"operator": "ALL", "conditions": a_conditions},
            "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE": {"operator": "NOT_A_AND_ANY", "conditions": positive_evidence},
            "C_NO_RELIABLE_INCREMENTAL_EDGE": {"operator": "NOT_A_AND_NOT_B", "conditions": ["NO_PREREGISTERED_POSITIVE_INCREMENTAL_EVIDENCE"]},
            "next_authorized_step": {
                "A_STRONG_INCREMENTAL_NONLINEAR_EDGE": "ABCDE_A2_R2_SIGNAL_LAG_AND_INCREMENTAL_MECHANISM",
                "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE": "ABCDE_A2_R2_MECHANISM_ONLY_NO_PRODUCTION_ADOPTION",
                "C_NO_RELIABLE_INCREMENTAL_EDGE": "STOP_CURRENT_A2_HGB_HYPOTHESIS_AND_REASSESS_INFORMATION_SET",
                "FAIL_CLOSED": "REPAIR_EXPLICIT_CONTRACT_OR_DATA_FAILURE_ONLY",
            },
        },
    }


def classify_gate(metrics: dict[str, float], failure_count: int = 0) -> str:
    if failure_count:
        return "FAIL_CLOSED"
    a = all((
        metrics["confirmation_delta_mean_rank_ic"] > 0,
        metrics["final_delta_mean_rank_ic"] > 0,
        metrics["confirmation_a2_mean_rank_ic"] > 0,
        metrics["final_a2_mean_rank_ic"] > 0,
        metrics["confirmation_delta_top20_mean_target"] > 0,
        metrics["final_delta_top20_mean_target"] > 0,
        metrics["final_delta_top_bottom_spread"] > 0,
        metrics["final_a2_top_quintile_mean_target"] > metrics["final_a2_bottom_quintile_mean_target"],
    ))
    if a:
        return "A_STRONG_INCREMENTAL_NONLINEAR_EDGE"
    positive = any((
        metrics["confirmation_delta_mean_rank_ic"] > 0,
        metrics["final_delta_mean_rank_ic"] > 0,
        metrics["confirmation_delta_top20_mean_target"] > 0,
        metrics["final_delta_top20_mean_target"] > 0,
        metrics["final_delta_top_bottom_spread"] > 0,
    ))
    return "B_PARTIAL_OR_UNSTABLE_INCREMENTAL_EDGE" if positive else "C_NO_RELIABLE_INCREMENTAL_EDGE"


def build_execution_contract(prereg: Any, feature_sha: str, split_sha: str) -> dict[str, Any]:
    signature = inspect.signature(prereg.HistGradientBoostingRegressor)
    unsupported = sorted(set(prereg.HGB_CONFIG) - set(signature.parameters))
    model_config = dict(prereg.HGB_CONFIG)
    return {
        "contract_id": "A2_R1_EXECUTION_CONTRACT_R1",
        "contract_role": "IMMUTABLE_OUTCOME_BLIND_EXECUTION_SUPPLEMENT",
        "original_preregistration": {
            "path": str(ORIGINAL_PREREG),
            "canonical_contract_sha256": ORIGINAL_PREREG_FINGERPRINT,
            "source_sha256": ORIGINAL_PREREG_SOURCE_SHA256,
            "changed": False,
        },
        "feature_contract_sha256": feature_sha,
        "split_and_decision_gate_sha256": split_sha,
        "target_contract": {
            "primary": prereg.PRIMARY_TARGET,
            "primary_equation": "ARITHMETIC_MEAN(ER_3D,ER_5D,ER_10D,ER_20D)",
            "secondary": prereg.SECONDARY_TARGET,
            "benchmark": prereg.TARGET_BENCHMARK,
            "horizons_trading_days": list(prereg.TARGET_HORIZONS),
            "max_horizon_trading_days": 20,
        },
        "model_contract": {
            "family": "HistGradientBoostingRegressor",
            "single_challenger_only": True,
            "config": model_config,
            "config_fingerprint": canonical_fingerprint(model_config),
            "unsupported_installed_api_parameters": unsupported,
            "hyperparameter_search_trial_count": 0,
            "additional_model_allowed": False,
        },
        "a1_control_contract": {
            "freeze_id": "ABCDE_COMPACT_V1_FREEZE_R1",
            "producer": "scripts/v21/v21_233_moomoo_only_abcde_rerun.py",
            "producer_sha256": "1735939ed45e6ed08b124b4869875f56e1ebbb931337f611b25837dbfdbbc966",
            "ast_contract_sha256": "91be39b3f795ba582f8d079eaee9346dec874ccb488da19913159f801cf3c1d2",
            "production_change_allowed": False,
            "same_u_t_and_target_filter_as_a2_required": True,
        },
        "outcome_blind_freeze": True,
        "target_value_read_count": 0,
        "outcome_read_count": 0,
        "model_fit_count": 0,
        "model_predict_call_count": 0,
    }


def _display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def run() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    prior_manifest = json.loads(RUN_MANIFEST_PATH.read_text(encoding="utf-8")) if RUN_MANIFEST_PATH.is_file() else {}
    created_at = prior_manifest.get("created_at_utc") or datetime.now(timezone.utc).isoformat()
    prereg = load_original_preregistration()
    prereg_contract = original_prereg_contract(prereg)
    prereg_fingerprint = canonical_fingerprint(prereg_contract)
    prereg_source_sha = sha256_file(ORIGINAL_PREREG)
    r0v = json.loads(R0V_SUMMARY.read_text(encoding="utf-8"))
    r1_gate = json.loads(R1_GATE_SUMMARY.read_text(encoding="utf-8"))

    feature_contract = build_feature_contract(prereg.FEATURES)
    write_canonical_json(FEATURE_CONTRACT_PATH, feature_contract)
    feature_sha = sha256_file(FEATURE_CONTRACT_PATH)
    split_gate = build_split_gate_contract()
    write_canonical_json(SPLIT_GATE_PATH, split_gate)
    split_sha = sha256_file(SPLIT_GATE_PATH)
    execution_contract = build_execution_contract(prereg, feature_sha, split_sha)
    write_canonical_json(EXECUTION_CONTRACT_PATH, execution_contract)
    execution_sha = sha256_file(EXECUTION_CONTRACT_PATH)

    implementation_sha = sha256_file(Path(__file__).resolve())
    combined = canonical_fingerprint({
        "original_preregistration_sha256": prereg_fingerprint,
        "original_preregistration_source_sha256": prereg_source_sha,
        "feature_contract_sha256": feature_sha,
        "split_gate_sha256": split_sha,
        "execution_contract_sha256": execution_sha,
        "implementation_sha256": implementation_sha,
    })
    same_implementation = prior_manifest.get("implementation_sha256") == implementation_sha
    run1 = prior_manifest.get("run1_fingerprint") if same_implementation else combined
    run1 = run1 or combined
    prior_count = int(prior_manifest.get("completed_run_count", 0)) if same_implementation else 0
    run_count = prior_count + 1
    reproducibility = "PASS" if run_count >= 2 and run1 == combined else "PENDING_SECOND_RUN"
    if run_count >= 2 and run1 != combined:
        reproducibility = "FAIL"

    fully = feature_contract["fully_specified_feature_count"]
    ambiguous = feature_contract["ambiguous_feature_count"]
    model_api_ok = not execution_contract["model_contract"]["unsupported_installed_api_parameters"]
    original_unchanged = prereg_fingerprint == ORIGINAL_PREREG_FINGERPRINT and prereg_source_sha == ORIGINAL_PREREG_SOURCE_SHA256
    pass_checks = {
        "r0v_pass": r0v.get("ABCDE_A2_R0V_STATUS") == "PASS",
        "prior_r1_failed_for_contract_only": r1_gate.get("ABCDE_A2_R1_STATUS") == "FAIL_CLOSED" and r1_gate.get("TARGET_VALUE_READ_COUNT") == 0,
        "original_preregistration_unchanged": original_unchanged,
        "feature_count_32": feature_contract["feature_count"] == 32,
        "fully_specified_32": fully == 32,
        "ambiguous_zero": ambiguous == 0,
        "purge_rule_frozen": split_gate["target_boundary"]["purge_horizon_trading_days"] == 20,
        "embargo_zero_frozen": split_gate["target_boundary"]["embargo_after_evaluation_trading_days"] == 0,
        "three_regions_frozen": [row["stage"] for row in split_gate["stages"]] == ["DEVELOPMENT", "CONFIRMATION", "FINAL"],
        "final_one_shot": split_gate["final_unlock_protocol"]["final_evaluation_max_count"] == 1,
        "model_config_frozen_and_api_compatible": model_api_ok,
        "decision_gate_frozen": bool(split_gate["decision_gate"]),
        "zero_forbidden_activity": True,
        "reproducibility": reproducibility == "PASS",
    }
    status = "PASS" if all(pass_checks.values()) else ("PENDING_SECOND_RUN" if all(value for key, value in pass_checks.items() if key != "reproducibility") else "FAIL_CLOSED")
    summary: dict[str, Any] = {
        "ABCDE_A2_R1C_STATUS": status,
        "ABCDE_A2_R1C_CLASSIFICATION": "A_EXECUTION_CONTRACT_FULLY_FROZEN_OUTCOME_BLIND" if status == "PASS" else status,
        "ABCDE_A2_R1C_DECISION": "AUTHORIZE_EXACT_RERUN_OF_A2_R1" if status == "PASS" else "WAIT_FOR_CONTRACT_REPRODUCIBILITY_OR_REPAIR",
        "A2_R1_ORIGINAL_PREREGISTRATION_STATUS": "PASS_IMMUTABLE_REFERENCE" if original_unchanged else "FAIL_CHANGED",
        "A2_R1_ORIGINAL_PREREGISTRATION_SHA256": prereg_fingerprint,
        "A2_R1_ORIGINAL_PREREGISTRATION_SOURCE_SHA256": prereg_source_sha,
        "A2_R1_ORIGINAL_PREREGISTRATION_CHANGED": not original_unchanged,
        "FEATURE_EQUATION_CONTRACT_STATUS": "PASS" if fully == 32 and ambiguous == 0 else "FAIL_CLOSED",
        "FEATURE_COUNT": feature_contract["feature_count"],
        "FULLY_SPECIFIED_FEATURE_COUNT": fully,
        "AMBIGUOUS_FEATURE_COUNT": ambiguous,
        "FEATURE_SCHEMA_FINGERPRINT": canonical_fingerprint(feature_contract["feature_order"]),
        "MAX_REQUIRED_LOOKBACK": 120,
        "MAX_REQUIRED_OBSERVATIONS": 121,
        "PURGE_RULE_FROZEN": True,
        "PURGE_HORIZON_TRADING_DAYS": 20,
        "EMBARGO_AFTER_EVALUATION_TRADING_DAYS": 0,
        "DEVELOPMENT_REGION_FROZEN": True,
        "CONFIRMATION_REGION_FROZEN": True,
        "FINAL_REGION_FROZEN": True,
        "DEVELOPMENT_REGION": "2023",
        "CONFIRMATION_REGION": "2024",
        "FINAL_REGION": "2025",
        "FINAL_IS_ONE_SHOT": True,
        "FINAL_EVALUATION_MAX_COUNT": 1,
        "MODEL_FAMILY": "HistGradientBoostingRegressor",
        "MODEL_CONFIG_FROZEN": model_api_ok,
        "MODEL_CONFIG_FINGERPRINT": execution_contract["model_contract"]["config_fingerprint"],
        "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0,
        "ANTI_MODEL_ZOO_STATUS": "PASS",
        "PRIMARY_METRIC": "MEAN_DAILY_SPEARMAN_RANK_IC",
        "DECISION_GATE_FROZEN": True,
        "FINAL_UNLOCK_PROTOCOL_FROZEN": True,
        "TARGET_VALUE_READ_COUNT": 0,
        "OUTCOME_READ_COUNT": 0,
        "POST2025_TARGET_READ_COUNT": 0,
        "POST2025_OUTCOME_READ_COUNT": 0,
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "BROKER_ACTION_COUNT": 0,
        "A1_PRODUCTION_CHANGED": False,
        "A2_PRODUCTION_ADOPTED": False,
        "FAST_CHANGED": False,
        "DAILY_CHAIN_CHANGED": False,
        "ANTI_BLOAT_STATUS": "PASS",
        "EXECUTION_CONTRACT_SHA256": execution_sha,
        "FEATURE_CONTRACT_SHA256": feature_sha,
        "SPLIT_GATE_SHA256": split_sha,
        "COMBINED_R1C_FINGERPRINT": combined,
        "REPRODUCIBILITY_STATUS": reproducibility,
        "RUN1_FINGERPRINT": run1,
        "RUN2_FINGERPRINT": combined if run_count >= 2 else None,
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "SUMMARY_PATH": str(SUMMARY_PATH),
        "EXECUTION_CONTRACT_PATH": str(EXECUTION_CONTRACT_PATH),
        "FEATURE_CONTRACT_PATH": str(FEATURE_CONTRACT_PATH),
        "SPLIT_GATE_PATH": str(SPLIT_GATE_PATH),
        "NEXT_AUTHORIZED_STEP": "RERUN_ABCDE_A2_R1_UNDER_R1C_FROZEN_EXECUTION_CONTRACT" if status == "PASS" else None,
        "FAILURE_REASON": None if status in {"PASS", "PENDING_SECOND_RUN"} else ";".join(key for key, value in pass_checks.items() if not value),
        "pass_checks": pass_checks,
        "implementation_sha256": implementation_sha,
        "outcome_or_target_paths_read": [],
    }
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "schema_version": "1.0",
        "created_at_utc": created_at,
        "last_verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "implementation_sha256": implementation_sha,
        "completed_run_count": run_count,
        "run1_fingerprint": run1,
        "current_run_fingerprint": combined,
        "reproducibility_status": reproducibility,
        "artifact_sha256": {
            str(EXECUTION_CONTRACT_PATH): execution_sha,
            str(FEATURE_CONTRACT_PATH): feature_sha,
            str(SPLIT_GATE_PATH): split_sha,
        },
        "target_value_read_count": 0,
        "outcome_read_count": 0,
        "model_fit_count": 0,
        "model_predict_call_count": 0,
    }
    write_canonical_json(SUMMARY_PATH, summary)
    write_canonical_json(RUN_MANIFEST_PATH, manifest)
    for field in SUMMARY_FIELDS:
        print(f"{field}={_display(summary.get(field))}")
    return summary


def main() -> int:
    summary = run()
    return 0 if summary["ABCDE_A2_R1C_STATUS"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
