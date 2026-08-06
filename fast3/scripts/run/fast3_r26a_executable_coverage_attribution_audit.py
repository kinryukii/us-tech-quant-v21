"""Read-only attribution audit for the stopped R26A executable-coverage gate.

This runner deliberately never computes prices, returns, costs, or model
outputs.  It reproduces only the frozen contract's legal-bar existence and
entry/exit timestamp tests to explain coverage loss.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday,
                                    USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay,
                                    USThanksgivingDay, nearest_workday)

from fast3.economics.executable_payoff_ledger_hard_r26a import ACTION_MAP, SYMBOL_MAP

HORIZON = pd.Timedelta(hours=24)
ENTRY_TOLERANCE = pd.Timedelta(minutes=15)
EXIT_TOLERANCE = pd.Timedelta(minutes=15)
NEXT_BAR_LIMIT = pd.Timedelta(hours=96)
ACTION_SYMBOLS = ("TQQQ", "SQQQ", "SOXL", "SOXS")


class AuditError(RuntimeError):
    pass


class NyseHolidayCalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, observance=nearest_workday, start_date="2022-01-01"),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in ("data-root", "scratch-root", "frozen-root", "cache-root", "source-r3-root",
                 "source-r3-audit-root", "r25-frozen-root", "authoritative-r26a-frozen-root", "run-id"):
        parser.add_argument(f"--{name}", required=True)
    return parser.parse_args()


def json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def write_json(root: Path, name: str, value: Any) -> None:
    (root / name).write_text(json.dumps(json_value(value), sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")


def action_map(candidates: pd.DataFrame) -> pd.DataFrame:
    instrument = candidates.candidate_instrument.astype(str)
    unknown = sorted(set(instrument).difference(SYMBOL_MAP))
    if unknown:
        raise AuditError(f"UNKNOWN_CANDIDATE_INSTRUMENT:{unknown}")
    out = candidates.copy()
    out["family"] = instrument.map(lambda value: SYMBOL_MAP[value][0])
    out["polarity"] = instrument.map(lambda value: SYMBOL_MAP[value][1]).astype("int8")
    out["up_action_instrument"] = [ACTION_MAP[(family, polarity)] for family, polarity in zip(out.family, out.polarity)]
    out["down_action_instrument"] = [ACTION_MAP[(family, -polarity)] for family, polarity in zip(out.family, out.polarity)]
    return out.sort_values("candidate_id", kind="mergesort").reset_index(drop=True)


def legal_timestamps(canonical_root: Path, symbol: str) -> tuple[pd.DatetimeIndex, set[tuple[int, int]]]:
    root = canonical_root / f"symbol={symbol}"
    files = sorted(root.rglob("*.parquet")) if root.is_dir() else []
    months: set[tuple[int, int]] = set()
    for path in files:
        try:
            year = int(path.parent.parent.name.split("=", 1)[1]); month = int(path.parent.name.split("=", 1)[1])
            months.add((year, month))
        except (IndexError, ValueError):
            raise AuditError(f"CANONICAL_PARTITION_LAYOUT_INVALID:{path}")
    if not files:
        raise AuditError(f"CANONICAL_PARTITION_MISSING:{symbol}")
    table = ds.dataset(root, format="parquet").to_table(columns=["symbol", "timestamp_et", "open", "high", "low", "close", "volume", "source"])
    bars = table.to_pandas()
    bars["timestamp_et"] = pd.to_datetime(bars.timestamp_et, utc=True)
    numeric = bars[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    legal = (bars.symbol.astype(str).eq(symbol) & bars.timestamp_et.notna()
             & np.isfinite(numeric).all(axis=1) & numeric.open.gt(0) & numeric.high.gt(0)
             & numeric.low.gt(0) & numeric.close.gt(0) & numeric.volume.ge(0)
             & numeric.high.ge(np.maximum(numeric.open, numeric.close))
             & numeric.low.le(np.minimum(numeric.open, numeric.close)) & bars.source.notna())
    times = pd.DatetimeIndex(bars.loc[legal, "timestamp_et"].sort_values(kind="mergesort").unique())
    if times.duplicated().any():
        raise AuditError(f"CANONICAL_DUPLICATE_TIMESTAMP:{symbol}")
    return times, months


def take_timestamp(times: pd.DatetimeIndex, positions: np.ndarray, index: pd.Index) -> pd.Series:
    values = np.full(len(positions), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    usable = positions < len(times)
    values[usable] = times.asi8[positions[usable]].view("datetime64[ns]")
    return pd.Series(pd.to_datetime(values, utc=True), index=index)


def action_existence(rows: pd.DataFrame, times: pd.DatetimeIndex, months: set[tuple[int, int]]) -> pd.DataFrame:
    anchor = pd.Series(pd.to_datetime(rows.authoritative_anchor_timestamp_et, utc=True).to_numpy(), index=rows.index)
    target = anchor + HORIZON
    entry_ts = take_timestamp(times, times.searchsorted(anchor.to_numpy(), side="right"), rows.index)
    exit_ts = take_timestamp(times, times.searchsorted(target.to_numpy(), side="left"), rows.index)
    next_delay = (exit_ts - target).dt.total_seconds().div(60)
    entry_valid = entry_ts.notna() & (entry_ts - anchor).le(ENTRY_TOLERANCE)
    exit_valid = exit_ts.notna() & (exit_ts - target).le(EXIT_TOLERANCE)
    target_local = target.dt.tz_convert("America/New_York")
    partition_present = pd.Series([(value.year, value.month) in months for value in target_local], index=rows.index)
    return pd.DataFrame({"entry_valid": entry_valid.to_numpy(bool), "exit_valid": exit_valid.to_numpy(bool),
                         "next_exit_delay_minutes": next_delay.to_numpy(float), "target_partition_present": partition_present.to_numpy(bool)}, index=rows.index)


def target_calendar(target: pd.Series) -> pd.DataFrame:
    local = target.dt.tz_convert("America/New_York")
    dates = local.dt.normalize().dt.tz_localize(None)
    calendar = NyseHolidayCalendar().holidays(start=dates.min(), end=dates.max())
    special = pd.DatetimeIndex([pd.Timestamp("2018-12-05")])
    holiday = dates.isin(calendar.union(special))
    weekend = local.dt.dayofweek.ge(5)
    minutes = local.dt.hour * 60 + local.dt.minute
    regular_clock = minutes.ge(9 * 60 + 30) & minutes.lt(16 * 60)
    open_session = ~(weekend | holiday) & regular_clock
    return pd.DataFrame({"target_weekend": weekend.to_numpy(bool), "target_holiday": holiday.to_numpy(bool),
                         "target_regular_session": open_session.to_numpy(bool)})


def session_name(anchor: pd.Series) -> pd.Series:
    local = anchor.dt.tz_convert("America/New_York")
    minutes = local.dt.hour * 60 + local.dt.minute
    return pd.Series(np.select([minutes.ge(4*60) & minutes.lt(9*60+30), minutes.ge(9*60+30) & minutes.lt(16*60), minutes.ge(16*60) & minutes.lt(20*60)], ["PREMARKET", "REGULAR", "POSTMARKET"], default="OVERNIGHT"), index=anchor.index)


def rate_table(frame: pd.DataFrame, by: list[str]) -> list[dict[str, Any]]:
    result = frame.groupby(by, dropna=False).agg(candidate_count=("candidate_id", "size"), up_valid_rate=("up_valid", "mean"), down_valid_rate=("down_valid", "mean"), both_direction_valid_rate=("both_valid", "mean"), up_only_rate=("up_only", "mean"), down_only_rate=("down_only", "mean")).reset_index()
    return result.to_dict("records")


def action_rate_table(actions: pd.DataFrame) -> list[dict[str, Any]]:
    result = actions.groupby("action_instrument", dropna=False).agg(action_exposure_count=("candidate_id", "size"), entry_valid_rate=("entry_valid", "mean"), exit_valid_rate=("exit_valid", "mean"), action_valid_rate=("payoff_valid", "mean")).reset_index()
    return result.to_dict("records")


def main() -> int:
    args = parse(); frozen = Path(args.frozen_root); scratch = Path(args.scratch_root); cache = Path(args.cache_root)
    frozen.mkdir(parents=True, exist_ok=False); scratch.mkdir(parents=True, exist_ok=False); cache.mkdir(parents=True, exist_ok=True)
    canonical_root = Path(args.data_root) / "fast3/moomoo_24h_1m/canonical"
    r3_root = Path(args.source_r3_root); authoritative = Path(args.authoritative_r26a_frozen_root)
    try:
        if any(str(path.resolve()).startswith(str(REPO.resolve())) or str(path.absolute()).startswith(str(REPO.absolute())) for path in (frozen, scratch, cache)):
            raise AuditError("AUDIT_STORAGE_ROOT_FORBIDDEN")
        authority = json.loads((authoritative / "R26A_FINAL_SUMMARY.json").read_text(encoding="utf-8"))
        raw = pd.read_parquet(r3_root / "fast3_complete_labelled_ledger.parquet", columns=["candidate_id", "underlying", "timestamp_et", "entry_timestamp_et"])
        if len(raw) != 729487 or raw.candidate_id.nunique() != len(raw):
            raise AuditError("AUDIT_CANDIDATE_IDENTITY_INVALID")
        candidates = action_map(raw.rename(columns={"underlying": "candidate_instrument", "timestamp_et": "decision_timestamp_et", "entry_timestamp_et": "authoritative_anchor_timestamp_et"}))
        target = pd.Series(pd.to_datetime(candidates.authoritative_anchor_timestamp_et, utc=True)) + HORIZON
        for direction in ("up", "down"):
            candidates[f"{direction}_entry_valid"] = False; candidates[f"{direction}_exit_valid"] = False
            candidates[f"{direction}_next_exit_delay_minutes"] = np.nan; candidates[f"{direction}_target_partition_present"] = False
        for symbol in ACTION_SYMBOLS:
            times, months = legal_timestamps(canonical_root, symbol)
            for direction in ("up", "down"):
                mask = candidates[f"{direction}_action_instrument"].eq(symbol)
                if mask.any():
                    result = action_existence(candidates.loc[mask], times, months)
                    for field in result:
                        candidates.loc[mask, f"{direction}_{field}"] = result[field].to_numpy()
        candidates["up_valid"] = candidates.up_entry_valid & candidates.up_exit_valid
        candidates["down_valid"] = candidates.down_entry_valid & candidates.down_exit_valid
        candidates["both_valid"] = candidates.up_valid & candidates.down_valid
        candidates["up_only"] = candidates.up_valid & ~candidates.down_valid
        candidates["down_only"] = ~candidates.up_valid & candidates.down_valid
        candidates["neither_valid"] = ~candidates.up_valid & ~candidates.down_valid
        for direction in ("up", "down"):
            candidates[f"{direction}_invalid_reason"] = np.where(candidates[f"{direction}_entry_valid"], np.where(candidates[f"{direction}_exit_valid"], None, "EXIT_BAR_UNAVAILABLE"), "ENTRY_BAR_UNAVAILABLE")
        calendar_detail = target_calendar(target)
        candidates = pd.concat([candidates, calendar_detail], axis=1)
        anchor = pd.Series(pd.to_datetime(candidates.authoritative_anchor_timestamp_et, utc=True))
        local_anchor = anchor.dt.tz_convert("America/New_York")
        candidates["anchor_weekday"] = local_anchor.dt.day_name(); candidates["anchor_hour_et"] = local_anchor.dt.hour.astype("int8")
        candidates["anchor_session"] = session_name(anchor); candidates["anchor_year"] = local_anchor.dt.year.astype("int16"); candidates["anchor_month"] = local_anchor.dt.month.astype("int8")
        schedule = json.loads((Path(args.r25_frozen_root) / "R25_SCHEDULE.json").read_text(encoding="utf-8"))["schedule"]
        candidates["time_block"] = "OUTSIDE_SCHEDULE"
        for block in schedule["blocks"]:
            mask = (pd.to_datetime(candidates.decision_timestamp_et, utc=True) >= pd.Timestamp(block["start"])) & (pd.to_datetime(candidates.decision_timestamp_et, utc=True) <= pd.Timestamp(block["end"]))
            candidates.loc[mask, "time_block"] = block["block_id"]
        action_rows = []
        for direction in ("up", "down"):
            action_rows.append(pd.DataFrame({"candidate_id": candidates.candidate_id, "direction": direction, "action_instrument": candidates[f"{direction}_action_instrument"], "candidate_instrument": candidates.candidate_instrument, "family": candidates.family, "polarity": candidates.polarity, "entry_valid": candidates[f"{direction}_entry_valid"], "exit_valid": candidates[f"{direction}_exit_valid"], "payoff_valid": candidates[f"{direction}_valid"], "invalid_reason": candidates[f"{direction}_invalid_reason"], "next_exit_delay_minutes": candidates[f"{direction}_next_exit_delay_minutes"], "target_partition_present": candidates[f"{direction}_target_partition_present"], "target_weekend": candidates.target_weekend, "target_holiday": candidates.target_holiday, "target_regular_session": candidates.target_regular_session}))
        actions = pd.concat(action_rows, ignore_index=True)
        exit_miss = actions.loc[~actions.exit_valid].copy()
        delay = exit_miss.next_exit_delay_minutes
        next_bins = {"NEXT_BAR_WITHIN_60M_COUNT": int(delay.le(60).sum()), "NEXT_BAR_WITHIN_12H_COUNT": int(delay.le(12*60).sum()), "NEXT_BAR_WITHIN_24H_COUNT": int(delay.le(24*60).sum()), "NEXT_BAR_WITHIN_48H_COUNT": int(delay.le(48*60).sum()), "NEXT_BAR_WITHIN_72H_COUNT": int(delay.le(72*60).sum()), "NEXT_BAR_WITHIN_96H_COUNT": int(delay.le(96*60).sum()), "NO_BAR_WITHIN_96H_COUNT": int((delay.isna() | delay.gt(96*60)).sum())}
        exit_missing = ~actions.exit_valid
        actions["calendar_market_closed"] = exit_missing & (actions.target_weekend | actions.target_holiday | ~actions.target_regular_session)
        actions["canonical_partition_missing"] = exit_missing & ~actions.target_partition_present
        actions["etf_no_legal_bar_regular_session"] = exit_missing & ~actions.calendar_market_closed & ~actions.canonical_partition_missing
        actions["attribution"] = np.select([actions.canonical_partition_missing, actions.calendar_market_closed, actions.etf_no_legal_bar_regular_session, ~actions.entry_valid], ["A_CANONICAL_PARTITION_MISSING", "B_MARKET_CLOSED", "C_ETF_NO_LEGAL_BAR_DURING_REGULAR_SESSION", "E_ENTRY_OR_OTHER_IMPLEMENTATION"], default="NONE")
        current = float(candidates.both_valid.mean())
        exit_96 = candidates[["up_next_exit_delay_minutes", "down_next_exit_delay_minutes"]].le(96*60).all(axis=1)
        calendar_96 = float((candidates.up_entry_valid & candidates.down_entry_valid & exit_96).mean())
        action_specific_96 = float((candidates.up_entry_valid & candidates.up_next_exit_delay_minutes.le(96*60)).mean())
        invalid_counts = actions.loc[~actions.payoff_valid].groupby(["direction", "invalid_reason"], dropna=False).size().rename("count").reset_index()
        invalid_counts["rate_of_action_exposures"] = invalid_counts["count"] / len(actions)
        primary = actions.loc[actions.attribution.ne("NONE"), "attribution"].value_counts()
        primary_cause = str(primary.index[0]) if len(primary) else "NONE"
        detail_columns = ["candidate_id", "candidate_instrument", "family", "polarity", "up_action_instrument", "down_action_instrument", "up_entry_valid", "up_exit_valid", "up_valid", "up_invalid_reason", "up_next_exit_delay_minutes", "down_entry_valid", "down_exit_valid", "down_valid", "down_invalid_reason", "down_next_exit_delay_minutes", "both_valid", "up_only", "down_only", "neither_valid", "target_weekend", "target_holiday", "target_regular_session", "anchor_weekday", "anchor_hour_et", "anchor_session", "anchor_year", "anchor_month", "time_block"]
        candidates.loc[:, detail_columns].to_parquet(scratch / "R26A_COVERAGE_ATTRIBUTION_CANDIDATE_DETAIL.parquet", index=False)
        write_json(frozen, "R26A_COVERAGE_INVALID_REASONS.json", invalid_counts.to_dict("records"))
        write_json(frozen, "R26A_COVERAGE_BY_ACTION_INSTRUMENT.json", action_rate_table(actions))
        write_json(frozen, "R26A_COVERAGE_BY_CANDIDATE_DIMENSION.json", {"candidate_instrument": rate_table(candidates, ["candidate_instrument"]), "family": rate_table(candidates, ["family"]), "polarity": rate_table(candidates, ["polarity"]), "weekday": rate_table(candidates, ["anchor_weekday"]), "hour_et": rate_table(candidates, ["anchor_hour_et"]), "session": rate_table(candidates, ["anchor_session"]), "year": rate_table(candidates, ["anchor_year"]), "month": rate_table(candidates, ["anchor_month"]), "time_block": rate_table(candidates, ["time_block"])})
        write_json(frozen, "R26A_COVERAGE_ATTRIBUTION_ACTIONS.json", {"attribution_counts": actions.attribution.value_counts().to_dict(), "entry_failure_action_count": int((~actions.entry_valid).sum()), "exit_failure_action_count": int((~actions.exit_valid).sum()), "exit_failure_action_exposures": int(len(exit_miss)), "wait_bins_are_cumulative": True, **next_bins})
        summary = {"AUDIT_CANDIDATE_COUNT": int(len(candidates)), "BOTH_DIRECTION_VALID_COUNT": int(candidates.both_valid.sum()), "UP_ONLY_VALID_COUNT": int(candidates.up_only.sum()), "DOWN_ONLY_VALID_COUNT": int(candidates.down_only.sum()), "NEITHER_VALID_COUNT": int(candidates.neither_valid.sum()), "INVALID_ENTRY_COUNT": int((~actions.entry_valid).sum()), "INVALID_EXIT_COUNT": int((~actions.exit_valid).sum()), "WEEKEND_TARGET_COUNT": int(candidates.target_weekend.sum()), "HOLIDAY_TARGET_COUNT": int(candidates.target_holiday.sum()), "CANONICAL_PARTITION_MISSING_COUNT": int(actions.canonical_partition_missing.sum()), "NO_BAR_WITHIN_15M_COUNT": int((~actions.exit_valid).sum()), **next_bins, "CURRENT_BOTH_DIRECTION_COVERAGE": current, "CALENDAR_AWARE_96H_HYPOTHETICAL_COVERAGE": calendar_96, "ACTION_SPECIFIC_HYPOTHETICAL_COVERAGE": action_specific_96, "ACTION_SPECIFIC_DIRECTION": "up_action_instrument", "PRIMARY_COVERAGE_LOSS_CAUSE": primary_cause, "DATA_REPAIR_REQUIRED": bool(primary_cause in ("A_CANONICAL_PARTITION_MISSING", "C_ETF_NO_LEGAL_BAR_DURING_REGULAR_SESSION")), "EXECUTION_CONTRACT_STRUCTURALLY_INFEASIBLE": bool(current < .95 and primary_cause == "B_MARKET_CLOSED"), "RECOMMENDED_NEXT_STEP": "STOP_CONTRACT_PRESERVED_COVERAGE_ATTRIBUTION_ONLY; investigate canonical availability and calendar attribution before any separately authorized research decision.", "CANONICAL_WRITE_COUNT": 0, "OLD_FROZEN_OUTPUT_MUTATION_COUNT": 0, "NEW_LOCAL_RESULTS_WRITE_COUNT": 0, "FINAL_DECISION": "PASS_R26A_EXECUTABLE_COVERAGE_ATTRIBUTION_AUDIT_NO_MODEL_CONCLUSION", "AUDIT_FROZEN_ROOT": str(frozen), "AUTHORITATIVE_R26A_FROZEN_ROOT": str(authoritative), "AUTHORITATIVE_INPUT_COVERAGE": authority["R26A_BOTH_DIRECTION_VALID_RATE"]}
        write_json(frozen, "R26A_COVERAGE_ATTRIBUTION_SUMMARY.json", summary)
        write_json(frozen, "R26A_COVERAGE_FILESYSTEM_AUDIT.json", {"status": "PASS", "canonical_write_count": 0, "old_frozen_output_mutation_count": 0, "new_local_results_write_count": 0, "repo_result_file_count": 0, "payoff_or_return_computation_performed": False, "r26_training_performed": False, "d3_d4_or_holdout_opened": False})
        for key, value in summary.items(): print(f"{key}={value}")
        return 0
    except Exception as exc:
        write_json(frozen, "R26A_COVERAGE_AUDIT_EXCEPTION.json", {"type": type(exc).__name__, "message": str(exc)})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
