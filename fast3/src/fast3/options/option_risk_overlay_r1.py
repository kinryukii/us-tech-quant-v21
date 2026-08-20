"""Outcome-blind, PIT-safe primitives for FAST3 Option Risk Overlay R1.

This module deliberately contains no alpha target, model, fitting, scoring, or
economic rule.  It only expresses the immutable data-timing and risk-action
contract that R1 audits and freezes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from typing import Iterable, Sequence


RISK_ACTION_MULTIPLIERS = {"NORMAL": 1.00, "REDUCED": 0.50, "VETO": 0.00}
ALLOWED_DIRECTIONS = frozenset({"UP", "DOWN"})
MAX_OPTION_SNAPSHOT_STALENESS = timedelta(minutes=5)
PERCENTILE_MIN_HISTORY = 60
PERCENTILE_MAX_HISTORY = 252


@dataclass(frozen=True)
class ConstantMaturityPoint:
    """An IV point already delta/ATM-normalized within one complete snapshot."""

    days_to_expiry: int
    implied_volatility: float


def assert_pit_quote(snapshot_completed_at: datetime, decision_at: datetime) -> None:
    """Reject a future or stale option snapshot; timestamps must be UTC-aware."""
    if snapshot_completed_at.tzinfo is None or decision_at.tzinfo is None:
        raise ValueError("option timestamps must be timezone-aware")
    if snapshot_completed_at > decision_at:
        raise ValueError("future option quote is prohibited")
    if decision_at - snapshot_completed_at > MAX_OPTION_SNAPSHOT_STALENESS:
        raise ValueError("option snapshot exceeds frozen maximum staleness")


def assert_previous_completed_day_oi(oi_as_of_date: date, decision_at: datetime) -> None:
    """Open interest, if ever used, must be known from a prior trading day."""
    if oi_as_of_date >= decision_at.date():
        raise ValueError("same-day final open interest is prohibited")


def constant_maturity_iv(points: Sequence[ConstantMaturityPoint], target_days: int) -> float:
    """Deterministically interpolate IV in total-variance space.

    The input must contain points from one legal, completed option snapshot.  A
    target that is not bracketed is unavailable rather than extrapolated.
    """
    if target_days <= 0:
        raise ValueError("target_days must be positive")
    unique = {point.days_to_expiry: point.implied_volatility for point in points}
    if target_days in unique:
        return float(unique[target_days])
    lower = [day for day in unique if day < target_days]
    upper = [day for day in unique if day > target_days]
    if not lower or not upper:
        raise ValueError("constant maturity target is not bracketed; no extrapolation")
    d1, d2 = max(lower), min(upper)
    v1, v2 = unique[d1], unique[d2]
    if min(v1, v2) <= 0:
        raise ValueError("implied volatility must be positive")
    total_variance_1 = v1 * v1 * d1
    total_variance_2 = v2 * v2 * d2
    weight = (target_days - d1) / (d2 - d1)
    return sqrt(((1.0 - weight) * total_variance_1 + weight * total_variance_2) / target_days)


def expanding_percentile(history: Iterable[tuple[datetime, float]], decision_at: datetime, value: float) -> float | None:
    """Return a historical-only empirical percentile, or None when immature."""
    past = [item_value for timestamp, item_value in history if timestamp < decision_at]
    past = past[-PERCENTILE_MAX_HISTORY:]
    if len(past) < PERCENTILE_MIN_HISTORY:
        return None
    return sum(item_value <= value for item_value in past) / len(past)


def overlay_action(fast3_direction: str, risk_action: str | None) -> dict[str, object]:
    """Apply a risk-only action without ever generating/reversing a FAST3 trade."""
    if fast3_direction not in ALLOWED_DIRECTIONS:
        raise ValueError("FAST3 direction must be UP or DOWN")
    if risk_action is None:
        return {
            "option_state": "UNAVAILABLE",
            "option_overlay_action": "NO_OPTION_OVERRIDE",
            "position_multiplier": 1.00,
            "fast3_direction": fast3_direction,
            "effective_direction": fast3_direction,
            "directional_label": f"{fast3_direction}_NORMAL",
        }
    if risk_action not in RISK_ACTION_MULTIPLIERS:
        raise ValueError("risk action must be NORMAL, REDUCED, or VETO")
    multiplier = RISK_ACTION_MULTIPLIERS[risk_action]
    return {
        "option_state": "AVAILABLE",
        "option_overlay_action": risk_action,
        "position_multiplier": multiplier,
        "fast3_direction": fast3_direction,
        "effective_direction": fast3_direction,
        "directional_label": f"{fast3_direction}_{risk_action}",
    }


def validate_overlay_result(result: dict[str, object]) -> None:
    """Fail closed on any direction flip or impermissible position multiplier."""
    if result["effective_direction"] != result["fast3_direction"]:
        raise ValueError("option overlay direction flip is prohibited")
    if result["position_multiplier"] not in set(RISK_ACTION_MULTIPLIERS.values()):
        raise ValueError("position multiplier is outside the frozen action set")
