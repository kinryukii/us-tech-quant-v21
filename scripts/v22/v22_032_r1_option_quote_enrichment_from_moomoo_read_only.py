#!/usr/bin/env python
"""V22.032_R1 option quote enrichment from Moomoo read-only.

Default mode is SAFE_DRY_RUN and does not import Moomoo/Futu, connect to
OpenD, or fetch data. Execute mode may use a read-only quote context to enrich
existing V22.032 option_code rows. This module never uses a trade context,
unlocks trading, places or changes orders, mutates V21/cache, or generates
trade candidates/recommendations.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ID = "V22.032_R1"
MODULE_NAME = "OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"
STAGE = "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_032_DIR = Path("outputs") / "v22" / "V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT"
SOURCE_CLEAN_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_snapshot_clean.csv"
SOURCE_SUMMARY_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_snapshot_summary.json"
V22_033_SUMMARY_INPUT = Path("outputs") / "v22" / "V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT" / "v22_option_chain_liquidity_coverage_summary.json"
CONTRACT_INPUT = Path("outputs") / "v22" / "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY" / "v22_etf_option_contract_spec_registry.csv"
UNIVERSE_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_registry.csv"

PASS_READY = "PASS_V22_032_R1_OPTION_QUOTE_ENRICHMENT_READY"
PASS_DRY_RUN = "PASS_V22_032_R1_DRY_RUN_SCHEMA_READY"
WARN_STILL_MISSING = "WARN_V22_032_R1_QUOTE_ENRICHMENT_COMPLETED_BUT_QUOTES_STILL_MISSING"
WARN_PARTIAL = "WARN_V22_032_R1_QUOTE_ENRICHMENT_PARTIAL"
WARN_FETCH_FAILED = "WARN_V22_032_R1_MOOMOO_CONNECTION_OR_QUOTE_FETCH_FAILED_READ_ONLY"
FAIL_MISSING_INPUTS = "FAIL_V22_032_R1_MISSING_REQUIRED_INPUTS"
READY_DECISION = "OPTION_QUOTE_ENRICHMENT_READY_FOR_LIQUIDITY_AUDIT_RESEARCH_ONLY"
FAIL_DECISION = "OPTION_QUOTE_ENRICHMENT_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT",
    "V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA",
    "V22.040_LONG_CALL_PUT_CANDIDATE_GENERATOR",
]

RAW_FIELDNAMES = [
    "enrichment_time_utc",
    "source_option_code",
    "underlying",
    "universe_group",
    "universe_tier",
    "theme_bucket",
    "leveraged_flag",
    "inverse_flag",
    "leverage_multiple",
    "expiration",
    "dte",
    "strike",
    "call_put",
    "option_code",
    "option_name",
    "bid_raw",
    "ask_raw",
    "last_raw",
    "volume_raw",
    "open_interest_raw",
    "implied_volatility_raw",
    "delta_raw",
    "gamma_raw",
    "theta_raw",
    "vega_raw",
    "rho_raw",
    "underlying_price_raw",
    "exchange_raw",
    "data_vendor",
    "raw_status",
    "raw_error",
    "reason",
]

CLEAN_FIELDNAMES = [
    "enrichment_time_utc",
    "underlying",
    "universe_group",
    "universe_tier",
    "theme_bucket",
    "leveraged_flag",
    "inverse_flag",
    "leverage_multiple",
    "expiration",
    "dte",
    "strike",
    "call_put",
    "option_code",
    "option_name",
    "bid",
    "ask",
    "mid",
    "last",
    "volume",
    "open_interest",
    "implied_volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
    "rho",
    "underlying_price",
    "moneyness",
    "spread_abs",
    "spread_pct",
    "contract_size",
    "exchange",
    "data_vendor",
    "quote_status",
    "clean_status",
    "reason",
]

UNDERLYING_AUDIT_FIELDNAMES = [
    "underlying",
    "target_contract_count",
    "attempted_contract_count",
    "enriched_raw_row_count",
    "enriched_clean_row_count",
    "valid_bid_ask_count",
    "valid_mid_count",
    "valid_spread_pct_count",
    "valid_iv_count",
    "valid_greeks_count",
    "valid_delta_count",
    "valid_gamma_count",
    "valid_theta_count",
    "valid_vega_count",
    "valid_volume_count",
    "valid_open_interest_count",
    "quote_enrichment_status",
    "ready_for_liquidity_audit",
    "ready_for_candidate_generation",
    "primary_blocker",
    "secondary_blockers",
    "reason",
]

FETCH_AUDIT_FIELDNAMES = [
    "event_time_utc",
    "mode",
    "host",
    "port",
    "batch_id",
    "underlying",
    "attempted_contract_count",
    "moomoo_import_attempted",
    "moomoo_import_status",
    "moomoo_connection_attempted",
    "moomoo_connection_status",
    "quote_enrichment_attempted",
    "api_method_attempted",
    "fetch_status",
    "error_type",
    "error_message",
    "row_count",
    "note",
]

FIELD_COVERAGE_FIELDNAMES = [
    "field_name",
    "raw_non_null_count",
    "clean_non_null_count",
    "raw_coverage_ratio",
    "clean_coverage_ratio",
    "required_for_candidate_generation",
    "required_for_liquidity_audit",
    "required_for_greeks_audit",
    "field_status",
    "reason",
]

REQUIRED_FOR_CANDIDATE = {
    "underlying",
    "expiration",
    "dte",
    "strike",
    "call_put",
    "option_code",
    "bid",
    "ask",
    "mid",
    "spread_pct",
    "volume",
    "open_interest",
    "implied_volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
}
LIQUIDITY_FIELDS = {"bid", "ask", "mid", "spread_pct", "volume", "open_interest"}
GREEKS_FIELDS = {"implied_volatility", "delta", "gamma", "theta", "vega", "rho"}


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.032_R1 output directory must be {expected}, got {output_dir.resolve()}")


def required_flags(repo_root: Path) -> dict[str, bool]:
    return {
        "v22_032_clean_input_exists": (repo_root / SOURCE_CLEAN_INPUT).exists(),
        "v22_032_summary_input_exists": (repo_root / SOURCE_SUMMARY_INPUT).exists(),
        "v22_033_summary_input_exists": (repo_root / V22_033_SUMMARY_INPUT).exists(),
        "v22_030_universe_input_exists": (repo_root / UNIVERSE_INPUT).exists(),
        "v22_031_contract_input_exists": (repo_root / CONTRACT_INPUT).exists(),
    }


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def unique_targets(source_rows: list[dict[str, str]], max_contracts: int, underlying_filter: str | None) -> list[dict[str, str]]:
    allowed = {item.strip().upper() for item in underlying_filter.split(",") if item.strip()} if underlying_filter else None
    seen: set[str] = set()
    targets: list[dict[str, str]] = []
    for row in source_rows:
        code = row.get("option_code", "").strip()
        underlying = row.get("underlying", "").strip().upper()
        if not code or code in seen:
            continue
        if allowed is not None and underlying not in allowed:
            continue
        seen.add(code)
        targets.append(row)
        if len(targets) >= max_contracts:
            break
    return targets


def chunks(rows: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    safe_size = max(1, size)
    return [rows[index : index + safe_size] for index in range(0, len(rows), safe_size)]


def value_from(raw: dict[str, Any], names: list[str]) -> Any:
    lower = {str(key).lower(): value for key, value in raw.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return ""


def raw_row_from_quote(source: dict[str, str], quote: dict[str, Any], enrichment_time: str, status: str, error: str = "") -> dict[str, Any]:
    return {
        "enrichment_time_utc": enrichment_time,
        "source_option_code": source.get("option_code", ""),
        "underlying": source.get("underlying", ""),
        "universe_group": source.get("universe_group", ""),
        "universe_tier": source.get("universe_tier", ""),
        "theme_bucket": source.get("theme_bucket", ""),
        "leveraged_flag": source.get("leveraged_flag", ""),
        "inverse_flag": source.get("inverse_flag", ""),
        "leverage_multiple": source.get("leverage_multiple", ""),
        "expiration": source.get("expiration", ""),
        "dte": source.get("dte", ""),
        "strike": source.get("strike", ""),
        "call_put": source.get("call_put", ""),
        "option_code": source.get("option_code", ""),
        "option_name": source.get("option_name", ""),
        "bid_raw": value_from(quote, ["bid", "bid_price", "bid1", "bid_price_1"]),
        "ask_raw": value_from(quote, ["ask", "ask_price", "ask1", "ask_price_1"]),
        "last_raw": value_from(quote, ["last", "last_price", "cur_price"]),
        "volume_raw": value_from(quote, ["volume", "vol"]),
        "open_interest_raw": value_from(quote, ["open_interest", "open_int"]),
        "implied_volatility_raw": value_from(quote, ["implied_volatility", "iv", "implied_vol"]),
        "delta_raw": value_from(quote, ["delta"]),
        "gamma_raw": value_from(quote, ["gamma"]),
        "theta_raw": value_from(quote, ["theta"]),
        "vega_raw": value_from(quote, ["vega"]),
        "rho_raw": value_from(quote, ["rho"]),
        "underlying_price_raw": value_from(quote, ["underlying_price", "stock_price", "underlying_last"]),
        "exchange_raw": value_from(quote, ["exchange", "market"]),
        "data_vendor": "MOOMOO_OPEND",
        "raw_status": status,
        "raw_error": error,
        "reason": "Read-only quote enrichment row; last price is non-tradable.",
    }


def clean_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    bid = numeric(raw.get("bid_raw"))
    ask = numeric(raw.get("ask_raw"))
    strike = numeric(raw.get("strike"))
    underlying_price = numeric(raw.get("underlying_price_raw"))
    mid: float | str = ""
    spread_abs: float | str = ""
    spread_pct: float | str = ""
    if bid is not None and ask is not None and ask >= bid:
        mid = round((bid + ask) / 2, 6)
        spread_abs = round(ask - bid, 6)
        spread_pct = round((ask - bid) / mid, 6) if mid else ""
    moneyness: float | str = ""
    if strike is not None and underlying_price is not None and underlying_price > 0:
        moneyness = round(strike / underlying_price, 6)
    clean_status = "QUOTE_ENRICHED_WITH_VALID_BID_ASK" if mid != "" else "QUOTE_FIELDS_MISSING_OR_INCOMPLETE"
    return {
        "enrichment_time_utc": raw.get("enrichment_time_utc", ""),
        "underlying": raw.get("underlying", ""),
        "universe_group": raw.get("universe_group", ""),
        "universe_tier": raw.get("universe_tier", ""),
        "theme_bucket": raw.get("theme_bucket", ""),
        "leveraged_flag": raw.get("leveraged_flag", ""),
        "inverse_flag": raw.get("inverse_flag", ""),
        "leverage_multiple": raw.get("leverage_multiple", ""),
        "expiration": raw.get("expiration", ""),
        "dte": raw.get("dte", ""),
        "strike": raw.get("strike", ""),
        "call_put": raw.get("call_put", ""),
        "option_code": raw.get("option_code", ""),
        "option_name": raw.get("option_name", ""),
        "bid": raw.get("bid_raw", ""),
        "ask": raw.get("ask_raw", ""),
        "mid": mid,
        "last": raw.get("last_raw", ""),
        "volume": raw.get("volume_raw", ""),
        "open_interest": raw.get("open_interest_raw", ""),
        "implied_volatility": raw.get("implied_volatility_raw", ""),
        "delta": raw.get("delta_raw", ""),
        "gamma": raw.get("gamma_raw", ""),
        "theta": raw.get("theta_raw", ""),
        "vega": raw.get("vega_raw", ""),
        "rho": raw.get("rho_raw", ""),
        "underlying_price": raw.get("underlying_price_raw", ""),
        "moneyness": moneyness,
        "spread_abs": spread_abs,
        "spread_pct": spread_pct,
        "contract_size": "100",
        "exchange": raw.get("exchange_raw", ""),
        "data_vendor": raw.get("data_vendor", ""),
        "quote_status": raw.get("raw_status", ""),
        "clean_status": clean_status,
        "reason": "Mid/spread computed only from valid bid and ask; last price is non-tradable.",
    }


def rows_from_vendor(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict("records")
            if isinstance(records, list):
                return [dict(row) for row in records if isinstance(row, dict)]
        except TypeError:
            return []
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ["data", "rows", "snapshot"]:
            if isinstance(value.get(key), list):
                return [dict(row) for row in value[key] if isinstance(row, dict)]
    return []


def fetch_event(mode: str, host: str, port: int, batch_id: int, underlying: str, attempted: int, import_attempted: bool, import_status: str, connection_attempted: bool, connection_status: str, quote_attempted: bool, method: str, status: str, error_type: str, error_message: str, row_count: int, note: str) -> dict[str, Any]:
    return {
        "event_time_utc": utc_now_text(),
        "mode": mode,
        "host": host,
        "port": port,
        "batch_id": batch_id,
        "underlying": underlying,
        "attempted_contract_count": attempted,
        "moomoo_import_attempted": import_attempted,
        "moomoo_import_status": import_status,
        "moomoo_connection_attempted": connection_attempted,
        "moomoo_connection_status": connection_status,
        "quote_enrichment_attempted": quote_attempted,
        "api_method_attempted": method,
        "fetch_status": status,
        "error_type": error_type,
        "error_message": error_message,
        "row_count": row_count,
        "note": note,
    }


def dry_run_fetch_audit(targets: list[dict[str, str]], host: str, port: int, batch_size: int) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    for batch_id, batch in enumerate(chunks(targets, batch_size), start=1):
        underlyings = ",".join(sorted({row.get("underlying", "") for row in batch}))
        audit.append(fetch_event("DRY_RUN", host, port, batch_id, underlyings, len(batch), False, "NOT_ATTEMPTED_DRY_RUN", False, "NOT_ATTEMPTED_DRY_RUN", False, "", "DRY_RUN_NOT_FETCHED", "", "", 0, "Dry run creates schemas only."))
    return audit


def execute_enrichment(targets: list[dict[str, str]], host: str, port: int, batch_size: int, enrichment_time: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool]]:
    raw_rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    flags = {
        "moomoo_import_attempted": True,
        "moomoo_import_succeeded": False,
        "moomoo_connection_attempted": False,
        "moomoo_connection_succeeded": False,
        "quote_enrichment_attempted": False,
        "read_only_quote_context_used": False,
    }
    try:
        moomoo_module = __import__("moomoo")
        flags["moomoo_import_succeeded"] = True
    except Exception as exc:  # noqa: BLE001
        for batch_id, batch in enumerate(chunks(targets, batch_size), start=1):
            audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, batch_id, ",".join(sorted({row.get("underlying", "") for row in batch})), len(batch), True, "IMPORT_FAILED", False, "NOT_ATTEMPTED", False, "", "FETCH_NOT_ATTEMPTED", type(exc).__name__, str(exc), 0, "Moomoo package import failed."))
        return raw_rows, audit, flags
    ctx = None
    try:
        quote_cls = getattr(moomoo_module, "OpenQuoteContext")
        flags["moomoo_connection_attempted"] = True
        ctx = quote_cls(host=host, port=port)
        flags["moomoo_connection_succeeded"] = True
        flags["read_only_quote_context_used"] = True
    except Exception as exc:  # noqa: BLE001
        for batch_id, batch in enumerate(chunks(targets, batch_size), start=1):
            audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, batch_id, ",".join(sorted({row.get("underlying", "") for row in batch})), len(batch), True, "IMPORT_SUCCEEDED", True, "CONNECTION_FAILED", False, "", "FETCH_NOT_ATTEMPTED", type(exc).__name__, str(exc), 0, "OpenD quote connection failed."))
        return raw_rows, audit, flags
    try:
        for batch_id, batch in enumerate(chunks(targets, batch_size), start=1):
            flags["quote_enrichment_attempted"] = True
            codes = [row.get("option_code", "") for row in batch]
            method_names = ["get_market_snapshot", "get_stock_quote", "get_option_snapshot"]
            batch_rows: list[dict[str, Any]] = []
            last_error = ""
            method_used = ""
            for method_name in method_names:
                method = getattr(ctx, method_name, None)
                if method is None:
                    continue
                try:
                    result = method(codes)
                    data = result[1] if isinstance(result, tuple) and len(result) >= 2 else result
                    vendor_rows = rows_from_vendor(data)
                    quote_by_code = {str(value_from(quote, ["code", "symbol", "option_code"])): quote for quote in vendor_rows}
                    for source in batch:
                        quote = quote_by_code.get(source.get("option_code", ""), {})
                        batch_rows.append(raw_row_from_quote(source, quote, enrichment_time, "QUOTE_FETCHED_READ_ONLY" if quote else "QUOTE_ROW_NOT_RETURNED"))
                    method_used = method_name
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
            if not method_used:
                for source in batch:
                    batch_rows.append(raw_row_from_quote(source, {}, enrichment_time, "QUOTE_FETCH_FAILED", last_error))
                audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, batch_id, ",".join(sorted({row.get("underlying", "") for row in batch})), len(batch), True, "IMPORT_SUCCEEDED", True, "CONNECTION_SUCCEEDED", True, ";".join(method_names), "FETCH_FAILED", "API_METHOD_UNAVAILABLE_OR_FAILED", last_error, 0, "Read-only quote enrichment batch failed."))
            else:
                audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, batch_id, ",".join(sorted({row.get("underlying", "") for row in batch})), len(batch), True, "IMPORT_SUCCEEDED", True, "CONNECTION_SUCCEEDED", True, method_used, "FETCH_SUCCEEDED", "", "", len(batch_rows), "Read-only quote enrichment batch completed."))
            raw_rows.extend(batch_rows)
    finally:
        close = getattr(ctx, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    return raw_rows, audit, flags


def group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key, "")), []).append(row)
    return grouped


def underlying_audit_rows(targets: list[dict[str, str]], raw_rows: list[dict[str, Any]], clean_rows: list[dict[str, Any]], attempted: bool) -> list[dict[str, Any]]:
    target_by = group_by(targets, "underlying")
    raw_by = group_by(raw_rows, "underlying")
    clean_by = group_by(clean_rows, "underlying")
    underlyings = sorted(set(target_by) | set(raw_by) | set(clean_by))
    rows: list[dict[str, Any]] = []
    for underlying in underlyings:
        clean = clean_by.get(underlying, [])
        raw = raw_by.get(underlying, [])
        valid_bid_ask = sum(1 for row in clean if numeric(row.get("bid")) is not None and numeric(row.get("ask")) is not None)
        valid_mid = sum(1 for row in clean if numeric(row.get("mid")) is not None)
        valid_spread = sum(1 for row in clean if numeric(row.get("spread_pct")) is not None)
        valid_iv = sum(1 for row in clean if numeric(row.get("implied_volatility")) is not None)
        valid_delta = sum(1 for row in clean if numeric(row.get("delta")) is not None)
        valid_gamma = sum(1 for row in clean if numeric(row.get("gamma")) is not None)
        valid_theta = sum(1 for row in clean if numeric(row.get("theta")) is not None)
        valid_vega = sum(1 for row in clean if numeric(row.get("vega")) is not None)
        valid_greeks = sum(1 for row in clean if all(numeric(row.get(field)) is not None for field in ["delta", "gamma", "theta", "vega"]))
        valid_volume = sum(1 for row in clean if numeric(row.get("volume")) is not None)
        valid_oi = sum(1 for row in clean if numeric(row.get("open_interest")) is not None)
        ready_liquidity = valid_bid_ask > 0 and valid_mid > 0 and valid_spread > 0
        ready_candidates = ready_liquidity and valid_iv > 0 and valid_greeks > 0 and valid_volume > 0 and valid_oi > 0
        if not attempted:
            status = "DRY_RUN_SCHEMA_ONLY"
            blocker = "DRY_RUN_NO_FETCH"
        elif not raw:
            status = "FETCH_FAILED"
            blocker = "NO_RAW_QUOTE_ROWS"
        elif ready_candidates:
            status = "ENRICHED_QUOTES_READY"
            blocker = ""
        elif valid_bid_ask > 0:
            status = "ENRICHED_PARTIAL_QUOTES"
            blocker = "MISSING_IV_GREEKS_VOLUME_OR_OI"
        else:
            status = "STRUCTURE_ONLY_QUOTES_STILL_MISSING"
            blocker = "BID_ASK_STILL_MISSING"
        secondary = []
        if valid_iv == 0:
            secondary.append("IV_MISSING")
        if valid_greeks == 0:
            secondary.append("GREEKS_MISSING")
        if valid_volume == 0:
            secondary.append("VOLUME_MISSING")
        if valid_oi == 0:
            secondary.append("OPEN_INTEREST_MISSING")
        rows.append(
            {
                "underlying": underlying,
                "target_contract_count": len(target_by.get(underlying, [])),
                "attempted_contract_count": len(target_by.get(underlying, [])) if attempted else 0,
                "enriched_raw_row_count": len(raw),
                "enriched_clean_row_count": len(clean),
                "valid_bid_ask_count": valid_bid_ask,
                "valid_mid_count": valid_mid,
                "valid_spread_pct_count": valid_spread,
                "valid_iv_count": valid_iv,
                "valid_greeks_count": valid_greeks,
                "valid_delta_count": valid_delta,
                "valid_gamma_count": valid_gamma,
                "valid_theta_count": valid_theta,
                "valid_vega_count": valid_vega,
                "valid_volume_count": valid_volume,
                "valid_open_interest_count": valid_oi,
                "quote_enrichment_status": status,
                "ready_for_liquidity_audit": ready_liquidity,
                "ready_for_candidate_generation": ready_candidates,
                "primary_blocker": blocker,
                "secondary_blockers": ";".join(secondary),
                "reason": "Quote enrichment is read-only; candidate generation remains separately gated.",
            }
        )
    return rows


def field_coverage_rows(raw_rows: list[dict[str, Any]], clean_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_map = {
        "bid": "bid_raw",
        "ask": "ask_raw",
        "last": "last_raw",
        "volume": "volume_raw",
        "open_interest": "open_interest_raw",
        "implied_volatility": "implied_volatility_raw",
        "delta": "delta_raw",
        "gamma": "gamma_raw",
        "theta": "theta_raw",
        "vega": "vega_raw",
        "rho": "rho_raw",
        "underlying_price": "underlying_price_raw",
        "exchange": "exchange_raw",
    }
    fields = list(dict.fromkeys(CLEAN_FIELDNAMES))
    raw_total = len(raw_rows)
    clean_total = len(clean_rows)
    rows: list[dict[str, Any]] = []
    for field in fields:
        raw_field = raw_map.get(field, field)
        raw_count = sum(1 for row in raw_rows if str(row.get(raw_field, "")).strip())
        clean_count = sum(1 for row in clean_rows if str(row.get(field, "")).strip())
        rows.append(
            {
                "field_name": field,
                "raw_non_null_count": raw_count,
                "clean_non_null_count": clean_count,
                "raw_coverage_ratio": round(raw_count / raw_total, 6) if raw_total else 0,
                "clean_coverage_ratio": round(clean_count / clean_total, 6) if clean_total else 0,
                "required_for_candidate_generation": field in REQUIRED_FOR_CANDIDATE,
                "required_for_liquidity_audit": field in LIQUIDITY_FIELDS,
                "required_for_greeks_audit": field in GREEKS_FIELDS,
                "field_status": "FIELD_PRESENT" if clean_count else "FIELD_MISSING_OR_NO_ROWS",
                "reason": "Coverage is measured only from returned quote rows; missing values are not fabricated.",
            }
        )
    return rows


def summary_payload(repo_root: Path, execute: bool, source_rows: list[dict[str, str]], targets: list[dict[str, str]], raw_rows: list[dict[str, Any]], clean_rows: list[dict[str, Any]], underlying_rows: list[dict[str, Any]], fetch_audit: list[dict[str, Any]], flags: dict[str, bool]) -> dict[str, Any]:
    required = required_flags(repo_root)
    required_ok = required["v22_032_clean_input_exists"] and required["v22_032_summary_input_exists"]
    valid_bid_ask = sum(int(row["valid_bid_ask_count"]) for row in underlying_rows)
    valid_mid = sum(int(row["valid_mid_count"]) for row in underlying_rows)
    valid_spread = sum(int(row["valid_spread_pct_count"]) for row in underlying_rows)
    valid_iv = sum(int(row["valid_iv_count"]) for row in underlying_rows)
    valid_greeks = sum(int(row["valid_greeks_count"]) for row in underlying_rows)
    valid_volume = sum(int(row["valid_volume_count"]) for row in underlying_rows)
    valid_oi = sum(int(row["valid_open_interest_count"]) for row in underlying_rows)
    ready_count = sum(1 for row in underlying_rows if row["ready_for_candidate_generation"] is True)
    failed_batches = sum(1 for row in fetch_audit if row["fetch_status"] == "FETCH_FAILED")
    successful_batches = sum(1 for row in fetch_audit if row["fetch_status"] == "FETCH_SUCCEEDED")
    if not required_ok:
        status = FAIL_MISSING_INPUTS
        decision = FAIL_DECISION
    elif not execute:
        status = PASS_DRY_RUN
        decision = READY_DECISION
    elif flags.get("quote_enrichment_attempted") and valid_bid_ask > 0 and ready_count > 0:
        status = PASS_READY
        decision = READY_DECISION
    elif flags.get("quote_enrichment_attempted") and valid_bid_ask > 0:
        status = WARN_PARTIAL
        decision = READY_DECISION
    elif flags.get("moomoo_connection_attempted") and not flags.get("moomoo_connection_succeeded"):
        status = WARN_FETCH_FAILED
        decision = READY_DECISION
    elif failed_batches and not successful_batches:
        status = WARN_FETCH_FAILED
        decision = READY_DECISION
    else:
        status = WARN_STILL_MISSING
        decision = READY_DECISION
    execution_mode = "EXECUTE_READ_ONLY" if execute else "DRY_RUN"
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": status,
        "final_decision": decision,
        "execution_mode": execution_mode,
        **required,
        "source_clean_contract_row_count": len(source_rows),
        "source_unique_option_code_count": len({row.get("option_code", "") for row in source_rows if row.get("option_code")}),
        "target_contract_count": len(targets),
        "attempted_contract_count": len(targets) if execute else 0,
        "batch_count": len(fetch_audit),
        "successful_batch_count": successful_batches,
        "failed_batch_count": failed_batches,
        "enriched_raw_row_count": len(raw_rows),
        "enriched_clean_row_count": len(clean_rows),
        "underlying_attempted_count": len({row.get("underlying", "") for row in targets}) if execute else 0,
        "underlying_enriched_count": len({row.get("underlying", "") for row in clean_rows}),
        "valid_bid_ask_count": valid_bid_ask,
        "valid_mid_count": valid_mid,
        "valid_spread_pct_count": valid_spread,
        "valid_iv_count": valid_iv,
        "valid_greeks_count": valid_greeks,
        "valid_volume_count": valid_volume,
        "valid_open_interest_count": valid_oi,
        "ready_for_candidate_generation_count": ready_count,
        "quote_enrichment_attempted": bool(flags.get("quote_enrichment_attempted", False)),
        "quote_enrichment_succeeded": valid_bid_ask > 0,
        "moomoo_import_attempted": bool(flags.get("moomoo_import_attempted", False)),
        "moomoo_import_succeeded": bool(flags.get("moomoo_import_succeeded", False)),
        "moomoo_connection_attempted": bool(flags.get("moomoo_connection_attempted", False)),
        "moomoo_connection_succeeded": bool(flags.get("moomoo_connection_succeeded", False)),
        "read_only_quote_context_used": bool(flags.get("read_only_quote_context_used", False)),
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "modify_order_called": False,
        "cancel_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_allowed": False,
        "market_data_fetch_allowed": execute,
        "moomoo_connection_allowed": execute,
        "option_quote_fetch_allowed": execute,
        "option_chain_fetch_allowed": False,
        "daily_chain_execution_allowed": False,
        "historical_outputs_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "factor_promotion_allowed": False,
        "factor_weight_change_allowed": False,
        "candidate_generation_allowed": ready_count > 0,
        "protected_outputs_modified": False,
        "research_only": True,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
    }


def risk_gate_payload(candidate_generation_allowed: bool) -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_allowed": False,
        "daily_chain_execution_allowed": False,
        "historical_outputs_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "factor_promotion_allowed": False,
        "factor_weight_change_allowed": False,
        "trade_context_allowed": False,
        "unlock_trade_allowed": False,
        "place_order_allowed": False,
        "modify_order_allowed": False,
        "cancel_order_allowed": False,
        "account_query_allowed": False,
        "candidate_generation_allowed": candidate_generation_allowed,
        "allowed_side_effects": [
            "create_outputs_v22_032_r1_only",
            "read_only_quote_market_data_fetch_only_in_execute_mode",
        ],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "use_trade_context",
            "unlock_trade",
            "place_order",
            "modify_order",
            "cancel_order",
            "query_broker_account",
            "mutate_v21_outputs",
            "mutate_cache",
            "create_trade_order",
            "modify_broker_state",
            "promote_factor",
            "promote_strategy",
            "change_factor_weight",
        ],
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.032_R1 Option Quote Enrichment From Moomoo Read Only",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"execution_mode={summary['execution_mode']}",
        f"source_clean_contract_row_count={summary['source_clean_contract_row_count']}",
        f"target_contract_count={summary['target_contract_count']}",
        f"quote_enrichment_attempted={summary['quote_enrichment_attempted']}",
        f"valid_bid_ask_count={summary['valid_bid_ask_count']}",
        "trade_context_used=False",
        "broker_action_allowed=False",
        "trade_allowed=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path, execute: bool = False, host: str = "127.0.0.1", port: int = 18441, max_contracts: int = 2000, batch_size: int = 200, underlying_filter: str | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_rows = read_csv_rows(repo_root / SOURCE_CLEAN_INPUT)
    targets = unique_targets(source_rows, max_contracts, underlying_filter)
    enrichment_time = utc_now_text()
    flags = {
        "moomoo_import_attempted": False,
        "moomoo_import_succeeded": False,
        "moomoo_connection_attempted": False,
        "moomoo_connection_succeeded": False,
        "quote_enrichment_attempted": False,
        "read_only_quote_context_used": False,
    }
    if execute and required_flags(repo_root)["v22_032_clean_input_exists"] and required_flags(repo_root)["v22_032_summary_input_exists"]:
        raw_rows, fetch_audit, flags = execute_enrichment(targets, host, port, batch_size, enrichment_time)
    else:
        raw_rows = []
        fetch_audit = dry_run_fetch_audit(targets, host, port, batch_size)
    clean_rows = [clean_from_raw(row) for row in raw_rows]
    underlying_rows = underlying_audit_rows(targets, raw_rows, clean_rows, execute)
    field_rows = field_coverage_rows(raw_rows, clean_rows)
    summary = summary_payload(repo_root, execute, source_rows, targets, raw_rows, clean_rows, underlying_rows, fetch_audit, flags)

    write_csv(output_dir / "v22_option_quote_enrichment_raw.csv", RAW_FIELDNAMES, raw_rows)
    write_csv(output_dir / "v22_option_quote_enrichment_clean.csv", CLEAN_FIELDNAMES, clean_rows)
    write_csv(output_dir / "v22_option_quote_enrichment_underlying_audit.csv", UNDERLYING_AUDIT_FIELDNAMES, underlying_rows)
    write_csv(output_dir / "v22_option_quote_enrichment_fetch_audit.csv", FETCH_AUDIT_FIELDNAMES, fetch_audit)
    write_csv(output_dir / "v22_option_quote_enrichment_field_coverage_audit.csv", FIELD_COVERAGE_FIELDNAMES, field_rows)
    write_json(output_dir / "v22_option_quote_enrichment_summary.json", summary)
    write_json(output_dir / "v22_option_quote_enrichment_risk_gate.json", risk_gate_payload(summary["candidate_generation_allowed"]))
    (output_dir / "V22.032_R1_option_quote_enrichment_from_moomoo_read_only_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    parser.add_argument("--max-contracts", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--underlying-filter", default=None)
    args = parser.parse_args(argv)
    payload = run(
        args.repo_root,
        execute=args.execute,
        host=args.host,
        port=args.port,
        max_contracts=args.max_contracts,
        batch_size=args.batch_size,
        underlying_filter=args.underlying_filter,
    )
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"execution_mode={payload['execution_mode']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_option_quote_enrichment_summary.json'}")
    print("broker_action_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_MISSING_INPUTS else 0


if __name__ == "__main__":
    raise SystemExit(main())
