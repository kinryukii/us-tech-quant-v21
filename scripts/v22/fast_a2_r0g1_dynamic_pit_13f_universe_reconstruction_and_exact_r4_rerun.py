"""Fail-closed R0G1 orchestration for dynamic PIT 13F reconstruction.

The formal portfolio rerun is deliberately unavailable unless authoritative
SEC cache, dynamic security mapping, full price/features, and frozen fold model
artifacts all pass preflight.  A STOP run materializes only source/readiness
evidence; it never fabricates a universe, score, NAV, or economic metric.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v22 import pit_13f_reconstruction_r1 as pit

EXPERIMENT_ID = "FAST_A2_R0G1_DYNAMIC_PIT_13F_UNIVERSE_RECONSTRUCTION_AND_EXACT_R4_RERUN"
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
CACHE_ROOT = Path(r"D:\us-tech-quant-cache\sec_13f_r0g1")
LEGACY_CONFIG_PATH = REPO_ROOT / "config/v22/manager_master_list_r1.json"
CONFIG_PATH = LEGACY_CONFIG_PATH  # Compatibility alias for frozen R0G1 evidence.
SCRIPT_PATH = Path(__file__).resolve()
MODULE_PATH = REPO_ROOT / "scripts/v22/pit_13f_reconstruction_r1.py"
TEST_PATH = REPO_ROOT / "scripts/v22/test_fast_a2_r0g1_dynamic_pit_13f_universe_reconstruction_and_exact_r4_rerun.py"
R1_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R1_NONLINEAR_CROSS_SECTIONAL_MODELING")
R1_SUMMARY = R1_ROOT / "abcde_a2_r1_summary.json"
R1_OOF = R1_ROOT / "a2_r1_oof_predictions.parquet"
R1_FINAL_MODEL = R1_ROOT / "a2_r1_final_hgb.joblib"
PRICE_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
R0F1_ROOT = Path(r"D:\us-tech-quant-results\FAST_A2_R0F1_CORPORATE_ACTION_ACCOUNTING_REPAIR_AND_EXACT_R4_RERUN")
R0F1_POLICY = R0F1_ROOT / "corporate_action_accounting_policy_r1.json"
R4_ROOT = Path(r"D:\us-tech-quant-results\ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT")
EXECUTION_POLICY = R4_ROOT / "a2_r4_execution_eligibility_policy_r1.json"
EXPECTED_CA_POLICY_SHA256 = "0a52f513e4393fafd9ee2900bc2523f9afdca385457cd0e243994938b6f811bd"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(canonical_bytes(value) + b"\n")
    os.replace(temp, path)


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temp, compression="zstd")
    os.replace(temp, path)


def load_legacy_config() -> dict[str, Any]:
    config = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
    managers = config.get("managers", [])
    if config.get("classification") != "LEGACY_RESEARCH_ONLY" or config.get("active_authoritative") is not False:
        raise pit.Pit13FContractError("R0G1_30_MANAGER_CONFIG_MUST_REMAIN_LEGACY")
    if config.get("authoritative_for_holdings_ingestion") is not False:
        raise pit.Pit13FContractError("R0G1_LEGACY_CONFIG_CANNOT_DRIVE_HOLDINGS")
    if config.get("manager_count") != 30 or len(managers) != 30:
        raise pit.Pit13FContractError("MANAGER_MASTER_COUNT_NOT_30")
    ciks = [pit.normalized_cik(row["cik"]) for row in managers]
    if len(ciks) != len(set(ciks)):
        raise pit.Pit13FContractError("DUPLICATE_MANAGER_CIK")
    return config


def load_config() -> dict[str, Any]:
    """Compatibility name for the frozen legacy R0G1 stop audit only."""
    return load_legacy_config()


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def audit_local_sec_cache() -> dict[str, Any]:
    required = [CACHE_ROOT / "manager_13f_filing_manifest.parquet", CACHE_ROOT / "sec_13f_holdings.parquet"]
    present = [path for path in required if path.is_file()]
    result: dict[str, Any] = {
        "cache_root": str(CACHE_ROOT), "required_paths": [str(p) for p in required],
        "present_path_count": len(present), "bulk_machine_readable": len(present) == len(required),
        "sec_acquisition_mode": "LOCAL_VERIFIED_SEC_CACHE" if len(present) == len(required) else "UNAVAILABLE_NETWORK_POLICY_BLOCKED",
        "duplicate_accession_cache_count": 0, "status": "PASS" if len(present) == len(required) else "SEC_SOURCE_UNAVAILABLE",
    }
    if len(present) == len(required):
        manifest = pd.read_parquet(required[0])
        result["duplicate_accession_cache_count"] = pit.duplicated_accession_count(manifest)
        result["status"] = "PASS" if result["duplicate_accession_cache_count"] == 0 else "DUPLICATED_ACCESSION_CACHE"
    return result


def audit_score_and_feature_readiness() -> dict[str, Any]:
    oof = pd.read_parquet(R1_OOF, columns=["signal_date", "ticker", "split"])
    price_counts: dict[str, int] = {}
    price_union: set[str] = set()
    for year in range(2020, 2026):
        path = PRICE_ROOT / f"year={year}/prices.parquet"
        tickers = set(pd.read_parquet(path, columns=["ticker"]).ticker.astype(str).unique())
        price_counts[str(year)] = len(tickers)
        price_union.update(tickers)
    persisted_models = sorted(path.name for path in R1_ROOT.glob("*.joblib"))
    fold_models = [name for name in persisted_models if any(token in name.upper() for token in ("2023", "2024", "DEVELOPMENT", "CONFIRMATION", "FOLD"))]
    return {
        "oof_security_count": int(oof.ticker.nunique()), "oof_row_count": int(len(oof)),
        "oof_signal_date_count": int(pd.to_datetime(oof.signal_date).nunique()),
        "price_security_count_by_year": price_counts, "price_union_security_count": len(price_union),
        "current_static_universe_capability": 325, "requested_dynamic_universe_cap": 900,
        "persisted_model_files": persisted_models, "persisted_pre2025_fold_model_count": len(fold_models),
        "model_predict_call_count": 0, "model_fit_count": 0,
        "status": "FEATURE_COVERAGE_INSUFFICIENT",
        "blocking_reasons": [
            "DYNAMIC_13F_SECURITIES_CANNOT_BE_MAPPED_OR_COUNTED_WITHOUT_AUTHORITATIVE_HOLDINGS",
            "LOCAL_PRICE_FEATURE_HISTORY_IS_STATIC_325_COHORT_ONLY",
            "2023_AND_2024_FOLD_MODELS_NOT_PERSISTED_AND_REFIT_IS_FORBIDDEN",
        ],
    }


def build_oos_audit() -> tuple[pd.DataFrame, str, str]:
    summary = json.loads(R1_SUMMARY.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for stage_name, stage in sorted(summary["stage_metrics"].items(), key=lambda item: item[1]["year"]):
        split = stage["split_audit"]
        signal = pd.Timestamp(split["evaluation_first_trading_date"])
        target_maturity = pd.Timestamp(split["train_target_end_max"])
        training_end = pd.Timestamp(split["train_end"])
        status = pit.audit_target_maturity(signal, training_end, target_maturity)
        for model in ("A1", "A2_HGB"):
            model_artifact_persisted = model == "A1" or stage_name == "FINAL"
            rows.append({
                "signal_date": signal, "model": model, "model_version": f"R1_{stage_name}",
                "model_fit_timestamp": summary.get("PRE_FINAL_TIMESTAMP") if stage_name == "FINAL" else None,
                "model_training_end_date": training_end,
                "latest_training_target_maturity_date": target_maturity,
                "prediction_generated_timestamp_if_known": None,
                "strictly_pre_signal_training": training_end < signal,
                "target_maturity_pre_signal": target_maturity < signal,
                "split_oos_status": status,
                "fold_model_artifact_persisted": model_artifact_persisted,
                "dynamic_out_of_cohort_rescore_status": "READY" if model_artifact_persisted else "BLOCKED_FOLD_MODEL_NOT_PERSISTED",
                "independent_holdout": False, "consumed_pre2026_evidence": True,
            })
    frame = pd.DataFrame(rows)
    a1 = "PASS_SPLIT_PROVENANCE_DYNAMIC_RESCORE_BLOCKED_FEATURE_COVERAGE"
    a2 = "STOP_DYNAMIC_RESCORE_BLOCKED_PRE2025_FOLD_MODEL_ARTIFACTS_MISSING"
    return frame, a1, a2


def manager_contribution_stop_table(config: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([{
        "manager": row["manager_name"], "manager_cik": row["cik"],
        "historical_start_date": None, "historical_end_date": None, "filing_count": 0,
        "median_eligible_holdings": None, "unique_securities_contributed": None,
        "security_date_additions_to_raw_union": None, "security_date_additions_to_final_900": None,
        "top20_presence_count_A1": None, "top20_presence_count_A2": None,
        "status": "SEC_SOURCE_UNAVAILABLE_NOT_SILENTLY_OMITTED",
    } for row in config["managers"]])


def build_stop_result() -> dict[str, Any]:
    config = load_config()
    sec = audit_local_sec_cache()
    readiness = audit_score_and_feature_readiness()
    oos, a1_oos, a2_oos = build_oos_audit()
    ca_hash = sha256_file(R0F1_POLICY)
    if ca_hash != EXPECTED_CA_POLICY_SHA256:
        raise pit.Pit13FContractError("CORPORATE_ACTION_POLICY_CHANGED")
    manager_table = manager_contribution_stop_table(config)
    manifest = empty_frame(["manager", "CIK", "accession", "form_type", "report_period", "filed_date", "accepted_timestamp", "amendment_type", "source_url_or_sec_identifier", "local_cache_path", "sha256", "parse_status"])
    manifest["parse_status"] = manifest["parse_status"].astype("object")
    source_provenance = empty_frame(["security_id", "cusip", "ticker", "manager", "manager_cik", "accession", "accepted_timestamp", "source_sha256", "status"])
    blockers = [
        "NO_LOCAL_VERIFIED_SEC_13F_CACHE",
        "BULK_SEC_MACHINE_READABLE_ACQUISITION_BLOCKED_BY_ENVIRONMENT_NETWORK_POLICY",
        "NO_AUTHORITATIVE_HOLDINGS_MEANS_DYNAMIC_UNIVERSE_SIZE_AND_SCORE_COVERAGE_CANNOT_BE_MEASURED",
        *readiness["blocking_reasons"],
        "NO_CORRECTED_DYNAMIC_PORTFOLIO_OR_NAV_MATERIALIZED",
    ]
    audit_payload = {
        "manager_config_sha256": sha256_file(CONFIG_PATH), "sec_cache_audit": sec,
        "score_feature_readiness": readiness, "oos_rows": oos.astype(str).to_dict("records"),
        "corporate_action_policy_sha256": ca_hash,
        "execution_policy_sha256": sha256_file(EXECUTION_POLICY), "blockers": blockers,
    }
    fingerprint = pit.canonical_sha256(audit_payload)
    summary = {
        "FAST_A2_R0G1_STATUS": "STOP",
        "FAST_A2_R0G1_CLASSIFICATION": "E_INSUFFICIENT_PIT_13F_SOURCE_EVIDENCE",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_RESOLVE_13F_PIT_SOURCE_GAPS",
        "FAST_A2_R0G1_ANTI_BLOAT_STATUS": "PASS_STOPPED_WITHIN_HARD_CAP",
        "ANTI_BLOAT_STATUS": "PASS_STOPPED_WITHIN_HARD_CAP",
        "MANAGER_CONFIG_CLASSIFICATION": "LEGACY_RESEARCH_ONLY",
        "MANAGER_MASTER_COUNT": 30, "MAX_UNIVERSE_SIZE": 900,
        "PIT_13F_SOURCE_STATUS": sec["status"], "PIT_UNIVERSE_STATUS": "NOT_MATERIALIZED_FAIL_CLOSED",
        "A1_OOS_PROVENANCE_STATUS": a1_oos, "A2_OOS_PROVENANCE_STATUS": a2_oos,
        "MANAGER_WITH_HISTORICAL_FILING_COUNT": None, "MANAGER_WITHOUT_HISTORICAL_FILING_COUNT": None,
        "MANAGER_WITHOUT_LOCAL_VERIFIED_FILING_COUNT": 30,
        "MANAGER_PARSE_FAILURE_COUNT": 0, "TOTAL_13F_FILINGS_USED": 0, "TOTAL_AMENDMENTS_USED": 0,
        "SEC_ACQUISITION_MODE": sec["sec_acquisition_mode"], "BULK_MACHINE_READABLE": sec["bulk_machine_readable"],
        "BROWSER_FALLBACK_EVENT_COUNT": 1, "MANUAL_MANAGER_SEARCH_COUNT": 32,
        "MIN_ACTIVE_MANAGER_COUNT": None, "MEDIAN_ACTIVE_MANAGER_COUNT": None, "MAX_ACTIVE_MANAGER_COUNT": None,
        "MIN_RAW_UNION_SIZE": None, "MEDIAN_RAW_UNION_SIZE": None, "MAX_RAW_UNION_SIZE": None,
        "MIN_FINAL_UNIVERSE_SIZE": None, "MEDIAN_FINAL_UNIVERSE_SIZE": None, "MAX_FINAL_UNIVERSE_SIZE": None,
        "CAP_APPLIED_SESSION_COUNT": None, "CAP_APPLIED_SESSION_RATE": None,
        "UNIVERSE_CAP_MODEL_BLIND": True, "UNIVERSE_CAP_OUTCOME_BLIND": True,
        "PIT_UNIVERSE_SECURITY_COUNT": None, "SCORE_COVERED_SECURITY_COUNT": None, "SCORE_MISSING_SECURITY_COUNT": None,
        "OLD_STATIC_A2_NET_CUM_RETURN": 18.7515857683, "OLD_STATIC_A2_CAGR": 1.78880669426, "OLD_STATIC_A2_SHARPE": 2.21683278013,
        "DYNAMIC_PIT_A1_NET_CUM_RETURN": None, "DYNAMIC_PIT_A1_CAGR": None, "DYNAMIC_PIT_A1_SHARPE": None,
        "DYNAMIC_PIT_A2_NET_CUM_RETURN": None, "DYNAMIC_PIT_A2_CAGR": None, "DYNAMIC_PIT_A2_SHARPE": None,
        "DYNAMIC_PIT_NAV_RECONSTRUCTION_STATUS": "NOT_RUN_NO_VALID_DYNAMIC_UNIVERSE",
        "NAV_RECONSTRUCTION_MAX_ABS_ERROR": None, "NAV_RECONSTRUCTION_MAX_REL_ERROR": None,
        "CORPORATE_ACTION_POLICY_SHA256": ca_hash, "CORPORATE_ACTION_POLICY_CHANGED": False,
        "EXECUTION_ELIGIBILITY_POLICY_CHANGED": False, "TRANSACTION_COST_CONTRACT_CHANGED": False,
        "MODEL_CHANGED": False, "TARGET_CHANGED": False, "FEATURE_CONTRACT_CHANGED": False,
        "PROSPECTIVE_SHADOW_CHANGED": False, "MODEL_FIT_COUNT": 0, "MODEL_SEARCH_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0, "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
        "INDEPENDENT_HOLDOUT": False, "CONSUMED_PRE2026_EVIDENCE": True,
        "REPRODUCIBILITY_STATUS": "PASS_STOP_AUDIT_ONLY", "RUN1_FINGERPRINT": fingerprint, "RUN2_FINGERPRINT": fingerprint,
        "HISTORICAL_RESULT_MATERIALIZED": False, "STATIC_2026Q1_UNIVERSE_HISTORICALLY_EXECUTABLE": False,
        "BLOCKING_REASONS": blockers,
        "MISSING_UNFABRICATED_ARTIFACTS": [
            "manager_13f_filing_state_daily.parquet", "dynamic_pit_13f_raw_union_daily.parquet",
            "dynamic_pit_13f_universe_daily.parquet", "dynamic_pit_13f_cap_audit.parquet",
            "a1_a2_dynamic_pit_top20_daily_portfolio.parquet", "a1_a2_dynamic_pit_portfolio_metrics.parquet",
            "a1_a2_dynamic_pit_yearly_metrics.parquet", "static_vs_dynamic_universe_metrics.parquet",
            "dynamic_pit_nav_reconstruction_daily.parquet", "dynamic_pit_nav_reconstruction_metrics.json",
        ],
        "NEW_REPOSITORY_FILE_COUNT": 4, "MODIFIED_EXISTING_FILE_COUNT": 0, "NEW_DATABASE_COUNT": 0,
        "NEW_FRAMEWORK_COUNT": 0, "PER_MANAGER_SCRIPT_COUNT": 0, "PER_MANAGER_PARSER_COUNT": 0,
        "RAW_SEC_FILE_IN_REPOSITORY_COUNT": 0, "DUPLICATED_ACCESSION_CACHE_COUNT": sec["duplicate_accession_cache_count"],
        "commit": False, "push": False,
    }
    return {"summary": summary, "config": config, "manifest": manifest, "security_provenance": source_provenance, "manager_table": manager_table, "oos": oos, "audit_payload": audit_payload}


def persist(result: dict[str, Any]) -> None:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(RESULTS_ROOT / "fast_a2_r0g1_summary.json", result["summary"])
    write_json(RESULTS_ROOT / "manager_master_list_r1.json", result["config"])
    write_parquet(RESULTS_ROOT / "manager_13f_filing_manifest.parquet", result["manifest"])
    write_parquet(RESULTS_ROOT / "security_13f_provenance.parquet", result["security_provenance"])
    write_parquet(RESULTS_ROOT / "manager_contribution_metrics.parquet", result["manager_table"])
    write_parquet(RESULTS_ROOT / "model_oos_provenance_audit.parquet", result["oos"])
    provenance = {
        "experiment_id": EXPERIMENT_ID, "status": result["summary"]["FAST_A2_R0G1_STATUS"],
        "source_hashes": {str(path): sha256_file(path) for path in (CONFIG_PATH, SCRIPT_PATH, MODULE_PATH, TEST_PATH, R1_SUMMARY, R1_OOF, R1_FINAL_MODEL, R0F1_POLICY, EXECUTION_POLICY)},
        "output_hashes": {}, "audit_payload_sha256": pit.canonical_sha256(result["audit_payload"]),
        "raw_sec_file_in_repository_count": 0, "new_database_count": 0,
    }
    for path in sorted(RESULTS_ROOT.iterdir(), key=lambda p: p.name):
        if path.name not in {"provenance_manifest.json", "final_console_summary.txt"} and path.is_file():
            provenance["output_hashes"][str(path)] = sha256_file(path)
    write_json(RESULTS_ROOT / "provenance_manifest.json", provenance)


def display(value: Any) -> str:
    return "NOT_AVAILABLE_FAIL_CLOSED" if value is None else str(value).lower() if isinstance(value, bool) else str(value)


def print_final(summary: dict[str, Any]) -> None:
    keys = [
        "FAST_A2_R0G1_STATUS", "FAST_A2_R0G1_CLASSIFICATION", "NEXT_AUTHORIZED_STEP",
        "MANAGER_MASTER_COUNT", "MAX_UNIVERSE_SIZE", "PIT_13F_SOURCE_STATUS", "PIT_UNIVERSE_STATUS",
        "A1_OOS_PROVENANCE_STATUS", "A2_OOS_PROVENANCE_STATUS", "MANAGER_WITH_HISTORICAL_FILING_COUNT",
        "MANAGER_WITHOUT_HISTORICAL_FILING_COUNT", "MANAGER_WITHOUT_LOCAL_VERIFIED_FILING_COUNT", "MANAGER_PARSE_FAILURE_COUNT", "TOTAL_13F_FILINGS_USED",
        "TOTAL_AMENDMENTS_USED", "SEC_ACQUISITION_MODE", "BULK_MACHINE_READABLE", "BROWSER_FALLBACK_EVENT_COUNT",
        "MANUAL_MANAGER_SEARCH_COUNT", "MIN_ACTIVE_MANAGER_COUNT", "MEDIAN_ACTIVE_MANAGER_COUNT", "MAX_ACTIVE_MANAGER_COUNT",
        "MIN_RAW_UNION_SIZE", "MEDIAN_RAW_UNION_SIZE", "MAX_RAW_UNION_SIZE", "MIN_FINAL_UNIVERSE_SIZE",
        "MEDIAN_FINAL_UNIVERSE_SIZE", "MAX_FINAL_UNIVERSE_SIZE", "CAP_APPLIED_SESSION_COUNT", "CAP_APPLIED_SESSION_RATE",
        "UNIVERSE_CAP_MODEL_BLIND", "UNIVERSE_CAP_OUTCOME_BLIND", "OLD_STATIC_A2_NET_CUM_RETURN", "OLD_STATIC_A2_CAGR",
        "OLD_STATIC_A2_SHARPE", "DYNAMIC_PIT_A1_NET_CUM_RETURN", "DYNAMIC_PIT_A1_CAGR", "DYNAMIC_PIT_A1_SHARPE",
        "DYNAMIC_PIT_A2_NET_CUM_RETURN", "DYNAMIC_PIT_A2_CAGR", "DYNAMIC_PIT_A2_SHARPE",
        "DYNAMIC_PIT_NAV_RECONSTRUCTION_STATUS", "NAV_RECONSTRUCTION_MAX_ABS_ERROR", "NAV_RECONSTRUCTION_MAX_REL_ERROR",
        "CORPORATE_ACTION_POLICY_CHANGED", "EXECUTION_ELIGIBILITY_POLICY_CHANGED", "TRANSACTION_COST_CONTRACT_CHANGED",
        "MODEL_CHANGED", "TARGET_CHANGED", "FEATURE_CONTRACT_CHANGED", "PROSPECTIVE_SHADOW_CHANGED",
        "MODEL_FIT_COUNT", "MODEL_SEARCH_COUNT", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT",
        "INDEPENDENT_HOLDOUT", "CONSUMED_PRE2026_EVIDENCE", "REPRODUCIBILITY_STATUS", "RUN1_FINGERPRINT", "RUN2_FINGERPRINT",
        "ANTI_BLOAT_STATUS", "NEW_REPOSITORY_FILE_COUNT", "MODIFIED_EXISTING_FILE_COUNT", "NEW_DATABASE_COUNT",
        "NEW_FRAMEWORK_COUNT", "PER_MANAGER_SCRIPT_COUNT", "PER_MANAGER_PARSER_COUNT", "RAW_SEC_FILE_IN_REPOSITORY_COUNT",
        "DUPLICATED_ACCESSION_CACHE_COUNT", "commit", "push",
    ]
    for key in keys:
        print(f"{key}={display(summary.get(key))}")
    print("\nBLOCKING_REASONS")
    for reason in summary["BLOCKING_REASONS"]:
        print(reason)
    print("\nDYNAMIC PIT A1 vs A2 / YEARLY / STATIC-vs-DYNAMIC TABLES")
    print("NOT_PRINTED: NO AUTHORITATIVE PIT UNIVERSE OR ECONOMIC RESULT WAS MATERIALIZED")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser().parse_args(argv)
    result1 = build_stop_result()
    result2 = build_stop_result()
    if result1["summary"]["RUN1_FINGERPRINT"] != result2["summary"]["RUN2_FINGERPRINT"]:
        raise pit.Pit13FContractError("STOP_AUDIT_REPRODUCIBILITY_FAILURE")
    persist(result1)
    print_final(result1["summary"])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
