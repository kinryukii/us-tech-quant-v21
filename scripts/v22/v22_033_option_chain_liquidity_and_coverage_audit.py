#!/usr/bin/env python
"""V22.033 option-chain liquidity and coverage audit.

Read-only audit of V22.032 option-chain snapshot outputs. This module reads
local files only; it does not connect to Moomoo, fetch market data or option
chains, execute daily chains, mutate caches or V21 outputs, place orders, or
generate option candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


MODULE_ID = "V22.033"
MODULE_NAME = "OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT"
STAGE = "V22.033_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT"
OUT_REL = Path("outputs") / "v22" / STAGE
FREEZE_DATE = date(2026, 7, 6).isoformat()

V22_032_DIR = Path("outputs") / "v22" / "V22.032_MOOMOO_ETF_OPTION_CHAIN_SNAPSHOT"
CLEAN_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_snapshot_clean.csv"
RAW_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_snapshot_raw.csv"
UNDERLYING_AUDIT_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_underlying_audit.csv"
FIELD_COVERAGE_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_field_coverage_audit.csv"
SUMMARY_INPUT = V22_032_DIR / "v22_moomoo_etf_option_chain_snapshot_summary.json"
UNIVERSE_INPUT = Path("outputs") / "v22" / "V22.030_ETF_OPTION_UNIVERSE_REGISTRY" / "v22_etf_option_universe_registry.csv"
CONTRACT_INPUT = Path("outputs") / "v22" / "V22.031_ETF_OPTION_CONTRACT_SPEC_REGISTRY" / "v22_etf_option_contract_spec_registry.csv"

PASS_STATUS = "PASS_V22_033_OPTION_CHAIN_LIQUIDITY_COVERAGE_READY"
WARN_STRUCTURE_ONLY = "WARN_V22_033_OPTION_CHAIN_STRUCTURE_ONLY_QUOTES_MISSING"
WARN_NO_USABLE = "WARN_V22_033_OPTION_CHAIN_AUDIT_READY_WITH_NO_USABLE_CONTRACTS"
FAIL_STATUS = "FAIL_V22_033_OPTION_CHAIN_AUDIT_MISSING_REQUIRED_INPUTS"
READY_DECISION = "OPTION_CHAIN_LIQUIDITY_COVERAGE_READY_RESEARCH_ONLY"
FAIL_DECISION = "OPTION_CHAIN_LIQUIDITY_COVERAGE_BLOCKED_MISSING_REQUIRED_INPUTS"

NEXT_RECOMMENDED_MODULES = [
    "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY",
    "V22.034_OPTION_PACKAGE_ACCOUNTING_SCHEMA",
    "V22.040_LONG_CALL_PUT_CANDIDATE_GENERATOR_BLOCKED_UNTIL_QUOTES",
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
QUOTE_ENRICHMENT_FIELDS = {"bid", "ask", "mid", "spread_pct", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"}

NO_ACTION_GATES = {
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "trade_allowed": False,
    "market_data_fetch_allowed": False,
    "moomoo_connection_allowed": False,
    "option_chain_fetch_allowed": False,
    "daily_chain_execution_allowed": False,
    "historical_outputs_mutation_allowed": False,
    "cache_mutation_allowed": False,
    "factor_promotion_allowed": False,
    "factor_weight_change_allowed": False,
}

LIQUIDITY_FIELDNAMES = [
    "underlying",
    "theme_bucket",
    "universe_group",
    "universe_tier",
    "leveraged_flag",
    "inverse_flag",
    "high_risk_secondary_flag",
    "raw_contract_count",
    "clean_contract_count",
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
    "nearest_expiration",
    "farthest_expiration",
    "liquidity_coverage_status",
    "quote_enrichment_required",
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
    "has_chain_structure",
    "has_usable_quotes",
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
    "option_quote_enrichment_required",
    "next_required_module",
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
        raise ValueError(f"V22.033 output directory must be {expected}, got {output_dir.resolve()}")


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
        "v22_032_summary_input_exists": (repo_root / SUMMARY_INPUT).exists(),
        "v22_032_clean_input_exists": (repo_root / CLEAN_INPUT).exists(),
        "v22_032_raw_input_exists": (repo_root / RAW_INPUT).exists(),
        "v22_030_universe_input_exists": (repo_root / UNIVERSE_INPUT).exists(),
        "v22_031_contract_input_exists": (repo_root / CONTRACT_INPUT).exists(),
    }


def group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key, ""), []).append(row)
    return grouped


def universe_meta(universe_rows: list[dict[str, str]], underlying_audit: list[dict[str, str]], clean_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_ticker = {row.get("ticker", ""): row for row in universe_rows}
    underlyings = set(by_ticker)
    underlyings.update(row.get("underlying", "") for row in underlying_audit if row.get("underlying"))
    underlyings.update(row.get("underlying", "") for row in clean_rows if row.get("underlying"))
    rows: list[dict[str, Any]] = []
    for underlying in sorted(underlyings):
        meta = by_ticker.get(underlying, {})
        audit = next((row for row in underlying_audit if row.get("underlying") == underlying), {})
        rows.append(
            {
                "underlying": underlying,
                "theme_bucket": meta.get("theme_bucket", audit.get("theme_bucket", "")),
                "universe_group": meta.get("universe_group", audit.get("universe_group", "")),
                "universe_tier": meta.get("universe_tier", audit.get("universe_tier", "")),
                "leveraged_flag": bool_from_text(meta.get("leveraged_flag", audit.get("leveraged_flag", ""))),
                "inverse_flag": bool_from_text(meta.get("inverse_flag", audit.get("inverse_flag", ""))),
                "high_risk_secondary_flag": bool_from_text(meta.get("high_risk_secondary_flag", audit.get("high_risk_secondary_flag", ""))),
            }
        )
    return rows


def liquidity_rows(meta_rows: list[dict[str, Any]], raw_rows: list[dict[str, str]], clean_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    raw_by = group_by(raw_rows, "underlying")
    clean_by = group_by(clean_rows, "underlying")
    rows: list[dict[str, Any]] = []
    for meta in meta_rows:
        underlying = meta["underlying"]
        raw = raw_by.get(underlying, [])
        clean = clean_by.get(underlying, [])
        clean_count = len(clean)
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
        expirations = sorted({row.get("expiration", "") for row in clean if row.get("expiration")})
        if clean_count == 0:
            status = "MISSING_CHAIN"
            primary = "NO_CHAIN_STRUCTURE"
            quote_required = True
        elif valid_bid_ask == 0:
            status = "STRUCTURE_ONLY_NO_QUOTES"
            primary = "BID_ASK_MISSING"
            quote_required = True
        elif not all([valid_mid, valid_spread, valid_iv, valid_greeks, valid_volume, valid_oi]):
            status = "PARTIAL_QUOTES_INSUFFICIENT"
            primary = "REQUIRED_QUOTE_FIELDS_INCOMPLETE"
            quote_required = True
        else:
            status = "READY_FOR_CANDIDATE_GENERATION"
            primary = ""
            quote_required = False
        candidate_allowed = status == "READY_FOR_CANDIDATE_GENERATION"
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
                "theme_bucket": meta["theme_bucket"],
                "universe_group": meta["universe_group"],
                "universe_tier": meta["universe_tier"],
                "leveraged_flag": meta["leveraged_flag"],
                "inverse_flag": meta["inverse_flag"],
                "high_risk_secondary_flag": meta["high_risk_secondary_flag"],
                "raw_contract_count": len(raw),
                "clean_contract_count": clean_count,
                "expiration_count": len(expirations),
                "call_count": sum(1 for row in clean if str(row.get("call_put", "")).upper().startswith("C")),
                "put_count": sum(1 for row in clean if str(row.get("call_put", "")).upper().startswith("P")),
                "valid_bid_ask_count": valid_bid_ask,
                "valid_bid_ask_ratio": round(valid_bid_ask / clean_count, 6) if clean_count else 0,
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
                "nearest_expiration": expirations[0] if expirations else "",
                "farthest_expiration": expirations[-1] if expirations else "",
                "liquidity_coverage_status": status,
                "quote_enrichment_required": quote_required,
                "candidate_generation_allowed": candidate_allowed,
                "primary_blocker": primary,
                "secondary_blockers": ";".join(secondary),
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_allowed": False,
                "research_only": True,
                "reason": "Last price is non-tradable; candidate generation requires bid/ask, spread, IV, Greeks, volume, and open interest.",
            }
        )
    return rows


def readiness_rows(liquidity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in liquidity:
        has_chain = int(row["clean_contract_count"]) > 0
        has_quotes = int(row["valid_bid_ask_count"]) > 0 and int(row["valid_mid_count"]) > 0 and int(row["valid_spread_pct_count"]) > 0
        has_iv = int(row["valid_iv_count"]) > 0
        has_greeks = int(row["valid_greeks_count"]) > 0
        has_volume = int(row["valid_volume_count"]) > 0
        has_oi = int(row["valid_open_interest_count"]) > 0
        has_required = all([has_chain, has_quotes, has_iv, has_greeks, has_volume, has_oi])
        if has_required:
            status = "READY"
            next_step = "Proceed to research-only candidate module gates."
        elif not has_chain:
            status = "BLOCKED_NO_CHAIN"
            next_step = "Fetch chain structure in an approved read-only snapshot module."
        elif not has_quotes:
            status = "BLOCKED_NO_QUOTES"
            next_step = "Run quote enrichment before candidate generation."
        else:
            status = "BLOCKED_MISSING_REQUIRED_FIELDS"
            next_step = "Repair missing IV/Greeks/volume/open-interest coverage."
        rows.append(
            {
                "underlying": row["underlying"],
                "has_chain_structure": has_chain,
                "has_usable_quotes": has_quotes,
                "has_usable_iv": has_iv,
                "has_usable_greeks": has_greeks,
                "has_usable_volume": has_volume,
                "has_usable_open_interest": has_oi,
                "has_required_candidate_fields": has_required,
                "readiness_status": status,
                "next_required_step": next_step,
                "reason": "Readiness is blocked until all required quote and liquidity fields are usable.",
            }
        )
    return rows


def field_blocker_rows(clean_rows: list[dict[str, str]], source_field_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    source_by_field = {row.get("field_name", ""): row for row in source_field_rows}
    total = len(clean_rows)
    fields = list(dict.fromkeys(REQUIRED_CANDIDATE_FIELDS + [row.get("field_name", "") for row in source_field_rows if row.get("field_name")]))
    rows: list[dict[str, Any]] = []
    for field in fields:
        source = source_by_field.get(field, {})
        clean_count = int(float(source.get("clean_non_null_count", "0") or 0)) if source else sum(1 for row in clean_rows if non_null(row, field))
        ratio = float(source.get("clean_coverage_ratio", "0") or 0) if source else (clean_count / total if total else 0)
        required_candidate = field in REQUIRED_CANDIDATE_FIELDS
        triggered = required_candidate and clean_count == 0
        rows.append(
            {
                "field_name": field,
                "required_for_candidate_generation": required_candidate,
                "required_for_liquidity_audit": field in LIQUIDITY_FIELDS,
                "required_for_greeks_audit": field in GREEKS_FIELDS,
                "clean_non_null_count": clean_count,
                "clean_coverage_ratio": round(ratio, 6),
                "blocker_triggered": triggered,
                "blocker_severity": "BLOCKING" if triggered else "INFO",
                "blocker_reason": "Required candidate field is missing from all clean rows." if triggered else "Field has some coverage or is not required for candidate generation.",
                "recommended_repair": "Run V22.032_R1 option quote enrichment from Moomoo read-only." if triggered else "Monitor coverage in downstream audits.",
            }
        )
    return rows


def candidate_gate_rows(field_blockers: list[dict[str, Any]], liquidity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gate_specs = [
        ("BID_ASK_GATE", ["bid", "ask"]),
        ("MID_PRICE_GATE", ["mid"]),
        ("SPREAD_GATE", ["spread_pct"]),
        ("IV_GATE", ["implied_volatility"]),
        ("GREEKS_GATE", ["delta", "gamma", "theta", "vega"]),
        ("VOLUME_OI_GATE", ["volume", "open_interest"]),
        ("LEVERAGED_ETF_HIGH_RISK_GATE", []),
        ("INVERSE_ETF_HIGH_RISK_GATE", []),
        ("NO_BROKER_ACTION_GATE", []),
        ("NO_TRADE_GATE", []),
    ]
    blocker_by_field = {row["field_name"]: row for row in field_blockers}
    rows: list[dict[str, Any]] = []
    affected_all = len(liquidity)
    for name, fields in gate_specs:
        missing = [field for field in fields if blocker_by_field.get(field, {}).get("blocker_triggered") is True]
        if name == "LEVERAGED_ETF_HIGH_RISK_GATE":
            affected = sum(1 for row in liquidity if row["high_risk_secondary_flag"] is True)
            passed = True
            status = "PASS_RESEARCH_ONLY_HIGH_RISK_REVIEW_REQUIRED"
            reason = "Leveraged ETFs remain high-risk secondary and require manual review."
        elif name == "INVERSE_ETF_HIGH_RISK_GATE":
            affected = sum(1 for row in liquidity if row["inverse_flag"] is True)
            passed = True
            status = "PASS_RESEARCH_ONLY_INVERSE_REVIEW_REQUIRED"
            reason = "Inverse ETFs remain high-risk secondary and require inverse exposure review."
        elif name in {"NO_BROKER_ACTION_GATE", "NO_TRADE_GATE"}:
            affected = 0
            passed = True
            status = "PASS_GATE_CLOSED"
            reason = "Broker and trade gates are closed."
        else:
            affected = affected_all if missing else 0
            passed = not missing
            status = "PASS" if passed else "BLOCKED_REQUIRED_FIELDS_MISSING"
            reason = "Required fields available." if passed else "Required quote/liquidity fields are missing."
        rows.append(
            {
                "gate_name": name,
                "gate_status": status,
                "gate_passed": passed,
                "blocker_count": len(missing),
                "required_fields_missing": ";".join(missing),
                "affected_underlying_count": affected,
                "candidate_generation_allowed": False,
                "option_quote_enrichment_required": bool(missing),
                "next_required_module": "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY" if missing else "",
                "reason": reason,
            }
        )
    return rows


def summary_payload(repo_root: Path, source_summary: dict[str, Any], raw_rows: list[dict[str, str]], clean_rows: list[dict[str, str]], liquidity: list[dict[str, Any]], field_blockers: list[dict[str, Any]]) -> dict[str, Any]:
    flags = input_flags(repo_root)
    required_ok = flags["v22_032_summary_input_exists"] and flags["v22_032_clean_input_exists"]
    total_valid_bid_ask = sum(int(row["valid_bid_ask_count"]) for row in liquidity)
    ready_count = sum(1 for row in liquidity if row["liquidity_coverage_status"] == "READY_FOR_CANDIDATE_GENERATION")
    clean_count = int(source_summary.get("clean_contract_row_count", len(clean_rows)) or 0)
    quote_blockers = [row for row in field_blockers if row["field_name"] in QUOTE_ENRICHMENT_FIELDS and row["blocker_triggered"] is True]
    if not required_ok:
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif clean_count > 0 and total_valid_bid_ask == 0:
        final_status = WARN_STRUCTURE_ONLY
        final_decision = READY_DECISION
    elif clean_count == 0:
        final_status = WARN_NO_USABLE
        final_decision = READY_DECISION
    elif ready_count > 0:
        final_status = PASS_STATUS
        final_decision = READY_DECISION
    else:
        final_status = WARN_STRUCTURE_ONLY
        final_decision = READY_DECISION
    quote_enrichment_required = bool(quote_blockers) or total_valid_bid_ask == 0
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        **flags,
        "source_execution_mode": source_summary.get("execution_mode", "UNKNOWN"),
        "target_underlying_count": int(source_summary.get("target_underlying_count", len(liquidity)) or 0),
        "raw_contract_row_count": int(source_summary.get("raw_contract_row_count", len(raw_rows)) or 0),
        "clean_contract_row_count": clean_count,
        "underlying_with_chain_structure_count": sum(1 for row in liquidity if int(row["clean_contract_count"]) > 0),
        "underlying_ready_for_candidate_generation_count": ready_count,
        "underlying_blocked_no_quotes_count": sum(1 for row in liquidity if row["liquidity_coverage_status"] == "STRUCTURE_ONLY_NO_QUOTES"),
        "underlying_blocked_no_chain_count": sum(1 for row in liquidity if row["liquidity_coverage_status"] == "MISSING_CHAIN"),
        "total_expiration_count": sum(int(row["expiration_count"]) for row in liquidity),
        "total_valid_bid_ask_count": total_valid_bid_ask,
        "total_valid_mid_count": sum(int(row["valid_mid_count"]) for row in liquidity),
        "total_valid_spread_pct_count": sum(int(row["valid_spread_pct_count"]) for row in liquidity),
        "total_valid_iv_count": sum(int(row["valid_iv_count"]) for row in liquidity),
        "total_valid_greeks_count": sum(int(row["valid_greeks_count"]) for row in liquidity),
        "total_valid_volume_count": sum(int(row["valid_volume_count"]) for row in liquidity),
        "total_valid_open_interest_count": sum(int(row["valid_open_interest_count"]) for row in liquidity),
        "required_candidate_field_blocker_count": sum(1 for row in field_blockers if row["required_for_candidate_generation"] is True and row["blocker_triggered"] is True),
        "candidate_generation_allowed_count": sum(1 for row in liquidity if row["candidate_generation_allowed"] is True),
        "quote_enrichment_required_count": sum(1 for row in liquidity if row["quote_enrichment_required"] is True),
        "option_quote_enrichment_required": quote_enrichment_required,
        "broker_action_allowed_count": 0,
        "official_adoption_allowed_count": 0,
        "trade_allowed_count": 0,
        "protected_outputs_modified": False,
        "research_only": True,
        "next_recommended_modules": NEXT_RECOMMENDED_MODULES,
        **NO_ACTION_GATES,
    }


def risk_gate_payload(candidate_generation_allowed: bool) -> dict[str, Any]:
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        **NO_ACTION_GATES,
        "candidate_generation_allowed": candidate_generation_allowed,
        "allowed_side_effects": ["create_outputs_v22_033_only"],
        "forbidden_side_effects": [
            "execute_daily_chain",
            "connect_moomoo",
            "fetch_market_data",
            "fetch_option_chain",
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
        "V22.033 Option Chain Liquidity And Coverage Audit",
        f"module_id={summary['module_id']}",
        f"module_name={summary['module_name']}",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"source_execution_mode={summary['source_execution_mode']}",
        f"clean_contract_row_count={summary['clean_contract_row_count']}",
        f"total_valid_bid_ask_count={summary['total_valid_bid_ask_count']}",
        f"underlying_ready_for_candidate_generation_count={summary['underlying_ready_for_candidate_generation_count']}",
        f"option_quote_enrichment_required={summary['option_quote_enrichment_required']}",
        "candidate_generation_allowed=False",
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
    field_source = read_csv_rows(repo_root / FIELD_COVERAGE_INPUT)
    universe = read_csv_rows(repo_root / UNIVERSE_INPUT)
    _contracts = read_csv_rows(repo_root / CONTRACT_INPUT)

    meta = universe_meta(universe, underlying_source, clean_rows) if flags["v22_032_clean_input_exists"] else []
    liquidity = liquidity_rows(meta, raw_rows, clean_rows)
    readiness = readiness_rows(liquidity)
    field_blockers = field_blocker_rows(clean_rows, field_source)
    gates = candidate_gate_rows(field_blockers, liquidity)
    summary = summary_payload(repo_root, source_summary, raw_rows, clean_rows, liquidity, field_blockers)

    write_csv(output_dir / "v22_option_chain_liquidity_coverage_audit.csv", LIQUIDITY_FIELDNAMES, liquidity)
    write_csv(output_dir / "v22_option_chain_underlying_readiness_audit.csv", READINESS_FIELDNAMES, readiness)
    write_csv(output_dir / "v22_option_chain_field_blocker_audit.csv", FIELD_BLOCKER_FIELDNAMES, field_blockers)
    write_csv(output_dir / "v22_option_chain_candidate_generation_gate.csv", GATE_FIELDNAMES, gates)
    write_json(output_dir / "v22_option_chain_liquidity_coverage_summary.json", summary)
    write_json(output_dir / "v22_option_chain_liquidity_coverage_risk_gate.json", risk_gate_payload(summary["candidate_generation_allowed_count"] > 0))
    (output_dir / "V22.033_option_chain_liquidity_and_coverage_audit_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true", help="Accepted for wrapper consistency; this module never fetches or connects.")
    args = parser.parse_args(argv)
    payload = run(args.repo_root)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_option_chain_liquidity_coverage_summary.json'}")
    print("candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("trade_allowed=False")
    return 1 if payload["final_status"] == FAIL_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
