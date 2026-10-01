"""Pure Top20 history ranking and conservative Moomoo history-quota planning.

No file, SDK, network, clock, or research-result reads occur here. Callers supply
already authorized records and a *fresh successful* get_history_kl_quota result.
Each record needs date (ISO session date), ticker, integer rank, and the explicit
record_kind ``daily_recommendation``. Explicitly authorized ``bootstrap_records``
may instead have kind ``historical_replay`` and must identify a single model_id
and source_id. They only initialize data-acquisition priority, not today's picks.
Same-day daily results replace that day's replay results. The caller is
responsible for verifying that these are reliable computed results.

The window is the latest 60 dates with reliable results, even if they are old.
Optional authoritative exchange ``trading_dates`` validates session membership;
it does not change the window to the 60 calendar sessions preceding today.
Top20 frequency ranks first; other symbols in the same source's Top40 fill the
remaining priority positions. Each ticker counts at most once per session.
``universe`` optionally adds requested symbols and explicit provider mappings,
using the conventions of refresh_market_data.load_universe. Special tickers
need an explicit moomoo_symbol/moomoo_code; punctuation is never guessed away.
Optional ``pool_supplement`` explicitly authorizes further current-pool members
for new quota after Top20/Top40. Each row has ticker and last_price_date (ISO
date or None for missing). The caller must verify current pool membership and
usable price coverage; the planner neither discovers nor trusts catalog pools.
Missing prices rank before stale prices, then oldest coverage and ticker.
Optional ``provider_unavailable`` contains explicit US provider codes whose
current, identity-matched receipts establish unavailable symbols or coverage.
The caller owns that evidence and its validity window; empty responses, rate
limits, and network failures alone must not populate this collection.

Quota accepts the SDK payload (used, remaining, list[{'code': ...}]) or a mapping
with used, remaining, details. Unknown or inconsistent quota routes everything
to ALTERNATE. The caller must recheck live quota when executing this advisory
plan: another process can consume slots after its snapshot. No local week/date
is used to infer a provider reset.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from numbers import Integral
from typing import Any


def _date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"INVALID_{field}:{value}")
    date.fromisoformat(value)
    return value


def _integer(value: Any, field: str, *, allow_string: bool = False) -> int:
    if allow_string and isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"INVALID_{field}")
    return int(value)


def _ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,31}", ticker):
        raise ValueError(f"INVALID_TICKER:{ticker}")
    return ticker


def _universe(rows: Iterable[Mapping[str, Any]]) -> dict[str, str | None]:
    """Validate caller-owned rows using load_universe's US symbol contract."""
    result: dict[str, str | None] = {}
    code_owners: dict[str, str] = {}
    for row in rows:
        ticker = _ticker(row.get("ticker"))
        code = str(row.get("moomoo_code") or row.get("moomoo_symbol") or "").strip().upper()
        if not code:
            code = "US." + ticker if re.fullmatch(r"[A-Z0-9]+", ticker) else None
        if code is not None and not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._-]{0,39}", code):
            raise ValueError(f"INVALID_US_MOOMOO_CODE:{code}")
        if ticker in result and result[ticker] is not None and code is not None and result[ticker] != code:
            raise ValueError(f"CONFLICTING_TICKER_MAPPING:{ticker}")
        if code is not None and code in code_owners and code_owners[code] != ticker:
            raise ValueError(f"AMBIGUOUS_PROVIDER_MAPPING:{code}")
        result[ticker] = code or result.get(ticker)
        if code is not None:
            code_owners[code] = ticker
    return result


def normalize_history_quota(payload: Any) -> dict[str, Any]:
    """Validate complete live details; do not mistake remaining for total limit."""
    try:
        if isinstance(payload, Mapping):
            used, remaining, details = payload["used"], payload["remaining"], payload["details"]
        elif isinstance(payload, (tuple, list)) and len(payload) == 3:
            used, remaining, details = payload
        else:
            raise ValueError("QUOTA_MISSING_OR_UNRECOGNIZED")
        used = _integer(used, "QUOTA_USED")
        remaining = _integer(remaining, "QUOTA_REMAINING")
        if not isinstance(details, list):
            raise ValueError("INVALID_QUOTA_DETAILS")
        known: set[str] = set()
        for row in details:
            if not isinstance(row, Mapping):
                raise ValueError("INVALID_QUOTA_DETAIL_ROW")
            code = row.get("code")
            # Slots in other markets also consume the provider's total quota.
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2}\.[A-Z0-9][A-Z0-9._-]{0,63}", code):
                raise ValueError("INVALID_QUOTA_DETAIL_CODE")
            if code in known:
                raise ValueError("DUPLICATE_QUOTA_DETAIL_CODE")
            known.add(code)
        if len(known) != used:
            raise ValueError("QUOTA_USED_DETAIL_MISMATCH")
        return {"status": "VALID", "used": used, "remaining": remaining,
                "known_codes": sorted(known), "provider_total": used + remaining,
                "reason": "LIVE_PROVIDER_SNAPSHOT"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"status": "UNKNOWN", "used": None, "remaining": None,
                "known_codes": [], "provider_total": None, "reason": str(exc)}


def build_top20_quota_plan(
    records: Iterable[Mapping[str, Any]],
    quota: Any,
    *,
    as_of_date: str,
    trading_dates: Iterable[str] | None = None,
    universe: Iterable[Mapping[str, Any]] | None = None,
    bootstrap_records: Iterable[Mapping[str, Any]] | None = None,
    pool_supplement: Iterable[Mapping[str, Any]] | None = None,
    provider_unavailable: Iterable[str] | None = None,
    lookback_sessions: int = 60,
    max_moomoo_symbols: int = 300,
) -> dict[str, Any]:
    """Return ranked priority_pool and per-symbol MOOMOO/ALTERNATE assignments.

    ``universe`` can include further requested symbols: those without recent
    Top40 membership are ALTERNATE unless their provider slot is already used
    or they appear in the caller's explicit stale/missing ``pool_supplement``.
    Supplement tickers must also be present in the explicit universe; that
    universe supplies their provider mappings. Never invent symbols. ``used``
    includes all provider slots, even those outside that pool; reusable symbols
    in the pool need no new slot. A user cap above 300 is rejected.
    """
    as_of_date = _date(as_of_date, "AS_OF_DATE")
    lookback_sessions = _integer(lookback_sessions, "LOOKBACK_SESSIONS")
    max_moomoo_symbols = _integer(max_moomoo_symbols, "MAX_MOOMOO_SYMBOLS")
    if lookback_sessions < 1 or not 1 <= max_moomoo_symbols <= 300:
        raise ValueError("INVALID_LOOKBACK_OR_MOOMOO_CAP")
    if isinstance(provider_unavailable, (str, bytes)):
        raise ValueError("PROVIDER_UNAVAILABLE_REQUIRES_CODE_COLLECTION")
    unavailable_codes = set()
    for code in provider_unavailable or []:
        if not isinstance(code, str) or not re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._-]{0,39}", code):
            raise ValueError("PROVIDER_UNAVAILABLE_REQUIRES_EXPLICIT_US_CODE")
        unavailable_codes.add(code)
    daily: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    bootstrap: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    identities: set[tuple[str, str]] = set()
    counts = {"input_records": 0, "bootstrap_input_records": 0, "excluded_record_kind": 0,
              "excluded_future_records": 0, "excluded_rank_records": 0,
              "excluded_outside_window_records": 0, "replaced_bootstrap_records": 0}
    calendar = None if trading_dates is None else {_date(day, "TRADING_DATE") for day in trading_dates}
    for source_records, kind, destination, count_key in (
        (records, "daily_recommendation", daily, "input_records"),
        (bootstrap_records or [], "historical_replay", bootstrap, "bootstrap_input_records"),
    ):
        for row in source_records:
            counts[count_key] += 1
            if row.get("record_kind") != kind:
                counts["excluded_record_kind"] += 1
                continue
            if kind == "historical_replay":
                identity = (row.get("model_id"), row.get("source_id"))
                if not all(isinstance(value, str) and value.strip() for value in identity):
                    raise ValueError("BOOTSTRAP_MODEL_AND_SOURCE_ID_REQUIRED")
                identities.add(identity)
            day = _date(row.get("date"), "RECORD_DATE")
            if day > as_of_date:
                counts["excluded_future_records"] += 1
                continue
            if calendar is not None and day not in calendar:
                raise ValueError(f"RESULT_DATE_NOT_IN_SUPPLIED_TRADING_DATES:{day}")
            rank = _integer(row.get("rank"), "RECORD_RANK", allow_string=True)
            if not 1 <= rank <= 40:
                counts["excluded_rank_records"] += 1
                continue
            destination[day].append({**row, "ticker": _ticker(row.get("ticker")), "rank": rank})
    if len(identities) > 1:
        raise ValueError("MIXED_BOOTSTRAP_MODEL_OR_SOURCE")
    combined = {**bootstrap, **daily}
    counts["replaced_bootstrap_records"] = sum(len(bootstrap[day]) for day in daily if day in bootstrap)
    dates = sorted(combined)[-lookback_sessions:]
    window_basis = "LATEST_RELIABLE_RESULT_DATES"
    window = set(dates)
    top20: dict[str, set[str]] = defaultdict(set)
    top40: dict[str, set[str]] = defaultdict(set)
    candidate_mappings: list[Mapping[str, Any]] = []
    counted_records = 0
    for day, rows in combined.items():
        if day not in window:
            counts["excluded_outside_window_records"] += len(rows)
            continue
        for row in rows:
            counted_records += 1
            ticker = row["ticker"]
            top40[ticker].add(day)
            if row["rank"] <= 20:
                top20[ticker].add(day)
            candidate_mappings.append(row)
    bootstrap_dates = sorted(day for day in dates if day in bootstrap and day not in daily)
    universe_rows = list(universe or [])
    supplied_tickers = {_ticker(row.get("ticker")) for row in universe_rows}
    pool_dates: dict[str, str | None] = {}
    for row in pool_supplement or []:
        ticker = _ticker(row.get("ticker"))
        if ticker not in supplied_tickers:
            raise ValueError(f"POOL_SUPPLEMENT_NOT_IN_UNIVERSE:{ticker}")
        if "last_price_date" not in row:
            raise ValueError(f"POOL_LAST_PRICE_DATE_REQUIRED:{ticker}")
        latest = row["last_price_date"]
        if latest is not None:
            latest = _date(latest, "POOL_LAST_PRICE_DATE")
        if ticker in pool_dates and pool_dates[ticker] != latest:
            raise ValueError(f"CONFLICTING_POOL_PRICE_COVERAGE:{ticker}")
        pool_dates[ticker] = latest
    # Explicit universe mapping has authority; any explicit conflicting history
    # mapping is still validated instead of silently choosing a provider code.
    for row in candidate_mappings:
        if row["date"] not in window:
            continue
        if row["ticker"] not in supplied_tickers or row.get("moomoo_code") or row.get("moomoo_symbol"):
            universe_rows.append(row)
    symbols = _universe(universe_rows)
    def order(ticker, appearances):
        return (-len(appearances[ticker]), -date.fromisoformat(max(appearances[ticker])).toordinal(), ticker)

    top20_ranking = sorted(top20, key=lambda ticker: order(ticker, top20))
    top40_ranking = sorted(set(top40) - set(top20), key=lambda ticker: order(ticker, top40))
    pool_ranking = sorted(
        (ticker for ticker, latest in pool_dates.items()
         if ticker not in top40 and (latest is None or latest < as_of_date)),
        key=lambda ticker: (pool_dates[ticker] is not None, pool_dates[ticker] or "", ticker),
    )
    ranking = top20_ranking + top40_ranking + pool_ranking
    ranking_positions = {ticker: index + 1 for index, ticker in enumerate(ranking)}
    # When filling the quota from an explicitly authorized full pool, symbols
    # without transport mappings cannot occupy one of its usable positions.
    eligible_ranking = [ticker for ticker in ranking
                        if symbols[ticker] not in unavailable_codes
                        and (pool_supplement is None or symbols[ticker] is not None)]
    priority_ranking = eligible_ranking[:max_moomoo_symbols]
    priority = set(priority_ranking)
    quota_info = normalize_history_quota(quota)
    known = set(quota_info["known_codes"])
    budget = 0
    if quota_info["status"] == "VALID":
        budget = min(quota_info["remaining"], max(0, max_moomoo_symbols - quota_info["used"]))
    starting_budget = budget
    ordered_symbols = ranking + sorted(set(symbols) - set(ranking))
    assignments = []
    reused = 0
    for ticker in ordered_symbols:
        code = symbols[ticker]
        provider, reason, consumes_slot = "ALTERNATE", "OUTSIDE_PRIORITY_POOL", False
        if ticker in pool_dates and pool_dates[ticker] is not None and pool_dates[ticker] >= as_of_date:
            reason = "POOL_PRICE_COVERAGE_ALREADY_CURRENT"
        if code is None:
            reason = "EXPLICIT_PROVIDER_MAPPING_REQUIRED"
        elif code in unavailable_codes:
            # An already charged unavailable code still counts in live `used`;
            # skipping its request does not refund a provider slot.
            reason = "PROVIDER_UNAVAILABLE_IN_CALLER_EVIDENCE"
        elif quota_info["status"] == "VALID" and code in known:
            provider = "MOOMOO"
            reason = "ALREADY_COUNTED_PROVIDER_SYMBOL" if ticker in priority else "ALREADY_COUNTED_PROVIDER_SYMBOL_OUTSIDE_PRIORITY_POOL"
            reused += 1
        elif ticker in priority:
            if quota_info["status"] != "VALID":
                reason = "QUOTA_UNKNOWN_OR_INCONSISTENT"
            elif budget:
                provider, reason, consumes_slot = "MOOMOO", "PRIORITY_POOL_NEW_PROVIDER_SYMBOL", True
                if ticker not in top40:
                    reason = "POOL_REFRESH_NEW_PROVIDER_SYMBOL"
                budget -= 1
            else:
                reason = "PROVIDER_REMAINING_OR_USER_CAP_EXHAUSTED"
        appearances = top20 if ticker in top20 else top40
        assignments.append({"ticker": ticker, "moomoo_symbol": code,
                            "frequency_days": len(appearances.get(ticker, ())),
                            "top20_frequency_days": len(top20.get(ticker, ())),
                            "top40_frequency_days": len(top40.get(ticker, ())),
                            "priority_tier": "TOP20" if ticker in top20 else "TOP40" if ticker in top40 else "POOL_REFRESH" if ticker in pool_ranking else None,
                            "last_seen_date": max(appearances[ticker]) if ticker in appearances else None,
                            "pool_last_price_date": pool_dates.get(ticker),
                            "in_explicit_refresh_pool": ticker in pool_dates,
                            "priority_rank": ranking_positions.get(ticker),
                            "in_priority_pool": ticker in priority, "provider": provider,
                            "reason": reason, "consumes_new_slot": consumes_slot})
    unique_days = sum(len(days) for days in top40.values())
    counts.update({"window_sessions": len(dates), "ranked_symbols": len(ranking),
                   "priority_pool_symbols": len(priority), "requested_symbols": len(assignments),
                   "counted_unique_ticker_days": unique_days,
                   "deduplicated_same_day_records": counted_records - unique_days,
                   "moomoo_symbols": sum(row["provider"] == "MOOMOO" for row in assignments),
                   "alternate_symbols": sum(row["provider"] == "ALTERNATE" for row in assignments),
                   "reused_provider_symbols": reused, "planned_new_provider_symbols": starting_budget - budget,
                   "provider_unavailable_symbols": sum(row["moomoo_symbol"] in unavailable_codes for row in assignments),
                   "priority_excluded_provider_unavailable_symbols": sum(symbols[ticker] in unavailable_codes for ticker in ranking),
                   "new_symbol_budget_before": starting_budget, "new_symbol_budget_after": budget,
                   "top20_unique_symbols": len(top20),
                   "top40_additional_unique_symbols": len(top40_ranking),
                   "priority_top40_symbols": len(priority & set(top40_ranking)),
                   "pool_supplement_symbols": len(pool_dates),
                   "pool_refresh_additional_symbols": len(pool_ranking),
                   "pool_current_symbols": sum(latest is not None and latest >= as_of_date for latest in pool_dates.values()),
                   "priority_pool_refresh_symbols": len(priority & set(pool_ranking)),
                   "pool_refresh_new_provider_symbols": sum(row["consumes_new_slot"] and row["priority_tier"] == "POOL_REFRESH" for row in assignments),
                   "bootstrap_sessions": len(bootstrap_dates), "daily_sessions": len(dates) - len(bootstrap_dates)})
    return {"schema_version": 1, "as_of_date": as_of_date,
            "lookback_sessions": lookback_sessions, "max_moomoo_symbols": max_moomoo_symbols,
            "window_basis": window_basis, "window_dates": dates,
            "window_start": dates[0] if dates else None, "window_end": dates[-1] if dates else None,
            "history_date_start": dates[0] if dates else None, "history_date_end": dates[-1] if dates else None,
            "bootstrap_used": bool(bootstrap_dates), "bootstrap_dates": bootstrap_dates,
            "bootstrap_identity": {"model_id": next(iter(identities))[0], "source_id": next(iter(identities))[1]} if identities else None,
            "result_dates_calendar_validated": calendar is not None,
            "pool_supplement_authorized": pool_supplement is not None,
            "provider_unavailable_codes": sorted(unavailable_codes),
            "quota": quota_info, "priority_pool": priority_ranking,
            "assignments": assignments, "counts": counts,
            "execution_requires_fresh_quota_check": True}
