#!/usr/bin/env python
"""V22.032 Moomoo ETF option chain snapshot.

Default mode is a deterministic dry run that creates schemas without connecting
to Moomoo/OpenD. Execute mode may use a read-only quote context for option-chain
market data only. This module never uses a trade context, unlocks trading,
places or modifies orders, mutates V21 outputs, mutates cache, or generates
trade candidates/recommendations.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ID = "V22.032"
MODULE_NAME = "MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT"
STAGE = "V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT"
OUT_REL = Path("outputs") / "v22" / STAGE

UNIVERSE_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_registry.csv"
UNIVERSE_SUMMARY_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_summary.json"
CONTRACT_INPUT = Path("outputs") / "v22" / "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY" / "v22_etf_option_contract_spec_registry.csv"
CONTRACT_SUMMARY_INPUT = Path("outputs") / "v22" / "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY" / "v22_etf_option_contract_spec_summary.json"

PASS_READY = "PASS_V22_032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT_READY"
PASS_DRY_RUN = "PASS_V22_032_DRY_RUN_SCHEMA_READY"
WARN_NO_ROWS = "WARN_V22_032_OPTION_CHAIN_FETCH_COMPLETED_WITH_NO_USABLE_CONTRACTS"
WARN_FETCH_FAILED = "WARN_V22_032_MOOMOO_CONNECTION_OR_FETCH_FAILED_READ_ONLY"
FAIL_MISSING_INPUTS = "FAIL_V22_032_MISSING_REQUIRED_INPUTS"
READY_DECISION = "MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT_READY_FOR_COVERAGE_AUDIT_RESEARCH_ONLY"
FAIL_DECISION = "MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT",
    "V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA",
    "V22.040_LONG_CALL_PUT_CANDIDATE_GENERATOR",
]

SNAPSHOT_FIELDNAMES = [
    "snapshot_time_utc",
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
    "raw_status",
    "clean_status",
    "reason",
]

UNDERLYING_AUDIT_FIELDNAMES = [
    "underlying",
    "theme_bucket",
    "universe_group",
    "universe_tier",
    "leveraged_flag",
    "inverse_flag",
    "high_risk_secondary_flag",
    "fetch_attempted",
    "fetch_status",
    "raw_contract_count",
    "clean_contract_count",
    "expiration_count",
    "call_count",
    "put_count",
    "valid_bid_ask_count",
    "valid_iv_count",
    "valid_greeks_count",
    "valid_volume_count",
    "valid_open_interest_count",
    "atm_contract_detected",
    "nearest_expiration",
    "farthest_expiration",
    "latest_snapshot_time_utc",
    "error_message",
    "reason",
]

FETCH_AUDIT_FIELDNAMES = [
    "event_time_utc",
    "mode",
    "host",
    "port",
    "moomoo_import_attempted",
    "moomoo_import_status",
    "moomoo_connection_attempted",
    "moomoo_connection_status",
    "option_chain_fetch_attempted",
    "underlying",
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
REQUIRED_FOR_LIQUIDITY = {"bid", "ask", "mid", "spread_pct", "volume", "open_interest"}
REQUIRED_FOR_GREEKS = {"implied_volatility", "delta", "gamma", "theta", "vega", "rho"}

NO_TRADE_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}


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


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.032 output directory must be {expected}, got {output_dir.resolve()}")


def required_flags(repo_root: Path) -> dict[str, bool]:
    return {
        "v22_030_universe_input_exists": (repo_root / UNIVERSE_INPUT).exists(),
        "v22_030_summary_input_exists": (repo_root / UNIVERSE_SUMMARY_INPUT).exists(),
        "v22_031_contract_input_exists": (repo_root / CONTRACT_INPUT).exists(),
        "v22_031_summary_input_exists": (repo_root / CONTRACT_SUMMARY_INPUT).exists(),
    }


def bool_from_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def target_underlyings(universe_rows: list[dict[str, str]], contract_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    contract_tickers = {row.get("ticker", "") for row in contract_rows}
    rows: list[dict[str, Any]] = []
    for row in universe_rows:
        ticker = row.get("ticker", "")
        if ticker and ticker in contract_tickers:
            rows.append(
                {
                    "underlying": ticker,
                    "theme_bucket": row.get("theme_bucket", ""),
                    "universe_group": row.get("universe_group", ""),
                    "universe_tier": row.get("universe_tier", ""),
                    "leveraged_flag": bool_from_text(row.get("leveraged_flag", "")),
                    "inverse_flag": bool_from_text(row.get("inverse_flag", "")),
                    "leverage_multiple": row.get("leverage_multiple", ""),
                    "high_risk_secondary_flag": bool_from_text(row.get("high_risk_secondary_flag", "")),
                }
            )
    return rows


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(result):
        return result
    return None


def text_value(row: dict[str, Any], candidates: list[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return ""


def normalize_vendor_row(raw: dict[str, Any], target: dict[str, Any], snapshot_time: str, raw_status: str, reason: str) -> dict[str, Any]:
    expiration = text_value(raw, ["expiration", "expiry", "expiry_date", "strike_time", "maturity_date"])
    strike = text_value(raw, ["strike", "strike_price"])
    call_put = text_value(raw, ["call_put", "option_type", "type"])
    option_code = text_value(raw, ["option_code", "code", "symbol"])
    bid = text_value(raw, ["bid", "bid_price"])
    ask = text_value(raw, ["ask", "ask_price"])
    last = text_value(raw, ["last", "last_price", "close"])
    volume = text_value(raw, ["volume", "vol"])
    open_interest = text_value(raw, ["open_interest", "oi"])
    iv = text_value(raw, ["implied_volatility", "iv"])
    row = {
        "snapshot_time_utc": snapshot_time,
        "underlying": target["underlying"],
        "universe_group": target["universe_group"],
        "universe_tier": target["universe_tier"],
        "theme_bucket": target["theme_bucket"],
        "leveraged_flag": target["leveraged_flag"],
        "inverse_flag": target["inverse_flag"],
        "leverage_multiple": target["leverage_multiple"],
        "expiration": expiration,
        "dte": text_value(raw, ["dte", "days_to_expiry"]),
        "strike": strike,
        "call_put": call_put,
        "option_code": option_code,
        "option_name": text_value(raw, ["option_name", "name"]),
        "bid": bid,
        "ask": ask,
        "mid": "",
        "last": last,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": iv,
        "delta": text_value(raw, ["delta"]),
        "gamma": text_value(raw, ["gamma"]),
        "theta": text_value(raw, ["theta"]),
        "vega": text_value(raw, ["vega"]),
        "rho": text_value(raw, ["rho"]),
        "underlying_price": text_value(raw, ["underlying_price", "stock_price", "underlying_last"]),
        "moneyness": "",
        "spread_abs": "",
        "spread_pct": "",
        "contract_size": text_value(raw, ["contract_size", "contract_multiplier"]),
        "exchange": text_value(raw, ["exchange", "market"]),
        "data_vendor": "MOOMOO_OPEND",
        "raw_status": raw_status,
        "clean_status": "",
        "reason": reason,
    }
    return row


def clean_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        required = [row.get("underlying"), row.get("expiration"), row.get("strike"), row.get("call_put"), row.get("option_code")]
        if not all(str(value).strip() for value in required):
            continue
        clean = dict(row)
        bid = numeric(clean.get("bid"))
        ask = numeric(clean.get("ask"))
        strike = numeric(clean.get("strike"))
        underlying_price = numeric(clean.get("underlying_price"))
        if bid is not None and ask is not None and ask >= bid:
            mid = (bid + ask) / 2
            spread_abs = ask - bid
            clean["mid"] = round(mid, 6)
            clean["spread_abs"] = round(spread_abs, 6)
            clean["spread_pct"] = round(spread_abs / mid, 6) if mid > 0 else ""
        if strike is not None and underlying_price is not None and underlying_price > 0:
            clean["moneyness"] = round(strike / underlying_price, 6)
        clean["clean_status"] = "CLEAN_USABLE_FOR_COVERAGE_AUDIT"
        rows.append(clean)
    return rows


def dataframe_like_to_rows(value: Any) -> list[dict[str, Any]]:
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
        for key in ["data", "rows", "contracts"]:
            if isinstance(value.get(key), list):
                return [dict(row) for row in value[key] if isinstance(row, dict)]
    return []


def try_fetch_for_underlying(ctx: Any, target: dict[str, Any], snapshot_time: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attempted_methods = ["get_option_chain", "request_option_chain", "get_option_expiration_date"]
    last_error = ""
    for method_name in attempted_methods:
        method = getattr(ctx, method_name, None)
        if method is None:
            continue
        try:
            if method_name == "get_option_expiration_date":
                result = method(code=f"US.{target['underlying']}")
            else:
                result = method(code=f"US.{target['underlying']}")
            data = result[1] if isinstance(result, tuple) and len(result) >= 2 else result
            source_rows = dataframe_like_to_rows(data)
            rows = [normalize_vendor_row(row, target, snapshot_time, "FETCHED_READ_ONLY", "Fetched through read-only quote context.") for row in source_rows]
            return rows, {"api_method_attempted": method_name, "fetch_status": "FETCH_SUCCEEDED", "error_type": "", "error_message": "", "row_count": len(rows)}
        except Exception as exc:  # noqa: BLE001 - defensive broker package boundary
            last_error = str(exc)
    return [], {"api_method_attempted": ";".join(attempted_methods), "fetch_status": "FETCH_FAILED", "error_type": "API_METHOD_UNAVAILABLE_OR_FAILED", "error_message": last_error, "row_count": 0}


def execute_fetch(targets: list[dict[str, Any]], host: str, port: int, snapshot_time: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool]]:
    fetch_audit: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    flags = {
        "moomoo_import_attempted": True,
        "moomoo_import_succeeded": False,
        "moomoo_connection_attempted": False,
        "moomoo_connection_succeeded": False,
        "option_chain_fetch_attempted": False,
        "read_only_quote_context_used": False,
    }
    ctx = None
    module = None
    try:
        module = __import__("moomoo")
        flags["moomoo_import_succeeded"] = True
    except Exception as exc:  # noqa: BLE001 - optional package boundary
        for target in targets:
            fetch_audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, True, "IMPORT_FAILED", False, "NOT_ATTEMPTED", False, target["underlying"], "", "FETCH_NOT_ATTEMPTED", type(exc).__name__, str(exc), 0, "Moomoo package import failed."))
        return raw_rows, fetch_audit, flags
    try:
        quote_cls = getattr(module, "OpenQuoteContext")
        flags["moomoo_connection_attempted"] = True
        ctx = quote_cls(host=host, port=port)
        flags["moomoo_connection_succeeded"] = True
        flags["read_only_quote_context_used"] = True
    except Exception as exc:  # noqa: BLE001 - local OpenD boundary
        for target in targets:
            fetch_audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, True, "IMPORT_SUCCEEDED", True, "CONNECTION_FAILED", False, target["underlying"], "", "FETCH_NOT_ATTEMPTED", type(exc).__name__, str(exc), 0, "OpenD quote connection failed."))
        return raw_rows, fetch_audit, flags
    try:
        for target in targets:
            flags["option_chain_fetch_attempted"] = True
            rows, audit = try_fetch_for_underlying(ctx, target, snapshot_time)
            raw_rows.extend(rows)
            fetch_audit.append(fetch_event("EXECUTE_READ_ONLY", host, port, True, "IMPORT_SUCCEEDED", True, "CONNECTION_SUCCEEDED", True, target["underlying"], audit["api_method_attempted"], audit["fetch_status"], audit["error_type"], audit["error_message"], audit["row_count"], "Read-only quote option-chain attempt."))
    finally:
        close = getattr(ctx, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    return raw_rows, fetch_audit, flags


def fetch_event(mode: str, host: str, port: int, import_attempted: bool, import_status: str, connection_attempted: bool, connection_status: str, fetch_attempted: bool, underlying: str, method: str, fetch_status: str, error_type: str, error_message: str, row_count: int, note: str) -> dict[str, Any]:
    return {
        "event_time_utc": utc_now_text(),
        "mode": mode,
        "host": host,
        "port": port,
        "moomoo_import_attempted": import_attempted,
        "moomoo_import_status": import_status,
        "moomoo_connection_attempted": connection_attempted,
        "moomoo_connection_status": connection_status,
        "option_chain_fetch_attempted": fetch_attempted,
        "underlying": underlying,
        "api_method_attempted": method,
        "fetch_status": fetch_status,
        "error_type": error_type,
        "error_message": error_message,
        "row_count": row_count,
        "note": note,
    }


def dry_run_fetch_audit(targets: list[dict[str, Any]], host: str, port: int) -> list[dict[str, Any]]:
    return [
        fetch_event("DRY_RUN", host, port, False, "NOT_ATTEMPTED_DRY_RUN", False, "NOT_ATTEMPTED_DRY_RUN", False, target["underlying"], "", "DRY_RUN_NOT_FETCHED", "", "", 0, "Dry run creates schemas only.")
        for target in targets
    ]


def underlying_audit_rows(targets: list[dict[str, Any]], raw_rows: list[dict[str, Any]], clean: list[dict[str, Any]], fetch_audit: list[dict[str, Any]], execute: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_underlying_raw = group_by(raw_rows, "underlying")
    by_underlying_clean = group_by(clean, "underlying")
    fetch_by_underlying = {row["underlying"]: row for row in fetch_audit if row.get("underlying")}
    for target in targets:
        underlying = target["underlying"]
        raw = by_underlying_raw.get(underlying, [])
        clean_rows_for_underlying = by_underlying_clean.get(underlying, [])
        expirations = sorted({str(row.get("expiration", "")) for row in clean_rows_for_underlying if row.get("expiration")})
        rows.append(
            {
                "underlying": underlying,
                "theme_bucket": target["theme_bucket"],
                "universe_group": target["universe_group"],
                "universe_tier": target["universe_tier"],
                "leveraged_flag": target["leveraged_flag"],
                "inverse_flag": target["inverse_flag"],
                "high_risk_secondary_flag": target["high_risk_secondary_flag"],
                "fetch_attempted": execute,
                "fetch_status": fetch_by_underlying.get(underlying, {}).get("fetch_status", "DRY_RUN_NOT_FETCHED" if not execute else "NOT_ATTEMPTED"),
                "raw_contract_count": len(raw),
                "clean_contract_count": len(clean_rows_for_underlying),
                "expiration_count": len(expirations),
                "call_count": sum(1 for row in clean_rows_for_underlying if str(row.get("call_put", "")).upper().startswith("C")),
                "put_count": sum(1 for row in clean_rows_for_underlying if str(row.get("call_put", "")).upper().startswith("P")),
                "valid_bid_ask_count": sum(1 for row in clean_rows_for_underlying if numeric(row.get("bid")) is not None and numeric(row.get("ask")) is not None),
                "valid_iv_count": sum(1 for row in clean_rows_for_underlying if numeric(row.get("implied_volatility")) is not None),
                "valid_greeks_count": sum(1 for row in clean_rows_for_underlying if all(numeric(row.get(field)) is not None for field in ["delta", "gamma", "theta", "vega"])),
                "valid_volume_count": sum(1 for row in clean_rows_for_underlying if numeric(row.get("volume")) is not None),
                "valid_open_interest_count": sum(1 for row in clean_rows_for_underlying if numeric(row.get("open_interest")) is not None),
                "atm_contract_detected": any(numeric(row.get("moneyness")) is not None and abs(float(row["moneyness"]) - 1.0) <= 0.02 for row in clean_rows_for_underlying),
                "nearest_expiration": expirations[0] if expirations else "",
                "farthest_expiration": expirations[-1] if expirations else "",
                "latest_snapshot_time_utc": max((str(row.get("snapshot_time_utc", "")) for row in raw), default=""),
                "error_message": fetch_by_underlying.get(underlying, {}).get("error_message", ""),
                "reason": "Dry-run schema row." if not execute else "Read-only quote fetch audit row.",
            }
        )
    return rows


def group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key, "")), []).append(row)
    return grouped


def field_coverage_rows(raw_rows: list[dict[str, Any]], clean: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_total = len(raw_rows)
    clean_total = len(clean)
    for field in SNAPSHOT_FIELDNAMES:
        raw_count = sum(1 for row in raw_rows if str(row.get(field, "")).strip())
        clean_count = sum(1 for row in clean if str(row.get(field, "")).strip())
        rows.append(
            {
                "field_name": field,
                "raw_non_null_count": raw_count,
                "clean_non_null_count": clean_count,
                "raw_coverage_ratio": round(raw_count / raw_total, 6) if raw_total else 0,
                "clean_coverage_ratio": round(clean_count / clean_total, 6) if clean_total else 0,
                "required_for_candidate_generation": field in REQUIRED_FOR_CANDIDATE,
                "required_for_liquidity_audit": field in REQUIRED_FOR_LIQUIDITY,
                "required_for_greeks_audit": field in REQUIRED_FOR_GREEKS,
                "field_status": "FIELD_PRESENT" if clean_count else "FIELD_MISSING_OR_NO_ROWS",
                "reason": "Coverage is measured from available rows only; missing fields are not fabricated.",
            }
        )
    return rows


def summary_payload(repo_root: Path, execute: bool, targets: list[dict[str, Any]], raw_rows: list[dict[str, Any]], clean: list[dict[str, Any]], underlying_audit: list[dict[str, Any]], fetch_audit: list[dict[str, Any]], flags: dict[str, bool]) -> dict[str, Any]:
    required = required_flags(repo_root)
    required_ok = all(required.values())
    execution_mode = "EXECUTE_READ_ONLY" if execute else "DRY_RUN"
    fetch_attempted = bool(flags.get("option_chain_fetch_attempted", False))
    any_fetch_failed = any(row.get("fetch_status") == "FETCH_FAILED" for row in fetch_audit)
    if not required_ok:
        final_status = FAIL_MISSING_INPUTS
        final_decision = FAIL_DECISION
    elif not execute:
        final_status = PASS_DRY_RUN
        final_decision = READY_DECISION
    elif clean:
        final_status = PASS_READY
        final_decision = READY_DECISION
    elif any_fetch_failed or not flags.get("moomoo_connection_succeeded", False):
        final_status = WARN_FETCH_FAILED
        final_decision = READY_DECISION
    else:
        final_status = WARN_NO_ROWS
        final_decision = READY_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "execution_mode": execution_mode,
        **required,
        "target_underlying_count": len(targets),
        "fetch_attempted_underlying_count": sum(1 for row in underlying_audit if row["fetch_attempted"] is True),
        "fetch_succeeded_underlying_count": sum(1 for row in underlying_audit if row["fetch_status"] == "FETCH_SUCCEEDED"),
        "fetch_failed_underlying_count": sum(1 for row in underlying_audit if row["fetch_status"] == "FETCH_FAILED"),
        "raw_contract_row_count": len(raw_rows),
        "clean_contract_row_count": len(clean),
        "underlying_with_clean_contract_count": len({row["underlying"] for row in clean}),
        "total_expiration_count": sum(int(row["expiration_count"]) for row in underlying_audit),
        "total_valid_bid_ask_count": sum(int(row["valid_bid_ask_count"]) for row in underlying_audit),
        "total_valid_iv_count": sum(int(row["valid_iv_count"]) for row in underlying_audit),
        "total_valid_greeks_count": sum(int(row["valid_greeks_count"]) for row in underlying_audit),
        "total_valid_volume_count": sum(int(row["valid_volume_count"]) for row in underlying_audit),
        "total_valid_open_interest_count": sum(int(row["valid_open_interest_count"]) for row in underlying_audit),
        "moomoo_import_attempted": bool(flags.get("moomoo_import_attempted", False)),
        "moomoo_import_succeeded": bool(flags.get("moomoo_import_succeeded", False)),
        "moomoo_connection_attempted": bool(flags.get("moomoo_connection_attempted", False)),
        "moomoo_connection_succeeded": bool(flags.get("moomoo_connection_succeeded", False)),
        "option_chain_fetch_attempted": fetch_attempted,
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
        "option_chain_fetch_allowed": execute,
        "daily_chain_execution_allowed": False,
        "historical_outputs_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "factor_promotion_allowed": False,
        "factor_weight_change_allowed": False,
        "protected_outputs_modified": False,
        "research_only": True,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
    }


def risk_gate_payload() -> dict[str, Any]:
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
        "allowed_side_effects": [
            "create_outputs_v22_032_only",
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
        "V22.032 Moomoo ETF Option Chain Snapshot",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"execution_mode={summary['execution_mode']}",
        f"target_underlying_count={summary['target_underlying_count']}",
        f"raw_contract_row_count={summary['raw_contract_row_count']}",
        f"clean_contract_row_count={summary['clean_contract_row_count']}",
        f"moomoo_connection_attempted={summary['moomoo_connection_attempted']}",
        f"option_chain_fetch_attempted={summary['option_chain_fetch_attempted']}",
        "trade_context_used=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path, execute: bool = False, host: str = "127.0.0.1", port: int = 18441) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    flags = {
        "moomoo_import_attempted": False,
        "moomoo_import_succeeded": False,
        "moomoo_connection_attempted": False,
        "moomoo_connection_succeeded": False,
        "option_chain_fetch_attempted": False,
        "read_only_quote_context_used": False,
    }
    required_ok = all(required_flags(repo_root).values())
    universe = read_csv_rows(repo_root / UNIVERSE_INPUT) if required_ok else []
    contracts = read_csv_rows(repo_root / CONTRACT_INPUT) if required_ok else []
    targets = target_underlyings(universe, contracts)
    snapshot_time = utc_now_text()
    if execute and required_ok:
        raw_rows, fetch_audit, flags = execute_fetch(targets, host, port, snapshot_time)
    else:
        raw_rows = []
        fetch_audit = dry_run_fetch_audit(targets, host, port)
    clean = clean_rows(raw_rows)
    underlying_audit = underlying_audit_rows(targets, raw_rows, clean, fetch_audit, execute and required_ok)
    field_coverage = field_coverage_rows(raw_rows, clean)
    summary = summary_payload(repo_root, execute and required_ok, targets, raw_rows, clean, underlying_audit, fetch_audit, flags)

    write_csv(output_dir / "v22_moomoo_etf_option_chain_snapshot_raw.csv", SNAPSHOT_FIELDNAMES, raw_rows)
    write_csv(output_dir / "v22_moomoo_etf_option_chain_snapshot_clean.csv", SNAPSHOT_FIELDNAMES, clean)
    write_csv(output_dir / "v22_moomoo_etf_option_chain_underlying_audit.csv", UNDERLYING_AUDIT_FIELDNAMES, underlying_audit)
    write_csv(output_dir / "v22_moomoo_etf_option_chain_fetch_audit.csv", FETCH_AUDIT_FIELDNAMES, fetch_audit)
    write_csv(output_dir / "v22_moomoo_etf_option_chain_field_coverage_audit.csv", FIELD_COVERAGE_FIELDNAMES, field_coverage)
    write_json(output_dir / "v22_moomoo_etf_option_chain_snapshot_summary.json", summary)
    write_json(output_dir / "v22_moomoo_etf_option_chain_snapshot_risk_gate.json", risk_gate_payload())
    (output_dir / "V22.032_moomoo_etf_option_chain_snapshot_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    args = parser.parse_args(argv)
    payload = run(args.repo_root, execute=args.execute, host=args.host, port=args.port)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"execution_mode={payload['execution_mode']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_moomoo_etf_option_chain_snapshot_summary.json'}")
    print("broker_action_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_MISSING_INPUTS else 0


if __name__ == "__main__":
    raise SystemExit(main())
