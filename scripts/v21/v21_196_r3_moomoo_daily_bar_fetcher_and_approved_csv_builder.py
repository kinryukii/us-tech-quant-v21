#!/usr/bin/env python
"""V21.196 R3 Moomoo daily bar fetcher and approved CSV builder."""

from __future__ import annotations

import csv
import importlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.196_R3_MOOMOO_DAILY_BAR_FETCHER_AND_APPROVED_CSV_BUILDER"
OUT = ROOT / "outputs/v21/V21.196_R3_MOOMOO_DAILY_BAR_FETCHER_AND_APPROVED_CSV_BUILDER"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
MANUAL_DIR = ROOT / "inputs/manual_price_sources"
APPROVED_PATH = MANUAL_DIR / "approved_daily_ohlcv_20260629_20260630.csv"
APPROVE_ENV = "V21_196_R3_APPROVE_MOOMOO_CSV"
TRUST_EXPORT_ENV = "V21_196_R3_TRUST_MOOMOO_EXPORT_OVER_API"
HOST_ENV = "MOOMOO_OPEND_HOST"
PORT_ENV = "MOOMOO_OPEND_PORT"
DEDICATED_PYTHON_ENV = "V21_196_R3_MOOMOO_PYTHON_EXE"
FETCH_TIMEOUT_ENV = "V21_196_R3_MOOMOO_FETCH_TIMEOUT_SECONDS"
R4_READY_SUMMARY = ROOT / "outputs/v21/V21.196_R4A_MOOMOO_API_PACKAGE_NAME_AND_PY311_ENV_REPAIR/v21_196_r4a_summary.json"
TARGET_DATES = ["2026-06-29", "2026-06-30"]
OVERLAP_DATE = "2026-06-26"
HEALTHCHECK = ["QQQ", "AAPL", "MU", "AMAT"]
MIN_COVERAGE_RATIO = 0.80
REQUIRED = ["symbol", "date", "open", "high", "low", "close", "volume"]
AUDIT_COLS = REQUIRED + ["source_provider", "source_file", "moomoo_code", "autype", "cross_validation_status"]
RAW_EXPORTS = [
    "raw_moomoo_ohlcv_20260629_20260630.csv",
    "raw_moomoo_ohlcv_20260629.csv",
    "raw_moomoo_ohlcv_20260630.csv",
]

SYMBOL_ALIASES = {"symbol", "ticker", "code", "instrument", "instrument_code", "stock_code", "security_code", "銘柄コード", "コード", "股票代码", "代码"}
DATE_ALIASES = {"date", "time", "datetime", "trading_date", "trade_date", "日付", "日期"}
OPEN_ALIASES = {"open", "始値", "开盘价"}
HIGH_ALIASES = {"high", "高値", "最高价"}
LOW_ALIASES = {"low", "安値", "最低价"}
CLOSE_ALIASES = {"close", "last", "last_price", "終値", "收盘价"}
VOLUME_ALIASES = {"volume", "vol", "vol.", "出来高", "成交量"}


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


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_home = OUT / "moomoo_sdk_runtime_home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env["APPDATA"] = str(runtime_home)
    env["appdata"] = str(runtime_home)
    env["HOME"] = str(runtime_home)
    return env


def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout, env=subprocess_env())


def git_status() -> list[str]:
    proc = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.splitlines()


def parse_timeout(value: str | None, default: int = 600) -> int:
    try:
        return max(30, min(int(value or default), 3600))
    except ValueError:
        return default


def load_r4_readiness(path: Path = R4_READY_SUMMARY) -> dict[str, Any]:
    if not path.is_file():
        return {"r4_readiness_loaded": False, "r4_ready_to_rerun": False, "load_error": "R4_READY_SUMMARY_MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["r4_readiness_loaded"] = True
        payload["r4_ready_to_rerun"] = bool(payload.get("r3_ready_to_rerun"))
        return payload
    except Exception as exc:
        return {"r4_readiness_loaded": False, "r4_ready_to_rerun": False, "load_error": str(exc)}


def dedicated_python_from_readiness(readiness: dict[str, Any]) -> str:
    override = os.environ.get(DEDICATED_PYTHON_ENV, "").strip()
    if override:
        return override
    value = str(readiness.get("dedicated_python_executable", "")).strip()
    if value:
        return value
    return str(ROOT / ".venv_moomoo_py312/Scripts/python.exe")


def verify_dedicated_moomoo_import(python_exe: str) -> dict[str, Any]:
    audit = {"dedicated_python_executable": python_exe, "dedicated_python_import_succeeded": False, "returncode": None, "stdout_tail": "", "stderr_tail": ""}
    if not python_exe or not Path(python_exe).is_file():
        audit["stderr_tail"] = "DEDICATED_PYTHON_NOT_FOUND"
        return audit
    proc = run_command([python_exe, "-c", "from moomoo import *\nprint('MOOMOO_IMPORT_OK')"], 60)
    audit["returncode"] = proc.returncode
    audit["stdout_tail"] = (proc.stdout or "")[-4000:]
    audit["stderr_tail"] = (proc.stderr or "")[-4000:]
    audit["dedicated_python_import_succeeded"] = proc.returncode == 0 and "MOOMOO_IMPORT_OK" in (proc.stdout or "")
    return audit


def parse_subprocess_payload(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if text.startswith("{") and '"status"' in text:
            return json.loads(text)
    raise ValueError("subprocess JSON payload not found")


def read_csv_records_if_present(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    try:
        return pd.read_csv(path).to_dict("records")
    except pd.errors.EmptyDataError:
        return []


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefixes = (
        "?? outputs/v21/V21.196_R3_MOOMOO_DAILY_BAR_FETCHER_AND_APPROVED_CSV_BUILDER/",
        "?? inputs/manual_price_sources/approved_daily_ohlcv_20260629_20260630.csv",
        " M inputs/manual_price_sources/approved_daily_ohlcv_20260629_20260630.csv",
    )
    allowed_scripts = {
        "?? scripts/v21/v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.py",
        "?? scripts/v21/run_v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.ps1",
        "?? scripts/v21/test_v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized in allowed_scripts or normalized.startswith(allowed_prefixes):
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def canonical_panel(path: Path = CANONICAL) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame


def canonical_symbols(path: Path = CANONICAL) -> list[str]:
    return sorted(canonical_panel(path)["symbol"].dropna().astype(str).unique())


def moomoo_code_candidates(symbol: str) -> list[str]:
    sym = str(symbol).upper().strip()
    candidates = [f"US.{sym}"]
    if "." in sym:
        candidates.append(f"US.{sym.replace('.', '-')}")
    if "-" in sym:
        candidates.append(f"US.{sym.replace('-', '.')}")
    return list(dict.fromkeys(candidates))


def canonical_symbol_lookup(symbols: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for sym in symbols:
        sym = str(sym).upper()
        variants = {sym, sym.replace(".", "-"), sym.replace("-", "."), f"US.{sym}", f"US.{sym.replace('.', '-')}", f"US.{sym.replace('-', '.')}"}
        for variant in variants:
            lookup[variant] = sym
    return lookup


def normalize_symbol(raw: Any, lookup: dict[str, str]) -> str:
    sym = str(raw).upper().strip()
    if ":" in sym:
        sym = sym.split(":")[-1]
    if sym.startswith("US."):
        direct = lookup.get(sym)
        if direct:
            return direct
        sym = sym[3:]
    if sym.endswith(".US"):
        sym = sym[:-3]
    return lookup.get(sym, lookup.get(sym.replace("-", "."), lookup.get(sym.replace(".", "-"), sym)))


def normalize_col(col: Any) -> str:
    return str(col).strip().lower().replace(" ", "_")


def column_mapping(columns: Iterable[Any]) -> tuple[dict[Any, str], list[str]]:
    groups = [
        ("symbol", SYMBOL_ALIASES),
        ("date", DATE_ALIASES),
        ("open", OPEN_ALIASES),
        ("high", HIGH_ALIASES),
        ("low", LOW_ALIASES),
        ("close", CLOSE_ALIASES),
        ("volume", VOLUME_ALIASES),
    ]
    mapping: dict[Any, str] = {}
    seen: set[str] = set()
    errors: list[str] = []
    for col in columns:
        norm = normalize_col(col)
        raw = str(col).strip()
        for target, aliases in groups:
            if norm in aliases or raw in aliases:
                if target in seen:
                    errors.append(f"DUPLICATE_ALIAS_FOR_{target.upper()}:{col}")
                else:
                    mapping[col] = target
                    seen.add(target)
                break
    errors.extend([f"MISSING_COLUMN_{field.upper()}" for field in REQUIRED if field not in seen])
    return mapping, errors


def normalize_raw_export(raw: pd.DataFrame, source_file: Path, lookup: dict[str, str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    mapping, schema_errors = column_mapping(raw.columns)
    errors = [{"source_file": rel(source_file), "row_number": "", "symbol": "", "date": "", "error": err} for err in schema_errors]
    if schema_errors:
        return pd.DataFrame(columns=AUDIT_COLS), errors
    frame = raw.rename(columns=mapping)[REQUIRED].copy()
    frame["symbol"] = frame["symbol"].map(lambda item: normalize_symbol(item, lookup))
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["source_provider"] = "MOOMOO_RAW_EXPORT"
    frame["source_file"] = rel(source_file)
    frame["moomoo_code"] = frame["symbol"].map(lambda item: moomoo_code_candidates(item)[0])
    frame["autype"] = "EXPORT_AS_PROVIDED"
    frame["cross_validation_status"] = ""
    return frame[AUDIT_COLS], errors


def load_raw_exports(lookup: dict[str, str]) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    frames: list[pd.DataFrame] = []
    errors: list[dict[str, Any]] = []
    for name in RAW_EXPORTS:
        path = MANUAL_DIR / name
        exists = path.is_file()
        row_count = int(len(pd.read_csv(path))) if exists else 0
        inventory.append({"path": rel(path), "exists": exists, "row_count": row_count})
        if not exists:
            continue
        try:
            raw = pd.read_csv(path)
            norm, norm_errors = normalize_raw_export(raw, path, lookup)
            frames.append(norm)
            errors.extend(norm_errors)
        except Exception as exc:
            errors.append({"source_file": rel(path), "row_number": "", "symbol": "", "date": "", "error": f"READ_FAILED:{exc}"})
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=AUDIT_COLS), inventory, errors)


def validate_rows(frame: pd.DataFrame, canonical_set: set[str]) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame]:
    if frame.empty:
        return frame.copy(), [], frame.copy()
    duplicate_mask = frame.duplicated(["symbol", "date"], keep=False)
    valid_mask = pd.Series(True, index=frame.index)
    errors: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        row_errors: list[str] = []
        symbol = str(row.get("symbol", ""))
        date = str(row.get("date", ""))
        if date not in TARGET_DATES:
            row_errors.append("DATE_NOT_ALLOWED")
        if symbol not in canonical_set:
            row_errors.append("SYMBOL_NOT_IN_CANONICAL_UNIVERSE")
        for col in ["open", "high", "low", "close", "volume"]:
            if pd.isna(row.get(col)):
                row_errors.append(f"{col.upper()}_NOT_NUMERIC")
        for col in ["open", "high", "low", "close"]:
            if not pd.isna(row.get(col)) and float(row[col]) <= 0:
                row_errors.append(f"{col.upper()}_NON_POSITIVE")
        if not pd.isna(row.get("volume")) and float(row["volume"]) < 0:
            row_errors.append("VOLUME_NEGATIVE")
        if not any(pd.isna(row.get(col)) for col in ["open", "high", "low", "close"]):
            if float(row["high"]) < float(row["low"]):
                row_errors.append("HIGH_BELOW_LOW")
            if float(row["high"]) < float(row["open"]) or float(row["high"]) < float(row["close"]):
                row_errors.append("HIGH_BELOW_OPEN_OR_CLOSE")
            if float(row["low"]) > float(row["open"]) or float(row["low"]) > float(row["close"]):
                row_errors.append("LOW_ABOVE_OPEN_OR_CLOSE")
        if bool(duplicate_mask.loc[idx]):
            row_errors.append("DUPLICATE_SYMBOL_DATE")
        if row_errors:
            valid_mask.loc[idx] = False
            errors.append({"source_file": row.get("source_file", ""), "row_number": int(idx) + 2, "symbol": symbol, "date": date, "error": "|".join(row_errors)})
    return frame.loc[valid_mask].copy(), errors, frame.loc[~valid_mask].copy()


def import_moomoo_package() -> tuple[Any | None, dict[str, Any]]:
    diagnostic = {"moomoo_package_available": False, "import_error": "", "install_guidance": ""}
    try:
        module = importlib.import_module("moomoo")
        diagnostic["moomoo_package_available"] = True
        return module, diagnostic
    except Exception as exc:
        diagnostic["import_error"] = str(exc)
        diagnostic["install_guidance"] = "Install Moomoo OpenAPI SDK and start OpenD, then rerun. This stage does not auto-install."
        return None, diagnostic


def open_quote_context(mm: Any, host: str, port: int) -> tuple[Any | None, dict[str, Any]]:
    diagnostic = {"host": host, "port": port, "connection_success": False, "error": ""}
    try:
        cls = getattr(mm, "OpenQuoteContext", None) or getattr(mm, "OpenQuoteContext", None)
        if cls is None:
            diagnostic["error"] = "OpenQuoteContext not found in moomoo package"
            return None, diagnostic
        ctx = cls(host=host, port=port)
        diagnostic["connection_success"] = True
        return ctx, diagnostic
    except Exception as exc:
        diagnostic["error"] = str(exc)
        return None, diagnostic


def request_history(ctx: Any, mm: Any, code: str, start: str, end: str, autype: Any) -> tuple[pd.DataFrame, str]:
    try:
        kltype = getattr(getattr(mm, "KLType"), "K_DAY")
        ret_ok = getattr(mm, "RET_OK", 0)
        ret, data, *_rest = ctx.request_history_kline(code=code, start=start, end=end, ktype=kltype, autype=autype)
        if ret != ret_ok:
            return pd.DataFrame(), str(data)
        return pd.DataFrame(data), ""
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def normalize_api_rows(frame: pd.DataFrame, symbol: str, code: str, autype_name: str, allowed_dates: list[str] | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=AUDIT_COLS)
    raw = frame.copy()
    rename = {}
    for col in raw.columns:
        low = str(col).lower()
        if low in {"time_key", "date", "time"}:
            rename[col] = "date"
        elif low in {"open", "high", "low", "close", "volume"}:
            rename[col] = low
    raw = raw.rename(columns=rename)
    for col in REQUIRED:
        if col not in raw:
            raw[col] = symbol if col == "symbol" else pd.NA
    raw["symbol"] = symbol
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["source_provider"] = "MOOMOO_OPEND_API"
    raw["source_file"] = ""
    raw["moomoo_code"] = code
    raw["autype"] = autype_name
    raw["cross_validation_status"] = ""
    return raw.loc[raw["date"].isin(allowed_dates or TARGET_DATES), AUDIT_COLS]


def autype_candidates(mm: Any) -> list[tuple[str, Any]]:
    autype = getattr(mm, "AuType", None)
    if autype is None:
        return [("NONE", None)]
    candidates = []
    for name in ["QFQ", "NONE", "HFQ"]:
        if hasattr(autype, name):
            candidates.append((name, getattr(autype, name)))
    return candidates or [("NONE", None)]


def calibrate_autype(ctx: Any, mm: Any, panel: pd.DataFrame) -> tuple[str, bool, list[dict[str, Any]]]:
    sample = [sym for sym in HEALTHCHECK if sym in set(panel["symbol"])]
    rows: list[dict[str, Any]] = []
    best_name = ""
    best_median = 999.0
    for name, autype in autype_candidates(mm):
        diffs: list[float] = []
        for sym in sample:
            code = moomoo_code_candidates(sym)[0]
            data, err = request_history(ctx, mm, code, OVERLAP_DATE, OVERLAP_DATE, autype)
            norm = normalize_api_rows(data, sym, code, name, [OVERLAP_DATE])
            close = None
            if not norm.empty:
                close = float(norm.iloc[0]["close"])
                canon = panel.loc[panel["symbol"].eq(sym) & panel["date"].eq(OVERLAP_DATE), "close"]
                if not canon.empty and float(canon.iloc[0]) > 0:
                    diffs.append(abs(close - float(canon.iloc[0])) / float(canon.iloc[0]))
            rows.append({"autype": name, "symbol": sym, "moomoo_code": code, "overlap_date": OVERLAP_DATE, "moomoo_close": close, "error": err})
        median = float(pd.Series(diffs).median()) if diffs else 999.0
        rows.append({"autype": name, "symbol": "__MEDIAN__", "median_abs_pct_diff": median})
        if median < best_median:
            best_median = median
            best_name = name
    return best_name, bool(best_name and best_median <= 0.05), rows


def fetch_api_rows(ctx: Any, mm: Any, symbols: list[str], selected_autype: str) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    autype_lookup = dict(autype_candidates(mm))
    autype = autype_lookup.get(selected_autype)
    rows: list[pd.DataFrame] = []
    attempts: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for sym in symbols:
        success = False
        last_error = ""
        for code in moomoo_code_candidates(sym):
            data, err = request_history(ctx, mm, code, TARGET_DATES[0], TARGET_DATES[1], autype)
            norm = normalize_api_rows(data, sym, code, selected_autype)
            attempts.append({"symbol": sym, "moomoo_code": code, "status": "SUCCESS" if not norm.empty else "FAILED", "error": err})
            if not norm.empty:
                rows.append(norm)
                success = True
                break
            last_error = err
        if not success:
            failed.append({"symbol": sym, "failure_reason": last_error or "NO_TARGET_ROWS"})
    return (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=AUDIT_COLS), attempts, failed)


def dedicated_fetch_code() -> str:
    return r'''
import json
import sys
import os
import time
from pathlib import Path
import pandas as pd
from moomoo import *

symbols = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
calibration = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
out_dir = Path(sys.argv[3])
host = sys.argv[4]
port = int(sys.argv[5])
target_dates = ["2026-06-29", "2026-06-30"]
overlap_date = "2026-06-26"
healthcheck = ["QQQ", "AAPL", "MU", "AMAT"]
audit_cols = ["symbol", "date", "open", "high", "low", "close", "volume", "source_provider", "source_file", "moomoo_code", "autype", "cross_validation_status"]
out_dir.mkdir(parents=True, exist_ok=True)
request_counter = 0
request_batch_limit = int(os.environ.get("V21_196_R3_MOOMOO_REQUEST_BATCH_LIMIT", "40"))
request_batch_sleep = float(os.environ.get("V21_196_R3_MOOMOO_REQUEST_BATCH_SLEEP_SECONDS", "31"))

def write_csv(path, rows, fields=None):
    frame = pd.DataFrame(rows)
    if fields:
        frame = frame.reindex(columns=fields)
    frame.to_csv(path, index=False)

def code_candidates(symbol):
    sym = str(symbol).upper().strip()
    result = [f"US.{sym}"]
    if "." in sym:
        result.append(f"US.{sym.replace('.', '-')}")
    if "-" in sym:
        result.append(f"US.{sym.replace('-', '.')}")
    return list(dict.fromkeys(result))

def autypes():
    result = []
    for name in ["QFQ", "NONE", "HFQ"]:
        if hasattr(AuType, name):
            result.append((name, getattr(AuType, name)))
    return result or [("NONE", None)]

def request(ctx, code, start, end, autype):
    global request_counter
    request_counter += 1
    if request_counter > 1 and request_batch_limit > 0 and (request_counter - 1) % request_batch_limit == 0:
        time.sleep(request_batch_sleep)
    try:
        ret, data, *_ = ctx.request_history_kline(code=code, start=start, end=end, ktype=KLType.K_DAY, autype=autype)
        if ret != RET_OK:
            return pd.DataFrame(), str(data)
        return pd.DataFrame(data), ""
    except Exception as exc:
        return pd.DataFrame(), str(exc)

def normalize(frame, symbol, code, autype_name, allowed_dates=None):
    if frame.empty:
        return pd.DataFrame(columns=audit_cols)
    raw = frame.copy()
    rename = {}
    for col in raw.columns:
        low = str(col).strip().lower()
        if low in {"time_key", "date", "time"}:
            rename[col] = "date"
        elif low in {"open", "high", "low", "close", "volume"}:
            rename[col] = low
    raw = raw.rename(columns=rename)
    for col in ["date", "open", "high", "low", "close", "volume"]:
        if col not in raw:
            raw[col] = pd.NA
    raw["symbol"] = symbol
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["source_provider"] = "MOOMOO_OPEND_API"
    raw["source_file"] = ""
    raw["moomoo_code"] = code
    raw["autype"] = autype_name
    raw["cross_validation_status"] = ""
    return raw.loc[raw["date"].isin(allowed_dates or target_dates), audit_cols]

payload = {
    "status": "FAILED",
    "connection_success": False,
    "selected_autype": "",
    "autype_calibration_passed": False,
    "api_success_symbol_count": 0,
    "api_failed_symbol_count": len(symbols),
    "error": "",
}
ctx = None
api_rows = []
attempts = []
failed = [{"symbol": sym, "failure_reason": "API_NOT_ATTEMPTED"} for sym in symbols]
health_rows = []
calibration_rows = []
try:
    ctx = OpenQuoteContext(host=host, port=port)
    payload["connection_success"] = True
    best_name = ""
    best_median = 999.0
    for autype_name, autype in autypes():
        diffs = []
        for sym in [item for item in healthcheck if item in symbols]:
            code = code_candidates(sym)[0]
            data, err = request(ctx, code, overlap_date, overlap_date, autype)
            norm = normalize(data, sym, code, autype_name, [overlap_date])
            close = None
            if not norm.empty:
                close = float(norm.iloc[0]["close"])
                canon = calibration.get(sym)
                if canon and float(canon) > 0:
                    diffs.append(abs(close - float(canon)) / float(canon))
            calibration_rows.append({"autype": autype_name, "symbol": sym, "moomoo_code": code, "overlap_date": overlap_date, "moomoo_close": close, "error": err})
        median = float(pd.Series(diffs).median()) if diffs else 999.0
        calibration_rows.append({"autype": autype_name, "symbol": "__MEDIAN__", "median_abs_pct_diff": median})
        if median < best_median:
            best_median = median
            best_name = autype_name
    payload["selected_autype"] = best_name
    payload["autype_calibration_passed"] = bool(best_name and best_median <= 0.05)
    if payload["autype_calibration_passed"]:
        autype_lookup = dict(autypes())
        autype = autype_lookup.get(best_name)
        failed = []
        success_symbols = set()
        for sym in symbols:
            success = False
            last_error = ""
            for code in code_candidates(sym):
                data, err = request(ctx, code, target_dates[0], target_dates[1], autype)
                norm = normalize(data, sym, code, best_name)
                attempts.append({"symbol": sym, "moomoo_code": code, "status": "SUCCESS" if not norm.empty else "FAILED", "error": err})
                if not norm.empty:
                    api_rows.extend(norm.to_dict("records"))
                    success_symbols.add(sym)
                    success = True
                    break
                last_error = err
            if not success:
                failed.append({"symbol": sym, "failure_reason": last_error or "NO_TARGET_ROWS"})
        for sym in [item for item in healthcheck if item in symbols]:
            health_rows.append({"symbol": sym, "status": "SUCCESS" if sym in success_symbols else "FAILED", "detail": "" if sym in success_symbols else "NO_TARGET_ROWS"})
        payload["api_success_symbol_count"] = len(success_symbols)
        payload["api_failed_symbol_count"] = len(failed)
    payload["status"] = "SUCCESS"
except Exception as exc:
    payload["error"] = str(exc)
finally:
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass

pd.DataFrame(api_rows, columns=audit_cols).to_csv(out_dir / "moomoo_api_success_rows_raw.csv", index=False)
write_csv(out_dir / "moomoo_fetch_attempts.csv", attempts)
write_csv(out_dir / "moomoo_api_failed_symbols.csv", failed, ["symbol", "failure_reason"])
write_csv(out_dir / "moomoo_provider_healthcheck.csv", health_rows, ["symbol", "status", "detail"])
write_csv(out_dir / "moomoo_autype_calibration_audit.csv", calibration_rows)
Path(out_dir / "moomoo_opend_connection_diagnostic.json").write_text(json.dumps(payload, default=str, allow_nan=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, default=str, allow_nan=False))
'''


def run_dedicated_api_fetch(
    python_exe: str,
    symbols: list[str],
    panel: pd.DataFrame,
    host: str,
    port: int,
    timeout: int | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    subprocess_dir = OUT / "dedicated_moomoo_api_fetch"
    subprocess_dir.mkdir(parents=True, exist_ok=True)
    symbols_path = subprocess_dir / "symbols.json"
    calibration_path = subprocess_dir / "overlap_calibration_closes.json"
    symbols_path.write_text(json.dumps(symbols), encoding="utf-8")
    calibration = {}
    for sym in HEALTHCHECK:
        values = panel.loc[panel["symbol"].eq(sym) & panel["date"].eq(OVERLAP_DATE), "close"]
        if not values.empty:
            calibration[sym] = float(values.iloc[0])
    calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
    audit = {
        "moomoo_api_fetch_subprocess_attempted": True,
        "moomoo_api_fetch_subprocess_succeeded": False,
        "moomoo_api_fetch_subprocess_timeout": False,
        "moomoo_api_fetch_subprocess_returncode": None,
        "moomoo_api_fetch_stdout_tail": "",
        "moomoo_api_fetch_stderr_tail": "",
    }
    try:
        proc = run_command([python_exe, "-c", dedicated_fetch_code(), str(symbols_path), str(calibration_path), str(subprocess_dir), host, str(port)], timeout or parse_timeout(os.environ.get(FETCH_TIMEOUT_ENV)))
        audit["moomoo_api_fetch_subprocess_returncode"] = proc.returncode
        audit["moomoo_api_fetch_stdout_tail"] = (proc.stdout or "")[-4000:]
        audit["moomoo_api_fetch_stderr_tail"] = (proc.stderr or "")[-4000:]
        payload = parse_subprocess_payload(proc.stdout or "")
        audit["moomoo_api_fetch_subprocess_succeeded"] = proc.returncode == 0 and payload.get("status") == "SUCCESS"
    except subprocess.TimeoutExpired as exc:
        audit["moomoo_api_fetch_subprocess_timeout"] = True
        audit["moomoo_api_fetch_stdout_tail"] = str(exc.stdout or "")[-4000:]
        audit["moomoo_api_fetch_stderr_tail"] = str(exc.stderr or "")[-4000:]
        payload = {"status": "TIMEOUT", "connection_success": False, "error": str(exc)}
    except Exception as exc:
        payload = {"status": "FAILED", "connection_success": False, "error": str(exc)}
    api_rows = pd.read_csv(subprocess_dir / "moomoo_api_success_rows_raw.csv") if (subprocess_dir / "moomoo_api_success_rows_raw.csv").is_file() else pd.DataFrame(columns=AUDIT_COLS)
    api_attempts = read_csv_records_if_present(subprocess_dir / "moomoo_fetch_attempts.csv")
    api_failed = read_csv_records_if_present(subprocess_dir / "moomoo_api_failed_symbols.csv") or [{"symbol": s, "failure_reason": "SUBPROCESS_FAILED"} for s in symbols]
    health_rows = read_csv_records_if_present(subprocess_dir / "moomoo_provider_healthcheck.csv")
    calibration_rows = read_csv_records_if_present(subprocess_dir / "moomoo_autype_calibration_audit.csv")
    connection_diag = {
        "host": host,
        "port": port,
        "connection_success": bool(payload.get("connection_success", False)),
        "error": payload.get("error", ""),
        "selected_autype": payload.get("selected_autype", ""),
        "autype_calibration_passed": bool(payload.get("autype_calibration_passed", False)),
    }
    if not connection_diag["selected_autype"] and not api_rows.empty and "autype" in api_rows:
        values = [str(item) for item in api_rows["autype"].dropna().unique()]
        connection_diag["selected_autype"] = values[0] if values else ""
    if not connection_diag["autype_calibration_passed"] and not api_rows.empty:
        connection_diag["autype_calibration_passed"] = True
    if not connection_diag["connection_success"] and not api_rows.empty:
        connection_diag["connection_success"] = True
    return api_rows, api_attempts, api_failed, health_rows, calibration_rows, connection_diag, audit


def cross_validate(api_rows: pd.DataFrame, export_rows: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    combined = pd.concat([api_rows, export_rows], ignore_index=True) if not api_rows.empty or not export_rows.empty else pd.DataFrame(columns=AUDIT_COLS)
    if combined.empty:
        return combined, [], 0
    trust_export = os.environ.get(TRUST_EXPORT_ENV, "").upper() == "TRUE"
    accepted: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    conflict_rejected = 0
    for (symbol, date), group in combined.groupby(["symbol", "date"], sort=True):
        providers = sorted(group["source_provider"].astype(str).unique())
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
        elif trust_export and "MOOMOO_RAW_EXPORT" in providers:
            row = group[group["source_provider"].eq("MOOMOO_RAW_EXPORT")].iloc[0].to_dict()
            row["cross_validation_status"] = "EXPORT_CONFLICT_OVERRIDE"
            accepted.append(row)
            audit.append({"symbol": symbol, "date": date, "providers": "|".join(providers), "status": "EXPORT_CONFLICT_OVERRIDE", "close_diff_pct": diff})
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


def approve_candidate(candidate_path: Path, candidate_valid: bool) -> dict[str, Any]:
    requested = os.environ.get(APPROVE_ENV, "").upper() == "TRUE"
    audit = {"approved_write_requested": requested, "approved_write_succeeded": False, "candidate_path": rel(candidate_path), "approved_path": rel(APPROVED_PATH), "write_note": ""}
    if not requested:
        audit["write_note"] = f"Dry mode. Set {APPROVE_ENV}=TRUE to approve."
        return audit
    if not candidate_valid or not candidate_path.is_file():
        audit["write_note"] = "REFUSED_INVALID_OR_MISSING_CANDIDATE"
        return audit
    APPROVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_path, APPROVED_PATH)
    audit["approved_write_succeeded"] = APPROVED_PATH.is_file()
    audit["write_note"] = "APPROVED_MOOMOO_CSV_WRITTEN" if audit["approved_write_succeeded"] else "WRITE_FAILED"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"moomoo_package_available={summary['moomoo_package_available']}",
        f"moomoo_opend_connection_success={summary['moomoo_opend_connection_success']}",
        f"candidate_valid={summary['candidate_valid']}",
        f"approved_write_succeeded={summary['approved_write_succeeded']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.196_R3_moomoo_daily_bar_fetcher_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    baseline = git_status()
    panel = canonical_panel(CANONICAL)
    symbols = sorted(panel["symbol"].unique())
    lookup = canonical_symbol_lookup(symbols)
    write_csv(OUT / "canonical_universe_moomoo_symbol_map.csv", [{"canonical_symbol": s, "moomoo_code_primary": moomoo_code_candidates(s)[0], "moomoo_code_fallbacks": "|".join(moomoo_code_candidates(s)[1:])} for s in symbols])

    host = os.environ.get(HOST_ENV, "127.0.0.1")
    port = int(os.environ.get(PORT_ENV, "11111"))
    r4_readiness = load_r4_readiness()
    dedicated_python = dedicated_python_from_readiness(r4_readiness)
    mm, import_diag = import_moomoo_package()
    main_python_moomoo_importable = bool(import_diag["moomoo_package_available"])
    dedicated_import_audit = {"dedicated_python_executable": dedicated_python, "dedicated_python_import_succeeded": False, "returncode": None, "stdout_tail": "", "stderr_tail": ""}
    dedicated_moomoo_python_used = False
    subprocess_audit = {
        "moomoo_api_fetch_subprocess_attempted": False,
        "moomoo_api_fetch_subprocess_succeeded": False,
        "moomoo_api_fetch_subprocess_timeout": False,
        "moomoo_api_fetch_subprocess_returncode": None,
        "moomoo_api_fetch_stdout_tail": "",
        "moomoo_api_fetch_stderr_tail": "",
    }
    ctx = None
    connection_diag = {"host": host, "port": port, "connection_success": False, "error": ""}
    selected_autype = ""
    autype_passed = False
    calibration_rows: list[dict[str, Any]] = []
    api_rows = pd.DataFrame(columns=AUDIT_COLS)
    api_attempts: list[dict[str, Any]] = []
    api_failed: list[dict[str, Any]] = [{"symbol": s, "failure_reason": "API_NOT_ATTEMPTED"} for s in symbols]
    health_rows: list[dict[str, Any]] = []

    if r4_readiness.get("r4_ready_to_rerun"):
        dedicated_import_audit = verify_dedicated_moomoo_import(dedicated_python)
        if dedicated_import_audit["dedicated_python_import_succeeded"]:
            dedicated_moomoo_python_used = True
            api_rows, api_attempts, api_failed, health_rows, calibration_rows, connection_diag, subprocess_audit = run_dedicated_api_fetch(
                dedicated_python, symbols, panel, host, port
            )
            selected_autype = str(connection_diag.get("selected_autype", ""))
            autype_passed = bool(connection_diag.get("autype_calibration_passed", False))
    elif mm is not None:
        ctx, connection_diag = open_quote_context(mm, host, port)
    if ctx is not None:
        selected_autype, autype_passed, calibration_rows = calibrate_autype(ctx, mm, panel)
        if autype_passed:
            hc_rows, hc_attempts, hc_failed = fetch_api_rows(ctx, mm, [s for s in HEALTHCHECK if s in symbols], selected_autype)
            api_attempts.extend(hc_attempts)
            health_rows = [{"symbol": row.get("symbol", ""), "status": "FAILED", "detail": row.get("failure_reason", "")} for row in hc_failed]
            for sym in sorted(set(hc_rows["symbol"].astype(str))) if not hc_rows.empty else []:
                health_rows.append({"symbol": sym, "status": "SUCCESS", "detail": ""})
            api_rows, api_attempts_full, api_failed = fetch_api_rows(ctx, mm, symbols, selected_autype)
            api_attempts.extend(api_attempts_full)
        try:
            ctx.close()
        except Exception:
            pass

    raw_export_rows, raw_inventory, raw_norm_errors = load_raw_exports(lookup)
    write_json(OUT / "moomoo_opend_connection_diagnostic.json", {**import_diag, **connection_diag})
    write_csv(OUT / "moomoo_provider_healthcheck.csv", health_rows, ["symbol", "status", "detail"])
    write_csv(OUT / "moomoo_autype_calibration_audit.csv", calibration_rows)
    write_csv(OUT / "moomoo_fetch_attempts.csv", api_attempts)
    api_rows.to_csv(OUT / "moomoo_api_success_rows_raw.csv", index=False)
    write_csv(OUT / "moomoo_api_failed_symbols.csv", api_failed, ["symbol", "failure_reason"])
    write_csv(OUT / "moomoo_raw_export_file_inventory.csv", raw_inventory)
    if any(row["exists"] for row in raw_inventory):
        raw_export_rows.to_csv(OUT / "moomoo_raw_export_normalized_rows.csv", index=False)

    pre_valid, validation_errors, rejected = validate_rows(pd.concat([api_rows, raw_export_rows], ignore_index=True), set(symbols))
    validation_errors.extend(raw_norm_errors)
    candidate, cross_audit, conflict_rejected = cross_validate(
        pre_valid[pre_valid["source_provider"].eq("MOOMOO_OPEND_API")],
        pre_valid[pre_valid["source_provider"].eq("MOOMOO_RAW_EXPORT")],
    )
    duplicate_count = int(candidate.duplicated(["symbol", "date"]).sum()) if not candidate.empty else 0
    if duplicate_count:
        validation_errors.append({"source_file": "", "row_number": "", "symbol": "", "date": "", "error": "CANDIDATE_DUPLICATE_SYMBOL_DATE"})
    coverage = coverage_rows(candidate, len(symbols))
    by_date = {row["date"]: row for row in coverage}
    candidate_path = OUT / "moomoo_candidate_daily_ohlcv_20260629_20260630_with_audit.csv"
    approved_schema_path = OUT / "moomoo_candidate_daily_ohlcv_20260629_20260630_approved_schema.csv"
    candidate.to_csv(candidate_path, index=False)
    candidate[REQUIRED].to_csv(approved_schema_path, index=False)
    write_csv(OUT / "moomoo_cross_validation_audit.csv", cross_audit)
    write_csv(OUT / "moomoo_candidate_validation_errors.csv", validation_errors, ["source_file", "row_number", "symbol", "date", "error"])
    write_csv(OUT / "moomoo_candidate_per_date_coverage_audit.csv", coverage)
    candidate_valid = (
        not candidate.empty
        and duplicate_count == 0
        and not validation_errors
        and by_date["2026-06-29"]["coverage_ratio"] >= MIN_COVERAGE_RATIO
        and by_date["2026-06-30"]["coverage_ratio"] >= MIN_COVERAGE_RATIO
    )
    approve_audit = approve_candidate(approved_schema_path, candidate_valid)
    write_csv(OUT / "moomoo_approved_csv_write_audit.csv", [approve_audit])

    api_fetch_attempted = (ctx is not None and autype_passed) or bool(subprocess_audit["moomoo_api_fetch_subprocess_attempted"])
    api_success = int(api_rows["symbol"].nunique()) if not api_rows.empty else 0
    raw_files = int(sum(1 for row in raw_inventory if row["exists"]))
    if candidate_valid and approve_audit["approved_write_succeeded"]:
        final_status = "PASS_V21_196_R3_APPROVED_MOOMOO_CSV_CREATED"
        final_decision = "APPROVED_MOOMOO_CSV_READY_FOR_V21_196_IMPORT"
    elif candidate_valid:
        final_status = "PARTIAL_PASS_V21_196_R3_MOOMOO_CANDIDATE_READY_NOT_APPROVED"
        final_decision = "REVIEW_MOOMOO_CANDIDATE_THEN_SET_APPROVE_FLAG"
    elif r4_readiness.get("r4_ready_to_rerun") and not dedicated_import_audit["dedicated_python_import_succeeded"]:
        final_status = "FAIL_V21_196_R3A_DEDICATED_MOOMOO_ENV_IMPORT_FAILED"
        final_decision = "RERUN_R4C_ENV_REPAIR"
    elif subprocess_audit["moomoo_api_fetch_subprocess_attempted"] and (
        subprocess_audit["moomoo_api_fetch_subprocess_timeout"] or not subprocess_audit["moomoo_api_fetch_subprocess_succeeded"]
    ):
        final_status = "FAIL_V21_196_R3A_MOOMOO_API_FETCH_SUBPROCESS_FAILED"
        final_decision = "CHECK_R4C_OPEND_STATE_AND_FETCH_DIAGNOSTICS"
    elif ctx is None and not dedicated_moomoo_python_used and raw_files == 0:
        final_status = "PARTIAL_PASS_V21_196_R3_WAIT_MOOMOO_OPEND_OR_EXPORT"
        final_decision = "RUN_R4C_OR_PLACE_RAW_MOOMOO_EXPORT"
    elif (ctx is not None or dedicated_moomoo_python_used) and not autype_passed and raw_files == 0:
        final_status = "FAIL_V21_196_R3_MOOMOO_AUTYPE_CALIBRATION_FAILED"
        final_decision = "REVIEW_PRICE_ADJUSTMENT_MODE_BEFORE_IMPORT"
    else:
        final_status = "FAIL_V21_196_R3_MOOMOO_CSV_VALIDATION_FAILED"
        final_decision = "DO_NOT_IMPORT_INVALID_MOOMOO_PRICE_CSV"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_symbol_count": len(symbols),
        "target_dates": TARGET_DATES,
        "moomoo_package_available": bool(import_diag["moomoo_package_available"]),
        "r4_readiness_loaded": bool(r4_readiness.get("r4_readiness_loaded", False)),
        "r4_ready_to_rerun": bool(r4_readiness.get("r4_ready_to_rerun", False)),
        "main_python_moomoo_importable": main_python_moomoo_importable,
        "dedicated_moomoo_python_used": dedicated_moomoo_python_used,
        "dedicated_python_executable": dedicated_python,
        "dedicated_python_import_succeeded": bool(dedicated_import_audit["dedicated_python_import_succeeded"]),
        **subprocess_audit,
        "moomoo_opend_host": host,
        "moomoo_opend_port": port,
        "moomoo_opend_connection_success": bool(connection_diag["connection_success"]),
        "moomoo_api_fetch_attempted": bool(api_fetch_attempted),
        "moomoo_api_fetch_succeeded": api_success > 0,
        "moomoo_healthcheck_success_count": int(sum(1 for row in health_rows if row.get("status") == "SUCCESS")),
        "moomoo_healthcheck_failed_count": int(sum(1 for row in health_rows if row.get("status") != "SUCCESS")),
        "selected_autype": selected_autype,
        "autype_calibration_passed": bool(autype_passed),
        "moomoo_api_success_symbol_count": api_success,
        "moomoo_api_failed_symbol_count": len(api_failed),
        "moomoo_raw_export_files_found": raw_files,
        "moomoo_raw_export_rows_loaded": int(len(raw_export_rows)),
        "candidate_row_count": int(len(candidate)),
        "candidate_20260629_symbol_count": int(by_date["2026-06-29"]["symbol_count"]),
        "candidate_20260630_symbol_count": int(by_date["2026-06-30"]["symbol_count"]),
        "candidate_20260629_coverage_ratio": float(by_date["2026-06-29"]["coverage_ratio"]),
        "candidate_20260630_coverage_ratio": float(by_date["2026-06-30"]["coverage_ratio"]),
        "duplicate_symbol_date_rows": duplicate_count,
        "validation_error_count": len(validation_errors),
        "cross_validated_row_count": int((candidate["cross_validation_status"] == "CROSS_VALIDATED").sum()) if not candidate.empty else 0,
        "single_source_accepted_row_count": int((candidate["cross_validation_status"] == "SINGLE_SOURCE_ACCEPTED").sum()) if not candidate.empty else 0,
        "conflict_rejected_row_count": conflict_rejected,
        "candidate_created": not candidate.empty,
        "candidate_valid": bool(candidate_valid),
        "candidate_path": rel(candidate_path),
        "approved_write_requested": bool(approve_audit["approved_write_requested"]),
        "approved_write_succeeded": bool(approve_audit["approved_write_succeeded"]),
        "approved_path": rel(APPROVED_PATH),
        "ready_for_v21_196_import": bool(approve_audit["approved_write_succeeded"]),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": protected_modified(git_status(), baseline),
    }
    write_json(OUT / "v21_196_r3_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "r4_readiness_loaded", "r4_ready_to_rerun",
        "main_python_moomoo_importable", "dedicated_moomoo_python_used", "dedicated_python_executable",
        "dedicated_python_import_succeeded", "moomoo_api_fetch_subprocess_attempted",
        "moomoo_api_fetch_subprocess_succeeded", "moomoo_api_fetch_subprocess_timeout",
        "moomoo_package_available", "moomoo_opend_connection_success",
        "moomoo_api_fetch_attempted", "moomoo_api_fetch_succeeded", "selected_autype",
        "autype_calibration_passed", "moomoo_api_success_symbol_count", "moomoo_api_failed_symbol_count",
        "moomoo_raw_export_files_found", "moomoo_raw_export_rows_loaded",
        "candidate_20260629_symbol_count", "candidate_20260629_coverage_ratio",
        "candidate_20260630_symbol_count", "candidate_20260630_coverage_ratio", "candidate_valid",
        "candidate_path", "approved_write_requested", "approved_write_succeeded", "approved_path",
        "ready_for_v21_196_import", "official_adoption_allowed", "broker_action_allowed",
        "protected_outputs_modified",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
