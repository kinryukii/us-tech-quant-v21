#!/usr/bin/env python
"""
V22.051 FAST3 RTH baseline event study R1.

Research-only, read-only workflow:
- validates the frozen V22.050 summary;
- processes the six V22.049 Canonical ETFs month-by-month;
- forms QQQ/SOXX RTH signals without lookahead;
- executes at the next minute open in TQQQ/SQQQ/SOXL/SOXS;
- produces event-level and stratified research outputs.

It never modifies RAW/Canonical data and never enables broker, paper-trading,
or official-adoption gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


VERSION = "V22.051_FAST3_RTH_BASELINE_EVENT_STUDY_R1"
SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SQQQ", "SOXL", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
HORIZONS = (5, 15, 30, 60, 120)
ONE_WAY_COST = 0.0005
ROUND_TRIP_COST = ONE_WAY_COST * 2.0

SIGNAL_START_MINUTE = 9 * 60 + 45
SIGNAL_END_MINUTE = 15 * 60 + 30
FORCED_EXIT_MINUTE = 15 * 60 + 55
RTH_START_MINUTE = 9 * 60 + 30
RTH_END_MINUTE = 15 * 60 + 59


class StudyError(RuntimeError):
    """The event study cannot continue safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def utc_z(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return utc_z(value)
    raise TypeError(f"Cannot serialize type {type(value)!r}")


def find_column(
    frame: pd.DataFrame,
    candidates: Iterable[str],
    *,
    required: bool = True,
) -> str | None:
    lower = {str(column).lower(): str(column) for column in frame.columns}
    for candidate in candidates:
        found = lower.get(candidate.lower())
        if found is not None:
            return found
    if required:
        raise StudyError(
            f"Required column missing. Expected one of {list(candidates)}, "
            f"received {list(frame.columns)}"
        )
    return None


def normalize_timestamp_utc(series: pd.Series) -> pd.Series:
    if isinstance(series.dtype, pd.DatetimeTZDtype):
        converted = series.dt.tz_convert("UTC")
    elif pd.api.types.is_datetime64_dtype(series.dtype):
        raise StudyError("timestamp_utc must be timezone-aware UTC.")
    else:
        converted = pd.to_datetime(series, utc=True, errors="raise")

    result = pd.Series(
        pd.array(converted, dtype="datetime64[ns, UTC]"),
        index=series.index,
        name=series.name,
    )
    if str(result.dtype) != "datetime64[ns, UTC]":
        raise StudyError(f"Unexpected timestamp dtype: {result.dtype}")
    return result


def validate_v22_050(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "data_ready_for_fast3_backtest": True,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = []
    for key, expected_value in expected.items():
        actual = summary.get(key)
        if actual != expected_value:
            failures.append(f"{key}: expected {expected_value!r}, got {actual!r}")
    if failures:
        raise StudyError("V22.050 gate validation failed: " + "; ".join(failures))


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        match = re.fullmatch(r"symbol=(.+)", part, flags=re.IGNORECASE)
        if match:
            symbol = match.group(1).upper()
        match = re.fullmatch(r"year=(\d{4})", part, flags=re.IGNORECASE)
        if match:
            year = match.group(1)
        match = re.fullmatch(r"month=(\d{1,2})", part, flags=re.IGNORECASE)
        if match:
            month = f"{int(match.group(1)):02d}"
    if not symbol or not year or not month:
        raise StudyError(f"Cannot derive symbol/year/month from {path}")
    return symbol, year, month


def index_canonical_files(canonical_root: Path) -> dict[tuple[str, str, str], Path]:
    index: dict[tuple[str, str, str], Path] = {}
    for path in sorted(canonical_root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key[0] not in ALL_SYMBOLS:
            continue
        if key in index:
            raise StudyError(f"Duplicate Canonical month partition for {key}")
        index[key] = path
    return index


def load_rth_partition(path: Path, symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if frame.empty:
        return pd.DataFrame(
            columns=["timestamp_utc", "timestamp_et", "trade_date", "open", "high", "low", "close", "volume"]
        )

    ts_col = find_column(frame, ("timestamp_utc",))
    open_col = find_column(frame, ("open",))
    high_col = find_column(frame, ("high",))
    low_col = find_column(frame, ("low",))
    close_col = find_column(frame, ("close",))
    volume_col = find_column(frame, ("volume",))

    timestamp_utc = normalize_timestamp_utc(frame[ts_col])
    timestamp_et = timestamp_utc.dt.tz_convert("America/New_York")
    minute = timestamp_et.dt.hour * 60 + timestamp_et.dt.minute
    mask = (minute >= RTH_START_MINUTE) & (minute <= RTH_END_MINUTE)

    result = pd.DataFrame(
        {
            "timestamp_utc": timestamp_utc.loc[mask],
            "timestamp_et": timestamp_et.loc[mask],
            "trade_date": timestamp_et.loc[mask].dt.strftime("%Y-%m-%d"),
            "open": pd.to_numeric(frame.loc[mask, open_col], errors="coerce"),
            "high": pd.to_numeric(frame.loc[mask, high_col], errors="coerce"),
            "low": pd.to_numeric(frame.loc[mask, low_col], errors="coerce"),
            "close": pd.to_numeric(frame.loc[mask, close_col], errors="coerce"),
            "volume": pd.to_numeric(frame.loc[mask, volume_col], errors="coerce").fillna(0.0),
        }
    )
    result = result.dropna(subset=["timestamp_utc", "open", "high", "low", "close"])
    result = result.sort_values("timestamp_utc", kind="mergesort")
    if result["timestamp_utc"].duplicated().any():
        raise StudyError(f"Duplicate RTH timestamp found in {symbol}: {path}")
    return result.reset_index(drop=True)


def cumulative_vwap(frame: pd.DataFrame) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    volume = frame["volume"].clip(lower=0.0)
    cumulative_volume = volume.cumsum()
    numerator = (typical * volume).cumsum()
    fallback = frame["close"].expanding().mean()
    vwap = numerator.divide(cumulative_volume.where(cumulative_volume > 0))
    return vwap.fillna(fallback)


def exact_elapsed_return(close: pd.Series, minutes: int) -> pd.Series:
    if not isinstance(close.index, pd.DatetimeIndex):
        raise StudyError("exact_elapsed_return requires a DatetimeIndex.")
    prior_index = close.index - pd.Timedelta(minutes=minutes)
    prior_values = close.reindex(prior_index).to_numpy(dtype=float)
    current_values = close.to_numpy(dtype=float)
    values = np.full(len(close), np.nan, dtype=float)
    valid = (
        np.isfinite(current_values)
        & np.isfinite(prior_values)
        & (prior_values > 0)
    )
    values[valid] = current_values[valid] / prior_values[valid] - 1.0
    return pd.Series(values, index=close.index)


def determine_signal(
    qqq_ret_15m: float,
    soxx_ret_15m: float,
    qqq_close: float,
    qqq_vwap: float,
    soxx_close: float,
    soxx_vwap: float,
) -> tuple[str, str] | None:
    values = (
        qqq_ret_15m,
        soxx_ret_15m,
        qqq_close,
        qqq_vwap,
        soxx_close,
        soxx_vwap,
    )
    if not all(np.isfinite(value) for value in values):
        return None

    if (
        qqq_ret_15m > 0
        and soxx_ret_15m > 0
        and qqq_close > qqq_vwap
        and soxx_close > soxx_vwap
    ):
        return ("LONG", "SOXL" if soxx_ret_15m > qqq_ret_15m else "TQQQ")

    if (
        qqq_ret_15m < 0
        and soxx_ret_15m < 0
        and qqq_close < qqq_vwap
        and soxx_close < soxx_vwap
    ):
        return ("SHORT", "SOXS" if soxx_ret_15m < qqq_ret_15m else "SQQQ")

    return None


def time_bucket(timestamp_et: pd.Timestamp) -> str:
    minute = timestamp_et.hour * 60 + timestamp_et.minute
    if 9 * 60 + 45 <= minute <= 10 * 60 + 29:
        return "09:45-10:29"
    if 10 * 60 + 30 <= minute <= 11 * 60 + 59:
        return "10:30-11:59"
    if 12 * 60 <= minute <= 13 * 60 + 59:
        return "12:00-13:59"
    if 14 * 60 <= minute <= 15 * 60 + 30:
        return "14:00-15:30"
    return "OUTSIDE"


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return "2018-2022_DEVELOPMENT"
    if 2023 <= year <= 2024:
        return "2023-2024_VALIDATION"
    if year >= 2025:
        return "2025-2026_YTD_CONFIRMATION"
    return "PRE_2018_REFERENCE"


def threshold_first_hit(
    future: pd.DataFrame,
    entry_price: float,
    positive_threshold: float,
    negative_threshold: float,
) -> tuple[bool, bool]:
    if future.empty or not np.isfinite(entry_price) or entry_price <= 0:
        return False, False
    plus_mask = future["high"].to_numpy(dtype=float) / entry_price - 1.0 >= positive_threshold
    minus_mask = future["low"].to_numpy(dtype=float) / entry_price - 1.0 <= negative_threshold
    plus_indices = np.flatnonzero(plus_mask)
    minus_indices = np.flatnonzero(minus_mask)
    plus_first = int(plus_indices[0]) if plus_indices.size else None
    minus_first = int(minus_indices[0]) if minus_indices.size else None

    # Conservative ambiguity handling: if both occur in the same 1-minute bar,
    # the adverse threshold is treated as first.
    plus_before_minus = (
        plus_first is not None
        and (minus_first is None or plus_first < minus_first)
    )
    minus_before_plus = (
        minus_first is not None
        and (plus_first is None or minus_first <= plus_first)
    )
    return plus_before_minus, minus_before_plus


def compute_event_metrics(
    execution: pd.DataFrame,
    signal_timestamp_utc: pd.Timestamp,
) -> dict[str, Any] | None:
    if execution.empty:
        return None

    indexed = execution.set_index("timestamp_utc", drop=False)
    entry_timestamp = signal_timestamp_utc + pd.Timedelta(minutes=1)
    if entry_timestamp not in indexed.index:
        return None

    entry_row = indexed.loc[entry_timestamp]
    if isinstance(entry_row, pd.DataFrame):
        raise StudyError(f"Duplicate execution timestamp at {entry_timestamp}")
    entry_price = float(entry_row["open"])
    if not np.isfinite(entry_price) or entry_price <= 0:
        return None

    trade_date = str(entry_row["trade_date"])
    date_rows = execution.loc[execution["trade_date"] == trade_date].copy()
    if date_rows.empty:
        return None
    exit_candidates = date_rows.loc[
        (date_rows["timestamp_et"].dt.hour * 60 + date_rows["timestamp_et"].dt.minute)
        <= FORCED_EXIT_MINUTE
    ]
    forced = exit_candidates.loc[exit_candidates["timestamp_utc"] >= entry_timestamp]
    if forced.empty:
        return None
    forced_row = forced.iloc[-1]
    forced_exit_timestamp = pd.Timestamp(forced_row["timestamp_utc"])
    forced_exit_close = float(forced_row["close"])

    metrics: dict[str, Any] = {
        "entry_timestamp_utc": entry_timestamp,
        "entry_timestamp_et": pd.Timestamp(entry_row["timestamp_et"]),
        "entry_price": entry_price,
        "forced_exit_timestamp_utc": forced_exit_timestamp,
        "forced_exit_timestamp_et": pd.Timestamp(forced_row["timestamp_et"]),
        "forced_exit_price": forced_exit_close,
        "forced_exit_return_gross": forced_exit_close / entry_price - 1.0,
        "forced_exit_return_net": forced_exit_close / entry_price - 1.0 - ROUND_TRIP_COST,
    }

    for horizon in HORIZONS:
        exit_timestamp = entry_timestamp + pd.Timedelta(minutes=horizon)
        key_gross = f"forward_return_{horizon}m_gross"
        key_net = f"forward_return_{horizon}m_net"
        if exit_timestamp <= forced_exit_timestamp and exit_timestamp in indexed.index:
            exit_row = indexed.loc[exit_timestamp]
            if isinstance(exit_row, pd.DataFrame):
                raise StudyError(f"Duplicate exit timestamp at {exit_timestamp}")
            gross = float(exit_row["close"]) / entry_price - 1.0
            metrics[key_gross] = gross
            metrics[key_net] = gross - ROUND_TRIP_COST
        else:
            metrics[key_gross] = np.nan
            metrics[key_net] = np.nan

    window_end = min(
        entry_timestamp + pd.Timedelta(minutes=60),
        forced_exit_timestamp,
    )
    future_60 = date_rows.loc[
        (date_rows["timestamp_utc"] >= entry_timestamp)
        & (date_rows["timestamp_utc"] <= window_end)
    ].sort_values("timestamp_utc")
    metrics["mfe_60m"] = (
        float(future_60["high"].max()) / entry_price - 1.0
        if not future_60.empty
        else np.nan
    )
    metrics["mae_60m"] = (
        float(future_60["low"].min()) / entry_price - 1.0
        if not future_60.empty
        else np.nan
    )
    metrics["observation_minutes_60m"] = int(len(future_60))

    for plus in (0.005, 0.01, 0.02, 0.03):
        plus_first, _ = threshold_first_hit(future_60, entry_price, plus, -0.006)
        label = str(plus).replace("0.", "").rstrip("0")
        mapping = {
            0.005: "hit_plus_0_5_before_minus_0_6",
            0.01: "hit_plus_1_before_minus_0_6",
            0.02: "hit_plus_2_before_minus_0_6",
            0.03: "hit_plus_3_before_minus_0_6",
        }
        metrics[mapping[plus]] = bool(plus_first)

    _, minus_before_plus = threshold_first_hit(future_60, entry_price, 0.01, -0.006)
    metrics["hit_minus_0_6_before_plus_1"] = bool(minus_before_plus)
    return metrics


def add_daily_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.set_index("timestamp_utc").copy()
    volume = result["volume"].clip(lower=0.0)
    typical = (result["high"] + result["low"] + result["close"]) / 3.0
    cumulative_volume = volume.groupby(result["trade_date"], sort=False).cumsum()
    cumulative_value = (typical * volume).groupby(
        result["trade_date"],
        sort=False,
    ).cumsum()
    fallback = (
        result.groupby("trade_date", sort=False)["close"]
        .expanding()
        .mean()
        .reset_index(level=0, drop=True)
    )
    result["vwap"] = (
        cumulative_value.divide(cumulative_volume.where(cumulative_volume > 0))
        .fillna(fallback)
    )
    result["ret_15m"] = result.groupby(
        "trade_date",
        sort=False,
    )["close"].transform(lambda series: exact_elapsed_return(series, 15))
    return result


def prepare_signal_frame(qqq: pd.DataFrame, soxx: pd.DataFrame) -> pd.DataFrame:
    q = add_daily_indicators(qqq)
    s = add_daily_indicators(soxx)

    columns_q = q[
        ["timestamp_et", "trade_date", "close", "vwap", "ret_15m"]
    ].rename(
        columns={
            "timestamp_et": "signal_timestamp_et",
            "close": "qqq_close",
            "vwap": "qqq_vwap",
            "ret_15m": "qqq_ret_15m",
        }
    )
    columns_s = s[["trade_date", "close", "vwap", "ret_15m"]].rename(
        columns={
            "trade_date": "soxx_trade_date",
            "close": "soxx_close",
            "vwap": "soxx_vwap",
            "ret_15m": "soxx_ret_15m",
        }
    )
    merged = columns_q.join(columns_s, how="inner")
    merged = merged.loc[merged["trade_date"] == merged["soxx_trade_date"]].copy()
    minute = (
        merged["signal_timestamp_et"].dt.hour * 60
        + merged["signal_timestamp_et"].dt.minute
    )
    merged = merged.loc[
        (minute >= SIGNAL_START_MINUTE) & (minute <= SIGNAL_END_MINUTE)
    ]
    return merged.sort_index()


def generate_month_events(
    frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    signals = prepare_signal_frame(frames["QQQ"], frames["SOXX"])
    execution_indexed = {
        symbol: frame for symbol, frame in frames.items() if symbol in EXECUTION_SYMBOLS
    }
    rows: list[dict[str, Any]] = []

    for signal_timestamp, row in signals.iterrows():
        decision = determine_signal(
            float(row["qqq_ret_15m"]),
            float(row["soxx_ret_15m"]),
            float(row["qqq_close"]),
            float(row["qqq_vwap"]),
            float(row["soxx_close"]),
            float(row["soxx_vwap"]),
        )
        if decision is None:
            continue
        direction, execution_symbol = decision
        metrics = compute_event_metrics(
            execution_indexed[execution_symbol],
            pd.Timestamp(signal_timestamp),
        )
        if metrics is None:
            continue

        signal_et = pd.Timestamp(row["signal_timestamp_et"])
        year = signal_et.year
        event = {
            "signal_timestamp_utc": pd.Timestamp(signal_timestamp),
            "signal_timestamp_et": signal_et,
            "broker_trade_date": str(row["trade_date"]),
            "calendar_year": year,
            "study_period": study_period(year),
            "time_bucket": time_bucket(signal_et),
            "direction": direction,
            "execution_symbol": execution_symbol,
            "qqq_ret_15m": float(row["qqq_ret_15m"]),
            "soxx_ret_15m": float(row["soxx_ret_15m"]),
            "qqq_vwap_deviation_bps": (
                float(row["qqq_close"]) / float(row["qqq_vwap"]) - 1.0
            ) * 10_000.0,
            "soxx_vwap_deviation_bps": (
                float(row["soxx_close"]) / float(row["soxx_vwap"]) - 1.0
            ) * 10_000.0,
            **metrics,
        }
        rows.append(event)

    return pd.DataFrame(rows)


def summarize_returns(
    events: pd.DataFrame,
    group_columns: Sequence[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if events.empty:
        return pd.DataFrame()

    grouped = (
        [((), events)]
        if not group_columns
        else events.groupby(list(group_columns), dropna=False, sort=True)
    )
    for group_key, group in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        base = dict(zip(group_columns, group_key))
        for horizon in HORIZONS:
            column = f"forward_return_{horizon}m_net"
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            row = {
                **base,
                "horizon_minutes": horizon,
                "event_count": int(len(group)),
                "available_return_count": int(len(values)),
                "mean_net_return": float(values.mean()) if len(values) else np.nan,
                "median_net_return": float(values.median()) if len(values) else np.nan,
                "positive_rate": float((values > 0).mean()) if len(values) else np.nan,
                "p10_net_return": float(values.quantile(0.10)) if len(values) else np.nan,
                "p90_net_return": float(values.quantile(0.90)) if len(values) else np.nan,
            }
            rows.append(row)
    return pd.DataFrame(rows)


def threshold_summary(events: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "hit_plus_0_5_before_minus_0_6",
        "hit_plus_1_before_minus_0_6",
        "hit_plus_2_before_minus_0_6",
        "hit_plus_3_before_minus_0_6",
        "hit_minus_0_6_before_plus_1",
    ]
    rows = []
    for direction, group in events.groupby("direction", dropna=False, sort=True):
        row = {"direction": direction, "event_count": int(len(group))}
        for column in columns:
            row[f"{column}_rate"] = float(group[column].astype(bool).mean())
        rows.append(row)
    if not events.empty:
        total = {"direction": "ALL", "event_count": int(len(events))}
        for column in columns:
            total[f"{column}_rate"] = float(events[column].astype(bool).mean())
        rows.append(total)
    return pd.DataFrame(rows)


def safe_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def run_study(
    *,
    v22_050_summary_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    if not v22_050_summary_path.exists():
        raise StudyError(f"V22.050 summary not found: {v22_050_summary_path}")
    v22_050 = json.loads(v22_050_summary_path.read_text(encoding="utf-8-sig"))
    validate_v22_050(v22_050)

    index = index_canonical_files(canonical_root)
    months = sorted({(year, month) for _, year, month in index})
    if not months:
        raise StudyError("No Canonical month partitions found.")

    missing = [
        (symbol, year, month)
        for year, month in months
        for symbol in ALL_SYMBOLS
        if (symbol, year, month) not in index
    ]
    if missing:
        raise StudyError(f"Missing required symbol-month partitions: {missing[:10]}")

    canonical_paths = [index[(symbol, year, month)] for year, month in months for symbol in ALL_SYMBOLS]
    before_hashes = {str(path): sha256_file(path) for path in canonical_paths}

    event_chunks: list[pd.DataFrame] = []
    for count, (year, month) in enumerate(months, start=1):
        frames = {
            symbol: load_rth_partition(index[(symbol, year, month)], symbol)
            for symbol in ALL_SYMBOLS
        }
        month_events = generate_month_events(frames)
        if not month_events.empty:
            event_chunks.append(month_events)
        print(
            f"[EVENT_STUDY] month={year}-{month} "
            f"progress={count}/{len(months)} "
            f"month_events={len(month_events)} "
            f"total_events={sum(len(chunk) for chunk in event_chunks)}",
            flush=True,
        )

    if event_chunks:
        events = pd.concat(event_chunks, ignore_index=True)
        events = events.sort_values(
            ["signal_timestamp_utc", "execution_symbol"],
            kind="mergesort",
        ).reset_index(drop=True)
    else:
        events = pd.DataFrame()

    if events.empty:
        raise StudyError("No FAST3 baseline events were generated.")

    duplicate_events = int(
        events.duplicated(
            subset=["signal_timestamp_utc", "execution_symbol"],
            keep=False,
        ).sum()
    )
    if duplicate_events:
        raise StudyError(f"Duplicate event rows detected: {duplicate_events}")

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "events_parquet": result_dir / "v22_051_events.parquet",
        "events_csv": result_dir / "v22_051_events.csv",
        "horizon_summary": result_dir / "v22_051_horizon_summary.csv",
        "period_summary": result_dir / "v22_051_period_summary.csv",
        "year_summary": result_dir / "v22_051_year_summary.csv",
        "symbol_summary": result_dir / "v22_051_symbol_summary.csv",
        "time_bucket_summary": result_dir / "v22_051_time_bucket_summary.csv",
        "threshold_summary": result_dir / "v22_051_threshold_touch_summary.csv",
        "summary": result_dir / "v22_051_summary.json",
        "manifest": result_dir / "v22_051_run_manifest.json",
    }

    events.to_parquet(outputs["events_parquet"], index=False)
    events.to_csv(outputs["events_csv"], index=False, encoding="utf-8-sig")

    horizon = summarize_returns(events, [])
    period = summarize_returns(events, ["study_period", "direction"])
    year_summary = summarize_returns(events, ["calendar_year", "direction"])
    symbol_summary = summarize_returns(events, ["execution_symbol"])
    bucket_summary = summarize_returns(events, ["time_bucket", "direction"])
    touch_summary = threshold_summary(events)

    horizon.to_csv(outputs["horizon_summary"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period_summary"], index=False, encoding="utf-8-sig")
    year_summary.to_csv(outputs["year_summary"], index=False, encoding="utf-8-sig")
    symbol_summary.to_csv(outputs["symbol_summary"], index=False, encoding="utf-8-sig")
    bucket_summary.to_csv(outputs["time_bucket_summary"], index=False, encoding="utf-8-sig")
    touch_summary.to_csv(outputs["threshold_summary"], index=False, encoding="utf-8-sig")

    after_hashes = {str(path): sha256_file(path) for path in canonical_paths}
    if before_hashes != after_hashes:
        raise StudyError("Canonical files changed during the read-only event study.")

    net_summary = {}
    for horizon_minutes in HORIZONS:
        values = pd.to_numeric(
            events[f"forward_return_{horizon_minutes}m_net"],
            errors="coerce",
        ).dropna()
        net_summary[str(horizon_minutes)] = {
            "available_count": int(len(values)),
            "mean": safe_scalar(float(values.mean()) if len(values) else np.nan),
            "median": safe_scalar(float(values.median()) if len(values) else np.nan),
            "positive_rate": safe_scalar(float((values > 0).mean()) if len(values) else np.nan),
        }

    result_by_period = (
        period.to_dict(orient="records") if not period.empty else []
    )
    result_by_year = (
        year_summary.to_dict(orient="records") if not year_summary.empty else []
    )
    result_by_bucket = (
        bucket_summary.to_dict(orient="records") if not bucket_summary.empty else []
    )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": "FAST3_RTH_BASELINE_EVENT_STUDY_COMPLETED_NO_ENTRY_EXIT_OPTIMIZATION",
        "v22_050_summary_path": str(v22_050_summary_path),
        "v22_050_summary_sha256": sha256_file(v22_050_summary_path),
        "v22_050_gate_validated": True,
        "canonical_root": str(canonical_root),
        "canonical_file_count_read": len(canonical_paths),
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "event_count": int(len(events)),
        "long_event_count": int((events["direction"] == "LONG").sum()),
        "short_event_count": int((events["direction"] == "SHORT").sum()),
        "event_count_by_execution_symbol": {
            str(key): int(value)
            for key, value in events["execution_symbol"].value_counts().sort_index().items()
        },
        "net_return_by_horizon": net_summary,
        "mfe_60m_median": safe_scalar(float(events["mfe_60m"].median())),
        "mae_60m_median": safe_scalar(float(events["mae_60m"].median())),
        "plus_3_before_minus_0_6_rate": safe_scalar(
            float(events["hit_plus_3_before_minus_0_6"].astype(bool).mean())
        ),
        "result_by_development_validation_confirmation": result_by_period,
        "result_by_year": result_by_year,
        "result_by_time_bucket": result_by_bucket,
        "event_study_completed": True,
        "entry_exit_optimization_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "signal_definition": {
            "signal_window_et": "09:45-15:30",
            "execution": "next minute open",
            "qqq_soxx_momentum_minutes": 15,
            "vwap": "cumulative typical-price VWAP within each RTH trade date",
            "round_trip_cost": ROUND_TRIP_COST,
            "forced_exit": "last available RTH close at or before 15:55 ET",
        },
        "methodological_limits": [
            "Every qualifying minute is retained as an event; events may overlap.",
            "Forward horizon returns require the exact future timestamp; otherwise they are null.",
            "MFE/MAE and threshold touches are capped at 60 minutes or the 15:55 forced exit.",
            "When positive and adverse thresholds occur in the same one-minute bar, adverse is treated as first.",
            "This is an event study, not a portfolio backtest.",
        ],
    }
    atomic_json(outputs["summary"], summary)

    manifest = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_v22_050_summary": str(v22_050_summary_path),
        "canonical_root": str(canonical_root),
        "month_count": len(months),
        "canonical_file_count_read": len(canonical_paths),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "read_only_guards": {
            "canonical_files_modified": False,
            "raw_files_modified": False,
            "open_d_called": False,
            "history_download_executed": False,
        },
        "policy_gates": {
            "entry_exit_optimization_executed": False,
            "broker_action_allowed": False,
            "paper_trading_allowed": False,
            "official_adoption_allowed": False,
        },
    }
    atomic_json(outputs["manifest"], manifest)

    return {"summary": summary, "outputs": outputs, "result_dir": result_dir}


def print_final(result: Mapping[str, Any]) -> None:
    summary = result["summary"]
    net = summary["net_return_by_horizon"]
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"FINAL_DECISION={summary['final_decision']}")
    print("FILES_MODIFIED=None")
    print("V22_050_GATE_VALIDATED=True")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("OPEN_D_CALLED=False")
    print("HISTORY_DOWNLOAD_EXECUTED=False")
    print(f"EVENT_COUNT={summary['event_count']}")
    print(f"LONG_EVENT_COUNT={summary['long_event_count']}")
    print(f"SHORT_EVENT_COUNT={summary['short_event_count']}")
    print(
        "EVENT_COUNT_BY_EXECUTION_SYMBOL="
        + json.dumps(summary["event_count_by_execution_symbol"], ensure_ascii=False)
    )
    print(
        "MEDIAN_NET_RETURN_BY_HORIZON="
        + json.dumps({key: value["median"] for key, value in net.items()}, ensure_ascii=False)
    )
    print(
        "MEAN_NET_RETURN_BY_HORIZON="
        + json.dumps({key: value["mean"] for key, value in net.items()}, ensure_ascii=False)
    )
    print(
        "POSITIVE_RATE_BY_HORIZON="
        + json.dumps({key: value["positive_rate"] for key, value in net.items()}, ensure_ascii=False)
    )
    print(f"MFE_60M_MEDIAN={summary['mfe_60m_median']}")
    print(f"MAE_60M_MEDIAN={summary['mae_60m_median']}")
    print(f"PLUS_3_BEFORE_MINUS_0_6_RATE={summary['plus_3_before_minus_0_6_rate']}")
    print("EVENT_STUDY_COMPLETED=True")
    print("ENTRY_EXIT_OPTIMIZATION_EXECUTED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={result['outputs']['summary']}")
    print(f"RESULT_DIRECTORY={result['result_dir']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-050-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.050_FAST3_SIX_ETF_MINUTE_TRADABILITY_AUDIT_R1"
            r"\v22_050_summary.json"
        ),
    )
    parser.add_argument(
        "--canonical-root",
        default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical",
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.051_FAST3_RTH_BASELINE_EVENT_STUDY_R1"
        ),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        result = run_study(
            v22_050_summary_path=Path(args.v22_050_summary),
            canonical_root=Path(args.canonical_root),
            result_dir=Path(args.result_dir),
        )
        print_final(result)
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
