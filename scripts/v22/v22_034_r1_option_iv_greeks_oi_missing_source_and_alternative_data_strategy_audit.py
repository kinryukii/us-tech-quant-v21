#!/usr/bin/env python
"""V22.034_R1 IV/Greeks/OI missing-source and alternative-data strategy audit.

This diagnostic stage reads local V22 option audit artifacts only. It explains
whether IV, Greeks, and open interest are absent because of schema, values, or
mapping, then recommends research-only next steps. It never fetches data,
connects to a broker, mutates prior outputs, generates candidates, or trades.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


MODULE_ID = "V22.034_R1"
MODULE_NAME = "OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
STAGE = "V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_033_R1_DIR = Path("outputs") / "v22" / "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_AFTER_CHAIN_DISCOVERY"
V22_032_R1_READ_ONLY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"

PASS_AVAILABLE = "PASS_V22_034_R1_PROVIDER_IV_GREEKS_OI_AVAILABLE"
WARN_SYNTHETIC_NEXT = "WARN_V22_034_R1_PROVIDER_IV_GREEKS_OI_MISSING_SYNTHETIC_RESEARCH_NEXT_STEP"
WARN_LIQUIDITY_ONLY = "WARN_V22_034_R1_LIQUIDITY_ONLY_RESEARCH_SCREEN_ALLOWED_FULL_SELECTION_BLOCKED"
FAIL_INPUT_NOT_FOUND = "FAIL_V22_034_R1_INPUT_NOT_FOUND"
READY_DECISION = "OPTION_IV_GREEKS_OI_MISSING_SOURCE_AUDIT_READY_RESEARCH_ONLY"
FAIL_DECISION = "OPTION_IV_GREEKS_OI_MISSING_SOURCE_AUDIT_BLOCKED_INPUT_NOT_FOUND"

ALIAS_GROUPS = {
    "bid": ["bid", "option_bid"],
    "ask": ["ask", "option_ask"],
    "mid": ["mid", "mid_price", "option_mid"],
    "spread": ["spread", "spread_pct", "bid_ask_spread", "option_spread_pct"],
    "volume": ["volume", "vol", "option_volume"],
    "implied_volatility": ["iv", "implied_vol", "implied_volatility", "implied_volatility_pct", "option_iv", "option_implied_vol", "imp_vol", "imp_volatility"],
    "delta": ["delta", "option_delta", "greek_delta"],
    "gamma": ["gamma", "option_gamma", "greek_gamma"],
    "theta": ["theta", "option_theta", "greek_theta"],
    "vega": ["vega", "option_vega", "greek_vega"],
    "rho": ["rho", "option_rho", "greek_rho"],
    "open_interest": ["open_interest", "oi", "openint", "open_int", "option_open_interest", "option_oi"],
    "underlying_price": ["underlying_price", "spot", "spot_price", "underlying_last", "underlying_close"],
    "strike": ["strike", "option_strike"],
    "expiration": ["expiration", "expiry", "expire_date", "expiration_date"],
    "call_put": ["call_put", "put_call", "option_type", "cp"],
    "option_code": ["option_code", "symbol", "option_symbol"],
}

TARGET_FIELDS = ["implied_volatility", "delta", "gamma", "theta", "vega", "rho", "open_interest"]
CAPABILITIES = ["BID_ASK", "MID", "SPREAD", "VOLUME", "IMPLIED_VOLATILITY", "DELTA", "GAMMA", "THETA", "VEGA", "RHO", "OPEN_INTEREST"]

RAW_SCHEMA_FIELDNAMES = [
    "filename",
    "row_count",
    "column_count",
    "columns_present",
    "normalized_columns_present",
    "bid_schema_present",
    "ask_schema_present",
    "mid_schema_present",
    "volume_schema_present",
    "implied_volatility_schema_present",
    "delta_schema_present",
    "gamma_schema_present",
    "theta_schema_present",
    "vega_schema_present",
    "rho_schema_present",
    "open_interest_schema_present",
]

ALIAS_FIELDNAMES = [
    "target_field",
    "alias_matched",
    "matched_column",
    "source_file",
    "non_null_count",
    "valid_numeric_count",
    "positive_count",
    "zero_count",
    "missing_count",
    "coverage_ratio",
    "observed_min",
    "observed_max",
    "status",
]

CAPABILITY_FIELDNAMES = [
    "capability",
    "provider",
    "observed_schema_status",
    "observed_value_status",
    "valid_count",
    "total_contract_count",
    "coverage_ratio",
    "capability_status",
]

CLASSIFICATION_FIELDNAMES = [
    "missing_family",
    "missing_source_classification",
    "raw_alias_present",
    "clean_alias_present",
    "any_alias_present",
    "all_values_null",
    "all_numeric_values_zero",
    "reason",
]

STRATEGY_FIELDNAMES = [
    "missing_family",
    "recommended_strategy",
    "required_inputs",
    "implementation_allowed_in_v22_034_r1",
    "candidate_generation_allowed",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_order_allowed",
    "reason",
]

POLICY_FIELDNAMES = [
    "quotes_ready",
    "liquidity_ready",
    "iv_ready",
    "greeks_ready",
    "oi_ready",
    "full_option_candidate_generation_allowed",
    "liquidity_only_research_screen_allowed",
    "synthetic_iv_greeks_research_next_step_allowed",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_order_allowed",
    "final_policy_label",
]


def normalize_column_name(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[\s\-/()]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def numeric(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def discover_input_files(repo_root: Path) -> list[Path]:
    roots = [repo_root / V22_033_R1_DIR, repo_root / V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR, repo_root / V22_032_R1_READ_ONLY_DIR]
    discovered: list[Path] = []
    relevant_tokens = ("quote", "enrichment", "liquidity", "coverage", "option")
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.csv")) + sorted(root.glob("*.json")):
            lower = path.name.lower()
            if path.suffix.lower() == ".json" and "summary" not in lower:
                continue
            if path.suffix.lower() == ".csv" and not any(token in lower for token in relevant_tokens):
                continue
            discovered.append(path)
    return discovered


def alias_match(columns: list[str], target_field: str) -> tuple[str, str]:
    normalized = {normalize_column_name(column): column for column in columns}
    for alias in ALIAS_GROUPS[target_field]:
        key = normalize_column_name(alias)
        if key in normalized:
            return key, normalized[key]
    return "", ""


def inspect_schema(path: Path, rows: list[dict[str, str]], columns: list[str]) -> dict[str, Any]:
    normalized = [normalize_column_name(column) for column in columns]
    row = {
        "filename": path.name,
        "row_count": len(rows),
        "column_count": len(columns),
        "columns_present": ";".join(columns),
        "normalized_columns_present": ";".join(normalized),
    }
    for field in ["bid", "ask", "mid", "volume", "implied_volatility", "delta", "gamma", "theta", "vega", "rho", "open_interest"]:
        alias, _column = alias_match(columns, field)
        row[f"{field}_schema_present"] = bool(alias)
    return row


def compute_field_coverage(rows: list[dict[str, str]], column: str) -> dict[str, Any]:
    values = [row.get(column, "") for row in rows]
    numbers = [numeric(value) for value in values if str(value).strip() != ""]
    numeric_values = [value for value in numbers if value is not None]
    non_null_count = sum(1 for value in values if str(value).strip() != "")
    zero_count = sum(1 for value in numeric_values if value == 0)
    positive_count = sum(1 for value in numeric_values if value > 0)
    missing_count = len(values) - non_null_count
    return {
        "non_null_count": non_null_count,
        "valid_numeric_count": len(numeric_values),
        "positive_count": positive_count,
        "zero_count": zero_count,
        "missing_count": missing_count,
        "coverage_ratio": round(non_null_count / len(values), 6) if values else 0.0,
        "observed_min": min(numeric_values) if numeric_values else "",
        "observed_max": max(numeric_values) if numeric_values else "",
    }


def coverage_status(coverage: dict[str, Any], row_count: int, positive_required: bool = False) -> str:
    if coverage["non_null_count"] == 0:
        return "PRESENT_BUT_ALL_NULL"
    if coverage["valid_numeric_count"] == 0:
        return "PRESENT_BUT_NON_NUMERIC"
    if coverage["zero_count"] == coverage["valid_numeric_count"]:
        return "PRESENT_BUT_ALL_ZERO"
    if positive_required and coverage["positive_count"] == 0:
        return "PRESENT_BUT_ALL_ZERO"
    if row_count > 0:
        return "PRESENT_AND_USABLE"
    return "PRESENT_BUT_ALL_NULL"


def build_alias_mapping_audit(csv_payloads: list[tuple[Path, list[dict[str, str]], list[str]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in TARGET_FIELDS:
        matched = False
        for path, data, columns in csv_payloads:
            alias, column = alias_match(columns, target)
            if not alias:
                continue
            matched = True
            coverage = compute_field_coverage(data, column)
            rows.append(
                {
                    "target_field": target,
                    "alias_matched": alias,
                    "matched_column": column,
                    "source_file": path.name,
                    **coverage,
                    "status": coverage_status(coverage, len(data), positive_required=target in {"implied_volatility", "open_interest"}),
                }
            )
        if not matched:
            rows.append(
                {
                    "target_field": target,
                    "alias_matched": "",
                    "matched_column": "",
                    "source_file": "",
                    "non_null_count": 0,
                    "valid_numeric_count": 0,
                    "positive_count": 0,
                    "zero_count": 0,
                    "missing_count": 0,
                    "coverage_ratio": 0.0,
                    "observed_min": "",
                    "observed_max": "",
                    "status": "MISSING_FROM_SCHEMA",
                }
            )
    return rows


def is_contract_quote_file(path: Path, columns: list[str]) -> bool:
    normalized = {normalize_column_name(column) for column in columns}
    return bool({"option_code", "strike", "expiration"}.intersection(normalized)) and bool({"bid", "ask", "mid", "volume"}.intersection(normalized))


def merged_contract_rows(csv_payloads: list[tuple[Path, list[dict[str, str]], list[str]]]) -> list[dict[str, str]]:
    clean_payloads = [(path, rows, columns) for path, rows, columns in csv_payloads if "clean" in path.name.lower() and is_contract_quote_file(path, columns)]
    source = clean_payloads or [(path, rows, columns) for path, rows, columns in csv_payloads if is_contract_quote_file(path, columns)]
    merged: list[dict[str, str]] = []
    for _path, rows, _columns in source:
        merged.extend(rows)
    return merged


def valid_numeric_count(rows: list[dict[str, str]], field: str, positive: bool = False) -> int:
    columns = list(rows[0].keys()) if rows else []
    _alias, column = alias_match(columns, field)
    if not column:
        return 0
    values = [numeric(row.get(column)) for row in rows]
    if positive:
        return sum(1 for value in values if value is not None and value > 0)
    return sum(1 for value in values if value is not None)


def bid_ask_count(rows: list[dict[str, str]]) -> int:
    if not rows:
        return 0
    _bid_alias, bid_col = alias_match(list(rows[0].keys()), "bid")
    _ask_alias, ask_col = alias_match(list(rows[0].keys()), "ask")
    if not bid_col or not ask_col:
        return 0
    count = 0
    for row in rows:
        bid = numeric(row.get(bid_col))
        ask = numeric(row.get(ask_col))
        if bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid:
            count += 1
    return count


def capability_from_count(capability: str, schema_present: bool, valid_count: int, total: int, zero_only: bool = False) -> dict[str, Any]:
    if total == 0:
        status = "UNKNOWN_INPUT_NOT_FOUND"
        schema_status = "UNKNOWN_INPUT_NOT_FOUND"
        value_status = "UNKNOWN_INPUT_NOT_FOUND"
    elif not schema_present:
        status = "PROVIDER_SCHEMA_MISSING_OR_UNSUPPORTED"
        schema_status = "MISSING"
        value_status = "NOT_AVAILABLE"
    elif valid_count > 0:
        status = "PROVIDER_AVAILABLE_AND_USABLE"
        schema_status = "PRESENT"
        value_status = "USABLE"
    elif zero_only:
        status = "PROVIDER_SCHEMA_PRESENT_BUT_VALUES_ZERO"
        schema_status = "PRESENT"
        value_status = "ALL_ZERO"
    else:
        status = "PROVIDER_SCHEMA_PRESENT_BUT_VALUES_EMPTY"
        schema_status = "PRESENT"
        value_status = "EMPTY"
    return {
        "capability": capability,
        "provider": "MOOMOO",
        "observed_schema_status": schema_status,
        "observed_value_status": value_status,
        "valid_count": valid_count,
        "total_contract_count": total,
        "coverage_ratio": round(valid_count / total, 6) if total else 0.0,
        "capability_status": status,
    }


def build_provider_capability_audit(contract_rows: list[dict[str, str]], alias_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(contract_rows)
    columns = list(contract_rows[0].keys()) if contract_rows else []
    alias_status = {row["target_field"]: row for row in alias_rows if row["source_file"]}
    rows = [
        capability_from_count("BID_ASK", bool(alias_match(columns, "bid")[1] and alias_match(columns, "ask")[1]), bid_ask_count(contract_rows), total),
        capability_from_count("MID", bool(alias_match(columns, "mid")[1]), valid_numeric_count(contract_rows, "mid", positive=True), total),
        capability_from_count("SPREAD", bool(alias_match(columns, "spread")[1]), valid_numeric_count(contract_rows, "spread"), total),
        capability_from_count("VOLUME", bool(alias_match(columns, "volume")[1]), valid_numeric_count(contract_rows, "volume"), total),
    ]
    for capability, target in [
        ("IMPLIED_VOLATILITY", "implied_volatility"),
        ("DELTA", "delta"),
        ("GAMMA", "gamma"),
        ("THETA", "theta"),
        ("VEGA", "vega"),
        ("RHO", "rho"),
        ("OPEN_INTEREST", "open_interest"),
    ]:
        field = alias_status.get(target)
        schema_present = bool(field)
        valid_count = int(field["positive_count"] if target in {"implied_volatility", "open_interest"} and field else field["valid_numeric_count"] if field else 0)
        zero_only = bool(field and field["status"] == "PRESENT_BUT_ALL_ZERO")
        rows.append(capability_from_count(capability, schema_present, valid_count, total, zero_only=zero_only))
    return rows


def classify_missing_source(family: str, csv_payloads: list[tuple[Path, list[dict[str, str]], list[str]]]) -> dict[str, Any]:
    targets = ["implied_volatility"] if family == "IMPLIED_VOLATILITY" else ["open_interest"] if family == "OPEN_INTEREST" else ["delta", "gamma", "theta", "vega"]
    if not csv_payloads:
        classification = "INPUT_ARTIFACT_NOT_DISCOVERED"
        return {"missing_family": family, "missing_source_classification": classification, "raw_alias_present": False, "clean_alias_present": False, "any_alias_present": False, "all_values_null": False, "all_numeric_values_zero": False, "reason": "No relevant input artifact was discovered."}
    raw_present = False
    clean_present = False
    any_present = False
    coverages: list[dict[str, Any]] = []
    for path, rows, columns in csv_payloads:
        for target in targets:
            _alias, column = alias_match(columns, target)
            if not column:
                continue
            any_present = True
            if "raw" in path.name.lower():
                raw_present = True
            if "clean" in path.name.lower() or "liquidity" in path.name.lower():
                clean_present = True
            coverages.append(compute_field_coverage(rows, column))
    if raw_present and not clean_present:
        classification = "FIELD_MAPPING_ISSUE_POSSIBLE"
        reason = "Raw artifact has aliases but clean/audit artifact lacks mapped target fields."
    elif not any_present:
        classification = "PROVIDER_SCHEMA_MISSING_OR_UNSUPPORTED"
        reason = "No alias column exists in discovered raw/enriched artifacts."
    elif coverages and all(item["non_null_count"] == 0 for item in coverages):
        classification = "PROVIDER_VALUE_EMPTY_OR_PERMISSION_LIMITED"
        reason = "Alias columns are present but values are blank/null."
    elif coverages and all(item["valid_numeric_count"] > 0 and item["zero_count"] == item["valid_numeric_count"] for item in coverages):
        classification = "PROVIDER_VALUE_ZERO_OR_MARKET_DATA_LIMITED"
        reason = "Alias columns are present but numeric values are all zero."
    else:
        classification = "UNKNOWN_REQUIRES_MANUAL_PROVIDER_CHECK"
        reason = "Observed aliases and values are mixed; manual provider documentation check is required."
    return {
        "missing_family": family,
        "missing_source_classification": classification,
        "raw_alias_present": raw_present,
        "clean_alias_present": clean_present,
        "any_alias_present": any_present,
        "all_values_null": bool(coverages and all(item["non_null_count"] == 0 for item in coverages)),
        "all_numeric_values_zero": bool(coverages and all(item["valid_numeric_count"] > 0 and item["zero_count"] == item["valid_numeric_count"] for item in coverages)),
        "reason": reason,
    }


def build_alternative_data_strategy_audit(classifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in classifications:
        family = item["missing_family"]
        if family == "IMPLIED_VOLATILITY":
            strategy = "LOCAL_SYNTHETIC_IV_RESEARCH_ONLY"
            required = "underlying spot price; option mid price; strike; expiration; option type; risk-free rate assumption; dividend yield assumption or zero-dividend fallback; Black-Scholes or American approximation marked research-only"
        elif family == "GREEKS":
            strategy = "LOCAL_SYNTHETIC_GREEKS_RESEARCH_ONLY_AFTER_SYNTHETIC_IV"
            required = "synthetic IV; underlying spot price; option mid price; strike; expiration; option type; risk-free rate; dividend assumption; delta/gamma/theta/vega from the same assumptions"
        else:
            strategy = "KEEP_OI_UNAVAILABLE_AND_BLOCK_FULL_SELECTION_OR_ADD_EXTERNAL_OI_PROVIDER_RESEARCH_ONLY"
            required = "explicit external OI provider research gate; no scraping; no fake OI; no volume-as-OI substitution"
        rows.append(
            {
                "missing_family": family,
                "recommended_strategy": strategy,
                "required_inputs": required,
                "implementation_allowed_in_v22_034_r1": False,
                "candidate_generation_allowed": False,
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_order_allowed": False,
                "reason": f"Classification={item['missing_source_classification']}; this module audits strategy only.",
            }
        )
    return rows


def has_contract_metadata(rows: list[dict[str, str]]) -> bool:
    if not rows:
        return False
    columns = list(rows[0].keys())
    required = ["strike", "expiration", "call_put", "option_code"]
    return all(alias_match(columns, field)[1] for field in required)


def has_underlying_price(rows: list[dict[str, str]], json_payloads: list[dict[str, Any]] | None = None) -> bool:
    if not rows:
        return False
    _alias, column = alias_match(list(rows[0].keys()), "underlying_price")
    row_price_available = bool(column and any(numeric(row.get(column)) is not None and numeric(row.get(column)) > 0 for row in rows))
    summary_price_available = any(int(payload.get("underlying_enriched_count", 0) or 0) > 0 for payload in (json_payloads or []))
    return row_price_available or summary_price_available


def build_candidate_generation_policy(capability_rows: list[dict[str, Any]], contract_rows: list[dict[str, str]], json_payloads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by_cap = {row["capability"]: row for row in capability_rows}
    quotes_ready = by_cap.get("BID_ASK", {}).get("capability_status") == "PROVIDER_AVAILABLE_AND_USABLE"
    liquidity_ready = all(by_cap.get(cap, {}).get("capability_status") == "PROVIDER_AVAILABLE_AND_USABLE" for cap in ["BID_ASK", "MID", "SPREAD", "VOLUME"])
    iv_ready = by_cap.get("IMPLIED_VOLATILITY", {}).get("capability_status") == "PROVIDER_AVAILABLE_AND_USABLE"
    greeks_ready = all(by_cap.get(cap, {}).get("capability_status") == "PROVIDER_AVAILABLE_AND_USABLE" for cap in ["DELTA", "GAMMA", "THETA", "VEGA"])
    oi_ready = by_cap.get("OPEN_INTEREST", {}).get("capability_status") == "PROVIDER_AVAILABLE_AND_USABLE"
    synthetic_next = liquidity_ready and has_contract_metadata(contract_rows) and has_underlying_price(contract_rows, json_payloads)
    if not contract_rows:
        label = "FAIL_INPUT_NOT_FOUND"
    elif synthetic_next and not (iv_ready and greeks_ready and oi_ready):
        label = "ALLOW_SYNTHETIC_IV_GREEKS_RESEARCH_DESIGN_ONLY"
    elif liquidity_ready and not (iv_ready and greeks_ready and oi_ready):
        label = "ALLOW_LIQUIDITY_ONLY_RESEARCH_SCREEN"
    else:
        label = "BLOCK_FULL_OPTION_SELECTION_PROVIDER_IV_GREEKS_OI_MISSING"
    return {
        "quotes_ready": quotes_ready,
        "liquidity_ready": liquidity_ready,
        "iv_ready": iv_ready,
        "greeks_ready": greeks_ready,
        "oi_ready": oi_ready,
        "full_option_candidate_generation_allowed": False,
        "liquidity_only_research_screen_allowed": liquidity_ready,
        "synthetic_iv_greeks_research_next_step_allowed": synthetic_next,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_order_allowed": False,
        "final_policy_label": label,
    }


def write_summary(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "v22_034_r1_summary.json", payload)


def report_text(summary: dict[str, Any]) -> str:
    lines = [
        "V22.034_R1 Option IV/Greeks/OI Missing Source And Alternative Data Strategy Audit",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"discovered_input_file_count={summary['discovered_input_file_count']}",
        f"discovered_contract_row_count={summary['discovered_contract_row_count']}",
        f"total_valid_bid_ask_count={summary['total_valid_bid_ask_count']}",
        f"total_valid_volume_count={summary['total_valid_volume_count']}",
        f"total_valid_iv_count={summary['total_valid_iv_count']}",
        f"total_valid_greeks_count={summary['total_valid_greeks_count']}",
        f"total_valid_open_interest_count={summary['total_valid_open_interest_count']}",
        f"iv_missing_source_classification={summary['iv_missing_source_classification']}",
        f"greeks_missing_source_classification={summary['greeks_missing_source_classification']}",
        f"oi_missing_source_classification={summary['oi_missing_source_classification']}",
        f"liquidity_only_research_screen_allowed={summary['liquidity_only_research_screen_allowed']}",
        f"synthetic_iv_greeks_research_next_step_allowed={summary['synthetic_iv_greeks_research_next_step_allowed']}",
        "full_option_candidate_generation_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_order_allowed=False",
    ]
    return "\n".join(lines) + "\n"


def run(repo_root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = (output_dir or (repo_root / OUT_REL)).resolve()
    expected_default = (repo_root / OUT_REL).resolve()
    if output_dir != expected_default and expected_default not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {expected_default}")
    output_dir.mkdir(parents=True, exist_ok=True)

    discovered = discover_input_files(repo_root)
    csv_payloads: list[tuple[Path, list[dict[str, str]], list[str]]] = []
    json_payloads: list[dict[str, Any]] = []
    for path in discovered:
        if path.suffix.lower() == ".csv":
            rows, columns = read_csv_rows(path)
            if columns:
                csv_payloads.append((path, rows, columns))
        elif path.suffix.lower() == ".json":
            json_payloads.append(read_json(path))

    schema_rows = [inspect_schema(path, rows, columns) for path, rows, columns in csv_payloads]
    alias_rows = build_alias_mapping_audit(csv_payloads)
    contract_rows = merged_contract_rows(csv_payloads)
    capability_rows = build_provider_capability_audit(contract_rows, alias_rows)
    classifications = [classify_missing_source(family, csv_payloads) for family in ["IMPLIED_VOLATILITY", "GREEKS", "OPEN_INTEREST"]]
    strategy_rows = build_alternative_data_strategy_audit(classifications)
    policy = build_candidate_generation_policy(capability_rows, contract_rows, json_payloads)

    classification_by_family = {row["missing_family"]: row["missing_source_classification"] for row in classifications}
    total_delta = valid_numeric_count(contract_rows, "delta")
    total_gamma = valid_numeric_count(contract_rows, "gamma")
    total_theta = valid_numeric_count(contract_rows, "theta")
    total_vega = valid_numeric_count(contract_rows, "vega")
    if not contract_rows:
        final_status = FAIL_INPUT_NOT_FOUND
        final_decision = FAIL_DECISION
    elif all(policy[key] for key in ["iv_ready", "greeks_ready", "oi_ready"]):
        final_status = PASS_AVAILABLE
        final_decision = READY_DECISION
    elif policy["synthetic_iv_greeks_research_next_step_allowed"]:
        final_status = WARN_SYNTHETIC_NEXT
        final_decision = READY_DECISION
    else:
        final_status = WARN_LIQUIDITY_ONLY
        final_decision = READY_DECISION

    summary = {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "input_v22_033_dir": str(repo_root / V22_033_R1_DIR),
        "input_v22_032_dir": str(repo_root / V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR),
        "discovered_input_file_count": len(discovered),
        "discovered_contract_row_count": len(contract_rows),
        "total_valid_bid_ask_count": bid_ask_count(contract_rows),
        "total_valid_mid_count": valid_numeric_count(contract_rows, "mid", positive=True),
        "total_valid_volume_count": valid_numeric_count(contract_rows, "volume"),
        "total_valid_iv_count": valid_numeric_count(contract_rows, "implied_volatility", positive=True),
        "total_valid_delta_count": total_delta,
        "total_valid_gamma_count": total_gamma,
        "total_valid_theta_count": total_theta,
        "total_valid_vega_count": total_vega,
        "total_valid_greeks_count": min(total_delta, total_gamma, total_theta, total_vega),
        "total_valid_rho_count": valid_numeric_count(contract_rows, "rho"),
        "total_valid_open_interest_count": valid_numeric_count(contract_rows, "open_interest", positive=True),
        "iv_missing_source_classification": classification_by_family["IMPLIED_VOLATILITY"],
        "greeks_missing_source_classification": classification_by_family["GREEKS"],
        "oi_missing_source_classification": classification_by_family["OPEN_INTEREST"],
        **policy,
    }

    write_csv(output_dir / "option_raw_quote_schema_audit.csv", RAW_SCHEMA_FIELDNAMES, schema_rows)
    write_csv(output_dir / "option_field_alias_mapping_audit.csv", ALIAS_FIELDNAMES, alias_rows)
    write_csv(output_dir / "option_provider_capability_audit.csv", CAPABILITY_FIELDNAMES, capability_rows)
    write_csv(output_dir / "option_iv_greeks_oi_missing_source_classification.csv", CLASSIFICATION_FIELDNAMES, classifications)
    write_csv(output_dir / "option_alternative_data_strategy_audit.csv", STRATEGY_FIELDNAMES, strategy_rows)
    write_csv(output_dir / "option_candidate_generation_policy_after_missing_data_audit.csv", POLICY_FIELDNAMES, [policy])
    write_summary(output_dir, summary)
    (output_dir / "V22.034_R1_option_iv_greeks_oi_missing_source_and_alternative_data_strategy_audit_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="Accepted for wrapper consistency; this audit remains read-only.")
    args = parser.parse_args(argv)
    payload = run(args.repo_root, args.output_dir)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_034_r1_summary.json'}")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if payload["final_status"] == FAIL_INPUT_NOT_FOUND else 0


if __name__ == "__main__":
    raise SystemExit(main())
