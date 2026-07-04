#!/usr/bin/env python
"""V21.196 R1 public-source/manual CSV builder for approved broad OHLCV import."""

from __future__ import annotations

import csv
import json
import os
import shutil
import ssl
import subprocess
import time
import traceback
import urllib.parse
import urllib.request
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.196_R1_PUBLIC_SOURCE_MANUAL_CSV_BUILDER_AND_VALIDATOR"
OUT = ROOT / "outputs/v21/V21.196_R1_PUBLIC_SOURCE_MANUAL_CSV_BUILDER_AND_VALIDATOR"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
MANUAL_DIR = ROOT / "inputs/manual_price_sources"
CANDIDATE_PATH = MANUAL_DIR / "candidate_daily_ohlcv_20260629_20260630.csv"
APPROVED_PATH = MANUAL_DIR / "approved_daily_ohlcv_20260629_20260630.csv"
LOCAL_RAW_FILES = [
    MANUAL_DIR / "raw_vendor_ohlcv_20260629_20260630.csv",
    MANUAL_DIR / "raw_moomoo_ohlcv_20260629_20260630.csv",
    MANUAL_DIR / "raw_broker_ohlcv_20260629_20260630.csv",
]
APPROVE_ENV = "V21_196_R1_APPROVE_AUTOBUILT_CSV"
TARGET_DATES = ["2026-06-29", "2026-06-30"]
MIN_COVERAGE_RATIO = 0.80
HTTP_TIMEOUT_SECONDS = 3
PROVIDER_EXCEPTION_ABORT_THRESHOLD = 4
REQUIRED = ["symbol", "date", "open", "high", "low", "close", "volume"]
AUDIT_COLS = REQUIRED + ["source_provider", "source_url", "source_file", "source_confidence", "cross_validation_status"]


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


def git_status() -> list[str]:
    proc = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed = {
        "?? scripts/v21/v21_196_r1_public_source_manual_csv_builder_and_validator.py",
        "?? scripts/v21/run_v21_196_r1_public_source_manual_csv_builder_and_validator.ps1",
        "?? scripts/v21/test_v21_196_r1_public_source_manual_csv_builder_and_validator.py",
    }
    allowed_prefixes = (
        "?? outputs/v21/V21.196_R1_PUBLIC_SOURCE_MANUAL_CSV_BUILDER_AND_VALIDATOR/",
        "?? inputs/manual_price_sources/candidate_daily_ohlcv_20260629_20260630.csv",
        "?? inputs/manual_price_sources/approved_daily_ohlcv_20260629_20260630.csv",
        " M inputs/manual_price_sources/candidate_daily_ohlcv_20260629_20260630.csv",
        " M inputs/manual_price_sources/approved_daily_ohlcv_20260629_20260630.csv",
    )
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized in allowed or normalized.startswith(allowed_prefixes):
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def load_canonical_universe(path: Path = CANONICAL) -> list[str]:
    df = pd.read_csv(path, usecols=["symbol"], low_memory=False)
    return sorted(df["symbol"].dropna().astype(str).str.upper().str.strip().unique())


def stooq_symbol(symbol: str) -> str:
    mapped = symbol.strip().lower().replace(".", "-")
    return f"{mapped}.us"


def normalize_provider_rows(raw: pd.DataFrame, provider: str, source_url: str = "", source_file: str = "") -> pd.DataFrame:
    rename = {}
    for col in raw.columns:
        low = str(col).strip().lower().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low == "date":
            rename[col] = "date"
        elif low in {"adj_close", "adjclose", "adjusted_close"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    frame = raw.rename(columns=rename).copy()
    if "symbol" not in frame:
        frame["symbol"] = ""
    for col in REQUIRED:
        if col not in frame:
            frame[col] = pd.NA
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["source_provider"] = provider
    frame["source_url"] = source_url
    frame["source_file"] = source_file
    frame["source_confidence"] = "USER_APPROVED_LOCAL_VENDOR" if provider.startswith("LOCAL_") else "PUBLIC_DAILY_ENDPOINT"
    return frame[AUDIT_COLS[:-1]].copy()


def http_get(url: str, timeout: int = HTTP_TIMEOUT_SECONDS) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 V21.196 research"})
    context = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_stooq(symbols: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[pd.DataFrame] = []
    attempts: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    exceptions: list[str] = []
    for symbol in symbols:
        if len(exceptions) >= PROVIDER_EXCEPTION_ABORT_THRESHOLD:
            failed.append({"symbol": symbol, "provider_mode": "stooq_direct", "failure_reason": "PROVIDER_ABORTED_AFTER_REPEATED_EXCEPTIONS"})
            attempts.append({"provider_mode": "stooq_direct", "symbol": symbol, "status": "SKIPPED_PROVIDER_ABORTED", "url": ""})
            continue
        mapped = stooq_symbol(symbol)
        url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(mapped)}&d1=20260629&d2=20260630&i=d"
        try:
            text = http_get(url)
            parsed = pd.read_csv(StringIO(text))
            if parsed.empty or "Date" not in parsed.columns:
                attempts.append({"provider_mode": "stooq_direct", "symbol": symbol, "status": "EMPTY_OR_SCHEMA_MISMATCH", "url": url})
                failed.append({"symbol": symbol, "provider_mode": "stooq_direct", "failure_reason": "EMPTY_OR_SCHEMA_MISMATCH"})
                continue
            parsed["symbol"] = symbol
            norm = normalize_provider_rows(parsed, "STOOQ_DIRECT_DAILY_CSV", source_url=url)
            norm = norm[norm["date"].isin(TARGET_DATES)]
            if norm.empty:
                attempts.append({"provider_mode": "stooq_direct", "symbol": symbol, "status": "NO_TARGET_DATE_ROWS", "url": url})
                failed.append({"symbol": symbol, "provider_mode": "stooq_direct", "failure_reason": "NO_TARGET_DATE_ROWS"})
            else:
                rows.append(norm)
                attempts.append({"provider_mode": "stooq_direct", "symbol": symbol, "status": "SUCCESS", "url": url, "row_count": len(norm)})
        except Exception as exc:
            attempts.append({"provider_mode": "stooq_direct", "symbol": symbol, "status": "EXCEPTION", "url": url, "detail": str(exc)})
            failed.append({"symbol": symbol, "provider_mode": "stooq_direct", "failure_reason": str(exc)})
            if len(exceptions) < 10:
                exceptions.append(f"STOOQ {symbol} {url}\n{traceback.format_exc()}")
        time.sleep(0.02)
    return (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=AUDIT_COLS[:-1]), attempts, failed, exceptions)


def fetch_yahoo_chart(symbols: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    exceptions: list[str] = []
    # 2026-06-29 00:00 UTC to 2026-07-01 00:00 UTC.
    p1, p2 = 1782691200, 1782864000
    for symbol in symbols:
        if len(exceptions) >= PROVIDER_EXCEPTION_ABORT_THRESHOLD:
            failed.append({"symbol": symbol, "provider_mode": "yahoo_chart", "failure_reason": "PROVIDER_ABORTED_AFTER_REPEATED_EXCEPTIONS"})
            attempts.append({"provider_mode": "yahoo_chart", "symbol": symbol, "status": "SKIPPED_PROVIDER_ABORTED", "url": ""})
            continue
        yahoo_symbol = symbol.replace(".", "-")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}?period1={p1}&period2={p2}&interval=1d&events=history&includeAdjustedClose=true"
        try:
            payload = json.loads(http_get(url))
            result = (payload.get("chart", {}).get("result") or [None])[0]
            if not result:
                attempts.append({"provider_mode": "yahoo_chart", "symbol": symbol, "status": "EMPTY_RESULT", "url": url})
                failed.append({"symbol": symbol, "provider_mode": "yahoo_chart", "failure_reason": "EMPTY_RESULT"})
                continue
            timestamps = result.get("timestamp") or []
            quote = (result.get("indicators", {}).get("quote") or [{}])[0]
            adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
            for idx, ts in enumerate(timestamps):
                date = pd.to_datetime(int(ts), unit="s", utc=True).strftime("%Y-%m-%d")
                if date not in TARGET_DATES:
                    continue
                rows.append({
                    "symbol": symbol,
                    "date": date,
                    "open": quote.get("open", [None] * len(timestamps))[idx],
                    "high": quote.get("high", [None] * len(timestamps))[idx],
                    "low": quote.get("low", [None] * len(timestamps))[idx],
                    "close": quote.get("close", [None] * len(timestamps))[idx],
                    "volume": quote.get("volume", [None] * len(timestamps))[idx],
                    "source_provider": "YAHOO_CHART_DIRECT",
                    "source_url": url,
                    "source_file": "",
                    "source_confidence": "PUBLIC_DAILY_ENDPOINT",
                })
            attempts.append({"provider_mode": "yahoo_chart", "symbol": symbol, "status": "SUCCESS" if rows else "NO_TARGET_DATE_ROWS", "url": url})
        except Exception as exc:
            attempts.append({"provider_mode": "yahoo_chart", "symbol": symbol, "status": "EXCEPTION", "url": url, "detail": str(exc)})
            failed.append({"symbol": symbol, "provider_mode": "yahoo_chart", "failure_reason": str(exc)})
            if len(exceptions) < 10:
                exceptions.append(f"YAHOO {symbol} {url}\n{traceback.format_exc()}")
        time.sleep(0.02)
    return pd.DataFrame(rows, columns=AUDIT_COLS[:-1]), attempts, failed, exceptions


def load_local_sources() -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[pd.DataFrame] = []
    attempts: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    exceptions: list[str] = []
    for path in LOCAL_RAW_FILES:
        if not path.is_file():
            attempts.append({"provider_mode": "local_user_approved", "symbol": "", "status": "FILE_MISSING", "source_file": rel(path)})
            continue
        try:
            raw = pd.read_csv(path)
            provider = f"LOCAL_{path.stem.upper()}"
            norm = normalize_provider_rows(raw, provider, source_file=rel(path))
            norm = norm[norm["date"].isin(TARGET_DATES)]
            rows.append(norm)
            attempts.append({"provider_mode": "local_user_approved", "symbol": "", "status": "SUCCESS", "source_file": rel(path), "row_count": len(norm)})
        except Exception as exc:
            attempts.append({"provider_mode": "local_user_approved", "symbol": "", "status": "EXCEPTION", "source_file": rel(path), "detail": str(exc)})
            failed.append({"symbol": "", "provider_mode": "local_user_approved", "failure_reason": str(exc)})
            exceptions.append(f"LOCAL {path}\n{traceback.format_exc()}")
    return (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=AUDIT_COLS[:-1]), attempts, failed, exceptions)


def optional_api_attempts() -> list[dict[str, Any]]:
    key_map = {
        "POLYGON_API_KEY": "polygon",
        "ALPHAVANTAGE_API_KEY": "alphavantage",
        "EODHD_API_KEY": "eodhd",
        "NASDAQ_DATA_LINK_API_KEY": "nasdaq_data_link",
    }
    rows = []
    for env, name in key_map.items():
        rows.append({
            "provider_mode": name,
            "symbol": "",
            "status": "KEY_PRESENT_NOT_USED_IN_R1" if os.environ.get(env) else "KEY_MISSING_OPTIONAL",
            "detail": env,
        })
    return rows


def validate_ohlcv_rows(frame: pd.DataFrame, canonical_symbols: set[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame]:
    if frame.empty:
        return frame.copy(), [], frame.copy()
    normalized = normalize_provider_rows(frame, "VALIDATION_RENORMALIZED")
    for col in ["source_provider", "source_url", "source_file", "source_confidence"]:
        if col in frame:
            normalized[col] = frame[col].values
    errors: list[dict[str, Any]] = []
    valid_mask = pd.Series(True, index=normalized.index)
    for idx, row in normalized.iterrows():
        row_errors: list[str] = []
        symbol = str(row["symbol"])
        date = str(row["date"])
        if date not in TARGET_DATES:
            row_errors.append("DATE_NOT_ALLOWED")
        if symbol not in canonical_symbols:
            row_errors.append("SYMBOL_NOT_IN_CANONICAL_UNIVERSE")
        for col in ["open", "high", "low", "close", "volume"]:
            if pd.isna(row[col]):
                row_errors.append(f"{col.upper()}_NOT_NUMERIC")
        for col in ["open", "high", "low", "close"]:
            if not pd.isna(row[col]) and float(row[col]) <= 0:
                row_errors.append(f"{col.upper()}_NON_POSITIVE")
        if not pd.isna(row["volume"]) and float(row["volume"]) < 0:
            row_errors.append("VOLUME_NEGATIVE")
        if not any(pd.isna(row[col]) for col in ["open", "high", "low", "close"]):
            if float(row["high"]) < float(row["low"]):
                row_errors.append("HIGH_BELOW_LOW")
            if float(row["high"]) < float(row["open"]) or float(row["high"]) < float(row["close"]):
                row_errors.append("HIGH_BELOW_OPEN_OR_CLOSE")
            if float(row["low"]) > float(row["open"]) or float(row["low"]) > float(row["close"]):
                row_errors.append("LOW_ABOVE_OPEN_OR_CLOSE")
        if row_errors:
            valid_mask.loc[idx] = False
            errors.append({"symbol": symbol, "date": date, "source_provider": row.get("source_provider", ""), "error": "|".join(row_errors)})
    return normalized.loc[valid_mask].copy(), errors, normalized.loc[~valid_mask].copy()


def cross_validate(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    if frame.empty:
        return frame.copy(), [], 0
    accepted: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    conflict_rejected = 0
    for (symbol, date), group in frame.groupby(["symbol", "date"], sort=True):
        providers = sorted(group["source_provider"].astype(str).unique())
        if group.duplicated(["symbol", "date", "source_provider"], keep=False).any():
            conflict_rejected += len(group)
            audit.append({"symbol": symbol, "date": date, "providers": "|".join(providers), "status": "DUPLICATE_PROVIDER_SYMBOL_DATE_REJECTED", "close_diff_pct": ""})
            continue
        local = group[group["source_provider"].astype(str).str.startswith("LOCAL_")]
        if len(group) == 1:
            row = group.iloc[0].to_dict()
            row["cross_validation_status"] = "SINGLE_SOURCE_ACCEPTED"
            accepted.append(row)
            audit.append({"symbol": symbol, "date": date, "providers": "|".join(providers), "status": "SINGLE_SOURCE_ACCEPTED", "close_diff_pct": 0.0})
            continue
        closes = pd.to_numeric(group["close"], errors="coerce")
        diff = (float(closes.max()) - float(closes.min())) / float(closes.mean()) if float(closes.mean()) else 999.0
        if diff <= 0.005:
            row = group.iloc[0].to_dict()
            row["cross_validation_status"] = "CROSS_VALIDATED"
            accepted.append(row)
            audit.append({"symbol": symbol, "date": date, "providers": "|".join(providers), "status": "CROSS_VALIDATED", "close_diff_pct": diff})
        elif not local.empty:
            row = local.iloc[0].to_dict()
            row["cross_validation_status"] = "LOCAL_VENDOR_CONFLICT_OVERRIDE"
            accepted.append(row)
            audit.append({"symbol": symbol, "date": date, "providers": "|".join(providers), "status": "LOCAL_VENDOR_CONFLICT_OVERRIDE", "close_diff_pct": diff})
        else:
            conflict_rejected += len(group)
            audit.append({"symbol": symbol, "date": date, "providers": "|".join(providers), "status": "CONFLICT_REJECTED", "close_diff_pct": diff})
    return pd.DataFrame(accepted, columns=AUDIT_COLS), audit, conflict_rejected


def coverage_rows(frame: pd.DataFrame, canonical_count: int) -> list[dict[str, Any]]:
    rows = []
    for date in TARGET_DATES:
        count = int(frame.loc[frame["date"].eq(date), "symbol"].nunique()) if not frame.empty else 0
        ratio = count / canonical_count if canonical_count else 0.0
        rows.append({"date": date, "symbol_count": count, "canonical_symbol_count": canonical_count, "coverage_ratio": ratio, "broad_eligible": ratio >= MIN_COVERAGE_RATIO})
    return rows


def write_candidate_files(candidate: pd.DataFrame) -> None:
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    candidate.to_csv(CANDIDATE_PATH, index=False)
    candidate.to_csv(OUT / "candidate_daily_ohlcv_20260629_20260630_with_audit_columns.csv", index=False)
    candidate[REQUIRED].to_csv(OUT / "candidate_daily_ohlcv_20260629_20260630_approved_schema.csv", index=False)


def maybe_approve(candidate_valid: bool) -> dict[str, Any]:
    requested = os.environ.get(APPROVE_ENV, "").upper() == "TRUE"
    audit = {
        "approved_write_requested": requested,
        "approved_write_succeeded": False,
        "candidate_path": rel(CANDIDATE_PATH),
        "approved_path": rel(APPROVED_PATH),
        "write_note": "",
    }
    if not requested:
        audit["write_note"] = f"Dry mode. Set {APPROVE_ENV}=TRUE after review."
        return audit
    if not candidate_valid or not CANDIDATE_PATH.is_file():
        audit["write_note"] = "REFUSED_INVALID_OR_MISSING_CANDIDATE"
        return audit
    APPROVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANDIDATE_PATH, APPROVED_PATH)
    audit["approved_write_succeeded"] = APPROVED_PATH.is_file()
    audit["write_note"] = "APPROVED_CSV_WRITTEN" if audit["approved_write_succeeded"] else "WRITE_FAILED"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"provider_modes_attempted={summary['provider_modes_attempted']}",
        f"provider_modes_succeeded={summary['provider_modes_succeeded']}",
        f"candidate_valid={summary['candidate_valid']}",
        f"candidate_path={summary['candidate_path']}",
        f"approved_write_requested={summary['approved_write_requested']}",
        f"approved_write_succeeded={summary['approved_write_succeeded']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.196_R1_public_source_manual_csv_builder_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    baseline = git_status()
    symbols = load_canonical_universe()
    canonical_symbols = set(symbols)
    write_csv(OUT / "canonical_universe_for_manual_csv.csv", [{"symbol": s} for s in symbols], ["symbol"])
    write_csv(OUT / "symbol_mapping_audit.csv", [{"symbol": s, "stooq_symbol": stooq_symbol(s), "yahoo_symbol": s.replace(".", "-")} for s in symbols])

    all_attempts: list[dict[str, Any]] = []
    all_failed: list[dict[str, Any]] = []
    exception_samples: list[str] = []
    frames: list[pd.DataFrame] = []

    local_rows, attempts, failed, exceptions = load_local_sources()
    frames.append(local_rows)
    all_attempts += attempts
    all_failed += failed
    exception_samples += exceptions

    stooq_rows, attempts, failed, exceptions = fetch_stooq(symbols)
    frames.append(stooq_rows)
    all_attempts += attempts
    all_failed += failed
    exception_samples += exceptions

    yahoo_rows, attempts, failed, exceptions = fetch_yahoo_chart(symbols)
    frames.append(yahoo_rows)
    all_attempts += attempts
    all_failed += failed
    exception_samples += exceptions

    all_attempts += optional_api_attempts()

    raw = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame(columns=AUDIT_COLS[:-1])
    raw.to_csv(OUT / "provider_success_rows_raw.csv", index=False)
    write_csv(OUT / "provider_fetch_attempts.csv", all_attempts)
    write_csv(OUT / "provider_failed_symbols.csv", all_failed, ["symbol", "provider_mode", "failure_reason"])
    (OUT / "provider_exception_samples.txt").write_text("\n\n".join(exception_samples[:20]) + ("\n" if exception_samples else ""), encoding="utf-8")

    valid_source_rows, validation_errors, _rejected = validate_ohlcv_rows(raw, canonical_symbols)
    candidate, cross_audit, conflict_rejected = cross_validate(valid_source_rows)
    candidate = candidate.sort_values(["symbol", "date"]).reset_index(drop=True) if not candidate.empty else pd.DataFrame(columns=AUDIT_COLS)
    duplicate_count = int(candidate.duplicated(["symbol", "date"]).sum()) if not candidate.empty else 0
    if duplicate_count:
        validation_errors.append({"symbol": "", "date": "", "source_provider": "", "error": "CANDIDATE_DUPLICATE_SYMBOL_DATE_ROWS"})
    coverage = coverage_rows(candidate, len(symbols))
    write_csv(OUT / "cross_validation_audit.csv", cross_audit)
    write_csv(OUT / "candidate_validation_errors.csv", validation_errors, ["symbol", "date", "source_provider", "error"])
    write_csv(OUT / "candidate_per_date_coverage_audit.csv", coverage)

    candidate_created = not candidate.empty
    if candidate_created:
        write_candidate_files(candidate)
    else:
        write_candidate_files(pd.DataFrame(columns=AUDIT_COLS))

    by_date = {row["date"]: row for row in coverage}
    candidate_valid = (
        candidate_created
        and duplicate_count == 0
        and len(validation_errors) == 0
        and by_date["2026-06-29"]["coverage_ratio"] >= MIN_COVERAGE_RATIO
        and by_date["2026-06-30"]["coverage_ratio"] >= MIN_COVERAGE_RATIO
    )
    approve_audit = maybe_approve(candidate_valid)
    write_csv(OUT / "approved_csv_write_audit.csv", [approve_audit])

    modes_attempted = sorted({str(row.get("provider_mode", "")) for row in all_attempts if row.get("provider_mode")})
    modes_succeeded = sorted({str(row.get("provider_mode", "")) for row in all_attempts if row.get("status") == "SUCCESS"})
    stooq_success = int(stooq_rows["symbol"].nunique()) if not stooq_rows.empty else 0
    yahoo_success = int(yahoo_rows["symbol"].nunique()) if not yahoo_rows.empty else 0
    local_success = int(local_rows["symbol"].nunique()) if not local_rows.empty else 0
    optional_success = 0
    cross_validated_count = int((candidate["cross_validation_status"] == "CROSS_VALIDATED").sum()) if not candidate.empty else 0
    single_source_count = int((candidate["cross_validation_status"] == "SINGLE_SOURCE_ACCEPTED").sum()) if not candidate.empty else 0

    if candidate_valid and approve_audit["approved_write_succeeded"]:
        final_status = "PASS_V21_196_R1_APPROVED_CSV_CREATED"
        final_decision = "APPROVED_MANUAL_PRICE_CSV_READY_FOR_V21_196_IMPORT"
    elif candidate_valid:
        final_status = "PARTIAL_PASS_V21_196_R1_CANDIDATE_CSV_READY_NOT_APPROVED"
        final_decision = "REVIEW_CANDIDATE_THEN_SET_APPROVE_FLAG_FOR_V21_196_IMPORT"
    elif validation_errors and candidate_created:
        final_status = "FAIL_V21_196_R1_CANDIDATE_CSV_VALIDATION_FAILED"
        final_decision = "DO_NOT_IMPORT_INVALID_PRICE_CSV"
    else:
        final_status = "PARTIAL_PASS_V21_196_R1_INSUFFICIENT_PROVIDER_COVERAGE"
        final_decision = "PROVIDE_BROKER_VENDOR_CSV_OR_RETRY_CONNECTIVITY"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_symbol_count": len(symbols),
        "target_dates": TARGET_DATES,
        "provider_modes_attempted": modes_attempted,
        "provider_modes_succeeded": modes_succeeded,
        "stooq_success_symbol_count": stooq_success,
        "yahoo_chart_success_symbol_count": yahoo_success,
        "local_vendor_success_symbol_count": local_success,
        "optional_api_success_symbol_count": optional_success,
        "candidate_row_count": int(len(candidate)),
        "candidate_20260629_symbol_count": int(by_date["2026-06-29"]["symbol_count"]),
        "candidate_20260630_symbol_count": int(by_date["2026-06-30"]["symbol_count"]),
        "candidate_20260629_coverage_ratio": float(by_date["2026-06-29"]["coverage_ratio"]),
        "candidate_20260630_coverage_ratio": float(by_date["2026-06-30"]["coverage_ratio"]),
        "duplicate_symbol_date_rows": duplicate_count,
        "validation_error_count": len(validation_errors),
        "cross_validated_row_count": cross_validated_count,
        "single_source_accepted_row_count": single_source_count,
        "conflict_rejected_row_count": conflict_rejected,
        "candidate_created": candidate_created,
        "candidate_valid": candidate_valid,
        "candidate_path": rel(CANDIDATE_PATH),
        "approved_write_requested": bool(approve_audit["approved_write_requested"]),
        "approved_write_succeeded": bool(approve_audit["approved_write_succeeded"]),
        "approved_path": rel(APPROVED_PATH),
        "ready_for_v21_196_import": bool(approve_audit["approved_write_succeeded"]),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": protected_modified(git_status(), baseline),
    }
    write_json(OUT / "v21_196_r1_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "provider_modes_attempted", "provider_modes_succeeded",
        "stooq_success_symbol_count", "yahoo_chart_success_symbol_count", "local_vendor_success_symbol_count",
        "candidate_20260629_symbol_count", "candidate_20260629_coverage_ratio",
        "candidate_20260630_symbol_count", "candidate_20260630_coverage_ratio",
        "cross_validated_row_count", "single_source_accepted_row_count", "conflict_rejected_row_count",
        "candidate_valid", "candidate_path", "approved_write_requested", "approved_write_succeeded",
        "approved_path", "official_adoption_allowed", "broker_action_allowed", "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
