"""Incremental current-pool Massive raw prices through the existing adapter.

No fitting, universe discovery, provider/basis substitution, or plaintext keys.
The caller owns current member selection. Target coverage here means raw bars,
not eligibility for the frozen model's separately checked adjusted-price basis.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote

import pandas as pd

from scripts.storage import refresh_massive_market as massive
from scripts.storage.build_data_catalog import register_file, sha256
from scripts.storage.restore_sec_data import file_identity, write_frame
from scripts.storage.storage_r2a import DataStore, resolve_storage_paths


_MAX_KEY_BYTES = 4096
_MAX_ENCRYPTED_BYTES = 65536


def _checked_key(value):
    if not isinstance(value, str):
        raise ValueError("MASSIVE_INVALID_API_KEY")
    value = value.strip()
    if not value or len(value.encode("utf-8")) > _MAX_KEY_BYTES or any(ord(char) < 33 or ord(char) == 127 or char.isspace() for char in value):
        raise ValueError("MASSIVE_INVALID_API_KEY")
    return value


def _credential_path(paths):
    paths = paths or resolve_storage_paths()
    destination = (paths.cache_root / "private_credentials/massive_api_key.dpapi").resolve()
    DataStore(paths)._check_data_path(destination, must_exist=False)
    if not destination.is_relative_to(paths.cache_root.resolve()):
        raise ValueError("MASSIVE_CREDENTIAL_PATH_OUTSIDE_CACHE_ROOT")
    return destination


def _dpapi(data, *, decrypt=False):
    """Windows current-user DPAPI with UI forbidden and fixed app entropy."""
    if os.name != "nt":
        raise OSError("DPAPI_WINDOWS_REQUIRED")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(value):
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return buffer, Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))

    buffer, incoming = blob(data)
    entropy_buffer, entropy = blob(b"us-tech-quant:massive-api-key:v1")
    outgoing = Blob()
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                          ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    try:
        if not operation(ctypes.byref(incoming), None if decrypt else "US Tech Quant Massive API key",
                         ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing)):
            raise OSError("DPAPI_OPERATION_FAILED")
        limit = _MAX_KEY_BYTES if decrypt else _MAX_ENCRYPTED_BYTES
        if not 0 < outgoing.cbData <= limit:
            raise ValueError("DPAPI_OUTPUT_SIZE_INVALID")
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.memset(buffer, 0, len(data))
        ctypes.memset(entropy_buffer, 0, len(entropy_buffer))
        if outgoing.pbData:
            ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
            kernel32.LocalFree(outgoing.pbData)


def save_encrypted_key(paths, key):
    """Save only current-user DPAPI ciphertext after caller obtains consent."""
    key = _checked_key(key)
    destination = _credential_path(paths)
    encrypted = _dpapi(key.encode("utf-8"))
    if not 0 < len(encrypted) <= _MAX_ENCRYPTED_BYTES:
        raise ValueError("MASSIVE_ENCRYPTED_CREDENTIAL_INVALID_SIZE")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".dpapi.tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(destination)
    return {"status": "SAVED_CURRENT_USER_DPAPI", "path": str(destination)}


def load_api_key(paths=None, *, issues=None):
    """Read named env/HKCU settings, then optional current-user DPAPI storage.

    Return the credential only in memory. Optional issues receive fixed error
    codes without credential values, exception text, or plaintext file paths.
    """
    issues = issues if issues is not None else []
    names = ("MASSIVE_API_KEY", "POLYGON_API_KEY")
    for name in names:
        value = os.environ.get(name, "")
        if value.strip():
            try:
                return _checked_key(value)
            except ValueError:
                issues.append({"reason": "MASSIVE_ENVIRONMENT_CREDENTIAL_INVALID"})
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            for name in names:
                try:
                    value, kind = winreg.QueryValueEx(handle, name)
                except FileNotFoundError:
                    continue
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(value, str) and value.strip():
                    try:
                        return _checked_key(value)
                    except ValueError:
                        issues.append({"reason": "MASSIVE_USER_ENVIRONMENT_CREDENTIAL_INVALID"})
    except (ImportError, OSError):
        pass
    try:
        path = _credential_path(paths)
        with path.open("rb") as stream:
            encrypted = stream.read(_MAX_ENCRYPTED_BYTES + 1)
        if not 0 < len(encrypted) <= _MAX_ENCRYPTED_BYTES:
            issues.append({"reason": "MASSIVE_ENCRYPTED_CREDENTIAL_INVALID_SIZE"})
            return None
        return _checked_key(_dpapi(encrypted, decrypt=True).decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError):
        issues.append({"reason": "MASSIVE_ENCRYPTED_CREDENTIAL_UNAVAILABLE_OR_INVALID"})
        return None


def _cached_days(roots, target):
    """Index successful day checkpoints, never load the 209 MB scope manifest."""
    found = {}
    for root in roots:
        for path in sorted((root / "days").glob("*/checkpoint.json")):
            day = path.parent.name
            if day > target:
                continue
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("status") == "SUCCESS":
                massive.checked_days([day])
                found[day] = (path, saved)
    return found


def _read_record(store, record):
    """Verify selected price bytes and their exact per-row source references."""
    if sha256(record["path"]) != record["source_sha256"]:
        raise ValueError("MASSIVE_SELECTED_PRICE_HASH_CHANGED")
    refs = store.resolve_price_inputs(record, verify_raw=False)
    frame = pd.read_parquet(record["path"])
    by_sha = {item["sha256"]: item for item in refs}
    if (frame.empty or frame.duplicated(["ticker", "date"]).any()
            or len(frame) != record["row_count"] or frame.date.min() != record["min_date"]
            or frame.date.max() != record["max_date"] or not frame.ticker.eq(record["ticker"]).all()
            or not frame.source.eq(massive.SOURCE).all() or not frame.adjustment.eq("raw").all()
            or not frame.provider_code.eq(record["lineage"]["provider_symbol"]).all()
            or set(frame.source_id) != set(by_sha)):
        raise ValueError("MASSIVE_SELECTED_PRICE_IDENTITY_OR_COVERAGE_MISMATCH")
    if (not frame.date.eq(frame.source_id.map({key: item["date"] for key, item in by_sha.items()})).all()
            or not frame.observed_at.eq(frame.source_id.map({key: item["observed_at"] for key, item in by_sha.items()})).all()):
        raise ValueError("MASSIVE_ROW_SOURCE_DATE_OR_OBSERVED_TIME_MISMATCH")
    return frame, by_sha


def _reached_target(records, target):
    return sorted(ticker for ticker, row in records.items()
                  if row["min_date"] <= target <= row["max_date"]
                  and len(pd.read_parquet(row["path"], columns=["date"], filters=[("date", "==", target)])) == 1)


def _refresh_days(days, completed, previous, tickers):
    """A globally cached session does not prove every selected ticker is current."""
    first = max(0, days.index(completed[-1]) - 4)
    for ticker in tickers:
        record = previous.get(ticker)
        if record is None:
            first = 0
            break
        after = next((index for index, day in enumerate(days) if day > record['max_date']), len(days))
        first = min(first, max(0, after - 5))
    return days[first:]


def _publish(store, new_records, previous, output_root, receipt_root):
    """Preserve old dates and source IDs; switch only validated Massive pointers."""
    prepared, issues, leaves_by_date = [], [], {}
    for new in new_records:
        ticker = new["ticker"]
        try:
            fresh, refs = _read_record(store, new)
            old = previous.get(ticker)
            if old:
                if old["lineage"]["provider_symbol"] != new["lineage"]["provider_symbol"]:
                    raise ValueError("MASSIVE_PROVIDER_IDENTITY_CHANGED")
                prior, prior_refs = _read_record(store, old)
                if list(prior.columns) != list(fresh.columns):
                    raise ValueError("MASSIVE_SCHEMA_CHANGED")
                overlap = prior[["date", "observed_at"]].merge(fresh[["date", "observed_at"]], on="date", suffixes=("_old", "_new"))
                if (pd.to_datetime(overlap.observed_at_new, utc=True) < pd.to_datetime(overlap.observed_at_old, utc=True)).any():
                    raise ValueError("MASSIVE_OVERLAP_VINTAGE_REGRESSION")
                merged = pd.concat([prior.loc[~prior.date.isin(fresh.date)], fresh], ignore_index=True).sort_values("date").reset_index(drop=True)
                refs = {**prior_refs, **refs}
                if not set(prior.date).issubset(set(merged.date)):
                    raise ValueError("MASSIVE_OLD_HISTORY_LOSS")
                if merged.equals(prior.reset_index(drop=True)):
                    continue
            else:
                merged = fresh
            selected = [refs[value] for value in sorted(set(merged.source_id))]
            pending = {}
            for item in selected:
                leaf = {field: item[field] for field in ("path", "sha256", "date", "observed_at")}
                if item["date"] in pending or (item["date"] in leaves_by_date and leaves_by_date[item["date"]] != leaf):
                    raise ValueError("MASSIVE_CONFLICTING_RAW_VINTAGE_PER_DATE")
                pending[item["date"]] = leaf
            contract = {"ticker": ticker, "old_sha256": old["source_sha256"] if old else None,
                        "new_sha256": new["source_sha256"]}
            version = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()[:24]
            output = write_frame(output_root / "versions" / version / quote(ticker, safe="") / "daily_raw.parquet", merged)
            lineage = {key: value for key, value in new["lineage"].items() if key not in ("inputs", "inputs_manifest")}
            lineage.update(requested_start=merged.date.min(), requested_end=merged.date.max(),
                           merge_semantics="ALL_OLD_DATES_RETAINED_NEWER_OVERLAP_VINTAGE_WINS",
                           previous_price={"path": old["path"], "sha256": old["source_sha256"]} if old else None)
            prepared.append({**new, "path": output["path"], "source_sha256": output["sha256"],
                             "row_count": len(merged), "min_date": merged.date.min(), "max_date": merged.date.max(),
                             "lineage": lineage, "_sources": set(merged.source_id)})
            leaves_by_date.update(pending)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            issues.append({"ticker": ticker, "reason": str(exc)})
    if not prepared:
        return [], issues, None
    leaves = [leaves_by_date[day] for day in sorted(leaves_by_date)]
    # Read each shared raw file once, not once per stock. This preserves the
    # hash chain without re-normalizing the 500-day full-market history.
    for leaf in leaves:
        if sha256(leaf["path"]) != leaf["sha256"]:
            raise ValueError("MASSIVE_RAW_SOURCE_HASH_CHANGED")
    payload = {"schema_version": 1, "role": "RAW_INPUT_MANIFEST", "provider": massive.SOURCE, "inputs": leaves}
    content = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    digest = hashlib.sha256(content).hexdigest()
    shared = receipt_root / "shared_inputs" / ("raw_inputs_" + digest[:24] + ".json")
    shared.parent.mkdir(parents=True, exist_ok=True)
    if shared.exists() and shared.read_bytes() != content:
        raise ValueError("MASSIVE_IMMUTABLE_SHARED_INPUT_COLLISION")
    if not shared.exists():
        shared.write_bytes(content)
    indexes = {item["sha256"]: i for i, item in enumerate(leaves)}
    for record in prepared:
        record["lineage"]["inputs_manifest"] = {"path": str(shared), "sha256": digest,
            "indexes": sorted(indexes[value] for value in record.pop("_sources"))}
        # Use the real DataStore contract before making this record current.
        _read_record(store, record)
    with sqlite3.connect(store.catalog_path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for record in prepared:
            expected = previous.get(record["ticker"])
            current = connection.execute("SELECT path,source_sha256 FROM data_files WHERE dataset=? AND ticker=? AND adjustment='raw' AND is_current=1",
                                         (massive.DATASET, record["ticker"])).fetchall()
            wanted = [(expected["path"], expected["source_sha256"])] if expected else []
            if current != wanted:
                raise ValueError("MASSIVE_CURRENT_POINTER_CHANGED_DURING_REFRESH")
            register_file(connection, massive.DATASET, record["ticker"], "raw", Path(record["path"]),
                          record["row_count"], record["min_date"], record["max_date"], massive.SOURCE, record["lineage"])
    manifest = receipt_root / "current_publication.json"
    massive.write_json(manifest, {"provider": massive.SOURCE, "catalog_records": prepared,
                                  "issues": issues, "inputs_manifest": file_identity(shared)}, immutable=True)
    return prepared, issues, str(manifest)


def refresh_massive_current(paths, members, sessions, target, run_dir, progress=lambda message: None,
                            *, full_history=False):
    """Refresh only caller-selected current members, then publish native raw data.

    Cached days are reused. Requests run oldest-first with the adapter's 12.5 s
    gate and stop at its first failure (including 401/403); no permission bypass.
    The two named environment/HKCU key settings are read afresh on each call.
    """
    target = massive.checked_days([target])[0]
    days = [day for day in massive.checked_days(sessions) if day <= target]
    if not days or days[-1] != target:
        raise ValueError("MASSIVE_TARGET_NOT_IN_COMPLETED_SESSIONS")
    members = list(members)
    tickers = sorted({member["ticker"] for member in members})
    run_dir = Path(run_dir).resolve()
    store = DataStore(paths)
    store._check_data_path(run_dir, must_exist=False)
    receipt_root = run_dir / "massive"
    result = {"status": "SKIPPED_EMPTY_SCOPE", "target": target, "selected_tickers": len(tickers),
              "history_mode": "FULL_REQUESTED_RANGE" if full_history else "INCREMENTAL",
              "target_reached_tickers": [], "available_tickers": [], "cached_latest_date": None,
              "catalog_records": [], "issues": [], "network_requests_this_run": 0,
              "price_basis": "RAW", "frozen_model_eligibility": "REQUIRES_SEPARATE_BASIS_VALIDATION"}
    if not tickers:
        return result
    previous, mappings, blocked = {}, {}, set()
    for ticker in tickers:
        try:
            record = store.metadata(massive.DATASET, ticker, "raw")
            if sha256(record["path"]) != record["source_sha256"]:
                raise ValueError("MASSIVE_CACHED_PRICE_HASH_CHANGED")
            previous[ticker] = record
            item = record["lineage"].get("provider_mapping")
            if item:
                mappings[ticker] = item
        except KeyError:
            pass
        except (ValueError, OSError) as exc:
            result["issues"].append({"ticker": ticker, "reason": str(exc)})
            blocked.add(ticker)
    # Explicit member mappings can extend, but cannot silently replace, an
    # already selected provider identity. Moomoo mappings are never guessed.
    for member in members:
        if member["ticker"] in blocked:
            continue
        item = member.get("massive_mapping")
        if item is not None:
            if member["ticker"] in mappings and mappings[member["ticker"]] != item:
                raise ValueError("MASSIVE_MEMBER_MAPPING_CONFLICT")
            mappings[member["ticker"]] = item
    tickers = sorted(set(tickers) - blocked)
    if not tickers:
        result["status"] = "FAILED_LOCAL_VALIDATION"
        massive.write_json(receipt_root / "refresh_report.json", result)
        return result
    mappings = massive.provider_mapping(tickers, mappings)
    result["available_tickers"] = sorted(previous)
    result["cached_latest_date"] = max((row["max_date"] for row in previous.values()), default=None)
    result["target_reached_tickers"] = _reached_target(previous, target)
    key = load_api_key(paths, issues=result["issues"])
    if not key:
        result.update(status="API_KEY_MISSING", latest_available_date=result["cached_latest_date"])
        result["issues"].append({"reason": "MASSIVE_API_KEY_OR_POLYGON_API_KEY_NOT_CONFIGURED"})
        massive.write_json(receipt_root / "refresh_report.json", result)
        progress(f"MASSIVE：尚未配置 API key，已缓存最新日期 {result['cached_latest_date'] or '无'}。")
        return result
    root = paths.cache_root / "daily_recommendation/massive_current"
    if (root / ".writer.lock").exists():
        raise ValueError("MASSIVE_INCREMENTAL_WRITER_ALREADY_ACTIVE")
    legacy = paths.cache_root / "data_acquisition/massive_20260913"
    cached = _cached_days([legacy, root], target)
    completed = sorted(set(cached) & set(days))
    if not completed:
        result.update(status="NO_INCREMENTAL_CACHE_BASE", latest_available_date=result["cached_latest_date"])
        result["issues"].append({"reason": "NO_VERIFIED_GROUPED_CACHE_BASE_FOR_INCREMENTAL_REFRESH"})
        massive.write_json(receipt_root / "refresh_report.json", result)
        return result
    planned = list(days) if full_history else _refresh_days(days, completed, previous, tickers)
    result.update(planned_start_date=planned[0], planned_end_date=planned[-1], planned_day_count=len(planned))
    for day in planned:
        destination = root / "days" / day / "checkpoint.json"
        if day in cached and not destination.exists():
            massive.write_json(destination, cached[day][1], immutable=True)
    progress(f"MASSIVE：处理 {len(planned)} 个交易日（含缓存重叠及所选股票的缺失区间），覆盖 {len(tickers)} 支股票。")
    try:
        summary = massive.acquire(planned, tickers, key, root, symbol_map=mappings,
            output_root=paths.data_root / "providers/massive/current_incremental",
            scope_source={"selection": "CALLER_SELECTED_CURRENT_POOL", "target": target,
                          "history_mode": result["history_mode"]},
            progress=lambda item: progress(f"MASSIVE：已取得 {item['date']}（{item['completed_days']}/{item['planned_days']}）。"))
    except Exception as exc:
        # Provider exceptions can contain request arguments. Persist only the
        # exception class; the existing adapter keeps redacted day receipts.
        result.update(status="ACQUISITION_FAILED", latest_available_date=result["cached_latest_date"])
        result["issues"].append({"reason": "MASSIVE_ACQUISITION_EXCEPTION", "error_type": type(exc).__name__})
        massive.write_json(receipt_root / "refresh_report.json", result)
        return result
    finally:
        key = None
    acquisition = json.loads(Path(summary["manifest_path"]).read_text(encoding="utf-8"))
    result["issues"].extend(acquisition["contract"].get("failures", []))
    records, issues, manifest = _publish(store, acquisition["catalog_records"], previous,
        paths.data_root / "providers/massive/current_merged", receipt_root)
    result["issues"].extend(issues)
    current = {**previous, **{row["ticker"]: row for row in records}}
    result.update(catalog_records=records, manifest=manifest, acquisition_manifest=summary["manifest_path"],
        network_requests_this_run=summary["network_requests_this_run"],
        available_tickers=sorted(current), latest_available_date=max((row["max_date"] for row in current.values()), default=None),
        target_reached_tickers=_reached_target(current, target))
    result["issues"].extend({"ticker": ticker, "reason": "MASSIVE_TARGET_BAR_UNAVAILABLE"}
                            for ticker in sorted(set(tickers) - set(result["target_reached_tickers"])))
    result["status"] = "UPDATED" if len(result["target_reached_tickers"]) == result["selected_tickers"] and not result["issues"] else "PARTIAL"
    massive.write_json(receipt_root / "refresh_report.json", result)
    return result
