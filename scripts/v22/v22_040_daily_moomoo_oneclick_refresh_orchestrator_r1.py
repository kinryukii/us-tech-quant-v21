#!/usr/bin/env python
"""V22.040 daily Moomoo one-click research refresh orchestrator R1."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import shutil
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


STAGE = "V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1"
OUT_REL = Path("outputs/v22") / STAGE
V231_REL = Path("outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD")
V232_REL = Path("outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN")
V233_REL = Path("outputs/v21/V21.233_MOOMOO_ONLY_ABCDE_RERUN")
V234_REL = Path("outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN")
V256_REL = Path("outputs/v21/V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1")

PASS_STATUS = "PASS_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_COMPLETE"
RUNNING_STATUS = "RUNNING_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_IN_PROGRESS"
RUNNING_DECISION = "DAILY_MOOMOO_REFRESH_IN_PROGRESS_RESEARCH_ONLY"
WARN_TARGET = "WARN_TARGET_DATE_NOT_AVAILABLE_USED_LATEST_COMPLETE_DATE"
FAIL_STATUS = "FAIL_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_BLOCKED"
FAIL_CHILD_SUMMARY_MISSING = "FAIL_V22_040_CHILD_SUMMARY_MISSING"
FAIL_CHILD_NONZERO = "FAIL_V22_040_CHILD_NONZERO_EXIT"
DECISION_READY = "DAILY_MOOMOO_REFRESH_COMPLETE_RESEARCH_ONLY"
DECISION_BLOCKED = "DAILY_MOOMOO_REFRESH_BLOCKED_RESEARCH_ONLY"

CANON_RAW = "canonical_moomoo_ohlcv_daily_raw.csv"
CANON_QFQ = "canonical_moomoo_ohlcv_daily_qfq.csv"
POINTER_FIELDS = ["key", "value"]

StageRunner = Callable[[str, Path, Path], dict[str, Any]]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def previous_weekday(value: date) -> date:
    value = value.fromordinal(value.toordinal() - 1)
    while value.weekday() >= 5:
        value = value.fromordinal(value.toordinal() - 1)
    return value


def latest_expected_completed_us_trading_date(now: datetime | None = None) -> str:
    ny_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    candidate = ny_now.date()
    if candidate.weekday() >= 5:
        return previous_weekday(candidate).isoformat()
    if ny_now.hour < 18:
        return previous_weekday(candidate).isoformat()
    return candidate.isoformat()


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_csv_atomic(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def python_exe(repo_root: Path) -> str:
    local = repo_root / ".venv/Scripts/python.exe"
    return str(local) if local.exists() else "python"


def powershell_exe() -> str:
    return "powershell"


def run_subprocess(cmd: list[str], cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    log_path.write_text(
        (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""),
        encoding="utf-8",
    )
    return proc.returncode


def child_summary_path(repo_root: Path, stage: str) -> Path:
    if stage == "V21.231":
        return repo_root / V231_REL / "v21_231_summary.json"
    if stage == "V21.232":
        return repo_root / V232_REL / "v21_232_summary.json"
    if stage == "V21.233":
        return repo_root / V233_REL / "v21_233_summary.json"
    if stage == "V21.234":
        return repo_root / V234_REL / "v21_234_summary.json"
    if stage == "V21.256":
        return repo_root / V256_REL / "v21_256_summary.json"
    raise ValueError(stage)


def log_path(out: Path, stage: str) -> Path:
    return out / f"{stage.lower().replace('.', '_')}_execute.log"


def child_command(repo_root: Path, stage: str, target_date: str | None, cache_root: Path | None, no_network: bool) -> list[str]:
    if stage == "V21.231":
        cmd = [
            python_exe(repo_root),
            str(repo_root / "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"),
            "--repo-root", str(repo_root),
            "--output-dir", str(repo_root / V231_REL),
            "--end-date", str(target_date or ""),
        ]
        if cache_root is not None:
            cmd.extend(["--cache-root", str(cache_root)])
        if no_network:
            cmd.append("--no-network")
        return cmd
    wrappers = {
        "V21.232": repo_root / "scripts/v21/run_v21_232_moomoo_only_dram_daily_and_intraday_plan.ps1",
        "V21.233": repo_root / "scripts/v21/run_v21_233_moomoo_only_abcde_rerun.ps1",
        "V21.234": repo_root / "scripts/v21/run_v21_234_minimal_moomoo_only_daily_research_chain.ps1",
        "V21.256": repo_root / "scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1",
    }
    cmd = [powershell_exe(), "-ExecutionPolicy", "Bypass", "-File", str(wrappers[stage])]
    if stage == "V21.256":
        cmd.extend(["-RepoRoot", str(repo_root), "-Execute"])
    return cmd


def running_summary(repo_root: Path, out: Path, target_date: str, run_start_utc: str) -> dict[str, Any]:
    return {
        "target_date": target_date,
        "revision": "V22.040_R1A",
        "latest_available_date": "",
        "canonical_snapshot_id": "",
        "canonical_latest_date": "",
        "abcde_latest_date": "",
        "dram_latest_price_date": "",
        "same_date_comparable_all_strategies": False,
        "data_gap_days": 0,
        "final_status": RUNNING_STATUS,
        "final_decision": RUNNING_DECISION,
        "repo_root": str(repo_root),
        "output_dir": str(out),
        "run_start_utc": run_start_utc,
        "last_heartbeat_utc": run_start_utc,
        "last_completed_stage": "STARTED",
        "current_stage": "INITIALIZING",
        "stage_attempted": False,
        "child_exit_codes": {},
        "child_summary_paths": {},
        "child_final_statuses": {},
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "market_data_fetch_attempted": False,
        "canonical_pointer_updated": False,
        "abcde_rerun_succeeded": False,
        "dram_rerun_succeeded": False,
        "research_only": True,
        "warning_count": 0,
        "error_count": 0,
    }


def persist_summary(out: Path, summary: dict[str, Any]) -> None:
    write_json_atomic(out / "v22_040_summary.json", summary)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]
    except Exception:
        return []


def date_key(value: str) -> str:
    return str(value or "")[:10]


def csv_stats(path: Path) -> dict[str, Any]:
    rows = read_csv_rows(path)
    dates = [date_key(row.get("date", "")) for row in rows if date_key(row.get("date", ""))]
    tickers = {row.get("ticker", "") for row in rows if row.get("ticker")}
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "ticker_count": len(tickers),
        "max_date": max(dates) if dates else "",
    }


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_stage_runner(stage: str, repo_root: Path, output_dir: Path) -> dict[str, Any]:
    code = run_subprocess(child_command(repo_root, stage, None, None, False), repo_root, log_path(repo_root / OUT_REL, stage))
    summary_path = child_summary_path(repo_root, stage)
    summary = read_json(summary_path)
    summary["_exit_code"] = code
    summary["_summary_path"] = str(summary_path)
    return summary


def run_fetch_stage(
    repo_root: Path,
    output_dir: Path,
    target_date: str | None,
    cache_root: Path | None,
    no_network: bool,
    fetch_runner: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    if fetch_runner is not None:
        return fetch_runner(repo_root=repo_root, target_date=target_date, cache_root=cache_root, no_network=no_network)
    code = run_subprocess(
        child_command(repo_root, "V21.231", target_date, cache_root, no_network),
        repo_root,
        log_path(output_dir, "V21.231"),
    )
    summary_path = child_summary_path(repo_root, "V21.231")
    summary = read_json(summary_path)
    summary["_exit_code"] = code
    summary["_summary_path"] = str(summary_path)
    return summary


def candidate_dirs(repo_root: Path, cache_root: Path, v231_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    pointer = read_json(v231_dir / "canonical_snapshot_pointer.json")
    for raw in [pointer.get("canonical_snapshot_dir"), read_json(v231_dir / "v21_231_summary.json").get("canonical_snapshot_dir")]:
        if raw:
            path = Path(raw)
            if path.exists() and path.resolve() not in seen:
                out.append(path)
                seen.add(path.resolve())
    canonical_root = cache_root / "canonical/moomoo_ohlcv"
    if canonical_root.exists():
        for path in sorted(canonical_root.glob("snapshot_id=*")):
            if path.is_dir() and path.resolve() not in seen:
                out.append(path)
                seen.add(path.resolve())
    local_root = repo_root / "cache/canonical/moomoo_ohlcv"
    if local_root.exists():
        for path in sorted(local_root.glob("snapshot_id=*")):
            if path.is_dir() and path.resolve() not in seen:
                out.append(path)
                seen.add(path.resolve())
    return out


def complete_candidates(repo_root: Path, cache_root: Path, v231_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for directory in candidate_dirs(repo_root, cache_root, v231_dir):
        raw_path = directory / CANON_RAW
        qfq_path = directory / CANON_QFQ
        raw = csv_stats(raw_path)
        qfq = csv_stats(qfq_path)
        complete = raw["exists"] and qfq["exists"] and raw["row_count"] > 0 and qfq["row_count"] > 0 and raw["max_date"] == qfq["max_date"]
        rows.append({
            "snapshot_id": directory.name.replace("snapshot_id=", ""),
            "canonical_snapshot_dir": str(directory),
            "raw_path": str(raw_path),
            "qfq_path": str(qfq_path),
            "raw_max_date": raw["max_date"],
            "qfq_max_date": qfq["max_date"],
            "raw_row_count": raw["row_count"],
            "qfq_row_count": qfq["row_count"],
            "raw_ticker_count": raw["ticker_count"],
            "qfq_ticker_count": qfq["ticker_count"],
            "complete": complete,
        })
    return rows


def select_latest_complete(candidates: list[dict[str, Any]], target_date: str | None) -> dict[str, Any]:
    complete = [row for row in candidates if row["complete"]]
    if not complete:
        raise RuntimeError("NO_COMPLETE_CANONICAL_SNAPSHOT_CANDIDATE")
    if target_date:
        exact = [row for row in complete if row["raw_max_date"] == target_date]
        if exact:
            return sorted(exact, key=lambda r: (r["raw_max_date"], r["snapshot_id"]))[-1]
    return sorted(complete, key=lambda r: (r["raw_max_date"], r["snapshot_id"]))[-1]


def promote_snapshot(cache_root: Path, selected: dict[str, Any]) -> tuple[str, Path]:
    snapshot_id = "v22_040_promoted_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target_dir = cache_root / "canonical/moomoo_ohlcv" / f"snapshot_id={snapshot_id}"
    target_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(selected["raw_path"], target_dir / CANON_RAW)
    shutil.copy2(selected["qfq_path"], target_dir / CANON_QFQ)
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at_utc": utc_now(),
        "promoted_from_snapshot_id": selected["snapshot_id"],
        "canonical_raw_path": str(target_dir / CANON_RAW),
        "canonical_qfq_path": str(target_dir / CANON_QFQ),
        "latest_date": selected["raw_max_date"],
    }
    write_json_atomic(target_dir / "canonical_manifest.json", manifest)
    return snapshot_id, target_dir


def pointer_payload(cache_root: Path, snapshot_id: str, canonical_dir: Path) -> dict[str, Any]:
    return {
        "policy_version": "V21.231",
        "snapshot_id": snapshot_id,
        "created_at_utc": utc_now(),
        "cache_root": str(cache_root),
        "canonical_snapshot_dir": str(canonical_dir),
        "canonical_raw_path": str(canonical_dir / CANON_RAW),
        "canonical_qfq_path": str(canonical_dir / CANON_QFQ),
        "canonical_manifest_path": str(canonical_dir / "canonical_manifest.json"),
        "source_policy": "MOOMOO_ONLY",
        "source": "MOOMOO_OPEND",
        "yfinance_used": False,
        "yahoo_used": False,
        "external_fallback_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def update_v231_pointer(v231_dir: Path, pointer: dict[str, Any]) -> None:
    write_json_atomic(v231_dir / "canonical_snapshot_pointer.json", pointer)
    write_csv_atomic(v231_dir / "canonical_snapshot_pointer.csv", [{"key": k, "value": v} for k, v in pointer.items()], POINTER_FIELDS)


def validate_pointer(pointer: dict[str, Any]) -> dict[str, Any]:
    raw_path = Path(pointer.get("canonical_raw_path", ""))
    qfq_path = Path(pointer.get("canonical_qfq_path", ""))
    raw = csv_stats(raw_path)
    qfq = csv_stats(qfq_path)
    ok = raw["exists"] and qfq["exists"] and raw["row_count"] > 0 and qfq["row_count"] > 0 and raw["max_date"] == qfq["max_date"]
    return {
        "ok": ok,
        "raw": raw,
        "qfq": qfq,
        "canonical_latest_date": raw["max_date"] if raw["max_date"] == qfq["max_date"] else "",
    }


def days_gap(target_date: str | None, latest_available: str) -> int:
    if not target_date or not latest_available:
        return 0
    try:
        return (date.fromisoformat(target_date) - date.fromisoformat(latest_available)).days
    except ValueError:
        return 0


def permission_ok(*summaries: dict[str, Any]) -> bool:
    for summary in summaries:
        if summary.get("broker_action_allowed") is not False:
            return False
        if summary.get("official_adoption_allowed") is not False:
            return False
        if summary.get("trade_allowed") is True or summary.get("trade_unlock_used") is True:
            return False
    return True


def run(
    repo_root: Path,
    output_dir: Path | None = None,
    target_date: str | None = None,
    cache_root: Path | None = None,
    no_network: bool = False,
    fetch_runner: Callable[..., dict[str, Any]] | None = None,
    stage_runner: StageRunner | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    out = output_dir or repo_root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    target_date = target_date or latest_expected_completed_us_trading_date()
    v231_dir = repo_root / V231_REL
    run_start = time.perf_counter()
    run_start_utc = utc_now()
    summary = running_summary(repo_root, out, target_date, run_start_utc)
    persist_summary(out, summary)
    stage_ledger: list[dict[str, Any]] = []
    failed_stage = ""
    forced_fail_status = ""
    market_data_fetch_attempted = False

    def before_stage(stage: str) -> None:
        nonlocal market_data_fetch_attempted
        summary["current_stage"] = stage
        summary["last_heartbeat_utc"] = utc_now()
        summary["stage_attempted"] = True
        if stage == "V21.231":
            market_data_fetch_attempted = True
            summary["market_data_fetch_attempted"] = True
        persist_summary(out, summary)

    def after_stage(stage: str, child_summary: dict[str, Any], exit_code: int) -> None:
        child_path = child_summary_path(repo_root, stage)
        child_status = child_summary.get("final_status", "")
        summary["last_completed_stage"] = stage
        summary["last_heartbeat_utc"] = utc_now()
        summary["child_exit_codes"][stage] = exit_code
        summary["child_summary_paths"][stage] = str(child_path)
        summary["child_final_statuses"][stage] = child_status
        stage_ledger.append({
            "stage_name": stage,
            "attempted": True,
            "succeeded": exit_code == 0 and not str(child_status).startswith("FAIL"),
            "final_status": child_status,
            "notes": "child stage completed",
        })
        persist_summary(out, summary)

    def execute_stage(stage: str) -> dict[str, Any]:
        before_stage(stage)
        if stage == "V21.231":
            child_summary = run_fetch_stage(repo_root, out, target_date, cache_root, no_network, fetch_runner)
        elif stage_runner is not None:
            child_summary = stage_runner(stage, repo_root, {
                "V21.232": repo_root / V232_REL,
                "V21.233": repo_root / V233_REL,
                "V21.234": repo_root / V234_REL,
                "V21.256": repo_root / V256_REL,
            }[stage])
        else:
            exit_code = run_subprocess(child_command(repo_root, stage, target_date, cache_root, no_network), repo_root, log_path(out, stage))
            child_summary = read_json(child_summary_path(repo_root, stage))
            child_summary["_exit_code"] = exit_code
            child_summary["_summary_path"] = str(child_summary_path(repo_root, stage))
        exit_code = int(child_summary.get("_exit_code", 0) or 0)
        summary_path = child_summary_path(repo_root, stage)
        disk_summary = read_json(summary_path)
        if not disk_summary:
            nonlocal_failed[0] = stage
            nonlocal_forced[0] = FAIL_CHILD_SUMMARY_MISSING
            after_stage(stage, child_summary, exit_code)
            raise RuntimeError(f"CHILD_SUMMARY_MISSING:{stage}:{summary_path}")
        child_summary = {**disk_summary, **{k: v for k, v in child_summary.items() if k.startswith("_")}}
        after_stage(stage, child_summary, exit_code)
        if exit_code != 0:
            nonlocal_failed[0] = stage
            nonlocal_forced[0] = FAIL_CHILD_NONZERO
            raise RuntimeError(f"CHILD_NONZERO_EXIT:{stage}:{exit_code}")
        return child_summary

    nonlocal_failed = [""]
    nonlocal_forced = [""]

    try:
        fetch_summary = execute_stage("V21.231")
        if str(fetch_summary.get("final_status", "")).startswith("FAIL"):
            nonlocal_failed[0] = "V21.231"
            raise RuntimeError(f"V21_231_FETCH_STAGE_FAILED:{fetch_summary.get('final_status')}")
        pointer_before = read_json(v231_dir / "canonical_snapshot_pointer.json")
        effective_cache_root = Path(cache_root or pointer_before.get("cache_root") or fetch_summary.get("cache_root") or (repo_root / "cache"))
        candidates = complete_candidates(repo_root, effective_cache_root, v231_dir)
        selected = select_latest_complete(candidates, target_date)
        warning = WARN_TARGET if selected["raw_max_date"] != target_date else ""
        promoted_id, promoted_dir = promote_snapshot(effective_cache_root, selected)
        pointer = pointer_payload(effective_cache_root, promoted_id, promoted_dir)
        update_v231_pointer(v231_dir, pointer)
        canonical_pointer_updated = True
        validation = validate_pointer(pointer)
        if not validation["ok"]:
            raise RuntimeError("PROMOTED_CANONICAL_POINTER_VALIDATION_FAILED")
        summary.update({
            "latest_available_date": selected["raw_max_date"],
            "canonical_snapshot_id": promoted_id,
            "canonical_latest_date": validation["canonical_latest_date"],
            "data_gap_days": max(days_gap(target_date, selected["raw_max_date"]), 0),
            "canonical_pointer_updated": True,
            "raw_row_count": validation["raw"]["row_count"],
            "raw_ticker_count": validation["raw"]["ticker_count"],
            "qfq_row_count": validation["qfq"]["row_count"],
            "qfq_ticker_count": validation["qfq"]["ticker_count"],
            "qfq_raw_max_date_equal": validation["raw"]["max_date"] == validation["qfq"]["max_date"],
            "canonical_raw_path_exists": validation["raw"]["exists"],
            "canonical_qfq_path_exists": validation["qfq"]["exists"],
        })
        persist_summary(out, summary)

        s232 = execute_stage("V21.232")
        s233 = execute_stage("V21.233")
        s234 = execute_stage("V21.234")
        s256 = execute_stage("V21.256")

        abcde_latest = str(s233.get("canonical_latest_date", ""))
        dram_latest = str(s232.get("latest_price_date", ""))
        canonical_latest = validation["canonical_latest_date"]
        same_date = abcde_latest == canonical_latest and dram_latest == canonical_latest and str(s233.get("same_date_comparable_all_strategies", "")).lower() in {"true", "1"}
        abcde_ok = not str(s233.get("final_status", "")).startswith("FAIL") and abcde_latest == canonical_latest
        dram_ok = not str(s232.get("final_status", "")).startswith("FAIL") and dram_latest == canonical_latest
        wrappers_ok = all(not str(s.get("final_status", "")).startswith("FAIL") for s in [s234, s256])
        gates_ok = permission_ok(fetch_summary, s232, s233, s234, s256)
        final_status = PASS_STATUS
        final_decision = DECISION_READY
        error_count = 0
        warning_count = 1 if warning else 0
        if not (abcde_ok and dram_ok and wrappers_ok and same_date and gates_ok):
            final_status = FAIL_STATUS
            final_decision = DECISION_BLOCKED
            error_count = 1
        elif warning:
            final_status = warning
        summary = {
            **summary,
            "revision": "V22.040_R1A",
            "target_date": target_date,
            "latest_available_date": selected["raw_max_date"],
            "canonical_snapshot_id": promoted_id,
            "canonical_latest_date": canonical_latest,
            "abcde_latest_date": abcde_latest,
            "dram_latest_price_date": dram_latest,
            "same_date_comparable_all_strategies": same_date,
            "data_gap_days": max(days_gap(target_date, selected["raw_max_date"]), 0),
            "final_status": final_status,
            "final_decision": final_decision,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "market_data_fetch_attempted": market_data_fetch_attempted,
            "canonical_pointer_updated": canonical_pointer_updated,
            "abcde_rerun_succeeded": abcde_ok,
            "dram_rerun_succeeded": dram_ok,
            "warning_code": warning,
            "raw_row_count": validation["raw"]["row_count"],
            "raw_ticker_count": validation["raw"]["ticker_count"],
            "qfq_row_count": validation["qfq"]["row_count"],
            "qfq_ticker_count": validation["qfq"]["ticker_count"],
            "qfq_raw_max_date_equal": validation["raw"]["max_date"] == validation["qfq"]["max_date"],
            "canonical_raw_path_exists": validation["raw"]["exists"],
            "canonical_qfq_path_exists": validation["qfq"]["exists"],
            "research_only": True,
            "warning_count": warning_count,
            "error_count": error_count,
            "current_stage": "COMPLETE",
            "run_end_utc": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - run_start, 3),
        }
    except BaseException as exc:
        failed_stage = nonlocal_failed[0] or summary.get("current_stage", "")
        forced_fail_status = nonlocal_forced[0]
        summary = {
            **summary,
            "revision": "V22.040_R1A",
            "target_date": target_date,
            "latest_available_date": summary.get("latest_available_date", ""),
            "canonical_snapshot_id": summary.get("canonical_snapshot_id", ""),
            "canonical_latest_date": summary.get("canonical_latest_date", ""),
            "abcde_latest_date": summary.get("abcde_latest_date", ""),
            "dram_latest_price_date": summary.get("dram_latest_price_date", ""),
            "same_date_comparable_all_strategies": summary.get("same_date_comparable_all_strategies", False),
            "data_gap_days": summary.get("data_gap_days", 0),
            "final_status": forced_fail_status or FAIL_STATUS,
            "final_decision": DECISION_BLOCKED,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "market_data_fetch_attempted": market_data_fetch_attempted,
            "canonical_pointer_updated": bool(summary.get("canonical_pointer_updated", False)),
            "abcde_rerun_succeeded": False,
            "dram_rerun_succeeded": False,
            "exception_type": type(exc).__name__,
            "error_message": str(exc),
            "exception_message": str(exc),
            "failed_stage": failed_stage,
            "run_end_utc": utc_now(),
            "elapsed_seconds": round(time.perf_counter() - run_start, 3),
            "research_only": True,
            "warning_count": 0,
            "error_count": 1,
        }

    write_json_atomic(out / "v22_040_summary.json", summary)
    write_csv(out / "v22_040_stage_ledger.csv", stage_ledger, ["stage_name", "attempted", "succeeded", "final_status", "notes"])
    write_csv(out / "v22_040_final_summary.csv", [{"key": k, "value": v} for k, v in summary.items()], ["key", "value"])
    report_keys = [
        "target_date", "latest_available_date", "canonical_snapshot_id", "canonical_latest_date",
        "abcde_latest_date", "dram_latest_price_date", "same_date_comparable_all_strategies",
        "data_gap_days", "final_status", "final_decision", "broker_action_allowed",
        "official_adoption_allowed", "market_data_fetch_attempted", "canonical_pointer_updated",
        "abcde_rerun_succeeded", "dram_rerun_succeeded",
    ]
    (out / "V22.040_daily_moomoo_oneclick_refresh_orchestrator_r1_report.txt").write_text(
        "\n".join([STAGE, *[f"{k}={summary.get(k)}" for k in report_keys]]) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--target-date", default=None)
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--no-network", action="store_true", default=False)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.output_dir, args.target_date, args.cache_root, args.no_network)
    for key in [
        "target_date", "latest_available_date", "canonical_snapshot_id", "canonical_latest_date",
        "abcde_latest_date", "dram_latest_price_date", "same_date_comparable_all_strategies",
        "data_gap_days", "final_status", "final_decision", "broker_action_allowed",
        "official_adoption_allowed", "market_data_fetch_attempted", "canonical_pointer_updated",
        "abcde_rerun_succeeded", "dram_rerun_succeeded",
    ]:
        print(f"{key}={summary.get(key)}")
    return 1 if str(summary.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
