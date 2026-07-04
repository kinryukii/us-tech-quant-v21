#!/usr/bin/env python
"""V21.190 alternate 2026-06-30 daily bar source and safe append.

Research-only. Canonical writes require V21_190_APPLY_20260630_APPEND=TRUE.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import traceback
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.190_ALTERNATE_DAILY_BAR_SOURCE_FOR_20260630_AND_SAFE_APPEND"
OUT = ROOT / "outputs/v21/V21.190_ALTERNATE_DAILY_BAR_SOURCE_FOR_20260630_AND_SAFE_APPEND"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
APPLY_ENV = "V21_190_APPLY_20260630_APPEND"
TARGET_DATE = "2026-06-30"
TARGET_END = "2026-07-01"
CACHE_DIR = OUT / "yfinance_cache"
HEALTHCHECK_TICKERS = ["QQQ", "AAPL", "MU", "AMAT"]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]
OHLCV = ["open", "high", "low", "close", "adjusted_close", "volume"]
SCAN_SUFFIXES = {".csv", ".parquet", ".bak", ".backup"}


def configure_yfinance_cache() -> tuple[Any | None, dict[str, Any], str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CACHE_HOME"] = str(CACHE_DIR)
    os.environ["YFINANCE_CACHE_DIR"] = str(CACHE_DIR)
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(OUT / "pycache"))
    probe = CACHE_DIR / "write_probe.tmp"
    cache_dir_writable = False
    cache_probe_file_created = False
    yfinance_cache_location_set = False
    import_error = ""
    try:
        probe.write_text("probe\n", encoding="utf-8")
        cache_probe_file_created = probe.is_file()
        cache_dir_writable = True
    except Exception as exc:
        import_error = f"cache_probe_failed:{exc}"
    try:
        import yfinance as yf  # type: ignore
        if hasattr(yf, "set_tz_cache_location"):
            yf.set_tz_cache_location(str(CACHE_DIR))
            yfinance_cache_location_set = True
        else:
            yfinance_cache_location_set = False
        yf_obj: Any | None = yf
    except Exception as exc:
        yf_obj = None
        import_error = (import_error + f"|yfinance_import_failed:{exc}").strip("|")
    diag = {
        "yfinance_cache_dir": rel(CACHE_DIR),
        "cache_dir_exists": CACHE_DIR.is_dir(),
        "cache_dir_writable": cache_dir_writable,
        "cache_probe_file_created": cache_probe_file_created,
        "yfinance_cache_location_set": yfinance_cache_location_set,
        "xdg_cache_home": os.environ.get("XDG_CACHE_HOME", ""),
        "yfinance_cache_dir_env": os.environ.get("YFINANCE_CACHE_DIR", ""),
        "pythonpycacheprefix": os.environ.get("PYTHONPYCACHEPREFIX", ""),
        "yfinance_import_error": import_error,
    }
    return yf_obj, diag, import_error


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


def row_hash(row: dict[str, Any]) -> str:
    text = "|".join(str(row.get(c, "")) for c in ["symbol", "date", *OHLCV])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    rename = {}
    for col in frame.columns:
        low = str(col).strip().lower().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low in {"adj_close", "adjclose"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    out = frame.rename(columns=rename).copy()
    if "symbol" not in out or "date" not in out:
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        if col not in out:
            out[col] = pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in CANONICAL_FIELDS:
        if col not in out:
            out[col] = ""
    out["adjusted_close"] = out["adjusted_close"].fillna(out["close"])
    out = out[CANONICAL_FIELDS]
    out = out[out["symbol"].ne("") & out["date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    out = out.dropna(subset=["open", "high", "low", "close", "adjusted_close", "volume"])
    out = out[pd.to_numeric(out["close"], errors="coerce") > 0]
    return out.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"]).reset_index(drop=True)


def read_price_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return normalize(pd.read_parquet(path))
    return normalize(pd.read_csv(path, low_memory=False))


def load_canonical() -> pd.DataFrame:
    if not CANONICAL.is_file():
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    return read_price_file(CANONICAL)


def audit_frame(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    return {
        "path": rel(path),
        "row_count": int(len(frame)),
        "ticker_count": int(frame["symbol"].nunique()) if len(frame) else 0,
        "min_date": str(frame["date"].min()) if len(frame) else "",
        "max_date": str(frame["date"].max()) if len(frame) else "",
        "non_null_ohlcv_count": int(frame[OHLCV].notna().all(axis=1).sum()) if len(frame) else 0,
        "duplicate_symbol_date_rows": int(frame.duplicated(["symbol", "date"]).sum()) if len(frame) else 0,
        "zero_or_negative_close_rows": int((pd.to_numeric(frame["close"], errors="coerce") <= 0).sum()) if len(frame) else 0,
        "sha256": sha256(path) if path.is_file() else "",
    }


def header(path: Path) -> list[str]:
    try:
        if path.suffix.lower() == ".parquet":
            return list(pd.read_parquet(path, columns=[]).columns)
        with path.open("r", encoding="utf-8-sig", errors="ignore") as handle:
            return next(csv.reader(handle), [])
    except Exception:
        return []


def price_like(path: Path) -> bool:
    cols = {c.lower().strip().replace(" ", "_") for c in header(path)}
    has_symbol = "symbol" in cols or "ticker" in cols
    return has_symbol and "date" in cols and len(cols.intersection({"open", "high", "low", "close", "adjusted_close", "adj_close", "volume"})) >= 3


def local_inventory(symbols: set[str]) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    found = []
    seen: set[str] = set()
    roots = [ROOT / "outputs", ROOT / "state", ROOT / "scripts"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            resolved = str(path.resolve()).lower()
            if resolved in seen or path.stat().st_size < 100:
                continue
            seen.add(resolved)
            if not price_like(path):
                continue
            try:
                frame = read_price_file(path)
                sub = frame[frame["date"].eq(TARGET_DATE) & frame["symbol"].isin(symbols)].copy()
                if len(sub):
                    sub["source_provider"] = sub["source_provider"].replace("", "LOCAL_ARCHIVED_PRICE_FILE")
                    sub["source_artifact"] = rel(path)
                    sub["price_row_status"] = "LOCAL_ARCHIVED_PROVIDER_OBSERVED_OHLCV_20260630"
                    found.append(sub)
                rows.append({
                    "file_path": rel(path),
                    "row_count": int(len(frame)),
                    "ticker_count": int(frame["symbol"].nunique()) if len(frame) else 0,
                    "min_date": str(frame["date"].min()) if len(frame) else "",
                    "max_date": str(frame["date"].max()) if len(frame) else "",
                    "target_rows_for_canonical_symbols": int(len(sub)),
                    "duplicate_symbol_date_rows": int(frame.duplicated(["symbol", "date"]).sum()) if len(frame) else 0,
                })
            except Exception as exc:
                rows.append({"file_path": rel(path), "row_count": 0, "ticker_count": 0, "min_date": "", "max_date": "", "target_rows_for_canonical_symbols": 0, "duplicate_symbol_date_rows": "", "error": str(exc)[:300]})
    out = normalize(pd.concat(found, ignore_index=True)) if found else pd.DataFrame(columns=CANONICAL_FIELDS)
    return rows, out


def make_row(ticker: str, rec: dict[str, Any], mode: str) -> dict[str, Any] | None:
    date_value = rec.get("Date") or rec.get("date")
    dt = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(dt) or dt.strftime("%Y-%m-%d") != TARGET_DATE:
        return None
    row = {
        "symbol": ticker,
        "date": TARGET_DATE,
        "open": rec.get("Open", rec.get("open")),
        "high": rec.get("High", rec.get("high")),
        "low": rec.get("Low", rec.get("low")),
        "close": rec.get("Close", rec.get("close")),
        "adjusted_close": rec.get("Adj Close", rec.get("adjusted_close", rec.get("Close", rec.get("close")))),
        "volume": rec.get("Volume", rec.get("volume")),
        "source_provider": "Yahoo/yfinance",
        "source_artifact": f"V21.190:{mode}:start={TARGET_DATE};end={TARGET_END};symbol={ticker}",
        "refresh_timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "price_row_status": f"PROVIDER_OBSERVED_OHLCV_20260630_{mode.upper()}",
    }
    row["row_hash"] = row_hash(row)
    return row


def yf_download(yf: Any, *args: Any, **kwargs: Any) -> tuple[pd.DataFrame, str, str]:
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            data = yf.download(*args, **kwargs)
        return data if data is not None else pd.DataFrame(), stderr.getvalue(), ""
    except Exception:
        return pd.DataFrame(), stderr.getvalue(), traceback.format_exc()


def operational_error_text(text: str) -> bool:
    low = text.lower()
    return "operationalerror" in low or "unable to open database file" in low


def healthcheck(yf: Any | None) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    trace_samples: list[str] = []
    if yf is None:
        for ticker in HEALTHCHECK_TICKERS:
            rows.append({"ticker": ticker, "status": "IMPORT_FAILED", "rows": 0, "operational_error": False, "detail": "yfinance import failed"})
        return rows, trace_samples, {"attempted": True, "success_count": 0, "failed_count": len(rows)}
    for ticker in HEALTHCHECK_TICKERS:
        data, stderr_text, exc_text = yf_download(
            yf,
            ticker,
            start=TARGET_DATE,
            end=TARGET_END,
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        detail = (exc_text or stderr_text).strip()
        if detail:
            trace_samples.append(f"HEALTHCHECK {ticker}\n{detail}\n")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]
        frame = data.reset_index() if data is not None and not data.empty else pd.DataFrame()
        found = 0
        if not frame.empty:
            for rec in frame.to_dict("records"):
                if make_row(ticker, rec, "healthcheck"):
                    found += 1
        op = operational_error_text(detail)
        rows.append({
            "ticker": ticker,
            "status": "SUCCESS" if found else ("OPERATIONAL_ERROR" if op else "EMPTY"),
            "rows": found,
            "operational_error": op,
            "detail": detail[:500],
        })
    success_count = sum(1 for row in rows if row["status"] == "SUCCESS")
    return rows, trace_samples, {"attempted": True, "success_count": success_count, "failed_count": len(rows) - success_count}


def yfinance_direct(tickers: list[str], diagnostics: list[dict[str, Any]], yf: Any | None, trace_samples: list[str]) -> pd.DataFrame:
    rows = []
    if yf is None:
        diagnostics.append({"mode": "yfinance_direct", "ticker": "", "status": "IMPORT_FAILED", "detail": "yfinance import failed"})
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    for ticker in tickers:
        hist, stderr_text, exc_text = yf_download(yf, ticker, start=TARGET_DATE, end=TARGET_END, interval="1d", progress=False, auto_adjust=False, threads=False)
        detail = (exc_text or stderr_text).strip()
        if detail and len(trace_samples) < 20:
            trace_samples.append(f"DIRECT {ticker}\n{detail}\n")
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = [c[0] for c in hist.columns]
        hist = hist.reset_index() if hist is not None and not hist.empty else pd.DataFrame()
        added = 0
        for rec in hist.to_dict("records"):
            row = make_row(ticker, rec, "yfinance_direct")
            if row:
                rows.append(row)
                added += 1
        if added:
            status = "SUCCESS"
        elif operational_error_text(detail):
            status = "OPERATIONAL_ERROR"
        elif exc_text:
            status = "ERROR"
        else:
            status = "EMPTY"
        diagnostics.append({"mode": "yfinance_direct", "ticker": ticker, "status": status, "detail": (detail or f"rows={added}")[:500]})
    return normalize(pd.DataFrame(rows)) if rows else pd.DataFrame(columns=CANONICAL_FIELDS)


def yfinance_batch(tickers: list[str], diagnostics: list[dict[str, Any]], yf: Any | None, trace_samples: list[str], chunk_size: int = 25) -> pd.DataFrame:
    rows = []
    if yf is None:
        diagnostics.append({"mode": "yfinance_batch", "ticker": "", "status": "IMPORT_FAILED", "detail": "yfinance import failed"})
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        label = " ".join(chunk)
        data, stderr_text, exc_text = yf_download(yf, label, start=TARGET_DATE, end=TARGET_END, interval="1d", progress=False, auto_adjust=False, group_by="ticker", threads=False)
        detail = (exc_text or stderr_text).strip()
        if detail and len(trace_samples) < 20:
            trace_samples.append(f"BATCH {'|'.join(chunk)}\n{detail}\n")
        added = 0
        if isinstance(data.columns, pd.MultiIndex):
            for ticker in chunk:
                if ticker not in data.columns.get_level_values(0):
                    continue
                sub = data[ticker].reset_index()
                for rec in sub.to_dict("records"):
                    row = make_row(ticker, rec, "yfinance_batch")
                    if row:
                        rows.append(row)
                        added += 1
        else:
            sub = data.reset_index() if data is not None and not data.empty else pd.DataFrame()
            if len(chunk) == 1:
                for rec in sub.to_dict("records"):
                    row = make_row(chunk[0], rec, "yfinance_batch")
                    if row:
                        rows.append(row)
                        added += 1
        if added:
            status = "SUCCESS"
        elif operational_error_text(detail):
            status = "OPERATIONAL_ERROR"
        elif exc_text:
            status = "ERROR"
        else:
            status = "EMPTY"
        diagnostics.append({"mode": "yfinance_batch", "ticker": "|".join(chunk), "status": status, "detail": (detail or f"rows={added}")[:500]})
    return normalize(pd.DataFrame(rows)) if rows else pd.DataFrame(columns=CANONICAL_FIELDS)


def discover_project_fetch_utilities() -> list[dict[str, Any]]:
    rows = []
    for path in (ROOT / "scripts").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        if "yfinance" in text or "download(" in text or "price" in path.name.lower():
            rows.append({"mode": "project_fetch_utility_scan", "ticker": "", "status": "FOUND", "detail": rel(path)})
    return rows


def candidate_valid(base: pd.DataFrame, candidate: pd.DataFrame, append_rows: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    append_unique = append_rows.drop_duplicates(["symbol", "date"]) if len(append_rows) else append_rows
    coverage = float(append_unique["symbol"].nunique() / base["symbol"].nunique()) if len(base) else 0.0
    details = {
        "append_ticker_coverage_ratio": coverage,
        "duplicate_symbol_date_rows": int(candidate.duplicated(["symbol", "date"]).sum()) if len(candidate) else 0,
        "candidate_panel_latest_date": str(candidate["date"].max()) if len(candidate) else "",
        "candidate_panel_rows": int(len(candidate)),
        "candidate_panel_ticker_count": int(candidate["symbol"].nunique()) if len(candidate) else 0,
        "zero_or_negative_close_rows": int((pd.to_numeric(candidate["close"], errors="coerce") <= 0).sum()) if len(candidate) else 0,
        "all_null_ohlcv_rows": int(candidate[OHLCV].isna().all(axis=1).sum()) if len(candidate) else 0,
    }
    valid = (
        details["candidate_panel_latest_date"] == TARGET_DATE
        and len(append_unique) > 0
        and details["duplicate_symbol_date_rows"] == 0
        and len(candidate) > len(base)
        and details["candidate_panel_ticker_count"] >= 300
        and coverage >= 0.80
        and details["all_null_ohlcv_rows"] == 0
        and details["zero_or_negative_close_rows"] == 0
    )
    return valid, details


def apply_candidate(candidate_path: Path, base: pd.DataFrame, candidate: pd.DataFrame, valid: bool) -> dict[str, Any]:
    requested = os.environ.get(APPLY_ENV, "").upper() == "TRUE"
    audit = {
        "canonical_apply_requested": requested,
        "canonical_apply_succeeded": False,
        "backup_created": False,
        "restored_after_failed_apply": False,
        "backup_path": "",
        "apply_note": "",
    }
    if not requested:
        audit["apply_note"] = f"Dry mode. Set {APPLY_ENV}=TRUE after validation."
        return audit
    if not valid:
        audit["apply_note"] = "REFUSED_INVALID_CANDIDATE"
        return audit
    backup = OUT / "canonical_backup_before_v21_190_apply.csv"
    shutil.copy2(CANONICAL, backup)
    audit["backup_created"] = True
    audit["backup_path"] = rel(backup)
    shutil.copy2(candidate_path, CANONICAL)
    after = load_canonical()
    still_valid, _ = candidate_valid(base, after, after[after["date"].eq(TARGET_DATE)])
    if still_valid:
        audit["canonical_apply_succeeded"] = True
        audit["apply_note"] = "APPLIED_AND_VERIFIED"
    else:
        shutil.copy2(backup, CANONICAL)
        audit["restored_after_failed_apply"] = True
        audit["apply_note"] = "VERIFY_FAILED_RESTORED_BACKUP"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"canonical_latest_date_before={summary['canonical_latest_date_before']}",
        f"candidate_panel_latest_date={summary['candidate_panel_latest_date']}",
        f"canonical_latest_date_after={summary['canonical_latest_date_after']}",
        f"append_rows_created={summary['append_rows_created']}",
        f"append_ticker_coverage_ratio={summary['append_ticker_coverage_ratio']}",
        f"candidate_panel_valid={summary['candidate_panel_valid']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.190_alternate_daily_bar_source_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    yf, cache_diag, import_error = configure_yfinance_cache()
    base = load_canonical()
    before_audit = audit_frame(base, CANONICAL)
    write_csv(OUT / "canonical_before_v21_190_audit.csv", [before_audit])
    symbols = set(base["symbol"].astype(str)) if len(base) else set()

    inventory, local_rows = local_inventory(symbols)
    write_csv(OUT / "local_20260630_price_file_inventory.csv", inventory)

    diagnostics = discover_project_fetch_utilities()
    health_rows, trace_samples, health_summary = healthcheck(yf)
    write_csv(OUT / "provider_healthcheck_20260630.csv", health_rows, ["ticker", "status", "rows", "operational_error", "detail"])
    provider_modes_attempted = ["local_inventory", "project_fetch_utility_scan", "yfinance_healthcheck"]
    provider_frames = [local_rows]
    remaining = sorted(symbols - set(local_rows["symbol"].astype(str))) if len(local_rows) else sorted(symbols)
    health_all_operational = bool(health_rows) and all(bool(row.get("operational_error")) for row in health_rows)
    if remaining and not health_all_operational:
        provider_modes_attempted.append("yfinance_direct")
        direct = yfinance_direct(remaining, diagnostics, yf, trace_samples)
        provider_frames.append(direct)
        remaining = sorted(set(remaining) - set(direct["symbol"].astype(str))) if len(direct) else remaining
    if remaining and not health_all_operational:
        provider_modes_attempted.append("yfinance_batch")
        batch = yfinance_batch(remaining, diagnostics, yf, trace_samples)
        provider_frames.append(batch)

    append_rows = normalize(pd.concat(provider_frames, ignore_index=True)) if provider_frames else pd.DataFrame(columns=CANONICAL_FIELDS)
    append_rows = append_rows[append_rows["date"].eq(TARGET_DATE) & append_rows["symbol"].isin(symbols)].drop_duplicates(["symbol", "date"], keep="first")
    success_symbols = sorted(set(append_rows["symbol"].astype(str))) if len(append_rows) else []
    failed_symbols = sorted(symbols - set(success_symbols))
    success_rows = append_rows.to_dict("records")
    failed_rows = [{"ticker": s, "failure_type": "NO_20260630_DAILY_BAR", "failure_reason": "No local/provider completed daily OHLCV row found."} for s in failed_symbols]
    write_csv(OUT / "provider_mode_diagnostics.csv", diagnostics, ["mode", "ticker", "status", "detail"])
    exception_sample = "\n".join(trace_samples).strip()
    (OUT / "provider_exception_trace_sample.txt").write_text(exception_sample + ("\n" if exception_sample else ""), encoding="utf-8")
    write_csv(OUT / "provider_success_rows_20260630.csv", success_rows, CANONICAL_FIELDS)
    write_csv(OUT / "provider_failed_tickers_20260630.csv", failed_rows, ["ticker", "failure_type", "failure_reason"])
    append_rows.to_csv(OUT / "candidate_append_rows_20260630.csv", index=False)

    candidate = normalize(pd.concat([base, append_rows], ignore_index=True)) if len(append_rows) else base.copy()
    candidate_path = OUT / "candidate_canonical_through_20260630.csv"
    candidate.to_csv(candidate_path, index=False)
    valid, detail = candidate_valid(base, candidate, append_rows)
    candidate_audit = {**audit_frame(candidate, candidate_path), **detail, "candidate_panel_valid": valid}
    write_csv(OUT / "candidate_canonical_audit.csv", [candidate_audit])
    apply_audit = apply_candidate(candidate_path, base, candidate, valid)
    write_csv(OUT / "canonical_apply_audit.csv", [apply_audit])
    after = load_canonical()
    after_latest = str(after["date"].max()) if len(after) else ""

    modes_succeeded = []
    if len(local_rows):
        modes_succeeded.append("local_inventory")
    if any(d.get("mode") == "yfinance_direct" and d.get("status") == "SUCCESS" for d in diagnostics):
        modes_succeeded.append("yfinance_direct")
    if any(d.get("mode") == "yfinance_batch" and d.get("status") == "SUCCESS" for d in diagnostics):
        modes_succeeded.append("yfinance_batch")
    operational_error_count = sum(
        1
        for row in [*diagnostics, *health_rows]
        if operational_error_text(str(row.get("detail", ""))) or str(row.get("status", "")).upper() == "OPERATIONAL_ERROR"
    )
    first_operational_error_message = ""
    for row in [*health_rows, *diagnostics]:
        if operational_error_text(str(row.get("detail", ""))) or str(row.get("status", "")).upper() == "OPERATIONAL_ERROR":
            first_operational_error_message = str(row.get("detail", ""))[:500]
            break
    cache_diag.update({
        "operational_error_count": operational_error_count,
        "first_operational_error_message": first_operational_error_message,
        "provider_healthcheck_attempted": bool(health_summary["attempted"]),
        "provider_healthcheck_success_count": int(health_summary["success_count"]),
        "provider_healthcheck_failed_count": int(health_summary["failed_count"]),
    })
    write_json(OUT / "yfinance_cache_diagnostic.json", cache_diag)

    if valid and not apply_audit["canonical_apply_requested"]:
        final_status = "PARTIAL_PASS_V21_190_R1_20260630_CANDIDATE_READY_NOT_APPLIED"
        final_decision = "CANDIDATE_20260630_APPEND_READY_FOR_GUARDED_APPLY"
    elif valid and apply_audit["canonical_apply_succeeded"]:
        final_status = "PASS_V21_190_R1_CANONICAL_APPENDED_TO_20260630"
        final_decision = "CANONICAL_20260630_READY_FOR_ABCDE_RERUN_RESEARCH_ONLY"
    elif health_all_operational:
        final_status = "FAIL_V21_190_R1_YFINANCE_CACHE_OR_SQLITE_FAILURE"
        final_decision = "FIX_LOCAL_YFINANCE_CACHE_OR_USE_MANUAL_APPROVED_PRICE_SOURCE"
    elif len(append_rows) == 0:
        final_status = "PARTIAL_PASS_V21_190_R1_PROVIDER_NO_20260630_DATA"
        final_decision = "WAIT_FOR_PROVIDER_OR_MANUAL_APPROVED_PRICE_SOURCE"
    else:
        final_status = "FAIL_V21_190_CANDIDATE_VALIDATION_FAILED"
        final_decision = "DO_NOT_APPLY_INVALID_PRICE_PANEL"

    summary = {
        "stage": STAGE,
        "r1_patch_applied": True,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_latest_date_before": before_audit["max_date"],
        "expected_append_date": TARGET_DATE,
        "local_inventory_files_scanned": len(inventory),
        "local_20260630_rows_found": int(len(local_rows)),
        "provider_modes_attempted": provider_modes_attempted,
        "provider_modes_succeeded": modes_succeeded,
        "provider_success_ticker_count": len(success_symbols),
        "provider_failed_ticker_count": len(failed_symbols),
        "append_rows_created": int(len(append_rows)),
        "append_ticker_coverage_ratio": detail["append_ticker_coverage_ratio"],
        "candidate_panel_created": candidate_path.is_file() and len(candidate) > 0,
        "candidate_panel_valid": bool(valid),
        "candidate_panel_latest_date": detail["candidate_panel_latest_date"],
        "candidate_panel_rows": detail["candidate_panel_rows"],
        "candidate_panel_ticker_count": detail["candidate_panel_ticker_count"],
        "duplicate_symbol_date_rows": detail["duplicate_symbol_date_rows"],
        "canonical_apply_requested": bool(apply_audit["canonical_apply_requested"]),
        "canonical_apply_succeeded": bool(apply_audit["canonical_apply_succeeded"]),
        "canonical_latest_date_after": after_latest,
        "backup_created": bool(apply_audit["backup_created"]),
        "restored_after_failed_apply": bool(apply_audit["restored_after_failed_apply"]),
        "yfinance_cache_dir": cache_diag["yfinance_cache_dir"],
        "cache_dir_exists": bool(cache_diag["cache_dir_exists"]),
        "cache_dir_writable": bool(cache_diag["cache_dir_writable"]),
        "cache_probe_file_created": bool(cache_diag["cache_probe_file_created"]),
        "yfinance_cache_location_set": bool(cache_diag["yfinance_cache_location_set"]),
        "provider_healthcheck_attempted": bool(cache_diag["provider_healthcheck_attempted"]),
        "provider_healthcheck_success_count": int(cache_diag["provider_healthcheck_success_count"]),
        "provider_healthcheck_failed_count": int(cache_diag["provider_healthcheck_failed_count"]),
        "operational_error_count": int(cache_diag["operational_error_count"]),
        "first_operational_error_message": cache_diag["first_operational_error_message"],
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
    }
    write_json(OUT / "v21_190_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "provider_modes_attempted", "provider_modes_succeeded",
        "provider_success_ticker_count", "provider_failed_ticker_count", "append_rows_created",
        "append_ticker_coverage_ratio", "candidate_panel_valid", "candidate_panel_latest_date",
        "canonical_latest_date_after", "official_adoption_allowed", "broker_action_allowed",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
