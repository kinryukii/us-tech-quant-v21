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

VERSION = "V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1"
VALIDATION = "2023-2024_VALIDATION"
CONFIRMATION = "2025-2026_YTD_CONFIRMATION"
PERIODS = ("2018-2022_DEVELOPMENT", VALIDATION, CONFIRMATION)
EXIT_VARIANTS = ("FIXED_30M", "FIXED_60M", "PREMARKET_0925")
ENTRY_COST = 0.0005
EXIT_COST = 0.0005
JUMP_THRESHOLD = 0.20
FACTOR_TOLERANCE = 0.03
EXTREME_RETURN_LIMIT = 0.25
RECON_TOL = 1e-9
ALLOWED_FACTORS = (2., 3., 4., 5., 6., 8., 10., 15., 20., 25., 30., 40., 50., 100.)
MIN_FULL = 80
MIN_VAL = 20
MIN_CONF = 20
MAX_YEAR_SHARE = 0.60
MAX_TOP1_SHARE = 0.50
MAX_TOP5_SHARE = 0.80


class StudyError(RuntimeError):
    pass


def require_columns(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise StudyError(f"{name} missing columns: {missing}")


def validate_p(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "NO_PREMARKET_BASELINE_CANDIDATE_QUALIFIED",
        "v22_062n_validated": True,
        "v22_056_validated": True,
        "session_name": "PREMARKET",
        "maximum_entries_per_session": 1,
        "entry_timing": "EXACT_NEXT_MINUTE_OPEN",
        "tradability_proxy_used": True,
        "bid_ask_spread_available": False,
        "order_book_depth_available": False,
        "vix_entry_gate_used": False,
        "vix_risk_scaling_used": False,
        "parameter_sweep_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
    }
    failures = [f"{k}: expected {v!r}, got {summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if failures:
        raise StudyError("V22.062P lineage failed: " + "; ".join(failures))
    if int(summary.get("canonical_partition_count_indexed", -1)) != 582:
        raise StudyError("V22.062P canonical count mismatch")
    if summary.get("supported_exit_variants_for_replication") != []:
        raise StudyError("V22.062P unexpectedly supports an exit")


def validate_pa(summary: Mapping[str, Any]) -> None:
    expected = {
        "final_status": "PASS",
        "final_decision": "PREMARKET_RESULT_BLOCKED_BY_EXTREME_RETURN_DATA_ANOMALY",
        "v22_062p_validated": True,
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
        "next_stage": "V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1",
    }
    failures = [f"{k}: expected {v!r}, got {summary.get(k)!r}" for k, v in expected.items() if summary.get(k) != v]
    if failures:
        raise StudyError("V22.062PA lineage failed: " + "; ".join(failures))
    if int(summary.get("mechanical_anomaly_trade_count", 0)) <= 0:
        raise StudyError("V22.062PA reports no anomaly trades")


def symbol_month_from_path(path: Path) -> tuple[str, str, str]:
    symbol = year = month = None
    for part in path.parts:
        m = re.fullmatch(r"symbol=(.+)", part, re.I)
        if m:
            symbol = m.group(1).upper().replace("US.", "")
        m = re.fullmatch(r"year=(\d{4})", part, re.I)
        if m:
            year = m.group(1)
        m = re.fullmatch(r"month=(\d{1,2})", part, re.I)
        if m:
            month = f"{int(m.group(1)):02d}"
    if not all((symbol, year, month)):
        raise StudyError(f"Cannot parse path: {path}")
    return symbol, year, month


def index_canonical(root: Path) -> dict[tuple[str, str, str], Path]:
    result: dict[tuple[str, str, str], Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        key = symbol_month_from_path(path)
        if key in result:
            raise StudyError(f"Duplicate partition: {key}")
        result[key] = path
    if len(result) < 582:
        raise StudyError(f"Canonical index too small: {len(result)}")
    return result


def find_column(frame: pd.DataFrame, aliases: Iterable[str]) -> str:
    mapping = {str(c).strip().lower(): str(c) for c in frame.columns}
    for alias in aliases:
        if alias.lower() in mapping:
            return mapping[alias.lower()]
    raise StudyError(f"Missing column aliases={tuple(aliases)}")


def previous_month(year: int, month: int) -> tuple[str, str]:
    prior = pd.Timestamp(year=year, month=month, day=1) - pd.offsets.MonthBegin(1)
    return f"{prior.year:04d}", f"{prior.month:02d}"


class PartitionCache:
    def __init__(self, index: Mapping[tuple[str, str, str], Path]) -> None:
        self.index = index
        self.cache: dict[tuple[str, str, str], pd.DataFrame] = {}
        self.paths_read: set[str] = set()

    def load(self, symbol: str, year: str, month: str) -> pd.DataFrame:
        key = (symbol, year, month)
        if key in self.cache:
            return self.cache[key]
        path = self.index.get(key)
        if path is None:
            self.cache[key] = pd.DataFrame()
            return self.cache[key]
        raw = pd.read_parquet(path)
        self.paths_read.add(str(path))
        if raw.empty:
            self.cache[key] = pd.DataFrame()
            return self.cache[key]
        ts = pd.to_datetime(raw[find_column(raw, ("timestamp_utc",))], utc=True, errors="raise")
        frame = pd.DataFrame({
            "timestamp_utc": ts,
            "open": pd.to_numeric(raw[find_column(raw, ("open",))], errors="coerce"),
            "high": pd.to_numeric(raw[find_column(raw, ("high",))], errors="coerce"),
            "low": pd.to_numeric(raw[find_column(raw, ("low",))], errors="coerce"),
            "close": pd.to_numeric(raw[find_column(raw, ("close",))], errors="coerce"),
            "volume": pd.to_numeric(raw[find_column(raw, ("volume",))], errors="coerce").fillna(0.0),
        }).dropna(subset=["timestamp_utc", "open", "high", "low", "close"])
        frame = frame.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc", keep="last").reset_index(drop=True)
        self.cache[key] = frame
        return frame

    def window(self, symbol: str, timestamp: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        et = timestamp.tz_convert("America/New_York")
        year, month = f"{et.year:04d}", f"{et.month:02d}"
        py, pm = previous_month(et.year, et.month)
        frames = [self.load(symbol, py, pm), self.load(symbol, year, month)]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc", keep="last")
        return combined.loc[(combined["timestamp_utc"] >= start) & (combined["timestamp_utc"] <= end)].reset_index(drop=True)


def factor_candidates() -> np.ndarray:
    values = set(ALLOWED_FACTORS)
    values.update(1.0 / x for x in ALLOWED_FACTORS)
    return np.array(sorted(values), dtype=float)


def snap_factor(raw_ratio: float) -> tuple[float, float] | None:
    if not np.isfinite(raw_ratio) or raw_ratio <= 0:
        return None
    factors = factor_candidates()
    errors = np.abs(factors / raw_ratio - 1.0)
    idx = int(np.argmin(errors))
    if float(errors[idx]) <= FACTOR_TOLERANCE:
        return float(factors[idx]), float(errors[idx])
    return None


def normalize_scale(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    if frame.empty:
        return frame.copy(), [], []
    result = frame.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True).copy()
    multiplier = 1.0
    multipliers: list[float] = []
    events: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    prev_close: float | None = None
    prev_ts: pd.Timestamp | None = None
    for _, row in result.iterrows():
        current_open = float(row["open"])
        ts = pd.Timestamp(row["timestamp_utc"])
        if prev_close is not None and prev_close > 0 and current_open > 0:
            raw_change = current_open / prev_close - 1.0
            if abs(raw_change) >= JUMP_THRESHOLD:
                raw_ratio = prev_close / current_open
                snapped = snap_factor(raw_ratio)
                if snapped is None:
                    unresolved.append({"timestamp_utc": ts, "previous_timestamp_utc": prev_ts, "raw_change": raw_change, "raw_ratio": raw_ratio})
                else:
                    factor, error = snapped
                    multiplier *= factor
                    events.append({"timestamp_utc": ts, "factor": factor, "relative_error": error, "raw_ratio": raw_ratio})
        multipliers.append(multiplier)
        prev_close = float(row["close"])
        prev_ts = ts
    result["scale_multiplier"] = multipliers
    for c in ("open", "high", "low", "close"):
        result[f"normalized_{c}"] = result[c] * result["scale_multiplier"]
    return result, events, unresolved


def normalize_trades(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "exit_variant", "study_period", "session_date", "calendar_year", "direction", "execution_symbol",
        "signal_timestamp_utc", "entry_timestamp_utc", "exit_timestamp_utc", "entry_price_raw", "exit_price_raw",
        "holding_minutes", "instrument_net_return", "position_weight", "account_trade_return",
        "qqq_prior_rth_close", "soxx_prior_rth_close", "qqq_close", "soxx_close",
    ]
    require_columns(frame, required, "V22.062P trades")
    result = frame.copy()
    result["trade_id"] = np.arange(len(result), dtype=int)
    for c in ("calendar_year", "entry_price_raw", "exit_price_raw", "holding_minutes", "instrument_net_return", "position_weight", "account_trade_return", "qqq_prior_rth_close", "soxx_prior_rth_close", "qqq_close", "soxx_close"):
        result[c] = pd.to_numeric(result[c], errors="coerce")
    for c in ("signal_timestamp_utc", "entry_timestamp_utc", "exit_timestamp_utc"):
        result[c] = pd.to_datetime(result[c], utc=True, errors="raise")
    result["execution_symbol"] = result["execution_symbol"].astype(str).str.upper().str.replace("US.", "", regex=False)
    result["source_reconstructed_return"] = result["exit_price_raw"] * (1.0 - EXIT_COST) / (result["entry_price_raw"] * (1.0 + ENTRY_COST)) - 1.0
    result["source_reconstruction_difference"] = result["instrument_net_return"] - result["source_reconstructed_return"]
    return result


def flagged_ids(pa_audit: pd.DataFrame, trades: pd.DataFrame) -> set[int]:
    require_columns(pa_audit, ["trade_id", "mechanical_anomaly"], "PA audit")
    anomaly = pa_audit["mechanical_anomaly"]
    if anomaly.dtype != bool:
        anomaly = anomaly.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    result = set(pd.to_numeric(pa_audit.loc[anomaly, "trade_id"], errors="coerce").dropna().astype(int))
    result.update(trades.loc[trades["instrument_net_return"].abs() >= EXTREME_RETURN_LIMIT, "trade_id"].astype(int))
    return result


def exact_row(frame: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    rows = frame.loc[frame["timestamp_utc"] == timestamp]
    return None if rows.empty else rows.iloc[-1]


def premarket_start(session_date: str) -> pd.Timestamp:
    return pd.Timestamp(f"{session_date} 04:00", tz="America/New_York").tz_convert("UTC")


def audit_signal_symbol(trade: pd.Series, symbol: str, cache: PartitionCache) -> dict[str, Any]:
    signal_ts = pd.Timestamp(trade["signal_timestamp_utc"])
    start = premarket_start(str(trade["session_date"])) - pd.Timedelta(hours=13)
    raw = cache.window(symbol, signal_ts, start, signal_ts)
    norm, events, unresolved = normalize_scale(raw)
    reasons: list[str] = []
    if unresolved:
        reasons.append(f"{symbol}_UNRESOLVED_SCALE_JUMP")
    pm_start = premarket_start(str(trade["session_date"]))
    intra = [e for e in events if pm_start < e["timestamp_utc"] <= signal_ts]
    if intra:
        reasons.append(f"{symbol}_INTRAPREMARKET_SCALE_EVENT")
    row = exact_row(norm, signal_ts)
    if row is None:
        reasons.append(f"{symbol}_SIGNAL_BAR_MISSING")
        normalized_close = math.nan
        multiplier = math.nan
    else:
        normalized_close = float(row["normalized_close"])
        multiplier = float(row["scale_multiplier"])
    prior = float(trade["qqq_prior_rth_close" if symbol == "QQQ" else "soxx_prior_rth_close"])
    valid = bool(np.isfinite(normalized_close) and (normalized_close > prior if str(trade["direction"]) == "LONG" else normalized_close < prior))
    if not valid:
        reasons.append(f"{symbol}_NORMALIZED_GAP_DIRECTION_INVALID")
    return {
        f"{symbol.lower()}_recognized_event_count": len(events),
        f"{symbol.lower()}_recognized_factors": "|".join(str(e["factor"]) for e in events),
        f"{symbol.lower()}_unresolved_jump_count": len(unresolved),
        f"{symbol.lower()}_intrapremarket_event_count": len(intra),
        f"{symbol.lower()}_signal_multiplier": multiplier,
        f"{symbol.lower()}_normalized_gap_direction_valid": valid,
        "reasons": reasons,
    }


def audit_execution(trade: pd.Series, cache: PartitionCache) -> dict[str, Any]:
    symbol = str(trade["execution_symbol"])
    entry_ts = pd.Timestamp(trade["entry_timestamp_utc"])
    exit_ts = pd.Timestamp(trade["exit_timestamp_utc"])
    raw = cache.window(symbol, entry_ts, entry_ts - pd.Timedelta(hours=18), exit_ts + pd.Timedelta(minutes=15))
    norm, events, unresolved = normalize_scale(raw)
    reasons: list[str] = []
    entry = exact_row(norm, entry_ts)
    exit_row = exact_row(norm, exit_ts)
    if entry is None:
        reasons.append("EXECUTION_ENTRY_BAR_MISSING")
    if exit_row is None:
        reasons.append("EXECUTION_EXIT_BAR_MISSING")
    if unresolved:
        reasons.append("EXECUTION_UNRESOLVED_SCALE_JUMP")
    corrected = math.nan
    norm_entry = math.nan
    norm_exit = math.nan
    if entry is not None and exit_row is not None:
        norm_entry = float(entry["normalized_open"])
        norm_exit = float(exit_row["normalized_close"])
        corrected = norm_exit * (1.0 - EXIT_COST) / (norm_entry * (1.0 + ENTRY_COST)) - 1.0
    holding_events = [e for e in events if entry_ts < e["timestamp_utc"] <= exit_ts]
    if np.isfinite(corrected) and abs(corrected) >= EXTREME_RETURN_LIMIT:
        reasons.append("CORRECTED_RETURN_STILL_EXTREME")
    if not holding_events and abs(float(trade["source_reconstruction_difference"])) > RECON_TOL:
        reasons.append("SOURCE_RETURN_RECONSTRUCTION_MISMATCH")
    return {
        "execution_recognized_event_count": len(events),
        "execution_event_count_during_holding": len(holding_events),
        "execution_recognized_factors": "|".join(str(e["factor"]) for e in events),
        "execution_unresolved_jump_count": len(unresolved),
        "normalized_entry_price": norm_entry,
        "normalized_exit_price": norm_exit,
        "corrected_instrument_return": corrected,
        "reasons": reasons,
    }


def repair_trade(trade: pd.Series, cache: PartitionCache) -> dict[str, Any]:
    qqq = audit_signal_symbol(trade, "QQQ", cache)
    soxx = audit_signal_symbol(trade, "SOXX", cache)
    execution = audit_execution(trade, cache)
    reasons = list(qqq.pop("reasons")) + list(soxx.pop("reasons")) + list(execution.pop("reasons"))
    corrected = float(execution["corrected_instrument_return"])
    account = corrected * float(trade["position_weight"]) if np.isfinite(corrected) else math.nan
    return {
        "trade_id": int(trade["trade_id"]),
        "exit_variant": str(trade["exit_variant"]),
        "study_period": str(trade["study_period"]),
        "session_date": str(trade["session_date"]),
        "calendar_year": int(trade["calendar_year"]),
        "direction": str(trade["direction"]),
        "execution_symbol": str(trade["execution_symbol"]),
        "source_instrument_return": float(trade["instrument_net_return"]),
        **qqq,
        **soxx,
        **execution,
        "corrected_account_return": account,
        "quarantined": bool(reasons),
        "quarantine_reasons": "|".join(sorted(set(reasons))),
    }


def build_corrected(source: pd.DataFrame, repairs: pd.DataFrame, target_ids: set[int]) -> pd.DataFrame:
    result = source.copy()
    result["normalization_targeted"] = result["trade_id"].isin(target_ids)
    result["quarantined"] = False
    result["quarantine_reasons"] = ""
    result["corrected_instrument_return"] = result["instrument_net_return"]
    result["corrected_account_return"] = result["account_trade_return"]
    indexed = repairs.set_index("trade_id") if not repairs.empty else pd.DataFrame()
    for idx, row in result.loc[result["normalization_targeted"]].iterrows():
        trade_id = int(row["trade_id"])
        if repairs.empty or trade_id not in indexed.index:
            result.at[idx, "quarantined"] = True
            result.at[idx, "quarantine_reasons"] = "TARGETED_TRADE_NOT_REPAIRED"
            continue
        repair = indexed.loc[trade_id]
        result.at[idx, "quarantined"] = bool(repair["quarantined"])
        result.at[idx, "quarantine_reasons"] = str(repair["quarantine_reasons"])
        result.at[idx, "corrected_instrument_return"] = repair["corrected_instrument_return"]
        result.at[idx, "corrected_account_return"] = repair["corrected_account_return"]
    result["included"] = (~result["quarantined"] & result["corrected_instrument_return"].notna() & result["corrected_account_return"].notna())
    return result


def profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean.loc[clean > 0].sum())
    losses = float(-clean.loc[clean < 0].sum())
    if losses == 0:
        return math.inf if gains > 0 else math.nan
    return gains / losses


def positive_share(values: pd.Series, n: int) -> float:
    positive = pd.to_numeric(values, errors="coerce").dropna().loc[lambda s: s > 0].sort_values(ascending=False)
    total = float(positive.sum())
    return float(positive.head(n).sum() / total) if total > 0 else math.nan


def cumulative_return(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    return float(np.prod(1.0 + clean.to_numpy(dtype=float)) - 1.0) if len(clean) else math.nan


def maximum_drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").fillna(0.0)
    if clean.empty:
        return math.nan
    nav = (1.0 + clean).cumprod()
    return float((nav / nav.cummax() - 1.0).min())


def daily_returns(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    included = trades.loc[trades["included"]]
    for keys, group in included.groupby(["exit_variant", "study_period", "session_date"], sort=True):
        variant, period, session_date = keys
        rows.append({
            "exit_variant": variant,
            "study_period": period,
            "session_date": session_date,
            "calendar_year": int(str(session_date)[:4]),
            "daily_return": float(np.prod(1.0 + group["corrected_account_return"].to_numpy(dtype=float)) - 1.0),
        })
    return pd.DataFrame(rows)


def period_summary(trades: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    included = trades.loc[trades["included"]]
    for variant in EXIT_VARIANTS:
        for period in PERIODS:
            group = included.loc[(included["exit_variant"] == variant) & (included["study_period"] == period)]
            days = daily.loc[(daily["exit_variant"] == variant) & (daily["study_period"] == period)]
            if group.empty:
                continue
            inst = group["corrected_instrument_return"]
            acct = group["corrected_account_return"]
            rows.append({
                "exit_variant": variant,
                "study_period": period,
                "trade_count": int(len(group)),
                "targeted_trade_count": int(group["normalization_targeted"].sum()),
                "mean_instrument_return": float(inst.mean()),
                "median_instrument_return": float(inst.median()),
                "positive_rate": float((inst > 0).mean()),
                "profit_factor": profit_factor(acct),
                "cumulative_return": cumulative_return(days["daily_return"]),
                "max_drawdown": maximum_drawdown(days["daily_return"]),
                "top1_positive_profit_share": positive_share(acct, 1),
                "top5_positive_profit_share": positive_share(acct, 5),
            })
    return pd.DataFrame(rows)


def year_summary(trades: pd.DataFrame) -> pd.DataFrame:
    included = trades.loc[trades["included"]]
    return included.groupby(["exit_variant", "calendar_year"], sort=True)["corrected_account_return"].agg(trade_count="size", account_return_sum="sum").reset_index()


def get_period_row(frame: pd.DataFrame, variant: str, period: str) -> pd.Series | None:
    rows = frame.loc[(frame["exit_variant"] == variant) & (frame["study_period"] == period)]
    return None if rows.empty else rows.iloc[0]


def qualification(period: pd.DataFrame, year: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant in EXIT_VARIANTS:
        vr = period.loc[period["exit_variant"] == variant]
        full = int(vr["trade_count"].sum())
        val = get_period_row(period, variant, VALIDATION)
        conf = get_period_row(period, variant, CONFIRMATION)
        val_n = int(val["trade_count"]) if val is not None else 0
        conf_n = int(conf["trade_count"]) if conf is not None else 0
        sample = full >= MIN_FULL and val_n >= MIN_VAL and conf_n >= MIN_CONF
        mean_pass = bool(sample and float(val["mean_instrument_return"]) > 0 and float(conf["mean_instrument_return"]) > 0)
        median_pass = bool(sample and float(val["median_instrument_return"]) > 0 and float(conf["median_instrument_return"]) > 0)
        pf_pass = bool(sample and float(val["profit_factor"]) > 1 and float(conf["profit_factor"]) > 1)
        cum_pass = bool(sample and float(val["cumulative_return"]) > 0 and float(conf["cumulative_return"]) > 0)
        concentration = bool(sample and float(val["top1_positive_profit_share"]) <= MAX_TOP1_SHARE and float(conf["top1_positive_profit_share"]) <= MAX_TOP1_SHARE and float(val["top5_positive_profit_share"]) <= MAX_TOP5_SHARE and float(conf["top5_positive_profit_share"]) <= MAX_TOP5_SHARE)
        yearly = year.loc[year["exit_variant"] == variant]
        positive = yearly.loc[yearly["account_return_sum"] > 0, "account_return_sum"]
        share = float(positive.max() / positive.sum()) if len(positive) and float(positive.sum()) > 0 else math.nan
        year_pass = bool(np.isfinite(share) and share <= MAX_YEAR_SHARE)
        candidate = bool(sample and mean_pass and median_pass and pf_pass and cum_pass and concentration and year_pass)
        rows.append({
            "exit_variant": variant,
            "full_history_trade_count": full,
            "validation_trade_count": val_n,
            "confirmation_trade_count": conf_n,
            "sample_pass": sample,
            "mean_positive_both_periods": mean_pass,
            "median_positive_both_periods": median_pass,
            "profit_factor_pass_both_periods": pf_pass,
            "cumulative_return_positive_both_periods": cum_pass,
            "trade_concentration_pass": concentration,
            "single_positive_year_profit_share": share,
            "year_concentration_pass": year_pass,
            "research_candidate_for_replication": candidate,
        })
    return pd.DataFrame(rows)


def choose_decision(repairs: pd.DataFrame, qual: pd.DataFrame) -> tuple[str, str, list[str]]:
    unresolved = int(repairs["quarantined"].sum()) if not repairs.empty else 0
    supported = qual.loc[qual["research_candidate_for_replication"], "exit_variant"].astype(str).tolist()
    if unresolved > 0:
        return (
            "PREMARKET_CORPORATE_ACTION_NORMALIZATION_INCOMPLETE_BLOCKED",
            "STOP_PREMARKET_BRANCH_PENDING_OFFICIAL_CORPORATE_ACTION_DATA",
            [],
        )
    if supported:
        return (
            "PREMARKET_CORPORATE_ACTION_SAFE_CANDIDATE_REQUIRES_INDEPENDENT_REPLICATION",
            "V22.062PR_FAST3_PREMARKET_INDEPENDENT_REPLICATION_R1",
            supported,
        )
    return (
        "PREMARKET_CORPORATE_ACTION_SAFE_EDGE_NOT_SUPPORTED",
        "V22.062A_FAST3_AFTER_HOURS_CLOSE_CONTINUATION_BASELINE_R1",
        [],
    )


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    raise TypeError(type(value))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column in {"source_instrument_return", "corrected_instrument_return", "mean_instrument_return", "median_instrument_return", "cumulative_return", "max_drawdown", "account_return_sum"}:
        return f"{float(value) * 10000:.2f}"
    if column in {"positive_rate", "top1_positive_profit_share", "top5_positive_profit_share", "single_positive_year_profit_share"}:
        return f"{float(value) * 100:.2f}"
    if column == "profit_factor":
        x = float(value)
        return "INF" if np.isinf(x) else f"{x:.3f}"
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
    for c in display.columns:
        display[c] = [format_value(c, v) for v in display[c]]
    print(display.to_string(index=False))


def run(v22_062p_root: Path, v22_062pa_root: Path, canonical_root: Path, result_dir: Path) -> dict[str, Any]:
    p_summary_path = v22_062p_root / "v22_062p_summary.json"
    p_trades_path = v22_062p_root / "v22_062p_trades.csv"
    pa_summary_path = v22_062pa_root / "v22_062pa_summary.json"
    pa_audit_path = v22_062pa_root / "v22_062pa_targeted_partition_audit.csv"
    for path in (p_summary_path, p_trades_path, pa_summary_path, pa_audit_path, canonical_root):
        if not path.exists():
            raise StudyError(f"Missing input: {path}")
    p_summary = json.loads(p_summary_path.read_text(encoding="utf-8-sig"))
    pa_summary = json.loads(pa_summary_path.read_text(encoding="utf-8-sig"))
    validate_p(p_summary)
    validate_pa(pa_summary)
    source = normalize_trades(pd.read_csv(p_trades_path))
    expected = int(p_summary["trade_record_count"])
    if len(source) != expected:
        raise StudyError(f"Trade count mismatch: {len(source)} vs {expected}")
    targets = flagged_ids(pd.read_csv(pa_audit_path), source)
    if not targets:
        raise StudyError("No targeted trades")
    canonical = index_canonical(canonical_root)
    cache = PartitionCache(canonical)
    repairs = pd.DataFrame([repair_trade(row, cache) for _, row in source.loc[source["trade_id"].isin(targets)].iterrows()])
    corrected = build_corrected(source, repairs, targets)
    daily = daily_returns(corrected)
    period = period_summary(corrected, daily)
    year = year_summary(corrected)
    qual = qualification(period, year)
    final_decision, next_stage, supported = choose_decision(repairs, qual)

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "repairs": result_dir / "v22_062pb_trade_normalization_audit.csv",
        "corrected": result_dir / "v22_062pb_corrected_trades.csv",
        "quarantine": result_dir / "v22_062pb_quarantined_trades.csv",
        "period": result_dir / "v22_062pb_corrected_period_summary.csv",
        "year": result_dir / "v22_062pb_corrected_year_summary.csv",
        "qualification": result_dir / "v22_062pb_corrected_qualification.csv",
        "summary": result_dir / "v22_062pb_summary.json",
    }
    repairs.to_csv(outputs["repairs"], index=False, encoding="utf-8-sig")
    corrected.to_csv(outputs["corrected"], index=False, encoding="utf-8-sig")
    corrected.loc[corrected["quarantined"]].to_csv(outputs["quarantine"], index=False, encoding="utf-8-sig")
    period.to_csv(outputs["period"], index=False, encoding="utf-8-sig")
    year.to_csv(outputs["year"], index=False, encoding="utf-8-sig")
    qual.to_csv(outputs["qualification"], index=False, encoding="utf-8-sig")

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": final_decision,
        "v22_062p_validated": True,
        "v22_062pa_validated": True,
        "source_trade_count": int(len(source)),
        "flagged_trade_count": int(len(targets)),
        "normalized_trade_count": int(len(repairs)),
        "recognized_execution_scale_event_count_during_holding": int(repairs["execution_event_count_during_holding"].sum()) if not repairs.empty else 0,
        "quarantined_trade_count": int(repairs["quarantined"].sum()) if not repairs.empty else 0,
        "included_corrected_trade_count": int(corrected["included"].sum()),
        "supported_exit_variants_for_replication": supported,
        "allowed_split_factors": list(ALLOWED_FACTORS),
        "split_factor_tolerance": FACTOR_TOLERANCE,
        "jump_threshold": JUMP_THRESHOLD,
        "corrected_extreme_return_limit": EXTREME_RETURN_LIMIT,
        "canonical_partition_count_indexed": int(len(canonical)),
        "canonical_partition_count_read": int(len(cache.paths_read)),
        "full_582_partition_reread": False,
        "strategy_signal_regeneration_executed": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "official_corporate_action_data_downloaded": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "next_stage": next_stage,
        "outputs": {k: str(v) for k, v in outputs.items()},
    }
    atomic_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.062PB corporate-action-safe normalization")
    print("==============================================")
    print_table("Targeted normalization audit", repairs[[
        "trade_id", "exit_variant", "study_period", "session_date", "execution_symbol",
        "source_instrument_return", "execution_event_count_during_holding",
        "execution_recognized_factors", "corrected_instrument_return",
        "qqq_normalized_gap_direction_valid", "soxx_normalized_gap_direction_valid",
        "quarantined", "quarantine_reasons",
    ]] if not repairs.empty else repairs)
    print_table("Corrected Validation / Confirmation", period.loc[period["study_period"].isin([VALIDATION, CONFIRMATION])])
    print_table("Corrected qualification", qual)
    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={final_decision}")
    print("V22_062P_VALIDATED=True")
    print("V22_062PA_VALIDATED=True")
    print(f"SOURCE_TRADE_COUNT={len(source)}")
    print(f"FLAGGED_TRADE_COUNT={len(targets)}")
    print(f"NORMALIZED_TRADE_COUNT={len(repairs)}")
    print(f"RECOGNIZED_EXECUTION_SCALE_EVENT_COUNT_DURING_HOLDING={summary['recognized_execution_scale_event_count_during_holding']}")
    print(f"QUARANTINED_TRADE_COUNT={summary['quarantined_trade_count']}")
    print(f"SUPPORTED_EXIT_VARIANTS_FOR_REPLICATION={supported}")
    print(f"CANONICAL_PARTITION_COUNT_READ={len(cache.paths_read)}")
    print("FULL_582_PARTITION_REREAD=False")
    print("STRATEGY_SIGNAL_REGENERATION_EXECUTED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("OFFICIAL_CORPORATE_ACTION_DATA_DOWNLOADED=False")
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v22-062p-root", default=r"D:\us-tech-quant-results\v22\V22.062P_FAST3_PREMARKET_GAP_AND_RANGE_BASELINE_R1")
    parser.add_argument("--v22-062pa-root", default=r"D:\us-tech-quant-results\v22\V22.062PA_FAST3_PREMARKET_EXTREME_RETURN_AUDIT_R1")
    parser.add_argument("--canonical-root", default=r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
    parser.add_argument("--result-dir", default=r"D:\us-tech-quant-results\v22\V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        run(Path(args.v22_062p_root), Path(args.v22_062pa_root), Path(args.canonical_root), Path(args.result_dir))
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
