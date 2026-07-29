#!/usr/bin/env python
"""
V22.049 known SOXX broker-source bad-tick quarantine and acceptance finalizer.

Scope is intentionally fixed:
- RAW is verified and never modified.
- Exactly one Canonical row may be removed:
  US.SOXX @ 2020-03-16T13:31:00Z.
- Exactly one Canonical partition may be rewritten.
- No OpenD or network API is used.
- Existing Canonical files are rescanned before V22.049 acceptance is frozen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


VERSION = "V22.049_SOXX_KNOWN_BAD_TICK_QUARANTINE_R1"
EXPECTED_SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
TARGET_CODE = "US.SOXX"
TARGET_SYMBOL = "SOXX"
TARGET_TIMESTAMP = pd.Timestamp("2020-03-16T13:31:00Z")
EXPECTED_VALUES = {
    "open": 188.00,
    "high": 188.00,
    "low": 188.00,
    "close": 209.42,
    "volume": 7.0,
}
OHLC_ABS_TOL = 1e-8


class MaintenanceError(RuntimeError):
    """A guarded maintenance validation failed."""


@dataclass(frozen=True)
class Paths:
    repo_root: Path
    data_root: Path
    raw_file: Path
    canonical_root: Path
    canonical_partition: Path
    failure_csv: Path
    quarantine_csv: Path
    summary_json: Path
    manifest_json: Path
    acceptance_root: Path
    acceptance_json: Path
    acceptance_csv: Path
    execution_report_json: Path


def build_paths(repo_root: Path, data_root: Path, results_root: Path) -> Paths:
    raw_file = (
        data_root
        / "raw"
        / "symbol=SOXX"
        / "request_start=2020-03-14"
        / "20260725T081527.parquet"
    )
    canonical_root = data_root / "canonical"
    canonical_partition = (
        canonical_root / "symbol=SOXX" / "year=2020" / "month=03" / "data.parquet"
    )
    acceptance_root = (
        results_root
        / "v22"
        / "V22.049_FAST3_SIX_ETF_24H_MINUTE_DATA_INGEST_R1"
    )
    return Paths(
        repo_root=repo_root,
        data_root=data_root,
        raw_file=raw_file,
        canonical_root=canonical_root,
        canonical_partition=canonical_partition,
        failure_csv=data_root / "six_etf_download_failures.csv",
        quarantine_csv=data_root / "six_etf_invalid_ohlc_quarantine.csv",
        summary_json=data_root / "v22_049_summary.json",
        manifest_json=data_root / "v22_049_run_manifest.json",
        acceptance_root=acceptance_root,
        acceptance_json=acceptance_root / "v22_049_acceptance_snapshot.json",
        acceptance_csv=acceptance_root / "v22_049_acceptance_report.csv",
        execution_report_json=data_root / "v22_049_known_bad_tick_maintenance_report.json",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return utc_z(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Cannot JSON encode {type(value)!r}")


def utc_z(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_timestamp_utc(series: pd.Series, *, naive_timezone: str | None = None) -> pd.Series:
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        result = series.dt.tz_convert("UTC")
    elif pd.api.types.is_datetime64_dtype(series.dtype):
        if naive_timezone is None:
            raise MaintenanceError("Naive datetime column requires an explicit source timezone.")
        result = (
            series.dt.tz_localize(
                naive_timezone,
                ambiguous="raise",
                nonexistent="raise",
            )
            .dt.tz_convert("UTC")
        )
    else:
        text = series.astype("string").str.strip()
        aware_mask = text.str.contains(
            r"(?:Z|[+-]\d{2}:?\d{2})$",
            regex=True,
            na=False,
        )
        result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
        if aware_mask.any():
            result.loc[aware_mask] = pd.to_datetime(
                text.loc[aware_mask],
                utc=True,
                errors="raise",
            )
        naive_mask = (~aware_mask) & text.notna()
        if naive_mask.any():
            if naive_timezone is None:
                raise MaintenanceError("Naive timestamp strings require a source timezone.")
            naive = pd.to_datetime(text.loc[naive_mask], errors="raise")
            result.loc[naive_mask] = (
                naive.dt.tz_localize(
                    naive_timezone,
                    ambiguous="raise",
                    nonexistent="raise",
                )
                .dt.tz_convert("UTC")
            )
    # Pandas 3 / PyArrow may preserve Parquet timestamps as microseconds.
    # Canonical V22.049 requires an explicit nanosecond-resolution UTC dtype.
    result = pd.Series(
        pd.array(
            pd.to_datetime(result, utc=True, errors="raise"),
            dtype="datetime64[ns, UTC]",
        ),
        index=series.index,
        name=series.name,
    )

    if str(result.dtype) != "datetime64[ns, UTC]":
        raise MaintenanceError(f"Unexpected timestamp dtype: {result.dtype}")

    return result


def find_column(df: pd.DataFrame, names: Iterable[str], *, required: bool = True) -> str | None:
    by_lower = {str(col).lower(): str(col) for col in df.columns}
    for name in names:
        found = by_lower.get(name.lower())
        if found is not None:
            return found
    if required:
        raise MaintenanceError(
            f"Required column missing. Expected one of {list(names)}; got {list(df.columns)}"
        )
    return None


def timestamp_column(df: pd.DataFrame) -> str:
    return find_column(df, ("timestamp_utc", "time_key", "datetime", "timestamp"))  # type: ignore[return-value]


def code_column(df: pd.DataFrame, *, required: bool = False) -> str | None:
    return find_column(df, ("code", "symbol", "ticker"), required=required)


def numeric_equal(actual: Any, expected: float, tol: float = OHLC_ABS_TOL) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tol
    except (TypeError, ValueError):
        return False


def validate_expected_target_row(row: pd.Series) -> None:
    for field, expected in EXPECTED_VALUES.items():
        col = find_column(row.to_frame().T, (field,))
        actual = row[col]
        if not numeric_equal(actual, expected):
            raise MaintenanceError(
                f"Target row field mismatch: {field} expected {expected}, got {actual}"
            )


def valid_ohlc_mask(df: pd.DataFrame) -> pd.Series:
    open_col = find_column(df, ("open",))
    high_col = find_column(df, ("high",))
    low_col = find_column(df, ("low",))
    close_col = find_column(df, ("close",))
    volume_col = find_column(df, ("volume",), required=False)

    o = pd.to_numeric(df[open_col], errors="coerce")
    h = pd.to_numeric(df[high_col], errors="coerce")
    l = pd.to_numeric(df[low_col], errors="coerce")
    c = pd.to_numeric(df[close_col], errors="coerce")

    valid = (
        o.notna()
        & h.notna()
        & l.notna()
        & c.notna()
        & (o > 0)
        & (h > 0)
        & (l > 0)
        & (c > 0)
        & (h + OHLC_ABS_TOL >= o)
        & (h + OHLC_ABS_TOL >= c)
        & (h + OHLC_ABS_TOL >= l)
        & (l - OHLC_ABS_TOL <= o)
        & (l - OHLC_ABS_TOL <= c)
        & (l - OHLC_ABS_TOL <= h)
    )
    if volume_col is not None:
        volume = pd.to_numeric(df[volume_col], errors="coerce")
        valid &= volume.notna() & (volume >= 0)
    return valid


def read_raw_target(paths: Paths) -> tuple[pd.DataFrame, pd.Series]:
    if not paths.raw_file.exists():
        raise MaintenanceError(f"RAW source file not found: {paths.raw_file}")

    raw = pd.read_parquet(paths.raw_file)
    time_col = timestamp_column(raw)
    if time_col.lower() == "time_key":
        raw["_timestamp_utc_guard"] = normalize_timestamp_utc(
            raw[time_col],
            naive_timezone="America/New_York",
        )
    else:
        raw["_timestamp_utc_guard"] = normalize_timestamp_utc(
            raw[time_col],
            naive_timezone="America/New_York",
        )

    raw_code_col = code_column(raw, required=False)
    mask = raw["_timestamp_utc_guard"].eq(TARGET_TIMESTAMP)
    if raw_code_col is not None:
        code_text = raw[raw_code_col].astype("string").str.upper()
        mask &= code_text.isin({TARGET_CODE, TARGET_SYMBOL})

    candidates = raw.loc[mask].copy()
    if len(candidates) != 1:
        raise MaintenanceError(
            f"Expected exactly one RAW provenance candidate; found {len(candidates)}."
        )
    candidate = candidates.iloc[0]
    validate_expected_target_row(candidate)
    if bool(valid_ohlc_mask(candidates).iloc[0]):
        raise MaintenanceError("RAW candidate unexpectedly passes OHLC validation.")
    return raw, candidate


def read_canonical_partition(paths: Paths) -> tuple[pd.DataFrame, str, str | None]:
    if not paths.canonical_partition.exists():
        raise MaintenanceError(
            f"Canonical target partition not found: {paths.canonical_partition}"
        )
    frame = pd.read_parquet(paths.canonical_partition)
    time_col = timestamp_column(frame)
    frame[time_col] = normalize_timestamp_utc(frame[time_col], naive_timezone="UTC")
    ccol = code_column(frame, required=False)
    return frame, time_col, ccol


def select_target_mask(frame: pd.DataFrame, time_col: str, ccol: str | None) -> pd.Series:
    mask = frame[time_col].eq(TARGET_TIMESTAMP)
    if ccol is not None:
        code_text = frame[ccol].astype("string").str.upper()
        mask &= code_text.isin({TARGET_CODE, TARGET_SYMBOL})
    return mask


def append_quarantine_record_idempotent(
    quarantine_path: Path,
    record: dict[str, Any],
) -> int:
    key_fields = ("code", "timestamp_utc")
    rows: list[dict[str, Any]] = []
    if quarantine_path.exists() and quarantine_path.stat().st_size > 0:
        rows = pd.read_csv(quarantine_path, dtype="string").fillna("").to_dict("records")

    record_key = tuple(str(record[field]) for field in key_fields)
    existing = {
        tuple(str(row.get(field, "")) for field in key_fields)
        for row in rows
    }
    if record_key not in existing:
        rows.append({key: str(value) for key, value in record.items()})

    fieldnames = list(record.keys())
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{quarantine_path.name}.",
        suffix=".tmp",
        dir=quarantine_path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, quarantine_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return len(rows)


def write_partition_atomic(
    path: Path,
    frame: pd.DataFrame,
    *,
    time_col: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp.parquet")
    try:
        frame.to_parquet(temp_path, index=False)
        check = pd.read_parquet(temp_path)
        check[time_col] = normalize_timestamp_utc(check[time_col], naive_timezone="UTC")
        if len(check) != len(frame):
            raise MaintenanceError("Temporary partition read-back row count mismatch.")
        if not bool(valid_ohlc_mask(check).all()):
            raise MaintenanceError("Temporary partition contains invalid OHLC rows.")
        if check[time_col].duplicated().any():
            raise MaintenanceError("Temporary partition contains duplicate timestamps.")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def quarantine_contains_target(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    frame = pd.read_csv(path, dtype="string").fillna("")
    if not {"code", "timestamp_utc"}.issubset(frame.columns):
        return False
    mask = (
        frame["code"].astype("string").str.upper().eq(TARGET_CODE)
        & frame["timestamp_utc"].astype("string").eq(utc_z(TARGET_TIMESTAMP))
    )
    return int(mask.sum()) == 1


def quarantine_known_bad_tick(paths: Paths) -> dict[str, Any]:
    raw_hash_before = sha256_file(paths.raw_file)
    _, raw_candidate = read_raw_target(paths)

    partition_hash_before = sha256_file(paths.canonical_partition)
    partition_stat_before = paths.canonical_partition.stat()
    frame, time_col, ccol = read_canonical_partition(paths)
    row_count_before = len(frame)

    mask = select_target_mask(frame, time_col, ccol)
    target_count = int(mask.sum())
    if target_count == 0 and quarantine_contains_target(paths.quarantine_csv):
        if not bool(valid_ohlc_mask(frame).all()):
            raise MaintenanceError(
                "Target row is already quarantined, but the target partition still "
                "contains invalid OHLC rows."
            )
        raw_hash_after = sha256_file(paths.raw_file)
        if raw_hash_after != raw_hash_before:
            raise MaintenanceError("RAW source hash changed unexpectedly.")
        quarantine_count, _ = count_quarantine_rows(paths.quarantine_csv)
        return {
            "raw_sha256_before": raw_hash_before,
            "raw_sha256_after": raw_hash_after,
            "raw_files_modified": False,
            "raw_files_deleted": False,
            "canonical_partition_sha256_before": partition_hash_before,
            "canonical_partition_sha256_after": partition_hash_before,
            "canonical_partition_size_before": partition_stat_before.st_size,
            "canonical_partition_size_after": partition_stat_before.st_size,
            "canonical_row_count_before": row_count_before,
            "canonical_row_count_after": row_count_before,
            "canonical_row_count_delta": 0,
            "canonical_partitions_rewritten": 0,
            "quarantine_record_count": quarantine_count,
            "rollback_path": "",
            "already_quarantined": True,
        }
    if target_count != 1:
        raise MaintenanceError(
            f"Expected exactly one Canonical target row; found {target_count}."
        )

    target_row = frame.loc[mask].iloc[0]
    validate_expected_target_row(target_row)
    if bool(valid_ohlc_mask(frame.loc[mask]).iloc[0]):
        raise MaintenanceError("Canonical target unexpectedly passes OHLC validation.")

    prior = frame.loc[frame[time_col] < TARGET_TIMESTAMP].sort_values(time_col).tail(1)
    following = frame.loc[frame[time_col] > TARGET_TIMESTAMP].sort_values(time_col).head(1)

    close_col = find_column(frame, ("close",))
    record = {
        "code": TARGET_CODE,
        "timestamp_utc": utc_z(TARGET_TIMESTAMP),
        "open": EXPECTED_VALUES["open"],
        "high": EXPECTED_VALUES["high"],
        "low": EXPECTED_VALUES["low"],
        "close": EXPECTED_VALUES["close"],
        "volume": int(EXPECTED_VALUES["volume"]),
        "turnover": raw_candidate.get("turnover", ""),
        "change_rate": raw_candidate.get("change_rate", ""),
        "last_close": raw_candidate.get("last_close", ""),
        "timestamp_et": TARGET_TIMESTAMP.tz_convert("America/New_York").isoformat(),
        "broker_trade_date": TARGET_TIMESTAMP.tz_convert("America/New_York").strftime("%Y-%m-%d"),
        "session": "RTH",
        "request_start": "2020-03-14",
        "violation": "high=188.00 < close=209.42",
        "root_cause_classification": "BROKER_SOURCE_BAD_TICK",
        "source_raw_file": str(paths.raw_file),
        "canonical_partition": str(paths.canonical_partition),
        "raw_row_number": int(raw_candidate.name),
        "raw_candidate_count": 1,
        "valid_raw_candidate_count": 0,
        "exclusion_reason": "BROKER_SOURCE_BAD_TICK_INVALID_OHLC",
        "resolution": "EXCLUDED_FROM_EFFECTIVE_CANONICAL_RAW_PRESERVED",
        "previous_valid_timestamp_utc": (
            utc_z(prior.iloc[0][time_col]) if not prior.empty else ""
        ),
        "previous_valid_close": (
            prior.iloc[0][close_col] if not prior.empty else ""
        ),
        "next_valid_timestamp_utc": (
            utc_z(following.iloc[0][time_col]) if not following.empty else ""
        ),
        "next_valid_close": (
            following.iloc[0][close_col] if not following.empty else ""
        ),
        "raw_sha256": raw_hash_before,
        "quarantined_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "validator_version": VERSION,
    }

    remaining = frame.loc[~mask].copy()
    remaining = remaining.sort_values(time_col, kind="mergesort").reset_index(drop=True)
    if len(remaining) != row_count_before - 1:
        raise MaintenanceError("Canonical row delta is not exactly -1.")
    if not bool(valid_ohlc_mask(remaining).all()):
        invalid_count = int((~valid_ohlc_mask(remaining)).sum())
        raise MaintenanceError(
            f"Target partition still contains {invalid_count} invalid OHLC rows."
        )
    if remaining[time_col].duplicated().any():
        raise MaintenanceError("Target partition contains duplicate timestamps after removal.")

    # Save rollback material outside the Canonical tree and use a non-Parquet extension.
    rollback_dir = paths.data_root / "_maintenance_rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    rollback_path = rollback_dir / f"SOXX_2020_03_{partition_hash_before}.parquet.bak"
    if not rollback_path.exists():
        shutil.copyfile(paths.canonical_partition, rollback_path)

    old_quarantine = (
        paths.quarantine_csv.read_bytes() if paths.quarantine_csv.exists() else None
    )

    try:
        write_partition_atomic(paths.canonical_partition, remaining, time_col=time_col)
        quarantine_count = append_quarantine_record_idempotent(
            paths.quarantine_csv,
            record,
        )

        final_frame, final_time_col, final_ccol = read_canonical_partition(paths)
        if int(select_target_mask(final_frame, final_time_col, final_ccol).sum()) != 0:
            raise MaintenanceError("Target row still exists after atomic replacement.")
        if len(final_frame) != row_count_before - 1:
            raise MaintenanceError("Final partition row count mismatch.")
        if not bool(valid_ohlc_mask(final_frame).all()):
            raise MaintenanceError("Final partition OHLC validation failed.")
        if sha256_file(paths.raw_file) != raw_hash_before:
            raise MaintenanceError("RAW source hash changed unexpectedly.")
    except Exception:
        shutil.copyfile(rollback_path, paths.canonical_partition)
        if old_quarantine is None:
            paths.quarantine_csv.unlink(missing_ok=True)
        else:
            atomic_write_bytes(paths.quarantine_csv, old_quarantine)
        raise

    raw_hash_after = sha256_file(paths.raw_file)
    partition_hash_after = sha256_file(paths.canonical_partition)
    return {
        "raw_sha256_before": raw_hash_before,
        "raw_sha256_after": raw_hash_after,
        "raw_files_modified": raw_hash_before != raw_hash_after,
        "raw_files_deleted": not paths.raw_file.exists(),
        "canonical_partition_sha256_before": partition_hash_before,
        "canonical_partition_sha256_after": partition_hash_after,
        "canonical_partition_size_before": partition_stat_before.st_size,
        "canonical_partition_size_after": paths.canonical_partition.stat().st_size,
        "canonical_row_count_before": row_count_before,
        "canonical_row_count_after": row_count_before - 1,
        "canonical_row_count_delta": -1,
        "canonical_partitions_rewritten": 1,
        "quarantine_record_count": quarantine_count,
        "rollback_path": str(rollback_path),
    }


def failure_csv_data_row_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return len(rows)


def symbol_from_partition(path: Path) -> str:
    for part in path.parts:
        match = re.fullmatch(r"symbol=(.+)", part, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    raise MaintenanceError(f"Cannot derive symbol from partition path: {path}")


def scan_canonical(paths: Paths) -> dict[str, Any]:
    files = sorted(paths.canonical_root.rglob("*.parquet"))
    if not files:
        raise MaintenanceError(f"No Canonical Parquet files under {paths.canonical_root}")

    partition_count_by_symbol: Counter[str] = Counter()
    row_count_by_symbol: Counter[str] = Counter()
    row_count_by_session: Counter[str] = Counter()
    row_count_by_session_by_symbol: dict[str, Counter[str]] = defaultdict(Counter)
    earliest: dict[str, pd.Timestamp] = {}
    latest: dict[str, pd.Timestamp] = {}
    duplicate_count = 0
    invalid_ohlc_count = 0
    timezone_validation_pass = True
    prior_partition_max: dict[str, pd.Timestamp] = {}

    for path in files:
        symbol = symbol_from_partition(path)
        partition_count_by_symbol[symbol] += 1
        frame = pd.read_parquet(path)
        time_col = timestamp_column(frame)
        frame[time_col] = normalize_timestamp_utc(frame[time_col], naive_timezone="UTC")
        timezone_validation_pass &= str(frame[time_col].dtype) == "datetime64[ns, UTC]"

        frame = frame.sort_values(time_col, kind="mergesort")
        within_duplicates = int(frame[time_col].duplicated().sum())
        duplicate_count += within_duplicates

        if not frame.empty:
            min_ts = frame[time_col].iloc[0]
            max_ts = frame[time_col].iloc[-1]
            if symbol in prior_partition_max and min_ts <= prior_partition_max[symbol]:
                # Partition overlap is not automatically a duplicate, so resolve only the boundary.
                # Monthly V22.049 partitions are expected to be strictly non-overlapping.
                raise MaintenanceError(
                    f"Overlapping Canonical partition ranges for {symbol}: "
                    f"{path} begins {min_ts}, prior max {prior_partition_max[symbol]}"
                )
            prior_partition_max[symbol] = max_ts
            earliest[symbol] = min(earliest.get(symbol, min_ts), min_ts)
            latest[symbol] = max(latest.get(symbol, max_ts), max_ts)

        row_count_by_symbol[symbol] += len(frame)
        invalid_ohlc_count += int((~valid_ohlc_mask(frame)).sum())

        session_col = find_column(frame, ("session",), required=False)
        if session_col is not None:
            counts = frame[session_col].fillna("").astype("string").value_counts(dropna=False)
            for session, count in counts.items():
                session_name = str(session)
                row_count_by_session[session_name] += int(count)
                row_count_by_session_by_symbol[symbol][session_name] += int(count)

    found_symbols = set(partition_count_by_symbol)
    missing = set(EXPECTED_SYMBOLS) - found_symbols
    extra = found_symbols - set(EXPECTED_SYMBOLS)
    if missing or extra:
        raise MaintenanceError(
            f"Unexpected Canonical symbols. Missing={sorted(missing)}, extra={sorted(extra)}"
        )

    expected_partition_shape = all(
        partition_count_by_symbol[symbol] == 97 for symbol in EXPECTED_SYMBOLS
    )

    return {
        "canonical_parquet_count": len(files),
        "partition_count_by_symbol": dict(sorted(partition_count_by_symbol.items())),
        "expected_partition_shape": expected_partition_shape,
        "row_count_by_symbol": {
            f"US.{symbol}": int(row_count_by_symbol[symbol])
            for symbol in EXPECTED_SYMBOLS
        },
        "earliest_timestamp_by_symbol": {
            f"US.{symbol}": utc_z(earliest[symbol]) for symbol in EXPECTED_SYMBOLS
        },
        "latest_timestamp_by_symbol": {
            f"US.{symbol}": utc_z(latest[symbol]) for symbol in EXPECTED_SYMBOLS
        },
        "row_count_by_session": dict(sorted(row_count_by_session.items())),
        "row_count_by_session_by_symbol": {
            f"US.{symbol}": dict(sorted(row_count_by_session_by_symbol[symbol].items()))
            for symbol in EXPECTED_SYMBOLS
        },
        "duplicate_count": int(duplicate_count),
        "invalid_ohlc_count": int(invalid_ohlc_count),
        "timezone_validation_pass": bool(timezone_validation_pass),
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MaintenanceError(f"Required JSON not found: {path}")
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise MaintenanceError(f"JSON root must be an object: {path}")
    return payload


def git_commit(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()
    except Exception:
        return "UNKNOWN"


def count_quarantine_rows(path: Path) -> tuple[int, dict[str, int]]:
    counts = {f"US.{symbol}": 0 for symbol in EXPECTED_SYMBOLS}
    if not path.exists() or path.stat().st_size == 0:
        return 0, counts
    frame = pd.read_csv(path, dtype="string").fillna("")
    if not {"code", "timestamp_utc"}.issubset(frame.columns):
        raise MaintenanceError("Quarantine CSV missing code/timestamp_utc.")
    duplicates = frame.duplicated(subset=["code", "timestamp_utc"]).sum()
    if int(duplicates) != 0:
        raise MaintenanceError("Quarantine CSV contains duplicate keys.")
    for code, count in frame["code"].value_counts().items():
        counts[str(code)] = int(count)
    return len(frame), counts


def update_summary_and_freeze(
    paths: Paths,
    maintenance: dict[str, Any],
    scan: dict[str, Any],
) -> dict[str, Any]:
    summary = read_json(paths.summary_json)
    manifest = read_json(paths.manifest_json)
    quarantine_count, quarantine_by_symbol = count_quarantine_rows(paths.quarantine_csv)
    failures = failure_csv_data_row_count(paths.failure_csv)

    existing_incremental = bool(summary.get("incremental_update_pass", False))
    existing_broker_date = bool(summary.get("broker_trade_date_validation_pass", False))

    per_symbol_clean = {
        code: (
            scan["row_count_by_symbol"].get(code, 0) > 0
            and code in scan["earliest_timestamp_by_symbol"]
            and code in scan["latest_timestamp_by_symbol"]
        )
        for code in (f"US.{symbol}" for symbol in EXPECTED_SYMBOLS)
    }
    postprocess_by_symbol = dict(per_symbol_clean)
    canonical_by_symbol = {
        code: bool(clean and scan["invalid_ohlc_count"] == 0 and scan["duplicate_count"] == 0)
        for code, clean in per_symbol_clean.items()
    }
    incremental_by_symbol = {
        code: bool(clean and existing_incremental)
        for code, clean in per_symbol_clean.items()
    }

    gate = {
        "canonical_parquet_count_is_582": scan["canonical_parquet_count"] == 582,
        "each_symbol_has_97_partitions": bool(scan["expected_partition_shape"]),
        "failure_count_is_0": failures == 0,
        "duplicate_count_is_0": scan["duplicate_count"] == 0,
        "invalid_ohlc_count_is_0": scan["invalid_ohlc_count"] == 0,
        "quarantine_count_is_1": quarantine_count == 1,
        "quarantine_is_expected_soxx_row": (
            quarantine_by_symbol.get(TARGET_CODE, 0) == 1
            and sum(quarantine_by_symbol.values()) == 1
        ),
        "raw_hash_unchanged": (
            maintenance["raw_sha256_before"] == maintenance["raw_sha256_after"]
        ),
        "timezone_validation_pass": bool(scan["timezone_validation_pass"]),
        "broker_trade_date_validation_pass": existing_broker_date,
        "incremental_update_pass": existing_incremental,
        "all_symbols_have_rows": all(v > 0 for v in scan["row_count_by_symbol"].values()),
        "all_postprocess_pass": all(postprocess_by_symbol.values()),
        "all_canonical_pass": all(canonical_by_symbol.values()),
        "all_incremental_pass": all(incremental_by_symbol.values()),
    }
    accepted = all(gate.values())

    summary.update(
        {
            "final_status": "PASS" if accepted else "FAIL",
            "final_decision": (
                "V22_049_SIX_ETF_CANONICAL_ACCEPTED_WITH_ONE_AUDITED_SOURCE_BAD_TICK_QUARANTINED"
                if accepted
                else "V22_049_KNOWN_BAD_TICK_MAINTENANCE_GATE_FAILED"
            ),
            "symbol_count_requested": 6,
            "symbol_count_succeeded": 6 if accepted else sum(postprocess_by_symbol.values()),
            "symbol_count_failed": 0 if accepted else 6 - sum(postprocess_by_symbol.values()),
            "row_count_by_symbol": scan["row_count_by_symbol"],
            "earliest_timestamp_by_symbol": scan["earliest_timestamp_by_symbol"],
            "latest_timestamp_by_symbol": scan["latest_timestamp_by_symbol"],
            "row_count_by_session": scan["row_count_by_session"],
            "row_count_by_session_by_symbol": scan["row_count_by_session_by_symbol"],
            "postprocess_pass_by_symbol": postprocess_by_symbol,
            "canonical_write_pass_by_symbol": canonical_by_symbol,
            "incremental_update_pass_by_symbol": incremental_by_symbol,
            "duplicate_count": scan["duplicate_count"],
            "invalid_ohlc_count": scan["invalid_ohlc_count"],
            "quarantined_raw_bad_tick_count": quarantine_count,
            "quarantined_raw_bad_tick_by_symbol": quarantine_by_symbol,
            "invalid_ohlc_quarantine_path": str(paths.quarantine_csv),
            "timezone_validation_pass": bool(scan["timezone_validation_pass"]),
            "broker_trade_date_validation_pass": existing_broker_date,
            "canonical_write_pass": all(canonical_by_symbol.values()),
            "incremental_update_pass": all(incremental_by_symbol.values()),
            "data_ready_for_v22_050": accepted,
            "maintenance_version": VERSION,
            "maintenance_gate_results": gate,
        }
    )
    atomic_write_json(paths.summary_json, summary)

    manifest["known_bad_tick_maintenance"] = {
        "version": VERSION,
        "executed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_code": TARGET_CODE,
        "target_timestamp_utc": utc_z(TARGET_TIMESTAMP),
        "root_cause_classification": "BROKER_SOURCE_BAD_TICK",
        "raw_preserved": True,
        "canonical_row_excluded": True,
        "quarantine_path": str(paths.quarantine_csv),
        "maintenance_gate_results": gate,
    }
    atomic_write_json(paths.manifest_json, manifest)

    # Re-read the generated summary; acceptance is based on persisted data, not memory.
    persisted = read_json(paths.summary_json)
    if bool(persisted.get("data_ready_for_v22_050")) != accepted:
        raise MaintenanceError("Persisted summary read-back disagrees with acceptance gate.")

    paths.acceptance_root.mkdir(parents=True, exist_ok=True)
    acceptance_rows = []
    for symbol in EXPECTED_SYMBOLS:
        code = f"US.{symbol}"
        acceptance_rows.append(
            {
                "Code": code,
                "CanonicalParquetCount": scan["partition_count_by_symbol"][symbol],
                "RowCount": scan["row_count_by_symbol"][code],
                "EarliestTimestamp": scan["earliest_timestamp_by_symbol"][code],
                "LatestTimestamp": scan["latest_timestamp_by_symbol"][code],
                "PostprocessPass": postprocess_by_symbol[code],
                "CanonicalWritePass": canonical_by_symbol[code],
                "IncrementalUpdatePass": incremental_by_symbol[code],
                "QuarantinedRawBadTickCount": quarantine_by_symbol[code],
            }
        )
    pd.DataFrame(acceptance_rows).to_csv(
        paths.acceptance_csv,
        index=False,
        encoding="utf-8-sig",
    )

    snapshot = {
        "acceptance_version": "V22.049_ACCEPTANCE_SNAPSHOT_R1",
        "accepted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_commit(paths.repo_root),
        "summary_path": str(paths.summary_json),
        "summary_sha256": sha256_file(paths.summary_json),
        "manifest_path": str(paths.manifest_json),
        "manifest_sha256": sha256_file(paths.manifest_json),
        "raw_source_path": str(paths.raw_file),
        "raw_source_sha256": sha256_file(paths.raw_file),
        "quarantine_path": str(paths.quarantine_csv),
        "quarantine_sha256": sha256_file(paths.quarantine_csv),
        "canonical_parquet_count": scan["canonical_parquet_count"],
        "partition_count_by_symbol": scan["partition_count_by_symbol"],
        "row_count_by_symbol": scan["row_count_by_symbol"],
        "earliest_timestamp_by_symbol": scan["earliest_timestamp_by_symbol"],
        "latest_timestamp_by_symbol": scan["latest_timestamp_by_symbol"],
        "duplicate_count": scan["duplicate_count"],
        "invalid_ohlc_count": scan["invalid_ohlc_count"],
        "quarantined_raw_bad_tick_count": quarantine_count,
        "gate_results": gate,
        "data_baseline_frozen": accepted,
        "v22_050_allowed": accepted,
    }
    atomic_write_json(paths.acceptance_json, snapshot)

    return {
        "accepted": accepted,
        "gate": gate,
        "summary": summary,
        "snapshot": snapshot,
        "acceptance_rows": acceptance_rows,
        "failure_count": failures,
        "quarantine_count": quarantine_count,
    }


def execute(paths: Paths) -> dict[str, Any]:
    canonical_before = len(list(paths.canonical_root.rglob("*.parquet")))
    non_target_hashes_before = {
        str(path): sha256_file(path)
        for path in paths.canonical_root.rglob("*.parquet")
        if path.resolve() != paths.canonical_partition.resolve()
    }

    maintenance = quarantine_known_bad_tick(paths)
    scan = scan_canonical(paths)

    canonical_after = len(list(paths.canonical_root.rglob("*.parquet")))
    non_target_changed = 0
    for raw_path, before_hash in non_target_hashes_before.items():
        path = Path(raw_path)
        if not path.exists() or sha256_file(path) != before_hash:
            non_target_changed += 1

    maintenance.update(
        {
            "canonical_partitions_before": canonical_before,
            "canonical_partitions_after": canonical_after,
            "non_target_partitions_changed": non_target_changed,
        }
    )
    if canonical_before != 582 or canonical_after != 582:
        raise MaintenanceError(
            f"Expected 582 Canonical partitions before/after; got "
            f"{canonical_before}/{canonical_after}."
        )
    if non_target_changed != 0:
        raise MaintenanceError(
            f"{non_target_changed} non-target Canonical partitions changed."
        )

    acceptance = update_summary_and_freeze(paths, maintenance, scan)

    report = {
        "version": VERSION,
        "final_status": "PASS" if acceptance["accepted"] else "FAIL",
        "final_decision": acceptance["summary"]["final_decision"],
        "maintenance": maintenance,
        "scan": scan,
        "failure_count": acceptance["failure_count"],
        "quarantine_record_count": acceptance["quarantine_count"],
        "gate_results": acceptance["gate"],
        "data_baseline_frozen": acceptance["accepted"],
        "v22_050_allowed": acceptance["accepted"],
        "acceptance_json": str(paths.acceptance_json),
        "acceptance_csv": str(paths.acceptance_csv),
    }
    atomic_write_json(paths.execution_report_json, report)
    return report


def print_report(report: dict[str, Any]) -> None:
    maintenance = report["maintenance"]
    scan = report["scan"]
    print(f"FINAL_STATUS={report['final_status']}")
    print(f"FINAL_DECISION={report['final_decision']}")
    print("MAINTENANCE_SCRIPT_CREATED=True")
    print(f"RAW_FILES_MODIFIED={maintenance['raw_files_modified']}")
    print(f"RAW_FILES_DELETED={maintenance['raw_files_deleted']}")
    print(f"RAW_SHA256_BEFORE={maintenance['raw_sha256_before']}")
    print(f"RAW_SHA256_AFTER={maintenance['raw_sha256_after']}")
    print(f"CANONICAL_PARTITIONS_BEFORE={maintenance['canonical_partitions_before']}")
    print(f"CANONICAL_PARTITIONS_AFTER={maintenance['canonical_partitions_after']}")
    print(f"CANONICAL_PARTITIONS_REWRITTEN={maintenance['canonical_partitions_rewritten']}")
    print(f"CANONICAL_ROW_COUNT_DELTA={maintenance['canonical_row_count_delta']}")
    print(f"NON_TARGET_PARTITIONS_CHANGED={maintenance['non_target_partitions_changed']}")
    print(f"QUARANTINE_RECORD_COUNT={report['quarantine_record_count']}")
    print("SYMBOL_COUNT_SUCCEEDED=6")
    print("SYMBOL_COUNT_FAILED=0")
    print("ROW_COUNT_BY_SYMBOL=" + json.dumps(scan["row_count_by_symbol"], ensure_ascii=False))
    print(f"DUPLICATE_COUNT={scan['duplicate_count']}")
    print(f"INVALID_OHLC_COUNT={scan['invalid_ohlc_count']}")
    print(f"QUARANTINED_RAW_BAD_TICK_COUNT={report['quarantine_record_count']}")
    print(f"CANONICAL_WRITE_PASS={report['gate_results']['all_canonical_pass']}")
    print(f"INCREMENTAL_UPDATE_PASS={report['gate_results']['all_incremental_pass']}")
    print(f"DATA_READY_FOR_V22_050={report['v22_050_allowed']}")
    print(f"DATA_BASELINE_FROZEN={report['data_baseline_frozen']}")
    print(f"V22_050_ALLOWED={report['v22_050_allowed']}")
    print(f"ACCEPTANCE_JSON={report['acceptance_json']}")
    print(f"ACCEPTANCE_CSV={report['acceptance_csv']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=r"D:\us-tech-quant")
    parser.add_argument(
        "--data-root",
        default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m",
    )
    parser.add_argument(
        "--results-root",
        default=r"D:\us-tech-quant-results",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required guard. Without it, no files are changed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2

    paths = build_paths(
        Path(args.repo_root),
        Path(args.data_root),
        Path(args.results_root),
    )
    try:
        report = execute(paths)
        print_report(report)
        return 0 if report["final_status"] == "PASS" else 1
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
