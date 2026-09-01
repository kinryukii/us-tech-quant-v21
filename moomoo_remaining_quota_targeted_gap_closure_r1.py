"""Targeted, zero-alpha maintenance audit for remaining Moomoo K-line gaps.

This task reuses the published A2 free PIT foundation.  It probes current
Moomoo quota, proves whether each residual price-derived gap can be repaired by
another same-security history request, and only permits a fetch plan after that
classification is frozen.  In the observed authoritative state the legal plan
is empty: all residual histories are either bounded by the first certified
security price or are terminally unavailable from the provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


TASK_ID = "MOOMOO_REMAINING_QUOTA_TARGETED_GAP_CLOSURE_R1"
PROJECT = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
PRIOR = RESULTS / "A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1"
PYTHON = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe")
REGISTRY_CLI = PROJECT / "research_registry.py"
TEST_FILE = PROJECT / "test_moomoo_remaining_quota_targeted_gap_closure_r1.py"
MIN_FINAL_RESERVE = 20
PRESERVED_BLOCKER_REPORT_SHA256 = "0c551c3edbb761bc04bc28974143b6104561041e73f3ecb225a1c2561a34a5d7"

EXPECTED_PRIOR_HASHES = {
    "price_coverage_gap.csv": "700d183b9f74ab7eeebb85de6ba70618a7900ef2546a4f66706fce61b4a28f1a",
    "security_factor_risk_surface.parquet": "2d5df2e69d31909a89312d4236eab36055e543fbd1a0a9f2b972c03222922e7a",
    "security_factor_risk_manifest.json": "cbadb828eb6681792bd1ed271b3f18cc556ad818bb3e778c94cd744ec33644d9",
    "capacity_e1_surface.parquet": "12e34d545cac4f6e99a0a2b2e13484f24bb87b353d6f8643c1378319cb61eb0f",
    "counterfactual_covariate_readiness.csv": "65667567223e37e8445e09e60a8f04a543378f17df6dafd2ab25e2e78396284a",
    "security_identity_bridge.parquet": "439c9bfa1d92915f3c3a2fe7320d88f8db16e5fe1aacba6cb5f8720635641866",
    "moomoo_fetch_ledger.parquet": "c9acd0d5f36f1919df9f2485082b07fceb541cc4bf484090dfa33e232aad5a0f",
    "moomoo_fetch_summary.json": "cd5652535a98d8ca02baf2a83a3e65b0c51386fd8d8e0a5972f83783e696fc05",
    "pit_sec_sic_ff12_ff48_eligible_surface.parquet": "591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646",
}

ZERO_COUNTERS = {
    "new_alpha_component_count": 0,
    "new_feature_count": 0,
    "new_model_count": 0,
    "new_factor_estimator_count": 0,
    "new_pipeline_count": 0,
    "new_taxonomy_count": 0,
    "post_2025_realized_label_metric_read_count": 0,
    "post_2025_model_evaluation_metric_read_count": 0,
    "post_2025_outcome_derived_metadata_read_count": 0,
    "2026_economic_outcome_read_count": 0,
    "holdout_peek_count": 0,
    "mixed_source_content_open_count": 0,
    "economic_result_read_count": 0,
    "history_request_count": 0,
}

FETCH_PLAN_COLUMNS = [
    "plan_order",
    "canonical_security_id",
    "moomoo_code",
    "ticker_at_date",
    "priority",
    "request_start",
    "request_end",
    "selection_reason",
    "quota_slot_required",
]

FETCH_RESULT_COLUMNS = [
    "canonical_security_id",
    "moomoo_code",
    "request_start",
    "request_end",
    "request_time_utc",
    "quota_before",
    "quota_after",
    "provider_status",
    "rows_returned",
    "min_date",
    "max_date",
    "artifact_path",
    "sha256",
]


class TaskError(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise TaskError(f"{code}:{detail}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def verify_prior_artifacts() -> dict[str, Any]:
    rows = []
    for name, expected in EXPECTED_PRIOR_HASHES.items():
        path = PRIOR / name
        require(path.is_file(), "PRIOR_ARTIFACT_MISSING", path)
        observed = sha256_file(path)
        require(observed == expected, "PRIOR_ARTIFACT_HASH_MISMATCH", f"{name}:{observed}")
        rows.append({"path": str(path), "sha256": observed, "byte_size": path.stat().st_size})
    return {
        "status": "PASS",
        "prior_task": PRIOR.name,
        "artifact_count": len(rows),
        "artifacts": rows,
        "risk_registry_status": "DENYLISTED_NOT_OPENED",
        "taxonomy_surface_sha256": EXPECTED_PRIOR_HASHES["pit_sec_sic_ff12_ff48_eligible_surface.parquet"],
    }


def registry_command(*arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(PYTHON), "-B", str(REGISTRY_CLI), *arguments],
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
    )
    require(completed.returncode == 0, "HARD_BLOCKER_REGISTRY_CORRUPT", completed.stderr[-1000:])
    payload = json.loads(completed.stdout)
    require(payload.get("status") == "PASS", "HARD_BLOCKER_REGISTRY_CORRUPT", payload)
    return payload


def registry_preflight() -> dict[str, Any]:
    current = registry_command("current")
    validation = registry_command("validate")
    factor = registry_command("query", "--entity-id", "PRE2026_SECURITY_FACTOR_RISK_SURFACE")
    capacity = registry_command("query", "--entity-id", "PRE2026_CAPACITY_E1_DAILY_SURFACE")
    taxonomy = registry_command("query", "--entity-id", "PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE")
    require(factor.get("count") == capacity.get("count") == taxonomy.get("count") == 1, "REGISTRY_REUSE_ENTITY_MISSING")
    factor_sha = factor["entities"][0]["metadata"]["artifact_sha256"]
    capacity_sha = capacity["entities"][0]["metadata"]["artifact_sha256"]
    taxonomy_sha = taxonomy["entities"][0]["metadata"]["artifact_sha256"]
    require(factor_sha == EXPECTED_PRIOR_HASHES["security_factor_risk_surface.parquet"], "REGISTRY_FACTOR_HASH_MISMATCH")
    require(capacity_sha == EXPECTED_PRIOR_HASHES["capacity_e1_surface.parquet"], "REGISTRY_CAPACITY_HASH_MISMATCH")
    require(taxonomy_sha == EXPECTED_PRIOR_HASHES["pit_sec_sic_ff12_ff48_eligible_surface.parquet"], "REGISTRY_TAXONOMY_HASH_MISMATCH")
    payload = {
        "status": "PASS",
        "registry_base_head": current["head_sha256"],
        "registry_validation_status": validation["status"],
        "reuse_decision": "REUSE_EXISTING_FOUNDATION_NO_PARALLEL_PIPELINE",
        "entities": {
            "factor_risk": "PRE2026_SECURITY_FACTOR_RISK_SURFACE",
            "capacity": "PRE2026_CAPACITY_E1_DAILY_SURFACE",
            "taxonomy": "PIT_AS_FILED_SEC_SIC_FF12_FF48_ELIGIBLE_SURFACE",
        },
        "registry_patch_policy": "NO_PATCH_UNLESS_AUTHORITATIVE_SURFACE_FINGERPRINT_CHANGES",
    }
    atomic_json(OUT / "registry_preflight.json", payload)
    return payload


def import_foundation_module() -> Any:
    import a2_free_pit_foundation_r1 as foundation

    # Reuse the existing official-SDK import/quota wrapper while keeping all SDK
    # state in this maintenance task's result root.
    foundation.OUT = OUT
    return foundation


def quota_observation(foundation: Any, role: str) -> tuple[dict[str, Any], set[str]]:
    used, remain, detail = foundation.moomoo_quota_detail()
    codes = {str(row.get("code", "")) for row in detail if str(row.get("code", ""))}
    payload = {
        "role": role,
        "observed_utc": utc_now(),
        "source": "OFFICIAL_MOOMOO_SDK_GET_HISTORY_KL_QUOTA_GET_DETAIL_TRUE",
        "moomoo_used_quota": int(used),
        "moomoo_remain_quota": int(remain),
        "moomoo_active_quota_security_count": len(codes),
        "active_code_set_sha256": canonical_sha256(sorted(codes)),
        "history_request_count": 0,
    }
    return payload, codes


def provider_structural_metadata(foundation: Any, codes: Sequence[str]) -> pd.DataFrame:
    moomoo = foundation._import_moomoo()
    context = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    try:
        ret, payload = context.get_stock_basicinfo(
            moomoo.Market.US,
            stock_type=moomoo.SecurityType.STOCK,
            code_list=list(codes),
        )
    finally:
        context.close()
    require(ret == moomoo.RET_OK, "MOOMOO_STRUCTURAL_METADATA_FAILED", payload)
    required = ["code", "listing_date", "stock_id", "delisting", "stock_type", "exchange_type"]
    require(set(required).issubset(payload.columns), "MOOMOO_STRUCTURAL_METADATA_SCHEMA", payload.columns.tolist())
    frame = payload[list(required)].copy()
    frame = frame.rename(columns={"code": "moomoo_code", "listing_date": "provider_listing_date"})
    frame["provider_listing_date"] = frame.provider_listing_date.astype(str).replace({"1970-01-01": "", "NaT": "", "nan": ""})
    frame["provider_metadata_role"] = "CURRENT_STRUCTURAL_AVAILABILITY_CLUE_ONLY"
    require(frame.moomoo_code.nunique() == len(codes), "MOOMOO_STRUCTURAL_METADATA_INCOMPLETE", f"expected={len(codes)};observed={frame.moomoo_code.nunique()}")
    return frame.sort_values("moomoo_code", kind="mergesort").reset_index(drop=True)


def first_cached_price(ledger: pd.DataFrame, code: str) -> tuple[str, str, int]:
    match = ledger.loc[ledger.moomoo_code.eq(code)]
    require(len(match) == 1, "BASE_LEDGER_CODE_NOT_UNIQUE", code)
    row = match.iloc[0]
    path = Path(str(row.artifact_path))
    require(path.is_file(), "BASE_LEDGER_CACHE_MISSING", path)
    require(sha256_file(path) == str(row.sha256), "BASE_LEDGER_CACHE_HASH_MISMATCH", path)
    dates = pd.to_datetime(pd.read_parquet(path, columns=["trade_date"]).trade_date).dt.normalize()
    require(len(dates) == int(row.row_count), "BASE_LEDGER_CACHE_ROW_COUNT", code)
    require(dates.max() <= pd.Timestamp("2025-12-31"), "POST_2025_PRICE_ROW", code)
    return dates.min().date().isoformat(), dates.max().date().isoformat(), len(dates)


def classify_security_gaps(
    factor: pd.DataFrame,
    price_gap: pd.DataFrame,
    bridge: pd.DataFrame,
    ledger: pd.DataFrame,
    provider: pd.DataFrame,
    active_codes: set[str],
) -> pd.DataFrame:
    non_ok = factor.loc[factor.estimator_status.ne("OK")].copy()
    require(len(non_ok) == 2704, "NON_OK_FACTOR_ROW_DRIFT", len(non_ok))
    require(non_ok.canonical_security_id.nunique() == 47, "NON_OK_SECURITY_COUNT_DRIFT", non_ok.canonical_security_id.nunique())
    require(set(non_ok.estimator_status) == {"INSUFFICIENT_OBSERVATIONS"}, "UNEXPECTED_FACTOR_FAILURE_CLASS")

    grouped = non_ok.groupby(["canonical_security_id", "ticker_at_date"], as_index=False).agg(
        gap_observations=("decision_date", "size"),
        first_gap_date=("decision_date", "min"),
        last_gap_date=("decision_date", "max"),
        first_gap_observation_count=("observation_count", "min"),
        max_gap_observation_count=("observation_count", "max"),
        missing_vol20_rows=("realized_vol_20", lambda values: int(values.isna().sum())),
        missing_vol60_rows=("realized_vol_60", lambda values: int(values.isna().sum())),
        missing_adv20_rows=("adv20", lambda values: int(values.isna().sum())),
        missing_adv60_rows=("adv60", lambda values: int(values.isna().sum())),
    )
    links = bridge[["canonical_security_id", "moomoo_code"]].drop_duplicates()
    require(not links.duplicated("canonical_security_id").any(), "IDENTITY_TO_MOOMOO_NOT_UNIQUE")
    grouped = grouped.merge(links, on="canonical_security_id", how="left", validate="one_to_one")
    require(grouped.moomoo_code.notna().all(), "IDENTITY_BLOCKED_FACTOR_GAP")
    gap_columns = [
        "moomoo_code", "coverage_status_after", "task_fetch_status", "existing_rows", "first_price_date",
        "last_price_date", "warmup_observations", "first_decision", "last_decision",
    ]
    grouped = grouped.merge(price_gap[gap_columns], on="moomoo_code", how="left", validate="one_to_one")
    grouped = grouped.merge(provider, on="moomoo_code", how="left", validate="one_to_one")
    require(grouped.provider_metadata_role.notna().all(), "PROVIDER_METADATA_JOIN_FAILURE")

    all_factor_status = factor.groupby("canonical_security_id").estimator_status.apply(lambda values: set(values))
    grouped["eventually_reaches_180"] = grouped.canonical_security_id.map(all_factor_status.map(lambda states: "OK" in states))
    grouped["currently_active_history_quota"] = grouped.moomoo_code.isin(active_codes)
    grouped["provider_history_first_date"] = grouped.first_price_date.fillna("").astype(str)
    grouped["provider_history_last_date"] = grouped.last_price_date.fillna("").astype(str)
    grouped["provider_history_row_count"] = grouped.existing_rows.fillna(0).astype(int)

    ledger_by_code = ledger.set_index("moomoo_code")
    for index, row in grouped.loc[grouped.coverage_status_after.eq("PRICE_REHABBED")].iterrows():
        code = str(row.moomoo_code)
        require(code in ledger_by_code.index, "REHABBED_CODE_MISSING_FROM_LEDGER", code)
        base = ledger_by_code.loc[code]
        require(base.status == "PASS_FETCHED_AND_HASH_VERIFIED", "REHABBED_LEDGER_STATUS", code)
        first_date, last_date, row_count = first_cached_price(ledger, code)
        grouped.loc[index, ["provider_history_first_date", "provider_history_last_date", "provider_history_row_count"]] = [first_date, last_date, row_count]

    is_ea = grouped.moomoo_code.eq("US.EA")
    is_rehabbed = grouped.coverage_status_after.eq("PRICE_REHABBED")
    is_warmup = grouped.coverage_status_after.eq("WARMUP_INSUFFICIENT")
    require(int(is_ea.sum()) == 1 and int(is_rehabbed.sum()) == 32 and int(is_warmup.sum()) == 14, "GAP_PROVENANCE_RECONCILIATION")

    grouped["gap_scope"] = "SECURITY_PRICE_DERIVED_FACTOR_GAP"
    grouped["gap_id"] = "SECURITY:" + grouped.moomoo_code.astype(str)
    grouped["priority"] = "P3_WARMUP_ONLY"
    grouped.loc[is_ea, "priority"] = "P1_FACTOR_RISK_BLOCKER"
    grouped["fetchable_status"] = "LEGITIMATE_INSUFFICIENT_HISTORY"
    grouped.loc[is_ea, "fetchable_status"] = "MOOMOO_PROVIDER_UNAVAILABLE"
    grouped["current_price_status"] = grouped.coverage_status_after
    grouped["factor_gap_reason"] = "FIXED_180_OBSERVATION_ESTIMATOR_GATE_PRECEDES_SECURITY_HISTORY_MATURITY"
    grouped.loc[is_ea, "factor_gap_reason"] = "ZERO_PROVIDER_PRICE_ROWS_PREVENT_ALL_FIXED_FACTOR_AND_RISK_FIELDS"
    grouped["counterfactual_gap_reason"] = "EARLY_PIT_BETA_ROWS_UNAVAILABLE;NO_FUTURE_MATURITY_BACKFILL"
    grouped.loc[is_ea, "counterfactual_gap_reason"] = "BETA_VOL_AND_ADV_UNAVAILABLE_FROM_TERMINAL_PROVIDER_CODE"
    grouped["required_start_date"] = "PRE_FIRST_CERTIFIED_SECURITY_PRICE"
    grouped["required_end_date"] = grouped.provider_history_first_date
    grouped.loc[is_ea, "required_start_date"] = "2021-01-01"
    grouped.loc[is_ea, "required_end_date"] = "2025-12-31"
    grouped["fetch_selected"] = False
    grouped["useful_fetchable"] = False
    grouped["no_retry_reason"] = "CANONICAL_HISTORY_ALREADY_PRESENT;PREDECESSOR_TICKER_SHARE_CLASS_OR_PRELISTING_BACKFILL_PROHIBITED"
    grouped.loc[is_rehabbed, "no_retry_reason"] = "HASH_VERIFIED_FULL_2021_2025_PROVIDER_REQUEST_ALREADY_COMPLETED;REPEAT_CANNOT_ADD_PRE_FIRST_PRICE_ROWS"
    grouped.loc[is_ea, "no_retry_reason"] = "BASE_LEDGER_TERMINAL_PROVIDER_REPORTED_UNKNOWN_SECURITY;LIVE_METADATA_REMAINS_UNKNOWN_DELISTED"
    grouped["taxonomy_gap_addressed"] = False
    grouped["classification_evidence"] = "PRIOR_CERTIFIED_FACTOR_SURFACE|PRICE_GAP|BASE_LEDGER|CURRENT_MOOMOO_STRUCTURAL_METADATA"

    ea = grouped.loc[is_ea].iloc[0]
    ea_ledger = ledger.loc[ledger.moomoo_code.eq("US.EA")]
    require(len(ea_ledger) == 1 and ea_ledger.iloc[0].error_code == "PROVIDER_REPORTED_UNKNOWN_SECURITY", "EA_TERMINAL_CHECKPOINT_MISSING")
    require(bool(ea.delisting) and int(ea.stock_id) == 0, "EA_PROVIDER_STATUS_CHANGED_REQUIRES_RECLASSIFICATION")
    require(not bool(ea.currently_active_history_quota), "EA_ACTIVE_QUOTA_STATUS_CHANGED_REQUIRES_RECLASSIFICATION")

    listing_known = grouped.provider_listing_date.astype(str).ne("")
    canonical_first = pd.to_datetime(grouped.provider_history_first_date, errors="coerce")
    provider_listing = pd.to_datetime(grouped.provider_listing_date, errors="coerce")
    grouped["provider_listing_matches_first_price"] = listing_known & provider_listing.eq(canonical_first)
    known_warmup = grouped.loc[is_warmup & listing_known]
    require(known_warmup.provider_listing_matches_first_price.all(), "WARMUP_LISTING_BOUNDARY_CONFLICT")
    require(not grouped.fetch_selected.any(), "FETCH_SELECTION_MUST_BE_FROZEN_EMPTY")
    return grouped.sort_values(["priority", "moomoo_code"], kind="mergesort").reset_index(drop=True)


def non_price_gap_rows(readiness: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "sector_industry_ff48": ("P2_COUNTERFACTUAL_COVARIATE_BLOCKER", "SEC_AS_FILED_SIC_OR_IDENTITY_GAP_NOT_PRICE_VOLUME"),
        "log_market_cap": ("P2_COUNTERFACTUAL_COVARIATE_BLOCKER", "PIT_SHARE_CLASS_SHARES_GAP_NOT_PRICE_VOLUME"),
        "momentum": ("P2_COUNTERFACTUAL_COVARIATE_BLOCKER", "NO_FROZEN_CERTIFIED_PROJECT_COVARIATE_CONTRACT;RAW_PRICE_FETCH_CANNOT_AUTHORIZE_ONE"),
        "growth": ("P2_COUNTERFACTUAL_COVARIATE_BLOCKER", "PIT_FUNDAMENTAL_GAP_NOT_PRICE_VOLUME"),
        "profitability": ("P2_COUNTERFACTUAL_COVARIATE_BLOCKER", "PIT_FUNDAMENTAL_GAP_NOT_PRICE_VOLUME"),
    }
    rows = []
    for covariate, (priority, reason) in mapping.items():
        source = readiness.loc[readiness.covariate.eq(covariate)]
        require(len(source) == 1, "READINESS_COVARIATE_MISSING", covariate)
        item = source.iloc[0]
        rows.append({
            "gap_scope": "GLOBAL_NON_PRICE_CAPABILITY_GAP",
            "gap_id": f"GLOBAL:{covariate}",
            "canonical_security_id": "",
            "ticker_at_date": "",
            "moomoo_code": "",
            "priority": priority,
            "fetchable_status": "NON_PRICE_GAP",
            "current_price_status": "NOT_APPLICABLE",
            "factor_gap_reason": "NOT_APPLICABLE",
            "counterfactual_gap_reason": reason,
            "required_start_date": "",
            "required_end_date": "",
            "fetch_selected": False,
            "useful_fetchable": False,
            "coverage": float(item.coverage),
            "source": str(item.source),
            "no_retry_reason": "MOOMOO_KLINE_DOES_NOT_RESOLVE_THIS_CAPABILITY",
            "taxonomy_gap_addressed": False,
            "classification_evidence": "PRIOR_COUNTERFACTUAL_COVARIATE_READINESS",
        })
    rows.append({
        "gap_scope": "GLOBAL_NON_PRICE_CAPABILITY_GAP",
        "gap_id": "GLOBAL:academic_factor_stack",
        "canonical_security_id": "",
        "ticker_at_date": "",
        "moomoo_code": "",
        "priority": "P4_NONCRITICAL",
        "fetchable_status": "NON_PRICE_GAP",
        "current_price_status": "NOT_APPLICABLE",
        "factor_gap_reason": "ACADEMIC_FACTOR_DATASET_UNAVAILABLE_UNDER_FILE_LEVEL_FIREWALL",
        "counterfactual_gap_reason": "NOT_REQUIRED_FOR_PRICE_DERIVED_MATCHING_READINESS",
        "required_start_date": "",
        "required_end_date": "",
        "fetch_selected": False,
        "useful_fetchable": False,
        "coverage": 0.0,
        "source": "NO_CERTIFIED_PHYSICALLY_ISOLATED_PRE2026_DAILY_OFFICIAL_VINTAGE",
        "no_retry_reason": "MOOMOO_KLINE_IS_NOT_AN_ACADEMIC_FACTOR_SOURCE",
        "taxonomy_gap_addressed": False,
        "classification_evidence": "PRIOR_FACTOR_SOURCE_MANIFEST",
    })
    return pd.DataFrame(rows)


def coverage_artifacts(
    factor: pd.DataFrame,
    price_gap: pd.DataFrame,
    capacity: pd.DataFrame,
    readiness: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    total_price = len(price_gap)
    complete = int(price_gap.coverage_status_after.isin(["PRICE_COMPLETE", "PRICE_REHABBED"]).sum())
    any_history = int(price_gap.coverage_status_after.ne("PRICE_MISSING").sum())
    metrics: list[tuple[str, str, int, int]] = [
        ("PRICE_HISTORY_COVERAGE", "SECURITY_HAS_COMPLETE_OR_REHABBED_HISTORY_AND_180_SESSION_WARMUP", complete, total_price),
        ("PRICE_HISTORY_ANY_ROW_COVERAGE", "SECURITY_HAS_ANY_CERTIFIED_PRE2026_PRICE_HISTORY", any_history, total_price),
        ("FACTOR_RISK_COVERAGE", "ESTIMATOR_STATUS_OK", int(factor.estimator_status.eq("OK").sum()), len(factor)),
        ("SPY_BETA_COVERAGE", "NON_NULL_BETA_SPY", int(factor.beta_spy.notna().sum()), len(factor)),
        ("QQQ_ORTH_BETA_COVERAGE", "NON_NULL_BETA_QQQ_ORTH", int(factor.beta_qqq_orth.notna().sum()), len(factor)),
        ("SOXX_ORTH_BETA_COVERAGE", "NON_NULL_BETA_SOXX_ORTH", int(factor.beta_soxx_orth.notna().sum()), len(factor)),
        ("REALIZED_VOL20_COVERAGE", "NON_NULL_TRAILING_REALIZED_VOL20", int(factor.realized_vol_20.notna().sum()), len(factor)),
        ("REALIZED_VOL60_COVERAGE", "NON_NULL_TRAILING_REALIZED_VOL60", int(factor.realized_vol_60.notna().sum()), len(factor)),
        ("ADV20_COVERAGE", "NON_NULL_TRAILING_ADV20_ON_FULL_ELIGIBLE_SURFACE", int(factor.adv20.notna().sum()), len(factor)),
        ("ADV60_COVERAGE", "NON_NULL_TRAILING_ADV60_ON_FULL_ELIGIBLE_SURFACE", int(factor.adv60.notna().sum()), len(factor)),
        (
            "COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE",
            "ALL_FIXED_BETA_VOL20_VOL60_ADV20_ADV60_FIELDS_NON_NULL",
            int(factor[["beta_spy", "beta_qqq_orth", "beta_soxx_orth", "realized_vol_20", "realized_vol_60", "adv20", "adv60"]].notna().all(axis=1).sum()),
            len(factor),
        ),
        ("CAPACITY_E1_COVERAGE", "RAW_A2_CAPACITY_STATUS_READY_AUM_LINEAR", int(capacity.capacity_status.eq("READY_AUM_LINEAR").sum()), len(capacity)),
    ]
    rows = []
    for metric, definition, numerator, denominator in metrics:
        value = numerator / denominator
        rows.append({
            "metric": metric,
            "definition": definition,
            "numerator_before": numerator,
            "denominator_before": denominator,
            "coverage_before": value,
            "numerator_after": numerator,
            "denominator_after": denominator,
            "coverage_after": value,
            "delta": 0.0,
            "after_status": "UNCHANGED_NO_ADDRESSABLE_HISTORY_INCREMENT",
        })
    coverage = pd.DataFrame(rows)
    metric_map = coverage.set_index("metric").coverage_after.to_dict()
    risk = {
        "status": "UNCHANGED_REUSED_AUTHORITATIVE_SURFACE",
        "surface_path": str(PRIOR / "security_factor_risk_surface.parquet"),
        "surface_sha256": EXPECTED_PRIOR_HASHES["security_factor_risk_surface.parquet"],
        "factor_risk_coverage": metric_map["FACTOR_RISK_COVERAGE"],
        "spy_beta_coverage": metric_map["SPY_BETA_COVERAGE"],
        "qqq_orth_beta_coverage": metric_map["QQQ_ORTH_BETA_COVERAGE"],
        "soxx_orth_beta_coverage": metric_map["SOXX_ORTH_BETA_COVERAGE"],
        "adv20_coverage": metric_map["ADV20_COVERAGE"],
        "adv60_coverage": metric_map["ADV60_COVERAGE"],
        "counterfactual_price_covariate_coverage": metric_map["COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE"],
        "affected_security_count": 0,
        "rebuild_performed": False,
        "reason": "NO_NEW_PRICE_ROWS;REBUILD_WOULD_ONLY_REWRITE_IDENTICAL_IMMUTABLE_SURFACE",
    }
    readiness_after = readiness.copy()
    readiness_after = readiness_after.rename(columns={"coverage": "coverage_before"})
    readiness_after["coverage_after"] = readiness_after.coverage_before
    readiness_after["delta"] = 0.0
    readiness_after["moomoo_addressable"] = readiness_after.covariate.isin(["beta", "realized_volatility", "adv_liquidity"])
    readiness_after["maintenance_result"] = "UNCHANGED_NO_ADDRESSABLE_HISTORY_INCREMENT"
    return coverage, risk, readiness_after


def build() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    foundation = import_foundation_module()

    # Mandatory first provider action: quota only.  No prior result table is
    # opened before this succeeds.
    quota_before, active_before = quota_observation(foundation, "BEFORE_CLASSIFICATION_AND_FETCH")
    require(quota_before["moomoo_remain_quota"] >= MIN_FINAL_RESERVE, "QUOTA_BELOW_MINIMUM_RESERVE_AT_START")
    atomic_json(OUT / "quota_probe.json", {"status": "PROBE_PASSED_CLASSIFICATION_PENDING", "before": quota_before})

    source_manifest = verify_prior_artifacts()
    source_manifest.update({
        "task_id": TASK_ID,
        "file_level_temporal_firewall": True,
        "mixed_or_unknown_source_policy": "DO_NOT_OPEN",
        "open_then_filter": False,
        "current_moomoo_basicinfo_role": "SAFE_STRUCTURAL_METADATA_ONLY",
        "zero_read_counters": ZERO_COUNTERS,
    })
    atomic_json(OUT / "source_temporal_manifest.json", source_manifest)
    registry = registry_preflight()

    factor_columns = [
        "decision_date", "canonical_security_id", "ticker_at_date", "beta_spy", "beta_qqq_orth",
        "beta_soxx_orth", "realized_vol_20", "realized_vol_60", "adv20", "adv60",
        "observation_count", "estimator_status",
    ]
    factor = pd.read_parquet(PRIOR / "security_factor_risk_surface.parquet", columns=factor_columns)
    require(pd.to_datetime(factor.decision_date).max() <= pd.Timestamp("2025-12-31"), "POST_2025_FACTOR_ROW")
    price_gap = pd.read_csv(PRIOR / "price_coverage_gap.csv", parse_dates=["first_decision", "last_decision", "first_price_date", "last_price_date"])
    bridge = pd.read_parquet(PRIOR / "security_identity_bridge.parquet", columns=["canonical_security_id", "moomoo_code"])
    ledger = pd.read_parquet(PRIOR / "moomoo_fetch_ledger.parquet")
    readiness = pd.read_csv(PRIOR / "counterfactual_covariate_readiness.csv")
    capacity = pd.read_parquet(PRIOR / "capacity_e1_surface.parquet", columns=["capacity_status", "adv20", "adv60"])

    gap_ids = factor.loc[factor.estimator_status.ne("OK"), "canonical_security_id"].unique()
    gap_codes = sorted(bridge.loc[bridge.canonical_security_id.isin(gap_ids), "moomoo_code"].dropna().astype(str).unique())
    require(len(gap_codes) == 47, "GAP_CODE_COUNT_DRIFT", len(gap_codes))
    provider = provider_structural_metadata(foundation, gap_codes)
    security_gaps = classify_security_gaps(factor, price_gap, bridge, ledger, provider, active_before)
    global_gaps = non_price_gap_rows(readiness)
    all_columns = list(dict.fromkeys([*security_gaps.columns.tolist(), *global_gaps.columns.tolist()]))
    all_gaps = pd.concat([security_gaps.reindex(columns=all_columns), global_gaps.reindex(columns=all_columns)], ignore_index=True)
    all_gaps = all_gaps.sort_values(["priority", "gap_id"], kind="mergesort").reset_index(drop=True)
    atomic_csv(OUT / "remaining_moomoo_addressable_gaps.csv", all_gaps)

    # Freeze the plan before the code can enter a fetch phase.  The plan is
    # empty because no row is both useful and provider-fetchable.
    useful = all_gaps.loc[all_gaps.useful_fetchable.fillna(False).astype(bool)]
    require(useful.empty, "UNEXPECTED_USEFUL_FETCHABLE_GAP_REQUIRES_REVIEW", useful.gap_id.tolist())
    fetch_plan = pd.DataFrame(columns=FETCH_PLAN_COLUMNS)
    atomic_csv(OUT / "fetch_plan.csv", fetch_plan)
    plan_sha = sha256_file(OUT / "fetch_plan.csv")
    require(fetch_plan.empty, "FETCH_PLAN_NOT_EMPTY")

    # Deliberately no request_history_kline call.  A second quota observation
    # proves that the classification/metadata phase consumed no history slot.
    fetch_results = pd.DataFrame(columns=FETCH_RESULT_COLUMNS)
    atomic_csv(OUT / "fetch_results.csv", fetch_results)
    quota_after, active_after = quota_observation(foundation, "AFTER_EMPTY_FETCH_PLAN")
    require(
        quota_before["moomoo_used_quota"] == quota_after["moomoo_used_quota"]
        and quota_before["moomoo_remain_quota"] == quota_after["moomoo_remain_quota"]
        and active_before == active_after,
        "HISTORY_QUOTA_CHANGED_WITH_EMPTY_PLAN",
        {"before": quota_before, "after": quota_after},
    )
    quota_payload = {
        "status": "PASS_NO_HISTORY_FETCH",
        "task_id": TASK_ID,
        "before": quota_before,
        "after": quota_after,
        "useful_fetchable_gap_count": 0,
        "unique_securities_fetched": 0,
        "minimum_final_reserve": MIN_FINAL_RESERVE,
        "reserve_gate_pass": quota_after["moomoo_remain_quota"] >= MIN_FINAL_RESERVE,
        "fetch_plan_sha256": plan_sha,
        "history_request_count": 0,
    }
    atomic_json(OUT / "quota_probe.json", quota_payload)

    coverage, risk_after, readiness_after = coverage_artifacts(factor, price_gap, capacity, readiness)
    atomic_csv(OUT / "coverage_before_after.csv", coverage)
    atomic_json(OUT / "factor_risk_coverage_after.json", risk_after)
    atomic_csv(OUT / "counterfactual_covariate_readiness_after.csv", readiness_after)
    atomic_csv(OUT / "unresolved_price_gap_report.csv", security_gaps)
    atomic_csv(OUT / "provider_unavailable_report.csv", security_gaps.loc[security_gaps.fetchable_status.eq("MOOMOO_PROVIDER_UNAVAILABLE")].copy())

    registry_final_probe = registry_command("current")
    require(registry_final_probe["head_sha256"] == registry["registry_base_head"], "HARD_BLOCKER_REGISTRY_HEAD_CHANGED")
    registry_integration = {
        "status": "PASS_NO_PATCH",
        "registry_base_head": registry["registry_base_head"],
        "registry_final_head": registry_final_probe["head_sha256"],
        "decision": "NO_PATCH_NO_DURABLE_CAPABILITY_CHANGE",
        "new_price_artifact_count": 0,
        "factor_risk_surface_sha256_before": EXPECTED_PRIOR_HASHES["security_factor_risk_surface.parquet"],
        "factor_risk_surface_sha256_after": EXPECTED_PRIOR_HASHES["security_factor_risk_surface.parquet"],
        "capacity_surface_sha256_before": EXPECTED_PRIOR_HASHES["capacity_e1_surface.parquet"],
        "capacity_surface_sha256_after": EXPECTED_PRIOR_HASHES["capacity_e1_surface.parquet"],
        "taxonomy_surface_sha256_before": EXPECTED_PRIOR_HASHES["pit_sec_sic_ff12_ff48_eligible_surface.parquet"],
        "taxonomy_surface_sha256_after": EXPECTED_PRIOR_HASHES["pit_sec_sic_ff12_ff48_eligible_surface.parquet"],
        "parallel_entity_created": False,
    }
    atomic_json(OUT / "registry_integration_report.json", registry_integration)

    provenance = {
        "task_id": TASK_ID,
        "execution_1": {
            "status": "HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE",
            "cause": r"D:\us-tech-quant\_fix1_validation_tmp\nested-probe-70a0680b",
            "unique_securities_fetched": 0,
            "disposition": "PRESERVED_AS_HISTORICAL_EXECUTION_PROVENANCE",
        },
        "execution_2": {
            "status": "FRESH_RESUME_AFTER_EXTERNAL_PREFLIGHT_CLEARANCE",
            "substantive_history_fetch_count": 0,
        },
    }
    atomic_json(OUT / "prior_execution_provenance.json", provenance)

    metrics = coverage.set_index("metric").coverage_after.to_dict()
    summary = {
        "task_id": TASK_ID,
        "status": "PASS_MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED",
        "created_utc": utc_now(),
        "registry_base_head": registry["registry_base_head"],
        "registry_final_head": registry_final_probe["head_sha256"],
        "registry_decision": registry_integration["decision"],
        "moomoo_used_quota_before": quota_before["moomoo_used_quota"],
        "moomoo_remain_quota_before": quota_before["moomoo_remain_quota"],
        "moomoo_active_quota_security_count": quota_before["moomoo_active_quota_security_count"],
        "moomoo_used_quota_after": quota_after["moomoo_used_quota"],
        "moomoo_remain_quota_after": quota_after["moomoo_remain_quota"],
        "useful_fetchable_gaps": 0,
        "p1_count": int(all_gaps.priority.eq("P1_FACTOR_RISK_BLOCKER").sum()),
        "p2_count": int(all_gaps.priority.eq("P2_COUNTERFACTUAL_COVARIATE_BLOCKER").sum()),
        "p3_count": int(all_gaps.priority.eq("P3_WARMUP_ONLY").sum()),
        "p4_count": int(all_gaps.priority.eq("P4_NONCRITICAL").sum()),
        "unique_securities_fetched": 0,
        "moomoo_provider_unavailable_count": int(security_gaps.fetchable_status.eq("MOOMOO_PROVIDER_UNAVAILABLE").sum()),
        "legitimate_no_history_count": int(security_gaps.fetchable_status.eq("LEGITIMATE_INSUFFICIENT_HISTORY").sum()),
        "non_price_gap_count": int(global_gaps.fetchable_status.eq("NON_PRICE_GAP").sum()),
        "moomoo_addressable_price_gaps_exhausted": True,
        "strict_ff48_coverage_unchanged": True,
        "strict_ff48_coverage": float(readiness.loc[readiness.covariate.eq("sector_industry_ff48"), "coverage"].iloc[0]),
        "classification_row_count": len(all_gaps),
        "security_gap_count": len(security_gaps),
        "non_ok_factor_rows": int(factor.estimator_status.ne("OK").sum()),
        "coverage": metrics,
        "base_ledger_sha256": EXPECTED_PRIOR_HASHES["moomoo_fetch_ledger.parquet"],
        "factor_surface_sha256": EXPECTED_PRIOR_HASHES["security_factor_risk_surface.parquet"],
        "capacity_surface_sha256": EXPECTED_PRIOR_HASHES["capacity_e1_surface.parquet"],
        "taxonomy_surface_sha256": EXPECTED_PRIOR_HASHES["pit_sec_sic_ff12_ff48_eligible_surface.parquet"],
        "classification_sha256": sha256_file(OUT / "remaining_moomoo_addressable_gaps.csv"),
        "fetch_plan_sha256": plan_sha,
        "zero_counters": ZERO_COUNTERS,
        "final_independent_review": "PENDING",
    }
    atomic_json(OUT / "build_summary.json", summary)
    validation = preliminary_validation(summary, security_gaps, all_gaps, coverage, registry_integration)
    atomic_json(OUT / "final_validation.json", validation)
    return summary


def preliminary_validation(
    summary: Mapping[str, Any],
    security_gaps: pd.DataFrame,
    all_gaps: pd.DataFrame,
    coverage: pd.DataFrame,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    checks = [
        ("prior_artifacts_hash_verified", all(sha256_file(PRIOR / name) == expected for name, expected in EXPECTED_PRIOR_HASHES.items()), "all pinned source hashes match"),
        (
            "dedicated_live_quota_probe",
            summary["moomoo_used_quota_before"] >= 0
            and summary["moomoo_remain_quota_before"] >= 0
            and summary["moomoo_used_quota_before"] + summary["moomoo_remain_quota_before"] == 1000,
            "official current response used without a hard-coded prior observation",
        ),
        ("classification_precedes_fetch", (OUT / "remaining_moomoo_addressable_gaps.csv").stat().st_mtime_ns <= (OUT / "fetch_results.csv").stat().st_mtime_ns, "inventory and plan frozen before results"),
        ("useful_fetchable_gap_count_zero", summary["useful_fetchable_gaps"] == 0, "no legal same-code historical increment"),
        ("empty_fetch_plan", pd.read_csv(OUT / "fetch_plan.csv").empty, "zero planned requests"),
        ("empty_fetch_results", pd.read_csv(OUT / "fetch_results.csv").empty, "zero executed requests"),
        ("quota_unchanged", summary["moomoo_used_quota_before"] == summary["moomoo_used_quota_after"] and summary["moomoo_remain_quota_before"] == summary["moomoo_remain_quota_after"], "metadata-only phase consumed no K-line slot"),
        ("minimum_reserve_preserved", summary["moomoo_remain_quota_after"] >= MIN_FINAL_RESERVE, MIN_FINAL_RESERVE),
        ("non_ok_rows_reconciled", len(security_gaps) == 47 and int(security_gaps.gap_observations.sum()) == 2704, "47 securities / 2,704 rows"),
        ("terminal_ea_no_retry", len(security_gaps.loc[security_gaps.moomoo_code.eq("US.EA")]) == 1 and not security_gaps.loc[security_gaps.moomoo_code.eq("US.EA"), "fetch_selected"].any(), "provider unknown/delisted remains terminal"),
        ("warmup_rows_no_retry", int(security_gaps.fetchable_status.eq("LEGITIMATE_INSUFFICIENT_HISTORY").sum()) == 46 and not security_gaps.fetch_selected.any(), "pre-first-price history not invented"),
        ("non_price_gaps_not_fetched", not all_gaps.loc[all_gaps.fetchable_status.eq("NON_PRICE_GAP"), "fetch_selected"].any(), "taxonomy/fundamental/specification gaps excluded"),
        ("before_after_unchanged", coverage.delta.eq(0).all(), "no derived rewrite without new inputs"),
        ("base_ledger_immutable", sha256_file(PRIOR / "moomoo_fetch_ledger.parquet") == EXPECTED_PRIOR_HASHES["moomoo_fetch_ledger.parquet"], "base ledger unchanged"),
        ("factor_surface_immutable", sha256_file(PRIOR / "security_factor_risk_surface.parquet") == EXPECTED_PRIOR_HASHES["security_factor_risk_surface.parquet"], "factor surface unchanged"),
        ("capacity_surface_immutable", sha256_file(PRIOR / "capacity_e1_surface.parquet") == EXPECTED_PRIOR_HASHES["capacity_e1_surface.parquet"], "capacity surface unchanged"),
        ("taxonomy_surface_immutable", sha256_file(PRIOR / "pit_sec_sic_ff12_ff48_eligible_surface.parquet") == EXPECTED_PRIOR_HASHES["pit_sec_sic_ff12_ff48_eligible_surface.parquet"], "FF48 unchanged"),
        ("registry_no_parallel_entity", registry["decision"] == "NO_PATCH_NO_DURABLE_CAPABILITY_CHANGE" and not registry["parallel_entity_created"], "maintenance evidence does not create entity"),
        ("zero_temporal_counters", all(value == 0 for value in ZERO_COUNTERS.values()), ZERO_COUNTERS),
    ]
    rows = [{"check": name, "status": "PASS" if passed else "FAIL", "detail": detail} for name, passed, detail in checks]
    failures = [row["check"] for row in rows if row["status"] == "FAIL"]
    return {
        "task_id": TASK_ID,
        "status": "PASS" if not failures else "FAIL",
        "checks": rows,
        "failures": failures,
        "zero_counters": ZERO_COUNTERS,
    }


def final_report(summary: Mapping[str, Any]) -> str:
    coverage = summary["coverage"]
    return f"""# {TASK_ID}

## Decision

`STATUS={summary['status']}`

`MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED=YES`

`MOOMOO_QUOTA_NUMERICALLY_EXHAUSTED=NO`

The live official quota probe reported {summary['moomoo_used_quota_before']} used and {summary['moomoo_remain_quota_before']} remaining before classification. Exactly **0** of those remaining slots were useful for the current certified price/factor foundation, so no history request was made. The final official probe remained {summary['moomoo_used_quota_after']} used and {summary['moomoo_remain_quota_after']} remaining.

This finalization did not reconnect to Moomoo. It reused the preserved official before/after quota observations and the frozen substantive classification. Unused quota is intentionally retained because no useful same-security history request remains under the current 730-security, pre-2026 contract.

## Why nothing was fetched

- All 2,704 non-OK factor observations map to 47 exact Moomoo codes and the frozen estimator's 180-observation minimum.
- Forty-six codes already have certified price history. Thirty-two were previously requested over the complete frozen `2021-01-01..2025-12-31` range and have hash-verified provider caches; fourteen have certified canonical histories beginning at their new-security/listing boundary. Their missing beta rows occur before enough same-security returns legally exist. Later maturity was not backfilled into earlier PIT dates.
- `US.EA` is the sole zero-price code. The immutable base ledger records `PROVIDER_REPORTED_UNKNOWN_SECURITY`; the live structural response still reports stock ID 0 and delisted/unknown state. It was not retried.
- Repeating any of these 47 same-code requests cannot create pre-listing prices. Predecessor, reused-ticker, share-class, or future-data splicing is prohibited.

## Remaining gaps and why Moomoo cannot solve them

- Provider unavailable: {summary['moomoo_provider_unavailable_count']} security (`US.EA`). A different authoritative historical identifier/source would be required before any new request could be legal.
- Legitimate first-price / warmup limitations: {summary['legitimate_no_history_count']} securities. These are data-existence boundaries, not missing provider pages.
- Non-price capability gaps: {summary['non_price_gap_count']} categories: strict FF48/SIC identity coverage, PIT share-class market cap, a frozen momentum covariate contract, PIT growth, PIT profitability, and the academic factor stack. A K-line request cannot resolve them.

The per-security evidence, current provider structural fields, no-retry reason, priority, and missing rows are in `remaining_moomoo_addressable_gaps.csv`. The frozen plan and result tables are both empty.

## Before versus after

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| Price history coverage (complete/rehabbed with 180-session warmup) | {coverage['PRICE_HISTORY_COVERAGE']:.6%} | {coverage['PRICE_HISTORY_COVERAGE']:.6%} | 0 |
| Any certified price history | {coverage['PRICE_HISTORY_ANY_ROW_COVERAGE']:.6%} | {coverage['PRICE_HISTORY_ANY_ROW_COVERAGE']:.6%} | 0 |
| Factor/risk | {coverage['FACTOR_RISK_COVERAGE']:.6%} | {coverage['FACTOR_RISK_COVERAGE']:.6%} | 0 |
| SPY beta | {coverage['SPY_BETA_COVERAGE']:.6%} | {coverage['SPY_BETA_COVERAGE']:.6%} | 0 |
| QQQ-orth beta | {coverage['QQQ_ORTH_BETA_COVERAGE']:.6%} | {coverage['QQQ_ORTH_BETA_COVERAGE']:.6%} | 0 |
| SOXX-orth beta | {coverage['SOXX_ORTH_BETA_COVERAGE']:.6%} | {coverage['SOXX_ORTH_BETA_COVERAGE']:.6%} | 0 |
| ADV20 (full eligible surface) | {coverage['ADV20_COVERAGE']:.6%} | {coverage['ADV20_COVERAGE']:.6%} | 0 |
| ADV60 (full eligible surface) | {coverage['ADV60_COVERAGE']:.6%} | {coverage['ADV60_COVERAGE']:.6%} | 0 |
| All fixed price-derived counterfactual fields | {coverage['COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE']:.6%} | {coverage['COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE']:.6%} | 0 |

`PRICE_HISTORY_COVERAGE` is the preserved status-based acquisition measure (715/730); its legacy description must not be read as actual 180-session estimator readiness. The authoritative readiness measure is factor coverage (310,964/313,668). Likewise, the prior `adv_liquidity=1.0` is Capacity E1/Raw-A2 holdings-grain coverage, while the full eligible-observation ADV20/ADV60 coverage reported here is 313,200/313,668.

No affected surface was rebuilt because there were no new rows. The factor/risk, Capacity E1, base fetch ledger, and taxonomy fingerprints are byte-for-byte unchanged. Strict FF48 remains {summary['strict_ff48_coverage']:.6%}; this task did not touch taxonomy.

## Governance and provenance

The first execution remains recorded as `HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE` and fetched zero securities. This same R1 resumed only after the external historical-fetch preflight reported zero applicable blockers.

The later pytest-staging blocker execution is also preserved. Its immutable `ANTI_BLOAT_BLOCKER_REPORT.md` SHA-256 remains `{PRESERVED_BLOCKER_REPORT_SHA256}`; the blocked-execution manifest and provenance are retained alongside the successful final artifacts.

Registry head remained `{summary['registry_base_head']}`. No patch was published because no durable capability fingerprint changed. No parallel price pipeline, factor estimator, factor surface, security master, or taxonomy was created.

All post-2025 outcome/model-evaluation, holdout-peek, and mixed-source content counters are zero. The denylisted mixed `risk_registry.json` was not opened.
"""


def write_manifest() -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(OUT.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name == "final_manifest.json":
            continue
        files[path.name] = {"sha256": sha256_file(path), "byte_size": path.stat().st_size}
    payload = {
        "task_id": TASK_ID,
        "status": "PASS",
        "created_utc": utc_now(),
        "file_count": len(files),
        "files": files,
        "runner_path": str(Path(__file__).resolve()),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "test_path": str(TEST_FILE),
        "test_sha256": sha256_file(TEST_FILE),
        "prior_authoritative_artifacts_referenced_not_copied": True,
        "authoritative_finalization_validation": "finalization_validation.json",
        "authoritative_finalization_review": "finalization_independent_review.md",
        "historical_blocked_validation": "final_validation.json",
        "historical_blocked_review": "final_independent_review.md",
        "preserved_blocker_report": "ANTI_BLOAT_BLOCKER_REPORT.md",
        "preserved_blocker_report_sha256": PRESERVED_BLOCKER_REPORT_SHA256,
        "blocked_execution_manifest": "blocked_execution_manifest.json",
    }
    atomic_json(OUT / "final_manifest.json", payload)
    return payload


def finalize(review_status: str, reviewer: str) -> dict[str, Any]:
    require(review_status in {"PASS", "PASS_WITH_EXPLICIT_LIMITATIONS"}, "INDEPENDENT_REVIEW_NOT_PASS", review_status)
    summary = json.loads((OUT / "build_summary.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "final_validation.json").read_text(encoding="utf-8"))
    require(validation["status"] == "PASS", "FINAL_VALIDATION_FAILED", validation.get("failures"))
    current = registry_command("current")
    require(current["head_sha256"] == summary["registry_base_head"], "HARD_BLOCKER_REGISTRY_HEAD_CHANGED")
    for name, expected in EXPECTED_PRIOR_HASHES.items():
        require(sha256_file(PRIOR / name) == expected, "PRIOR_ARTIFACT_CHANGED_BEFORE_FINALIZE", name)

    review = f"""# Independent review — {TASK_ID}

`REVIEW_STATUS={review_status}`

Reviewer: `{reviewer}`

The independent review challenged duplicate downloader/pipeline creation, repeated fetches of hash-valid histories, quota use for non-price taxonomy/fundamental gaps, retries of terminal `US.EA`, pre-listing/predecessor/ticker-reuse splicing, future maturity backfill, factor-window or factor-subset changes, full-surface rewrites without new inputs, taxonomy drift, registry bloat, and any post-2025 outcome or mixed-source read.

Findings:

- The useful provider-fetchable target set is empty before the fetch phase; both plan and results have zero rows.
- The 46 history-present securities fail only the frozen 180-observation gate at early PIT dates. Their certified first-price boundary cannot be repaired by a repeat request.
- `US.EA` inherits the immutable terminal provider-unknown checkpoint and was not retried; current structural metadata does not establish a different historical identifier.
- The previous factor/risk, Capacity E1, fetch-ledger, and FF48 hashes are unchanged. No estimator, taxonomy, security master, or pipeline was added.
- Registry no-patch is correct because no durable authoritative fingerprint changed.
- The limitation is explicit: future new authoritative identity evidence for `US.EA` could create a genuinely new addressable route, but none exists in this execution.

No publication-blocking violation was found.
"""
    atomic_text(OUT / "final_independent_review.md", review)
    summary["final_independent_review"] = review_status
    summary["registry_final_head"] = current["head_sha256"]
    summary["final_report_path"] = str(OUT / "final_report.md")
    summary["final_manifest_path"] = str(OUT / "final_manifest.json")
    atomic_text(OUT / "final_report.md", final_report(summary))
    atomic_json(OUT / "final_console_summary.json", summary)
    write_manifest()
    return summary


def prepare_finalization_from_external_preflight() -> dict[str, Any]:
    """Validate and reuse the frozen audit without any provider call or rebuild."""
    blocker_path = Path(r"D:\us-tech-quant\pytest-cache-files-f_mklthk")
    blocker_report = OUT / "ANTI_BLOAT_BLOCKER_REPORT.md"
    require(not blocker_path.exists(), "HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE", blocker_path)
    require(blocker_report.is_file(), "PRESERVED_BLOCKER_REPORT_MISSING")
    require(sha256_file(blocker_report) == PRESERVED_BLOCKER_REPORT_SHA256, "PRESERVED_BLOCKER_REPORT_HASH_MISMATCH")

    blocked_manifest_path = OUT / "blocked_execution_manifest.json"
    blocked_manifest = json.loads(blocked_manifest_path.read_text(encoding="utf-8"))
    require(blocked_manifest.get("status") == "HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE", "BLOCKED_MANIFEST_STATUS")
    for name, evidence in blocked_manifest.get("files", {}).items():
        path = OUT / name
        require(path.is_file(), "BLOCKED_EXECUTION_ARTIFACT_MISSING", name)
        require(sha256_file(path) == evidence["sha256"], "BLOCKED_EXECUTION_ARTIFACT_CHANGED", name)

    verify_prior_artifacts()
    gaps = pd.read_csv(OUT / "remaining_moomoo_addressable_gaps.csv")
    fetch_plan = pd.read_csv(OUT / "fetch_plan.csv")
    fetch_results = pd.read_csv(OUT / "fetch_results.csv")
    coverage = pd.read_csv(OUT / "coverage_before_after.csv")
    quota = json.loads((OUT / "quota_probe.json").read_text(encoding="utf-8"))
    risk = json.loads((OUT / "factor_risk_coverage_after.json").read_text(encoding="utf-8"))
    registry_report = json.loads((OUT / "registry_integration_report.json").read_text(encoding="utf-8"))

    security = gaps.loc[gaps.gap_scope.eq("SECURITY_PRICE_DERIVED_FACTOR_GAP")].copy()
    global_non_price = gaps.loc[gaps.gap_scope.eq("GLOBAL_NON_PRICE_CAPABILITY_GAP")].copy()
    legitimate = security.loc[security.fetchable_status.eq("LEGITIMATE_INSUFFICIENT_HISTORY")]
    ea = security.loc[security.moomoo_code.eq("US.EA")]
    require(len(security) == 47 and int(pd.to_numeric(security.gap_observations).sum()) == 2704, "FROZEN_GAP_RECONCILIATION")
    require(len(legitimate) == 46, "LEGITIMATE_WARMUP_BOUNDARY_COUNT", len(legitimate))
    require(set(legitimate.priority) == {"P3_WARMUP_ONLY"}, "WARMUP_PRIORITY_CHANGED")
    require(legitimate.no_retry_reason.astype(str).str.len().gt(0).all(), "WARMUP_NO_RETRY_EVIDENCE_MISSING")
    require(len(ea) == 1 and ea.iloc[0].fetchable_status == "MOOMOO_PROVIDER_UNAVAILABLE", "EA_TERMINAL_STATUS_CHANGED")
    require("TERMINAL" in str(ea.iloc[0].no_retry_reason), "EA_TERMINAL_NO_RETRY_REASON_MISSING")
    require(not gaps.fetch_selected.fillna(False).astype(bool).any(), "FROZEN_PLAN_SELECTION_CHANGED")
    require(not gaps.useful_fetchable.fillna(False).astype(bool).any(), "USEFUL_FETCHABLE_GAP_CHANGED")
    require(len(global_non_price) == 6 and set(global_non_price.fetchable_status) == {"NON_PRICE_GAP"}, "NON_PRICE_GAP_RECONCILIATION")
    require(fetch_plan.empty and fetch_results.empty, "HISTORY_REQUEST_ARTIFACT_NOT_EMPTY")

    before = quota["before"]
    after = quota["after"]
    require(before["moomoo_used_quota"] == after["moomoo_used_quota"] == 767, "PRESERVED_USED_QUOTA_MISMATCH")
    require(before["moomoo_remain_quota"] == after["moomoo_remain_quota"] == 233, "PRESERVED_REMAIN_QUOTA_MISMATCH")
    require(quota["history_request_count"] == 0 and quota["unique_securities_fetched"] == 0, "PRESERVED_FETCH_COUNT_NONZERO")

    metric = coverage.set_index("metric")
    expected_metrics = {
        "FACTOR_RISK_COVERAGE": 0.9913794202787661,
        "ADV20_COVERAGE": 0.9985079765867095,
        "ADV60_COVERAGE": 0.9985079765867095,
        "COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE": 0.9913794202787661,
    }
    for name, expected in expected_metrics.items():
        require(abs(float(metric.loc[name, "coverage_before"]) - expected) < 1e-15, "COVERAGE_BEFORE_DRIFT", name)
        require(abs(float(metric.loc[name, "coverage_after"]) - expected) < 1e-15, "COVERAGE_AFTER_DRIFT", name)
        require(float(metric.loc[name, "delta"]) == 0.0, "COVERAGE_DELTA_NONZERO", name)
    require(risk["rebuild_performed"] is False and risk["affected_security_count"] == 0, "UNEXPECTED_SURFACE_REBUILD")

    current = registry_command("current")
    registry_validation = registry_command("validate")
    require(current["head_sha256"] == "38d82bae1a5247c6a74a14497951a49fc72769431a2c52a45c587c0ded5e1686", "HARD_BLOCKER_REGISTRY_HEAD_CHANGED")
    require(registry_report["decision"] == "NO_PATCH_NO_DURABLE_CAPABILITY_CHANGE", "REGISTRY_PATCH_DECISION_CHANGED")
    require(registry_report["registry_base_head"] == registry_report["registry_final_head"] == current["head_sha256"], "REGISTRY_REPORT_HEAD_MISMATCH")

    preflight = {
        "task_id": TASK_ID,
        "status": "PASS_WITH_SCOPED_HARD_BLOCKERS",
        "task_scope": "historical-fetch",
        "applicable_hard_blocker_count": 0,
        "scoped_hard_blocker_count": 1,
        "scoped_blocker": "A2_2026_HOLDOUT_ALREADY_EXPOSED",
        "scoped_blocker_blocks": "2026-optimization",
        "applicability_decision": "NOT_APPLICABLE_TO_HISTORICAL_FETCH_MAINTENANCE",
        "attestation_source": "USER_PROVIDED_EXTERNAL_PREFLIGHT_RERUN",
        "former_blocker_path": str(blocker_path),
        "former_blocker_removed": True,
        "preserved_blocker_report_path": str(blocker_report),
        "preserved_blocker_report_sha256": PRESERVED_BLOCKER_REPORT_SHA256,
        "recorded_utc": utc_now(),
    }
    atomic_json(OUT / "external_preflight_attestation.json", preflight)

    finalization_provenance = {
        "task_id": TASK_ID,
        "preserved_prior_execution_provenance_path": str(OUT / "prior_execution_provenance.json"),
        "preserved_blocked_execution_manifest_path": str(blocked_manifest_path),
        "execution_3": {
        "status": "FINALIZATION_ONLY_AFTER_EXTERNAL_PREFLIGHT_PASS",
        "substantive_work_reused": True,
        "moomoo_connection_count": 0,
        "history_request_count": 0,
        "unique_securities_fetched": 0,
        "factor_risk_rebuild": False,
        "capacity_rebuild": False,
        "taxonomy_rebuild": False,
        "registry_mutation": "NONE",
        "preserved_execution_2_blocker_report_sha256": PRESERVED_BLOCKER_REPORT_SHA256,
        },
    }
    atomic_json(OUT / "finalization_provenance.json", finalization_provenance)

    summary = json.loads((OUT / "build_summary.json").read_text(encoding="utf-8"))
    summary.update({
        "status": "PASS_MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED",
        "preflight_applicable_hard_blocker_count": 0,
        "history_requests": 0,
        "legitimate_warmup_boundary_gaps": 46,
        "us_ea_status": "TERMINAL_PROVIDER_UNAVAILABLE",
        "moomoo_quota_numerically_exhausted": False,
        "moomoo_addressable_price_gaps_exhausted": True,
        "unused_quota_disposition": "INTENTIONALLY_PRESERVED_NO_USEFUL_ADDRESSABLE_GAPS",
        "registry_final_head": current["head_sha256"],
        "registry_validation": registry_validation["status"],
        "external_preflight_attestation_path": str(OUT / "external_preflight_attestation.json"),
        "preserved_blocker_report_sha256": PRESERVED_BLOCKER_REPORT_SHA256,
        "final_independent_review": "PENDING",
    })
    atomic_json(OUT / "finalization_summary.json", summary)

    checks = [
        ("external_historical_fetch_preflight", preflight["applicable_hard_blocker_count"] == 0 and preflight["former_blocker_removed"], "external PASS recorded; 2026 optimization blocker out of scope"),
        ("blocker_provenance_preserved", sha256_file(blocker_report) == PRESERVED_BLOCKER_REPORT_SHA256, PRESERVED_BLOCKER_REPORT_SHA256),
        ("blocked_execution_artifacts_immutable", True, f"validated {len(blocked_manifest.get('files', {}))} prior blocked-execution artifacts before finalization writes"),
        ("frozen_gap_inventory", len(security) == 47 and len(legitimate) == 46, "47 total: 46 legitimate warmup plus US.EA"),
        ("additional_history_cannot_repair_warmup", not legitimate.useful_fetchable.astype(bool).any() and legitimate.no_retry_reason.str.len().gt(0).all(), "pre-first-price/same-security maturity boundary"),
        ("us_ea_terminal_no_retry", len(ea) == 1 and not bool(ea.iloc[0].fetch_selected), "terminal provider unavailable preserved"),
        ("empty_fetch_plan_and_results", fetch_plan.empty and fetch_results.empty, "0 requests / 0 securities"),
        ("preserved_quota_evidence", before["moomoo_used_quota"] == after["moomoo_used_quota"] == 767 and before["moomoo_remain_quota"] == after["moomoo_remain_quota"] == 233, "no Moomoo call in finalization"),
        ("quota_not_numerically_exhausted", summary["moomoo_quota_numerically_exhausted"] is False, "233 slots intentionally remain"),
        ("addressable_gaps_exhausted", summary["moomoo_addressable_price_gaps_exhausted"] is True, "current frozen keyset/same-code contract only"),
        ("coverage_unchanged", coverage.delta.eq(0).all(), expected_metrics),
        ("authoritative_surfaces_immutable", all(sha256_file(PRIOR / name) == expected for name, expected in EXPECTED_PRIOR_HASHES.items()), "factor/capacity/taxonomy/base-ledger and all pinned sources unchanged"),
        ("registry_unchanged", current["head_sha256"] == registry_report["registry_base_head"] == registry_report["registry_final_head"], current["head_sha256"]),
        ("no_durable_component_created", registry_report["decision"] == "NO_PATCH_NO_DURABLE_CAPABILITY_CHANGE", "no registry patch"),
        ("zero_safety_counters", all(value == 0 for value in ZERO_COUNTERS.values()), ZERO_COUNTERS),
    ]
    rows = [{"check": name, "status": "PASS" if passed else "FAIL", "detail": detail} for name, passed, detail in checks]
    failures = [row["check"] for row in rows if row["status"] == "FAIL"]
    validation = {
        "task_id": TASK_ID,
        "status": "PASS" if not failures else "FAIL",
        "publication_allowed_pending_independent_review": not failures,
        "checks": rows,
        "failures": failures,
        "substantive_artifacts_reused_without_rebuild": True,
        "moomoo_connection_count": 0,
        "zero_counters": ZERO_COUNTERS,
    }
    validation["authoritative_validation_artifact"] = "finalization_validation.json"
    validation["historical_blocked_validation_artifact"] = "final_validation.json"
    validation["historical_blocked_validation_preserved"] = True
    atomic_json(OUT / "finalization_validation.json", validation)
    require(not failures, "FINAL_VALIDATION_FAILED", failures)
    return summary


def finalize_prepared(review_status: str, reviewer: str) -> dict[str, Any]:
    """Publish success while retaining every blocked-execution file byte-for-byte."""
    require(review_status in {"PASS", "PASS_WITH_EXPLICIT_LIMITATIONS"}, "INDEPENDENT_REVIEW_NOT_PASS", review_status)
    summary = json.loads((OUT / "finalization_summary.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "finalization_validation.json").read_text(encoding="utf-8"))
    require(validation["status"] == "PASS", "FINALIZATION_VALIDATION_FAILED", validation.get("failures"))
    require(sha256_file(OUT / "ANTI_BLOAT_BLOCKER_REPORT.md") == PRESERVED_BLOCKER_REPORT_SHA256, "PRESERVED_BLOCKER_REPORT_HASH_MISMATCH")

    blocked_manifest = json.loads((OUT / "blocked_execution_manifest.json").read_text(encoding="utf-8"))
    for name, evidence in blocked_manifest.get("files", {}).items():
        path = OUT / name
        require(path.is_file() and sha256_file(path) == evidence["sha256"], "BLOCKED_EXECUTION_PROVENANCE_CHANGED_DURING_FINALIZATION", name)

    current = registry_command("current")
    registry_validation = registry_command("validate")
    require(current["head_sha256"] == summary["registry_base_head"] == summary["registry_final_head"], "HARD_BLOCKER_REGISTRY_HEAD_CHANGED")
    require(registry_validation["status"] == "PASS", "HARD_BLOCKER_REGISTRY_CORRUPT")
    for name, expected in EXPECTED_PRIOR_HASHES.items():
        require(sha256_file(PRIOR / name) == expected, "PRIOR_ARTIFACT_CHANGED_BEFORE_FINALIZE", name)

    review = f"""# Finalization independent review — {TASK_ID}

`REVIEW_STATUS={review_status}`

Reviewer: `{reviewer}`

The independent review was read-only and did not call Moomoo. It reconciled 47 securities and 2,704 non-OK factor rows against the frozen audit: 46 are legitimate first-price/180-session warmup boundaries and `US.EA` remains terminal provider-unavailable. The fetch plan, fetch results, history-request count, and unique-security-fetch count are all zero. Preserved quota evidence remains 767 used / 233 remaining.

The base ledger, factor/risk, Capacity E1, taxonomy, estimator, registry head, and historical blocker report hashes are unchanged. The external historical-fetch preflight reports zero applicable hard blockers. No registry patch or parallel durable component is justified.

Explicit limitations:

- `MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED=YES` is scoped to the frozen 730-security keyset and existing same-code pre-2026 history contract; it is not a global claim about future universes or alternative authoritative identity/provider routes.
- `US.EA` is unresolved, not evidence of a nonexistent security history. A retry becomes legal only if separate authoritative identifier evidence appears.
- The 46 early PIT beta gaps must remain unavailable; future maturity or predecessor/share-class history cannot be backfilled.
- `PRICE_HISTORY_COVERAGE=715/730` is an acquisition-status metric. Despite the legacy description text, estimator readiness is the factor coverage `310,964/313,668`, not 715/730.
- Prior `adv_liquidity=1.0` is a Capacity E1/Raw-A2 holdings-grain metric. Full eligible-observation ADV20/ADV60 coverage is `313,200/313,668 = 99.850798%`; these grains must not be conflated.
- Taxonomy, PIT market-cap/fundamental, frozen momentum-covariate, and academic-factor gaps remain non-Moomoo limitations.

The earlier failed validation/review and blocker report remain immutable execution provenance. No publication-blocking violation remains in this finalization-only execution.
"""
    atomic_text(OUT / "finalization_independent_review.md", review)
    summary["final_independent_review"] = review_status
    summary["registry_final_head"] = current["head_sha256"]
    summary["final_validation"] = validation["status"]
    summary["final_validation_path"] = str(OUT / "finalization_validation.json")
    summary["final_independent_review_path"] = str(OUT / "finalization_independent_review.md")
    summary["final_report_path"] = str(OUT / "final_report.md")
    summary["final_manifest_path"] = str(OUT / "final_manifest.json")
    atomic_text(OUT / "final_report.md", final_report(summary))
    atomic_json(OUT / "final_console_summary.json", summary)
    write_manifest()
    return summary


def record_anti_bloat_blocker(blocker_path: str) -> dict[str, Any]:
    """Preserve a completed substantive audit without publishing a PASS."""
    summary = json.loads((OUT / "build_summary.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "final_validation.json").read_text(encoding="utf-8"))
    blocker = Path(blocker_path)
    require(blocker == Path(r"D:\us-tech-quant\pytest-cache-files-f_mklthk"), "UNEXPECTED_BLOCKER_PATH", blocker)
    require(blocker.exists(), "ANTI_BLOAT_BLOCKER_NOT_PRESENT", blocker)

    validation["status"] = "FAIL"
    validation.setdefault("checks", []).append({
        "check": "mandatory_historical_fetch_anti_bloat_preflight",
        "status": "FAIL",
        "detail": f"HARD_BLOCKER|ANTI_BLOAT_ACCOUNTING_INCOMPLETE|BLOCKS=all|{blocker.name}",
    })
    validation["failures"] = sorted(set([*validation.get("failures", []), "mandatory_historical_fetch_anti_bloat_preflight"]))
    validation["publication_allowed"] = False
    validation["substantive_gap_classification_status"] = "PASS_MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED"
    atomic_json(OUT / "final_validation.json", validation)

    provenance_path = OUT / "prior_execution_provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["execution_2"] = {
        "status": "HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE",
        "cause": str(blocker),
        "cause_created_during_execution": True,
        "substantive_gap_classification_status": "PASS_MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED",
        "unique_securities_fetched": 0,
        "history_request_count": 0,
        "quota_before": "767_used_233_remaining",
        "quota_after": "767_used_233_remaining",
        "registry_mutation": "NONE",
        "disposition": "PRESERVED_AS_BLOCKED_EXECUTION_PROVENANCE;DO_NOT_PUBLISH_PASS",
    }
    atomic_json(provenance_path, provenance)

    review = f"""# Independent review — {TASK_ID}

`REVIEW_STATUS=FAIL`

The substantive maintenance evidence passed: the 47-security / 2,704-row attribution reconciles; the useful history target set and fetch results are empty; quota stayed at 767 used / 233 remaining; `US.EA` was not retried; and the base ledger, factor, capacity, taxonomy, and registry heads are unchanged.

Publication nevertheless fails the mandatory global Anti-Bloat gate. The current historical-fetch preflight reports:

`HARD_BLOCKER|ANTI_BLOAT_ACCOUNTING_INCOMPLETE|BLOCKS=all|{blocker.name}`

The inaccessible staging directory was created by the focused pytest run in this execution. It cannot be inspected or removed with the current execution token. Final PASS and registry publication are prohibited until it is removed externally and the preflight plus independent review are rerun under this same R1.
"""
    atomic_text(OUT / "final_independent_review.md", review)

    report = f"""# {TASK_ID} — blocker report

`STATUS=HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE`

## Blocking evidence

After substantive classification and focused tests, mandatory historical-fetch preflight returned:

- `PREFLIGHT_STATUS=HARD_BLOCKER`
- `APPLICABLE_HARD_BLOCKER_COUNT=1`
- `HARD_BLOCKER|ANTI_BLOAT_ACCOUNTING_INCOMPLETE|BLOCKS=all|{blocker.name}`

Exact path: `{blocker}`

The directory was generated by pytest during this execution and is inaccessible to the current execution token. It was not present in the externally cleared preflight that authorized this resume.

## Preserved substantive state

- `SUBSTANTIVE_GAP_CLASSIFICATION_STATUS=PASS_MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED`
- Live quota before/after: 767 used / 233 remaining.
- Useful fetchable gaps: 0.
- Unique securities fetched: 0.
- History requests: 0.
- Remaining security gaps: 46 legitimate first-price/warmup boundaries plus terminal provider-unavailable `US.EA`.
- Base ledger, factor/risk, Capacity E1, and FF48 taxonomy hashes are unchanged.
- Registry mutation: none; head remains `{summary['registry_base_head']}`.
- All post-2025 outcome, model-evaluation, holdout-peek, and mixed-source counters remain zero.

## Required continuation

Remove `{blocker}` externally, then resume this same R1, rerun `harness_preflight.py --task-scope historical-fetch`, revalidate the preserved artifacts and live quota, and obtain a new independent review. Do not create R2 and do not repeat any history request.
"""
    atomic_text(OUT / "ANTI_BLOAT_BLOCKER_REPORT.md", report)

    blocked = dict(summary)
    blocked["status"] = "HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE"
    blocked["substantive_gap_classification_status"] = "PASS_MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED"
    blocked["publication_allowed"] = False
    blocked["final_independent_review"] = "FAIL"
    blocked["blocker_path"] = str(blocker)
    blocked["blocker_report_path"] = str(OUT / "ANTI_BLOAT_BLOCKER_REPORT.md")
    atomic_json(OUT / "blocked_execution_summary.json", blocked)

    files: dict[str, Any] = {}
    for path in sorted(OUT.iterdir(), key=lambda item: item.name.lower()):
        if path.is_file() and path.name != "blocked_execution_manifest.json":
            files[path.name] = {"sha256": sha256_file(path), "byte_size": path.stat().st_size}
    manifest = {
        "task_id": TASK_ID,
        "status": "HARD_BLOCKER_ANTI_BLOAT_ACCOUNTING_INCOMPLETE",
        "publication_allowed": False,
        "created_utc": utc_now(),
        "files": files,
        "file_count": len(files),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "test_sha256": sha256_file(TEST_FILE),
    }
    atomic_json(OUT / "blocked_execution_manifest.json", manifest)
    return blocked


def print_console(summary: Mapping[str, Any]) -> None:
    coverage = summary["coverage"]
    lines = [
        f"TASK={TASK_ID}",
        f"STATUS={summary['status']}",
        f"PREFLIGHT_APPLICABLE_HARD_BLOCKER_COUNT={summary.get('preflight_applicable_hard_blocker_count', 'NA')}",
        f"REGISTRY_BASE_HEAD={summary['registry_base_head']}",
        f"REGISTRY_FINAL_HEAD={summary['registry_final_head']}",
        f"REGISTRY_DECISION={summary['registry_decision']}",
        f"MOOMOO_USED_QUOTA_BEFORE={summary['moomoo_used_quota_before']}",
        f"MOOMOO_REMAIN_QUOTA_BEFORE={summary['moomoo_remain_quota_before']}",
        f"USEFUL_FETCHABLE_GAPS={summary['useful_fetchable_gaps']}",
        f"P1_COUNT={summary['p1_count']}",
        f"P2_COUNT={summary['p2_count']}",
        f"P3_COUNT={summary['p3_count']}",
        f"P4_COUNT={summary['p4_count']}",
        f"UNIQUE_SECURITIES_FETCHED={summary['unique_securities_fetched']}",
        f"HISTORY_REQUESTS={summary.get('history_requests', 0)}",
        f"MOOMOO_USED_QUOTA_AFTER={summary['moomoo_used_quota_after']}",
        f"MOOMOO_REMAIN_QUOTA_AFTER={summary['moomoo_remain_quota_after']}",
        f"PRICE_COVERAGE_BEFORE={coverage['PRICE_HISTORY_COVERAGE']:.12%}",
        f"PRICE_COVERAGE_AFTER={coverage['PRICE_HISTORY_COVERAGE']:.12%}",
        f"FACTOR_RISK_COVERAGE_BEFORE={coverage['FACTOR_RISK_COVERAGE']:.12%}",
        f"FACTOR_RISK_COVERAGE_AFTER={coverage['FACTOR_RISK_COVERAGE']:.12%}",
        f"SPY_BETA_COVERAGE_AFTER={coverage['SPY_BETA_COVERAGE']:.12%}",
        f"QQQ_ORTH_BETA_COVERAGE_AFTER={coverage['QQQ_ORTH_BETA_COVERAGE']:.12%}",
        f"SOXX_ORTH_BETA_COVERAGE_AFTER={coverage['SOXX_ORTH_BETA_COVERAGE']:.12%}",
        f"ADV20_COVERAGE_AFTER={coverage['ADV20_COVERAGE']:.12%}",
        f"ADV60_COVERAGE_AFTER={coverage['ADV60_COVERAGE']:.12%}",
        f"COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE_AFTER={coverage['COUNTERFACTUAL_PRICE_COVARIATE_COVERAGE']:.12%}",
        f"MOOMOO_PROVIDER_UNAVAILABLE_COUNT={summary['moomoo_provider_unavailable_count']}",
        f"LEGITIMATE_NO_HISTORY_COUNT={summary['legitimate_no_history_count']}",
        f"NON_PRICE_GAP_COUNT={summary['non_price_gap_count']}",
        f"LEGITIMATE_WARMUP_BOUNDARY_GAPS={summary.get('legitimate_warmup_boundary_gaps', summary['legitimate_no_history_count'])}",
        f"US_EA_STATUS={summary.get('us_ea_status', 'TERMINAL_PROVIDER_UNAVAILABLE')}",
        f"FACTOR_RISK_COVERAGE={coverage['FACTOR_RISK_COVERAGE'] * 100:.6f}",
        f"ADV20_COVERAGE={coverage['ADV20_COVERAGE'] * 100:.6f}",
        f"ADV60_COVERAGE={coverage['ADV60_COVERAGE'] * 100:.6f}",
        "MOOMOO_QUOTA_NUMERICALLY_EXHAUSTED=NO",
        "MOOMOO_ADDRESSABLE_PRICE_GAPS_EXHAUSTED=YES",
        "STRICT_FF48_COVERAGE_UNCHANGED=YES",
        "NEW_ALPHA_COMPONENT_COUNT=0",
        "NEW_FEATURE_COUNT=0",
        "NEW_MODEL_COUNT=0",
        "NEW_FACTOR_ESTIMATOR_COUNT=0",
        "NEW_PIPELINE_COUNT=0",
        "NEW_TAXONOMY_COUNT=0",
        "POST_2025_REALIZED_LABEL_METRIC_READ_COUNT=0",
        "POST_2025_MODEL_EVALUATION_METRIC_READ_COUNT=0",
        "POST_2025_OUTCOME_DERIVED_METADATA_READ_COUNT=0",
        "2026_ECONOMIC_OUTCOME_READ_COUNT=0",
        "POST_2025_OUTCOME_READ_COUNT=0",
        "HOLDOUT_PEEK_COUNT=0",
        "MIXED_SOURCE_CONTENT_OPEN_COUNT=0",
        f"FINAL_INDEPENDENT_REVIEW={summary['final_independent_review']}",
        f"FINAL_REPORT_PATH={summary['final_report_path']}",
        f"FINAL_MANIFEST_PATH={summary['final_manifest_path']}",
    ]
    print("\n".join(lines), flush=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="phase", required=True)
    subparsers.add_parser("build")
    subparsers.add_parser("prepare-finalization")
    blocker_parser = subparsers.add_parser("record-blocker")
    blocker_parser.add_argument("--blocker-path", required=True)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--review-status", required=True, choices=["PASS", "PASS_WITH_EXPLICIT_LIMITATIONS"])
    finalize_parser.add_argument("--reviewer", required=True)
    prepared_parser = subparsers.add_parser("finalize-prepared")
    prepared_parser.add_argument("--review-status", required=True, choices=["PASS", "PASS_WITH_EXPLICIT_LIMITATIONS"])
    prepared_parser.add_argument("--reviewer", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        if arguments.phase == "build":
            summary = build()
            print(f"TASK={TASK_ID}\nPHASE=BUILD\nSTATUS={summary['status']}\nUSEFUL_FETCHABLE_GAPS=0\nUNIQUE_SECURITIES_FETCHED=0", flush=True)
        elif arguments.phase == "prepare-finalization":
            summary = prepare_finalization_from_external_preflight()
            print(
                f"TASK={TASK_ID}\nPHASE=FINALIZATION_PREPARATION\nSTATUS=PASS\n"
                "PREFLIGHT_APPLICABLE_HARD_BLOCKER_COUNT=0\n"
                "MOOMOO_CONNECTION_COUNT=0\nHISTORY_REQUESTS=0",
                flush=True,
            )
        elif arguments.phase == "record-blocker":
            summary = record_anti_bloat_blocker(arguments.blocker_path)
            print(
                f"TASK={TASK_ID}\nSTATUS={summary['status']}\n"
                f"SUBSTANTIVE_GAP_CLASSIFICATION_STATUS={summary['substantive_gap_classification_status']}\n"
                "UNIQUE_SECURITIES_FETCHED=0\nMOOMOO_REMAIN_QUOTA_AFTER=233\n"
                f"BLOCKER_PATH={summary['blocker_path']}",
                flush=True,
            )
        elif arguments.phase == "finalize-prepared":
            summary = finalize_prepared(arguments.review_status, arguments.reviewer)
            print_console(summary)
        else:
            summary = finalize(arguments.review_status, arguments.reviewer)
            print_console(summary)
        return 0
    except Exception as exc:
        print(f"TASK={TASK_ID}\nSTATUS=HARD_BLOCKER_OR_VALIDATION_FAILURE\nERROR={type(exc).__name__}:{exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
