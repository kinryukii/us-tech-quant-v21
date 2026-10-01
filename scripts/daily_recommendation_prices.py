"""Frozen A2 raw-plus-forward-rehabilitation price input adapter.

Fresh provider rehabilitation responses are separate immutable receipts. The
historical index anchor is preserved; QFQ/Yahoo values never stand in for it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ADAPTER_PATH = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/scripts/run_rebuild.py")
ADAPTER_SHA = "68f4eb6599638db4c6af51b0ff8894f757b78a60dba27ce03e5c798e9508cc0e"
COVERAGE_PATH = Path("D:/us-tech-quant-backtests/research/a2/demo_2026_calendar_replay/input_coverage.json")
COVERAGE_SHA = "4c979486b983108d41631f93244cbb2d991d730e6c707c23b7986a24f9d034f3"
PRICE_FIELDS = ["open", "high", "low", "close", "volume"]
RAW_COLUMNS = ["code", "time_key", *PRICE_FIELDS]
SUCCESS = {"FETCHED_VALIDATED_INTERVAL", "REUSED_VERIFIED_INTERVAL"}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verify(path, expected):
    path = Path(path)
    if not path.is_file() or not expected or digest(path) != expected:
        raise ValueError(f"PRICE_SOURCE_HASH_MISMATCH:{path.name}")
    return path


def _write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def refresh_rehab(paths, members, work_root, target, progress=None):
    """Query current corporate-action factors only; no price/history/trade API.

    Every response, including zero-event responses, is explicitly dated and
    attributed to its code. An old receipt is never silently refreshed.
    """
    from scripts.storage.refresh_market_data import load_module, PROFILE
    work = Path(work_root)
    work.mkdir(parents=True, exist_ok=True)
    receipt_path = work / "rehab_receipt.json"
    if receipt_path.exists():
        raise ValueError("REHAB_RUN_ALREADY_EXISTS_USE_NEW_RUN_DIRECTORY")
    receipt = {"status": "RUNNING", "source": "MOOMOO_OPEND_GET_REHAB", "target_date": target,
               "results": [], "history_requests": 0, "trade_requests": 0}
    context = None
    try:
        profile_module = load_module(paths.repo_root / PROFILE, "today_rehab_profile")
        profile = profile_module.load_profile(paths.repo_root / "config/moomoo_opend_connection.json", dict(os.environ))
        connected, reason = profile_module.tcp_probe(profile)
        if not connected:
            raise ConnectionError(reason)
        appdata = work / "sdk_appdata"
        appdata.mkdir(exist_ok=True)
        os.environ["APPDATA"] = str(appdata)
        sdk = importlib.import_module("moomoo")
        sdk.SysConfig.set_all_thread_daemon(True)
        context = sdk.OpenQuoteContext(host=profile.host, port=profile.port, is_async_connect=True)
        context.set_sync_query_connect_timeout(10)
        codes = sorted({row.get("moomoo_symbol", row.get("moomoo_transport_code")) for row in members})
        for index, code in enumerate(codes, 1):
            if not code:
                raise ValueError("REHAB_CODE_MISSING")
            row = {"code": code, "status": "FAILED"}
            try:
                returned, frame = context.get_rehab(code)
                if returned != sdk.RET_OK:
                    raise RuntimeError(str(frame))
                if not isinstance(frame, pd.DataFrame):
                    raise ValueError("REHAB_RESPONSE_SCHEMA")
                frame = frame.copy()
                if "code" in frame and not frame.code.eq(code).all():
                    raise ValueError("REHAB_RESPONSE_CODE_MISMATCH")
                frame["code"] = code
                if frame.empty:
                    for column in ("ex_div_date", "forward_adj_factorA", "forward_adj_factorB"):
                        if column not in frame:
                            frame[column] = pd.Series(dtype="object")
                elif not {"ex_div_date", "forward_adj_factorA", "forward_adj_factorB"} <= set(frame):
                    raise ValueError("REHAB_FACTORS_MISSING")
                path = work / (hashlib.sha256(code.encode()).hexdigest()[:24] + ".parquet")
                frame.to_parquet(path, index=False)
                row.update(status="PASS", path=str(path), sha256=digest(path), row_count=len(frame),
                           fetched_at=datetime.now(timezone.utc).isoformat())
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}:{exc}"
            receipt["results"].append(row)
            _write(receipt_path, receipt)
            if progress:
                progress(f"复权资料 {index}/{len(codes)}：{code} {row['status']}")
            if index < len(codes):
                time.sleep(0.6)
        receipt["status"] = "READY" if all(row["status"] == "PASS" for row in receipt["results"]) else "PARTIAL"
    except Exception as exc:
        receipt.update(status="BLOCKED", error=f"{type(exc).__name__}:{exc}")
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as exc:
                receipt["quote_context_close_error"] = str(exc)
        receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path), "receipt_sha256": digest(receipt_path)}


def _adapter(target):
    verify(ADAPTER_PATH, ADAPTER_SHA)
    spec = importlib.util.spec_from_file_location("today_a2_original_price_index", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.END_EXCLUSIVE = pd.Timestamp(target) + pd.Timedelta(days=1)
    return module


def _raw_frame(frame, code):
    result = frame.copy()
    if "code" in result:
        if not result.code.astype(str).eq(code).all():
            raise ValueError("RAW_PROVIDER_CODE_MISMATCH")
    for column in ("moomoo_symbol", "provider_code"):
        if column in result and not result[column].astype(str).eq(code).all():
            raise ValueError("RAW_PROVIDER_CODE_MISMATCH")
    if "source" in result and not result.source.isin(["MOOMOO_OPEND", "MOOMOO"]).all():
        raise ValueError("RAW_SOURCE_NOT_MOOMOO")
    if "adjustment" in result and not result.adjustment.astype(str).str.lower().eq("raw").all():
        raise ValueError("RAW_SOURCE_PRICE_BASIS_MISMATCH")
    day = next((column for column in ("trade_date", "date", "time_key") if column in result), None)
    if day is None or not set(PRICE_FIELDS) <= set(result):
        raise ValueError("RAW_COLUMNS_MISSING")
    result["trade_date"] = pd.to_datetime(result[day]).dt.normalize()
    values = result[PRICE_FIELDS].to_numpy(float)
    if result.trade_date.isna().any() or not np.isfinite(values).all() or (result[PRICE_FIELDS[:-1]] <= 0).any().any() or (result.volume < 0).any():
        raise ValueError("RAW_PRICE_VALUES_INVALID")
    return result[["trade_date", *PRICE_FIELDS]]


def _qualified_yahoo_tail(receipt, original, ticker, target):
    """Qualify only an unchanged-unit tail using actual raw response evidence."""
    if receipt.get("status") != "SUCCESS" or receipt.get("rejected_row_count") != 0:
        raise ValueError("YAHOO_ACQUISITION_NOT_COMPLETE")
    contract = receipt["contract"]
    lineage = receipt["catalog_record"]["lineage"]
    if (contract.get("provider") != "YAHOO_CHART" or contract.get("ticker") != ticker
            or lineage.get("price_basis") != "SPLIT_ADJUSTED" or lineage.get("currency") != "USD"
            or lineage.get("exchange_timezone") != "America/New_York"
            or receipt.get("max_date") != target):
        raise ValueError("YAHOO_SOURCE_IDENTITY_OR_END_DATE_INVALID")
    observed = datetime.fromisoformat(receipt["observed_at"].replace("Z", "+00:00"))
    target_close = datetime.combine(pd.Timestamp(target).date(), datetime.min.time(), ZoneInfo("America/New_York")) + timedelta(hours=16)
    if observed.tzinfo is None or observed < target_close:
        raise ValueError("YAHOO_RESPONSE_PREDATES_TARGET_CLOSE")
    observed_date = observed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if contract["end"] < target or observed_date > contract.get("events_through", contract["end"]):
        raise ValueError("YAHOO_SPLIT_EVENT_REQUEST_DOES_NOT_COVER_RETRIEVAL_DATE")
    parsed_url = urlparse(receipt["source_url"])
    query = parse_qs(parsed_url.query)
    if (parsed_url.scheme != "https" or parsed_url.hostname not in {"query1.finance.yahoo.com", "query2.finance.yahoo.com"}
            or parsed_url.username or parsed_url.password
            or set(query) - {"period1", "period2", "interval", "events", "includeAdjustedClose", "includePrePost"}):
        raise ValueError("YAHOO_PUBLIC_SOURCE_URL_REQUIRED")
    try:
        requested_until = int(query["period2"][0])
    except (KeyError, ValueError, IndexError):
        raise ValueError("YAHOO_EVENT_REQUEST_PERIOD2_UNVERIFIED")
    if requested_until < observed.timestamp():
        raise ValueError("YAHOO_EVENT_REQUEST_PERIOD2_PRECEDES_RETRIEVAL")
    if "splits" not in query.get("events", [""])[0].split(","):
        raise ValueError("YAHOO_SPLIT_EVENTS_NOT_EXPLICITLY_REQUESTED")
    files = {row["role"]: row for row in receipt["files"]}
    raw_ref, normalized_ref = files["RAW_HTTP_RESPONSE"], files["NORMALIZED_DAILY"]
    response = json.loads(verify(raw_ref["path"], raw_ref["sha256"]).read_text(encoding="utf-8"))
    chart = response.get("chart", {})
    result = chart.get("result")
    if chart.get("error") or not isinstance(result, list) or len(result) != 1:
        raise ValueError("YAHOO_RAW_RESPONSE_INVALID")
    result = result[0]
    if result.get("meta", {}).get("symbol") != contract["symbol"]:
        raise ValueError("YAHOO_RAW_SYMBOL_MISMATCH")
    frame = pd.read_parquet(verify(normalized_ref["path"], normalized_ref["sha256"]))
    if (not frame.ticker.eq(ticker).all() or not frame.source.eq("YAHOO_CHART").all()
            or not frame.adjustment.eq("split_adjusted").all()
            or not frame.provider_code.eq(contract["symbol"]).all()):
        raise ValueError("YAHOO_NORMALIZED_SYMBOL_MISMATCH")
    frame["trade_date"] = pd.to_datetime(frame.date).dt.normalize()
    if frame.trade_date.duplicated().any():
        raise ValueError("YAHOO_DUPLICATE_SESSIONS")
    values = frame[PRICE_FIELDS].to_numpy(float)
    if not np.isfinite(values).all() or (frame[PRICE_FIELDS[:-1]] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError("YAHOO_INVALID_OHLCV")
    overlap = original.merge(frame[["trade_date", *PRICE_FIELDS]], on="trade_date", suffixes=("_raw", "_yahoo"))
    overlap = overlap.sort_values("trade_date").tail(5)
    if len(overlap) < 5:
        raise ValueError("YAHOO_RAW_OVERLAP_FEWER_THAN_FIVE_SESSIONS")
    if contract["start"] > overlap.trade_date.min().date().isoformat():
        raise ValueError("YAHOO_SPLIT_EVENT_REQUEST_START_TOO_LATE")
    for event in result.get("events", {}).get("splits", {}).values():
        event_date = datetime.fromtimestamp(event["date"], ZoneInfo("America/New_York")).date().isoformat()
        if overlap.trade_date.min().date().isoformat() <= event_date <= observed_date:
            raise ValueError("YAHOO_SPLIT_IN_OVERLAP_OR_GAP")
    for column in PRICE_FIELDS:
        if not np.allclose(overlap[f"{column}_raw"], overlap[f"{column}_yahoo"], rtol=0, atol=1e-6):
            raise ValueError(f"YAHOO_RAW_OVERLAP_MISMATCH:{column}")
    tail = frame.loc[frame.trade_date.gt(original.trade_date.max()) & frame.trade_date.le(pd.Timestamp(target)),
                     ["trade_date", *PRICE_FIELDS]].copy()
    if tail.empty or tail.trade_date.max() != pd.Timestamp(target):
        raise ValueError("YAHOO_TAIL_NOT_CURRENT")
    return tail, {"provider": "YAHOO_CHART", "qualification": "NO_SPLITS_IN_GAP_WITH_RAW_OVERLAP",
        "raw_response_sha256": raw_ref["sha256"], "normalized_sha256": normalized_ref["sha256"],
        "observed_at": receipt["observed_at"], "overlap_sessions": 5, "absolute_tolerance": 1e-6,
        "first_added_date": tail.trade_date.min().date().isoformat(), "last_added_date": target,
        "input_field": "split_adjusted_OHLC_WITH_NO_SPLITS_NOT_adjusted_close",
        "acquisition_receipt": {"status": receipt["status"], "rejected_row_count": 0,
            "max_date": receipt["max_date"], "observed_at": receipt["observed_at"],
            "source_url": receipt["source_url"],
            "contract": {key: contract[key] for key in ("provider", "ticker", "symbol", "start", "end", "events_through") if key in contract},
            "catalog_record": {"lineage": {key: lineage[key] for key in ("price_basis", "currency", "exchange_timezone")}},
            "files": [{key: ref[key] for key in ("role", "path", "sha256")}
                      for ref in (raw_ref, normalized_ref)]}}


def _massive_raw_window(record, ticker, first, target, store, raw_cache=None):
    """Validate source identity, immutable raw leaves and normalized OHLCV.

    This shared reader grants no overlap or consumer qualification. The model
    caller below still requires all five OHLCV fields to match its raw anchor.
    """
    from scripts.storage.refresh_massive_market import ENDPOINT, validate_response
    raw_cache = {} if raw_cache is None else raw_cache
    lineage = record.get("lineage") or json.loads(record.get("lineage_json") or "{}")
    mapping = lineage.get("provider_mapping", {})
    symbol = mapping.get("provider_symbol")
    if (record.get("dataset") != "prices_daily_massive" or record.get("source") != "MASSIVE_GROUPED"
            or record.get("ticker") != ticker or record.get("adjustment") != "raw"
            or record.get("format") != "parquet" or lineage.get("provider") != "MASSIVE_GROUPED"
            or lineage.get("price_basis") != "RAW" or lineage.get("currency") != "USD"
            or lineage.get("exchange_timezone") != "America/New_York"
            or not symbol or lineage.get("provider_symbol") != symbol):
        raise ValueError("MASSIVE_SOURCE_IDENTITY_INVALID")
    if symbol != ticker and not str(mapping.get("evidence_url", "")).startswith("https://"):
        raise ValueError("MASSIVE_ALIAS_WITHOUT_EXPLICIT_EVIDENCE")
    if record.get("max_date", "") < target:
        raise ValueError("MASSIVE_TARGET_SESSION_UNAVAILABLE")
    path = verify(record["path"], record.get("source_sha256"))
    frame = pq.read_table(path, filters=[("date", ">=", first), ("date", "<=", target)]).to_pandas()
    required = {"ticker", "date", "source", "adjustment", "provider_code", "source_id", "observed_at",
                "source_timestamp_ms", "currency", *PRICE_FIELDS}
    if frame.empty or not required <= set(frame):
        raise ValueError("MASSIVE_NORMALIZED_SCHEMA_INVALID")
    if (not frame.ticker.eq(ticker).all() or not frame.source.eq("MASSIVE_GROUPED").all()
            or not frame.adjustment.eq("raw").all() or not frame.provider_code.eq(symbol).all()
            or not frame.currency.eq("USD").all() or frame.date.duplicated().any()
            or frame.date.max() != target):
        raise ValueError("MASSIVE_NORMALIZED_IDENTITY_OR_TARGET_INVALID")
    frame["trade_date"] = pd.to_datetime(frame.date).dt.normalize()
    values = frame[PRICE_FIELDS].to_numpy(float)
    if (not np.isfinite(values).all() or (frame[PRICE_FIELDS[:-1]] <= 0).any().any()
            or (frame.volume < 0).any()
            or (frame.high < frame[["open", "low", "close"]].max(axis=1)).any()
            or (frame.low > frame[["open", "high", "close"]].min(axis=1)).any()):
        raise ValueError("MASSIVE_INVALID_OHLCV")
    references = store.resolve_price_inputs(record, verify_raw=False)
    by_date = {}
    for ref in references:
        if ref["date"] in by_date:
            raise ValueError("MASSIVE_DUPLICATE_SOURCE_DAY")
        by_date[ref["date"]] = ref
    checked = []
    for row in frame.to_dict("records"):
        day = row["date"]
        if not mapping.get("effective_from", day) <= day <= mapping.get("effective_to", day):
            raise ValueError("MASSIVE_MAPPING_OUTSIDE_EFFECTIVE_WINDOW")
        ref = by_date.get(day)
        if not ref or row["source_id"] != ref["sha256"]:
            raise ValueError("MASSIVE_NORMALIZED_SOURCE_ID_MISMATCH")
        observed = datetime.fromisoformat(ref["observed_at"].replace("Z", "+00:00"))
        close = datetime.combine(pd.Timestamp(day).date(), datetime.min.time(), ZoneInfo("America/New_York")) + timedelta(hours=16)
        if observed.tzinfo is None or observed < close:
            raise ValueError("MASSIVE_BAR_OBSERVED_BEFORE_SESSION_CLOSE")
        if pd.Timestamp(row["observed_at"]) != pd.Timestamp(observed):
            raise ValueError("MASSIVE_NORMALIZED_OBSERVED_AT_MISMATCH")
        cache_key = (ref["path"], ref["sha256"], day, ref["observed_at"])
        cached = raw_cache.get(cache_key)
        if cached is None:
            raw_path = verify(ref["path"], ref["sha256"])
            checkpoint_path = raw_path.parent / "checkpoint.json"
            checkpoint_bytes = checkpoint_path.read_bytes()
            checkpoint = json.loads(checkpoint_bytes)
            expected_contract = {"date": day, "url": ENDPOINT + day,
                                 "params": {"adjusted": "false", "include_otc": "false"}}
            if (checkpoint.get("status") != "SUCCESS" or checkpoint.get("contract") != expected_contract
                    or checkpoint.get("raw", {}).get("sha256") != ref["sha256"]
                    or Path(checkpoint.get("raw", {}).get("path", "")).resolve() != raw_path.resolve()
                    or checkpoint.get("observed_at") != ref["observed_at"]):
                raise ValueError("MASSIVE_DAY_CHECKPOINT_IDENTITY_MISMATCH")
            payload = json.loads(raw_path.read_bytes())
            records = validate_response(payload)
            cached = ({item["T"]: item for item in records},
                      hashlib.sha256(checkpoint_bytes).hexdigest(), str(checkpoint_path))
            raw_cache[cache_key] = cached
        raw = cached[0].get(symbol)
        if raw is None:
            raise ValueError("MASSIVE_SYMBOL_ABSENT_FROM_RAW_DAY")
        if not isinstance(raw.get("t"), int) or isinstance(raw["t"], bool) or raw["t"] <= 0:
            raise ValueError("MASSIVE_INVALID_SOURCE_TIMESTAMP")
        source_values = [float(raw[field]) for field in ("o", "h", "l", "c", "v")]
        if not np.array_equal(np.asarray(source_values), np.asarray([row[field] for field in PRICE_FIELDS], dtype=float)):
            raise ValueError("MASSIVE_NORMALIZED_VALUES_DIFFER_FROM_SOURCE")
        if int(row["source_timestamp_ms"]) != raw["t"]:
            raise ValueError("MASSIVE_NORMALIZED_SOURCE_TIMESTAMP_MISMATCH")
        checked.append({**ref, "checkpoint_path": cached[2], "checkpoint_sha256": cached[1]})
    return frame, {"normalized_path": str(path), "normalized_sha256": record["source_sha256"],
                   "provider_symbol": symbol, "provider_mapping": mapping, "raw_inputs": checked}


def _qualified_massive_tail(record, original, ticker, target, store, raw_cache=None, *, gap_dates=None):
    """Bridge only source-proven RAW bars with five matching Moomoo sessions."""
    original = original.sort_values("trade_date")
    required_overlap = original.tail(5)
    if len(required_overlap) != 5:
        raise ValueError("MASSIVE_RAW_OVERLAP_FEWER_THAN_FIVE_SESSIONS")
    gaps = sorted({pd.Timestamp(day) for day in (gap_dates or [])})
    if any(day < original.trade_date.min() or day > original.trade_date.max()
           or day > pd.Timestamp(target) or day in set(original.trade_date) for day in gaps):
        raise ValueError("MASSIVE_GAP_OUTSIDE_MISSING_ANCHORED_RAW")
    gap_anchors = original.iloc[0:0]
    if gaps:
        # Validate five original sessions preceding every missing segment,
        # in addition to the unchanged final-five-session bridge gate.
        parts = [original.loc[original.trade_date.lt(day)].tail(5) for day in gaps]
        if any(len(part) != 5 for part in parts):
            raise ValueError("MASSIVE_GAP_PREFIX_OVERLAP_FEWER_THAN_FIVE_SESSIONS")
        gap_anchors = pd.concat(parts).drop_duplicates("trade_date").sort_values("trade_date")
        required_overlap = pd.concat([gap_anchors, required_overlap]).drop_duplicates("trade_date").sort_values("trade_date")
    first = min([required_overlap.trade_date.min(), *gaps]).date().isoformat()
    frame, source = _massive_raw_window(record, ticker, first, target, store, raw_cache)
    overlap = required_overlap.merge(frame[["trade_date", *PRICE_FIELDS]], on="trade_date", suffixes=("_raw", "_massive"))
    if len(overlap) != len(required_overlap):
        raise ValueError("MASSIVE_RAW_OVERLAP_FEWER_THAN_FIVE_SESSIONS")
    for field in PRICE_FIELDS[:-1]:
        if not np.isclose(overlap[field + "_raw"], overlap[field + "_massive"], rtol=0, atol=1e-6).all():
            raise ValueError("MASSIVE_RAW_OVERLAP_MISMATCH:" + field)
    # Moomoo KLine.volume is int64; Massive grouped v preserves fractional
    # shares. Prove exact whole-share identity, never a widened numeric tolerance.
    raw_volume = overlap["volume_raw"].to_numpy(float)
    massive_volume = overlap["volume_massive"].to_numpy(float)
    if (not np.isfinite(raw_volume).all() or (raw_volume < 0).any()
            or not np.equal(raw_volume, np.floor(raw_volume)).all()):
        raise ValueError("MOOMOO_RAW_VOLUME_NOT_NONNEGATIVE_WHOLE_SHARES")
    if not np.array_equal(raw_volume, np.floor(massive_volume)):
        raise ValueError("MASSIVE_RAW_OVERLAP_MISMATCH:volume")
    tail = frame.loc[(frame.trade_date > original.trade_date.max()) | frame.trade_date.isin(gaps), ["trade_date", *PRICE_FIELDS]].copy()
    if gaps and not set(gaps) <= set(tail.trade_date):
        raise ValueError("MASSIVE_REQUESTED_INTERNAL_GAP_UNAVAILABLE")
    if tail.empty or (original.trade_date.max() < pd.Timestamp(target) and tail.trade_date.max() != pd.Timestamp(target)):
        raise ValueError("MASSIVE_NO_COMPLETE_TARGET_TAIL")
    # Normalize only the derived model tail. Immutable vendor responses and
    # normalized provider archives retain their original fractional quantities.
    tail["volume"] = np.floor(tail["volume"].to_numpy(float))
    proof = {"provider": "MASSIVE_GROUPED", "qualification": "UNADJUSTED_RAW_WITH_FIVE_SESSION_MOOMOO_OVERLAP",
        **source,
        "overlap_sessions": 5,
        "volume_normalization": {"rule": "WHOLE_SHARE_FLOOR", "scope": "DERIVED_MODEL_TAIL_ONLY",
            "reference_schema": "MOOMOO_KLINE_VOLUME_INT64",
            "qualification": "FIVE_SESSION_EXACT_FLOOR_EQUALITY",
            "source_values_preserved": True,
            "overlap": [{"date": pd.Timestamp(row.trade_date).date().isoformat(),
                         "moomoo_volume": float(row.volume_raw),
                         "massive_source_volume": float(row.volume_massive)}
                        for row in overlap.itertuples()]},
        "tail_start": tail.trade_date.min().date().isoformat(), "tail_end": target}
    if gaps:
        proof["gap_fill"] = {"rule": "MISSING_RAW_SESSIONS_ONLY",
            "requested_dates": [day.date().isoformat() for day in gaps],
            "added_dates": tail.trade_date.dt.strftime("%Y-%m-%d").tolist(),
            "prefix_overlap_dates": gap_anchors.trade_date.dt.strftime("%Y-%m-%d").tolist()}
        proof["volume_normalization"]["scope"] = "DERIVED_MISSING_RAW_SESSIONS_ONLY"
    return tail, proof



def load_price_inputs(target, members, sessions, acquisitions, store, rehab_receipt,
                      *, coverage_reference=None):
    """Return (accepted full-history index frame, lineage, explicit missing rows).

    Eligibility matches the original source-covered intersection. Callers must
    disclose exclusions and require enough eligible securities for frozen Top20.
    """
    reference = coverage_reference or {"path": COVERAGE_PATH, "sha256": COVERAGE_SHA}
    coverage = json.loads(verify(reference["path"], reference["sha256"]).read_text(encoding="utf-8"))
    adapter = _adapter(target)
    needed = [day for day in sessions if day <= target][-121:]
    if len(needed) != 121 or needed[-1] != target:
        raise ValueError("A2_NEEDS_121_COMPLETED_SESSIONS")
    target_close = datetime.combine(pd.Timestamp(target).date(), datetime.min.time(), ZoneInfo("America/New_York")) + timedelta(hours=16)
    fresh = {}
    if rehab_receipt.get("target_date") == target and rehab_receipt.get("source") == "MOOMOO_OPEND_GET_REHAB":
        for row in rehab_receipt.get("results", []):
            if row.get("status") == "PASS":
                if row["code"] in fresh:
                    raise ValueError("DUPLICATE_REHAB_RESPONSE_CODE")
                fresh[row["code"]] = row
    fetched = {row["item"]["ticker"]: row for row in acquisitions.get("moomoo", {}).get("results", [])
               if row.get("status") in SUCCESS and row["item"]["adjustment"] == "raw"}
    alternate = acquisitions.get("alternate", {})
    if alternate.get("receipt"):
        alternate = json.loads(Path(alternate["receipt"]).read_text(encoding="utf-8"))
    yahoo = {row["contract"]["ticker"]: row for row in alternate.get("results", []) if row.get("status") == "SUCCESS"}
    massive = {row["ticker"]: row for row in acquisitions.get("massive", {}).get("catalog_records", [])}
    massive_raw_cache = {}
    frames, lineage, missing = [], [], []
    for member in members:
        ticker = member["ticker"]
        code = member.get("moomoo_symbol", member.get("moomoo_transport_code"))
        alternate_rejections = []
        try:
            anchor = coverage["raw"]["code_map"].get(code)
            if not anchor or anchor["ticker"] != ticker:
                raise ValueError("A2_ORIGINAL_RAW_ANCHOR_UNBOUND")
            rehab = fresh.get(code)
            if rehab is None:
                raise ValueError("LATEST_REHAB_RESPONSE_MISSING")
            fetched_at = datetime.fromisoformat(rehab["fetched_at"].replace("Z", "+00:00"))
            if fetched_at.tzinfo is None or fetched_at < target_close:
                raise ValueError("REHAB_RESPONSE_PREDATES_TARGET_CLOSE")
            factors = pd.read_parquet(verify(rehab["path"], rehab["sha256"]))
            if len(factors) != rehab["row_count"] or not factors.code.eq(code).all():
                raise ValueError("REHAB_RESPONSE_IDENTITY_MISMATCH")
            if not factors.empty:
                if not {"ex_div_date", "forward_adj_factorA", "forward_adj_factorB"} <= set(factors):
                    raise ValueError("REHAB_FACTORS_MISSING")
                values = factors[["forward_adj_factorA", "forward_adj_factorB"]].to_numpy(float)
                if not np.isfinite(values).all() or (values[:, 0] <= 0).any():
                    raise ValueError("REHAB_FACTORS_INVALID")
            raw_parts, source_refs = [], []
            for value in anchor["paths"]:
                original = verify(value, coverage["raw"]["file_sha256"][value])
                raw_parts.append(_raw_frame(pq.read_table(original, columns=RAW_COLUMNS, filters=[("code", "=", code)]).to_pandas(), code))
                source_refs.append({"path": str(original), "sha256": coverage["raw"]["file_sha256"][value], "role": "ORIGINAL_ANCHOR"})
            if ticker in fetched:
                receipt = fetched[ticker]
                recent = verify(receipt["path"], receipt["sha256"])
                raw_parts.append(_raw_frame(pd.read_csv(recent), code))
                source_refs.append({"path": str(recent), "sha256": receipt["sha256"], "role": "CURRENT_RAW"})
            else:
                try:
                    metadata = store.metadata("prices_daily", ticker, "raw")
                except (KeyError, FileNotFoundError):
                    metadata = None
                if metadata is not None:
                    current_path = verify(metadata["path"], metadata.get("source_sha256", metadata.get("sha256")))
                    raw_parts.append(_raw_frame(store.daily(ticker, "raw", anchor["first_date"], target), code))
                    source_refs.append({"path": str(current_path), "sha256": digest(current_path), "role": "CURRENT_CATALOG_RAW"})
            raw = pd.concat(raw_parts, ignore_index=True)
            raw = raw.loc[raw.trade_date.between(pd.Timestamp(anchor["first_date"]), pd.Timestamp(target))].copy()
            if raw.empty or raw.trade_date.min() != pd.Timestamp(anchor["first_date"]):
                raise ValueError("ORIGINAL_PRICE_INDEX_ANCHOR_CHANGED")
            for _, duplicate in raw.loc[raw.trade_date.duplicated(keep=False)].groupby("trade_date"):
                if any(duplicate[column].nunique() > 1 for column in PRICE_FIELDS):
                    raise ValueError("CONFLICTING_OVERLAP_RAW_PRICE")
            raw = raw.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)
            bridge = None
            gaps = [day for day in needed if raw.trade_date.min() <= pd.Timestamp(day) <= raw.trade_date.max()
                    and pd.Timestamp(day) not in set(raw.trade_date)]
            if raw.trade_date.max() < pd.Timestamp(target) or gaps:
                candidate = massive.get(ticker)
                if candidate is None:
                    try:
                        candidate = store.metadata("prices_daily_massive", ticker, "raw")
                    except (KeyError, FileNotFoundError):
                        candidate = None
                if candidate is not None:
                    try:
                        tail, bridge = _qualified_massive_tail(candidate, raw, ticker, target, store, massive_raw_cache, gap_dates=gaps)
                        raw = pd.concat([raw, tail], ignore_index=True).sort_values("trade_date").reset_index(drop=True)
                    except (ValueError, KeyError, OSError, RuntimeError) as exc:
                        alternate_rejections.append({"provider": "MASSIVE_GROUPED", "reason": str(exc)})
            if raw.trade_date.max() < pd.Timestamp(target) and ticker in yahoo:
                try:
                    tail, bridge = _qualified_yahoo_tail(yahoo[ticker], raw, ticker, target)
                    raw = pd.concat([raw, tail], ignore_index=True).sort_values("trade_date").reset_index(drop=True)
                except (ValueError, KeyError, OSError, RuntimeError) as exc:
                    alternate_rejections.append({"provider": "YAHOO_CHART", "reason": str(exc)})
            if not set(needed) <= set(raw.trade_date.dt.strftime("%Y-%m-%d")):
                if alternate_rejections:
                    raise ValueError(";".join(row["provider"] + ":" + row["reason"] for row in alternate_rejections))
                raise ValueError("RAW_HISTORY_FEWER_THAN_121_OBSERVATIONS" if len(raw) < 121
                                 else "RAW_121_CONSECUTIVE_SESSIONS_INCOMPLETE")
            wolf = {"event_date": coverage["adjustment"]["wolf_event_date"],
                    "quantity_multiplier": coverage["adjustment"]["wolf_new_shares_per_old_share"]}
            adjusted, events = adapter.adjusted_price_frame(code, ticker, raw, factors, wolf)
            selected = adjusted.loc[adjusted.trade_date.dt.strftime("%Y-%m-%d").isin(needed)].copy()
            if len(selected) != 121:
                raise ValueError("ADJUSTED_SESSION_CARDINALITY_MISMATCH")
            frames.append(selected[["ticker", "trade_date", "close", "volume"]])
            lineage.append({"ticker": ticker, "code": code,
                "source": ("MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB" if bridge and bridge["provider"] == "MASSIVE_GROUPED"
                           else "MOOMOO_RAW_PLUS_QUALIFIED_YAHOO_TAIL_PLUS_MOOMOO_REHAB" if bridge else "MOOMOO_OPEND_RAW_PLUS_REHAB"),
                "price_basis": "PIT_FORWARD_REHAB_INDEX", "anchor_date": anchor["first_date"],
                "adapter_sha256": ADAPTER_SHA, "coverage_manifest_sha256": reference["sha256"],
                "rehab_sha256": rehab["sha256"], "rehab_fetched_at": rehab["fetched_at"],
                "raw_sources": source_refs, "alternate_bridge": bridge, "alternate_rejections": alternate_rejections,
                "applied_event_count": sum(row["audit_kind"] == "APPLIED_CORPORATE_ACTION" for row in events),
                "qualification": "ORIGINAL_PROVIDER_INDEX_CONDITIONAL_NOT_CERTIFIED_TOTAL_RETURN"})
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            reason = str(exc)
            kind = ("INSUFFICIENT_HISTORY" if reason == "RAW_HISTORY_FEWER_THAN_121_OBSERVATIONS"
                    else "UNQUALIFIED_PRICE_BASIS" if "ANCHOR" in reason or "YAHOO" in reason or "MASSIVE" in reason
                    else "DATA_BLOCKED")
            missing.append({"ticker": ticker, "reason": reason, "category": kind,
                            "alternate_provider_inference": "BASIS_NOT_QUALIFIED", "alternate_rejections": alternate_rejections})
    output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ticker", "trade_date", "close", "volume"])
    return output, lineage, missing


def publish_acquired_prices(paths, acquisitions, target, run_dir, progress=None):
    """Publish verified Moomoo intervals, preserving history and other datasets.

    QFQ conflicts get one full-history repair only for already charged symbols.
    Publication failure is returned explicitly so A2 can still use its verified
    raw acquisition receipts. Yahoo snapshots are not spliced into this catalog.
    """
    import csv
    import sqlite3
    from collections import defaultdict
    from types import SimpleNamespace
    from scripts.storage import build_data_catalog as catalog_api
    from scripts.storage import refresh_market_data as refresh
    from scripts import daily_recommendation_inputs as inputs

    work = Path(run_dir) / "market_publication"
    work.mkdir(parents=True, exist_ok=True)
    result_path = work / "publication.json"
    moomoo = acquisitions.get("moomoo", acquisitions)
    request_hash = hashlib.sha256(json.dumps({"target_date": target, "receipts": [
        {key: row.get(key) for key in ("item", "path", "sha256")}
        for row in moomoo.get("results", []) if row.get("status") in SUCCESS
    ]}, sort_keys=True).encode()).hexdigest()
    if result_path.exists():
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        if saved.get("request_sha256") != request_hash:
            return {"status": "BLOCKED", "error": "PUBLICATION_RUN_INPUTS_CHANGED_USE_NEW_RUN_DIRECTORY",
                    "report_path": str(result_path)}
        return saved
    report = {"status": "BLOCKED", "target_date": target, "repairs": [], "issues": [],
              "new_unique_security_touch_count": 0, "request_sha256": request_hash,
              "report_path": str(result_path)}
    conn = None
    try:
        catalog_path = paths.cache_root / "derived/data_catalog/catalog.sqlite3"
        with sqlite3.connect(catalog_path.as_uri() + "?mode=ro", uri=True) as reader:
            selected = {(t, a): {"path": p, "sha256": h, "min_date": lo, "max_date": hi}
                        for t, a, p, h, lo, hi in reader.execute(
                            "SELECT ticker,adjustment,path,source_sha256,min_date,max_date "
                            "FROM data_files WHERE dataset='prices_daily' AND is_current=1")}
        accepted, repairs = [], {}
        for row in moomoo.get("results", []):
            if row.get("status") not in SUCCESS:
                continue
            try:
                item = row["item"]
                if item["adjustment"] not in {"raw", "qfq"}:
                    raise ValueError("UNSUPPORTED_MARKET_ADJUSTMENT")
                path = verify(row["path"], row["sha256"])
                frame = catalog_api.normalize(pd.read_csv(path), item["adjustment"], row["sha256"], target)
                if frame.empty or not frame.ticker.eq(item["ticker"]).all():
                    raise ValueError("PUBLICATION_INTERVAL_IDENTITY_INVALID")
                accepted.append(row)
                old = selected.get((item["ticker"], item["adjustment"]))
                if item["adjustment"] == "qfq" and old and old["max_date"] < target:
                    previous = pd.read_parquet(verify(old["path"], old["sha256"]))
                    combined, _, issues = catalog_api.combine_candidates(
                        [(0, previous, old["path"]), (100, frame, str(path))], "qfq")
                    if combined.date.max() < target and any(x["reason"] == "PRICE_VINTAGE_CONFLICT" for x in issues):
                        repairs[item["ticker"]] = {"ticker": item["ticker"],
                            "moomoo_symbol": item["moomoo_symbol"], "start": old["min_date"]}
            except (ValueError, KeyError, OSError) as exc:
                report["issues"].append({"ticker": row.get("item", {}).get("ticker"), "reason": str(exc)})
        if not accepted:
            raise ValueError("NO_VERIFIED_MOOMOO_INTERVALS_TO_PUBLISH")
        if repairs:
            from scripts.common.daily_support import live_quota
            try:
                _, _, details = live_quota(paths, work)
                charged = {row["code"] for row in details}
            except Exception as exc:
                charged = set()
                report["issues"].append({"reason": "QFQ_REPAIR_QUOTA_UNAVAILABLE:" + str(exc)})
            groups = defaultdict(list)
            for row in repairs.values():
                if row["moomoo_symbol"] in charged:
                    groups[row["start"]].append(row)
                else:
                    report["issues"].append({"ticker": row["ticker"], "reason": "QFQ_REPAIR_REQUIRES_ALREADY_CHARGED_CODE"})
            for start, members in sorted(groups.items()):
                if progress:
                    progress(f"补齐 {len(members)} 只股票的完整前复权历史，保留原始行情。")
                root = work / "qfq_repair" / start
                root.mkdir(parents=True, exist_ok=True)
                universe_csv = root / "universe.csv"
                with universe_csv.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["ticker", "moomoo_symbol"])
                    writer.writeheader()
                    writer.writerows({key: member[key] for key in writer.fieldnames} for member in members)
                try:
                    repair = refresh.run(SimpleNamespace(repo_root=paths.repo_root, work_root=root,
                        tickers=None, universe_csv=universe_csv, start=start, end=target,
                        adjustments=["qfq"], host=None, port=None, max_retries=1, execute=True))
                    report["repairs"].append(repair)
                    report["new_unique_security_touch_count"] += repair.get("new_unique_security_touch_count", 0)
                    if report["new_unique_security_touch_count"]:
                        raise ValueError("QFQ_REPAIR_UNEXPECTED_NEW_UNIQUE_TOUCH")
                    for row in repair.get("results", []):
                        if row.get("status") in SUCCESS:
                            verify(row["path"], row["sha256"])
                            accepted.append(row)
                    if repair.get("status") not in {"ACQUIRED", "ALL_INTERVALS_REUSED"}:
                        report["issues"].append({"reason": "QFQ_FULL_HISTORY_REPAIR_INCOMPLETE", "start": start})
                except Exception as exc:
                    report["issues"].append({"reason": "QFQ_FULL_HISTORY_REPAIR_FAILED:" + str(exc), "start": start})
                if report["new_unique_security_touch_count"]:
                    break
        interval_root = work / "inputs"
        for index, row in enumerate(accepted):
            _write(interval_root / "intervals" / f"{index:05d}.json", row)
        frozen_before = inputs.load_frozen_binding(paths.repo_root)
        with sqlite3.connect(catalog_path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(work / "catalog_before.sqlite3") as backup:
            source.backup(backup)
        conn = sqlite3.connect(catalog_path, timeout=60)
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT ticker,adjustment,path,source_sha256,min_date,max_date,row_count "
                              "FROM data_files WHERE dataset='prices_daily' AND is_current=1").fetchall()
        other_before = conn.execute("SELECT * FROM data_files WHERE dataset!='prices_daily' ORDER BY dataset,ticker,adjustment,path").fetchall()
        if progress:
            progress("发布已验证的行情，并核对旧历史和其他数据指针。")
        publication = catalog_api.materialize_market(paths, conn, target, extra_root=interval_root, updates_only=True)
        current = {(t, a): (p, h, lo, hi, count) for t, a, p, h, lo, hi, count in conn.execute(
            "SELECT ticker,adjustment,path,source_sha256,min_date,max_date,row_count "
            "FROM data_files WHERE dataset='prices_daily' AND is_current=1")}
        for ticker, adjustment, path, expected, first, last, count in before:
            verify(path, expected)
            new = current[(ticker, adjustment)]
            if new[2] > first or new[3] < last or new[4] < count:
                raise ValueError("PUBLICATION_TRUNCATED_EXISTING_HISTORY:" + ticker)
            if new[1] != expected:
                old_dates = set(pq.read_table(path, columns=["date"]).column("date").to_pylist())
                new_dates = set(pq.read_table(new[0], columns=["date"]).column("date").to_pylist())
                if not old_dates <= new_dates:
                    raise ValueError("PUBLICATION_LOST_OLD_SESSION:" + ticker)
        if other_before != conn.execute("SELECT * FROM data_files WHERE dataset!='prices_daily' ORDER BY dataset,ticker,adjustment,path").fetchall():
            raise ValueError("PUBLICATION_CHANGED_NONMARKET_POINTERS")
        if inputs.load_frozen_binding(paths.repo_root) != frozen_before:
            raise ValueError("PUBLICATION_CHANGED_FROZEN_BINDING")
        requested = sorted({(row["item"]["ticker"], row["item"]["adjustment"]) for row in accepted})
        unresolved = [{"ticker": t, "adjustment": a, "max_date": current.get((t, a), (None,) * 5)[3]}
                      for t, a in requested if (t, a) not in current or current[(t, a)][3] < target]
        conn.commit()
        _write(work / "materialization.json", publication)
        report.update(status="PARTIAL" if unresolved or report["issues"] or publication["rejected_sources"] or publication["quarantined_rows"] else "PUBLISHED",
            published_intervals=len(accepted), requested_keys=len(requested), unresolved=unresolved,
            raw_reached_target=sum(a == "raw" and current.get((t, a), (None,) * 5)[3] == target for t, a in requested),
            qfq_reached_target=sum(a == "qfq" and current.get((t, a), (None,) * 5)[3] == target for t, a in requested),
            old_versions_preserved=len(before), all_old_dates_preserved=True,
            nonmarket_pointers_unchanged=True, frozen_binding_unchanged=True,
            rejected_sources=publication["rejected_sources"], quarantined_rows=publication["quarantined_rows"])
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        report.update(status="BLOCKED", error=type(exc).__name__ + ":" + str(exc))
    finally:
        if conn is not None:
            conn.close()
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write(result_path, report)
    return report
