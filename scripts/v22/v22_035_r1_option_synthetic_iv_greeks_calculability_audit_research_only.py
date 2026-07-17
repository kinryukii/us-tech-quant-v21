#!/usr/bin/env python
"""V22.035_R1 synthetic IV/Greeks calculability audit.

Research-only local audit of whether option rows contain enough inputs for a
future synthetic IV and Greeks calculation stage. This module does not compute
IV, compute Greeks, generate candidates, fetch data, connect to brokers, or
mutate prior V22 outputs.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


MODULE_ID = "V22.035_R1"
MODULE_NAME = "OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_RESEARCH_ONLY"
STAGE = "V22.035_R1_OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

V22_034_R1_DIR = Path("outputs") / "v22" / "V22.034_R1_OPTION_IV_GREEKS_OI_MISSING_SOURCE_AND_ALTERNATIVE_DATA_STRATEGY_AUDIT"
V22_033_R1_DIR = Path("outputs") / "v22" / "V22.033_R1_OPTION_CHAIN_LIQUIDITY_AND_COVERAGE_AUDIT_AFTER_QUOTE_ENRICHMENT"
V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_AFTER_CHAIN_DISCOVERY"
V22_032_R1_READ_ONLY_DIR = Path("outputs") / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY"

PASS_READY = "PASS_V22_035_R1_SYNTHETIC_IV_GREEKS_CALCULABILITY_READY_RESEARCH_ONLY"
WARN_PARTIAL = "WARN_V22_035_R1_LIQUIDITY_READY_SYNTHETIC_FIELDS_PARTIAL"
WARN_INCOMPLETE = "WARN_V22_035_R1_SYNTHETIC_INPUTS_INCOMPLETE_FULL_SELECTION_BLOCKED"
FAIL_INPUT_NOT_FOUND = "FAIL_V22_035_R1_INPUT_NOT_FOUND"
READY_DECISION = "OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_READY_RESEARCH_ONLY"
FAIL_DECISION = "OPTION_SYNTHETIC_IV_GREEKS_CALCULABILITY_AUDIT_BLOCKED_INPUT_NOT_FOUND"

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
    "underlying_spot": ["underlying_spot", "underlying_price", "stock_price", "spot", "spot_price", "last_underlying_price", "underlying_last", "underlying_price_raw"],
    "valuation_date": ["valuation_date", "quote_date", "trade_date", "asof_date", "snapshot_date", "timestamp", "quote_timestamp", "enrichment_time_utc", "snapshot_time_utc"],
    "dte": ["dte", "days_to_expiry", "days_to_expiration", "time_to_expiry_days"],
    "open_interest": ["open_interest", "oi", "openint", "open_int", "option_open_interest", "option_oi", "open_interest_raw"],
}

REQUIRED_FIELD_COLUMNS = [
    "option_code",
    "underlying_symbol",
    "expiration",
    "strike",
    "option_type",
    "bid",
    "ask",
    "mid",
    "volume",
    "underlying_spot",
    "valuation_date",
    "dte",
    "has_contract_identity",
    "has_valid_market_price",
    "has_valid_contract_metadata",
    "has_valid_underlying_spot",
    "has_valid_time_to_expiry",
    "has_model_assumption_inputs",
    "synthetic_iv_calculable",
    "synthetic_greeks_calculable_after_iv",
    "missing_required_fields",
    "calculability_status",
]

ALIAS_AUDIT_COLUMNS = [
    "target_field",
    "matched_column",
    "alias_matched",
    "source_file",
    "present",
    "non_null_count",
    "valid_numeric_count",
    "usable_count",
    "coverage_ratio",
    "status",
]

DTE_COLUMNS = ["option_code", "expiration", "valuation_date", "observed_dte", "computed_dte", "final_audit_dte", "dte_status"]

MODEL_POLICY_COLUMNS = [
    "model_family",
    "american_option_limitation",
    "early_exercise_not_modeled",
    "risk_free_rate_policy",
    "dividend_yield_policy",
    "calendar_policy",
    "timestamp_alignment_policy",
    "option_price_policy",
    "numerical_solver_policy",
    "synthetic_iv_floor_policy",
    "synthetic_iv_cap_policy",
    "greeks_dependency_policy",
    "oi_policy",
]

BY_UNDERLYING_COLUMNS = [
    "underlying_symbol",
    "total_contract_count",
    "valid_bid_ask_count",
    "valid_mid_count",
    "valid_volume_count",
    "valid_underlying_spot_count",
    "valid_contract_metadata_count",
    "valid_dte_count",
    "synthetic_iv_calculable_count",
    "synthetic_greeks_calculable_after_iv_count",
    "synthetic_iv_calculable_ratio",
    "synthetic_greeks_calculable_ratio",
    "liquidity_only_research_screen_allowed",
    "synthetic_iv_greeks_research_calculation_next_step_allowed",
    "full_option_candidate_generation_allowed",
]

POLICY_COLUMNS = [
    "quotes_ready",
    "liquidity_ready",
    "synthetic_iv_calculability_ready",
    "synthetic_greeks_calculability_ready",
    "provider_oi_ready",
    "synthetic_oi_available",
    "full_option_candidate_generation_allowed",
    "liquidity_only_research_screen_allowed",
    "synthetic_iv_greeks_research_calculation_next_step_allowed",
    "broker_action_allowed",
    "official_adoption_allowed",
    "trade_order_allowed",
    "final_policy_label",
]


def normalize_column_name(name: str) -> str:
    text = str(name).strip().lower()
    text = re.sub(r"[\s\-/().]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def discover_input_files(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / V22_034_R1_DIR,
        repo_root / V22_033_R1_DIR,
        repo_root / V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR,
        repo_root / V22_032_R1_READ_ONLY_DIR,
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.csv")):
            try:
                columns = list(pd.read_csv(path, nrows=0).columns)
            except (pd.errors.EmptyDataError, UnicodeDecodeError, OSError):
                continue
            resolved = resolve_alias_columns(columns)
            contract_like = bool(resolved.get("option_code") and resolved.get("underlying_symbol") and resolved.get("expiration") and resolved.get("strike"))
            quote_like = bool(resolved.get("bid") and resolved.get("ask") and (resolved.get("mid") or resolved.get("volume")))
            if contract_like and quote_like:
                files.append(path)
    return files


def resolve_alias_columns(columns: list[str]) -> dict[str, str]:
    normalized_to_original = {normalize_column_name(column): column for column in columns}
    resolved: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            normalized = normalize_column_name(alias)
            if normalized in normalized_to_original:
                resolved[target] = normalized_to_original[normalized]
                break
    return resolved


def parse_option_type(value: Any) -> str:
    text = str(value).strip().upper()
    if text in {"C", "CALL"}:
        return "CALL"
    if text in {"P", "PUT"}:
        return "PUT"
    return ""


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


def parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return pd.to_datetime(text, utc=False).date()
    except (ValueError, TypeError):
        return None


def compute_audit_dte(observed_dte: Any, expiration: Any, valuation_date: Any) -> tuple[float | None, str]:
    source_dte = parse_numeric(observed_dte)
    if source_dte is not None:
        if source_dte > 0:
            return source_dte, "DTE_USABLE_FROM_SOURCE"
        return source_dte, "DTE_INVALID_OR_EXPIRED"
    exp = parse_date(expiration)
    val = parse_date(valuation_date)
    if exp is None:
        return None, "DTE_MISSING_EXPIRATION"
    if val is None:
        return None, "DTE_MISSING_VALUATION_DATE"
    computed = (exp - val).days
    if computed <= 0:
        return float(computed), "DTE_INVALID_OR_EXPIRED"
    return float(computed), "DTE_COMPUTED_FROM_EXPIRATION_AND_VALUATION_DATE"


def read_contract_rows(files: list[Path]) -> tuple[pd.DataFrame, dict[str, str], str]:
    if not files:
        return pd.DataFrame(), {}, ""
    preferred = sorted(files, key=lambda p: (0 if "clean" in p.name.lower() else 1, str(p)))[0]
    frame = pd.read_csv(preferred, dtype=str, keep_default_na=False)
    return frame, resolve_alias_columns(list(frame.columns)), preferred.name


def value(row: pd.Series, aliases: dict[str, str], target: str) -> Any:
    column = aliases.get(target)
    return row.get(column, "") if column else ""


def has_valid_bid_ask(row: pd.Series, aliases: dict[str, str]) -> bool:
    bid = parse_numeric(value(row, aliases, "bid"))
    ask = parse_numeric(value(row, aliases, "ask"))
    return bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid


def has_valid_mid(row: pd.Series, aliases: dict[str, str]) -> bool:
    mid = parse_numeric(value(row, aliases, "mid"))
    return mid is not None and mid > 0


def has_valid_volume(row: pd.Series, aliases: dict[str, str]) -> bool:
    return parse_numeric(value(row, aliases, "volume")) is not None


def audit_required_fields(frame: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        option_code = str(value(source, aliases, "option_code")).strip()
        underlying = str(value(source, aliases, "underlying_symbol")).strip()
        expiration = str(value(source, aliases, "expiration")).strip()
        strike = parse_numeric(value(source, aliases, "strike"))
        option_type = parse_option_type(value(source, aliases, "option_type"))
        bid = parse_numeric(value(source, aliases, "bid"))
        ask = parse_numeric(value(source, aliases, "ask"))
        mid = parse_numeric(value(source, aliases, "mid"))
        volume = parse_numeric(value(source, aliases, "volume"))
        spot = parse_numeric(value(source, aliases, "underlying_spot"))
        valuation = str(value(source, aliases, "valuation_date")).strip()
        dte_value, dte_status = compute_audit_dte(value(source, aliases, "dte"), expiration, valuation)
        has_identity = bool(option_code and underlying)
        has_market = has_valid_bid_ask(source, aliases) and mid is not None and mid > 0
        has_metadata = bool(strike is not None and strike > 0 and parse_date(expiration) is not None and option_type in {"CALL", "PUT"})
        has_spot = bool(spot is not None and spot > 0)
        has_time = bool(dte_value is not None and dte_value > 0 and dte_status != "DTE_INVALID_OR_EXPIRED")
        has_assumptions = True
        missing = []
        if not has_identity:
            missing.append("contract_identity")
        if not has_market:
            missing.append("market_price")
        if not has_metadata:
            missing.append("contract_metadata")
        if not has_spot:
            missing.append("underlying_spot")
        if not has_time:
            missing.append("time_to_expiry")
        if not has_assumptions:
            missing.append("model_assumptions")
        calculable = has_identity and has_market and has_metadata and has_spot and has_time and has_assumptions
        if calculable:
            status = "SYNTHETIC_IV_GREEKS_CALCULABLE_RESEARCH_ONLY"
        elif not has_identity:
            status = "MISSING_CONTRACT_IDENTITY"
        elif not has_market:
            status = "MISSING_MARKET_PRICE"
        elif not has_metadata:
            status = "MISSING_CONTRACT_METADATA"
        elif not has_spot:
            status = "MISSING_UNDERLYING_SPOT"
        elif dte_status == "DTE_INVALID_OR_EXPIRED":
            status = "INVALID_OR_EXPIRED_CONTRACT"
        elif not has_time:
            status = "MISSING_TIME_TO_EXPIRY"
        elif not has_assumptions:
            status = "MISSING_MODEL_ASSUMPTIONS"
        else:
            status = "UNKNOWN_INPUT_NOT_FOUND"
        rows.append(
            {
                "option_code": option_code,
                "underlying_symbol": underlying,
                "expiration": expiration,
                "strike": strike if strike is not None else "",
                "option_type": option_type,
                "bid": bid if bid is not None else "",
                "ask": ask if ask is not None else "",
                "mid": mid if mid is not None else "",
                "volume": volume if volume is not None else "",
                "underlying_spot": spot if spot is not None else "",
                "valuation_date": valuation,
                "dte": dte_value if dte_value is not None else "",
                "has_contract_identity": has_identity,
                "has_valid_market_price": has_market,
                "has_valid_contract_metadata": has_metadata,
                "has_valid_underlying_spot": has_spot,
                "has_valid_time_to_expiry": has_time,
                "has_model_assumption_inputs": has_assumptions,
                "synthetic_iv_calculable": calculable,
                "synthetic_greeks_calculable_after_iv": calculable,
                "missing_required_fields": ";".join(missing),
                "calculability_status": status,
            }
        )
    return pd.DataFrame(rows, columns=REQUIRED_FIELD_COLUMNS)


def build_dte_audit(frame: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        expiration = str(value(source, aliases, "expiration")).strip()
        valuation = str(value(source, aliases, "valuation_date")).strip()
        observed = value(source, aliases, "dte")
        dte_value, status = compute_audit_dte(observed, expiration, valuation)
        computed = ""
        if parse_numeric(observed) is None and parse_date(expiration) is not None and parse_date(valuation) is not None:
            computed = float((parse_date(expiration) - parse_date(valuation)).days)  # type: ignore[operator]
        rows.append(
            {
                "option_code": str(value(source, aliases, "option_code")).strip(),
                "expiration": expiration,
                "valuation_date": valuation,
                "observed_dte": parse_numeric(observed) if parse_numeric(observed) is not None else "",
                "computed_dte": computed,
                "final_audit_dte": dte_value if dte_value is not None else "",
                "dte_status": status,
            }
        )
    return pd.DataFrame(rows, columns=DTE_COLUMNS)


def build_field_alias_audit(files: list[Path]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    targets = list(ALIASES)
    for target in targets:
        added = False
        for path in files:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            aliases = resolve_alias_columns(list(frame.columns))
            column = aliases.get(target, "")
            if not column:
                continue
            added = True
            series = frame[column].astype(str).str.strip()
            non_null = int((series != "").sum())
            numeric_count = int(series.map(lambda item: parse_numeric(item) is not None).sum()) if target in {"strike", "bid", "ask", "mid", "volume", "underlying_spot", "dte"} else 0
            if target == "option_type":
                usable = int(series.map(lambda item: parse_option_type(item) in {"CALL", "PUT"}).sum())
            elif target in {"strike", "bid", "ask", "mid", "underlying_spot"}:
                usable = int(series.map(lambda item: (parse_numeric(item) or 0) > 0).sum())
            elif target in {"volume", "dte"}:
                usable = numeric_count
            elif target in {"expiration", "valuation_date"}:
                usable = int(series.map(lambda item: parse_date(item) is not None).sum())
            else:
                usable = non_null
            rows.append(
                {
                    "target_field": target,
                    "matched_column": column,
                    "alias_matched": normalize_column_name(column),
                    "source_file": path.name,
                    "present": True,
                    "non_null_count": non_null,
                    "valid_numeric_count": numeric_count,
                    "usable_count": usable,
                    "coverage_ratio": round(non_null / len(frame), 6) if len(frame) else 0.0,
                    "status": "PRESENT_AND_USABLE" if usable > 0 else "PRESENT_BUT_NOT_USABLE",
                }
            )
        if not added:
            rows.append(
                {
                    "target_field": target,
                    "matched_column": "",
                    "alias_matched": "",
                    "source_file": "",
                    "present": False,
                    "non_null_count": 0,
                    "valid_numeric_count": 0,
                    "usable_count": 0,
                    "coverage_ratio": 0.0,
                    "status": "MISSING_FROM_SCHEMA",
                }
            )
    return pd.DataFrame(rows, columns=ALIAS_AUDIT_COLUMNS)


def build_model_assumption_policy() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_family": "BLACK_SCHOLES_RESEARCH_ONLY_BASELINE",
                "american_option_limitation": True,
                "early_exercise_not_modeled": True,
                "risk_free_rate_policy": "CONSTANT_ASSUMPTION_REQUIRED_NOT_IMPLEMENTED_IN_V22_035",
                "dividend_yield_policy": "ZERO_DIVIDEND_FALLBACK_ALLOWED_RESEARCH_ONLY",
                "calendar_policy": "CALENDAR_DAYS_BASELINE_AUDIT_ONLY",
                "timestamp_alignment_policy": "REQUIRE_SAME_DAY_OR_EXPLICIT_ASOF_ALIGNMENT",
                "option_price_policy": "USE_MID_PRICE_ONLY_IF_VALID_BID_ASK",
                "numerical_solver_policy": "FUTURE_VERSION_ONLY_DO_NOT_SOLVE_IN_V22_035",
                "synthetic_iv_floor_policy": "FUTURE_VERSION_REQUIRED",
                "synthetic_iv_cap_policy": "FUTURE_VERSION_REQUIRED",
                "greeks_dependency_policy": "GREEKS_REQUIRE_SYNTHETIC_IV_FIRST",
                "oi_policy": "OI_UNAVAILABLE_FULL_SELECTION_REMAINS_BLOCKED",
            }
        ],
        columns=MODEL_POLICY_COLUMNS,
    )


def build_by_underlying_summary(required: pd.DataFrame) -> pd.DataFrame:
    if required.empty:
        return pd.DataFrame(columns=BY_UNDERLYING_COLUMNS)
    rows: list[dict[str, Any]] = []
    for underlying, group in required.groupby("underlying_symbol", dropna=False):
        total = len(group)
        iv_count = int(group["synthetic_iv_calculable"].sum())
        greeks_count = int(group["synthetic_greeks_calculable_after_iv"].sum())
        liquidity = bool((group["has_valid_market_price"] & group["volume"].map(lambda item: parse_numeric(item) is not None)).any())
        rows.append(
            {
                "underlying_symbol": underlying,
                "total_contract_count": total,
                "valid_bid_ask_count": int(group["has_valid_market_price"].sum()),
                "valid_mid_count": int(group["mid"].map(lambda item: parse_numeric(item) is not None and parse_numeric(item) > 0).sum()),
                "valid_volume_count": int(group["volume"].map(lambda item: parse_numeric(item) is not None).sum()),
                "valid_underlying_spot_count": int(group["has_valid_underlying_spot"].sum()),
                "valid_contract_metadata_count": int(group["has_valid_contract_metadata"].sum()),
                "valid_dte_count": int(group["has_valid_time_to_expiry"].sum()),
                "synthetic_iv_calculable_count": iv_count,
                "synthetic_greeks_calculable_after_iv_count": greeks_count,
                "synthetic_iv_calculable_ratio": round(iv_count / total, 6) if total else 0.0,
                "synthetic_greeks_calculable_ratio": round(greeks_count / total, 6) if total else 0.0,
                "liquidity_only_research_screen_allowed": liquidity,
                "synthetic_iv_greeks_research_calculation_next_step_allowed": iv_count > 0,
                "full_option_candidate_generation_allowed": False,
            }
        )
    return pd.DataFrame(rows, columns=BY_UNDERLYING_COLUMNS)


def build_candidate_generation_safety_policy(required: pd.DataFrame, by_underlying: pd.DataFrame) -> dict[str, Any]:
    if required.empty:
        label = "FAIL_INPUT_NOT_FOUND"
        quotes_ready = liquidity_ready = calc_ready = greeks_ready = liquidity_only = calc_next = False
    else:
        quotes_ready = bool(required["has_valid_market_price"].any())
        liquidity_ready = bool((required["has_valid_market_price"] & required["volume"].map(lambda item: parse_numeric(item) is not None)).any())
        calc_ready = bool(required["synthetic_iv_calculable"].any())
        greeks_ready = bool(required["synthetic_greeks_calculable_after_iv"].any())
        liquidity_only = liquidity_ready
        calc_next = bool(not by_underlying.empty and by_underlying["synthetic_iv_greeks_research_calculation_next_step_allowed"].any())
        if calc_next:
            label = "ALLOW_SYNTHETIC_IV_GREEKS_RESEARCH_CALCULATION_NEXT_STEP_FULL_SELECTION_BLOCKED"
        elif liquidity_only:
            label = "ALLOW_LIQUIDITY_ONLY_RESEARCH_SCREEN_SYNTHETIC_FIELDS_INCOMPLETE"
        else:
            label = "BLOCK_SYNTHETIC_IV_GREEKS_INPUTS_INCOMPLETE"
    return {
        "quotes_ready": quotes_ready,
        "liquidity_ready": liquidity_ready,
        "synthetic_iv_calculability_ready": calc_ready,
        "synthetic_greeks_calculability_ready": greeks_ready,
        "provider_oi_ready": False,
        "synthetic_oi_available": False,
        "full_option_candidate_generation_allowed": False,
        "liquidity_only_research_screen_allowed": liquidity_only,
        "synthetic_iv_greeks_research_calculation_next_step_allowed": calc_next,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_order_allowed": False,
        "final_policy_label": label,
    }


def write_summary_and_report(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "v22_035_r1_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "V22.035_R1 Option Synthetic IV/Greeks Calculability Audit Research Only",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"discovered_contract_row_count={summary['discovered_contract_row_count']}",
        f"underlying_count={summary['underlying_count']}",
        f"valid_bid_ask_count={summary['valid_bid_ask_count']}",
        f"valid_mid_count={summary['valid_mid_count']}",
        f"valid_volume_count={summary['valid_volume_count']}",
        f"valid_underlying_spot_count={summary['valid_underlying_spot_count']}",
        f"valid_contract_metadata_count={summary['valid_contract_metadata_count']}",
        f"valid_dte_count={summary['valid_dte_count']}",
        f"synthetic_iv_calculable_count={summary['synthetic_iv_calculable_count']}",
        f"synthetic_greeks_calculable_after_iv_count={summary['synthetic_greeks_calculable_after_iv_count']}",
        f"synthetic_iv_greeks_research_calculation_next_step_allowed={summary['synthetic_iv_greeks_research_calculation_next_step_allowed']}",
        "full_option_candidate_generation_allowed=False",
        "broker_action_allowed=False",
        "official_adoption_allowed=False",
        "trade_order_allowed=False",
    ]
    (output_dir / "V22.035_R1_option_synthetic_iv_greeks_calculability_audit_research_only_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    default_output = (repo_root / OUT_REL).resolve()
    output_dir = (output_dir or default_output).resolve()
    if output_dir != default_output and default_output not in output_dir.parents:
        raise ValueError(f"OutputDir must be under {default_output}")
    output_dir.mkdir(parents=True, exist_ok=True)

    files = discover_input_files(repo_root)
    contract_frame, aliases, _source_file = read_contract_rows(files)
    required = audit_required_fields(contract_frame, aliases) if not contract_frame.empty else pd.DataFrame(columns=REQUIRED_FIELD_COLUMNS)
    alias_audit = build_field_alias_audit(files)
    dte_audit = build_dte_audit(contract_frame, aliases) if not contract_frame.empty else pd.DataFrame(columns=DTE_COLUMNS)
    model_policy = build_model_assumption_policy()
    by_underlying = build_by_underlying_summary(required)
    policy = build_candidate_generation_safety_policy(required, by_underlying)

    if required.empty:
        final_status = FAIL_INPUT_NOT_FOUND
        final_decision = FAIL_DECISION
    elif int(required["synthetic_iv_calculable"].sum()) > 0:
        final_status = PASS_READY
        final_decision = READY_DECISION
    elif policy["liquidity_only_research_screen_allowed"]:
        final_status = WARN_PARTIAL
        final_decision = READY_DECISION
    else:
        final_status = WARN_INCOMPLETE
        final_decision = READY_DECISION

    summary = {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": final_status,
        "final_decision": final_decision,
        "input_v22_034_dir": str(repo_root / V22_034_R1_DIR),
        "input_v22_033_dir": str(repo_root / V22_033_R1_DIR),
        "input_v22_032_dir": str(repo_root / V22_032_R1_AFTER_CHAIN_DISCOVERY_DIR),
        "discovered_input_file_count": len(files),
        "discovered_contract_row_count": len(required),
        "underlying_count": int(required["underlying_symbol"].replace("", pd.NA).dropna().nunique()) if not required.empty else 0,
        "valid_bid_ask_count": int(required["has_valid_market_price"].sum()) if not required.empty else 0,
        "valid_mid_count": int(required["mid"].map(lambda item: parse_numeric(item) is not None and parse_numeric(item) > 0).sum()) if not required.empty else 0,
        "valid_volume_count": int(required["volume"].map(lambda item: parse_numeric(item) is not None).sum()) if not required.empty else 0,
        "valid_underlying_spot_count": int(required["has_valid_underlying_spot"].sum()) if not required.empty else 0,
        "valid_contract_metadata_count": int(required["has_valid_contract_metadata"].sum()) if not required.empty else 0,
        "valid_dte_count": int(required["has_valid_time_to_expiry"].sum()) if not required.empty else 0,
        "synthetic_iv_calculable_count": int(required["synthetic_iv_calculable"].sum()) if not required.empty else 0,
        "synthetic_greeks_calculable_after_iv_count": int(required["synthetic_greeks_calculable_after_iv"].sum()) if not required.empty else 0,
        "synthetic_iv_calculable_ratio": round(float(required["synthetic_iv_calculable"].sum()) / len(required), 6) if len(required) else 0.0,
        "synthetic_greeks_calculable_ratio": round(float(required["synthetic_greeks_calculable_after_iv"].sum()) / len(required), 6) if len(required) else 0.0,
        **policy,
    }

    required.to_csv(output_dir / "option_synthetic_iv_greeks_required_field_audit.csv", index=False, lineterminator="\n")
    alias_audit.to_csv(output_dir / "option_synthetic_field_alias_resolution_audit.csv", index=False, lineterminator="\n")
    dte_audit.to_csv(output_dir / "option_synthetic_dte_audit.csv", index=False, lineterminator="\n")
    model_policy.to_csv(output_dir / "option_synthetic_model_assumption_policy_audit.csv", index=False, lineterminator="\n")
    by_underlying.to_csv(output_dir / "option_synthetic_calculability_by_underlying.csv", index=False, lineterminator="\n")
    pd.DataFrame([policy], columns=POLICY_COLUMNS).to_csv(output_dir / "option_synthetic_candidate_generation_safety_policy.csv", index=False, lineterminator="\n")
    write_summary_and_report(output_dir, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="Accepted for wrapper consistency; this audit never calculates, fetches, or trades.")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.output_dir)
    print(f"final_status={summary['final_status']}")
    print(f"final_decision={summary['final_decision']}")
    print(f"summary_path={(args.output_dir or (args.repo_root / OUT_REL)) / 'v22_035_r1_summary.json'}")
    print("full_option_candidate_generation_allowed=False")
    print("broker_action_allowed=False")
    print("official_adoption_allowed=False")
    print("trade_order_allowed=False")
    return 1 if summary["final_status"] == FAIL_INPUT_NOT_FOUND else 0


if __name__ == "__main__":
    raise SystemExit(main())
