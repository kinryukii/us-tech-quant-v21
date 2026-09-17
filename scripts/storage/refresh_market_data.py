"""Explicit, resumable daily Moomoo acquisition using the existing V21 fetcher.

Dry-run is the default and neither imports the SDK nor touches the network.
Each immutable interval keeps its acquisition vintage; promotion/merging belongs
to the existing data layer. This module never invokes the daily research chain.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.util
import io
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

FETCHER = "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"
PROFILE = "scripts/v22/v22_047_r1c_moomoo_opend_connection_profile.py"
FIELDS = ["ticker", "moomoo_symbol", "market", "date", "open", "high", "low",
          "close", "volume", "turnover", "adjustment", "source", "source_policy",
          "snapshot_id", "fetched_at_utc"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_universe(tickers: list[str] | None, universe_csv: Path | None) -> list[dict]:
    if universe_csv:
        with universe_csv.open(encoding="utf-8-sig", newline="") as handle:
            source = list(csv.DictReader(handle))
    else:
        source = [{"ticker": token} for entry in tickers or [] for token in entry.split(",") if token]
    result = {}
    for row in source:
        ticker = str(row.get("ticker", "")).strip().upper()
        code = str(row.get("moomoo_code") or row.get("moomoo_symbol") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,31}", ticker):
            raise ValueError(f"INVALID_TICKER:{ticker}")
        if not code:
            if not re.fullmatch(r"[A-Z0-9]+", ticker):
                raise ValueError(f"EXPLICIT_PROVIDER_MAPPING_REQUIRED:{ticker}")
            code = "US." + ticker
        if not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._-]{0,39}", code):
            raise ValueError(f"INVALID_US_MOOMOO_CODE:{code}")
        item = {"ticker": ticker, "moomoo_symbol": code, "security_id": row.get("security_id", "")}
        if ticker in result and result[ticker] != item:
            raise ValueError(f"CONFLICTING_TICKER_MAPPING:{ticker}")
        result[ticker] = item
    codes = [item["moomoo_symbol"] for item in result.values()]
    if not result or len(codes) != len(set(codes)):
        raise ValueError("EMPTY_UNIVERSE_OR_AMBIGUOUS_PROVIDER_MAPPING")
    return sorted(result.values(), key=lambda item: item["ticker"])


def make_plan(universe: list[dict], start: str, end: str, adjustments: list[str]) -> list[dict]:
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("START_AFTER_END")
    if date.fromisoformat(end) > date.today():
        raise ValueError("FUTURE_END_DATE")
    return [{**item, "market": "US", "frequency": "1d", "adjustment": adjustment,
             "planned_start_date": start, "planned_end_date": end}
            for item in universe for adjustment in sorted(set(adjustments))]


def interval_key(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:24]


def validate_records(records: list[dict], item: dict) -> dict:
    seen = set()
    for row in records:
        day = str(row.get("date", ""))
        date.fromisoformat(day)
        if not item["planned_start_date"] <= day <= item["planned_end_date"]:
            raise ValueError("OUT_OF_REQUESTED_DATE_RANGE")
        if day in seen:
            raise ValueError("DUPLICATE_DAILY_KEY")
        seen.add(day)
        for key in ("ticker", "moomoo_symbol", "adjustment"):
            if row.get(key) != item[key]:
                raise ValueError("IDENTITY_OR_ADJUSTMENT_MISMATCH")
        if row.get("source") != "MOOMOO_OPEND" or row.get("source_policy") != "MOOMOO_ONLY":
            raise ValueError("SOURCE_POLICY_MISMATCH")
        prices = [float(row[key]) for key in ("open", "high", "low", "close")]
        volume = float(row["volume"])
        if not all(math.isfinite(value) and value > 0 for value in prices):
            raise ValueError("INVALID_OHLC")
        opening, high, low, close = prices
        if high < max(opening, close, low) or low > min(opening, close, high):
            raise ValueError("INVALID_OHLC_ORDER")
        if not math.isfinite(volume) or volume < 0:
            raise ValueError("INVALID_VOLUME")
    if not seen:
        raise ValueError("EMPTY_RESPONSE")
    return {"row_count": len(seen), "first_date": min(seen), "latest_date": max(seen),
            "coverage_claim": "RETURNED_VALID_BARS_ONLY_NOT_EXCHANGE_SESSION_COMPLETENESS"}


def read_checkpoint(root: Path, item: dict) -> dict | None:
    key = interval_key(item)
    manifest = root / "intervals" / f"{key}.json"
    if not manifest.exists():
        return None
    value = json.loads(manifest.read_text(encoding="utf-8"))
    target = root / "intervals" / f"{key}.csv"
    if value.get("item") != item:
        raise ValueError(f"CHECKPOINT_IDENTITY_FAILED:{key}")
    if not target.is_file() and value.get("status") == "PREPARED_INTERVAL":
        return None
    if not target.is_file() or digest(target) != value.get("sha256"):
        raise ValueError(f"CHECKPOINT_IDENTITY_FAILED:{key}")
    with target.open(encoding="utf-8", newline="") as handle:
        stats = validate_records(list(csv.DictReader(handle)), item)
    if stats["row_count"] != value.get("row_count"):
        raise ValueError(f"CHECKPOINT_ROW_COUNT_FAILED:{key}")
    return {**value, "status": "REUSED_VERIFIED_INTERVAL"}


def save_interval(root: Path, item: dict, records: list[dict], source_hash: str) -> dict:
    stats = validate_records(records, item)
    key = interval_key(item)
    target = root / "intervals" / f"{key}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"IMMUTABLE_INTERVAL_ALREADY_EXISTS:{target}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(sorted(records, key=lambda row: row["date"]))
    payload = buffer.getvalue().encode("utf-8")
    result = {"item": item, "status": "PREPARED_INTERVAL", "path": str(target),
              "sha256": hashlib.sha256(payload).hexdigest(), "source_implementation_sha256": source_hash, **stats}
    # A prepared receipt makes a crash between data publication and checkpoint
    # completion resumable. Unpublished temporary bytes are safe to regenerate.
    write_json(target.with_suffix(".json"), result)
    temporary = target.with_suffix(".csv.tmp")
    temporary.write_bytes(payload)
    os.rename(temporary, target)
    result["status"] = "FETCHED_VALIDATED_INTERVAL"
    write_json(target.with_suffix(".json"), result)
    return result


class QuoteHistoryOnly:
    """Expose only the single method used by the canonical acquisition helper."""
    def __init__(self, context):
        self.context = context

    def request_history_kline(self, code, **kwargs):
        response = self.context.request_history_kline(code, **kwargs)
        if isinstance(response, tuple) and len(response) > 1 and response[0] == 0:
            frame = response[1]
            if hasattr(frame, "columns") and "code" in frame.columns:
                if not set(frame["code"].dropna().astype(str)).issubset({code}):
                    raise ValueError("PROVIDER_RESPONSE_CODE_MISMATCH")
        return response


def run(args) -> dict:
    root = args.work_root.resolve()
    repo = args.repo_root.resolve()
    if root == repo or root.is_relative_to(repo):
        raise ValueError("ACQUISITION_OUTPUT_MUST_BE_EXTERNAL_TO_CODE_REPOSITORY")
    universe = load_universe(args.tickers, args.universe_csv)
    plan = make_plan(universe, args.start, args.end, args.adjustments)
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:20]
    report = root / "runs" / f"{plan_hash}.json"
    summary = {"schema_version": 1, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
               "mode": "EXECUTE" if args.execute else "DRY_RUN", "status": "PLANNED",
               "plan": plan, "results": [], "source_policy": "MOOMOO_ONLY",
               "trade_context_opened": False, "canonical_pointer_modified": False,
               "history_request_count": 0, "new_unique_security_touch_count": 0}
    pending = []
    for item in plan:
        cached = read_checkpoint(root, item)
        if cached:
            summary["results"].append(cached)
        else:
            pending.append(item)
    summary["pending_leg_count"] = len(pending)
    write_json(report, summary)
    if not args.execute or not pending:
        summary["status"] = "DRY_RUN_READY" if not args.execute else "ALL_INTERVALS_REUSED"
        write_json(report, summary)
        return summary
    context = None
    limiter = None
    try:
        profile_module = load_module(repo / PROFILE, "data_refresh_connection_profile")
        environ = dict(os.environ)
        if args.host:
            environ["MOOMOO_OPEND_HOST"] = args.host
        if args.port:
            environ["MOOMOO_OPEND_PORT"] = str(args.port)
        profile = profile_module.load_profile(repo / "config/moomoo_opend_connection.json", environ)
        summary["endpoint"] = {"host": profile.host, "port": profile.port}
        connected, reason = profile_module.tcp_probe(profile)
        if not connected:
            raise ConnectionError(reason)
        # SDK logging is initialized during import; route only this subprocess.
        sdk_appdata = root / "sdk_appdata"
        sdk_appdata.mkdir(parents=True, exist_ok=True)
        os.environ["APPDATA"] = str(sdk_appdata)
        sdk = importlib.import_module("moomoo")
        sdk.SysConfig.set_all_thread_daemon(True)
        context = sdk.OpenQuoteContext(host=profile.host, port=profile.port, is_async_connect=True)
        context.set_sync_query_connect_timeout(10)
        quota_result, quota = context.get_history_kl_quota(get_detail=True)
        if quota_result != sdk.RET_OK:
            raise RuntimeError("QUOTA_QUERY_FAILED:" + str(quota))
        used, remaining, details = quota
        if not isinstance(details, list):
            raise ValueError("INVALID_QUOTA_DETAILS")
        known = {str(row.get("code", "")) for row in details}
        remaining = int(remaining)
        summary["quota_before"] = {"used": int(used), "remaining": remaining,
                                   "known_codes": sorted(known)}
        fetcher = load_module(repo / FETCHER, "data_refresh_v21_fetcher")
        source_hash = digest(repo / FETCHER)
        limiter = fetcher.HistoryKlineLimiter()
        errors, recovered = [], []
        for item in pending:
            code = item["moomoo_symbol"]
            result = {"item": item, "status": "BLOCKED_QUOTA"}
            if code in known or remaining > 0:
                if code not in known:
                    known.add(code)
                    remaining -= 1  # conservative accounting even if a request fails
                    summary["new_unique_security_touch_count"] += 1
                records, error_type, error_message, retries = fetcher.guarded_moomoo_fetch(
                    item, sdk, QuoteHistoryOnly(context), args.max_retries,
                    "market_interval_" + interval_key(item), limiter, errors, recovered)
                if records:
                    try:
                        result = save_interval(root, item, records, source_hash)
                    except (ValueError, OSError) as exc:
                        result.update(status="FAILED_VALIDATION_OR_WRITE", error=str(exc))
                else:
                    result.update(status="FAILED_FETCH", error_type=error_type,
                                  error=error_message, retries=retries)
            summary["results"].append(result)
            summary["history_request_count"] = len(limiter.audit_rows)
            summary["request_audit"] = limiter.audit_rows
            summary["errors"], summary["recovered_errors"] = errors, recovered
            write_json(report, summary)
            print(json.dumps({"ticker": item["ticker"], "adjustment": item["adjustment"],
                              "status": result["status"]}), flush=True)
        successful = {"REUSED_VERIFIED_INTERVAL", "FETCHED_VALIDATED_INTERVAL"}
        summary["status"] = "ACQUIRED" if all(row["status"] in successful for row in summary["results"]) else "PARTIAL"
    except Exception as exc:
        summary.update(status="BLOCKED", error_type=type(exc).__name__, error=str(exc))
        done = {interval_key(row["item"]) for row in summary["results"]}
        summary["results"].extend({"item": item, "status": "BLOCKED_CONNECTION_OR_SETUP"}
                                  for item in pending if interval_key(item) not in done)
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as exc:
                summary["quote_context_close_error"] = str(exc)
        if limiter is not None:
            summary["history_request_count"] = len(limiter.audit_rows)
        write_json(report, summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--work-root", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tickers", nargs="+")
    source.add_argument("--universe-csv", type=Path)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--adjustments", nargs="+", choices=("raw", "qfq"), default=["raw", "qfq"])
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--max-retries", type=int, choices=(0, 1), default=1)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    summary = run(args)
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in {"plan", "results", "request_audit", "quota_before"}}, indent=2))
    return 0 if summary["status"] in {"DRY_RUN_READY", "ALL_INTERVALS_REUSED", "ACQUIRED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
