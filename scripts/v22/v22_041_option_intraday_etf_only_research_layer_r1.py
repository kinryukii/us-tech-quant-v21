#!/usr/bin/env python
"""V22.041 ETF-only option intraday research layer R1.

Research-only contract universe and liquidity audit for ETF option candidates.
This module blocks single-stock option contracts, does not open trade context,
does not unlock trading, and does not create broker action instructions.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import socket
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ID = "V22.041"
MODULE_NAME = "OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1"
STAGE = "V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1"
OUT_REL = Path("outputs") / "v22" / STAGE

PASS_STATUS = "PASS_V22_041_ETF_OPTION_INTRADAY_RESEARCH_LAYER_READY"
WARN_LIVE_UNAVAILABLE_STATUS = "WARN_V22_041_LIVE_OPTION_QUOTE_ENRICHMENT_UNAVAILABLE"
READY_DECISION = "ETF_OPTION_INTRADAY_RESEARCH_LAYER_READY_RESEARCH_ONLY"

ALLOWED_ETFS = ["SOXX", "SOXL", "SOXS", "QQQ", "TQQQ", "SQQQ", "SPY"]
SAMPLE_ASOF_DATE = date(2026, 7, 8)

NO_ACTION_GATES = {
    "research_only": True,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "trade_context_used": False,
    "order_placement_used": False,
    "broker_instruction_created": False,
    "canonical_stock_ranking_outputs_mutated": False,
    "official_strategy_adoption_files_mutated": False,
}

SAFE_LOG_STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"

UNIVERSE_FIELDS = [
    "contract_id", "underlying", "underlying_allowed_etf", "asset_scope", "expiration", "dte",
    "strike", "call_put", "bid", "ask", "mid", "spread_abs", "spread_pct", "volume",
    "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
    "quote_time_utc", "source", "clean_status", "warning_fields", "research_only",
    "broker_action_allowed", "official_adoption_allowed",
]
QUOTE_AUDIT_FIELDS = [
    "contract_id", "underlying", "quote_present", "bid", "ask", "mid", "spread_pct",
    "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega",
    "rho", "valid_bid_ask", "valid_mid", "valid_spread_pct", "valid_volume",
    "missing_quote", "missing_iv", "missing_greeks", "missing_open_interest",
    "warning_fields", "audit_status", "reason",
]
CANDIDATE_FIELDS = [
    "contract_id", "underlying", "expiration", "dte", "strike", "call_put", "bid", "ask",
    "mid", "spread_pct", "volume", "open_interest", "implied_volatility", "delta",
    "gamma", "theta", "vega", "rho", "liquidity_status", "research_only",
    "candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed",
]
REJECT_FIELDS = [
    "contract_id", "underlying", "asset_scope", "expiration", "dte", "strike", "call_put",
    "bid", "ask", "mid", "spread_pct", "volume", "reject_reason", "single_stock_blocked",
    "broker_action_allowed", "official_adoption_allowed", "research_only",
]


DEFAULT_CONTRACTS = [
    {"contract_id": "QQQ_20260717_C_500", "underlying": "QQQ", "expiration": "2026-07-17", "strike": 500, "call_put": "CALL", "bid": 4.10, "ask": 4.40, "volume": 1200, "open_interest": "", "implied_volatility": "", "delta": "", "gamma": "", "theta": "", "vega": "", "rho": ""},
    {"contract_id": "SOXX_20260717_P_230", "underlying": "SOXX", "expiration": "2026-07-17", "strike": 230, "call_put": "PUT", "bid": 3.00, "ask": 3.30, "volume": 80, "open_interest": 500, "implied_volatility": 0.31, "delta": -0.42, "gamma": 0.02, "theta": -0.08, "vega": 0.15, "rho": -0.01},
    {"contract_id": "SPY_20260724_C_620", "underlying": "SPY", "expiration": "2026-07-24", "strike": 620, "call_put": "CALL", "bid": 2.00, "ask": 2.20, "volume": 4000, "open_interest": 12000, "implied_volatility": 0.18, "delta": 0.35, "gamma": 0.01, "theta": -0.04, "vega": 0.20, "rho": 0.02},
    {"contract_id": "TQQQ_20260717_C_90_ZERO_BID", "underlying": "TQQQ", "expiration": "2026-07-17", "strike": 90, "call_put": "CALL", "bid": 0, "ask": 0.15, "volume": 100, "open_interest": 200, "implied_volatility": 0.7},
    {"contract_id": "SOXL_20260717_C_40_CROSSED", "underlying": "SOXL", "expiration": "2026-07-17", "strike": 40, "call_put": "CALL", "bid": 1.20, "ask": 1.10, "volume": 100, "open_interest": 200},
    {"contract_id": "SQQQ_20260717_P_18_WIDE", "underlying": "SQQQ", "expiration": "2026-07-17", "strike": 18, "call_put": "PUT", "bid": 0.50, "ask": 1.20, "volume": 300, "open_interest": 700},
    {"contract_id": "SOXS_20260717_C_12_LOWVOL", "underlying": "SOXS", "expiration": "2026-07-17", "strike": 12, "call_put": "CALL", "bid": 0.80, "ask": 0.90, "volume": 0, "open_interest": 100},
    {"contract_id": "AAPL_20260717_C_250_SINGLE_STOCK", "underlying": "AAPL", "expiration": "2026-07-17", "strike": 250, "call_put": "CALL", "bid": 1.00, "ask": 1.15, "volume": 500, "open_interest": 1000, "implied_volatility": 0.22},
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


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]


def validate_output_dir(repo_root: Path, output_dir: Path) -> None:
    expected = (repo_root / OUT_REL).resolve()
    if output_dir.resolve() != expected:
        raise ValueError(f"V22.041 output directory must be {expected}, got {output_dir.resolve()}")


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def finite_positive(value: Any) -> bool:
    parsed = numeric(value)
    return parsed is not None and parsed > 0


def parse_dte(expiration: Any, asof: date) -> int | None:
    try:
        return (date.fromisoformat(str(expiration)[:10]) - asof).days
    except ValueError:
        return None


def warning_fields(row: dict[str, Any]) -> list[str]:
    warnings = []
    if numeric(row.get("implied_volatility")) is None:
        warnings.append("implied_volatility")
    greek_fields = ["delta", "gamma", "theta", "vega"]
    missing_greeks = [field for field in greek_fields if numeric(row.get(field)) is None]
    warnings.extend(missing_greeks)
    if numeric(row.get("open_interest")) is None:
        warnings.append("open_interest")
    return warnings


def normalize_contracts(rows: list[dict[str, Any]], asof: date) -> list[dict[str, Any]]:
    normalized = []
    quote_time = utc_now_text()
    for raw in rows:
        row = dict(raw)
        underlying = str(row.get("underlying", "")).upper().strip()
        bid = numeric(row.get("bid"))
        ask = numeric(row.get("ask"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        spread_abs = ask - bid if bid is not None and ask is not None else None
        spread_pct = spread_abs / mid if mid and mid > 0 and spread_abs is not None else None
        dte = row.get("dte")
        if dte in {"", None}:
            dte = parse_dte(row.get("expiration"), asof)
        warnings = warning_fields(row)
        normalized.append({
            **row,
            "contract_id": row.get("contract_id") or row.get("option_code") or row.get("symbol") or "",
            "underlying": underlying,
            "underlying_allowed_etf": underlying in ALLOWED_ETFS,
            "asset_scope": "ETF_OPTION" if underlying in ALLOWED_ETFS else "BLOCKED_SINGLE_STOCK_OR_NON_ETF_OPTION",
            "dte": dte if dte is not None else "",
            "bid": "" if bid is None else bid,
            "ask": "" if ask is None else ask,
            "mid": "" if mid is None else round(mid, 6),
            "spread_abs": "" if spread_abs is None else round(spread_abs, 6),
            "spread_pct": "" if spread_pct is None else round(spread_pct, 6),
            "quote_time_utc": row.get("quote_time_utc") or quote_time,
            "source": row.get("source") or "LOCAL_RESEARCH_SAMPLE_OR_READ_ONLY_QUOTE",
            "warning_fields": ";".join(warnings),
            "clean_status": "ETF_WHITELISTED" if underlying in ALLOWED_ETFS else "REJECT_SINGLE_STOCK_OR_NON_ETF",
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
        })
    return normalized


def reject_reasons(row: dict[str, Any], min_dte: int, max_dte: int, allow_0dte: bool, max_spread_pct: float) -> list[str]:
    reasons = []
    if not row.get("underlying_allowed_etf"):
        reasons.append("UNDERLYING_NOT_IN_ETF_WHITELIST_SINGLE_STOCK_BLOCKED")
    dte = numeric(row.get("dte"))
    if dte is None:
        reasons.append("DTE_MISSING")
    elif dte == 0 and not allow_0dte:
        reasons.append("ZERO_DTE_DISABLED")
    elif dte < min_dte or dte > max_dte:
        reasons.append("DTE_OUT_OF_RANGE")
    bid = numeric(row.get("bid"))
    ask = numeric(row.get("ask"))
    mid = numeric(row.get("mid"))
    spread_pct = numeric(row.get("spread_pct"))
    volume = numeric(row.get("volume"))
    if bid is None or ask is None:
        reasons.append("MISSING_QUOTE")
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
    return reasons


def quote_audit_rows(universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in universe:
        warnings = str(row.get("warning_fields", ""))
        greeks_missing = any(field in warnings.split(";") for field in ["delta", "gamma", "theta", "vega"])
        quote_present = numeric(row.get("bid")) is not None and numeric(row.get("ask")) is not None
        valid_bid_ask = quote_present and numeric(row.get("bid")) > 0 and numeric(row.get("ask")) > numeric(row.get("bid"))
        rows.append({
            "contract_id": row.get("contract_id", ""),
            "underlying": row.get("underlying", ""),
            "quote_present": quote_present,
            "bid": row.get("bid", ""),
            "ask": row.get("ask", ""),
            "mid": row.get("mid", ""),
            "spread_pct": row.get("spread_pct", ""),
            "volume": row.get("volume", ""),
            "open_interest": row.get("open_interest", ""),
            "implied_volatility": row.get("implied_volatility", ""),
            "delta": row.get("delta", ""),
            "gamma": row.get("gamma", ""),
            "theta": row.get("theta", ""),
            "vega": row.get("vega", ""),
            "rho": row.get("rho", ""),
            "valid_bid_ask": valid_bid_ask,
            "valid_mid": finite_positive(row.get("mid")),
            "valid_spread_pct": numeric(row.get("spread_pct")) is not None,
            "valid_volume": finite_positive(row.get("volume")),
            "missing_quote": not quote_present,
            "missing_iv": numeric(row.get("implied_volatility")) is None,
            "missing_greeks": greeks_missing,
            "missing_open_interest": numeric(row.get("open_interest")) is None,
            "warning_fields": warnings,
            "audit_status": "WARN_OPTIONAL_FIELDS_MISSING" if warnings else "QUOTE_AUDIT_OK",
            "reason": "IV, Greeks, and OI are warnings only in R1." if warnings else "Required bid/ask/mid/spread/volume checked.",
        })
    return rows


def split_candidates(
    universe: list[dict[str, Any]],
    min_dte: int,
    max_dte: int,
    allow_0dte: bool,
    max_spread_pct: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = []
    rejected = []
    for row in universe:
        reasons = reject_reasons(row, min_dte, max_dte, allow_0dte, max_spread_pct)
        if reasons:
            rejected.append({
                **row,
                "reject_reason": ";".join(reasons),
                "single_stock_blocked": "UNDERLYING_NOT_IN_ETF_WHITELIST_SINGLE_STOCK_BLOCKED" in reasons,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "research_only": True,
            })
        else:
            candidates.append({
                **row,
                "liquidity_status": "R1_LIQUIDITY_FILTER_PASS",
                "candidate_generation_allowed": True,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "research_only": True,
            })
    return candidates, rejected


def load_input_contracts(input_csv: Path | None) -> list[dict[str, Any]]:
    if input_csv is not None and input_csv.exists():
        return read_csv_rows(input_csv)
    return [dict(row) for row in DEFAULT_CONTRACTS]


def opend_port_reachable(host: str, port: int, timeout_seconds: float = 1.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def read_only_quote_rows(underlyings: list[str], host: str, port: int) -> tuple[list[dict[str, Any]], str]:
    reachable, reach_error = opend_port_reachable(host, port)
    if not reachable:
        return [], f"READ_ONLY_QUOTE_UNAVAILABLE:OPEND_PORT_UNREACHABLE:{reach_error}"
    try:
        moomoo = __import__("moomoo")
        quote_cls = getattr(moomoo, "OpenQuoteContext")
        ctx = quote_cls(host=host, port=port)
    except Exception as exc:  # noqa: BLE001 - optional read-only market data boundary
        return [], f"READ_ONLY_QUOTE_UNAVAILABLE:{type(exc).__name__}:{exc}"
    try:
        rows: list[dict[str, Any]] = []
        for underlying in underlyings:
            method = getattr(ctx, "get_option_chain", None)
            if method is None:
                continue
            result = method(code=f"US.{underlying}")
            data = result[1] if isinstance(result, tuple) and len(result) > 1 else result
            if hasattr(data, "to_dict"):
                data_rows = data.to_dict("records")
            else:
                data_rows = data if isinstance(data, list) else []
            for item in data_rows:
                if isinstance(item, dict):
                    rows.append({**item, "underlying": underlying, "source": "MOOMOO_READ_ONLY_QUOTE"})
        return rows, "READ_ONLY_QUOTE_ATTEMPTED"
    except Exception as exc:  # noqa: BLE001
        return [], f"READ_ONLY_QUOTE_FAILED:{type(exc).__name__}:{exc}"
    finally:
        close = getattr(ctx, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass


def load_r3_module() -> Any:
    path = Path(__file__).with_name("v22_041_r3_live_option_quote_enrichment_from_chain_codes.py")
    spec = importlib.util.spec_from_file_location("v22_041_r3_live_enrichment", path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise ImportError(f"Unable to load R3 enrichment module from {path}")
    spec.loader.exec_module(module)
    return module


def read_only_enriched_option_rows(
    repo_root: Path,
    host: str,
    port: int,
    max_contracts: int,
    batch_size: int,
    max_spread_pct: float,
    include_zero_dte: bool,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    try:
        r3 = load_r3_module()
        summary = r3.run(
            repo_root,
            execute=True,
            host=host,
            port=port,
            max_contracts=max_contracts,
            batch_size=batch_size,
            max_spread_pct=max_spread_pct,
            include_zero_dte=include_zero_dte,
        )
        enriched_path = repo_root / r3.OUT_REL / "live_option_quote_enriched_rows.csv"
        rows = read_csv_rows(enriched_path)
        if rows and summary.get("enrichment_success_count", 0) > 0:
            return rows, "READ_ONLY_OPTION_QUOTE_ENRICHED_FROM_CHAIN_CODES", summary
        return [], f"READ_ONLY_OPTION_QUOTE_ENRICHMENT_FAILED:{summary.get('final_status')}:{summary.get('quote_enrichment_root_cause_if_zero', '')}", summary
    except Exception as exc:  # noqa: BLE001
        return [], f"READ_ONLY_OPTION_QUOTE_ENRICHMENT_FAILED:{type(exc).__name__}:{exc}", {}


def configure_safe_moomoo_log_environment(repo_root: Path) -> Path:
    output_dir = repo_root / "outputs" / "v22" / SAFE_LOG_STAGE
    safe_log_dir = output_dir / "provider_logs"
    safe_root = output_dir / "provider_env"
    userprofile = safe_root / "userprofile"
    appdata = safe_root / "AppData" / "Roaming"
    localappdata = safe_root / "AppData" / "Local"
    for path in [safe_log_dir, userprofile, appdata, localappdata]:
        path.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "FUTU_OPEND_LOG_DIR": str(safe_log_dir),
        "MOOMOO_LOG_DIR": str(safe_log_dir),
        "FUTU_LOG_DIR": str(safe_log_dir),
        "FutuOpenD_LogDir": str(safe_log_dir),
        "TMP": str(safe_log_dir),
        "TEMP": str(safe_log_dir),
        "USERPROFILE": str(userprofile),
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(localappdata),
    })
    return safe_log_dir


def summary_payload(
    execution_mode: str,
    universe: list[dict[str, Any]],
    quote_audit: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    quote_status: str,
    fallback_rows_used: bool = False,
    safe_log_dir_path: str = "",
    final_status: str = PASS_STATUS,
    r3_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_underlyings = {row.get("underlying", "") for row in universe if row.get("underlying")}
    single_stock_count = sum(1 for row in universe if not row.get("underlying_allowed_etf"))
    zero_bid_count = sum(1 for row in rejected if "ZERO_OR_NEGATIVE_BID" in row.get("reject_reason", ""))
    wide_spread_count = sum(1 for row in rejected if "WIDE_SPREAD" in row.get("reject_reason", ""))
    low_volume_count = sum(1 for row in rejected if "LOW_OR_ZERO_VOLUME" in row.get("reject_reason", ""))
    missing_quote_count = sum(1 for row in quote_audit if row["missing_quote"] is True)
    missing_iv_count = sum(1 for row in quote_audit if row["missing_iv"] is True)
    missing_greeks_count = sum(1 for row in quote_audit if row["missing_greeks"] is True)
    missing_oi_count = sum(1 for row in quote_audit if row["missing_open_interest"] is True)
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": READY_DECISION,
        "execution_mode": execution_mode,
        "allowed_underlying_etf_count": len(ALLOWED_ETFS),
        "observed_underlying_count": len(observed_underlyings),
        "single_stock_contract_count": single_stock_count,
        "single_stock_blocked_count": sum(1 for row in rejected if row.get("single_stock_blocked") is True),
        "contract_attempted_count": len(universe),
        "contract_clean_count": sum(1 for row in universe if row.get("underlying_allowed_etf")),
        "valid_bid_ask_count": sum(1 for row in quote_audit if row["valid_bid_ask"] is True),
        "valid_mid_count": sum(1 for row in quote_audit if row["valid_mid"] is True),
        "valid_spread_pct_count": sum(1 for row in quote_audit if row["valid_spread_pct"] is True),
        "valid_volume_count": sum(1 for row in quote_audit if row["valid_volume"] is True),
        "liquidity_candidate_count": len(candidates),
        "zero_bid_count": zero_bid_count,
        "wide_spread_count": wide_spread_count,
        "low_volume_count": low_volume_count,
        "missing_quote_count": missing_quote_count,
        "missing_iv_count": missing_iv_count,
        "missing_greeks_count": missing_greeks_count,
        "missing_open_interest_count": missing_oi_count,
        "etf_only_gate_passed": single_stock_count == sum(1 for row in rejected if row.get("single_stock_blocked") is True),
        "candidate_generation_allowed": True,
        "allowed_underlyings": ALLOWED_ETFS,
        "quote_access_status": quote_status,
        "fallback_rows_used": fallback_rows_used,
        "real_readonly_quote_verified": not fallback_rows_used and quote_status in {"READ_ONLY_QUOTE_ATTEMPTED", "READ_ONLY_OPTION_QUOTE_ENRICHED_FROM_CHAIN_CODES"},
        "safe_log_dir_path": safe_log_dir_path,
        "enrichment_target_count": (r3_summary or {}).get("enrichment_target_count", 0),
        "enrichment_success_count": (r3_summary or {}).get("enrichment_success_count", 0),
        "bid_field_mapped": (r3_summary or {}).get("bid_field_mapped", False),
        "ask_field_mapped": (r3_summary or {}).get("ask_field_mapped", False),
        "volume_field_mapped": (r3_summary or {}).get("volume_field_mapped", False),
        **NO_ACTION_GATES,
    }


def report_text(summary: dict[str, Any]) -> str:
    keys = [
        "final_status", "final_decision", "execution_mode", "allowed_underlying_etf_count",
        "observed_underlying_count", "single_stock_contract_count", "single_stock_blocked_count",
        "contract_attempted_count", "liquidity_candidate_count", "missing_iv_count",
        "missing_greeks_count", "missing_open_interest_count", "etf_only_gate_passed",
        "research_only", "broker_action_allowed", "official_adoption_allowed",
    ]
    return "\n".join(["V22.041 ETF Option Intraday Research Layer R1", *[f"{key}={summary.get(key)}" for key in keys]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    input_csv: Path | None = None,
    min_dte: int = 1,
    max_dte: int = 21,
    allow_0dte: bool = False,
    max_spread_pct: float = 0.30,
    host: str = "127.0.0.1",
    port: int = 18441,
    max_contracts: int = 1000,
    batch_size: int = 100,
    allow_fallback_rows: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_rows = load_input_contracts(input_csv)
    quote_status = "PLAN_MODE_LOCAL_RESEARCH_ROWS_ONLY"
    fallback_rows_used = not execute
    safe_log_dir_path = ""
    final_status = PASS_STATUS
    r3_summary: dict[str, Any] = {}
    if execute:
        safe_log_dir_path = str(configure_safe_moomoo_log_environment(repo_root))
        fetched, quote_status, r3_summary = read_only_enriched_option_rows(repo_root, host, port, max_contracts, batch_size, max_spread_pct, allow_0dte)
        if fetched:
            base_rows = fetched
            fallback_rows_used = False
        else:
            fallback_rows_used = allow_fallback_rows
            final_status = WARN_LIVE_UNAVAILABLE_STATUS
            if allow_fallback_rows:
                quote_status = f"{quote_status}:FALLBACK_LOCAL_RESEARCH_ROWS_USED"
            else:
                base_rows = []
                quote_status = f"{quote_status}:NO_FALLBACK_ROWS_USED"
    universe = normalize_contracts(base_rows, SAMPLE_ASOF_DATE)
    quote_audit = quote_audit_rows(universe)
    candidates, rejected = split_candidates(universe, min_dte, max_dte, allow_0dte, max_spread_pct)
    summary = summary_payload("EXECUTE_READ_ONLY" if execute else "PLAN", universe, quote_audit, candidates, rejected, quote_status, fallback_rows_used, safe_log_dir_path, final_status, r3_summary)

    write_csv(output_dir / "etf_option_contract_universe.csv", UNIVERSE_FIELDS, universe)
    write_csv(output_dir / "etf_option_quote_audit.csv", QUOTE_AUDIT_FIELDS, quote_audit)
    write_csv(output_dir / "etf_option_liquidity_candidates.csv", CANDIDATE_FIELDS, candidates)
    write_csv(output_dir / "etf_option_rejected_contracts.csv", REJECT_FIELDS, rejected)
    write_json(output_dir / "v22_041_summary.json", summary)
    (output_dir / "V22.041_etf_option_intraday_research_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--input-csv", type=Path, default=None)
    parser.add_argument("--min-dte", type=int, default=1)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--allow-0dte", action="store_true", default=False)
    parser.add_argument("--max-spread-pct", type=float, default=0.30)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    parser.add_argument("--max-contracts", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--allow-fallback-rows", action="store_true", default=False)
    args = parser.parse_args(argv)
    payload = run(args.repo_root, args.execute, args.input_csv, args.min_dte, args.max_dte, args.allow_0dte, args.max_spread_pct, args.host, args.port, args.max_contracts, args.batch_size, args.allow_fallback_rows)
    for key in ["final_status", "final_decision", "execution_mode", "liquidity_candidate_count", "single_stock_blocked_count", "research_only", "broker_action_allowed", "official_adoption_allowed"]:
        print(f"{key}={payload.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_041_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
