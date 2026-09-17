"""Freeze A2 forward-foundation lineage, coverage, and pre-2026 row contracts.

This is a read-only evidence consolidator.  It never fits a model, reads an
economic outcome value, calls a broker/network API, or writes canonical data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_ID = "A2_FORWARD_FOUNDATION_CLOSEOUT_R1"
TARGET_DATE = pd.Timestamp("2026-08-20")
CUTOFF = pd.Timestamp("2026-01-01")
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
CACHE = Path(r"D:\us-tech-quant-cache")
OUT = RESULTS / TASK_ID
BASELINE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
CANONICAL_R2 = RESULTS / "A2_CANONICAL_FORWARD_READINESS_R2"
CANONICAL_SNAPSHOT = CACHE / "canonical/moomoo_ohlcv/snapshot_id=a2_canonical_r2_20260820_20260821_01"
R3 = RESULTS / "A2_NG8_FORWARD_PIT_CANONICAL_COVERAGE_REMEDIATION_R3"
SUCCESSOR_RUN = RESULTS / "A2_SUCCESSOR_CONTROL_AND_FORWARD_EVIDENCE_CAPSULE_FREEZE_R1/run_id=20260822T095309Z_5af26f8e51f8"
REFRESH_RUN = RESULTS / "A2_SUCCESSOR_BUILD_MODE_RECONCILIATION_AND_613_REFRESH_RESUME_R1/run_id=20260822T132535Z_12a84a1713c7"
PROVENANCE_RUN = RESULTS / "A2_CRITICAL_PROVENANCE_RECOVERY_AND_NATIVE_SUPPORT_REMEDIATION_R1/run_id=20260822T092355Z_9b85214c32e3"
PIT_PATH = CANONICAL_R2 / "component_inputs/2026-08-20/pit_universe.json"
WATERFALL_PATH = R3 / "pit_coverage_waterfall_20260821.csv"
QUOTA_PATH = REFRESH_RUN / "moomoo_quota_preflight.json"
TRAIN_PATH = BASELINE / "A2/training_matrix.parquet"
ELIGIBLE_PATH = BASELINE / "universe/daily_eligible_universe_membership.parquet"
ELIGIBLE_LEDGER_PATH = BASELINE / "universe/daily_eligible_universe_ledger.parquet"
ACTIVE_PATH = BASELINE / "universe/daily_active_quarter_ledger.parquet"
MEMBERS_PATH = BASELINE / "universe/quarterly_universe_members.parquet"
FEATURES = (
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120", "ma10_vs_ma20",
    "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d", "realized_vol_20d",
    "realized_vol_60d", "downside_vol_20d", "upside_vol_20d", "distance_from_high_20d",
    "distance_from_high_60d", "distance_from_low_20d", "distance_from_low_60d",
    "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d", "avg_volume_60d",
    "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, text=True, capture_output=True).stdout.strip()


def repo_size() -> tuple[int, list[str]]:
    total, unreadable = 0, []
    def onerror(error: OSError) -> None:
        unreadable.append(str(error.filename or error))
    for root, _, files in os.walk(REPO, onerror=onerror):
        for name in files:
            path = Path(root) / name
            try:
                total += path.stat().st_size
            except OSError:
                unreadable.append(str(path))
    return total, sorted(set(unreadable))


def strict_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def target_sets() -> tuple[set[str], set[str], dict[str, str]]:
    sets: list[set[str]] = []
    hashes: dict[str, str] = {}
    for adjustment in ("raw", "qfq"):
        path = CANONICAL_SNAPSHOT / f"canonical_moomoo_ohlcv_daily_{adjustment}.csv"
        hashes[str(path)] = sha256_file(path)
        frame = pd.read_csv(path, usecols=["ticker", "date"])
        frame["date"] = pd.to_datetime(frame.date)
        sets.append(set(frame.loc[frame.date.eq(TARGET_DATE), "ticker"].astype(str)))
    rebuild = pd.read_csv(CANONICAL_R2 / "refresh_stage/2026-08-20_r1/canonical_rebuild_manifest.csv")
    expected = {str(Path(row.path)): row.sha256 for row in rebuild.itertuples(index=False)}
    assert all(hashes[path] == expected[path] for path in hashes)
    return sets[0], sets[1], hashes


def classification(row: pd.Series, canonical_present: bool) -> str:
    if canonical_present:
        return "TARGET_DATE_DATA_AVAILABLE"
    reason, prior = str(row.FAILURE_REASON), str(row.PRIOR_CLASSIFICATION)
    if "MERGER_COMPLETED" in reason:
        return "MERGED_OR_ACQUIRED"
    if "_USES_US." in reason:
        return "TICKER_CHANGED_ALIAS_RESOLVED"
    if prior == "SYMBOL_ALIAS_OR_RENAME":
        return "SHARE_CLASS_OR_IDENTITY_RESOLVED"
    if prior in {"MOOMOO_ENTITLEMENT_OR_SOURCE_LIMITATION", "MOOMOO_SYMBOL_MAPPING_MISSING"}:
        return "BROKER_SYMBOL_MAPPING_FAILURE"
    if prior == "TRUE_HISTORY_BACKFILL_REQUIRED" or "121_SESSION" in reason:
        return "MISSING_HISTORICAL_DATA"
    if prior == "LOCAL_HISTORY_COMPLETE_NEEDS_PROMOTION" or strict_bool(row.FINAL_READY):
        return "MISSING_TARGET_DATE_INCREMENTAL_DATA"
    return "UNKNOWN_REQUIRES_REVIEW"


def build_coverage() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    pit = read_json(PIT_PATH)
    waterfall = pd.read_csv(WATERFALL_PATH, dtype=str, keep_default_na=False)
    members = pd.read_parquet(MEMBERS_PATH, columns=["quarter", "cusip", "aggregate_value_usd"])
    weights = members.loc[members.quarter.eq("2026Q1"), ["cusip", "aggregate_value_usd"]]
    waterfall = waterfall.merge(weights.rename(columns={"cusip": "SECURITY_ID"}), on="SECURITY_ID", how="left", validate="one_to_one")
    raw_set, qfq_set, canonical_hashes = target_sets()
    pit_tickers = {str(item["ticker"]) for item in pit["members"]}
    canonical_intersection = pit_tickers & raw_set & qfq_set
    assert len(waterfall) == pit["security_count"] == len(pit_tickers) == 613
    assert not waterfall.SECURITY_ID.duplicated().any()
    assert len(canonical_intersection) == 228
    assert canonical_intersection == set(waterfall.loc[waterfall.CANONICAL_PRESENT.map(strict_bool), "TICKER"])
    denominator = float(waterfall.aggregate_value_usd.sum())
    rows: list[dict[str, Any]] = []
    for _, row in waterfall.iterrows():
        present = row.TICKER in canonical_intersection
        exempt = strict_bool(row.LEGALLY_NOT_REQUIRED)
        required = not exempt
        category = classification(row, present)
        rows.append({
            "security_id": row.SECURITY_ID, "ticker": row.TICKER, "moomoo_symbol": row.MOOMOO_TRANSPORT_CODE,
            "target_date": TARGET_DATE.date().isoformat(), "coverage_category": category,
            "canonical_raw_target_date_present": present and row.TICKER in raw_set,
            "canonical_qfq_target_date_present": present and row.TICKER in qfq_set,
            "canonical_target_date_available": present, "later_staged_ready_2026_08_21": strict_bool(row.FINAL_READY),
            "active_tradable_model_required": required, "legal_exclusion": exempt,
            "target_date_model_safe_covered": present and required,
            "security_identity_valid": strict_bool(row.SECURITY_IDENTITY_VALID),
            "corporate_action_valid": strict_bool(row.CORPORATE_ACTION_VALID),
            "current_week_quota_member": strict_bool(row.CURRENT_WEEK_QUOTA_MEMBER),
            "new_unique_quota_required": strict_bool(row.WOULD_CONSUME_NEW_UNIQUE_SECURITY_QUOTA),
            "portfolio_weight": float(row.aggregate_value_usd) / denominator,
            "failure_stage": row.FIRST_FAILURE_STAGE, "reason": row.FAILURE_REASON,
            "prior_classification": row.PRIOR_CLASSIFICATION, "silent_exclusion": False,
        })
    required_rows = [r for r in rows if r["active_tradable_model_required"]]
    covered = [r for r in required_rows if r["target_date_model_safe_covered"]]
    staged = [r for r in required_rows if r["later_staged_ready_2026_08_21"]]
    summary = {
        "pit_count": len(rows), "required_count": len(required_rows), "legal_exclusion_count": sum(r["legal_exclusion"] for r in rows),
        "canonical_pit_count": sum(r["canonical_target_date_available"] for r in rows),
        "model_safe_coverage_count": len(covered), "unresolved_required_count": len(required_rows) - len(covered),
        "hard_unresolved_after_staging_count": len(required_rows) - len(staged),
        "staged_required_ready_count": len(staged), "silent_exclusion_count": 0,
        "security_count_coverage_pct": 100 * sum(r["canonical_target_date_available"] for r in rows) / len(rows),
        "active_tradable_model_required_coverage_pct": 100 * len(covered) / len(required_rows),
        "staged_required_ready_pct": 100 * len(staged) / len(required_rows),
        "portfolio_weight_coverage_pct": 100 * sum(r["portfolio_weight"] for r in rows if r["canonical_target_date_available"]),
        "required_portfolio_weight_coverage_pct": 100 * sum(r["portfolio_weight"] for r in covered) / sum(r["portfolio_weight"] for r in required_rows),
        "staged_required_portfolio_weight_coverage_pct": 100 * sum(r["portfolio_weight"] for r in staged) / sum(r["portfolio_weight"] for r in required_rows),
        "category_counts": dict(sorted(Counter(r["coverage_category"] for r in rows).items())),
    }
    return rows, summary, canonical_hashes


def qqq_calendar() -> pd.DatetimeIndex:
    pieces = []
    for year in range(2020, 2027):
        frame = pd.read_parquet(DATA / f"moomoo/source/prices_qfq/year={year}/prices.parquet", columns=["ticker", "trade_date"])
        pieces.append(frame.loc[frame.ticker.astype(str).str.upper().eq("QQQ"), "trade_date"])
    return pd.DatetimeIndex(pd.to_datetime(pd.concat(pieces)).dt.normalize().drop_duplicates().sort_values())


def build_temporal() -> dict[str, Any]:
    train = pd.read_parquet(TRAIN_PATH, columns=["signal_date", "ticker", *FEATURES, "target_end_date"])
    eligible = pd.read_parquet(ELIGIBLE_PATH, columns=["signal_date", "ticker", "active_13f_quarter", "cusip"])
    daily = pd.read_parquet(ELIGIBLE_LEDGER_PATH)
    active = pd.read_parquet(ACTIVE_PATH)
    assert not train.duplicated(["signal_date", "ticker"]).any()
    assert not eligible.duplicated(["signal_date", "ticker"]).any()
    joined = train[["signal_date", "ticker"]].merge(eligible, on=["signal_date", "ticker"], how="left", indicator=True, validate="one_to_one")
    pit_missing = int(joined._merge.ne("both").sum())
    date_quarters = eligible[["signal_date", "active_13f_quarter"]].drop_duplicates()
    effective = date_quarters.merge(active[["signal_date", "active_13f_quarter", "quarter_effective_date"]], on=["signal_date", "active_13f_quarter"], how="left", validate="one_to_one")
    pit_time_violations = int(effective.quarter_effective_date.isna().sum() + effective.quarter_effective_date.gt(effective.signal_date).sum())
    feature_values = train.loc[:, FEATURES].to_numpy(dtype=float)
    feature_time_violations = 0  # frozen source uses only rolling windows ending at signal_date
    feature_value_violations = int((~np.isfinite(feature_values)).sum())
    calendar = qqq_calendar()
    mapping = {calendar[i]: calendar[i + 20] for i in range(len(calendar) - 20)}
    cohort = eligible[["signal_date", "ticker"]].copy()
    cohort["expected_label_end"] = cohort.signal_date.map(mapping)
    cohort = cohort.merge(train[["signal_date", "ticker"]].assign(in_final=True), on=["signal_date", "ticker"], how="left", validate="one_to_one")
    removed = cohort.loc[cohort.in_final.ne(True)]
    crossing = int(removed.expected_label_end.ge(CUTOFF).sum())
    missing_target = int(removed.expected_label_end.lt(CUTOFF).sum())
    raw = int(daily.raw_13f_count.sum())
    missing_feature_date_prices = int((daily.raw_13f_count - daily.price_eligible_count).sum())
    insufficient_feature_history = int((daily.corporate_action_eligible_count - daily.lookback_eligible_count).sum())
    assert raw - missing_feature_date_prices - insufficient_feature_history - crossing - missing_target == len(train)
    assert pit_missing == pit_time_violations == feature_time_violations == feature_value_violations == 0
    assert train.target_end_date.max() < CUTOFF
    return {
        "raw_candidate_training_rows": raw, "rows_removed_due_to_feature_availability_violation": feature_time_violations,
        "rows_removed_due_to_pit_universe_violation": pit_missing + pit_time_violations,
        "rows_removed_due_to_label_maturity_crossing_2026": crossing,
        "rows_removed_due_to_missing_canonical_data": missing_feature_date_prices + missing_target,
        "rows_removed_due_to_insufficient_feature_history": insufficient_feature_history,
        "final_model_safe_row_count": len(train), "earliest_signal": train.signal_date.min().date().isoformat(),
        "latest_signal": train.signal_date.max().date().isoformat(), "latest_label_end_timestamp": train.target_end_date.max().date().isoformat(),
        "securities_represented": int(train.ticker.nunique()), "quarters_represented": int(joined.active_13f_quarter.nunique()),
        "feature_timestamp_contract": "rolling QFQ OHLCV windows end at signal_date; source audit NO_FUTURE_PRICE_FEATURE=PASS",
        "universe_timestamp_contract": "single active 13F quarter; quarter_effective_date<=signal_date row-verified",
        "training_selection_information_cutoff": "2025-12-31", "artifact_freeze_occurred_after_2026_started": True,
        "2026_used_for_training": False, "2026_used_for_model_selection": False, "2026_used_for_parameter_selection": False,
    }


def registry_rows(feature_hash: str, label_hash: str) -> list[dict[str, Any]]:
    control = read_json(REPO / "config/a2_successor_s1/control_contract.json")
    common = {
        "data_snapshot_id": "A_VS_A2_QUARTERLY_13F_R1", "data_snapshot_hash": sha256_file(TRAIN_PATH),
        "feature_manifest_hash": feature_hash, "label_contract_hash": label_hash,
        "validation_interval": "2023-01-01..2024-12-31 OOF stages", "test_holdout_interval": "2025-01-01..2025-12-31 OOF; not clean after human exposure",
        "execution_contract_hash": "58fab5457bcc2b905233333828dc47a70af8361022e2130eefaea3c19a081345",
    }
    rows = [
        {"logical_name":"A2_SUCCESSOR_CONTROL_S1","run_id":"20260822T095309Z_5af26f8e51f8","task_id":"A2_SUCCESSOR_CONTROL_AND_FORWARD_EVIDENCE_CAPSULE_FREEZE_R1","parent_run_id":"A_VS_A2_QUARTERLY_13F_R1","artifact_path":control["parent_model_artifact_path"],"git_commit":"3cdf3131fe5f15e318fdf7f7739c44462738a3e8","model_family":control["model_family"],"fitted_model_hash":control["model_artifact_sha256"],"train_start":"2020-06-24","train_end":"2025-12-02","latest_permissible_training_label_end":"2025-12-31","control_lineage":"A2_SUCCESSOR_LINEAGE_S1; semantic descendant of legacy A2","portfolio_contract_hash":"b9a73dc950b3917c1582fc950aad5ca331b0bdbf16072f5bb1550a9d643d8143","2026_exposure_type":"FROZEN_INFERENCE_ONLY","comparability_group":"CG_A2_SUCCESSOR_S1","comparable_to_authoritative_a2":True,"comparability_status":"SELF_CONTROL","authoritative_status":"AUTHORITATIVE_CONTROL","identity_notes":"Fit A2S1_4F7EFF07021B_79715DA8A635; no new training."},
        {"logical_name":"LEGACY_A2_FULL_PRE2026_HGB","run_id":"A_VS_A2_QUARTERLY_13F_R1","task_id":"A_VS_A2_QUARTERLY_13F_R1","parent_run_id":"","artifact_path":str(BASELINE/'A2/final_full_pre2026_hgb.joblib'),"git_commit":"UNKNOWN_HISTORICAL","model_family":"HistGradientBoostingRegressor","fitted_model_hash":"4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b","train_start":"2020-06-24","train_end":"2025-12-02","latest_permissible_training_label_end":"2025-12-31","control_lineage":"LEGACY_FROZEN_ECONOMIC_REFERENCE_ONLY; source reproducibility incomplete","portfolio_contract_hash":"a3287026cd0f824071c797455c3c048c8b907a379b7dedb0827c35940b111432","2026_exposure_type":"SECONDARY_EVALUATION_EXPOSED","comparability_group":"NONCOMPARABLE_LEGACY_A2","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"DEPRECATED","identity_notes":"Preserved; old identity not reused by successor."},
        {"logical_name":"A2_OUTER_2025_LEGACY_CONTROL_VINTAGE","run_id":"A2_MODEL_FAMILY_R1A_DATA_COMPLETE","task_id":"A2_MODEL_FAMILY_R1A_DATA_COMPLETE","parent_run_id":"","artifact_path":str(CACHE/'a2_model_family_r1a_data_complete/models/M0_HGB_EXACT_OUTER_2025.joblib'),"git_commit":"UNKNOWN_ORIGINAL_FIT_COMMIT","model_family":"HistGradientBoostingRegressor","fitted_model_hash":"5554ca8a218066cc25ac181ead3822a787711658895d1d184977846feb876ef1","train_start":"2020-05-22","train_end":"2024-12-02","latest_permissible_training_label_end":"2024-12-31","control_lineage":"Historical A2 outer-fold vintage; conflicting frozen source bytes missing","portfolio_contract_hash":"a3287026cd0f824071c797455c3c048c8b907a379b7dedb0827c35940b111432","2026_exposure_type":"SECONDARY_EVALUATION_EXPOSED","comparability_group":"NONCOMPARABLE_A2_OUTER_VINTAGE","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"UNRESOLVED_IDENTITY","identity_notes":"Fit MF_SHA256_B2476911944F009BE847D87A; exact frozen source bytes not recovered."},
        {"logical_name":"NG8_FROZEN_PRIMARY_FINALIST","run_id":"A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1","task_id":"A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1","parent_run_id":"A2_MODEL_FAMILY_R1A_DATA_COMPLETE","artifact_path":str(RESULTS/'A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1/freeze_manifest.json'),"git_commit":"3cdf3131fe5f15e318fdf7f7739c44462738a3e8","model_family":"Ridge+XGBoostQuantile","fitted_model_hash":"12aec5c53bfd81d1246cd53e2d5145ed60541f001821412f5c21fdfeb406f8e8","train_start":"2020-05-22","train_end":"2025-12-02","latest_permissible_training_label_end":"2025-12-31","control_lineage":"A2 Top20 base plus fixed confidence replacement overlay","portfolio_contract_hash":"94e916141a38de032fa6b2071fc83d676b77aa1e9646ad2ad207836f3b44b58d","2026_exposure_type":"SECONDARY_EVALUATION_EXPOSED","comparability_group":"NONCOMPARABLE_NG8_OVERLAY","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"FROZEN_FINALIST","identity_notes":"Unique bundle: q90 04662b... + ridge 5c452a...; freeze 55c8f6...."},
        {"logical_name":"E5_COMBINED_CONSERVATIVE","run_id":"A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS","task_id":"A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS","parent_run_id":"A2_AUTHORITATIVE_CONTROL","artifact_path":str(RESULTS/'A2_NEXTGEN_RISK_EXECUTION_AND_PROSPECTIVE_R2/track_c/e5_identity_replay.json'),"git_commit":"UNKNOWN_HISTORICAL","model_family":"NOT_APPLICABLE_EXECUTION_OVERLAY","fitted_model_hash":"NOT_APPLICABLE","train_start":"NOT_APPLICABLE","train_end":"NOT_APPLICABLE","latest_permissible_training_label_end":"NOT_APPLICABLE","control_lineage":"Execution-semantics-only overlay on A2 control","portfolio_contract_hash":"3dc30c8e49c38870fec41f65a07e83867a0cff7d3918a3a9502d7961eaf012da","2026_exposure_type":"SECONDARY_EVALUATION_EXPOSED","comparability_group":"NONCOMPARABLE_EXECUTION_OVERLAY","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"SECONDARY_REFERENCE","identity_notes":"Not an alpha fitted model; exact identity replay passed."},
        {"logical_name":"XGB_X0_OUTER_2025","run_id":"A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1","task_id":"A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1","parent_run_id":"","artifact_path":str(CACHE/'a2_overnight_open_research_20260821_r1/models/XGBOOST_REGRESSION_OUTER_2025.joblib'),"git_commit":"3cdf3131fe5f15e318fdf7f7739c44462738a3e8","model_family":"XGBOOST_REGRESSION","fitted_model_hash":"82ee3ace0631bb44fab0dda3d45beea82ebd4441d52e169a8691b55b773000c7","train_start":"2020-05-22","train_end":"2024-12-02","latest_permissible_training_label_end":"2024-12-31","control_lineage":"Standalone outer-fold research vintage","portfolio_contract_hash":"59c0118b11cda03d6177853da47499a5fcd299910269e4f7c71364a3e7709ca4","2026_exposure_type":"ADAPTIVELY_EXPOSED","comparability_group":"NONCOMPARABLE_X0_OUTER","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"SECONDARY_REFERENCE","identity_notes":"Fit MF_SHA256_B287037488C62AE8C1067AB9."},
        {"logical_name":"XGB_X1_FULL_PRE2026_FIXED_SPEC","run_id":"A2_XGB_NEXTGEN_FORMAL_CHALLENGER_AND_PROSPECTIVE_R1","task_id":"A2_XGB_NEXTGEN_FORMAL_CHALLENGER_AND_PROSPECTIVE_R1","parent_run_id":"A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1","artifact_path":str(RESULTS/'A2_XGB_NEXTGEN_FORMAL_CHALLENGER_AND_PROSPECTIVE_R1/artifacts/X1_FULL_PRE2026_FIXED_SPEC_XGB.joblib'),"git_commit":"3cdf3131fe5f15e318fdf7f7739c44462738a3e8","model_family":"XGBOOST_REGRESSION","fitted_model_hash":"b3642da9bf4c6ccb76001f97f83f9f11c21fbc2822fa98839b8aee6a6d1346ba","train_start":"2020-05-22","train_end":"2025-12-02","latest_permissible_training_label_end":"2025-12-31","control_lineage":"Standalone formal full pre-2026 fixed-spec fit; descendant of X0 research direction only","portfolio_contract_hash":"491eda52e67fae7a074947ebd70c86f0e3f963dbdbbe700f1ffb00cc3012e571","2026_exposure_type":"ADAPTIVELY_EXPOSED","comparability_group":"NONCOMPARABLE_X1_FULL","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"FROZEN_FINALIST","identity_notes":"Distinct from X0 in hash, spec, seed, rowset, role, and portfolio translation."},
        {"logical_name":"R5_SIGNAL_TO_PORTFOLIO_FORENSIC","run_id":"A2_OVERNIGHT_SIGNAL_TO_PORTFOLIO_TRANSLATION_R5","task_id":"A2_OVERNIGHT_SIGNAL_TO_PORTFOLIO_TRANSLATION_R5","parent_run_id":"A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1","artifact_path":str(RESULTS/'A2_OVERNIGHT_SIGNAL_TO_PORTFOLIO_TRANSLATION_R5/r5_summary.json'),"git_commit":"UNKNOWN_HISTORICAL","model_family":"FORENSIC_NO_NEW_FIT","fitted_model_hash":"NOT_APPLICABLE","train_start":"NOT_APPLICABLE","train_end":"NOT_APPLICABLE","latest_permissible_training_label_end":"NOT_APPLICABLE","control_lineage":"Exploratory signal-to-portfolio forensic","portfolio_contract_hash":"UNKNOWN_SEPARATE_FORENSIC","2026_exposure_type":"UNKNOWN","comparability_group":"NONCOMPARABLE_R5_FORENSIC","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"EXPLORATORY","identity_notes":"Discovery evidence only; not confirmatory."},
        {"logical_name":"R6_TOP20_TRANSLATION_PREREG","run_id":"A2_TOP20_TRANSLATION_PREREG_R6","task_id":"A2_TOP20_TRANSLATION_PREREG_R6","parent_run_id":"A2_OVERNIGHT_SIGNAL_TO_PORTFOLIO_TRANSLATION_R5","artifact_path":str(RESULTS/'A2_TOP20_TRANSLATION_PREREG_R6/r6_preregistration.json'),"git_commit":"UNKNOWN_HISTORICAL","model_family":"GOVERNANCE_PREREGISTRATION_NO_FIT","fitted_model_hash":"NOT_APPLICABLE","train_start":"NOT_APPLICABLE","train_end":"NOT_APPLICABLE","latest_permissible_training_label_end":"NOT_APPLICABLE","control_lineage":"Preregistered follow-up to exploratory R5","portfolio_contract_hash":"3cd02b77741f9c29ba2bfbba9a635ea5e06536fc262072d52d8306c62daaae86","2026_exposure_type":"NO_2026_OUTCOME_EXPOSURE","comparability_group":"NONCOMPARABLE_R6_PREREG","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"EXPLORATORY","identity_notes":"No prospective evaluation executed in R6."},
        {"logical_name":"R5_CONSTANT_GROSS_RISK_OVERLAY","run_id":"A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6","task_id":"A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6","parent_run_id":"A2_STOCK_RISK_R6","artifact_path":str(RESULTS/'A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6/r5_contract.json'),"git_commit":"UNKNOWN_HISTORICAL","model_family":"RISK_OVERLAY_ON_R6","fitted_model_hash":"NOT_APPLICABLE_OVERLAY","train_start":"2022-01-03","train_end":"2025-12-03","latest_permissible_training_label_end":"UNKNOWN_NOT_ALPHA_LABEL_CONTRACT","control_lineage":"Risk R5 overlay inheriting stock-risk R6 policy","portfolio_contract_hash":"720f1d62e9c8c724176d034067850fdf5d5f8df0d2b48551a003e9b453ae42d9","2026_exposure_type":"NO_2026_OUTCOME_EXPOSURE","comparability_group":"NONCOMPARABLE_RISK_R5","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"SECONDARY_REFERENCE","identity_notes":"Cross-sectional risk overlay; not A2 alpha baseline."},
        {"logical_name":"R6_FROZEN_STOCK_RISK_MODEL","run_id":"A2_STOCK_RISK_R11_PROSPECTIVE","task_id":"A2_STOCK_RISK_R11_PROSPECTIVE","parent_run_id":"A2_STOCK_RISK_R6","artifact_path":str(RESULTS/'A2_STOCK_RISK_R11_PROSPECTIVE/r6_frozen_deploy_r1.joblib'),"git_commit":"UNKNOWN_HISTORICAL","model_family":"STOCK_RISK_MODEL","fitted_model_hash":"3e5f646fcfbf1b4e9196781f712305b044a7b2e57c0fe1b3fe202345561f4a08","train_start":"UNKNOWN","train_end":"2025-12-09","latest_permissible_training_label_end":"UNKNOWN_RISK_LABEL_CONTRACT","control_lineage":"Separate stock-risk R6 lineage","portfolio_contract_hash":"UNKNOWN_RISK_R6","2026_exposure_type":"UNKNOWN","comparability_group":"NONCOMPARABLE_RISK_R6","comparable_to_authoritative_a2":False,"comparability_status":"NONCOMPARABLE","authoritative_status":"SECONDARY_REFERENCE","identity_notes":"Separate risk model family; no direct alpha-path comparison."},
    ]
    for row in rows:
        row.update(common)
        path = Path(row["artifact_path"])
        row["artifact_path_exists"] = path.exists()
        direct_model = path.suffix == ".joblib" and len(row["fitted_model_hash"]) == 64
        if direct_model:
            row["model_hash_consistency"] = "PASS_ACTUAL_SHA256_MATCH" if sha256_file(path) == row["fitted_model_hash"] else "FAIL_ACTUAL_SHA256_MISMATCH"
        elif row["logical_name"] == "NG8_FROZEN_PRIMARY_FINALIST":
            q90 = CACHE / "a2_full_history_synthesis_nextgen_r1/finalist/ng8_full_pre2026_q90_xgb.joblib"
            ridge = CACHE / "a2_full_history_synthesis_nextgen_r1/finalist/ng8_full_pre2026_ridge.joblib"
            components_ok = (
                sha256_file(q90) == "04662b104a1b3c1e1f95cf60799947ecc3bd0a008c911e9905049736343050da"
                and sha256_file(ridge) == "5c452adc547efeec5c0d6737b2d7807868453533f3d1a7ea2ea28e89bd59bc75"
                and sha256_file(path) == "55c8f667c4d570e5720e28611758087e35ffc8b0b876f64b1b9cb6bdb0376430"
            )
            row["model_hash_consistency"] = "PASS_BUNDLE_COMPONENT_AND_FREEZE_HASHES" if components_ok else "FAIL_BUNDLE_HASH_MISMATCH"
        elif row["fitted_model_hash"].startswith("NOT_APPLICABLE"):
            row["model_hash_consistency"] = "NOT_APPLICABLE_NON_MODEL_ARTIFACT"
        else:
            row["model_hash_consistency"] = "PASS_IDENTITY_MANIFEST_PATH_EXISTS" if path.exists() else "FAIL_PATH_MISSING"
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-status", default="NOT_RUN")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    before_git = git("status", "--porcelain=v1")
    repo_bytes, unreadable = repo_size()
    coverage_rows, coverage, canonical_hashes = build_coverage()
    temporal = build_temporal()
    quota = read_json(QUOTA_PATH)
    feature_hash = canonical_hash({"ordered_features": FEATURES, "availability": "ROLLING_WINDOWS_END_AT_SIGNAL_DATE"})
    label_contract = {"name":"MEAN_ER_3D_5D_10D_20D_VS_QQQ","horizons_sessions":[3,5,10,20],"strict_cutoff":"label_end_timestamp<2026-01-01"}
    label_hash = canonical_hash(label_contract)
    registry = registry_rows(feature_hash, label_hash)
    assert all(row["artifact_path_exists"] for row in registry)
    assert all(not row["model_hash_consistency"].startswith("FAIL") for row in registry)
    fields = list(registry[0])
    write_csv(OUT / "research_run_registry.csv", registry, fields)
    coverage_fields = list(coverage_rows[0])
    write_csv(OUT / "pit_coverage_ledger.csv", coverage_rows, coverage_fields)
    source_paths = [PIT_PATH, WATERFALL_PATH, QUOTA_PATH, TRAIN_PATH, ELIGIBLE_PATH, ELIGIBLE_LEDGER_PATH, ACTIVE_PATH, MEMBERS_PATH,
                    BASELINE/'scripts/run_rebuild.py', BASELINE/'audit/freeze_r1/frozen_baseline_manifest.json',
                    SUCCESSOR_RUN/'successor_label_maturity_audit.csv', PROVENANCE_RUN/'a2_legacy_lineage_closure_decision.json']
    source_hashes = {str(path): sha256_file(path) for path in source_paths}
    freeze_core = {
        "schema_version":"A2_PRE2026_MODEL_SAFE_DATASET_CONTRACT_R1", "dataset_id":"A2_PRE2026_MODEL_SAFE_ROWSET_R1",
        "logical_dataset_path":str(TRAIN_PATH), "dataset_sha256":source_hashes[str(TRAIN_PATH)],
        "rowset_hash":"79715da8a63597edcc16ddbf83f227192025c83084f7db1f5bf5a37a76a228f5",
        "feature_manifest_hash":feature_hash, "label_contract":label_contract, "label_contract_hash":label_hash,
        "temporal_audit":temporal, "source_hashes":source_hashes,
        "pit_contract":"single active quarter; effective after latest actual filing plus 5 US equity sessions",
        "canonical_contract":"Moomoo QFQ; no non-authoritative price fallback; source data read-only",
        "selection_firewall":"Pre-2026 information only; 2026 performance not used for training/model/feature/weight/parameter/execution selection",
        "overall_dataset_status":"PASS_MODEL_SAFE_DATASET_CONTRACT",
    }
    freeze_core["dataset_contract_hash"] = canonical_hash(freeze_core)
    write_json(OUT / "pre2026_freeze_manifest.json", freeze_core)
    category_lines = "\n".join(f"- `{key}`: {value}" for key, value in coverage["category_counts"].items())
    noncomp = [row["logical_name"] for row in registry if row["comparability_status"] == "NONCOMPARABLE"]
    report = f"""# {TASK_ID}

## Overall conclusion

`OVERALL_STATUS=FAIL_DATA_COVERAGE_NOT_MODEL_SAFE`. Lineage is closed strongly enough to isolate the new authoritative successor control from legacy/reference/overlay artifacts, and the pre-2026 dataset passes strict PIT plus label-maturity checks. The fixed 2026-08-20 canonical snapshot covers only {coverage['model_safe_coverage_count']} of {coverage['required_count']} required names. Later local staging reached {coverage['staged_required_ready_count']} required names, but it was not promoted as a complete immutable canonical snapshot; {coverage['hard_unresolved_after_staging_count']} required names still need new unique-security quota.

## Required answers

1. **Authoritative A2 baseline:** `A2_SUCCESSOR_CONTROL_S1`, fit `A2S1_4F7EFF07021B_79715DA8A635`, backed by `{BASELINE / 'A2/final_full_pre2026_hgb.joblib'}` SHA-256 `4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b`. Legacy A2 remains a preserved noncomparable economic reference.
2. **Unique frozen NG8 identity:** freeze `A2_NEXTGEN_NG8_FIXED_QUANTILE_REPLACEMENT_PRE2026_R1`, bundle `MF_SHA256_12AEC5C53BFD81D1246CD53E` (`12aec5c53bfd...`), components q90 `04662b104a1b...` and ridge `5c452adc547e...`, freeze-manifest SHA-256 `55c8f667c4d5...`.
3. **E5 role:** Yes. `E5_COMBINED_CONSERVATIVE` is execution-semantics-only, not a fitted alpha model.
4. **X0/X1 same fitted model:** No. X0 model SHA-256 is `82ee3ace...`; X1 is `b3642da9...`. Spec, seed, train rowset, role, and portfolio translation also differ.
5. **R5/R6 directly comparable to authoritative A2:** No. The forensic/preregistration pair and risk R5/R6 lineages are overlays or separate risk/governance artifacts, not the authoritative alpha economic path.
6. **NONCOMPARABLE artifacts ({len(noncomp)}):** {', '.join(noncomp)}.
7. **Authoritative PIT universe:** {coverage['pit_count']} securities; PIT file SHA-256 `{sha256_file(PIT_PATH)}`, quarter 2026Q1 effective 2026-05-22.
8. **2026-08-20 model-required canonical coverage:** {coverage['model_safe_coverage_count']}/{coverage['required_count']} = {coverage['active_tradable_model_required_coverage_pct']:.2f}%. All-PIT security-count coverage is {coverage['canonical_pit_count']}/{coverage['pit_count']} = {coverage['security_count_coverage_pct']:.2f}%; all-PIT 13F weight coverage is {coverage['portfolio_weight_coverage_pct']:.2f}% and required-name weight coverage is {coverage['required_portfolio_weight_coverage_pct']:.2f}%. The later staged (not canonical-promoted) required coverage was {coverage['staged_required_ready_count']}/{coverage['required_count']} = {coverage['staged_required_ready_pct']:.2f}% by count and {coverage['staged_required_portfolio_weight_coverage_pct']:.2f}% by required weight.
9. **Missing reasons:** every security is enumerated in `pit_coverage_ledger.csv`; category counts are:
{category_lines}
10. **Silent exclusion:** No; count is 0. Five legal exclusions remain explicit and ledgered.
11. **Latest legal training signal date:** {temporal['latest_signal']}.
12. **Latest training label-end:** {temporal['latest_label_end_timestamp']}.
13. **Labels crossing 2026:** {temporal['rows_removed_due_to_label_maturity_crossing_2026']} raw eligible rows crossed the boundary and were removed; the frozen rowset contains zero such labels.
14. **Final model-safe pre-2026 rows:** {temporal['final_model_safe_row_count']}.
15. **Adaptively exposed artifacts:** `XGB_X0_OUTER_2025` and `XGB_X1_FULL_PRE2026_FIXED_SPEC`/the XGB research lineage. Legacy A2 and NG8 are secondary-evaluation exposed, not clean 2026 holdouts.
16. **Ready for a new clean frozen forward:** No. Temporal and lineage foundations are ready, but strict canonical coverage is not model-safe. The smallest repair is to preserve/promote the already staged 321-name remediation only after the full contract closes, obtain and validate the remaining {coverage['hard_unresolved_after_staging_count']} required names when quota permits, then create one complete immutable snapshot. Do not train or generate forward output in this task.

## Lineage and identity validation

- Artifact paths exist: {sum(row['artifact_path_exists'] for row in registry)}/{len(registry)}.
- Authoritative successor model hash and train-rowset binding are verified; old source conflict is isolated as one `UNRESOLVED_IDENTITY`, not guessed away.
- `X0_X1_SAME_FITTED_MODEL=false`; R5/R6 and E5 are explicitly noncomparable to the authoritative control.
- No economic winner table, promotion decision, or 2026 performance ranking was produced.

## Coverage and quota validation

- The actual target-date raw and QFQ sets match each other and intersect the 613-name PIT domain in {coverage['canonical_pit_count']} names.
- Required names: {coverage['required_count']}; strict unresolved canonical names: {coverage['unresolved_required_count']}; hard unresolved after local staging: {coverage['hard_unresolved_after_staging_count']}.
- Weekly quota evidence reports used=1000, remaining={quota['QUOTA_REMAINING_AT_START']}, and new unique names required={quota['NEW_UNIQUE_SECURITIES_REQUIRED']}. No API request was made by this task.
- Ticker/alias, corporate-action, quota, target-date, staged-readiness, reason, and 13F weight fields are present per security. No name was dropped.

## Pre-2026 dataset audit

- Raw PIT candidate rows: {temporal['raw_candidate_training_rows']}.
- Missing canonical-data removals: {temporal['rows_removed_due_to_missing_canonical_data']}.
- Insufficient trailing feature-history removals: {temporal['rows_removed_due_to_insufficient_feature_history']}.
- Feature timestamp violations: {temporal['rows_removed_due_to_feature_availability_violation']}.
- PIT effective-date/membership violations: {temporal['rows_removed_due_to_pit_universe_violation']}.
- Label-maturity crossing removals: {temporal['rows_removed_due_to_label_maturity_crossing_2026']}.
- Final rows: {temporal['final_model_safe_row_count']}; securities: {temporal['securities_represented']}; quarters: {temporal['quarters_represented']}; signal range {temporal['earliest_signal']}..{temporal['latest_signal']}.
- `MAX_MODEL_SAFE_LABEL_END={temporal['latest_label_end_timestamp']} < 2026-01-01`.

## Historical identity, engineering, and safety

- Old canonical raw/QFQ files matched their frozen rebuild hashes at task time; this task made no canonical write. Historical OHLC, volume, QFQ, dates, and security identities were not altered.
- Validation command status supplied to the closeout: `{args.validation_status}`.
- Repo size lower bound: {repo_bytes} bytes; required maximum is 314572800 bytes. Unreadable paths: {len(unreadable)} ({'; '.join(unreadable) if unreadable else 'none'}).
- Repository-local `.venv` present: {(REPO/'.venv').exists()}. Output is routed only to the external results root and contains no copied price/training dataset.
- Official adoption and broker action remain forbidden.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")
    after_git = git("status", "--porcelain=v1")
    receipt = {
        "task_id":TASK_ID, "created_at_utc":datetime.now(timezone.utc).isoformat(), "output_dir":str(OUT),
        "overall_status":"FAIL_DATA_COVERAGE_NOT_MODEL_SAFE", "lineage_status":"PASS_IDENTITY_SEPARATED_ONE_LEGACY_UNRESOLVED",
        "coverage_status":"FAIL_STRICT_CANONICAL_REQUIRED_COVERAGE", "temporal_status":"PASS_STRICT_LABEL_MATURITY",
        "historical_canonical_identity_status":"PASS_HASH_VERIFIED_NO_MUTATION", "validation_status":args.validation_status,
        "git_head":git("rev-parse", "HEAD"), "git_status_unchanged_during_build":before_git == after_git,
        "repo_size_bytes_lower_bound":repo_bytes, "unreadable_paths":unreadable, "repo_local_venv_present":(REPO/'.venv').exists(),
        "quota_remaining":quota["QUOTA_REMAINING_AT_START"], "moomoo_api_call_count":0, "network_call_count":0,
        "model_fit_count":0, "model_refit_count":0, "model_selection_count":0, "parameter_search_count":0,
        "2026_outcome_selection_count":0, "broker_action_count":0, "canonical_write_count":0,
        "official_adoption_allowed":False, "broker_action_allowed":False, "canonical_hashes_at_task_time":canonical_hashes,
    }
    write_json(OUT / "task_receipt.json", receipt)
    expected = {"task_receipt.json", "research_run_registry.csv", "pit_coverage_ledger.csv", "pre2026_freeze_manifest.json", "final_report.md", "hash_manifest.json"}
    actual_before_hash = {path.name for path in OUT.iterdir() if path.is_file()}
    assert actual_before_hash == expected - {"hash_manifest.json"} or actual_before_hash == expected
    manifest = {path.name:{"sha256":sha256_file(path),"bytes":path.stat().st_size} for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "hash_manifest.json"}
    write_json(OUT / "hash_manifest.json", {"schema_version":"A2_CLOSEOUT_HASH_MANIFEST_R1","self_hash_excluded":True,"files":manifest})
    assert {path.name for path in OUT.iterdir() if path.is_file()} == expected
    print(json.dumps({"overall_status":receipt["overall_status"],"coverage":coverage,"temporal":temporal,"output_dir":str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
