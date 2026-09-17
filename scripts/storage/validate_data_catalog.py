"""Read-only validation of the selected data catalog, files, and source lineage.

Integrity and date coverage are separate results. Calendar gaps are potential
gaps only: listing, delisting, suspension, identity and PIT eligibility require
their own authoritative evidence. No prices are filled or pointers changed.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.storage.storage_r2a import (DAILY_PRICE_FIELDS, DataStore, resolve_storage_paths, sha256,
                                         validate_daily_price_metadata)

PRICE_FIELDS = DAILY_PRICE_FIELDS
NUMERIC_FIELDS = ["open", "high", "low", "close", "volume"]


def catalog_snapshot(store):
    # Reuse the consumer's schema/version and ambiguity checks before direct
    # metadata-only access to the source registry and selected dataset names.
    store._catalog_rows("prices_daily")
    with sqlite3.connect(store.catalog_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        names = [row[0] for row in conn.execute("SELECT DISTINCT dataset FROM data_files WHERE is_current=1 ORDER BY dataset")]
        sources = [dict(row) for row in conn.execute("SELECT * FROM source_files ORDER BY path")]
    rows = [row for name in names for row in store._catalog_rows(name)]
    return rows, sources


def day(value):
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed.date().isoformat()


def missing_spans(missing, sessions):
    positions = {value: index for index, value in enumerate(sessions)}
    result = []
    previous = -2
    for value in missing:
        position = positions[value]
        if position != previous + 1:
            result.append({"start": value, "end": value, "sessions": 1})
        else:
            result[-1]["end"] = value
            result[-1]["sessions"] += 1
        previous = position
    return result


def calendar_coverage(dates, calendar, target):
    values = sorted({value for value in dates if value <= target})
    target_session = calendar.date_to_session(target, direction="previous").date().isoformat()
    if not values:
        return {"target_session": target_session, "target_session_present": False,
                "observed_rows_through_target": 0, "potential_internal_missing_sessions": None,
                "potential_tail_missing_sessions": None, "lifecycle_status": "UNKNOWN"}
    sessions = [stamp.date().isoformat() for stamp in calendar.sessions_in_range(values[0], target_session)]
    observed = set(values)
    internal = [value for value in sessions if value <= values[-1] and value not in observed]
    tail = [value for value in sessions if value > values[-1]]
    return {"target_session": target_session, "target_session_present": target_session in observed,
            "observed_rows_through_target": len(values), "first_observed_date": values[0],
            "last_observed_date_through_target": values[-1],
            "potential_internal_missing_sessions": len(internal),
            "potential_internal_missing_spans": missing_spans(internal, sessions),
            "potential_tail_missing_sessions": len(tail),
            "potential_tail_missing_spans": missing_spans(tail, sessions),
            "observed_non_xnys_session_dates": sorted(observed - set(sessions)),
            "lifecycle_status": "UNKNOWN", "leading_history_before_first_observation": "NOT_INFERRED"}


def validate_catalog(store, target_date):
    target = date.fromisoformat(target_date).isoformat()
    report = {"schema_version": 1, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
              "catalog": str(store.catalog_path.resolve()), "target_date": target,
              "catalog_role": "REBUILDABLE_FILE_INDEX", "files": [], "errors": [],
              "warnings": [], "model_execution_count": 0, "data_or_pointer_modified": False,
              "coverage_interpretation": "Potential XNYS session gaps; no IPO, delisting, suspension, identity, or PIT eligibility inferred."}
    try:
        rows, sources = catalog_snapshot(store)
    except (ValueError, OSError, sqlite3.DatabaseError, KeyError) as exc:
        report.update(integrity_status="FAIL", coverage_status="UNKNOWN")
        report["errors"].append({"issue": "CATALOG_UNREADABLE_OR_INVALID", "detail": str(exc)})
        return report
    catalog_identity = sha256(store.catalog_path)
    report["catalog_sha256"] = catalog_identity
    source_index = {}
    for source in sources:
        source_index.setdefault(source.get("sha256", ""), []).append(source)
    earliest = min([day(row.get("min_date")) for row in rows if day(row.get("min_date"))] + [target])
    calendar = xcals.get_calendar("XNYS", start=str((pd.Timestamp(earliest) - pd.Timedelta(days=7)).date()),
                                 end=max(target, date.today().isoformat()))
    verified_sources = {}
    shared_manifests = {}
    date_sets = {}

    def verify_source(source_path, expected):
        cache_key = (str(source_path), expected)
        if cache_key in verified_sources:
            return verified_sources[cache_key]
        errors = []
        try:
            if not Path(source_path).is_absolute():
                raise ValueError("source path is not absolute")
            path = store._check_data_path(Path(source_path))
            if not path.is_file():
                raise ValueError("source is not a regular file")
            if not re.fullmatch(r"[0-9a-f]{64}", str(expected or "")):
                raise ValueError("invalid source SHA-256")
            if sha256(path) != expected:
                raise ValueError("source file SHA-256 mismatch")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        verified_sources[cache_key] = errors
        return errors

    for index, row in enumerate(rows):
        result = {"dataset": row["dataset"], "ticker": row["ticker"], "adjustment": row["adjustment"],
                  "path": row["path"], "errors": [], "warnings": []}
        report["files"].append(result)
        path, actual_hash = None, None
        try:
            if row.get("format") not in {"parquet", "parquet_manifest"} or not Path(row["path"]).is_absolute():
                raise ValueError("catalog entry requires an absolute Parquet or manifest file path")
            path = store._check_data_path(Path(row["path"]))
            if not path.is_file():
                raise ValueError("catalog validation requires a fixed regular file")
            actual_hash = sha256(path)
            result["sha256"] = actual_hash
            if actual_hash != row.get("source_sha256"):
                result["errors"].append("SELECTED_FILE_SHA256_MISMATCH")
                continue  # Do not interpret unverified replacement bytes.
            lineage = json.loads(row.get("lineage_json") or "{}")
            if not isinstance(lineage, dict):
                raise ValueError("lineage must be an object")
            price_contract = validate_daily_price_metadata(row, lineage)
            shared_inputs = None
            if "inputs_manifest" in lineage:
                shared_inputs = store.resolve_price_inputs(row, verify_raw=False)
                reference = lineage["inputs_manifest"]
                shared_manifests[(reference["path"], reference["sha256"])] = True
                result["raw_input_manifest"] = {"path": reference["path"], "sha256": reference["sha256"],
                                                "selected_input_count": len(shared_inputs)}
            if row["format"] == "parquet_manifest":
                from scripts.storage.build_parquet_manifest import load_manifest, verify_hashes
                if price_contract is not None:
                    raise ValueError("daily-price validation requires the normalized single-file contract")
                manifest, fragments, schema = load_manifest(store, row)
                result.update(schema={field.name: str(field.type) for field in schema},
                              row_count=manifest["row_count"], min_date=manifest["min_date"],
                              max_date=manifest["max_date"], fragment_count=len(fragments),
                              validation_scope=manifest["validation_scope"],
                              completeness=manifest["completeness"])
                result["warnings"].append("FRAGMENT_FOOTER_INTEGRITY_ONLY_INTRABAR_VALUES_AND_INTERNAL_GAPS_NOT_AUDITED")
                verify_hashes(store, path, actual_hash, manifest)
                continue
            parquet = pq.ParquetFile(path)
            schema = parquet.schema_arrow
            result["schema"] = {field.name: str(field.type) for field in schema}
            result["row_count"] = parquet.metadata.num_rows
            if parquet.metadata.num_rows != row.get("row_count"):
                result["errors"].append("CATALOG_ROW_COUNT_MISMATCH")
            if price_contract is None:
                dc = lineage.get("date_column")
                if dc and dc not in schema.names:
                    result["errors"].append("DECLARED_DATE_COLUMN_MISSING")
                elif dc:
                    frame = store._read_parquet(path, None, None, [dc], dc)
                    valid = pd.to_datetime(frame[dc], errors="coerce", utc=True)
                    result["invalid_date_count"] = int((frame[dc].notna() & valid.isna()).sum())
                    result["min_date"] = day(valid.min())
                    result["max_date"] = day(valid.max())
                    if result["invalid_date_count"]:
                        result["errors"].append("INVALID_DATES")
                    if (result["min_date"], result["max_date"]) != (day(row.get("min_date")), day(row.get("max_date"))):
                        result["errors"].append("CATALOG_DATE_RANGE_MISMATCH")
                continue
            if not parquet.metadata.num_rows:
                result["errors"].append("EMPTY_SELECTED_PRICE_FILE")
            required_fields = price_contract["required_fields"]
            missing = sorted(required_fields - set(schema.names))
            if missing:
                result["errors"].append("PRICE_SCHEMA_MISSING_COLUMNS:" + ",".join(missing))
                continue
            if row["adjustment"] not in price_contract["adjustments"]:
                raise ValueError("unsupported price adjustment")
            for name in NUMERIC_FIELDS:
                dtype = schema.field(name).type
                if not (pa.types.is_floating(dtype) or pa.types.is_integer(dtype) or pa.types.is_decimal(dtype)):
                    result["errors"].append("PRICE_SCHEMA_NONNUMERIC:" + name)
            if row["dataset"] == "prices_daily_yahoo":
                dtype = schema.field("adjusted_close").type
                if not (pa.types.is_null(dtype) or pa.types.is_floating(dtype) or pa.types.is_integer(dtype) or pa.types.is_decimal(dtype)):
                    result["errors"].append("PRICE_SCHEMA_NONNUMERIC:adjusted_close")
            # Pin the path captured above. Read all rows of this price file so
            # ticker filtering cannot conceal misplaced symbols or duplicate keys.
            frame = store._read_parquet(path, None, None, sorted(required_fields), "date")
            dates = pd.to_datetime(frame.date, format="mixed", errors="coerce", utc=True)
            valid_dates = dates.dropna().dt.strftime("%Y-%m-%d")
            result.update(min_date=day(dates.min()), max_date=day(dates.max()),
                          invalid_date_count=int(dates.isna().sum()),
                          non_daily_timestamp_count=int((dates.dropna() != dates.dropna().dt.normalize()).sum()),
                          duplicate_key_rows=int(frame.assign(_day=dates.dt.strftime("%Y-%m-%d")).duplicated(
                              ["ticker", "_day", "adjustment"], keep=False).sum()))
            if result["invalid_date_count"] or result["non_daily_timestamp_count"]:
                result["errors"].append("INVALID_DAILY_DATES")
            if result["duplicate_key_rows"]:
                result["errors"].append("DUPLICATE_TICKER_DATE_ADJUSTMENT")
            if not frame.ticker.eq(row["ticker"]).all() or not frame.adjustment.eq(row["adjustment"]).all():
                result["errors"].append("CATALOG_FILE_IDENTITY_MISMATCH")
            if (result["min_date"], result["max_date"]) != (day(row.get("min_date")), day(row.get("max_date"))):
                result["errors"].append("CATALOG_DATE_RANGE_MISMATCH")
            numbers = frame[NUMERIC_FIELDS].apply(pd.to_numeric, errors="coerce")
            good = np.isfinite(numbers).all(axis=1) & (numbers[["open", "high", "low", "close"]] > 0).all(axis=1)
            good &= (numbers.volume >= 0) & (numbers.high >= numbers[["open", "close", "low"]].max(axis=1))
            good &= numbers.low <= numbers[["open", "close", "high"]].min(axis=1)
            result["invalid_ohlcv_rows"] = int((~good).sum())
            if not good.all():
                result["errors"].append("INVALID_OHLCV")
            result["providers"] = sorted(frame.source.dropna().astype(str).unique())
            result["provider_codes"] = sorted(frame.provider_code.dropna().astype(str).unique())
            if not frame.source.isin(price_contract["sources"]).all():
                result["errors"].append("UNVERIFIED_MARKET_SOURCE")
            if row["dataset"] != "prices_daily":
                if not frame.provider_code.eq(lineage["provider_symbol"]).all():
                    result["errors"].append("PROVIDER_CODE_DIFFERS_FROM_RETURNED_META_SYMBOL")
                if row["dataset"] == "prices_daily_yahoo":
                    adjusted = pd.to_numeric(frame.adjusted_close, errors="coerce")
                    present = frame.adjusted_close.notna()
                    if (present & (~np.isfinite(adjusted) | adjusted.le(0))).any():
                        result["errors"].append("INVALID_AUXILIARY_ADJUSTED_CLOSE")
                result["price_basis"] = lineage["price_basis"]
                result["vintage_semantics"] = lineage["vintage_semantics"]
            elif not frame.provider_code.fillna("").astype(str).str.fullmatch(r"US\.[A-Z0-9][A-Z0-9._/-]{0,63}").all():
                result["errors"].append("INVALID_PROVIDER_CODE")
            result["missing_observed_at_rows"] = int(pd.to_datetime(frame.observed_at, errors="coerce", utc=True).isna().sum())
            if row["dataset"] != "prices_daily":
                observed_type = schema.field("observed_at").type
                aware = pa.types.is_timestamp(observed_type) and observed_type.tz is not None
                if pa.types.is_string(observed_type) or pa.types.is_large_string(observed_type):
                    aware = frame.observed_at.dropna().astype(str).str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True).all()
                if not aware:
                    result["errors"].append(price_contract["retrieval_prefix"] + "_RETRIEVAL_TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE")
            if result["missing_observed_at_rows"]:
                result["warnings"].append("SOURCE_AVAILABILITY_TIME_UNKNOWN")
                if row["dataset"] != "prices_daily":
                    result["errors"].append(price_contract["retrieval_prefix"] + "_RETRIEVAL_TIMESTAMP_MISSING_OR_INVALID")
            source_ids = set(frame.source_id.dropna().astype(str))
            inputs = shared_inputs if shared_inputs is not None else store.resolve_price_inputs(row, verify_raw=False)
            input_ids = {item.get("sha256", "") for item in inputs}
            result["source_id_count"] = len(source_ids)
            if frame.source_id.isna().any() or source_ids != input_ids:
                result["errors"].append("ROW_SOURCE_ID_LINEAGE_MISMATCH")
            if shared_inputs is not None:
                input_dates = {item["sha256"]: item["date"] for item in inputs}
                input_observations = {item["sha256"]: item["observed_at"] for item in inputs}
                if not frame.source_id.map(input_dates).eq(dates.dt.strftime("%Y-%m-%d")).all():
                    result["errors"].append("ROW_SOURCE_DATE_LINEAGE_MISMATCH")
                expected_observations = pd.to_datetime(frame.source_id.map(input_observations), errors="coerce", utc=True, format="mixed")
                observations = pd.to_datetime(frame.observed_at, errors="coerce", utc=True, format="mixed")
                if not observations.eq(expected_observations).all():
                    result["errors"].append("ROW_SOURCE_OBSERVATION_LINEAGE_MISMATCH")
            for entry in inputs:
                sid, source_path = entry.get("sha256", ""), entry.get("path", "")
                registered = source_index.get(sid, [])
                exact = [source for source in registered if source.get("path") == source_path]
                if not exact or any(source.get("status") == "REJECTED" for source in exact):
                    result["errors"].append("SOURCE_ID_NOT_IN_VALID_SOURCE_REGISTRY:" + sid)
                for error in verify_source(source_path, sid):
                    result["errors"].append("SOURCE_LINEAGE_INVALID:" + error + ":" + str(source_path))
            result["coverage"] = calendar_coverage(valid_dates, calendar, target)
            if result["coverage"].get("observed_non_xnys_session_dates"):
                result["warnings"].append("OBSERVED_DATE_OUTSIDE_XNYS_CALENDAR")
            result["rows_after_target"] = int((valid_dates > target).sum())
            if row["dataset"] == "prices_daily":
                date_sets[(row["ticker"], row["adjustment"])] = set(valid_dates[valid_dates <= target])
        except (OSError, ValueError, KeyError, TypeError, pa.ArrowException) as exc:
            result["errors"].append("FILE_VALIDATION_FAILED:" + str(exc))
        finally:
            if path is not None and actual_hash is not None:
                try:
                    if sha256(path) != actual_hash:
                        result["errors"].append("SELECTED_FILE_CHANGED_DURING_VALIDATION")
                except OSError as exc:
                    result["errors"].append("SELECTED_FILE_RECHECK_FAILED:" + str(exc))
        if index % 200 == 0:
            print(f"validated {index + 1}/{len(rows)} catalog files", flush=True)
    report["adjustments"] = {}
    for adjustment in ("raw", "qfq"):
        files = [item for item in report["files"] if item["dataset"] == "prices_daily" and item["adjustment"] == adjustment]
        coverages = [item["coverage"] for item in files if "coverage" in item]
        report["adjustments"][adjustment] = {
            "selected_files": len(files), "validated_coverage_files": len(coverages),
            "rows": sum(item.get("row_count", 0) for item in files),
            "target_session_present": sum(item["target_session_present"] for item in coverages),
            "potential_internal_missing_sessions": sum(item.get("potential_internal_missing_sessions") or 0 for item in coverages),
            "potential_tail_missing_sessions": sum(item.get("potential_tail_missing_sessions") or 0 for item in coverages)}
    report["supplemental_price_datasets"] = {}
    for name in sorted({item["dataset"] for item in report["files"] if item["dataset"].startswith("prices_daily_")}):
        files = [item for item in report["files"] if item["dataset"] == name]
        coverages = [item["coverage"] for item in files if "coverage" in item]
        report["supplemental_price_datasets"][name] = {
            "selected_files": len(files), "rows": sum(item.get("row_count", 0) for item in files),
            "validated_coverage_files": len(coverages),
            "target_session_present": sum(item["target_session_present"] for item in coverages),
            "potential_internal_missing_sessions": sum(item.get("potential_internal_missing_sessions") or 0 for item in coverages),
            "potential_tail_missing_sessions": sum(item.get("potential_tail_missing_sessions") or 0 for item in coverages),
            "scope": "EXPLICIT_PROVIDER_ONLY_NOT_A_REPLACEMENT_FOR_MOOMOO_OR_PIT_ACCEPTANCE"}
    report["raw_qfq_differences"] = []
    all_sessions = [stamp.date().isoformat() for stamp in calendar.sessions]
    all_session_set = set(all_sessions)
    for ticker in sorted({key[0] for key in date_sets}):
        raw, qfq = date_sets.get((ticker, "raw")), date_sets.get((ticker, "qfq"))
        if raw is None or qfq is None or raw != qfq:
            raw_only, qfq_only = (raw or set()) - (qfq or set()), (qfq or set()) - (raw or set())
            report["raw_qfq_differences"].append({"ticker": ticker, "raw_leg_present": raw is not None,
                "qfq_leg_present": qfq is not None, "raw_only_date_count": len(raw_only),
                "qfq_only_date_count": len(qfq_only),
                "raw_only_session_spans": missing_spans(sorted(raw_only & all_session_set), all_sessions),
                "qfq_only_session_spans": missing_spans(sorted(qfq_only & all_session_set), all_sessions),
                "non_session_differences": sorted((raw_only | qfq_only) - all_session_set)})
    report["referenced_source_files_checked"] = len(verified_sources)
    report["shared_raw_input_manifests_checked"] = len(shared_manifests)
    for (manifest_path, expected) in shared_manifests:
        try:
            path = store._check_data_path(Path(manifest_path))
            if sha256(path) != expected:
                raise ValueError("shared raw-input manifest changed during validation")
        except (OSError, ValueError) as exc:
            report["errors"].append({"issue": "RAW_INPUT_MANIFEST_RECHECK_FAILED", "path": manifest_path, "detail": str(exc)})
    try:
        after, _ = catalog_snapshot(store)
        if rows != after or sha256(store.catalog_path) != catalog_identity:
            report["errors"].append({"issue": "CATALOG_CHANGED_DURING_VALIDATION"})
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        report["errors"].append({"issue": "CATALOG_RECHECK_FAILED", "detail": str(exc)})
    report["failed_file_count"] = sum(bool(item["errors"]) for item in report["files"])
    if not any(item["dataset"] == "prices_daily" for item in report["files"]):
        report["errors"].append({"issue": "NO_SELECTED_PRICE_FILES"})
    report["integrity_status"] = "FAIL" if report["errors"] or report["failed_file_count"] else "PASS"
    coverage_ok = all(value["selected_files"] > 0 and value["selected_files"] == value["target_session_present"]
                      and value["potential_internal_missing_sessions"] == 0 for value in report["adjustments"].values())
    coverage_ok = coverage_ok and not report["raw_qfq_differences"]
    report["coverage_status"] = "OBSERVED_SESSIONS_COVERED_LIFECYCLE_UNVERIFIED" if coverage_ok else "POTENTIAL_GAPS_REQUIRING_LIFECYCLE_REVIEW"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--data-root"); parser.add_argument("--cache-root"); parser.add_argument("--results-root")
    parser.add_argument("--target-date", default="2026-09-11")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.suffix.lower() != ".json":
        parser.error("--report must name a JSON report file")
    paths = resolve_storage_paths(data_root=args.data_root, cache_root=args.cache_root, results_root=args.results_root)
    report = validate_catalog(DataStore(paths, args.catalog), args.target_date)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("integrity_status", "coverage_status", "catalog", "target_date")}, indent=2))
    return 0 if report["integrity_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
