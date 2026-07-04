#!/usr/bin/env python
"""V21.230 Moomoo-only historical refetch dry-run.

Plans the V21.231 Moomoo-only historical refetch and canonical rebuild inputs.
This module does not fetch market data, import provider SDKs, rebuild canonical
data, overwrite price panels, or mutate historical research outputs.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN"
OUT_REL = Path("outputs/v21") / STAGE
V229_R1_REL = Path("outputs/v21/V21.229_R1_ACTIVE_DATA_SOURCE_BLOCKER_TRIAGE_AND_ENFORCEMENT")
PASS_STATUS = "PASS_V21_230_MOOMOO_ONLY_REFETCH_DRY_RUN_READY"
WARN_STATUS = "WARN_V21_230_MOOMOO_ONLY_REFETCH_DRY_RUN_READY_WITH_PREREQUISITES"
FAIL_POLICY_STATUS = "FAIL_V21_230_BLOCKED_BY_MOOMOO_ONLY_POLICY_GATE"
FAIL_FORBIDDEN_STATUS = "FAIL_V21_230_YFINANCE_POLICY_VIOLATION"
PASS_DECISION = "MOOMOO_ONLY_HISTORICAL_REFETCH_PLAN_READY_FOR_V21_231_EXECUTION"
WARN_DECISION = "MOOMOO_ONLY_REFETCH_PLAN_READY_REVIEW_PREREQUISITES_BEFORE_V21_231"
NEXT_STAGE = "V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
DEFAULT_START_DATE = "2019-01-01"
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
DEFAULT_ARCHIVE_ROOT = Path(r"D:\us-tech-quant-archive")
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"
FORBIDDEN_WEB_PROVIDER = "ya" + "hoo"
SDK_ONE = "moo" + "moo"
SDK_TWO = "fu" + "tu"
INTRADAY_FREQS = ["1m", "5m", "15m", "1h"]
DAILY_ADJUSTMENTS = ["raw", "qfq"]
BENCHMARK_TICKERS = {"SPY", "QQQ", "SOXX", "SMH"}
LEVERAGED_ETFS = {"TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXL", "SPXS", "TECL", "TECS"}

PLAN_FIELDS = ["ticker","market","moomoo_symbol","asset_type","active_scope","frequency","adjustment","planned_start_date","planned_end_date","fetch_required","local_cache_available","local_cache_latest_date","proposed_raw_cache_path","proposed_canonical_path","estimated_rows","priority","notes"]
UNIVERSE_FIELDS = ["ticker","resolved_symbol","market","source_file","source_run_id","source_rank","included_in_dram","included_in_abcde","included_in_benchmark","included_in_active_universe","excluded_reason","notes"]
CONNECTION_FIELDS = ["check_name","expected","actual","pass","severity","notes"]
PERMISSION_FIELDS = ["permission_or_capability","required_for_stage","required_in_v21_230","required_in_v21_231","readiness","notes"]
FREQUENCY_FIELDS = ["frequency","scope","required","planned_for_v21_231","estimated_ticker_count","adjustment_modes","notes"]
ADJUSTMENT_FIELDS = ["adjustment","scope","required","planned_for_v21_231","reason"]
CACHE_TARGET_FIELDS = ["cache_category","proposed_path","source_policy","allowed_data_source","active_runtime_needed","retention_policy","will_create_in_v21_231","notes"]
CANONICAL_TARGET_FIELDS = ["canonical_category","proposed_path","source_policy","snapshot_policy","overwrite_allowed","will_create_in_v21_231","notes"]
DRAM_FIELDS = ["ticker","moomoo_symbol","frequency","planned_start_date","planned_end_date","proposed_cache_path","local_cache_available","fetch_required","priority","notes"]
ABCDE_FIELDS = ["ticker","moomoo_symbol","adjustment","planned_start_date","planned_end_date","proposed_cache_path","proposed_canonical_path","local_cache_available","fetch_required","notes"]
MISSING_FIELDS = ["ticker","moomoo_symbol","reason","severity","retry_allowed","yahoo_fallback_allowed","external_fallback_allowed","required_user_review","notes"]
VOLUME_FIELDS = ["category","frequency","ticker_count","estimated_rows","estimated_bytes","proposed_root","notes"]
REUSE_FIELDS = ["ticker","frequency","adjustment","local_cache_path","local_cache_exists","local_cache_latest_date","reusable_for_v21_231","reason"]
CROSS_FIELDS = ["check_name","expected","actual","pass","severity","notes"]
AUDIT_FIELDS = ["check_name","pass","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]
PREREQ_FIELDS = ["prerequisite","required","satisfied","severity","blocks_v21_231","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def read_csv_rows(path: Path, limit: int = 2000) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows: list[dict[str, str]] = []
            for row in csv.DictReader(handle):
                rows.append({k: (v or "") for k, v in row.items() if k is not None})
                if len(rows) >= limit:
                    break
            return rows
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix().replace("\\", "/")


def bool_text(value: bool) -> str:
    return "True" if value else "False"


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


def latest_known_completed_session(repo_root: Path) -> str:
    pattern = re.compile(r"20\d{2}-\d{2}-\d{2}")
    best = ""
    bases = [repo_root / "outputs/v21", repo_root / "config/v21"]
    for base in bases:
        if not base.exists():
            continue
        for path in list(base.glob("*.json")) + list(base.glob("*.csv")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:200000]
            except OSError:
                continue
            for match in pattern.findall(text):
                if match > best:
                    best = match
    return best or date.today().isoformat()


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    ticker = ticker.replace(".", "-")
    return re.sub(r"[^A-Z0-9\-]", "", ticker)


def market_for_ticker(ticker: str) -> str:
    return "US"


def moomoo_symbol_for(ticker: str) -> str:
    return f"US.{ticker}"


def asset_type_for(ticker: str) -> str:
    return "ETF" if ticker in BENCHMARK_TICKERS or ticker.endswith("Q") and ticker in {"QQQ"} else "EQUITY"


def source_run_id(path: Path) -> str:
    for part in reversed(path.parts):
        if part.startswith("V21.") or part.startswith("FULL_SYSTEM"):
            return part
    return path.parent.name


def candidate_universe_files(repo_root: Path, include_v20: bool) -> list[Path]:
    bases = [repo_root / "outputs/v21", repo_root / "config/v21"]
    if include_v20:
        bases.extend([repo_root / "outputs/v20", repo_root / "config/v20"])
    files: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            parts = {p.lower() for p in path.parts}
            if any("pytest_tmp" in p or p in {".pytest_cache", "__pycache__"} for p in parts):
                continue
            name = path.name.lower()
            if path.suffix.lower() == ".csv" and any(term in name for term in ["ranking", "universe", "ticker", "dram", "abcde", "canonical", "moomoo"]):
                files.append(path)
            elif path.suffix.lower() == ".json" and any(term in name for term in ["summary", "manifest", "universe", "ticker"]):
                files.append(path)
    return sorted(files, key=lambda p: (p.stat().st_mtime if p.exists() else 0, str(p)), reverse=True)[:300]


def add_ticker(found: dict[str, dict[str, Any]], ticker: str, path: Path, root: Path, rank: str = "", *, dram: bool = False, abcde: bool = False, benchmark: bool = False, active: bool = True, notes: str = "") -> None:
    ticker = normalize_ticker(ticker)
    if not ticker or len(ticker) > 8 or ticker in {"ALL", "NAN", "NONE", "NULL"}:
        return
    if ticker in LEVERAGED_ETFS and not benchmark:
        return
    current = found.setdefault(ticker, {
        "ticker": ticker,
        "resolved_symbol": moomoo_symbol_for(ticker),
        "market": market_for_ticker(ticker),
        "source_file": rel(path, root) if path else "seed",
        "source_run_id": source_run_id(path) if path else "V21.230_SEED",
        "source_rank": rank,
        "included_in_dram": False,
        "included_in_abcde": False,
        "included_in_benchmark": False,
        "included_in_active_universe": False,
        "excluded_reason": "",
        "notes": "",
    })
    current["included_in_dram"] = bool(current["included_in_dram"] or dram or ticker == "DRAM")
    current["included_in_abcde"] = bool(current["included_in_abcde"] or abcde)
    current["included_in_benchmark"] = bool(current["included_in_benchmark"] or benchmark or ticker in BENCHMARK_TICKERS)
    current["included_in_active_universe"] = bool(current["included_in_active_universe"] or active)
    if rank and not current.get("source_rank"):
        current["source_rank"] = rank
    if notes and notes not in current.get("notes", ""):
        current["notes"] = (current.get("notes", "") + "; " + notes).strip("; ")


def resolve_universe(repo_root: Path, include_v20: bool) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in candidate_universe_files(repo_root, include_v20):
        lower = path.as_posix().lower()
        is_dram = "dram" in lower
        is_abcde = "abcde" in lower or "ranking" in lower or "abcd" in lower
        if path.suffix.lower() == ".csv":
            for row in read_csv_rows(path):
                key = next((k for k in row if k and k.lower() in {"ticker", "symbol", "resolved_symbol"}), "")
                if not key:
                    continue
                rank_key = next((k for k in row if k and k.lower() == "rank"), "")
                ticker = row.get(key, "")
                add_ticker(found, ticker, path, repo_root, row.get(rank_key, "") if rank_key else "", dram=is_dram or normalize_ticker(ticker) == "DRAM", abcde=is_abcde, benchmark=normalize_ticker(ticker) in BENCHMARK_TICKERS, active=True)
        elif path.suffix.lower() == ".json":
            payload = read_json(path)
            for key in ["tickers", "ticker_universe", "active_tickers", "watch_tickers", "failed_tickers"]:
                value = payload.get(key)
                if isinstance(value, list):
                    for item in value:
                        ticker = item.get("ticker", "") if isinstance(item, dict) else str(item)
                        add_ticker(found, ticker, path, repo_root, dram=is_dram or normalize_ticker(ticker) == "DRAM", abcde=is_abcde, benchmark=normalize_ticker(ticker) in BENCHMARK_TICKERS, active=True, notes=f"from_json_{key}")
                elif isinstance(value, str):
                    for ticker in re.split(r"[,;\s]+", value):
                        add_ticker(found, ticker, path, repo_root, dram=is_dram or normalize_ticker(ticker) == "DRAM", abcde=is_abcde, benchmark=normalize_ticker(ticker) in BENCHMARK_TICKERS, active=True, notes=f"from_json_{key}")
    add_ticker(found, "DRAM", Path("seed"), repo_root, dram=True, abcde=True, active=True, notes="required DRAM ticker seed")
    for ticker in sorted(BENCHMARK_TICKERS):
        add_ticker(found, ticker, Path("seed"), repo_root, benchmark=True, active=True, notes="active benchmark/support seed")
    rows = list(found.values())
    for row in rows:
        for key in ["included_in_dram", "included_in_abcde", "included_in_benchmark", "included_in_active_universe"]:
            row[key] = bool_text(bool(row[key]))
    return sorted(rows, key=lambda r: (r["ticker"] != "DRAM", r["ticker"]))


def cache_path(cache_root: Path, ticker: str, frequency: str, adjustment: str) -> Path:
    return cache_root / "data/raw/moomoo" / frequency / adjustment / f"{ticker}.csv"


def canonical_path(cache_root: Path, ticker: str, adjustment: str) -> Path:
    return cache_root / "data/canonical/moomoo_only" / adjustment / f"{ticker}.csv"


def cache_latest_date(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    pattern = re.compile(r"20\d{2}-\d{2}-\d{2}")
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[-200000:]
    except OSError:
        return ""
    matches = pattern.findall(text)
    return max(matches) if matches else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()


def estimate_rows(start: str, end: str, frequency: str) -> int:
    try:
        days = max((date.fromisoformat(end) - date.fromisoformat(start)).days + 1, 1)
    except ValueError:
        days = 1
    if frequency == "1d":
        return max(int(days * 5 / 7), 1)
    per_day = {"1m": 390, "5m": 78, "15m": 26, "1h": 7}.get(frequency, 1)
    return max(int(days * 5 / 7) * per_day, per_day)


def build_plans(universe: list[dict[str, Any]], cache_root: Path, start_date: str, end_date: str) -> dict[str, Any]:
    main_rows: list[dict[str, Any]] = []
    dram_rows: list[dict[str, Any]] = []
    abcde_rows: list[dict[str, Any]] = []
    reuse_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    for item in universe:
        ticker = item["ticker"]
        symbol = item["resolved_symbol"]
        scope = ",".join(name for name, flag in [
            ("DRAM", item["included_in_dram"] == "True"),
            ("ABCDE", item["included_in_abcde"] == "True"),
            ("BENCHMARK", item["included_in_benchmark"] == "True"),
            ("ACTIVE_UNIVERSE", item["included_in_active_universe"] == "True"),
        ] if flag)
        for adjustment in DAILY_ADJUSTMENTS:
            cpath = cache_path(cache_root, ticker, "1d", adjustment)
            canpath = canonical_path(cache_root, ticker, adjustment)
            latest = cache_latest_date(cpath)
            exists = cpath.exists()
            rows = estimate_rows(start_date, end_date, "1d")
            main_rows.append({
                "ticker": ticker, "market": item["market"], "moomoo_symbol": symbol, "asset_type": asset_type_for(ticker),
                "active_scope": scope, "frequency": "1d", "adjustment": adjustment, "planned_start_date": start_date,
                "planned_end_date": end_date, "fetch_required": bool_text(not exists), "local_cache_available": bool_text(exists),
                "local_cache_latest_date": latest, "proposed_raw_cache_path": str(cpath), "proposed_canonical_path": str(canpath),
                "estimated_rows": rows, "priority": "HIGH" if ticker == "DRAM" else "NORMAL",
                "notes": "dry-run only; no historical bars requested",
            })
            abcde_rows.append({
                "ticker": ticker, "moomoo_symbol": symbol, "adjustment": adjustment, "planned_start_date": start_date,
                "planned_end_date": end_date, "proposed_cache_path": str(cpath), "proposed_canonical_path": str(canpath),
                "local_cache_available": bool_text(exists), "fetch_required": bool_text(not exists),
                "notes": "planned for V21.231 ABCDE/canonical daily input",
            })
            reuse_rows.append({
                "ticker": ticker, "frequency": "1d", "adjustment": adjustment, "local_cache_path": str(cpath),
                "local_cache_exists": bool_text(exists), "local_cache_latest_date": latest,
                "reusable_for_v21_231": bool_text(exists), "reason": "local cache file exists" if exists else "no local cache file found",
            })
        if item["included_in_dram"] == "True":
            for freq in INTRADAY_FREQS:
                cpath = cache_path(cache_root, ticker, freq, "raw")
                exists = cpath.exists()
                main_rows.append({
                    "ticker": ticker, "market": item["market"], "moomoo_symbol": symbol, "asset_type": asset_type_for(ticker),
                    "active_scope": scope, "frequency": freq, "adjustment": "raw", "planned_start_date": start_date,
                    "planned_end_date": end_date, "fetch_required": bool_text(not exists), "local_cache_available": bool_text(exists),
                    "local_cache_latest_date": cache_latest_date(cpath), "proposed_raw_cache_path": str(cpath),
                    "proposed_canonical_path": "", "estimated_rows": estimate_rows(start_date, end_date, freq),
                    "priority": "HIGH", "notes": "DRAM intraday dry-run plan only",
                })
                dram_rows.append({
                    "ticker": ticker, "moomoo_symbol": symbol, "frequency": freq, "planned_start_date": start_date,
                    "planned_end_date": end_date, "proposed_cache_path": str(cpath), "local_cache_available": bool_text(exists),
                    "fetch_required": bool_text(not exists), "priority": "HIGH", "notes": "no intraday bars requested in V21.230",
                })
                reuse_rows.append({
                    "ticker": ticker, "frequency": freq, "adjustment": "raw", "local_cache_path": str(cpath),
                    "local_cache_exists": bool_text(exists), "local_cache_latest_date": cache_latest_date(cpath),
                    "reusable_for_v21_231": bool_text(exists), "reason": "local cache file exists" if exists else "no local cache file found",
                })
        if not symbol:
            missing_rows.append({
                "ticker": ticker, "moomoo_symbol": symbol, "reason": "missing resolved Moomoo symbol", "severity": "ERROR",
                "retry_allowed": "True", "yahoo_fallback_allowed": "False", "external_fallback_allowed": "False",
                "required_user_review": "True", "notes": "no external fallback allowed",
            })
    return {"main": main_rows, "dram": dram_rows, "abcde": abcde_rows, "reuse": reuse_rows, "missing": missing_rows}


def policy_gate() -> dict[str, Any]:
    return {
        "policy_version": "V21.230",
        "dry_run_only": True,
        "actual_historical_fetch_allowed_now": False,
        "canonical_rebuild_allowed_now": False,
        "overwrite_allowed_now": False,
        "yfinance_allowed": False,
        "yahoo_allowed": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "moomoo_bulk_fetch_allowed_now": False,
        "opend_probe_allowed_by_default": False,
        "data_fetch_used": False,
        "yfinance_used": False,
        "moomoo_historical_fetch_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "next_allowed_stage": NEXT_STAGE,
    }


def self_forbidden_audit(repo_root: Path) -> tuple[list[dict[str, Any]], bool]:
    script = repo_root / "scripts/v21/v21_230_moomoo_only_historical_refetch_dry_run.py"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    import_present = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call_present = FORBIDDEN_PROVIDER_CALL in text
    rows = [{
        "check_name": "v21_230_script_forbidden_provider_audit",
        "pass": bool_text(not import_present and not call_present),
        "yfinance_import_present": bool_text(import_present),
        "yfinance_call_present": bool_text(call_present),
        "yahoo_default_allowed": "False",
        "external_fallback_default_allowed": "False",
        "notes": "static audit of V21.230 dry-run script; no provider call executed",
    }]
    return rows, import_present or call_present


def run(
    repo_root: Path,
    output_dir: Path,
    v21_229_r1_output_dir: Path | None = None,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    allow_opend_probe: bool = False,
    include_v20: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    end_date = end_date or latest_known_completed_session(repo_root)
    v229_dir = (v21_229_r1_output_dir or (repo_root / V229_R1_REL)).resolve()
    v229_summary_path = v229_dir / "v21_229_r1_summary.json"
    v229_summary = read_json(v229_summary_path)
    guard_found = (repo_root / "scripts/v21/v21_data_source_policy_guard.py").exists()
    policy_guard_passed = False
    warning_count = 0
    error_count = 0
    hard_fail = False
    fail_status = FAIL_POLICY_STATUS
    cross_rows: list[dict[str, Any]] = []

    if not v229_summary_path.exists() or not v229_summary.get("v21_230_ready", False) or int(v229_summary.get("still_blocks_v21_230_count", 1)) != 0:
        hard_fail = True
        error_count += 1
    if not guard_found:
        hard_fail = True
        error_count += 1

    if guard_found:
        try:
            guard = load_policy_guard(repo_root)
            guard.assert_moomoo_only_policy("V21.230 canonical dram abcde dry-run")
            policy = guard.load_data_source_policy(repo_root / "config/v21/data_source_policy.json")
            flags = guard.policy_flags_for_summary()
            blocked_keys = [
                "yfinance_allowed_by_default", "yahoo_allowed_by_default", "yfinance_allowed_for_canonical",
                "yfinance_allowed_for_dram", "yfinance_allowed_for_abcde", "external_fallback_allowed_for_canonical",
                "external_fallback_allowed_for_dram", "external_fallback_allowed_for_abcde", "broker_action_allowed",
                "official_adoption_allowed",
            ]
            bad = [key for key in blocked_keys if policy.get(key) is not False]
            if flags.get("research_only") is not True or policy.get("research_only") is not True:
                bad.append("research_only")
            if policy.get("default_data_source_policy") != "MOOMOO_ONLY":
                bad.append("default_data_source_policy")
            policy_guard_passed = not bad
            if bad:
                hard_fail = True
                error_count += 1
        except Exception as exc:
            policy_guard_passed = False
            hard_fail = True
            error_count += 1
            policy = {}
            flags = {}
            warning_count += 1
            guard_error = str(exc)
        else:
            guard_error = ""
    else:
        policy = {}
        flags = {}
        guard_error = "policy guard missing"

    audit_rows, forbidden_violation = self_forbidden_audit(repo_root)
    if forbidden_violation:
        hard_fail = True
        fail_status = FAIL_FORBIDDEN_STATUS
        error_count += 1

    universe = resolve_universe(repo_root, include_v20) if not hard_fail else []
    plans = build_plans(universe, cache_root, start_date, end_date)
    daily_raw = [r for r in plans["main"] if r["frequency"] == "1d" and r["adjustment"] == "raw"]
    daily_qfq = [r for r in plans["main"] if r["frequency"] == "1d" and r["adjustment"] == "qfq"]
    intraday = [r for r in plans["main"] if r["frequency"] in INTRADAY_FREQS]
    reuse_count = sum(1 for r in plans["reuse"] if r["local_cache_exists"] == "True")
    estimated_total_rows = sum(int(r["estimated_rows"]) for r in plans["main"])
    estimated_total_bytes = estimated_total_rows * 96

    connection_rows = [
        {"check_name": "opend_probe_default", "expected": "False", "actual": bool_text(allow_opend_probe), "pass": bool_text(not allow_opend_probe), "severity": "INFO", "notes": "default is disabled; no historical bars requested"},
        {"check_name": "cache_root_exists", "expected": "optional", "actual": bool_text(cache_root.exists()), "pass": "True", "severity": "INFO", "notes": "existence checked only; directory not created"},
        {"check_name": "archive_root_exists", "expected": "optional", "actual": bool_text(archive_root.exists()), "pass": "True", "severity": "INFO", "notes": "existence checked only"},
    ]
    opend_status = "NOT_PROBED_BY_DEFAULT" if not allow_opend_probe else "PROBE_NOT_IMPLEMENTED_NO_MARKET_DATA_REQUESTED"
    permission_rows = [
        {"permission_or_capability": "Moomoo OpenD historical kline", "required_for_stage": "V21.231", "required_in_v21_230": "False", "required_in_v21_231": "True", "readiness": "NOT_CHECKED_DRY_RUN", "notes": "no SDK import and no bar request in V21.230"},
        {"permission_or_capability": "local cache read", "required_for_stage": "V21.230", "required_in_v21_230": "True", "required_in_v21_231": "True", "readiness": "READY", "notes": "read-only path existence checks only"},
    ]
    frequency_rows = [
        {"frequency": "1d", "scope": "daily raw/qfq canonical input", "required": "True", "planned_for_v21_231": "True", "estimated_ticker_count": len(universe), "adjustment_modes": "raw,qfq", "notes": "daily dry-run plan"},
    ] + [
        {"frequency": freq, "scope": "DRAM intraday", "required": "True", "planned_for_v21_231": "True", "estimated_ticker_count": sum(1 for r in universe if r["included_in_dram"] == "True"), "adjustment_modes": "raw", "notes": "intraday dry-run plan"}
        for freq in INTRADAY_FREQS
    ]
    adjustment_rows = [
        {"adjustment": "raw", "scope": "daily and intraday", "required": "True", "planned_for_v21_231": "True", "reason": "raw bars preserve provider source input"},
        {"adjustment": "qfq", "scope": "daily", "required": "True", "planned_for_v21_231": "True", "reason": "qfq daily bars required for adjusted OHLCV research input"},
    ]
    cache_target_rows = [
        {"cache_category": "daily_raw", "proposed_path": str(cache_root / "data/raw/moomoo/1d/raw"), "source_policy": "MOOMOO_ONLY", "allowed_data_source": "MOOMOO_OPEND_OR_LOCAL_MOOMOO_CACHE", "active_runtime_needed": "V21.231", "retention_policy": "external_cache", "will_create_in_v21_231": "True", "notes": "not created in V21.230"},
        {"cache_category": "daily_qfq", "proposed_path": str(cache_root / "data/raw/moomoo/1d/qfq"), "source_policy": "MOOMOO_ONLY", "allowed_data_source": "MOOMOO_OPEND_OR_LOCAL_MOOMOO_CACHE", "active_runtime_needed": "V21.231", "retention_policy": "external_cache", "will_create_in_v21_231": "True", "notes": "not created in V21.230"},
        {"cache_category": "dram_intraday", "proposed_path": str(cache_root / "data/raw/moomoo/{frequency}/raw"), "source_policy": "MOOMOO_ONLY", "allowed_data_source": "MOOMOO_OPEND_OR_LOCAL_MOOMOO_CACHE", "active_runtime_needed": "V21.231", "retention_policy": "external_cache", "will_create_in_v21_231": "True", "notes": "not created in V21.230"},
    ]
    canonical_target_rows = [
        {"canonical_category": "moomoo_only_ohlcv", "proposed_path": str(cache_root / "data/canonical/moomoo_only"), "source_policy": "MOOMOO_ONLY", "snapshot_policy": "new V21.231 snapshot only", "overwrite_allowed": "False", "will_create_in_v21_231": "True", "notes": "canonical rebuild forbidden in V21.230"},
    ]
    volume_rows = [
        {"category": "daily_raw", "frequency": "1d", "ticker_count": len(universe), "estimated_rows": sum(int(r["estimated_rows"]) for r in daily_raw), "estimated_bytes": sum(int(r["estimated_rows"]) for r in daily_raw) * 96, "proposed_root": str(cache_root), "notes": "estimate only"},
        {"category": "daily_qfq", "frequency": "1d", "ticker_count": len(universe), "estimated_rows": sum(int(r["estimated_rows"]) for r in daily_qfq), "estimated_bytes": sum(int(r["estimated_rows"]) for r in daily_qfq) * 96, "proposed_root": str(cache_root), "notes": "estimate only"},
        {"category": "dram_intraday", "frequency": "mixed", "ticker_count": sum(1 for r in universe if r["included_in_dram"] == "True"), "estimated_rows": sum(int(r["estimated_rows"]) for r in intraday), "estimated_bytes": sum(int(r["estimated_rows"]) for r in intraday) * 96, "proposed_root": str(cache_root), "notes": "estimate only"},
    ]
    cross_rows.extend([
        {"check_name": "v21_229_r1_summary_found", "expected": "True", "actual": bool_text(v229_summary_path.exists()), "pass": bool_text(v229_summary_path.exists()), "severity": "ERROR" if not v229_summary_path.exists() else "INFO", "notes": str(v229_summary_path)},
        {"check_name": "v21_230_ready", "expected": "True", "actual": str(v229_summary.get("v21_230_ready", "")), "pass": bool_text(v229_summary.get("v21_230_ready", False) is True), "severity": "ERROR", "notes": "must be ready from V21.229_R1"},
        {"check_name": "still_blocks_v21_230_count", "expected": "0", "actual": str(v229_summary.get("still_blocks_v21_230_count", "")), "pass": bool_text(int(v229_summary.get("still_blocks_v21_230_count", 999)) == 0 if str(v229_summary.get("still_blocks_v21_230_count", "")).isdigit() else False), "severity": "ERROR", "notes": "must be zero"},
        {"check_name": "policy_guard_imported_and_passed", "expected": "True", "actual": bool_text(policy_guard_passed), "pass": bool_text(policy_guard_passed), "severity": "ERROR", "notes": guard_error},
    ])
    prereq_rows = [
        {"prerequisite": "V21.229_R1 Moomoo-only policy readiness", "required": "True", "satisfied": bool_text(not hard_fail and bool(v229_summary)), "severity": "ERROR", "blocks_v21_231": bool_text(hard_fail), "notes": "policy gate must remain ready"},
        {"prerequisite": "Moomoo OpenD configured and permissioned", "required": "True", "satisfied": "False", "severity": "WARN", "blocks_v21_231": "False", "notes": "not probed by default in V21.230"},
        {"prerequisite": "human approval for V21.231 actual fetch", "required": "True", "satisfied": "False", "severity": "WARN", "blocks_v21_231": "False", "notes": "V21.230 is dry-run only"},
    ]
    v21_231_blockers = sum(1 for r in prereq_rows if r["blocks_v21_231"] == "True")
    warning_count += sum(1 for r in prereq_rows if r["severity"] == "WARN")
    final_status = fail_status if hard_fail else (WARN_STATUS if any(r["satisfied"] == "False" and r["severity"] == "WARN" for r in prereq_rows) else PASS_STATUS)
    final_decision = WARN_DECISION if final_status == WARN_STATUS else PASS_DECISION

    gate = policy_gate()
    write_json(output_dir / "dry_run_policy_gate.json", gate)
    write_csv(output_dir / "moomoo_refetch_dry_run_plan.csv", plans["main"], PLAN_FIELDS)
    write_csv(output_dir / "ticker_universe_resolution.csv", universe, UNIVERSE_FIELDS)
    write_csv(output_dir / "moomoo_connection_readiness.csv", connection_rows, CONNECTION_FIELDS)
    write_csv(output_dir / "moomoo_permission_readiness.csv", permission_rows, PERMISSION_FIELDS)
    write_csv(output_dir / "moomoo_frequency_plan.csv", frequency_rows, FREQUENCY_FIELDS)
    write_csv(output_dir / "moomoo_adjustment_plan.csv", adjustment_rows, ADJUSTMENT_FIELDS)
    write_csv(output_dir / "moomoo_cache_target_plan.csv", cache_target_rows, CACHE_TARGET_FIELDS)
    write_csv(output_dir / "moomoo_canonical_target_plan.csv", canonical_target_rows, CANONICAL_TARGET_FIELDS)
    write_csv(output_dir / "dram_intraday_refetch_plan.csv", plans["dram"], DRAM_FIELDS)
    write_csv(output_dir / "abcde_daily_refetch_plan.csv", plans["abcde"], ABCDE_FIELDS)
    write_csv(output_dir / "failed_or_missing_ticker_plan.csv", plans["missing"], MISSING_FIELDS)
    write_csv(output_dir / "estimated_data_volume_plan.csv", volume_rows, VOLUME_FIELDS)
    write_csv(output_dir / "local_cache_reuse_plan.csv", plans["reuse"], REUSE_FIELDS)
    write_csv(output_dir / "v21_229_r1_policy_crosscheck.csv", cross_rows, CROSS_FIELDS)
    write_csv(output_dir / "no_yfinance_enforcement_audit.csv", audit_rows, AUDIT_FIELDS)
    write_csv(output_dir / "v21_231_execution_prerequisites.csv", prereq_rows, PREREQ_FIELDS)

    summary = {
        "final_status": final_status,
        "final_decision": final_decision,
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "v21_229_r1_input_found": v229_summary_path.exists(),
        "policy_guard_found": guard_found,
        "policy_guard_passed": policy_guard_passed,
        "ticker_universe_count": len(universe),
        "dram_ticker_count": sum(1 for r in universe if r["included_in_dram"] == "True"),
        "abcde_ticker_count": sum(1 for r in universe if r["included_in_abcde"] == "True"),
        "benchmark_ticker_count": sum(1 for r in universe if r["included_in_benchmark"] == "True"),
        "planned_daily_raw_item_count": len(daily_raw),
        "planned_daily_qfq_item_count": len(daily_qfq),
        "planned_intraday_item_count": len(intraday),
        "planned_total_fetch_items": len(plans["main"]),
        "local_cache_reuse_candidate_count": reuse_count,
        "missing_ticker_count": len(plans["missing"]),
        "failed_or_missing_ticker_count": len(plans["missing"]),
        "estimated_total_rows": estimated_total_rows,
        "estimated_total_bytes": estimated_total_bytes,
        "opend_probe_used": allow_opend_probe,
        "opend_readiness_status": opend_status,
        "v21_231_blocker_count": v21_231_blockers,
        "dry_run_only": True,
        "actual_historical_fetch_allowed_now": False,
        "canonical_rebuild_allowed_now": False,
        "overwrite_allowed_now": False,
        "yfinance_used": False,
        "yahoo_used": False,
        "external_fallback_used": False,
        "moomoo_historical_fetch_used": False,
        "data_fetch_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "warning_count": warning_count,
        "error_count": error_count,
    }
    write_json(output_dir / "v21_230_summary.json", summary)
    report = "\n".join([STAGE, f"final_status={final_status}", f"final_decision={final_decision}", f"ticker_universe_count={len(universe)}", f"planned_total_fetch_items={len(plans['main'])}", "historical_data_fetched=False", "canonical_data_rebuilt=False"]) + "\n"
    (output_dir / "V21.230_moomoo_only_historical_refetch_dry_run_report.txt").write_text(report, encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--v21-229-r1-output-dir", type=Path, default=None)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--allow-opend-probe", action="store_true", default=False)
    parser.add_argument("--include-v20", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    out = args.output_dir or (repo_root / OUT_REL)
    summary = run(
        repo_root=repo_root,
        output_dir=out,
        v21_229_r1_output_dir=args.v21_229_r1_output_dir,
        cache_root=args.cache_root,
        archive_root=args.archive_root,
        start_date=args.start_date,
        end_date=args.end_date,
        allow_opend_probe=args.allow_opend_probe,
        include_v20=args.include_v20,
    )
    print(str(out / "v21_230_summary.json"))
    return 1 if summary["final_status"].startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
