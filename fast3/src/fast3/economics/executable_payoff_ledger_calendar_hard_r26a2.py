"""R26A2's single calendar-aware, real-ETF payoff ledger.

The implementation deliberately reuses the R26A1 canonical-bar, JSON and
hashing contracts.  The only economic change is the independently-audited
calendar allowance on the *exit* after the immutable 24-hour target.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday,
                                    USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay,
                                    USThanksgivingDay, nearest_workday)

from fast3.economics import executable_payoff_ledger_hard_r26a as base

SYMBOL_MAP, ACTION_MAP, COSTS = base.SYMBOL_MAP, base.ACTION_MAP, base.COSTS
HORIZON_HOURS, MAX_EXIT_HOURS = 24, 96
EXECUTION_CONTRACT_VERSION = "R26A2_CALENDAR_AWARE_NEXT_LEGAL_BAR_AFTER_24H_MAX_96H"
R26A2ContractError = base.R26AContractError
canonical_json, stable_hash, file_hash, bar_hash, legal_bars = (base.canonical_json, base.stable_hash, base.file_hash, base.bar_hash, base.legal_bars)
assert_candidate_map, _range_extreme = base.assert_candidate_map, base._range_extreme

_BASE = ("candidate_id", "candidate_instrument", "decision_timestamp_et", "authoritative_anchor_timestamp_et", "family", "polarity", "up_action_instrument", "down_action_instrument")
_ACTION = ("entry_timestamp_et", "entry_price", "entry_delay_minutes", "theoretical_exit_timestamp_et", "actual_exit_timestamp_et", "exit_price", "calendar_exit_delay_minutes", "exchange_weekend_at_theoretical_exit", "exchange_holiday_at_theoretical_exit", "market_closed_at_theoretical_exit", "regular_session_expected_at_theoretical_exit", "exit_reason", "action_gross_return", "action_net_return_5bps", "action_net_return_10bps", "action_net_return_20bps", "action_mfe", "action_mae", "entry_bar_hash", "exit_bar_hash", "path_hash", "payoff_valid", "invalid_reason")
PAYOFF_ROW_HASH_SCHEMA = _BASE + tuple(f"{d}_{f}" for d in ("up", "down") for f in _ACTION) + ("frozen_horizon_hours", "source_candidate_hash", "canonical_partition_manifest_hash", "execution_contract_hash")
_NUMERIC = ("entry_price", "exit_price", "action_gross_return", "action_net_return_5bps", "action_net_return_10bps", "action_net_return_20bps", "action_mfe", "action_mae")
_NULL_ON_INVALID = tuple(x for x in _ACTION if x not in ("theoretical_exit_timestamp_et", "payoff_valid", "invalid_reason"))
_NEW_YORK = "America/New_York"
_CALENDAR_FIELDS = ("exchange_weekend_at_theoretical_exit", "exchange_holiday_at_theoretical_exit", "market_closed_at_theoretical_exit", "regular_session_expected_at_theoretical_exit")


class _FrozenNyseHolidayCalendar(AbstractHolidayCalendar):
    """The complete-closure calendar frozen by the R26A coverage audit.

    This deliberately is not ``USFederalHolidayCalendar``: its rules express
    NYSE full-day closures and deliberately exclude early closes.  The single
    special closure is also part of the existing frozen audit contract.
    """

    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, observance=nearest_workday,
                start_date="2022-01-01"),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


def _utc_datetime_series(values: Any, index: pd.Index) -> pd.Series:
    """Normalize every missing datetime representation to tz-aware UTC NaT."""
    converted = pd.to_datetime(values, utc=True, errors="coerce")
    return pd.Series(pd.DatetimeIndex(converted), index=index,
                     dtype="datetime64[ns, UTC]")


def _holiday_dates(start: pd.Timestamp, end: pd.Timestamp) -> set[date]:
    """Return full NYSE-closure dates for an already-valid timestamp range.

    Source: the repository's frozen R26A coverage-attribution NYSE calendar.
    The function receives timezone-aware values only; calling calendar methods
    on NaT is a contract error rather than an inferred non-holiday.
    """
    if pd.isna(start) or pd.isna(end) or start.tzinfo is None or end.tzinfo is None:
        raise R26A2ContractError("R26A2_CALENDAR_TIMESTAMP_UNAVAILABLE")
    local_start = start.tz_convert(_NEW_YORK).normalize().tz_localize(None)
    local_end = end.tz_convert(_NEW_YORK).normalize().tz_localize(None)
    days = _FrozenNyseHolidayCalendar().holidays(start=local_start, end=local_end)
    return {item.date() for item in days}.union({date(2018, 12, 5)})


def _calendar_diagnostics(target: pd.Series, valid: pd.Series) -> pd.DataFrame:
    """Classify valid theoretical exits without ever operating on NaT.

    All diagnostic columns use pandas' nullable BooleanDtype.  An invalid
    payoff is calendar-unknown by contract, so it remains ``pd.NA`` instead of
    being coerced to false.
    """
    result = pd.DataFrame({field: pd.Series(pd.array([pd.NA] * len(target), dtype="boolean"), index=target.index)
                           for field in _CALENDAR_FIELDS}, index=target.index)
    usable = target.notna() & valid
    if not usable.any():
        return result
    local = target.loc[usable].dt.tz_convert(_NEW_YORK)
    holidays = _holiday_dates(local.min(), local.max())
    weekend = local.dt.dayofweek.ge(5)
    holiday = local.dt.date.isin(holidays)
    market_closed = weekend | holiday
    minute = local.dt.hour * 60 + local.dt.minute
    regular_session = (~market_closed) & minute.ge(9 * 60 + 30) & minute.lt(16 * 60)
    result.loc[usable, "exchange_weekend_at_theoretical_exit"] = pd.array(weekend, dtype="boolean")
    result.loc[usable, "exchange_holiday_at_theoretical_exit"] = pd.array(holiday, dtype="boolean")
    result.loc[usable, "market_closed_at_theoretical_exit"] = pd.array(market_closed, dtype="boolean")
    result.loc[usable, "regular_session_expected_at_theoretical_exit"] = pd.array(regular_session, dtype="boolean")
    return result


def _is_aware_timestamp(value: Any) -> bool:
    if base._is_missing(value):
        return False
    return pd.Timestamp(value).tzinfo is not None


def _assert_row(row: dict[str, Any]) -> None:
    for direction in ("up", "down"):
        valid = row[f"{direction}_payoff_valid"]
        if base._is_missing(valid):
            raise R26A2ContractError(f"R26A2_PAYOFF_VALIDITY_MISSING:{row['candidate_id']}:{direction}")
        if bool(valid):
            for field in ("entry_timestamp_et", "theoretical_exit_timestamp_et", "actual_exit_timestamp_et"):
                if not _is_aware_timestamp(row[f"{direction}_{field}"]):
                    raise R26A2ContractError(f"R26A2_VALID_PAYOFF_TIMESTAMP_UNAVAILABLE:{row['candidate_id']}:{direction}_{field}")
            for field in _CALENDAR_FIELDS:
                value = row[f"{direction}_{field}"]
                if base._is_missing(value):
                    raise R26A2ContractError(f"R26A2_VALID_PAYOFF_CALENDAR_UNKNOWN:{row['candidate_id']}:{direction}_{field}")
            for field in _NUMERIC:
                value = row[f"{direction}_{field}"]
                if base._is_missing(value) or not np.isfinite(float(value)):
                    raise R26A2ContractError(f"R26A2_VALID_PAYOFF_NONFINITE:{row['candidate_id']}:{direction}_{field}")
        else:
            if base._is_missing(row[f"{direction}_invalid_reason"]):
                raise R26A2ContractError(f"R26A2_INVALID_PAYOFF_REASON_MISSING:{row['candidate_id']}:{direction}")
            for field in _NULL_ON_INVALID:
                if not base._is_missing(row[f"{direction}_{field}"]):
                    raise R26A2ContractError(f"R26A2_INVALID_PAYOFF_FIELD_NOT_NULL:{row['candidate_id']}:{direction}_{field}")


def payoff_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    if tuple(row) != PAYOFF_ROW_HASH_SCHEMA:
        raise R26A2ContractError("R26A2_PAYOFF_ROW_HASH_SCHEMA_INVALID")
    _assert_row(row)
    return {key: row[key] for key in PAYOFF_ROW_HASH_SCHEMA}


def payoff_row_hashes(frame: pd.DataFrame) -> list[str]:
    if tuple(frame.columns) != PAYOFF_ROW_HASH_SCHEMA:
        raise R26A2ContractError("R26A2_PAYOFF_ROW_HASH_SCHEMA_INVALID")
    return [stable_hash(payoff_row_payload(row)) for row in frame.to_dict("records")]


def _action_partition_schema(prefix: str) -> tuple[str, ...]:
    """The sole merge payload schema for one action direction.

    Static mapping fields such as ``up_action_instrument`` belong only to the
    candidate-side schema.  They must never cross this merge boundary, because
    pandas would silently rename them to ``_x``/``_y`` and remove the fixed
    payoff schema's canonical mapping fields.
    """
    return ("candidate_id", *(f"{prefix}_{field}" for field in _ACTION), f"_{prefix}_old_valid")


def _join_action(rows: pd.DataFrame, bars: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """One partitioned vectorized as-of entry/exit join; never synthesize ETF PnL."""
    if rows.candidate_id.isna().any() or not rows.candidate_id.is_unique:
        raise R26A2ContractError("R26A2_CANDIDATE_ID_INVALID")
    x = rows.copy().sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    anchor = _utc_datetime_series(x.authoritative_anchor_timestamp_et, x.index)
    x["_anchor"] = anchor
    right = bars[["timestamp_et", "open", "bar_hash"]].rename(columns={"timestamp_et":"_bar_ts", "open":"_price", "bar_hash":"_bar_hash"}).copy()
    right["_bar_ts"] = _utc_datetime_series(right["_bar_ts"], right.index)
    right = right.sort_values("_bar_ts")
    ent = pd.merge_asof(x.sort_values("_anchor"), right, left_on="_anchor", right_on="_bar_ts", direction="forward", allow_exact_matches=False).sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    entry_ts = _utc_datetime_series(ent._bar_ts, x.index)
    entry_target = entry_ts + pd.Timedelta(hours=HORIZON_HOURS)
    exit_left = x.copy(); exit_left["_entry_target"] = entry_target
    available = exit_left._entry_target.notna()
    exit_join = pd.merge_asof(exit_left.loc[available].sort_values("_entry_target"), right, left_on="_entry_target", right_on="_bar_ts", direction="forward", allow_exact_matches=True)
    absent = exit_left.loc[~available].copy()
    absent["_bar_ts"] = pd.NaT; absent["_price"] = np.nan; absent["_bar_hash"] = None
    ext = pd.concat([exit_join, absent], ignore_index=True).sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    if not (ent.candidate_id.equals(x.candidate_id) and ext.candidate_id.equals(x.candidate_id)):
        raise R26A2ContractError("R26A2_ASOF_CANDIDATE_ALIGNMENT_INVALID")
    exit_ts = _utc_datetime_series(ext._bar_ts, x.index)
    target = entry_target
    entry_delay = (entry_ts - anchor).dt.total_seconds() / 60.0
    exit_delay = (exit_ts - target).dt.total_seconds() / 60.0
    entry_ok = entry_ts.notna() & entry_delay.gt(0) & entry_delay.le(15)
    exit_ok = exit_ts.notna() & exit_delay.ge(0) & exit_delay.le(MAX_EXIT_HOURS * 60)
    valid = entry_ok & exit_ok
    calendar = _calendar_diagnostics(target, valid)
    gross = ext._price / ent._price - 1.0
    x[f"{prefix}_entry_timestamp_et"] = entry_ts.where(valid)
    x[f"{prefix}_entry_price"] = ent._price.where(valid)
    x[f"{prefix}_entry_delay_minutes"] = entry_delay.where(valid)
    x[f"{prefix}_theoretical_exit_timestamp_et"] = target
    x[f"{prefix}_actual_exit_timestamp_et"] = exit_ts.where(valid)
    x[f"{prefix}_exit_price"] = ext._price.where(valid)
    x[f"{prefix}_calendar_exit_delay_minutes"] = exit_delay.where(valid)
    for field in _CALENDAR_FIELDS:
        x[f"{prefix}_{field}"] = calendar[field]
    x[f"{prefix}_exit_reason"] = np.where(valid, "NEXT_LEGAL_BAR_AFTER_FROZEN_24H_HORIZON", None)
    x[f"{prefix}_action_gross_return"] = gross.where(valid)
    for cost in COSTS:
        x[f"{prefix}_action_net_return_{int(cost * 10000)}bps"] = (gross - cost).where(valid)
    starts = bars.timestamp_et.searchsorted(entry_ts.fillna(pd.Timestamp("1900-01-01", tz="UTC")).to_numpy(), side="left")
    ends = bars.timestamp_et.searchsorted(exit_ts.fillna(pd.Timestamp("1900-01-01", tz="UTC")).to_numpy(), side="right") - 1
    maximum = _range_extreme(bars.high.to_numpy(float), starts, ends, True)
    minimum = _range_extreme(bars.low.to_numpy(float), starts, ends, False)
    x[f"{prefix}_action_mfe"] = (maximum / ent._price.to_numpy(float) - 1.0); x[f"{prefix}_action_mae"] = (minimum / ent._price.to_numpy(float) - 1.0)
    x.loc[~valid, [f"{prefix}_action_mfe", f"{prefix}_action_mae"]] = np.nan
    x[f"{prefix}_entry_bar_hash"] = ent._bar_hash.where(valid); x[f"{prefix}_exit_bar_hash"] = ext._bar_hash.where(valid)
    x[f"{prefix}_path_hash"] = [stable_hash({"entry":a,"exit":b,"instrument":i}) if ok else None for a,b,i,ok in zip(x[f"{prefix}_entry_bar_hash"], x[f"{prefix}_exit_bar_hash"], x[f"{prefix}_action_instrument"], valid)]
    x[f"{prefix}_payoff_valid"] = valid
    x[f"{prefix}_invalid_reason"] = np.where(valid, None, np.where(~entry_ok, "ENTRY_BAR_UNAVAILABLE", np.where(exit_ts.isna(), "EXIT_BAR_UNAVAILABLE", "EXECUTION_DELAY_OUT_OF_BOUNDS")))
    # In-memory lineage proof only; never written as a second payoff ledger.
    x[f"_{prefix}_old_valid"] = entry_ok & exit_ts.notna() & exit_delay.ge(0) & exit_delay.le(15)
    return x.drop(columns=["_anchor"])


def construct_payoffs(candidates: pd.DataFrame, canonical_root) -> tuple[pd.DataFrame, dict[str, Any]]:
    x = assert_candidate_map(candidates)
    if x.candidate_id.isna().any() or not x.candidate_id.is_unique:
        raise R26A2ContractError("R26A2_CANDIDATE_ID_INVALID")
    x = x.sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
    pieces: dict[str, list[pd.DataFrame]] = {"up":[], "down":[]}; manifests = {}
    for instrument in sorted(set(x.up_action_instrument).union(x.down_action_instrument)):
        bars, manifest = legal_bars(canonical_root, instrument); manifests[instrument] = manifest
        for direction in ("up", "down"):
            subset = x.loc[x[f"{direction}_action_instrument"].eq(instrument)]
            if not subset.empty:
                joined = _join_action(subset, bars, direction)
                # Whitelist only the computed action schema.  The joined frame
                # also retains static action mappings from its candidate input;
                # merging those back would overwrite them with pandas suffixes.
                schema = _action_partition_schema(direction)
                missing = set(schema).difference(joined.columns)
                if missing:
                    raise R26A2ContractError(f"R26A2_ACTION_PARTITION_SCHEMA_MISSING:{direction}:{sorted(missing)}")
                pieces[direction].append(joined.loc[:, schema])
    out = x.copy()
    for direction in ("up", "down"):
        if not pieces[direction]:
            raise R26A2ContractError(f"R26A2_ACTION_PARTITION_EMPTY:{direction}")
        schema = _action_partition_schema(direction)
        part = pd.concat(pieces[direction], ignore_index=True).loc[:, schema]
        part = part.sort_values("candidate_id", kind="mergesort").reset_index(drop=True)
        if tuple(part.columns) != schema:
            raise R26A2ContractError(f"R26A2_ACTION_PARTITION_SCHEMA_INVALID:{direction}")
        for name, frame in (("left", out), ("right", part)):
            if frame.candidate_id.isna().any() or not frame.candidate_id.is_unique:
                raise R26A2ContractError(f"R26A2_ACTION_PARTITION_KEY_INVALID:{direction}:{name}")
        if not pd.api.types.is_dtype_equal(out.candidate_id.dtype, part.candidate_id.dtype):
            raise R26A2ContractError(f"R26A2_ACTION_PARTITION_KEY_DTYPE_INVALID:{direction}")
        if set(schema[1:]).intersection(out.columns):
            raise R26A2ContractError(f"R26A2_ACTION_PARTITION_COLUMN_CONFLICT:{direction}")
        if len(part) != len(out) or not part.candidate_id.equals(out.candidate_id):
            raise R26A2ContractError(f"R26A2_ACTION_PARTITION_CANDIDATE_COVERAGE_INVALID:{direction}")
        out = out.merge(part, on="candidate_id", how="left", validate="one_to_one")
        if (len(out) != len(x) or not out.candidate_id.equals(x.candidate_id)
                or any(column.endswith(("_x", "_y")) for column in out.columns)):
            raise R26A2ContractError(f"R26A2_ACTION_PARTITION_MERGE_INVALID:{direction}")
    rescued = (out.up_payoff_valid & out.down_payoff_valid & ~(out._up_old_valid & out._down_old_valid))
    rescue_ok = bool((out.loc[rescued, "up_entry_timestamp_et"].notna() & out.loc[rescued, "down_entry_timestamp_et"].notna()).all())
    rescue = {"rescued_both_direction_count":int(rescued.sum()), "old_both_direction_valid_count":int((out._up_old_valid & out._down_old_valid).sum()), "rescued_entry_lineage_pass":rescue_ok, "rescued_only_old_exit_window":bool((~(out.loc[rescued, "_up_old_valid"] & out.loc[rescued, "_down_old_valid"])).all())}
    out = out.drop(columns=["_up_old_valid", "_down_old_valid"])
    out["frozen_horizon_hours"] = HORIZON_HOURS
    out["source_candidate_hash"] = [stable_hash({"candidate_id":cid,"anchor":str(anchor),"instrument":inst}) for cid,anchor,inst in zip(out.candidate_id, out.authoritative_anchor_timestamp_et, out.candidate_instrument)]
    partition_hash = stable_hash(manifests); out["canonical_partition_manifest_hash"] = partition_hash
    contract = {"execution_contract_version":EXECUTION_CONTRACT_VERSION,"anchor_field":"entry_timestamp_et","horizon_hours":24,"entry":"first legal action-ETF 1m bar strictly after anchor within 15m; open","exit":"first legal action-ETF 1m bar at/after entry+24h within 96h; open","costs":list(COSTS)}
    out["execution_contract_hash"] = stable_hash(contract)
    out = out.loc[:, PAYOFF_ROW_HASH_SCHEMA].copy()
    out["payoff_row_hash"] = payoff_row_hashes(out)
    return out, {"partition_manifest":manifests,"partition_manifest_hash":partition_hash,"execution_contract":contract,"rescue":rescue}


def payoff_audit(frame: pd.DataFrame, expected_ids: pd.Series) -> dict[str, Any]:
    duplicate = int(frame.candidate_id.duplicated().sum()); missing = int((~expected_ids.isin(frame.candidate_id)).sum()); unexpected = int((~frame.candidate_id.isin(expected_ids)).sum())
    both = frame.up_payoff_valid & frame.down_payoff_valid; price_ok = arithmetic_ok = True
    for direction in ("up", "down"):
        valid = frame[f"{direction}_payoff_valid"]
        prices = frame.loc[valid, [f"{direction}_entry_price", f"{direction}_exit_price"]].to_numpy(float)
        price_ok &= bool(np.isfinite(prices).all() and (prices > 0).all())
        gross = frame.loc[valid, f"{direction}_exit_price"] / frame.loc[valid, f"{direction}_entry_price"] - 1.0
        for cost in COSTS:
            arithmetic_ok &= bool(np.allclose(gross-cost, frame.loc[valid, f"{direction}_action_net_return_{int(cost*10000)}bps"], rtol=0, atol=1e-14))
    return {"candidate_count":int(len(frame)),"unique_candidate_count":int(frame.candidate_id.nunique()),"duplicate_candidate_count":duplicate,"missing_candidate_count":missing,"unexpected_candidate_count":unexpected,"both_direction_valid_rate":float(both.mean()),"valid_prices_pass":price_ok,"cost_reproduction_pass":arithmetic_ok}
