#!/usr/bin/env python
"""V22.041 R3 live option quote enrichment from option-chain codes.

Research-only stage that fetches ETF option-chain metadata, selects a bounded
DTE-eligible target set, enriches option codes with read-only quote snapshots,
and applies the V22.041 liquidity filters to enriched rows only.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import os
import socket
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable


MODULE_ID = "V22.041_R3"
MODULE_NAME = "LIVE_OPTION_QUOTE_ENRICHMENT_FROM_CHAIN_CODES"
STAGE = "V22.041_R3_LIVE_OPTION_QUOTE_ENRICHMENT_FROM_CHAIN_CODES"
OUT_REL = Path("outputs") / "v22" / STAGE
R1A_STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"

PASS_STATUS = "PASS_V22_041_R3_LIVE_OPTION_QUOTE_ENRICHMENT_READY"
WARN_ZERO_STATUS = "WARN_V22_041_R3_QUOTE_ENRICHED_BUT_ZERO_LIQUIDITY_CANDIDATES"
WARN_MAPPING_STATUS = "WARN_V22_041_R3_QUOTE_ENRICHMENT_BID_ASK_MAPPING_FAILED"
WARN_UNAVAILABLE_STATUS = "WARN_V22_041_R3_LIVE_OPTION_QUOTE_UNAVAILABLE"
READY_DECISION = "LIVE_OPTION_QUOTE_ENRICHMENT_READY_FOR_V22_041_INTEGRATION_RESEARCH_ONLY"
ZERO_DECISION = "LIVE_OPTION_QUOTE_ENRICHED_ZERO_CANDIDATES_REVIEW_FILTERS_RESEARCH_ONLY"
BLOCKED_DECISION = "LIVE_OPTION_QUOTE_ENRICHMENT_NOT_READY_RESEARCH_ONLY"

ALLOWED_ETFS = ["SOXX", "SOXL", "SOXS", "QQQ", "TQQQ", "SQQQ", "SPY"]
ASOF_DATE = date(2026, 7, 8)

CODE_FIELDS = ["code", "option_code", "contract_id", "symbol"]
EXPIRY_FIELDS = ["strike_time", "expiration", "expiry", "expiry_date", "expiration_date"]
STRIKE_FIELDS = ["strike_price", "strike", "strikePrice"]
CALL_PUT_FIELDS = ["option_type", "call_put", "type", "contract_type"]
SPOT_FIELDS = ["last_price", "last", "price", "cur_price", "close", "prev_close_price"]
QUOTE_ALIASES = {
    "bid": ["bid", "bid_price", "bidPrice", "best_bid", "bestBid", "bid1", "bid_1"],
    "ask": ["ask", "ask_price", "askPrice", "best_ask", "bestAsk", "ask1", "ask_1"],
    "last_price": ["last_price", "last", "price", "cur_price", "close"],
    "volume": ["volume", "vol", "trade_volume", "option_volume"],
    "open_interest": ["open_interest", "openInterest", "oi", "option_open_interest"],
    "implied_volatility": ["implied_volatility", "impliedVolatility", "iv", "implied_vol", "option_implied_volatility"],
    "delta": ["delta"],
    "gamma": ["gamma"],
    "theta": ["theta"],
    "vega": ["vega"],
    "quote_time": ["quote_time", "time", "data_time", "update_time", "timestamp"],
}

METADATA_FIELDS = [
    "option_code", "underlying", "expiration", "dte", "strike", "call_put",
    "raw_code", "raw_option_type", "raw_strike_time", "raw_strike_price", "raw_field_names",
]
TARGET_FIELDS = [
    "target_rank", "option_code", "underlying", "expiration", "dte", "strike", "call_put",
    "underlying_spot", "selection_distance", "selection_reason",
]
ENRICHED_FIELDS = [
    "option_code", "underlying", "expiration", "dte", "strike", "call_put", "bid", "ask",
    "mid", "spread", "spread_pct", "volume", "open_interest", "implied_volatility",
    "delta", "gamma", "theta", "vega", "last_price", "quote_time", "quote_status",
    "warning_fields",
]
BATCH_FIELDS = [
    "batch_id", "requested_count", "returned_count", "method_used", "fetch_succeeded",
    "fetch_status", "error_type", "error_message",
]
FIELD_AUDIT_FIELDS = [
    "canonical_field", "mapped", "mapped_provider_field", "available_count", "missing_count",
    "warning_only", "mapping_status",
]
CANDIDATE_FIELDS = ENRICHED_FIELDS + ["liquidity_status", "broker_action_allowed", "official_adoption_allowed", "research_only"]
REJECT_FIELDS = ENRICHED_FIELDS + ["reject_reason", "broker_action_allowed", "official_adoption_allowed", "research_only"]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "opend_port_reachable",
    "moomoo_quote_context_connected", "moomoo_quote_context_disconnected_cleanly",
    "real_readonly_quote_verified", "fallback_rows_used", "allowed_underlying_etf_count",
    "chain_fetch_attempted_underlying_count", "chain_fetch_success_underlying_count",
    "total_raw_contract_count", "total_dte_eligible_count", "enrichment_target_count",
    "enrichment_attempted_count", "enrichment_success_count", "enrichment_failed_count",
    "enrichment_batch_count", "enrichment_success_batch_count", "enrichment_failed_batch_count",
    "bid_field_mapped", "ask_field_mapped", "volume_field_mapped", "open_interest_field_mapped",
    "iv_field_mapped", "greeks_field_mapped", "valid_bid_ask_count", "valid_mid_count",
    "finite_spread_pct_count", "spread_pass_count", "volume_positive_count",
    "liquidity_candidate_count", "quote_enrichment_root_cause_if_zero", "trade_context_used",
    "unlock_trade_called", "place_order_called", "broker_action_allowed",
    "official_adoption_allowed", "research_only",
]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def first_present(row: dict[str, Any], aliases: list[str]) -> tuple[str, Any]:
    lower = {str(key).lower(): key for key in row}
    for alias in aliases:
        key = lower.get(alias.lower())
        if key is not None:
            return str(key), row.get(key)
    return "", None


def parse_dte(value: Any, asof: date = ASOF_DATE) -> int | None:
    if value in {"", None}:
        return None
    text = str(value)
    for raw, fmt in [(text[:10], "iso"), (text[:10], "%Y/%m/%d"), (text[:8], "%Y%m%d")]:
        try:
            parsed = date.fromisoformat(raw) if fmt == "iso" else datetime.strptime(raw, fmt).date()
            return (parsed - asof).days
        except ValueError:
            continue
    return None


def normalize_call_put(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"CALL", "C"} or "CALL" in text:
        return "CALL"
    if text in {"PUT", "P"} or "PUT" in text:
        return "PUT"
    return ""


def data_to_rows(data: Any) -> list[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        return [dict(row) for row in data.to_dict("records") if isinstance(row, dict)]
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, dict)]
    return []


def result_ok_data(result: Any) -> tuple[bool, Any]:
    if isinstance(result, tuple) and len(result) >= 2:
        code = result[0]
        return code == 0 or str(code).upper() in {"0", "RET_OK", "OK"}, result[1]
    return result is not None, result


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        raise ValueError("BatchSize must be positive")
    return [items[i:i + size] for i in range(0, len(items), size)]


def configure_safe_moomoo_environment(repo_root: Path) -> Path:
    log_dir = repo_root / "outputs" / "v22" / R1A_STAGE / "provider_logs"
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


def metadata_from_chain_rows(chain_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for raw in chain_rows:
        code_field, code = first_present(raw, CODE_FIELDS)
        expiry_field, expiry = first_present(raw, EXPIRY_FIELDS)
        strike_field, strike = first_present(raw, STRIKE_FIELDS)
        cp_field, cp = first_present(raw, CALL_PUT_FIELDS)
        underlying = str(raw.get("underlying", "")).upper()
        dte = parse_dte(expiry)
        out.append({
            "option_code": code or "",
            "underlying": underlying,
            "expiration": expiry or "",
            "dte": "" if dte is None else dte,
            "strike": "" if numeric(strike) is None else numeric(strike),
            "call_put": normalize_call_put(cp),
            "raw_code": code or "",
            "raw_option_type": cp or "",
            "raw_strike_time": expiry or "",
            "raw_strike_price": strike or "",
            "raw_field_names": ";".join(sorted(str(k) for k in raw.keys())),
            "_code_field": code_field,
            "_expiry_field": expiry_field,
            "_strike_field": strike_field,
            "_cp_field": cp_field,
        })
    return out


def median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def dte_eligible(row: dict[str, Any], include_zero_dte: bool, min_dte: int = 1, max_dte: int = 21) -> bool:
    dte = numeric(row.get("dte"))
    if dte is None:
        return False
    lower = 0 if include_zero_dte else min_dte
    return lower <= dte <= max_dte


def select_enrichment_targets(metadata: list[dict[str, Any]], max_contracts: int = 1000, include_zero_dte: bool = False, spot_by_underlying: dict[str, float | None] | None = None) -> list[dict[str, Any]]:
    spot_by_underlying = spot_by_underlying or {}
    eligible = [row for row in metadata if row.get("underlying") in ALLOWED_ETFS and row.get("option_code") and dte_eligible(row, include_zero_dte)]
    medians = {
        underlying: median([numeric(row.get("strike")) for row in eligible if row.get("underlying") == underlying and numeric(row.get("strike")) is not None] or [])
        for underlying in ALLOWED_ETFS
    }
    ranked = []
    for row in eligible:
        strike = numeric(row.get("strike"))
        spot = spot_by_underlying.get(str(row.get("underlying")))
        center = spot if spot is not None else medians.get(str(row.get("underlying")))
        distance = abs(strike - center) if strike is not None and center is not None else 999999999.0
        reason = "NEAR_THE_MONEY_BY_UNDERLYING_SPOT" if spot is not None else "CLOSEST_TO_CHAIN_MEDIAN_STRIKE"
        ranked.append((str(row.get("underlying")), numeric(row.get("dte")) or 9999, distance, 0 if row.get("call_put") == "CALL" else 1, str(row.get("option_code")), row, reason))
    ranked.sort(key=lambda item: item[:5])
    selected = []
    seen_codes = set()
    # First pass seeds call/put representation per underlying before filling by rank.
    for underlying in ALLOWED_ETFS:
        for cp in ["CALL", "PUT"]:
            match = next((item for item in ranked if item[0] == underlying and item[5].get("call_put") == cp and str(item[5].get("option_code")) not in seen_codes), None)
            if match is not None:
                selected.append((match, match[6]))
                seen_codes.add(str(match[5].get("option_code")))
                if len(selected) >= max_contracts:
                    break
        if len(selected) >= max_contracts:
            break
    for item in ranked:
        code = str(item[5].get("option_code"))
        if len(selected) >= max_contracts:
            break
        if code not in seen_codes:
            selected.append((item, item[6]))
            seen_codes.add(code)
    targets = []
    for rank, (item, reason) in enumerate(selected[:max_contracts], start=1):
        row = dict(item[5])
        row.update({
            "target_rank": rank,
            "underlying_spot": "" if spot_by_underlying.get(row["underlying"]) is None else spot_by_underlying[row["underlying"]],
            "selection_distance": round(item[2], 6) if item[2] < 999999999 else "",
            "selection_reason": reason,
        })
        targets.append(row)
    return targets


def normalize_quote_row(meta: dict[str, Any], quote: dict[str, Any], status: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    field_names: dict[str, str] = {}
    for field, aliases in QUOTE_ALIASES.items():
        mapped, value = first_present(quote, aliases)
        field_names[field] = mapped
        values[field] = value
    bid = numeric(values["bid"])
    ask = numeric(values["ask"])
    last_price = numeric(values["last_price"])
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    spread = ask - bid if bid is not None and ask is not None else None
    spread_pct = spread / mid if mid and mid > 0 and spread is not None else None
    warnings = []
    for field in ["volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"]:
        if numeric(values.get(field)) is None:
            warnings.append(field)
    if bid is None or ask is None:
        warnings.append("bid_ask")
    return {
        "option_code": meta.get("option_code", ""),
        "underlying": meta.get("underlying", ""),
        "expiration": meta.get("expiration", ""),
        "dte": meta.get("dte", ""),
        "strike": meta.get("strike", ""),
        "call_put": meta.get("call_put", ""),
        "bid": "" if bid is None else bid,
        "ask": "" if ask is None else ask,
        "mid": "" if mid is None else round(mid, 8),
        "spread": "" if spread is None else round(spread, 8),
        "spread_pct": "" if spread_pct is None else round(spread_pct, 8),
        "volume": "" if numeric(values["volume"]) is None else numeric(values["volume"]),
        "open_interest": "" if numeric(values["open_interest"]) is None else numeric(values["open_interest"]),
        "implied_volatility": "" if numeric(values["implied_volatility"]) is None else numeric(values["implied_volatility"]),
        "delta": "" if numeric(values["delta"]) is None else numeric(values["delta"]),
        "gamma": "" if numeric(values["gamma"]) is None else numeric(values["gamma"]),
        "theta": "" if numeric(values["theta"]) is None else numeric(values["theta"]),
        "vega": "" if numeric(values["vega"]) is None else numeric(values["vega"]),
        "last_price": "" if last_price is None else last_price,
        "quote_time": values["quote_time"] or utc_now_text(),
        "quote_status": status,
        "warning_fields": ";".join(sorted(set(warnings))),
        "_mapped_fields": field_names,
    }


def split_liquidity(enriched: list[dict[str, Any]], max_spread_pct: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = []
    rejects = []
    for row in enriched:
        reasons = []
        bid = numeric(row.get("bid"))
        ask = numeric(row.get("ask"))
        mid = numeric(row.get("mid"))
        spread_pct = numeric(row.get("spread_pct"))
        volume = numeric(row.get("volume"))
        if bid is None or ask is None:
            reasons.append("QUOTE_ENRICHMENT_BID_ASK_MISSING")
        else:
            if bid <= 0:
                reasons.append("ZERO_OR_NEGATIVE_BID")
            if ask <= bid:
                reasons.append("ASK_NOT_GREATER_THAN_BID")
        if mid is None or mid <= 0:
            reasons.append("INVALID_MID")
        if spread_pct is None:
            reasons.append("INVALID_SPREAD_PCT")
        elif spread_pct > max_spread_pct:
            reasons.append("WIDE_SPREAD")
        if volume is not None and volume <= 0:
            reasons.append("LOW_OR_ZERO_VOLUME")
        if reasons:
            rejects.append({**row, "reject_reason": ";".join(reasons), "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
        else:
            candidates.append({**row, "liquidity_status": "R3_LIQUIDITY_FILTER_PASS", "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True})
    return candidates, rejects


def field_mapping_audit(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for field in ["bid", "ask", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"]:
        mapped_fields = sorted({row.get("_mapped_fields", {}).get(field, "") for row in enriched if row.get("_mapped_fields", {}).get(field, "")})
        available = sum(1 for row in enriched if numeric(row.get(field)) is not None)
        warning_only = field not in {"bid", "ask"}
        rows.append({
            "canonical_field": field,
            "mapped": bool(mapped_fields),
            "mapped_provider_field": ";".join(mapped_fields),
            "available_count": available,
            "missing_count": max(len(enriched) - available, 0),
            "warning_only": warning_only,
            "mapping_status": "MAPPED" if mapped_fields else ("WARNING_FIELD_MISSING" if warning_only else "REQUIRED_FIELD_MISSING"),
        })
    return rows


def fetch_underlying_spots(ctx: Any, underlyings: list[str]) -> dict[str, float | None]:
    method = getattr(ctx, "get_market_snapshot", None)
    if method is None:
        return {u: None for u in underlyings}
    try:
        ok, data = result_ok_data(method([f"US.{u}" for u in underlyings]))
    except Exception:
        return {u: None for u in underlyings}
    rows = data_to_rows(data) if ok else []
    by_code = {str(row.get("code", "")).upper(): row for row in rows}
    spots = {}
    for u in underlyings:
        row = by_code.get(f"US.{u}", {})
        spots[u] = next((numeric(first_present(row, [field])[1]) for field in SPOT_FIELDS if numeric(first_present(row, [field])[1]) is not None), None)
    return spots


def fetch_chains(ctx: Any, underlyings: list[str]) -> tuple[list[dict[str, Any]], int, int]:
    rows = []
    attempted = 0
    succeeded = 0
    method = getattr(ctx, "get_option_chain", None)
    if method is None:
        return rows, attempted, succeeded
    for underlying in underlyings:
        attempted += 1
        try:
            ok, data = result_ok_data(method(code=f"US.{underlying}"))
            fetched = data_to_rows(data) if ok else []
            if ok:
                succeeded += 1
            for row in fetched:
                row["underlying"] = underlying
            rows.extend(fetched)
        except Exception:
            continue
    return rows, attempted, succeeded


def fetch_quote_batches(ctx: Any, targets: list[dict[str, Any]], batch_size: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quote_by_code: dict[str, dict[str, Any]] = {}
    audits = []
    methods = ["get_market_snapshot", "get_stock_quote", "get_option_snapshot"]
    for batch_id, batch in enumerate(chunks(targets, batch_size), start=1):
        codes = [str(row["option_code"]) for row in batch]
        method_used = ""
        returned = 0
        error = ""
        succeeded = False
        for method_name in methods:
            method = getattr(ctx, method_name, None)
            if method is None:
                continue
            try:
                ok, data = result_ok_data(method(codes))
                rows = data_to_rows(data) if ok else []
                if ok:
                    method_used = method_name
                    returned = len(rows)
                    succeeded = True
                    for row in rows:
                        code = str(first_present(row, CODE_FIELDS)[1] or row.get("code", ""))
                        if code:
                            quote_by_code[code] = row
                    break
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
        audits.append({"batch_id": batch_id, "requested_count": len(batch), "returned_count": returned, "method_used": method_used, "fetch_succeeded": succeeded, "fetch_status": "FETCH_SUCCEEDED" if succeeded else "FETCH_FAILED", "error_type": error.split(":", 1)[0] if error else "", "error_message": error})
    enriched = [normalize_quote_row(meta, quote_by_code.get(str(meta["option_code"]), {}), "QUOTE_FETCHED_READ_ONLY" if str(meta["option_code"]) in quote_by_code else "QUOTE_ROW_NOT_RETURNED") for meta in targets]
    return enriched, audits


def plan_outputs(max_contracts: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    metadata: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    enriched: list[dict[str, Any]] = []
    audit = [{"batch_id": "", "requested_count": 0, "returned_count": 0, "method_used": "", "fetch_succeeded": False, "fetch_status": "PLAN_MODE_NOT_FETCHED", "error_type": "", "error_message": ""}]
    return metadata, targets[:max_contracts], enriched, audit, 0, 0


def root_cause(enriched: list[dict[str, Any]], candidates: list[dict[str, Any]], field_audit: list[dict[str, Any]]) -> str:
    if candidates:
        return ""
    if not enriched:
        return "QUOTE_ENRICHMENT_NO_ROWS"
    mapped = {row["canonical_field"]: bool(row["mapped"]) for row in field_audit}
    if not mapped.get("bid") or not mapped.get("ask"):
        return "QUOTE_ENRICHMENT_BID_ASK_MISSING"
    if not mapped.get("volume"):
        return "QUOTE_ENRICHMENT_VOLUME_MISSING"
    return "QUOTE_ENRICHED_ZERO_LIQUIDITY_CANDIDATES"


def build_summary(
    execution_mode: str,
    reachable: bool,
    connected: bool,
    closed: bool,
    metadata: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    enriched: list[dict[str, Any]],
    batch_audit: list[dict[str, Any]],
    field_audit_rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    chain_attempted: int,
    chain_success: int,
    max_spread_pct: float,
) -> dict[str, Any]:
    bid_mapped = any(row["canonical_field"] == "bid" and bool(row["mapped"]) for row in field_audit_rows)
    ask_mapped = any(row["canonical_field"] == "ask" and bool(row["mapped"]) for row in field_audit_rows)
    root = root_cause(enriched, candidates, field_audit_rows)
    if bid_mapped and ask_mapped and candidates:
        status, decision = PASS_STATUS, READY_DECISION
    elif bid_mapped and ask_mapped and enriched:
        status, decision = WARN_ZERO_STATUS, ZERO_DECISION
    elif enriched:
        status, decision = WARN_MAPPING_STATUS, BLOCKED_DECISION
    else:
        status, decision = WARN_UNAVAILABLE_STATUS, BLOCKED_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "generated_at_utc": utc_now_text(),
        "final_status": status,
        "final_decision": decision,
        "execution_mode": execution_mode,
        "opend_port_reachable": reachable,
        "moomoo_quote_context_connected": connected,
        "moomoo_quote_context_disconnected_cleanly": closed,
        "real_readonly_quote_verified": connected and bool(enriched),
        "fallback_rows_used": False,
        "allowed_underlying_etf_count": len(ALLOWED_ETFS),
        "chain_fetch_attempted_underlying_count": chain_attempted,
        "chain_fetch_success_underlying_count": chain_success,
        "total_raw_contract_count": len(metadata),
        "total_dte_eligible_count": sum(1 for row in metadata if dte_eligible(row, False)),
        "enrichment_target_count": len(targets),
        "enrichment_attempted_count": len(targets),
        "enrichment_success_count": sum(1 for row in enriched if row["quote_status"] == "QUOTE_FETCHED_READ_ONLY"),
        "enrichment_failed_count": sum(1 for row in enriched if row["quote_status"] != "QUOTE_FETCHED_READ_ONLY"),
        "enrichment_batch_count": len(batch_audit),
        "enrichment_success_batch_count": sum(1 for row in batch_audit if bool(row["fetch_succeeded"])),
        "enrichment_failed_batch_count": sum(1 for row in batch_audit if not bool(row["fetch_succeeded"])),
        "bid_field_mapped": bid_mapped,
        "ask_field_mapped": ask_mapped,
        "volume_field_mapped": any(row["canonical_field"] == "volume" and bool(row["mapped"]) for row in field_audit_rows),
        "open_interest_field_mapped": any(row["canonical_field"] == "open_interest" and bool(row["mapped"]) for row in field_audit_rows),
        "iv_field_mapped": any(row["canonical_field"] == "implied_volatility" and bool(row["mapped"]) for row in field_audit_rows),
        "greeks_field_mapped": all(any(row["canonical_field"] == f and bool(row["mapped"]) for row in field_audit_rows) for f in ["delta", "gamma", "theta", "vega"]),
        "valid_bid_ask_count": sum(1 for row in enriched if numeric(row["bid"]) is not None and numeric(row["ask"]) is not None and numeric(row["bid"]) > 0 and numeric(row["ask"]) > numeric(row["bid"])),
        "valid_mid_count": sum(1 for row in enriched if numeric(row["mid"]) is not None and numeric(row["mid"]) > 0),
        "finite_spread_pct_count": sum(1 for row in enriched if numeric(row["spread_pct"]) is not None),
        "spread_pass_count": sum(1 for row in enriched if numeric(row["spread_pct"]) is not None and numeric(row["spread_pct"]) <= max_spread_pct),
        "volume_positive_count": sum(1 for row in enriched if numeric(row["volume"]) is not None and numeric(row["volume"]) > 0),
        "liquidity_candidate_count": len(candidates),
        "quote_enrichment_root_cause_if_zero": root,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.041 R3 Live Option Quote Enrichment From Chain Codes", *[f"{key}={summary.get(key)}" for key in SUMMARY_FIELDS]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    host: str = "127.0.0.1",
    port: int = 18441,
    max_contracts: int = 1000,
    batch_size: int = 100,
    max_spread_pct: float = 0.30,
    include_zero_dte: bool = False,
    import_func: Callable[[str], Any] | None = None,
    injected_chain_rows: list[dict[str, Any]] | None = None,
    injected_quote_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_safe_moomoo_environment(repo_root)
    reachable = connected = closed = False
    chain_attempted = chain_success = 0

    if injected_chain_rows is not None:
        chain_rows = [dict(row) for row in injected_chain_rows]
        metadata = metadata_from_chain_rows(chain_rows)
        spot_by_underlying = {}
        targets = select_enrichment_targets(metadata, max_contracts, include_zero_dte, spot_by_underlying)
        quote_by_code = {str(first_present(row, CODE_FIELDS)[1] or row.get("code", "")): row for row in (injected_quote_rows or [])}
        enriched = [normalize_quote_row(meta, quote_by_code.get(str(meta["option_code"]), {}), "QUOTE_FETCHED_READ_ONLY" if str(meta["option_code"]) in quote_by_code else "QUOTE_ROW_NOT_RETURNED") for meta in targets]
        batch_audit = [{"batch_id": i, "requested_count": len(batch), "returned_count": sum(1 for row in batch if str(row["option_code"]) in quote_by_code), "method_used": "INJECTED", "fetch_succeeded": True, "fetch_status": "INJECTED_TEST_ROWS", "error_type": "", "error_message": ""} for i, batch in enumerate(chunks(targets, batch_size), start=1)]
        reachable = connected = closed = True
        chain_attempted = chain_success = len(ALLOWED_ETFS)
    elif not execute:
        metadata, targets, enriched, batch_audit, chain_attempted, chain_success = plan_outputs(max_contracts)
    else:
        reachable, reach_error = opend_port_reachable(host, port)
        metadata = []
        targets = []
        enriched = []
        batch_audit = []
        if reachable:
            moomoo, ok, _error = import_moomoo(import_func)
            ctx = None
            if ok:
                try:
                    ctx = moomoo.OpenQuoteContext(host=host, port=port)
                    connected = True
                    spot_by_underlying = fetch_underlying_spots(ctx, ALLOWED_ETFS)
                    chain_rows, chain_attempted, chain_success = fetch_chains(ctx, ALLOWED_ETFS)
                    metadata = metadata_from_chain_rows(chain_rows)
                    targets = select_enrichment_targets(metadata, max_contracts, include_zero_dte, spot_by_underlying)
                    enriched, batch_audit = fetch_quote_batches(ctx, targets, batch_size)
                except Exception as exc:  # noqa: BLE001
                    batch_audit = [{"batch_id": "", "requested_count": 0, "returned_count": 0, "method_used": "", "fetch_succeeded": False, "fetch_status": "LIVE_FETCH_FAILED", "error_type": type(exc).__name__, "error_message": str(exc)}]
                finally:
                    close = getattr(ctx, "close", None)
                    if callable(close):
                        close()
                        closed = True
        else:
            batch_audit = [{"batch_id": "", "requested_count": 0, "returned_count": 0, "method_used": "", "fetch_succeeded": False, "fetch_status": "OPEND_PORT_UNREACHABLE", "error_type": reach_error.split(":", 1)[0], "error_message": reach_error}]

    field_rows = field_mapping_audit(enriched)
    candidates, rejects = split_liquidity(enriched, max_spread_pct)
    summary = build_summary("EXECUTE_READ_ONLY" if execute else "PLAN", reachable, connected, closed, metadata, targets, enriched, batch_audit, field_rows, candidates, chain_attempted, chain_success, max_spread_pct)

    write_csv(output_dir / "live_option_chain_metadata.csv", METADATA_FIELDS, metadata)
    write_csv(output_dir / "live_option_enrichment_targets.csv", TARGET_FIELDS, targets)
    write_csv(output_dir / "live_option_quote_enriched_rows.csv", ENRICHED_FIELDS, enriched)
    write_csv(output_dir / "live_option_quote_enrichment_batch_audit.csv", BATCH_FIELDS, batch_audit)
    write_csv(output_dir / "live_option_quote_field_mapping_audit.csv", FIELD_AUDIT_FIELDS, field_rows)
    write_csv(output_dir / "live_option_liquidity_candidates_after_enrichment.csv", CANDIDATE_FIELDS, candidates)
    write_csv(output_dir / "live_option_rejected_after_enrichment.csv", REJECT_FIELDS, rejects)
    write_json(output_dir / "v22_041_r3_summary.json", summary)
    (output_dir / "V22.041_R3_live_option_quote_enrichment_from_chain_codes_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    parser.add_argument("--max-contracts", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-spread-pct", type=float, default=0.30)
    parser.add_argument("--include-zero-dte", action="store_true", default=False)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.host, args.port, args.max_contracts, args.batch_size, args.max_spread_pct, args.include_zero_dte)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_041_r3_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
