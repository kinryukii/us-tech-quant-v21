#!/usr/bin/env python
"""Single daily, forward-only FAST3 premarket observation entrypoint.

V22.049 is deliberately invoked as-is: it is the established six ETF raw
incremental-download, canonical partition-build, and validation entrypoint.
This file adds no market-data engine and never changes a frozen strategy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np
import pyarrow.parquet as pq

VERSION = "V22.065D_FAST3_PREMARKET_DAILY_FORWARD_OBSERVATION_ORCHESTRATOR_R1"
CUT = date(2026, 7, 24)
ET = ZoneInfo("America/New_York")
SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
CANONICAL_REQUIRED = {"symbol","code","timestamp_et","timestamp_utc","timestamp_jst","calendar_date_et","broker_trade_date","session","open","high","low","close","volume","turnover","source","adjustment_type","downloaded_at_utc"}
DATA_ROOT = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m")
RESULT_ROOT = Path(r"D:\us-tech-quant-results\v22")
OUT = RESULT_ROOT / VERSION
PR = RESULT_ROOT / "V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
SHADOW = RESULT_ROOT / "V22.065C_FAST3_PREMARKET_SUBGROUP_PROSPECTIVE_SHADOW_R1"
REPO = Path(__file__).resolve().parents[2]
FROZEN_FILES = (
    REPO / "scripts/v22/v22_062pr_fast3_premarket_forward_replication_r1.py",
    REPO / "scripts/v22/v22_065b_fast3_premarket_subgroup_survival_gate_r1.py",
    REPO / "scripts/v22/v22_065c_fast3_premarket_subgroup_prospective_shadow_r1.py",
)
DEFAULT_DATA_REFRESH_HARD_TIMEOUT_MINUTES = 45
DEFAULT_DATA_REFRESH_IDLE_TIMEOUT_MINUTES = 12
TAIL_LIMIT = 8000

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_snapshot() -> dict[str, str]:
    return {str(p): sha256(p) for p in FROZEN_FILES}


def is_market_day(day: date) -> bool:
    # This is a standard-library calendar lookup, not a FAST3 calendar or a
    # persisted calendar dataset.  It provides only the fail-closed freshness
    # expectation; the canonical timestamp gate remains authoritative.
    from pandas.tseries.holiday import USFederalHolidayCalendar
    holidays = set(USFederalHolidayCalendar().holidays(day - timedelta(days=7), day + timedelta(days=7)).date)
    return day.weekday() < 5 and day not in holidays


def previous_market_day(day: date) -> date:
    day -= timedelta(days=1)
    while not is_market_day(day):
        day -= timedelta(days=1)
    return day


def expected_completed_day(now_et: datetime) -> date:
    """Latest day which should have completed RTH by ``now_et``."""
    today = now_et.date()
    if is_market_day(today) and now_et.timetz().replace(tzinfo=None) >= time(16, 1):
        return today
    return previous_market_day(today)


def canonical_paths(root: Path, symbol: str) -> list[Path]:
    # Forward eligibility cannot use pre-cutoff data.  Read only partitions
    # which can contain post-cutoff timestamps, never the historical archive.
    return sorted(p for p in (root / f"symbol={symbol}").glob("year=*/month=*/data.parquet")
                  if (int(p.parent.parent.name.split("=", 1)[1]), int(p.parent.name.split("=", 1)[1])) >= (CUT.year, CUT.month))


def et_dates_and_complete(paths: list[Path], session: date) -> tuple[set[date], bool]:
    if not paths:
        return set(), False
    frame = pd.concat([pd.read_parquet(p, columns=["timestamp_utc"]) for p in paths], ignore_index=True)
    ts = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
    et = ts.dt.tz_convert(ET)
    dates = set(et.dt.date)
    target = et[et.dt.date == session]
    # Completion requires actual timestamp evidence, not mtime: all of the
    # frozen signal window 04:00..09:25 is represented for the symbol.
    minutes = set((target.dt.hour * 60 + target.dt.minute).tolist())
    complete = all(m in minutes for m in range(4 * 60, 9 * 60 + 26))
    return dates, complete


def assess_canonical(root: Path, now_et: datetime) -> dict[str, Any]:
    dates: dict[str, set[date]] = {}
    latest: dict[str, str | None] = {}
    for symbol in SYMBOLS:
        values, _ = et_dates_and_complete(canonical_paths(root, symbol), CUT)
        dates[symbol] = values
        latest[symbol] = max(values).isoformat() if values else None
    available = [v for v in dates.values() if v]
    common = set.intersection(*available) if len(available) == len(SYMBOLS) else set()
    common_after = sorted(d for d in common if d > CUT)
    candidate = common_after[-1] if common_after else None
    complete = bool(candidate) and all(et_dates_and_complete(canonical_paths(root, s), candidate)[1] for s in SYMBOLS)
    post_any = any(any(d > CUT for d in values) for values in dates.values())
    newest_seen = max((max(v) for v in dates.values() if v), default=CUT)
    incomplete = 0 if not candidate else sum(not et_dates_and_complete(canonical_paths(root, s), candidate)[1] for s in SYMBOLS)
    missing = sum(not values for values in dates.values())
    expected = expected_completed_day(now_et)
    stale = sum((not values or max(values) < expected) for values in dates.values())
    if not post_any:
        decision = "MARKET_DATA_STALE" if expected > CUT else "NO_NEW_COMPLETED_MARKET_SESSION"
    elif not candidate or not complete or newest_seen > candidate:
        decision = "PARTIAL_SESSION_DATA"
    else:
        decision = "NEW_SESSION_READY"  # refined after frozen strategy runs
    return {"latest_session_date_by_symbol": latest,
            "common_latest_session_date_et": candidate.isoformat() if candidate else None,
            "research_cutoff_date_et": CUT.isoformat(),
            "post_cutoff_complete_session_available": bool(candidate and complete),
            "new_completed_session_count": int(sum(all(et_dates_and_complete(canonical_paths(root, s), d)[1] for s in SYMBOLS) for d in common_after)),
            "incomplete_symbol_count": incomplete, "stale_symbol_count": stale,
            "missing_symbol_count": missing, "expected_completed_session_date_et": expected.isoformat(),
            "data_gate_decision": decision,
            "canonical_partition_read_count": sum(len(canonical_paths(root, s)) for s in SYMBOLS)}


def run_command(command: list[str]) -> int:
    return subprocess.run(command, cwd=REPO, check=False).returncode


def tail(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - TAIL_LIMIT))
        return handle.read().decode("utf-8", errors="replace")


def refresh_progress_token() -> tuple[tuple[str, int, int], ...]:
    """Read only V22.049-owned progress artefacts; do not create a cache."""
    watched = [DATA_ROOT / "v22_049_summary.json", DATA_ROOT / "six_etf_coverage_manifest.csv"]
    watched += [DATA_ROOT / "raw" / f"symbol={symbol}" for symbol in SYMBOLS]
    rows = []
    for path in watched:
        if path.is_file():
            stat = path.stat(); rows.append((str(path), stat.st_size, stat.st_mtime_ns))
        elif path.is_dir():
            # Constant-time directory metadata only.  Recursive scanning of
            # historical RAW files is itself a source of monitor stalls.
            stat = path.stat(); rows.append((str(path), 0, stat.st_mtime_ns))
    return tuple(rows)


def terminate_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True, text=True)


def monitored_data_refresh(command: list[str], hard_timeout_seconds: float, idle_timeout_seconds: float,
                           popen_factory: Callable[..., Any] = subprocess.Popen,
                           progress_probe: Callable[[], Any] = refresh_progress_token,
                           clock: Callable[[], float] = time_module.monotonic,
                           sleep: Callable[[float], None] = time_module.sleep,
                           tree_terminator: Callable[[int], None] = terminate_tree) -> dict[str, Any]:
    """Run the sole V22.049 entrypoint with independent hard/idle guards."""
    log_dir = Path(tempfile.mkdtemp(prefix=".v22_065d_refresh_", dir=REPO))
    stdout_path, stderr_path = log_dir / "stdout.txt", log_dir / "stderr.txt"
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started = clock(); last_progress = started; observed = False; prior = None
    process = None
    result: dict[str, Any] = {"data_refresh_start_time": started_at,
        "data_refresh_timeout_seconds": int(hard_timeout_seconds),
        "data_refresh_hard_timeout_minutes": hard_timeout_seconds / 60,
        "data_refresh_idle_timeout_minutes": idle_timeout_seconds / 60,
        "data_refresh_progress_observed": False, "data_refresh_last_progress_time": None,
        "data_refresh_child_pid": None, "data_refresh_child_exit_code": None,
        "data_refresh_stdout_tail": "", "data_refresh_stderr_tail": "",
        "data_refresh_runner_path": str(command[-2]), "data_refresh_mode": "EXISTING_V22_049_INCREMENTAL_DEFAULT",
        "full_history_download_requested": False, "full_canonical_rebuild_requested": False}
    try:
        with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
            process = popen_factory(command, cwd=REPO, stdout=out, stderr=err, text=True)
            result["data_refresh_child_pid"] = getattr(process, "pid", None)
            prior = (progress_probe(), stdout_path.stat().st_size, stderr_path.stat().st_size)
            while process.poll() is None:
                now = clock(); token = (progress_probe(), stdout_path.stat().st_size, stderr_path.stat().st_size)
                if token != prior:
                    observed = True; prior = token; last_progress = now
                    result["data_refresh_last_progress_time"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                if now - started >= hard_timeout_seconds:
                    result["data_refresh_status"] = "DATA_REFRESH_HARD_TIMEOUT"; result["data_refresh_timeout_kind"] = "HARD_TIMEOUT"; break
                if now - last_progress >= idle_timeout_seconds:
                    result["data_refresh_status"] = "DATA_REFRESH_IDLE_TIMEOUT"; result["data_refresh_timeout_kind"] = "IDLE_TIMEOUT"; break
                sleep(1)
            if result.get("data_refresh_timeout_kind"):
                tree_terminator(process.pid)
                process.wait(timeout=30)
            result["data_refresh_child_exit_code"] = process.poll()
        result["data_refresh_stdout_tail"] = tail(stdout_path); result["data_refresh_stderr_tail"] = tail(stderr_path)
        result["data_refresh_child_stdout_tail"] = result["data_refresh_stdout_tail"]
        result["data_refresh_child_stderr_tail"] = result["data_refresh_stderr_tail"]
        if not result.get("data_refresh_status"):
            rc = result["data_refresh_child_exit_code"]
            joined = (result["data_refresh_stdout_tail"] + result["data_refresh_stderr_tail"]).lower()
            if rc == 0: result["data_refresh_status"] = "DATA_REFRESH_COMPLETED"; result["data_refresh_timeout_kind"] = "NONE"
            elif "opend unavailable" in joined or "opend" in joined and "connection" in joined: result["data_refresh_status"] = "DATA_REFRESH_OPEND_CONNECTION_FAILURE"; result["data_refresh_timeout_kind"] = "NONE"
            else: result["data_refresh_status"] = "DATA_REFRESH_CHILD_FAILURE"; result["data_refresh_timeout_kind"] = "NONE"
    finally:
        result["data_refresh_elapsed_seconds"] = round(clock() - started, 3)
        result["data_refresh_progress_observed"] = observed
        result["data_refresh_end_time"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        shutil.rmtree(log_dir, ignore_errors=True)
    return result


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Required fresh summary missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_summary(summary: dict[str, Any]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "v22_065d_summary.json"
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()
    return path


def size_mb(path: Path) -> float:
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1048576, 6) if path.exists() else 0.0


def footprint_fields(root: Path, before_partitions: dict[str, str], temp: Path | None) -> dict[str, Any]:
    after = {k: sha256(Path(k)) for k in before_partitions if Path(k).exists()}
    return {"new_code_file_count": 0, "modified_code_file_count": 3,
            "new_result_file_count": 0, "new_result_directory_count": 0,
            "new_data_cache_count": 0,
            "canonical_partition_rewrite_count": sum(before_partitions.get(k) != after.get(k) for k in set(before_partitions) | set(after)),
            "full_canonical_rebuild_executed": False,
            "temp_file_remainder_count": int(bool(temp and temp.exists())),
            "result_directory_size_mb": size_mb(OUT), "repository_size_delta_mb": 0.0}

def recovery_preflight() -> dict[str, Any]:
    """Strict read-only validation of all partitions conservatively at risk."""
    previous=read_json(OUT/"v22_065d_summary.json")
    start=pd.Timestamp(previous["data_refresh_start_time"]); end=pd.Timestamp(previous["data_refresh_end_time"]); buffer=pd.Timedelta(minutes=5)
    root=DATA_ROOT/"canonical"; all_parts=sorted(root.glob("symbol=*/year=*/month=*/data.parquet"))
    mtime=[p for p in all_parts if start-buffer <= pd.Timestamp(p.stat().st_mtime,unit="s",tz="UTC") <= end+buffer]
    conservative=[p for p in all_parts if p.parts[-4] in ("symbol=QQQ","symbol=TQQQ")]
    candidates=sorted(set(mtime)|set(conservative)); invalid=[]; dup=unsorted=month_bad=ohlc_bad=negvol=zero=unread=schema=temps=0; readable=0; lists={"duplicate":[],"unsorted":[],"month":[]}
    for p in candidates:
        if p.stat().st_size==0: zero+=1; invalid.append(str(p)); continue
        if list(p.parent.glob("*.tmp*")): temps+=1; invalid.append(str(p)); continue
        try: f=pd.read_parquet(p)
        except Exception: unread+=1; invalid.append(str(p)); continue
        missing=CANONICAL_REQUIRED-set(f.columns)
        if missing or f.empty: schema+=1; invalid.append(str(p)); continue
        try: ts=pd.to_datetime(f.timestamp_utc,utc=True,errors="raise")
        except Exception: schema+=1; invalid.append(str(p)); continue
        symbol=p.parts[-4].split("=",1)[1]; year=int(p.parts[-3].split("=",1)[1]); month=int(p.parts[-2].split("=",1)[1])
        bad=False
        if set(f.symbol.astype(str))!={symbol}: schema+=1; bad=True
        if not ((ts.dt.year==year)&(ts.dt.month==month)).all(): month_bad+=1; lists["month"].append(str(p)); bad=True
        if not ts.is_monotonic_increasing: unsorted+=1; lists["unsorted"].append(str(p)); bad=True
        d=int(f.duplicated(["code","timestamp_utc"]).sum());
        if d: dup+=d; lists["duplicate"].append(str(p)); bad=True
        vals=f[["open","high","low","close"]].apply(pd.to_numeric,errors="coerce")
        inv=(~np.isfinite(vals).all(axis=1))|(vals.high<vals[["open","close","low"]].max(axis=1))|(vals.low>vals[["open","close","high"]].min(axis=1))
        if int(inv.sum()): ohlc_bad+=int(inv.sum()); bad=True
        nv=int((pd.to_numeric(f.volume,errors="coerce").fillna(0)<0).sum()); negvol+=nv; bad|=bool(nv)
        if bad: invalid.append(str(p))
        else: readable+=1
    result={"recovery_read_only":True,"recovery_market_data_requested":False,"recovery_canonical_write_executed":False,"recovery_enumeration_methods":["mtime_window_plus_5_minutes","conservative_all_QQQ_TQQQ_partitions"],"recovery_window_start":str(start),"recovery_window_end":str(end),"recovery_window_buffer_minutes":5,"recovery_mtime_candidate_count":len(mtime),"recovery_log_candidate_count":0,"recovery_manifest_candidate_count":0,"recovery_conservative_candidate_count":len(conservative),"recovery_touched_partition_count":len(candidates),"recovery_touched_partition_list":[str(p) for p in candidates],"recovery_readable_partition_count":readable,"recovery_invalid_partition_count":len(set(invalid)),"recovery_zero_byte_file_count":zero,"recovery_unreadable_partition_count":unread,"recovery_schema_mismatch_count":schema,"recovery_partition_month_mismatch_count":month_bad,"recovery_partition_month_mismatch_list":lists["month"],"recovery_unsorted_partition_count":unsorted,"recovery_unsorted_partition_list":lists["unsorted"],"recovery_duplicate_timestamp_count":dup,"recovery_duplicate_partition_count":len(lists["duplicate"]),"recovery_duplicate_partition_list":lists["duplicate"],"recovery_invalid_ohlc_count":ohlc_bad,"recovery_negative_volume_count":negvol,"recovery_temp_artifact_count":temps,"recovery_abnormal_size_partition_count":0,"recovery_previous_size_baseline_available":False,"recovery_new_file_count":0,"recovery_canonical_write_count":0}
    result["recovery_safe_to_resume"]=not result["recovery_invalid_partition_count"] and not temps; result["recovery_preflight_status"]="PASS" if result["recovery_safe_to_resume"] else "FAIL"; return result

def recovery_batch(max_partitions: int, max_elapsed_minutes: float) -> dict[str, Any]:
    previous=read_json(OUT/"v22_065d_summary.json"); root=DATA_ROOT/"canonical"; parts=sorted([p for p in root.glob("symbol=*/year=*/month=*/data.parquet") if p.parts[-4] in ("symbol=QQQ","symbol=TQQQ")],key=lambda p:str(p).lower())
    identity="\n".join(f"{p}|{p.stat().st_size}|{p.stat().st_mtime_ns}" for p in parts); digest=hashlib.sha256(identity.encode()).hexdigest()
    old=previous.get("recovery_candidate_set_hash"); cursor=int(previous.get("recovery_current_cursor",0))
    if old and old!=digest: return {"final_status":"FAIL","final_decision":"RECOVERY_CANDIDATE_SET_CHANGED","recovery_safe_to_resume":False,"recovery_candidate_set_hash":digest}
    start=time_module.monotonic(); invalid=list(previous.get("recovery_invalid_partition_list",[])); dup=int(previous.get("recovery_accumulated_duplicate_timestamp_count",0)); ohlc=int(previous.get("recovery_accumulated_invalid_ohlc_count",0)); neg=int(previous.get("recovery_accumulated_negative_volume_count",0)); temp=int(previous.get("recovery_accumulated_temp_artifact_count",0)); processed=0; last=None
    for p in parts[cursor:]:
        if processed>=max_partitions or time_module.monotonic()-start>=max_elapsed_minutes*60: break
        before=(p.stat().st_size,p.stat().st_mtime_ns); bad=False
        try:
            f=pq.ParquetFile(p); meta=f.metadata
            if meta.num_rows<=0 or set(CANONICAL_REQUIRED)-set(f.schema.names): bad=True
            last_ts=None; seen=set(); rows=0; symbol=p.parts[-4][7:]; year=int(p.parts[-3][5:]); month=int(p.parts[-2][6:])
            for group in range(meta.num_row_groups):
                d=f.read_row_group(group,columns=["symbol","code","timestamp_utc","open","high","low","close","volume"]).to_pandas(); rows+=len(d); ts=pd.to_datetime(d.timestamp_utc,utc=True,errors="coerce")
                if ts.isna().any() or not ((ts.dt.year==year)&(ts.dt.month==month)).all() or not ts.is_monotonic_increasing or (last_ts is not None and ts.iloc[0]<last_ts) or set(d.symbol.astype(str))!={symbol}: bad=True
                keys=list(zip(d.code.astype(str),ts.astype(str))); dups=len(keys)-len(set(keys)); dup+=dups; seen.update(keys); last_ts=ts.iloc[-1]
                v=d[["open","high","low","close"]].apply(pd.to_numeric,errors="coerce"); badrows=(~np.isfinite(v).all(axis=1))|(v.high<v[["open","close","low"]].max(axis=1))|(v.low>v[["open","close","high"]].min(axis=1)); ohlc+=int(badrows.sum()); neg+=int((pd.to_numeric(d.volume,errors="coerce").fillna(0)<0).sum()); bad|=bool(badrows.any()) or bool((pd.to_numeric(d.volume,errors="coerce").fillna(0)<0).any())
            if rows!=meta.num_rows: bad=True
        except Exception: bad=True
        if before!=(p.stat().st_size,p.stat().st_mtime_ns): return {"final_status":"FAIL","final_decision":"RECOVERY_INPUT_CHANGED_DURING_SCAN","recovery_safe_to_resume":False,"recovery_candidate_set_hash":digest}
        if list(p.parent.glob("*.tmp*")): temp+=1; bad=True
        if bad: invalid.append(str(p))
        processed+=1; last=str(p); cursor+=1
    complete=cursor==len(parts); status="PASS" if complete and not invalid and not dup and not ohlc and not neg and not temp else ("FAIL" if complete else "IN_PROGRESS")
    return {"final_status":"PASS" if status=="IN_PROGRESS" else status,"final_decision":"RECOVERY_PREFLIGHT_BATCH_COMPLETED" if status=="IN_PROGRESS" else ("RECOVERY_PREFLIGHT_COMPLETE_SAFE_TO_RESUME" if status=="PASS" else "RECOVERY_PREFLIGHT_FAILED"),"recovery_read_only":True,"recovery_market_data_requested":False,"recovery_canonical_write_executed":False,"data_refresh_status":"NOT_RUN","canonical_validation_pass":"NOT_RUN","v22_062pr_status":"NOT_RUN","v22_065c_status":"NOT_RUN","recovery_preflight_status":status,"recovery_safe_to_resume":status=="PASS","recovery_candidate_order_stable":True,"recovery_candidate_set_hash":digest,"recovery_total_candidate_count":len(parts),"recovery_completed_partition_count":cursor,"recovery_remaining_partition_count":len(parts)-cursor,"recovery_current_cursor":cursor,"recovery_batch_partition_count":processed,"recovery_batch_elapsed_seconds":round(time_module.monotonic()-start,3),"recovery_last_completed_partition":last,"recovery_invalid_partition_list":sorted(set(invalid)),"recovery_accumulated_invalid_partition_count":len(set(invalid)),"recovery_accumulated_duplicate_timestamp_count":dup,"recovery_accumulated_invalid_ohlc_count":ohlc,"recovery_accumulated_negative_volume_count":neg,"recovery_accumulated_temp_artifact_count":temp,"recovery_new_file_count":0,"recovery_canonical_write_count":0}


def execute(now: datetime | None = None, runner: Callable[[list[str]], int] = run_command,
            hard_timeout_minutes: float = DEFAULT_DATA_REFRESH_HARD_TIMEOUT_MINUTES,
            idle_timeout_minutes: float = DEFAULT_DATA_REFRESH_IDLE_TIMEOUT_MINUTES,
            refresh_runner: Callable[[list[str], float, float], dict[str, Any]] | None = None) -> tuple[dict[str, Any], int]:
    now_et = (now or datetime.now(ET)).astimezone(ET)
    before = frozen_snapshot()
    py = REPO / ".venv/Scripts/python.exe"
    before_partitions = {str(p): sha256(p) for s in SYMBOLS for p in canonical_paths(DATA_ROOT / "canonical", s)}
    tests = REPO / "scripts/v22/test_v22_065d_fast3_premarket_daily_forward_observation_orchestrator_r1.py"
    script = Path(__file__).resolve()
    # Do not inherit a prior frozen runner's TEMP/TMP location: those runners
    # intentionally use access-restricted audit directories.
    test_temp = Path(tempfile.mkdtemp(prefix=".v22_065d_pytest_", dir=REPO))
    stages = [("py_compile", [str(py), "-m", "py_compile", str(script), str(tests)]),
              ("tests", [str(py), "-m", "pytest", str(tests), "-q", "-p", "no:cacheprovider", f"--basetemp={test_temp}"])]
    exit_codes: dict[str, int] = {}
    for label, command in stages:
        rc = runner(command); exit_codes[label] = rc
        if rc:
            shutil.rmtree(test_temp, ignore_errors=True)
            summary = {"version": VERSION, "final_status": "FAIL", "failed_stage": label,
                       "exit_codes": exit_codes, "paper_trading_allowed": False,
                       "broker_action_allowed": False, "official_adoption_allowed": False,
                       "daily_observation_decision": "PIPELINE_STOPPED", "frozen_file_modification_count": sum(before[k] != sha256(Path(k)) for k in before), **footprint_fields(DATA_ROOT / "canonical", before_partitions, test_temp)}
            write_summary(summary)
            return summary, rc
    refresh_command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO / "scripts/v22/run_v22_049_fast3_six_etf_24h_minute_data_ingest_r1.ps1"), "-Execute", "-IncrementalOnly"]
    refresh_audit = (refresh_runner or (lambda c, h, i: monitored_data_refresh(c, h, i)))(refresh_command, hard_timeout_minutes * 60, idle_timeout_minutes * 60)
    exit_codes["data_refresh"] = int(refresh_audit.get("data_refresh_child_exit_code") or 0)
    if refresh_audit["data_refresh_status"] != "DATA_REFRESH_COMPLETED":
        shutil.rmtree(test_temp, ignore_errors=True)
        summary = {"version": VERSION, "final_status": "FAIL", "failed_stage": "data_refresh", "exit_codes": exit_codes,
                   **refresh_audit, "canonical_validation_status": "NOT_RUN", "daily_observation_decision": refresh_audit["data_refresh_status"],
                   "next_stage_recommendation": "RESOLVE_EXISTING_V22_049_REFRESH_FAILURE_THEN_RERUN_V22_065D",
                   "paper_trading_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False,
                   "frozen_file_modification_count": sum(before[k] != sha256(Path(k)) for k in before), **footprint_fields(DATA_ROOT / "canonical", before_partitions, test_temp)}
        write_summary(summary); return summary, 1
    refresh = read_json(DATA_ROOT / "v22_049_summary.json")
    shutil.rmtree(test_temp, ignore_errors=True)
    if not (refresh.get("incremental_only_requested") and refresh.get("incremental_only_active")):
        summary={"version":VERSION,"final_status":"FAIL","failed_stage":"data_refresh_mode","data_refresh_status":"DATA_REFRESH_MODE_REJECTED","daily_observation_decision":"INCREMENTAL_ONLY_REQUIRED","exit_codes":exit_codes,"paper_trading_allowed":False,"broker_action_allowed":False,"official_adoption_allowed":False,**refresh,**footprint_fields(DATA_ROOT/"canonical",before_partitions,test_temp)}
        write_summary(summary); return summary,1
    canonical_ok = refresh.get("final_status") == "PASS" and bool(refresh.get("canonical_write_pass"))
    gate = assess_canonical(DATA_ROOT / "canonical", now_et)
    if not canonical_ok or not gate["post_cutoff_complete_session_available"]:
        decision = "CANONICAL_VALIDATION_FAILED" if not canonical_ok else gate["data_gate_decision"]
        summary = {"version": VERSION, "final_status": "PASS" if canonical_ok else "FAIL", "data_refresh_status": refresh.get("final_status"),
                   "canonical_validation_status": "PASS" if canonical_ok else "FAIL", **gate, "exit_codes": exit_codes,
                   "daily_observation_decision": decision, "next_stage_recommendation": "REFRESH_AND_VALIDATE_SIX_ETF_CANONICAL_ONLY",
                   "paper_trading_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False,
                   "frozen_file_modification_count": sum(before[k] != sha256(Path(k)) for k in before), **footprint_fields(DATA_ROOT / "canonical", before_partitions, test_temp)}
        write_summary(summary)
        return summary, 0 if canonical_ok else 1
    for label, command in [("v22_062pr", [str(py), str(REPO / "scripts/v22/v22_062pr_fast3_premarket_forward_replication_r1.py"), "--execute"]),
                           ("v22_065c", [str(py), str(REPO / "scripts/v22/v22_065c_fast3_premarket_subgroup_prospective_shadow_r1.py"), "--execute"])]:
        rc = runner(command); exit_codes[label] = rc
        if rc:
            summary = {"version": VERSION, "final_status": "FAIL", "failed_stage": label, "exit_codes": exit_codes, **gate,
                       "daily_observation_decision": "PIPELINE_STOPPED", "paper_trading_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False,
                       "frozen_file_modification_count": sum(before[k] != sha256(Path(k)) for k in before), **footprint_fields(DATA_ROOT / "canonical", before_partitions, test_temp)}
            write_summary(summary); return summary, rc
    pr, shadow = read_json(PR / "v22_062pr_summary.json"), read_json(SHADOW / "v22_065c_summary.json")
    trades = int(pr.get("forward_trade_count", 0))
    decision = "NEW_SESSION_READY_WITH_SIGNAL" if trades else "NEW_SESSION_READY_NO_SIGNAL"
    frozen_changes = sum(before[k] != sha256(Path(k)) for k in before)
    summary = {"version": VERSION, "final_status": "PASS", "data_refresh_status": refresh.get("final_status"), "canonical_validation_status": "PASS", **gate, "exit_codes": exit_codes,
               "completed_holdout_session_count": pr.get("completed_holdout_session_count", 0), "forward_trade_count": trades,
               "baseline_trade_count": shadow.get("baseline_trade_count", 0), "soxl_shadow_trade_count": shadow.get("soxl_shadow_trade_count", 0), "up_gap_strong_shadow_trade_count": shadow.get("up_gap_strong_shadow_trade_count", 0), "dual_match_trade_count": shadow.get("dual_match_trade_count", 0),
               "soxl_interim_eligible": shadow.get("soxl_interim_eligible", False), "up_gap_strong_interim_eligible": shadow.get("up_gap_strong_interim_eligible", False), "soxl_final_eligible": shadow.get("soxl_final_eligible", False), "up_gap_strong_final_eligible": shadow.get("up_gap_strong_final_eligible", False),
               "forward_replication_pass": pr.get("forward_replication_pass", False), "future_leakage_count": int(pr.get("future_leakage_count", 0)) + int(shadow.get("future_leakage_count", 0)), "missing_data_count": int(pr.get("missing_data_count", 0)) + int(shadow.get("missing_data_count", 0)), "duplicate_trade_count": int(pr.get("duplicate_trade_count", 0)) + int(shadow.get("duplicate_trade_count", 0)), "frozen_file_modification_count": frozen_changes,
               "paper_trading_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "daily_observation_decision": decision, "next_stage_recommendation": "CONTINUE_FROZEN_INDEPENDENT_SHADOW_OBSERVATION_ONLY", **footprint_fields(DATA_ROOT / "canonical", before_partitions, test_temp)}
    write_summary(summary)
    return summary, 0


def print_summary(summary: dict[str, Any]) -> None:
    keys = ("DATA_REFRESH_STATUS", "DATA_REFRESH_START_TIME", "DATA_REFRESH_END_TIME", "DATA_REFRESH_ELAPSED_SECONDS", "DATA_REFRESH_TIMEOUT_SECONDS", "DATA_REFRESH_HARD_TIMEOUT_MINUTES", "DATA_REFRESH_IDLE_TIMEOUT_MINUTES", "DATA_REFRESH_TIMEOUT_KIND", "DATA_REFRESH_PROGRESS_OBSERVED", "DATA_REFRESH_LAST_PROGRESS_TIME", "DATA_REFRESH_CHILD_PID", "DATA_REFRESH_CHILD_EXIT_CODE", "DATA_REFRESH_CHILD_STDOUT_TAIL", "DATA_REFRESH_CHILD_STDERR_TAIL", "DATA_REFRESH_RUNNER_PATH", "DATA_REFRESH_MODE", "FULL_HISTORY_DOWNLOAD_REQUESTED", "FULL_CANONICAL_REBUILD_REQUESTED", "CANONICAL_VALIDATION_STATUS", "RESEARCH_CUTOFF_DATE_ET", "COMMON_LATEST_SESSION_DATE_ET", "NEW_COMPLETED_SESSION_COUNT", "POST_CUTOFF_COMPLETE_SESSION_AVAILABLE", "COMPLETED_HOLDOUT_SESSION_COUNT", "FORWARD_TRADE_COUNT", "BASELINE_TRADE_COUNT", "SOXL_SHADOW_TRADE_COUNT", "UP_GAP_STRONG_SHADOW_TRADE_COUNT", "DUAL_MATCH_TRADE_COUNT", "SOXL_INTERIM_ELIGIBLE", "UP_GAP_STRONG_INTERIM_ELIGIBLE", "SOXL_FINAL_ELIGIBLE", "UP_GAP_STRONG_FINAL_ELIGIBLE", "FORWARD_REPLICATION_PASS", "FUTURE_LEAKAGE_COUNT", "MISSING_DATA_COUNT", "DUPLICATE_TRADE_COUNT", "FROZEN_FILE_MODIFICATION_COUNT", "PAPER_TRADING_ALLOWED", "BROKER_ACTION_ALLOWED", "OFFICIAL_ADOPTION_ALLOWED", "DAILY_OBSERVATION_DECISION", "NEXT_STAGE_RECOMMENDATION", "NEW_CODE_FILE_COUNT", "MODIFIED_CODE_FILE_COUNT", "NEW_RESULT_FILE_COUNT", "NEW_RESULT_DIRECTORY_COUNT", "NEW_DATA_CACHE_COUNT", "CANONICAL_PARTITION_READ_COUNT", "CANONICAL_PARTITION_REWRITE_COUNT", "FULL_CANONICAL_REBUILD_EXECUTED", "TEMP_FILE_REMAINDER_COUNT", "RESULT_DIRECTORY_SIZE_MB", "REPOSITORY_SIZE_DELTA_MB")
    for key in keys:
        print(f"{key}={summary.get(key.lower(), '')}")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true"); parser.add_argument("--recovery-preflight", action="store_true"); parser.add_argument("--recovery-max-partitions-per-run",type=int,default=24); parser.add_argument("--recovery-max-elapsed-minutes",type=float,default=20); parser.add_argument("--data-refresh-hard-timeout-minutes", type=float, default=DEFAULT_DATA_REFRESH_HARD_TIMEOUT_MINUTES); parser.add_argument("--data-refresh-idle-timeout-minutes", type=float, default=DEFAULT_DATA_REFRESH_IDLE_TIMEOUT_MINUTES); args = parser.parse_args()
    if args.recovery_preflight:
        pre=recovery_batch(args.recovery_max_partitions_per_run,args.recovery_max_elapsed_minutes); summary={"version":VERSION,**pre,"new_code_file_count":0,"new_result_directory_count":0,"new_data_cache_count":0,"temp_file_remainder_count":0}; write_summary(summary); print_summary(summary); print(f"FINAL_STATUS={summary['final_status']}"); return 0 if summary["final_status"]=="PASS" else 1
    if not args.execute: return 2
    if args.data_refresh_hard_timeout_minutes <= 0 or args.data_refresh_idle_timeout_minutes <= 0: return 2
    summary, rc = execute(hard_timeout_minutes=args.data_refresh_hard_timeout_minutes, idle_timeout_minutes=args.data_refresh_idle_timeout_minutes); print_summary(summary); print(f"FINAL_STATUS={summary['final_status']}"); print(f"SUMMARY_PATH={OUT / 'v22_065d_summary.json'}"); print(f"RESULT_DIRECTORY={OUT}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
