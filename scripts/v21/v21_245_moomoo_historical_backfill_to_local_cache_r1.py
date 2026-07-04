#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STAGE = "V21.245_MOOMOO_HISTORICAL_BACKFILL_TO_LOCAL_CACHE_R1"
OUT_REL = Path("outputs/v21") / STAGE
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
PROVIDER = "MOOMOO"
PRICE_TYPES = ["RAW_DAILY", "QFQ_DAILY"]
STD_COLS = ["date", "ticker", "moomoo_symbol", "open", "high", "low", "close", "volume", "turnover", "price_type", "provider", "fetch_timestamp", "source_run_id"]
TECHNICALS = [
    ("RSI", 15), ("KDJ", 30), ("K", 30), ("D", 30), ("J", 30), ("MACD", 35), ("DIF", 35), ("DEA", 35),
    ("Bollinger Bands", 20), ("BB", 20), ("MA20", 20), ("MA50", 50), ("EMA", 35), ("volume_ma", 20),
    ("volatility", 20), ("momentum", 20), ("relative_strength", 60), ("breakout", 60), ("pullback", 30),
]
FORWARD_HORIZONS = ["1D", "5D", "10D", "20D"]


class DailyProvider(Protocol):
    def fetch_daily(self, ticker: str, moomoo_symbol: str, start: str, end: str, price_type: str) -> list[dict[str, Any]]:
        ...


class MoomooDailyProvider:
    """Quote-data adapter only; no trade context, unlock, or broker action APIs."""

    def __init__(self, sleep_seconds: float = 0.25):
        self.sleep_seconds = sleep_seconds
        from scripts.data_sources.moomoo_client import MoomooQuoteClient
        self.client = MoomooQuoteClient()
        from scripts.data_sources.moomoo_daily_ohlcv_fetcher import fetch_history_daily
        self._fetch_history_daily = fetch_history_daily

    def __enter__(self) -> "MoomooDailyProvider":
        self.client.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.client.__exit__(exc_type, exc, tb)

    def fetch_daily(self, ticker: str, moomoo_symbol: str, start: str, end: str, price_type: str) -> list[dict[str, Any]]:
        mode = "RAW" if price_type == "RAW_DAILY" else "QFQ"
        frame = self._fetch_history_daily(self.client, ticker, moomoo_symbol, start=start, end=end, adjustment_mode=mode)
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        if hasattr(frame, "to_dict"):
            return frame.to_dict("records")
        return list(frame or [])


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id() -> str:
    return f"{STAGE}__{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def latest_completed_session(today: date | None = None) -> str:
    d = today or datetime.now().date()
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def read_rows(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            out = []
            for i, row in enumerate(csv.DictReader(f)):
                if limit is not None and i >= limit:
                    break
                out.append({k: (v or "") for k, v in row.items() if k is not None})
            return out
    except Exception:
        return []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return ""
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_file(cache_root: Path, ticker: str, price_type: str) -> Path:
    sub = "raw" if price_type == "RAW_DAILY" else "qfq"
    safe = "".join(ch for ch in ticker.upper() if ch.isalnum() or ch in "._-")
    return cache_root / "market_data" / "moomoo" / "daily" / sub / f"{safe}.csv"


def registry_dir(cache_root: Path) -> Path:
    return cache_root / "market_data" / "moomoo" / "registry"


def normalize_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return t if t.startswith("US.") else f"US.{t}"


def is_valid_us_equity_symbol(ticker: str) -> bool:
    if not ticker or len(ticker) > 8:
        return False
    bad = {"", "NAN", "NONE", "CASH"}
    return ticker.upper() not in bad and all(ch.isalnum() or ch in ".-" for ch in ticker)


def discover_universe(repo: Path, universe_source: str = "auto", top_n: int | None = None) -> list[dict[str, Any]]:
    candidates = [
        repo / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN",
        repo / "outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN",
        repo / "outputs/v21/V21.244_FACTOR_EFFECTIVENESS_COVERAGE_AND_GRANULARITY_REPAIR_R1",
        repo / "outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN",
        repo / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
        repo / "outputs/v21/V21.250_E_R2_SHADOW_FORWARD_TRACKING_LEDGER",
        repo / "outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY",
    ]
    files: list[Path] = []
    for d in candidates:
        if d.exists():
            files.extend(sorted(d.glob("*.csv")))
    seen: dict[str, dict[str, Any]] = {}
    for path in files:
        rows = read_rows(path, 5000)
        if not rows:
            continue
        cols = {c.lower(): c for c in rows[0].keys()}
        ticker_col = cols.get("ticker") or cols.get("internal_symbol") or cols.get("symbol")
        if not ticker_col:
            continue
        for r in rows:
            ticker = str(r.get(ticker_col, "")).strip().upper().replace("US.", "")
            if not ticker or ticker in seen:
                continue
            status = "INCLUDED" if is_valid_us_equity_symbol(ticker) else "EXCLUDED_BAD_SYMBOL"
            seen[ticker] = {
                "ticker": ticker,
                "moomoo_symbol": normalize_symbol(ticker),
                "market": "US",
                "security_type": "EQUITY",
                "source_artifact": str(path.relative_to(repo)).replace("\\", "/") if path.is_relative_to(repo) else str(path),
                "included_in_canonical_universe": status == "INCLUDED",
                "included_in_recent_abcde": "ABCDE" in str(path).upper() or "RANK" in path.name.upper(),
                "included_in_dram": ticker == "DRAM",
                "ipo_or_first_seen_date_if_known": "",
                "universe_status": status,
            }
            if top_n is not None and len(seen) >= top_n:
                return list(seen.values())
    return list(seen.values())[:top_n] if top_n is not None else list(seen.values())


def cache_latest(path: Path) -> str:
    rows = read_rows(path)
    dates = sorted({r.get("date", "") for r in rows if r.get("date")})
    return dates[-1] if dates else ""


def build_plan(universe: list[dict[str, Any]], cache_root: Path, start: str, end: str, price_types: list[str]) -> list[dict[str, Any]]:
    rows = []
    for u in universe:
        for price_type in price_types:
            cp = cache_file(cache_root, u["ticker"], price_type)
            latest = cache_latest(cp)
            excluded = u["universe_status"] != "INCLUDED"
            if excluded:
                status = "SKIP_UNIVERSE_EXCLUDED" if u["universe_status"] != "EXCLUDED_BAD_SYMBOL" else "SKIP_INVALID_SYMBOL"
                needed = False
                fetch_start = ""
            elif latest and latest >= end:
                status = "SKIP_ALREADY_CURRENT"
                needed = False
                fetch_start = ""
            else:
                status = "FETCH_REQUIRED"
                needed = True
                fetch_start = (date.fromisoformat(latest) + timedelta(days=1)).isoformat() if latest else start
            rows.append({
                "ticker": u["ticker"], "moomoo_symbol": u["moomoo_symbol"], "price_type": price_type, "kline_type": "K_DAY",
                "requested_start_date": start, "requested_end_date": end, "existing_cache_path": str(cp),
                "existing_cache_latest_date": latest, "fetch_start_date": fetch_start, "fetch_end_date": end if needed else "",
                "backfill_needed": needed, "priority": "HIGH" if u.get("included_in_recent_abcde") or u["ticker"] == "DRAM" else "NORMAL",
                "plan_status": status,
            })
    return rows


def normalize_provider_rows(rows: list[dict[str, Any]], ticker: str, moomoo_symbol: str, price_type: str, rid: str) -> list[dict[str, Any]]:
    out = []
    stamp = utc_now()
    for r in rows:
        d = str(r.get("date") or r.get("time_key") or r.get("time") or "")[:10]
        if not d:
            continue
        out.append({
            "date": d,
            "ticker": ticker,
            "moomoo_symbol": moomoo_symbol,
            "open": r.get("open", ""),
            "high": r.get("high", ""),
            "low": r.get("low", ""),
            "close": r.get("close", ""),
            "volume": r.get("volume", ""),
            "turnover": r.get("turnover", ""),
            "price_type": price_type,
            "provider": PROVIDER,
            "fetch_timestamp": stamp,
            "source_run_id": rid,
        })
    return out


def valid_schema(rows: list[dict[str, Any]]) -> bool:
    for r in rows:
        try:
            vals = [float(r[k]) for k in ["open", "high", "low", "close"]]
            if any(v < 0 for v in vals):
                return False
            float(r.get("volume") or 0)
        except Exception:
            return False
    return True


def merge_cache(path: Path, new_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool, str]:
    old = read_rows(path)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for r in old + new_rows:
        d = r.get("date", "")
        t = r.get("ticker", "")
        if d and t:
            merged[(t, d)] = {c: r.get(c, "") for c in STD_COLS}
    rows = sorted(merged.values(), key=lambda r: (r["ticker"], r["date"]))
    dates = [r["date"] for r in rows]
    if dates != sorted(dates):
        return rows, False, "date monotonicity validation failed"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(path, rows, STD_COLS)
    return rows, True, ""


def result_for_skip(plan: dict[str, Any]) -> dict[str, Any]:
    cp = Path(plan["existing_cache_path"])
    rows = read_rows(cp)
    dates = sorted({r.get("date", "") for r in rows if r.get("date")})
    return {
        "ticker": plan["ticker"], "moomoo_symbol": plan["moomoo_symbol"], "price_type": plan["price_type"],
        "requested_start_date": plan["requested_start_date"], "requested_end_date": plan["requested_end_date"],
        "first_available_date": dates[0] if dates else "", "latest_available_date": dates[-1] if dates else "",
        "fetched_row_count": 0, "final_cache_row_count": len(rows), "cache_file_path": str(cp), "sha256": sha256_file(cp),
        "result_status": "SKIPPED_ALREADY_CURRENT", "warning_count": 0, "error_count": 0, "message": "existing cache current",
    }


def execute_plan(plan: list[dict[str, Any]], provider: DailyProvider, cache_root: Path, rid: str, progress_path: Path, fail_on_all_fetch_failed: bool = False) -> list[dict[str, Any]]:
    results = []
    for i, p in enumerate(plan, 1):
        if p["plan_status"] == "SKIP_ALREADY_CURRENT":
            res = result_for_skip(p)
            results.append(res)
        elif p["plan_status"] != "FETCH_REQUIRED":
            res = empty_result(p, "FAIL_NO_MOOMOO_DATA", "plan skipped or invalid")
            results.append(res)
        else:
            cp = Path(p["existing_cache_path"])
            try:
                raw = provider.fetch_daily(p["ticker"], p["moomoo_symbol"], p["fetch_start_date"], p["fetch_end_date"], p["price_type"])
                new_rows = normalize_provider_rows(raw, p["ticker"], p["moomoo_symbol"], p["price_type"], rid)
                if not new_rows:
                    res = empty_result(p, "FAIL_EMPTY_RESPONSE", "provider returned no rows")
                elif not valid_schema(new_rows):
                    res = empty_result(p, "FAIL_SCHEMA_ERROR", "OHLCV schema validation failed")
                else:
                    final_rows, ok, msg = merge_cache(cp, new_rows)
                    if not ok:
                        res = empty_result(p, "FAIL_SCHEMA_ERROR", msg)
                    else:
                        dates = sorted({r["date"] for r in final_rows if r.get("date")})
                        first, latest = (dates[0], dates[-1]) if dates else ("", "")
                        full = first <= p["requested_start_date"] and latest >= p["requested_end_date"]
                        status = "SUCCESS_FULL" if full else "SUCCESS_PARTIAL_IPO_LATE" if first and first > p["requested_start_date"] else "SUCCESS_PARTIAL_PROVIDER_LIMIT"
                        res = {
                            "ticker": p["ticker"], "moomoo_symbol": p["moomoo_symbol"], "price_type": p["price_type"],
                            "requested_start_date": p["requested_start_date"], "requested_end_date": p["requested_end_date"],
                            "first_available_date": first, "latest_available_date": latest, "fetched_row_count": len(new_rows),
                            "final_cache_row_count": len(final_rows), "cache_file_path": str(cp), "sha256": sha256_file(cp),
                            "result_status": status, "warning_count": 0 if status == "SUCCESS_FULL" else 1, "error_count": 0,
                            "message": "cache updated",
                        }
            except PermissionError as exc:
                res = empty_result(p, "FAIL_PERMISSION_OR_SUBSCRIPTION", str(exc))
            except Exception as exc:
                res = empty_result(p, "FAIL_PROVIDER_ERROR", f"{type(exc).__name__}: {exc}")
            results.append(res)
        write_csv(progress_path, [{**r, "progress_index": j + 1} for j, r in enumerate(results)], RESULT_FIELDS + ["progress_index"])
    if fail_on_all_fetch_failed and plan and not any(str(r["result_status"]).startswith(("SUCCESS", "SKIPPED")) for r in results):
        raise RuntimeError("all Moomoo fetches failed")
    return results


def empty_result(p: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    return {
        "ticker": p["ticker"], "moomoo_symbol": p["moomoo_symbol"], "price_type": p["price_type"],
        "requested_start_date": p["requested_start_date"], "requested_end_date": p["requested_end_date"],
        "first_available_date": "", "latest_available_date": "", "fetched_row_count": 0, "final_cache_row_count": len(read_rows(Path(p["existing_cache_path"]))),
        "cache_file_path": p["existing_cache_path"], "sha256": sha256_file(Path(p["existing_cache_path"])), "result_status": status,
        "warning_count": 0, "error_count": 1, "message": message,
    }


RESULT_FIELDS = ["ticker", "moomoo_symbol", "price_type", "requested_start_date", "requested_end_date", "first_available_date", "latest_available_date", "fetched_row_count", "final_cache_row_count", "cache_file_path", "sha256", "result_status", "warning_count", "error_count", "message"]


def manifest_rows(results: list[dict[str, Any]], rid: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = utc_now()
    manifest, hashes = [], []
    for r in results:
        cp = Path(r["cache_file_path"])
        rows = read_rows(cp)
        dates = sorted({x.get("date", "") for x in rows if x.get("date")})
        status = "CURRENT" if r["result_status"] in {"SUCCESS_FULL", "SKIPPED_ALREADY_CURRENT"} else "PARTIAL" if str(r["result_status"]).startswith("SUCCESS_PARTIAL") else "MISSING" if not rows else "INVALID"
        manifest.append({"cache_file_path": str(cp), "ticker": r["ticker"], "moomoo_symbol": r["moomoo_symbol"], "price_type": r["price_type"], "provider": PROVIDER, "first_date": dates[0] if dates else "", "latest_date": dates[-1] if dates else "", "row_count": len(rows), "created_at": now, "updated_at": now, "source_run_id": rid, "cache_status": status})
        hashes.append({"cache_file_path": str(cp), "sha256": sha256_file(cp), "byte_size": cp.stat().st_size if cp.exists() else 0, "row_count": len(rows), "generated_at": now, "source_run_id": rid})
    return manifest, hashes


def failure_audit(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        st = r["result_status"]
        if st in {"SUCCESS_FULL", "SKIPPED_ALREADY_CURRENT"}:
            continue
        if st == "SUCCESS_PARTIAL_IPO_LATE":
            cls, action, repair = "PARTIAL_HISTORY", "ACCEPT_IPO_LATE_PARTIAL", False
        elif st == "SUCCESS_PARTIAL_PROVIDER_LIMIT":
            cls, action, repair = "PARTIAL_HISTORY", "ACCEPT_PROVIDER_LIMIT_PARTIAL", True
        elif st == "FAIL_EMPTY_RESPONSE":
            cls, action, repair = "EMPTY_RESPONSE", "RETRY_LATER", True
        elif st == "FAIL_PERMISSION_OR_SUBSCRIPTION":
            cls, action, repair = "PROVIDER_PERMISSION", "NEEDS_USER_REVIEW", True
        elif st == "FAIL_SCHEMA_ERROR":
            cls, action, repair = "SCHEMA_ERROR", "NEEDS_USER_REVIEW", True
        elif st == "FAIL_NO_MOOMOO_DATA":
            cls, action, repair = "PROVIDER_NO_DATA", "EXCLUDE_FROM_FACTOR_PANEL", False
        else:
            cls, action, repair = "UNKNOWN", "RETRY_LATER", True
        out.append({"ticker": r["ticker"], "moomoo_symbol": r["moomoo_symbol"], "price_type": r["price_type"], "result_status": st, "failure_class": cls, "failure_reason": r["message"], "repair_possible": repair, "next_action": action})
    return out


def coverage_audit(universe: list[dict[str, Any]], manifest: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    by = {(r["ticker"], r["price_type"]): r for r in manifest}
    target_days = max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
    out = []
    for u in universe:
        raw = by.get((u["ticker"], "RAW_DAILY"), {})
        qfq = by.get((u["ticker"], "QFQ_DAILY"), {})
        raw_rows, qfq_rows = int(raw.get("row_count") or 0), int(qfq.get("row_count") or 0)
        raw_ratio, qfq_ratio = raw_rows / target_days, qfq_rows / target_days
        if raw_rows <= 0 and qfq_rows <= 0:
            cls = "NO_DATA"
        elif ((raw.get("first_date") or "9999") <= start and (raw.get("latest_date") or "") >= end) or ((qfq.get("first_date") or "9999") <= start and (qfq.get("latest_date") or "") >= end):
            cls = "FULL_FROM_2018"
        elif raw_rows or qfq_rows:
            cls = "PARTIAL_IPO_LATE"
        else:
            cls = "INVALID"
        out.append({"ticker": u["ticker"], "raw_daily_status": raw.get("cache_status", "MISSING"), "qfq_daily_status": qfq.get("cache_status", "MISSING"), "raw_first_date": raw.get("first_date", ""), "raw_latest_date": raw.get("latest_date", ""), "qfq_first_date": qfq.get("first_date", ""), "qfq_latest_date": qfq.get("latest_date", ""), "raw_row_count": raw_rows, "qfq_row_count": qfq_rows, "coverage_start_target": start, "coverage_end_target": end, "raw_coverage_ratio": raw_ratio, "qfq_coverage_ratio": qfq_ratio, "missing_date_count_estimate": max(0, target_days - max(raw_rows, qfq_rows)), "coverage_class": cls})
    return out


def build_technical_plan(manifest: list[dict[str, Any]], start: str) -> list[dict[str, Any]]:
    has_qfq = any(r["price_type"] == "QFQ_DAILY" and int(r.get("row_count") or 0) > 0 for r in manifest)
    out = []
    for name, lookback in TECHNICALS:
        earliest = (date.fromisoformat(start) + timedelta(days=lookback)).isoformat()
        out.append({"technical_subfactor_name": name, "source_required": "daily OHLCV cache", "source_available_in_cache": has_qfq, "required_price_type": "QFQ_DAILY", "minimum_lookback_days": lookback, "earliest_computable_date": earliest if has_qfq else "", "build_status": "READY_TO_BUILD_FROM_CACHE" if has_qfq else "WAITING_FOR_CACHE", "next_version": "V21.246_TECHNICAL_INDICATOR_PANEL_BUILD_R1"})
    return out


def build_forward_plan(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_qfq = any(r["price_type"] == "QFQ_DAILY" and int(r.get("row_count") or 0) > 0 for r in manifest)
    return [{"horizon": h, "source_required": "daily close cache", "source_available_in_cache": has_qfq, "required_price_type": "QFQ_DAILY", "maturity_rule": f"requires close at t+{h[:-1]} completed trading sessions", "build_status": "READY_TO_BUILD_FROM_CACHE" if has_qfq else "WAITING_FOR_CACHE", "next_version": "V21.246_FORWARD_RETURN_PANEL_BUILD_R1"} for h in FORWARD_HORIZONS]


def summary_status(execute: bool, allow_fetch: bool, results: list[dict[str, Any]], coverage: list[dict[str, Any]]) -> tuple[str, str]:
    if not execute or not allow_fetch:
        return "WARN_V21_245_MOOMOO_BACKFILL_PARTIAL_PROVIDER_LIMITS", "MOOMOO_HISTORICAL_CACHE_PARTIAL_CONTINUE_REPAIR"
    failed = sum(1 for r in results if str(r["result_status"]).startswith("FAIL"))
    success = sum(1 for r in results if str(r["result_status"]).startswith("SUCCESS") or r["result_status"] == "SKIPPED_ALREADY_CURRENT")
    if success == 0 and failed > 0:
        return "WARN_V21_245_MOOMOO_BACKFILL_PARTIAL_PROVIDER_LIMITS", "MOOMOO_HISTORICAL_CACHE_BLOCKED_BY_PROVIDER_OR_PERMISSION"
    if failed or any(r["coverage_class"].startswith("PARTIAL") for r in coverage):
        return "PARTIAL_PASS_V21_245_MOOMOO_BACKFILL_CACHE_READY_WITH_WARNINGS", "MOOMOO_HISTORICAL_CACHE_PARTIAL_CONTINUE_REPAIR"
    return "PASS_V21_245_MOOMOO_HISTORICAL_BACKFILL_CACHE_READY", "MOOMOO_HISTORICAL_CACHE_READY_FOR_FACTOR_PANEL_RECONSTRUCTION"


def run(repo: Path, output_dir: Path | None = None, cache_root: Path = DEFAULT_CACHE_ROOT, start_date: str = "2018-01-01", end_date: str = "latest_completed", universe_source: str = "auto", price_types: list[str] | None = None, execute: bool = False, allow_moomoo_provider_fetch: bool = False, resume: bool = False, top_n: int | None = None, fail_on_all_fetch_failed: bool = False, provider: DailyProvider | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    rid = run_id()
    end = latest_completed_session() if end_date == "latest_completed" else end_date
    pts = price_types or PRICE_TYPES
    try:
        universe = discover_universe(repo, universe_source, top_n)
        plan = build_plan(universe, cache_root, start_date, end, pts)
        results: list[dict[str, Any]] = []
        if execute and allow_moomoo_provider_fetch and plan:
            registry_dir(cache_root).mkdir(parents=True, exist_ok=True)
            if provider is not None:
                results = execute_plan(plan, provider, cache_root, rid, out / "moomoo_backfill_progress.csv", fail_on_all_fetch_failed)
            else:
                with MoomooDailyProvider() as real_provider:
                    results = execute_plan(plan, real_provider, cache_root, rid, out / "moomoo_backfill_progress.csv", fail_on_all_fetch_failed)
        else:
            results = [result_for_skip(p) if p["plan_status"] == "SKIP_ALREADY_CURRENT" else empty_result(p, "FAIL_NO_MOOMOO_DATA", "dry run or provider fetch not allowed; plan only") for p in plan]
            write_csv(out / "moomoo_backfill_progress.csv", results, RESULT_FIELDS)
        manifest, hashes = manifest_rows(results, rid)
        coverage = coverage_audit(universe, manifest, start_date, end)
        tech_plan = build_technical_plan(manifest, start_date)
        fwd_plan = build_forward_plan(manifest)
        status, decision = summary_status(execute, allow_moomoo_provider_fetch, results, coverage)
        summary = {
            "version": STAGE, "final_status": status, "final_decision": decision, "research_only": True,
            "official_adoption_allowed": False, "broker_action_allowed": False, "provider": PROVIDER,
            "backfill_start_date": start_date, "backfill_end_date": end, "universe_count": len(universe),
            "planned_fetch_count": sum(1 for p in plan if p["plan_status"] == "FETCH_REQUIRED"),
            "successful_full_count": sum(1 for r in results if r["result_status"] == "SUCCESS_FULL"),
            "successful_partial_count": sum(1 for r in results if str(r["result_status"]).startswith("SUCCESS_PARTIAL")),
            "skipped_already_current_count": sum(1 for r in results if r["result_status"] == "SKIPPED_ALREADY_CURRENT"),
            "failed_count": sum(1 for r in results if str(r["result_status"]).startswith("FAIL")),
            "raw_daily_current_count": sum(1 for r in manifest if r["price_type"] == "RAW_DAILY" and r["cache_status"] == "CURRENT"),
            "qfq_daily_current_count": sum(1 for r in manifest if r["price_type"] == "QFQ_DAILY" and r["cache_status"] == "CURRENT"),
            "full_from_2018_count": sum(1 for r in coverage if r["coverage_class"] == "FULL_FROM_2018"),
            "partial_ipo_late_count": sum(1 for r in coverage if r["coverage_class"] == "PARTIAL_IPO_LATE"),
            "no_data_count": sum(1 for r in coverage if r["coverage_class"] == "NO_DATA"),
            "cache_manifest_row_count": len(manifest),
            "technical_ready_to_build_count": sum(1 for r in tech_plan if r["build_status"] == "READY_TO_BUILD_FROM_CACHE"),
            "forward_return_ready_to_build_count": sum(1 for r in fwd_plan if r["build_status"] == "READY_TO_BUILD_FROM_CACHE"),
            "output_root": str(out), "cache_root": str(cache_root), "official_factor_marked_count": 0, "shadow_candidate_marked_count": 0,
        }
        write_all_outputs(out, cache_root, summary, universe, plan, results, manifest, hashes, coverage, tech_plan, fwd_plan)
        if execute and allow_moomoo_provider_fetch:
            registry_dir(cache_root).mkdir(parents=True, exist_ok=True)
            write_csv(registry_dir(cache_root) / "moomoo_cache_manifest.csv", manifest, MANIFEST_FIELDS)
            write_csv(registry_dir(cache_root) / "moomoo_cache_hash_manifest.csv", hashes, HASH_FIELDS)
        return summary
    except Exception as exc:
        summary = {"version": STAGE, "final_status": "FAIL_V21_245_MOOMOO_BACKFILL_EXECUTION_ERROR", "final_decision": "MOOMOO_HISTORICAL_CACHE_BLOCKED_BY_PROVIDER_OR_PERMISSION", "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "provider": PROVIDER, "backfill_start_date": start_date, "backfill_end_date": end, "output_root": str(out), "cache_root": str(cache_root), "error": repr(exc)}
        write_json(out / "v21_245_summary.json", summary)
        raise


UNIVERSE_FIELDS = ["ticker", "moomoo_symbol", "market", "security_type", "source_artifact", "included_in_canonical_universe", "included_in_recent_abcde", "included_in_dram", "ipo_or_first_seen_date_if_known", "universe_status"]
PLAN_FIELDS = ["ticker", "moomoo_symbol", "price_type", "kline_type", "requested_start_date", "requested_end_date", "existing_cache_path", "existing_cache_latest_date", "fetch_start_date", "fetch_end_date", "backfill_needed", "priority", "plan_status"]
FAIL_FIELDS = ["ticker", "moomoo_symbol", "price_type", "result_status", "failure_class", "failure_reason", "repair_possible", "next_action"]
MANIFEST_FIELDS = ["cache_file_path", "ticker", "moomoo_symbol", "price_type", "provider", "first_date", "latest_date", "row_count", "created_at", "updated_at", "source_run_id", "cache_status"]
HASH_FIELDS = ["cache_file_path", "sha256", "byte_size", "row_count", "generated_at", "source_run_id"]
COVERAGE_FIELDS = ["ticker", "raw_daily_status", "qfq_daily_status", "raw_first_date", "raw_latest_date", "qfq_first_date", "qfq_latest_date", "raw_row_count", "qfq_row_count", "coverage_start_target", "coverage_end_target", "raw_coverage_ratio", "qfq_coverage_ratio", "missing_date_count_estimate", "coverage_class"]
TECH_FIELDS = ["technical_subfactor_name", "source_required", "source_available_in_cache", "required_price_type", "minimum_lookback_days", "earliest_computable_date", "build_status", "next_version"]
FWD_FIELDS = ["horizon", "source_required", "source_available_in_cache", "required_price_type", "maturity_rule", "build_status", "next_version"]


def write_all_outputs(out: Path, cache_root: Path, summary: dict[str, Any], universe: list[dict[str, Any]], plan: list[dict[str, Any]], results: list[dict[str, Any]], manifest: list[dict[str, Any]], hashes: list[dict[str, Any]], coverage: list[dict[str, Any]], tech_plan: list[dict[str, Any]], fwd_plan: list[dict[str, Any]]) -> None:
    write_json(out / "v21_245_summary.json", summary)
    write_csv(out / "moomoo_backfill_universe.csv", universe, UNIVERSE_FIELDS)
    write_csv(out / "moomoo_backfill_plan.csv", plan, PLAN_FIELDS)
    if not (out / "moomoo_backfill_progress.csv").exists():
        write_csv(out / "moomoo_backfill_progress.csv", results, RESULT_FIELDS)
    write_csv(out / "moomoo_backfill_result.csv", results, RESULT_FIELDS)
    write_csv(out / "moomoo_backfill_failure_audit.csv", failure_audit(results), FAIL_FIELDS)
    write_csv(out / "moomoo_cache_manifest.csv", manifest, MANIFEST_FIELDS)
    write_csv(out / "moomoo_cache_hash_manifest.csv", hashes, HASH_FIELDS)
    write_csv(out / "moomoo_daily_panel_coverage_audit.csv", coverage, COVERAGE_FIELDS)
    write_csv(out / "technical_indicator_build_plan.csv", tech_plan, TECH_FIELDS)
    write_csv(out / "forward_return_build_plan.csv", fwd_plan, FWD_FIELDS)
    report = [STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"provider={PROVIDER}", f"cache_root={cache_root}", "research_only=True", "official_adoption_allowed=False", "broker_action_allowed=False", "No factor effectiveness, promotion, ranking, weight, trade, or broker action mutation was performed."]
    (out / "V21.245_moomoo_historical_backfill_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo-root", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--start-date", default="2018-01-01")
    p.add_argument("--end-date", default="latest_completed")
    p.add_argument("--universe-source", default="auto")
    p.add_argument("--price-types", default="raw,qfq")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--top-n", type=int)
    p.add_argument("--fail-on-all-fetch-failed", action="store_true")
    p.add_argument("--allow-moomoo-provider-fetch", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    price_types = []
    for item in a.price_types.split(","):
        x = item.strip().lower()
        if x == "raw":
            price_types.append("RAW_DAILY")
        elif x == "qfq":
            price_types.append("QFQ_DAILY")
    try:
        s = run(a.repo_root.resolve(), a.output_dir, a.cache_root.resolve(), a.start_date, a.end_date, a.universe_source, price_types or PRICE_TYPES, execute=bool(a.execute), allow_moomoo_provider_fetch=bool(a.allow_moomoo_provider_fetch), resume=a.resume, top_n=a.top_n, fail_on_all_fetch_failed=a.fail_on_all_fetch_failed)
    except Exception:
        return 1
    for key in ["final_status", "final_decision", "provider", "backfill_start_date", "backfill_end_date", "universe_count", "planned_fetch_count", "successful_full_count", "successful_partial_count", "skipped_already_current_count", "failed_count", "raw_daily_current_count", "qfq_daily_current_count", "full_from_2018_count", "partial_ipo_late_count", "no_data_count", "technical_ready_to_build_count", "forward_return_ready_to_build_count", "official_adoption_allowed", "broker_action_allowed", "output_root", "cache_root"]:
        print(f"{key}={s.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
