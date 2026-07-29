#!/usr/bin/env python
r"""
V22.062N FAST3 overnight synchronized trend baseline R1.

This stage is structurally independent from the failed RTH opening-range
baseline and the terminated pullback/re-entry architecture.

Frozen overnight session
------------------------
- Session: 20:00 ET through 03:59 ET.
- Session date: the calendar date of the post-midnight segment.
- Initial range: 20:00 through 20:59 ET.
- Signal window: 21:00 through 02:54 ET.
- Maximum one entry per overnight session.
- Entry at the exact next-minute open.

Frozen synchronized signal
--------------------------
LONG:
- QQQ and SOXX both close above their own 20:00-20:59 initial-range highs.
- Both are above cumulative overnight typical-price VWAP.
- Both exact 30-minute returns are positive.
- Both pass the frozen minute-data tradability proxy.

SHORT:
- QQQ and SOXX both close below their own initial-range lows.
- Both are below cumulative overnight typical-price VWAP.
- Both exact 30-minute returns are negative.
- Both pass the frozen minute-data tradability proxy.

Frozen tradability proxy
------------------------
For each signal asset:
- Initial range contains at least 30 observed one-minute bars.
- First observed initial-range bar is no later than 20:05 ET.
- Last observed initial-range bar is no earlier than 20:54 ET.
- At the signal minute, the preceding 30-minute window contains:
  at least 15 observed bars, at least 10 positive-volume bars,
  and at least 5 nonzero close changes.
- The exact signal minute and exact 30-minute-lag minute both exist.

This is only an OHLCV tradability proxy. Bid/ask spread and order-book depth
are not available and are not inferred.

Frozen execution selection
--------------------------
- Compute 30-minute momentum divided by trailing 120-minute realized
  one-minute volatility for QQQ and SOXX.
- LONG: stronger normalized SOXX -> SOXL; otherwise TQQQ.
- SHORT: weaker normalized SOXX -> SOXS; otherwise SQQQ.

Frozen exits
------------
- FIXED_30M
- FIXED_60M
- SESSION_0355

All three exits require exact minute bars. No hard stop, trailing stop,
no-progress exit or factor invalidation is used.

Diagnostics only
----------------
- Overnight 5-minute RSI(14), MACD(12,26,9), KDJ(9,3,3).
- Prior available official Cboe VIX 1-day change, 3-day change and
  absolute-change percentile.
These diagnostics do not create, delete or size a signal.

Guards
------
- No parameter sweep.
- No session-window sweep.
- No initial-range-length sweep.
- No indicator threshold optimization.
- No VIX gate or VIX risk scaling.
- No broker or paper trading.
- No RAW or Canonical mutation.
- No new market-data cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


VERSION = "V22.062N_FAST3_OVERNIGHT_SYNCHRONIZED_TREND_BASELINE_R1"

SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "SESSION_0355")

OVERNIGHT_EVENING_START = 20 * 60
OVERNIGHT_MORNING_END = 3 * 60 + 59
SESSION_LENGTH = 480

INITIAL_RANGE_START = 0
INITIAL_RANGE_END = 59
SIGNAL_START = 60
SIGNAL_END = 414
SESSION_EXIT_MINUTE = 475

ENTRY_COST = 0.0005
EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.20

INITIAL_RANGE_MIN_BARS = 30
INITIAL_RANGE_FIRST_MAX = 5
INITIAL_RANGE_LAST_MIN = 54
RECENT_WINDOW = 30
RECENT_MIN_BARS = 15
RECENT_MIN_POSITIVE_VOLUME_BARS = 10
RECENT_MIN_CLOSE_CHANGES = 5
NORMALIZATION_WINDOW = 120
NORMALIZATION_MIN_RETURNS = 30

MIN_FULL_HISTORY_TRADES = 80
MIN_VALIDATION_TRADES = 20
MIN_CONFIRMATION_TRADES = 20
MAX_SINGLE_POSITIVE_YEAR_SHARE = 0.60

PERIODS = (
    "2018-2022_DEVELOPMENT",
    "2023-2024_VALIDATION",
    "2025-2026_YTD_CONFIRMATION",
)
PERIOD_ORDER = {period: index for index, period in enumerate(PERIODS)}


class StudyError(RuntimeError):
    """V22.062N cannot continue safely."""


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return "2018-2022_DEVELOPMENT"
    if 2023 <= year <= 2024:
        return "2023-2024_VALIDATION"
    if 2025 <= year <= 2026:
        return "2025-2026_YTD_CONFIRMATION"
    return "OUTSIDE_STUDY"


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value)!r}")


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise StudyError(f"{name} missing required columns: {missing}")


def validate_v22_061(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "NO_ORB_BASELINE_CANDIDATE_QUALIFIED",
        "v22_060_validated": True,
        "v22_056_validated": True,
        "previous_pullback_reentry_architecture_used": False,
        "opening_range_minutes": 30,
        "maximum_entries_per_day": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "parameter_sweep_executed": False,
        "opening_range_length_sweep_executed": False,
        "breakout_buffer_sweep_executed": False,
        "indicator_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise StudyError(
            "V22.061 lineage validation failed: " + "; ".join(failures)
        )

    if int(summary.get("canonical_partition_count_indexed", -1)) != 582:
        raise StudyError("V22.061 did not index the expected 582 partitions")
    if summary.get("supported_exit_variants_for_replication") != []:
        raise StudyError("V22.061 unexpectedly contains a supported exit")


def validate_v22_056(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": (
            "OFFICIAL_CBOE_DAILY_VIX_READY_FOR_PRIOR_DAY_REGIME_FILTER"
        ),
        "prior_day_shift_validated": True,
        "daily_vix_regime_ready": True,
        "intraday_vix_data_ready": False,
        "intraday_vix_features_allowed": False,
        "vix_proxy_substitution_used": False,
        "data_ready_for_daily_vix_multifactor_backtest": True,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise StudyError(
            "V22.056 lineage validation failed: " + "; ".join(failures)
        )


def find_column(frame: pd.DataFrame, aliases: Iterable[str]) -> str:
    mapping = {
        str(column).strip().lower(): str(column)
        for column in frame.columns
    }
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise StudyError(
        f"Missing required column from aliases={tuple(aliases)}"
    )


def normalize_timestamp_utc(series: pd.Series) -> pd.Series:
    values = pd.to_datetime(series, errors="raise", utc=True)
    if values.dt.tz is None:
        raise StudyError("timestamp_utc must be timezone-aware")
    return values


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        symbol_match = re.fullmatch(r"symbol=(.+)", part, re.I)
        if symbol_match:
            symbol = (
                symbol_match.group(1)
                .upper()
                .replace("US.", "")
            )
        year_match = re.fullmatch(r"year=(\d{4})", part, re.I)
        if year_match:
            year = year_match.group(1)
        month_match = re.fullmatch(r"month=(\d{1,2})", part, re.I)
        if month_match:
            month = f"{int(month_match.group(1)):02d}"
    if not all((symbol, year, month)):
        raise StudyError(f"Cannot parse Canonical path: {path}")
    return symbol, year, month


def index_canonical(
    root: Path,
) -> dict[tuple[str, str, str], Path]:
    result: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key[0] not in ALL_SYMBOLS:
            continue
        if key in result:
            raise StudyError(f"Duplicate Canonical partition: {key}")
        result[key] = path

    counts = {symbol: 0 for symbol in ALL_SYMBOLS}
    for symbol, _, _ in result:
        counts[symbol] += 1
    if any(count == 0 for count in counts.values()):
        raise StudyError(f"Missing Canonical symbol partitions: {counts}")
    if len(set(counts.values())) != 1:
        raise StudyError(
            f"Canonical partition counts differ by symbol: {counts}"
        )
    if len(result) != 582:
        raise StudyError(
            f"Expected 582 Canonical partitions, found {len(result)}"
        )
    return result


def load_overnight_partition(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "timestamp_et",
                "session_date",
                "session_minute",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )

    timestamp = normalize_timestamp_utc(
        raw[find_column(raw, ("timestamp_utc",))]
    )
    timestamp_et = timestamp.dt.tz_convert("America/New_York")
    minute_et = timestamp_et.dt.hour * 60 + timestamp_et.dt.minute
    mask = (
        (minute_et >= OVERNIGHT_EVENING_START)
        | (minute_et <= OVERNIGHT_MORNING_END)
    )

    selected_et = timestamp_et.loc[mask]
    selected_minute = minute_et.loc[mask].astype(int)
    local_day = selected_et.dt.normalize()
    session_day = local_day.where(
        selected_minute <= OVERNIGHT_MORNING_END,
        local_day + pd.Timedelta(days=1),
    )
    session_minute = np.where(
        selected_minute >= OVERNIGHT_EVENING_START,
        selected_minute - OVERNIGHT_EVENING_START,
        selected_minute + 240,
    ).astype(np.int16)

    frame = pd.DataFrame(
        {
            "timestamp_utc": timestamp.loc[mask],
            "timestamp_et": selected_et,
            "session_date": session_day.dt.strftime("%Y-%m-%d"),
            "session_minute": session_minute,
            "open": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("open",))],
                errors="coerce",
            ),
            "high": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("high",))],
                errors="coerce",
            ),
            "low": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("low",))],
                errors="coerce",
            ),
            "close": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("close",))],
                errors="coerce",
            ),
            "volume": pd.to_numeric(
                raw.loc[mask, find_column(raw, ("volume",))],
                errors="coerce",
            ).fillna(0.0),
        }
    ).dropna(
        subset=[
            "timestamp_utc",
            "open",
            "high",
            "low",
            "close",
        ]
    )
    frame = frame.sort_values(
        "timestamp_utc",
        kind="mergesort",
    ).reset_index(drop=True)

    if (
        frame.duplicated(["session_date", "session_minute"]).any()
        or frame["timestamp_utc"].duplicated().any()
    ):
        raise StudyError(f"Duplicate overnight minute: {path}")
    if (
        (frame["low"] > frame["high"]).any()
        or (frame["close"] < frame["low"]).any()
        or (frame["close"] > frame["high"]).any()
    ):
        raise StudyError(f"Invalid overnight OHLC relationship: {path}")
    return frame


def load_symbol_overnight(
    symbol: str,
    canonical: Mapping[tuple[str, str, str], Path],
) -> pd.DataFrame:
    paths = [
        path
        for (current, _, _), path in sorted(canonical.items())
        if current == symbol
    ]
    frames = [load_overnight_partition(path) for path in paths]
    frame = pd.concat(frames, ignore_index=True)
    frame = frame.sort_values(
        ["session_date", "session_minute"],
        kind="mergesort",
    ).reset_index(drop=True)
    if frame.duplicated(["session_date", "session_minute"]).any():
        duplicates = frame.loc[
            frame.duplicated(
                ["session_date", "session_minute"],
                keep=False,
            ),
            ["session_date", "session_minute"],
        ].head()
        raise StudyError(
            f"Cross-partition duplicate for {symbol}: "
            f"{duplicates.to_dict('records')}"
        )
    return frame.set_index(
        ["session_date", "session_minute"],
        drop=False,
    ).sort_index()


def get_session(
    table: pd.DataFrame,
    session_date: str,
) -> pd.DataFrame:
    try:
        day = table.xs(
            session_date,
            level="session_date",
            drop_level=True,
        ).copy()
    except KeyError:
        return pd.DataFrame()

    # load_symbol_overnight intentionally keeps session_minute both as an
    # index level and as a column for auditability. Remove the index before
    # sorting by the retained column to avoid pandas label/index ambiguity.
    return (
        day.reset_index(drop=True)
        .sort_values(
            "session_minute",
            kind="mergesort",
        )
        .reset_index(drop=True)
    )


def session_grid(day: pd.DataFrame) -> pd.DataFrame:
    grid = pd.DataFrame(index=pd.RangeIndex(SESSION_LENGTH))
    grid.index.name = "session_minute"
    if day.empty:
        for column in [
            "timestamp_utc",
            "timestamp_et",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            grid[column] = np.nan
        return grid

    indexed = day.set_index("session_minute")
    grid = grid.join(
        indexed[
            [
                "timestamp_utc",
                "timestamp_et",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ],
        how="left",
    )
    grid["observed"] = grid["close"].notna()
    grid["positive_volume"] = grid["volume"].fillna(0.0) > 0

    typical = (
        grid["high"] + grid["low"] + grid["close"]
    ) / 3.0
    volume = grid["volume"].fillna(0.0).clip(lower=0.0)
    cumulative_volume = volume.cumsum()
    cumulative_value = (typical.fillna(0.0) * volume).cumsum()
    observed_mean = grid["close"].expanding().mean()
    grid["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(observed_mean)

    grid["ret_1m"] = grid["close"].pct_change(fill_method=None)
    grid["ret_30m"] = grid["close"] / grid["close"].shift(30) - 1.0
    grid["recent_observed_count"] = (
        grid["observed"].rolling(
            RECENT_WINDOW,
            min_periods=1,
        ).sum()
    )
    grid["recent_positive_volume_count"] = (
        grid["positive_volume"].rolling(
            RECENT_WINDOW,
            min_periods=1,
        ).sum()
    )
    close_change = (
        grid["close"].diff().abs().gt(0)
        & grid["close"].notna()
        & grid["close"].shift(1).notna()
    )
    grid["recent_close_change_count"] = (
        close_change.rolling(
            RECENT_WINDOW,
            min_periods=1,
        ).sum()
    )
    grid["realized_vol_120m"] = (
        grid["ret_1m"].rolling(
            NORMALIZATION_WINDOW,
            min_periods=NORMALIZATION_MIN_RETURNS,
        ).std(ddof=1)
        * math.sqrt(30.0)
    )
    grid["normalized_momentum_30m"] = (
        grid["ret_30m"]
        / grid["realized_vol_120m"].replace(0.0, np.nan)
    )

    opening = grid.loc[INITIAL_RANGE_START:INITIAL_RANGE_END]
    observed_opening = opening.loc[opening["observed"]]
    grid["initial_range_bar_count"] = int(len(observed_opening))
    grid["initial_range_first_minute"] = (
        int(observed_opening.index.min())
        if len(observed_opening)
        else np.nan
    )
    grid["initial_range_last_minute"] = (
        int(observed_opening.index.max())
        if len(observed_opening)
        else np.nan
    )
    grid["initial_range_high"] = (
        float(observed_opening["high"].max())
        if len(observed_opening)
        else np.nan
    )
    grid["initial_range_low"] = (
        float(observed_opening["low"].min())
        if len(observed_opening)
        else np.nan
    )
    grid["initial_range_complete"] = bool(
        len(observed_opening) >= INITIAL_RANGE_MIN_BARS
        and int(observed_opening.index.min())
        <= INITIAL_RANGE_FIRST_MAX
        and int(observed_opening.index.max())
        >= INITIAL_RANGE_LAST_MIN
    ) if len(observed_opening) else False

    grid["tradability_proxy_pass"] = (
        grid["observed"]
        & grid["close"].shift(30).notna()
        & (
            grid["recent_observed_count"]
            >= RECENT_MIN_BARS
        )
        & (
            grid["recent_positive_volume_count"]
            >= RECENT_MIN_POSITIVE_VOLUME_BARS
        )
        & (
            grid["recent_close_change_count"]
            >= RECENT_MIN_CLOSE_CHANGES
        )
        & grid["normalized_momentum_30m"].notna()
    )
    return grid


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(
        span=span,
        adjust=False,
        min_periods=span,
    ).mean()


def rsi_wilder(
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = gain.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    average_loss = loss.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    relative_strength = (
        average_gain / average_loss.replace(0.0, np.nan)
    )
    result = 100.0 - 100.0 / (1.0 + relative_strength)
    return result.where(average_loss != 0.0, 100.0)


def kdj(
    bars: pd.DataFrame,
    period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    lowest = bars["low"].rolling(
        period,
        min_periods=period,
    ).min()
    highest = bars["high"].rolling(
        period,
        min_periods=period,
    ).max()
    denominator = (highest - lowest).replace(0.0, np.nan)
    rsv = (
        (bars["close"] - lowest)
        / denominator
        * 100.0
    ).fillna(50.0)

    k = pd.Series(index=bars.index, dtype=float)
    d = pd.Series(index=bars.index, dtype=float)
    previous_k = 50.0
    previous_d = 50.0
    for index, value in rsv.items():
        previous_k = (
            (2.0 / 3.0) * previous_k
            + (1.0 / 3.0) * float(value)
        )
        previous_d = (
            (2.0 / 3.0) * previous_d
            + (1.0 / 3.0) * previous_k
        )
        k.loc[index] = previous_k
        d.loc[index] = previous_d
    return k, d, 3.0 * k - 2.0 * d


def diagnostic_5m_at(
    grid: pd.DataFrame,
    signal_minute: int,
) -> dict[str, float]:
    observed = grid.loc[
        :signal_minute,
        ["open", "high", "low", "close", "volume"],
    ].copy()
    observed["bucket"] = observed.index // 5
    bars = (
        observed.dropna(subset=["close"])
        .groupby("bucket", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            minute_count=("close", "size"),
        )
    )
    if bars.empty:
        return {
            "rsi14": math.nan,
            "macd_dif": math.nan,
            "macd_dea": math.nan,
            "macd_hist": math.nan,
            "kdj_k": math.nan,
            "kdj_d": math.nan,
            "kdj_j": math.nan,
        }

    bars["rsi14"] = rsi_wilder(bars["close"], 14)
    bars["macd_dif"] = (
        ema(bars["close"], 12)
        - ema(bars["close"], 26)
    )
    bars["macd_dea"] = ema(bars["macd_dif"], 9)
    bars["macd_hist"] = (
        bars["macd_dif"] - bars["macd_dea"]
    )
    k, d, j = kdj(bars)
    bars["kdj_k"] = k
    bars["kdj_d"] = d
    bars["kdj_j"] = j
    row = bars.iloc[-1]
    return {
        column: (
            float(row[column])
            if pd.notna(row[column])
            else math.nan
        )
        for column in (
            "rsi14",
            "macd_dif",
            "macd_dea",
            "macd_hist",
            "kdj_k",
            "kdj_d",
            "kdj_j",
        )
    }


def build_candidate(
    session_date: str,
    qqq_grid: pd.DataFrame,
    soxx_grid: pd.DataFrame,
) -> dict[str, Any] | None:
    if not bool(qqq_grid["initial_range_complete"].iloc[0]):
        return None
    if not bool(soxx_grid["initial_range_complete"].iloc[0]):
        return None

    signal_slice = pd.RangeIndex(
        SIGNAL_START,
        SIGNAL_END + 1,
    )
    qqq = qqq_grid.loc[signal_slice]
    soxx = soxx_grid.loc[signal_slice]

    qqq_long = (
        qqq["tradability_proxy_pass"]
        & (qqq["close"] > qqq["initial_range_high"])
        & (qqq["close"] > qqq["vwap"])
        & (qqq["ret_30m"] > 0)
    ).fillna(False)
    soxx_long = (
        soxx["tradability_proxy_pass"]
        & (soxx["close"] > soxx["initial_range_high"])
        & (soxx["close"] > soxx["vwap"])
        & (soxx["ret_30m"] > 0)
    ).fillna(False)

    qqq_short = (
        qqq["tradability_proxy_pass"]
        & (qqq["close"] < qqq["initial_range_low"])
        & (qqq["close"] < qqq["vwap"])
        & (qqq["ret_30m"] < 0)
    ).fillna(False)
    soxx_short = (
        soxx["tradability_proxy_pass"]
        & (soxx["close"] < soxx["initial_range_low"])
        & (soxx["close"] < soxx["vwap"])
        & (soxx["ret_30m"] < 0)
    ).fillna(False)

    long_state = qqq_long & soxx_long
    short_state = qqq_short & soxx_short
    long_transition = (
        long_state
        & ~long_state.shift(1, fill_value=False)
    )
    short_transition = (
        short_state
        & ~short_state.shift(1, fill_value=False)
    )

    triggers = pd.DataFrame(
        {
            "LONG": long_transition,
            "SHORT": short_transition,
        },
        index=signal_slice,
    )
    locations = np.argwhere(triggers.to_numpy(dtype=bool))
    if len(locations) == 0:
        return None

    row_location, direction_location = locations[0]
    signal_minute = int(triggers.index[int(row_location)])
    direction = str(triggers.columns[int(direction_location)])

    qqq_row = qqq_grid.loc[signal_minute]
    soxx_row = soxx_grid.loc[signal_minute]
    qqq_norm = float(qqq_row["normalized_momentum_30m"])
    soxx_norm = float(soxx_row["normalized_momentum_30m"])

    if direction == "LONG":
        execution_symbol = (
            "SOXL" if soxx_norm > qqq_norm else "TQQQ"
        )
    else:
        execution_symbol = (
            "SOXS" if soxx_norm < qqq_norm else "SQQQ"
        )

    qqq_diag = diagnostic_5m_at(qqq_grid, signal_minute)
    soxx_diag = diagnostic_5m_at(soxx_grid, signal_minute)

    candidate: dict[str, Any] = {
        "session_date": session_date,
        "calendar_year": int(session_date[:4]),
        "study_period": study_period(int(session_date[:4])),
        "direction": direction,
        "execution_symbol": execution_symbol,
        "signal_session_minute": signal_minute,
        "signal_timestamp_utc": qqq_row["timestamp_utc"],
        "signal_timestamp_et": qqq_row["timestamp_et"],
        "qqq_initial_range_bar_count": int(
            qqq_row["initial_range_bar_count"]
        ),
        "soxx_initial_range_bar_count": int(
            soxx_row["initial_range_bar_count"]
        ),
        "qqq_initial_range_high": float(
            qqq_row["initial_range_high"]
        ),
        "qqq_initial_range_low": float(
            qqq_row["initial_range_low"]
        ),
        "soxx_initial_range_high": float(
            soxx_row["initial_range_high"]
        ),
        "soxx_initial_range_low": float(
            soxx_row["initial_range_low"]
        ),
        "qqq_close": float(qqq_row["close"]),
        "soxx_close": float(soxx_row["close"]),
        "qqq_vwap": float(qqq_row["vwap"]),
        "soxx_vwap": float(soxx_row["vwap"]),
        "qqq_ret_30m": float(qqq_row["ret_30m"]),
        "soxx_ret_30m": float(soxx_row["ret_30m"]),
        "qqq_normalized_momentum_30m": qqq_norm,
        "soxx_normalized_momentum_30m": soxx_norm,
        "relative_normalized_momentum": soxx_norm - qqq_norm,
        "qqq_recent_observed_count": int(
            qqq_row["recent_observed_count"]
        ),
        "soxx_recent_observed_count": int(
            soxx_row["recent_observed_count"]
        ),
        "qqq_recent_positive_volume_count": int(
            qqq_row["recent_positive_volume_count"]
        ),
        "soxx_recent_positive_volume_count": int(
            soxx_row["recent_positive_volume_count"]
        ),
        "qqq_recent_close_change_count": int(
            qqq_row["recent_close_change_count"]
        ),
        "soxx_recent_close_change_count": int(
            soxx_row["recent_close_change_count"]
        ),
    }
    for column, value in qqq_diag.items():
        candidate[f"qqq_{column}_diagnostic"] = value
    for column, value in soxx_diag.items():
        candidate[f"soxx_{column}_diagnostic"] = value
    return candidate


def cost_adjusted_long_return(
    entry_open: float,
    exit_close: float,
) -> float:
    if (
        not np.isfinite(entry_open)
        or not np.isfinite(exit_close)
        or entry_open <= 0
        or exit_close <= 0
    ):
        return math.nan
    return (
        exit_close * (1.0 - EXIT_COST)
        / (entry_open * (1.0 + ENTRY_COST))
        - 1.0
    )


def exit_minute(entry_minute: int, variant: str) -> int:
    if variant == "FIXED_30M":
        return entry_minute + 30
    if variant == "FIXED_60M":
        return entry_minute + 60
    if variant == "SESSION_0355":
        return SESSION_EXIT_MINUTE
    raise StudyError(f"Unknown exit variant: {variant}")


def return_from_grid(
    grid: pd.DataFrame,
    entry_minute: int,
    variant: str,
) -> tuple[float, dict[str, Any]] | None:
    target = exit_minute(entry_minute, variant)
    if target >= SESSION_LENGTH:
        return None
    entry = grid.loc[entry_minute]
    exit_row = grid.loc[target]
    if (
        pd.isna(entry["open"])
        or pd.isna(exit_row["close"])
        or pd.isna(entry["timestamp_utc"])
        or pd.isna(exit_row["timestamp_utc"])
    ):
        return None
    value = cost_adjusted_long_return(
        float(entry["open"]),
        float(exit_row["close"]),
    )
    if not np.isfinite(value):
        return None
    return value, {
        "entry_timestamp_utc": entry["timestamp_utc"],
        "entry_timestamp_et": entry["timestamp_et"],
        "entry_price_raw": float(entry["open"]),
        "entry_price_with_cost": float(entry["open"]) * (1.0 + ENTRY_COST),
        "exit_timestamp_utc": exit_row["timestamp_utc"],
        "exit_timestamp_et": exit_row["timestamp_et"],
        "exit_price_raw": float(exit_row["close"]),
        "exit_price_after_cost": float(exit_row["close"]) * (1.0 - EXIT_COST),
        "holding_minutes": target - entry_minute,
    }


def simulate_candidate(
    candidate: Mapping[str, Any],
    grids: Mapping[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    entry_minute = int(candidate["signal_session_minute"]) + 1
    selected_symbol = str(candidate["execution_symbol"])
    direction = str(candidate["direction"])
    direction_symbols = (
        ("TQQQ", "SOXL")
        if direction == "LONG"
        else ("SQQQ", "SOXS")
    )

    rows: list[dict[str, Any]] = []
    for variant in EXIT_VARIANTS:
        selected = return_from_grid(
            grids[selected_symbol],
            entry_minute,
            variant,
        )
        if selected is None:
            continue
        selected_return, details = selected

        pair_returns: list[float] = []
        for symbol in direction_symbols:
            result = return_from_grid(
                grids[symbol],
                entry_minute,
                variant,
            )
            if result is not None:
                pair_returns.append(float(result[0]))
        pair_mean = (
            float(np.mean(pair_returns))
            if len(pair_returns) == 2
            else math.nan
        )

        rows.append(
            {
                **dict(candidate),
                "exit_variant": variant,
                "entry_session_minute": entry_minute,
                **details,
                "instrument_net_return": selected_return,
                "position_weight": FIXED_ACCOUNT_WEIGHT,
                "account_trade_return": (
                    FIXED_ACCOUNT_WEIGHT * selected_return
                ),
                "direction_pair_baseline_count": len(pair_returns),
                "direction_pair_mean_net_return": pair_mean,
                "selection_excess_return": (
                    selected_return - pair_mean
                    if np.isfinite(pair_mean)
                    else math.nan
                ),
            }
        )
    return rows


def load_vix_diagnostics(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise StudyError(f"VIX daily file not found: {path}")
    frame = (
        pd.read_parquet(path)
        if path.suffix.lower() == ".parquet"
        else pd.read_csv(path)
    )
    mapping = {
        str(column).strip().upper(): str(column)
        for column in frame.columns
    }
    if "DATE" not in mapping or "CLOSE" not in mapping:
        raise StudyError("VIX daily requires DATE and CLOSE columns")

    result = pd.DataFrame(
        {
            "vix_date": pd.to_datetime(
                frame[mapping["DATE"]],
                errors="raise",
            ).dt.normalize(),
            "vix_close": pd.to_numeric(
                frame[mapping["CLOSE"]],
                errors="raise",
            ),
        }
    ).sort_values(
        "vix_date",
        kind="mergesort",
    ).drop_duplicates(
        "vix_date",
        keep="last",
    ).reset_index(drop=True)

    if len(result) < 7000 or (result["vix_close"] <= 0).any():
        raise StudyError("Official VIX daily history is invalid")

    result["vix_rate_1d"] = result["vix_close"].pct_change()
    result["vix_rate_3d"] = (
        result["vix_close"]
        / result["vix_close"].shift(3)
        - 1.0
    )

    absolute = result["vix_rate_1d"].abs().to_numpy(dtype=float)
    percentile = np.full(len(result), np.nan, dtype=float)
    for index in range(253, len(result)):
        current = absolute[index]
        history = absolute[index - 252:index]
        if np.isfinite(current) and np.isfinite(history).all():
            percentile[index] = float(np.mean(history <= current))
    result["vix_abs_rate_pctl_252"] = percentile
    return result


def attach_vix_diagnostics(
    candidates: pd.DataFrame,
    vix: pd.DataFrame,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    left = candidates.copy()
    left["vix_cutoff_date"] = (
        pd.to_datetime(left["session_date"])
        - pd.Timedelta(days=1)
    )
    right = vix.sort_values("vix_date", kind="mergesort")
    result = pd.merge_asof(
        left.sort_values("vix_cutoff_date"),
        right,
        left_on="vix_cutoff_date",
        right_on="vix_date",
        direction="backward",
    )
    return result.sort_values(
        "session_date",
        kind="mergesort",
    ).reset_index(drop=True)


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def maximum_drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (1.0 + clean).cumprod()
    peaks = nav.cummax()
    return float((nav / peaks - 1.0).min())


def cumulative_return(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    return float(
        np.prod(1.0 + clean.to_numpy(dtype=float)) - 1.0
    )


def daily_account_returns(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        ["exit_variant", "study_period", "session_date"],
        sort=True,
    ):
        variant, period, session_date = keys
        returns = pd.to_numeric(
            group["account_trade_return"],
            errors="coerce",
        ).dropna()
        rows.append(
            {
                "exit_variant": variant,
                "study_period": period,
                "session_date": session_date,
                "calendar_year": int(str(session_date)[:4]),
                "daily_return": (
                    float(np.prod(1.0 + returns.to_numpy(dtype=float)) - 1.0)
                    if len(returns)
                    else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_periods(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in EXIT_VARIANTS:
        for period in PERIODS:
            group = trades.loc[
                (trades["exit_variant"] == variant)
                & (trades["study_period"] == period)
            ]
            days = daily.loc[
                (daily["exit_variant"] == variant)
                & (daily["study_period"] == period)
            ]
            if group.empty:
                continue

            instrument = group["instrument_net_return"]
            account = group["account_trade_return"]
            excess = group["selection_excess_return"].dropna()
            rows.append(
                {
                    "exit_variant": variant,
                    "study_period": period,
                    "trade_count": int(len(group)),
                    "long_trade_count": int(
                        (group["direction"] == "LONG").sum()
                    ),
                    "short_trade_count": int(
                        (group["direction"] == "SHORT").sum()
                    ),
                    "mean_instrument_net_return": float(instrument.mean()),
                    "median_instrument_net_return": float(instrument.median()),
                    "positive_rate": float((instrument > 0).mean()),
                    "profit_factor": profit_factor(account),
                    "mean_account_trade_return": float(account.mean()),
                    "cumulative_return": cumulative_return(days["daily_return"]),
                    "max_drawdown": maximum_drawdown(days["daily_return"]),
                    "pair_baseline_eligible_trade_count": int(len(excess)),
                    "mean_selection_excess_return": (
                        float(excess.mean()) if len(excess) else math.nan
                    ),
                    "mean_signal_session_minute": float(
                        group["signal_session_minute"].mean()
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["period_order"] = result["study_period"].map(PERIOD_ORDER)
        result = result.sort_values(
            ["exit_variant", "period_order"],
            kind="mergesort",
        ).drop(columns=["period_order"])
    return result


def summarize_years(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, days in daily.groupby(
        ["exit_variant", "calendar_year"],
        sort=True,
    ):
        variant, year = keys
        group = trades.loc[
            (trades["exit_variant"] == variant)
            & (trades["calendar_year"] == year)
        ]
        rows.append(
            {
                "exit_variant": variant,
                "calendar_year": int(year),
                "trade_count": int(len(group)),
                "cumulative_return": cumulative_return(days["daily_return"]),
                "max_drawdown": maximum_drawdown(days["daily_return"]),
                "mean_instrument_net_return": float(
                    group["instrument_net_return"].mean()
                ),
                "median_instrument_net_return": float(
                    group["instrument_net_return"].median()
                ),
                "positive_rate": float(
                    (group["instrument_net_return"] > 0).mean()
                ),
                "profit_factor": profit_factor(
                    group["account_trade_return"]
                ),
            }
        )
    return pd.DataFrame(rows)


def period_row(
    frame: pd.DataFrame,
    variant: str,
    period: str,
) -> pd.Series | None:
    rows = frame.loc[
        (frame["exit_variant"] == variant)
        & (frame["study_period"] == period)
    ]
    return None if rows.empty else rows.iloc[0]


def build_qualification(
    period: pd.DataFrame,
    year: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant in EXIT_VARIANTS:
        full_count = int(
            period.loc[
                period["exit_variant"] == variant,
                "trade_count",
            ].sum()
        )
        validation = period_row(
            period,
            variant,
            "2023-2024_VALIDATION",
        )
        confirmation = period_row(
            period,
            variant,
            "2025-2026_YTD_CONFIRMATION",
        )
        validation_count = (
            int(validation["trade_count"])
            if validation is not None
            else 0
        )
        confirmation_count = (
            int(confirmation["trade_count"])
            if confirmation is not None
            else 0
        )
        sample_evaluable = bool(
            full_count >= MIN_FULL_HISTORY_TRADES
            and validation_count >= MIN_VALIDATION_TRADES
            and confirmation_count >= MIN_CONFIRMATION_TRADES
        )

        mean_positive = bool(
            sample_evaluable
            and float(validation["mean_instrument_net_return"]) > 0
            and float(confirmation["mean_instrument_net_return"]) > 0
        )
        median_positive = bool(
            sample_evaluable
            and float(validation["median_instrument_net_return"]) > 0
            and float(confirmation["median_instrument_net_return"]) > 0
        )
        pf_pass = bool(
            sample_evaluable
            and float(validation["profit_factor"]) > 1.0
            and float(confirmation["profit_factor"]) > 1.0
        )
        cumulative_positive = bool(
            sample_evaluable
            and float(validation["cumulative_return"]) > 0
            and float(confirmation["cumulative_return"]) > 0
        )

        year_rows = year.loc[year["exit_variant"] == variant]
        positive_years = year_rows.loc[
            year_rows["cumulative_return"] > 0,
            "cumulative_return",
        ]
        single_year_share = (
            float(positive_years.max() / positive_years.sum())
            if len(positive_years)
            and float(positive_years.sum()) > 0
            else math.nan
        )
        year_pass = bool(
            np.isfinite(single_year_share)
            and single_year_share <= MAX_SINGLE_POSITIVE_YEAR_SHARE
        )
        candidate = bool(
            sample_evaluable
            and mean_positive
            and median_positive
            and pf_pass
            and cumulative_positive
            and year_pass
        )
        rows.append(
            {
                "exit_variant": variant,
                "full_history_trade_count": full_count,
                "validation_trade_count": validation_count,
                "confirmation_trade_count": confirmation_count,
                "sample_evaluable": sample_evaluable,
                "mean_positive_both_periods": mean_positive,
                "median_positive_both_periods": median_positive,
                "profit_factor_pass_both_periods": pf_pass,
                "cumulative_return_positive_both_periods": cumulative_positive,
                "single_positive_year_profit_share": single_year_share,
                "year_concentration_pass": year_pass,
                "research_candidate_for_next_stage": candidate,
            }
        )
    return pd.DataFrame(rows)


def choose_decision(
    qualification: pd.DataFrame,
) -> tuple[str, list[str]]:
    supported = qualification.loc[
        qualification["research_candidate_for_next_stage"],
        "exit_variant",
    ].astype(str).tolist()
    if supported:
        return (
            "OVERNIGHT_BASELINE_CANDIDATE_SUPPORTED_FOR_INDEPENDENT_REPLICATION",
            supported,
        )
    if not bool(qualification["sample_evaluable"].any()):
        return (
            "OVERNIGHT_BASELINE_INCONCLUSIVE_INSUFFICIENT_TRADABLE_SAMPLE",
            [],
        )
    return ("NO_OVERNIGHT_BASELINE_CANDIDATE_QUALIFIED", [])


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_instrument_net_return",
        "median_instrument_net_return",
        "mean_account_trade_return",
        "mean_selection_excess_return",
        "cumulative_return",
        "max_drawdown",
    }:
        return f"{float(value) * 10000:.2f}"
    if column == "positive_rate":
        return f"{float(value) * 100:.2f}"
    if column == "profit_factor":
        numeric = float(value)
        return "INF" if np.isinf(numeric) else f"{numeric:.3f}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.3f}"
    return str(value)


def print_table(title: str, frame: pd.DataFrame) -> None:
    print()
    print(f"========== {title} ==========")
    if frame.empty:
        print("NO_ROWS")
        return
    display = frame.copy()
    for column in display.columns:
        display[column] = [
            format_value(column, value)
            for value in display[column]
        ]
    print(display.to_string(index=False))


def run_study(
    v22_061_summary_path: Path,
    v22_056_summary_path: Path,
    vix_daily_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    for path in (
        v22_061_summary_path,
        v22_056_summary_path,
        vix_daily_path,
        canonical_root,
    ):
        if not path.exists():
            raise StudyError(f"Missing required input: {path}")

    summary_061 = json.loads(
        v22_061_summary_path.read_text(encoding="utf-8-sig")
    )
    summary_056 = json.loads(
        v22_056_summary_path.read_text(encoding="utf-8-sig")
    )
    validate_v22_061(summary_061)
    validate_v22_056(summary_056)

    canonical = index_canonical(canonical_root)
    partition_counts = {
        symbol: sum(
            1 for current, _, _ in canonical if current == symbol
        )
        for symbol in ALL_SYMBOLS
    }

    symbol_tables = {
        symbol: load_symbol_overnight(symbol, canonical)
        for symbol in ALL_SYMBOLS
    }
    session_sets = {
        symbol: set(
            table.index.get_level_values("session_date").unique()
        )
        for symbol, table in symbol_tables.items()
    }
    common_signal_sessions = sorted(
        session_sets["QQQ"] & session_sets["SOXX"]
    )

    funnel = {
        "common_signal_session_count": len(common_signal_sessions),
        "both_initial_ranges_complete_count": 0,
        "tradability_proxy_any_signal_minute_count": 0,
        "signal_candidate_count": 0,
        "long_candidate_count": 0,
        "short_candidate_count": 0,
        "all_execution_symbols_present_session_count": 0,
        "all_three_exit_variants_executable_count": 0,
    }

    candidate_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for session_date in common_signal_sessions:
        qqq_grid = session_grid(
            get_session(symbol_tables["QQQ"], session_date)
        )
        soxx_grid = session_grid(
            get_session(symbol_tables["SOXX"], session_date)
        )

        both_initial = bool(
            qqq_grid["initial_range_complete"].iloc[0]
            and soxx_grid["initial_range_complete"].iloc[0]
        )
        if both_initial:
            funnel["both_initial_ranges_complete_count"] += 1

        signal_range = pd.RangeIndex(SIGNAL_START, SIGNAL_END + 1)
        any_tradable = bool(
            (
                qqq_grid.loc[
                    signal_range,
                    "tradability_proxy_pass",
                ]
                & soxx_grid.loc[
                    signal_range,
                    "tradability_proxy_pass",
                ]
            ).any()
        )
        if any_tradable:
            funnel["tradability_proxy_any_signal_minute_count"] += 1

        candidate = build_candidate(
            session_date,
            qqq_grid,
            soxx_grid,
        )
        if candidate is None:
            continue

        funnel["signal_candidate_count"] += 1
        funnel[
            (
                "long_candidate_count"
                if candidate["direction"] == "LONG"
                else "short_candidate_count"
            )
        ] += 1

        grids: dict[str, pd.DataFrame] = {
            "QQQ": qqq_grid,
            "SOXX": soxx_grid,
        }
        all_execution_present = True
        for symbol in EXECUTION_SYMBOLS:
            day = get_session(symbol_tables[symbol], session_date)
            if day.empty:
                all_execution_present = False
            grids[symbol] = session_grid(day)
        if all_execution_present:
            funnel[
                "all_execution_symbols_present_session_count"
            ] += 1

        rows = simulate_candidate(candidate, grids)
        if len(rows) == len(EXIT_VARIANTS):
            funnel[
                "all_three_exit_variants_executable_count"
            ] += 1
        candidate_rows.append(candidate)
        trade_rows.extend(rows)

    candidates = pd.DataFrame(candidate_rows)
    trades = pd.DataFrame(trade_rows)
    if candidates.empty:
        raise StudyError("No overnight candidate was generated")
    if trades.empty:
        raise StudyError("No executable overnight trade was generated")

    vix = load_vix_diagnostics(vix_daily_path)
    candidates = attach_vix_diagnostics(candidates, vix)
    trades = trades.merge(
        candidates[
            [
                "session_date",
                "vix_date",
                "vix_close",
                "vix_rate_1d",
                "vix_rate_3d",
                "vix_abs_rate_pctl_252",
            ]
        ],
        on="session_date",
        how="left",
        validate="many_to_one",
    )

    candidates = candidates.sort_values(
        "session_date",
        kind="mergesort",
    ).reset_index(drop=True)
    trades = trades.sort_values(
        ["session_date", "exit_variant"],
        kind="mergesort",
    ).reset_index(drop=True)

    daily = daily_account_returns(trades)
    period = summarize_periods(trades, daily)
    year = summarize_years(trades, daily)
    qualification = build_qualification(period, year)
    final_decision, supported = choose_decision(qualification)

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "candidates": result_dir
        / "v22_062n_signal_candidates.csv",
        "trades": result_dir / "v22_062n_trades.csv",
        "daily": result_dir
        / "v22_062n_daily_account_returns.csv",
        "period": result_dir
        / "v22_062n_period_summary.csv",
        "year": result_dir
        / "v22_062n_year_summary.csv",
        "qualification": result_dir
        / "v22_062n_qualification.csv",
        "funnel": result_dir
        / "v22_062n_tradability_funnel.csv",
        "manifest": result_dir
        / "v22_062n_manifest.json",
        "summary": result_dir / "v22_062n_summary.json",
    }

    frames = {
        "candidates": candidates,
        "trades": trades,
        "daily": daily,
        "period": period,
        "year": year,
        "qualification": qualification,
        "funnel": pd.DataFrame([funnel]),
    }
    for name, frame in frames.items():
        frame.to_csv(
            outputs[name],
            index=False,
            encoding="utf-8-sig",
        )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": final_decision,
        "v22_061_validated": True,
        "v22_056_validated": True,
        "rth_orb_architecture_used": False,
        "pullback_reentry_architecture_used": False,
        "session_name": "OVERNIGHT",
        "session_start_et": "20:00",
        "session_end_et": "03:59",
        "initial_range_start_et": "20:00",
        "initial_range_end_et": "20:59",
        "signal_start_et": "21:00",
        "signal_end_et": "02:54",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "exit_variants": list(EXIT_VARIANTS),
        "entry_cost_bps": ENTRY_COST * 10000,
        "exit_cost_bps": EXIT_COST * 10000,
        "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "diagnostic_indicators_recorded": True,
        "canonical_partition_count_indexed": len(canonical),
        "canonical_partition_read_operations": len(canonical),
        "canonical_partition_count_by_symbol": partition_counts,
        "common_signal_session_count": len(common_signal_sessions),
        "signal_candidate_count": int(len(candidates)),
        "long_candidate_count": int(
            (candidates["direction"] == "LONG").sum()
        ),
        "short_candidate_count": int(
            (candidates["direction"] == "SHORT").sum()
        ),
        "trade_record_count": int(len(trades)),
        "trade_count_by_exit_variant": {
            variant: int(
                (trades["exit_variant"] == variant).sum()
            )
            for variant in EXIT_VARIANTS
        },
        "supported_exit_variants_for_replication": supported,
        "parameter_sweep_executed": False,
        "session_window_sweep_executed": False,
        "initial_range_length_sweep_executed": False,
        "liquidity_threshold_sweep_executed": False,
        "indicator_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "open_d_called": False,
        "history_download_executed": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "outputs": {
            name: str(path)
            for name, path in outputs.items()
        },
    }
    atomic_json(outputs["summary"], summary)

    manifest = {
        "version": VERSION,
        "generated_at_utc": datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "v22_061_summary": str(v22_061_summary_path),
            "v22_061_summary_sha256": sha256_file(
                v22_061_summary_path
            ),
            "v22_056_summary": str(v22_056_summary_path),
            "v22_056_summary_sha256": sha256_file(
                v22_056_summary_path
            ),
            "vix_daily": str(vix_daily_path),
            "vix_daily_sha256": sha256_file(vix_daily_path),
            "canonical_root": str(canonical_root),
        },
        "frozen_design": {
            "session_et": ["20:00", "03:59"],
            "initial_range_et": ["20:00", "20:59"],
            "signal_window_et": ["21:00", "02:54"],
            "maximum_entries_per_session": 1,
            "exit_variants": list(EXIT_VARIANTS),
            "round_trip_cost_bps": 10,
            "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
            "tradability_proxy": {
                "initial_range_min_bars": INITIAL_RANGE_MIN_BARS,
                "recent_window_minutes": RECENT_WINDOW,
                "recent_min_bars": RECENT_MIN_BARS,
                "recent_min_positive_volume_bars": (
                    RECENT_MIN_POSITIVE_VOLUME_BARS
                ),
                "recent_min_close_changes": (
                    RECENT_MIN_CLOSE_CHANGES
                ),
            },
        },
        "guards": {
            "parameter_sweep_executed": False,
            "indicator_entry_gates_used": False,
            "vix_entry_gate_used": False,
            "canonical_files_modified": False,
            "raw_files_modified": False,
            "new_market_data_cache_created": False,
            "broker_action_allowed": False,
            "paper_trading_allowed": False,
            "official_adoption_allowed": False,
        },
    }
    atomic_json(outputs["manifest"], manifest)

    print("==============================================")
    print(" V22.062N overnight synchronized trend baseline")
    print("==============================================")
    print_table("Qualification", qualification)
    print_table(
        "Validation / Confirmation performance",
        period.loc[
            period["study_period"].isin(
                [
                    "2023-2024_VALIDATION",
                    "2025-2026_YTD_CONFIRMATION",
                ]
            )
        ],
    )
    print_table(
        "Tradability funnel",
        pd.DataFrame([funnel]),
    )

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={final_decision}")
    print("V22_061_VALIDATED=True")
    print("V22_056_VALIDATED=True")
    print("RTH_ORB_ARCHITECTURE_USED=False")
    print("PULLBACK_REENTRY_ARCHITECTURE_USED=False")
    print(f"CANONICAL_PARTITION_COUNT_INDEXED={len(canonical)}")
    print(
        f"CANONICAL_PARTITION_READ_OPERATIONS={len(canonical)}"
    )
    print(
        f"COMMON_SIGNAL_SESSION_COUNT="
        f"{len(common_signal_sessions)}"
    )
    print(f"SIGNAL_CANDIDATE_COUNT={len(candidates)}")
    print(
        f"LONG_CANDIDATE_COUNT="
        f"{int((candidates['direction'] == 'LONG').sum())}"
    )
    print(
        f"SHORT_CANDIDATE_COUNT="
        f"{int((candidates['direction'] == 'SHORT').sum())}"
    )
    for variant in EXIT_VARIANTS:
        print(
            f"TRADE_COUNT_{variant}="
            f"{int((trades['exit_variant'] == variant).sum())}"
        )
    print(
        "SUPPORTED_EXIT_VARIANTS_FOR_REPLICATION="
        f"{supported}"
    )
    print("TRADABILITY_PROXY_USED=True")
    print("BID_ASK_SPREAD_AVAILABLE=False")
    print("ORDER_BOOK_DEPTH_AVAILABLE=False")
    print("RSI_ENTRY_GATE_USED=False")
    print("MACD_ENTRY_GATE_USED=False")
    print("KDJ_ENTRY_GATE_USED=False")
    print("VIX_ENTRY_GATE_USED=False")
    print("VIX_RISK_SCALING_USED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("SESSION_WINDOW_SWEEP_EXECUTED=False")
    print("INITIAL_RANGE_LENGTH_SWEEP_EXECUTED=False")
    print("LIQUIDITY_THRESHOLD_SWEEP_EXECUTED=False")
    print("INDICATOR_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("EXIT_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("OPEN_D_CALLED=False")
    print("HISTORY_DOWNLOAD_EXECUTED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={result_dir}")

    return {
        "summary": summary,
        "qualification": qualification,
        "period": period,
        "funnel": funnel,
    }


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-061-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.061_FAST3_SYNCHRONIZED_OPENING_RANGE_BREAKOUT_BASELINE_R1"
            r"\v22_061_summary.json"
        ),
    )
    parser.add_argument(
        "--v22-056-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.056_FAST3_CBOE_DAILY_VIX_INGEST_AND_PIT_REGIME_R1"
            r"\v22_056_summary.json"
        ),
    )
    parser.add_argument(
        "--vix-daily",
        default=(
            r"D:\us-tech-quant-data\fast3\vix_cboe_daily"
            r"\canonical\vix_daily.parquet"
        ),
    )
    parser.add_argument(
        "--canonical-root",
        default=(
            r"D:\us-tech-quant-data\fast3"
            r"\moomoo_24h_1m\canonical"
        ),
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.062N_FAST3_OVERNIGHT_SYNCHRONIZED_TREND_BASELINE_R1"
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
        run_study(
            v22_061_summary_path=Path(args.v22_061_summary),
            v22_056_summary_path=Path(args.v22_056_summary),
            vix_daily_path=Path(args.vix_daily),
            canonical_root=Path(args.canonical_root),
            result_dir=Path(args.result_dir),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
