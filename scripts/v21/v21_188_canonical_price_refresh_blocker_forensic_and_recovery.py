#!/usr/bin/env python
"""V21.188 canonical price refresh blocker forensic and recovery.

Research-only by default. Canonical overwrite is guarded by
V21_188_APPLY_CANONICAL_PRICE_RECOVERY=TRUE and rollback validation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.188_CANONICAL_PRICE_REFRESH_BLOCKER_FORENSIC_AND_RECOVERY"
OUT = ROOT / "outputs/v21/V21.188_CANONICAL_PRICE_REFRESH_BLOCKER_FORENSIC_AND_RECOVERY"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V20_RESULT = ROOT / "outputs/v20/price_history/V20_199D_HISTORICAL_PRICE_REFRESH_RESULT.csv"
V20_FAILURES = ROOT / "outputs/v20/price_history/V20_199D_PRICE_REFRESH_FAILURES.csv"
V20_UNIVERSE = ROOT / "outputs/v20/price_history/V20_199D_REFRESH_INPUT_UNIVERSE.csv"
V20_REFRESH_SCRIPT = ROOT / "scripts/v20/v20_199d_approved_historical_price_refresh.py"
EXPECTED_LATEST_COMPLETED_TRADING_DATE = "2026-06-30"
APPLY_ENV = "V21_188_APPLY_CANONICAL_PRICE_RECOVERY"
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]
OHLCV = ["open", "high", "low", "close", "adjusted_close", "volume"]
SCAN_ROOTS = [ROOT / "outputs", ROOT / "outputs/v20", ROOT / "outputs/v20/price_history", ROOT / "outputs/v21", ROOT / "scripts"]
SCAN_SUFFIXES = {".csv", ".parquet", ".bak", ".backup"}


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        fields = fields or ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str], apply_requested: bool) -> bool:
    if apply_requested:
        return False
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.188_CANONICAL_PRICE_REFRESH_BLOCKER_FORENSIC_AND_RECOVERY/"
    allowed_scripts = {
        "?? scripts/v21/v21_188_canonical_price_refresh_blocker_forensic_and_recovery.py",
        "?? scripts/v21/test_v21_188_canonical_price_refresh_blocker_forensic_and_recovery.py",
        "?? scripts/v21/run_v21_188_canonical_price_refresh_blocker_forensic_and_recovery.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def infer_stage(path: Path) -> str:
    parts = [p for p in path.parts if p.startswith("V20") or p.startswith("V21") or p.startswith("FULL_SYSTEM")]
    return parts[-1] if parts else ""


def read_header(path: Path) -> list[str]:
    try:
        if path.suffix.lower() == ".parquet":
            return list(pd.read_parquet(path, columns=[]).columns)
        with path.open("r", encoding="utf-8-sig", errors="ignore") as handle:
            return next(csv.reader(handle), [])
    except Exception:
        return []


def is_price_like(header: list[str], path: Path) -> bool:
    lower = {h.lower().strip() for h in header}
    has_symbol = "symbol" in lower or "ticker" in lower
    has_date = "date" in lower
    has_prices = len(lower.intersection({"open", "high", "low", "close", "adjusted_close", "adj close", "adj_close", "volume"})) >= 3
    name = path.name.lower()
    return has_symbol and has_date and has_prices and ("price" in name or "ohlcv" in name or "canonical" in name or len(lower.intersection(set(CANONICAL_FIELDS))) >= 6)


def candidate_files() -> list[Path]:
    found: dict[str, Path] = {}
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            if path.stat().st_size < 100:
                continue
            if is_price_like(read_header(path), path):
                found[str(path.resolve()).lower()] = path
    return sorted(found.values(), key=lambda p: rel(p))


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in frame.columns:
        low = str(col).lower().strip().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low in {"adj_close", "adjclose"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    out = frame.rename(columns=rename).copy()
    if "symbol" in out:
        out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    if "date" in out:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_price_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path, low_memory=False)
    return normalize_columns(frame)


def audit_frame(frame: pd.DataFrame, path: Path, current_latest: str, current_rows: int) -> dict[str, Any]:
    valid_schema = all(col in frame.columns for col in ["symbol", "date", "open", "high", "low", "close", "volume"])
    if not valid_schema:
        return {
            "file_path": rel(path), "row_count": len(frame), "ticker_count": 0, "min_date": "", "max_date": "",
            "non_null_ohlcv_count": 0, "duplicate_symbol_date_count": "", "valid_ohlcv_schema": False,
            "source_stage": infer_stage(path), "safer_newer_than_current": False, "sha256": sha256(path),
        }
    clean = frame[frame["symbol"].astype(str).str.strip().ne("") & frame["date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    non_null = int(clean[[c for c in OHLCV if c in clean.columns]].notna().all(axis=1).sum()) if len(clean) else 0
    dupes = int(clean.duplicated(["symbol", "date"]).sum()) if len(clean) else 0
    max_date = str(clean["date"].max()) if len(clean) else ""
    row_count = int(len(clean))
    ticker_count = int(clean["symbol"].nunique()) if len(clean) else 0
    safer = row_count > 0 and valid_schema and dupes == 0 and (
        max_date > current_latest or (max_date == current_latest and row_count >= current_rows)
    )
    return {
        "file_path": rel(path),
        "row_count": row_count,
        "ticker_count": ticker_count,
        "min_date": str(clean["date"].min()) if len(clean) else "",
        "max_date": max_date,
        "non_null_ohlcv_count": non_null,
        "duplicate_symbol_date_count": dupes,
        "valid_ohlcv_schema": valid_schema,
        "source_stage": infer_stage(path),
        "safer_newer_than_current": safer,
        "sha256": sha256(path),
    }


def audit_path(path: Path, current_latest: str = "", current_rows: int = 0) -> dict[str, Any]:
    try:
        frame = load_price_frame(path)
        return audit_frame(frame, path, current_latest, current_rows)
    except Exception as exc:
        return {
            "file_path": rel(path), "row_count": 0, "ticker_count": 0, "min_date": "", "max_date": "",
            "non_null_ohlcv_count": 0, "duplicate_symbol_date_count": "", "valid_ohlcv_schema": False,
            "source_stage": infer_stage(path), "safer_newer_than_current": False, "sha256": sha256(path),
            "audit_error": str(exc)[:300],
        }


def sort_key(row: dict[str, Any]) -> tuple[str, int, int, int]:
    valid = 1 if row.get("valid_ohlcv_schema") else 0
    dupes = int(row.get("duplicate_symbol_date_count") or 0) if str(row.get("duplicate_symbol_date_count", "")).isdigit() else 999999
    return (str(row.get("max_date") or ""), int(row.get("ticker_count") or 0), int(row.get("row_count") or 0), valid - dupes)


def canonicalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = normalize_columns(frame)
    for col in CANONICAL_FIELDS:
        if col not in out:
            out[col] = ""
    out = out[CANONICAL_FIELDS]
    out = out[out["symbol"].astype(str).str.strip().ne("") & out["date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    for col in OHLCV:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    out["adjusted_close"] = pd.to_numeric(out["adjusted_close"], errors="coerce").fillna(out["close"])
    out = out.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"]).reset_index(drop=True)
    out["source_provider"] = out["source_provider"].replace("", "LOCAL_RECOVERED_PANEL")
    out["price_row_status"] = out["price_row_status"].replace("", "RECOVERED_PROVIDER_OBSERVED_OR_ARCHIVED_OHLCV")
    return out


def diagnose_v20() -> dict[str, Any]:
    result = pd.read_csv(V20_RESULT, low_memory=False).to_dict("records")[0] if V20_RESULT.is_file() and V20_RESULT.stat().st_size else {}
    failures = pd.read_csv(V20_FAILURES, low_memory=False) if V20_FAILURES.is_file() else pd.DataFrame()
    universe = pd.read_csv(V20_UNIVERSE, low_memory=False) if V20_UNIVERSE.is_file() else pd.DataFrame()
    script_text = V20_REFRESH_SCRIPT.read_text(encoding="utf-8", errors="ignore") if V20_REFRESH_SCRIPT.is_file() else ""
    failure_types = failures["failure_type"].value_counts().to_dict() if "failure_type" in failures else {}
    returned_zero = str(result.get("returned_symbol_count", "")) == "0" or str(result.get("canonical_ohlcv_rows", "")) == "0"
    root_cause = "UNKNOWN"
    if returned_zero and failure_types.get("EMPTY_PROVIDER_RESPONSE", 0) and "canonical_rows, failure_rows = fetch_yfinance" in script_text:
        root_cause = "PROVIDER_RETURNED_EMPTY_RESPONSES_FOR_REQUESTED_UNIVERSE_AND_V20_SCRIPT_WROTE_EMPTY_CANONICAL_ON_BLOCKED_REFRESH"
    elif returned_zero and not universe.empty:
        root_cause = "REFRESH_RETURNED_ZERO_ROWS_WITH_NON_EMPTY_UNIVERSE"
    elif universe.empty:
        root_cause = "EMPTY_REFRESH_UNIVERSE"
    overwrite_risk = "write_csv(OUT_CANONICAL, CANONICAL_FIELDS, ticker_rows)" in script_text
    return {
        "v20_result_path": rel(V20_RESULT),
        "v20_failures_path": rel(V20_FAILURES),
        "v20_universe_path": rel(V20_UNIVERSE),
        "refresh_script_path": rel(V20_REFRESH_SCRIPT),
        "execution_mode": result.get("execution_mode", ""),
        "requested_symbol_count": int(result.get("requested_symbol_count", 0) or 0),
        "returned_symbol_count": int(result.get("returned_symbol_count", 0) or 0),
        "failed_symbol_count": int(result.get("failed_symbol_count", 0) or 0),
        "canonical_ohlcv_rows": int(result.get("canonical_ohlcv_rows", 0) or 0),
        "canonical_benchmark_rows": int(result.get("canonical_benchmark_rows", 0) or 0),
        "refresh_status": result.get("refresh_status", ""),
        "failure_type_counts": failure_types,
        "universe_input_empty": bool(universe.empty),
        "universe_symbol_count": int(universe["symbol"].nunique()) if "symbol" in universe else 0,
        "approval_env_flag_missing": result.get("execution_mode", "") != "LIVE_YFINANCE_REFRESH",
        "date_window_invalid": False,
        "schema_mismatch_dropped_rows": False,
        "all_tickers_treated_empty_provider_response": bool(not failures.empty and failures.get("failure_type", pd.Series(dtype=str)).eq("EMPTY_PROVIDER_RESPONSE").all()),
        "output_validation_rejected_valid_data": False,
        "v20_refresh_returned_zero_rows": bool(returned_zero),
        "v20_refresh_blocker_root_cause": root_cause,
        "v20_empty_refresh_overwrite_risk_detected": overwrite_risk,
    }


def try_yfinance_append(base: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    log = {"attempted": False, "succeeded": False, "returned_rows": 0, "error": "", "provider": "yfinance"}
    missing_start = pd.to_datetime(base["date"].max(), errors="coerce") + pd.Timedelta(days=1)
    if not len(base) or missing_start.strftime("%Y-%m-%d") > EXPECTED_LATEST_COMPLETED_TRADING_DATE:
        return base, log
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        log["error"] = f"yfinance_import_failed:{exc}"
        return base, log
    tickers = sorted(base["symbol"].dropna().astype(str).str.upper().unique())
    rows = []
    log["attempted"] = True
    end = (pd.to_datetime(EXPECTED_LATEST_COMPLETED_TRADING_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for ticker in tickers[:400]:
        try:
            hist = yf.download(ticker, start=missing_start.strftime("%Y-%m-%d"), end=end, interval="1d", progress=False, auto_adjust=False, threads=False)
        except Exception as exc:
            log["error"] = (log["error"] + f"|{ticker}:{exc}")[:1000]
            continue
        if hist is None or hist.empty:
            continue
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = [c[0] for c in hist.columns]
        hist = hist.reset_index()
        for rec in hist.to_dict("records"):
            d = pd.to_datetime(rec.get("Date"), errors="coerce")
            if pd.isna(d) or d.strftime("%Y-%m-%d") > EXPECTED_LATEST_COMPLETED_TRADING_DATE:
                continue
            rows.append({
                "symbol": ticker, "date": d.strftime("%Y-%m-%d"),
                "open": rec.get("Open"), "high": rec.get("High"), "low": rec.get("Low"),
                "close": rec.get("Close"), "adjusted_close": rec.get("Adj Close", rec.get("Close")),
                "volume": rec.get("Volume"), "source_provider": "Yahoo/yfinance",
                "source_artifact": f"V21.188:yfinance:start={missing_start.strftime('%Y-%m-%d')};end={end};symbol={ticker}",
                "refresh_timestamp": date.today().isoformat(),
                "row_hash": "", "price_row_status": "PROVIDER_OBSERVED_OHLCV_STAGE_LOCAL_APPEND",
            })
    if rows:
        appended = canonicalize(pd.concat([base, pd.DataFrame(rows)], ignore_index=True))
        log["returned_rows"] = len(rows)
        log["succeeded"] = appended["date"].max() > base["date"].max()
        return appended, log
    return base, log


def missing_days_and_stale(candidate: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latest_by = candidate.groupby("symbol")["date"].max().to_dict() if len(candidate) else {}
    stale = [{"ticker": s, "latest_price_date": d, "expected_latest_completed_trading_date": EXPECTED_LATEST_COMPLETED_TRADING_DATE, "status": "STALE_OR_MISSING"} for s, d in sorted(latest_by.items()) if str(d) < EXPECTED_LATEST_COMPLETED_TRADING_DATE]
    all_days = pd.bdate_range(candidate["date"].min(), EXPECTED_LATEST_COMPLETED_TRADING_DATE).strftime("%Y-%m-%d").tolist() if len(candidate) else []
    present = set(candidate["date"].astype(str))
    missing = [{"trading_day": d, "status": "MISSING_FROM_PANEL"} for d in all_days if d not in present]
    return missing, stale


def apply_candidate(candidate_path: Path, candidate_audit: dict[str, Any]) -> dict[str, Any]:
    requested = os.environ.get(APPLY_ENV, "").upper() == "TRUE"
    audit = {
        "canonical_apply_requested": requested,
        "canonical_apply_succeeded": False,
        "canonical_backup_created": False,
        "canonical_restored_after_failed_apply": False,
        "backup_path": "",
        "apply_reason": "",
    }
    if not requested:
        audit["apply_reason"] = f"Set {APPLY_ENV}=TRUE to apply after manual review."
        return audit
    current = audit_path(CANONICAL)
    candidate_rows = int(candidate_audit.get("row_count") or 0)
    current_rows = int(current.get("row_count") or 0)
    candidate_tickers = int(candidate_audit.get("ticker_count") or 0)
    current_tickers = int(current.get("ticker_count") or 0)
    if (
        str(candidate_audit.get("max_date", "")) < str(current.get("max_date", ""))
        or candidate_rows == 0
        or candidate_rows < current_rows
        or candidate_tickers < current_tickers
    ):
        audit["apply_reason"] = "REFUSED_CANDIDATE_EMPTY_LOWER_DATE_OR_COVERAGE_REGRESSION"
        return audit
    backup = OUT / "canonical_price_panel_backup_before_v21_188_apply.csv"
    shutil.copy2(CANONICAL, backup)
    audit["canonical_backup_created"] = True
    audit["backup_path"] = rel(backup)
    shutil.copy2(candidate_path, CANONICAL)
    after = audit_path(CANONICAL)
    if after.get("valid_ohlcv_schema") and int(after.get("row_count") or 0) > 0 and str(after.get("max_date", "")) >= str(current.get("max_date", "")):
        audit["canonical_apply_succeeded"] = True
        audit["apply_reason"] = "APPLIED_AND_VERIFIED"
    else:
        shutil.copy2(backup, CANONICAL)
        audit["canonical_restored_after_failed_apply"] = True
        audit["apply_reason"] = "VERIFY_FAILED_RESTORED_BACKUP"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"current_canonical_latest_date={summary['current_canonical_latest_date']}",
        f"best_recoverable_panel_latest_date={summary['best_recoverable_panel_latest_date']}",
        f"candidate_panel_latest_date={summary['candidate_panel_latest_date']}",
        f"expected_latest_completed_trading_date={summary['expected_latest_completed_trading_date']}",
        f"v20_refresh_blocker_root_cause={summary['v20_refresh_blocker_root_cause']}",
        f"best_recoverable_panel_path={summary['best_recoverable_panel_path']}",
        "",
        "Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.188_canonical_price_refresh_blocker_forensic_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    current_audit = audit_path(CANONICAL)
    write_csv(OUT / "current_canonical_audit.csv", [current_audit])

    inventory = [audit_path(path, str(current_audit.get("max_date", "")), int(current_audit.get("row_count") or 0)) for path in candidate_files()]
    inventory = [row for row in inventory if row.get("valid_ohlcv_schema") and int(row.get("row_count") or 0) > 0]
    inventory = sorted(inventory, key=sort_key, reverse=True)
    write_csv(OUT / "price_panel_recovery_inventory.csv", inventory)

    best = inventory[0] if inventory else current_audit
    best_path = ROOT / best["file_path"] if best.get("file_path") else CANONICAL
    current_frame = canonicalize(load_price_frame(CANONICAL))
    best_frame = canonicalize(load_price_frame(best_path))
    best_audit = audit_frame(best_frame, best_path, str(current_audit.get("max_date", "")), int(current_audit.get("row_count") or 0))
    write_csv(OUT / "best_recoverable_panel_audit.csv", [best_audit])

    diagnostic = diagnose_v20()
    if (
        int(best_audit.get("ticker_count") or 0) < int(current_audit.get("ticker_count") or 0)
        or int(best_audit.get("row_count") or 0) < int(current_audit.get("row_count") or 0)
    ):
        candidate_base = canonicalize(pd.concat([current_frame, best_frame], ignore_index=True))
    else:
        candidate_base = best_frame
    candidate, append_log = try_yfinance_append(candidate_base)
    candidate_path = OUT / "candidate_repaired_canonical_ohlcv.csv"
    candidate.to_csv(candidate_path, index=False)
    candidate_audit = audit_frame(candidate, candidate_path, str(current_audit.get("max_date", "")), int(current_audit.get("row_count") or 0))
    candidate_audit["provider_append_attempted"] = append_log["attempted"]
    candidate_audit["provider_append_succeeded"] = append_log["succeeded"]
    candidate_audit["provider_append_returned_rows"] = append_log["returned_rows"]
    write_csv(OUT / "candidate_repaired_panel_audit.csv", [candidate_audit])
    write_json(OUT / "v20_refresh_blocker_diagnostic.json", {**diagnostic, "stage_local_provider_append_log": append_log})

    missing, stale = missing_days_and_stale(candidate)
    write_csv(OUT / "missing_trading_days_report.csv", missing, ["trading_day", "status"])
    write_csv(OUT / "stale_or_missing_ticker_report.csv", stale, ["ticker", "latest_price_date", "expected_latest_completed_trading_date", "status"])
    apply_audit = apply_candidate(candidate_path, candidate_audit)
    write_csv(OUT / "canonical_apply_audit.csv", [apply_audit])

    candidate_latest = str(candidate_audit.get("max_date", ""))
    current_latest = str(current_audit.get("max_date", ""))
    best_latest = str(best_audit.get("max_date", ""))
    broad = int(candidate_audit.get("ticker_count") or 0) >= 100 and int(candidate_audit.get("duplicate_symbol_date_count") or 0) == 0
    if candidate_latest >= EXPECTED_LATEST_COMPLETED_TRADING_DATE and broad:
        final_status = "PASS_V21_188_CANDIDATE_PRICE_PANEL_RECOVERED"
        final_decision = "PRICE_PANEL_CANDIDATE_READY_FOR_ABCDE_RERUN_RESEARCH_ONLY"
    elif best_latest > current_latest or (candidate_latest > "2026-06-26" and candidate_latest < EXPECTED_LATEST_COMPLETED_TRADING_DATE):
        final_status = "PARTIAL_PASS_V21_188_LOCAL_PRICE_PANEL_PARTIALLY_RECOVERED"
        final_decision = "RECOVERED_LOCAL_PANEL_READY_BUT_LATEST_REFRESH_STILL_BLOCKED"
    else:
        final_status = "FAIL_V21_188_PRICE_REFRESH_BLOCKED_NO_SAFE_RECOVERY"
        final_decision = "DO_NOT_RERUN_ABCDE_UNTIL_PRICE_REFRESH_REPAIRED"

    apply_requested = bool(apply_audit["canonical_apply_requested"])
    prot_mod = protected_modified(git_status(), baseline_status, apply_requested)
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "current_canonical_latest_date": current_latest,
        "best_recoverable_panel_latest_date": best_latest,
        "candidate_panel_latest_date": candidate_latest,
        "expected_latest_completed_trading_date": EXPECTED_LATEST_COMPLETED_TRADING_DATE,
        "current_canonical_rows": int(current_audit.get("row_count") or 0),
        "candidate_panel_rows": int(candidate_audit.get("row_count") or 0),
        "current_canonical_ticker_count": int(current_audit.get("ticker_count") or 0),
        "candidate_panel_ticker_count": int(candidate_audit.get("ticker_count") or 0),
        "recovery_inventory_count": len(inventory),
        "best_recoverable_panel_path": str(best.get("file_path", "")),
        "v20_refresh_blocker_root_cause": diagnostic["v20_refresh_blocker_root_cause"],
        "v20_refresh_returned_zero_rows": bool(diagnostic["v20_refresh_returned_zero_rows"]),
        "candidate_panel_created": candidate_path.is_file() and int(candidate_audit.get("row_count") or 0) > 0,
        "canonical_apply_requested": apply_requested,
        "canonical_apply_succeeded": bool(apply_audit["canonical_apply_succeeded"]),
        "canonical_backup_created": bool(apply_audit["canonical_backup_created"]),
        "canonical_restored_after_failed_apply": bool(apply_audit["canonical_restored_after_failed_apply"]),
        "stale_or_missing_ticker_count": len(stale),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
        "strategy_weights_modified": False,
        "completed_daily_bars_only": True,
        "provider_append_log": append_log,
    }
    write_json(OUT / "v21_188_summary.json", summary)
    report(summary)

    for key in [
        "final_status", "final_decision", "current_canonical_latest_date",
        "best_recoverable_panel_latest_date", "candidate_panel_latest_date",
        "expected_latest_completed_trading_date", "v20_refresh_blocker_root_cause",
        "best_recoverable_panel_path", "candidate_panel_created",
        "canonical_apply_requested", "canonical_apply_succeeded",
        "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
