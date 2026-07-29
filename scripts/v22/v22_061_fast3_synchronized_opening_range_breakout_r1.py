#!/usr/bin/env python
r"""
V22.061 FAST3 synchronized opening-range breakout baseline R1.

Research hypothesis
-------------------
The previous pullback/re-entry architecture is frozen and terminated. This
stage tests a structurally independent, simple synchronized opening-range
breakout using QQQ and SOXX as signal assets and leveraged ETFs only as
execution instruments.

Frozen signal
-------------
- RTH opening range: 09:30 through 09:59 ET, exactly 30 completed minutes.
- Signal window: 10:00 through 14:30 ET.
- LONG:
    QQQ and SOXX both close above their opening-range highs,
    both close above cumulative RTH typical-price VWAP,
    and both exact 15-minute returns are positive.
- SHORT:
    QQQ and SOXX both close below their opening-range lows,
    both close below cumulative RTH typical-price VWAP,
    and both exact 15-minute returns are negative.
- Trigger only when the synchronized state changes from false to true.
- First valid trigger only; maximum one entry per trading day.
- Entry at the exact next-minute open.

Frozen execution selection
--------------------------
LONG:
    SOXX 15-minute return > QQQ 15-minute return -> SOXL
    otherwise -> TQQQ
SHORT:
    SOXX 15-minute return < QQQ 15-minute return -> SOXS
    otherwise -> SQQQ

Frozen exits
------------
- FIXED_30M
- FIXED_60M
- SESSION_1555
No hard stop, trailing stop, no-progress exit or factor invalidation is used.

Costs and sizing
----------------
- 5 bps at entry and 5 bps at exit.
- Fixed 33% account weight for research comparability.
- No overnight position.

Diagnostics only
----------------
- 5-minute RSI(14), MACD(12,26,9), KDJ(9,3,3).
- Prior-day official Cboe VIX 1-day change, 3-day change and absolute-change
  percentile.
None of these diagnostic values is allowed to delete or create a signal.

Guards
------
- No parameter sweep.
- No opening-range-length sweep.
- No breakout-buffer sweep.
- No RSI/MACD/KDJ/VIX gate.
- No broker or paper trading.
- No RAW or Canonical mutation.
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


VERSION = (
    "V22.061_FAST3_SYNCHRONIZED_OPENING_RANGE_BREAKOUT_BASELINE_R1"
)

SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "SESSION_1555")

RTH_START = 9 * 60 + 30
RTH_END = 15 * 60 + 59
OPENING_RANGE_END = 9 * 60 + 59
SIGNAL_START = 10 * 60
SIGNAL_END = 14 * 60 + 30
SESSION_EXIT_MINUTE = 15 * 60 + 55

ENTRY_COST = 0.0005
EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.33
MIN_PIT_BASELINE_COUNT = 20

MIN_FULL_HISTORY_TRADES = 100
MIN_VALIDATION_TRADES = 30
MIN_CONFIRMATION_TRADES = 30
MAX_SINGLE_POSITIVE_YEAR_SHARE = 0.60

PERIODS = (
    "2018-2022_DEVELOPMENT",
    "2023-2024_VALIDATION",
    "2025-2026_YTD_CONFIRMATION",
)
PERIOD_ORDER = {period: index for index, period in enumerate(PERIODS)}


class StudyError(RuntimeError):
    """V22.061 cannot continue safely."""


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else math.nan

    def add(self, value: float) -> None:
        if np.isfinite(value):
            self.count += 1
            self.total += float(value)


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


def validate_v22_060(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": (
            "NO_RISK_SCALER_OR_EXIT_ARCHITECTURE_QUALIFIED"
        ),
        "v22_059_validated": True,
        "v22_059a_validated": True,
        "source_variant": "NO_VIX_CONTROL",
        "canonical_partition_count_read": 0,
        "etf_minute_data_read": False,
        "backtest_entry_signal_regenerated": False,
        "parameter_sweep_executed": False,
        "risk_threshold_optimization_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "open_d_called": False,
        "history_download_executed": False,
        "intraday_vix_used": False,
        "vix_proxy_used": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "recommended_exit_variant": None,
        "risk_metrics_pass": False,
        "tradable_edge_pass": False,
        "hard_stop_capture_problem": False,
        "next_stage": "STOP_CURRENT_FAST3_ENTRY_ARCHITECTURE",
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise StudyError(
            "V22.060 lineage validation failed: " + "; ".join(failures)
        )


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
    return result


def load_rth_partition(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "timestamp_et",
                "trade_date",
                "minute_et",
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
    mask = (minute_et >= RTH_START) & (minute_et <= RTH_END)

    frame = pd.DataFrame(
        {
            "timestamp_utc": timestamp.loc[mask],
            "timestamp_et": timestamp_et.loc[mask],
            "trade_date": (
                timestamp_et.loc[mask].dt.strftime("%Y-%m-%d")
            ),
            "minute_et": minute_et.loc[mask].astype(int),
            "open": pd.to_numeric(
                raw.loc[
                    mask,
                    find_column(raw, ("open",)),
                ],
                errors="coerce",
            ),
            "high": pd.to_numeric(
                raw.loc[
                    mask,
                    find_column(raw, ("high",)),
                ],
                errors="coerce",
            ),
            "low": pd.to_numeric(
                raw.loc[
                    mask,
                    find_column(raw, ("low",)),
                ],
                errors="coerce",
            ),
            "close": pd.to_numeric(
                raw.loc[
                    mask,
                    find_column(raw, ("close",)),
                ],
                errors="coerce",
            ),
            "volume": pd.to_numeric(
                raw.loc[
                    mask,
                    find_column(raw, ("volume",)),
                ],
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

    if frame["timestamp_utc"].duplicated().any():
        raise StudyError(f"Duplicate RTH timestamp: {path}")
    if (
        (frame["low"] > frame["high"]).any()
        or (frame["close"] < frame["low"]).any()
        or (frame["close"] > frame["high"]).any()
    ):
        raise StudyError(f"Invalid RTH OHLC relationship: {path}")
    return frame


def enrich_minute_day(frame: pd.DataFrame) -> pd.DataFrame:
    day = frame.sort_values(
        "timestamp_utc",
        kind="mergesort",
    ).reset_index(drop=True).copy()
    if day.empty:
        return day

    opening = day.loc[
        (day["minute_et"] >= RTH_START)
        & (day["minute_et"] <= OPENING_RANGE_END)
    ]
    expected_minutes = set(
        range(RTH_START, OPENING_RANGE_END + 1)
    )
    if (
        len(opening) != 30
        or set(opening["minute_et"].astype(int)) != expected_minutes
    ):
        day["opening_range_complete"] = False
        day["opening_range_high"] = np.nan
        day["opening_range_low"] = np.nan
    else:
        day["opening_range_complete"] = True
        day["opening_range_high"] = float(opening["high"].max())
        day["opening_range_low"] = float(opening["low"].min())

    volume = day["volume"].clip(lower=0.0)
    typical = (day["high"] + day["low"] + day["close"]) / 3.0
    cumulative_volume = volume.cumsum()
    cumulative_value = (typical * volume).cumsum()
    fallback = day["close"].expanding().mean()
    day["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(fallback)
    day["ret_15m"] = day["close"] / day["close"].shift(15) - 1.0
    return day


def aggregate_complete_5m(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["bucket"] = (
        (work["minute_et"] - RTH_START) // 5
    ).astype(int)
    bars = (
        work.groupby(["trade_date", "bucket"], sort=True)
        .agg(
            timestamp_utc=("timestamp_utc", "max"),
            timestamp_et=("timestamp_et", "max"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            minute_count=("close", "size"),
        )
        .reset_index()
    )
    return bars.loc[
        bars["minute_count"] == 5
    ].reset_index(drop=True)


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
    frame: pd.DataFrame,
    period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    lowest = frame["low"].rolling(
        period,
        min_periods=period,
    ).min()
    highest = frame["high"].rolling(
        period,
        min_periods=period,
    ).max()
    denominator = (highest - lowest).replace(0.0, np.nan)
    rsv = (
        (frame["close"] - lowest)
        / denominator
        * 100.0
    ).fillna(50.0)

    k = pd.Series(index=frame.index, dtype=float)
    d = pd.Series(index=frame.index, dtype=float)
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


def add_diagnostic_factors(
    bars: pd.DataFrame,
) -> pd.DataFrame:
    result = bars.sort_values(
        "timestamp_utc",
        kind="mergesort",
    ).reset_index(drop=True).copy()
    if result.empty:
        return result
    result["rsi14"] = rsi_wilder(result["close"], 14)
    result["macd_dif"] = (
        ema(result["close"], 12)
        - ema(result["close"], 26)
    )
    result["macd_dea"] = ema(result["macd_dif"], 9)
    result["macd_hist"] = (
        result["macd_dif"] - result["macd_dea"]
    )
    k, d, j = kdj(result, 9)
    result["kdj_k"] = k
    result["kdj_d"] = d
    result["kdj_j"] = j
    return result


def latest_diagnostic(
    factors: pd.DataFrame,
    timestamp: pd.Timestamp,
    trade_date: str,
) -> dict[str, float]:
    if factors.empty:
        return {
            "rsi14": math.nan,
            "macd_dif": math.nan,
            "macd_dea": math.nan,
            "macd_hist": math.nan,
            "kdj_k": math.nan,
            "kdj_d": math.nan,
            "kdj_j": math.nan,
        }
    timestamps = factors["timestamp_utc"]
    location = int(
        timestamps.searchsorted(timestamp, side="right") - 1
    )
    if location < 0:
        return {
            "rsi14": math.nan,
            "macd_dif": math.nan,
            "macd_dea": math.nan,
            "macd_hist": math.nan,
            "kdj_k": math.nan,
            "kdj_d": math.nan,
            "kdj_j": math.nan,
        }
    row = factors.iloc[location]
    if str(row["trade_date"]) != trade_date:
        return {
            "rsi14": math.nan,
            "macd_dif": math.nan,
            "macd_dea": math.nan,
            "macd_hist": math.nan,
            "kdj_k": math.nan,
            "kdj_d": math.nan,
            "kdj_j": math.nan,
        }
    return {
        column: float(row[column])
        if pd.notna(row[column])
        else math.nan
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


def rolling_prior_abs_percentile(
    daily_return: pd.Series,
    window: int = 252,
) -> pd.Series:
    values = (
        pd.to_numeric(daily_return, errors="coerce")
        .abs()
        .to_numpy(dtype=float)
    )
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(window + 1, len(values)):
        current = values[index - 1]
        history = values[index - window - 1 : index - 1]
        if (
            np.isfinite(current)
            and len(history) == window
            and np.isfinite(history).all()
        ):
            output[index] = float(np.mean(history <= current))
    return pd.Series(output, index=daily_return.index, dtype=float)


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
            "trade_date_timestamp": pd.to_datetime(
                frame[mapping["DATE"]],
                errors="raise",
            ),
            "vix_close": pd.to_numeric(
                frame[mapping["CLOSE"]],
                errors="raise",
            ),
        }
    ).sort_values(
        "trade_date_timestamp",
        kind="mergesort",
    ).drop_duplicates(
        "trade_date_timestamp",
        keep="last",
    ).reset_index(drop=True)

    if len(result) < 7000 or (result["vix_close"] <= 0).any():
        raise StudyError("Official VIX daily history is invalid")

    daily_return = result["vix_close"].pct_change()
    result["vix_rate_1d_prior"] = daily_return.shift(1)
    result["vix_rate_3d_prior"] = (
        result["vix_close"].shift(1)
        / result["vix_close"].shift(4)
        - 1.0
    )
    result["vix_abs_rate_pctl_252_prior"] = (
        rolling_prior_abs_percentile(daily_return, 252)
    )
    result["trade_date"] = result[
        "trade_date_timestamp"
    ].dt.strftime("%Y-%m-%d")
    return result[
        [
            "trade_date",
            "vix_rate_1d_prior",
            "vix_rate_3d_prior",
            "vix_abs_rate_pctl_252_prior",
        ]
    ].drop_duplicates("trade_date", keep="last")


def align_signal_days(
    qqq_day: pd.DataFrame,
    soxx_day: pd.DataFrame,
) -> pd.DataFrame:
    qqq = enrich_minute_day(qqq_day)
    soxx = enrich_minute_day(soxx_day)
    if qqq.empty or soxx.empty:
        return pd.DataFrame()

    qqq = qqq.set_index("timestamp_utc").add_prefix("qqq_")
    soxx = soxx.set_index("timestamp_utc").add_prefix("soxx_")
    aligned = qqq.join(soxx, how="inner")
    aligned = aligned.loc[
        aligned["qqq_trade_date"] == aligned["soxx_trade_date"]
    ].copy()
    aligned["trade_date"] = aligned["qqq_trade_date"]
    aligned["signal_timestamp_utc"] = aligned.index
    aligned["signal_timestamp_et"] = aligned["qqq_timestamp_et"]
    aligned["minute_et"] = aligned["qqq_minute_et"].astype(int)
    return aligned.sort_index()


def build_first_candidate(
    aligned: pd.DataFrame,
) -> dict[str, Any] | None:
    if aligned.empty:
        return None
    if not bool(aligned["qqq_opening_range_complete"].all()):
        return None
    if not bool(aligned["soxx_opening_range_complete"].all()):
        return None

    work = aligned.loc[
        (aligned["minute_et"] >= SIGNAL_START)
        & (aligned["minute_et"] <= SIGNAL_END)
    ].copy()
    if work.empty:
        return None

    long_state = (
        (work["qqq_close"] > work["qqq_opening_range_high"])
        & (work["soxx_close"] > work["soxx_opening_range_high"])
        & (work["qqq_close"] > work["qqq_vwap"])
        & (work["soxx_close"] > work["soxx_vwap"])
        & (work["qqq_ret_15m"] > 0)
        & (work["soxx_ret_15m"] > 0)
    ).fillna(False)

    short_state = (
        (work["qqq_close"] < work["qqq_opening_range_low"])
        & (work["soxx_close"] < work["soxx_opening_range_low"])
        & (work["qqq_close"] < work["qqq_vwap"])
        & (work["soxx_close"] < work["soxx_vwap"])
        & (work["qqq_ret_15m"] < 0)
        & (work["soxx_ret_15m"] < 0)
    ).fillna(False)

    long_transition = long_state & ~long_state.shift(1, fill_value=False)
    short_transition = short_state & ~short_state.shift(1, fill_value=False)

    triggers = pd.DataFrame(
        {
            "LONG": long_transition,
            "SHORT": short_transition,
        },
        index=work.index,
    )
    locations = np.argwhere(
        triggers.to_numpy(dtype=bool)
    )
    if len(locations) == 0:
        return None

    row_location, direction_location = locations[0]
    timestamp = triggers.index[int(row_location)]
    direction = triggers.columns[int(direction_location)]
    row = work.loc[timestamp]
    if isinstance(row, pd.DataFrame):
        raise StudyError("Duplicate aligned signal timestamp")

    qqq_return = float(row["qqq_ret_15m"])
    soxx_return = float(row["soxx_ret_15m"])
    if direction == "LONG":
        execution_symbol = (
            "SOXL" if soxx_return > qqq_return else "TQQQ"
        )
    else:
        execution_symbol = (
            "SOXS" if soxx_return < qqq_return else "SQQQ"
        )

    return {
        "trade_date": str(row["trade_date"]),
        "calendar_year": int(str(row["trade_date"])[:4]),
        "study_period": study_period(
            int(str(row["trade_date"])[:4])
        ),
        "direction": direction,
        "execution_symbol": execution_symbol,
        "signal_timestamp_utc": pd.Timestamp(timestamp),
        "signal_timestamp_et": pd.Timestamp(
            row["signal_timestamp_et"]
        ),
        "signal_minute_et": int(row["minute_et"]),
        "qqq_opening_range_high": float(
            row["qqq_opening_range_high"]
        ),
        "qqq_opening_range_low": float(
            row["qqq_opening_range_low"]
        ),
        "soxx_opening_range_high": float(
            row["soxx_opening_range_high"]
        ),
        "soxx_opening_range_low": float(
            row["soxx_opening_range_low"]
        ),
        "qqq_close": float(row["qqq_close"]),
        "soxx_close": float(row["soxx_close"]),
        "qqq_vwap": float(row["qqq_vwap"]),
        "soxx_vwap": float(row["soxx_vwap"]),
        "qqq_ret_15m": qqq_return,
        "soxx_ret_15m": soxx_return,
        "relative_return_15m": soxx_return - qqq_return,
    }


def execution_index(day: pd.DataFrame) -> pd.DataFrame:
    table = day.sort_values(
        "timestamp_utc",
        kind="mergesort",
    ).set_index("timestamp_utc", drop=False)
    if table.index.has_duplicates:
        raise StudyError("Execution day has duplicate timestamp")
    return table


def exact_exit_timestamp(
    entry_timestamp: pd.Timestamp,
    entry_row: pd.Series,
    variant: str,
) -> pd.Timestamp:
    if variant == "FIXED_30M":
        return entry_timestamp + pd.Timedelta(minutes=30)
    if variant == "FIXED_60M":
        return entry_timestamp + pd.Timedelta(minutes=60)
    if variant == "SESSION_1555":
        entry_et = pd.Timestamp(entry_row["timestamp_et"])
        target_et = entry_et.normalize() + pd.Timedelta(
            minutes=SESSION_EXIT_MINUTE
        )
        return target_et.tz_convert("UTC")
    raise StudyError(f"Unknown exit variant: {variant}")


def cost_adjusted_return(
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
    entry_fill = entry_open * (1.0 + ENTRY_COST)
    exit_fill = exit_close * (1.0 - EXIT_COST)
    return exit_fill / entry_fill - 1.0


def simulate_candidate(
    candidate: Mapping[str, Any],
    execution_day: pd.DataFrame,
    baseline: Mapping[
        tuple[str, str, int],
        RunningStats,
    ],
) -> list[dict[str, Any]]:
    table = execution_index(execution_day)
    signal_timestamp = pd.Timestamp(
        candidate["signal_timestamp_utc"]
    )
    entry_timestamp = signal_timestamp + pd.Timedelta(minutes=1)
    if entry_timestamp not in table.index:
        return []

    entry_row = table.loc[entry_timestamp]
    if isinstance(entry_row, pd.DataFrame):
        raise StudyError("Duplicate execution entry timestamp")
    entry_open = float(entry_row["open"])
    entry_minute = int(entry_row["minute_et"])

    rows: list[dict[str, Any]] = []
    for variant in EXIT_VARIANTS:
        exit_timestamp = exact_exit_timestamp(
            entry_timestamp,
            entry_row,
            variant,
        )
        if exit_timestamp not in table.index:
            continue
        exit_row = table.loc[exit_timestamp]
        if isinstance(exit_row, pd.DataFrame):
            raise StudyError("Duplicate execution exit timestamp")

        net_return = cost_adjusted_return(
            entry_open,
            float(exit_row["close"]),
        )
        if not np.isfinite(net_return):
            continue

        key = (
            str(candidate["execution_symbol"]),
            variant,
            entry_minute,
        )
        stats = baseline.get(key, RunningStats())
        baseline_count = int(stats.count)
        baseline_mean = float(stats.mean)
        pit_eligible = (
            baseline_count >= MIN_PIT_BASELINE_COUNT
            and np.isfinite(baseline_mean)
        )
        rows.append(
            {
                **dict(candidate),
                "exit_variant": variant,
                "entry_timestamp_utc": entry_timestamp,
                "entry_timestamp_et": pd.Timestamp(
                    entry_row["timestamp_et"]
                ),
                "entry_minute_et": entry_minute,
                "entry_price_raw": entry_open,
                "entry_price_with_cost": (
                    entry_open * (1.0 + ENTRY_COST)
                ),
                "exit_timestamp_utc": exit_timestamp,
                "exit_timestamp_et": pd.Timestamp(
                    exit_row["timestamp_et"]
                ),
                "exit_price_raw": float(exit_row["close"]),
                "exit_price_after_cost": (
                    float(exit_row["close"])
                    * (1.0 - EXIT_COST)
                ),
                "holding_minutes": int(
                    (
                        exit_timestamp - entry_timestamp
                    )
                    / pd.Timedelta(minutes=1)
                ),
                "instrument_net_return": net_return,
                "position_weight": FIXED_ACCOUNT_WEIGHT,
                "account_trade_return": (
                    FIXED_ACCOUNT_WEIGHT * net_return
                ),
                "pit_baseline_count": baseline_count,
                "pit_baseline_mean_net_return": baseline_mean,
                "pit_baseline_eligible": bool(pit_eligible),
                "entry_excess_pit": (
                    net_return - baseline_mean
                    if pit_eligible
                    else math.nan
                ),
            }
        )
    return rows


def update_baseline_for_day(
    symbol: str,
    day: pd.DataFrame,
    baseline: dict[
        tuple[str, str, int],
        RunningStats,
    ],
) -> None:
    if day.empty:
        return
    table = execution_index(day)
    by_minute = {
        int(row["minute_et"]): timestamp
        for timestamp, row in table.iterrows()
    }
    for entry_minute in range(SIGNAL_START + 1, SIGNAL_END + 2):
        entry_timestamp = by_minute.get(entry_minute)
        if entry_timestamp is None:
            continue
        entry_row = table.loc[entry_timestamp]
        entry_open = float(entry_row["open"])

        for variant in EXIT_VARIANTS:
            exit_timestamp = exact_exit_timestamp(
                pd.Timestamp(entry_timestamp),
                entry_row,
                variant,
            )
            if exit_timestamp not in table.index:
                continue
            exit_close = float(table.loc[exit_timestamp, "close"])
            net_return = cost_adjusted_return(
                entry_open,
                exit_close,
            )
            key = (symbol, variant, entry_minute)
            baseline.setdefault(key, RunningStats()).add(net_return)


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
        ["exit_variant", "study_period", "trade_date"],
        sort=True,
    ):
        variant, period, trade_date = keys
        returns = pd.to_numeric(
            group["account_trade_return"],
            errors="coerce",
        ).dropna()
        rows.append(
            {
                "exit_variant": variant,
                "study_period": period,
                "trade_date": trade_date,
                "calendar_year": int(str(trade_date)[:4]),
                "daily_return": (
                    float(
                        np.prod(
                            1.0 + returns.to_numpy(dtype=float)
                        )
                        - 1.0
                    )
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
            pit = group.loc[
                group["pit_baseline_eligible"],
                "entry_excess_pit",
            ].dropna()
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
                    "mean_instrument_net_return": float(
                        instrument.mean()
                    ),
                    "median_instrument_net_return": float(
                        instrument.median()
                    ),
                    "positive_rate": float(
                        (instrument > 0).mean()
                    ),
                    "profit_factor": profit_factor(account),
                    "mean_account_trade_return": float(
                        account.mean()
                    ),
                    "cumulative_return": cumulative_return(
                        days["daily_return"]
                    ),
                    "max_drawdown": maximum_drawdown(
                        days["daily_return"]
                    ),
                    "pit_eligible_trade_count": int(len(pit)),
                    "mean_entry_excess_pit": (
                        float(pit.mean())
                        if len(pit)
                        else math.nan
                    ),
                    "mean_signal_minute_et": float(
                        group["signal_minute_et"].mean()
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["period_order"] = result[
            "study_period"
        ].map(PERIOD_ORDER)
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
                "cumulative_return": cumulative_return(
                    days["daily_return"]
                ),
                "max_drawdown": maximum_drawdown(
                    days["daily_return"]
                ),
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

        direction_positive = bool(
            sample_evaluable
            and float(validation["mean_instrument_net_return"]) > 0
            and float(confirmation["mean_instrument_net_return"]) > 0
        )
        median_positive = bool(
            sample_evaluable
            and float(validation["median_instrument_net_return"]) > 0
            and float(confirmation["median_instrument_net_return"]) > 0
        )
        profit_factor_pass = bool(
            sample_evaluable
            and float(validation["profit_factor"]) > 1.0
            and float(confirmation["profit_factor"]) > 1.0
        )
        pit_excess_positive = bool(
            sample_evaluable
            and int(validation["pit_eligible_trade_count"])
            >= MIN_VALIDATION_TRADES
            and int(confirmation["pit_eligible_trade_count"])
            >= MIN_CONFIRMATION_TRADES
            and float(validation["mean_entry_excess_pit"]) > 0
            and float(confirmation["mean_entry_excess_pit"]) > 0
        )

        year_rows = year.loc[
            year["exit_variant"] == variant
        ]
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
        year_concentration_pass = bool(
            np.isfinite(single_year_share)
            and single_year_share
            <= MAX_SINGLE_POSITIVE_YEAR_SHARE
        )

        candidate = bool(
            sample_evaluable
            and direction_positive
            and median_positive
            and profit_factor_pass
            and pit_excess_positive
            and year_concentration_pass
        )
        rows.append(
            {
                "exit_variant": variant,
                "full_history_trade_count": full_count,
                "validation_trade_count": validation_count,
                "confirmation_trade_count": confirmation_count,
                "sample_evaluable": sample_evaluable,
                "mean_positive_both_periods": direction_positive,
                "median_positive_both_periods": median_positive,
                "profit_factor_pass_both_periods": profit_factor_pass,
                "pit_excess_positive_both_periods": (
                    pit_excess_positive
                ),
                "single_positive_year_profit_share": (
                    single_year_share
                ),
                "year_concentration_pass": year_concentration_pass,
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
            "ORB_BASELINE_CANDIDATE_SUPPORTED_FOR_INDEPENDENT_REPLICATION",
            supported,
        )
    if not bool(qualification["sample_evaluable"].any()):
        return (
            "ORB_BASELINE_INCONCLUSIVE_INSUFFICIENT_SAMPLE",
            [],
        )
    return ("NO_ORB_BASELINE_CANDIDATE_QUALIFIED", [])


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_instrument_net_return",
        "median_instrument_net_return",
        "mean_account_trade_return",
        "mean_entry_excess_pit",
        "cumulative_return",
        "max_drawdown",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {"positive_rate"}:
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
    v22_060_summary_path: Path,
    v22_056_summary_path: Path,
    vix_daily_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    for path in (
        v22_060_summary_path,
        v22_056_summary_path,
        vix_daily_path,
        canonical_root,
    ):
        if not path.exists():
            raise StudyError(f"Missing required input: {path}")

    v22_060_summary = json.loads(
        v22_060_summary_path.read_text(encoding="utf-8-sig")
    )
    v22_056_summary = json.loads(
        v22_056_summary_path.read_text(encoding="utf-8-sig")
    )
    validate_v22_060(v22_060_summary)
    validate_v22_056(v22_056_summary)

    canonical = index_canonical(canonical_root)
    partition_counts = {
        symbol: sum(
            1 for current, _, _ in canonical if current == symbol
        )
        for symbol in ALL_SYMBOLS
    }
    months = sorted(
        {(year, month) for _, year, month in canonical}
    )
    vix = load_vix_diagnostics(vix_daily_path).set_index(
        "trade_date"
    )

    baseline: dict[
        tuple[str, str, int],
        RunningStats,
    ] = {}
    candidate_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    funnel = {
        "month_count": len(months),
        "calendar_day_count_seen": 0,
        "common_signal_day_count": 0,
        "opening_range_complete_day_count": 0,
        "candidate_day_count": 0,
        "long_candidate_count": 0,
        "short_candidate_count": 0,
        "execution_failure_day_count": 0,
    }

    read_operations = 0
    for year, month in months:
        month_tables: dict[str, pd.DataFrame] = {}
        for symbol in ALL_SYMBOLS:
            key = (symbol, year, month)
            if key not in canonical:
                raise StudyError(
                    f"Missing monthly Canonical partition: {key}"
                )
            month_tables[symbol] = load_rth_partition(
                canonical[key]
            )
            read_operations += 1

        factor_tables = {
            symbol: add_diagnostic_factors(
                aggregate_complete_5m(month_tables[symbol])
            )
            for symbol in SIGNAL_SYMBOLS
        }

        date_sets = {
            symbol: set(
                month_tables[symbol]["trade_date"].unique()
            )
            for symbol in ALL_SYMBOLS
        }
        all_dates = sorted(set.union(*date_sets.values()))
        signal_dates = sorted(
            date_sets["QQQ"] & date_sets["SOXX"]
        )
        funnel["calendar_day_count_seen"] += len(all_dates)
        funnel["common_signal_day_count"] += len(signal_dates)

        by_symbol_day = {
            symbol: {
                trade_date: group.copy()
                for trade_date, group in table.groupby(
                    "trade_date",
                    sort=True,
                )
            }
            for symbol, table in month_tables.items()
        }

        for trade_date in signal_dates:
            qqq_day = by_symbol_day["QQQ"][trade_date]
            soxx_day = by_symbol_day["SOXX"][trade_date]
            aligned = align_signal_days(qqq_day, soxx_day)
            if aligned.empty:
                continue

            opening_complete = bool(
                aligned["qqq_opening_range_complete"].all()
                and aligned[
                    "soxx_opening_range_complete"
                ].all()
            )
            if opening_complete:
                funnel[
                    "opening_range_complete_day_count"
                ] += 1

            candidate = build_first_candidate(aligned)
            if candidate is not None:
                vix_row = (
                    vix.loc[trade_date]
                    if trade_date in vix.index
                    else None
                )
                if isinstance(vix_row, pd.DataFrame):
                    vix_row = vix_row.iloc[-1]

                for symbol in SIGNAL_SYMBOLS:
                    diagnostic = latest_diagnostic(
                        factor_tables[symbol],
                        pd.Timestamp(
                            candidate["signal_timestamp_utc"]
                        ),
                        trade_date,
                    )
                    prefix = symbol.lower()
                    for column, value in diagnostic.items():
                        candidate[
                            f"{prefix}_{column}_diagnostic"
                        ] = value

                candidate["vix_rate_1d_prior_diagnostic"] = (
                    float(vix_row["vix_rate_1d_prior"])
                    if vix_row is not None
                    and pd.notna(vix_row["vix_rate_1d_prior"])
                    else math.nan
                )
                candidate["vix_rate_3d_prior_diagnostic"] = (
                    float(vix_row["vix_rate_3d_prior"])
                    if vix_row is not None
                    and pd.notna(vix_row["vix_rate_3d_prior"])
                    else math.nan
                )
                candidate[
                    "vix_abs_rate_pctl_252_prior_diagnostic"
                ] = (
                    float(
                        vix_row[
                            "vix_abs_rate_pctl_252_prior"
                        ]
                    )
                    if vix_row is not None
                    and pd.notna(
                        vix_row[
                            "vix_abs_rate_pctl_252_prior"
                        ]
                    )
                    else math.nan
                )

                candidate_rows.append(dict(candidate))
                funnel["candidate_day_count"] += 1
                funnel[
                    (
                        "long_candidate_count"
                        if candidate["direction"] == "LONG"
                        else "short_candidate_count"
                    )
                ] += 1

                execution_symbol = str(
                    candidate["execution_symbol"]
                )
                execution_day = by_symbol_day[
                    execution_symbol
                ].get(trade_date)
                if execution_day is None:
                    funnel[
                        "execution_failure_day_count"
                    ] += 1
                else:
                    trades = simulate_candidate(
                        candidate,
                        execution_day,
                        baseline,
                    )
                    if not trades:
                        funnel[
                            "execution_failure_day_count"
                        ] += 1
                    trade_rows.extend(trades)

            # Prior-only baseline: add the current day only after its
            # candidate has been evaluated.
            for symbol in EXECUTION_SYMBOLS:
                execution_day = by_symbol_day[symbol].get(
                    trade_date
                )
                if execution_day is not None:
                    update_baseline_for_day(
                        symbol,
                        execution_day,
                        baseline,
                    )

    candidates = pd.DataFrame(candidate_rows)
    trades = pd.DataFrame(trade_rows)
    if candidates.empty:
        raise StudyError("No synchronized ORB candidate was generated")
    if trades.empty:
        raise StudyError("No executable ORB trade was generated")

    trades = trades.sort_values(
        ["trade_date", "exit_variant"],
        kind="mergesort",
    ).reset_index(drop=True)
    candidates = candidates.sort_values(
        "trade_date",
        kind="mergesort",
    ).reset_index(drop=True)

    daily = daily_account_returns(trades)
    period = summarize_periods(trades, daily)
    year_summary = summarize_years(trades, daily)
    qualification = build_qualification(
        period,
        year_summary,
    )
    final_decision, supported = choose_decision(
        qualification
    )

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "candidates": result_dir
        / "v22_061_signal_candidates.csv",
        "trades": result_dir / "v22_061_trades.csv",
        "daily": result_dir
        / "v22_061_daily_account_returns.csv",
        "period": result_dir
        / "v22_061_period_summary.csv",
        "year": result_dir
        / "v22_061_year_summary.csv",
        "qualification": result_dir
        / "v22_061_qualification.csv",
        "funnel": result_dir
        / "v22_061_signal_funnel.csv",
        "manifest": result_dir
        / "v22_061_manifest.json",
        "summary": result_dir / "v22_061_summary.json",
    }

    candidates.to_csv(
        outputs["candidates"],
        index=False,
        encoding="utf-8-sig",
    )
    trades.to_csv(
        outputs["trades"],
        index=False,
        encoding="utf-8-sig",
    )
    daily.to_csv(
        outputs["daily"],
        index=False,
        encoding="utf-8-sig",
    )
    period.to_csv(
        outputs["period"],
        index=False,
        encoding="utf-8-sig",
    )
    year_summary.to_csv(
        outputs["year"],
        index=False,
        encoding="utf-8-sig",
    )
    qualification.to_csv(
        outputs["qualification"],
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame([funnel]).to_csv(
        outputs["funnel"],
        index=False,
        encoding="utf-8-sig",
    )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": final_decision,
        "v22_060_validated": True,
        "v22_056_validated": True,
        "previous_pullback_reentry_architecture_used": False,
        "opening_range_start_et": "09:30",
        "opening_range_end_et": "09:59",
        "opening_range_minutes": 30,
        "signal_start_et": "10:00",
        "signal_end_et": "14:30",
        "maximum_entries_per_day": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "exit_variants": list(EXIT_VARIANTS),
        "entry_cost_bps": ENTRY_COST * 10000,
        "exit_cost_bps": EXIT_COST * 10000,
        "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "diagnostic_indicators_recorded": True,
        "canonical_partition_count_indexed": int(
            len(canonical)
        ),
        "canonical_partition_read_operations": int(
            read_operations
        ),
        "canonical_partition_count_by_symbol": (
            partition_counts
        ),
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
            "v22_060_summary": str(
                v22_060_summary_path
            ),
            "v22_060_summary_sha256": sha256_file(
                v22_060_summary_path
            ),
            "v22_056_summary": str(
                v22_056_summary_path
            ),
            "v22_056_summary_sha256": sha256_file(
                v22_056_summary_path
            ),
            "vix_daily": str(vix_daily_path),
            "vix_daily_sha256": sha256_file(
                vix_daily_path
            ),
            "canonical_root": str(canonical_root),
        },
        "frozen_design": {
            "opening_range_minutes": 30,
            "signal_window_et": [
                "10:00",
                "14:30",
            ],
            "maximum_entries_per_day": 1,
            "exit_variants": list(EXIT_VARIANTS),
            "round_trip_cost_bps": 10,
            "fixed_account_weight": (
                FIXED_ACCOUNT_WEIGHT
            ),
            "minimum_full_history_trades": (
                MIN_FULL_HISTORY_TRADES
            ),
            "minimum_validation_trades": (
                MIN_VALIDATION_TRADES
            ),
            "minimum_confirmation_trades": (
                MIN_CONFIRMATION_TRADES
            ),
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
    print(" V22.061 synchronized opening-range breakout")
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

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={final_decision}")
    print("V22_060_VALIDATED=True")
    print("V22_056_VALIDATED=True")
    print(
        "PREVIOUS_PULLBACK_REENTRY_ARCHITECTURE_USED=False"
    )
    print(
        f"CANONICAL_PARTITION_COUNT_INDEXED={len(canonical)}"
    )
    print(
        f"CANONICAL_PARTITION_READ_OPERATIONS={read_operations}"
    )
    print(
        f"SIGNAL_CANDIDATE_COUNT={len(candidates)}"
    )
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
    print("RSI_ENTRY_GATE_USED=False")
    print("MACD_ENTRY_GATE_USED=False")
    print("KDJ_ENTRY_GATE_USED=False")
    print("VIX_ENTRY_GATE_USED=False")
    print("VIX_RISK_SCALING_USED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print(
        "OPENING_RANGE_LENGTH_SWEEP_EXECUTED=False"
    )
    print("BREAKOUT_BUFFER_SWEEP_EXECUTED=False")
    print(
        "INDICATOR_THRESHOLD_OPTIMIZATION_EXECUTED=False"
    )
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
        "result_dir": result_dir,
        "outputs": outputs,
    }


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-060-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.060_FAST3_VIX_MAGNITUDE_RISK_AND_EXIT_CAPTURE_R1"
            r"\v22_060_summary.json"
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
            r"\V22.061_FAST3_SYNCHRONIZED_OPENING_RANGE_BREAKOUT_BASELINE_R1"
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
            v22_060_summary_path=Path(
                args.v22_060_summary
            ),
            v22_056_summary_path=Path(
                args.v22_056_summary
            ),
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
