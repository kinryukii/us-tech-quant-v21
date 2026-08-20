"""Pure helpers for the FAST3 5-minute Moomoo option-shadow data stream.

No SDK import, model, trade context, alpha score, position change, or overlay
decision exists here.  This module only validates/materializes data already
returned by a read-only quote client.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isnan
from typing import Any, Iterable


CANONICAL_RESOLUTION_MINUTES = 5
ALLOWED_MULTIPLIERS = frozenset({0.0, 0.5, 1.0})


def canonical_slot(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        raise ValueError("snapshot timestamp must be timezone-aware")
    minute = timestamp.minute - (timestamp.minute % CANONICAL_RESOLUTION_MINUTES)
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def is_valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and not isnan(float(value))


def quote_is_stale(source_timestamp: datetime | None, materialized_timestamp: datetime, max_staleness_seconds: int) -> bool:
    if source_timestamp is None or source_timestamp.tzinfo is None:
        return True
    if source_timestamp > materialized_timestamp:
        return True
    return (materialized_timestamp - source_timestamp).total_seconds() > max_staleness_seconds


def choose_expiry(expiries: Iterable[dict[str, Any]], target_dte: int) -> dict[str, Any] | None:
    legal = [item for item in expiries if is_valid_number(item.get("dte")) and item["dte"] >= 0]
    return min(legal, key=lambda item: (abs(item["dte"] - target_dte), item["dte"], str(item["expiry"]))) if legal else None


def choose_atm_contract(chain: Iterable[dict[str, Any]], expiry: str, call_put: str, spot: float) -> dict[str, Any] | None:
    legal = [item for item in chain if item.get("expiry") == expiry and item.get("call_put") == call_put and is_valid_number(item.get("strike"))]
    return min(legal, key=lambda item: (abs(float(item["strike"]) - spot), float(item["strike"]), str(item["option_code"]))) if legal else None


def choose_delta_filtered_put(chain: Iterable[dict[str, Any]], expiry: str, spot: float) -> dict[str, Any] | None:
    """Choose one contract from the server's -0.30..-0.20 delta-filtered chain."""
    puts = [item for item in chain if item.get("expiry") == expiry and item.get("call_put") == "PUT" and is_valid_number(item.get("strike"))]
    return min(puts, key=lambda item: (abs(float(item["strike"]) - spot * .94), float(item["strike"]), str(item["option_code"]))) if puts else None


def mean_available(values: Iterable[Any]) -> float | None:
    legal = [float(value) for value in values if is_valid_number(value)]
    return sum(legal) / len(legal) if legal else None


def materialize_surface(selected: list[dict[str, Any]]) -> dict[str, Any]:
    """Materialize only genuine returned IV/delta values; never synthesize them."""
    by_role = {item.get("role"): item for item in selected}
    mid_call, mid_put = by_role.get("mid_atm_call"), by_role.get("mid_atm_put")
    near_call, near_put = by_role.get("near_atm_call"), by_role.get("near_atm_put")
    atm_mid = mean_available([mid_call.get("implied_volatility") if mid_call else None, mid_put.get("implied_volatility") if mid_put else None])
    atm_near = mean_available([near_call.get("implied_volatility") if near_call else None, near_put.get("implied_volatility") if near_put else None])
    skew_put = by_role.get("mid_delta_filtered_put")
    skew_iv = skew_put.get("implied_volatility") if skew_put else None
    skew_delta = skew_put.get("delta") if skew_put else None
    skew = float(skew_iv) - atm_mid if atm_mid is not None and is_valid_number(skew_iv) and is_valid_number(skew_delta) else None
    return {
        "option_atm_iv_30d": atm_mid,
        "option_downside_skew_30d": skew,
        "option_iv_term_slope": float(atm_near) - atm_mid if atm_near is not None and atm_mid is not None else None,
        "option_25d_point_status": "AVAILABLE_SERVER_DELTA_FILTERED" if skew is not None else "UNAVAILABLE_NO_REAL_IV_OR_DELTA",
    }


def derive_changes(history: list[dict[str, Any]], field: str) -> dict[str, float | None]:
    """Use current minus exactly 1/2/3 completed canonical 5m observations."""
    if not history:
        return {"5m": None, "10m": None, "15m": None}
    current = history[-1].get(field)
    def change(intervals: int) -> float | None:
        if len(history) <= intervals or not is_valid_number(current):
            return None
        previous = history[-1 - intervals].get(field)
        return float(current) - float(previous) if is_valid_number(previous) else None
    return {"5m": change(1), "10m": change(2), "15m": change(3)}


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot["snapshot_timestamp_utc"] > snapshot["retrieved_at_utc"]:
        raise ValueError("future option quote is prohibited")
    if snapshot["position_multiplier_applied"] is not False:
        raise ValueError("shadow data logger cannot apply a position multiplier")
    if snapshot["fast3_signal_changed"] is not False:
        raise ValueError("shadow data logger cannot change FAST3")
    if snapshot["direction_reversal_allowed"] is not False:
        raise ValueError("direction reversal must remain prohibited")
