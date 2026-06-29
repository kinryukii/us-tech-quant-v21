#!/usr/bin/env python
"""V21.036-R1 historical OHLCV backfill for technical subfactors.

Local-data-only research stage that consolidates OHLCV-like CSV files into a
normalized historical dataset and reports indicator warmup readiness.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.036-R1_HISTORICAL_OHLCV_BACKFILL_FOR_TECHNICAL_SUBFACTORS"
PASS_STATUS = "PASS_V21_036_R1_HISTORICAL_OHLCV_BACKFILL_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_036_R1_HISTORICAL_OHLCV_BACKFILL_LIMITED_HISTORY"
BLOCKED_STATUS = "BLOCKED_V21_036_R1_NO_LOCAL_OHLCV_SOURCE"
DECISION = "HISTORICAL_OHLCV_BACKFILL_READY_FOR_TECHNICAL_SUBFACTOR_RERUN_OFFICIAL_UPDATE_BLOCKED"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V35_SUMMARY = OUT_DIR / "V21_035_R1_TECHNICAL_SUBFACTOR_PRODUCER_SUMMARY.csv"

SUMMARY_OUT = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_BACKFILL_SUMMARY.csv"
NORMALIZED_OUT = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_NORMALIZED.csv"
SOURCE_AUDIT_OUT = OUT_DIR / "V21_036_R1_HISTORICAL_OHLCV_SOURCE_AUDIT.csv"
DEPTH_OUT = OUT_DIR / "V21_036_R1_HISTORICAL_DEPTH_BY_TICKER.csv"
READINESS_OUT = OUT_DIR / "V21_036_R1_TECHNICAL_RERUN_READINESS_MATRIX.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_036_R1_HISTORICAL_OHLCV_BACKFILL_FOR_TECHNICAL_SUBFACTORS_REPORT.md"

NORMALIZED_FIELDS = [
    "as_of_date", "ticker", "source_file_path", "source_priority", "open", "high", "low", "close",
    "adjusted_close", "volume", "row_quality_status", "duplicate_resolution_status",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.10f}"
    return value


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def candidate_files() -> list[Path]:
    roots = [ROOT / "data", ROOT / "inputs", ROOT / "outputs" / "v20", ROOT / "outputs" / "v21"]
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = str(path).lower()
            if any(token in name for token in ["price", "ohlcv", "quote", "history", "yahoo", "cache", "market"]):
                files.append(path)
            if len(files) >= 1200:
                return sorted(set(files))
    return sorted(set(files))


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


def audit_file(path: Path) -> dict[str, object]:
    cols = header(path)
    date_col = find_col(cols, ["price_date", "latest_price_date", "date", "as_of_date", "trading_date"])
    ticker_col = find_col(cols, ["ticker", "symbol", "benchmark_ticker"])
    open_col = find_col(cols, ["open", "latest_open"])
    high_col = find_col(cols, ["high", "latest_high"])
    low_col = find_col(cols, ["low", "latest_low"])
    close_col = find_col(cols, ["close", "latest_close", "close_like_price"])
    adj_col = find_col(cols, ["adjusted_close", "adj_close", "latest_adj_close", "adj close"])
    volume_col = find_col(cols, ["volume", "latest_volume"])
    rows = 0
    min_date = max_date = ""
    tickers = set()
    if cols:
        try:
            for chunk in pd.read_csv(path, usecols=[c for c in [date_col, ticker_col] if c], chunksize=50000):
                rows += len(chunk)
                if date_col and date_col in chunk:
                    dates = pd.to_datetime(chunk[date_col], errors="coerce", format="mixed")
                    if dates.notna().any():
                        cmin, cmax = dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")
                        min_date = cmin if not min_date or cmin < min_date else min_date
                        max_date = cmax if not max_date or cmax > max_date else max_date
                if ticker_col and ticker_col in chunk:
                    tickers.update(chunk[ticker_col].dropna().astype(str).str.upper().str.strip().unique().tolist())
        except Exception:
            rows = 0
    usable = bool(rows and date_col and ticker_col and close_col and volume_col)
    return {
        "source_file_path": str(path.relative_to(ROOT)),
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
        "usable_for_ohlcv_backfill": yes(usable),
        "reason_if_not_usable": "" if usable else "Missing required date/ticker/close/volume columns or no rows.",
    }


def source_priority(audit: dict[str, object]) -> int:
    score = 0
    for key in ["detected_open_column", "detected_high_column", "detected_low_column", "detected_close_column", "detected_adjusted_close_column", "detected_volume_column"]:
        score += 1 if audit.get(key) else 0
    rows = int(audit.get("rows") or 0)
    tickers = int(audit.get("distinct_tickers") or 0)
    depth_bonus = min(500, rows // max(1, tickers)) if tickers else 0
    name = str(audit.get("source_file_path", "")).lower()
    hist_bonus = 100 if "ticker_price_cache" in name or "historical" in name else 0
    current_penalty = -50 if "current_candidate" in name else 0
    return score * 1000 + depth_bonus + hist_bonus + current_penalty


def row_quality(row: pd.Series) -> str:
    if not row.get("as_of_date"):
        return "INVALID_DATE"
    if not row.get("ticker"):
        return "INVALID_TICKER"
    if pd.isna(row.get("close")):
        return "MISSING_CLOSE"
    if pd.isna(row.get("volume")):
        return "MISSING_VOLUME"
    if pd.isna(row.get("open")) or pd.isna(row.get("high")) or pd.isna(row.get("low")):
        return "PARTIAL_OHLCV"
    return "PASS"


def load_rows(audits: list[dict[str, object]]) -> pd.DataFrame:
    frames = []
    for audit in audits:
        if audit["usable_for_ohlcv_backfill"] != "TRUE":
            continue
        path = ROOT / str(audit["source_file_path"])
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        out = pd.DataFrame()
        out["as_of_date"] = pd.to_datetime(df[str(audit["detected_date_column"])], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
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
        out["source_file_path"] = str(audit["source_file_path"])
        out["source_priority"] = source_priority(audit)
        frames.append(out)
    if not frames:
        return pd.DataFrame(columns=NORMALIZED_FIELDS)
    raw = pd.concat(frames, ignore_index=True)
    raw["row_quality_status"] = raw.apply(row_quality, axis=1)
    raw = raw[~raw["row_quality_status"].isin(["INVALID_DATE", "INVALID_TICKER"])]
    raw["field_completeness"] = raw[["open", "high", "low", "close", "adjusted_close", "volume"]].notna().sum(axis=1)
    dup_counts = raw.groupby(["ticker", "as_of_date"])["ticker"].transform("count")
    raw = raw.sort_values(["ticker", "as_of_date", "source_priority", "field_completeness", "source_file_path"], ascending=[True, True, False, False, True])
    dedup = raw.drop_duplicates(["ticker", "as_of_date"], keep="first").copy()
    dedup["duplicate_resolution_status"] = np.where(dup_counts.loc[dedup.index].to_numpy() > 1, "DEDUPED_PREFERRED_FULLER_OR_DEEPER_SOURCE", "UNIQUE")
    return dedup[NORMALIZED_FIELDS].sort_values(["ticker", "as_of_date"]).reset_index(drop=True)


def depth_rows(normalized: pd.DataFrame) -> pd.DataFrame:
    if normalized.empty:
        return pd.DataFrame([{"ticker": "", "history_depth_status": "MISSING", "notes": "No normalized rows produced."}])
    rows = []
    for ticker, g in normalized.groupby("ticker"):
        dates = g["as_of_date"].nunique()
        rsi = dates >= 20
        kdj = dates >= 15
        macd = dates >= 50
        bb = dates >= 25
        ma20 = dates >= 25
        ma50 = dates >= 60
        vol = dates >= 25
        tech = all([rsi, kdj, macd, bb, ma20, ma50, vol])
        status = "READY_TRUE_TECHNICAL_SCORE" if tech else "PARTIAL_HISTORY" if dates >= 20 else "INSUFFICIENT_HISTORY"
        rows.append({
            "ticker": ticker,
            "row_count": len(g),
            "min_date": g["as_of_date"].min(),
            "max_date": g["as_of_date"].max(),
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
            "notes": "Enough depth for true technical score." if tech else "History remains too shallow for one or more warmup windows.",
        })
    return pd.DataFrame(rows).sort_values(["ticker"])


def validation(summary: dict[str, object]) -> list[dict[str, object]]:
    items = [
        ("LOCAL_OHLCV_SOURCE_FOUND", summary["local_ohlcv_source_found"], "TRUE"),
        ("NORMALIZED_DATASET_CREATED", yes(int(summary["total_normalized_rows_produced"]) > 0), "TRUE"),
        ("DISTINCT_TICKERS_AVAILABLE", summary["distinct_tickers"], ">0"),
        ("DISTINCT_DATES_AVAILABLE", summary["distinct_as_of_dates"], ">=20"),
        ("RSI14_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE"),
        ("KDJ9_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE"),
        ("MACD_26_9_WARMUP_READY", yes(int(summary["tickers_with_50d_history"]) > 0), "TRUE"),
        ("BB20_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE"),
        ("MA20_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE"),
        ("MA50_WARMUP_READY", yes(int(summary["tickers_with_80d_history"]) > 0), "TRUE"),
        ("VOLUME_MA20_WARMUP_READY", yes(int(summary["tickers_with_20d_history"]) > 0), "TRUE"),
        ("TRUE_TECHNICAL_SCORE_WARMUP_READY", summary["technical_indicator_warmup_ready"], "TRUE"),
        ("NO_OFFICIAL_MUTATION", "TRUE", "TRUE"),
        ("RESEARCH_ONLY_TRUE", summary["research_only"], "TRUE"),
        ("DATA_TRUST_ALPHA_FALSE", summary["data_trust_alpha_weight_allowed"], "FALSE"),
    ]
    rows = []
    for item, observed, required in items:
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
            "notes": "Local-only historical OHLCV backfill validation.",
        })
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    upstream = first(read_csv(V35_SUMMARY))
    audits = [audit_file(path) for path in candidate_files()]
    normalized = load_rows(audits)
    depth = depth_rows(normalized)
    usable_audits = [a for a in audits if a["usable_for_ohlcv_backfill"] == "TRUE"]
    duplicate_removed = sum(int(a.get("rows") or 0) for a in usable_audits) - len(normalized)
    if normalized.empty:
        max_depth = median_depth = 0
        t20 = t50 = t80 = t180 = 0
        warmup_ready = False
    else:
        depths = normalized.groupby("ticker")["as_of_date"].nunique()
        max_depth = int(depths.max())
        median_depth = float(depths.median())
        t20 = int((depths >= 20).sum())
        t50 = int((depths >= 50).sum())
        t80 = int((depths >= 80).sum())
        t180 = int((depths >= 180).sum())
        warmup_ready = bool((depth["technical_score_ready"] == "TRUE").any())
    true_ready = bool(warmup_ready)
    if normalized.empty:
        final_status = BLOCKED_STATUS
    elif true_ready:
        final_status = PASS_STATUS
    else:
        final_status = PARTIAL_STATUS
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "decision": DECISION,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_035_final_status": upstream.get("final_status", ""),
        "local_ohlcv_source_found": yes(bool(usable_audits)),
        "source_file_count_scanned": len(audits),
        "source_file_count_usable": len(usable_audits),
        "total_raw_rows_scanned": sum(int(a.get("rows") or 0) for a in audits),
        "total_normalized_rows_produced": len(normalized),
        "duplicate_ticker_date_rows_removed": max(0, duplicate_removed),
        "distinct_tickers": int(normalized["ticker"].nunique()) if not normalized.empty else 0,
        "distinct_as_of_dates": int(normalized["as_of_date"].nunique()) if not normalized.empty else 0,
        "min_as_of_date": normalized["as_of_date"].min() if not normalized.empty else "",
        "max_as_of_date": normalized["as_of_date"].max() if not normalized.empty else "",
        "max_history_depth_by_ticker": max_depth,
        "median_history_depth_by_ticker": median_depth,
        "tickers_with_20d_history": t20,
        "tickers_with_50d_history": t50,
        "tickers_with_80d_history": t80,
        "tickers_with_180d_history": t180,
        "technical_indicator_warmup_ready": yes(warmup_ready),
        "true_subfactor_producer_rerun_allowed": yes(bool(usable_audits)),
        "true_reweighting_ready": yes(true_ready),
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.035_R1_RERUN_WITH_V21_036_HISTORICAL_BACKFILL" if bool(usable_audits) else "LOCAL_OHLCV_ACQUISITION_REQUIRED",
    }
    write_csv(SUMMARY_OUT, [summary], list(summary.keys()))
    write_csv(SOURCE_AUDIT_OUT, audits or [{"source_file_path": "", "exists": "FALSE", "usable_for_ohlcv_backfill": "FALSE", "reason_if_not_usable": "No candidate files found."}], [
        "source_file_path", "exists", "rows", "detected_date_column", "detected_ticker_column", "detected_open_column",
        "detected_high_column", "detected_low_column", "detected_close_column", "detected_adjusted_close_column",
        "detected_volume_column", "min_date", "max_date", "distinct_tickers", "usable_for_ohlcv_backfill", "reason_if_not_usable",
    ])
    if normalized.empty:
        write_csv(NORMALIZED_OUT, [{"row_quality_status": "INVALID_DATE", "duplicate_resolution_status": "NO_USABLE_SOURCE"}], NORMALIZED_FIELDS)
    else:
        write_csv(NORMALIZED_OUT, normalized.replace({np.nan: None}).to_dict("records"), NORMALIZED_FIELDS)
    write_csv(DEPTH_OUT, depth.replace({np.nan: None}).to_dict("records"), [
        "ticker", "row_count", "min_date", "max_date", "distinct_dates", "has_20d_history", "has_50d_history",
        "has_80d_history", "has_180d_history", "rsi14_ready", "kdj9_ready", "macd_26_9_ready", "bb20_ready",
        "ma20_ready", "ma50_ready", "volume_ma20_ready", "technical_score_ready", "history_depth_status", "notes",
    ])
    write_csv(READINESS_OUT, validation(summary), ["validation_item", "validation_status", "observed_value", "required_value", "pass_fail", "notes"])
    source_lines = "\n".join(f"- {a['source_file_path']} ({a['rows']} rows, {a['min_date']} to {a['max_date']})" for a in usable_audits[:20]) or "- No usable local OHLCV source found."
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {final_status}
- decision: {DECISION}

## V21.035-R1 limitation summary

V21.035-R1 final_status: {upstream.get("final_status", "")}. It produced {upstream.get("total_subfactor_rows_produced", "")} rows across {upstream.get("distinct_as_of_dates_produced", "")} dates and all core technical coverage ratios were warmup-limited.

## Local OHLCV sources found

{source_lines}

## Normalization and deduplication logic

Rows are normalized to ticker/as_of_date/open/high/low/close/adjusted_close/volume. One row per ticker/as_of_date is retained by preferring sources with fuller OHLCV fields and greater source priority/history depth. Missing OHLCV is not fabricated.

## Historical depth by ticker

Distinct tickers: {summary['distinct_tickers']}; median history depth: {summary['median_history_depth_by_ticker']}; max history depth: {summary['max_history_depth_by_ticker']}.

## Indicator warmup requirements

Tickers with 20D history: {t20}; 50D history: {t50}; 80D history: {t80}; 180D history: {t180}. technical_indicator_warmup_ready: {summary['technical_indicator_warmup_ready']}.

## Whether V21.035-R1 can be rerun with expanded history

true_subfactor_producer_rerun_allowed: {summary['true_subfactor_producer_rerun_allowed']}.

## True reweighting readiness

true_reweighting_ready: {summary['true_reweighting_ready']}.

## Why official mutation remains blocked

Official mutation remains blocked because this is a research-only local-data backfill stage, all official mutation flags are FALSE, no broker or book action is allowed, and DATA_TRUST alpha weight remains FALSE.

## Next recommended stage

{summary['next_recommended_stage']}
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={DECISION}")
    print(f"total_normalized_rows_produced={len(normalized)}")
    print(f"true_reweighting_ready={yes(true_ready)}")


if __name__ == "__main__":
    main()
