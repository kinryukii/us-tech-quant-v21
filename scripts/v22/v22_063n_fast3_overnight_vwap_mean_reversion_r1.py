from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

import v22_063r1_fast3_rth_vwap_mean_reversion_r1 as base

VERSION = "V22.063N_FAST3_OVERNIGHT_VWAP_MEAN_REVERSION_BASELINE_R1"
SIGNAL_SYMBOLS = ("QQQ", "SOXX")
EXECUTION_SYMBOLS = ("TQQQ", "SOXL", "SQQQ", "SOXS")
ALL_SYMBOLS = SIGNAL_SYMBOLS + EXECUTION_SYMBOLS
EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "DUAL_VWAP_TOUCH_OR_60M")

EVENING_START_ET = 20 * 60
MORNING_END_ET = 3 * 60 + 59
SESSION_LENGTH = 480
SIGNAL_START = 180       # 23:00 ET
SIGNAL_END = 390         # 02:30 ET
DEVIATION_THRESHOLD = 2.00
VOL_WINDOW = 60
VOL_MIN_RETURNS = 30
RECENT_WINDOW = 60
RECENT_MIN_OBSERVED = 30
RECENT_MIN_POSITIVE_VOLUME = 20
RECENT_MIN_CLOSE_CHANGES = 10
ENTRY_COST = EXIT_COST = 0.0005
FIXED_ACCOUNT_WEIGHT = 0.20

PERIODS = base.PERIODS

class StudyError(RuntimeError):
    pass


def validate_v22_062n(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "NO_OVERNIGHT_BASELINE_CANDIDATE_QUALIFIED",
        "session_name": "OVERNIGHT",
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    bad = [f"{k}={summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if bad:
        raise StudyError("V22.062N lineage invalid: " + "; ".join(bad))
    if summary.get("supported_exit_variants_for_replication") != []:
        raise StudyError("V22.062N unexpectedly supports an exit")
    if int(summary.get("canonical_partition_count_indexed", -1)) != 582:
        raise StudyError("V22.062N partition inventory invalid")


def validate_v22_062pr(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "v22_062pb_validated": True,
        "research_cutoff_date": "2026-07-24",
        "forward_holdout_only": True,
        "rule_change_requires_reset": True,
        "sole_exit_variant": "PREMARKET_0925",
        "historical_pre_cutoff_outcomes_used_for_qualification": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "strategy_rule_change_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    bad = [f"{k}={summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if bad:
        raise StudyError("V22.062PR lineage invalid: " + "; ".join(bad))


def validate_v22_063r1(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED",
        "v22_061_validated": True,
        "v22_062pr_validated": True,
        "premarket_forward_chain_modified": False,
        "session_name": "RTH",
        "parameter_sweep_executed": False,
        "deviation_threshold_sweep_executed": False,
        "signal_window_sweep_executed": False,
        "exit_threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    bad = [f"{k}={summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if bad:
        raise StudyError("V22.063R1 lineage invalid: " + "; ".join(bad))
    if summary.get("supported_exit_variants_for_replication") != []:
        raise StudyError("V22.063R1 unexpectedly supports an exit")


def load_symbol_full(
    symbol: str,
    canonical: Mapping[tuple[str, str, str], Path],
) -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    used: list[str] = []
    for (current, _, _), path in sorted(canonical.items()):
        if current != symbol:
            continue
        raw = pd.read_parquet(path)
        used.append(str(path))
        if raw.empty:
            continue
        timestamp = pd.to_datetime(
            raw[base.find_column(raw, ("timestamp_utc",))],
            errors="raise",
            utc=True,
        )
        frames.append(
            pd.DataFrame(
                {
                    "timestamp_utc": timestamp,
                    "open": pd.to_numeric(raw[base.find_column(raw, ("open",))], errors="coerce"),
                    "high": pd.to_numeric(raw[base.find_column(raw, ("high",))], errors="coerce"),
                    "low": pd.to_numeric(raw[base.find_column(raw, ("low",))], errors="coerce"),
                    "close": pd.to_numeric(raw[base.find_column(raw, ("close",))], errors="coerce"),
                    "volume": pd.to_numeric(raw[base.find_column(raw, ("volume",))], errors="coerce").fillna(0.0),
                }
            ).dropna(subset=["timestamp_utc", "open", "high", "low", "close"])
        )
    if not frames:
        return pd.DataFrame(), used
    result = (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp_utc", kind="mergesort")
        .drop_duplicates("timestamp_utc", keep="last")
        .reset_index(drop=True)
    )
    if ((result.low > result.high) | (result.close < result.low) | (result.close > result.high)).any():
        raise StudyError(f"Invalid OHLC for {symbol}")
    return result, used


def normalize_and_extract_overnight(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), pd.DataFrame(), pd.DataFrame()

    ordered = frame.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True).copy()
    multiplier = 1.0
    multipliers: list[float] = []
    recognized: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    previous_close: float | None = None
    previous_timestamp: pd.Timestamp | None = None

    for _, row in ordered.iterrows():
        timestamp = pd.Timestamp(row.timestamp_utc)
        current_open = float(row.open)
        if previous_close is not None and previous_close > 0 and current_open > 0:
            elapsed = timestamp - previous_timestamp
            change = current_open / previous_close - 1.0
            if elapsed <= pd.Timedelta(days=3) and abs(change) >= base.JUMP_THRESHOLD:
                ratio = previous_close / current_open
                snapped = base.snap_split_factor(ratio)
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
                    multiplier *= factor
                    recognized.append(
                        {
                            **record,
                            "recognized_factor": factor,
                            "relative_error": error,
                        }
                    )
        multipliers.append(multiplier)
        previous_close = float(row.close)
        previous_timestamp = timestamp

    ordered["scale_multiplier"] = multipliers
    for column in ("open", "high", "low", "close"):
        ordered[f"normalized_{column}"] = ordered[column] * ordered.scale_multiplier

    timestamp_et = ordered.timestamp_utc.dt.tz_convert("America/New_York")
    minute_et = timestamp_et.dt.hour * 60 + timestamp_et.dt.minute
    mask = (minute_et >= EVENING_START_ET) | (minute_et <= MORNING_END_ET)
    overnight = ordered.loc[mask].copy()
    selected_et = timestamp_et.loc[mask]
    selected_minute = minute_et.loc[mask].astype(int)
    local_day = selected_et.dt.normalize()
    session_day = local_day.where(
        selected_minute <= MORNING_END_ET,
        local_day + pd.Timedelta(days=1),
    )
    overnight["session_date"] = session_day.dt.strftime("%Y-%m-%d")
    overnight["session_minute"] = np.where(
        selected_minute >= EVENING_START_ET,
        selected_minute - EVENING_START_ET,
        selected_minute + 240,
    ).astype(int)
    if overnight.duplicated(["session_date", "session_minute"]).any():
        raise StudyError("Duplicate overnight minute")
    return overnight.reset_index(drop=True), pd.DataFrame(recognized), pd.DataFrame(unresolved)


def get_session(frame: pd.DataFrame, session_date: str) -> pd.DataFrame:
    return (
        frame.loc[frame.session_date == session_date]
        .sort_values("session_minute", kind="mergesort")
        .reset_index(drop=True)
    )


def session_grid(day: pd.DataFrame) -> pd.DataFrame:
    grid = pd.DataFrame(index=pd.RangeIndex(SESSION_LENGTH))
    grid.index.name = "session_minute"
    columns = [
        "timestamp_utc",
        "normalized_open",
        "normalized_high",
        "normalized_low",
        "normalized_close",
        "volume",
    ]
    if day.empty:
        for column in columns:
            grid[column] = np.nan
        grid["observed"] = False
        grid["positive_volume"] = False
        return grid

    indexed = (
        day.sort_values("session_minute", kind="mergesort")
        .drop_duplicates("session_minute", keep="last")
        .set_index("session_minute")
    )
    grid = grid.join(indexed[columns], how="left")
    grid["observed"] = grid.normalized_close.notna()
    grid["positive_volume"] = grid.volume.fillna(0.0) > 0

    typical = (grid.normalized_high + grid.normalized_low + grid.normalized_close) / 3.0
    volume = grid.volume.fillna(0.0).clip(lower=0.0)
    cumulative_volume = volume.cumsum()
    cumulative_value = (typical.fillna(0.0) * volume).cumsum()
    grid["vwap"] = cumulative_value.divide(
        cumulative_volume.where(cumulative_volume > 0)
    ).fillna(grid.normalized_close.expanding().mean())

    grid["ret_1m"] = grid.normalized_close.pct_change(fill_method=None)
    grid["ret_5m"] = grid.normalized_close / grid.normalized_close.shift(5) - 1.0
    grid["realized_vol_60m"] = (
        grid.ret_1m.rolling(VOL_WINDOW, min_periods=VOL_MIN_RETURNS).std(ddof=1)
        * math.sqrt(VOL_WINDOW)
    )
    grid["vwap_deviation"] = grid.normalized_close / grid.vwap - 1.0
    grid["normalized_vwap_deviation"] = (
        grid.vwap_deviation / grid.realized_vol_60m.replace(0.0, np.nan)
    )
    grid["prior_high"] = grid.normalized_high.shift(1)
    grid["prior_low"] = grid.normalized_low.shift(1)

    grid["recent_observed_count"] = grid.observed.rolling(
        RECENT_WINDOW, min_periods=1
    ).sum()
    grid["recent_positive_volume_count"] = grid.positive_volume.rolling(
        RECENT_WINDOW, min_periods=1
    ).sum()
    close_change = (
        grid.normalized_close.diff().abs().gt(0)
        & grid.normalized_close.notna()
        & grid.normalized_close.shift(1).notna()
    )
    grid["recent_close_change_count"] = close_change.rolling(
        RECENT_WINDOW, min_periods=1
    ).sum()
    grid["tradability_proxy_pass"] = (
        grid.observed
        & grid.normalized_close.shift(5).notna()
        & (grid.recent_observed_count >= RECENT_MIN_OBSERVED)
        & (grid.recent_positive_volume_count >= RECENT_MIN_POSITIVE_VOLUME)
        & (grid.recent_close_change_count >= RECENT_MIN_CLOSE_CHANGES)
        & grid.realized_vol_60m.gt(0)
        & grid.normalized_vwap_deviation.notna()
    )
    return grid


def build_candidate(
    session_date: str,
    qqq: pd.DataFrame,
    soxx: pd.DataFrame,
    recognized: Mapping[str, pd.DataFrame],
    unresolved: Mapping[str, pd.DataFrame],
) -> tuple[dict[str, Any] | None, list[str]]:
    previous_date = (pd.Timestamp(session_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    start = pd.Timestamp(f"{previous_date} 23:00", tz="America/New_York").tz_convert("UTC")
    end = pd.Timestamp(f"{session_date} 02:30", tz="America/New_York").tz_convert("UTC")
    reasons: list[str] = []
    for symbol in SIGNAL_SYMBOLS:
        if base.event_in_window(recognized[symbol], start, end):
            reasons.append(f"{symbol}_RECOGNIZED_SCALE_EVENT_DURING_SIGNAL")
        if base.event_in_window(unresolved[symbol], start, end):
            reasons.append(f"{symbol}_UNRESOLVED_SCALE_EVENT_DURING_SIGNAL")
    if reasons:
        return None, reasons

    window = pd.RangeIndex(SIGNAL_START, SIGNAL_END + 1)
    q = qqq.loc[window]
    s = soxx.loc[window]
    q_long = (
        q.tradability_proxy_pass
        & (q.normalized_vwap_deviation <= -DEVIATION_THRESHOLD)
        & (q.ret_5m > 0)
        & (q.normalized_close > q.prior_high)
    ).fillna(False)
    s_long = (
        s.tradability_proxy_pass
        & (s.normalized_vwap_deviation <= -DEVIATION_THRESHOLD)
        & (s.ret_5m > 0)
        & (s.normalized_close > s.prior_high)
    ).fillna(False)
    q_short = (
        q.tradability_proxy_pass
        & (q.normalized_vwap_deviation >= DEVIATION_THRESHOLD)
        & (q.ret_5m < 0)
        & (q.normalized_close < q.prior_low)
    ).fillna(False)
    s_short = (
        s.tradability_proxy_pass
        & (s.normalized_vwap_deviation >= DEVIATION_THRESHOLD)
        & (s.ret_5m < 0)
        & (s.normalized_close < s.prior_low)
    ).fillna(False)

    long_state = q_long & s_long
    short_state = q_short & s_short
    triggers = pd.DataFrame(
        {
            "LONG": long_state & ~long_state.shift(1, fill_value=False),
            "SHORT": short_state & ~short_state.shift(1, fill_value=False),
        },
        index=window,
    )
    locations = np.argwhere(triggers.to_numpy(dtype=bool))
    if len(locations) == 0:
        return None, []
    row_location, direction_location = locations[0]
    minute = int(triggers.index[int(row_location)])
    direction = str(triggers.columns[int(direction_location)])
    q_row = qqq.loc[minute]
    s_row = soxx.loc[minute]
    q_dev = float(q_row.normalized_vwap_deviation)
    s_dev = float(s_row.normalized_vwap_deviation)
    if direction == "LONG":
        execution = "SOXL" if s_dev < q_dev else "TQQQ"
    else:
        execution = "SOXS" if s_dev > q_dev else "SQQQ"
    return {
        "trade_date": session_date,
        "session_date": session_date,
        "calendar_year": int(session_date[:4]),
        "study_period": base.study_period(int(session_date[:4])),
        "direction": direction,
        "execution_symbol": execution,
        "signal_session_minute": minute,
        "signal_timestamp_utc": q_row.timestamp_utc,
        "qqq_normalized_vwap_deviation": q_dev,
        "soxx_normalized_vwap_deviation": s_dev,
        "qqq_vwap_deviation": float(q_row.vwap_deviation),
        "soxx_vwap_deviation": float(s_row.vwap_deviation),
        "qqq_ret_5m": float(q_row.ret_5m),
        "soxx_ret_5m": float(s_row.ret_5m),
        "relative_overextension": s_dev - q_dev,
    }, []


def exit_minute(
    variant: str,
    entry: int,
    direction: str,
    qqq: pd.DataFrame,
    soxx: pd.DataFrame,
) -> int:
    if variant == "FIXED_30M":
        return entry + 30
    if variant == "FIXED_60M":
        return entry + 60
    if variant != "DUAL_VWAP_TOUCH_OR_60M":
        raise StudyError(f"Unknown exit variant: {variant}")
    for minute in range(entry, entry + 61):
        q = qqq.loc[minute]
        s = soxx.loc[minute]
        if pd.isna(q.normalized_close) or pd.isna(s.normalized_close):
            continue
        if direction == "LONG":
            touched = q.normalized_close >= q.vwap and s.normalized_close >= s.vwap
        else:
            touched = q.normalized_close <= q.vwap and s.normalized_close <= s.vwap
        if touched:
            return minute
    return entry + 60


def return_from_grid(
    grid: pd.DataFrame,
    entry: int,
    exit_: int,
) -> tuple[float, dict[str, Any]] | None:
    if entry >= SESSION_LENGTH or exit_ >= SESSION_LENGTH or exit_ <= entry:
        return None
    entry_row = grid.loc[entry]
    exit_row = grid.loc[exit_]
    if (
        pd.isna(entry_row.normalized_open)
        or pd.isna(exit_row.normalized_close)
        or pd.isna(entry_row.timestamp_utc)
        or pd.isna(exit_row.timestamp_utc)
    ):
        return None
    value = (
        float(exit_row.normalized_close) * (1.0 - EXIT_COST)
        / (float(entry_row.normalized_open) * (1.0 + ENTRY_COST))
        - 1.0
    )
    return value, {
        "entry_timestamp_utc": entry_row.timestamp_utc,
        "exit_timestamp_utc": exit_row.timestamp_utc,
        "entry_price_normalized": float(entry_row.normalized_open),
        "exit_price_normalized": float(exit_row.normalized_close),
        "holding_minutes": exit_ - entry,
    }


def simulate(
    candidate: Mapping[str, Any],
    grids: Mapping[str, pd.DataFrame],
    recognized: Mapping[str, pd.DataFrame],
    unresolved: Mapping[str, pd.DataFrame],
) -> tuple[list[dict[str, Any]], list[str]]:
    entry = int(candidate["signal_session_minute"]) + 1
    direction = str(candidate["direction"])
    selected = str(candidate["execution_symbol"])
    pair = ("TQQQ", "SOXL") if direction == "LONG" else ("SQQQ", "SOXS")
    rows: list[dict[str, Any]] = []
    reasons: list[str] = []

    for variant in EXIT_VARIANTS:
        exit_ = exit_minute(variant, entry, direction, grids["QQQ"], grids["SOXX"])
        if exit_ >= SESSION_LENGTH:
            reasons.append(f"{variant}_EXIT_OUTSIDE_SESSION")
            continue
        entry_ts = grids[selected].loc[entry, "timestamp_utc"]
        exit_ts = grids[selected].loc[exit_, "timestamp_utc"]
        if pd.isna(entry_ts) or pd.isna(exit_ts):
            reasons.append(f"{variant}_EXACT_EXECUTION_BAR_MISSING")
            continue
        blocked = False
        for symbol in ALL_SYMBOLS:
            if base.event_in_window(recognized[symbol], pd.Timestamp(entry_ts), pd.Timestamp(exit_ts)):
                reasons.append(f"{variant}_{symbol}_RECOGNIZED_SCALE_EVENT")
                blocked = True
            if base.event_in_window(unresolved[symbol], pd.Timestamp(entry_ts), pd.Timestamp(exit_ts)):
                reasons.append(f"{variant}_{symbol}_UNRESOLVED_SCALE_EVENT")
                blocked = True
        if blocked:
            continue
        chosen = return_from_grid(grids[selected], entry, exit_)
        if chosen is None:
            reasons.append(f"{variant}_RETURN_NOT_RECONSTRUCTABLE")
            continue
        value, details = chosen
        pair_values: list[float] = []
        for symbol in pair:
            result = return_from_grid(grids[symbol], entry, exit_)
            if result is not None:
                pair_values.append(float(result[0]))
        pair_mean = float(np.mean(pair_values)) if len(pair_values) == 2 else math.nan
        rows.append(
            {
                **dict(candidate),
                "exit_variant": variant,
                "entry_session_minute": entry,
                "exit_session_minute": exit_,
                **details,
                "instrument_net_return": value,
                "position_weight": FIXED_ACCOUNT_WEIGHT,
                "account_trade_return": value * FIXED_ACCOUNT_WEIGHT,
                "direction_pair_baseline_count": len(pair_values),
                "direction_pair_mean_return": pair_mean,
                "selection_excess_return": value - pair_mean if np.isfinite(pair_mean) else math.nan,
            }
        )
    return rows, sorted(set(reasons))


def choose_decision(qualification: pd.DataFrame) -> tuple[str, list[str]]:
    supported = qualification.loc[
        qualification.research_candidate_for_independent_replication,
        "exit_variant",
    ].astype(str).tolist()
    if supported:
        return (
            "OVERNIGHT_VWAP_MEAN_REVERSION_CANDIDATE_REQUIRES_INDEPENDENT_REPLICATION",
            supported,
        )
    if not bool(qualification.sample_pass.any()):
        return (
            "OVERNIGHT_VWAP_MEAN_REVERSION_INCONCLUSIVE_INSUFFICIENT_SAMPLE",
            [],
        )
    return "NO_OVERNIGHT_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED", []


def run_study(
    v22_062n_summary_path: Path,
    v22_062pr_summary_path: Path,
    v22_063r1_summary_path: Path,
    canonical_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    for path in (
        v22_062n_summary_path,
        v22_062pr_summary_path,
        v22_063r1_summary_path,
        canonical_root,
    ):
        if not path.exists():
            raise StudyError(f"Missing required input: {path}")

    summary_062n = json.loads(v22_062n_summary_path.read_text(encoding="utf-8-sig"))
    summary_062pr = json.loads(v22_062pr_summary_path.read_text(encoding="utf-8-sig"))
    summary_063r1 = json.loads(v22_063r1_summary_path.read_text(encoding="utf-8-sig"))
    validate_v22_062n(summary_062n)
    validate_v22_062pr(summary_062pr)
    validate_v22_063r1(summary_063r1)

    canonical = base.index_canonical(canonical_root)
    overnight: dict[str, pd.DataFrame] = {}
    recognized: dict[str, pd.DataFrame] = {}
    unresolved: dict[str, pd.DataFrame] = {}
    paths_read: set[str] = set()

    for symbol in ALL_SYMBOLS:
        raw, used = load_symbol_full(symbol, canonical)
        paths_read.update(used)
        overnight[symbol], recognized[symbol], unresolved[symbol] = normalize_and_extract_overnight(raw)

    session_sets = {
        symbol: set(overnight[symbol].session_date.unique())
        for symbol in ALL_SYMBOLS
    }
    common_sessions = sorted(set.intersection(*session_sets.values()))

    session_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []

    for session_date in common_sessions:
        grids = {
            symbol: session_grid(get_session(overnight[symbol], session_date))
            for symbol in ALL_SYMBOLS
        }
        candidate, reasons = build_candidate(
            session_date,
            grids["QQQ"],
            grids["SOXX"],
            recognized,
            unresolved,
        )
        rows: list[dict[str, Any]] = []
        if candidate is not None and not reasons:
            rows, execution_reasons = simulate(candidate, grids, recognized, unresolved)
            reasons.extend(execution_reasons)
        session_rows.append(
            {
                "session_date": session_date,
                "signal_generated": candidate is not None,
                "trade_record_count": len(rows),
                "session_quarantined": bool(reasons) and not rows,
                "partial_execution_issue": bool(reasons) and bool(rows),
                "quarantine_reasons": "|".join(sorted(set(reasons))),
            }
        )
        if candidate is not None:
            candidate_rows.append(candidate)
        trade_rows.extend(rows)

    sessions = pd.DataFrame(session_rows)
    candidates = pd.DataFrame(candidate_rows)
    trades = pd.DataFrame(trade_rows)
    if candidates.empty:
        raise StudyError("No overnight VWAP mean-reversion candidate generated")
    if trades.empty:
        raise StudyError("No executable overnight mean-reversion trades generated")

    candidates = candidates.sort_values("session_date", kind="mergesort").reset_index(drop=True)
    trades = trades.sort_values(["session_date", "exit_variant"], kind="mergesort").reset_index(drop=True)

    base.EXIT_VARIANTS = EXIT_VARIANTS
    daily = base.daily_returns(trades)
    period = base.summarize_periods(trades, daily)
    year = base.summarize_years(trades)
    qualification = base.qualification(period, year)
    decision, supported = choose_decision(qualification)

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "sessions": result_dir / "v22_063n_sessions.csv",
        "candidates": result_dir / "v22_063n_candidates.csv",
        "trades": result_dir / "v22_063n_trades.csv",
        "daily": result_dir / "v22_063n_daily_returns.csv",
        "period": result_dir / "v22_063n_period_summary.csv",
        "year": result_dir / "v22_063n_year_summary.csv",
        "qualification": result_dir / "v22_063n_qualification.csv",
        "recognized_events": result_dir / "v22_063n_recognized_scale_events.csv",
        "unresolved_events": result_dir / "v22_063n_unresolved_scale_events.csv",
        "summary": result_dir / "v22_063n_summary.json",
    }
    sessions.to_csv(outputs["sessions"], index=False, encoding="utf-8-sig")
    candidates.to_csv(outputs["candidates"], index=False, encoding="utf-8-sig")
    trades.to_csv(outputs["trades"], index=False, encoding="utf-8-sig")
    daily.to_csv(outputs["daily"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period"], index=False, encoding="utf-8-sig")
    year.to_csv(outputs["year"], index=False, encoding="utf-8-sig")
    qualification.to_csv(outputs["qualification"], index=False, encoding="utf-8-sig")

    recognized_frames = [df.assign(symbol=symbol) for symbol, df in recognized.items() if not df.empty]
    unresolved_frames = [df.assign(symbol=symbol) for symbol, df in unresolved.items() if not df.empty]
    recognized_all = pd.concat(recognized_frames, ignore_index=True) if recognized_frames else pd.DataFrame()
    unresolved_all = pd.concat(unresolved_frames, ignore_index=True) if unresolved_frames else pd.DataFrame()
    recognized_all.to_csv(outputs["recognized_events"], index=False, encoding="utf-8-sig")
    unresolved_all.to_csv(outputs["unresolved_events"], index=False, encoding="utf-8-sig")

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": decision,
        "v22_062n_validated": True,
        "v22_062pr_validated": True,
        "v22_063r1_validated": True,
        "premarket_forward_chain_modified": False,
        "previous_overnight_trend_architecture_used": False,
        "previous_rth_mean_reversion_architecture_used": False,
        "session_name": "OVERNIGHT",
        "session_start_et": "20:00",
        "session_end_et": "03:59",
        "signal_start_et": "23:00",
        "signal_end_et": "02:30",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "deviation_threshold": DEVIATION_THRESHOLD,
        "exit_variants": list(EXIT_VARIANTS),
        "entry_cost_bps": 5.0,
        "exit_cost_bps": 5.0,
        "fixed_account_weight": FIXED_ACCOUNT_WEIGHT,
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "corporate_action_safe_normalization_used": True,
        "signal_candidate_count": int(len(candidates)),
        "long_candidate_count": int((candidates.direction == "LONG").sum()),
        "short_candidate_count": int((candidates.direction == "SHORT").sum()),
        "trade_record_count": int(len(trades)),
        "trade_count_by_exit_variant": {
            variant: int((trades.exit_variant == variant).sum())
            for variant in EXIT_VARIANTS
        },
        "supported_exit_variants_for_replication": supported,
        "canonical_partition_count_indexed": int(len(canonical)),
        "canonical_partition_count_read": int(len(paths_read)),
        "parameter_sweep_executed": False,
        "deviation_threshold_sweep_executed": False,
        "session_window_sweep_executed": False,
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
    base.atomic_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.063N overnight VWAP mean-reversion baseline")
    print("==============================================")
    print("\n========== Validation / Confirmation performance ==========")
    print(period.loc[period.study_period.isin(PERIODS[1:])].to_string(index=False))
    print("\n========== Qualification ==========")
    print(qualification.to_string(index=False))
    print("\nFINAL_STATUS=PASS")
    print(f"FINAL_DECISION={decision}")
    print("V22_062N_VALIDATED=True")
    print("V22_062PR_VALIDATED=True")
    print("V22_063R1_VALIDATED=True")
    print("PREMARKET_FORWARD_CHAIN_MODIFIED=False")
    print(f"SIGNAL_CANDIDATE_COUNT={len(candidates)}")
    print(f"LONG_CANDIDATE_COUNT={int((candidates.direction == 'LONG').sum())}")
    print(f"SHORT_CANDIDATE_COUNT={int((candidates.direction == 'SHORT').sum())}")
    for variant in EXIT_VARIANTS:
        print(f"TRADE_COUNT_{variant}={int((trades.exit_variant == variant).sum())}")
    print(f"SUPPORTED_EXIT_VARIANTS_FOR_REPLICATION={supported}")
    print(f"CANONICAL_PARTITION_COUNT_READ={len(paths_read)}")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("DEVIATION_THRESHOLD_SWEEP_EXECUTED=False")
    print("SESSION_WINDOW_SWEEP_EXECUTED=False")
    print("LIQUIDITY_THRESHOLD_SWEEP_EXECUTED=False")
    print("EXIT_THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"RESULT_DIRECTORY={result_dir}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--v22-062n-summary",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.062N_FAST3_OVERNIGHT_SYNCHRONIZED_TREND_BASELINE_R1"
            r"\v22_062n_summary.json"
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
        default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical",
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.063N_FAST3_OVERNIGHT_VWAP_MEAN_REVERSION_BASELINE_R1"
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
            Path(args.v22_062n_summary),
            Path(args.v22_062pr_summary),
            Path(args.v22_063r1_summary),
            Path(args.canonical_root),
            Path(args.result_dir),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
