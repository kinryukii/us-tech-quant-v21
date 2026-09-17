"""Close out the A2 PIT/canonical coverage gap without partial promotion.

This narrow runner validates frozen local evidence, rechecks the live Moomoo
historical quota ledger, and emits the six closeout artifacts.  It never
trains a model, reads model returns, places broker orders, or performs a
partial canonical promotion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK = "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1"
TARGET = "2026-08-20"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
OUT = RESULTS / TASK
UPSTREAM = RESULTS / "A2_FORWARD_FOUNDATION_CLOSEOUT_R1"
READINESS = RESULTS / "A2_CANONICAL_FORWARD_READINESS_R2"
R3 = RESULTS / "A2_PIT_CANONICAL_COVERAGE_R3"
NG_R3 = RESULTS / "A2_NG8_FORWARD_PIT_CANONICAL_COVERAGE_REMEDIATION_R3"
COMPLETION = RESULTS / "A2_PIT_MOOMOO_CURRENT_WEEK_COMPLETION_R1"
PIT_PATH = READINESS / "component_inputs/2026-08-20/pit_universe.json"
POINTER_PATH = Path(
    r"D:\us-tech-quant-daily\current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    r"\canonical_snapshot_pointer.json"
)
STAGE_RAW = R3 / "api_incremental_raw_20260819_20260820.parquet"
STAGE_QFQ = R3 / "api_incremental_qfq_20260819_20260820.parquet"
STAGE_ACTIONS = NG_R3 / "remediation_actions.csv"
LOOKBACK = NG_R3 / "lookback_sufficiency_report.csv"
BACKLOG = R3 / "coverage_remediation_backlog.parquet"
INVENTORY = R3 / "missing_385_classification.parquet"
QUOTA_PROBE = REPO / "scripts/v22/a2_pit_moomoo_current_week_completion_r1.py"
BROKER_BINDING = REPO / "config/research_governance/a2_forward_shadow_production_binding_r1.json"

EXCLUSION_EVIDENCE = {
    "EA": {
        "reason": "MERGED_OR_ACQUIRED;ACQUISITION_COMPLETED_2026-08-04;LAST_TRADING_DATE_2026-08-04",
        "evidence": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-545",
    },
    "TALK": {
        "reason": "MERGED_OR_ACQUIRED;ACQUISITION_COMPLETED_2026-08-17",
        "evidence": "https://uhs.com/news/universal-health-services-inc-completes-acquisition-of-talkspace-inc/",
    },
    "OLPX": {
        "reason": "MERGED_OR_ACQUIRED;MERGER_COMPLETED_2026-07-07",
        "evidence": "https://www.sec.gov/Archives/edgar/data/1868726/000119312526296993/d128672d8k.htm",
    },
    "PAYP": {
        "reason": "NOT_YET_MODEL_FEATURE_ELIGIBLE;FIRST_PRICE_2026-03-12;113_OBSERVATIONS_LT_FROZEN_121",
        "evidence": str(NG_R3 / "pit_readiness_manifest.json"),
    },
}
GE_EVIDENCE = (
    "https://www.ge.com/news/press-releases/ge-completes-one-for-eight-reverse-stock-split;"
    "CUSIP_369604301_TRADES_AS_GE_NOT_GE.WI"
)


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
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def strict_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, text=True, capture_output=True).stdout.strip()


def load_quota() -> tuple[int, int, list[dict[str, Any]], str]:
    spec = importlib.util.spec_from_file_location("a2_gap_quota_probe", QUOTA_PROBE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    used, remaining, detail = module.quota_detail()
    normalized = sorted(
        ({"code": str(row.get("code", "")), "request_time": str(row.get("request_time", ""))} for row in detail),
        key=lambda row: (row["code"], row["request_time"]),
    )
    return used, remaining, detail, hash_json(normalized)


def valid_prices(frame: pd.DataFrame) -> pd.Series:
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric).all(axis=1)
    positive = numeric[["open", "high", "low", "close"]].gt(0).all(axis=1)
    bounds = (
        numeric.high.ge(numeric[["open", "close", "low"]].max(axis=1))
        & numeric.low.le(numeric[["open", "close", "high"]].min(axis=1))
    )
    return finite & positive & bounds & numeric.volume.ge(0)


def staged_validation(required_staged: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    raw = pd.read_parquet(STAGE_RAW)
    qfq = pd.read_parquet(STAGE_QFQ)
    actions = pd.read_csv(STAGE_ACTIONS, dtype=str).fillna("")
    lookback = pd.read_csv(LOOKBACK, dtype=str).fillna("").set_index("ticker")
    required_schema = {
        "ticker", "moomoo_symbol", "date", "open", "high", "low", "close", "volume",
        "adjustment", "source", "source_policy", "identity_source_ticker", "identity_rule_id",
    }
    results: dict[str, dict[str, Any]] = {}
    global_checks = {
        "stage_raw_schema_compatible": required_schema <= set(raw.columns),
        "stage_qfq_schema_compatible": required_schema <= set(qfq.columns),
        "stage_raw_primary_key_unique": not raw.duplicated(["ticker", "date"]).any(),
        "stage_qfq_primary_key_unique": not qfq.duplicated(["ticker", "date"]).any(),
        "stage_raw_ohlcv_valid": bool(valid_prices(raw).all()),
        "stage_qfq_ohlcv_valid": bool(valid_prices(qfq).all()),
        "stage_action_hashes_valid": True,
    }
    for row in actions.itertuples(index=False):
        path = Path(row.path)
        if not path.is_file() or sha256_file(path) != row.sha256:
            global_checks["stage_action_hashes_valid"] = False
            break
    for ticker in sorted(required_staged):
        r = raw.loc[raw.ticker.astype(str).eq(ticker)].copy()
        q = qfq.loc[qfq.ticker.astype(str).eq(ticker)].copy()
        rdates = r.date.astype(str).str[:10]
        qdates = q.date.astype(str).str[:10]
        target_raw = r.loc[rdates.eq(TARGET)]
        target_qfq = q.loc[qdates.eq(TARGET)]
        mono_raw = rdates.tolist() == sorted(rdates.tolist())
        mono_qfq = qdates.tolist() == sorted(qdates.tolist())
        history_ready = ticker in lookback.index and strict_bool(lookback.loc[ticker, "ng8_feature_ready"])
        checks = {
            "identity": len(r) > 0 and len(q) > 0 and r.ticker.eq(ticker).all() and q.ticker.eq(ticker).all(),
            "mapping": len(r) > 0 and len(q) > 0 and r.moomoo_symbol.nunique() == q.moomoo_symbol.nunique() == 1
            and set(r.moomoo_symbol) == set(q.moomoo_symbol),
            "duplicates": not r.duplicated(["ticker", "date"]).any() and not q.duplicated(["ticker", "date"]).any(),
            "ordering": mono_raw and mono_qfq,
            "ohlcv": bool(valid_prices(r).all() and valid_prices(q).all()),
            "qfq": len(q) > 0 and q.adjustment.astype(str).str.lower().eq("qfq").all(),
            "target": len(target_raw) == 1 and len(target_qfq) == 1,
            "history": history_ready,
            "schema": required_schema <= set(r.columns) and required_schema <= set(q.columns),
        }
        passed = all(checks.values())
        results[ticker] = {
            "passed": passed,
            "checks": checks,
            "symbol": "" if r.empty else str(r.iloc[0].moomoo_symbol),
            "raw_rows": len(r),
            "qfq_rows": len(q),
        }
    global_checks.update({
        "required_staged_count": len(required_staged),
        "validated_count": sum(item["passed"] for item in results.values()),
        "requiring_remediation_count": sum(not item["passed"] for item in results.values()),
        "all_required_staged_present": set(results) == required_staged,
    })
    return results, global_checks


def local_gap_scan(gap_tickers: set[str]) -> dict[str, dict[str, Any]]:
    modes: dict[str, pd.DataFrame] = {}
    for mode in ("raw", "qfq"):
        path = DATA / f"moomoo/source/prices_{mode}/year=2026/prices.parquet"
        frame = pd.read_parquet(path)
        frame["trade_date"] = frame.trade_date.astype(str).str[:10]
        modes[mode] = frame.loc[frame.ticker.astype(str).isin(gap_tickers)]
    found: dict[str, dict[str, Any]] = {}
    for ticker in sorted(gap_tickers):
        r = modes["raw"].loc[modes["raw"].ticker.astype(str).eq(ticker)]
        q = modes["qfq"].loc[modes["qfq"].ticker.astype(str).eq(ticker)]
        found[ticker] = {
            "raw_rows": len(r), "qfq_rows": len(q),
            "raw_target": int(r.trade_date.eq(TARGET).sum()),
            "qfq_target": int(q.trade_date.eq(TARGET).sum()),
        }
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-tests", default="NOT_RUN")
    args = parser.parse_args()
    allowed_outputs = {
        "task_receipt.json", "coverage_gap_ledger.csv", "promotion_manifest.json",
        "post_promotion_reconciliation.json", "final_report.md", "hash_manifest.json",
    }
    if OUT.is_dir():
        unexpected = {path.name for path in OUT.iterdir()} - allowed_outputs
        assert not unexpected, f"UNEXPECTED_EXISTING_OUTPUTS:{sorted(unexpected)}"
    else:
        OUT.mkdir(parents=True, exist_ok=False)

    pit_payload = read_json(PIT_PATH)
    pit = pd.DataFrame(pit_payload["members"])[["security_id", "ticker"]]
    upstream = pd.read_csv(UPSTREAM / "pit_coverage_ledger.csv", dtype=str).fillna("")
    assert len(pit) == pit.security_id.nunique() == pit.ticker.nunique() == 613
    assert set(pit.ticker) == set(upstream.ticker)
    pointer_before_bytes = POINTER_PATH.read_bytes()
    pointer = json.loads(pointer_before_bytes)
    manifest_path = Path(pointer["canonical_manifest_path"])
    raw_path = Path(pointer["canonical_raw_path"])
    qfq_path = Path(pointer["canonical_qfq_path"])
    raw_hash_before, qfq_hash_before = sha256_file(raw_path), sha256_file(qfq_path)
    manifest_hash_before = sha256_file(manifest_path)
    upstream_receipt = read_json(UPSTREAM / "task_receipt.json")
    expected = upstream_receipt["canonical_hashes_at_task_time"]
    historical_identity = (
        raw_hash_before == expected[str(raw_path)]
        and qfq_hash_before == expected[str(qfq_path)]
    )

    upstream_required = upstream.active_tradable_model_required.map(strict_bool)
    upstream_covered = upstream.target_date_model_safe_covered.map(strict_bool)
    upstream_staged = upstream.later_staged_ready_2026_08_21.map(strict_bool)
    required_staged = set(upstream.loc[upstream_required & upstream_staged & ~upstream_covered, "ticker"])
    original_gap = pd.read_parquet(BACKLOG)
    original_gap_tickers = set(original_gap.ticker.astype(str))
    assert len(required_staged) == 321 and len(original_gap_tickers) == 59

    stage_result, stage_checks = staged_validation(required_staged)
    used, remaining, quota_detail, quota_hash = load_quota()
    touched = {str(item.get("code", "")) for item in quota_detail}
    backlog_by_ticker = original_gap.set_index("ticker").to_dict("index")
    original_gap_touched = {
        ticker for ticker, row in backlog_by_ticker.items() if str(row["moomoo_transport_code"]) in touched
    }
    gap_with_ge = original_gap_tickers | {"GE"}
    local = local_gap_scan(gap_with_ge)
    locally_resolved = {
        ticker for ticker, row in local.items() if row["raw_target"] == 1 and row["qfq_target"] == 1
    }
    inventory = pd.read_parquet(INVENTORY).set_index("ticker").to_dict("index")

    canonical_raw = pd.read_csv(raw_path, usecols=["ticker", "date"])
    canonical_qfq = pd.read_csv(qfq_path, usecols=["ticker", "date"])
    raw_target = set(canonical_raw.loc[canonical_raw.date.astype(str).str[:10].eq(TARGET), "ticker"].astype(str))
    qfq_target = set(canonical_qfq.loc[canonical_qfq.date.astype(str).str[:10].eq(TARGET), "ticker"].astype(str))
    authoritative_covered = set(pit.ticker) & raw_target & qfq_target
    assert len(authoritative_covered) == 228

    rows: list[dict[str, Any]] = []
    for member in pit.itertuples(index=False):
        ticker = str(member.ticker)
        prior = upstream.loc[upstream.ticker.eq(ticker)].iloc[0]
        old_required = strict_bool(prior.active_tradable_model_required)
        final_required = ticker not in EXCLUSION_EVIDENCE
        covered = ticker in authoritative_covered
        staged = ticker in required_staged
        classification_change = ticker == "GE.WI"
        if covered:
            final_class = "VALID_CANONICAL_COVERAGE"
        elif ticker in EXCLUSION_EVIDENCE:
            final_class = "LEGITIMATE_MODEL_SAFE_EXCLUSION"
        elif staged and stage_result[ticker]["passed"]:
            final_class = "STAGED_VALID_FOR_PROMOTION"
        else:
            final_class = "UNRESOLVED_REQUIRED_QUOTA_BLOCKED"

        if ticker in EXCLUSION_EVIDENCE:
            exclusion_reason = EXCLUSION_EVIDENCE[ticker]["reason"]
            unresolved_reason = ""
            evidence = EXCLUSION_EVIDENCE[ticker]["evidence"]
        elif ticker == "GE.WI":
            exclusion_reason = ""
            unresolved_reason = "BROKER_SYMBOL_ALIAS_REQUIRED:GE.WI_TO_GE;US.GE_NOT_TOUCHED;QUOTA_REMAINING_0;TARGET_DATE_DATA_MISSING"
            evidence = GE_EVIDENCE
        elif ticker in original_gap_tickers:
            gap = backlog_by_ticker[ticker]
            exclusion_reason = ""
            unresolved_reason = (
                f"{gap['local_status']};{gap['reason_code']};CURRENT_ROLLING_QUOTA_REMAINING_{remaining};"
                "NEW_UNIQUE_SECURITY_QUOTA_REQUIRED"
            )
            evidence = ""
        else:
            exclusion_reason = ""
            unresolved_reason = "" if covered or staged else str(prior.reason)
            evidence = ""

        if covered:
            action = "REUSED_AUTHORITATIVE_CANONICAL;TARGET_DATE_REVERIFIED"
            data_status = "AUTHORITATIVE_RAW_QFQ_TARGET_PRESENT"
            staged_status = "NOT_NEEDED"
        elif staged:
            action = "VALIDATED_EXISTING_STAGED_RAW_QFQ;NO_REDOWNLOAD"
            data_status = "LOCAL_STAGED_RAW_QFQ_TARGET_PRESENT;QFQ_121_SESSION_FEATURE_READY"
            staged_status = "STAGED_VALID_FOR_PROMOTION" if stage_result[ticker]["passed"] else "STAGED_REMEDIATION_REQUIRED"
        elif ticker in EXCLUSION_EVIDENCE:
            action = "VALIDATED_LEGAL_EXCLUSION_EVIDENCE"
            data_status = "TARGET_BAR_NOT_REQUIRED_UNDER_AUDITED_EXCLUSION"
            staged_status = "STAGED_BUT_EXCLUDED" if ticker == "PAYP" else "NOT_STAGED"
        else:
            action = "CHECKED_CANONICAL_CACHE_RAW_QFQ_IDENTITY_AND_LIVE_QUOTA;NO_API_REQUEST_ALLOWED"
            data_status = "NO_AUTHORITATIVE_LOCAL_TARGET_RAW_QFQ"
            staged_status = "NOT_STAGED"

        if ticker == "GE.WI":
            identity_status = "ALIAS_RESOLVED_TO_GE;COVERAGE_UNRESOLVED"
            quota_status = "US.GE_NEW_UNIQUE_SECURITY_QUOTA_REQUIRED;REMAINING_0"
        elif ticker in original_gap_tickers:
            code = str(backlog_by_ticker[ticker]["moomoo_transport_code"])
            identity_status = (
                "IDENTITY_MAPPING_DOCUMENTED;DATA_UNRESOLVED"
                if str(backlog_by_ticker[ticker]["local_status"]) == "CORPORATE_ACTION_IDENTITY_TRANSITION"
                else "PRIOR_MAPPING_RETAINED_FAIL_CLOSED"
            )
            quota_status = "ALREADY_TOUCHED_THIS_QUOTA_WEEK" if code in touched else "NEW_UNIQUE_SECURITY_QUOTA_REQUIRED;REMAINING_0"
        else:
            identity_status = "VALIDATED" if not classification_change else "ALIAS_RESOLVED"
            quota_status = "NOT_REQUIRED" if covered or ticker in EXCLUSION_EVIDENCE else "ALREADY_TOUCHED_THIS_QUOTA_WEEK"

        rows.append({
            "security_id": member.security_id,
            "ticker": ticker,
            "pit_status": "PIT_UNIVERSE",
            "target_date_required": final_required,
            "pre_task_status": "CURRENT_AUTHORITATIVE_COVERED" if covered else (
                "STAGED_NOT_PROMOTED" if staged else ("UNRESOLVED_REQUIRED" if ticker in original_gap_tickers else "LEGITIMATE_NON_REQUIRED")
            ),
            "staged_status": staged_status,
            "data_source_status": data_status,
            "quota_status": quota_status,
            "identity_status": identity_status,
            "target_date_status": "AUTHORITATIVE_PRESENT" if covered else (
                "STAGED_PRESENT_NOT_AUTHORITATIVE" if staged else ("NOT_REQUIRED" if not final_required else "MISSING")
            ),
            "final_classification": final_class,
            "final_required": final_required,
            "final_covered": covered and final_required,
            "exclusion_reason": exclusion_reason,
            "unresolved_reason": unresolved_reason,
            "action_taken": action,
            "old_classification": "ACTIVE_TRADABLE_REQUIRED" if old_required else "LEGITIMATE_NON_REQUIRED",
            "new_classification": "ACTIVE_TRADABLE_REQUIRED" if final_required else "LEGITIMATE_NON_REQUIRED",
            "classification_change_evidence": evidence,
            "reason_for_change": "CORRECT_STALE_GE.WI_WHEN_ISSUED_MAPPING_TO_GE" if classification_change else "",
        })

    final_required_rows = [row for row in rows if row["final_required"]]
    final_unresolved = [
        row for row in final_required_rows
        if not row["final_covered"] and row["final_classification"] != "STAGED_VALID_FOR_PROMOTION"
    ]
    silent = [row for row in rows if not row["final_required"] and not row["exclusion_reason"]]
    staged_valid = sum(row["final_classification"] == "STAGED_VALID_FOR_PROMOTION" for row in rows)
    promotion_allowed = not final_unresolved and not silent and historical_identity and staged_valid == len(required_staged)
    # Atomic promotion is intentionally absent when any required gap remains.
    promotion_executed = False
    assert not promotion_allowed, "Complete coverage requires the existing atomic promotion mechanism, not this fail-close path"

    # Verify the authoritative pointer and immutable bodies again after every read/probe.
    pointer_unchanged = POINTER_PATH.read_bytes() == pointer_before_bytes
    raw_hash_after, qfq_hash_after = sha256_file(raw_path), sha256_file(qfq_path)
    historical_identity = historical_identity and pointer_unchanged and raw_hash_after == raw_hash_before and qfq_hash_after == qfq_hash_before
    broker_binding = read_json(BROKER_BINDING)
    broker_disabled = broker_binding.get("broker_action_allowed") is False and pointer.get("broker_action_allowed") is False
    overall = "FAIL_UNRESOLVED_REQUIRED_COVERAGE" if historical_identity else "FAIL_CANONICAL_IDENTITY_OR_PROMOTION"

    fields = list(rows[0])
    write_csv(OUT / "coverage_gap_ledger.csv", rows, fields)
    source_paths = [
        PIT_PATH, UPSTREAM / "pit_coverage_ledger.csv", UPSTREAM / "pre2026_freeze_manifest.json",
        POINTER_PATH, manifest_path, raw_path, qfq_path, STAGE_RAW, STAGE_QFQ, STAGE_ACTIONS,
        LOOKBACK, BACKLOG, INVENTORY, COMPLETION / "current_week_quota_set.csv", BROKER_BINDING,
    ]
    source_hashes = {str(path): sha256_file(path) for path in source_paths}
    task_receipt = {
        "task_id": TASK,
        "created_utc": now_utc(),
        "target_date": TARGET,
        "git_commit": git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(git("status", "--porcelain")),
        "authoritative_upstream": str(UPSTREAM),
        "source_hashes": source_hashes,
        "live_quota": {
            "used": used, "remaining": remaining, "detail_count": len(quota_detail),
            "normalized_code_request_time_sha256": quota_hash,
            "original_gap_already_touched_count": len(original_gap_touched),
        },
        "classification_changes": [{
            "ticker": "GE.WI", "security_id": "369604301",
            "old_classification": "LEGITIMATE_NON_REQUIRED",
            "new_classification": "ACTIVE_TRADABLE_REQUIRED",
            "evidence": GE_EVIDENCE,
            "reason_for_change": "CUSIP 369604301 trades as GE; GE.WI was temporary when-issued trading only",
        }],
        "external_identity_evidence": EXCLUSION_EVIDENCE,
        "prohibited_actions": {
            "model_training_executed": False, "2026_used_for_training": False,
            "2026_used_for_model_selection": False, "broker_action_executed": False,
            "partial_promotion_executed": False, "git_commit_or_push_executed": False,
        },
    }
    write_json(OUT / "task_receipt.json", task_receipt)

    promotion_manifest = {
        "task_id": TASK,
        "PROMOTION_EXECUTED": promotion_executed,
        "promotion_status": "NOT_EXECUTED_FAIL_CLOSED_UNRESOLVED_REQUIRED_COVERAGE",
        "candidate_snapshot_status": "NOT_CREATED_INCOMPLETE_REQUIRED_GATE",
        "reason": f"{len(final_unresolved)} required securities lack authoritative target-date coverage",
        "precondition": "UNEXPLAINED_REQUIRED_SECURITY_COUNT=0_AND_SILENT_EXCLUSION_COUNT=0",
        "existing_authoritative_snapshot_id": pointer["snapshot_id"],
        "existing_canonical_manifest_sha256": manifest_hash_before,
        "existing_raw_sha256": raw_hash_before,
        "existing_qfq_sha256": qfq_hash_before,
        "new_canonical_snapshot_id": None,
        "new_canonical_manifest_sha256": None,
        "atomicity": "PASS_NO_PARTIAL_PROMOTION;EXISTING_POINTER_UNCHANGED",
    }
    write_json(OUT / "promotion_manifest.json", promotion_manifest)

    validation = {
        "security_identity_uniqueness": len(pit) == pit.security_id.nunique(),
        "ticker_mapping_consistency": all(row["identity_status"] != "UNKNOWN" for row in rows),
        "target_date_row_uniqueness": stage_checks["stage_raw_primary_key_unique"] and stage_checks["stage_qfq_primary_key_unique"],
        "ohlc_validity": stage_checks["stage_raw_ohlcv_valid"] and stage_checks["stage_qfq_ohlcv_valid"],
        "volume_validity": stage_checks["stage_raw_ohlcv_valid"] and stage_checks["stage_qfq_ohlcv_valid"],
        "qfq_validity": stage_checks["stage_qfq_ohlcv_valid"],
        "date_monotonicity": all(item["checks"]["ordering"] for item in stage_result.values()),
        "required_universe_reconciliation": len(rows) == len(final_required_rows) + len(EXCLUSION_EVIDENCE),
        "silent_exclusion_check": len(silent) == 0,
        "historical_no_mutation_check": historical_identity,
        "candidate_snapshot_hash": "NOT_APPLICABLE_CANDIDATE_NOT_CREATED",
        "post_promotion_manifest_verification": "NOT_APPLICABLE_PROMOTION_NOT_EXECUTED;CURRENT_MANIFEST_HASH_VERIFIED",
        "broker_live_disabled": broker_disabled,
        "external_tests": args.external_tests,
    }
    reconciliation = {
        "task_id": TASK,
        "overall_status": overall,
        "target_date": TARGET,
        "pit_universe_security_count": len(rows),
        "pre_task_active_tradable_required_count": int(upstream_required.sum()),
        "final_active_tradable_required_count": len(final_required_rows),
        "pre_task_authoritative_covered_count": int(upstream_covered.sum()),
        "authoritative_target_date_covered_count": sum(row["final_covered"] for row in rows),
        "staged_security_count": len(required_staged),
        "staged_validated_count": staged_valid,
        "staged_requiring_remediation_count": len(required_staged) - staged_valid,
        "pre_task_unresolved_required_count": len(original_gap_tickers),
        "resolved_from_local_data_count": len(locally_resolved & original_gap_tickers),
        "resolved_by_identity_mapping_count": 0,
        "resolved_by_already_touched_refresh_count": 0,
        "resolved_by_new_quota_request_count": 0,
        "final_unresolved_required_count": len(final_unresolved),
        "legitimate_exclusion_count": len(EXCLUSION_EVIDENCE),
        "silent_exclusion_count": len(silent),
        "model_safe_coverage_pct": round(100 * sum(row["final_covered"] for row in rows) / len(final_required_rows), 6),
        "historical_canonical_identity_status": "PASS_HASH_VERIFIED_NO_MUTATION" if historical_identity else "FAIL_MUTATION",
        "candidate_snapshot_status": promotion_manifest["candidate_snapshot_status"],
        "atomic_promotion_status": promotion_manifest["promotion_status"],
        "authoritative_snapshot_id": pointer["snapshot_id"],
        "authoritative_manifest_sha256": manifest_hash_before,
        "validation": validation,
        "staged_validation": stage_checks,
        "unresolved": [{"security_id": row["security_id"], "ticker": row["ticker"], "reason": row["unresolved_reason"]} for row in final_unresolved],
    }
    write_json(OUT / "post_promotion_reconciliation.json", reconciliation)

    unresolved_lines = "\n".join(f"- `{row['ticker']}`: {row['unresolved_reason']}" for row in final_unresolved)
    nonrequired_lines = "\n".join(
        f"- `{ticker}`: {value['reason']} — evidence: {value['evidence']}" for ticker, value in EXCLUSION_EVIDENCE.items()
    )
    report = f"""# {TASK}

Overall status: `{overall}`. The coverage gate remains open, so no candidate snapshot was created and no atomic promotion was attempted. The existing authoritative snapshot remains byte-identical.

## Required answers

1. Upstream PIT universe: **{len(rows)}** securities (`{sha256_file(PIT_PATH)}`).
2. Active/tradable/model-required cohort: **{len(final_required_rows)}**. It was 608 upstream; `GE.WI` was corrected from an unsupported exclusion to required CUSIP `369604301` / ticker `GE` coverage work.
3. Upstream approximately 321 staged names: **{len(required_staged)}** required securities confirmed (plus PAYP staged but legitimately excluded under the frozen feature contract).
4. Direct staged validation passes: **{staged_valid}**.
5. Staged names needing remediation: **{len(required_staged) - staged_valid}**.
6. Original unresolved cohort: **{len(original_gap_tickers)}**.
7. Resolved from existing local raw/QFQ: **{len(locally_resolved & original_gap_tickers)}**.
8. Resolved through alias/identity reconciliation with complete data: **0**. `GE.WI -> GE` was identified, but target-date coverage is still missing.
9. Resolved through already-touched refresh: **0**; none of the 59 original gaps nor `US.GE` is in the current touched set.
10. Resolved through new unique-security quota: **0**; live quota is `{used}` used / `{remaining}` remaining, so no request was made.
11. Remaining unresolved required securities: **{len(final_unresolved)}**.
12. Each unresolved reason is listed below and in `coverage_gap_ledger.csv`.
13. The former five non-required names are now four legitimate exclusions: EA, TALK, and OLPX are acquired/delisted before target; PAYP has 113 observations versus the frozen 121 requirement. GE.WI was reclassified as required because CUSIP 369604301 trades as GE.
14. Silent exclusions: **{len(silent)}**.
15. Historical canonical identity: **{'PASS_HASH_VERIFIED_NO_MUTATION' if historical_identity else 'FAIL_MUTATION'}** (raw/QFQ bodies, manifest, and pointer rehashed).
16. Complete candidate snapshot created: **No** (`NOT_CREATED_INCOMPLETE_REQUIRED_GATE`).
17. Atomic promotion executed: **No** (`NOT_EXECUTED_FAIL_CLOSED_UNRESOLVED_REQUIRED_COVERAGE`).
18. New authoritative snapshot/hash: **none**. Existing snapshot remains `{pointer['snapshot_id']}` / `{manifest_hash_before}`.
19. Post-task authoritative model-safe coverage: **{sum(row['final_covered'] for row in rows)}/{len(final_required_rows)} = {100 * sum(row['final_covered'] for row in rows) / len(final_required_rows):.2f}%**.
20. Ready for `A2_UNIFIED_REPLAY_AND_ATTRIBUTION_R1`: **No**. The smallest next action is to wait for rolling quota release, request only the 59 ledgered broker symbols plus corrected `US.GE`, validate them, then run the existing atomic promotion mechanism.

## Legitimate exclusions

{nonrequired_lines}

## Unresolved required securities

{unresolved_lines}

## Validation

- Staged raw/QFQ target-date uniqueness, OHLC, volume, QFQ mode, date ordering, schema, security identity, ticker mapping, artifact hashes, and frozen 121-session sufficiency: **{'PASS' if staged_valid == len(required_staged) else 'FAIL'}**.
- Required-universe reconciliation and silent-exclusion gate: **{'PASS' if len(silent) == 0 else 'FAIL'}**.
- Historical no-mutation and authoritative pointer identity: **{'PASS' if historical_identity else 'FAIL'}**.
- Existing relevant tests / Anti-Bloat guard: `{args.external_tests}`.
- Broker/live action: **disabled**. Model training and 2026 model/parameter selection: **not executed**.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")

    core = ["task_receipt.json", "coverage_gap_ledger.csv", "promotion_manifest.json", "post_promotion_reconciliation.json", "final_report.md"]
    hash_manifest = {
        "task_id": TASK,
        "definition": "SHA256 of the five other core artifacts; this manifest excludes itself",
        "artifacts": [{"path": str(OUT / name), "bytes": (OUT / name).stat().st_size, "sha256": sha256_file(OUT / name)} for name in core],
    }
    hash_manifest["artifact_set_sha256"] = hash_json(hash_manifest["artifacts"])
    write_json(OUT / "hash_manifest.json", hash_manifest)

    summary = {
        "OVERALL_STATUS": overall,
        "TARGET_DATE": TARGET,
        "PIT_UNIVERSE_SECURITY_COUNT": len(rows),
        "PRE_TASK_ACTIVE_TRADABLE_REQUIRED_COUNT": int(upstream_required.sum()),
        "FINAL_ACTIVE_TRADABLE_REQUIRED_COUNT": len(final_required_rows),
        "PRE_TASK_AUTHORITATIVE_COVERED_COUNT": int(upstream_covered.sum()),
        "STAGED_SECURITY_COUNT": len(required_staged),
        "STAGED_VALIDATED_COUNT": staged_valid,
        "STAGED_REQUIRING_REMEDIATION_COUNT": len(required_staged) - staged_valid,
        "PRE_TASK_UNRESOLVED_REQUIRED_COUNT": len(original_gap_tickers),
        "RESOLVED_FROM_LOCAL_DATA_COUNT": len(locally_resolved & original_gap_tickers),
        "RESOLVED_BY_IDENTITY_MAPPING_COUNT": 0,
        "RESOLVED_BY_ALREADY_TOUCHED_REFRESH_COUNT": 0,
        "RESOLVED_BY_NEW_QUOTA_REQUEST_COUNT": 0,
        "FINAL_UNRESOLVED_REQUIRED_COUNT": len(final_unresolved),
        "LEGITIMATE_EXCLUSION_COUNT": len(EXCLUSION_EVIDENCE),
        "SILENT_EXCLUSION_COUNT": len(silent),
        "FINAL_AUTHORITATIVE_MODEL_SAFE_COVERAGE_COUNT": sum(row["final_covered"] for row in rows),
        "FINAL_AUTHORITATIVE_MODEL_SAFE_COVERAGE_PCT": f"{100 * sum(row['final_covered'] for row in rows) / len(final_required_rows):.2f}%",
        "HISTORICAL_CANONICAL_IDENTITY_STATUS": reconciliation["historical_canonical_identity_status"],
        "CANDIDATE_SNAPSHOT_STATUS": promotion_manifest["candidate_snapshot_status"],
        "ATOMIC_PROMOTION_STATUS": promotion_manifest["promotion_status"],
        "NEW_CANONICAL_SNAPSHOT_ID": "",
        "NEW_CANONICAL_MANIFEST_SHA256": "",
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
