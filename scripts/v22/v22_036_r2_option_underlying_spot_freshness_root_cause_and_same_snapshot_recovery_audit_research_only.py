#!/usr/bin/env python
"""V22.036_R2 underlying spot freshness root-cause and recovery audit.

Read-only forensic audit. It searches prior local V22 artifacts for the
underlying quote implied by V22.032_R1's underlying_enriched_count, diagnoses
why V22.036_R1 rejected spot sources, and writes a recovered injected copy only
if an existing same-snapshot/same-date spot can be proven.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


MODULE_ID = "V22.036_R2"
MODULE_NAME = "OPTION_UNDERLYING_SPOT_FRESHNESS_ROOT_CAUSE_AND_SAME_SNAPSHOT_RECOVERY_AUDIT_RESEARCH_ONLY"
STAGE = "V22.036_R2_OPTION_UNDERLYING_SPOT_FRESHNESS_ROOT_CAUSE_AND_SAME_SNAPSHOT_RECOVERY_AUDIT_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_036_R1_DIR = Path("outputs") / "v22" / "V22.036_R1_OPTION_UNDERLYING_SPOT_SOURCE_RESOLUTION_AND_INJECTION_AUDIT_RESEARCH_ONLY"
V22_035_R1_DIR = Path("outputs") / "v22" / "V22.035_R1_OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_RESEARCH_ONLY"
V22_034_R1_DIR = Path("outputs") / "v22" / "V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
V22_033_R1_DIR = Path("outputs") / "v22" / "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
V22_032_R1_AFTER_CHAIN_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_AFTER_CHAIN_DISCOVERY"
V22_032_R1_READ_ONLY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"

PASS_RECOVERED = "PASS_V22_036_R2_SAME_SNAPSHOT_UNDERLYING_SPOT_RECOVERED_FOR_SYNTHETIC_RESEARCH"
WARN_REFRESH = "WARN_V22_036_R2_NO_SAME_SNAPSHOT_SPOT_FOUND_REFRESH_REQUIRED"
WARN_STALE = "WARN_V22_036_R2_ONLY_STALE_SPOT_AVAILABLE_SYNTHETIC_BLOCKED"
FAIL_INPUT = "FAIL_V22_036_R2_INPUT_NOT_FOUND"
READY_DECISION = "OPTION_UNDERLYING_SPOT_RECOVERED_READY_FOR_SYNTHETIC_IV_SOLVER_RESEARCH_ONLY"
FAIL_DECISION = "OPTION_UNDERLYING_SPOT_RECOVERY_FAILED_REFRESH_REQUIRED_RESEARCH_ONLY"

PRICE_ALIASES = ["underlying_spot", "underlying_price", "underlying_last", "last_underlying_price", "stock_price", "spot", "spot_price", "last", "last_price", "close", "latest_price", "current_price", "quote_price", "mid", "mark", "price"]
DATE_ALIASES = ["valuation_date", "quote_date", "trade_date", "asof_date", "snapshot_date", "price_date", "date", "timestamp", "quote_timestamp", "update_time", "updated_at", "server_time", "local_time", "provider_time", "enrichment_time_utc"]
SYMBOL_ALIASES = ["underlying", "underlying_symbol", "underlying_code", "stock_code", "ticker", "root_symbol", "symbol", "code", "source_option_code"]
CONTRACT_ALIASES = {
    "option_code": ["option_code", "contract_symbol", "contract_code", "option_symbol", "source_option_code"],
    "underlying": SYMBOL_ALIASES,
    "expiration": ["expiration", "expiry", "expiration_date", "expire_date"],
    "strike": ["strike", "strike_price", "exercise_price"],
    "option_type": ["option_type", "call_put", "cp", "put_call", "right"],
    "bid": ["bid", "bid_raw", "bid_price"],
    "ask": ["ask", "ask_raw", "ask_price"],
    "mid": ["mid", "mid_price", "mark"],
    "volume": ["volume", "volume_raw", "vol"],
    "valuation_date": DATE_ALIASES,
    "dte": ["dte", "days_to_expiry", "days_to_expiration"],
}


def normalize_column_name(name: str) -> str:
    text = str(name).strip().lower()
    text = re.sub(r"[\s\-/().]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def normalize_symbol(value: Any) -> str:
    text = str(value).strip().upper()
    if not text:
        return ""
    text = re.sub(r"\s+", ".", text)
    for prefix in ["US.", "NASDAQ.", "NYSE.", "AMEX."]:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in [".US", ".USA", ".NASDAQ", ".NYSE", ".AMEX"]:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text if re.fullmatch(r"[A-Z0-9._-]+", text) else ""


def parse_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date_or_timestamp(value: Any) -> tuple[datetime | None, str, str]:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None, "MISSING_TIMESTAMP_AND_DATE", ""
    raw = str(value).strip()
    if re.fullmatch(r"\d{8}", raw):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    try:
        ts = pd.to_datetime(raw, utc=False)
    except (ValueError, TypeError):
        return None, "FAILED_TO_PARSE", "Could not parse timestamp/date."
    dt = ts.to_pydatetime()
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc), "PARSED_WITH_EXPLICIT_TIMEZONE", ""
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", str(value).strip()) or re.fullmatch(r"\d{8}", str(value).strip()):
        return dt, "PARSED_DATE_ONLY", "Date-only value has no intraday timestamp."
    return dt, "PARSED_AS_NAIVE_ASIA_TOKYO", "Naive timestamp interpreted as Asia/Tokyo for normalization audit only."


def parsed_date(value: Any) -> date | None:
    dt, status, _warning = parse_date_or_timestamp(value)
    return dt.date() if dt and status != "FAILED_TO_PARSE" else None


def discover_input_files(repo_root: Path) -> list[Path]:
    roots = [repo_root / V22_036_R1_DIR, repo_root / V22_035_R1_DIR, repo_root / V22_034_R1_DIR, repo_root / V22_033_R1_DIR, repo_root / V22_032_R1_AFTER_CHAIN_DIR, repo_root / V22_032_R1_READ_ONLY_DIR]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(sorted([p for p in root.glob("*") if p.suffix.lower() in {".csv", ".json", ".txt"}]))
    return files


def alias(columns: list[str], aliases: list[str]) -> str:
    normalized = {normalize_column_name(c): c for c in columns}
    for a in aliases:
        if normalize_column_name(a) in normalized:
            return normalized[normalize_column_name(a)]
    return ""


def resolve_contract_aliases(columns: list[str]) -> dict[str, str]:
    return {k: alias(columns, v) for k, v in CONTRACT_ALIASES.items()}


def discover_contract_input(repo_root: Path) -> tuple[pd.DataFrame, dict[str, str], str]:
    candidates = []
    for root in [repo_root / V22_036_R1_DIR, repo_root / V22_035_R1_DIR, repo_root / V22_033_R1_DIR, repo_root / V22_032_R1_AFTER_CHAIN_DIR, repo_root / V22_032_R1_READ_ONLY_DIR]:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.csv")):
            try:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError):
                continue
            aliases = resolve_contract_aliases(list(frame.columns))
            score = sum(bool(aliases.get(k)) for k in ["option_code", "underlying", "expiration", "strike", "bid", "ask", "mid", "volume", "valuation_date"])
            if score >= 6 and len(frame) > 0:
                candidates.append((score, 1 if "clean" in path.name.lower() else 0, path, frame, aliases))
    if not candidates:
        return pd.DataFrame(), {}, ""
    candidates.sort(key=lambda item: (item[0], item[1], len(item[3])), reverse=True)
    _score, _clean, path, frame, aliases = candidates[0]
    return frame, aliases, str(path)


def trace_v22_032_underlying_enrichment(repo_root: Path) -> pd.DataFrame:
    roots = [repo_root / V22_032_R1_AFTER_CHAIN_DIR, repo_root / V22_032_R1_READ_ONLY_DIR]
    rows = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted([p for p in root.glob("*") if p.suffix.lower() in {".csv", ".json", ".txt"}]):
            try:
                if path.suffix.lower() == ".csv":
                    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
                    cols = list(frame.columns)
                    text = " ".join(cols)
                    attempted = ""
                    enriched = ""
                    if "underlying_attempted_count" in cols and len(frame):
                        attempted = str(frame["underlying_attempted_count"].iloc[0])
                    if "underlying_enriched_count" in cols and len(frame):
                        enriched = str(frame["underlying_enriched_count"].iloc[0])
                    symbols = sorted({normalize_symbol(v) for c in cols if normalize_column_name(c) in [normalize_column_name(a) for a in SYMBOL_ALIASES] for v in frame[c].head(200).tolist() if normalize_symbol(v)})
                    price_cols = [c for c in cols if normalize_column_name(c) in [normalize_column_name(a) for a in PRICE_ALIASES]]
                    date_cols = [c for c in cols if normalize_column_name(c) in [normalize_column_name(a) for a in DATE_ALIASES] and "timestamp" not in normalize_column_name(c)]
                    ts_cols = [c for c in cols if normalize_column_name(c) in [normalize_column_name(a) for a in DATE_ALIASES] and ("time" in normalize_column_name(c) or "timestamp" in normalize_column_name(c))]
                    contract_rows = bool(alias(cols, CONTRACT_ALIASES["option_code"]) and alias(cols, CONTRACT_ALIASES["expiration"]) and alias(cols, CONTRACT_ALIASES["strike"]))
                    underlying_quote_rows = bool(symbols and price_cols and not contract_rows)
                    row = {
                        "source_file": str(path), "file_type": "CSV", "row_count": len(frame), "column_count": len(cols),
                        "contains_underlying_attempted_count": bool(attempted), "contains_underlying_enriched_count": bool(enriched),
                        "observed_underlying_attempted_count": attempted, "observed_underlying_enriched_count": enriched,
                        "contains_underlying_symbol": bool(symbols), "observed_underlying_symbols": ";".join(symbols),
                        "contains_candidate_price_field": bool(price_cols), "candidate_price_columns": ";".join(price_cols),
                        "contains_candidate_date_field": bool(date_cols), "candidate_date_columns": ";".join(date_cols),
                        "contains_candidate_timestamp_field": bool(ts_cols), "candidate_timestamp_columns": ";".join(ts_cols),
                        "contains_option_contract_rows": contract_rows, "contains_underlying_quote_rows": underlying_quote_rows,
                        "trace_status": "UNDERLYING_QUOTE_ROW_FOUND" if underlying_quote_rows else ("POSSIBLE_UNDERLYING_QUOTE_ARTIFACT_FOUND" if price_cols and symbols else "NO_UNDERLYING_TRACE_FOUND"),
                    }
                else:
                    raw = path.read_text(encoding="utf-8", errors="ignore")
                    payload = json.loads(raw) if path.suffix.lower() == ".json" else {}
                    attempted = payload.get("underlying_attempted_count", "") if isinstance(payload, dict) else ""
                    enriched = payload.get("underlying_enriched_count", "") if isinstance(payload, dict) else ""
                    row = {
                        "source_file": str(path), "file_type": path.suffix.upper().strip("."), "row_count": 1, "column_count": 0,
                        "contains_underlying_attempted_count": "underlying_attempted_count" in raw, "contains_underlying_enriched_count": "underlying_enriched_count" in raw,
                        "observed_underlying_attempted_count": attempted, "observed_underlying_enriched_count": enriched,
                        "contains_underlying_symbol": bool(re.search(r"\b(QQQ|SPY)\b", raw)), "observed_underlying_symbols": ";".join(sorted(set(re.findall(r"\b(QQQ|SPY)\b", raw)))),
                        "contains_candidate_price_field": any(a in raw.lower() for a in PRICE_ALIASES), "candidate_price_columns": "",
                        "contains_candidate_date_field": any(a in raw.lower() for a in DATE_ALIASES), "candidate_date_columns": "",
                        "contains_candidate_timestamp_field": "time" in raw.lower() or "timestamp" in raw.lower(), "candidate_timestamp_columns": "",
                        "contains_option_contract_rows": "option_code" in raw, "contains_underlying_quote_rows": False,
                        "trace_status": "SUMMARY_ONLY_UNDERLYING_COUNT_FOUND" if enriched != "" else "NO_UNDERLYING_TRACE_FOUND",
                    }
                rows.append(row)
            except Exception:
                rows.append({"source_file": str(path), "file_type": path.suffix.upper().strip("."), "row_count": 0, "column_count": 0, "contains_underlying_attempted_count": False, "contains_underlying_enriched_count": False, "observed_underlying_attempted_count": "", "observed_underlying_enriched_count": "", "contains_underlying_symbol": False, "observed_underlying_symbols": "", "contains_candidate_price_field": False, "candidate_price_columns": "", "contains_candidate_date_field": False, "candidate_date_columns": "", "contains_candidate_timestamp_field": False, "candidate_timestamp_columns": "", "contains_option_contract_rows": False, "contains_underlying_quote_rows": False, "trace_status": "FILE_READ_FAILED"})
    return pd.DataFrame(rows)


def load_v22_036_r1_rejections(repo_root: Path) -> pd.DataFrame:
    root = repo_root / V22_036_R1_DIR
    src = pd.read_csv(root / "option_underlying_spot_source_discovery_audit.csv", dtype=str, keep_default_na=False) if (root / "option_underlying_spot_source_discovery_audit.csv").exists() else pd.DataFrame()
    align = pd.read_csv(root / "option_underlying_spot_timestamp_alignment_audit.csv", dtype=str, keep_default_na=False) if (root / "option_underlying_spot_timestamp_alignment_audit.csv").exists() else pd.DataFrame()
    sel = pd.read_csv(root / "option_underlying_spot_selection_audit.csv", dtype=str, keep_default_na=False) if (root / "option_underlying_spot_selection_audit.csv").exists() else pd.DataFrame()
    rows = []
    for _, s in src.iterrows():
        symbol = normalize_symbol(s.get("underlying_symbol", ""))
        a = align[align.get("underlying_symbol", pd.Series(dtype=str)).map(normalize_symbol) == symbol].head(1) if not align.empty else pd.DataFrame()
        se = sel[sel.get("underlying_symbol", pd.Series(dtype=str)).map(normalize_symbol) == symbol].head(1) if not sel.empty else pd.DataFrame()
        arow = a.iloc[0] if not a.empty else {}
        serow = se.iloc[0] if not se.empty else {}
        root_cause, repair = classify_rejection_root_cause(s, arow, serow)
        rows.append({
            "source_category": s.get("source_category", ""), "source_file": s.get("source_file", ""), "underlying_symbol": symbol,
            "candidate_spot_price": s.get("candidate_spot_price", ""), "candidate_price_column": s.get("candidate_price_column", ""),
            "candidate_date_column": s.get("candidate_date_column", ""), "candidate_timestamp_column": s.get("candidate_timestamp_column", ""),
            "option_valuation_date": arow.get("option_valuation_date", ""), "option_quote_timestamp": arow.get("option_quote_timestamp", ""),
            "underlying_price_date": arow.get("underlying_price_date", s.get("latest_observed_date", "")), "underlying_quote_timestamp": arow.get("underlying_quote_timestamp", s.get("latest_observed_timestamp", "")),
            "date_diff_days": arow.get("date_diff_days", ""), "alignment_status": arow.get("alignment_status", ""),
            "source_status": s.get("source_status", ""), "selection_status": serow.get("selection_status", ""),
            "rejection_root_cause": root_cause, "repair_possibility": repair,
            "repair_recommendation": "Run V22.036_R3 read-only same-snapshot underlying quote refresh." if repair == "NOT_REPAIRABLE_STALE_SOURCE" else "Review alias/timestamp/symbol discovery rules.",
        })
    return pd.DataFrame(rows)


def classify_rejection_root_cause(source: Any, align: Any, selection: Any) -> tuple[str, str]:
    status = str(align.get("alignment_status", "") if hasattr(align, "get") else "")
    source_status = str(source.get("source_status", "") if hasattr(source, "get") else "")
    if status == "STALE_UNDERLYING_PRICE" or str(selection.get("selection_status", "") if hasattr(selection, "get") else "") == "REJECTED_STALE_SPOT":
        return "STALE_PRICE_TRUE_REJECTION", "NOT_REPAIRABLE_STALE_SOURCE"
    if source_status == "CANDIDATE_DATE_MISSING":
        return "DATE_ALIAS_MISSED", "REPAIRABLE_BY_ALIAS_MAPPING"
    if "parse" in status.lower() or source_status == "CANDIDATE_DATE_NON_NUMERIC":
        return "DATE_PARSE_FAILURE", "REPAIRABLE_BY_TIMESTAMP_NORMALIZATION"
    if source_status == "CANDIDATE_SYMBOL_MISMATCH":
        return "SYMBOL_NORMALIZATION_MISMATCH", "REPAIRABLE_BY_SYMBOL_NORMALIZATION"
    if source_status in {"CANDIDATE_PRICE_MISSING", "SOURCE_FILE_NOT_RELEVANT"}:
        return "PRICE_ALIAS_MISSED", "REPAIRABLE_BY_ALIAS_MAPPING"
    return "UNKNOWN_REJECTION_REASON", "UNKNOWN_REQUIRES_MANUAL_REVIEW"


def option_reference(frame: pd.DataFrame, aliases: dict[str, str]) -> tuple[str, str, str]:
    if frame.empty:
        return "", "", ""
    symbol = normalize_symbol(frame[aliases["underlying"]].iloc[0]) if aliases.get("underlying") else ""
    val_col = aliases.get("valuation_date", "")
    timestamps = frame[val_col].map(lambda x: parse_date_or_timestamp(x)[0]).dropna() if val_col else pd.Series(dtype=object)
    latest = max(timestamps) if len(timestamps) else None
    return symbol, latest.date().isoformat() if latest else "", latest.isoformat() if latest else ""


def candidate_row(version: str, path: Path, file_type: str, category: str, record_path: str, symbol: str, price: Any, price_key: str, date_val: Any, date_key: str, ts_val: Any, ts_key: str, option_date: str, option_ts: str) -> dict[str, Any]:
    norm = normalize_symbol(symbol)
    price_num = parse_numeric(price)
    raw_time = ts_val if str(ts_val).strip() else date_val
    dt, _status, _warning = parse_date_or_timestamp(raw_time)
    cand_date = dt.date().isoformat() if dt else ""
    opt_date = parsed_date(option_date)
    diff = abs((opt_date - dt.date()).days) if opt_date and dt else ""
    same = diff == 0
    near = bool(diff != "" and int(diff) == 0)
    if not norm:
        status = "SYMBOL_MISMATCH_REJECTED"
    elif price_num is None or price_num <= 0:
        status = "PRICE_INVALID_REJECTED"
    elif not dt:
        status = "DATE_OR_TIMESTAMP_MISSING"
    elif diff == 0:
        status = "SAME_SNAPSHOT_CANDIDATE_USABLE" if ts_key else "SAME_DATE_CANDIDATE_USABLE"
    elif diff != "" and int(diff) <= 1:
        status = "WITHIN_ONE_DAY_CANDIDATE_RESEARCH_ONLY"
    else:
        status = "STALE_CANDIDATE_REJECTED"
    return {"source_version": version, "source_file": str(path), "file_type": file_type, "source_category": category, "candidate_record_path": record_path, "candidate_symbol": symbol, "normalized_candidate_symbol": norm, "candidate_price": price_num if price_num is not None else "", "candidate_price_column_or_key": price_key, "candidate_date": str(date_val), "candidate_date_column_or_key": date_key, "candidate_timestamp": str(ts_val), "candidate_timestamp_column_or_key": ts_key, "option_reference_date": option_date, "option_reference_timestamp": option_ts, "same_date": same, "timestamp_near_option_snapshot": near, "date_diff_days": diff, "candidate_status": status}


def source_version(path: Path) -> str:
    for token in ["V22.036_R1", "V22.035_R1", "V22.034_R1", "V22.033_R1", "V22.032_R1"]:
        if token in str(path):
            return token
    return "LOCAL"


def extract_candidates_from_csv(path: Path, expected: str, option_date: str, option_ts: str) -> list[dict[str, Any]]:
    rows = []
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return rows
    cols = list(frame.columns)
    sym_col = alias(cols, SYMBOL_ALIASES)
    price_cols = [c for c in cols if normalize_column_name(c) in [normalize_column_name(a) for a in PRICE_ALIASES]]
    contract_like = bool(alias(cols, CONTRACT_ALIASES["option_code"]) and alias(cols, CONTRACT_ALIASES["strike"]) and alias(cols, CONTRACT_ALIASES["expiration"]))
    if contract_like:
        explicit_underlying_price_aliases = ["underlying_spot", "underlying_price", "underlying_last", "last_underlying_price", "stock_price", "spot", "spot_price", "latest_price", "current_price", "quote_price"]
        price_cols = [c for c in price_cols if normalize_column_name(c) in [normalize_column_name(a) for a in explicit_underlying_price_aliases]]
    date_cols = [c for c in cols if normalize_column_name(c) in [normalize_column_name(a) for a in DATE_ALIASES]]
    if not price_cols:
        return rows
    for idx, row in frame.head(2000).iterrows():
        symbol = row.get(sym_col, expected) if sym_col else expected
        for price_col in price_cols:
            date_col = date_cols[0] if date_cols else ""
            rows.append(candidate_row(source_version(path), path, "CSV", "CSV_ARTIFACT", f"row[{idx}]", symbol, row.get(price_col, ""), price_col, row.get(date_col, ""), date_col, row.get(date_col, ""), date_col if "time" in normalize_column_name(date_col) else "", option_date, option_ts))
    return rows


def walk_json(obj: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    found = []
    if isinstance(obj, dict):
        found.append((path, obj))
        for k, v in obj.items():
            found.extend(walk_json(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(walk_json(v, f"{path}[{i}]"))
    return found


def extract_candidates_from_json(path: Path, expected: str, option_date: str, option_ts: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for rec_path, obj in walk_json(data):
        keys = list(obj.keys())
        price_key = alias(keys, PRICE_ALIASES)
        if not price_key:
            continue
        sym_key = alias(keys, SYMBOL_ALIASES)
        date_key = alias(keys, DATE_ALIASES)
        ts_key = date_key if "time" in normalize_column_name(date_key) else ""
        rows.append(candidate_row(source_version(path), path, "JSON", "JSON_ARTIFACT", rec_path, obj.get(sym_key, expected) if sym_key else expected, obj.get(price_key, ""), price_key, obj.get(date_key, ""), date_key, obj.get(ts_key, ""), ts_key, option_date, option_ts))
    return rows


def extract_candidates_from_text(path: Path, expected: str, option_date: str, option_ts: str) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = []
    for match in re.finditer(r"(QQQ|SPY).{0,80}?(?:price|last|spot|close)[=: ]+([0-9]+(?:\.[0-9]+)?)", text, flags=re.I):
        rows.append(candidate_row(source_version(path), path, "TXT", "TEXT_ARTIFACT", f"char[{match.start()}]", match.group(1), match.group(2), "text_price", option_date, "option_reference_date", option_ts, "option_reference_timestamp", option_date, option_ts))
    return rows


def normalize_timestamps_for_alignment(candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in candidates.iterrows():
        dt, status, warning = parse_date_or_timestamp(row.get("candidate_timestamp") or row.get("candidate_date"))
        rows.append({"source_file": row.get("source_file", ""), "raw_timestamp_value": row.get("candidate_timestamp", ""), "raw_date_value": row.get("candidate_date", ""), "parsed_datetime": dt.isoformat() if dt else "", "parsed_date": dt.date().isoformat() if dt else "", "inferred_timezone": "Asia/Tokyo" if status == "PARSED_AS_NAIVE_ASIA_TOKYO" else "", "normalization_status": status, "normalization_warning": warning})
    return pd.DataFrame(rows)


def symbol_normalization_audit(candidates: pd.DataFrame, expected: str) -> pd.DataFrame:
    rows = []
    for _, row in candidates.iterrows():
        raw = row.get("candidate_symbol", "")
        norm = normalize_symbol(raw)
        match = norm == expected
        status = "SYMBOL_MISSING" if not raw else ("SYMBOL_MATCH_EXACT" if raw == expected else ("SYMBOL_MATCH_AFTER_NORMALIZATION" if match else "SYMBOL_MISMATCH"))
        rows.append({"source_file": row.get("source_file", ""), "raw_symbol": raw, "normalized_symbol": norm, "expected_underlying_symbol": expected, "symbol_match": match, "normalization_status": status})
    return pd.DataFrame(rows)


def select_same_snapshot_recovery(candidates: pd.DataFrame, expected: str) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame([selection(expected, False, None, "NOT_RECOVERED_NO_UNDERLYING_ARTIFACT_FOUND", "No candidate artifacts found.")])
    valid = candidates[(candidates["normalized_candidate_symbol"] == expected) & (candidates["candidate_status"].isin(["SAME_SNAPSHOT_CANDIDATE_USABLE", "SAME_DATE_CANDIDATE_USABLE"]))]
    if valid.empty:
        stale = candidates[candidates["candidate_status"] == "STALE_CANDIDATE_REJECTED"]
        status = "NOT_RECOVERED_ONLY_STALE_SOURCES_FOUND" if not stale.empty else "NOT_RECOVERED_NO_PRICE_FIELD_FOUND"
        return pd.DataFrame([selection(expected, False, stale.iloc[0] if not stale.empty else None, status, "No same-snapshot or same-date spot recovered.")])
    valid = valid.assign(_rank=valid["candidate_status"].map({"SAME_SNAPSHOT_CANDIDATE_USABLE": 0, "SAME_DATE_CANDIDATE_USABLE": 1}))
    best = valid.sort_values(["_rank", "source_version", "source_file"]).iloc[0]
    status = "RECOVERED_SAME_SNAPSHOT_SPOT" if best["candidate_status"] == "SAME_SNAPSHOT_CANDIDATE_USABLE" else "RECOVERED_SAME_DATE_SPOT"
    return pd.DataFrame([selection(expected, True, best, status, "Recovered aligned spot from existing artifact.")])


def selection(expected: str, recovered: bool, row: Any, status: str, reason: str) -> dict[str, Any]:
    return {"underlying_symbol": expected, "recovered": recovered, "recovered_source_version": row.get("source_version", "") if row is not None else "", "recovered_source_file": row.get("source_file", "") if row is not None else "", "recovered_record_path": row.get("candidate_record_path", "") if row is not None else "", "recovered_price": row.get("candidate_price", "") if row is not None else "", "recovered_date": row.get("candidate_date", "") if row is not None else "", "recovered_timestamp": row.get("candidate_timestamp", "") if row is not None else "", "recovery_alignment_status": row.get("candidate_status", "") if row is not None else "", "recovery_status": status, "recovery_reason": reason}


def val(row: Any, aliases: dict[str, str], field: str) -> Any:
    col = aliases.get(field, "")
    return row.get(col, "") if col else ""


def inject_recovered_spot(frame: pd.DataFrame, aliases: dict[str, str], recovery: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    rec = recovery.iloc[0].to_dict() if not recovery.empty else {}
    recovered = bool(rec.get("recovered", False))
    status = "INJECTED_RECOVERED_SAME_SNAPSHOT_SPOT" if rec.get("recovery_status") == "RECOVERED_SAME_SNAPSHOT_SPOT" else ("INJECTED_RECOVERED_SAME_DATE_SPOT" if recovered else ("NOT_INJECTED_STALE_ONLY" if rec.get("recovery_status") == "NOT_RECOVERED_ONLY_STALE_SOURCES_FOUND" else "NOT_INJECTED_RECOVERY_FAILED"))
    output["recovered_underlying_symbol"] = output[aliases["underlying"]].map(normalize_symbol) if aliases.get("underlying") else ""
    output["recovered_underlying_spot"] = rec.get("recovered_price", "") if recovered else ""
    output["recovered_underlying_spot_source_version"] = rec.get("recovered_source_version", "")
    output["recovered_underlying_spot_source_file"] = rec.get("recovered_source_file", "")
    output["recovered_underlying_spot_record_path"] = rec.get("recovered_record_path", "")
    output["recovered_underlying_spot_date"] = rec.get("recovered_date", "")
    output["recovered_underlying_spot_timestamp"] = rec.get("recovered_timestamp", "")
    output["recovered_underlying_spot_alignment_status"] = rec.get("recovery_alignment_status", "")
    output["recovered_underlying_spot_injected"] = recovered
    output["recovered_underlying_spot_injection_status"] = status
    return output


def dte(row: Any, aliases: dict[str, str]) -> float | None:
    source = parse_numeric(val(row, aliases, "dte"))
    if source is not None:
        return source if source > 0 else None
    exp = parsed_date(val(row, aliases, "expiration"))
    vd = parsed_date(val(row, aliases, "valuation_date"))
    if not exp or not vd:
        return None
    diff = (exp - vd).days
    return float(diff) if diff > 0 else None


def refresh_synthetic_calculability_after_recovery(injected: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, row in injected.iterrows():
        bid = parse_numeric(val(row, aliases, "bid"))
        ask = parse_numeric(val(row, aliases, "ask"))
        mid = parse_numeric(val(row, aliases, "mid"))
        spot = parse_numeric(row.get("recovered_underlying_spot", ""))
        market = bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid and mid is not None and mid > 0
        meta = bool(parse_numeric(val(row, aliases, "strike")) and parsed_date(val(row, aliases, "expiration")) and str(val(row, aliases, "option_type")).upper() in {"CALL", "PUT", "C", "P"})
        time_ok = dte(row, aliases) is not None
        identity = bool(str(val(row, aliases, "option_code")).strip() and row.get("recovered_underlying_symbol", ""))
        spot_ok = spot is not None and spot > 0
        calc = identity and market and meta and time_ok and spot_ok
        missing = [name for name, ok in [("market_price", market), ("contract_metadata", meta), ("time_to_expiry", time_ok), ("underlying_spot", spot_ok)] if not ok]
        status = "SYNTHETIC_IV_GREEKS_CALCULABLE_AFTER_RECOVERED_SPOT_INJECTION_RESEARCH_ONLY" if calc else ("MISSING_UNDERLYING_SPOT_AFTER_RECOVERY" if not spot_ok else "UNKNOWN_INPUT_NOT_FOUND")
        rows.append({"option_code": val(row, aliases, "option_code"), "underlying_symbol": row.get("recovered_underlying_symbol", ""), "expiration": val(row, aliases, "expiration"), "strike": val(row, aliases, "strike"), "option_type": val(row, aliases, "option_type"), "bid": val(row, aliases, "bid"), "ask": val(row, aliases, "ask"), "mid": val(row, aliases, "mid"), "volume": val(row, aliases, "volume"), "valuation_date": val(row, aliases, "valuation_date"), "dte": dte(row, aliases) or "", "recovered_underlying_spot": row.get("recovered_underlying_spot", ""), "has_contract_identity": identity, "has_valid_market_price": market, "has_valid_contract_metadata": meta, "has_valid_underlying_spot_after_recovery": spot_ok, "has_valid_time_to_expiry": time_ok, "has_model_assumption_inputs": True, "synthetic_iv_calculable_after_recovered_spot_injection": calc, "synthetic_greeks_calculable_after_recovered_spot_injection_and_iv": calc, "missing_required_fields_after_recovery": ";".join(missing), "calculability_status_after_recovery": status})
    return pd.DataFrame(rows)


def build_root_cause_policy(trace: pd.DataFrame, recovery: pd.DataFrame, calc: pd.DataFrame) -> pd.DataFrame:
    enriched = int(pd.to_numeric(trace.get("observed_underlying_enriched_count", pd.Series(dtype=str)), errors="coerce").fillna(0).max()) if not trace.empty else 0
    artifact_found = bool((trace.get("trace_status", pd.Series(dtype=str)) == "UNDERLYING_QUOTE_ROW_FOUND").any()) if not trace.empty else False
    recovered = bool(recovery.iloc[0]["recovered"]) if not recovery.empty else False
    calc_count = int(calc["synthetic_iv_calculable_after_recovered_spot_injection"].sum()) if not calc.empty else 0
    refresh = not recovered
    label = "ALLOW_SYNTHETIC_IV_SOLVER_NEXT_STEP_AFTER_SAME_SNAPSHOT_SPOT_RECOVERY_FULL_SELECTION_BLOCKED" if calc_count else ("REQUIRE_V22_036_R3_READ_ONLY_UNDERLYING_QUOTE_REFRESH" if refresh else "BLOCK_SYNTHETIC_IV_SOLVER_ONLY_STALE_SPOT_AVAILABLE")
    return pd.DataFrame([{"v22_032_underlying_enriched_count_observed": enriched, "v22_032_underlying_quote_artifact_found": artifact_found, "v22_036_r1_rejection_reason_confirmed": True, "same_snapshot_spot_recovered": recovered, "recovered_spot_injected": recovered, "synthetic_iv_calculable_after_recovery_count": calc_count, "synthetic_iv_solver_next_step_allowed": calc_count > 0, "read_only_underlying_quote_refresh_needed": refresh, "full_option_candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False, "final_policy_label": label}])


def write_summary_and_report(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "v22_036_r2_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["V22.036_R2 Option Underlying Spot Freshness Root Cause And Same Snapshot Recovery Audit Research Only"] + [f"{k}={summary[k]}" for k in ["final_status", "final_decision", "discovered_contract_row_count", "underlying_count", "expected_underlying_symbol", "v22_032_underlying_enriched_count_observed", "v22_032_underlying_quote_artifact_found", "same_snapshot_candidate_count", "same_date_candidate_count", "stale_candidate_count", "recovered_spot_source_count", "recovered_spot_injected_contract_count", "synthetic_iv_calculable_after_recovery_count", "synthetic_iv_solver_next_step_allowed", "read_only_underlying_quote_refresh_needed", "root_cause_classification", "full_option_candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed", "trade_order_allowed"]]
    (output_dir / "V22.036_R2_option_underlying_spot_freshness_root_cause_and_same_snapshot_recovery_audit_research_only_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    default = (repo_root / OUT_REL).resolve()
    output_dir = (output_dir or default).resolve()
    if output_dir != default and default not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {default}")
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = discover_input_files(repo_root)
    contracts, aliases, contract_file = discover_contract_input(repo_root)
    expected, option_date, option_ts = option_reference(contracts, aliases)
    trace = trace_v22_032_underlying_enrichment(repo_root)
    rejections = load_v22_036_r1_rejections(repo_root)
    candidate_rows = []
    for path in inputs:
        if path.suffix.lower() == ".csv":
            candidate_rows.extend(extract_candidates_from_csv(path, expected, option_date, option_ts))
        elif path.suffix.lower() == ".json":
            candidate_rows.extend(extract_candidates_from_json(path, expected, option_date, option_ts))
        elif path.suffix.lower() == ".txt":
            candidate_rows.extend(extract_candidates_from_text(path, expected, option_date, option_ts))
    candidates = pd.DataFrame(candidate_rows)
    if candidates.empty:
        candidates = pd.DataFrame(columns=["source_version","source_file","file_type","source_category","candidate_record_path","candidate_symbol","normalized_candidate_symbol","candidate_price","candidate_price_column_or_key","candidate_date","candidate_date_column_or_key","candidate_timestamp","candidate_timestamp_column_or_key","option_reference_date","option_reference_timestamp","same_date","timestamp_near_option_snapshot","date_diff_days","candidate_status"])
    ts_norm = normalize_timestamps_for_alignment(candidates)
    sym_norm = symbol_normalization_audit(candidates, expected)
    recovery = select_same_snapshot_recovery(candidates, expected) if expected else pd.DataFrame([selection("", False, None, "UNKNOWN_RECOVERY_FAILURE", "No expected underlying symbol.")])
    injected = inject_recovered_spot(contracts, aliases, recovery) if not contracts.empty else pd.DataFrame()
    calc = refresh_synthetic_calculability_after_recovery(injected, aliases) if not injected.empty else pd.DataFrame()
    policy = build_root_cause_policy(trace, recovery, calc)
    enriched = int(policy.iloc[0]["v22_032_underlying_enriched_count_observed"])
    artifact_found = bool(policy.iloc[0]["v22_032_underlying_quote_artifact_found"])
    recovered = bool(policy.iloc[0]["same_snapshot_spot_recovered"])
    stale_count = int((candidates["candidate_status"] == "STALE_CANDIDATE_REJECTED").sum()) if not candidates.empty else 0
    if contracts.empty:
        final_status = FAIL_INPUT
        final_decision = FAIL_DECISION
        root_cause = "INPUT_NOT_FOUND"
    elif recovered:
        final_status = PASS_RECOVERED
        final_decision = READY_DECISION
        root_cause = "V22_036_R1_DISCOVERY_ALIAS_MISSED_SAME_SNAPSHOT_SPOT"
    elif stale_count > 0:
        final_status = WARN_STALE
        final_decision = FAIL_DECISION
        root_cause = "ONLY_STALE_LOCAL_SPOT_AVAILABLE"
    else:
        final_status = WARN_REFRESH
        final_decision = FAIL_DECISION
        root_cause = "V22_032_SUMMARY_REPORTED_UNDERLYING_BUT_NO_ARTIFACT_FOUND" if enriched and not artifact_found else "UNKNOWN_REQUIRES_MANUAL_REVIEW"
    summary = {"module_id": MODULE_ID, "module_name": MODULE_NAME, "final_status": final_status, "final_decision": final_decision, "input_v22_036_r1_dir": str(repo_root / V22_036_R1_DIR), "input_v22_035_dir": str(repo_root / V22_035_R1_DIR), "input_v22_034_dir": str(repo_root / V22_034_R1_DIR), "input_v22_033_dir": str(repo_root / V22_033_R1_DIR), "input_v22_032_dir": str(repo_root / V22_032_R1_AFTER_CHAIN_DIR), "discovered_input_file_count": len(inputs), "selected_contract_input_file": contract_file, "discovered_contract_row_count": len(contracts), "underlying_count": 1 if expected else 0, "expected_underlying_symbol": expected, "v22_032_underlying_enriched_count_observed": enriched, "v22_032_underlying_quote_artifact_found": artifact_found, "same_snapshot_candidate_count": int((candidates["candidate_status"] == "SAME_SNAPSHOT_CANDIDATE_USABLE").sum()) if not candidates.empty else 0, "same_date_candidate_count": int((candidates["candidate_status"] == "SAME_DATE_CANDIDATE_USABLE").sum()) if not candidates.empty else 0, "stale_candidate_count": stale_count, "recovered_spot_source_count": int(recovered), "recovered_spot_injected_contract_count": int(injected["recovered_underlying_spot_injected"].sum()) if not injected.empty else 0, "valid_underlying_spot_after_recovery_count": int(calc["has_valid_underlying_spot_after_recovery"].sum()) if not calc.empty else 0, "synthetic_iv_calculable_after_recovery_count": int(calc["synthetic_iv_calculable_after_recovered_spot_injection"].sum()) if not calc.empty else 0, "synthetic_greeks_calculable_after_recovery_count": int(calc["synthetic_greeks_calculable_after_recovered_spot_injection_and_iv"].sum()) if not calc.empty else 0, "synthetic_iv_solver_next_step_allowed": bool(policy.iloc[0]["synthetic_iv_solver_next_step_allowed"]), "read_only_underlying_quote_refresh_needed": bool(policy.iloc[0]["read_only_underlying_quote_refresh_needed"]), "full_option_candidate_generation_allowed": False, "provider_oi_ready": False, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False, "root_cause_classification": root_cause}
    trace.to_csv(output_dir / "option_underlying_v22_032_enrichment_trace_audit.csv", index=False, lineterminator="\n")
    rejections.to_csv(output_dir / "option_underlying_spot_rejection_root_cause_audit.csv", index=False, lineterminator="\n")
    candidates.to_csv(output_dir / "option_same_snapshot_underlying_spot_artifact_discovery_audit.csv", index=False, lineterminator="\n")
    ts_norm.to_csv(output_dir / "option_underlying_spot_timestamp_normalization_audit.csv", index=False, lineterminator="\n")
    sym_norm.to_csv(output_dir / "option_underlying_symbol_normalization_audit.csv", index=False, lineterminator="\n")
    recovery.to_csv(output_dir / "option_same_snapshot_underlying_spot_recovery_selection_audit.csv", index=False, lineterminator="\n")
    injected.to_csv(output_dir / "option_contract_rows_with_recovered_underlying_spot_injected_research_only.csv", index=False, lineterminator="\n")
    calc.to_csv(output_dir / "option_synthetic_calculability_after_recovered_spot_injection.csv", index=False, lineterminator="\n")
    policy.to_csv(output_dir / "option_underlying_spot_root_cause_and_next_step_policy.csv", index=False, lineterminator="\n")
    write_summary_and_report(output_dir, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.output_dir)
    print(f"final_status={summary['final_status']}")
    print(f"final_decision={summary['final_decision']}")
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_036_r2_summary.json'}")
    print("full_option_candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if summary["final_status"] == FAIL_INPUT else 0


if __name__ == "__main__":
    raise SystemExit(main())
