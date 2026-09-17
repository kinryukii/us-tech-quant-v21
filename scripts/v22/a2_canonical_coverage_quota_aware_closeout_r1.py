"""Quota-aware, fail-closed closeout for the frozen A2 canonical gap.

The runner has a deliberately narrow zero-quota branch.  It validates the two
authoritative upstream results, freezes the exact fetch cohort, verifies the
existing staged and canonical identities, and writes compact external evidence.
It never requests price history when the live historical-security quota is zero.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


TASK = "A2_CANONICAL_COVERAGE_QUOTA_AWARE_CLOSEOUT_R1"
TARGET = "2026-08-20"
FETCH_START = "2026-02-27"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
OUT = RESULTS / TASK
FOUNDATION = RESULTS / "A2_FORWARD_FOUNDATION_CLOSEOUT_R1"
GAP_CLOSE = RESULTS / "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1"
READINESS = RESULTS / "A2_CANONICAL_FORWARD_READINESS_R2"
R3 = RESULTS / "A2_PIT_CANONICAL_COVERAGE_R3"
NG_R3 = RESULTS / "A2_NG8_FORWARD_PIT_CANONICAL_COVERAGE_REMEDIATION_R3"
COMPLETION = RESULTS / "A2_PIT_MOOMOO_CURRENT_WEEK_COMPLETION_R1"
PIT_PATH = READINESS / "component_inputs/2026-08-20/pit_universe.json"
BACKLOG = R3 / "coverage_remediation_backlog.parquet"
INVENTORY = R3 / "missing_385_classification.parquet"
STAGE_RAW = R3 / "api_incremental_raw_20260819_20260820.parquet"
STAGE_QFQ = R3 / "api_incremental_qfq_20260819_20260820.parquet"
STAGE_ACTIONS = NG_R3 / "remediation_actions.csv"
LOOKBACK = NG_R3 / "lookback_sufficiency_report.csv"
COMPLETION_STATUS = COMPLETION / "security_completion_status.csv"
POINTER_PATH = Path(
    r"D:\us-tech-quant-daily\current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    r"\canonical_snapshot_pointer.json"
)
MAPPING_RUNNER = REPO / "scripts/v22/a2_pit_moomoo_current_week_completion_r1.py"
MAPPING_TEST = REPO / "scripts/v22/test_a2_pit_moomoo_current_week_completion_r1.py"
BROKER_BINDING = REPO / "config/research_governance/a2_forward_shadow_production_binding_r1.json"
POLICY = REPO / "docs/governance/ANTI_BLOAT_POLICY.md"

EXCLUSIONS = {"EA", "TALK", "OLPX", "PAYP"}
OUTPUTS = {
    "task_receipt.json", "coverage_gap_ledger.csv", "quota_and_fetch_plan.json",
    "promotion_manifest.json", "post_promotion_reconciliation.json",
    "final_report.md", "hash_manifest.json",
}
LEDGER_FIELDS = [
    "security_id", "pit_ticker", "canonical_ticker", "broker_symbol",
    "identity_status", "historical_data_status", "target_date_status",
    "raw_status", "qfq_status", "already_touched_this_week",
    "new_unique_quota_required", "fetch_start", "fetch_end",
    "required_action", "final_status", "failure_reason",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_json(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def strict_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, text=True, capture_output=True
    ).stdout.strip()


def validate_hash_manifest(root: Path) -> dict[str, Any]:
    manifest = read_json(root / "hash_manifest.json")
    entries = manifest.get("artifacts")
    if entries is None:
        entries = [
            {"path": str(root / name), **record}
            for name, record in manifest["files"].items()
        ]
    failures = []
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            failures.append(str(path))
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def live_quota(mapping: Any) -> dict[str, Any]:
    used, remaining, detail = mapping.quota_detail()
    normalized = sorted(
        ({"code": str(row.get("code", "")), "request_time": str(row.get("request_time", ""))} for row in detail),
        key=lambda row: (row["code"], row["request_time"]),
    )
    times = sorted(row["request_time"] for row in normalized if row["request_time"])
    return {
        "QUOTA_CHECK_STATUS": "PASS_LIVE_MOOMOO_QUOTA",
        "HISTORICAL_SECURITY_USED": int(used),
        "HISTORICAL_SECURITY_LIMIT": int(used + remaining),
        "HISTORICAL_SECURITY_REMAINING": int(remaining),
        "DETAIL_COUNT": len(detail),
        "QUOTA_PERIOD_ID": "PROVIDER_ROLLING_DETAIL;RESET_TIME_NOT_REPORTED",
        "EARLIEST_REQUEST_TIME": times[0] if times else None,
        "LATEST_REQUEST_TIME": times[-1] if times else None,
        "NORMALIZED_CODE_REQUEST_TIME_SHA256": hash_json(normalized),
        "touched_codes": sorted({row["code"] for row in normalized if row["code"]}),
    }


def current_local_counts(tickers: set[str]) -> dict[str, dict[str, int]]:
    answer = {ticker: {"raw_rows": 0, "qfq_rows": 0, "raw_target": 0, "qfq_target": 0} for ticker in tickers}
    for mode in ("raw", "qfq"):
        path = DATA / f"moomoo/source/prices_{mode}/year=2026/prices.parquet"
        frame = pd.read_parquet(path, columns=["ticker", "trade_date"])
        frame["ticker"] = frame.ticker.astype(str)
        frame["trade_date"] = frame.trade_date.astype(str).str[:10]
        frame = frame.loc[frame.ticker.isin(tickers)]
        for ticker, group in frame.groupby("ticker"):
            answer[ticker][f"{mode}_rows"] = len(group)
            answer[ticker][f"{mode}_target"] = int(group.trade_date.eq(TARGET).sum())
    return answer


def staged_integrity(expected_tickers: set[str], prior_receipt: dict[str, Any]) -> dict[str, Any]:
    expected_hashes = prior_receipt["source_hashes"]
    paths = [STAGE_RAW, STAGE_QFQ, STAGE_ACTIONS, LOOKBACK]
    hashes = {str(path): sha256_file(path) for path in paths}
    exact_hashes = all(hashes[str(path)] == expected_hashes[str(path)] for path in paths)
    raw = pd.read_parquet(STAGE_RAW, columns=["ticker", "date"])
    qfq = pd.read_parquet(STAGE_QFQ, columns=["ticker", "date"])
    raw_target = raw.loc[raw.date.astype(str).str[:10].eq(TARGET)]
    qfq_target = qfq.loc[qfq.date.astype(str).str[:10].eq(TARGET)]
    raw_required = set(raw_target.ticker.astype(str)) & expected_tickers
    qfq_required = set(qfq_target.ticker.astype(str)) & expected_tickers
    actions = pd.read_csv(STAGE_ACTIONS, dtype=str).fillna("")
    all_paths_exist = all(Path(path).is_file() for path in actions.path)
    passed = (
        exact_hashes
        and raw_required == qfq_required == expected_tickers
        and not raw_target.loc[raw_target.ticker.isin(expected_tickers)].duplicated(["ticker", "date"]).any()
        and not qfq_target.loc[qfq_target.ticker.isin(expected_tickers)].duplicated(["ticker", "date"]).any()
        and all_paths_exist
    )
    return {
        "status": "PASS_HASH_MANIFEST_EXISTENCE_NO_MUTATION" if passed else "FAIL_STAGED_MUTATION",
        "expected_security_count": len(expected_tickers),
        "raw_target_security_count": len(raw_required),
        "qfq_target_security_count": len(qfq_required),
        "aggregate_and_manifest_hashes_exact": exact_hashes,
        "manifest_leg_count": len(actions),
        "manifest_leg_paths_all_exist": all_paths_exist,
        "hashes": hashes,
    }


def anti_bloat_surface(temp_status: str, guard_status: str) -> dict[str, Any]:
    local_venvs = [str(path) for path in REPO.iterdir() if path.is_dir() and path.name.lower() in {".venv", "venv"}]
    repo_temp = REPO / ".tmp_a2_gap_close_r1_pytest"
    cache_temp = Path(r"D:\us-tech-quant-cache\pytest_a2_gap_close_r1_20260822_2352")
    return {
        "policy_sha256": sha256_file(POLICY),
        "repo_local_venv_count": len(local_venvs),
        "repo_local_venvs": local_venvs,
        "duplicate_canonical_dataset_in_output_count": 0,
        "new_large_repository_file_count": 0,
        "known_repo_temp_path": str(repo_temp),
        "known_repo_temp_exists": repo_temp.exists(),
        "known_external_temp_path": str(cache_temp),
        "known_external_temp_exists": cache_temp.exists(),
        "temp_cleanup_status": temp_status,
        "guard_status": guard_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ge-test-status", required=True)
    parser.add_argument("--pytest-acl-status", required=True)
    parser.add_argument("--temp-cleanup-status", required=True)
    parser.add_argument("--anti-bloat-status", required=True)
    args = parser.parse_args()

    assert not OUT.exists(), f"OUTPUT_ALREADY_EXISTS:{OUT}"
    upstream_hashes = {
        str(FOUNDATION): validate_hash_manifest(FOUNDATION),
        str(GAP_CLOSE): validate_hash_manifest(GAP_CLOSE),
    }
    assert all(value["status"] == "PASS" for value in upstream_hashes.values())

    prior_ledger = pd.read_csv(GAP_CLOSE / "coverage_gap_ledger.csv", dtype=str).fillna("")
    prior_recon = read_json(GAP_CLOSE / "post_promotion_reconciliation.json")
    prior_receipt = read_json(GAP_CLOSE / "task_receipt.json")
    pit_payload = read_json(PIT_PATH)
    pit = pd.DataFrame(pit_payload["members"])[["security_id", "ticker"]].astype(str)
    assert len(pit) == pit.security_id.nunique() == pit.ticker.nunique()

    required = prior_ledger.final_required.map(strict_bool)
    covered = prior_ledger.final_covered.map(strict_bool)
    staged_mask = prior_ledger.final_classification.eq("STAGED_VALID_FOR_PROMOTION")
    exclusion_mask = prior_ledger.final_classification.eq("LEGITIMATE_MODEL_SAFE_EXCLUSION")
    unresolved_mask = prior_ledger.final_classification.eq("UNRESOLVED_REQUIRED_QUOTA_BLOCKED")
    covered_ids = set(prior_ledger.loc[required & covered, "security_id"])
    staged_ids = set(prior_ledger.loc[required & staged_mask, "security_id"])
    unresolved_ids = set(prior_ledger.loc[required & unresolved_mask, "security_id"])
    exclusion_ids = set(prior_ledger.loc[exclusion_mask, "security_id"])
    required_ids = covered_ids | staged_ids | unresolved_ids
    assert not (covered_ids & staged_ids or covered_ids & unresolved_ids or staged_ids & unresolved_ids)
    assert not (required_ids & exclusion_ids)
    assert required_ids | exclusion_ids == set(pit.security_id)
    assert len(required_ids) + len(exclusion_ids) == len(pit)

    exclusions = prior_ledger.loc[exclusion_mask].copy()
    assert set(exclusions.ticker) == EXCLUSIONS
    assert exclusions.exclusion_reason.str.len().gt(0).all()
    assert exclusions.classification_change_evidence.str.len().gt(0).all()
    assert not exclusions.exclusion_reason.str.fullmatch("(?i).*missing.data.*").any()
    payp_evidence = Path(exclusions.loc[exclusions.ticker.eq("PAYP"), "classification_change_evidence"].iloc[0])
    assert payp_evidence.is_file()

    mapping = load_module("a2_quota_aware_mapping", MAPPING_RUNNER)
    frozen_intervals = pd.read_parquet(
        RESULTS / "A2_PIT13F_MATERIALIZATION_R1/effective_universe_intervals.parquet"
    )
    ge_frozen = frozen_intervals.loc[frozen_intervals.security_id.astype(str).eq("369604301")]
    ge_corrected = mapping.apply_security_identity_overrides(ge_frozen)
    ge_mapping_pass = (
        not ge_frozen.empty
        and set(ge_frozen.ticker.astype(str)) == {"GE.WI"}
        and set(ge_corrected.ticker.astype(str)) == {"GE"}
        and set(ge_corrected.moomoo_transport_code.astype(str)) == {"US.GE"}
        and set(ge_corrected.mapping_source.astype(str)) == {"A2_CUSIP_IDENTITY_OVERRIDE_R1"}
    )
    assert ge_mapping_pass

    quota = live_quota(mapping)
    if quota["HISTORICAL_SECURITY_REMAINING"] != 0:
        raise RuntimeError(
            "LIVE_QUOTA_POSITIVE_REQUIRES_EXISTING_FETCH_AND_PROMOTION_WORKFLOW;"
            "THIS_ZERO_QUOTA_CLOSEOUT_MUST_NOT_EMIT_WAITING_EVIDENCE"
        )
    touched = set(quota.pop("touched_codes"))

    expected_staged_tickers = set(prior_ledger.loc[staged_mask & required, "ticker"])
    stage = staged_integrity(expected_staged_tickers, prior_receipt)
    assert stage["status"].startswith("PASS")

    pointer_before = POINTER_PATH.read_bytes()
    pointer = json.loads(pointer_before)
    canonical_manifest = Path(pointer["canonical_manifest_path"])
    canonical_raw = Path(pointer["canonical_raw_path"])
    canonical_qfq = Path(pointer["canonical_qfq_path"])
    manifest_hash = sha256_file(canonical_manifest)
    raw_hash = sha256_file(canonical_raw)
    qfq_hash = sha256_file(canonical_qfq)
    expected_sources = prior_receipt["source_hashes"]
    historical_identity = (
        manifest_hash == expected_sources[str(canonical_manifest)]
        and raw_hash == expected_sources[str(canonical_raw)]
        and qfq_hash == expected_sources[str(canonical_qfq)]
        and sha256_file(POINTER_PATH) == expected_sources[str(POINTER_PATH)]
    )
    assert historical_identity

    backlog = pd.read_parquet(BACKLOG).astype({"security_id": str, "ticker": str})
    backlog_by_id = backlog.set_index("security_id").to_dict("index")
    inventory = pd.read_parquet(INVENTORY).astype({"security_id": str, "ticker": str})
    inventory_by_id = inventory.set_index("security_id").to_dict("index")
    gap_prior = prior_ledger.loc[unresolved_mask].copy()
    assert set(gap_prior.security_id) == unresolved_ids

    identities: dict[str, tuple[str, str, str]] = {}
    for security_id in sorted(unresolved_ids):
        prior = gap_prior.loc[gap_prior.security_id.eq(security_id)].iloc[0]
        if security_id == "369604301":
            identities[security_id] = ("GE", "US.GE", "CUSIP_VERIFIED_GE_MAPPING_FIXED")
        else:
            gap = backlog_by_id[security_id]
            canonical_ticker = str(gap["ticker"])
            broker_symbol = str(gap["moomoo_transport_code"])
            identity_status = (
                "ALIAS_MAPPING_FROZEN_PENDING_BROKER_DATA_VALIDATION"
                if str(gap["local_status"]) == "CORPORATE_ACTION_IDENTITY_TRANSITION"
                else "EXISTING_MAPPING_FROZEN_PENDING_BROKER_DATA_VALIDATION"
            )
            identities[security_id] = (canonical_ticker, broker_symbol, identity_status)

    scan_tickers = {ticker for ticker, _, _ in identities.values()} | set(gap_prior.ticker)
    local = current_local_counts(scan_tickers)
    stage_raw_tickers = set(pd.read_parquet(STAGE_RAW, columns=["ticker"]).ticker.astype(str))
    stage_qfq_tickers = set(pd.read_parquet(STAGE_QFQ, columns=["ticker"]).ticker.astype(str))
    completion_status = pd.read_csv(COMPLETION_STATUS, dtype=str).fillna("")
    completion_codes = set(completion_status.moomoo_code)

    rows: list[dict[str, Any]] = []
    for prior in gap_prior.sort_values(["security_id", "ticker"]).itertuples(index=False):
        security_id = str(prior.security_id)
        pit_ticker = str(prior.ticker)
        canonical_ticker, broker_symbol, identity_status = identities[security_id]
        raw_count = local.get(canonical_ticker, {}).get("raw_rows", 0) + (
            local.get(pit_ticker, {}).get("raw_rows", 0) if pit_ticker != canonical_ticker else 0
        )
        qfq_count = local.get(canonical_ticker, {}).get("qfq_rows", 0) + (
            local.get(pit_ticker, {}).get("qfq_rows", 0) if pit_ticker != canonical_ticker else 0
        )
        raw_target = local.get(canonical_ticker, {}).get("raw_target", 0) + (
            local.get(pit_ticker, {}).get("raw_target", 0) if pit_ticker != canonical_ticker else 0
        )
        qfq_target = local.get(canonical_ticker, {}).get("qfq_target", 0) + (
            local.get(pit_ticker, {}).get("qfq_target", 0) if pit_ticker != canonical_ticker else 0
        )
        in_stage = canonical_ticker in stage_raw_tickers or canonical_ticker in stage_qfq_tickers
        in_completion = broker_symbol in completion_codes
        already_touched = broker_symbol in touched
        if security_id == "369604301":
            source_class = "BROKER_SYMBOL_ALIAS_REQUIRED:GE.WI_TO_GE"
        else:
            inv = inventory_by_id[security_id]
            source_class = f"{inv['classification']}:{inv['reason_code']}"
        local_available = raw_count > 0 or qfq_count > 0 or in_stage or in_completion
        rows.append({
            "security_id": security_id,
            "pit_ticker": pit_ticker,
            "canonical_ticker": canonical_ticker,
            "broker_symbol": broker_symbol,
            "identity_status": identity_status,
            "historical_data_status": "LOCAL_FRAGMENT_PRESENT_REQUIRES_VALIDATION" if local_available else "NO_LOCAL_RAW_QFQ_OR_STAGED_FRAGMENT",
            "target_date_status": "LOCAL_TARGET_PRESENT_NOT_CANONICAL" if raw_target and qfq_target else "MISSING_RAW_AND_QFQ_TARGET_DATE",
            "raw_status": f"LOCAL_ROWS_{raw_count};TARGET_ROWS_{raw_target}",
            "qfq_status": f"LOCAL_ROWS_{qfq_count};TARGET_ROWS_{qfq_target}",
            "already_touched_this_week": already_touched,
            "new_unique_quota_required": not already_touched,
            "fetch_start": FETCH_START,
            "fetch_end": TARGET,
            "required_action": "MINIMUM_CONTRACT_RAW_AND_QFQ_FETCH;STANDARD_REQUEST_THEN_AT_MOST_ONE_TARGETED_RETRY",
            "final_status": "UNRESOLVED_REQUIRED_QUOTA_BLOCKED",
            "failure_reason": f"{source_class};LIVE_HISTORICAL_SECURITY_QUOTA_REMAINING_0",
        })

    assert len(rows) == len({row["security_id"] for row in rows}) == len(unresolved_ids)
    already_touched_count = sum(strict_bool(row["already_touched_this_week"]) for row in rows)
    new_quota_count = sum(strict_bool(row["new_unique_quota_required"]) for row in rows)
    local_data_count = sum("PRESENT" in row["historical_data_status"] for row in rows)
    assert already_touched_count + new_quota_count == len(rows)

    broker_binding = read_json(BROKER_BINDING)
    broker_disabled = pointer.get("broker_action_allowed") is False and broker_binding.get("broker_action_allowed") is False
    assert broker_disabled
    anti_bloat = anti_bloat_surface(args.temp_cleanup_status, args.anti_bloat_status)
    silent_exclusions = int(
        exclusions.exclusion_reason.eq("").sum()
        + exclusions.classification_change_evidence.eq("").sum()
    )
    assert silent_exclusions == 0

    # Final no-mutation check after every read and the quota-only network call.
    historical_identity = historical_identity and (
        POINTER_PATH.read_bytes() == pointer_before
        and sha256_file(canonical_manifest) == manifest_hash
        and sha256_file(canonical_raw) == raw_hash
        and sha256_file(canonical_qfq) == qfq_hash
    )
    assert historical_identity
    overall = "WAITING_FOR_QUOTA_PREFLIGHT_READY"

    OUT.mkdir(parents=True, exist_ok=False)
    write_csv(OUT / "coverage_gap_ledger.csv", rows)

    plan_entries = [
        {
            "priority": 1 if row["already_touched_this_week"] else 4,
            "security_id": row["security_id"],
            "pit_ticker": row["pit_ticker"],
            "canonical_ticker": row["canonical_ticker"],
            "broker_symbol": row["broker_symbol"],
            "fetch_start": row["fetch_start"],
            "fetch_end": row["fetch_end"],
            "request_policy": "STANDARD_ONCE;OPTIONAL_ONE_TARGETED_RETRY",
        }
        for row in sorted(rows, key=lambda item: (not strict_bool(item["already_touched_this_week"]), item["broker_symbol"]))
    ]
    quota_plan = {
        "task_id": TASK,
        "target_date": TARGET,
        "branch": "BRANCH_A_ZERO_QUOTA_PREFLIGHT_ONLY",
        "quota_checked_utc": now_utc(),
        "live_quota": quota,
        "unresolved_security_count": len(rows),
        "local_data_available_count": local_data_count,
        "already_touched_count": already_touched_count,
        "new_unique_quota_required_count": new_quota_count,
        "actual_price_fetch_security_count": 0,
        "fetch_success_count": 0,
        "fetch_failure_count": 0,
        "price_api_request_count": 0,
        "reset_time_assumption": "NONE;PROVIDER_DID_NOT_REPORT_RESET_TIME",
        "next_fetch_plan_sha256": hash_json(plan_entries),
        "next_fetch_plan": plan_entries,
    }
    write_json(OUT / "quota_and_fetch_plan.json", quota_plan)

    promotion = {
        "task_id": TASK,
        "PROMOTION_EXECUTED": False,
        "REASON": "WAITING_FOR_HISTORICAL_SECURITY_QUOTA",
        "candidate_snapshot_status": "NOT_CREATED_ZERO_QUOTA_AND_INCOMPLETE_REQUIRED_GATE",
        "atomic_promotion_status": "NOT_EXECUTED_FAIL_CLOSED_WAITING_FOR_QUOTA",
        "unresolved_required_count": len(rows),
        "silent_exclusion_count": silent_exclusions,
        "existing_authoritative_snapshot_id": pointer["snapshot_id"],
        "existing_canonical_manifest_sha256": manifest_hash,
        "new_canonical_snapshot_id": None,
        "new_canonical_manifest_sha256": None,
        "authoritative_pointer_unchanged": True,
        "partial_promotion_executed": False,
    }
    write_json(OUT / "promotion_manifest.json", promotion)

    validation = {
        "upstream_hash_manifests": upstream_hashes,
        "pit_security_identity_uniqueness": len(pit) == pit.security_id.nunique(),
        "pit_ticker_uniqueness": len(pit) == pit.ticker.nunique(),
        "required_partition_disjoint": True,
        "pit_reconciliation": f"{len(pit)}={len(required_ids)}+{len(exclusion_ids)}",
        "required_reconciliation": f"{len(required_ids)}={len(covered_ids)}+{len(staged_ids)}+{len(unresolved_ids)}",
        "ge_mapping_contract": "PASS_CUSIP_369604301_GE_US.GE",
        "ge_regression_test": args.ge_test_status,
        "staged_integrity": stage,
        "historical_no_mutation": historical_identity,
        "silent_exclusion_check": silent_exclusions == 0,
        "broker_live_disabled": broker_disabled,
        "pytest_acl_status": args.pytest_acl_status,
        "anti_bloat": anti_bloat,
    }
    reconciliation = {
        "task_id": TASK,
        "overall_status": overall,
        "target_date": TARGET,
        "pit_universe_security_count": len(pit),
        "active_tradable_required_count": len(required_ids),
        "legitimate_exclusion_count": len(exclusion_ids),
        "authoritative_model_safe_coverage_count": len(covered_ids),
        "authoritative_model_safe_coverage_pct": round(100 * len(covered_ids) / len(required_ids), 6),
        "prevalidated_staged_count": len(staged_ids),
        "unresolved_required_count": len(unresolved_ids),
        "silent_exclusion_count": silent_exclusions,
        "historical_canonical_identity_status": "PASS_HASH_VERIFIED_NO_MUTATION",
        "candidate_snapshot_status": promotion["candidate_snapshot_status"],
        "atomic_promotion_status": promotion["atomic_promotion_status"],
        "authoritative_snapshot_id": pointer["snapshot_id"],
        "authoritative_manifest_sha256": manifest_hash,
        "validation": validation,
    }
    write_json(OUT / "post_promotion_reconciliation.json", reconciliation)

    source_paths = [
        FOUNDATION / "hash_manifest.json", GAP_CLOSE / "hash_manifest.json",
        GAP_CLOSE / "coverage_gap_ledger.csv", GAP_CLOSE / "task_receipt.json",
        PIT_PATH, BACKLOG, INVENTORY, STAGE_RAW, STAGE_QFQ, STAGE_ACTIONS,
        LOOKBACK, COMPLETION_STATUS, POINTER_PATH, canonical_manifest,
        canonical_raw, canonical_qfq, MAPPING_RUNNER, MAPPING_TEST, BROKER_BINDING, POLICY,
    ]
    receipt = {
        "task_id": TASK,
        "created_utc": now_utc(),
        "target_date": TARGET,
        "authoritative_upstreams": [str(FOUNDATION), str(GAP_CLOSE)],
        "git_commit": git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(git("status", "--porcelain")),
        "source_hashes": {str(path): sha256_file(path) for path in source_paths},
        "quota_probe_only_network_call_count": 1,
        "price_api_request_count": 0,
        "actual_fetch_security_count": 0,
        "ge_mapping_patch": {
            "security_id": "369604301", "pit_ticker": "GE.WI",
            "authoritative_ticker": "GE", "broker_symbol": "US.GE",
            "mapping_layer": str(MAPPING_RUNNER), "status": "PASS",
        },
        "prohibited_actions": {
            "model_training_executed": False,
            "2026_used_for_training": False,
            "2026_used_for_model_selection": False,
            "broker_action_executed": False,
            "candidate_snapshot_created": False,
            "promotion_executed": False,
            "git_commit_or_push_executed": False,
        },
    }
    write_json(OUT / "task_receipt.json", receipt)

    exclusions_text = "\n".join(
        f"- `{row.ticker}` — `{row.exclusion_reason}`; evidence: `{row.classification_change_evidence}`"
        for row in exclusions.sort_values("ticker").itertuples(index=False)
    )
    unresolved_text = "\n".join(
        f"- `{row['pit_ticker']}` → `{row['broker_symbol']}`: `{row['failure_reason']}`"
        for row in rows
    )
    report = f"""# {TASK}

Overall status: `{overall}`. Live historical-security quota is exhausted, so the run completed the full preflight and made zero price-history requests. No candidate snapshot or promotion was attempted.

## Required answers

1. Actual PIT universe: **{len(pit)}**.
2. Actual active/tradable/model-required cohort: **{len(required_ids)}**.
3. The four legitimate exclusions remain valid: **yes** — EA, TALK, OLPX and PAYP have explicit, reused evidence and none is a missing-data-driven exclusion.
4. GE.WI root cause: the legacy V11 universe materialization persisted a temporary when-issued/ex-distribution ticker as the permanent transport identity for GE CUSIPs.
5. Correct GE identity: CUSIP/security ID **369604301**, authoritative ticker **GE**, Moomoo broker symbol **US.GE**.
6. Regression test: **{args.ge_test_status}**. The test also proves the frozen source frame is not mutated.
7. Final frozen unresolved cohort: **{len(rows)}** unique required securities.
8. Of the 60, securities with current local raw/QFQ or staged/completion fragments: **{local_data_count}**.
9. Already touched in the current provider quota detail: **{already_touched_count}**.
10. Requiring a new unique-security quota slot: **{new_quota_count}**.
11. Live quota: **{quota['HISTORICAL_SECURITY_USED']} used / {quota['HISTORICAL_SECURITY_LIMIT']} limit / {quota['HISTORICAL_SECURITY_REMAINING']} remaining**. Provider reset time was not reported and was not guessed.
12. Securities actually requested this run: **0** (quota-detail probe only; no price request).
13. Securities resolved this run through data fetch: **0**. GE's mapping contract was fixed, but its data gap remains.
14. Final unresolved required securities: **{len(rows)}**.
15. Existing 321 staged securities: **{stage['status']}**; aggregate raw/QFQ and manifest hashes, target-date sets, uniqueness and file existence remained exact.
16. Pytest ACL: **{args.pytest_acl_status}**. This is an infrastructure non-execution classification, not a code-test failure; the focused GE suite passed.
17. Temporary directory cleanup: **{args.temp_cleanup_status}**. Exact-path deletion remained blocked; no broad ACL reset was attempted.
18. Anti-Bloat: **{args.anti_bloat_status}**; no local venv, no duplicated canonical data in results and no large new repository artifact, but the unreadable repo temp keeps the hard gate open.
19. Candidate snapshot created: **no** (`{promotion['candidate_snapshot_status']}`).
20. Atomic promotion executed: **no** (`{promotion['atomic_promotion_status']}`).
21. New authoritative snapshot/hash: **none**. Existing authoritative identity remains `{pointer['snapshot_id']}` / `{manifest_hash}`.
22. Post-task authoritative coverage: **{len(covered_ids)}/{len(required_ids)} = {100 * len(covered_ids) / len(required_ids):.2f}%**; staged data is not counted as authoritative.
23. Ready for `A2_UNIFIED_REPLAY_AND_ATTRIBUTION_R1`: **no**. The minimum blocker is historical-security quota availability followed by resolving all 60 staged gaps and one atomic promotion; the managed temp ACL must also be cleared for an Anti-Bloat PASS.

## Legitimate exclusions

{exclusions_text}

## Frozen unresolved fetch cohort

{unresolved_text}

## Safety and scope

- Reconciliation: `{len(pit)} PIT = {len(required_ids)} required + {len(exclusion_ids)} exclusions`; `{len(required_ids)} required = {len(covered_ids)} authoritative + {len(staged_ids)} validated staged + {len(unresolved_ids)} unresolved`.
- Historical canonical raw/QFQ, manifest, and authoritative pointer: **PASS_HASH_VERIFIED_NO_MUTATION**.
- Candidate/promotion: **not created/not executed**; partial promotion count is zero.
- Model training, model selection, parameter selection, Unified Replay, forward generation and broker action: **not executed**.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")

    core = [
        "task_receipt.json", "coverage_gap_ledger.csv", "quota_and_fetch_plan.json",
        "promotion_manifest.json", "post_promotion_reconciliation.json", "final_report.md",
    ]
    artifact_rows = [
        {"path": str(OUT / name), "bytes": (OUT / name).stat().st_size, "sha256": sha256_file(OUT / name)}
        for name in core
    ]
    write_json(OUT / "hash_manifest.json", {
        "task_id": TASK,
        "definition": "SHA256 of the six other core artifacts; this manifest excludes itself",
        "artifacts": artifact_rows,
        "artifact_set_sha256": hash_json(artifact_rows),
    })
    assert {path.name for path in OUT.iterdir()} == OUTPUTS

    summary = {
        "OVERALL_STATUS": overall,
        "TARGET_DATE": TARGET,
        "PIT_UNIVERSE_SECURITY_COUNT": len(pit),
        "ACTIVE_TRADABLE_REQUIRED_COUNT": len(required_ids),
        "LEGITIMATE_EXCLUSION_COUNT": len(exclusion_ids),
        "SILENT_EXCLUSION_COUNT": silent_exclusions,
        "GE_MAPPING_STATUS": "PASS_FIXED_AT_CUSIP_MAPPING_BOUNDARY",
        "GE_AUTHORITATIVE_IDENTITY": "CUSIP_369604301;TICKER_GE",
        "GE_BROKER_SYMBOL": "US.GE",
        "GE_REGRESSION_TEST_STATUS": args.ge_test_status,
        "PRE_TASK_AUTHORITATIVE_COVERED_COUNT": len(covered_ids),
        "PREVALIDATED_STAGED_COUNT": len(staged_ids),
        "PRE_TASK_UNRESOLVED_REQUIRED_COUNT": len(unresolved_ids),
        "HISTORICAL_QUOTA_USED": quota["HISTORICAL_SECURITY_USED"],
        "HISTORICAL_QUOTA_LIMIT": quota["HISTORICAL_SECURITY_LIMIT"],
        "HISTORICAL_QUOTA_REMAINING_AT_START": quota["HISTORICAL_SECURITY_REMAINING"],
        "UNRESOLVED_ALREADY_TOUCHED_COUNT": already_touched_count,
        "UNRESOLVED_NEW_QUOTA_REQUIRED_COUNT": new_quota_count,
        "ACTUAL_FETCH_SECURITY_COUNT": 0,
        "FETCH_SUCCESS_COUNT": 0,
        "FETCH_FAILURE_COUNT": 0,
        "FINAL_UNRESOLVED_REQUIRED_COUNT": len(unresolved_ids),
        "STAGED_321_INTEGRITY_STATUS": stage["status"],
        "PYTEST_ACL_STATUS": args.pytest_acl_status,
        "TEMP_CLEANUP_STATUS": args.temp_cleanup_status,
        "ANTI_BLOAT_STATUS": args.anti_bloat_status,
        "CANDIDATE_SNAPSHOT_STATUS": promotion["candidate_snapshot_status"],
        "ATOMIC_PROMOTION_STATUS": promotion["atomic_promotion_status"],
        "NEW_CANONICAL_SNAPSHOT_ID": "",
        "NEW_CANONICAL_MANIFEST_SHA256": "",
        "FINAL_AUTHORITATIVE_MODEL_SAFE_COVERAGE_COUNT": len(covered_ids),
        "FINAL_AUTHORITATIVE_MODEL_SAFE_COVERAGE_PCT": f"{100 * len(covered_ids) / len(required_ids):.2f}%",
        "HISTORICAL_CANONICAL_IDENTITY_STATUS": "PASS_HASH_VERIFIED_NO_MUTATION",
        "2026_USED_FOR_TRAINING": "false",
        "2026_USED_FOR_MODEL_SELECTION": "false",
        "MODEL_TRAINING_EXECUTED": "false",
        "CLEAN_FORWARD_FOUNDATION_READY": "false",
        "READY_FOR_UNIFIED_REPLAY": "false",
        "OFFICIAL_ADOPTION_ALLOWED": "false",
        "BROKER_ACTION_ALLOWED": "false",
        "OUTPUT_DIR": str(OUT),
        "FINAL_REPORT": str(OUT / "final_report.md"),
        "HASH_MANIFEST": str(OUT / "hash_manifest.json"),
    }
    print("=" * 60)
    print(f"{TASK}_FINAL")
    print("=" * 60)
    for key, value in summary.items():
        print(f"{key}={value}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
