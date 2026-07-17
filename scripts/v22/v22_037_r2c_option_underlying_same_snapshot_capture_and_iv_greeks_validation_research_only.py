from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

REVISION = "V22.037_R2C"
OUTPUT_DIR_NAME = "V22.037_R2C_OPTION_UNDERLYING_SAME_SNAPSHOT_CAPTURE_AND_IV_GREEKS_VALIDATION_RESEARCH_ONLY"
PASS_STATUS = "PASS_V22_037_R2C_SAME_SNAPSHOT_CAPTURE_AND_IV_GREEKS_VALIDATED"
WARN_STATUS = "WARN_V22_037_R2C_CAPTURED_WITH_ALIGNMENT_OR_QUALITY_WARNINGS"
FAIL_CAPTURE = "FAIL_V22_037_R2C_NO_VALID_SAME_SNAPSHOT_OPTION_ROWS"
FAIL_CHILD = "FAIL_V22_037_R2C_IV_GREEKS_CHILD_FAILED"
FAIL_EXCEPTION = "FAIL_V22_037_R2C_UNHANDLED_EXCEPTION"
PASS_DECISION = "SAME_SNAPSHOT_IV_GREEKS_READY_FOR_RESEARCH_RANKING_ONLY"
WARN_DECISION = "SAME_SNAPSHOT_IV_GREEKS_AVAILABLE_WITH_FILTER_REQUIRED_RESEARCH_ONLY"
FAIL_DECISION = "SAME_SNAPSHOT_IV_GREEKS_BLOCKED_RESEARCH_ONLY"

RESEARCH_ONLY = True
OFFICIAL_ADOPTION_ALLOWED = False
BROKER_ACTION_ALLOWED = False
UTC = timezone.utc
ET = ZoneInfo("America/New_York")

CAPTURE_FIELDS = [
    "capture_id", "capture_batch_id", "batch_sequence", "request_start_utc", "request_end_utc",
    "snapshot_request_latency_seconds", "same_snapshot_request", "data_vendor", "quote_api",
    "option_code", "contract_code", "underlying", "underlying_code", "expiration", "dte",
    "strike", "call_put", "option_type", "bid", "ask", "mid", "last", "last_price",
    "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
    "option_quote_timestamp", "option_quote_timestamp_utc", "option_quote_timestamp_et",
    "underlying_price", "underlying_quote_timestamp", "underlying_quote_timestamp_utc",
    "underlying_quote_timestamp_et", "quote_alignment_seconds", "timestamp_alignment_pass",
    "option_quote_timestamp_explicit", "underlying_quote_timestamp_explicit", "quote_status",
    "clean_status", "reason", "enrichment_time_utc", "candidate_generation_allowed",
    "research_only", "official_adoption_allowed", "broker_action_allowed",
]

BATCH_AUDIT_FIELDS = [
    "capture_id", "capture_batch_id", "underlying", "batch_sequence", "requested_code_count",
    "requested_option_count", "returned_row_count", "returned_option_count", "underlying_row_found",
    "request_start_utc", "request_end_utc", "request_latency_seconds", "ret_code", "error_message",
]

CHAIN_AUDIT_FIELDS = [
    "underlying", "underlying_code", "expiration", "expiration_distance_days", "chain_row_count",
    "selected_row_count", "status", "error_message",
]

SUMMARY_FIELDS = [
    "revision", "final_status", "final_decision", "repo_root", "output_dir", "run_start_utc",
    "run_end_utc", "underlyings_requested", "underlying_count", "expiration_count",
    "option_chain_static_row_count", "selected_contract_count", "snapshot_batch_count",
    "captured_option_row_count", "same_snapshot_request_count", "explicit_option_quote_timestamp_count",
    "explicit_underlying_quote_timestamp_count", "timestamp_alignment_pass_count",
    "timestamp_alignment_pass_ratio", "regular_session_clock_pass", "capture_input_path",
    "iv_child_executed", "iv_child_exit_code", "iv_child_summary_path", "iv_child_final_status",
    "iv_child_final_decision", "synthetic_iv_solved_count", "synthetic_iv_coverage_ratio",
    "greeks_valid_count", "research_ranking_eligible_count", "research_ranking_eligible_ratio",
    "quality_tier_a_count", "quality_tier_b_count", "quality_tier_c_count", "quality_rejected_count",
    "research_only", "official_adoption_allowed", "broker_action_allowed", "error_message",
]


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 18441
    min_dte: int = 0
    max_dte: int = 14
    max_contracts_per_underlying: int = 399
    snapshot_option_batch_size: int = 399
    max_alignment_seconds: float = 15.0
    min_alignment_pass_ratio: float = 0.80
    risk_free_rate: float = 0.043
    dividend_yield: float = 0.0
    max_spread_ratio: float = 0.50
    child_pass_iv_coverage_ratio: float = 0.80
    child_pass_ranking_eligible_ratio: float = 0.20


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


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


def first_present(row: Mapping[str, Any], aliases: Sequence[str]) -> Any:
    lower = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        value = lower.get(alias.lower())
        if value is not None and str(value).strip() != "":
            return value
    return None


def records_from_table(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        try:
            values = data.to_dict(orient="records")
        except TypeError:
            values = data.to_dict("records")
        return [dict(row) for row in values]
    if isinstance(data, Mapping):
        return [dict(data)]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        return [dict(row) for row in data if isinstance(row, Mapping)]
    return []


def normalize_underlying_symbol(value: str) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("US."):
        text = text[3:]
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", text):
        raise ValueError(f"Invalid US underlying symbol: {value!r}")
    return text


def underlying_code(symbol: str) -> str:
    return f"US.{normalize_underlying_symbol(symbol)}"


def parse_underlyings(value: str | Sequence[str]) -> list[str]:
    raw: Iterable[str]
    if isinstance(value, str):
        raw = re.split(r"[,;\s]+", value)
    else:
        raw = value
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not str(item).strip():
            continue
        symbol = normalize_underlying_symbol(str(item))
        if symbol not in seen:
            result.append(symbol)
            seen.add(symbol)
    if not result:
        raise ValueError("At least one underlying is required.")
    return result


def parse_date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_us_update_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        cleaned = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def expiration_close_et(expiration: date) -> datetime:
    return datetime.combine(expiration, time(16, 0), tzinfo=ET)


def parse_option_type(value: Any, code: str = "") -> str:
    text = str(value or "").strip().upper()
    if text in {"CALL", "C", "1", "CALL_OPTION"}:
        return "CALL"
    if text in {"PUT", "P", "2", "PUT_OPTION"}:
        return "PUT"
    match = re.search(r"\d{6}([CP])\d{6,8}$", code.upper().replace("US.", ""))
    if match:
        return "CALL" if match.group(1) == "C" else "PUT"
    return ""


def parse_strike(value: Any, code: str = "") -> float | None:
    strike = safe_float(value)
    if strike is not None and strike > 0:
        return strike
    match = re.search(r"\d{6}[CP](\d{6,8})$", code.upper().replace("US.", ""))
    if match:
        parsed = int(match.group(1)) / 1000.0
        return parsed if parsed > 0 else None
    return None


def parse_expiration_from_code(code: str) -> date | None:
    match = re.search(r"([0-9]{6})[CP][0-9]{6,8}$", code.upper().replace("US.", ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%y%m%d").date()
    except ValueError:
        return None


def normalize_option_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if code and not code.startswith("US."):
        code = f"US.{code}"
    return code


def ret_ok(ret: Any, module_ret_ok: Any = 0) -> bool:
    return ret == module_ret_ok or ret == 0 or str(ret).upper() in {"RET_OK", "OK", "0"}


def chunked(values: Sequence[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError("Chunk size must be positive.")
    return [list(values[i:i + size]) for i in range(0, len(values), size)]


def select_expirations(
    expiration_rows: Sequence[Mapping[str, Any]],
    as_of_et: datetime,
    min_dte: int,
    max_dte: int,
) -> list[tuple[date, int]]:
    result: list[tuple[date, int]] = []
    seen: set[date] = set()
    for row in expiration_rows:
        expiry = parse_date_value(first_present(row, ("strike_time", "expiration", "expiry", "expiration_date")))
        if expiry is None or expiry in seen:
            continue
        distance = safe_int(first_present(row, ("option_expiry_date_distance", "dte", "expiry_distance_days")))
        if distance is None:
            distance = (expiry - as_of_et.date()).days
        if distance < min_dte or distance > max_dte:
            continue
        if expiration_close_et(expiry) <= as_of_et:
            continue
        result.append((expiry, distance))
        seen.add(expiry)
    result.sort(key=lambda item: (item[0], item[1]))
    return result


def normalize_chain_row(row: Mapping[str, Any], symbol: str, expiry_hint: date | None = None) -> dict[str, Any] | None:
    code = normalize_option_code(first_present(row, ("code", "option_code", "contract_code", "symbol")))
    if not code:
        return None
    expiry = parse_date_value(first_present(row, ("strike_time", "expiration", "expiry", "expiration_date")))
    expiry = expiry or expiry_hint or parse_expiration_from_code(code)
    strike = parse_strike(first_present(row, ("strike_price", "option_strike_price", "strike")), code)
    option_type = parse_option_type(first_present(row, ("option_type", "call_put", "type")), code)
    if expiry is None or strike is None or not option_type:
        return None
    return {
        "option_code": code,
        "underlying": normalize_underlying_symbol(symbol),
        "expiration": expiry.isoformat(),
        "strike": strike,
        "option_type": option_type,
        "call_put": option_type,
        "chain_name": str(first_present(row, ("name", "option_name")) or ""),
        "lot_size": safe_float(first_present(row, ("lot_size", "option_contract_size", "contract_size"))),
    }


def select_contracts(chain_rows: Sequence[Mapping[str, Any]], spot: float | None, maximum: int) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in chain_rows:
        code = str(row.get("option_code", ""))
        if code:
            unique[code] = dict(row)
    values = list(unique.values())

    def score(row: Mapping[str, Any]) -> tuple[Any, ...]:
        expiry = str(row.get("expiration", ""))
        strike = safe_float(row.get("strike"))
        if spot is not None and spot > 0 and strike is not None and strike > 0:
            distance = abs(math.log(strike / spot))
        else:
            distance = float("inf")
        side = 0 if str(row.get("option_type")) == "CALL" else 1
        return expiry, distance, strike or float("inf"), side, str(row.get("option_code", ""))

    values.sort(key=score)
    if maximum > 0:
        values = values[:maximum]
    return values


def snapshot_price(row: Mapping[str, Any]) -> float | None:
    for aliases in (
        ("last_price", "cur_price", "price"),
        ("bid_price", "bid"),
        ("ask_price", "ask"),
    ):
        value = safe_float(first_present(row, aliases))
        if value is not None and value > 0:
            return value
    return None


def row_by_code(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = normalize_option_code(first_present(row, ("code", "option_code", "contract_code", "symbol")))
        if code:
            result[code] = dict(row)
    return result


def build_capture_row(
    capture_id: str,
    batch_id: str,
    batch_sequence: int,
    request_start: datetime,
    request_end: datetime,
    chain_row: Mapping[str, Any],
    option_snapshot: Mapping[str, Any],
    underlying_snapshot: Mapping[str, Any],
    config: Config,
) -> dict[str, Any]:
    option_code = str(chain_row["option_code"])
    symbol = str(chain_row["underlying"])
    option_time = parse_us_update_time(first_present(option_snapshot, ("update_time", "quote_time", "timestamp")))
    underlying_time = parse_us_update_time(first_present(underlying_snapshot, ("update_time", "quote_time", "timestamp")))
    alignment = abs((option_time - underlying_time).total_seconds()) if option_time and underlying_time else None
    alignment_pass = alignment is not None and alignment <= config.max_alignment_seconds
    bid = safe_float(first_present(option_snapshot, ("bid_price", "bid")))
    ask = safe_float(first_present(option_snapshot, ("ask_price", "ask")))
    last = safe_float(first_present(option_snapshot, ("last_price", "cur_price", "last")))
    mid = 0.5 * (bid + ask) if bid is not None and ask is not None and ask >= bid else None
    underlying_price = snapshot_price(underlying_snapshot)
    expiry = parse_date_value(chain_row.get("expiration"))
    dte = (expiry - option_time.date()).days if expiry and option_time else None
    reason_parts: list[str] = []
    if option_time is None:
        reason_parts.append("OPTION_UPDATE_TIME_MISSING")
    if underlying_time is None:
        reason_parts.append("UNDERLYING_UPDATE_TIME_MISSING")
    if underlying_price is None:
        reason_parts.append("UNDERLYING_PRICE_MISSING")
    if not alignment_pass:
        reason_parts.append("OPTION_UNDERLYING_TIMESTAMP_MISALIGNED")
    if bid is None or ask is None or ask <= 0 or bid < 0 or ask < bid:
        reason_parts.append("BID_ASK_INVALID")
    clean = not reason_parts
    option_time_et = option_time.isoformat() if option_time else ""
    option_time_utc = option_time.astimezone(UTC).isoformat() if option_time else ""
    underlying_time_et = underlying_time.isoformat() if underlying_time else ""
    underlying_time_utc = underlying_time.astimezone(UTC).isoformat() if underlying_time else ""
    return {
        "capture_id": capture_id,
        "capture_batch_id": batch_id,
        "batch_sequence": batch_sequence,
        "request_start_utc": request_start.astimezone(UTC).isoformat(),
        "request_end_utc": request_end.astimezone(UTC).isoformat(),
        "snapshot_request_latency_seconds": (request_end - request_start).total_seconds(),
        "same_snapshot_request": True,
        "data_vendor": "MOOMOO_OPENAPI",
        "quote_api": "GET_MARKET_SNAPSHOT",
        "option_code": option_code,
        "contract_code": option_code,
        "underlying": symbol,
        "underlying_code": underlying_code(symbol),
        "expiration": str(chain_row.get("expiration", "")),
        "dte": dte,
        "strike": chain_row.get("strike"),
        "call_put": chain_row.get("option_type"),
        "option_type": chain_row.get("option_type"),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last": last,
        "last_price": last,
        "volume": safe_float(first_present(option_snapshot, ("volume", "option_volume"))),
        "open_interest": safe_float(first_present(option_snapshot, ("option_open_interest", "open_interest", "oi"))),
        "implied_volatility": safe_float(first_present(option_snapshot, ("option_implied_volatility", "implied_volatility"))),
        "delta": safe_float(first_present(option_snapshot, ("option_delta", "delta"))),
        "gamma": safe_float(first_present(option_snapshot, ("option_gamma", "gamma"))),
        "theta": safe_float(first_present(option_snapshot, ("option_theta", "theta"))),
        "vega": safe_float(first_present(option_snapshot, ("option_vega", "vega"))),
        "rho": safe_float(first_present(option_snapshot, ("option_rho", "rho"))),
        "option_quote_timestamp": option_time_et,
        "option_quote_timestamp_utc": option_time_utc,
        "option_quote_timestamp_et": option_time_et,
        "underlying_price": underlying_price,
        "underlying_quote_timestamp": underlying_time_et,
        "underlying_quote_timestamp_utc": underlying_time_utc,
        "underlying_quote_timestamp_et": underlying_time_et,
        "quote_alignment_seconds": alignment,
        "timestamp_alignment_pass": alignment_pass,
        "option_quote_timestamp_explicit": option_time is not None,
        "underlying_quote_timestamp_explicit": underlying_time is not None,
        "quote_status": "QUOTE_FETCHED_READ_ONLY",
        "clean_status": "PASS" if clean else "WARN",
        "reason": ";".join(reason_parts),
        "enrichment_time_utc": request_end.astimezone(UTC).isoformat(),
        "candidate_generation_allowed": alignment_pass and option_time is not None and underlying_time is not None,
        "research_only": RESEARCH_ONLY,
        "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
        "broker_action_allowed": BROKER_ACTION_ALLOWED,
    }


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    os.replace(tmp, path)


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def regular_session_clock_pass(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    current = now_et.timetz().replace(tzinfo=None)
    return time(9, 30) <= current <= time(16, 0)


def get_initial_spot(ctx: Any, code: str, module_ret_ok: Any) -> float | None:
    ret, data = ctx.get_market_snapshot([code])
    if not ret_ok(ret, module_ret_ok):
        return None
    rows = records_from_table(data)
    mapping = row_by_code(rows)
    return snapshot_price(mapping.get(code, {}))


def collect_static_chain(
    ctx: Any,
    symbol: str,
    as_of_et: datetime,
    config: Config,
    module_ret_ok: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    code = underlying_code(symbol)
    ret, expiration_data = ctx.get_option_expiration_date(code)
    if not ret_ok(ret, module_ret_ok):
        raise RuntimeError(f"get_option_expiration_date failed for {code}: {expiration_data}")
    expiration_rows = records_from_table(expiration_data)
    expirations = select_expirations(expiration_rows, as_of_et, config.min_dte, config.max_dte)
    if not expirations:
        raise RuntimeError(f"No unexpired option expirations within DTE {config.min_dte}..{config.max_dte} for {code}")
    all_rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for expiry, distance in expirations:
        try:
            ret, chain_data = ctx.get_option_chain(code, start=expiry.isoformat(), end=expiry.isoformat())
        except TypeError:
            ret, chain_data = ctx.get_option_chain(code, start=expiry.isoformat(), end=expiry.isoformat())
        if not ret_ok(ret, module_ret_ok):
            audit.append({
                "underlying": symbol, "underlying_code": code, "expiration": expiry.isoformat(),
                "expiration_distance_days": distance, "chain_row_count": 0, "selected_row_count": 0,
                "status": "FAIL", "error_message": str(chain_data),
            })
            continue
        raw_chain = records_from_table(chain_data)
        normalized = [item for item in (normalize_chain_row(row, symbol, expiry) for row in raw_chain) if item]
        all_rows.extend(normalized)
        audit.append({
            "underlying": symbol, "underlying_code": code, "expiration": expiry.isoformat(),
            "expiration_distance_days": distance, "chain_row_count": len(raw_chain),
            "selected_row_count": len(normalized), "status": "PASS", "error_message": "",
        })
    return all_rows, audit, len(expirations)


def capture_symbol(
    ctx: Any,
    symbol: str,
    capture_id: str,
    as_of_et: datetime,
    config: Config,
    module_ret_ok: Any,
    now_fn: Callable[[], datetime] = utc_now,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    code = underlying_code(symbol)
    static_rows, chain_audit, expiration_count = collect_static_chain(
        ctx, symbol, as_of_et, config, module_ret_ok
    )
    initial_spot = get_initial_spot(ctx, code, module_ret_ok)
    selected = select_contracts(static_rows, initial_spot, config.max_contracts_per_underlying)
    selected_codes = [str(row["option_code"]) for row in selected]
    batches = chunked(selected_codes, min(config.snapshot_option_batch_size, 399))
    chain_by_code = {str(row["option_code"]): row for row in selected}
    captured: list[dict[str, Any]] = []
    batch_audit: list[dict[str, Any]] = []
    for batch_sequence, option_codes in enumerate(batches, start=1):
        batch_id = f"{capture_id}_{symbol}_{batch_sequence:03d}"
        request_codes = [code] + option_codes
        request_start = now_fn()
        ret, snapshot_data = ctx.get_market_snapshot(request_codes)
        request_end = now_fn()
        if not ret_ok(ret, module_ret_ok):
            batch_audit.append({
                "capture_id": capture_id, "capture_batch_id": batch_id, "underlying": symbol,
                "batch_sequence": batch_sequence, "requested_code_count": len(request_codes),
                "requested_option_count": len(option_codes), "returned_row_count": 0,
                "returned_option_count": 0, "underlying_row_found": False,
                "request_start_utc": request_start.isoformat(), "request_end_utc": request_end.isoformat(),
                "request_latency_seconds": (request_end - request_start).total_seconds(),
                "ret_code": ret, "error_message": str(snapshot_data),
            })
            continue
        snapshot_rows = records_from_table(snapshot_data)
        mapping = row_by_code(snapshot_rows)
        under_row = mapping.get(code)
        if under_row is None:
            batch_audit.append({
                "capture_id": capture_id, "capture_batch_id": batch_id, "underlying": symbol,
                "batch_sequence": batch_sequence, "requested_code_count": len(request_codes),
                "requested_option_count": len(option_codes), "returned_row_count": len(snapshot_rows),
                "returned_option_count": sum(opt in mapping for opt in option_codes),
                "underlying_row_found": False, "request_start_utc": request_start.isoformat(),
                "request_end_utc": request_end.isoformat(),
                "request_latency_seconds": (request_end - request_start).total_seconds(),
                "ret_code": ret, "error_message": "Underlying snapshot row missing from same request.",
            })
            continue
        returned_options = 0
        for option_code in option_codes:
            option_row = mapping.get(option_code)
            if option_row is None:
                continue
            returned_options += 1
            captured.append(build_capture_row(
                capture_id, batch_id, batch_sequence, request_start, request_end,
                chain_by_code[option_code], option_row, under_row, config,
            ))
        batch_audit.append({
            "capture_id": capture_id, "capture_batch_id": batch_id, "underlying": symbol,
            "batch_sequence": batch_sequence, "requested_code_count": len(request_codes),
            "requested_option_count": len(option_codes), "returned_row_count": len(snapshot_rows),
            "returned_option_count": returned_options, "underlying_row_found": True,
            "request_start_utc": request_start.isoformat(), "request_end_utc": request_end.isoformat(),
            "request_latency_seconds": (request_end - request_start).total_seconds(),
            "ret_code": ret, "error_message": "",
        })
    return captured, batch_audit, chain_audit, len(static_rows), expiration_count


def import_moomoo_module() -> Any:
    errors: list[str] = []
    for name in ("moomoo", "futu"):
        try:
            return importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - live environment dependent
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    raise ImportError("Unable to import moomoo/futu OpenAPI package. " + " | ".join(errors))


def run_iv_child(
    repo_root: Path,
    capture_input: Path,
    child_output_dir: Path,
    config: Config,
) -> tuple[int, dict[str, Any], Path]:
    child_script = repo_root / "scripts/v22/v22_037_r2b_synthetic_iv_greeks_timestamp_provenance_repair_and_quality_validation_research_only.py"
    if not child_script.exists():
        raise FileNotFoundError(f"R2B child script not found: {child_script}")
    child_summary_path = child_output_dir / "v22_037_r2b_summary.json"
    command = [
        sys.executable, str(child_script),
        "--repo-root", str(repo_root),
        "--input", str(capture_input),
        "--output-dir", str(child_output_dir),
        "--risk-free-rate", str(config.risk_free_rate),
        "--dividend-yield", str(config.dividend_yield),
        "--max-spread-ratio", str(config.max_spread_ratio),
        "--max-alignment-seconds", str(config.max_alignment_seconds),
        "--pass-iv-coverage-ratio", str(config.child_pass_iv_coverage_ratio),
        "--pass-ranking-eligible-ratio", str(config.child_pass_ranking_eligible_ratio),
        "--execute",
    ]
    completed = subprocess.run(command, check=False, text=True)
    summary: dict[str, Any] = {}
    if child_summary_path.exists():
        summary = json.loads(child_summary_path.read_text(encoding="utf-8"))
    return completed.returncode, summary, child_summary_path


def final_status_for(
    captured_count: int,
    aligned_count: int,
    config: Config,
    child_executed: bool,
    child_exit_code: int,
    child_summary: Mapping[str, Any],
) -> tuple[str, str]:
    if captured_count <= 0:
        return FAIL_CAPTURE, FAIL_DECISION
    if child_executed and (child_exit_code != 0 or str(child_summary.get("final_status", "")).startswith("FAIL_")):
        return FAIL_CHILD, FAIL_DECISION
    aligned_ratio = aligned_count / captured_count
    if child_executed:
        eligible = int(child_summary.get("research_ranking_eligible_count", 0) or 0)
        solved = int(child_summary.get("synthetic_iv_solved_count", 0) or 0)
        if solved > 0 and eligible > 0 and aligned_ratio >= config.min_alignment_pass_ratio:
            return PASS_STATUS, PASS_DECISION
    return WARN_STATUS, WARN_DECISION


def make_summary(
    repo_root: Path,
    output_dir: Path,
    started: str,
    ended: str,
    underlyings: Sequence[str],
    expiration_count: int,
    static_count: int,
    selected_count: int,
    batch_count: int,
    captured: Sequence[Mapping[str, Any]],
    capture_input_path: Path,
    child_executed: bool,
    child_exit_code: int,
    child_summary: Mapping[str, Any],
    child_summary_path: Path | None,
    regular_session_pass: bool,
    config: Config,
    error_message: str = "",
) -> dict[str, Any]:
    captured_count = len(captured)
    aligned = sum(str(row.get("timestamp_alignment_pass")).lower() in {"true", "1"} or row.get("timestamp_alignment_pass") is True for row in captured)
    same_request = sum(str(row.get("same_snapshot_request")).lower() in {"true", "1"} or row.get("same_snapshot_request") is True for row in captured)
    explicit_option = sum(bool(row.get("option_quote_timestamp")) for row in captured)
    explicit_under = sum(bool(row.get("underlying_quote_timestamp")) for row in captured)
    status, decision = final_status_for(captured_count, aligned, config, child_executed, child_exit_code, child_summary)
    if error_message and status == WARN_STATUS and captured_count == 0:
        status, decision = FAIL_EXCEPTION, FAIL_DECISION
    return {
        "revision": REVISION,
        "final_status": status,
        "final_decision": decision,
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "run_start_utc": started,
        "run_end_utc": ended,
        "underlyings_requested": ",".join(underlyings),
        "underlying_count": len(underlyings),
        "expiration_count": expiration_count,
        "option_chain_static_row_count": static_count,
        "selected_contract_count": selected_count,
        "snapshot_batch_count": batch_count,
        "captured_option_row_count": captured_count,
        "same_snapshot_request_count": same_request,
        "explicit_option_quote_timestamp_count": explicit_option,
        "explicit_underlying_quote_timestamp_count": explicit_under,
        "timestamp_alignment_pass_count": aligned,
        "timestamp_alignment_pass_ratio": aligned / captured_count if captured_count else 0.0,
        "regular_session_clock_pass": regular_session_pass,
        "capture_input_path": str(capture_input_path),
        "iv_child_executed": child_executed,
        "iv_child_exit_code": child_exit_code,
        "iv_child_summary_path": str(child_summary_path) if child_summary_path else "",
        "iv_child_final_status": child_summary.get("final_status", ""),
        "iv_child_final_decision": child_summary.get("final_decision", ""),
        "synthetic_iv_solved_count": child_summary.get("synthetic_iv_solved_count", 0),
        "synthetic_iv_coverage_ratio": child_summary.get("synthetic_iv_coverage_ratio", 0.0),
        "greeks_valid_count": child_summary.get("greeks_valid_count", 0),
        "research_ranking_eligible_count": child_summary.get("research_ranking_eligible_count", 0),
        "research_ranking_eligible_ratio": child_summary.get("research_ranking_eligible_ratio", 0.0),
        "quality_tier_a_count": child_summary.get("quality_tier_a_count", 0),
        "quality_tier_b_count": child_summary.get("quality_tier_b_count", 0),
        "quality_tier_c_count": child_summary.get("quality_tier_c_count", 0),
        "quality_rejected_count": child_summary.get("quality_rejected_count", 0),
        "research_only": RESEARCH_ONLY,
        "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
        "broker_action_allowed": BROKER_ACTION_ALLOWED,
        "error_message": error_message,
    }


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "V22.037 R2C Option/Underlying Same-Snapshot Capture and IV/Greeks Validation",
        "=" * 82,
        f"Revision: {summary.get('revision', '')}",
        f"Final status: {summary.get('final_status', '')}",
        f"Final decision: {summary.get('final_decision', '')}",
        "",
        "Capture",
        "-------",
        f"Underlyings: {summary.get('underlyings_requested', '')}",
        f"Selected contracts: {summary.get('selected_contract_count', 0)}",
        f"Captured option rows: {summary.get('captured_option_row_count', 0)}",
        f"Same-request rows: {summary.get('same_snapshot_request_count', 0)}",
        f"Explicit option timestamps: {summary.get('explicit_option_quote_timestamp_count', 0)}",
        f"Explicit underlying timestamps: {summary.get('explicit_underlying_quote_timestamp_count', 0)}",
        f"Alignment pass ratio: {summary.get('timestamp_alignment_pass_ratio', 0):.4f}",
        f"Regular-session clock pass: {summary.get('regular_session_clock_pass')}",
        "",
        "IV/Greeks child",
        "---------------",
        f"Child status: {summary.get('iv_child_final_status', '')}",
        f"Synthetic IV solved: {summary.get('synthetic_iv_solved_count', 0)}",
        f"Greeks valid: {summary.get('greeks_valid_count', 0)}",
        f"Ranking eligible: {summary.get('research_ranking_eligible_count', 0)}",
        f"Tier A: {summary.get('quality_tier_a_count', 0)}",
        "",
        "Hard policy",
        "-----------",
        f"research_only={summary.get('research_only')}",
        f"official_adoption_allowed={summary.get('official_adoption_allowed')}",
        f"broker_action_allowed={summary.get('broker_action_allowed')}",
    ]
    if summary.get("error_message"):
        lines.extend(["", "Error", "-----", str(summary["error_message"])])
    return "\n".join(lines) + "\n"


def execute(
    repo_root: Path,
    output_dir: Path,
    underlyings: Sequence[str],
    config: Config,
    run_child: bool = True,
    module: Any | None = None,
    context_factory: Callable[..., Any] | None = None,
    as_of_et: datetime | None = None,
) -> dict[str, Any]:
    started = utc_now_iso()
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_id = f"v22_037_r2c_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    capture_input = output_dir / "option_underlying_same_snapshot_capture_research_only.csv"
    batch_audit_path = output_dir / "same_snapshot_batch_audit.csv"
    chain_audit_path = output_dir / "option_chain_discovery_audit.csv"
    summary_path = output_dir / "v22_037_r2c_summary.json"
    report_path = output_dir / "V22.037_R2C_same_snapshot_capture_and_iv_greeks_validation_report.txt"
    child_output_dir = output_dir / "iv_greeks_r2b_child"
    current_et = as_of_et or datetime.now(ET)
    captured_all: list[dict[str, Any]] = []
    batch_audit_all: list[dict[str, Any]] = []
    chain_audit_all: list[dict[str, Any]] = []
    static_count = 0
    selected_count = 0
    expiration_count = 0
    error_message = ""
    child_executed = False
    child_exit_code = 0
    child_summary: dict[str, Any] = {}
    child_summary_path: Path | None = None
    try:
        live_module = module or import_moomoo_module()
        module_ret_ok = getattr(live_module, "RET_OK", 0)
        factory = context_factory or getattr(live_module, "OpenQuoteContext")
        ctx = factory(host=config.host, port=config.port)
        try:
            for symbol in underlyings:
                rows, batches, chain_audit, static_rows, exp_count = capture_symbol(
                    ctx, symbol, capture_id, current_et, config, module_ret_ok
                )
                captured_all.extend(rows)
                batch_audit_all.extend(batches)
                chain_audit_all.extend(chain_audit)
                static_count += static_rows
                selected_count += sum(int(row.get("requested_option_count", 0) or 0) for row in batches)
                expiration_count += exp_count
        finally:
            close = getattr(ctx, "close", None)
            if callable(close):
                close()
        write_csv(capture_input, captured_all, CAPTURE_FIELDS)
        write_csv(batch_audit_path, batch_audit_all, BATCH_AUDIT_FIELDS)
        write_csv(chain_audit_path, chain_audit_all, CHAIN_AUDIT_FIELDS)
        if run_child and captured_all:
            child_executed = True
            child_exit_code, child_summary, child_summary_path = run_iv_child(
                repo_root, capture_input, child_output_dir, config
            )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        if not capture_input.exists():
            write_csv(capture_input, captured_all, CAPTURE_FIELDS)
        if not batch_audit_path.exists():
            write_csv(batch_audit_path, batch_audit_all, BATCH_AUDIT_FIELDS)
        if not chain_audit_path.exists():
            write_csv(chain_audit_path, chain_audit_all, CHAIN_AUDIT_FIELDS)
    summary = make_summary(
        repo_root, output_dir, started, utc_now_iso(), underlyings, expiration_count, static_count,
        selected_count, len(batch_audit_all), captured_all, capture_input, child_executed,
        child_exit_code, child_summary, child_summary_path, regular_session_clock_pass(current_et),
        config, error_message,
    )
    if error_message and not captured_all:
        summary["final_status"] = FAIL_EXCEPTION
        summary["final_decision"] = FAIL_DECISION
    write_json(summary_path, summary)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary


def default_repo_root() -> Path:
    env = os.environ.get("US_TECH_QUANT_REPO_ROOT")
    if env:
        return Path(env)
    return Path(r"D:\us-tech-quant") if os.name == "nt" else Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V22.037 R2C research-only same-snapshot option/underlying capture and IV/Greeks validation")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--underlyings", type=str, default="QQQ")
    parser.add_argument("--host", type=str, default=Config.host)
    parser.add_argument("--port", type=int, default=Config.port)
    parser.add_argument("--min-dte", type=int, default=Config.min_dte)
    parser.add_argument("--max-dte", type=int, default=Config.max_dte)
    parser.add_argument("--max-contracts-per-underlying", type=int, default=Config.max_contracts_per_underlying)
    parser.add_argument("--snapshot-option-batch-size", type=int, default=Config.snapshot_option_batch_size)
    parser.add_argument("--max-alignment-seconds", type=float, default=Config.max_alignment_seconds)
    parser.add_argument("--min-alignment-pass-ratio", type=float, default=Config.min_alignment_pass_ratio)
    parser.add_argument("--risk-free-rate", type=float, default=Config.risk_free_rate)
    parser.add_argument("--dividend-yield", type=float, default=Config.dividend_yield)
    parser.add_argument("--max-spread-ratio", type=float, default=Config.max_spread_ratio)
    parser.add_argument("--child-pass-iv-coverage-ratio", type=float, default=Config.child_pass_iv_coverage_ratio)
    parser.add_argument("--child-pass-ranking-eligible-ratio", type=float, default=Config.child_pass_ranking_eligible_ratio)
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute:
        print("Refusing to run without --execute. Read-only research module; no broker actions are implemented.")
        return 2
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir or repo_root / "outputs/v22" / OUTPUT_DIR_NAME
    config = Config(
        host=args.host,
        port=args.port,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        max_contracts_per_underlying=args.max_contracts_per_underlying,
        snapshot_option_batch_size=args.snapshot_option_batch_size,
        max_alignment_seconds=args.max_alignment_seconds,
        min_alignment_pass_ratio=args.min_alignment_pass_ratio,
        risk_free_rate=args.risk_free_rate,
        dividend_yield=args.dividend_yield,
        max_spread_ratio=args.max_spread_ratio,
        child_pass_iv_coverage_ratio=args.child_pass_iv_coverage_ratio,
        child_pass_ranking_eligible_ratio=args.child_pass_ranking_eligible_ratio,
    )
    try:
        underlyings = parse_underlyings(args.underlyings)
        summary = execute(
            repo_root, output_dir.resolve(), underlyings, config, run_child=not args.capture_only
        )
    except Exception as exc:  # pragma: no cover
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "revision": REVISION,
            "final_status": FAIL_EXCEPTION,
            "final_decision": FAIL_DECISION,
            "repo_root": str(repo_root),
            "output_dir": str(output_dir),
            "research_only": RESEARCH_ONLY,
            "official_adoption_allowed": OFFICIAL_ADOPTION_ALLOWED,
            "broker_action_allowed": BROKER_ACTION_ALLOWED,
            "error_message": f"{type(exc).__name__}: {exc}",
        }
        write_json(output_dir / "v22_037_r2c_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if str(summary.get("final_status", "")).startswith("FAIL_") else 0


if __name__ == "__main__":
    sys.exit(main())
