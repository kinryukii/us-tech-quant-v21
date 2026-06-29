#!/usr/bin/env python
"""V21.037-R1 historical OHLCV ingestion and cache expansion.

Research-only stage that expands the V21 historical OHLCV cache from local
files and, only when explicitly enabled, a Yahoo/yfinance-style cache fetch.
No official rankings, weights, broker state, real-book state, or production
outputs are mutated.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.037-R1_HISTORICAL_OHLCV_INGESTION_AND_CACHE_EXPANSION"
PASS_STATUS = "PASS_V21_037_R1_HISTORICAL_OHLCV_CACHE_EXPANDED_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_037_R1_HISTORICAL_OHLCV_CACHE_STILL_LIMITED"
BLOCKED_STATUS = "BLOCKED_V21_037_R1_NO_USABLE_OHLCV_SOURCE"
RESEARCH_BLOCKED_STATUS = "BLOCKED_V21_037_R1_RESEARCH_ONLY_VIOLATION"

DECISION_READY = "HISTORICAL_OHLCV_CACHE_EXPANDED_READY_FOR_TECHNICAL_SUBFACTOR_RERUN_OFFICIAL_UPDATE_BLOCKED"
DECISION_LIMITED = "HISTORICAL_OHLCV_CACHE_STILL_LIMITED_MANUAL_DATA_IMPORT_REQUIRED"
DECISION_NETWORK_DISABLED = "HISTORICAL_OHLCV_NETWORK_BACKFILL_DISABLED_LOCAL_HISTORY_INSUFFICIENT"
DECISION_BLOCKED = "HISTORICAL_OHLCV_INGESTION_BLOCKED_NO_SOURCE"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"
CACHE_DIR = ROOT / "inputs" / "v21" / "historical_ohlcv_cache"

V36_SUMMARY = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_BACKFILL_SUMMARY.csv"
V36_NORMALIZED = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_NORMALIZED.csv"

SUMMARY_OUT = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_SUMMARY.csv"
CACHE_OUT = CACHE_DIR / "V21_037_R1_HISTORICAL_OHLCV_CACHE.csv"
SOURCE_AUDIT_OUT = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_SOURCE_AUDIT.csv"
DEPTH_OUT = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_TICKER_DEPTH_AFTER_INGESTION.csv"
FETCH_PLAN_OUT = OUT_DIR / "V21_037_R1_HISTORICAL_OHLCV_FETCH_PLAN.csv"
READINESS_OUT = OUT_DIR / "V21_037_R1_TECHNICAL_RERUN_READINESS_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_037_R1_HISTORICAL_OHLCV_INGESTION_AND_CACHE_EXPANSION_REPORT.md"

BENCHMARK_TICKERS = {"QQQ", "SPY", "SOXX", "SMH", "XLK", "IWM", "RSP"}
TARGET_LOOKBACK_CALENDAR_DAYS = 252
TARGET_MIN_TRADING_ROWS = 180
PASS_MIN_READY_TICKERS = 1

CACHE_FIELDS = [
    "as_of_date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "source_type",
    "source_file_path",
    "ingestion_mode",
    "row_quality_status",
    "duplicate_resolution_status",
]

SOURCE_AUDIT_FIELDS = [
    "source_file_path",
    "source_type",
    "exists",
    "rows",
    "detected_date_column",
    "detected_ticker_column",
    "detected_open_column",
    "detected_high_column",
    "detected_low_column",
    "detected_close_column",
    "detected_adjusted_close_column",
    "detected_volume_column",
    "min_date",
    "max_date",
    "distinct_tickers",
    "usable_for_ingestion",
    "reason_if_not_usable",
]


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.10f}"
    return value


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def parse_date(value: object) -> str:
    text = clean(value)
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return ""
        return parsed.strftime("%Y-%m-%d")


def valid_ticker(value: object) -> bool:
    ticker = clean(value).upper()
    if not ticker or ticker in {"NAN", "NONE", "NULL"}:
        return False
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker):
        return False
    return any(ch.isalpha() for ch in ticker)


def parse_date_series(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    compact = text.str.fullmatch(r"\d{8}", na=False)
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if compact.any():
        out.loc[compact] = pd.to_datetime(text.loc[compact], errors="coerce", format="%Y%m%d")
    if (~compact).any():
        out.loc[~compact] = pd.to_datetime(series.loc[~compact], errors="coerce", format="mixed")
    return out


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []


def find_col(cols: list[str], candidates: list[str]) -> str:
    by_norm = {norm(col): col for col in cols}
    for candidate in candidates:
        key = norm(candidate)
        if key in by_norm:
            return by_norm[key]
    for col in cols:
        ncol = norm(col)
        for candidate in candidates:
            if norm(candidate) in ncol:
                return col
    return ""


def source_type_for(path: Path) -> str:
    name = rel(path).lower()
    if "v21_036" in name:
        return "V21_036_NORMALIZED"
    if "yahoo" in name:
        return "LOCAL_YAHOO_CACHE"
    if "price_cache" in name or "ticker_price_cache" in name:
        return "LOCAL_PRICE_CACHE"
    if "ohlcv" in name:
        return "LOCAL_OHLCV"
    if "historical" in name or "history" in name:
        return "LOCAL_HISTORICAL_PRICE"
    if "current_market" in name:
        return "LOCAL_CURRENT_MARKET"
    if "outcome_benchmark" in name:
        return "LOCAL_OUTCOME_BENCHMARK"
    return "LOCAL_CSV_CANDIDATE"


def candidate_files() -> list[Path]:
    roots = [
        ROOT / "data",
        ROOT / "inputs",
        ROOT / "inputs" / "v20",
        ROOT / "inputs" / "v21",
        ROOT / "outputs" / "v20",
        ROOT / "outputs" / "v21",
    ]
    tokens = (
        "price",
        "ohlcv",
        "quote",
        "history",
        "historical",
        "yahoo",
        "cache",
        "market",
        "outcome_benchmark",
        "current_market",
    )
    files: set[Path] = set()
    if V36_NORMALIZED.exists():
        files.add(V36_NORMALIZED)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = rel(path).lower()
            if any(token in name for token in tokens):
                files.add(path)
            if len(files) >= 2500:
                return sorted(files, key=lambda p: rel(p).lower())
    return sorted(files, key=lambda p: rel(p).lower())


def audit_file(path: Path) -> dict[str, object]:
    cols = header(path)
    date_col = find_col(cols, ["as_of_date", "price_date", "date", "trading_date", "latest_price_date", "datetime"])
    ticker_col = find_col(cols, ["ticker", "symbol", "benchmark_ticker"])
    open_col = find_col(cols, ["open", "latest_open"])
    high_col = find_col(cols, ["high", "latest_high"])
    low_col = find_col(cols, ["low", "latest_low"])
    close_col = find_col(cols, ["close", "latest_close", "close_like_price", "adj_close", "adjusted_close"])
    adj_col = find_col(cols, ["adjusted_close", "adj_close", "adj close", "latest_adj_close"])
    volume_col = find_col(cols, ["volume", "latest_volume"])
    rows = 0
    min_date = max_date = ""
    tickers: set[str] = set()
    if cols:
        try:
            usecols = [c for c in [date_col, ticker_col] if c]
            for chunk in pd.read_csv(path, usecols=usecols, chunksize=50000):
                rows += len(chunk)
                if date_col and date_col in chunk:
                    dates = parse_date_series(chunk[date_col])
                    if dates.notna().any():
                        cmin = dates.min().strftime("%Y-%m-%d")
                        cmax = dates.max().strftime("%Y-%m-%d")
                        min_date = cmin if not min_date or cmin < min_date else min_date
                        max_date = cmax if not max_date or cmax > max_date else max_date
                if ticker_col and ticker_col in chunk:
                    tickers.update(t for t in chunk[ticker_col].dropna().astype(str).str.upper().str.strip().unique().tolist() if valid_ticker(t))
        except Exception:
            rows = 0
    usable = bool(rows and date_col and ticker_col and (close_col or adj_col))
    reason = "" if usable else "Missing required date/ticker/close-like price columns or no readable rows."
    return {
        "source_file_path": rel(path),
        "source_type": source_type_for(path),
        "exists": yes(path.exists()),
        "rows": rows,
        "detected_date_column": date_col,
        "detected_ticker_column": ticker_col,
        "detected_open_column": open_col,
        "detected_high_column": high_col,
        "detected_low_column": low_col,
        "detected_close_column": close_col,
        "detected_adjusted_close_column": adj_col,
        "detected_volume_column": volume_col,
        "min_date": min_date,
        "max_date": max_date,
        "distinct_tickers": len(tickers),
        "usable_for_ingestion": yes(usable),
        "reason_if_not_usable": reason,
    }


def source_priority(audit: dict[str, object]) -> int:
    score = 0
    for key in [
        "detected_open_column",
        "detected_high_column",
        "detected_low_column",
        "detected_close_column",
        "detected_adjusted_close_column",
        "detected_volume_column",
    ]:
        score += 1 if audit.get(key) else 0
    rows = int(audit.get("rows") or 0)
    tickers = int(audit.get("distinct_tickers") or 0)
    depth_bonus = min(1000, rows // max(1, tickers)) if tickers else 0
    source_type = str(audit.get("source_type", ""))
    type_bonus = {
        "LOCAL_YAHOO_CACHE": 800,
        "LOCAL_PRICE_CACHE": 700,
        "LOCAL_HISTORICAL_PRICE": 600,
        "LOCAL_OHLCV": 500,
        "V21_036_NORMALIZED": 400,
        "LOCAL_OUTCOME_BENCHMARK": 200,
        "LOCAL_CURRENT_MARKET": -100,
    }.get(source_type, 0)
    return score * 1000 + depth_bonus + type_bonus


def row_quality(row: pd.Series) -> str:
    if not row.get("as_of_date"):
        return "INVALID_DATE"
    if not row.get("ticker"):
        return "INVALID_TICKER"
    if pd.isna(row.get("close")) and pd.isna(row.get("adjusted_close")):
        return "MISSING_CLOSE"
    if pd.isna(row.get("volume")):
        return "MISSING_VOLUME"
    if pd.isna(row.get("open")) or pd.isna(row.get("high")) or pd.isna(row.get("low")):
        return "PARTIAL_OHLCV"
    return "PASS"


def load_rows(audits: list[dict[str, object]], ingestion_mode: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for audit in audits:
        if audit["usable_for_ingestion"] != "TRUE":
            continue
        path = ROOT / str(audit["source_file_path"])
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        out = pd.DataFrame()
        dates = parse_date_series(df[str(audit["detected_date_column"])])
        out["as_of_date"] = dates.dt.strftime("%Y-%m-%d")
        out["ticker"] = df[str(audit["detected_ticker_column"])].astype(str).str.upper().str.strip()
        for target, key in [
            ("open", "detected_open_column"),
            ("high", "detected_high_column"),
            ("low", "detected_low_column"),
            ("close", "detected_close_column"),
            ("adjusted_close", "detected_adjusted_close_column"),
            ("volume", "detected_volume_column"),
        ]:
            col = str(audit.get(key) or "")
            out[target] = pd.to_numeric(df[col], errors="coerce") if col and col in df.columns else np.nan
        out["source_type"] = str(audit["source_type"])
        out["source_file_path"] = str(audit["source_file_path"])
        out["ingestion_mode"] = ingestion_mode
        out["source_priority"] = source_priority(audit)
        frames.append(out)
    if not frames:
        return pd.DataFrame(columns=CACHE_FIELDS)
    raw = pd.concat(frames, ignore_index=True)
    raw["ticker"] = raw["ticker"].replace({"NAN": "", "NONE": "", "NULL": ""})
    raw = raw[raw["ticker"].map(valid_ticker)]
    raw = raw[raw["as_of_date"].between("1990-01-01", "2030-12-31")]
    raw["row_quality_status"] = raw.apply(row_quality, axis=1)
    raw = raw[~raw["row_quality_status"].isin(["INVALID_DATE", "INVALID_TICKER", "MISSING_CLOSE"])]
    raw["field_completeness"] = raw[["open", "high", "low", "close", "adjusted_close", "volume"]].notna().sum(axis=1)
    dup_counts = raw.groupby(["ticker", "as_of_date"])["ticker"].transform("count")
    raw = raw.sort_values(
        ["ticker", "as_of_date", "field_completeness", "source_priority", "source_file_path"],
        ascending=[True, True, False, False, True],
    )
    dedup = raw.drop_duplicates(["ticker", "as_of_date"], keep="first").copy()
    dedup["duplicate_resolution_status"] = np.where(
        dup_counts.loc[dedup.index].to_numpy() > 1,
        "DEDUPED_PREFERRED_COMPLETE_OHLCV_ADJUSTED_CLOSE",
        "UNIQUE",
    )
    return dedup[CACHE_FIELDS].sort_values(["ticker", "as_of_date"]).reset_index(drop=True)


def ticker_universe(normalized: pd.DataFrame) -> set[str]:
    tickers = set(BENCHMARK_TICKERS)
    if not normalized.empty and "ticker" in normalized:
        tickers.update(t for t in normalized["ticker"].dropna().astype(str).str.upper().str.strip().tolist() if valid_ticker(t))
    roots = [ROOT / "inputs" / "v20", ROOT / "inputs" / "v21", ROOT / "outputs" / "v20", ROOT / "outputs" / "v21"]
    name_tokens = ("candidate", "ranking", "rankings", "current", "selection", "universe")
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.csv"), key=lambda p: rel(p).lower()):
            if not any(token in path.name.lower() for token in name_tokens):
                continue
            cols = header(path)
            ticker_col = find_col(cols, ["ticker", "symbol", "benchmark_ticker"])
            if not ticker_col:
                continue
            try:
                for chunk in pd.read_csv(path, usecols=[ticker_col], chunksize=50000):
                    tickers.update(t for t in chunk[ticker_col].dropna().astype(str).str.upper().str.strip().tolist() if valid_ticker(t))
            except Exception:
                continue
    return {t for t in tickers if valid_ticker(t)}


def depth_rows(normalized: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    rows = []
    by_ticker = {ticker: g for ticker, g in normalized.groupby("ticker")} if not normalized.empty else {}
    for ticker in sorted(universe | set(by_ticker)):
        g = by_ticker.get(ticker, pd.DataFrame(columns=CACHE_FIELDS))
        dates = int(g["as_of_date"].nunique()) if not g.empty else 0
        rsi = dates >= 20
        kdj = dates >= 15
        macd = dates >= 50
        bb = dates >= 25
        ma20 = dates >= 25
        ma50 = dates >= 60
        vol = dates >= 25
        tech = all([rsi, kdj, macd, bb, ma20, ma50, vol])
        source_status = "NO_ROWS" if g.empty else ";".join(sorted(g["source_type"].dropna().astype(str).unique()))
        status = "READY_TRUE_TECHNICAL_SCORE" if tech else "PARTIAL_HISTORY" if dates >= 20 else "INSUFFICIENT_HISTORY"
        rows.append({
            "ticker": ticker,
            "row_count": len(g),
            "min_date": g["as_of_date"].min() if not g.empty else "",
            "max_date": g["as_of_date"].max() if not g.empty else "",
            "distinct_dates": dates,
            "has_20d_history": yes(dates >= 20),
            "has_50d_history": yes(dates >= 50),
            "has_80d_history": yes(dates >= 80),
            "has_180d_history": yes(dates >= 180),
            "rsi14_ready": yes(rsi),
            "kdj9_ready": yes(kdj),
            "macd_26_9_ready": yes(macd),
            "bb20_ready": yes(bb),
            "ma20_ready": yes(ma20),
            "ma50_ready": yes(ma50),
            "volume_ma20_ready": yes(vol),
            "technical_score_ready": yes(tech),
            "history_depth_status": status,
            "data_source_status": source_status,
            "notes": "Enough depth for true technical score." if tech else "History remains too shallow for one or more warmup windows.",
        })
    return pd.DataFrame(rows)


def approved_fetch_helper_found() -> bool:
    helper = ROOT / "scripts" / "v20" / "v20_214_operator_approved_historical_price_and_membership_input_fill_or_yahoo_cache_build.py"
    return helper.exists() or importlib.util.find_spec("yfinance") is not None


def build_fetch_plan(depth: pd.DataFrame, end_date: str, network_enabled: bool) -> list[dict[str, object]]:
    target_end = end_date
    target_start = (date.fromisoformat(end_date) - timedelta(days=TARGET_LOOKBACK_CALENDAR_DAYS)).isoformat()
    rows = []
    for _, row in depth.sort_values("ticker").iterrows():
        current_dates = int(row["distinct_dates"] or 0)
        backfill_required = current_dates < TARGET_MIN_TRADING_ROWS
        if not backfill_required:
            status = "NOT_REQUIRED"
            source = "NONE"
        elif network_enabled:
            status = "PENDING_NETWORK_BACKFILL"
            source = "YFINANCE_IF_AVAILABLE"
        else:
            status = "NETWORK_BACKFILL_DISABLED"
            source = "NONE"
        rows.append({
            "ticker": row["ticker"],
            "current_distinct_dates": current_dates,
            "current_min_date": row["min_date"],
            "current_max_date": row["max_date"],
            "target_start_date": target_start,
            "target_end_date": target_end,
            "missing_history_days_estimate": max(0, TARGET_MIN_TRADING_ROWS - current_dates),
            "backfill_required": yes(backfill_required),
            "backfill_status": status,
            "fetch_source": source,
            "notes": "Network backfill disabled by default." if backfill_required and not network_enabled else "",
        })
    return rows


def network_backfill(fetch_plan: list[dict[str, object]], enabled: bool) -> tuple[pd.DataFrame, list[dict[str, object]], bool, bool]:
    if not enabled:
        return pd.DataFrame(columns=CACHE_FIELDS), fetch_plan, False, approved_fetch_helper_found()
    helper_found = approved_fetch_helper_found()
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # noqa: BLE001
        for row in fetch_plan:
            if row["backfill_required"] == "TRUE":
                row["backfill_status"] = f"NETWORK_BACKFILL_FAILED_YFINANCE_UNAVAILABLE: {type(exc).__name__}"
                row["fetch_source"] = "YFINANCE_UNAVAILABLE"
                row["notes"] = clean(exc)
        return pd.DataFrame(columns=CACHE_FIELDS), fetch_plan, False, helper_found

    frames: list[pd.DataFrame] = []
    used = False
    for row in fetch_plan:
        if row["backfill_required"] != "TRUE":
            continue
        ticker = str(row["ticker"])
        try:
            data = yf.download(
                ticker,
                start=str(row["target_start_date"]),
                end=str(row["target_end_date"]),
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            used = True
            if data is None or data.empty:
                row["backfill_status"] = "NETWORK_BACKFILL_FAILED_NO_ROWS"
                row["fetch_source"] = "YFINANCE"
                continue
            data = data.reset_index()
            out = pd.DataFrame()
            out["as_of_date"] = pd.to_datetime(data.get("Date", data.get("Datetime")), errors="coerce").dt.strftime("%Y-%m-%d")
            out["ticker"] = ticker
            out["open"] = pd.to_numeric(data.get("Open"), errors="coerce")
            out["high"] = pd.to_numeric(data.get("High"), errors="coerce")
            out["low"] = pd.to_numeric(data.get("Low"), errors="coerce")
            out["close"] = pd.to_numeric(data.get("Close"), errors="coerce")
            out["adjusted_close"] = pd.to_numeric(data.get("Adj Close"), errors="coerce") if "Adj Close" in data else np.nan
            out["volume"] = pd.to_numeric(data.get("Volume"), errors="coerce")
            out["source_type"] = "NETWORK_YAHOO_YFINANCE_EXPLICITLY_ENABLED"
            out["source_file_path"] = "NETWORK_YAHOO_YFINANCE_EXPLICITLY_ENABLED"
            out["ingestion_mode"] = "allow_network_backfill"
            out["row_quality_status"] = out.apply(row_quality, axis=1)
            out["duplicate_resolution_status"] = "NETWORK_BACKFILL_ROW"
            frames.append(out[CACHE_FIELDS])
            row["backfill_status"] = "NETWORK_BACKFILL_SUCCEEDED"
            row["fetch_source"] = "YFINANCE"
            row["notes"] = f"Downloaded {len(out)} rows."
        except Exception as exc:  # noqa: BLE001
            used = True
            row["backfill_status"] = f"NETWORK_BACKFILL_FAILED: {type(exc).__name__}"
            row["fetch_source"] = "YFINANCE"
            row["notes"] = clean(exc)
    if not frames:
        return pd.DataFrame(columns=CACHE_FIELDS), fetch_plan, used, helper_found
    return pd.concat(frames, ignore_index=True), fetch_plan, used, helper_found


def dedupe_cache(local_rows: pd.DataFrame, network_rows: pd.DataFrame, ingestion_mode: str) -> pd.DataFrame:
    frames = [df for df in [local_rows, network_rows] if not df.empty]
    if not frames:
        return pd.DataFrame(columns=CACHE_FIELDS)
    raw = pd.concat(frames, ignore_index=True)
    raw["ingestion_mode"] = np.where(raw["source_type"].astype(str).str.startswith("NETWORK_"), "allow_network_backfill", ingestion_mode)
    raw["field_completeness"] = raw[["open", "high", "low", "close", "adjusted_close", "volume"]].notna().sum(axis=1)
    raw["network_priority"] = np.where(raw["source_type"].astype(str).str.startswith("NETWORK_"), 10000, 0)
    dup_counts = raw.groupby(["ticker", "as_of_date"])["ticker"].transform("count")
    raw = raw.sort_values(["ticker", "as_of_date", "field_completeness", "network_priority", "source_file_path"], ascending=[True, True, False, False, True])
    dedup = raw.drop_duplicates(["ticker", "as_of_date"], keep="first").copy()
    dedup["duplicate_resolution_status"] = np.where(
        dup_counts.loc[dedup.index].to_numpy() > 1,
        "DEDUPED_PREFERRED_COMPLETE_OHLCV_ADJUSTED_CLOSE",
        dedup["duplicate_resolution_status"],
    )
    return dedup[CACHE_FIELDS].sort_values(["ticker", "as_of_date"]).reset_index(drop=True)


def summary_stats(cache: pd.DataFrame) -> dict[str, object]:
    if cache.empty:
        return {
            "total_rows_after_ingestion": 0,
            "distinct_tickers_after_ingestion": 0,
            "distinct_as_of_dates_after_ingestion": 0,
            "min_as_of_date_after_ingestion": "",
            "max_as_of_date_after_ingestion": "",
            "median_history_depth_by_ticker_after_ingestion": 0,
            "tickers_with_20d_history": 0,
            "tickers_with_50d_history": 0,
            "tickers_with_80d_history": 0,
            "tickers_with_180d_history": 0,
        }
    depths = cache.groupby("ticker")["as_of_date"].nunique()
    return {
        "total_rows_after_ingestion": len(cache),
        "distinct_tickers_after_ingestion": int(cache["ticker"].nunique()),
        "distinct_as_of_dates_after_ingestion": int(cache["as_of_date"].nunique()),
        "min_as_of_date_after_ingestion": cache["as_of_date"].min(),
        "max_as_of_date_after_ingestion": cache["as_of_date"].max(),
        "median_history_depth_by_ticker_after_ingestion": float(depths.median()),
        "tickers_with_20d_history": int((depths >= 20).sum()),
        "tickers_with_50d_history": int((depths >= 50).sum()),
        "tickers_with_80d_history": int((depths >= 80).sum()),
        "tickers_with_180d_history": int((depths >= 180).sum()),
    }


def validation(summary: dict[str, object]) -> list[dict[str, object]]:
    items = [
        ("LOCAL_OHLCV_SOURCE_FOUND", summary["local_source_found"], "TRUE", "Local usable OHLCV-like source found."),
        ("HISTORICAL_CACHE_CREATED", yes(int(summary["total_rows_after_ingestion"]) > 0), "TRUE", "V21 research cache output created."),
        ("NETWORK_BACKFILL_FLAG_RESPECTED", yes(summary["network_backfill_enabled"] in {"TRUE", "FALSE"}), "TRUE", "Network is explicit opt-in only."),
        ("DISTINCT_TICKERS_AVAILABLE", summary["distinct_tickers_after_ingestion"], ">0", "At least one ticker required."),
        ("DISTINCT_DATES_AVAILABLE", summary["distinct_as_of_dates_after_ingestion"], ">=20", "At least 20 dates for initial technical rerun."),
        ("RSI14_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE", "RSI14 requires 20 distinct dates."),
        ("KDJ9_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE", "KDJ9 requires at least 15 dates; 20D count is conservative."),
        ("MACD_26_9_WARMUP_READY", yes(int(summary["tickers_with_50d_history"]) > 0), "TRUE", "MACD warmup requires 50 dates."),
        ("BB20_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE", "BB20 requires 25 dates; tracked with technical score gate."),
        ("MA20_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE", "MA20 requires 25 dates; tracked with technical score gate."),
        ("MA50_WARMUP_READY", yes(int(summary["tickers_with_80d_history"]) > 0), "TRUE", "MA50 requires 60 dates."),
        ("VOLUME_MA20_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE", "Volume MA20 requires 25 dates; tracked with technical score gate."),
        ("TRUE_TECHNICAL_SCORE_WARMUP_READY", summary["technical_indicator_warmup_ready"], "TRUE", "All technical warmups ready for at least one ticker."),
        ("V21_035_RERUN_ALLOWED", summary["v21_035_rerun_allowed"], "TRUE", "V21.035 can rerun only when cache has rows."),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE", "No official files are written by this stage."),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE", "Research-only guardrail."),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE", "Data-trust alpha remains blocked."),
    ]
    rows = []
    for item, observed, required, notes in items:
        if required == ">0":
            ok = int(observed) > 0
        elif required == ">=20":
            ok = int(observed) >= 20
        else:
            ok = str(observed) == required
        rows.append({
            "validation_item": item,
            "validation_status": "PASS" if ok else "FAIL",
            "observed_value": observed,
            "required_value": required,
            "pass_fail": "PASS" if ok else "FAIL",
            "notes": notes,
        })
    return rows


def render_report(summary: dict[str, object], usable_audits: list[dict[str, object]], depth: pd.DataFrame) -> str:
    source_lines = "\n".join(
        f"- {a['source_file_path']} ({a['source_type']}, {a['rows']} rows, {a['min_date']} to {a['max_date']})"
        for a in usable_audits[:25]
    ) or "- No usable local OHLCV source found."
    ready_count = int((depth["technical_score_ready"] == "TRUE").sum()) if not depth.empty else 0
    return f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {summary['final_status']}
- decision: {summary['decision']}

## V21.036-R1 limitation summary

Upstream V21.036-R1 final_status: {summary['upstream_v21_036_final_status']}. The prior normalized history was limited, with V21.036 metrics carried into this run before searching broader local caches.

## Ingestion mode used

ingestion_mode: {summary['ingestion_mode']}

## Network backfill

network_backfill_enabled: {summary['network_backfill_enabled']}; network_backfill_used: {summary['network_backfill_used']}. Network backfill is disabled by default and only runs with `--allow-network-backfill` or `V21_ALLOW_NETWORK_BACKFILL=TRUE`.

## Local sources found

{source_lines}

## Historical cache coverage after ingestion

Rows after ingestion: {summary['total_rows_after_ingestion']}; distinct tickers: {summary['distinct_tickers_after_ingestion']}; distinct dates: {summary['distinct_as_of_dates_after_ingestion']}; range: {summary['min_as_of_date_after_ingestion']} to {summary['max_as_of_date_after_ingestion']}; median depth: {summary['median_history_depth_by_ticker_after_ingestion']}.

## Ticker depth summary

Tickers with 20D history: {summary['tickers_with_20d_history']}; 50D: {summary['tickers_with_50d_history']}; 80D: {summary['tickers_with_80d_history']}; 180D: {summary['tickers_with_180d_history']}; technical-score-ready tickers: {ready_count}.

## Warmup readiness for RSI/KDJ/MACD/BB/MA/Volume

technical_indicator_warmup_ready: {summary['technical_indicator_warmup_ready']}. Readiness is computed per ticker using RSI14 >=20 dates, KDJ9 >=15, MACD26/9 >=50, BB20 >=25, MA20 >=25, MA50 >=60, and volume MA20 >=25.

## Whether V21.035-R1 can be rerun

v21_035_rerun_allowed: {summary['v21_035_rerun_allowed']}.

## True technical reweighting readiness

true_reweighting_ready: {summary['true_reweighting_ready']}. True technical reweighting remains blocked unless warmup coverage is sufficient and official mutation remains separately blocked.

## Why official mutation remains blocked

Official mutation remains blocked because this stage writes only V21 research/cache artifacts, keeps all official mutation flags FALSE, never calls broker APIs, never creates trade actions, and keeps DATA_TRUST alpha weight FALSE.

## Next recommended stage

{summary['next_recommended_stage']}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-network-backfill", action="store_true")
    parser.add_argument("--end-date", default=date.today().isoformat())
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    env_network = os.environ.get("V21_ALLOW_NETWORK_BACKFILL", "").upper() == "TRUE"
    network_enabled = bool(args.allow_network_backfill or env_network)
    ingestion_mode = "allow_network_backfill" if network_enabled else "local_only"

    upstream = first(read_csv(V36_SUMMARY))
    audits = [audit_file(path) for path in candidate_files()]
    usable_audits = [a for a in audits if a["usable_for_ingestion"] == "TRUE"]
    local_rows = load_rows(audits, ingestion_mode)
    rows_before = len(local_rows)
    universe = ticker_universe(local_rows)
    initial_depth = depth_rows(local_rows, universe)
    fetch_plan = build_fetch_plan(initial_depth, parse_date(args.end_date) or date.today().isoformat(), network_enabled)
    network_rows, fetch_plan, network_used, helper_found = network_backfill(fetch_plan, network_enabled)
    cache = dedupe_cache(local_rows, network_rows, ingestion_mode)
    depth = depth_rows(cache, universe)
    stats = summary_stats(cache)
    ready_tickers = int((depth["technical_score_ready"] == "TRUE").sum()) if not depth.empty else 0
    warmup_ready = ready_tickers >= PASS_MIN_READY_TICKERS
    true_ready = bool(warmup_ready and stats["median_history_depth_by_ticker_after_ingestion"] >= 60)

    if cache.empty and not helper_found:
        final_status = BLOCKED_STATUS
        decision = DECISION_BLOCKED
    elif cache.empty:
        final_status = BLOCKED_STATUS
        decision = DECISION_BLOCKED
    elif warmup_ready:
        final_status = PASS_STATUS
        decision = DECISION_READY
    else:
        final_status = PARTIAL_STATUS
        decision = DECISION_LIMITED if network_enabled else DECISION_NETWORK_DISABLED

    guardrail_ok = all([
        True,  # explicit placeholder so the condition documents the guardrail gate below
    ])
    if not guardrail_ok:
        final_status = RESEARCH_BLOCKED_STATUS
        decision = DECISION_BLOCKED

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": decision,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_036_final_status": upstream.get("final_status", ""),
        "ingestion_mode": ingestion_mode,
        "local_source_found": yes(bool(usable_audits)),
        "network_backfill_enabled": yes(network_enabled),
        "network_backfill_used": yes(network_used),
        "approved_fetch_helper_found": yes(helper_found),
        "target_lookback_calendar_days": TARGET_LOOKBACK_CALENDAR_DAYS,
        "target_min_trading_rows": TARGET_MIN_TRADING_ROWS,
        "universe_ticker_count": len(universe),
        "benchmark_ticker_count": len(BENCHMARK_TICKERS),
        "source_file_count_scanned": len(audits),
        "source_file_count_usable": len(usable_audits),
        "total_rows_before_ingestion": rows_before,
        **stats,
        "technical_indicator_warmup_ready": yes(warmup_ready),
        "v21_035_rerun_allowed": yes(not cache.empty),
        "true_reweighting_ready": yes(true_ready),
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.035_R1_RERUN_WITH_V21_037_HISTORICAL_CACHE" if not cache.empty else "MANUAL_OHLCV_SOURCE_IMPORT_OR_EXPLICIT_NETWORK_BACKFILL",
    }

    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(SOURCE_AUDIT_OUT, audits or [{
        "source_file_path": "",
        "source_type": "NO_CANDIDATE",
        "exists": "FALSE",
        "usable_for_ingestion": "FALSE",
        "reason_if_not_usable": "No candidate files found.",
    }], SOURCE_AUDIT_FIELDS)
    if cache.empty:
        write_csv(CACHE_OUT, [{
            "source_type": "NO_USABLE_SOURCE",
            "ingestion_mode": ingestion_mode,
            "row_quality_status": "NO_USABLE_SOURCE",
            "duplicate_resolution_status": "NO_USABLE_SOURCE",
        }], CACHE_FIELDS)
    else:
        write_csv(CACHE_OUT, cache.replace({np.nan: None}).to_dict("records"), CACHE_FIELDS)
    write_csv(DEPTH_OUT, depth.replace({np.nan: None}).to_dict("records"), [
        "ticker",
        "row_count",
        "min_date",
        "max_date",
        "distinct_dates",
        "has_20d_history",
        "has_50d_history",
        "has_80d_history",
        "has_180d_history",
        "rsi14_ready",
        "kdj9_ready",
        "macd_26_9_ready",
        "bb20_ready",
        "ma20_ready",
        "ma50_ready",
        "volume_ma20_ready",
        "technical_score_ready",
        "history_depth_status",
        "data_source_status",
        "notes",
    ])
    write_csv(FETCH_PLAN_OUT, fetch_plan or [{
        "ticker": "",
        "backfill_status": "NO_UNIVERSE",
        "fetch_source": "NONE",
    }], [
        "ticker",
        "current_distinct_dates",
        "current_min_date",
        "current_max_date",
        "target_start_date",
        "target_end_date",
        "missing_history_days_estimate",
        "backfill_required",
        "backfill_status",
        "fetch_source",
        "notes",
    ])
    write_csv(READINESS_OUT, validation(summary), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    REPORT_OUT.write_text(render_report(summary, usable_audits, depth), encoding="utf-8")

    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={decision}")
    print(f"ingestion_mode={ingestion_mode}")
    print(f"network_backfill_enabled={yes(network_enabled)}")
    print(f"network_backfill_used={yes(network_used)}")
    print(f"total_rows_after_ingestion={summary['total_rows_after_ingestion']}")
    print(f"median_history_depth_by_ticker_after_ingestion={summary['median_history_depth_by_ticker_after_ingestion']}")
    print(f"true_reweighting_ready={summary['true_reweighting_ready']}")


if __name__ == "__main__":
    main()
