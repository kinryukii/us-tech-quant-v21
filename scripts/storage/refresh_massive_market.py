"""Official grouped daily raw snapshots; key stays in caller memory, no catalog writes.

Raw day checkpoints are independent of the local ticker scope, so explicit
mapping corrections or scope additions can be normalized offline on resume.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote

import pandas as pd
import requests

from scripts.storage.build_data_catalog import PRICE_COLUMNS, sha256, utc_now
from scripts.storage.restore_sec_data import file_identity, write_frame
from scripts.storage.storage_r2a import DataStore, resolve_storage_paths
from scripts.storage.manage_data import acquisition_tickers

SOURCE = "MASSIVE_GROUPED"
DATASET = "prices_daily_massive"
ENDPOINT = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/"
DOC_URL = "https://massive.com/docs/rest/stocks/aggregates/daily-market-summary"
EXTRA_COLUMNS = ["source_timestamp_ms", "vwap", "transactions", "currency"]
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


def write_json(path, payload, *, immutable=False):
    path = Path(path)
    # Match the established write_text newline translation on this platform.
    encoded = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").replace("\n", os.linesep).encode("utf-8")
    if immutable and path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"Preserving a different existing manifest: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)


def checked_days(days):
    days = sorted(set(days))
    if not days or any(date.fromisoformat(day).isoformat() != day for day in days):
        raise ValueError("EXPLICIT_ISO_DATES_REQUIRED")
    return days


def provider_mapping(tickers, symbol_map=None):
    tickers = sorted(set(tickers))
    mapping = symbol_map or {}
    if not tickers or set(mapping) - set(tickers):
        raise ValueError("MAPPING_OUTSIDE_EXPLICIT_TICKER_SCOPE")
    output = {}
    for ticker in tickers:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,31}", ticker) or ".." in ticker:
            raise ValueError("INVALID_CATALOG_TICKER")
        item = mapping.get(ticker, {"provider_symbol": ticker})
        if not isinstance(item, dict):
            raise ValueError("EXPLICIT_MAPPING_OBJECT_REQUIRED")
        symbol = item.get("provider_symbol", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}", symbol) or ".." in symbol:
            raise ValueError("INVALID_PROVIDER_SYMBOL")
        if symbol != ticker and not str(item.get("evidence_url", "")).startswith("https://"):
            raise ValueError("NONIDENTICAL_SYMBOL_REQUIRES_MAPPING_EVIDENCE")
        output[ticker] = {"provider_symbol": symbol, "evidence_url": item.get("evidence_url")}
        for bound in ("effective_from", "effective_to"):
            if item.get(bound):
                output[ticker][bound] = checked_days([item[bound]])[0]
    if len({item["provider_symbol"] for item in output.values()}) != len(output):
        raise ValueError("AMBIGUOUS_PROVIDER_SYMBOL_MAPPING")
    return output


def validate_response(payload):
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        raise ValueError("PROVIDER_STATUS_NOT_OK")
    if payload.get("adjusted") is not False:
        raise ValueError("RAW_ADJUSTMENT_NOT_CONFIRMED")
    rows = payload.get("results", [])
    if not isinstance(rows, list) or payload.get("resultsCount") != len(rows):
        raise ValueError("RESULT_COUNT_MISMATCH")
    if payload.get("next_url"):
        raise ValueError("UNEXPECTED_GROUPED_PAGINATION")
    symbols = [item.get("T") for item in rows if isinstance(item, dict)]
    if len(symbols) != len(rows) or any(not isinstance(s, str) for s in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("INVALID_OR_DUPLICATE_PROVIDER_SYMBOL")
    return rows


def normalize_grouped(payload, requested_date, mapping, source_id, observed_at):
    """Date is the requested exchange session; raw timestamp never changes it."""
    checked_days([requested_date])
    observed = pd.Timestamp(observed_at)
    if observed.tzinfo is None:
        raise ValueError("OBSERVED_AT_REQUIRES_UTC_OFFSET")
    rows = validate_response(payload)
    for item in mapping.values():
        if requested_date < item.get("effective_from", requested_date) or requested_date > item.get("effective_to", requested_date):
            raise ValueError("MAPPING_OUTSIDE_EXPLICIT_EFFECTIVE_DATES")
    inverse = {item["provider_symbol"]: ticker for ticker, item in mapping.items()}
    accepted, rejected = [], []
    for raw in rows:
        symbol = raw["T"]
        if symbol not in inverse:
            continue
        ticker = inverse[symbol]
        try:
            numbers = {name: float(raw[field]) for name, field in
                       (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))}
            valid = all(math.isfinite(value) for value in numbers.values())
            valid &= min(numbers[k] for k in ("open", "high", "low", "close")) > 0
            valid &= numbers["volume"] >= 0
            valid &= numbers["high"] >= max(numbers[k] for k in ("open", "low", "close"))
            valid &= numbers["low"] <= min(numbers[k] for k in ("open", "high", "close"))
            timestamp = raw["t"]
            valid &= isinstance(timestamp, int) and not isinstance(timestamp, bool) and timestamp > 0
            vwap, transactions = raw.get("vw"), raw.get("n")
            valid &= vwap is None or (math.isfinite(float(vwap)) and float(vwap) > 0)
            valid &= transactions is None or (isinstance(transactions, int) and not isinstance(transactions, bool) and transactions >= 0)
            if not valid:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            rejected.append({"ticker": ticker, "provider_symbol": symbol, "date": requested_date, "reason": "INVALID_OHLCV_OR_SOURCE_FIELDS"})
            continue
        accepted.append({**numbers, "ticker": ticker, "date": requested_date,
            "turnover": float("nan"), "adjustment": "raw", "source": SOURCE,
            "provider_code": symbol, "source_id": source_id, "observed_at": observed_at,
            "source_timestamp_ms": timestamp, "vwap": None if vwap is None else float(vwap),
            "transactions": transactions, "currency": "USD"})
    frame = pd.DataFrame(accepted, columns=PRICE_COLUMNS + EXTRA_COLUMNS)
    for col in ["open", "high", "low", "close", "volume", "turnover", "vwap"]:
        frame[col] = pd.to_numeric(frame[col]).astype("float64")
    for col in ["source_timestamp_ms", "transactions"]:
        frame[col] = frame[col].astype("Int64")
    return frame.sort_values(["ticker", "date"]).reset_index(drop=True), rejected


def wait_request(root, minimum_interval=12.5):
    """Single shared process gate plus persisted spacing across resumes."""
    global _LAST_REQUEST
    with _REQUEST_LOCK:
        state = root / "request_gate.json"
        saved = json.loads(state.read_text()) if state.exists() else {}
        wait = max(0.0, _LAST_REQUEST + minimum_interval - time.monotonic(),
                   saved.get("not_before_epoch", 0) - time.time())
        if wait:
            time.sleep(wait)
        _LAST_REQUEST = time.monotonic()
        write_json(state, {"not_before_epoch": time.time() + minimum_interval})


def acquire_day(day, key, root, *, request_get=requests.get, gate=wait_request):
    checkpoint = root / "days" / day / "checkpoint.json"
    contract = {"date": day, "url": ENDPOINT + day,
                "params": {"adjusted": "false", "include_otc": "false"}}
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved["contract"] != contract:
            raise ValueError("DAY_CHECKPOINT_CONTRACT_CHANGED")
        for item in saved.get("attempts", []):
            if "raw" in item and sha256(item["raw"]["path"]) != item["raw"]["sha256"]:
                raise ValueError("DAY_CHECKPOINT_RAW_CHANGED")
        if saved["status"] == "SUCCESS":
            validate_response(json.loads(Path(saved["raw"]["path"]).read_bytes()))
            return saved, 0
    else:
        saved = {"contract": contract, "status": "PENDING", "attempts": []}
    # Three consecutive failed requests end the run; auth/rate-limit ends sooner.
    requests_made = 0
    for _ in range(3):
        gate(root)
        attempt = {"started_at": utc_now()}
        requests_made += 1
        try:
            response = request_get(contract["url"], params=contract["params"],
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                timeout=(15, 45), allow_redirects=False)
            observed = utc_now()
            raw = response.content
            # Fail closed if an upstream error happens to echo a credential.
            if key.encode() in raw:
                raise ValueError("RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED")
            digest = hashlib.sha256(raw).hexdigest()
            destination = checkpoint.parent / ("response_" + digest + ".json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and sha256(destination) != digest:
                raise ValueError("RAW_HASH_COLLISION_OR_FILE_CHANGED")
            if not destination.exists():
                temporary = destination.with_suffix(".json.tmp")
                temporary.write_bytes(raw)
                temporary.replace(destination)
            attempt.update(observed_at=observed, http_status=response.status_code,
                           raw=file_identity(destination), http_date=response.headers.get("Date"))
            if response.status_code == 200:
                validate_response(json.loads(raw))
                saved.update(status="SUCCESS", raw=attempt["raw"], observed_at=observed)
            else:
                attempt["error"] = "HTTP_" + str(response.status_code)
        except requests.RequestException:
            attempt["error"] = "NETWORK_FAILURE"
        except (ValueError, UnicodeDecodeError):
            attempt["error"] = "INVALID_OR_UNSAFE_PROVIDER_RESPONSE"
        saved["attempts"].append(attempt)
        if saved["status"] != "SUCCESS":
            saved.update(status="FAILED", error=attempt["error"])
        write_json(checkpoint, saved)
        if saved["status"] == "SUCCESS":
            return saved, requests_made
        if attempt.get("http_status", 500) < 500 or attempt["error"] == "INVALID_OR_UNSAFE_PROVIDER_RESPONSE":
            break
    return saved, requests_made


def materialize(days, mapping, frames, rejected, references, failures, output_root, scope_source, requests_made=0):
    """Pure local normalization publication shared by acquisition and cache reuse."""
    contract = {"schema_version": 1, "provider": SOURCE, "days": days, "mapping": mapping,
                "scope_source": scope_source, "inputs": references, "failures": failures}
    version = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:24]
    directory = output_root / "versions" / version
    directory.mkdir(parents=True, exist_ok=True)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS + EXTRA_COLUMNS)
    if combined.duplicated(["ticker", "date"]).any():
        raise ValueError("DUPLICATE_NORMALIZED_TICKER_DATE")
    records, coverage = [], []
    by_hash = {ref["sha256"]: ref for ref in references}
    for ticker, item in mapping.items():
        frame = combined.loc[combined.ticker == ticker].sort_values("date").reset_index(drop=True)
        missing = sorted(set(days) - set(frame.date))
        coverage.append({"ticker": ticker, "provider_symbol": item["provider_symbol"],
            "rows": len(frame), "missing_dates": missing,
            "status": "COMPLETE_REQUESTED_SESSIONS" if not missing else "MISSING_PROVIDER_BARS"})
        if frame.empty:
            continue
        output = write_frame(directory / quote(ticker, safe="") / "daily_raw.parquet", frame)
        lineage = {"schema_version": 1, "role": "PROVIDER_DAILY_PRICE_SNAPSHOT", "provider": SOURCE,
            "date_column": "date", "price_basis": "RAW", "currency": "USD",
            "exchange_timezone": "America/New_York", "provider_symbol": item["provider_symbol"],
            "vintage_semantics": "CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT",
            "inputs": [by_hash[value] for value in sorted(set(frame.source_id))],
                "transport_mapping_evidence": item["evidence_url"], "provider_mapping": item, "source_url": DOC_URL,
            "identity_semantics": "EXPLICIT_TRANSPORT_MAPPING_NOT_HISTORICAL_IDENTITY_CERTIFICATION",
            "date_semantics": "REQUESTED_EXCHANGE_SESSION_DATE_SOURCE_TIMESTAMP_MS_PRESERVED",
            "turnover_semantics": "NOT_REPORTED_NULL_NO_VWAP_TIMES_VOLUME_INFERENCE",
            "requested_start": days[0], "requested_end": days[-1]}
        records.append({"dataset": DATASET, "ticker": ticker, "adjustment": "raw", "format": "parquet",
            "path": output["path"], "source_sha256": output["sha256"], "source": SOURCE,
            "row_count": len(frame), "min_date": frame.date.min(), "max_date": frame.date.max(),
            "vintage_id": version, "updated_utc": frame.observed_at.max(), "lineage": lineage})
    manifest_path = directory / "acquisition_manifest.json"
    summary = {"status": "COMPLETE" if len(references) == len(days) else "STOPPED_PARTIAL",
        "planned_days": len(days), "completed_days": len(references), "scope_tickers": len(mapping),
        "tickers_with_rows": len(records), "normalized_rows": len(combined),
        "missing_ticker_days": sum(len(row["missing_dates"]) for row in coverage),
        "rejected_rows": len(rejected), "network_requests_this_run": requests_made,
        "manifest_path": str(manifest_path), "catalog_written": False}
    write_json(manifest_path, {"summary": {k: v for k, v in summary.items() if k != "network_requests_this_run"}, "contract": contract, "coverage": coverage,
        "rejected_rows": rejected, "catalog_records": records,
        "availability": "CURRENT_RETRIEVAL_ONLY_NO_HISTORICAL_PIT_CLAIM",
        "free_plan": {"history_years": 2, "minimum_request_interval_seconds": 12.5,
                      "plan_url": "https://massive.com/stocks"}}, immutable=True)
    return summary



def acquire(days, tickers, key, workroot, *, symbol_map=None, output_root=None,
            scope_source=None, request_get=requests.get, gate=wait_request, progress=None):
    """Checkpoint daily bodies, then publish immutable candidate Parquet files.

    Caller supplies the secret in memory. Return only counts and manifest path.
    One writer per work root; no account mutations and no catalog mutations.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("IN_MEMORY_API_KEY_REQUIRED")
    days = checked_days(days)
    mapping = provider_mapping(tickers, symbol_map)
    root = Path(workroot).resolve()
    output_root = Path(output_root or root / "normalized").resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".writer.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        frames, rejected, references, completed, requests_made = [], [], [], [], 0
        failures = []
        for day in days:
            saved, count = acquire_day(day, key, root, request_get=request_get, gate=gate)
            requests_made += count
            if saved["status"] != "SUCCESS":
                failures.append({"date": day, "error": saved["error"]})
                break
            frame, bad = normalize_grouped(json.loads(Path(saved["raw"]["path"]).read_bytes()),
                day, mapping, saved["raw"]["sha256"], saved["observed_at"])
            frames.append(frame)
            rejected.extend(bad)
            references.append({"date": day, **saved["raw"], "observed_at": saved["observed_at"]})
            completed.append(day)
            write_json(root / "progress.json", {"completed_days": len(completed), "planned_days": len(days),
                "last_date": day, "network_requests_this_run": requests_made, "updated_at": utc_now()})
            if progress:
                progress({"date": day, "completed_days": len(completed), "planned_days": len(days)})
        summary = materialize(days, mapping, frames, rejected, references, failures,
            output_root, scope_source, requests_made)
        write_json(root / "acquisition_summary.json", summary)
        return summary
    finally:
        lock.unlink()


def normalize_cached(*, acquisition_manifest, checkpoint_root, symbol_map, output_root):
    """Offline alias supplement: verify every completed source day before writing.

    No API key, transport object, request callback or network fallback exists on
    this call path. Original manifests, day checkpoints and summaries are inputs.
    """
    return _normalize_cached_selection(acquisition_manifest, checkpoint_root,
        symbol_map, symbol_map, output_root, explicit_symbols=False)


def normalize_cached_tickers(acquisition_manifest, checkpoint_root, tickers,
                             symbol_map=None, *, output_root):
    """Normalize explicitly selected symbols from verified full-market raw only.

    This adds neither a subscription nor identity/strategy membership. Optional
    effective dates bound transport selection; all source days are still verified
    and retained in the candidate's coverage. No network fallback exists.
    """
    if isinstance(tickers, (str, bytes)) or tickers is None:
        raise ValueError("EXPLICIT_TICKER_LIST_REQUIRED")
    tickers = list(tickers)
    if not tickers or any(not isinstance(ticker, str) for ticker in tickers):
        raise ValueError("EXPLICIT_TICKER_LIST_REQUIRED")
    return _normalize_cached_selection(acquisition_manifest, checkpoint_root,
        tickers, symbol_map, output_root, explicit_symbols=True)


def _normalize_cached_selection(acquisition_manifest, checkpoint_root, tickers,
                                symbol_map, output_root, *, explicit_symbols):
    manifest_path = Path(acquisition_manifest).resolve()
    original = file_identity(manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    root, output_root = Path(checkpoint_root).resolve(), Path(output_root).resolve()
    if output_root.is_relative_to(root) or output_root.is_relative_to(manifest_path.parent):
        raise ValueError("OFFLINE_OUTPUT_MUST_BE_SEPARATE_FROM_SOURCE")
    contract = manifest["contract"]
    if manifest["summary"]["status"] != "COMPLETE" or contract["provider"] != SOURCE:
        raise ValueError("COMPLETE_GROUPED_SOURCE_MANIFEST_REQUIRED")
    if not explicit_symbols and (not symbol_map or set(symbol_map) - set(contract["mapping"])):
        raise ValueError("ALIAS_SUPPLEMENT_OUTSIDE_ORIGINAL_SCOPE")
    mapping = provider_mapping(tickers, symbol_map)
    if explicit_symbols and any(item.get("effective_from", "0001-01-01") > item.get("effective_to", "9999-12-31")
                                for item in mapping.values()):
        raise ValueError("REVERSED_EXPLICIT_EFFECTIVE_DATES")
    original_owners = {(row["lineage"]["provider_symbol"], row["ticker"]) for row in manifest["catalog_records"]}
    if explicit_symbols:
        # An original scoped ticker reserves its transport even when no bars
        # were returned; new symbols cannot silently acquire that ownership.
        original_owners.update((item["provider_symbol"], ticker) for ticker, item in contract["mapping"].items())
    if any(symbol == item["provider_symbol"] and owner != ticker
           for ticker, item in mapping.items() for symbol, owner in original_owners):
        raise ValueError("ALIAS_PROVIDER_SYMBOL_ALREADY_OWNED_IN_ORIGINAL_SNAPSHOT")
    days = checked_days(contract["days"])
    refs = contract["inputs"]
    if len(refs) != len(days) or sorted(ref["date"] for ref in refs) != days:
        raise ValueError("SOURCE_MANIFEST_DAY_COVERAGE_MISMATCH")
    frames, rejected, references, checkpoint_refs = [], [], [], []
    for ref in sorted(refs, key=lambda item: item["date"]):
        day = ref["date"]
        day_root = root / "days" / day
        checkpoint = day_root / "checkpoint.json"
        if day_root.resolve() != day_root or checkpoint.resolve() != checkpoint:
            raise ValueError("DAY_CHECKPOINT_OUTSIDE_EXPECTED_DIRECTORY")
        checkpoint_bytes = checkpoint.read_bytes()
        saved = json.loads(checkpoint_bytes)
        expected = {"date": day, "url": ENDPOINT + day,
                    "params": {"adjusted": "false", "include_otc": "false"}}
        if saved.get("status") != "SUCCESS" or saved["contract"] != expected:
            raise ValueError("COMPLETE_DAY_CHECKPOINT_REQUIRED")
        if any(saved["raw"][key] != ref[key] for key in ("path", "sha256", "bytes")) or saved["observed_at"] != ref["observed_at"]:
            raise ValueError("SOURCE_MANIFEST_CHECKPOINT_MISMATCH")
        # Verify all retained attempts, including errors; raw success also gets
        # checked from the exact bytes subsequently parsed, avoiding read races.
        for attempt in saved.get("attempts", []):
            if "raw" in attempt:
                attempt_path = Path(attempt["raw"]["path"])
                if not attempt_path.is_absolute() or not attempt_path.resolve().is_relative_to(day_root):
                    raise ValueError("DAY_RAW_OUTSIDE_CHECKPOINT_DIRECTORY")
                if sha256(attempt_path) != attempt["raw"]["sha256"]:
                    raise ValueError("DAY_CHECKPOINT_RAW_CHANGED")
        raw_path = Path(ref["path"]).resolve()
        if not Path(ref["path"]).is_absolute() or not raw_path.is_relative_to(day_root):
            raise ValueError("DAY_RAW_OUTSIDE_CHECKPOINT_DIRECTORY")
        raw = raw_path.read_bytes()
        if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("DAY_CHECKPOINT_RAW_CHANGED")
        selected = {ticker: item for ticker, item in mapping.items()
                    if item.get("effective_from", day) <= day <= item.get("effective_to", day)} if explicit_symbols else mapping
        frame, bad = normalize_grouped(json.loads(raw), day, selected, ref["sha256"], ref["observed_at"])
        frames.append(frame)
        rejected.extend(bad)
        references.append(ref)
        checkpoint_ref = file_identity(checkpoint)
        if checkpoint_ref["sha256"] != hashlib.sha256(checkpoint_bytes).hexdigest():
            raise ValueError("DAY_CHECKPOINT_CHANGED_DURING_OFFLINE_READ")
        checkpoint_refs.append(checkpoint_ref)
    if file_identity(manifest_path) != original:
        raise ValueError("SOURCE_MANIFEST_CHANGED_DURING_OFFLINE_READ")
    scope_source = {"mode": "VERIFIED_CACHE_ONLY_ALIAS_SUPPLEMENT", "network_requests": 0,
        "provider_collision_policy": "REJECT_ALIAS_DUPLICATING_EXISTING_PROVIDER_SYMBOL_OWNER",
        "acquisition_manifest": original, "day_checkpoints": checkpoint_refs,
        "original_ticker_scope_sha256": hashlib.sha256(json.dumps(sorted(contract["mapping"])).encode()).hexdigest()}
    if explicit_symbols:
        scope_source.update(mode="EXPLICIT_SYMBOLS",
            provider_collision_policy="REJECT_SYMBOL_OWNED_BY_ANOTHER_ORIGINAL_TICKER",
            selection_semantics="EXPLICIT_TRANSPORT_SYMBOLS_NO_IDENTITY_CERTIFICATION_OR_STRATEGY_MEMBERSHIP",
            effective_date_policy="FILTER_EXPLICIT_TRANSPORT_WINDOW_KEEP_ALL_SOURCE_DAYS_IN_COVERAGE")
    return materialize(days, mapping, frames, rejected, references, [], output_root, scope_source)


def compact_acquisition_manifest(acquisition_manifest, output_root):
    """Verify an immutable completed snapshot and share its repeated raw inputs.

    Reads only the supplied manifest and its referenced files; never accesses a
    live acquisition work root, performs HTTP, or writes/copies price Parquet.
    """
    source = Path(acquisition_manifest).resolve()
    raw_manifest = source.read_bytes()
    source_sha = hashlib.sha256(raw_manifest).hexdigest()
    original = json.loads(raw_manifest)
    if original.get("summary", {}).get("status") != "COMPLETE" or original.get("contract", {}).get("provider") != SOURCE:
        raise ValueError("COMPACT_REQUIRES_COMPLETED_MASSIVE_ACQUISITION")
    contract = original["contract"]
    days = checked_days(contract["days"])
    leaves = []
    for item in sorted(contract["inputs"], key=lambda ref: ref["date"]):
        if item.get("provider", SOURCE) != SOURCE:
            raise ValueError("COMPACT_MIXED_SOURCE_PROVIDER")
        leaf = {key: item[key] for key in ("path", "sha256", "date", "observed_at")}
        path = Path(leaf["path"])
        observed = pd.Timestamp(leaf["observed_at"])
        if not path.is_absolute() or pd.isna(observed) or observed.tzinfo is None:
            raise ValueError("COMPACT_INVALID_RAW_PATH_OR_OBSERVED_TIME")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != leaf["sha256"] or ("bytes" in item and len(raw) != item["bytes"]):
            raise ValueError("COMPACT_RAW_HASH_MISMATCH")
        validate_response(json.loads(raw))
        leaves.append(leaf)
    if [leaf["date"] for leaf in leaves] != days or any(len({leaf[key] for leaf in leaves}) != len(leaves) for key in ("path", "sha256", "date")):
        raise ValueError("COMPACT_DUPLICATE_OR_INCOMPLETE_RAW_INPUTS")
    by_sha = {leaf["sha256"]: (index, leaf) for index, leaf in enumerate(leaves)}
    source_dates = {leaf["sha256"]: leaf["date"] for leaf in leaves}
    source_observed = {leaf["sha256"]: leaf["observed_at"] for leaf in leaves}
    checked_records = []
    keys = set()
    for record in original["catalog_records"]:
        lineage = record["lineage"]
        identity = (record["dataset"], record["ticker"], record["adjustment"])
        if identity in keys:
            raise ValueError("COMPACT_DUPLICATE_CATALOG_RECORD")
        keys.add(identity)
        if (record["dataset"], record["source"], record["adjustment"], record.get("format", "parquet"),
                lineage.get("provider"), lineage.get("price_basis")) != (DATASET, SOURCE, "raw", "parquet", SOURCE, "RAW"):
            raise ValueError("COMPACT_MIXED_SOURCE_PROVIDER_OR_PRICE_BASIS")
        if "inputs_manifest" in lineage or not lineage.get("inputs"):
            raise ValueError("COMPACT_REQUIRES_ORIGINAL_INLINE_INPUTS")
        selected = []
        for item in lineage["inputs"]:
            index, leaf = by_sha.get(item["sha256"], (None, None))
            if leaf is None or any(item.get(key) != leaf[key] for key in leaf):
                raise ValueError("COMPACT_RECORD_RAW_LINEAGE_MISMATCH")
            selected.append(index)
        if len(set(selected)) != len(selected):
            raise ValueError("COMPACT_DUPLICATE_RECORD_INPUT")
        price_path = Path(record["path"])
        if not price_path.is_absolute() or sha256(price_path) != record["source_sha256"]:
            raise ValueError("COMPACT_PRICE_HASH_MISMATCH")
        frame = pd.read_parquet(price_path, columns=["ticker", "date", "source", "adjustment", "provider_code", "source_id", "observed_at"])
        if (len(frame) != record["row_count"] or frame.empty or frame.duplicated(["ticker", "date"]).any()
                or not frame.ticker.eq(record["ticker"]).all() or not frame.source.eq(SOURCE).all()
                or not frame.adjustment.eq("raw").all() or not frame.provider_code.eq(lineage["provider_symbol"]).all()
                or frame.date.min() != record["min_date"] or frame.date.max() != record["max_date"]):
            raise ValueError("COMPACT_PRICE_IDENTITY_OR_COVERAGE_MISMATCH")
        if frame.source_id.isna().any() or set(frame.source_id) != {leaves[index]["sha256"] for index in selected}:
            raise ValueError("COMPACT_ROW_SOURCE_ID_MISMATCH")
        if not frame.date.eq(frame.source_id.map(source_dates)).all() or not frame.observed_at.eq(frame.source_id.map(source_observed)).all():
            raise ValueError("COMPACT_ROW_DATE_OR_OBSERVED_TIME_MISMATCH")
        checked_records.append((record, sorted(selected)))
    if not checked_records or len(checked_records) != original["summary"]["tickers_with_rows"]:
        raise ValueError("COMPACT_RECORD_COUNT_MISMATCH")
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha:
        raise ValueError("COMPACT_SOURCE_MANIFEST_CHANGED_DURING_READ")
    shared = {"schema_version": 1, "role": "RAW_INPUT_MANIFEST", "provider": SOURCE, "inputs": leaves}
    encode = lambda value: (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    shared_bytes = encode(shared)
    shared_sha = hashlib.sha256(shared_bytes).hexdigest()
    root = Path(output_root).resolve()
    directory = root / "versions" / source_sha[:24]
    shared_path = root / "shared_inputs" / ("raw_inputs_" + shared_sha[:24] + ".json")
    records = []
    for record, selected in checked_records:
        ref = {"path": str(shared_path), "sha256": shared_sha}
        if selected != list(range(len(leaves))):
            ref["indexes"] = selected
        records.append({**record, "lineage": {**{k: v for k, v in record["lineage"].items() if k != "inputs"}, "inputs_manifest": ref}})
    manifest_path = directory / "compact_acquisition_manifest.json"
    compact = {"schema_version": 1, "role": "COMPACT_PROVIDER_CATALOG_RECORDS", "provider": SOURCE,
        "source_acquisition_manifest": {"path": str(source), "sha256": source_sha},
        "summary": {**original["summary"], "manifest_path": str(manifest_path)},
        "inputs_manifest": {"path": str(shared_path), "sha256": shared_sha}, "catalog_records": records,
        "prices_reused_without_modification": True, "catalog_written": False, "network_requests": 0}
    compact_bytes = encode(compact)
    for path, data in ((shared_path, shared_bytes), (manifest_path, compact_bytes)):
        if path == source or (path.exists() and path.read_bytes() != data):
            raise ValueError("COMPACT_PRESERVING_DIFFERENT_EXISTING_MANIFEST")
    for path, data in ((shared_path, shared_bytes), (manifest_path, compact_bytes)):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_bytes(data); temporary.replace(path)
    metadata_bytes = len(shared_bytes) + len(compact_bytes)
    return {"status": "COMPLETE", "manifest": file_identity(manifest_path), "shared_inputs": file_identity(shared_path),
        "record_count": len(records), "raw_input_count": len(leaves), "price_files_reused": len(records),
        "source_manifest_bytes": len(raw_manifest), "compact_metadata_bytes": metadata_bytes,
        "metadata_bytes_saved": len(raw_manifest) - metadata_bytes, "network_requests": 0, "parquet_files_written": 0}


def run_acquisition(*, api_key, start_date, end_date, work_root,
                    repo_root=Path("D:/us-tech-quant"), symbol_map=None, progress=None):
    """Resolve current catalog scope and calendar. No API key CLI or environment."""
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    today = pd.Timestamp.now(tz="America/New_York").date()
    if start > end or start < (pd.Timestamp(today) - pd.DateOffset(years=2)).date() or end >= today:
        raise ValueError("REQUEST_OUTSIDE_FREE_TWO_YEAR_COMPLETED_DAY_WINDOW")
    paths = resolve_storage_paths(Path(repo_root))
    root = Path(work_root).resolve()
    if not root.is_relative_to(paths.cache_root):
        raise ValueError("ACQUISITION_WORK_ROOT_MUST_BE_UNDER_RESOLVED_CACHE_ROOT")
    store = DataStore(paths)
    tickers = acquisition_tickers(store)
    calendar = store.metadata("trading_calendar")
    if sha256(calendar["path"]) != calendar["source_sha256"]:
        raise ValueError("CALENDAR_SOURCE_HASH_CHANGED")
    if calendar["min_date"] > start_date or calendar["max_date"] < end_date:
        raise ValueError("CATALOG_CALENDAR_DOES_NOT_COVER_REQUEST")
    sessions = store.read("trading_calendar", start_date=start_date, end_date=end_date,
        date_column="trade_date", columns=["trade_date"])
    days = sessions["trade_date"].tolist()
    scope_source = {"catalog_path": str(store.catalog_path), "selection": "CURRENT_DAILY_PROVIDER_TICKERS_AND_EXPLICIT_DATA_SUBSCRIPTIONS",
        "tickers_sha256": hashlib.sha256(json.dumps(tickers).encode()).hexdigest(),
        "calendar": {"path": calendar["path"], "sha256": calendar["source_sha256"]}}
    return acquire(days, tickers, api_key, root, symbol_map=symbol_map,
        output_root=paths.data_root / "providers/massive/grouped_daily", scope_source=scope_source,
        progress=progress)
