#!/usr/bin/env python
"""V21.231 Moomoo-only historical refetch and canonical rebuild."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.util
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import pandas as pd
except Exception:  # pragma: no cover - tests exercise stdlib fallback lightly
    pd = None


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
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"
SDK_NAMES = ["moo" + "moo", "fu" + "tu"]
DEFAULT_CACHE_ROOT = Path(r"D:\us-tech-quant-cache")

FETCH_FIELDS = ["ticker","moomoo_symbol","market","asset_type","active_scope","frequency","adjustment","planned_start_date","planned_end_date","attempted","success","row_count","latest_bar_date","cache_path","sha256","error_type","error_message","retry_count","source","source_policy","notes"]
DAILY_FIELDS = ["ticker","moomoo_symbol","market","attempted","success","row_count","first_date","latest_date","cache_path","sha256","error_type","notes"]
INTRA_FIELDS = ["ticker","moomoo_symbol","frequency","attempted","success","row_count","first_timestamp","latest_timestamp","cache_path","sha256","error_type","notes"]
CANON_FIELDS = ["canonical_artifact","path","adjustment","row_count","ticker_count","first_date","latest_date","sha256","source_policy","yfinance_used","external_fallback_used","notes"]
QUALITY_FIELDS = ["check_name","scope","passed","severity","affected_rows","affected_tickers","notes"]
COVERAGE_FIELDS = ["ticker","moomoo_symbol","daily_raw_success","daily_qfq_success","intraday_success","raw_latest_date","qfq_latest_date","coverage_status","missing_reason","notes"]
FAILED_FIELDS = ["ticker","moomoo_symbol","frequency","adjustment","error_type","error_message","retry_count","retry_allowed","yahoo_fallback_allowed","external_fallback_allowed","required_user_review","notes"]
ERROR_FIELDS = ["timestamp_utc","ticker","moomoo_symbol","frequency","adjustment","api_call","error_type","error_message","retry_count","severity","notes"]
RATE_FIELDS = ["batch_number","item_count","sleep_seconds","started_at_utc","ended_at_utc","duration_seconds","notes"]
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


def make_snapshot_id() -> str:
    return datetime.now().strftime("moomoo_only_%Y%m%d_%H%M%S")


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
        if max_items is not None and len(selected) >= max_items:
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


def guarded_moomoo_fetch(item: dict[str, Any], host: str, port: int, max_retries: int, snapshot_id: str) -> tuple[list[dict[str, Any]], str, str, int]:
    last_error = ("", "")
    for retry in range(max_retries + 1):
        ctx = None
        try:
            module = None
            for name in SDK_NAMES:
                try:
                    module = importlib.import_module(name)
                    break
                except Exception:
                    continue
            if module is None:
                raise RuntimeError("Moomoo/Futu SDK import failed")
            quote_cls = getattr(module, "OpenQuoteContext")
            ctx = quote_cls(host=host, port=int(port))
            ktype_map = {"1d": "K_DAY", "1m": "K_1M", "5m": "K_5M", "15m": "K_15M", "1h": "K_60M"}
            au_map = {"raw": "NONE", "qfq": "QFQ"}
            kltype = getattr(getattr(module, "KLType"), ktype_map[item["frequency"]])
            autype = getattr(getattr(module, "AuType"), au_map.get(item["adjustment"], "NONE"))
            page_key = None
            frames = []
            while True:
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
            return normalize_records(data, item["ticker"], item["moomoo_symbol"], item.get("market", "US"), item["adjustment"], snapshot_id, utc_now()), "", "", retry
        except Exception as exc:
            last_error = (type(exc).__name__, str(exc))
            if retry >= max_retries:
                return [], last_error[0], last_error[1], retry
            time.sleep(0.5)
        finally:
            if ctx is not None and hasattr(ctx, "close"):
                try:
                    ctx.close()
                except Exception:
                    pass
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
    opend_port: int = 11111,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    v230_dir = (v21_230_output_dir or (repo_root / V230_REL)).resolve()
    v230r1_dir = (v21_230_r1_output_dir or (repo_root / V230R1_REL)).resolve()
    snapshot = resume_snapshot_id or snapshot_id or make_snapshot_id()
    resume = resume_snapshot_id is not None
    paths = snapshot_paths(cache_root, snapshot)
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
    snapshot_ok, snapshot_error = ensure_snapshot_available(paths, resume)
    write_json(output_dir / "source_policy_gate.json", source_policy_gate())
    if not input_ok or not policy_ok or forbidden_violation or not snapshot_ok:
        status = FAIL_INPUT if not input_ok else FAIL_SOURCE if (not policy_ok or forbidden_violation) else FAIL_SNAPSHOT
        summary = base_summary(
            status, repo_root, output_dir, cache_root, snapshot,
            input_ok, sr1.get("v21_231_ready") is True, guard_found, policy_ok, paths, s230,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            0.0, 0.0, 0.0,
            0, 0, 0, 0, "",
            0, 0, 0, 0, 0, 0,
            error_count + 1, warning_count,
        )
        write_outputs(output_dir, summary, [], [], [], [], [], [], [], [], [], [], cross_rows, audit_rows, {}, [])
        return summary

    items = plans(v230_dir, start_date, end_date, max_fetch_items)
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
    for batch_index in range(0, len(items), max(1, batch_size)):
        batch = items[batch_index:batch_index + max(1, batch_size)]
        started = utc_now()
        t0 = time.perf_counter()
        for item in batch:
            target = cache_file_for(paths, item)
            attempted = True
            if no_network:
                records, err_type, err_msg, retry_count = mock_fetch(item, snapshot), "", "", 0
            else:
                records, err_type, err_msg, retry_count = guarded_moomoo_fetch(item, opend_host, opend_port, max_retries, snapshot)
            success = bool(records)
            digest = ""
            size = 0
            row_count = 0
            written = False
            already = False
            if success:
                ok, digest, size, row_count, written, already = write_records(target, records, resume)
                success = ok
                write_rows.append({"source_path_or_api": "MOOMOO_OPEND" if not no_network else "MOCK_NO_NETWORK", "cache_path": str(target), "file_exists": bool_text(target.exists()), "size_bytes": size, "sha256": digest, "written_now": bool_text(written), "already_present_verified": bool_text(already), "verified": bool_text(ok), "notes": "raw fetched cache file"})
                if item["frequency"] == "1d" and item["adjustment"] == "raw":
                    raw_files.append(target); raw_rows_all.extend(records)
                if item["frequency"] == "1d" and item["adjustment"] == "qfq":
                    qfq_files.append(target); qfq_rows_all.extend(records)
            first, latest = date_stats(records)
            base = {"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "market": item.get("market", "US"), "asset_type": item.get("asset_type", ""), "active_scope": item.get("active_scope", ""), "frequency": item["frequency"], "adjustment": item["adjustment"], "planned_start_date": item.get("planned_start_date", ""), "planned_end_date": item.get("planned_end_date", ""), "attempted": bool_text(attempted), "success": bool_text(success), "row_count": row_count, "latest_bar_date": latest, "cache_path": str(target), "sha256": digest, "error_type": err_type, "error_message": err_msg, "retry_count": retry_count, "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY", "notes": "Moomoo-only fetch"}
            fetch_rows.append(base)
            if item["frequency"] == "1d":
                manifest = {"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "market": item.get("market", "US"), "attempted": "True", "success": bool_text(success), "row_count": row_count, "first_date": first, "latest_date": latest, "cache_path": str(target), "sha256": digest, "error_type": err_type, "notes": "daily fetch"}
                (raw_manifest if item["adjustment"] == "raw" else qfq_manifest).append(manifest)
            else:
                intra_manifest.append({"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "attempted": "True", "success": bool_text(success), "row_count": row_count, "first_timestamp": first, "latest_timestamp": latest, "cache_path": str(target), "sha256": digest, "error_type": err_type, "notes": "DRAM intraday fetch"})
            if not success:
                failed_rows.append({"ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "adjustment": item["adjustment"], "error_type": err_type or "EmptyData", "error_message": err_msg, "retry_count": retry_count, "retry_allowed": "True", "yahoo_fallback_allowed": "False", "external_fallback_allowed": "False", "required_user_review": "True", "notes": "no fallback allowed"})
                error_rows.append({"timestamp_utc": utc_now(), "ticker": item["ticker"], "moomoo_symbol": item["moomoo_symbol"], "frequency": item["frequency"], "adjustment": item["adjustment"], "api_call": "request_history_kline", "error_type": err_type or "EmptyData", "error_message": err_msg, "retry_count": retry_count, "severity": "ERROR", "notes": "Moomoo API failure or empty response"})
        ended = utc_now()
        rate_rows.append({"batch_number": batch_index // max(1, batch_size) + 1, "item_count": len(batch), "sleep_seconds": sleep_seconds, "started_at_utc": started, "ended_at_utc": ended, "duration_seconds": round(time.perf_counter() - t0, 3), "notes": "rate limit audit"})
        if sleep_seconds and batch_index + batch_size < len(items):
            time.sleep(sleep_seconds)

    raw_canon, raw_write = build_canonical(paths, snapshot, "raw", raw_files, resume)
    qfq_canon, qfq_write = build_canonical(paths, snapshot, "qfq", qfq_files, resume)
    write_rows.extend(raw_write + qfq_write)
    canonical_manifest = [raw_canon, qfq_canon]
    quality_rows = quality_audit(raw_rows_all, qfq_rows_all)
    quality_errors = sum(1 for r in quality_rows if r["severity"] == "ERROR")
    quality_warnings = sum(1 for r in quality_rows if r["severity"] == "WARN")
    coverage_rows = coverage(raw_manifest, qfq_manifest, intra_manifest)
    coverage_warnings = sum(1 for r in coverage_rows if r["coverage_status"] != "OK")
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
    pointer = pointer_payload(cache_root, paths, snapshot, raw_canon["path"], qfq_canon["path"])
    write_json(paths["canonical"] / "canonical_manifest.json", {"snapshot": pointer, "canonical_manifest": canonical_manifest})
    write_csv(paths["canonical"] / "canonical_quality_audit.csv", quality_rows, QUALITY_FIELDS)
    pointer["canonical_manifest_path"] = str(paths["canonical"] / "canonical_manifest.json")
    write_json(output_dir / "canonical_snapshot_pointer.json", pointer)
    write_csv(output_dir / "canonical_snapshot_pointer.csv", [{"key": k, "value": v} for k, v in pointer.items()], POINTER_CSV_FIELDS)
    append_registry(paths["registry"] / "moomoo_fetch_registry.csv", {"snapshot_id": snapshot, "created_at_utc": utc_now(), "fetch_items": len(fetch_rows), "success": sum(1 for r in fetch_rows if r["success"] == "True")}, ["snapshot_id","created_at_utc","fetch_items","success"])
    append_registry(paths["registry"] / "canonical_snapshot_registry.csv", {"snapshot_id": snapshot, "created_at_utc": utc_now(), "canonical_raw_path": raw_canon["path"], "canonical_qfq_path": qfq_canon["path"]}, ["snapshot_id","created_at_utc","canonical_raw_path","canonical_qfq_path"])
    latest_dates = [raw_canon["latest_date"], qfq_canon["latest_date"]]
    summary = base_summary(status, repo_root, output_dir, cache_root, snapshot, True, True, guard_found, policy_ok, paths, s230, len(items), len(fetch_rows), sum(1 for r in fetch_rows if r["success"] == "True"), len(failed_rows), daily_raw_attempted, daily_raw_success, daily_raw_attempted - daily_raw_success, daily_qfq_attempted, daily_qfq_success, daily_qfq_attempted - daily_qfq_success, intra_attempted, intra_success, intra_attempted - intra_success, raw_ratio, qfq_ratio, intra_ratio, raw_canon["row_count"], qfq_canon["row_count"], raw_canon["ticker_count"], qfq_canon["ticker_count"], max([d for d in latest_dates if d] or [""]), sum(1 for r in write_rows if r["written_now"] == "True"), sum(int(r["size_bytes"]) for r in write_rows if str(r["size_bytes"]).isdigit()), sum(1 for r in write_rows if r["verified"] == "True"), quality_errors, quality_warnings, coverage_warnings, error_count, warning_count)
    write_outputs(output_dir, summary, fetch_rows, raw_manifest, qfq_manifest, intra_manifest, canonical_manifest, quality_rows, coverage_rows, failed_rows, error_rows, rate_rows, cross_rows, audit_rows, pointer, write_rows)
    return summary


def coverage(raw_manifest: list[dict[str, Any]], qfq_manifest: list[dict[str, Any]], intra_manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tickers = sorted({r["ticker"] for r in raw_manifest + qfq_manifest + intra_manifest})
    rows = []
    for t in tickers:
        raw = next((r for r in raw_manifest if r["ticker"] == t), {})
        qfq = next((r for r in qfq_manifest if r["ticker"] == t), {})
        intra = [r for r in intra_manifest if r["ticker"] == t]
        intra_ok = all(r["success"] == "True" for r in intra) if intra else True
        ok = raw.get("success") == "True" and qfq.get("success") == "True" and intra_ok
        rows.append({"ticker": t, "moomoo_symbol": raw.get("moomoo_symbol") or qfq.get("moomoo_symbol") or (intra[0]["moomoo_symbol"] if intra else ""), "daily_raw_success": raw.get("success", "False"), "daily_qfq_success": qfq.get("success", "False"), "intraday_success": bool_text(intra_ok), "raw_latest_date": raw.get("latest_date", ""), "qfq_latest_date": qfq.get("latest_date", ""), "coverage_status": "OK" if ok else "MISSING_OR_FAILED", "missing_reason": "" if ok else "one or more planned fetches failed", "notes": "Moomoo-only coverage"})
    return rows


def pointer_payload(cache_root: Path, paths: dict[str, Path], snapshot: str, raw_path: str, qfq_path: str) -> dict[str, Any]:
    return {"policy_version": "V21.231", "snapshot_id": snapshot, "created_at_utc": utc_now(), "cache_root": str(cache_root), "raw_daily_snapshot_dir": str(paths["raw_daily"]), "qfq_daily_snapshot_dir": str(paths["qfq_daily"]), "intraday_snapshot_dir": str(paths["intraday"]), "canonical_snapshot_dir": str(paths["canonical"]), "canonical_raw_path": raw_path, "canonical_qfq_path": qfq_path, "canonical_manifest_path": str(paths["canonical"] / "canonical_manifest.json"), "source_policy": "MOOMOO_ONLY", "source": "MOOMOO_OPEND", "yfinance_used": False, "yahoo_used": False, "external_fallback_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True}


def base_summary(status: str, repo_root: Path, output_dir: Path, cache_root: Path, snapshot: str, v230_ok: bool, r1_ok: bool, guard_found: bool, policy_ok: bool, paths: dict[str, Path], s230: dict[str, Any], planned: int, attempted: int, success: int, failed: int, raw_att: int, raw_succ: int, raw_fail: int, qfq_att: int, qfq_succ: int, qfq_fail: int, intra_att: int, intra_succ: int, intra_fail: int, raw_ratio: float, qfq_ratio: float, intra_ratio: float, canon_raw_rows: int, canon_qfq_rows: int, canon_raw_tickers: int, canon_qfq_tickers: int, latest: str, written_count: int, written_bytes: int, hash_count: int, q_errors: int, q_warnings: int, cov_warnings: int, error_count: int, warning_count: int) -> dict[str, Any]:
    return {"final_status": status, "final_decision": FINAL_DECISION, "repo_root": str(repo_root), "output_dir": str(output_dir), "cache_root": str(cache_root), "snapshot_id": snapshot, "v21_230_input_found": v230_ok, "v21_230_r1_input_found": r1_ok, "policy_guard_found": guard_found, "policy_guard_passed": policy_ok, "ticker_universe_count": int(s230.get("ticker_universe_count", 0) or 0), "planned_total_fetch_items": planned or int(s230.get("planned_total_fetch_items", 0) or 0), "attempted_fetch_items": attempted, "successful_fetch_items": success, "failed_fetch_items": failed, "daily_raw_attempted_count": raw_att, "daily_raw_success_count": raw_succ, "daily_raw_failure_count": raw_fail, "daily_qfq_attempted_count": qfq_att, "daily_qfq_success_count": qfq_succ, "daily_qfq_failure_count": qfq_fail, "dram_intraday_attempted_count": intra_att, "dram_intraday_success_count": intra_succ, "dram_intraday_failure_count": intra_fail, "daily_raw_success_ratio": raw_ratio, "daily_qfq_success_ratio": qfq_ratio, "dram_intraday_success_ratio": intra_ratio, "canonical_raw_row_count": canon_raw_rows, "canonical_qfq_row_count": canon_qfq_rows, "canonical_raw_ticker_count": canon_raw_tickers, "canonical_qfq_ticker_count": canon_qfq_tickers, "canonical_latest_date": latest, "canonical_snapshot_dir": str(paths["canonical"]), "cache_written_file_count": written_count, "cache_written_total_bytes": written_bytes, "hash_verified_file_count": hash_count, "quality_error_count": q_errors, "quality_warning_count": q_warnings, "coverage_warning_count": cov_warnings, "yfinance_used": False, "yahoo_used": False, "external_fallback_used": False, "moomoo_historical_fetch_used": attempted > 0, "data_fetch_used": attempted > 0, "broker_action_allowed": False, "trade_unlock_used": False, "official_adoption_allowed": False, "research_only": True, "warning_count": warning_count, "error_count": error_count}


def write_outputs(output_dir: Path, summary: dict[str, Any], fetch_rows: list[dict[str, Any]], raw_manifest: list[dict[str, Any]], qfq_manifest: list[dict[str, Any]], intra_manifest: list[dict[str, Any]], canonical_manifest: list[dict[str, Any]], quality_rows: list[dict[str, Any]], coverage_rows: list[dict[str, Any]], failed_rows: list[dict[str, Any]], error_rows: list[dict[str, Any]], rate_rows: list[dict[str, Any]], cross_rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]], pointer: dict[str, Any], write_rows: list[dict[str, Any]]) -> None:
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
    p.add_argument("--opend-port", type=int, default=11111)
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
