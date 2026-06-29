"""Shared helpers for V21.073 path-based policy research."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd


OUT_REL = Path("outputs/v21/v21_073")
SOURCE_REL = Path(
    "outputs/v21/experiments/momentum_dynamic/random_backtests/"
    "V21_060_R2_RANDOM_ASOF_BACKTEST_RESULTS.csv"
)
PRICE_REL = Path(
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
)
GRID_REL = Path("outputs/v21/v21_072/V21_072_R1_JOINT_POLICY_GRID.csv")
WINDOWS = ("5D", "10D", "20D")
VARIANT_MAP = {
    "A1_BASELINE": "A1_BASELINE_REPLAY_CURRENT",
    "B_STATIC_MOMENTUM": "B_MOMENTUM_STATIC_R1",
    "C_DYNAMIC_MOMENTUM": "C_MOMENTUM_DYNAMIC_R1",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def split_name(seed: pd.Series) -> pd.Series:
    bucket = pd.to_numeric(seed, errors="coerce").fillna(0).astype("int64").mod(10)
    return bucket.map(
        lambda value: "TRAIN" if value < 6 else "VALIDATION" if value < 8 else "TEST"
    )


def load_source_panel(path: Path) -> pd.DataFrame:
    columns = [
        "seed", "batch_id", "sampled_as_of_date", "variant_id", "ticker",
        "instrument_type", "theme",
        "rank", "score", "base_score", "momentum_score", "momentum_state",
        "chase_permission", "risk_size_bucket", "market_regime",
        "forward_window", "realized_forward_return", "benchmark_spy_return",
        "benchmark_qqq_return", "benchmark_smh_return", "top_n_bucket",
        "price_data_status", "point_in_time_valid", "research_only",
    ]
    chunks = []
    for chunk in pd.read_csv(path, usecols=columns, chunksize=250000, low_memory=False):
        keep = (
            chunk["forward_window"].astype(str).isin(WINDOWS)
            & chunk["top_n_bucket"].astype(str).eq("TOP50")
            & chunk["point_in_time_valid"].map(truth)
            & chunk["research_only"].map(truth)
            & chunk["price_data_status"].astype(str).eq("PASS")
        )
        chunks.append(chunk[keep].copy())
    panel = pd.concat(chunks, ignore_index=True)
    panel["sampled_as_of_date"] = panel["sampled_as_of_date"].astype(str).str[:10]
    panel["ticker"] = panel["ticker"].astype(str).str.upper().str.strip()
    panel["split"] = split_name(panel["seed"])
    return panel


def add_d_variant(panel: pd.DataFrame) -> pd.DataFrame:
    base = panel[panel["variant_id"] == "B_MOMENTUM_STATIC_R1"].copy()
    base["variant_id"] = "DERIVED_D_WEIGHT_OPTIMIZED_R1"
    base["score"] = (
        0.60 * pd.to_numeric(base["base_score"], errors="coerce")
        + 0.40 * pd.to_numeric(base["momentum_score"], errors="coerce")
    )
    base["rank"] = base.groupby(
        ["seed", "batch_id", "forward_window"]
    )["score"].rank(method="first", ascending=False)
    return pd.concat([panel, base], ignore_index=True)


def entry_allowed(frame: pd.DataFrame, policy: str) -> pd.Series:
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    chase = frame["chase_permission"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    if policy == "ENTRY_PULLBACK_R1":
        return state.str.contains("PULLBACK") | chase.str.contains("PRIORITY_ENTRY")
    if policy == "ENTRY_BREAKOUT_CONTINUATION_R1":
        return (
            state.str.contains("ACCELERATING|EXTENDED_BUT_VALID", regex=True)
            & chase.str.contains("ALLOW")
            & ~state.str.contains("FIRST_DAY_BREAKOUT")
        )
    return (
        ~chase.str.contains("HOLD_ONLY")
        & ~risk.str.contains("WATCH_ONLY")
        & ~state.str.contains("NO_MOMENTUM")
    )


def size_multiplier(frame: pd.DataFrame, exit_policy: str) -> pd.Series:
    state = frame["momentum_state"].fillna("").astype(str).str.upper()
    risk = frame["risk_size_bucket"].fillna("").astype(str).str.upper()
    regime = frame["market_regime"].fillna("").astype(str).str.upper()
    result = pd.Series(1.0, index=frame.index)
    if exit_policy == "EXIT_FAST_RISK_CONTROL_R1":
        result = result.mask(risk.str.contains("WATCH|SMALL"), 0.5)
        result = result.mask(regime.str.contains("RISK_OFF"), 0.5)
    elif exit_policy == "EXIT_TREND_HOLD_R1":
        result = result.mask(~state.str.contains("LEADER|ACCELERATING"), 0.8)
    else:
        result = result.mask(state.str.contains("EXTENDED|EXHAUST"), 0.7)
    return result


def protected_files(root: Path, output: Path) -> list[Path]:
    paths = []
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or output.resolve() in path.resolve().parents:
                continue
            text = path.as_posix().lower()
            if any(token in text for token in (
                "official", "broker", "protected", "forward_observation_ledger",
                "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
                "outputs/v21/v21_072",
            )):
                paths.append(path.resolve())
    return sorted(set(paths))
