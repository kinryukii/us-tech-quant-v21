#!/usr/bin/env python
"""V22.042 ETF option intraday direction gate R1.

Research-only directional overlay for V22.041 enriched ETF option liquidity
candidates. This module uses read-only market data only and never creates
broker action instructions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import socket
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable


MODULE_ID = "V22.042"
MODULE_NAME = "OPTION_INTRADAY_ETF_DIRECTION_GATE_R1"
STAGE = "V22.042_OPTION_INTRADAY_ETF_DIRECTION_GATE_R1"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_041_REL = Path("outputs") / "v22" / "V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1"
R1A_STAGE = "V22.041_R1A_ETF_OPTION_MOOMOO_READONLY_QUOTE_AND_LOG_PERMISSION_REPAIR"

PASS_STATUS = "PASS_V22_042_OPTION_INTRADAY_ETF_DIRECTION_GATE_READY"
WARN_DATA_STATUS = "WARN_V22_042_INTRADAY_DATA_INSUFFICIENT_DIRECTION_GATE_WAIT"
WARN_CANDIDATES_STATUS = "WARN_V22_042_V22_041_CANDIDATES_MISSING"
PASS_DECISION = "OPTION_INTRADAY_ETF_DIRECTION_GATE_READY_RESEARCH_ONLY"
WAIT_DECISION = "OPTION_INTRADAY_ETF_DIRECTION_GATE_WAIT_RESEARCH_ONLY"

DIRECTION_UNDERLYINGS = ["SOXX", "QQQ", "SPY"]
EXECUTION_ETFS = ["SOXL", "SOXS", "TQQQ", "SQQQ", "QQQ", "SPY"]
PRIMARY_SEMI_EXECUTION = ["SOXL", "SOXS"]

MARKET_ET = ZoneInfo("America/New_York")
TIMESTAMP_CONTRACT_VERSION = "V22.042_R2B_DIRECTION_BAR_TIMESTAMP_PROVENANCE"
HISTORY_FETCH_CONTRACT_VERSION = "V22.042_R2C_LATEST_HISTORY_KLINE_WINDOW_AND_PAGINATION"
HISTORY_FETCH_POLICY = "EXPLICIT_RECENT_DATE_WINDOW_PAGE_TO_END_SORT_DEDUP_TAKE_LATEST_N"
HISTORY_FETCH_PAGE_SIZE = 1000
HISTORY_FETCH_MAX_PAGES = 100
TIMEFRAME_FETCH_CALENDAR_DAYS = {"1m": 10, "15m": 30, "1h": 120}
TIMEFRAME_INTERVAL_MINUTES = {"1m": 1, "15m": 15, "1h": 60}
TIMESTAMP_PROVENANCE_FIELDS = [
    "underlying", "timeframe", "requested_bar_count", "actual_bar_count",
    "parsed_timestamp_count", "first_bar_time_raw", "last_bar_time_raw",
    "first_bar_time_et", "last_bar_time_et", "first_bar_time_utc",
    "last_bar_time_utc", "bar_interval_minutes", "estimated_scope_minutes",
    "history_fetch_contract_version", "history_fetch_policy",
    "history_request_start_date", "history_request_end_date",
    "history_pages_fetched", "history_raw_row_count",
    "history_selected_latest_row_count",
    "timestamp_parse_status", "source_provider", "research_only",
]

SNAPSHOT_FIELDS = [
    "underlying", "bar_count_1m", "bar_count_15m", "bar_count_1h", "latest_close",
    "intraday_return", "vwap", "vwap_position", "ema_slope_1m", "ema_slope_15m",
    "ema_slope_1h", "rsi_1m", "bollinger_position_1m", "volume_confirmation",
    "direction_label", "data_status",
]
INDICATOR_FIELDS = [
    "underlying", "timeframe", "bar_count", "first_close", "last_close", "return_pct",
    "vwap", "ema_fast", "ema_slow", "ema_slope", "rsi", "bollinger_position",
    "volume_latest", "volume_average", "volume_confirmation", "indicator_status",
]
DECISION_FIELDS = [
    "decision_scope", "soxx_direction_label", "qqq_confirmation_label",
    "spy_confirmation_label", "final_direction_label", "wait_state",
    "direction_gate_passed", "reason",
]
CANDIDATE_FIELDS = [
    "contract_id", "underlying", "expiration", "dte", "strike", "call_put", "bid",
    "ask", "mid", "spread_pct", "volume", "direction_action", "direction_label",
    "research_only", "broker_action_allowed", "official_adoption_allowed",
]
REJECT_FIELDS = CANDIDATE_FIELDS + ["reject_reason"]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "v22_041_summary_found",
    "v22_041_liquidity_candidate_count", "v22_041_real_readonly_quote_verified",
    "v22_041_fallback_rows_used", "intraday_data_attempted", "intraday_data_available",
    "soxx_direction_label", "qqq_confirmation_label", "spy_confirmation_label",
    "final_direction_label", "promoted_candidate_count", "rejected_by_direction_count",
    "wait_state", "direction_gate_passed", "intraday_data_insufficient",
    "trade_context_used", "unlock_trade_called", "place_order_called",
    "direction_timestamp_contract_version", "direction_source_time_utc",
    "direction_source_time_policy", "direction_source_time_trust",
    "direction_timestamp_complete", "direction_required_timestamp_row_count",
    "direction_parsed_timestamp_row_count", "direction_input_latest_time_min_utc",
    "direction_input_latest_time_max_utc", "direction_input_time_dispersion_seconds",
    "direction_bar_timestamp_provenance_path",
    "broker_action_allowed", "official_adoption_allowed", "research_only",
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


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]


def numeric(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


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


def opend_port_reachable(host: str, port: int, timeout_seconds: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


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


def result_ok_data_page(result: Any) -> tuple[bool, Any, Any]:
    """Return status, data and the next history-kline page key."""
    if isinstance(result, tuple) and len(result) >= 2:
        code = result[0]
        ok = code == 0 or str(code).upper() in {"0", "RET_OK", "OK"}
        page_key = result[2] if len(result) >= 3 else None
        return ok, result[1], page_key
    return result is not None, result, None


def history_request_window(timeframe: str, now_et: datetime | None = None) -> tuple[str, str]:
    current = now_et.astimezone(MARKET_ET) if now_et is not None else datetime.now(MARKET_ET)
    end_date = current.date()
    calendar_days = TIMEFRAME_FETCH_CALENDAR_DAYS[timeframe]
    start_date = end_date - timedelta(days=calendar_days)
    return start_date.isoformat(), end_date.isoformat()


def latest_history_rows(
    method: Callable[..., Any],
    code: str,
    ktype: Any,
    timeframe: str,
    requested_bar_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch every page in an explicit recent window and retain the latest N rows."""
    start_date, end_date = history_request_window(timeframe)
    page_key: Any = None
    pages_fetched = 0
    all_rows: list[dict[str, Any]] = []

    while pages_fetched < HISTORY_FETCH_MAX_PAGES:
        kwargs: dict[str, Any] = {
            "code": code,
            "start": start_date,
            "end": end_date,
            "ktype": ktype,
            "max_count": HISTORY_FETCH_PAGE_SIZE,
        }
        if page_key is not None:
            kwargs["page_req_key"] = page_key

        ok, data, next_page_key = result_ok_data_page(method(**kwargs))
        if not ok:
            return [], {
                "history_fetch_contract_version": HISTORY_FETCH_CONTRACT_VERSION,
                "history_fetch_policy": HISTORY_FETCH_POLICY,
                "history_request_start_date": start_date,
                "history_request_end_date": end_date,
                "history_pages_fetched": pages_fetched,
                "history_raw_row_count": len(all_rows),
                "history_selected_latest_row_count": 0,
            }

        pages_fetched += 1
        all_rows.extend(data_to_rows(data))
        if next_page_key is None:
            break
        page_key = next_page_key
    else:
        # A non-terminating page chain is not trustworthy.
        return [], {
            "history_fetch_contract_version": HISTORY_FETCH_CONTRACT_VERSION,
            "history_fetch_policy": HISTORY_FETCH_POLICY,
            "history_request_start_date": start_date,
            "history_request_end_date": end_date,
            "history_pages_fetched": pages_fetched,
            "history_raw_row_count": len(all_rows),
            "history_selected_latest_row_count": 0,
        }

    dedup: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        raw_time = str(row.get("time_key") or row.get("time") or row.get("datetime") or row.get("date") or "").strip()
        if raw_time:
            dedup[raw_time] = row

    def sort_key(row: dict[str, Any]) -> tuple[int, float | str]:
        raw = row.get("time_key") or row.get("time") or row.get("datetime") or row.get("date") or ""
        _et, utc_value = parse_market_bar_time(raw)
        if utc_value is not None:
            return (0, utc_value.timestamp())
        return (1, str(raw))

    ordered = sorted(dedup.values(), key=sort_key)
    selected = ordered[-max(int(requested_bar_count), 0):] if requested_bar_count > 0 else []
    metadata = {
        "history_fetch_contract_version": HISTORY_FETCH_CONTRACT_VERSION,
        "history_fetch_policy": HISTORY_FETCH_POLICY,
        "history_request_start_date": start_date,
        "history_request_end_date": end_date,
        "history_pages_fetched": pages_fetched,
        "history_raw_row_count": len(all_rows),
        "history_selected_latest_row_count": len(selected),
    }
    return selected, metadata


def ktype_value(module: Any, name: str) -> Any:
    kltype = getattr(module, "KLType", None)
    if kltype is None:
        return name
    for candidate in [name, name.replace("K_", "K_"), name.lower()]:
        if hasattr(kltype, candidate):
            return getattr(kltype, candidate)
    return name


def normalize_bar(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "time_key": row.get("time_key") or row.get("time") or row.get("datetime") or row.get("date") or "",
        "open": numeric(row.get("open")),
        "high": numeric(row.get("high")),
        "low": numeric(row.get("low")),
        "close": numeric(row.get("close")),
        "volume": numeric(row.get("volume")),
    }


def parse_market_bar_time(value: Any) -> tuple[datetime | None, datetime | None]:
    """Parse a Moomoo US kline time_key as America/New_York unless offset-aware."""
    text = str(value or "").strip()
    if not text:
        return None, None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None, None
    et_value = parsed.replace(tzinfo=MARKET_ET) if parsed.tzinfo is None else parsed.astimezone(MARKET_ET)
    return et_value, et_value.astimezone(timezone.utc)


def iso_text(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def build_timestamp_provenance(
    bars_by_symbol: dict[str, dict[str, list[dict[str, Any]]]],
    requested_bar_count: int,
    require_qqq_confirmation: bool,
    require_spy_confirmation: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parsed_latest_by_key: dict[tuple[str, str], datetime] = {}

    for symbol in DIRECTION_UNDERLYINGS:
        for timeframe in ["1m", "15m", "1h"]:
            bars = list(bars_by_symbol.get(symbol, {}).get(timeframe, []))
            parsed_entries: list[tuple[str, datetime, datetime]] = []
            for bar in bars:
                raw = str(bar.get("time_key") or "").strip()
                et_value, utc_value = parse_market_bar_time(raw)
                if et_value is not None and utc_value is not None:
                    parsed_entries.append((raw, et_value, utc_value))

            parsed_entries.sort(key=lambda item: item[2])
            first_raw = str(bars[0].get("time_key") or "").strip() if bars else ""
            last_raw = str(bars[-1].get("time_key") or "").strip() if bars else ""
            first_et = parsed_entries[0][1] if parsed_entries else None
            last_et = parsed_entries[-1][1] if parsed_entries else None
            first_utc = parsed_entries[0][2] if parsed_entries else None
            last_utc = parsed_entries[-1][2] if parsed_entries else None

            if not bars:
                parse_status = "NO_BARS"
            elif not parsed_entries:
                parse_status = "TIMESTAMP_PARSE_FAILED"
            elif len(parsed_entries) != len(bars):
                parse_status = "PARTIAL_TIMESTAMP_PARSE"
            else:
                parse_status = "OK"

            if last_utc is not None:
                parsed_latest_by_key[(symbol, timeframe)] = last_utc

            interval = TIMEFRAME_INTERVAL_MINUTES[timeframe]
            fetch_meta = bars[0] if bars else {}
            rows.append({
                "underlying": symbol,
                "timeframe": timeframe,
                "requested_bar_count": requested_bar_count,
                "actual_bar_count": len(bars),
                "parsed_timestamp_count": len(parsed_entries),
                "first_bar_time_raw": first_raw,
                "last_bar_time_raw": last_raw,
                "first_bar_time_et": iso_text(first_et),
                "last_bar_time_et": iso_text(last_et),
                "first_bar_time_utc": iso_text(first_utc),
                "last_bar_time_utc": iso_text(last_utc),
                "bar_interval_minutes": interval,
                "estimated_scope_minutes": len(bars) * interval,
                "history_fetch_contract_version": fetch_meta.get("_history_fetch_contract_version", ""),
                "history_fetch_policy": fetch_meta.get("_history_fetch_policy", ""),
                "history_request_start_date": fetch_meta.get("_history_request_start_date", ""),
                "history_request_end_date": fetch_meta.get("_history_request_end_date", ""),
                "history_pages_fetched": fetch_meta.get("_history_pages_fetched", ""),
                "history_raw_row_count": fetch_meta.get("_history_raw_row_count", ""),
                "history_selected_latest_row_count": fetch_meta.get("_history_selected_latest_row_count", ""),
                "timestamp_parse_status": parse_status,
                "source_provider": "MOOMOO_OPENQUOTE_HISTORY_KLINE",
                "research_only": True,
            })

    required_symbols = ["SOXX"]
    if require_qqq_confirmation:
        required_symbols.append("QQQ")
    if require_spy_confirmation:
        required_symbols.append("SPY")
    required_keys = [(symbol, timeframe) for symbol in required_symbols for timeframe in ["1m", "15m", "1h"]]
    required_times = [parsed_latest_by_key[key] for key in required_keys if key in parsed_latest_by_key]
    complete = len(required_times) == len(required_keys)
    min_time = min(required_times) if complete else None
    max_time = max(required_times) if complete else None
    dispersion = (max_time - min_time).total_seconds() if min_time is not None and max_time is not None else None

    context = {
        "direction_timestamp_contract_version": TIMESTAMP_CONTRACT_VERSION,
        "direction_source_time_utc": iso_text(min_time),
        "direction_source_time_policy": "MIN_LATEST_BAR_TIME_ACROSS_REQUIRED_UNDERLYING_TIMEFRAMES",
        "direction_source_time_trust": "HIGH" if complete else "MISSING",
        "direction_timestamp_complete": complete,
        "direction_required_timestamp_row_count": len(required_keys),
        "direction_parsed_timestamp_row_count": len(required_times),
        "direction_input_latest_time_min_utc": iso_text(min_time),
        "direction_input_latest_time_max_utc": iso_text(max_time),
        "direction_input_time_dispersion_seconds": "" if dispersion is None else dispersion,
    }
    return rows, context


def fetch_intraday_bars(repo_root: Path, host: str, port: int, lookback_minutes: int, import_func: Callable[[str], Any] | None = None) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], bool]:
    configure_safe_moomoo_environment(repo_root)
    if not opend_port_reachable(host, port):
        return {}, False
    try:
        module = import_func("moomoo") if import_func else __import__("moomoo")
        ctx = module.OpenQuoteContext(host=host, port=port)
    except Exception:
        return {}, False
    bars: dict[str, dict[str, list[dict[str, Any]]]] = {}
    try:
        method = getattr(ctx, "request_history_kline", None)
        if method is None:
            return {}, False
        for symbol in DIRECTION_UNDERLYINGS:
            bars[symbol] = {}
            for timeframe, ktype in [("1m", "K_1M"), ("15m", "K_15M"), ("1h", "K_60M")]:
                try:
                    rows, metadata = latest_history_rows(
                        method,
                        code=f"US.{symbol}",
                        ktype=ktype_value(module, ktype),
                        timeframe=timeframe,
                        requested_bar_count=lookback_minutes,
                    )
                    normalized = [normalize_bar(row) for row in rows if numeric(row.get("close")) is not None]
                    for bar in normalized:
                        bar.update({
                            "_history_fetch_contract_version": metadata.get("history_fetch_contract_version", ""),
                            "_history_fetch_policy": metadata.get("history_fetch_policy", ""),
                            "_history_request_start_date": metadata.get("history_request_start_date", ""),
                            "_history_request_end_date": metadata.get("history_request_end_date", ""),
                            "_history_pages_fetched": metadata.get("history_pages_fetched", ""),
                            "_history_raw_row_count": metadata.get("history_raw_row_count", ""),
                            "_history_selected_latest_row_count": metadata.get("history_selected_latest_row_count", ""),
                        })
                    bars[symbol][timeframe] = normalized
                except Exception:
                    bars[symbol][timeframe] = []
    finally:
        close = getattr(ctx, "close", None)
        if callable(close):
            close()
    return bars, True


def ema(values: list[float], span: int) -> float | None:
    if not values:
        return None
    alpha = 2 / (span + 1)
    current = values[0]
    for value in values[1:]:
        current = alpha * value + (1 - alpha) * current
    return current


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for prev, curr in zip(values[-period - 1:-1], values[-period:]):
        change = curr - prev
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def indicators_for_bars(underlying: str, timeframe: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [numeric(row.get("close")) for row in bars if numeric(row.get("close")) is not None]
    vols = [numeric(row.get("volume")) for row in bars if numeric(row.get("volume")) is not None]
    if len(closes) < 3:
        return {"underlying": underlying, "timeframe": timeframe, "bar_count": len(closes), "indicator_status": "INSUFFICIENT_BARS"}
    latest = closes[-1]
    first = closes[0]
    ret = (latest / first - 1) if first else 0
    fast = ema(closes[-min(12, len(closes)):], min(5, len(closes)))
    slow = ema(closes[-min(26, len(closes)):], min(12, len(closes)))
    slope = (fast - slow) / slow if fast is not None and slow else None
    typical_values = []
    typical_vols = []
    for row in bars:
        close = numeric(row.get("close"))
        high = numeric(row.get("high")) or close
        low = numeric(row.get("low")) or close
        volume = numeric(row.get("volume"))
        if close is not None and volume is not None:
            typical_values.append(((high + low + close) / 3) * volume)
            typical_vols.append(volume)
    vwap = sum(typical_values) / sum(typical_vols) if typical_vols and sum(typical_vols) else None
    recent = closes[-20:]
    avg = sum(recent) / len(recent)
    stdev = math.sqrt(sum((x - avg) ** 2 for x in recent) / len(recent)) if len(recent) >= 2 else None
    bb_pos = ((latest - (avg - 2 * stdev)) / (4 * stdev)) if stdev and stdev > 0 else None
    vol_avg = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else None
    vol_confirm = vols[-1] > vol_avg if vols and vol_avg else False
    return {
        "underlying": underlying,
        "timeframe": timeframe,
        "bar_count": len(closes),
        "first_close": first,
        "last_close": latest,
        "return_pct": round(ret, 8),
        "vwap": "" if vwap is None else round(vwap, 8),
        "ema_fast": "" if fast is None else round(fast, 8),
        "ema_slow": "" if slow is None else round(slow, 8),
        "ema_slope": "" if slope is None else round(slope, 8),
        "rsi": "" if rsi(closes) is None else round(rsi(closes), 4),
        "bollinger_position": "" if bb_pos is None else round(bb_pos, 6),
        "volume_latest": "" if not vols else vols[-1],
        "volume_average": "" if vol_avg is None else round(vol_avg, 4),
        "volume_confirmation": vol_confirm,
        "indicator_status": "OK",
    }


def classify_underlying(indicators: list[dict[str, Any]]) -> str:
    valid = [row for row in indicators if row.get("indicator_status") == "OK"]
    if len(valid) < 2:
        return "INTRADAY_DATA_INSUFFICIENT"
    score = 0
    for row in valid:
        ret = numeric(row.get("return_pct")) or 0
        slope = numeric(row.get("ema_slope")) or 0
        close = numeric(row.get("last_close"))
        vwap = numeric(row.get("vwap"))
        if ret > 0:
            score += 1
        elif ret < 0:
            score -= 1
        if slope > 0:
            score += 1
        elif slope < 0:
            score -= 1
        if close is not None and vwap is not None:
            score += 1 if close >= vwap else -1
    if score >= 3:
        return "BULLISH"
    if score <= -3:
        return "BEARISH"
    return "MIXED_OR_WAIT"


def final_direction(soxx: str, qqq: str, spy: str, require_qqq: bool, require_spy: bool) -> tuple[str, bool, str]:
    if "INSUFFICIENT" in {soxx, qqq, spy}:
        return "INTRADAY_DATA_INSUFFICIENT", True, "Intraday bar data missing for one or more required underlyings."
    bull_ok = soxx == "BULLISH" and (not require_qqq or qqq == "BULLISH") and (not require_spy or spy == "BULLISH")
    bear_ok = soxx == "BEARISH" and (not require_qqq or qqq == "BEARISH") and (not require_spy or spy == "BEARISH")
    if bull_ok:
        return "BULL_SEMICONDUCTOR_CONFIRMED", False, "SOXX bullish with required broad confirmation."
    if bear_ok:
        return "BEAR_SEMICONDUCTOR_CONFIRMED", False, "SOXX bearish with required broad confirmation."
    return "MIXED_OR_WAIT", True, "Directional confirmation is mixed or absent."


def build_indicator_outputs(bars_by_symbol: dict[str, dict[str, list[dict[str, Any]]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    audit = []
    snapshot = []
    labels = {}
    for symbol in DIRECTION_UNDERLYINGS:
        rows = [indicators_for_bars(symbol, tf, bars_by_symbol.get(symbol, {}).get(tf, [])) for tf in ["1m", "15m", "1h"]]
        audit.extend(rows)
        label = classify_underlying(rows)
        labels[symbol] = label
        by_tf = {row["timeframe"]: row for row in rows}
        latest = by_tf.get("1m", {})
        snapshot.append({
            "underlying": symbol,
            "bar_count_1m": by_tf.get("1m", {}).get("bar_count", 0),
            "bar_count_15m": by_tf.get("15m", {}).get("bar_count", 0),
            "bar_count_1h": by_tf.get("1h", {}).get("bar_count", 0),
            "latest_close": latest.get("last_close", ""),
            "intraday_return": latest.get("return_pct", ""),
            "vwap": latest.get("vwap", ""),
            "vwap_position": "ABOVE" if numeric(latest.get("last_close")) is not None and numeric(latest.get("vwap")) is not None and numeric(latest.get("last_close")) >= numeric(latest.get("vwap")) else "BELOW_OR_MISSING",
            "ema_slope_1m": by_tf.get("1m", {}).get("ema_slope", ""),
            "ema_slope_15m": by_tf.get("15m", {}).get("ema_slope", ""),
            "ema_slope_1h": by_tf.get("1h", {}).get("ema_slope", ""),
            "rsi_1m": latest.get("rsi", ""),
            "bollinger_position_1m": latest.get("bollinger_position", ""),
            "volume_confirmation": latest.get("volume_confirmation", False),
            "direction_label": label,
            "data_status": "OK" if label != "INTRADAY_DATA_INSUFFICIENT" else "INTRADAY_BAR_DATA_MISSING_RESEARCH_ONLY",
        })
    return snapshot, audit, labels


def map_candidates(candidates: list[dict[str, str]], direction_label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    promoted = []
    rejected = []
    for row in candidates:
        underlying = str(row.get("underlying", "")).upper()
        cp = str(row.get("call_put", "")).upper()
        promote = False
        action = "WAIT"
        if direction_label == "BULL_SEMICONDUCTOR_CONFIRMED":
            promote = underlying == "SOXL" and cp == "CALL"
            action = "PROMOTE_SOXL_CALL_RESEARCH" if promote else ("WATCH_SOXS_PUT_RESEARCH" if underlying == "SOXS" and cp == "PUT" else "REJECT_DIRECTION_MISMATCH")
        elif direction_label == "BEAR_SEMICONDUCTOR_CONFIRMED":
            promote = underlying == "SOXS" and cp == "CALL"
            action = "PROMOTE_SOXS_CALL_RESEARCH" if promote else ("WATCH_SOXL_PUT_RESEARCH" if underlying == "SOXL" and cp == "PUT" else "REJECT_DIRECTION_MISMATCH")
        record = {
            **{field: row.get(field, "") for field in CANDIDATE_FIELDS if field not in {"direction_action", "direction_label", "research_only", "broker_action_allowed", "official_adoption_allowed"}},
            "direction_action": action,
            "direction_label": direction_label,
            "research_only": True,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
        }
        if promote:
            promoted.append(record)
        else:
            rejected.append({**record, "reject_reason": "WAIT_STATE_NO_DIRECTION_PROMOTION" if direction_label in {"MIXED_OR_WAIT", "INTRADAY_DATA_INSUFFICIENT", "NO_TRADE_RESEARCH_ONLY"} else "DIRECTION_MISMATCH"})
    return promoted, rejected


def load_v22_041(repo_root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    root = repo_root / V22_041_REL
    return read_json(root / "v22_041_summary.json"), read_csv_rows(root / "etf_option_liquidity_candidates.csv")


def build_summary(
    execution_mode: str,
    v41: dict[str, Any],
    candidates: list[dict[str, str]],
    attempted: bool,
    available: bool,
    labels: dict[str, str],
    final_label: str,
    wait_state: bool,
    promoted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    timestamp_context: dict[str, Any],
) -> dict[str, Any]:
    v41_found = bool(v41)
    v41_count = int(v41.get("liquidity_candidate_count", len(candidates)) or 0) if v41_found else 0
    v41_ok = v41_found and v41.get("real_readonly_quote_verified") is True and v41.get("fallback_rows_used") is False and v41_count > 0
    insufficient = not available or final_label == "INTRADAY_DATA_INSUFFICIENT"
    if not v41_ok:
        status, decision = WARN_CANDIDATES_STATUS, WAIT_DECISION
    elif insufficient:
        status, decision = WARN_DATA_STATUS, WAIT_DECISION
    else:
        status, decision = PASS_STATUS, WAIT_DECISION if wait_state else PASS_DECISION
    return {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "generated_at_utc": utc_now_text(),
        "final_status": status,
        "final_decision": decision,
        "execution_mode": execution_mode,
        "v22_041_summary_found": v41_found,
        "v22_041_liquidity_candidate_count": v41_count,
        "v22_041_real_readonly_quote_verified": bool(v41.get("real_readonly_quote_verified", False)),
        "v22_041_fallback_rows_used": bool(v41.get("fallback_rows_used", False)),
        "intraday_data_attempted": attempted,
        "intraday_data_available": available,
        "soxx_direction_label": labels.get("SOXX", "INTRADAY_DATA_INSUFFICIENT"),
        "qqq_confirmation_label": labels.get("QQQ", "INTRADAY_DATA_INSUFFICIENT"),
        "spy_confirmation_label": labels.get("SPY", "INTRADAY_DATA_INSUFFICIENT"),
        "final_direction_label": final_label,
        "promoted_candidate_count": len(promoted),
        "rejected_by_direction_count": len(rejected),
        "wait_state": wait_state,
        "direction_gate_passed": not wait_state and len(promoted) > 0,
        "intraday_data_insufficient": insufficient,
        "direction_timestamp_contract_version": timestamp_context.get("direction_timestamp_contract_version", TIMESTAMP_CONTRACT_VERSION),
        "direction_source_time_utc": timestamp_context.get("direction_source_time_utc", ""),
        "direction_source_time_policy": timestamp_context.get("direction_source_time_policy", "MIN_LATEST_BAR_TIME_ACROSS_REQUIRED_UNDERLYING_TIMEFRAMES"),
        "direction_source_time_trust": timestamp_context.get("direction_source_time_trust", "MISSING"),
        "direction_timestamp_complete": bool(timestamp_context.get("direction_timestamp_complete", False)),
        "direction_required_timestamp_row_count": int(timestamp_context.get("direction_required_timestamp_row_count", 0) or 0),
        "direction_parsed_timestamp_row_count": int(timestamp_context.get("direction_parsed_timestamp_row_count", 0) or 0),
        "direction_input_latest_time_min_utc": timestamp_context.get("direction_input_latest_time_min_utc", ""),
        "direction_input_latest_time_max_utc": timestamp_context.get("direction_input_latest_time_max_utc", ""),
        "direction_input_time_dispersion_seconds": timestamp_context.get("direction_input_time_dispersion_seconds", ""),
        "direction_bar_timestamp_provenance_path": timestamp_context.get("direction_bar_timestamp_provenance_path", ""),
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.042 Option Intraday ETF Direction Gate R1", *[f"{key}={summary.get(key)}" for key in SUMMARY_FIELDS]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    lookback_minutes: int = 240,
    use_v22_041_latest: bool = True,
    require_qqq_confirmation: bool = True,
    require_spy_confirmation: bool = False,
    bars_by_symbol: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    v22_041_summary: dict[str, Any] | None = None,
    v22_041_candidates: list[dict[str, str]] | None = None,
    host: str = "127.0.0.1",
    port: int = 18441,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = repo_root / OUT_REL
    output_dir.mkdir(parents=True, exist_ok=True)
    if v22_041_summary is None or v22_041_candidates is None:
        v22_041_summary, v22_041_candidates = load_v22_041(repo_root) if use_v22_041_latest else ({}, [])
    attempted = False
    if bars_by_symbol is None:
        if execute:
            attempted = True
            bars_by_symbol, _connected = fetch_intraday_bars(repo_root, host, port, lookback_minutes)
        else:
            bars_by_symbol = {}
    else:
        attempted = execute
    timestamp_rows, timestamp_context = build_timestamp_provenance(
        bars_by_symbol,
        lookback_minutes,
        require_qqq_confirmation,
        require_spy_confirmation,
    )
    timestamp_context["direction_bar_timestamp_provenance_path"] = str(
        output_dir / "direction_bar_timestamp_provenance.csv"
    )
    snapshot, audit, labels = build_indicator_outputs(bars_by_symbol)
    available = all(row["data_status"] == "OK" for row in snapshot)
    final_label, wait_state, reason = final_direction(labels.get("SOXX", "INTRADAY_DATA_INSUFFICIENT"), labels.get("QQQ", "INTRADAY_DATA_INSUFFICIENT"), labels.get("SPY", "INTRADAY_DATA_INSUFFICIENT"), require_qqq_confirmation, require_spy_confirmation)
    promoted, rejected = map_candidates(v22_041_candidates, final_label if available else "INTRADAY_DATA_INSUFFICIENT")
    if not available:
        final_label = "INTRADAY_DATA_INSUFFICIENT"
        wait_state = True
        reason = "Intraday bar data missing; direction not fabricated from snapshots."
    decision_rows = [{"decision_scope": "V22.042_R1", "soxx_direction_label": labels.get("SOXX", "INTRADAY_DATA_INSUFFICIENT"), "qqq_confirmation_label": labels.get("QQQ", "INTRADAY_DATA_INSUFFICIENT"), "spy_confirmation_label": labels.get("SPY", "INTRADAY_DATA_INSUFFICIENT"), "final_direction_label": final_label, "wait_state": wait_state, "direction_gate_passed": not wait_state and bool(promoted), "reason": reason}]
    summary = build_summary("EXECUTE_READ_ONLY" if execute else "PLAN", v22_041_summary, v22_041_candidates, attempted, available, labels, final_label, wait_state, promoted, rejected, timestamp_context)
    write_csv(output_dir / "direction_bar_timestamp_provenance.csv", TIMESTAMP_PROVENANCE_FIELDS, timestamp_rows)
    write_csv(output_dir / "etf_intraday_direction_snapshot.csv", SNAPSHOT_FIELDS, snapshot)
    write_csv(output_dir / "etf_intraday_indicator_audit.csv", INDICATOR_FIELDS, audit)
    write_csv(output_dir / "etf_direction_gate_decision.csv", DECISION_FIELDS, decision_rows)
    write_csv(output_dir / "etf_option_candidates_direction_filtered.csv", CANDIDATE_FIELDS, promoted)
    write_csv(output_dir / "etf_option_candidates_rejected_by_direction.csv", REJECT_FIELDS, rejected)
    write_json(output_dir / "v22_042_summary.json", summary)
    (output_dir / "V22.042_option_intraday_etf_direction_gate_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--lookback-minutes", type=int, default=240)
    parser.add_argument("--use-v22-041-latest", action="store_true", default=True)
    parser.add_argument("--no-use-v22-041-latest", dest="use_v22_041_latest", action="store_false")
    parser.add_argument("--require-qqq-confirmation", action="store_true", default=True)
    parser.add_argument("--no-require-qqq-confirmation", dest="require_qqq_confirmation", action="store_false")
    parser.add_argument("--require-spy-confirmation", action="store_true", default=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18441)
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.lookback_minutes, args.use_v22_041_latest, args.require_qqq_confirmation, args.require_spy_confirmation, None, None, None, args.host, args.port)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_042_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
