#!/usr/bin/env python
"""V22.033_R1 post-enrichment option-chain liquidity and coverage audit.

Reads V22.032_R1 quote-enriched option-chain files and writes a research-only
audit. This module is deliberately local-file only: it does not connect to
Moomoo, fetch market data, fetch option chains or quotes, mutate caches or
historical outputs, run daily chains, place orders, or generate candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODULE_ID = "V22.033_R1"
MODULE_NAME = "OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
STAGE = "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_032_R1_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"
CLEAN_INPUT = V22_032_R1_DIR / "v22_option_quote_enrichment_clean.csv"
RAW_INPUT = V22_032_R1_DIR / "v22_option_quote_enrichment_raw.csv"
UNDERLYING_AUDIT_INPUT = V22_032_R1_DIR / "v22_option_quote_enrichment_underlying_audit.csv"
FIELD_COVERAGE_INPUT = V22_032_R1_DIR / "v22_option_quote_enrichment_field_coverage_audit.csv"
SUMMARY_INPUT = V22_032_R1_DIR / "v22_option_quote_enrichment_summary.json"
V22_033_SUMMARY_INPUT = Path("outputs") / "v22" / "V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT" / "v22_option_chain_liquidity_coverage_summary.json"
UNIVERSE_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_registry.csv"
CONTRACT_INPUT = Path("outputs") / "v22" / "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY" / "v22_etf_option_contract_spec_registry.csv"

PASS_READY = "PASS_V22_033_R1_OPTION_CHAIN_LIQUIDITY_COVERAGE_READY"
WARN_IV_GREEKS_OI = "WARN_V22_033_R1_QUOTES_READY_BUT_IV_GREEKS_OI_MISSING"
WARN_NO_QUOTES = "WARN_V22_033_R1_POST_ENRICHMENT_AUDIT_READY_WITH_NO_USABLE_QUOTES"
FAIL_MISSING_INPUTS = "FAIL_V22_033_R1_POST_ENRICHMENT_AUDIT_MISSING_REQUIRED_INPUTS"
READY_DECISION = "OPTION_CHAIN_POST_ENRICHMENT_LIQUIDITY_COVERAGE_READY_RESEARCH_ONLY"
FAIL_DECISION = "OPTION_CHAIN_POST_ENRICHMENT_LIQUIDITY_COVERAGE_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.032_R2_OPTION_IV_GREEKS_AND_OPEN_INTEREST_ENRICHMENT_RESEARCH",
    "V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA",
    "V22.040_LONG_CALL_PUT_CANDIDATE_GENERATOR_BLOCKED_UNTIL_IV_GREEKS_OI_POLICY",
]

REQUIRED_CANDIDATE_FIELDS = [
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
]
LIQUIDITY_FIELDS = {"bid", "ask", "mid", "spread_pct", "volume", "open_interest"}
GREEKS_FIELDS = {"implied_volatility", "delta", "gamma", "theta", "vega"}

NO_ACTION_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "option_quote_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}

FORBIDDEN_SIDE_EFFECTS = [
    "execute_daily_chain",
    "connect_moomoo",
    "fetch_market_data",
    "fetch_option_chain",
    "fetch_option_quote",
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
]

LIQUIDITY_FIELDNAMES = [
    "underlying",
    "theme_bucket",
    "universe_group",
    "universe_tier",
    "leveraged_flag",
    "inverse_flag",
    "high_risk_secondary_flag",
    "enriched_contract_count",
    "expiration_count",
    "call_count",
    "put_count",
    "valid_bid_ask_count",
    "valid_bid_ask_ratio",
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
    "narrow_spread_count",
    "medium_spread_count",
    "wide_spread_count",
    "zero_bid_or_zero_ask_count",
    "nearest_expiration",
    "farthest_expiration",
    "liquidity_coverage_status",
    "quote_enrichment_status",
    "iv_greeks_enrichment_required",
    "open_interest_enrichment_required",
    "candidate_generation_allowed",
    "primary_blocker",
    "secondary_blockers",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_allowed",
    "research_only",
    "reason",
]

READINESS_FIELDNAMES = [
    "underlying",
    "has_enriched_quotes",
    "has_usable_bid_ask",
    "has_usable_mid",
    "has_usable_spread_pct",
    "has_usable_iv",
    "has_usable_greeks",
    "has_usable_volume",
    "has_usable_open_interest",
    "has_required_candidate_fields",
    "readiness_status",
    "next_required_step",
    "reason",
]

FIELD_BLOCKER_FIELDNAMES = [
    "field_name",
    "required_for_candidate_generation",
    "required_for_liquidity_audit",
    "required_for_greeks_audit",
    "clean_non_null_count",
    "clean_coverage_ratio",
    "blocker_triggered",
    "blocker_severity",
    "blocker_reason",
    "recommended_repair",
]

GATE_FIELDNAMES = [
    "gate_name",
    "gate_status",
    "gate_passed",
    "blocker_count",
    "required_fields_missing",
    "affected_underlying_count",
    "candidate_generation_allowed",
    "quote_enrichment_succeeded",
    "iv_greeks_enrichment_required",
    "open_interest_enrichment_required",
    "next_required_module",
    "reason",
]

BUCKET_FIELDNAMES = [
    "bucket_name",
    "spread_pct_min",
    "spread_pct_max",
    "contract_count",
    "underlying_count",
    "candidate_generation_allowed",
    "reason",
]


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
        raise ValueError(f"V22.033_R1 output directory must be {expected}, got {output_dir.resolve()}")


def numeric(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def non_null(row: dict[str, str], field: str) -> bool:
    return str(row.get(field, "")).strip() != ""


def bool_from_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def input_flags(repo_root: Path) -> dict[str, bool]:
    return {
        "v22_032_r1_summary_input_exists": (repo_root / SUMMARY_INPUT).exists(),
        "v22_032_r1_clean_input_exists": (repo_root / CLEAN_INPUT).exists(),
        "v22_032_r1_raw_input_exists": (repo_root / RAW_INPUT).exists(),
        "v22_033_summary_input_exists": (repo_root / V22_033_SUMMARY_INPUT).exists(),
        "v22_030_universe_input_exists": (repo_root / UNIVERSE_INPUT).exists(),
        "v22_031_contract_input_exists": (repo_root / CONTRACT_INPUT).exists(),
    }


def group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key, ""), []).append(row)
    return grouped


def valid_bid_ask(row: dict[str, str]) -> bool:
    bid = numeric(row.get("bid"))
    ask = numeric(row.get("ask"))
    return bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid


def valid_positive(row: dict[str, str], field: str) -> bool:
    value = numeric(row.get(field))
    return value is not None and value > 0


def valid_number(row: dict[str, str], field: str) -> bool:
    return numeric(row.get(field)) is not None


def valid_greeks(row: dict[str, str]) -> bool:
    return all(valid_number(row, field) for field in ["delta", "gamma", "theta", "vega"])


def spread_bucket(spread: float | None) -> str:
    if spread is None:
        return "SPREAD_UNKNOWN"
    if 0 <= spread <= 0.05:
        return "NARROW_SPREAD_0_TO_5_PCT"
    if spread <= 0.15:
        return "MEDIUM_SPREAD_5_TO_15_PCT"
    if spread <= 0.30:
        return "WIDE_SPREAD_15_TO_30_PCT"
    return "EXTREME_SPREAD_GT_30_PCT"


def meta_rows(universe_rows: list[dict[str, str]], underlying_audit: list[dict[str, str]], clean_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_ticker = {row.get("ticker", row.get("underlying", "")): row for row in universe_rows}
    underlyings = {ticker for ticker in by_ticker if ticker}
    underlyings.update(row.get("underlying", "") for row in underlying_audit if row.get("underlying"))
    underlyings.update(row.get("underlying", "") for row in clean_rows if row.get("underlying"))
    rows: list[dict[str, Any]] = []
    for underlying in sorted(underlyings):
        source = by_ticker.get(underlying, {})
        audit = next((row for row in underlying_audit if row.get("underlying") == underlying), {})
        clean = next((row for row in clean_rows if row.get("underlying") == underlying), {})
        rows.append(
            {
                "underlying": underlying,
                "theme_bucket": source.get("theme_bucket", audit.get("theme_bucket", clean.get("theme_bucket", ""))),
                "universe_group": source.get("universe_group", audit.get("universe_group", clean.get("universe_group", ""))),
                "universe_tier": source.get("universe_tier", audit.get("universe_tier", clean.get("universe_tier", ""))),
                "leveraged_flag": bool_from_text(source.get("leveraged_flag", audit.get("leveraged_flag", clean.get("leveraged_flag", "")))),
                "inverse_flag": bool_from_text(source.get("inverse_flag", audit.get("inverse_flag", clean.get("inverse_flag", "")))),
                "high_risk_secondary_flag": bool_from_text(source.get("high_risk_secondary_flag", audit.get("high_risk_secondary_flag", ""))),
            }
        )
    return rows


def liquidity_rows(meta: list[dict[str, Any]], clean_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    clean_by = group_by(clean_rows, "underlying")
    rows: list[dict[str, Any]] = []
    for item in meta:
        underlying = item["underlying"]
        chain = clean_by.get(underlying, [])
        expiration_values = sorted({row.get("expiration", "") for row in chain if row.get("expiration")})
        bid_ask_count = sum(1 for row in chain if valid_bid_ask(row))
        mid_count = sum(1 for row in chain if valid_positive(row, "mid"))
        spread_count = sum(1 for row in chain if valid_number(row, "spread_pct"))
        iv_count = sum(1 for row in chain if valid_positive(row, "implied_volatility"))
        delta_count = sum(1 for row in chain if valid_number(row, "delta"))
        gamma_count = sum(1 for row in chain if valid_number(row, "gamma"))
        theta_count = sum(1 for row in chain if valid_number(row, "theta"))
        vega_count = sum(1 for row in chain if valid_number(row, "vega"))
        greeks_count = sum(1 for row in chain if valid_greeks(row))
        volume_count = sum(1 for row in chain if valid_number(row, "volume"))
        oi_count = sum(1 for row in chain if valid_positive(row, "open_interest"))
        narrow = sum(1 for row in chain if spread_bucket(numeric(row.get("spread_pct"))) == "NARROW_SPREAD_0_TO_5_PCT")
        medium = sum(1 for row in chain if spread_bucket(numeric(row.get("spread_pct"))) == "MEDIUM_SPREAD_5_TO_15_PCT")
        wide = sum(1 for row in chain if spread_bucket(numeric(row.get("spread_pct"))) == "WIDE_SPREAD_15_TO_30_PCT")
        zero_side = sum(1 for row in chain if numeric(row.get("bid")) == 0 or numeric(row.get("ask")) == 0)
        required_ready = bool(chain) and all(
            count > 0
            for count in [bid_ask_count, mid_count, spread_count, iv_count, greeks_count, volume_count, oi_count]
        )
        if required_ready:
            status = "READY_FOR_CANDIDATE_GENERATION"
            primary = ""
        elif chain and bid_ask_count > 0 and (iv_count == 0 or greeks_count == 0 or oi_count == 0):
            status = "QUOTES_READY_BUT_IV_GREEKS_OI_MISSING"
            primary = "IV_GREEKS_OPEN_INTEREST_MISSING"
        elif chain and bid_ask_count > 0:
            status = "PARTIAL_QUOTES_INSUFFICIENT"
            primary = "REQUIRED_CANDIDATE_FIELDS_MISSING"
        elif chain:
            status = "STRUCTURE_ONLY_NO_QUOTES"
            primary = "NO_USABLE_BID_ASK_QUOTES"
        else:
            status = "MISSING_CHAIN"
            primary = "NO_ENRICHED_CHAIN_ROWS"
        blockers = []
        if bid_ask_count == 0:
            blockers.append("bid_ask")
        if mid_count == 0:
            blockers.append("mid")
        if spread_count == 0:
            blockers.append("spread_pct")
        if volume_count == 0:
            blockers.append("volume")
        if oi_count == 0:
            blockers.append("open_interest")
        if iv_count == 0:
            blockers.append("implied_volatility")
        if greeks_count == 0:
            blockers.append("delta;gamma;theta;vega")
        rows.append(
            {
                **item,
                "enriched_contract_count": len(chain),
                "expiration_count": len(expiration_values),
                "call_count": sum(1 for row in chain if row.get("call_put", "").upper() == "CALL"),
                "put_count": sum(1 for row in chain if row.get("call_put", "").upper() == "PUT"),
                "valid_bid_ask_count": bid_ask_count,
                "valid_bid_ask_ratio": round(bid_ask_count / len(chain), 6) if chain else 0.0,
                "valid_mid_count": mid_count,
                "valid_spread_pct_count": spread_count,
                "valid_iv_count": iv_count,
                "valid_greeks_count": greeks_count,
                "valid_delta_count": delta_count,
                "valid_gamma_count": gamma_count,
                "valid_theta_count": theta_count,
                "valid_vega_count": vega_count,
                "valid_volume_count": volume_count,
                "valid_open_interest_count": oi_count,
                "narrow_spread_count": narrow,
                "medium_spread_count": medium,
                "wide_spread_count": wide,
                "zero_bid_or_zero_ask_count": zero_side,
                "nearest_expiration": expiration_values[0] if expiration_values else "",
                "farthest_expiration": expiration_values[-1] if expiration_values else "",
                "liquidity_coverage_status": status,
                "quote_enrichment_status": "HAS_ENRICHED_QUOTES" if bid_ask_count > 0 else "NO_USABLE_QUOTES",
                "iv_greeks_enrichment_required": iv_count == 0 or greeks_count == 0,
                "open_interest_enrichment_required": oi_count == 0,
                "candidate_generation_allowed": required_ready,
                "primary_blocker": primary,
                "secondary_blockers": ";".join(blockers),
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_allowed": False,
                "research_only": True,
                "reason": "Last price is non-tradable; candidate generation requires explicit bid/ask, mid, spread, volume, IV, Greeks, and open interest.",
            }
        )
    return rows


def readiness_rows(liquidity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in liquidity:
        has_bid_ask = int(row["valid_bid_ask_count"]) > 0
        has_mid = int(row["valid_mid_count"]) > 0
        has_spread = int(row["valid_spread_pct_count"]) > 0
        has_iv = int(row["valid_iv_count"]) > 0
        has_greeks = int(row["valid_greeks_count"]) > 0
        has_volume = int(row["valid_volume_count"]) > 0
        has_oi = int(row["valid_open_interest_count"]) > 0
        required = has_bid_ask and has_mid and has_spread and has_iv and has_greeks and has_volume and has_oi
        if required:
            status = "READY"
            next_step = "Research-only candidate policy review; broker and trade gates remain closed."
        elif int(row["enriched_contract_count"]) == 0:
            status = "BLOCKED_NO_CHAIN"
            next_step = "Provide V22.032_R1 enriched chain rows for this underlying."
        elif not has_bid_ask:
            status = "BLOCKED_NO_QUOTES"
            next_step = "Repair bid/ask quote enrichment."
        elif not has_iv or not has_greeks or not has_oi:
            status = "BLOCKED_IV_GREEKS_OI_MISSING"
            next_step = "Run V22.032_R2 IV, Greeks, and open-interest enrichment research."
        else:
            status = "BLOCKED_MISSING_REQUIRED_FIELDS"
            next_step = "Repair missing required candidate fields."
        rows.append(
            {
                "underlying": row["underlying"],
                "has_enriched_quotes": int(row["enriched_contract_count"]) > 0,
                "has_usable_bid_ask": has_bid_ask,
                "has_usable_mid": has_mid,
                "has_usable_spread_pct": has_spread,
                "has_usable_iv": has_iv,
                "has_usable_greeks": has_greeks,
                "has_usable_volume": has_volume,
                "has_usable_open_interest": has_oi,
                "has_required_candidate_fields": required,
                "readiness_status": status,
                "next_required_step": next_step,
                "reason": "Readiness is conservative and blocks candidate generation until every required candidate field is populated.",
            }
        )
    return rows


def field_blocker_rows(clean_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    total = len(clean_rows)
    rows: list[dict[str, Any]] = []
    for field in REQUIRED_CANDIDATE_FIELDS:
        if field == "open_interest":
            count = sum(1 for row in clean_rows if valid_positive(row, field))
        elif field == "implied_volatility":
            count = sum(1 for row in clean_rows if valid_positive(row, field))
        elif field in {"delta", "gamma", "theta", "vega"}:
            count = sum(1 for row in clean_rows if valid_number(row, field))
        elif field in {"bid", "ask", "mid", "spread_pct", "volume"}:
            count = sum(1 for row in clean_rows if valid_number(row, field))
        else:
            count = sum(1 for row in clean_rows if non_null(row, field))
        ratio = count / total if total else 0.0
        triggered = count == 0
        rows.append(
            {
                "field_name": field,
                "required_for_candidate_generation": True,
                "required_for_liquidity_audit": field in LIQUIDITY_FIELDS,
                "required_for_greeks_audit": field in GREEKS_FIELDS,
                "clean_non_null_count": count,
                "clean_coverage_ratio": round(ratio, 6),
                "blocker_triggered": triggered,
                "blocker_severity": "BLOCKING" if triggered else "INFO",
                "blocker_reason": "Required candidate field is missing from all usable clean rows." if triggered else "Required candidate field has usable clean coverage.",
                "recommended_repair": "Run V22.032_R2 IV, Greeks, and open-interest enrichment research." if field in GREEKS_FIELDS or field == "open_interest" else "Monitor field coverage in downstream audits.",
            }
        )
    return rows


def gate_rows(field_blockers: list[dict[str, Any]], liquidity: list[dict[str, Any]], quote_enrichment_succeeded: bool) -> list[dict[str, Any]]:
    blocker_by_field = {row["field_name"]: row for row in field_blockers}
    gate_specs = [
        ("BID_ASK_GATE", ["bid", "ask"], "Bid and ask coverage is required."),
        ("MID_PRICE_GATE", ["mid"], "Mid price coverage is required."),
        ("SPREAD_GATE", ["spread_pct"], "Spread coverage is required."),
        ("VOLUME_GATE", ["volume"], "Volume coverage is required."),
        ("OPEN_INTEREST_GATE", ["open_interest"], "Open-interest coverage is required."),
        ("IV_GATE", ["implied_volatility"], "Implied-volatility coverage is required."),
        ("GREEKS_GATE", ["delta", "gamma", "theta", "vega"], "Greek coverage is required."),
        ("LEVERAGED_ETF_HIGH_RISK_GATE", [], "Leveraged ETFs remain research-only high risk."),
        ("INVERSE_ETF_HIGH_RISK_GATE", [], "Inverse ETFs remain research-only high risk."),
        ("NO_BROKER_ACTION_GATE", [], "Broker action is forbidden for this module."),
        ("NO_TRADE_GATE", [], "Trading is forbidden for this module."),
    ]
    iv_greeks_required = any(blocker_by_field.get(field, {}).get("blocker_triggered") is True for field in ["implied_volatility", "delta", "gamma", "theta", "vega"])
    oi_required = blocker_by_field.get("open_interest", {}).get("blocker_triggered") is True
    rows: list[dict[str, Any]] = []
    affected_all = len(liquidity)
    for name, fields, reason in gate_specs:
        if name in {"LEVERAGED_ETF_HIGH_RISK_GATE", "INVERSE_ETF_HIGH_RISK_GATE", "NO_BROKER_ACTION_GATE", "NO_TRADE_GATE"}:
            missing: list[str] = []
            affected = sum(1 for row in liquidity if row["leveraged_flag"] is True) if name.startswith("LEVERAGED") else 0
            if name.startswith("INVERSE"):
                affected = sum(1 for row in liquidity if row["inverse_flag"] is True)
            passed = False
            status = "CLOSED_RESEARCH_ONLY"
        else:
            missing = [field for field in fields if blocker_by_field.get(field, {}).get("blocker_triggered") is True]
            affected = affected_all if missing else 0
            passed = not missing
            status = "PASS" if passed else "BLOCKED_REQUIRED_FIELDS_MISSING"
        rows.append(
            {
                "gate_name": name,
                "gate_status": status,
                "gate_passed": passed,
                "blocker_count": len(missing),
                "required_fields_missing": ";".join(missing),
                "affected_underlying_count": affected,
                "candidate_generation_allowed": False,
                "quote_enrichment_succeeded": quote_enrichment_succeeded,
                "iv_greeks_enrichment_required": iv_greeks_required,
                "open_interest_enrichment_required": oi_required,
                "next_required_module": "V22.032_R2_OPTION_IV_GREEKS_AND_OPEN_INTEREST_ENRICHMENT_RESEARCH" if missing else "",
                "reason": reason,
            }
        )
    return rows


def bucket_rows(clean_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    specs = [
        ("NARROW_SPREAD_0_TO_5_PCT", 0, 0.05),
        ("MEDIUM_SPREAD_5_TO_15_PCT", 0.05, 0.15),
        ("WIDE_SPREAD_15_TO_30_PCT", 0.15, 0.30),
        ("EXTREME_SPREAD_GT_30_PCT", 0.30, ""),
        ("SPREAD_UNKNOWN", "", ""),
    ]
    rows: list[dict[str, Any]] = []
    for name, minimum, maximum in specs:
        matched = [row for row in clean_rows if spread_bucket(numeric(row.get("spread_pct"))) == name]
        rows.append(
            {
                "bucket_name": name,
                "spread_pct_min": minimum,
                "spread_pct_max": maximum,
                "contract_count": len(matched),
                "underlying_count": len({row.get("underlying", "") for row in matched if row.get("underlying")}),
                "candidate_generation_allowed": False,
                "reason": "Spread quality is audited only; candidate generation remains blocked until all required candidate fields are present.",
            }
        )
    return rows


def summary_payload(repo_root: Path, source_summary: dict[str, Any], raw_rows: list[dict[str, str]], clean_rows: list[dict[str, str]], liquidity: list[dict[str, Any]], field_blockers: list[dict[str, Any]]) -> dict[str, Any]:
    flags = input_flags(repo_root)
    required_ok = flags["v22_032_r1_summary_input_exists"] and flags["v22_032_r1_clean_input_exists"]
    total_bid_ask = sum(int(row["valid_bid_ask_count"]) for row in liquidity)
    total_iv = sum(int(row["valid_iv_count"]) for row in liquidity)
    total_greeks = sum(int(row["valid_greeks_count"]) for row in liquidity)
    total_oi = sum(int(row["valid_open_interest_count"]) for row in liquidity)
    ready_count = sum(1 for row in liquidity if row["liquidity_coverage_status"] == "READY_FOR_CANDIDATE_GENERATION")
    iv_greeks_required = total_iv == 0 or total_greeks == 0
    oi_required = total_oi == 0
    if not required_ok:
        final_status = FAIL_MISSING_INPUTS
        final_decision = FAIL_DECISION
    elif ready_count > 0:
        final_status = PASS_READY
        final_decision = READY_DECISION
    elif total_bid_ask > 0 and (iv_greeks_required or oi_required):
        final_status = WARN_IV_GREEKS_OI
        final_decision = READY_DECISION
    else:
        final_status = WARN_NO_QUOTES
        final_decision = READY_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "final_status": final_status,
        "final_decision": final_decision,
        **flags,
        "source_execution_mode": source_summary.get("execution_mode", "UNKNOWN"),
        "source_target_contract_count": int(source_summary.get("target_contract_count", 0) or 0),
        "enriched_raw_row_count": int(source_summary.get("enriched_raw_row_count", len(raw_rows)) or 0),
        "enriched_clean_row_count": int(source_summary.get("enriched_clean_row_count", len(clean_rows)) or 0),
        "underlying_with_enriched_quotes_count": sum(1 for row in liquidity if int(row["valid_bid_ask_count"]) > 0),
        "underlying_ready_for_candidate_generation_count": ready_count,
        "underlying_blocked_iv_greeks_oi_missing_count": sum(1 for row in liquidity if row["liquidity_coverage_status"] == "QUOTES_READY_BUT_IV_GREEKS_OI_MISSING"),
        "underlying_blocked_no_quotes_count": sum(1 for row in liquidity if row["liquidity_coverage_status"] in {"STRUCTURE_ONLY_NO_QUOTES", "MISSING_CHAIN"}),
        "total_expiration_count": sum(int(row["expiration_count"]) for row in liquidity),
        "total_valid_bid_ask_count": total_bid_ask,
        "total_valid_mid_count": sum(int(row["valid_mid_count"]) for row in liquidity),
        "total_valid_spread_pct_count": sum(int(row["valid_spread_pct_count"]) for row in liquidity),
        "total_valid_iv_count": total_iv,
        "total_valid_greeks_count": total_greeks,
        "total_valid_volume_count": sum(int(row["valid_volume_count"]) for row in liquidity),
        "total_valid_open_interest_count": total_oi,
        "narrow_spread_count": sum(int(row["narrow_spread_count"]) for row in liquidity),
        "medium_spread_count": sum(int(row["medium_spread_count"]) for row in liquidity),
        "wide_spread_count": sum(int(row["wide_spread_count"]) for row in liquidity),
        "extreme_spread_count": sum(1 for row in clean_rows if spread_bucket(numeric(row.get("spread_pct"))) == "EXTREME_SPREAD_GT_30_PCT"),
        "required_candidate_field_blocker_count": sum(1 for row in field_blockers if row["blocker_triggered"] is True),
        "candidate_generation_allowed_count": 0 if iv_greeks_required or oi_required else ready_count,
        "quote_enrichment_succeeded": bool(source_summary.get("quote_enrichment_succeeded", total_bid_ask > 0)),
        "iv_greeks_enrichment_required": iv_greeks_required,
        "open_interest_enrichment_required": oi_required,
        "broker_action_allowed_count": 0,
        "official_adoption_allowed_count": 0,
        "trade_allowed_count": 0,
        "protected_outputs_modified": False,
        "research_only": True,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        **NO_ACTION_GATES,
    }


def risk_gate_payload(summary: dict[str, Any]) -> dict[str, Any]:
    blocked = bool(summary["iv_greeks_enrichment_required"] or summary["open_interest_enrichment_required"])
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        **NO_ACTION_GATES,
        "candidate_generation_allowed": False if blocked else summary["underlying_ready_for_candidate_generation_count"] > 0,
        "allowed_side_effects": ["create_outputs_v22_033_r1_only"],
        "forbidden_side_effects": FORBIDDEN_SIDE_EFFECTS,
    }


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.033_R1 Option Chain Liquidity And Coverage Audit After Quote Enrichment",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"source_execution_mode={summary['source_execution_mode']}",
        f"enriched_clean_row_count={summary['enriched_clean_row_count']}",
        f"total_valid_bid_ask_count={summary['total_valid_bid_ask_count']}",
        f"total_valid_volume_count={summary['total_valid_volume_count']}",
        f"total_valid_iv_count={summary['total_valid_iv_count']}",
        f"total_valid_greeks_count={summary['total_valid_greeks_count']}",
        f"total_valid_open_interest_count={summary['total_valid_open_interest_count']}",
        f"candidate_generation_allowed_count={summary['candidate_generation_allowed_count']}",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_allowed=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    validate_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    flags = input_flags(repo_root)
    source_summary = read_json(repo_root / SUMMARY_INPUT)
    raw_rows = read_csv_rows(repo_root / RAW_INPUT)
    clean_rows = read_csv_rows(repo_root / CLEAN_INPUT)
    underlying_source = read_csv_rows(repo_root / UNDERLYING_AUDIT_INPUT)
    universe = read_csv_rows(repo_root / UNIVERSE_INPUT)

    meta = meta_rows(universe, underlying_source, clean_rows) if flags["v22_032_r1_clean_input_exists"] else []
    liquidity = liquidity_rows(meta, clean_rows)
    readiness = readiness_rows(liquidity)
    blockers = field_blocker_rows(clean_rows)
    summary = summary_payload(repo_root, source_summary, raw_rows, clean_rows, liquidity, blockers)
    gates = gate_rows(blockers, liquidity, bool(summary["quote_enrichment_succeeded"]))
    buckets = bucket_rows(clean_rows)

    write_csv(output_dir / "v22_option_chain_post_enrichment_liquidity_coverage_audit.csv", LIQUIDITY_FIELDNAMES, liquidity)
    write_csv(output_dir / "v22_option_chain_post_enrichment_underlying_readiness_audit.csv", READINESS_FIELDNAMES, readiness)
    write_csv(output_dir / "v22_option_chain_post_enrichment_field_blocker_audit.csv", FIELD_BLOCKER_FIELDNAMES, blockers)
    write_csv(output_dir / "v22_option_chain_post_enrichment_candidate_generation_gate.csv", GATE_FIELDNAMES, gates)
    write_csv(output_dir / "v22_option_chain_post_enrichment_liquidity_bucket_audit.csv", BUCKET_FIELDNAMES, buckets)
    write_json(output_dir / "v22_option_chain_post_enrichment_summary.json", summary)
    write_json(output_dir / "v22_option_chain_post_enrichment_risk_gate.json", risk_gate_payload(summary))
    (output_dir / "V22.033_R1_option_chain_liquidity_and_coverage_after_quote_enrichment_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true", help="Accepted for consistency; this audit never fetches or connects.")
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_option_chain_post_enrichment_summary.json'}")
    print("candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_MISSING_INPUTS else 0


if __name__ == "__main__":
    raise SystemExit(main())
