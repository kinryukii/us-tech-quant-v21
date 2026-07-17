#!/usr/bin/env python
"""V22.036_R1 underlying spot source resolution and injection audit.

Read-only research stage. It discovers local option contract rows and local
underlying spot artifacts, validates date alignment, and writes a new injected
copy under V22.036 only. It does not fetch data, connect to Moomoo, calculate
IV/Greeks, generate candidates, or trade.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


MODULE_ID = "V22.036_R1"
MODULE_NAME = "OPTION_UNDERLYING_SPOT_SOURCE_RESOLUTION_AND_INJECTION_AUDIT_RESEARCH_ONLY"
STAGE = "V22.036_R1_OPTION_UNDERLYING_SPOT_SOURCE_RESOLUTION_AND_INJECTION_AUDIT_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_035_R1_DIR = Path("outputs") / "v22" / "V22.035_R1_OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_RESEARCH_ONLY"
V22_034_R1_DIR = Path("outputs") / "v22" / "V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
V22_033_R1_DIR = Path("outputs") / "v22" / "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_AFTER_CHAIN_DISCOVERY"
V22_032_R1_READ_ONLY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")

PASS_READY = "PASS_V22_036_R1_UNDERLYING_SPOT_RESOLVED_FOR_SYNTHETIC_RESEARCH"
WARN_FALLBACK = "WARN_V22_036_R1_UNDERLYING_SPOT_RESOLVED_WITH_RESEARCH_ONLY_FALLBACK"
WARN_NOT_RESOLVED = "WARN_V22_036_R1_LIQUIDITY_READY_BUT_UNDERLYING_SPOT_NOT_RESOLVED"
FAIL_INPUT_NOT_FOUND = "FAIL_V22_036_R1_INPUT_NOT_FOUND"
READY_DECISION = "OPTION_UNDERLYING_SPOT_INJECTION_READY_FOR_SYNTHETIC_IV_SOLVER_RESEARCH_ONLY"
BLOCKED_DECISION = "OPTION_UNDERLYING_SPOT_INJECTION_BLOCKED_RESEARCH_ONLY"

ALIASES = {
    "option_code": ["option_code", "contract_code", "contract_symbol", "option_symbol", "code", "symbol", "source_option_code"],
    "underlying_symbol": ["underlying", "underlying_symbol", "underlying_code", "stock_code", "ticker", "root_symbol"],
    "expiration": ["expiration", "expiry", "expiration_date", "expire_date", "maturity", "maturity_date"],
    "strike": ["strike", "strike_price", "exercise_price"],
    "option_type": ["option_type", "call_put", "cp", "put_call", "right", "contract_type"],
    "bid": ["bid", "bid_price", "best_bid", "bid_raw"],
    "ask": ["ask", "ask_price", "best_ask", "ask_raw"],
    "mid": ["mid", "mid_price", "mark", "mark_price"],
    "volume": ["volume", "vol", "trade_volume", "volume_raw"],
    "valuation_date": ["valuation_date", "quote_date", "trade_date", "asof_date", "snapshot_date", "timestamp", "quote_timestamp", "enrichment_time_utc", "snapshot_time_utc"],
    "dte": ["dte", "days_to_expiry", "days_to_expiration", "time_to_expiry_days"],
}
SPOT_ALIASES = ["underlying_spot", "underlying_price", "underlying_last", "last_underlying_price", "stock_price", "spot", "spot_price", "last", "last_price", "close", "latest_price", "current_price", "quote_price", "mid", "mark", "price"]
DATE_ALIASES = ["valuation_date", "quote_date", "trade_date", "asof_date", "snapshot_date", "price_date", "date", "timestamp", "quote_timestamp", "update_time", "updated_at", "fetch_timestamp", "fetched_at_utc"]
SYMBOL_ALIASES = ["underlying", "underlying_symbol", "ticker", "symbol", "stock_code", "root_symbol", "moomoo_symbol"]


def normalize_column_name(name: str) -> str:
    text = str(name).strip().lower()
    text = re.sub(r"[\s\-/().]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def resolve_alias_columns(columns: list[str], include_spot: bool = False) -> dict[str, str]:
    normalized = {normalize_column_name(column): column for column in columns}
    resolved: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            key = normalize_column_name(alias)
            if key in normalized:
                resolved[target] = normalized[key]
                break
    if include_spot:
        for target, aliases in {"underlying_spot": SPOT_ALIASES, "price_date": DATE_ALIASES, "underlying_symbol": SYMBOL_ALIASES}.items():
            for alias in aliases:
                key = normalize_column_name(alias)
                if key in normalized:
                    resolved.setdefault(target, normalized[key])
                    break
    return resolved


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


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return pd.to_datetime(text, utc=False).to_pydatetime()
    except (ValueError, TypeError):
        return None


def parse_date(value: Any) -> date | None:
    ts = parse_timestamp(value)
    return ts.date() if ts else None


def option_type(value: Any) -> str:
    text = str(value).strip().upper()
    if text in {"C", "CALL"}:
        return "CALL"
    if text in {"P", "PUT"}:
        return "PUT"
    return ""


def value(row: pd.Series, aliases: dict[str, str], field: str) -> Any:
    column = aliases.get(field)
    return row.get(column, "") if column else ""


def valid_bid_ask(row: pd.Series, aliases: dict[str, str]) -> bool:
    bid = parse_numeric(value(row, aliases, "bid"))
    ask = parse_numeric(value(row, aliases, "ask"))
    return bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid


def valid_mid(row: pd.Series, aliases: dict[str, str]) -> bool:
    mid = parse_numeric(value(row, aliases, "mid"))
    return mid is not None and mid > 0


def valid_volume(row: pd.Series, aliases: dict[str, str]) -> bool:
    return parse_numeric(value(row, aliases, "volume")) is not None


def valid_metadata(row: pd.Series, aliases: dict[str, str]) -> bool:
    return bool(parse_numeric(value(row, aliases, "strike")) and parse_date(value(row, aliases, "expiration")) and option_type(value(row, aliases, "option_type")))


def audit_dte(row: pd.Series, aliases: dict[str, str]) -> float | None:
    dte = parse_numeric(value(row, aliases, "dte"))
    if dte is not None:
        return dte if dte > 0 else None
    exp = parse_date(value(row, aliases, "expiration"))
    val = parse_date(value(row, aliases, "valuation_date"))
    if not exp or not val:
        return None
    diff = (exp - val).days
    return float(diff) if diff > 0 else None


def discover_contract_input_files(repo_root: Path) -> list[dict[str, Any]]:
    roots = [repo_root / V22_035_R1_DIR, repo_root / V22_034_R1_DIR, repo_root / V22_033_R1_DIR, repo_root / V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR, repo_root / V22_032_R1_READ_ONLY_DIR]
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.csv")):
            try:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            except (pd.errors.EmptyDataError, UnicodeDecodeError, OSError):
                continue
            aliases = resolve_alias_columns(list(frame.columns))
            flags = {f"has_{field}": bool(aliases.get(field)) for field in ["option_code", "underlying_symbol", "expiration", "strike", "option_type", "bid", "ask", "mid", "volume", "valuation_date"]}
            detected = int(len(frame)) if all(flags.get(f"has_{field}") for field in ["option_code", "underlying_symbol", "expiration", "strike", "bid", "ask"]) else 0
            score = sum(int(value) for value in flags.values()) + detected
            rows.append({"path": path, "frame": frame, "aliases": aliases, "score": score, "detected_contract_row_count": detected, **flags})
    rows.sort(key=lambda item: (item["detected_contract_row_count"], item["score"], 1 if "clean" in item["path"].name.lower() else 0), reverse=True)
    return rows


def contract_discovery_audit(candidates: list[dict[str, Any]]) -> pd.DataFrame:
    selected = candidates[0]["path"] if candidates and candidates[0]["detected_contract_row_count"] else None
    rows = []
    for item in candidates:
        path = item["path"]
        frame = item["frame"]
        aliases = item["aliases"]
        rows.append(
            {
                "source_file": str(path),
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "detected_contract_row_count": item["detected_contract_row_count"],
                "detected_underlying_count": int(frame[aliases["underlying_symbol"]].replace("", pd.NA).dropna().nunique()) if aliases.get("underlying_symbol") else 0,
                "has_option_code": item["has_option_code"],
                "has_underlying_symbol": item["has_underlying_symbol"],
                "has_expiration": item["has_expiration"],
                "has_strike": item["has_strike"],
                "has_option_type": item["has_option_type"],
                "has_bid": item["has_bid"],
                "has_ask": item["has_ask"],
                "has_mid": item["has_mid"],
                "has_volume": item["has_volume"],
                "has_valuation_date": item["has_valuation_date"],
                "selected_for_injection": selected == path,
                "selection_reason": "Highest-scoring contract-level option table." if selected == path else "Not selected; lower contract-table score.",
            }
        )
    return pd.DataFrame(rows)


def resolve_underlying_symbols(frame: pd.DataFrame, aliases: dict[str, str], source_file: str) -> pd.DataFrame:
    if frame.empty or not aliases.get("underlying_symbol"):
        return pd.DataFrame([{"observed_underlying_symbol": "", "normalized_underlying_symbol": "", "contract_count": 0, "source_file": source_file, "resolution_status": "UNKNOWN_INPUT_NOT_FOUND"}])
    series = frame[aliases["underlying_symbol"]].astype(str).str.strip()
    counts = series[series != ""].value_counts()
    if counts.empty:
        return pd.DataFrame([{"observed_underlying_symbol": "", "normalized_underlying_symbol": "", "contract_count": len(frame), "source_file": source_file, "resolution_status": "MISSING_UNDERLYING_SYMBOL"}])
    status = "RESOLVED_SINGLE_UNDERLYING" if len(counts) == 1 else "RESOLVED_MULTIPLE_UNDERLYINGS"
    return pd.DataFrame([{"observed_underlying_symbol": symbol, "normalized_underlying_symbol": normalize_symbol(symbol), "contract_count": int(count), "source_file": source_file, "resolution_status": status} for symbol, count in counts.items()])


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol).strip().upper()
    return text[3:] if text.startswith("US.") else text


def discover_underlying_spot_source_files(repo_root: Path, symbols: list[str]) -> list[tuple[str, Path]]:
    roots = [
        ("V22_032_UNDERLYING_QUOTE_ARTIFACT", repo_root / V22_032_R1_READ_ONLY_DIR),
        ("V22_033_UNDERLYING_OR_QUOTE_ARTIFACT", repo_root / V22_033_R1_DIR),
        ("V22_035_CALCULABILITY_ARTIFACT", repo_root / V22_035_R1_DIR),
    ]
    if repo_root == Path(r"D:\us-tech-quant").resolve():
        roots.extend(
            [
                ("LOCAL_MOOMOO_PRICE_CACHE", CACHE_ROOT / "market_data" / "moomoo"),
                ("LOCAL_CANONICAL_PRICE_CACHE", CACHE_ROOT / "canonical"),
                ("LOCAL_OTHER_PRICE_CACHE", CACHE_ROOT / "large_outputs"),
            ]
        )
    files: list[tuple[str, Path]] = []
    for category, root in roots:
        if not root.exists():
            continue
        if category == "LOCAL_MOOMOO_PRICE_CACHE":
            for symbol in symbols:
                for rel in [Path("daily") / "qfq" / f"{symbol}.csv", Path("daily") / "raw" / f"{symbol}.csv"]:
                    path = root / rel
                    if path.exists():
                        files.append((category, path))
            continue
        if category == "LOCAL_CANONICAL_PRICE_CACHE":
            continue
        if category == "LOCAL_OTHER_PRICE_CACHE":
            continue
        patterns = [f"{symbol}.csv" for symbol in symbols] + ["*.csv"]
        seen: set[Path] = set()
        for pattern in patterns:
            for path in sorted(root.rglob(pattern)):
                if path in seen:
                    continue
                seen.add(path)
                name = path.name.lower()
                if category.startswith("LOCAL") and not any(symbol.lower() in str(path).lower() for symbol in symbols) and path.stat().st_size > 50_000_000:
                    continue
                if any(token in name for token in ["quote", "price", "ohlcv", "calculability", "enrichment"]) or any(symbol.lower() == path.stem.lower() for symbol in symbols):
                    files.append((category, path))
    return files


def latest_candidate_for_symbol(frame: pd.DataFrame, aliases: dict[str, str], symbol: str) -> pd.Series | None:
    if frame.empty or not aliases.get("underlying_spot"):
        return None
    work = frame.copy()
    sym_col = aliases.get("underlying_symbol")
    if sym_col:
        work = work[work[sym_col].map(normalize_symbol) == normalize_symbol(symbol)]
    elif len(work) > 0:
        pass
    if work.empty:
        return None
    date_col = aliases.get("price_date")
    if date_col:
        work = work.assign(_parsed_date=work[date_col].map(parse_timestamp))
        work = work.sort_values("_parsed_date", na_position="first")
    return work.iloc[-1]


def extract_candidate_spot_sources(files: list[tuple[str, Path]], symbols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    priority = {
        "V22_032_UNDERLYING_QUOTE_ARTIFACT": 1,
        "V22_033_UNDERLYING_OR_QUOTE_ARTIFACT": 1,
        "EXISTING_CONTRACT_ROW_COLUMN": 2,
        "LOCAL_MOOMOO_PRICE_CACHE": 3,
        "LOCAL_CANONICAL_PRICE_CACHE": 4,
        "LOCAL_OTHER_PRICE_CACHE": 5,
        "V22_035_CALCULABILITY_ARTIFACT": 6,
    }
    for category, path in files:
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        except (pd.errors.EmptyDataError, UnicodeDecodeError, OSError):
            continue
        aliases = resolve_alias_columns(list(frame.columns), include_spot=True)
        price_col = aliases.get("underlying_spot", "")
        date_col = aliases.get("price_date", "")
        sym_col = aliases.get("underlying_symbol", "")
        for symbol in symbols:
            selected = latest_candidate_for_symbol(frame, aliases, symbol)
            if selected is None:
                status = "CANDIDATE_PRICE_MISSING" if price_col else "SOURCE_FILE_NOT_RELEVANT"
                rows.append(base_source_row(category, path, symbol, price_col, date_col, sym_col, len(frame), priority.get(category, 9), status))
                continue
            price = parse_numeric(selected.get(price_col, ""))
            dates = frame[date_col].map(parse_timestamp).dropna() if date_col else pd.Series(dtype=object)
            if sym_col and normalize_symbol(selected.get(sym_col, "")) != normalize_symbol(symbol):
                status = "CANDIDATE_SYMBOL_MISMATCH"
            elif price is None:
                status = "CANDIDATE_PRICE_NON_NUMERIC" if str(selected.get(price_col, "")).strip() else "CANDIDATE_PRICE_MISSING"
            elif price <= 0:
                status = "CANDIDATE_PRICE_NON_POSITIVE"
            elif not date_col or parse_date(selected.get(date_col, "")) is None:
                status = "CANDIDATE_DATE_MISSING"
            else:
                status = "CANDIDATE_USABLE"
            prices = frame[price_col].map(parse_numeric) if price_col else pd.Series(dtype=object)
            rows.append(
                {
                    "source_category": category,
                    "source_file": str(path),
                    "underlying_symbol": symbol,
                    "normalized_underlying_symbol": normalize_symbol(symbol),
                    "candidate_price_column": price_col,
                    "candidate_date_column": date_col if date_col and "date" in normalize_column_name(date_col) else "",
                    "candidate_timestamp_column": date_col if date_col and "date" not in normalize_column_name(date_col) else "",
                    "row_count": len(frame),
                    "non_null_price_count": int(frame[price_col].astype(str).str.strip().ne("").sum()) if price_col else 0,
                    "valid_numeric_price_count": int(prices.map(lambda item: item is not None).sum()) if price_col else 0,
                    "positive_price_count": int(prices.map(lambda item: item is not None and item > 0).sum()) if price_col else 0,
                    "latest_observed_date": max([ts.date().isoformat() for ts in dates], default=""),
                    "latest_observed_timestamp": max([ts.isoformat() for ts in dates], default=""),
                    "candidate_spot_price": price if price is not None else "",
                    "source_priority": priority.get(category, 9),
                    "source_status": status,
                }
            )
    if not rows:
        rows.append(base_source_row("LOCAL_OTHER_PRICE_CACHE", Path(""), "", "", "", "", 0, 9, "SOURCE_NOT_FOUND"))
    return pd.DataFrame(rows)


def base_source_row(category: str, path: Path, symbol: str, price_col: str, date_col: str, sym_col: str, row_count: int, priority: int, status: str) -> dict[str, Any]:
    return {
        "source_category": category,
        "source_file": str(path),
        "underlying_symbol": symbol,
        "normalized_underlying_symbol": normalize_symbol(symbol),
        "candidate_price_column": price_col,
        "candidate_date_column": date_col,
        "candidate_timestamp_column": "",
        "row_count": row_count,
        "non_null_price_count": 0,
        "valid_numeric_price_count": 0,
        "positive_price_count": 0,
        "latest_observed_date": "",
        "latest_observed_timestamp": "",
        "candidate_spot_price": "",
        "source_priority": priority,
        "source_status": status,
    }


def option_dates_by_symbol(frame: pd.DataFrame, aliases: dict[str, str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if frame.empty or not aliases.get("underlying_symbol"):
        return result
    sym_col = aliases["underlying_symbol"]
    val_col = aliases.get("valuation_date", "")
    for symbol, group in frame.groupby(frame[sym_col].map(normalize_symbol)):
        timestamps = group[val_col].map(parse_timestamp).dropna() if val_col else pd.Series(dtype=object)
        latest = max(timestamps) if len(timestamps) else None
        result[symbol] = {"date": latest.date().isoformat() if latest else "", "timestamp": latest.isoformat() if latest else ""}
    return result


def audit_timestamp_alignment(sources: pd.DataFrame, option_dates: dict[str, dict[str, str]]) -> pd.DataFrame:
    rows = []
    usable = sources[sources["source_status"] == "CANDIDATE_USABLE"] if not sources.empty else sources
    for _, source in usable.iterrows():
        symbol = normalize_symbol(source["underlying_symbol"])
        option_date = parse_date(option_dates.get(symbol, {}).get("date", ""))
        price_date = parse_date(source["latest_observed_date"])
        if not option_date:
            status = "MISSING_OPTION_VALUATION_DATE"
            diff = ""
        elif not price_date:
            status = "MISSING_UNDERLYING_PRICE_DATE"
            diff = ""
        else:
            diff_int = abs((option_date - price_date).days)
            diff = diff_int
            if diff_int == 0:
                status = "SAME_DATE_ALIGNED"
            elif diff_int <= 1:
                status = "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY"
            else:
                status = "STALE_UNDERLYING_PRICE"
        rows.append(
            {
                "underlying_symbol": symbol,
                "option_valuation_date": option_dates.get(symbol, {}).get("date", ""),
                "option_quote_timestamp": option_dates.get(symbol, {}).get("timestamp", ""),
                "underlying_price_date": source["latest_observed_date"],
                "underlying_quote_timestamp": source["latest_observed_timestamp"],
                "date_diff_days": diff,
                "same_date": diff == 0,
                "timestamp_available": bool(option_dates.get(symbol, {}).get("timestamp", "") and source["latest_observed_timestamp"]),
                "alignment_status": status,
                "alignment_policy_reason": "Same date preferred; one-day fallback is research-only; older prices are rejected.",
            }
        )
    if not rows:
        rows.append({"underlying_symbol": "", "option_valuation_date": "", "option_quote_timestamp": "", "underlying_price_date": "", "underlying_quote_timestamp": "", "date_diff_days": "", "same_date": False, "timestamp_available": False, "alignment_status": "UNKNOWN_ALIGNMENT", "alignment_policy_reason": "No usable source for timestamp alignment."})
    return pd.DataFrame(rows)


def select_best_spot_source(sources: pd.DataFrame, alignments: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        usable = sources[(sources["normalized_underlying_symbol"] == normalize_symbol(symbol)) & (sources["source_status"] == "CANDIDATE_USABLE")].copy()
        if usable.empty:
            rows.append(selection_row(symbol, False, None, "REJECTED_NO_USABLE_SPOT", "No usable local spot source found."))
            continue
        merged = usable.merge(alignments, left_on="normalized_underlying_symbol", right_on="underlying_symbol", how="left", suffixes=("", "_align"))
        merged = merged[merged["alignment_status"].isin(["SAME_DATE_ALIGNED", "TIMESTAMP_ALIGNED", "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY"])]
        if merged.empty:
            rows.append(selection_row(symbol, False, usable.sort_values("source_priority").iloc[0], "REJECTED_STALE_SPOT", "Only stale or unaligned spot sources were found."))
            continue
        merged = merged.assign(_align_rank=merged["alignment_status"].map({"SAME_DATE_ALIGNED": 0, "TIMESTAMP_ALIGNED": 0, "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY": 1}).fillna(9))
        best = merged.sort_values(["_align_rank", "source_priority", "source_file"]).iloc[0]
        status = "SELECTED_WITHIN_ONE_DAY_RESEARCH_ONLY_FALLBACK" if best["alignment_status"] == "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY" else ("SELECTED_SAME_DATE_LOCAL_CACHE" if "LOCAL" in best["source_category"] else "SELECTED_SAME_DATE_PROVIDER_OR_LOCAL_QUOTE")
        rows.append(selection_row(symbol, True, best, status, "Best aligned local spot source selected."))
    return pd.DataFrame(rows)


def selection_row(symbol: str, selected: bool, source: pd.Series | None, status: str, reason: str) -> dict[str, Any]:
    return {
        "underlying_symbol": normalize_symbol(symbol),
        "selected": selected,
        "selected_source_category": source.get("source_category", "") if source is not None else "",
        "selected_source_file": source.get("source_file", "") if source is not None else "",
        "selected_price_column": source.get("candidate_price_column", "") if source is not None else "",
        "selected_date_column": source.get("candidate_date_column", "") if source is not None else "",
        "selected_timestamp_column": source.get("candidate_timestamp_column", "") if source is not None else "",
        "selected_underlying_spot": source.get("candidate_spot_price", "") if source is not None else "",
        "selected_underlying_price_date": source.get("latest_observed_date", "") if source is not None else "",
        "selected_underlying_quote_timestamp": source.get("latest_observed_timestamp", "") if source is not None else "",
        "alignment_status": source.get("alignment_status", "") if source is not None else "",
        "source_priority": source.get("source_priority", "") if source is not None else "",
        "selection_status": status,
        "selection_reason": reason,
    }


def inject_underlying_spot(frame: pd.DataFrame, aliases: dict[str, str], selections: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    selected_by_symbol = {row["underlying_symbol"]: row for _, row in selections.iterrows()}
    injected_rows = []
    for _, row in output.iterrows():
        symbol = normalize_symbol(value(row, aliases, "underlying_symbol"))
        selected = selected_by_symbol.get(symbol)
        if selected is not None and bool(selected["selected"]):
            status = "INJECTED_WITHIN_ONE_DAY_RESEARCH_ONLY_FALLBACK" if selected["selection_status"] == "SELECTED_WITHIN_ONE_DAY_RESEARCH_ONLY_FALLBACK" else "INJECTED_SAME_DATE_SPOT"
            injected = True
            spot = selected["selected_underlying_spot"]
        else:
            status = "NOT_INJECTED_STALE_SPOT" if selected is not None and selected["selection_status"] == "REJECTED_STALE_SPOT" else "NOT_INJECTED_NO_USABLE_SPOT"
            injected = False
            spot = ""
        injected_rows.append(
            {
                "resolved_underlying_symbol": symbol,
                "injected_underlying_spot": spot,
                "injected_underlying_spot_source_category": selected["selected_source_category"] if selected is not None else "",
                "injected_underlying_spot_source_file": selected["selected_source_file"] if selected is not None else "",
                "injected_underlying_spot_price_date": selected["selected_underlying_price_date"] if selected is not None else "",
                "injected_underlying_spot_timestamp": selected["selected_underlying_quote_timestamp"] if selected is not None else "",
                "injected_underlying_spot_alignment_status": selected["alignment_status"] if selected is not None else "",
                "underlying_spot_injected": injected,
                "underlying_spot_injection_status": status,
            }
        )
    return pd.concat([output.reset_index(drop=True), pd.DataFrame(injected_rows)], axis=1)


def refresh_synthetic_calculability_after_injection(injected: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, row in injected.iterrows():
        spot = parse_numeric(row.get("injected_underlying_spot", ""))
        has_identity = bool(str(value(row, aliases, "option_code")).strip() and row.get("resolved_underlying_symbol", ""))
        has_market = valid_bid_ask(row, aliases) and valid_mid(row, aliases)
        has_meta = valid_metadata(row, aliases)
        has_dte = audit_dte(row, aliases) is not None
        has_spot = spot is not None and spot > 0
        missing = []
        if not has_market:
            missing.append("market_price")
        if not has_meta:
            missing.append("contract_metadata")
        if not has_dte:
            missing.append("time_to_expiry")
        if not has_spot:
            missing.append("underlying_spot")
        calc = has_identity and has_market and has_meta and has_dte and has_spot
        status = "SYNTHETIC_IV_GREEKS_CALCULABLE_AFTER_SPOT_INJECTION_RESEARCH_ONLY" if calc else ("MISSING_UNDERLYING_SPOT_AFTER_INJECTION" if not has_spot else "UNKNOWN_INPUT_NOT_FOUND")
        rows.append(
            {
                "option_code": value(row, aliases, "option_code"),
                "underlying_symbol": row.get("resolved_underlying_symbol", ""),
                "expiration": value(row, aliases, "expiration"),
                "strike": value(row, aliases, "strike"),
                "option_type": option_type(value(row, aliases, "option_type")),
                "bid": value(row, aliases, "bid"),
                "ask": value(row, aliases, "ask"),
                "mid": value(row, aliases, "mid"),
                "volume": value(row, aliases, "volume"),
                "valuation_date": value(row, aliases, "valuation_date"),
                "dte": audit_dte(row, aliases) or "",
                "injected_underlying_spot": row.get("injected_underlying_spot", ""),
                "has_contract_identity": has_identity,
                "has_valid_market_price": has_market,
                "has_valid_contract_metadata": has_meta,
                "has_valid_underlying_spot_after_injection": has_spot,
                "has_valid_time_to_expiry": has_dte,
                "has_model_assumption_inputs": True,
                "synthetic_iv_calculable_after_spot_injection": calc,
                "synthetic_greeks_calculable_after_spot_injection_and_iv": calc,
                "missing_required_fields_after_spot_injection": ";".join(missing),
                "calculability_status_after_spot_injection": status,
            }
        )
    return pd.DataFrame(rows)


def build_summary_by_underlying(calc: pd.DataFrame, selections: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol, group in calc.groupby("underlying_symbol", dropna=False):
        sel = selections[selections["underlying_symbol"] == symbol]
        selected = sel.iloc[0] if not sel.empty else {}
        total = len(group)
        iv_count = int(group["synthetic_iv_calculable_after_spot_injection"].sum())
        greek_count = int(group["synthetic_greeks_calculable_after_spot_injection_and_iv"].sum())
        rows.append(
            {
                "underlying_symbol": symbol,
                "total_contract_count": total,
                "selected_underlying_spot": selected.get("selected_underlying_spot", ""),
                "selected_source_category": selected.get("selected_source_category", ""),
                "selected_price_date": selected.get("selected_underlying_price_date", ""),
                "selected_alignment_status": selected.get("alignment_status", ""),
                "injected_contract_count": int(group["has_valid_underlying_spot_after_injection"].sum()),
                "not_injected_contract_count": total - int(group["has_valid_underlying_spot_after_injection"].sum()),
                "valid_bid_ask_count": int(group["has_valid_market_price"].sum()),
                "valid_mid_count": int(group["mid"].map(lambda x: parse_numeric(x) is not None and parse_numeric(x) > 0).sum()),
                "valid_volume_count": int(group["volume"].map(lambda x: parse_numeric(x) is not None).sum()),
                "valid_contract_metadata_count": int(group["has_valid_contract_metadata"].sum()),
                "valid_dte_count": int(group["has_valid_time_to_expiry"].sum()),
                "synthetic_iv_calculable_after_spot_injection_count": iv_count,
                "synthetic_greeks_calculable_after_spot_injection_count": greek_count,
                "synthetic_iv_calculable_after_spot_injection_ratio": round(iv_count / total, 6) if total else 0.0,
                "synthetic_greeks_calculable_after_spot_injection_ratio": round(greek_count / total, 6) if total else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_safety_policy(calc: pd.DataFrame) -> dict[str, Any]:
    if calc.empty:
        label = "FAIL_INPUT_NOT_FOUND"
        quotes_ready = liquidity_ready = spot_resolved = spot_injected = calc_ready = False
    else:
        quotes_ready = bool(calc["has_valid_market_price"].any())
        liquidity_ready = bool((calc["has_valid_market_price"] & calc["volume"].map(lambda x: parse_numeric(x) is not None)).any())
        calc_ready = bool(calc["synthetic_iv_calculable_after_spot_injection"].any())
        spot_injected = bool(calc["has_valid_underlying_spot_after_injection"].any())
        spot_resolved = spot_injected
        if calc_ready:
            label = "ALLOW_SYNTHETIC_IV_SOLVER_NEXT_STEP_AFTER_SPOT_INJECTION_FULL_SELECTION_BLOCKED"
        elif liquidity_ready:
            label = "ALLOW_LIQUIDITY_ONLY_RESEARCH_SCREEN_SPOT_NOT_RESOLVED"
        else:
            label = "BLOCK_SYNTHETIC_IV_SOLVER_UNDERLYING_SPOT_MISSING"
    return {
        "quotes_ready": quotes_ready,
        "liquidity_ready": liquidity_ready,
        "underlying_spot_resolved": spot_resolved,
        "underlying_spot_injected": spot_injected,
        "synthetic_iv_calculability_ready_after_spot_injection": calc_ready,
        "synthetic_greeks_calculability_ready_after_spot_injection": calc_ready,
        "synthetic_iv_calculation_allowed_next_step": calc_ready,
        "synthetic_greeks_calculation_allowed_next_step": calc_ready,
        "provider_oi_ready": False,
        "synthetic_oi_available": False,
        "full_option_candidate_generation_allowed": False,
        "liquidity_only_research_screen_allowed": liquidity_ready,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_order_allowed": False,
        "final_policy_label": label,
    }


def write_summary_and_report(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "v22_036_r1_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "V22.036_R1 Option Underlying Spot Source Resolution And Injection Audit Research Only",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"discovered_contract_row_count={summary['discovered_contract_row_count']}",
        f"underlying_count={summary['underlying_count']}",
        f"usable_spot_source_count={summary['usable_spot_source_count']}",
        f"selected_spot_source_count={summary['selected_spot_source_count']}",
        f"injected_contract_row_count={summary['injected_contract_row_count']}",
        f"valid_underlying_spot_after_injection_count={summary['valid_underlying_spot_after_injection_count']}",
        f"synthetic_iv_calculable_after_spot_injection_count={summary['synthetic_iv_calculable_after_spot_injection_count']}",
        f"synthetic_iv_calculation_allowed_next_step={summary['synthetic_iv_calculation_allowed_next_step']}",
        "full_option_candidate_generation_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_order_allowed=False",
    ]
    (output_dir / "V22.036_R1_option_underlying_spot_source_resolution_and_injection_audit_research_only_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    default_output = (repo_root / OUT_REL).resolve()
    output_dir = (output_dir or default_output).resolve()
    if output_dir != default_output and default_output not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {default_output}")
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = discover_contract_input_files(repo_root)
    selected = candidates[0] if candidates and candidates[0]["detected_contract_row_count"] else None
    frame = selected["frame"] if selected else pd.DataFrame()
    aliases = selected["aliases"] if selected else {}
    source_file = str(selected["path"]) if selected else ""
    discovery = contract_discovery_audit(candidates)
    symbols_df = resolve_underlying_symbols(frame, aliases, source_file)
    symbols = [s for s in symbols_df["normalized_underlying_symbol"].tolist() if s]
    spot_files = discover_underlying_spot_source_files(repo_root, symbols)
    sources = extract_candidate_spot_sources(spot_files, symbols)
    option_dates = option_dates_by_symbol(frame, aliases)
    alignments = audit_timestamp_alignment(sources, option_dates)
    selections = select_best_spot_source(sources, alignments, symbols) if symbols else pd.DataFrame()
    injected = inject_underlying_spot(frame, aliases, selections) if selected is not None else pd.DataFrame()
    calc = refresh_synthetic_calculability_after_injection(injected, aliases) if not injected.empty else pd.DataFrame()
    by_underlying = build_summary_by_underlying(calc, selections) if not calc.empty else pd.DataFrame()
    policy = build_safety_policy(calc)

    if selected is None:
        final_status = FAIL_INPUT_NOT_FOUND
        final_decision = BLOCKED_DECISION
    elif policy["synthetic_iv_calculation_allowed_next_step"]:
        fallback = any(selections.get("selection_status", pd.Series(dtype=str)).eq("SELECTED_WITHIN_ONE_DAY_RESEARCH_ONLY_FALLBACK")) if not selections.empty else False
        final_status = WARN_FALLBACK if fallback else PASS_READY
        final_decision = READY_DECISION
    else:
        final_status = WARN_NOT_RESOLVED
        final_decision = BLOCKED_DECISION

    summary = {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "input_v22_035_dir": str(repo_root / V22_035_R1_DIR),
        "input_v22_034_dir": str(repo_root / V22_034_R1_DIR),
        "input_v22_033_dir": str(repo_root / V22_033_R1_DIR),
        "input_v22_032_dir": str(repo_root / V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR),
        "discovered_input_file_count": len(candidates) + len(spot_files),
        "selected_contract_input_file": source_file,
        "discovered_contract_row_count": len(frame),
        "underlying_count": len(symbols),
        "resolved_underlying_symbol_count": len(symbols),
        "usable_spot_source_count": int(sources["source_status"].eq("CANDIDATE_USABLE").sum()) if not sources.empty else 0,
        "selected_spot_source_count": int(selections["selected"].sum()) if not selections.empty else 0,
        "injected_contract_row_count": int(injected["underlying_spot_injected"].sum()) if not injected.empty else 0,
        "not_injected_contract_row_count": int((~injected["underlying_spot_injected"]).sum()) if not injected.empty else 0,
        "valid_bid_ask_count": int(calc["has_valid_market_price"].sum()) if not calc.empty else 0,
        "valid_mid_count": int(calc["mid"].map(lambda x: parse_numeric(x) is not None and parse_numeric(x) > 0).sum()) if not calc.empty else 0,
        "valid_volume_count": int(calc["volume"].map(lambda x: parse_numeric(x) is not None).sum()) if not calc.empty else 0,
        "valid_contract_metadata_count": int(calc["has_valid_contract_metadata"].sum()) if not calc.empty else 0,
        "valid_dte_count": int(calc["has_valid_time_to_expiry"].sum()) if not calc.empty else 0,
        "valid_underlying_spot_after_injection_count": int(calc["has_valid_underlying_spot_after_injection"].sum()) if not calc.empty else 0,
        "synthetic_iv_calculable_after_spot_injection_count": int(calc["synthetic_iv_calculable_after_spot_injection"].sum()) if not calc.empty else 0,
        "synthetic_greeks_calculable_after_spot_injection_count": int(calc["synthetic_greeks_calculable_after_spot_injection_and_iv"].sum()) if not calc.empty else 0,
        "synthetic_iv_calculable_after_spot_injection_ratio": round(float(calc["synthetic_iv_calculable_after_spot_injection"].sum()) / len(calc), 6) if len(calc) else 0.0,
        "synthetic_greeks_calculable_after_spot_injection_ratio": round(float(calc["synthetic_greeks_calculable_after_spot_injection_and_iv"].sum()) / len(calc), 6) if len(calc) else 0.0,
        **policy,
    }

    discovery.to_csv(output_dir / "option_underlying_spot_contract_input_discovery_audit.csv", index=False, lineterminator="\n")
    symbols_df.to_csv(output_dir / "option_underlying_symbol_resolution_audit.csv", index=False, lineterminator="\n")
    sources.to_csv(output_dir / "option_underlying_spot_source_discovery_audit.csv", index=False, lineterminator="\n")
    alignments.to_csv(output_dir / "option_underlying_spot_timestamp_alignment_audit.csv", index=False, lineterminator="\n")
    selections.to_csv(output_dir / "option_underlying_spot_selection_audit.csv", index=False, lineterminator="\n")
    injected.to_csv(output_dir / "option_contract_rows_with_underlying_spot_injected_research_only.csv", index=False, lineterminator="\n")
    calc.to_csv(output_dir / "option_synthetic_calculability_after_underlying_spot_injection.csv", index=False, lineterminator="\n")
    by_underlying.to_csv(output_dir / "option_underlying_spot_injection_summary_by_underlying.csv", index=False, lineterminator="\n")
    pd.DataFrame([policy]).to_csv(output_dir / "option_underlying_spot_injection_candidate_generation_safety_policy.csv", index=False, lineterminator="\n")
    write_summary_and_report(output_dir, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="Accepted for wrapper consistency; this audit never fetches or trades.")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.output_dir)
    print(f"final_status={summary['final_status']}")
    print(f"final_decision={summary['final_decision']}")
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_036_r1_summary.json'}")
    print("full_option_candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if summary["final_status"] == FAIL_INPUT_NOT_FOUND else 0


if __name__ == "__main__":
    raise SystemExit(main())
