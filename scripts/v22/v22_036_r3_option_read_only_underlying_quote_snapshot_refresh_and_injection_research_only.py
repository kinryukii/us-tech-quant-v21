#!/usr/bin/env python
"""V22.036_R3 read-only underlying quote refresh and spot injection.

This stage may, only with --execute, connect to a Moomoo/Futu read-only quote
context to refresh the underlying quote for QQQ. It never uses trade context,
refreshes option chains or option quotes, calculates IV/Greeks, creates
candidates, or places orders.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


MODULE_ID = "V22.036_R3"
MODULE_NAME = "OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY"
STAGE = "V22.036_R3_OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_036_R2_DIR = Path("outputs") / "v22" / "V22.036_R2_OPTION_UNDERLYING_SPOT_FRESHNESS_ROOT_CAUSE_AND_SAME_SNAPSHOT_RECOVERY_AUDIT_RESEARCH_ONLY"
V22_036_R1_DIR = Path("outputs") / "v22" / "V22.036_R1_OPTION_UNDERLYING_SPOT_SOURCE_RESOLUTION_AND_INJECTION_AUDIT_RESEARCH_ONLY"
V22_035_R1_DIR = Path("outputs") / "v22" / "V22.035_R1_OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_RESEARCH_ONLY"
V22_034_R1_DIR = Path("outputs") / "v22" / "V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
V22_033_R1_DIR = Path("outputs") / "v22" / "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
V22_032_R1_AFTER_CHAIN_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_AFTER_CHAIN_DISCOVERY"
V22_032_R1_READ_ONLY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"

PASS_READY = "PASS_V22_036_R3_UNDERLYING_SPOT_REFRESHED_AND_INJECTED_FOR_SYNTHETIC_RESEARCH"
WARN_ALIGN = "WARN_V22_036_R3_UNDERLYING_SPOT_REFRESHED_WITH_ALIGNMENT_WARNING"
WARN_FAILED = "WARN_V22_036_R3_UNDERLYING_REFRESH_FAILED_SYNTHETIC_BLOCKED"
FAIL_INPUT = "FAIL_V22_036_R3_INPUT_NOT_FOUND"
FAIL_SCOPE = "FAIL_V22_036_R3_SCOPE_VIOLATION"
READY_DECISION = "OPTION_UNDERLYING_SPOT_REFRESHED_READY_FOR_SYNTHETIC_IV_SOLVER_RESEARCH_ONLY"
BLOCKED_DECISION = "OPTION_UNDERLYING_SPOT_REFRESH_FAILED_SYNTHETIC_IV_SOLVER_BLOCKED_RESEARCH_ONLY"

ALLOWED_UNDERLYINGS = ["QQQ"]
PROVIDER = "MOOMOO"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18441

ALIASES = {
    "option_code": ["option_code", "contract_symbol", "contract_code", "option_symbol", "source_option_code"],
    "underlying": ["underlying", "underlying_symbol", "underlying_code", "stock_code", "ticker", "root_symbol"],
    "expiration": ["expiration", "expiry", "expiration_date", "expire_date"],
    "strike": ["strike", "strike_price", "exercise_price"],
    "option_type": ["option_type", "call_put", "cp", "put_call", "right"],
    "bid": ["bid", "bid_raw", "bid_price", "best_bid"],
    "ask": ["ask", "ask_raw", "ask_price", "best_ask"],
    "mid": ["mid", "mid_price", "mark", "mark_price"],
    "volume": ["volume", "volume_raw", "vol", "trade_volume"],
    "valuation_date": ["valuation_date", "quote_date", "trade_date", "asof_date", "snapshot_date", "timestamp", "quote_timestamp", "enrichment_time_utc", "snapshot_time_utc"],
    "dte": ["dte", "days_to_expiry", "days_to_expiration", "time_to_expiry_days"],
}
QUOTE_ALIASES = {
    "last_price": ["last_price", "last", "cur_price", "current_price", "latest_price", "price"],
    "bid": ["bid", "bid_price", "best_bid", "bid1"],
    "ask": ["ask", "ask_price", "best_ask", "ask1"],
    "mid": ["mid", "mid_price", "mark", "mark_price"],
    "timestamp": ["quote_timestamp", "timestamp", "update_time", "updated_at", "server_time", "time"],
    "date": ["quote_date", "date", "trade_date", "asof_date"],
    "symbol": ["code", "symbol", "ticker", "stock_code"],
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
    return text


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


def parse_date_or_timestamp(value: Any) -> datetime | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    raw = str(value).strip()
    if re.fullmatch(r"\d{8}", raw):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    try:
        return pd.to_datetime(raw, utc=False).to_pydatetime()
    except (ValueError, TypeError):
        return None


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def alias(columns: list[str], names: list[str]) -> str:
    normalized = {normalize_column_name(c): c for c in columns}
    for name in names:
        key = normalize_column_name(name)
        if key in normalized:
            return normalized[key]
    return ""


def resolve_contract_aliases(columns: list[str]) -> dict[str, str]:
    return {field: alias(columns, names) for field, names in ALIASES.items()}


def discover_contract_input_files(repo_root: Path) -> list[dict[str, Any]]:
    roots = [repo_root / V22_036_R2_DIR, repo_root / V22_036_R1_DIR, repo_root / V22_035_R1_DIR, repo_root / V22_033_R1_DIR, repo_root / V22_032_R1_AFTER_CHAIN_DIR, repo_root / V22_032_R1_READ_ONLY_DIR]
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.csv")):
            try:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError):
                continue
            aliases = resolve_contract_aliases(list(frame.columns))
            flags = {f"has_{field}": bool(aliases.get(field)) for field in ["option_code", "underlying", "expiration", "strike", "option_type", "bid", "ask", "mid", "volume", "valuation_date", "dte"]}
            detected = len(frame) if all(flags[f"has_{field}"] for field in ["option_code", "underlying", "expiration", "strike", "bid", "ask"]) else 0
            score = detected + sum(int(v) for v in flags.values()) + (20 if "recovered" in path.name.lower() else 0) + (10 if "clean" in path.name.lower() else 0)
            underlyings = sorted({normalize_symbol(x) for x in frame[aliases["underlying"]].tolist() if normalize_symbol(x)}) if aliases.get("underlying") else []
            rows.append({"path": path, "frame": frame, "aliases": aliases, "score": score, "detected_contract_row_count": detected, "detected_underlying_symbols": ";".join(underlyings), **flags})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def select_contract_input(candidates: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, str], str, pd.DataFrame]:
    selected = candidates[0] if candidates and candidates[0]["detected_contract_row_count"] else None
    audit_rows = []
    for item in candidates:
        frame = item["frame"]
        audit_rows.append({
            "source_file": str(item["path"]),
            "row_count": len(frame),
            "column_count": len(frame.columns),
            "detected_contract_row_count": item["detected_contract_row_count"],
            "detected_underlying_count": len([s for s in item["detected_underlying_symbols"].split(";") if s]),
            "detected_underlying_symbols": item["detected_underlying_symbols"],
            "has_option_code": item["has_option_code"],
            "has_underlying_symbol": item["has_underlying"],
            "has_expiration": item["has_expiration"],
            "has_strike": item["has_strike"],
            "has_option_type": item["has_option_type"],
            "has_bid": item["has_bid"],
            "has_ask": item["has_ask"],
            "has_mid": item["has_mid"],
            "has_volume": item["has_volume"],
            "has_valuation_date": item["has_valuation_date"],
            "has_dte": item["has_dte"],
            "selected_for_injection": selected is not None and item["path"] == selected["path"],
            "selection_reason": "Selected highest scoring contract-level option table." if selected is not None and item["path"] == selected["path"] else "Not selected.",
        })
    if selected is None:
        return pd.DataFrame(), {}, "", pd.DataFrame(audit_rows)
    return selected["frame"], selected["aliases"], str(selected["path"]), pd.DataFrame(audit_rows)


def build_refresh_permission_gate(requested_underlying_symbol: str, quote_context_allowed: bool = True, trade_context_allowed: bool = False, option_chain_refresh_allowed: bool = False, option_quote_refresh_allowed: bool = False, iv_greeks_oi_fetch_allowed: bool = False) -> dict[str, Any]:
    normalized = normalize_symbol(requested_underlying_symbol)
    forbidden = trade_context_allowed or option_chain_refresh_allowed or option_quote_refresh_allowed or iv_greeks_oi_fetch_allowed
    if normalized not in ALLOWED_UNDERLYINGS:
        status = "FAIL_UNDERLYING_SYMBOL_NOT_ALLOWED"
    elif forbidden:
        status = "FAIL_FORBIDDEN_CONTEXT_REQUESTED"
    elif not quote_context_allowed:
        status = "FAIL_SCOPE_ESCALATION_DETECTED"
    else:
        status = "PASS_READ_ONLY_UNDERLYING_QUOTE_REFRESH_SCOPE"
    return {
        "requested_underlying_symbol": normalized,
        "allowed_underlying_symbols": ";".join(ALLOWED_UNDERLYINGS),
        "quote_context_allowed": quote_context_allowed,
        "trade_context_allowed": trade_context_allowed,
        "option_chain_refresh_allowed": option_chain_refresh_allowed,
        "option_quote_refresh_allowed": option_quote_refresh_allowed,
        "iv_greeks_oi_fetch_allowed": iv_greeks_oi_fetch_allowed,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_order_allowed": False,
        "refresh_scope_status": "READ_ONLY_UNDERLYING_ONLY" if status.startswith("PASS") else "SCOPE_BLOCKED",
        "gate_status": status,
    }


def rows_from_provider(data: Any) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        return pd.DataFrame([data])
    return pd.DataFrame()


def refresh_underlying_quote_read_only(symbol: str, execute: bool, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> tuple[pd.DataFrame, dict[str, Any]]:
    provider_symbol = f"US.{normalize_symbol(symbol)}"
    base = {
        "provider": PROVIDER,
        "requested_underlying_symbol": normalize_symbol(symbol),
        "provider_symbol_used": provider_symbol,
        "provider_call_attempted": False,
        "provider_call_succeeded": False,
        "provider_return_code": "",
        "provider_return_message": "",
        "provider_row_count": 0,
        "quote_refresh_status": "REFRESH_NOT_EXECUTED",
        "quote_refresh_error": "",
        "read_only_quote_context_used": False,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
    }
    if not execute:
        return pd.DataFrame(), base
    try:
        moomoo_module = __import__("moomoo")
    except Exception as exc:  # noqa: BLE001
        base.update({"provider_call_attempted": True, "quote_refresh_status": "PROVIDER_PACKAGE_UNAVAILABLE", "quote_refresh_error": f"{type(exc).__name__}: {exc}"})
        return pd.DataFrame(), base
    ctx = None
    try:
        ctx = getattr(moomoo_module, "OpenQuoteContext")(host=host, port=port)
        base["read_only_quote_context_used"] = True
    except Exception as exc:  # noqa: BLE001
        base.update({"provider_call_attempted": True, "quote_refresh_status": "PROVIDER_CONNECTION_FAILED", "quote_refresh_error": f"{type(exc).__name__}: {exc}"})
        return pd.DataFrame(), base
    try:
        methods = ["get_market_snapshot", "get_stock_quote"]
        last_error = ""
        for method_name in methods:
            method = getattr(ctx, method_name, None)
            if method is None:
                continue
            base["provider_call_attempted"] = True
            try:
                result = method([provider_symbol])
                ret = result[0] if isinstance(result, tuple) and len(result) >= 1 else ""
                data = result[1] if isinstance(result, tuple) and len(result) >= 2 else result
                frame = rows_from_provider(data)
                base.update({"provider_return_code": str(ret), "provider_return_message": "", "provider_row_count": len(frame)})
                if len(frame):
                    base["provider_call_succeeded"] = True
                    return frame, base
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
        base.update({"quote_refresh_status": "PROVIDER_CALL_FAILED", "quote_refresh_error": last_error or "No supported read-only quote method returned rows."})
        return pd.DataFrame(), base
    finally:
        close = getattr(ctx, "close", None)
        if callable(close):
            close()


def extract_provider_quote_fields(frame: pd.DataFrame, meta: dict[str, Any], refresh_time: datetime) -> tuple[dict[str, Any], pd.DataFrame]:
    columns = list(frame.columns)
    normalized = [normalize_column_name(c) for c in columns]
    def col(field: str) -> str:
        return alias(columns, QUOTE_ALIASES[field])
    row = frame.iloc[0] if len(frame) else pd.Series(dtype=object)
    last_col, bid_col, ask_col, mid_col, ts_col, date_col = col("last_price"), col("bid"), col("ask"), col("mid"), col("timestamp"), col("date")
    last_price = parse_numeric(row.get(last_col, "")) if last_col else None
    bid = parse_numeric(row.get(bid_col, "")) if bid_col else None
    ask = parse_numeric(row.get(ask_col, "")) if ask_col else None
    mid = parse_numeric(row.get(mid_col, "")) if mid_col else None
    if mid is None and bid is not None and ask is not None and ask >= bid and ask > 0:
        mid = round((bid + ask) / 2, 8)
    selected = last_price if last_price is not None and last_price > 0 else (mid if mid is not None and mid > 0 else "")
    timestamp_value = row.get(ts_col, "") if ts_col else row.get(date_col, "") if date_col else refresh_time.isoformat()
    dt = parse_date_or_timestamp(timestamp_value) or refresh_time
    status = "REFRESHED_UNDERLYING_QUOTE_USABLE"
    if selected == "":
        status = "REFRESHED_UNDERLYING_QUOTE_PRICE_MISSING"
    audit = {
        **{k: meta.get(k, "") for k in ["provider", "requested_underlying_symbol", "provider_symbol_used", "provider_call_attempted", "provider_call_succeeded", "provider_return_code", "provider_return_message", "provider_row_count"]},
        "raw_columns": ";".join(columns),
        "normalized_columns": ";".join(normalized),
        "candidate_last_price_column": last_col,
        "candidate_bid_column": bid_col,
        "candidate_ask_column": ask_col,
        "candidate_mid_column": mid_col,
        "candidate_timestamp_column": ts_col,
        "candidate_date_column": date_col,
        "refreshed_last_price": last_price if last_price is not None else "",
        "refreshed_bid": bid if bid is not None else "",
        "refreshed_ask": ask if ask is not None else "",
        "refreshed_mid": mid if mid is not None else "",
        "selected_refreshed_underlying_spot": selected,
        "refreshed_quote_timestamp": dt.isoformat(),
        "refreshed_quote_date": dt.date().isoformat(),
        "quote_refresh_status": meta.get("quote_refresh_status") if not len(frame) else status,
        "quote_refresh_error": meta.get("quote_refresh_error", ""),
    }
    raw = frame.copy()
    if raw.empty:
        raw = pd.DataFrame([{}])
    raw["provider"] = PROVIDER
    raw["requested_underlying_symbol"] = meta.get("requested_underlying_symbol", "")
    raw["provider_symbol_used"] = meta.get("provider_symbol_used", "")
    raw["refresh_timestamp_local"] = refresh_time.isoformat()
    raw["refresh_date_local"] = refresh_time.date().isoformat()
    raw["read_only_quote_context_used"] = meta.get("read_only_quote_context_used", False)
    raw["trade_context_used"] = False
    raw["unlock_trade_called"] = False
    raw["place_order_called"] = False
    return audit, raw


def clean_underlying_quote_snapshot(audit: dict[str, Any], refresh_time: datetime) -> dict[str, Any]:
    last_price = parse_numeric(audit.get("refreshed_last_price"))
    bid = parse_numeric(audit.get("refreshed_bid"))
    ask = parse_numeric(audit.get("refreshed_ask"))
    mid = parse_numeric(audit.get("refreshed_mid"))
    selected = ""
    field = ""
    if last_price is not None and last_price > 0:
        selected = last_price
        field = audit.get("candidate_last_price_column", "last_price")
    elif mid is not None and mid > 0:
        selected = mid
        field = audit.get("candidate_mid_column", "mid") or "bid_ask_midpoint"
    elif bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid:
        selected = round((bid + ask) / 2, 8)
        field = "bid_ask_midpoint"
    price_valid = selected != ""
    timestamp_valid = bool(parse_date_or_timestamp(audit.get("refreshed_quote_timestamp")))
    if price_valid and timestamp_valid:
        status = "CLEAN_UNDERLYING_SPOT_READY"
    elif price_valid:
        status = "CLEAN_UNDERLYING_SPOT_TIMESTAMP_MISSING_WARN"
    elif audit.get("quote_refresh_status", "").startswith("REFRESHED"):
        status = "CLEAN_UNDERLYING_SPOT_INVALID"
    else:
        status = "CLEAN_UNDERLYING_SPOT_REFRESH_FAILED"
    return {
        "provider": PROVIDER,
        "requested_underlying_symbol": audit.get("requested_underlying_symbol", ""),
        "normalized_underlying_symbol": normalize_symbol(audit.get("requested_underlying_symbol", "")),
        "selected_underlying_spot": selected,
        "selected_price_source_field": field,
        "last_price": last_price if last_price is not None else "",
        "bid": bid if bid is not None else "",
        "ask": ask if ask is not None else "",
        "mid": mid if mid is not None else "",
        "quote_timestamp": audit.get("refreshed_quote_timestamp", ""),
        "quote_date": audit.get("refreshed_quote_date", ""),
        "refresh_timestamp_local": refresh_time.isoformat(),
        "refresh_date_local": refresh_time.date().isoformat(),
        "price_valid": price_valid,
        "timestamp_valid": timestamp_valid,
        "quote_snapshot_status": status,
    }


def option_reference(frame: pd.DataFrame, aliases: dict[str, str]) -> tuple[str, str]:
    if frame.empty or not aliases.get("valuation_date"):
        return "", ""
    timestamps = frame[aliases["valuation_date"]].map(parse_date_or_timestamp).dropna()
    latest = max(timestamps) if len(timestamps) else None
    return latest.date().isoformat() if latest else "", latest.isoformat() if latest else ""


def audit_timestamp_alignment(symbol: str, frame: pd.DataFrame, aliases: dict[str, str], clean: dict[str, Any]) -> dict[str, Any]:
    option_date, option_ts = option_reference(frame, aliases)
    refresh_date = clean.get("quote_date", "")
    opt_dt = parse_date_or_timestamp(option_date)
    ref_dt = parse_date_or_timestamp(refresh_date)
    if not opt_dt:
        status, diff = "MISSING_OPTION_VALUATION_DATE", ""
    elif not ref_dt:
        status, diff = "MISSING_REFRESHED_QUOTE_DATE", ""
    else:
        diff_int = abs((ref_dt.date() - opt_dt.date()).days)
        diff = diff_int
        if diff_int == 0:
            status = "REFRESHED_AFTER_OPTION_SNAPSHOT_RESEARCH_ONLY" if clean.get("quote_timestamp") and option_ts and str(clean["quote_timestamp"]) >= option_ts else "SAME_DATE_ALIGNED"
        elif diff_int <= 1:
            status = "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY"
        else:
            status = "STALE_OR_MISMATCHED_REFRESH_REJECTED"
    return {
        "underlying_symbol": symbol,
        "option_valuation_date": option_date,
        "option_quote_timestamp": option_ts,
        "refreshed_underlying_quote_date": refresh_date,
        "refreshed_underlying_quote_timestamp": clean.get("quote_timestamp", ""),
        "refresh_timestamp_local": clean.get("refresh_timestamp_local", ""),
        "date_diff_days": diff,
        "same_date": diff == 0,
        "timestamp_available": bool(option_ts and clean.get("quote_timestamp")),
        "alignment_status": status,
        "alignment_policy_reason": "Same-date read-only underlying refresh accepted for research; one-day alignment warns; older dates rejected.",
    }


def val(row: Any, aliases: dict[str, str], field: str) -> Any:
    col = aliases.get(field, "")
    return row.get(col, "") if col else ""


def inject_refreshed_underlying_spot(frame: pd.DataFrame, aliases: dict[str, str], clean: dict[str, Any], alignment: dict[str, Any]) -> pd.DataFrame:
    output = frame.copy()
    status = alignment["alignment_status"]
    price = clean.get("selected_underlying_spot", "")
    can_inject = bool(clean.get("price_valid")) and status in {"SAME_DATE_ALIGNED", "REFRESHED_AFTER_OPTION_SNAPSHOT_RESEARCH_ONLY", "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY"}
    if can_inject:
        inj_status = "INJECTED_REFRESHED_WITHIN_ONE_DAY_RESEARCH_ONLY" if status == "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY" else ("INJECTED_REFRESHED_AFTER_OPTION_SNAPSHOT_RESEARCH_ONLY" if status == "REFRESHED_AFTER_OPTION_SNAPSHOT_RESEARCH_ONLY" else "INJECTED_REFRESHED_SAME_DATE_SPOT")
    elif not clean.get("price_valid"):
        inj_status = "NOT_INJECTED_PRICE_INVALID"
    elif status == "STALE_OR_MISMATCHED_REFRESH_REJECTED":
        inj_status = "NOT_INJECTED_STALE_OR_MISMATCHED"
    else:
        inj_status = "NOT_INJECTED_REFRESH_FAILED"
    output["refreshed_underlying_symbol"] = clean.get("normalized_underlying_symbol", "")
    output["refreshed_underlying_spot"] = price if can_inject else ""
    output["refreshed_underlying_spot_source_provider"] = PROVIDER
    output["refreshed_underlying_spot_source_file"] = "underlying_quote_snapshot_clean_research_only.csv"
    output["refreshed_underlying_spot_price_field"] = clean.get("selected_price_source_field", "")
    output["refreshed_underlying_spot_quote_date"] = clean.get("quote_date", "")
    output["refreshed_underlying_spot_quote_timestamp"] = clean.get("quote_timestamp", "")
    output["refreshed_underlying_spot_refresh_timestamp_local"] = clean.get("refresh_timestamp_local", "")
    output["refreshed_underlying_spot_alignment_status"] = status
    output["refreshed_underlying_spot_injected"] = can_inject
    output["refreshed_underlying_spot_injection_status"] = inj_status
    return output


def dte(row: Any, aliases: dict[str, str]) -> float | None:
    source = parse_numeric(val(row, aliases, "dte"))
    if source is not None:
        return source if source > 0 else None
    exp = parse_date_or_timestamp(val(row, aliases, "expiration"))
    vd = parse_date_or_timestamp(val(row, aliases, "valuation_date"))
    if not exp or not vd:
        return None
    diff = (exp.date() - vd.date()).days
    return float(diff) if diff > 0 else None


def refresh_synthetic_calculability_after_injection(injected: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, row in injected.iterrows():
        bid, ask, mid = parse_numeric(val(row, aliases, "bid")), parse_numeric(val(row, aliases, "ask")), parse_numeric(val(row, aliases, "mid"))
        market = bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid and mid is not None and mid > 0
        meta = bool(parse_numeric(val(row, aliases, "strike")) and parse_date_or_timestamp(val(row, aliases, "expiration")) and str(val(row, aliases, "option_type")).upper() in {"CALL", "PUT", "C", "P"})
        time_ok = dte(row, aliases) is not None
        spot = parse_numeric(row.get("refreshed_underlying_spot", ""))
        spot_ok = spot is not None and spot > 0
        identity = bool(str(val(row, aliases, "option_code")).strip() and row.get("refreshed_underlying_symbol", ""))
        calc = identity and market and meta and time_ok and spot_ok
        missing = [name for name, ok in [("market_price", market), ("contract_metadata", meta), ("time_to_expiry", time_ok), ("underlying_spot", spot_ok)] if not ok]
        status = "SYNTHETIC_IV_GREEKS_CALCULABLE_AFTER_REFRESHED_SPOT_INJECTION_RESEARCH_ONLY" if calc else ("MISSING_UNDERLYING_SPOT_AFTER_REFRESH" if not spot_ok else "UNKNOWN_INPUT_NOT_FOUND")
        rows.append({"option_code": val(row, aliases, "option_code"), "underlying_symbol": row.get("refreshed_underlying_symbol", ""), "expiration": val(row, aliases, "expiration"), "strike": val(row, aliases, "strike"), "option_type": val(row, aliases, "option_type"), "bid": val(row, aliases, "bid"), "ask": val(row, aliases, "ask"), "mid": val(row, aliases, "mid"), "volume": val(row, aliases, "volume"), "valuation_date": val(row, aliases, "valuation_date"), "dte": dte(row, aliases) or "", "refreshed_underlying_spot": row.get("refreshed_underlying_spot", ""), "has_contract_identity": identity, "has_valid_market_price": market, "has_valid_contract_metadata": meta, "has_valid_underlying_spot_after_refresh": spot_ok, "has_valid_time_to_expiry": time_ok, "has_model_assumption_inputs": True, "synthetic_iv_calculable_after_refreshed_spot_injection": calc, "synthetic_greeks_calculable_after_refreshed_spot_injection_and_iv": calc, "missing_required_fields_after_refresh": ";".join(missing), "calculability_status_after_refresh": status})
    return pd.DataFrame(rows)


def build_safety_policy(calc: pd.DataFrame) -> dict[str, Any]:
    if calc.empty:
        quotes = liquidity = spot = solver = False
    else:
        quotes = bool(calc["has_valid_market_price"].any())
        liquidity = bool((calc["has_valid_market_price"] & calc["volume"].map(lambda x: parse_numeric(x) is not None)).any())
        spot = bool(calc["has_valid_underlying_spot_after_refresh"].any())
        solver = bool(calc["synthetic_iv_calculable_after_refreshed_spot_injection"].any())
    if solver:
        label = "ALLOW_SYNTHETIC_IV_SOLVER_NEXT_STEP_AFTER_READ_ONLY_UNDERLYING_REFRESH_FULL_SELECTION_BLOCKED"
    elif spot:
        label = "REFRESHED_UNDERLYING_SPOT_AVAILABLE_BUT_SYNTHETIC_INPUTS_INCOMPLETE"
    elif not calc.empty:
        label = "BLOCK_SYNTHETIC_IV_SOLVER_UNDERLYING_REFRESH_FAILED"
    else:
        label = "FAIL_INPUT_NOT_FOUND"
    return {"quotes_ready": quotes, "liquidity_ready": liquidity, "refreshed_underlying_spot_ready": spot, "refreshed_underlying_spot_injected": spot, "synthetic_iv_calculability_ready_after_refresh": solver, "synthetic_greeks_calculability_ready_after_refresh": solver, "synthetic_iv_solver_next_step_allowed": solver, "synthetic_greeks_calculation_next_step_allowed": solver, "provider_oi_ready": False, "synthetic_oi_available": False, "full_option_candidate_generation_allowed": False, "liquidity_only_research_screen_allowed": liquidity, "broker_action_allowed": False, "official_adoption_allowed": False, "trade_order_allowed": False, "final_policy_label": label}


def summary_by_underlying(calc: pd.DataFrame, clean: dict[str, Any], alignment: dict[str, Any]) -> pd.DataFrame:
    if calc.empty:
        return pd.DataFrame()
    rows = []
    for symbol, group in calc.groupby("underlying_symbol", dropna=False):
        total = len(group)
        iv_count = int(group["synthetic_iv_calculable_after_refreshed_spot_injection"].sum())
        greek_count = int(group["synthetic_greeks_calculable_after_refreshed_spot_injection_and_iv"].sum())
        rows.append({"underlying_symbol": symbol, "total_contract_count": total, "selected_refreshed_underlying_spot": clean.get("selected_underlying_spot", ""), "refreshed_quote_date": clean.get("quote_date", ""), "refreshed_quote_timestamp": clean.get("quote_timestamp", ""), "alignment_status": alignment.get("alignment_status", ""), "injected_contract_count": int(group["has_valid_underlying_spot_after_refresh"].sum()), "not_injected_contract_count": total - int(group["has_valid_underlying_spot_after_refresh"].sum()), "valid_bid_ask_count": int(group["has_valid_market_price"].sum()), "valid_mid_count": int(group["mid"].map(lambda x: parse_numeric(x) is not None and parse_numeric(x) > 0).sum()), "valid_volume_count": int(group["volume"].map(lambda x: parse_numeric(x) is not None).sum()), "valid_contract_metadata_count": int(group["has_valid_contract_metadata"].sum()), "valid_dte_count": int(group["has_valid_time_to_expiry"].sum()), "synthetic_iv_calculable_after_refreshed_spot_injection_count": iv_count, "synthetic_greeks_calculable_after_refreshed_spot_injection_count": greek_count, "synthetic_iv_calculable_after_refreshed_spot_injection_ratio": round(iv_count / total, 6), "synthetic_greeks_calculable_after_refreshed_spot_injection_ratio": round(greek_count / total, 6)})
    return pd.DataFrame(rows)


def write_summary_and_report(output_dir: Path, summary: dict[str, Any]) -> None:
    (output_dir / "v22_036_r3_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    keys = ["final_status", "final_decision", "requested_underlying_symbol", "provider_call_attempted", "provider_call_succeeded", "quote_refresh_status", "selected_refreshed_underlying_spot", "refreshed_quote_date", "refreshed_quote_timestamp", "discovered_contract_row_count", "injected_contract_row_count", "valid_underlying_spot_after_refresh_count", "synthetic_iv_calculable_after_refreshed_spot_injection_count", "synthetic_iv_solver_next_step_allowed", "full_option_candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed", "trade_order_allowed"]
    lines = ["V22.036_R3 Option Read-Only Underlying Quote Snapshot Refresh And Injection Research Only"] + [f"{k}={summary[k]}" for k in keys]
    (output_dir / "V22.036_R3_option_read_only_underlying_quote_snapshot_refresh_and_injection_research_only_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path, output_dir: Path | None = None, execute: bool = False, requested_underlying_symbol: str = "QQQ") -> dict[str, Any]:
    repo_root = repo_root.resolve()
    default = (repo_root / OUT_REL).resolve()
    output_dir = (output_dir or default).resolve()
    if output_dir != default and default not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {default}")
    output_dir.mkdir(parents=True, exist_ok=True)
    gate = build_refresh_permission_gate(requested_underlying_symbol)
    gates = pd.DataFrame([gate])
    candidates = discover_contract_input_files(repo_root)
    contracts, aliases, contract_file, discovery = select_contract_input(candidates)
    refresh_time = now_local()
    if gate["gate_status"] != "PASS_READ_ONLY_UNDERLYING_QUOTE_REFRESH_SCOPE":
        provider_frame, provider_meta = pd.DataFrame(), {"provider": PROVIDER, "requested_underlying_symbol": normalize_symbol(requested_underlying_symbol), "provider_symbol_used": "", "provider_call_attempted": False, "provider_call_succeeded": False, "provider_return_code": "", "provider_return_message": "", "provider_row_count": 0, "quote_refresh_status": "REFRESH_NOT_EXECUTED", "quote_refresh_error": gate["gate_status"], "read_only_quote_context_used": False, "trade_context_used": False, "unlock_trade_called": False, "place_order_called": False}
    else:
        provider_frame, provider_meta = refresh_underlying_quote_read_only(requested_underlying_symbol, execute)
    live_audit, raw_artifact = extract_provider_quote_fields(provider_frame, provider_meta, refresh_time)
    clean = clean_underlying_quote_snapshot(live_audit, refresh_time)
    symbol = normalize_symbol(requested_underlying_symbol)
    alignment = audit_timestamp_alignment(symbol, contracts, aliases, clean) if not contracts.empty else {"alignment_status": "UNKNOWN_ALIGNMENT", "date_diff_days": "", "same_date": False, "timestamp_available": False, "underlying_symbol": symbol, "option_valuation_date": "", "option_quote_timestamp": "", "refreshed_underlying_quote_date": clean.get("quote_date", ""), "refreshed_underlying_quote_timestamp": clean.get("quote_timestamp", ""), "refresh_timestamp_local": clean.get("refresh_timestamp_local", ""), "alignment_policy_reason": "No contract input."}
    injected = inject_refreshed_underlying_spot(contracts, aliases, clean, alignment) if not contracts.empty else pd.DataFrame()
    calc = refresh_synthetic_calculability_after_injection(injected, aliases) if not injected.empty else pd.DataFrame()
    policy = build_safety_policy(calc)
    by_underlying = summary_by_underlying(calc, clean, alignment)
    if gate["gate_status"] != "PASS_READ_ONLY_UNDERLYING_QUOTE_REFRESH_SCOPE":
        final_status, final_decision = FAIL_SCOPE, BLOCKED_DECISION
    elif contracts.empty:
        final_status, final_decision = FAIL_INPUT, BLOCKED_DECISION
    elif policy["synthetic_iv_solver_next_step_allowed"]:
        final_status = WARN_ALIGN if alignment["alignment_status"] == "DATE_WITHIN_ONE_DAY_ACCEPTED_RESEARCH_ONLY" else PASS_READY
        final_decision = READY_DECISION
    else:
        final_status, final_decision = WARN_FAILED, BLOCKED_DECISION
    discovered_files = sum(1 for root in [repo_root / V22_036_R2_DIR, repo_root / V22_036_R1_DIR, repo_root / V22_035_R1_DIR, repo_root / V22_034_R1_DIR, repo_root / V22_033_R1_DIR, repo_root / V22_032_R1_AFTER_CHAIN_DIR, repo_root / V22_032_R1_READ_ONLY_DIR] if root.exists() for _ in root.glob("*"))
    summary = {"module_id": MODULE_ID, "module_name": MODULE_NAME, "final_status": final_status, "final_decision": final_decision, "input_v22_036_r2_dir": str(repo_root / V22_036_R2_DIR), "input_v22_036_r1_dir": str(repo_root / V22_036_R1_DIR), "input_v22_035_dir": str(repo_root / V22_035_R1_DIR), "input_v22_034_dir": str(repo_root / V22_034_R1_DIR), "input_v22_033_dir": str(repo_root / V22_033_R1_DIR), "input_v22_032_dir": str(repo_root / V22_032_R1_AFTER_CHAIN_DIR), "discovered_input_file_count": discovered_files, "selected_contract_input_file": contract_file, "discovered_contract_row_count": len(contracts), "underlying_count": int(contracts[aliases["underlying"]].map(normalize_symbol).nunique()) if not contracts.empty and aliases.get("underlying") else 0, "requested_underlying_symbol": symbol, "provider": PROVIDER, "provider_call_attempted": bool(live_audit.get("provider_call_attempted")), "provider_call_succeeded": bool(live_audit.get("provider_call_succeeded")), "provider_return_code": live_audit.get("provider_return_code", ""), "quote_refresh_status": live_audit.get("quote_refresh_status", ""), "selected_refreshed_underlying_spot": clean.get("selected_underlying_spot", ""), "refreshed_quote_date": clean.get("quote_date", ""), "refreshed_quote_timestamp": clean.get("quote_timestamp", ""), "injected_contract_row_count": int(injected["refreshed_underlying_spot_injected"].sum()) if not injected.empty else 0, "not_injected_contract_row_count": int((~injected["refreshed_underlying_spot_injected"]).sum()) if not injected.empty else 0, "valid_underlying_spot_after_refresh_count": int(calc["has_valid_underlying_spot_after_refresh"].sum()) if not calc.empty else 0, "valid_bid_ask_count": int(calc["has_valid_market_price"].sum()) if not calc.empty else 0, "valid_mid_count": int(calc["mid"].map(lambda x: parse_numeric(x) is not None and parse_numeric(x) > 0).sum()) if not calc.empty else 0, "valid_volume_count": int(calc["volume"].map(lambda x: parse_numeric(x) is not None).sum()) if not calc.empty else 0, "valid_contract_metadata_count": int(calc["has_valid_contract_metadata"].sum()) if not calc.empty else 0, "valid_dte_count": int(calc["has_valid_time_to_expiry"].sum()) if not calc.empty else 0, "synthetic_iv_calculable_after_refreshed_spot_injection_count": int(calc["synthetic_iv_calculable_after_refreshed_spot_injection"].sum()) if not calc.empty else 0, "synthetic_greeks_calculable_after_refreshed_spot_injection_count": int(calc["synthetic_greeks_calculable_after_refreshed_spot_injection_and_iv"].sum()) if not calc.empty else 0, "synthetic_iv_calculable_after_refreshed_spot_injection_ratio": round(float(calc["synthetic_iv_calculable_after_refreshed_spot_injection"].sum()) / len(calc), 6) if len(calc) else 0.0, "synthetic_greeks_calculable_after_refreshed_spot_injection_ratio": round(float(calc["synthetic_greeks_calculable_after_refreshed_spot_injection_and_iv"].sum()) / len(calc), 6) if len(calc) else 0.0, "read_only_quote_context_used": bool(provider_meta.get("read_only_quote_context_used", False)), "trade_context_used": False, "unlock_trade_called": False, "place_order_called": False, **policy}
    gates.to_csv(output_dir / "option_underlying_quote_refresh_permission_gate_audit.csv", index=False, lineterminator="\n")
    discovery.to_csv(output_dir / "option_underlying_quote_refresh_contract_input_discovery_audit.csv", index=False, lineterminator="\n")
    pd.DataFrame([live_audit]).to_csv(output_dir / "option_underlying_quote_refresh_live_audit.csv", index=False, lineterminator="\n")
    raw_artifact.to_csv(output_dir / "underlying_quote_snapshot_raw_moomoo_read_only.csv", index=False, lineterminator="\n")
    pd.DataFrame([clean]).to_csv(output_dir / "underlying_quote_snapshot_clean_research_only.csv", index=False, lineterminator="\n")
    pd.DataFrame([alignment]).to_csv(output_dir / "option_underlying_quote_refresh_timestamp_alignment_audit.csv", index=False, lineterminator="\n")
    injected.to_csv(output_dir / "option_contract_rows_with_refreshed_underlying_spot_injected_research_only.csv", index=False, lineterminator="\n")
    calc.to_csv(output_dir / "option_synthetic_calculability_after_refreshed_spot_injection.csv", index=False, lineterminator="\n")
    by_underlying.to_csv(output_dir / "option_underlying_quote_refresh_injection_summary_by_underlying.csv", index=False, lineterminator="\n")
    pd.DataFrame([policy]).to_csv(output_dir / "option_underlying_quote_refresh_candidate_generation_safety_policy.csv", index=False, lineterminator="\n")
    write_summary_and_report(output_dir, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--underlying", default="QQQ")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.output_dir, args.execute, args.underlying)
    print(f"final_status={summary['final_status']}")
    print(f"final_decision={summary['final_decision']}")
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_036_r3_summary.json'}")
    print("full_option_candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if summary["final_status"] in {FAIL_INPUT, FAIL_SCOPE} else 0


if __name__ == "__main__":
    raise SystemExit(main())
