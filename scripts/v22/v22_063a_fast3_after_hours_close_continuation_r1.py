#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

VERSION = "V22.063A_FAST3_AFTER_HOURS_CLOSE_CONTINUATION_BASELINE_R1"
SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "SESSION_1955")

RTH_START_ET = 9 * 60 + 30
RTH_CLOSE_ET = 15 * 60 + 59
RTH_LAG_30_ET = 15 * 60 + 29
AH_START_ET = 16 * 60
AH_END_ET = 19 * 60 + 59
AH_LENGTH = 240
SIGNAL_START = 30
SIGNAL_END = 150
SESSION_EXIT_MINUTE = 235

RECENT_WINDOW = 30
RECENT_MIN_OBSERVED = 15
RECENT_MIN_POSITIVE_VOLUME = 10
RECENT_MIN_CLOSE_CHANGES = 5
VOL_WINDOW = 30
VOL_MIN_RETURNS = 15

ENTRY_COST = 0.0005
EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.20
JUMP_THRESHOLD = 0.20
FACTOR_TOLERANCE = 0.03
ALLOWED_SPLIT_FACTORS = (
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    8.0,
    10.0,
    15.0,
    20.0,
    25.0,
    30.0,
    40.0,
    50.0,
    100.0,
)

MIN_FULL_HISTORY_TRADES = 100
MIN_VALIDATION_TRADES = 30
MIN_CONFIRMATION_TRADES = 30
MAX_TOP1_SHARE = 0.50
MAX_TOP5_SHARE = 0.80
MAX_POSITIVE_YEAR_SHARE = 0.60

PERIODS = (
    "2018-2022_DEVELOPMENT",
    "2023-2024_VALIDATION",
    "2025-2026_YTD_CONFIRMATION",
)
PERIOD_ORDER = {period: index for index, period in enumerate(PERIODS)}


class StudyError(RuntimeError):
    pass


def study_period(year: int) -> str:
    if 2018 <= year <= 2022:
        return "2018-2022_DEVELOPMENT"
    if 2023 <= year <= 2024:
        return "2023-2024_VALIDATION"
    if 2025 <= year <= 2026:
        return "2025-2026_YTD_CONFIRMATION"
    return "OUTSIDE_STUDY"


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        match = re.fullmatch(r"symbol=(.+)", part, re.I)
        if match:
            symbol = match.group(1).upper().replace("US.", "")
        match = re.fullmatch(r"year=(\d{4})", part, re.I)
        if match:
            year = match.group(1)
        match = re.fullmatch(r"month=(\d{1,2})", part, re.I)
        if match:
            month = f"{int(match.group(1)):02d}"
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

    counts = {
        symbol: sum(
            1 for current, _, _ in result
            if current == symbol
        )
        for symbol in ALL_SYMBOLS
    }
    if any(count == 0 for count in counts.values()):
        raise StudyError(f"Missing Canonical symbol partitions: {counts}")
    if len(set(counts.values())) != 1:
        raise StudyError(f"Unbalanced Canonical partition counts: {counts}")
    if len(result) != 582:
        raise StudyError(
            f"Expected 582 Canonical partitions, found {len(result)}"
        )
    return result


def find_column(
    frame: pd.DataFrame,
    aliases: Iterable[str],
) -> str:
    mapping = {
        str(column).strip().lower(): str(column)
        for column in frame.columns
    }
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise StudyError(f"Missing column from aliases={tuple(aliases)}")


def load_symbol_full(
    symbol: str,
    canonical: Mapping[tuple[str, str, str], Path],
) -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    paths_read: list[str] = []

    paths = [
        path
        for (current, _, _), path in sorted(canonical.items())
        if current == symbol
    ]
    for path in paths:
        raw = pd.read_parquet(path)
        paths_read.append(str(path))
        if raw.empty:
            continue

        timestamp = pd.to_datetime(
            raw[find_column(raw, ("timestamp_utc",))],
            errors="raise",
            utc=True,
        )
        frame = pd.DataFrame(
            {
                "timestamp_utc": timestamp,
                "open": pd.to_numeric(
                    raw[find_column(raw, ("open",))],
                    errors="coerce",
                ),
                "high": pd.to_numeric(
                    raw[find_column(raw, ("high",))],
                    errors="coerce",
                ),
                "low": pd.to_numeric(
                    raw[find_column(raw, ("low",))],
                    errors="coerce",
                ),
                "close": pd.to_numeric(
                    raw[find_column(raw, ("close",))],
                    errors="coerce",
                ),
                "volume": pd.to_numeric(
                    raw[find_column(raw, ("volume",))],
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
        frames.append(frame)

    if not frames:
        return pd.DataFrame(), paths_read

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp_utc", kind="mergesort")
        .drop_duplicates("timestamp_utc", keep="last")
        .reset_index(drop=True)
    )
    if (
        (combined["low"] > combined["high"]).any()
        or (combined["close"] < combined["low"]).any()
        or (combined["close"] > combined["high"]).any()
    ):
        raise StudyError(f"Invalid OHLC for {symbol}")
    return combined, paths_read


def split_factor_candidates() -> np.ndarray:
    values = set(ALLOWED_SPLIT_FACTORS)
    values.update(
        1.0 / value
        for value in ALLOWED_SPLIT_FACTORS
    )
    return np.array(sorted(values), dtype=float)


def snap_split_factor(
    raw_ratio: float,
) -> tuple[float, float] | None:
    if not np.isfinite(raw_ratio) or raw_ratio <= 0:
        return None
    factors = split_factor_candidates()
    errors = np.abs(factors / raw_ratio - 1.0)
    location = int(np.argmin(errors))
    factor = float(factors[location])
    error = float(errors[location])
    if error <= FACTOR_TOLERANCE:
        return factor, error
    return None

def validate_lineage(
    overnight: Mapping[str, Any],
    forward: Mapping[str, Any],
    rth: Mapping[str, Any],
) -> None:
    checks = [
        (
            overnight,
            {
                "final_status": "PASS",
                "final_decision": (
                    "OVERNIGHT_VWAP_MEAN_REVERSION_"
                    "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
                ),
                "v22_062pr_validated": True,
                "premarket_forward_chain_modified": False,
                "parameter_sweep_executed": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "broker_action_allowed": False,
                "paper_trading_allowed": False,
                "official_adoption_allowed": False,
            },
            "V22.063N",
        ),
        (
            forward,
            {
                "final_status": "PASS",
                "v22_062pb_validated": True,
                "research_cutoff_date": "2026-07-24",
                "forward_holdout_only": True,
                "rule_change_requires_reset": True,
                "sole_exit_variant": "PREMARKET_0925",
                "historical_pre_cutoff_outcomes_used_for_qualification": False,
                "parameter_sweep_executed": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "broker_action_allowed": False,
                "paper_trading_allowed": False,
                "official_adoption_allowed": False,
            },
            "V22.062PR",
        ),
        (
            rth,
            {
                "final_status": "PASS",
                "final_decision": (
                    "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED"
                ),
                "v22_062pr_validated": True,
                "premarket_forward_chain_modified": False,
                "parameter_sweep_executed": False,
                "canonical_files_modified": False,
                "raw_files_modified": False,
                "broker_action_allowed": False,
                "paper_trading_allowed": False,
                "official_adoption_allowed": False,
            },
            "V22.063R1",
        ),
    ]
    failures: list[str] = []
    for summary, expected, name in checks:
        for key, value in expected.items():
            if summary.get(key) != value:
                failures.append(
                    f"{name}.{key}: expected {value!r}, got {summary.get(key)!r}"
                )
    if failures:
        raise StudyError("Lineage validation failed: " + "; ".join(failures))


def normalize_and_extract(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    result = frame.sort_values(
        "timestamp_utc", kind="mergesort"
    ).reset_index(drop=True).copy()
    multiplier = 1.0
    multipliers: list[float] = []
    recognized: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    previous_close: float | None = None
    previous_timestamp: pd.Timestamp | None = None

    for _, row in result.iterrows():
        timestamp = pd.Timestamp(row["timestamp_utc"])
        current_open = float(row["open"])
        if (
            previous_close is not None
            and previous_close > 0
            and current_open > 0
        ):
            change = current_open / previous_close - 1.0
            if abs(change) >= JUMP_THRESHOLD:
                ratio = previous_close / current_open
                snapped = snap_split_factor(ratio)
                record = {
                    "timestamp_utc": timestamp,
                    "previous_timestamp_utc": previous_timestamp,
                    "raw_change": change,
                    "raw_ratio": ratio,
                }
                if snapped is None:
                    unresolved.append(record)
                else:
                    factor, error = snapped
                    multiplier *= float(factor)
                    recognized.append(
                        {
                            **record,
                            "recognized_factor": float(factor),
                            "relative_error": float(error),
                        }
                    )
        multipliers.append(multiplier)
        previous_close = float(row["close"])
        previous_timestamp = timestamp

    result["scale_multiplier"] = multipliers
    for column in ("open", "high", "low", "close"):
        result[f"normalized_{column}"] = (
            result[column] * result["scale_multiplier"]
        )

    local = result["timestamp_utc"].dt.tz_convert("America/New_York")
    result["trade_date"] = local.dt.strftime("%Y-%m-%d")
    result["minute_et"] = (local.dt.hour * 60 + local.dt.minute).astype(int)

    rth = result.loc[
        (result["minute_et"] >= RTH_START_ET)
        & (result["minute_et"] <= RTH_CLOSE_ET)
    ].copy()
    ah = result.loc[
        (result["minute_et"] >= AH_START_ET)
        & (result["minute_et"] <= AH_END_ET)
    ].copy()
    ah["session_minute"] = ah["minute_et"] - AH_START_ET

    rth_rows: list[dict[str, Any]] = []
    for trade_date, day in rth.groupby("trade_date", sort=True):
        indexed = day.set_index("minute_et", drop=False)
        if RTH_CLOSE_ET not in indexed.index or RTH_LAG_30_ET not in indexed.index:
            continue
        close_row = indexed.loc[RTH_CLOSE_ET]
        lag_row = indexed.loc[RTH_LAG_30_ET]
        if isinstance(close_row, pd.DataFrame):
            close_row = close_row.iloc[-1]
        if isinstance(lag_row, pd.DataFrame):
            lag_row = lag_row.iloc[-1]

        typical = (
            day["normalized_high"]
            + day["normalized_low"]
            + day["normalized_close"]
        ) / 3.0
        volume = day["volume"].clip(lower=0.0)
        denominator = float(volume.sum())
        rth_vwap = (
            float((typical * volume).sum() / denominator)
            if denominator > 0
            else float(day["normalized_close"].mean())
        )
        rth_rows.append(
            {
                "trade_date": trade_date,
                "rth_close_timestamp_utc": close_row["timestamp_utc"],
                "rth_close": float(close_row["normalized_close"]),
                "rth_vwap": rth_vwap,
                "rth_return_30m": (
                    float(close_row["normalized_close"])
                    / float(lag_row["normalized_close"])
                    - 1.0
                ),
            }
        )

    return (
        ah.reset_index(drop=True),
        pd.DataFrame(rth_rows),
        pd.DataFrame(recognized),
        pd.DataFrame(unresolved),
    )


def get_day(frame: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    return (
        frame.loc[frame["trade_date"] == trade_date]
        .sort_values("session_minute", kind="mergesort")
        .reset_index(drop=True)
    )


def session_grid(day: pd.DataFrame) -> pd.DataFrame:
    grid = pd.DataFrame(index=pd.RangeIndex(AH_LENGTH))
    grid.index.name = "session_minute"
    if day.empty:
        for column in (
            "timestamp_utc",
            "normalized_open",
            "normalized_high",
            "normalized_low",
            "normalized_close",
            "volume",
        ):
            grid[column] = np.nan
        grid["observed"] = False
        return grid

    indexed = (
        day.sort_values("session_minute", kind="mergesort")
        .drop_duplicates("session_minute", keep="last")
        .set_index("session_minute")
    )
    grid = grid.join(
        indexed[
            [
                "timestamp_utc",
                "normalized_open",
                "normalized_high",
                "normalized_low",
                "normalized_close",
                "volume",
            ]
        ],
        how="left",
    )
    grid["observed"] = grid["normalized_close"].notna()
    grid["positive_volume"] = grid["volume"].fillna(0.0) > 0

    typical = (
        grid["normalized_high"]
        + grid["normalized_low"]
        + grid["normalized_close"]
    ) / 3.0
    volume = grid["volume"].fillna(0.0).clip(lower=0.0)
    cumulative_volume = volume.cumsum()
    cumulative_value = (typical.fillna(0.0) * volume).cumsum()
    fallback = grid["normalized_close"].expanding().mean()
    grid["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(fallback)

    grid["ret_1m"] = grid["normalized_close"].pct_change(fill_method=None)
    grid["ret_15m"] = (
        grid["normalized_close"] / grid["normalized_close"].shift(15) - 1.0
    )
    grid["realized_vol_30m"] = (
        grid["ret_1m"]
        .rolling(VOL_WINDOW, min_periods=VOL_MIN_RETURNS)
        .std(ddof=1)
        * math.sqrt(15.0)
    )
    grid["normalized_momentum_15m"] = (
        grid["ret_15m"]
        / grid["realized_vol_30m"].replace(0.0, np.nan)
    )
    grid["recent_observed_count"] = (
        grid["observed"].rolling(RECENT_WINDOW, min_periods=1).sum()
    )
    grid["recent_positive_volume_count"] = (
        grid["positive_volume"].rolling(RECENT_WINDOW, min_periods=1).sum()
    )
    close_change = (
        grid["normalized_close"].diff().abs().gt(0)
        & grid["normalized_close"].notna()
        & grid["normalized_close"].shift(1).notna()
    )
    grid["recent_close_change_count"] = (
        close_change.rolling(RECENT_WINDOW, min_periods=1).sum()
    )
    grid["tradability_proxy_pass"] = (
        grid["observed"]
        & grid["normalized_close"].shift(15).notna()
        & (grid["recent_observed_count"] >= RECENT_MIN_OBSERVED)
        & (
            grid["recent_positive_volume_count"]
            >= RECENT_MIN_POSITIVE_VOLUME
        )
        & (grid["recent_close_change_count"] >= RECENT_MIN_CLOSE_CHANGES)
        & grid["normalized_momentum_15m"].notna()
    )
    return grid


def event_in_window(
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> bool:
    if events.empty:
        return False
    timestamps = pd.to_datetime(events["timestamp_utc"], utc=True)
    return bool(((timestamps >= start) & (timestamps <= end)).any())


def rth_row(frame: pd.DataFrame, trade_date: str) -> pd.Series | None:
    rows = frame.loc[frame["trade_date"] == trade_date]
    return None if rows.empty else rows.iloc[-1]


def build_candidate(
    trade_date: str,
    qqq: pd.DataFrame,
    soxx: pd.DataFrame,
    qqq_rth: pd.Series,
    soxx_rth: pd.Series,
    recognized: Mapping[str, pd.DataFrame],
    unresolved: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    signal_start_ts = pd.Timestamp(
        f"{trade_date} 16:30", tz="America/New_York"
    ).tz_convert("UTC")
    signal_end_ts = pd.Timestamp(
        f"{trade_date} 18:30", tz="America/New_York"
    ).tz_convert("UTC")
    for symbol in SIGNAL_SYMBOLS:
        if event_in_window(recognized[symbol], signal_start_ts, signal_end_ts):
            reasons.append(f"{symbol}_RECOGNIZED_SCALE_EVENT")
        if event_in_window(unresolved[symbol], signal_start_ts, signal_end_ts):
            reasons.append(f"{symbol}_UNRESOLVED_SCALE_EVENT")
    if reasons:
        return None, reasons

    signal_slice = pd.RangeIndex(SIGNAL_START, SIGNAL_END + 1)
    q = qqq.loc[signal_slice]
    s = soxx.loc[signal_slice]

    q_long = (
        q["tradability_proxy_pass"]
        & (float(qqq_rth["rth_return_30m"]) > 0)
        & (float(qqq_rth["rth_close"]) > float(qqq_rth["rth_vwap"]))
        & (q["normalized_close"] > float(qqq_rth["rth_close"]))
        & (q["normalized_close"] > q["vwap"])
        & (q["ret_15m"] > 0)
    ).fillna(False)
    s_long = (
        s["tradability_proxy_pass"]
        & (float(soxx_rth["rth_return_30m"]) > 0)
        & (float(soxx_rth["rth_close"]) > float(soxx_rth["rth_vwap"]))
        & (s["normalized_close"] > float(soxx_rth["rth_close"]))
        & (s["normalized_close"] > s["vwap"])
        & (s["ret_15m"] > 0)
    ).fillna(False)
    q_short = (
        q["tradability_proxy_pass"]
        & (float(qqq_rth["rth_return_30m"]) < 0)
        & (float(qqq_rth["rth_close"]) < float(qqq_rth["rth_vwap"]))
        & (q["normalized_close"] < float(qqq_rth["rth_close"]))
        & (q["normalized_close"] < q["vwap"])
        & (q["ret_15m"] < 0)
    ).fillna(False)
    s_short = (
        s["tradability_proxy_pass"]
        & (float(soxx_rth["rth_return_30m"]) < 0)
        & (float(soxx_rth["rth_close"]) < float(soxx_rth["rth_vwap"]))
        & (s["normalized_close"] < float(soxx_rth["rth_close"]))
        & (s["normalized_close"] < s["vwap"])
        & (s["ret_15m"] < 0)
    ).fillna(False)

    long_state = q_long & s_long
    short_state = q_short & s_short
    long_transition = long_state & ~long_state.shift(1, fill_value=False)
    short_transition = short_state & ~short_state.shift(1, fill_value=False)
    triggers = pd.DataFrame(
        {"LONG": long_transition, "SHORT": short_transition},
        index=signal_slice,
    )
    locations = np.argwhere(triggers.to_numpy(dtype=bool))
    if len(locations) == 0:
        return None, []

    row_location, direction_location = locations[0]
    signal_minute = int(triggers.index[int(row_location)])
    direction = str(triggers.columns[int(direction_location)])
    q_row = qqq.loc[signal_minute]
    s_row = soxx.loc[signal_minute]
    q_norm = float(q_row["normalized_momentum_15m"])
    s_norm = float(s_row["normalized_momentum_15m"])

    if direction == "LONG":
        execution_symbol = "SOXL" if s_norm > q_norm else "TQQQ"
    else:
        execution_symbol = "SOXS" if s_norm < q_norm else "SQQQ"

    return {
        "trade_date": trade_date,
        "calendar_year": int(trade_date[:4]),
        "study_period": study_period(int(trade_date[:4])),
        "direction": direction,
        "execution_symbol": execution_symbol,
        "signal_session_minute": signal_minute,
        "signal_timestamp_utc": q_row["timestamp_utc"],
        "qqq_rth_return_30m": float(qqq_rth["rth_return_30m"]),
        "soxx_rth_return_30m": float(soxx_rth["rth_return_30m"]),
        "qqq_ah_return_15m": float(q_row["ret_15m"]),
        "soxx_ah_return_15m": float(s_row["ret_15m"]),
        "qqq_normalized_momentum_15m": q_norm,
        "soxx_normalized_momentum_15m": s_norm,
        "relative_normalized_momentum": s_norm - q_norm,
    }, []


def exit_minute(variant: str, entry_minute: int) -> int:
    if variant == "FIXED_30M":
        return entry_minute + 30
    if variant == "FIXED_60M":
        return entry_minute + 60
    if variant == "SESSION_1955":
        return SESSION_EXIT_MINUTE
    raise StudyError(f"Unknown exit variant: {variant}")


def return_from_grid(
    grid: pd.DataFrame,
    entry_minute: int,
    target_minute: int,
) -> tuple[float, dict[str, Any]] | None:
    if (
        entry_minute >= AH_LENGTH
        or target_minute >= AH_LENGTH
        or target_minute <= entry_minute
    ):
        return None
    entry = grid.loc[entry_minute]
    exit_row = grid.loc[target_minute]
    if (
        pd.isna(entry["normalized_open"])
        or pd.isna(exit_row["normalized_close"])
        or pd.isna(entry["timestamp_utc"])
        or pd.isna(exit_row["timestamp_utc"])
    ):
        return None
    entry_price = float(entry["normalized_open"])
    exit_price = float(exit_row["normalized_close"])
    net_return = (
        exit_price * (1.0 - EXIT_COST)
        / (entry_price * (1.0 + ENTRY_COST))
        - 1.0
    )
    return net_return, {
        "entry_timestamp_utc": entry["timestamp_utc"],
        "exit_timestamp_utc": exit_row["timestamp_utc"],
        "entry_price_normalized": entry_price,
        "exit_price_normalized": exit_price,
        "holding_minutes": target_minute - entry_minute,
    }


def simulate_candidate(
    candidate: Mapping[str, Any],
    grids: Mapping[str, pd.DataFrame],
    recognized: Mapping[str, pd.DataFrame],
    unresolved: Mapping[str, pd.DataFrame],
) -> tuple[list[dict[str, Any]], list[str]]:
    entry_minute = int(candidate["signal_session_minute"]) + 1
    direction = str(candidate["direction"])
    execution_symbol = str(candidate["execution_symbol"])
    pair_symbols = (
        ("TQQQ", "SOXL") if direction == "LONG" else ("SQQQ", "SOXS")
    )
    rows: list[dict[str, Any]] = []
    reasons: list[str] = []

    for variant in EXIT_VARIANTS:
        target = exit_minute(variant, entry_minute)
        selected = return_from_grid(grids[execution_symbol], entry_minute, target)
        if selected is None:
            reasons.append(f"{variant}_EXACT_EXECUTION_BAR_MISSING")
            continue
        selected_return, details = selected
        start = pd.Timestamp(details["entry_timestamp_utc"])
        end = pd.Timestamp(details["exit_timestamp_utc"])
        variant_reasons: list[str] = []
        for symbol in ALL_SYMBOLS:
            if event_in_window(unresolved[symbol], start, end):
                variant_reasons.append(f"{variant}_{symbol}_UNRESOLVED_SCALE_EVENT")
            if event_in_window(recognized[symbol], start, end):
                variant_reasons.append(f"{variant}_{symbol}_RECOGNIZED_SCALE_EVENT")
        if variant_reasons:
            reasons.extend(variant_reasons)
            continue

        pair_returns: list[float] = []
        for symbol in pair_symbols:
            result = return_from_grid(grids[symbol], entry_minute, target)
            if result is not None:
                pair_returns.append(float(result[0]))
        pair_mean = (
            float(np.mean(pair_returns)) if len(pair_returns) == 2 else math.nan
        )
        rows.append(
            {
                **dict(candidate),
                "exit_variant": variant,
                "entry_session_minute": entry_minute,
                "exit_session_minute": target,
                **details,
                "instrument_net_return": selected_return,
                "position_weight": FIXED_ACCOUNT_WEIGHT,
                "account_trade_return": (
                    selected_return * FIXED_ACCOUNT_WEIGHT
                ),
                "direction_pair_baseline_count": len(pair_returns),
                "direction_pair_mean_return": pair_mean,
                "selection_excess_return": (
                    selected_return - pair_mean
                    if np.isfinite(pair_mean)
                    else math.nan
                ),
            }
        )
    return rows, sorted(set(reasons))


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def positive_profit_share(values: pd.Series, top_n: int) -> float:
    positive = (
        pd.to_numeric(values, errors="coerce")
        .dropna()
        .loc[lambda series: series > 0]
        .sort_values(ascending=False)
    )
    total = float(positive.sum())
    if total <= 0:
        return math.nan
    return float(positive.head(top_n).sum() / total)


def cumulative_return(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    return float(np.prod(1.0 + clean.to_numpy(dtype=float)) - 1.0)


def maximum_drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (1.0 + clean).cumprod()
    return float((nav / nav.cummax() - 1.0).min())


def daily_returns(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        ["exit_variant", "study_period", "trade_date"], sort=True
    ):
        variant, period, trade_date = keys
        rows.append(
            {
                "exit_variant": variant,
                "study_period": period,
                "trade_date": trade_date,
                "calendar_year": int(str(trade_date)[:4]),
                "daily_return": float(
                    np.prod(
                        1.0
                        + group["account_trade_return"].to_numpy(dtype=float)
                    )
                    - 1.0
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
                    "mean_instrument_return": float(instrument.mean()),
                    "median_instrument_return": float(instrument.median()),
                    "positive_rate": float((instrument > 0).mean()),
                    "profit_factor": profit_factor(account),
                    "cumulative_return": cumulative_return(
                        days["daily_return"]
                    ),
                    "max_drawdown": maximum_drawdown(days["daily_return"]),
                    "top1_positive_profit_share": positive_profit_share(
                        account, 1
                    ),
                    "top5_positive_profit_share": positive_profit_share(
                        account, 5
                    ),
                    "selection_excess_count": int(len(excess)),
                    "mean_selection_excess_return": (
                        float(excess.mean()) if len(excess) else math.nan
                    ),
                    "mean_signal_session_minute": float(
                        group["signal_session_minute"].mean()
                    ),
                    "mean_holding_minutes": float(
                        group["holding_minutes"].mean()
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["period_order"] = result["study_period"].map(PERIOD_ORDER)
        result = result.sort_values(
            ["exit_variant", "period_order"], kind="mergesort"
        ).drop(columns=["period_order"])
    return result


def summarize_years(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(
        ["exit_variant", "calendar_year"], sort=True
    ):
        variant, year = keys
        rows.append(
            {
                "exit_variant": variant,
                "calendar_year": int(year),
                "trade_count": int(len(group)),
                "account_return_sum": float(
                    group["account_trade_return"].sum()
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
        variant_rows = period.loc[period["exit_variant"] == variant]
        full_count = int(variant_rows["trade_count"].sum())
        validation = period_row(period, variant, "2023-2024_VALIDATION")
        confirmation = period_row(
            period, variant, "2025-2026_YTD_CONFIRMATION"
        )
        validation_count = (
            int(validation["trade_count"]) if validation is not None else 0
        )
        confirmation_count = (
            int(confirmation["trade_count"])
            if confirmation is not None
            else 0
        )
        sample_pass = bool(
            full_count >= MIN_FULL_HISTORY_TRADES
            and validation_count >= MIN_VALIDATION_TRADES
            and confirmation_count >= MIN_CONFIRMATION_TRADES
        )
        mean_pass = bool(
            sample_pass
            and float(validation["mean_instrument_return"]) > 0
            and float(confirmation["mean_instrument_return"]) > 0
        )
        median_pass = bool(
            sample_pass
            and float(validation["median_instrument_return"]) > 0
            and float(confirmation["median_instrument_return"]) > 0
        )
        pf_pass = bool(
            sample_pass
            and float(validation["profit_factor"]) > 1.0
            and float(confirmation["profit_factor"]) > 1.0
        )
        cumulative_pass = bool(
            sample_pass
            and float(validation["cumulative_return"]) > 0
            and float(confirmation["cumulative_return"]) > 0
        )
        selection_pass = bool(
            sample_pass
            and float(validation["mean_selection_excess_return"]) >= 0
            and float(confirmation["mean_selection_excess_return"]) >= 0
        )
        trade_concentration_pass = bool(
            sample_pass
            and float(validation["top1_positive_profit_share"])
            <= MAX_TOP1_SHARE
            and float(confirmation["top1_positive_profit_share"])
            <= MAX_TOP1_SHARE
            and float(validation["top5_positive_profit_share"])
            <= MAX_TOP5_SHARE
            and float(confirmation["top5_positive_profit_share"])
            <= MAX_TOP5_SHARE
        )
        yearly = year.loc[year["exit_variant"] == variant]
        positive = yearly.loc[
            yearly["account_return_sum"] > 0,
            "account_return_sum",
        ]
        year_share = (
            float(positive.max() / positive.sum())
            if len(positive) and float(positive.sum()) > 0
            else math.nan
        )
        year_pass = bool(
            np.isfinite(year_share)
            and year_share <= MAX_POSITIVE_YEAR_SHARE
        )
        candidate = bool(
            sample_pass
            and mean_pass
            and median_pass
            and pf_pass
            and cumulative_pass
            and selection_pass
            and trade_concentration_pass
            and year_pass
        )
        rows.append(
            {
                "exit_variant": variant,
                "full_history_trade_count": full_count,
                "validation_trade_count": validation_count,
                "confirmation_trade_count": confirmation_count,
                "sample_pass": sample_pass,
                "mean_positive_both_periods": mean_pass,
                "median_positive_both_periods": median_pass,
                "profit_factor_pass_both_periods": pf_pass,
                "cumulative_return_positive_both_periods": cumulative_pass,
                "selection_excess_nonnegative_both_periods": selection_pass,
                "trade_concentration_pass": trade_concentration_pass,
                "single_positive_year_profit_share": year_share,
                "year_concentration_pass": year_pass,
                "research_candidate_for_independent_replication": candidate,
            }
        )
    return pd.DataFrame(rows)


def choose_decision(
    qualification: pd.DataFrame,
) -> tuple[str, list[str]]:
    supported = qualification.loc[
        qualification["research_candidate_for_independent_replication"],
        "exit_variant",
    ].astype(str).tolist()
    if supported:
        return (
            "AFTER_HOURS_CLOSE_CONTINUATION_CANDIDATE_"
            "REQUIRES_INDEPENDENT_REPLICATION",
            supported,
        )
    if not bool(qualification["sample_pass"].any()):
        return (
            "AFTER_HOURS_CLOSE_CONTINUATION_"
            "INCONCLUSIVE_INSUFFICIENT_SAMPLE",
            [],
        )
    return (
        "NO_AFTER_HOURS_CLOSE_CONTINUATION_CANDIDATE_QUALIFIED",
        [],
    )


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=lambda value: (
                    value.item()
                    if isinstance(value, (np.integer, np.floating))
                    else str(value)
                ),
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_instrument_return",
        "median_instrument_return",
        "cumulative_return",
        "max_drawdown",
        "mean_selection_excess_return",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {
        "positive_rate",
        "top1_positive_profit_share",
        "top5_positive_profit_share",
        "single_positive_year_profit_share",
    }:
        return f"{float(value) * 100:.2f}"
    if column == "profit_factor":
        number = float(value)
        return "INF" if np.isinf(number) else f"{number:.3f}"
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
    overnight_summary_path: Path,
    forward_summary_path: Path,
    rth_summary_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    for path in (
        overnight_summary_path,
        forward_summary_path,
        rth_summary_path,
        canonical_root,
    ):
        if not path.exists():
            raise StudyError(f"Missing required input: {path}")

    overnight_summary = json.loads(
        overnight_summary_path.read_text(encoding="utf-8-sig")
    )
    forward_summary = json.loads(
        forward_summary_path.read_text(encoding="utf-8-sig")
    )
    rth_summary = json.loads(
        rth_summary_path.read_text(encoding="utf-8-sig")
    )
    validate_lineage(overnight_summary, forward_summary, rth_summary)

    canonical = index_canonical(canonical_root)
    ah_by_symbol: dict[str, pd.DataFrame] = {}
    rth_by_symbol: dict[str, pd.DataFrame] = {}
    recognized_by_symbol: dict[str, pd.DataFrame] = {}
    unresolved_by_symbol: dict[str, pd.DataFrame] = {}
    paths_read: set[str] = set()

    for symbol in ALL_SYMBOLS:
        raw, symbol_paths = load_symbol_full(symbol, canonical)
        paths_read.update(symbol_paths)
        ah, rth, recognized, unresolved = normalize_and_extract(raw)
        ah_by_symbol[symbol] = ah
        rth_by_symbol[symbol] = rth
        recognized_by_symbol[symbol] = recognized
        unresolved_by_symbol[symbol] = unresolved

    date_sets = {
        symbol: set(ah_by_symbol[symbol]["trade_date"].unique())
        for symbol in ALL_SYMBOLS
    }
    common_dates = sorted(set.intersection(*date_sets.values()))

    funnel = {
        "common_after_hours_date_count": len(common_dates),
        "both_rth_context_available_count": 0,
        "both_signal_assets_any_tradable_minute_count": 0,
        "signal_candidate_count": 0,
        "long_candidate_count": 0,
        "short_candidate_count": 0,
        "all_three_exit_variants_executable_count": 0,
    }
    session_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for trade_date in common_dates:
        qqq_rth = rth_row(rth_by_symbol["QQQ"], trade_date)
        soxx_rth = rth_row(rth_by_symbol["SOXX"], trade_date)
        if qqq_rth is None or soxx_rth is None:
            continue
        funnel["both_rth_context_available_count"] += 1
        grids = {
            symbol: session_grid(get_day(ah_by_symbol[symbol], trade_date))
            for symbol in ALL_SYMBOLS
        }
        signal_range = pd.RangeIndex(SIGNAL_START, SIGNAL_END + 1)
        any_tradable = bool(
            (
                grids["QQQ"].loc[
                    signal_range,
                    "tradability_proxy_pass",
                ]
                & grids["SOXX"].loc[
                    signal_range,
                    "tradability_proxy_pass",
                ]
            ).any()
        )
        if any_tradable:
            funnel["both_signal_assets_any_tradable_minute_count"] += 1

        candidate, reasons = build_candidate(
            trade_date,
            grids["QQQ"],
            grids["SOXX"],
            qqq_rth,
            soxx_rth,
            recognized_by_symbol,
            unresolved_by_symbol,
        )
        rows: list[dict[str, Any]] = []
        if candidate is not None and not reasons:
            funnel["signal_candidate_count"] += 1
            funnel[
                "long_candidate_count"
                if candidate["direction"] == "LONG"
                else "short_candidate_count"
            ] += 1
            rows, execution_reasons = simulate_candidate(
                candidate,
                grids,
                recognized_by_symbol,
                unresolved_by_symbol,
            )
            reasons.extend(execution_reasons)
            if len(rows) == len(EXIT_VARIANTS):
                funnel["all_three_exit_variants_executable_count"] += 1

        quarantined = bool(reasons)
        session_rows.append(
            {
                "trade_date": trade_date,
                "signal_generated": candidate is not None,
                "trade_record_count": len(rows) if not quarantined else 0,
                "session_quarantined": quarantined,
                "quarantine_reasons": "|".join(sorted(set(reasons))),
            }
        )
        if candidate is not None:
            candidate_rows.append(candidate)
        if not quarantined:
            trade_rows.extend(rows)

    sessions = pd.DataFrame(session_rows)
    candidates = pd.DataFrame(candidate_rows)
    trades = pd.DataFrame(trade_rows)

    if not candidates.empty:
        candidates = candidates.sort_values(
            "trade_date", kind="mergesort"
        ).reset_index(drop=True)
    if not trades.empty:
        trades = trades.sort_values(
            ["trade_date", "exit_variant"], kind="mergesort"
        ).reset_index(drop=True)

    if trades.empty:
        daily = pd.DataFrame()
        period = pd.DataFrame(
            columns=["exit_variant", "study_period", "trade_count"]
        )
        year = pd.DataFrame(
            columns=[
                "exit_variant",
                "calendar_year",
                "trade_count",
                "account_return_sum",
            ]
        )
    else:
        daily = daily_returns(trades)
        period = summarize_periods(trades, daily)
        year = summarize_years(trades)

    qualification = build_qualification(period, year)
    final_decision, supported = choose_decision(qualification)

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "sessions": result_dir / "v22_063a_sessions.csv",
        "candidates": result_dir / "v22_063a_candidates.csv",
        "trades": result_dir / "v22_063a_trades.csv",
        "daily": result_dir / "v22_063a_daily_returns.csv",
        "period": result_dir / "v22_063a_period_summary.csv",
        "year": result_dir / "v22_063a_year_summary.csv",
        "qualification": result_dir / "v22_063a_qualification.csv",
        "funnel": result_dir / "v22_063a_tradability_funnel.csv",
        "summary": result_dir / "v22_063a_summary.json",
    }
    sessions.to_csv(outputs["sessions"], index=False, encoding="utf-8-sig")
    candidates.to_csv(
        outputs["candidates"], index=False, encoding="utf-8-sig"
    )
    trades.to_csv(outputs["trades"], index=False, encoding="utf-8-sig")
    daily.to_csv(outputs["daily"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period"], index=False, encoding="utf-8-sig")
    year.to_csv(outputs["year"], index=False, encoding="utf-8-sig")
    qualification.to_csv(
        outputs["qualification"], index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([funnel]).to_csv(
        outputs["funnel"], index=False, encoding="utf-8-sig"
    )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": final_decision,
        "v22_063n_validated": True,
        "v22_062pr_validated": True,
        "v22_063r1_validated": True,
        "premarket_forward_chain_modified": False,
        "session_name": "AFTER_HOURS",
        "session_start_et": "16:00",
        "session_end_et": "19:59",
        "signal_start_et": "16:30",
        "signal_end_et": "18:30",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "exit_variants": list(EXIT_VARIANTS),
        "entry_cost_bps": ENTRY_COST * 10000,
        "exit_cost_bps": EXIT_COST * 10000,
        "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "corporate_action_safe_normalization_used": True,
        "signal_candidate_count": int(len(candidates)),
        "long_candidate_count": (
            int((candidates["direction"] == "LONG").sum())
            if not candidates.empty
            else 0
        ),
        "short_candidate_count": (
            int((candidates["direction"] == "SHORT").sum())
            if not candidates.empty
            else 0
        ),
        "trade_record_count": int(len(trades)),
        "trade_count_by_exit_variant": {
            variant: (
                int((trades["exit_variant"] == variant).sum())
                if not trades.empty
                else 0
            )
            for variant in EXIT_VARIANTS
        },
        "supported_exit_variants_for_replication": supported,
        "canonical_partition_count_indexed": int(len(canonical)),
        "canonical_partition_count_read": int(len(paths_read)),
        "parameter_sweep_executed": False,
        "session_window_sweep_executed": False,
        "rth_context_threshold_sweep_executed": False,
        "liquidity_threshold_sweep_executed": False,
        "exit_threshold_optimization_executed": False,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "history_download_executed": False,
        "open_d_called": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    atomic_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.063A after-hours close continuation")
    print("==============================================")
    print_table(
        "Validation / Confirmation performance",
        (
            period.loc[
                period["study_period"].isin(
                    [
                        "2023-2024_VALIDATION",
                        "2025-2026_YTD_CONFIRMATION",
                    ]
                )
            ]
            if not period.empty
            else period
        ),
    )
    print_table("Qualification", qualification)
    print_table("Tradability funnel", pd.DataFrame([funnel]))

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={final_decision}")
    print("V22_063N_VALIDATED=True")
    print("V22_062PR_VALIDATED=True")
    print("V22_063R1_VALIDATED=True")
    print("PREMARKET_FORWARD_CHAIN_MODIFIED=False")
    print(f"SIGNAL_CANDIDATE_COUNT={len(candidates)}")
    print(f"LONG_CANDIDATE_COUNT={summary['long_candidate_count']}")
    print(f"SHORT_CANDIDATE_COUNT={summary['short_candidate_count']}")
    for variant in EXIT_VARIANTS:
        print(
            f"TRADE_COUNT_{variant}="
            f"{summary['trade_count_by_exit_variant'][variant]}"
        )
    print(f"SUPPORTED_EXIT_VARIANTS_FOR_REPLICATION={supported}")
    print(f"CANONICAL_PARTITION_COUNT_READ={len(paths_read)}")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("SESSION_WINDOW_SWEEP_EXECUTED=False")
    print("RTH_CONTEXT_THRESHOLD_SWEEP_EXECUTED=False")
    print("LIQUIDITY_THRESHOLD_SWEEP_EXECUTED=False")
    print("EXIT_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("RSI_ENTRY_GATE_USED=False")
    print("MACD_ENTRY_GATE_USED=False")
    print("KDJ_ENTRY_GATE_USED=False")
    print("VIX_ENTRY_GATE_USED=False")
    print("VIX_RISK_SCALING_USED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("HISTORY_DOWNLOAD_EXECUTED=False")
    print("OPEN_D_CALLED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={result_dir}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-063n-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.063N_FAST3_OVERNIGHT_VWAP_MEAN_REVERSION_BASELINE_R1"
            r"\v22_063n_summary.json"
        ),
    )
    parser.add_argument(
        "--v22-062pr-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
            r"\v22_062pr_summary.json"
        ),
    )
    parser.add_argument(
        "--v22-063r1-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.063R1_FAST3_RTH_VWAP_MEAN_REVERSION_BASELINE_R1"
            r"\v22_063r1_summary.json"
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
            r"\V22.063A_FAST3_AFTER_HOURS_CLOSE_CONTINUATION_BASELINE_R1"
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
            overnight_summary_path=Path(args.v22_063n_summary),
            forward_summary_path=Path(args.v22_062pr_summary),
            rth_summary_path=Path(args.v22_063r1_summary),
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
