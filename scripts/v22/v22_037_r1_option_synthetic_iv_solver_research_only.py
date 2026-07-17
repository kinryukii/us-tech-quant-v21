#!/usr/bin/env python
"""V22.037 R1 synthetic IV and Greeks solver research-only.

Computes Black-Scholes European approximation implied volatility and Greeks
from enriched option quote rows. It never opens broker/trade contexts or
enables candidate generation, official adoption, or broker actions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, datetime, time, timezone
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


MODULE_ID = "V22.037_R1"
MODULE_NAME = "OPTION_SYNTHETIC_IV_SOLVER_RESEARCH_ONLY"
STAGE = "V22.037_R1_OPTION_SYNTHETIC_IV_SOLVER_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE
PRICING_MODEL = "BLACK_SCHOLES_EUROPEAN_APPROXIMATION"
ET = ZoneInfo("America/New_York")

PASS_STATUS = "PASS_V22_037_R1_SYNTHETIC_IV_GREEKS_READY_FOR_LIQUIDITY_AUDIT"
WARN_STATUS = "WARN_V22_037_R1_SYNTHETIC_IV_PARTIAL_WITH_INVALID_QUOTES"
FAIL_NO_QUOTES = "FAIL_V22_037_R1_NO_USABLE_OPTION_QUOTES"
FAIL_INPUT = "FAIL_V22_037_R1_INPUT_NOT_FOUND"
PASS_DECISION = "SYNTHETIC_IV_GREEKS_READY_FOR_LIQUIDITY_AUDIT_RESEARCH_ONLY"
WARN_DECISION = "SYNTHETIC_IV_PARTIAL_REVIEW_INVALID_QUOTES_RESEARCH_ONLY"
NO_QUOTES_DECISION = "NO_USABLE_OPTION_QUOTES_RESEARCH_ONLY"
INPUT_DECISION = "INPUT_NOT_FOUND_RESEARCH_ONLY"

ALIASES = {
    "option_code": ["option_code", "contract_code", "code", "contract_id", "symbol"],
    "underlying": ["underlying", "underlying_symbol", "ticker"],
    "option_type": ["option_type", "cp", "right", "call_put", "type"],
    "strike": ["strike", "strike_price", "strikePrice"],
    "expiry": ["expiry", "expiration", "expiry_date", "expiration_date", "strike_time"],
    "bid": ["bid", "bid_price", "bid_raw"],
    "ask": ["ask", "ask_price", "ask_raw"],
    "mid": ["mid", "mark", "mark_price"],
    "last": ["last", "last_price", "last_raw", "price"],
    "volume": ["volume", "vol", "volume_raw"],
    "underlying_price": ["underlying_price", "spot", "underlying_spot", "underlying_last", "underlying_price_raw"],
    "quote_datetime": ["quote_datetime", "timestamp", "quote_time", "market_datetime", "enrichment_time_utc"],
    "open_interest": ["open_interest", "openInterest", "oi", "open_interest_raw"],
}

CLEAN_FIELDS = [
    "option_code", "underlying", "option_type", "strike", "expiry", "quote_datetime",
    "bid", "ask", "mid", "last", "volume", "underlying_price", "pricing_source",
    "model_price_input", "time_to_expiry_years", "risk_free_rate", "dividend_yield",
    "pricing_model", "synthetic_iv", "synthetic_delta", "synthetic_gamma",
    "synthetic_theta_per_day", "synthetic_vega_per_vol_point", "iv_status",
    "greeks_status", "intrinsic_value", "extrinsic_value", "moneyness",
    "log_moneyness", "spread_abs", "spread_pct", "open_interest_available",
    "open_interest_source", "open_interest_proxy_used", "candidate_generation_allowed",
    "broker_action_allowed", "official_adoption_allowed",
]
AUDIT_FIELDS = [
    "underlying", "option_type", "expiry", "iv_status", "row_count",
    "iv_solved_count", "greeks_solved_count", "median_synthetic_iv",
    "median_spread_pct", "median_volume",
]
SUMMARY_KEYS = [
    "module_name", "final_status", "final_decision", "input_path", "output_dir",
    "row_count", "attempted_contract_count", "iv_attempted_count", "iv_solved_count",
    "iv_solved_ratio", "greeks_solved_count", "greeks_solved_ratio",
    "open_interest_available_count", "open_interest_unavailable_count",
    "invalid_quote_count", "no_arbitrage_failure_count", "solver_failed_count",
    "candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed",
    "research_only", "pricing_model", "american_exercise_adjustment_applied",
    "ready_for_liquidity_audit",
]


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_d1_d2(s: float, k: float, t: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    denom = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / denom
    return d1, d1 - denom


def black_scholes_price(option_type: str, s: float, k: float, t: float, r: float, q: float, sigma: float) -> float:
    d1, d2 = bs_d1_d2(s, k, t, r, q, sigma)
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)
    if option_type == "CALL":
        return s * disc_q * norm_cdf(d1) - k * disc_r * norm_cdf(d2)
    return k * disc_r * norm_cdf(-d2) - s * disc_q * norm_cdf(-d1)


def black_scholes_greeks(option_type: str, s: float, k: float, t: float, r: float, q: float, sigma: float) -> dict[str, float]:
    d1, d2 = bs_d1_d2(s, k, t, r, q, sigma)
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)
    if option_type == "CALL":
        delta = disc_q * norm_cdf(d1)
        theta = (-(s * disc_q * norm_pdf(d1) * sigma) / (2 * math.sqrt(t)) - r * k * disc_r * norm_cdf(d2) + q * s * disc_q * norm_cdf(d1)) / 365.0
    else:
        delta = disc_q * (norm_cdf(d1) - 1)
        theta = (-(s * disc_q * norm_pdf(d1) * sigma) / (2 * math.sqrt(t)) + r * k * disc_r * norm_cdf(-d2) - q * s * disc_q * norm_cdf(-d1)) / 365.0
    gamma = disc_q * norm_pdf(d1) / (s * sigma * math.sqrt(t))
    vega = s * disc_q * norm_pdf(d1) * math.sqrt(t) / 100.0
    return {"delta": delta, "gamma": gamma, "theta_per_day": theta, "vega_per_vol_point": vega}


def brentq_fallback(func: Any, low: float, high: float, tol: float = 1e-8, max_iter: int = 100) -> float:
    flo = func(low)
    fhi = func(high)
    if flo * fhi > 0:
        raise ValueError("Root is not bracketed")
    a, b = low, high
    fa, fb = flo, fhi
    for _ in range(max_iter):
        c = (a + b) / 2
        fc = func(c)
        if abs(fc) < tol or abs(b - a) < tol:
            return c
        if fa * fc <= 0:
            b, fb = c, fc
        else:
            a, fa = c, fc
    return (a + b) / 2


def solve_iv(option_type: str, price: float, s: float, k: float, t: float, r: float, q: float, high: float, retry_high: float) -> tuple[float | None, str, bool]:
    def objective(sig: float) -> float:
        return black_scholes_price(option_type, s, k, t, r, q, sig) - price
    try:
        return brentq_fallback(objective, 0.0001, high), "SOLVED", False
    except Exception:
        try:
            return brentq_fallback(objective, 0.0001, retry_high), "SOLVED", True
        except Exception:
            return None, "SOLVER_BRACKET_FAILED", True


def first_present(row: dict[str, str], field: str) -> tuple[str, str]:
    lower = {str(k).lower(): k for k in row}
    for alias in ALIASES[field]:
        key = lower.get(alias.lower())
        if key is not None:
            return str(key), row.get(key, "")
    return "", ""


def parse_float(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalize_type(value: str) -> str:
    text = str(value or "").upper().strip()
    if text in {"CALL", "C"} or "CALL" in text:
        return "CALL"
    if text in {"PUT", "P"} or "PUT" in text:
        return "PUT"
    return ""


def parse_datetime_et(value: str, expiry_mode: bool = False) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 10 and text[4] == "-":
            d = date.fromisoformat(text)
            return datetime.combine(d, time(16, 0) if expiry_mode else time(0, 0), tzinfo=ET)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        return dt.astimezone(ET)
    except ValueError:
        return None


def time_to_expiry_years(quote_dt: datetime | None, expiry_dt: datetime | None) -> float | None:
    if quote_dt is None or expiry_dt is None:
        return None
    seconds = (expiry_dt - quote_dt).total_seconds()
    return seconds / (365.0 * 24 * 3600) if seconds > 0 else None


def no_arb_bounds(option_type: str, s: float, k: float, t: float, r: float, q: float) -> tuple[float, float]:
    if option_type == "CALL":
        return max(0.0, s * math.exp(-q * t) - k * math.exp(-r * t)), s * math.exp(-q * t)
    return max(0.0, k * math.exp(-r * t) - s * math.exp(-q * t)), k * math.exp(-r * t)


def intrinsic(option_type: str, s: float, k: float) -> float:
    return max(0.0, s - k) if option_type == "CALL" else max(0.0, k - s)


def discover_input(repo_root: Path) -> Path | None:
    roots = [repo_root / "outputs" / "v22"]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            for path in root.rglob("*.csv"):
                name = path.name.lower()
                parent = path.parent.name.lower()
                if ("v22.032" in parent or "v22.032_r1" in parent or "032" in parent) and "quote" in name and "clean" in name:
                    candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]


def clean_row(raw: dict[str, str], risk_free_rate: float, dividend_yield: float, max_sigma: float, high_retry: float) -> dict[str, Any]:
    option_code = first_present(raw, "option_code")[1]
    underlying = first_present(raw, "underlying")[1]
    option_type = normalize_type(first_present(raw, "option_type")[1])
    expiry_raw = first_present(raw, "expiry")[1]
    quote_raw = first_present(raw, "quote_datetime")[1]
    strike = parse_float(first_present(raw, "strike")[1])
    bid = parse_float(first_present(raw, "bid")[1])
    ask = parse_float(first_present(raw, "ask")[1])
    mid_input = parse_float(first_present(raw, "mid")[1])
    last = parse_float(first_present(raw, "last")[1])
    volume = parse_float(first_present(raw, "volume")[1])
    spot = parse_float(first_present(raw, "underlying_price")[1])
    oi_col, oi_raw = first_present(raw, "open_interest")
    oi = parse_float(oi_raw)
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        price = (bid + ask) / 2
        pricing_source = "MID_BID_ASK"
    elif mid_input is not None and mid_input > 0:
        price = mid_input
        pricing_source = "INPUT_MID"
    else:
        price = None
        pricing_source = "NO_VALID_MID"
    spread_abs = ask - bid if bid is not None and ask is not None else None
    spread_pct = spread_abs / price if spread_abs is not None and price and price > 0 else None
    quote_dt = parse_datetime_et(quote_raw)
    expiry_dt = parse_datetime_et(expiry_raw, expiry_mode=True)
    t = time_to_expiry_years(quote_dt, expiry_dt)
    status = "SOLVED"
    iv = None
    retry = False
    greeks: dict[str, float] = {}
    intr = extr = moneyness = log_moneyness = None
    required_missing = strike is None or spot is None or price is None or not option_code or not expiry_raw
    if option_type not in {"CALL", "PUT"}:
        status = "INVALID_OPTION_TYPE"
    elif required_missing:
        status = "MISSING_REQUIRED_FIELDS"
    elif t is None or t <= 0:
        status = "EXPIRED_OR_ZERO_T"
    elif price is None or price <= 0 or strike is None or spot is None or strike <= 0 or spot <= 0:
        status = "INVALID_PRICE"
    else:
        intr = intrinsic(option_type, spot, strike)
        extr = price - intr
        moneyness = spot / strike
        log_moneyness = math.log(spot / strike)
        lower, upper = no_arb_bounds(option_type, spot, strike, t, risk_free_rate, dividend_yield)
        if price < lower - 1e-8:
            status = "INVALID_BELOW_INTRINSIC_BOUND"
        elif price > upper + 1e-8:
            status = "INVALID_ABOVE_UPPER_BOUND"
        elif extr <= 1e-10:
            status = "NO_EXTRINSIC_VALUE"
        else:
            iv, status, retry = solve_iv(option_type, price, spot, strike, t, risk_free_rate, dividend_yield, max_sigma, high_retry)
            if iv is not None and status == "SOLVED":
                greeks = black_scholes_greeks(option_type, spot, strike, t, risk_free_rate, dividend_yield, iv)
    greeks_status = "SOLVED" if status == "SOLVED" and iv is not None else "NOT_SOLVED_IV_UNAVAILABLE"
    return {
        "option_code": option_code,
        "underlying": underlying,
        "option_type": option_type,
        "strike": "" if strike is None else strike,
        "expiry": expiry_raw,
        "quote_datetime": quote_raw,
        "bid": "" if bid is None else bid,
        "ask": "" if ask is None else ask,
        "mid": "" if mid_input is None else mid_input,
        "last": "" if last is None else last,
        "volume": "" if volume is None else volume,
        "underlying_price": "" if spot is None else spot,
        "pricing_source": pricing_source,
        "model_price_input": "" if price is None else price,
        "time_to_expiry_years": "" if t is None else t,
        "risk_free_rate": risk_free_rate,
        "dividend_yield": dividend_yield,
        "pricing_model": PRICING_MODEL,
        "synthetic_iv": "" if iv is None else iv,
        "synthetic_delta": "" if "delta" not in greeks else greeks["delta"],
        "synthetic_gamma": "" if "gamma" not in greeks else greeks["gamma"],
        "synthetic_theta_per_day": "" if "theta_per_day" not in greeks else greeks["theta_per_day"],
        "synthetic_vega_per_vol_point": "" if "vega_per_vol_point" not in greeks else greeks["vega_per_vol_point"],
        "iv_status": status,
        "greeks_status": greeks_status,
        "intrinsic_value": "" if intr is None else intr,
        "extrinsic_value": "" if extr is None else extr,
        "moneyness": "" if moneyness is None else moneyness,
        "log_moneyness": "" if log_moneyness is None else log_moneyness,
        "spread_abs": "" if spread_abs is None else spread_abs,
        "spread_pct": "" if spread_pct is None else spread_pct,
        "open_interest_available": oi is not None,
        "open_interest_source": "INPUT_COLUMN" if oi is not None and oi_col else "UNAVAILABLE_FROM_CURRENT_MOOMOO_QUOTE_PAYLOAD",
        "open_interest_proxy_used": False,
        "candidate_generation_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "solver_retry_high_vol": retry,
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["underlying"]), str(row["option_type"]), str(row["expiry"]), str(row["iv_status"]))
        groups.setdefault(key, []).append(row)
    out = []
    for (underlying, option_type, expiry, status), vals in sorted(groups.items()):
        ivs = [parse_float(v["synthetic_iv"]) for v in vals if parse_float(v["synthetic_iv"]) is not None]
        spreads = [parse_float(v["spread_pct"]) for v in vals if parse_float(v["spread_pct"]) is not None]
        vols = [parse_float(v["volume"]) for v in vals if parse_float(v["volume"]) is not None]
        out.append({"underlying": underlying, "option_type": option_type, "expiry": expiry, "iv_status": status, "row_count": len(vals), "iv_solved_count": sum(1 for v in vals if v["iv_status"] == "SOLVED"), "greeks_solved_count": sum(1 for v in vals if v["greeks_status"] == "SOLVED"), "median_synthetic_iv": "" if not ivs else median(ivs), "median_spread_pct": "" if not spreads else median(spreads), "median_volume": "" if not vols else median(vols)})
    return out


def summary_payload(input_path: Path | None, output_dir: Path, rows: list[dict[str, Any]], input_found: bool) -> dict[str, Any]:
    if not input_found:
        status, decision = FAIL_INPUT, INPUT_DECISION
    elif not rows:
        status, decision = FAIL_NO_QUOTES, NO_QUOTES_DECISION
    else:
        solved = sum(1 for r in rows if r["iv_status"] == "SOLVED")
        greeks = sum(1 for r in rows if r["greeks_status"] == "SOLVED")
        ratio = solved / len(rows) if rows else 0
        if solved > 0 and greeks > 0:
            status, decision = PASS_STATUS, PASS_DECISION
        elif ratio < 0.5:
            status, decision = WARN_STATUS, WARN_DECISION
        else:
            status, decision = WARN_STATUS, WARN_DECISION
    row_count = len(rows)
    iv_solved = sum(1 for r in rows if r["iv_status"] == "SOLVED")
    greeks_solved = sum(1 for r in rows if r["greeks_status"] == "SOLVED")
    no_arb = sum(1 for r in rows if r["iv_status"] in {"INVALID_BELOW_INTRINSIC_BOUND", "INVALID_ABOVE_UPPER_BOUND"})
    solver_failed = sum(1 for r in rows if r["iv_status"] in {"SOLVER_BRACKET_FAILED", "SOLVER_FAILED"})
    return {"module_name": MODULE_NAME, "final_status": status, "final_decision": decision, "input_path": "" if input_path is None else str(input_path), "output_dir": str(output_dir), "row_count": row_count, "attempted_contract_count": row_count, "iv_attempted_count": sum(1 for r in rows if r["iv_status"] not in {"MISSING_REQUIRED_FIELDS", "INVALID_OPTION_TYPE", "EXPIRED_OR_ZERO_T", "INVALID_PRICE"}), "iv_solved_count": iv_solved, "iv_solved_ratio": 0 if row_count == 0 else iv_solved / row_count, "greeks_solved_count": greeks_solved, "greeks_solved_ratio": 0 if row_count == 0 else greeks_solved / row_count, "open_interest_available_count": sum(1 for r in rows if r["open_interest_available"] is True), "open_interest_unavailable_count": sum(1 for r in rows if r["open_interest_available"] is not True), "invalid_quote_count": sum(1 for r in rows if r["iv_status"] != "SOLVED"), "no_arbitrage_failure_count": no_arb, "solver_failed_count": solver_failed, "candidate_generation_allowed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True, "pricing_model": PRICING_MODEL, "american_exercise_adjustment_applied": False, "ready_for_liquidity_audit": iv_solved > 0 and greeks_solved > 0}


def report_text(summary: dict[str, Any]) -> str:
    lines = ["V22.037_R1 Option Synthetic IV Greeks Solver Research Only"]
    for key in ["final_status", "final_decision", "input_path", "output_dir", "row_count", "iv_solved_count", "greeks_solved_count", "open_interest_available_count", "open_interest_unavailable_count"]:
        lines.append(f"{key}={summary.get(key)}")
    lines.append("open_interest_note=Open Interest was not synthetically inferred; no proxy was used.")
    lines.append("broker_action_allowed=False")
    lines.append("official_adoption_allowed=False")
    return "\n".join(lines) + "\n"


def run(repo_root: Path, input_path: Path | None = None, output_root: Path | None = None, risk_free_rate: float = 0.045, dividend_yield: float = 0.0, max_sigma: float = 5.0, high_vol_retry_sigma: float = 10.0, execute: bool = True) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = (output_root or (repo_root / OUT_REL)).resolve()
    if input_path is None:
        input_path = discover_input(repo_root)
    if not execute:
        return summary_payload(input_path, output_dir, [], input_path is not None and input_path.exists())
    if input_path is None or not input_path.exists():
        summary = summary_payload(input_path, output_dir, [], False)
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / "option_synthetic_iv_greeks_clean.csv", CLEAN_FIELDS, [])
        write_csv(output_dir / "option_synthetic_iv_greeks_audit.csv", AUDIT_FIELDS, [])
        (output_dir / "v22_037_r1_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output_dir / "V22.037_R1_option_synthetic_iv_greeks_report.txt").write_text(report_text(summary), encoding="utf-8")
        return summary
    raw_rows = read_rows(input_path)
    clean = [clean_row(row, risk_free_rate, dividend_yield, max_sigma, high_vol_retry_sigma) for row in raw_rows]
    audit = audit_rows(clean)
    summary = summary_payload(input_path, output_dir, clean, True)
    write_csv(output_dir / "option_synthetic_iv_greeks_clean.csv", CLEAN_FIELDS, clean)
    write_csv(output_dir / "option_synthetic_iv_greeks_audit.csv", AUDIT_FIELDS, audit)
    (output_dir / "v22_037_r1_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    (output_dir / "V22.037_R1_option_synthetic_iv_greeks_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--input-path", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--risk-free-rate", type=float, default=0.045)
    parser.add_argument("--dividend-yield", type=float, default=0.0)
    parser.add_argument("--max-sigma", type=float, default=5.0)
    parser.add_argument("--high-vol-retry-sigma", type=float, default=10.0)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.input_path, args.output_root, args.risk_free_rate, args.dividend_yield, args.max_sigma, args.high_vol_retry_sigma, args.execute)
    for key in ["final_status", "final_decision", "iv_solved_count", "greeks_solved_count", "open_interest_available_count", "open_interest_unavailable_count", "candidate_generation_allowed", "broker_action_allowed", "official_adoption_allowed"]:
        print(f"{key}={summary.get(key)}")
    print(f"output_dir={summary.get('output_dir')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
