#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

STAGE = "V21.245_R1A_MOOMOO_CACHE_CURRENTNESS_AND_FAILURE_TRIAGE"
OUT_REL = Path("outputs/v21") / STAGE
DEFAULT_V245_REL = Path("outputs/v21/V21.245_MOOMOO_HISTORICAL_BACKFILL_TO_LOCAL_CACHE_R1")
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
PROVIDER = "MOOMOO"
REQUIRED_COLS = ["date", "ticker", "moomoo_symbol", "open", "high", "low", "close", "volume", "turnover", "price_type", "provider", "fetch_timestamp", "source_run_id"]
GATE_STATUSES = {"PASS_READY_FOR_V21_246", "PARTIAL_PASS_READY_WITH_EXCLUSIONS", "WARN_REPAIR_RECOMMENDED_BEFORE_V21_246", "FAIL_NOT_READY_FOR_V21_246"}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [{k: (v or "") for k, v in r.items() if k is not None} for r in csv.DictReader(f)]
    except Exception:
        return []


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def intv(v: Any) -> int:
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def cache_path(cache_root: Path, ticker: str, price_type: str) -> Path:
    sub = "raw" if price_type == "RAW_DAILY" else "qfq"
    return cache_root / "market_data/moomoo/daily" / sub / f"{ticker.upper()}.csv"


def inspect_cache_file(path: Path, ticker: str, price_type: str, manifest_hash: str = "") -> dict[str, Any]:
    exists = path.exists()
    if not exists:
        return {"cache_file_path": str(path), "ticker": ticker, "price_type": price_type, "file_exists": False, "byte_size": 0, "row_count": 0, "sha256_current": "", "sha256_manifest": manifest_hash, "hash_matches_manifest": False, "required_columns_present": False, "duplicate_date_count": 0, "null_close_count": 0, "invalid_ohlc_count": 0, "date_monotonic": False, "integrity_status": "MISSING_FILE", "first_date": "", "latest_date": ""}
    rows = read_rows(path)
    byte_size = path.stat().st_size
    sha = sha256_file(path)
    if not rows:
        return {"cache_file_path": str(path), "ticker": ticker, "price_type": price_type, "file_exists": True, "byte_size": byte_size, "row_count": 0, "sha256_current": sha, "sha256_manifest": manifest_hash, "hash_matches_manifest": bool(manifest_hash and sha == manifest_hash), "required_columns_present": False, "duplicate_date_count": 0, "null_close_count": 0, "invalid_ohlc_count": 0, "date_monotonic": True, "integrity_status": "FAIL_EMPTY_FILE", "first_date": "", "latest_date": ""}
    cols_ok = all(c in rows[0] for c in REQUIRED_COLS)
    dates = [r.get("date", "") for r in rows if r.get("date")]
    dup = len(dates) - len(set(dates))
    null_close = sum(1 for r in rows if r.get("close", "") == "")
    invalid = 0
    for r in rows:
        try:
            o, h, l, c = [float(r.get(k) or 0) for k in ["open", "high", "low", "close"]]
            if min(o, h, l, c) < 0 or h < max(o, c, l) or l > min(o, c, h):
                invalid += 1
        except Exception:
            invalid += 1
    mono = dates == sorted(dates)
    if not cols_ok:
        status = "FAIL_SCHEMA_INVALID"
    elif invalid:
        status = "FAIL_OHLC_INVALID"
    elif dup:
        status = "WARN_DUPLICATE_DATES"
    elif null_close:
        status = "WARN_NULL_VALUES"
    elif manifest_hash and sha != manifest_hash:
        status = "WARN_HASH_MANIFEST_MISMATCH"
    else:
        status = "PASS"
    return {"cache_file_path": str(path), "ticker": ticker, "price_type": price_type, "file_exists": True, "byte_size": byte_size, "row_count": len(rows), "sha256_current": sha, "sha256_manifest": manifest_hash, "hash_matches_manifest": bool(manifest_hash and sha == manifest_hash), "required_columns_present": cols_ok, "duplicate_date_count": dup, "null_close_count": null_close, "invalid_ohlc_count": invalid, "date_monotonic": mono, "integrity_status": status, "first_date": min(dates) if dates else "", "latest_date": max(dates) if dates else ""}


def currentness_status(info: dict[str, Any], expected: str, result_status: str, coverage_class: str) -> tuple[str, str, bool, int]:
    if not info["file_exists"]:
        return "MISSING_CACHE_FILE", "cache file missing", False, 999999
    if info["integrity_status"] in {"FAIL_SCHEMA_INVALID", "FAIL_OHLC_INVALID"}:
        return "INVALID_CACHE_SCHEMA", info["integrity_status"], False, 999999
    if info["row_count"] <= 0:
        return "EMPTY_CACHE_FILE", "cache has no rows", False, 999999
    latest = info["latest_date"]
    ed, ld = parse_date(expected), parse_date(latest)
    stale = (ed - ld).days if ed and ld else 999999
    latest_ok = latest >= expected
    if result_status.startswith("FAIL") or coverage_class == "NO_DATA":
        return ("NO_DATA" if not latest_ok else "CURRENT_TO_EXPECTED_LATEST"), "V21.245 no-data/failure entry", latest_ok, stale
    if latest_ok and (result_status == "SUCCESS_PARTIAL_IPO_LATE" or coverage_class == "PARTIAL_IPO_LATE"):
        return "PARTIAL_IPO_LATE_BUT_CURRENT", "start date is late but latest date reaches expected session", True, 0
    if latest_ok:
        return "CURRENT_TO_EXPECTED_LATEST", "latest date reaches expected session", True, 0
    if stale <= 10:
        return "STALE_BUT_USABLE", "latest date is stale but near expected session", True, stale
    return "PARTIAL_PROVIDER_LIMIT", "latest date is materially stale", False, stale


def build(repo: Path, v245_root: Path, cache_root: Path, expected_latest: str, min_usable: int) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    v245 = v245_root if v245_root.is_absolute() else repo / v245_root
    summary245 = read_json(v245 / "v21_245_summary.json")
    result = read_rows(v245 / "moomoo_backfill_result.csv")
    failure = read_rows(v245 / "moomoo_backfill_failure_audit.csv")
    coverage = read_rows(v245 / "moomoo_daily_panel_coverage_audit.csv")
    universe = read_rows(v245 / "moomoo_backfill_universe.csv")
    hash_manifest = read_rows(v245 / "moomoo_cache_hash_manifest.csv")
    h_by_path = {r.get("cache_file_path", ""): r.get("sha256", "") for r in hash_manifest}
    res_by = {(r.get("ticker"), r.get("price_type")): r for r in result}
    cov_by = {r.get("ticker"): r for r in coverage}
    tickers = sorted({r.get("ticker") for r in universe if r.get("ticker")} | {r.get("ticker") for r in result if r.get("ticker")})
    integrity = []
    current = []
    for ticker in tickers:
        for pt in ["RAW_DAILY", "QFQ_DAILY"]:
            cp = cache_path(cache_root, ticker, pt)
            info = inspect_cache_file(cp, ticker, pt, h_by_path.get(str(cp), ""))
            integrity.append({k: v for k, v in info.items() if k not in {"first_date", "latest_date"}})
            r = res_by.get((ticker, pt), {})
            cov = cov_by.get(ticker, {})
            cov_class = cov.get("coverage_class", "")
            st, reason, ready, stale = currentness_status(info, expected_latest, r.get("result_status", ""), cov_class)
            current.append({"ticker": ticker, "moomoo_symbol": r.get("moomoo_symbol") or f"US.{ticker}", "price_type": pt, "expected_cache_file_path": str(cp), "cache_file_exists": info["file_exists"], "cache_schema_valid": info["integrity_status"] not in {"FAIL_SCHEMA_INVALID", "FAIL_OHLC_INVALID"}, "row_count": info["row_count"], "first_date": info["first_date"], "latest_date": info["latest_date"], "expected_latest_completed_date": expected_latest, "latest_date_matches_expected": info["latest_date"] >= expected_latest, "days_stale_estimate": stale, "cache_currentness_status": st, "cache_currentness_reason": reason, "v21_245_result_status": r.get("result_status", ""), "v21_245_coverage_class": cov_class, "ready_for_v21_246": ready})
    failed = build_failed_triage(failure, current)
    partial = build_partial(current, expected_latest)
    dist = build_distribution(current, expected_latest)
    logic = build_logic_audit(summary245, current)
    gate = build_gate(current, failed, integrity, summary245, expected_latest, min_usable)
    status, decision = final_decision(gate[0])
    summary = {"version": STAGE, "final_status": status, "final_decision": decision, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "provider": PROVIDER, "v21_245_output_root": str(v245), "cache_root": str(cache_root), "expected_latest_completed_date": expected_latest, "universe_count": len(tickers), "audited_cache_entry_count": len(current), "cache_file_count": sum(1 for r in integrity if r["file_exists"]), "current_to_expected_count": sum(1 for r in current if r["cache_currentness_status"] == "CURRENT_TO_EXPECTED_LATEST"), "stale_but_usable_count": sum(1 for r in current if r["cache_currentness_status"] == "STALE_BUT_USABLE"), "partial_ipo_late_but_current_count": sum(1 for r in current if r["cache_currentness_status"] == "PARTIAL_IPO_LATE_BUT_CURRENT"), "provider_limit_suspected_count": sum(1 for r in partial if r["partial_history_class"] == "PROVIDER_HISTORY_LIMIT_SUSPECTED"), "no_data_count": sum(1 for r in current if r["cache_currentness_status"] in {"NO_DATA", "MISSING_CACHE_FILE", "EMPTY_CACHE_FILE"}), "failed_entry_count": len(failed), "invalid_cache_file_count": sum(1 for r in integrity if str(r["integrity_status"]).startswith("FAIL")), "missing_cache_file_count": sum(1 for r in integrity if r["integrity_status"] == "MISSING_FILE"), "hash_mismatch_count": sum(1 for r in integrity if r["integrity_status"] == "WARN_HASH_MANIFEST_MISMATCH"), "duplicate_date_file_count": sum(1 for r in integrity if r["duplicate_date_count"]), "raw_recomputed_current_count": sum(1 for r in current if r["price_type"] == "RAW_DAILY" and r["latest_date_matches_expected"]), "qfq_recomputed_current_count": sum(1 for r in current if r["price_type"] == "QFQ_DAILY" and r["latest_date_matches_expected"]), "both_price_types_usable_count": gate[0]["both_price_types_usable_count"], "ready_for_v21_246_gate_status": gate[0]["gate_status"], "ready_for_v21_246_gate_decision": gate[0]["gate_decision"], "output_root": str(repo / OUT_REL), "official_factor_marked_count": 0, "shadow_candidate_marked_count": 0, "broad_provider_fetch_attempted": False, "network_provider_fetch_attempted": False}
    return summary, {"current": current, "failed": failed, "partial": partial, "dist": dist, "gate": gate, "logic": logic, "integrity": integrity}


def build_failed_triage(failures: list[dict[str, str]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cur = {(r["ticker"], r["price_type"]): r for r in current}
    out = []
    for f in failures:
        if not str(f.get("result_status", "")).startswith("FAIL") and f.get("failure_class") not in {"PROVIDER_NO_DATA", "EMPTY_RESPONSE", "PROVIDER_PERMISSION", "SYMBOL_MAPPING", "SCHEMA_ERROR", "UNKNOWN"}:
            continue
        c = cur.get((f.get("ticker"), f.get("price_type")), {})
        reason = (f.get("failure_reason") or "").lower()
        symbol = f.get("failure_class") == "SYMBOL_MAPPING" or "symbol" in reason
        permission = f.get("failure_class") == "PROVIDER_PERMISSION" or "permission" in reason or "subscription" in reason
        no_data = f.get("failure_class") in {"PROVIDER_NO_DATA", "EMPTY_RESPONSE"}
        retry = permission or f.get("failure_class") in {"EMPTY_RESPONSE", "UNKNOWN"}
        if symbol:
            action = "MANUAL_SYMBOL_MAPPING"
        elif retry:
            action = "TARGETED_RETRY_MOOMOO_ONLY"
        elif no_data:
            action = "ACCEPT_NO_DATA_AND_EXCLUDE"
        elif c.get("ready_for_v21_246"):
            action = "ACCEPT_PARTIAL_AND_USE"
        else:
            action = "EXCLUDE_FROM_V21_246_PANEL"
        out.append({"ticker": f.get("ticker", ""), "moomoo_symbol": f.get("moomoo_symbol", ""), "price_type": f.get("price_type", ""), "result_status": f.get("result_status", ""), "failure_class": f.get("failure_class", ""), "failure_reason": f.get("failure_reason", ""), "cache_file_exists": c.get("cache_file_exists", False), "cache_row_count": c.get("row_count", 0), "cache_first_date": c.get("first_date", ""), "cache_latest_date": c.get("latest_date", ""), "symbol_mapping_suspect": symbol, "likely_delisted_or_unsupported": no_data and not retry, "permission_suspect": permission, "retry_worthwhile": retry, "targeted_retry_allowed": True, "recommended_next_action": action})
    return out


def build_partial(current: list[dict[str, Any]], expected: str) -> list[dict[str, Any]]:
    out = []
    for r in current:
        if r["cache_currentness_status"] in {"NO_DATA", "MISSING_CACHE_FILE", "EMPTY_CACHE_FILE"}:
            cls, disp = "NO_DATA", "EXCLUDE_FROM_V21_246_PANEL"
        elif not r["cache_schema_valid"]:
            cls, disp = "INVALID", "NEEDS_MANUAL_REVIEW"
        elif r["latest_date"] < expected:
            cls, disp = "NOT_CURRENT", "TARGETED_RETRY_MOOMOO_ONLY"
        elif r["first_date"] <= "2018-01-01":
            cls, disp = "FULL_FROM_2018", "USE_FOR_V21_246_FROM_FIRST_AVAILABLE_DATE"
        elif r["cache_currentness_status"] == "PARTIAL_PROVIDER_LIMIT":
            cls, disp = "PROVIDER_HISTORY_LIMIT_SUSPECTED", "TARGETED_RETRY_MOOMOO_ONLY"
        else:
            cls, disp = "NORMAL_IPO_OR_FIRST_AVAILABLE_AFTER_2018", "USE_FOR_V21_246_FROM_FIRST_AVAILABLE_DATE"
        out.append({"ticker": r["ticker"], "moomoo_symbol": r["moomoo_symbol"], "price_type": r["price_type"], "requested_start_date": "2018-01-01", "first_available_date": r["first_date"], "latest_available_date": r["latest_date"], "expected_latest_completed_date": expected, "row_count": r["row_count"], "v21_245_result_status": r["v21_245_result_status"], "v21_245_coverage_class": r["v21_245_coverage_class"], "partial_history_class": cls, "partial_history_reason": r["cache_currentness_reason"], "usable_for_technical_panel": r["ready_for_v21_246"], "usable_for_forward_return_panel": r["ready_for_v21_246"], "earliest_technical_computable_date_estimate": r["first_date"], "recommended_disposition": disp})
    return out


def build_distribution(current: list[dict[str, Any]], expected: str) -> list[dict[str, Any]]:
    out = []
    for pt in ["RAW_DAILY", "QFQ_DAILY"]:
        vals = [r for r in current if r["price_type"] == pt]
        total = max(1, len(vals))
        by_date = defaultdict(list)
        for r in vals:
            by_date[r["latest_date"] or "MISSING"].append(r["ticker"])
        for d, tickers in sorted(by_date.items()):
            out.append({"price_type": pt, "latest_date": d, "ticker_count": len(tickers), "ticker_pct": len(tickers) / total, "example_tickers": "|".join(tickers[:10]), "distribution_note": "expected_latest_completed_date" if d == expected else "stale_or_missing"})
        out.append({"price_type": pt, "latest_date": "SPECIAL_EXPECTED_LATEST", "ticker_count": sum(1 for r in vals if r["latest_date"] >= expected), "ticker_pct": sum(1 for r in vals if r["latest_date"] >= expected) / total, "example_tickers": f"expected_latest_completed_date={expected}; current_to_expected_count={sum(1 for r in vals if r['latest_date'] >= expected)}; stale_count={sum(1 for r in vals if r['latest_date'] and r['latest_date'] < expected)}; missing_count={sum(1 for r in vals if not r['latest_date'])}", "distribution_note": "special_summary_row"})
    return out


def build_logic_audit(s245: dict[str, Any], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recomputed = {"raw_daily_current_count": sum(1 for r in current if r["price_type"] == "RAW_DAILY" and r["latest_date_matches_expected"]), "qfq_daily_current_count": sum(1 for r in current if r["price_type"] == "QFQ_DAILY" and r["latest_date_matches_expected"]), "full_from_2018_count": sum(1 for r in current if r["first_date"] <= "2018-01-01" and r["latest_date_matches_expected"]), "partial_ipo_late_count": len({r["ticker"] for r in current if r["first_date"] > "2018-01-01" and r["latest_date_matches_expected"]})}
    rows = []
    for metric in ["raw_daily_current_count", "qfq_daily_current_count", "full_from_2018_count", "partial_ipo_late_count"]:
        old = intv(s245.get(metric))
        new = recomputed[metric]
        if metric in {"raw_daily_current_count", "qfq_daily_current_count"} and old == 0 and new > 0:
            issue = "MANIFEST_STATUS_NOT_UPDATED"
        elif metric == "full_from_2018_count" and old == 0 and new == 0 and recomputed["partial_ipo_late_count"] > 0:
            issue = "CLASSIFICATION_TOO_STRICT_FULL_FROM_2018_ONLY"
        elif old == new:
            issue = "NO_ISSUE"
        else:
            issue = "MIXED_CAUSES"
        rows.append({"metric_name": metric, "v21_245_value": old, "recomputed_value": new, "interpretation": "Recomputed from cache latest_date and first_date, treating IPO-late currentness separately.", "likely_issue": issue, "recommended_fix": "Use latest-date currentness for cache readiness; keep first-date coverage as separate partial-history classification."})
    return rows


def build_gate(current: list[dict[str, Any]], failed: list[dict[str, Any]], integrity: list[dict[str, Any]], s245: dict[str, Any], expected: str, min_usable: int) -> list[dict[str, Any]]:
    by_ticker = defaultdict(dict)
    for r in current:
        by_ticker[r["ticker"]][r["price_type"]] = r
    both = sum(1 for v in by_ticker.values() if v.get("RAW_DAILY", {}).get("ready_for_v21_246") and v.get("QFQ_DAILY", {}).get("ready_for_v21_246"))
    invalid = sum(1 for r in integrity if str(r["integrity_status"]).startswith("FAIL"))
    stale = sum(1 for r in current if r["cache_currentness_status"] in {"PARTIAL_PROVIDER_LIMIT"})
    no_data = len({r["ticker"] for r in current if r["cache_currentness_status"] in {"NO_DATA", "MISSING_CACHE_FILE", "EMPTY_CACHE_FILE"}})
    if both >= min_usable and invalid == 0:
        status, decision = "PARTIAL_PASS_READY_WITH_EXCLUSIONS" if failed or no_data else "PASS_READY_FOR_V21_246", "PROCEED_TO_V21_246_WITH_EXCLUSION_LIST" if failed or no_data else "PROCEED_TO_V21_246_TECHNICAL_AND_FORWARD_PANEL_BUILD"
    elif both >= max(50, min_usable // 2):
        status, decision = "WARN_REPAIR_RECOMMENDED_BEFORE_V21_246", "RUN_TARGETED_RETRY_FIRST"
    else:
        status, decision = "FAIL_NOT_READY_FOR_V21_246", "STOP_AND_REPAIR_CACHE"
    return [{"gate_name": "V21_246_CACHE_READINESS", "expected_latest_completed_date": expected, "universe_count": len(by_ticker), "raw_current_or_usable_count": sum(1 for r in current if r["price_type"] == "RAW_DAILY" and r["ready_for_v21_246"]), "qfq_current_or_usable_count": sum(1 for r in current if r["price_type"] == "QFQ_DAILY" and r["ready_for_v21_246"]), "both_price_types_usable_count": both, "no_data_ticker_count": no_data, "failed_entry_count": len(failed), "stale_entry_count": stale, "invalid_cache_file_count": invalid, "technical_ready_to_build_count_from_v21_245": s245.get("technical_ready_to_build_count", 0), "forward_return_ready_to_build_count_from_v21_245": s245.get("forward_return_ready_to_build_count", 0), "minimum_required_usable_ticker_count": min_usable, "gate_status": status, "gate_decision": decision, "blocker_summary": f"failed={len(failed)}; no_data={no_data}; stale={stale}; invalid={invalid}", "next_version": "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_R1"}]


def final_decision(gate: dict[str, Any]) -> tuple[str, str]:
    gd = gate["gate_decision"]
    if gd == "PROCEED_TO_V21_246_TECHNICAL_AND_FORWARD_PANEL_BUILD":
        return "PASS_V21_245_R1A_CACHE_CURRENTNESS_TRIAGE_READY", "CACHE_READY_FOR_V21_246_TECHNICAL_AND_FORWARD_PANEL_BUILD"
    if gd == "PROCEED_TO_V21_246_WITH_EXCLUSION_LIST":
        return "PARTIAL_PASS_V21_245_R1A_CACHE_READY_WITH_EXCLUSIONS", "CACHE_READY_FOR_V21_246_WITH_EXCLUSION_LIST"
    if gd == "RUN_TARGETED_RETRY_FIRST":
        return "WARN_V21_245_R1A_TARGETED_RETRY_RECOMMENDED", "TARGETED_MOOMOO_RETRY_RECOMMENDED_BEFORE_V21_246"
    return "WARN_V21_245_R1A_TARGETED_RETRY_RECOMMENDED", "CACHE_NOT_READY_REPAIR_REQUIRED"


FIELDS = {
    "current": ["ticker", "moomoo_symbol", "price_type", "expected_cache_file_path", "cache_file_exists", "cache_schema_valid", "row_count", "first_date", "latest_date", "expected_latest_completed_date", "latest_date_matches_expected", "days_stale_estimate", "cache_currentness_status", "cache_currentness_reason", "v21_245_result_status", "v21_245_coverage_class", "ready_for_v21_246"],
    "failed": ["ticker", "moomoo_symbol", "price_type", "result_status", "failure_class", "failure_reason", "cache_file_exists", "cache_row_count", "cache_first_date", "cache_latest_date", "symbol_mapping_suspect", "likely_delisted_or_unsupported", "permission_suspect", "retry_worthwhile", "targeted_retry_allowed", "recommended_next_action"],
    "partial": ["ticker", "moomoo_symbol", "price_type", "requested_start_date", "first_available_date", "latest_available_date", "expected_latest_completed_date", "row_count", "v21_245_result_status", "v21_245_coverage_class", "partial_history_class", "partial_history_reason", "usable_for_technical_panel", "usable_for_forward_return_panel", "earliest_technical_computable_date_estimate", "recommended_disposition"],
    "dist": ["price_type", "latest_date", "ticker_count", "ticker_pct", "example_tickers", "distribution_note"],
    "gate": ["gate_name", "expected_latest_completed_date", "universe_count", "raw_current_or_usable_count", "qfq_current_or_usable_count", "both_price_types_usable_count", "no_data_ticker_count", "failed_entry_count", "stale_entry_count", "invalid_cache_file_count", "technical_ready_to_build_count_from_v21_245", "forward_return_ready_to_build_count_from_v21_245", "minimum_required_usable_ticker_count", "gate_status", "gate_decision", "blocker_summary", "next_version"],
    "logic": ["metric_name", "v21_245_value", "recomputed_value", "interpretation", "likely_issue", "recommended_fix"],
    "integrity": ["cache_file_path", "ticker", "price_type", "file_exists", "byte_size", "row_count", "sha256_current", "sha256_manifest", "hash_matches_manifest", "required_columns_present", "duplicate_date_count", "null_close_count", "invalid_ohlc_count", "date_monotonic", "integrity_status"],
}


def write_outputs(out: Path, summary: dict[str, Any], tables: dict[str, list[dict[str, Any]]], write_exclusion: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "v21_245_r1a_summary.json", summary)
    names = {"current": "moomoo_cache_currentness_audit.csv", "failed": "moomoo_failed_symbol_triage.csv", "partial": "moomoo_partial_history_classification.csv", "dist": "moomoo_latest_date_distribution.csv", "gate": "moomoo_cache_ready_for_v21_246_gate.csv", "logic": "moomoo_currentness_logic_audit.csv", "integrity": "moomoo_cache_file_integrity_audit.csv"}
    for key, name in names.items():
        write_csv(out / name, tables[key], FIELDS[key])
    if write_exclusion:
        excluded = [r for r in tables["partial"] if r["recommended_disposition"] in {"EXCLUDE_FROM_V21_246_PANEL", "TARGETED_RETRY_MOOMOO_ONLY", "NEEDS_MANUAL_REVIEW"}]
        write_csv(out / "moomoo_v21_246_exclusion_list.csv", excluded, FIELDS["partial"])
    report = [STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"provider={PROVIDER}", "research_only=True", "official_adoption_allowed=False", "broker_action_allowed=False", "No provider backfill, factor evaluation, promotion, trade, ranking, or weight mutation was performed."]
    (out / "V21.245_R1A_moomoo_cache_currentness_triage_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


def run(repo: Path, output_dir: Path | None = None, cache_root: Path = DEFAULT_CACHE_ROOT, v245_root: Path = DEFAULT_V245_REL, expected_latest_date: str = "2026-07-03", minimum_usable_ticker_count: int = 250, write_exclusion_list: bool = False) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    try:
        summary, tables = build(repo, v245_root, cache_root, expected_latest_date, minimum_usable_ticker_count)
        summary["output_root"] = str(out)
        write_outputs(out, summary, tables, write_exclusion_list)
        return summary
    except Exception as exc:
        summary = {"version": STAGE, "final_status": "FAIL_V21_245_R1A_CACHE_TRIAGE_EXECUTION_ERROR", "final_decision": "CACHE_NOT_READY_REPAIR_REQUIRED", "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "provider": PROVIDER, "error": repr(exc), "output_root": str(out)}
        write_json(out / "v21_245_r1a_summary.json", summary)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--v21-245-root", type=Path, default=DEFAULT_V245_REL)
    p.add_argument("--expected-latest-date", default="2026-07-03")
    p.add_argument("--minimum-usable-ticker-count", type=int, default=250)
    p.add_argument("--write-exclusion-list", action="store_true")
    p.add_argument("--fail-on-not-ready", action="store_true")
    p.add_argument("--audit-only", action="store_true")
    a = p.parse_args(argv)
    try:
        s = run(a.repo_root.resolve(), a.output_dir, a.cache_root.resolve(), a.v21_245_root, a.expected_latest_date, a.minimum_usable_ticker_count, a.write_exclusion_list)
    except Exception:
        return 1
    for k in ["final_status", "final_decision", "provider", "expected_latest_completed_date", "universe_count", "audited_cache_entry_count", "cache_file_count", "current_to_expected_count", "stale_but_usable_count", "partial_ipo_late_but_current_count", "provider_limit_suspected_count", "no_data_count", "failed_entry_count", "invalid_cache_file_count", "missing_cache_file_count", "raw_recomputed_current_count", "qfq_recomputed_current_count", "both_price_types_usable_count", "ready_for_v21_246_gate_status", "ready_for_v21_246_gate_decision", "official_adoption_allowed", "broker_action_allowed", "output_root"]:
        print(f"{k}={s.get(k)}")
    return 1 if a.fail_on_not_ready and s.get("ready_for_v21_246_gate_status") == "FAIL_NOT_READY_FOR_V21_246" else 0


if __name__ == "__main__":
    raise SystemExit(main())
