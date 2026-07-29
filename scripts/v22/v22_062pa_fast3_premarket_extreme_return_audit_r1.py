#!/usr/bin/env python
r"""
V22.062PA FAST3 premarket extreme-return and corporate-action audit R1.

Purpose
-------
V22.062P produced highly asymmetric confirmation results:
- very large positive mean;
- near-zero or negative median;
- extremely high profit factor;
- almost all positive profit concentrated in one year.

This stage does not develop another strategy. It audits whether those results
are caused by a small number of influential trades, price-scale discontinuity,
split/reverse-split behavior, timestamp mismatch, or other mechanical issues.

Inputs
------
- V22.062P summary and trades.
- Existing 582 Canonical partitions.

Scope
-----
- Reads V22.062P result files.
- Selects influential/extreme trades using frozen rules.
- Opens only the Canonical partitions required for those trades, plus the
  immediately preceding monthly partition when available.
- Reconstructs entry/exit returns.
- Audits adjacent one-minute price jumps and previous-close-to-entry changes.
- Produces concentration and anomaly-excluded sensitivity diagnostics.

It does not:
- rerun the premarket strategy;
- regenerate signals;
- scan thresholds;
- change RAW or Canonical data;
- download data;
- approve paper or broker trading.
"""

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


VERSION = (
    "V22.062PA_FAST3_PREMARKET_EXTREME_RETURN_"
    "AND_CORPORATE_ACTION_AUDIT_R1"
)

EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "PREMARKET_0925")
VALIDATION = "2023-2024_VALIDATION"
CONFIRMATION = "2025-2026_YTD_CONFIRMATION"

ENTRY_COST = 0.0005
EXIT_COST = 0.0005

EXTREME_ABS_RETURN_THRESHOLD = 0.25
ADJACENT_MINUTE_JUMP_THRESHOLD = 0.20
PREVIOUS_CLOSE_TO_ENTRY_THRESHOLD = 0.50
RETURN_RECONSTRUCTION_TOLERANCE = 1e-9
TOP1_POSITIVE_PROFIT_SHARE_LIMIT = 0.50
TOP5_POSITIVE_PROFIT_SHARE_LIMIT = 0.80
MAX_TOP_TRADES_PER_GROUP = 10
MAX_TARGETED_AUDIT_TRADES = 120


class AuditError(RuntimeError):
    """The V22.062PA audit cannot continue safely."""


def require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise AuditError(f"{name} missing required columns: {missing}")


def validate_v22_062p(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "NO_PREMARKET_BASELINE_CANDIDATE_QUALIFIED",
        "v22_062n_validated": True,
        "v22_056_validated": True,
        "overnight_architecture_used": False,
        "rth_orb_architecture_used": False,
        "pullback_reentry_architecture_used": False,
        "session_name": "PREMARKET",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "rsi_entry_gate_used": False,
        "macd_entry_gate_used": False,
        "kdj_entry_gate_used": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "parameter_sweep_executed": False,
        "session_window_sweep_executed": False,
        "initial_range_length_sweep_executed": False,
        "gap_threshold_sweep_executed": False,
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
    }
    failures = [
        f"{key}: expected {expected_value!r}, got {summary.get(key)!r}"
        for key, expected_value in expected.items()
        if summary.get(key) != expected_value
    ]
    if failures:
        raise AuditError(
            "V22.062P lineage validation failed: " + "; ".join(failures)
        )

    if int(summary.get("canonical_partition_count_indexed", -1)) != 582:
        raise AuditError("V22.062P did not index 582 Canonical partitions")
    if summary.get("supported_exit_variants_for_replication") != []:
        raise AuditError("V22.062P unexpectedly has a supported variant")


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
        raise AuditError(f"Cannot parse Canonical path: {path}")
    return symbol, year, month


def index_canonical(
    root: Path,
) -> dict[tuple[str, str, str], Path]:
    result: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key in result:
            raise AuditError(f"Duplicate Canonical partition: {key}")
        result[key] = path
    if len(result) < 582:
        raise AuditError(
            f"Canonical index unexpectedly small: {len(result)}"
        )
    return result


def find_column(frame: pd.DataFrame, aliases: Iterable[str]) -> str:
    mapping = {
        str(column).strip().lower(): str(column)
        for column in frame.columns
    }
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise AuditError(f"Missing column from aliases={tuple(aliases)}")


def normalize_trades(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "exit_variant",
        "study_period",
        "session_date",
        "calendar_year",
        "direction",
        "execution_symbol",
        "entry_timestamp_utc",
        "exit_timestamp_utc",
        "entry_price_raw",
        "exit_price_raw",
        "holding_minutes",
        "instrument_net_return",
        "account_trade_return",
    ]
    require_columns(frame, required, "V22.062P trades")

    result = frame.copy()
    numeric = [
        "calendar_year",
        "entry_price_raw",
        "exit_price_raw",
        "holding_minutes",
        "instrument_net_return",
        "account_trade_return",
    ]
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result["entry_timestamp_utc"] = pd.to_datetime(
        result["entry_timestamp_utc"],
        errors="raise",
        utc=True,
    )
    result["exit_timestamp_utc"] = pd.to_datetime(
        result["exit_timestamp_utc"],
        errors="raise",
        utc=True,
    )
    result["execution_symbol"] = (
        result["execution_symbol"]
        .astype(str)
        .str.upper()
        .str.replace("US.", "", regex=False)
    )
    result["trade_id"] = np.arange(len(result), dtype=int)

    result["reconstructed_net_return"] = (
        result["exit_price_raw"] * (1.0 - EXIT_COST)
        / (
            result["entry_price_raw"]
            * (1.0 + ENTRY_COST)
        )
        - 1.0
    )
    result["return_reconstruction_difference"] = (
        result["instrument_net_return"]
        - result["reconstructed_net_return"]
    )
    result["price_ratio"] = (
        result["exit_price_raw"] / result["entry_price_raw"]
    )
    result["preliminary_extreme_return"] = (
        result["instrument_net_return"].abs()
        >= EXTREME_ABS_RETURN_THRESHOLD
    )
    result["preliminary_nonpositive_price"] = (
        (result["entry_price_raw"] <= 0)
        | (result["exit_price_raw"] <= 0)
    )
    result["preliminary_reconstruction_mismatch"] = (
        result["return_reconstruction_difference"].abs()
        > RETURN_RECONSTRUCTION_TOLERANCE
    )
    result["preliminary_invalid_holding"] = (
        (result["holding_minutes"] <= 0)
        | (result["holding_minutes"] > 330)
    )
    return result


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def positive_profit_share(
    values: pd.Series,
    top_n: int,
) -> float:
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


def distribution_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = ["exit_variant", "study_period"]
    for keys, group in trades.groupby(columns, sort=True):
        variant, period = keys
        instrument = group["instrument_net_return"]
        account = group["account_trade_return"]
        ordered = group.sort_values(
            "instrument_net_return",
            ascending=False,
            kind="mergesort",
        )
        rows.append(
            {
                "exit_variant": variant,
                "study_period": period,
                "trade_count": int(len(group)),
                "mean_instrument_return": float(instrument.mean()),
                "median_instrument_return": float(instrument.median()),
                "positive_rate": float((instrument > 0).mean()),
                "profit_factor": profit_factor(account),
                "maximum_instrument_return": float(instrument.max()),
                "minimum_instrument_return": float(instrument.min()),
                "top1_positive_profit_share": positive_profit_share(
                    account, 1
                ),
                "top5_positive_profit_share": positive_profit_share(
                    account, 5
                ),
                "mean_excluding_top1_return": (
                    float(ordered.iloc[1:]["instrument_net_return"].mean())
                    if len(ordered) > 1
                    else math.nan
                ),
                "mean_excluding_top5_return": (
                    float(ordered.iloc[5:]["instrument_net_return"].mean())
                    if len(ordered) > 5
                    else math.nan
                ),
                "extreme_abs_25pct_trade_count": int(
                    group["preliminary_extreme_return"].sum()
                ),
                "reconstruction_mismatch_count": int(
                    group["preliminary_reconstruction_mismatch"].sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def year_concentration(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    yearly = (
        trades.groupby(
            ["exit_variant", "calendar_year"],
            sort=True,
        )["account_trade_return"]
        .sum()
        .reset_index(name="account_return_sum")
    )
    for variant, group in yearly.groupby("exit_variant", sort=True):
        positive = group.loc[group["account_return_sum"] > 0].copy()
        total_positive = float(positive["account_return_sum"].sum())
        for _, row in group.iterrows():
            contribution = (
                float(row["account_return_sum"]) / total_positive
                if total_positive > 0
                and float(row["account_return_sum"]) > 0
                else 0.0
            )
            rows.append(
                {
                    "exit_variant": variant,
                    "calendar_year": int(row["calendar_year"]),
                    "account_return_sum": float(
                        row["account_return_sum"]
                    ),
                    "positive_profit_contribution_share": contribution,
                }
            )
    return pd.DataFrame(rows)


def select_targeted_trades(trades: pd.DataFrame) -> pd.DataFrame:
    selected_ids: set[int] = set(
        trades.loc[
            trades[
                [
                    "preliminary_extreme_return",
                    "preliminary_nonpositive_price",
                    "preliminary_reconstruction_mismatch",
                    "preliminary_invalid_holding",
                ]
            ].any(axis=1),
            "trade_id",
        ].astype(int)
    )

    for _, group in trades.groupby(
        ["exit_variant", "study_period"],
        sort=True,
    ):
        selected_ids.update(
            group.nlargest(
                MAX_TOP_TRADES_PER_GROUP,
                "instrument_net_return",
            )["trade_id"].astype(int)
        )
        selected_ids.update(
            group.assign(
                abs_return=group["instrument_net_return"].abs()
            )
            .nlargest(MAX_TOP_TRADES_PER_GROUP, "abs_return")[
                "trade_id"
            ]
            .astype(int)
        )

    selected = trades.loc[
        trades["trade_id"].isin(selected_ids)
    ].copy()
    selected["audit_priority"] = (
        selected["preliminary_extreme_return"].astype(int) * 100
        + selected[
            "preliminary_reconstruction_mismatch"
        ].astype(int) * 100
        + selected["instrument_net_return"].abs() * 10
    )
    return (
        selected.sort_values(
            "audit_priority",
            ascending=False,
            kind="mergesort",
        )
        .head(MAX_TARGETED_AUDIT_TRADES)
        .drop(columns=["audit_priority"])
        .reset_index(drop=True)
    )


def previous_month(year: int, month: int) -> tuple[str, str]:
    timestamp = pd.Timestamp(year=year, month=month, day=1)
    previous = timestamp - pd.offsets.MonthBegin(1)
    return f"{previous.year:04d}", f"{previous.month:02d}"


def load_audit_partition_set(
    canonical: Mapping[tuple[str, str, str], Path],
    symbol: str,
    entry_timestamp: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    entry_et = entry_timestamp.tz_convert("America/New_York")
    year = f"{entry_et.year:04d}"
    month = f"{entry_et.month:02d}"
    keys = [(symbol, year, month)]
    prior_year, prior_month = previous_month(
        entry_et.year,
        entry_et.month,
    )
    keys.insert(0, (symbol, prior_year, prior_month))

    frames: list[pd.DataFrame] = []
    paths_used: list[str] = []
    for key in keys:
        path = canonical.get(key)
        if path is None:
            continue
        raw = pd.read_parquet(path)
        if raw.empty:
            continue

        timestamp_column = find_column(raw, ("timestamp_utc",))
        timestamp = pd.to_datetime(
            raw[timestamp_column],
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
            subset=["timestamp_utc", "open", "high", "low", "close"]
        )
        frames.append(frame)
        paths_used.append(str(path))

    if not frames:
        return pd.DataFrame(), paths_used

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp_utc", kind="mergesort")
        .drop_duplicates("timestamp_utc", keep="last")
        .reset_index(drop=True)
    )
    return combined, paths_used


def audit_one_trade(
    trade: pd.Series,
    canonical: Mapping[tuple[str, str, str], Path],
) -> tuple[dict[str, Any], pd.DataFrame]:
    symbol = str(trade["execution_symbol"])
    entry_timestamp = pd.Timestamp(trade["entry_timestamp_utc"])
    exit_timestamp = pd.Timestamp(trade["exit_timestamp_utc"])

    data, paths_used = load_audit_partition_set(
        canonical,
        symbol,
        entry_timestamp,
    )
    base: dict[str, Any] = {
        "trade_id": int(trade["trade_id"]),
        "exit_variant": str(trade["exit_variant"]),
        "study_period": str(trade["study_period"]),
        "session_date": str(trade["session_date"]),
        "direction": str(trade["direction"]),
        "execution_symbol": symbol,
        "entry_timestamp_utc": entry_timestamp,
        "exit_timestamp_utc": exit_timestamp,
        "reported_entry_price": float(trade["entry_price_raw"]),
        "reported_exit_price": float(trade["exit_price_raw"]),
        "reported_net_return": float(trade["instrument_net_return"]),
        "partition_paths_used": " | ".join(paths_used),
        "partition_count_read": len(paths_used),
    }

    if data.empty:
        base.update(
            {
                "entry_bar_found": False,
                "exit_bar_found": False,
                "canonical_reconstructed_return": math.nan,
                "canonical_return_difference": math.nan,
                "maximum_adjacent_close_jump": math.nan,
                "previous_rth_close_found": False,
                "previous_rth_close": math.nan,
                "previous_close_to_entry_return": math.nan,
                "mechanical_anomaly": True,
                "anomaly_reasons": "MISSING_CANONICAL_PARTITION",
            }
        )
        return base, pd.DataFrame()

    indexed = data.set_index("timestamp_utc", drop=False)
    entry_found = entry_timestamp in indexed.index
    exit_found = exit_timestamp in indexed.index
    reasons: list[str] = []

    if not entry_found:
        reasons.append("ENTRY_BAR_MISSING")
    if not exit_found:
        reasons.append("EXIT_BAR_MISSING")

    canonical_return = math.nan
    canonical_difference = math.nan
    canonical_entry = math.nan
    canonical_exit = math.nan
    entry_volume = math.nan
    exit_volume = math.nan

    if entry_found:
        entry_row = indexed.loc[entry_timestamp]
        if isinstance(entry_row, pd.DataFrame):
            entry_row = entry_row.iloc[-1]
        canonical_entry = float(entry_row["open"])
        entry_volume = float(entry_row["volume"])
        if abs(
            canonical_entry - float(trade["entry_price_raw"])
        ) > 1e-9:
            reasons.append("ENTRY_PRICE_MISMATCH")

    if exit_found:
        exit_row = indexed.loc[exit_timestamp]
        if isinstance(exit_row, pd.DataFrame):
            exit_row = exit_row.iloc[-1]
        canonical_exit = float(exit_row["close"])
        exit_volume = float(exit_row["volume"])
        if abs(
            canonical_exit - float(trade["exit_price_raw"])
        ) > 1e-9:
            reasons.append("EXIT_PRICE_MISMATCH")

    if entry_found and exit_found:
        canonical_return = (
            canonical_exit * (1.0 - EXIT_COST)
            / (canonical_entry * (1.0 + ENTRY_COST))
            - 1.0
        )
        canonical_difference = (
            float(trade["instrument_net_return"])
            - canonical_return
        )
        if abs(canonical_difference) > RETURN_RECONSTRUCTION_TOLERANCE:
            reasons.append("RETURN_RECONSTRUCTION_MISMATCH")

    entry_et = entry_timestamp.tz_convert("America/New_York")
    previous_day_cutoff = entry_et.normalize()
    local_timestamp = data["timestamp_utc"].dt.tz_convert(
        "America/New_York"
    )
    minute_et = local_timestamp.dt.hour * 60 + local_timestamp.dt.minute
    previous_close_rows = data.loc[
        (local_timestamp < previous_day_cutoff)
        & (minute_et == 15 * 60 + 59)
    ].copy()
    previous_close_found = not previous_close_rows.empty
    previous_close = (
        float(previous_close_rows.iloc[-1]["close"])
        if previous_close_found
        else math.nan
    )
    previous_close_to_entry = (
        canonical_entry / previous_close - 1.0
        if previous_close_found
        and np.isfinite(canonical_entry)
        and previous_close > 0
        else math.nan
    )

    window_start = (
        previous_close_rows.iloc[-1]["timestamp_utc"]
        if previous_close_found
        else entry_timestamp - pd.Timedelta(hours=18)
    )
    window_end = exit_timestamp + pd.Timedelta(minutes=15)
    window = data.loc[
        (data["timestamp_utc"] >= window_start)
        & (data["timestamp_utc"] <= window_end)
    ].copy()
    window["adjacent_close_return"] = (
        window["close"].pct_change(fill_method=None)
    )
    max_adjacent = (
        float(window["adjacent_close_return"].abs().max())
        if not window.empty
        else math.nan
    )
    if (
        np.isfinite(max_adjacent)
        and max_adjacent >= ADJACENT_MINUTE_JUMP_THRESHOLD
    ):
        reasons.append("ADJACENT_MINUTE_PRICE_JUMP")
    if (
        np.isfinite(previous_close_to_entry)
        and abs(previous_close_to_entry)
        >= PREVIOUS_CLOSE_TO_ENTRY_THRESHOLD
    ):
        reasons.append("PREVIOUS_CLOSE_TO_ENTRY_SCALE_JUMP")
    if (
        np.isfinite(canonical_entry)
        and canonical_entry <= 0
    ) or (
        np.isfinite(canonical_exit)
        and canonical_exit <= 0
    ):
        reasons.append("NONPOSITIVE_PRICE")

    mechanical_anomaly = bool(reasons)
    base.update(
        {
            "entry_bar_found": bool(entry_found),
            "exit_bar_found": bool(exit_found),
            "canonical_entry_price": canonical_entry,
            "canonical_exit_price": canonical_exit,
            "entry_bar_volume": entry_volume,
            "exit_bar_volume": exit_volume,
            "canonical_reconstructed_return": canonical_return,
            "canonical_return_difference": canonical_difference,
            "maximum_adjacent_close_jump": max_adjacent,
            "previous_rth_close_found": bool(previous_close_found),
            "previous_rth_close": previous_close,
            "previous_close_to_entry_return": previous_close_to_entry,
            "mechanical_anomaly": mechanical_anomaly,
            "anomaly_reasons": "|".join(sorted(set(reasons))),
        }
    )

    if not window.empty:
        window = window.assign(
            trade_id=int(trade["trade_id"]),
            execution_symbol=symbol,
            exit_variant=str(trade["exit_variant"]),
            session_date=str(trade["session_date"]),
        )
    return base, window


def sensitivity_summary(
    trades: pd.DataFrame,
    anomaly_trade_ids: set[int],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, frame in (
        ("ALL_TRADES", trades),
        (
            "EXCLUDE_MECHANICAL_ANOMALIES",
            trades.loc[~trades["trade_id"].isin(anomaly_trade_ids)],
        ),
    ):
        for keys, group in frame.groupby(
            ["exit_variant", "study_period"],
            sort=True,
        ):
            variant, period = keys
            rows.append(
                {
                    "sensitivity_set": label,
                    "exit_variant": variant,
                    "study_period": period,
                    "trade_count": int(len(group)),
                    "mean_instrument_return": float(
                        group["instrument_net_return"].mean()
                    ),
                    "median_instrument_return": float(
                        group["instrument_net_return"].median()
                    ),
                    "positive_rate": float(
                        (group["instrument_net_return"] > 0).mean()
                    ),
                    "profit_factor": profit_factor(
                        group["account_trade_return"]
                    ),
                    "top1_positive_profit_share": positive_profit_share(
                        group["account_trade_return"], 1
                    ),
                    "top5_positive_profit_share": positive_profit_share(
                        group["account_trade_return"], 5
                    ),
                }
            )
    return pd.DataFrame(rows)


def choose_decision(
    distribution: pd.DataFrame,
    concentration: pd.DataFrame,
    audit: pd.DataFrame,
) -> tuple[str, str]:
    anomaly_count = (
        int(audit["mechanical_anomaly"].sum())
        if not audit.empty
        else 0
    )
    if anomaly_count > 0:
        return (
            "PREMARKET_RESULT_BLOCKED_BY_EXTREME_RETURN_DATA_ANOMALY",
            "V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1",
        )

    recent = distribution.loc[
        distribution["study_period"].isin(
            [VALIDATION, CONFIRMATION]
        )
    ]
    concentrated = bool(
        (
            recent["top1_positive_profit_share"]
            > TOP1_POSITIVE_PROFIT_SHARE_LIMIT
        ).any()
        or (
            recent["top5_positive_profit_share"]
            > TOP5_POSITIVE_PROFIT_SHARE_LIMIT
        ).any()
    )
    year_concentrated = bool(
        (
            concentration["positive_profit_contribution_share"]
            > 0.60
        ).any()
    )

    if concentrated or year_concentrated:
        return (
            "PREMARKET_RESULT_NOT_REPLICATION_READY_OUTLIER_AND_YEAR_CONCENTRATED",
            "V22.062A_FAST3_AFTER_HOURS_CLOSE_CONTINUATION_BASELINE_R1",
        )
    return (
        "PREMARKET_RESULT_REQUIRES_INDEPENDENT_REPLICATION",
        "V22.062PR_FAST3_PREMARKET_INDEPENDENT_REPLICATION_R1",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
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


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {
        "mean_instrument_return",
        "median_instrument_return",
        "maximum_instrument_return",
        "minimum_instrument_return",
        "mean_excluding_top1_return",
        "mean_excluding_top5_return",
        "canonical_reconstructed_return",
        "canonical_return_difference",
        "maximum_adjacent_close_jump",
        "previous_close_to_entry_return",
        "account_return_sum",
    }:
        return f"{float(value) * 10000:.2f}"
    if column in {
        "positive_rate",
        "top1_positive_profit_share",
        "top5_positive_profit_share",
        "positive_profit_contribution_share",
    }:
        return f"{float(value) * 100:.2f}"
    if column == "profit_factor":
        numeric = float(value)
        return "INF" if np.isinf(numeric) else f"{numeric:.3f}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.6f}"
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


def run_audit(
    v22_062p_root: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    summary_path = v22_062p_root / "v22_062p_summary.json"
    trades_path = v22_062p_root / "v22_062p_trades.csv"

    for path in (summary_path, trades_path, canonical_root):
        if not path.exists():
            raise AuditError(f"Missing required input: {path}")

    source_summary = json.loads(
        summary_path.read_text(encoding="utf-8-sig")
    )
    validate_v22_062p(source_summary)

    trades = normalize_trades(pd.read_csv(trades_path))
    expected_count = int(source_summary["trade_record_count"])
    if len(trades) != expected_count:
        raise AuditError(
            f"Trade count mismatch: expected {expected_count}, got {len(trades)}"
        )

    distribution = distribution_summary(trades)
    concentration = year_concentration(trades)
    targeted = select_targeted_trades(trades)
    canonical = index_canonical(canonical_root)

    audit_rows: list[dict[str, Any]] = []
    window_frames: list[pd.DataFrame] = []
    partition_paths_read: set[str] = set()

    for _, trade in targeted.iterrows():
        audit_row, window = audit_one_trade(trade, canonical)
        audit_rows.append(audit_row)
        paths = str(audit_row["partition_paths_used"]).split(" | ")
        partition_paths_read.update(path for path in paths if path)
        if not window.empty:
            window_frames.append(window)

    audit = pd.DataFrame(audit_rows)
    windows = (
        pd.concat(window_frames, ignore_index=True)
        if window_frames
        else pd.DataFrame()
    )
    anomaly_ids = set(
        audit.loc[
            audit["mechanical_anomaly"],
            "trade_id",
        ].astype(int)
    ) if not audit.empty else set()

    sensitivity = sensitivity_summary(trades, anomaly_ids)
    final_decision, next_stage = choose_decision(
        distribution,
        concentration,
        audit,
    )

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "distribution": result_dir
        / "v22_062pa_distribution_summary.csv",
        "year_concentration": result_dir
        / "v22_062pa_year_concentration.csv",
        "targeted_trades": result_dir
        / "v22_062pa_targeted_trades.csv",
        "partition_audit": result_dir
        / "v22_062pa_targeted_partition_audit.csv",
        "windows": result_dir
        / "v22_062pa_suspect_trade_windows.csv",
        "sensitivity": result_dir
        / "v22_062pa_anomaly_excluded_sensitivity.csv",
        "summary": result_dir / "v22_062pa_summary.json",
    }

    frames = {
        "distribution": distribution,
        "year_concentration": concentration,
        "targeted_trades": targeted,
        "partition_audit": audit,
        "windows": windows,
        "sensitivity": sensitivity,
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
        "v22_062p_validated": True,
        "source_trade_count": int(len(trades)),
        "targeted_trade_count": int(len(targeted)),
        "mechanical_anomaly_trade_count": int(len(anomaly_ids)),
        "canonical_partition_count_indexed": int(len(canonical)),
        "canonical_partition_count_read": int(len(partition_paths_read)),
        "full_582_partition_reread": False,
        "strategy_backtest_executed": False,
        "signal_regeneration_executed": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "corporate_action_data_downloaded": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "next_stage": next_stage,
        "outputs": {
            name: str(path)
            for name, path in outputs.items()
        },
    }
    atomic_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.062PA premarket extreme-return audit")
    print("==============================================")
    print_table(
        "Validation / Confirmation concentration",
        distribution.loc[
            distribution["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ],
    )
    print_table(
        "Year concentration",
        concentration,
    )
    print_table(
        "Targeted Canonical audit",
        audit[
            [
                "trade_id",
                "exit_variant",
                "study_period",
                "session_date",
                "execution_symbol",
                "reported_net_return",
                "canonical_reconstructed_return",
                "maximum_adjacent_close_jump",
                "previous_close_to_entry_return",
                "mechanical_anomaly",
                "anomaly_reasons",
            ]
        ] if not audit.empty else audit,
    )
    print_table(
        "Anomaly-excluded sensitivity",
        sensitivity.loc[
            sensitivity["study_period"].isin(
                [VALIDATION, CONFIRMATION]
            )
        ],
    )

    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={final_decision}")
    print("V22_062P_VALIDATED=True")
    print(f"SOURCE_TRADE_COUNT={len(trades)}")
    print(f"TARGETED_TRADE_COUNT={len(targeted)}")
    print(
        f"MECHANICAL_ANOMALY_TRADE_COUNT={len(anomaly_ids)}"
    )
    print(
        f"CANONICAL_PARTITION_COUNT_READ="
        f"{len(partition_paths_read)}"
    )
    print("FULL_582_PARTITION_REREAD=False")
    print("STRATEGY_BACKTEST_EXECUTED=False")
    print("SIGNAL_REGENERATION_EXECUTED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"NEXT_STAGE={next_stage}")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={result_dir}")

    return summary


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-062p-root",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.062P_FAST3_PREMARKET_GAP_AND_RANGE_BASELINE_R1"
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
            r"\V22.062PA_FAST3_PREMARKET_EXTREME_RETURN_AUDIT_R1"
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
        run_audit(
            v22_062p_root=Path(args.v22_062p_root),
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
