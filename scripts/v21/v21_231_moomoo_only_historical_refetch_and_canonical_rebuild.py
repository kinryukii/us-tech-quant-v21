#!/usr/bin/env python
"""V21.231 Moomoo-only historical refetch and canonical rebuild."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import pandas as pd
except Exception:  # pragma: no cover - tests exercise stdlib fallback lightly
    pd = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.prerequisite_lifecycle import R1 as PREREQ_R1, V230 as PREREQ_V230, resolve as resolve_prerequisite


STAGE = "V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
OUT_REL = Path("outputs/v21") / STAGE
V230_REL = Path("outputs/v21/V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN")
V230R1_REL = Path("outputs/v21/V21.230_R1_MOOMOO_OPEND_READINESS_AND_PERMISSION_PROBE")
NEXT_STAGE = "V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
PASS_STATUS = "PASS_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY"
WARN_STATUS = "WARN_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY_WITH_COVERAGE_WARNINGS"
FAIL_DAILY = "FAIL_V21_231_DAILY_COVERAGE_BELOW_THRESHOLD"
FAIL_DRAM = "FAIL_V21_231_DRAM_INTRADAY_FETCH_FAILED"
FAIL_SOURCE = "FAIL_V21_231_SOURCE_POLICY_VIOLATION"
FAIL_QUALITY = "FAIL_V21_231_CANONICAL_QUALITY_CHECK_FAILED"
FAIL_INPUT = "FAIL_V21_231_READINESS_INPUTS_MISSING_OR_NOT_READY"
FAIL_SNAPSHOT = "FAIL_V21_231_SNAPSHOT_OVERWRITE_BLOCKED"
FINAL_DECISION = "MOOMOO_ONLY_CANONICAL_READY_FOR_DRAM_AND_ABCDE_RERUN"
BLOCKED_DECISION = "MOOMOO_ONLY_CANONICAL_BLOCKED_READINESS_INPUTS_MISSING_OR_INVALID"
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"
SDK_NAMES = ["moo" + "moo", "fu" + "tu"]
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
ABCDE_STOCKS_ROOT = Path(r"D:\us-tech-quant-data\stocks")
ABCDE_UNIVERSE_MANIFEST = Path(r"D:\us-tech-quant-data\moomoo\metadata\abcde_price_universe_r2.csv")
ABCDE_UNIVERSE_METADATA = ABCDE_UNIVERSE_MANIFEST.with_suffix(".active_manifest.json")

FETCH_FIELDS = ["ticker","moomoo_symbol","market","asset_type","active_scope","frequency","adjustment","planned_start_date","planned_end_date","attempted","success","fetch_status","row_count","latest_bar_date","cache_path","sha256","error_type","error_message","retry_count","source","source_policy","notes"]
DAILY_FIELDS = ["ticker","moomoo_symbol","market","attempted","success","row_count","first_date","latest_date","cache_path","sha256","error_type","notes"]
INTRA_FIELDS = ["ticker","moomoo_symbol","frequency","attempted","success","row_count","first_timestamp","latest_timestamp","cache_path","sha256","error_type","notes"]
CANON_FIELDS = ["canonical_artifact","path","adjustment","row_count","ticker_count","first_date","latest_date","sha256","source_policy","yfinance_used","external_fallback_used","notes"]
QUALITY_FIELDS = ["check_name","scope","passed","severity","affected_rows","affected_tickers","notes"]
COVERAGE_FIELDS = ["ticker","moomoo_symbol","daily_raw_success","daily_qfq_success","intraday_success","raw_latest_date","qfq_latest_date","coverage_status","missing_reason","notes"]
FAILED_FIELDS = ["ticker","moomoo_symbol","frequency","adjustment","error_type","error_message","retry_count","retry_allowed","yahoo_fallback_allowed","external_fallback_allowed","required_user_review","notes"]
ERROR_FIELDS = ["timestamp_utc","ticker","moomoo_symbol","frequency","adjustment","api_call","error_type","error_message","retry_count","severity","notes"]
RATE_FIELDS = ["timestamp_utc","ticker","adjustment","frequency","api_call","calls_in_previous_30_seconds","waited_seconds","notes"]
EXCLUSION_FIELDS = ["ticker","target_date","exclusion_reason","effective_date","last_trading_date","evidence_source","evidence_reference","evidence_value","reviewed_at","allowed"]
RECONNECT_FIELDS = ["timestamp_utc","event","detail"]
WRITE_FIELDS = ["source_path_or_api","cache_path","file_exists","size_bytes","sha256","written_now","already_present_verified","verified","notes"]
CROSS_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
AUDIT_FIELDS = ["check_name","passed","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]
POINTER_CSV_FIELDS = ["key","value"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_abcde_universe() -> set[str]:
    """Load the sole current ABCDE authority and verify its declared digest.

    Historical snapshots and PIT inputs deliberately do not participate here:
    this function describes only today's active daily-refresh membership.
    """
    rows = read_csv_rows(ABCDE_UNIVERSE_MANIFEST)
    universe = {r.get("ticker", "").upper() for r in rows if r.get("ticker")}
    metadata = read_json(ABCDE_UNIVERSE_METADATA)
    declared = str(metadata.get("sha256", ""))
    if metadata and declared and ABCDE_UNIVERSE_MANIFEST.exists() and sha256_file(ABCDE_UNIVERSE_MANIFEST) != declared:
        raise RuntimeError("ACTIVE_ABCDE_UNIVERSE_SHA256_MISMATCH")
    if metadata and int(metadata.get("active_ticker_count", len(universe))) != len(universe):
        raise RuntimeError("ACTIVE_ABCDE_UNIVERSE_COUNT_MISMATCH")
    return universe


class HistoryKlineLimiter:
    """One limiter for every history-kline page, adjustment, and retry."""
    def __init__(self, max_calls: int = 55, window_seconds: float = 30.0, min_interval: float = 0.62) -> None:
        self.max_calls, self.window_seconds, self.min_interval = max_calls, window_seconds, min_interval
        self.calls: deque[float] = deque()
        self.last_call = 0.0
        self.audit_rows: list[dict[str, Any]] = []

    def acquire(self, item: dict[str, Any]) -> None:
        waited = 0.0
        while True:
            now = time.monotonic()
            while self.calls and now - self.calls[0] >= self.window_seconds:
                self.calls.popleft()
            delay = max(0.0, self.min_interval - (now - self.last_call)) if self.last_call else 0.0
            if len(self.calls) >= self.max_calls:
                delay = max(delay, self.window_seconds - (now - self.calls[0]) + 0.01)
            if delay <= 0:
                break
            time.sleep(delay); waited += delay
        now = time.monotonic(); self.calls.append(now); self.last_call = now
        self.audit_rows.append({"timestamp_utc": utc_now(), "ticker": item["ticker"], "adjustment": item["adjustment"], "frequency": item["frequency"], "api_call": "request_history_kline", "calls_in_previous_30_seconds": len(self.calls) - 1, "waited_seconds": round(waited, 3), "notes": "global sliding-window limiter"})


def is_rate_limit_error(message: str) -> bool:
    text = (message or "").lower()
    return "30" in text and ("60" in text or "rate" in text or "频" in text) and ("max" in text or "每" in text or "too" in text)


def make_snapshot_id() -> str:
    return datetime.now().strftime("moomoo_only_%Y%m%d_%H%M%S")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def read_csv_rows(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows: list[dict[str, str]] = []
            for row in csv.DictReader(handle):
                rows.append({k: (v or "") for k, v in row.items() if k is not None})
                if limit is not None and len(rows) >= limit:
                    break
            return rows
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy_guard(repo_root: Path):
    guard_path = repo_root / "scripts/v21/v21_data_source_policy_guard.py"
    if not guard_path.exists():
        raise FileNotFoundError(str(guard_path))
    spec = importlib.util.spec_from_file_location("v21_data_source_policy_guard", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load policy guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_policy_gate() -> dict[str, Any]:
    return {
        "policy_version": "V21.231",
        "execution_stage": "Moomoo-only historical refetch and canonical rebuild",
        "moomoo_historical_fetch_allowed_now": True,
        "canonical_rebuild_allowed_now": True,
        "overwrite_allowed_now": False,
        "yfinance_allowed": False,
        "yahoo_allowed": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "broker_action_allowed": False,
        "trade_unlock_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "next_allowed_stage": NEXT_STAGE,
    }


def self_forbidden_audit(repo_root: Path) -> tuple[list[dict[str, Any]], bool]:
    script = repo_root / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    import_present = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call_present = FORBIDDEN_PROVIDER_CALL in text
    return ([{
        "check_name": "v21_231_script_forbidden_provider_audit",
        "passed": bool_text(not import_present and not call_present),
        "yfinance_import_present": bool_text(import_present),
        "yfinance_call_present": bool_text(call_present),
        "yahoo_default_allowed": "False",
        "external_fallback_default_allowed": "False",
        "notes": "static audit of V21.231 execution script",
    }], import_present or call_present)


def validate_inputs(v230_dir: Path, v230r1_dir: Path) -> tuple[bool, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    required_230 = ["v21_230_summary.json","moomoo_refetch_dry_run_plan.csv","ticker_universe_resolution.csv","moomoo_frequency_plan.csv","moomoo_adjustment_plan.csv","moomoo_cache_target_plan.csv","moomoo_canonical_target_plan.csv","dram_intraday_refetch_plan.csv","abcde_daily_refetch_plan.csv","failed_or_missing_ticker_plan.csv","v21_231_execution_prerequisites.csv","dry_run_policy_gate.json"]
    required_r1 = ["v21_230_r1_summary.json","opend_connection_probe.csv","moomoo_import_probe.csv","moomoo_api_capability_probe.csv","ticker_symbol_probe.csv","permission_probe.csv","v21_231_go_no_go_gate.csv","opend_probe_policy_gate.json"]
    rows: list[dict[str, Any]] = []
    ok = True
    for path_root, names, label in [(v230_dir, required_230, "v21_230"), (v230r1_dir, required_r1, "v21_230_r1")]:
        for name in names:
            exists = (path_root / name).exists()
            ok = ok and exists
            rows.append({"check_name": f"{label}_{name}", "expected": "present", "actual": "present" if exists else "missing", "passed": bool_text(exists), "severity": "ERROR" if not exists else "INFO", "notes": str(path_root / name)})
    s230 = read_json(v230_dir / "v21_230_summary.json")
    sr1 = read_json(v230r1_dir / "v21_230_r1_summary.json")
    r1_ready = sr1.get("v21_231_ready") is True and sr1.get("final_status") == "PASS_V21_230_R1_MOOMOO_OPEND_READY_FOR_V21_231"
    ok = ok and r1_ready
    rows.append({"check_name": "v21_230_r1_ready", "expected": "True", "actual": str(sr1.get("v21_231_ready", "")), "passed": bool_text(r1_ready), "severity": "ERROR" if not r1_ready else "INFO", "notes": sr1.get("final_status", "")})
    return ok, rows, s230, sr1


def snapshot_paths(cache_root: Path, snapshot_id: str) -> dict[str, Path]:
    return {
        "raw_daily": cache_root / "raw/moomoo/daily_raw" / f"snapshot_id={snapshot_id}",
        "qfq_daily": cache_root / "raw/moomoo/daily_qfq" / f"snapshot_id={snapshot_id}",
        "intraday": cache_root / "raw/moomoo/intraday/DRAM" / f"snapshot_id={snapshot_id}",
        "canonical": cache_root / "canonical/moomoo_ohlcv" / f"snapshot_id={snapshot_id}",
        "registry": cache_root / "registry",
    }


def ensure_snapshot_available(paths: dict[str, Path], resume: bool) -> tuple[bool, str]:
    existing = [p for key, p in paths.items() if key != "registry" and p.exists()]
    if existing and not resume:
        return False, "; ".join(str(p) for p in existing)
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return True, ""


def plans(v230_dir: Path, start_date: str | None, end_date: str | None, max_items: int | None) -> list[dict[str, Any]]:
    rows = read_csv_rows(v230_dir / "moomoo_refetch_dry_run_plan.csv")
    # V21.230's old dry-run plan contains only the five DRAM/ETF probes.  It is
    # not an ABCDE ranking universe.  The durable per-ticker store is the
    # authority for the complete ABCDE universe and must be refreshed daily.
    manifest_universe = active_abcde_universe()
    full_universe = sorted(manifest_universe) or (sorted(p.name.upper() for p in ABCDE_STOCKS_ROOT.iterdir() if p.is_dir()) if ABCDE_STOCKS_ROOT.exists() else [])
    daily_templates = {(r.get("ticker", "").upper(), r.get("adjustment", "")): r for r in rows if r.get("frequency") == "1d"}
    if full_universe:
        # Do not carry the legacy ETF probe tickers into the ABCDE pool.
        rows = [r for r in rows if r.get("frequency") != "1d" or r.get("ticker", "").upper() in set(full_universe)]
        existing = {r.get("ticker", "").upper() for r in rows if r.get("frequency") == "1d"}
        template = next(iter(daily_templates.values()), {"market": "US", "asset_type": "EQUITY", "active_scope": "ABCDE_FULL_UNIVERSE", "frequency": "1d"})
        for ticker in full_universe:
            if ticker in existing:
                continue
            for adjustment in ("raw", "qfq"):
                item = dict(template)
                item.update({"ticker": ticker, "moomoo_symbol": f"US.{ticker}", "frequency": "1d", "adjustment": adjustment,
                             "market": "US", "active_scope": "ABCDE_FULL_UNIVERSE"})
                rows.append(item)
    selected = []
    for row in rows:
        freq = row.get("frequency", "")
        adj = row.get("adjustment", "")
        if freq != "1d" and row.get("ticker") != "DRAM":
            continue
        item = dict(row)
        if start_date:
            item["planned_start_date"] = start_date
        if end_date:
            item["planned_end_date"] = end_date
        selected.append(item)
        # Never let a convenience limit silently truncate the daily ABCDE
        # universe.  It is only applicable to non-daily DRAM requests.
        if max_items is not None and item["frequency"] != "1d" and len(selected) >= max_items:
            break
    return selected


def normalize_records(data: Any, ticker: str, symbol: str, market: str, adjustment: str, snapshot_id: str, fetched_at: str) -> list[dict[str, Any]]:
    if data is None:
        return []
    if pd is not None and hasattr(data, "to_dict"):
        raw_rows = data.to_dict("records")
    else:
        raw_rows = list(data) if isinstance(data, list) else []
    rows = []
    for row in raw_rows:
        date_value = row.get("date") or row.get("time_key") or row.get("time") or row.get("datetime")
        if date_value is None:
            continue
        date_text = str(date_value)[:10]
        rows.append({
            "ticker": ticker,
            "moomoo_symbol": symbol,
            "market": market,
            "date": date_text,
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
            "turnover": row.get("turnover", ""),
            "adjustment": adjustment,
            "source": "MOOMOO_OPEND",
            "source_policy": "MOOMOO_ONLY",
            "snapshot_id": snapshot_id,
            "fetched_at_utc": fetched_at,
        })
    return rows


def mock_fetch(item: dict[str, Any], snapshot_id: str) -> list[dict[str, Any]]:
    ticker = item["ticker"]
    symbol = item["moomoo_symbol"]
    market = item.get("market", "US")
    adj = item["adjustment"]
    fetched_at = utc_now()
    dates = [item.get("planned_start_date") or "2019-01-01", item.get("planned_end_date") or "2026-07-03"]
    if item.get("frequency") != "1d":
        dates = [item.get("planned_end_date") or "2026-07-03"]
    return [{
        "ticker": ticker, "moomoo_symbol": symbol, "market": market, "date": d,
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000, "turnover": 10500.0,
        "adjustment": adj, "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY", "snapshot_id": snapshot_id, "fetched_at_utc": fetched_at,
    } for d in dates]


def guarded_moomoo_fetch(item: dict[str, Any], module: Any, ctx: Any, max_retries: int, snapshot_id: str, limiter: HistoryKlineLimiter, error_rows: list[dict[str, Any]], recovered_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str, int]:
    """Fetch one leg.  The caller owns the shared OpenQuoteContext lifetime."""
    last_error = ("", "")
    for retry in range(max_retries + 1):
        try:
            ktype_map = {"1d": "K_DAY", "1m": "K_1M", "5m": "K_5M", "15m": "K_15M", "1h": "K_60M"}
            au_map = {"raw": "NONE", "qfq": "QFQ"}
            kltype = getattr(getattr(module, "KLType"), ktype_map[item["frequency"]])
            autype = getattr(getattr(module, "AuType"), au_map.get(item["adjustment"], "NONE"))
            page_key = None
            frames = []
            while True:
                limiter.acquire(item)
                ret = ctx.request_history_kline(
                    item["moomoo_symbol"],
                    start=item.get("planned_start_date") or "2019-01-01",
                    end=item.get("planned_end_date") or None,
                    ktype=kltype,
                    autype=autype,
                    page_req_key=page_key,
                )
                ok = getattr(module, "RET_OK", 0)
                if not isinstance(ret, tuple) or ret[0] != ok:
                    raise RuntimeError(str(ret[1] if isinstance(ret, tuple) and len(ret) > 1 else ret))
                frames.append(ret[1])
                page_key = ret[2] if len(ret) > 2 else None
                if not page_key:
                    break
            if pd is not None and frames:
                data = pd.concat(frames, ignore_index=True)
            else:
                data = []
                for frame in frames:
                    data.extend(frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame))
            if retry:
                recovered_rows.append({"timestamp_utc": utc_now(), "ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "adjustment": item["adjustment"], "api_call": "request_history_kline", "error_type": "RATE_LIMIT", "error_message": last_error[1], "retry_count": retry, "severity": "INFO", "notes": "recovered after rate-limit retry"})
            return normalize_records(data, item["ticker"], item["moomoo_symbol"], item.get("market", "US"), item["adjustment"], snapshot_id, utc_now()), "", "", retry
        except Exception as exc:
            last_error = (type(exc).__name__, str(exc))
            if is_rate_limit_error(last_error[1]):
                error_rows.append({"timestamp_utc": utc_now(), "ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "adjustment": item["adjustment"], "api_call": "request_history_kline", "error_type": "RATE_LIMIT", "error_message": last_error[1], "retry_count": retry, "severity": "ERROR", "notes": "retry only this failed ticker-adjustment leg"})
            if retry >= max_retries:
                return [], last_error[0], last_error[1], retry
            time.sleep((31, 61, 91)[min(retry, 2)] if is_rate_limit_error(last_error[1]) else 0.5)
    return [], last_error[0], last_error[1], max_retries


def write_records(path: Path, records: list[dict[str, Any]], resume: bool) -> tuple[bool, str, int, int, bool, bool]:
    if path.exists():
        existing_hash = sha256_file(path)
        if resume:
            return True, existing_hash, path.stat().st_size, sum(1 for _ in path.open(encoding="utf-8")) - 1, False, True
        return False, existing_hash, path.stat().st_size, 0, False, False
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ticker","moomoo_symbol","market","date","open","high","low","close","volume","turnover","adjustment","source","source_policy","snapshot_id","fetched_at_utc"]
    write_csv(path, records, fields)
    return True, sha256_file(path), path.stat().st_size, len(records), True, False


def cache_file_for(paths: dict[str, Path], item: dict[str, Any]) -> Path:
    safe = item["ticker"].replace("/", "_")
    if item["frequency"] == "1d" and item["adjustment"] == "raw":
        return paths["raw_daily"] / f"{safe}.csv"
    if item["frequency"] == "1d" and item["adjustment"] == "qfq":
        return paths["qfq_daily"] / f"{safe}.csv"
    return paths["intraday"] / item["frequency"] / f"{safe}.csv"


def newest_prior_snapshot(cache_root: Path, current_snapshot: str) -> str | None:
    root = cache_root / "raw/moomoo/daily_raw"
    candidates = sorted((p.name.removeprefix("snapshot_id=") for p in root.glob("snapshot_id=*") if p.is_dir() and p.name != f"snapshot_id={current_snapshot}"), reverse=True)
    return candidates[0] if candidates else None


def reusable_prior_file(cache_root: Path, prior_snapshot: str | None, item: dict[str, Any], intraday_snapshot_id: str | None = None) -> Path | None:
    if not prior_snapshot:
        return None
    if item.get("frequency") != "1d":
        root = cache_root / "raw/moomoo/intraday" / item["ticker"].replace('/', '_')
        # A failed most-recent daily snapshot may have created an empty
        # intraday directory.  Walk older immutable snapshots before making
        # an SDK call; a cached successful bar file remains authoritative.
        snapshot_ids = ([intraday_snapshot_id] if intraday_snapshot_id else []) + [prior_snapshot] + [p.name.removeprefix("snapshot_id=") for p in sorted(root.glob("snapshot_id=*"), reverse=True)]
        for candidate_id in dict.fromkeys(snapshot_ids):
            candidate = root / f"snapshot_id={candidate_id}" / item["frequency"] / f"{item['ticker'].replace('/', '_')}.csv"
            if candidate.exists() and read_csv_rows(candidate, limit=1):
                return candidate
        return None
    kind = "daily_raw" if item["adjustment"] == "raw" else "daily_qfq"
    candidate = cache_root / "raw/moomoo" / kind / f"snapshot_id={prior_snapshot}" / f"{item['ticker'].replace('/', '_')}.csv"
    return candidate if candidate.exists() and read_csv_rows(candidate, limit=1) else None


INTRADAY_REQUIRED_COLUMNS = ["ticker", "moomoo_symbol", "market", "date", "open", "high", "low", "close", "volume", "turnover", "adjustment", "source", "source_policy", "snapshot_id", "fetched_at_utc"]


def expected_intraday_legs(plan_path: Path) -> list[dict[str, str]]:
    """Use the V21.231 source plan, never a guessed list of frequencies."""
    rows = [r for r in read_csv_rows(plan_path) if r.get("frequency") and r.get("frequency") != "1d"]
    return sorted(rows, key=lambda r: (r.get("ticker", ""), r.get("frequency", ""), r.get("adjustment", "")))


def intraday_leg_key(leg: dict[str, Any]) -> str:
    return "|".join(str(leg.get(k, "")) for k in ("ticker", "frequency", "adjustment"))


def reconstruct_intraday_manifest(cache_root: Path, plan_path: Path, snapshot_id: str, required_latest_date: str) -> dict[str, Any]:
    """Build a manifest only from stable, existing immutable cache files."""
    snapshot_dir = cache_root / "raw/moomoo/intraday/DRAM" / f"snapshot_id={snapshot_id}"
    legs = expected_intraday_legs(plan_path)
    expected_keys = [intraday_leg_key(leg) for leg in legs]
    duplicate_expected = len(expected_keys) != len(set(expected_keys))
    entries: list[dict[str, Any]] = []
    changed: list[str] = []
    for leg in legs:
        ticker, frequency, adjustment = leg["ticker"], leg["frequency"], leg["adjustment"]
        path = snapshot_dir / frequency / f"{ticker.replace('/', '_')}.csv"
        before = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
        actual_columns: list[str] = []; rows: list[dict[str, str]] = []; parse_passed = False
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle); actual_columns = reader.fieldnames or []; rows = [{k: (v or "") for k, v in r.items() if k is not None} for r in reader]
            parse_passed = True
        except (OSError, UnicodeDecodeError, csv.Error):
            pass
        after = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
        digest = sha256_file(path) if path.exists() and after and after[0] else ""
        final_state = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
        if before != after or after != final_state:
            changed.append(intraday_leg_key(leg))
        dates = [str(row.get("date", ""))[:10] for row in rows if row.get("date")]
        file_exists, nonempty = path.exists(), bool(rows) and bool(after and after[0])
        schema_passed = all(column in actual_columns for column in INTRADAY_REQUIRED_COLUMNS)
        ticker_match = bool(rows) and all(row.get("ticker") == ticker and row.get("moomoo_symbol") == leg.get("moomoo_symbol", f"US.{ticker}") for row in rows)
        # Frequency is encoded by the immutable path because the source CSV
        # schema has no frequency column.
        frequency_match = path.parent.name == frequency
        adjustment_match = bool(rows) and all(row.get("adjustment") == adjustment for row in rows)
        latest_date = max(dates) if dates else ""; first_date = min(dates) if dates else ""
        valid = file_exists and nonempty and parse_passed and schema_passed and ticker_match and frequency_match and adjustment_match and latest_date >= required_latest_date and intraday_leg_key(leg) not in changed
        entries.append({"ticker": ticker, "moomoo_symbol": leg.get("moomoo_symbol", f"US.{ticker}"), "frequency": frequency, "adjustment": adjustment,
                        "relative_path": str(path.relative_to(snapshot_dir)) if path.is_relative_to(snapshot_dir) else "", "absolute_path": str(path), "file_exists": file_exists,
                        "size_bytes": final_state[0] if final_state else 0, "sha256": digest, "row_count": len(rows),
                        "first_timestamp": first_date, "latest_timestamp": latest_date, "first_date": first_date, "latest_date": latest_date,
                        "required_columns": INTRADAY_REQUIRED_COLUMNS, "actual_columns": actual_columns, "parse_passed": parse_passed, "schema_passed": schema_passed,
                        "ticker_match": ticker_match, "frequency_match": frequency_match, "adjustment_match": adjustment_match, "nonempty": nonempty, "valid": valid})
    invalid = [intraday_leg_key(entry) for entry in entries if not entry["valid"]]
    missing = [intraday_leg_key(entry) for entry in entries if not entry["file_exists"]]
    aggregate = hashlib.sha256("".join(f"{intraday_leg_key(entry)}|{entry['sha256']}\n" for entry in sorted(entries, key=intraday_leg_key)).encode("utf-8")).hexdigest()
    payload = {"snapshot_id": snapshot_id, "snapshot_directory": str(snapshot_dir), "manifest_type": "RECONSTRUCTED_FROM_EXISTING_IMMUTABLE_FILES", "reconstructed": True,
               "reconstructed_at_utc": utc_now(), "reconstruction_reason": "MISSING_ORIGINAL_INTRADAY_MANIFEST", "expected_leg_count": len(legs), "valid_leg_count": len(entries) - len(invalid), "invalid_leg_count": len(invalid),
               "expected_legs": expected_keys, "missing_legs": missing, "invalid_legs": invalid, "aggregate_sha256": aggregate, "source_policy": "MOOMOO_ONLY", "sdk_call_used": False, "yahoo_used": False, "yfinance_used": False,
               "broker_action_allowed": False, "official_adoption_allowed": False, "required_latest_date": required_latest_date, "legs": entries, "duplicate_or_conflicting_expected_legs": duplicate_expected, "files_changed_during_validation": changed}
    if len(legs) == 4 and not duplicate_expected and not invalid and not changed:
        write_json(snapshot_dir / "intraday_manifest.json", payload)
        payload["written"] = True
    else:
        write_json(snapshot_dir / "reconstruction_failure_report.json", payload)
        payload["written"] = False
    return payload


def valid_intraday_manifest(path: Path, expected: list[dict[str, str]], required_latest_date: str) -> dict[str, Any] | None:
    manifest = read_json(path)
    if not manifest or manifest.get("expected_leg_count") != len(expected) or manifest.get("valid_leg_count") != len(expected) or manifest.get("invalid_leg_count") != 0:
        return None
    if manifest.get("reconstructed") is True and not manifest.get("aggregate_sha256"):
        return None
    entries = manifest.get("legs", [])
    if {intraday_leg_key(e) for e in entries} != {intraday_leg_key(e) for e in expected}:
        return None
    # Re-hash every file so a reconstructed manifest cannot become stale.
    for entry in entries:
        p = Path(entry.get("absolute_path", ""))
        if not entry.get("valid") or not p.exists() or p.stat().st_size != entry.get("size_bytes") or sha256_file(p) != entry.get("sha256") or str(entry.get("latest_date", "")) < required_latest_date:
            return None
    if manifest.get("reconstructed") is True:
        aggregate = hashlib.sha256("".join(f"{intraday_leg_key(e)}|{e.get('sha256','')}\n" for e in sorted(entries, key=intraday_leg_key)).encode("utf-8")).hexdigest()
        if aggregate != manifest.get("aggregate_sha256"):
            return None
    return manifest


def select_valid_intraday_snapshot(cache_root: Path, plan_path: Path, required_latest_date: str) -> dict[str, Any] | None:
    expected = expected_intraday_legs(plan_path); root = cache_root / "raw/moomoo/intraday/DRAM"
    for directory in sorted(root.glob("snapshot_id=*"), reverse=True):
        manifest = valid_intraday_manifest(directory / "intraday_manifest.json", expected, required_latest_date)
        if manifest:
            return manifest
    return None


def date_stats(records: list[dict[str, Any]]) -> tuple[str, str]:
    vals = sorted({str(r.get("date", "")) for r in records if r.get("date")})
    return (vals[0], vals[-1]) if vals else ("", "")


def build_canonical(paths: dict[str, Path], snapshot_id: str, adjustment: str, source_files: list[Path], resume: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for path in source_files:
        rows.extend(read_csv_rows(path))
    out = paths["canonical"] / f"canonical_moomoo_ohlcv_daily_{adjustment}.csv"
    ok, digest, size, row_count, written, already = write_records(out, rows, resume)
    first, latest = date_stats(rows)
    manifest = {
        "canonical_artifact": f"canonical_moomoo_ohlcv_daily_{adjustment}",
        "path": str(out), "adjustment": adjustment, "row_count": row_count if row_count else len(rows),
        "ticker_count": len({r.get("ticker") for r in rows if r.get("ticker")}),
        "first_date": first, "latest_date": latest, "sha256": digest,
        "source_policy": "MOOMOO_ONLY", "yfinance_used": "False", "external_fallback_used": "False",
        "notes": "new immutable canonical snapshot" if ok else "write blocked",
    }
    write_rows = [{"source_path_or_api": "canonical_builder", "cache_path": str(out), "file_exists": bool_text(out.exists()), "size_bytes": size, "sha256": digest, "written_now": bool_text(written), "already_present_verified": bool_text(already), "verified": bool_text(ok), "notes": "canonical output"}]
    return manifest, write_rows


def quality_audit(raw_rows: list[dict[str, Any]], qfq_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for scope, rows in [("raw", raw_rows), ("qfq", qfq_rows)]:
        bad = 0
        dupes = 0
        seen = set()
        for r in rows:
            key = (r.get("ticker"), r.get("date"), r.get("adjustment"))
            if key in seen:
                dupes += 1
            seen.add(key)
            try:
                o, h, l, c = [float(r.get(k)) for k in ["open", "high", "low", "close"]]
                v = float(r.get("volume"))
                if min(o, h, l, c) < 0 or h < max(o, l, c) or l > min(o, h, c) or v < 0:
                    bad += 1
                datetime.fromisoformat(str(r.get("date")))
            except Exception:
                bad += 1
        checks.append({"check_name": "ohlcv_sanity", "scope": scope, "passed": bool_text(bad == 0), "severity": "ERROR" if bad else "INFO", "affected_rows": bad, "affected_tickers": "", "notes": "price/date/volume validation"})
        checks.append({"check_name": "duplicate_ticker_date_adjustment", "scope": scope, "passed": bool_text(dupes == 0), "severity": "ERROR" if dupes else "INFO", "affected_rows": dupes, "affected_tickers": "", "notes": "canonical key uniqueness"})
    return checks


def append_registry(path: Path, row: dict[str, Any], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def run(
    repo_root: Path,
    output_dir: Path,
    v21_230_output_dir: Path | None = None,
    v21_230_r1_output_dir: Path | None = None,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    snapshot_id: str | None = None,
    resume_snapshot_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    batch_size: int = 10,
    sleep_seconds: float = 0.25,
    max_retries: int = 2,
    max_fetch_items: int | None = None,
    min_daily_success_ratio: float = 0.95,
    require_dram_intraday: bool = True,
    allow_dram_missing: bool = False,
    no_network: bool = False,
    opend_host: str = "127.0.0.1",
    opend_port: int = 18441,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    production = repo_root == default_repo_root().resolve()
    v230_dir = (v21_230_output_dir or (resolve_prerequisite(PREREQ_V230, repo_root) if production else None) or (repo_root / V230_REL)).resolve()
    v230r1_dir = (v21_230_r1_output_dir or (resolve_prerequisite(PREREQ_R1, repo_root) if production else None) or (repo_root / V230R1_REL)).resolve()
    input_ok, cross_rows, s230, sr1 = validate_inputs(v230_dir, v230r1_dir)
    guard_found = (repo_root / "scripts/v21/v21_data_source_policy_guard.py").exists()
    policy_ok = False
    error_count = 0
    warning_count = 0
    try:
        guard = load_policy_guard(repo_root)
        guard.assert_moomoo_only_policy("V21.231 canonical dram abcde execution")
        policy = guard.load_data_source_policy(repo_root / "config/v21/data_source_policy.json")
        policy_ok = policy.get("default_data_source_policy") == "MOOMOO_ONLY" and policy.get("research_only") is True and all(policy.get(k) is False for k in ["yfinance_allowed_by_default","yahoo_allowed_by_default","external_fallback_allowed_for_canonical","external_fallback_allowed_for_dram","external_fallback_allowed_for_abcde","broker_action_allowed","official_adoption_allowed"])
    except Exception as exc:
        cross_rows.append({"check_name": "policy_guard", "expected": "pass", "actual": f"{type(exc).__name__}: {exc}", "passed": "False", "severity": "ERROR", "notes": "central guard must pass"})
    else:
        cross_rows.append({"check_name": "policy_guard", "expected": "pass", "actual": "pass", "passed": bool_text(policy_ok), "severity": "INFO" if policy_ok else "ERROR", "notes": "central guard imported and used"})
    audit_rows, forbidden_violation = self_forbidden_audit(repo_root)
    # Readiness is a strict precondition: do not create a snapshot directory,
    # pointer, registry, or empty CSV bundle until every guard has passed.
    if not input_ok or not policy_ok or forbidden_violation:
        status = FAIL_INPUT if not input_ok else FAIL_SOURCE
        empty_paths = {"canonical": cache_root / "canonical/moomoo_ohlcv", "raw_daily": cache_root / "raw/moomoo/daily_raw", "qfq_daily": cache_root / "raw/moomoo/daily_qfq", "intraday": cache_root / "raw/moomoo/intraday/DRAM", "registry": cache_root / "registry"}
        summary = base_summary(
            status, repo_root, output_dir, cache_root, "",
            input_ok, sr1.get("v21_231_ready") is True, guard_found, policy_ok, empty_paths, s230,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            0.0, 0.0, 0.0,
            0, 0, 0, 0, "",
            0, 0, 0, 0, 0, 0,
            error_count + 1, warning_count,
        )
        summary["final_decision"] = BLOCKED_DECISION
        write_json(output_dir / "v21_231_summary.json", summary)
        write_json(output_dir / "v21_231_failure_diagnostic.json", {"final_status": status, "final_decision": BLOCKED_DECISION, "readiness_checks": cross_rows})
        return summary

    snapshot = resume_snapshot_id or snapshot_id or make_snapshot_id()
    resume = resume_snapshot_id is not None
    paths = snapshot_paths(cache_root, snapshot)
    snapshot_ok, snapshot_error = ensure_snapshot_available(paths, resume)
    write_json(output_dir / "source_policy_gate.json", source_policy_gate())
    if not snapshot_ok:
        summary = base_summary(FAIL_SNAPSHOT, repo_root, output_dir, cache_root, snapshot, input_ok, True, guard_found, policy_ok, paths, s230, 0,0,0,0,0,0,0,0,0,0,0,0,0,0.0,0.0,0.0,0,0,0,0,"",0,0,0,0,0,0,1,0)
        summary["final_decision"] = "MOOMOO_ONLY_CANONICAL_BLOCKED_SNAPSHOT_CONFLICT"
        write_json(output_dir / "v21_231_summary.json", summary)
        return summary

    items = plans(v230_dir, start_date, end_date, max_fetch_items)
    # A dry-run plan is authoritative for its target session.  Do not compare
    # a deterministic fixture (or a delayed market session) with an empty
    # target date merely because the caller omitted --end-date.
    if not end_date:
        end_date = max((str(item.get("planned_end_date", ""))[:10] for item in items), default="") or datetime.now(timezone.utc).date().isoformat()
    # Persist the planned full ABCDE universe separately from the fetch result.
    # The coverage ledger is evidence of what happened, not authority to shrink
    # the universe after a partial fetch.
    expected_abcde = sorted({r.get("ticker", "") for r in items if r.get("frequency") == "1d" and r.get("ticker")})
    write_csv(output_dir / "abcde_expected_universe.csv",
              [{"ticker": ticker, "moomoo_symbol": f"US.{ticker}", "source": "V21.231_FULL_DAILY_PLAN"} for ticker in expected_abcde],
              ["ticker", "moomoo_symbol", "source"])
    fetch_rows: list[dict[str, Any]] = []
    raw_manifest: list[dict[str, Any]] = []
    qfq_manifest: list[dict[str, Any]] = []
    intra_manifest: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    write_rows: list[dict[str, Any]] = []
    rate_rows: list[dict[str, Any]] = []
    raw_files: list[Path] = []
    qfq_files: list[Path] = []
    raw_rows_all: list[dict[str, Any]] = []
    qfq_rows_all: list[dict[str, Any]] = []
    recovered_error_rows: list[dict[str, Any]] = []
    reconnect_rows: list[dict[str, Any]] = []
    # The ledger is durable audit evidence.  Keep it across refreshes; it is
    # evaluated against the requested as-of date below, never used to erase
    # historical bars or universe manifests.
    exclusion_rows = read_csv_rows(output_dir / "abcde_daily_exclusion_ledger.csv")
    prior_snapshot = newest_prior_snapshot(cache_root, snapshot) if not resume else None
    intraday_required_date = str(end_date or "")[:10]
    intraday_preflight = select_valid_intraday_snapshot(cache_root, v230_dir / "moomoo_refetch_dry_run_plan.csv", intraday_required_date) if intraday_required_date else None
    intraday_cache_snapshot_id = str(intraday_preflight.get("snapshot_id", "")) if intraday_preflight else None
    limiter = HistoryKlineLimiter()
    module = None
    ctx = None
    if not no_network:
        for name in SDK_NAMES:
            try:
                module = importlib.import_module(name); break
            except Exception:
                continue
        if module is None:
            reconnect_rows.append({"timestamp_utc": utc_now(), "event": "OPEN_FAILED", "detail": "Moomoo/Futu SDK import failed; only unreusable legs will be marked failed"})
        else:
            ctx = getattr(module, "OpenQuoteContext")(host=opend_host, port=int(opend_port))
            reconnect_rows.append({"timestamp_utc": utc_now(), "event": "OPEN", "detail": "shared OpenQuoteContext created for daily refresh"})
    try:
      for batch_index in range(0, len(items), max(1, batch_size)):
        batch = items[batch_index:batch_index + max(1, batch_size)]
        started = utc_now()
        t0 = time.perf_counter()
        for item in batch:
            target = cache_file_for(paths, item)
            prior_file = reusable_prior_file(cache_root, prior_snapshot, item, intraday_cache_snapshot_id)
            # A prior immutable file is reusable only when it reaches this
            # run's target session.  Reusing a stale ETF/support ticker masks
            # a required refresh and creates a false coverage failure.
            if prior_file is not None and item.get("planned_end_date"):
                prior_latest = date_stats(read_csv_rows(prior_file))[1]
                if prior_latest < str(item["planned_end_date"])[:10]:
                    prior_file = None
            attempted = prior_file is None
            fetch_status = "FETCHED"
            if prior_file is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(prior_file, target)
                records, err_type, err_msg, retry_count = read_csv_rows(target), "", "", 0
                fetch_status = "REUSED_FROM_PRIOR_SNAPSHOT"
            elif no_network:
                records, err_type, err_msg, retry_count = mock_fetch(item, snapshot), "", "", 0
            elif module is None or ctx is None:
                records, err_type, err_msg, retry_count = [], "MoomooSdkUnavailable", "Moomoo/Futu SDK import failed", 0
            else:
                records, err_type, err_msg, retry_count = guarded_moomoo_fetch(item, module, ctx, min(3, max_retries), snapshot, limiter, error_rows, recovered_error_rows)
                if retry_count and records:
                    fetch_status = "RETRIED_RECOVERED"
            success = bool(records)
            digest = ""
            size = 0
            row_count = 0
            written = False
            already = False
            if success:
                ok, digest, size, row_count, written, already = write_records(target, records, resume or prior_file is not None)
                success = ok
                write_rows.append({"source_path_or_api": "MOOMOO_OPEND" if not no_network else "MOCK_NO_NETWORK", "cache_path": str(target), "file_exists": bool_text(target.exists()), "size_bytes": size, "sha256": digest, "written_now": bool_text(written), "already_present_verified": bool_text(already), "verified": bool_text(ok), "notes": "raw fetched cache file"})
                if item["frequency"] == "1d" and item["adjustment"] == "raw":
                    raw_files.append(target); raw_rows_all.extend(records)
                if item["frequency"] == "1d" and item["adjustment"] == "qfq":
                    qfq_files.append(target); qfq_rows_all.extend(records)
            first, latest = date_stats(records)
            base = {"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "market": item.get("market", "US"), "asset_type": item.get("asset_type", ""), "active_scope": item.get("active_scope", ""), "frequency": item["frequency"], "adjustment": item["adjustment"], "planned_start_date": item.get("planned_start_date", ""), "planned_end_date": item.get("planned_end_date", ""), "attempted": bool_text(attempted), "success": bool_text(success), "fetch_status": fetch_status if success else "FAILED", "row_count": row_count, "latest_bar_date": latest, "cache_path": str(target), "sha256": digest, "error_type": err_type, "error_message": err_msg, "retry_count": retry_count, "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY", "notes": "Moomoo-only fetch"}
            fetch_rows.append(base)
            if item["frequency"] == "1d":
                manifest = {"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "market": item.get("market", "US"), "attempted": "True", "success": bool_text(success), "row_count": row_count, "first_date": first, "latest_date": latest, "cache_path": str(target), "sha256": digest, "error_type": err_type, "notes": "daily fetch"}
                (raw_manifest if item["adjustment"] == "raw" else qfq_manifest).append(manifest)
            else:
                intra_manifest.append({"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "attempted": "True", "success": bool_text(success), "row_count": row_count, "first_timestamp": first, "latest_timestamp": latest, "cache_path": str(target), "sha256": digest, "error_type": err_type, "notes": "DRAM intraday fetch"})
            if not success:
                failed_rows.append({"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "adjustment": item["adjustment"], "error_type": err_type or "EmptyData", "error_message": err_msg, "retry_count": retry_count, "retry_allowed": "True", "yahoo_fallback_allowed": "False", "external_fallback_allowed": "False", "required_user_review": "True", "notes": "no fallback allowed"})
                error_rows.append({"timestamp_utc": utc_now(), "ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "adjustment": item["adjustment"], "api_call": "request_history_kline", "error_type": err_type or "EmptyData", "error_message": err_msg, "retry_count": retry_count, "severity": "ERROR", "notes": "Moomoo API failure or empty response"})
      rate_rows.extend(limiter.audit_rows)
    finally:
      if ctx is not None and hasattr(ctx, "close"):
        try:
          ctx.close(); reconnect_rows.append({"timestamp_utc": utc_now(), "event": "CLOSE", "detail": "shared OpenQuoteContext closed in finally"})
        except Exception as exc:
          reconnect_rows.append({"timestamp_utc": utc_now(), "event": "CLOSE_FAILED", "detail": str(exc)})

    raw_canon, raw_write = build_canonical(paths, snapshot, "raw", raw_files, resume)
    qfq_canon, qfq_write = build_canonical(paths, snapshot, "qfq", qfq_files, resume)
    write_rows.extend(raw_write + qfq_write)
    canonical_manifest = [raw_canon, qfq_canon]
    quality_rows = quality_audit(raw_rows_all, qfq_rows_all)
    quality_errors = sum(1 for r in quality_rows if r["severity"] == "ERROR")
    quality_warnings = sum(1 for r in quality_rows if r["severity"] == "WARN")
    target_date = str(end_date or "")[:10]
    coverage_rows = coverage(raw_manifest, qfq_manifest, intra_manifest, target_date, exclusion_rows)
    coverage_warnings = sum(1 for r in coverage_rows if r["coverage_status"] not in {"OK_TARGET_DATE", "LEGALLY_EXCLUDED"})
    daily_raw_attempted = len(raw_manifest); daily_qfq_attempted = len(qfq_manifest); intra_attempted = len(intra_manifest)
    daily_raw_success = sum(1 for r in raw_manifest if r["success"] == "True")
    daily_qfq_success = sum(1 for r in qfq_manifest if r["success"] == "True")
    intra_success = sum(1 for r in intra_manifest if r["success"] == "True")
    raw_ratio = daily_raw_success / daily_raw_attempted if daily_raw_attempted else 0.0
    qfq_ratio = daily_qfq_success / daily_qfq_attempted if daily_qfq_attempted else 0.0
    intra_ratio = intra_success / intra_attempted if intra_attempted else 1.0
    if quality_errors:
        status = FAIL_QUALITY
    elif raw_ratio < min_daily_success_ratio or qfq_ratio < min_daily_success_ratio:
        status = FAIL_DAILY
    elif require_dram_intraday and not allow_dram_missing and intra_attempted and intra_success < intra_attempted:
        status = FAIL_DRAM
    elif failed_rows or coverage_warnings:
        status = WARN_STATUS
    else:
        status = PASS_STATUS
    error_count += 1 if status.startswith("FAIL_") else 0
    warning_count += len(failed_rows) if status == WARN_STATUS else 0
    universe_cov = complete_universe_coverage(raw_canon["path"], qfq_canon["path"], set(expected_abcde), target_date, exclusion_rows)
    if end_date and universe_cov["stale_ticker_count"]:
        status = FAIL_DAILY
        error_count = max(error_count, 1)
    pointer = pointer_payload(cache_root, paths, snapshot, raw_canon["path"], qfq_canon["path"])
    pointer.update(universe_cov)
    write_json(paths["canonical"] / "canonical_manifest.json", {"snapshot": pointer, "canonical_manifest": canonical_manifest})
    write_csv(paths["canonical"] / "canonical_quality_audit.csv", quality_rows, QUALITY_FIELDS)
    pointer["canonical_manifest_path"] = str(paths["canonical"] / "canonical_manifest.json")
    write_json(output_dir / "canonical_snapshot_pointer.json", pointer)
    write_csv(output_dir / "canonical_snapshot_pointer.csv", [{"key": k, "value": v} for k, v in pointer.items()], POINTER_CSV_FIELDS)
    append_registry(paths["registry"] / "moomoo_fetch_registry.csv", {"snapshot_id": snapshot, "created_at_utc": utc_now(), "fetch_items": len(fetch_rows), "success": sum(1 for r in fetch_rows if r["success"] == "True")}, ["snapshot_id","created_at_utc","fetch_items","success"])
    append_registry(paths["registry"] / "canonical_snapshot_registry.csv", {"snapshot_id": snapshot, "created_at_utc": utc_now(), "canonical_raw_path": raw_canon["path"], "canonical_qfq_path": qfq_canon["path"]}, ["snapshot_id","created_at_utc","canonical_raw_path","canonical_qfq_path"])
    summary = base_summary(status, repo_root, output_dir, cache_root, snapshot, True, True, guard_found, policy_ok, paths, s230, len(items), len(fetch_rows), sum(1 for r in fetch_rows if r["success"] == "True"), len(failed_rows), daily_raw_attempted, daily_raw_success, daily_raw_attempted - daily_raw_success, daily_qfq_attempted, daily_qfq_success, daily_qfq_attempted - daily_qfq_success, intra_attempted, intra_success, intra_attempted - intra_success, raw_ratio, qfq_ratio, intra_ratio, raw_canon["row_count"], qfq_canon["row_count"], raw_canon["ticker_count"], qfq_canon["ticker_count"], universe_cov["canonical_complete_universe_date"], sum(1 for r in write_rows if r["written_now"] == "True"), sum(int(r["size_bytes"]) for r in write_rows if str(r["size_bytes"]).isdigit()), sum(1 for r in write_rows if r["verified"] == "True"), quality_errors, quality_warnings, coverage_warnings, error_count, warning_count)
    summary.update(universe_cov)
    summary.update({
        "failed_stage": "COVERAGE_EVALUATION" if status.startswith("FAIL") else "",
        "failure_category": "GENUINE_TARGET_DATE_TICKER_GAPS" if status == FAIL_DAILY and universe_cov["stale_ticker_count"] else "",
        "failure_reason": "target-date data missing for: " + ",".join(universe_cov["missing_target_date_tickers"]) if universe_cov["stale_ticker_count"] else "",
        "universe_resolution_completed": True,
        "fetch_execution_completed": True,
        "canonical_assembly_completed": True,
        "coverage_evaluation_completed": True,
    })
    summary["ticker_universe_count"] = universe_cov["expected_universe_count"]
    summary["legacy_probe_ticker_count"] = int(s230.get("ticker_universe_count", 0) or 0)
    api_legs = {(r["ticker"], r["adjustment"], r["frequency"]) for r in error_rows}
    recovered_legs = {(r["ticker"], r["adjustment"], r["frequency"]) for r in recovered_error_rows}
    summary["api_error_count"] = len(api_legs)
    summary["recovered_api_error_count"] = len(recovered_legs)
    summary["unresolved_api_error_count"] = len(api_legs - recovered_legs)
    summary["intraday_cache_source_snapshot_id"] = intraday_cache_snapshot_id or ""
    summary["intraday_cache_reused_count"] = sum(1 for r in fetch_rows if r.get("frequency") != "1d" and r.get("fetch_status") == "REUSED_FROM_PRIOR_SNAPSHOT")
    summary["intraday_sdk_call_count"] = sum(1 for r in fetch_rows if r.get("frequency") != "1d" and r.get("attempted") == "True")
    summary["stale_ticker_count_after_exclusion"] = universe_cov["stale_ticker_count"]
    promotable = (universe_cov["expected_universe_count"] == len(active_abcde_universe()) and universe_cov["target_date_ticker_count"] == universe_cov["eligible_universe_count"] and universe_cov["stale_ticker_count"] == 0 and summary["unresolved_api_error_count"] == 0 and universe_cov["raw_qfq_target_date_ticker_set_exact_match"] and universe_cov["canonical_complete_universe_date"] == target_date)
    if not promotable and status in {PASS_STATUS, WARN_STATUS}:
        summary["final_status"] = FAIL_DAILY
        summary["final_decision"] = "MOOMOO_ONLY_CANONICAL_BLOCKED_DAILY_COVERAGE_BELOW_THRESHOLD"
    write_outputs(output_dir, summary, fetch_rows, raw_manifest, qfq_manifest, intra_manifest, canonical_manifest, quality_rows, coverage_rows, failed_rows, error_rows, rate_rows, cross_rows, audit_rows, pointer, write_rows, exclusion_rows, recovered_error_rows, reconnect_rows)
    return summary


def coverage(raw_manifest: list[dict[str, Any]], qfq_manifest: list[dict[str, Any]], intra_manifest: list[dict[str, Any]], target_date: str, exclusions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tickers = sorted({r["ticker"] for r in raw_manifest + qfq_manifest + intra_manifest})
    rows = []
    for t in tickers:
        raw = next((r for r in raw_manifest if r["ticker"] == t), {})
        qfq = next((r for r in qfq_manifest if r["ticker"] == t), {})
        intra = [r for r in intra_manifest if r["ticker"] == t]
        intra_ok = all(r["success"] == "True" for r in intra) if intra else True
        raw_ok, qfq_ok = raw.get("success") == "True", qfq.get("success") == "True"
        raw_latest, qfq_latest = raw.get("latest_date", ""), qfq.get("latest_date", "")
        excluded = t in effective_exclusion_tickers(exclusions, target_date)
        if excluded: status, reason = "LEGALLY_EXCLUDED", "documented Moomoo/OpenD evidence"
        elif not raw_ok or not qfq_ok: status, reason = "API_FAILED", "one or more planned fetches failed"
        elif raw_latest < target_date or qfq_latest < target_date: status, reason = "STALE_TARGET_DATE", "API succeeded but latest date is earlier than target"
        elif raw_latest != qfq_latest: status, reason = "RAW_QFQ_MISMATCH", "raw/qfq latest-date mismatch"
        else: status, reason = "OK_TARGET_DATE", ""
        rows.append({"ticker": t, "moomoo_symbol": raw.get("moomoo_symbol") or qfq.get("moomoo_symbol") or (intra[0]["moomoo_symbol"] if intra else ""), "daily_raw_success": raw.get("success", "False"), "daily_qfq_success": qfq.get("success", "False"), "intraday_success": bool_text(intra_ok), "raw_latest_date": raw_latest, "qfq_latest_date": qfq_latest, "coverage_status": status, "missing_reason": reason, "notes": "Moomoo-only coverage"})
    return rows


def effective_exclusion_tickers(rows: list[dict[str, Any]], target_date: str) -> set[str]:
    """Return only explicitly approved exclusions effective on target_date."""
    approved = set()
    for row in rows:
        ticker = row.get("ticker", "")
        allowed = str(row.get("allowed", "")).lower() == "true" or str(row.get("status", "")).upper() in {"APPROVED", "VALID", "ACTIVE"}
        effective = str(row.get("effective_date") or row.get("target_date") or "")[:10]
        if ticker and allowed and (not effective or effective <= target_date):
            approved.add(ticker)
    return approved


def complete_universe_coverage(raw_path: str, qfq_path: str, expected: set[str], target_date: str, exclusions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Calculate canonical dates from complete ticker coverage, never table max."""
    raw_by_date: dict[str, set[str]] = {}; qfq_by_date: dict[str, set[str]] = {}
    for row in read_csv_rows(Path(raw_path)):
        if row.get("ticker") and row.get("date"):
            raw_by_date.setdefault(str(row["date"])[:10], set()).add(row["ticker"])
    for row in read_csv_rows(Path(qfq_path)):
        if row.get("ticker") and row.get("date"):
            qfq_by_date.setdefault(str(row["date"])[:10], set()).add(row["ticker"])
    # A retained delisting ledger is historical audit evidence.  It only
    # affects a current coverage denominator when that ticker is still a
    # member of the current active authority.
    excluded = effective_exclusion_tickers(exclusions or [], target_date) & expected; eligible = expected - excluded
    complete = next((d for d in sorted(set(raw_by_date) & set(qfq_by_date), reverse=True)
                     if eligible <= raw_by_date[d] and eligible <= qfq_by_date[d]), "")
    raw_target, qfq_target = raw_by_date.get(target_date, set()), qfq_by_date.get(target_date, set())
    missing = sorted(((eligible - raw_target) | (eligible - qfq_target)))
    return {"canonical_complete_universe_date": complete, "expected_universe_count": len(expected),
            "eligible_universe_count": len(eligible), "target_date_ticker_count": len(eligible & raw_target & qfq_target), "legally_excluded_count": len(excluded),
            "gross_target_date_coverage_ratio": len(eligible & raw_target & qfq_target) / len(expected) if expected else 0.0,
            "eligible_target_date_coverage_ratio": len(eligible & raw_target & qfq_target) / len(eligible) if eligible else 0.0,
            "target_date_coverage_ratio": len(eligible & raw_target & qfq_target) / len(eligible) if eligible else 0.0,
            "stale_ticker_count": len(missing), "missing_target_date_tickers": missing,
            "raw_qfq_target_date_ticker_set_exact_match": raw_target == qfq_target}


def pointer_payload(cache_root: Path, paths: dict[str, Path], snapshot: str, raw_path: str, qfq_path: str) -> dict[str, Any]:
    return {"policy_version": "V21.231", "snapshot_id": snapshot, "created_at_utc": utc_now(), "cache_root": str(cache_root), "raw_daily_snapshot_dir": str(paths["raw_daily"]), "qfq_daily_snapshot_dir": str(paths["qfq_daily"]), "intraday_snapshot_dir": str(paths["intraday"]), "canonical_snapshot_dir": str(paths["canonical"]), "canonical_raw_path": raw_path, "canonical_qfq_path": qfq_path, "canonical_manifest_path": str(paths["canonical"] / "canonical_manifest.json"), "source_policy": "MOOMOO_ONLY", "source": "MOOMOO_OPEND", "yfinance_used": False, "yahoo_used": False, "external_fallback_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True}


def base_summary(status: str, repo_root: Path, output_dir: Path, cache_root: Path, snapshot: str, v230_ok: bool, r1_ok: bool, guard_found: bool, policy_ok: bool, paths: dict[str, Path], s230: dict[str, Any], planned: int, attempted: int, success: int, failed: int, raw_att: int, raw_succ: int, raw_fail: int, qfq_att: int, qfq_succ: int, qfq_fail: int, intra_att: int, intra_succ: int, intra_fail: int, raw_ratio: float, qfq_ratio: float, intra_ratio: float, canon_raw_rows: int, canon_qfq_rows: int, canon_raw_tickers: int, canon_qfq_tickers: int, latest: str, written_count: int, written_bytes: int, hash_count: int, q_errors: int, q_warnings: int, cov_warnings: int, error_count: int, warning_count: int) -> dict[str, Any]:
    return {"final_status": status, "final_decision": FINAL_DECISION, "repo_root": str(repo_root), "output_dir": str(output_dir), "cache_root": str(cache_root), "snapshot_id": snapshot, "v21_230_input_found": v230_ok, "v21_230_r1_input_found": r1_ok, "policy_guard_found": guard_found, "policy_guard_passed": policy_ok, "ticker_universe_count": int(s230.get("ticker_universe_count", 0) or 0), "planned_total_fetch_items": planned or int(s230.get("planned_total_fetch_items", 0) or 0), "attempted_fetch_items": attempted, "successful_fetch_items": success, "failed_fetch_items": failed, "daily_raw_attempted_count": raw_att, "daily_raw_success_count": raw_succ, "daily_raw_failure_count": raw_fail, "daily_qfq_attempted_count": qfq_att, "daily_qfq_success_count": qfq_succ, "daily_qfq_failure_count": qfq_fail, "dram_intraday_attempted_count": intra_att, "dram_intraday_success_count": intra_succ, "dram_intraday_failure_count": intra_fail, "daily_raw_success_ratio": raw_ratio, "daily_qfq_success_ratio": qfq_ratio, "dram_intraday_success_ratio": intra_ratio, "canonical_raw_row_count": canon_raw_rows, "canonical_qfq_row_count": canon_qfq_rows, "canonical_raw_ticker_count": canon_raw_tickers, "canonical_qfq_ticker_count": canon_qfq_tickers, "canonical_latest_date": latest, "canonical_snapshot_dir": str(paths["canonical"]), "cache_written_file_count": written_count, "cache_written_total_bytes": written_bytes, "hash_verified_file_count": hash_count, "quality_error_count": q_errors, "quality_warning_count": q_warnings, "coverage_warning_count": cov_warnings, "yfinance_used": False, "yahoo_used": False, "external_fallback_used": False, "moomoo_historical_fetch_used": attempted > 0, "data_fetch_used": attempted > 0, "broker_action_allowed": False, "trade_unlock_used": False, "official_adoption_allowed": False, "research_only": True, "warning_count": warning_count, "error_count": error_count}


def write_outputs(output_dir: Path, summary: dict[str, Any], fetch_rows: list[dict[str, Any]], raw_manifest: list[dict[str, Any]], qfq_manifest: list[dict[str, Any]], intra_manifest: list[dict[str, Any]], canonical_manifest: list[dict[str, Any]], quality_rows: list[dict[str, Any]], coverage_rows: list[dict[str, Any]], failed_rows: list[dict[str, Any]], error_rows: list[dict[str, Any]], rate_rows: list[dict[str, Any]], cross_rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]], pointer: dict[str, Any], write_rows: list[dict[str, Any]], exclusions: list[dict[str, Any]] | None = None, recovered_errors: list[dict[str, Any]] | None = None, reconnects: list[dict[str, Any]] | None = None) -> None:
    write_csv(output_dir / "fetch_execution_master.csv", fetch_rows, FETCH_FIELDS)
    write_csv(output_dir / "daily_raw_fetch_manifest.csv", raw_manifest, DAILY_FIELDS)
    write_csv(output_dir / "daily_qfq_fetch_manifest.csv", qfq_manifest, DAILY_FIELDS)
    write_csv(output_dir / "dram_intraday_fetch_manifest.csv", intra_manifest, INTRA_FIELDS)
    write_csv(output_dir / "canonical_rebuild_manifest.csv", canonical_manifest, CANON_FIELDS)
    write_csv(output_dir / "canonical_quality_audit.csv", quality_rows, QUALITY_FIELDS)
    write_csv(output_dir / "ticker_coverage_audit.csv", coverage_rows, COVERAGE_FIELDS)
    write_csv(output_dir / "failed_ticker_retry_ledger.csv", failed_rows, FAILED_FIELDS)
    write_csv(output_dir / "moomoo_api_error_ledger.csv", error_rows, ERROR_FIELDS)
    write_csv(output_dir / "fetch_rate_limit_audit.csv", rate_rows, RATE_FIELDS)
    write_csv(output_dir / "abcde_daily_exclusion_ledger.csv", exclusions or [], EXCLUSION_FIELDS)
    write_csv(output_dir / "moomoo_api_recovered_ledger.csv", recovered_errors or [], ERROR_FIELDS)
    write_csv(output_dir / "opend_reconnect_ledger.csv", reconnects or [], RECONNECT_FIELDS)
    write_csv(output_dir / "local_cache_write_manifest.csv", write_rows, WRITE_FIELDS)
    if pointer:
        write_json(output_dir / "canonical_snapshot_pointer.json", pointer)
        write_csv(output_dir / "canonical_snapshot_pointer.csv", [{"key": k, "value": v} for k, v in pointer.items()], POINTER_CSV_FIELDS)
    else:
        write_json(output_dir / "canonical_snapshot_pointer.json", {})
        write_csv(output_dir / "canonical_snapshot_pointer.csv", [], POINTER_CSV_FIELDS)
    write_csv(output_dir / "v21_230_230r1_readiness_crosscheck.csv", cross_rows, CROSS_FIELDS)
    write_csv(output_dir / "no_yfinance_enforcement_audit.csv", audit_rows, AUDIT_FIELDS)
    write_json(output_dir / "v21_231_summary.json", summary)
    report_keys = ["final_status","final_decision","snapshot_id","attempted_fetch_items","successful_fetch_items","failed_fetch_items","canonical_latest_date","cache_written_file_count","quality_error_count","warning_count","error_count"]
    (output_dir / "V21.231_moomoo_only_historical_refetch_and_canonical_rebuild_report.txt").write_text("\n".join([STAGE, *[f"{k}={summary.get(k)}" for k in report_keys], "yfinance_used=False", "external_fallback_used=False", "broker_action_allowed=False", "trade_unlock_used=False"]) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root", type=Path, default=default_repo_root())
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--v21-230-output-dir", type=Path, default=None)
    p.add_argument("--v21-230-r1-output-dir", type=Path, default=None)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--snapshot-id", default=None)
    p.add_argument("--resume-snapshot-id", default=None)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--sleep-seconds", type=float, default=0.25)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--max-fetch-items", type=int, default=None)
    p.add_argument("--min-daily-success-ratio", type=float, default=0.95)
    p.add_argument("--require-dram-intraday", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--allow-dram-missing", action="store_true", default=False)
    p.add_argument("--no-network", action="store_true", default=False)
    p.add_argument("--opend-host", default="127.0.0.1")
    p.add_argument("--opend-port", type=int, default=18441)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    root = a.repo_root.resolve()
    out = a.output_dir or (root / OUT_REL)
    summary = run(root, out, a.v21_230_output_dir, a.v21_230_r1_output_dir, a.cache_root, a.snapshot_id, a.resume_snapshot_id, a.start_date, a.end_date, a.batch_size, a.sleep_seconds, a.max_retries, a.max_fetch_items, a.min_daily_success_ratio, a.require_dram_intraday, a.allow_dram_missing, a.no_network, a.opend_host, a.opend_port)
    print(str(out / "v21_231_summary.json"))
    return 1 if str(summary["final_status"]).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
