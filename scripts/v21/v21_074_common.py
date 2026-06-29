"""Shared PIT entry scoring and policy helpers for V21.074."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import (
    OUT_REL as V73_OUT_REL, SOURCE_REL, VARIANT_MAP, WINDOWS,
    add_d_variant, load_source_panel, protected_files, sha256,
    size_multiplier, truth,
)


OUT_REL = Path("outputs/v21/v21_074")
SIM_REL = V73_OUT_REL / "V21_073_R3_CAUSAL_EXIT_SIMULATION.csv"
PATH_AUDIT_REL = V73_OUT_REL / "V21_073_R2_VALIDATION_SUMMARY.csv"
GRID_REL = Path("outputs/v21/v21_072/V21_072_R1_JOINT_POLICY_GRID.csv")
V73_VALIDATION_REL = V73_OUT_REL / "V21_073_R4_VALIDATION_SUMMARY.csv"
SELECTION_MAP = {
    **VARIANT_MAP,
    "D_WEIGHT_OPTIMIZED_R1": "DERIVED_D_WEIGHT_OPTIMIZED_R1",
}
ENTRY_VARIANTS = {
    "ENTRY_HYBRID_STRICT_R1": 80,
    "ENTRY_HYBRID_BALANCED_R1": 75,
    "ENTRY_HYBRID_RELAXED_R1": 70,
    "ENTRY_HYBRID_MOMENTUM_RELAXED_R1": 70,
    "ENTRY_HYBRID_SOFT_BLOCK_R1": 70,
}
EXIT_POLICIES = (
    "EXIT_FAST_RISK_CONTROL_R1",
    "EXIT_TREND_HOLD_R1",
    "EXIT_PROFIT_PROTECT_R1",
)


def entry_components(frame: pd.DataFrame) -> pd.DataFrame:
    rank = pd.to_numeric(frame["rank"], errors="coerce")
    momentum = pd.to_numeric(frame["momentum_score"], errors="coerce")
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    chase = frame["chase_permission"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    quality = frame["price_data_status"].fillna("").astype(str).str.upper()
    ranking = ((51 - rank.clip(1, 50)) / 50 * 25).clip(0, 25)
    trend = pd.Series(5.0, index=frame.index)
    trend = trend.mask(state.str.contains("LEADER|ACCELERATING"), 20)
    trend = trend.mask(state.str.contains("PULLBACK"), 16)
    pattern = pd.Series(5.0, index=frame.index)
    pattern = pattern.mask(state.str.contains("PULLBACK"), 20)
    pattern = pattern.mask(state.str.contains("ACCELERATING"), 18)
    pattern = pattern.mask(state.str.contains("EXTENDED_BUT_VALID"), 12)
    oscillator = (momentum.rank(pct=True) * 15).fillna(0)
    volume_liquidity = pd.Series(5.0, index=frame.index)
    market = pd.Series(10.0, index=frame.index)
    market = market.mask(regime.str.contains("RISK_OFF"), 0)
    severe_overheat = (
        state.str.contains("EXHAUST|OVERHEAT")
        & chase.str.contains("HOLD_ONLY|DO_NOT_CHASE")
    )
    weak_trend = trend.lt(12)
    data_bad = ~quality.eq("PASS")
    breakout_chase = state.str.contains("FIRST_DAY_BREAKOUT")
    pullback_failed = state.str.contains("PULLBACK") & ~chase.str.contains(
        "PRIORITY|ALLOW"
    )
    oscillator_failed = oscillator.lt(7.5)
    volume_failed = state.str.contains("NO_MOMENTUM")
    trend_failed = weak_trend
    market_block = regime.str.contains("RISK_OFF") & weak_trend
    score = ranking + trend + pattern + oscillator + volume_liquidity + market
    return pd.DataFrame({
        "entry_score": score, "ranking_strength_score": ranking,
        "trend_confirmation_score": trend,
        "entry_pattern_quality_score": pattern,
        "oscillator_confirmation_score": oscillator,
        "volume_liquidity_score": volume_liquidity,
        "market_regime_score": market,
        "data_quality_block": data_bad,
        "severe_overheat_block": severe_overheat,
        "market_regime_block": market_block,
        "breakout_chase_block": breakout_chase,
        "pullback_confirmation_failed": pullback_failed,
        "oscillator_confirmation_failed": oscillator_failed,
        "volume_confirmation_failed": volume_failed,
        "trend_confirmation_failed": trend_failed,
    }, index=frame.index)


def primary_block_reason(
    frame: pd.DataFrame, components: pd.DataFrame, threshold: float
) -> pd.Series:
    reason = pd.Series("", index=frame.index, dtype="object")
    ordered = (
        ("data_quality_block", "data_quality_block"),
        ("severe_overheat_block", "overheat_block"),
        ("market_regime_block", "market_regime_block"),
        ("breakout_chase_block", "breakout_chase_block"),
        ("pullback_confirmation_failed", "pullback_confirmation_failed"),
        ("oscillator_confirmation_failed", "oscillator_confirmation_failed"),
        ("volume_confirmation_failed", "volume_confirmation_failed"),
        ("trend_confirmation_failed", "trend_confirmation_failed"),
    )
    for column, label in ordered:
        reason = reason.mask(reason.eq("") & components[column], label)
    reason = reason.mask(
        reason.eq("") & components["entry_score"].lt(threshold),
        "entry_score_below_threshold",
    )
    return reason.mask(reason.eq(""), "other")


def evaluate_entry_variant(
    frame: pd.DataFrame, policy: str, selection_policy: str
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    components = entry_components(frame)
    threshold = ENTRY_VARIANTS[policy]
    reason = primary_block_reason(frame, components, threshold)
    hard_block = (
        components["data_quality_block"]
        | components["severe_overheat_block"]
        | components["market_regime_block"]
    )
    score = components["entry_score"].copy()
    if policy == "ENTRY_HYBRID_SOFT_BLOCK_R1":
        penalties = (
            components["breakout_chase_block"].astype(int) * 5
            + components["pullback_confirmation_failed"].astype(int) * 5
            + components["oscillator_confirmation_failed"].astype(int) * 4
            + components["volume_confirmation_failed"].astype(int) * 3
            + components["trend_confirmation_failed"].astype(int) * 5
        )
        score = score - penalties
        allowed = score.ge(threshold) & ~hard_block
    elif policy == "ENTRY_HYBRID_MOMENTUM_RELAXED_R1":
        relaxed = (
            selection_policy in {"D_WEIGHT_OPTIMIZED_R1", "C_DYNAMIC_MOMENTUM"}
            and True
        )
        relaxed_mask = (
            pd.to_numeric(frame["rank"], errors="coerce").le(20)
            & ~frame["market_regime"].fillna("").astype(str).str.upper().str.contains(
                "RISK_OFF"
            )
            & components["trend_confirmation_score"].ge(12)
            & score.ge(65)
        )
        allowed = (score.ge(threshold) | (relaxed_mask if relaxed else False)) & ~hard_block
    else:
        allowed = score.ge(threshold) & ~hard_block
    reason = reason.mask(allowed, "")
    components["effective_entry_score"] = score
    return allowed, reason, components


def load_panel_with_d(root: Path) -> pd.DataFrame:
    return add_d_variant(load_source_panel(root / SOURCE_REL))


def load_simulations(root: Path) -> pd.DataFrame:
    return pd.read_csv(root / SIM_REL, low_memory=False)
