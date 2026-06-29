#!/usr/bin/env python
"""V21.095-R7A API Ninjas earnings provider contract repair."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


CONFIG_REL = Path("config/v21_event_sources.json")
OUT_REL = Path("outputs/v21")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
RAW_REL = Path("data/events/raw_snapshots")
GENERATED_REL = Path("data/events/manual_import/generated/earnings")
R6_REL = Path(
    "scripts/v21/v21_095_r6_import_pit_timestamped_macro_and_earnings_snapshots.py"
)
SOURCE_ID = "earnings_calendar_api_provider"
KEY_ENV_VARS = ("EARNINGS_CALENDAR_API_KEY", "API_NINJAS_API_KEY")
ENDPOINTS = {
    "earningscalendar": (
        "https://api.api-ninjas.com/v1/earningscalendar",
        "/v1/earningscalendar",
    ),
    "upcomingearnings": (
        "https://api.api-ninjas.com/v1/upcomingearnings",
        "/v1/upcomingearnings",
    ),
}
NORMALIZED_COLUMNS = [
    "event_id", "event_type", "event_name", "event_date", "event_time",
    "event_timezone", "affected_ticker", "affected_sector", "earnings_session",
    "candidate_universe_member", "source_name", "source_url_or_provider",
    "retrieval_timestamp_utc", "provider_available_date",
    "known_as_of_timestamp", "raw_payload_hash", "normalized_row_hash",
    "source_confidence", "pit_certified", "pit_exclusion_reason",
    "historical_backtest_usable", "forward_observation_usable",
    "research_only", "notes",
]
OUTPUT_NAMES = (
    "v21_095_r7a_api_ninjas_request_diagnostics.csv",
    "v21_095_r7a_ticker_earnings_events_normalized.csv",
    "v21_095_r7a_auto_event_source_autofiller_report.md",
    "v21_095_r7a_auto_event_source_autofiller_summary.json",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def row_hash(row: dict[str, Any]) -> str:
    text = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=json_default) + "\n", encoding="utf-8")


def markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [f"# {title}", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in payload.items())
    lines.extend([
        "",
        "Request diagnostics contain endpoint paths and sanitized parameters only. API keys, "
        "request headers, and sensitive URLs are never persisted.",
    ])
    return "\n".join(lines) + "\n"


def load_config(root: Path) -> dict[str, Any]:
    registry = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    return next((row for row in registry if row.get("source_id") == SOURCE_ID), {})


def resolve_key(config: dict[str, Any]) -> tuple[str, str]:
    configured = config.get("api_key_env_vars", [])
    for name in configured:
        if name not in KEY_ENV_VARS:
            continue
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def protected_snapshot(root: Path, outputs: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    event_root = (root / "data/events").resolve()
    result = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.resolve() in outputs:
                continue
            if event_root in path.resolve().parents:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


def sanitized_params(params: dict[str, Any]) -> str:
    allowed = {
        "ticker", "date", "date_start", "date_end", "show_upcoming",
        "start_date", "end_date", "limit", "offset",
    }
    clean = {key: params[key] for key in sorted(params) if key in allowed}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


def provider_error(decoded: Any) -> tuple[str, str]:
    if isinstance(decoded, list):
        return "", ""
    if isinstance(decoded, dict):
        code = str(decoded.get("code") or decoded.get("error_code") or "PROVIDER_ERROR")
        message = str(decoded.get("error") or decoded.get("message") or "")
        lower = message.lower()
        if "premium" in lower or "subscription" in lower or "plan" in lower:
            return code, "PREMIUM_OR_PLAN_RESTRICTION"
        if "unsupported" in lower or "invalid" in lower or "parameter" in lower:
            return code, "UNSUPPORTED_OR_INVALID_PARAMETER"
        return code, "PROVIDER_ERROR_MESSAGE_REDACTED"
    return "INVALID_RESPONSE_SHAPE", "PROVIDER_RESPONSE_NOT_ARRAY"


def decode_payload(payload: bytes) -> Any:
    return json.loads(payload.decode("utf-8"))


def http_attempt(
    endpoint_url: str,
    params: dict[str, Any],
    api_key: str,
    timeout: int = 30,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{endpoint_url}?{query}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = int(exc.code)
    except urllib.error.URLError:
        return {
            "http_status": 0, "payload": b"", "decoded": None,
            "provider_error_code": "NETWORK_URL_ERROR",
            "provider_error_message_redacted": "NETWORK_ERROR",
        }
    if api_key.encode("utf-8") in payload:
        return {
            "http_status": status, "payload": b"", "decoded": None,
            "provider_error_code": "KEY_MATERIAL_IN_RESPONSE",
            "provider_error_message_redacted": "SECURITY_REJECTION",
        }
    try:
        decoded = decode_payload(payload)
        code, message = provider_error(decoded)
    except Exception:
        decoded = None
        code, message = "INVALID_JSON_RESPONSE", "PROVIDER_RESPONSE_NOT_JSON"
    return {
        "http_status": status, "payload": payload, "decoded": decoded,
        "provider_error_code": code,
        "provider_error_message_redacted": message,
    }


def build_params(
    endpoint_mode: str,
    ticker: str,
    start_date: str,
    end_date: str,
    use_date_range: bool,
    show_upcoming: bool = True,
) -> dict[str, Any]:
    if endpoint_mode == "earningscalendar":
        params: dict[str, Any] = {"ticker": ticker}
        if show_upcoming:
            params["show_upcoming"] = "true"
        if use_date_range:
            params["date_start"] = start_date
            params["date_end"] = end_date
        return params
    return {
        "ticker": ticker, "start_date": start_date, "end_date": end_date,
        "limit": 100,
    }


def should_retry_without_upcoming(attempt: dict[str, Any]) -> bool:
    if attempt["http_status"] == 400:
        return True
    message = str(attempt["provider_error_message_redacted"])
    return message in {"PREMIUM_OR_PLAN_RESTRICTION", "UNSUPPORTED_OR_INVALID_PARAMETER"}


def fetch_ticker(
    endpoint_mode: str,
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str,
    use_date_range: bool,
    attempt_fn=http_attempt,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[bytes, str]]]:
    endpoint_url, endpoint_path = ENDPOINTS[endpoint_mode]
    attempts = []
    snapshots = []
    first_params = build_params(
        endpoint_mode, ticker, start_date, end_date, use_date_range, True
    )
    first = attempt_fn(endpoint_url, first_params, api_key)
    attempts.append({
        "ticker": ticker, "endpoint_mode": endpoint_mode,
        "endpoint_path": endpoint_path,
        "sanitized_params": sanitized_params(first_params),
        "http_status": first["http_status"],
        "fetch_status": (
            "SUCCESS" if first["http_status"] == 200
            and isinstance(first["decoded"], list) else "FAILED"
        ),
        "retry_attempted": False, "retry_reason": "",
        "response_row_count": len(first["decoded"]) if isinstance(first["decoded"], list) else 0,
        "provider_error_code": first["provider_error_code"],
        "provider_error_message_redacted": first["provider_error_message_redacted"],
        "notes": "API key and request headers omitted.",
    })
    final = first
    if (
        endpoint_mode == "earningscalendar"
        and should_retry_without_upcoming(first)
    ):
        retry_params = build_params(
            endpoint_mode, ticker, start_date, end_date, use_date_range, False
        )
        retry = attempt_fn(endpoint_url, retry_params, api_key)
        attempts[-1]["retry_attempted"] = True
        attempts[-1]["retry_reason"] = (
            "SHOW_UPCOMING_HTTP_400" if first["http_status"] == 400
            else "SHOW_UPCOMING_UNSUPPORTED_OR_PREMIUM"
        )
        attempts.append({
            "ticker": ticker, "endpoint_mode": endpoint_mode,
            "endpoint_path": endpoint_path,
            "sanitized_params": sanitized_params(retry_params),
            "http_status": retry["http_status"],
            "fetch_status": (
                "SUCCESS" if retry["http_status"] == 200
                and isinstance(retry["decoded"], list) else "FAILED"
            ),
            "retry_attempted": True,
            "retry_reason": attempts[-1]["retry_reason"],
            "response_row_count": len(retry["decoded"]) if isinstance(retry["decoded"], list) else 0,
            "provider_error_code": retry["provider_error_code"],
            "provider_error_message_redacted": retry["provider_error_message_redacted"],
            "notes": "Fallback removed show_upcoming; API key and headers omitted.",
        })
        final = retry
    if final["http_status"] == 200 and isinstance(final["decoded"], list):
        snapshots.append((final["payload"], ticker))
        return final["decoded"], attempts, snapshots
    return [], attempts, snapshots


def event_time_from_timestamp(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        timestamp = float(value)
        if timestamp <= 0:
            return ""
        moment = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(
            ZoneInfo("America/New_York")
        )
        return moment.strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def session_value(value: Any) -> str:
    return {
        "before_market": "BEFORE_MARKET",
        "during_market": "DURING_MARKET",
        "after_market": "AFTER_MARKET",
    }.get(str(value).strip().lower(), "")


def normalize(
    provider_rows: list[dict[str, Any]],
    ticker: str,
    retrieval_ts: pd.Timestamp,
    raw_hash: str,
    universe: set[str],
    run_date: pd.Timestamp,
    end_date: pd.Timestamp,
    allow_past: bool,
    recent_buffer_days: int,
    endpoint_mode: str = "earningscalendar",
) -> tuple[pd.DataFrame, int]:
    rows = []
    past_filtered = 0
    for index, raw in enumerate(provider_rows):
        returned_ticker = str(raw.get("ticker", ticker)).upper().strip()
        event_date = pd.to_datetime(raw.get("date"), errors="coerce")
        if pd.isna(event_date) or returned_ticker != ticker:
            continue
        if event_date.date() < run_date.date() and not allow_past:
            past_filtered += 1
            continue
        if event_date.date() > end_date.date():
            continue
        forward = event_date.date() >= (
            run_date - pd.Timedelta(days=recent_buffer_days)
        ).date()
        base = {
            "event_type": "ticker_earnings",
            "event_name": f"{ticker} earnings",
            "event_date": event_date.date().isoformat(),
            "event_time": event_time_from_timestamp(raw.get("earnings_call_timestamp")),
            "event_timezone": "America/New_York",
            "affected_ticker": ticker, "affected_sector": "ALL",
            "earnings_session": session_value(raw.get("earnings_timing")),
            "candidate_universe_member": ticker in universe,
            "source_name": "API Ninjas Earnings Calendar",
            "source_url_or_provider": ENDPOINTS[endpoint_mode][0],
            "retrieval_timestamp_utc": retrieval_ts.isoformat(),
            "provider_available_date": "",
            "known_as_of_timestamp": retrieval_ts.isoformat(),
            "raw_payload_hash": raw_hash, "normalized_row_hash": "",
            "source_confidence": "LOW", "pit_certified": True,
            "pit_exclusion_reason": "", "historical_backtest_usable": False,
            "forward_observation_usable": forward, "research_only": True,
            "notes": "Date/session/call timestamp only; financial result fields ignored.",
        }
        identity = "|".join([
            SOURCE_ID, ticker, base["event_date"], retrieval_ts.isoformat(),
            raw_hash, str(index),
        ])
        base["event_id"] = "V21_095_R7A_" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()[:20].upper()
        base["normalized_row_hash"] = row_hash(base)
        rows.append(base)
    frame = pd.DataFrame(rows, columns=NORMALIZED_COLUMNS) if rows else pd.DataFrame(
        columns=NORMALIZED_COLUMNS
    )
    return frame, past_filtered


def write_generated(root: Path, normalized: pd.DataFrame, run_ts: pd.Timestamp) -> Path:
    destination = root / GENERATED_REL
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"auto_earnings_events_{run_ts:%Y%m%d_%H%M%S}.csv"
    pd.DataFrame({
        "ticker": normalized["affected_ticker"],
        "event_type": normalized["event_type"],
        "event_name": normalized["event_name"],
        "event_date": normalized["event_date"],
        "event_time": normalized["event_time"],
        "event_timezone": normalized["event_timezone"],
        "earnings_session": normalized["earnings_session"],
        "source_name": normalized["source_name"],
        "source_url_or_provider": normalized["source_url_or_provider"],
        "retrieval_timestamp_utc": normalized["retrieval_timestamp_utc"],
        "provider_available_date": normalized["provider_available_date"],
        "notes": normalized["notes"],
    }).to_csv(path, index=False)
    return path


def load_r6(root: Path):
    spec = importlib.util.spec_from_file_location("v21_095_r6_r7a", root / R6_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    root: Path,
    endpoint_mode: str,
    tickers: list[str],
    lookahead_days: int,
    allow_low_confidence: bool,
    reuse_r6: bool,
    allow_past: bool,
    use_date_range: bool,
    recent_buffer_days: int = 7,
    fetch_fn=fetch_ticker,
) -> dict[str, Any]:
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUT_NAMES}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256_file(root / D_REL)
    config = load_config(root)
    api_key, env_name = resolve_key(config)
    key_present = bool(api_key)
    fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else ""
    run_ts = pd.Timestamp(datetime.now(timezone.utc))
    run_date = run_ts.normalize()
    end_date = run_date + pd.Timedelta(days=max(1, lookahead_days))
    requested = list(dict.fromkeys(
        ticker.strip().upper() for ticker in tickers if ticker.strip()
    ))
    universe = set(pd.read_csv(
        root / D_REL, usecols=["ticker"], low_memory=False
    )["ticker"].astype(str).str.upper().str.strip()) | {
        "SPY", "QQQ", "SMH", "SOXX", "TQQQ"
    }
    diagnostics = []
    normalized_parts = []
    past_filtered_total = 0
    raw_dir = root / RAW_REL / run_ts.date().isoformat() / "auto" / SOURCE_ID
    if key_present and allow_low_confidence:
        raw_dir.mkdir(parents=True, exist_ok=True)
        for ticker in requested:
            retrieval_ts = pd.Timestamp(datetime.now(timezone.utc))
            provider_rows, ticker_diagnostics, snapshots = fetch_fn(
                endpoint_mode, ticker, run_date.date().isoformat(),
                end_date.date().isoformat(), api_key, use_date_range,
            )
            diagnostics.extend(ticker_diagnostics)
            for payload, payload_ticker in snapshots:
                if api_key.encode("utf-8") in payload:
                    continue
                raw_hash = sha256_bytes(payload)
                path = raw_dir / (
                    f"{payload_ticker}_{retrieval_ts:%Y%m%d_%H%M%S_%f}_{raw_hash[:12]}.json"
                )
                path.write_bytes(payload)
                frame, past_filtered = normalize(
                    provider_rows, ticker, retrieval_ts, raw_hash, universe,
                    run_date, end_date, allow_past, recent_buffer_days,
                    endpoint_mode,
                )
                normalized_parts.append(frame)
                past_filtered_total += past_filtered
    elif key_present and not allow_low_confidence:
        for ticker in requested:
            diagnostics.append({
                "ticker": ticker, "endpoint_mode": endpoint_mode,
                "endpoint_path": ENDPOINTS[endpoint_mode][1],
                "sanitized_params": "{}",
                "http_status": 0, "fetch_status": "SKIPPED",
                "retry_attempted": False,
                "retry_reason": "LOW_CONFIDENCE_NOT_ALLOWED",
                "response_row_count": 0,
                "provider_error_code": "LOW_CONFIDENCE_NOT_ALLOWED",
                "provider_error_message_redacted": "",
                "notes": "Use --allow-low-confidence-earnings to fetch.",
            })
    elif not key_present:
        for ticker in requested:
            params = build_params(
                endpoint_mode, ticker, run_date.date().isoformat(),
                end_date.date().isoformat(), use_date_range, True,
            )
            diagnostics.append({
                "ticker": ticker, "endpoint_mode": endpoint_mode,
                "endpoint_path": ENDPOINTS[endpoint_mode][1],
                "sanitized_params": sanitized_params(params),
                "http_status": 0, "fetch_status": "SKIPPED",
                "retry_attempted": False, "retry_reason": "API_KEY_MISSING",
                "response_row_count": 0,
                "provider_error_code": "API_KEY_MISSING",
                "provider_error_message_redacted": "",
                "notes": "No request attempted; key and headers omitted.",
            })
    diagnostics_frame = pd.DataFrame(diagnostics, columns=[
        "ticker", "endpoint_mode", "endpoint_path", "sanitized_params",
        "http_status", "fetch_status", "retry_attempted", "retry_reason",
        "response_row_count", "provider_error_code",
        "provider_error_message_redacted", "notes",
    ])
    diagnostics_frame.to_csv(out / OUTPUT_NAMES[0], index=False)
    normalized = pd.concat(normalized_parts, ignore_index=True) if normalized_parts else pd.DataFrame(
        columns=NORMALIZED_COLUMNS
    )
    normalized = normalized.drop_duplicates(
        ["affected_ticker", "event_date", "earnings_session"], keep="last"
    )
    normalized.to_csv(out / OUTPUT_NAMES[1], index=False)
    generated_path = ""
    r6_certified_rows = 0
    if len(normalized):
        generated = write_generated(root, normalized, run_ts)
        generated_path = generated.relative_to(root).as_posix()
        if reuse_r6:
            r6_summary = load_r6(root).run(root)
            r6_certified_rows = int(r6_summary["CERTIFIED_TICKER_EVENT_ROWS"])

    statuses = pd.to_numeric(
        diagnostics_frame["http_status"], errors="coerce"
    ) if len(diagnostics_frame) else pd.Series(dtype=float)
    attempts = int(statuses.gt(0).sum())
    successes = int(diagnostics_frame["fetch_status"].eq("SUCCESS").sum())
    http_400 = int(statuses.eq(400).sum())
    http_401_403 = int(statuses.isin([401, 403]).sum())
    other_failed = int(
        diagnostics_frame["fetch_status"].eq("FAILED").sum()
        - http_400 - http_401_403
    ) if len(diagnostics_frame) else 0
    certified = int(normalized["pit_certified"].map(truth).sum())
    warnings = int((
        normalized["pit_certified"].map(truth)
        & pd.to_datetime(normalized["known_as_of_timestamp"], utc=True, errors="coerce").isna()
    ).sum())
    if not key_present:
        decision = "AUTO_EARNINGS_PROVIDER_KEY_MISSING"
    elif attempts > 0 and http_400 == attempts:
        decision = "AUTO_EARNINGS_PROVIDER_CONTRACT_ERROR"
    elif attempts > 0 and http_401_403 == attempts:
        decision = "AUTO_EARNINGS_PROVIDER_PERMISSION_OR_PLAN_ERROR"
    elif successes > 0 and certified == 0 and past_filtered_total > 0:
        decision = "AUTO_EARNINGS_PROVIDER_FETCHED_NO_FORWARD_EVENTS"
    elif certified > 0 and (not reuse_r6 or r6_certified_rows > 0):
        decision = "AUTO_TICKER_EVENTS_IMPORTED_READY_FOR_FORWARD_OBSERVATION"
    elif attempts > 0 and successes == 0:
        decision = (
            "AUTO_EARNINGS_PROVIDER_PERMISSION_OR_PLAN_ERROR"
            if http_401_403 > 0 and http_401_403 + http_400 == attempts
            else "AUTO_EARNINGS_PROVIDER_FETCH_FAILED"
        )
    else:
        decision = "AUTO_EARNINGS_PROVIDER_FETCHED_NO_FORWARD_EVENTS"

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = sha256_file(root / D_REL) == d_hash_before
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    summary = {
        "FINAL_STATUS": "PASS" if not warnings and not changed and d_preserved else "FAIL",
        "DECISION": decision, "API_KEY_PRESENT": key_present,
        "API_KEY_FINGERPRINT": fingerprint,
        "API_KEY_ENV_VAR_USED": env_name if key_present else "",
        "API_NINJAS_ENDPOINT_MODE": endpoint_mode,
        "TICKERS_REQUESTED": len(requested), "REQUESTS_ATTEMPTED": attempts,
        "REQUESTS_SUCCEEDED": successes, "REQUESTS_HTTP_400": http_400,
        "REQUESTS_HTTP_401_403": http_401_403,
        "REQUESTS_OTHER_FAILED": max(0, other_failed),
        "AUTO_EARNINGS_EVENT_ROWS": len(normalized),
        "CERTIFIED_TICKER_EVENT_ROWS": certified,
        "FORWARD_EVENT_OBSERVATION_ALLOWED": bool(
            normalized["forward_observation_usable"].map(truth).any()
        ) if len(normalized) else False,
        "HISTORICAL_RANDOM_BACKTEST_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": warnings,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "GENERATED_IMPORT_PATH": generated_path,
        "R6_CERTIFIED_TICKER_ROWS": r6_certified_rows,
        "PAST_ROWS_FILTERED": past_filtered_total,
    }
    write_json(out / OUTPUT_NAMES[3], summary)
    (out / OUTPUT_NAMES[2]).write_text(markdown(
        "V21.095-R7A API Ninjas Earnings Provider Contract Repair", summary
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--api-ninjas-endpoint",
        choices=["earningscalendar", "upcomingearnings"],
        default="earningscalendar",
    )
    parser.add_argument("--tickers", default="MU,WDC,STX,NVDA")
    parser.add_argument("--lookahead-days", type=int, default=120)
    parser.add_argument("--allow-low-confidence-earnings", action="store_true")
    parser.add_argument("--reuse-r6-importer", action="store_true")
    parser.add_argument("--allow-past-forward-snapshot", action="store_true")
    parser.add_argument("--api-ninjas-use-date-range", action="store_true")
    parser.add_argument("--recent-buffer-days", type=int, default=7)
    args = parser.parse_args()
    summary = run(
        args.root.resolve(), args.api_ninjas_endpoint, args.tickers.split(","),
        args.lookahead_days, args.allow_low_confidence_earnings,
        args.reuse_r6_importer, args.allow_past_forward_snapshot,
        args.api_ninjas_use_date_range, max(0, args.recent_buffer_days),
    )
    keys = (
        "FINAL_STATUS", "DECISION", "API_KEY_PRESENT", "API_KEY_FINGERPRINT",
        "API_KEY_ENV_VAR_USED", "API_NINJAS_ENDPOINT_MODE", "TICKERS_REQUESTED",
        "REQUESTS_ATTEMPTED", "REQUESTS_SUCCEEDED", "REQUESTS_HTTP_400",
        "REQUESTS_HTTP_401_403", "REQUESTS_OTHER_FAILED",
        "AUTO_EARNINGS_EVENT_ROWS", "CERTIFIED_TICKER_EVENT_ROWS",
        "FORWARD_EVENT_OBSERVATION_ALLOWED", "HISTORICAL_RANDOM_BACKTEST_ALLOWED",
        "PIT_LEAKAGE_WARNINGS", "PROTECTED_OUTPUTS_MODIFIED",
        "OFFICIAL_OUTPUTS_MODIFIED", "RESEARCH_ONLY",
        "OFFICIAL_ADOPTION_ALLOWED", "D_BASELINE_PRESERVED",
    )
    for key in keys:
        print(f"{key}={summary[key]}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
