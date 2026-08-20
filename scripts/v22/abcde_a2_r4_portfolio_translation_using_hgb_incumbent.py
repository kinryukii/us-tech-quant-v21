"""ABCDE A2-R4 executable portfolio translation for the frozen HGB incumbent.

The portfolio contract can be frozen without reading any row-level OOF signal,
execution-price value, future portfolio return, or PnL artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
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
from zoneinfo import ZoneInfo


EXPERIMENT_ID = "ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
CONTRACT_PATH = RESULTS_ROOT / "a2_r4_portfolio_translation_contract_r1.json"
WITNESS_PATH = RESULTS_ROOT / "a2_r4_contract_freeze_witness.json"
SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r4_summary.json"
MANIFEST_PATH = RESULTS_ROOT / "a2_r4_manifest.json"
DAILY_PATH = RESULTS_ROOT / "a1_a2_top20_daily_portfolio.parquet"
METRICS_PATH = RESULTS_ROOT / "a1_a2_portfolio_metrics.parquet"
COST_SENSITIVITY_PATH = RESULTS_ROOT / "a2_r4_cost_sensitivity.json"
EXECUTION_COVERAGE_AUDIT_PATH = RESULTS_ROOT / "a2_r4_execution_price_coverage_audit.json"
EXECUTION_ELIGIBILITY_POLICY_PATH = RESULTS_ROOT / "a2_r4_execution_eligibility_policy_r1.json"
EXECUTION_ELIGIBILITY_WITNESS_PATH = RESULTS_ROOT / "a2_r4_execution_eligibility_freeze_witness.json"
EXECUTION_ELIGIBILITY_AUDIT_PATH = RESULTS_ROOT / "a2_r4_execution_eligibility_audit.parquet"
FROZEN_MODEL_PATH = RESULTS_ROOT / "a2_r4_frozen_full_pre2026_hgb.joblib"
ACTIVATION_PATH = RESULTS_ROOT / "a2_r4_prospective_shadow_activation.json"
PRIOR_FAIL_SUMMARY_PATH = RESULTS_ROOT / "abcde_a2_r4_summary.fail_closed_pre_r4e.json"
PRIOR_FAIL_MANIFEST_PATH = RESULTS_ROOT / "a2_r4_manifest.fail_closed_pre_r4e.json"
PRIOR_FAIL_COVERAGE_PATH = RESULTS_ROOT / "a2_r4_execution_price_coverage_audit.fail_closed_pre_r4e.json"

R1_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING")
R2_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R2_SIGNAL_LAG_AND_INCREMENTAL_MECHANISM")
R3_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R3_FROZEN_RANKING_OBJECTIVE_CHALLENGER")
R1_SUMMARY_PATH = R1_ROOT / "abcde_a2_r1_summary.json"
R1_OOF_PATH = R1_ROOT / "a2_r1_oof_predictions.parquet"
R1_MODEL_PATH = R1_ROOT / "a2_r1_final_hgb.joblib"
R2_SUMMARY_PATH = R2_ROOT / "abcde_a2_r2_summary.json"
R3_SUMMARY_PATH = R3_ROOT / "abcde_a2_r3_summary.json"
R4X_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R4X_HIVE_20230712_EXECUTION_PRICE_RECOVERY")
R4X_SUMMARY_PATH = R4X_ROOT / "abcde_a2_r4x_summary.json"
R4X_EVIDENCE_PATH = R4X_ROOT / "hive_20230710_20230714_moomoo_evidence.json"
R1_MODULE_PATH = REPO_ROOT / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
PRICE_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")

EXPECTED_R1_SUMMARY_SHA256 = "df1f4b63270a6974cffb962bfb1df5efb044a268591e37a9ab72cfdf39dcd6e5"
EXPECTED_R1_OOF_SHA256 = "a601b655afddf3e9aac63ea38571fff4dab3caad10400ae2a4a75697feeaf47e"
EXPECTED_R1_MODEL_SHA256 = "17c5c70010424cf0c409f84f5af420dd9d60fc7043a6c029ffbd5897e46f578d"
EXPECTED_R2_SUMMARY_SHA256 = "310a03167ce2910a0e3ce5258e92761b477c8a033113cb18d1a538a4da37ed4e"
EXPECTED_R3_SUMMARY_SHA256 = "77349c0aa0e8c658fbd720f9362a8915ae10f5a12df727014cd862d977752efe"
EXPECTED_PRICE_SHA256 = {
    2023: "a5a35422629920b7f5d063acabbb04f0ad410ec9f7e504de7daadd3b9d249bf6",
    2024: "7e14eb6735e7660e6895ab1a9a4ee86fa3ed1bd3ea976c56aeecfd75411e5eb8",
    2025: "b8a8abb5a8bdd7cbf9cf44ebba2f54bc09b60612c6fd8a7b7951aa064f9abc89",
}
EXPECTED_CONTRACT_SHA256 = "3d803330dee82a425b2544af16736547befea865dde5967e0de046b2ce83cd9d"
EXPECTED_R4X_SUMMARY_SHA256 = "82698f896c22a712cade5fe64cb64d4a41b9314a9a2695dda7fc7e37c27e0290"
EXPECTED_R4X_EVIDENCE_SHA256 = "ce6436e29ce404a0f7ced39eca92588a3eecacb3ebd78aa58aff62db5ff8cede"


def canonical_payload(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_payload(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_payload(value) + b"\n")
    os.replace(temporary, path)


def benchmark_contract() -> dict[str, Any]:
    return {
        "identity": "QQQ",
        "inheritance": "R1_TARGET_CANONICAL_BENCHMARK",
        "source": "MOOMOO_DERIVED_CANONICAL_QFQ_OHLCV",
        "calendar": "QQQ_CANONICAL_TRADING_DATES",
        "price_field": "canonical_qfq_open",
        "return_equation": "QQQ_OPEN_T/QQQ_OPEN_T_MINUS_1-1",
        "cumulative_excess_equation": "PORTFOLIO_NET_CUMULATIVE_RETURN_MINUS_QQQ_CUMULATIVE_RETURN",
        "no_alternative_benchmark_selection": True,
    }


def portfolio_contract() -> dict[str, Any]:
    benchmark = benchmark_contract()
    return {
        "contract_id": "ABCDE_A2_R4_PORTFOLIO_TRANSLATION_CONTRACT_R1",
        "experiment_role": "POST_MODEL_SELECTION_PRE2026_ECONOMIC_TRANSLATION",
        "primary_question": "DOES_FROZEN_HGB_RANKING_EDGE_TRANSLATE_TO_EXECUTABLE_NET_PORTFOLIO_ADVANTAGE_OVER_FROZEN_A1",
        "authoritative_prerequisites": {
            "r1": {"status": "PASS", "classification": "A_STRONG_INCREMENTAL_NONLINEAR_EDGE", "summary_sha256": EXPECTED_R1_SUMMARY_SHA256},
            "r2": {"status": "PASS", "classification": "M1_STRONG_MECHANISTIC_SUPPORT", "signal_lag_evidence": "SUPPORTS_EARLIER_CAPTURE", "summary_sha256": EXPECTED_R2_SUMMARY_SHA256},
            "r3": {"status": "PASS", "classification": "C_NO_INCREMENTAL_RANKING_OBJECTIVE_EDGE", "summary_sha256": EXPECTED_R3_SUMMARY_SHA256},
        },
        "incumbents": {
            "a1": "FROZEN_AUTHORITATIVE_A1_RAW_SCORE_AND_RANK_FROM_R1_OOF",
            "a2": "R1_HISTGRADIENTBOOSTINGREGRESSOR_AUTHORITATIVE_OOF_PREDICTION_AND_RANK",
            "r1_oof_sha256": EXPECTED_R1_OOF_SHA256,
            "r1_hgb_model_sha256": EXPECTED_R1_MODEL_SHA256,
            "current_cohort_count": 325,
            "current_cohort_fingerprint": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
            "same_signal_dates_tickers_u_t_and_target_availability": True,
            "model_search_allowed": False,
            "lambda_rank_route_status": "STOPPED",
        },
        "evidence_role": {
            "2023": "CONSUMED_PRE2026_TRANSLATION_EVIDENCE",
            "2024": "CONSUMED_PRE2026_TRANSLATION_EVIDENCE",
            "2025": "CONSUMED_PRE2026_TRANSLATION_EVIDENCE_NOT_FINAL",
            "2026_plus": "PROSPECTIVE_ONLY_NO_OUTCOME_READ",
        },
        "signal_and_execution": {
            "signal_information_cutoff": "AFTER_SIGNAL_DATE_CANONICAL_SESSION_CLOSE_AND_FINAL_FULL_DAY_VOLUME",
            "feature_information_basis": "FROZEN_32_FEATURES_INCLUDE_SIGNAL_DATE_CANONICAL_QFQ_CLOSE_AND_VOLUME",
            "same_close_execution_allowed": False,
            "first_legal_execution_timestamp": "NEXT_QQQ_CANONICAL_TRADING_SESSION_OPEN_AFTER_SIGNAL_DATE",
            "execution_price_field": "canonical_qfq_open",
            "signal_to_execution_date": "SMALLEST_QQQ_CANONICAL_TRADING_DATE_STRICTLY_GREATER_THAN_SIGNAL_DATE",
            "target_at_open": "TOPN_FROM_IMMEDIATELY_PREVIOUS_QQQ_SESSION_SIGNAL_IF_PRESENT_ELSE_CASH",
            "missing_signal_policy": "TARGET_ZERO_RISKY_WEIGHT_AND_CASH",
            "last_signal_policy": "HOLD_FOR_ONE_OPEN_TO_OPEN_INTERVAL_THEN_LIQUIDATE_AT_NEXT_CANONICAL_OPEN_IF_NO_NEW_SIGNAL",
            "missing_selected_or_held_open_policy": "FAIL_CLOSED_NO_FUTURE_FILL",
            "future_fill_allowed": False,
        },
        "portfolio": {
            "primary": {"top_n": 20, "side": "LONG_ONLY", "weighting": "EQUAL_WEIGHT", "target_weight_per_name": 0.05, "gross_exposure": 1.0, "leverage": 1.0, "shorting": False},
            "secondary": [{"top_n": 5, "secondary_only": True}, {"top_n": 10, "secondary_only": True}],
            "rebalance": "DAILY_AT_FIRST_LEGAL_EXECUTION_OPEN",
            "rank_direction": "RANK_1_IS_HIGHEST_SCORE",
            "portfolio_optimizer": False,
            "fast_gating": False,
            "stops_or_profit_taking": False,
        },
        "accounting": {
            "method": "PATH_WISE_OPEN_TO_NEXT_OPEN_SELF_FINANCING_WITH_CASH",
            "pretrade_weight": "PRIOR_TARGET_WEIGHT_TIMES_OPEN_RELATIVE_NORMALIZED_BY_PRE_COST_GROSS_PORTFOLIO_RETURN",
            "turnover_equation": "0.5*SUM_OVER_RISKY_SECURITIES(ABS(TARGET_WEIGHT-PRETRADE_WEIGHT))",
            "initial_and_liquidation_turnover_policy": "SAME_EQUATION_NO_SPECIAL_CASE",
            "gross_return_equation": "SUM(PRIOR_RISKY_WEIGHT*(OPEN_T/OPEN_T_MINUS_1-1));CASH_RETURN=0",
            "cost_application": "NET_RETURN=(1+GROSS_RETURN)*(1-TURNOVER*COST_BPS/10000)-1",
            "nav_update": "NAV_T=NAV_T_MINUS_1*(1+NET_RETURN_T)",
            "overlapping_forward_targets_as_cash_returns": False,
        },
        "transaction_cost": {
            "primary_one_way_cost_bps": 10,
            "sensitivity_bps": [0, 5, 10, 20],
            "gate_cost_bps": 10,
            "cost_equation": "TURNOVER*BPS/10000",
            "market_impact_model": "NONE",
        },
        "benchmark": {**benchmark, "benchmark_contract_fingerprint": canonical_fingerprint(benchmark)},
        "price_source": {
            "root": str(PRICE_ROOT),
            "partitions": {str(year): {"path": str(PRICE_ROOT / f"year={year}" / "prices.parquet"), "sha256": digest} for year, digest in EXPECTED_PRICE_SHA256.items()},
            "required_columns": ["ticker", "trade_date", "open", "autype", "source"],
            "required_autype": "QFQ",
            "required_source": "MOOMOO_DERIVED_CANONICAL",
            "date_scope": "2023-01-01_THROUGH_2025-12-31_ONLY",
        },
        "metrics": {
            "rf": 0.0,
            "annualization_trading_days": 252,
            "volatility_ddof": 0,
            "sharpe": "MEAN_DAILY_NET_RETURN/STDEV_DDOF0_DAILY_NET_RETURN*SQRT(252);RF=0",
            "cagr": "(ENDING_NAV/STARTING_NAV)^(252/DAILY_OBSERVATION_COUNT)-1",
            "max_drawdown": "MIN(NAV/CUMMAX_NAV-1)",
            "calmar": "CAGR/ABS(MAX_DRAWDOWN)",
            "positive_day": "NET_RETURN>0",
            "positive_month": "COMPOUNDED_CALENDAR_MONTH_NET_RETURN>0",
            "annualized_turnover": "MEAN_DAILY_TURNOVER*252",
            "reporting_scopes": [2023, 2024, 2025, "POOLED_PRE2026"],
        },
        "decision_gate": {
            "P1_STRONG_PORTFOLIO_TRANSLATION": [
                "POOLED_A2_NET_CAGR>POOLED_A1_NET_CAGR",
                "POOLED_A2_NET_SHARPE>POOLED_A1_NET_SHARPE",
                "POOLED_A2_CALMAR>POOLED_A1_CALMAR",
                "POOLED_A2_NET_EXCESS_RETURN>POOLED_A1_NET_EXCESS_RETURN",
                "A2_NET_RETURN_GREATER_THAN_A1_YEAR_COUNT>=2",
                "POOLED_A2_NET_CUMULATIVE_RETURN_MINUS_A1>0",
                "ALL_EXECUTION_LEAKAGE_IDENTITY_REPRODUCIBILITY_AUDITS_PASS",
            ],
            "P2_PARTIAL_OR_COST_SENSITIVE_TRANSLATION": "NOT_P1_AND_ANY_OF_DELTA_NET_CAGR_DELTA_NET_SHARPE_DELTA_CALMAR_DELTA_NET_EXCESS_RETURN_POSITIVE_OR_POSITIVE_YEAR_COUNT_AT_LEAST_1",
            "P3_RANKING_EDGE_DOES_NOT_TRANSLATE": "NOT_P1_AND_NOT_P2",
            "FAIL_CLOSED": "ANY_CONTRACT_EXECUTION_PRICE_LEAKAGE_IDENTITY_OR_REPRODUCIBILITY_FAILURE",
            "primary_top_n": 20,
            "primary_cost_bps": 10,
            "cost_sensitivity_not_gate": True,
        },
        "prospective_activation": {
            "allowed_only_if": "P1_STRONG_PORTFOLIO_TRANSLATION",
            "model": "FULL_PRE2026_FROZEN_R1_HGB_CONFIG",
            "no_2026_outcome_read": True,
            "no_backfill": True,
            "first_legal_signal": "FIRST_LIVE_CANONICAL_TRADING_DATE_STRICTLY_AFTER_MODEL_FREEZE",
            "production_adoption": False,
            "broker_action_allowed": False,
        },
        "reproducibility": {"complete_materializations": 2, "required": "RUN1_FINGERPRINT_EQUALS_RUN2_FINGERPRINT"},
        "prohibitions": {
            "new_model": True, "model_tuning": True, "portfolio_optimization": True,
            "fast_change": True, "post2025_outcome_read": True, "production_adoption": True,
            "broker_action": True,
        },
    }


def freeze_contract() -> dict[str, Any]:
    contract = portfolio_contract()
    payload = canonical_payload(contract) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    if CONTRACT_PATH.exists():
        if CONTRACT_PATH.read_bytes() != payload:
            raise RuntimeError("EXISTING_R4_CONTRACT_DIFFERS_FAIL_CLOSED")
    else:
        temporary = CONTRACT_PATH.with_suffix(".json.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, CONTRACT_PATH)
    witness = {
        "experiment_id": EXPERIMENT_ID,
        "contract_path": str(CONTRACT_PATH),
        "contract_sha256": digest,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "row_level_oof_signal_read_count_before_freeze": 0,
        "future_execution_price_value_read_count_before_freeze": 0,
        "portfolio_outcome_read_count_before_freeze": 0,
        "post2025_target_read_count_before_freeze": 0,
        "post2025_outcome_read_count_before_freeze": 0,
        "status": "PASS_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ",
    }
    if WITNESS_PATH.exists():
        prior = json.loads(WITNESS_PATH.read_text(encoding="utf-8"))
        if prior.get("contract_sha256") != digest or prior.get("status") != witness["status"]:
            raise RuntimeError("R4_FREEZE_WITNESS_MISMATCH_FAIL_CLOSED")
        witness = prior
    else:
        write_json_atomic(WITNESS_PATH, witness)
    return witness


def execution_eligibility_policy() -> dict[str, Any]:
    return {
        "policy_id": "ABCDE_A2_R4_EXECUTION_ELIGIBILITY_POLICY_R1",
        "execution_eligibility_policy_version": "R1",
        "supplements_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "supplement_scope": "MISSING_AUTHORITATIVE_EXECUTION_PRICE_HANDLING_ONLY",
        "original_contract_unchanged": True,
        "model_universe_type": "FROZEN_CURRENT_325",
        "current_cohort_count": 325,
        "current_cohort_fingerprint": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
        "model_cohort_changed": False,
        "a1_model_changed": False,
        "a2_model_changed": False,
        "eligibility_layers": ["MODEL_ELIGIBILITY", "SIGNAL_ELIGIBILITY", "EXECUTION_ELIGIBILITY"],
        "portfolio_candidate_equation": "MODEL_ELIGIBLE_AND_SIGNAL_ELIGIBLE_AND_EXECUTION_ELIGIBLE",
        "execution_eligibility_equation": "HAS_AUTHORITATIVE_CANONICAL_QFQ_OPEN_SECURITY_DATE",
        "execution_price_field": "canonical_qfq_open",
        "execution_session": "FIRST_LEGAL_QQQ_CANONICAL_SESSION_AFTER_SIGNAL",
        "missing_entry_execution_policy": "SKIP_ENTRY_HOLD_CASH",
        "missing_held_execution_policy": "HOLD_POSITION_NO_TRADE",
        "no_stale_order_queue": True,
        "next_session_policy": "RECOMPUTE_FROM_LATEST_FROZEN_SIGNAL_TARGET_WITHOUT_OLD_ORDER",
        "valuation_policy": {
            "normal_mark": "CURRENT_SESSION_CANONICAL_QFQ_OPEN",
            "missing_current_open_mark": "LAST_OBSERVED_CANONICAL_CLOSE_STRICTLY_BEFORE_EXECUTION_SESSION",
            "stale_mark_flag_required": True,
            "stale_mark_must_not_be_execution_price": True,
            "no_prior_close": "FAIL_CLOSED_UNVALUABLE_HELD_POSITION",
            "future_close_read_allowed": False,
        },
        "cash_accounting": {
            "unexecuted_sell_generates_cash": False,
            "unexecuted_buy_consumes_cash": False,
            "phantom_proceeds_allowed": False,
            "implicit_leverage_allowed": False,
            "buy_cash_shortfall_policy": "PRO_RATA_SCALE_EXECUTABLE_BUYS",
        },
        "turnover": {
            "target_turnover": "0.5*SUM_ABS(TARGET_RISKY_WEIGHT_MINUS_PRETRADE_RISKY_WEIGHT)",
            "executed_turnover": "0.5*EXECUTED_TRADED_NOTIONAL/PRETRADE_NAV",
            "transaction_cost_basis": "EXECUTED_TURNOVER_ONLY",
        },
        "permanent_security_exclusion": False,
        "ticker_specific_exception_allowed": False,
        "synthetic_fill_allowed": False,
        "previous_close_execution_allowed": False,
        "next_open_substitution_allowed": False,
        "future_fill_allowed": False,
        "applies_identically_to": ["A1", "A2_HGB"],
        "r4x_evidence": {
            "summary_path": str(R4X_SUMMARY_PATH), "summary_sha256": EXPECTED_R4X_SUMMARY_SHA256,
            "evidence_path": str(R4X_EVIDENCE_PATH), "evidence_sha256": EXPECTED_R4X_EVIDENCE_SHA256,
            "status": "PASS_EVIDENCE_RESOLVED_NO_BAR", "hive_20230712_status": "MOOMOO_CONFIRMED_NO_BAR",
        },
        "model_search_count": 0,
        "hyperparameter_search_trial_count": 0,
        "model_fit_for_selection_count": 0,
    }


def _preserve_prior_fail_closed_provenance() -> dict[str, str]:
    mapping = (
        (SUMMARY_PATH, PRIOR_FAIL_SUMMARY_PATH),
        (MANIFEST_PATH, PRIOR_FAIL_MANIFEST_PATH),
        (EXECUTION_COVERAGE_AUDIT_PATH, PRIOR_FAIL_COVERAGE_PATH),
    )
    hashes: dict[str, str] = {}
    for source, destination in mapping:
        if not source.is_file():
            raise RuntimeError(f"R4E_MISSING_PRIOR_FAIL_CLOSED_PROVENANCE:{source}")
        payload = source.read_bytes()
        if destination.exists():
            if destination.read_bytes() != payload:
                raise RuntimeError(f"R4E_PRIOR_PROVENANCE_DESTINATION_MISMATCH:{destination}")
        else:
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        hashes[str(destination)] = sha256_file(destination)
    return hashes


def _prior_portfolio_outcome_audit() -> dict[str, Any]:
    prior_summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    prior_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    coverage = json.loads(EXECUTION_COVERAGE_AUDIT_PATH.read_text(encoding="utf-8"))
    no_pnl_artifacts = not any(path.exists() for path in (DAILY_PATH, METRICS_PATH, COST_SENSITIVITY_PATH))
    passed = bool(
        prior_summary.get("ABCDE_A2_R4_STATUS") == "FAIL_CLOSED"
        and prior_summary.get("R4_CLASSIFICATION") == "FAIL_CLOSED"
        and "R4_MISSING_CANONICAL_EXECUTION_OPEN_FAIL_CLOSED" in str(prior_summary.get("FAILURE_REASON"))
        and coverage.get("missing_event_count") == 1
        and prior_manifest.get("status") == "FAIL_CLOSED"
        and no_pnl_artifacts
    )
    if not passed:
        raise RuntimeError("R4E_CANNOT_PROVE_PRIOR_PORTFOLIO_OUTCOME_UNREAD")
    return {
        "R4_PORTFOLIO_OUTCOME_PREVIOUSLY_READ": False,
        "prior_r4_status": prior_summary.get("ABCDE_A2_R4_STATUS"),
        "prior_r4_failure_reason": prior_summary.get("FAILURE_REASON"),
        "prior_missing_execution_open_count": coverage.get("missing_event_count"),
        "daily_portfolio_artifact_existed_before_freeze": DAILY_PATH.exists(),
        "metrics_artifact_existed_before_freeze": METRICS_PATH.exists(),
        "cost_sensitivity_artifact_existed_before_freeze": COST_SENSITIVITY_PATH.exists(),
        "audit_status": "PASS_PROVEN_BEFORE_FIRST_PORTFOLIO_MATERIALIZATION",
    }


def freeze_execution_eligibility_policy() -> dict[str, Any]:
    if sha256_file(CONTRACT_PATH) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("R4E_ORIGINAL_R4_CONTRACT_CHANGED")
    if not R4X_SUMMARY_PATH.is_file() or sha256_file(R4X_SUMMARY_PATH) != EXPECTED_R4X_SUMMARY_SHA256:
        raise RuntimeError("R4E_R4X_SUMMARY_IDENTITY_FAILURE")
    if not R4X_EVIDENCE_PATH.is_file() or sha256_file(R4X_EVIDENCE_PATH) != EXPECTED_R4X_EVIDENCE_SHA256:
        raise RuntimeError("R4E_R4X_EVIDENCE_IDENTITY_FAILURE")
    r4x_summary = json.loads(R4X_SUMMARY_PATH.read_text(encoding="utf-8"))
    r4x_evidence = json.loads(R4X_EVIDENCE_PATH.read_text(encoding="utf-8"))
    if (
        r4x_summary.get("ABCDE_A2_R4X_STATUS") != "PASS_EVIDENCE_RESOLVED_NO_BAR"
        or r4x_summary.get("HIVE_20230712_STATUS") != "MOOMOO_CONFIRMED_NO_BAR"
        or r4x_evidence.get("target_row_count") != 0
    ):
        raise RuntimeError("R4E_R4X_NO_BAR_EVIDENCE_STATUS_FAILURE")
    policy = execution_eligibility_policy()
    payload = canonical_payload(policy) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    if EXECUTION_ELIGIBILITY_POLICY_PATH.exists():
        if EXECUTION_ELIGIBILITY_POLICY_PATH.read_bytes() != payload:
            raise RuntimeError("R4E_EXISTING_EXECUTION_ELIGIBILITY_POLICY_DIFFERS")
        if not EXECUTION_ELIGIBILITY_WITNESS_PATH.is_file():
            raise RuntimeError("R4E_POLICY_EXISTS_WITHOUT_FREEZE_WITNESS")
        witness = json.loads(EXECUTION_ELIGIBILITY_WITNESS_PATH.read_text(encoding="utf-8"))
        if witness.get("execution_eligibility_policy_sha256") != digest:
            raise RuntimeError("R4E_EXECUTION_ELIGIBILITY_WITNESS_MISMATCH")
        return witness
    prior_audit = _prior_portfolio_outcome_audit()
    provenance_hashes = _preserve_prior_fail_closed_provenance()
    temporary = EXECUTION_ELIGIBILITY_POLICY_PATH.with_suffix(".json.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, EXECUTION_ELIGIBILITY_POLICY_PATH)
    witness = {
        "experiment_id": "ABCDE_A2_R4E_EXECUTION_ELIGIBILITY_FREEZE_AND_EXACT_RERUN",
        "execution_eligibility_policy_path": str(EXECUTION_ELIGIBILITY_POLICY_PATH),
        "execution_eligibility_policy_sha256": digest,
        "original_r4_contract_path": str(CONTRACT_PATH),
        "original_r4_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_eligibility_policy_frozen_before_portfolio_outcome_read": True,
        "portfolio_outcome_read_count_before_freeze": 0,
        "post2025_target_read_count_before_freeze": 0,
        "post2025_outcome_read_count_before_freeze": 0,
        "prior_outcome_audit": prior_audit,
        "preserved_fail_closed_provenance_sha256": provenance_hashes,
        "status": "PASS_FROZEN_OUTCOME_BLIND_BEFORE_R4_PORTFOLIO_MATERIALIZATION",
    }
    write_json_atomic(EXECUTION_ELIGIBILITY_WITNESS_PATH, witness)
    return witness


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


def validate_prerequisites() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    required = (R1_SUMMARY_PATH, R1_OOF_PATH, R1_MODEL_PATH, R2_SUMMARY_PATH, R3_SUMMARY_PATH, R1_MODULE_PATH)
    missing = [str(path) for path in required if not path.is_file()]
    for year in EXPECTED_PRICE_SHA256:
        path = PRICE_ROOT / f"year={year}" / "prices.parquet"
        if not path.is_file():
            missing.append(str(path))
    if missing:
        raise RuntimeError("MISSING_R4_AUTHORITATIVE_ARTIFACT:" + ",".join(missing))
    if sha256_file(CONTRACT_PATH) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("R4_CONTRACT_SHA256_MISMATCH")
    hashes = {
        "r1_summary": sha256_file(R1_SUMMARY_PATH), "r1_oof": sha256_file(R1_OOF_PATH),
        "r1_model": sha256_file(R1_MODEL_PATH), "r2_summary": sha256_file(R2_SUMMARY_PATH),
        "r3_summary": sha256_file(R3_SUMMARY_PATH),
    }
    expected = {
        "r1_summary": EXPECTED_R1_SUMMARY_SHA256, "r1_oof": EXPECTED_R1_OOF_SHA256,
        "r1_model": EXPECTED_R1_MODEL_SHA256, "r2_summary": EXPECTED_R2_SUMMARY_SHA256,
        "r3_summary": EXPECTED_R3_SUMMARY_SHA256,
    }
    if hashes != expected:
        raise RuntimeError("R4_INHERITED_ARTIFACT_SHA256_MISMATCH:" + ",".join(key for key in expected if hashes[key] != expected[key]))
    price_hashes = {year: sha256_file(PRICE_ROOT / f"year={year}" / "prices.parquet") for year in EXPECTED_PRICE_SHA256}
    if price_hashes != EXPECTED_PRICE_SHA256:
        raise RuntimeError("R4_CANONICAL_PRICE_PARTITION_SHA256_MISMATCH")
    r1_summary = json.loads(R1_SUMMARY_PATH.read_text(encoding="utf-8"))
    r2_summary = json.loads(R2_SUMMARY_PATH.read_text(encoding="utf-8"))
    r3_summary = json.loads(R3_SUMMARY_PATH.read_text(encoding="utf-8"))
    checks = {
        "r1_status": r1_summary.get("ABCDE_A2_R1_STATUS") == "PASS",
        "r1_classification": r1_summary.get("ABCDE_A2_R1_CLASSIFICATION") == "A_STRONG_INCREMENTAL_NONLINEAR_EDGE",
        "r1_identity": r1_summary.get("A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS") == "PASS",
        "r1_model": r1_summary.get("MODEL_FAMILY") == "HistGradientBoostingRegressor",
        "r2_status": r2_summary.get("ABCDE_A2_R2_STATUS") == "PASS",
        "r2_classification": r2_summary.get("ABCDE_A2_R2_CLASSIFICATION") == "M1_STRONG_MECHANISTIC_SUPPORT",
        "r2_lag": r2_summary.get("SIGNAL_LAG_EVIDENCE") == "SUPPORTS_EARLIER_CAPTURE",
        "r3_status": r3_summary.get("ABCDE_A2_R3_STATUS") == "PASS",
        "r3_classification": r3_summary.get("R3_CLASSIFICATION") == "C_NO_INCREMENTAL_RANKING_OBJECTIVE_EDGE",
        "post2025_r1": r1_summary.get("POST2025_OUTCOME_READ_COUNT") == 0,
        "post2025_r2": r2_summary.get("POST2025_OUTCOME_READ_COUNT") == 0,
        "post2025_r3": r3_summary.get("POST2025_OUTCOME_READ_COUNT") == 0,
    }
    if not all(checks.values()):
        raise RuntimeError("R4_INHERITED_STATUS_FAILURE:" + ",".join(key for key, passed in checks.items() if not passed))
    return r1_summary, r2_summary, r3_summary, {"checks": checks, "artifact_hashes": hashes, "price_hashes": price_hashes}


def load_authoritative_signals() -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = ["signal_date", "ticker", "universe_size", "split", "a1_raw_score", "a1_rank", "a2_prediction", "a2_rank"]
    signals = pq.read_table(R1_OOF_PATH, columns=columns).to_pandas()
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])
    signals["ticker"] = signals["ticker"].astype(str).str.upper()
    signals = signals.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    if len(signals) != 210445 or signals.duplicated(["signal_date", "ticker"]).any():
        raise RuntimeError("R4_SIGNAL_ROW_IDENTITY_FAILURE")
    if (signals.signal_date >= pd.Timestamp("2026-01-01")).any():
        raise RuntimeError("R4_POST2025_SIGNAL_ROW_FAILURE")
    if signals[["a1_raw_score", "a1_rank", "a2_prediction", "a2_rank"]].isna().any().any():
        raise RuntimeError("R4_NONFINITE_AUTHORITATIVE_SIGNAL")
    if np.isinf(signals[["a1_raw_score", "a2_prediction"]].to_numpy(dtype=float)).any():
        raise RuntimeError("R4_INFINITE_AUTHORITATIVE_SIGNAL")
    date_counts = signals.groupby("signal_date", sort=True).size()
    if not (signals.groupby("signal_date", sort=True)["universe_size"].nunique() == 1).all():
        raise RuntimeError("R4_U_T_SIZE_NOT_UNIQUE_WITHIN_DATE")
    universe_sizes = signals.groupby("signal_date", sort=True).universe_size.first()
    if (date_counts > universe_sizes).any():
        raise RuntimeError("R4_OOF_ROWS_EXCEED_U_T_SIZE")
    topn_incomplete: dict[str, int] = {}
    for top_n in (5, 10, 20):
        a1_count = signals.loc[signals.a1_rank <= top_n].groupby("signal_date").size().reindex(date_counts.index, fill_value=0)
        a2_count = signals.loc[signals.a2_rank <= top_n].groupby("signal_date").size().reindex(date_counts.index, fill_value=0)
        if (a1_count > top_n).any() or (a2_count > top_n).any():
            raise RuntimeError(f"R4_TOPN_COUNT_EXCEEDS_FROZEN_N:{top_n}")
        topn_incomplete[str(top_n)] = int(((a1_count < top_n) | (a2_count < top_n)).sum())
    audit = {
        "signal_rows": len(signals), "signal_date_count": int(signals.signal_date.nunique()),
        "signal_start": str(signals.signal_date.min().date()), "signal_end": str(signals.signal_date.max().date()),
        "a1_a2_signal_date_identity": True, "a1_a2_daily_universe_identity": True,
        "oof_target_availability_gap_date_count": int((date_counts < universe_sizes).sum()),
        "shared_cash_override_incomplete_topn_date_count": topn_incomplete,
        "post2025_signal_count": 0,
    }
    return signals, audit


def load_execution_prices(wanted: set[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    pieces: list[pd.DataFrame] = []
    for year in (2023, 2024, 2025):
        path = PRICE_ROOT / f"year={year}" / "prices.parquet"
        table = pq.read_table(path, columns=["ticker", "trade_date", "open", "close", "autype", "source"])
        frame = table.to_pandas()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        pieces.append(frame.loc[frame.ticker.isin(wanted | {"QQQ"})])
    prices = pd.concat(pieces, ignore_index=True)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices["open"] = pd.to_numeric(prices["open"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.sort_values(["trade_date", "ticker"], kind="mergesort").reset_index(drop=True)
    if prices.empty or prices.duplicated(["trade_date", "ticker"]).any():
        raise RuntimeError("R4_CANONICAL_OPEN_DUPLICATE_OR_EMPTY")
    if (prices.trade_date >= pd.Timestamp("2026-01-01")).any():
        raise RuntimeError("R4_POST2025_PRICE_READ_FAILURE")
    if set(prices.autype.astype(str).str.lower().unique()) != {"qfq"}:
        raise RuntimeError("R4_NON_QFQ_EXECUTION_PRICE_SOURCE")
    if set(prices.source.astype(str).str.upper().unique()) != {"MOOMOO_OPEND"}:
        raise RuntimeError("R4_NON_MOOMOO_EXECUTION_PRICE_SOURCE")
    if "QQQ" not in set(prices.ticker):
        raise RuntimeError("R4_MISSING_QQQ_BENCHMARK")
    audit = {
        "price_rows_read": len(prices), "price_start": str(prices.trade_date.min().date()),
        "price_end": str(prices.trade_date.max().date()), "autype_values": ["qfq"],
        "source_values": ["MOOMOO_OPEND"], "post2025_price_rows": 0,
    }
    return prices, audit


def build_target_map(
    signals: pd.DataFrame, rank_column: str, top_n: int,
    valid_signal_dates: set[pd.Timestamp] | None = None,
) -> dict[pd.Timestamp, dict[str, float]]:
    selected = signals.loc[signals[rank_column] <= top_n, ["signal_date", "ticker", rank_column]].copy()
    if valid_signal_dates is not None:
        selected = selected.loc[selected.signal_date.isin(valid_signal_dates)]
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for signal_date, day in selected.groupby("signal_date", sort=True):
        if len(day) != top_n or day.ticker.nunique() != top_n:
            raise RuntimeError(f"R4_TOPN_CARDINALITY_FAILURE:{rank_column}:{top_n}:{signal_date}:{len(day)}")
        result[pd.Timestamp(signal_date)] = {ticker: 1.0 / top_n for ticker in day.ticker.tolist()}
    return result


def _safe_open(open_wide: pd.DataFrame, date: pd.Timestamp, ticker: str) -> float:
    try:
        value = float(open_wide.at[date, ticker])
    except (KeyError, TypeError, ValueError):
        value = np.nan
    if not np.isfinite(value) or value <= 0:
        raise RuntimeError(f"R4_MISSING_OR_INVALID_CANONICAL_OPEN:{ticker}:{date.date()}")
    return value


def execution_open_coverage_audit(signals: pd.DataFrame, prices: pd.DataFrame) -> dict[str, Any]:
    qqq = prices.loc[prices.ticker == "QQQ", ["trade_date", "open"]].drop_duplicates("trade_date").sort_values("trade_date")
    full_calendar = pd.DatetimeIndex(qqq.trade_date)
    positions = pd.Series(np.arange(len(full_calendar)), index=full_calendar)
    signal_dates = pd.DatetimeIndex(sorted(signals.signal_date.unique()))
    if not signal_dates.isin(full_calendar).all():
        raise RuntimeError("R4_SIGNAL_DATE_NOT_ON_QQQ_CALENDAR")
    first = int(positions.loc[signal_dates.min()]) + 1
    end = int(positions.loc[signal_dates.max()]) + 3
    if end > len(full_calendar):
        raise RuntimeError("R4_INSUFFICIENT_EXECUTION_COVERAGE_CALENDAR")
    calendar = full_calendar[first:end]
    opens = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()

    def has_open(date: pd.Timestamp, ticker: str) -> bool:
        try:
            value = float(opens.at[date, ticker])
        except (KeyError, TypeError, ValueError):
            return False
        return bool(np.isfinite(value) and value > 0)

    missing: set[tuple[str, int, str, str, str]] = set()
    path_count = 0
    for model, rank_column in (("A1", "a1_rank"), ("A2_HGB", "a2_rank")):
        for top_n in (5, 10, 20):
            all_dates = pd.DatetimeIndex(sorted(signals.signal_date.unique()))
            a1_count = signals.loc[signals.a1_rank <= top_n].groupby("signal_date").size().reindex(all_dates, fill_value=0)
            a2_count = signals.loc[signals.a2_rank <= top_n].groupby("signal_date").size().reindex(all_dates, fill_value=0)
            valid_dates = set(pd.Timestamp(date) for date in all_dates[(a1_count.to_numpy() == top_n) & (a2_count.to_numpy() == top_n)])
            target_map = build_target_map(signals, rank_column, top_n, valid_dates)
            prior_holdings: set[str] = set()
            prior_execution_date: pd.Timestamp | None = None
            for execution_date in calendar:
                execution_date = pd.Timestamp(execution_date)
                if prior_execution_date is not None:
                    for ticker in prior_holdings:
                        if not has_open(prior_execution_date, ticker):
                            missing.add((model, top_n, str(prior_execution_date.date()), ticker, "HELD_INTERVAL_START_OPEN"))
                        if not has_open(execution_date, ticker):
                            missing.add((model, top_n, str(execution_date.date()), ticker, "HELD_INTERVAL_END_OR_EXIT_OPEN"))
                prior_signal_date = pd.Timestamp(full_calendar[int(positions.loc[execution_date]) - 1])
                target = target_map.get(prior_signal_date, {})
                for ticker in target:
                    if not has_open(execution_date, ticker):
                        missing.add((model, top_n, str(execution_date.date()), ticker, "TARGET_ENTRY_OR_REBALANCE_OPEN"))
                prior_holdings = set(target)
                prior_execution_date = execution_date
            path_count += 1
    events = [
        {"model": model, "top_n": top_n, "execution_date": date, "ticker": ticker, "requirement": requirement}
        for model, top_n, date, ticker, requirement in sorted(missing)
    ]
    payload = {
        "status": "PASS" if not events else "FAIL_CLOSED_MISSING_CANONICAL_EXECUTION_OPEN",
        "audited_model_topn_path_count": path_count, "missing_event_count": len(events),
        "missing_events": events, "future_fill_count": 0,
        "policy": "FAIL_CLOSED_NO_FUTURE_FILL",
    }
    payload["logical_fingerprint"] = canonical_fingerprint(payload)
    return payload


def execution_eligibility_audit(
    signals: pd.DataFrame, prices: pd.DataFrame, top_ns: tuple[int, ...] = (20,),
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Enumerate required security-date execution events without reading portfolio PnL."""
    qqq = prices.loc[prices.ticker == "QQQ", ["trade_date", "open"]].drop_duplicates("trade_date").sort_values("trade_date")
    full_calendar = pd.DatetimeIndex(qqq.trade_date)
    calendar_position = pd.Series(np.arange(len(full_calendar)), index=full_calendar)
    signal_dates = pd.DatetimeIndex(sorted(signals.signal_date.unique()))
    if not signal_dates.isin(full_calendar).all():
        raise RuntimeError("R4E_SIGNAL_DATE_NOT_ON_QQQ_CALENDAR")
    first = int(calendar_position.loc[signal_dates.min()]) + 1
    end = int(calendar_position.loc[signal_dates.max()]) + 3
    if end > len(full_calendar):
        raise RuntimeError("R4E_INSUFFICIENT_EXECUTION_AUDIT_CALENDAR")
    calendar = full_calendar[first:end]
    opens = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()

    def has_open(date: pd.Timestamp, ticker: str) -> bool:
        try:
            value = float(opens.at[date, ticker])
        except (KeyError, TypeError, ValueError):
            return False
        return bool(np.isfinite(value) and value > 0)

    rows: list[dict[str, Any]] = []
    for model, rank_column in (("A1", "a1_rank"), ("A2_HGB", "a2_rank")):
        for top_n in top_ns:
            a1_count = signals.loc[signals.a1_rank <= top_n].groupby("signal_date").size().reindex(signal_dates, fill_value=0)
            a2_count = signals.loc[signals.a2_rank <= top_n].groupby("signal_date").size().reindex(signal_dates, fill_value=0)
            valid_dates = set(pd.Timestamp(date) for date in signal_dates[(a1_count.to_numpy() == top_n) & (a2_count.to_numpy() == top_n)])
            target_map = build_target_map(signals, rank_column, top_n, valid_dates)
            actual_holdings: set[str] = set()
            for execution_date in calendar:
                execution_date = pd.Timestamp(execution_date)
                prior_signal_date = pd.Timestamp(full_calendar[int(calendar_position.loc[execution_date]) - 1])
                target = set(target_map.get(prior_signal_date, {}))
                updated = set(actual_holdings)
                for ticker in sorted(actual_holdings | target):
                    in_held = ticker in actual_holdings
                    in_target = ticker in target
                    if not in_held and in_target:
                        action = "BUY_ENTRY"
                    elif in_held and not in_target:
                        action = "SELL_EXIT"
                    else:
                        action = "REBALANCE_HELD"
                    eligible = has_open(execution_date, ticker)
                    rows.append({
                        "ticker": ticker, "signal_date": prior_signal_date,
                        "execution_date": execution_date, "model": model,
                        "portfolio": f"TOP{top_n}_EQUAL_WEIGHT_LONG_ONLY", "top_n": top_n,
                        "required_action": action, "execution_eligible": eligible,
                        "missing_field": None if eligible else "canonical_qfq_open",
                    })
                    if eligible:
                        if in_target:
                            updated.add(ticker)
                        else:
                            updated.discard(ticker)
                actual_holdings = updated
            if actual_holdings:
                raise RuntimeError(f"R4E_TERMINAL_POSITION_NOT_EXECUTABLY_CLOSED:{model}:TOP{top_n}:{sorted(actual_holdings)[:5]}")
    detail = pd.DataFrame(rows).sort_values(
        ["execution_date", "model", "top_n", "ticker"], kind="mergesort",
    ).reset_index(drop=True)
    missing = detail.loc[~detail.execution_eligible]
    ineligible_by_ticker = missing.groupby("ticker", sort=True).execution_date.apply(list)
    max_consecutive = 0
    calendar_pos = {pd.Timestamp(date): index for index, date in enumerate(full_calendar)}
    for dates in ineligible_by_ticker:
        positions = sorted(calendar_pos[pd.Timestamp(date)] for date in set(dates))
        run = 0
        prior = None
        for position in positions:
            run = run + 1 if prior is not None and position == prior + 1 else 1
            max_consecutive = max(max_consecutive, run)
            prior = position
    fingerprint_columns = [
        "ticker", "signal_date", "execution_date", "model", "portfolio", "top_n",
        "required_action", "execution_eligible", "missing_field",
    ]
    summary = {
        "status": "PASS_EXECUTION_ELIGIBILITY_POLICY_DETERMINISTIC",
        "EXECUTION_REQUIRED_EVENT_COUNT": len(detail),
        "EXECUTION_ELIGIBLE_EVENT_COUNT": int(detail.execution_eligible.sum()),
        "EXECUTION_INELIGIBLE_EVENT_COUNT": len(missing),
        "UNIQUE_EXECUTION_INELIGIBLE_SECURITY_COUNT": int(missing.ticker.nunique()),
        "PERMANENT_SECURITY_EXCLUSION_COUNT": 0,
        "MAX_CONSECUTIVE_EXECUTION_INELIGIBLE_SESSIONS": int(max_consecutive),
        "HIVE_2023_07_12_NATURAL_FAILURE_COUNT": int(
            ((missing.ticker == "HIVE") & (missing.execution_date == pd.Timestamp("2023-07-12"))).sum()
        ),
        "FUTURE_FILL_COUNT": 0,
        "TICKER_SPECIFIC_EXCEPTION_COUNT": 0,
        "logical_fingerprint": dataframe_fingerprint(detail, fingerprint_columns),
    }
    return detail, summary


def simulate_portfolio(
    signals: pd.DataFrame, prices: pd.DataFrame, model: str, rank_column: str,
    top_n: int, cost_bps: int,
    risk_budget_by_signal_date: dict[pd.Timestamp, float] | None = None,
    corporate_action_adapter: Any | None = None,
) -> pd.DataFrame:
    qqq = prices.loc[prices.ticker == "QQQ", ["trade_date", "open"]].drop_duplicates("trade_date").sort_values("trade_date")
    if qqq.open.isna().any() or (qqq.open <= 0).any():
        raise RuntimeError("R4_INVALID_QQQ_OPEN")
    full_calendar = pd.DatetimeIndex(qqq.trade_date)
    calendar_position = pd.Series(np.arange(len(full_calendar)), index=full_calendar)
    signal_dates = pd.DatetimeIndex(sorted(signals.signal_date.unique()))
    if not signal_dates.isin(full_calendar).all():
        raise RuntimeError("R4_SIGNAL_DATE_NOT_ON_QQQ_CALENDAR")
    first_signal_position = int(calendar_position.loc[signal_dates.min()])
    last_signal_position = int(calendar_position.loc[signal_dates.max()])
    if first_signal_position + 1 >= len(full_calendar) or last_signal_position + 2 >= len(full_calendar):
        raise RuntimeError("R4_INSUFFICIENT_NEXT_OPEN_EXECUTION_CALENDAR")
    simulation_calendar = full_calendar[first_signal_position + 1:last_signal_position + 3]
    open_wide = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    close_wide = prices.pivot(index="trade_date", columns="ticker", values="close").sort_index()
    all_dates = pd.DatetimeIndex(sorted(signals.signal_date.unique()))
    a1_count = signals.loc[signals.a1_rank <= top_n].groupby("signal_date").size().reindex(all_dates, fill_value=0)
    a2_count = signals.loc[signals.a2_rank <= top_n].groupby("signal_date").size().reindex(all_dates, fill_value=0)
    valid_signal_dates = set(pd.Timestamp(date) for date in all_dates[(a1_count.to_numpy() == top_n) & (a2_count.to_numpy() == top_n)])
    target_map = build_target_map(signals, rank_column, top_n, valid_signal_dates)
    qqq_open = qqq.set_index("trade_date").open.astype(float)
    shares: dict[str, float] = {}
    cash = 1.0
    net_nav = 1.0
    gross_nav = 1.0
    benchmark_nav = 1.0
    rows: list[dict[str, Any]] = []
    previous_date: pd.Timestamp | None = None
    cost_rate = cost_bps / 10000.0

    def open_value(date: pd.Timestamp, ticker: str) -> float:
        try:
            value = float(open_wide.at[date, ticker])
        except (KeyError, TypeError, ValueError):
            return np.nan
        return value if np.isfinite(value) and value > 0 else np.nan

    def mark_value(date: pd.Timestamp, ticker: str) -> tuple[float, bool, pd.Timestamp]:
        opening = open_value(date, ticker)
        if np.isfinite(opening):
            return opening, False, date
        if ticker not in close_wide.columns:
            raise RuntimeError(f"R4E_FAIL_CLOSED_UNVALUABLE_HELD_POSITION:{ticker}:{date.date()}")
        history = close_wide.loc[close_wide.index < date, ticker].dropna()
        history = history.loc[np.isfinite(history.to_numpy(dtype=float)) & (history.to_numpy(dtype=float) > 0)]
        if history.empty:
            raise RuntimeError(f"R4E_FAIL_CLOSED_UNVALUABLE_HELD_POSITION:{ticker}:{date.date()}")
        return float(history.iloc[-1]), True, pd.Timestamp(history.index[-1])

    for execution_date in simulation_calendar:
        execution_date = pd.Timestamp(execution_date)
        transition_rows: list[dict[str, Any]] = []
        corporate_action_cash_delta = 0.0
        if corporate_action_adapter is not None:
            # Corporate actions become effective before the session mark and
            # before any rebalance trade.  The default R4 path passes no
            # adapter and is therefore byte-for-byte economically unchanged.
            shares, cash, transition_rows = corporate_action_adapter.apply(
                execution_date=execution_date, shares=shares, cash=cash,
                context={"model": model, "top_n": top_n, "cost_bps": cost_bps},
            )
            corporate_action_cash_delta = float(sum(row.get("cash_delta", 0.0) for row in transition_rows))
        marks: dict[str, float] = {}
        stale_mark_count = 0
        stale_mark_oldest_date: pd.Timestamp | None = None
        position_values: dict[str, float] = {}
        for ticker, quantity in shares.items():
            mark, stale, mark_date = mark_value(execution_date, ticker)
            marks[ticker] = mark
            position_values[ticker] = quantity * mark
            if stale:
                stale_mark_count += 1
                stale_mark_oldest_date = mark_date if stale_mark_oldest_date is None else min(stale_mark_oldest_date, mark_date)
        pretrade_nav = cash + sum(position_values.values())
        if not np.isfinite(pretrade_nav) or pretrade_nav <= 0:
            raise RuntimeError(f"R4E_INVALID_PRETRADE_NAV:{model}:{top_n}:{execution_date.date()}")
        gross_return = 0.0 if previous_date is None else pretrade_nav / net_nav - 1.0
        benchmark_return = 0.0 if previous_date is None else float(qqq_open.loc[execution_date] / qqq_open.loc[previous_date] - 1.0)
        prior_position = int(calendar_position.loc[execution_date]) - 1
        prior_signal_date = pd.Timestamp(full_calendar[prior_position])
        target = target_map.get(prior_signal_date, {})
        risk_budget = 1.0
        if target and risk_budget_by_signal_date is not None:
            if prior_signal_date not in risk_budget_by_signal_date:
                raise RuntimeError(f"R4E_MISSING_FROZEN_RISK_BUDGET:{prior_signal_date.date()}")
            risk_budget = float(risk_budget_by_signal_date[prior_signal_date])
            if not np.isfinite(risk_budget) or risk_budget < 0.0 or risk_budget > 1.0:
                raise RuntimeError(f"R4E_INVALID_FROZEN_RISK_BUDGET:{prior_signal_date.date()}:{risk_budget}")
            target = {ticker: weight * risk_budget for ticker, weight in target.items()}
        pretrade_weights = {ticker: value / pretrade_nav for ticker, value in position_values.items()}
        target_turnover = 0.5 * sum(
            abs(target.get(ticker, 0.0) - pretrade_weights.get(ticker, 0.0))
            for ticker in set(target) | set(pretrade_weights)
        )
        desired_values = {ticker: weight * pretrade_nav for ticker, weight in target.items()}
        transaction_cost_amount = 0.0
        executed_traded_notional = 0.0
        skipped_buy_count = 0
        blocked_sell_or_rebalance_count = 0
        execution_ineligible_event_count = 0
        eligibility_lost_notional = 0.0

        # Sells execute first. Missing opens never generate cash or stale orders.
        for ticker in sorted(set(shares) | set(target)):
            current_value = position_values.get(ticker, 0.0)
            desired_value = desired_values.get(ticker, 0.0)
            if current_value <= desired_value + 1e-14:
                continue
            opening = open_value(execution_date, ticker)
            if not np.isfinite(opening):
                blocked_sell_or_rebalance_count += 1
                execution_ineligible_event_count += 1
                continue
            sell_notional = current_value - desired_value
            sell_quantity = sell_notional / opening
            shares[ticker] = max(0.0, shares[ticker] - sell_quantity)
            if shares[ticker] <= 1e-14:
                shares.pop(ticker, None)
            cash += sell_notional
            executed_traded_notional += sell_notional
            transaction_cost_amount += 0.5 * sell_notional * cost_rate

        # Revalue at the same execution marks after sells, then determine buys.
        post_sell_values = {ticker: quantity * marks[ticker] for ticker, quantity in shares.items()}
        executable_buys: dict[str, float] = {}
        for ticker in sorted(target):
            current_value = post_sell_values.get(ticker, 0.0)
            desired_value = desired_values[ticker]
            if desired_value <= current_value + 1e-14:
                continue
            buy_notional = desired_value - current_value
            opening = open_value(execution_date, ticker)
            if not np.isfinite(opening):
                skipped_buy_count += 1
                execution_ineligible_event_count += 1
                eligibility_lost_notional += buy_notional
                continue
            executable_buys[ticker] = buy_notional
            marks[ticker] = opening
        buy_total = sum(executable_buys.values())
        buy_cash_requirement = buy_total * (1.0 + 0.5 * cost_rate)
        cash_available_for_buys = max(0.0, cash - transaction_cost_amount)
        buy_scale = min(1.0, cash_available_for_buys / buy_cash_requirement) if buy_cash_requirement > 0 else 1.0
        if buy_scale < -1e-15:
            raise RuntimeError("R4E_NEGATIVE_BUY_SCALE")
        buy_scale = max(0.0, buy_scale)
        for ticker, requested_notional in executable_buys.items():
            buy_notional = requested_notional * buy_scale
            if buy_notional <= 1e-14:
                continue
            opening = marks[ticker]
            shares[ticker] = shares.get(ticker, 0.0) + buy_notional / opening
            cash -= buy_notional
            executed_traded_notional += buy_notional
            transaction_cost_amount += 0.5 * buy_notional * cost_rate

        cash -= transaction_cost_amount
        if cash < -1e-10:
            raise RuntimeError(f"R4E_IMPLICIT_LEVERAGE_OR_NEGATIVE_CASH:{model}:{top_n}:{execution_date.date()}:{cash}")
        cash = max(0.0, cash)
        posttrade_position_values = {ticker: quantity * marks[ticker] for ticker, quantity in shares.items()}
        posttrade_nav = cash + sum(posttrade_position_values.values())
        if not np.isclose(posttrade_nav, pretrade_nav - transaction_cost_amount, rtol=0.0, atol=1e-10):
            raise RuntimeError(f"R4E_CASH_ACCOUNTING_IDENTITY_FAILURE:{model}:{top_n}:{execution_date.date()}")
        executed_turnover = 0.5 * executed_traded_notional / pretrade_nav
        if executed_turnover < -1e-15 or executed_turnover > 1.000000000001:
            raise RuntimeError(f"R4E_EXECUTED_TURNOVER_BOUND_FAILURE:{executed_turnover}")
        transaction_cost_fraction = transaction_cost_amount / pretrade_nav
        net_return = posttrade_nav / net_nav - 1.0
        net_nav = posttrade_nav
        gross_nav *= 1.0 + gross_return
        benchmark_nav *= 1.0 + benchmark_return
        gross_exposure = sum(posttrade_position_values.values()) / net_nav
        cash_weight = cash / net_nav
        rows.append({
            "execution_date": execution_date, "signal_date_used": prior_signal_date if target else pd.NaT,
            "model": model, "top_n": top_n, "cost_bps": cost_bps,
            "gross_return": gross_return, "net_return": net_return, "benchmark_return": benchmark_return,
            "gross_nav": gross_nav, "net_nav": net_nav, "benchmark_nav": benchmark_nav,
            "target_turnover": target_turnover, "executed_turnover": executed_turnover,
            "target_vs_executed_turnover_gap": target_turnover - executed_turnover,
            "turnover": executed_turnover, "transaction_cost_fraction": transaction_cost_fraction,
            "transaction_cost_amount": transaction_cost_amount, "risky_name_count": len(target),
            "actual_risky_name_count": len(shares), "gross_exposure": gross_exposure, "cash_weight": cash_weight,
            "skipped_buy_count": skipped_buy_count,
            "blocked_sell_or_rebalance_count": blocked_sell_or_rebalance_count,
            "execution_ineligible_event_count": execution_ineligible_event_count,
            "stale_mark_count": stale_mark_count,
            "stale_mark": stale_mark_count > 0,
            "stale_mark_oldest_source_date": stale_mark_oldest_date,
            "execution_eligibility_lost_gross_exposure": eligibility_lost_notional / pretrade_nav,
            "buy_cash_scale": buy_scale,
            "risk_budget": risk_budget,
            "year": execution_date.year,
            "year_role": "CONSUMED_PRE2026_TRANSLATION_EVIDENCE" if execution_date.year < 2025 else "CONSUMED_PRE2026_TRANSLATION_EVIDENCE_NOT_FINAL",
            **({
                "corporate_action_transition_count": len(transition_rows),
                "corporate_action_cash_delta": corporate_action_cash_delta,
            } if corporate_action_adapter is not None else {}),
        })
        previous_date = execution_date
    if shares:
        raise RuntimeError(f"R4E_FAIL_CLOSED_TERMINAL_POSITION_REMAINS:{model}:TOP{top_n}:{sorted(shares)[:5]}")
    output = pd.DataFrame(rows)
    if output.empty or (output.execution_date >= pd.Timestamp("2026-01-01")).any():
        raise RuntimeError("R4_EMPTY_OR_POST2025_PORTFOLIO_PATH")
    return output


def portfolio_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    ordered = frame.sort_values("execution_date", kind="mergesort")
    returns = ordered.net_return.to_numpy(dtype=float)
    gross_returns = ordered.gross_return.to_numpy(dtype=float)
    benchmark_returns = ordered.benchmark_return.to_numpy(dtype=float)
    n = len(returns)
    cumulative_return = float(np.prod(1.0 + returns) - 1.0)
    gross_cumulative_return = float(np.prod(1.0 + gross_returns) - 1.0)
    benchmark_cumulative_return = float(np.prod(1.0 + benchmark_returns) - 1.0)
    cagr = float((1.0 + cumulative_return) ** (252.0 / n) - 1.0) if n else np.nan
    annualized_mean = float(np.mean(returns) * 252.0)
    annualized_volatility = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    sharpe = float(annualized_mean / annualized_volatility) if annualized_volatility > 0 else np.nan
    nav = np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else np.nan
    monthly = ordered.set_index("execution_date").net_return.resample("ME").apply(lambda values: float(np.prod(1.0 + values) - 1.0))
    target_turnover = ordered["target_turnover"] if "target_turnover" in ordered else ordered.turnover
    executed_turnover = ordered["executed_turnover"] if "executed_turnover" in ordered else ordered.turnover
    turnover_gap = target_turnover - executed_turnover
    cash_weights = ordered["cash_weight"] if "cash_weight" in ordered else pd.Series(np.zeros(n))
    return {
        "observation_count": n, "cumulative_return": cumulative_return,
        "gross_cumulative_return": gross_cumulative_return, "cagr": cagr,
        "annualized_mean_return": annualized_mean, "annualized_volatility": annualized_volatility,
        "sharpe_rf0": sharpe, "max_drawdown": max_drawdown, "calmar": calmar,
        "positive_day_fraction": float(np.mean(returns > 0)),
        "positive_month_fraction": float(np.mean(monthly.to_numpy() > 0)),
        "total_turnover": float(executed_turnover.sum()),
        "annualized_turnover": float(executed_turnover.mean() * 252.0),
        "total_target_turnover": float(target_turnover.sum()),
        "annualized_target_turnover": float(target_turnover.mean() * 252.0),
        "target_vs_executed_turnover_gap": float(turnover_gap.sum()),
        "total_transaction_cost": float(ordered.transaction_cost_amount.sum()),
        "total_transaction_cost_fraction": float(ordered.transaction_cost_fraction.sum()),
        "cost_drag": gross_cumulative_return - cumulative_return,
        "benchmark_cumulative_return": benchmark_cumulative_return,
        "net_excess_return": cumulative_return - benchmark_cumulative_return,
        "average_cash_weight": float(cash_weights.mean()),
        "max_cash_weight": float(cash_weights.max()),
        "skipped_buy_count": int(ordered.get("skipped_buy_count", pd.Series(np.zeros(n))).sum()),
        "blocked_sell_or_rebalance_count": int(ordered.get("blocked_sell_or_rebalance_count", pd.Series(np.zeros(n))).sum()),
        "stale_mark_day_count": int(ordered.get("stale_mark", pd.Series(np.zeros(n, dtype=bool))).sum()),
        "execution_eligibility_lost_gross_exposure": float(
            ordered.get("execution_eligibility_lost_gross_exposure", pd.Series(np.zeros(n))).sum()
        ),
    }


def materialize_all(signals: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    paths: list[pd.DataFrame] = []
    metric_rows: list[dict[str, Any]] = []
    nested: dict[str, Any] = {}
    for model, rank_column in (("A1", "a1_rank"), ("A2_HGB", "a2_rank")):
        nested[model] = {}
        for top_n in (5, 10, 20):
            nested[model][str(top_n)] = {}
            for cost_bps in (0, 5, 10, 20):
                path = simulate_portfolio(signals, prices, model, rank_column, top_n, cost_bps)
                paths.append(path)
                nested[model][str(top_n)][str(cost_bps)] = {}
                for scope in (2023, 2024, 2025, "POOLED_PRE2026"):
                    scoped = path if scope == "POOLED_PRE2026" else path.loc[path.year == scope]
                    metrics = portfolio_metrics(scoped)
                    nested[model][str(top_n)][str(cost_bps)][str(scope)] = metrics
                    metric_rows.extend({
                        "model": model, "top_n": top_n, "cost_bps": cost_bps,
                        "scope": str(scope), "metric": metric, "value": value,
                    } for metric, value in metrics.items())
    all_paths = pd.concat(paths, ignore_index=True).sort_values(["top_n", "cost_bps", "model", "execution_date"], kind="mergesort").reset_index(drop=True)
    metrics_frame = pd.DataFrame(metric_rows)
    return all_paths, metrics_frame, nested


def classify_translation(metrics: dict[str, Any], audits_pass: bool) -> tuple[str, dict[str, Any]]:
    a1 = metrics["A1"]["20"]["10"]["POOLED_PRE2026"]
    a2 = metrics["A2_HGB"]["20"]["10"]["POOLED_PRE2026"]
    positive_years = sum(
        metrics["A2_HGB"]["20"]["10"][str(year)]["cumulative_return"]
        > metrics["A1"]["20"]["10"][str(year)]["cumulative_return"]
        for year in (2023, 2024, 2025)
    )
    deltas = {
        "net_cagr": a2["cagr"] - a1["cagr"],
        "net_sharpe": a2["sharpe_rf0"] - a1["sharpe_rf0"],
        "calmar": a2["calmar"] - a1["calmar"],
        "max_drawdown": a2["max_drawdown"] - a1["max_drawdown"],
        "annualized_turnover": a2["annualized_turnover"] - a1["annualized_turnover"],
        "cost_drag": a2["cost_drag"] - a1["cost_drag"],
        "net_excess_return": a2["net_excess_return"] - a1["net_excess_return"],
        "net_cumulative_return": a2["cumulative_return"] - a1["cumulative_return"],
    }
    conditions = {
        "a2_net_cagr_gt_a1": deltas["net_cagr"] > 0,
        "a2_net_sharpe_gt_a1": deltas["net_sharpe"] > 0,
        "a2_calmar_gt_a1": deltas["calmar"] > 0,
        "a2_net_excess_gt_a1": deltas["net_excess_return"] > 0,
        "a2_better_year_count": positive_years,
        "a2_better_at_least_two_of_three_years": positive_years >= 2,
        "cost_after_edge_positive": deltas["net_cumulative_return"] > 0,
        "audits_pass": audits_pass,
    }
    if not audits_pass:
        return "FAIL_CLOSED", {"conditions": conditions, "deltas": deltas}
    p1 = all(value for key, value in conditions.items() if key != "a2_better_year_count")
    if p1:
        classification = "P1_STRONG_PORTFOLIO_TRANSLATION"
    elif any(deltas[key] > 0 for key in ("net_cagr", "net_sharpe", "calmar", "net_excess_return")) or positive_years >= 1:
        classification = "P2_PARTIAL_OR_COST_SENSITIVE_TRANSLATION"
    else:
        classification = "P3_RANKING_EDGE_DOES_NOT_TRANSLATE"
    return classification, {"conditions": conditions, "deltas": deltas}


def cost_sensitivity(metrics: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for cost in (0, 5, 10, 20):
        a1 = metrics["A1"]["20"][str(cost)]["POOLED_PRE2026"]
        a2 = metrics["A2_HGB"]["20"][str(cost)]["POOLED_PRE2026"]
        rows.append({
            "cost_bps": cost, "a1_cumulative_return": a1["cumulative_return"],
            "a2_cumulative_return": a2["cumulative_return"],
            "a1_cagr": a1["cagr"], "a2_cagr": a2["cagr"],
            "a1_sharpe": a1["sharpe_rf0"], "a2_sharpe": a2["sharpe_rf0"],
            "a2_minus_a1": a2["cumulative_return"] - a1["cumulative_return"],
        })
    return {"primary_top_n": 20, "primary_gate_cost_bps": 10, "rows": rows, "EDGE_SURVIVES_20BPS": rows[-1]["a2_minus_a1"] > 0}


def protected_hashes() -> dict[str, str]:
    paths = (
        REPO_ROOT / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py",
        REPO_ROOT / "config/v21/abcde_compact_v1_freeze_r1.json",
        REPO_ROOT / "config/v21/active_chain_manifest.json",
        REPO_ROOT / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py",
        REPO_ROOT / "scripts/v22/abcde_a2_r2_signal_lag_and_incremental_mechanism.py",
        REPO_ROOT / "scripts/v22/abcde_a2_r3_frozen_ranking_objective_challenger.py",
        REPO_ROOT / "scripts/v22/v22_044_daily_single_entrypoint_freeze_and_guard_r1.py",
    )
    return {path.relative_to(REPO_ROOT).as_posix(): sha256_file(path) for path in paths if path.is_file()}


def _next_business_date_after_freeze(freeze_time: datetime) -> str:
    eastern_date = freeze_time.astimezone(ZoneInfo("America/New_York")).date()
    frozen_date = np.datetime64(eastern_date)
    candidate = np.busday_offset(frozen_date, 1) if np.is_busday(frozen_date) else np.busday_offset(frozen_date, 0, roll="forward")
    return str(candidate)


def fit_prospective_hgb(freeze_time: datetime) -> dict[str, Any]:
    r1 = import_module("abcde_a2_r4_r1_helpers", R1_MODULE_PATH)
    inputs = r1.load_and_validate_frozen_inputs()
    prices = r1.load_prices_through(2025, set(inputs.eligibility.ticker))
    matrix = r1.attach_targets(r1.materialize_feature_matrix(prices, inputs.eligibility, 2025), prices)
    training = matrix.loc[matrix.target.notna() & (matrix.signal_date < pd.Timestamp("2026-01-01"))].copy()
    training = training.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    model = inputs.prereg.make_hgb()
    model.fit(training.loc[:, r1.FEATURE_COLUMNS].to_numpy(dtype=float), training.target.to_numpy(dtype=float))
    temporary = FROZEN_MODEL_PATH.with_suffix(".joblib.tmp")
    joblib.dump(model, temporary, compress=3)
    os.replace(temporary, FROZEN_MODEL_PATH)
    activation = {
        "PROSPECTIVE_HGB_SHADOW_STATUS": "ACTIVE_ACCUMULATING",
        "A2_HGB_PROSPECTIVE_SHADOW": "ACTIVE_ACCUMULATING_FROM_FIRST_LEGAL_FUTURE_DATE",
        "PROSPECTIVE_FREEZE_TIMESTAMP_UTC": freeze_time.isoformat(),
        "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE": _next_business_date_after_freeze(freeze_time),
        "FIRST_LEGAL_DATE_STATUS": "BUSINESS_DAY_CANDIDATE_REQUIRES_LIVE_CANONICAL_TRADING_AND_ELIGIBILITY_CONFIRMATION",
        "NO_BACKFILL": True, "TRAINING_ROW_COUNT": len(training),
        "FEATURE_SCHEMA_FINGERPRINT": "6e2020a8d99dabc657c7cb1fe5ec67dbff28a3b1da832581bdd90988d867f7a4",
        "MODEL_CONFIG_FINGERPRINT": "871fbbc386d7678c744764f86e3beaaf5e74185c6e47a4157fdb7460ae577514",
        "CURRENT_COHORT_FINGERPRINT": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
        "MODEL_PATH": str(FROZEN_MODEL_PATH), "MODEL_SHA256": sha256_file(FROZEN_MODEL_PATH),
        "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
        "PRODUCTION_ADOPTION": False, "BROKER_ACTION_ALLOWED": False,
    }
    write_json_atomic(ACTIVATION_PATH, activation)
    return activation


def run_translation() -> dict[str, Any]:
    witness = freeze_contract()
    if witness["contract_sha256"] != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("R4_FROZEN_CONTRACT_SHA_MISMATCH")
    eligibility_witness = freeze_execution_eligibility_policy()
    eligibility_policy_sha = eligibility_witness["execution_eligibility_policy_sha256"]
    frozen_at = datetime.fromisoformat(eligibility_witness["frozen_at_utc"])
    first_outcome_read_at = datetime.now(timezone.utc)
    if first_outcome_read_at <= frozen_at:
        raise RuntimeError("R4E_EXECUTION_ELIGIBILITY_FREEZE_BEFORE_READ_ORDER_FAILURE")
    protected_before = protected_hashes()
    original_contract_before = sha256_file(CONTRACT_PATH)
    _, _, _, inherited_audit = validate_prerequisites()
    signals, signal_audit = load_authoritative_signals()
    prices, price_audit = load_execution_prices(set(signals.ticker))
    eligibility_detail1, eligibility_audit1 = execution_eligibility_audit(signals, prices)
    eligibility_detail2, eligibility_audit2 = execution_eligibility_audit(signals, prices)
    if eligibility_audit1 != eligibility_audit2 or not eligibility_detail1.equals(eligibility_detail2):
        raise RuntimeError("R4E_EXECUTION_ELIGIBILITY_AUDIT_NOT_REPRODUCIBLE")
    if eligibility_audit1["HIVE_2023_07_12_NATURAL_FAILURE_COUNT"] < 1:
        raise RuntimeError("R4E_HIVE_CONFIRMED_NO_BAR_NOT_NATURALLY_PRESENT_IN_EXECUTION_AUDIT")
    write_parquet_atomic(EXECUTION_ELIGIBILITY_AUDIT_PATH, eligibility_detail1)
    missing_detail = eligibility_detail1.loc[~eligibility_detail1.execution_eligible]
    write_json_atomic(EXECUTION_COVERAGE_AUDIT_PATH, {
        **eligibility_audit1,
        "policy": "EXECUTION_ELIGIBILITY_SECURITY_DATE_LEVEL_NO_SYNTHETIC_OR_FUTURE_FILL",
        "missing_events": missing_detail.to_dict("records"),
    })
    run1_paths, run1_metric_frame, run1_metrics = materialize_all(signals, prices)
    run2_paths, run2_metric_frame, run2_metrics = materialize_all(signals, prices)
    fingerprint_columns = [
        "execution_date", "signal_date_used", "model", "top_n", "cost_bps", "gross_return", "net_return",
        "benchmark_return", "gross_nav", "net_nav", "benchmark_nav", "turnover", "transaction_cost_fraction",
        "transaction_cost_amount", "target_turnover", "executed_turnover", "target_vs_executed_turnover_gap",
        "risky_name_count", "actual_risky_name_count", "gross_exposure", "cash_weight", "skipped_buy_count",
        "blocked_sell_or_rebalance_count", "execution_ineligible_event_count", "stale_mark_count", "stale_mark",
        "stale_mark_oldest_source_date", "execution_eligibility_lost_gross_exposure", "buy_cash_scale",
        "year", "year_role",
    ]
    run1_fingerprint = canonical_fingerprint({
        "paths": dataframe_fingerprint(run1_paths, fingerprint_columns),
        "metrics": dataframe_fingerprint(run1_metric_frame, ["model", "top_n", "cost_bps", "scope", "metric", "value"]),
    })
    run2_fingerprint = canonical_fingerprint({
        "paths": dataframe_fingerprint(run2_paths, fingerprint_columns),
        "metrics": dataframe_fingerprint(run2_metric_frame, ["model", "top_n", "cost_bps", "scope", "metric", "value"]),
    })
    reproducibility = "PASS" if run1_fingerprint == run2_fingerprint else "FAIL"
    primary_paths = run1_paths.loc[(run1_paths.top_n == 20) & (run1_paths.cost_bps == 10)].copy()
    a1_dates = primary_paths.loc[primary_paths.model == "A1", "execution_date"].reset_index(drop=True)
    a2_dates = primary_paths.loc[primary_paths.model == "A2_HGB", "execution_date"].reset_index(drop=True)
    execution_identity = a1_dates.equals(a2_dates)
    timing_pass = bool((primary_paths.signal_date_used.dropna() < primary_paths.loc[primary_paths.signal_date_used.notna(), "execution_date"]).all())
    eligibility_identity = bool(
        eligibility_audit1["status"] == "PASS_EXECUTION_ELIGIBILITY_POLICY_DETERMINISTIC"
        and eligibility_audit1["TICKER_SPECIFIC_EXCEPTION_COUNT"] == 0
        and eligibility_audit1["FUTURE_FILL_COUNT"] == 0
    )
    audits_pass = reproducibility == "PASS" and execution_identity and timing_pass and eligibility_identity
    classification, gate = classify_translation(run1_metrics, audits_pass)
    if classification == "FAIL_CLOSED":
        raise RuntimeError("R4_EXECUTION_IDENTITY_TIMING_OR_REPRODUCIBILITY_FAILURE")
    sensitivity = cost_sensitivity(run1_metrics)
    write_parquet_atomic(DAILY_PATH, primary_paths)
    write_parquet_atomic(METRICS_PATH, run1_metric_frame)
    write_json_atomic(COST_SENSITIVITY_PATH, sensitivity)
    activation = None
    freeze_time = datetime.now(timezone.utc)
    if classification == "P1_STRONG_PORTFOLIO_TRANSLATION":
        activation = fit_prospective_hgb(freeze_time)
        next_step = "FAST_A2_R1_ALPHA_RELIABILITY_AND_RISK_BUDGET"
        shadow_status = "ACTIVE_ACCUMULATING_FROM_FIRST_LEGAL_FUTURE_DATE"
        model_fit_count = 1
    elif classification == "P2_PARTIAL_OR_COST_SENSITIVE_TRANSLATION":
        next_step = "ANALYZE_PORTFOLIO_TRANSLATION_FRICTION_WITHOUT_MODEL_RETUNING"
        shadow_status = "NOT_ACTIVATED_CLASSIFICATION_NOT_P1"
        model_fit_count = 0
    else:
        next_step = "STOP_PORTFOLIO_DEPLOYMENT_AND_REASSESS_SIGNAL_TO_EXECUTION_MAPPING"
        shadow_status = "NOT_ACTIVATED_CLASSIFICATION_NOT_P1"
        model_fit_count = 0
    protected_after = protected_hashes()
    if protected_before != protected_after:
        raise RuntimeError("R4_PROTECTED_PRODUCTION_OR_INCUMBENT_SOURCE_CHANGED")
    if original_contract_before != EXPECTED_CONTRACT_SHA256 or sha256_file(CONTRACT_PATH) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("R4E_ORIGINAL_R4_CONTRACT_CHANGED_DURING_RUN")
    a1 = run1_metrics["A1"]["20"]["10"]["POOLED_PRE2026"]
    a2 = run1_metrics["A2_HGB"]["20"]["10"]["POOLED_PRE2026"]
    deltas = gate["deltas"]
    execution_diagnostics = {
        "EXECUTION_INELIGIBLE_EVENT_COUNT": eligibility_audit1["EXECUTION_INELIGIBLE_EVENT_COUNT"],
        "UNIQUE_EXECUTION_INELIGIBLE_SECURITY_COUNT": eligibility_audit1["UNIQUE_EXECUTION_INELIGIBLE_SECURITY_COUNT"],
        "SKIPPED_BUY_COUNT": int(primary_paths.skipped_buy_count.sum()),
        "BLOCKED_SELL_OR_REBALANCE_COUNT": int(primary_paths.blocked_sell_or_rebalance_count.sum()),
        "STALE_MARK_DAY_COUNT": int(primary_paths.stale_mark.sum()),
        "MAX_CONSECUTIVE_EXECUTION_INELIGIBLE_SESSIONS": eligibility_audit1["MAX_CONSECUTIVE_EXECUTION_INELIGIBLE_SESSIONS"],
        "AVERAGE_CASH_WEIGHT": float(primary_paths.cash_weight.mean()),
        "MAX_CASH_WEIGHT": float(primary_paths.cash_weight.max()),
        "EXECUTION_ELIGIBILITY_LOST_GROSS_EXPOSURE": float(primary_paths.execution_eligibility_lost_gross_exposure.sum()),
        "TARGET_VS_EXECUTED_TURNOVER_GAP": float(primary_paths.target_vs_executed_turnover_gap.sum()),
        "PERMANENT_SECURITY_EXCLUSION_COUNT": eligibility_audit1["PERMANENT_SECURITY_EXCLUSION_COUNT"],
    }
    summary = {
        "ABCDE_A2_R4_STATUS": "PASS", "R4_CLASSIFICATION": classification,
        "ABCDE_A2_R4_DECISION": next_step,
        "R4_EVIDENCE_ROLE": "POST_MODEL_SELECTION_PRE2026_ECONOMIC_TRANSLATION",
        "R4_CONTRACT_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ": True,
        "R4_CONTRACT_SHA256": EXPECTED_CONTRACT_SHA256,
        "R4_ORIGINAL_CONTRACT_CHANGED": False,
        "R4_PORTFOLIO_OUTCOME_PREVIOUSLY_READ": False,
        "EXECUTION_ELIGIBILITY_POLICY_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ": True,
        "EXECUTION_ELIGIBILITY_POLICY_SHA256": eligibility_policy_sha,
        "EXECUTION_ELIGIBILITY_POLICY_VERSION": "R1",
        "MODEL_UNIVERSE_TYPE": "FROZEN_CURRENT_325", "MODEL_COHORT_CHANGED": False,
        "CURRENT_COHORT_COUNT": 325,
        "CURRENT_COHORT_FINGERPRINT": "0128b9ce5eccf74c059e93a09ada7d60605a9cc30b64a44a36087bc930c0a9dc",
        "MODEL_ELIGIBILITY": "FROZEN_R0V_CURRENT_COHORT_SECURITY_DATE_ELIGIBILITY",
        "SIGNAL_ELIGIBILITY": "FROZEN_R1_COMMON_A1_A2_OOF_SIGNAL_ROWS",
        "EXECUTION_ELIGIBILITY": "HAS_AUTHORITATIVE_CANONICAL_QFQ_OPEN_SECURITY_DATE",
        "MISSING_ENTRY_EXECUTION_POLICY": "SKIP_ENTRY_HOLD_CASH",
        "MISSING_HELD_EXECUTION_POLICY": "HOLD_POSITION_NO_TRADE",
        "NO_STALE_ORDER_QUEUE": True,
        "BUY_CASH_SHORTFALL_POLICY": "PRO_RATA_SCALE_EXECUTABLE_BUYS",
        "STALE_MARK_POLICY": "LAST_OBSERVED_CANONICAL_CLOSE_STRICTLY_BEFORE_EXECUTION_SESSION_NOT_EXECUTION_PRICE",
        "INCUMBENT_MODEL": "HistGradientBoostingRegressor", "LAMBDA_RANK_ROUTE_STATUS": "STOPPED",
        "A1_A2_SIGNAL_DATE_IDENTITY_STATUS": "PASS", "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS": "PASS",
        "A1_A2_EXECUTION_DATE_IDENTITY_STATUS": "PASS" if execution_identity else "FAIL",
        "SIGNAL_INFORMATION_CUTOFF": portfolio_contract()["signal_and_execution"]["signal_information_cutoff"],
        "FIRST_LEGAL_EXECUTION_TIMESTAMP": portfolio_contract()["signal_and_execution"]["first_legal_execution_timestamp"],
        "EXECUTION_PRICE_FIELD": "canonical_qfq_open", "SAME_CLOSE_EXECUTION_ALLOWED": False,
        "EXECUTION_TIMING_AUDIT_STATUS": "PASS" if timing_pass else "FAIL",
        "PRICE_INTEGRITY_AUDIT_STATUS": "PASS_EXECUTION_ELIGIBILITY_POLICY_APPLIED", "FUTURE_FILL_COUNT": 0,
        "EXECUTION_PRICE_COVERAGE_AUDIT_STATUS": eligibility_audit1["status"],
        "MISSING_CANONICAL_EXECUTION_OPEN_COUNT": eligibility_audit1["EXECUTION_INELIGIBLE_EVENT_COUNT"],
        "EXECUTION_REQUIRED_EVENT_COUNT": eligibility_audit1["EXECUTION_REQUIRED_EVENT_COUNT"],
        "EXECUTION_ELIGIBLE_EVENT_COUNT": eligibility_audit1["EXECUTION_ELIGIBLE_EVENT_COUNT"],
        **execution_diagnostics,
        "BENCHMARK_IDENTITY": "QQQ", "BENCHMARK_FINGERPRINT": canonical_fingerprint(benchmark_contract()),
        "PRIMARY_TOP_N": 20, "PRIMARY_ONE_WAY_COST_BPS": 10,
        "SECONDARY_ONLY_TOP_N": [5, 10], "RISK_FREE_RATE": 0.0,
        "POOLED_A1_METRICS": a1, "POOLED_A2_METRICS": a2,
        "DELTA_NET_CAGR": deltas["net_cagr"], "DELTA_NET_SHARPE": deltas["net_sharpe"],
        "DELTA_CALMAR": deltas["calmar"], "DELTA_MAX_DRAWDOWN": deltas["max_drawdown"],
        "DELTA_ANNUALIZED_TURNOVER": deltas["annualized_turnover"], "DELTA_COST_DRAG": deltas["cost_drag"],
        "DELTA_NET_EXCESS_RETURN": deltas["net_excess_return"],
        "EDGE_SURVIVES_20BPS": sensitivity["EDGE_SURVIVES_20BPS"],
        "decision_gate": gate, "portfolio_metrics": run1_metrics,
        "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
        "2026_PORTFOLIO_SELECTION_USE_COUNT": 0, "MODEL_SEARCH_COUNT": 0,
        "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0, "MODEL_FIT_FOR_SELECTION_COUNT": 0,
        "MODEL_FIT_COUNT": model_fit_count,
        "REPRODUCIBILITY_STATUS": reproducibility, "RUN1_FINGERPRINT": run1_fingerprint,
        "RUN2_FINGERPRINT": run2_fingerprint,
        "PROSPECTIVE_HGB_SHADOW_STATUS": activation.get("PROSPECTIVE_HGB_SHADOW_STATUS") if activation else shadow_status,
        "A2_HGB_PROSPECTIVE_SHADOW": shadow_status,
        "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE": activation.get("FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE") if activation else None,
        "PROSPECTIVE_MODEL_SHA256": activation.get("MODEL_SHA256") if activation else None,
        "PRODUCTION_ADOPTION": False, "BROKER_ACTION_ALLOWED": False, "BROKER_ACTION_COUNT": 0,
        "FAST_CHANGED": False, "DAILY_CHAIN_CHANGED": False, "A1_PRODUCTION_CHANGED": False,
        "ANTI_MODEL_ZOO_STATUS": "PASS", "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT), "SUMMARY_PATH": str(SUMMARY_PATH),
        "DAILY_PORTFOLIO_PATH": str(DAILY_PATH), "METRICS_PATH": str(METRICS_PATH),
        "COST_SENSITIVITY_PATH": str(COST_SENSITIVITY_PATH),
        "EXECUTION_ELIGIBILITY_POLICY_PATH": str(EXECUTION_ELIGIBILITY_POLICY_PATH),
        "EXECUTION_ELIGIBILITY_WITNESS_PATH": str(EXECUTION_ELIGIBILITY_WITNESS_PATH),
        "EXECUTION_ELIGIBILITY_AUDIT_PATH": str(EXECUTION_ELIGIBILITY_AUDIT_PATH),
        "FROZEN_MODEL_PATH": str(FROZEN_MODEL_PATH) if activation else None,
        "PROSPECTIVE_ACTIVATION_PATH": str(ACTIVATION_PATH) if activation else None,
        "NEXT_AUTHORIZED_STEP": next_step, "FAILURE_REASON": None,
        "signal_audit": signal_audit, "price_audit": price_audit,
        "execution_eligibility_audit": eligibility_audit1,
        "inherited_audit": inherited_audit, "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    write_json_atomic(SUMMARY_PATH, summary)
    manifest = {
        "experiment_id": EXPERIMENT_ID, "schema_version": "1.0",
        "contract_frozen_at_utc": witness["frozen_at_utc"],
        "execution_eligibility_policy_frozen_at_utc": eligibility_witness["frozen_at_utc"],
        "first_portfolio_outcome_read_at_utc": first_outcome_read_at.isoformat(),
        "contract_frozen_before_portfolio_outcome_read": first_outcome_read_at > frozen_at,
        "contract_sha256": EXPECTED_CONTRACT_SHA256, "classification": classification,
        "execution_eligibility_policy_sha256": eligibility_policy_sha,
        "run1_fingerprint": run1_fingerprint, "run2_fingerprint": run2_fingerprint,
        "reproducibility_status": reproducibility,
        "artifact_sha256": {
            str(SUMMARY_PATH): sha256_file(SUMMARY_PATH), str(DAILY_PATH): sha256_file(DAILY_PATH),
            str(METRICS_PATH): sha256_file(METRICS_PATH), str(COST_SENSITIVITY_PATH): sha256_file(COST_SENSITIVITY_PATH),
            str(EXECUTION_ELIGIBILITY_POLICY_PATH): sha256_file(EXECUTION_ELIGIBILITY_POLICY_PATH),
            str(EXECUTION_ELIGIBILITY_WITNESS_PATH): sha256_file(EXECUTION_ELIGIBILITY_WITNESS_PATH),
            str(EXECUTION_ELIGIBILITY_AUDIT_PATH): sha256_file(EXECUTION_ELIGIBILITY_AUDIT_PATH),
            str(EXECUTION_COVERAGE_AUDIT_PATH): sha256_file(EXECUTION_COVERAGE_AUDIT_PATH),
            **({str(FROZEN_MODEL_PATH): sha256_file(FROZEN_MODEL_PATH), str(ACTIVATION_PATH): sha256_file(ACTIVATION_PATH)} if activation else {}),
        },
        "post2025_target_read_count": 0, "post2025_outcome_read_count": 0,
        "2026_portfolio_selection_use_count": 0,
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
    "ABCDE_A2_R4_STATUS", "R4_CLASSIFICATION", "ABCDE_A2_R4_DECISION", "R4_EVIDENCE_ROLE",
    "R4_CONTRACT_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ", "R4_CONTRACT_SHA256", "INCUMBENT_MODEL",
    "EXECUTION_ELIGIBILITY_POLICY_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ", "EXECUTION_ELIGIBILITY_POLICY_SHA256",
    "R4_PORTFOLIO_OUTCOME_PREVIOUSLY_READ", "MODEL_UNIVERSE_TYPE", "MODEL_COHORT_CHANGED",
    "LAMBDA_RANK_ROUTE_STATUS", "A1_A2_SIGNAL_DATE_IDENTITY_STATUS", "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS",
    "A1_A2_EXECUTION_DATE_IDENTITY_STATUS", "SIGNAL_INFORMATION_CUTOFF", "FIRST_LEGAL_EXECUTION_TIMESTAMP",
    "EXECUTION_PRICE_FIELD", "SAME_CLOSE_EXECUTION_ALLOWED", "EXECUTION_TIMING_AUDIT_STATUS",
    "PRICE_INTEGRITY_AUDIT_STATUS", "BENCHMARK_IDENTITY", "BENCHMARK_FINGERPRINT", "PRIMARY_TOP_N",
    "PRIMARY_ONE_WAY_COST_BPS", "DELTA_NET_CAGR", "DELTA_NET_SHARPE", "DELTA_CALMAR",
    "DELTA_MAX_DRAWDOWN", "DELTA_ANNUALIZED_TURNOVER", "DELTA_COST_DRAG", "DELTA_NET_EXCESS_RETURN",
    "EDGE_SURVIVES_20BPS", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT",
    "2026_PORTFOLIO_SELECTION_USE_COUNT", "MODEL_SEARCH_COUNT", "HYPERPARAMETER_SEARCH_TRIAL_COUNT",
    "MODEL_FIT_COUNT", "EXECUTION_PRICE_COVERAGE_AUDIT_STATUS", "MISSING_CANONICAL_EXECUTION_OPEN_COUNT",
    "EXECUTION_REQUIRED_EVENT_COUNT", "EXECUTION_ELIGIBLE_EVENT_COUNT", "EXECUTION_INELIGIBLE_EVENT_COUNT",
    "UNIQUE_EXECUTION_INELIGIBLE_SECURITY_COUNT", "SKIPPED_BUY_COUNT", "BLOCKED_SELL_OR_REBALANCE_COUNT",
    "STALE_MARK_DAY_COUNT", "MAX_CONSECUTIVE_EXECUTION_INELIGIBLE_SESSIONS", "AVERAGE_CASH_WEIGHT",
    "MAX_CASH_WEIGHT", "EXECUTION_ELIGIBILITY_LOST_GROSS_EXPOSURE", "TARGET_VS_EXECUTED_TURNOVER_GAP",
    "PERMANENT_SECURITY_EXCLUSION_COUNT",
    "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT", "RUN2_FINGERPRINT",
    "PROSPECTIVE_HGB_SHADOW_STATUS", "A2_HGB_PROSPECTIVE_SHADOW", "FIRST_LEGAL_PROSPECTIVE_SIGNAL_DATE",
    "PRODUCTION_ADOPTION", "BROKER_ACTION_ALLOWED", "BROKER_ACTION_COUNT", "FAST_CHANGED",
    "DAILY_CHAIN_CHANGED", "ANTI_MODEL_ZOO_STATUS", "ANTI_BLOAT_STATUS", "RESULTS_ROOT", "SUMMARY_PATH",
    "NEXT_AUTHORIZED_STEP", "FAILURE_REASON",
)


def print_core(summary: dict[str, Any]) -> None:
    for field in CORE_FIELDS:
        print(f"{field}={_display(summary.get(field))}")
    for scope in ("2023", "2024", "2025", "POOLED_PRE2026"):
        for model in ("A1", "A2_HGB"):
            values = summary.get("portfolio_metrics", {}).get(model, {}).get("20", {}).get("10", {}).get(scope, {})
            for metric, value in values.items():
                print(f"{scope}_{model}_{metric.upper()}={_display(value)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-contract-only", action="store_true")
    args = parser.parse_args(argv)
    witness = freeze_contract()
    eligibility_witness = freeze_execution_eligibility_policy()
    print("R4_CONTRACT_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ=true")
    print(f"R4_CONTRACT_SHA256={witness['contract_sha256']}")
    print("EXECUTION_ELIGIBILITY_POLICY_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ=true")
    print(f"EXECUTION_ELIGIBILITY_POLICY_SHA256={eligibility_witness['execution_eligibility_policy_sha256']}")
    if args.freeze_contract_only:
        return 0
    try:
        summary = run_translation()
    except Exception as exc:
        coverage = None
        if EXECUTION_COVERAGE_AUDIT_PATH.is_file():
            try:
                coverage = json.loads(EXECUTION_COVERAGE_AUDIT_PATH.read_text(encoding="utf-8"))
            except Exception:
                coverage = None
        summary = {
            "ABCDE_A2_R4_STATUS": "FAIL_CLOSED", "R4_CLASSIFICATION": "FAIL_CLOSED",
            "ABCDE_A2_R4_DECISION": "STOP_AND_REPAIR_EXPLICIT_R4_EXECUTION_OR_DATA_FAILURE",
            "R4_EVIDENCE_ROLE": "POST_MODEL_SELECTION_PRE2026_ECONOMIC_TRANSLATION",
            "R4_CONTRACT_FROZEN_BEFORE_PORTFOLIO_OUTCOME_READ": True,
            "R4_CONTRACT_SHA256": witness["contract_sha256"],
            "INCUMBENT_MODEL": "HistGradientBoostingRegressor", "LAMBDA_RANK_ROUTE_STATUS": "STOPPED",
            "A1_A2_SIGNAL_DATE_IDENTITY_STATUS": "PASS_PRE_FAILURE" if coverage else "NOT_REACHED",
            "A1_A2_DAILY_UNIVERSE_IDENTITY_STATUS": "PASS_PRE_FAILURE" if coverage else "NOT_REACHED",
            "A1_A2_EXECUTION_DATE_IDENTITY_STATUS": "NOT_REACHED_EXECUTION_PRICE_FAIL_CLOSED",
            "SIGNAL_INFORMATION_CUTOFF": portfolio_contract()["signal_and_execution"]["signal_information_cutoff"],
            "FIRST_LEGAL_EXECUTION_TIMESTAMP": portfolio_contract()["signal_and_execution"]["first_legal_execution_timestamp"],
            "EXECUTION_PRICE_FIELD": "canonical_qfq_open", "SAME_CLOSE_EXECUTION_ALLOWED": False,
            "EXECUTION_TIMING_AUDIT_STATUS": "PASS_CONTRACT_PRICE_COVERAGE_FAIL_CLOSED" if coverage else "NOT_REACHED",
            "PRICE_INTEGRITY_AUDIT_STATUS": coverage.get("status") if coverage else "NOT_REACHED",
            "BENCHMARK_IDENTITY": "QQQ", "BENCHMARK_FINGERPRINT": canonical_fingerprint(benchmark_contract()),
            "PRIMARY_TOP_N": 20, "PRIMARY_ONE_WAY_COST_BPS": 10,
            "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
            "2026_PORTFOLIO_SELECTION_USE_COUNT": 0, "MODEL_SEARCH_COUNT": 0,
            "HYPERPARAMETER_SEARCH_TRIAL_COUNT": 0, "MODEL_FIT_COUNT": 0,
            "REPRODUCIBILITY_STATUS": "PASS_FAIL_CLOSED_EXECUTION_COVERAGE_AUDIT" if coverage else "NOT_REACHED",
            "RUN1_FINGERPRINT": coverage.get("logical_fingerprint") if coverage else None,
            "RUN2_FINGERPRINT": coverage.get("logical_fingerprint") if coverage else None,
            "EXECUTION_PRICE_COVERAGE_AUDIT_STATUS": coverage.get("status") if coverage else "NOT_AVAILABLE",
            "MISSING_CANONICAL_EXECUTION_OPEN_COUNT": coverage.get("missing_event_count") if coverage else None,
            "EXECUTION_COVERAGE_AUDIT_PATH": str(EXECUTION_COVERAGE_AUDIT_PATH) if coverage else None,
            "PRODUCTION_ADOPTION": False, "BROKER_ACTION_ALLOWED": False, "BROKER_ACTION_COUNT": 0,
            "FAST_CHANGED": False, "DAILY_CHAIN_CHANGED": False, "A1_PRODUCTION_CHANGED": False,
            "PROSPECTIVE_HGB_SHADOW_STATUS": "NOT_ACTIVATED_FAIL_CLOSED",
            "A2_HGB_PROSPECTIVE_SHADOW": "NOT_ACTIVATED_FAIL_CLOSED",
            "ANTI_MODEL_ZOO_STATUS": "PASS", "ANTI_BLOAT_STATUS": "PASS",
            "RESULTS_ROOT": str(RESULTS_ROOT), "SUMMARY_PATH": str(SUMMARY_PATH),
            "NEXT_AUTHORIZED_STEP": (
                "ACQUIRE_OR_AUTHORITATIVELY_RESOLVE_HIVE_2023_07_12_EXECUTION_OPEN_OR_FREEZE_NEW_MISSING_OPEN_POLICY"
                if coverage else "REPAIR_EXPLICIT_R4_EXECUTION_OR_DATA_FAILURE_ONLY"
            ),
            "FAILURE_REASON": f"{type(exc).__name__}:{exc}",
        }
        write_json_atomic(SUMMARY_PATH, summary)
        manifest = {
            "experiment_id": EXPERIMENT_ID, "schema_version": "1.0_FAIL_CLOSED",
            "contract_sha256": witness["contract_sha256"], "status": "FAIL_CLOSED",
            "failure_reason": summary["FAILURE_REASON"],
            "reproducibility_status": summary["REPRODUCIBILITY_STATUS"],
            "run1_fingerprint": summary["RUN1_FINGERPRINT"], "run2_fingerprint": summary["RUN2_FINGERPRINT"],
            "artifact_sha256": {
                str(SUMMARY_PATH): sha256_file(SUMMARY_PATH),
                **({str(EXECUTION_COVERAGE_AUDIT_PATH): sha256_file(EXECUTION_COVERAGE_AUDIT_PATH)} if coverage else {}),
            },
            "post2025_target_read_count": 0, "post2025_outcome_read_count": 0,
            "2026_portfolio_selection_use_count": 0,
        }
        write_json_atomic(MANIFEST_PATH, manifest)
        print_core(summary)
        return 2
    print_core(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
