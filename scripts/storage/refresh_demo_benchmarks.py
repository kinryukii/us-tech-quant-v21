"""Extend the DEMO's bound ETF RAW references from verified provider cache.

No provider SDK, HTTP client, credential loader, catalog mutation, or download
fallback is used. Both ETFs must cover every new verified session before the
small reference is atomically published. The initial historical projection is
created separately and retained as immutable provenance.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pandas as pd

COLUMNS = ["date", "ticker", "open", "source", "adjustment"]
CUTOVER = {"date": "2024-09-13", "before": "MOOMOO_OPEND", "on_and_after": "MASSIVE_GROUPED"}
FALLBACK_POLICY = "ETF_NATIVE_RAW_OPEN_FALLBACK_V1"
OFFICIAL_OPEN_POLICY = "ETF_NATIVE_OFFICIAL_OPEN_V1"
ETF_IDENTITIES = {"QQQ": {"security_id": "46090E103", "provider_code": "US.QQQ", "currency": "USD"},
                  "SPY": {"security_id": "78462F103", "provider_code": "US.SPY", "currency": "USD"}}
ENDPOINT = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/"


def _bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _ref(path, expected=None):
    path = Path(path).resolve()
    value = _hash(path)
    if expected is not None and (not re.fullmatch(r"[a-f0-9]{64}", expected) or value != expected):
        raise ValueError("BENCHMARK_SOURCE_HASH_CHANGED:" + str(path))
    return {"path": str(path), "sha256": value}


def _iso(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("BENCHMARK_ISO_DATE_REQUIRED")
    return value


def _reference_shape(value):
    if (not isinstance(value, dict) or not isinstance(value.get("path"), str)
            or not Path(value["path"]).is_absolute()
            or not re.fullmatch(r"[a-f0-9]{64}", value.get("sha256", ""))):
        raise ValueError("BENCHMARK_SOURCE_REFERENCE_INVALID")
    return value


def source_exceptions(manifest):
    """Validate the one explicit append-only provider exception protocol."""
    result = {symbol: set() for symbol in ETF_IDENTITIES}
    records = manifest.get("source_fallbacks", [])
    if not isinstance(records, list) or (records and manifest.get("fixed_source_cutover") != CUTOVER):
        raise ValueError("BENCHMARK_SOURCE_FALLBACK_SCHEMA_INVALID")
    for record in records:
        if not isinstance(record, dict) or record.get("schema") not in {FALLBACK_POLICY, OFFICIAL_OPEN_POLICY}:
            raise ValueError("BENCHMARK_SOURCE_FALLBACK_SCHEMA_INVALID")
        days = [_iso(day) for day in record.get("dates", [])]
        prior_end = _iso(record.get("previous_end_date"))
        _reference_shape(record.get("previous_manifest"))
        if (not days or days != sorted(set(days)) or prior_end >= days[0]
                or days[-1] > manifest["end_date"] or days[0] < CUTOVER["date"]
                or set(days) & result["QQQ"]):
            raise ValueError("BENCHMARK_SOURCE_FALLBACK_DATE_INVALID")
        if record["schema"] == OFFICIAL_OPEN_POLICY:
            from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
            phase = record.get("execution_open", {})
            if (days != [phase.get("execution_date")] or phase.get("signal_date") != prior_end
                    or record.get("reason") != "OFFICIAL_RTH_OPEN_ONLY_NOT_CLOSED_OHLCV"
                    or "massive_failures" in record):
                raise ValueError("BENCHMARK_OFFICIAL_OPEN_PHASE_INVALID")
            execution_open_clock(prior_end, days[0], phase.get("sessions", []), phase.get("as_of_utc"))
        else:
            failures = record.get("massive_failures", [])
            if (not isinstance(failures, list) or [x.get("date") for x in failures] != days
                    or any(x.get("status") != "FAILED" or not x.get("error") for x in failures)):
                raise ValueError("BENCHMARK_SOURCE_FALLBACK_FAILURE_PROOF_INVALID")
            for failure in failures:
                captured = _reference_shape(failure.get("reference"))
                origin = _reference_shape(failure.get("origin_reference"))
                if captured["sha256"] != origin["sha256"]:
                    raise ValueError("BENCHMARK_SOURCE_FALLBACK_FAILURE_CAPTURE_MISMATCH")
        proofs = record.get("qualifications", {})
        if set(proofs) != set(ETF_IDENTITIES):
            raise ValueError("BENCHMARK_SOURCE_FALLBACK_BOTH_ETFS_REQUIRED")
        latest = None
        for symbol, proof in proofs.items():
            identity = ETF_IDENTITIES[symbol]
            overlap = proof.get("overlap_days")
            five = proof.get("latest_five_dates", [])
            if (any(proof.get(k) != v for k, v in identity.items())
                    or proof.get("source") != "MOOMOO_OPEND" or proof.get("adjustment") != "raw"
                    or proof.get("comparison") != "EXACT_FLOAT_EQUALITY"
                    or proof.get("all_overlap_exact") is not True
                    or type(overlap) is not int or overlap < 5
                    or proof.get("exact_equal_count") != overlap
                    or not isinstance(five, list) or len(five) != 5
                    or five != sorted(set(_iso(day) for day in five)) or five[-1] != prior_end):
                raise ValueError("BENCHMARK_SOURCE_FALLBACK_QUALIFICATION_INVALID:" + symbol)
            if latest is not None and five != latest:
                raise ValueError("BENCHMARK_SOURCE_FALLBACK_CALENDARS_DIFFER")
            latest = five
            inputs = proof.get("source_refs")
            if not isinstance(inputs, list) or not inputs:
                raise ValueError("BENCHMARK_SOURCE_FALLBACK_INPUTS_REQUIRED")
            for item in inputs:
                _reference_shape(item)
            if record["schema"] == OFFICIAL_OPEN_POLICY:
                opened = proof.get("official_open", {})
                opening, observed = execution_open_clock(prior_end, days[0], phase["sessions"], phase["as_of_utc"])
                captured = pd.Timestamp(opened.get("observed_at_utc"))
                if (opened.get("date") != days[0] or opened.get("code") != identity["provider_code"]
                        or opened.get("price_field") != "open" or opened.get("session") != "RTH"
                        or opened.get("adjustment") != "raw" or opened.get("intraday_ohlcv_consumed") is not False
                        or captured.tzinfo is None or not opening <= captured <= observed):
                    raise ValueError("BENCHMARK_OFFICIAL_OPEN_QUALIFICATION_INVALID:" + symbol)
                _reference_shape(opened.get("sdk_response"))
            result[symbol].update(days)
    return result


def _native_reference(paths, reference):
    reference = _reference_shape(reference)
    path = Path(reference["path"]).resolve()
    roots = [Path(getattr(paths, name)).resolve() for name in
             ("data_root", "cache_root", "daily_root", "results_root") if hasattr(paths, name)]
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError("BENCHMARK_NATIVE_INPUT_OUTSIDE_ALLOWED_ROOTS")
    return _ref(path, reference["sha256"])


def _native_rows(paths, symbol, target, specification):
    """Reuse original native-leaf and current-kline qualification owners."""
    identity = ETF_IDENTITIES[symbol]
    if not isinstance(specification, dict) or any(specification.get(k) != v for k, v in identity.items()):
        raise ValueError("BENCHMARK_NATIVE_SECURITY_IDENTITY_INVALID:" + symbol)
    reference = _native_reference(paths, specification.get("reference"))
    if specification.get("kind") == "CATALOG_RAW":
        from scripts.research.a2.inference.historical_top40_prices import _store
        from scripts.research.a2.inference.current_native_prices import _native_raw
        store = _store(paths)
        record = store.metadata("prices_daily", symbol, "raw")
        if (Path(record["path"]).resolve() != Path(reference["path"])
                or record.get("source_sha256") != reference["sha256"]):
            raise ValueError("BENCHMARK_NATIVE_CATALOG_REFERENCE_MISMATCH")
        raw, proof = _native_raw(store, symbol, identity["provider_code"], target)
        refs = [reference, *proof["raw_inputs"]]
        frame = raw.rename(columns={"trade_date": "date"})[["date", "open"]].copy()
    elif specification.get("kind") == "CURRENT_KLINE":
        from scripts.storage import refresh_market_data as market
        import pyarrow.parquet as pq
        saved = json.loads(Path(reference["path"]).read_bytes())
        item, provenance = saved.get("item", {}), saved.get("current_kline_provenance", {})
        if (item.get("ticker") != symbol or item.get("moomoo_symbol") != identity["provider_code"]
                or item.get("security_id") != identity["security_id"] or item.get("market") != "US"
                or item.get("adjustment") != "raw" or item.get("planned_end_date") != target
                or item.get("acquisition_method") != "GET_CUR_KLINE" or item.get("session") != "RTH"
                or item.get("num") != market.CURRENT_KLINE_NUM or item.get("subscribe_push") is not False
                or provenance.get("code") != identity["provider_code"] or provenance.get("api") != "get_cur_kline"
                or type(provenance.get("retcode")) is not int or provenance.get("retcode") != 0 or provenance.get("autype") != "NONE"
                or provenance.get("ktype") != "K_DAY" or provenance.get("session") != "RTH"
                or saved.get("status") not in {"FETCHED_VALIDATED_INTERVAL", "REUSED_VERIFIED_INTERVAL"}):
            raise ValueError("BENCHMARK_NATIVE_CURRENT_KLINE_CONTRACT_INVALID")
        try:
            observed = datetime.fromisoformat(provenance["observed_at_utc"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("BENCHMARK_NATIVE_CLOSED_BAR_NOT_OBSERVED") from exc
        closing = datetime.fromisoformat(target + "T16:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
        if (observed.tzinfo is None or observed.utcoffset() is None
                or not closing <= observed <= datetime.now(timezone.utc)):
            raise ValueError("BENCHMARK_NATIVE_CLOSED_BAR_NOT_OBSERVED")
        root = Path(reference["path"]).parent.parent
        verified = market.read_checkpoint(root, item)
        if verified is None or Path(verified["path"]).resolve() != Path(saved["path"]).resolve():
            raise ValueError("BENCHMARK_NATIVE_CURRENT_KLINE_CHECKPOINT_INVALID")
        raw_ref = _native_reference(paths, {"path": saved["path"], "sha256": saved["sha256"]})
        sdk_ref = _native_reference(paths, provenance.get("sdk_response"))
        if not Path(sdk_ref["path"]).is_relative_to(root / "sdk_responses"):
            raise ValueError("BENCHMARK_NATIVE_SDK_RESPONSE_OUTSIDE_CHECKPOINT")
        sdk = pq.ParquetFile(sdk_ref["path"])
        if sdk.metadata.num_rows > market.CURRENT_KLINE_NUM:
            raise ValueError("BENCHMARK_NATIVE_SDK_RESPONSE_LIMIT")
        frame_sdk = pq.read_table(sdk_ref["path"], filters=[("time_key", ">=", item["planned_start_date"]),
            ("time_key", "<=", target + " 23:59:59")]).to_pandas()
        if frame_sdk.empty or not frame_sdk.code.eq(identity["provider_code"]).all():
            raise ValueError("BENCHMARK_NATIVE_SDK_RESPONSE_CODE_INVALID")
        fetcher = market.load_module(paths.repo_root / market.FETCHER, "benchmark_original_kline_normalizer")
        normalized = fetcher.normalize_records(frame_sdk, symbol, identity["provider_code"], "US", "raw",
            "benchmark_leaf_validation", provenance["observed_at_utc"])
        market.validate_records(normalized, item)
        captured = pd.DataFrame(normalized).sort_values("date").reset_index(drop=True)
        recorded = pd.read_csv(raw_ref["path"]).sort_values("date").reset_index(drop=True)
        if captured.date.tolist() != recorded.date.tolist():
            raise ValueError("BENCHMARK_NATIVE_SDK_RESPONSE_DATES_DIFFER")
        fields = ["open", "high", "low", "close", "volume", "turnover"]
        if not captured[fields].astype(float).equals(recorded[fields].astype(float)):
            raise ValueError("BENCHMARK_NATIVE_SDK_RESPONSE_PRICES_DIFFER")
        refs = [reference, raw_ref, sdk_ref]
        frame = recorded[["date", "open"]].copy()
    else:
        raise ValueError("BENCHMARK_NATIVE_INPUT_KIND_INVALID")
    frame["date"] = pd.to_datetime(frame.date).dt.strftime("%Y-%m-%d")
    frame = frame.loc[frame.date.le(target)].reset_index(drop=True)
    if (frame.empty or frame.date.tolist() != sorted(set(frame.date))
            or not all(math.isfinite(float(value)) and float(value) > 0 for value in frame.open)):
        raise ValueError("BENCHMARK_NATIVE_OPEN_PROJECTION_INVALID")
    for ref in refs:
        _native_reference(paths, ref)
    return frame, refs


def _qualified_native(paths, native_inputs, frames, old_dates, target):
    if not isinstance(native_inputs, dict) or set(native_inputs) != set(ETF_IDENTITIES):
        raise ValueError("BENCHMARK_NATIVE_BOTH_ETF_INPUTS_REQUIRED")
    if len(old_dates) < 5:
        raise ValueError("BENCHMARK_NATIVE_FIVE_ACCEPTED_SESSIONS_REQUIRED")
    result, proofs, refs = {}, {}, []
    for symbol, previous in frames.items():
        current, sources = _native_rows(paths, symbol, target, native_inputs[symbol])
        overlap = previous[["date", "open"]].merge(current, on="date", suffixes=("_accepted", "_native"), validate="one_to_one")
        if (len(overlap) < 5 or not set(old_dates[-5:]) <= set(overlap.date)
                or not overlap.open_accepted.eq(overlap.open_native).all()):
            raise ValueError("BENCHMARK_NATIVE_EXACT_OPEN_BRIDGE_FAILED:" + symbol)
        proofs[symbol] = {**ETF_IDENTITIES[symbol], "source": "MOOMOO_OPEND", "adjustment": "raw",
            "comparison": "EXACT_FLOAT_EQUALITY", "overlap_days": len(overlap), "exact_equal_count": len(overlap),
            "latest_five_dates": old_dates[-5:], "all_overlap_exact": True, "source_refs": sources,
            "availability": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT"}
        result[symbol] = dict(zip(current.date, current.open.astype(float)))
        refs.extend(sources)
    return result, proofs, refs


def _qualified_official_open(paths, native_inputs, frames, old_dates, target, calendar, phase):
    """Reuse closed-history qualification; materialize only the next official open."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from scripts.research.a2.evaluation.demo_performance_prices import execution_open_clock
    if (not isinstance(phase, dict) or phase.get("signal_date") != old_dates[-1]
            or phase.get("execution_date") != target
            or set(native_inputs or {}) != set(ETF_IDENTITIES)
            or any(spec.get("kind") != "CURRENT_KLINE" for spec in native_inputs.values())):
        raise ValueError("BENCHMARK_OFFICIAL_OPEN_INPUTS_REQUIRED")
    signal = old_dates[-1]
    opening, observed = execution_open_clock(signal, target, calendar["sessions"], phase.get("as_of_utc"))
    # The original validator still verifies all mature OHLCV only through signal.
    _, qualifications, refs = _qualified_native(paths, native_inputs, frames, old_dates, signal)
    rows = {}
    for symbol, identity in ETF_IDENTITIES.items():
        reference = _native_reference(paths, native_inputs[symbol]["reference"])
        saved = json.loads(Path(reference["path"]).read_bytes())
        provenance = saved["current_kline_provenance"]
        captured = pd.Timestamp(provenance.get("observed_at_utc"))
        if (provenance.get("num") != 130 or provenance.get("owned_subscription") is not True
                or provenance.get("sdk_response_semantics") != "RETURNED_DATAFRAME_PARQUET_NOT_WIRE_RESPONSE"
                or provenance.get("availability") != "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT"
                or captured.tzinfo is None or not opening <= captured <= observed):
            raise ValueError("BENCHMARK_OFFICIAL_OPEN_OBSERVATION_INVALID:" + symbol)
        sdk = _native_reference(paths, provenance["sdk_response"])
        schema = pq.read_schema(sdk["path"])
        if pa.types.is_boolean(schema.field("open").type):
            raise ValueError("BENCHMARK_OFFICIAL_OPEN_BOOLEAN_PRICE_INVALID:" + symbol)
        kind = schema.field("time_key").type
        lo, hi = pd.Timestamp(target), pd.Timestamp(target) + pd.Timedelta(days=1)
        if pa.types.is_timestamp(kind):
            if kind.tz is not None:
                raise ValueError("BENCHMARK_OFFICIAL_OPEN_NATIVE_DATE_COORDINATE_INVALID")
            lower, upper = lo.to_pydatetime(), hi.to_pydatetime()
        elif pa.types.is_date(kind):
            lower, upper = lo.date(), hi.date()
        elif pa.types.is_string(kind) or pa.types.is_large_string(kind):
            lower, upper = lo.date().isoformat(), hi.date().isoformat()
        else:
            raise ValueError("BENCHMARK_OFFICIAL_OPEN_NATIVE_DATE_COORDINATE_INVALID")
        # Intraday high/low/close/volume/turnover are never materialized here.
        terminal = pq.read_table(sdk["path"], columns=["code", "time_key", "open"],
            filters=[("time_key", ">=", lower), ("time_key", "<", upper)]).to_pandas()
        if (len(terminal) != 1 or terminal.iloc[0].code != identity["provider_code"]
                or pd.Timestamp(terminal.iloc[0].time_key).normalize() != lo
                or isinstance(terminal.iloc[0].open, bool)
                or not math.isfinite(float(terminal.iloc[0].open)) or float(terminal.iloc[0].open) <= 0):
            raise ValueError("BENCHMARK_OFFICIAL_OPEN_MISSING_OR_INVALID:" + symbol)
        rows[symbol] = {"date": target, "ticker": symbol, "open": float(terminal.iloc[0].open),
                        "source": "MOOMOO_OPEND", "adjustment": "raw"}
        qualifications[symbol]["official_open"] = {"date": target, "code": identity["provider_code"],
            "price_field": "open", "session": "RTH", "adjustment": "raw",
            "observed_at_utc": provenance["observed_at_utc"], "sdk_response": sdk,
            "intraday_ohlcv_consumed": False}
    for ref in refs:
        _native_reference(paths, ref)
    return rows, qualifications, refs


def _failed_checkpoint(cache_root, day):
    path = Path(cache_root) / "daily_recommendation/massive_current/days" / day / "checkpoint.json"
    reference = _ref(path)
    saved = json.loads(path.read_bytes())
    expected = {"date": day, "url": ENDPOINT + day, "params": {"adjusted": "false", "include_otc": "false"}}
    if saved.get("contract") != expected or saved.get("status") != "FAILED" or not saved.get("error"):
        raise ValueError("BENCHMARK_NATIVE_REQUIRES_EXPLICIT_MASSIVE_FAILURE:" + day)
    return {"date": day, "status": "FAILED", "error": saved["error"], "reference": reference}


def expected_source(day, source_days=()):
    return "MOOMOO_OPEND" if day in source_days or day < CUTOVER["date"] else CUTOVER["on_and_after"]


def _preserve_failure(root, failure):
    """Preserve actual FAILED cache bytes before its legitimate later retry."""
    original = failure["reference"]
    _ref(original["path"], original["sha256"])
    payload = Path(original["path"]).read_bytes()
    if hashlib.sha256(payload).hexdigest() != original["sha256"]:
        raise ValueError("BENCHMARK_FAILED_CACHE_CHANGED_DURING_CAPTURE")
    path = (root / "updated/input_proofs" / original["sha256"] / "failed_checkpoint.json").resolve()
    if not path.is_relative_to(root / "updated"):
        raise ValueError("BENCHMARK_FAILURE_CAPTURE_OUTSIDE_DERIVED_ROOT")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _ref(path, original["sha256"])
    else:
        path.write_bytes(payload)
    _ref(original["path"], original["sha256"])
    return {**failure, "origin_reference": original, "reference": _ref(path, original["sha256"])}


def _frame(frame, symbol, source_days=()):
    frame = frame.loc[:, COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame.date).dt.strftime("%Y-%m-%d")
    if (frame.empty or not frame.ticker.eq(symbol).all() or not frame.adjustment.eq("raw").all()
            or frame.date.tolist() != sorted(set(frame.date))
            or not all(math.isfinite(float(x)) and float(x) > 0 for x in frame.open)):
        raise ValueError("BENCHMARK_INVALID_PRICE_PROJECTION:" + symbol)
    wanted = frame.date.map(lambda day: expected_source(day, source_days))
    if not frame.source.eq(wanted).all():
        raise ValueError("BENCHMARK_FIXED_RAW_SOURCE_RULE_CHANGED")
    return frame.reset_index(drop=True)


def _checkpoint(cache_root, day):
    root = (Path(cache_root) / "daily_recommendation/massive_current/days" / day).resolve()
    checkpoint_path = root / "checkpoint.json"
    checkpoint_ref = _ref(checkpoint_path)
    saved = json.loads(checkpoint_path.read_bytes())
    expected = {"date": day, "url": ENDPOINT + day,
                "params": {"adjusted": "false", "include_otc": "false"}}
    if saved.get("status") != "SUCCESS" or saved.get("contract") != expected:
        raise ValueError("BENCHMARK_MASSIVE_DAY_NOT_VERIFIED:" + day)
    source = saved["raw"]
    raw_path = Path(source["path"]).resolve()
    if raw_path.parent != root or raw_path.suffix != ".json":
        raise ValueError("BENCHMARK_MASSIVE_RAW_OUTSIDE_CHECKPOINT")
    raw_ref = _ref(raw_path, source["sha256"])
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) != source["bytes"]:
        raise ValueError("BENCHMARK_MASSIVE_RAW_SIZE_CHANGED")
    raw = json.loads(raw_bytes)
    if raw.get("status") != "OK" or not isinstance(raw.get("results"), list) or raw.get("resultsCount") != len(raw["results"]) or raw.get("next_url"):
        raise ValueError("BENCHMARK_MASSIVE_RESPONSE_NOT_COMPLETE")
    if raw.get("adjusted") is not False:
        raise ValueError("BENCHMARK_MASSIVE_RAW_BASIS_REQUIRED")
    rows = {}
    for symbol in ("QQQ", "SPY"):
        selected = [row for row in raw.get("results", []) if row.get("T") == symbol]
        if len(selected) != 1:
            raise ValueError("BENCHMARK_ETF_MISSING_OR_DUPLICATED:" + day + ":" + symbol)
        item = selected[0]
        stamp = pd.Timestamp(item["t"], unit="ms", tz="UTC").tz_convert("America/New_York")
        opening = float(item["o"])
        if stamp.strftime("%Y-%m-%d") != day or not math.isfinite(opening) or opening <= 0:
            raise ValueError("BENCHMARK_INVALID_CACHED_OPEN:" + day + ":" + symbol)
        rows[symbol] = {"date": day, "ticker": symbol, "open": opening,
                        "source": "MASSIVE_GROUPED", "adjustment": "raw"}
    # Detect source changes during extraction before publication.
    _ref(raw_path, raw_ref["sha256"])
    _ref(checkpoint_path, checkpoint_ref["sha256"])
    return rows, [raw_ref, checkpoint_ref]


def _refresh(paths, target, calendar, result, *, native_inputs=None, publish=True, scope_only=False, execution_open=None):
    target = _iso(target)
    sessions = [_iso(day) for day in calendar["sessions"]]
    if sessions != sorted(set(sessions)) or target not in sessions or calendar.get("target_date") != target:
        raise ValueError("BENCHMARK_VERIFIED_TARGET_CALENDAR_REQUIRED")
    root = (Path(paths.results_root) / "demo-console/benchmarks").resolve()
    pointer = root / "updated_reference.json"
    original_pointer = pointer.read_bytes()
    reference = json.loads(original_pointer)
    manifest_path = Path(reference["path"]).resolve()
    if not manifest_path.is_relative_to(root / "updated"):
        raise ValueError("BENCHMARK_REFERENCE_OUTSIDE_DERIVED_ROOT")
    manifest_ref = _ref(manifest_path, reference["sha256"])
    base = json.loads(manifest_path.read_bytes())
    if (base.get("schema_version") != 1 or base.get("status") != "READY"
            or base.get("basis") != "OPEN_TO_OPEN_PRICE_RETURN" or base.get("adjustment") != "RAW"
            or base.get("provider") != "MOOMOO_OPEND_AND_MASSIVE" or base.get("dividends_included") is not False
            or base.get("splits_adjusted") is not False or base.get("fixed_source_cutover") != CUTOVER):
        raise ValueError("BENCHMARK_ESTABLISHED_RAW_CONTRACT_CHANGED")
    artifacts = base["artifacts"]
    if len(artifacts) != 2 or sorted(x["symbol"] for x in artifacts) != ["QQQ", "SPY"]:
        raise ValueError("BENCHMARK_BOTH_ETFS_REQUIRED")
    exceptions = source_exceptions(base)
    frames, old_dates = {}, None
    for artifact in artifacts:
        symbol, path = artifact["symbol"], Path(artifact["path"]).resolve()
        if path.parent != manifest_path.parent:
            raise ValueError("BENCHMARK_PRICE_OUTSIDE_IMMUTABLE_RUN")
        _ref(path, artifact["sha256"])
        frame = _frame(pd.read_parquet(path, columns=COLUMNS), symbol, exceptions[symbol])
        if len(frame) != artifact["row_count"] or (frame.date.iloc[0], frame.date.iloc[-1]) != (artifact["start_date"], artifact["end_date"]):
            raise ValueError("BENCHMARK_PRICE_COVERAGE_METADATA_CHANGED")
        if artifact["start_date"] != base["start_date"] or artifact["end_date"] != base["end_date"]:
            raise ValueError("BENCHMARK_COMMON_WINDOW_REQUIRED")
        if old_dates is not None and frame.date.tolist() != old_dates:
            raise ValueError("BENCHMARK_ETF_DATE_SETS_DIFFER")
        old_dates = frame.date.tolist()
        if not artifact.get("source_refs"):
            raise ValueError("BENCHMARK_SOURCE_REFS_REQUIRED")
        for source in artifact["source_refs"]:
            _ref(source["path"], source["sha256"])
        frames[symbol] = frame
    previous_end = base["end_date"]
    result.update(previous_end_date=previous_end, available_end_date=previous_end, base_end=previous_end,
                  bridge_start=old_dates[-min(5, len(old_dates))], required_dates=[], missing_dates=[], native_tickers=[])
    if target < base["start_date"]:
        raise ValueError("BENCHMARK_TARGET_BEFORE_AVAILABLE_WINDOW")
    if target <= previous_end:
        if target not in old_dates:
            raise ValueError("BENCHMARK_TARGET_MISSING_FROM_EXISTING_WINDOW")
        result.update(status="NOOP" if scope_only else "READY", reused=True, manifest=manifest_ref, reference=str(pointer),
                      start_date=base["start_date"], end_date=previous_end, appended_sessions=0)
        return result
    if previous_end not in sessions:
        raise ValueError("BENCHMARK_PREVIOUS_END_OUTSIDE_VERIFIED_CALENDAR")
    days = [day for day in sessions if previous_end < day <= target]
    additions = {symbol: [] for symbol in frames}
    refs = []
    if execution_open is not None:
        if scope_only or days != [target]:
            raise ValueError("BENCHMARK_OFFICIAL_OPEN_ONLY_NEXT_SESSION")
        rows, qualifications, refs = _qualified_official_open(paths, native_inputs, frames, old_dates,
                                                              target, calendar, execution_open)
        cached = {target: rows}
        fallback = {"schema": OFFICIAL_OPEN_POLICY, "dates": [target], "previous_end_date": previous_end,
            "previous_manifest": manifest_ref, "reason": "OFFICIAL_RTH_OPEN_ONLY_NOT_CLOSED_OHLCV",
            "execution_open": {"signal_date": previous_end, "execution_date": target,
                "sessions": old_dates[-5:] + [target], "as_of_utc": execution_open["as_of_utc"]},
            "qualifications": qualifications}
        for symbol in frames:
            exceptions[symbol].add(target)
        result.update(official_open_only=True, closed_ohlcv_observed=False)
    else:
        failures, cached = [], {}
        for day in days:
            try:
                rows, inputs = _checkpoint(paths.cache_root, day)
            except (ValueError, KeyError, OSError):
                failures.append(_failed_checkpoint(paths.cache_root, day))
            else:
                cached[day] = rows
                refs.extend(inputs)
        scope = {"target_date": target, "base_end": previous_end, "bridge_start": old_dates[-min(5, len(old_dates))],
                 "missing_dates": [item["date"] for item in failures],
                 "required_dates": old_dates[-5:] + [item["date"] for item in failures] if failures else [],
                 "native_tickers": sorted(frames) if failures else []}
        result.update(scope)
        if scope_only:
            result.update(status="NEEDS_NATIVE" if failures else "MASSIVE_READY", massive_failures=failures)
            return result
        fallback = None
        if failures:
            native, qualifications, native_refs = _qualified_native(paths, native_inputs, frames, old_dates, target)
            failures = [_preserve_failure(root, failure) for failure in failures]
            refs.extend(native_refs)
            refs.extend(item["reference"] for item in failures)
            fallback = {"schema": FALLBACK_POLICY, "dates": scope["missing_dates"], "previous_end_date": previous_end,
                        "previous_manifest": manifest_ref, "massive_failures": failures, "qualifications": qualifications}
            for symbol in frames:
                exceptions[symbol].update(scope["missing_dates"])
            for day in scope["missing_dates"]:
                cached[day] = {}
                for symbol in frames:
                    if day not in native[symbol]:
                        raise ValueError("BENCHMARK_NATIVE_REQUIRED_SESSION_MISSING:" + day + ":" + symbol)
                    cached[day][symbol] = {"date": day, "ticker": symbol, "open": native[symbol][day],
                                           "source": "MOOMOO_OPEND", "adjustment": "raw"}
    for day in days:
        for symbol in frames:
            additions[symbol].append(cached[day][symbol])
    for symbol in frames:
        frames[symbol] = _frame(pd.concat([frames[symbol], pd.DataFrame(additions[symbol])], ignore_index=True), symbol, exceptions[symbol])
        if frames[symbol].date.tolist() != old_dates + days:
            raise ValueError("BENCHMARK_NEW_SESSION_COVERAGE_MISMATCH")
    for ref in refs:
        _ref(ref["path"], ref["sha256"])
    calendar_proof = {key: calendar[key] for key in ("calendar_id", "calendar_sha256", "as_of_utc") if key in calendar}
    calendar_proof.update(target_date=target, appended_sessions=days,
                          sessions_sha256=hashlib.sha256(_bytes(sessions)).hexdigest())
    contract = {key: value for key, value in base.items() if key not in
                {"artifacts", "generated_at", "run_id", "content_fingerprint", "previous_manifest", "refresh_calendar", "end_date"}}
    contract.update(end_date=target, previous_manifest=manifest_ref, refresh_calendar=calendar_proof)
    if fallback:
        contract["source_fallbacks"] = [*base.get("source_fallbacks", []), fallback]
    source_exceptions(contract)
    specifications = []
    for artifact in artifacts:
        sources = {item["path"]: item for item in [*artifact["source_refs"], manifest_ref,
                   {"path": artifact["path"], "sha256": artifact["sha256"]}, *refs]}
        specifications.append({"symbol": artifact["symbol"], "start_date": base["start_date"], "end_date": target,
                               "row_count": len(frames[artifact["symbol"]]), "source_refs": [sources[k] for k in sorted(sources)]})
    identity = hashlib.sha256(_bytes({**contract, "artifacts": specifications})).hexdigest()
    run_dir = root / "updated" / identity[:24]
    run_dir.mkdir(parents=True, exist_ok=True)
    for artifact in specifications:
        path = run_dir / (artifact["symbol"] + ".parquet")
        if path.exists():
            pd.testing.assert_frame_equal(pd.read_parquet(path), frames[artifact["symbol"]])
        else:
            frames[artifact["symbol"]].to_parquet(path, index=False)
        artifact.update(_ref(path))
        pd.testing.assert_frame_equal(_frame(pd.read_parquet(path), artifact["symbol"], exceptions[artifact["symbol"]]), frames[artifact["symbol"]])
    manifest = {**contract, "artifacts": specifications, "generated_at": datetime.now(timezone.utc).isoformat(),
                "run_id": identity[:24], "content_fingerprint": identity}
    output = run_dir / "manifest.json"
    if output.exists():
        prior = json.loads(output.read_bytes())
        if prior["content_fingerprint"] != identity or prior["artifacts"] != specifications:
            raise ValueError("BENCHMARK_IMMUTABLE_RUN_CONFLICT")
    else:
        output.write_bytes(_bytes(manifest))
    published = _ref(output)
    if pointer.read_bytes() != original_pointer:
        raise ValueError("BENCHMARK_REFERENCE_CHANGED_DURING_REFRESH")
    temporary = pointer.with_name("updated_reference." + identity[:16] + ".tmp")
    if publish:
        temporary.write_bytes(_bytes(published))
        os.replace(temporary, pointer)
    result.update(status="READY", reused=False, manifest=published, reference=str(pointer),
                  start_date=base["start_date"], end_date=target, available_end_date=target if publish else previous_end, appended_sessions=len(days),
                  published=publish, source_fallback_applied=bool(fallback))
    return result


def refresh_demo_benchmarks(paths, target, calendar, progress=lambda message: None, *, native_inputs=None, publish=True, execution_open=None):
    """Return an independent status; missing cache never changes the old pointer."""
    result = {"status": "BLOCKED", "target_date": target, "network_requests": 0, "moomoo_requests": 0,
              "basis": "OPEN_TO_OPEN_PRICE_RETURN", "dividends_included": False}
    try:
        if type(publish) is not bool:
            raise ValueError("BENCHMARK_PUBLISH_BOOLEAN_REQUIRED")
        result = _refresh(paths, target, calendar, result, native_inputs=native_inputs, publish=publish, execution_open=execution_open)
    except Exception as exc:
        result["error"] = str(exc)
        progress("QQQ / SPY 缓存尚未覆盖本次日期；保留已有基准及其实际截止日期。")
        return result
    progress("QQQ / SPY 价格基准" + ("已发布" if publish else "候选已核验（尚未发布）")
             + "至 " + result["end_date"] + "（不含分红）。")
    return result


def benchmark_native_scope(paths, target, calendar):
    """Cache-only acquisition scope using the publisher's exact existing gates."""
    result = {"status": "BLOCKED", "target_date": target, "network_requests": 0, "moomoo_requests": 0}
    try:
        result = _refresh(paths, target, calendar, result, publish=False, scope_only=True)
    except Exception as exc:
        result["error"] = str(exc)
    return result
