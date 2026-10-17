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
import time
from datetime import date, datetime, timezone
from pathlib import Path

FETCHER = "scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py"
PROFILE = "scripts/v22/v22_047_r1c_moomoo_opend_connection_profile.py"
CURRENT_KLINE_NUM = 130
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



def _current_subscription_snapshot(context, sdk):
    returned, value = context.query_subscription(is_all_conn=True)
    if returned != sdk.RET_OK or not isinstance(value, dict):
        raise RuntimeError("SUBSCRIPTION_QUERY_REJECTED:" + str(value))
    if any(type(value.get(key)) is not int or value[key] < 0
           for key in ("total_used", "own_used", "remain")):
        raise ValueError("INVALID_SUBSCRIPTION_QUOTA_RESPONSE")
    return value


def _run_current_kline(summary, pending, root, repo, context, sdk):
    """Official subscribed RAW/RTH daily API; no history request or fallback."""
    fetcher = load_module(repo / FETCHER, "current_kline_original_normalizer")
    source_hash = digest(repo / FETCHER)
    limiter = fetcher.HistoryKlineLimiter(max_calls=40, window_seconds=30.0, min_interval=0.75)
    owned = []
    summary.update(current_kline_calls=0, subscribe_calls=0, unsubscribe_calls=0,
                   owned_subscriptions=[], subscription_api_audit=[], response_isolation=[],
                   other_quote_api_calls=0, current_kline_num=CURRENT_KLINE_NUM)
    report = root / "runs" / (hashlib.sha256(json.dumps(summary["plan"], sort_keys=True).encode()).hexdigest()[:20] + ".json")
    before = _current_subscription_snapshot(context, sdk)
    summary["subscription_before"] = {key: before[key] for key in ("total_used", "own_used", "remain")}
    if before["own_used"] != 0:
        raise ValueError("FRESH_CONNECTION_ALREADY_OWNS_SUBSCRIPTIONS")
    try:
        for item in pending:
            code = item["moomoo_symbol"]
            result = {"item": item, "status": "FAILED_CURRENT_KLINE"}
            try:
                quota = _current_subscription_snapshot(context, sdk)
                if quota["remain"] < 1:
                    raise RuntimeError("SUBSCRIPTION_QUOTA_INSUFFICIENT")
                limiter.acquire(item)
                returned, message = context.subscribe([code], [sdk.SubType.K_DAY],
                    is_first_push=False, subscribe_push=False, extended_time=False, session=sdk.Session.RTH)
                summary["subscribe_calls"] += 1
                audit = {"code": code, "api": "subscribe", "retcode": int(returned),
                         "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                         "subscription_type": "K_DAY", "session": "RTH", "subscribe_push": False,
                         "preexisting_global_kday": code in quota.get("sub_list", {}).get("K_DAY", [])}
                summary["subscription_api_audit"].append(audit)
                if returned != sdk.RET_OK:
                    audit["error"] = str(message)
                    raise RuntimeError("SUBSCRIBE_REJECTED:" + str(message))
                owned.append((code, time.monotonic()))
                summary["owned_subscriptions"].append(code)
                limiter.acquire(item)
                returned, frame = context.get_cur_kline(code, CURRENT_KLINE_NUM,
                    ktype=sdk.KLType.K_DAY, autype=sdk.AuType.NONE)
                observed = datetime.now(timezone.utc).isoformat()
                summary["current_kline_calls"] += 1
                audit = {"code": code, "api": "get_cur_kline", "retcode": int(returned),
                         "observed_at_utc": observed, "num": CURRENT_KLINE_NUM,
                         "ktype": "K_DAY", "autype": "NONE", "session": "RTH"}
                summary["subscription_api_audit"].append(audit)
                if returned != sdk.RET_OK:
                    audit["error"] = str(frame)
                    raise RuntimeError("GET_CUR_KLINE_REJECTED:" + str(frame))
                if (not hasattr(frame, "columns") or not hasattr(frame, "to_parquet")
                        or not {"code", "time_key", "open", "high", "low", "close", "volume", "turnover"} <= set(frame.columns)):
                    raise ValueError("CURRENT_KLINE_RESPONSE_SCHEMA")
                if len(frame) > CURRENT_KLINE_NUM or frame.empty:
                    raise ValueError("CURRENT_KLINE_EMPTY_OR_OVER_REQUEST_LIMIT")
                if not frame.code.eq(code).all():
                    raise ValueError("CURRENT_KLINE_RESPONSE_CODE_MISMATCH")
                days = frame.time_key.astype(str).str[:10]
                for value in days:
                    date.fromisoformat(value)
                if any(value > date.today().isoformat() for value in days):
                    raise ValueError("CURRENT_KLINE_FUTURE_DATE")
                if days.duplicated().any():
                    raise ValueError("CURRENT_KLINE_DUPLICATE_DATE")
                # Capture actual SDK dataframe values before selecting completed
                # rows. This quarantine is not a raw wire/protobuf byte claim.
                raw_path = root / "sdk_responses" / (interval_key(item) + ".parquet")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                if raw_path.exists():
                    raise FileExistsError("IMMUTABLE_SDK_RESPONSE_ALREADY_EXISTS")
                frame.to_parquet(raw_path, index=False)
                allowed = days.between(item["planned_start_date"], item["planned_end_date"])
                isolation = {"code": code, "returned_rows": len(frame), "accepted_rows": int(allowed.sum()),
                    "post_target_rows": int((days > item["planned_end_date"]).sum()),
                    "pre_start_rows": int((days < item["planned_start_date"]).sum()),
                    "post_target_dates": sorted(set(days[days > item["planned_end_date"]])),
                    "prices_outside_target_not_published": True}
                summary["response_isolation"].append(isolation)
                completed = frame.loc[allowed].copy()
                records = fetcher.normalize_records(completed, item["ticker"], code, "US", "raw",
                    "current_kline_" + interval_key(item), observed)
                result = save_interval(root, item, records, source_hash)
                result["current_kline_provenance"] = {**audit,
                    "sdk_response": {"path": str(raw_path), "sha256": digest(raw_path)},
                    "sdk_response_semantics": "RETURNED_DATAFRAME_PARQUET_NOT_WIRE_RESPONSE",
                    "isolation": isolation, "owned_subscription": True,
                    "collector_implementation_sha256": digest(Path(__file__)),
                    "availability": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT"}
                write_json(Path(result["path"]).with_suffix(".json"), result)
            except Exception as exc:
                result.update(status="FAILED_CURRENT_KLINE", error_type=type(exc).__name__, error=str(exc))
            summary["results"].append(result)
            write_json(report, summary)
            print(json.dumps({"ticker": item["ticker"], "status": result["status"]}), flush=True)
            if result.get("error") and any(token in result["error"].lower()
                    for token in ("quota", "permission", "entitlement", "rate limit", "频率", "额度", "权限")):
                break
    finally:
        for code, started in owned:
            delay = max(0.0, 60.0 - (time.monotonic() - started))
            if delay:
                time.sleep(delay)
            summary["unsubscribe_calls"] += 1
            try:
                returned, message = context.unsubscribe([code], [sdk.SubType.K_DAY], unsubscribe_all=False)
                audit = {"api": "unsubscribe", "code": code, "retcode": int(returned),
                         "only_owned": True, "error": None if returned == sdk.RET_OK else str(message)}
            except Exception as exc:
                audit = {"api": "unsubscribe", "code": code, "only_owned": True,
                         "error": type(exc).__name__ + ":" + str(exc)}
            summary["subscription_api_audit"].append(audit)
            write_json(report, summary)
        after = _current_subscription_snapshot(context, sdk)
        summary["subscription_after"] = {key: after[key] for key in ("total_used", "own_used", "remain")}
        summary["owned_subscriptions_released"] = after["own_used"] == 0
    successful = {"FETCHED_VALIDATED_INTERVAL", "REUSED_VERIFIED_INTERVAL"}
    done = {interval_key(row["item"]) for row in summary["results"]}
    summary["results"].extend({"item": item, "status": "BLOCKED_AFTER_PROVIDER_PERMISSION_QUOTA_OR_RATE_LIMIT"}
        for item in pending if interval_key(item) not in done)
    summary["status"] = ("ACQUIRED" if summary["owned_subscriptions_released"]
        and all(row["status"] in successful for row in summary["results"]) else "PARTIAL")
    summary["request_audit"] = limiter.audit_rows
    return summary

def run(args) -> dict:
    root = args.work_root.resolve()
    repo = args.repo_root.resolve()
    if root == repo or root.is_relative_to(repo):
        raise ValueError("ACQUISITION_OUTPUT_MUST_BE_EXTERNAL_TO_CODE_REPOSITORY")
    universe = load_universe(args.tickers, args.universe_csv)
    plan = make_plan(universe, args.start, args.end, args.adjustments)
    acquisition_mode = getattr(args, "acquisition_mode", "history")
    if acquisition_mode not in {"history", "current-kline"}:
        raise ValueError("UNKNOWN_ACQUISITION_MODE")
    if acquisition_mode == "current-kline":
        if args.adjustments != ["raw"] or args.max_retries != 0:
            raise ValueError("CURRENT_KLINE_REQUIRES_RAW_AND_ZERO_RETRIES")
        if any(not re.fullmatch(r"[A-Z0-9]{9}", row["security_id"]) for row in universe):
            raise ValueError("CURRENT_KLINE_EXPLICIT_SECURITY_ID_REQUIRED")
        plan = [{**item, "acquisition_method": "GET_CUR_KLINE", "num": CURRENT_KLINE_NUM,
                 "session": "RTH", "subscribe_push": False} for item in plan]
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:20]
    report = root / "runs" / f"{plan_hash}.json"
    summary = {"schema_version": 1, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
               "mode": "EXECUTE" if args.execute else "DRY_RUN", "status": "PLANNED",
               "plan": plan, "results": [], "source_policy": "MOOMOO_ONLY",
               "trade_context_opened": False, "canonical_pointer_modified": False,
               "history_request_count": 0, "new_unique_security_touch_count": 0}
    known_only = getattr(args, "known_only", False)
    if type(known_only) is not bool:
        raise ValueError("KNOWN_ONLY_REQUIRES_BOOLEAN")
    summary["known_history_securities_only"] = known_only
    summary["acquisition_mode"] = acquisition_mode
    pending = []
    for item in plan:
        cached = read_checkpoint(root, item)
        if cached:
            if acquisition_mode == "current-kline":
                ref = cached.get("current_kline_provenance", {}).get("sdk_response", {})
                response_path = Path(ref.get("path", "")).resolve()
                if (not response_path.is_relative_to(root / "sdk_responses")
                        or not response_path.is_file() or digest(response_path) != ref.get("sha256")):
                    raise ValueError("CURRENT_KLINE_SDK_RESPONSE_CHECKPOINT_CHANGED")
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
        if acquisition_mode == "current-kline":
            return _run_current_kline(summary, pending, root, repo, context, sdk)
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
            result = {"item": item, "status": "BLOCKED_KNOWN_SECURITY_ONLY" if known_only else "BLOCKED_QUOTA"}
            if code in known or (not known_only and remaining > 0):
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
    parser.add_argument("--acquisition-mode", choices=("history", "current-kline"), default="history",
                        help="Current-kline uses official subscribed RAW/RTH daily data, fixed num130 and zero retries.")
    parser.add_argument("--known-only", action="store_true",
                        help="Fetch only current history-quota known codes; never spend an additional unique-security slot.")
    args = parser.parse_args(argv)
    summary = run(args)
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in {"plan", "results", "request_audit", "quota_before"}}, indent=2))
    return 0 if summary["status"] in {"DRY_RUN_READY", "ALL_INTERVALS_REUSED", "ACQUIRED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
