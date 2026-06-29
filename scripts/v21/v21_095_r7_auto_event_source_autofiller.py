#!/usr/bin/env python
"""V21.095-R7 secure API-key earnings event autofiller."""

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

import numpy as np
import pandas as pd


CONFIG_REL = Path("config/v21_event_sources.json")
OUT_REL = Path("outputs/v21")
D_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
GENERATED_REL = Path("data/events/manual_import/generated/earnings")
RAW_REL = Path("data/events/raw_snapshots")
R6_SCRIPT_REL = Path(
    "scripts/v21/v21_095_r6_import_pit_timestamped_macro_and_earnings_snapshots.py"
)
SOURCE_ID = "earnings_calendar_api_provider"
ALLOWED_KEY_ENV_VARS = ("EARNINGS_CALENDAR_API_KEY", "API_NINJAS_API_KEY")
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
    "v21_095_r7_source_fetch_plan.csv",
    "v21_095_r7_raw_fetch_manifest.csv",
    "v21_095_r7_ticker_earnings_events_normalized.csv",
    "v21_095_r7_auto_event_source_autofiller_report.md",
    "v21_095_r7_auto_event_source_autofiller_summary.json",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        "Credentials are read only from approved environment variables. Raw key material is "
        "never logged, persisted, placed in request metadata outputs, or included in errors.",
    ])
    return "\n".join(lines) + "\n"


def load_provider_config(root: Path) -> dict[str, Any]:
    registry = json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))
    return next(
        (row for row in registry if row.get("source_id") == SOURCE_ID),
        {},
    )


def resolve_api_key(config: dict[str, Any]) -> tuple[str, str]:
    configured = config.get("api_key_env_vars", [])
    allowed = [name for name in configured if name in ALLOWED_KEY_ENV_VARS]
    for name in allowed:
        value = os.environ.get(name, "")
        if value.strip():
            return value.strip(), name
    return "", ""


def redact_error(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP_ERROR_{error.code}"
    if isinstance(error, urllib.error.URLError):
        return "NETWORK_URL_ERROR"
    if isinstance(error, TimeoutError):
        return "NETWORK_TIMEOUT"
    return f"PROVIDER_ERROR_{type(error).__name__}"


def protected_snapshot(root: Path, output_paths: set[Path]) -> dict[str, str]:
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
            if not path.is_file() or path.resolve() in output_paths:
                continue
            if event_root in path.resolve().parents:
                continue
            if any(token in path.as_posix().lower() for token in tokens):
                result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


def request_upcoming(
    endpoint: str,
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str,
    timeout: int = 30,
) -> tuple[bytes, list[dict[str, Any]], int]:
    query = urllib.parse.urlencode({
        "ticker": ticker, "start_date": start_date, "end_date": end_date,
        "limit": 100,
    })
    request = urllib.request.Request(
        f"{endpoint}?{query}",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        status = int(getattr(response, "status", 200))
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, list):
        raise ValueError("PROVIDER_RESPONSE_NOT_LIST")
    return payload, decoded, status


def session_value(value: Any) -> str:
    mapping = {
        "before_market": "BEFORE_MARKET",
        "during_market": "DURING_MARKET",
        "after_market": "AFTER_MARKET",
    }
    return mapping.get(str(value).strip().lower(), "")


def normalize_events(
    fetched: list[dict[str, Any]],
    ticker: str,
    retrieval_ts: pd.Timestamp,
    raw_hash: str,
    source_name: str,
    source_url: str,
    universe: set[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    for index, raw in enumerate(fetched):
        returned_ticker = str(raw.get("ticker", ticker)).upper().strip()
        event_date = pd.to_datetime(raw.get("date"), errors="coerce")
        if (
            pd.isna(event_date)
            or returned_ticker != ticker
            or not start_date.date() <= event_date.date() <= end_date.date()
        ):
            continue
        session = session_value(raw.get("earnings_timing"))
        base = {
            "event_type": "ticker_earnings",
            "event_name": f"{returned_ticker} earnings",
            "event_date": event_date.date().isoformat(),
            "event_time": "",
            "event_timezone": "America/New_York",
            "affected_ticker": returned_ticker,
            "affected_sector": "ALL",
            "earnings_session": session,
            "candidate_universe_member": returned_ticker in universe,
            "source_name": source_name,
            "source_url_or_provider": source_url,
            "retrieval_timestamp_utc": retrieval_ts.isoformat(),
            "provider_available_date": "",
            "known_as_of_timestamp": retrieval_ts.isoformat(),
            "raw_payload_hash": raw_hash,
            "normalized_row_hash": "",
            "source_confidence": "LOW",
            "pit_certified": True,
            "pit_exclusion_reason": "",
            "historical_backtest_usable": False,
            "forward_observation_usable": True,
            "research_only": True,
            "notes": "Upcoming date/session only; provider estimates and actuals ignored.",
        }
        identity = "|".join([
            SOURCE_ID, returned_ticker, base["event_date"],
            retrieval_ts.isoformat(), str(index), raw_hash,
        ])
        base["event_id"] = "V21_095_R7_" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()[:20].upper()
        base["normalized_row_hash"] = row_hash(base)
        rows.append(base)
    return pd.DataFrame(rows, columns=NORMALIZED_COLUMNS) if rows else pd.DataFrame(
        columns=NORMALIZED_COLUMNS
    )


def write_generated_csv(
    root: Path, normalized: pd.DataFrame, run_ts: pd.Timestamp
) -> Path:
    destination = root / GENERATED_REL
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"auto_earnings_events_{run_ts:%Y%m%d_%H%M%S}.csv"
    generated = pd.DataFrame({
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
    })
    generated.to_csv(path, index=False)
    return path


def load_r6(root: Path):
    path = root / R6_SCRIPT_REL
    spec = importlib.util.spec_from_file_location("v21_095_r6_reuse", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    root: Path,
    earnings_provider: str,
    tickers: list[str],
    lookahead_days: int,
    allow_low_confidence: bool,
    reuse_r6: bool,
    fetcher=request_upcoming,
) -> dict[str, Any]:
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUT_NAMES}
    before = protected_snapshot(root, output_paths)
    d_hash_before = sha256_file(root / D_REL)
    config = load_provider_config(root)
    api_key, key_env_name = resolve_api_key(config)
    key_present = bool(api_key)
    fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else ""
    enabled = bool(config.get("enabled")) and earnings_provider == "api"
    run_ts = pd.Timestamp(datetime.now(timezone.utc))
    start_date = run_ts.normalize()
    end_date = start_date + pd.Timedelta(days=lookahead_days)
    clean_tickers = list(dict.fromkeys(
        ticker.strip().upper() for ticker in tickers if ticker.strip()
    ))

    d = pd.read_csv(root / D_REL, usecols=["ticker"], low_memory=False)
    universe = set(d["ticker"].astype(str).str.upper().str.strip()) | {
        "SPY", "QQQ", "SMH", "SOXX", "TQQQ"
    }
    plan_rows = [{
        "source_id": SOURCE_ID, "earnings_provider": earnings_provider,
        "provider_enabled": enabled, "ticker": ticker,
        "lookahead_start_date": start_date.date().isoformat(),
        "lookahead_end_date": end_date.date().isoformat(),
        "requires_network": bool(config.get("requires_network")),
        "requires_api_key": bool(config.get("requires_api_key")),
        "api_key_present": key_present,
        "api_key_fingerprint": fingerprint,
        "historical_backtest_allowed": False,
        "forward_observation_only": True,
        "status": (
            "READY" if enabled and key_present and allow_low_confidence
            else "LOW_CONFIDENCE_NOT_ALLOWED" if enabled and key_present
            else "API_KEY_MISSING" if enabled
            else "PROVIDER_DISABLED"
        ),
        "notes": "Request headers and credentials are not persisted.",
    } for ticker in clean_tickers]
    pd.DataFrame(plan_rows).to_csv(out / OUTPUT_NAMES[0], index=False)

    raw_rows = []
    normalized_parts = []
    attempted = succeeded = failed = False
    error_codes: list[str] = []
    if enabled and key_present and allow_low_confidence:
        attempted = True
        endpoint = str(config.get("source_url_or_provider", "")).strip()
        raw_dir = root / RAW_REL / run_ts.date().isoformat() / "auto" / SOURCE_ID
        raw_dir.mkdir(parents=True, exist_ok=True)
        for ticker in clean_tickers:
            fetch_ts = pd.Timestamp(datetime.now(timezone.utc))
            try:
                payload, decoded, status = fetcher(
                    endpoint, ticker, start_date.date().isoformat(),
                    end_date.date().isoformat(), api_key,
                )
                if api_key.encode("utf-8") in payload:
                    raise ValueError("PROVIDER_RESPONSE_CONTAINED_KEY_MATERIAL")
                payload_hash = sha256_bytes(payload)
                raw_path = raw_dir / f"{ticker}_{fetch_ts:%Y%m%d_%H%M%S_%f}_{payload_hash[:12]}.json"
                raw_path.write_bytes(payload)
                normalized = normalize_events(
                    decoded, ticker, fetch_ts, payload_hash,
                    str(config.get("source_name", SOURCE_ID)),
                    endpoint, universe, start_date, end_date,
                )
                normalized_parts.append(normalized)
                raw_rows.append({
                    "source_id": SOURCE_ID, "ticker": ticker,
                    "snapshot_path": raw_path.relative_to(root).as_posix(),
                    "retrieval_timestamp_utc": fetch_ts.isoformat(),
                    "raw_payload_hash": payload_hash,
                    "http_status": status, "response_bytes": len(payload),
                    "provider_rows_received": len(decoded),
                    "normalized_rows": len(normalized),
                    "fetch_succeeded": True, "error_code": "",
                    "request_metadata_redacted": True,
                    "research_only": True,
                })
                succeeded = True
            except Exception as exc:
                failed = True
                code = redact_error(exc)
                error_codes.append(code)
                raw_rows.append({
                    "source_id": SOURCE_ID, "ticker": ticker,
                    "snapshot_path": "", "retrieval_timestamp_utc": fetch_ts.isoformat(),
                    "raw_payload_hash": "", "http_status": "",
                    "response_bytes": 0, "provider_rows_received": 0,
                    "normalized_rows": 0, "fetch_succeeded": False,
                    "error_code": code, "request_metadata_redacted": True,
                    "research_only": True,
                })
    raw_manifest = pd.DataFrame(raw_rows, columns=[
        "source_id", "ticker", "snapshot_path", "retrieval_timestamp_utc",
        "raw_payload_hash", "http_status", "response_bytes",
        "provider_rows_received", "normalized_rows", "fetch_succeeded",
        "error_code", "request_metadata_redacted", "research_only",
    ])
    raw_manifest.to_csv(out / OUTPUT_NAMES[1], index=False)
    normalized = pd.concat(normalized_parts, ignore_index=True) if normalized_parts else pd.DataFrame(
        columns=NORMALIZED_COLUMNS
    )
    normalized = normalized.drop_duplicates(
        ["affected_ticker", "event_date", "earnings_session"], keep="last"
    )
    normalized.to_csv(out / OUTPUT_NAMES[2], index=False)
    generated_path = ""
    r6_reused = False
    if len(normalized):
        generated = write_generated_csv(root, normalized, run_ts)
        generated_path = generated.relative_to(root).as_posix()
        if reuse_r6:
            load_r6(root).run(root)
            r6_reused = True

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_preserved = sha256_file(root / D_REL) == d_hash_before
    official_changed = [p for p in changed if "official" in p.lower() or "broker" in p.lower()]
    certified_rows = int(normalized["pit_certified"].map(truth).sum())
    warnings = int((
        normalized["pit_certified"].map(truth)
        & pd.to_datetime(normalized["known_as_of_timestamp"], utc=True, errors="coerce").isna()
    ).sum())
    if not key_present:
        decision = "AUTO_EARNINGS_PROVIDER_KEY_MISSING"
    elif attempted and failed and not succeeded:
        decision = "AUTO_EARNINGS_PROVIDER_FETCH_FAILED"
    elif succeeded and certified_rows == 0:
        decision = "AUTO_EARNINGS_PROVIDER_FETCHED_NO_EVENTS"
    elif certified_rows > 0:
        decision = "AUTO_TICKER_EVENTS_IMPORTED_READY_FOR_FORWARD_OBSERVATION"
    else:
        decision = "AUTO_EARNINGS_PROVIDER_FETCH_FAILED"
    summary = {
        "FINAL_STATUS": "PASS" if not warnings and not changed and d_preserved else "FAIL",
        "DECISION": decision,
        "API_KEY_PRESENT": key_present,
        "API_KEY_FINGERPRINT": fingerprint,
        "EARNINGS_PROVIDER_ENABLED": enabled,
        "EARNINGS_PROVIDER_FETCH_ATTEMPTED": attempted,
        "EARNINGS_PROVIDER_FETCH_SUCCEEDED": succeeded,
        "EARNINGS_PROVIDER_FETCH_FAILED": failed,
        "AUTO_EARNINGS_EVENT_ROWS": len(normalized),
        "CERTIFIED_TICKER_EVENT_ROWS": certified_rows,
        "FORWARD_EVENT_OBSERVATION_ALLOWED": certified_rows > 0,
        "HISTORICAL_RANDOM_BACKTEST_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": warnings,
        "PROTECTED_OUTPUTS_MODIFIED": bool(changed or not d_preserved),
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True,
        "OFFICIAL_ADOPTION_ALLOWED": False,
        "GENERATED_IMPORT_PATH": generated_path,
        "R6_IMPORTER_REUSED": r6_reused,
        "API_KEY_ENV_VAR_USED": key_env_name if key_present else "",
        "FETCH_ERROR_CODES": sorted(set(error_codes)),
        "D_BASELINE_PRESERVED": d_preserved,
    }
    write_json(out / OUTPUT_NAMES[4], summary)
    (out / OUTPUT_NAMES[3]).write_text(markdown(
        "V21.095-R7 Auto Event Source Autofiller", summary
    ), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--earnings-provider", choices=["api"], default="api")
    parser.add_argument("--tickers", default="MU,WDC,STX,NVDA")
    parser.add_argument("--lookahead-days", type=int, default=120)
    parser.add_argument("--allow-low-confidence-earnings", action="store_true")
    parser.add_argument("--reuse-r6-importer", action="store_true")
    args = parser.parse_args()
    summary = run(
        args.root.resolve(), args.earnings_provider, args.tickers.split(","),
        max(1, args.lookahead_days), args.allow_low_confidence_earnings,
        args.reuse_r6_importer,
    )
    for key, value in summary.items():
        if key in {"GENERATED_IMPORT_PATH", "R6_IMPORTER_REUSED", "API_KEY_ENV_VAR_USED",
                   "FETCH_ERROR_CODES", "D_BASELINE_PRESERVED", "FINAL_STATUS", "DECISION"}:
            pass
        if isinstance(value, list):
            value = "|".join(value)
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
