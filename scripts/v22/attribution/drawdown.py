"""Deterministic drawdown-window diagnostics, explicitly non-causal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .schemas import AttributionConfig


def detect_drawdown_episodes(daily: pd.DataFrame) -> list[dict[str, Any]]:
    """Detect strict recovery episodes: recovery requires NAV > prior peak."""
    if "nav_after" not in daily or daily.nav_after.isna().all():
        return []
    nav = daily.loc[daily.nav_after.notna(), ["date", "nav_after"]].sort_values("date", kind="mergesort")
    if nav.empty:
        return []
    peak_date = pd.Timestamp(nav.iloc[0].date)
    peak_nav = float(nav.iloc[0].nav_after)
    active: dict[str, Any] | None = None
    episodes: list[dict[str, Any]] = []
    for observation, row in enumerate(nav.itertuples(index=False), start=0):
        current_date, current_nav = pd.Timestamp(row.date), float(row.nav_after)
        if current_nav > peak_nav:
            if active is not None:
                active["recovery_date"] = current_date.date().isoformat()
                active["recovered"] = True
                active["recovery_observation"] = observation
                active["duration_observations_to_recovery"] = observation - active["peak_observation"]
                episodes.append(active)
                active = None
            peak_date, peak_nav = current_date, current_nav
            continue
        if current_nav < peak_nav:
            drawdown = current_nav / peak_nav - 1.0
            if active is None:
                active = {
                    "peak_date": peak_date.date().isoformat(), "peak_nav": peak_nav,
                    "trough_date": current_date.date().isoformat(), "trough_nav": current_nav,
                    "drawdown_magnitude": drawdown, "peak_observation": observation - 1,
                    "trough_observation": observation, "recovery_date": None, "recovered": False,
                    "recovery_observation": None, "duration_observations_to_trough": 1,
                    "duration_observations_to_recovery": None,
                }
            elif drawdown < active["drawdown_magnitude"]:
                active["trough_date"] = current_date.date().isoformat()
                active["trough_nav"] = current_nav
                active["drawdown_magnitude"] = drawdown
                active["trough_observation"] = observation
                active["duration_observations_to_trough"] = observation - active["peak_observation"]
    if active is not None:
        episodes.append(active)
    return episodes


def _aggregate(window: pd.DataFrame, dimension: str) -> pd.DataFrame:
    if window.empty:
        return pd.DataFrame(columns=[dimension, "gross_contribution", "cost_contribution", "net_contribution"])
    frame = window.copy()
    frame[dimension] = frame[dimension].fillna("UNKNOWN").astype(str)
    return frame.groupby(dimension, as_index=False, dropna=False).agg(
        gross_contribution=("gross_contribution", lambda values: float(values.sum(min_count=1))),
        cost_contribution=("cost_contribution", lambda values: float(values.sum(min_count=1))),
        net_contribution=("net_contribution", "sum"),
    ).sort_values(["net_contribution", dimension], kind="mergesort").reset_index(drop=True)


def drawdown_window_diagnostics(
    rows: pd.DataFrame, episodes: list[dict[str, Any]], config: "AttributionConfig",
) -> list[dict[str, Any]]:
    diagnostics = []
    for index, episode in enumerate(episodes, start=1):
        peak, trough = pd.Timestamp(episode["peak_date"]), pd.Timestamp(episode["trough_date"])
        window = rows.loc[(rows.date > peak) & (rows.date <= trough)].copy()
        security_window = window.loc[window.component_type.eq("SECURITY")]
        diagnostics.append({
            "episode_id": f"DRAWDOWN_{index}",
            "definition": "REALIZED_CONTRIBUTION_DURING_PEAK_EXCLUSIVE_TROUGH_INCLUSIVE_WINDOW_NOT_CAUSAL",
            "episode": episode,
            "window_total_net_contribution": float(window.net_contribution.sum()),
            "security": _aggregate(security_window, "security_id"),
            "sector": _aggregate(window, "sector"),
            "rank_bucket": _aggregate(window, "rank_bucket"),
            "identity_status": "PASS" if abs(float(window.net_contribution.sum()) - sum(
                float(item) for item in window.groupby("date").net_contribution.sum()
            )) <= config.identity_tolerance else "FAIL",
        })
    return diagnostics
