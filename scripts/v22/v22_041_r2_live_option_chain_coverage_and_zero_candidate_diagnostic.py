#!/usr/bin/env python
"""V22.041 R2 live option chain zero-candidate diagnostic.

Research-only live read-only Moomoo option-chain coverage and filter-funnel
audit. This does not change V22.041 strategy logic, open trade context, unlock
trading, place orders, or write official adoption artifacts.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import os
import socket
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable


MODULE_ID = "V22.041_R2"
MODULE_NAME = "LIVE_OPTION_CHAIN_COVERAGE_AND_ZERO_CANDIDATE_DIAGNOSTIC"
STAGE = "V22.041_R2_LIVE_OPTION_CHAIN_COVERAGE_AND_ZERO_CANDIDATE_DIAGNOSTIC"
OUT_REL = Path("outputs") / "v22" / STAGE
R1A_STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"
V22_041_SUMMARY_REL = Path("outputs") / "v22" / "V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1" / "v22_041_summary.json"

PASS_STATUS = "PASS_V22_041_R2_LIVE_OPTION_ZERO_CANDIDATE_DIAGNOSTIC_READY"
WARN_STATUS = "WARN_V22_041_R2_LIVE_OPTION_QUOTE_UNAVAILABLE"
READY_DECISION = "LIVE_OPTION_ZERO_CANDIDATE_ROOT_CAUSE_IDENTIFIED_RESEARCH_ONLY"
BLOCKED_DECISION = "LIVE_OPTION_ZERO_CANDIDATE_DIAGNOSTIC_BLOCKED_RESEARCH_ONLY"

ALLOWED_ETFS = ["SOXX", "SOXL", "SOXS", "QQQ", "TQQQ", "SQQQ", "SPY"]
ASOF_DATE = date(2026, 7, 8)

BID_FIELDS = ["bid", "bid_price", "bidPrice", "best_bid", "bestBid", "bid1", "bid_1"]
ASK_FIELDS = ["ask", "ask_price", "askPrice", "best_ask", "bestAsk", "ask1", "ask_1"]
VOLUME_FIELDS = ["volume", "vol", "trade_volume", "option_volume"]
OI_FIELDS = ["open_interest", "openInterest", "oi", "option_open_interest"]
IV_FIELDS = ["implied_volatility", "impliedVolatility", "iv", "implied_vol"]
DELTA_FIELDS = ["delta"]
GAMMA_FIELDS = ["gamma"]
THETA_FIELDS = ["theta"]
VEGA_FIELDS = ["vega"]
RHO_FIELDS = ["rho"]
EXPIRY_FIELDS = ["expiration", "expiry", "expiry_date", "expiration_date", "strike_time", "end_date"]
CALL_PUT_FIELDS = ["call_put", "option_type", "type", "contract_type"]
STRIKE_FIELDS = ["strike", "strike_price", "strikePrice"]
CONTRACT_ID_FIELDS = ["contract_id", "option_code", "code", "symbol", "name"]

COVERAGE_FIELDS = [
    "underlying", "chain_fetch_attempted", "chain_fetch_succeeded", "raw_contract_count",
    "expiry_count", "min_dte", "max_dte", "dte_1_21_count", "call_count", "put_count",
    "fetch_status", "error_type", "error_message",
]
FIELD_FIELDS = [
    "underlying", "raw_contract_count", "raw_field_names", "bid_field_found", "ask_field_found",
    "expiration_field_found", "volume_field_found", "open_interest_field_found", "iv_field_found",
    "delta_field_found", "gamma_field_found", "theta_field_found", "vega_field_found",
    "bid_available_count", "ask_available_count", "mid_available_count", "spread_pct_available_count",
    "volume_available_count", "open_interest_available_count", "iv_available_count",
    "greeks_complete_count", "field_mapping_issue_detected", "missing_volume_field_all_rows",
    "missing_bid_ask_field_all_rows",
]
FUNNEL_FIELDS = [
    "step_order", "filter_step", "surviving_count", "dropped_count", "drop_reason",
    "official_filter", "notes",
]
ROOT_FIELDS = [
    "root_cause_rank", "root_cause_code", "underlying", "evidence_count", "evidence_detail",
    "recommended_next_action",
]
RELAXED_FIELDS = [
    "simulation_name", "min_dte", "max_dte", "max_spread_pct", "require_positive_volume",
    "candidate_count", "official_candidate_filter_unchanged",
]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "opend_port_reachable",
    "moomoo_quote_context_connected", "moomoo_quote_context_disconnected_cleanly",
    "real_readonly_quote_verified", "fallback_rows_used", "allowed_underlying_etf_count",
    "chain_fetch_attempted_underlying_count", "chain_fetch_success_underlying_count",
    "total_raw_contract_count", "total_dte_eligible_count", "total_valid_bid_count",
    "total_valid_ask_gt_bid_count", "total_valid_mid_count", "total_finite_spread_pct_count",
    "total_spread_pass_count", "total_volume_available_count", "total_volume_positive_count",
    "liquidity_candidate_count", "zero_candidate_root_cause_primary",
    "zero_candidate_root_cause_secondary", "field_mapping_issue_detected",
    "missing_volume_field_all_rows", "missing_bid_ask_field_all_rows",
    "quote_access_status_normalization_recommended", "trade_context_used", "unlock_trade_called",
    "place_order_called", "broker_action_allowed", "official_adoption_allowed", "research_only",
]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_dte(value: Any, asof: date = ASOF_DATE) -> int | None:
    if value in {"", None}:
        return None
    text = str(value)[:10]
    for fmt in ["iso", "%Y/%m/%d", "%Y%m%d"]:
        try:
            parsed = date.fromisoformat(text) if fmt == "iso" else datetime.strptime(str(value)[:8 if fmt == "%Y%m%d" else 10], fmt).date()
            return (parsed - asof).days
        except ValueError:
            continue
    return None


def first_present(row: dict[str, Any], names: list[str]) -> tuple[str, Any]:
    lowered = {str(k).lower(): k for k in row}
    for name in names:
        key = lowered.get(name.lower())
        if key is not None:
            return str(key), row.get(key)
    return "", None


def normalize_call_put(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"CALL", "C"} or "CALL" in text:
        return "CALL"
    if text in {"PUT", "P"} or "PUT" in text:
        return "PUT"
    return ""


def safe_log_dir(repo_root: Path) -> Path:
    return repo_root / "outputs" / "v22" / R1A_STAGE / "provider_logs"


def configure_safe_moomoo_environment(repo_root: Path) -> Path:
    log_dir = safe_log_dir(repo_root)
    env_root = log_dir.parent / "provider_env"
    userprofile = env_root / "userprofile"
    appdata = env_root / "AppData" / "Roaming"
    localappdata = env_root / "AppData" / "Local"
    for path in [log_dir, userprofile, appdata, localappdata]:
        path.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "FUTU_OPEND_LOG_DIR": str(log_dir),
        "MOOMOO_LOG_DIR": str(log_dir),
        "FUTU_LOG_DIR": str(log_dir),
        "FutuOpenD_LogDir": str(log_dir),
        "TMP": str(log_dir),
        "TEMP": str(log_dir),
        "USERPROFILE": str(userprofile),
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(localappdata),
    })
    return log_dir


def opend_port_reachable(host: str, port: int, timeout_seconds: float = 1.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def import_moomoo(import_func: Callable[[str], Any] | None = None) -> tuple[Any | None, bool, str]:
    try:
        return (import_func("moomoo") if import_func else importlib.import_module("moomoo")), True, ""
    except Exception as exc:  # noqa: BLE001
        return None, False, f"{type(exc).__name__}: {exc}"


def result_ok_data(result: Any) -> tuple[bool, Any]:
    if isinstance(result, tuple) and len(result) >= 2:
        code = result[0]
        ok = code == 0 or str(code).upper() in {"0", "RET_OK", "OK"}
        return ok, result[1]
    return result is not None, result


def data_to_rows(data: Any) -> list[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        records = data.to_dict("records")
        return [dict(row) for row in records if isinstance(row, dict)]
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, dict)]
    return []


def fetch_live_option_chains(moomoo: Any, host: str, port: int, underlyings: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bool | str]]:
    ctx = None
    state: dict[str, bool | str] = {"connected": False, "closed": False, "status": "QUOTE_CONTEXT_NOT_OPENED"}
    rows: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    try:
        ctx = moomoo.OpenQuoteContext(host=host, port=port)
        state["connected"] = True
        state["status"] = "QUOTE_CONTEXT_OPENED"
    except Exception as exc:  # noqa: BLE001
        state["status"] = f"QUOTE_CONTEXT_OPEN_FAILED:{type(exc).__name__}:{exc}"
        for underlying in underlyings:
            coverage.append({"underlying": underlying, "chain_fetch_attempted": False, "chain_fetch_succeeded": False, "raw_contract_count": 0, "expiry_count": 0, "min_dte": "", "max_dte": "", "dte_1_21_count": 0, "call_count": 0, "put_count": 0, "fetch_status": "QUOTE_CONTEXT_OPEN_FAILED", "error_type": type(exc).__name__, "error_message": str(exc)})
        return rows, coverage, state

    try:
        method = getattr(ctx, "get_option_chain", None)
        for underlying in underlyings:
            if method is None:
                coverage.append({"underlying": underlying, "chain_fetch_attempted": False, "chain_fetch_succeeded": False, "raw_contract_count": 0, "expiry_count": 0, "min_dte": "", "max_dte": "", "dte_1_21_count": 0, "call_count": 0, "put_count": 0, "fetch_status": "GET_OPTION_CHAIN_METHOD_MISSING", "error_type": "", "error_message": ""})
                continue
            try:
                ok, data = result_ok_data(method(code=f"US.{underlying}"))
                fetched = data_to_rows(data) if ok else []
                for row in fetched:
                    row["underlying"] = underlying
                    row["source"] = "MOOMOO_READ_ONLY_QUOTE"
                rows.extend(fetched)
                coverage.append(coverage_for_underlying(underlying, fetched, True, ok, "CHAIN_FETCH_OK" if ok else "CHAIN_FETCH_RET_NOT_OK", "", ""))
            except Exception as exc:  # noqa: BLE001
                coverage.append({"underlying": underlying, "chain_fetch_attempted": True, "chain_fetch_succeeded": False, "raw_contract_count": 0, "expiry_count": 0, "min_dte": "", "max_dte": "", "dte_1_21_count": 0, "call_count": 0, "put_count": 0, "fetch_status": "CHAIN_FETCH_EXCEPTION", "error_type": type(exc).__name__, "error_message": str(exc)})
    finally:
        close = getattr(ctx, "close", None)
        if close is not None:
            try:
                close()
                state["closed"] = True
            except Exception:
                state["closed"] = False
    return rows, coverage, state


def enriched_row(raw: dict[str, Any]) -> dict[str, Any]:
    bid_field, bid_value = first_present(raw, BID_FIELDS)
    ask_field, ask_value = first_present(raw, ASK_FIELDS)
    volume_field, volume_value = first_present(raw, VOLUME_FIELDS)
    expiry_field, expiry_value = first_present(raw, EXPIRY_FIELDS)
    cp_field, cp_value = first_present(raw, CALL_PUT_FIELDS)
    strike_field, strike_value = first_present(raw, STRIKE_FIELDS)
    contract_field, contract_value = first_present(raw, CONTRACT_ID_FIELDS)
    bid = numeric(bid_value)
    ask = numeric(ask_value)
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread_pct = ((ask - bid) / mid) if mid and mid > 0 and ask is not None and bid is not None else None
    dte = parse_dte(expiry_value)
    return {
        **raw,
        "_contract_id": contract_value or "",
        "_contract_field": contract_field,
        "_underlying": str(raw.get("underlying", "")).upper(),
        "_expiration": expiry_value or "",
        "_expiration_field": expiry_field,
        "_dte": dte,
        "_strike": strike_value if strike_field else "",
        "_strike_field": strike_field,
        "_call_put": normalize_call_put(cp_value),
        "_call_put_field": cp_field,
        "_bid": bid,
        "_bid_field": bid_field,
        "_ask": ask,
        "_ask_field": ask_field,
        "_mid": mid,
        "_spread_pct": spread_pct,
        "_volume": numeric(volume_value),
        "_volume_field": volume_field,
        "_open_interest": numeric(first_present(raw, OI_FIELDS)[1]),
        "_open_interest_field": first_present(raw, OI_FIELDS)[0],
        "_iv": numeric(first_present(raw, IV_FIELDS)[1]),
        "_iv_field": first_present(raw, IV_FIELDS)[0],
        "_delta": numeric(first_present(raw, DELTA_FIELDS)[1]),
        "_gamma": numeric(first_present(raw, GAMMA_FIELDS)[1]),
        "_theta": numeric(first_present(raw, THETA_FIELDS)[1]),
        "_vega": numeric(first_present(raw, VEGA_FIELDS)[1]),
        "_rho": numeric(first_present(raw, RHO_FIELDS)[1]),
    }


def enrich_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enriched_row(row) for row in raw_rows]


def coverage_for_underlying(underlying: str, rows: list[dict[str, Any]], attempted: bool, succeeded: bool, status: str, err_type: str, err_msg: str) -> dict[str, Any]:
    enriched = enrich_rows(rows)
    dtes = [row["_dte"] for row in enriched if row["_dte"] is not None]
    expiries = {row["_expiration"] for row in enriched if row["_expiration"]}
    return {
        "underlying": underlying,
        "chain_fetch_attempted": attempted,
        "chain_fetch_succeeded": succeeded,
        "raw_contract_count": len(rows),
        "expiry_count": len(expiries),
        "min_dte": min(dtes) if dtes else "",
        "max_dte": max(dtes) if dtes else "",
        "dte_1_21_count": sum(1 for dte in dtes if 1 <= dte <= 21),
        "call_count": sum(1 for row in enriched if row["_call_put"] == "CALL"),
        "put_count": sum(1 for row in enriched if row["_call_put"] == "PUT"),
        "fetch_status": status,
        "error_type": err_type,
        "error_message": err_msg,
    }


def build_coverage_from_rows(raw_rows: list[dict[str, Any]], underlyings: list[str] = ALLOWED_ETFS) -> list[dict[str, Any]]:
    return [coverage_for_underlying(underlying, [row for row in raw_rows if str(row.get("underlying", "")).upper() == underlying], True, any(str(row.get("underlying", "")).upper() == underlying for row in raw_rows), "CHAIN_FETCH_OK" if any(str(row.get("underlying", "")).upper() == underlying for row in raw_rows) else "CHAIN_EMPTY_OR_UNAVAILABLE", "", "") for underlying in underlyings]


def field_availability(enriched: list[dict[str, Any]], underlyings: list[str] = ALLOWED_ETFS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for underlying in underlyings:
        subset = [row for row in enriched if row["_underlying"] == underlying]
        raw_fields = sorted({str(key) for row in subset for key in row.keys() if not str(key).startswith("_")})
        count = len(subset)
        bid_count = sum(1 for row in subset if row["_bid"] is not None)
        ask_count = sum(1 for row in subset if row["_ask"] is not None)
        vol_count = sum(1 for row in subset if row["_volume"] is not None)
        bid_field_found = any(row["_bid_field"] for row in subset)
        ask_field_found = any(row["_ask_field"] for row in subset)
        missing_bid_ask = count > 0 and (not bid_field_found or not ask_field_found)
        rows.append({
            "underlying": underlying,
            "raw_contract_count": count,
            "raw_field_names": ";".join(raw_fields),
            "bid_field_found": bid_field_found,
            "ask_field_found": ask_field_found,
            "expiration_field_found": any(row["_expiration_field"] for row in subset),
            "volume_field_found": any(row["_volume_field"] for row in subset),
            "open_interest_field_found": any(row["_open_interest_field"] for row in subset),
            "iv_field_found": any(row["_iv_field"] for row in subset),
            "delta_field_found": any("_delta" in row and row["_delta"] is not None for row in subset),
            "gamma_field_found": any("_gamma" in row and row["_gamma"] is not None for row in subset),
            "theta_field_found": any("_theta" in row and row["_theta"] is not None for row in subset),
            "vega_field_found": any("_vega" in row and row["_vega"] is not None for row in subset),
            "bid_available_count": bid_count,
            "ask_available_count": ask_count,
            "mid_available_count": sum(1 for row in subset if row["_mid"] is not None),
            "spread_pct_available_count": sum(1 for row in subset if row["_spread_pct"] is not None),
            "volume_available_count": vol_count,
            "open_interest_available_count": sum(1 for row in subset if row["_open_interest"] is not None),
            "iv_available_count": sum(1 for row in subset if row["_iv"] is not None),
            "greeks_complete_count": sum(1 for row in subset if all(row[f] is not None for f in ["_delta", "_gamma", "_theta", "_vega"])),
            "field_mapping_issue_detected": missing_bid_ask,
            "missing_volume_field_all_rows": count > 0 and vol_count == 0,
            "missing_bid_ask_field_all_rows": count > 0 and bid_count == 0 and ask_count == 0,
        })
    return rows


def filter_sets(enriched: list[dict[str, Any]], min_dte: int, max_dte: int, max_spread_pct: float, require_positive_volume: bool = False) -> list[list[dict[str, Any]]]:
    allowed = [row for row in enriched if row["_underlying"] in ALLOWED_ETFS]
    chain = allowed
    dte = [row for row in chain if row["_dte"] is not None and min_dte <= row["_dte"] <= max_dte]
    bid = [row for row in dte if row["_bid"] is not None and row["_bid"] > 0]
    ask = [row for row in bid if row["_ask"] is not None and row["_ask"] > row["_bid"]]
    mid = [row for row in ask if row["_mid"] is not None and row["_mid"] > 0]
    spread = [row for row in mid if row["_spread_pct"] is not None]
    spread_pass = [row for row in spread if row["_spread_pct"] <= max_spread_pct]
    if require_positive_volume:
        volume_pass = [row for row in spread_pass if row["_volume"] is not None and row["_volume"] > 0]
    else:
        volume_pass = [row for row in spread_pass if row["_volume"] is None or row["_volume"] > 0]
    return [allowed, chain, dte, bid, ask, mid, spread, spread_pass, volume_pass, volume_pass]


def build_funnel(enriched: list[dict[str, Any]], min_dte: int = 1, max_dte: int = 21, max_spread_pct: float = 0.30) -> list[dict[str, Any]]:
    names = [
        ("allowed ETF whitelist", "NON_ALLOWED_UNDERLYING", "ETF whitelist gate"),
        ("option chain fetched", "CHAIN_EMPTY_OR_UNAVAILABLE", "Rows returned by read-only chain fetch"),
        ("DTE between 1 and 21", "DTE_OUT_OF_RANGE_OR_MISSING", f"Official min_dte={min_dte}, max_dte={max_dte}"),
        ("bid > 0", "ZERO_OR_MISSING_BID", "Official bid gate"),
        ("ask > bid", "ASK_NOT_GREATER_THAN_BID_OR_MISSING", "Official ask gate"),
        ("mid > 0", "INVALID_MID", "Derived from bid/ask"),
        ("finite spread_pct", "INVALID_SPREAD_PCT", "Derived from bid/ask/mid"),
        ("spread_pct <= max_spread_pct", "WIDE_SPREAD", f"Official max_spread_pct={max_spread_pct}"),
        ("volume > 0 when available", "LOW_OR_ZERO_VOLUME", "Official volume gate ignores missing volume"),
        ("final liquidity candidate", "FINAL_FILTERED_OUT", "Official R2 diagnostic mirror of V22.041 R1"),
    ]
    sets = filter_sets(enriched, min_dte, max_dte, max_spread_pct, require_positive_volume=False)
    rows = []
    previous = len(enriched)
    for index, ((name, reason, note), surviving) in enumerate(zip(names, sets), start=1):
        count = len(surviving)
        rows.append({"step_order": index, "filter_step": name, "surviving_count": count, "dropped_count": max(previous - count, 0), "drop_reason": reason, "official_filter": True, "notes": note})
        previous = count
    return rows


def relaxed_simulations(enriched: list[dict[str, Any]], min_dte: int, max_dte: int, max_spread_pct: float, relaxed_max_spread_pct: float) -> list[dict[str, Any]]:
    sims = [
        ("official_filters", min_dte, max_dte, max_spread_pct, False),
        ("relaxed_spread_only", min_dte, max_dte, relaxed_max_spread_pct, False),
        ("relaxed_dte_and_spread", 0, 60, relaxed_max_spread_pct, False),
        ("require_positive_volume_diagnostic", min_dte, max_dte, max_spread_pct, True),
    ]
    rows = []
    for name, lo, hi, spread, req_vol in sims:
        rows.append({"simulation_name": name, "min_dte": lo, "max_dte": hi, "max_spread_pct": spread, "require_positive_volume": req_vol, "candidate_count": len(filter_sets(enriched, lo, hi, spread, req_vol)[-1]), "official_candidate_filter_unchanged": True})
    return rows


def classify_root_causes(enriched: list[dict[str, Any]], coverage: list[dict[str, Any]], field_rows: list[dict[str, Any]], funnel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_raw = len(enriched)
    by_step = {row["filter_step"]: int(row["surviving_count"]) for row in funnel}
    missing_volume_all = total_raw > 0 and sum(1 for row in enriched if row["_volume"] is not None) == 0
    missing_bid_ask_all = total_raw > 0 and sum(1 for row in enriched if row["_bid"] is not None or row["_ask"] is not None) == 0
    field_mapping = missing_bid_ask_all or any(bool(row["field_mapping_issue_detected"]) for row in field_rows)
    causes: list[tuple[str, str, int, str, str]] = []
    empty_underlyings = [row["underlying"] for row in coverage if int(row["raw_contract_count"]) == 0]
    if total_raw == 0:
        causes.append(("CHAIN_EMPTY_OR_UNAVAILABLE", "ALL", len(ALLOWED_ETFS), "All ETF option chains returned zero rows.", "Confirm option-chain entitlement and market/session availability."))
    if field_mapping:
        causes.append(("FIELD_MAPPING_ISSUE", "ALL" if missing_bid_ask_all else "", total_raw, "Bid/ask values are absent under known aliases; raw schema likely differs from V22.041 mapping.", "Inspect live_option_field_availability_audit.csv raw_field_names and add mappings in a later repair."))
    if missing_volume_all:
        causes.append(("FIELD_MISSING_VOLUME", "ALL", total_raw, "Volume field is missing for all live rows; classify separately from LOW_VOLUME.", "Inspect raw schema for a volume alias before using volume as an eliminator."))
    ordered_steps = [
        ("DTE_FILTER_ELIMINATED_ALL", "DTE between 1 and 21", "All rows were eliminated by official DTE range."),
        ("BID_FILTER_ELIMINATED_ALL", "bid > 0", "All DTE-eligible rows were eliminated by bid gate."),
        ("BID_ASK_FILTER_ELIMINATED_ALL", "ask > bid", "All rows with positive bid were eliminated by ask > bid gate."),
        ("SPREAD_FIELD_OR_CALCULATION_UNAVAILABLE", "finite spread_pct", "No finite spread_pct survived because bid/ask/mid data was unavailable."),
        ("SPREAD_FILTER_ELIMINATED_ALL", "spread_pct <= max_spread_pct", "All finite-spread rows failed max spread filter."),
        ("VOLUME_FILTER_ELIMINATED_ALL", "volume > 0 when available", "Rows with available volume failed positive-volume gate."),
    ]
    previous = total_raw
    for code, step, detail in ordered_steps:
        current = by_step.get(step, 0)
        if total_raw > 0 and previous > 0 and current == 0:
            if code == "VOLUME_FILTER_ELIMINATED_ALL" and missing_volume_all:
                continue
            causes.append((code, "", previous, detail, "Use funnel and relaxed simulation to assess whether strategy thresholds need later review."))
            break
        previous = current
    if not causes and by_step.get("final liquidity candidate", 0) == 0:
        causes.append(("ZERO_CANDIDATE_CAUSE_UNRESOLVED", "", total_raw, "No single eliminator was isolated by the cumulative funnel.", "Review per-underlying field and funnel outputs."))
    if total_raw > 0 and empty_underlyings:
        causes.append(("CHAIN_EMPTY_OR_UNAVAILABLE", ";".join(empty_underlyings), len(empty_underlyings), "One or more ETF option chains returned zero rows.", "Confirm per-underlying option-chain availability."))
    if not causes:
        causes.append(("NO_ZERO_CANDIDATE_FAILURE", "", by_step.get("final liquidity candidate", 0), "Official filters produced candidates.", "No zero-candidate repair needed."))
    return [{"root_cause_rank": i, "root_cause_code": code, "underlying": underlying, "evidence_count": count, "evidence_detail": detail, "recommended_next_action": action} for i, (code, underlying, count, detail, action) in enumerate(causes, start=1)]


def previous_quote_normalization_recommended(repo_root: Path) -> bool:
    payload = read_json(repo_root / V22_041_SUMMARY_REL)
    return payload.get("quote_access_status") == "READ_ONLY_QUOTE_ATTEMPTED" and payload.get("real_readonly_quote_verified") is True


def build_summary(
    execution_mode: str,
    opend_reachable: bool,
    quote_state: dict[str, bool | str],
    coverage: list[dict[str, Any]],
    enriched: list[dict[str, Any]],
    field_rows: list[dict[str, Any]],
    funnel: list[dict[str, Any]],
    root_rows: list[dict[str, Any]],
    normalization_recommended: bool,
) -> dict[str, Any]:
    by_step = {row["filter_step"]: int(row["surviving_count"]) for row in funnel}
    total_raw = len(enriched)
    verified = bool(quote_state.get("connected")) and total_raw > 0
    final_status = PASS_STATUS if verified else WARN_STATUS
    primary = root_rows[0]["root_cause_code"] if root_rows else ""
    secondary = root_rows[1]["root_cause_code"] if len(root_rows) > 1 else ""
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "generated_at_utc": utc_now_text(),
        "final_status": final_status,
        "final_decision": READY_DECISION if root_rows else BLOCKED_DECISION,
        "execution_mode": execution_mode,
        "opend_port_reachable": opend_reachable,
        "moomoo_quote_context_connected": bool(quote_state.get("connected")),
        "moomoo_quote_context_disconnected_cleanly": bool(quote_state.get("closed")),
        "real_readonly_quote_verified": verified,
        "fallback_rows_used": False,
        "allowed_underlying_etf_count": len(ALLOWED_ETFS),
        "chain_fetch_attempted_underlying_count": sum(1 for row in coverage if bool(row["chain_fetch_attempted"])),
        "chain_fetch_success_underlying_count": sum(1 for row in coverage if bool(row["chain_fetch_succeeded"])),
        "total_raw_contract_count": total_raw,
        "total_dte_eligible_count": by_step.get("DTE between 1 and 21", 0),
        "total_valid_bid_count": by_step.get("bid > 0", 0),
        "total_valid_ask_gt_bid_count": by_step.get("ask > bid", 0),
        "total_valid_mid_count": by_step.get("mid > 0", 0),
        "total_finite_spread_pct_count": by_step.get("finite spread_pct", 0),
        "total_spread_pass_count": by_step.get("spread_pct <= max_spread_pct", 0),
        "total_volume_available_count": sum(1 for row in enriched if row["_volume"] is not None),
        "total_volume_positive_count": sum(1 for row in enriched if row["_volume"] is not None and row["_volume"] > 0),
        "liquidity_candidate_count": by_step.get("final liquidity candidate", 0),
        "zero_candidate_root_cause_primary": primary,
        "zero_candidate_root_cause_secondary": secondary,
        "field_mapping_issue_detected": any(bool(row["field_mapping_issue_detected"]) for row in field_rows),
        "missing_volume_field_all_rows": total_raw > 0 and sum(1 for row in enriched if row["_volume"] is not None) == 0,
        "missing_bid_ask_field_all_rows": total_raw > 0 and sum(1 for row in enriched if row["_bid"] is not None or row["_ask"] is not None) == 0,
        "quote_access_status_normalization_recommended": normalization_recommended,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.041 R2 Live Option Chain Coverage And Zero Candidate Diagnostic", *[f"{key}={summary.get(key)}" for key in SUMMARY_FIELDS]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    host: str = "127.0.0.1",
    port: int = 18441,
    min_dte: int = 1,
    max_dte: int = 21,
    max_spread_pct: float = 0.30,
    relaxed_max_spread_pct: float = 1.00,
    import_func: Callable[[str], Any] | None = None,
    injected_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_safe_moomoo_environment(repo_root)
    coverage: list[dict[str, Any]]
    raw_rows: list[dict[str, Any]]
    quote_state: dict[str, bool | str] = {"connected": False, "closed": False, "status": "NOT_EXECUTED"}
    reachable = False

    if injected_rows is not None:
        raw_rows = [dict(row) for row in injected_rows]
        coverage = build_coverage_from_rows(raw_rows)
        quote_state = {"connected": True, "closed": True, "status": "INJECTED_TEST_ROWS"}
        reachable = True
    elif execute:
        reachable, reach_error = opend_port_reachable(host, port)
        if reachable:
            moomoo, ok, error = import_moomoo(import_func)
            if ok:
                raw_rows, coverage, quote_state = fetch_live_option_chains(moomoo, host, port, ALLOWED_ETFS)
            else:
                raw_rows = []
                quote_state = {"connected": False, "closed": False, "status": f"MOOMOO_IMPORT_FAILED:{error}"}
                coverage = [{"underlying": u, "chain_fetch_attempted": False, "chain_fetch_succeeded": False, "raw_contract_count": 0, "expiry_count": 0, "min_dte": "", "max_dte": "", "dte_1_21_count": 0, "call_count": 0, "put_count": 0, "fetch_status": "MOOMOO_IMPORT_FAILED", "error_type": error.split(":", 1)[0], "error_message": error} for u in ALLOWED_ETFS]
        else:
            raw_rows = []
            quote_state = {"connected": False, "closed": False, "status": f"OPEND_PORT_UNREACHABLE:{reach_error}"}
            coverage = [{"underlying": u, "chain_fetch_attempted": False, "chain_fetch_succeeded": False, "raw_contract_count": 0, "expiry_count": 0, "min_dte": "", "max_dte": "", "dte_1_21_count": 0, "call_count": 0, "put_count": 0, "fetch_status": "OPEND_PORT_UNREACHABLE", "error_type": reach_error.split(":", 1)[0], "error_message": reach_error} for u in ALLOWED_ETFS]
    else:
        raw_rows = []
        coverage = [{"underlying": u, "chain_fetch_attempted": False, "chain_fetch_succeeded": False, "raw_contract_count": 0, "expiry_count": 0, "min_dte": "", "max_dte": "", "dte_1_21_count": 0, "call_count": 0, "put_count": 0, "fetch_status": "PLAN_MODE_NOT_FETCHED", "error_type": "", "error_message": ""} for u in ALLOWED_ETFS]

    enriched = enrich_rows(raw_rows)
    field_rows = field_availability(enriched)
    funnel = build_funnel(enriched, min_dte, max_dte, max_spread_pct)
    roots = classify_root_causes(enriched, coverage, field_rows, funnel)
    relaxed = relaxed_simulations(enriched, min_dte, max_dte, max_spread_pct, relaxed_max_spread_pct)
    summary = build_summary("EXECUTE_READ_ONLY" if execute else "PLAN", reachable, quote_state, coverage, enriched, field_rows, funnel, roots, previous_quote_normalization_recommended(repo_root))

    write_csv(output_dir / "live_option_chain_coverage_by_underlying.csv", COVERAGE_FIELDS, coverage)
    write_csv(output_dir / "live_option_field_availability_audit.csv", FIELD_FIELDS, field_rows)
    write_csv(output_dir / "live_option_filter_funnel.csv", FUNNEL_FIELDS, funnel)
    write_csv(output_dir / "live_option_zero_candidate_root_cause.csv", ROOT_FIELDS, roots)
    write_csv(output_dir / "live_option_relaxed_filter_simulation.csv", RELAXED_FIELDS, relaxed)
    write_json(output_dir / "v22_041_r2_summary.json", summary)
    (output_dir / "V22.041_R2_live_option_chain_coverage_and_zero_candidate_diagnostic_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    parser.add_argument("--min-dte", type=int, default=1)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--max-spread-pct", type=float, default=0.30)
    parser.add_argument("--relaxed-max-spread-pct", type=float, default=1.00)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.host, args.port, args.min_dte, args.max_dte, args.max_spread_pct, args.relaxed_max_spread_pct)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_041_r2_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
