from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

REVISION = "V22.037_R2B"
OUTPUT_DIR_NAME = "V22.037_R2B_SYNTHETIC_IV_GREEKS_TIMESTAMP_PROVENANCE_REPAIR_AND_QUALITY_VALIDATION_RESEARCH_ONLY"
PASS_STATUS = "PASS_V22_037_R2B_SYNTHETIC_IV_GREEKS_RECALCULATED_AND_QUALITY_VALIDATED"
WARN_STATUS = "WARN_V22_037_R2B_SYNTHETIC_IV_GREEKS_RECALCULATED_WITH_QUALITY_WARNINGS"
FAIL_INPUT = "FAIL_V22_037_R2B_OPTION_INPUT_NOT_FOUND"
FAIL_NO_CALC = "FAIL_V22_037_R2B_NO_VALID_IV_GREEKS_CALCULATION"
FAIL_EXCEPTION = "FAIL_V22_037_R2B_UNHANDLED_EXCEPTION"
PASS_DECISION = "SYNTHETIC_IV_GREEKS_READY_FOR_RESEARCH_RANKING_ONLY"
WARN_DECISION = "SYNTHETIC_IV_GREEKS_AVAILABLE_WITH_QUALITY_FILTER_REQUIRED_RESEARCH_ONLY"
FAIL_DECISION = "SYNTHETIC_IV_GREEKS_BLOCKED_RESEARCH_ONLY"

RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False
BROKER_ACTION_ALLOWED = False

UTC = timezone.utc
ET = ZoneInfo("America/New_York")

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "contract_code": (
        "contract_code", "option_contract_code", "option_code", "code", "symbol", "option_symbol", "contract_symbol",
        "moomoo_symbol", "security_code",
    ),
    "underlying": (
        "underlying", "underlying_symbol", "underlying_ticker", "underlying_code", "root_symbol", "ticker", "stock_code",
    ),
    "option_type": (
        "option_type", "call_put", "cp", "put_call", "contract_type", "option_side", "option_direction", "type",
    ),
    "strike": ("strike", "strike_price", "exercise_price"),
    "expiry": (
        "expiry", "expiration", "expiration_date", "expiration_timestamp", "expiry_date", "expiry_timestamp",
        "maturity", "strike_time", "last_trade_date",
    ),
    "bid": ("bid", "bid_price", "bid_price_1", "best_bid", "bid1"),
    "ask": ("ask", "ask_price", "ask_price_1", "best_ask", "ask1"),
    "last": ("last", "last_price", "option_last_price", "option_price_for_iv", "market_price", "mid_price", "mark_price",
        "close", "price", "trade_price"),
    "spot": (
        "underlying_price", "underlying_spot", "spot", "spot_price", "underlying_last_price",
        "ref_underlying_price", "injected_underlying_price", "underlying_quote_price", "refreshed_underlying_spot",
        "underlying_spot_refreshed", "resolved_underlying_spot", "repaired_underlying_price",
        "underlying_price_after_injection", "underlying_price_after",
    ),
    "quote_time": (
        "quote_time", "quote_timestamp", "data_timestamp", "timestamp", "update_time", "option_quote_time",
        "option_quote_timestamp", "option_quote_timestamp_utc", "asof_timestamp", "snapshot_timestamp",
    ),
    "enrichment_time": (
        "enrichment_time_utc", "enrichment_time", "retrieval_time_utc", "retrieval_timestamp_utc",
        "fetch_time_utc", "fetch_timestamp_utc", "download_time_utc", "snapshot_created_utc",
    ),
    "underlying_quote_time": (
        "underlying_quote_time", "underlying_quote_timestamp", "spot_timestamp", "spot_quote_time",
        "underlying_timestamp", "underlying_quote_timestamp_utc", "injected_underlying_timestamp",
        "refreshed_underlying_quote_timestamp",
    ),
    "underlying_snapshot_age_minutes": (
        "underlying_snapshot_age_minutes", "underlying_quote_age_minutes", "spot_age_minutes",
        "underlying_age_minutes", "snapshot_age_minutes",
    ),
    "risk_free_rate": ("risk_free_rate", "r", "interest_rate", "annual_risk_free_rate"),
    "dividend_yield": ("dividend_yield", "q", "annual_dividend_yield"),
    "volume": ("volume", "option_volume", "trade_volume"),
    "open_interest": ("open_interest", "oi", "option_open_interest"),
    "lot_size": ("lot_size", "contract_size", "multiplier"),
}

OUTPUT_FIELDS = [
    "source_row_number", "contract_code", "underlying", "option_type", "strike", "expiry_timestamp_et",
    "valuation_timestamp_et", "valuation_time_source", "option_quote_timestamp_et", "enrichment_timestamp_et",
    "underlying_quote_timestamp_et", "underlying_quote_time_source", "underlying_snapshot_age_minutes",
    "valuation_timestamp_trust_pass", "days_to_expiry", "time_to_expiry_years",
    "bid", "ask", "last_price", "pricing_source", "option_market_price", "underlying_price",
    "risk_free_rate", "dividend_yield", "intrinsic_value", "lower_arbitrage_bound", "upper_arbitrage_bound",
    "moneyness_spot_over_strike", "log_moneyness", "spread_absolute", "spread_ratio_mid",
    "quote_alignment_seconds", "synthetic_iv", "model_price", "repricing_error_absolute",
    "repricing_error_ratio", "delta", "gamma", "vega_per_1vol_point", "theta_per_day", "rho_per_1pct",
    "iv_solver_iterations", "iv_solver_converged", "no_arbitrage_pass", "greeks_invariant_pass",
    "quote_quality_pass", "timestamp_alignment_pass", "quality_tier", "eligible_for_research_ranking",
    "quality_issue_count", "quality_flags", "model_name", "model_risk_note", "research_only",
    "official_adoption_allowed", "broker_action_allowed", "source_input_path",
]

VALIDATION_FIELDS = [
    "source_row_number", "contract_code", "underlying", "option_type", "check_name", "expected", "actual",
    "passed", "severity", "notes",
]

SUMMARY_BY_UNDERLYING_FIELDS = [
    "underlying", "input_row_count", "iv_solved_count", "ranking_eligible_count", "tier_a_count", "tier_b_count",
    "tier_c_count", "rejected_count", "iv_coverage_ratio", "ranking_eligible_ratio", "median_iv",
    "median_spread_ratio", "median_abs_delta", "median_gamma", "median_vega_per_1vol_point",
    "primary_quality_issue", "research_only", "official_adoption_allowed", "broker_action_allowed",
]

PARITY_FIELDS = [
    "underlying", "expiry_timestamp_et", "strike", "call_contract_code", "put_contract_code", "call_price",
    "put_price", "spot", "time_to_expiry_years", "risk_free_rate", "dividend_yield", "parity_lhs_call_minus_put",
    "parity_rhs_discounted_forward_intrinsic", "parity_error_absolute", "parity_error_ratio_spot",
    "parity_pass", "notes",
]

DISCOVERY_FIELDS = [
    "candidate_rank", "path", "exists", "size_bytes", "modified_utc", "header_score", "detected_fields",
    "selected", "selection_reason",
]
SCHEMA_FIELDS = [
    "canonical_field", "selected_source_column", "found", "requirement", "accepted_aliases", "notes",
]


@dataclass(frozen=True)
class Config:
    risk_free_rate: float = 0.043
    dividend_yield: float = 0.0
    min_iv: float = 0.0001
    max_iv: float = 8.0
    solver_tolerance: float = 1e-8
    solver_max_iterations: int = 200
    max_spread_ratio_for_pass: float = 0.50
    max_alignment_seconds_for_pass: float = 900.0
    min_days_to_expiry: float = 1.0 / 1440.0
    max_days_to_expiry: float = 730.0
    repricing_abs_tolerance: float = 0.01
    repricing_ratio_tolerance: float = 0.005
    pass_iv_coverage_ratio: float = 0.80
    pass_ranking_eligible_ratio: float = 0.60
    parity_abs_tolerance: float = 0.15
    parity_ratio_spot_tolerance: float = 0.0025


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "null", "n/a", "na", "--"}:
        return None
    text = text.rstrip("%")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    return int(number) if number is not None else None


def first_value(row: Mapping[str, Any], canonical: str) -> Any:
    lower = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in FIELD_ALIASES[canonical]:
        if alias.lower() in lower:
            value = lower[alias.lower()]
            if value is not None and str(value).strip() != "":
                return value
    return None


def parse_option_type(value: Any, contract_code: str = "") -> str | None:
    text = str(value or "").strip().upper()
    if text in {"C", "CALL", "CALLS", "1", "CALL_OPTION"}:
        return "CALL"
    if text in {"P", "PUT", "PUTS", "2", "PUT_OPTION"}:
        return "PUT"
    code = contract_code.upper()
    match = re.search(r"\d{6}([CP])\d", code)
    if match:
        return "CALL" if match.group(1) == "C" else "PUT"
    if re.search(r"(?:^|[._-])C(?:[._-]|$)", code):
        return "CALL"
    if re.search(r"(?:^|[._-])P(?:[._-]|$)", code):
        return "PUT"
    return None


def parse_underlying(value: Any, contract_code: str = "") -> str:
    text = str(value or "").strip().upper()
    if text.startswith("US."):
        text = text[3:]
    if text and not re.search(r"\d", text):
        return text
    code = contract_code.upper()
    code = code[3:] if code.startswith("US.") else code
    occ = re.match(r"([A-Z]{1,6})\d{6}[CP]\d{8}$", code)
    if occ:
        return occ.group(1)
    prefix = re.match(r"([A-Z]{1,6})", code)
    return prefix.group(1) if prefix else text


def parse_strike(value: Any, contract_code: str = "") -> float | None:
    strike = safe_float(value)
    if strike is not None and strike > 0:
        return strike
    code = contract_code.upper().replace("US.", "")
    match = re.match(r"[A-Z]{1,6}\d{6}[CP](\d{8})$", code)
    if match:
        parsed = int(match.group(1)) / 1000.0
        return parsed if parsed > 0 else None
    return None


def parse_expiry(value: Any, contract_code: str = "") -> datetime | None:
    raw = str(value or "").strip()
    formats = (
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
        "%Y/%m/%d", "%Y%m%d", "%y%m%d",
    )
    dt: datetime | None = None
    if raw:
        cleaned = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            for fmt in formats:
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
    if dt is None:
        code = contract_code.upper().replace("US.", "")
        match = re.match(r"[A-Z]{1,6}(\d{6})[CP]\d{8}$", code)
        if match:
            try:
                dt = datetime.strptime(match.group(1), "%y%m%d")
            except ValueError:
                return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        if dt.time() == time(0, 0):
            dt = datetime.combine(dt.date(), time(16, 0), tzinfo=ET)
        else:
            dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def parse_timestamp(value: Any, default_tz: ZoneInfo = ET) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = raw.replace("Z", "+00:00")
    candidates = [cleaned]
    if "." in cleaned and "+" not in cleaned[10:] and cleaned.count("-") <= 2:
        candidates.append(cleaned.split(".")[0])
    dt: datetime | None = None
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            break
        except ValueError:
            pass
    if dt is None:
        for fmt in (
            "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
            "%Y-%m-%d", "%Y/%m/%d",
        ):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(ET)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(option_type: str, spot: float, strike: float, t: float, rate: float, div: float, sigma: float) -> float:
    if min(spot, strike, t, sigma) <= 0:
        return float("nan")
    root_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * sigma * sigma) * t) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    disc_q = math.exp(-div * t)
    disc_r = math.exp(-rate * t)
    if option_type == "CALL":
        return spot * disc_q * norm_cdf(d1) - strike * disc_r * norm_cdf(d2)
    return strike * disc_r * norm_cdf(-d2) - spot * disc_q * norm_cdf(-d1)


def arbitrage_bounds(option_type: str, spot: float, strike: float, t: float, rate: float, div: float) -> tuple[float, float]:
    discounted_spot = spot * math.exp(-div * t)
    discounted_strike = strike * math.exp(-rate * t)
    if option_type == "CALL":
        return max(0.0, discounted_spot - discounted_strike), discounted_spot
    return max(0.0, discounted_strike - discounted_spot), discounted_strike


def implied_vol_bisection(
    option_type: str,
    market_price: float,
    spot: float,
    strike: float,
    t: float,
    rate: float,
    div: float,
    config: Config,
) -> tuple[float | None, int, str]:
    if min(market_price, spot, strike, t) <= 0:
        return None, 0, "NONPOSITIVE_INPUT"
    lower_bound, upper_bound = arbitrage_bounds(option_type, spot, strike, t, rate, div)
    bound_eps = max(config.repricing_abs_tolerance, market_price * config.repricing_ratio_tolerance)
    if market_price < lower_bound - bound_eps or market_price > upper_bound + bound_eps:
        return None, 0, "ARBITRAGE_BOUND_VIOLATION"
    low = config.min_iv
    high = config.max_iv
    low_price = bs_price(option_type, spot, strike, t, rate, div, low)
    high_price = bs_price(option_type, spot, strike, t, rate, div, high)
    if market_price < low_price - bound_eps:
        return None, 0, "MARKET_PRICE_BELOW_MODEL_MIN_IV"
    if market_price > high_price + bound_eps:
        return None, 0, "MARKET_PRICE_ABOVE_MODEL_MAX_IV"
    for iteration in range(1, config.solver_max_iterations + 1):
        mid = 0.5 * (low + high)
        value = bs_price(option_type, spot, strike, t, rate, div, mid)
        error = value - market_price
        if abs(error) <= config.solver_tolerance:
            return mid, iteration, "CONVERGED"
        if error > 0:
            high = mid
        else:
            low = mid
    mid = 0.5 * (low + high)
    value = bs_price(option_type, spot, strike, t, rate, div, mid)
    if abs(value - market_price) <= max(config.repricing_abs_tolerance, market_price * config.repricing_ratio_tolerance):
        return mid, config.solver_max_iterations, "CONVERGED_WITH_RELAXED_TOLERANCE"
    return None, config.solver_max_iterations, "MAX_ITERATIONS"


def bs_greeks(
    option_type: str, spot: float, strike: float, t: float, rate: float, div: float, sigma: float
) -> dict[str, float]:
    root_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * sigma * sigma) * t) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    disc_q = math.exp(-div * t)
    disc_r = math.exp(-rate * t)
    pdf = norm_pdf(d1)
    gamma = disc_q * pdf / (spot * sigma * root_t)
    vega = spot * disc_q * pdf * root_t / 100.0
    if option_type == "CALL":
        delta = disc_q * norm_cdf(d1)
        theta_annual = (
            -spot * disc_q * pdf * sigma / (2.0 * root_t)
            - rate * strike * disc_r * norm_cdf(d2)
            + div * spot * disc_q * norm_cdf(d1)
        )
        rho = strike * t * disc_r * norm_cdf(d2) / 100.0
    else:
        delta = -disc_q * norm_cdf(-d1)
        theta_annual = (
            -spot * disc_q * pdf * sigma / (2.0 * root_t)
            + rate * strike * disc_r * norm_cdf(-d2)
            - div * spot * disc_q * norm_cdf(-d1)
        )
        rho = -strike * t * disc_r * norm_cdf(-d2) / 100.0
    return {
        "delta": delta,
        "gamma": gamma,
        "vega_per_1vol_point": vega,
        "theta_per_day": theta_annual / 365.0,
        "rho_per_1pct": rho,
    }


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def intrinsic_value(option_type: str, spot: float, strike: float) -> float:
    return max(spot - strike, 0.0) if option_type == "CALL" else max(strike - spot, 0.0)


def choose_market_price(bid: float | None, ask: float | None, last: float | None) -> tuple[float | None, str]:
    if bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid:
        midpoint = 0.5 * (bid + ask)
        if midpoint > 0:
            return midpoint, "BID_ASK_MIDPOINT"
    if last is not None and last > 0:
        return last, "OPTION_LAST_PRICE_FALLBACK"
    if ask is not None and ask > 0:
        return ask, "ASK_FALLBACK"
    return None, "NO_VALID_OPTION_PRICE"


def convert_rate(value: Any, default: float) -> tuple[float, bool]:
    parsed = safe_float(value)
    if parsed is None:
        return default, True
    if abs(parsed) > 1.0:
        parsed /= 100.0
    return parsed, False


def format_number(value: Any, digits: int = 10) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return bool_text(value)
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.{digits}g}"
    return value


def validation_row(
    source_row_number: int,
    contract_code: str,
    underlying: str,
    option_type: str,
    check_name: str,
    expected: Any,
    actual: Any,
    passed: bool,
    severity: str,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "source_row_number": source_row_number,
        "contract_code": contract_code,
        "underlying": underlying,
        "option_type": option_type,
        "check_name": check_name,
        "expected": format_number(expected),
        "actual": format_number(actual),
        "passed": bool_text(passed),
        "severity": severity,
        "notes": notes,
    }


def recalculate_row(
    raw: Mapping[str, Any],
    source_row_number: int,
    source_input_path: Path,
    config: Config,
    valuation_time_override: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contract_code = str(first_value(raw, "contract_code") or "").strip()
    underlying = parse_underlying(first_value(raw, "underlying"), contract_code)
    option_type = parse_option_type(first_value(raw, "option_type"), contract_code) or ""
    strike = parse_strike(first_value(raw, "strike"), contract_code)
    expiry = parse_expiry(first_value(raw, "expiry"), contract_code)
    bid = safe_float(first_value(raw, "bid"))
    ask = safe_float(first_value(raw, "ask"))
    last = safe_float(first_value(raw, "last"))
    spot = safe_float(first_value(raw, "spot"))
    option_quote_time = parse_timestamp(first_value(raw, "quote_time"))
    enrichment_time = parse_timestamp(first_value(raw, "enrichment_time"))
    underlying_quote_time = parse_timestamp(first_value(raw, "underlying_quote_time"))
    underlying_snapshot_age_minutes = safe_float(first_value(raw, "underlying_snapshot_age_minutes"))
    underlying_quote_time_source = "EXPLICIT_UNDERLYING_QUOTE_TIMESTAMP" if underlying_quote_time is not None else ""
    if (
        underlying_quote_time is None
        and enrichment_time is not None
        and underlying_snapshot_age_minutes is not None
        and underlying_snapshot_age_minutes >= 0
    ):
        underlying_quote_time = enrichment_time - timedelta(minutes=underlying_snapshot_age_minutes)
        underlying_quote_time_source = "RECONSTRUCTED_FROM_ENRICHMENT_TIME_MINUS_SNAPSHOT_AGE"

    if valuation_time_override is not None:
        valuation_time = valuation_time_override
        valuation_time_source = "CLI_OVERRIDE"
    elif option_quote_time is not None:
        valuation_time = option_quote_time
        valuation_time_source = "EXPLICIT_OPTION_QUOTE_TIMESTAMP"
    elif enrichment_time is not None:
        valuation_time = enrichment_time
        valuation_time_source = "ENRICHMENT_TIME_UTC_FALLBACK"
    elif underlying_quote_time is not None:
        valuation_time = underlying_quote_time
        valuation_time_source = "UNDERLYING_QUOTE_TIMESTAMP_FALLBACK"
    else:
        valuation_time = datetime.now(ET)
        valuation_time_source = "RUNTIME_FALLBACK"
    valuation_timestamp_trust_pass = valuation_time_source in {"CLI_OVERRIDE", "EXPLICIT_OPTION_QUOTE_TIMESTAMP"}
    rate, rate_assumed = convert_rate(first_value(raw, "risk_free_rate"), config.risk_free_rate)
    div, div_assumed = convert_rate(first_value(raw, "dividend_yield"), config.dividend_yield)
    market_price, pricing_source = choose_market_price(bid, ask, last)

    validations: list[dict[str, Any]] = []
    flags: list[str] = []

    def add_check(name: str, expected: Any, actual: Any, passed: bool, severity: str, notes: str = "") -> None:
        validations.append(validation_row(
            source_row_number, contract_code, underlying, option_type, name, expected, actual, passed, severity, notes
        ))
        if not passed:
            flags.append(name.upper())

    add_check("contract_code_present", "non-empty", contract_code, bool(contract_code), "ERROR")
    add_check("underlying_present", "non-empty", underlying, bool(underlying), "ERROR")
    add_check("option_type_valid", "CALL|PUT", option_type, option_type in {"CALL", "PUT"}, "ERROR")
    add_check("strike_positive", ">0", strike, strike is not None and strike > 0, "ERROR")
    add_check("underlying_price_positive", ">0", spot, spot is not None and spot > 0, "ERROR",
              "Option last_price is never accepted as underlying spot.")
    add_check("option_market_price_positive", ">0", market_price,
              market_price is not None and market_price > 0, "ERROR", pricing_source)
    add_check("expiry_parseable", "valid ET timestamp", expiry.isoformat() if expiry else "", expiry is not None, "ERROR")

    t_years: float | None = None
    days_to_expiry: float | None = None
    if expiry is not None:
        seconds = (expiry - valuation_time.astimezone(ET)).total_seconds()
        days_to_expiry = seconds / 86400.0
        t_years = seconds / (365.0 * 86400.0)
    t_valid = (
        t_years is not None
        and days_to_expiry is not None
        and days_to_expiry >= config.min_days_to_expiry
        and days_to_expiry <= config.max_days_to_expiry
    )
    add_check("time_to_expiry_valid", f"{config.min_days_to_expiry}..{config.max_days_to_expiry} days",
              days_to_expiry, t_valid, "ERROR")
    add_check("valuation_timestamp_source_available", "non-runtime as-of timestamp",
              f"{valuation_time_source}:{valuation_time.isoformat()}",
              valuation_time_source != "RUNTIME_FALLBACK", "WARN",
              "enrichment_time_utc is accepted only as a disclosed historical as-of fallback.")
    add_check("valuation_timestamp_trust_pass", "explicit option quote timestamp or explicit CLI override",
              valuation_time_source, valuation_timestamp_trust_pass, "WARN",
              "Enrichment/retrieval time is not guaranteed to equal the exchange quote timestamp and cannot qualify for ranking.")
    add_check("underlying_quote_timestamp_source_available", "explicit or age-reconstructed timestamp",
              underlying_quote_time_source or "MISSING", underlying_quote_time is not None, "WARN",
              "Age reconstruction uses enrichment_time_utc - underlying_snapshot_age_minutes and remains approximate.")
    add_check("risk_free_rate_source_available", "source column preferred", rate,
              not rate_assumed, "WARN", "CLI/default assumption is disclosed when source rate is absent.")
    add_check("dividend_yield_source_available", "source column preferred", div,
              not div_assumed, "WARN", "ETF dividend yield assumption can affect synthetic IV and parity.")

    spread_abs: float | None = None
    spread_ratio: float | None = None
    quote_structure_valid = bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid
    if quote_structure_valid:
        spread_abs = ask - bid
        midpoint = 0.5 * (bid + ask)
        spread_ratio = spread_abs / midpoint if midpoint > 0 else None
    quote_quality_pass = quote_structure_valid and spread_ratio is not None and spread_ratio <= config.max_spread_ratio_for_pass
    add_check("bid_ask_structure_valid", "0<=bid<=ask", f"bid={bid};ask={ask}", quote_structure_valid, "WARN")
    add_check("spread_ratio_within_limit", f"<={config.max_spread_ratio_for_pass}", spread_ratio,
              quote_quality_pass, "WARN")

    alignment_seconds: float | None = None
    if valuation_time_source != "RUNTIME_FALLBACK" and underlying_quote_time is not None:
        alignment_seconds = abs((valuation_time - underlying_quote_time).total_seconds())
        alignment_pass = alignment_seconds <= config.max_alignment_seconds_for_pass
    else:
        alignment_pass = False
    add_check("option_underlying_timestamp_alignment", f"<={config.max_alignment_seconds_for_pass}s",
              alignment_seconds, alignment_pass, "WARN", "Missing timestamp is treated as a quality warning.")

    if valuation_time_source == "RUNTIME_FALLBACK":
        flags.append("VALUATION_TIME_RUNTIME_FALLBACK")
    elif valuation_time_source == "ENRICHMENT_TIME_UTC_FALLBACK":
        flags.append("VALUATION_TIME_ENRICHMENT_FALLBACK")
    elif valuation_time_source == "UNDERLYING_QUOTE_TIMESTAMP_FALLBACK":
        flags.append("VALUATION_TIME_UNDERLYING_FALLBACK")
    if underlying_quote_time_source == "RECONSTRUCTED_FROM_ENRICHMENT_TIME_MINUS_SNAPSHOT_AGE":
        flags.append("UNDERLYING_TIME_RECONSTRUCTED_FROM_AGE")
    if rate_assumed:
        flags.append("RISK_FREE_RATE_ASSUMED")
    if div_assumed:
        flags.append("DIVIDEND_YIELD_ASSUMED")
    if pricing_source != "BID_ASK_MIDPOINT":
        flags.append(pricing_source)

    lower_bound: float | None = None
    upper_bound: float | None = None
    intrinsic: float | None = None
    no_arbitrage_pass = False
    iv: float | None = None
    iterations = 0
    solver_status = "INPUT_INVALID"
    model_price: float | None = None
    repricing_abs: float | None = None
    repricing_ratio: float | None = None
    greeks = {
        "delta": None, "gamma": None, "vega_per_1vol_point": None, "theta_per_day": None,
        "rho_per_1pct": None,
    }
    greeks_invariant_pass = False

    core_valid = (
        option_type in {"CALL", "PUT"}
        and strike is not None and strike > 0
        and spot is not None and spot > 0
        and market_price is not None and market_price > 0
        and t_valid and t_years is not None
    )
    if core_valid:
        intrinsic = intrinsic_value(option_type, spot, strike)
        lower_bound, upper_bound = arbitrage_bounds(option_type, spot, strike, t_years, rate, div)
        bound_eps = max(config.repricing_abs_tolerance, market_price * config.repricing_ratio_tolerance)
        no_arbitrage_pass = lower_bound - bound_eps <= market_price <= upper_bound + bound_eps
        add_check("no_arbitrage_bounds", f"[{lower_bound},{upper_bound}]", market_price,
                  no_arbitrage_pass, "ERROR")
        iv, iterations, solver_status = implied_vol_bisection(
            option_type, market_price, spot, strike, t_years, rate, div, config
        )
        iv_converged = iv is not None
        add_check("iv_solver_converged", "True", solver_status, iv_converged, "ERROR")
        if iv is not None:
            model_price = bs_price(option_type, spot, strike, t_years, rate, div, iv)
            repricing_abs = abs(model_price - market_price)
            repricing_ratio = repricing_abs / market_price if market_price > 0 else None
            repricing_pass = (
                repricing_abs <= config.repricing_abs_tolerance
                or (repricing_ratio is not None and repricing_ratio <= config.repricing_ratio_tolerance)
            )
            add_check("repricing_error_within_tolerance",
                      f"abs<={config.repricing_abs_tolerance} or ratio<={config.repricing_ratio_tolerance}",
                      f"abs={repricing_abs};ratio={repricing_ratio}", repricing_pass, "ERROR")
            greeks = bs_greeks(option_type, spot, strike, t_years, rate, div, iv)
            delta = greeks["delta"]
            gamma = greeks["gamma"]
            vega = greeks["vega_per_1vol_point"]
            theta = greeks["theta_per_day"]
            rho = greeks["rho_per_1pct"]
            sign_pass = (
                all(finite(value) for value in (delta, gamma, vega, theta, rho))
                and gamma > 0
                and vega > 0
                and ((option_type == "CALL" and 0 <= delta <= 1 and rho >= 0)
                     or (option_type == "PUT" and -1 <= delta <= 0 and rho <= 0))
            )
            greeks_invariant_pass = sign_pass
            add_check("greeks_finite_and_sign_invariants", "finite; gamma>0; vega>0; delta/rho sign valid",
                      f"delta={delta};gamma={gamma};vega={vega};theta={theta};rho={rho}", sign_pass, "ERROR")
    else:
        add_check("core_calculation_inputs_valid", "True", "False", False, "ERROR")

    error_failures = [v for v in validations if v["passed"] == "False" and v["severity"] == "ERROR"]
    warn_failures = [v for v in validations if v["passed"] == "False" and v["severity"] == "WARN"]
    eligible = (
        iv is not None
        and not error_failures
        and quote_quality_pass
        and alignment_pass
        and valuation_timestamp_trust_pass
    )
    if eligible and not warn_failures:
        tier = "A"
    elif iv is not None and not error_failures and quote_quality_pass:
        tier = "B"
    elif iv is not None and not error_failures:
        tier = "C"
    else:
        tier = "REJECTED"

    moneyness = spot / strike if spot is not None and strike is not None and strike > 0 else None
    log_moneyness = math.log(moneyness) if moneyness is not None and moneyness > 0 else None
    issue_names = sorted(dict.fromkeys(flags))
    result = {
        "source_row_number": source_row_number,
        "contract_code": contract_code,
        "underlying": underlying,
        "option_type": option_type,
        "strike": strike,
        "expiry_timestamp_et": expiry.isoformat() if expiry else "",
        "valuation_timestamp_et": valuation_time.astimezone(ET).isoformat(),
        "valuation_time_source": valuation_time_source,
        "option_quote_timestamp_et": option_quote_time.astimezone(ET).isoformat() if option_quote_time else "",
        "enrichment_timestamp_et": enrichment_time.astimezone(ET).isoformat() if enrichment_time else "",
        "underlying_quote_timestamp_et": underlying_quote_time.astimezone(ET).isoformat() if underlying_quote_time else "",
        "underlying_quote_time_source": underlying_quote_time_source,
        "underlying_snapshot_age_minutes": underlying_snapshot_age_minutes,
        "valuation_timestamp_trust_pass": valuation_timestamp_trust_pass,
        "days_to_expiry": days_to_expiry,
        "time_to_expiry_years": t_years,
        "bid": bid,
        "ask": ask,
        "last_price": last,
        "pricing_source": pricing_source,
        "option_market_price": market_price,
        "underlying_price": spot,
        "risk_free_rate": rate,
        "dividend_yield": div,
        "intrinsic_value": intrinsic,
        "lower_arbitrage_bound": lower_bound,
        "upper_arbitrage_bound": upper_bound,
        "moneyness_spot_over_strike": moneyness,
        "log_moneyness": log_moneyness,
        "spread_absolute": spread_abs,
        "spread_ratio_mid": spread_ratio,
        "quote_alignment_seconds": alignment_seconds,
        "synthetic_iv": iv,
        "model_price": model_price,
        "repricing_error_absolute": repricing_abs,
        "repricing_error_ratio": repricing_ratio,
        **greeks,
        "iv_solver_iterations": iterations,
        "iv_solver_converged": iv is not None,
        "no_arbitrage_pass": no_arbitrage_pass,
        "greeks_invariant_pass": greeks_invariant_pass,
        "quote_quality_pass": quote_quality_pass,
        "timestamp_alignment_pass": alignment_pass,
        "quality_tier": tier,
        "eligible_for_research_ranking": eligible,
        "quality_issue_count": len(issue_names),
        "quality_flags": ";".join(issue_names),
        "model_name": "BLACK_SCHOLES_MERTON_EUROPEAN_APPROXIMATION",
        "model_risk_note": "US ETF options may be American-style; synthetic IV/Greeks are research-only BSM approximations.",
        "research_only": RESEARCH_ONLY,
        "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
        "broker_action_allowed": BROKER_ACTION_ALLOWED,
        "source_input_path": str(source_input_path),
    }
    return result, validations


def median(values: Iterable[float | None]) -> float | None:
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return None
    middle = len(clean) // 2
    return clean[middle] if len(clean) % 2 else 0.5 * (clean[middle - 1] + clean[middle])


def summarize_by_underlying(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("underlying", ""))].append(row)
    output: list[dict[str, Any]] = []
    for underlying in sorted(grouped):
        items = grouped[underlying]
        solved = [row for row in items if row.get("synthetic_iv") is not None]
        eligible = [row for row in items if bool(row.get("eligible_for_research_ranking"))]
        tiers = Counter(str(row.get("quality_tier", "REJECTED")) for row in items)
        issues = Counter()
        for row in items:
            for issue in str(row.get("quality_flags", "")).split(";"):
                if issue:
                    issues[issue] += 1
        output.append({
            "underlying": underlying,
            "input_row_count": len(items),
            "iv_solved_count": len(solved),
            "ranking_eligible_count": len(eligible),
            "tier_a_count": tiers["A"],
            "tier_b_count": tiers["B"],
            "tier_c_count": tiers["C"],
            "rejected_count": tiers["REJECTED"],
            "iv_coverage_ratio": len(solved) / len(items) if items else 0.0,
            "ranking_eligible_ratio": len(eligible) / len(items) if items else 0.0,
            "median_iv": median(row.get("synthetic_iv") for row in solved),
            "median_spread_ratio": median(row.get("spread_ratio_mid") for row in items),
            "median_abs_delta": median(abs(float(row["delta"])) if row.get("delta") is not None else None for row in solved),
            "median_gamma": median(row.get("gamma") for row in solved),
            "median_vega_per_1vol_point": median(row.get("vega_per_1vol_point") for row in solved),
            "primary_quality_issue": issues.most_common(1)[0][0] if issues else "",
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
        })
    return output


def put_call_parity_audit(rows: Sequence[Mapping[str, Any]], config: Config) -> list[dict[str, Any]]:
    pairs: dict[tuple[str, str, str], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        if row.get("synthetic_iv") is None or row.get("option_market_price") is None:
            continue
        key = (
            str(row.get("underlying", "")),
            str(row.get("expiry_timestamp_et", "")),
            f"{float(row.get('strike')):.8f}" if row.get("strike") is not None else "",
        )
        side = str(row.get("option_type", ""))
        if side in {"CALL", "PUT"}:
            current = pairs[key].get(side)
            if current is None or float(row.get("spread_ratio_mid") or 1e9) < float(current.get("spread_ratio_mid") or 1e9):
                pairs[key][side] = row
    output: list[dict[str, Any]] = []
    for (underlying, expiry, strike_text), pair in sorted(pairs.items()):
        if "CALL" not in pair or "PUT" not in pair:
            continue
        call = pair["CALL"]
        put = pair["PUT"]
        strike = float(strike_text)
        call_price = float(call["option_market_price"])
        put_price = float(put["option_market_price"])
        spot = 0.5 * (float(call["underlying_price"]) + float(put["underlying_price"]))
        t = 0.5 * (float(call["time_to_expiry_years"]) + float(put["time_to_expiry_years"]))
        rate = 0.5 * (float(call["risk_free_rate"]) + float(put["risk_free_rate"]))
        div = 0.5 * (float(call["dividend_yield"]) + float(put["dividend_yield"]))
        lhs = call_price - put_price
        rhs = spot * math.exp(-div * t) - strike * math.exp(-rate * t)
        error_abs = abs(lhs - rhs)
        error_ratio = error_abs / spot if spot > 0 else None
        passed = error_abs <= config.parity_abs_tolerance or (
            error_ratio is not None and error_ratio <= config.parity_ratio_spot_tolerance
        )
        output.append({
            "underlying": underlying,
            "expiry_timestamp_et": expiry,
            "strike": strike,
            "call_contract_code": call.get("contract_code", ""),
            "put_contract_code": put.get("contract_code", ""),
            "call_price": call_price,
            "put_price": put_price,
            "spot": spot,
            "time_to_expiry_years": t,
            "risk_free_rate": rate,
            "dividend_yield": div,
            "parity_lhs_call_minus_put": lhs,
            "parity_rhs_discounted_forward_intrinsic": rhs,
            "parity_error_absolute": error_abs,
            "parity_error_ratio_spot": error_ratio,
            "parity_pass": bool_text(passed),
            "notes": "Research diagnostic only; American exercise and quote asynchrony can create deviations.",
        })
    return output


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: format_number(row.get(name)) for name in fieldnames})
    os.replace(temp, path)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def discovery_candidates(repo_root: Path) -> list[Path]:
    r1a_exact = [
        repo_root / "outputs/v22/V22.037_R1A_OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY/option_contract_rows_with_underlying_price_repaired_research_only.csv",
        repo_root / "outputs/v22/V22.037_R1A_OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY/option_contract_rows_with_underlying_spot_injected_research_only.csv",
        repo_root / "outputs/v22/V22.037_R1A_OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY/option_contract_rows_with_repaired_underlying_price_research_only.csv",
    ]
    r3_exact = [
        repo_root / "outputs/v22/V22.036_R3_OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY/option_contract_rows_with_refreshed_underlying_spot_injected_research_only.csv",
        repo_root / "outputs/v22/V22.036_R3_OPTION_READ_ONLY_UNDERLYING_QUOTE_SNAPSHOT_REFRESH_AND_INJECTION_RESEARCH_ONLY/option_synthetic_calculability_after_refreshed_spot_injection.csv",
    ]
    groups: list[Iterable[Path]] = [
        r1a_exact,
        sorted(
            repo_root.glob("outputs/v22/V22.037_R1A*/*.csv"),
            key=lambda item: item.stat().st_mtime if item.exists() else 0,
            reverse=True,
        ),
        r3_exact,
        sorted(
            repo_root.glob("outputs/v22/V22.036_R3*/*option*contract*injected*.csv"),
            key=lambda item: item.stat().st_mtime if item.exists() else 0,
            reverse=True,
        ),
        sorted(
            repo_root.glob("outputs/v22/V22.036_R3*/*synthetic*calculability*.csv"),
            key=lambda item: item.stat().st_mtime if item.exists() else 0,
            reverse=True,
        ),
    ]
    seen: set[Path] = set()
    ordered: list[Path] = []
    for group in groups:
        for path in group:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                ordered.append(path)
    return ordered


def inspect_candidate_header(path: Path) -> tuple[int, list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
    except (OSError, UnicodeError, csv.Error):
        return 0, []
    lower = {str(name).strip().lower() for name in header if str(name).strip()}
    detected: list[str] = []
    score = 0
    weights = {
        "contract_code": 3,
        "underlying": 2,
        "option_type": 4,
        "strike": 5,
        "expiry": 5,
        "bid": 2,
        "ask": 2,
        "last": 1,
        "spot": 7,
        "quote_time": 1,
        "enrichment_time": 2,
        "underlying_quote_time": 1,
        "underlying_snapshot_age_minutes": 1,
    }
    for canonical, weight in weights.items():
        if any(alias.lower() in lower for alias in FIELD_ALIASES[canonical]):
            score += weight
            detected.append(canonical)
    # A usable contract table must expose strike/expiry/spot and either explicit side or a parseable contract code.
    has_required = all(name in detected for name in ("strike", "expiry", "spot"))
    has_identity = "option_type" in detected or "contract_code" in detected
    has_price = any(name in detected for name in ("bid", "ask", "last"))
    if not (has_required and has_identity and has_price):
        score = min(score, 9)
    return score, detected


def discover_input(repo_root: Path, explicit_input: Path | None) -> tuple[Path | None, list[dict[str, Any]]]:
    candidates = [explicit_input] if explicit_input is not None else discovery_candidates(repo_root)
    audit: list[dict[str, Any]] = []
    selected: Path | None = None
    scored: list[tuple[int, int, Path]] = []
    records: list[dict[str, Any]] = []
    for rank, candidate in enumerate(candidates, start=1):
        if candidate is None:
            continue
        exists = candidate.exists() and candidate.is_file()
        size = candidate.stat().st_size if exists else 0
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, UTC).isoformat() if exists else ""
        header_score, detected = inspect_candidate_header(candidate) if exists and size > 0 else (0, [])
        record = {
            "candidate_rank": rank,
            "path": str(candidate),
            "exists": exists,
            "size_bytes": size,
            "modified_utc": modified,
            "header_score": header_score,
            "detected_fields": ";".join(detected),
            "selected": False,
            "selection_reason": "",
        }
        records.append(record)
        if exists and size > 0:
            scored.append((header_score, -rank, candidate))
    if scored:
        best_score, _, selected = max(scored, key=lambda item: (item[0], item[1]))
        # Explicit input is honored if nonempty, even when its schema is intentionally being diagnosed.
        if explicit_input is None and best_score < 10:
            selected = None
    for record in records:
        if selected is not None and Path(record["path"]).resolve() == selected.resolve():
            record["selected"] = True
            record["selection_reason"] = "HIGHEST_CONTRACT_SCHEMA_SCORE_WITH_SOURCE_PRIORITY"
    audit.extend(records)
    return selected, audit


def build_schema_mapping(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except (OSError, UnicodeError, csv.Error):
        header = []
    lower_to_original = {str(name).strip().lower(): str(name).strip() for name in header if str(name).strip()}
    requirements = {
        "contract_code": "CONDITIONAL_IDENTITY",
        "underlying": "RECOMMENDED",
        "option_type": "CONDITIONAL_IDENTITY",
        "strike": "REQUIRED",
        "expiry": "REQUIRED",
        "bid": "RECOMMENDED_PRICE",
        "ask": "RECOMMENDED_PRICE",
        "last": "CONDITIONAL_PRICE",
        "spot": "REQUIRED_SEPARATE_UNDERLYING_PRICE",
        "quote_time": "RECOMMENDED_EXACT",
        "enrichment_time": "CONDITIONAL_HISTORICAL_ASOF_FALLBACK",
        "underlying_quote_time": "RECOMMENDED_EXACT",
        "underlying_snapshot_age_minutes": "CONDITIONAL_TIMESTAMP_RECONSTRUCTION",
        "risk_free_rate": "OPTIONAL_DEFAULTED",
        "dividend_yield": "OPTIONAL_DEFAULTED",
        "volume": "OPTIONAL",
        "open_interest": "OPTIONAL",
        "lot_size": "OPTIONAL",
    }
    rows: list[dict[str, Any]] = []
    for canonical in FIELD_ALIASES:
        selected = ""
        for alias in FIELD_ALIASES[canonical]:
            if alias.lower() in lower_to_original:
                selected = lower_to_original[alias.lower()]
                break
        notes = ""
        if canonical == "spot":
            notes = "Must be a separate underlying price field; option last_price is forbidden as spot."
        elif canonical in {"bid", "ask", "last"}:
            notes = "Bid/ask midpoint is preferred; last/mark is fallback only."
        elif canonical == "enrichment_time":
            notes = "Historical as-of fallback only; not treated as an exact exchange quote timestamp."
        elif canonical == "underlying_snapshot_age_minutes":
            notes = "Used only to reconstruct approximate underlying timestamp from enrichment_time_utc."
        rows.append({
            "canonical_field": canonical,
            "selected_source_column": selected,
            "found": bool(selected),
            "requirement": requirements.get(canonical, "OPTIONAL"),
            "accepted_aliases": ";".join(FIELD_ALIASES[canonical]),
            "notes": notes,
        })
    return rows


def global_validation_rows(
    calc_rows: Sequence[Mapping[str, Any]], parity_rows: Sequence[Mapping[str, Any]], config: Config
) -> list[dict[str, Any]]:
    total = len(calc_rows)
    solved = sum(row.get("synthetic_iv") is not None for row in calc_rows)
    eligible = sum(bool(row.get("eligible_for_research_ranking")) for row in calc_rows)
    invariant_failures = sum(
        row.get("synthetic_iv") is not None and not bool(row.get("greeks_invariant_pass")) for row in calc_rows
    )
    parity_evaluated = len(parity_rows)
    parity_passed = sum(str(row.get("parity_pass")) == "True" for row in parity_rows)
    iv_ratio = solved / total if total else 0.0
    eligible_ratio = eligible / total if total else 0.0
    return [
        validation_row(0, "", "ALL", "", "global_iv_coverage_ratio", f">={config.pass_iv_coverage_ratio}",
                       iv_ratio, iv_ratio >= config.pass_iv_coverage_ratio, "WARN"),
        validation_row(0, "", "ALL", "", "global_ranking_eligible_ratio",
                       f">={config.pass_ranking_eligible_ratio}", eligible_ratio,
                       eligible_ratio >= config.pass_ranking_eligible_ratio, "WARN"),
        validation_row(0, "", "ALL", "", "global_greeks_invariant_failure_count", 0,
                       invariant_failures, invariant_failures == 0, "ERROR"),
        validation_row(0, "", "ALL", "", "put_call_parity_pairs_evaluated", ">=0",
                       parity_evaluated, True, "INFO",
                       f"passed={parity_passed}; parity is diagnostic and not a hard gate"),
        validation_row(0, "", "ALL", "", "research_only_policy", True,
                       RESEARCH_ONLY, RESEARCH_ONLY, "ERROR"),
        validation_row(0, "", "ALL", "", "official_adoption_allowed", False,
                       OFFICIAL_ADOPTION_ALLOWED, not OFFICIAL_ADOPTION_ALLOWED, "ERROR"),
        validation_row(0, "", "ALL", "", "broker_action_allowed", False,
                       BROKER_ACTION_ALLOWED, not BROKER_ACTION_ALLOWED, "ERROR"),
    ]


def make_summary(
    repo_root: Path,
    output_dir: Path,
    input_path: Path | None,
    calc_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
    parity_rows: Sequence[Mapping[str, Any]],
    started_utc: str,
    ended_utc: str,
    status: str,
    decision: str,
    error_message: str = "",
) -> dict[str, Any]:
    total = len(calc_rows)
    solved = sum(row.get("synthetic_iv") is not None for row in calc_rows)
    eligible = sum(bool(row.get("eligible_for_research_ranking")) for row in calc_rows)
    tiers = Counter(str(row.get("quality_tier", "REJECTED")) for row in calc_rows)
    input_spot_valid = sum(row.get("underlying_price") is not None and float(row.get("underlying_price")) > 0 for row in calc_rows)
    no_arb = sum(bool(row.get("no_arbitrage_pass")) for row in calc_rows)
    greeks_ok = sum(bool(row.get("greeks_invariant_pass")) for row in calc_rows)
    quote_ok = sum(bool(row.get("quote_quality_pass")) for row in calc_rows)
    aligned = sum(bool(row.get("timestamp_alignment_pass")) for row in calc_rows)
    risk_free_assumed = sum("RISK_FREE_RATE_ASSUMED" in str(row.get("quality_flags", "")) for row in calc_rows)
    dividend_assumed = sum("DIVIDEND_YIELD_ASSUMED" in str(row.get("quality_flags", "")) for row in calc_rows)
    last_fallback = sum(str(row.get("pricing_source")) == "OPTION_LAST_PRICE_FALLBACK" for row in calc_rows)
    runtime_time_fallback = sum("VALUATION_TIME_RUNTIME_FALLBACK" in str(row.get("quality_flags", "")) for row in calc_rows)
    enrichment_time_fallback = sum(str(row.get("valuation_time_source")) == "ENRICHMENT_TIME_UTC_FALLBACK" for row in calc_rows)
    exact_option_quote_time = sum(str(row.get("valuation_time_source")) == "EXPLICIT_OPTION_QUOTE_TIMESTAMP" for row in calc_rows)
    trusted_valuation_time = sum(bool(row.get("valuation_timestamp_trust_pass")) for row in calc_rows)
    underlying_time_reconstructed = sum(
        str(row.get("underlying_quote_time_source")) == "RECONSTRUCTED_FROM_ENRICHMENT_TIME_MINUS_SNAPSHOT_AGE"
        for row in calc_rows
    )
    parity_pass = sum(str(row.get("parity_pass")) == "True" for row in parity_rows)
    validation_error_fail = sum(
        str(row.get("severity")) == "ERROR" and str(row.get("passed")) == "False" for row in validation_rows
    )
    validation_warn_fail = sum(
        str(row.get("severity")) == "WARN" and str(row.get("passed")) == "False" for row in validation_rows
    )
    return {
        "revision": REVISION,
        "final_status": status,
        "final_decision": decision,
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "source_input_path": str(input_path) if input_path else "",
        "run_start_utc": started_utc,
        "run_end_utc": ended_utc,
        "input_row_count": total,
        "underlying_price_valid_count": input_spot_valid,
        "synthetic_iv_solved_count": solved,
        "synthetic_iv_coverage_ratio": solved / total if total else 0.0,
        "greeks_valid_count": greeks_ok,
        "no_arbitrage_pass_count": no_arb,
        "quote_quality_pass_count": quote_ok,
        "timestamp_alignment_pass_count": aligned,
        "risk_free_rate_assumed_count": risk_free_assumed,
        "dividend_yield_assumed_count": dividend_assumed,
        "option_last_price_fallback_count": last_fallback,
        "valuation_time_runtime_fallback_count": runtime_time_fallback,
        "valuation_time_enrichment_fallback_count": enrichment_time_fallback,
        "valuation_time_explicit_option_quote_count": exact_option_quote_time,
        "valuation_timestamp_trust_pass_count": trusted_valuation_time,
        "underlying_time_reconstructed_from_age_count": underlying_time_reconstructed,
        "research_ranking_eligible_count": eligible,
        "research_ranking_eligible_ratio": eligible / total if total else 0.0,
        "quality_tier_a_count": tiers["A"],
        "quality_tier_b_count": tiers["B"],
        "quality_tier_c_count": tiers["C"],
        "quality_rejected_count": tiers["REJECTED"],
        "underlying_count": len({str(row.get("underlying", "")) for row in calc_rows if row.get("underlying")}),
        "put_call_parity_pair_count": len(parity_rows),
        "put_call_parity_pass_count": parity_pass,
        "validation_error_failure_count": validation_error_fail,
        "validation_warning_failure_count": validation_warn_fail,
        "model_name": "BLACK_SCHOLES_MERTON_EUROPEAN_APPROXIMATION",
        "model_risk_note": "US ETF options may be American-style; outputs are synthetic research-only approximations.",
        "research_only": RESEARCH_ONLY,
        "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
        "broker_action_allowed": BROKER_ACTION_ALLOWED,
        "error_message": error_message,
        "output_files": {
            "recalculated": str(output_dir / "option_iv_greeks_recalculated_research_only.csv"),
            "validation": str(output_dir / "option_iv_greeks_quality_validation.csv"),
            "summary_by_underlying": str(output_dir / "option_iv_greeks_quality_summary_by_underlying.csv"),
            "put_call_parity": str(output_dir / "option_put_call_parity_audit.csv"),
            "input_discovery": str(output_dir / "option_iv_greeks_input_discovery_audit.csv"),
            "input_schema_mapping": str(output_dir / "option_iv_greeks_input_schema_mapping.csv"),
            "report": str(output_dir / "V22.037_R2B_synthetic_iv_greeks_timestamp_provenance_repair_and_quality_validation_report.txt"),
        },
    }


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "V22.037 R2B Synthetic IV/Greeks Timestamp-Provenance Repair and Quality Validation",
        "=" * 76,
        f"Revision: {summary.get('revision', '')}",
        f"Final status: {summary.get('final_status', '')}",
        f"Final decision: {summary.get('final_decision', '')}",
        f"Source input: {summary.get('source_input_path', '')}",
        "",
        "Coverage",
        "--------",
        f"Input rows: {summary.get('input_row_count', 0)}",
        f"Valid underlying prices: {summary.get('underlying_price_valid_count', 0)}",
        f"Synthetic IV solved: {summary.get('synthetic_iv_solved_count', 0)}",
        f"Synthetic IV coverage ratio: {summary.get('synthetic_iv_coverage_ratio', 0):.4f}",
        f"Greeks invariant pass: {summary.get('greeks_valid_count', 0)}",
        f"Research ranking eligible: {summary.get('research_ranking_eligible_count', 0)}",
        f"Research ranking eligible ratio: {summary.get('research_ranking_eligible_ratio', 0):.4f}",
        "",
        "Quality tiers",
        "-------------",
        f"Tier A: {summary.get('quality_tier_a_count', 0)}",
        f"Tier B: {summary.get('quality_tier_b_count', 0)}",
        f"Tier C: {summary.get('quality_tier_c_count', 0)}",
        f"Rejected: {summary.get('quality_rejected_count', 0)}",
        "",
        "Hard policy",
        "-----------",
        f"research_only={summary.get('research_only')}",
        f"official_adoption_allowed={summary.get('official_adoption_allowed')}",
        f"broker_action_allowed={summary.get('broker_action_allowed')}",
        "",
        "Model caveat",
        "------------",
        str(summary.get("model_risk_note", "")),
    ]
    if summary.get("error_message"):
        lines.extend(["", "Error", "-----", str(summary["error_message"])])
    return "\n".join(lines) + "\n"


def execute(
    repo_root: Path,
    output_dir: Path,
    input_path: Path | None,
    config: Config,
    valuation_time_override: datetime | None = None,
) -> dict[str, Any]:
    started = utc_now_iso()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected, discovery = discover_input(repo_root, input_path)
    write_csv(output_dir / "option_iv_greeks_input_discovery_audit.csv", discovery, DISCOVERY_FIELDS)
    if selected is None:
        write_csv(output_dir / "option_iv_greeks_input_schema_mapping.csv", [], SCHEMA_FIELDS)
        summary = make_summary(
            repo_root, output_dir, None, [], [], [], started, utc_now_iso(), FAIL_INPUT, FAIL_DECISION,
            "No existing non-empty option contract input CSV was found.",
        )
        write_json_atomic(output_dir / "v22_037_r2b_summary.json", summary)
        (output_dir / "V22.037_R2B_synthetic_iv_greeks_timestamp_provenance_repair_and_quality_validation_report.txt").write_text(
            render_report(summary), encoding="utf-8"
        )
        return summary

    schema_mapping = build_schema_mapping(selected)
    write_csv(output_dir / "option_iv_greeks_input_schema_mapping.csv", schema_mapping, SCHEMA_FIELDS)
    raw_rows = read_csv_rows(selected)
    calc_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=2):
        calc, checks = recalculate_row(raw, index, selected, config, valuation_time_override)
        calc_rows.append(calc)
        validation_rows.extend(checks)
    parity_rows = put_call_parity_audit(calc_rows, config)
    validation_rows.extend(global_validation_rows(calc_rows, parity_rows, config))
    by_underlying = summarize_by_underlying(calc_rows)

    solved = sum(row.get("synthetic_iv") is not None for row in calc_rows)
    eligible = sum(bool(row.get("eligible_for_research_ranking")) for row in calc_rows)
    invariant_failures = sum(
        row.get("synthetic_iv") is not None and not bool(row.get("greeks_invariant_pass")) for row in calc_rows
    )
    iv_ratio = solved / len(calc_rows) if calc_rows else 0.0
    eligible_ratio = eligible / len(calc_rows) if calc_rows else 0.0
    if solved == 0:
        status, decision = FAIL_NO_CALC, FAIL_DECISION
    elif (
        iv_ratio >= config.pass_iv_coverage_ratio
        and eligible_ratio >= config.pass_ranking_eligible_ratio
        and invariant_failures == 0
    ):
        status, decision = PASS_STATUS, PASS_DECISION
    else:
        status, decision = WARN_STATUS, WARN_DECISION

    write_csv(output_dir / "option_iv_greeks_recalculated_research_only.csv", calc_rows, OUTPUT_FIELDS)
    write_csv(output_dir / "option_iv_greeks_quality_validation.csv", validation_rows, VALIDATION_FIELDS)
    write_csv(output_dir / "option_iv_greeks_quality_summary_by_underlying.csv", by_underlying, SUMMARY_BY_UNDERLYING_FIELDS)
    write_csv(output_dir / "option_put_call_parity_audit.csv", parity_rows, PARITY_FIELDS)

    summary = make_summary(
        repo_root, output_dir, selected, calc_rows, validation_rows, parity_rows,
        started, utc_now_iso(), status, decision,
    )
    write_json_atomic(output_dir / "v22_037_r2b_summary.json", summary)
    (output_dir / "V22.037_R2B_synthetic_iv_greeks_timestamp_provenance_repair_and_quality_validation_report.txt").write_text(
        render_report(summary), encoding="utf-8"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V22.037 R2B research-only synthetic IV/Greeks recalculation with timestamp provenance repair")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--risk-free-rate", type=float, default=Config.risk_free_rate)
    parser.add_argument("--dividend-yield", type=float, default=Config.dividend_yield)
    parser.add_argument("--max-spread-ratio", type=float, default=Config.max_spread_ratio_for_pass)
    parser.add_argument("--max-alignment-seconds", type=float, default=Config.max_alignment_seconds_for_pass)
    parser.add_argument("--pass-iv-coverage-ratio", type=float, default=Config.pass_iv_coverage_ratio)
    parser.add_argument("--pass-ranking-eligible-ratio", type=float, default=Config.pass_ranking_eligible_ratio)
    parser.add_argument("--valuation-time-et", type=str, default="")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir or repo_root / "outputs/v22" / OUTPUT_DIR_NAME
    override = parse_timestamp(args.valuation_time_et) if args.valuation_time_et else None
    config = Config(
        risk_free_rate=args.risk_free_rate,
        dividend_yield=args.dividend_yield,
        max_spread_ratio_for_pass=args.max_spread_ratio,
        max_alignment_seconds_for_pass=args.max_alignment_seconds,
        pass_iv_coverage_ratio=args.pass_iv_coverage_ratio,
        pass_ranking_eligible_ratio=args.pass_ranking_eligible_ratio,
    )
    if not args.execute:
        print("Refusing to run without --execute. Research-only module; no broker actions are implemented.")
        return 2
    try:
        summary = execute(repo_root, output_dir.resolve(), args.input.resolve() if args.input else None, config, override)
    except Exception as exc:  # pragma: no cover - defensive top-level persistence
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = make_summary(
            repo_root, output_dir, args.input, [], [], [], utc_now_iso(), utc_now_iso(),
            FAIL_EXCEPTION, FAIL_DECISION, f"{type(exc).__name__}: {exc}",
        )
        write_json_atomic(output_dir / "v22_037_r2b_summary.json", summary)
        (output_dir / "V22.037_R2B_synthetic_iv_greeks_timestamp_provenance_repair_and_quality_validation_report.txt").write_text(
            render_report(summary), encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL_") else 0


if __name__ == "__main__":
    sys.exit(main())
