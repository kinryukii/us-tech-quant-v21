"""Shared helpers for V21.075 ranking-only portfolio sizing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from v21_073_common import (
    OUT_REL as V73_OUT_REL, PRICE_REL, SOURCE_REL, add_d_variant,
    load_source_panel, protected_files, sha256, truth,
)


OUT_REL = Path("outputs/v21/v21_075")
PATH_REL = V73_OUT_REL / "V21_073_R1_PIT_DAILY_PRICE_PATH_PANEL.csv"
PATH_AUDIT_REL = V73_OUT_REL / "V21_073_R2_VALIDATION_SUMMARY.csv"
V74_VALIDATION_REL = Path("outputs/v21/v21_074/V21_074_R4_VALIDATION_SUMMARY.csv")
SELECTIONS = {
    "D_WEIGHT_OPTIMIZED_R1": "DERIVED_D_WEIGHT_OPTIMIZED_R1",
    "C_DYNAMIC_MOMENTUM": "C_MOMENTUM_DYNAMIC_R1",
}
POLICIES = (
    ("EW_TOP20_R1", "EQUAL_WEIGHT", 20),
    ("EW_TOP50_R1", "EQUAL_WEIGHT", 50),
    ("RANK_WEIGHTED_TOP20_R1", "RANK_WEIGHTED", 20),
    ("RANK_WEIGHTED_TOP50_R1", "RANK_WEIGHTED", 50),
    ("SCORE_WEIGHTED_TOP20_R1", "SCORE_WEIGHTED", 20),
    ("SCORE_WEIGHTED_TOP50_R1", "SCORE_WEIGHTED", 50),
    ("VOL_ADJUSTED_TOP20_R1", "VOL_ADJUSTED", 20),
    ("VOL_ADJUSTED_TOP50_R1", "VOL_ADJUSTED", 50),
    ("HYBRID_RISK_BUDGET_TOP20_R1", "HYBRID_RISK_BUDGET", 20),
    ("HYBRID_RISK_BUDGET_TOP50_R1", "HYBRID_RISK_BUDGET", 50),
)


def load_panel(root: Path) -> pd.DataFrame:
    return add_d_variant(load_source_panel(root / SOURCE_REL))


def risk_proxy(frame: pd.DataFrame) -> pd.Series:
    bucket = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    result = pd.Series(1.0, index=frame.index)
    result = result.mask(bucket.str.contains("HALF"), 1.5)
    result = result.mask(bucket.str.contains("QUARTER|WATCH"), 2.0)
    return result.clip(lower=0.75, upper=2.0)


def capped_normalize(
    raw: pd.Series, cap: float, floor: float
) -> pd.Series:
    raw = pd.to_numeric(raw, errors="coerce").fillna(0).clip(lower=0)
    if raw.sum() <= 0:
        raw = pd.Series(1.0, index=raw.index)
    weight = pd.Series(floor, index=raw.index, dtype=float)
    capacity = pd.Series(cap - floor, index=raw.index, dtype=float)
    remaining = 1.0 - float(weight.sum())
    active = capacity.gt(1e-15)
    for _ in range(len(raw) + 2):
        if remaining <= 1e-14 or not active.any():
            break
        active_raw = raw[active]
        proposal = (
            pd.Series(remaining / active.sum(), index=active_raw.index)
            if active_raw.sum() <= 0
            else active_raw / active_raw.sum() * remaining
        )
        saturated = proposal >= capacity[active]
        if saturated.any():
            indexes = proposal.index[saturated]
            weight.loc[indexes] += capacity.loc[indexes]
            remaining -= float(capacity.loc[indexes].sum())
            capacity.loc[indexes] = 0
            active.loc[indexes] = False
        else:
            weight.loc[proposal.index] += proposal
            remaining = 0
    return weight / weight.sum()


def policy_weights(frame: pd.DataFrame, method: str, top_n: int) -> pd.Series:
    rank = pd.to_numeric(frame["rank"], errors="coerce")
    score = pd.to_numeric(frame["score"], errors="coerce")
    score_norm = (score - score.min()).clip(lower=0) + 1e-6
    cap = 0.10 if top_n == 20 else 0.05
    floor = 0.01 if top_n == 20 else 0.005
    if method == "EQUAL_WEIGHT":
        return pd.Series(1 / len(frame), index=frame.index)
    if method == "RANK_WEIGHTED":
        raw = top_n + 1 - rank
    elif method == "SCORE_WEIGHTED":
        raw = score_norm
    elif method == "VOL_ADJUSTED":
        raw = score_norm / risk_proxy(frame)
    else:
        rank_strength = (top_n + 1 - rank).clip(lower=1)
        data_penalty = frame["price_data_status"].map(
            lambda value: 1.0 if str(value).upper() == "PASS" else 0.5
        )
        raw = rank_strength * score_norm / risk_proxy(frame) * data_penalty
    return capped_normalize(raw, cap, floor)


def path_features(root: Path) -> pd.DataFrame:
    paths = pd.read_csv(root / PATH_REL, low_memory=False)
    paths["open"] = pd.to_numeric(paths["open"], errors="coerce")
    paths["high"] = pd.to_numeric(paths["high"], errors="coerce")
    paths["low"] = pd.to_numeric(paths["low"], errors="coerce")
    rows = []
    for observation_id, group in paths.groupby("observation_id", sort=False):
        group = group.sort_values("forward_day_index")
        entry = group.iloc[0]["open"]
        for window in (5, 10, 20):
            selected = group.head(window)
            rows.append({
                "observation_id": observation_id,
                "sampled_as_of_date": selected.iloc[0]["as_of_date"],
                "ticker": selected.iloc[0]["ticker"],
                "forward_window": f"{window}D",
                "max_adverse_excursion": selected["low"].min() / entry - 1,
                "max_favorable_excursion": selected["high"].max() / entry - 1,
                "path_coverage": len(selected) >= window,
            })
    return pd.DataFrame(rows)
